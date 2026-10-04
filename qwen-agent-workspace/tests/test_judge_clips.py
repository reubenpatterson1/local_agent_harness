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
