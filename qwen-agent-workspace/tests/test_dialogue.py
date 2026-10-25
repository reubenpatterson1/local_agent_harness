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


# --- DLG7-DLG10, Review Focus 2-3: bin/ltx-story-manifest speech (DG7, DG9) ---------------------

DG9_SETTING = ("The setting is a hilltop temple gate in modern Japan, worn stone steps underfoot, "
               "cedar trees behind, under low golden evening light.")
CAST_PLAN = {"schema": "ltx-movie.plan.v1", "cast": [
    {"id": "c1", "phrase": "the courier", "descriptor": seu.COURIER, "cast_name": None},
    {"id": "c2", "phrase": "the old monk", "descriptor": seu.MONK, "cast_name": None}],
    "beats": [{"cast": ["c1"]}, {"cast": ["c2"]}]}
CHAINED_DG9 = """# The Gate

A courier reaches a hilltop temple.

## Panel 1 — The Steps
Image: %s The courier climbs toward the gate.
Motion: The courier climbs the last worn step toward the gate. The camera stays static.
Narration: The bell had not yet rung.

## Panel 2 — At the Gate
Motion: The old monk lowers his broom and lifts his eyes. The old monk faces the camera. The camera stays static.
@@LINES@@
""" % DG9_SETTING
SHOTS_DG9 = """# The Letter

A courier brings a letter to a temple.

## Characters
- "the courier": %(courier)s.
- "the old monk": %(monk)s.

## Panel 1 — The Road
Image: %(setting)s The courier walks up the road. The shot is a wide shot.
Motion: The courier walks up the road toward the gate. The camera tracks alongside the movement.
Narration: The road was long.

## Panel 2 — The Stairs
Image: %(setting)s The courier climbs the stairs. The shot is a medium shot.
Motion: The courier climbs the worn stone stairs. The camera stays static.
Narration: The stairs were steep.

## Panel 3 — The Letter
Image: %(setting)s The courier is %(courier)s. The courier stands at the gate holding the sealed letter at chest height. The courier faces the camera. The shot is a medium close-up.
Motion: The courier raises the sealed letter toward the gate. The courier faces the camera. The camera stays static.
Dialogue: the courier: I carry a letter for the abbot.
Narration: The bell had not yet rung.
""" % {"courier": seu.COURIER, "monk": seu.MONK, "setting": DG9_SETTING}
NO_STILLS_DG9 = """# Shelter

A courier finds shelter.

## Panel 1 — Rain
Prompt: The courier runs through the rain toward the temple. The camera stays static.
Narration: The rain came suddenly.

## Panel 2 — Gate
Prompt: The courier reaches the temple gate and knocks twice. The camera stays static.
Narration: Someone was inside.

## Panel 3 — Door
Prompt: The old monk opens the heavy wooden door. The camera stays static.
Narration: The door creaked open.

## Panel 4 — Shelter
Prompt: The old monk sets down his broom as rain drips from the eaves. The old monk is %s. %s The shot is a close-up. The old monk faces the camera. The camera stays static.
Dialogue: the old monk: Come in. Sit by the fire. He will see you.
Narration: Inside, the fire was already lit.
""" % (seu.MONK, seu.TEMPLE)
OVER_CAP = "I carry a sealed letter from the harbour master for the abbot of this temple."


def _manifest_ws(tmp_path, monkeypatch, story_id, text, plan=None, images=1):
    """A workspace for bin/ltx-story-manifest (its module WS patched), with character_lib.py and
    lora_catalog.py symlinked in, the story.md, `images` panel stills, and plan (a dict, or the
    raw file text) as generated/stories/<story_id>/plan.json when given."""
    ws = tmp_path / "mws"
    if not ws.exists():
        ws.mkdir()
        for name in ("character_lib.py", "lora_catalog.py"):
            os.symlink(os.path.join(WS, name), str(ws / name))
    monkeypatch.setattr(story_manifest, "WS", str(ws))
    story_md = tmp_path / ("%s.md" % story_id)
    story_md.write_text(text, encoding="utf-8")
    paths = []
    for k in range(1, images + 1):
        path = tmp_path / ("%s_%02d.png" % (story_id, k))
        path.write_bytes(PNG_1X1)
        paths.append(str(path))
    if plan is not None:
        story_dir = ws / "generated" / "stories" / story_id
        story_dir.mkdir(parents=True, exist_ok=True)
        (story_dir / "plan.json").write_text(plan if isinstance(plan, str) else json.dumps(plan),
                                             encoding="utf-8")
    return str(story_md), paths, str(ws)


def _manifest_argv(story_id, story_md, images, mode="chain", panels=2, frames=145, extra=()):
    argv = ["--story-id", story_id, "--prompts-md", story_md]
    if mode == "chain":
        argv += ["--chain", "--image", images[0]]
    elif mode == "shots":
        argv += ["--shots"]
        for image in images:
            argv += ["--image", image]
    else:
        argv += ["--no-images"]
    return argv + ["--fps", "24", "--target-seconds", repr(frames * panels / 24.0),
                   "--min-frames", str(frames), "--max-frames", str(frames), "--force"] + list(extra)


def _read_manifest(ws, story_id):
    with open(os.path.join(ws, "generated", "stories", story_id, "manifest.json"),
              encoding="utf-8") as f:
        return json.load(f)


def test_dlg7_manifest_goldens(tmp_path, monkeypatch):
    chained = CHAINED_DG9.replace(
        "@@LINES@@", "Dialogue: the old monk: You came far. Rest here before the abbot sees you.")
    head = "The old monk lowers his broom and lifts his eyes. The old monk faces the camera. "
    expected = {
        "beats": head + 'The old monk says, "You came far." After a breath, "Rest here before the '
                        'abbot sees you." ' + AC + " The camera stays static.",
        "plain": head + 'The old monk says: "You came far. Rest here before the abbot sees you." '
                        "The camera stays static.",
        "beats-no-acoustic": head + 'The old monk says, "You came far." After a breath, "Rest here '
                                    'before the abbot sees you." The camera stays static.'}
    for delivery, motion in expected.items():
        story_md, images, ws = _manifest_ws(tmp_path, monkeypatch, "dlg7c", chained, plan=CAST_PLAN)
        extra = [] if delivery == "beats" else ["--speech-delivery", delivery]
        assert story_manifest.main(_manifest_argv("dlg7c", story_md, images, extra=extra)) == 0
        panels = _read_manifest(ws, "dlg7c")["panels"]
        assert panels[1]["motion_prompt"] == motion, delivery
        assert (panels[1]["speaker"], panels[1]["speech"], panels[1]["speech_source"],
                panels[1]["narration"], panels[1]["narration_words"]) == (
            "the old monk", "You came far. Rest here before the abbot sees you.", "dialogue", "",
            10)
        assert not {"speaker", "speech", "speech_source"} & set(panels[0])
    story_md, images, ws = _manifest_ws(tmp_path, monkeypatch, "dlg7s", SHOTS_DG9, images=3)
    assert story_manifest.main(_manifest_argv("dlg7s", story_md, images, mode="shots",
                                              panels=3)) == 0
    panel = _read_manifest(ws, "dlg7s")["panels"][2]
    assert panel["motion_prompt"] == (
        'The courier raises the sealed letter toward the gate. The courier faces the camera. The '
        'courier says, "I carry a letter for the abbot." ' + AC + " The camera stays static.")
    assert (panel["speech_source"], panel["narration"]) == ("dialogue", "The bell had not yet rung.")
    story_md, images, ws = _manifest_ws(tmp_path, monkeypatch, "dlg7n", NO_STILLS_DG9,
                                        plan=CAST_PLAN, images=0)
    assert story_manifest.main(_manifest_argv("dlg7n", story_md, images, mode="no_images",
                                              panels=4)) == 0
    panel = _read_manifest(ws, "dlg7n")["panels"][3]
    assert panel["motion_prompt"] == (
        "The old monk sets down his broom as rain drips from the eaves. The old monk is %s. %s The "
        'shot is a close-up. The old monk faces the camera. The old monk says, "Come in." After a '
        'breath, "Sit by the fire." After a short pause, "He will see you." %s The camera stays '
        "static." % (seu.MONK, seu.TEMPLE, AC))
    assert panel["speech"] == "Come in. Sit by the fire. He will see you."


def test_dlg8_narration_alias(tmp_path, monkeypatch):
    alias = CHAINED_DG9.replace(
        "Motion: The old monk lowers his broom and lifts his eyes. The old monk faces the camera. "
        "The camera stays static.\n@@LINES@@",
        "Motion: The courier runs. The camera tracks alongside the movement.\n"
        "Narration: the courier: Keep moving.")
    for delivery, motion in (
            ("beats", 'The courier runs. The courier says, "Keep moving." ' + AC
                      + " The camera tracks alongside the movement."),
            ("plain", 'The courier runs. The courier says: "Keep moving." The camera tracks '
                      "alongside the movement.")):
        story_md, images, ws = _manifest_ws(tmp_path, monkeypatch, "dlg8", alias, plan=CAST_PLAN)
        assert story_manifest.main(_manifest_argv(
            "dlg8", story_md, images, extra=["--speech-delivery", delivery])) == 0
        panel = _read_manifest(ws, "dlg8")["panels"][1]
        assert panel["motion_prompt"] == motion, delivery
        assert (panel["speaker"], panel["speech"], panel["speech_source"], panel["narration"],
                panel["narration_words"]) == ("the courier", "Keep moving.", "narration",
                                              "the courier: Keep moving.", 2)


def test_dlg9_manifest_errors(tmp_path, monkeypatch, capsys):
    tail = SPLIT
    cases = [
        ("Dialogue: the stranger: Halt.", 2, "",
         "Error: panel 2: Dialogue: names 'the stranger', which is no character's referring "
         "phrase; use one of: 'the courier', 'the old monk'\n"),
        ("Dialogue: the courier: " + OVER_CAP, 2, "",
         "Error: panel 2: Dialogue: is 15 words in 1 sentences; a 6.04-second clip fits at most "
         "14 words in 1 sentences" + tail + "\n"),
        ("Narration: the courier: " + OVER_CAP, 0,
         "WARNING: panel 2: the spoken Narration: is 15 words in 1 sentences; a 6.04-second clip "
         "fits at most 14 words in 1 sentences" + tail + "\n", ""),
        ("", 2, "",
         "Error: --pace proportional requires every panel to have a non-empty Narration or "
         "Dialogue field; panel 2 has neither\n"),
    ]
    for i, (lines, rc, out, err) in enumerate(cases):
        story_id = "dlg9-%d" % i
        story_md, images, ws = _manifest_ws(tmp_path, monkeypatch, story_id,
                                            CHAINED_DG9.replace("@@LINES@@", lines), plan=CAST_PLAN)
        capsys.readouterr()
        assert story_manifest.main(_manifest_argv(story_id, story_md, images)) == rc, lines
        captured = capsys.readouterr()
        assert out in captured.out, lines
        assert captured.err == err, lines
        assert os.path.exists(os.path.join(ws, "generated", "stories", story_id,
                                           "manifest.json")) == (rc == 0)


def test_dlg10_dialogue_wins_over_a_prefixed_narration(tmp_path, monkeypatch):
    both = CHAINED_DG9.replace(
        "Motion: The old monk lowers his broom and lifts his eyes. The old monk faces the camera. "
        "The camera stays static.\n@@LINES@@",
        "Motion: The courier waits at the gate. The camera stays static.\n"
        "Dialogue: the courier: Keep moving.\nNarration: the old monk: Wait.")
    story_md, images, ws = _manifest_ws(tmp_path, monkeypatch, "dlg10", both, plan=CAST_PLAN)
    assert story_manifest.main(_manifest_argv("dlg10", story_md, images)) == 0
    panel = _read_manifest(ws, "dlg10")["panels"][1]
    assert (panel["speaker"], panel["speech"], panel["speech_source"], panel["narration"]) == (
        "the courier", "Keep moving.", "dialogue", "the old monk: Wait.")
    assert panel["motion_prompt"] == ('The courier waits at the gate. The courier says, "Keep '
                                      'moving." ' + AC + " The camera stays static.")


def test_review_focus_2_a_spoken_line_that_names_another_cast_member(tmp_path, monkeypatch,
                                                                     story_env, capsys):
    _members(story_env, "kyra", "ronin")
    text = """# Quay

Two travellers on a quay.

## Panel 1 — One
Image: The woman in grey stands on the quay.
Motion: The woman in grey watches the ronin cross the quay. The camera stays static.
Narration: The tide was turning.

## Panel 2 — Two
Motion: The woman in grey lifts her chin. The woman in grey faces the camera. The camera stays static.
Dialogue: the woman in grey: Tell the ronin I am here.
"""
    story_md, images, ws = _manifest_ws(tmp_path, monkeypatch, "rf2", text)
    assert story_manifest.main(_manifest_argv("rf2", story_md, images, extra=[
        "--cast", "the woman in grey=kyra", "--cast", "the ronin=ronin"])) == 0
    panels = _read_manifest(ws, "rf2")["panels"]
    assert panels[1]["motion_prompt"] == (
        "The kyrawmn woman in grey lifts her chin. The kyrawmn woman in grey faces the camera. The "
        'kyrawmn woman in grey says, "Tell the ronin I am here." ' + AC + " The camera stays static.")
    assert [c["name"] for c in panels[1]["characters"]] == ["kyra"]
    assert [c["name"] for c in panels[0]["characters"]] == ["kyra", "ronin"]


def test_review_focus_3_dialogue_with_equal_pace_and_no_narration(tmp_path, monkeypatch):
    text = CHAINED_DG9.replace("Narration: The bell had not yet rung.\n", "").replace(
        "@@LINES@@", "Dialogue: the old monk: You came far.")
    story_md, images, ws = _manifest_ws(tmp_path, monkeypatch, "rf3", text, plan=CAST_PLAN)
    assert story_manifest.main(_manifest_argv("rf3", story_md, images,
                                              extra=["--pace", "equal"])) == 0
    panels = _read_manifest(ws, "rf3")["panels"]
    assert (panels[1]["speech_source"], panels[1]["narration"]) == ("dialogue", "")
    assert 'The old monk says, "You came far." ' + AC in panels[1]["motion_prompt"]
    assert panels[0]["narration"] == "" and "speaker" not in panels[0]


# --- DLG31: Dialogue in place of Narration (S3, V0) ------------------------------------------

def test_dlg31_dialogue_satisfies_the_narration_requirement(tmp_path):
    shots = ('# S\n\n## Characters\n- "the courier": %s.\n\n## Panel 1 — One\nImage: %s The courier '
             "stands at the gate.\nMotion: The courier raises the letter.\n@@LINE@@\n"
             % (seu.COURIER, DG9_SETTING))
    chained = ("# C\n\n## Panel 1 — One\nImage: A quay.\nMotion: The courier waits.\n@@LINE@@\n\n"
               "## Panel 2 — Two\nMotion: The courier runs.\nNarration: Rain fell.\n")
    no_stills = ("# N\n\n## Panel 1 — One\nPrompt: The courier waits on the quay.\n@@LINE@@\n")
    missing_s3 = "panel 1: S3 fields: missing/empty Narration: field"
    missing_v0 = "panel 1: missing/empty Narration: field"
    for line, ok in (("Dialogue: the courier: I carry a letter.", True), ("", False)):
        path = tmp_path / "shots.md"
        path.write_text(shots.replace("@@LINE@@", line), encoding="utf-8")
        panels = story_manifest._parse_prompts_md(str(path))[1]
        found = character_lib.shots_violations(path.read_text(encoding="utf-8"), panels, 1, [])
        assert (missing_s3 not in found) == ok, line
        for text, no_stills_flag, count in ((chained, False, 2), (no_stills, True, 1)):
            path = tmp_path / "story.md"
            path.write_text(text.replace("@@LINE@@", line), encoding="utf-8")
            assert (ltx_movie._validate_story_md(str(path), count, no_stills_flag) == []) == ok
            if not ok:
                assert missing_v0 in ltx_movie._validate_story_md(str(path), count, no_stills_flag)


# --- DLG11, DLG33: the plan's speaker and its coercion (2.2, 2.4, SP2) ------------------------

class _Done(object):
    returncode = 0


def _movie_args(*argv):
    """bin/ltx-movie args after the resolvers main() runs before Phase 1."""
    args = ltx_movie.build_parser().parse_args(list(argv))
    args.video_width, args.video_height = 704, 448
    for resolve in (ltx_movie._resolve_shots, ltx_movie._resolve_casting,
                    ltx_movie._resolve_global_loras, ltx_movie._resolve_story_engine):
        assert resolve(args) == 0
    return args


def test_dlg11_speaking_beat_coercion(ws):
    ctx = seu.make_ctx(se, ws, mode="shots", panels=3)
    raw = seu.plan_json("shots", 3)
    raw["beats"][1].update(speaker="c1", cast=["c1", "c2"])        # a wide shot, tracking
    raw["beats"][2].update(speaker="c1", shot="extreme close-up", camera="slow push-in")
    plan, shape = se.normalize_plan(ctx, raw)
    assert [b["speaker"] for b in plan["beats"]] == ["", "c1", "c1"]
    assert plan["beats"][1]["cast"] == ["c1"]
    assert (plan["beats"][1]["shot"], plan["beats"][1]["camera"]) == ("medium close-up", "static")
    assert (plan["beats"][2]["shot"], plan["beats"][2]["camera"]) == ("close-up", "slow push-in")
    assert plan["speech_notes"] == [
        "beat 2: P14 speaking beat: cast [c1, c2] changed to [c1] so the speaker is alone on screen",
        "beat 2: P14 speaking beat: shot 'wide shot' changed to 'medium close-up' so the speaker's "
        "face stays readable",
        "beat 2: P14 speaking beat: camera 'tracking' changed to 'static' so the speaker's face "
        "stays readable",
        "beat 3: P14 speaking beat: shot 'extreme close-up' changed to 'close-up' so the "
        "speaker's face stays readable"]
    assert se.plan_checks(ctx, plan, shape)[1][-4:] == plan["speech_notes"]
    chained = seu.make_ctx(se, ws)
    raw = seu.plan_json("chained", 3)
    raw["beats"][1]["speaker"] = "c9"
    plan, _shape = se.normalize_plan(chained, raw)
    assert plan["beats"][1]["speaker"] == "" and plan["speech_notes"] == [
        "beat 2: P14 speaking beat: speaker 'c9' is not a cast id, so nobody speaks in this beat"]
    raw["beats"][1]["speaker"] = "c1"
    plan, _shape = se.normalize_plan(chained._replace(narration=False), raw)
    assert plan["beats"][1]["speaker"] == "" and plan["speech_notes"] == [
        "beat 2: P14 speaking beat: speaker 'c1' dropped: this movie has no spoken lines"]
    raw = seu.plan_json("chained", 3)
    raw["beats"][2].update(speaker="c1", shot="wide shot", camera="tracking")
    plan, _shape = se.normalize_plan(chained, raw)
    assert [(b["shot"], b["camera"], b["speaker"]) for b in plan["beats"]] == [
        ("medium shot", "static", ""), ("wide shot", "tracking", ""), ("wide shot", "tracking", "c1")]
    assert plan["speech_notes"] == []
    runner = se._Run(chained, "")
    runner.make_state(0, plan, [se.empty_parts("chained", k, plan) for k in (1, 2, 3)])
    with open(os.path.join(chained.story_dir, "story_rounds", "round_0", "plan.json"),
              encoding="utf-8") as f:
        saved = json.load(f)
    assert [b["speaker"] for b in saved["beats"]] == ["", "", "c1"]
    assert saved["speech_notes"] == [] and list(saved)[-1] == "speech_notes"


def test_dlg33_an_older_plan_json_loads(ws):
    ctx = seu.make_ctx(se, ws)
    plan, _shape = se.normalize_plan(ctx, seu.plan_json("chained", 3))
    del plan["speech_notes"]
    for beat in plan["beats"]:
        del beat["speaker"]
    with open(os.path.join(ctx.story_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f)
    loaded = se.load_plan(ctx)
    assert [b["speaker"] for b in loaded["beats"]] == ["", "", ""]
    assert loaded["speech_notes"] == []


def test_story_context_carries_the_clip_length(tmp_path, monkeypatch):
    monkeypatch.setattr(ltx_movie, "WS", seu.make_ws(tmp_path))
    ctx = ltx_movie._story_context(_movie_args("n", "--story-id", "x", "--frames", "97"))
    assert (ctx.seconds, ctx.clip_seconds) == ("4", 97 / 24.0)
    assert se.engine_seconds(ctx) == 97 / 24.0
    assert se.engine_seconds(ctx._replace(clip_seconds=None)) == 4.0
    assert ltx_movie._story_context(_movie_args("n", "--story-id", "x")).clip_seconds == 145 / 24.0


# --- DLG12: the plan prompt (8.1) ------------------------------------------------------------

def test_dlg12_plan_prompt_speaker_rule(ws):
    spoken = (" speaker is the id of the one character who says something aloud on screen during "
              "the beat, or an empty string when nobody speaks; give a speaker only where a spoken "
              "line moves the story. A beat with a speaker shows only that character (its cast is "
              "just their id), in a medium close-up or close-up, facing the camera, with the camera "
              "static or a slow push-in.")
    silent = " speaker is always an empty string: nobody speaks in this movie."
    for mode in ("chained", "no_stills", "shots"):
        for narration, rule in ((True, spoken), ("speech", spoken), (False, silent)):
            prompt = se.build_plan_prompt(seu.make_ctx(se, ws, mode=mode, narration=narration),
                                          [], [])
            where = (mode, narration)
            assert ("at most %d.%s\n" % (se.MAX_CAST[mode], rule)) in prompt, where
            assert ("with the keys index, arc, action, shot, camera, location, cast and speaker."
                    in prompt), where
            assert "not a sequence of steps, with no on-screen text." in prompt, where
            assert "no dialogue" not in prompt and "@@" not in prompt, where


# --- DLG13, DLG14, Review Focus 1: writer keys and the panel prompt (SP5, 8.2) ----------------

def _speaking(k=2, speaker="c1"):
    """A plan mutation: speaker speaks in beat k."""
    def mutate(raw):
        raw["beats"][k - 1]["speaker"] = speaker
    return mutate


def _story(ws, mode, n=3, plan_mut=None, replies=None, ctx_kw=None):
    """(ctx, plan, parts, text, path) for seu.plan_json/panel_json; replies maps a panel number to
    a dict merged into that panel's writer reply before it is parsed (a speaking panel's reply
    needs a "dialogue")."""
    ctx = seu.make_ctx(se, ws, mode=mode, panels=n, **(ctx_kw or {}))
    raw = seu.plan_json(mode, n)
    if plan_mut:
        plan_mut(raw)
    plan, _shape = se.normalize_plan(ctx, raw)
    phrase = plan["cast"][0]["phrase"]
    parts = []
    for k in range(1, n + 1):
        reply = dict(seu.panel_json(mode, k, phrase), **(replies or {}).get(k, {}))
        parts.append(se.parse_panel_reply(ctx, plan, k, json.dumps(reply)))
    text = se.assemble(ctx, plan, parts)
    path = os.path.join(ctx.story_dir, "check.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return ctx, plan, parts, text, path


NO_STILLS_PROMPT = (
    "prompt: W1 to W2 words in the present tense: one flowing paragraph in strict chronological "
    "order that opens with the main action, carries enough separate beats to fill the full "
    "@@SECONDS@@ seconds, links them with temporal connectors (initially, as, then, while, a moment "
    "later), names the ambient and environmental sounds alongside the actions that make them, and "
    "states the camera viewpoint and the lighting and colour; you may also state a camera "
    "movement. Name each character only by their referring phrase. Do not describe any "
    "character's appearance or clothing, do not write a sentence about the place itself and do "
    "not name the shot type: the pipeline adds each character's description, the place's setting "
    "sentence, the shot type and, unless you state one, the camera movement itself. Describe only "
    "what is physically observable, with no mood words, no spoken words and no markdown.")
LINE = "Keep moving. The gate is close."


def test_dlg13_writer_keys_and_speaking_key_lines(ws):
    base = {("chained", 1): ["title", "image", "motion"], ("chained", 2): ["title", "motion"],
            ("no_stills", 1): ["title", "prompt"], ("no_stills", 2): ["title", "prompt"],
            ("shots", 1): ["title", "image", "motion"], ("shots", 2): ["title", "image", "motion"]}
    for (mode, k), keys in base.items():
        for narration in (True, "speech", False):
            for speaks in (False, True):
                expected = (keys + (["dialogue"] if speaks and narration is not False else [])
                            + (["narration"] if narration is True else []))
                assert list(se.writer_keys(mode, k, narration, speaks)) == expected, (
                    mode, k, narration, speaks)
    assert se.writer_keys("chained", 2) == ("title", "motion", "narration")
    for name, text in se.KEY_LINE_TEMPLATES.items():
        assert "Do not mention the camera" not in text and "camera or lens" not in text, name
    assert "narration_speech" not in se.KEY_LINE_TEMPLATES
    assert se.KEY_LINE_TEMPLATES["no_stills_prompt"] == NO_STILLS_PROMPT
    assert se.KEY_LINE_TEMPLATES["narration"] == (
        "narration: one sentence of 3 to 30 words of voice-over that nobody on screen says aloud. "
        "Never put a spoken line here.")
    assert se.KEY_LINE_TEMPLATES["narration_with_dialogue"] == (
        "narration: one sentence of 3 to 30 words of voice-over that nobody on screen says aloud, "
        "or an empty string: this panel's spoken line goes in dialogue, never here.")
    ctx, plan, parts, _t, _p = _story(ws, "chained", 3, plan_mut=_speaking(2),
                                      replies={2: {"dialogue": LINE}})
    prompt = se.build_panel_prompt(ctx, plan, parts, 2)
    assert ('\ndialogue: the exact words "the courier" says aloud in this panel: at most 14 words '
            "as one sentence, about one word fewer for each further sentence, and at most three "
            "sentences; no quotation marks, no speaker name and no description of how the words "
            "are said -- the pipeline adds who says them and how.\n") in prompt
    assert "\n" + se.KEY_LINE_TEMPLATES["narration_with_dialogue"] + "\n" in prompt
    assert ('already on screen. You may add one camera direction. In this panel "the courier" '
            "speaks the dialogue: keep their movement small -- a breath, a glance, a small hand "
            "gesture -- with the camera holding still, and do not write the spoken words or a "
            "speaking verb here; the pipeline adds them.\n") in prompt
    assert "@@" not in prompt
    quiet = se.build_panel_prompt(ctx, plan, parts, 3)
    assert "\ndialogue: " not in quiet
    assert "\n" + se.KEY_LINE_TEMPLATES["narration"] + "\n" in quiet
    ctx, plan, parts, _t, _p = _story(ws, "no_stills", 3, plan_mut=_speaking(2),
                                      replies={2: {"dialogue": LINE}})
    prompt = se.build_panel_prompt(ctx, plan, parts, 2)
    assert ('fills the full 6 seconds with small, continuous movements of "the courier" -- a '
            "breath, a glance, a small hand gesture -- names the ambient") in prompt
    assert ("no spoken words and no markdown. Do not write the spoken words or a speaking verb "
            "here; the pipeline adds them.\n") in prompt
    ctx, plan, parts, _t, _p = _story(ws, "shots", 3, plan_mut=_speaking(2),
                                      replies={2: {"dialogue": LINE}})
    prompt = se.build_panel_prompt(ctx, plan, parts, 2)
    assert ('Never name a person who is not in this shot. "the courier" is the only person in the '
            "frame, facing the camera.\n") in prompt
    assert ('without one, the pipeline adds the planned camera sentence. In this panel "the '
            'courier" speaks the dialogue:') in prompt
    ctx, plan, parts, _t, _p = _story(ws, "chained", 3, plan_mut=_speaking(2),
                                      replies={2: {"dialogue": LINE}},
                                      ctx_kw={"seconds": "4", "clip_seconds": 97 / 24.0})
    assert "at most 9 words as one sentence" in se.build_panel_prompt(ctx, plan, parts, 2)


def test_dlg14_parse_panel_reply_on_a_speaking_panel(ws):
    ctx = seu.make_ctx(se, ws)
    raw = seu.plan_json("chained", 3)
    raw["beats"][1]["speaker"] = "c1"
    plan, _shape = se.normalize_plan(ctx, raw)
    reply = dict(seu.panel_json("chained", 2), narration="",
                 dialogue='the courier: You came far. He said "wait".')
    parts = se.parse_panel_reply(ctx, plan, 2, json.dumps(reply))
    assert list(parts) == ["title", "motion", "dialogue", "narration"]
    assert (parts["dialogue"], parts["narration"]) == ("You came far. He said 'wait'.", "")
    assert se.parse_panel_reply(ctx, plan, 2, json.dumps(dict(reply, dialogue="  "))) is None
    no_line = dict(reply)
    del no_line["dialogue"]
    assert se.parse_panel_reply(ctx, plan, 2, json.dumps(no_line)) is None
    quiet = se.parse_panel_reply(ctx, plan, 3, json.dumps(dict(seu.panel_json("chained", 3),
                                                               dialogue="Ignored.")))
    assert list(quiet) == ["title", "motion", "narration"]
    assert se.parse_panel_reply(ctx, plan, 3, json.dumps(dict(seu.panel_json("chained", 3),
                                                              narration=""))) is None
    speech = ctx._replace(narration="speech")
    plan_speech, _shape = se.normalize_plan(speech, raw)
    assert list(se.parse_panel_reply(speech, plan_speech, 2, json.dumps(reply))) == [
        "title", "motion", "dialogue"]
    off = ctx._replace(narration=False)
    plan_off, _shape = se.normalize_plan(off, raw)
    assert list(se.parse_panel_reply(off, plan_off, 2, json.dumps(reply))) == ["title", "motion"]
    assert se.unparseable_panel_problem("chained", 2, True, True) == (
        "the reply is not one JSON object with the keys title, motion, dialogue, narration")


def test_review_focus_1_writer_dialogue_with_label_prefix_and_quotes(ws):
    ctx = seu.make_ctx(se, ws)
    raw = seu.plan_json("chained", 3)
    raw["beats"][1]["speaker"] = "c1"
    plan, _shape = se.normalize_plan(ctx, raw)
    for written in ("dialogue: the courier: “Keep moving.”", 'The Courier: "Keep moving."',
                    '"Keep moving."', "the courier:   Keep   moving."):
        reply = dict(seu.panel_json("chained", 2), dialogue=written)
        assert se.parse_panel_reply(ctx, plan, 2, json.dumps(reply))["dialogue"] == (
            "Keep moving."), written


def test_empty_parts_uses_panel_keys_with_ctx(ws):
    ctx, plan, _parts, _t, _p = _story(ws, "chained", 3, plan_mut=_speaking(2),
                                       replies={2: {"dialogue": LINE}})
    got = se.empty_parts(ctx.mode, 2, plan, ctx)
    assert sorted(got) == sorted(se.panel_keys(ctx, plan, 2))
    assert "dialogue" in got
    assert "dialogue" not in se.empty_parts(ctx.mode, 2, plan)
    ctx, plan, _parts, _t, _p = _story(ws, "chained", 3, plan_mut=_speaking(2),
                                       replies={2: {"dialogue": LINE}},
                                       ctx_kw={"narration": "speech"})
    got = se.empty_parts(ctx.mode, 2, plan, ctx)
    assert "narration" not in got and "dialogue" in got


# --- DLG15: assembly (SP4, CM4) --------------------------------------------------------------

SPEAKING_WRITERS = {
    "chained": [{"title": "Wet Road", "image": "The courier waits on the left",
                 "motion": "The courier pushes off", "narration": "The rain had not stopped"},
                {"title": "The Bend", "motion": "The courier leans into the bend.",
                 "dialogue": LINE, "narration": ""}],
    "no_stills": [{"title": "Wet Road", "prompt": "The courier pedals through the rain",
                   "narration": "The rain had not stopped"},
                  {"title": "The Bend", "prompt": "The courier leans into the bend.",
                   "dialogue": LINE, "narration": "Every street led down to the water."}],
    "shots": [{"title": "Wet Road", "image": "The courier waits on the left",
               "motion": "The courier pushes off", "narration": "The rain had not stopped"},
              {"title": "The Bend", "image": "The courier leans right.",
               "motion": "The courier leans into the bend.", "dialogue": LINE,
               "narration": "Every street led down to the water."}],
}
HEAD = ("# The Sealed Letter\n\nA courier carries a sealed letter through a rainy harbour town and "
        "delivers it at the temple gate.\n\n")
IDENTITY = "The courier is " + seu.COURIER + "."
PANEL1_IMAGE = ("Image: " + seu.HARBOUR + " " + IDENTITY
                + " The courier waits on the left. The shot is a medium shot.\n")
PANEL1_REST = "Motion: The courier pushes off. The camera stays static.\nNarration: The rain had not stopped.\n\n"
DIALOGUE_LINE = "Dialogue: the courier: Keep moving. The gate is close.\n"
GOLDEN_SPEAKING = {
    "chained": (HEAD + "## Panel 1 — Wet Road\n" + PANEL1_IMAGE + PANEL1_REST
                + "## Panel 2 — The Bend\nMotion: The courier leans into the bend. The courier "
                  "faces the camera. The camera stays static.\n" + DIALOGUE_LINE),
    "no_stills": (HEAD + "## Panel 1 — Wet Road\nPrompt: The courier pedals through the rain. "
                  + IDENTITY + " " + seu.HARBOUR + " The shot is a medium shot. The camera stays "
                  "static.\nNarration: The rain had not stopped.\n\n## Panel 2 — The Bend\nPrompt: "
                  "The courier leans into the bend. " + IDENTITY + " " + seu.HARBOUR + " The shot "
                  "is a medium close-up. The courier faces the camera. The camera stays static.\n"
                  + DIALOGUE_LINE + "Narration: Every street led down to the water.\n"),
    "shots": (HEAD + "## Characters\n- \"the courier\": " + seu.COURIER + ".\n- \"the old monk\": "
              + seu.MONK + ".\n\n## Panel 1 — Wet Road\n" + PANEL1_IMAGE + PANEL1_REST
              + "## Panel 2 — The Bend\nImage: " + seu.HARBOUR + " " + IDENTITY + " The courier "
                "leans right. The courier faces the camera. The shot is a medium close-up.\n"
                "Motion: The courier leans into the bend. The courier faces the camera. The camera "
                "stays static.\n" + DIALOGUE_LINE
              + "Narration: Every street led down to the water.\n"),
}


def test_dlg15_assembly_goldens_and_dedupe(ws, tmp_path):
    for mode, golden in GOLDEN_SPEAKING.items():
        ctx = seu.make_ctx(se, ws, mode=mode, panels=2)
        raw = seu.plan_json(mode, 2)
        raw["beats"][1]["speaker"] = "c1"
        plan, _shape = se.normalize_plan(ctx, raw)
        text = se.assemble(ctx, plan, SPEAKING_WRITERS[mode])
        assert text == golden, mode
        path = tmp_path / ("%s.md" % mode)
        path.write_text(text, encoding="utf-8")
        panel = story_manifest._parse_prompts_md(str(path))[1][1]
        assert panel["dialogue"] == "the courier: " + LINE
        assert character_lib.parse_dialogue(panel["dialogue"], PHRASES) == ("the courier", LINE,
                                                                            None)
        labels = [label for label, _text in se.story_fields(mode, 2, panel)]
        assert labels[-2:] == ["Dialogue", "Narration"], mode
        assert [label for label, _text in se.story_fields(mode, 2, panel, False)][-1] == "Dialogue"
    ctx = seu.make_ctx(se, ws, mode="shots", panels=2)
    plan, _shape = se.normalize_plan(ctx, seu.plan_json("shots", 2))
    parts = [dict(SPEAKING_WRITERS["shots"][0]),
             dict(SPEAKING_WRITERS["shots"][1], motion="The courier turns. The camera slowly pans "
                                                       "left.")]
    assert dict(se.panel_fields(ctx, plan, parts, 2))["Motion"] == (
        "The courier turns. The camera slowly pans left.")
    assert se.pasted_pieces(ctx, plan, 2)["motion"] == ["The camera tracks alongside the movement."]
    parts[1]["motion"] = "The courier turns. The camera viewpoint is front-facing."
    assert dict(se.panel_fields(ctx, plan, parts, 2))["Motion"] == (
        "The courier turns. The camera viewpoint is front-facing. The camera tracks alongside the "
        "movement.")
    raw = seu.plan_json("shots", 2)
    raw["beats"][1]["speaker"] = "c1"
    plan, _shape = se.normalize_plan(ctx, raw)
    parts[1]["motion"] = "The courier turns. The camera slowly pans left."
    assert dict(se.panel_fields(ctx, plan, parts, 2))["Motion"] == (
        "The courier turns. The camera slowly pans left. The courier faces the camera. The camera "
        "stays static.")
    assert se.pasted_pieces(ctx, plan, 2)["motion"] == ["The courier faces the camera.",
                                                        "The camera stays static."]
    lib = se._character_lib(WS)
    fields = [("Motion", "The courier waits."),
              ("Dialogue", "the courier: Tell the old monk <later>.")]
    assert se._field_checks(ctx, lib, plan, 2, "T", fields, {"Dialogue": "Tell the old monk "
                                                                         "<later>."},
                            ("N4", "N10"), []) == ([], [])


def test_shots_s5_ignores_the_pasted_facing_sentence(ws):
    # Controller ruling Q1 (Spec amendment 1): the pasted facing sentence is not an S5 action.
    s5 = ("panel 2: S5 one action: Motion: has 2 action sentences; it must have exactly one, "
          "optionally followed by a camera sentence")
    ctx, plan, parts, text, path = _story(ws, "shots", 3, plan_mut=_speaking(2),
                                          replies={2: {"dialogue": LINE}})
    hard, advisory = se.panel_checks(ctx, plan, parts, text, path)
    assert not [m for m in hard + advisory if " S5 " in m]
    panels = story_manifest._parse_prompts_md(path)[1]
    assert panels[1]["motion"].endswith(" The courier faces the camera. The camera stays static.")
    assert s5 in character_lib.shots_violations(text, panels, 3, [])
    assert s5 not in character_lib.shots_violations(text, panels, 3, [], ignore_facing=True)
    panels[1]["motion"] = panels[1]["motion"].replace(
        "The courier faces the camera.", "The courier faces the camera. The courier waves.")
    assert s5 in character_lib.shots_violations(text, panels, 3, [], ignore_facing=True)
    assert se.FACING_SENTENCE == character_lib.FACING_SENTENCE


# --- DLG16, DLG17, Review Focus 4: T1, T2, T3, N18 and the Dialogue N16/N17 (6.2, 7) ------------

BUSY = "The courier stops at the crates, then turns, then pedals on toward the far end of the wet road."
OVERLOAD = ("The courier stops, then turns, then waves, then pedals on, then rides away along the "
            "wet road.")
SIXTEEN = "I carry a sealed letter from the old harbour master for the abbot of this temple."


def _checks(ws, mode, **kw):
    ctx, plan, parts, text, path = _story(ws, mode, 3, **kw)
    return se.panel_checks(ctx, plan, parts, text, path)


def _only(messages, rule):
    return [m for m in messages if " %s " % rule in m]


def test_dlg16_t1_spoken_timing(ws):
    def t1(line):
        hard, advisory = _checks(ws, "chained", plan_mut=_speaking(2), replies={2: {"dialogue": line}})
        assert not _only(advisory, "T1")
        return _only(hard, "T1")

    assert t1(SIXTEEN) == ["panel 2: T1 spoken timing: Dialogue: is 16 words in 1 sentences; a "
                           "6-second clip fits at most 14 words in 1 sentences" + SPLIT]
    assert t1("Come in now. Sit by the warm fire. He will see you soon.") == [
        "panel 2: T1 spoken timing: Dialogue: is 13 words in 3 sentences; a 6-second clip fits at "
        "most 12 words in 3 sentences" + SPLIT]
    assert t1("Stop. Wait. Look. Go.") == [
        "panel 2: T1 spoken timing: Dialogue: is 4 words in 4 sentences; a 6-second clip fits at "
        "most 11 words in 4 sentences" + SPLIT]
    assert t1(LINE) == []
    hard, advisory = _checks(ws, "chained", replies={2: {"narration": "the courier: " + SIXTEEN}})
    assert not _only(hard, "T1")
    assert _only(advisory, "T1") == [
        "panel 2: T1 spoken timing: Narration: speaks 16 words in 1 sentences; a 6-second clip "
        "fits at most 14 words in 1 sentences" + SPLIT]


def test_dlg17_t2_t3_action_amount(ws):
    def t(mode, key, text):
        hard, advisory = _checks(ws, mode, replies={2: {key: text}})
        assert not _only(advisory, "T2") and not _only(advisory, "T3")
        return _only(hard, "T2") + _only(hard, "T3")

    cut = ", so cut the extra actions and keep every other sentence word for word"
    assert t("chained", "motion", "The courier stops at the crates, then pedals on toward the far "
                                  "end of the wet road.") == []
    assert t("chained", "motion", BUSY) == [
        "panel 2: T2 action amount: Motion: holds 3 actions; a 6-second clip fits at most 2" + cut]
    assert t("chained", "motion", OVERLOAD) == [
        "panel 2: T3 action overload: Motion: holds 5 actions; a 6-second clip fits at most 2 and "
        "cannot render more than 4; give the extra actions their own panels"]
    assert t("shots", "motion", "The courier turns. The courier waves. The courier steps "
                                "forward.") == [
        "panel 2: T2 action amount: Motion: holds 3 actions; a 6-second clip fits at most 2" + cut]
    six = ("The courier pedals along the wet harbour road. Initially the tyres hiss. A moment later "
           "a gull cries. Moments later the rain thickens. Finally the bell rings. After that the "
           "lamps glow. Soon after the courier slows.")
    assert t("no_stills", "prompt", six) == [
        "panel 2: T2 action amount: Prompt: holds 7 actions; a 6-second clip fits at most 6" + cut]
    assert t("chained", "motion", "The camera slowly pans left. The camera holds.") == [
        "panel 2: T2 action amount: Motion: has no physical action; a 6-second clip needs one, so "
        "add one action sentence and keep every other sentence word for word"]
    for mode in ("chained", "no_stills", "shots"):
        ctx, plan, parts, text, path = _story(ws, mode, 6)
        hard, advisory = se.panel_checks(ctx, plan, parts, text, path)
        assert not [m for m in hard + advisory if " T1 " in m or " T2 " in m or " T3 " in m], mode
    assert se.GENERATION_CHECKS[16:20] == ("N18", "T1", "T2", "T3")
    assert se.RECHECK_IDS[14:18] == ("N18", "T1", "T2", "T3")


def test_n16_n17_n18_dialogue_messages(ws):
    ctx, plan, _parts, _text, _path = _story(ws, "chained", 3, plan_mut=_speaking(2),
                                             replies={2: {"dialogue": "Keep moving."}})
    lib = se._character_lib(WS)
    ids = ("N16", "N17", "N18", "T1")

    def checks(fields, writers=None, beat_cast=None):
        p = copy.deepcopy(plan)
        if beat_cast:
            p["beats"][1]["cast"] = beat_cast
        return se._field_checks(ctx, lib, p, 2, "T", fields, writers or {}, ids, [])

    waits = ("Motion", "The courier waits.")
    assert checks([waits, ("Dialogue", "the stranger: Halt.")]) == ([
        "panel 2: N18 dialogue: Dialogue: names 'the stranger', which is no character's referring "
        "phrase; use one of: 'the courier', 'the old monk'"], [])
    assert checks([waits, ("Dialogue", "the courier:")]) == ([
        "panel 2: N18 dialogue: Dialogue: has a speaker but no words"], [])
    assert checks([waits, ("Dialogue", "the old monk: Wait for me.")]) == ([], [
        "panel 2: N16 speaker: Dialogue: is spoken by 'the old monk', who is not in this shot; put "
        "'the old monk' in the shot or move the line to a panel that shows them"])
    assert checks([waits, ("Dialogue", "the courier: Keep moving.")], beat_cast=["c1", "c2"]) == (
        [], ["panel 2: N17 speaking shot: Dialogue: 'the courier' speaks in a shot that also shows "
             "'the old monk'; a speaking shot shows only the speaker"])
    pans = "The courier waits. The camera slowly pans left."
    assert checks([("Motion", pans), ("Dialogue", "the courier: Keep moving.")],
                  {"Motion": pans}) == ([], [
        "panel 2: N17 speaking shot: Motion: has the camera direction 'The camera slowly pans "
        "left.' while 'the courier' speaks; a speaking shot keeps the camera static"])
    pushes = "The courier waits. The camera slowly pushes in."
    assert checks([("Motion", pushes), ("Dialogue", "the courier: Keep moving.")],
                  {"Motion": pushes}) == ([], [])


def test_review_focus_4_a_short_clip_uses_the_same_cap_in_engine_and_manifest(ws, tmp_path,
                                                                              monkeypatch, capsys):
    ten = "I carry a letter for the abbot of this temple."
    short = {"seconds": "4", "clip_seconds": 97 / 24.0}
    hard, _advisory = _checks(ws, "chained", plan_mut=_speaking(2), replies={2: {"dialogue": ten}},
                              ctx_kw=short)
    assert _only(hard, "T1") == ["panel 2: T1 spoken timing: Dialogue: is 10 words in 1 "
                                 "sentences; a 4-second clip fits at most 9 words in 1 sentences"
                                 + SPLIT]
    hard, _advisory = _checks(ws, "chained", plan_mut=_speaking(2), replies={2: {"dialogue": ten}})
    assert _only(hard, "T1") == []
    story_md, images, mws = _manifest_ws(tmp_path, monkeypatch, "rf4", CHAINED_DG9.replace(
        "@@LINES@@", "Dialogue: the old monk: " + ten), plan=CAST_PLAN)
    capsys.readouterr()
    assert story_manifest.main(_manifest_argv("rf4", story_md, images, frames=97)) == 2
    assert capsys.readouterr().err == (
        "Error: panel 2: Dialogue: is 10 words in 1 sentences; a 4.04-second clip fits at most 9 "
        "words in 1 sentences" + SPLIT + "\n")


# --- DLG23, DLG24, DLG26: the round controller (6.1, 6.5, PG5, 6.8) --------------------------

def _replies(mode, n, overrides=None, phrase="the courier"):
    """The fake agent's panel script: one valid reply per panel; overrides maps a panel number to
    a list of dicts, each merged into that panel's seu.panel_json reply (one reply per call)."""
    script = {}
    for k in range(1, n + 1):
        changes = (overrides or {}).get(k, [{}])
        script[str(k)] = [seu.answer(dict(seu.panel_json(mode, k, phrase), **c)) for c in changes]
    return script


def _run(ws, tmp_path, monkeypatch, mode="chained", n=3, plan=None, panel=None, critic=(),
         **ctx_kw):
    log = seu.script_agent(monkeypatch, tmp_path,
                           plan=plan if plan is not None else [seu.answer(seu.plan_json(mode, n))],
                           panel=panel if panel is not None else _replies(mode, n),
                           critic=list(critic))
    ctx = seu.make_ctx(se, ws, mode=mode, panels=n, **ctx_kw)
    rc, advisories = se.run(ctx)
    return rc, advisories, ctx, seu.agent_log(log)


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _speaking_plan(mode, n, *ks):
    raw = seu.plan_json(mode, n)
    for k in ks:
        raw["beats"][k - 1]["speaker"] = "c1"
    return [seu.answer(raw)]


T2_MESSAGE = ("panel 2: T2 action amount: Motion: holds 3 actions; a 6-second clip fits at most 2, "
              "so cut the extra actions and keep every other sentence word for word")


def test_dlg23_two_rounds_blocking_and_ranking(ws, tmp_path, monkeypatch, capsys):
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, panel=_replies("chained", 3, {2: [
        {"motion": BUSY}]}), critic=[seu.answer(seu.critic_json((6, 6, 6), "revise")),
                                     seu.answer(seu.critic_json((7, 7, 7), "revise"))])
    assert rc == 0
    out = capsys.readouterr().out
    assert "stop: max_rounds; best round 2 (1 hard)\n" in out
    assert out.endswith("Warning: unresolved after 2 critic round(s): %s\n" % T2_MESSAGE)
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert checks["hard"] == [] and [v["message"] for v in checks["unresolved"]] == [T2_MESSAGE]
    run_doc = _read_json(os.path.join(ctx.story_dir, "story_rounds", "run.json"))
    assert run_doc["budgets"]["critic_rounds"] == 2
    assert [r["stage"] for r in log].count("critic") == 2
    t3 = ("panel 2: T3 action overload: Motion: holds 5 actions; a 6-second clip fits at most 2 "
          "and cannot render more than 4; give the extra actions their own panels")
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, story_id="t3", panel=_replies(
        "chained", 3, {2: [{"motion": OVERLOAD}, {"motion": OVERLOAD}]}),
        critic=[{"answer": "x"}] * 4)
    assert rc == 0
    assert ("Warning: unresolved after 1 critic round(s): %s\n" % t3) in capsys.readouterr().out
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, story_id="t1",
                            plan=_speaking_plan("chained", 3, 2), panel=_replies(
                                "chained", 3, {2: [{"dialogue": OVER_CAP}, {"dialogue": OVER_CAP}]}),
                            critic=[{"answer": "x"}] * 4)
    assert rc == 2
    err = capsys.readouterr().err
    assert err.startswith("Error: story.md has 1 hard violation(s) after the critic rounds")
    assert "split it across alternating close-up panels (the speaker, then the listener, then the " \
           "speaker again)" in err
    t1 = ("panel 2: T1 spoken timing: Dialogue: is 15 words in 1 sentences; a 6-second clip fits "
          "at most 14 words in 1 sentences" + SPLIT)
    a = {"hard": [t1], "advisory": [], "scores": None}
    t2s = [T2_MESSAGE.replace("panel 2:", "panel %d:" % k) for k in (1, 2, 3)]
    b = {"hard": t2s, "advisory": [], "scores": None}
    assert se.best_round([a, b]) == 1 and se.better([a, b], 1, 0)
    assert se.final_outcome([a, b]) == (1, [], t2s)
    assert se.final_outcome([a]) == (0, [t1], [])


def test_dlg24_code_only_round_merge(ws):
    ctx = seu.make_ctx(se, ws, mode="shots", panels=3)
    raw = seu.plan_json("shots", 3)
    raw["beats"][1]["speaker"] = "c1"
    plan, _shape = se.normalize_plan(ctx, raw)
    old = {"title": "Old", "image": "The courier stands at the gate.",
           "motion": "The courier turns, then waves.", "dialogue": OVER_CAP,
           "narration": "It rained."}
    new = {"title": "New", "image": "A different picture.", "motion": "The courier waves.",
           "dialogue": "I carry a letter.", "narration": "It poured."}
    assert se.merge_repair(ctx, plan, 2, old, new, {"T2"}) == dict(old, motion="The courier waves.")
    assert se.merge_repair(ctx, plan, 2, old, new, {"T1"}) == dict(old, dialogue="I carry a letter.")
    assert se.merge_repair(ctx, plan, 2, old, new, {"N11"}) == dict(old, narration="It poured.")
    assert se.merge_repair(ctx, plan, 2, old, dict(new, dialogue=OVER_CAP + " Again."),
                           {"T1"}) == old
    wide = dict(old, motion="The courier turns. The courier waves, then bows.")
    rewrite = dict(new, motion="The courier kneels. The courier bows. The courier rises.")
    assert se.merge_repair(ctx, plan, 2, wide, rewrite, {"T2"}) == wide
    assert se.merge_repair(ctx, plan, 2, old, new, {"N7"}) == old


def test_dlg26_judge_gate_is_report_only(tmp_path, monkeypatch, capsys):
    ws = seu.make_ws(tmp_path, fake_judge=True)
    reply = seu.critic_json((4, 8, 8), "revise", [
        {"target": "panel", "index": 2, "field": "motion", "reason": "r",
         "replacement": "The courier waves."}])
    monkeypatch.setenv("FAKE_JUDGE_REPLY", json.dumps(reply))
    monkeypatch.setenv("FAKE_JUDGE_LOG", os.path.join(str(tmp_path), "judge_log.jsonl"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-key")
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, judge=True)
    assert rc == 0
    rounds = os.path.join(ctx.story_dir, "story_rounds")
    saved = os.path.join(rounds, "round_0", "judgment.patches.json")
    assert _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["judge"] == {
        "status": "ok", "detail": "min score 4",
        "scores": {"continuity": 4, "story": 8, "renderability": 8}, "min_score": 4,
        "applied": False}
    assert sorted(os.listdir(rounds)) == ["round_0", "run.json"]
    with open(os.path.join(rounds, "round_0", "story.md"), encoding="utf-8") as f:
        round_0 = f.read()
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        assert f.read() == round_0
    assert ("Warning: judge-story minimum score 4 is below 7; its patches are saved in %s and were "
            "not applied (only spoken timing and the amount of action are repaired automatically)\n"
            % saved) in capsys.readouterr().out
    assert _read_json(saved)["patches"] == reply["patches"]


# --- DLG20, DLG22: the patch whitelist and guards (PG1-PG4) ----------------------------------

NOT_REPAIRED_REASON = ("not repaired automatically: only spoken timing and the amount of action "
                       "are patched")
THREE = ("The courier stops at the crates, then turns, then pedals on. The courier glances up at "
         "the rain. The camera slowly pans left.")
ONE_CHANGED = ("The courier stops at the crates and pedals on. The courier glances up at the rain. "
               "The camera slowly pans left.")
TWO_CHANGED = ("The courier stops at the crates and pedals on. The courier looks up at the grey "
               "sky. The camera slowly pans left.")


def _patch(target, index, field, replacement):
    return {"target": target, "index": index, "field": field, "reason": "r",
            "replacement": replacement}


def test_dlg20_apply_patches_whitelist_and_guard(ws):
    no_problem = ("panel %d has no hard timing or amount-of-action problem; advisory findings are "
                  "never patched")
    ctx, plan, parts, _t, _p = _story(ws, "chained", 3, plan_mut=_speaking(2),
                                      replies={2: {"motion": THREE, "dialogue": OVER_CAP}})
    state = {"plan": plan, "parts": parts}
    result = se.apply_patches(ctx, state, [
        _patch("plan", 2, field, "x") for field in ("beat.action", "beat.shot", "beat.camera",
                                                    "location.setting")]
        + [_patch("panel", 1, "image", "x"), _patch("panel", 2, "narration", "x")])
    assert len(result) == 3
    new, applied, rejected = result
    assert applied == [] and new == state
    assert [r["reason"] for r in rejected] == [NOT_REPAIRED_REASON] * 6
    _new, applied, rejected = se.apply_patches(ctx, state, [
        _patch("panel", 2, "motion", ONE_CHANGED), _patch("panel", 3, "dialogue", "Hello there.")],
        repairable={2: {"T1"}})
    assert applied == [] and [r["reason"] for r in rejected] == [no_problem % 2, no_problem % 3]
    new, applied, rejected = se.apply_patches(ctx, state, [
        _patch("panel", 2, "dialogue", 'the courier: "I carry a letter for the abbot"')],
        repairable={2: {"T1"}})
    assert len(applied) == 1 and new["parts"][1]["dialogue"] == "I carry a letter for the abbot."
    for replacement, reason in (
            (OVER_CAP, "the new line is 15 words in 1 sentences; at most 14 words in 1 sentences "
                       "fit this clip"),
            ('  ""  ', "empty after cleanup")):
        _new, applied, rejected = se.apply_patches(ctx, state, [
            _patch("panel", 2, "dialogue", replacement)])
        assert applied == [] and [r["reason"] for r in rejected] == [reason], replacement
    new, applied, rejected = se.apply_patches(ctx, state, [_patch("panel", 2, "motion",
                                                                  ONE_CHANGED)])
    assert len(applied) == 1 and new["parts"][1]["motion"] == ONE_CHANGED
    _new, applied, rejected = se.apply_patches(ctx, state, [_patch("panel", 2, "motion",
                                                                   TWO_CHANGED)])
    assert [r["reason"] for r in rejected] == [
        "the patch changes 2 sentences; it may change at most 1 contiguous sentence(s) and must "
        "keep every other sentence word for word"]
    panned = {"plan": plan, "parts": copy.deepcopy(parts)}
    panned["parts"][2]["motion"] = "The courier stops, then turns, then waves. The camera slowly pans left."
    _new, applied, rejected = se.apply_patches(ctx, panned, [
        _patch("panel", 3, "motion", "The courier stops, then turns, then waves. The courier rests.")])
    assert [r["reason"] for r in rejected] == [
        "the patch drops the camera direction 'The camera slowly pans left.'"]


def test_dlg22_the_critic_rewrites_one_sentence(ws, tmp_path, monkeypatch):
    good = _patch("panel", 2, "motion", ONE_CHANGED)
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, plan=_speaking_plan("chained", 3, 2),
                            panel=_replies("chained", 3, {2: [{"motion": THREE, "dialogue": LINE}]}),
                            critic=[seu.answer(seu.critic_json((6, 6, 6), "revise", [good]))])
    assert rc == 0
    rounds = os.path.join(ctx.story_dir, "story_rounds")
    with open(os.path.join(rounds, "round_0", "story.md"), encoding="utf-8") as f:
        before = f.read()
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        after = f.read()
    assert after == before.replace("Motion: " + THREE + " ", "Motion: " + ONE_CHANGED + " ")
    assert ("Motion: " + ONE_CHANGED + " The courier faces the camera. The camera stays static.\n"
            + "Dialogue: the courier: " + LINE + "\n") in after
    assert _read_json(os.path.join(rounds, "round_1", "critic.json"))["applied"] == [good]
    state0 = {"plan": _read_json(os.path.join(rounds, "round_0", "plan.json")),
              "parts": [dict((key, value) for key, value in p.items() if key != "index")
                        for p in _read_json(os.path.join(rounds, "round_0", "parts.json"))["panels"]]}
    _new, applied, rejected = se.apply_patches(ctx, state0, [dict(good, replacement=TWO_CHANGED)],
                                               repairable={2: {"T2"}})
    assert applied == [] and [r["reason"] for r in rejected] == [
        "the patch changes 2 sentences; it may change at most 1 contiguous sentence(s) and must "
        "keep every other sentence word for word"]


# --- DLG18, DLG21, DLG25: the D6 classes and the re-check (6.3, 6.4, 6.7) -------------------

NARRATIVE = "A courier carries a sealed letter across a rainy harbour town."
STRIKE = "The courier strikes the old monk with a heavy staff."


def _ids(messages):
    return set(se.parse_violation(m if isinstance(m, str) else m["message"])["id"]
               for m in messages)


def _saved(ws, monkeypatch, mode="chained", n=3, story_id="s1", plan_mut=None, replies=None):
    """A story.md and plan.json saved in <story_dir> as a run would leave them."""
    monkeypatch.setattr(ltx_movie, "WS", ws)
    ctx, plan, _parts, text, _path = _story(ws, mode, n, plan_mut=plan_mut, replies=replies,
                                            ctx_kw={"story_id": story_id})
    with open(os.path.join(ctx.story_dir, "story.md"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(ctx.story_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f)
    return ctx, text


def _edit(ctx, old, new):
    path = os.path.join(ctx.story_dir, "story.md")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert text.count(old) == 1, old
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.replace(old, new))


def _two_people(raw):
    raw["beats"][1]["cast"] = ["c1", "c2"]


def test_dlg18_reclassification(ws, tmp_path, monkeypatch, capsys, story_env):
    def advisory_only(mode, rule, replies):
        hard, advisory = _checks(ws, mode, replies=replies)
        assert hard == [] and _only(advisory, rule), (rule, hard, advisory)

    advisory_only("chained", "N2", {2: {"motion": "The courier waves at the woman beside the "
                                                  "crates and keeps pedalling forward in the rain."}})
    advisory_only("chained", "N3", {2: {"motion": "The courier pulls the grey hood tighter and "
                                                  "pedals forward along the road past the boats."}})
    advisory_only("chained", "N4", {2: {"motion": "The courier pedals past the old monk beside the "
                                                  "crates and on toward the end of the quay."}})
    advisory_only("chained", "N5", {1: {"image": seu.panel_json("chained", 1)["image"][:300] + " "
                                                 + seu.TEMPLE}})
    advisory_only("no_stills", "N7", {2: {"prompt": seu.panel_json("no_stills", 2)["prompt"]
                                                    + " A fisherman shouts across the water."}})
    advisory_only("chained", "N7", {3: {"motion": 'The courier reads the "urgent" note and pedals '
                                                  "on toward the end of the quay."}})
    advisory_only("shots", "N7", {2: {"image": seu.panel_json("shots", 2)["image"]
                                               + " A caption fills the lower edge."}})
    advisory_only("chained", "N8", {2: {"motion": "The courier pedals toward a noise off-screen at "
                                                  "the far end of the long quay."}})
    advisory_only("chained", "N9", {2: {"motion": "The courier pedals hard and we cut to the far "
                                                  "end of the quay at once."}})
    advisory_only("chained", "N10", {1: {"narration": "<one sentence of voice-over narration>"}})
    replies = {2: {"motion": STRIKE}, 3: {"motion": "The courier steps forward then turns."}}
    ctx, plan, parts, text, path = _story(ws, "shots", 3, plan_mut=_two_people, replies=replies)
    parts[2]["narration"] = ""
    text = se.assemble(ctx, plan, parts)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    hard, advisory = se.panel_checks(ctx._replace(panels=4), plan, parts, text, path)
    assert _ids(hard) == {"S1", "S3", "N11"} and {"S5", "S8"} <= _ids(advisory)
    saved, _text = _saved(ws, monkeypatch, "shots", story_id="d18", plan_mut=_two_people,
                          replies=replies)
    _edit(saved, "Narration: " + seu.panel_json("shots", 3)["narration"] + "\n", "")
    assert se.recheck(saved, ltx_movie._validate_story_md)[0] == 2
    checks = _read_json(os.path.join(saved.story_dir, "story_checks.json"))
    assert {"S3", "N11"} <= _ids(checks["hard"]) and not {"S5", "S8"} & _ids(checks["hard"])
    assert {"S5", "S8"} <= _ids(checks["advisory"])
    story_md = os.path.join(saved.story_dir, "story.md")
    report = se.plan_free_report(story_md, "shots", 4, [], ltx_movie._validate_story_md, ws=ws)
    assert _ids(report[0]) == {"S1", "S3", "N11"} and {"S5", "S8"} <= _ids(report[1])
    os.remove(os.path.join(saved.story_dir, "plan.json"))
    capsys.readouterr()
    assert se.recheck(saved._replace(panels=4), ltx_movie._validate_story_md) == (2, [])
    err = capsys.readouterr().err
    assert "  - story: S1 panel count: expected exactly 4 panels, found 3\n" in err
    assert " S3 fields: " in err and " S5 " not in err and " S8 " not in err

    def plan_classes(mutate, mode="chained"):
        ctx = seu.make_ctx(se, ws, mode=mode, panels=3)
        raw = seu.plan_json(mode, 3)
        mutate(raw)
        plan, shape = se.normalize_plan(ctx, raw)
        return se.plan_checks(ctx, plan, shape)

    seu.ronin(story_env["lib"])
    for mutate, rule, mode in (
            (lambda raw: raw["locations"][0].update(setting="A rainy harbour town in modern Japan, "
                                                            "wet cobblestones underfoot, boats "
                                                            "behind, under grey light."), "P4",
             "chained"),
            (lambda raw: raw["beats"][1].update(arc="middle"), "P5", "chained"),
            (lambda raw: raw["beats"][2].update(shot="aerial shot"), "P7", "chained"),
            (lambda raw: raw["beats"][2].update(camera="zoom"), "P8", "chained"),
            (lambda raw: raw["cast"][1].update(phrase="the very old bald monk"), "P3", "chained"),
            (lambda raw: raw["cast"][1].update(descriptor="an old man"), "P3", "chained"),
            (lambda raw: raw["cast"][1].update(phrase="the ronin"), "P13", "chained"),
            (lambda raw: (raw["cast"].append({"id": "c3", "phrase": "the guard",
                                              "descriptor": seu.MONK}),
                          raw["beats"][1].update(cast=["c1", "c2", "c3"])), "P9", "shots")):
        hard, advisory = plan_classes(mutate, mode)
        assert hard == [] and _only(advisory, rule), (rule, hard, advisory)
    for phrase in ("The Courier", "the monk!"):
        hard, advisory = plan_classes(lambda raw: raw["cast"][1].update(phrase=phrase))
        assert _only(hard, "P3") and not _only(advisory, "P3"), phrase
    files = str(tmp_path / "files")
    entries = [seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style"),
               seu.catalog_entry(seu.lora_file(files, "big"), "big-style", kind="style"),
               seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion"),
               seu.catalog_entry(seu.lora_file(files, "rain"), "rain-physics", kind="physics")]
    lctx = seu.make_ctx(se, ws, catalog={"schema_version": 1, "entries": entries})

    def lora(loras, ctx=lctx):
        raw = seu.plan_json("chained", 3)
        raw["loras"] = dict({"global": [], "per_beat": {}, "stills": []}, **loras)
        plan, _shape = se.normalize_plan(ctx, raw)
        compatible = dict((e["id"], e) for e in se.compatible_entries(ctx))
        return se.lora_checks(ctx, plan, compatible, dict((e["id"], e) for e in entries))

    def pick(entry_id, strength=0.8):
        return {"id": entry_id, "strength": strength}

    assert lora({"global": [pick("fast-motion", 2.5)]}) == ([
        "plan: L5 strength: 'fast-motion' strength 2.5 is outside (0, 2], which the renderer "
        "refuses"], [])
    assert lora({"global": [pick("fast-motion", 1.4)]}) == ([], [
        "plan: L5 strength: 'fast-motion' strength 1.4 is outside its range 0.5 to 1.0"])
    for loras, rule, ctx in (
            ({"global": [pick("film-grain"), pick("big-style")]}, "L2", lctx),
            ({"per_beat": {"2": [pick("film-grain")]}}, "L2", lctx),
            ({"global": [pick("fast-motion")], "per_beat": {"2": [pick("rain-physics")]}}, "L3",
             lctx),
            ({"global": [pick("film-grain")], "per_beat": {"2": [pick("fast-motion")]}}, "L4",
             lctx._replace(pinned=[{"path": "/p/%d.safetensors" % i, "strength": 1.0,
                                    "catalog_id": None, "kind": None} for i in (1, 2, 3)]))):
        hard, advisory = lora(loras, ctx)
        assert hard == [] and _only(advisory, rule), (rule, hard, advisory)
    assert lora({"global": [pick("nope")]}) == (["plan: L1 catalog id: 'nope' is not in the "
                                                 "catalog"], [])
    rain = dict((e["id"], e["path"]) for e in entries)["rain-physics"]
    hard, _advisory = lora({"global": [pick("rain-physics")]}, lctx._replace(pinned=[
        {"path": rain, "strength": 1.0, "catalog_id": "rain-physics", "kind": "physics"}]))
    assert _only(hard, "L6")
    assert _only(lora({"stills": [pick("nope"), pick("nope-two")]})[0], "L7")


def test_dlg21_an_advisory_only_round_0_passes_untouched(tmp_path, monkeypatch, capsys):
    ws = seu.make_ws(tmp_path)
    monkeypatch.setattr(ltx_movie, "WS", ws)
    monkeypatch.setattr(ltx_movie, "_check_sudo_and_start_keepalive", lambda: None)
    camera = ("The courier pedals forward along the road as the camera slowly pans left past the "
              "boats.")
    quote = 'The courier reads the "urgent" note and pedals on toward the end of the quay.'
    cases = (("chained", [], {2: [{"motion": camera}], 3: [{"motion": quote}]},
              "panel 3: N7 dialogue and text: Motion: contains a double quote"),
             ("shots", ["--shots"], {2: [{"motion": STRIKE}]},
              "panel 2: S8 contact: Motion: 'strikes' acts on 'the old monk'; two people touching "
              "on screen"))
    for mode, flags, overrides, advisory in cases:
        raw = seu.plan_json(mode, 3)
        if mode == "shots":
            _two_people(raw)
        story_id = "d21-" + mode
        log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(raw)],
                               panel=_replies(mode, 3, overrides))
        rc = ltx_movie.main([NARRATIVE, "--story-id", story_id, "--panels", "3", "--story-only",
                             "--no-review"] + flags)
        out = capsys.readouterr().out
        assert rc == 0, mode
        assert [r["stage"] for r in seu.agent_log(log)] == ["plan", "panel", "panel", "panel"]
        story_dir = os.path.join(ws, "generated", "stories", story_id)
        with open(os.path.join(story_dir, "story.md"), "rb") as f:
            final = f.read()
        with open(os.path.join(story_dir, "story_rounds", "round_0", "story.md"), "rb") as f:
            assert f.read() == final, mode
        checks = _read_json(os.path.join(story_dir, "story_checks.json"))
        assert (checks["stop_reason"], checks["hard"], checks["unresolved"]) == ("passed", [], [])
        assert "Warning: " + advisory + "\n" in out, mode
        assert " N3 " not in out


def test_dlg25_recheck_blocks_only_on_blocking_violations(ws, monkeypatch, capsys, story_env):
    validate = ltx_movie._validate_story_md
    ctx, _text = _saved(ws, monkeypatch, story_id="r1", replies={2: {"motion": BUSY}})
    capsys.readouterr()
    assert se.recheck(ctx, validate)[0] == 0
    assert ("Warning: unresolved: " + T2_MESSAGE + "\n") in capsys.readouterr().out
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert checks["hard"] == [] and _ids(checks["unresolved"]) == {"T2"}
    ctx, _text = _saved(ws, monkeypatch, story_id="r2", plan_mut=_speaking(2),
                        replies={2: {"dialogue": OVER_CAP}})
    assert se.recheck(ctx, validate)[0] == 2
    assert " T1 spoken timing: Dialogue: is 15 words" in capsys.readouterr().err
    ctx, _text = _saved(ws, monkeypatch, story_id="r3", plan_mut=_speaking(2),
                        replies={2: {"dialogue": "Keep moving."}})
    _edit(ctx, "Dialogue: the courier: Keep moving.", "Dialogue: the stranger: Halt.")
    assert se.recheck(ctx, validate)[0] == 2
    assert ("  - panel 2: N18 dialogue: Dialogue: names 'the stranger', which is no character's "
            "referring phrase; use one of: 'the courier', 'the old monk'\n") in (
        capsys.readouterr().err)
    seu.ronin(story_env["lib"])
    ctx, _text = _saved(ws, monkeypatch, story_id="r4")
    os.remove(os.path.join(ctx.story_dir, "plan.json"))
    _edit(ctx, "Narration: The rain had not stopped since dawn.\n",
          "Narration: The ronin watched the rain.\n")
    assert se.recheck(ctx, validate) == (0, [])
    out, err = capsys.readouterr()
    assert err == ""
    assert "Warning: panel 1: N15 undeclared character: Narration: names library character ronin" in out
    ctx, _text = _saved(ws, monkeypatch, "shots", story_id="r5", plan_mut=_two_people,
                        replies={2: {"motion": STRIKE}})
    os.remove(os.path.join(ctx.story_dir, "plan.json"))
    rc, advisories = se.recheck(ctx, validate)
    assert rc == 0 and ("panel 2: S8 contact: Motion: 'strikes' acts on 'the old monk'; two "
                        "people touching on screen") in advisories
    assert se.recheck(ctx._replace(panels=4), validate) == (2, [])
    assert "  - story: S1 panel count: expected exactly 4 panels, found 3\n" in (
        capsys.readouterr().err)


# --- DLG19: the critic prompt (8.3) -----------------------------------------------------------

N12_MESSAGE = "panel 1: N12 one action: Motion: chains actions with 'then'"
MOTION_LINE = ('- target "panel", field "%s", index = the panel number, only for a panel with a '
               "[hard] T2 or T3 problem: replacement is the panel's whole new %s: writer text, "
               "identical to the current text except for the sentence or sentences that hold the "
               "extra or missing action.")
DIALOGUE_FIELD_LINE = ('- target "panel", field "dialogue", index = the panel number, only for a '
                       "panel with a [hard] T1 problem: replacement is the shortened spoken line, "
                       "without the speaker's phrase and without quotation marks, within the "
                       "limit the T1 problem states.")


def test_dlg19_critic_prompt(ws):
    header = ("\nProblems the pipeline's own checks found in this draft. Only the [hard] ones are "
              "fixed by patches; the [advisory] ones are reported to the user and must never be "
              "patched:\n- [hard] " + T2_MESSAGE + "\n- [advisory] " + N12_MESSAGE + "\n")
    render = ("- renderability: every panel shows physical action that a video model can render "
              "in 6 seconds -- neither more actions than fit nor none -- every spoken line fits "
              "its clip, and there is no on-screen text and nothing outside the frame. Camera "
              "directions and dialogue are part of a good panel, never a fault.\n")
    patches = ("Then propose at most 8 patches, most important first, only for the [hard] "
               "problems: a spoken line that does not fit its clip, or a panel with more or fewer "
               "actions than its clip can hold. Each patch is an object with exactly the keys "
               "target, index, field, reason and replacement. The allowed patches are:\n")
    preserve = ("\nPreserve every camera direction, every descriptive sentence and every dialogue "
                "line word for word: change only the sentence or sentences that cause the "
                "problem, and copy every other sentence of the field unchanged. A patch that "
                "changes anything else is rejected. A panel replacement holds only the text the "
                "writer writes: never include a character's description, a setting sentence or "
                "the shot type, because the pipeline adds those itself. The number of panels, the "
                "characters' referring phrases and their descriptions never change.\n")
    for mode in ("chained", "no_stills", "shots"):
        _ctx, plan, _parts, text, _p = _story(ws, mode, 3)
        prompt = se.build_critic_prompt(plan, text, ([T2_MESSAGE], [N12_MESSAGE]))
        for piece in (header, render, patches, preserve):
            assert piece in prompt, (mode, piece[:50])
        field, label = ("prompt", "Prompt") if mode == "no_stills" else ("motion", "Motion")
        lines = [MOTION_LINE % (field, label), DIALOGUE_FIELD_LINE]
        assert se.critic_field_lines(mode, None).split("\n") == lines, mode
        assert se.critic_field_lines(mode, None, False).split("\n") == lines[:1], mode
        assert ("are:\n" + "\n".join(lines) + "\nPreserve") in prompt, mode
        for absent in ("(only 1:", 'field "beat.action"', 'field "image"', 'field "narration"',
                       "@@"):
            assert absent not in prompt, (mode, absent)
    assert se.critic_field_lines("chained", ["- fast-motion: x"]).split("\n")[0].startswith(
        '- target "plan", field "lora", index 0 for the global picks')
    assert not hasattr(se, "ONLY1")


# --- DLG30: bin/judge-story (CM5, G5) --------------------------------------------------------

def test_dlg30_judge_story_goal_and_patch_fields():
    judge_story = _judge("judge_story_for_dialogue", "bin/judge-story")
    assert judge_story.DEFAULT_GOAL == ("the most realistic action scenes possible, with any "
                                        "spoken lines delivered on camera by the character who "
                                        "says them")
    assert judge_story.PATCH_FIELDS == ("beat.action", "beat.shot", "beat.camera",
                                        "location.setting", "lora", "motion", "image", "prompt",
                                        "narration", "dialogue")
    assert '"dialogue"' in json.dumps(judge_story.SUBMIT_REVIEW_SCHEMA)


def test_judge_story_reports_unresolved_as_advisory(tmp_path):
    # Controller ruling Q2 (Spec amendment 2): unresolved T2/T3 reach the judge as [advisory].
    judge_story = _judge("judge_story_for_dialogue", "bin/judge-story")
    checks = {"hard": [{"message": "panel 2: T1 spoken timing: x"}],
              "unresolved": [{"message": T2_MESSAGE}],
              "advisory": [{"message": N12_MESSAGE}]}
    (tmp_path / "story_checks.json").write_text(json.dumps(checks), encoding="utf-8")
    assert judge_story._story_checks_messages(str(tmp_path)) == (
        ["panel 2: T1 spoken timing: x"], [T2_MESSAGE, N12_MESSAGE])
    del checks["unresolved"]
    (tmp_path / "story_checks.json").write_text(json.dumps(checks), encoding="utf-8")
    assert judge_story._story_checks_messages(str(tmp_path)) == (
        ["panel 2: T1 spoken timing: x"], [N12_MESSAGE])


# --- DLG29: bin/judge-clips (CM5, G6) --------------------------------------------------------

def test_dlg29_judge_clips_panel_text():
    judge_clips = _judge("judge_clips_for_dialogue", "bin/judge-clips")
    base = {"index": 2, "title": "Gate", "motion_prompt": "The courier waits.", "image_path": None}
    head = "## Panel 2 — Gate\nMotion: The courier waits.\n"
    assert judge_clips.format_panel_text(2, dict(
        base, speaker="the courier", speech="Keep moving.", speech_source="dialogue",
        narration="The bell had not rung.")) == (
        head + "Dialogue: the courier: Keep moving.\nNarration: The bell had not rung.")
    alias = dict(base, speaker="the courier", speech="Keep moving.", speech_source="narration",
                 narration="the courier: Keep moving.")
    assert judge_clips.format_panel_text(2, alias) == head + "Dialogue: the courier: Keep moving."
    older = dict(alias)
    del older["speech_source"]
    assert judge_clips.format_panel_text(2, older) == head + "Dialogue: the courier: Keep moving."
    assert judge_clips.format_panel_text(2, dict(base, narration="Rain fell.")) == (
        head + "Narration: Rain fell.")
    assert ("A Dialogue: text is a line the named character speaks on camera in that panel's clip; "
            "Narration: text is voice-over.") in judge_clips.SYSTEM_PROMPT
    assert "starts with a character's referring phrase and a colon" not in judge_clips.SYSTEM_PROMPT


# --- DLG27: bin/ltx-movie --speech-delivery (DG8) --------------------------------------------

def test_dlg27_speech_delivery_reaches_the_manifest(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ltx_movie, "WS", seu.make_ws(tmp_path))
    assert ltx_movie.build_parser().parse_args(["n", "--story-id", "x"]).speech_delivery == "beats"
    calls = []
    monkeypatch.setattr(ltx_movie.subprocess, "run",
                        lambda cmd, **kw: calls.append(list(cmd)) or _Done())
    for delivery in ("beats", "plain", "beats-no-acoustic"):
        calls[:] = []
        argv = ["n", "--story-id", "sd1", "--panels", "3", "--no-review"]
        if delivery != "beats":
            argv += ["--speech-delivery", delivery]
        assert ltx_movie.phase3_manifest(_movie_args(*argv)) == 0
        manifest = calls[0]
        assert "ltx-story-manifest" in manifest[1]
        assert ("--speech-delivery" in manifest) == (delivery != "beats"), delivery
        if delivery != "beats":
            assert manifest[manifest.index("--speech-delivery") + 1] == delivery
    for flags, expected in (([], None), (["--speech-delivery", "plain"], "plain"),
                            (["--story-legacy", "--speech-delivery", "beats-no-acoustic"],
                             "beats-no-acoustic")):
        capsys.readouterr()
        assert ltx_movie.main(["n", "--story-id", "sd2", "--panels", "3", "--dry-run",
                               "--no-review"] + flags) == 0, flags
        line = [l for l in capsys.readouterr().out.splitlines()
                if l.startswith("Command: ") and "ltx-story-manifest" in l][0]
        if expected is None:
            assert "--speech-delivery" not in line
        else:
            assert line.endswith(" --force --speech-delivery " + expected), line


# --- 6.8, 6.9, CM6: bin/ltx-movie text ---------------------------------------------------------

def test_ltx_movie_dialogue_help_and_docstring_text():
    actions = ltx_movie.build_parser()._option_string_actions
    assert actions["--judge"].help == (
        "after the local critic rounds, run bin/judge-story --patches (Claude; needs "
        "ANTHROPIC_API_KEY) as a final report: its scores go into story_checks.json and its "
        "patches are saved, never applied")
    assert actions["--story-legacy"].help.endswith(
        " It does not ask for Dialogue: lines; a prefixed Narration: line still renders as "
        "dialogue.")
    doc = " ".join(ltx_movie.__doc__.split())
    assert ("up to two local critic rounds that repair only spoken timing and the amount of action"
            in doc)
    assert "when blocking violations remain" in doc and "up to three local critic rounds" not in doc
