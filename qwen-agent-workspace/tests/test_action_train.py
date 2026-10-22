"""Tests for action_dataset training (Phase 3). A stub ltx-2-mlx binary stands in
for preprocess/train so the orchestration (config, argv, latent check, checkpoint
-> library record, status) is exercised without a GPU, dev model or real training.
Plus pure config/argv builders."""

import importlib.machinery
import os
import stat

import pytest

HERE = os.path.dirname(os.path.realpath(__file__))
WS = os.path.dirname(HERE)
ad = importlib.machinery.SourceFileLoader(
    "action_dataset", os.path.join(WS, "action_dataset.py")).load_module()
al = importlib.machinery.SourceFileLoader(
    "action_lib", os.path.join(WS, "action_lib.py")).load_module()

DESC = "a spinning kick delivered with the rear leg to head height in one motion"
TRIGGER = "performs a roundhouse kick"

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
        open(os.path.join(pdir, "clip_%02d.txt" % i), "w").write(TRIGGER)
    data = al.new_action(name, TRIGGER, DESC, ["/abs/ref0.mp4"], identity_agnostic=True)
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


# ---- pure builders -------------------------------------------------------------
def test_train_config_has_action_geometry_and_trigger():
    cfg = ad.train_config("/data", TRIGGER, "/out", 1344, 768, 97, rank=16, steps=800)
    assert "video_dims: [1344, 768, 97]" in cfg
    assert '"%s"' % TRIGGER in cfg
    assert "rank: 16" in cfg and "alpha: 16" in cfg and "steps: 800" in cfg


def test_preprocess_argv_is_multi_frame():
    argv = ad.preprocess_argv("/clips", "/caps", "/out", 1344, 768, 97)
    assert "--max-frames" in argv and argv[argv.index("--max-frames") + 1] == "97"  # not 1 (that's stills)
    assert "-H" in argv and argv[argv.index("-H") + 1] == "768"
    assert "-W" in argv and argv[argv.index("-W") + 1] == "1344"


def test_train_argv_low_ram():
    assert ad.train_argv("/cfg.yaml") == [ad.LTX2_MLX_BIN, "train", "--config", "/cfg.yaml", "--low-ram"]


# ---- orchestration via the stub binary ----------------------------------------
def test_train_action_records_lora(tmp_path, monkeypatch):
    name = _seed_action(tmp_path / "lib")
    _install_stub(tmp_path, monkeypatch)
    data, lora_path = ad.train_action(name)
    assert data["status"] == "trained"
    assert os.path.isfile(lora_path) and os.path.getsize(lora_path) > 0
    assert data["lora"]["base_model"] == ad.INFERENCE_MODEL
    assert data["lora"]["rank"] == ad.ACTION_RANK == data["lora"]["alpha"]
    al.validate_action(data)                      # the trained record is valid
    assert al.load_action(name)["status"] == "trained"
    assert al.registered_triggers() == {TRIGGER: name}  # now offered to the planner


def test_train_refuses_too_few_clips(tmp_path, monkeypatch):
    name = _seed_action(tmp_path / "lib", clips=4)   # < MIN_CLIPS
    _install_stub(tmp_path, monkeypatch)
    with pytest.raises(ad.DatasetError):
        ad.train_action(name)


def test_train_refuses_missing_train_model(tmp_path, monkeypatch):
    name = _seed_action(tmp_path / "lib")
    _install_stub(tmp_path, monkeypatch)
    monkeypatch.setattr(ad, "TRAIN_MODEL", str(tmp_path / "does-not-exist"))
    with pytest.raises(ad.DatasetError):
        ad.train_action(name)


def test_train_refuses_while_busy_or_story_server_up(tmp_path, monkeypatch):
    # spec 4.3 (A7): never train concurrently with a render or with the story server loaded.
    name = _seed_action(tmp_path / "lib")
    _install_stub(tmp_path, monkeypatch)
    monkeypatch.setattr(ad, "busy_process", lambda: (4242, "bin/ltx-mlx-render --manifest m"))
    with pytest.raises(ad.DatasetError, match="pid 4242"):
        ad.train_action(name)
    monkeypatch.setattr(ad, "busy_process", lambda: None)
    monkeypatch.setattr(ad, "story_server_state", lambda: "SERVING mlx-vision")
    with pytest.raises(ad.DatasetError, match="story server is SERVING mlx-vision"):
        ad.train_action(name)
    assert al.load_action(name)["status"] != "trained"
