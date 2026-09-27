"""Plain-python (no pytest) offline tests for bin/ltx-mlx-render.

Run: python3 tests/test_ltx_mlx_render.py
No GPU, no model weights, no network. The one test that shells out to real
ffmpeg (R9) skips itself with a clear message when ffmpeg is absent.
"""

import contextlib
import glob
import importlib.machinery
import io
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
    check("R1e height 448", a.height == 448, "got %r" % a.height)
    check("R1f frame_rate 24 and is an int", a.frame_rate == 24 and isinstance(a.frame_rate, int),
          "got %r" % a.frame_rate)
    check("R1g seed 0", a.seed == 0, "got %r" % a.seed)
    check("R1h model is the pack id", a.model == "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8",
          "got %r" % a.model)
    check("R1h1 gemma is SKILL.GEMMA_MODEL_ID", a.gemma == render.SKILL.GEMMA_MODEL_ID,
          "got %r" % a.gemma)
    check("R1h2 lora_path defaults to None", a.lora_path is None, "got %r" % a.lora_path)
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
    # "video_" + "backend": the spec's grep gate (12.1 item 5) must not match test sources.
    check("R1af the removed backend flag stays gone",
          not hasattr(a, "video_" + "backend")
          and ("--video-" + "backend") not in render.build_parser().format_help())
    check("R1w SECONDS_PER_PANEL_ESTIMATE is an int", isinstance(
        render.SECONDS_PER_PANEL_ESTIMATE, int), "got %r" % render.SECONDS_PER_PANEL_ESTIMATE)
    with open(_RENDER_PATH) as f:
        _src = f.read()
    check("R1ad SECONDS_PER_PANEL_ESTIMATE is a multiple of 60",
          render.SECONDS_PER_PANEL_ESTIMATE % 60 == 0,
          "got %r" % render.SECONDS_PER_PANEL_ESTIMATE)
    check("R1ae the constant records its A1 provenance",
          "Measured by acceptance test A1" in _src,
          "the estimate must be replaced by the A1 measurement before this ships")


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

        # v3 (bin/ltx-story-manifest --chain): conditioning is required and validated.
        def _v3(panels):
            return _write_manifest(td, panels, schema_version=3)

        good = _v3([{"index": 1, "image_path": img, "panel_text": "t", "conditioning": "still"},
                    {"index": 2, "image_path": None, "panel_text": "m", "conditioning": "chain"},
                    {"index": 3, "image_path": None, "panel_text": "x", "conditioning": "t2v"}])
        check("R3k a valid v3 still/chain/t2v manifest loads",
              [p["conditioning"] for p in render.load_manifest(good)["panels"]]
              == ["still", "chain", "t2v"])
        for label, panels, want in (
                ("R3l missing conditioning",
                 [{"index": 1, "image_path": img, "panel_text": "t"}],
                 "panel 1: conditioning must be one of still/chain/t2v, got None"),
                ("R3m unknown conditioning",
                 [{"index": 1, "image_path": img, "panel_text": "t", "conditioning": "bogus"}],
                 "panel 1: conditioning must be one of still/chain/t2v, got 'bogus'"),
                ("R3n still with a null image_path",
                 [{"index": 1, "image_path": None, "panel_text": "t", "conditioning": "still"}],
                 "panel 1: conditioning 'still' requires an existing, readable image_path"),
                ("R3o chain on panel 1",
                 [{"index": 1, "image_path": None, "panel_text": "t", "conditioning": "chain"}],
                 "panel 1: conditioning 'chain' requires index >= 2 and image_path null"),
                ("R3p chain with an image_path",
                 [{"index": 1, "image_path": img, "panel_text": "t", "conditioning": "still"},
                  {"index": 2, "image_path": img, "panel_text": "m", "conditioning": "chain"}],
                 "panel 2: conditioning 'chain' requires index >= 2 and image_path null"),
                ("R3q t2v with an image_path",
                 [{"index": 1, "image_path": img, "panel_text": "t", "conditioning": "t2v"}],
                 "panel 1: conditioning 't2v' requires image_path null")):
            msg = _load_error(_v3(panels))
            check("%s is rejected with the spec message" % label, msg == want, "got %r" % msg)

        derived = render.load_manifest(_write_manifest(td, [_panel(1, img), _panel(2, None)]))
        check("R3r v2 derives conditioning: image -> still, null -> t2v",
              [p["conditioning"] for p in derived["panels"]] == ["still", "t2v"])
        v1_path = os.path.join(td, "v1.json")
        with open(v1_path, "w") as f:
            json.dump({"story_id": "demo", "panels": [_panel(1, img), _panel(2, None)]}, f)
        check("R3s a v1 manifest (no schema_version) derives the same way",
              [p["conditioning"] for p in render.load_manifest(v1_path)["panels"]]
              == ["still", "t2v"])


# ---------------------------------------------------------------------------
# R4: per-panel unit derivation
# ---------------------------------------------------------------------------

def test_build_units():
    panels = [
        {"index": 1, "image_path": "/abs/p1.png", "panel_text": "text one",
         "motion_prompt": "motion one", "conditioning": "still"},
        {"index": 2, "image_path": None, "panel_text": "text two",
         "motion_prompt": None, "conditioning": "t2v"},
        {"index": 3, "image_path": "/abs/p3.png", "panel_text": "text three",
         "motion_prompt": "", "conditioning": "still"},
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
    check("R4j image_path carried through for still/t2v, None stays None",
          [u["image_path"] for u in units] == ["/abs/p1.png", None, "/abs/p3.png"],
          "got %r" % [u["image_path"] for u in units])
    check("R4k log_path is None when run_root is None",
          render.build_units(panels, 0, "/clips")[0]["log_path"] is None)
    check("R4l unit keys are exactly the documented set",
          set(units[0]) == {"index", "label", "seed", "prompt", "image_path",
                            "clip_path", "log_path", "conditioning", "chain_source"},
          "got %r" % sorted(units[0]))
    check("R4m conditioning is carried and still/t2v units have no chain_source",
          [(u["conditioning"], u["chain_source"]) for u in units]
          == [("still", None), ("t2v", None), ("still", None)])

    chain = [
        {"index": 1, "image_path": "/abs/p1.png", "panel_text": "img", "motion_prompt": "m1",
         "conditioning": "still"},
        {"index": 2, "image_path": None, "panel_text": "m2", "motion_prompt": "m2",
         "conditioning": "chain"},
        {"index": 3, "image_path": None, "panel_text": "m3", "motion_prompt": "m3",
         "conditioning": "chain"},
    ]
    cu = render.build_units(chain, seed=0, clips_dir="/clips")
    check("R4n a still unit keeps its own image_path", cu[0]["image_path"] == "/abs/p1.png")
    check("R4o chain units read a derived <clips>/panel_%02d.chainseed.png",
          [u["image_path"] for u in cu[1:]]
          == ["/clips/panel_02.chainseed.png", "/clips/panel_03.chainseed.png"],
          "got %r" % [u["image_path"] for u in cu[1:]])
    check("R4p chain_source is the previous panel's clip",
          [u["chain_source"] for u in cu] == [None, "/clips/panel_01.mp4", "/clips/panel_02.mp4"],
          "got %r" % [u["chain_source"] for u in cu])
    check("R4q chain units keep seed + i and their Motion: prompt",
          [(u["seed"], u["prompt"]) for u in cu] == [(1, "m1"), (2, "m2"), (3, "m3")])


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

            provenance = {"model_identity": {"resolved_path": td}}
            render.write_clip_provenance(good, provenance)
            render.clip_frame_count = lambda p: 241
            check("R5a correct frame count -> reusable",
                  render.clip_is_reusable(good, 241, provenance) is True)
            check("R5b missing file -> not reusable",
                  render.clip_is_reusable(gone, 241, provenance) is False)
            check("R5c zero-byte file -> not reusable",
                  render.clip_is_reusable(zero, 241, provenance) is False)

            render.clip_frame_count = lambda p: 193
            check("R5d wrong frame count -> not reusable",
                  render.clip_is_reusable(good, 241, provenance) is False)

            render.clip_frame_count = lambda p: None
            check("R5e ffprobe failure (None) -> not reusable",
                  render.clip_is_reusable(good, 241, provenance) is False)
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


def test_probe_streams_survives_missing_ffprobe():
    saved = render.subprocess.run
    try:
        def _boom(*a, **k):
            raise FileNotFoundError(2, "No such file or directory", "ffprobe")
        render.subprocess.run = _boom
        try:
            render.probe_streams("/x.mp4")
            raised = None
        except render.ConcatPreflightError as e:
            raised = e
        except Exception as e:
            raised = e
        check("R5j ffprobe not installed -> ConcatPreflightError (not raw OSError)",
              isinstance(raised, render.ConcatPreflightError), "got %r" % raised)
    finally:
        render.subprocess.run = saved


# ---------------------------------------------------------------------------
# R6: concat list quoting and concat argv
# ---------------------------------------------------------------------------

def test_build_concat_list():
    text = render.build_concat_list(["/abs/clips/panel_01.mp4", "/abs/clips/panel_02.mp4"])
    check("R6a one 'file' line per clip, in order",
          text == "file '/abs/clips/panel_01.mp4'\nfile '/abs/clips/panel_02.mp4'\n",
          "got %r" % text)
    quoted = render.build_concat_list(["/abs/o'brien/panel_01.mp4"])
    check("R6b a single quote is escaped as '\\'' per the concat demuxer rules",
          quoted == "file '/abs/o'\\''brien/panel_01.mp4'\n", "got %r" % quoted)

    try:
        render.build_concat_list(["/abs/clips/panel_0\n1.mp4"])
        raised = None
    except render.ConcatPreflightError as e:
        raised = e
    check("R6e a newline in a clip path raises ConcatPreflightError",
          isinstance(raised, render.ConcatPreflightError), "got %r" % raised)


def test_build_concat_command():
    cmd = render.build_concat_command("/runs/r1/concat_list.txt", "/out/movie.mp4")
    check("R6c golden concat argv",
          cmd == ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                  "-i", "/runs/r1/concat_list.txt", "-c", "copy",
                  "-movflags", "+faststart", "/out/movie.mp4"],
          "got %r" % (cmd,))
    check("R6d never re-encodes", "-c:v" not in cmd and "libx264" not in cmd
          and "-filter_complex" not in cmd, "got %r" % (cmd,))


# ---------------------------------------------------------------------------
# R7: ffprobe uniformity checker, fed synthetic stream dicts
# ---------------------------------------------------------------------------

def _probe(width=704, height=448, rfr="24/1", vcodec="h264", pix="yuv420p",
           acodec="aac", rate="48000", channels=2, n_video=1, n_audio=1):
    streams = []
    for _ in range(n_video):
        streams.append({"codec_type": "video", "codec_name": vcodec, "pix_fmt": pix,
                        "width": width, "height": height, "r_frame_rate": rfr})
    for _ in range(n_audio):
        streams.append({"codec_type": "audio", "codec_name": acodec,
                        "sample_rate": rate, "channels": channels})
    return {"streams": streams}


def _uniform_error(pairs):
    try:
        render.assert_clips_uniform(pairs, 704, 448, 24)
    except render.ConcatPreflightError as e:
        return str(e)
    return None


def test_assert_clips_uniform():
    good = [("/c/panel_01.mp4", _probe()), ("/c/panel_02.mp4", _probe())]
    check("R7a uniform clips pass", _uniform_error(good) is None,
          "got %r" % _uniform_error(good))

    bad_w = [("/c/panel_01.mp4", _probe()), ("/c/panel_02.mp4", _probe(width=640))]
    msg = _uniform_error(bad_w)
    check("R7b differing width raises naming clip and field",
          msg is not None and "panel_02.mp4" in msg and "width" in msg, "got %r" % msg)

    bad_h = [("/c/panel_01.mp4", _probe()), ("/c/panel_02.mp4", _probe(height=360))]
    msg = _uniform_error(bad_h)
    check("R7l differing height raises naming clip and field",
          msg is not None and "panel_02.mp4" in msg and "height" in msg, "got %r" % msg)

    bad_fr = [("/c/panel_01.mp4", _probe(rfr="30/1"))]
    msg = _uniform_error(bad_fr)
    check("R7c differing r_frame_rate raises naming clip and field",
          msg is not None and "panel_01.mp4" in msg and "r_frame_rate" in msg,
          "got %r" % msg)

    no_audio = [("/c/panel_01.mp4", _probe(n_audio=0))]
    msg = _uniform_error(no_audio)
    check("R7d missing audio stream raises naming the clip",
          msg is not None and "panel_01.mp4" in msg and "audio stream" in msg,
          "got %r" % msg)

    two_video = [("/c/panel_01.mp4", _probe(n_video=2))]
    msg = _uniform_error(two_video)
    check("R7e two video streams raises naming the clip",
          msg is not None and "panel_01.mp4" in msg and "video stream" in msg,
          "got %r" % msg)

    bad_codec = [("/c/panel_01.mp4", _probe(vcodec="hevc"))]
    msg = _uniform_error(bad_codec)
    check("R7f wrong video codec raises", msg is not None and "video codec_name" in msg,
          "got %r" % msg)

    bad_pix = [("/c/panel_01.mp4", _probe(pix="yuv444p"))]
    check("R7g wrong pix_fmt raises", "pix_fmt" in (_uniform_error(bad_pix) or ""),
          "got %r" % _uniform_error(bad_pix))

    bad_acodec = [("/c/panel_01.mp4", _probe(acodec="mp3"))]
    check("R7h wrong audio codec raises",
          "audio codec_name" in (_uniform_error(bad_acodec) or ""),
          "got %r" % _uniform_error(bad_acodec))

    bad_rate = [("/c/panel_01.mp4", _probe()), ("/c/panel_02.mp4", _probe(rate="44100"))]
    msg = _uniform_error(bad_rate)
    check("R7i differing sample_rate raises naming the later clip",
          msg is not None and "panel_02.mp4" in msg and "sample_rate" in msg, "got %r" % msg)

    bad_ch = [("/c/panel_01.mp4", _probe()), ("/c/panel_02.mp4", _probe(channels=1))]
    msg = _uniform_error(bad_ch)
    check("R7j differing channel count raises naming the later clip",
          msg is not None and "panel_02.mp4" in msg and "channels" in msg, "got %r" % msg)

    msg = _uniform_error(bad_w)
    check("R7k the error tells the operator to re-render with --force",
          msg is not None and "--force" in msg, "got %r" % msg)


# ---------------------------------------------------------------------------
# R9: REAL ffmpeg concat integration (fast, no GPU) -- required
# ---------------------------------------------------------------------------

def _ffprobe_json(path, *extra):
    proc = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json"]
                          + list(extra) + [path],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return json.loads(proc.stdout) if proc.returncode == 0 else None


def test_real_ffmpeg_concat():
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("SKIP R9 real-ffmpeg concat: ffmpeg/ffprobe not on PATH")
        return
    with tempfile.TemporaryDirectory() as td:
        clips = []
        for i in range(1, 4):
            clip = os.path.join(td, "panel_%02d.mp4" % i)
            proc = subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=704x448:rate=24",
                 "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                 "-t", "1", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", clip],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if proc.returncode != 0:
                check("R9a synthesized clip %d" % i, False, proc.stdout[-800:])
                return
            clips.append(clip)
        check("R9a synthesized three 1s 704x448/24fps clips", len(clips) == 3)

        counts = [render.clip_frame_count(c) for c in clips]
        check("R9b clip_frame_count reads 24 packets per clip", counts == [24, 24, 24],
              "got %r" % counts)

        pairs = [(c, render.probe_streams(c)) for c in clips]
        err = None
        try:
            render.assert_clips_uniform(pairs, 704, 448, 24)
        except render.ConcatPreflightError as e:
            err = str(e)
        check("R9c real preflight passes on real clips", err is None, "got %r" % err)

        list_path = os.path.join(td, "concat_list.txt")
        with open(list_path, "w") as f:
            f.write(render.build_concat_list(clips))
        out = os.path.join(td, "movie.mp4")
        proc = subprocess.run(render.build_concat_command(list_path, out),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        check("R9d real concat exits 0", proc.returncode == 0, proc.stdout[-800:])
        check("R9e movie.mp4 written non-empty",
              os.path.isfile(out) and os.path.getsize(out) > 0)

        info = _ffprobe_json(out, "-show_format", "-show_streams")
        check("R9f ffprobe reads the result", info is not None)
        if info:
            duration = float(info["format"]["duration"])
            check("R9g duration within 0.1s of 3.0s", abs(duration - 3.0) <= 0.1,
                  "got %.3f" % duration)
            v = [s for s in info["streams"] if s["codec_type"] == "video"]
            a = [s for s in info["streams"] if s["codec_type"] == "audio"]
            check("R9h exactly one video stream, h264", len(v) == 1
                  and v[0]["codec_name"] == "h264", "got %r" % v)
            check("R9i exactly one audio stream, aac", len(a) == 1
                  and a[0]["codec_name"] == "aac", "got %r" % a)


def test_real_clip_frame_count_smoke():
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("SKIP R9j real clip_frame_count smoke: ffmpeg/ffprobe not on PATH")
        return
    with tempfile.TemporaryDirectory() as td:
        clip = os.path.join(td, "smoke.mp4")
        proc = subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=24",
             "-frames:v", "24", clip],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        check("R9j synthesized 24-frame clip", proc.returncode == 0, proc.stdout[-800:])
        check("R9k clip_frame_count reads 24 on a real clip",
              render.clip_frame_count(clip) == 24,
              "got %r" % render.clip_frame_count(clip))


def test_probe_timeout_kwarg_present():
    import inspect
    src = inspect.getsource(render.probe_streams)
    check("R9l probe_streams handles subprocess.TimeoutExpired",
          "TimeoutExpired" in src)
    check("R9m probe_streams passes timeout=60", "timeout=60" in src)

    src = inspect.getsource(render.clip_frame_count)
    check("R9n clip_frame_count handles subprocess.TimeoutExpired",
          "TimeoutExpired" in src)
    check("R9o clip_frame_count passes timeout=60", "timeout=60" in src)


# ---------------------------------------------------------------------------
# R8: wall-clock estimate
# ---------------------------------------------------------------------------

def _write_summary(story_dir, run_id, units, **over):
    run_root = os.path.join(story_dir, "runs", run_id)
    os.makedirs(run_root, exist_ok=True)
    summary = {"schema_version": 3, "backend": "ltx-2-mlx", "frames_per_panel": 241, "width": 704,
               "height": 448, "low_ram": True, "tile_frames": 1, "tile_spatial": 1,
               "model": render.SKILL.MODEL_ID, "units": units}
    summary.update(over)
    with open(os.path.join(run_root, "story_summary.json"), "w") as f:
        json.dump(summary, f)
    return run_root


def test_estimate_default_source():
    with tempfile.TemporaryDirectory() as td:
        secs, label = render.estimate_seconds_per_panel(td, 241, 704, 448, True, 1, 1,
                                                         render.SKILL.MODEL_ID)
        check("R8a no summaries -> default constant",
              secs == float(render.SECONDS_PER_PANEL_ESTIMATE), "got %r" % secs)
        check("R8b default label",
              label == "default estimate (unmeasured for this configuration)",
              "got %r" % label)


def test_estimate_measured_source():
    with tempfile.TemporaryDirectory() as td:
        units = [{"unit": "panel-%d" % i, "status": "ok", "resumed": False,
                  "seconds": s} for i, s in enumerate([1200.0, 1500.0, 1800.0], start=1)]
        _write_summary(td, "20260910T010101Z-aaaaaaaa", units)
        secs, label = render.estimate_seconds_per_panel(td, 241, 704, 448, True, 1, 1,
                                                         render.SKILL.MODEL_ID)
        check("R8c measured mean of the three ok units", abs(secs - 1500.0) < 1e-9,
              "got %r" % secs)
        check("R8d measured label names the run id and panel count",
              label == "measured (20260910T010101Z-aaaaaaaa, 3 panels)", "got %r" % label)


def test_estimate_excludes_resumed_and_mismatched():
    with tempfile.TemporaryDirectory() as td:
        _write_summary(td, "20260910T020202Z-bbbbbbbb",
                       [{"unit": "panel-1", "status": "ok", "resumed": False,
                         "seconds": 900.0}],
                       frames_per_panel=193)
        secs, label = render.estimate_seconds_per_panel(td, 241, 704, 448, True, 1, 1,
                                                         render.SKILL.MODEL_ID)
        check("R8e a config-mismatched summary is ignored",
              secs == float(render.SECONDS_PER_PANEL_ESTIMATE), "got %r" % secs)

        _write_summary(td, "20260910T030303Z-cccccccc",
                       [{"unit": "panel-1", "status": "ok", "resumed": True,
                         "seconds": 0.0},
                        {"unit": "panel-2", "status": "ok", "resumed": False,
                         "seconds": 2000.0},
                        {"unit": "panel-3", "status": "error", "resumed": False,
                         "seconds": 30.0}])
        secs, label = render.estimate_seconds_per_panel(td, 241, 704, 448, True, 1, 1,
                                                         render.SKILL.MODEL_ID)
        check("R8f resumed (seconds 0.0) and error units are excluded from the mean",
              abs(secs - 2000.0) < 1e-9, "got %r" % secs)
        check("R8g label counts only the units used", "1 panels" in label, "got %r" % label)


def test_estimate_prefers_newest_matching_summary():
    with tempfile.TemporaryDirectory() as td:
        older = _write_summary(td, "20260910T010101Z-aaaaaaaa",
                               [{"unit": "panel-1", "status": "ok", "resumed": False,
                                 "seconds": 1000.0}])
        os.utime(os.path.join(older, "story_summary.json"), (1000, 1000))
        newer = _write_summary(td, "20260910T020202Z-bbbbbbbb",
                               [{"unit": "panel-1", "status": "ok", "resumed": False,
                                 "seconds": 2000.0}])
        os.utime(os.path.join(newer, "story_summary.json"), (2000, 2000))
        secs, label = render.estimate_seconds_per_panel(td, 241, 704, 448, True, 1, 1,
                                                         render.SKILL.MODEL_ID)
        check("R8m the newer matching summary wins over the older one",
              abs(secs - 2000.0) < 1e-9, "got %r" % secs)
        check("R8n the label names the newer run id",
              "20260910T020202Z-bbbbbbbb" in label, "got %r" % label)


def test_estimate_skips_corrupt_summary():
    with tempfile.TemporaryDirectory() as td:
        good = _write_summary(td, "20260910T040404Z-dddddddd",
                              [{"unit": "panel-1", "status": "ok", "resumed": False,
                                "seconds": 1500.0}])
        os.utime(os.path.join(good, "story_summary.json"), (1000, 1000))
        corrupt_dir = os.path.join(td, "runs", "20260910T050505Z-eeeeeeee")
        os.makedirs(corrupt_dir, exist_ok=True)
        with open(os.path.join(corrupt_dir, "story_summary.json"), "w") as f:
            f.write("[1, 2, 3]")
        os.utime(os.path.join(corrupt_dir, "story_summary.json"), (2000, 2000))
        secs, label = render.estimate_seconds_per_panel(td, 241, 704, 448, True, 1, 1,
                                                         render.SKILL.MODEL_ID)
        check("R8o a corrupt (non-dict) summary is skipped without crashing",
              abs(secs - 1500.0) < 1e-9, "got %r" % secs)


def test_estimate_order_independent_of_glob_order():
    with tempfile.TemporaryDirectory() as td:
        old_dir = _write_summary(td, "20260910T010101Z-aaaaaaaa",
                                 [{"unit": "panel-1", "status": "ok", "resumed": False,
                                   "seconds": 1000.0}])
        old_path = os.path.join(old_dir, "story_summary.json")
        os.utime(old_path, (1000, 1000))
        new_dir = _write_summary(td, "20260910T020202Z-bbbbbbbb",
                                 [{"unit": "panel-1", "status": "ok", "resumed": False,
                                   "seconds": 2000.0}])
        new_path = os.path.join(new_dir, "story_summary.json")
        os.utime(new_path, (2000, 2000))

        real_glob = render.glob.glob
        try:
            for order in ([old_path, new_path], [new_path, old_path]):
                render.glob.glob = lambda pat, _o=order: list(_o)
                secs, label = render.estimate_seconds_per_panel(
                    td, 241, 704, 448, True, 1, 1, render.SKILL.MODEL_ID)
                check("R8p newest wins regardless of glob order (%r)" % order,
                      abs(secs - 2000.0) < 1e-9, "got %r for order %r" % (secs, order))
        finally:
            render.glob.glob = real_glob


def test_estimate_dangling_path_sorts_last_not_fatal():
    with tempfile.TemporaryDirectory() as td:
        good_dir = _write_summary(td, "20260910T030303Z-cccccccc",
                                  [{"unit": "panel-1", "status": "ok", "resumed": False,
                                    "seconds": 1234.0}])
        good_path = os.path.join(good_dir, "story_summary.json")
        os.utime(good_path, (1000, 1000))
        dangling_path = os.path.join(td, "runs", "does-not-exist", "story_summary.json")

        real_glob = render.glob.glob
        try:
            render.glob.glob = lambda pat: [dangling_path, good_path]
            secs, label = render.estimate_seconds_per_panel(
                td, 241, 704, 448, True, 1, 1, render.SKILL.MODEL_ID)
            check("R8q a dangling glob result does not crash and the real summary is used",
                  abs(secs - 1234.0) < 1e-9, "got %r" % secs)
        finally:
            render.glob.glob = real_glob


def test_estimate_mtime_tie_break_is_deterministic():
    with tempfile.TemporaryDirectory() as td:
        dir_a = _write_summary(td, "20260910T040404Z-dddddddd",
                               [{"unit": "panel-1", "status": "ok", "resumed": False,
                                 "seconds": 111.0}])
        path_a = os.path.join(dir_a, "story_summary.json")
        dir_b = _write_summary(td, "20260910T050505Z-eeeeeeee",
                               [{"unit": "panel-1", "status": "ok", "resumed": False,
                                 "seconds": 222.0}])
        path_b = os.path.join(dir_b, "story_summary.json")
        os.utime(path_a, (5000, 5000))
        os.utime(path_b, (5000, 5000))

        real_glob = render.glob.glob
        try:
            results = set()
            for order in ([path_a, path_b], [path_b, path_a]):
                render.glob.glob = lambda pat, _o=order: list(_o)
                secs, _ = render.estimate_seconds_per_panel(
                    td, 241, 704, 448, True, 1, 1, render.SKILL.MODEL_ID)
                results.add(secs)
            check("R8r identical mtimes resolve deterministically regardless of glob order",
                  len(results) == 1, "got multiple results across glob orders: %r" % results)
        finally:
            render.glob.glob = real_glob


def test_estimate_model_key_gates_reuse():
    with tempfile.TemporaryDirectory() as td:
        _write_summary(td, "20260910T060606Z-ffffffff",
                       [{"unit": "panel-1", "status": "ok", "resumed": False,
                         "seconds": 999.0}], model="some-other-model")
        secs_same, _ = render.estimate_seconds_per_panel(
            td, 241, 704, 448, True, 1, 1, "some-other-model")
        check("R8s matching model reuses the measurement",
              abs(secs_same - 999.0) < 1e-9, "got %r" % secs_same)
        secs_diff, label_diff = render.estimate_seconds_per_panel(
            td, 241, 704, 448, True, 1, 1, render.SKILL.MODEL_ID)
        check("R8t mismatched model falls back to the default estimate",
              secs_diff == float(render.SECONDS_PER_PANEL_ESTIMATE), "got %r" % secs_diff)


def test_estimate_handles_null_units_and_non_dict_entries():
    with tempfile.TemporaryDirectory() as td:
        run_root = os.path.join(td, "runs", "20260910T070707Z-99999999")
        os.makedirs(run_root, exist_ok=True)
        with open(os.path.join(run_root, "story_summary.json"), "w") as f:
            json.dump({"backend": "ltx-2-mlx", "frames_per_panel": 241, "width": 704, "height": 448,
                      "low_ram": True, "tile_frames": 1, "tile_spatial": 1,
                      "model": render.SKILL.MODEL_ID, "units": None}, f)
        secs, label = render.estimate_seconds_per_panel(
            td, 241, 704, 448, True, 1, 1, render.SKILL.MODEL_ID)
        check("R8u units:null does not crash, falls back to default",
              secs == float(render.SECONDS_PER_PANEL_ESTIMATE), "got %r" % secs)

        run_root2 = os.path.join(td, "runs", "20260910T080808Z-88888888")
        os.makedirs(run_root2, exist_ok=True)
        with open(os.path.join(run_root2, "story_summary.json"), "w") as f:
            json.dump({"backend": "ltx-2-mlx", "frames_per_panel": 241, "width": 704, "height": 448,
                      "low_ram": True, "tile_frames": 1, "tile_spatial": 1,
                      "model": render.SKILL.MODEL_ID,
                      "units": ["not-a-dict", {"status": "ok", "resumed": False,
                                                "seconds": 555.0}]}, f)
        secs2, label2 = render.estimate_seconds_per_panel(
            td, 241, 704, 448, True, 1, 1, render.SKILL.MODEL_ID)
        check("R8v a non-dict unit entry alongside a good one does not crash",
              abs(secs2 - 555.0) < 1e-9, "got %r" % secs2)


def test_format_estimate_lines():
    lines = render.format_estimate_lines(2400.0, "default estimate (unmeasured for "
                                         "this configuration)", 3, 3)
    check("R8h single line when nothing is skipped", len(lines) == 1, "got %r" % lines)
    check("R8i exact estimate line format",
          lines[0] == "estimated render time: 3 panels x 40.0 min = 2.0 h  "
                      "[source: default estimate (unmeasured for this configuration)]",
          "got %r" % lines[0])

    lines = render.format_estimate_lines(2400.0, "measured (r1, 2 panels)", 1, 3)
    check("R8j second line appears when panels are skipped", len(lines) == 2,
          "got %r" % lines)
    check("R8k exact skipped line format",
          lines[1] == "  (2 of 3 panels already rendered and will be skipped)",
          "got %r" % lines[1])
    check("R8l estimate line uses the render count, not the total",
          lines[0].startswith("estimated render time: 1 panels x 40.0 min = 0.7 h"),
          "got %r" % lines[0])


# ---------------------------------------------------------------------------
# R10: --dry-run output (all seven items)
# ---------------------------------------------------------------------------

def _run_render(argv, cwd=None):
    return subprocess.run([sys.executable, _RENDER_PATH] + argv,
                          capture_output=True, text=True, cwd=cwd or WS)


def test_dry_run_output():
    with tempfile.TemporaryDirectory() as td:
        img = os.path.join(td, "p1.png")
        with open(img, "wb") as f:
            f.write(b"png")
        manifest = _write_manifest(td, [_panel(1, img), _panel(2, None), _panel(3, img)],
                                   story_id="drydemo")
        clips = os.path.join(td, "clips")
        os.makedirs(clips)
        out = os.path.join(td, "movie.mp4")

        r = _run_render([manifest, out, "--clips-dir", clips, "--dry-run"])
        o = r.stdout
        check("R10a exits 0", r.returncode == 0, "rc=%r stderr=%r" % (r.returncode, r.stderr))
        check("R10b names the manifest path", os.path.abspath(manifest) in o, "got %r" % o)
        check("R10c names the story id", "story id: drydemo" in o, "got %r" % o)
        check("R10d names the panel count", "panels: 3" in o, "got %r" % o)
        check("R10e marks I2V panels with their image path",
              ("panel  1: I2V %s" % img) in o, "got %r" % o)
        check("R10f marks T2V panels", "panel  2: T2V (no conditioning image)" in o,
              "got %r" % o)
        check("R10g resolved geometry line",
              "geometry: 704x448, 241 frames @ 24 fps = 10.04 s per panel" in o, "got %r" % o)
        check("R10h total line", "total: 3 panels x 10.04 s = 30.12 s of finished movie" in o,
              "got %r" % o)
        check("R10i the num_frames-ignored note",
              "note: manifest per-panel num_frames is ignored; --frames 241 is authoritative"
              in o, "got %r" % o)
        check("R10j the first render command is shown, shlex-joined",
              "first render command:" in o and "--distilled" in o and "--frame-rate 24" in o,
              "got %r" % o)
        check("R10j1 the first render command carries --gemma with the default GEMMA_MODEL_ID",
              ("--gemma %s" % render.SKILL.GEMMA_MODEL_ID) in o, "got %r" % o)

        r2 = _run_render([manifest, out, "--clips-dir", clips, "--dry-run",
                          "--gemma", "Other/Gemma"])
        check("R10j2 a non-default --gemma reaches the first render command",
              "--gemma Other/Gemma" in r2.stdout, "got %r" % r2.stdout)
        check("R10k the estimate line is present",
              "estimated render time: 3 panels x" in o and "[source: default estimate" in o,
              "got %r" % o)
        check("R10l nothing was written", not os.path.exists(out)
              and os.listdir(clips) == [], "clips=%r" % os.listdir(clips))
        check("R10m no runs/ directory was created",
              not os.path.isdir(os.path.join(render.story_dir_for("drydemo"), "runs"))
              or not glob_has_new_run("drydemo"), "a run root was created under --dry-run")


def glob_has_new_run(story_id):
    import glob as _g
    return bool(_g.glob(os.path.join(render.story_dir_for(story_id), "runs", "*")))


def test_manifest_without_story_id_falls_back():
    """A manifest with no story_id must fall back to "story"; without the
    fallback story_dir_for(None) raises TypeError deep in os.path.join."""
    with tempfile.TemporaryDirectory() as td:
        img = os.path.join(td, "p1.png")
        with open(img, "wb") as f:
            f.write(b"png")
        path = os.path.join(td, "no_story_id.json")
        with open(path, "w") as f:
            json.dump({"schema_version": 2, "fps": 24, "panels": [_panel(1, img)]}, f)
        r = _run_render([path, os.path.join(td, "movie.mp4"),
                         "--clips-dir", os.path.join(td, "clips"), "--dry-run"])
        check("R10v a manifest with no story_id falls back to 'story'",
              r.returncode == 0 and "story id: story" in r.stdout,
              "rc=%r stdout=%r stderr=%r" % (r.returncode, r.stdout, r.stderr))


def test_dry_run_validates_output_path():
    """--dry-run is the human review gate bin/ltx-movie Phase 3 shows before
    Phase 4 renders, so it must reject the output paths Phase 4 would reject.
    These three checks are pure reads, so --dry-run still touches nothing."""
    with tempfile.TemporaryDirectory() as td:
        img = os.path.join(td, "p1.png")
        with open(img, "wb") as f:
            f.write(b"png")
        manifest = _write_manifest(td, [_panel(1, img)], story_id="dryvalidate")
        clips = os.path.join(td, "clips")
        os.makedirs(clips)
        out = os.path.join(td, "movie.mp4")

        r = _run_render([manifest, os.path.join(td, "movie.mov"), "--clips-dir", clips,
                         "--dry-run"])
        check("R10p --dry-run rejects a non-.mp4 output with exit 2",
              r.returncode == 2 and "must end in .mp4" in r.stderr,
              "rc=%r stderr=%r" % (r.returncode, r.stderr))

        r = _run_render([manifest, os.path.join(td, "missing_dir", "m.mp4"),
                         "--clips-dir", clips, "--dry-run"])
        check("R10q --dry-run rejects a missing output directory with exit 2",
              r.returncode == 2 and "output directory not writable" in r.stderr,
              "rc=%r stderr=%r" % (r.returncode, r.stderr))

        with open(out, "wb") as f:
            f.write(b"x")
        r = _run_render([manifest, out, "--clips-dir", clips, "--dry-run"])
        check("R10r --dry-run rejects an existing output without --force",
              r.returncode == 2 and "--force" in r.stderr,
              "rc=%r stderr=%r" % (r.returncode, r.stderr))

        r = _run_render([manifest, out, "--clips-dir", clips, "--dry-run", "--force"])
        check("R10s --dry-run with --force accepts an existing output",
              r.returncode == 0, "rc=%r stderr=%r" % (r.returncode, r.stderr))

        check("R10t --dry-run still touched nothing", os.listdir(clips) == [],
              "clips=%r" % os.listdir(clips))

        # The ffmpeg/ltx-2-mlx checks must STAY below the short-circuit: a dry
        # run has to remain usable on a host that cannot render.
        r = subprocess.run(
            [sys.executable, _RENDER_PATH, manifest, os.path.join(td, "ok.mp4"),
             "--clips-dir", clips, "--dry-run"],
            capture_output=True, text=True, cwd=WS,
            env=dict(os.environ, LTX2_MLX_BIN=os.path.join(td, "no-such-bin")))
        check("R10u --dry-run still works with no ltx-2-mlx binary installed",
              r.returncode == 0, "rc=%r stderr=%r" % (r.returncode, r.stderr))


def test_dry_run_resume_lines():
    saved = render.clip_frame_count
    try:
        with tempfile.TemporaryDirectory() as td:
            img = os.path.join(td, "p1.png")
            with open(img, "wb") as f:
                f.write(b"png")
            manifest = _write_manifest(td, [_panel(1, img), _panel(2, img)],
                                       story_id="resdemo")
            clips = os.path.join(td, "clips")
            os.makedirs(clips)
            with open(os.path.join(clips, "panel_01.mp4"), "wb") as f:
                f.write(b"\x00" * 64)
            out = os.path.join(td, "movie.mp4")

            r = _run_render([manifest, out, "--clips-dir", clips, "--resume",
                             "--dry-run", "--frames", "241"])
            o = r.stdout
            check("R10n --resume dry-run exits 0", r.returncode == 0,
                  "rc=%r stderr=%r" % (r.returncode, r.stderr))
            check("R10o resume lines name skipped and rendering panels",
                  "resume:" in o and "would render" in o, "got %r" % o)
    finally:
        render.clip_frame_count = saved


# ---------------------------------------------------------------------------
# R11: the input content screen is a THROWAWAY SUBPROCESS, and it is live
# ---------------------------------------------------------------------------

def test_input_content_screen_shape():
    import inspect
    src = inspect.getsource(render.run_input_content_screen)
    check("R11a screens in a child process, not in-process",
          "sys.executable" in src and '"-c"' in src, "src=%r" % src)
    check("R11b the child imports content_safety, this process never does",
          "import content_safety" in src, "src=%r" % src)
    check("R11c the child prints SCREEN_OK / SCREEN_BLOCKED",
          "SCREEN_OK" in src and "SCREEN_BLOCKED" in src, "src=%r" % src)
    check("R11d the child exits 3 on a block", "sys.exit(3)" in src, "src=%r" % src)
    check("R11e the skill label is ltx-mlx-render", "ltx-mlx-render" in src, "src=%r" % src)

    with open(_RENDER_PATH) as f:
        text = f.read()
    check("R11f the call site is LIVE, not commented out",
          "rc = run_input_content_screen(" in text
          and "#rc = run_input_content_screen(" not in text
          and "# rc = run_input_content_screen(" not in text,
          "the ported screen must actually run in this path")


def test_input_content_screen_empty_list_is_cheap():
    rc = render.run_input_content_screen([])
    check("R11g screening zero images returns 0 without importing anything heavy",
          rc == 0, "got %r" % rc)


def test_input_content_screen_behavioral():
    """Actually runs run_input_content_screen's child subprocess against a
    real stub content_safety.py, rather than just grepping source text."""
    saved_ws = render.WS
    try:
        with tempfile.TemporaryDirectory() as td:
            stub_src = (
                "import os\n"
                "class ContentSafetyError(Exception):\n"
                "    pass\n"
                "def assert_image_safe(img, skill=None, prompt=None):\n"
                "    with open(os.path.join(os.path.dirname(__file__), 'skill_seen.txt'), 'a') as f:\n"
                "        f.write(repr(skill) + '\\n')\n"
                "    if skill != 'ltx-mlx-render':\n"
                "        raise SystemExit('BAD_SKILL %r' % (skill,))\n"
                "    if os.path.basename(prompt).startswith('blocked'):\n"
                "        raise ContentSafetyError('blocked marker found')\n"
            )
            with open(os.path.join(td, "content_safety.py"), "w") as f:
                f.write(stub_src)

            # PIL is a real dependency the child script imports; stub it too
            # so this test has no dependency on torch/transformers being
            # installed for real image safety classification.
            pil_dir = os.path.join(td, "PIL")
            os.makedirs(pil_dir, exist_ok=True)
            with open(os.path.join(pil_dir, "__init__.py"), "w") as f:
                # open() checks the path exists (like real PIL does) so the
                # missing-path case below actually fails closed.
                f.write("import builtins\n"
                       "class Image:\n"
                       "    @staticmethod\n"
                       "    def open(p):\n"
                       "        builtins.open(p, 'rb').close()\n"
                       "        class _Img:\n"
                       "            def convert(self, mode):\n"
                       "                return self\n"
                       "        return _Img()\n")

            render.WS = td

            clean_paths = [os.path.join(td, "ok1.png"), os.path.join(td, "ok2.png")]
            for p in clean_paths:
                open(p, "wb").close()
            rc = render.run_input_content_screen(clean_paths)
            check("R11h all-clean images screen through with rc 0", rc == 0, "got %r" % rc)

            with open(os.path.join(td, "skill_seen.txt")) as f:
                seen = [ln.strip() for ln in f if ln.strip()]
            check("R11k the safety call is actually reached with skill='ltx-mlx-render', once per image",
                  seen == ["'ltx-mlx-render'"] * 2, "got %r" % seen)

            blocked_path = os.path.join(td, "blocked.png")
            open(blocked_path, "wb").close()
            never_reached = os.path.join(td, "never_reached.png")
            open(never_reached, "wb").close()
            rc2 = render.run_input_content_screen([clean_paths[0], blocked_path, never_reached])
            check("R11i a blocked image in the middle of the list stops the run with rc 3",
                  rc2 == 3, "got %r" % rc2)

            missing_path = os.path.join(td, "does_not_exist.png")
            rc3 = render.run_input_content_screen([missing_path])
            check("R11j a nonexistent image path fails closed (nonzero rc)",
                  rc3 != 0, "got %r" % rc3)

            # R11l: the metacharacters live in the FINAL path segment (no "/"
            # inside it, or open() would treat them as directories). The
            # sentinel is a bare relative name, and run_input_content_screen
            # passes no cwd= to subprocess.run, so the child inherits ours --
            # we chdir to td across the call to make td/PWNED the one and only
            # place a shelled-out `touch PWNED` could land.
            weird = os.path.join(td, "it's a $(touch PWNED) ; file.png")
            open(weird, "wb").close()
            sentinel = os.path.join(td, "PWNED")
            saved_cwd = os.getcwd()
            try:
                os.chdir(td)
                rc4 = render.run_input_content_screen([weird])
            finally:
                os.chdir(saved_cwd)
            check("R11l a path with quote/$()/; is passed as argv, never interpolated or shelled out",
                  rc4 == 0 and not os.path.exists(sentinel),
                  "rc=%r sentinel_exists=%r" % (rc4, os.path.exists(sentinel)))
    finally:
        render.WS = saved_ws


# ---------------------------------------------------------------------------
# R12: render_panel maps skill outcomes onto unit statuses
# ---------------------------------------------------------------------------

def _stub_args(**over):
    a = render.build_parser().parse_args(["/tmp/m.json", "/tmp/o.mp4"])
    for k, v in over.items():
        setattr(a, k, v)
    return a


def _render_panel_capturing_stderr(unit, args):
    """Call render_panel with sys.stderr redirected; return (result, stderr).

    render_panel's jetsam remediation ladder is written to stderr and is the
    only operator-facing output of a jetsam kill, so it has to be asserted on
    directly -- asserting the JETSAM_LADDER constant's text proves nothing
    about whether anything ever prints it."""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        res = render.render_panel(unit, args)
    return res, buf.getvalue()


def test_render_panel_statuses():
    saved = render.SKILL.generate_video
    saved_verification = (render.build_clip_provenance, render.write_clip_provenance,
                          render.clip_frame_count, render.probe_streams, render.assert_clips_uniform)
    render.build_clip_provenance = lambda unit, args, **kwargs: {"model_identity": None}
    render.write_clip_provenance = lambda clip, provenance: None
    render.clip_frame_count = lambda clip: 145
    render.probe_streams = lambda clip: {}
    render.assert_clips_uniform = lambda *args: None
    try:
        # Every field below is deliberately distinct from every other field
        # and from build_parser()'s defaults, so that an argument-swap or a
        # hardcoded-constant mutation in render_panel cannot pass.
        unit = {"index": 1, "label": "panel-1", "seed": 7, "prompt": "p",
                "image_path": "/tmp/in.png", "clip_path": "/tmp/panel_01.mp4",
                "log_path": "/tmp/panel_01.log"}
        args = _stub_args(width=640, height=384, frames=145, frame_rate=25,
                          model="test-model", no_low_ram=True, tile_frames=2,
                          tile_spatial=3, panel_timeout=11)

        calls = []

        def _ok(*a, **k):
            calls.append((a, k))
            # Deliberately NOT unit["clip_path"]: the skill returns
            # os.path.abspath(output_path), and R12c must prove that
            # render_panel records the skill's return value rather than
            # re-deriving the path from the unit.
            return "/tmp/abs/panel_01.mp4"
        render.SKILL.generate_video = _ok
        res = render.render_panel(unit, args)
        check("R12a success -> status ok", res["status"] == "ok", "got %r" % res)
        check("R12b success -> attempts 1", res["attempts"] == 1, "got %r" % res)
        check("R12c success -> the skill's returned clip path is recorded",
              res["clip"] == "/tmp/abs/panel_01.mp4", "got %r" % res)
        check("R12d success -> resumed False", res["resumed"] is False, "got %r" % res)
        check("R12e success -> seconds is a float", isinstance(res["seconds"], float),
              "got %r" % res)
        check("R12f unit label carried", res["unit"] == "panel-1", "got %r" % res)

        check("R12t1 exactly one skill call", len(calls) == 1, "got %r" % (calls,))
        pos, kw = calls[0] if calls else ((), {})
        check("R12t2 prompt and clip path are the positional args",
              pos == ("p", "/tmp/panel_01.mp4"), "got %r" % (pos,))
        check("R12t3 force=True is passed unconditionally", kw.get("force") is True,
              "got %r" % (kw,))
        check("R12t4 image_path comes from the unit",
              kw.get("image_path", "MISSING") == "/tmp/in.png", "got %r" % (kw,))
        check("R12t5 seed comes from the unit", kw.get("seed") == 7, "got %r" % (kw,))
        check("R12t6 log_path comes from the unit",
              kw.get("log_path", "MISSING") == "/tmp/panel_01.log", "got %r" % (kw,))
        check("R12t7 num_frames comes from --frames", kw.get("num_frames") == 145,
              "got %r" % (kw,))
        check("R12t8 frame_rate comes from --frame-rate", kw.get("frame_rate") == 25,
              "got %r" % (kw,))
        check("R12t9 width and height are not swapped",
              (kw.get("width"), kw.get("height")) == (640, 384), "got %r" % (kw,))
        check("R12t10 model comes from --model", kw.get("model") == "test-model",
              "got %r" % (kw,))
        check("R12t11 tile_frames and tile_spatial are not swapped",
              (kw.get("tile_frames"), kw.get("tile_spatial")) == (2, 3), "got %r" % (kw,))
        check("R12t12 low_ram is the inverse of --no-low-ram",
              kw.get("low_ram") is False, "got %r" % (kw,))
        check("R12t13 timeout_s comes from --panel-timeout", kw.get("timeout_s") == 11,
              "got %r" % (kw,))

        def _raise_value(*a, **k):
            raise ValueError("bad image")
        render.SKILL.generate_video = _raise_value
        res, err = _render_panel_capturing_stderr(unit, args)
        check("R12g ValueError -> status invalid", res["status"] == "invalid", "got %r" % res)
        check("R12h invalid -> clip None", res["clip"] is None, "got %r" % res)

        def _raise_rc1(*a, **k):
            raise render.SKILL.Ltx2MlxError("boom", returncode=1, cmd=[],
                                            stderr_tail="tail", output_path="/tmp/x.mp4")
        render.SKILL.generate_video = _raise_rc1
        res, err = _render_panel_capturing_stderr(unit, args)
        check("R12i non-zero rc -> status error", res["status"] == "error", "got %r" % res)
        check("R12j rc recorded", res.get("rc") == 1, "got %r" % res)
        check("R12p non-zero rc is not flagged jetsam", "jetsam" not in res, "got %r" % res)
        check("R12p2 non-zero rc does not print the jetsam ladder",
              render.JETSAM_LADDER not in err, "got %r" % err)

        def _raise_timeout(*a, **k):
            raise render.SKILL.Ltx2MlxError("slow", returncode=-9, cmd=[],
                                            stderr_tail="", output_path="/tmp/x.mp4",
                                            timed_out=True)
        render.SKILL.generate_video = _raise_timeout
        res, err = _render_panel_capturing_stderr(unit, args)
        check("R12k timeout -> status timeout", res["status"] == "timeout", "got %r" % res)

        # A timeout whose returncode is NOT -9: status must be keyed on
        # timed_out, never on a particular return code.
        def _raise_timeout_rc_none(*a, **k):
            raise render.SKILL.Ltx2MlxError("slow", returncode=None, cmd=[],
                                            stderr_tail="", output_path="/tmp/x.mp4",
                                            timed_out=True)
        render.SKILL.generate_video = _raise_timeout_rc_none
        res, err = _render_panel_capturing_stderr(unit, args)
        check("R12r timeout with rc None -> status timeout", res["status"] == "timeout",
              "got %r" % res)

        # The converse: rc -9 without timed_out is a signal kill, not a
        # timeout (the parent itself was killed), and is a plain error.
        def _raise_rc_neg9_no_timeout(*a, **k):
            raise render.SKILL.Ltx2MlxError("killed", returncode=-9, cmd=[],
                                            stderr_tail="", output_path="/tmp/x.mp4")
        render.SKILL.generate_video = _raise_rc_neg9_no_timeout
        res, err = _render_panel_capturing_stderr(unit, args)
        check("R12s rc -9 without timed_out -> status error", res["status"] == "error",
              "got %r" % res)
        check("R12s2 rc -9 without timed_out is not flagged jetsam",
              "jetsam" not in res, "got %r" % res)

        def _raise_jetsam(*a, **k):
            raise render.SKILL.Ltx2MlxError("no output", returncode=0, cmd=[],
                                            stderr_tail="", output_path="/tmp/x.mp4")
        render.SKILL.generate_video = _raise_jetsam
        res, err = _render_panel_capturing_stderr(unit, args)
        check("R12l jetsam signature -> status error", res["status"] == "error",
              "got %r" % res)
        check("R12m jetsam signature is flagged for the ladder message",
              res.get("jetsam") is True, "got %r" % res)
        check("R12o jetsam signature prints the remediation ladder to stderr",
              render.JETSAM_LADDER in err, "got %r" % err)

        # The watchdog can fire in the window where the child has already
        # exited 0, so rc 0 AND timed_out is reachable: timeout must win and
        # the ladder must stay quiet.
        def _raise_timeout_rc0(*a, **k):
            raise render.SKILL.Ltx2MlxError("slow", returncode=0, cmd=[],
                                            stderr_tail="", output_path="/tmp/x.mp4",
                                            timed_out=True)
        render.SKILL.generate_video = _raise_timeout_rc0
        res, err = _render_panel_capturing_stderr(unit, args)
        check("R12q rc 0 with timed_out -> status timeout", res["status"] == "timeout",
              "got %r" % res)
        check("R12q2 rc 0 with timed_out is not flagged jetsam", "jetsam" not in res,
              "got %r" % res)
        check("R12q3 rc 0 with timed_out does not print the jetsam ladder",
              render.JETSAM_LADDER not in err, "got %r" % err)
    finally:
        render.SKILL.generate_video = saved
        (render.build_clip_provenance, render.write_clip_provenance,
         render.clip_frame_count, render.probe_streams, render.assert_clips_uniform) = saved_verification


def test_jetsam_ladder_text():
    for rung in ("--tile-frames 2", "--tile-spatial 2", "--frames 193", "--frames 145"):
        check("R12n the jetsam ladder names %r" % rung, rung in render.JETSAM_LADDER,
              "got %r" % render.JETSAM_LADDER)


# ---------------------------------------------------------------------------
# R13: main() preflight exit codes (all exit 2, all before any panel)
# ---------------------------------------------------------------------------

def test_preflight_exit_codes():
    with tempfile.TemporaryDirectory() as td:
        img = os.path.join(td, "p1.png")
        with open(img, "wb") as f:
            f.write(b"png")
        manifest = _write_manifest(td, [_panel(1, img)], story_id="preflight")
        clips = os.path.join(td, "clips")
        out = os.path.join(td, "movie.mp4")

        r = _run_render([os.path.join(td, "nope.json"), out, "--clips-dir", clips])
        check("R13a unreadable manifest exits 2", r.returncode == 2,
              "rc=%r stderr=%r" % (r.returncode, r.stderr))
        check("R13a2 the manifest error names the unreadable path",
              "nope.json" in r.stderr, "stderr=%r" % r.stderr)

        r = _run_render([manifest, os.path.join(td, "movie.mov"), "--clips-dir", clips])
        check("R13b non-.mp4 output exits 2", r.returncode == 2, "rc=%r" % r.returncode)
        check("R13b2 the .mp4 check is the check that fired",
              "must end in .mp4" in r.stderr, "stderr=%r" % r.stderr)

        r = _run_render([manifest, os.path.join(td, "missing_dir", "m.mp4"),
                         "--clips-dir", clips])
        check("R13c missing output directory exits 2", r.returncode == 2, "rc=%r" % r.returncode)
        check("R13c2 the output-directory check is the check that fired",
              "output directory not writable" in r.stderr, "stderr=%r" % r.stderr)

        with open(out, "wb") as f:
            f.write(b"x")
        r = _run_render([manifest, out, "--clips-dir", clips])
        check("R13d existing OUTPUT_MP4 without --force exits 2", r.returncode == 2,
              "rc=%r stderr=%r" % (r.returncode, r.stderr))
        check("R13e that error names --force", "--force" in r.stderr, "stderr=%r" % r.stderr)
        os.remove(out)

        r = _run_render([manifest, out, "--clips-dir", clips, "--frames", "240"])
        check("R13f off-lattice --frames exits 2", r.returncode == 2, "rc=%r" % r.returncode)
        check("R13f2 the geometry check is the check that fired",
              "(num_frames - 1) % 8 == 0" in r.stderr, "stderr=%r" % r.stderr)

        env_r = subprocess.run(
            [sys.executable, _RENDER_PATH, manifest, out, "--clips-dir", clips,
             "--skip-input-screen"],
            capture_output=True, text=True, cwd=WS,
            env=dict(os.environ, LTX2_MLX_BIN=os.path.join(td, "no-such-bin")))
        check("R13g missing LTX2_MLX_BIN exits 2", env_r.returncode == 2,
              "rc=%r stderr=%r" % (env_r.returncode, env_r.stderr))
        check("R13h that error names the resolved path", "no-such-bin" in env_r.stderr,
              "stderr=%r" % env_r.stderr)


def test_preflight_clips_dir_not_writable():
    """The --clips-dir writability check (the one preflight that lives BELOW
    the ffmpeg/binary checks). LTX2_MLX_BIN is pointed at a real executable so
    this case does not depend on ltx-2-mlx being installed on the host."""
    with tempfile.TemporaryDirectory() as td:
        img = os.path.join(td, "p1.png")
        with open(img, "wb") as f:
            f.write(b"png")
        manifest = _write_manifest(td, [_panel(1, img)], story_id="rodir")
        out = os.path.join(td, "movie.mp4")
        clips = os.path.join(td, "ro_clips")
        os.makedirs(clips)
        os.chmod(clips, 0o500)
        try:
            r = subprocess.run(
                [sys.executable, _RENDER_PATH, manifest, out, "--clips-dir", clips,
                 "--skip-input-screen"],
                capture_output=True, text=True, cwd=WS,
                env=dict(os.environ, LTX2_MLX_BIN="/bin/echo"))
            check("R13m an unwritable --clips-dir exits 2", r.returncode == 2,
                  "rc=%r stderr=%r" % (r.returncode, r.stderr))
            check("R13n the --clips-dir writability check is the check that fired",
                  "--clips-dir is not writable" in r.stderr, "stderr=%r" % r.stderr)
        finally:
            os.chmod(clips, 0o700)


# ---------------------------------------------------------------------------
# R13i-R13l: the input content screen call site inside main() is LIVE
# ---------------------------------------------------------------------------

def test_main_content_screen_is_live():
    """Behavioral, not a source grep: main() is driven in-process with the
    screen stubbed to block. If the call site were commented out, guarded by a
    dead branch, or had its rc discarded, main() would fall through to the
    panel loop and this test would fail."""
    saved = (render.story_dir_for, render.render_panel,
             render.finish_run, render.run_input_content_screen)
    try:
        with tempfile.TemporaryDirectory() as td:
            img = os.path.join(td, "p1.png")
            with open(img, "wb") as f:
                f.write(b"png")
            # panels 1 and 2 SHARE one image, panel 3 is T2V -- proves the dedup
            manifest = _write_manifest(td, [_panel(1, img), _panel(2, img), _panel(3, None)],
                                       story_id="screenlive")
            clips = os.path.join(td, "clips")
            os.makedirs(os.path.join(td, "story", "screenlive"))
            render.story_dir_for = lambda sid: os.path.join(td, "story", sid)
            rendered = []

            def _never(unit, args):
                rendered.append(unit["index"])
                return {"unit": unit["label"], "status": "error", "attempts": 1,
                        "seconds": 0.0, "clip": None, "rc": 1, "error": "should not run"}

            render.render_panel = _never
            render.finish_run = lambda *a, **k: 99
            seen = []
            render.run_input_content_screen = lambda paths: (seen.append(list(paths)) or 3)

            rc = render.main([manifest, os.path.join(td, "m.mp4"), "--clips-dir", clips])
            check("R13i a screen block makes main() exit 1, not 2", rc == 1, "rc=%r" % rc)
            check("R13j the screen was actually called exactly once",
                  len(seen) == 1, "calls=%r" % seen)
            check("R13k the screen got deduped, non-null image paths",
                  seen == [[img]], "got %r" % seen)
            check("R13l no panel was rendered after a block",
                  rendered == [], "rendered=%r" % rendered)
            check("R13l2 the screen runs BEFORE the run root is created",
                  not os.path.isdir(os.path.join(td, "story", "screenlive", "runs")),
                  "a run root was created despite a content-screen block")
    finally:
        (render.story_dir_for, render.render_panel,
         render.finish_run, render.run_input_content_screen) = saved


# ---------------------------------------------------------------------------
# R13o-R13z: the panel loop -- stop policy, circuit breaker, resume gate,
# not_attempted backfill, run_root collision
# ---------------------------------------------------------------------------

_FINISH_KEYS = ("args", "raw_argv", "manifest", "units", "unit_results",
                "clips_by_index", "completed", "stopped_reason", "run_root",
                "story_id")


def _drive_main(td, story_id, n_panels, extra_argv, panel_status="error",
                reusable=None, run_id=None):
    """Run main()'s panel loop in-process and return finish_run's arguments as
    a dict, plus the list of panel indices render_panel was actually called
    with. render_panel, finish_run and story_dir_for are stubbed; the loop
    itself is the real one."""
    img = os.path.join(td, "%s.png" % story_id)
    with open(img, "wb") as f:
        f.write(b"png")
    manifest = _write_manifest(td, [_panel(i, img) for i in range(1, n_panels + 1)],
                               story_id=story_id)
    clips = os.path.join(td, "clips_%s" % story_id)
    out = os.path.join(td, "%s.mp4" % story_id)
    os.makedirs(os.path.join(td, "story", story_id), exist_ok=True)

    captured = {}
    rendered = []

    def fake_render_panel(unit, args):
        rendered.append(unit["index"])
        if panel_status == "ok":
            return {"unit": unit["label"], "status": "ok", "attempts": 1,
                    "seconds": 1.0, "clip": os.path.abspath(unit["clip_path"]),
                    "resumed": False}
        return {"unit": unit["label"], "status": panel_status, "attempts": 1,
                "seconds": 0.1, "clip": None, "rc": 1, "error": "stub failure"}

    def fake_finish_run(*a, **k):
        captured.update(dict(zip(_FINISH_KEYS, a)))
        return 77

    saved = (render.story_dir_for, render.render_panel, render.finish_run,
             render.run_input_content_screen, render.clip_is_reusable,
             render.new_run_id, render.SKILL._resolve_bin)
    try:
        render.story_dir_for = lambda sid: os.path.join(td, "story", sid)
        render.render_panel = fake_render_panel
        render.finish_run = fake_finish_run
        render.run_input_content_screen = lambda paths: 0
        # so these tests do not depend on ltx-2-mlx being installed
        render.SKILL._resolve_bin = lambda: sys.executable
        if reusable is not None:
            render.clip_is_reusable = lambda path, frames, provenance=None: reusable
        if run_id is not None:
            render.new_run_id = lambda: run_id
        argv = [manifest, out, "--clips-dir", clips, "--skip-input-screen"] + extra_argv
        rc = render.main(argv)
    finally:
        (render.story_dir_for, render.render_panel, render.finish_run,
         render.run_input_content_screen, render.clip_is_reusable,
         render.new_run_id, render.SKILL._resolve_bin) = saved
    return rc, captured, rendered, argv


def _reached_loop(tag, rc, captured):
    """Guard so a preflight regression reports one clean FAIL instead of
    crashing the rest of the suite on an empty capture dict."""
    ok = bool(captured)
    check("%s main() reached the panel loop and called finish_run" % tag, ok,
          "main() returned %r before finish_run" % rc)
    return ok


def test_panel_loop_circuit_breaker():
    with tempfile.TemporaryDirectory() as td:
        rc, cap, rendered, argv = _drive_main(
            td, "cb", 5, ["--on-panel-failure", "skip", "--max-consecutive-failures", "2"])
        if not _reached_loop("R13o0", rc, cap):
            return
        check("R13o main() returns finish_run's value", rc == 77, "rc=%r" % rc)
        check("R13p the circuit breaker stops the loop at the 2nd consecutive failure",
              rendered == [1, 2], "rendered=%r" % rendered)
        check("R13q stopped_reason is consecutive_failures",
              cap.get("stopped_reason") == "consecutive_failures",
              "got %r" % cap.get("stopped_reason"))
        check("R13r completed is 0 when every attempted panel failed",
              cap.get("completed") == 0, "got %r" % cap.get("completed"))
        check("R13s unit_results is keyed by panel index, one entry per unit",
              isinstance(cap.get("unit_results"), dict)
              and sorted(cap["unit_results"]) == [1, 2, 3, 4, 5],
              "got %r" % (cap.get("unit_results"),))
        _st = {i: cap["unit_results"].get(i, {}).get("status") for i in (1, 2, 3, 4, 5)}
        check("R13t unattempted panels are backfilled as not_attempted",
              [_st[i] for i in (1, 2, 3, 4, 5)]
              == ["error", "error", "not_attempted", "not_attempted", "not_attempted"],
              "got %r" % _st)
        check("R13u raw_argv is the argv main() was called with",
              cap.get("raw_argv") == argv, "got %r" % (cap.get("raw_argv"),))


def test_panel_loop_stop_policy_wins_over_circuit_breaker():
    """Both policies armed at once. 'stop' is checked first, so a single
    failure must report panel_failure, never consecutive_failures."""
    with tempfile.TemporaryDirectory() as td:
        rc, cap, rendered, _ = _drive_main(
            td, "stopwins", 4, ["--on-panel-failure", "stop", "--max-consecutive-failures", "1"])
        if not _reached_loop("R13v0", rc, cap):
            return
        check("R13v the stop policy aborts on the first failure",
              rendered == [1], "rendered=%r" % rendered)
        check("R13w the stop policy wins over the circuit breaker",
              cap.get("stopped_reason") == "panel_failure",
              "got %r; the circuit breaker must not claim this stop"
              % cap.get("stopped_reason"))


def test_panel_loop_max_consecutive_failures_zero_disables():
    with tempfile.TemporaryDirectory() as td:
        rc, cap, rendered, _ = _drive_main(
            td, "cbzero", 4, ["--on-panel-failure", "skip", "--max-consecutive-failures", "0"])
        if not _reached_loop("R13x0", rc, cap):
            return
        check("R13x --max-consecutive-failures 0 disables the circuit breaker",
              rendered == [1, 2, 3, 4], "rendered=%r" % rendered)
        check("R13y a disabled circuit breaker leaves stopped_reason None",
              cap.get("stopped_reason") is None, "got %r" % cap.get("stopped_reason"))


def test_panel_loop_reuse_requires_resume_flag():
    """clip_is_reusable is forced True. WITHOUT --resume every panel must
    still be rendered: the reuse gate is 'resume AND reusable', never OR."""
    with tempfile.TemporaryDirectory() as td:
        rc, cap, rendered, _ = _drive_main(
            td, "noresume", 3, ["--on-panel-failure", "skip"],
            panel_status="ok", reusable=True)
        if not _reached_loop("R13z0", rc, cap):
            return
        check("R13z a reusable clip is NOT reused without --resume",
              rendered == [1, 2, 3], "rendered=%r" % rendered)
        check("R13z2 no unit is marked resumed without --resume",
              all(not cap["unit_results"].get(i, {}).get("resumed") for i in (1, 2, 3)),
              "got %r" % cap["unit_results"])

        rc, cap, rendered, _ = _drive_main(
            td, "yesresume", 3, ["--on-panel-failure", "skip", "--resume"],
            panel_status="ok", reusable=True)
        if not _reached_loop("R13z30", rc, cap):
            return
        check("R13z3 with --resume a reusable clip skips render_panel",
              rendered == [], "rendered=%r" % rendered)
        check("R13z4 resumed units are flagged resumed with seconds 0.0",
              all(cap["unit_results"].get(i, {}).get("resumed")
                  and cap["unit_results"].get(i, {}).get("seconds") == 0.0
                  for i in (1, 2, 3)),
              "got %r" % cap["unit_results"])
        check("R13z5 resumed units still count as completed",
              cap.get("completed") == 3, "got %r" % cap.get("completed"))
        check("R13z6 resumed units populate clips_by_index by index",
              sorted(cap.get("clips_by_index", {})) == [1, 2, 3],
              "got %r" % (cap.get("clips_by_index"),))


def test_run_root_collision_is_loud():
    """os.makedirs(run_root) deliberately has no exist_ok=True: a run-id
    collision must never be silently merged into a stale run."""
    with tempfile.TemporaryDirectory() as td:
        rc, cap, rendered, _ = _drive_main(
            td, "collide", 1, ["--on-panel-failure", "skip"], run_id="FIXED-RUN-ID")
        if not _reached_loop("R13z70", rc, cap):
            return
        check("R13z7 the first run creates its run root", rc == 77, "rc=%r" % rc)
        raised = None
        try:
            _drive_main(td, "collide", 1, ["--on-panel-failure", "skip"],
                        run_id="FIXED-RUN-ID")
        except FileExistsError as e:
            raised = e
        check("R13z8 a run-id collision raises instead of merging into the stale run",
              isinstance(raised, FileExistsError), "raised=%r" % (raised,))


# ---------------------------------------------------------------------------
# R14: story_summary.json shape
# ---------------------------------------------------------------------------

def _newest_summary(story_id):
    matches = glob.glob(os.path.join(render.story_dir_for(story_id), "runs", "*",
                                     "story_summary.json"))
    if not matches:
        return None
    with open(max(matches, key=os.path.getmtime)) as f:
        return json.load(f)


def test_summary_shape():
    s = {"schema_version": 3, "backend": "ltx-2-mlx", "requested_units": 3,
         "completed_units": 3, "frames_per_panel": 241,
         "intended_total_frames": 723, "actual_total_frames": 723, "fps": 24,
         "units": [{"unit": "panel-1", "attempts": 1}]}
    check("R14a intended == requested * frames_per_panel",
          s["intended_total_frames"] == s["requested_units"] * s["frames_per_panel"])
    for key in ("completed_units", "requested_units", "intended_total_frames",
                "actual_total_frames", "fps", "units"):
        check("R14b _report_summary reads %r" % key, key in s)
    check("R14c summary_keys() is the single source of truth for the schema",
          set(render.SUMMARY_KEYS) >= {
              "schema_version", "backend", "story_id", "manifest_path",
              "manifest_schema_version", "model", "width", "height",
              "frames_per_panel", "fps", "low_ram", "tile_frames", "tile_spatial",
              "requested_units", "completed_units", "intended_total_frames",
              "actual_total_frames", "units", "clips", "skipped_panels",
              "concat_mode", "output_path", "on_panel_failure", "stopped_reason"},
          "got %r" % sorted(render.SUMMARY_KEYS))


def test_finish_run_emits_exactly_summary_keys():
    saved = (render.probe_streams, render.assert_clips_uniform,
             render.build_concat_command)
    render.probe_streams = lambda p: {"streams": []}
    render.assert_clips_uniform = lambda *a: None
    render.build_concat_command = lambda lp, out: [
        sys.executable, "-c", "import sys; open(sys.argv[1],'wb').write(b'M')", out]
    try:
        with tempfile.TemporaryDirectory() as td:
            run_root = os.path.join(td, "run"); os.makedirs(run_root)
            args = render.build_parser().parse_args(
                [os.path.join(td, "m.json"), os.path.join(td, "out.mp4")])
            units = [{"index": 1, "label": "panel-1", "prompt": "p",
                      "image_path": None, "clip_path": os.path.join(td, "c1.mp4"),
                      "log_path": None, "seed": 1}]
            ur = {1: {"unit": "panel-1", "status": "ok", "attempts": 1,
                      "seconds": 1.0, "clip": "/a/1.mp4", "resumed": False}}
            rc = render.finish_run(args, ["m", "o"], {"schema_version": 2}, units,
                                   ur, {1: "/a/1.mp4"}, 1, None, run_root, "sid")
            with open(os.path.join(run_root, "story_summary.json")) as f:
                s = json.load(f)
            check("R14d finish_run emits exactly SUMMARY_KEYS",
                  set(s) == set(render.SUMMARY_KEYS),
                  "extra=%r missing=%r" % (sorted(set(s) - set(render.SUMMARY_KEYS)),
                                           sorted(set(render.SUMMARY_KEYS) - set(s))))
            check("R14e a complete run exits 0", rc == 0, "rc=%r" % rc)
            check("R14f schema_version is 3", s["schema_version"] == 3,
                  "got %r" % s["schema_version"])
    finally:
        (render.probe_streams, render.assert_clips_uniform,
         render.build_concat_command) = saved


def test_finish_run_writes_summary_when_concat_fails():
    saved = (render.probe_streams, render.assert_clips_uniform,
             render.build_concat_command)
    render.probe_streams = lambda p: {"streams": []}
    render.assert_clips_uniform = lambda *a: None
    try:
        for tag, cmd_stub, keys in (
                ("R14g/h/i ffmpeg non-zero rc",
                 lambda lp, out: [sys.executable, "-c", "raise SystemExit(7)"],
                 ("R14g", "R14h", "R14i")),
                ("R14j/k/l ffmpeg missing from PATH mid-run",
                 lambda lp, out: ["/nonexistent/ffmpeg", "-i", lp, out],
                 ("R14j", "R14k", "R14l"))):
            render.build_concat_command = cmd_stub
            with tempfile.TemporaryDirectory() as td:
                run_root = os.path.join(td, "run")
                os.makedirs(run_root)
                args = render.build_parser().parse_args(
                    [os.path.join(td, "m.json"), os.path.join(td, "out.mp4")])
                units = [{"index": 1, "label": "panel-1", "prompt": "p",
                          "image_path": None, "clip_path": os.path.join(td, "c1.mp4"),
                          "log_path": None, "seed": 1}]
                ur = {1: {"unit": "panel-1", "status": "ok", "attempts": 1,
                          "seconds": 1.0, "clip": "/a/1.mp4", "resumed": False}}
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    rc = render.finish_run(args, ["m", "o"], {}, units, ur,
                                           {1: "/a/1.mp4"}, 1, None, run_root, "sid")
                summary_path = os.path.join(run_root, "story_summary.json")
                check("%s exits 1" % keys[0], rc == 1, "%s rc=%r" % (tag, rc))
                check("%s still writes story_summary.json" % keys[1],
                      os.path.exists(summary_path), tag)
                if not os.path.exists(summary_path):
                    continue
                with open(summary_path) as f:
                    s = json.load(f)
                check("%s records output_path null" % keys[2],
                      s["output_path"] is None, "%s got %r" % (tag, s["output_path"]))
    finally:
        (render.probe_streams, render.assert_clips_uniform,
         render.build_concat_command) = saved


# ---------------------------------------------------------------------------
# R15: end-to-end main() against a stubbed skill and a stubbed concat
# ---------------------------------------------------------------------------

class _Harness(object):
    """Runs main() in-process with SKILL.generate_video, probe_streams,
    assert_clips_uniform, build_concat_command and clip_frame_count all
    stubbed, so no model and no ffmpeg are needed. Records which panel seeds
    were actually rendered."""

    def __init__(self, td, story_id, n_panels, fail_indices=(), fail_status="error"):
        self.td = td
        self.story_id = story_id
        self.rendered_seeds = []
        self.received_kwargs = []
        self.fail_indices = set(fail_indices)
        self.fail_status = fail_status
        self.saved = {}
        img = os.path.join(td, "p.png")
        with open(img, "wb") as f:
            f.write(b"png")
        self.manifest = _write_manifest(
            td, [_panel(i, img) for i in range(1, n_panels + 1)], story_id=story_id)
        self.model = os.path.join(td, "model-fixture")
        os.makedirs(self.model, exist_ok=True)
        with open(os.path.join(self.model, "split_model.json"), "w") as handle:
            json.dump({"recipe": "ltx-2.5"}, handle)
        self.clips = os.path.join(td, "clips")
        os.makedirs(self.clips, exist_ok=True)
        self.out = os.path.join(td, "movie.mp4")

    def __enter__(self):
        self.saved = {
            "gen": render.SKILL.generate_video,
            "probe": render.probe_streams,
            "uniform": render.assert_clips_uniform,
            "concat": render.build_concat_command,
            "count": render.clip_frame_count,
            "bin": render.SKILL.LTX2_MLX_BIN,
        }
        fake_bin = os.path.join(self.td, "fake-ltx")
        with open(fake_bin, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(fake_bin, 0o755)
        render.SKILL.LTX2_MLX_BIN = fake_bin

        harness = self

        def _gen(prompt, output_path, image_path=None, **kw):
            harness.rendered_seeds.append(kw["seed"])
            harness.received_kwargs.append(kw)
            idx = int(os.path.basename(output_path)[len("panel_"):-len(".mp4")])
            if idx in harness.fail_indices:
                if harness.fail_status == "invalid":
                    raise ValueError("stub invalid panel %d" % idx)
                raise render.SKILL.Ltx2MlxError(
                    "stub failure", returncode=1, cmd=[], stderr_tail="stub tail",
                    output_path=output_path)
            with open(output_path, "wb") as f:
                f.write(b"\x00" * 128)
            return os.path.abspath(output_path)

        render.SKILL.generate_video = _gen
        render.probe_streams = lambda p: {"streams": []}
        render.assert_clips_uniform = lambda pairs, w, h, fr: None
        render.build_concat_command = lambda lp, out: [
            sys.executable, "-c",
            "import sys; open(sys.argv[1],'wb').write(b'MOVIE')", out]
        render.clip_frame_count = lambda p: 241
        return self

    def __exit__(self, *exc):
        render.SKILL.generate_video = self.saved["gen"]
        render.probe_streams = self.saved["probe"]
        render.assert_clips_uniform = self.saved["uniform"]
        render.build_concat_command = self.saved["concat"]
        render.clip_frame_count = self.saved["count"]
        render.SKILL.LTX2_MLX_BIN = self.saved["bin"]
        shutil.rmtree(render.story_dir_for(self.story_id), ignore_errors=True)
        return False

    def run(self, *extra):
        return render.main([self.manifest, self.out, "--clips-dir", self.clips,
                            "--skip-input-screen", "--model", self.model] + list(extra))


def test_resume_force_orthogonality():
    with tempfile.TemporaryDirectory() as td:
        with _Harness(td, "orth1", 2) as h:
            rc = h.run()
            check("R15a first run renders every panel and exits 0", rc == 0,
                  "rc=%r" % rc)
            check("R15b both panels rendered", h.rendered_seeds == [1, 2],
                  "got %r" % h.rendered_seeds)

    with tempfile.TemporaryDirectory() as td:
        with _Harness(td, "orth2", 2) as h:
            h.run()
            h.rendered_seeds[:] = []
            rc = h.run("--resume", "--force")
            check("R15c --resume --force renders zero panels", h.rendered_seeds == [],
                  "got %r" % h.rendered_seeds)
            check("R15d --resume --force rewrites the movie and exits 0", rc == 0,
                  "rc=%r" % rc)

    with tempfile.TemporaryDirectory() as td:
        with _Harness(td, "orth3", 2) as h:
            h.run()
            h.rendered_seeds[:] = []
            rc = h.run("--resume")
            check("R15e --resume alone with an existing OUTPUT_MP4 exits 2", rc == 2,
                  "rc=%r" % rc)
            check("R15f nothing was rendered before that exit", h.rendered_seeds == [],
                  "got %r" % h.rendered_seeds)

    with tempfile.TemporaryDirectory() as td:
        with _Harness(td, "orth4", 2) as h:
            h.run()
            h.rendered_seeds[:] = []
            rc = h.run("--force")
            check("R15g --force alone regenerates every panel", h.rendered_seeds == [1, 2],
                  "got %r" % h.rendered_seeds)
            check("R15h --force alone exits 0", rc == 0, "rc=%r" % rc)


def test_failure_state_machine():
    with tempfile.TemporaryDirectory() as td:
        with _Harness(td, "fsm1", 4, fail_indices=[2]) as h:
            rc = h.run("--on-panel-failure", "stop")
            check("R16a stop aborts on the first failure", h.rendered_seeds == [1, 2],
                  "got %r" % h.rendered_seeds)
            check("R16b stop exits 1", rc == 1, "rc=%r" % rc)
            s = _newest_summary("fsm1")
            check("R16c stopped_reason is panel_failure",
                  s and s["stopped_reason"] == "panel_failure",
                  "got %r" % (s or {}).get("stopped_reason"))
            check("R16d panels after the abort are not_attempted",
                  s and s["units"][3]["status"] == "not_attempted",
                  "got %r" % (s or {}).get("units"))

    with tempfile.TemporaryDirectory() as td:
        with _Harness(td, "fsm2", 4, fail_indices=[2]) as h:
            rc = h.run("--on-panel-failure", "skip")
            check("R16e skip continues past the failure",
                  h.rendered_seeds == [1, 2, 3, 4], "got %r" % h.rendered_seeds)
            check("R16f skip exits 1 when a panel was skipped", rc == 1, "rc=%r" % rc)
            s = _newest_summary("fsm2")
            check("R16g survivors are concatenated in index order",
                  s and [os.path.basename(c) for c in s["clips"]]
                  == ["panel_01.mp4", "panel_03.mp4", "panel_04.mp4"],
                  "got %r" % (s or {}).get("clips"))
            check("R16h skipped_panels records the failure", s and s["skipped_panels"] == [2],
                  "got %r" % (s or {}).get("skipped_panels"))
            check("R16i completed_units counts survivors only",
                  s and s["completed_units"] == 3, "got %r" % (s or {}).get("completed_units"))
            check("R16j actual_total_frames = completed * frames_per_panel",
                  s and s["actual_total_frames"] == 3 * 241,
                  "got %r" % (s or {}).get("actual_total_frames"))
            check("R16k intended_total_frames = requested * frames_per_panel",
                  s and s["intended_total_frames"] == 4 * 241,
                  "got %r" % (s or {}).get("intended_total_frames"))
            check("R16l the movie was still written", s and s["output_path"] is not None)

    with tempfile.TemporaryDirectory() as td:
        with _Harness(td, "fsm3", 6, fail_indices=[2, 3, 4]) as h:
            rc = h.run("--on-panel-failure", "skip", "--max-consecutive-failures", "3")
            check("R16m the circuit breaker stops on the third consecutive failure",
                  h.rendered_seeds == [1, 2, 3, 4], "got %r" % h.rendered_seeds)
            s = _newest_summary("fsm3")
            check("R16n stopped_reason is consecutive_failures",
                  s and s["stopped_reason"] == "consecutive_failures",
                  "got %r" % (s or {}).get("stopped_reason"))
            check("R16o exits 1", rc == 1, "rc=%r" % rc)

    with tempfile.TemporaryDirectory() as td:
        with _Harness(td, "fsm4", 2, fail_indices=[2]) as h:
            h.fail_indices = {2}

            original = render.SKILL.generate_video
            state = {"seen": 0}

            def _flaky(prompt, output_path, image_path=None, **kw):
                idx = int(os.path.basename(output_path)[len("panel_"):-len(".mp4")])
                if idx == 2 and state["seen"] == 0:
                    state["seen"] = 1
                    h.rendered_seeds.append(kw["seed"])
                    raise render.SKILL.Ltx2MlxError(
                        "first attempt fails", returncode=1, cmd=[],
                        stderr_tail="t", output_path=output_path)
                h.fail_indices = set()
                return original(prompt, output_path, image_path=image_path, **kw)

            render.SKILL.generate_video = _flaky
            rc = h.run("--on-panel-failure", "skip", "--retry-failed", "1",
                       "--retry-idle", "0")
            s = _newest_summary("fsm4")
            check("R16p the retry pass records attempts: 2",
                  s and s["units"][1]["attempts"] == 2,
                  "got %r" % (s or {}).get("units"))
            check("R16q the retried panel ends ok", s and s["units"][1]["status"] == "ok",
                  "got %r" % (s or {}).get("units"))
            check("R16r a fully recovered run exits 0", rc == 0, "rc=%r" % rc)
            check("R16r2 the retried clip lands in the concat list",
                  s and [os.path.basename(c) for c in s["clips"]]
                  == ["panel_01.mp4", "panel_02.mp4"],
                  "got %r" % (s or {}).get("clips"))
            check("R16r3 a fully recovered run skips nothing",
                  s and s["skipped_panels"] == [],
                  "got %r" % (s or {}).get("skipped_panels"))

    with tempfile.TemporaryDirectory() as td:
        with _Harness(td, "fsm5", 2, fail_indices=[1, 2]) as h:
            rc = h.run("--on-panel-failure", "skip", "--max-consecutive-failures", "0")
            s = _newest_summary("fsm5")
            check("R16s all-panels-failed writes output_path null",
                  s and s["output_path"] is None, "got %r" % (s or {}).get("output_path"))
            check("R16t all-panels-failed exits 1", rc == 1, "rc=%r" % rc)
            check("R16u the summary still exists", s is not None)

    with tempfile.TemporaryDirectory() as td:
        with _Harness(td, "fsm6", 2, fail_indices=[1], fail_status="invalid") as h:
            h.run("--on-panel-failure", "skip")
            s = _newest_summary("fsm6")
            check("R16v a skill ValueError maps to status invalid",
                  s and s["units"][0]["status"] == "invalid",
                  "got %r" % (s or {}).get("units"))

    with tempfile.TemporaryDirectory() as td:
        with _Harness(td, "fsm7", 4, fail_indices=[2]) as h:
            rc = h.run("--on-panel-failure", "stop", "--retry-failed", "1",
                       "--retry-idle", "0")
            s = _newest_summary("fsm7")
            check("R16w stop suppresses the retry pass (attempts stays 1)",
                  s and s["units"][1]["attempts"] == 1,
                  "got %r" % (s or {}).get("units"))
            check("R16x the failed panel was rendered exactly once",
                  h.rendered_seeds == [1, 2], "got %r" % h.rendered_seeds)
            check("R16y stopped_reason is still panel_failure",
                  s and s["stopped_reason"] == "panel_failure",
                  "got %r" % (s or {}).get("stopped_reason"))
            check("R16z stop + retry still exits 1", rc == 1, "rc=%r" % rc)


def test_gemma_lora_reach_generate_video():
    with tempfile.TemporaryDirectory() as td:
        with _Harness(td, "gemma-lora-wiring", 1) as h:
            rc = h.run("--gemma", "Other/Gemma", "--lora", "/tmp/my.safetensors")
            check("R33a run exits 0", rc == 0, "got %r" % rc)
            check("R33b exactly one panel rendered", len(h.received_kwargs) == 1,
                  "got %r" % h.received_kwargs)
            if h.received_kwargs:
                kw = h.received_kwargs[0]
                check("R33c gemma reached SKILL.generate_video",
                      kw.get("gemma") == "Other/Gemma", "got %r" % kw)
                check("R33d lora_path reached SKILL.generate_video",
                      kw.get("lora_path") == "/tmp/my.safetensors", "got %r" % kw)


def test_clip_provenance_contract():
    from unittest import mock
    import hashlib
    with tempfile.TemporaryDirectory() as td:
        model = os.path.join(td,'model')
        os.mkdir(model)
        for name,data in [('z.safetensors',b'weights'),('config.json',b'{}'),('ignored.txt',b'ignored')]:
            with open(os.path.join(model,name),'wb') as handle: handle.write(data)
        image = os.path.join(td,'image.png')
        clip = os.path.join(td,'clip.mp4')
        with open(image,'wb') as handle: handle.write(b'image bytes')
        with open(clip,'wb') as handle: handle.write(b'video bytes')
        unit = dict(prompt='literal prompt\n',image_path=image,seed=4,clip_path=clip,
                    conditioning='still',chain_source=None)
        args = _stub_args(model=model, gemma='Other/Gemma', lora_path='/tmp/my.safetensors')
        expected = render.build_clip_provenance(unit,args)
        check('R18z provenance records gemma and lora_path',
              expected['gemma'] == 'Other/Gemma' and expected['lora_path'] == '/tmp/my.safetensors',
              "got %r" % {k: expected.get(k) for k in ('gemma', 'lora_path')})
        check('R18 schema_version 2 and the ltx-2-mlx backend constant',
              expected['schema_version']==2 and expected['backend']=='ltx-2-mlx')
        check('R18 no VAE decode budget key','vae_decode_budget_gb' not in expected)
        check('R18 still provenance carries its conditioning and no chain keys',
              expected['conditioning']=='still' and expected['chain_source_sha256'] is None
              and expected['chain_frame_index'] is None)
        identity = expected['model_identity']
        check('R18 exact identity fields',set(identity)=={'resolved_path','snapshot_revision','files'})
        check('R18 canonical bundle and local revision',identity['resolved_path']==os.path.realpath(model)
              and identity['snapshot_revision'] is None)
        check('R18 sorted relevant metadata excludes unrelated files',
              [item['path'] for item in identity['files']]==['config.json','z.safetensors'])
        check('R18 file metadata records sizes and nanosecond mtimes',all(set(item)=={'path','size','mtime_ns'}
              and isinstance(item['mtime_ns'],int) for item in identity['files']))
        check('R18 exact prompt and image hashes',expected['prompt_sha256']==hashlib.sha256(b'literal prompt\n').hexdigest()
              and expected['image_sha256']==hashlib.sha256(b'image bytes').hexdigest())
        sidecar = clip+'.provenance.json'
        payload = dict(expected,output_sha256=hashlib.sha256(b'video bytes').hexdigest())
        def write(value):
            with open(sidecar,'w') as handle: json.dump(value,handle)
        with mock.patch.object(render,'clip_frame_count',return_value=241):
            check('R18 missing sidecar is never reusable',not render.clip_is_reusable(clip,241,expected))
            write(payload)
            check('R18 exact provenance reuses clip',render.clip_is_reusable(clip,241,expected))
            write(dict(reversed(list(payload.items()))))
            check('R18 reordered valid keys still reuse',render.clip_is_reusable(clip,241,expected))
            for name,value,comparison in (('schema_version',True,expected),('fps',24.0,expected),
                                           ('seed',True,dict(expected,seed=1)),('frames',float('nan'),expected)):
                malformed = dict(payload,**{name:value})
                write(malformed)
                check('R18 malformed numeric type %s=%r regenerates' % (name,value),
                      not render.clip_is_reusable(clip,241,comparison))
            for key in payload:
                changed = dict(payload)
                changed[key] = None if payload[key] is not None else 'changed'
                write(changed)
                check('R18 mismatched %s regenerates' % key,not render.clip_is_reusable(clip,241,expected))
            for value in (None,[],{},'bad',42):
                write(value)
                check('R18 malformed sidecar %r regenerates' % value,not render.clip_is_reusable(clip,241,expected))
            with open(sidecar,'w') as handle: handle.write('{broken')
            check('R18 corrupt JSON regenerates',not render.clip_is_reusable(clip,241,expected))
            write(payload)
            with open(clip,'wb') as handle: handle.write(b'changed video')
            check('R18 mutated clip checksum regenerates',not render.clip_is_reusable(clip,241,expected))
            with open(clip,'wb') as handle: handle.write(b'video bytes')
            with open(os.path.join(model,'config.json'),'ab') as handle: handle.write(b' ')
            current = render.build_clip_provenance(unit,args)
            check('R18 changed model metadata regenerates',not render.clip_is_reusable(clip,241,current))
            unknown = dict(expected,model_identity=None)
            write(dict(unknown,output_sha256=payload['output_sha256']))
            check('R18 unknown model identity cannot resume',not render.clip_is_reusable(clip,241,unknown))
        with mock.patch.object(render,'clip_frame_count',return_value=240):
            write(payload)
            check('R18 original frame count guard retained',not render.clip_is_reusable(clip,241,expected))
        no_image = render.build_clip_provenance(dict(unit,image_path=None,conditioning='t2v'),args)
        check('R18 T2V provenance hashes no image and no chain source',
              no_image['image_sha256'] is None and no_image['conditioning']=='t2v'
              and no_image['chain_source_sha256'] is None and no_image['chain_frame_index'] is None)
        chain_unit = dict(unit,image_path=os.path.join(td,'panel_02.chainseed.png'),
                          conditioning='chain',chain_source=clip)
        chained = render.build_clip_provenance(chain_unit,args)
        check('R18 chain provenance keys the SOURCE CLIP bytes, never the (absent) PNG',
              chained['image_sha256'] is None
              and chained['chain_source_sha256']==hashlib.sha256(b'video bytes').hexdigest())
        check('R18 chain provenance records the source frame index and its conditioning',
              chained['chain_frame_index']==args.frames-1 and chained['conditioning']=='chain')


def test_cached_model_metadata_and_io_failures():
    from unittest import mock
    with tempfile.TemporaryDirectory() as td:
        cache = os.path.join(td,'cache')
        repo = os.path.join(cache,'hub','models--org--bundle')
        snapshot = os.path.join(repo,'snapshots','revision123')
        os.makedirs(snapshot)
        os.makedirs(os.path.join(repo,'refs'))
        with open(os.path.join(repo,'refs','main'),'w') as handle: handle.write('revision123')
        blob = os.path.join(td,'blob')
        with open(blob,'wb') as handle: handle.write(b'weight bytes')
        os.symlink(blob,os.path.join(snapshot,'weights.safetensors'))
        external = os.path.join(td,'external')
        os.mkdir(external)
        with open(os.path.join(external,'ignored.json'),'w') as handle: handle.write('{}')
        os.symlink(external,os.path.join(snapshot,'linked-directory'))
        with mock.patch.object(render.SKILL,'LTX2_MLX_HF_HOME',cache):
            identity = render.model_identity('org/bundle')
            check('R20 cached identity includes canonical snapshot and revision',
                  identity['resolved_path']==os.path.realpath(snapshot) and identity['snapshot_revision']=='revision123')
            check('R20 file symlinks followed, directory symlinks not traversed',
                  [entry['path'] for entry in identity['files']]==['weights.safetensors'] and identity['files'][0]['size']==12)
            real_stat = render.os.stat
            def denied(path,*args,**kwargs):
                if str(path).endswith('weights.safetensors'): raise PermissionError('fixture read denied')
                return real_stat(path,*args,**kwargs)
            with mock.patch.object(render.os,'stat',side_effect=denied):
                check('R20 unreadable metadata refuses resume',render.model_identity('org/bundle') is None)
                try:
                    render.model_identity('org/bundle',strict=True)
                    raised = False
                except OSError:
                    raised = True
                check('R20 resolved metadata I/O is fatal to verification',raised)
            check('R20 uncached direct reference remains unresolved',render.model_identity('missing/ref',strict=True) is None)
            ref_path = os.path.join(repo,'refs','main')
            real_open = open
            def unreadable(path,*args,**kwargs):
                if str(path)==ref_path: raise PermissionError('fixture refs denied')
                return real_open(path,*args,**kwargs)
            with mock.patch('builtins.open',side_effect=unreadable):
                for strict in (False,True):
                    try:
                        result = render.model_identity('org/bundle',strict=strict)
                        raised = False
                    except OSError:
                        raised = True
                    check('R20 unreadable existing refs strict=%s' % strict,raised==strict)
            with open(ref_path,'w') as handle: handle.write('missing-snapshot')
            for strict in (False,True):
                try:
                    result = render.model_identity('org/bundle',strict=strict)
                    raised = False
                except OSError:
                    raised = True
                check('R20 broken existing snapshot strict=%s' % strict,raised==strict)

        flat_repo = os.path.join(cache,'hub','models--flat--bundle')
        os.makedirs(os.path.join(flat_repo,'refs'))
        with open(os.path.join(flat_repo,'refs','main'),'w') as handle: handle.write('flatrevision')
        with open(os.path.join(flat_repo,'weights.safetensors'),'wb') as handle: handle.write(b'flat weight bytes')
        with mock.patch.object(render.SKILL,'LTX2_MLX_HF_HOME',cache):
            flat_identity = render.model_identity('flat/bundle')
            check('R20 hf-download --local-dir flat layout (no snapshots/ tree) resolves via the repo root',
                  flat_identity is not None and flat_identity['resolved_path']==os.path.realpath(flat_repo)
                  and flat_identity['snapshot_revision']=='flatrevision'
                  and [entry['path'] for entry in flat_identity['files']]==['weights.safetensors'])

        with _Harness(td,'provenanceio-mlx',1) as h:
            args = _stub_args(model=h.model)
            unit = render.build_units(render.load_manifest(h.manifest)['panels'],0,h.clips)[0]
            with mock.patch.object(render.os,'replace',side_effect=OSError('fixture publish denied')):
                result = render.render_panel(unit,args)
            check('R20 sidecar I/O maps to a failed unit',result['status']=='error' and result['clip'] is None)
            check('R20 sidecar I/O retains the clip and removes sidecar/temp',
                  os.path.isfile(unit['clip_path']) and not glob.glob(unit['clip_path']+'.provenance.json*'))
            check('R20 a verification failure is not fatal on the ltx-2-mlx backend',
                  not result.get('fatal'))


def test_provenance_rejects_changes_during_generation():
    from unittest import mock
    for changed in ('image','model'):
        with tempfile.TemporaryDirectory() as td:
            with _Harness(td,'toctou-'+changed,1) as h:
                unit = render.build_units(render.load_manifest(h.manifest)['panels'],0,h.clips)[0]
                args = _stub_args(model=h.model)
                original = render.SKILL.generate_video
                def mutate(*pos,**kwargs):
                    result = original(*pos,**kwargs)
                    target = unit['image_path'] if changed=='image' else os.path.join(h.model,'split_model.json')
                    with open(target,'ab') as handle: handle.write(b'changed')
                    return result
                with mock.patch.object(render.SKILL,'generate_video',side_effect=mutate):
                    result = render.render_panel(unit,args)
                check('R22 changed %s during generation fails without sidecar' % changed,
                      result['status']=='error' and not result.get('fatal')
                      and os.path.isfile(unit['clip_path'])
                      and not os.path.exists(unit['clip_path']+'.provenance.json'))
    with tempfile.TemporaryDirectory() as td:
        with _Harness(td,'identityresolved',1) as h:
            unit = render.build_units(render.load_manifest(h.manifest)['panels'],0,h.clips)[0]
            args = _stub_args(model='initially/uncached')
            with mock.patch.object(render,'model_identity',side_effect=[None,{'resolved_path':'new'}]):
                result = render.render_panel(unit,args)
            with open(unit['clip_path']+'.provenance.json') as handle: provenance = json.load(handle)
            check('R22 newly resolved identity is not adopted for generated clip',
                  result['status']=='ok' and provenance['model_identity'] is None)


# ---------------------------------------------------------------------------
# R23/R26/R27: chain-seed extraction and validation
# ---------------------------------------------------------------------------

def _rgb_framemd5(path, vf):
    """md5 of the single rgb24 frame ffmpeg produces for path under filter vf, or None."""
    proc = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-vf", vf,
                           "-fps_mode", "passthrough", "-f", "framemd5", "-"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    rows = [l for l in proc.stdout.splitlines() if l.strip() and not l.startswith("#")]
    if proc.returncode != 0 or len(rows) != 1:
        return None
    return rows[0].split(",")[-1].strip()


def test_extract_last_frame_argv():
    saved = render.subprocess.run
    seen = {}

    class _Ok(object):
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_ok(argv, **kw):
        seen["argv"], seen["kw"] = argv, kw
        with open(argv[-1], "wb") as f:
            f.write(b"PNGDATA")
        return _Ok()

    try:
        with tempfile.TemporaryDirectory() as td:
            out_png = os.path.join(td, "panel_02.chainseed.png")
            tmp_png = os.path.join(td, "panel_02.chainseed.tmp.png")
            render.subprocess.run = _fake_ok
            v = render.extract_last_frame("/c/panel_01.mp4", out_png, 145)
            check("R23a exact argv: select by exact index frames-1, passthrough, one frame, to .tmp.png",
                  seen.get("argv") == ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i",
                                       "/c/panel_01.mp4", "-vf", "select=eq(n\\,144)",
                                       "-fps_mode", "passthrough", "-frames:v", "1", tmp_png],
                  "got %r" % seen.get("argv"))
            check("R23b timeout=120", seen.get("kw", {}).get("timeout") == 120,
                  "got %r" % seen.get("kw"))
            check("R23c success returns []", v == [], "got %r" % v)
            check("R23d the tmp file is renamed onto the final path",
                  os.path.isfile(out_png) and not os.path.exists(tmp_png))

            class _Fail(object):
                returncode = 1
                stdout = ""
                stderr = "E1\nE2\nE3\nE4\nE5\nE6\n"
            render.subprocess.run = lambda argv, **kw: _Fail()
            v = render.extract_last_frame("/c/panel_01.mp4", out_png, 145)
            check("R23e rc!=0 -> one violation naming the clip and the last 5 stderr lines",
                  len(v) == 1 and v[0].startswith("clip /c/panel_01.mp4: last-frame extraction failed: ")
                  and "E6" in v[0] and "E2" in v[0] and "E1" not in v[0], "got %r" % v)

            render.subprocess.run = lambda argv, **kw: _Ok()
            os.remove(out_png)
            v = render.extract_last_frame("/c/panel_01.mp4", out_png, 145)
            check("R23f rc 0 but no file written -> a violation, nothing at the final path",
                  len(v) == 1 and "last-frame extraction failed" in v[0]
                  and not os.path.exists(out_png), "got %r" % v)

            def _fake_empty(argv, **kw):
                open(argv[-1], "wb").close()
                return _Ok()
            render.subprocess.run = _fake_empty
            v = render.extract_last_frame("/c/panel_01.mp4", out_png, 145)
            check("R23g a zero-byte frame -> a violation", len(v) == 1
                  and "last-frame extraction failed" in v[0], "got %r" % v)

            def _boom(argv, **kw):
                raise OSError("no ffmpeg here")
            render.subprocess.run = _boom
            v = render.extract_last_frame("/c/panel_01.mp4", out_png, 145)
            check("R23h OSError -> a violation carrying the exception text",
                  len(v) == 1 and "no ffmpeg here" in v[0], "got %r" % v)
    finally:
        render.subprocess.run = saved


def test_extract_last_frame_real_ffmpeg():
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("SKIP R23i-k real last-frame extraction: ffmpeg/ffprobe not on PATH")
        return
    with tempfile.TemporaryDirectory() as td:
        clip = os.path.join(td, "panel_01.mp4")
        proc = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
                               "testsrc2=size=64x64:rate=24", "-frames:v", "9", "-c:v", "libx264",
                               "-pix_fmt", "yuv420p", clip],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        check("R23i synthesized a 9-frame 64x64 h264 clip",
              proc.returncode == 0 and render.clip_frame_count(clip) == 9, proc.stdout[-400:])
        out_png = os.path.join(td, "panel_02.chainseed.png")
        v = render.extract_last_frame(clip, out_png, 9)
        check("R23j extraction succeeds and leaves no tmp file",
              v == [] and os.path.isfile(out_png)
              and not os.path.exists(os.path.join(td, "panel_02.chainseed.tmp.png")), "got %r" % v)
        want = _rgb_framemd5(clip, "select=eq(n\\,8),format=rgb24")
        got = _rgb_framemd5(out_png, "format=rgb24")
        not_last = _rgb_framemd5(clip, "select=eq(n\\,7),format=rgb24")
        check("R23k the PNG is exactly frame 8 -- the last -- and not frame 7",
              want is not None and got == want and not_last != want,
              "want=%r got=%r frame7=%r" % (want, got, not_last))


def test_check_chain_seed():
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("SKIP R26 check_chain_seed: ffmpeg/ffprobe not on PATH")
        return
    with tempfile.TemporaryDirectory() as td:
        def _still(name, source):
            path = os.path.join(td, name)
            p = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
                                source, "-frames:v", "1", path],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            return path if p.returncode == 0 else None
        black = _still("black.png", "color=c=black:s=64x64")
        grey = _still("grey.png", "color=c=0x808080:s=64x64")
        busy = _still("busy.png", "testsrc2=s=64x64")
        # Healthy range (YMIN=16, YMAX=235, range=219) but low average (YAVG=19.42):
        # the RANGE clause alone would NOT reject this frame, so only the YAVG clause
        # detects it. Isolates R26b (which black -- range=0 -- does not).
        lowavg = _still("lowavg.png",
                       "color=c=black:s=64x64,drawbox=x=0:y=0:w=8:h=8:c=white:t=fill")
        check("R26a synthesized black, flat-grey, testsrc2 and low-average frames",
              None not in (black, grey, busy, lowavg))
        if None in (black, grey, busy, lowavg):
            return
        v = render.check_chain_seed(black, 64, 64, 1)
        check("R26b a black frame is degenerate and names panel 1's Motion: as the remedy",
              len(v) == 1 and ("chain frame %s is degenerate (YAVG=" % black) in v[0]
              and "edit panel 1's Motion: in story.md" in v[0], "got %r" % v)
        v = render.check_chain_seed(grey, 64, 64, 4)
        check("R26c a flat grey frame (bright but no range) is degenerate",
              len(v) == 1 and "is degenerate" in v[0] and "edit panel 4's Motion:" in v[0],
              "got %r" % v)
        check("R26d a testsrc2 frame passes", render.check_chain_seed(busy, 64, 64, 1) == [],
              "got %r" % render.check_chain_seed(busy, 64, 64, 1))
        v = render.check_chain_seed(busy, 128, 64, 1)
        check("R26e the wrong size is a size violation",
              v == ["chain frame %s is 64x64, expected 128x64" % busy], "got %r" % v)
        missing = os.path.join(td, "missing.png")
        v = render.check_chain_seed(missing, 64, 64, 1)
        check("R26f a missing frame is an ffprobe failure",
              len(v) == 1 and v[0].startswith("chain frame %s: ffprobe failed: " % missing),
              "got %r" % v)
        v = render.check_chain_seed(lowavg, 64, 64, 7)
        check("R26g a low-average but healthy-range frame is degenerate on the YAVG clause "
              "alone (range=219 would pass the RANGE clause by itself)",
              len(v) == 1 and "is degenerate" in v[0] and "edit panel 7's Motion:" in v[0],
              "got %r" % v)


def test_chain_seed_thresholds():
    """R26: pin the exact threshold constants and the strict-< boundary behavior of both
    clauses in check_chain_seed, using stubbed signalstats output (this tests the
    comparison logic itself, not real ffmpeg)."""
    check("R26h the degenerate thresholds are pinned",
          render.CHAIN_SEED_MIN_YAVG == 20 and render.CHAIN_SEED_MIN_YRANGE == 10,
          "got CHAIN_SEED_MIN_YAVG=%r CHAIN_SEED_MIN_YRANGE=%r"
          % (render.CHAIN_SEED_MIN_YAVG, render.CHAIN_SEED_MIN_YRANGE))

    saved_run = render.subprocess.run
    saved_probe = render.ffprobe_image_size

    class _Ok(object):
        returncode = 0
        stderr = ""

        def __init__(self, stdout):
            self.stdout = stdout

    def _stats(yavg, ymin, ymax):
        stdout = ("lavfi.signalstats.YAVG=%s\nlavfi.signalstats.YMIN=%s\n"
                  "lavfi.signalstats.YMAX=%s\n" % (yavg, ymin, ymax))
        return lambda argv, **kw: _Ok(stdout)

    try:
        render.ffprobe_image_size = lambda path: ((64, 64), None)

        render.subprocess.run = _stats(20, 15, 25)  # YAVG==20, range==10: both at boundary
        v = render.check_chain_seed("/x.png", 64, 64, 1)
        check("R26i YAVG==20 and range==10 both pass (strict <, boundary is inclusive-pass)",
              v == [], "got %r" % v)

        render.subprocess.run = _stats(19.9, 15, 25)  # YAVG just under threshold
        v = render.check_chain_seed("/x.png", 64, 64, 1)
        check("R26j YAVG==19.9 (just under CHAIN_SEED_MIN_YAVG) fails",
              len(v) == 1 and "is degenerate" in v[0], "got %r" % v)

        render.subprocess.run = _stats(20, 15.1, 25)  # range just under threshold
        v = render.check_chain_seed("/x.png", 64, 64, 1)
        check("R26k range==9.9 (just under CHAIN_SEED_MIN_YRANGE) fails",
              len(v) == 1 and "is degenerate" in v[0], "got %r" % v)
    finally:
        render.subprocess.run = saved_run
        render.ffprobe_image_size = saved_probe


def test_prepare_chain_seed_composition():
    saved = (render.extract_last_frame, render.check_chain_seed)
    seen = []
    try:
        unit = {"index": 3, "chain_source": "/c/panel_02.mp4",
                "image_path": "/c/panel_03.chainseed.png"}
        args = _stub_args(frames=145, width=512, height=384)
        render.extract_last_frame = lambda clip, png, frames: (
            seen.append(("x", clip, png, frames)) or ["extract failed"])
        render.check_chain_seed = lambda png, w, h, src: (seen.append(("c", png, w, h, src)) or [])
        v = render.prepare_chain_seed(unit, args)
        check("R27a an extraction failure short-circuits the frame check",
              v == ["extract failed"]
              and seen == [("x", "/c/panel_02.mp4", "/c/panel_03.chainseed.png", 145)],
              "v=%r seen=%r" % (v, seen))
        seen[:] = []
        render.extract_last_frame = lambda clip, png, frames: (seen.append(("x",)) or [])
        render.check_chain_seed = lambda png, w, h, src: (
            seen.append(("c", png, w, h, src)) or ["bad frame"])
        v = render.prepare_chain_seed(unit, args)
        check("R27b after a clean extraction the frame is checked at --width x --height, "
              "naming panel index-1", v == ["bad frame"]
              and seen == [("x",), ("c", "/c/panel_03.chainseed.png", 512, 384, 2)],
              "v=%r seen=%r" % (v, seen))
    finally:
        render.extract_last_frame, render.check_chain_seed = saved


# ---------------------------------------------------------------------------
# R24/R25/R28-R32: the chain loop (a v3 --chain manifest through the REAL main()
# loop and the REAL finish_run; render_panel and the chain seed are scripted)
# ---------------------------------------------------------------------------

def _write_chain_manifest(td, story_id, n_panels):
    still = os.path.join(td, "%s_still.png" % story_id)
    with open(still, "wb") as f:
        f.write(b"png")
    panels = [{"index": 1, "image_path": still, "panel_text": "still image text",
               "motion_prompt": "motion 1", "conditioning": "still", "num_frames": 145}]
    for i in range(2, n_panels + 1):
        panels.append({"index": i, "image_path": None, "panel_text": "motion %d" % i,
                       "motion_prompt": "motion %d" % i, "conditioning": "chain",
                       "num_frames": 145})
    return _write_manifest(td, panels, story_id=story_id, schema_version=3), still


def _drive_chain(td, story_id, n_panels, extra_argv, script=None, seed_violations=None,
                 screen=None, still_probe=((704, 448), None)):
    """script[i] is the list of statuses successive render_panel calls on panel i
    return ("ok"/"error"/"fatal"); a panel missing from script always returns "ok".
    "fatal" returns status "error" with fatal=True, matching render_panel's own
    fatal-backend-error shape.
    seed_violations[i] is what prepare_chain_seed returns for panel i (default []).
    screen replaces run_input_content_screen (default: always 0). still_probe is
    what ffprobe_image_size returns for the panel-1 still.
    Returns (rc, calls, summary, prepared, stdout, stderr)."""
    manifest, _still = _write_chain_manifest(td, story_id, n_panels)
    clips = os.path.join(td, "clips_%s" % story_id)
    out = os.path.join(td, "%s.mp4" % story_id)
    story_root = os.path.join(td, "story")
    os.makedirs(os.path.join(story_root, story_id), exist_ok=True)
    script = script or {}
    calls, prepared, attempts = [], [], {}

    def fake_render_panel(unit, args):
        i = unit["index"]
        calls.append(i)
        n = attempts.get(i, 0)
        attempts[i] = n + 1
        statuses = script.get(i, ["ok"])
        status = statuses[min(n, len(statuses) - 1)]
        if status == "ok":
            return {"unit": unit["label"], "status": "ok", "attempts": 1, "seconds": 1.0,
                    "clip": os.path.abspath(unit["clip_path"]), "resumed": False}
        if status == "fatal":
            return {"unit": unit["label"], "status": "error", "attempts": 1, "seconds": 0.1,
                    "clip": None, "rc": 1, "error": "stub fatal failure", "fatal": True}
        return {"unit": unit["label"], "status": status, "attempts": 1, "seconds": 0.1,
                "clip": None, "rc": 1, "error": "stub failure"}

    def fake_prepare(unit, args):
        prepared.append(unit["index"])
        return list((seed_violations or {}).get(unit["index"], []))

    saved = (render.story_dir_for, render.render_panel, render.prepare_chain_seed,
             render.run_input_content_screen, render.SKILL._resolve_bin,
             render.ffprobe_image_size, render.probe_streams, render.assert_clips_uniform,
             render.build_concat_command)
    so, se = io.StringIO(), io.StringIO()
    try:
        render.story_dir_for = lambda sid: os.path.join(story_root, sid)
        render.render_panel = fake_render_panel
        render.prepare_chain_seed = fake_prepare
        render.run_input_content_screen = screen or (lambda paths: 0)
        render.SKILL._resolve_bin = lambda: sys.executable
        render.ffprobe_image_size = lambda path: still_probe
        render.probe_streams = lambda p: {"streams": []}
        render.assert_clips_uniform = lambda *a: None
        render.build_concat_command = lambda lp, o: [
            sys.executable, "-c", "import sys; open(sys.argv[1],'wb').write(b'MOVIE')", o]
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            rc = render.main([manifest, out, "--clips-dir", clips] + extra_argv)
    finally:
        (render.story_dir_for, render.render_panel, render.prepare_chain_seed,
         render.run_input_content_screen, render.SKILL._resolve_bin,
         render.ffprobe_image_size, render.probe_streams, render.assert_clips_uniform,
         render.build_concat_command) = saved
    found = glob.glob(os.path.join(story_root, story_id, "runs", "*", "story_summary.json"))
    summary = None
    if found:
        with open(max(found, key=os.path.getmtime)) as f:
            summary = json.load(f)
    return rc, calls, summary, prepared, so.getvalue(), se.getvalue()


def _clip_names(summary):
    return [os.path.basename(c) for c in (summary or {}).get("clips", [])]


def test_chain_manifest_rejects_skip_policy():
    with tempfile.TemporaryDirectory() as td:
        for extra, tag in (([], "R31a"), (["--dry-run"], "R31b")):
            rc, calls, summary, prepared, out, err = _drive_chain(
                td, "skipchain%s" % tag, 3, ["--skip-input-screen", "--on-panel-failure", "skip"] + extra)
            check("%s --on-panel-failure skip on a chained manifest exits 2 before any work" % tag,
                  rc == 2 and calls == [] and summary is None
                  and "--on-panel-failure skip is not allowed for a chained manifest: a skipped "
                      "panel leaves the next panel with no frame to continue from" in err,
                  "rc=%r calls=%r err=%r" % (rc, calls, err))


def test_chain_loop_inline_retry_then_stop():
    with tempfile.TemporaryDirectory() as td:
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "retrystop", 3, ["--skip-input-screen", "--retry-failed", "1", "--retry-idle", "0"],
            script={2: ["error", "error"]})
        check("R24a panel 2 fails twice -> exit 1", rc == 1, "rc=%r" % rc)
        check("R24b panel 2 was rendered twice (inline retry), panel 3 never",
              calls == [1, 2, 2], "calls=%r" % calls)
        check("R24c stopped_reason is chain_broken", s and s["stopped_reason"] == "chain_broken",
              "got %r" % (s or {}).get("stopped_reason"))
        check("R24d panel 3 is not_attempted",
              s and s["units"][2]["status"] == "not_attempted", "got %r" % (s or {}).get("units"))
        check("R24e the retry is recorded as attempt 2 with its first failure",
              s and s["units"][1]["attempts"] == 2 and s["units"][1]["first_failure"] == "error",
              "got %r" % (s or {}).get("units"))
        check("R24f the completed prefix (panel 1) is concatenated into the movie",
              _clip_names(s) == ["panel_01.mp4"] and s["output_path"] is not None,
              "got %r" % _clip_names(s))
        check("R24g the inline-retry banner and the relaunch hint are printed",
              "=== inline retry: panel 2 (chained; later panels depend on it) ===" in out
              and "relaunch:" in out, "got %r" % out[-1200:])
        check("R24h the chain seed is prepared once for panel 2 (the retry reuses it)",
              prepared == [2], "prepared=%r" % prepared)

    with tempfile.TemporaryDirectory() as td:
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "retryok", 3, ["--skip-input-screen", "--retry-failed", "1", "--retry-idle", "0"],
            script={2: ["error", "ok"]})
        check("R24i a successful inline retry completes the chain and exits 0",
              rc == 0 and calls == [1, 2, 2, 3] and prepared == [2, 3]
              and s["units"][1]["status"] == "ok" and s["units"][1]["attempts"] == 2
              and s["stopped_reason"] is None,
              "rc=%r calls=%r prepared=%r" % (rc, calls, prepared))

    with tempfile.TemporaryDirectory() as td:
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "noretry", 3, ["--skip-input-screen"], script={2: ["error"]})
        check("R24j without --retry-failed one failure is chain_broken",
              rc == 1 and calls == [1, 2] and s["stopped_reason"] == "chain_broken",
              "rc=%r calls=%r" % (rc, calls))

    with tempfile.TemporaryDirectory() as td:
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "p1fails", 3, ["--skip-input-screen", "--retry-failed", "1", "--retry-idle", "0"],
            script={1: ["error", "error"]})
        check("R24k panel 1 of a chained manifest also retries inline, then stops",
              rc == 1 and calls == [1, 1] and prepared == [] and s["stopped_reason"] == "chain_broken"
              and s["output_path"] is None, "rc=%r calls=%r" % (rc, calls))

    # G14: the end-of-run retry pass must never run for a chained manifest, even when
    # finish_run is reached with stopped_reason None.
    saved = (render.render_panel, render.probe_streams, render.assert_clips_uniform,
             render.build_concat_command)
    retried = []
    try:
        render.render_panel = lambda unit, args: (retried.append(unit["index"]) or {
            "unit": unit["label"], "status": "ok", "attempts": 1, "seconds": 0.0,
            "clip": "/a/2.mp4", "resumed": False})
        render.probe_streams = lambda p: {"streams": []}
        render.assert_clips_uniform = lambda *a: None
        render.build_concat_command = lambda lp, o: [
            sys.executable, "-c", "import sys; open(sys.argv[1],'wb').write(b'M')", o]
        with tempfile.TemporaryDirectory() as td:
            run_root = os.path.join(td, "run")
            os.makedirs(run_root)
            args = render.build_parser().parse_args(
                [os.path.join(td, "m.json"), os.path.join(td, "out.mp4"),
                 "--retry-failed", "1", "--retry-idle", "0"])
            panels = [{"index": 1, "image_path": "/s.png", "panel_text": "t", "motion_prompt": "m",
                       "conditioning": "still"},
                      {"index": 2, "image_path": None, "panel_text": "m2", "motion_prompt": "m2",
                       "conditioning": "chain"}]
            units = render.build_units(panels, 0, os.path.join(td, "clips"), run_root)
            ur = {1: {"unit": "panel-1", "status": "ok", "attempts": 1, "seconds": 1.0,
                      "clip": "/a/1.mp4", "resumed": False},
                  2: {"unit": "panel-2", "status": "error", "attempts": 1, "seconds": 0.1,
                      "clip": None, "rc": 1, "error": "x"}}
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                render.finish_run(args, ["m", "o"], {"schema_version": 3}, units, ur,
                                  {1: "/a/1.mp4"}, 1, None, run_root, "sid")
        check("R24l the end-of-run retry pass never runs for a chained manifest", retried == [],
              "retried=%r" % retried)
    finally:
        (render.render_panel, render.probe_streams, render.assert_clips_uniform,
         render.build_concat_command) = saved


def test_chain_loop_inline_retry_fatal_is_backend_failure():
    """Review Finding 1: a fatal backend error on the INLINE chain retry must stop with
    stopped_reason backend_failure, the same label a fatal error on the first attempt
    already gets -- not chain_broken, which would mislabel an unretryable backend
    crash as an ordinary chain failure and print the (nonsensical) relaunch hint."""
    with tempfile.TemporaryDirectory() as td:
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "retryfatal", 3, ["--skip-input-screen", "--retry-failed", "1", "--retry-idle", "0"],
            script={2: ["error", "fatal"]})
        check("F1a a fatal error on the inline chain retry stops with backend_failure, "
              "not chain_broken",
              rc == 1 and calls == [1, 2, 2] and s and s["stopped_reason"] == "backend_failure",
              "rc=%r calls=%r stopped_reason=%r" % (rc, calls, (s or {}).get("stopped_reason")))
        check("F1b the fatal retry is still recorded as attempt 2 with its first failure",
              s["units"][1]["attempts"] == 2 and s["units"][1]["first_failure"] == "error"
              and s["units"][1]["status"] == "error", "got %r" % s["units"][1])
        check("F1c panel 3 is not_attempted and no relaunch hint is printed for a "
              "backend_failure stop",
              s["units"][2]["status"] == "not_attempted" and "relaunch:" not in out,
              "units=%r out=%r" % (s["units"], out[-500:]))


def test_chain_loop_seed_invalid_stops():
    with tempfile.TemporaryDirectory() as td:
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "seedbad", 3, ["--skip-input-screen", "--retry-failed", "1", "--retry-idle", "0"],
            seed_violations={2: ["chain frame X is degenerate (YAVG=16.0, YMIN=16.0, YMAX=16.0)"]})
        check("R28a a degenerate chain frame stops the run before panel 2 renders",
              rc == 1 and calls == [1] and prepared == [2], "rc=%r calls=%r" % (rc, calls))
        check("R28b panel 2 is recorded chain_seed_invalid with 0 attempts and the reason",
              s and s["units"][1]["status"] == "chain_seed_invalid"
              and s["units"][1]["attempts"] == 0 and "degenerate" in s["units"][1]["error"],
              "got %r" % (s or {}).get("units"))
        check("R28c stopped_reason chain_seed_invalid; panel 3 not_attempted; prefix kept",
              s["stopped_reason"] == "chain_seed_invalid"
              and s["units"][2]["status"] == "not_attempted" and _clip_names(s) == ["panel_01.mp4"])
        check("R28d the operator sees 'panel 2 FAILED (chain seed):'",
              "panel 2 FAILED (chain seed): chain frame X is degenerate" in err, "got %r" % err)

    with tempfile.TemporaryDirectory() as td:
        screened = []

        def screen(paths):
            screened.append(list(paths))
            return 3 if any(p.endswith(".chainseed.png") for p in paths) else 0
        rc, calls, s, prepared, out, err = _drive_chain(td, "seedblocked", 3, [], screen=screen)
        check("R28e a chain frame that fails the content screen stops the run",
              rc == 1 and calls == [1] and s["units"][1]["status"] == "chain_seed_blocked"
              and s["stopped_reason"] == "chain_seed_blocked", "rc=%r calls=%r" % (rc, calls))
        check("R28f the still is screened at startup and the chain frame before its render",
              len(screened) == 2 and screened[0][0].endswith("seedblocked_still.png")
              and screened[1][0].endswith("panel_02.chainseed.png"), "got %r" % screened)

    with tempfile.TemporaryDirectory() as td:
        screened = []
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "noscreen", 3, ["--skip-input-screen"],
            screen=lambda paths: (screened.append(list(paths)) or 0))
        check("R28g --skip-input-screen also skips the chain-frame screen",
              rc == 0 and screened == [] and calls == [1, 2, 3], "rc=%r screened=%r" % (rc, screened))


def test_chain_resume_cascade():
    saved = render.clip_frame_count
    try:
        render.clip_frame_count = lambda p: 145
        with tempfile.TemporaryDirectory() as td:
            model = os.path.join(td, "model")
            os.makedirs(model)
            with open(os.path.join(model, "split_model.json"), "w") as f:
                f.write("{}")
            still = os.path.join(td, "still.png")
            with open(still, "wb") as f:
                f.write(b"still")
            clips = os.path.join(td, "clips")
            os.makedirs(clips)

            def _panels(p2="motion 2"):
                return [{"index": 1, "image_path": still, "panel_text": "img",
                         "motion_prompt": "motion 1", "conditioning": "still"},
                        {"index": 2, "image_path": None, "panel_text": p2, "motion_prompt": p2,
                         "conditioning": "chain"},
                        {"index": 3, "image_path": None, "panel_text": "motion 3",
                         "motion_prompt": "motion 3", "conditioning": "chain"}]

            args = _stub_args(model=model, frames=145, resume=True)
            units = render.build_units(_panels(), 0, clips)
            for u in units:  # an earlier, complete run, recorded in order
                with open(u["clip_path"], "wb") as f:
                    f.write(("clip %d" % u["index"]).encode())
                render.write_clip_provenance(u["clip_path"], render.build_clip_provenance(u, args))

            def _predict(us):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    render.print_dry_run(args, {"schema_version": 3}, us,
                                         "_cascade_%d" % os.getpid(), clips)
                out = buf.getvalue()
                m = re.search(r"resume: \d+ panel\(s\) would render: (\[.*\])", out)
                return (json.loads(m.group(1)) if m else None), out

            got, _ = _predict(units)
            check("R25a unchanged prompts reuse all three clips", got == [], "got %r" % got)
            got, out = _predict(render.build_units(_panels(p2="motion 2 edited"), 0, clips))
            check("R25b editing panel 2's Motion: reuses 1 and re-renders 2 and 3",
                  got == [2, 3], "got %r" % got)
            check("R25c the first render command conditions on panel 2's chain seed",
                  "panel_02.chainseed.png" in out.split("first render command:")[1].splitlines()[0],
                  "got %r" % out)
            with open(units[0]["clip_path"], "wb") as f:
                f.write(b"clip 1 re-rendered")
            render.write_clip_provenance(units[0]["clip_path"],
                                         render.build_clip_provenance(units[0], args))
            got, _ = _predict(units)
            check("R25d new clip-1 bytes (with a valid clip-1 sidecar) re-render 2 and 3",
                  got == [2, 3], "got %r" % got)
    finally:
        render.clip_frame_count = saved


def test_chain_dry_run_resume_missing_source_does_not_crash():
    """Task 10 hazard closure: a v3 chain manifest whose previous clip does not
    exist on disk yet (nothing has ever been rendered) must not make print_dry_run's
    --resume prediction crash with a FileNotFoundError out of build_clip_provenance's
    file_sha256(chain_source). It must cleanly predict every panel would render."""
    with tempfile.TemporaryDirectory() as td:
        still = os.path.join(td, "still.png")
        with open(still, "wb") as f:
            f.write(b"png")
        clips = os.path.join(td, "clips")
        os.makedirs(clips)
        panels = [{"index": 1, "image_path": still, "panel_text": "img",
                   "motion_prompt": "motion 1", "conditioning": "still"},
                  {"index": 2, "image_path": None, "panel_text": "motion 2",
                   "motion_prompt": "motion 2", "conditioning": "chain"},
                  {"index": 3, "image_path": None, "panel_text": "motion 3",
                   "motion_prompt": "motion 3", "conditioning": "chain"}]
        args = _stub_args(frames=145, resume=True)
        units = render.build_units(panels, 0, clips)
        assert not os.path.exists(units[1]["chain_source"]), "test setup invalid"
        assert not os.path.exists(units[2]["chain_source"]), "test setup invalid"

        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = render.print_dry_run(args, {"schema_version": 3}, units,
                                          "hazardcheck", clips)
        except FileNotFoundError as e:
            check("hazard: dry-run --resume on a chain manifest with no prior clip "
                  "does not raise FileNotFoundError", False, "raised %r" % e)
        else:
            out = buf.getvalue()
            m = re.search(r"resume: \d+ panel\(s\) would render: (\[.*\])", out)
            got = json.loads(m.group(1)) if m else None
            check("hazard: dry-run --resume on a chain manifest with no prior clip "
                  "does not raise, and predicts every panel would render",
                  rc == 0 and got == [1, 2, 3], "rc=%r got=%r out=%r" % (rc, got, out))


def test_chain_resume_real_main_mid_chain_recovery():
    """Review Finding 2: the ONLY way this code runs in production is main() with
    --resume, since bin/ltx-movie::_render_flags always passes it. Drive the REAL
    main() on a v3 chain manifest where panel 1's clip already exists (from an
    earlier, crashed run) and confirm --resume reuses it and picks the chain up from
    there -- rendering, and preparing the chain seed for, only panels 2 and 3."""
    saved = (render.story_dir_for, render.render_panel, render.prepare_chain_seed,
             render.run_input_content_screen, render.SKILL._resolve_bin,
             render.clip_frame_count, render.probe_streams, render.assert_clips_uniform,
             render.build_concat_command)
    calls, prepared = [], []
    try:
        with tempfile.TemporaryDirectory() as td:
            manifest, _still = _write_chain_manifest(td, "midchain", 3)
            clips = os.path.join(td, "clips_midchain")
            os.makedirs(clips)
            out = os.path.join(td, "midchain.mp4")
            story_root = os.path.join(td, "story")
            os.makedirs(os.path.join(story_root, "midchain"), exist_ok=True)
            model = os.path.join(td, "model")
            os.makedirs(model)
            with open(os.path.join(model, "split_model.json"), "w") as f:
                f.write("{}")

            argv = [manifest, out, "--clips-dir", clips, "--skip-input-screen",
                    "--frames", "145", "--resume", "--model", model]
            args = render.build_parser().parse_args(argv)
            panels = render.load_manifest(manifest)["panels"]
            units = render.build_units(panels, args.seed, clips)

            # An earlier run completed panel 1 and then crashed before panel 2.
            with open(units[0]["clip_path"], "wb") as f:
                f.write(b"clip 1 pre-existing")
            render.write_clip_provenance(units[0]["clip_path"],
                                         render.build_clip_provenance(units[0], args))

            def fake_render_panel(unit, args):
                i = unit["index"]
                calls.append(i)
                with open(unit["clip_path"], "wb") as f:
                    f.write(("clip %d" % i).encode())
                render.write_clip_provenance(unit["clip_path"],
                                             render.build_clip_provenance(unit, args))
                return {"unit": unit["label"], "status": "ok", "attempts": 1, "seconds": 1.0,
                        "clip": os.path.abspath(unit["clip_path"]), "resumed": False}

            def fake_prepare(unit, args):
                prepared.append(unit["index"])
                return []

            render.story_dir_for = lambda sid: os.path.join(story_root, sid)
            render.render_panel = fake_render_panel
            render.prepare_chain_seed = fake_prepare
            render.run_input_content_screen = lambda paths: 0
            render.SKILL._resolve_bin = lambda: sys.executable
            render.clip_frame_count = lambda p: 145
            render.probe_streams = lambda p: {"streams": []}
            render.assert_clips_uniform = lambda *a: None
            render.build_concat_command = lambda lp, o: [
                sys.executable, "-c", "import sys; open(sys.argv[1],'wb').write(b'MOVIE')", o]

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = render.main(argv)

            check("F2a mid-chain --resume through the REAL main() reuses panel 1's "
                  "existing clip and renders only 2 and 3",
                  rc == 0 and calls == [2, 3], "rc=%r calls=%r" % (rc, calls))
            check("F2b the chain seed is prepared only for the panels that actually "
                  "render, not the reused one",
                  prepared == [2, 3], "prepared=%r" % prepared)
    finally:
        (render.story_dir_for, render.render_panel, render.prepare_chain_seed,
         render.run_input_content_screen, render.SKILL._resolve_bin,
         render.clip_frame_count, render.probe_streams, render.assert_clips_uniform,
         render.build_concat_command) = saved


def test_v3_still_aspect_preflight():
    with tempfile.TemporaryDirectory() as td:
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "aspectbad", 2, ["--skip-input-screen"], still_probe=((1280, 704), None))
        check("R29a a 1280x704 still against --width 704 --height 448 exits 2, no render",
              rc == 2 and calls == [] and s is None
              and "is 1280x704; its aspect ratio does not match --width x --height (704x448), "
                  "so ltx-2-mlx would crop it" in err, "rc=%r err=%r" % (rc, err))
        check("R29b no run root was created",
              not glob.glob(os.path.join(td, "story", "aspectbad", "runs", "*")))
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "aspectok", 2, ["--skip-input-screen"], still_probe=((1408, 896), None))
        check("R29c a 1408x896 still (2W x 2H) passes", rc == 0 and calls == [1, 2],
              "rc=%r err=%r" % (rc, err))
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "aspectprobe", 2, ["--skip-input-screen"], still_probe=(None, "rc=1: boom"))
        check("R29d an unmeasurable still exits 2", rc == 2 and "ffprobe failed: rc=1: boom" in err,
              "rc=%r err=%r" % (rc, err))
        probed = []
        saved = render.ffprobe_image_size
        render.ffprobe_image_size = lambda p: (probed.append(p) or ((1, 1), None))
        try:
            rc, cap, rendered, _ = _drive_main(td, "v2noprobe", 2, ["--on-panel-failure", "skip"],
                                               panel_status="ok")
        finally:
            render.ffprobe_image_size = saved
        check("R29e a schema_version 2 manifest is never aspect-probed",
              probed == [] and rendered == [1, 2], "probed=%r rendered=%r" % (probed, rendered))


def test_dry_run_chain_lines():
    with tempfile.TemporaryDirectory() as td:
        manifest, still = _write_chain_manifest(td, "drychain", 3)
        clips = os.path.join(td, "clips")
        os.makedirs(clips)
        r = _run_render([manifest, os.path.join(td, "movie.mp4"), "--clips-dir", clips,
                         "--frames", "145", "--dry-run"])
        o = r.stdout
        check("R30a a chained dry run exits 0", r.returncode == 0,
              "rc=%r stderr=%r" % (r.returncode, r.stderr))
        check("R30b panel 1 is I2V from the still", ("  panel  1: I2V %s" % still) in o, "got %r" % o)
        check("R30c panels 2-3 name the exact source frame and clip",
              ("  panel  2: I2V chained <- last frame (index 144) of %s"
               % os.path.join(clips, "panel_01.mp4")) in o
              and ("  panel  3: I2V chained <- last frame (index 144) of %s"
                   % os.path.join(clips, "panel_02.mp4")) in o, "got %r" % o)
        check("R30d the first render command conditions on the still",
              still in o.split("first render command:")[1].splitlines()[0], "got %r" % o)
        check("R30e the dry run wrote nothing", os.listdir(clips) == [])


def test_single_panel_v3_manifest_is_not_chained():
    with tempfile.TemporaryDirectory() as td:
        rc, calls, s, prepared, out, err = _drive_chain(td, "single", 1, ["--skip-input-screen"])
        check("R32a a one-panel v3 manifest renders its still and concatenates one clip",
              rc == 0 and calls == [1] and prepared == [] and _clip_names(s) == ["panel_01.mp4"],
              "rc=%r calls=%r" % (rc, calls))
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "singleskip", 1, ["--skip-input-screen", "--on-panel-failure", "skip"])
        check("R32b it has no chain units, so --on-panel-failure skip is allowed",
              rc == 0 and calls == [1], "rc=%r err=%r" % (rc, err))


if __name__ == "__main__":
    test_parser_defaults()
    test_gemma_lora_reach_generate_video()
    test_clip_provenance_contract()
    test_cached_model_metadata_and_io_failures()
    test_provenance_rejects_changes_during_generation()
    test_geometry_validation()
    test_run_id_and_story_dir()
    test_render_script_has_no_heavy_imports()
    test_load_manifest()
    test_build_units()
    test_clip_is_reusable()
    test_clip_frame_count_argv()
    test_clip_frame_count_survives_missing_ffprobe()
    test_probe_streams_survives_missing_ffprobe()
    test_build_concat_list()
    test_build_concat_command()
    test_assert_clips_uniform()
    test_real_ffmpeg_concat()
    test_real_clip_frame_count_smoke()
    test_probe_timeout_kwarg_present()
    test_estimate_default_source()
    test_estimate_measured_source()
    test_estimate_excludes_resumed_and_mismatched()
    test_estimate_prefers_newest_matching_summary()
    test_estimate_skips_corrupt_summary()
    test_estimate_order_independent_of_glob_order()
    test_estimate_dangling_path_sorts_last_not_fatal()
    test_estimate_mtime_tie_break_is_deterministic()
    test_estimate_model_key_gates_reuse()
    test_estimate_handles_null_units_and_non_dict_entries()
    test_format_estimate_lines()
    test_dry_run_output()
    test_dry_run_resume_lines()
    test_manifest_without_story_id_falls_back()
    test_dry_run_validates_output_path()
    test_input_content_screen_shape()
    test_input_content_screen_empty_list_is_cheap()
    test_input_content_screen_behavioral()
    test_render_panel_statuses()
    test_jetsam_ladder_text()
    test_preflight_exit_codes()
    test_preflight_clips_dir_not_writable()
    test_main_content_screen_is_live()
    test_panel_loop_circuit_breaker()
    test_panel_loop_stop_policy_wins_over_circuit_breaker()
    test_panel_loop_max_consecutive_failures_zero_disables()
    test_panel_loop_reuse_requires_resume_flag()
    test_run_root_collision_is_loud()
    test_summary_shape()
    test_finish_run_emits_exactly_summary_keys()
    test_finish_run_writes_summary_when_concat_fails()
    test_resume_force_orthogonality()
    test_failure_state_machine()
    test_extract_last_frame_argv()
    test_extract_last_frame_real_ffmpeg()
    test_check_chain_seed()
    test_chain_seed_thresholds()
    test_prepare_chain_seed_composition()
    test_chain_manifest_rejects_skip_policy()
    test_chain_loop_inline_retry_then_stop()
    test_chain_loop_inline_retry_fatal_is_backend_failure()
    test_chain_loop_seed_invalid_stops()
    test_chain_resume_cascade()
    test_chain_dry_run_resume_missing_source_does_not_crash()
    test_chain_resume_real_main_mid_chain_recovery()
    test_v3_still_aspect_preflight()
    test_dry_run_chain_lines()
    test_single_panel_v3_manifest_is_not_chained()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
