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
    summary = {"schema_version": 3, "frames_per_panel": 241, "width": 704,
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
            json.dump({"frames_per_panel": 241, "width": 704, "height": 448,
                      "low_ram": True, "tile_frames": 1, "tile_spatial": 1,
                      "model": render.SKILL.MODEL_ID, "units": None}, f)
        secs, label = render.estimate_seconds_per_panel(
            td, 241, 704, 448, True, 1, 1, render.SKILL.MODEL_ID)
        check("R8u units:null does not crash, falls back to default",
              secs == float(render.SECONDS_PER_PANEL_ESTIMATE), "got %r" % secs)

        run_root2 = os.path.join(td, "runs", "20260910T080808Z-88888888")
        os.makedirs(run_root2, exist_ok=True)
        with open(os.path.join(run_root2, "story_summary.json"), "w") as f:
            json.dump({"frames_per_panel": 241, "width": 704, "height": 448,
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
            render.clip_is_reusable = lambda path, frames: reusable
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
        self.fail_indices = set(fail_indices)
        self.fail_status = fail_status
        self.saved = {}
        img = os.path.join(td, "p.png")
        with open(img, "wb") as f:
            f.write(b"png")
        self.manifest = _write_manifest(
            td, [_panel(i, img) for i in range(1, n_panels + 1)], story_id=story_id)
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
                            "--skip-input-screen"] + list(extra))


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

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
