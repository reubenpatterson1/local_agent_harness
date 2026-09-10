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
    check("M3f width < 32 rejected",
          "width" in (_raises_value_error(skill.validate_geometry, 0, 480, 241) or ""),
          "got %r" % _raises_value_error(skill.validate_geometry, 0, 480, 241))
    check("M3g height < 32 rejected",
          "height" in (_raises_value_error(skill.validate_geometry, 704, -32, 241) or ""),
          "got %r" % _raises_value_error(skill.validate_geometry, 704, -32, 241))


# ---------------------------------------------------------------------------
# M3b: _resolve_bin
# ---------------------------------------------------------------------------

def test_resolve_bin():
    saved_bin = skill.LTX2_MLX_BIN
    saved_which = skill.shutil.which
    try:
        skill.LTX2_MLX_BIN = "ltx-2-mlx"
        skill.shutil.which = lambda name: "/fake/found/path"
        check("M3h bare name resolvable via PATH returns which() result",
              skill._resolve_bin() == "/fake/found/path",
              "got %r" % skill._resolve_bin())
    finally:
        skill.shutil.which = saved_which
        skill.LTX2_MLX_BIN = saved_bin

    try:
        skill.LTX2_MLX_BIN = "totally-not-a-real-binary-xyz"
        check("M3i bare name not resolvable via PATH returns name verbatim",
              skill._resolve_bin() == "totally-not-a-real-binary-xyz",
              "got %r" % skill._resolve_bin())
    finally:
        skill.LTX2_MLX_BIN = saved_bin

    try:
        skill.LTX2_MLX_BIN = "/some/explicit/path/ltx-2-mlx"

        def _raise_if_called(name):
            raise AssertionError("shutil.which should not be called for a path")

        skill.shutil.which = _raise_if_called
        check("M3j path containing os.sep returns unchanged without calling shutil.which",
              skill._resolve_bin() == "/some/explicit/path/ltx-2-mlx",
              "got %r" % skill._resolve_bin())
    finally:
        skill.shutil.which = saved_which
        skill.LTX2_MLX_BIN = saved_bin


# ---------------------------------------------------------------------------
# M4: build_command golden argv
# ---------------------------------------------------------------------------

def test_build_command_i2v_defaults():
    cmd = skill.build_command(prompt="a prompt", output_path="/tmp/out.mp4",
                              image_path="/tmp/in.png", width=704, height=480,
                              num_frames=241, frame_rate=24, seed=0)
    check("M4a I2V golden argv",
          cmd == [skill._resolve_bin(), "generate",
                  "--model", skill.MODEL_ID,
                  "--distilled",
                  "--prompt", "a prompt",
                  "--output", "/tmp/out.mp4",
                  "--image", "/tmp/in.png", "0", "1.0",
                  "-H", "480", "-W", "704", "-f", "241",
                  "--frame-rate", "24", "--seed", "0",
                  "--low-ram"],
          "got %r" % (cmd,))


def test_build_command_t2v():
    cmd = skill.build_command(prompt="p", output_path="/tmp/o.mp4", image_path=None,
                              width=704, height=480, num_frames=241,
                              frame_rate=24, seed=3)
    check("M4b T2V has no --image token at all", "--image" not in cmd, "got %r" % (cmd,))
    check("M4c T2V golden argv",
          cmd == [skill._resolve_bin(), "generate",
                  "--model", skill.MODEL_ID,
                  "--distilled",
                  "--prompt", "p",
                  "--output", "/tmp/o.mp4",
                  "-H", "480", "-W", "704", "-f", "241",
                  "--frame-rate", "24", "--seed", "3",
                  "--low-ram"],
          "got %r" % (cmd,))


def test_build_command_flags():
    no_low = skill.build_command(prompt="p", output_path="/tmp/o.mp4", width=704,
                                 height=480, num_frames=241, frame_rate=24, seed=0,
                                 low_ram=False)
    check("M4d low_ram=False omits --low-ram", "--low-ram" not in no_low, "got %r" % (no_low,))

    tiled = skill.build_command(prompt="p", output_path="/tmp/o.mp4", width=704,
                                height=480, num_frames=241, frame_rate=24, seed=0,
                                tile_frames=2, tile_spatial=2)
    check("M4e tiling emitted after --low-ram in order",
          tiled[-4:] == ["--tile-frames", "2", "--tile-spatial", "2"], "got %r" % (tiled,))

    untiled = skill.build_command(prompt="p", output_path="/tmp/o.mp4", width=704,
                                  height=480, num_frames=241, frame_rate=24, seed=0,
                                  tile_frames=1, tile_spatial=1)
    check("M4f tiling at 1 emits nothing",
          "--tile-frames" not in untiled and "--tile-spatial" not in untiled,
          "got %r" % (untiled,))

    custom = skill.build_command(prompt="p", output_path="/tmp/o.mp4", width=1024,
                                 height=576, num_frames=121, frame_rate=30, seed=99,
                                 model="Other/Model", quiet=True)
    check("M4g custom seed/model/geometry/quiet",
          custom[2:4] == ["--model", "Other/Model"]
          and "--seed" in custom and custom[custom.index("--seed") + 1] == "99"
          and custom[-1] == "--quiet"
          and custom[custom.index("-W") + 1] == "1024"
          and custom[custom.index("-H") + 1] == "576"
          and custom[custom.index("-f") + 1] == "121"
          and custom[custom.index("--frame-rate") + 1] == "30",
          "got %r" % (custom,))


def test_build_command_invariants():
    for kw in ({"image_path": "/tmp/i.png"}, {}):
        cmd = skill.build_command(prompt="p", output_path="/tmp/o.mp4", width=704,
                                  height=480, num_frames=241, frame_rate=24, seed=0, **kw)
        check("M4h --distilled always present (image_path=%r)" % kw.get("image_path"),
              "--distilled" in cmd, "got %r" % (cmd,))
        check("M4i --frame-rate always present (image_path=%r)" % kw.get("image_path"),
              "--frame-rate" in cmd, "got %r" % (cmd,))
        check("M4j no --negative-prompt (image_path=%r)" % kw.get("image_path"),
              "--negative-prompt" not in cmd, "got %r" % (cmd,))
        check("M4k no --steps / --lora / --two-stage (image_path=%r)" % kw.get("image_path"),
              not any(t in cmd for t in ("--steps", "--lora", "--two-stage",
                                         "--two-stages-hq", "--one-stage")),
              "got %r" % (cmd,))


# ---------------------------------------------------------------------------
# M5: the eight ValueError conditions, all raised BEFORE any subprocess
# ---------------------------------------------------------------------------

_STUB_SRC = '''#!/usr/bin/env python3
import os, sys, time
argv = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(repr(argv) + "\\n")
if os.environ.get("STUB_PIDFILE"):
    with open(os.environ["STUB_PIDFILE"], "w") as f:
        f.write(str(os.getpid()))
out = argv[argv.index("--output") + 1] if "--output" in argv else None
sys.stdout.write("stub stdout line 1\\n")
sys.stdout.flush()
sys.stderr.write("stub stderr line 2\\n")
sys.stderr.flush()
mode = os.environ.get("STUB_MODE", "ok")
if mode == "fail":
    sys.stderr.write("stub failing on purpose\\n")
    sys.exit(1)
if mode == "sleep":
    time.sleep(120)
if mode == "empty":
    open(out, "w").close()
elif mode == "ok":
    with open(out, "wb") as f:
        f.write(b"\\x00" * 1024)
sys.exit(0)
'''


def _install_stub(td, mode="ok"):
    """Point the module at a stub CLI. Returns (stub_path, invocation_log)."""
    stub = os.path.join(td, "stub-ltx-2-mlx")
    with open(stub, "w") as f:
        f.write(_STUB_SRC)
    os.chmod(stub, 0o755)
    log = os.path.join(td, "invocations.log")
    skill.LTX2_MLX_BIN = stub
    skill.LTX2_MLX_DIR = td
    os.environ["STUB_LOG"] = log
    os.environ["STUB_MODE"] = mode
    return stub, log


def _invocation_count(log):
    if not os.path.exists(log):
        return 0
    with open(log) as f:
        return len([ln for ln in f.read().splitlines() if ln.strip()])


def test_generate_video_value_errors():
    saved_bin, saved_dir = skill.LTX2_MLX_BIN, skill.LTX2_MLX_DIR
    try:
        with tempfile.TemporaryDirectory() as td:
            _stub, log = _install_stub(td)
            img = os.path.join(td, "in.png")
            with open(img, "wb") as f:
                f.write(b"png")
            out = os.path.join(td, "out.mp4")

            def base(**over):
                kw = dict(prompt="p", output_path=out, image_path=img)
                kw.update(over)
                return kw

            cases = [
                ("M5a empty prompt", "prompt", base(prompt="")),
                ("M5b non-str prompt", "prompt", base(prompt=None)),
                ("M5c width % 32", "width", base(width=700)),
                ("M5d height % 32", "height", base(height=481)),
                ("M5e num_frames lattice", "num_frames", base(num_frames=240)),
                ("M5f num_frames < 9", "num_frames", base(num_frames=1)),
                ("M5g output not .mp4", ".mp4",
                 base(output_path=os.path.join(td, "out.mov"))),
                ("M5h parent dir missing", "output directory",
                 base(output_path=os.path.join(td, "nope", "out.mp4"))),
                ("M5j image unreadable", "image_path",
                 base(image_path=os.path.join(td, "missing.png"))),
                ("M5k tile_frames < 1", "tile_frames", base(tile_frames=0)),
                ("M5l tile_spatial < 1", "tile_spatial", base(tile_spatial=0)),
                ("M5o non-str output_path", "output_path", base(output_path=None)),
            ]
            for name, needle, kw in cases:
                msg = _raises_value_error(skill.generate_video, **kw)
                check(name, msg is not None and needle in msg, "got %r" % msg)

            def _v(**over):
                kw = dict(prompt="p", output_path=out, image_path=img, width=704,
                          height=480, num_frames=241, tile_frames=1, tile_spatial=1,
                          force=False)
                kw.update(over)
                return _raises_value_error(skill._validate_generate_args, **kw)

            for label, over in [
                ("I2V defaults", {}),
                ("T2V image_path=None", dict(image_path=None)),
                ("tiling > 1", dict(tile_frames=2, tile_spatial=2)),
                ("non-default valid geometry", dict(width=1024, height=576, num_frames=121)),
            ]:
                m = _v(**over)
                check("M5n negative control: %s accepted" % label, m is None,
                      "over-rejected: %r" % m)

            with open(out, "wb") as f:
                f.write(b"existing")
            msg = _raises_value_error(skill.generate_video, **base())
            check("M5i existing output without force", msg is not None and "already exists" in msg,
                  "got %r" % msg)

            msg = _raises_value_error(skill._validate_generate_args, prompt="p",
                                      output_path=out, image_path=img, width=704,
                                      height=480, num_frames=241, tile_frames=1,
                                      tile_spatial=1, force=True)
            check("M5p force=True accepts an existing output_path", msg is None,
                  "over-rejected: %r" % msg)

            check("M5m no subprocess was ever spawned by validation-only calls",
                  _invocation_count(log) == 0,
                  "got %d invocations" % _invocation_count(log))
    finally:
        skill.LTX2_MLX_BIN, skill.LTX2_MLX_DIR = saved_bin, saved_dir


if __name__ == "__main__":
    test_constants()
    test_error_type()
    test_validate_geometry()
    test_resolve_bin()
    test_build_command_i2v_defaults()
    test_build_command_t2v()
    test_build_command_flags()
    test_build_command_invariants()
    test_generate_video_value_errors()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
