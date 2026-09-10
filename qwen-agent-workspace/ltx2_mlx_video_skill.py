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
DEFAULT_HEIGHT = 480           # 480 % 32 == 0
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
