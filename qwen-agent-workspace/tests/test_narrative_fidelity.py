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


# --- NF1-NF4: the spoken lines of a narrative (QL1-QL4) -----------------------------------------

def _hockey(case):
    """The case.json of a recorded hockey run (spec 8.2)."""
    with open(os.path.join(FIXTURES, case, "case.json"), encoding="utf-8") as f:
        return json.load(f)


with open(os.path.join(FIXTURES, "narrative.txt"), encoding="utf-8") as _f:
    HOCKEY = _f.read().strip()
LINE1 = "Getting the best deal on hockey isn't a hat trick..."
LINE2 = "It's just FuboTV."


def _hockey_ctx(ws, case, **kw):
    """The StoryContext of a recorded hockey run (spec 8.1): chained, --speech-only, the case's
    panels, seconds, clip length and goal; keyword arguments replace fields."""
    c = _hockey(case)
    fields = dict(story_id=c["story_id"], mode="chained", panels=c["panels"],
                  seconds=c["seconds"], clip_seconds=c["frames"] / 24.0, narration="speech",
                  narrative=HOCKEY, goal=c["goal"])
    fields.update(kw)
    return seu.make_ctx(se, ws, **fields)


def test_nf1_the_hockey_narrative():
    assert se.classify_quotes(HOCKEY) == [("FuboTV", False), ("FuboTV", False), (LINE1, True),
                                          (LINE2, True)]
    assert se.spoken_lines(HOCKEY) == [LINE1, LINE2]
    assert se.line_words(LINE1) == ["getting", "the", "best", "deal", "on", "hockey", "isn't", "a",
                                    "hat", "trick"]


NF2_CASES = (
    ("She whispers, “Keep moving.”", ["Keep moving."]),
    ('"Run!" he shouts.', ["Run!"]),
    ('"Wait," she says, "I\'m coming."', ["Wait.", "I'm coming."]),
    ('He says to the old monk, "Rest here."', ["Rest here."]),
    ('"Hi," the old monk says.', ["Hi."]),
    ('A sign that says "OPEN" hangs on the door.', []),
    ('The scoreboard says "GOAL".', []),
    ('The shop called "Joe\'s" is closed.', []),
    ('He called out "Over here!"', ["Over here!"]),
    ('The monk says nothing, pointing at the "EXIT" sign.', []),
    ('He nods. "Go!" flashes on the screen.', []),
    ('He says "Keep moving.', []),
    ('He says "".', []),
    ('He says "...".', []),
    ('He says "Wait…"', ["Wait..."]),
    ('He says "Keep moving" and leaves.', ["Keep moving."]),
    ('A sign says "OPEN" and he says "Come in."', ["Come in."]),
    ('He looks at the "FuboTV" logo and says "Wow."', ["Wow."]),
    ('He wears a "Fubo" cap and says nothing.', []),
    ('He says nothing and points at the "EXIT" sign.', []),
    ('He calls his dog "Rex"', []),
    ('The crowd chants "Go Fubo!" as he says hello.', []),
    ('The crowd yells "Goal!"', []),
)


def test_nf2_which_quotes_are_spoken():
    for narrative, expected in NF2_CASES:
        assert se.spoken_lines(narrative) == expected, narrative
    assert se.spoken_lines(HOCKEY) == [LINE1, LINE2]


def test_nf3_line_words():
    for text in ("It's just FuboTV.", "IT’S JUST FUBOTV", "it‘s just fubotv...", "It's  just FuboTV…",
                 "it's, just; FuboTV!"):
        assert se.line_words(text) == ["it's", "just", "fubotv"], text
    assert se.line_words("Café au lait, s’il vous plaît.") == [
        "café", "au", "lait", "s'il", "vous", "plaît"]
    assert se.line_words("a well-known stop") == ["a", "well", "known", "stop"]
    assert se.line_words("...") == []


def test_nf4_required_lines(ws):
    for narration in (True, "speech"):
        assert se.required_lines(_hockey_ctx(ws, "hockey-2x145", narration=narration)) == [
            LINE1, LINE2], narration
    assert se.required_lines(_hockey_ctx(ws, "hockey-2x145", narration=False)) == []
    assert se.required_lines(seu.make_ctx(se, ws)) == []


# --- NF5, NF6, NF31: the pre-flight (QL5) ----------------------------------------------------------

COURIER_LINES = ('The courier says "Keep moving." Then he says "The gate is close." At the gate he '
                 'whispers "We made it."')
SIX_WORD_LINES = ('The courier says "Keep moving along the wet road." Then he says "The temple gate '
                  'is close now." At the gate he whispers "We made it here at last."')
OVER_CAP = "I carry a sealed letter from the harbour master for the abbot of this temple."
PANELS_PROBLEM = ("the narrative quotes 3 spoken lines, which need at least 2 panels of 6 seconds "
                  "(one panel speaks at most 14 words), but this movie has 1; use --panels 2 or "
                  "more, or longer clips (a larger --frames)")


def test_nf5_spoken_lines_problem(ws):
    def problem(narrative, **kw):
        return se.spoken_lines_problem(seu.make_ctx(se, ws, narrative=narrative, **kw))

    assert problem('The courier says "%s"' % OVER_CAP) == (
        "the narrative's spoken line 1 (\"%s\") is 15 words in 1 sentence; no clip fits it, because "
        "a spoken line has at most 14 words in at most 3 sentences; split it into shorter quoted "
        "lines in the narrative" % OVER_CAP)
    assert problem('The courier says "Stop. Wait. Look. Go."') == (
        "the narrative's spoken line 1 (\"Stop. Wait. Look. Go.\") is 4 words in 4 sentences; no "
        "clip fits it, because a spoken line has at most 14 words in at most 3 sentences; split it "
        "into shorter quoted lines in the narrative")
    ten = "I carry a letter for the abbot of this temple."
    assert problem('The courier says "%s"' % ten, seconds="4", clip_seconds=97 / 24.0) == (
        "the narrative's spoken line 1 (\"%s\") is 10 words in 1 sentence; a 4-second clip fits at "
        "most 9 words in 1 sentence; use longer clips (a larger --frames) or split it into shorter "
        "quoted lines in the narrative" % ten)
    assert problem('The courier says "%s"' % ten) is None
    assert problem(SIX_WORD_LINES, panels=1) == PANELS_PROBLEM
    assert problem(SIX_WORD_LINES, panels=2) is None
    assert problem(SIX_WORD_LINES, panels=1, narration=False) is None
    assert problem(seu.make_ctx(se, ws).narrative, panels=1) is None
    for case, panels in (("hockey-2x145", 2), ("hockey-2x145", 1), ("hockey-1x241", 1)):
        assert se.spoken_lines_problem(_hockey_ctx(ws, case, panels=panels)) is None, (case, panels)
    assert (se._n_sentences(1), se._n_sentences(2)) == ("1 sentence", "2 sentences")


def test_nf6_panels_needed():
    lib = character_lib
    six = 145 / 24.0
    assert se.panels_needed(lib, six, [LINE1, LINE2]) == 1
    assert se.panels_needed(lib, six, se.spoken_lines(SIX_WORD_LINES)) == 2
    four = ["Keep moving now, friend.", "The gate is close.", "We made it here.",
            "Please open the door."]
    assert se.panels_needed(lib, six, four) == 2
    assert se.panels_needed(lib, six, []) == 0
    assert se.panels_needed(lib, six, [OVER_CAP]) == 1


def test_nf31_an_infeasible_line_set_exits_2_before_any_call(ws, tmp_path, monkeypatch, capsys):
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(seu.plan_json("chained", 1))])
    ctx = seu.make_ctx(se, ws, panels=1, narrative=SIX_WORD_LINES)
    capsys.readouterr()
    rc, _advisories = se.run(ctx)
    assert rc == 2
    assert capsys.readouterr().err == "Error: " + PANELS_PROBLEM + "\n"
    assert seu.agent_log(log) == []
    with open(os.path.join(ctx.story_dir, "story_rounds", "run.json"), encoding="utf-8") as f:
        assert json.load(f)["exit"] == 2
