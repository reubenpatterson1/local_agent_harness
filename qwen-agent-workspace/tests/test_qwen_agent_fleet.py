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
