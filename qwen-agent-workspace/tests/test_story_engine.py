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


NOISY_AGENT = ("#!/usr/bin/env python3\n"
               "import sys\n"
               "sys.stderr.write('qwen-agent: http://127.0.0.1:8000/v1/models returned HTTP 503.\\n')\n"
               "sys.exit(2)\n")


def test_rst5b_run_agent_reports_stderr_when_there_is_no_answer(tmp_path, capsys):
    ws = seu.make_ws(tmp_path)
    with open(os.path.join(ws, "bin", "qwen-agent"), "w") as f:
        f.write(NOISY_AGENT)
    ctx = seu.make_ctx(se, ws)
    assert se.run_agent(ctx, "p", max_tokens=10, timeout=60) == ("no_envelope", None)
    assert capsys.readouterr().out == (
        "Warning: bin/qwen-agent gave no answer (no_envelope); the last lines of its stderr:\n"
        "  qwen-agent: http://127.0.0.1:8000/v1/models returned HTTP 503.\n")


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


# --- RST8, RST9, RST13-RST15, LCT6b: the plan (RS7, RS9-RS11, LC6) ------------------------

def _cast_members(story_env, *names):
    lib = story_env["lib"]
    if "kyra" in names:
        seu.kyra(lib)
    if "ronin" in names:
        seu.ronin(lib)
    return se._character_lib(WS).resolve_cast([(None, n) for n in names])


def _three_entry_catalog(tmp_path):
    files = str(tmp_path / "files")
    return {"schema_version": 1, "entries": [
        seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style",
                          triggers=["grainfilm"]),
        seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion", triggers=["fastmo"],
                          use_when="a chase", avoid_when="a still scene"),
        seu.catalog_entry(seu.lora_file(files, "ink"), "ink-stills", kind="style",
                          target="stills", base_models=[seu.STILLS_MODEL])]}


def test_rst8_plan_prompt_matrix(ws, tmp_path, story_env):
    members = _cast_members(story_env, "kyra", "ronin")
    catalog = _three_entry_catalog(tmp_path)
    for mode in ("chained", "no_stills", "shots"):
        for cast in ([], members):
            for state in ("empty", "catalog", "off"):
                for seed in ((None, "/s/seed_downscaled.png") if mode == "chained" else (None,)):
                    ctx = seu.make_ctx(se, ws, mode=mode, members=cast, seed_agent_image=seed,
                                       catalog=catalog if state == "catalog" else
                                       {"schema_version": 1, "entries": []},
                                       auto_lora=state != "off")
                    prompt = se.build_plan_prompt(ctx, se.compatible_entries(ctx), [])
                    where = (mode, len(cast), state, seed)
                    assert "{" not in prompt and "}" not in prompt, where
                    assert "@@" not in prompt, where
                    assert prompt.startswith(
                        'You are planning a short narrated movie (story-id "s1").\n'), where
                    assert prompt.endswith(se.NO_TOOL_SENTENCE), where
                    assert "do NOT run run_python or any other tool to check it" in prompt
                    assert ("This movie has no stills, so stills stays empty." in prompt) == (
                        mode == "no_stills" and state == "catalog"), where
                    assert ("An image is attached to this message." in prompt) == bool(seed)
                    assert ("LoRA catalog (pick only from these):" in prompt) == (state == "catalog")
                    if cast:
                        assert ('\n- id c1, phrase "the woman in grey", descriptor "%s"'
                                % seu.DESC_K) in prompt
                        assert '\n- id c2, phrase "the ronin", descriptor "%s"' % seu.DESC_R in prompt
                    else:
                        assert "already cast" not in prompt
                    if state == "catalog":
                        assert ("- ink-stills: style LoRA for stills" in prompt) == (
                            mode != "no_stills")
                        assert ("- fast-motion: motion LoRA for video, default strength 0.8, "
                                "range 0.5 to 1.0. a test LoRA. Use when: a chase. Avoid when: "
                                "a still scene.") in prompt
    ctx = seu.make_ctx(se, ws, mode="shots", panels=14, goal="the most realistic action")
    prompt = se.build_plan_prompt(ctx, [], [])
    assert "\n\nThe target output goal is the most realistic action.\n\nHow this movie is made: it " \
           "is a sequence of separate shots joined by cuts, 6 seconds each." in prompt
    assert "beats: a list of EXACTLY 14 objects" in prompt
    assert "at most 2. speaker is the id of the one character who says something aloud" in prompt
    assert "Rules for this movie: two people never touch on screen." in prompt
    assert "loras: " + se.LORA_EMPTY_PARAGRAPH + "\n" in prompt
    pins = [{"path": "/p/a.safetensors", "strength": 1.0, "catalog_id": None, "kind": None},
            {"path": "/p/b.safetensors", "strength": 0.6, "catalog_id": "film-grain",
             "kind": "style"}]
    ctx = seu.make_ctx(se, ws, catalog=catalog, panels=2)
    prompt = se.build_plan_prompt(ctx, se.compatible_entries(ctx), pins)
    assert prompt.count("\n- ") >= 4
    assert ("\nAlready applied to every panel by the user, not to be picked again:\n- a LoRA "
            "outside the catalog at strength 1.0\n- film-grain (style) at strength 0.6\n\n") in prompt
    assert "the first beat is introduction and the last is resolution." in prompt
    assert "arc is one of introduction, rising, climax, falling, resolution, in story order; " \
           "use climax." in se.build_plan_prompt(seu.make_ctx(se, ws, panels=1), [], [])


def test_rst9_narrative_is_inserted_verbatim(ws):
    ctx = seu.make_ctx(se, ws, narrative="Count @@PANELS@@ and @@STORY_ID@@ {x}.")
    prompt = se.build_plan_prompt(ctx, [], [])
    assert "Narrative to adapt:\nCount @@PANELS@@ and @@STORY_ID@@ {x}.\n" in prompt
    assert "EXACTLY 3 objects" in prompt


def test_rst13_normalization(ws, story_env, tmp_path):
    members = _cast_members(story_env, "kyra", "ronin")
    catalog = _three_entry_catalog(tmp_path)
    pins = [{"path": "/p/a.safetensors", "strength": 1.0, "catalog_id": None, "kind": None}]
    ctx = seu.make_ctx(se, ws, mode="shots", members=members, catalog=catalog, pinned=pins)
    raw = seu.plan_json("shots", 3, cast=[
        {"id": "c2", "phrase": "the swordsman", "descriptor": "a man"},
        {"id": "c3", "phrase": "  the   bandit ", "descriptor": seu.MONK + "."}],
        surprise="dropped", locations=[{"id": "l1", "setting": "The setting is a forest " * 3}])
    raw["loras"] = {"global": [{"id": "film-grain"}], "per_beat": {"2": [{"id": "fast-motion",
                                                                          "strength": 0.7}]}}
    plan, shape = se.normalize_plan(ctx, raw)
    assert shape == []
    assert [c["id"] for c in plan["cast"]] == ["c1", "c2", "c3"]
    assert plan["cast"][0] == {"id": "c1", "phrase": "the woman in grey", "descriptor": seu.DESC_K,
                               "cast_name": "kyra"}
    assert plan["cast"][1] == {"id": "c2", "phrase": "the ronin", "descriptor": seu.DESC_R,
                               "cast_name": "ronin"}
    assert plan["cast"][2] == {"id": "c3", "phrase": "the bandit", "descriptor": seu.MONK,
                               "cast_name": None}
    assert plan["locations"][0]["setting"] == ("The setting is a forest The setting is a forest "
                                               "The setting is a forest.")
    assert "surprise" not in plan
    assert [b["speaker"] for b in plan["beats"]] == ["", "", ""] and plan["speech_notes"] == []
    assert list(plan)[-1] == "speech_notes" and list(plan["beats"][0])[-1] == "speaker"
    assert list(plan)[:10] == ["schema", "story_id", "mode", "panels", "seconds", "narrative",
                               "goal", "seed_image", "video_model", "auto_lora"]
    assert plan["loras"] == {"global": [{"id": "film-grain", "strength": 0.8}],
                             "per_beat": {"2": [{"id": "fast-motion", "strength": 0.7}]},
                             "stills": [], "pinned": pins}
    off, _ = se.normalize_plan(ctx._replace(auto_lora=False), raw)
    assert off["loras"] == {"global": [], "per_beat": {}, "stills": [], "pinned": pins}
    raw.pop("loras")
    assert se.normalize_plan(ctx, raw)[0]["loras"]["global"] == []
    broken, shape = se.normalize_plan(seu.make_ctx(se, ws), {"title": 5, "cast": "nobody",
                                                             "beats": [3, {"cast": "c1"}]})
    assert shape == ["plan: P2 structure: 'cast' is not a list",
                     "plan: P2 structure: the reply is missing the key 'locations'",
                     "plan: P2 structure: the reply is missing the key 'props'",
                     "plan: P2 structure: beats item 1 is not an object",
                     "beat 1: P2 structure: cast is not a list"]
    assert broken["title"] == "" and broken["cast"] == [] and broken["beats"][0]["index"] == 0


def _checks(ctx, raw):
    plan, shape = se.normalize_plan(ctx, raw)
    hard, advisory = se.plan_checks(ctx, plan, shape)
    return hard + advisory


def test_rst14_plan_checks(ws):
    chained = seu.make_ctx(se, ws, panels=6)
    assert _checks(chained, seu.plan_json("chained", 6)) == []
    for mode in ("no_stills", "shots"):
        assert _checks(seu.make_ctx(se, ws, mode=mode, panels=6), seu.plan_json(mode, 6)) == []

    def variant(mutate, mode="chained", n=6):
        raw = seu.plan_json(mode, n)
        mutate(raw)
        return _checks(seu.make_ctx(se, ws, mode=mode, panels=n), raw)

    def beat(k, **changes):
        return lambda raw: raw["beats"][k - 1].update(changes)

    def cast2(**changes):
        return lambda raw: raw["cast"][1].update(changes)

    def setting(text):
        return lambda raw: raw["locations"][0].update(setting=text)

    long_desc = "a tall woman " + "with a long " * 15 + "coat"
    cases = [
        (lambda raw: (raw["beats"].pop(2), [b.update(index=i) for i, b in
                                             enumerate(raw["beats"], start=1)]),
         ["plan: P1 beat count: expected exactly 6 beats, found 5"]),
        (beat(3, index=7), ["plan: P1 beat count: beat 3 has index 7; beats must be numbered 1 "
                            "to 6 in order"]),
        (lambda raw: raw.update(title=""), ["plan: P2 structure: title must be a non-empty string"]),
        (beat(2, location="l9"), ["beat 2: P2 structure: location 'l9' is not defined"]),
        (beat(2, cast=["c9"]), ["beat 2: P2 structure: cast id 'c9' is not defined"]),
        (lambda raw: raw.pop("props"), ["plan: P2 structure: the reply is missing the key 'props'"]),
        (lambda raw: raw["cast"][1].update(id="x2"),
         ["plan: P2 structure: cast entry 2 has id 'x2'; ids are c1, c2 and so on"]),
        (beat(4, action=""), ["beat 4: P2 structure: action is missing or empty"]),
        (lambda raw: raw.update(locations=[]),
         ["plan: P2 structure: there must be at least one location"]
         + ["beat %d: P2 structure: location 'l1' is not defined" % k for k in range(1, 7)]),
        (cast2(phrase="the very old bald monk"),
         ["plan: P3 cast entry: c2's phrase 'the very old bald monk' has 5 words; at most 4"]),
        (cast2(phrase="The Courier"), ["plan: P3 cast entry: c2's phrase 'The Courier' is also c1's"]),
        (cast2(descriptor="an old man"),
         ["plan: P3 cast entry: c2's descriptor: must be 8-70 words, got 3"]),
        (cast2(phrase="the monk!"),
         ["plan: P3 cast entry: c2's phrase word 'monk!' may contain only letters, digits, "
          "apostrophes and hyphens (phrase 'the monk!')"]),
        (setting("A rainy harbour town in modern Japan, wet cobblestones underfoot, boats behind, "
                 "under grey light."),
         ['plan: P4 setting sentence: l1\'s setting does not start with "The setting is"']),
        (setting("The setting is a harbour."),
         ["plan: P4 setting sentence: l1's setting is 5 words; aim for 12-45"]),
        (setting("The setting is a rainy harbour town in Japan. Boats rock behind under grey "
                 "light all afternoon."),
         ["plan: P4 setting sentence: l1's setting is more than one sentence"]),
        (beat(2, arc="middle"), ["beat 2: P5 arc: 'middle' is not one of introduction, rising, "
                                 "climax, falling, resolution"]),
        (beat(5, arc="rising"), ["plan: P5 arc: no beat has arc 'climax'"]),
        (lambda raw: (raw["beats"][3].update(arc="climax"), raw["beats"][4].update(arc="rising")),
         ["beat 5: P6 arc order: 'rising' follows 'climax'"]),
        (beat(1, arc="rising"), ["plan: P5 arc: no beat has arc 'introduction'",
                                 "plan: P6 arc order: the first beat's arc is 'rising', not "
                                 "'introduction'"]),
        (beat(6, arc="falling"), ["plan: P5 arc: no beat has arc 'resolution'",
                                  "plan: P6 arc order: the last beat's arc is 'falling', not "
                                  "'resolution'"]),
        (beat(3, shot="aerial shot"), ["beat 3: P7 shot type: 'aerial shot' is not one of: extreme "
                                       "wide shot, wide shot, medium shot, medium close-up, "
                                       "close-up, extreme close-up"]),
        (beat(3, camera="zoom"), ["beat 3: P8 camera: 'zoom' is not one of: static, slow push-in, "
                                  "slow pull-back, slow pan left, slow pan right, slow tilt up, "
                                  "slow tilt down, tracking"]),
        (lambda raw: (raw["cast"].append({"id": "c3", "phrase": "the guard",
                                          "descriptor": seu.MONK}),
                      raw["beats"][1].update(cast=["c1", "c2", "c3"])),
         ("shots", ["beat 2: P9 cast count: 3 characters on screen; at most 2 in this mode"])),
        (lambda raw: (raw["cast"][1].update(descriptor=long_desc),
                      raw["cast"].append({"id": "c3", "phrase": "the guard",
                                          "descriptor": long_desc}),
                      raw["beats"][0].update(cast=["c1", "c2", "c3"]),
                      [b.update(cast=["c1", "c2", "c3"]) for b in raw["beats"]]),
         ["beat 1: P10 word budget: Image: the pasted sentences take 153 of its 120-170 words, "
          "leaving fewer than 20 for the writer"]),
        (lambda raw: [b.update(location="l2") for b in raw["beats"][3:]],
         ["beat 4: P11 location change: moves from l1 to l2 with no cut; the action must carry "
          "the characters there"]),
        (beat(3, cast=["c1", "c2"]), ["beat 3: P12 new character: c2 is not in the opening frame; "
                                      "their look is left to the video model"]),
    ]
    for mutate, expected in cases:
        mode = "chained"
        if isinstance(expected, tuple):
            mode, expected = expected
        assert variant(mutate, mode=mode) == expected, expected


def _lora_ctx(ws, tmp_path, **overrides):
    files = str(tmp_path / "files")
    entries = [
        seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style"),
        seu.catalog_entry(seu.lora_file(files, "big"), "big-style", kind="style"),
        seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion"),
        seu.catalog_entry(seu.lora_file(files, "rain"), "rain-physics", kind="physics"),
        seu.catalog_entry(seu.lora_file(files, "ink"), "ink-stills", kind="style",
                          target="stills", base_models=[seu.STILLS_MODEL]),
        seu.catalog_entry(seu.lora_file(files, "other"), "other-model",
                          base_models=["Other/pack"])]
    overrides.setdefault("catalog", {"schema_version": 1, "entries": entries})
    return seu.make_ctx(se, ws, **overrides)


def _lora_violations(ctx, loras, cast=None, beat_cast=None):
    raw = seu.plan_json(ctx.mode, ctx.panels, cast=cast)
    if beat_cast is not None:
        raw["beats"][0]["cast"] = beat_cast
    raw["loras"] = loras
    plan, _ = se.normalize_plan(ctx, raw)
    compatible = {e["id"]: e for e in se.compatible_entries(ctx)}
    catalog = {e["id"]: e for e in ctx.catalog["entries"]}
    hard, advisory = se.lora_checks(ctx, plan, compatible, catalog)
    return hard, advisory


def _pins(*specs):
    return [{"path": path, "strength": strength, "catalog_id": cid, "kind": kind}
            for path, strength, cid, kind in specs]


def test_rst15_lora_checks(ws, tmp_path, story_env):
    ctx = _lora_ctx(ws, tmp_path)
    paths = {e["id"]: e["path"] for e in ctx.catalog["entries"]}
    model = seu.VIDEO_MODEL

    def pick(entry_id, strength=0.8):
        return {"id": entry_id, "strength": strength}

    def lv(loras, **kw):
        return _lora_violations(kw.pop("ctx", ctx), loras, **kw)

    assert lv({"global": [pick("film-grain"), pick("fast-motion")],
               "per_beat": {"2": [pick("rain-physics")]}, "stills": [pick("ink-stills")]}) == (
        ["beat 2: L3 motion: 2 motion or physics LoRAs on this panel (fast-motion, "
         "rain-physics); at most 1"], [])
    assert lv({"global": [pick("film-grain")], "per_beat": {"2": [pick("rain-physics")]},
               "stills": [pick("ink-stills")]}) == ([], [])
    cases = [
        ({"global": [pick("nope")]}, ["plan: L1 catalog id: 'nope' is not in the catalog"]),
        ({"global": [pick("other-model")]},
         ["plan: L1 catalog id: 'other-model' does not support model %s" % model]),
        ({"global": [pick("ink-stills")]},
         ["plan: L1 catalog id: 'ink-stills' is a stills LoRA; global and per-beat picks must "
          "be video LoRAs"]),
        ({"stills": [pick("fast-motion")]},
         ["plan: L1 catalog id: 'fast-motion' is a video LoRA; a stills pick must be a stills "
          "LoRA"]),
        ({"per_beat": {"9": [pick("fast-motion")]}},
         ["plan: L1 catalog id: per_beat key '9' is not a beat number from 1 to 3"]),
        ({"per_beat": {"2": [{"id": "fast-motion", "strength": "high"}]}},
         ['beat 2: L1 catalog id: pick {"id": "fast-motion", "strength": "high"} is not an '
          'object with an id and a numeric strength']),
        ({"global": [pick("film-grain"), pick("big-style")]},
         ["plan: L2 style: 2 style LoRAs for every panel (film-grain, big-style); at most 1"]),
        ({"per_beat": {"2": [pick("film-grain")]}},
         ["beat 2: L2 style: style LoRA 'film-grain' can only be a global pick"]),
        ({"global": [pick("fast-motion", 1.4)]},
         ["plan: L5 strength: 'fast-motion' strength 1.4 is outside its range 0.5 to 1.0"]),
        ({"stills": [pick("ink-stills"), pick("ink-stills")]},
         ["plan: L7 stills: 2 stills LoRAs; at most 1"]),
    ]
    for loras, expected in cases:
        full = {"global": [], "per_beat": {}, "stills": []}
        full.update(loras)
        assert lv(full) == (expected, []), expected
    pins3 = _pins(("/p/1.safetensors", 1.0, None, None), ("/p/2.safetensors", 1.0, None, None),
                  ("/p/3.safetensors", 1.0, None, None))
    assert lv({"global": [pick("film-grain")], "per_beat": {"2": [pick("fast-motion")]}},
              ctx=ctx._replace(pinned=pins3)) == (
        ["beat 2: L4 LoRA count: 5 LoRAs on this panel (pinned LoRA, pinned LoRA, pinned LoRA, "
         "film-grain, fast-motion); at most 4"], [])
    members = _cast_members(story_env, "kyra", "ronin")
    cast_ctx = ctx._replace(pinned=pins3, members=members, mode="shots")
    fixed = [{"id": "c1", "phrase": "the woman in grey", "descriptor": seu.DESC_K},
             {"id": "c2", "phrase": "the ronin", "descriptor": seu.DESC_R}]
    assert lv({}, ctx=cast_ctx, cast=fixed, beat_cast=["c1", "c2"]) == (
        [], ["beat 1: L4 LoRA count: 5 LoRAs on this panel (pinned LoRA, pinned LoRA, pinned "
             "LoRA, character kyra, character ronin); at most 4"])
    dup_pin = _pins((paths["rain-physics"], 1.0, "rain-physics", "physics"))
    hard, _ = lv({"global": [pick("rain-physics")]}, ctx=ctx._replace(pinned=dup_pin))
    assert "beat 1: L6 duplicate: 'rain-physics' is applied twice on this panel" in hard
    assert sum("L6" in h for h in hard) == 1
    hard, _ = lv({"stills": [pick("ink-stills")]}, ctx=ctx._replace(mode="no_stills"))
    assert hard == ["plan: L1 catalog id: 'ink-stills' is not in the catalog",
                    "plan: L7 stills: this movie has no stills; stills must be empty"]
    assert lv({"stills": [pick("ink-stills")]},
              ctx=ctx._replace(stills_pinned=[os.path.realpath(paths["ink-stills"])])) == (
        ["plan: L7 stills: 'ink-stills' is also passed with --stills-lora"], [])
    style_pin = _pins((paths["big-style"], 1.9, "big-style", "style"))
    assert lv({"global": [pick("film-grain")]}, ctx=ctx._replace(pinned=style_pin)) == (
        ["plan: L2 style: 2 style LoRAs for every panel (big-style, film-grain); at most 1"], [])
    assert lv({}, ctx=ctx._replace(pinned=style_pin)) == ([], [])
    off = ctx._replace(auto_lora=False)
    assert lv({"global": [pick("nope")]}, ctx=off) == ([], [])


def test_lct6b_compatible_set_and_warnings(ws, tmp_path, story_env):
    members = _cast_members(story_env, "kyra")
    files = str(tmp_path / "files")
    gone = seu.catalog_entry(seu.lora_file(files, "gone"), "gone-motion")
    os.remove(gone["path"])
    clash = seu.catalog_entry(seu.lora_file(files, "clash"), "clash-motion", triggers=["KyraWmn"])
    ok = seu.catalog_entry(seu.lora_file(files, "ok"), "ok-motion")
    ink = seu.catalog_entry(seu.lora_file(files, "ink"), "ink-stills", kind="style",
                            target="stills", base_models=[seu.STILLS_MODEL])
    wrong_stills = seu.catalog_entry(seu.lora_file(files, "ws"), "video-model-stills",
                                     kind="style", target="stills", base_models=[seu.VIDEO_MODEL])
    catalog = {"schema_version": 1, "entries": [gone, clash, ok, ink, wrong_stills]}
    ctx = seu.make_ctx(se, ws, mode="shots", members=members, catalog=catalog)
    assert [e["id"] for e in se.compatible_entries(ctx)] == ["ink-stills", "ok-motion"]
    assert se.catalog_warnings(ctx) == [
        "Warning: catalog LoRA clash-motion is skipped: its trigger KyraWmn is character kyra's "
        "trigger",
        "Warning: catalog LoRA gone-motion is skipped: %s is not a readable file" % gone["path"]]
    no_stills = ctx._replace(mode="no_stills", members=[])
    assert [e["id"] for e in se.compatible_entries(no_stills)] == ["clash-motion", "ok-motion"]
    assert se.compatible_entries(ctx._replace(auto_lora=False)) == []


def _p13(ronin_name="ronin"):
    return ("library characters appear only when declared with --character %s" % ronin_name)


def test_rst55_p13_undeclared_character(ws, story_env):
    seu.ronin(story_env["lib"])
    uncast = seu.make_ctx(se, ws, panels=4)
    raw = seu.plan_json("chained", 4)
    raw["cast"][1]["phrase"] = "the ronin"
    raw["beats"][2]["action"] = "the courier hands the sealed letter to roninmn on the quay"
    raw["logline"] = "A courier crosses a rainy harbour town to meet Ronin at the temple gate."
    expected = [
        "plan: P13 undeclared character: c2's phrase names library character ronin by its "
        "referring phrase 'the ronin'; " + _p13(),
        "plan: P13 undeclared character: the logline names library character ronin by its name "
        "'Ronin'; " + _p13(),
        "plan: P13 undeclared character: beat 3's action names library character ronin by its "
        "trigger 'roninmn'; " + _p13()]
    assert _checks(uncast, raw) == expected
    clean = seu.plan_json("chained", 4)
    clean["beats"][1]["action"] = "the courier waves at the ronin across the wet quay"
    assert _checks(uncast, clean) == [
        "plan: P13 undeclared character: beat 2's action names library character ronin by its "
        "referring phrase 'the ronin'; " + _p13()]
    members = se._character_lib(WS).resolve_cast([(None, "ronin")])
    declared = seu.make_ctx(se, ws, panels=4, members=members)
    raw["cast"][1]["phrase"] = "the old monk"
    assert [m for m in _checks(declared, raw) if "P13" in m] == []


def test_rst57_reserved_sentence_in_the_plan_prompt(ws, story_env):
    seu.kyra(story_env["lib"])
    seu.ronin(story_env["lib"])
    os.makedirs(os.path.join(story_env["lib"], "broken"))
    with open(os.path.join(story_env["lib"], "broken", "character.json"), "w") as f:
        f.write("{not json")
    os.makedirs(os.path.join(story_env["lib"], "partial"))
    with open(os.path.join(story_env["lib"], "partial", "character.json"), "w") as f:
        json.dump({"name": "partial", "trigger": 5}, f)
    assert se.library_identities(ws) == [("kyra", "kyrawmn", "the woman in grey"),
                                         ("ronin", "roninmn", "the ronin")]
    uncast = seu.make_ctx(se, ws)
    prompt = se.build_plan_prompt(uncast, [], [])
    sentence = (" Never use these names or referring phrases, which belong to characters who are "
                'not in this movie: kyra ("the woman in grey"), ronin ("the ronin").\n')
    assert "accessories." + sentence in prompt
    assert "{" not in prompt and "}" not in prompt
    members = se._character_lib(WS).resolve_cast([(None, "kyra")])
    cast = seu.make_ctx(se, ws, mode="shots", members=members)
    prompt = se.build_plan_prompt(cast, [], [])
    assert ('accessories. Never use these names or referring phrases, which belong to characters '
            'who are not in this movie: ronin ("the ronin"). The following characters are already '
            'cast;') in prompt
    assert 'kyra ("the woman in grey")' not in prompt
    both = se._character_lib(WS).resolve_cast([(None, "kyra"), (None, "ronin")])
    assert "Never use these names" not in se.build_plan_prompt(
        seu.make_ctx(se, ws, mode="shots", members=both), [], [])


def test_rst55b_p13_masks_declared_and_invented_phrases(ws, story_env):
    lib_dir = story_env["lib"]
    seu.kyra(lib_dir)
    seu.make_character(lib_dir, "wmn", "wmntrg", "the woman", "woman", seu.DESC_K)
    members = se._character_lib(WS).resolve_cast([(None, "kyra")])
    declared = seu.make_ctx(se, ws, panels=4, members=members)
    raw = seu.plan_json("chained", 4, cast=[
        {"id": "c1", "phrase": "the woman in grey", "descriptor": seu.DESC_K}])
    raw["beats"][1]["action"] = "the woman in grey crosses the quay."
    assert [m for m in _checks(declared, raw) if "P13" in m] == []
    raw["beats"][1]["action"] = "the woman waves."
    hits = [m for m in _checks(declared, raw) if "P13" in m]
    assert len(hits) == 1 and "beat 2's action names library character wmn" in hits[0]
    lib = se._character_lib(WS)
    undeclared = [("wmn", "wmntrg", "the woman")]
    text = "the woman in grey walks"
    assert se.undeclared_references(lib, text, undeclared) == [("wmn", "referring phrase", "the woman")]
    assert se.undeclared_references(lib, text, undeclared, masks=("the woman in grey",)) == []
    seu.make_character(lib_dir, "empty", "", "the empty", "person", seu.DESC_K)
    plain = seu.make_ctx(se, ws, panels=4)
    assert [m for m in _checks(plain, seu.plan_json("chained", 4)) if "empty" in m] == []


# --- RST12, RST16-RST21, RST56, RST57: panels (RS12-RS16, RS37) -----------------------------

ltx_movie = importlib.machinery.SourceFileLoader(
    "ltx_movie_for_story_engine", os.path.join(WS, "bin", "ltx-movie")).load_module()
DESC30 = ("a young man with short brown hair and a lean build wearing a yellow rain jacket with "
          "a hood over grey trousers and black boots and a canvas satchel strapped")
MONK30 = ("an old man with a shaved head and a calm lined face wearing a saffron robe and wooden "
          "sandals with a string of prayer beads looped twice around his wrist")


def _norm(text):
    return " ".join(text.split())


def test_rst12_lexicons():
    templates = _norm(ltx_movie.STORY_PROMPT_TEMPLATE + " " + ltx_movie.STORY_PROMPT_TEMPLATE_NO_STILLS
                      + " " + ltx_movie.STORY_PROMPT_TEMPLATE_SHOTS)
    for example in se.COPIED_EXAMPLES:
        assert _norm(example) in templates, example
    for word in ("short", "light", "ring", "cap", "fair"):
        assert word not in se.APPEARANCE_WORDS
    assert {"grey", "kimono", "camera", "close-up", "palette"} <= se.APPEARANCE_WORDS


def _story(ws, mode, n, plan_mut=None, part_mut=None, ctx_kw=None):
    """(ctx, plan, parts, text, path) for plan_json/panel_json with the mutations applied."""
    ctx = seu.make_ctx(se, ws, mode=mode, panels=n, **(ctx_kw or {}))
    raw = seu.plan_json(mode, n)
    if plan_mut:
        plan_mut(raw)
    plan, _ = se.normalize_plan(ctx, raw)
    phrase = plan["cast"][0]["phrase"]
    parts = [se.parse_panel_reply(ctx, plan, k, json.dumps(seu.panel_json(mode, k, phrase)))
             for k in range(1, n + 1)]
    if part_mut:
        part_mut(parts)
    text = se.assemble(ctx, plan, parts)
    path = os.path.join(ctx.story_dir, "check.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return ctx, plan, parts, text, path


def _story_checks(ws, mode, n=3, **kw):
    ctx, plan, parts, text, path = _story(ws, mode, n, **kw)
    hard, advisory = se.panel_checks(ctx, plan, parts, text, path)
    return hard + advisory


def MEDIUM(raw):   # every beat a medium shot, so N17 (speaking in a wide shot) stays quiet
    for beat in raw["beats"]:
        beat["shot"] = "medium shot"


def test_rst20d_speaking_shot(ws):
    # N17 (advisory): a speaker in a wide shot, or held to a fixed smile, plays as voice-over.
    def speak(k, text, **changes):
        return lambda parts: parts[k - 1].update(narration=text, **changes)

    line = "the courier: Keep moving, stay low."
    SMILING = ("The courier pedals his bicycle steadily along the wet cobblestones of the harbour "
               "road, leaning into the rain with a broad smile on his face as he rides past the "
               "stacked wooden crates toward the old stone pier.")
    assert _story_checks(ws, "shots", part_mut=speak(2, line)) == [
        "panel 2: N17 speaking shot: Narration: 'the courier' speaks in a wide shot, too small to "
        "read the lips, so it plays as voice-over; use a medium shot or closer"]
    assert _story_checks(ws, "shots", part_mut=speak(1, line)) == []          # beat 1: medium shot
    assert _story_checks(ws, "chained", part_mut=speak(2, line)) == []        # shot is panel 1's only
    smiling = speak(1, line, motion=SMILING)
    assert _story_checks(ws, "chained", part_mut=smiling) == [
        "panel 1: N17 speaking shot: Narration: 'the courier' speaks, but the panel holds the "
        "expression 'broad smile', which freezes the mouth; describe the speaking instead"]
    voice_over = speak(1, "Rain falls on the harbour town.",
                       motion=SMILING)
    assert _story_checks(ws, "chained", part_mut=voice_over) == []


def test_rst20e_speech_only_framing(ws):
    # --speech-only: framed beats are medium shot to close-up (P7 hard), the plan and critic
    # list only those, and the Image/Motion/Prompt key lines carry the framing sentence.
    speech = {"narration": "speech"}
    shots = seu.make_ctx(se, ws, mode="shots", panels=3, **speech)
    assert _checks(shots, seu.plan_json("shots", 3)) == [
        "beat 2: P7 shot type: 'wide shot' is too wide for on-screen speech; use one of: "
        "medium shot, medium close-up, close-up"]
    chained = seu.make_ctx(se, ws, mode="chained", panels=3, **speech)
    assert _checks(chained, seu.plan_json("chained", 3)) == []   # only beat 1's shot is used
    assert _checks(seu.make_ctx(se, ws, mode="shots", panels=3), seu.plan_json("shots", 3)) == []
    prompt = se.build_plan_prompt(shots, [], [])
    assert "shot is exactly one of: medium shot, medium close-up, close-up" + se.SPEECH_SHOT_NOTE \
        in prompt and "wide shot" not in prompt
    assert "close-up, extreme close-up" in se.build_plan_prompt(
        seu.make_ctx(se, ws, mode="shots", panels=3), [], [])
    assert "exactly one of: medium shot, medium close-up, close-up." in se.critic_field_lines(
        "shots", None, "speech")
    for mode in ("chained", "no_stills", "shots"):
        ctx, plan, parts, _text, _path = _story(ws, mode, 3, ctx_kw=speech, plan_mut=MEDIUM)
        assert se.SPEECH_FRAMING_SENTENCE in se.build_panel_prompt(ctx, plan, parts, 1), mode
        ctx, plan, parts, _text, _path = _story(ws, mode, 3, plan_mut=MEDIUM)
        assert se.SPEECH_FRAMING_SENTENCE not in se.build_panel_prompt(ctx, plan, parts, 1), mode


def test_rst20b_narration_speaker(ws):
    # A Narration: line spoken on camera starts with an on-screen character's referring phrase
    # and a colon; an off-screen speaker is hard (N16), an unknown prefix is read as voice-over.
    def narration(text):
        return lambda parts: parts[1].update(narration=text)

    for mode in ("chained", "no_stills", "shots"):
        for line in ("the courier: Keep moving, stay low.", "The courier: Keep moving, stay low."):
            assert _story_checks(ws, mode, part_mut=narration(line), plan_mut=MEDIUM) == [], mode
    assert _story_checks(ws, "chained", part_mut=narration("the old monk: Wait for me.")) == [
        "panel 2: N16 speaker: Narration: is spoken by 'the old monk', who is not in this shot; "
        "only a character on screen can speak, so make it voice-over (no prefix) or put "
        "'the old monk' in the shot"]
    assert _story_checks(ws, "chained", part_mut=narration("Dawn: the city wakes slowly.")) == [
        "panel 2: N16 speaker: Narration: starts with 'Dawn:', which is no character's referring "
        "phrase, so it is read as voice-over; start a spoken line with the speaker's referring "
        "phrase, or drop the colon"]
    # N14 counts the spoken words only: "the courier:" does not push 29 words over 30.
    words29 = " ".join(["go"] * 28) + " now."
    assert _story_checks(ws, "chained", part_mut=narration("the courier: " + words29)) == []


def test_rst20c_narration_modes(ws):
    # --speech-only: Narration: may be empty; a voice-over line is hard N16. --no-narration:
    # no Narration: field at all and no narration check.
    def narration(text):   # panel 2 says text; the other panels have no narration
        return lambda parts: [p.update(narration=text if k == 1 else "")
                              for k, p in enumerate(parts)]

    speech = {"narration": "speech"}
    for mode in ("chained", "no_stills", "shots"):
        assert _story_checks(ws, mode, part_mut=narration(""), ctx_kw=speech) == [], mode
        assert _story_checks(ws, mode, part_mut=narration("the courier: Keep moving, stay low."),
                             ctx_kw=speech, plan_mut=MEDIUM) == [], mode
    assert _story_checks(ws, "chained", part_mut=narration("Rain falls on the harbour town."),
                         ctx_kw=speech) == [
        "panel 2: N16 speaker: Narration: is voice-over, but this story is speech-only; start it "
        "with the referring phrase of the character in the shot who says it and a colon, or "
        "leave it empty"]
    ctx, plan, parts, text, _path = _story(ws, "chained", 3, part_mut=narration(""), ctx_kw=speech)
    assert "Narration:" not in text
    reply = dict(seu.panel_json("chained", 2, plan["cast"][0]["phrase"]), narration="")
    assert se.parse_panel_reply(ctx, plan, 2, json.dumps(reply))["narration"] == ""
    assert se.KEY_LINE_TEMPLATES["narration_speech"] in se.build_panel_prompt(ctx, plan, parts, 2)
    off = {"narration": False}
    for mode in ("chained", "no_stills", "shots"):
        assert _story_checks(ws, mode, ctx_kw=off) == [], mode
        ctx, plan, parts, text, _path = _story(ws, mode, 3, ctx_kw=off)
        assert "Narration:" not in text and "narration" not in se.writer_keys(mode, 1, False)
        prompt = se.build_panel_prompt(ctx, plan, parts, 1)
        assert se.KEY_LINE_TEMPLATES["narration"] not in prompt
        assert se.KEY_LINE_TEMPLATES["narration_speech"] not in prompt


def test_rst16_panel_prompt(ws):
    def fixture(raw):
        raw["cast"][0]["descriptor"] = DESC30
        raw["cast"][1]["descriptor"] = MONK30
        raw["beats"][0]["cast"] = ["c1", "c2"]

    rules = ltx_movie.STORY_PROMPT_TEMPLATE_NO_STILLS
    rules = rules[rules.index("Rules:\n") + len("Rules:\n"):rules.index("\n\nNarrative to adapt:")]
    rules = "\n".join(line.strip() for line in rules.split("\n"))
    expected = {
        ("chained", 1): ["image: 27 to 77 words describing the opening frame",
                         "motion: 21 to 46 words in one or two plain sentences: what the characters "
                         "physically do during these 6 seconds. Name"],
        ("chained", 2): ["motion: 15 to 35 words in one or two plain sentences: what the characters "
                         "physically do during these 6 seconds, continuing"],
        ("no_stills", 1): ["prompt: 53 to 123 words in the present tense"],
        ("shots", 1): ["image: 20 to 77 words describing this shot's first frame",
                       "motion: ONE sentence of 6 to 21 words naming ONE character"],
        ("shots", 2): ["motion: ONE sentence of 5 to 19 words naming ONE character"],
    }
    for (mode, k), lines in expected.items():
        ctx, plan, parts, _text, _path = _story(ws, mode, 3, plan_mut=fixture,
                                                ctx_kw={"seed_agent_image": "/s/seed.png"}
                                                if mode == "chained" else None)
        prompt = se.build_panel_prompt(ctx, plan, parts, k, no_stills_rules=rules)
        assert prompt.startswith('You are writing panel %d of 3 of a short narrated movie '
                                 '(story-id "s1").\n' % k)
        assert prompt.endswith(se.NO_TOOL_SENTENCE)
        assert "{" not in prompt and "}" not in prompt and "@@" not in prompt
        for line in lines:
            assert "\n" + line in prompt, (mode, k, line)
        assert "\ntitle: a short title for the panel, 2 to 6 words.\n" in prompt
        assert prompt.count("\n" + se.KEY_LINE_TEMPLATES["narration"] + "\n") == 1
        assert ("The previous panel's Motion: " in prompt) == (mode == "chained" and k >= 2)
        assert ("It IS this movie's first frame" in prompt) == (mode == "chained" and k == 1)
        assert ("\nRules:\n" + rules + "\n\n" in prompt) == (mode == "no_stills")
        assert ("Rules for this shot: two people never touch" in prompt) == (mode == "shots")
        assert (">> %d. (%s) " % (k, plan["beats"][k - 1]["arc"])) in prompt
        if k == 1:
            assert 'referring phrases: "the courier"; "the old monk"\n' in prompt
    assert len(rules.split("\n")) == 4
    ctx, plan, parts, _text, _path = _story(ws, "chained", 3)
    prompt = se.build_panel_prompt(ctx, plan, parts, 2)
    previous = dict(se.panel_fields(ctx, plan, parts, 1))["Motion"]
    assert ('referring phrases: "the courier"\nThe previous panel\'s Motion: ' + previous
            + "\n\nWrite this panel as one JSON object") in prompt
    fixed = se.build_panel_prompt(ctx, plan, parts, 2, fix=["panel 2: N3 appearance: x",
                                                            "panel 2: N12 one action: y"])
    assert ("\n\nYour previous version of this panel was rejected. Problems:\n- panel 2: N3 "
            "appearance: x\n- panel 2: N12 one action: y\nPrevious version:\ntitle: "
            + parts[1]["title"] + "\nmotion: " + parts[1]["motion"] + "\nnarration: "
            + parts[1]["narration"] + "\n\nReply with the JSON object only") in fixed
    assert se.unparseable_panel_problem("chained", 2) == (
        "the reply is not one JSON object with the keys title, motion, narration")


def test_rst17_cleanup_and_title_fallback(ws):
    ctx, plan, parts, _t, _p = _story(ws, "shots", 3)
    lib = se._character_lib(WS)
    pasted = se.pasted_pieces(ctx, plan, 1)["image"]
    raw = ('Image:  "The courier stands left.\nThe setting is a RAINY harbour town in modern '
           'Japan, wet cobblestones underfoot, fishing boats behind, under grey afternoon light. '
           'Gulls circle.  The shot is a medium shot."')
    assert se.clean_writer(lib, raw, pasted) == "The courier stands left. Gulls circle."
    assert se.clean_writer(lib, "“motion: x y”") == "motion: x y"
    assert se.clean_writer(lib, "MOTION : The courier turns. The camera stays static.",
                           se.pasted_pieces(ctx, plan, 1)["motion"]) == "The courier turns."
    assert se.clean_writer(lib, None) == ""
    reply = dict(seu.panel_json("shots", 1), title="one two three four five six seven")
    assert se.parse_panel_reply(ctx, plan, 1, json.dumps(reply))["title"] == "the courier pedals a bicycle"
    plan["beats"][0]["action"] = "the courier's (wet) bike: rolls, slowly away"
    assert se.title_fallback(plan["beats"][0]["action"]) == "the courier's wet bike rolls"
    for bad in ("not json", json.dumps(dict(seu.panel_json("shots", 1), motion="  ")),
                json.dumps({"title": "x", "image": "a b"})):
        assert se.parse_panel_reply(ctx, plan, 1, bad) is None


GOLDEN_CHAINED = """# The Sealed Letter

A courier carries a sealed letter through a rainy harbour town and delivers it at the temple gate.

## Panel 1 — Wet Road
Image: The setting is a rainy harbour town in modern Japan, wet cobblestones underfoot, fishing boats behind, under grey afternoon light. The courier is a young man with short brown hair and a lean build wearing a yellow rain jacket and grey trousers. The courier waits on the left. The shot is a medium shot.
Motion: The courier pushes off. The camera stays static.
Narration: The rain had not stopped.

## Panel 2 — The Bend
Motion: The courier leans into the bend.
Narration: Every street led down to the water.
"""
GOLDEN_NO_STILLS = """# The Sealed Letter

A courier carries a sealed letter through a rainy harbour town and delivers it at the temple gate.

## Panel 1 — Wet Road
Prompt: The courier pedals through the rain. The courier is a young man with short brown hair and a lean build wearing a yellow rain jacket and grey trousers. The setting is a rainy harbour town in modern Japan, wet cobblestones underfoot, fishing boats behind, under grey afternoon light. The shot is a medium shot. The camera stays static.
Narration: The rain had not stopped.

## Panel 2 — The Bend
Prompt: The courier leans into the bend. The courier is a young man with short brown hair and a lean build wearing a yellow rain jacket and grey trousers. The setting is a rainy harbour town in modern Japan, wet cobblestones underfoot, fishing boats behind, under grey afternoon light. The shot is a wide shot. The camera tracks alongside the movement.
Narration: Every street led down to the water.
"""
GOLDEN_SHOTS = """# The Sealed Letter

A courier carries a sealed letter through a rainy harbour town and delivers it at the temple gate.

## Characters
- "the courier": a young man with short brown hair and a lean build wearing a yellow rain jacket and grey trousers.
- "the old monk": an old man with a shaved head and a calm face wearing a saffron robe and wooden sandals.

## Panel 1 — Wet Road
Image: The setting is a rainy harbour town in modern Japan, wet cobblestones underfoot, fishing boats behind, under grey afternoon light. The courier is a young man with short brown hair and a lean build wearing a yellow rain jacket and grey trousers. The courier waits on the left. The shot is a medium shot.
Motion: The courier pushes off. The camera stays static.
Narration: The rain had not stopped.

## Panel 2 — The Bend
Image: The setting is a rainy harbour town in modern Japan, wet cobblestones underfoot, fishing boats behind, under grey afternoon light. The courier is a young man with short brown hair and a lean build wearing a yellow rain jacket and grey trousers. The courier leans right. The shot is a wide shot.
Motion: The courier leans into the bend. The camera tracks alongside the movement.
Narration: Every street led down to the water.
"""


def test_rst18_assembly_goldens(ws):
    writer = {
        "chained": [{"title": "Wet Road", "image": "The courier waits on the left",
                     "motion": "The courier pushes off", "narration": "The rain had not stopped"},
                    {"title": "The Bend", "motion": "The courier leans into the bend.",
                     "narration": "Every street led down to the water."}],
        "no_stills": [{"title": "Wet Road", "prompt": "The courier pedals through the rain",
                       "narration": "The rain had not stopped"},
                      {"title": "The Bend", "prompt": "The courier leans into the bend.",
                       "narration": "Every street led down to the water."}],
        "shots": [{"title": "Wet Road", "image": "The courier waits on the left",
                   "motion": "The courier pushes off", "narration": "The rain had not stopped"},
                  {"title": "The Bend", "image": "The courier leans right.",
                   "motion": "The courier leans into the bend.",
                   "narration": "Every street led down to the water."}],
    }
    goldens = {"chained": GOLDEN_CHAINED, "no_stills": GOLDEN_NO_STILLS, "shots": GOLDEN_SHOTS}
    manifest = se._story_manifest(WS)
    lib = se._character_lib(WS)
    for mode, golden in goldens.items():
        ctx = seu.make_ctx(se, ws, mode=mode, panels=2)
        plan, _ = se.normalize_plan(ctx, seu.plan_json(mode, 2))
        text = se.assemble(ctx, plan, writer[mode])
        assert text == golden, mode
        path = os.path.join(ctx.story_dir, "golden.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        panels = manifest._parse_prompts_md(path)[1]
        assert [p["number"] for p in panels] == [1, 2]
        assert [p["title"] for p in panels] == ["Wet Road", "The Bend"]
        assert [bool(p["image"]) for p in panels] == {"chained": [True, False],
                                                      "no_stills": [False, False],
                                                      "shots": [True, True]}[mode]
        assert all(bool(p["prompt"]) == (mode == "no_stills") for p in panels)
        assert all(bool(p["motion"]) == (mode != "no_stills") for p in panels)
        if mode == "shots":
            assert lib.parse_character_roster(text) == ([("the courier", seu.COURIER + "."),
                                                         ("the old monk", seu.MONK + ".")], [])


def test_rst19_cast_shots_story_has_no_s9_or_s12(ws, story_env):
    members = _cast_members(story_env, "kyra", "ronin")
    fixed = [{"id": "c1", "phrase": "the woman in grey", "descriptor": seu.DESC_K},
             {"id": "c2", "phrase": "the ronin", "descriptor": seu.DESC_R}]

    def cast(raw):
        raw["cast"] = fixed
        raw["beats"][2]["cast"] = ["c2"]

    ctx, plan, parts, text, path = _story(ws, "shots", 4, plan_mut=cast,
                                          ctx_kw={"members": members})
    hard, advisory = se.panel_checks(ctx, plan, parts, text, path)
    assert not [h for h in hard if " S9 " in h or " S12 " in h]
    assert "The woman in grey is %s." % seu.DESC_K in text


def test_rst20_panel_checks(ws):
    for mode in ("chained", "no_stills", "shots"):
        assert _story_checks(ws, mode) == [], mode

    def part(k, **changes):
        return lambda parts: parts[k - 1].update(changes)

    forty = " ".join(["The courier pedals onward"] * 10)  # within N1's 25% tolerance
    fifty_two = " ".join(["The courier pedals onward"] * 13)
    cases = [
        ("chained", {"part_mut": part(2, motion=forty)}, []),
        ("chained", {"part_mut": part(2, motion=fifty_two)},
         ["panel 2: N1 word count: Motion: is 52 words; aim for 15-35"]),
        ("chained", {"part_mut": part(2, motion="The courier waves at the woman beside the crates "
                                                "and keeps pedalling forward in the rain.")},
         ["panel 2: N2 referring phrase: Motion: names 'woman' outside every referring phrase; "
          "name each character by their exact phrase"]),
        ("chained", {"part_mut": part(2, motion="The courier pulls the grey hood tighter and "
                                                "pedals forward along the road past the boats.")},
         ["panel 2: N3 appearance: Motion: says 'grey'; panels after the first never re-describe "
          "appearance, clothing, setting, lighting, colour, style or camera"]),
        ("chained", {"part_mut": part(2, motion="The courier holds the parcel up to the camera and "
                                                "pedals forward along the road past the boats.")}, []),
        ("chained", {"part_mut": part(2, motion="The courier pedals forward along the road as the "
                                                "camera slowly pans left past the boats.")},
         ["panel 2: N3 appearance: Motion: says 'camera'; panels after the first never re-describe "
          "appearance, clothing, setting, lighting, colour, style or camera"]),
        ("chained", {"part_mut": part(2, motion="The courier pedals past the old monk beside the "
                                                "crates and on toward the end of the quay.")},
         ["panel 2: N4 stray cast: Motion: names 'the old monk', who is not in beat 2's cast"]),
        ("chained", {"part_mut": lambda parts: parts[0].update(
            image=parts[0]["image"][:300] + " " + seu.TEMPLE)},
         ["panel 1: N5 setting sentence: Image: contains l2's setting sentence; beat 1 is at l1"]),
        ("no_stills", {"part_mut": part(2, prompt=seu.panel_json("no_stills", 2)["prompt"]
                                        + " A fisherman shouts across the water.")},
         ["panel 2: N7 dialogue and text: Prompt: says 'shouts'"]),
        ("chained", {"part_mut": part(3, motion='The courier reads the "urgent" note and pedals on '
                                                "toward the end of the quay.")},
         ["panel 3: N7 dialogue and text: Motion: contains a double quote"]),
        ("shots", {"part_mut": part(2, image=seu.panel_json("shots", 2)["image"]
                                    + " A caption fills the lower edge.")},
         ["panel 2: N7 dialogue and text: Image: says 'caption'"]),
        ("chained", {"part_mut": part(2, motion="The courier pedals toward a noise off-screen at "
                                                "the far end of the long quay.")},
         ["panel 2: N8 off-screen: Motion: says 'off-screen'; describe only what is in the frame"]),
        ("chained", {"part_mut": part(2, motion="The courier pedals hard and we cut to the far end "
                                                "of the quay at once.")},
         ["panel 2: N9 cut wording: Motion: says 'cut to'; one panel is one continuous shot"]),
        ("chained", {"part_mut": part(1, narration="<one sentence of voice-over narration>")},
         ["panel 1: N10 copied example: Narration: contains template text '<one sentence of "
          "voice-over narration>'"]),
        ("chained", {"plan_mut": lambda raw: raw["locations"][1].update(
            setting=se.COPIED_EXAMPLES[0] + ".")},
         ["plan: N10 copied example: l2's setting contains template text '%s'"
          % se.COPIED_EXAMPLES[0]]),
        ("chained", {"part_mut": part(2, narration="")},
         ["panel 2: N11 narration: Narration: is empty"]),
        ("chained", {"part_mut": part(2, motion="The courier stops at the crates then pedals "
                                                "forward along the wet road past the boats.")},
         ["panel 2: N12 one action: Motion: chains actions with 'then'"]),
        ("chained", {"part_mut": lambda parts: parts[2].update(motion=parts[1]["motion"])},
         ["panel 3: N13 repeat: Motion: repeats panel 2's action (similarity 1.00)"]),
        ("chained", {"part_mut": part(2, narration="It rained. It poured.")},
         ["panel 2: N14 narration form: Narration: is 2 sentences; it should be one sentence of "
          "3-30 words"]),
        ("chained", {"part_mut": part(2, narration="Rain")},
         ["panel 2: N14 narration form: Narration: is 1 words; it should be one sentence of 3-30 "
          "words"]),
    ]
    for mode, kw, expected in cases:
        assert _story_checks(ws, mode, **kw) == expected, expected
    shots_long = _story_checks(ws, "shots", part_mut=part(2, motion=forty))
    assert not [v for v in shots_long if " N1 " in v]
    assert [v for v in shots_long if " S4 " in v] == [
        "panel 2: S4 motion length: Motion: is 46 words; aim for 10-25"]
    offscreen = _story_checks(ws, "shots", part_mut=part(2, motion="The courier turns toward "
                                                                   "a noise off-screen."))
    assert offscreen == ["panel 2: S11 off-screen wording: Motion: says 'off-screen'; use left "
                         "and right screen direction instead"]
    ctx, plan, parts, _text, _path = _story(ws, "chained", 3)
    lib = se._character_lib(WS)
    fields = [("Image", "The courier stands."), ("Motion", "x"), ("Narration", "y")]
    assert se._field_checks(ctx, lib, plan, 1, "T", fields, {}, ("N5", "N6"), []) == (
        ["panel 1: N5 setting sentence: Image: lacks l1's setting sentence word for word",
         "panel 1: N6 description: Image: lacks c1's description word for word"], [])
    shots_ctx = ctx._replace(mode="shots")
    plan["cast"][0]["cast_name"] = "kyra"
    assert se._field_checks(shots_ctx, lib, plan, 1, "T", fields, {}, ("N6",), []) == ([], [])


def test_rst21_shots_rules_are_appended_unchanged(ws):
    def contact(raw):
        raw["beats"][1]["cast"] = ["c1", "c2"]

    checks = _story_checks(ws, "shots", plan_mut=contact, part_mut=lambda parts: parts[1].update(
        motion="The courier strikes the old monk with a heavy staff."))
    assert checks == ["panel 2: S8 contact: Motion: 'strikes' acts on 'the old monk'; two people "
                      "touching on screen"]


def test_rst56_n15_undeclared_character_in_panels(ws, story_env):
    seu.ronin(story_env["lib"])

    def refer(parts):
        parts[0]["title"] = "roninmn Arrives"
        parts[1]["motion"] = "The ronin raises one hand against the falling rain."
        parts[2]["narration"] = "Ronin had waited all day."

    checks = _story_checks(ws, "shots", part_mut=refer)
    tail = "; library characters appear only when declared with --character ronin"
    assert checks == [
        "panel 1: N15 undeclared character: Title: names library character ronin by its trigger "
        "'roninmn'" + tail,
        "panel 2: N15 undeclared character: Motion: names library character ronin by its "
        "referring phrase 'The ronin'" + tail,
        "panel 3: N15 undeclared character: Narration: names library character ronin by its name "
        "'Ronin'" + tail]
    members = se._character_lib(WS).resolve_cast([(None, "ronin")])
    fixed = [{"id": "c1", "phrase": "the ronin", "descriptor": seu.DESC_R}]
    declared = _story_checks(ws, "shots", plan_mut=lambda raw: raw.update(cast=fixed),
                             ctx_kw={"members": members})
    assert not [v for v in declared if " N15 " in v]


def test_rst57_reserved_line_in_the_panel_prompt(ws, story_env):
    seu.ronin(story_env["lib"])
    ctx, plan, parts, _t, _p = _story(ws, "chained", 3)
    prompt = se.build_panel_prompt(ctx, plan, parts, 1)
    assert ('referring phrases: "the courier"\nCharacters who are not in this movie, never to be '
            'named: ronin ("the ronin").\n\nAn image') not in prompt
    assert ('referring phrases: "the courier"\nCharacters who are not in this movie, never to be '
            'named: ronin ("the ronin").\n\nWrite this panel') in prompt
    members = se._character_lib(WS).resolve_cast([(None, "ronin")])
    declared = ctx._replace(members=members)
    assert "never to be named" not in se.build_panel_prompt(declared, plan, parts, 1)


def test_rst56b_n15_masks_declared_phrase(ws, story_env):
    lib = se._character_lib(WS)
    members = _cast_members(story_env, "kyra")
    fixed = [{"id": "c1", "phrase": "the woman in grey", "descriptor": seu.DESC_K}]
    seu.make_character(story_env["lib"], "wmn", "wmntrg", "the woman", "woman", seu.DESC_K)
    undeclared = [("wmn", "wmntrg", "the woman")]
    assert se.undeclared_references(lib, "the kyra woman waves", undeclared, masks=("kyra",)) == []

    def motion(text):
        return lambda parts: parts[1].update(motion=text)

    for text, expect in (("The woman in grey turns.", False), ("The woman waves.", True)):
        checks = _story_checks(ws, "shots", plan_mut=lambda raw: raw.update(cast=fixed),
                               part_mut=motion(text), ctx_kw={"members": members})
        assert bool([v for v in checks if " N15 " in v]) == expect, (text, checks)


def test_rst56c_n15_invented_phrase_naming_library_character_not_masked(ws, story_env):
    seu.ronin(story_env["lib"])
    seu.make_character(story_env["lib"], "wmn", "wmntrg", "the woman", "woman", seu.DESC_K)

    def motion(text):
        return lambda parts: parts[1].update(motion=text)

    def invented(phrase):
        fixed = [{"id": "c1", "phrase": "the courier", "descriptor": seu.COURIER},
                 {"id": "c2", "phrase": phrase, "descriptor": seu.DESC_R}]
        return lambda raw: raw.update(cast=fixed)

    checks = _story_checks(ws, "shots", plan_mut=invented("the ronin"),
                           part_mut=motion("The ronin raises a hand."))
    assert [v for v in checks if " N15 " in v], checks
    checks = _story_checks(ws, "shots", plan_mut=invented("the woman in grey"),
                           part_mut=motion("The woman in grey turns."))
    assert not [v for v in checks if " N15 " in v], checks


def test_rst56d_masks_hide_only_references_inside_them(ws, story_env):
    lib = se._character_lib(WS)
    kyra = [("kyra", "kyratok", "the woman in grey")]
    assert se.undeclared_references(lib, "The woman in grey runs.", kyra,
                                    masks=["the woman"]) == [
        ("kyra", "referring phrase", "The woman in grey")]
    wmn = [("wmn", "wmntrg", "the woman")]
    assert se.undeclared_references(lib, "The woman in grey runs.", wmn,
                                    masks=["the woman in grey"]) == []
    ronin = [("ronin", "roninmn", "the ronin")]
    identity = "The woman in grey is a young woman in a ronin's straw hat."
    assert se.undeclared_references(lib, identity, ronin,
                                    masks=["a young woman in a ronin's straw hat"]) == []

    class Member(object):
        name, trigger, phrase = "kyra", "kyrawmn", "the woman in grey"
        descriptor = "a young woman in a ronin's straw hat"

    ctx = seu.make_ctx(se, ws, members=[Member()])
    plan = {"cast": [{"id": "c1", "phrase": "the ronin", "cast_name": "kyra"},
                     {"id": "c2", "phrase": "the courier", "cast_name": None},
                     {"id": "c3", "phrase": "the ronin", "cast_name": None}]}
    assert se._undeclared_masks(lib, ctx, plan, ronin) == [
        "kyra", "kyrawmn", "the woman in grey", "a young woman in a ronin's straw hat",
        "the courier"]


# --- RST22-RST24, RST26 (validation): the critic (RS17-RS19) ---------------------------------

def test_rst22_critic_prompt(ws, tmp_path):
    texts = {}
    for mode in ("chained", "no_stills", "shots"):
        ctx, plan, parts, text, _p = _story(ws, mode, 3)
        prompt = se.build_critic_prompt(plan, text, ([], []))
        texts[mode] = prompt
        assert prompt.startswith('You are the critic for a short narrated movie (story-id "s1").')
        assert "\nThe draft story.md:\n" + text + "\n\nProblems" in prompt
        assert "\nProblems the pipeline's own checks found in this draft (fix the hard ones first):"\
               "\n- none\n" in prompt
        assert '"title": "The Sealed Letter"' in prompt and '"schema"' not in prompt
        assert prompt.endswith(se.CRITIC_REPLY_PARAGRAPH)
        assert "{" in prompt
        assert 'field "lora"' not in prompt
        has = {f: ('field "%s"' % f) in prompt for f in ("image", "motion", "prompt")}
        assert has == {"image": mode != "no_stills", "motion": mode != "no_stills",
                       "prompt": mode == "no_stills"}, mode
        assert prompt.count("(only 1: later panels continue the same picture)") == (
            3 if mode == "chained" else 0)
        assert "render in 6 seconds" in prompt and "@@" not in prompt
    ctx, plan, parts, text, _p = _story(ws, "shots", 3)
    lines = ["- fast-motion: motion LoRA for video, default strength 0.8, range 0.5 to 1.0."]
    with_lora = se.build_critic_prompt(plan, text, ([], []), catalog_lines=lines)
    assert ('field "lora", index 0 for the global picks or a beat number for that beat\'s own '
            "picks: replacement is the complete new list of picks, each an object with the keys "
            "id and strength, from this catalog:\n" + lines[0] + "\n") in with_lora
    many = (["panel %d: N1 word count: x" % i for i in range(1, 39)],
            ["panel 1: N13 repeat: y", "panel 2: N13 repeat: y", "panel 3: N13 repeat: y"])
    capped = se.build_critic_prompt(plan, text, many)
    block = capped.split("fix the hard ones first):\n", 1)[1].split("\n\nScore the draft", 1)[0]
    assert block.split("\n") == (["- [hard] panel %d: N1 word count: x" % i for i in range(1, 39)]
                                 + ["- [advisory] panel 1: N13 repeat: y",
                                    "- [advisory] panel 2: N13 repeat: y", "- ... and 1 more"])
    judge = se.build_critic_prompt(plan, text, many, for_judge=True)
    assert judge.endswith("\n\nCall submit_review with your scores, verdict and patches.")
    assert judge[:-len(se.JUDGE_REPLY_PARAGRAPH)] == capped[:-len(se.CRITIC_REPLY_PARAGRAPH)]
    goal_plan = dict(plan, goal="quiet suspense", narrative="N @@SECONDS@@")
    goal = se.build_critic_prompt(goal_plan, text, ([], []))
    assert "\n\nThe target output goal is quiet suspense.\n\nThe plan (JSON):\n" in goal
    assert "the panels tell the narrative and serve the target output goal, with" in goal
    assert "Narrative to adapt:\nN @@SECONDS@@\n" in goal


def _critic_ws(tmp_path, monkeypatch, critic=()):
    ws = seu.make_ws(tmp_path)
    log = seu.script_agent(monkeypatch, tmp_path, critic=list(critic))
    return seu.make_ctx(se, ws), log


def test_rst23_critic_routing(tmp_path, monkeypatch, capsys):
    prompt = "You are the critic for a test"
    ctx, log = _critic_ws(tmp_path, monkeypatch, critic=[{"answer": "L1"}, {"answer": "L2"},
                                                         {"answer": "L3"}, {"answer": "L4"}])
    local = seu.FakeFleet(seu.fleet_view(True, ["a"]))
    monkeypatch.setattr(se, "_load_fleet", lambda ws: local)
    assert se.run_critic(ctx, prompt) == ("ok", "L1", "local")
    assert local.calls == []
    records = seu.agent_log(log)
    assert "--skill=analyst" in records[0]["argv"] and records[0]["env_preflight"] == "1"
    peers = seu.FakeFleet(seu.fleet_view(False, ["a", "b"]),
                          [("busy", None, "no capacity"), ("ok", seu.ok_envelope("FLEET"), "")])
    monkeypatch.setattr(se, "_load_fleet", lambda ws: peers)
    assert se.run_critic(ctx, prompt) == ("ok", "FLEET", "fleet:b")
    assert [c[3] for c in peers.calls] == ["a", "b"]
    assert peers.calls[0][:3] == ("http://127.0.0.1:8190", "analyst", prompt)
    assert capsys.readouterr().out == "Warning: critic on a failed: busy no capacity\n"
    failing = seu.FakeFleet(seu.fleet_view(False, ["a"]), [("ok", seu.ok_envelope("  "), "")])
    monkeypatch.setattr(se, "_load_fleet", lambda ws: failing)
    assert se.run_critic(ctx, prompt) == ("ok", "L2", "local")
    monkeypatch.setattr(se, "_load_fleet", lambda ws: None)
    assert se.run_critic(ctx, prompt) == ("ok", "L3", "local")
    broken = seu.FakeFleet(seu.fleet_view(False, ["a"]), raise_on_fetch=True)
    monkeypatch.setattr(se, "_load_fleet", lambda ws: broken)
    assert se.run_critic(ctx, prompt) == ("ok", "L4", "local")
    assert broken.calls == []
    assert len(seu.agent_log(log)) == 4


def test_rst24_real_fleet_lib_with_no_daemon(tmp_path, monkeypatch):
    ctx, log = _critic_ws(tmp_path, monkeypatch, critic=[{"answer": "LOCAL"}])
    assert se._load_fleet(ctx.ws) is not None
    assert se.run_critic(ctx, "You are the critic for a test") == ("ok", "LOCAL", "local")
    assert len(seu.agent_log(log)) == 1


def test_rst26a_parse_critic():
    good = seu.critic_json((7, 6, 8), "revise", [{"target": "panel"}])
    assert se.parse_critic(json.dumps(good)) == good
    assert se.parse_critic("```json\n" + json.dumps(dict(good, extra=1)) + "\n```") == good
    for bad in (dict(good, scores={"continuity": 7, "story": 6}),
                dict(good, scores={"continuity": True, "story": 6, "renderability": 8}),
                dict(good, scores={"continuity": 11, "story": 6, "renderability": 8}),
                dict(good, scores={"continuity": 7.0, "story": 6, "renderability": 8}),
                dict(good, verdict="maybe"), dict(good, patches={})):
        assert se.parse_critic(json.dumps(bad)) is None, bad
    assert se.parse_critic(None) is None


# --- RST27-RST32, LCT28: patches (RS20) ----------------------------------------------------

def _patch(target, index, field, replacement, reason="because"):
    return {"target": target, "index": index, "field": field, "reason": reason,
            "replacement": replacement}


def _state(ws, mode, n=3, **kw):
    ctx, plan, parts, _text, _path = _story(ws, mode, n, **kw)
    return ctx, {"plan": plan, "parts": parts}


def _reasons(rejected):
    return [r["reason"] for r in rejected]


def test_rst27_whitelist_limit_and_duplicates(ws):
    ctx, state = _state(ws, "chained")
    good_action = "the courier coasts slowly down the empty harbour road"
    patches = [
        _patch("plan", 2, "beat.shot", "close-up"),
        _patch("plan", 2, "beat.camera", "static"),
        _patch("panel", 2, "image", "x"),
        _patch("panel", 1, "prompt", "x"),
        _patch("plan", 1, "lora", []),
        _patch("plan", 4, "beat.action", good_action),
        _patch("plan", True, "beat.action", good_action),
        _patch("panel", 0, "narration", "x"),
        _patch("story", 1, "narration", "x"),
        {"target": "panel", "index": 1, "field": "narration"},
        _patch("panel", 1, "narration", ["x"]),
        _patch("plan", 1, "lora", "x"),
    ]
    new, applied, rejected, regenerate = se.apply_patches(ctx, state, patches[:8])
    assert applied == [] and regenerate == []
    assert _reasons(rejected) == [
        "index 2 is out of range for beat.shot (allowed: 1 only)",
        "index 2 is out of range for beat.camera (allowed: 1 only)",
        "index 2 is out of range for image (allowed: 1 only)",
        "field not allowed in this mode",
        "field not allowed in this mode",
        "index 4 is out of range for beat.action (allowed: 1 to 3)",
        "index is not an integer",
        "index 0 is out of range for narration (allowed: 1 to 3)"]
    _new, _a, rejected, _r = se.apply_patches(ctx, state, patches[8:])
    assert _reasons(rejected) == [
        "unknown target or field",
        "not an object with the keys target, index, field, reason and replacement",
        "replacement must be a string", "field not allowed in this mode"]
    nine = [_patch("panel", (i % 3) + 1, "narration", "Line %d of the rain." % i) for i in range(9)]
    _new, applied, rejected, _r = se.apply_patches(ctx, state, nine)
    assert [p["index"] for p in applied] == [1, 2, 3]
    assert _reasons(rejected) == ["duplicate patch target"] * 5 + ["over the 8-patch limit"]
    assert rejected[-1]["patch"] is nine[8]
    shots_ctx, shots_state = _state(ws, "shots")
    _new, applied, rejected, _r = se.apply_patches(shots_ctx, shots_state, [
        _patch("plan", 3, "beat.shot", "close-up"), _patch("panel", 3, "image", "The courier "
                                                                                "waits."),
        _patch("panel", 2, "prompt", "x")])
    assert len(applied) == 2 and _reasons(rejected) == ["field not allowed in this mode"]
    no_stills_ctx, ns_state = _state(ws, "no_stills")
    _new, applied, rejected, _r = se.apply_patches(no_stills_ctx, ns_state, [
        _patch("panel", 2, "motion", "x"), _patch("panel", 2, "prompt", "The courier pedals.")])
    assert len(applied) == 1 and _reasons(rejected) == ["field not allowed in this mode"]
    assert state["parts"][0]["narration"] == "The rain had not stopped since dawn."


def test_rst28_location_setting_patch(ws):
    ctx, state = _state(ws, "shots")
    new_setting = ("The setting is a stormy fishing harbour in modern Japan, slick black "
                   "cobblestones underfoot, cranes behind, under blue evening light.")
    new, applied, rejected, _r = se.apply_patches(ctx, state, [
        _patch("plan", 1, "location.setting", new_setting[:-1]),
        _patch("plan", 2, "location.setting", "A short harbour")])
    assert len(applied) == 1
    assert _reasons(rejected) == ['the new setting does not start with "The setting is"']
    text = se.assemble(ctx, new["plan"], new["parts"])
    assert text.count(new_setting) == 3
    assert seu.HARBOUR not in text
    assert state["plan"]["locations"][0]["setting"] == seu.HARBOUR


def test_rst29_beat_action_regenerates_that_panel(ws):
    ctx, state = _state(ws, "shots")
    calls = []

    def regen(k, plan, parts):
        calls.append((k, plan["beats"][k - 1]["action"]))
        return "ok", dict(parts[k - 1], motion="The courier rests one hand on the railing.")

    action = "the courier stops beside the railing to catch his breath"
    new, applied, rejected, regenerate = se.apply_patches(ctx, state, [
        _patch("plan", 2, "beat.action", action),
        _patch("panel", 2, "motion", "The courier waves."),
        _patch("plan", 3, "beat.action", "too short")], regen=regen)
    assert calls == [(2, action)] and regenerate == [2]
    assert new["parts"][1]["motion"] == "The courier rests one hand on the railing."
    assert _reasons(rejected) == ["the new action is 2 words; it must be 6 to 40",
                                  "panel regenerated from a beat.action patch this round"]
    new, applied, rejected, regenerate = se.apply_patches(
        ctx, state, [_patch("plan", 2, "beat.action", action)],
        regen=lambda k, plan, parts: ("budget", None))
    assert new["plan"]["beats"][1]["action"] == action
    assert new["parts"][1] == state["parts"][1]
    assert _reasons(rejected) == ["panel 2 regeneration skipped: call budget exhausted"]


def test_rst30_shot_and_camera_reassemble_without_agent_calls(ws, monkeypatch):
    ctx, state = _state(ws, "shots")
    monkeypatch.setattr(se, "run_agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    new, applied, rejected, regenerate = se.apply_patches(ctx, state, [
        _patch("plan", 2, "beat.shot", "Close-Up"), _patch("plan", 2, "beat.camera", "slow pan left"),
        _patch("plan", 3, "beat.shot", "aerial")])
    assert regenerate == [] and len(applied) == 2
    assert _reasons(rejected) == ["'aerial' is not one of: extreme wide shot, wide shot, medium "
                                  "shot, medium close-up, close-up, extreme close-up"]
    fields = dict(se.panel_fields(ctx, new["plan"], new["parts"], 2))
    assert fields["Image"].endswith(" The shot is a close-up.")
    assert fields["Motion"].endswith(" The camera slowly pans left.")


def _lora_state(ws, tmp_path, story_env, cast_kyra=False):
    files = str(tmp_path / "files")
    entries = [seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style"),
               seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion"),
               seu.catalog_entry(seu.lora_file(files, "rain"), "rain-physics", kind="physics")]
    kw = {"catalog": {"schema_version": 1, "entries": entries}}
    plan_mut = None
    if cast_kyra:
        kw["members"] = _cast_members(story_env, "kyra")

        def plan_mut(raw):
            raw["cast"] = [{"id": "c1", "phrase": "the woman in grey", "descriptor": seu.DESC_K},
                           {"id": "c2", "phrase": "the old monk", "descriptor": seu.MONK}]
            raw["loras"] = {"global": [{"id": "film-grain", "strength": 0.8}],
                            "per_beat": {"2": [{"id": "fast-motion", "strength": 0.7}]},
                            "stills": []}
    return _state(ws, "shots", plan_mut=plan_mut, ctx_kw=kw)


def test_rst31_lora_patch(ws, tmp_path, story_env):
    ctx, state = _lora_state(ws, tmp_path, story_env)
    new, applied, rejected, _r = se.apply_patches(ctx, state, [
        _patch("plan", 0, "lora", [{"id": "fast-motion", "strength": 0.7}]),
        _patch("plan", 2, "lora", [{"id": "rain-physics", "strength": 0.9}])])
    assert len(applied) == 1
    assert new["plan"]["loras"]["global"] == [{"id": "fast-motion", "strength": 0.7}]
    assert new["plan"]["loras"]["per_beat"] == {}
    assert _reasons(rejected) == ["would break beat 2: L3 motion: 2 motion or physics LoRAs on "
                                  "this panel (fast-motion, rain-physics); at most 1"]
    cleared, applied, _rj, _r = se.apply_patches(ctx, new, [_patch("plan", 0, "lora", [])])
    assert cleared["plan"]["loras"]["global"] == [] and len(applied) == 1


def test_rst32_patches_never_change_counts_phrases_or_descriptors(ws):
    ctx, state = _state(ws, "shots", n=4)
    rng = random.Random(7)
    fields = ["beat.action", "beat.shot", "beat.camera", "location.setting", "lora", "motion",
              "image", "prompt", "narration", "cast.phrase", "descriptor"]
    values = ["the courier runs along the quay past the moored boats", "close-up", "static",
              seu.TEMPLE, "x", "", "The courier jumps.", [], [{"id": "x", "strength": 1}], 3,
              "the stranger"]
    before = (len(state["parts"]), len(state["plan"]["beats"]),
              [(c["phrase"], c["descriptor"]) for c in state["plan"]["cast"]])
    for _ in range(20):
        patches = [_patch(rng.choice(["plan", "panel", "cast"]), rng.randint(-1, 5),
                          rng.choice(fields), rng.choice(values)) for _ in range(rng.randint(0, 10))]
        new, _a, _rj, _r = se.apply_patches(ctx, state, patches)
        after = (len(new["parts"]), len(new["plan"]["beats"]),
                 [(c["phrase"], c["descriptor"]) for c in new["plan"]["cast"]])
        assert after == before
        state = new


def test_lct28_lora_limits_with_a_cast_character(ws, tmp_path, story_env):
    ctx, state = _lora_state(ws, tmp_path, story_env, cast_kyra=True)
    plan = state["plan"]
    assert plan["beats"][1]["cast"] == ["c1"] and plan["cast"][0]["cast_name"] == "kyra"
    compatible = {e["id"]: e for e in se.compatible_entries(ctx)}
    catalog = {e["id"]: e for e in ctx.catalog["entries"]}
    assert se.lora_checks(ctx, plan, compatible, catalog) == ([], [])
    _new, applied, rejected, _r = se.apply_patches(ctx, state, [
        _patch("plan", 2, "lora", [{"id": "fast-motion", "strength": 0.7},
                                   {"id": "rain-physics", "strength": 0.6}])])
    assert applied == []
    assert _reasons(rejected) == ["would break beat 2: L3 motion: 2 motion or physics LoRAs on "
                                  "this panel (fast-motion, rain-physics); at most 1"]


# --- RST10, RST11, RST17b, RST26b, RST33-RST39, RST43, RST55b, RST58: the run (RS8, RS13,
# RS21-RS27) -----------------------------------------------------------------------------------

SHOUT2 = "The courier shouts across the quay and pedals on toward the far end of the wet road."
SHOUT1 = SHOUT2[:-1] + " past the moored boats."


def _panel_script(mode, n, phrase="the courier", **overrides):
    """{"<k>": [one valid reply]} for every panel; overrides p<k>=[items] replace panel k's."""
    script = dict((str(k), [seu.answer(seu.panel_json(mode, k, phrase))]) for k in range(1, n + 1))
    for key, items in overrides.items():
        script[key[1:]] = items
    return script


def _shouting(mode, k, text):
    return seu.answer(dict(seu.panel_json(mode, k), motion=text))


def _run(ws, tmp_path, monkeypatch, mode="chained", n=3, plan=None, panel=None, critic=(),
         **ctx_kw):
    log = seu.script_agent(monkeypatch, tmp_path,
                           plan=plan if plan is not None else [seu.answer(seu.plan_json(mode, n))],
                           panel=panel if panel is not None else _panel_script(mode, n),
                           critic=list(critic))
    ctx = seu.make_ctx(se, ws, mode=mode, panels=n, **ctx_kw)
    rc, advisories = se.run(ctx)
    return rc, advisories, ctx, seu.agent_log(log)


def _rounds(ctx, r=None):
    base = os.path.join(ctx.story_dir, "story_rounds")
    return base if r is None else os.path.join(base, "round_%d" % r)


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_rst10_plan_retry_and_fatal_plan(ws, tmp_path, monkeypatch, capsys):
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, plan=[
        {"answer": "I think the story is about rain."}, seu.answer(seu.plan_json("chained", 3))],
        critic=[seu.answer(seu.critic_json())])
    assert rc == 0
    assert os.path.exists(os.path.join(_rounds(ctx, 0), "plan_reply_2.txt"))
    second = log[1]["argv"][-1]
    assert ("\n\nYOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- the reply is not one JSON object\n"
            "Previous reply:\nI think the story is about rain.\n\nReply with the complete "
            "corrected JSON object only.") in second
    assert second.startswith('You are planning a short narrated movie (story-id "s1").')
    capsys.readouterr()
    os.makedirs(os.path.join(ws, "generated", "stories", "s2"))
    with open(os.path.join(ws, "generated", "stories", "s2", "story.md"), "w") as f:
        f.write("OLD")
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, story_id="s2",
                            plan=[{"answer": "nope"}, {"status": "http_error"}])
    assert rc == 1
    err = capsys.readouterr().err
    assert err == ("Error: the story model did not return a usable plan after 2 call(s)\n"
                   "  - the reply is not one JSON object\n"
                   "Raw replies are kept in %s. Rerun the same command to try again.\n"
                   % _rounds(ctx, 0))
    with open(os.path.join(ctx.story_dir, "story.md")) as f:
        assert f.read() == "OLD"
    assert not os.path.exists(os.path.join(ctx.story_dir, "plan.json"))
    with open(os.path.join(_rounds(ctx, 0), "plan_reply_2.txt")) as f:
        assert f.read() == "<no answer: http_error>"
    assert [r["stage"] for r in log] == ["plan", "plan"]


def test_rst11_short_plan_is_fatal(ws, tmp_path, monkeypatch, capsys):
    short = seu.plan_json("chained", 5)
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, n=6,
                            plan=[seu.answer(short), seu.answer(short)])
    assert rc == 1 and len(log) == 2
    assert capsys.readouterr().err.splitlines()[:2] == [
        "Error: the story model did not return a usable plan after 2 call(s)",
        "  - plan: P1 beat count: expected exactly 6 beats, found 5"]
    assert "plan: P1 beat count: expected exactly 6 beats, found 5" in log[1]["argv"][-1]


def test_rst17b_invalid_panel_retried_once_never_three_times(ws, tmp_path, monkeypatch):
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, panel=_panel_script(
        "chained", 3, p2=[{"answer": "not json"}, {"answer": "still not json"}]))
    assert rc == 2
    panel2 = [r for r in log if r["stage"] == "panel" and r["panel"] == 2]
    assert len(panel2) == 2
    assert ("Your previous version of this panel was rejected. Problems:\n- the reply is not one "
            "JSON object with the keys title, motion, narration\nPrevious version:\ntitle: "
            "the courier swerves around a\nmotion: \nnarration: \n\n") in panel2[1]["argv"][-1]
    parts = _read_json(os.path.join(_rounds(ctx, 0), "parts.json"))["panels"]
    assert parts[1] == {"index": 2, "title": "the courier swerves around a", "motion": "",
                        "narration": ""}


def test_rst26b_critic_retry_and_code_only_round(ws, tmp_path, monkeypatch, capsys):
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, panel=_panel_script(
        "chained", 3, p2=[_shouting("chained", 2, SHOUT2), seu.answer(seu.panel_json("chained", 2))]),
        critic=[{"answer": "garbage"}, {"answer": "{}"}, {"answer": "still garbage"},
                seu.answer(seu.critic_json())])
    assert rc == 0
    out = capsys.readouterr().out
    assert "critic round 1: no valid reply after 2 call(s); code-only round\n" in out
    assert "critic round 2 (local): continuity=8 story=8 renderability=8 verdict=ok; 0 patch(es): " \
           "0 applied, 0 rejected\nstop: passed; best round 1 (0 hard)\n" in out
    assert [(r["stage"], r["panel"]) for r in log] == [
        ("plan", None), ("panel", 1), ("panel", 2), ("panel", 3), ("critic", None),
        ("critic", None), ("panel", 2), ("critic", None), ("critic", None)]
    assert log[5]["argv"][-1].endswith(se.CRITIC_RETRY_SUFFIX)
    assert "panel 2: N7 dialogue and text: Motion: says 'shouts'" in log[6]["argv"][-1]
    critic1 = _read_json(os.path.join(_rounds(ctx, 1), "critic.json"))
    assert critic1 == {"route": "local", "calls": 2, "reply": None, "applied": [], "rejected": []}


def test_rst33_stop_passed(ws, tmp_path, monkeypatch, capsys):
    rc, advisories, ctx, log = _run(ws, tmp_path, monkeypatch,
                                    critic=[seu.answer(seu.critic_json((7, 7, 8)))])
    assert (rc, advisories) == (0, [])
    assert capsys.readouterr().out == (
        "plan: call 1 of 2\npanel 1/3: call 1\npanel 2/3: call 1\npanel 3/3: call 1\n"
        "round 0: 0 hard, 0 advisory\n"
        "critic round 1 (local): continuity=7 story=7 renderability=8 verdict=ok; 0 patch(es): "
        "0 applied, 0 rejected\nstop: passed; best round 0 (0 hard)\n")
    assert [r["stage"] for r in log].count("critic") == 1
    assert [r["env_preflight"] for r in log] == [None, "1", "1", "1", "1"]
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert (checks["stop_reason"], checks["best_round"], checks["round"]) == ("passed", 0, 0)
    assert checks["scores"] == {"continuity": 7, "story": 7, "renderability": 8}


def _narration_patch(k, text):
    return {"target": "panel", "index": k, "field": "narration", "reason": "r",
            "replacement": text}


def test_rst34_stop_plateau(ws, tmp_path, monkeypatch, capsys):
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, critic=[
        seu.answer(seu.critic_json((6, 6, 6), "revise", [_narration_patch(2, "The streets ran with water.")])),
        seu.answer(seu.critic_json((5, 5, 5), "revise", [_narration_patch(3, "Never applied.")]))])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.endswith("critic round 2 (local): continuity=5 story=5 renderability=5 "
                        "verdict=revise; 1 patch(es): 0 applied, 0 rejected\n"
                        "stop: plateau; best round 0 (0 hard)\n")
    assert _read_json(os.path.join(_rounds(ctx, 2), "critic.json"))["applied"] == []
    assert not os.path.exists(os.path.join(_rounds(ctx, 2), "plan.json"))
    with open(os.path.join(ctx.story_dir, "story.md")) as f:
        story = f.read()
    with open(os.path.join(_rounds(ctx, 0), "story.md")) as f:
        assert f.read() == story


def _motion_patch(k, text):
    return {"target": "panel", "index": k, "field": "motion", "reason": "r", "replacement": text}


def test_rst35_stop_max_rounds(ws, tmp_path, monkeypatch, capsys):
    clean = dict((k, seu.panel_json("chained", k)["motion"]) for k in (1, 2, 3))
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, panel=_panel_script(
        "chained", 3, p1=[_shouting("chained", 1, SHOUT1)], p2=[_shouting("chained", 2, SHOUT2)],
        p3=[_shouting("chained", 3, SHOUT2.replace("quay", "lane"))]),
        critic=[seu.answer(seu.critic_json((6, 6, 6), "revise", [_motion_patch(2, clean[2])])),
                seu.answer(seu.critic_json((6, 6, 6), "revise", [_motion_patch(3, clean[3])])),
                seu.answer(seu.critic_json((6, 6, 6), "revise", [_motion_patch(1, clean[1])]))])
    assert rc == 0
    out = capsys.readouterr().out
    hard_counts = [int(line.split()[2]) for line in out.splitlines() if line.startswith("round ")]
    assert hard_counts == [3, 2, 1, 0]
    assert out.endswith("stop: max_rounds; best round 3 (0 hard)\n")
    assert sorted(os.listdir(_rounds(ctx))) == ["round_0", "round_1", "round_2", "round_3",
                                                "run.json"]


def test_rst36_ranking():
    def state(hard, scores=None):
        return {"hard": ["x"] * hard,
                "scores": dict(zip(se.SCORE_KEYS, scores)) if scores else None}

    assert se.best_round([state(2, (9, 9, 9)), state(1, (3, 3, 3))]) == 1
    assert se.best_round([state(1, (6, 9, 9)), state(1, (7, 7, 7))]) == 1
    assert se.best_round([state(1, (7, 7, 9)), state(1, (7, 7, 8))]) == 0
    assert se.best_round([state(1, (7, 7, 8)), state(1, (7, 7, 8))]) == 1
    states = [state(1, (6, 6, 6)), state(1)]
    assert se.best_round(states) == 1 and not se.better(states, 1, 0)
    assert se.better([state(2), state(1)], 1, 0)
    assert se.best_round([state(0), state(0)]) == 1


def test_rst36b_a_state_that_introduces_n15_loses_a_tie():
    n7 = "panel 2: N7 dialogue and text: Motion: says 'yells'"
    n15 = ("panel 2: N15 undeclared character: Motion: names library character ronin by its "
           "name 'ronin'; library characters appear only when declared with --character ronin")
    s0 = {"hard": [n7], "scores": {"continuity": 7, "story": 7, "renderability": 7}}
    s1 = {"hard": [n15], "scores": {"continuity": 9, "story": 9, "renderability": 9}}
    assert se.best_round([s0, s1]) == 0
    s1["hard"] = ["panel 3: N1 word count: Motion: is 4 words; it must be 15-35"]
    assert se.best_round([s0, s1]) == 1
    s0["hard"], s1["hard"] = [n15], [n15]
    assert se.best_round([s0, s1]) == 1


def test_rst37_budgets_and_the_wall_clock(ws, tmp_path, monkeypatch, capsys):
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, plan=[
        {"answer": "no"}, seu.answer(seu.plan_json("chained", 3))], panel=_panel_script(
        "chained", 3, p1=[{"answer": "no"}, seu.answer(seu.panel_json("chained", 1))],
        p2=[_shouting("chained", 2, SHOUT2), seu.answer(seu.panel_json("chained", 2))],
        p3=[_shouting("chained", 3, SHOUT2), _shouting("chained", 3, SHOUT2)]),
        critic=[{"answer": "x"}] * 6)
    assert rc == 2
    calls = _read_json(os.path.join(_rounds(ctx), "run.json"))["calls"]
    stages = [(c["stage"], c["panel"]) for c in calls]
    assert stages.count(("plan", None)) == 2
    assert all(stages.count(("panel", k)) <= 2 for k in (1, 2, 3))
    assert [c["round"] for c in calls if c["stage"] == "critic"] == [1, 1, 2, 2, 3, 3]
    assert "stop: plateau; best round 2 (1 hard)" in capsys.readouterr().out
    run_doc = _read_json(os.path.join(_rounds(ctx), "run.json"))
    assert run_doc["budgets"] == {"plan_calls": 2, "panel_calls": 2, "critic_rounds": 3,
                                  "critic_calls_per_round": 2, "max_patches": 8,
                                  "wall_clock_s": 2400}
    assert (run_doc["exit"], run_doc["stop_reason"], run_doc["best_round"]) == (2, "plateau", 2)

    clock = [0.0]
    monkeypatch.setattr(se, "_now", lambda: clock[0])
    real_agent = se.run_agent

    def slow_agent(*args, **kwargs):
        result = real_agent(*args, **kwargs)
        clock[0] = 10.0 ** 6
        return result

    monkeypatch.setattr(se, "run_agent", slow_agent)
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, story_id="s2")
    assert rc == 1 and [r["stage"] for r in log] == ["plan"]
    assert capsys.readouterr().err == (
        "Error: story generation exceeded the wall-clock cap of 2400s before every panel was "
        "written; partial work is kept in %s\n" % _rounds(ctx, 0))
    assert not os.path.exists(os.path.join(ctx.story_dir, "story.md"))

    clock[0] = 0.0
    monkeypatch.setattr(se, "run_agent", real_agent)
    real_critic = se.run_critic

    def slow_critic(*args, **kwargs):
        result = real_critic(*args, **kwargs)
        clock[0] = 10.0 ** 6
        return result

    monkeypatch.setattr(se, "run_critic", slow_critic)
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, story_id="s3", critic=[
        seu.answer(seu.critic_json((6, 6, 6), "revise", [_narration_patch(2, "It rained on.")]))])
    assert rc == 0
    assert capsys.readouterr().out.endswith("stop: time_cap; best round 1 (0 hard)\n")
    for name in ("plan.json", "story.md", "story_checks.json"):
        assert os.path.exists(os.path.join(ctx.story_dir, name))


def test_rst39_outputs_and_layout(ws, tmp_path, monkeypatch):
    os.makedirs(os.path.join(ws, "generated", "stories", "s1", "story_rounds"))
    with open(os.path.join(ws, "generated", "stories", "s1", "story_rounds", "old.txt"), "w") as f:
        f.write("kept")
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, critic=[
        seu.answer(seu.critic_json((6, 6, 6), "revise", [_narration_patch(2, "It rained on.")])),
        seu.answer(seu.critic_json((8, 8, 8)))])
    assert rc == 0
    moved = [n for n in os.listdir(ctx.story_dir) if n.startswith("story_rounds-")]
    assert len(moved) == 1 and re.fullmatch(r"story_rounds-\d{8}T\d{6}Z-\d+", moved[0])
    with open(os.path.join(ctx.story_dir, moved[0], "old.txt")) as f:
        assert f.read() == "kept"
    plan = _read_json(os.path.join(ctx.story_dir, "plan.json"))
    assert list(plan) == ["schema", "story_id", "mode", "panels", "seconds", "narrative", "goal",
                          "seed_image", "video_model", "auto_lora", "title", "logline", "cast",
                          "locations", "props", "beats", "loras", "speech_notes"]
    assert plan["schema"] == "ltx-movie.plan.v1" and plan["panels"] == 3
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert list(checks) == ["schema", "story_id", "mode", "panels", "checked_at", "source",
                            "round", "hard", "advisory", "scores", "verdict", "stop_reason",
                            "rounds", "best_round", "judge"]
    assert checks["source"] == "robust" and checks["best_round"] == 1 and checks["judge"] is None
    assert checks["rounds"] == [
        {"round": 0, "hard": 0, "advisory": 0, "scores": {"continuity": 6, "story": 6,
                                                          "renderability": 6},
         "verdict": "revise"},
        {"round": 1, "hard": 0, "advisory": 0, "scores": {"continuity": 8, "story": 8,
                                                          "renderability": 8},
         "verdict": "ok"}]
    assert sorted(os.listdir(_rounds(ctx, 0))) == [
        "panel_01_prompt_1.txt", "panel_01_reply_1.txt", "panel_02_prompt_1.txt",
        "panel_02_reply_1.txt", "panel_03_prompt_1.txt", "panel_03_reply_1.txt", "parts.json",
        "plan.json", "plan_prompt.txt", "plan_reply_1.txt", "story.md", "story_checks.json"]
    assert sorted(os.listdir(_rounds(ctx, 1))) == [
        "critic.json", "critic_prompt_1.txt", "critic_reply_1.txt", "parts.json", "plan.json",
        "story.md", "story_checks.json"]
    assert sorted(os.listdir(_rounds(ctx, 2))) == ["critic.json", "critic_prompt_1.txt",
                                                   "critic_reply_1.txt"]
    round1 = _read_json(os.path.join(_rounds(ctx, 1), "story_checks.json"))
    assert (round1["round"], round1["stop_reason"], round1["best_round"], round1["rounds"]) == (
        1, None, None, [])
    run_doc = _read_json(os.path.join(_rounds(ctx), "run.json"))
    assert [c["stage"] for c in run_doc["calls"]] == ["plan", "panel", "panel", "panel",
                                                      "critic", "critic"]
    assert run_doc["calls"][4]["route"] == "local" and run_doc["exit"] == 0
    with open(os.path.join(ctx.story_dir, "story.md")) as f:
        assert "Narration: It rained on.\n" in f.read()


def test_rst43_exit_2_message(ws, tmp_path, monkeypatch, capsys):
    shout3 = SHOUT2.replace("quay", "lane")
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, panel=_panel_script(
        "chained", 3, p2=[_shouting("chained", 2, SHOUT2), _shouting("chained", 2, SHOUT2)],
        p3=[_shouting("chained", 3, shout3), _shouting("chained", 3, shout3)]),
        critic=[{"answer": "x"}] * 4)
    assert rc == 2
    assert capsys.readouterr().err == (
        "Error: story.md has 2 hard violation(s) after the critic rounds (best round 1 of 1):\n"
        "  - panel 2: N7 dialogue and text: Motion: says 'shouts'\n"
        "  - panel 3: N7 dialogue and text: Motion: says 'shouts'\n"
        "story.md, plan.json and story_checks.json are saved in %s. Hand-edit story.md to fix "
        "the violations above and rerun: story.md already exists, so Phase 1 re-checks it "
        "instead of regenerating it (pass --force-story to regenerate).\n" % ctx.story_dir)
    for name in ("plan.json", "story.md", "story_checks.json"):
        assert os.path.exists(os.path.join(ctx.story_dir, name))
    assert [h["id"] for h in _read_json(os.path.join(ctx.story_dir,
                                                     "story_checks.json"))["hard"]] == ["N7", "N7"]


def test_rst55b_p13_forces_plan_call_2(ws, tmp_path, monkeypatch, story_env):
    seu.ronin(story_env["lib"])
    bad = seu.plan_json("chained", 3)
    bad["cast"][1]["phrase"] = "the ronin"
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, plan=[
        seu.answer(bad), seu.answer(seu.plan_json("chained", 3))],
        critic=[seu.answer(seu.critic_json())])
    assert rc == 0 and [r["stage"] for r in log][:2] == ["plan", "plan"]
    assert ("- plan: P13 undeclared character: c2's phrase names library character ronin by its "
            "referring phrase 'the ronin'") in log[1]["argv"][-1]


def test_rst58_a_patch_that_names_an_undeclared_character_loses(ws, tmp_path, monkeypatch,
                                                                 story_env):
    seu.ronin(story_env["lib"])
    patch = _motion_patch(2, "The courier waves to the ronin by the crates and pedals on along "
                             "the quay.")
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, critic=[
        seu.answer(seu.critic_json((8, 8, 8), "revise", [patch])),
        seu.answer(seu.critic_json((9, 9, 9)))])
    assert rc == 0
    assert _read_json(os.path.join(_rounds(ctx, 1), "critic.json"))["applied"] == [patch]
    round1 = _read_json(os.path.join(_rounds(ctx, 1), "story_checks.json"))
    assert "N15" in [h["id"] for h in round1["hard"]]
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert (checks["best_round"], checks["stop_reason"]) == (0, "plateau")


def _judge_env(monkeypatch, tmp_path, reply):
    log = os.path.join(str(tmp_path), "judge_log.jsonl")
    monkeypatch.setenv("FAKE_JUDGE_REPLY", json.dumps(reply))
    monkeypatch.setenv("FAKE_JUDGE_LOG", log)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-key")
    return log


def test_rst38_judge_gate(tmp_path, monkeypatch, capsys):
    ws = seu.make_ws(tmp_path, fake_judge=True)
    judge_log = _judge_env(monkeypatch, tmp_path, seu.critic_json((8, 9, 8)))
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, judge=True, goal="quiet suspense",
                            critic=[seu.answer(seu.critic_json((7, 7, 8)))])
    assert rc == 0
    judge = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["judge"]
    assert judge == {"status": "ok", "detail": "min score 8",
                     "scores": {"continuity": 8, "story": 9, "renderability": 8},
                     "min_score": 8, "applied": False}
    argv = seu.agent_log(judge_log)[0]["argv"]
    assert argv == ["--story-md", os.path.join(_rounds(ctx, 0), "story.md"), "--patches",
                    "--goal", "quiet suspense"]
    assert sorted(os.listdir(_rounds(ctx, 1))) == ["critic.json", "critic_prompt_1.txt",
                                                   "critic_reply_1.txt"]

    _judge_env(monkeypatch, tmp_path, seu.critic_json((5, 7, 7), "revise",
                                                      [_narration_patch(2, "The judge's line.")]))
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, judge=True, story_id="s2", critic=[
        seu.answer(seu.critic_json((7, 7, 8))), seu.answer(seu.critic_json((8, 8, 8)))])
    assert rc == 0
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert checks["judge"]["applied"] is True and checks["judge"]["min_score"] == 5
    assert checks["best_round"] == 1
    critic1 = _read_json(os.path.join(_rounds(ctx, 1), "critic.json"))
    assert critic1["route"] is None and critic1["reply"]["scores"]["continuity"] == 5
    assert os.path.exists(os.path.join(_rounds(ctx, 1), "judgment.patches.json"))
    assert os.path.exists(os.path.join(_rounds(ctx, 2), "critic.json"))
    with open(os.path.join(ctx.story_dir, "story.md")) as f:
        assert "Narration: The judge's line.\n" in f.read()

    _judge_env(monkeypatch, tmp_path, {"exit": 1})
    capsys.readouterr()
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, judge=True, story_id="s3",
                            critic=[seu.answer(seu.critic_json((7, 7, 8)))])
    assert rc == 0
    assert "Warning: judge-story failed (exit 1); keeping the critic's best round\n" in (
        capsys.readouterr().out)
    judge = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["judge"]
    assert (judge["status"], judge["detail"], judge["applied"]) == ("error", "exit 1", False)

    judge_log = _judge_env(monkeypatch, tmp_path, seu.critic_json())
    os.remove(judge_log) if os.path.exists(judge_log) else None
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, judge=True, story_id="s4", panel=_panel_script(
        "chained", 3, p2=[_shouting("chained", 2, SHOUT2), _shouting("chained", 2, SHOUT2)]),
        critic=[{"answer": "x"}] * 4)
    assert rc == 2 and not os.path.exists(judge_log)
    judge = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["judge"]
    assert judge == {"status": "skipped", "detail": "best round has hard violations",
                     "scores": None, "min_score": None, "applied": False}


def test_story_focus_1_a_non_ascii_phrase_is_repaired_or_reported(ws, tmp_path, monkeypatch,
                                                                    capsys):
    bad = seu.plan_json("chained", 3)
    bad["cast"][1]["phrase"] = "the café owner"
    p3 = ("plan: P3 cast entry: c2's phrase word 'café' may contain only letters, digits, "
          "apostrophes and hyphens (phrase 'the café owner')")
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, plan=[
        seu.answer(bad), seu.answer(seu.plan_json("chained", 3))],
        critic=[seu.answer(seu.critic_json())])
    assert rc == 0 and ("- " + p3) in log[1]["argv"][-1]
    capsys.readouterr()
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, story_id="s2",
                            plan=[seu.answer(bad), seu.answer(bad)], critic=[{"answer": "x"}] * 4)
    assert rc == 2
    assert "  - %s\n" % p3 in capsys.readouterr().err


def test_story_focus_2_a_one_panel_story(ws, tmp_path, monkeypatch):
    rc, advisories, ctx, log = _run(ws, tmp_path, monkeypatch, n=1,
                                    critic=[seu.answer(seu.critic_json())])
    assert (rc, advisories) == (0, [])
    plan = _read_json(os.path.join(ctx.story_dir, "plan.json"))
    assert [b["arc"] for b in plan["beats"]] == ["climax"]
    with open(os.path.join(ctx.story_dir, "story.md")) as f:
        assert f.read().count("## Panel ") == 1
    assert "use climax." in log[0]["argv"][-1]


def test_story_focus_3_ctrl_c_during_a_run_keeps_story_md(ws, tmp_path, monkeypatch):
    story_dir = os.path.join(ws, "generated", "stories", "s1")
    os.makedirs(story_dir)
    with open(os.path.join(story_dir, "story.md"), "w") as f:
        f.write("OLD")
    real = se.run_agent

    def interrupted(ctx, prompt, **kwargs):
        if prompt.startswith("You are writing panel 2 "):
            raise KeyboardInterrupt
        return real(ctx, prompt, **kwargs)

    monkeypatch.setattr(se, "run_agent", interrupted)
    with pytest.raises(KeyboardInterrupt):
        _run(ws, tmp_path, monkeypatch)
    with open(os.path.join(story_dir, "story.md")) as f:
        assert f.read() == "OLD"
    rounds = os.path.join(story_dir, "story_rounds")
    assert os.path.exists(os.path.join(rounds, "round_0", "panel_01_reply_1.txt"))
    assert _read_json(os.path.join(rounds, "run.json"))["exit"] is None
    monkeypatch.setattr(se, "run_agent", real)
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, critic=[seu.answer(seu.critic_json())])
    assert rc == 0
    assert len([n for n in os.listdir(story_dir) if n.startswith("story_rounds-")]) == 1


# --- RST44 (engine), RST45, RST56b: re-check (RS28) -----------------------------------------

def _saved_story(ws, monkeypatch, mode="chained", n=3, **kw):
    """A story.md and plan.json saved in <story_dir> as a run would leave them."""
    monkeypatch.setattr(ltx_movie, "WS", ws)
    ctx, plan, parts, text, _path = _story(ws, mode, n, **kw)
    with open(os.path.join(ctx.story_dir, "story.md"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(ctx.story_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f)
    return ctx, text


def _edit_story(ctx, old, new):
    path = os.path.join(ctx.story_dir, "story.md")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert text.count(old) == 1
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.replace(old, new))


def test_rst44_recheck_with_plan(ws, monkeypatch, tmp_path, capsys):
    log = seu.script_agent(monkeypatch, tmp_path)
    ctx, text = _saved_story(ws, monkeypatch)
    assert se.recheck(ctx, ltx_movie._validate_story_md) == (0, [])
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert (checks["source"], checks["round"], checks["stop_reason"], checks["rounds"],
            checks["hard"]) == ("recheck", None, None, [], [])
    motion = seu.panel_json("chained", 2)["motion"]
    _edit_story(ctx, "Motion: " + motion, "Motion: The courier yells " + motion[12:])
    story_md = os.path.join(ctx.story_dir, "story.md")
    assert se.recheck(ctx, ltx_movie._validate_story_md) == (2, [])
    assert capsys.readouterr().err == (
        "Error: story.md fails the story checks:\n"
        "  - panel 2: N7 dialogue and text: Motion: says 'yells'\n"
        "Hand-edit %s to fix the violations above and rerun, or pass --force-story to "
        "regenerate it.\n" % story_md)
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert checks["source"] == "recheck" and [h["id"] for h in checks["hard"]] == ["N7"]
    assert seu.agent_log(log) == []
    _edit_story(ctx, "Narration: Every street led down to the water.\n", "Narration:\n")
    se.recheck(ctx, ltx_movie._validate_story_md)
    hard = [h["message"] for h in _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["hard"]]
    assert hard == ["panel 2: missing/empty Narration: field",
                    "panel 2: N7 dialogue and text: Motion: says 'yells'",
                    "panel 2: N11 narration: Narration: is empty"]


def test_rst45_recheck_without_plan(ws, monkeypatch, capsys, story_env):
    ctx, text = _saved_story(ws, monkeypatch)
    os.remove(os.path.join(ctx.story_dir, "plan.json"))
    story_md = os.path.join(ctx.story_dir, "story.md")
    _edit_story(ctx, "Narration: The rain had not stopped since dawn.\n", "")
    assert se.recheck(ctx, ltx_movie._validate_story_md) == (1, [])
    assert capsys.readouterr().err == (
        "Error: story.md failed validation:\n  - panel 1: missing/empty Narration: field\n"
        "Hand-edit %s to fix the violations above and rerun; story.md already exists so Phase 1 "
        "will be skipped next time (pass --force-story to regenerate it instead).\n" % story_md)
    assert not os.path.exists(os.path.join(ctx.story_dir, "story_checks.json"))
    short, _t = _saved_story(ws, monkeypatch, n=3, ctx_kw={"story_id": "s9"})
    os.remove(os.path.join(short.story_dir, "plan.json"))
    motion = seu.panel_json("chained", 2)["motion"]
    _edit_story(short, "Motion: " + motion, "Motion: The courier pedals on.")
    assert se.recheck(short, ltx_movie._validate_story_md) == (0, [])
    shots, _t = _saved_story(ws, monkeypatch, mode="shots", ctx_kw={"story_id": "s8"})
    os.remove(os.path.join(shots.story_dir, "plan.json"))
    _edit_story(shots, "Motion: The courier steps forward onto the wet stones.",
                "Motion: The courier steps forward then turns.")
    assert se.recheck(shots, ltx_movie._validate_story_md) == (2, [])
    err = capsys.readouterr().err
    assert err.startswith("Error: story.md breaks the shot rules:\n")
    assert "  - panel 3: S5 one action: Motion: chains actions with 'then'\n" in err
    assert err.endswith("Hand-edit %s to fix the violations above and rerun, or pass "
                        "--force-story to have the story model write a new one.\n"
                        % os.path.join(shots.story_dir, "story.md"))


def test_rst56b_n15_in_recheck_and_plan_free_report(ws, monkeypatch, capsys, story_env):
    seu.ronin(story_env["lib"])
    ctx, text = _saved_story(ws, monkeypatch, mode="shots")
    _edit_story(ctx, "Narration: He knew the letter could not wait.",
                "Narration: Ronin knew the letter could not wait.")
    assert se.recheck(ctx, ltx_movie._validate_story_md)[0] == 2
    message = ("panel 3: N15 undeclared character: Narration: names library character ronin by "
               "its name 'Ronin'; library characters appear only when declared with --character "
               "ronin")
    assert "  - %s\n" % message in capsys.readouterr().err
    story_md = os.path.join(ctx.story_dir, "story.md")
    assert se.plan_free_report(story_md, "shots", 3, [], ltx_movie._validate_story_md,
                               ws=ws) == [message]
    members = se._character_lib(WS).resolve_cast([(None, "ronin")])
    report = se.plan_free_report(story_md, "shots", 3, members, ltx_movie._validate_story_md, ws=ws)
    assert message not in report
    chained, _t = _saved_story(ws, monkeypatch, ctx_kw={"story_id": "s7"})
    path = os.path.join(chained.story_dir, "story.md")
    assert se.plan_free_report(path, "chained", 3, [], ltx_movie._validate_story_md, ws=ws) == []
    assert se.plan_free_report(path, "chained", 4, [], ltx_movie._validate_story_md, ws=ws) == [
        "expected exactly 4 panels, found 3"]


def _plan_path(ctx):
    return os.path.join(ctx.story_dir, "plan.json")


def test_rst44b_recheck_stale_plan_cast_does_not_mask(ws, monkeypatch, capsys, story_env):
    seu.ronin(story_env["lib"])
    ctx, text = _saved_story(ws, monkeypatch, mode="shots")
    plan = _read_json(_plan_path(ctx))
    plan["cast"].append({"id": "c3", "phrase": "the ronin", "cast_name": "ronin",
                         "descriptor": "a lean man in a grey kimono"})
    with open(_plan_path(ctx), "w", encoding="utf-8") as f:
        json.dump(plan, f)
    _edit_story(ctx, "Narration: He knew the letter could not wait.",
                "Narration: The ronin knew the letter could not wait.")
    assert se.recheck(ctx, ltx_movie._validate_story_md)[0] == 2
    assert " N15 " in capsys.readouterr().err


def test_rst44c_recheck_malformed_plan_falls_back(ws, monkeypatch, capsys, story_env):
    def malform_cast_none(p):
        p["cast"] = None

    def malform_no_phrase(p):
        p["cast"].append({"cast_name": "x"})

    def malform_beat(p):
        del p["beats"][0]["cast"]

    def malform_loras(p):
        p["loras"] = None

    def malform_locations(p):
        p["locations"] = "x"

    for i, mutate in enumerate((malform_cast_none, malform_no_phrase, malform_beat,
                                malform_loras, malform_locations)):
        ctx, _t = _saved_story(ws, monkeypatch, ctx_kw={"story_id": "m%d" % i})
        plan = _read_json(_plan_path(ctx))
        mutate(plan)
        with open(_plan_path(ctx), "w", encoding="utf-8") as f:
            json.dump(plan, f)
        got = se.recheck(ctx, ltx_movie._validate_story_md)
        captured = capsys.readouterr()
        got_err = captured.err
        assert captured.out.startswith("note: %s is malformed; re-checking story.md without it\n"
                                       % _plan_path(ctx))
        os.remove(_plan_path(ctx))
        assert se.recheck(ctx, ltx_movie._validate_story_md) == got
        assert capsys.readouterr().err == got_err


def test_rst44d_recheck_no_plan_enforces_n15(ws, monkeypatch, capsys, story_env):
    seu.ronin(story_env["lib"])
    ctx, text = _saved_story(ws, monkeypatch)
    os.remove(_plan_path(ctx))
    _edit_story(ctx, "Narration: The rain had not stopped since dawn.\n",
                "Narration: The ronin watched the rain.\n")
    assert se.recheck(ctx, ltx_movie._validate_story_md) == (2, [])
    err = capsys.readouterr().err
    assert " N15 " in err
    assert err.endswith("ltx-movie: story.md names library characters that were not declared "
                        "with --character; fix story.md and re-run\n")
    members = se._character_lib(WS).resolve_cast([(None, "ronin")])
    declared = seu.make_ctx(se, ws, mode="chained", panels=3, members=members)
    assert se.recheck(declared, ltx_movie._validate_story_md) == (0, [])


def test_rst44e_recheck_judges_writer_text_like_generation(ws, monkeypatch, capsys):
    def mutate(raw):
        raw["locations"][0]["setting"] = seu.HARBOUR.replace("fishing boats behind",
                                                             "vendors call out")
    ctx, plan, parts, text, path = _story(ws, "chained", 3, plan_mut=mutate)
    assert "vendors call out" in text
    assert se.panel_checks(ctx, plan, parts, text, path)[0] == []
    ctx, text = _saved_story(ws, monkeypatch, plan_mut=mutate, ctx_kw={"story_id": "s2"})
    assert se.recheck(ctx, ltx_movie._validate_story_md) == (0, [])
    motion = seu.panel_json("chained", 2)["motion"]
    _edit_story(ctx, "Motion: " + motion, "Motion: The courier yells " + motion[12:])
    assert se.recheck(ctx, ltx_movie._validate_story_md)[0] == 2
    assert "  - panel 2: N7 dialogue and text: Motion: says 'yells'\n" in capsys.readouterr().err


def test_rst44f_recheck_lora_violations_point_at_plan_json(ws, monkeypatch, capsys):
    def mutate(raw):
        raw["loras"] = {"global": [{"id": "gone", "strength": 0.8}], "per_beat": {}, "stills": []}
    ctx, _text = _saved_story(ws, monkeypatch, plan_mut=mutate)
    assert se.recheck(ctx, ltx_movie._validate_story_md)[0] == 2
    err = capsys.readouterr().err
    assert "  - plan: L1 catalog id: 'gone' is not in the catalog\n" in err
    assert err.endswith(
        "The L violations come from plan.json's catalog LoRA picks, not from story.md: restore or "
        "re-add the LoRA files (bin/lora-catalog verify), rerun with --no-auto-lora, or pass "
        "--force-story to regenerate.\n")


# --- RST2-RST4, RST39b, RST40, RST42, RST46, RST50-RST54: bin/ltx-movie (RS2, RS25, RS29,
# RS31, RS34, RS35) -------------------------------------------------------------------------

LEGACY_STORY = """# Legacy

## Panel 1 — One
Image: A courier stands on a wet quay.
Motion: The courier pushes off.
Narration: It rained.

## Panel 2 — Two
Motion: The courier pedals on.
Narration: It rained more.

## Panel 3 — Three
Motion: The courier arrives.
Narration: It stopped.
"""
NARRATIVE = "A courier carries a sealed letter across a rainy harbour town."


@pytest.fixture
def movie(tmp_path, monkeypatch):
    """A temp workspace with the fake agent; ltx_movie.WS points at it; no sudo check."""
    ws = seu.make_ws(tmp_path)
    monkeypatch.setattr(ltx_movie, "WS", ws)
    monkeypatch.setattr(ltx_movie, "_check_sudo_and_start_keepalive", lambda: None)
    return ws


class _LegacyPopen(object):
    """Records each Popen argv; communicate() writes LEGACY_STORY to the story.md named by the
    story id in the prompt and exits 0."""
    calls = []

    def __init__(self, cmd, **kwargs):
        _LegacyPopen.calls.append(list(cmd))
        self.cmd = cmd
        self.returncode = 0

    def communicate(self, timeout=None):
        story_id = re.search(r'\(story-id "([^"]+)"\)', self.cmd[-1]).group(1)
        with open(os.path.join(ltx_movie.WS, "generated", "stories", story_id, "story.md"),
                  "w", encoding="utf-8") as f:
            f.write(LEGACY_STORY)
        return "", None


def test_rst2_flags_and_parse_goal():
    args = ltx_movie.build_parser().parse_args(["n", "--story-id", "x"])
    assert (args.story_legacy, args.no_auto_lora, args.judge, args.goal) == (False, False, False,
                                                                             None)
    judge_story = _judge_story()
    for text in ("a quiet drama.", "", "two\nlines", "x" * 301, "realistic action", "   "):
        outcomes = []
        for parse in (ltx_movie._parse_goal, judge_story.parse_goal):
            try:
                outcomes.append(("ok", parse(text)))
            except Exception as e:
                outcomes.append((type(e).__name__, str(e)))
        assert outcomes[0] == outcomes[1], text
    assert ltx_movie._parse_goal(" a quiet drama. ") == "a quiet drama"
    args = ltx_movie.build_parser().parse_args(["n", "--story-id", "x", "--story-legacy",
                                                "--no-auto-lora", "--judge", "--goal", "g."])
    assert (args.story_legacy, args.no_auto_lora, args.judge, args.goal) == (True, True, True, "g")


def _engine_args(*argv):
    args = ltx_movie.build_parser().parse_args(["n", "--story-id", "x"] + list(argv))
    return args, ltx_movie._resolve_story_engine(args)


def test_rst3_resolve_story_engine(tmp_path, capsys, monkeypatch, story_env):
    override = str(tmp_path / "override.txt")
    with open(override, "w") as f:
        f.write("P")
    for extra, reason in ((["--story-legacy"], "--story-legacy"),
                          (["--story-prompt-override", override], "--story-prompt-override")):
        for flag in (["--judge"], ["--no-auto-lora"], ["--goal", "g"]):
            _args, rc = _engine_args(*(extra + flag))
            assert rc == 2
            assert capsys.readouterr().err == (
                "Error: %s needs the default story engine; it cannot be combined with %s\n"
                % (flag[0], reason))
        args, rc = _engine_args(*extra)
        assert (rc, args.story_engine, args.story_catalog) == (0, "legacy", None)
    _args, rc = _engine_args("--judge")
    assert rc == 2 and capsys.readouterr().err == (
        "Error: --judge needs ANTHROPIC_API_KEY for bin/judge-story; export it or drop --judge\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-key")
    args, rc = _engine_args("--judge")
    assert (rc, args.story_engine) == (0, "robust")
    args, rc = _engine_args()
    assert (rc, args.story_engine, args.story_catalog) == (0, "robust", {"schema_version": 1,
                                                                         "entries": []})
    path = os.path.join(story_env["catalog"], "catalog.json")
    with open(path, "w") as f:
        f.write("[]")
    _args, rc = _engine_args()
    assert rc == 2 and capsys.readouterr().err == (
        "Error: invalid LoRA catalog %s: top level: must be an object with exactly the keys "
        "entries, schema_version; run bin/lora-catalog verify\n" % path)
    args, rc = _engine_args("--no-auto-lora")
    assert (rc, args.story_catalog) == (0, {"schema_version": 1, "entries": []})


def test_rst4_direct_phase1_story_call_stays_legacy(movie, monkeypatch):
    _LegacyPopen.calls = []
    monkeypatch.setattr(ltx_movie.subprocess, "Popen", _LegacyPopen)
    os.makedirs(os.path.join(movie, "generated", "stories", "d1"))
    args = ltx_movie.build_parser().parse_args([NARRATIVE, "--story-id", "d1", "--panels", "3",
                                                "--no-review"])
    assert not hasattr(args, "story_engine")
    assert ltx_movie.phase1_story(args) == 0
    assert _LegacyPopen.calls[0][4:8] == ["--max-tokens", "4096", "--max-rounds", "4"]


def test_rst40_legacy_phase1_is_byte_identical(movie, monkeypatch, tmp_path, story_env, capsys):
    from PIL import Image
    with open(os.path.join(story_env["catalog"], "catalog.json"), "w") as f:
        f.write("[]")
    _LegacyPopen.calls = []
    monkeypatch.setattr(ltx_movie.subprocess, "Popen", _LegacyPopen)
    seed = str(tmp_path / "seed.png")
    Image.new("RGB", (704, 448), (10, 20, 30)).save(seed)
    head = [sys.executable, os.path.join(movie, "bin", "qwen-agent"), "--workspace", movie,
            "--max-tokens", "4096", "--max-rounds", "4", "--request-timeout", "600"]
    cases = [
        ("l1", [], [], False),
        ("l2", ["--force-story"], ["--danger-auto-approve"], False),
        ("l3", ["--story-model", "andrevp/Qwen", "--story-context-window", "262144"],
         ["--model", "andrevp/Qwen", "--context-window", "262144"], False),
        ("l4", ["--seed-image", seed],
         ["--image", os.path.join(movie, "generated", "stories", "l4", "seed_downscaled.png")],
         True),
    ]
    for story_id, flags, middle, seeded in cases:
        argv = [NARRATIVE, "--story-id", story_id, "--panels", "3", "--story-legacy",
                "--story-only", "--no-review"] + flags
        assert ltx_movie.main(argv) == 0, capsys.readouterr().err
        prompt = ltx_movie.build_story_prompt(NARRATIVE, story_id, 3, False, seeded, seconds="6")
        assert _LegacyPopen.calls[-1] == head + middle + ["--user-prompt", prompt]
        with open(os.path.join(movie, "generated", "stories", story_id, "story_prompt.txt")) as f:
            assert f.read() == prompt
    assert len(_LegacyPopen.calls) == 4


def test_rst42_legacy_moves_a_stale_plan_aside(movie, monkeypatch, capsys):
    _LegacyPopen.calls = []
    monkeypatch.setattr(ltx_movie.subprocess, "Popen", _LegacyPopen)
    story_dir = os.path.join(movie, "generated", "stories", "m1")
    os.makedirs(story_dir)
    with open(os.path.join(story_dir, "plan.json"), "w") as f:
        f.write("{}")
    assert ltx_movie.main([NARRATIVE, "--story-id", "m1", "--panels", "3", "--story-legacy",
                           "--dry-run", "--no-review"]) == 0
    assert os.path.exists(os.path.join(story_dir, "plan.json"))
    capsys.readouterr()
    assert ltx_movie.main([NARRATIVE, "--story-id", "m1", "--panels", "3", "--story-legacy",
                           "--story-only", "--no-review"]) == 0
    moved = [n for n in os.listdir(story_dir) if n.startswith("plan.stale-")]
    assert len(moved) == 1 and re.fullmatch(r"plan\.stale-\d{8}T\d{6}Z-\d+\.json", moved[0])
    assert not os.path.exists(os.path.join(story_dir, "plan.json"))
    assert ("note: moved the robust engine's plan.json aside to %s; this story.md is written by "
            "--story-legacy\n" % os.path.join(story_dir, moved[0])) in capsys.readouterr().out


def test_rst46_review_gate(ws, monkeypatch, capsys, story_env):
    ctx, text = _saved_story(ws, monkeypatch, part_mut=lambda parts: parts[1].update(
        narration="It rained. It poured."))
    members = _cast_members(story_env, "kyra")
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt))
    for no_review in (False, True):
        args = ltx_movie.build_parser().parse_args(
            [NARRATIVE, "--story-id", "s1", "--panels", "3"] + (["--no-review"] if no_review else []))
        assert ltx_movie._resolve_story_engine(args) == 0
        args.cast_members = members
        assert ltx_movie._phase1_robust(args) == 0
        out = capsys.readouterr().out
        warnings = ("Warning: panel 2: N14 narration form: Narration: is 2 sentences; it should be "
                    "one sentence of 3-30 words\nWarning: story.md does not use cast phrase 'the "
                    "woman in grey'; character kyra gets no LoRA in this story\n")
        note = ("note: %s already exists; re-checking it instead of regenerating it (pass "
                "--force-story to regenerate)\n" % os.path.join(ctx.story_dir, "story.md"))
        if no_review:
            assert out == note + warnings
        else:
            assert out == note + "=== story.md ===\n" + text + "\n" + warnings
    assert prompts == ["Review story.md above. Enter to continue, Ctrl-C to abort: "]


def test_rst50_source_literal_counts():
    with open(os.path.join(WS, "bin", "ltx-movie"), encoding="utf-8") as f:
        movie = f.read()
    with open(os.path.join(WS, "bin", "ltx-story-images"), encoding="utf-8") as f:
        images = f.read()
    counts = [('["--model", args.story_model]', 2),
              ('["--context-window", str(args.story_context_window)]', 2),
              ('"--workspace", WS,', 2), ("_render_flags(args)", 4),
              ('os.path.join(WS, "bin", "ltx-mlx-render")', 4),
              ('cmd += ["--image", args.seed_downscaled_path]', 1),
              ('phase1_cmd += ["--image", paths["seed_downscaled"]]', 1),
              ('\n        cmd += ["--seed-image", args.seed_image]', 1),
              ('phase2_cmd += ["--seed-image", args.seed_image]', 1),
              ('"--glob"', 0), ('"--engine"', 0), ("sudo -S", 0)]
    for literal, count in counts:
        assert movie.count(literal) == count, literal
    for literal, count in (("_compose_prompt(", 3), ('"source": "generated"', 4),
                           ('"source": "seed"', 3), ("_panel_seed(args.seed, i, grounded)", 2)):
        assert images.count(literal) == count, literal
    body = inspect.getsource(ltx_movie.phase2_stills)
    assert "no_stills" not in body


def test_rst50b_robust_review_reads_utf8():
    source = inspect.getsource(ltx_movie._phase1_robust)
    assert "open(story_md)" not in source
    assert source.count('open(story_md, encoding="utf-8")') == 2


def _main_run(tmp_path, monkeypatch, argv, plan=None, panel=None, critic=()):
    log = seu.script_agent(monkeypatch, tmp_path, plan=plan or [], panel=panel or {},
                           critic=list(critic))
    rc = ltx_movie.main(argv)
    return rc, seu.agent_log(log)


def test_rst51_e2e_chained(movie, tmp_path, monkeypatch):
    rc, log = _main_run(tmp_path, monkeypatch,
                        [NARRATIVE, "--story-id", "e1", "--panels", "3", "--story-only",
                         "--no-review", "--force-story"],
                        plan=[seu.answer(seu.plan_json("chained", 3))],
                        panel=_panel_script("chained", 3), critic=[seu.answer(seu.critic_json())])
    assert rc == 0
    story_dir = os.path.join(movie, "generated", "stories", "e1")
    assert ltx_movie._validate_story_md(os.path.join(story_dir, "story.md"), 3) == []
    for name in ("plan.json", "story_checks.json"):
        assert os.path.exists(os.path.join(story_dir, name))
    with open(os.path.join(story_dir, "story_prompt.txt")) as f:
        assert f.read() == ltx_movie.build_story_prompt(NARRATIVE, "e1", 3, False, False,
                                                        seconds="6")
    assert [r["stage"] for r in log] == ["plan", "panel", "panel", "panel", "critic"]
    assert "--skill=analyst" in log[-1]["argv"]
    assert all("--max-rounds" in r["argv"] and r["argv"][r["argv"].index("--max-rounds") + 1] == "1"
               for r in log)


def test_rst52_e2e_no_stills_with_a_setting_patch(movie, tmp_path, monkeypatch):
    setting = ("The setting is a stormy fishing harbour in modern Japan, slick black cobblestones "
               "underfoot, cranes behind, under blue evening light.")
    patch = {"target": "plan", "index": 1, "field": "location.setting", "reason": "r",
             "replacement": setting}
    rc, log = _main_run(tmp_path, monkeypatch,
                        [NARRATIVE, "--story-id", "e2", "--panels", "2", "--no-stills",
                         "--story-only", "--no-review"],
                        plan=[seu.answer(seu.plan_json("no_stills", 2))],
                        panel=_panel_script("no_stills", 2),
                        critic=[seu.answer(seu.critic_json((6, 6, 6), "revise", [patch])),
                                seu.answer(seu.critic_json())])
    assert rc == 0
    story_md = os.path.join(movie, "generated", "stories", "e2", "story.md")
    panels = se._story_manifest(WS)._parse_prompts_md(story_md)[1]
    assert [150 <= len(p["prompt"].split()) <= 220 for p in panels] == [True, True]
    assert all(setting in p["prompt"] for p in panels)
    critic = _read_json(os.path.join(movie, "generated", "stories", "e2", "story_rounds",
                                     "round_1", "critic.json"))
    assert critic["applied"] == [patch]


def test_rst53_e2e_shots_with_two_characters(movie, tmp_path, monkeypatch, story_env):
    seu.kyra(story_env["lib"])
    seu.ronin(story_env["lib"])
    cast = [{"id": "c1", "phrase": "the woman in grey", "descriptor": "a woman"},
            {"id": "c2", "phrase": "the ronin", "descriptor": seu.DESC_R}]
    raw = seu.plan_json("shots", 4, cast=cast)
    raw["beats"][2]["cast"] = ["c2"]
    raw["beats"][2]["action"] = "the ronin steps out from behind a cedar trunk onto the trail"
    panels = _panel_script("shots", 4, phrase="the woman in grey")
    panels["2"] = [{"answer": "I would rather not"}] + panels["2"]
    panels["3"] = [seu.answer(seu.panel_json("shots", 3, phrase="the ronin"))]
    rc, log = _main_run(tmp_path, monkeypatch,
                        [NARRATIVE, "--story-id", "e3", "--panels", "4", "--shots", "--character",
                         "kyra", "--character", "ronin", "--story-only", "--no-review"],
                        plan=[seu.answer(raw)], panel=panels,
                        critic=[{"answer": "garbage"}, seu.answer(seu.critic_json())])
    assert rc == 0
    story_dir = os.path.join(movie, "generated", "stories", "e3")
    plan = _read_json(os.path.join(story_dir, "plan.json"))
    assert plan["cast"][:2] == [
        {"id": "c1", "phrase": "the woman in grey", "descriptor": seu.DESC_K, "cast_name": "kyra"},
        {"id": "c2", "phrase": "the ronin", "descriptor": seu.DESC_R, "cast_name": "ronin"}]
    checks = _read_json(os.path.join(story_dir, "story_checks.json"))
    assert checks["hard"] == []
    assert [(r["stage"], r["panel"]) for r in log].count(("panel", 2)) == 2
    assert [r["stage"] for r in log].count("critic") == 2
    with open(os.path.join(story_dir, "story.md")) as f:
        text = f.read()
    lib = se._character_lib(WS)
    members = lib.resolve_cast([(None, "kyra"), (None, "ronin")])
    parsed = se._story_manifest(WS)._parse_prompts_md(os.path.join(story_dir, "story.md"))[1]
    assert lib.shots_violations(text, parsed, 4, members) == []


def test_rst54_e2e_hard_fail_then_hand_edit_and_recheck(movie, tmp_path, monkeypatch, capsys):
    argv = [NARRATIVE, "--story-id", "e4", "--panels", "3", "--story-only", "--no-review"]
    rc, log = _main_run(tmp_path, monkeypatch, argv,
                        plan=[seu.answer(seu.plan_json("chained", 3))],
                        panel=_panel_script("chained", 3, p2=[_shouting("chained", 2, SHOUT2),
                                                              _shouting("chained", 2, SHOUT2)]),
                        critic=[{"answer": "x"}] * 4)
    assert rc == 2
    assert "  - panel 2: N7 dialogue and text: Motion: says 'shouts'\n" in capsys.readouterr().err
    story_md = os.path.join(movie, "generated", "stories", "e4", "story.md")
    with open(story_md) as f:
        text = f.read()
    with open(story_md, "w") as f:
        f.write(text.replace("Motion: " + SHOUT2,
                             "Motion: " + seu.panel_json("chained", 2)["motion"] + "."))
    rc, again = _main_run(tmp_path, monkeypatch, argv)
    assert rc == 0 and again == []
    assert "re-checking it instead of regenerating it" in capsys.readouterr().out
    assert _read_json(os.path.join(movie, "generated", "stories", "e4",
                                   "story_checks.json"))["source"] == "recheck"


def test_story_focus_5_non_ascii_text_round_trips(movie, tmp_path, monkeypatch):
    narrative = "東京の雨 — a courier's café run through Shinjuku."
    raw = seu.plan_json("chained", 2)
    raw["title"] = "Café 東京"
    rc, log = _main_run(tmp_path, monkeypatch,
                        [narrative, "--story-id", "u1", "--panels", "2", "--story-only",
                         "--no-review"],
                        plan=[seu.answer(raw)], panel=_panel_script("chained", 2),
                        critic=[seu.answer(seu.critic_json())])
    assert rc == 0
    story_dir = os.path.join(movie, "generated", "stories", "u1")
    with open(os.path.join(story_dir, "plan.json"), encoding="utf-8") as f:
        text = f.read()
    assert narrative in text and "\\u" not in text
    with open(os.path.join(story_dir, "story.md"), encoding="utf-8") as f:
        assert f.read().startswith("# Café 東京\n")
    assert ("Narrative to adapt:\n" + narrative + "\n") in log[0]["argv"][-1]


# --- RST41, RST47, RST57 (dry run): the robust dry run (RS30, RSK5) ---------------------------

FORBIDDEN_IN_PHASE1 = ("{", "}", "ltx-mlx-render", "ltx-story-images", "ltx-story-manifest",
                       "story-server", "--resume", "--chain", "--shots", "--no-images")


def test_rst41_legacy_dry_run_matches_the_golden():
    regression = importlib.machinery.SourceFileLoader(
        "casting_regression_for_rst41", os.path.join(WS, "tests", "test_casting_regression.py")
    ).load_module()
    with open(regression.GOLDEN_B1, encoding="utf-8") as f:
        assert regression.b1_text() == f.read()


def _dry_run(story_id, *flags, env=None):
    proc = subprocess.run([sys.executable, os.path.join(WS, "bin", "ltx-movie"), NARRATIVE,
                           "--story-id", story_id, "--dry-run", "--no-review"] + list(flags),
                          cwd=WS, capture_output=True, text=True,
                          env=dict(os.environ, **(env or {})))
    return proc


def _phase1_block(out):
    lines = out.splitlines()
    start = lines.index("--- Phase 1: story ---")
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("--- Phase "))
    return lines[start:end]


def test_rst47_robust_dry_run(tmp_path, story_env, monkeypatch):
    from PIL import Image
    seed = str(tmp_path / "seed.png")
    Image.new("RGB", (704, 448), (10, 20, 30)).save(seed)
    files = str(tmp_path / "files")
    seu.make_catalog(story_env["catalog"], [
        seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion"),
        seu.catalog_entry(seu.lora_file(files, "other"), "other-model", base_models=["X/y"])])
    catalog_path = os.path.join(story_env["catalog"], "catalog.json")
    story_dir = os.path.join(WS, "generated", "stories", "rst47-%d" % os.getpid())
    assert not os.path.exists(story_dir)
    cases = [
        ([], "Catalog LoRAs: 1 compatible entry in %s" % catalog_path, False, False),
        (["--no-stills"], "Catalog LoRAs: 1 compatible entry in %s" % catalog_path, False, False),
        (["--shots"], "Catalog LoRAs: 1 compatible entry in %s" % catalog_path, False, False),
        (["--seed-image", seed], "Catalog LoRAs: 1 compatible entry in %s" % catalog_path, True,
         False),
        (["--no-auto-lora"], "Catalog LoRAs: off (--no-auto-lora)", False, False),
        (["--judge"], "Catalog LoRAs: 1 compatible entry in %s" % catalog_path, False, True),
    ]
    for flags, catalog_line, seeded, judge in cases:
        proc = _dry_run(os.path.basename(story_dir), "--panels", "4", *flags,
                        env={"ANTHROPIC_API_KEY": "test-not-a-key"} if judge else None)
        assert proc.returncode == 0, proc.stderr
        block = _phase1_block(proc.stdout)
        assert block[:4] == [
            "--- Phase 1: story ---",
            "Would skip if %s already exists and re-check it instead (pass --force-story to "
            "regenerate)." % os.path.join(story_dir, "story.md"),
            "Story engine: a JSON plan, one call per panel, deterministic checks and up to 3 "
            "critic rounds (analyst via the local qwen-agentd, else a local one-shot); "
            "--story-legacy for the single-prompt path.",
            catalog_line]
        command = block[5 if judge else 4]
        if judge:
            assert block[4] == "Judge gate: bin/judge-story --patches after the critic rounds."
        assert command.startswith("Command (subprocess timeout 600s): ")
        argv = shlex.split(proc.stdout.split("Command (subprocess timeout 600s): ", 1)[1]
                           .split("\n\nRendered plan prompt:\n", 1)[0])
        assert argv[argv.index("--max-rounds") + 1] == "1"
        assert argv[argv.index("--max-tokens") + 1] == "4096"
        assert ("--image" in argv) == seeded
        if seeded:
            assert argv[argv.index("--image") + 1] == os.path.join(story_dir, "seed_downscaled.png")
        assert argv[-1].startswith('You are planning a short narrated movie (story-id "rst47-')
        assert block[block.index("Rendered plan prompt:") + 1].startswith("You are planning")
        assert not [line for line in proc.stdout.splitlines() if "{" in line or "}" in line]
        phase1 = "\n".join(block)
        assert not [s for s in FORBIDDEN_IN_PHASE1 if s in phase1], flags
    assert not os.path.exists(story_dir)
    os.remove(catalog_path)
    proc = _dry_run("rst47b-%d" % os.getpid())
    assert ("Catalog LoRAs: none compatible in %s" % catalog_path) in proc.stdout.splitlines()
    script = (
        "import contextlib, io, sys\n"
        "sys.path.insert(0, %r)\n"
        "import importlib.machinery\n"
        "m = importlib.machinery.SourceFileLoader('ltx_movie', %r).load_module()\n"
        "with contextlib.redirect_stdout(io.StringIO()):\n"
        "    rc = m.main(['n', '--story-id', 'x', '--dry-run', '--no-review'])\n"
        "print('RC=%%d' %% rc)\n"
        "print('CHARACTER_LIB_LOADED=%%s' %% ('character_lib' in sys.modules))\n"
        "print('FLEET_LOADED=%%s' %% ('fleet_lib_for_story' in sys.modules))\n"
    ) % (WS, os.path.join(WS, "bin", "ltx-movie"))
    seu.kyra(story_env["lib"])
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert proc.stdout.splitlines() == ["RC=0", "CHARACTER_LIB_LOADED=False", "FLEET_LOADED=False"], (
        proc.stderr)


def test_rst57c_dry_run_lists_the_undeclared_characters(story_env):
    seu.ronin(story_env["lib"])
    proc = _dry_run("rst57-%d" % os.getpid(), "--panels", "3")
    assert proc.returncode == 0, proc.stderr
    assert (' Never use these names or referring phrases, which belong to characters who are not '
            'in this movie: ronin ("the ronin").') in proc.stdout


# --- RST48, RST49: bin/judge-story --patches, bin/iterate-story (RS32, RS33) --------------------

def _judge_story():
    """bin/judge-story, loaded only by the tests that use it (it imports anthropic and
    jsonschema, which collecting the engine tests must not need)."""
    pytest.importorskip("anthropic")
    pytest.importorskip("jsonschema")
    return importlib.machinery.SourceFileLoader(
        "judge_story_for_story_engine", os.path.join(WS, "bin", "judge-story")).load_module()


iterate_story = importlib.machinery.SourceFileLoader(
    "iterate_story_for_story_engine", os.path.join(WS, "bin", "iterate-story")).load_module()


class _FakeAnthropic(object):
    """Stands in for anthropic.Anthropic (the tests/test_judge_story.py pattern)."""

    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []
        self.messages = type("M", (), {})()
        self.messages.create = self._create

    def __call__(self, *args, **kwargs):
        return self

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.scripted.pop(0)


def _anthropic_message(name, tool_input):
    import anthropic
    return anthropic.types.Message.model_validate({
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "stop_reason": "tool_use", "stop_sequence": None,
        "content": [{"type": "tool_use", "id": "toolu_test", "name": name, "input": tool_input}],
        "usage": {"input_tokens": 100, "output_tokens": 50}})


def test_rst48_judge_story_patches(ws, monkeypatch, capsys, tmp_path):
    judge_story = _judge_story()
    ctx, text = _saved_story(ws, monkeypatch)
    story_md = os.path.join(ctx.story_dir, "story.md")
    checks = {"hard": [{"message": "panel 2: N7 dialogue and text: Motion: says 'yells'"}],
              "advisory": [{"message": "panel 3: N13 repeat: Motion: repeats panel 2's action "
                                       "(similarity 0.71)"}]}
    with open(os.path.join(ctx.story_dir, "story_checks.json"), "w") as f:
        json.dump(checks, f)
    review = {"scores": {"renderability": 6, "continuity": 8, "story": 7}, "verdict": "revise",
              "patches": [{"target": "panel", "index": 2, "field": "motion", "reason": "dialogue",
                           "replacement": "The courier pedals on."}]}
    fake = _FakeAnthropic([_anthropic_message("submit_review", review)])
    monkeypatch.setattr(judge_story.anthropic, "Anthropic", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-key")
    monkeypatch.setattr(judge_story, "WS", WS)
    assert judge_story.main(["--story-md", story_md, "--patches"]) == 0
    kwargs = fake.calls[0]
    assert kwargs["system"] == judge_story.PATCH_SYSTEM_PROMPT_TEMPLATE.replace(
        "@@GOAL@@", judge_story.DEFAULT_GOAL)
    assert kwargs["tools"] == [{"name": "submit_review", "description": (
        "Submit your review of the story: three 1-10 scores, a verdict, and at most 8 patches. "
        "You must call this exactly once."), "input_schema": judge_story.SUBMIT_REVIEW_SCHEMA}]
    plan = _read_json(os.path.join(ctx.story_dir, "plan.json"))
    assert kwargs["messages"] == [{"role": "user", "content": se.build_critic_prompt(
        plan, text, ([checks["hard"][0]["message"]], [checks["advisory"][0]["message"]]),
        for_judge=True)}]
    judgment = _read_json(os.path.join(ctx.story_dir, "judgment.patches.json"))
    assert list(judgment) == ["story_md_path", "plan_path", "model", "effort", "goal", "timestamp",
                              "usage", "scores", "verdict", "patches"]
    assert list(judgment["scores"]) == ["continuity", "story", "renderability"]
    assert judgment["patches"] == review["patches"]
    assert capsys.readouterr().out == ("Scores:\n  continuity      8\n  story           7\n"
                                       "  renderability   6\n\nVerdict: revise\nPatches: 1\n")
    os.remove(os.path.join(ctx.story_dir, "plan.json"))
    assert judge_story.main(["--story-md", story_md, "--patches"]) == 2
    assert capsys.readouterr().err == (
        "Error: plan.json not found: %s. --patches needs a story written by bin/ltx-movie's "
        "default story engine.\n" % os.path.join(ctx.story_dir, "plan.json"))
    with pytest.raises(SystemExit) as exc:
        judge_story.main(["--story-md", story_md, "--patches", "--target-panels", "3"])
    assert exc.value.code == 2
    assert "--patches cannot be combined with --target-panels" in capsys.readouterr().err
    with open(os.path.join(ctx.story_dir, "story_prompt.txt"), "w") as f:
        f.write("PROMPT")
    judgment_input = {"scores": dict((k, 7) for k in judge_story.SCORE_KEYS), "critique": "c",
                      "revised_prompt": "r"}
    fake = _FakeAnthropic([_anthropic_message("submit_judgment", judgment_input)])
    monkeypatch.setattr(judge_story.anthropic, "Anthropic", fake)
    assert judge_story.main(["--story-md", story_md]) == 0
    assert fake.calls[0]["system"] == judge_story.SYSTEM_PROMPT
    assert fake.calls[0]["tools"][0]["name"] == "submit_judgment"
    assert list(_read_json(os.path.join(ctx.story_dir, "judgment.json"))) == [
        "story_md_path", "story_prompt_path", "model", "effort", "goal", "timestamp", "usage",
        "scores", "critique", "revised_prompt"]


def test_rst48b_judge_story_patches_rejects_a_malformed_plan(ws, monkeypatch, capsys):
    judge_story = _judge_story()
    ctx, _text = _saved_story(ws, monkeypatch)
    story_md = os.path.join(ctx.story_dir, "story.md")
    plan_path = os.path.join(ctx.story_dir, "plan.json")
    fake = _FakeAnthropic([])
    monkeypatch.setattr(judge_story.anthropic, "Anthropic", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-key")
    monkeypatch.setattr(judge_story, "WS", WS)
    expected = ("Error: %s is not a plan.json written by bin/ltx-movie's default story engine. "
                "--patches needs a story written by bin/ltx-movie's default story engine.\n"
                % plan_path)
    for bad in ([], {"schema": "ltx-movie.plan.v1", "mode": "chained"}):
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(bad, f)
        assert judge_story.main(["--story-md", story_md, "--patches"]) == 2
        assert capsys.readouterr().err == expected
    assert fake.calls == []


def test_rst48c_engine_tests_collect_without_anthropic(tmp_path):
    block = tmp_path / "block"
    block.mkdir()
    (block / "anthropic.py").write_text("raise ImportError('blocked for this test')\n")
    (block / "jsonschema.py").write_text("raise ImportError('blocked for this test')\n")
    env = dict(os.environ, PYTHONPATH=str(block))
    proc = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p",
                           "no:cacheprovider", os.path.join(WS, "tests", "test_story_engine.py")],
                          cwd=WS, env=env, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]


class _Completed(object):
    def __init__(self, returncode, stdout):
        self.returncode, self.stdout = returncode, stdout


def test_rst49_iterate_story_wrapper(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(iterate_story, "WS", str(tmp_path))
    story_dir = tmp_path / "generated" / "stories" / "it1"
    story_dir.mkdir(parents=True)
    plan = {"schema": "ltx-movie.plan.v1", "mode": "shots", "panels": 4,
            "narrative": "A ronin at dusk.", "seed_image": "/s/seed.png", "goal": "plan goal",
            "cast": [{"id": "c1", "cast_name": "kyra"}, {"id": "c2", "cast_name": None},
                     {"id": "c3", "cast_name": "ronin"}],
            "loras": {"pinned": [{"path": "/p/a.safetensors", "strength": 1.0},
                                 {"path": "/p/b.safetensors", "strength": 0.5}]}}
    (story_dir / "plan.json").write_text(json.dumps(plan))
    calls = []
    monkeypatch.setattr(iterate_story, "_run",
                        lambda cmd: calls.append(cmd) or _Completed(3, "engine output\n"))
    rc = iterate_story.main(["--story-id", "it1", "--threshold", "8", "--goal", "cli goal",
                             "--story-model", "M", "--story-context-window", "9000"])
    assert rc == 3
    assert calls == [[sys.executable, os.path.join(str(tmp_path), "bin", "ltx-movie"),
                      "A ronin at dusk.", "--story-id", "it1", "--panels", "4", "--shots",
                      "--character", "kyra", "--character", "ronin", "--seed-image",
                      "/s/seed.png", "--lora", "/p/a.safetensors:1.0", "--lora",
                      "/p/b.safetensors:0.5", "--goal", "cli goal", "--force-story",
                      "--no-review", "--story-only", "--judge", "--story-model", "M",
                      "--story-context-window", "9000"]]
    out, err = capsys.readouterr()
    assert out == "engine output\n"
    assert err == (iterate_story.DEPRECATION_NOTICE + "\niterate-story: --threshold and "
                   "--max-rounds are ignored on the default engine; its thresholds are fixed\n")
    assert "=== round 1: ltx-movie ===" in (story_dir / "iterate-story.log").read_text()
    plan.update(mode="no_stills", goal=None, seed_image=None)
    (story_dir / "plan.json").write_text(json.dumps(plan))
    iterate_story.main(["--story-id", "it1", "--threshold", "8"])
    assert calls[-1][7] == "--no-stills" and "--goal" not in calls[-1]
    capsys.readouterr()
    (story_dir / "plan.json").unlink()
    assert iterate_story.main(["--story-id", "it1", "--threshold", "8"]) == 2
    out, err = capsys.readouterr()
    assert err.startswith("Error: story.md not found") and iterate_story.DEPRECATION_NOTICE not in err
    (story_dir / "story.md").write_text("## Panel 1 — A\nMotion: x\n")
    (story_dir / "story_prompt.txt").write_text("P")
    monkeypatch.setattr(iterate_story, "_run", lambda cmd: _Completed(1, "judge failed"))
    assert iterate_story.main(["--story-id", "it1", "--threshold", "8"]) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith(iterate_story.DEPRECATION_NOTICE + "\nError: round 1: judge-story "
                          "exited 1")
    (story_dir / "plan.json").write_text(json.dumps({"schema": "ltx-movie.plan.v1", "panels": 3}))
    before = len(calls)
    assert iterate_story.main(["--story-id", "it1", "--threshold", "8"]) == 2
    assert capsys.readouterr().err == (
        "Error: %s is not a usable plan.json; regenerate the story with bin/ltx-movie "
        "--force-story\n" % (story_dir / "plan.json"))
    assert len(calls) == before


# --- RST61-RST63: interpreters, imports, isolation (RSK2-RSK4) --------------------------------

CHANGED_FILES = ("story_engine.py", "lora_catalog.py", "bin/lora-catalog", "bin/ltx-movie",
                 "bin/ltx-story-manifest", "bin/ltx-story-images", "bin/ltx-mlx-render",
                 "bin/judge-story", "bin/iterate-story", "scripts/deploy/build_pkg.py",
                 "tests/story_engine_testutil.py", "tests/test_story_engine.py",
                 "tests/test_lora_catalog.py", "tests/test_ltx_movie_offline.py",
                 "tests/test_casting_regression.py", "tests/test_casting_pipeline.py",
                 "tests/test_shots_mode.py", "tests/test_deploy_pkg.py")
COMPILE_ONLY = ("import sys\n"
                "for path in sys.argv[1:]:\n"
                "    with open(path, encoding='utf-8') as f:\n"
                "        compile(f.read(), path, 'exec')\n"
                "print('compiled %d' % (len(sys.argv) - 1))\n")


def test_rst61_both_interpreters_compile_every_changed_file():
    paths = [os.path.join(WS, rel) for rel in CHANGED_FILES]
    for interpreter in ("/usr/bin/python3", sys.executable):
        proc = subprocess.run([interpreter, "-c", COMPILE_ONLY] + paths, capture_output=True,
                              text=True)
        assert (proc.returncode, proc.stdout) == (0, "compiled %d\n" % len(paths)), (
            interpreter, proc.stderr)


def _all_imports(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module)
    return names


def test_rst62_import_sets():
    assert _top_level_imports(os.path.join(WS, "bin", "lora-catalog")) == {
        "argparse", "importlib.machinery", "json", "os", "sys", "lora_catalog"}
    baseline = {
        "bin/ltx-movie": {"argparse", "glob", "importlib.machinery", "json", "os", "pipeline_log",
                          "shlex", "subprocess", "sys", "threading", "time"},
        "bin/ltx-story-images": {"argparse", "importlib.machinery", "json", "os", "pipeline_log",
                                 "sys", "time"},
        "bin/ltx-mlx-render": {"argparse", "datetime", "glob", "hashlib", "json",
                               "ltx2_mlx_video_skill", "os", "re", "shlex", "shutil", "stat",
                               "subprocess", "sys", "time", "uuid"},
        "bin/judge-story": {"anthropic", "argparse", "datetime", "json", "jsonschema", "os", "sys"},
        "bin/ltx-story-manifest": {"PIL", "argparse", "datetime", "glob", "importlib.machinery",
                                   "json", "os", "re", "sys"},
    }
    for rel, names in baseline.items():
        assert _top_level_imports(os.path.join(WS, rel)) == names, rel
    for rel in ("bin/ltx-mlx-render", "bin/judge-story"):
        assert _all_imports(os.path.join(WS, rel)) == baseline[rel], rel
    assert _all_imports(os.path.join(WS, "story_engine.py")) == _top_level_imports(
        os.path.join(WS, "story_engine.py"))


def test_rst63b_every_suite_gets_a_temporary_catalog(request):
    assert "lora_catalog_isolation" in request.fixturenames
    path = request.getfixturevalue("lora_catalog_isolation")
    assert not path.startswith(WS + os.sep)
    assert path != os.path.dirname(seu.REAL_CATALOG)


def test_rst63_isolation(story_env):
    assert os.environ["HOME"] == story_env["home"]
    assert os.environ["CHARACTER_LIBRARY_DIR"] == story_env["lib"]
    assert os.environ["LORA_CATALOG_DIR"] == story_env["catalog"]
    assert re.fullmatch(r"http://127\.0\.0\.1:\d+", os.environ["QWEN_AGENT_DAEMON_URL"])
    assert os.environ["STORY_PIPELINE_LOGGED"] == "1"
    assert "ANTHROPIC_API_KEY" not in os.environ
    assert seu._stat_or_none(seu.REAL_CATALOG) == seu.REAL_CATALOG_STAT
    for module in ("tests/test_story_engine.py", "tests/test_lora_catalog.py"):
        with open(os.path.join(WS, module), encoding="utf-8") as f:
            source = f.read()
        assert "@pytest.fixture(autouse=True)\ndef story_env(monkeypatch, tmp_path):\n    return " \
               "seu.set_story_env(monkeypatch, tmp_path)\n" in source
