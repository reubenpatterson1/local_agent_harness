"""Tests for bin/ltx-movie's --seed-context still (docs/superpowers/specs/2026-11-10-seeded-shots-context-design.md,
CX1-CX13: CXT1-CXT11): in seeded shots mode every panel after the first is a two-image Qwen edit of the seed and the
previous panel's still, one child per panel in panel order, screened, fitted, recorded in seed_context_edits.json
and reused on a rerun; panel 1 and every location change (a different Image: setting sentence) stay single-image
edits of the seed.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_ltx_movie_seed_context.py

bin/ltx-movie is loaded with SourceFileLoader, spec_from_loader, module_from_spec and exec_module as ltx_movie_sctx.
The ctx_env fixture sets HOME, HF_HOME and Z_IMAGE_HF_HOME under tmp_path, removes HF_HUB_CACHE and every
SEED_EDIT_* variable, and patches _story_dir to <tmp>/stories/<id> and _qwen_edit to _FakeContextQwenEdit (the
shots seed tests' multi-job fake plus the multi-reference table, a log_path recorder, an event log of the centre
pixel of every source at call time, and an exception to raise). CXT11 uses the real qwen_edit with the stub children
of tests/test_seed_edit_tool.py. No test loads a model, renders, contacts a server or touches port 8177 or 8178.
Stdlib, PIL and pytest.
"""

import argparse
import glob
import hashlib
import importlib.machinery
import importlib.util
import json
import os

import pytest
from PIL import Image

import movie_ui_testutil as mt
import qwen_edit
import test_seed_edit_tool as st
from test_ltx_movie_shots_seed import PANEL_QWENEDIT_STUB, _FakeShotsQwenEdit, _seed1920, _story_md, _write_story
from test_qwen_edit import _bf16_cache, _mflux_ready, env  # noqa: F401

WS = mt.WS
UNC = [{"id": "uncensored", "scale": 1.0}]
SEED_PREFIX = ("Edit this photo into a new shot of the same film. Every person from the photo who appears in the new "
               "shot keeps exactly the same face, hair, skin tone, build and clothing. Change their pose and action, "
               "the place, the background, the lighting, the framing and the camera angle to match the new shot, and "
               "leave out anyone the new shot does not describe. The new shot: ")
CONTEXT_PREFIX = (
    "Make the next shot of the same film from two pictures. Picture 1, the first input image, shows the people: "
    "everyone in the new shot keeps exactly the face, hair, skin tone, build and clothing they have in Picture 1. "
    "Picture 2, the second input image, is the previous moment of this scene: keep its place, background, props, "
    "time of day, lighting, colour palette and who stands on which side of the frame, and take nothing else from it: "
    "not the faces, the clothing, any blur or the grain. Change the pose, the action, the framing and the camera "
    "angle to match the new shot, and leave out anyone the new shot does not describe. The new shot: ")
SWAPPED_PREFIX = (
    "Make the next shot of the same film from two pictures. Picture 2, the second input image, shows the people: "
    "everyone in the new shot keeps exactly the face, hair, skin tone, build and clothing they have in Picture 2. "
    "Picture 1, the first input image, is the previous moment of this scene: keep its place, background, props, "
    "time of day, lighting, colour palette and who stands on which side of the frame, and take nothing else from it: "
    "not the faces, the clothing, any blur or the grain. Change the pose, the action, the framing and the camera "
    "angle to match the new shot, and leave out anyone the new shot does not describe. The new shot: ")
HARBOUR = "The setting is a rain-soaked stone harbour at night, wet cobbles underfoot, under amber lamplight."
MARKET = "The setting is a covered fish market hall at dawn, a wet stone floor, under cold white strip lights."
IMAGES = [HARBOUR + " She stands at the end of the quay facing right; medium shot, eye level.",
          HARBOUR + " She runs along the quay toward the camera; wide shot, low angle.",
          MARKET + " She walks between the fish stalls; medium shot, eye level.",
          MARKET + " She looks down at a crate of silver fish; close-up, high angle."]
STYLE = "Muted teal and amber colour with soft film grain."
SEED = (0, 200, 0)
ENTRY_KEYS = ["n", "status", "created", "label", "source", "source_sha256", "original", "context", "prompt", "seed",
              "width", "height", "still_width", "still_height", "qwen_model", "loras", "steps", "scheduler", "output",
              "still", "still_sha256", "seconds", "error"]
CHANGE_LINE = ("seed context: location changes at panels %s (the Image: setting sentence differs from the previous "
               "panel's): each of them is a single-image edit of the seed, like panel 1")
NONE_CONTEXT = {"kind": "none", "file": None, "sha256": None, "picture": None}


def _load_movie():
    path = os.path.join(WS, "bin", "ltx-movie")
    loader = importlib.machinery.SourceFileLoader("ltx_movie_sctx", path)
    spec = importlib.util.spec_from_loader("ltx_movie_sctx", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


movie = _load_movie()


def _pixel(path):
    with Image.open(path) as img:
        return img.convert("RGB").getpixel((img.width // 2, img.height // 2))


class _FakeContextQwenEdit(_FakeShotsQwenEdit):
    """The shots seed tests' multi-job fake (job n writes colour (0, 0, 40 * n)), plus multi_reference_problem;
    run_jobs records log_path in logs and ("edit", n, [centre pixel of every source at call time]) in events, and
    raises error when it is set."""
    MULTI_REFERENCE_MODEL_IDS = qwen_edit.MULTI_REFERENCE_MODEL_IDS

    def __init__(self):
        _FakeShotsQwenEdit.__init__(self)
        self.multi_reference_problem = qwen_edit.multi_reference_problem
        self.logs, self.events, self.error = [], [], None

    def run_jobs(self, model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None,
                 noun="job"):
        self.logs.append(log_path)
        for job in jobs:
            self.events.append(("edit", job["n"], [_pixel(p) for p in job.get("sources", [job["source"]])]))
        if self.error is not None:
            self.calls["run_jobs"].append({"jobs": [dict(j) for j in jobs]})
            raise self.error
        return _FakeShotsQwenEdit.run_jobs(self, model_id, loras, jobs, width, height, skill, work_dir,
                                           on_result=on_result, noun=noun)


@pytest.fixture
def ctx_env(monkeypatch, tmp_path):
    """The module docstring's environment. Returns {"tmp", "fake"}."""
    tmp = str(tmp_path)
    monkeypatch.setenv("HOME", os.path.join(tmp, "home"))
    for key in list(os.environ):
        if key.startswith("SEED_EDIT_"):
            monkeypatch.delenv(key)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", os.path.join(tmp, "hf"))
    monkeypatch.setenv("Z_IMAGE_HF_HOME", os.path.join(tmp, "zi"))
    fake = _FakeContextQwenEdit()
    monkeypatch.setattr(movie, "_qwen_edit", lambda: fake)
    monkeypatch.setattr(movie, "_story_dir", lambda story_id: os.path.join(tmp, "stories", story_id))
    return {"tmp": tmp, "fake": fake}


def _story(tmp, images=IMAGES, story_id="s1"):
    return _write_story(tmp, story_id, _story_md(images, STYLE))


def _args(tmp, **overrides):
    """A seeded shots run of story s1 at 704x448 (stills 1408x896), image seed 3, qwen21-q4 + uncensored, with
    --seed-context still (seed-first) and the 200x100 green PNG seed <tmp>/seed.png."""
    seed = os.path.join(tmp, "seed.png")
    if not os.path.isfile(seed):
        st.png(seed, (200, 100), SEED)
    values = dict(story_id="s1", seed_image=seed, video_width=704, video_height=448, image_seed=3,
                  seed_edit={"qwen_model": "qwen21-q4", "loras": UNC}, shots=True, redo_panels=[],
                  cast_members=[], location_pins=[], story_engine="robust", no_auto_lora=True, panels=4,
                  force_story=False, global_stills_loras=[], stills_lora_path=None,
                  seed_context={"mode": "still", "order": "seed-first"})
    values.update(overrides)
    return argparse.Namespace(**values)


def _record(story_dir):
    with open(os.path.join(story_dir, "seed_context_edits.json"), encoding="utf-8") as f:
        return json.load(f)


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _still(story_dir, n):
    return os.path.join(story_dir, "images", "panel_%02d.png" % n)


def _edited(fake, since=0):
    """The panel of every run_jobs call from call number since on."""
    return [call["jobs"][0]["n"] for call in fake.calls["run_jobs"][since:]]


def _prompt(n, images=IMAGES, prefix=None):
    if prefix is None:
        prefix = SEED_PREFIX if n in (1, 3) else CONTEXT_PREFIX
    return prefix + images[n - 1] + " " + STYLE


# --- CXT1 (CX2): the option rules ---------------------------------------------------------------------------------

def _parse(*extra):
    args = movie.build_parser().parse_args(["a narrative", "--story-id", "s1"] + list(extra))
    args.seed_edit = None
    return args


def test_cxt1_the_option_rules(ctx_env, capsys):
    tmp = ctx_env["tmp"]
    seed = st.png(os.path.join(tmp, "seed.png"), (64, 64))
    q4 = {"qwen_model": "qwen21-q4", "loras": UNC}
    args = _parse()
    assert (args.seed_context_mode, args.seed_context_order) == (None, None)
    assert movie._resolve_seed_context(args) == 0 and args.seed_context is None
    shots = ["--shots", "--seed-image", seed, "--seed-context", "still"]
    cases = [(("--seed-context-order", "context-first"), None, "Error: --seed-context-order needs --seed-context\n"),
             (("--seed-context", "still"), q4,
              "Error: --seed-context needs --shots: it conditions each seeded shots still on the previous panel\n"),
             (("--shots", "--seed-context", "still"), q4,
              "Error: --seed-context needs --seed-image: every shots still is then a Qwen edit of the seed\n"),
             (tuple(shots + ["--cast-refs-model", "qwen21-q4"]), q4,
              "Error: --seed-context cannot be combined with --cast-refs-model: with a seed image every shots still "
              "is already a Qwen edit of the seed\n"),
             (tuple(shots), None,
              "Error: --seed-context needs --seed-edit-model ID, a Qwen registry edit model (as-is is refused): every "
              "shots still is a Qwen edit of the seed\n"),
             (tuple(shots), {"qwen_model": "qwen2511-q4", "loras": []},
              "Error: --seed-context needs a --seed-edit-model that edits with several pictures; qwen2511-q4 is "
              "refused: " + qwen_edit.MULTI_REFERENCE_REFUSED["qwen2511-q4"] + "\n")]
    for extra, edit, text in cases:
        args = _parse(*extra)
        args.seed_edit = edit
        assert movie._resolve_seed_context(args) == 2, extra
        assert capsys.readouterr() == ("", text), extra
        assert args.seed_context is None
    for model in ("qwen21-q4", "qwen21-q8", "qwen21-bf16", "qwen2511-bf16"):
        args = _parse(*shots)
        args.seed_edit = {"qwen_model": model, "loras": []}
        assert movie._resolve_seed_context(args) == 0
        assert args.seed_context == {"mode": "still", "order": "seed-first"}
    args = _parse(*(shots + ["--seed-context-order", "context-first"]))
    args.seed_edit = q4
    assert movie._resolve_seed_context(args) == 0
    assert args.seed_context == {"mode": "still", "order": "context-first"}
    assert capsys.readouterr() == ("", "")
    base = ["n", "--story-id", "s1", "--dry-run", "--seed-context", "still"]
    for extra, text in (
            (["--shots", "--no-stills"],
             "Error: --shots needs Phase 2's per-panel stills; it cannot be combined with --no-stills\n"),
            (["--shots", "--seed-image", seed],
             "Error: --shots with --seed-image needs --seed-edit-model ID: every panel's still is a Qwen edit of the "
             "seed, so the seed cannot be used as-is\n"),
            (["--shots", "--seed-image", seed, "--seed-edit-model", "as-is"],
             "Error: --shots with --seed-image needs --seed-edit-model ID: every panel's still is a Qwen edit of the "
             "seed, so the seed cannot be used as-is\n"),
            (["--shots", "--seed-image", seed, "--seed-edit-model", "qwen2511-q4"],
             "Error: --seed-context needs a --seed-edit-model that edits with several pictures; qwen2511-q4 is "
             "refused: " + qwen_edit.MULTI_REFERENCE_REFUSED["qwen2511-q4"] + "\n"),
            (["--shots", "--seed-image", seed, "--seed-edit-model", "qwen21-q4", "--cast-refs-model", "qwen21-q4"],
             "Error: --cast-refs-model cannot be combined with --seed-image: with a seed image every shots still is "
             "already a Qwen edit of the seed\n"),
            (["--no-stills"], "Error: --seed-context needs --shots: it conditions each seeded shots still on the "
                              "previous panel\n")):
        assert movie.main(base + extra) == 2, extra
        assert capsys.readouterr().err == text, extra


# --- CXT2 (CX3, CX4, CX5): the setting sentence, the kinds, the prompts and the key --------------------------------

def test_cxt2_the_plan(ctx_env):
    tmp, fake = ctx_env["tmp"], ctx_env["fake"]
    lib = movie._character_lib()
    setting = movie._seed_context_setting
    assert setting(lib, IMAGES[0]) == HARBOUR and setting(lib, IMAGES[2]) == MARKET
    assert setting(lib, "She waits. The setting is  a quay\n at night. Rain falls.") == (
        "The setting is a quay at night.")
    assert setting(lib, "the setting is a quay at dusk. She waits.") == "the setting is a quay at dusk."
    assert setting(lib, "She waits on the quay. Rain falls.") is None
    story_dir = _story(tmp)
    args = _args(tmp)
    error, plan = movie._seed_context_plan(args, fake)
    assert error is None
    assert plan["kinds"] == {1: "none", 2: "still", 3: "none", 4: "still"} and plan["changes"] == [3]
    assert plan["prompts"] == dict((n, _prompt(n)) for n in (1, 2, 3, 4))
    assert (plan["size"], plan["still"], plan["total"], plan["entries"]) == ((704, 448), (1408, 896), 4, {})
    assert plan["base"][2] == dict(qwen_edit.settings("qwen21-q4", UNC), source_sha256=_sha(args.seed_image),
                                   prompt=_prompt(2), seed=3, width=704, height=448, still_width=1408,
                                   still_height=896)
    _error, plan = movie._seed_context_plan(_args(tmp, seed_context={"mode": "still", "order": "context-first"}),
                                            fake)
    assert plan["prompts"] == {1: _prompt(1), 2: _prompt(2, prefix=SWAPPED_PREFIX), 3: _prompt(3),
                               4: _prompt(4, prefix=SWAPPED_PREFIX)}
    one_place = [IMAGES[0], IMAGES[1], HARBOUR + " She sits.", "She stands up. " + HARBOUR]
    _story(tmp, one_place)
    _error, plan = movie._seed_context_plan(args, fake)
    assert (plan["kinds"], plan["changes"]) == ({1: "none", 2: "still", 3: "still", 4: "still"}, [])
    _story(tmp, ["She waits.", "She runs.", HARBOUR + " She sits.", "She stands."])
    _error, plan = movie._seed_context_plan(args, fake)
    assert (plan["kinds"], plan["changes"]) == ({1: "none", 2: "still", 3: "none", 4: "none"}, [3, 4])
    story_md = os.path.join(story_dir, "story.md")
    _write_story(tmp, "s1", _story_md([IMAGES[0], None, IMAGES[2]], STYLE))
    assert movie._seed_context_plan(args, fake) == (
        "panel 2 of %s has no Image: description to edit the seed with" % story_md, None)
    _write_story(tmp, "s1", "# Empty\n\nNo panels.\n")
    assert movie._seed_context_plan(args, fake) == ("%s has no panels to edit the seed into" % story_md, None)
    assert fake.calls["run_jobs"] == [] and not os.path.exists(os.path.join(story_dir, "seed_context_edits.json"))


# --- CXT3 (CX6, CX8, CX10): one child per panel, in order, each context the previous panel's fresh still ---------

def test_cxt3_every_panel_in_order(ctx_env, capsys):
    tmp, fake = ctx_env["tmp"], ctx_env["fake"]
    story_dir = _story(tmp)
    args = _args(tmp)
    assert movie.phase2_stills(args) == 0
    work = os.path.join(story_dir, "seed_context_edits")
    original = os.path.join(story_dir, "seed-original.png")
    stage = lambda n: os.path.join(work, "panel_%02d.pending.png" % n)   # noqa: E731
    output = lambda n: os.path.join(work, "panel_%02d.png" % n)          # noqa: E731
    jobs = [{"n": 1, "seed": 3, "prompt": _prompt(1), "source": original, "stage_path": stage(1),
             "output_path": output(1)},
            {"n": 2, "seed": 3, "prompt": _prompt(2), "source": original, "stage_path": stage(2),
             "output_path": output(2), "sources": [original, _still(story_dir, 1)]},
            {"n": 3, "seed": 3, "prompt": _prompt(3), "source": original, "stage_path": stage(3),
             "output_path": output(3)},
            {"n": 4, "seed": 3, "prompt": _prompt(4), "source": original, "stage_path": stage(4),
             "output_path": output(4), "sources": [original, _still(story_dir, 3)]}]
    assert fake.calls["run_jobs"] == [{"model_id": "qwen21-q4", "loras": UNC, "jobs": [job], "size": (704, 448),
                                       "skill": "ltx_movie_seed_context_edit", "work_dir": work, "noun": "panel"}
                                      for job in jobs]
    assert fake.events == [("edit", 1, [SEED]), ("edit", 2, [SEED, (0, 0, 40)]), ("edit", 3, [SEED]),
                           ("edit", 4, [SEED, (0, 0, 120)])]
    assert fake.logs == [os.path.join(work, "child-%02d.log" % n) for n in (1, 2, 3, 4)]
    assert fake.calls["wait_for_memory"] == [(20.0, "Qwen-Image-2.1 q4", "ltx-movie")] * 4
    with Image.open(original) as img:
        assert (img.format, img.size) == ("PNG", (200, 100))
    record = _record(story_dir)
    assert list(record) == ["schema", "updated", "panels"] and record["schema"] == "ltx-movie.seed-context-edits.v1"
    settings = qwen_edit.settings("qwen21-q4", UNC)
    for n, entry in enumerate(record["panels"], start=1):
        with Image.open(_still(story_dir, n)) as img:
            assert (img.format, img.size, img.getpixel((5, 5))) == ("PNG", (1408, 896), (0, 0, 40 * n))
        assert list(entry) == ENTRY_KEYS
        context = NONE_CONTEXT if n in (1, 3) else {"kind": "still", "file": "images/panel_%02d.png" % (n - 1),
                                                    "sha256": _sha(_still(story_dir, n - 1)), "picture": 2}
        assert dict(entry, created=None) == {
            "n": n, "status": "ok", "created": None, "label": "Qwen-Image-2.1 q4",
            "source": os.path.abspath(args.seed_image), "source_sha256": _sha(args.seed_image),
            "original": "seed-original.png", "context": context, "prompt": _prompt(n), "seed": 3, "width": 704,
            "height": 448, "still_width": 1408, "still_height": 896, "qwen_model": settings["qwen_model"],
            "loras": settings["loras"], "steps": 40, "scheduler": "linear",
            "output": "seed_context_edits/panel_%02d.png" % n, "still": "images/panel_%02d.png" % n,
            "still_sha256": _sha(_still(story_dir, n)), "seconds": 12.5, "error": None}
    assert [len(record["panels"])] == [4]
    for name in ("seed_edits.json", "seed_edits", "redo", os.path.join("images", "images.json")):
        assert not os.path.exists(os.path.join(story_dir, name)), name
    assert capsys.readouterr().out.splitlines() == [
        "=== Phase 2: stills ===", CHANGE_LINE % "3",
        "seed context: %s; 704x448, fitted into 1408x896 stills; seed 3; 4 panels in order, one Qwen child per edited "
        "panel; the seed is Picture 1 and the previous panel's still is Picture 2"
        % qwen_edit.generator_text("qwen21-q4", UNC),
        "seed context: panel 1: a single-image edit of the seed",
        "panel 1 -> %s (seed-context Qwen edit, 12.5s)" % _still(story_dir, 1),
        "seed context: panel 2: Picture 1 is the seed (%s), Picture 2 is panel 1's still (%s)"
        % (original, _still(story_dir, 1)),
        "panel 2 -> %s (seed-context Qwen edit, 12.5s)" % _still(story_dir, 2),
        "seed context: panel 3: a single-image edit of the seed (a location change: its setting sentence differs "
        "from panel 2's)",
        "panel 3 -> %s (seed-context Qwen edit, 12.5s)" % _still(story_dir, 3),
        "seed context: panel 4: Picture 1 is the seed (%s), Picture 2 is panel 3's still (%s)"
        % (original, _still(story_dir, 3)),
        "panel 4 -> %s (seed-context Qwen edit, 12.5s)" % _still(story_dir, 4),
        "seed context: 4 panel stills written, 0 reused"]


# --- CXT4 (CX3, CX6): --seed-context-order context-first swaps the pictures and the prompt -----------------------

def test_cxt4_context_first(ctx_env, capsys):
    tmp, fake = ctx_env["tmp"], ctx_env["fake"]
    story_dir = _story(tmp)
    args = _args(tmp, seed_context={"mode": "still", "order": "context-first"})
    assert movie._phase2_seed_context(args) == 0
    original = os.path.join(story_dir, "seed-original.png")
    job = fake.calls["run_jobs"][1]["jobs"][0]
    assert (job["prompt"], job["source"], job["sources"]) == (
        _prompt(2, prefix=SWAPPED_PREFIX), _still(story_dir, 1), [_still(story_dir, 1), original])
    assert fake.events[1] == ("edit", 2, [(0, 0, 40), SEED])
    assert "sources" not in fake.calls["run_jobs"][2]["jobs"][0]
    entries = _record(story_dir)["panels"]
    assert [e["context"]["picture"] for e in entries] == [None, 1, None, 1]
    out = capsys.readouterr().out.splitlines()
    assert ("seed context: panel 2: Picture 2 is the seed (%s), Picture 1 is panel 1's still (%s)"
            % (original, _still(story_dir, 1))) in out
    assert out[1].endswith("the seed is Picture 2 and the previous panel's still is Picture 1")


# --- CXT5 (CX7): a rerun reuses unchanged panels; a changed still re-edits the panels that see it ---------------

def test_cxt5_reuse_and_the_cascade(ctx_env, capsys):
    tmp, fake = ctx_env["tmp"], ctx_env["fake"]
    story_dir = _story(tmp)
    assert movie._phase2_seed_context(_args(tmp)) == 0
    capsys.readouterr()

    def rerun(images=IMAGES, **overrides):
        """The panels a rerun edits."""
        _story(tmp, images)
        before = len(fake.calls["run_jobs"])
        assert movie._phase2_seed_context(_args(tmp, **overrides)) == 0
        return _edited(fake, before)

    assert rerun() == []
    out = capsys.readouterr().out.splitlines()
    assert out[2:] == ["seed context: panel %d: reusing %s (a recorded edit of the same seed image, context picture, "
                       "prompt, seed and settings)" % (n, _still(story_dir, n)) for n in (1, 2, 3, 4)] + [
        "seed context: 0 panel stills written, 4 reused"]
    old_02 = _sha(_still(story_dir, 2))
    changed = list(IMAGES)
    changed[1] = IMAGES[1] + " Gulls circle overhead."
    assert rerun(changed) == [2]
    (moved,) = glob.glob(os.path.join(story_dir, "redo", "*", "images", "panel_02.png"))
    assert _sha(moved) == old_02
    assert ("seed context: moved %s -> %s (not a recorded edit of this seed image, context picture, prompt, seed and "
            "settings)" % (_still(story_dir, 2), moved)) in capsys.readouterr().out.splitlines()
    assert rerun() == [2]
    first = list(IMAGES)
    first[0] = IMAGES[0] + " Rain falls."
    assert rerun(first) == [1, 2]
    assert rerun() == [1, 2]
    third = list(IMAGES)
    third[2] = IMAGES[2] + " Gulls cry."
    assert rerun(third) == [3, 4]
    assert rerun() == [3, 4]
    capsys.readouterr()
    assert rerun(redo_panels=[1]) == [1, 2]
    assert capsys.readouterr().out.splitlines()[1] == (
        "note: seed context: --redo 1 also re-edits panels 2: their context picture is the previous panel's still, "
        "so it changes with it, up to the next location change")
    assert rerun(redo_panels=[1, 3]) == [1, 2, 3, 4]
    assert "note: seed context: --redo 1,3 also re-edits panels 2,4: " in capsys.readouterr().out
    assert rerun(redo_panels=[2]) == [2]
    assert "--redo" not in capsys.readouterr().out
    assert rerun(seed_context={"mode": "still", "order": "context-first"}) == [2, 4]
    assert rerun() == [2, 4]
    other = st.png(os.path.join(tmp, "seed-red.png"), (200, 100), (200, 0, 0))
    assert rerun(seed_image=other) == [1, 2, 3, 4]
    assert rerun() == [1, 2, 3, 4]
    assert rerun(image_seed=4) == [1, 2, 3, 4]
    assert rerun() == [1, 2, 3, 4]
    Image.new("RGB", (1408, 896), (9, 9, 9)).save(_still(story_dir, 2))
    assert rerun() == [2]
    Image.new("RGB", (1408, 896), (9, 9, 9)).save(_still(story_dir, 1))
    assert rerun() == [1, 2]
    assert rerun(seed_edit={"qwen_model": "qwen21-q8", "loras": []}) == [1, 2, 3, 4]


# --- CXT6 (CX8): a blocked or failed panel stops the phase at that panel, with no fallback and no traceback ------

def test_cxt6_blocked_failed_and_raising_panels(ctx_env, capsys):
    tmp, fake = ctx_env["tmp"], ctx_env["fake"]
    story_dir = _story(tmp)
    story_md = os.path.join(story_dir, "story.md")
    fake.outcomes = {2: "blocked"}
    assert movie._phase2_seed_context(_args(tmp)) == 1
    captured = capsys.readouterr()
    assert captured.err == (
        "Error: the content screen blocked the seed-context Qwen edit (Qwen-Image-2.1 q4) of panel 2 of story s1; the "
        "movie stops here rather than use an unscreened, unedited or text-rendered still. Change that panel's Image: "
        "line in %s, then rerun: every recorded still before it is reused\n" % story_md)
    assert "panel 2 BLOCKED: the content screen blocked the seed-context Qwen edit" in captured.out.splitlines()
    assert _edited(fake) == [1, 2]
    assert [(e["n"], e["status"], e["still"]) for e in _record(story_dir)["panels"]] == [
        (1, "ok", "images/panel_01.png"), (2, "blocked", None)]
    assert [os.path.exists(_still(story_dir, n)) for n in (1, 2, 3, 4)] == [True, False, False, False]
    fake.reset()
    assert movie._phase2_seed_context(_args(tmp)) == 0
    assert _edited(fake) == [1, 2, 2, 3, 4]
    fake.outcomes, fake.failure = {3: "stop"}, "Qwen-Image-2.1 q4 child timed out after 3600 s"
    capsys.readouterr()
    assert movie._phase2_seed_context(_args(tmp, redo_panels=[3])) == 1
    assert capsys.readouterr().err == (
        "Error: the seed-context edit of panel 3 failed: Qwen-Image-2.1 q4 child timed out after 3600 s; the stills "
        "before it are kept, and a rerun continues from panel 3\n")
    assert _edited(fake) == [1, 2, 2, 3, 4, 3]
    assert [(e["n"], e["status"], e["seconds"], e["error"]) for e in _record(story_dir)["panels"]] == [
        (1, "ok", 12.5, None), (2, "ok", 12.5, None),
        (3, "failed", None, "Qwen-Image-2.1 q4 child timed out after 3600 s")]
    assert os.path.isfile(_still(story_dir, 4)) and not os.path.exists(_still(story_dir, 3))
    fake.reset()
    fake.outcomes = {3: "stop"}
    assert movie._phase2_seed_context(_args(tmp)) == 1
    assert "failed: Qwen-Image-2.1 q4 reported no result for panel 3; " in capsys.readouterr().err
    fake.reset()
    text = "only 3.0 GiB available after waiting 600 s; Qwen-Image-2.1 q4 needs 20 GiB; free memory and retry"
    fake.wait_error = qwen_edit.Unavailable(text)
    assert movie._phase2_seed_context(_args(tmp)) == 1
    assert capsys.readouterr().err == ("Error: the seed-context edit of panel 3 failed: %s; the stills before it are "
                                       "kept, and a rerun continues from panel 3\n" % text)
    assert _record(story_dir)["panels"][2]["error"] == text
    fake.reset()
    fake.error = OSError("disk full")
    assert movie._phase2_seed_context(_args(tmp)) == 1
    assert capsys.readouterr().err == ("Error: the seed-context edit of panel 3 failed: OSError: disk full; the stills "
                                       "before it are kept, and a rerun continues from panel 3\n")
    assert [(e["n"], e["status"], e["error"]) for e in _record(story_dir)["panels"]][2] == (
        3, "failed", "OSError: disk full")
    fake.error = None
    fake.interrupt_after = 3
    with pytest.raises(KeyboardInterrupt):
        movie._phase2_seed_context(_args(tmp))
    assert [(e["n"], e["status"]) for e in _record(story_dir)["panels"]] == [(1, "ok"), (2, "ok"), (3, "ok")]
    fake.reset()
    capsys.readouterr()
    before = len(fake.calls["run_jobs"])
    assert movie._phase2_seed_context(_args(tmp)) == 0
    assert _edited(fake, before) == [4]


# --- CXT7 (CX12): without the flag nothing changes ------------------------------------------------------------------

def test_cxt7_without_the_flag(ctx_env, monkeypatch, capsys):
    tmp, fake = ctx_env["tmp"], ctx_env["fake"]
    story_dir = _story(tmp)
    seen = []
    monkeypatch.setattr(movie, "_phase2_shots_seed", lambda args: seen.append(args) or 0)
    args = _args(tmp, seed_context=None)
    assert movie.phase2_stills(args) == 0
    assert seen == [args] and fake.calls["run_jobs"] == []
    assert not os.path.exists(os.path.join(story_dir, "seed_context_edits.json"))
    assert not os.path.exists(os.path.join(story_dir, "seed_context_edits"))
    assert capsys.readouterr().out == "=== Phase 2: stills ===\n"
    for context in (None, {"mode": "still", "order": "seed-first"}):
        seq = argparse.Namespace(no_stills=False, story_server_stop_after_story=True, seed_image="x.png",
                                 story_only=False, shots=True, redo_panels=[], seed_edit={"qwen_model": "qwen21-q4"},
                                 seed_context=context)
        assert [p.__name__ for p in movie._phase_sequence(seq)] == [
            "phase0_seed", "phase1_story", "phase_release_story_server", "phase2_stills", "phase3_manifest",
            "phase4_render"]


# --- CXT8 (CX11): the dry run ---------------------------------------------------------------------------------------

DRY = ("Would edit the seed into every panel's still with %s at 576x320, seed 0, one Qwen child per edited panel, in "
       "panel order: panel 1 and every panel whose Image: setting sentence differs from the previous panel's are "
       "single-image edits of the seed (the shots seed-edit instruction); every other panel is a two-image edit with "
       "the seed as Picture 1 and the previous panel's still as Picture 2 (the seed-context instruction). Each is "
       "prompted by its own Image: text (and the Style: text) from story.md, screened with content safety (skill "
       "ltx_movie_seed_context_edit), fitted (never cropped) into %s at 1152x640 and recorded in %s. Z-Image and "
       "stills LoRAs are not used. A blocked or failed panel stops the run; a rerun reuses every recorded edit whose "
       "context picture is unchanged.")


def _dry(capsys, *extra):
    rc = movie.main(["a narrative", "--story-id", "s1", "--dry-run", "--no-review", "--no-auto-lora"] + list(extra))
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    return captured.out.splitlines()


def test_cxt8_the_dry_run(ctx_env, capsys):
    tmp, fake = ctx_env["tmp"], ctx_env["fake"]
    seed = _seed1920(tmp)
    story_dir = os.path.join(tmp, "stories", "s1")
    flags = ("--shots", "--seed-image", seed, "--seed-edit-model", "qwen21-q4", "--seed-context", "still")
    lines = _dry(capsys, *flags)
    i = lines.index("--- Phase 2: stills ---")
    assert lines[i:i + 5] == [
        "--- Phase 2: stills ---",
        DRY % (qwen_edit.generator_text("qwen21-q4", []), os.path.join(story_dir, "images", "panel_NN.png"),
               os.path.join(story_dir, "seed_context_edits.json")),
        "Panels: decided at Phase 2, from story.md after Phase 1", "", "--- Phase 3: manifest + dry-run ---"]
    swapped = _dry(capsys, *(flags + ("--seed-context-order", "context-first")))
    assert ("with the seed as Picture 2 and the previous panel's still as Picture 1 (the seed-context instruction)"
            in swapped[i + 1])
    _story(tmp)
    args = _args(tmp, seed_image=seed, video_width=576, video_height=320, image_seed=0,
                 seed_edit={"qwen_model": "qwen21-q4", "loras": []})
    assert movie._phase2_seed_context(args) == 0
    third = list(IMAGES)
    third[2] = IMAGES[2] + " Gulls cry."
    _story(tmp, third)
    lines = _dry(capsys, *flags)
    i = lines.index("--- Phase 2: stills ---")
    assert lines[i + 2:i + 5] == ["Location changes (single-image edits): 3", "Panels to edit: 3,4; reused: 1,2", ""]
    lines = _dry(capsys, *(flags + ("--redo", "1", "--panels", "4")))
    assert "Panels to edit: 1,2,3,4; reused: none" in lines
    assert len(fake.calls["run_jobs"]) == 4 and fake.calls["selection_problem"] == []
    assert not os.path.exists(os.path.join(story_dir, "redo"))
    assert _record(story_dir)["panels"][2]["prompt"] == _prompt(3)


# --- CXT9 (CX1, CX13): the help texts and the docstring paragraph ------------------------------------------------

HELP = {
    "--seed-context": (
        "a test option for --shots with --seed-image: every panel after the first is a two-image Qwen edit of the "
        "seed (the people) and the previous panel's still (the scene), one Qwen child per panel in panel order, "
        "recorded in seed_context_edits.json; panel 1 and every panel whose Image: setting sentence differs from the "
        "previous panel's stay single-image edits of the seed. frame uses the exact last frame of the previous "
        "panel's clip instead, rendering each clip right after its still; a failed still or clip stops the run. "
        "Needs a --seed-edit-model that edits with several pictures (qwen2511-q4 is refused). See "
        "docs/superpowers/specs/2026-11-10-seeded-shots-context-design.md."),
    "--seed-context-order": ("with --seed-context: seed-first (the default) makes the seed Picture 1 and the context "
                             "picture Picture 2; context-first swaps them")}
DOC = ("Seed context (docs/superpowers/specs/2026-11-10-seeded-shots-context-design.md), a test option: in shots mode "
       "with --seed-image, --seed-context still makes every panel after the first a two-image Qwen edit of the seed "
       "(the people) and the previous panel's still (the scene), one Qwen child per panel in panel order, recorded in "
       "seed_context_edits.json; panel 1 and every panel whose Image: setting sentence differs from the previous "
       "panel's stay single-image edits of the seed. --seed-context frame uses the exact last frame of the previous "
       "panel's clip instead: Phase 2 then renders each clip right after its still (bin/ltx-mlx-render --resume on "
       "the panels so far), and Phases 3 and 4 reuse every clip. Absent, Phase 2 is unchanged. Cast references")


def test_cxt9_the_help_texts_and_the_docstring():
    actions = dict((a.option_strings[0], a) for a in movie.build_parser()._actions if a.option_strings)
    for flag, text in HELP.items():
        assert actions[flag].help == text, flag
    assert actions["--seed-context"].choices == ["still", "frame"]
    assert actions["--seed-context-order"].choices == ["seed-first", "context-first"]
    assert DOC in " ".join(movie.__doc__.split())
    with open(os.path.join(WS, "bin", "ltx-movie"), encoding="utf-8") as f:
        text = f.read()
    assert "\nimport re\n" not in text
    for orphan in ("_style_echo_warnings", "_style_content_warnings", "_content_words", "_ECHO_",
                   "_STYLE_BANNED_TOKENS", "require_style"):
        assert orphan not in text, orphan


# --- CXT10 (CX8): the panel order of the edits is the event order -------------------------------------------------

def test_cxt10_each_context_still_exists_before_its_edit(ctx_env, monkeypatch):
    tmp, fake = ctx_env["tmp"], ctx_env["fake"]
    story_dir = _story(tmp, [IMAGES[0], IMAGES[1], HARBOUR + " She sits.", HARBOUR + " She stands."])
    events = []
    real_fit = movie._image_fit

    class _Fit(object):
        def __init__(self, mod):
            self.mod = mod
            self.load_oriented_rgb = mod.load_oriented_rgb

        def fit_letterbox(self, img, width, height):
            events.append(("fit", img.getpixel((0, 0))[2] // 40))
            return self.mod.fit_letterbox(img, width, height)

    monkeypatch.setattr(movie, "_image_fit", lambda: _Fit(real_fit()))
    real_run = fake.run_jobs

    def run_jobs(model_id, loras, jobs, *a, **k):
        events.append(("child", jobs[0]["n"], [os.path.basename(p) for p in jobs[0].get("sources", [])]))
        return real_run(model_id, loras, jobs, *a, **k)

    monkeypatch.setattr(fake, "run_jobs", run_jobs)
    assert movie._phase2_seed_context(_args(tmp)) == 0
    assert events == [("child", 1, []), ("fit", 1), ("child", 2, ["seed-original.png", "panel_01.png"]), ("fit", 2),
                      ("child", 3, ["seed-original.png", "panel_02.png"]), ("fit", 3),
                      ("child", 4, ["seed-original.png", "panel_03.png"]), ("fit", 4)]
    assert fake.events == [("edit", 1, [SEED]), ("edit", 2, [SEED, (0, 0, 40)]), ("edit", 3, [SEED, (0, 0, 80)]),
                           ("edit", 4, [SEED, (0, 0, 120)])]
    assert os.path.isfile(_still(story_dir, 4))


# --- CXT11 (CX8): the real runner: one child per panel, the two sources, every output screened ---------------------

def test_cxt11_the_real_runner(env):
    py, _snapshot, _lora = _mflux_ready(env)
    tmp, mp = env["tmp"], env["mp"]
    mp.setattr(movie, "_qwen_edit", lambda: qwen_edit)
    mp.setattr(movie, "_story_dir", lambda story_id: os.path.join(tmp, "stories", story_id))
    images = IMAGES[:2] + [HARBOUR + " She sits on a bollard; medium shot, eye level."]
    story_dir = _story(tmp, images)
    work = os.path.join(story_dir, "seed_context_edits")
    original = os.path.join(story_dir, "seed-original.png")
    args = _args(tmp, panels=3)
    prompts = [_prompt(1, images), _prompt(2, images), _prompt(3, images, prefix=CONTEXT_PREFIX)]
    assert movie._phase2_seed_context(args) == 0
    calls = st.stub_calls(py)
    assert [[(j["n"], j["prompt"], j["source"], j.get("sources")) for j in c["spec"]["jobs"]] for c in calls] == [
        [(1, prompts[0], original, None)], [(2, prompts[1], original, [original, _still(story_dir, 1)])],
        [(3, prompts[2], original, [original, _still(story_dir, 2)])]]
    assert env["calls"]["safety"] == [{"skill": "ltx_movie_seed_context_edit", "prompt": p, "size": (704, 448)}
                                      for p in prompts]
    for n in (1, 2, 3):
        with open(os.path.join(work, "child-%02d.log" % n), encoding="utf-8") as f:
            assert f.read() == "seed-edit-child done %d 1.0\n" % n
    with open(os.path.join(work, "child-02.log"), "a", encoding="utf-8") as f:
        f.write("an older run's line\n")
    st.stub_config(py, {"red": [3]})
    assert movie._phase2_seed_context(_args(tmp, panels=3, redo_panels=[2])) == 1
    assert [c["spec"]["jobs"][0]["n"] for c in st.stub_calls(py)] == [1, 2, 3, 2, 3]
    with open(os.path.join(work, "child-02.log"), encoding="utf-8") as f:
        assert f.read() == "seed-edit-child done 2 1.0\n"
    assert [e["status"] for e in _record(story_dir)["panels"]] == ["ok", "ok", "blocked"]
    stub = st.qwenedit_stub(env, {"blocked": [2]})
    with open(stub, "w", encoding="utf-8") as f:
        f.write(PANEL_QWENEDIT_STUB)
    _bf16_cache(env)
    mp.setattr(qwen_edit, "avail_gib", lambda: 80.0)
    _story(tmp, images, story_id="s2")
    bf16 = _args(tmp, story_id="s2", panels=3, seed_edit={"qwen_model": "qwen2511-bf16", "loras": []})
    assert movie._phase2_seed_context(bf16) == 1
    s2 = os.path.join(tmp, "stories", "s2")
    calls = st.stub_calls(stub)
    assert [c["spec"]["jobs"] for c in calls] == [
        [{"prompt": _prompt(1, images), "output_path": os.path.join(s2, "seed_context_edits", "panel_01.pending.png"),
          "seed": 3, "width": 704, "height": 448}],
        [{"prompt": _prompt(2, images), "output_path": os.path.join(s2, "seed_context_edits", "panel_02.pending.png"),
          "seed": 3, "width": 704, "height": 448, "images": [os.path.join(s2, "seed-original.png"),
                                                             _still(s2, 1)]}]]
    assert [c["spec"]["skill"] for c in calls] == ["ltx_movie_seed_context_edit"] * 2
    assert [e["status"] for e in _record(s2)["panels"]] == ["ok", "blocked"]
