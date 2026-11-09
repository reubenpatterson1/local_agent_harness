"""Tests for bin/ltx-movie's --cast-refs-model (docs/superpowers/specs/2026-11-09-shots-multi-reference-stills-
design.md, CR4-CR13: CRT7-CRT18): in shots mode without a seed image, every panel whose Image: names two cast
characters is one Qwen edit with both characters' reference stills as its sources, in one batch, screened,
fitted, recorded in cast_ref_edits.json and reused on a rerun; every other panel keeps the Z-Image stills groups.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_ltx_movie_cast_refs.py

bin/ltx-movie is loaded with SourceFileLoader, spec_from_loader, module_from_spec and exec_module as
ltx_movie_crf. The cast_env fixture is story_engine_testutil.set_story_env (a temporary HOME and character
library) plus HF_HOME and Z_IMAGE_HF_HOME under tmp_path, no HF_HUB_CACHE and no SEED_EDIT_* variable; it patches
_story_dir to <tmp>/stories/<id>, _qwen_edit to a recording fake, and _stream_and_tee (the Z-Image stills group
runs) to a recorder that writes a still for every --only panel. CRT18 uses the real qwen_edit with the stub
children of tests/test_seed_edit_tool.py. No test loads a model, renders, contacts a server or touches port 8177
or 8178. Stdlib, PIL and pytest.
"""

import argparse
import glob
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import shutil

import pytest
from PIL import Image

import movie_ui_testutil as mt
import qwen_edit
import story_engine_testutil as seu
import test_seed_edit_tool as st
from test_ltx_movie_shots_seed import PANEL_QWENEDIT_STUB, _FakeShotsQwenEdit
from test_qwen_edit import _bf16_cache, _mflux_ready, env  # noqa: F401

WS = mt.WS
UNC = [{"id": "uncensored", "scale": 1.0}]
KYRA, RONIN = "the woman in grey", "the ronin"
STYLE = "Muted teal colour."
IMAGES = ["The woman in grey stands at the temple gate in the rain.",
          "The woman in grey stands on the left of the frame facing right toward the ronin. The ronin stands on the "
          "right of the frame and faces left.",
          "The ronin kneels by the stone well.",
          "The ronin and the woman in grey stand center-frame facing each other."]
PREFIX = ("Make one new film still that shows two different people together. Picture 1, the first input image, "
          "shows the woman in grey, and Picture 2, the second input image, shows the ronin. The woman in grey keeps "
          "exactly the face, hair, skin tone, build and clothing from Picture 1, and the ronin keeps exactly the "
          "face, hair, skin tone, build and clothing from Picture 2; never swap or mix their faces, colours or "
          "clothing. Take only these two people from the pictures, not their pose, background, lighting or "
          "framing. ")
POSITION = "In the new shot the woman in grey is on the left of the frame and the ronin is on the right. "
ENTRY_KEYS = ["n", "status", "created", "label", "sources", "source_paths", "prompt", "seed", "width", "height",
              "still_width", "still_height", "qwen_model", "loras", "steps", "scheduler", "output", "still",
              "still_sha256", "seconds", "error"]
LORA_NOTE = ("note: Z-Image stills LoRAs (character, location, catalog and --stills-lora) do not apply to the "
             "cast-reference panels %s: they are Qwen edits of the two characters' reference stills; every other "
             "panel keeps its Z-Image stills LoRAs")


def _load_movie():
    path = os.path.join(WS, "bin", "ltx-movie")
    loader = importlib.machinery.SourceFileLoader("ltx_movie_crf", path)
    spec = importlib.util.spec_from_loader("ltx_movie_crf", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


movie = _load_movie()


def _prompt(n, images=IMAGES):
    return PREFIX + ("The new shot: " if n != 2 else POSITION + "The new shot: ") + images[n - 1] + " " + STYLE


class _FakeCastRefsQwenEdit(_FakeShotsQwenEdit):
    """test_ltx_movie_shots_seed's multi-job fake, plus the multi-reference table of the real qwen_edit; run_jobs
    also records log_path."""
    MULTI_REFERENCE_MODEL_IDS = qwen_edit.MULTI_REFERENCE_MODEL_IDS

    def __init__(self):
        _FakeShotsQwenEdit.__init__(self)
        self.multi_reference_problem = qwen_edit.multi_reference_problem
        self.logs = []

    def run_jobs(self, model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None,
                 noun="job"):
        self.logs.append(log_path)
        return _FakeShotsQwenEdit.run_jobs(self, model_id, loras, jobs, width, height, skill, work_dir,
                                           on_result=on_result, noun=noun)


@pytest.fixture
def cast_env(monkeypatch, tmp_path):
    """The module docstring's environment. Returns {"tmp", "lib", "fake", "groups"}; groups records every Z-Image
    group command and returns groups_rc (a list holding one int)."""
    tmp = str(tmp_path)
    story_env = seu.set_story_env(monkeypatch, tmp_path)
    for key in list(os.environ):
        if key.startswith("SEED_EDIT_"):
            monkeypatch.delenv(key)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", os.path.join(tmp, "hf"))
    monkeypatch.setenv("Z_IMAGE_HF_HOME", os.path.join(tmp, "zi"))
    fake = _FakeCastRefsQwenEdit()
    monkeypatch.setattr(movie, "_qwen_edit", lambda: fake)
    monkeypatch.setattr(movie, "_story_dir", lambda story_id: os.path.join(tmp, "stories", story_id))
    groups, groups_rc = [], [0]

    def stream(cmd, log_path):
        groups.append(list(cmd))
        out = cmd[cmd.index("--out-dir") + 1]
        size = (int(cmd[cmd.index("--width") + 1]), int(cmd[cmd.index("--height") + 1]))
        os.makedirs(out, exist_ok=True)
        for n in cmd[cmd.index("--only") + 1].split(","):
            Image.new("RGB", size, (200, 0, 0)).save(os.path.join(out, "panel_%02d.png" % int(n)))
        return groups_rc[0]

    monkeypatch.setattr(movie, "_stream_and_tee", stream)
    return {"tmp": tmp, "lib": story_env["lib"], "fake": fake, "groups": groups, "groups_rc": groups_rc}


def _character_still(lib, name, filename, color, size=(1024, 640)):
    path = os.path.join(lib, name, "dataset", "stills", filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def _manifest(lib, name, item9):
    path = os.path.join(lib, name, "dataset", "manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"reference": "char_00", "items": [{"n": 1, "kept": True, "gen_prompt": "Close-up of x"}, item9]},
                  f)


def _cast(lib, names=("kyra", "ronin"), stills=True):
    """Trained kyra and ronin (and a third, monk, when named) with a char_00 reference still each (distinct colours)
    unless stills is False; returns the resolved CastMember list in names order."""
    makers = {"kyra": seu.kyra, "ronin": seu.ronin,
              "monk": lambda d: seu.make_character(d, "monk", "monkmn", "the old monk", "man", seu.MONK)}
    for i, name in enumerate(names):
        makers[name](lib)
        if stills:
            _character_still(lib, name, "char_00.png", (10 + 40 * i, 20, 30))
    return movie._character_lib().resolve_cast([(None, name) for name in names])


def _story(tmp, images=IMAGES, story_id="s1", style=STYLE):
    story_dir = os.path.join(tmp, "stories", story_id)
    os.makedirs(story_dir, exist_ok=True)
    lines = ["# The gate", "", "Two strangers meet at a temple gate.", "", "## Characters",
             '- "the woman in grey": %s.' % seu.DESC_K, '- "the ronin": %s.' % seu.DESC_R, ""]
    for n, image in enumerate(images, start=1):
        lines += ["## Panel %d — Shot %d" % (n, n), "Image: %s" % image]
        if n == 1 and style:
            lines.append("Style: %s" % style)
        lines += ["Motion: The ronin turns his head. The camera stays static.", "Narration: Rain falls.", ""]
    with open(os.path.join(story_dir, "story.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return story_dir


def _args(tmp, members, stills=None, **overrides):
    """Phase args of a shots run of story s1 at 704x448 (stills 1408x896), image seed 3, qwen21-q4 + uncensored."""
    lib = movie._character_lib()
    stills = stills or dict((m.name, os.path.join(lib.character_dir(m.name), "dataset", "stills", "char_00.png"))
                            for m in members)
    values = dict(story_id="s1", seed_image=None, video_width=704, video_height=448, image_seed=3, shots=True,
                  redo_panels=[], cast_members=members, character_strength=0.8, location_pins=[],
                  story_engine="robust", no_auto_lora=True, panels=4, force_story=False, global_stills_loras=[],
                  stills_lora_path=None, cast_refs={"qwen_model": "qwen21-q4", "loras": UNC, "stills": stills})
    values.update(overrides)
    return argparse.Namespace(**values)


def _record(story_dir):
    with open(os.path.join(story_dir, "cast_ref_edits.json"), encoding="utf-8") as f:
        return json.load(f)


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _still(story_dir, n):
    return os.path.join(story_dir, "images", "panel_%02d.png" % n)


def _only(groups):
    return [cmd[cmd.index("--only") + 1] for cmd in groups]


# --- CRT7 (CR4): the option rules --------------------------------------------------------------------------------

def _parse(*extra):
    args = movie.build_parser().parse_args(["a narrative", "--story-id", "s1"] + list(extra))
    args.cast_members = []
    return args


def test_crt7_the_option_rules(cast_env, capsys, monkeypatch):
    tmp, lib, fake = cast_env["tmp"], cast_env["lib"], cast_env["fake"]
    seed = st.png(os.path.join(tmp, "seed.png"), (64, 64))
    args = _parse()
    assert (args.cast_refs_model, args.cast_refs_loras) == (None, None)
    assert movie._resolve_cast_refs(args) == 0 and args.cast_refs is None
    assert capsys.readouterr() == ("", "")
    cases = [(("--cast-refs-lora", "uncensored=1"),
              "Error: --cast-refs-lora needs --cast-refs-model\n"),
             (("--cast-refs-model", "qwen21-q4"),
              "Error: --cast-refs-model needs --shots: it renders the shots stills that show two cast characters\n"),
             (("--cast-refs-model", "qwen21-q4", "--no-stills"),
              "Error: --cast-refs-model needs --shots: it renders the shots stills that show two cast characters\n"),
             (("--shots", "--seed-image", seed, "--cast-refs-model", "qwen21-q4"),
              "Error: --cast-refs-model cannot be combined with --seed-image: with a seed image every shots still is "
              "already a Qwen edit of the seed\n"),
             (("--shots", "--cast-refs-model", "as-is"),
              "Error: --cast-refs-model must be one of qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-bf16\n"),
             (("--shots", "--cast-refs-model", "qwen2511-q4"),
              "Error: --cast-refs-model qwen2511-q4 is refused: " + qwen_edit.MULTI_REFERENCE_REFUSED["qwen2511-q4"]
              + "\n"),
             (("--shots", "--cast-refs-model", "qwen21-q4", "--cast-refs-lora", "x=1"),
              "Error: --cast-refs-lora: unknown LoRA x; known: uncensored, viggle-turbo\n")]
    for extra, text in cases:
        args = _parse(*extra)
        assert movie._resolve_cast_refs(args) == 2, extra
        assert capsys.readouterr() == ("", text), extra
        assert args.cast_refs is None
    assert movie.main(["n", "--story-id", "s1", "--shots", "--no-stills", "--cast-refs-model", "qwen21-q4",
                       "--dry-run"]) == 2
    assert capsys.readouterr().err == ("Error: --shots needs Phase 2's per-panel stills; it cannot be combined with "
                                       "--no-stills\n")
    members = _cast(lib)
    args = _parse("--shots", "--cast-refs-model", "qwen21-q4")
    args.cast_members = members[:1]
    assert movie._resolve_cast_refs(args) == 0 and args.cast_refs is None
    assert capsys.readouterr() == (
        "note: --cast-refs-model has no effect: it needs at least two cast characters (--character or --cast), and "
        "this run casts 1; every still is a Z-Image still\n", "")
    args = _parse("--shots", "--cast-refs-model", "qwen21-q4", "--cast-refs-lora", "uncensored=1", "--dry-run")
    args.cast_members = members
    assert movie._resolve_cast_refs(args) == 0
    k00, r00 = (os.path.join(lib, name, "dataset", "stills", "char_00.png") for name in ("kyra", "ronin"))
    assert args.cast_refs == {"qwen_model": "qwen21-q4", "loras": UNC, "stills": {"kyra": k00, "ronin": r00}}
    out = capsys.readouterr().out.splitlines()
    assert out == ["note: --cast-refs-model: character %s has no kept medium-shot dataset still (char_09.png); its "
                   "reference still %s is used, which may show only the head and shoulders, so its clothing rests "
                   "on the Image: text" % (name, path) for name, path in (("kyra", k00), ("ronin", r00))]
    assert fake.calls["selection_problem"] == []
    monkeypatch.setattr(fake, "selection_problem", lambda model_id, loras: fake.calls["selection_problem"].append(
        (model_id, loras)) or "Qwen-Image-2.1 q4 is unavailable: no mflux venv")
    args = _parse("--shots", "--cast-refs-model", "qwen21-q4", "--cast-refs-lora", "uncensored=1")
    args.cast_members = members
    assert movie._resolve_cast_refs(args) == 2 and args.cast_refs is None
    assert capsys.readouterr().err == ("Error: --cast-refs-model qwen21-q4: Qwen-Image-2.1 q4 is unavailable: no "
                                       "mflux venv\n")
    assert fake.calls["selection_problem"] == [("qwen21-q4", UNC)]
    os.remove(r00)
    args = _parse("--shots", "--cast-refs-model", "qwen21-q4", "--dry-run")
    args.cast_members = members
    assert movie._resolve_cast_refs(args) == 2
    assert capsys.readouterr().err == (
        "Error: --cast-refs-model: character ronin has no reference still (looked for %s); rebuild its dataset with "
        "bin/character create ronin --regenerate\n" % r00)
    shutil.copyfile(k00, r00)
    assert movie._resolve_cast_refs(args) == 2
    assert capsys.readouterr().err == (
        "Error: --cast-refs-model: characters kyra and ronin have the same reference still bytes (%s); each picture "
        "must show a different person\n" % r00)
    monkeypatch.setattr(movie, "WS", tmp)
    assert movie._resolve_cast_refs(args) == 2
    assert capsys.readouterr().err == ("Error: --cast-refs-model needs %s, which this workspace does not have\n"
                                       % os.path.join(tmp, "qwen_edit.py"))


# --- CRT8 (CR6): the reference picture: the kept medium-shot still, else the dataset reference ---------------

def test_crt8_the_reference_picture(cast_env, capsys):
    lib = cast_env["lib"]
    kyra = _cast(lib, names=("kyra",))[0]
    k00 = os.path.join(lib, "kyra", "dataset", "stills", "char_00.png")
    k09 = _character_still(lib, "kyra", "char_09.png", (0, 0, 250))
    standing = {"n": 9, "kept": True, "gen_prompt": "Medium shot of a woman, standing with arms relaxed, in a studio"}
    edit = {"n": 9, "kept": True, "gen_prompt": "Show this exact same person ... Re-shoot them as a medium shot, "
                                                "standing with arms relaxed, in a studio with a plain grey backdrop."}
    for item9 in (standing, edit):
        _manifest(lib, "kyra", item9)
        assert movie._cast_ref_still(kyra) == (k09, None)
        assert capsys.readouterr() == ("", "")
    for item9 in (dict(standing, kept=False), dict(standing, gen_prompt="Close-up of a woman, in profile facing right"),
                  dict(standing, n=17), "not an item"):
        _manifest(lib, "kyra", item9)
        assert movie._cast_ref_still(kyra) == (k00, None), item9
        assert "has no kept medium-shot dataset still (char_09.png)" in capsys.readouterr().out
    _manifest(lib, "kyra", standing)
    os.remove(k09)
    assert movie._cast_ref_still(kyra) == (k00, None)
    with open(os.path.join(lib, "kyra", "dataset", "manifest.json"), "w", encoding="utf-8") as f:
        f.write("[1, 2]")
    assert movie._cast_ref_still(kyra) == (k00, None)
    os.remove(k00)
    assert movie._cast_ref_still(kyra) == (None, "character kyra has no reference still (looked for %s); rebuild its "
                                                 "dataset with bin/character create kyra --regenerate" % k00)


# --- CRT9 (CR8): the left/right reading and the prompt -----------------------------------------------------

FIGHT7 = ("The setting is a neon street. The ronin is a lean man wearing a faded indigo haori. The ronin stands left "
          "of center, sword raised, facing right toward the green ogre who is partially visible on the right edge of "
          "the frame, blocking with a fist. The shot is a medium close-up.")


def test_crt9_the_left_right_reading_and_the_prompt(cast_env):
    lib = movie._character_lib()
    side = movie._cast_refs_side
    assert (side(lib, FIGHT7, "the green ogre", "the ronin"), side(lib, FIGHT7, "the ronin", "the green ogre")) == (
        "right", "left")
    assert (side(lib, IMAGES[1], KYRA, RONIN), side(lib, IMAGES[1], RONIN, KYRA)) == ("left", "right")
    for text in (IMAGES[3], "The ronin walks left to right past the woman in grey.",
                 "The ronin stands on the left and turns to the right edge of the road; the woman in grey waits.",
                 "The ronin faces left. The woman in grey faces right."):
        assert side(lib, text, RONIN, KYRA) is None, text
    assert side(lib, "The ronin stands center-left. The woman in grey stands centre right.", RONIN, KYRA) == "left"
    assert side(lib, "The ronin stands center-left. The woman in grey stands centre right.", KYRA, RONIN) == "right"
    members = _cast(cast_env["lib"])
    assert movie._cast_refs_prompt(lib, members, IMAGES[1]) == PREFIX + POSITION + "The new shot: " + IMAGES[1]
    assert movie._cast_refs_prompt(lib, members, IMAGES[3]) == PREFIX + "The new shot: " + IMAGES[3]
    assert movie._cast_refs_prompt(lib, members[::-1], IMAGES[1]).startswith(
        "Make one new film still that shows two different people together. Picture 1, the first input image, shows "
        "the ronin, and Picture 2, the second input image, shows the woman in grey. The ronin keeps exactly")
    assert ("In the new shot the ronin is on the right of the frame and the woman in grey is on the left. The new "
            "shot: ") in movie._cast_refs_prompt(lib, members[::-1], IMAGES[1])


# --- CRT10 (CR9): the plan: which panels, in what order, with what key --------------------------------------

def test_crt10_the_plan(cast_env, capsys):
    tmp, lib, fake = cast_env["tmp"], cast_env["lib"], cast_env["fake"]
    members = _cast(lib)
    story_dir = _story(tmp)
    error, plan = movie._cast_refs_plan(_args(tmp, members), fake)
    assert error is None
    assert dict((n, [m.name for m in pair]) for n, pair in plan["pairs"].items()) == {2: ["kyra", "ronin"],
                                                                                      4: ["kyra", "ronin"]}
    assert plan["prompts"] == {2: _prompt(2), 4: _prompt(4)}
    assert (plan["size"], plan["still"], plan["todo"], plan["reuse"], plan["total"]) == (
        (1408, 896), (1408, 896), [2, 4], [], 4)
    k00, r00 = (os.path.join(lib, name, "dataset", "stills", "char_00.png") for name in ("kyra", "ronin"))
    assert plan["keys"][2] == dict(qwen_edit.settings("qwen21-q4", UNC),
                                   sources=[{"name": "kyra", "still": "char_00.png", "sha256": _sha(k00)},
                                            {"name": "ronin", "still": "char_00.png", "sha256": _sha(r00)}],
                                   prompt=_prompt(2), seed=3, width=1408, height=896, still_width=1408,
                                   still_height=896)
    reversed_cast = movie._character_lib().resolve_cast([(None, "ronin"), (None, "kyra")])
    _error, plan = movie._cast_refs_plan(_args(tmp, reversed_cast), fake)
    assert [m.name for m in plan["pairs"][2]] == ["ronin", "kyra"]
    three = _cast(lib, names=("kyra", "ronin", "monk"))
    _story(tmp, images=IMAGES[:3] + ["The ronin, the woman in grey and the old monk share tea."])
    error, plan = movie._cast_refs_plan(_args(tmp, three), fake)
    assert (error, plan) == ("panel 4 of %s names 3 cast characters (kyra, monk, ronin); --cast-refs-model takes "
                             "exactly two per panel" % os.path.join(story_dir, "story.md"), None)
    with open(os.path.join(story_dir, "story.md"), "w", encoding="utf-8") as f:
        f.write("# Empty\n")
    assert movie._cast_refs_plan(_args(tmp, members), fake) == ("%s has no panels" % os.path.join(story_dir,
                                                                                                    "story.md"), None)


# --- CRT11 (CR10, CR11): Phase 2: Z-Image groups without the cast-reference panels, then one Qwen batch ------

def test_crt11_phase_2_splits_the_panels(cast_env, capsys):
    tmp, lib, fake, groups = cast_env["tmp"], cast_env["lib"], cast_env["fake"], cast_env["groups"]
    members = _cast(lib)
    story_dir = _story(tmp)
    k00, r00 = (os.path.join(lib, name, "dataset", "stills", "char_00.png") for name in ("kyra", "ronin"))
    assert movie.phase2_stills(_args(tmp, members)) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[:2] == ["=== Phase 2: stills ===", LORA_NOTE % "2,4"]
    assert sorted(_only(groups)) == ["1", "3"] and all("--shots" in cmd for cmd in groups)
    (call,) = fake.calls["run_jobs"]
    work = os.path.join(story_dir, "cast_ref_edits")
    assert (call["model_id"], call["loras"], call["size"], call["skill"], call["work_dir"], call["noun"]) == (
        "qwen21-q4", UNC, (1408, 896), "ltx_movie_cast_ref_edit", work, "panel")
    assert fake.logs == [os.path.join(work, "child.log")]
    assert call["jobs"] == [{"n": n, "seed": 3, "prompt": _prompt(n), "source": k00, "sources": [k00, r00],
                             "stage_path": os.path.join(work, "panel_%02d.pending.png" % n),
                             "output_path": os.path.join(work, "panel_%02d.png" % n)} for n in (2, 4)]
    assert fake.calls["wait_for_memory"] == [(20.0, "Qwen-Image-2.1 q4", "ltx-movie")]
    for n in (1, 2, 3, 4):
        with Image.open(_still(story_dir, n)) as img:
            assert img.size == (1408, 896)
            assert img.getpixel((5, 5)) == ((200, 0, 0) if n in (1, 3) else (0, 0, 40 * n))
    record = _record(story_dir)
    assert record["schema"] == "ltx-movie.cast-ref-edits.v1"
    assert [list(e) for e in record["panels"]] == [ENTRY_KEYS, ENTRY_KEYS]
    for entry, n in zip(record["panels"], (2, 4)):
        assert (entry["n"], entry["status"], entry["label"], entry["prompt"], entry["seed"], entry["output"],
                entry["still"], entry["still_sha256"], entry["seconds"], entry["error"]) == (
            n, "ok", "Qwen-Image-2.1 q4", _prompt(n), 3, "cast_ref_edits/panel_%02d.png" % n,
            "images/panel_%02d.png" % n, _sha(_still(story_dir, n)), 12.5, None)
        assert entry["sources"] == [{"name": "kyra", "still": "char_00.png", "sha256": _sha(k00)},
                                    {"name": "ronin", "still": "char_00.png", "sha256": _sha(r00)}]
        assert entry["source_paths"] == [k00, r00]
    assert "cast refs: panel 2: Picture 1 kyra (%s), Picture 2 ronin (%s)" % (k00, r00) in out
    assert out[-3:] == ["panel 2 -> %s (cast-reference Qwen edit, 12.5s)" % _still(story_dir, 2),
                        "panel 4 -> %s (cast-reference Qwen edit, 12.5s)" % _still(story_dir, 4),
                        "cast refs: 2 panel stills written"]


# --- CRT12 (CR9): a rerun edits exactly the changed panels --------------------------------------------------

def test_crt12_a_rerun_edits_exactly_the_changed_panels(cast_env, capsys):
    tmp, lib, fake, groups = cast_env["tmp"], cast_env["lib"], cast_env["fake"], cast_env["groups"]
    members = _cast(lib)
    story_dir = _story(tmp)
    assert movie.phase2_stills(_args(tmp, members)) == 0
    capsys.readouterr()
    assert movie.phase2_stills(_args(tmp, members)) == 0
    out = capsys.readouterr().out
    assert len(fake.calls["run_jobs"]) == 1 and len(fake.calls["wait_for_memory"]) == 1 and len(groups) == 2
    assert ("cast refs: reusing the stills of panels 2,4 (recorded edits of the same pictures, prompt, seed and "
            "settings)\ncast refs: every cast-reference panel's still is a recorded edit of the same pictures, "
            "prompt, seed and settings; nothing to edit\n") in out
    _story(tmp, images=IMAGES[:3] + [IMAGES[3] + " Lanterns glow."])
    assert movie.phase2_stills(_args(tmp, members)) == 0
    assert [[j["n"] for j in c["jobs"]] for c in fake.calls["run_jobs"]] == [[2, 4], [4]]
    (moved,) = glob.glob(os.path.join(story_dir, "redo", "*", "images", "panel_04.png"))
    assert "cast refs: moved %s -> %s (not a recorded cast-reference edit" % (_still(story_dir, 4), moved) in (
        capsys.readouterr().out)
    assert movie.phase2_stills(_args(tmp, members, redo_panels=[2])) == 0
    assert [j["n"] for j in fake.calls["run_jobs"][-1]["jobs"]] == [2]
    _character_still(lib, "ronin", "char_00.png", (99, 99, 99))
    assert movie.phase2_stills(_args(tmp, members)) == 0
    assert [j["n"] for j in fake.calls["run_jobs"][-1]["jobs"]] == [2, 4]
    q8 = dict(_args(tmp, members).cast_refs, qwen_model="qwen21-q8", loras=[])
    assert movie.phase2_stills(_args(tmp, members, cast_refs=q8)) == 0
    assert [j["n"] for j in fake.calls["run_jobs"][-1]["jobs"]] == [2, 4]
    Image.new("RGB", (1408, 896), (1, 2, 3)).save(_still(story_dir, 2))
    assert movie.phase2_stills(_args(tmp, members, cast_refs=q8)) == 0
    assert [j["n"] for j in fake.calls["run_jobs"][-1]["jobs"]] == [2]
    assert len(groups) == 2


# --- CRT13 (CR10): a blocked or failed panel fails the phase after the batch; no Z-Image fallback ---------------

def test_crt13_blocked_and_failed_panels(cast_env, capsys):
    tmp, lib, fake, groups = cast_env["tmp"], cast_env["lib"], cast_env["fake"], cast_env["groups"]
    members = _cast(lib)
    story_dir = _story(tmp)
    fake.outcomes = {4: "blocked"}
    assert movie.phase2_stills(_args(tmp, members)) == 1
    assert capsys.readouterr().err == (
        "Error: the content screen blocked the cast-reference Qwen edit (Qwen-Image-2.1 q4) of panels 4 of story s1; "
        "the movie stops here rather than use an unscreened or Z-Image still. Change those panels' Image: lines in "
        "%s, then rerun: every other panel's still is reused\n" % os.path.join(story_dir, "story.md"))
    assert [os.path.isfile(_still(story_dir, n)) for n in (1, 2, 3, 4)] == [True, True, True, False]
    assert sorted(_only(groups)) == ["1", "3"]
    assert [(e["n"], e["status"], e["still"]) for e in _record(story_dir)["panels"]] == [
        (2, "ok", "images/panel_02.png"), (4, "blocked", None)]
    fake.reset()
    fake.outcomes, fake.failure = {4: "stop"}, "Qwen-Image-2.1 q4 child timed out after 7200 s"
    assert movie.phase2_stills(_args(tmp, members)) == 1
    assert capsys.readouterr().err == ("Error: the cast-reference edits failed: Qwen-Image-2.1 q4 child timed out "
                                       "after 7200 s (kept: 2; edited on the next run: 4)\n")
    assert [(e["n"], e["status"], e["error"]) for e in _record(story_dir)["panels"]] == [
        (2, "ok", None), (4, "failed", "Qwen-Image-2.1 q4 child timed out after 7200 s")]
    assert not os.path.exists(_still(story_dir, 4))
    fake.reset()
    fake.wait_error = qwen_edit.Unavailable("only 3.0 GiB available after waiting 600 s; Qwen-Image-2.1 q4 needs 20 "
                                            "GiB; free memory and retry")
    assert movie.phase2_stills(_args(tmp, members)) == 1
    assert "Error: the cast-reference edits failed: only 3.0 GiB" in capsys.readouterr().err
    fake.reset()
    os.remove(_still(story_dir, 1))
    cast_env["groups_rc"][0] = 1
    assert movie.phase2_stills(_args(tmp, members)) == 1
    assert "Error: ltx-story-images exited nonzero for 1 of 2 stills groups:" in capsys.readouterr().err
    assert [j["n"] for j in fake.calls["run_jobs"][-1]["jobs"]] == [4]
    assert os.path.isfile(_still(story_dir, 4))


# --- CRT14 (CR10): no two-character panel means the plain Z-Image Phase 2 ------------------------------------

def test_crt14_no_cast_reference_panel(cast_env, capsys):
    tmp, lib, fake, groups = cast_env["tmp"], cast_env["lib"], cast_env["fake"], cast_env["groups"]
    members = _cast(lib)
    story_dir = _story(tmp, images=[IMAGES[0], IMAGES[2], IMAGES[0], IMAGES[2]])
    assert movie.phase2_stills(_args(tmp, members)) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[:2] == ["=== Phase 2: stills ===", "note: cast refs: no panel's Image: names two cast characters; "
                                                  "every still is a Z-Image still"]
    assert sorted(_only(groups)) == ["1,3", "2,4"]
    assert fake.calls["run_jobs"] == [] and not os.path.exists(os.path.join(story_dir, "cast_ref_edits.json"))


# --- CRT15 (CR14): without the flag, Phase 2 and the record helpers are unchanged ------------------------------

def test_crt15_without_the_flag_nothing_changes(cast_env, capsys, monkeypatch):
    tmp, lib, fake, groups = cast_env["tmp"], cast_env["lib"], cast_env["fake"], cast_env["groups"]
    members = _cast(lib)
    story_dir = _story(tmp)
    seen = []
    real = movie._phase2_shots
    monkeypatch.setattr(movie, "_phase2_shots", lambda *a, **k: seen.append((len(a), k)) or real(*a, **k))
    assert movie.phase2_stills(_args(tmp, members, cast_refs=None)) == 0
    assert seen == [(2, {})]
    assert sorted(_only(groups)) == ["1", "2,4", "3"]
    assert fake.calls == {"selection_problem": [], "wait_for_memory": [], "run_jobs": []}
    assert not os.path.exists(os.path.join(story_dir, "cast_ref_edits"))
    built = [(("kyra",), [1]), (("kyra", "ronin"), [2, 4])]
    assert movie._exclude_groups(built, ()) is built
    assert movie._exclude_groups(built, [2]) == [(("kyra",), [1]), (("kyra", "ronin"), [4])]
    assert movie._exclude_groups(built, [2, 4]) == [(("kyra",), [1])]
    path = os.path.join(tmp, "r.json")
    movie._write_shots_seed_record(path, {1: {"n": 1}}, 3)
    assert movie._shots_seed_entries(path) == {1: {"n": 1}} and movie._shots_seed_entries(
        path, movie.CAST_REFS_SCHEMA) == {}
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["schema"] == "ltx-movie.seed-edits.v1"


# --- CRT16 (CR12): the dry run ----------------------------------------------------------------------------------

def _dry(capsys, *extra):
    rc = movie.main(["a narrative", "--story-id", "s1", "--dry-run", "--no-review", "--no-auto-lora", "--shots",
                     "--panels", "4", "--character", "kyra", "--character", "ronin"] + list(extra))
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    return captured.out.splitlines()


def test_crt16_the_dry_run(cast_env, capsys):
    tmp, lib, fake = cast_env["tmp"], cast_env["lib"], cast_env["fake"]
    _cast(lib)
    story_dir = os.path.join(tmp, "stories", "s1")
    k00, r00 = (os.path.join(lib, name, "dataset", "stills", "char_00.png") for name in ("kyra", "ronin"))
    plain = _dry(capsys)
    lines = _dry(capsys, "--cast-refs-model", "qwen21-q4")
    i = lines.index("--- Phase 2: stills ---")
    assert lines[i + 1] == (
        "Would edit every panel whose Image: names two cast characters with %s at 1408x896, seed 0, in one Qwen "
        "child: Picture 1 and Picture 2 are the two characters' reference stills in cast order (kyra %s; ronin %s); "
        "each panel is prompted by the cast-reference instruction and its own Image: text (and the Style: text), "
        "screened with content safety (skill ltx_movie_cast_ref_edit) and recorded in %s. No Z-Image stills LoRA "
        "applies to those panels; a blocked or failed one stops the run after the batch. Every other panel is a "
        "Z-Image still:" % (qwen_edit.generator_text("qwen21-q4", []), k00, r00,
                            os.path.join(story_dir, "cast_ref_edits.json")))
    assert lines[i + 2] == "Cast-reference panels: decided at Phase 2, from story.md after Phase 1"
    j = plain.index("--- Phase 2: stills ---")
    assert lines[i + 3:i + 5] == plain[j + 1:j + 3]
    assert [line for line in lines if line not in plain and not line.startswith("note: --cast-refs-model")] == \
        lines[i + 1:i + 3]
    _story(tmp)
    members = movie._character_lib().resolve_cast([(None, "kyra"), (None, "ronin")])
    args = _args(tmp, members, image_seed=0, cast_refs={"qwen_model": "qwen21-q4", "loras": [],
                                                        "stills": {"kyra": k00, "ronin": r00}})
    _error, plan = movie._cast_refs_plan(args, fake)
    assert movie._phase2_cast_refs_batch(args, fake, plan) == 0
    _story(tmp, images=IMAGES[:3] + [IMAGES[3] + " Lanterns glow."])
    capsys.readouterr()
    lines = _dry(capsys, "--cast-refs-model", "qwen21-q4")
    i = lines.index("--- Phase 2: stills ---")
    assert lines[i + 2] == "Cast-reference panels: 2 (kyra, ronin); 4 (kyra, ronin); to edit: 4; reused: 2"
    groups = lines[i + 3:lines.index("", i)]
    assert [line for line in groups if line.startswith("stills group ")] == [
        "stills group 1/2 (kyra; panels 1)", "stills group 2/2 (ronin; panels 3)"]
    assert len(fake.calls["run_jobs"]) == 1 and fake.calls["selection_problem"] == []


# --- CRT17 (CR13): the help texts and the docstring paragraph ------------------------------------------------

HELP = {
    "--cast-refs-model": (
        "a test option for --shots without --seed-image: every panel whose Image: names two cast characters "
        "(--character/--cast) is rendered by this Qwen registry edit model (qwen21-q4, qwen21-q8, qwen21-bf16, "
        "qwen2511-bf16; qwen2511-q4 is refused) with the two characters' reference stills as Picture 1 and Picture "
        "2, instead of Z-Image with both stills LoRAs; screened with content safety and recorded in "
        "cast_ref_edits.json. Every other panel is unchanged. See docs/superpowers/specs/"
        "2026-11-09-shots-multi-reference-stills-design.md."),
    "--cast-refs-lora": ("with --cast-refs-model ID: a registry LoRA of that model's family, 0 < SCALE <= 2 "
                         "(repeatable); none listed means no LoRA")}
DOC = ("Cast references (docs/superpowers/specs/2026-11-09-shots-multi-reference-stills-design.md), a test option: "
       "in shots mode without --seed-image, --cast-refs-model ID renders every panel whose Image: names two cast "
       "characters as one Qwen edit with both characters' reference stills as Picture 1 and Picture 2, instead of "
       "Z-Image with both stills LoRAs (which blends the two people); one child for all of them, screened, recorded "
       "in cast_ref_edits.json and reused on a rerun when nothing changed. Every other panel is unchanged. Absent, "
       "Phase 2 is unchanged.")


def test_crt17_the_help_texts_and_the_docstring():
    actions = dict((a.option_strings[0], a) for a in movie.build_parser()._actions if a.option_strings)
    for flag, text in HELP.items():
        assert actions[flag].help == text, flag
    assert " ".join(movie.__doc__.split()).endswith(DOC)
    with open(os.path.join(WS, "bin", "ltx-movie"), encoding="utf-8") as f:
        assert "\nimport re\n" not in f.read()


# --- CRT18 (CR3, CR10): the real runner: one child, both sources, every output screened ---------------------

def test_crt18_the_real_runner(env, monkeypatch):
    py, _snapshot, _lora = _mflux_ready(env)
    st.stub_config(py, {"red": [4]})
    tmp, mp = env["tmp"], env["mp"]
    lib = os.path.join(tmp, "characters")
    os.makedirs(lib)
    mp.setenv("CHARACTER_LIBRARY_DIR", lib)
    mp.setattr(movie, "_qwen_edit", lambda: qwen_edit)
    mp.setattr(movie, "_story_dir", lambda story_id: os.path.join(tmp, "stories", story_id))
    members = _cast(lib)
    story_dir = _story(tmp)
    k00, r00 = (os.path.join(lib, name, "dataset", "stills", "char_00.png") for name in ("kyra", "ronin"))
    args = _args(tmp, members)
    _error, plan = movie._cast_refs_plan(args, qwen_edit)
    assert movie._phase2_cast_refs_batch(args, qwen_edit, plan) == 1
    (call,) = st.stub_calls(py)
    assert [(j["n"], j["prompt"], j["source"], j["sources"]) for j in call["spec"]["jobs"]] == [
        (n, _prompt(n), k00, [k00, r00]) for n in (2, 4)]
    assert (call["spec"]["width"], call["spec"]["height"]) == (1408, 896)
    assert env["calls"]["safety"] == [{"skill": "ltx_movie_cast_ref_edit", "prompt": _prompt(n), "size": (1408, 896)}
                                      for n in (2, 4)]
    assert [e["status"] for e in _record(story_dir)["panels"]] == ["ok", "blocked"]
    assert os.path.isfile(os.path.join(story_dir, "cast_ref_edits", "child.log"))
    stub = st.qwenedit_stub(env, {"blocked": []})
    with open(stub, "w", encoding="utf-8") as f:
        f.write(PANEL_QWENEDIT_STUB)
    _bf16_cache(env)
    mp.setattr(qwen_edit, "avail_gib", lambda: 80.0)
    args = _args(tmp, members, cast_refs={"qwen_model": "qwen2511-bf16", "loras": [],
                                          "stills": {"kyra": k00, "ronin": r00}})
    _error, plan = movie._cast_refs_plan(args, qwen_edit)
    assert plan["todo"] == [2, 4]
    assert movie._phase2_cast_refs_batch(args, qwen_edit, plan) == 0
    (call,) = st.stub_calls(stub)
    assert [j["images"] for j in call["spec"]["jobs"]] == [[k00, r00], [k00, r00]]
    assert call["spec"]["skill"] == "ltx_movie_cast_ref_edit"
