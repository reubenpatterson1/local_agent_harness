"""Tests for narrative dialogue fidelity (docs/superpowers/specs/2026-10-26-narrative-dialogue-
fidelity-design.md, Section 8.1: NF1-NF37, without NF18, and the plan's Review Focus 1-5): the
narrative's quoted lines are required on-camera dialogue (Q1), speaking shots may move, the spoken
line is placed after the first action sentence, and crowds are setting, not cast.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py
Stdlib plus pytest. Every model call goes to the fake bin/qwen-agent of a temp workspace
(story_engine_testutil.make_ws); no test renders or reaches a model server, a daemon or the
Anthropic API, and every test runs under the autouse story_env fixture (a temporary HOME,
character library and LoRA catalog). The hockey fixtures under tests/fixtures/narrative_fidelity/
are verbatim copies of the two recorded 2026-10-26 runs, plus two hand-written plan replies.
"""

import copy
import importlib.machinery
import json
import os
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
FIXTURES = os.path.join(WS, "tests", "fixtures", "narrative_fidelity")
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402
import test_dialogue as dlg  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


character_lib = _load("character_lib_for_fidelity", "character_lib.py")
se = _load("story_engine_for_fidelity", "story_engine.py")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


# --- NF34, NF35: speech placement (SP-P) ------------------------------------------------------

PLAYER = "the FuboTV player"
STOP_MOTION = ("The FuboTV player skates forward, then halts in a sharp hockey stop that sprays ice "
               "mist into the air. He skates away from the camera. The FuboTV player faces the "
               "camera. The camera stays static.")
STOP_HEAD = ("The FuboTV player skates forward, then halts in a sharp hockey stop that sprays ice "
             "mist into the air. The FuboTV player faces the camera.")
STOP_TAIL = "He skates away from the camera. The camera stays static."


def test_nf34_insert_speech_after_the_first_action():
    lib = character_lib
    assert lib.insert_speech(STOP_MOTION, "S", [PLAYER], first_action=True) == (
        STOP_HEAD + " S " + STOP_TAIL)
    courier = ["the courier"]
    assert lib.insert_speech("The courier faces the camera. The courier runs. The courier waves. "
                             "The camera stays static.", "S", courier, first_action=True) == (
        "The courier runs. The courier faces the camera. S The courier waves. The camera stays "
        "static.")
    assert lib.insert_speech("The courier runs. The courier waves.", "S", courier,
                             first_action=True) == "The courier runs. S The courier waves."
    one = "The courier raises the letter. The courier faces the camera. The camera stays static."
    assert lib.insert_speech(one, "S", courier, first_action=True) == lib.insert_speech(
        one, "S", courier)
    said = 'The courier says, "Go."'
    assert lib.insert_speech(one, said, courier, first_action=False) == (
        "The courier raises the letter. The courier faces the camera. " + said
        + " The camera stays static.")
    assert lib.insert_speech(one, said, first_action=False) == (
        "The courier raises the letter. " + said + " The courier faces the camera. The camera "
        "stays static.")
    run = "The courier runs. The camera slowly pushes in. The camera holds."
    assert lib.insert_speech(run, said, courier, first_action=False) == (
        "The courier runs. " + said + " The camera slowly pushes in. The camera holds.")
    assert lib.insert_speech("The camera stays static. The camera holds.", said,
                             first_action=False) == (
        "The camera stays static. " + said + " The camera holds.")
    assert lib.insert_speech("The camera stays static.", said, first_action=False) == (
        "The camera stays static. " + said)
    he = 'He says: "Go."'
    assert lib.insert_speech("He runs. The camera tracks alongside the movement.", he,
                             first_action=False) == (
        'He runs. He says: "Go." The camera tracks alongside the movement.')
    assert lib.insert_speech("He runs. He jumps.", he, first_action=False) == (
        'He runs. He jumps. He says: "Go."')
    assert lib.is_facing_sentence("  the courier FACES the camera. ", courier)
    assert lib.is_facing_sentence("The FuboTV player faces the camera.", [PLAYER])
    assert not lib.is_facing_sentence("The courier faces the gate.", courier)
    assert not lib.is_facing_sentence("The courier faces the camera.", [])


HOCKEY_SETTING = ("The setting is a modern indoor ice hockey arena at night, a smooth white ice "
                  "rink floor, under bright overhead floodlights.")
PLAYER_DESC = ("a man in his late twenties with an athletic build wearing a reddish-orange and "
               "white hockey jersey")
HOCKEY_MANIFEST_PLAN = {"schema": "ltx-movie.plan.v1", "cast": [
    {"id": "c1", "phrase": PLAYER, "descriptor": PLAYER_DESC, "cast_name": None}],
    "beats": [{"cast": ["c1"]}, {"cast": ["c1"]}]}
CHAINED_STOP = """# The Stop

A hockey player stops short.

## Panel 1 — Skating In
Image: %s The FuboTV player glides forward on the ice.
Motion: The FuboTV player glides forward toward the camera. The camera stays static.
Narration: The crowd roars.

## Panel 2 — The Stop
Motion: %s
Dialogue: the FuboTV player: It's just FuboTV.
""" % (HOCKEY_SETTING, STOP_MOTION)
SHOTS_STOP = """# The Stop

A hockey player stops short.

## Characters
- "the FuboTV player": %s.

## Panel 1 — Skating In
Image: %s The FuboTV player glides forward on the ice. The shot is a medium shot.
Motion: The FuboTV player glides forward toward the camera. The camera stays static.
Narration: The crowd roars.

## Panel 2 — The Stop
Image: %s The FuboTV player halts on the ice. The FuboTV player faces the camera. The shot is a medium close-up.
Motion: %s
Dialogue: the FuboTV player: It's just FuboTV.
Narration: The crowd goes quiet.
""" % (PLAYER_DESC, HOCKEY_SETTING, HOCKEY_SETTING, STOP_MOTION)
NO_STILLS_STOP = """# The Stop

A hockey player stops short.

## Panel 1 — Skating In
Prompt: The FuboTV player glides forward toward the camera. The camera stays static.
Narration: The crowd roars.

## Panel 2 — The Stop
Prompt: The FuboTV player skates forward. He skates away from the camera. The FuboTV player faces the camera. The camera stays static.
Dialogue: the FuboTV player: It's just FuboTV.
"""


def test_nf35_manifest_places_the_line_after_the_first_action(tmp_path, monkeypatch):
    beats = STOP_HEAD + ' The FuboTV player says, "It\'s just FuboTV." ' + dlg.AC + " " + STOP_TAIL
    plain = STOP_HEAD + ' The FuboTV player says: "It\'s just FuboTV." ' + STOP_TAIL
    for delivery, motion in (("beats", beats), ("plain", plain)):
        story_md, images, mws = dlg._manifest_ws(tmp_path, monkeypatch, "nf35c", CHAINED_STOP,
                                                 plan=HOCKEY_MANIFEST_PLAN)
        extra = [] if delivery == "beats" else ["--speech-delivery", delivery]
        assert dlg.story_manifest.main(dlg._manifest_argv("nf35c", story_md, images,
                                                          extra=extra)) == 0
        panel = dlg._read_manifest(mws, "nf35c")["panels"][1]
        assert panel["motion_prompt"] == motion, delivery
        assert (panel["speaker"], panel["speech"]) == (PLAYER, "It's just FuboTV.")
    story_md, images, mws = dlg._manifest_ws(tmp_path, monkeypatch, "nf35s", SHOTS_STOP, images=2)
    assert dlg.story_manifest.main(dlg._manifest_argv("nf35s", story_md, images,
                                                      mode="shots")) == 0
    assert dlg._read_manifest(mws, "nf35s")["panels"][1]["motion_prompt"] == beats
    story_md, images, mws = dlg._manifest_ws(tmp_path, monkeypatch, "nf35n", NO_STILLS_STOP,
                                             plan=HOCKEY_MANIFEST_PLAN, images=0)
    assert dlg.story_manifest.main(dlg._manifest_argv("nf35n", story_md, images,
                                                      mode="no_images")) == 0
    assert dlg._read_manifest(mws, "nf35n")["panels"][1]["motion_prompt"] == (
        "The FuboTV player skates forward. He skates away from the camera. The FuboTV player "
        'faces the camera. The FuboTV player says, "It\'s just FuboTV." ' + dlg.AC
        + " The camera stays static.")
