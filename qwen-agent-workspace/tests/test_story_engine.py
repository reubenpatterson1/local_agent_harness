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
    assert "beats: a list of EXACTLY 14 objects" in prompt and "at most 2.\n" in prompt
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
         ["plan: P3 cast entry: c2's descriptor: must be 8-60 words, got 3"]),
        (cast2(phrase="the monk!"),
         ["plan: P3 cast entry: c2's phrase word 'monk!' may contain only letters, digits, "
          "apostrophes and hyphens (phrase 'the monk!')"]),
        (setting("A rainy harbour town in modern Japan, wet cobblestones underfoot, boats behind, "
                 "under grey light."),
         ['plan: P4 setting sentence: l1\'s setting does not start with "The setting is"']),
        (setting("The setting is a harbour."),
         ["plan: P4 setting sentence: l1's setting is 5 words; it must be 12-45"]),
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
        assert prompt.count("\nnarration: one sentence of voice-over narration, 3 to 30 words.\n") == 1
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

    forty = " ".join(["The courier pedals onward"] * 10)
    cases = [
        ("chained", {"part_mut": part(2, motion=forty)},
         ["panel 2: N1 word count: Motion: is 40 words; it must be 15-35"]),
        ("chained", {"part_mut": part(2, motion="The courier waves at the woman beside the crates "
                                                "and keeps pedalling forward in the rain.")},
         ["panel 2: N2 referring phrase: Motion: names 'woman' outside every referring phrase; "
          "name each character by their exact phrase"]),
        ("chained", {"part_mut": part(2, motion="The courier pulls the grey hood tighter and "
                                                "pedals forward along the road past the boats.")},
         ["panel 2: N3 appearance: Motion: says 'grey'; panels after the first never re-describe "
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
        "panel 2: S4 motion length: Motion: is 46 words; it must be 10-25"]
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
