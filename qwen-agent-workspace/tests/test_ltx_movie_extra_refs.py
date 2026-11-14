"""Tests for bin/ltx-movie's --extra-ref (docs/superpowers/specs/2026-11-13-extra-reference-images-design.md, XR1-XR15,
XR21, XR23: XR-T6-XR-T18): up to nine user pictures added to every Qwen edit of the run after the edit's own pictures,
named in the edit prompt, copied into the story, keyed for reuse, capped by the edit model's max_references and refused
in low-RAM mode.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_ltx_movie_extra_refs.py

bin/ltx-movie is loaded with SourceFileLoader, spec_from_loader, module_from_spec and exec_module as ltx_movie_xr.
The xr_env fixture is test_ltx_movie_shots_seed's clean_env with the multi-job fake plus what the resolver needs
(_xr), and no autotune variable. XR-T12, XR-T13 and XR-T14 use the fixtures and the loaded modules of
test_ltx_movie_seed_edit, test_ltx_movie_seed_context and test_ltx_movie_cast_refs, which patch their own copy of
bin/ltx-movie. XR-T18 uses the real qwen_edit with the stub children of tests/test_seed_edit_tool.py. No test loads a
model, renders, contacts a server or touches port 8177 or 8178. Stdlib, PIL and pytest.
"""

import argparse
import glob
import importlib.machinery
import importlib.util
import json
import os
import shutil

import pytest
from PIL import Image

import movie_ui_testutil as mt
import qwen_edit
import test_seed_edit_tool as st
from test_ltx_movie_cast_refs import DOC as cr_DOC
from test_ltx_movie_cast_refs import IMAGES as cr_IMAGES
from test_ltx_movie_cast_refs import _args as cr_args
from test_ltx_movie_cast_refs import _cast as cr_cast
from test_ltx_movie_cast_refs import _prompt as cr_prompt
from test_ltx_movie_cast_refs import _story as cr_story
from test_ltx_movie_cast_refs import cast_env  # noqa: F401
from test_ltx_movie_cast_refs import movie as cr_movie
from test_ltx_movie_seed_context import _args as cx_args
from test_ltx_movie_seed_context import _prompt as cx_prompt
from test_ltx_movie_seed_context import _story as cx_story
from test_ltx_movie_seed_context import ctx_env  # noqa: F401
from test_ltx_movie_seed_context import movie as cx_movie
from test_ltx_movie_seed_edit import PROMPT as se_PROMPT
from test_ltx_movie_seed_edit import _edit_args as se_edit_args
from test_ltx_movie_seed_edit import _files as se_files
from test_ltx_movie_seed_edit import _write_story as se_write_story
from test_ltx_movie_seed_edit import movie as se_movie
from test_ltx_movie_seed_edit import qe_fake  # noqa: F401
from test_ltx_movie_shots_seed import ENTRY_KEYS, PREFIX, UNC, _FakeShotsQwenEdit, _phase_args, _seed1920, _seed_jpeg
from test_ltx_movie_shots_seed import _prompt as sse_prompt
from test_ltx_movie_shots_seed import _sha, _write_story
from test_qwen_edit import _mflux_ready, env  # noqa: F401

WS = mt.WS
AS_IS = ("Error: --extra-ref cannot be combined with --seed-edit-model as-is: the seed is used unedited (with --shots, "
         "the Z-Image engine renders every other still), so no Qwen edit would see the extra references; choose a Qwen "
         "--seed-edit-model ID\n")
NO_EDIT = ("Error: --extra-ref needs a Qwen edit in this run: --seed-image with --seed-edit-model ID (panel 1 in "
           "chained mode, every still with --shots), or --shots with --cast-refs-model ID and at least two cast "
           "characters\n")
LOW_RAM = ("Error: --extra-ref needs --no-low-ram: in low-RAM mode (the default) a Qwen edit takes at most 2 reference "
           "images, so extra references are off; on a host with at least 96 GiB of memory pass --no-low-ram, or set "
           "QWEN_LTX_AUTOTUNE=1 to turn it on there automatically\n")
SENT1 = ("Picture 2, the second input image, shows the sword; Picture 3, the third input image, is one more "
         "reference picture. Use each of them only where the shot below calls for it. ")
M3_HELP = ("an extra reference picture (a location, a prop, a style) for every Qwen edit of the run, after the edit's "
           "own pictures (the seed, the context picture or the two cast stills); repeatable, at most 9, in picture "
           "order. CAPTION (at most 60 characters, no ':') names what it shows, e.g. 'the sword', in the edit prompt. "
           "Needs a Qwen edit (--seed-edit-model ID, or --cast-refs-model) and --no-low-ram, and at most the edit "
           "model's max_references pictures per edit (10 for qwen21, 3 for qwen2511-bf16, 1 for qwen2511-q4). See "
           "docs/superpowers/specs/2026-11-13-extra-reference-images-design.md.")
M1_PARAGRAPH = (
    "Extra references (docs/superpowers/specs/2026-11-13-extra-reference-images-design.md): --extra-ref "
    "PATH[:CAPTION] (repeatable, at most 9) adds the user's pictures (a location, a prop, a style) to every Qwen edit "
    "of the run, after the edit's own pictures (the seed, the context picture or the two cast stills), each named in "
    "the edit prompt by its picture number and caption. It needs --no-low-ram (QWEN_LTX_AUTOTUNE=1 sets it on a host "
    "with at least 96 GiB) and at most the edit model's max_references pictures per edit; a changed extra re-edits "
    "every still that used it.")
HEADER = ("seed edits: %s; 704x448, fitted into 1408x896 stills; seed 3; panels 1,2,3 of 3, each prompted by its own "
          "Image: text")


def _load_movie():
    path = os.path.join(WS, "bin", "ltx-movie")
    loader = importlib.machinery.SourceFileLoader("ltx_movie_xr", path)
    spec = importlib.util.spec_from_loader("ltx_movie_xr", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


movie = _load_movie()


def _xr(fake):
    """Add what the resolver needs to any fixture's fake and return it."""
    fake.max_references = qwen_edit.max_references
    fake.multi_reference_problem = qwen_edit.multi_reference_problem
    fake.MULTI_REFERENCE_MODEL_IDS = qwen_edit.MULTI_REFERENCE_MODEL_IDS
    fake.memory_answer = None
    fake.calls["reference_memory_problem"] = []
    fake.reference_memory_problem = lambda model_id, references: (
        fake.calls["reference_memory_problem"].append((model_id, references)) or fake.memory_answer)
    return fake


@pytest.fixture
def xr_env(monkeypatch, tmp_path):
    """test_ltx_movie_shots_seed's clean_env with _xr(_FakeShotsQwenEdit()), and no autotune variable. Returns
    {"tmp", "fake"}."""
    tmp = str(tmp_path)
    monkeypatch.setenv("HOME", os.path.join(tmp, "home"))
    for key in list(os.environ):
        if key.startswith("SEED_EDIT_"):
            monkeypatch.delenv(key)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", os.path.join(tmp, "hf"))
    monkeypatch.setenv("Z_IMAGE_HF_HOME", os.path.join(tmp, "zi"))
    monkeypatch.delenv("QWEN_LTX_AUTOTUNE", raising=False)
    monkeypatch.delenv("QWEN_LTX_MEM_GIB", raising=False)
    fake = _xr(_FakeShotsQwenEdit())
    monkeypatch.setattr(movie, "_qwen_edit", lambda: fake)
    monkeypatch.setattr(movie, "_story_dir", lambda story_id: os.path.join(tmp, "stories", story_id))
    return {"tmp": tmp, "fake": fake}


def _pic(tmp, name, color, size=(64, 48)):
    path = os.path.join(tmp, "x", "%s.png" % name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def _ns(specs, **overrides):
    values = dict(extra_ref_specs=specs, seed_edit_model="qwen21-q4", cast_refs=None, seed_context=None,
                  seed_edit={"qwen_model": "qwen21-q4", "loras": UNC}, no_low_ram=True, dry_run=True,
                  story_only=False)
    values.update(overrides)
    return argparse.Namespace(**values)


def _extras(tmp, *specs, mod=None):
    """Resolve specs through _resolve_extra_refs (of mod, movie by default) on a seeded Qwen run's namespace;
    returns args.extra_refs."""
    args = _ns(list(specs))
    assert (mod or movie)._resolve_extra_refs(args) == 0
    return args.extra_refs


def _with(prompt, sentence):
    i = prompt.index("The new shot: ")
    return prompt[:i] + sentence + prompt[i:]


# --- XR-T6 (XR2-XR4, XR8, XR9): the refusals ----------------------------------------------------------------

def test_xrt6_the_refusals(xr_env, monkeypatch, capsys):
    tmp, fake = xr_env["tmp"], xr_env["fake"]
    a = _pic(tmp, "a", (200, 0, 0))
    b = _pic(tmp, "b", (0, 200, 0))
    capsys.readouterr()

    def refused(text, specs, **overrides):
        ns = _ns(list(specs), **overrides)
        assert movie._resolve_extra_refs(ns) == 2, text
        captured = capsys.readouterr()
        assert captured.err == text + "\n" and captured.out == "", text
        assert ns.extra_refs == [], text

    monkeypatch.setattr(movie, "_qwen_edit", lambda: pytest.fail("loaded"))
    refused(AS_IS.rstrip("\n"), [a], seed_edit_model="as-is", seed_edit=None)
    refused(NO_EDIT.rstrip("\n"), [a], seed_edit_model=None, seed_edit=None)
    refused(NO_EDIT.rstrip("\n"), [a], seed_edit=None, seed_edit_model=None, cast_refs=None,
            cast_refs_model="qwen21-q4")
    refused(LOW_RAM.rstrip("\n"), [a], no_low_ram=False)
    ten = [_pic(tmp, "t%d" % k, (k * 20, 10, 10)) for k in range(10)]
    refused("Error: --extra-ref is given 10 times; at most 9 extra references are allowed", ten)
    monkeypatch.setattr(movie, "_qwen_edit", lambda: fake)
    nope = os.path.join(tmp, "x", "nope.png")
    for value in (nope, a + ":the sword: ornate"):
        refused("Error: --extra-ref %s: no such image file (the form is PATH or PATH:CAPTION, and a caption cannot "
                "contain ':')" % value, [value])
    for value in (a + ":" + "x" * 61, a + ":the\tsword"):
        refused("Error: --extra-ref %s: the caption must be at most 60 characters with no control characters" % value,
                [value])
    bad = os.path.join(tmp, "x", "bad.png")
    with open(bad, "wb") as f:
        f.write(b"not an image")
    ns = _ns([bad])
    assert movie._resolve_extra_refs(ns) == 2
    captured = capsys.readouterr()
    assert captured.err.startswith("Error: --extra-ref %s: cannot read it as an image (UnidentifiedImageError: " % bad)
    assert captured.out == "" and ns.extra_refs == []
    copy = os.path.join(tmp, "x", "copy_of_a.png")
    shutil.copy(a, copy)
    refused("Error: --extra-ref %s and %s are the same image bytes; give each extra reference once" % (a, copy),
            [a, copy])
    refused("Error: --extra-ref: Qwen-Image-Edit-2511 q4 (Lightning) reads only the first input image, so it takes no "
            "extra references; choose a qwen21 model (up to 9) or qwen2511-bf16 (up to 2)", [a],
            seed_edit={"qwen_model": "qwen2511-q4", "loras": []})
    three = [a, b, _pic(tmp, "c", (0, 0, 200))]
    refused("Error: --extra-ref: Qwen-Image-Edit-2511 bf16 (Lightning, diffusers) takes at most 3 reference images per "
            "edit, and each edit of this run would take 4 (the seed, then 3 extra references); give at most 2 "
            "--extra-ref", three, seed_edit={"qwen_model": "qwen2511-bf16", "loras": []})
    refused("Error: --extra-ref: Qwen-Image-Edit-2511 bf16 (Lightning, diffusers) takes at most 3 reference images per "
            "edit, and each edit of this run would take 4 (the two characters' reference stills, then 2 extra "
            "references); give at most 1 --extra-ref", [a, b],
            cast_refs={"qwen_model": "qwen2511-bf16", "loras": [], "stills": {}})
    nine = [_pic(tmp, "n%d" % k, (k * 20, 50, 10)) for k in range(9)]
    refused("Error: --extra-ref: Qwen-Image-2.1 q4 takes at most 10 reference images per edit, and each edit of this "
            "run would take 11 (the seed and the context picture, then 9 extra references); give at most 8 "
            "--extra-ref", nine, seed_context={"mode": "still", "order": "seed-first"})
    problem = ("Qwen-Image-2.1 q4 with 3 reference images is unavailable: needs a host with at least 22 GiB of memory "
               "(this host has 16.0 GiB)")
    fake.memory_answer = problem
    refused("Error: --extra-ref: " + problem, [a, b], dry_run=False)
    assert fake.calls["reference_memory_problem"] == [("qwen21-q4", 3)]


# --- XR-T7 (XR1, XR2, XR23): the resolved extras ----------------------------------------------------------------

def test_xrt7_the_resolved_extras(xr_env, monkeypatch, capsys):
    tmp, fake = xr_env["tmp"], xr_env["fake"]
    a = _pic(tmp, "a", (200, 0, 0))
    b = _pic(tmp, "b", (0, 200, 0))
    c = _pic(tmp, "c", (0, 0, 200))
    assert _extras(tmp, a + ":  the sword. ", b, c + ":") == [
        {"path": os.path.abspath(a), "caption": "the sword", "sha256": _sha(a), "file": "extra_refs/extra_01.png"},
        {"path": os.path.abspath(b), "caption": None, "sha256": _sha(b), "file": "extra_refs/extra_02.png"},
        {"path": os.path.abspath(c), "caption": None, "sha256": _sha(c), "file": "extra_refs/extra_03.png"}]
    colon = _pic(tmp, "d:e", (10, 20, 30))
    (item,) = _extras(tmp, colon)
    assert item["path"] == os.path.abspath(colon) and item["caption"] is None
    capsys.readouterr()
    monkeypatch.setattr(movie, "_qwen_edit", lambda: pytest.fail("loaded"))
    ns = _ns(None)
    assert movie._resolve_extra_refs(ns) == 0 and ns.extra_refs == []
    monkeypatch.setattr(movie, "_qwen_edit", lambda: fake)
    assert capsys.readouterr().out == ""
    d = _pic(tmp, "d", (90, 90, 0))
    assert len(_extras(tmp, a, b, c)) == 3
    assert capsys.readouterr().out == ""
    assert len(_extras(tmp, a, b, c, d)) == 4
    assert capsys.readouterr().out == (
        "Warning: --extra-ref: each Qwen edit of this run takes up to 5 reference images (the seed, then 4 extra "
        "references); above 4 the edit models are past the 1 to 3 input images they are tuned for, so faces, "
        "clothing and props can blend or drift: check every still\n")
    assert fake.calls["reference_memory_problem"] == []


# --- XR-T8 (XR4): low-RAM mode is read after autotune -----------------------------------------------------------

def _dry_argv(tmp, *extra):
    return ["a narrative", "--story-id", "s1", "--dry-run", "--no-review", "--no-auto-lora", "--shots",
            "--seed-image", _seed1920(tmp), "--seed-edit-model", "qwen21-q4"] + list(extra)


def test_xrt8_low_ram_is_read_after_autotune(xr_env, monkeypatch, capsys):
    tmp, fake = xr_env["tmp"], xr_env["fake"]
    a = _pic(tmp, "a", (200, 0, 0))
    extra = ["--extra-ref", a + ":the sword"]
    extras_dir = os.path.join(tmp, "stories", "s1", "extra_refs")
    capsys.readouterr()
    assert movie.main(_dry_argv(tmp, *extra)) == 2
    captured = capsys.readouterr()
    assert captured.err.splitlines()[-1] == LOW_RAM.rstrip("\n")
    assert fake.calls["run_jobs"] == [] and not os.path.exists(extras_dir)
    assert movie.main(_dry_argv(tmp, *(extra + ["--no-low-ram"]))) == 0
    captured = capsys.readouterr()
    assert "--- Extra references ---" in captured.out.splitlines()
    assert fake.calls["run_jobs"] == [] and not os.path.exists(extras_dir)
    monkeypatch.setenv("QWEN_LTX_AUTOTUNE", "1")
    monkeypatch.setenv("QWEN_LTX_MEM_GIB", "128")
    assert movie.main(_dry_argv(tmp, *extra)) == 0
    captured = capsys.readouterr()
    assert "no_low_ram=True" in captured.err
    assert "--- Extra references ---" in captured.out.splitlines()
    assert fake.calls["run_jobs"] == [] and not os.path.exists(extras_dir)
    monkeypatch.setenv("QWEN_LTX_MEM_GIB", "64")
    assert movie.main(_dry_argv(tmp, *extra)) == 2
    captured = capsys.readouterr()
    assert captured.err.splitlines()[-1] == LOW_RAM.rstrip("\n")
    assert fake.calls["run_jobs"] == [] and not os.path.exists(extras_dir)


# --- XR-T9 (XR5, XR11): the prompt sentence ---------------------------------------------------------------------

def test_xrt9_the_prompt_sentence():
    assert movie.EXTRA_REFS_ANCHOR == "The new shot: "
    assert movie.EXTRA_REFS_ORDINALS == ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth",
                                         "ninth", "tenth")
    assert movie.EXTRA_REFS_NO_CAPTION == "is one more reference picture"
    assert movie.EXTRA_REFS_USE_ONE == ". Use it only where the shot below calls for it. "
    assert movie.EXTRA_REFS_USE_MANY == ". Use each of them only where the shot below calls for it. "
    assert (movie.EXTRA_REFS_MAX, movie.EXTRA_REFS_WARN_ABOVE, movie.EXTRA_REFS_CAPTION_MAX,
            movie.EXTRA_REFS_DIR) == (9, 4, 60, "extra_refs")

    def ns(*captions):
        return argparse.Namespace(extra_refs=[{"path": "p", "caption": c, "sha256": "s", "file": "f"}
                                              for c in captions])

    P = PREFIX + "x"
    assert movie._extra_refs_prompt(ns(), P, 1) is P
    two = ns("the sword", None)
    assert movie._extra_refs_prompt(two, PREFIX + "x", 1) == _with(PREFIX + "x", SENT1)
    assert movie._extra_refs_prompt(two, "A gate.", 1) == SENT1 + "A gate."
    second = movie._extra_refs_prompt(two, PREFIX + "x", 2)
    assert "Picture 3, the third input image, shows the sword; Picture 4, the fourth input image, " in second
    assert movie._extra_refs_prompt(ns("the throne room"), P, 1) == _with(
        P, "Picture 2, the second input image, shows the throne room. Use it only where the shot below calls for it. ")
    cast = cr_prompt(2)
    sentence = ("Picture 3, the third input image, shows the sword; Picture 4, the fourth input image, is one more "
                "reference picture. Use each of them only where the shot below calls for it. ")
    assert "is on the right. " + sentence + "The new shot: " in movie._extra_refs_prompt(two, cast, 2)
    nine = movie._extra_refs_prompt(ns(*([None] * 9)), "The new shot: y", 1)
    assert nine.endswith("Picture 10, the tenth input image, is one more reference picture. Use each of them only "
                         "where the shot below calls for it. The new shot: y")


# --- XR-T10 (XR6, XR7, XR11-XR13): seeded shots with extras -----------------------------------------------------

def _x_pictures(tmp):
    os.makedirs(os.path.join(tmp, "x"), exist_ok=True)
    x1 = _seed_jpeg(os.path.join(tmp, "x", "x1.jpg"), (200, 0, 0))
    x2 = _pic(tmp, "x2", (0, 200, 0))
    return x1, x2


def test_xrt10_seeded_shots_with_extras(xr_env, capsys):
    tmp, fake = xr_env["tmp"], xr_env["fake"]
    story_dir = _write_story(tmp)
    x1, x2 = _x_pictures(tmp)
    args = _phase_args(tmp, extra_refs=_extras(tmp, x1 + ":the sword", x2))
    folder = os.path.join(story_dir, "extra_refs")
    os.makedirs(folder)
    Image.new("RGB", (8, 8), (1, 2, 3)).save(os.path.join(folder, "extra_03.png"))
    capsys.readouterr()
    assert movie._phase2_shots_seed(args) == 0
    original = os.path.join(story_dir, "seed-original.png")
    e1, e2 = os.path.join(folder, "extra_01.png"), os.path.join(folder, "extra_02.png")
    work = os.path.join(story_dir, "seed_edits")
    (call,) = fake.calls["run_jobs"]
    assert call["jobs"] == [{"n": n, "seed": 3, "prompt": _with(sse_prompt(n), SENT1), "source": original,
                             "sources": [original, e1, e2],
                             "stage_path": os.path.join(work, "panel_%02d.pending.png" % n),
                             "output_path": os.path.join(work, "panel_%02d.png" % n)} for n in (1, 2, 3)]
    assert fake.calls["wait_for_memory"] == [(22.0, "Qwen-Image-2.1 q4", "ltx-movie")]
    with Image.open(e1) as img:
        assert (img.format, img.size) == ("PNG", (100, 200))
    with Image.open(e2) as img:
        assert (img.format, img.size) == ("PNG", (64, 48))
    assert not os.path.exists(os.path.join(folder, "extra_03.png"))
    with open(os.path.join(story_dir, "seed_edits.json"), encoding="utf-8") as f:
        record = json.load(f)
    for entry in record["panels"]:
        assert list(entry) == ENTRY_KEYS + ["extras"]
        assert entry["extras"] == [{"file": "extra_refs/extra_01.png", "caption": "the sword", "sha256": _sha(x1)},
                                   {"file": "extra_refs/extra_02.png", "caption": None, "sha256": _sha(x2)}]
    out = capsys.readouterr().out.splitlines()
    assert out == [HEADER % qwen_edit.generator_text("qwen21-q4", UNC),
                   'extra refs: every Qwen edit here also gets 2 extra reference pictures after its own: %s ("the '
                   'sword"); %s (no caption)' % (e1, e2)] + [
        "panel %d -> %s (Qwen edit of the seed, 12.5s)" % (n, os.path.join(story_dir, "images", "panel_%02d.png" % n))
        for n in (1, 2, 3)] + ["seed edits: 3 panel stills written"]


# --- XR-T11 (XR7): reuse and change -----------------------------------------------------------------------------

def test_xrt11_reuse_and_change(xr_env, capsys):
    tmp, fake = xr_env["tmp"], xr_env["fake"]
    story_dir = _write_story(tmp)
    x1, x2 = _x_pictures(tmp)

    def run(extras, **overrides):
        before = len(fake.calls["run_jobs"])
        capsys.readouterr()
        assert movie._phase2_shots_seed(_phase_args(tmp, extra_refs=extras, **overrides)) == 0
        out = capsys.readouterr().out.splitlines()
        new = fake.calls["run_jobs"][before:]
        return out, [[job["n"] for job in call["jobs"]] for call in new], new

    first = _extras(tmp, x1 + ":the sword", x2)
    assert run(first)[1] == [[1, 2, 3]]
    out, jobs, _new = run(_extras(tmp, x1 + ":the sword", x2))
    assert jobs == [] and ("seed edits: every panel's still is a recorded edit of the same seed image, prompt, seed "
                           "and settings; nothing to edit") in out
    assert run(_extras(tmp, x1 + ":the long sword", x2))[1] == [[1, 2, 3]]
    assert len(glob.glob(os.path.join(story_dir, "redo", "*", "images", "panel_0[123].png"))) == 3
    _pic(tmp, "x2", (0, 0, 250))
    assert run(_extras(tmp, x1 + ":the long sword", x2))[1] == [[1, 2, 3]]
    assert run(_extras(tmp, x2, x1 + ":the long sword"))[1] == [[1, 2, 3]]
    only = _extras(tmp, x1 + ":the long sword")
    assert run(only)[1] == [[1, 2, 3]]
    _out, jobs, new = run([])
    assert jobs == [[1, 2, 3]] and all("sources" not in job for job in new[0]["jobs"])
    with open(os.path.join(story_dir, "seed_edits.json"), encoding="utf-8") as f:
        assert all("extras" not in entry for entry in json.load(f)["panels"])
    assert run([])[1] == []
    assert run(only, redo_panels=[2])[1] == [[1, 2, 3]]
    assert run(only, redo_panels=[2])[1] == [[2]]


# --- XR-T12 (XR6, XR7, XR11-XR13): Phase 1c with extras ---------------------------------------------------------

def test_xrt12_phase_1c_with_extras(qe_fake, tmp_path):
    fake = _xr(qe_fake)
    tmp = str(tmp_path)
    x = _pic(tmp, "x", (200, 0, 0))
    story_dir = se_write_story(tmp_path)
    files = se_files(story_dir)
    args = se_edit_args(tmp_path)
    args.extra_refs = _extras(tmp, x + ":the throne room", mod=se_movie)
    assert se_movie.phase_seed_edit(args) == 0
    (call,) = fake.calls["run_jobs"]
    assert call["jobs"] == [{
        "n": 1, "seed": 3,
        "prompt": "Picture 2, the second input image, shows the throne room. Use it only where the shot below calls "
                  "for it. " + se_PROMPT,
        "source": files["original"], "sources": [files["original"], os.path.join(story_dir, "extra_refs",
                                                                                 "extra_01.png")],
        "stage_path": files["stage"], "output_path": files["edited"]}]
    assert fake.calls["wait_for_memory"] == [(20.0, "Qwen-Image-2.1 q4", "ltx-movie")]
    with open(files["record"], encoding="utf-8") as f:
        record = json.load(f)
    assert list(record) == ["schema", "created", "status", "label", "source", "source_sha256", "original", "output",
                            "prompt", "seed", "width", "height", "qwen_model", "loras", "steps", "scheduler",
                            "seconds", "error", "extras"]
    assert se_movie.phase_seed_edit(args) == 0
    assert len(fake.calls["run_jobs"]) == 1
    args.extra_refs = _extras(tmp, x + ":the hall", mod=se_movie)
    assert se_movie.phase_seed_edit(args) == 0
    assert len(fake.calls["run_jobs"]) == 2
    other = se_edit_args(tmp_path, story_id="s2")
    se_write_story(tmp_path, "s2")
    assert se_movie.phase_seed_edit(other) == 0
    assert len(fake.calls["run_jobs"]) == 3 and "sources" not in fake.calls["run_jobs"][2]["jobs"][0]
    other.extra_refs = []
    assert se_movie.phase_seed_edit(other) == 0
    assert len(fake.calls["run_jobs"]) == 3


# --- XR-T13 (XR6, XR7, XR11-XR13): seed context with extras -----------------------------------------------------

def test_xrt13_seed_context_with_extras(ctx_env):
    tmp, fake = ctx_env["tmp"], _xr(ctx_env["fake"])
    x1, x2 = _x_pictures(tmp)
    story_dir = cx_story(tmp)
    args = cx_args(tmp, extra_refs=_extras(tmp, x1 + ":the sword", x2, mod=cx_movie))
    assert cx_movie._phase2_seed_context(args) == 0
    original = os.path.join(story_dir, "seed-original.png")
    e1, e2 = (os.path.join(story_dir, "extra_refs", "extra_%02d.png" % k) for k in (1, 2))
    still = lambda n: os.path.join(story_dir, "images", "panel_%02d.png" % n)   # noqa: E731
    context_sentence = SENT1.replace("Picture 3, the third", "Picture 4, the fourth").replace(
        "Picture 2, the second", "Picture 3, the third")
    jobs = [call["jobs"][0] for call in fake.calls["run_jobs"]]
    assert [(j["n"], j["prompt"], j["sources"]) for j in jobs] == [
        (1, _with(cx_prompt(1), SENT1), [original, e1, e2]),
        (2, _with(cx_prompt(2), context_sentence), [original, still(1), e1, e2]),
        (3, _with(cx_prompt(3), SENT1), [original, e1, e2]),
        (4, _with(cx_prompt(4), context_sentence), [original, still(3), e1, e2])]
    assert [floor for floor, _label, _tag in fake.calls["wait_for_memory"]] == [22.0, 24.0, 22.0, 24.0]
    with open(os.path.join(story_dir, "seed_context_edits.json"), encoding="utf-8") as f:
        assert all(list(entry)[-1] == "extras" for entry in json.load(f)["panels"])
    before = len(fake.calls["run_jobs"])
    assert cx_movie._phase2_seed_context(args) == 0
    assert len(fake.calls["run_jobs"]) == before
    first = cx_args(tmp, extra_refs=args.extra_refs, seed_context={"mode": "still", "order": "context-first"},
                    redo_panels=[2])
    assert cx_movie._phase2_seed_context(first) == 0
    new = [call["jobs"][0] for call in fake.calls["run_jobs"][before:]]
    (two,) = [j for j in new if j["n"] == 2]
    assert two["sources"] == [still(1), original, e1, e2]


# --- XR-T14 (XR6, XR7, XR11-XR13): cast refs with extras --------------------------------------------------------

def test_xrt14_cast_refs_with_extras(cast_env, monkeypatch, capsys):
    tmp, lib, groups = cast_env["tmp"], cast_env["lib"], cast_env["groups"]
    fake = _xr(cast_env["fake"])
    monkeypatch.setattr(cr_movie, "_catalog_stills_flags", lambda args, dry_run=False: (None, []))
    members = cr_cast(lib)
    x = _pic(tmp, "x", (200, 0, 0))
    story_dir = cr_story(tmp)
    args = cr_args(tmp, members, extra_refs=_extras(tmp, x + ":the throne room", mod=cr_movie))
    k00, r00 = (os.path.join(lib, name, "dataset", "stills", "char_00.png") for name in ("kyra", "ronin"))
    e1 = os.path.join(story_dir, "extra_refs", "extra_01.png")
    capsys.readouterr()
    assert cr_movie.phase2_stills(args) == 0
    assert sorted(cmd[cmd.index("--only") + 1] for cmd in groups) == ["1", "3"]
    (call,) = fake.calls["run_jobs"]
    sentence = ("Picture 3, the third input image, shows the throne room. Use it only where the shot below calls for "
                "it. ")
    assert [(j["n"], j["prompt"], j["sources"], j["source"]) for j in call["jobs"]] == [
        (n, _with(cr_prompt(n), sentence), [k00, r00, e1], k00) for n in (2, 4)]
    assert fake.calls["wait_for_memory"][0][0] == 22.0
    with open(os.path.join(story_dir, "cast_ref_edits.json"), encoding="utf-8") as f:
        assert all(list(entry)[-1] == "extras" for entry in json.load(f)["panels"])
    story_two = cr_story(tmp, images=[cr_IMAGES[0], cr_IMAGES[2]], story_id="s2")
    args = cr_args(tmp, members, story_id="s2", extra_refs=_extras(tmp, x + ":the throne room", mod=cr_movie))
    capsys.readouterr()
    assert cr_movie.phase2_stills(args) == 0
    out = capsys.readouterr().out.splitlines()
    i = out.index(cr_movie.CAST_REFS_NONE_NOTE)
    assert out[i + 1] == ("note: --extra-ref: no panel is a cast-reference Qwen edit, so the extra references are not "
                          "used")
    assert len(fake.calls["run_jobs"]) == 1 and not os.path.exists(os.path.join(story_two, "extra_refs"))


# --- XR-T15 (XR6): frame mode writes the copies before its loop -------------------------------------------------

def test_xrt15_frame_mode_writes_the_copies_before_its_loop():
    with open(os.path.join(WS, "bin", "ltx-movie"), encoding="utf-8") as f:
        text = f.read()
    frame = text[text.index("def phase_seed_context_frames(args):"):text.index("def _cast_refs_paths(story_dir):")]
    pin = ('    fit.load_oriented_rgb(args.seed_image).save(files["original"], format="PNG")\n'
           '    _extra_refs_note(args)\n    _extra_refs_write(args)\n'
           '    placeholder = os.path.join(files["work"], "placeholder.png")\n')
    assert frame.count(pin) == 1
    edit = text[text.index("def _seed_context_edit("):text.index("def _seed_context_stop(")]
    assert "    _extra_refs_job(args, job)\n    fit = _image_fit()\n" in edit
    assert "qe.memory_floor(model_id, _edit_references([job]))" in edit


# --- XR-T16 (XR14): the dry run ---------------------------------------------------------------------------------

def test_xrt16_the_dry_run(xr_env, capsys):
    tmp, fake = xr_env["tmp"], xr_env["fake"]
    a = _pic(tmp, "a", (200, 0, 0))
    b = _pic(tmp, "b", (0, 200, 0))
    capsys.readouterr()
    argv = _dry_argv(tmp, "--extra-ref", a + ":the sword", "--extra-ref", b, "--no-low-ram")
    assert movie.main(argv) == 0
    lines = capsys.readouterr().out.splitlines()
    i = lines.index("--- Extra references ---")
    assert lines[i:i + 6] == [
        "--- Extra references ---",
        "Would add 2 extra reference pictures to every Qwen edit of this run with Qwen-Image-2.1 q4, after the edit's "
        "own pictures (the seed), each named in the edit prompt by its picture number and caption; each edit takes up "
        "to 3 of the model's 10 reference images. They are copied into %s when the edits run; a changed picture, "
        "caption, order or count re-edits every still that used it." % os.path.join(tmp, "stories", "s1", "extra_refs"),
        '  extra 1: %s ("the sword")' % a, "  extra 2: %s (no caption)" % b, "", "--- Phase 3: manifest + dry-run ---"]
    assert fake.calls == {"selection_problem": [], "wait_for_memory": [], "run_jobs": [],
                          "reference_memory_problem": []}
    assert not os.path.exists(os.path.join(tmp, "stories", "s1", "extra_refs"))
    assert movie.main(_dry_argv(tmp)) == 0
    assert "--- Extra references ---" not in capsys.readouterr().out


# --- XR-T17 (XR1, XR15): the help text and the docstring --------------------------------------------------------

def test_xrt17_help_and_docstring():
    (action,) = [a for a in movie.build_parser()._actions if "--extra-ref" in a.option_strings]
    assert (action.help, action.dest, action.metavar, action.default) == (
        M3_HELP, "extra_ref_specs", "PATH[:CAPTION]", None)
    doc = " ".join(movie.__doc__.split())
    assert M1_PARAGRAPH + " Seed context (docs/" in doc
    assert doc.endswith(" ".join(cr_DOC.split()))
    with open(os.path.join(WS, "bin", "ltx-movie"), encoding="utf-8") as f:
        assert "\nimport re\n" not in f.read()


# --- XR-T18 (XR8, XR10): the real runner ------------------------------------------------------------------------

def test_xrt18_the_real_runner(env):
    py, _snapshot, _lora = _mflux_ready(env)
    tmp, mp = env["tmp"], env["mp"]
    mp.setattr(movie, "_qwen_edit", lambda: qwen_edit)
    mp.setattr(movie, "_story_dir", lambda story_id: os.path.join(tmp, "stories", story_id))
    seen, real = [], qwen_edit.run_child

    def spy(argv, child_env, on_line, timeout_s, log_path=None):
        seen.append(timeout_s)
        return real(argv, child_env, on_line, timeout_s, log_path)

    mp.setattr(qwen_edit, "run_child", spy)
    story_dir = _write_story(tmp)
    x1, x2 = _x_pictures(tmp)
    args = _phase_args(tmp, extra_refs=_extras(tmp, x1 + ":the sword", x2))
    assert movie._phase2_shots_seed(args) == 0
    (call,) = st.stub_calls(py)
    original = os.path.join(story_dir, "seed-original.png")
    e1, e2 = (os.path.join(story_dir, "extra_refs", "extra_%02d.png" % k) for k in (1, 2))
    assert [(j["n"], j["sources"]) for j in call["spec"]["jobs"]] == [(n, [original, e1, e2]) for n in (1, 2, 3)]
    assert seen == [16200]
    assert env["calls"]["safety"] == [{"skill": "ltx_movie_shots_seed_edit", "prompt": _with(sse_prompt(n), SENT1),
                                       "size": (704, 448)} for n in (1, 2, 3)]
    with open(os.path.join(story_dir, "seed_edits.json"), encoding="utf-8") as f:
        assert all("extras" in entry for entry in json.load(f)["panels"])
