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


# --- synthetic clips and the frame-number oracle (spec 7.1) ---------------------------

GARBAGE_CLIP = b"not a real clip"


def _make_clip(path, frames):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y",
                    "-f", "lavfi", "-i",
                    "color=c=black:s=64x48:r=24,format=yuv420p,geq=lum='16+N*8':cb=128:cr=128",
                    "-f", "lavfi", "-t", "2", "-i", "anullsrc=r=48000:cl=mono",
                    "-map", "0:v", "-map", "1:a", "-frames:v", str(frames),
                    "-c:v", "libx264", "-preset", "ultrafast", "-qp", "0", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(path)], check=True)


def _frame_number(jpeg_bytes, tmp_path):
    path = tmp_path / ("oracle_%s.jpg" % uuid.uuid4().hex)
    path.write_bytes(jpeg_bytes)
    out = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
                          "-vf", "scale=1:1:flags=area", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    return round(out[0] * 219 / 255 / 8)


@pytest.fixture(scope="session")
def synthetic_clips(tmp_path_factory):
    """{25: path, 3: path, 1: path}: real h264+aac clips whose frame N has uniform luma
    16 + 8N, generated once per session (spec 7.1)."""
    directory = tmp_path_factory.mktemp("synthetic")
    paths = {}
    for frames in (25, 3, 1):
        path = directory / ("clip%d.mp4" % frames)
        _make_clip(path, frames)
        paths[frames] = str(path)
    return paths


def _fake_run(monkeypatch, returncode, stdout="", stderr=""):
    """Replace judge_clips.subprocess.run with a recorder that returns one canned
    CompletedProcess. Returns the list of (argv, kwargs) calls."""
    calls = []

    def _run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)
    monkeypatch.setattr(judge_clips.subprocess, "run", _run)
    return calls


CAPTURE_KWARGS = {"capture_output": True, "encoding": "utf-8", "errors": "replace"}


# --- T4, T9, T10: frame indices, probing, extraction (spec 3.4-3.6) -------------------

def test_t4a_frame_indices_table():
    table = {241: [0, 80, 160, 240], 145: [0, 48, 96, 144], 25: [0, 8, 16, 24],
             9: [0, 3, 5, 8], 5: [0, 1, 3, 4], 4: [0, 1, 2, 3], 3: [0, 1, 1, 2],
             2: [0, 0, 1, 1], 1: [0, 0, 0, 0]}
    for n, expected in table.items():
        assert judge_clips.frame_indices(n) == expected, n


def test_t4b_frame_indices_properties():
    for n in range(1, 2001):
        idx = judge_clips.frame_indices(n)
        assert len(idx) == 4, n
        assert idx[0] == 0, n
        assert idx[3] == n - 1, n
        assert idx == sorted(idx), n
        for k in range(4):
            assert abs(idx[k] - k * (n - 1) / 3) <= 0.5, (n, k)


def test_t9a_probe_synthetic_clips(synthetic_clips):
    for frames in (25, 3, 1):
        assert judge_clips.probe_clip(synthetic_clips[frames]) == (frames, fractions.Fraction(24))


def test_t9b_probe_real_failures(tmp_path):
    garbage = tmp_path / "garbage.mp4"
    garbage.write_bytes(GARBAGE_CLIP)
    with pytest.raises(judge_clips.ClipError) as exc:
        judge_clips.probe_clip(str(garbage))
    assert str(exc.value).startswith("ffprobe failed on %s (exit 1): " % garbage)

    audio_only = tmp_path / "audio_only.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-t", "1",
                    "-i", "anullsrc=r=48000:cl=mono", "-c:a", "aac", str(audio_only)], check=True)
    zero_frames = tmp_path / "zero_frames.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "color=c=black:s=64x48:r=24", "-frames:v", "0", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(zero_frames)], check=True)
    for path in (audio_only, zero_frames):
        with pytest.raises(judge_clips.ClipError) as exc:
            judge_clips.probe_clip(str(path))
        assert str(exc.value) == "%s has no video stream" % path


def test_t9c_probe_canned_output(monkeypatch):
    clip = "/x/panel_01.mp4"
    calls = _fake_run(monkeypatch, 0,
                      stdout='{"streams": [{"avg_frame_rate": "24/1", "nb_read_frames": "145"}]}')
    assert judge_clips.probe_clip(clip) == (145, fractions.Fraction(24))
    assert calls == [(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                       "-show_entries", "stream=nb_read_frames,avg_frame_rate", "-of", "json",
                       "/x/panel_01.mp4"], CAPTURE_KWARGS)]
    cases = [
        (0, '{"streams": [{"avg_frame_rate": "24/1", "nb_read_frames": "0"}]}', "",
         "/x/panel_01.mp4 has no decodable video frames"),                          # (b)
        (0, '{"streams": [{"avg_frame_rate": "24/1"}]}', "",
         "/x/panel_01.mp4 has no decodable video frames"),                          # (c)
        (0, '{"streams": [{"avg_frame_rate": "0/0", "nb_read_frames": "145"}]}', "",
         "/x/panel_01.mp4 has no usable frame rate (avg_frame_rate='0/0')"),        # (d)
        (0, "not json", "", "ffprobe returned unreadable output for /x/panel_01.mp4"),  # (e)
        (1, "", "line one\nlast line\n\n",
         "ffprobe failed on /x/panel_01.mp4 (exit 1): last line"),                  # (f)
        (1, "", "", "ffprobe failed on /x/panel_01.mp4 (exit 1): (no error output)"),  # (g)
    ]
    for returncode, stdout, stderr, message in cases:
        _fake_run(monkeypatch, returncode, stdout=stdout, stderr=stderr)
        with pytest.raises(judge_clips.ClipError) as exc:
            judge_clips.probe_clip(clip)
        assert str(exc.value) == message


def test_t10a_extract_four_distinct_frames(tmp_path, synthetic_clips):
    out = tmp_path / "out"
    out.mkdir()
    images = judge_clips.extract_frames(synthetic_clips[25], [0, 8, 16, 24], str(out))
    assert len(images) == 4
    assert all(image.startswith(b"\xff\xd8") for image in images)
    assert [_frame_number(image, tmp_path) for image in images] == [0, 8, 16, 24]
    size = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
                           "-of", "csv=p=0", str(out / "frame_1.jpg")],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert size == "64,48"
    assert sorted(os.listdir(out)) == ["frame_1.jpg", "frame_2.jpg", "frame_3.jpg", "frame_4.jpg"]


def test_t10b_extract_repeated_indices(tmp_path, synthetic_clips):
    out = tmp_path / "out"
    out.mkdir()
    images = judge_clips.extract_frames(synthetic_clips[3], [0, 1, 1, 2], str(out))
    assert len(images) == 4
    assert images[1] == images[2]
    assert [_frame_number(image, tmp_path) for image in images] == [0, 1, 1, 2]
    assert len(os.listdir(out)) == 3

    out2 = tmp_path / "out2"
    out2.mkdir()
    images = judge_clips.extract_frames(synthetic_clips[1], [0, 0, 0, 0], str(out2))
    assert len(images) == 4
    assert images[0] == images[1] == images[2] == images[3]
    assert [_frame_number(image, tmp_path) for image in images] == [0, 0, 0, 0]
    assert len(os.listdir(out2)) == 1


def test_t10c_extract_canned_output(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    calls = _fake_run(monkeypatch, 0)
    with pytest.raises(judge_clips.ClipError) as exc:
        judge_clips.extract_frames("/x/panel_02.mp4", [0, 1, 1, 2], str(out))
    assert calls == [(["ffmpeg", "-nostdin", "-v", "error", "-i", "/x/panel_02.mp4",
                       "-map", "0:v:0", "-vf", "select=eq(n\\,0)+eq(n\\,1)+eq(n\\,2)",
                       "-fps_mode", "passthrough", "-q:v", "2", "-f", "image2",
                       os.path.join(str(out), "frame_%d.jpg")], CAPTURE_KWARGS)]
    assert str(exc.value) == "ffmpeg wrote 0 frames from /x/panel_02.mp4; expected 3"

    _fake_run(monkeypatch, 1, stderr="bad\nworse\n")
    with pytest.raises(judge_clips.ClipError) as exc:
        judge_clips.extract_frames("/x/panel_02.mp4", [0, 1, 1, 2], str(out))
    assert str(exc.value) == "ffmpeg failed on /x/panel_02.mp4 (exit 1): worse"


def test_t10d_extract_real_failures(tmp_path, synthetic_clips):
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(judge_clips.ClipError) as exc:
        judge_clips.extract_frames(synthetic_clips[3], [0, 1, 2, 5], str(out))
    assert str(exc.value) == "ffmpeg wrote 3 frames from %s; expected 4" % synthetic_clips[3]

    garbage = tmp_path / "garbage.mp4"
    garbage.write_bytes(GARBAGE_CLIP)
    out3 = tmp_path / "out3"
    out3.mkdir()
    with pytest.raises(judge_clips.ClipError) as exc:
        judge_clips.extract_frames(str(garbage), [0], str(out3))
    assert str(exc.value).startswith("ffmpeg failed on %s (exit " % garbage)


# --- T6-T8: panel text, frame labels, user content, system prompt (spec 3.7-3.9, 4.5) -

def _clip_input(panel, text, prefix):
    """A build_user_content input entry: frames at t = 0.0, 0.5, 1.0, 1.5 whose data are
    "<prefix>0" .. "<prefix>3" (spec 7.2 T8a)."""
    return {"panel": panel, "text": text,
            "frames": [{"t": t, "data": "%s%d" % (prefix, k)}
                       for k, t in enumerate((0.0, 0.5, 1.0, 1.5))]}


def test_t6_format_panel_text():
    expected_a = ("## Panel 1 — The Beach at Dawn\n"
                  "Opening still: A wide shot of a woman in a yellow sundress at the water's "
                  "edge — dawn.\n"
                  "Motion: She takes a slow step into the surf.\n"
                  "Narration: She came to the shore for solitude.")
    expected_b = ("## Panel 2 — The Horse Appears\n"
                  "Motion: A chestnut horse trots out of the mist.\n"
                  "Narration: A wild horse appeared.")
    without_opening = ("## Panel 1 — The Beach at Dawn\n"
                       "Motion: She takes a slow step into the surf.\n"
                       "Narration: She came to the shore for solitude.")
    assert judge_clips.format_panel_text(1, PANEL_1) == expected_a                     # (a)
    assert judge_clips.format_panel_text(2, PANEL_2) == expected_b                     # (b)
    assert judge_clips.format_panel_text(1, dict(PANEL_1, image_path=None)) == without_opening  # (c)
    assert judge_clips.format_panel_text(1, dict(PANEL_1, panel_text="   ")) == without_opening  # (d)
    assert judge_clips.format_panel_text(
        3, {"index": 3, "title": "", "motion_prompt": None}) == "## Panel 3 —"           # (e)
    assert judge_clips.format_panel_text(
        4, {"index": 4, "title": "  Padded  ", "motion_prompt": "  Runs.  ",
            "narration": 7}) == "## Panel 4 — Padded\nMotion: Runs."                    # (f)
    # (g) a still path on a panel other than 1 never adds an Opening still: line
    assert judge_clips.format_panel_text(
        2, dict(PANEL_2, image_path="/abs/story/images/panel_02.png")) == expected_b


def test_t7_format_frame_label():
    assert judge_clips.format_frame_label(3, 2, 2.0) == "Panel 3, frame 2 of 4 (t=2.00s)"
    assert judge_clips.format_frame_label(1, 4, 6.0) == "Panel 1, frame 4 of 4 (t=6.00s)"
    assert judge_clips.format_frame_label(2, 1, 1 / 3) == "Panel 2, frame 1 of 4 (t=0.33s)"


def test_t8a_build_user_content_two_clips():
    content = judge_clips.build_user_content([_clip_input(1, "T1", "A"), _clip_input(2, "T2", "B")])
    expected = []
    for panel, text, prefix in ((1, "T1", "A"), (2, "T2", "B")):
        expected.append({"type": "text", "text": text})
        for k, t in enumerate((0.0, 0.5, 1.0, 1.5)):
            expected.append({"type": "text",
                             "text": judge_clips.format_frame_label(panel, k + 1, t)})
            expected.append({"type": "image",
                             "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": "%s%d" % (prefix, k)}})
    expected.append({"type": "text", "text": judge_clips.FINAL_USER_TEXT_MULTI_TEMPLATE % 2})
    assert len(content) == 19
    assert content == expected
    assert content[1]["text"] == "Panel 1, frame 1 of 4 (t=0.00s)"
    assert judge_clips.FINAL_USER_TEXT_MULTI_TEMPLATE % 2 == (
        "You are judging all 2 clips above, 4 sampled frames from each, against their panel "
        "text. Submit one clips entry per panel with motion_fidelity, physical_realism, and "
        "temporal_stability, score both seam_continuity and narrative_clarity for the movie, "
        "and call submit_judgment.")


def test_t8b_build_user_content_one_clip():
    content = judge_clips.build_user_content([_clip_input(1, "T1", "A")])
    assert len(content) == 10
    assert content[-1] == {"type": "text", "text": judge_clips.FINAL_USER_TEXT_SINGLE}
    assert judge_clips.FINAL_USER_TEXT_SINGLE == (
        "You are judging 1 clip above, shown as 4 sampled frames, against its panel text. "
        "There is only one clip, so there is no join between clips to judge: omit "
        "seam_continuity from your movie object entirely. Score motion_fidelity, "
        "physical_realism, and temporal_stability for the clip, score narrative_clarity for "
        "the movie, and call submit_judgment.")


def test_t8c_system_prompt_content():
    for phrase in ("the most realistic action scenes possible", "you receive no audio",
                   "Do not judge audio", "motion_fidelity:", "physical_realism:",
                   "temporal_stability:", "seam_continuity:", "narrative_clarity:",
                   "do not include seam_continuity", "you must include seam_continuity",
                   "exactly once"):
        assert phrase in judge_clips.SYSTEM_PROMPT, phrase
    assert not judge_clips.SYSTEM_PROMPT.endswith("\n")


# --- shared fixtures for main() tests -------------------------------------------------

def _dummy(n):
    """Placeholder clip bytes for precondition tests: nothing decodes a clip before E14."""
    return b"dummy clip %d" % n


def _make_story(tmp_path, monkeypatch, manifest=_manifest([PANEL_1, PANEL_2]), clips={1: 25, 2: 3},
                story_id=STORY_ID, with_clips_dir=True, synthetic=None):
    """Build tmp_path/generated/stories/<story_id>/ and point judge_clips.WS at tmp_path
    (spec 7.1). manifest: a dict or list is written with json.dumps, a str as-is, bytes
    with write_bytes; None writes no manifest.json. Unless with_clips_dir is False,
    clips/ is created, and each (number, spec) in clips becomes clips/panel_%02d.mp4 (a
    str number is used verbatim as the filename): an int spec copies synthetic[spec], a
    bytes spec is written as-is. Returns the story directory as a pathlib.Path."""
    monkeypatch.setattr(judge_clips, "WS", str(tmp_path))
    story_dir = tmp_path / "generated" / "stories" / story_id
    story_dir.mkdir(parents=True)
    manifest_path = story_dir / "manifest.json"
    if isinstance(manifest, (dict, list)):
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif isinstance(manifest, str):
        manifest_path.write_text(manifest, encoding="utf-8")
    elif isinstance(manifest, bytes):
        manifest_path.write_bytes(manifest)
    if with_clips_dir:
        clips_dir = story_dir / "clips"
        clips_dir.mkdir()
        for number, spec in clips.items():
            name = number if isinstance(number, str) else "panel_%02d.mp4" % number
            if isinstance(spec, int):
                shutil.copyfile(synthetic[spec], str(clips_dir / name))
            else:
                (clips_dir / name).write_bytes(spec)
    return story_dir


def _listing(directory):
    """Every path under directory, relative and sorted, to prove nothing was written."""
    return sorted(os.path.relpath(os.path.join(root, name), directory)
                  for root, dirs, files in os.walk(directory) for name in dirs + files)


class _FakeAnthropic:
    """Stands in for anthropic.Anthropic. Calling it records the construction and returns
    itself as the client; .messages.create(**kwargs) records kwargs and returns (or
    raises, for exception instances) the scripted items in order."""

    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.constructions = []
        self.calls = []
        self.messages = types.SimpleNamespace(create=self._create)

    def __call__(self, *args, **kwargs):
        self.constructions.append((args, kwargs))
        return self

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.scripted.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _install_fake(monkeypatch, scripted):
    fake = _FakeAnthropic(scripted)
    monkeypatch.setattr(judge_clips.anthropic, "Anthropic", fake)
    return fake


def _no_subprocess(monkeypatch):
    def _forbidden(*args, **kwargs):
        raise AssertionError("subprocess ran")
    monkeypatch.setattr(judge_clips.subprocess, "run", _forbidden)


def _no_tempdir(monkeypatch):
    def _forbidden(*args, **kwargs):
        raise AssertionError("temporary directory created")
    monkeypatch.setattr(judge_clips.tempfile, "TemporaryDirectory", _forbidden)


def _run_precondition(monkeypatch, capsys, story_dir, story_id=STORY_ID):
    """The spec 7.2 T14 harness. No subprocess or temporary directory may be created, a
    recording fake client is installed, and the key IS set, so a check that wrongly ran
    after the key gate would still trip a guard. Asserts exit 2, empty stdout, no client
    constructed, and (when story_dir is given) nothing written. Returns stderr."""
    _no_subprocess(monkeypatch)
    _no_tempdir(monkeypatch)
    fake = _install_fake(monkeypatch, [])
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    before = _listing(story_dir) if story_dir is not None else None
    assert judge_clips.main(["--story-id", story_id]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert fake.constructions == []
    if story_dir is not None:
        assert _listing(story_dir) == before
    return err


# --- T1, T2, T14, T15, T24: arguments, paths, preconditions, key gate, wiring ----------

def test_t1a_no_args_exit_2():
    with pytest.raises(SystemExit) as exc:
        judge_clips.main([])
    assert exc.value.code == 2


def test_t1b_unknown_flag_exit_2():
    with pytest.raises(SystemExit) as exc:
        judge_clips.main(["--story-md", "x"])
    assert exc.value.code == 2


def test_t2_resolve_paths(monkeypatch, tmp_path):
    assert judge_clips.WS == WS
    base = os.path.join(WS, "generated", "stories", "abc")
    assert judge_clips.resolve_paths("abc") == (
        base, os.path.join(base, "clips"), os.path.join(base, "manifest.json"))
    # WS is read at call time, not import time (spec 2.2).
    monkeypatch.setattr(judge_clips, "WS", str(tmp_path))
    assert judge_clips.resolve_paths("abc")[0] == os.path.join(
        str(tmp_path), "generated", "stories", "abc")


def test_t14a_missing_clips_dir(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, clips={}, with_clips_dir=False)
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == "Error: clips directory not found: %s\n" % (story_dir / "clips")


def test_t14b_no_matching_clips(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, clips={
        "panel_1.mp4": _dummy(1), "panel_01.mp4.provenance.json": b"{}",
        "panel_02.chainseed.png": b"png"})
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == "Error: no panel_NN.mp4 clips found in %s\n" % (story_dir / "clips")


def test_t14c_duplicate_clip_number(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, manifest=_manifest([PANEL_1]),
                            clips={1: _dummy(1), "panel_001.mp4": _dummy(1)})
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == ("Error: more than one clip for panel 1 in %s: panel_001.mp4, panel_01.mp4\n"
                   % (story_dir / "clips"))


def test_t14d_more_than_25_clips(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, manifest=None,
                            clips={n: _dummy(n) for n in range(1, 27)})
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == ("Error: 26 clips found in %s; judge-clips sends 4 frames per clip in one "
                   "request and judges at most 25 clips (100 images, the Anthropic API's "
                   "per-request image limit for 200k-context models).\n" % (story_dir / "clips"))


def test_t14e_exactly_25_clips_passes_cap(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, manifest=None,
                            clips={n: _dummy(n) for n in range(1, 26)})
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == "Error: manifest.json not found: %s\n" % (story_dir / "manifest.json")


def test_t14f_missing_manifest(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, manifest=None, clips={1: _dummy(1)})
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == "Error: manifest.json not found: %s\n" % (story_dir / "manifest.json")


def test_t14g_manifest_not_valid_json(tmp_path, monkeypatch, capsys):
    for i, manifest in enumerate(("{not json", b"\xff\xfe{}")):
        story_id = "bad-json-%d" % i
        story_dir = _make_story(tmp_path, monkeypatch, manifest=manifest,
                                clips={1: _dummy(1)}, story_id=story_id)
        err = _run_precondition(monkeypatch, capsys, story_dir, story_id=story_id)
        assert err.startswith("Error: manifest.json is not valid JSON: %s: "
                              % (story_dir / "manifest.json"))
        assert err.endswith("\n") and err.count("\n") == 1


def test_t14h_manifest_without_panels_list(tmp_path, monkeypatch, capsys):
    for i, manifest in enumerate(([], {}, {"panels": {}}, {"panels": []})):
        story_id = "no-panels-%d" % i
        story_dir = _make_story(tmp_path, monkeypatch, manifest=manifest,
                                clips={1: _dummy(1)}, story_id=story_id)
        err = _run_precondition(monkeypatch, capsys, story_dir, story_id=story_id)
        assert err == ("Error: manifest.json has no panels list: %s\n"
                       % (story_dir / "manifest.json"))


def test_t14i_panel_entry_without_integer_index(tmp_path, monkeypatch, capsys):
    cases = [({"panels": [{"title": "x"}]}, 1),
             ({"panels": [{"index": 1}, {"index": "2"}]}, 2),
             ({"panels": [{"index": True}]}, 1),
             ({"panels": ["panel"]}, 1)]
    for i, (manifest, position) in enumerate(cases):
        story_id = "bad-index-%d" % i
        story_dir = _make_story(tmp_path, monkeypatch, manifest=manifest,
                                clips={1: _dummy(1)}, story_id=story_id)
        err = _run_precondition(monkeypatch, capsys, story_dir, story_id=story_id)
        assert err == ("Error: manifest.json panel entry %d has no integer index: %s\n"
                       % (position, story_dir / "manifest.json"))


def test_t14j_duplicate_manifest_index(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch,
                            manifest={"panels": [{"index": 1}, {"index": 1}]},
                            clips={1: _dummy(1)})
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == ("Error: manifest.json lists panel index 1 more than once: %s\n"
                   % (story_dir / "manifest.json"))


def test_t14k_extra_clip(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch,
                            clips={1: _dummy(1), 2: _dummy(2), 3: _dummy(3)})
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == ("Error: clips with no matching panel in manifest.json: panel_03.mp4; the "
                   "clips in %s may be stale relative to manifest.json.\n" % (story_dir / "clips"))


def test_t14l_partial_render(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch,
                            manifest=_manifest([{"index": i} for i in (1, 2, 3, 4)]),
                            clips={1: _dummy(1), 3: _dummy(3)})
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == ("Error: manifest.json panels with no rendered clip in %s: 2, 4; "
                   "judge-clips judges only complete renders.\n" % (story_dir / "clips"))


def test_t14m_nonexistent_story(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(judge_clips, "WS", str(tmp_path))
    story_id = "judge-clips-test-nonexistent-%s" % uuid.uuid4().hex
    err = _run_precondition(monkeypatch, capsys, None, story_id=story_id)
    assert err.startswith("Error: clips directory not found:")
    assert not (tmp_path / "generated").exists()


def test_t14n_ffmpeg_or_ffprobe_missing(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, clips={1: _dummy(1), 2: _dummy(2)})
    monkeypatch.setattr(judge_clips.shutil, "which",
                        lambda t: None if t == "ffprobe" else "/bin/" + t)
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == ("Error: ffprobe not found on PATH; judge-clips needs ffmpeg and ffprobe "
                   "to extract frames.\n")
    # Both missing: ffmpeg is reported, which pins the check order.
    monkeypatch.setattr(judge_clips.shutil, "which", lambda t: None)
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == ("Error: ffmpeg not found on PATH; judge-clips needs ffmpeg and ffprobe "
                   "to extract frames.\n")


def test_t14o_extra_clip_reported_before_missing(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, clips={1: _dummy(1), 3: _dummy(3)})
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == ("Error: clips with no matching panel in manifest.json: panel_03.mp4; the "
                   "clips in %s may be stale relative to manifest.json.\n" % (story_dir / "clips"))


def test_t15_key_unset_runs_nothing(tmp_path, monkeypatch, capsys, synthetic_clips):
    story_dir = _make_story(tmp_path, monkeypatch, synthetic=synthetic_clips)
    before = _listing(story_dir)
    _no_subprocess(monkeypatch)
    _no_tempdir(monkeypatch)
    fake = _install_fake(monkeypatch, [])
    expected_err = ("Error: ANTHROPIC_API_KEY is not set; export it in your environment to "
                    "run judge-clips.\n")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert judge_clips.main(["--story-id", STORY_ID]) == 1
    out, err = capsys.readouterr()
    assert err == expected_err
    assert out == ""
    assert fake.constructions == []
    assert fake.calls == []
    # An empty value counts as unset (spec 4.2).
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert judge_clips.main(["--story-id", STORY_ID]) == 1
    out, err = capsys.readouterr()
    assert err == expected_err
    assert out == ""
    assert fake.constructions == []
    assert fake.calls == []
    assert _listing(story_dir) == before


def test_t24_pipeline_log_wiring():
    with open(_SCRIPT_PATH, encoding="utf-8") as f:
        text = f.read()
    assert ('pipeline_log.run_logged("judge-clips", _pipeline_log_story_dir(sys.argv[1:]), '
            'main, sys.argv)') in text
    assert "sys.path.insert(0, WS)" in text
    assert "import pipeline_log" in text
    assert "    sys.exit(main())" not in text
    assert (judge_clips._pipeline_log_story_dir(["--story-id", "abc"])
            == os.path.join(WS, "generated", "stories", "abc"))
    assert judge_clips._pipeline_log_story_dir([]) is None


# --- SDK response builders: real anthropic.types.Message objects (spec 7.1) ----------

THINKING_BLOCK = {"type": "thinking", "thinking": "Comparing the clips to the panel text.",
                  "signature": "sig-abc123"}


def _usage(input_tokens, output_tokens, thinking_tokens):
    """thinking_tokens=None omits output_tokens_details, as when the API does not report it."""
    usage = {"input_tokens": input_tokens, "output_tokens": output_tokens}
    if thinking_tokens is not None:
        usage["output_tokens_details"] = {"thinking_tokens": thinking_tokens}
    return usage


def _message(content, usage, stop_reason):
    return anthropic.types.Message.model_validate({
        "id": "msg_test_%s" % uuid.uuid4().hex, "type": "message", "role": "assistant",
        "model": "claude-opus-5-5", "stop_reason": stop_reason, "stop_sequence": None,
        "content": content, "usage": usage})


def _tool_response(tool_input, usage):
    return _message([THINKING_BLOCK, {"type": "tool_use", "id": "toolu_test",
                                      "name": "submit_judgment", "input": tool_input}],
                    usage, "tool_use")


def _text_response(text, usage):
    return _message([THINKING_BLOCK, {"type": "text", "text": text}], usage, "end_turn")


_REAL_TEMPORARY_DIRECTORY = tempfile.TemporaryDirectory


def _record_tempdirs(monkeypatch):
    """Wrap the real tempfile.TemporaryDirectory (captured at import, before any patch)
    so each directory judge-clips creates is recorded. Returns the list of names."""
    created = []

    def _recording(*args, **kwargs):
        tmp = _REAL_TEMPORARY_DIRECTORY(*args, **kwargs)
        created.append(tmp.name)
        return tmp
    monkeypatch.setattr(judge_clips.tempfile, "TemporaryDirectory", _recording)
    return created


TWO_CLIP_STDOUT = ("Clip scores:\n"
                   "  panel  motion_fidelity   physical_realism  temporal_stability\n"
                   "  1      7                 6                 8\n"
                   "  2      4                 3                 5\n"
                   "\n"
                   "Movie scores:\n"
                   "  seam_continuity       9\n"
                   "  narrative_clarity     2\n"
                   "\n"
                   "--- Critique ---\n")


# --- T16-T18, T21, T25: extraction in main, judging call, outputs (spec 1.4, 4-6) ----

def test_t16_extraction_failure(tmp_path, monkeypatch, capsys, synthetic_clips):
    story_dir = _make_story(tmp_path, monkeypatch, clips={1: 25, 2: GARBAGE_CLIP},
                            synthetic=synthetic_clips)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    fake = _install_fake(monkeypatch, [])
    created = _record_tempdirs(monkeypatch)
    before = _listing(story_dir)

    assert judge_clips.main(["--story-id", STORY_ID]) == 1

    out, err = capsys.readouterr()
    assert err.startswith("Error: frame extraction failed: ffprobe failed on %s (exit 1): "
                          % (story_dir / "clips" / "panel_02.mp4"))
    assert out == ""
    assert fake.constructions == []
    assert len(created) == 1
    assert not os.path.exists(created[0])
    assert _listing(story_dir) == before


def test_t17_successful_run_two_clips(tmp_path, monkeypatch, capsys, synthetic_clips):
    story_dir = _make_story(tmp_path, monkeypatch, synthetic=synthetic_clips)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    created = _record_tempdirs(monkeypatch)
    clips_before = _listing(story_dir / "clips")
    fake = _install_fake(monkeypatch, [
        _tool_response(copy.deepcopy(VALID_INPUT), _usage(1200, 3400, 2100))])

    assert judge_clips.main(["--story-id", STORY_ID]) == 0

    with open(story_dir / "clips_judgment.json", encoding="utf-8") as f:
        raw_text = f.read()
    judgment = json.loads(raw_text)
    assert list(judgment) == ["story_id", "model", "effort", "timestamp", "frames_per_clip",
                              "usage", "clips", "movie", "critique"]
    assert judgment["story_id"] == STORY_ID
    assert judgment["model"] == "claude-opus-5-5"
    assert judgment["effort"] == "high"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", judgment["timestamp"])
    assert judgment["frames_per_clip"] == 4
    assert judgment["usage"] == {"input_tokens": 1200, "output_tokens": 3400,
                                 "thinking_tokens": 2100}
    assert judgment["clips"] == [
        {"panel": 1, "frames": [0, 8, 16, 24], "motion_fidelity": 7, "physical_realism": 6,
         "temporal_stability": 8},
        {"panel": 2, "frames": [0, 1, 1, 2], "motion_fidelity": 4, "physical_realism": 3,
         "temporal_stability": 5}]
    for entry in judgment["clips"]:
        assert list(entry) == ["panel", "frames", "motion_fidelity", "physical_realism",
                               "temporal_stability"]
    assert judgment["movie"] == {"seam_continuity": 9, "narrative_clarity": 2}
    assert list(judgment["movie"]) == ["seam_continuity", "narrative_clarity"]
    assert judgment["critique"] == VALID_INPUT["critique"]
    assert "—" in raw_text                 # ensure_ascii=False
    assert raw_text.endswith("}\n")        # trailing newline after json.dump
    for name in ("clips_judgment.raw.json", "judgment.json", "stills_judgment.json"):
        assert not (story_dir / name).exists(), name

    out, err = capsys.readouterr()
    assert out == TWO_CLIP_STDOUT + VALID_INPUT["critique"] + "\n"
    assert err == ""

    assert fake.constructions == [((), {})]               # Anthropic() with no arguments
    assert len(fake.calls) == 1
    kwargs = fake.calls[0]
    assert sorted(kwargs) == ["max_tokens", "messages", "model", "output_config", "system",
                              "thinking", "tool_choice", "tools"]
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["max_tokens"] == 21333
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"] == {"effort": "high"}
    assert kwargs["tool_choice"] == {"type": "auto"}
    assert kwargs["system"] == judge_clips.SYSTEM_PROMPT
    assert [tool["name"] for tool in kwargs["tools"]] == ["submit_judgment"]
    assert kwargs["tools"][0]["input_schema"] == judge_clips.SUBMIT_JUDGMENT_SCHEMA
    assert kwargs["tools"][0]["description"] == judge_clips.TOOL_DESCRIPTION
    messages = kwargs["messages"]
    assert len(messages) == 1 and messages[0]["role"] == "user"
    content = messages[0]["content"]
    assert [block["type"] for block in content] == (
        ["text"] + ["text", "image"] * 4 + ["text"] + ["text", "image"] * 4 + ["text"])
    assert content[0]["text"] == judge_clips.format_panel_text(1, PANEL_1)
    assert content[9]["text"] == judge_clips.format_panel_text(2, PANEL_2)
    # 24-fps values; the manifest's fps of 30 would give 0.27, 0.53, 0.80 and 0.03, 0.03, 0.07.
    assert [content[i]["text"] for i in (1, 3, 5, 7)] == [
        "Panel 1, frame 1 of 4 (t=0.00s)", "Panel 1, frame 2 of 4 (t=0.33s)",
        "Panel 1, frame 3 of 4 (t=0.67s)", "Panel 1, frame 4 of 4 (t=1.00s)"]
    assert [content[i]["text"] for i in (10, 12, 14, 16)] == [
        "Panel 2, frame 1 of 4 (t=0.00s)", "Panel 2, frame 2 of 4 (t=0.04s)",
        "Panel 2, frame 3 of 4 (t=0.04s)", "Panel 2, frame 4 of 4 (t=0.08s)"]
    for i in (2, 4, 6, 8, 11, 13, 15, 17):
        assert content[i]["source"]["type"] == "base64"
        assert content[i]["source"]["media_type"] == "image/jpeg"
    assert [_frame_number(base64.b64decode(content[i]["source"]["data"]), tmp_path)
            for i in (2, 4, 6, 8)] == [0, 8, 16, 24]
    assert [_frame_number(base64.b64decode(content[i]["source"]["data"]), tmp_path)
            for i in (11, 13, 15, 17)] == [0, 1, 1, 2]
    assert content[18]["text"] == judge_clips.FINAL_USER_TEXT_MULTI_TEMPLATE % 2

    assert len(created) == 1
    assert os.path.basename(created[0]).startswith("judge-clips-")
    assert not os.path.exists(created[0])
    assert not os.path.realpath(created[0]).startswith(os.path.realpath(str(story_dir)))
    assert _listing(story_dir / "clips") == clips_before


def test_t18_successful_run_one_clip(tmp_path, monkeypatch, capsys, synthetic_clips):
    story_dir = _make_story(tmp_path, monkeypatch, manifest=_manifest([PANEL_1]),
                            clips={1: 1}, synthetic=synthetic_clips)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    fake = _install_fake(monkeypatch, [
        _tool_response(copy.deepcopy(ONE_CLIP_INPUT), _usage(900, 2500, 1500))])

    assert judge_clips.main(["--story-id", STORY_ID]) == 0

    with open(story_dir / "clips_judgment.json", encoding="utf-8") as f:
        raw_text = f.read()
    judgment = json.loads(raw_text)
    assert judgment["clips"] == [{"panel": 1, "frames": [0, 0, 0, 0], "motion_fidelity": 7,
                                  "physical_realism": 6, "temporal_stability": 8}]
    assert judgment["movie"] == {"seam_continuity": None, "narrative_clarity": 2}
    assert '"seam_continuity": null' in raw_text
    out, err = capsys.readouterr()
    assert out == ("Clip scores:\n"
                   "  panel  motion_fidelity   physical_realism  temporal_stability\n"
                   "  1      7                 6                 8\n"
                   "\n"
                   "Movie scores:\n"
                   "  seam_continuity       n/a (only 1 clip)\n"
                   "  narrative_clarity     2\n"
                   "\n"
                   "--- Critique ---\n" + ONE_CLIP_INPUT["critique"] + "\n")
    assert err == ""
    assert len(fake.calls) == 1                       # a valid tool_use: no retry
    content = fake.calls[0]["messages"][0]["content"]
    assert len(content) == 10
    assert len({content[i]["source"]["data"] for i in (2, 4, 6, 8)}) == 1
    assert [content[i]["text"] for i in (1, 3, 5, 7)] == [
        "Panel 1, frame %d of 4 (t=0.00s)" % k for k in (1, 2, 3, 4)]
    assert content[9]["text"] == judge_clips.FINAL_USER_TEXT_SINGLE


def test_t21a_schema_invalid_tool_input(tmp_path, monkeypatch, capsys, synthetic_clips):
    story_dir = _make_story(tmp_path, monkeypatch, synthetic=synthetic_clips)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    bad = copy.deepcopy(VALID_INPUT)
    bad["clips"][0]["temporal_stability"] = 11            # clips[0] is panel 2
    fake = _install_fake(monkeypatch, [_tool_response(bad, _usage(10, 20, 5))])

    assert judge_clips.main(["--story-id", STORY_ID]) == 1

    assert len(fake.calls) == 1            # no retry on a validation failure
    with open(story_dir / "clips_judgment.raw.json", encoding="utf-8") as f:
        raw = json.load(f)
    assert len(raw["responses"]) == 1
    assert not (story_dir / "clips_judgment.json").exists()
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("Error: submit_judgment input failed schema validation: ")


def test_t21b_missing_judged_panel(tmp_path, monkeypatch, capsys, synthetic_clips):
    story_dir = _make_story(tmp_path, monkeypatch, synthetic=synthetic_clips)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    partial = copy.deepcopy(VALID_INPUT)
    partial["clips"] = [partial["clips"][1]]               # panel 1 only
    fake = _install_fake(monkeypatch, [_tool_response(partial, _usage(10, 20, 5))])

    assert judge_clips.main(["--story-id", STORY_ID]) == 1

    assert len(fake.calls) == 1
    with open(story_dir / "clips_judgment.raw.json", encoding="utf-8") as f:
        assert len(json.load(f)["responses"]) == 1
    assert not (story_dir / "clips_judgment.json").exists()
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ("Error: submit_judgment input failed schema validation: clips is missing "
                   "these judged panels: 2\n")


def test_t21c_two_clips_missing_seam(tmp_path, monkeypatch, capsys, synthetic_clips):
    story_dir = _make_story(tmp_path, monkeypatch, synthetic=synthetic_clips)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    no_seam = copy.deepcopy(VALID_INPUT)
    del no_seam["movie"]["seam_continuity"]
    fake = _install_fake(monkeypatch, [_tool_response(no_seam, _usage(10, 20, 5))])

    assert judge_clips.main(["--story-id", STORY_ID]) == 1

    assert len(fake.calls) == 1
    with open(story_dir / "clips_judgment.raw.json", encoding="utf-8") as f:
        assert len(json.load(f)["responses"]) == 1
    assert not (story_dir / "clips_judgment.json").exists()
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ("Error: submit_judgment input failed schema validation: seam_continuity "
                   "is required when judging 2 or more clips\n")


def test_t25_float_scores_written_as_integers(tmp_path, monkeypatch, capsys, synthetic_clips):
    story_dir = _make_story(tmp_path, monkeypatch, manifest=_manifest([PANEL_1]),
                            clips={1: 1}, synthetic=synthetic_clips)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    _install_fake(monkeypatch, [_tool_response(
        {"clips": [{"panel": 1.0, "motion_fidelity": 7.0, "physical_realism": 6.0,
                    "temporal_stability": 8.0}],
         "movie": {"narrative_clarity": 2.0}, "critique": "c"}, _usage(10, 20, 5))])

    assert judge_clips.main(["--story-id", STORY_ID]) == 0

    with open(story_dir / "clips_judgment.json", encoding="utf-8") as f:
        raw_text = f.read()
    judgment = json.loads(raw_text)
    for entry in judgment["clips"]:
        for key in ("panel", "motion_fidelity", "physical_realism", "temporal_stability"):
            assert type(entry[key]) is int, key
    assert type(judgment["movie"]["narrative_clarity"]) is int
    assert judgment["movie"]["seam_continuity"] is None
    assert '"panel": 1,' in raw_text
