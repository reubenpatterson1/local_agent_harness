"""Tests for ltx2_mlx_video_skill's host-aware autotune layer. The layer is
opt-in (QWEN_LTX_AUTOTUNE) and only raises geometry / drops --low-ram on a
big-memory host, so the fixed DEFAULT_* baseline (and every golden test and
fleet host that relies on it) is unaffected when it is off."""

import importlib.machinery
import os

HERE = os.path.dirname(os.path.realpath(__file__))
WS = os.path.dirname(HERE)


def _skill():
    return importlib.machinery.SourceFileLoader(
        "ltx2_mlx_video_skill", os.path.join(WS, "ltx2_mlx_video_skill.py")).load_module()


class _Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


_FIELDS = [("width", "width", ["--width"], int),
           ("height", "height", ["--height"], int),
           ("num_frames", "frames", ["--frames"], int),
           ("low_ram", "no_low_ram", ["--no-low-ram"], lambda v: not v)]


def test_overrides_only_fire_on_big_tier(monkeypatch):
    s = _skill()
    assert s.autotune_overrides(128) == {"low_ram": False, "width": 1216,
                                         "height": 704, "num_frames": 241}
    assert s.autotune_overrides(96) != {}      # at threshold
    assert s.autotune_overrides(48) == {}      # 48 GB dev host unchanged
    assert s.autotune_overrides(16) == {}      # lean host unchanged
    # undetectable RAM -> no change (force detection to fail via a bad mem env)
    monkeypatch.setenv(s.AUTOTUNE_MEM_ENV, "not-a-number")
    assert s.autotune_overrides(None) == {}


def test_detect_honors_mem_env(monkeypatch):
    s = _skill()
    monkeypatch.setenv(s.AUTOTUNE_MEM_ENV, "128")
    assert s.detect_unified_memory_gib() == 128.0
    monkeypatch.setenv(s.AUTOTUNE_MEM_ENV, "not-a-number")
    assert s.detect_unified_memory_gib() is None


def test_enabled_flag(monkeypatch):
    s = _skill()
    for truthy in ("1", "true", "YES", "on"):
        monkeypatch.setenv(s.AUTOTUNE_ENV, truthy)
        assert s.autotune_enabled() is True
    monkeypatch.setenv(s.AUTOTUNE_ENV, "0")
    assert s.autotune_enabled() is False
    monkeypatch.delenv(s.AUTOTUNE_ENV, raising=False)
    assert s.autotune_enabled() is False


def test_apply_overrides_unset_fields_on_big_host(monkeypatch):
    s = _skill()
    monkeypatch.setenv(s.AUTOTUNE_ENV, "1")
    monkeypatch.setenv(s.AUTOTUNE_MEM_ENV, "128")
    args = _Args(width=704, height=448, frames=145, no_low_ram=False)
    applied = s.maybe_autotune_apply(args, ["--prompt", "x"], _FIELDS)
    assert args.width == 1216 and args.height == 704 and args.frames == 241
    assert args.no_low_ram is True            # low_ram off
    assert set(applied) == {"width=1216", "height=704", "frames=241", "no_low_ram=True"}


def test_apply_respects_explicit_flags(monkeypatch):
    s = _skill()
    monkeypatch.setenv(s.AUTOTUNE_ENV, "1")
    monkeypatch.setenv(s.AUTOTUNE_MEM_ENV, "128")
    args = _Args(width=640, height=384, frames=145, no_low_ram=False)
    # user passed --width and --no-low-ram explicitly -> those must NOT change
    applied = s.maybe_autotune_apply(args, ["--width", "640", "--no-low-ram"], _FIELDS)
    assert args.width == 640                  # respected
    assert args.no_low_ram is False           # respected (not overridden to True)
    assert args.height == 704 and args.frames == 241   # the unset ones still tuned
    assert "width=640" not in " ".join(applied)


def test_noop_when_disabled(monkeypatch):
    s = _skill()
    monkeypatch.delenv(s.AUTOTUNE_ENV, raising=False)
    monkeypatch.setenv(s.AUTOTUNE_MEM_ENV, "128")   # big host, but autotune OFF
    args = _Args(width=704, height=448, frames=145, no_low_ram=False)
    assert s.maybe_autotune_apply(args, [], _FIELDS) == []
    assert args.width == 704 and args.frames == 145 and args.no_low_ram is False


def test_noop_on_small_host(monkeypatch):
    s = _skill()
    monkeypatch.setenv(s.AUTOTUNE_ENV, "1")
    monkeypatch.setenv(s.AUTOTUNE_MEM_ENV, "48")    # dev host, enabled but below big tier
    args = _Args(width=704, height=448, frames=145, no_low_ram=False)
    assert s.maybe_autotune_apply(args, [], _FIELDS) == []
    assert args.width == 704 and args.no_low_ram is False
