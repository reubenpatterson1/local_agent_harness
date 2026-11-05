"""Tests for bin/ltx-movie's shots mode with a seed image (docs/superpowers/specs/2026-11-05-compose-shots-seed-
edit-design.md, Sections 3 and 6.2: SET1-SET15, with the plan's Review Focus pins 1-4): every panel's still is a
Qwen edit of the original seed, made in one batch, screened, fitted, recorded in seed_edits.json and reused on a
rerun; the option rules, the story prompt, the phase tuples and the dry run.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_ltx_movie_shots_seed.py

Rules (spec 6.1): bin/ltx-movie is loaded with SourceFileLoader, spec_from_loader, module_from_spec and
exec_module as ltx_movie_sse. The clean_env fixture sets HOME, HF_HOME and Z_IMAGE_HF_HOME under tmp_path,
removes HF_HUB_CACHE and every SEED_EDIT_* variable, and patches _story_dir to <tmp>/stories/<id> and _qwen_edit
to the multi-job fake _FakeShotsQwenEdit (the real qwen_edit's pure parts, and recorders for selection_problem,
wait_for_memory and run_jobs). SET15 and Review Focus 3 use the real qwen_edit instead, with test_qwen_edit's
env fixture and the stub children of tests/test_seed_edit_tool.py. No test loads a model, renders, contacts a
server or touches port 8177 or 8178. Stdlib, PIL and pytest.
"""

import argparse
import glob
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
import test_seed_edit_tool as st
from test_qwen_edit import _bf16_cache, _mflux_ready, env  # noqa: F401

WS = mt.WS
UNC = [{"id": "uncensored", "scale": 1.0}]
PREFIX = ("Edit this photo into a new shot of the same film. Every person from the photo who appears in the new "
          "shot keeps exactly the same face, hair, skin tone, build and clothing. Change their pose and action, "
          "the place, the background, the lighting, the framing and the camera angle to match the new shot, and "
          "leave out anyone the new shot does not describe. The new shot: ")
LORA_NOTE = ("note: Z-Image stills LoRAs (character, location and catalog stills LoRAs) do not apply to Qwen "
             "edits; every panel's still is edited without them")
SETTING = "The setting is a rain-soaked stone harbour at night, wet cobbles underfoot, under amber lamplight."
WOMAN = "The woman in a red coat is a tall woman in her thirties with short black hair and a red wool coat."
IMAGES = [SETTING + " " + WOMAN + " She stands at the end of the quay facing right; medium shot, eye level.",
          SETTING + " " + WOMAN + " She runs along the quay toward the camera; wide shot, low angle.",
          SETTING + " " + WOMAN + " She looks out to sea; close-up, eye level."]
STYLE = "Muted teal and amber colour with soft film grain."
ENTRY_KEYS = ["n", "status", "created", "label", "source", "source_sha256", "original", "prompt", "seed", "width",
              "height", "still_width", "still_height", "qwen_model", "loras", "steps", "scheduler", "output",
              "still", "still_sha256", "seconds", "error"]


def _story_md(images=IMAGES, style=STYLE, dialogue=False):
    """A shots story.md: a title, a summary, a Characters section and one panel per images item (no Image: line
    for None); panel 1 has a Style: line unless style is None; dialogue adds a Dialogue: line to every panel."""
    lines = ["# The harbour", "", "A woman waits on a harbour quay for a boat that never comes.", "",
             "## Characters",
             '- "the woman in a red coat": a tall woman in her thirties with short black hair and a red wool coat.',
             ""]
    for n, image in enumerate(images, start=1):
        lines.append("## Panel %d — Shot %d" % (n, n))
        if image is not None:
            lines.append("Image: %s" % image)
        if n == 1 and style is not None:
            lines.append("Style: %s" % style)
        lines.append("Motion: The woman in a red coat turns her head. The camera stays static.")
        if dialogue:
            lines.append("Dialogue: the woman in a red coat: Where are you?")
        lines.append("Narration: She waits.")
        lines.append("")
    return "\n".join(lines)


SHOTS_STORY = _story_md()


def _load_movie():
    path = os.path.join(WS, "bin", "ltx-movie")
    loader = importlib.machinery.SourceFileLoader("ltx_movie_sse", path)
    spec = importlib.util.spec_from_loader("ltx_movie_sse", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


movie = _load_movie()


class _FakeShotsQwenEdit(object):
    """Spec 6.1's multi-job fake qwen_edit: the real pure parts, and recorders for selection_problem,
    wait_for_memory (raises wait_error when set) and run_jobs. run_jobs handles the jobs in order by
    outcomes.get(n, "ok"): "ok" writes a (width, height) PNG of colour (0, 0, 40 * n) at output_path and reports
    12.5 s, "blocked" reports a block and writes nothing, "stop" stops (this job and every later one are failed);
    after the on_result of job interrupt_after it raises KeyboardInterrupt. It returns (results in job order,
    failure)."""
    MODEL_IDS = qwen_edit.MODEL_IDS
    SelectionError = qwen_edit.SelectionError
    Unavailable = qwen_edit.Unavailable

    def __init__(self):
        self.calls = {"selection_problem": [], "wait_for_memory": [], "run_jobs": []}
        self.reset()
        for name in ("cli_selection", "settings", "label", "multiple", "memory_floor", "generator_text"):
            setattr(self, name, getattr(qwen_edit, name))

    def reset(self):
        self.outcomes, self.failure, self.interrupt_after, self.wait_error = {}, None, None, None

    def selection_problem(self, model_id, loras):
        self.calls["selection_problem"].append((model_id, loras))
        return None

    def wait_for_memory(self, floor, label, tag="seed-edit"):
        self.calls["wait_for_memory"].append((floor, label, tag))
        if self.wait_error is not None:
            raise self.wait_error

    def run_jobs(self, model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None,
                 noun="job"):
        self.calls["run_jobs"].append({"model_id": model_id, "loras": loras, "jobs": [dict(j) for j in jobs],
                                       "size": (width, height), "skill": skill, "work_dir": work_dir, "noun": noun})
        results, stopped = [], False
        for job in jobs:
            n = job["n"]
            outcome = "stop" if stopped else self.outcomes.get(n, "ok")
            if outcome == "stop":
                stopped = True
                results.append({"n": n, "output_path": job["output_path"], "status": "failed", "seconds": None})
                continue
            if outcome == "ok":
                Image.new("RGB", (width, height), (0, 0, 40 * n)).save(job["output_path"])
            result = {"n": n, "output_path": job["output_path"], "status": outcome, "seconds": 12.5}
            on_result(dict(result))
            results.append(result)
            if self.interrupt_after == n:
                raise KeyboardInterrupt()
        return results, self.failure


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """Spec 6.1: HOME, HF_HOME and Z_IMAGE_HF_HOME under tmp_path, no HF_HUB_CACHE and no SEED_EDIT_* variable;
    _story_dir is <tmp>/stories/<id> and _qwen_edit the multi-job fake. Returns {"tmp", "fake"}."""
    tmp = str(tmp_path)
    monkeypatch.setenv("HOME", os.path.join(tmp, "home"))
    for key in list(os.environ):
        if key.startswith("SEED_EDIT_"):
            monkeypatch.delenv(key)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", os.path.join(tmp, "hf"))
    monkeypatch.setenv("Z_IMAGE_HF_HOME", os.path.join(tmp, "zi"))
    fake = _FakeShotsQwenEdit()
    monkeypatch.setattr(movie, "_qwen_edit", lambda: fake)
    monkeypatch.setattr(movie, "_story_dir", lambda story_id: os.path.join(tmp, "stories", story_id))
    return {"tmp": tmp, "fake": fake}


def _seed_jpeg(path, color=(0, 200, 0)):
    """QET28's seed: a 200x100 JPEG whose EXIF orientation 6 makes it 100x200 when oriented."""
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (200, 100), color).save(path, "JPEG", exif=exif.tobytes())
    return path


def _write_story(tmp, story_id="s1", text=None):
    """<tmp>/stories/<story_id>/story.md with text (SHOTS_STORY by default); returns the story directory."""
    story_dir = os.path.join(tmp, "stories", story_id)
    os.makedirs(story_dir, exist_ok=True)
    with open(os.path.join(story_dir, "story.md"), "w", encoding="utf-8") as f:
        f.write(SHOTS_STORY if text is None else text)
    return story_dir


def _phase_args(tmp, **overrides):
    """Spec 6.1's phase args: a shots seed run of story s1 at 704x448, image seed 3, qwen21-q4 + uncensored @ 1,
    the seed <tmp>/seed.jpg (written on first use)."""
    seed = os.path.join(tmp, "seed.jpg")
    if not os.path.isfile(seed):
        _seed_jpeg(seed)
    values = dict(story_id="s1", seed_image=seed, video_width=704, video_height=448, image_seed=3,
                  seed_edit={"qwen_model": "qwen21-q4", "loras": UNC}, shots=True, redo_panels=[],
                  cast_members=[], location_pins=[], story_engine="robust", no_auto_lora=True, panels=3,
                  force_story=False, global_stills_loras=[], stills_lora_path=None)
    values.update(overrides)
    return argparse.Namespace(**values)


def _record(story_dir):
    with open(os.path.join(story_dir, "seed_edits.json"), encoding="utf-8") as f:
        return json.load(f)


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _jobs(fake):
    """The panel numbers of every run_jobs call, one list per call."""
    return [[job["n"] for job in call["jobs"]] for call in fake.calls["run_jobs"]]


def _prompt(n, images=IMAGES):
    return PREFIX + images[n - 1] + " " + STYLE


def _still(story_dir, n):
    return os.path.join(story_dir, "images", "panel_%02d.png" % n)


def _blocked_text(story_dir, panels):
    return ("Error: the content screen blocked the Qwen edit of the seed (Qwen-Image-2.1 q4) for panels %s of story "
            "s1; the movie stops here rather than use an unscreened, unedited or text-rendered still. Change those "
            "panels' Image: lines in %s, then rerun: every other panel's recorded still is reused\n"
            % (panels, os.path.join(story_dir, "story.md")))


# --- SET4 (SE8, SEK3): Phase 2 dispatches a shots seed run, and only it -------------------------------------

def test_set4_phase_2_dispatches_shots_seed_runs(clean_env, monkeypatch, capsys):
    calls = {"seed": [], "shots": [], "run": []}
    monkeypatch.setattr(movie, "_phase2_shots_seed", lambda args: calls["seed"].append(args) or 0)
    monkeypatch.setattr(movie, "_phase2_shots", lambda args, cmd: calls["shots"].append(list(cmd)) or 0)
    monkeypatch.setattr(movie.subprocess, "run",
                        lambda *a, **k: calls["run"].append(a) or types.SimpleNamespace(returncode=0))
    monkeypatch.setattr(movie, "_stream_and_tee", lambda cmd, log_path: calls["run"].append(cmd) or 0)
    args = _phase_args(clean_env["tmp"])
    assert movie.phase2_stills(args) == 0
    assert calls == {"seed": [args], "shots": [], "run": []}
    assert capsys.readouterr().out == "=== Phase 2: stills ===\n"
    plain = _phase_args(clean_env["tmp"], seed_image=None, seed_edit=None)
    assert movie.phase2_stills(plain) == 0
    assert len(calls["seed"]) == 1 and calls["run"] == [] and len(calls["shots"]) == 1
    assert "--seed-image" not in calls["shots"][0]


# --- SET5 (SE9-SE13, SE15, SE18, SEK4): every panel is a Qwen edit of the seed, in one batch ---------------

def test_set5_every_panel_is_a_qwen_edit_of_the_seed(clean_env, capsys):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    story_dir = _write_story(tmp)
    args = _phase_args(tmp)
    assert movie.SHOTS_SEED_EDIT_PREFIX == PREFIX and movie.SHOTS_SEED_LORA_NOTE == LORA_NOTE
    assert (movie.SHOTS_SEED_EDIT_SKILL, movie.SHOTS_SEED_EDITS_SCHEMA) == (
        "ltx_movie_shots_seed_edit", "ltx-movie.seed-edits.v1")
    assert movie._phase2_shots_seed(args) == 0
    work = os.path.join(story_dir, "seed_edits")
    original = os.path.join(story_dir, "seed-original.png")
    (call,) = fake.calls["run_jobs"]
    assert call == {"model_id": "qwen21-q4", "loras": UNC, "size": (704, 448), "skill": "ltx_movie_shots_seed_edit",
                    "work_dir": work, "noun": "panel",
                    "jobs": [{"n": n, "seed": 3, "prompt": _prompt(n), "source": original,
                              "stage_path": os.path.join(work, "panel_%02d.pending.png" % n),
                              "output_path": os.path.join(work, "panel_%02d.png" % n)} for n in (1, 2, 3)]}
    assert fake.calls["wait_for_memory"] == [(20.0, "Qwen-Image-2.1 q4", "ltx-movie")]
    assert fake.calls["selection_problem"] == []
    with Image.open(original) as img:
        assert (img.format, img.size) == ("PNG", (100, 200))
    record = _record(story_dir)
    assert list(record) == ["schema", "updated", "panels"] and record["schema"] == "ltx-movie.seed-edits.v1"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", record["updated"])
    settings = qwen_edit.settings("qwen21-q4", UNC)
    assert len(record["panels"]) == 3
    for n, entry in enumerate(record["panels"], start=1):
        with Image.open(_still(story_dir, n)) as img:
            assert (img.format, img.size) == ("PNG", (1408, 896))
        assert list(entry) == ENTRY_KEYS
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", entry["created"])
        assert dict(entry, created=None) == {
            "n": n, "status": "ok", "created": None, "label": "Qwen-Image-2.1 q4",
            "source": os.path.abspath(args.seed_image), "source_sha256": _sha(args.seed_image),
            "original": "seed-original.png", "prompt": _prompt(n), "seed": 3, "width": 704, "height": 448,
            "still_width": 1408, "still_height": 896, "qwen_model": settings["qwen_model"],
            "loras": settings["loras"], "steps": 40, "scheduler": "linear",
            "output": "seed_edits/panel_%02d.png" % n, "still": "images/panel_%02d.png" % n,
            "still_sha256": _sha(_still(story_dir, n)), "seconds": 12.5, "error": None}
        assert os.path.isfile(os.path.join(work, "panel_%02d.png" % n))
    assert glob.glob(os.path.join(story_dir, "images", "*.tmp")) == []
    assert not os.path.exists(os.path.join(story_dir, "seed_edit.json"))
    assert not os.path.exists(os.path.join(story_dir, "images", "images.json"))
    assert not os.path.exists(os.path.join(story_dir, "redo"))
    assert capsys.readouterr().out.splitlines() == [
        "seed edits: %s; 704x448, fitted into 1408x896 stills; seed 3; panels 1,2,3 of 3, each prompted by its own "
        "Image: text" % qwen_edit.generator_text("qwen21-q4", UNC)] + [
        "panel %d -> %s (Qwen edit of the seed, 12.5s)" % (n, _still(story_dir, n)) for n in (1, 2, 3)] + [
        "seed edits: 3 panel stills written"]


# --- SET6 (SE17, SEK5): a blocked panel fails the phase, with no still and no fallback ----------------------

def test_set6_a_blocked_panel_fails_the_phase(clean_env, capsys):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    story_dir = _write_story(tmp)
    fake.outcomes = {2: "blocked"}
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 1
    captured = capsys.readouterr()
    assert captured.err == _blocked_text(story_dir, "2")
    assert "panel 2 BLOCKED: the content screen blocked the Qwen edit of the seed" in captured.out.splitlines()
    entries = _record(story_dir)["panels"]
    assert [e["status"] for e in entries] == ["ok", "blocked", "ok"]
    assert [entries[1][k] for k in ("output", "still", "still_sha256", "seconds", "error")] == [
        None, None, None, 12.5, None]
    assert [os.path.exists(_still(story_dir, n)) for n in (1, 2, 3)] == [True, False, True]


# --- SET7 (SE16, SE17, SEK6): a failed batch keeps its finished panels, and the rerun edits the rest -------

def test_set7_a_failed_batch_keeps_the_finished_panels(clean_env, capsys):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    story_dir = _write_story(tmp)
    fake.outcomes, fake.failure = {2: "stop"}, "Qwen-Image-2.1 q4 child exited 1: boom"
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 1
    assert capsys.readouterr().err == ("Error: the seed edits failed: Qwen-Image-2.1 q4 child exited 1: boom (kept: "
                                       "1; edited on the next run: 2,3)\n")
    assert [(e["n"], e["status"], e["error"], e["seconds"]) for e in _record(story_dir)["panels"]] == [
        (1, "ok", None, 12.5), (2, "failed", "Qwen-Image-2.1 q4 child exited 1: boom", None),
        (3, "failed", "Qwen-Image-2.1 q4 child exited 1: boom", None)]
    fake.reset()
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    assert _jobs(fake) == [[1, 2, 3], [2, 3]]
    assert ("seed edits: reusing the stills of panels 1 (recorded edits of the same seed image, prompt, seed and "
            "settings)") in capsys.readouterr().out.splitlines()
    assert [e["status"] for e in _record(story_dir)["panels"]] == ["ok"] * 3


# --- SET8 (SE16, SEK6): an interrupted batch leaves ok entries only for the stills it finished -------------

def test_set8_an_interrupted_batch_records_only_finished_stills(clean_env, capsys):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    story_dir = _write_story(tmp)
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    first = _record(story_dir)["panels"]
    old_03 = _sha(_still(story_dir, 3))
    changed = [IMAGES[0], IMAGES[1] + " Rain falls harder.", IMAGES[2] + " Rain falls harder."]
    _write_story(tmp, text=_story_md(changed))
    fake.interrupt_after = 2
    with pytest.raises(KeyboardInterrupt):
        movie._phase2_shots_seed(_phase_args(tmp))
    entries = _record(story_dir)["panels"]
    assert [(e["n"], e["status"]) for e in entries] == [(1, "ok"), (2, "ok")]
    assert entries[0] == first[0] and entries[1]["prompt"] == _prompt(2, changed)
    moved = glob.glob(os.path.join(story_dir, "redo", "*", "images", "panel_03.png"))
    assert len(moved) == 1 and _sha(moved[0]) == old_03
    assert not os.path.exists(_still(story_dir, 3))
    fake.reset()
    capsys.readouterr()
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    assert _jobs(fake) == [[1, 2, 3], [2, 3], [3]]


# --- SET9 (SE13, SEK4): a rerun edits exactly the panels whose key changed ----------------------------------

def test_set9_a_rerun_edits_exactly_the_changed_panels(clean_env, capsys):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    story_dir = _write_story(tmp)
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    capsys.readouterr()
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    assert len(fake.calls["run_jobs"]) == 1 and len(fake.calls["wait_for_memory"]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "seed edits: reusing the stills of panels 1,2,3 (recorded edits of the same seed image, prompt, seed and "
        "settings)",
        "seed edits: every panel's still is a recorded edit of the same seed image, prompt, seed and settings; "
        "nothing to edit"]

    def edits_after(story_id, **overrides):
        """The panels a rerun of a fresh all-ok copy of the story edits after overrides."""
        _write_story(tmp, story_id)
        assert movie._phase2_shots_seed(_phase_args(tmp, story_id=story_id)) == 0
        before = len(fake.calls["run_jobs"])
        assert movie._phase2_shots_seed(_phase_args(tmp, story_id=story_id, **overrides)) == 0
        return [job["n"] for call in fake.calls["run_jobs"][before:] for job in call["jobs"]]

    other = _seed_jpeg(os.path.join(tmp, "seed-red.jpg"), color=(200, 0, 0))
    assert edits_after("s-seed", seed_image=other) == [1, 2, 3]
    assert edits_after("s-image-seed", image_seed=4) == [1, 2, 3]
    assert edits_after("s-q8", seed_edit={"qwen_model": "qwen21-q8", "loras": UNC}) == [1, 2, 3]
    assert edits_after("s-scale", seed_edit={"qwen_model": "qwen21-q4",
                                             "loras": [{"id": "uncensored", "scale": 0.5}]}) == [1, 2, 3]
    capsys.readouterr()
    old_02 = _sha(_still(story_dir, 2))
    _write_story(tmp, text=_story_md([IMAGES[0], IMAGES[1] + " Gulls circle overhead.", IMAGES[2]]))
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    assert _jobs(fake)[-1] == [2]
    (moved,) = glob.glob(os.path.join(story_dir, "redo", "*", "images", "panel_02.png"))
    assert re.fullmatch(r"\d{8}T\d{6}Z-%d" % os.getpid(), os.path.basename(os.path.dirname(os.path.dirname(moved))))
    assert _sha(moved) == old_02
    assert ("seed edits: moved %s -> %s (not a recorded edit of this seed image, prompt, seed and settings)"
            % (_still(story_dir, 2), moved)) in capsys.readouterr().out.splitlines()
    Image.new("RGB", (1408, 896), (9, 9, 9)).save(_still(story_dir, 3))
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    assert _jobs(fake)[-1] == [3]
    assert movie._phase2_shots_seed(_phase_args(tmp, redo_panels=[1])) == 0
    assert _jobs(fake)[-1] == [1]


# --- SET10 (SE17): the memory wait or the install check fails every panel, before any child --------------

def test_set10_an_unavailable_selection_fails_every_panel(clean_env, capsys):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    story_dir = _write_story(tmp)
    text = "only 10.0 GiB available after waiting 0 s; Qwen-Image-2.1 q4 needs 20 GiB; free memory and retry"
    fake.wait_error = qwen_edit.Unavailable(text)
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 1
    assert capsys.readouterr().err == ("Error: the seed edits failed: %s (kept: none; edited on the next run: "
                                       "1,2,3)\n" % text)
    assert [(e["status"], e["error"], e["seconds"], e["output"]) for e in _record(story_dir)["panels"]] == [
        ("failed", text, None, None)] * 3
    assert fake.calls["run_jobs"] == []


# --- SET11 (SE14): one note when a Z-Image stills LoRA would have applied -----------------------------------

def test_set11_the_stills_lora_note(clean_env, capsys):
    tmp = clean_env["tmp"]
    _write_story(tmp)
    member = types.SimpleNamespace(stills_lora="/x.safetensors")
    assert movie._phase2_shots_seed(_phase_args(tmp, cast_members=[member])) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == LORA_NOTE and out.count(LORA_NOTE) == 1
    _write_story(tmp, "s2")
    assert movie._phase2_shots_seed(_phase_args(tmp, story_id="s2")) == 0
    assert LORA_NOTE not in capsys.readouterr().out


# --- SET12 (SE13): a panel without Image: text, or a story without panels, stops before any write ---------

def test_set12_a_panel_without_an_image_line(clean_env, capsys):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    story_dir = _write_story(tmp, text=_story_md([IMAGES[0], None, IMAGES[2]]))
    story_md = os.path.join(story_dir, "story.md")
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 1
    assert capsys.readouterr().err == ("Error: panel 2 of %s has no Image: description to edit the seed with\n"
                                       % story_md)
    assert not os.path.exists(os.path.join(story_dir, "seed-original.png"))
    assert not os.path.exists(os.path.join(story_dir, "seed_edits.json"))
    assert fake.calls["run_jobs"] == [] and fake.calls["wait_for_memory"] == []
    _write_story(tmp, text="# Empty\n\nNo panels.\n")
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 1
    assert capsys.readouterr().err == "Error: %s has no panels to edit the seed into\n" % story_md
    assert not os.path.exists(os.path.join(story_dir, "seed_edits.json"))


# --- SET15 (SE15, SEK4, SEK5): the real runner, one mflux child, every output screened ---------------------

def test_set15_the_real_runner_screens_every_panel(env):
    py, _snapshot, _lora = _mflux_ready(env)
    st.stub_config(py, {"red": [2]})
    tmp, mp = env["tmp"], env["mp"]
    mp.setattr(movie, "_qwen_edit", lambda: qwen_edit)
    mp.setattr(movie, "_story_dir", lambda story_id: os.path.join(tmp, "stories", story_id))
    story_dir = _write_story(tmp)
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 1
    (call,) = st.stub_calls(py)
    original = os.path.join(story_dir, "seed-original.png")
    assert [(j["n"], j["prompt"], j["source"]) for j in call["spec"]["jobs"]] == [
        (n, _prompt(n), original) for n in (1, 2, 3)]
    assert env["calls"]["safety"] == [{"skill": "ltx_movie_shots_seed_edit", "prompt": _prompt(n), "size": (704, 448)}
                                      for n in (1, 2, 3)]
    for n in (1, 3):
        with Image.open(_still(story_dir, n)) as img:
            assert img.size == (1408, 896)
    assert not os.path.exists(_still(story_dir, 2))
    assert [e["status"] for e in _record(story_dir)["panels"]] == ["ok", "blocked", "ok"]


# --- Review Focus 1: the story the default engine writes in shots mode (no Style:, Dialogue: lines) -------

def test_sse_review_focus_1_the_robust_engine_shots_story(clean_env):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    story_dir = _write_story(tmp, text=_story_md(style=None, dialogue=True))
    assert movie._shots_seed_prompts(os.path.join(story_dir, "story.md")) == [
        (n, PREFIX + IMAGES[n - 1]) for n in (1, 2, 3)]
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    assert [job["prompt"] for job in fake.calls["run_jobs"][0]["jobs"]] == [PREFIX + image for image in IMAGES]


# --- Review Focus 2: --redo of a shots seed story re-edits only its panels ----------------------------------

def test_sse_review_focus_2_a_redo_re_edits_only_its_panels(clean_env, capsys):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    story_dir = _write_story(tmp)
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    first = _record(story_dir)["panels"]
    old_02 = _sha(_still(story_dir, 2))
    args = _phase_args(tmp, redo_panels=[2])
    assert movie.phase_redo_shots(args) == 0
    capsys.readouterr()
    assert movie.phase2_stills(args) == 0
    out = capsys.readouterr().out.splitlines()
    assert _jobs(fake) == [[1, 2, 3], [2]]
    assert out[:2] == ["=== Phase 2: stills ===",
                       "seed edits: reusing the stills of panels 1,3 (recorded edits of the same seed image, prompt, "
                       "seed and settings)"]
    assert [line for line in out if line.startswith("seed edits: moved ")] == []
    (moved,) = glob.glob(os.path.join(story_dir, "redo", "*", "images", "panel_02.png"))
    assert _sha(moved) == old_02
    entries = _record(story_dir)["panels"]
    assert (entries[0], entries[2]) == (first[0], first[2])
    assert entries[1]["status"] == "ok" and entries[1]["still_sha256"] == _sha(_still(story_dir, 2))


# --- Review Focus 3: the legacy diffusers model (qwen2511-bf16) edits every panel in its own child ---------

PANEL_QWENEDIT_STUB = st.QWENEDIT_STUB.replace("int(name[5:7])", "int(name[6:8])")   # panel_NN.pending.png


def test_sse_review_focus_3_the_legacy_diffusers_model(env):
    assert PANEL_QWENEDIT_STUB != st.QWENEDIT_STUB
    tmp, mp = env["tmp"], env["mp"]
    _bf16_cache(env)
    stub = st.qwenedit_stub(env, {"blocked": [2]})
    with open(stub, "w", encoding="utf-8") as f:
        f.write(PANEL_QWENEDIT_STUB)
    mp.setattr(qwen_edit, "avail_gib", lambda: 80.0)
    mp.setattr(movie, "_qwen_edit", lambda: qwen_edit)
    mp.setattr(movie, "_story_dir", lambda story_id: os.path.join(tmp, "stories", story_id))
    story_dir = _write_story(tmp)
    assert movie._phase2_shots_seed(_phase_args(tmp, seed_edit={"qwen_model": "qwen2511-bf16", "loras": []})) == 1
    (call,) = st.stub_calls(stub)
    work = os.path.join(story_dir, "seed_edits")
    spec = call["spec"]
    assert (spec["image"], spec["skill"]) == (os.path.join(story_dir, "seed-original.png"), "ltx_movie_shots_seed_edit")
    assert spec["jobs"] == [{"prompt": _prompt(n), "output_path": os.path.join(work, "panel_%02d.pending.png" % n),
                             "seed": 3, "width": 704, "height": 448} for n in (1, 2, 3)]
    assert [e["status"] for e in _record(story_dir)["panels"]] == ["ok", "blocked", "ok"]
    assert [os.path.isfile(_still(story_dir, n)) for n in (1, 2, 3)] == [True, False, True]
    assert env["calls"]["safety"] == []


# --- Review Focus 4: a block and a failure in the same batch ------------------------------------------------

def test_sse_review_focus_4_a_block_and_a_failure_in_one_batch(clean_env, capsys):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    story_dir = _write_story(tmp)
    fake.outcomes, fake.failure = {2: "blocked", 3: "stop"}, "Qwen-Image-2.1 q4 child timed out after 3600 s"
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 1
    assert capsys.readouterr().err == (
        "Error: the seed edits failed: Qwen-Image-2.1 q4 child timed out after 3600 s (kept: 1; edited on the next "
        "run: 2,3)\n" + _blocked_text(story_dir, "2"))
    assert [(e["status"], e["error"]) for e in _record(story_dir)["panels"]] == [
        ("ok", None), ("blocked", None), ("failed", "Qwen-Image-2.1 q4 child timed out after 3600 s")]
    fake.reset()
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    assert _jobs(fake) == [[1, 2, 3], [2, 3]] and len(fake.calls["wait_for_memory"]) == 2
