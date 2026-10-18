"""Tests for the robust story engine (docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-
design.md Section 5.3, RST1-RST54 and RST60-RST63): story_engine.py and its integration into
bin/ltx-movie, bin/judge-story and bin/iterate-story.

Run from the workspace root: python3 -m pytest tests/test_story_engine.py
Plain pytest asserts only. Every model call goes to the fake bin/qwen-agent of a temp
workspace (story_engine_testutil.make_ws) or to a monkeypatched seam; no test reaches a model
server, a daemon or the Anthropic API, and every test runs under Section 5.1's environment
(the autouse story_env fixture).
"""

import ast
import contextlib
import importlib.machinery
import inspect
import io
import json
import os
import py_compile
import random
import re
import shlex
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402

story_engine = importlib.machinery.SourceFileLoader(
    "story_engine", os.path.join(WS, "story_engine.py")).load_module()
se = story_engine


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


def _top_level_imports(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module)
    return names


# --- RST1, RST5-RST7, RST25: the module, the agent call, JSON extraction (RS1, RS4-RS6) -----

def test_rst1_module_imports_and_no_top_level_loader():
    path = os.path.join(WS, "story_engine.py")
    assert _top_level_imports(path) == {
        "collections", "copy", "datetime", "hashlib", "importlib.machinery", "json", "os", "re",
        "shlex", "subprocess", "sys", "time", "uuid"}
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            continue
        for sub in ast.walk(node):
            assert not (isinstance(sub, ast.Attribute) and sub.attr == "SourceFileLoader")
    py_compile.compile(path, doraise=True)
    assert "stdlib only; loaded by path by bin/ltx-movie and\nbin/judge-story" in se.__doc__
    assert se._now is se.time.monotonic
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", se._utc())


def test_rs4_constants():
    assert se.SHOT_TYPES == ("extreme wide shot", "wide shot", "medium shot", "medium close-up",
                             "close-up", "extreme close-up")
    assert [k for k, _ in se.CAMERA_SENTENCES] == [
        "static", "slow push-in", "slow pull-back", "slow pan left", "slow pan right",
        "slow tilt up", "slow tilt down", "tracking"]
    assert se.ARC_ROLES == ("introduction", "rising", "climax", "falling", "resolution")
    assert se.WORD_RANGES["chained"] == {"image1": (120, 170), "motion1": (25, 50),
                                         "motion": (15, 35)}
    assert se.MAX_CAST == {"chained": 4, "no_stills": 4, "shots": 2}
    assert (se.PLAN_MAX_CALLS, se.PANEL_MAX_CALLS, se.CRITIC_MAX_ROUNDS,
            se.CRITIC_CALLS_PER_ROUND, se.MAX_PATCHES) == (2, 2, 3, 2, 8)
    assert (se.PANEL_MAX_TOKENS, se.CRITIC_MAX_TOKENS, se.PANEL_TIMEOUT, se.CRITIC_TIMEOUT,
            se.JUDGE_TIMEOUT, se.REQUEST_TIMEOUT, se.MAX_LISTED) == (1536, 4096, 600, 900, 900,
                                                                      600, 40)
    assert (se.plan_max_tokens(14), se.plan_max_tokens(30)) == (4096, 7500)
    assert (se.plan_timeout(6), se.plan_timeout(30)) == (600, 1200)
    assert (se.wall_clock_cap(6), se.wall_clock_cap(30)) == (2400, 5400)
    character_lib = se._character_lib(WS)
    for _key, sentence in se.CAMERA_SENTENCES:
        assert character_lib._is_camera_sentence(sentence), sentence


def test_rst5_agent_cmd(ws):
    ctx = seu.make_ctx(se, ws)
    head = [sys.executable, os.path.join(ws, "bin", "qwen-agent"), "--workspace", ws,
            "--max-tokens", "4096", "--max-rounds", "1", "--request-timeout", "600"]
    assert se.agent_cmd(ctx, "P", max_tokens=4096) == head + ["--user-prompt", "P"]
    tuned = ctx._replace(story_model="andrevp/Qwen", context_window=262144)
    assert se.agent_cmd(tuned, "P", max_tokens=4096) == head + [
        "--model", "andrevp/Qwen", "--context-window", "262144", "--user-prompt", "P"]
    assert se.agent_cmd(ctx, "P", max_tokens=4096, image="/s/seed.png") == head + [
        "--image", "/s/seed.png", "--user-prompt", "P"]
    assert se.agent_cmd(ctx, "P", max_tokens=4096, skill="analyst") == head + [
        "--skill=analyst", "--user-prompt", "P"]
    for cmd in (se.agent_cmd(tuned, "P", max_tokens=1, image="/i", skill="analyst"),):
        assert "--danger-auto-approve" not in cmd


def test_rst6_run_agent(ws, tmp_path, monkeypatch):
    ctx = seu.make_ctx(se, ws)
    log = seu.script_agent(monkeypatch, tmp_path, plan=[
        {"answer": "first"}, {"answer": "forced summary", "status": "max_rounds"},
        {"status": "http_error"}, {"no_envelope": True}, {"sleep": 5, "answer": "late"},
        {"answer": "   "}])
    seen = []
    real_popen = se.subprocess.Popen

    def recording_popen(cmd, **kwargs):
        seen.append(kwargs)
        return real_popen(cmd, **kwargs)

    monkeypatch.setattr(se.subprocess, "Popen", recording_popen)
    prompt = "You are planning a test"
    assert se.run_agent(ctx, prompt, max_tokens=10, timeout=30) == ("ok", "first")
    assert se.run_agent(ctx, prompt, max_tokens=10, timeout=30, preflight_done=True) == (
        "max_rounds", "forced summary")
    assert se.run_agent(ctx, prompt, max_tokens=10, timeout=30) == ("http_error", None)
    assert se.run_agent(ctx, prompt, max_tokens=10, timeout=30) == ("no_envelope", None)
    assert se.run_agent(ctx, prompt, max_tokens=10, timeout=1) == ("timeout", None)
    assert se.run_agent(ctx, prompt, max_tokens=10, timeout=30) == ("ok", None)
    assert all(kw["stdin"] is subprocess.DEVNULL and kw["cwd"] == ws for kw in seen)
    records = seu.agent_log(log)
    assert [r["env_preflight"] for r in records[:2]] == [None, "1"]
    assert records[0]["argv"][-2:] == ["--user-prompt", prompt]


def test_rst7_extract_json():
    assert se.extract_json('{"a": 1}') == {"a": 1}
    assert se.extract_json('Here:\n```json\n{"a": {"b": 2}}\n```\nthanks') == {"a": {"b": 2}}
    assert se.extract_json('Sure! {"a": 1} hope that helps') == {"a": 1}
    assert se.extract_json("```{\"a\": 3}```") == {"a": 3}
    assert se.extract_json("[1, 2]") is None
    assert se.extract_json("{not json}") is None
    assert se.extract_json(None) is None
    assert se.extract_json("no braces at all") is None


def test_parse_violation_shapes():
    assert se.parse_violation("panel 3: N1 word count: Motion: is 41 words; it must be 15-35") == {
        "id": "N1", "name": "word count", "scope": "panel", "index": 3,
        "message": "panel 3: N1 word count: Motion: is 41 words; it must be 15-35"}
    assert se.parse_violation("plan: P5 arc: no beat has arc 'climax'")["scope"] == "plan"
    assert se.parse_violation("story: S1 panel count: expected exactly 4 panels, found 3")[
        "index"] is None
    assert se.parse_violation("panel 2: missing/empty Motion: field") == {
        "id": "V0", "name": "structure", "scope": "story", "index": None,
        "message": "panel 2: missing/empty Motion: field"}


def test_rst25_fleet_lib_contract():
    fleet = se._load_fleet(WS)
    params = list(inspect.signature(fleet.delegate_once).parameters)
    assert params[:4] == ["daemon_url", "skill", "task", "host_id"]
    assert fleet.LOCAL == "@local"
    for name in ("route_candidates", "fetch_view", "daemon_url_from_env"):
        assert callable(getattr(fleet, name))
    assert se._load_fleet(str(os.path.join(WS, "no-such-dir"))) is None
