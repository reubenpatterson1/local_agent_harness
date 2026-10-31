"""Tests for bin/seam-report (docs/superpowers/specs/2026-10-30-chained-end-frames-design.md,
Sections 3 and 6: CT17-CT22 and CT30, with the plan's Review Focus pins 1 and 2).

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_seam_report.py
Stdlib plus pytest. No test renders, reads the real HOME, or contacts a model server, a daemon,
ffmpeg or the Anthropic API: the VLM (vlm_models, vlm_complete), ffmpeg (last_frame_png and
shutil.which) and http.client.HTTPConnection are monkeypatched, HOME and the temporary directory
are under tmp_path, and every story lives in a temporary workspace.
"""

import ast
import http.client
import importlib.machinery
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SEAM = os.path.join(WS, "bin", "seam-report")
seam = importlib.machinery.SourceFileLoader("seam_report_for_tests", SEAM).load_module()

COURIER = ("a young man with short brown hair and a lean build wearing a yellow rain jacket and "
           "grey trousers")
E1 = "The courier stands at frame centre on the wet quay, facing the camera, seen from the waist up."
E2 = "The courier stands at the left edge beside the boats, facing right, seen from the knees up."
E3 = "The courier holds out the sealed letter at frame centre, facing the camera, in a close-up."
SEED2 = b"\x89PNG\r\n\x1a\nseed-of-panel-2"
SEED3 = b"\x89PNG\r\n\x1a\nseed-of-panel-3"
LAST_PNG = b"\x89PNG\r\n\x1a\nlast-frame-of-a-clip"
MP4 = b"\x00\x00\x00\x18ftypmp42"
CREATED = "2026-10-31T12:00:00Z"
DOWN = ("Error: the story server is not answering at 127.0.0.1:8177 (%s); nothing was changed. "
        "Start it with bin/story-server mlx-vision and rerun bin/seam-report %s.\n")
STOPPED = ("Error: the story server stopped answering at 127.0.0.1:8177 (%s) while checking "
           "panel %d; nothing was written. Start it with bin/story-server mlx-vision and rerun "
           "bin/seam-report %s.\n")


@pytest.fixture(autouse=True)
def isolation(monkeypatch, tmp_path):
    """A temporary HOME and temporary directory, no STORY_SERVER_PORT, and no real network."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("STORY_SERVER_PORT", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    temp = tmp_path / "tmp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))

    def no_network(*_args, **_kw):
        raise AssertionError("a test opened an HTTP connection")
    monkeypatch.setattr(http.client, "HTTPConnection", no_network)
    return {"home": str(home), "temp": str(temp)}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """<tmp>/ws with generated/stories/ and story_engine.py symlinked; seam.WS points at it."""
    root = tmp_path / "ws"
    (root / "generated" / "stories").mkdir(parents=True)
    os.symlink(os.path.join(WS, "story_engine.py"), str(root / "story_engine.py"))
    monkeypatch.setattr(seam, "WS", str(root))
    monkeypatch.setattr(seam, "_utc", lambda: CREATED)
    return str(root)


def _plan(frames=(E1, E2, E3), mode="chained", casts=None):
    """A plan.json document whose beat k has end_frame frames[k - 1] (none when None)."""
    beats = []
    for k, frame in enumerate(frames, start=1):
        beat = {"index": k, "arc": "rising", "action": "the courier rides on", "shot": "medium shot",
                "camera": "slow push-in", "location": "l1",
                "cast": list((casts or {}).get(k, ["c1"])), "speaker": "", "lines": []}
        if frame is not None:
            beat["end_frame"] = frame
        beats.append(beat)
    return {"schema": "ltx-movie.plan.v1", "story_id": "sr1", "mode": mode, "panels": len(beats),
            "cast": [{"id": "c1", "phrase": "the courier", "descriptor": COURIER, "cast_name": None},
                     {"id": "c2", "phrase": "the old monk", "descriptor": "an old man in a robe",
                      "cast_name": None}],
            "beats": beats}


def _story(ws, plan, story_id="sr1", files=()):
    """generated/stories/<story_id>/ with plan (a dict, or raw text; None: no plan.json) and
    files [(relpath, bytes, mtime)]; returns the story directory."""
    sdir = os.path.join(ws, "generated", "stories", story_id)
    os.makedirs(os.path.join(sdir, "clips"), exist_ok=True)
    if plan is not None:
        with open(os.path.join(sdir, "plan.json"), "w", encoding="utf-8") as f:
            f.write(plan if isinstance(plan, str) else json.dumps(plan))
    for rel, data, mtime in files:
        path = os.path.join(sdir, rel)
        with open(path, "wb") as f:
            f.write(data)
        os.utime(path, (mtime, mtime))
    return sdir


def _reports(sdir):
    return sorted(n for n in os.listdir(sdir) if n.startswith("seam_report"))


class FakeVLM(object):
    """vlm_models and vlm_complete stand-ins: replies are returned (an Exception is raised) in
    order; calls records (port, model, prompt, png)."""

    def __init__(self, replies, model="test-vlm"):
        self.replies = list(replies)
        self.model = model
        self.calls = []
        self.ports = []

    def models(self, port):
        self.ports.append(port)
        return self.model, None

    def complete(self, port, model, prompt, png):
        self.calls.append((port, model, prompt, png))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _vlm(monkeypatch, replies, model="test-vlm"):
    fake = FakeVLM(replies, model)
    monkeypatch.setattr(seam, "vlm_models", fake.models)
    monkeypatch.setattr(seam, "vlm_complete", fake.complete)
    return fake


def _ffmpeg(monkeypatch, fail=None):
    """shutil.which finds ffmpeg and ffprobe; last_frame_png writes LAST_PNG, or raises
    SeamError(fail). Returns the clip names it was called with."""
    monkeypatch.setattr(seam.shutil, "which", lambda name: "/opt/fake/bin/" + name)
    calls = []

    def fake(clip, out_png):
        calls.append(os.path.basename(clip))
        if fail is not None:
            raise seam.SeamError(fail)
        with open(out_png, "wb") as f:
            f.write(LAST_PNG)
    monkeypatch.setattr(seam, "last_frame_png", fake)
    return calls


def _reply(score, reason, missing=()):
    return json.dumps({"score": score, "reason": reason, "missing": list(missing)})


def _run(argv, capsys):
    rc = seam.main(argv)
    out, err = capsys.readouterr()
    return rc, out, err


# --- CT17: nothing to check (CE13 steps 3-5) -------------------------------------------------------

def test_ct17_nothing_to_check(ws, monkeypatch, capsys):
    def never(*_args):
        raise AssertionError("the story server was contacted")
    monkeypatch.setattr(seam, "vlm_models", never)
    sdir = _story(ws, _plan(mode="shots"), "shots-story")
    assert _run(["shots-story"], capsys) == (0, "seam-report: nothing to check: shots-story is a "
                                             "shots story; seams are checked only in chained "
                                             "stories\n", "")
    assert _reports(sdir) == []
    sdir = _story(ws, _plan(frames=(None, None)), "no-frames")
    assert _run(["no-frames"], capsys) == (
        0, "seam-report: nothing to check: this plan has no end frames; no seam report\n", "")
    assert _reports(sdir) == []
    sdir = _story(ws, _plan(frames=("   ", None)), "blank-frames")
    assert _run(["blank-frames"], capsys)[1] == (
        "seam-report: nothing to check: this plan has no end frames; no seam report\n")
    sdir = _story(ws, _plan(), "no-clips")
    assert _run(["no-clips"], capsys) == (
        0, "seam-report: no clips to check in %s\n" % os.path.join(sdir, "clips"), "")
    assert _reports(sdir) == []


def test_ct17_the_script_as_a_subprocess(tmp_path):
    root = tmp_path / "sub"
    (root / "bin").mkdir(parents=True)
    shutil.copy(SEAM, str(root / "bin" / "seam-report"))
    os.symlink(os.path.join(WS, "story_engine.py"), str(root / "story_engine.py"))
    sdir = _story(str(root), _plan(), "sub-story")
    env = dict(os.environ, HOME=str(tmp_path / "home"))
    proc = subprocess.run([sys.executable, str(root / "bin" / "seam-report"), "sub-story"],
                          capture_output=True, text=True, env=env, timeout=60)
    clips = os.path.join(os.path.realpath(str(root)), "generated", "stories", "sub-story", "clips")
    assert (proc.returncode, proc.stdout, proc.stderr) == (
        0, "seam-report: no clips to check in %s\n" % clips, "")
    assert _reports(sdir) == []


# --- CT18: preconditions (CE13 CLI and steps 1, 2, 6) ---------------------------------------------

def test_ct18_preconditions(ws, monkeypatch, capsys):
    stories = os.path.join(ws, "generated", "stories")
    for bad in ("bad/../id", "a..b", ".hidden", "x" * 81):
        assert _run([bad], capsys) == (2, "", "Error: invalid story id: %s\n" % bad), bad
    assert _run(["nope"], capsys) == (2, "", "Error: no story nope in %s\n" % stories)
    for story_id, plan in (("missing", None), ("not-json", "{not json"),
                           ("wrong-schema", dict(_plan(), schema="ltx-movie.plan.v0")),
                           ("no-mode", dict(_plan(), mode=None)),
                           ("no-beats", dict(_plan(), beats={})), ("a-list", "[]")):
        sdir = _story(ws, plan, story_id)
        path = os.path.join(sdir, "plan.json")
        assert _run([story_id], capsys) == (
            2, "", "Error: %s is not a plan.json written by bin/ltx-movie's default story "
                   "engine\n" % path), story_id
        assert _reports(sdir) == []
    sdir = _story(ws, _plan(), "no-ffmpeg", files=[("clips/panel_01.mp4", MP4, 1000)])
    monkeypatch.setattr(seam.shutil, "which", lambda name: None if name == "ffprobe" else "/x")
    assert _run(["no-ffmpeg"], capsys) == (
        2, "", "Error: ffmpeg and ffprobe must be on PATH to read the clips in %s\n"
        % os.path.join(sdir, "clips"))
    assert _reports(sdir) == []
    for argv in ([], ["a", "b"], ["sr1", "--port", "x"]):
        with pytest.raises(SystemExit) as exit_info:
            seam.main(argv)
        assert exit_info.value.code == 2, argv
    capsys.readouterr()
    assert seam.build_parser().parse_args(["sr1"]).port == 8177
    monkeypatch.setenv("STORY_SERVER_PORT", "9123")
    assert seam.build_parser().parse_args(["sr1"]).port == 9123
    assert seam.build_parser().parse_args(["sr1", "--port", "8188"]).port == 8188


def test_ct18_the_embed_port_and_a_bad_port_variable(ws, monkeypatch, capsys):
    _story(ws, _plan(), files=[("clips/panel_02.chainseed.png", SEED2, 2000)])
    embed = "Error: " + seam.EMBED % seam.EMBED_PORT + "\n"
    assert _run(["sr1", "--port", str(seam.EMBED_PORT)], capsys) == (2, "", embed)
    monkeypatch.setenv("STORY_SERVER_PORT", str(seam.EMBED_PORT))
    assert _run(["sr1"], capsys) == (2, "", embed)
    assert _run(["shots-or-not", "--port", str(seam.EMBED_PORT)], capsys) == (2, "", embed)
    monkeypatch.setenv("STORY_SERVER_PORT", "abc")
    with pytest.raises(SystemExit) as exit_info:
        seam.main(["sr1"])
    assert exit_info.value.code == 2
    assert capsys.readouterr().err.endswith(
        "seam-report: error: argument --port: 'abc' is not an integer (from --port or "
        "STORY_SERVER_PORT)\n")
    assert seam.build_parser().parse_args(["sr1", "--port", "8188"]).port == 8188


# --- CT19: the story server is down (CE13 steps 7, 8) --------------------------------------------

def test_ct19_server_down_at_the_probe(ws, monkeypatch, capsys, isolation):
    sdir = _story(ws, _plan(), files=[("clips/panel_02.chainseed.png", SEED2, 2000)])
    with open(os.path.join(sdir, "seam_report.json"), "wb") as f:
        f.write(b"an older report\n")
    monkeypatch.setattr(seam, "vlm_models", lambda port: (None, "ConnectionRefusedError"))
    assert _run(["sr1"], capsys) == (2, "", DOWN % ("ConnectionRefusedError", "sr1"))
    with open(os.path.join(sdir, "seam_report.json"), "rb") as f:
        assert f.read() == b"an older report\n"
    assert _reports(sdir) == ["seam_report.json"]
    assert os.listdir(isolation["temp"]) == []


def test_ct19_server_stops_while_checking(ws, monkeypatch, capsys, isolation):
    sdir = _story(ws, _plan(), files=[("clips/panel_02.chainseed.png", SEED2, 2000),
                                      ("clips/panel_03.chainseed.png", SEED3, 2000)])
    _ffmpeg(monkeypatch)
    fake = _vlm(monkeypatch, [_reply(8, "Fine."), seam.TransportError("HTTP 503")])
    assert _run(["sr1"], capsys) == (2, "", STOPPED % ("HTTP 503", 2, "sr1"))
    assert len(fake.calls) == 2
    assert _reports(sdir) == []
    assert os.listdir(isolation["temp"]) == []


def test_ct19_a_text_model_or_no_loaded_model_is_refused(ws, monkeypatch, capsys, isolation):
    sdir = _story(ws, _plan(), files=[("clips/panel_02.chainseed.png", SEED2, 2000)])
    made = _connection(monkeypatch, body=json.dumps(
        {"data": [{"id": seam.TEXT_MODEL_ID, "object": "model"}]}).encode("utf-8"))
    assert _run(["sr1"], capsys) == (2, "", "Error: " + seam.TEXT_SERVER % (
        8177, seam.TEXT_MODEL_ID, "sr1") + "\n")
    assert [(m["method"], m["path"]) for m in made] == [("GET", "/v1/models")]
    _connection(monkeypatch, body=b'{"data": [{"id": "/m/a", "loaded": false}, {"id": "/m/b"}]}')
    assert _run(["sr1"], capsys) == (2, "", DOWN % ("no model loaded", "sr1"))
    assert _reports(sdir) == []
    assert os.listdir(isolation["temp"]) == []


# --- CT20: verdicts and the report (CE13 steps 5, 8-10; CK6) ---------------------------------------

def _three_panel_story(ws):
    return _story(ws, _plan(), files=[("clips/panel_01.mp4", MP4, 1000),
                                      ("clips/panel_02.mp4", MP4, 1000),
                                      ("clips/panel_03.mp4", MP4, 1000),
                                      ("clips/panel_02.chainseed.png", SEED2, 2000),
                                      ("clips/panel_03.chainseed.png", SEED3, 2000)])


EXPECTED_MD = """# Seam report: sr1

Created 2026-10-31T12:00:00Z with test-vlm. A score below 6 is missed.

| Panel | Score | Verdict | Reason | Missing |
|---|---|---|---|---|
| 1 | 8 | ok | The courier stands at frame centre. | - |
| 2 | 5 | missed | The courier faces left, not right. | facing right; seen from the knees up |
| 3 | 6 | ok | Close to the plan. | the sealed letter |

Mean score 6.33 over 3 scored panel(s); 1 missed, 0 without a clip, 0 unparseable.

## Planned end frames

- panel 1: %s
- panel 2: %s
- panel 3: %s
""" % (E1, E2, E3)


def test_ct20_verdicts_sources_and_the_report(ws, monkeypatch, capsys):
    sdir = _three_panel_story(ws)
    clips = _ffmpeg(monkeypatch)
    fake = _vlm(monkeypatch, [
        _reply(8, "The courier stands at frame centre."),
        _reply(5, "The courier  faces left,\nnot right.", [" facing right ", "seen from the knees up", "  "]),
        _reply(6, "Close to the plan.", ["the sealed letter"])])
    rc, out, err = _run(["sr1"], capsys)
    json_path, md_path = (os.path.join(sdir, "seam_report.json"),
                          os.path.join(sdir, "seam_report.md"))
    assert (rc, err) == (0, "")
    assert out == (
        "panel 1: ok (8/10): The courier stands at frame centre.\n"
        "panel 2: missed (5/10): The courier faces left, not right.; missing: facing right; seen "
        "from the knees up\n"
        "panel 3: ok (6/10): Close to the plan.\n"
        "seam-report: wrote %s and %s: 1 of 3 panel(s) missed, mean score 6.33\n"
        % (json_path, md_path))
    assert clips == ["panel_03.mp4"]
    assert [c[3] for c in fake.calls] == [SEED2, SEED3, LAST_PNG]
    assert [(c[0], c[1]) for c in fake.calls] == [(8177, "test-vlm")] * 3
    assert fake.ports == [8177]
    with open(json_path, encoding="utf-8") as f:
        text = f.read()
    assert text == json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n"
    assert json.loads(text) == {
        "schema": "ltx-movie.seam-report.v1", "story_id": "sr1", "created": CREATED,
        "model": "test-vlm", "threshold": 6,
        "panels": [
            {"panel": 1, "end_frame": E1, "source": "chainseed",
             "frame": "clips/panel_02.chainseed.png", "score": 8, "verdict": "ok",
             "reason": "The courier stands at frame centre.", "missing": [], "attempts": 1},
            {"panel": 2, "end_frame": E2, "source": "chainseed",
             "frame": "clips/panel_03.chainseed.png", "score": 5, "verdict": "missed",
             "reason": "The courier faces left, not right.",
             "missing": ["facing right", "seen from the knees up"], "attempts": 1},
            {"panel": 3, "end_frame": E3, "source": "clip", "frame": "clips/panel_03.mp4",
             "score": 6, "verdict": "ok", "reason": "Close to the plan.",
             "missing": ["the sealed letter"], "attempts": 1}],
        "summary": {"panels": 3, "scored": 3, "ok": 2, "missed": 1, "no_clip": 0,
                    "unparseable": 0, "mean_score": 6.33}}
    with open(md_path, encoding="utf-8") as f:
        assert f.read() == EXPECTED_MD
    assert _reports(sdir) == ["seam_report.json", "seam_report.md"]


def test_ct20_stale_seeds_missing_clips_and_unreadable_clips(ws, monkeypatch, capsys):
    stale = _story(ws, _plan(frames=(E1, E2)), "stale", files=[
        ("clips/panel_01.mp4", MP4, 1000), ("clips/panel_02.chainseed.png", SEED2, 500),
        ("clips/panel_02.mp4", MP4, 1000)])
    assert [(k, s, os.path.basename(p)) for k, _e, s, p in
            seam.frame_sources(_plan(frames=(E1, E2)), os.path.join(stale, "clips"))] == [
        (1, "clip", "panel_01.mp4"), (2, "clip", "panel_02.mp4")]
    seeded = _story(ws, _plan(frames=(E1, E2)), "seeded", files=[
        ("clips/panel_02.chainseed.png", SEED2, 500), ("clips/panel_02.mp4", MP4, 1000)])
    assert [(k, s) for k, _e, s, _p in
            seam.frame_sources(_plan(frames=(E1, E2)), os.path.join(seeded, "clips"))] == [
        (1, "chainseed"), (2, "clip")]
    gap = _story(ws, _plan(frames=(E1, None, E3)), "gap", files=[("clips/panel_03.mp4", MP4, 1000)])
    _ffmpeg(monkeypatch)
    _vlm(monkeypatch, [_reply(7, "Good.")])
    rc, out, _err = _run(["gap"], capsys)
    doc = json.load(open(os.path.join(gap, "seam_report.json"), encoding="utf-8"))
    assert rc == 0
    assert [(p["panel"], p["source"], p["frame"], p["score"], p["verdict"], p["reason"],
             p["attempts"]) for p in doc["panels"]] == [
        (1, None, None, None, "no clip", "clips/panel_01.mp4 does not exist", 0),
        (3, "clip", "clips/panel_03.mp4", 7, "ok", "Good.", 1)]
    assert doc["summary"] == {"panels": 2, "scored": 1, "ok": 1, "missed": 0, "no_clip": 1,
                              "unparseable": 0, "mean_score": 7.0}
    assert out.startswith("panel 1: no clip: clips/panel_01.mp4 does not exist\n"
                          "panel 3: ok (7/10): Good.\n")
    broken = _story(ws, _plan(frames=(E1,)), "broken", files=[("clips/panel_01.mp4", MP4, 1000)])
    _ffmpeg(monkeypatch, fail="x")
    fake = _vlm(monkeypatch, [])
    rc, out, _err = _run(["broken"], capsys)
    doc = json.load(open(os.path.join(broken, "seam_report.json"), encoding="utf-8"))
    assert rc == 0 and fake.calls == []
    assert doc["panels"][0]["verdict"] == "no clip" and doc["panels"][0]["attempts"] == 0
    assert doc["panels"][0]["reason"] == "cannot read the last frame of clips/panel_01.mp4: x"
    assert doc["summary"]["mean_score"] is None
    assert out.endswith(": 0 of 1 panel(s) missed, mean score n/a\n")
    with open(os.path.join(broken, "seam_report.md"), encoding="utf-8") as f:
        md = f.read()
    assert "| 1 | - | no clip | cannot read the last frame of clips/panel_01.mp4: x | - |\n" in md
    assert "Mean score n/a over 0 scored panel(s); 0 missed, 1 without a clip, 0 unparseable." in md


def test_ct20_a_report_file_that_cannot_be_written(ws, monkeypatch, capsys):
    sdir = _story(ws, _plan(frames=(E1, E2)), files=[("clips/panel_02.chainseed.png", SEED2, 2000)])
    os.makedirs(os.path.join(sdir, "seam_report.json.tmp"))
    _vlm(monkeypatch, [_reply(9, "Fine.")])
    rc, out, err = _run(["sr1"], capsys)
    assert rc == 1 and out == ""
    assert err.startswith("Error: cannot write %s: " % os.path.join(sdir, "seam_report.json"))
    assert sorted(os.listdir(sdir)) == ["clips", "plan.json", "seam_report.json.tmp"]


def test_ct20_a_failed_write_leaves_the_old_pair_and_no_tmp_file(ws, monkeypatch, capsys):
    sdir = _story(ws, _plan(frames=(E1, E2)), files=[("clips/panel_02.chainseed.png", SEED2, 2000)])
    for name in ("seam_report.json", "seam_report.md"):
        with open(os.path.join(sdir, name), "wb") as f:
            f.write(b"old " + name.encode("ascii") + b"\n")
    os.makedirs(os.path.join(sdir, "seam_report.md.tmp"))
    _vlm(monkeypatch, [_reply(9, "Fine.")])
    rc, out, err = _run(["sr1"], capsys)
    assert rc == 1 and out == ""
    assert err.startswith("Error: cannot write %s: " % os.path.join(sdir, "seam_report.md"))
    assert sorted(os.listdir(sdir)) == ["clips", "plan.json", "seam_report.json", "seam_report.md",
                                        "seam_report.md.tmp"]
    os.rmdir(os.path.join(sdir, "seam_report.md.tmp"))
    os.remove(os.path.join(sdir, "seam_report.md"))
    os.makedirs(os.path.join(sdir, "seam_report.md"))
    _vlm(monkeypatch, [_reply(9, "Fine.")])
    rc, out, err = _run(["sr1"], capsys)
    assert rc == 1 and out == ""
    assert err.startswith("Error: cannot write %s: " % os.path.join(sdir, "seam_report.md"))
    assert sorted(os.listdir(sdir)) == ["clips", "plan.json", "seam_report.json", "seam_report.md"]
    with open(os.path.join(sdir, "seam_report.json"), "rb") as f:
        assert f.read() == b"old seam_report.json\n"


def test_ct20_an_unreadable_chainseed_is_no_clip(ws, monkeypatch, capsys):
    sdir = _story(ws, _plan(frames=(E1, E2)))
    gone = os.path.join(sdir, "clips", "panel_02.chainseed.png")
    monkeypatch.setattr(seam, "frame_sources", lambda plan, clips_dir: [(1, E1, "chainseed", gone)])
    fake = _vlm(monkeypatch, [])
    rc, out, _err = _run(["sr1"], capsys)
    assert rc == 0 and fake.calls == []
    with open(os.path.join(sdir, "seam_report.json"), encoding="utf-8") as f:
        panel = json.load(f)["panels"][0]
    assert (panel["source"], panel["frame"], panel["score"], panel["verdict"], panel["reason"],
            panel["attempts"]) == ("chainseed", "clips/panel_02.chainseed.png", None, "no clip",
                                   "cannot read clips/panel_02.chainseed.png: FileNotFoundError", 0)
    assert out.startswith("panel 1: no clip: cannot read clips/panel_02.chainseed.png: "
                          "FileNotFoundError\n")


def test_ct20_a_lone_surrogate_in_a_reply_is_a_failed_write(ws, monkeypatch, capsys):
    sdir = _story(ws, _plan(frames=(E1, E2)), files=[("clips/panel_02.chainseed.png", SEED2, 2000)])
    for name in ("seam_report.json", "seam_report.md"):
        with open(os.path.join(sdir, name), "wb") as f:
            f.write(b"old " + name.encode("ascii") + b"\n")
    _vlm(monkeypatch, [_reply(9, "bad \ud800 reason")])
    rc, out, err = _run(["sr1"], capsys)
    assert rc == 1 and out == ""
    assert err.startswith("Error: cannot write %s: 'utf-8' codec can't encode character '\\ud800'"
                          % os.path.join(sdir, "seam_report.json"))
    assert sorted(os.listdir(sdir)) == ["clips", "plan.json", "seam_report.json", "seam_report.md"]
    for name in ("seam_report.json", "seam_report.md"):
        with open(os.path.join(sdir, name), "rb") as f:
            assert f.read() == b"old " + name.encode("ascii") + b"\n"


# --- CT21: unparseable replies (CE13 step 8) ------------------------------------------------------

def _one_panel(ws, monkeypatch, replies, capsys):
    sdir = _story(ws, _plan(frames=(E1, E2)), files=[("clips/panel_02.chainseed.png", SEED2, 2000)])
    fake = _vlm(monkeypatch, replies)
    rc, _out, _err = _run(["sr1"], capsys)
    assert rc == 0
    with open(os.path.join(sdir, "seam_report.json"), encoding="utf-8") as f:
        panel = json.load(f)["panels"][0]
    shutil.rmtree(sdir)
    return panel, fake


def test_ct21_unparseable_replies_are_retried(ws, monkeypatch, capsys):
    panel, fake = _one_panel(ws, monkeypatch, ["garbage"] * 3, capsys)
    assert (panel["verdict"], panel["attempts"], panel["score"], panel["reason"],
            panel["missing"]) == ("unparseable", 3, None,
                                  "the model gave no valid reply in 3 attempts", [])
    assert len(fake.calls) == 3
    panel, _fake = _one_panel(ws, monkeypatch, ["garbage", _reply(7, "ok")], capsys)
    assert (panel["verdict"], panel["attempts"], panel["score"]) == ("ok", 2, 7)
    panel, _fake = _one_panel(ws, monkeypatch, [None, _reply(11, "x"), _reply(4, "Off.")], capsys)
    assert (panel["verdict"], panel["attempts"], panel["score"]) == ("missed", 3, 4)
    for content in (_reply(11, "x"), _reply(0, "x"), _reply(True, "x"), _reply(7.0, "x"),
                    _reply(7, " \n "), json.dumps({"score": 7, "reason": "x", "missing": "y"}),
                    json.dumps({"score": 7, "reason": "x", "missing": [1]}),
                    json.dumps({"score": 7, "missing": []}), "[1, 2]", "garbage"):
        assert seam.parse_reply(content) is None, content
    assert seam.parse_reply('<think>{"score": 1}</think>{"score": 7, "reason": "ok", '
                            '"missing": []}') == {"score": 7, "reason": "ok", "missing": []}
    assert seam.parse_reply('```json\n{"score": 3, "reason": " far \\n off ", '
                            '"missing": [" the quay ", ""]}\n```') == {
        "score": 3, "reason": "far off", "missing": ["the quay"]}


# --- CT22: the prompt and the request (CE13) -------------------------------------------------------

class FakeConnection(object):
    """http.client.HTTPConnection stand-in: records the request and answers status / body, or
    raises error from request()."""
    made = []
    status, body, error = 200, b"{}", None

    def __init__(self, host, port, timeout=None):
        self.record = {"host": host, "port": port, "timeout": timeout}
        FakeConnection.made.append(self.record)

    def request(self, method, path, body=None, headers=None):
        self.record.update(method=method, path=path, body=body, headers=headers)
        if FakeConnection.error is not None:
            raise FakeConnection.error

    def getresponse(self):
        record = self.record

        class Response(object):
            status = FakeConnection.status

            def read(self, n=None):
                record["read"] = n
                return FakeConnection.body
        return Response()

    def close(self):
        self.record["closed"] = True


def _connection(monkeypatch, status=200, body=b"{}", error=None):
    FakeConnection.made = []
    FakeConnection.status, FakeConnection.body, FakeConnection.error = status, body, error
    monkeypatch.setattr(http.client, "HTTPConnection", FakeConnection)
    return FakeConnection.made


def test_ct22_the_prompt(ws):
    plan = _plan(casts={2: ["c1", "c2"], 3: []})
    assert seam.seam_prompt(plan, 2) == (
        "This image is the last frame of panel 2 of a movie. The story plan says the panel ends "
        "on this frame:\n" + E2 + "\nCharacters in this panel: 'the courier' is " + COURIER
        + "; 'the old monk' is an old man in a robe.\nScore how well the image matches the "
        "planned end frame, from 1 (nothing matches) to 10 (everything matches). Judge only who "
        "or what is in frame, where each one is (left, centre or right; foreground or "
        "background), which way they face and how tight the shot is; ignore image quality, "
        "lighting, colour and style.\nReply with one JSON object only, with exactly these keys: "
        "score (an integer from 1 to 10), reason (one sentence of at most 25 words) and missing "
        "(a list of the short phrases of the planned end frame that the image does not show, or "
        "an empty list).")
    empty = seam.seam_prompt(plan, 3)
    assert "Characters in this panel" not in empty
    assert ("ends on this frame:\n" + E3 + "\n\nScore how well") in empty
    assert seam.seam_prompt(plan, 1).count("Characters in this panel: 'the courier' is ") == 1
    assert '"' not in seam.seam_prompt(plan, 2)


def test_ct22_the_requests(monkeypatch):
    made = _connection(monkeypatch, body=json.dumps(
        {"choices": [{"message": {"role": "assistant", "content": "a reply"}}]}).encode("utf-8"))
    assert seam.vlm_complete(8177, "test-vlm", "the prompt", b"PNGBYTES") == "a reply"
    record = made[0]
    assert (record["host"], record["port"], record["timeout"]) == ("127.0.0.1", 8177, 300)
    assert (record["method"], record["path"], record["read"], record["closed"]) == (
        "POST", "/v1/chat/completions", 1048576, True)
    body = json.loads(record["body"].decode("utf-8"))
    assert sorted(body) == ["chat_template_kwargs", "max_tokens", "messages", "model", "temperature"]
    assert (body["model"], body["max_tokens"], body["temperature"]) == ("test-vlm", 600, 0)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["messages"][0]["role"] == "user"
    text, image = body["messages"][0]["content"]
    assert text == {"type": "text", "text": "the prompt"}
    assert image["type"] == "image_url"
    assert image["image_url"]["url"] == "data:image/png;base64,UE5HQllURVM="
    for reply in (b"not json", json.dumps({"choices": []}).encode("utf-8"),
                  json.dumps({"choices": [{"message": {"content": None}}]}).encode("utf-8")):
        _connection(monkeypatch, body=reply)
        assert seam.vlm_complete(8177, "m", "p", b"x") is None, reply
    _connection(monkeypatch, status=503)
    with pytest.raises(seam.TransportError) as error:
        seam.vlm_complete(8177, "m", "p", b"x")
    assert str(error.value) == "HTTP 503"
    _connection(monkeypatch, error=ConnectionRefusedError(61, "refused"))
    with pytest.raises(seam.TransportError) as error:
        seam.vlm_complete(8177, "m", "p", b"x")
    assert str(error.value) == "ConnectionRefusedError"
    made = _connection(monkeypatch, body=b'{"object": "list", "data": [{"id": "mlx-vlm"}]}')
    assert seam.vlm_models(9001) == ("mlx-vlm", None)
    assert (made[0]["method"], made[0]["path"], made[0]["port"], made[0]["timeout"]) == (
        "GET", "/v1/models", 9001, 10)
    for status, body, what in ((500, b"{}", "HTTP 500"), (200, b"<html>", "invalid JSON"),
                               (200, b'{"data": []}', "no model listed"),
                               (200, b'{"data": [{"id": 5}]}', "no model listed"),
                               (200, b"[1]", "no model listed")):
        _connection(monkeypatch, status=status, body=body)
        assert seam.vlm_models(8177) == (None, what), body
    _connection(monkeypatch, error=http.client.RemoteDisconnected("gone"))
    assert seam.vlm_models(8177) == (None, "RemoteDisconnected")
    for body, expected in (
            (b'{"data": [{"id": "/m/cached", "loaded": false}, {"id": "/m/vl", "loaded": true}]}',
             ("/m/vl", None)),
            (b'{"data": [{"id": "/m/a", "loaded": true}, {"id": "/m/b", "loaded": true}]}',
             ("/m/a", None)),
            (b'{"data": [{"id": 5, "loaded": true}, {"id": "/m/b", "loaded": true}]}',
             ("/m/b", None)),
            (b'{"data": [{"id": "/m/a", "loaded": false}]}', (None, "no model loaded")),
            (b'{"data": [{"id": "/m/a", "loaded": "true"}, {"id": "/m/b"}]}',
             (None, "no model loaded")),
            (b'{"data": [{"id": "first"}, {"id": "second"}]}', ("first", None))):
        _connection(monkeypatch, body=body)
        assert seam.vlm_models(8177) == expected, body


# --- CT30: the script itself (CE13) ---------------------------------------------------------------

def test_ct30_executable_shebang_and_stdlib_imports():
    assert os.access(SEAM, os.X_OK)
    with open(SEAM, encoding="utf-8") as f:
        source = f.read()
    assert source.startswith("#!/usr/bin/env python3\n")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert imported == {"argparse", "base64", "http.client", "importlib.machinery", "json", "os",
                        "re", "shutil", "subprocess", "sys", "tempfile", "time"}
    assert seam.VERDICTS == ("ok", "missed", "no clip", "unparseable")
    assert (seam.SCHEMA, seam.MISS_BELOW, seam.ATTEMPTS, seam.MAX_TOKENS, seam.TEMPERATURE,
            seam.CALL_TIMEOUT_S, seam.MODELS_TIMEOUT_S, seam.MAX_BODY) == (
        "ltx-movie.seam-report.v1", 6, 3, 600, 0, 300, 10, 1048576)
    # The embed server's port is written as 8177 + 1 so the new tests never hold the literal
    # (plan Task 7 Step 7's check).
    assert (seam.EMBED_PORT, seam.TEXT_MODEL_ID) == (8177 + 1, "qwen38-6bit")


# --- Review Focus 1, 2 -----------------------------------------------------------------------------

def test_review_focus_1_pipes_line_breaks_and_accents_in_the_report(ws, monkeypatch, capsys):
    frame = "The café owner | the courier stand at frame centre — facing left, seen from the waist up."
    sdir = _story(ws, _plan(frames=(frame, E2)), files=[("clips/panel_02.chainseed.png", SEED2, 2000)])
    _vlm(monkeypatch, [_reply(4, "Left | right\nswapped — café", ["the | sign", "l’aube"])])
    rc, out, _err = _run(["sr1"], capsys)
    assert rc == 0
    with open(os.path.join(sdir, "seam_report.md"), encoding="utf-8") as f:
        md = f.read()
    assert ("| 1 | 4 | missed | Left \\| right swapped — café | the \\| sign; l’aube |\n") in md
    assert "- panel 1: " + frame + "\n" in md
    with open(os.path.join(sdir, "seam_report.json"), encoding="utf-8") as f:
        raw = f.read()
    assert "café" in raw and "l’aube" in raw and "\\u" not in raw
    assert json.loads(raw)["panels"][0]["end_frame"] == frame
    assert "panel 1: missed (4/10): Left | right swapped — café; missing: the | sign; l’aube\n" in out


def test_review_focus_2_an_empty_chainseed_never_stands_in_for_its_clip(ws, monkeypatch, capsys):
    sdir = _story(ws, _plan(frames=(E1, E2)), files=[
        ("clips/panel_01.mp4", MP4, 1000), ("clips/panel_02.chainseed.png", b"", 2000),
        ("clips/panel_02.mp4", MP4, 1000)])
    assert [(k, s) for k, _e, s, _p in
            seam.frame_sources(_plan(frames=(E1, E2)), os.path.join(sdir, "clips"))] == [
        (1, "clip"), (2, "clip")]
    clips = _ffmpeg(monkeypatch)
    fake = _vlm(monkeypatch, [_reply(9, "Fine."), _reply(9, "Fine.")])
    assert _run(["sr1"], capsys)[0] == 0
    assert clips == ["panel_01.mp4", "panel_02.mp4"]
    assert [c[3] for c in fake.calls] == [LAST_PNG, LAST_PNG]
