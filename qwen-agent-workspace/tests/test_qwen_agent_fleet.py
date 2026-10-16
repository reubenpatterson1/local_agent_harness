"""bin/qwen-agent tests for the researcher port and fleet routing (fleet spec 11.4, D7).

Run from the workspace root: python3 -m pytest tests/test_qwen_agent_fleet.py -v
Loads bin/qwen-agent with importlib.machinery.SourceFileLoader, as
tests/test_qwen_agent_context_budget.py does. No model server and no real daemon:
every chat_completion goes to a recording fake, and every fleet view comes from an
in-process loopback fake daemon. QWEN_AGENT_DAEMON_URL is always set by the test,
so a qwen-agentd running on this machine is never contacted.
"""

import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import types

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
QA_PATH = os.path.join(WS, "bin", "qwen-agent")
UNSAFE_PATH = os.path.join(os.path.dirname(WS), "agent", "qwen-agent-unsafe")


def _load(path=QA_PATH, name="qwen_agent_fleet_under_test"):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def qa(monkeypatch):
    monkeypatch.delenv("QWEN_AGENT_SEARXNG_URL", raising=False)
    return _load()


class _FakeResp(object):
    def __init__(self, data):
        self._buf = io.BytesIO(data)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._buf.read()


def _chat_body(qa, monkeypatch, **ns):
    monkeypatch.setattr(qa, "TOOLS", [])
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp(b'{"choices": []}')

    monkeypatch.setattr(qa.urllib.request, "urlopen", fake_urlopen)
    fields = dict(model="m", think=False, max_tokens=10, temperature=None, request_timeout=5,
                  api_key=None)
    fields.update(ns)
    qa.chat_completion("http://x/v1", [{"role": "user", "content": "hi"}], types.SimpleNamespace(**fields))
    return captured["body"]


class _Stop(Exception):
    pass


def _run_main(qa, monkeypatch, argv, load_fleet=None):
    """Run qa.main() with argv; oneshot/repl are replaced and record args_ns."""
    seen = {}

    def capture(args_ns):
        seen["args_ns"] = args_ns
        raise _Stop()

    monkeypatch.setattr(qa, "oneshot", capture)
    monkeypatch.setattr(qa, "repl", capture)
    if load_fleet is not None:
        monkeypatch.setattr(qa, "_load_fleet_lib", load_fleet, raising=False)
    monkeypatch.setattr(sys, "argv", ["qwen-agent"] + list(argv))
    with pytest.raises(_Stop):
        qa.main()
    return seen["args_ns"]


# --- T30-T34: the researcher port, --model-server-type, SearXNG override (F71-F77, F79) ---

def test_t30_researcher_constants_and_prompt(qa):
    assert qa.SKILL_TOOL_NAMES["researcher"] == ("search", "fetch_url", "read_file", "calculate")
    assert qa.DELEGATE_TARGETS[None] == ("investigator", "analyst", "planner", "researcher")
    assert qa.DELEGATE_TARGETS["investigator"] == ("analyst", "researcher")
    assert set(qa.DELEGATE_TARGETS) == {None, "investigator"}
    assert qa.SKILL_THINK_TEMP_DEFAULTS["researcher"] == {"think": False, "temperature": 0.7}
    unsafe = _load(UNSAFE_PATH, "qwen_agent_unsafe_for_prompt")
    assert qa.SKILL_SYSTEM_PROMPTS["researcher"] == unsafe.SKILL_SYSTEM_PROMPTS["researcher"]
    assert "{workspace}" in qa.SKILL_SYSTEM_PROMPTS["researcher"]
    with open(QA_PATH, encoding="utf-8") as f:
        source = f.read()
    for name in ("SKILL_ENDPOINT", "SKILL_MODEL_", "OLLAMA_SKILLS", "SKILL_ENDPOINT_OVERRIDES"):
        assert name not in source, name


def test_t31_skill_tools_are_all_auto_approved(qa):
    gated = ("bash", "write_file", "run_python", "generate_image", "promote")
    for skill in ("investigator", "analyst", "planner", "researcher"):
        for name in qa.SKILL_TOOL_NAMES[skill]:
            assert name in qa.AUTO_APPROVE_TOOLS, (skill, name)
            assert name not in gated
    names = [t["function"]["name"] for t in qa.build_tools_for_context("researcher")]
    assert sorted(names) == ["calculate", "fetch_url", "read_file", "search"]


def test_t32_researcher_cli_defaults(qa, monkeypatch):
    args_ns = qa.parse_args(["--skill=researcher", "--user-prompt=x"])
    assert args_ns.skill == "researcher" and args_ns.model_server_type == "vllm"
    args_ns = _run_main(qa, monkeypatch, ["--skill=researcher", "--user-prompt=x"],
                        load_fleet=lambda: None)
    assert args_ns.think is False and args_ns.temperature == 0.7
    assert qa.parse_args(["--model-server-type=ollama"]).model_server_type == "ollama"
    with pytest.raises(SystemExit) as e:
        qa.parse_args(["--model-server-type=bogus"])
    assert e.value.code == 2


def test_t33_reasoning_effort_only_for_ollama_think_off(qa, monkeypatch):
    body = _chat_body(qa, monkeypatch, model_server_type="ollama", think=False)
    assert body["reasoning_effort"] == "none"
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "reasoning_effort" not in _chat_body(qa, monkeypatch, model_server_type="ollama", think=True)
    today = {"model", "messages", "tools", "tool_choice", "chat_template_kwargs", "max_tokens",
             "temperature", "top_p", "stream"}
    for think in (False, True):
        assert set(_chat_body(qa, monkeypatch, model_server_type="vllm", think=think)) == today
    assert set(_chat_body(qa, monkeypatch, think=False)) == today


def test_t34_searxng_url_override(monkeypatch):
    monkeypatch.setenv("QWEN_AGENT_SEARXNG_URL", " http://10.0.0.5:8888/ ")
    assert _load().SEARXNG_BASE_URL == "http://10.0.0.5:8888"
    for value in ("", "   "):
        monkeypatch.setenv("QWEN_AGENT_SEARXNG_URL", value)
        assert _load().SEARXNG_BASE_URL == "http://127.0.0.1:8888"
    monkeypatch.delenv("QWEN_AGENT_SEARXNG_URL")
    assert _load().SEARXNG_BASE_URL == "http://127.0.0.1:8888"


# --- T35-T39: fleet routing in bin/qwen-agent (F63, F64, F69, F70, F78) -----------------

import http.server  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402

_OK = {"schema": "qwen-agent.oneshot.v1", "status": "ok", "answer": "REMOTE", "error": None,
       "rounds": 1, "tool_calls": []}
_LOCAL_LINE = ('{"schema": "qwen-agent.oneshot.v1", "status": "ok", "answer": "LOCAL", "error": null, '
               '"rounds": 1, "tool_calls": []}\n')


def _closed_url():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return "http://127.0.0.1:%d" % port


def _skill(name, verified=True):
    return {"skill": name, "model": "m", "verified": verified, "busy": False}


def _view(self_skills, peers):
    return {"schema": "qwen-agentd.peers.v1",
            "self": {"host_id": "mac-local", "role": "agent", "version": "dev", "proto": 1,
                     "discovery": "beacon", "skills": self_skills},
            "peers": [{"host_id": h, "address": "127.0.0.1", "port": 1, "role": "agent", "version": "dev",
                       "proto": 1, "compatible": True, "skills": s, "heard_via": "beacon", "age": 0.1}
                      for h, s in peers]}


class _FakeDaemon(object):
    """Loopback fake qwen-agentd: GET /peers -> view (or a scripted status/body);
    POST /delegate -> outcomes[host_id] = (outcome, envelope). Records every request."""

    def __init__(self, view=None, outcomes=None, peers_status=200, peers_body=None):
        self.view, self.outcomes = view, outcomes or {}
        self.peers_status, self.peers_body = peers_status, peers_body
        self.requests = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, raw):
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                outer.requests.append(("GET", self.path, None))
                raw = outer.peers_body if outer.peers_body is not None else json.dumps(outer.view).encode()
                self._send(outer.peers_status, raw)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                outer.requests.append(("POST", self.path, body))
                outcome, envelope = outer.outcomes.get(body["host_id"], ("not_live", None))
                self._send(200, json.dumps({"outcome": outcome, "envelope": envelope, "detail": ""}).encode())

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def delegate_bodies(self):
        return [b for m, p, b in self.requests if (m, p) == ("POST", "/delegate")]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class _FakeProc(object):
    calls = []

    def __init__(self, argv, **kwargs):
        _FakeProc.calls.append(argv)
        self.pid = 999999
        self.returncode = 0

    def communicate(self, timeout=None):
        return _LOCAL_LINE, ""


def _prepare_delegation(qa, monkeypatch, tmp_path, daemon_url, argv=("--user-prompt=x",)):
    """Module state as main() leaves it, without running a turn: fleet loaded, tools built."""
    _FakeProc.calls = []
    monkeypatch.setattr(qa.subprocess, "Popen", _FakeProc)
    monkeypatch.setattr(qa, "ONESHOT", True)
    monkeypatch.setattr(qa, "WORKSPACE", str(tmp_path))
    monkeypatch.setattr(qa, "FLEET", qa._load_fleet_lib())
    monkeypatch.setattr(qa, "FLEET_DAEMON_URL", daemon_url)
    tools = qa.build_tools_for_context(None)
    monkeypatch.setattr(qa, "TOOLS", tools)
    monkeypatch.setattr(qa, "TOOL_BY_NAME", {t["function"]["name"]: t for t in tools})
    return qa.parse_args(list(argv))


def _today_argv(qa, args_ns, skill, task, workspace):
    return [sys.executable, os.path.realpath(sys.argv[0]), "--skill=%s" % skill, "--user-prompt=%s" % task,
            "--workspace=%s" % workspace, "--base-url=%s" % args_ns.base_url, "--model=%s" % args_ns.model,
            "--max-tokens", str(args_ns.max_tokens), "--request-timeout", str(args_ns.request_timeout),
            "--max-rounds", str(args_ns.max_rounds), "--tool-timeout", str(args_ns.tool_timeout),
            "--context-window", str(qa.CONTEXT_WINDOW)]


def test_t35_no_daemon_and_no_fleet_lib_behave_as_today(qa, monkeypatch, tmp_path):
    lone_bin = tmp_path / "lone" / "bin"
    lone_bin.mkdir(parents=True)
    shutil.copy(QA_PATH, str(lone_bin / "qwen-agent"))
    lone = _load(str(lone_bin / "qwen-agent"), "qwen_agent_lone")
    assert lone._load_fleet_lib() is None
    _run_main(lone, monkeypatch, ["--user-prompt=x"])
    assert lone.TOOLS == lone.build_tools_for_context(None) and lone.FLEET is None
    _run_main(lone, monkeypatch, ["--skill=investigator", "--user-prompt=x"])
    assert lone.TOOLS == lone.build_tools_for_context("investigator")

    closed = _closed_url()
    fleet = qa._load_fleet_lib()
    assert fleet is not None and fleet.fetch_view(closed) == (None, None)
    args_ns = _prepare_delegation(qa, monkeypatch, tmp_path, closed)
    result = qa.exec_delegate_to_skill({"skill": "researcher", "task": "t"}, args_ns)
    assert result == "LOCAL"
    assert _FakeProc.calls == [_today_argv(qa, args_ns, "researcher", "t", str(tmp_path))]

    assert qa._envelope_to_result("analyst", {"status": "ok", "answer": "yes"}) == "yes"
    assert qa._envelope_to_result("analyst", {"status": "ok", "answer": ""}) == \
        "(the analyst skill produced no answer)"
    assert qa._envelope_to_result("analyst", {"status": "max_rounds", "answer": "part", "error": "cap"}) == \
        "ERROR: the analyst skill ended with status 'max_rounds': cap\n\n[partial answer before the failure]\npart"
    assert qa._envelope_to_result("analyst", {"status": "http_error", "answer": None}) == \
        "ERROR: the analyst skill ended with status 'http_error': no error detail"
    with open(QA_PATH, encoding="utf-8") as f:
        source = f.read()
    assert "fleet.env" not in source and "QWEN_AGENT_FLEET_TOKEN" not in source


def test_t36_remote_routing_and_failover(qa, monkeypatch, tmp_path, capsys):
    local = _FakeDaemon(view=_view([_skill("researcher")], [("p1", [_skill("researcher")])]))
    try:
        args_ns = _prepare_delegation(qa, monkeypatch, tmp_path, local.url)
        assert qa.exec_delegate_to_skill({"skill": "researcher", "task": "t"}, args_ns) == "LOCAL"
        assert local.delegate_bodies() == [] and len(_FakeProc.calls) == 1
    finally:
        local.close()

    remote = _FakeDaemon(view=_view([], [("a", [_skill("researcher")]), ("b", [_skill("researcher")])]),
                         outcomes={"a": ("busy", None), "b": ("ok", _OK)})
    try:
        args_ns = _prepare_delegation(qa, monkeypatch, tmp_path, remote.url)
        assert qa.exec_delegate_to_skill({"skill": "researcher", "task": "find x"}, args_ns) == "REMOTE"
        assert remote.delegate_bodies() == [{"skill": "researcher", "task": "find x", "host_id": "a"},
                                            {"skill": "researcher", "task": "find x", "host_id": "b"}]
        assert _FakeProc.calls == []
        err = capsys.readouterr().err
        assert "[delegating to researcher on a, up to 900s...]" in err
        assert "[researcher on a failed: busy]" in err
        assert "[delegating to researcher on b, up to 900s...]" in err

        remote.outcomes = {"a": ("busy", None), "b": ("timeout", None)}
        assert qa.exec_delegate_to_skill({"skill": "researcher", "task": "t2"}, args_ns) == \
            "ERROR: no live host serves 'researcher' (tried: a: busy; b: timeout)"
        partial = dict(_OK, status="max_rounds", answer="half", error="cap")
        remote.outcomes = {"a": ("ok", partial)}
        assert qa.exec_delegate_to_skill({"skill": "researcher", "task": "t3"}, args_ns) == \
            qa._envelope_to_result("researcher", partial)
        remote.view = _view([], [])
        assert qa.exec_delegate_to_skill({"skill": "researcher", "task": "t4"}, args_ns) == \
            "ERROR: no live host serves 'researcher'"

        remote.view = _view([], [("a", [_skill("researcher")])])

        def interrupted(*args):
            raise KeyboardInterrupt
        monkeypatch.setattr(qa.FLEET, "delegate_once", interrupted)
        assert qa.exec_delegate_to_skill({"skill": "researcher", "task": "t5"}, args_ns) == (
            "ERROR: execution was interrupted by the user before the researcher skill finished on a. "
            "The remote run may still be in progress there.")
    finally:
        remote.close()


def test_t37_startup_enum_and_fleet_banner(qa, monkeypatch, capsys):
    daemon = _FakeDaemon(view=_view([_skill("analyst")], [("p1", [_skill("researcher")])]))
    try:
        monkeypatch.setenv("QWEN_AGENT_DAEMON_URL", daemon.url)
        _run_main(qa, monkeypatch, ["--user-prompt=x"])
        enum = qa.TOOL_BY_NAME["delegate_to_skill"]["function"]["parameters"]["properties"]["skill"]["enum"]
        assert enum == ["analyst", "researcher"]
        assert "[fleet:" not in capsys.readouterr().err
        _run_main(qa, monkeypatch, ["--skill=investigator", "--user-prompt=x"])
        enum = qa.TOOL_BY_NAME["delegate_to_skill"]["function"]["parameters"]["properties"]["skill"]["enum"]
        assert enum == ["analyst", "researcher"]
        daemon.view = _view([], [])
        _run_main(qa, monkeypatch, ["--skill=investigator", "--user-prompt=x"])
        assert "delegate_to_skill" not in qa.TOOL_BY_NAME
        daemon.view = _view([_skill("planner")], [("p1", [_skill("researcher")])])
        _run_main(qa, monkeypatch, [])
        assert capsys.readouterr().err == (
            "[fleet: qwen-agentd at %s; 1 live peer(s); delegate targets: planner, researcher]\n" % daemon.url)
    finally:
        daemon.close()


def test_t38_bad_daemon_url_or_view_falls_back(qa, monkeypatch, tmp_path, capsys):
    daemon = _FakeDaemon(view=_view([], []))
    try:
        bad = "http://192.168.1.5:%d" % daemon.httpd.server_address[1]
        monkeypatch.setenv("QWEN_AGENT_DAEMON_URL", bad)
        _run_main(qa, monkeypatch, ["--user-prompt=x"])
        assert capsys.readouterr().err == (
            "qwen-agent: warning: ignoring QWEN_AGENT_DAEMON_URL=%s: it must be http://127.0.0.1:<port>; "
            "fleet routing disabled\n" % bad)
        assert daemon.requests == []
        enum = qa.TOOL_BY_NAME["delegate_to_skill"]["function"]["parameters"]["properties"]["skill"]["enum"]
        assert enum == list(qa.DELEGATE_TARGETS[None])
    finally:
        daemon.close()
    warning = ("qwen-agent: warning: qwen-agentd at %s returned an unrecognized fleet view; "
               "fleet routing disabled\n")
    for kwargs in ({"peers_body": b'{"schema": "nope"}'}, {"peers_status": 403, "peers_body": b""}):
        daemon = _FakeDaemon(**kwargs)
        try:
            monkeypatch.setenv("QWEN_AGENT_DAEMON_URL", daemon.url)
            _run_main(qa, monkeypatch, ["--user-prompt=x"])
            assert capsys.readouterr().err == warning % daemon.url
            args_ns = _prepare_delegation(qa, monkeypatch, tmp_path, daemon.url)
            assert qa.exec_delegate_to_skill({"skill": "analyst", "task": "t"}, args_ns) == "LOCAL"
            assert capsys.readouterr().err == (warning % daemon.url) + "[delegating to analyst, up to 900s...]\n"
            assert daemon.delegate_bodies() == []
        finally:
            daemon.close()


def test_t39_model_server_type_forwarded_to_local_children(qa, monkeypatch, tmp_path):
    closed = _closed_url()
    for argv, expect in ((["--user-prompt=x", "--model-server-type=ollama", "--api-key=k"], True),
                         (["--user-prompt=x", "--api-key=k"], False)):
        args_ns = _prepare_delegation(qa, monkeypatch, tmp_path, closed, argv)
        qa.exec_delegate_to_skill({"skill": "analyst", "task": "t"}, args_ns)
        child = _FakeProc.calls[-1]
        assert ("--model-server-type=ollama" in child) is expect
        if expect:
            assert child.index("--model-server-type=ollama") < child.index("--api-key=k")
        assert not any(a.startswith("--model-server-type=vllm") for a in child)
