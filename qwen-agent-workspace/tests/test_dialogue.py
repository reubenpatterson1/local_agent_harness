"""Tests for on-camera dialogue (docs/superpowers/specs/2026-10-24-on-camera-dialogue-design.md,
Sections 9.1 and 11.8: DLG1-DLG34, DLG-H, DLG-K1 and CA1-CA9): the Dialogue: field, beat-mapped
speech in the LTX motion prompt, the timing-only critic and chained casting attachment.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py
Stdlib plus pytest. Every model call goes to the fake bin/qwen-agent of a temp workspace
(story_engine_testutil.make_ws) or to a monkeypatched seam; no test renders or reaches a model
server, a daemon or the Anthropic API, and every test runs under the autouse story_env fixture
(a temporary HOME, character library and LoRA catalog).
"""

import base64
import copy
import importlib.machinery
import json
import os
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


character_lib = _load("character_lib_for_dialogue", "character_lib.py")
se = _load("story_engine_for_dialogue", "story_engine.py")
story_manifest = _load("ltx_story_manifest_for_dialogue", "bin/ltx-story-manifest")
ltx_movie = _load("ltx_movie_for_dialogue", "bin/ltx-movie")

# A valid 1x1 PNG: bin/ltx-story-manifest only checks that each panel still opens.
PNG_1X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
                           "60e6kgAAAABJRU5ErkJggg==")
AC = ("The audio is clear close-mic dialogue with a subtle natural room tone; the dialogue takes "
      "priority over the quiet ambience.")
SPLIT = (", and a line has at most 3 sentences; shorten the line, or split it across alternating "
         "close-up panels (the speaker, then the listener, then the speaker again)")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


# --- DLG1-DLG3, Review Focus 5: the Dialogue grammar (DG1-DG5) ------------------------------

PHRASES = ["the courier", "the old monk"]


def test_dlg1_parse_dialogue():
    parse = character_lib.parse_dialogue
    assert parse("the old monk: You came far.", PHRASES) == ("the old monk", "You came far.", None)
    assert parse("  The Old   Monk :  You came far ", PHRASES) == (
        "the old monk", "You came far.", None)
    assert parse("the old monk: You came far.", ["the old", "the old monk"])[0] == "the old monk"
    assert parse('the courier: "Keep moving."', PHRASES) == ("the courier", "Keep moving.", None)
    assert parse("the courier: “Keep moving.”", PHRASES) == (
        "the courier", "Keep moving.", None)
    assert parse('the courier: He said "go" twice', PHRASES) == (
        "the courier", "He said 'go' twice.", None)
    assert parse("the courier: Are you there?", PHRASES)[1] == "Are you there?"
    assert parse("the stranger: Halt.", PHRASES) == (
        None, "", "names 'the stranger', which is no character's referring phrase; use one of: "
                  "'the courier', 'the old monk'")
    assert parse("the stranger: Halt.", []) == (
        None, "", "names 'the stranger', which is no character's referring phrase; use one of: "
                  "none (no --cast, no ## Characters section and no plan.json cast)")
    assert parse("Keep moving.", PHRASES) == (
        None, "", "has no speaker; write it as <referring phrase>: <the spoken words>")
    assert parse('the courier:  ""', PHRASES) == (None, "", "has a speaker but no words")
    seven = "the tall old man in the hat"
    assert parse(seven + ": Sit down.", [seven]) == (seven, "Sit down.", None)
    assert parse("   ", PHRASES) == (None, "", None)
    assert parse("", PHRASES) == (None, "", None)


def test_dlg2_fragments_and_word_cap():
    lib = character_lib
    assert lib.split_fragments("You came far. Rest here before the abbot sees you.") == [
        "You came far.", "Rest here before the abbot sees you."]
    assert lib.split_fragments("  Stop!  Who goes there?  ") == ["Stop!", "Who goes there?"]
    assert lib.split_fragments("No sentence end") == ["No sentence end"]
    assert lib.split_fragments("") == []
    for frames, caps in ((145, [14, 13, 12]), (121, [12, 11, 10]), (97, [9, 8, 7]),
                         (241, [14, 14, 14])):
        assert [lib.dialogue_word_cap(frames / 24.0, n) for n in (1, 2, 3)] == caps, frames
    assert lib.dialogue_word_cap(6.0) == 14


def test_dlg3_speech_text():
    lib = character_lib
    assert (lib.DIALOGUE_MAX_WORDS, lib.DIALOGUE_MAX_FRAGMENTS, lib.DIALOGUE_WORDS_PER_SECOND,
            lib.DIALOGUE_BEAT_SECONDS) == (14, 3, 2.4, 0.4)
    assert lib.SPEECH_DELIVERIES == ("beats", "plain", "beats-no-acoustic")
    assert lib.DEFAULT_SPEECH_DELIVERY == "beats"
    assert lib.SPEECH_BEATS == ("After a breath", "After a short pause")
    assert lib.ACOUSTIC_SENTENCE == AC
    assert lib.speech_text("the courier", "I carry a letter for the abbot.", "beats") == (
        'The courier says, "I carry a letter for the abbot." ' + AC)
    assert lib.speech_text("the old monk", "You came far. Rest here before the abbot sees you.",
                           "beats") == ('The old monk says, "You came far." After a breath, '
                                        '"Rest here before the abbot sees you." ' + AC)
    three = "Come in. Sit by the fire. He will see you."
    assert lib.speech_text("the old monk", three, "beats") == (
        'The old monk says, "Come in." After a breath, "Sit by the fire." After a short pause, '
        '"He will see you." ' + AC)
    assert lib.speech_text("the old monk", three, "beats-no-acoustic") == (
        'The old monk says, "Come in." After a breath, "Sit by the fire." After a short pause, '
        '"He will see you."')
    for line in ("Keep moving.", three, "Go"):
        assert lib.speech_text("the courier", line, "plain") == lib.speech_sentence(
            "the courier", line)
    assert lib.speech_text("the courier", "One. Two. Three. Four. Five.", "beats") == (
        'The courier says, "One." After a breath, "Two." After a short pause, '
        '"Three. Four. Five." ' + AC)
    assert lib.speech_text("the courier", "Keep moving.") == lib.speech_text(
        "the courier", "Keep moving.", "beats")


def test_review_focus_5_non_ascii_spoken_words():
    lib = character_lib
    line = lib.parse_dialogue("the courier: ¿Dónde está el abad? ¡Aquí!", ["the courier"])[1]
    assert line == "¿Dónde está el abad? ¡Aquí!"
    assert lib.split_fragments(line) == ["¿Dónde está el abad?", "¡Aquí!"]
    assert len(line.split()) == 5
    assert lib.speech_text("the courier", line, "beats-no-acoustic") == (
        'The courier says, "¿Dónde está el abad?" After a breath, "¡Aquí!"')


def test_dlg5b_speech_text_empty_line_composes_nothing():
    lib = character_lib
    for delivery in ("beats", "beats-no-acoustic"):
        assert lib.speech_text("the courier", "", delivery) == ""
    assert lib.speech_text("the courier", "   ", "beats") == ""


# --- DLG5, DLG34: camera sentences (CM1) ----------------------------------------------------

def test_dlg5_camera_sentence_classifier():
    cam = character_lib._is_camera_sentence
    assert cam("Slowly the lens drifts across the empty quay.")
    assert cam("A close-up of the sealed letter.")
    assert not cam("He turns toward the camera.")
    assert not cam("The courier faces the camera.", ["the courier"])
    assert not cam("The waves pan out across the bay.")
    assert cam("A wide shot of the harbour.", ["the monk!"])          # a CharacterError is skipped
    for _key, sentence in se.CAMERA_SENTENCES:
        assert cam(sentence), sentence
        assert cam(sentence, PHRASES), sentence
    for tail in ("Static camera.", "Slow push-in.", "Handheld, slow pan left.", "He stays static."):
        assert cam(tail), tail
    for tail in ("He kneels.", "The robber takes the shot."):
        assert not cam(tail), tail


def test_dlg34_motion_problems_with_phrases():
    motion = "The courier raises the sealed letter. The courier faces the camera."
    two = ("S5 one action", "Motion: has 2 action sentences; it must have exactly one, optionally "
                            "followed by a camera sentence")
    assert character_lib.motion_problems(motion) == []
    assert character_lib.motion_problems(motion, ["the courier"]) == [two]
    text = '# S\n\n## Characters\n- "the courier": %s.\n' % seu.COURIER
    panel = {"number": 1, "title": "One", "image": "The courier waits.", "motion": motion,
             "narration": "It rained.", "prompt": "", "dialogue": ""}
    assert "panel 1: %s: %s" % two in character_lib.shots_violations(text, [panel], 1, [])


# --- DLG4, DLG6: placement and triggers (DG6) -----------------------------------------------

def _members(story_env, *names):
    """Resolved CastMembers for the test library characters kyra and ronin."""
    for name in names:
        {"kyra": seu.kyra, "ronin": seu.ronin}[name](story_env["lib"])
    return character_lib.resolve_cast([(None, name) for name in names])


def test_dlg4_insert_speech_placement():
    lib = character_lib
    said = 'The courier says, "Go."'
    motion = "The courier raises the letter. The courier faces the camera. The camera stays static."
    assert lib.insert_speech(motion, said, ["the courier"]) == (
        "The courier raises the letter. The courier faces the camera. " + said
        + " The camera stays static.")
    assert lib.insert_speech(motion, said) == (
        "The courier raises the letter. " + said + " The courier faces the camera. The camera "
        "stays static.")
    run = "The courier runs. The camera slowly pushes in. The camera holds."
    assert lib.insert_speech(run, said, ["the courier"]) == (
        "The courier runs. " + said + " The camera slowly pushes in. The camera holds.")
    assert lib.insert_speech("The camera stays static. The camera holds.", said) == (
        "The camera stays static. " + said + " The camera holds.")
    assert lib.insert_speech("The camera stays static.", said) == "The camera stays static. " + said
    he = 'He says: "Go."'
    assert lib.insert_speech("He runs. The camera tracks alongside the movement.", he) == (
        'He runs. He says: "Go." The camera tracks alongside the movement.')
    assert lib.insert_speech("He runs. He jumps.", he) == 'He runs. He jumps. He says: "Go."'


def test_dlg6_cast_text_skip_quoted(story_env):
    members = _members(story_env, "kyra", "ronin")
    text = 'The woman in grey says, "Tell the ronin the woman in grey is here."'
    assert character_lib.cast_text(text, members, skip_quoted=True) == (
        'The kyrawmn woman in grey says, "Tell the ronin the woman in grey is here."', ["kyra"])
    assert character_lib.cast_text(text, members) == (
        'The kyrawmn woman in grey says, "Tell the roninmn ronin the kyrawmn woman in grey is '
        'here."', ["kyra", "ronin"])
    assert character_lib.cast_text('"The ronin waits."', members, skip_quoted=True) == (
        '"The ronin waits."', [])


# --- DLG32: the Dialogue: label (DG7 step 1, G7) ---------------------------------------------

LABEL_PATTERN = r"^(Image|Motion|Narration|Prompt|Style|Dialogue):\s*(.*)$"
STORY_WITH_DIALOGUE = """# Gate

A courier reaches a temple gate.

## Panel 1 — Arrival
Image: The courier stands at the gate.
Motion: The courier raises the letter.
Dialogue: the courier: I carry a letter
for the abbot.
Narration: The bell had not yet rung.
"""
IMAGE_THEN_DIALOGUE = """# Gate

## Panel 1 — Arrival
Image: A temple gate at dusk.
Dialogue: the courier: I carry a letter.
Motion: The courier raises the letter.
"""


def _judge(name, rel):
    """A bin/judge-* script, loaded only by the tests that use it (they import anthropic and
    jsonschema, which collecting this module must not need)."""
    pytest.importorskip("anthropic")
    pytest.importorskip("jsonschema")
    return _load(name, rel)


def test_dlg32_dialogue_label(tmp_path):
    assert story_manifest._PANEL_LABEL_RE.pattern == LABEL_PATTERN
    assert character_lib._STORY_FIELD_RE.pattern == LABEL_PATTERN
    path = tmp_path / "story.md"
    path.write_text(STORY_WITH_DIALOGUE, encoding="utf-8")
    panel = story_manifest._parse_prompts_md(str(path))[1][0]
    assert (panel["image"], panel["motion"], panel["dialogue"], panel["narration"]) == (
        "The courier stands at the gate.", "The courier raises the letter.",
        "the courier: I carry a letter for the abbot.", "The bell had not yet rung.")
    plain = tmp_path / "plain.md"
    plain.write_text(STORY_WITH_DIALOGUE.replace(
        "Dialogue: the courier: I carry a letter\nfor the abbot.\n", ""), encoding="utf-8")
    assert story_manifest._parse_prompts_md(str(plain))[1][0]["dialogue"] == ""
    member = character_lib.CastMember("courier", "the courier", "courierx", "man", seu.COURIER,
                                      "/v.safetensors", None, None, None)
    assert character_lib.repair_cast_descriptions(IMAGE_THEN_DIALOGUE, [member]) == (
        IMAGE_THEN_DIALOGUE, [])
    judge_stills = _judge("judge_stills_for_dialogue", "bin/judge-stills")
    assert judge_stills.PANEL_LABEL_RE.pattern == LABEL_PATTERN
    parsed = judge_stills.parse_panels(STORY_WITH_DIALOGUE)[0]
    assert (parsed["image"], parsed["motion"], parsed["narration"]) == (
        "The courier stands at the gate.", "The courier raises the letter.",
        "The bell had not yet rung.")
