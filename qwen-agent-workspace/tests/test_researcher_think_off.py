"""Tests for the researcher skill's thinking-off request body (agent/qwen-agent-unsafe).

Run from the workspace root: python3 -m pytest tests/test_researcher_think_off.py -v
No network calls: urllib.request.urlopen is replaced by a recording fake.
"""

import importlib.machinery
import io
import json
import os
import types

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
_SCRIPT_PATH = os.path.join(os.path.dirname(WS), "agent", "qwen-agent-unsafe")
qa = importlib.machinery.SourceFileLoader("qwen_agent_unsafe", _SCRIPT_PATH).load_module()


class _FakeResp:
    def __init__(self, data):
        self._buf = io.BytesIO(data)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._buf.read()


def _capture_body(monkeypatch, skill, think):
    monkeypatch.setattr(qa, "TOOLS", [])
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp(b'{"choices": []}')

    monkeypatch.setattr(qa.urllib.request, "urlopen", fake_urlopen)
    args_ns = types.SimpleNamespace(
        model="m", think=think, skill=skill, max_tokens=10,
        temperature=None, request_timeout=5, api_key=None,
    )
    qa.chat_completion("http://x/v1", [{"role": "user", "content": "hi"}], args_ns)
    return captured["body"]


def test_researcher_default_think_is_off():
    assert qa.SKILL_THINK_TEMP_DEFAULTS["researcher"]["think"] is False


def test_researcher_think_off_sends_reasoning_effort_none(monkeypatch):
    body = _capture_body(monkeypatch, "researcher", False)
    assert body["reasoning_effort"] == "none"
    assert body["chat_template_kwargs"] == {"enable_thinking": False}


def test_researcher_think_on_omits_reasoning_effort(monkeypatch):
    body = _capture_body(monkeypatch, "researcher", True)
    assert "reasoning_effort" not in body


def test_vllm_skills_never_get_reasoning_effort(monkeypatch):
    for skill in (None, "investigator", "analyst", "planner"):
        for think in (False, True):
            body = _capture_body(monkeypatch, skill, think)
            assert "reasoning_effort" not in body


def test_researcher_is_only_ollama_skill():
    assert qa.OLLAMA_SKILLS == ("researcher",)


def test_parse_args_accepts_researcher_skill():
    ns = qa.parse_args(["--skill=researcher", "--user-prompt=x"])
    assert ns.skill == "researcher"


def test_every_skill_role_is_a_cli_choice():
    for skill in qa.SKILL_THINK_TEMP_DEFAULTS:
        assert qa.parse_args(["--skill=%s" % skill, "--user-prompt=x"]).skill == skill
