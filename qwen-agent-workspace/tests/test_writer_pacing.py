"""Tests for writer pacing (docs/superpowers/specs/2026-10-26-writer-pacing-design.md, Section 4.1:
WT1-WT9, and the plan's Review Focus 1-5): the chained writer is told where the pipeline speaks
the line (one sentence on each side of the speech point), every chained Motion key line asks for
fast, concrete motion at real-time speed with named effects, and the critic's chained Motion
patch keeps the speech point.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_writer_pacing.py
Stdlib plus pytest. No test renders, reads the real HOME, or contacts a model server, a daemon or
the Anthropic API: every ctx lives under tmp_path (story_engine_testutil.make_ws) and every test
runs under the autouse story_env fixture (a temporary HOME, character library and LoRA catalog).
The hockey fixtures under tests/fixtures/writer_pacing/ are verbatim copies of the two recorded
2026-10-26 NK8 runs (hockey-2x145-f, hockey-1x241-f), plus one hand-written case.json each.
"""

import copy
import importlib.machinery
import json
import os
import re
import shutil
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
FIX = os.path.join(WS, "tests", "fixtures", "writer_pacing")
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402
import test_dialogue as dlg  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


lib = _load("character_lib_for_pacing", "character_lib.py")
se = _load("story_engine_for_pacing", "story_engine.py")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


def _case(name):
    """The hand-written case.json of a recorded hockey run (spec 4.2)."""
    with open(os.path.join(FIX, name, "case.json"), encoding="utf-8") as f:
        return json.load(f)


def _read(name, filename):
    with open(os.path.join(FIX, name, filename), encoding="utf-8") as f:
        return f.read()


def _json(name, filename):
    with open(os.path.join(FIX, name, filename), encoding="utf-8") as f:
        return json.load(f)


with open(os.path.join(WS, "tests", "fixtures", "narrative_fidelity", "narrative.txt"),
          encoding="utf-8") as _f:
    HOCKEY = _f.read().strip()


def _ctx(ws, name, **kw):
    """The StoryContext of a recorded hockey run: chained, --speech-only, the case's panels,
    seconds, clip length and goal; keyword arguments replace fields."""
    c = _case(name)
    fields = dict(story_id=c["story_id"], mode="chained", panels=c["panels"],
                  seconds=c["seconds"], clip_seconds=c["frames"] / 24.0, narration="speech",
                  narrative=HOCKEY, goal=c["goal"])
    fields.update(kw)
    return seu.make_ctx(se, ws, **fields)


def _recorded(name):
    """(plan, parts) of a recorded run: plan.json as written, and parts.json's panels without
    their "index" key."""
    plan = _json(name, "plan.json")
    parts = [{k: v for k, v in p.items() if k != "index"}
             for p in _json(name, "parts.json")["panels"]]
    return plan, parts


def _motion_key_line(prompt):
    """The first line of a panel prompt that starts with "motion: " (the motion key line)."""
    return [line for line in prompt.split("\n") if line.startswith("motion: ")][0]


PHRASE = "FuboTV hockey player"
LINE1 = "Getting the best deal on hockey isn't a hat trick..."
LINE2 = "It's just FuboTV."
GOOD2 = ("The FuboTV hockey player snaps into a hard stop, throwing a big, bright spray of ice. "
         "The FuboTV hockey player skates away at real-time speed.")
SAY2 = lib.speech_text(PHRASE, LINE2, "beats")
FACING_CAMERA = " FuboTV hockey player faces the camera. The camera stays static."
NAMES = ("hockey-2x145-f", "hockey-1x241-f")

# --- WT1: the constants (WP1, WP2) ----------------------------------------------------------------

PACING = (" The motion plays at real-time speed: use fast, concrete action verbs, with no words "
          "that slow it down, and end the main action with the words 'at real-time speed'. When "
          "an action throws something up, such as ice, snow, water, dust or sparks, name it in "
          "the same sentence as a big, bright spray, splash or cloud, and never say how long it "
          "lasts, how small it is or when it settles.")
SPEAKING_CHAINED = (
    " In this panel @@SPEAKER@@ speaks the dialogue, and the pipeline inserts it right after the "
    "first sentence about what @@SPEAKER@@ does. Write that first sentence as everything "
    "@@SPEAKER@@ does before the dialogue, ending with them near the camera, face toward it (if "
    "the dialogue comes before they do anything, it is how they turn or step toward the camera; "
    "never write only that they face it); after it you may write one short second sentence of "
    "how @@SPEAKER@@ reacts once the line is said, such as a nod, a breath or a glance down, in "
    "which nobody else acts. Begin each of these sentences with @@SPEAKER@@, word for word, and "
    "write nothing about anyone else before the first one. Never put an action from before the "
    "dialogue and one from after it in the same sentence, and do not write the spoken words or a "
    "speaking verb; the pipeline adds them.")
CHAINED_MOTION1 = (
    "motion: W1 to W2 words: one or two plain sentences of what the characters physically do "
    "during these @@SECONDS@@ seconds, then the camera sentence. Name each character only by "
    "their referring phrase, word for word. Describe ONE continuous physical motion, not a "
    "sequence of separate steps: @@SECONDS@@ seconds is enough for a single gesture, a few "
    "footsteps or the start of a movement. The motion plays at real-time speed: use fast, "
    "concrete action verbs, with no words that slow it down, and end the main action with the "
    "words 'at real-time speed'. When an action throws something up, such as ice, snow, water, "
    "dust or sparks, name it in the same sentence as a big, bright spray, splash or cloud, and "
    "never say how long it lasts, how small it is or when it settles.")
CHAINED_MOTION = (
    "motion: W1 to W2 words: one or two plain sentences of what the characters physically do "
    "during these @@SECONDS@@ seconds, continuing from where the previous panel left them, then "
    "the camera sentence. Name each character only by their referring phrase, word for word. "
    "Describe ONE continuous physical motion, not a sequence of separate steps: @@SECONDS@@ "
    "seconds is enough for a single gesture, a few footsteps or the start of a movement. The "
    "motion plays at real-time speed: use fast, concrete action verbs, with no words that slow "
    "it down, and end the main action with the words 'at real-time speed'. When an action "
    "throws something up, such as ice, snow, water, dust or sparks, name it in the same "
    "sentence as a big, bright spray, splash or cloud, and never say how long it lasts, how "
    "small it is or when it settles. Do not describe appearance, clothing, setting, lighting, "
    "colour or style -- all of that is already on screen.")
SPEAKING_ACTION = (" In this panel @@SPEAKER@@ speaks the dialogue: they may move as the beat "
                   "says, but write the motion so that their face is toward the camera, in frame "
                   "and lit while they speak -- a speaker who approaches the camera speaks once "
                   "close -- and do not write the spoken words or a speaking verb here; the "
                   "pipeline adds them.")


def test_wt1_the_constants():
    assert se.PACING_SENTENCE == PACING
    assert se.SPEAKING_CHAINED_MOTION_SENTENCE == SPEAKING_CHAINED
    assert se.KEY_LINE_TEMPLATES["chained_motion1"] == CHAINED_MOTION1
    assert se.KEY_LINE_TEMPLATES["chained_motion"] == CHAINED_MOTION
    assert se.SPEAKING_ACTION_SENTENCE == SPEAKING_ACTION
    assert se.SPEAKING_SENTENCES == {"image": se.SPEAKING_IMAGE_SENTENCE,
                                     "motion": se.SPEAKING_ACTION_SENTENCE,
                                     "prompt": se.SPEAKING_PROMPT_SENTENCE}
    for text in (PACING, SPEAKING_CHAINED, CHAINED_MOTION1, CHAINED_MOTION):
        assert "slowly" not in text.lower() and "no adverbs" not in text, text[:40]
        assert set(re.findall(r"@@[A-Z_]+@@", text)) <= {"@@SECONDS@@", "@@SPEAKER@@"}, text[:40]
    assert "speaks once close" not in SPEAKING_CHAINED


# --- WT2: pacing reaches chained prompts only (WP1, D5) ------------------------------------------

OLD_PACING = "use plain action verbs with no adverbs of speed or manner"


def test_wt2_pacing_reaches_chained_prompts_only(ws):
    ctx, plan, parts, _t, _p = dlg._story(ws, "chained", 3)
    for k in (1, 2, 3):
        prompt = se.build_panel_prompt(ctx, plan, parts, k)
        assert prompt.count(se.PACING_SENTENCE) == 1, k
        assert OLD_PACING not in prompt, k
    for mode, ks in (("shots", (1, 2)), ("no_stills", (1,))):
        ctx, plan, parts, _t, _p = dlg._story(ws, mode, 3)
        for k in ks:
            prompt = se.build_panel_prompt(ctx, plan, parts, k)
            # the shots prompt's format reference (R10) has the words; its own lines do not
            body = prompt.replace(se.FORMAT_REFERENCE, "")
            assert se.PACING_SENTENCE not in prompt and "at real-time speed" not in body, (
                mode, k)


# --- WT3, Review Focus 1, 2: the hockey speaking prompts (WP1-WP3) -----------------------------

def _camera_line(key):
    """The writer's camera sentence instruction for camera key (shot prompt format spec SF7)."""
    move, form = se.CAMERA_WRITER_FORMS[key]
    return se.CAMERA_WRITER_SENTENCE.replace("@@CAMERA_MOVE@@", move).replace("@@CAMERA_FORM@@",
                                                                             form)


def _expected_line(template, w1, w2, seconds, camera):
    return (se.KEY_LINE_TEMPLATES[template].replace("W1", w1, 1).replace("W2", w2, 1)
            .replace("@@SECONDS@@", seconds) + se.SPEECH_FRAMING_SENTENCE
            + se.SPEAKING_CHAINED_MOTION_SENTENCE.replace("@@SPEAKER@@", '"%s"' % PHRASE)
            + se.SPEAKING_STAY_SENTENCE.replace("@@SPEAKER@@", '"%s"' % PHRASE)
            + _camera_line(camera))


def test_wt3_the_hockey_speaking_prompts(ws):
    ctx = _ctx(ws, "hockey-2x145-f")
    plan, parts = _recorded("hockey-2x145-f")
    for k, template, w1, w2, camera in ((1, "chained_motion1", "43", "93", "tracking"),
                                        (2, "chained_motion", "45", "95", "static")):
        prompt = se.build_panel_prompt(ctx, plan, parts, k)
        assert _motion_key_line(prompt) == _expected_line(template, w1, w2, "6", camera), k
        assert "before the dialogue" in prompt and "speaks once close" not in prompt, k
    assert 'dialogue: exactly "It\'s just FuboTV." -- ' in se.build_panel_prompt(
        ctx, plan, parts, 2)


def test_review_focus_1_a_writer_re_ask_keeps_one_contract(ws):
    ctx = _ctx(ws, "hockey-2x145-f")
    plan, parts = _recorded("hockey-2x145-f")
    fix = ["panel 2: N12 one action: Motion: chains actions with 'then'"]
    prompt = se.build_panel_prompt(ctx, plan, parts, 2, fix=fix)
    assert "\n" + _expected_line("chained_motion", "45", "95", "6", "static") + "\n" in prompt
    assert prompt.count(se.PACING_SENTENCE) == 1
    assert prompt.count(se.SPEAKING_CHAINED_MOTION_SENTENCE.replace(
        "@@SPEAKER@@", '"%s"' % PHRASE)) == 1
    assert "speaks once close" not in prompt and "@@" not in prompt
    assert "\n- " + fix[0] + "\n" in prompt
    assert "\nPrevious version:\n" in prompt and "\nmotion: " + parts[1]["motion"] + "\n" in prompt


def test_review_focus_2_one_ten_second_panel_speaks_both_lines(ws):
    ctx = _ctx(ws, "hockey-1x241-f")
    plan, parts = _recorded("hockey-1x241-f")
    prompt = se.build_panel_prompt(ctx, plan, parts, 1)
    assert _motion_key_line(prompt) == _expected_line("chained_motion1", "43", "93", "10",
                                                      "tracking")
    assert '\ndialogue: exactly "%s %s" -- ' % (LINE1, LINE2) in prompt
    assert "@@" not in prompt and "speaks once close" not in prompt


# --- WT4: shots and no_stills speaking prompts are unchanged (D2) --------------------------------

def test_wt4_shots_and_no_stills_speaking_prompts_are_unchanged(ws):
    ctx, plan, parts, _t, _p = dlg._story(ws, "shots", 3, plan_mut=dlg._speaking(2),
                                          replies={2: {"dialogue": dlg.LINE}})
    prompt = se.build_panel_prompt(ctx, plan, parts, 2)
    assert ("and never use a semicolon."
            + se.SPEAKING_ACTION_SENTENCE.replace("@@SPEAKER@@", '"the courier"')
            + se.SPEAKING_REACTION_SENTENCE.replace("@@SPEAKER@@", '"the courier"')
            + se.SPEAKING_STAY_SENTENCE.replace("@@SPEAKER@@", '"the courier"')
            + _camera_line("tracking") + "\n") in prompt
    assert "before the dialogue" not in prompt
    ctx, plan, parts, _t, _p = dlg._story(ws, "no_stills", 3, plan_mut=dlg._speaking(2),
                                          replies={2: {"dialogue": dlg.LINE}})
    prompt = se.build_panel_prompt(ctx, plan, parts, 2)
    assert ("here; the pipeline adds them."
            + se.SPEAKING_STAY_SENTENCE.replace("@@SPEAKER@@", '"the courier"')
            + _camera_line("tracking") + "\n") in prompt
    assert "before the dialogue" not in prompt


# --- WT5, WT6: a Motion written to the contract (D1) ---------------------------------------------

def _good(ws):
    """(ctx, plan, parts) of the 2x145-f run with panel 2's Motion written to the contract."""
    ctx = _ctx(ws, "hockey-2x145-f")
    plan, parts = _recorded("hockey-2x145-f")
    parts[1]["motion"] = GOOD2
    return ctx, plan, parts


def _compose(writer, say=SAY2):
    return lib.insert_speech(writer + FACING_CAMERA, say, [PHRASE], first_action=True)


def test_wt5_the_contract_matches_the_placement(ws):
    ctx, plan, parts = _good(ws)
    motion = dict(se.panel_fields(ctx, plan, parts, 2))["Motion"]
    assert motion == GOOD2 + FACING_CAMERA
    out = lib.insert_speech(motion, SAY2, [PHRASE], first_action=True)
    assert out == ("The FuboTV hockey player snaps into a hard stop, throwing a big, bright spray "
                   "of ice. FuboTV hockey player faces the camera. " + SAY2 + " The FuboTV hockey "
                   "player skates away at real-time speed. The camera stays static.")
    assert out.index(SAY2) < out.index("skates away")
    camera_first = ("The camera holds on him. The FuboTV hockey player snaps into a hard hockey "
                    "stop. He skates away at real-time speed.")
    out = _compose(camera_first)
    assert out == ("The camera holds on him. The FuboTV hockey player snaps into a hard hockey "
                   "stop. FuboTV hockey player faces the camera. " + SAY2 + " He skates away at "
                   "real-time speed. The camera stays static.")
    assert out.index(SAY2) < out.index("skates away")
    camera_last = ("The FuboTV hockey player snaps into a hard hockey stop. He skates away at "
                   "real-time speed. The camera holds on him as he recedes.")
    out = _compose(camera_last)
    assert out == ("The FuboTV hockey player snaps into a hard hockey stop. FuboTV hockey player "
                   "faces the camera. " + SAY2 + " He skates away at real-time speed. The camera "
                   "holds on him as he recedes. The camera stays static.")
    assert out.index(SAY2) < out.index("skates away")
    one = "The FuboTV hockey player skates toward the camera at real-time speed."
    assert _compose(one) == (one + " FuboTV hockey player faces the camera. " + SAY2
                             + " The camera stays static.")
    plain = lib.speech_text(PHRASE, LINE2, "plain")
    out = _compose(GOOD2, plain)
    assert out == ("The FuboTV hockey player snaps into a hard stop, throwing a big, bright spray "
                   "of ice. FuboTV hockey player faces the camera. " + plain + " The FuboTV hockey "
                   "player skates away at real-time speed. The camera stays static.")
    assert out.index(plain) < out.index("skates away")
    off = ("The FuboTV hockey player snaps into a hard stop, throwing a big, bright spray of ice. "
           "The FuboTV hockey player skates off camera.")
    out = _compose(off)
    assert out == ("The FuboTV hockey player snaps into a hard stop, throwing a big, bright spray of "
                   "ice. FuboTV hockey player faces the camera. " + SAY2 + " The FuboTV hockey "
                   "player skates off camera. The camera stays static.")
    assert out.index(SAY2) < out.index("skates off")
    first = ("The FuboTV hockey player turns toward the camera. "
             "The FuboTV hockey player skates away at real-time speed.")
    out = _compose(first)
    assert out == ("The FuboTV hockey player turns toward the camera. FuboTV hockey player faces "
                   "the camera. " + SAY2 + " The FuboTV hockey player skates away at real-time "
                   "speed. The camera stays static.")
    assert out.index(SAY2) < out.index("skates away")


def test_wt6_the_contract_motion_passes_the_checks(ws, tmp_path):
    ctx, plan, parts = _good(ws)
    text = se.assemble(ctx, plan, parts)
    path = os.path.join(str(tmp_path), "story.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    # Shot prompt format spec: the recorded panel 1's speaking verb is a hard N7 while generating
    # (R12), the contract's exit after the line a hard N21 (R16), and both Motions are under the
    # 55-105 range (R8).
    assert se.panel_checks(ctx, plan, parts, text, path) == (
        ["panel 1: N7 dialogue and text: Motion: says 'speaks'; the pipeline adds the spoken line "
         "itself, so write only what the speaker physically does, with no speaking verb",
         "panel 2: N21 after the line: Motion: 'The FuboTV hockey player skates away at "
         "real-time speed.' has a character leave the frame or turn away ('skates away'); "
         "'FuboTV hockey player' speaks in this panel, so end it with 'FuboTV hockey player' "
         "still in frame, face toward the camera"],
        ["panel 1: N1 word count: Motion: is 33 words; aim for 55-105",
         "panel 2: N1 word count: Motion: is 35 words; aim for 55-105"])


# --- WT8, WT9: old stories compose and check unchanged (WK6) -------------------------------------

def _story_fields(text):
    """[(image, motion, dialogue)] of each "## Panel" section of a story.md (image is "" on a
    panel with no Image: line)."""
    fields = []
    for section in text.split("\n## Panel ")[1:]:
        lines = section.split("\n")
        image = ([line[len("Image: "):] for line in lines if line.startswith("Image: ")] + [""])[0]
        motion = [line[len("Motion: "):] for line in lines if line.startswith("Motion: ")][0]
        dialogue = [line[len("Dialogue: "):] for line in lines if line.startswith("Dialogue: ")][0]
        fields.append((image, motion, dialogue))
    return fields


# Shot prompt format spec SF15, SF16 (R13): bin/ltx-story-manifest composes a speech movie's
# chained prompt with character_lib.panel_prompt: panel 1's framing first, the line after the
# first action, then the other actions and the camera, and the audio sentence last.
COMPOSED = {
    "hockey-2x145-f": [
        ("The shot is a medium shot. The FuboTV hockey player skates forward toward the camera, "
         "his face toward the lens, in frame and lit as he speaks. FuboTV hockey player faces "
         "the camera. FuboTV hockey player says, \"Getting the best deal on hockey isn't a hat "
         "trick...\" The camera tracks alongside the movement. " + dlg.AC),
        ("The FuboTV hockey player carves a sharp stop, spraying ice mist into the air, his face "
         "toward the lens, then pushes off and skates away from the camera. FuboTV hockey "
         'player faces the camera. FuboTV hockey player says, "It\'s just FuboTV." The camera '
         "holds on him as he recedes. The camera stays static. " + dlg.AC)],
    "hockey-1x241-f": [
        ("The shot is a medium shot. The FuboTV hockey player skates toward the camera, stops "
         "short, and kicks up a spray of ice mist. FuboTV hockey player faces the camera. "
         "FuboTV hockey player says, \"Getting the best deal on hockey isn't a hat "
         "trick...\" After a breath, \"It's just FuboTV.\" He then skates away from the "
         "camera. The camera tracks alongside the movement. " + dlg.AC)],
}


def test_wt8_old_stories_compose_unchanged():
    for name in NAMES:
        panels = _json(name, "manifest.json")["panels"]
        fields = _story_fields(_read(name, "story.md"))
        assert len(fields) == len(panels) == _case(name)["panels"], name
        for k, (image, motion, dialogue) in enumerate(fields, start=1):
            phrase, line, _rest = lib.parse_dialogue(dialogue, [PHRASE])
            framing = lib.framing_sentence(image) if k == 1 else ""
            assert lib.panel_prompt(motion, framing, phrase, line, "beats", [phrase]) == (
                COMPOSED[name][k - 1]), (name, k)


RECORDED_ADVISORY = {
    "hockey-2x145-f": ["panel 1: N7 dialogue and text: Motion: says 'speaks'",
                       "panel 2: N12 one action: Motion: chains actions with 'then'",
                       "panel 2: N1 word count: Motion: is 46 words; aim for 15-35"],
    "hockey-1x241-f": ["panel 1: N12 one action: Motion: chains actions with 'then'"],
}
# Shot prompt format spec: the generation checks of the recorded stories now. The speaking verb
# of 2x145-f's panel 1 is a hard N7 (R12); each exit after the line is a hard N21 (R16); N1 uses
# the 55-105 range (R8), and 2x145-f's panel 2 no longer counts the dropped pasted camera (R6).
CURRENT_CHECKS = {
    "hockey-2x145-f": (
        ["panel 1: N7 dialogue and text: Motion: says 'speaks'; the pipeline adds the spoken line "
         "itself, so write only what the speaker physically does, with no speaking verb",
         "panel 2: N21 after the line: Motion: 'The FuboTV hockey player carves a sharp stop, "
         "spraying ice mist into the air, his face toward the lens, then pushes off and skates "
         "away from the camera.' has a character leave the frame or turn away ('skates away'); "
         "'FuboTV hockey player' speaks in this panel, so end it with 'FuboTV hockey player' "
         "still in frame, face toward the camera"],
        ["panel 1: N1 word count: Motion: is 33 words; aim for 55-105",
         "panel 2: N12 one action: Motion: chains actions with 'then'"]),
    "hockey-1x241-f": (
        ["panel 1: N21 after the line: Motion: 'He then skates away from the camera.' has a "
         "character leave the frame or turn away ('skates away'); 'FuboTV hockey player' speaks "
         "in this panel, so end it with 'FuboTV hockey player' still in frame, face toward the "
         "camera"],
        ["panel 1: N12 one action: Motion: chains actions with 'then'",
         "panel 1: N1 word count: Motion: is 37 words; aim for 55-105"]),
}
# R6 (CM4): on 2x145-f's speaking panel 2 the writer's own camera sentence ("The camera holds on
# him as he recedes.") now leaves the pasted "The camera stays static." out of the assembly.
ASSEMBLED = {"hockey-2x145-f": (
    "FuboTV hockey player faces the camera. The camera stays static.\nDialogue: FuboTV hockey "
    "player: It's just FuboTV.\n",
    "FuboTV hockey player faces the camera.\nDialogue: FuboTV hockey player: It's just FuboTV.\n")}


def test_wt9_old_stories_check_unchanged(ws, tmp_path):
    for name in NAMES:
        ctx = _ctx(ws, name)
        plan, parts = _recorded(name)
        text = se.assemble(ctx, plan, parts)
        recorded = _read(name, "story.md")
        if name in ASSEMBLED:
            old, new = ASSEMBLED[name]
            assert recorded.count(old) == 1, name
            recorded = recorded.replace(old, new)
        assert text == recorded, name
        path = os.path.join(str(tmp_path), name + ".md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        rec = _json(name, "story_checks.json")
        expected = ([m["message"] for m in rec["hard"]], [m["message"] for m in rec["advisory"]])
        assert expected == ([], RECORDED_ADVISORY[name]), name
        assert se.panel_checks(ctx, plan, parts, text, path) == CURRENT_CHECKS[name], name
        for filename in ("plan.json", "story.md"):
            shutil.copy(os.path.join(FIX, name, filename), os.path.join(ctx.story_dir, filename))
        rc, _adv = se.recheck(ctx, lambda path, panels, no_stills=False: [])
        assert rc == 0, name


# --- WT7, Review Focus 3, 4, 5: the critic's chained Motion patch line (WP4, WP5, D6) -----------

MOTION = dlg.MOTION_LINE % ("motion", "Motion")
CRITIC_CLAUSE = (
    " On a panel with a Dialogue: line, the pipeline inserts the spoken words right after the "
    "first sentence about what the speaker does, so keep everything the speaker does before "
    "the line in that first sentence and at most one short sentence of the speaker's reaction "
    "after it, in which nobody else acts and the speaker never leaves the frame. Begin each of "
    "those sentences with the speaker's referring phrase.")
CATALOG = ["- fast-motion: x"]


def test_wt7_the_critic_clause(ws):
    assert se.CRITIC_SPEAKING_MOTION_CLAUSE == CRITIC_CLAUSE
    assert "slowly" not in CRITIC_CLAUSE.lower() and "no adverbs" not in CRITIC_CLAUSE
    assert re.findall(r"@@[A-Z_]+@@", CRITIC_CLAUSE) == []
    assert se.critic_field_lines("chained", None, "speech", True, speaking=True).split("\n")[0] == (
        MOTION + CRITIC_CLAUSE)
    for mode in ("shots", "no_stills"):
        assert se.critic_field_lines(mode, None, "speech", True, speaking=True) == (
            se.critic_field_lines(mode, None, "speech", True)), mode
    assert se.critic_field_lines("chained", None, False, False, speaking=True) == (
        se.critic_field_lines("chained", None, False))
    for mode in ("chained", "shots", "no_stills"):
        assert se.critic_field_lines(mode, None) == se.critic_field_lines(
            mode, None, True, False, False), mode
    plan = _json("hockey-2x145-f", "plan.json")
    text = _read("hockey-2x145-f", "story.md")
    for for_judge in (False, True):
        prompt = se.build_critic_prompt(plan, text, ([], []), narration="speech",
                                        for_judge=for_judge)
        assert "\n" + MOTION + CRITIC_CLAUSE + "\n" in prompt, for_judge
    _c, quiet, _parts, quiet_text, _p = dlg._story(ws, "chained", 3)
    for narration in (True, "speech"):
        assert CRITIC_CLAUSE not in se.build_critic_prompt(quiet, quiet_text, ([], []),
                                                           narration=narration), narration


def test_review_focus_3_a_silent_chained_movie_gets_pacing_and_no_speech_point(ws):
    ctx, plan, parts, text, _p = dlg._story(ws, "chained", 3, plan_mut=dlg._speaking(2),
                                            ctx_kw={"narration": False})
    assert [b["speaker"] for b in plan["beats"]] == ["", "", ""]
    for k in (1, 2, 3):
        prompt = se.build_panel_prompt(ctx, plan, parts, k)
        assert prompt.count(se.PACING_SENTENCE) == 1, k
        assert "speaks the dialogue" not in prompt and "\ndialogue: " not in prompt, k
    assert "are:\n" + MOTION + "\nPreserve" in se.build_critic_prompt(plan, text, ([], []),
                                                                      narration=False)
    hockey = _json("hockey-2x145-f", "plan.json")
    prompt = se.build_critic_prompt(hockey, _read("hockey-2x145-f", "story.md"), ([], []),
                                    narration=False)
    assert "are:\n" + MOTION + "\nPreserve" in prompt and CRITIC_CLAUSE not in prompt


def test_review_focus_4_the_lora_catalog_line_stays_first(ws):
    lines = se.critic_field_lines("chained", CATALOG, "speech", True, speaking=True)
    before = se.critic_field_lines("chained", CATALOG, "speech", True)
    assert lines == before.replace("\n" + MOTION + "\n", "\n" + MOTION + CRITIC_CLAUSE + "\n")
    assert lines.count(CRITIC_CLAUSE) == 1
    assert lines.startswith('- target "plan", field "lora", index 0 for the global picks')
    prompt = se.build_critic_prompt(_json("hockey-2x145-f", "plan.json"),
                                    _read("hockey-2x145-f", "story.md"), ([], []), CATALOG,
                                    narration="speech")
    assert ("\n- fast-motion: x\n" + MOTION + CRITIC_CLAUSE + "\n" + dlg.DIALOGUE_FIELD_LINE
            + "\n") in prompt


def test_review_focus_5_an_older_plan_json_through_judge_story():
    text = _read("hockey-2x145-f", "story.md")
    older = _json("hockey-2x145-f", "plan.json")
    del older["spoken_lines"]
    for beat in older["beats"]:
        del beat["speaker"]
        del beat["lines"]
    prompt = se.build_critic_prompt(older, text, ([], []), for_judge=True)
    assert "are:\n" + MOTION + "\n" + dlg.DIALOGUE_FIELD_LINE + "\nPreserve" in prompt
    assert CRITIC_CLAUSE not in prompt
    mixed = copy.deepcopy(older)
    mixed["beats"][1]["speaker"] = "c1"
    assert ("are:\n" + MOTION + CRITIC_CLAUSE + "\n" + dlg.DIALOGUE_FIELD_LINE + "\nPreserve") in (
        se.build_critic_prompt(mixed, text, ([], []), for_judge=True))
