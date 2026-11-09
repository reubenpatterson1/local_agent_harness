"""Tests for bin/ltx-movie's --seed-context frame (docs/superpowers/specs/2026-11-10-seeded-shots-context-design.md,
CX14-CX20: CXT12-CXT19): Phase 2 makes each still, then its clip (bin/ltx-mlx-render --resume on a manifest of the
panels so far), then extracts the clip's exact last frame as the next panel's context picture; Phases 3 and 4 reuse
every clip.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_ltx_movie_seed_context_frame.py

The module under test is tests/test_ltx_movie_seed_context.py's movie, with its ctx_env fixture and Qwen fake. The
frame fixture adds: _stream_and_tee as a fake that writes manifest.json for a bin/ltx-story-manifest command and,
for a bin/ltx-mlx-render command, writes clips/panel_NN.mp4 whose bytes name the panel's motion, its still's sha256
and a per-panel variant; _ltx_render as a fake module whose extract_last_frame writes a 704x448 PNG whose colour
follows the clip bytes; _wait_for_avail as a recorder. Every fake appends to the Qwen fake's events, so one list holds
the order of every step. CXT16 drives the real bin/ltx-mlx-render main() in-process instead (its generator, probes,
concat and content screen stubbed, as tests/test_ltx_mlx_render.py's _Harness does). No test loads a model, renders,
contacts a server or touches port 8177 or 8178. Stdlib, PIL and pytest.
"""

import builtins
import glob
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import sys
import types

import pytest
from PIL import Image

import movie_ui_testutil as mt
import qwen_edit
from test_ltx_movie_seed_context import (HARBOUR, IMAGES, SEED, _args, _edited, _pixel, _record, _story,  # noqa: F401
                                         ctx_env, movie)

WS = mt.WS
FRAME = {"mode": "frame", "order": "seed-first"}
UNC_LIST = [{"id": "uncensored", "scale": 1.0}]
RENDER_KEYS = dict(frames=145, fps=24, model="M", gemma="G", tile_frames=1, tile_spatial=1, lora_path=None,
                   no_low_ram=False, force=False, panel_timeout=7200, no_stills=False, min_avail_gib=25.0,
                   avail_timeout=1800, no_review=True, speech_delivery="beats", no_narration=False,
                   speech_only=False)


def _frame_args(tmp, **overrides):
    values = dict(RENDER_KEYS, seed_context=FRAME)
    values.update(overrides)
    return _args(tmp, **values)


def _colour(clip):
    with open(clip, "rb") as f:
        data = f.read()
    return (int(os.path.basename(clip)[6:8]) * 40, 100, sum(data) % 251)


@pytest.fixture
def frame_env(ctx_env, monkeypatch):
    """The module docstring's fakes. Returns ctx_env plus {"events", "rc", "variant", "violations", "rendered",
    "uptos", "cmds", "frame_error"}."""
    tmp, fake = ctx_env["tmp"], ctx_env["fake"]
    events = fake.events
    state = {"events": events, "rc": {}, "manifest_rc": [0], "variant": {}, "violations": {}, "rendered": [],
             "uptos": [], "cmds": [], "frame_error": [None]}

    def stream(cmd, log_path):
        state["cmds"].append((list(cmd), log_path))
        story_dir = os.path.join(tmp, "stories", "s1")
        if os.path.basename(cmd[1]) == "ltx-story-manifest":
            images = [cmd[i + 1] for i, word in enumerate(cmd) if word == "--image"]
            events.append(("manifest", len(images)))
            panels = [{"index": i, "image_path": image, "conditioning": "still", "panel_text": "panel %d" % i,
                       "motion_prompt": "motion %d" % i, "num_frames": 145} for i, image in enumerate(images, 1)]
            with open(os.path.join(story_dir, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump({"schema_version": 3, "story_id": "s1", "fps": 24, "panels": panels}, f)
            return state["manifest_rc"][0]
        with open(cmd[2], encoding="utf-8") as f:
            upto = json.load(f)
        k = len(upto["panels"])
        state["uptos"].append(upto)
        events.append(("render", k))
        os.makedirs(os.path.join(story_dir, "clips"), exist_ok=True)
        for p in upto["panels"]:
            with open(p["image_path"], "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
            data = ("%s %s %s" % (p["motion_prompt"], digest, state["variant"].get(p["index"], ""))).encode()
            clip = os.path.join(story_dir, "clips", "panel_%02d.mp4" % p["index"])
            if not os.path.isfile(clip) or open(clip, "rb").read() != data:
                with open(clip, "wb") as f:
                    f.write(data)
                state["rendered"].append(p["index"])
        with open(cmd[3], "wb") as f:
            f.write(b"MOVIE")
        return state["rc"].get(k, 0)

    def extract_last_frame(clip, out_png, frames):
        events.append(("frame", int(os.path.basename(clip)[6:8]), frames))
        if state["frame_error"][0] is not None:
            raise state["frame_error"][0]
        Image.new("RGB", (704, 448), _colour(clip)).save(out_png)
        return []

    def check_chain_seed(png_path, width, height, source_panel):
        events.append(("check", source_panel, (width, height)))
        return state["violations"].get(source_panel, [])

    monkeypatch.setattr(movie, "_stream_and_tee", stream)
    monkeypatch.setattr(movie, "_ltx_render", lambda: types.SimpleNamespace(
        extract_last_frame=extract_last_frame, check_chain_seed=check_chain_seed))
    monkeypatch.setattr(movie, "_wait_for_avail", lambda gib, timeout: events.append(("avail", gib, timeout)) or True)
    return dict(ctx_env, **state)


def _work(tmp, *names):
    return os.path.join(tmp, "stories", "s1", "seed_context_edits", *names)


def _clip(tmp, n):
    return os.path.join(tmp, "stories", "s1", "clips", "panel_%02d.mp4" % n)


# --- CXT12 (CX14, CX15, CX17): the flag, the phase tuple, the render flags and the shared helpers -------------------

def test_cxt12_the_flag_the_phases_and_the_helpers(ctx_env, monkeypatch, capsys):
    tmp = ctx_env["tmp"]
    args = movie.build_parser().parse_args(["n", "--story-id", "s1", "--shots", "--seed-image", "x.png",
                                            "--seed-context", "frame"])
    args.seed_edit = {"qwen_model": "qwen21-q4", "loras": UNC_LIST}
    assert movie._resolve_seed_context(args) == 0 and args.seed_context == FRAME
    seq = dict(no_stills=False, story_server_stop_after_story=True, seed_image="x.png", story_only=False, shots=True,
               redo_panels=[], seed_edit={"qwen_model": "qwen21-q4"}, seed_context=FRAME)
    names = lambda **kw: [p.__name__ for p in movie._phase_sequence(types.SimpleNamespace(**dict(seq, **kw)))]  # noqa
    assert names() == ["phase0_seed", "phase1_story", "phase_release_story_server", "phase_seed_context_frames",
                       "phase3_manifest", "phase4_render"]
    assert names(redo_panels=[2], story_server_stop_after_story=False) == [
        "phase0_seed", "phase1_story", "phase_redo_shots", "phase_seed_context_frames", "phase3_manifest",
        "phase4_render"]
    assert names(story_only=True) == ["phase0_seed", "phase1_story"]
    assert "phase2_stills" in names(seed_context={"mode": "still", "order": "seed-first"})
    fargs = _frame_args(tmp)
    flags = movie._phase4_flags(fargs)
    assert flags == movie._phase4_flags(fargs)
    assert flags[flags.index("--on-panel-failure") + 1] == "skip"
    assert flags[flags.index("--retry-failed") + 1] == "1"
    assert "--resume" in flags
    assert movie._render_tool() == os.path.join(WS, "bin", "ltx-mlx-render")
    _story(tmp)
    rc, cmd = movie._phase3_manifest_cmd(fargs)
    assert rc == 0 and cmd[:2] == [sys.executable, os.path.join(WS, "bin", "ltx-story-manifest")]
    assert cmd[cmd.index("--shots") + 1:cmd.index("--fps")] == movie._shots_image_flags(fargs)
    rc, placeholder_cmd = movie._phase3_manifest_cmd(fargs, ["--image", "P"] * 4)
    assert placeholder_cmd[placeholder_cmd.index("--shots") + 1:placeholder_cmd.index("--fps")] == ["--image", "P"] * 4
    assert [w for w in placeholder_cmd if w != "P"] == [w for w in cmd if not w.endswith(".png")]
    seen = []
    monkeypatch.setattr(movie, "_stream_and_tee", lambda c, log: seen.append((c, log)) or 0)
    monkeypatch.setattr(movie, "_wait_for_avail", lambda gib, timeout: True)
    monkeypatch.setattr(movie, "_report_summary", lambda a, m, d: 0)
    assert movie.phase4_render(fargs) == 0
    story_dir = os.path.join(tmp, "stories", "s1")
    assert seen == [([sys.executable, os.path.join(WS, "bin", "ltx-mlx-render"),
                      os.path.join(story_dir, "manifest.json"), os.path.join(story_dir, "movie.mp4")] + movie._phase4_flags(fargs),
                     os.path.join(story_dir, "movie.log"))]



# --- CXT13 (CX15-CX18): still, clip, frame, in that order; the frame is the next panel's context picture ----------

def test_cxt13_the_interleaved_order(frame_env, capsys):
    tmp, fake, events = frame_env["tmp"], frame_env["fake"], frame_env["events"]
    story_dir = _story(tmp)
    args = _frame_args(tmp)
    assert movie.phase_seed_context_frames(args) == 0
    f1, f3 = _work(tmp, "frame_01.png"), _work(tmp, "frame_03.png")
    avail = ("avail", 25.0, 1800)
    assert events == [("manifest", 4),
                      ("edit", 1, [SEED]), avail, ("render", 1), ("frame", 1, 145), ("check", 1, (704, 448)),
                      ("edit", 2, [SEED, _colour(_clip(tmp, 1))]), avail, ("render", 2),
                      ("edit", 3, [SEED]), avail, ("render", 3), ("frame", 3, 145), ("check", 3, (704, 448)),
                      ("edit", 4, [SEED, _colour(_clip(tmp, 3))]), avail, ("render", 4)]
    original = os.path.join(story_dir, "seed-original.png")
    assert [c["jobs"][0].get("sources") for c in fake.calls["run_jobs"]] == [None, [original, f1], None, [original, f3]]
    placeholder = _work(tmp, "placeholder.png")
    with Image.open(placeholder) as img:
        assert (img.size, _pixel(placeholder)) == ((1408, 896), SEED)
    (build, build_log), renders = frame_env["cmds"][0], frame_env["cmds"][1:]
    assert build_log == _work(tmp, "manifest.log")
    assert build[build.index("--shots") + 1:build.index("--fps")] == ["--image", placeholder] * 4
    upto_json, upto_mp4 = _work(tmp, "manifest_upto.json"), _work(tmp, "upto.mp4")
    assert [(c, log) for c, log in renders] == [
        ([sys.executable, os.path.join(WS, "bin", "ltx-mlx-render"), upto_json, upto_mp4]
         + movie._phase4_flags(args), _work(tmp, "render-%02d.log" % k)) for k in (1, 2, 3, 4)]
    with open(os.path.join(story_dir, "manifest.json"), encoding="utf-8") as f:
        built = json.load(f)["panels"]
    for k, upto in enumerate(frame_env["uptos"], start=1):
        assert upto["panels"] == [dict(p, image_path=os.path.join(story_dir, "images", "panel_%02d.png" % p["index"]))
                                  for p in built[:k]]
    assert frame_env["rendered"] == [1, 2, 3, 4] and not os.path.exists(upto_mp4)
    entries = _record(story_dir)["panels"]
    assert [e["context"] for e in entries] == [
        {"kind": "none", "file": None, "sha256": None, "picture": None},
        {"kind": "frame", "file": "seed_context_edits/frame_01.png", "sha256": _sha(f1), "picture": 2},
        {"kind": "none", "file": None, "sha256": None, "picture": None},
        {"kind": "frame", "file": "seed_context_edits/frame_03.png", "sha256": _sha(f3), "picture": 2}]
    assert not os.path.exists(_work(tmp, "frame_02.png")) and not os.path.exists(_work(tmp, "frame_04.png"))
    out = capsys.readouterr().out.splitlines()
    assert out[:3] == ["=== Phase 2: stills and clips, panel by panel (seed context frame) ===",
                       "seed context: location changes at panels 3 (the Image: setting sentence differs from the "
                       "previous panel's): each of them is a single-image edit of the seed, like panel 1",
                       "seed context: %s; 704x448, fitted into 1408x896 stills; seed 3; 4 panels in order, one Qwen "
                       "child per edited panel; the seed is Picture 1 and the last frame of the previous panel's clip "
                       "is Picture 2" % qwen_edit.generator_text("qwen21-q4", UNC_LIST)]
    assert ("seed context: the manifest, built once with %s as every panel's still until it is made; log: %s"
            % (placeholder, _work(tmp, "manifest.log"))) in out
    assert ("seed context: panel 2: Picture 1 is the seed (%s), Picture 2 is the last frame of panel 1's clip (%s)"
            % (original, f1)) in out
    assert "seed context: panel 1: its clip (bin/ltx-mlx-render --resume on panels 1-1); log: %s" % _work(
        tmp, "render-01.log") in out
    assert "seed context: panel 2: the last frame of %s -> %s" % (_clip(tmp, 1), f1) in out
    assert out[-1] == "seed context: 4 panel stills written, 0 reused; every clip is made, so Phase 4 reuses them all"


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# --- CXT14 (CX19): the guards before any edit: an existing movie, a failed manifest build, no render tool ---------

def test_cxt14_the_guards_before_any_edit(frame_env, monkeypatch, capsys):
    tmp, fake, events = frame_env["tmp"], frame_env["fake"], frame_env["events"]
    story_dir = _story(tmp)
    args = _frame_args(tmp)
    with open(os.path.join(story_dir, "movie.mp4"), "wb") as f:
        f.write(b"old")
    assert movie.phase_seed_context_frames(args) == 2
    assert capsys.readouterr().err == ("Error: %s already exists; pass --force to overwrite\n"
                                       % os.path.join(story_dir, "movie.mp4"))
    assert events == [] and frame_env["cmds"] == []
    os.remove(os.path.join(story_dir, "movie.mp4"))
    frame_env["manifest_rc"][0] = 1
    assert movie.phase_seed_context_frames(args) == 1
    assert capsys.readouterr().err == "Error: ltx-story-manifest exited 1; see %s\n" % _work(tmp, "manifest.log")
    assert fake.calls["run_jobs"] == []
    frame_env["manifest_rc"][0] = 0
    monkeypatch.setattr(movie, "_ltx_render", lambda: (_ for _ in ()).throw(SyntaxError("bad line")))
    assert movie.phase_seed_context_frames(args) == 1
    assert capsys.readouterr().err == ("Error: cannot load %s: SyntaxError: bad line\n"
                                       % os.path.join(WS, "bin", "ltx-mlx-render"))
    assert fake.calls["run_jobs"] == []


# --- CXT15 (CX18, CX19): a blocked still, a failed clip, a bad frame or memory stop the run; the review gate ----

def test_cxt15_still_clip_and_frame_failures(frame_env, monkeypatch, capsys):
    tmp, fake, events = frame_env["tmp"], frame_env["fake"], frame_env["events"]
    story_dir = _story(tmp)
    args = _frame_args(tmp)
    fake.outcomes = {2: "blocked"}
    assert movie.phase_seed_context_frames(args) == 1
    assert "Error: the content screen blocked the seed-context Qwen edit (Qwen-Image-2.1 q4) of panel 2 " in (
        capsys.readouterr().err)
    assert events[-1][:2] == ("edit", 2) and ("render", 2) not in events
    fake.reset()
    del events[:]
    frame_env["rc"][2] = 1
    assert movie.phase_seed_context_frames(args) == 1
    assert capsys.readouterr().err == (
        "Error: ltx-mlx-render exited 1 on panels 1-2, so panel 2's clip is not made; frame mode stops here (see %s); "
        "a rerun reuses every recorded still and finished clip\n" % _work(tmp, "render-02.log"))
    assert events[-1] == ("render", 2) and _edited(fake)[-1] == 2
    frame_env["rc"].clear()
    del events[:]
    frame_env["violations"][1] = ["chain frame %s is degenerate" % _work(tmp, "frame_01.png")]
    assert movie.phase_seed_context_frames(args) == 1
    assert capsys.readouterr().err == ("Error: panel 2's context frame (the last frame of %s): chain frame %s is "
                                       "degenerate\n" % (_clip(tmp, 1), _work(tmp, "frame_01.png")))
    assert events[-1] == ("check", 1, (704, 448))
    frame_env["violations"].clear()
    frame_env["frame_error"][0] = RuntimeError("ffmpeg vanished")
    del events[:]
    assert movie.phase_seed_context_frames(args) == 1
    assert capsys.readouterr().err == ("Error: panel 2's context frame (the last frame of %s): RuntimeError: ffmpeg "
                                       "vanished\n" % _clip(tmp, 1))
    frame_env["frame_error"][0] = None
    monkeypatch.setattr(movie, "_wait_for_avail", lambda gib, timeout: False)
    del events[:]
    assert movie.phase_seed_context_frames(args) == 1
    assert not any(e[0] == "render" for e in events)
    monkeypatch.setattr(movie, "_wait_for_avail", lambda gib, timeout: True)
    prompts = []
    monkeypatch.setattr(builtins, "input", lambda prompt: prompts.append(prompt) or "")
    del events[:]
    assert movie.phase_seed_context_frames(_frame_args(tmp, no_review=False)) == 0
    assert prompts == ["Frame mode renders every panel's clip right after its still, before the next still is "
                       "edited. Enter to start, Ctrl-C to abort: "]
    assert [e["status"] for e in _record(story_dir)["panels"]] == ["ok"] * 4


# --- CXT16 (CX16, CX18): a rerun reuses stills by record and clips by --resume; a changed clip re-edits ------------

def test_cxt16_reruns(frame_env, capsys):
    tmp, fake, events = frame_env["tmp"], frame_env["fake"], frame_env["events"]
    _story(tmp)
    assert movie.phase_seed_context_frames(_frame_args(tmp)) == 0

    def rerun(images=IMAGES, **overrides):
        """(the panels a rerun edits, the clips it renders)."""
        _story(tmp, images)
        before, rendered = len(fake.calls["run_jobs"]), len(frame_env["rendered"])
        del events[:]
        assert movie.phase_seed_context_frames(_frame_args(tmp, **overrides)) == 0
        return _edited(fake, before), frame_env["rendered"][rendered:]

    assert rerun() == ([], [])
    assert [e for e in events if e[0] in ("render", "frame")] == [("render", 1), ("frame", 1, 145), ("render", 2),
                                                                  ("render", 3), ("frame", 3, 145), ("render", 4)]
    assert capsys.readouterr().out.splitlines()[-1] == (
        "seed context: 0 panel stills written, 4 reused; every clip is made, so Phase 4 reuses them all")
    frame_env["variant"][1] = "a new motion"
    assert rerun() == ([2], [1])
    assert rerun() == ([], [])
    first = list(IMAGES)
    first[0] = IMAGES[0] + " Rain falls."
    assert rerun(first) == ([1, 2], [])
    capsys.readouterr()
    assert rerun(first, redo_panels=[3]) == ([3, 4], [])
    assert ("note: seed context: --redo 3 also re-edits panels 4: their context picture is the last frame of the "
            "previous panel's clip, so it changes with it, up to the next location change"
            in capsys.readouterr().out.splitlines())


# --- CXT17 (CX16, CX17): the real bin/ltx-mlx-render accepts the partial manifests and reuses their clips -----------

def _load_render():
    path = os.path.join(WS, "bin", "ltx-mlx-render")
    loader = importlib.machinery.SourceFileLoader("ltx_mlx_render_sctx", path)
    spec = importlib.util.spec_from_loader("ltx_mlx_render_sctx", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_cxt17_the_real_render_tool(ctx_env, monkeypatch, capsys):
    tmp, fake = ctx_env["tmp"], ctx_env["fake"]
    render = _load_render()
    model = os.path.join(tmp, "model-fixture")
    os.makedirs(model)
    with open(os.path.join(model, "split_model.json"), "w") as f:
        json.dump({"recipe": "ltx-2.5"}, f)
    fake_bin = os.path.join(tmp, "fake-ltx")
    with open(fake_bin, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(fake_bin, 0o755)
    generated, screened, frames = [], [], []

    def generate_video(prompt, output_path, image_path=None, **kw):
        generated.append((int(os.path.basename(output_path)[6:8]), kw["seed"], _pixel(image_path)))
        with open(output_path, "wb") as f:
            f.write(b"clip " + prompt.encode())
        return os.path.abspath(output_path)

    def extract_last_frame(clip, out_png, n_frames):
        frames.append((os.path.basename(clip), n_frames))
        Image.new("RGB", (704, 448), (90, 90, 90)).save(out_png)
        return []

    monkeypatch.setattr(render.SKILL, "generate_video", generate_video)
    monkeypatch.setattr(render.SKILL, "LTX2_MLX_BIN", fake_bin)
    monkeypatch.setattr(render, "shutil", types.SimpleNamespace(which=lambda tool: "/usr/bin/" + tool))
    monkeypatch.setattr(render, "probe_streams", lambda p: {"streams": []})
    monkeypatch.setattr(render, "assert_clips_uniform", lambda pairs, w, h, fr: None)
    monkeypatch.setattr(render, "build_concat_command", lambda lp, out: [
        sys.executable, "-c", "import sys; open(sys.argv[1], 'wb').write(b'MOVIE')", out])
    monkeypatch.setattr(render, "clip_frame_count", lambda p: 145)
    monkeypatch.setattr(render, "ffprobe_image_size", lambda p: ((1408, 896), None))
    monkeypatch.setattr(render, "run_input_content_screen", lambda paths: screened.append(len(paths)) or 0)
    monkeypatch.setattr(render, "story_dir_for", lambda story_id: os.path.join(tmp, "stories", story_id))
    monkeypatch.setattr(render, "extract_last_frame", extract_last_frame)
    monkeypatch.setattr(render, "check_chain_seed", lambda png, w, h, source: [])
    story_dir = os.path.join(tmp, "stories", "s1")

    def stream(cmd, log_path):
        if os.path.basename(cmd[1]) == "ltx-story-manifest":
            images = [cmd[i + 1] for i, word in enumerate(cmd) if word == "--image"]
            panels = [{"index": i, "image_path": image, "conditioning": "still", "panel_text": "panel %d" % i,
                       "motion_prompt": "motion %d" % i, "num_frames": 145} for i, image in enumerate(images, 1)]
            with open(os.path.join(story_dir, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump({"schema_version": 3, "story_id": "s1", "fps": 24, "panels": panels}, f)
            return 0
        assert cmd[:2] == [sys.executable, os.path.join(WS, "bin", "ltx-mlx-render")]
        return render.main(cmd[2:])

    monkeypatch.setattr(movie, "_stream_and_tee", stream)
    monkeypatch.setattr(movie, "_ltx_render", lambda: render)
    monkeypatch.setattr(movie, "_wait_for_avail", lambda gib, timeout: True)
    _story(tmp, IMAGES[:2] + [HARBOUR + " She sits on a bollard; medium shot, eye level."])
    args = _frame_args(tmp, panels=3, model=model)
    assert movie.phase_seed_context_frames(args) == 0
    assert generated == [(1, 1, (0, 0, 40)), (2, 2, (0, 0, 80)), (3, 3, (0, 0, 120))]
    assert frames == [("panel_01.mp4", 145), ("panel_02.mp4", 145)]
    assert screened == [1, 2, 3]
    summaries = []
    for path in sorted(glob.glob(os.path.join(story_dir, "runs", "*", "story_summary.json")),
                       key=lambda p: os.path.getmtime(p)):
        with open(path, encoding="utf-8") as f:
            summaries.append(json.load(f))
    assert [(s["requested_units"], s["completed_units"], s["intended_total_frames"], s["actual_total_frames"],
             [u["resumed"] for u in s["units"]], s["on_panel_failure"], s["stopped_reason"]) for s in summaries] == [
        (1, 1, 145, 145, [False], "skip", None), (2, 2, 290, 290, [True, False], "skip", None),
        (3, 3, 435, 435, [True, True, False], "skip", None)]
    assert [e["context"]["kind"] for e in _record(story_dir)["panels"]] == ["none", "frame", "frame"]
    final = _work(tmp, "manifest_upto.json")
    assert render.main([final, os.path.join(story_dir, "movie.mp4")] + movie._phase4_flags(args)) == 0
    assert len(generated) == 3
    del generated[:]
    capsys.readouterr()
    assert movie.phase_seed_context_frames(args) == 2
    assert movie.phase_seed_context_frames(_frame_args(tmp, panels=3, model=model, force=True)) == 0
    assert generated == [] and _edited(fake)[3:] == []
    with open(os.path.join(story_dir, "clips", "panel_02.mp4.provenance.json"), encoding="utf-8") as f:
        assert json.load(f)["image_sha256"] == _sha(os.path.join(story_dir, "images", "panel_02.png"))


# --- CXT20 (CX17): a transient clip failure is retried once by the real bin/ltx-mlx-render --------------------------

def test_cxt20_a_failed_clip_is_retried_once(ctx_env, monkeypatch, capsys):
    tmp = ctx_env["tmp"]
    render = _load_render()
    model = os.path.join(tmp, "model-fixture")
    os.makedirs(model)
    with open(os.path.join(model, "split_model.json"), "w") as f:
        json.dump({"recipe": "ltx-2.5"}, f)
    fake_bin = os.path.join(tmp, "fake-ltx")
    with open(fake_bin, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(fake_bin, 0o755)
    calls = []

    def generate_video(prompt, output_path, image_path=None, **kw):
        calls.append(output_path)
        if len(calls) == 1:
            raise render.SKILL.Ltx2MlxError("transient failure", returncode=1)
        with open(output_path, "wb") as f:
            f.write(b"clip " + prompt.encode())
        return os.path.abspath(output_path)

    monkeypatch.setattr(render.SKILL, "generate_video", generate_video)
    monkeypatch.setattr(render.SKILL, "LTX2_MLX_BIN", fake_bin)
    monkeypatch.setattr(render, "shutil", types.SimpleNamespace(which=lambda tool: "/usr/bin/" + tool))
    monkeypatch.setattr(render, "probe_streams", lambda p: {"streams": []})
    monkeypatch.setattr(render, "assert_clips_uniform", lambda pairs, w, h, fr: None)
    monkeypatch.setattr(render, "build_concat_command", lambda lp, out: [
        sys.executable, "-c", "import sys; open(sys.argv[1], 'wb').write(b'MOVIE')", out])
    monkeypatch.setattr(render, "clip_frame_count", lambda p: 145)
    monkeypatch.setattr(render, "ffprobe_image_size", lambda p: ((1408, 896), None))
    monkeypatch.setattr(render, "run_input_content_screen", lambda paths: 0)
    monkeypatch.setattr(render, "story_dir_for", lambda story_id: os.path.join(tmp, "stories", story_id))
    monkeypatch.setattr(render, "extract_last_frame", lambda clip, out_png, n: [])
    monkeypatch.setattr(render, "check_chain_seed", lambda png, w, h, source: [])
    story_dir = os.path.join(tmp, "stories", "s1")

    def stream(cmd, log_path):
        if os.path.basename(cmd[1]) == "ltx-story-manifest":
            images = [cmd[i + 1] for i, word in enumerate(cmd) if word == "--image"]
            panels = [{"index": i, "image_path": image, "conditioning": "still", "panel_text": "panel %d" % i,
                       "motion_prompt": "motion %d" % i, "num_frames": 145} for i, image in enumerate(images, 1)]
            with open(os.path.join(story_dir, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump({"schema_version": 3, "story_id": "s1", "fps": 24, "panels": panels}, f)
            return 0
        argv = list(cmd[2:])
        argv[argv.index("--retry-idle") + 1] = "0"
        return render.main(argv)

    monkeypatch.setattr(movie, "_stream_and_tee", stream)
    monkeypatch.setattr(movie, "_ltx_render", lambda: render)
    monkeypatch.setattr(movie, "_wait_for_avail", lambda gib, timeout: True)
    _story(tmp, IMAGES[:1])
    args = _frame_args(tmp, panels=1, model=model)
    assert movie.phase_seed_context_frames(args) == 0
    assert len(calls) == 2
    paths = glob.glob(os.path.join(story_dir, "runs", "*", "story_summary.json"))
    assert len(paths) == 1
    with open(paths[0], encoding="utf-8") as f:
        summary = json.load(f)
    assert (summary["completed_units"], summary["on_panel_failure"], summary["stopped_reason"]) == (1, "skip", None)
    unit = summary["units"][0]
    assert (unit["status"], unit["attempts"], unit["first_failure"]) == ("ok", 2, "error")


# --- CXT18 (CX20): the frame mode's dry run ----------------------------------------------------------------------

def test_cxt18_the_dry_run(frame_env, capsys):
    tmp = frame_env["tmp"]
    from test_ltx_movie_shots_seed import _seed1920
    seed = _seed1920(tmp)
    story_dir = os.path.join(tmp, "stories", "s1")
    base = ["a narrative", "--story-id", "s1", "--dry-run", "--no-review", "--no-auto-lora", "--shots",
            "--seed-image", seed, "--seed-edit-model", "qwen21-q4", "--seed-context"]

    def dry(mode):
        assert movie.main(base + [mode]) == 0
        return capsys.readouterr().out.splitlines()

    still, frame = dry("still"), dry("frame")
    i = frame.index("--- Phase 2: stills ---")
    work = os.path.join(story_dir, "seed_context_edits")
    assert frame[i + 1] == still[i + 1].replace("the previous panel's still", "the last frame of the previous "
                                                                          "panel's clip")
    assert frame[i + 2] == (
        "Frame mode: Phase 2 also renders each panel's clip right after its still, with bin/ltx-mlx-render --resume "
        "on a manifest of the panels so far (%s; Phase 4's flags: skip plus one retry; logs %s), and the exact last frame "
        "of clip k is panel k+1's context picture. A clip still failing after the retry stops the run. Phases 3 and 4 then build the final manifest "
        "and reuse every clip." % (os.path.join(work, "manifest_upto.json"), os.path.join(work, "render-NN.log")))
    assert frame[i + 3] == "Panels: decided at Phase 2, from story.md after Phase 1"
    assert frame[i + 4:] == still[i + 3:]
    _story(tmp)
    lines = dry("frame")
    assert lines[i + 3:i + 5] == [
        "Location changes (single-image edits): 3",
        "Panels to edit: decided panel by panel during the run: a context picture is the last frame of a clip this "
        "run renders or reuses"]
    assert frame_env["fake"].calls["run_jobs"] == [] and frame_env["cmds"] == []
    assert not os.path.exists(work)


# --- CXT19 (CX14): the help text and the docstring ---------------------------------------------------------------

HELP = ("a test option for --shots with --seed-image: every panel after the first is a two-image Qwen edit of the "
        "seed (the people) and the previous panel's still (the scene), one Qwen child per panel in panel order, "
        "recorded in seed_context_edits.json; panel 1 and every panel whose Image: setting sentence differs from the "
        "previous panel's stay single-image edits of the seed. frame uses the exact last frame of the previous panel's "
        "clip instead, rendering each clip right after its still; a failed still or clip stops the run. Needs a "
        "--seed-edit-model that edits with several pictures (qwen2511-q4 is refused). See docs/superpowers/specs/"
        "2026-11-10-seeded-shots-context-design.md.")
DOC = ("stay single-image edits of the seed. --seed-context frame uses the exact last frame of the previous panel's "
       "clip instead: Phase 2 then renders each clip right after its still (bin/ltx-mlx-render --resume on the panels "
       "so far), and Phases 3 and 4 reuse every clip. Absent, Phase 2 is unchanged. Cast references")


def test_cxt19_the_help_text_and_the_docstring():
    actions = dict((a.option_strings[0], a) for a in movie.build_parser()._actions if a.option_strings)
    assert actions["--seed-context"].help == HELP
    assert actions["--seed-context"].choices == ["still", "frame"]
    assert DOC in " ".join(movie.__doc__.split())
