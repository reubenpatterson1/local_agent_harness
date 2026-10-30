"""Tests for the location library's story use (docs/superpowers/specs/
2026-10-29-location-lora-design.md, Sections 4.3-4.6 and 6.7: LS1-LS14, with the plan's Review
Focus pins): the plan prompt's fixed places, plan normalisation, P21 location presence and the
L4 LoRA count.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_location_story.py
Stdlib plus pytest. No test reads the real HOME, renders, trains, runs Z-Image or the editor,
contacts a model server or touches port 8178: every model call goes to the fake bin/qwen-agent of
a temporary workspace (story_engine_testutil.make_ws), and every test runs under the autouse
story_env fixture (a temporary HOME, character library, location library and LoRA catalog). The
plan fixtures under tests/fixtures/location/ were written at d210c26, before story_engine.py was
edited (spec 6.3).
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


se = _load("story_engine_for_location_story", "story_engine.py")
cl = _load("character_lib_for_location_story", "character_lib.py")
FIXTURES = os.path.join(WS, "tests", "fixtures", "location")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    env = seu.set_story_env(monkeypatch, tmp_path)
    env["locations"] = os.path.join(str(tmp_path), "locations")
    os.makedirs(env["locations"], exist_ok=True)
    monkeypatch.setenv("LOCATION_LIBRARY_DIR", env["locations"])
    return env


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


# --- LS1: without locations, every plan prompt and plan.json is byte-identical (LK5) ---------

def test_ls1_without_locations_plan_prompts_and_plans_are_byte_identical(ws, story_env):
    seu.kyra(story_env["lib"])
    seu.ronin(story_env["lib"])
    members = cl.resolve_cast([(None, "kyra"), (None, "ronin")])
    for name, kw in (("plan_prompt_chained.txt", dict(mode="chained")),
                     ("plan_prompt_shots.txt", dict(mode="shots", panels=4)),
                     ("plan_prompt_chained_cast.txt", dict(mode="chained", members=members))):
        with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
            expected = f.read()
        assert se.build_plan_prompt(seu.make_ctx(se, ws, **kw), [], []) == expected, name
    plan, _shape = se.normalize_plan(seu.make_ctx(se, ws), seu.plan_json("chained", 3))
    with open(os.path.join(FIXTURES, "normalized_plan_chained.json"), encoding="utf-8") as f:
        assert json.dumps(plan, indent=2, sort_keys=True) == f.read()
    assert [sorted(entry) for entry in plan["locations"]] == [["id", "setting"]] * 2
