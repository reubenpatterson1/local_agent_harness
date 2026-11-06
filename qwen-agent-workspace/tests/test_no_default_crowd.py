"""Tests for the story-no-default-crowd change (docs/superpowers/specs/2026-11-06-story-no-
default-crowd-design.md: NCT1-NCT5): the robust story engine adds a crowd or other group of
people to a place only when the narrative mentions one.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_no_default_crowd.py
Stdlib plus pytest. No test reads the real HOME, renders or contacts a model server: every test
runs under the autouse story_env fixture (a temporary HOME, character library and LoRA catalog)
and builds prompts in memory.
"""

import importlib.machinery
import json
import os
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


se = _load("story_engine_for_no_default_crowd", "story_engine.py")

LOCATION_CLAUSE = ("names the period, the place, the ground and the light, and a crowd or other "
                   "group of people in the background only when the narrative mentions one.")
SPEAKING_IMAGE = " @@SPEAKER@@ is the only person in the foreground, facing the camera."
SPEAKING_IMAGE_SILENT = (" @@SPEAKER@@ is in the foreground, facing the camera; also in frame, "
                         "and silent: @@SILENT@@.")
CROWD_NARRATIVE = ("A young skater wins the final at a packed ice rink while a crowd of fans "
                   "cheers in the stands.")
CROWD_SETTING = ("The setting is an indoor ice rink in a modern city at night, smooth white ice "
                 "underfoot, a cheering crowd of fans in the stands in the background, under "
                 "bright floodlights.")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


def _strings(value):
    """Every str inside a str, dict, list or tuple value, in order."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _strings(v)]
    return []


def _plan(ctx, mode, n, speaker_beat=None, locations=None):
    raw = seu.plan_json(mode, n)
    if speaker_beat:
        raw["beats"][speaker_beat - 1]["speaker"] = "c1"
    if locations is not None:
        raw["locations"] = locations
    return se.normalize_plan(ctx, raw)[0]


def _parts(ctx, plan, n):
    return [se.empty_parts(ctx.mode, k, plan, ctx) for k in range(1, n + 1)]


def _key_line(prompt, key):
    return [line for line in prompt.split("\n") if line.startswith(key + ": ")][0]


# --- NCT1: the prompt texts (NC1, NC2, NC4) ----------------------------------------------------

def test_nct1_the_prompt_texts_name_no_default_crowd():
    assert LOCATION_CLAUSE + "@@LOCATION_FIXED@@\n" in se.PLAN_PROMPT_TEMPLATE
    assert "any crowd" not in se.PLAN_PROMPT_TEMPLATE
    assert se.PLAN_PROMPT_TEMPLATE.lower().count("crowd") == 2
    assert se.SPEAKING_IMAGE_SENTENCE == SPEAKING_IMAGE
    assert se.SPEAKING_IMAGE_SILENT_SENTENCE == SPEAKING_IMAGE_SILENT
    assert se.SPEAKING_SENTENCES["image"] == SPEAKING_IMAGE
    for name, value in sorted(vars(se).items()):
        if name.startswith("__") or name == "PLAN_PROMPT_TEMPLATE":
            continue
        for text in _strings(value):
            assert "crowd" not in text.lower(), name


# --- NCT2: a plan prompt for a narrative without a crowd (NC1) -------------------------------

def test_nct2_plan_prompts_have_only_the_conditional_crowd_clause(ws):
    for kw in (dict(mode="chained"), dict(mode="shots", panels=4), dict(mode="no_stills"),
               dict(mode="chained", seed_agent_image="/s/seed.png"),
               dict(mode="shots", panels=4, narration="speech")):
        ctx = seu.make_ctx(se, ws, **kw)
        assert "crowd" not in ctx.narrative.lower()
        prompt = se.build_plan_prompt(ctx, [], [])
        assert LOCATION_CLAUSE + "\nprops: " in prompt, kw
        assert "any crowd" not in prompt, kw
        assert prompt.lower().count("crowd") == 2, kw


# --- NCT3: the panel and critic prompts of a movie without a crowd (NC2, NC3) -----------------

def test_nct3_panel_and_critic_prompts_name_no_crowd(ws):
    prompts = []
    for mode, n, k in (("chained", 3, 1), ("shots", 3, 2), ("no_stills", 3, 2)):
        ctx = seu.make_ctx(se, ws, mode=mode, panels=n)
        plan = _plan(ctx, mode, n, speaker_beat=k)
        parts = _parts(ctx, plan, n)
        panels = [se.build_panel_prompt(ctx, plan, parts, j) for j in range(1, n + 1)]
        if mode != "no_stills":
            assert _key_line(panels[k - 1], "image").endswith(
                ' "the courier" is the only person in the foreground, facing the camera.'), mode
        prompts += panels + [se.build_critic_prompt(plan, se.assemble(ctx, plan, parts), ([], []))]
    ctx = seu.make_ctx(se, ws)
    plan = _plan(ctx, "chained", 3, speaker_beat=1)
    plan["beats"][0]["cast"] = ["c1", "c2"]
    silent = se.build_panel_prompt(ctx, plan, _parts(ctx, plan, 3), 1)
    assert _key_line(silent, "image").endswith(
        ' "the courier" is in the foreground, facing the camera; also in frame, and silent: '
        '"the old monk".')
    for prompt in prompts + [silent]:
        assert "crowd" not in prompt.lower()


# --- NCT4: a narrative with a crowd keeps it (NC1, NC5) ----------------------------------------

def test_nct4_a_crowd_in_the_narrative_reaches_the_setting_and_every_image(ws):
    ctx = seu.make_ctx(se, ws, mode="shots", panels=3, narrative=CROWD_NARRATIVE)
    prompt = se.build_plan_prompt(ctx, [], [])
    assert "\n" + CROWD_NARRATIVE + "\n" in prompt and LOCATION_CLAUSE in prompt
    plan = _plan(ctx, "shots", 3, locations=[{"id": "l1", "setting": CROWD_SETTING},
                                             {"id": "l2", "setting": seu.TEMPLE}])
    assert [l["setting"] for l in plan["locations"]] == [CROWD_SETTING, seu.TEMPLE]
    parts = _parts(ctx, plan, 3)
    for k in (1, 2, 3):
        assert dict(se.panel_fields(ctx, plan, parts, k))["Image"].startswith(CROWD_SETTING), k
    chained = seu.make_ctx(se, ws, narrative=CROWD_NARRATIVE)
    cplan = _plan(chained, "chained", 3, locations=[{"id": "l1", "setting": CROWD_SETTING},
                                                    {"id": "l2", "setting": seu.TEMPLE}])
    image = dict(se.panel_fields(chained, cplan, _parts(chained, cplan, 3), 1))["Image"]
    assert image.startswith(CROWD_SETTING)


# --- NCT5: the validators neither require nor reward a crowd (NC5) -----------------------------

def test_nct5_setting_checks_are_neutral_about_crowds(ws):
    for setting in (CROWD_SETTING, seu.HARBOUR, seu.TEMPLE):
        assert se._setting_problems(setting) == [], setting
        assert se._setting_length(setting) is None, setting
    assert se._setting_problems("A rink with fans.") == ['does not start with "The setting is"']
    for locations in (None, [{"id": "l1", "setting": CROWD_SETTING},
                             {"id": "l2", "setting": seu.TEMPLE}]):
        ctx = seu.make_ctx(se, ws)
        raw = seu.plan_json("chained", 3)
        if locations is not None:
            raw["locations"] = locations
        plan, shape = se.normalize_plan(ctx, raw)
        hard, advisory = se.plan_checks(ctx, plan, shape)
        assert [m for m in hard + advisory if " P4 " in m] == [], locations
    assert "crowd" not in json.dumps(se.PLAN_REFERENCE_PLAN).lower()
