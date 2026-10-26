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
