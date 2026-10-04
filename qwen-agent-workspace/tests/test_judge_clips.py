"""Tests for bin/judge-clips.

Spec: docs/superpowers/specs/2026-10-04-judge-clips-design.md (Section 7).
Run from the workspace root: python3 -m pytest tests/test_judge_clips.py -v

Plain pytest asserts only -- no check() helper, which reports false greens under
pytest. No test makes a network call: the autouse fixture below makes constructing
the real anthropic.Anthropic client fail the test, and every test that reaches the
API installs a recording fake first. Real ffmpeg and ffprobe run on small synthetic
clips (no skips: a missing ffmpeg, ffprobe, or libx264 errors the tests loudly).
Story fixtures live under tmp_path with judge_clips.WS patched to it; nothing is
written to the real generated/ tree. Exactly one test function per spec test ID
(55 total); multi-case IDs loop inside their function.
"""

import base64
import copy
import fractions
import importlib.machinery
import json
import os
import re
import shutil
import subprocess
import tempfile
import types
import uuid

import anthropic
import httpx
import jsonschema
import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
_SCRIPT_PATH = os.path.join(WS, "bin", "judge-clips")
judge_clips = importlib.machinery.SourceFileLoader("judge_clips", _SCRIPT_PATH).load_module()

SENTINEL_KEY = "sk-test-SENTINEL-do-not-leak"
STORY_ID = "clips-test"

# Deliberately in reverse panel order, with distinct values per score, and a non-ASCII
# dash (checks ensure_ascii=False in the written JSON) (spec 7.1).
VALID_INPUT = {
    "clips": [
        {"panel": 2, "motion_fidelity": 4, "physical_realism": 3, "temporal_stability": 5},
        {"panel": 1, "motion_fidelity": 7, "physical_realism": 6, "temporal_stability": 8}],
    "movie": {"seam_continuity": 9, "narrative_clarity": 2},
    "critique": "Panel 1 holds the dawn light; Panel 2's horse melts by frame 3 — fix it.",
}
ONE_CLIP_INPUT = {
    "clips": [{"panel": 1, "motion_fidelity": 7, "physical_realism": 6, "temporal_stability": 8}],
    "movie": {"narrative_clarity": 2},
    "critique": VALID_INPUT["critique"],
}


@pytest.fixture(autouse=True)
def _no_real_client(monkeypatch):
    """SC8 guard for every test: constructing the real client fails the test, and the
    key starts unset. Tests that reach the API install a recording fake over this."""
    def _forbidden(*args, **kwargs):
        raise AssertionError("test constructed a real anthropic.Anthropic client")
    monkeypatch.setattr(judge_clips.anthropic, "Anthropic", _forbidden)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


# --- T11-T13: submit_judgment validation (spec 4.3, 4.4) -----------------------------

def test_t11a_missing_top_level_key_rejected():
    for key in ("clips", "movie", "critique"):
        payload = copy.deepcopy(VALID_INPUT)
        del payload[key]
        with pytest.raises(jsonschema.ValidationError):
            judge_clips.validate_judgment_input(payload, [1, 2])


def test_t11b_missing_clip_entry_key_rejected():
    for key in ("panel", "motion_fidelity", "physical_realism", "temporal_stability"):
        payload = copy.deepcopy(VALID_INPUT)
        del payload["clips"][1][key]           # clips[1] is the panel-1 entry
        with pytest.raises(jsonschema.ValidationError):
            judge_clips.validate_judgment_input(payload, [1, 2])


def test_t11c_out_of_range_or_non_integer_score_rejected():
    # 0 and 11 are the range cases; "7", 7.5 and True pin "non-integer score"
    # (jsonschema does not count booleans as integers).
    for bad in (0, 11, "7", 7.5, True):
        for key in ("motion_fidelity", "physical_realism", "temporal_stability"):
            payload = copy.deepcopy(VALID_INPUT)
            payload["clips"][1][key] = bad
            with pytest.raises(jsonschema.ValidationError):
                judge_clips.validate_judgment_input(payload, [1, 2])
        for key in ("seam_continuity", "narrative_clarity"):
            payload = copy.deepcopy(VALID_INPUT)
            payload["movie"][key] = bad
            with pytest.raises(jsonschema.ValidationError):
                judge_clips.validate_judgment_input(payload, [1, 2])


def test_t11d_non_integer_panel_rejected():
    for bad in ("1", True, 1.5, None):
        payload = copy.deepcopy(VALID_INPUT)
        payload["clips"][1]["panel"] = bad
        with pytest.raises(jsonschema.ValidationError):
            judge_clips.validate_judgment_input(payload, [1, 2])


def test_t11e_valid_payloads_accepted():
    for value in (1, 10):
        payload = copy.deepcopy(VALID_INPUT)
        for entry in payload["clips"]:
            for key in ("motion_fidelity", "physical_realism", "temporal_stability"):
                entry[key] = value
        payload["movie"] = {"seam_continuity": value, "narrative_clarity": value}
        assert judge_clips.validate_judgment_input(payload, [1, 2]) is None
    # No additionalProperties constraint: extra keys are tolerated (spec 4.3).
    payload = copy.deepcopy(VALID_INPUT)
    payload["extra"] = "ignored"
    payload["clips"][0]["extra_score"] = 99
    payload["movie"]["extra_movie_score"] = 99
    assert judge_clips.validate_judgment_input(payload, [1, 2]) is None
    # jsonschema accepts 7.0 as an integer; 1.0/2.0 equal 1/2 in the panel-set checks.
    payload = copy.deepcopy(VALID_INPUT)
    payload["clips"][0]["panel"] = 2.0
    payload["clips"][1]["panel"] = 1.0
    for entry in payload["clips"]:
        for key in ("motion_fidelity", "physical_realism", "temporal_stability"):
            entry[key] = 7.0
    payload["movie"] = {"seam_continuity": 7.0, "narrative_clarity": 7.0}
    assert judge_clips.validate_judgment_input(payload, [1, 2]) is None


def test_t11f_missing_narrative_clarity_rejected():
    payload = copy.deepcopy(VALID_INPUT)
    del payload["movie"]["narrative_clarity"]
    with pytest.raises(jsonschema.ValidationError):
        judge_clips.validate_judgment_input(payload, [1, 2])
    payload = copy.deepcopy(ONE_CLIP_INPUT)
    del payload["movie"]["narrative_clarity"]
    with pytest.raises(jsonschema.ValidationError):
        judge_clips.validate_judgment_input(payload, [1])


def test_t12_panel_set_rules():
    panel_1 = VALID_INPUT["clips"][1]
    panel_3 = dict(panel_1, panel=3)
    cases = [
        # (a) two entries for panel 1, none for 2: the duplicate check precedes the
        # missing check.
        ([panel_1, panel_1], "clips lists these panels more than once: 1"),
        ([panel_1], "clips is missing these judged panels: 2"),                    # (b)
        ([panel_1, VALID_INPUT["clips"][0], panel_3],
         "clips includes panels that were not judged: 3"),                        # (c)
        ([panel_1, panel_1, panel_3], "clips lists these panels more than once: 1"),  # (d)
    ]
    for clips, message in cases:
        payload = copy.deepcopy(VALID_INPUT)
        payload["clips"] = copy.deepcopy(clips)
        with pytest.raises(jsonschema.ValidationError) as exc:
            judge_clips.validate_judgment_input(payload, [1, 2])
        assert exc.value.message == message


def test_t13_seam_two_way_rule():
    payload = copy.deepcopy(VALID_INPUT)
    del payload["movie"]["seam_continuity"]
    with pytest.raises(jsonschema.ValidationError) as exc:
        judge_clips.validate_judgment_input(payload, [1, 2])
    assert exc.value.message == "seam_continuity is required when judging 2 or more clips"
    payload = copy.deepcopy(ONE_CLIP_INPUT)
    payload["movie"]["seam_continuity"] = 5
    with pytest.raises(jsonschema.ValidationError) as exc:
        judge_clips.validate_judgment_input(payload, [1])
    assert exc.value.message == "seam_continuity must be omitted when judging fewer than 2 clips"
    assert judge_clips.validate_judgment_input(copy.deepcopy(ONE_CLIP_INPUT), [1]) is None
    assert judge_clips.validate_judgment_input(copy.deepcopy(VALID_INPUT), [1, 2]) is None


# --- shared manifest panel fixtures (spec 7.1) -----------------------------------------

PANEL_1 = {"index": 1, "image_path": "/abs/story/images/panel_01.png", "title": "The Beach at Dawn",
           "panel_text": "A wide shot of a woman in a yellow sundress at the water's edge — dawn.",
           "narration": "She came to the shore for solitude.", "num_frames": 25,
           "motion_prompt": "She takes a slow step into the surf.", "conditioning": "still"}
PANEL_2 = {"index": 2, "image_path": None, "title": "The Horse Appears",
           "panel_text": "A chestnut horse trots out of the mist.",
           "narration": "A wild horse appeared.", "num_frames": 3,
           "motion_prompt": "A chestnut horse trots out of the mist.", "conditioning": "chain"}

def _manifest(panels):
    # fps 30 deliberately differs from the clips' real 24 fps, so a label computed from
    # the manifest fps instead of ffprobe's avg_frame_rate is caught (T17).
    return {"schema_version": 3, "story_id": STORY_ID, "fps": 30, "panels": panels}


# --- T3, T5: clip discovery and manifest loading (spec 3.1-3.3) -----------------------

def test_t3_find_clips_numeric_sort_and_filter(tmp_path):
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    for name in ("panel_03.mp4", "panel_01.mp4", "panel_100.mp4", "panel_99.mp4",
                 "panel_02.mp4", "panel_1.mp4", "panel_01.mp4.provenance.json",
                 "panel_02.chainseed.png", "panel_01.mov", "Panel_04.mp4", "panel_05.mp4.bak"):
        (clips_dir / name).write_bytes(b"x")
    d = str(clips_dir)
    assert judge_clips.find_clips(d) == [
        (1, os.path.join(d, "panel_01.mp4")),
        (2, os.path.join(d, "panel_02.mp4")),
        (3, os.path.join(d, "panel_03.mp4")),
        (99, os.path.join(d, "panel_99.mp4")),
        (100, os.path.join(d, "panel_100.mp4")),
    ]


def test_t5_load_manifest_pairs_by_index(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema_version": 3, "panels": [PANEL_2, PANEL_1]}),
                    encoding="utf-8")
    assert judge_clips.load_manifest_panels(str(path)) == {1: PANEL_1, 2: PANEL_2}
