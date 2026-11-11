"""Tests for audio only quoted (docs/superpowers/specs/2026-11-11-audio-only-quoted-design.md, AQ1-AQ4: AOQ1-AOQ6): a chained or shots speech movie's audio sentence says only the quoted words are spoken, or that nobody speaks.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_audio_only_quoted.py

No test renders, reads the real HOME, or contacts a model server, a daemon or the Anthropic API. Stdlib and pytest."""
import importlib.machinery
import os
import re
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402
import test_dialogue as dlg  # noqa: E402

lib = importlib.machinery.SourceFileLoader("character_lib_for_aoq", os.path.join(WS, "character_lib.py")).load_module()

ACOUSTIC = ("The audio is clear close-mic dialogue with a subtle natural room tone; "
            "only the quoted words are spoken, and only once; "
            "the dialogue takes priority over the quiet ambience, and there is no music.")
AMBIENCE = ("The audio is the natural ambient sound of the place; "
            "nobody speaks, and there is no music.")
SPEAK = "The courier lifts the letter. The camera pushes in."
WALK = "The courier walks down the road. The camera tracks alongside the movement."


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


def test_aoq1_the_sentences():
    assert lib.ACOUSTIC_SENTENCE == ACOUSTIC
    assert lib.AMBIENCE_SENTENCE == AMBIENCE
    assert "only the quoted words are spoken, and only once" in ACOUSTIC
    assert "the dialogue takes priority over the quiet ambience" in ACOUSTIC
    assert "nobody speaks" in AMBIENCE
    for s in (ACOUSTIC, AMBIENCE):
        assert "no music" in s
        assert not set('{}"') & set(s)
        assert lib._SENTENCE_SPLIT_RE.split(s) == [s]
        assert s.endswith(".")


def test_aoq2_a_speaking_panel_ends_with_the_new_sentence():
    p = lib.panel_prompt(SPEAK, "The shot is a close-up.", "the courier", "Go now.", "beats", ["the courier"])
    assert p == ('The shot is a close-up. The courier lifts the letter. The courier says, "Go now." '
                 'The camera pushes in. ' + ACOUSTIC)
    assert p.count("The audio is") == 1
    assert re.findall(r'"[^"]*"', p) == ['"Go now."']
    assert lib.speech_text("the courier", "Go now.", "beats") == 'The courier says, "Go now." ' + ACOUSTIC


def test_aoq3_a_silent_panel_ends_with_nobody_speaks():
    p = lib.panel_prompt(WALK, "The shot is a wide shot.", None, "", "beats", ["the courier"])
    assert p == "The shot is a wide shot. " + WALK + " " + AMBIENCE
    assert p.endswith("nobody speaks, and there is no music.")
    assert '"' not in p


def test_aoq4_plain_and_no_acoustic_add_no_audio_sentence():
    assert lib.panel_prompt(SPEAK, "", "the courier", "Go now.", "plain", ["the courier"]) == (
        'The courier lifts the letter. The courier says: "Go now." The camera pushes in.')
    assert lib.panel_prompt(SPEAK, "", "the courier", "Go now.", "beats-no-acoustic", ["the courier"]) == (
        'The courier lifts the letter. The courier says, "Go now." The camera pushes in.')
    for d in ("plain", "beats-no-acoustic"):
        assert lib.panel_prompt(WALK, "", None, "", d, ["the courier"]) == WALK
    assert lib.speech_text("the courier", "Go now.", "beats-no-acoustic") == 'The courier says, "Go now."'


def test_aoq5_the_shots_manifest_uses_both_sentences(tmp_path, monkeypatch):
    story_md, images, ws = dlg._manifest_ws(tmp_path, monkeypatch, "aoq5", dlg.SHOTS_DG9, images=3)
    assert dlg.story_manifest.main(dlg._manifest_argv("aoq5", story_md, images, mode="shots", panels=3)) == 0
    prompts = [p["motion_prompt"] for p in dlg._read_manifest(ws, "aoq5")["panels"]]
    assert prompts[2].endswith(" " + ACOUSTIC)
    assert prompts[0].endswith(" " + AMBIENCE)
    assert prompts[1].endswith(" " + AMBIENCE)


def test_aoq6_the_no_stills_manifest_speaking_panel(tmp_path, monkeypatch):
    story_md, images, ws = dlg._manifest_ws(tmp_path, monkeypatch, "aoq6", dlg.NO_STILLS_DG9,
                                            plan=dlg.CAST_PLAN, images=0)
    assert dlg.story_manifest.main(dlg._manifest_argv("aoq6", story_md, images, mode="no_images", panels=4)) == 0
    prompts = [p["motion_prompt"] for p in dlg._read_manifest(ws, "aoq6")["panels"]]
    assert prompts[3].endswith(" " + ACOUSTIC)
    assert prompts[3].count("The audio is") == 1
    for k in (0, 1, 2):
        assert "The audio is" not in prompts[k]
