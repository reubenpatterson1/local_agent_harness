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

def _probe(width=704, height=480, rfr="24/1", vcodec="h264", pix="yuv420p",
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
        render.assert_clips_uniform(pairs, 704, 480, 24)
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
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=704x480:rate=24",
                 "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                 "-t", "1", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", clip],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if proc.returncode != 0:
                check("R9a synthesized clip %d" % i, False, proc.stdout[-800:])
                return
            clips.append(clip)
        check("R9a synthesized three 1s 704x480/24fps clips", len(clips) == 3)

        counts = [render.clip_frame_count(c) for c in clips]
        check("R9b clip_frame_count reads 24 packets per clip", counts == [24, 24, 24],
              "got %r" % counts)

        pairs = [(c, render.probe_streams(c)) for c in clips]
        err = None
        try:
            render.assert_clips_uniform(pairs, 704, 480, 24)
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

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
