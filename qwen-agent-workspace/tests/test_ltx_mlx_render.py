"""Plain-python (no pytest) offline tests for bin/ltx-mlx-render.

Run: python3 tests/test_ltx_mlx_render.py
No GPU, no model weights, no network. The one test that shells out to real
ffmpeg (R9) skips itself with a clear message when ffmpeg is absent.
"""

import importlib.machinery
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

_RENDER_PATH = os.path.join(WS, "bin", "ltx-mlx-render")
render = importlib.machinery.SourceFileLoader("ltx_mlx_render", _RENDER_PATH).load_module()

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
# R1: parser defaults and derived paths
# ---------------------------------------------------------------------------

def test_parser_defaults():
    a = render.build_parser().parse_args(["/tmp/m.json", "/tmp/movie.mp4"])
    check("R1a manifest_path positional", a.manifest_path == "/tmp/m.json")
    check("R1b output_path positional", a.output_path == "/tmp/movie.mp4")
    check("R1c frames 241", a.frames == 241, "got %r" % a.frames)
    check("R1d width 704", a.width == 704, "got %r" % a.width)
    check("R1e height 480", a.height == 480, "got %r" % a.height)
    check("R1f frame_rate 24 and is an int", a.frame_rate == 24 and isinstance(a.frame_rate, int),
          "got %r" % a.frame_rate)
    check("R1g seed 0", a.seed == 0, "got %r" % a.seed)
    check("R1h model is the pack id", a.model == "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8",
          "got %r" % a.model)
    check("R1i no_low_ram False", a.no_low_ram is False, "got %r" % a.no_low_ram)
    check("R1j tile_frames 1", a.tile_frames == 1, "got %r" % a.tile_frames)
    check("R1k tile_spatial 1", a.tile_spatial == 1, "got %r" % a.tile_spatial)
    check("R1l panel_timeout 7200", a.panel_timeout == 7200, "got %r" % a.panel_timeout)
    check("R1m clips_dir None", a.clips_dir is None, "got %r" % a.clips_dir)
    check("R1n resume False", a.resume is False, "got %r" % a.resume)
    check("R1o force False", a.force is False, "got %r" % a.force)
    check("R1p dry_run False", a.dry_run is False, "got %r" % a.dry_run)
    check("R1q on_panel_failure stop", a.on_panel_failure == "stop",
          "got %r" % a.on_panel_failure)
    check("R1r retry_failed 0", a.retry_failed == 0, "got %r" % a.retry_failed)
    check("R1s retry_idle 120", a.retry_idle == 120, "got %r" % a.retry_idle)
    check("R1t max_consecutive_failures 3", a.max_consecutive_failures == 3,
          "got %r" % a.max_consecutive_failures)
    check("R1u skip_input_screen False", a.skip_input_screen is False,
          "got %r" % a.skip_input_screen)
    check("R1v there is no --fps flag", "--fps" not in render.build_parser().format_help())
    check("R1w SECONDS_PER_PANEL_ESTIMATE is an int", isinstance(
        render.SECONDS_PER_PANEL_ESTIMATE, int), "got %r" % render.SECONDS_PER_PANEL_ESTIMATE)


def test_geometry_validation():
    def _args(**over):
        a = render.build_parser().parse_args(["/tmp/m.json", "/tmp/o.mp4"])
        for k, v in over.items():
            setattr(a, k, v)
        return a
    check("R1x default geometry accepted", render.validate_cli_geometry(_args()) is None)
    check("R1y width off 32 rejected",
          "width" in (render.validate_cli_geometry(_args(width=700)) or ""),
          "got %r" % render.validate_cli_geometry(_args(width=700)))
    check("R1z frames off lattice rejected",
          "num_frames" in (render.validate_cli_geometry(_args(frames=240)) or ""),
          "got %r" % render.validate_cli_geometry(_args(frames=240)))
    check("R1aa tile_frames < 1 rejected",
          "tile_frames" in (render.validate_cli_geometry(_args(tile_frames=0)) or ""),
          "got %r" % render.validate_cli_geometry(_args(tile_frames=0)))


def test_run_id_and_story_dir():
    rid = render.new_run_id()
    check("R1ab run id matches <UTC>-<hex8>",
          re.match(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$", rid) is not None, "got %r" % rid)
    sd = render.story_dir_for("demo")
    check("R1ac story dir under WS/generated/stories",
          sd == os.path.join(WS, "generated", "stories", "demo"), "got %r" % sd)


# ---------------------------------------------------------------------------
# R2: bin/ltx-mlx-render itself imports nothing heavy (design doc 6.12)
# ---------------------------------------------------------------------------

def test_render_script_has_no_heavy_imports():
    import ast
    with open(_RENDER_PATH) as f:
        tree = ast.parse(f.read(), filename=_RENDER_PATH)
    forbidden = ("mps_guard", "torch", "diffusers", "transformers", "mlx", "PIL",
                 "content_safety", "psutil")
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hits += [a.name for a in node.names if a.name.split(".")[0] in forbidden]
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in forbidden:
                hits.append(node.module)
    check("R2a bin/ltx-mlx-render imports none of mps_guard/torch/diffusers/"
          "transformers/mlx/PIL/content_safety/psutil at any scope", not hits,
          "found %r" % hits)


if __name__ == "__main__":
    test_parser_defaults()
    test_geometry_validation()
    test_run_id_and_story_dir()
    test_render_script_has_no_heavy_imports()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
