#!/usr/bin/env python3
"""ltx2_mlx_video_skill -- thin, stdlib-only wrapper around one
`ltx-2-mlx generate --distilled` subprocess per clip.

This module NEVER loads a model. It builds an argv, spawns the pinned
ltx-2-mlx binary, streams its combined stdout/stderr, and verifies that a
non-empty .mp4 landed on disk. It deliberately does NOT import mps_guard,
torch, diffusers, transformers, mlx, PIL or content_safety -- there is no
in-process GPU work to guard, and tests/check_ltx2_mlx_no_forbidden_imports.py
enforces that. The OLD backend (ltx_video_skill.py) is untouched and remains
the module every existing consumer uses.

The LTX2_MLX_BIN / LTX2_MLX_DIR environment overrides exist solely so the
offline test suite can substitute a stub CLI. They are test infrastructure,
not a user-facing feature.

Why the venv binary and not bare `ltx-2-mlx`: the `ltx-2-mlx` name on PATH is
a SHELL ALIAS pointing at ~/local_model_harness_red_team/.../ltx-2-mlx, and
shell aliases do not resolve inside subprocess. Pinning
~/ltx-2-mlx/.venv/bin/ltx-2-mlx is what makes "use ~/ltx-2-mlx" reproducible.
"""

import argparse
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading

LTX2_MLX_DIR = os.environ.get("LTX2_MLX_DIR", os.path.expanduser("~/ltx-2-mlx"))
LTX2_MLX_BIN = os.environ.get("LTX2_MLX_BIN",
                              os.path.join(LTX2_MLX_DIR, ".venv", "bin", "ltx-2-mlx"))

MODEL_ID = "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8"
DEFAULT_WIDTH = 704            # 704 % 32 == 0
DEFAULT_HEIGHT = 448           # 448 % 64 == 0; distilled two-stage snaps H down to a multiple of 64
DEFAULT_NUM_FRAMES = 241       # (241 - 1) % 8 == 0; 240 / 24 == 10.000 s
DEFAULT_FRAME_RATE = 24
DEFAULT_LOW_RAM = True
DEFAULT_TILE_FRAMES = 1
DEFAULT_TILE_SPATIAL = 1

STDERR_TAIL_LINES = 40


class Ltx2MlxError(RuntimeError):
    """Raised when the ltx-2-mlx subprocess fails to produce a usable mp4."""

    def __init__(self, message, returncode=None, cmd=None, stderr_tail="",
                 output_path="", timed_out=False):
        super().__init__(message)
        self.returncode = returncode
        self.cmd = list(cmd or [])
        self.stderr_tail = stderr_tail
        self.output_path = output_path
        self.timed_out = timed_out


def _format_error(reason, returncode, output_path, stderr_tail):
    """The one message format for every Ltx2MlxError: return code, then the
    output path, then the stderr tail, in that order (contract in the design
    doc section 5.2)."""
    return ("ltx-2-mlx %s: returncode=%s output=%s\n"
            "--- last %d lines of combined output ---\n%s"
            % (reason, returncode, output_path, STDERR_TAIL_LINES, stderr_tail))


def validate_geometry(width, height, num_frames):
    """Raise ValueError unless width/height are multiples of 32 and
    num_frames sits on the 8k+1 lattice at or above 9. The VAE silently
    crops off-lattice frame counts instead of erroring, so this check is the
    only thing standing between a typo and a silently shorter clip."""
    if width % 32 != 0:
        raise ValueError("width must be a multiple of 32, got %d" % width)
    if width < 32:
        raise ValueError("width must be >= 32, got %d" % width)
    if height % 32 != 0:
        raise ValueError("height must be a multiple of 32, got %d" % height)
    if height < 32:
        raise ValueError("height must be >= 32, got %d" % height)
    if (num_frames - 1) % 8 != 0:
        raise ValueError("num_frames must satisfy (num_frames - 1) %% 8 == 0, got %d"
                         % num_frames)
    if num_frames < 9:
        raise ValueError("num_frames must be >= 9, got %d" % num_frames)


def _resolve_bin():
    """Absolute path to the ltx-2-mlx binary. A bare name (no path
    separator) is resolved through PATH; anything else is used verbatim so
    the pinned venv binary is never second-guessed."""
    candidate = LTX2_MLX_BIN
    if os.sep not in candidate:
        found = shutil.which(candidate)
        if found:
            return found
    return candidate


def build_command(*, prompt, output_path, image_path=None, width, height,
                  num_frames, frame_rate, seed, model=MODEL_ID, low_ram=True,
                  tile_frames=1, tile_spatial=1, quiet=False):
    """Emit the ltx-2-mlx argv in a fixed token order so golden tests can
    assert on the list.

    --distilled is unconditional: the pack ships no dev transformer, and
    `generate` refuses to run without exactly one pipeline-mode flag.
    --frame-rate is unconditional because the parser marks it required=True.
    The explicit three-argument `--image PATH 0 1.0` form is preferred over
    bare PATH so the anchor index and strength show up in the logged command
    instead of depending on ImageAction's legacy defaulting; frame_idx 0
    selects VideoConditionByLatentIndex, which replaces latent frame 0 --
    the single-anchor I2V semantics this pipeline relies on."""
    cmd = [_resolve_bin(), "generate",
           "--model", str(model),
           "--distilled",
           "--prompt", str(prompt),
           "--output", str(output_path)]
    if image_path is not None:
        cmd += ["--image", str(image_path), "0", "1.0"]
    cmd += ["-H", str(height),
            "-W", str(width),
            "-f", str(num_frames),
            "--frame-rate", str(frame_rate),
            "--seed", str(seed)]
    if low_ram:
        cmd.append("--low-ram")
    if tile_frames > 1:
        cmd += ["--tile-frames", str(tile_frames)]
    if tile_spatial > 1:
        cmd += ["--tile-spatial", str(tile_spatial)]
    if quiet:
        cmd.append("--quiet")
    return cmd


def _validate_generate_args(prompt, output_path, image_path, width, height,
                            num_frames, tile_frames, tile_spatial, force,
                            log_path=None, timeout_s=None):
    """Every ValueError this module can raise is raised here, before any
    subprocess is spawned. Order matches the design doc section 5.3 list."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a non-empty string, got %r" % (prompt,))

    validate_geometry(width, height, num_frames)

    if not isinstance(output_path, str) or not output_path:
        raise ValueError("output_path must be a non-empty string, got %r" % (output_path,))

    if not output_path.endswith(".mp4"):
        raise ValueError("output_path must end in .mp4, got %r" % (output_path,))

    out_dir = os.path.dirname(os.path.abspath(output_path)) or "."
    if not os.path.isdir(out_dir) or not os.access(out_dir, os.W_OK):
        raise ValueError("output directory does not exist or is not writable: %s" % out_dir)

    if log_path is not None:
        log_dir = os.path.dirname(os.path.abspath(log_path)) or "."
        if not os.path.isdir(log_dir) or not os.access(log_dir, os.W_OK):
            raise ValueError("log_path directory does not exist or is not writable: %s" % log_dir)
        if os.path.isdir(log_path):
            raise ValueError("log_path is a directory: %s" % log_path)
        if os.path.exists(log_path) and not os.access(log_path, os.W_OK):
            raise ValueError("log_path exists but is not writable: %s" % log_path)

    if timeout_s is not None and timeout_s <= 0:
        raise ValueError("timeout_s must be positive, got %r" % (timeout_s,))

    if os.path.exists(output_path) and not force:
        raise ValueError("output already exists: %s (pass force=True to overwrite)"
                         % output_path)

    if image_path is not None:
        if not os.path.isfile(image_path) or not os.access(image_path, os.R_OK):
            raise ValueError("image_path is not a readable file: %r" % (image_path,))

    if tile_frames < 1:
        raise ValueError("tile_frames must be >= 1, got %d" % tile_frames)
    if tile_spatial < 1:
        raise ValueError("tile_spatial must be >= 1, got %d" % tile_spatial)


def generate_video(prompt, output_path, image_path=None, *,
                   width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT,
                   num_frames=DEFAULT_NUM_FRAMES, frame_rate=DEFAULT_FRAME_RATE,
                   seed=0, model=MODEL_ID, low_ram=DEFAULT_LOW_RAM,
                   tile_frames=DEFAULT_TILE_FRAMES, tile_spatial=DEFAULT_TILE_SPATIAL,
                   log_path=None, timeout_s=None, force=False, quiet=False):
    """Render one clip and return the ABSOLUTE path of the written .mp4.

    Never returns PIL images. There is no --resume, no three-stage split and
    no embeds.pt staleness logic: MLX does not have the "only process exit
    frees memory" problem that forced them on the old backend.

    Raises ValueError (before any subprocess) for bad arguments; raises
    Ltx2MlxError for a missing binary, a non-zero exit, a timeout, or the
    jetsam signature (exit 0 with no usable output file)."""
    _validate_generate_args(prompt, output_path, image_path, width, height,
                            num_frames, tile_frames, tile_spatial, force,
                            log_path=log_path, timeout_s=timeout_s)
    resolved_bin = _resolve_bin()
    if not os.path.isfile(resolved_bin) or not os.access(resolved_bin, os.X_OK):
        raise Ltx2MlxError(
            _format_error("binary not found or not executable: %s (set LTX2_MLX_BIN)"
                          % resolved_bin, None, output_path, ""),
            returncode=None, cmd=[resolved_bin], stderr_tail="", output_path=output_path)
    if not os.path.isdir(LTX2_MLX_DIR):
        raise Ltx2MlxError(
            _format_error("LTX2_MLX_DIR is not a directory: %s (set LTX2_MLX_DIR)"
                          % LTX2_MLX_DIR, None, output_path, ""),
            returncode=None, cmd=[resolved_bin], stderr_tail="", output_path=output_path)

    cmd = build_command(prompt=prompt, output_path=output_path, image_path=image_path,
                        width=width, height=height, num_frames=num_frames,
                        frame_rate=frame_rate, seed=seed, model=model, low_ram=low_ram,
                        tile_frames=tile_frames, tile_spatial=tile_spatial, quiet=quiet)
    print("[ltx2_mlx_video_skill] %s" % shlex.join(cmd))
    sys.stdout.flush()

    returncode, tail, timed_out = _run_subprocess(cmd, log_path, timeout_s, output_path)

    if timed_out:
        raise Ltx2MlxError(
            _format_error("subprocess timed out after %ss" % timeout_s,
                          returncode, output_path, tail),
            returncode=returncode, cmd=cmd, stderr_tail=tail,
            output_path=output_path, timed_out=True)
    if returncode != 0:
        raise Ltx2MlxError(
            _format_error("subprocess failed", returncode, output_path, tail),
            returncode=returncode, cmd=cmd, stderr_tail=tail, output_path=output_path)
    if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
        # Jetsam signature: the OS killed the ffmpeg child, so there is no
        # traceback anywhere and the parent still exits 0. Callers key their
        # remediation message on returncode == 0 with timed_out False.
        raise Ltx2MlxError(
            _format_error("exited 0 but produced no usable output (missing or zero bytes)",
                          returncode, output_path, tail),
            returncode=0, cmd=cmd, stderr_tail=tail, output_path=output_path)

    return os.path.abspath(output_path)


def _run_subprocess(cmd, log_path, timeout_s, output_path):
    """Spawn cmd in its own process group with cwd=LTX2_MLX_DIR, stream its
    combined stdout/stderr line-by-line to this process's stdout (and to
    log_path when given), and return (returncode, stderr_tail, timed_out).

    Line-by-line streaming is not cosmetic: a render takes tens of minutes,
    and buffering the whole run would leave the operator staring at nothing.
    The timeout is a watchdog thread that SIGKILLs the whole process group,
    because ltx-2-mlx spawns an ffmpeg child that would otherwise survive.
    A failed spawn, or any other exception while the child is running, also
    kills and reaps the whole process group so nothing is left orphaned."""
    try:
        logf = open(log_path, "a") if log_path else None
    except OSError as e:
        raise Ltx2MlxError(
            _format_error("cannot open log_path %s: %s" % (log_path, e), None,
                          output_path, ""),
            returncode=None, cmd=cmd, stderr_tail="", output_path=output_path)
    try:
        popen = subprocess.Popen(cmd, cwd=LTX2_MLX_DIR, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, bufsize=1,
                                 start_new_session=True)
    except OSError as e:
        if logf:
            logf.close()
        raise Ltx2MlxError(
            _format_error("failed to spawn: %s" % e, None, output_path, ""),
            returncode=None, cmd=cmd, stderr_tail="", output_path=output_path)

    timed_out = [False]
    timer = None
    if timeout_s is not None:
        def _kill_group():
            timed_out[0] = True
            try:
                os.killpg(os.getpgid(popen.pid), signal.SIGKILL)
            except OSError:
                pass
        timer = threading.Timer(timeout_s, _kill_group)
        timer.daemon = True
        timer.start()

    lines = []
    with popen as proc:
        try:
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                if logf:
                    logf.write(line)
                    logf.flush()
                lines.append(line)
            proc.wait()
        except BaseException:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                pass
            proc.wait()
            raise
        finally:
            if timer:
                timer.cancel()
            if logf:
                logf.close()

    return proc.returncode, "".join(lines[-STDERR_TAIL_LINES:]), timed_out[0]


def build_cli_parser():
    parser = argparse.ArgumentParser(
        prog="ltx2_mlx_video_skill",
        description=("Render one clip with ltx-2-mlx generate --distilled. "
                     "Omitting --image is text-to-video; there is no separate "
                     "--t2v flag."),
    )
    parser.add_argument("prompt")
    parser.add_argument("output", metavar="OUTPUT_MP4")
    parser.add_argument("--image", default=None)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--frames", type=int, default=DEFAULT_NUM_FRAMES)
    parser.add_argument("--frame-rate", dest="frame_rate", type=int,
                        default=DEFAULT_FRAME_RATE)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--model", default=MODEL_ID)
    parser.add_argument("--no-low-ram", dest="no_low_ram", action="store_true",
                        default=False)
    parser.add_argument("--tile-frames", dest="tile_frames", type=int,
                        default=DEFAULT_TILE_FRAMES)
    parser.add_argument("--tile-spatial", dest="tile_spatial", type=int,
                        default=DEFAULT_TILE_SPATIAL)
    parser.add_argument("--log", default=None)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--quiet", action="store_true", default=False)
    parser.add_argument("--force", action="store_true", default=False)
    return parser


def main(argv=None):
    args = build_cli_parser().parse_args(argv)
    try:
        path = generate_video(
            args.prompt, args.output, image_path=args.image,
            width=args.width, height=args.height, num_frames=args.frames,
            frame_rate=args.frame_rate, seed=args.seed, model=args.model,
            low_ram=(not args.no_low_ram), tile_frames=args.tile_frames,
            tile_spatial=args.tile_spatial, log_path=args.log,
            timeout_s=args.timeout, force=args.force, quiet=args.quiet)
    except ValueError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    except Ltx2MlxError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 1
    print("[ltx2_mlx_video_skill] wrote: %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
