"""movie-ui progress parser (movie-ui spec MUT16, MU55, MU56).
Run from the workspace root: python3 -m pytest tests/test_movie_ui_progress.py -v"""

import os

import movie_ui_testutil as mt
import movie_ui_lib as lib


def _read(name):
    with open(os.path.join(mt.FIXTURES, name), "rb") as f:
        return f.read()


def _job(tmp_path, kind, fields, story_id="demo"):
    return {"id": "20261019-142233-a1b2", "kind": kind, "workspace": str(tmp_path), "story_id": story_id,
            "fields": fields}


def _parse(name, kind, fields, slices=None):
    parser = lib.ProgressParser(kind, fields)
    data = _read(name)
    if slices is None:
        parser.feed(data)
    else:
        for i in range(0, len(data), slices):
            parser.feed(data[i:i + slices])
    return parser


def test_mut16_render_chained(tmp_path):
    fields = {"action": "movie", "mode": "chained", "panels": 3, "seed_upload": None}
    parser = _parse("render-chained.log", "movie", fields)
    progress = parser.snapshot(_job(tmp_path, "movie", fields), {"started": lib.utc_now()}, str(tmp_path))
    assert progress == {
        "phase": "4", "phase_title": "render", "rewrite": None, "phases": ["1", "1b", "2", "3", "4"], "redo": None,
        "panels_total": 3,
        "panels": {"1": {"state": "ok", "reused": False}, "2": {"state": "ok", "reused": False},
                   "3": {"state": "running"}},
        "panels_done": 2, "wrap_up": False, "stills": None, "last_line": "ltx-2-mlx: 60%"}
    sliced = _parse("render-chained.log", "movie", fields, slices=7)
    assert sliced.snapshot(_job(tmp_path, "movie", fields), None, str(tmp_path)) == progress
    assert parser.offset == len(_read("render-chained.log"))


def test_mut16_shots_redo_failed_then_summary(tmp_path):
    fields = {"action": "redo", "mode": "shots", "panels": 4, "seed_upload": None, "redo": [2, 4]}
    progress = _parse("render-shots-redo.log", "movie", fields).snapshot(
        _job(tmp_path, "movie", fields), None, str(tmp_path))
    assert progress["phases"] == ["1", "1b", "redo", "2", "3", "4"]
    assert progress["redo"] == "2,4" and progress["phase"] == "4"
    assert progress["panels"] == {
        "1": {"state": "ok", "reused": True}, "2": {"state": "ok", "reused": False},
        "3": {"state": "ok", "reused": True},
        "4": {"state": "failed", "reason": "timeout, rc=-9", "detail": "ltx-2-mlx exceeded --panel-timeout 7200s"}}
    assert progress["panels_done"] == 3 and progress["panels_total"] == 4 and progress["wrap_up"] is True
    assert progress["last_line"] == "Error: 1 panel(s) failed"


def test_mut16_story_only_rewrite_and_phases(tmp_path):
    fields = {"action": "story", "mode": "chained", "panels": 6, "seed_upload": "a" * 64 + ".png"}
    progress = _parse("story-only.log", "story", fields).snapshot(_job(tmp_path, "story", fields), None, str(tmp_path))
    assert progress["phases"] == ["0", "1"]
    assert (progress["phase"], progress["phase_title"], progress["rewrite"]) == ("1", "story", [1, 2])
    assert progress["panels"] == {} and progress["panels_total"] is None and progress["panels_done"] == 0
    assert progress["last_line"] == "story.md written: /ws/generated/stories/demo/story.md"
    assert lib.job_phases("movie", {"action": "movie", "mode": "no_stills"}) == ["1", "1b", "3", "4"]
    assert lib.job_phases("movie", {"action": "movie", "mode": "chained", "seed_upload": "x.png"}) == [
        "0", "1", "1b", "2", "3", "4"]


def test_mut16_stills_count_during_phase_2(tmp_path):
    images = os.path.join(str(tmp_path), "generated", "stories", "demo", "images")
    os.makedirs(images)
    for name in ("panel_01.png", "panel_02.png", "panel_3.png", "seed.png"):
        open(os.path.join(images, name), "wb").close()
    for mode, expected in (("chained", 1), ("shots", 5)):
        fields = {"action": "movie", "mode": mode, "panels": 5, "seed_upload": None}
        parser = lib.ProgressParser("movie", fields)
        parser.feed(b"=== Phase 1: story ===\n=== Phase 2: stills ===\n")
        assert parser.snapshot(_job(tmp_path, "movie", fields), None, str(tmp_path))["stills"] == {
            "expected": expected, "count": 2}


def test_mut16_cr_collapse_and_character_face(tmp_path):
    assert lib.collapse("a\rb\rc\r") == "c"
    assert lib.collapse("plain") == "plain"
    parser = lib.ProgressParser("movie", {"action": "movie", "mode": "chained"})
    parser.feed(b"=== panel 1/2 (x) ===\nstep 1\rstep 2")
    assert parser.current_last_line() == "step 2"
    parser.feed(b"\rpanel 1 ok: /c.mp4 (1.0s)\n")
    assert parser.panels == {"1": {"state": "ok", "reused": False}}
    parser.feed(("x" * 400 + "\n").encode())
    assert len(parser.current_last_line()) == 300
    fields = {"name": "kyra"}
    face = _parse("character-face.log", "character-create", fields)
    snap = face.snapshot(_job(tmp_path, "character-create", fields, story_id=None),
                         {"started": "2026-10-19T10:00:00Z"}, str(tmp_path), now=lib.parse_utc("2026-10-19T10:00:42Z"))
    assert snap == {"kind": "character-create", "elapsed_s": 42, "last_line": "[movie-ui] exit 2 (failed)",
                    "face_problem": True}
    other = lib.ProgressParser("character-train", fields)
    other.feed(b"Error: the vision model found no face in the seed image; pass --force to proceed anyway.\n")
    assert other.face_problem is True
    assert lib.ProgressParser("character-train", fields).snapshot(
        _job(tmp_path, "character-train", fields), None, str(tmp_path))["elapsed_s"] is None
