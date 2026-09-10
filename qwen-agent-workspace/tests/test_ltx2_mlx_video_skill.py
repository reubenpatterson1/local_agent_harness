"""Plain-python (no pytest) offline tests for ltx2_mlx_video_skill.py.

Run: python3 tests/test_ltx2_mlx_video_skill.py
No GPU, no model weights, no network: every subprocess outcome is driven by
a stub CLI installed through the LTX2_MLX_BIN / LTX2_MLX_DIR seam.
"""

import os
import sys
import tempfile

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import ltx2_mlx_video_skill as skill  # noqa: E402

TOTAL = 0
FAILED = 0


def check(name, condition, detail=""):
    global TOTAL, FAILED
    TOTAL += 1
    if condition:
        print("PASS %s" % name)
    else:
        FAILED += 1
        print("FAIL %s %s" % (name, detail))


# ---------------------------------------------------------------------------
# M1: module constants
# ---------------------------------------------------------------------------

def test_constants():
    check("M1a MODEL_ID", skill.MODEL_ID == "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8",
          "got %r" % skill.MODEL_ID)
    check("M1b DEFAULT_WIDTH 704", skill.DEFAULT_WIDTH == 704, "got %r" % skill.DEFAULT_WIDTH)
    check("M1c DEFAULT_HEIGHT 480", skill.DEFAULT_HEIGHT == 480, "got %r" % skill.DEFAULT_HEIGHT)
    check("M1d DEFAULT_NUM_FRAMES 241", skill.DEFAULT_NUM_FRAMES == 241,
          "got %r" % skill.DEFAULT_NUM_FRAMES)
    check("M1e DEFAULT_FRAME_RATE 24", skill.DEFAULT_FRAME_RATE == 24,
          "got %r" % skill.DEFAULT_FRAME_RATE)
    check("M1f DEFAULT_LOW_RAM True", skill.DEFAULT_LOW_RAM is True,
          "got %r" % skill.DEFAULT_LOW_RAM)
    check("M1g DEFAULT_TILE_FRAMES 1", skill.DEFAULT_TILE_FRAMES == 1,
          "got %r" % skill.DEFAULT_TILE_FRAMES)
    check("M1h DEFAULT_TILE_SPATIAL 1", skill.DEFAULT_TILE_SPATIAL == 1,
          "got %r" % skill.DEFAULT_TILE_SPATIAL)
    check("M1i geometry is on the lattice",
          skill.DEFAULT_WIDTH % 32 == 0 and skill.DEFAULT_HEIGHT % 32 == 0
          and (skill.DEFAULT_NUM_FRAMES - 1) % 8 == 0)
    check("M1j LTX2_MLX_BIN defaults under LTX2_MLX_DIR/.venv/bin",
          skill.LTX2_MLX_BIN.endswith(os.path.join(".venv", "bin", "ltx-2-mlx"))
          or os.environ.get("LTX2_MLX_BIN") is not None,
          "got %r" % skill.LTX2_MLX_BIN)


# ---------------------------------------------------------------------------
# M2: Ltx2MlxError shape
# ---------------------------------------------------------------------------

def test_error_type():
    check("M2a subclasses RuntimeError", issubclass(skill.Ltx2MlxError, RuntimeError))
    exc = skill.Ltx2MlxError("boom", returncode=7, cmd=["a", "b"],
                             stderr_tail="tail-line\n", output_path="/tmp/x.mp4")
    check("M2b returncode attribute", exc.returncode == 7, "got %r" % exc.returncode)
    check("M2c cmd attribute", exc.cmd == ["a", "b"], "got %r" % exc.cmd)
    check("M2d stderr_tail attribute", exc.stderr_tail == "tail-line\n",
          "got %r" % exc.stderr_tail)
    check("M2e output_path attribute", exc.output_path == "/tmp/x.mp4",
          "got %r" % exc.output_path)
    check("M2f timed_out defaults False", exc.timed_out is False, "got %r" % exc.timed_out)

    msg = skill._format_error("subprocess failed", 7, "/tmp/x.mp4", "the-tail\n")
    i_rc, i_out, i_tail = msg.find("7"), msg.find("/tmp/x.mp4"), msg.find("the-tail")
    check("M2g str() names rc, output path, stderr tail in that order",
          -1 < i_rc < i_out < i_tail, "msg=%r" % msg)


# ---------------------------------------------------------------------------
# M3: validate_geometry
# ---------------------------------------------------------------------------

def _raises_value_error(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except ValueError as e:
        return str(e)
    return None


def test_validate_geometry():
    check("M3a (704,480,241) accepted", skill.validate_geometry(704, 480, 241) is None)
    check("M3b width not multiple of 32 rejected",
          "width" in (_raises_value_error(skill.validate_geometry, 700, 480, 241) or ""),
          "got %r" % _raises_value_error(skill.validate_geometry, 700, 480, 241))
    check("M3c height not multiple of 32 rejected",
          "height" in (_raises_value_error(skill.validate_geometry, 704, 481, 241) or ""),
          "got %r" % _raises_value_error(skill.validate_geometry, 704, 481, 241))
    check("M3d num_frames off the 8k+1 lattice rejected",
          "8" in (_raises_value_error(skill.validate_geometry, 704, 480, 240) or ""),
          "got %r" % _raises_value_error(skill.validate_geometry, 704, 480, 240))
    check("M3e num_frames < 9 rejected",
          ">= 9" in (_raises_value_error(skill.validate_geometry, 704, 480, 1) or ""),
          "got %r" % _raises_value_error(skill.validate_geometry, 704, 480, 1))


if __name__ == "__main__":
    test_constants()
    test_error_type()
    test_validate_geometry()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
