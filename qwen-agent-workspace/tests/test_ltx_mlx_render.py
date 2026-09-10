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


# ---------------------------------------------------------------------------
# R3: manifest validation
# ---------------------------------------------------------------------------

def _write_manifest(td, panels, story_id="demo", schema_version=2):
    path = os.path.join(td, "manifest.json")
    with open(path, "w") as f:
        json.dump({"schema_version": schema_version, "story_id": story_id,
                   "fps": 24, "panels": panels}, f)
    return path


def _panel(i, image_path, text="panel text %d", motion=None, num_frames=241):
    return {"index": i, "image_path": image_path, "panel_text": text % i,
            "motion_prompt": motion, "num_frames": num_frames}


def _load_error(path):
    try:
        render.load_manifest(path)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        return str(e)
    return None


def test_load_manifest():
    with tempfile.TemporaryDirectory() as td:
        img = os.path.join(td, "p1.png")
        with open(img, "wb") as f:
            f.write(b"png")

        ok = _write_manifest(td, [_panel(1, img), _panel(2, None)])
        data = render.load_manifest(ok)
        check("R3a valid manifest loads", len(data["panels"]) == 2)
        check("R3b null image_path is accepted as T2V", data["panels"][1]["image_path"] is None,
              "got %r" % data["panels"][1]["image_path"])
        check("R3c story_id preserved", data.get("story_id") == "demo")

        empty = _write_manifest(td, [])
        check("R3d empty panels rejected", "no panels" in (_load_error(empty) or ""),
              "got %r" % _load_error(empty))

        gap = _write_manifest(td, [_panel(1, img), _panel(3, img)])
        msg = _load_error(gap)
        check("R3e non-contiguous index rejected naming the expected index",
              msg is not None and "expected index 2" in msg, "got %r" % msg)

        blank = _write_manifest(td, [dict(_panel(1, img), panel_text="   ")])
        msg = _load_error(blank)
        check("R3f empty panel_text rejected naming the panel",
              msg is not None and "panel 1" in msg and "panel_text" in msg, "got %r" % msg)

        emptystr = _write_manifest(td, [dict(_panel(1, img), image_path="")])
        msg = _load_error(emptystr)
        check("R3g empty-string image_path rejected (not 'absent')",
              msg is not None and "panel 1" in msg and "image_path" in msg, "got %r" % msg)

        missing = _write_manifest(td, [dict(_panel(1, img),
                                            image_path=os.path.join(td, "gone.png"))])
        msg = _load_error(missing)
        check("R3h unreadable image_path rejected naming the panel",
              msg is not None and "panel 1" in msg and "image_path" in msg, "got %r" % msg)

        offlattice = _write_manifest(td, [dict(_panel(1, img), num_frames=240)])
        check("R3i manifest num_frames is NOT validated (--frames is authoritative)",
              _load_error(offlattice) is None, "got %r" % _load_error(offlattice))

        nokey = _write_manifest(td, [{"index": 1, "panel_text": "t"}])
        check("R3j absent image_path key is accepted as T2V",
              render.load_manifest(nokey)["panels"][0]["image_path"] is None)


# ---------------------------------------------------------------------------
# R4: per-panel unit derivation
# ---------------------------------------------------------------------------

def test_build_units():
    panels = [
        {"index": 1, "image_path": "/abs/p1.png", "panel_text": "text one",
         "motion_prompt": "motion one"},
        {"index": 2, "image_path": None, "panel_text": "text two",
         "motion_prompt": None},
        {"index": 3, "image_path": "/abs/p3.png", "panel_text": "text three",
         "motion_prompt": ""},
    ]
    units = render.build_units(panels, seed=100, clips_dir="/clips", run_root="/runs/r1")

    check("R4a one unit per panel", len(units) == 3, "got %d" % len(units))
    check("R4b prompt prefers motion_prompt", units[0]["prompt"] == "motion one",
          "got %r" % units[0]["prompt"])
    check("R4c prompt falls back to panel_text when motion_prompt is None",
          units[1]["prompt"] == "text two", "got %r" % units[1]["prompt"])
    check("R4d prompt falls back to panel_text when motion_prompt is empty",
          units[2]["prompt"] == "text three", "got %r" % units[2]["prompt"])
    check("R4e seed is base + i", [u["seed"] for u in units] == [101, 102, 103],
          "got %r" % [u["seed"] for u in units])
    check("R4f label is panel-<i>", [u["label"] for u in units] == ["panel-1", "panel-2", "panel-3"],
          "got %r" % [u["label"] for u in units])
    check("R4g clip path is panel_%02d.mp4",
          [os.path.basename(u["clip_path"]) for u in units]
          == ["panel_01.mp4", "panel_02.mp4", "panel_03.mp4"],
          "got %r" % [u["clip_path"] for u in units])
    check("R4h clips live under clips_dir",
          all(os.path.dirname(u["clip_path"]) == "/clips" for u in units))
    check("R4i log path is <run_root>/panel_%02d.log",
          units[1]["log_path"] == os.path.join("/runs/r1", "panel_02.log"),
          "got %r" % units[1]["log_path"])
    check("R4j image_path carried through, None stays None",
          [u["image_path"] for u in units] == ["/abs/p1.png", None, "/abs/p3.png"],
          "got %r" % [u["image_path"] for u in units])
    check("R4k log_path is None when run_root is None",
          render.build_units(panels, 0, "/clips")[0]["log_path"] is None)
    check("R4l unit keys are exactly the documented set",
          set(units[0]) == {"index", "label", "seed", "prompt", "image_path",
                            "clip_path", "log_path"},
          "got %r" % sorted(units[0]))


# ---------------------------------------------------------------------------
# R5: --resume clip-reuse predicate
# ---------------------------------------------------------------------------

def test_clip_is_reusable():
    saved = render.clip_frame_count
    try:
        with tempfile.TemporaryDirectory() as td:
            good = os.path.join(td, "good.mp4")
            with open(good, "wb") as f:
                f.write(b"\x00" * 512)
            zero = os.path.join(td, "zero.mp4")
            open(zero, "w").close()
            gone = os.path.join(td, "gone.mp4")

            render.clip_frame_count = lambda p: 241
            check("R5a correct frame count -> reusable",
                  render.clip_is_reusable(good, 241) is True)
            check("R5b missing file -> not reusable",
                  render.clip_is_reusable(gone, 241) is False)
            check("R5c zero-byte file -> not reusable",
                  render.clip_is_reusable(zero, 241) is False)

            render.clip_frame_count = lambda p: 193
            check("R5d wrong frame count -> not reusable",
                  render.clip_is_reusable(good, 241) is False)

            render.clip_frame_count = lambda p: None
            check("R5e ffprobe failure (None) -> not reusable",
                  render.clip_is_reusable(good, 241) is False)
    finally:
        render.clip_frame_count = saved


def test_clip_frame_count_argv():
    saved = render.subprocess.run
    seen = {}
    class P:
        returncode = 0
        stdout = '{"streams":[{"nb_read_packets":"241"}]}'
        stderr = ""
    try:
        render.subprocess.run = lambda argv, **k: (seen.__setitem__("argv", argv), P())[1]
        check("R5h returns parsed int", render.clip_frame_count("/c.mp4") == 241)
        check("R5i exact argv", seen["argv"] == [
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
            "-show_entries", "stream=nb_read_packets", "-print_format", "json", "/c.mp4"],
            "got %r" % seen.get("argv"))
    finally:
        render.subprocess.run = saved


def test_clip_frame_count_survives_missing_ffprobe():
    saved = render.subprocess.run
    try:
        def _boom(*a, **k):
            raise FileNotFoundError(2, "No such file or directory", "ffprobe")
        render.subprocess.run = _boom
        check("R5g ffprobe not installed -> None (no raise)",
              render.clip_frame_count("/x.mp4") is None)
    finally:
        render.subprocess.run = saved


if __name__ == "__main__":
    test_parser_defaults()
    test_geometry_validation()
    test_run_id_and_story_dir()
    test_render_script_has_no_heavy_imports()
    test_load_manifest()
    test_build_units()
    test_clip_is_reusable()
    test_clip_frame_count_argv()
    test_clip_frame_count_survives_missing_ffprobe()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
