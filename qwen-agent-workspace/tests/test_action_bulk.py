"""Tests for bulk action-LoRA clip loading (docs/superpowers/specs/2026-11-23-bulk-action-clips-design.md,
Section 6.1: BKT1-BKT12, plus the plan's Review Focus 1 and 2): the file-name grammar, the folder
scan, folder captions in build_dataset, the contact-sheet sample, the scaled disk check, stale-clip
cleanup, create --dir, bin/action scan and the scaled preprocess timeout.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_action_bulk.py
Stdlib, PIL (through action_dataset) and pytest. The ffmpeg tests build tiny synthetic clips and skip
when ffmpeg is missing; the others fake probe/normalize/extract-frame. Every folder and library is
under tmp_path.
"""

import importlib.machinery
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.realpath(__file__))
WS = os.path.dirname(HERE)
ad = importlib.machinery.SourceFileLoader(
    "action_dataset", os.path.join(WS, "action_dataset.py")).load_module()
al = importlib.machinery.SourceFileLoader(
    "action_lib", os.path.join(WS, "action_lib.py")).load_module()

_HAVE_FFMPEG = os.path.exists(ad.FFMPEG) and os.path.exists(ad.FFPROBE)
needs_ffmpeg = pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg/ffprobe not available")
PY39 = "/usr/bin/python3"

DESC = "a spinning kick delivered with the rear leg to head height in one motion"
TRIGGER = "performs a fight combo"
VIDEO_REASON = "not a video (.mp4, .mov, .m4v, .webm, .mkv)"
NO_MATCH = "name does not match <n>_<n>_<moves>.<ext>"
MANIFEST_KEYS = ["name", "trigger", "descriptor", "clips", "performers", "identity_agnostic", "width",
                 "height", "frames", "fps", "sources", "items", "source_dir", "skipped", "contact_sheet_clips"]

MATCHING = [
    ("006_00_high_kick-stance-front_kick.mp4", ["high kick", "stance", "front kick"]),
    ("005_01_punch-stance-high_kick.mp4", ["punch", "stance", "high kick"]),
    ("6_0_Kick.MP4", ["kick"]),
    ("010_02_jab-jab.mov", ["jab", "jab"]),
    ("007_00_spinning__back_kick.mp4", ["spinning back kick"]),
    ("007_00__kick_.mp4", ["kick"]),
]
NON_MATCHING = [
    ("notes.txt", VIDEO_REASON),
    ("006_00_kick.mp4.part", VIDEO_REASON),
    ("kick.mp4", NO_MATCH),
    ("006_kick.mp4", NO_MATCH),
    ("006_00_.mp4", NO_MATCH),
    ("006_00_kick kick.mp4", NO_MATCH),
    ("006_00_kíck.mp4", NO_MATCH),
    ("006_00_punch--kick.mp4", "empty move"),
    ("006_00_-kick.mp4", "empty move"),
    ("006_00_" + "a" * 41 + ".mp4", "move longer than 40 characters"),
    ("006_00_1st_kick.mp4", "move '1st kick' must start with a letter"),
    ("006_00_a-b-c-d-e-f-g-h-i.mp4", "more than 8 moves"),
    (".006_00_kick.mp4", "hidden file"),
    ("._006_00_kick.mp4", "hidden file"),
]


def _make_clip(path, color="red", size="100x80", dur=1):
    subprocess.run([ad.FFMPEG, "-y", "-f", "lavfi", "-i",
                    "color=c=%s:s=%s:d=%d" % (color, size, dur), "-r", "24", path],
                   capture_output=True, check=True)


def _touch(path):
    with open(path, "wb"):
        pass


def _folder(tmp_path, names):
    """<tmp>/clips (a realpath) holding a zero-byte file for each name."""
    d = os.path.join(os.path.realpath(str(tmp_path)), "clips")
    os.makedirs(d)
    for name in names:
        _touch(os.path.join(d, name))
    return d


def _clips(tmp_path, n):
    paths = []
    for i, color in enumerate(("red", "green", "blue")[:n]):
        p = os.path.join(os.path.realpath(str(tmp_path)), "ref_%d.mp4" % i)
        _make_clip(p, color=color)
        paths.append(p)
    return paths


def _read(path, mode="r"):
    with open(path, mode) as f:
        return f.read()


def _manifest(name):
    with open(os.path.join(al.action_dir(name), "dataset", "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def _fake_ffmpeg(monkeypatch, extracted=None):
    """probe/normalize/extract-frame without ffmpeg: every clip is 24 frames, normalize writes a
    4-byte file, and extract-frame records the clip and fails (so the sheet is the placeholder)."""
    def probe(path):
        return 64, 64, 24, 1.0

    def normalize(src, dst, width, height, frames, fps=24):
        with open(dst, "wb") as f:
            f.write(b"clip")

    def extract(clip, dst_png, at_frac=0.5):
        if extracted is not None:
            extracted.append(os.path.basename(clip))
        raise ad.DatasetError("no frame in a fake clip")

    monkeypatch.setattr(ad, "probe_clip", probe)
    monkeypatch.setattr(ad, "normalize_clip", normalize)
    monkeypatch.setattr(ad, "extract_frame", extract)


def _main_create(*extra):
    return ad.main(["create", "combo-set", "--trigger", TRIGGER, "--descriptor", DESC] + list(extra))


def _bin_action():
    loader = importlib.machinery.SourceFileLoader("bin_action_for_bulk", os.path.join(WS, "bin", "action"))
    spec = importlib.util.spec_from_loader("bin_action_for_bulk", loader)
    tool = importlib.util.module_from_spec(spec)
    loader.exec_module(tool)
    return tool


def _scan(lib_dir, *args, python=None):
    env = dict(os.environ, ACTION_LIBRARY_DIR=lib_dir, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([python or sys.executable, os.path.join(WS, "bin", "action"), "scan"] + list(args),
                          capture_output=True, text=True, timeout=60, env=env)


def _snapshot(d):
    entries = []
    for name in sorted(os.listdir(d)):
        st = os.stat(os.path.join(d, name))
        entries.append((name, st.st_size, st.st_mtime_ns))
    return entries, os.stat(d).st_mtime_ns


# ---- copied from tests/test_action_train.py (the stub ltx-2-mlx) -------------------------------
_STUB = r"""#!/bin/bash
cmd="$1"; shift
if [ "$cmd" = "preprocess" ]; then
  videos=""; out=""
  while [ $# -gt 0 ]; do case "$1" in
    --videos|-v) videos="$2"; shift 2;;
    -o|--output) out="$2"; shift 2;;
    *) shift;; esac; done
  mkdir -p "$out/.precomputed/latents"
  i=0; for f in "$videos"/*.mp4; do touch "$out/.precomputed/latents/lat_$i.pt"; i=$((i+1)); done
elif [ "$cmd" = "train" ]; then
  cfg=""
  while [ $# -gt 0 ]; do case "$1" in --config|-c) cfg="$2"; shift 2;; *) shift;; esac; done
  outdir=$(grep '^output_dir:' "$cfg" | sed 's/output_dir: *//' | tr -d '"')
  mkdir -p "$outdir/checkpoints"
  echo "fake-lora-weights" > "$outdir/checkpoints/lora_weights_step_01000.safetensors"
fi
exit 0
"""


def _seed_action(lib_dir, name="roundhouse", clips=8):
    os.environ[al.LIBRARY_ENV] = str(lib_dir)
    os.makedirs(al.action_dir(name))
    cdir = os.path.join(al.action_dir(name), "dataset", "clips"); os.makedirs(cdir)
    pdir = os.path.join(al.action_dir(name), "dataset", "captions"); os.makedirs(pdir)
    for i in range(clips):
        open(os.path.join(cdir, "clip_%02d.mp4" % i), "w").write("x")
        open(os.path.join(pdir, "clip_%02d.txt" % i), "w").write("performs a roundhouse kick")
    data = al.new_action(name, "performs a roundhouse kick", DESC, ["/abs/ref0.mp4"], identity_agnostic=True)
    data["dataset"] = {"clips": clips, "performers": 3, "width": 64, "height": 64,
                       "frames": 9, "fps": 24, "contact_sheet": "x"}
    al.write_action(data)
    return name


def _install_stub(tmp_path, monkeypatch):
    stub = tmp_path / "ltx-2-mlx"
    stub.write_text(_STUB)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXUSR)
    model = tmp_path / "trainmodel"; model.mkdir()
    monkeypatch.setattr(ad, "LTX2_MLX_BIN", str(stub))
    monkeypatch.setattr(ad, "TRAIN_MODEL", str(model))
    monkeypatch.setattr(ad, "LTX2_MLX_DIR", str(tmp_path))
    monkeypatch.setattr(ad, "LTX2_MLX_HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setattr(ad, "busy_process", lambda: None)
    monkeypatch.setattr(ad, "story_server_state", lambda: "STOPPED")


# ---- BKT1-BKT4: the grammar, the scan, the caption ---------------------------------------------

def test_bkt1_matching_names():
    for name, moves in MATCHING:
        assert al.parse_clip_name(name) == (moves, None), name
    assert al.parse_clip_name("006_00_" + "a" * 40 + ".mp4") == (["a" * 40], None)
    assert al.parse_clip_name("006_00_a-b-c-d-e-f-g-h.mp4") == (list("abcdefgh"), None)


def test_bkt2_non_matching_names():
    for name, reason in NON_MATCHING:
        assert al.parse_clip_name(name) == (None, reason), name


def test_bkt3_scan_clip_dir(tmp_path, monkeypatch):
    root = os.path.realpath(str(tmp_path))
    d = _folder(tmp_path, ["9_00_kick.mp4", "10_00_punch-kick.mp4", "006_00_high_kick-stance-front_kick.mp4",
                           "notes.txt", ".006_00_kick.mp4", "011_00_jab.mp4"])
    os.makedirs(os.path.join(d, "sub"))
    _touch(os.path.join(d, "sub", "001_00_kick.mp4"))
    locked = os.path.join(d, "011_00_jab.mp4")
    os.chmod(locked, 0)
    try:
        scan = al.scan_clip_dir(d)
        as_root = os.geteuid() == 0
        names = ["006_00_high_kick-stance-front_kick.mp4", "9_00_kick.mp4", "10_00_punch-kick.mp4"]
        if as_root:
            names.append("011_00_jab.mp4")
        assert scan["dir"] == d
        assert [c["name"] for c in scan["clips"]] == names
        assert scan["clips"][0] == {"name": names[0], "path": os.path.join(d, names[0]),
                                    "moves": ["high kick", "stance", "front kick"]}
        assert scan["clips"][2] == {"name": "10_00_punch-kick.mp4", "path": os.path.join(d, "10_00_punch-kick.mp4"),
                                    "moves": ["punch", "kick"]}
        skipped = [{"name": ".006_00_kick.mp4", "reason": "hidden file"}]
        if not as_root:
            skipped.append({"name": "011_00_jab.mp4", "reason": "not readable"})
        skipped += [{"name": "notes.txt", "reason": VIDEO_REASON}, {"name": "sub", "reason": "folder (not scanned)"}]
        assert scan["skipped"] == skipped
        monkeypatch.chdir(root)
        assert al.scan_clip_dir("clips") == scan
    finally:
        os.chmod(locked, 0o644)
    for bad in (os.path.join(d, "notes.txt"), os.path.join(root, "missing")):
        with pytest.raises(al.ActionError, match="^folder %s is not a readable directory$" % re.escape(bad)):
            al.scan_clip_dir(bad)


def test_bkt4_clip_caption():
    assert al.clip_caption(TRIGGER, ["kick"]) == "performs a fight combo: kick"
    assert al.clip_caption(TRIGGER, ["high kick", "stance", "front kick"]) == (
        "performs a fight combo: high kick, then stance, then front kick")


# ---- BKT5-BKT9: build_dataset ------------------------------------------------------------------

@needs_ffmpeg
def test_bkt5_captions_on_disk_and_the_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    clips = _clips(tmp_path, 3)
    captions = ["t: a", "t: b, then c", "t: d"]
    skipped = [{"name": "n.txt", "reason": "r"}]
    ad.build_dataset("combo-set", TRIGGER, DESC, clips, performers=3, width=64, height=64, frames=9,
                     captions=captions, source_dir="/x", skipped=skipped)
    base = os.path.join(al.action_dir("combo-set"), "dataset")
    for i, caption in enumerate(captions):
        assert _read(os.path.join(base, "captions", "clip_%02d.txt" % i), "rb") == caption.encode("utf-8")
    manifest = _manifest("combo-set")
    assert list(manifest) == MANIFEST_KEYS
    assert manifest["sources"] == clips
    assert manifest["items"] == [{"clip": "clip_%02d.mp4" % i, "source": clips[i], "caption": captions[i]}
                                 for i in range(3)]
    assert manifest["source_dir"] == "/x"
    assert manifest["skipped"] == skipped
    assert manifest["contact_sheet_clips"] == [0, 1, 2]


def test_bkt5_caption_errors_come_before_any_file(tmp_path, monkeypatch):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    paths = ["/nope/a.mp4", "/nope/b.mp4", "/nope/c.mp4"]
    with pytest.raises(ad.DatasetError, match=r"^captions: 2 given for 3 clips$"):
        ad.build_dataset("combo-bad", TRIGGER, DESC, paths, performers=3, width=64, height=64, frames=9,
                         captions=["t: a", "t: b"])
    with pytest.raises(ad.DatasetError, match=r"^captions: -1 given for 3 clips$"):
        ad.build_dataset("combo-bad", TRIGGER, DESC, paths, performers=3, width=64, height=64, frames=9,
                         captions="t: a")
    for bad in ("", "   ", "a\nb", "a\rb", None):
        with pytest.raises(ad.DatasetError, match=r"^captions: caption 1 must be one non-empty line$"):
            ad.build_dataset("combo-bad", TRIGGER, DESC, paths, performers=3, width=64, height=64, frames=9,
                             captions=["t: a", bad, "t: d"])
    assert not os.path.exists(al.action_dir("combo-bad"))


@needs_ffmpeg
def test_bkt6_the_single_trigger_path_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    clips = _clips(tmp_path, 3)
    data = ad.build_dataset("roundhouse-kick", "performs a roundhouse kick", DESC, clips,
                            performers=3, width=64, height=64, frames=9)
    al.validate_action(data)
    assert data["status"] == "dataset" and data["identity_agnostic"] is True
    assert data["dataset"]["clips"] == 3 and data["dataset"]["width"] == 64
    assert list(data["dataset"]) == ["clips", "performers", "width", "height", "frames", "fps", "contact_sheet"]
    assert data["source"] == {"type": "clips", "paths": clips}
    base = os.path.join(al.action_dir("roundhouse-kick"), "dataset")
    for i in range(3):
        assert _read(os.path.join(base, "captions", "clip_%02d.txt" % i), "rb") == b"performs a roundhouse kick"
    manifest = _manifest("roundhouse-kick")
    assert list(manifest) == MANIFEST_KEYS
    assert [item["caption"] for item in manifest["items"]] == ["performs a roundhouse kick"] * 3
    assert manifest["source_dir"] is None and manifest["skipped"] == []
    assert al.load_action("roundhouse-kick") == data


def test_bkt7_contact_sample():
    assert ad.CONTACT_MAX == 48
    assert ad.contact_sample(0) == []
    assert ad.contact_sample(5) == [0, 1, 2, 3, 4]
    assert ad.contact_sample(48) == list(range(48))
    for n in (49, 1000):
        sample = ad.contact_sample(n)
        assert len(sample) == 48 and len(set(sample)) == 48 and sample == sorted(sample), n
        assert sample[0] == 0 and sample[-1] == n - 1, n


def test_bkt7_only_sampled_clips_reach_the_sheet(tmp_path, monkeypatch):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    extracted = []
    _fake_ffmpeg(monkeypatch, extracted)
    d = _folder(tmp_path, ["src_%02d.mp4" % i for i in range(50)])
    paths = [os.path.join(d, "src_%02d.mp4" % i) for i in range(50)]
    ad.build_dataset("sample-set", TRIGGER, DESC, paths, performers=3, width=64, height=64, frames=9)
    assert extracted == ["clip_%02d.mp4" % i for i in ad.contact_sample(50)]
    assert _manifest("sample-set")["contact_sheet_clips"] == ad.contact_sample(50)


@needs_ffmpeg
def test_bkt8_a_rebuild_removes_stale_clips(tmp_path, monkeypatch):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    clips = _clips(tmp_path, 3)
    ad.build_dataset("stale-set", TRIGGER, DESC, clips, performers=3, width=64, height=64, frames=9)
    base = os.path.join(al.action_dir("stale-set"), "dataset")
    _touch(os.path.join(base, "clips", "keep.md"))
    ad.build_dataset("stale-set", TRIGGER, DESC, clips[:2], performers=3, width=64, height=64, frames=9)
    assert sorted(os.listdir(os.path.join(base, "clips"))) == ["clip_00.mp4", "clip_01.mp4", "keep.md"]
    assert sorted(os.listdir(os.path.join(base, "captions"))) == ["clip_00.txt", "clip_01.txt"]


def test_bkt9_disk_scaling(tmp_path, monkeypatch):
    assert ad.CREATE_PER_CLIP_GIB == 0.005
    assert ad.create_min_free_gib(0) == pytest.approx(2.0)
    assert ad.create_min_free_gib(100) == pytest.approx(2.5)
    assert ad.create_min_free_gib(1000) == pytest.approx(7.0)
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    monkeypatch.setattr(ad, "_free_gib", lambda p: 2.01)
    d = _folder(tmp_path, ["z_0.mp4", "z_1.mp4", "z_2.mp4"])
    paths = [os.path.join(d, "z_%d.mp4" % i) for i in range(3)]
    with pytest.raises(ad.DatasetError) as e:
        ad.build_dataset("disk-set", TRIGGER, DESC, paths, performers=3, width=64, height=64, frames=9)
    message = str(e.value)
    assert message.startswith("less than 2.0 GiB free at ") and message.endswith("(needed for 3 clips)")
    assert message == "less than 2.0 GiB free at %s (needed for 3 clips)" % al.action_dir("disk-set")
    assert os.listdir(os.path.join(al.action_dir("disk-set"), "dataset", "clips")) == []


# ---- BKT10-BKT12: create --dir, bin/action scan, the preprocess timeout -----------------------

def test_bkt10_create_dir_argument_rules(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    d = _folder(tmp_path, ["notes.txt"])
    assert _main_create("--dir", d, "--clip", "/abs/a.mp4") == 2
    assert capsys.readouterr().err == "Error: give either --dir or --clip, not both\n"
    assert _main_create() == 2
    assert capsys.readouterr().err == (
        "Error: create needs --trigger, --descriptor and --dir or at least one --clip\n")
    assert _main_create("--dir", d) == 2
    out = capsys.readouterr()
    assert out.out == "skipped: notes.txt (%s)\nfolder: 0 clip(s) matched, 1 skipped in %s\n" % (VIDEO_REASON, d)
    assert out.err == "Error: no file in %s matches <n>_<n>_<moves>.<ext>\n" % d
    missing = os.path.join(os.path.realpath(str(tmp_path)), "missing")
    assert _main_create("--dir", missing) == 2
    assert capsys.readouterr().err == "Error: folder %s is not a readable directory\n" % missing
    assert _main_create("--dir", d, "--trigger", "bad:trigger") == 2
    assert capsys.readouterr().err.startswith("Error: trigger: ")
    assert not os.path.exists(al.action_dir("combo-set"))


@needs_ffmpeg
def test_bkt10_create_dir_captions_each_clip_from_its_name(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    d = _folder(tmp_path, ["notes.txt"])
    names = ["001_00_kick.mp4", "002_00_punch-kick.mp4", "003_00_high_kick-stance.mp4"]
    for name, color in zip(names, ("red", "green", "blue")):
        _make_clip(os.path.join(d, name), color=color)
    rc = _main_create("--dir", d, "--width", "64", "--height", "64", "--frames", "9", "--performers", "3")
    out = capsys.readouterr()
    assert rc == 3, out.err
    assert "skipped: notes.txt (%s)\n" % VIDEO_REASON in out.out
    assert "folder: 3 clip(s) matched, 1 skipped in %s\n" % d in out.out
    assert "clip 1/3: 001_00_kick.mp4\n" in out.out and "clip 3/3: 003_00_high_kick-stance.mp4\n" in out.out
    assert "add more clips and run bin/action create combo-set --regenerate." in out.err
    base = os.path.join(al.action_dir("combo-set"), "dataset")
    captions = [al.clip_caption(TRIGGER, moves) for moves in (["kick"], ["punch", "kick"], ["high kick", "stance"])]
    for i, caption in enumerate(captions):
        assert _read(os.path.join(base, "captions", "clip_%02d.txt" % i)) == caption
    manifest = _manifest("combo-set")
    assert manifest["source_dir"] == d
    assert manifest["skipped"] == [{"name": "notes.txt", "reason": VIDEO_REASON}]
    assert [item["source"] for item in manifest["items"]] == [os.path.join(d, n) for n in names]
    assert [item["caption"] for item in manifest["items"]] == captions
    assert al.load_action("combo-set")["source"]["paths"] == [os.path.join(d, n) for n in names]


def test_bkt10_the_folder_clip_cap(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    monkeypatch.setattr(ad, "_load_action_lib", lambda: al)
    monkeypatch.setattr(al, "MAX_DIR_CLIPS", 2)
    d = _folder(tmp_path, ["001_00_kick.mp4", "002_00_kick.mp4", "003_00_kick.mp4"])
    assert _main_create("--dir", d) == 2
    assert capsys.readouterr().err == "Error: %s has 3 matching clips; an action takes at most 2\n" % d
    assert not os.path.exists(al.action_dir("combo-set"))


def test_bkt10_both_parsers_take_dir():
    argv = ["create", "x", "--trigger", "t", "--descriptor", "d", "--dir", "/tmp"]
    for parser in (_bin_action().build_parser(), ad.build_parser()):
        args = parser.parse_args(argv)
        assert args.dir == "/tmp" and args.clips == []
    args = _bin_action().build_parser().parse_args(["scan", "/tmp"])
    assert (args.command, args.dir, args.trigger) == ("scan", "/tmp", None)


def test_bkt11_bin_action_scan_is_read_only_json(tmp_path):
    lib_dir = os.path.join(os.path.realpath(str(tmp_path)), "lib")
    d = _folder(tmp_path, ["006_00_high_kick-stance-front_kick.mp4", "9_00_kick.mp4", "notes.txt"])
    before = _snapshot(d)
    run = _scan(lib_dir, d, "--trigger", TRIGGER)
    assert run.returncode == 0, run.stderr
    data = json.loads(run.stdout)
    assert list(data) == ["dir", "matched", "max", "clips", "skipped"]
    assert (data["dir"], data["matched"], data["max"]) == (d, 2, 1000)
    assert data["clips"] == [
        {"name": "006_00_high_kick-stance-front_kick.mp4",
         "path": os.path.join(d, "006_00_high_kick-stance-front_kick.mp4"),
         "moves": ["high kick", "stance", "front kick"],
         "caption": "performs a fight combo: high kick, then stance, then front kick"},
        {"name": "9_00_kick.mp4", "path": os.path.join(d, "9_00_kick.mp4"), "moves": ["kick"],
         "caption": "performs a fight combo: kick"}]
    assert data["skipped"] == [{"name": "notes.txt", "reason": VIDEO_REASON}]
    run = _scan(lib_dir, d)
    assert run.returncode == 0, run.stderr
    assert [c["caption"] for c in json.loads(run.stdout)["clips"]] == [None, None]
    run = _scan(lib_dir, d, "--trigger", "bad:trigger")
    assert run.returncode == 2 and run.stdout == "" and run.stderr.startswith("Error: trigger:")
    missing = os.path.join(os.path.realpath(str(tmp_path)), "missing")
    run = _scan(lib_dir, missing)
    assert (run.returncode, run.stderr) == (2, "Error: folder %s is not a readable directory\n" % missing)
    assert _snapshot(d) == before
    assert not os.path.exists(lib_dir)


def test_bkt12_preprocess_timeout_scales(tmp_path, monkeypatch):
    assert [ad.preprocess_timeout_s(n) for n in (8, 80, 300, 1000)] == [1800, 1800, 5100, 15600]
    _install_stub(tmp_path, monkeypatch)
    seen = []
    real_run = ad._run_logged

    def recording(cmd, log_path, cwd, env, timeout_s):
        seen.append((os.path.basename(log_path), timeout_s))
        return real_run(cmd, log_path, cwd, env, timeout_s)

    monkeypatch.setattr(ad, "_run_logged", recording)
    for clips, lib_name, expected in ((8, "lib8", 1800), (100, "lib100", 2100)):
        monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / lib_name))
        name = _seed_action(tmp_path / lib_name, clips=clips)
        del seen[:]
        data, _lora = ad.train_action(name)
        assert data["status"] == "trained"
        assert seen == [("preprocess.log", expected), ("train.log", 14400)], clips


# ---- Review Focus 1 and 2 --------------------------------------------------------------------

def test_bk_review_focus_1_numeric_order_keeps_each_caption_with_its_clip(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    _fake_ffmpeg(monkeypatch)
    d = _folder(tmp_path, ["100_00_jab-jab.mp4", "10_00_punch.mp4", "9_00_kick.mp4", "9_01_front_kick.mp4"])
    assert _main_create("--dir", d, "--performers", "3") == 3
    order = ["9_00_kick.mp4", "9_01_front_kick.mp4", "10_00_punch.mp4", "100_00_jab-jab.mp4"]
    captions = [al.clip_caption(TRIGGER, m) for m in (["kick"], ["front kick"], ["punch"], ["jab", "jab"])]
    out = capsys.readouterr().out
    assert [line for line in out.splitlines() if line.startswith("clip ")] == [
        "clip %d/4: %s" % (i + 1, n) for i, n in enumerate(order)]
    base = os.path.join(al.action_dir("combo-set"), "dataset")
    for i, caption in enumerate(captions):
        assert _read(os.path.join(base, "captions", "clip_%02d.txt" % i)) == caption
    assert [(os.path.basename(item["source"]), item["caption"]) for item in _manifest("combo-set")["items"]] == (
        list(zip(order, captions)))
    assert al.load_action("combo-set")["source"]["paths"] == [os.path.join(d, n) for n in order]


@pytest.mark.skipif(not os.path.isfile(PY39), reason="/usr/bin/python3 is not installed")
def test_bk_review_focus_2_python_39_runs_scan_and_compiles_the_files(tmp_path):
    lib_dir = os.path.join(os.path.realpath(str(tmp_path)), "lib")
    d = _folder(tmp_path, ["9_00_kick.mp4", "10_00_punch-kick.mp4", "notes.txt"])
    runs = [_scan(lib_dir, d, "--trigger", TRIGGER, python=py) for py in (PY39, sys.executable)]
    assert [r.returncode for r in runs] == [0, 0], [r.stderr for r in runs]
    assert runs[0].stdout == runs[1].stdout
    script = ("import py_compile, sys\n"
              "for k, path in enumerate(sys.argv[2:]):\n"
              "    py_compile.compile(path, cfile=sys.argv[1] + '/%d.pyc' % k, doraise=True)\n")
    files = [os.path.join(WS, rel) for rel in ("action_lib.py", "action_dataset.py", os.path.join("bin", "action"))]
    proc = subprocess.run([PY39, "-c", script, str(tmp_path)] + files, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
