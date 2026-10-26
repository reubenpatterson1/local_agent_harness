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


# --- NF16, NF17, NF19: speaking shots may move (SM1-SM3, SM5) ------------------------------------

FACING = "The courier faces the camera."


def _speaking_beat(ctx, mode, n, k, **beat):
    """The normalized seu.plan_json plan whose beat k is spoken by c1 (beat: field overrides)."""
    raw = seu.plan_json(mode, n)
    raw["beats"][k - 1].update(speaker="c1", **beat)
    return se.normalize_plan(ctx, raw)[0]


def test_nf16_the_speaking_coercion_table(ws):
    ctx = seu.make_ctx(se, ws, mode="shots", panels=3)
    shots = {"extreme wide shot": "medium close-up", "wide shot": "medium close-up",
             "medium shot": "medium shot", "medium close-up": "medium close-up",
             "close-up": "close-up", "extreme close-up": "close-up", "": "medium close-up"}
    kept = ("static", "slow push-in", "slow pull-back", "tracking")
    assert sorted(shots) == sorted(se.SHOT_TYPES + ("",))
    for shot in se.SHOT_TYPES + ("",):
        for camera in se.CAMERA_KEYS + ("",):
            plan = _speaking_beat(ctx, "shots", 3, 2, shot=shot, camera=camera)
            want = (shots[shot], camera if camera in kept else "static")
            assert (plan["beats"][1]["shot"], plan["beats"][1]["camera"]) == want, (shot, camera)
            notes = []
            if want[0] != shot:
                notes.append("beat 2: P14 speaking beat: shot %s changed to %s so the speaker's "
                             "face stays readable" % (se._q(shot), se._q(want[0])))
            if want[1] != camera:
                notes.append("beat 2: P14 speaking beat: camera %s changed to 'static' so the "
                             "speaker's face stays readable" % se._q(camera))
            assert plan["speech_notes"] == notes, (shot, camera)
    plan = _speaking_beat(seu.make_ctx(se, ws), "chained", 3, 3, shot="extreme wide shot",
                          camera="slow pan left")
    assert (plan["beats"][2]["shot"], plan["beats"][2]["camera"]) == (
        "extreme wide shot", "slow pan left")
    assert plan["speech_notes"] == []
    assert se.speaking_camera({"camera": "tracking"}) == "tracking"
    assert se.speaking_camera({"camera": "slow tilt up"}) == "static"


def test_nf17_pasted_pieces_of_a_speaking_panel(ws):
    def pieces(mode, camera, field):
        ctx = seu.make_ctx(se, ws, mode=mode, panels=3)
        return se.pasted_pieces(ctx, _speaking_beat(ctx, mode, 3, 2, camera=camera), 2)[field]

    assert pieces("chained", "tracking", "motion") == [
        FACING, "The camera tracks alongside the movement."]
    assert pieces("chained", "slow pan left", "motion") == [FACING, "The camera stays static."]
    assert pieces("shots", "slow pull-back", "image")[-2] == FACING
    assert pieces("shots", "slow pull-back", "motion") == [FACING, "The camera pulls back."]
    assert pieces("no_stills", "static", "prompt")[-2:] == [FACING, "The camera stays static."]
    assert se.SPEAKING_CAMERA == dict(se.CAMERA_SENTENCES)["static"]
    assert not hasattr(se, "MOVING_FACING_SENTENCE")
    assert not hasattr(character_lib, "MOVING_FACING_SENTENCE")


def test_nf19_n17_accepts_a_moving_speaking_camera(ws):
    ctx = seu.make_ctx(se, ws)
    plan = _speaking_beat(ctx, "chained", 3, 2)
    lib = se._character_lib(WS)

    def n17(motion):
        fields = [("Motion", motion), ("Dialogue", "the courier: Keep moving.")]
        return se._field_checks(ctx, lib, plan, 2, "T", fields, {"Motion": motion}, ("N17",), [])

    assert n17("The courier waits. The camera slowly pans left.") == ([], [
        "panel 2: N17 speaking shot: Motion: has the camera direction 'The camera slowly pans "
        "left.' while 'the courier' speaks; while someone speaks the camera stays static, pushes "
        "in, pulls back or tracks them, so their face stays readable"])
    for camera in ("The camera tracks the courier.", "The camera pulls back.",
                   "The camera follows the courier.", "The camera slowly pushes in."):
        assert n17("The courier waits. " + camera) == ([], []), camera


# --- NF22, NF23, NF27, NF36: groups are setting; the plan advisories P15, Q2, Q3 (GC, QL12) -------

P15_2X145 = ("plan: P15 group cast: c2 'the cheering crowd' is a group of people, not a "
             "character, so it is removed from the cast and from beat 2; describe it in the "
             "setting sentence instead")


def _reply(case, name="plan_reply_1.txt"):
    """The parsed JSON of a fixture plan reply."""
    with open(os.path.join(FIXTURES, case, name), encoding="utf-8") as f:
        return se.extract_json(f.read())


def _entry(phrase, descriptor="a man in a red jersey with short dark hair", cast_name=None):
    return {"id": "c2", "phrase": phrase, "descriptor": descriptor, "cast_name": cast_name}


def test_nf22_is_group_entry():
    for phrase in ("the cheering crowd", "the fans'", "the hockey team", "the people",
                   "the spectators", "the fans’"):
        assert se.is_group_entry(_entry(phrase)), phrase
    for phrase in ("the team captain", "the crowd's leader", "the crowd’s leader", PLAYER):
        assert not se.is_group_entry(_entry(phrase)), phrase
    assert se.is_group_entry(_entry("the onlookers", "a dense group of spectators in the stands"))
    assert se.is_group_entry(_entry("the hecklers", "a dense group of hecklers in the stands"))
    assert se.is_group_entry(_entry("the hecklers", "A row of hecklers in winter coats"))
    assert not se.is_group_entry(_entry("the hiker", "a man with a group of friends"))
    assert not se.is_group_entry(_entry("the crowd", cast_name="crowd"))


def test_nf23_normalization_drops_the_crowd(ws):
    ctx = _hockey_ctx(ws, "hockey-2x145")
    plan, shape = se.normalize_plan(ctx, _reply("hockey-2x145"))
    assert shape == []
    assert [c["id"] for c in plan["cast"]] == ["c1"]
    assert plan["cast_notes"] == [P15_2X145]
    assert plan["beats"][1]["cast"] == ["c1"]
    advisory = se.plan_checks(ctx, plan, shape)[1]
    assert P15_2X145 in advisory and not [m for m in advisory if " P12 " in m]
    raw = _reply("hockey-2x145")
    raw["beats"][1]["speaker"] = "c9"
    plan, shape = se.normalize_plan(ctx, raw)
    not_cast = "beat 2: P14 speaking beat: speaker 'c9' is not a cast id, so nobody speaks in this beat"
    assert plan["speech_notes"] == [not_cast]
    assert se.plan_checks(ctx, plan, shape)[1][-2:] == [P15_2X145, not_cast]
    assert list(plan)[-2:] == ["cast_notes", "speech_notes"]
    many = {"cast": [_entry(PLAYER, cast_name=None), _entry("the fans", "a sea of fans")],
            "beats": [{"cast": ["c1", "c2"]}, {"cast": ["c2", "c2"]}, {"cast": ["c1"]}]}
    many["cast"][0]["id"] = "c1"
    assert se.drop_groups(many) == [
        "plan: P15 group cast: c2 'the fans' is a group of people, not a character, so it is "
        "removed from the cast and from beats 1, 2; describe it in the setting sentence instead"]
    assert [b["cast"] for b in many["beats"]] == [["c1"], [], ["c1"]]
    alone = {"cast": [_entry("the audience")], "beats": [{"cast": []}]}
    assert se.drop_groups(alone) == [
        "plan: P15 group cast: c2 'the audience' is a group of people, not a character, so it is "
        "removed from the cast; describe it in the setting sentence instead"]
    assert alone["cast"] == []


Q2_HOCKEY = ("plan: Q2 spoken lines: the narrative quotes 2 spoken line(s), but --no-narration "
             "makes this movie silent, so none of them is spoken")


def test_nf27_q2_no_narration_drops_the_spoken_lines(ws):
    for narration, expected in ((False, [Q2_HOCKEY]), ("speech", []), (True, [])):
        ctx = _hockey_ctx(ws, "hockey-2x145", narration=narration)
        plan, shape = se.normalize_plan(ctx, seu.plan_json("chained", 2))
        hard, advisory = se.plan_checks(ctx, plan, shape)
        assert [m for m in advisory if " Q2 " in m] == expected, narration
        assert not [m for m in hard if " Q2 " in m]


def test_nf36_q3_an_odd_quote_count(ws):
    q3 = ("plan: Q3 quotes: the narrative has an odd number of double quotes (1), so its last "
          "quote is unmatched and ignored; close every quoted line")
    for narration in (True, "speech", False):
        ctx = seu.make_ctx(se, ws, narrative='He says "Go.', narration=narration)
        plan, shape = se.normalize_plan(ctx, seu.plan_json("chained", 3))
        assert [m for m in se.plan_checks(ctx, plan, shape)[1] if " Q3 " in m] == [q3], narration
        ctx = _hockey_ctx(ws, "hockey-2x145", narration=narration)
        plan, shape = se.normalize_plan(ctx, seu.plan_json("chained", 2))
        assert not [m for m in se.plan_checks(ctx, plan, shape)[1] if " Q3 " in m], narration
    ctx = seu.make_ctx(se, ws, narrative="He says “Go.” Then “Stop.")
    plan, shape = se.normalize_plan(ctx, seu.plan_json("chained", 3))
    assert [m for m in se.plan_checks(ctx, plan, shape)[1] if " Q3 " in m] == [
        q3.replace("(1)", "(3)")]


def test_nf22b_group_head_word():
    for phrase in ("the captain of the team", "a member of the crowd",
                   "the lead singer of the band", "the fan from the crowd"):
        assert not se.is_group_entry(_entry(phrase)), phrase
    assert se.is_group_entry(_entry("the fans,"))
    assert se.is_group_entry(_entry("the cheering crowd"))
    for descriptor in ("a mass of curly hair framing a pale face", "a thin line of stubble",
                       "a sea of freckles"):
        assert not se.is_group_entry(_entry("the hiker", descriptor)), descriptor


# --- NF13, NF14, NF26, Review Focus 3: lines in the plan (QL7, QL8, 2.1) ---------------------------

def _lines_plan(ws, narrative, beats, n=3, **ctx_kw):
    """(ctx, normalized plan) of seu.plan_json("chained", n) under narrative; beats maps a beat
    number to the fields that replace that beat's."""
    ctx = seu.make_ctx(se, ws, panels=n, narrative=narrative, **ctx_kw)
    raw = seu.plan_json("chained", n)
    for k, fields in beats.items():
        raw["beats"][k - 1].update(fields)
    return ctx, se.normalize_plan(ctx, raw)[0]


def _fixture_text(case, name):
    with open(os.path.join(FIXTURES, case, name), encoding="utf-8") as f:
        return f.read()


COURIER_SPOKEN = ["Keep moving.", "The gate is close.", "We made it."]


def test_nf13_coerce_speakers_with_lines(ws):
    every = dict((k, {"speaker": "c1", "lines": [k]}) for k in (1, 2, 3))
    _ctx, plan = _lines_plan(ws, COURIER_LINES, every)
    assert plan["spoken_lines"] == COURIER_SPOKEN
    assert [(b["speaker"], b["lines"]) for b in plan["beats"]] == [("c1", [1]), ("c1", [2]),
                                                                    ("c1", [3])]
    assert plan["speech_notes"] == [] and se.line_assignment_problems(plan) == []
    _ctx, plan = _lines_plan(ws, COURIER_LINES, {1: {"speaker": "c1", "lines": [2, 1]},
                                                 2: {"speaker": "c1", "lines": [2]},
                                                 3: {"speaker": "c1", "lines": [4]}})
    assert [(b["speaker"], b["lines"]) for b in plan["beats"]] == [("c1", [1, 2]), ("c1", []),
                                                                    ("c1", [])]
    assert plan["speech_notes"] == [
        "beat 2: P14 speaking beat: line 2 dropped: an earlier beat already speaks line 2 or a "
        "later one",
        "beat 3: P14 speaking beat: line 4 dropped: the narrative has no spoken line 4"]
    assert se.line_assignment_problems(plan) == [
        'plan: Q1 spoken line: spoken line 3 "We made it." is in no beat\'s lines; put 3 in the '
        "lines of the beat whose action surrounds it in the narrative, and give that beat a "
        "speaker"]
    _ctx, plan = _lines_plan(ws, COURIER_LINES, {1: {"lines": [1]}})
    assert (plan["beats"][0]["speaker"], plan["beats"][0]["lines"]) == ("c1", [1])
    assert plan["speech_notes"] == [
        "beat 1: P14 speaking beat: speaker set to 'c1', the only character in the beat, to say "
        "line(s) 1"]
    _ctx, plan = _lines_plan(ws, COURIER_LINES, {1: {"cast": ["c1", "c2"], "lines": [1, 2]}})
    assert (plan["beats"][0]["speaker"], plan["beats"][0]["lines"]) == ("", [])
    assert plan["speech_notes"] == [
        "beat 1: P14 speaking beat: line(s) 1, 2 dropped: the beat has no speaker"]
    seven = ('The courier says "Keep moving along the wet harbour road." Then he says "The temple '
             'gate is close to us."')
    _ctx, plan = _lines_plan(ws, seven, {1: {"speaker": "c1", "lines": [1, 2]}})
    assert plan["beats"][0]["lines"] == [1]
    assert plan["speech_notes"] == [
        "beat 1: P14 speaking beat: line 2 dropped: together with the beat's other lines it does "
        "not fit a 6-second clip"]
    _ctx, plan = _lines_plan(ws, seu.make_ctx(se, ws).narrative, every)
    assert [(b["speaker"], b["lines"]) for b in plan["beats"]] == [("c1", [])] * 3
    assert plan["speech_notes"] == [] and plan["spoken_lines"] == []
    _ctx, plan = _lines_plan(ws, COURIER_LINES, every, narration=False)
    assert [(b["speaker"], b["lines"]) for b in plan["beats"]] == [("", [])] * 3
    assert plan["spoken_lines"] == []
    assert se._clean_lines("1") == [] and se._clean_lines(["2", True, 1.0, 3]) == [2, 3]
    assert se._clean_lines(None) == [] and se._clean_lines([" 4 ", "x", -1, "²"]) == [4, -1]
    assert se._nums([1, 2, 3]) == "1, 2, 3"


def test_nf14_the_plan_retry_gate(ws, tmp_path, monkeypatch):
    recorded = seu.answer(_fixture_text("hockey-2x145", "plan_reply_1.txt"))
    fixed = seu.answer(_fixture_text("hockey-2x145", "plan_reply_fixed.json"))
    ctx = _hockey_ctx(ws, "hockey-2x145")
    log = seu.script_agent(monkeypatch, tmp_path, plan=[recorded, fixed])
    found, why = se._Run(ctx, "").plan_round()
    calls = seu.agent_log(log)
    assert why is None and [c["stage"] for c in calls] == ["plan", "plan"]
    retry = calls[1]["argv"][calls[1]["argv"].index("--user-prompt") + 1]
    assert ('- plan: Q1 spoken line: spoken line 1 "%s" is in no beat\'s lines; put 1 in the '
            "lines of the beat whose action surrounds it in the narrative, and give that beat a "
            "speaker\n" % LINE1) in retry
    assert '- plan: Q1 spoken line: spoken line 2 "%s"' % LINE2 in retry
    assert [b["lines"] for b in found[0]["beats"]] == [[1], [2]] and found[2] == []
    log = seu.script_agent(monkeypatch, tmp_path, plan=[fixed])
    found, why = se._Run(ctx, "").plan_round()
    assert len(seu.agent_log(log)) == 1 and [b["lines"] for b in found[0]["beats"]] == [[1], [2]]


def test_nf26_an_older_plan_json_loads(ws):
    ctx = _hockey_ctx(ws, "hockey-2x145")
    plan, _shape = se.normalize_plan(ctx, _reply("hockey-2x145", "plan_reply_fixed.json"))
    del plan["spoken_lines"], plan["cast_notes"]
    for beat in plan["beats"]:
        del beat["lines"]
    with open(os.path.join(ctx.story_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f)
    loaded = se.load_plan(ctx)
    assert [b["lines"] for b in loaded["beats"]] == [[], []]
    assert (loaded["spoken_lines"], loaded["cast_notes"]) == ([], [])


def test_review_focus_3_the_planner_gives_a_line_to_the_crowd(ws):
    # The planner makes the crowd (a group, dropped by P15) the speaker of the beat that holds
    # line 2. Expected: the line stays on that beat, spoken by its one remaining character, and
    # one P15 note says so (controller ruling, plan Spec amendment 1); with no individual left,
    # the note says the beat has no speaker.
    raw = _reply("hockey-2x145", "plan_reply_fixed.json")
    raw["beats"][1]["speaker"] = "c2"
    plan, _shape = se.normalize_plan(_hockey_ctx(ws, "hockey-2x145"), raw)
    assert plan["cast_notes"] == [P15_2X145]
    beat = plan["beats"][1]
    assert (beat["speaker"], beat["lines"], beat["cast"]) == ("c1", [2], ["c1"])
    assert plan["speech_notes"] == [
        "beat 2: P15 group cast: the cheering crowd is part of the setting, not a speaker; the "
        "beat's line goes to the FuboTV player"]
    assert se.line_assignment_problems(plan) == []
    no_speaker = ("beat 2: P15 group cast: the cheering crowd is part of the setting, not a "
                  "speaker; the beat has no speaker")
    for speaker in ("c2", "The Cheering Crowd"):
        raw = _reply("hockey-2x145")
        raw["beats"][1]["speaker"] = speaker
        plan, _shape = se.normalize_plan(_hockey_ctx(ws, "hockey-2x145"), raw)
        assert (plan["beats"][1]["speaker"], plan["speech_notes"]) == ("", [no_speaker]), speaker
    raw = seu.plan_json("chained", 3)
    raw["cast"].append({"id": "c3", "phrase": "the harbour crowd",
                        "descriptor": "a crowd of fishermen in yellow oilskins"})
    raw["beats"][0].update(cast=["c1", "c2", "c3"], speaker="c3", lines=[1])
    plan, _shape = se.normalize_plan(seu.make_ctx(se, ws, narrative=COURIER_LINES), raw)
    assert (plan["beats"][0]["speaker"], plan["beats"][0]["lines"]) == ("", [])
    assert plan["speech_notes"] == [
        "beat 1: P15 group cast: the harbour crowd is part of the setting, not a speaker; the beat "
        "has no speaker",
        "beat 1: P14 speaking beat: line(s) 1 dropped: the beat has no speaker"]


def test_nf22b_cut_words_and_collective_heads():
    for phrase in ("a group of fans", "a sea of fans", "a line of commuters",
                   "the fans in the stands", "the crowd from the bleachers", "the cheering crowd"):
        assert se.is_group_entry(_entry(phrase)), phrase
    for phrase in ("the captain of the team", "a member of the crowd",
                   "the lead singer of the band", "the man in the crowd", "the woman in grey"):
        assert not se.is_group_entry(_entry(phrase)), phrase


# --- NF12: the plan prompt (QL6, 7.1) -------------------------------------------------------------

CAST_LINE = ("cast: a list with one object per individual character who acts or speaks on screen, "
             "with the keys id, phrase and descriptor; a group of people (a crowd, an audience, "
             "fans, spectators, a team) is never a cast entry, and belongs in the setting sentence "
             "of its place. id is c1, c2, c3 and so on, in order. phrase is the character's "
             "referring phrase:")
SETTING_LINE = ("names the period, the place, the ground, the light and any crowd or other group "
                "of people in the background.\n")
SPEAKER_RULE = (" speaker is the id of the one character who says something aloud on screen "
                "during the beat, or an empty string when nobody speaks; give a speaker only where "
                "a spoken line moves the story. A beat with a speaker shows only that character "
                "(its cast is just their id), facing the camera, in a medium shot, medium close-up "
                "or close-up; the speaker may move during the beat, and the camera may stay static, "
                "push in, pull back or track them, as long as their face stays in frame and lit "
                "while they speak.")
LINES_RULE = (" lines is the list of the numbers of the spoken lines above that the speaker says "
              "aloud during the beat, in order, or an empty list. Every spoken line belongs to "
              "exactly one beat, in the narrative's order: give each line to the beat whose action "
              "surrounds it in the narrative, and give a speaker to every beat with lines and to no "
              "other beat. A beat may hold two or more consecutive lines only when together they "
              "are at most @@LINE_WORDS@@ words. Give each line its own beat whenever there are at "
              "least as many beats as lines.")
SPOKEN_BLOCK = ("\n\nSpoken lines (the narrative quotes these words; the movie must speak every one "
                "of them on camera, word for word, in this order):\n1. \"%s\"\n2. \"%s\""
                % (LINE1, LINE2))


def test_nf12_the_plan_prompt(ws):
    assert (se.SPEAKER_RULE, se.LINES_RULE) == (SPEAKER_RULE, LINES_RULE)
    assert se.spoken_lines_block([LINE1, LINE2]) == SPOKEN_BLOCK
    assert se.spoken_lines_block([]) == ""
    prompt = se.build_plan_prompt(_hockey_ctx(ws, "hockey-2x145"), [], [])
    assert ("Narrative to adapt:\n" + HOCKEY + SPOKEN_BLOCK + "\n\nThe target output goal is "
            ) in prompt
    assert "location, cast, speaker and lines. index runs from 1 to 2." in prompt
    assert ("at most 4." + SPEAKER_RULE + LINES_RULE.replace("@@LINE_WORDS@@", "13") + "\n"
            ) in prompt
    assert CAST_LINE in prompt and SETTING_LINE in prompt and "@@" not in prompt
    one = se.build_plan_prompt(_hockey_ctx(ws, "hockey-1x241"), [], [])
    assert "together they are at most 14 words." in one and "@@" not in one
    quiet = se.build_plan_prompt(seu.make_ctx(se, ws), [], [])
    assert "Spoken lines (" not in quiet and "lines is the list" not in quiet
    assert "location, cast and speaker. index runs" in quiet
    assert ("at most 4." + SPEAKER_RULE + "\n") in quiet
    assert CAST_LINE in quiet and SETTING_LINE in quiet and "@@" not in quiet
    silent = se.build_plan_prompt(_hockey_ctx(ws, "hockey-2x145", narration=False), [], [])
    assert "Spoken lines (" not in silent and "lines is the list" not in silent
    assert "location, cast and speaker. index runs" in silent
    assert ("at most 4." + se.SILENT_SPEAKER_RULE + "\n") in silent


# --- NF15, NF20: the panel writer (QL9, SM4, 7.2) ---------------------------------------------------

DIALOGUE_FIXED = ("dialogue: exactly @@LINE@@ -- the narrative's own words, which @@SPEAKER@@ says "
                  "aloud in this panel; copy them unchanged, because the pipeline uses the "
                  "narrative's words whatever this field holds.")
SPEAKING_ACTION = (" In this panel @@SPEAKER@@ speaks the dialogue: they may move as the beat "
                   "says, but write the motion so that their face is toward the camera, in frame "
                   "and lit while they speak -- a speaker who approaches the camera speaks once "
                   "close -- and do not write the spoken words or a speaking verb here; the "
                   "pipeline adds them.")
SPEAKING_IMAGE = (" @@SPEAKER@@ is the only person in the foreground, facing the camera; any crowd "
                  "stays in the background.")
SPEECH_FRAMING = (" Characters speak on screen in this movie: keep each character within medium "
                  "to close-up range of the camera while they speak, and never have a character "
                  "shrink into the distance or leave the frame before their line ends.")


def _panel_reply(case, k):
    """The parsed JSON of a recorded panel reply."""
    return se.extract_json(_fixture_text(case, "panel_%02d_reply_1.txt" % k))


def test_nf15_the_writer_gets_the_narrative_words(ws):
    ctx = _hockey_ctx(ws, "hockey-2x145")
    plan, _shape = se.normalize_plan(ctx, _reply("hockey-2x145", "plan_reply_fixed.json"))
    assert (se.assigned_dialogue(plan, 1), se.assigned_dialogue(plan, 2)) == (LINE1, LINE2)
    parts = [se.empty_parts(ctx.mode, k, plan, ctx) for k in (1, 2)]
    assert [p["dialogue"] for p in parts] == [LINE1, LINE2]
    assert "dialogue" not in se.empty_parts(ctx.mode, 2, plan)
    prompt = se.build_panel_prompt(ctx, plan, parts, 2)
    assert ('\ndialogue: exactly "It\'s just FuboTV." -- the narrative\'s own words, which "the '
            'FuboTV player" says aloud in this panel; copy them unchanged, because the pipeline '
            "uses the narrative's words whatever this field holds.\n") in prompt
    assert "@@" not in prompt and "\ndialogue: the exact words" not in prompt
    assert '\ndialogue: exactly "%s" -- ' % LINE1 in se.build_panel_prompt(ctx, plan, parts, 1)
    reply = _panel_reply("hockey-2x145", 2)
    for written in (dict(reply, dialogue="Something else."), reply):
        assert se.parse_panel_reply(ctx, plan, 2, json.dumps(written))["dialogue"] == LINE2
    parts[1] = dict(se.parse_panel_reply(ctx, plan, 2, json.dumps(reply)), dialogue="Other words.")
    assert dict(se.panel_fields(ctx, plan, parts, 2))["Dialogue"] == PLAYER + ": " + LINE2
    recorded, _shape = se.normalize_plan(ctx, _reply("hockey-2x145"))
    assert se.assigned_dialogue(recorded, 1) == ""
    assert ('\ndialogue: the exact words "the FuboTV player" says aloud in this panel: at most 14 '
            "words") in se.build_panel_prompt(ctx, recorded, parts, 1)
    written = se.parse_panel_reply(ctx, recorded, 1, json.dumps(_panel_reply("hockey-2x145", 1)))
    assert written["dialogue"] == "Getting the best deal on hockey isn't a hat trick."


def test_nf20_the_panel_prompt_constants():
    assert se.KEY_LINE_TEMPLATES["dialogue_fixed"] == DIALOGUE_FIXED
    assert se.SPEAKING_ACTION_SENTENCE == SPEAKING_ACTION
    assert se.SPEAKING_IMAGE_SENTENCE == SPEAKING_IMAGE
    assert se.SPEECH_FRAMING_SENTENCE == SPEECH_FRAMING
    base = se.KEY_LINE_TEMPLATES["no_stills_prompt"]
    assert se.KEY_LINE_TEMPLATES["no_stills_prompt_speaking"] == base.replace(
        "carries enough separate beats to fill the full @@SECONDS@@ seconds, links them with "
        "temporal connectors (initially, as, then, while, a moment later), ",
        "fills the full @@SECONDS@@ seconds with the one continuous movement of @@SPEAKER@@ that "
        "the beat describes, keeping their face toward the camera while they speak, ")
    assert se.KEY_LINE_TEMPLATES["no_stills_prompt_speaking"] != base
    assert se.SPEAKING_SENTENCES == {"image": SPEAKING_IMAGE, "motion": SPEAKING_ACTION,
                                     "prompt": se.SPEAKING_PROMPT_SENTENCE}
    for text in (DIALOGUE_FIXED, SPEAKING_ACTION, SPEAKING_IMAGE, SPEECH_FRAMING,
                 se.KEY_LINE_TEMPLATES["no_stills_prompt_speaking"]):
        assert "slowly" not in text.lower()

# --- NF7-NF11, Review Focus 1, 2: Q1 (QL10, QL14) ----------------------------------------------------

T2_2X145 = ("panel 2: T2 action amount: Motion: holds 3 actions; a 6-second clip fits at most 2, "
            "so cut the extra actions and keep every other sentence word for word")
Q1_MISSING = ("story: Q1 spoken line: the narrative's spoken line %d \"%s\" is in no panel's "
              "Dialogue:; give it word for word to the panel that shows it being said (Dialogue: "
              "<speaker's referring phrase>: <the line>)")
Q1_ORDER = ("story: Q1 spoken line: the narrative's spoken line %d \"%s\" is spoken out of the "
            "narrative's order; the Dialogue: fields must say the spoken lines in the order the "
            "narrative gives them")
PANEL2_FIXED = ("Motion: The FuboTV player skates forward, then halts in a sharp hockey stop that "
                "sprays ice mist into the air. He holds the pose, then skates away from the camera. "
                "The FuboTV player faces the camera. The camera stays static.\n"
                "Dialogue: the FuboTV player: It's just FuboTV.\n")


def _say(line):
    return PLAYER + ": " + line


def _replay(ws, case, reply_file, assign=False, **ctx_kw):
    """(state, plan, notes) of a recorded run's round 0 replayed through the current checks (spec
    8.1): the plan reply normalized; with assign, assign_missing_lines (QL8b), its notes added to
    speech_notes as _Run.go() adds them; the recorded parts.json panels; every beat with lines
    given its assigned dialogue; then _Run.make_state."""
    ctx = _hockey_ctx(ws, case, **ctx_kw)
    plan, shape = se.normalize_plan(ctx, _reply(case, reply_file))
    notes = se.assign_missing_lines(ctx, plan) if assign else []
    plan["speech_notes"] += notes
    parts = [dict((key, value) for key, value in panel.items() if key != "index")
             for panel in json.loads(_fixture_text(case, "parts.json"))["panels"]]
    for k, beat in enumerate(plan["beats"], start=1):
        if beat["lines"]:
            parts[k - 1]["dialogue"] = se.assigned_dialogue(plan, k)
    runner = se._Run(ctx, "")
    runner.shape = shape
    return runner.make_state(0, plan, parts), plan, notes


def test_nf7_spoken_line_problems(ws):
    assert (se.Q1_MISSING, se.Q1_ORDER) == (Q1_MISSING, Q1_ORDER)
    ctx = _hockey_ctx(ws, "hockey-2x145")

    def q1(*dialogues):
        return se.spoken_line_problems(ctx, character_lib, [PLAYER], list(dialogues))

    assert q1(_say(LINE1), _say(LINE2)) == []
    assert q1(_say(LINE1 + " " + LINE2), "") == []
    assert q1(_say(LINE1), "") == [Q1_MISSING % (2, LINE2)]
    assert q1(_say(LINE2), _say(LINE1)) == [Q1_ORDER % (2, LINE2)]
    assert q1(_say("Getting the best deal on hockey"), _say("isn't a hat trick... " + LINE2)) == [
        Q1_MISSING % (1, LINE1)]
    assert q1(_say("Hey there. " + LINE1 + " Right?"), _say("Yes. " + LINE2 + " Go.")) == []
    assert q1(_say("GETTING the best deal on hockey, isn’t a hat trick"), _say("it's JUST fubotv!")
              ) == []
    assert q1("the stranger: " + LINE1 + " " + LINE2, "") == [Q1_MISSING % (1, LINE1),
                                                              Q1_MISSING % (2, LINE2)]
    assert q1("", "") == [Q1_MISSING % (1, LINE1), Q1_MISSING % (2, LINE2)]
    assert q1() == [Q1_MISSING % (1, LINE1), Q1_MISSING % (2, LINE2)]
    twice = seu.make_ctx(se, ws, narrative='The courier says "Go." Then he says "Go."')
    for dialogues, expected in ((["the courier: Go."], [Q1_ORDER % (2, "Go.")]),
                                (["the courier: Go. Go."], []),
                                (["the courier: Go.", "the courier: Go."], [])):
        assert se.spoken_line_problems(twice, character_lib, ["the courier"], dialogues) == (
            expected), dialogues
    silent = _hockey_ctx(ws, "hockey-2x145", narration=False)
    assert se.spoken_line_problems(silent, character_lib, [PLAYER], []) == []
    assert se._find_run(["a", "b", "a", "b"], ["a", "b"], 1) == 2
    assert se._find_run(["a", "b"], ["b", "a"], 0) is None
    assert se.GENERATION_CHECKS[-2:] == ("Q1", "N19") and se.RECHECK_IDS[-2:] == ("Q1", "N19")
    assert "Q1" not in se.PLAN_FREE_IDS and "Q1" not in se.NON_BLOCKING_IDS
    assert "Q1" not in se.REPAIR_IDS


def test_nf8_replay_the_recorded_2x145_plan(ws):
    state, plan, _notes = _replay(ws, "hockey-2x145", "plan_reply_1.txt")
    q1 = Q1_MISSING % (2, LINE2)
    assert state["hard"] == [T2_2X145, q1]
    assert se.blocking(state["hard"]) == [q1]
    assert se.parse_violation(q1) == {"id": "Q1", "name": "spoken line", "scope": "story",
                                      "index": None, "message": q1}
    assert P15_2X145 in state["advisory"]
    assert not [m for m in state["advisory"] if " P12 " in m]
    assert plan["beats"][1]["cast"] == ["c1"]


def test_nf9_replay_the_recorded_1x241_plan(ws):
    state, _plan, _notes = _replay(ws, "hockey-1x241", "plan_reply_1.txt")
    assert state["hard"] == [Q1_MISSING % (1, LINE1), Q1_MISSING % (2, LINE2)]
    assert se.blocking(state["hard"]) == state["hard"]


def test_nf10_replay_the_fixed_plans(ws):
    state, _plan, _notes = _replay(ws, "hockey-2x145", "plan_reply_fixed.json")
    assert state["hard"] == [T2_2X145] and se.blocking(state["hard"]) == []
    assert "Dialogue: the FuboTV player: " + LINE1 + "\n" in state["text"]
    assert state["text"].endswith(PANEL2_FIXED)
    state, plan, _notes = _replay(ws, "hockey-1x241", "plan_reply_fixed.json")
    assert state["hard"] == [] and plan["speech_notes"] == []
    assert (plan["beats"][0]["shot"], plan["beats"][0]["camera"]) == ("medium shot", "tracking")
    assert ("Motion: The FuboTV player skates forward toward the camera, then stops abruptly in a "
            "hockey stop, spraying ice mist into the air. He then skates away from the camera. The "
            "FuboTV player faces the camera. The camera tracks alongside the movement.\n"
            "Dialogue: the FuboTV player: " + LINE1 + " " + LINE2 + "\n") in state["text"]
    image = [l for l in state["text"].split("\n") if l.startswith("Image: ")]
    assert len(image) == 1
    assert image[0].endswith(" The FuboTV player faces the camera. The shot is a medium shot.")


def _recheck(ctx, capsys, text, check_ctx=None):
    """(rc, captured) of se.recheck on text written as the story's story.md."""
    with open(os.path.join(ctx.story_dir, "story.md"), "w", encoding="utf-8") as f:
        f.write(text)
    capsys.readouterr()
    rc, _advisories = se.recheck(check_ctx or ctx, lambda path, panels, no_stills=False: [])
    return rc, capsys.readouterr()


def test_nf11_recheck_with_a_plan(ws, capsys):
    state, plan, _notes = _replay(ws, "hockey-2x145", "plan_reply_fixed.json")
    ctx = _hockey_ctx(ws, "hockey-2x145")
    se._write_json(os.path.join(ctx.story_dir, "plan.json"), plan)
    rc, out = _recheck(ctx, capsys, state["text"])
    assert rc == 0 and " Q1 " not in out.out + out.err
    cut = state["text"].replace("Dialogue: the FuboTV player: It's just FuboTV.\n", "")
    assert cut != state["text"]
    rc, out = _recheck(ctx, capsys, cut)
    assert rc == 2 and ("  - " + Q1_MISSING % (2, LINE2) + "\n") in out.err
    rc, out = _recheck(ctx, capsys, cut, ctx._replace(narration=False))
    assert " Q1 " not in out.out + out.err


def test_review_focus_1_smart_quotes_in_the_narrative(ws):
    # A narrative typed with smart quotes and a curly apostrophe (macOS text fields). Expected: the
    # required line keeps the author's apostrophe in the plan prompt and in Dialogue:, Q1 passes,
    # and a hand-typed Dialogue: with a straight apostrophe and no full stop also passes.
    narrative = "The courier reaches the gate and says “It’s just a short climb.”"
    line = "It’s just a short climb."
    assert se.spoken_lines(narrative) == [line]
    ctx = seu.make_ctx(se, ws, panels=1, narrative=narrative)
    assert '\n1. "%s"\n' % line in se.build_plan_prompt(ctx, [], [])
    raw = seu.plan_json("chained", 1)
    raw["beats"][0].update(speaker="c1", lines=[1])
    plan, _shape = se.normalize_plan(ctx, raw)
    parts = [se.parse_panel_reply(ctx, plan, 1, json.dumps(seu.panel_json("chained", 1)))]
    text = se.assemble(ctx, plan, parts)
    assert "\nDialogue: the courier: %s\n" % line in text
    path = os.path.join(ctx.story_dir, "check.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    hard, _advisory = se.panel_checks(ctx, plan, parts, text, path)
    assert not [m for m in hard if " Q1 " in m]
    assert se.spoken_line_problems(ctx, character_lib, ["the courier"],
                                   ["the courier: it's just a short climb"]) == []


def test_review_focus_2_recheck_of_a_story_written_before_this_change(ws, capsys):
    # bin/ltx-movie re-checks an existing story.md on every rerun. A story written before this
    # change has a plan.json with the crowd still cast and no lines, spoken_lines or cast_notes.
    # Expected: once its Dialogue: fields hold every quoted line (the QL14 hand edit), the re-check
    # passes with no Q1; without the edit it exits 2 and names the missing line.
    state, plan, _notes = _replay(ws, "hockey-2x145", "plan_reply_1.txt")
    old = copy.deepcopy(plan)
    del old["spoken_lines"], old["cast_notes"]
    old["cast"].append(dict(_reply("hockey-2x145")["cast"][1], cast_name=None))
    old["beats"][1]["cast"] = ["c1", "c2"]
    for beat in old["beats"]:
        del beat["lines"]
    ctx = _hockey_ctx(ws, "hockey-2x145")
    se._write_json(os.path.join(ctx.story_dir, "plan.json"), old)
    rc, out = _recheck(ctx, capsys, state["text"] + "Dialogue: the FuboTV player: It's just "
                                                    "FuboTV.\n")
    assert rc == 0 and " Q1 " not in out.out + out.err
    rc, out = _recheck(ctx, capsys, state["text"])
    assert rc == 2
    assert out.err.startswith("Error: story.md fails the story checks:\n  - "
                              + Q1_MISSING % (2, LINE2) + "\n")
    assert "pass --force-story to regenerate it" in out.err


def test_nf_lines_consecutive_only(ws):
    # Spec 7.1(e): a beat holds only consecutive spoken lines; the rest are dropped and unassigned.
    _ctx, plan = _lines_plan(ws, COURIER_LINES, {1: {"speaker": "c1", "lines": [1, 3]}})
    assert plan["beats"][0]["lines"] == [1]
    assert plan["speech_notes"] == [
        "beat 1: P14 speaking beat: line(s) 3 dropped: the beat's lines are not consecutive"]
    problems = se.line_assignment_problems(plan)
    assert [p.split(" is in no beat")[0] for p in problems] == [
        'plan: Q1 spoken line: spoken line 2 "The gate is close."',
        'plan: Q1 spoken line: spoken line 3 "We made it."']
    _ctx, plan = _lines_plan(ws, COURIER_LINES, {1: {"speaker": "c1", "lines": [2, 3]}})
    assert plan["beats"][0]["lines"] == [2, 3] and plan["speech_notes"] == []
    _ctx, plan = _lines_plan(ws, COURIER_LINES, {1: {"speaker": "c1", "lines": [1, 2, 4]}})
    assert plan["beats"][0]["lines"] == [1, 2]


# --- NF9b, NF28-NF30, NF32, NF33, NF37, Review Focus 5: the pipeline assignment (QL8b) -------------

GIVEN = ("beat %d: P14 speaking beat: line %d given to this beat by the pipeline, because the plan "
         "gave it to no beat")


def _engine(monkeypatch, tmp_path, ctx, plan, panel, critic=()):
    """(rc, agent log) of se.run(ctx) with the fake agent's scripted replies."""
    log = seu.script_agent(monkeypatch, tmp_path, plan=plan, panel=panel, critic=list(critic))
    rc, _advisories = se.run(ctx)
    return rc, seu.agent_log(log)


def _story_json(ctx, *parts):
    with open(os.path.join(ctx.story_dir, *parts), encoding="utf-8") as f:
        return json.load(f)


def _story_text(ctx, *parts):
    with open(os.path.join(ctx.story_dir, *parts), encoding="utf-8") as f:
        return f.read()


def _stages(log):
    return [call["stage"] for call in log]


def test_nf9b_replay_with_the_pipeline_assignment(ws):
    state, plan, notes = _replay(ws, "hockey-2x145", "plan_reply_1.txt", assign=True)
    assert [b["lines"] for b in plan["beats"]] == [[1], [2]]
    assert plan["beats"][1]["speaker"] == "c1"
    assert notes == [GIVEN % (1, 1), GIVEN % (2, 2)]
    assert state["hard"] == [T2_2X145]
    state, plan, notes = _replay(ws, "hockey-1x241", "plan_reply_1.txt", assign=True)
    beat = plan["beats"][0]
    assert (beat["lines"], beat["speaker"], beat["shot"], beat["camera"]) == (
        [1, 2], "c1", "medium shot", "tracking")
    assert notes == [GIVEN % (1, 1), GIVEN % (1, 2)]
    assert state["hard"] == []


def test_nf37_assign_missing_lines(ws):
    def assigned(beats, n=3, narrative=COURIER_LINES):
        ctx, plan = _lines_plan(ws, narrative, beats, n=n)
        notes = se.assign_missing_lines(ctx, plan)
        return plan, notes

    plan, notes = assigned({})
    assert [b["lines"] for b in plan["beats"]] == [[1], [2], [3]]
    assert notes == [GIVEN % (1, 1), GIVEN % (2, 2), GIVEN % (3, 3)]
    assert [b["speaker"] for b in plan["beats"]] == ["c1", "c1", "c1"]
    assert (plan["beats"][0]["shot"], plan["beats"][0]["camera"]) == ("medium shot", "static")
    plan, notes = assigned({2: {"cast": ["c1", "c2"]}})
    assert [b["lines"] for b in plan["beats"]] == [[1], [], [2, 3]]
    assert notes == [GIVEN % (1, 1), GIVEN % (3, 2), GIVEN % (3, 3)]
    plan, notes = assigned({1: {"speaker": "c1", "lines": [1]}, 2: {"speaker": "c1", "lines": [3]}})
    assert [b["lines"] for b in plan["beats"]] == [[1], [2, 3], []]
    assert notes == [GIVEN % (2, 2)]
    seven = ('The courier says "Keep moving along the wet harbour road." Then he says "The temple '
             'gate is close to us."')
    plan, notes = assigned({}, n=1, narrative=seven)
    assert [b["lines"] for b in plan["beats"]] == [[1]] and notes == [GIVEN % (1, 1)]
    assert se.line_assignment_problems(plan) == [
        'plan: Q1 spoken line: spoken line 2 "The temple gate is close to us." is in no beat\'s '
        "lines; put 2 in the lines of the beat whose action surrounds it in the narrative, and "
        "give that beat a speaker"]
    plan, notes = assigned({}, narrative=seu.make_ctx(se, ws).narrative)
    assert notes == [] and [b["lines"] for b in plan["beats"]] == [[], [], []]


NF28_PATCH = {"target": "panel", "index": 2, "field": "motion", "reason": "r",
              "replacement": "The FuboTV player skates forward, then halts in a sharp hockey stop "
                             "that sprays ice mist into the air. He skates away from the camera."}


def _recorded(case, name):
    return seu.answer(_fixture_text(case, name))


def test_nf28_engine_the_2x145_failure(ws, tmp_path, monkeypatch):
    ctx = _hockey_ctx(ws, "hockey-2x145")
    plan = _recorded("hockey-2x145", "plan_reply_1.txt")
    rc, log = _engine(monkeypatch, tmp_path, ctx, [plan, plan],
                      {"1": [_recorded("hockey-2x145", "panel_01_reply_1.txt")],
                       "2": [_recorded("hockey-2x145", "panel_02_reply_1.txt")]},
                      [seu.answer(seu.critic_json((7, 6, 6), "revise", [NF28_PATCH]))])
    assert rc == 0
    assert _stages(log) == ["plan", "plan", "panel", "panel", "critic"]
    round0 = _story_json(ctx, "story_rounds", "round_0", "plan.json")
    assert [b["lines"] for b in round0["beats"]] == [[1], [2]]
    assert (round0["beats"][1]["speaker"], round0["beats"][1]["cast"]) == ("c1", ["c1"])
    assert round0["speech_notes"] == [GIVEN % (1, 1), GIVEN % (2, 2)]
    checks0 = _story_json(ctx, "story_rounds", "round_0", "story_checks.json")
    assert [v["id"] for v in checks0["hard"]] == ["T2"]
    assert '\ndialogue: exactly "%s" -- ' % LINE1 in _story_text(
        ctx, "story_rounds", "round_0", "panel_01_prompt_1.txt")
    assert _story_json(ctx, "story_rounds", "round_1", "critic.json")["applied"] == [NF28_PATCH]
    assert _story_json(ctx, "story_checks.json")["stop_reason"] == "passed"
    story = _story_text(ctx, "story.md")
    assert "Dialogue: the FuboTV player: " + LINE1 + "\n" in story
    assert story.endswith(
        "## Panel 2 — The FuboTV Hockey Stop\nMotion: The FuboTV player skates forward, then halts "
        "in a sharp hockey stop that sprays ice mist into the air. He skates away from the camera. "
        "The FuboTV player faces the camera. The camera stays static.\n"
        "Dialogue: the FuboTV player: It's just FuboTV.\n")


def test_nf29_engine_the_1x241_failure(ws, tmp_path, monkeypatch):
    ctx = _hockey_ctx(ws, "hockey-1x241")
    plan = _recorded("hockey-1x241", "plan_reply_1.txt")
    rc, log = _engine(monkeypatch, tmp_path, ctx, [plan, plan],
                      {"1": [_recorded("hockey-1x241", "panel_01_reply_1.txt")]})
    assert rc == 0
    assert _stages(log) == ["plan", "plan", "panel"]
    assert _story_json(ctx, "story_rounds", "round_0", "story_checks.json")["hard"] == []
    assert _story_json(ctx, "story_checks.json")["stop_reason"] == "passed"
    assert _story_json(ctx, "plan.json")["speech_notes"] == [GIVEN % (1, 1), GIVEN % (1, 2)]
    story = _story_text(ctx, "story.md")
    assert ("Motion: The FuboTV player skates forward toward the camera, then stops abruptly in a "
            "hockey stop, spraying ice mist into the air. He then skates away from the camera. The "
            "FuboTV player faces the camera. The camera tracks alongside the movement.\n"
            "Dialogue: the FuboTV player: " + LINE1 + " " + LINE2 + "\n") in story


def test_nf30_q1_blocks_when_no_beat_is_eligible(ws, tmp_path, monkeypatch, capsys):
    raw = seu.plan_json("chained", 3)
    for beat in raw["beats"]:
        beat["cast"] = ["c1", "c2"]
    ctx = seu.make_ctx(se, ws, narrative=COURIER_LINES)
    capsys.readouterr()
    rc, log = _engine(monkeypatch, tmp_path, ctx, [seu.answer(raw), seu.answer(raw)],
                      dict((str(k), [seu.answer(seu.panel_json("chained", k))]) for k in (1, 2, 3)),
                      [{"answer": "x"}] * 4)
    assert rc == 2
    assert _story_json(ctx, "story_rounds", "round_0", "plan.json")["speech_notes"] == []
    err = capsys.readouterr().err
    for i, line in enumerate(COURIER_SPOKEN, start=1):
        assert ("  - " + Q1_MISSING % (i, line) + "\n") in err
    assert [v["id"] for v in _story_json(ctx, "story_checks.json")["hard"]] == ["Q1", "Q1", "Q1"]
    assert _stages(log).count("critic") == 4 and _stages(log).count("plan") == 2
    assert "\nDialogue:" not in _story_text(ctx, "story.md")


def test_nf32_no_narration_keeps_the_movie_silent(ws, tmp_path, monkeypatch):
    ctx = seu.make_ctx(se, ws, narration=False, narrative=HOCKEY)
    rc, log = _engine(monkeypatch, tmp_path, ctx, [seu.answer(seu.plan_json("chained", 3))],
                      dict((str(k), [seu.answer(seu.panel_json("chained", k))]) for k in (1, 2, 3)))
    assert rc == 0 and _stages(log) == ["plan", "panel", "panel", "panel"]
    checks0 = _story_json(ctx, "story_rounds", "round_0", "story_checks.json")
    assert not [v for v in checks0["hard"] + checks0["advisory"] if v["id"] == "Q1"]
    assert Q2_HOCKEY in [v["message"] for v in checks0["advisory"]]
    assert "Spoken lines (" not in _story_text(ctx, "story_rounds", "round_0", "plan_prompt.txt")


def test_nf33_default_narration_with_the_fixed_plan(ws, tmp_path, monkeypatch, capsys):
    ctx = _hockey_ctx(ws, "hockey-2x145", narration=True)
    p2 = _recorded("hockey-2x145", "panel_02_reply_1.txt")
    capsys.readouterr()
    rc, log = _engine(monkeypatch, tmp_path, ctx, [_recorded("hockey-2x145", "plan_reply_fixed.json")],
                      {"1": [_recorded("hockey-2x145", "panel_01_reply_1.txt")], "2": [p2, p2]},
                      [{"answer": "x"}] * 4)
    assert rc == 0
    assert _stages(log).count("plan") == 1
    assert _story_json(ctx, "story_rounds", "round_0", "plan.json")["speech_notes"] == []
    checks0 = _story_json(ctx, "story_rounds", "round_0", "story_checks.json")
    assert [v["id"] for v in checks0["hard"]] == ["T2"]
    assert ("Warning: unresolved after 2 critic round(s): " + T2_2X145 + "\n"
            ) in capsys.readouterr().out
    story = _story_text(ctx, "story.md")
    assert "Dialogue: the FuboTV player: " + LINE1 + "\n" in story
    assert "Dialogue: the FuboTV player: " + LINE2 + "\n" in story


def test_review_focus_5_a_shots_movie_with_quoted_lines(ws, tmp_path, monkeypatch):
    # --shots with a quoted narrative: every shot is its own still and the shot rules S1/S3 are
    # hard. Expected: the plan's lines reach each speaking shot's Dialogue:, the shot rules do not
    # trip on the pasted facing sentence or the Dialogue: line, and the run passes with no Q1.
    narrative = 'The courier says "Keep moving." At the gate he whispers "We made it."'
    raw = seu.plan_json("shots", 2)
    raw["beats"][0].update(speaker="c1", lines=[1])
    raw["beats"][1].update(speaker="c1", lines=[2])
    ctx = seu.make_ctx(se, ws, mode="shots", panels=2, narrative=narrative)
    rc, log = _engine(monkeypatch, tmp_path, ctx, [seu.answer(raw)],
                      dict((str(k), [seu.answer(seu.panel_json("shots", k))]) for k in (1, 2)))
    assert rc == 0 and _stages(log) == ["plan", "panel", "panel"]
    assert _story_json(ctx, "story_rounds", "round_0", "story_checks.json")["hard"] == []
    story = _story_text(ctx, "story.md")
    assert "\nDialogue: the courier: Keep moving.\n" in story
    assert "\nDialogue: the courier: We made it.\n" in story


def test_nf37b_assign_keeps_runs_consecutive(ws):
    two_sided = {2: {"cast": ["c1", "c2"]}, 3: {"cast": ["c1", "c2"]}}
    long2 = "Keep moving along the wet harbour road toward the old temple gate by the sea now."
    narrative = ('The courier says "Keep moving." Then he says "%s" At the gate he whispers '
                 '"We made it."' % long2)
    beats = dict(two_sided)
    beats[1] = {"speaker": "c1", "lines": [1]}
    ctx, plan = _lines_plan(ws, narrative, beats)
    notes = se.assign_missing_lines(ctx, plan)
    assert [b["lines"] for b in plan["beats"]] == [[1], [], []] and notes == []
    assert [n for n, _line in enumerate(plan["spoken_lines"], start=1)
            if not any(n in b["lines"] for b in plan["beats"])] == [2, 3]
    five = ('The courier says "Keep moving." Then he says "The gate is close." Then he says '
            '"We made it." Then he says "Hold the rope." At last he says "Open the door."')
    beats = {1: {"cast": ["c1", "c2"]}, 2: {"cast": ["c1", "c2"]},
             3: {"speaker": "c1", "lines": [5]}}
    ctx, plan = _lines_plan(ws, five, beats)
    notes = se.assign_missing_lines(ctx, plan)
    assert [b["lines"] for b in plan["beats"]] == [[], [], [4, 5]]
    assert notes == [GIVEN % (3, 4)]

