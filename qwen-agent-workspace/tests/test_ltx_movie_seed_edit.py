"""Tests for bin/ltx-movie's seed edit (docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md,
Section 7, test table 11.2: QET26-QET32): --seed-edit-model and --seed-edit-lora, their rules, Phase 1c,
seed_edit.json, the Phase 2 seed and the dry run.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_ltx_movie_seed_edit.py

Rules (spec 11.1): bin/ltx-movie is loaded with SourceFileLoader, spec_from_loader, module_from_spec and
exec_module as ltx_movie_qe. Every test patches _story_dir to <tmp>/stories/<id>, HOME to <tmp>/home and
_qwen_edit to a fake module (the qe_fake fixture): the real qwen_edit's MODEL_IDS, cli_selection,
SelectionError, Unavailable, settings, label, multiple, memory_floor and generator_text, and recorders for
selection_problem, wait_for_memory and run_jobs. Nothing loads a model, renders, contacts a server or
touches port 8177 or 8178; the only processes are none (Phase 2's subprocess.run is a recorder). Stdlib,
PIL and pytest.
"""

import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import re
import types

import pytest
from PIL import Image

import movie_ui_testutil as mt
import qwen_edit

WS = mt.WS
UNC = [{"id": "uncensored", "scale": 1.0}]
IMAGE = "A ronin in a grey kimono stands at a red temple gate at dusk, wide shot."
STYLE = "Muted film colour with soft grain."
PROMPT = IMAGE + " " + STYLE
STORY_MD = ("# The gate\n\nA ronin returns to his temple at dusk.\n\n"
            "## Panel 1 — The gate\nImage: %s\nStyle: %s\nMotion: The ronin bows. The camera stays static.\n"
            "Narration: He has come home.\n\n"
            "## Panel 2 — The road\nMotion: The ronin walks down the road. The camera follows him.\n"
            "Narration: The road behind him is long.\n" % (IMAGE, STYLE))


def _load_movie():
    path = os.path.join(WS, "bin", "ltx-movie")
    loader = importlib.machinery.SourceFileLoader("ltx_movie_qe", path)
    spec = importlib.util.spec_from_loader("ltx_movie_qe", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


movie = _load_movie()


class _FakeQwenEdit(object):
    """QET26's fake qwen_edit: the real pure parts, and recorders for the three calls that would touch the
    host. result is "ok" (run_jobs writes the output and reports 12.5 s), "blocked", a failure text, or an
    exception to raise."""
    MODEL_IDS = qwen_edit.MODEL_IDS
    SelectionError = qwen_edit.SelectionError
    Unavailable = qwen_edit.Unavailable

    def __init__(self):
        self.calls = {"selection_problem": [], "wait_for_memory": [], "run_jobs": []}
        self.problem = None
        self.result = "ok"
        for name in ("cli_selection", "settings", "label", "multiple", "memory_floor", "generator_text"):
            setattr(self, name, getattr(qwen_edit, name))

    def selection_problem(self, model_id, loras):
        self.calls["selection_problem"].append((model_id, loras))
        return self.problem

    def wait_for_memory(self, floor, label, tag="seed-edit"):
        self.calls["wait_for_memory"].append((floor, label, tag))

    def run_jobs(self, model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None,
                 noun="job"):
        self.calls["run_jobs"].append({"model_id": model_id, "loras": loras, "jobs": jobs, "size": (width, height),
                                       "skill": skill, "work_dir": work_dir})
        job = jobs[0]
        if isinstance(self.result, Exception):
            raise self.result
        if self.result == "ok":
            Image.new("RGB", (width, height), (0, 0, 200)).save(job["output_path"])
            return [{"n": 1, "output_path": job["output_path"], "status": "ok", "seconds": 12.5}], None
        if self.result == "blocked":
            return [{"n": 1, "output_path": job["output_path"], "status": "blocked", "seconds": 12.5}], None
        return [{"n": 1, "output_path": job["output_path"], "status": "failed", "seconds": None}], self.result


@pytest.fixture
def qe_fake(monkeypatch, tmp_path):
    fake = _FakeQwenEdit()
    monkeypatch.setattr(movie, "_qwen_edit", lambda: fake)
    monkeypatch.setattr(movie, "_story_dir", lambda story_id: os.path.join(str(tmp_path), "stories", story_id))
    monkeypatch.setenv("HOME", os.path.join(str(tmp_path), "home"))
    for key in list(os.environ):
        if key.startswith("SEED_EDIT_"):
            monkeypatch.delenv(key)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", os.path.join(str(tmp_path), "hf"))
    monkeypatch.setenv("Z_IMAGE_HF_HOME", os.path.join(str(tmp_path), "zi"))
    return fake


def _args(*extra):
    return movie.build_parser().parse_args(["a narrative", "--story-id", "s1"] + list(extra))


class _PhaseArgs(object):
    def __init__(self, no_stills=False, story_server_stop_after_story=False, seed_image=None, story_only=False,
                 seed_edit=None):
        self.no_stills, self.story_server_stop_after_story = no_stills, story_server_stop_after_story
        self.seed_image, self.story_only, self.seed_edit = seed_image, story_only, seed_edit
        self.min_avail_gib, self.avail_timeout = 25.0, 1800


def _names(args):
    return tuple(p.__name__ for p in movie._phase_sequence(args))


def _seed_jpeg(path, color=(0, 200, 0)):
    """A 200x100 JPEG whose EXIF orientation 6 makes it 100x200 when oriented."""
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (200, 100), color).save(path, "JPEG", exif=exif.tobytes())
    return path


def _edit_args(tmp_path, model="qwen21-q4", loras=None, width=704, height=448, image_seed=3, story_id="s1"):
    seed = os.path.join(str(tmp_path), "seed.jpg")
    if not os.path.isfile(seed):
        _seed_jpeg(seed)
    return argparse.Namespace(story_id=story_id, seed_image=seed, video_width=width, video_height=height,
                              image_seed=image_seed,
                              seed_edit={"qwen_model": model, "loras": UNC if loras is None else loras})


def _write_story(tmp_path, story_id="s1", text=STORY_MD):
    story_dir = os.path.join(str(tmp_path), "stories", story_id)
    os.makedirs(story_dir, exist_ok=True)
    with open(os.path.join(story_dir, "story.md"), "w", encoding="utf-8") as f:
        f.write(text)
    return story_dir


def _files(story_dir):
    return {"original": os.path.join(story_dir, "seed-original.png"),
            "edited": os.path.join(story_dir, "seed-edited.png"),
            "record": os.path.join(story_dir, "seed_edit.json"),
            "work": os.path.join(story_dir, "seed_edit_work"),
            "stage": os.path.join(story_dir, "seed_edit_work", "seed-edited.pending.png")}


L41 = [(dict(), ("phase1_story", "phase2_stills", "phase3_manifest", "phase4_render")),
       (dict(story_server_stop_after_story=True),
        ("phase1_story", "phase_release_story_server", "phase2_stills", "phase3_manifest", "phase4_render")),
       (dict(no_stills=True), ("phase1_story", "phase3_manifest", "phase4_render")),
       (dict(no_stills=True, story_server_stop_after_story=True),
        ("phase1_story", "phase_release_story_server", "phase3_manifest", "phase4_render")),
       (dict(seed_image="x.png"), ("phase0_seed", "phase1_story", "phase2_stills", "phase3_manifest", "phase4_render")),
       (dict(story_server_stop_after_story=True, seed_image="x.png"),
        ("phase0_seed", "phase1_story", "phase_release_story_server", "phase2_stills", "phase3_manifest",
         "phase4_render")),
       (dict(no_stills=True, seed_image="x.png"), ("phase0_seed", "phase1_story", "phase3_manifest", "phase4_render")),
       (dict(no_stills=True, story_server_stop_after_story=True, seed_image="x.png"),
        ("phase0_seed", "phase1_story", "phase_release_story_server", "phase3_manifest", "phase4_render"))]


# --- QET26 (QE40-QE44, QEK4): the options, their rules and the unchanged phase tuples ----------------------

def test_qet26_the_options_and_their_rules(qe_fake, capsys):
    args = _args("--seed-image", "x.png", "--seed-edit-model", "qwen21-q4", "--seed-edit-lora", "uncensored=1",
                 "--seed-edit-lora", "viggle-turbo=0.5")
    assert (args.seed_edit_model, args.seed_edit_loras) == ("qwen21-q4", ["uncensored=1", "viggle-turbo=0.5"])
    assert (_args().seed_edit_model, _args().seed_edit_loras) == (None, None)
    rules = [(("--seed-edit-lora", "uncensored=1"), "--seed-edit-lora needs --seed-edit-model"),
             (("--seed-edit-model", "qwen21-q4"), "--seed-edit-model needs --seed-image"),
             (("--seed-image", "x.png", "--seed-edit-model", "as-is", "--seed-edit-lora", "uncensored=1"),
              "--seed-edit-lora cannot be combined with --seed-edit-model as-is"),
             (("--seed-image", "x.png", "--seed-edit-model", "flux"),
              "--seed-edit-model must be as-is or one of qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-q4, "
              "qwen2511-bf16"),
             (("--seed-image", "x.png", "--seed-edit-model", "qwen2511-q4", "--seed-edit-lora", "uncensored=1"),
              "--seed-edit-lora uncensored is for Qwen-Image-2.1, not Qwen-Image-Edit-2511 q4 (Lightning)"),
             (("--seed-image", "x.png", "--seed-edit-model", "qwen21-q4", "--seed-edit-lora", "uncensored"),
              "--seed-edit-lora must be ID=SCALE (got uncensored)")]
    for extra, text in rules:
        args = _args(*extra)
        assert movie._resolve_seed_edit(args) == 2, extra
        assert capsys.readouterr().err == "Error: %s\n" % text, extra
    for extra in ((), ("--seed-image", "x.png"), ("--seed-image", "x.png", "--seed-edit-model", "as-is")):
        args = _args(*extra)
        assert movie._resolve_seed_edit(args) == 0 and args.seed_edit is None, extra
    assert qe_fake.calls["selection_problem"] == []
    args = _args("--seed-image", "x.png", "--seed-edit-model", "qwen21-q8", "--seed-edit-lora", "uncensored=0.5")
    assert movie._resolve_seed_edit(args) == 0
    assert args.seed_edit == {"qwen_model": "qwen21-q8", "loras": [{"id": "uncensored", "scale": 0.5}]}
    assert qe_fake.calls["selection_problem"] == [("qwen21-q8", [{"id": "uncensored", "scale": 0.5}])]
    qe_fake.problem = "Qwen-Image-2.1 q8 is unavailable: not here (run bin/seed-edit-setup --model qwen21-q8)"
    assert movie._resolve_seed_edit(args) == 2 and args.seed_edit is None
    assert capsys.readouterr().err == ("Error: --seed-edit-model qwen21-q8: Qwen-Image-2.1 q8 is unavailable: not "
                                       "here (run bin/seed-edit-setup --model qwen21-q8)\n")
    for flag in ("--dry-run", "--story-only"):
        args = _args("--seed-image", "x.png", "--seed-edit-model", "qwen21-q8", flag)
        assert movie._resolve_seed_edit(args) == 0 and args.seed_edit["qwen_model"] == "qwen21-q8", flag
    assert len(qe_fake.calls["selection_problem"]) == 2
    for kwargs, names in L41:
        assert _names(_PhaseArgs(**kwargs)) == names, kwargs


# --- QET27 (QE44): Phase 1c sits after the story (and its release) and before the stills -------------------

def test_qet27_the_phase_sequence_with_a_seed_edit():
    edit = {"qwen_model": "qwen21-q4", "loras": UNC}
    assert _names(_PhaseArgs(seed_image="x.png", story_server_stop_after_story=True, seed_edit=edit)) == (
        "phase0_seed", "phase1_story", "phase_release_story_server", "phase_seed_edit", "phase2_stills",
        "phase3_manifest", "phase4_render")
    assert _names(_PhaseArgs(seed_image="x.png", seed_edit=edit)) == (
        "phase0_seed", "phase1_story", "phase_seed_edit", "phase2_stills", "phase3_manifest", "phase4_render")
    assert _names(_PhaseArgs(seed_image="x.png", story_only=True, seed_edit=edit)) == ("phase0_seed", "phase1_story")


# --- QET28 (QE45-QE49): Phase 1c edits the seed into panel 1, and Phase 2 takes the edited image ------------

def test_qet28_phase_1c_edits_the_seed_into_panel_1(qe_fake, tmp_path, monkeypatch, capsys):
    story_dir = _write_story(tmp_path)
    files = _files(story_dir)
    args = _edit_args(tmp_path)
    assert movie.phase_seed_edit(args) == 0
    (call,) = qe_fake.calls["run_jobs"]
    assert call == {"model_id": "qwen21-q4", "loras": UNC, "size": (704, 448), "skill": "ltx_movie_seed_edit",
                    "work_dir": files["work"],
                    "jobs": [{"n": 1, "seed": 3, "prompt": PROMPT, "source": files["original"],
                              "stage_path": files["stage"], "output_path": files["edited"]}]}
    assert qe_fake.calls["wait_for_memory"] == [(20.0, "Qwen-Image-2.1 q4", "ltx-movie")]
    with Image.open(files["original"]) as img:
        assert (img.format, img.size) == ("PNG", (100, 200))
    with open(files["record"], encoding="utf-8") as f:
        record = json.load(f)
    with open(args.seed_image, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    settings = qwen_edit.settings("qwen21-q4", UNC)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", record["created"])
    assert list(record) == ["schema", "created", "status", "label", "source", "source_sha256", "original", "output",
                            "prompt", "seed", "width", "height", "qwen_model", "loras", "steps", "scheduler",
                            "seconds", "error"]
    assert dict(record, created=None) == {
        "schema": "ltx-movie.seed-edit.v1", "created": None, "status": "ok", "label": "Qwen-Image-2.1 q4",
        "source": os.path.abspath(args.seed_image), "source_sha256": sha, "original": "seed-original.png",
        "output": "seed-edited.png", "prompt": PROMPT, "seed": 3, "width": 704, "height": 448,
        "qwen_model": settings["qwen_model"], "loras": settings["loras"], "steps": 40, "scheduler": "linear",
        "seconds": 12.5, "error": None}
    assert args.seed_edited_path == files["edited"]
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "=== Phase 1c: seed edit ==="
    assert out[1] == "seed edit: %s; 704x448; seed 3; prompt: panel 1's Image: text (%d characters)" % (
        qwen_edit.generator_text("qwen21-q4", UNC), len(PROMPT))
    assert out[-1] == "seed edit: %s (12.5 s)" % files["edited"]
    runs = []
    monkeypatch.setattr(movie.subprocess, "run", lambda cmd, cwd=None: runs.append(cmd) or types.SimpleNamespace(
        returncode=0))
    monkeypatch.setattr(movie, "_catalog_stills_flags", lambda a, dry_run=False: (None, []))
    phase2 = argparse.Namespace(**vars(args))
    phase2.global_stills_loras = phase2.stills_lora_path = phase2.cast_members = phase2.location_pins = None
    phase2.shots = False
    assert movie.phase2_stills(phase2) == 0
    (cmd,) = runs
    assert cmd.count("--seed-image") == 1 and cmd[cmd.index("--seed-image") + 1] == files["edited"]
    for model, loras, size in (("qwen2511-q4", [], (720, 448)), ("qwen21-q4", UNC, (704, 448))):
        qe_fake.calls["run_jobs"] = []
        edit_args = _edit_args(tmp_path, model=model, loras=loras, width=720, height=448, story_id="s-" + model)
        _write_story(tmp_path, edit_args.story_id)
        assert movie.phase_seed_edit(edit_args) == 0
        assert qe_fake.calls["run_jobs"][0]["size"] == size, model


# --- QET29 (QE48 step 9): a blocked or failed edit stops the movie before Phase 2 ---------------------------

def test_qet29_a_blocked_or_failed_edit_stops_the_movie(qe_fake, tmp_path, monkeypatch, capsys):
    story_dir = _write_story(tmp_path)
    files = _files(story_dir)
    seed = _seed_jpeg(os.path.join(str(tmp_path), "seed.jpg"))
    ran = []

    def recorder(name, rc=0):
        def phase(args):
            ran.append(name)
            if name == "phase0_seed":
                args.video_width, args.video_height = 704, 448
            return rc
        return phase

    for name in ("phase0_seed", "phase1_story", "phase_release_story_server", "phase2_stills", "phase3_manifest",
                 "phase4_render"):
        monkeypatch.setattr(movie, name, recorder(name))
    monkeypatch.setattr(movie, "_check_sudo_and_start_keepalive", lambda: None)
    qe_fake.result = "blocked"
    argv = ["a narrative", "--story-id", "s1", "--panels", "2", "--seed-image", seed, "--seed-edit-model",
            "qwen21-q4", "--no-review", "--story-legacy"]
    capsys.readouterr()
    assert movie.main(argv) == 1
    assert ran == ["phase0_seed", "phase1_story", "phase_release_story_server"]
    assert capsys.readouterr().err == (
        "Error: the content screen blocked the edited seed image (Qwen-Image-2.1 q4) for story s1; the movie stops "
        "here rather than use an unscreened or unedited panel 1. Change panel 1's Image: line in %s, or rerun with "
        "--seed-edit-model as-is to use the seed unchanged\n" % os.path.join(story_dir, "story.md"))
    with open(files["record"], encoding="utf-8") as f:
        record = json.load(f)
    assert (record["status"], record["output"], record["error"], record["seconds"]) == ("blocked", None, None, 12.5)
    assert not os.path.exists(files["edited"]) and not os.path.exists(os.path.join(story_dir, ".movie.lock"))
    args = _edit_args(tmp_path)
    qe_fake.result = "Qwen-Image-2.1 q4 child exited 1: boom"
    assert movie.phase_seed_edit(args) == 1
    assert capsys.readouterr().err == "Error: the seed edit failed: Qwen-Image-2.1 q4 child exited 1: boom\n"
    with open(files["record"], encoding="utf-8") as f:
        record = json.load(f)
    assert (record["status"], record["output"], record["error"], record["seconds"]) == (
        "failed", None, "Qwen-Image-2.1 q4 child exited 1: boom", None)
    qe_fake.result = qwen_edit.Unavailable("LoRA Uncensored (abenzerps) is unavailable: gone")
    assert movie.phase_seed_edit(args) == 1
    assert capsys.readouterr().err == ("Error: the seed edit failed: LoRA Uncensored (abenzerps) is unavailable: "
                                       "gone\n")
    assert getattr(args, "seed_edited_path", None) is None
    _write_story(tmp_path, text=STORY_MD.replace("Image: %s\nStyle: %s\n" % (IMAGE, STYLE), ""))
    assert movie.phase_seed_edit(args) == 1
    assert capsys.readouterr().err == ("Error: panel 1 of %s has no Image: description to edit the seed with\n"
                                       % os.path.join(story_dir, "story.md"))


# --- QET30 (QE48 step 4): a rerun reuses an identical edit and redoes a changed one -------------------------

def test_qet30_a_rerun_reuses_an_identical_edit(qe_fake, tmp_path, capsys):
    story_dir = _write_story(tmp_path)
    edited = _files(story_dir)["edited"]
    assert movie.phase_seed_edit(_edit_args(tmp_path)) == 0
    capsys.readouterr()
    args = _edit_args(tmp_path)
    assert movie.phase_seed_edit(args) == 0
    assert len(qe_fake.calls["run_jobs"]) == 1 and args.seed_edited_path == edited
    assert capsys.readouterr().out.splitlines()[-1] == (
        "seed edit: reusing %s (same seed image, prompt, seed and settings)" % edited)

    def runs_after(edit_args):
        before = len(qe_fake.calls["run_jobs"])
        assert movie.phase_seed_edit(edit_args) == 0
        return len(qe_fake.calls["run_jobs"]) - before

    _seed_jpeg(os.path.join(str(tmp_path), "seed.jpg"), color=(200, 0, 0))
    assert runs_after(_edit_args(tmp_path)) == 1
    _write_story(tmp_path, text=STORY_MD.replace("at dusk, wide shot", "at dawn, wide shot"))
    assert runs_after(_edit_args(tmp_path)) == 1
    assert runs_after(_edit_args(tmp_path, image_seed=4)) == 1
    assert runs_after(_edit_args(tmp_path, image_seed=4, model="qwen21-q8")) == 1
    half = [{"id": "uncensored", "scale": 0.5}]
    assert runs_after(_edit_args(tmp_path, image_seed=4, model="qwen21-q8", loras=half)) == 1
    assert runs_after(_edit_args(tmp_path, image_seed=4, model="qwen21-q8", loras=half)) == 0


# --- QET31 (QE50, QEK4): the dry run -----------------------------------------------------------------------------

def _dry(capsys, *extra):
    argv = ["a narrative", "--story-id", "s1", "--panels", "3", "--story-legacy", "--no-review", "--dry-run"]
    assert movie.main(argv + list(extra)) == 0
    return capsys.readouterr().out


def test_qet31_the_dry_run(qe_fake, tmp_path, capsys):
    seed = os.path.join(str(tmp_path), "seed1920.png")
    Image.new("RGB", (1920, 1080), (40, 50, 60)).save(seed)
    plain = _dry(capsys, "--seed-image", seed)
    assert _dry(capsys, "--seed-image", seed, "--seed-edit-model", "as-is") == plain
    edited = _dry(capsys, "--seed-image", seed, "--seed-edit-model", "qwen21-q4", "--seed-edit-lora", "uncensored=1")
    files = _files(os.path.join(str(tmp_path), "stories", "s1"))
    lines, plain_lines = edited.splitlines(), plain.splitlines()
    i = lines.index("--- Phase 1c: seed edit ---")
    assert lines[:i] == plain_lines[:i] and plain_lines[i - 1] == "" and plain_lines[i] == "--- Phase 2: stills ---"
    assert lines[i:i + 3] == [
        "--- Phase 1c: seed edit ---",
        "Would edit the seed with %s at 576x320, seed 0, prompted by panel 1's Image: text (and its Style: text) "
        "from story.md; every output is screened with content safety (skill ltx_movie_seed_edit); writes %s, %s "
        "and %s. A blocked or failed edit stops the run." % (qwen_edit.generator_text("qwen21-q4", UNC),
                                                             files["original"], files["edited"], files["record"]),
        ""]
    assert lines[i - 4] == "--- Phase 1b: release the story server ---"
    assert lines[i + 3:] == [line.replace("--seed-image " + seed, "--seed-image " + files["edited"])
                             if "ltx-story-images" in line else line for line in plain_lines[i:]]
    assert [line for line in lines if "ltx-story-images" in line][0].count("--seed-image") == 1
    assert qe_fake.calls["selection_problem"] == [] and qe_fake.calls["run_jobs"] == []


# --- QET32 (QE43 row 6): a workspace without qwen_edit.py --------------------------------------------------------

def test_qet32_a_workspace_without_qwen_edit(qe_fake, tmp_path, monkeypatch, capsys):
    seed = os.path.join(str(tmp_path), "seed1920.png")
    Image.new("RGB", (1920, 1080), (40, 50, 60)).save(seed)
    path = os.path.join(movie.WS, "qwen_edit.py")
    real_isfile = os.path.isfile
    monkeypatch.setattr(os.path, "isfile", lambda p: False if p == path else real_isfile(p))
    argv = ["a narrative", "--story-id", "s1", "--panels", "3", "--story-legacy", "--no-review", "--dry-run",
            "--seed-image", seed]
    assert movie.main(argv + ["--seed-edit-model", "qwen21-q4"]) == 2
    assert capsys.readouterr().err == "Error: --seed-edit-model needs %s, which this workspace does not have\n" % path
    assert movie.main(argv + ["--seed-edit-model", "as-is"]) == 0
