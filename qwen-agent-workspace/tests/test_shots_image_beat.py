"""Tests for the shots Image: key line showing the beat's moment (SIB-T1..T6): every shots panel
prompt asks for what each character is doing when the beat begins; a seeded shots run gets the
change-only wording.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_shots_image_beat.py
Stdlib plus pytest. Prompts are built in memory under the autouse story_env fixture.
"""

import importlib.machinery
import json
import os
import re
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


se = _load("story_engine_for_shots_image_beat", "story_engine.py")

SEED = dict(seed_image="/s/seed.png", seed_agent_image="/s/seed-agent.png")
MOMENT = "first what each character is doing at the moment this panel's beat begins"
OLD_TAIL = "the lighting and colour palette; the camera viewpoint; and the rendering style"
SEEDED_HEAD = "written as a change to the movie's reference picture"
SEEDED_TAIL = "only the background, lighting or colour palette that this beat changes"


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


def _ctx(ws, mode, seeded=False, n=3):
    fields = dict(SEED) if seeded else {}
    return seu.make_ctx(se, ws, mode=mode, panels=n, **fields)


def _plan(ctx, n=3, speaker_beat=None, actions=None):
    raw = seu.plan_json(ctx.mode, n)
    if speaker_beat:
        raw["beats"][speaker_beat - 1]["speaker"] = raw["cast"][0]["id"]
    for k, action in (actions or {}).items():
        raw["beats"][k - 1]["action"] = action
    return se.normalize_plan(ctx, raw)[0]


def _parts(ctx, plan, n=3):
    parts = []
    for k in range(1, n + 1):
        reply = seu.panel_json(ctx.mode, k, plan["cast"][0]["phrase"])
        if "dialogue" in se.panel_keys(ctx, plan, k):
            reply["dialogue"] = "The letter is here."
        parts.append(se.parse_panel_reply(ctx, plan, k, json.dumps(reply)))
    return parts


def _prompt(ctx, plan, k):
    return se.build_panel_prompt(ctx, plan, _parts(ctx, plan), k)


def test_sib_t1_unseeded_shots_asks_for_the_beat_moment(ws):
    ctx = _ctx(ws, "shots")
    prompt = _prompt(ctx, _plan(ctx), 1)
    assert MOMENT in prompt
    assert OLD_TAIL in prompt
    assert "as a change to the movie's reference picture" not in prompt


def test_sib_t2_seeded_shots_asks_for_a_change_only_image(ws):
    ctx = _ctx(ws, "shots", True)
    prompt = _prompt(ctx, _plan(ctx), 1)
    assert SEEDED_HEAD in prompt
    assert SEEDED_TAIL in prompt
    assert "the rendering style" not in prompt


def test_sib_t3_chained_and_no_stills_are_unchanged(ws):
    assert se.KEY_LINE_TEMPLATES["chained_image"].startswith(
        "image: W1 to W2 words describing the opening frame as one still picture: where each ")
    for mode, ks in (("chained", (1, 2)), ("no_stills", (1,))):
        for seeded in (False, True):
            ctx = _ctx(ws, mode, seeded)
            plan = _plan(ctx)
            for k in ks:
                prompt = _prompt(ctx, plan, k)
                assert MOMENT not in prompt, (mode, k)
                assert SEEDED_HEAD not in prompt, (mode, k)
                assert SEEDED_TAIL not in prompt, (mode, k)


def test_sib_t4_placeholders_are_replaced_for_speaking_and_silent_panels(ws):
    for seeded in (False, True):
        ctx = _ctx(ws, "shots", seeded)
        plan = _plan(ctx, speaker_beat=2)
        for k in (1, 2):
            prompt = _prompt(ctx, plan, k)
            line = [ln for ln in prompt.split("\n") if ln.startswith("image: ")]
            assert len(line) == 1, (seeded, k)
            assert re.match(r"image: \d+ to \d+ words ", line[0]), line[0][:40]
            assert "@@" not in prompt and "W1" not in prompt and "W2" not in prompt


def test_sib_t5_each_panel_prompt_shows_its_own_beat(ws):
    ctx = _ctx(ws, "shots", True)
    plan = _plan(ctx, actions={1: "the courier lifts the sealed letter above the rain",
                               2: "the courier slides the letter under the temple door"})
    p1, p2 = _prompt(ctx, plan, 1), _prompt(ctx, plan, 2)
    assert "This panel's beat: the courier lifts the sealed letter above the rain" in p1
    assert "This panel's beat: the courier slides" not in p1
    assert "This panel's beat: the courier slides the letter under the temple door" in p2
    assert "This panel's beat: the courier lifts" not in p2
    assert SEEDED_HEAD in p1 and SEEDED_HEAD in p2


def test_sib_t6_zimage_unseeded_path_uses_the_unseeded_wording(ws):
    ctx = seu.make_ctx(se, ws, mode="shots", panels=3, seed_image=None)
    assert not se.seed_omits_identities(ctx)
    prompt = _prompt(ctx, _plan(ctx), 1)
    assert MOMENT in prompt and OLD_TAIL in prompt
    assert SEEDED_HEAD not in prompt
