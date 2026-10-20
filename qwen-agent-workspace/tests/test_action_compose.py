"""Tests for ltx-movie --action composition (action-LoRA Phase 4): _resolve_actions
turns trained actions into global video-LoRA entries, gated by lora-check, merging
with cast-character LoRAs. The arch gate is stubbed for the resolution tests (its
real behavior is covered by test_lora_compat)."""

import importlib.machinery
import os

import pytest

HERE = os.path.dirname(os.path.realpath(__file__))
WS = os.path.dirname(HERE)
ltx_movie = importlib.machinery.SourceFileLoader(
    "ltx_movie", os.path.join(WS, "bin", "ltx-movie")).load_module()
al = importlib.machinery.SourceFileLoader(
    "action_lib", os.path.join(WS, "action_lib.py")).load_module()

DESC = "a spinning kick delivered with the rear leg to head height in one motion"


def _args(*argv):
    return ltx_movie.build_parser().parse_args(["a narrative", "--story-id", "t", *argv])


def _make_action(libdir, name="roundhouse", status="trained", strength=0.7):
    os.environ[al.LIBRARY_ENV] = str(libdir)
    os.makedirs(al.action_dir(name), exist_ok=True)
    data = al.new_action(name, "performs a %s" % name.replace("-", " "), DESC, ["/abs/c0.mp4"])
    data["default_strength"] = strength
    if status == "trained":
        ld = os.path.join(al.action_dir(name), "loras", "video"); os.makedirs(ld, exist_ok=True)
        lp = os.path.join(ld, "%s.safetensors" % name)
        with open(lp, "wb") as f:
            f.write(b"x" * 32)
        data["lora"] = {"path": lp, "sha256": "a" * 64, "rank": 16, "alpha": 16,
                        "base_model": "dgrauet/ltx-2.3-mlx-q8"}
        data["status"] = "trained"
    al.write_action(data)
    return name, (data.get("lora") or {}).get("path")


@pytest.fixture
def pass_gate(monkeypatch):
    monkeypatch.setattr(ltx_movie, "_action_lora_arch_ok", lambda p: (True, "stub"))


def test_action_resolves_to_global_video_lora(tmp_path, monkeypatch, pass_gate):
    name, lp = _make_action(tmp_path / "lib")
    args = _args("--action", name)
    assert ltx_movie._resolve_actions(args) == 0
    assert args.global_video_loras == [(os.path.abspath(lp), 0.7)]


def test_action_strength_override(tmp_path, monkeypatch, pass_gate):
    name, lp = _make_action(tmp_path / "lib")
    args = _args("--action", "%s:0.4" % name)
    assert ltx_movie._resolve_actions(args) == 0
    assert args.global_video_loras == [(os.path.abspath(lp), 0.4)]


def test_untrained_action_refused(tmp_path, monkeypatch, pass_gate):
    name, _ = _make_action(tmp_path / "lib", status="dataset")
    assert ltx_movie._resolve_actions(_args("--action", name)) == 2


def test_unknown_action_refused(tmp_path, monkeypatch, pass_gate):
    os.environ[al.LIBRARY_ENV] = str(tmp_path / "lib")
    assert ltx_movie._resolve_actions(_args("--action", "ghost")) == 2


def test_bad_strength_refused(tmp_path, monkeypatch, pass_gate):
    name, _ = _make_action(tmp_path / "lib")
    assert ltx_movie._resolve_actions(_args("--action", "%s:3.0" % name)) == 2


def test_arch_gate_failure_refuses(tmp_path, monkeypatch):
    name, _ = _make_action(tmp_path / "lib")
    monkeypatch.setattr(ltx_movie, "_action_lora_arch_ok", lambda p: (False, "modules absent"))
    assert ltx_movie._resolve_actions(_args("--action", name)) == 2


def test_action_merges_with_global_lora(tmp_path, monkeypatch, pass_gate):
    name, lp = _make_action(tmp_path / "lib")
    other = str(tmp_path / "style.safetensors")
    with open(other, "wb") as f:
        f.write(b"y" * 32)
    args = _args("--lora", other, "--action", name)
    assert ltx_movie._resolve_actions(args) == 0
    paths = [p for p, _s in args.global_video_loras]
    assert os.path.abspath(other) in paths and os.path.abspath(lp) in paths


def test_no_action_is_noop(tmp_path, monkeypatch):
    args = _args()
    assert ltx_movie._resolve_actions(args) == 0
    assert getattr(args, "global_video_loras", None) in (None, [])
