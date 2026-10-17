"""bin/qwen-agent tests for fleet tracing (tracing spec Section 6.4).

Run from the workspace root: python3 -m pytest tests/test_qwen_agent_tracing.py -v
Loads bin/qwen-agent with importlib.machinery.SourceFileLoader, as
tests/test_qwen_agent_fleet.py does. No model server and no real daemon: in-process runs
fake urllib.request.urlopen and replace setup(); every span goes to an in-process loopback
fake daemon; HOME is a temp directory; QWEN_AGENT_DAEMON_URL (subprocesses) and
qa.FLEET_DAEMON_URL (in-process) always point at a test daemon or a closed port.
"""

import ast
import base64
import builtins
import contextlib
import http.server
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
QA_PATH = os.path.join(WS, "bin", "qwen-agent")
sys.path.insert(0, WS)
import fleet_lib  # noqa: E402
import fleet_testutil as ftu  # noqa: E402

T = "4bf92f3577b34da6a3ce929d0e0e4736"
P = "53995c3f42cd8ad8"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 8
_OK = {"schema": "qwen-agent.oneshot.v1", "status": "ok", "answer": "REMOTE", "error": None,
       "rounds": 1, "tool_calls": []}
_LOCAL_LINE = ('{"schema": "qwen-agent.oneshot.v1", "status": "ok", "answer": "LOCAL", "error": null, '
               '"rounds": 1, "tool_calls": []}\n')


def _load(path=QA_PATH, name="qwen_agent_tracing_under_test"):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _closed_url():
    return "http://127.0.0.1:%d" % ftu.free_port()


@pytest.fixture
def qa(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("QWEN_AGENT_SEARXNG_URL", raising=False)
    monkeypatch.delenv("QWEN_AGENT_TRACE_ID", raising=False)
    monkeypatch.delenv("QWEN_AGENT_PARENT_SPAN", raising=False)
    monkeypatch.setenv("QWEN_AGENT_DAEMON_URL", _closed_url())
    return _load()


@pytest.fixture(autouse=True)
def _reap_processes():
    yield
    ftu.kill_all()


def _skill(name):
    return {"skill": name, "model": "m", "verified": True, "busy": False}


def _view(self_skills, peers):
    return {"schema": "qwen-agentd.peers.v1",
            "self": {"host_id": "mac-local", "role": "agent", "version": "dev", "proto": 1,
                     "discovery": "beacon", "skills": self_skills},
            "peers": [{"host_id": h, "address": "127.0.0.1", "port": 1, "role": "agent", "version": "dev",
                       "proto": 1, "compatible": True, "skills": s, "heard_via": "beacon", "age": 0.1}
                      for h, s in peers]}


class _TraceDaemon(object):
    """In-process loopback fake qwen-agentd (tracing spec 6.4).

    GET /peers -> view (default: a valid empty view); GET /trace?id=<id> -> trace_result with
    its trace_id set to <id> (200), or 404 when trace_result is None; POST /spans -> appends the parsed body to .spans and answers 200
    (mode "ok"), 500 ("error"), or 200 after 5 s ("slow"); POST /delegate -> outcomes[host_id]
    = (outcome, envelope). Every request is recorded in .requests as (method, path, body).
    """

    def __init__(self, view=None, mode="ok", trace_result=None, outcomes=None):
        self.view = view if view is not None else _view([], [])
        self.mode, self.trace_result, self.outcomes = mode, trace_result, outcomes or {}
        self.requests, self.spans = [], []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, raw):
                try:
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except OSError:
                    pass

            def do_GET(self):
                outer.requests.append(("GET", self.path, None))
                if self.path == "/peers":
                    self._send(200, json.dumps(outer.view).encode())
                elif self.path.startswith("/trace?id=") and outer.trace_result is not None:
                    result = dict(outer.trace_result, trace_id=self.path[len("/trace?id="):])
                    self._send(200, json.dumps(result).encode())
                else:
                    self._send(404, b"")

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                outer.requests.append(("POST", self.path, body))
                if self.path == "/spans":
                    outer.spans.append(body)
                    if outer.mode == "slow":
                        time.sleep(5)
                    self._send(500 if outer.mode == "error" else 200, b'{"ok": true}')
                    return
                outcome, envelope = outer.outcomes.get(body.get("host_id"), ("not_live", None))
                self._send(200, json.dumps({"outcome": outcome, "envelope": envelope, "detail": ""}).encode())

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def posts(self, path):
        return [b for m, p, b in self.requests if (m, p) == ("POST", path)]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class _FakeResp(object):
    def __init__(self, data):
        self._buf = io.BytesIO(data)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._buf.read()


class _FakeProc(object):
    """subprocess.Popen stand-in for a local --skill child: records argv and env."""
    calls = []

    def __init__(self, argv, **kwargs):
        _FakeProc.calls.append((argv, kwargs.get("env")))
        self.pid = 999999
        self.returncode = 0

    def communicate(self, timeout=None):
        return _LOCAL_LINE, ""


def _today_argv(qa, args_ns, skill, task, workspace):
    return [sys.executable, os.path.realpath(sys.argv[0]), "--skill=%s" % skill, "--user-prompt=%s" % task,
            "--workspace=%s" % workspace, "--base-url=%s" % args_ns.base_url, "--model=%s" % args_ns.model,
            "--max-tokens", str(args_ns.max_tokens), "--request-timeout", str(args_ns.request_timeout),
            "--max-rounds", str(args_ns.max_rounds), "--tool-timeout", str(args_ns.tool_timeout),
            "--context-window", str(qa.CONTEXT_WINDOW)]


def _reply(content=None, tool_calls=None, usage=None, finish=None):
    """One chat-completions response body."""
    message = {"role": "assistant", "content": content or ""}
    if tool_calls:
        message["tool_calls"] = [{"id": "call_%d" % i, "type": "function",
                                  "function": {"name": name, "arguments": json.dumps(args)}}
                                 for i, (name, args) in enumerate(tool_calls, 1)]
    body = {"choices": [{"index": 0, "message": message,
                         "finish_reason": finish or ("tool_calls" if tool_calls else "stop")}]}
    if usage is not None:
        body["usage"] = {"prompt_tokens": usage[0], "completion_tokens": usage[1], "total_tokens": sum(usage)}
    return body


def _state(qa, monkeypatch, tmp_path, daemon_url, view=None, fleet=True, calculate=False):
    """Module state as main() leaves it, with setup() replaced; returns the workspace path.

    calculate=True adds the calculate tool, which the top level does not advertise (only the
    skill roles do), so that a one-shot named "oneshot" can make an auto-approved call."""
    ws = os.path.realpath(str(tmp_path / "ws"))
    os.makedirs(ws, exist_ok=True)
    loaded = qa._load_fleet_lib() if fleet else None
    monkeypatch.setattr(qa, "FLEET", loaded)
    monkeypatch.setattr(qa, "FLEET_DAEMON_URL", daemon_url)
    targets = loaded.delegate_enum(qa.DELEGATE_TARGETS[None], view) if (loaded and view) else None
    tools = qa.build_tools_for_context(None, targets) + ([qa._CALCULATE_TOOL] if calculate else [])
    monkeypatch.setattr(qa, "TOOLS", tools)
    monkeypatch.setattr(qa, "TOOL_BY_NAME", dict((t["function"]["name"], t) for t in tools))
    monkeypatch.setattr(qa, "setup", lambda args_ns: setattr(qa, "WORKSPACE", qa.Path(ws)))
    _FakeProc.calls = []
    monkeypatch.setattr(qa.subprocess, "Popen", _FakeProc)
    return ws


def _oneshot(qa, monkeypatch, replies, argv=("--user-prompt=go",)):
    """qa.oneshot() in-process; replies are what urlopen returns (dict, bytes) or raises, in order.
    Returns (exit code, stdout, stderr, the chat request bodies)."""
    queue, bodies = list(replies), []

    def fake_urlopen(req, timeout=None):
        bodies.append(json.loads(req.data.decode("utf-8")))
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            raise item()
        return _FakeResp(item if isinstance(item, bytes) else json.dumps(item).encode())

    monkeypatch.setattr(qa.urllib.request, "urlopen", fake_urlopen)
    args_ns = qa.parse_args(list(argv))
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        with pytest.raises(SystemExit) as e:
            qa.oneshot(args_ns)
    return e.value.code, out.getvalue(), err.getvalue(), bodies


# --- TRT20-TRT25, TRT27, TRT28: spans, propagation, the budget (TR40-TR46, TR48, TR49) ---

def test_trt20_constants_and_unchanged_imports(qa):
    assert qa.TRACE_RING_SIZE == 20
    assert qa.TRACE_TURN_BUDGET == 2.0
    assert qa.TRACE_ENV_KEYS == (fleet_lib.TRACE_ENV_ID, fleet_lib.TRACE_ENV_PARENT)
    assert qa.TRACE_USAGE == "usage: /trace [N | TRACE_ID]  (N from 1 to 20 counts back from the last turn)"
    assert qa.TURN_TRACE is None and qa.TRACE_RING == []
    with open(QA_PATH, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module)
    assert names == {"argparse", "ast", "base64", "datetime", "html.parser", "json", "operator", "os", "re",
                     "signal", "subprocess", "sys", "time", "urllib.error", "urllib.parse", "urllib.request",
                     "uuid", "pathlib"}


def test_trt21_oneshot_posts_model_tool_model_turn(qa, monkeypatch, tmp_path):
    replies = [_reply(tool_calls=[("calculate", {"expression": "2+2"})], usage=(11, 3)),
               _reply("four", usage=(13, 5))]
    sink = _TraceDaemon()
    try:
        _state(qa, monkeypatch, tmp_path, sink.url, calculate=True)
        traced = _oneshot(qa, monkeypatch, replies)
        spans = list(sink.spans)
        _state(qa, monkeypatch, tmp_path, sink.url, calculate=True)
        no_usage = _oneshot(qa, monkeypatch, [_reply(tool_calls=[("calculate", {"expression": "2+2"})]),
                                              _reply("four")])
    finally:
        sink.close()
    _state(qa, monkeypatch, tmp_path, None, fleet=False, calculate=True)
    untraced = _oneshot(qa, monkeypatch, replies)
    assert traced[:2] == untraced[:2] == no_usage[:2] and traced[0] == 0
    assert json.loads(traced[1])["answer"] == "four"
    assert [s["kind"] for s in spans] == ["model", "tool", "model", "turn"]
    model1, tool, model2, turn = spans
    assert all(fleet_lib.trace_record_error(s, posted=True) is None for s in spans)
    assert len(set(s["trace_id"] for s in spans)) == 1
    assert turn["parent_span_id"] is None and (turn["name"], turn["status"]) == ("oneshot", "ok")
    assert turn["attrs"] == {"rounds": 2, "tool_calls": 1}
    assert all(s["parent_span_id"] == turn["span_id"] for s in (model1, tool, model2))
    assert model1["attrs"] == {"call": 1, "tools": True, "prompt_tokens": 11, "completion_tokens": 3,
                               "finish_reason": "tool_calls", "http": None}
    assert model2["attrs"] == {"call": 2, "tools": True, "prompt_tokens": 13, "completion_tokens": 5,
                               "finish_reason": "stop", "http": None}
    assert (model1["name"], model1["status"]) == ("qwen38-6bit", "ok")
    assert (tool["name"], tool["status"]) == ("calculate", "ok")
    assert tool["attrs"] == {"round": 1, "decision": "approved", "key": "2+2", "outcome": "OK: 4", "error": False}
    later = sink.spans[len(spans):]
    assert [s["kind"] for s in later] == ["model", "tool", "model", "turn"]
    assert later[0]["attrs"]["prompt_tokens"] is None and later[0]["attrs"]["completion_tokens"] is None
    assert later[0]["trace_id"] != turn["trace_id"]


def test_trt22_delegations_carry_the_tool_span(qa, monkeypatch, tmp_path):
    view = _view([_skill("analyst")], [("p1", [_skill("researcher")])])
    sink = _TraceDaemon(view=view, outcomes={"p1": ("ok", _OK)})
    try:
        _state(qa, monkeypatch, tmp_path, sink.url, view)
        code, _out, _err, _bodies = _oneshot(qa, monkeypatch, [
            _reply(tool_calls=[("delegate_to_skill", {"skill": "researcher", "task": "find x"})]),
            _reply("done")])
        assert code == 0
        [remote_tool] = [s for s in sink.spans if s["kind"] == "tool"]
        trace_id = remote_tool["trace_id"]
        assert remote_tool["attrs"]["key"] == "skill=researcher"
        assert sink.posts("/delegate") == [{"skill": "researcher", "task": "find x", "host_id": "p1",
                                            "trace": {"trace_id": trace_id,
                                                      "parent_span_id": remote_tool["span_id"]}}]
        ws = _state(qa, monkeypatch, tmp_path, sink.url, view)
        code, _out, _err, _bodies = _oneshot(qa, monkeypatch, [
            _reply(tool_calls=[("delegate_to_skill", {"skill": "analyst", "task": "t"})]), _reply("done")])
        assert code == 0
        local_tool = [s for s in sink.spans if s["kind"] == "tool"][-1]
        [(argv, env)] = _FakeProc.calls
        assert env["QWEN_AGENT_TRACE_ID"] == local_tool["trace_id"] != trace_id
        assert env["QWEN_AGENT_PARENT_SPAN"] == local_tool["span_id"]
        assert argv == _today_argv(qa, qa.parse_args(["--user-prompt=go"]), "analyst", "t", ws)
        assert len(sink.posts("/delegate")) == 1
    finally:
        sink.close()
    _state(qa, monkeypatch, tmp_path, None, fleet=False)
    monkeypatch.setenv("QWEN_AGENT_TRACE_ID", T)
    monkeypatch.setenv("QWEN_AGENT_PARENT_SPAN", P)
    monkeypatch.setattr(qa, "WORKSPACE", qa.Path(os.path.realpath(str(tmp_path / "ws"))))
    monkeypatch.setattr(qa, "ONESHOT", True)
    assert qa.exec_delegate_to_skill({"skill": "analyst", "task": "t"}, qa.parse_args(["--user-prompt=go"])) == \
        "LOCAL"
    [(_argv, env)] = _FakeProc.calls
    assert "QWEN_AGENT_TRACE_ID" not in env and "QWEN_AGENT_PARENT_SPAN" not in env


def _run_skill(home, sink_url, stub, extra_env):
    env = ftu.clean_env(home, QWEN_AGENT_DAEMON_URL=sink_url, **extra_env)
    return subprocess.run([sys.executable, QA_PATH, "--skill=researcher", "--user-prompt=x",
                           "--workspace=%s" % os.path.join(str(home), "ws"), "--base-url=%s" % stub.url,
                           "--model=m"], env=env, capture_output=True, text=True, timeout=120)


def test_trt23_child_inherits_a_valid_trace_only(qa, monkeypatch, tmp_path):
    stub = ftu.StubModelServer("vllm", "m", "ANSWER")
    sink = _TraceDaemon()
    try:
        home = tmp_path / "child"
        home.mkdir()
        proc = _run_skill(home, sink.url, stub, {"QWEN_AGENT_TRACE_ID": T, "QWEN_AGENT_PARENT_SPAN": P})
        assert proc.returncode == 0, proc.stderr
        assert [s["kind"] for s in sink.spans] == ["model"]
        assert (sink.spans[0]["trace_id"], sink.spans[0]["parent_span_id"]) == (T, P)
        assert sink.spans[0]["name"] == "m" and sink.spans[0]["attrs"]["prompt_tokens"] == 1
        for bad in (P.upper(), P[:15]):
            del sink.spans[:]
            proc = _run_skill(home, sink.url, stub, {"QWEN_AGENT_TRACE_ID": T, "QWEN_AGENT_PARENT_SPAN": bad})
            assert proc.returncode == 0, proc.stderr
            assert [s["kind"] for s in sink.spans] == ["model", "turn"]
            turn = sink.spans[1]
            assert (turn["name"], turn["parent_span_id"]) == ("researcher", None) and turn["trace_id"] != T
            assert sink.spans[0]["parent_span_id"] == turn["span_id"]
        del sink.spans[:]
        _state(qa, monkeypatch, tmp_path, sink.url)
        monkeypatch.setenv("QWEN_AGENT_TRACE_ID", T)
        monkeypatch.setenv("QWEN_AGENT_PARENT_SPAN", P)
        lines = ["hello"]
        monkeypatch.setattr(builtins, "input", lambda prompt="": lines.pop(0) if lines else (_ for _ in ()).throw(EOFError()))
        monkeypatch.setattr(qa, "print_banner", lambda *a, **k: None)
        monkeypatch.setattr(qa, "run_turn", lambda messages, args_ns, snapshot: {
            "status": "ok", "answer": "hi", "rounds": 1, "tool_calls": [], "error": None})
        with contextlib.redirect_stdout(io.StringIO()), pytest.raises(SystemExit):
            qa.repl(qa.parse_args([]))
        [turn] = sink.spans
        assert (turn["kind"], turn["name"], turn["parent_span_id"]) == ("turn", "repl", None)
        assert turn["trace_id"] != T and qa.TRACE_RING == [turn["trace_id"]]
    finally:
        sink.close()
        stub.stop()


def test_trt24_trt25_a_failing_daemon_never_changes_the_run(tmp_path):
    stub = ftu.StubModelServer("vllm", "m", "ANSWER")
    results = {}
    sinks = {"slow": _TraceDaemon(mode="slow"), "error": _TraceDaemon(mode="error"), "ok": _TraceDaemon()}
    try:
        for name, url in (("closed", _closed_url()), ("slow", sinks["slow"].url),
                          ("error", sinks["error"].url), ("ok", sinks["ok"].url)):
            home = tmp_path / name
            home.mkdir()
            env = ftu.clean_env(home, QWEN_AGENT_DAEMON_URL=url)
            started = time.monotonic()
            proc = subprocess.run([sys.executable, QA_PATH, "--user-prompt=x",
                                   "--workspace=%s" % (home / "ws"), "--base-url=%s" % stub.url, "--model=m"],
                                  env=env, capture_output=True, text=True, timeout=120)
            results[name] = (proc.returncode, proc.stdout, time.monotonic() - started)
        assert len(set((code, out) for code, out, _t in results.values())) == 1
        assert results["ok"][0] == 0 and json.loads(results["ok"][1])["answer"] == "ANSWER"
        assert results["slow"][2] - results["closed"][2] <= 2.5
        assert len(sinks["slow"].posts("/spans")) == 1 and len(sinks["error"].posts("/spans")) == 1
        assert [s["kind"] for s in sinks["ok"].posts("/spans")] == ["model", "turn"]
    finally:
        for sink in sinks.values():
            sink.close()
        stub.stop()
    found = [os.path.join(d, n) for d, _dirs, names in os.walk(str(tmp_path / "closed"))
             for n in names if n.startswith("trace.jsonl")]
    assert found == []


def test_trt27_no_prompt_task_content_answer_or_image_in_any_span(qa, monkeypatch, tmp_path):
    view = _view([_skill("analyst")], [("p1", [_skill("researcher"), _skill("vision")])])
    sink = _TraceDaemon(view=view, outcomes={"p1": ("ok", _OK)})
    try:
        ws = _state(qa, monkeypatch, tmp_path, sink.url, view)
        for name in ("a.png", "b.png"):
            with open(os.path.join(ws, name), "wb") as f:
                f.write(PNG_BYTES)
        code, out, _err, _bodies = _oneshot(qa, monkeypatch, [
            _reply(tool_calls=[
                ("delegate_to_skill", {"skill": "researcher", "task": "TRSENTINEL-TASK"}),
                ("delegate_to_skill", {"skill": "analyst", "task": "TRSENTINEL-TASK"}),
                ("write_file", {"path": "out.txt", "content": "TRSENTINEL-CONTENT"}),
                ("delegate_to_skill", {"skill": "vision", "task": "TRSENTINEL-TASK",
                                       "images": ["a.png", "b.png"]})]),
            _reply("TRSENTINEL-ANSWER")],
            argv=("--user-prompt=TRSENTINEL-PROMPT", "--danger-auto-approve"))
        assert code == 0 and json.loads(out)["answer"] == "TRSENTINEL-ANSWER"
        with open(os.path.join(ws, "out.txt"), encoding="utf-8") as f:
            assert f.read() == "TRSENTINEL-CONTENT"
        assert [b["host_id"] for b in sink.posts("/delegate")] == ["p1", "p1"]
        assert len(_FakeProc.calls) == 1
        tools = [s for s in sink.spans if s["kind"] == "tool"]
        assert [(s["name"], s["status"]) for s in tools] == [("delegate_to_skill", "ok")] * 2 + [
            ("write_file", "ok"), ("delegate_to_skill", "ok")]
        assert [s["attrs"]["key"] for s in tools] == ["skill=researcher", "skill=analyst", "out.txt",
                                                      "skill=vision images=2"]
        blob = json.dumps(sink.posts("/spans"))
        b64 = base64.b64encode(PNG_BYTES).decode("ascii")
        for needle in ("TRSENTINEL", b64, b64[:40], "a.png", "b.png", "LOCAL", "REMOTE"):
            assert needle not in blob, needle
    finally:
        sink.close()


def test_trt28_model_span_status_for_every_transport_failure(qa, monkeypatch, tmp_path):
    def http_500():
        return urllib.error.HTTPError("http://x/v1/chat/completions", 500, "Internal Server Error", {},
                                      io.BytesIO(b"model exploded"))

    cases = ((http_500, "http_error", 500), (urllib.error.URLError("refused"), "network_error", None),
             (b"not json", "malformed_response", None), (KeyboardInterrupt(), "interrupted", None))
    for failure, status, http in cases:
        sink = _TraceDaemon()
        try:
            _state(qa, monkeypatch, tmp_path, sink.url)
            traced = _oneshot(qa, monkeypatch, [failure])
        finally:
            sink.close()
        _state(qa, monkeypatch, tmp_path, None, fleet=False)
        untraced = _oneshot(qa, monkeypatch, [failure])
        assert traced[:3] == untraced[:3], status
        assert [s["kind"] for s in sink.spans] == ["model", "turn"]
        model, turn = sink.spans
        assert (model["status"], model["attrs"]["http"]) == (status, http)
        assert turn["status"] == json.loads(traced[1])["status"]
        if http == 500:
            assert "[server error 500] model exploded\n" in traced[2]


# --- TRT26 and the /help line: /trace in the REPL (TR47) ----------------------------------

_HELP_LINE = "  /trace      Show a turn's trace: /trace (last turn), /trace N (N turns back), /trace <id>"


def _canned():
    """A valid GET /trace?id= result with one turn record; the fake daemon sets its trace_id."""
    turn = fleet_lib.make_record(T, "1000000000000001", None, "mac-local", "turn", "repl", 1760000000.0, 0.0,
                                 "ok", {"rounds": 1, "tool_calls": 0}, now=1.5)
    return {"schema": fleet_lib.TRACE_SCHEMA, "trace_id": T, "records": [turn], "missing": [], "truncated": []}


def _repl(qa, monkeypatch, lines, run_turn=None):
    """qa.repl() over scripted input lines; run_turn is faked unless given. Returns stdout."""
    feed = list(lines)

    def fake_input(prompt=""):
        if not feed:
            raise EOFError
        return feed.pop(0)

    monkeypatch.setattr(builtins, "input", fake_input)
    monkeypatch.setattr(qa, "print_banner", lambda *a, **k: None)
    monkeypatch.setattr(qa, "memory_checkpoint", lambda *a, **k: None)
    monkeypatch.setattr(qa, "TRACE_RING", [])
    if run_turn is None:
        monkeypatch.setattr(qa, "run_turn", lambda messages, args_ns, snapshot: {
            "status": "ok", "answer": "hi %d" % len(messages), "rounds": 1, "tool_calls": [], "error": None})
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        with pytest.raises(SystemExit):
            qa.repl(qa.parse_args([]))
    return out.getvalue()


def test_trt20_help_lists_trace(qa):
    lines = qa.HELP_TEXT.splitlines()
    i = [n for n, line in enumerate(lines) if line.startswith("  /remember")][0]
    assert lines[i + 1] == _HELP_LINE


def test_trt26_slash_trace(qa, monkeypatch, tmp_path):
    sink = _TraceDaemon(trace_result=_canned())
    other = "5" * 32
    try:
        _state(qa, monkeypatch, tmp_path, sink.url)
        out = _repl(qa, monkeypatch, ["/trace", "hello", "/trace", "/trace 1", "/trace 2", "/trace 21",
                                      "/trace 0", "/trace xyz", "/trace   %s  " % other])
        [turn] = sink.posts("/spans")
        ring_id = turn["trace_id"]
        tree = "\n".join(qa.FLEET.render_trace(dict(_canned(), trace_id=ring_id))) + "\n"
        tree_other = "\n".join(qa.FLEET.render_trace(dict(_canned(), trace_id=other))) + "\n"
        usage = qa.TRACE_USAGE + "\n"
        assert out == ("no turns in this session yet\n" + "hi 2\n" + tree + tree +
                       "only 1 turn in this session\n" + usage * 3 + tree_other + "\n")
        gets = [p for m, p, _b in sink.requests if m == "GET" and p.startswith("/trace")]
        assert gets == ["/trace?id=" + ring_id] * 2 + ["/trace?id=" + other]
        sink.trace_result = None
        out = _repl(qa, monkeypatch, ["hello", "/trace"])
        assert out == "hi 2\nthe daemon at %s has no trace support (http 404)\n\n" % sink.url
        sink.trace_result = _canned()
        out = _repl(qa, monkeypatch, ["hello"] * 25)
        turn_ids = [s["trace_id"] for s in sink.posts("/spans")[-25:]]
        assert len(set(turn_ids)) == 25 and qa.TRACE_RING == turn_ids[-20:]
        traced_turns = out
    finally:
        sink.close()
    closed = _closed_url()
    _state(qa, monkeypatch, tmp_path, closed)
    assert _repl(qa, monkeypatch, ["hello", "/trace"]) == "hi 2\ndaemon not reachable at %s\n\n" % closed
    monkeypatch.setattr(qa, "FLEET_DAEMON_URL", None)
    assert _repl(qa, monkeypatch, ["/trace"]) == "tracing is off: QWEN_AGENT_DAEMON_URL is not usable\n\n"
    _state(qa, monkeypatch, tmp_path, None, fleet=False)
    assert _repl(qa, monkeypatch, ["hello", "/trace"]) == "hi 2\ntracing is off: fleet_lib.py is not available\n\n"
    assert _repl(qa, monkeypatch, ["hello"] * 25) == traced_turns
    assert qa.TRACE_RING == []


def test_tracing_focus_3_an_interrupted_repl_turn_is_still_traced(qa, monkeypatch, tmp_path):
    """Review Focus 3: Ctrl-C while the model is answering a REPL turn. Expected: the turn
    still gets a trace (its model span and turn span say "interrupted"), the next turn gets a
    new trace, and /trace 2 reaches the interrupted one."""
    sink = _TraceDaemon(trace_result=_canned())
    try:
        _state(qa, monkeypatch, tmp_path, sink.url)
        replies = [KeyboardInterrupt(), _reply("second answer")]
        monkeypatch.setattr(qa.urllib.request, "urlopen",
                            lambda req, timeout=None: (_ for _ in ()).throw(replies.pop(0))
                            if isinstance(replies[0], BaseException) else _FakeResp(json.dumps(replies.pop(0)).encode()))
        out = _repl(qa, monkeypatch, ["first", "second", "/trace 2"], run_turn=qa.run_turn)
        spans = sink.posts("/spans")
        assert [(s["kind"], s["status"]) for s in spans] == [("model", "interrupted"), ("turn", "interrupted"),
                                                             ("model", "ok"), ("turn", "ok")]
        first, second = spans[1]["trace_id"], spans[3]["trace_id"]
        assert first != second and qa.TRACE_RING == [first, second]
        assert spans[0]["trace_id"] == first and spans[0]["parent_span_id"] == spans[1]["span_id"]
        assert out.startswith("second answer\n")
        assert [p for m, p, _b in sink.requests if m == "GET" and p.startswith("/trace")] == ["/trace?id=" + first]
    finally:
        sink.close()
