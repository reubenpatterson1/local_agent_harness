"""Tests for action_dataset.py (Phase 2 of the action-LoRA spec). Pure helpers run
anywhere; the normalization tests use ffmpeg on tiny synthetic clips and skip if
ffmpeg is unavailable."""

import importlib.machinery
import os
import subprocess

import pytest

HERE = os.path.dirname(os.path.realpath(__file__))
WS = os.path.dirname(HERE)
ad = importlib.machinery.SourceFileLoader(
    "action_dataset", os.path.join(WS, "action_dataset.py")).load_module()
al = importlib.machinery.SourceFileLoader(
    "action_lib", os.path.join(WS, "action_lib.py")).load_module()

_HAVE_FFMPEG = os.path.exists(ad.FFMPEG) and os.path.exists(ad.FFPROBE)
needs_ffmpeg = pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg/ffprobe not available")

DESC = "a spinning kick delivered with the rear leg to head height in one motion"


# ---- pure helpers (no ffmpeg) --------------------------------------------------
def test_snap_frames():
    assert ad.snap_frames(1) == 9          # floor is 9
    assert ad.snap_frames(24) == 17        # largest 8k+1 <= 24
    assert ad.snap_frames(97) == 97
    assert ad.snap_frames(300) == 241 or ad.snap_frames(300) == 297  # just the lattice, uncapped here


def test_validate_geometry():
    ad.validate_geometry(768, 768, 97)     # ok
    for w, h, f in [(700, 768, 97), (768, 700, 97), (768, 768, 50), (32, 64, 9)]:
        with pytest.raises(ad.DatasetError):
            ad.validate_geometry(w, h, f)


# ---- ffmpeg-backed clip pipeline ----------------------------------------------
def _make_clip(path, color="red", size="100x80", dur=1):
    subprocess.run([ad.FFMPEG, "-y", "-f", "lavfi", "-i",
                    "color=c=%s:s=%s:d=%d" % (color, size, dur), "-r", "24", path],
                   capture_output=True, check=True)


@needs_ffmpeg
def test_build_dataset_normalizes_and_writes(tmp_path, monkeypatch):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    clips = []
    for i, c in enumerate(("red", "green", "blue")):
        p = str(tmp_path / ("ref_%d.mp4" % i)); _make_clip(p, color=c); clips.append(p)
    data = ad.build_dataset("roundhouse-kick", "performs a roundhouse kick", DESC, clips,
                            performers=3, width=64, height=64, frames=9)
    # action.json is valid and records the dataset + identity-agnostic result
    al.validate_action(data)
    assert data["status"] == "dataset" and data["identity_agnostic"] is True
    assert data["dataset"]["clips"] == 3 and data["dataset"]["width"] == 64
    # normalized clips exist at the target geometry; captions are the trigger only
    base = al.action_dir("roundhouse-kick")
    for i in range(3):
        clip = os.path.join(base, "dataset", "clips", "clip_%02d.mp4" % i)
        assert os.path.isfile(clip)
        w, h, nb, dur = ad.probe_clip(clip)
        assert (w, h) == (64, 64)
        cap = open(os.path.join(base, "dataset", "captions", "clip_%02d.txt" % i)).read()
        assert cap == "performs a roundhouse kick"
    assert os.path.isfile(os.path.join(base, "dataset", "contact_sheet.jpg"))
    # it round-trips through the library
    assert al.load_action("roundhouse-kick") == data


@needs_ffmpeg
def test_identity_agnostic_gate(tmp_path, monkeypatch):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    p = str(tmp_path / "ref.mp4"); _make_clip(p)
    # < 3 performers without --force is refused
    with pytest.raises(ad.DatasetError):
        ad.build_dataset("solo-move", "does a solo move", DESC, [p], performers=1,
                         width=64, height=64, frames=9)
    # with force it proceeds but records identity_agnostic=false
    data = ad.build_dataset("solo-move", "does a solo move", DESC, [p], performers=1,
                            width=64, height=64, frames=9, force=True)
    assert data["identity_agnostic"] is False


@needs_ffmpeg
def test_create_exit_3_when_too_few_clips(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    clips = []
    for i, c in enumerate(("red", "green", "blue")):
        p = str(tmp_path / ("r_%d.mp4" % i)); _make_clip(p, color=c); clips.append(p)
    rc = ad.main(["create", "shortset", "--trigger", "does a thing",
                  "--descriptor", DESC, "--performers", "3",
                  "--width", "64", "--height", "64", "--frames", "9"]
                 + sum([["--clip", c] for c in clips], []))
    assert rc == 3  # 3 clips < MIN_CLIPS (8): dataset kept, exit 3
    assert al.load_action("shortset")["dataset"]["clips"] == 3


def test_bad_geometry_rejected_before_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    with pytest.raises(ad.DatasetError):
        ad.build_dataset("test-move", "does a thing", DESC, ["/nope.mp4"], performers=3,
                         width=700, height=768, frames=97)
