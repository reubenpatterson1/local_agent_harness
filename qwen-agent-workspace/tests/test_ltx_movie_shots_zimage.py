"""Tests for the shots Z-Image engine (docs/superpowers/specs/2026-11-11-shots-zimage-engine-design.md, SZ1-SZ10): with
--shots, --seed-image and --seed-edit-model as-is, panel 1 is the seed and every other panel a Z-Image still.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_ltx_movie_shots_zimage.py

No test loads a model, renders or contacts a server. Stdlib, PIL and pytest.
"""

import argparse
import glob
import hashlib
import json
import os

import pytest
from PIL import Image

import story_engine_testutil as seu
import test_dialogue as dlg
import test_ltx_movie_shots_seed as sse
from test_ltx_movie_shots_seed import clean_env  # noqa: F401

movie = sse.movie
MOVE = "(a Qwen edit of the seed; the Z-Image engine renders this panel again)"
NO_MODEL = ("Error: --shots with --seed-image needs --seed-edit-model: a Qwen model ID makes every panel's still an "
            "edit of the seed; as-is keeps the seed as panel 1 and renders every other panel's still with Z-Image\n")
CONTEXT_AS_IS = ("Error: --seed-context needs --seed-edit-model ID, a Qwen registry edit model (as-is is refused): "
                 "every shots still is a Qwen edit of the seed\n")
PLAN_WARNING = ("Warning: %s was planned for the Qwen engine (plan.json records the seed image), so its Image: lines "
                "leave out the cast descriptions that Z-Image draws from; rerun with --force-story to plan the story "
                "for Z-Image")
HELP_EDIT = (
    "with --seed-image: edit the seed into panel 1 with a Qwen registry edit model (qwen21-q4, qwen21-q8, "
    "qwen21-bf16, qwen2511-q4, qwen2511-bf16), prompted by panel 1's Image: text after Phase 1 and screened with "
    "content safety; as-is, like leaving the flag out, uses the seed unchanged. With --shots it is required and "
    "chooses the stills engine: an ID makes every panel's still an edit of the seed, each prompted by its own Image: "
    "text; as-is keeps the seed as panel 1 and renders every other panel's still with Z-Image and its stills LoRAs, "
    "as --shots does without a seed. See docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md, "
    "2026-11-05-compose-shots-seed-edit-design.md and 2026-11-11-shots-zimage-engine-design.md.")
HELP_SHOTS = (
    "shots mode: every panel is its own shot with its own Image: still and is rendered from that still (no "
    "chaining; cuts between panels). Phase 1 uses the shots story template and enforces the shot rules (one "
    "action per Motion:, at most two cast characters per shot), Phase 2 renders a still for every panel, and "
    "every cast character LoRA defaults to 0.8. With --seed-image, --seed-edit-model (required) chooses the stills "
    "engine: an ID makes every panel's still a Qwen edit of the seed; as-is keeps the seed as panel 1 and renders "
    "every other panel's still with Z-Image. See docs/superpowers/specs/2026-10-06-shots-mode-design.md.")
DOC_SENTENCE = (
    "Absent, or as-is, the seed is used unchanged. With --shots (docs/superpowers/specs/2026-11-11-shots-zimage-"
    "engine-design.md) the flag is required: as-is keeps the seed as panel 1 and renders every other panel's still "
    "with Z-Image and its stills LoRAs, as --shots does without a seed.")
STILLS_GROUPS = ("Stills groups: computed from story.md after Phase 1 -- one run per distinct set of cast stills "
                 "LoRAs, each with --only <PANELS> (that group's panels):")
GROUP_CMD = ["py", "ltx-story-images", "--only", "1", "--seed-image", "/s.jpg"]


def _z(tmp, **kw):
    """tests/test_ltx_movie_shots_seed.py's phase args on the Z-Image engine: --seed-edit-model as-is, no seed edit."""
    return sse._phase_args(tmp, seed_edit=None, seed_edit_model="as-is", **kw)


def _stills(tmp, n=3):
    """<tmp>/stories/s1/images/panel_0k.png for k in 1..n, each 8x8 RGB of colour (10 * k, 0, 0); returns {k: path}."""
    images = os.path.join(tmp, "stories", "s1", "images")
    os.makedirs(images, exist_ok=True)
    paths = {}
    for k in range(1, n + 1):
        paths[k] = os.path.join(images, "panel_%02d.png" % k)
        Image.new("RGB", (8, 8), (10 * k, 0, 0)).save(paths[k])
    return paths


def _rec(tmp, name, schema, entries):
    """<tmp>/stories/s1/<name> as {"schema": schema, "panels": entries}; returns its path."""
    path = os.path.join(tmp, "stories", "s1", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"schema": schema, "panels": entries}, f)
    return path


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _qwen_state(tmp):
    """SZ5's final state: story.md, panels 1-3, seed_edits.json recording panel 2 (its sha) and panel 3 (another sha)
    as ok, and seed_context_edits.json recording panel 3 (its sha) as ok. Returns {k: path}."""
    sse._write_story(tmp)
    p = _stills(tmp)
    _rec(tmp, "seed_edits.json", "ltx-movie.seed-edits.v1",
         [{"n": 2, "status": "ok", "still_sha256": _sha(p[2])}, {"n": 3, "status": "ok", "still_sha256": "0" * 64}])
    _rec(tmp, "seed_context_edits.json", "ltx-movie.seed-context-edits.v1",
         [{"n": 3, "status": "ok", "still_sha256": _sha(p[3])}])
    return p


def _recorder(calls):
    """A _stream_and_tee stand-in: records each command and returns 0."""
    return lambda cmd, log_path: calls.append(list(cmd)) or 0


# --- SZ1 (ZE2): the option rules ----------------------------------------------------------------------------

def test_sz1_the_option_rules(clean_env, capsys):
    tmp = clean_env["tmp"]
    shots = ["--shots", "--seed-image", sse._seed1920(tmp)]
    as_is = ["--seed-edit-model", "as-is"]
    for extra, rc, err in (([], 2, NO_MODEL), (as_is, 0, ""),
                           (as_is + ["--stills-lora", "/x.safetensors"], 0, ""),
                           (as_is + ["--story-legacy"], 2, sse.ENGINE_RULE % "--story-legacy"),
                           (["--seed-edit-model", "qwen21-q4", "--stills-lora", "/x.safetensors"], 2,
                            sse.STILLS_RULE)):
        assert movie._resolve_shots(sse._parse(*(shots + extra))) == rc, extra
        assert capsys.readouterr().err == err, extra
    base = ["n", "--story-id", "s1", "--dry-run", "--no-review", "--no-auto-lora"] + shots + as_is
    for extra, err in ((["--seed-edit-lora", "uncensored=1.0"],
                        "Error: --seed-edit-lora cannot be combined with --seed-edit-model as-is\n"),
                       (["--cast-refs-model", "qwen21-q4"],
                        "Error: --cast-refs-model cannot be combined with --seed-image: with a seed image every shots "
                        "still is already a Qwen edit of the seed\n"),
                       (["--seed-context", "still"], CONTEXT_AS_IS)):
        assert movie.main(base + extra) == 2, extra
        assert capsys.readouterr().err == err, extra


# --- SZ2 (ZE1): the path predicate --------------------------------------------------------------------------

def test_sz2_the_path_predicate():
    def zimage(shots, image, model):
        return movie._shots_zimage_seed(argparse.Namespace(shots=shots, seed_image=image, seed_edit_model=model))

    assert zimage(True, "/s.png", "as-is") is True
    for case in ((True, "/s.png", "qwen21-q4"), (True, "/s.png", None), (True, None, "as-is"),
                 (False, "/s.png", "as-is")):
        assert zimage(*case) is False, case
    assert movie._shots_zimage_seed(argparse.Namespace(shots=True, seed_image="/s.png")) is False


# --- SZ3 (ZE5): the phase tuple has no Phase 1c --------------------------------------------------------------

def test_sz3_the_phase_tuple(clean_env):
    args = sse._parse("--shots", "--seed-image", sse._seed1920(clean_env["tmp"]), "--seed-edit-model", "as-is")
    assert movie._resolve_shots(args) == 0
    assert movie._resolve_seed_edit(args) == 0 and args.seed_edit is None
    args.seed_context = None
    args.story_server_stop_after_story = True
    assert [p.__name__ for p in movie._phase_sequence(args)] == [
        "phase0_seed", "phase1_story", "phase_release_story_server", "phase2_stills", "phase3_manifest",
        "phase4_render"]
    args.story_only = True
    assert [p.__name__ for p in movie._phase_sequence(args)] == ["phase0_seed", "phase1_story"]


# --- SZ4 (ZE4): Phase 2 runs the shots branch with the seed and the stills LoRAs ------------------------------

def test_sz4_phase_2_runs_the_shots_branch(clean_env, monkeypatch, capsys):
    calls = {"qwen": [], "shots": []}
    monkeypatch.setattr(movie, "_phase2_shots_seed", lambda args: calls["qwen"].append(args) or 0)
    monkeypatch.setattr(movie, "_phase2_seed_context", lambda args: calls["qwen"].append(args) or 0)
    monkeypatch.setattr(movie, "_phase2_shots", lambda args, cmd: calls["shots"].append(list(cmd)) or 0)
    args = _z(clean_env["tmp"], global_stills_loras=[("/x/still.safetensors", 0.8)])
    assert movie.phase2_stills(args) == 0
    assert calls["qwen"] == [] and len(calls["shots"]) == 1
    cmd = calls["shots"][0]
    assert cmd[cmd.index("--seed-image") + 1] == args.seed_image
    assert cmd[cmd.index("--lora") + 1] == "/x/still.safetensors:0.8"
    assert cmd[cmd.index("--only") + 1] == "1"
    assert cmd[cmd.index("--width") + 1] == "1408"
    assert capsys.readouterr().out == "=== Phase 2: stills ===\n"


# --- SZ5 (ZE6): the missing stills: panel 1 and every recorded Qwen still ----------------------------------

def test_sz5_missing_stills(clean_env):
    tmp = clean_env["tmp"]
    sse._write_story(tmp)
    p = _stills(tmp)
    _rec(tmp, "seed_edits.json", "ltx-movie.seed-edits.v1",
         [{"n": 2, "status": "ok", "still_sha256": _sha(p[2])}, {"n": 3, "status": "ok", "still_sha256": "0" * 64}])
    assert movie._shots_missing_stills(_z(tmp), [1, 2, 3]) == [1, 2]
    _rec(tmp, "seed_context_edits.json", "ltx-movie.seed-context-edits.v1",
         [{"n": 3, "status": "ok", "still_sha256": _sha(p[3])}])
    assert movie._shots_missing_stills(_z(tmp), [1, 2, 3]) == [1, 2, 3]
    assert movie._shots_missing_stills(sse._phase_args(tmp), [1, 2, 3]) == []
    assert movie._shots_missing_stills(sse._phase_args(tmp, seed_image=None, seed_edit=None), [1, 2, 3]) == []


# --- SZ6 (ZE6): the Qwen stills move aside, and panel 1's group runs ----------------------------------------

def test_sz6_qwen_stills_move_aside_and_the_group_runs(clean_env, monkeypatch, capsys):
    tmp = clean_env["tmp"]
    p = _qwen_state(tmp)
    old = dict((n, _sha(p[n])) for n in (2, 3))
    calls = []
    monkeypatch.setattr(movie, "_stream_and_tee", _recorder(calls))
    capsys.readouterr()
    assert movie._phase2_shots(_z(tmp), list(GROUP_CMD)) == 0
    assert len(calls) == 1
    assert calls[0][calls[0].index("--only") + 1] == "1,2,3" and calls[0][-1] == "--shots"
    assert os.path.exists(p[1]) and not os.path.exists(p[2]) and not os.path.exists(p[3])
    story_dir = os.path.join(tmp, "stories", "s1")
    moved = {}
    for n in (2, 3):
        found = glob.glob(os.path.join(story_dir, "redo", "*", "images", "panel_%02d.png" % n))
        assert len(found) == 1, n
        moved[n] = found[0]
        assert _sha(moved[n]) == old[n]
    out = capsys.readouterr().out.splitlines()
    assert [line for line in out if line.startswith("stills: moved ")] == [
        "stills: moved %s -> %s %s" % (p[n], moved[n], MOVE) for n in (2, 3)]
    for n in (2, 3):
        Image.new("RGB", (8, 8), (0, 10 * n, 0)).save(p[n])
    assert movie._phase2_shots(_z(tmp), list(GROUP_CMD)) == 0
    assert len(calls) == 2 and calls[1][calls[1].index("--only") + 1] == "1,2,3"
    assert not [line for line in capsys.readouterr().out.splitlines() if line.startswith("stills: moved ")]
    assert movie._phase2_shots(sse._phase_args(tmp, seed_image=None, seed_edit=None), list(GROUP_CMD)) == 0
    assert len(calls) == 2
    assert ("stills group 1/1 (no character LoRAs; panels 1,2,3): every still exists; skipped"
            in capsys.readouterr().out.splitlines())


# --- SZ7 (ZE7): the warning for a story planned for the Qwen engine -----------------------------------------

def test_sz7_the_plan_warning(clean_env, capsys):
    tmp = clean_env["tmp"]
    story_dir = sse._write_story(tmp)
    story_md = os.path.join(story_dir, "story.md")
    plan = os.path.join(story_dir, "plan.json")
    assert movie.SHOTS_ZIMAGE_PLAN_WARNING == PLAN_WARNING and movie.SHOTS_ZIMAGE_MOVE_WHY == MOVE
    with open(plan, "w", encoding="utf-8") as f:
        json.dump({"seed_image": "/s/seed.png"}, f)
    movie._shots_zimage_prepare(_z(tmp))
    assert capsys.readouterr().out == movie.SHOTS_ZIMAGE_PLAN_WARNING % story_md + "\n"
    movie._shots_zimage_prepare(_z(tmp), dry_run=True)
    assert capsys.readouterr().out == movie.SHOTS_ZIMAGE_PLAN_WARNING % story_md + "\n"
    movie._shots_zimage_prepare(_z(tmp, force_story=True), dry_run=True)
    assert capsys.readouterr().out == ""
    with open(plan, "w", encoding="utf-8") as f:
        json.dump({"seed_image": None}, f)
    movie._shots_zimage_prepare(_z(tmp))
    assert capsys.readouterr().out == ""
    os.remove(plan)
    movie._shots_zimage_prepare(_z(tmp))
    assert capsys.readouterr().out == ""


# --- SZ8 (ZE3): the Z-Image story keeps the cast identity sentences ------------------------------------------

def test_sz8_the_story_keeps_the_identity_sentences(tmp_path, monkeypatch):
    seu.set_story_env(monkeypatch, tmp_path)
    monkeypatch.setattr(dlg.ltx_movie, "WS", seu.make_ws(tmp_path))
    args = dlg._movie_args("n", "--story-id", "x", "--shots", "--seed-image", "/s/seed.png", "--seed-edit-model",
                           "as-is")
    args.seed_downscaled_path = "/s/agent.png"
    ctx = dlg.ltx_movie._story_context(args)
    assert ctx.seed_image is None and ctx.seed_agent_image == "/s/agent.png"
    assert not dlg.se.seed_omits_identities(ctx)
    args = dlg._movie_args("n", "--story-id", "x", "--shots", "--seed-image", "/s/seed.png", "--seed-edit-model",
                           "qwen21-q4")
    args.seed_downscaled_path = "/s/agent.png"
    ctx = dlg.ltx_movie._story_context(args)
    assert ctx.seed_image == "/s/seed.png" and ctx.seed_agent_image == "/s/agent.png"
    assert dlg.se.seed_omits_identities(ctx)


# --- SZ9 (ZE9): the dry run ---------------------------------------------------------------------------------

def test_sz9_the_dry_run(clean_env, capsys):
    tmp = clean_env["tmp"]
    seed = sse._seed1920(tmp)
    story_dir = os.path.join(tmp, "stories", "s1")
    shots = ("--shots", "--seed-image", seed, "--seed-edit-model", "as-is")
    out = sse._dry(capsys, *shots)
    lines = out.splitlines()
    zero = [line for line in lines if line.startswith("Would validate ")]
    assert len(zero) == 1 and zero[0].endswith(
        "(long edge 1024px) to %s. Phase 2 fits the ORIGINAL into panel_01.png at twice the video size and renders "
        "every other panel's still with Z-Image; nothing is cropped." % os.path.join(story_dir, "seed_downscaled.png"))
    assert "--- Phase 1c: seed edit ---" not in lines
    assert "Would edit the seed into every panel's still" not in out
    i = lines.index(STILLS_GROUPS)
    assert ("--seed-image " + seed) in lines[i + 1] and lines[i + 1].endswith("--shots")
    assert clean_env["fake"].calls == {"selection_problem": [], "wait_for_memory": [], "run_jobs": []}
    sse._write_story(tmp)
    p = _stills(tmp)
    _rec(tmp, "seed_edits.json", "ltx-movie.seed-edits.v1",
         [{"n": 2, "status": "ok", "still_sha256": _sha(p[2])}, {"n": 3, "status": "ok", "still_sha256": "0" * 64}])
    lines = sse._dry(capsys, *shots).splitlines()
    assert "Would move %s -> %s %s" % (
        p[2], os.path.join(story_dir, "redo", "<UTC stamp>-<pid>", "images", "panel_02.png"), MOVE) in lines
    assert not [line for line in lines if line.startswith("Would move ") and "panel_03.png" in line]
    assert "stills group 1/1 (no character LoRAs; panels 1,2,3)" in lines
    assert not [line for line in lines if "would be skipped" in line]
    assert os.path.exists(p[2]) and not os.path.exists(os.path.join(story_dir, "redo"))


# --- SZ10 (ZE10): the helps and the docstring ---------------------------------------------------------------

def test_sz10_help_and_docstring():
    actions = dict((a.option_strings[0], a) for a in movie.build_parser()._actions if a.option_strings)
    assert actions["--seed-edit-model"].help == HELP_EDIT
    assert actions["--shots"].help == HELP_SHOTS
    assert actions["--seed-image"].help == sse.HELP["--seed-image"]
    assert sse.HELP["--seed-edit-model"] == HELP_EDIT and sse.HELP["--shots"] == HELP_SHOTS
    doc = " ".join(movie.__doc__.split())
    assert DOC_SENTENCE in doc and sse.DOC_SENTENCE in doc


# --- Review Focus 1: odd records and plans never crash Phase 2's first step and move nothing ------------------

def test_sz_review_focus_1_odd_records_and_plans_move_nothing(clean_env, capsys):
    tmp = clean_env["tmp"]
    story_dir = sse._write_story(tmp)
    p = _stills(tmp)
    record = os.path.join(story_dir, "seed_edits.json")
    context = os.path.join(story_dir, "seed_context_edits.json")
    plan = os.path.join(story_dir, "plan.json")
    odd_entries = [{"n": 1, "status": "blocked", "still_sha256": _sha(p[1])},
                   {"n": 2, "status": "failed", "still_sha256": _sha(p[2])},
                   {"n": True, "status": "ok", "still_sha256": _sha(p[1])},
                   {"n": "3", "status": "ok", "still_sha256": _sha(p[3])},
                   {"n": 3, "status": "ok"},
                   {"n": 9, "status": "ok", "still_sha256": _sha(p[3])},
                   "panel 3"]
    records = ['{"schema": "ltx-movie.seed-edits.v1", "panels": [',
               json.dumps({"schema": "ltx-movie.cast-ref-edits.v1",
                           "panels": [{"n": 2, "status": "ok", "still_sha256": _sha(p[2])}]}),
               json.dumps({"schema": "ltx-movie.seed-edits.v1", "panels": odd_entries}),
               json.dumps({"schema": "ltx-movie.seed-edits.v1",
                           "panels": {"2": {"n": 2, "status": "ok", "still_sha256": _sha(p[2])}}}),
               None]
    plans = ["[1]", '"x"', json.dumps({"seed_image": ""}), json.dumps({"seed_image": 5}), "not json"]
    with open(context, "w", encoding="utf-8") as f:
        json.dump({"schema": "ltx-movie.seed-context-edits.v1", "panels": [
            {"n": 3, "status": "blocked", "still_sha256": _sha(p[3])}]}, f)
    capsys.readouterr()
    for text, plan_text in zip(records, plans):
        if text is None:
            os.remove(record)
        else:
            with open(record, "w", encoding="utf-8") as f:
                f.write(text)
        with open(plan, "w", encoding="utf-8") as f:
            f.write(plan_text)
        args = _z(tmp)
        assert movie._shots_qwen_stills(args) == {}, plan_text
        movie._shots_zimage_prepare(args)
        assert capsys.readouterr().out == "", plan_text
        movie._shots_zimage_prepare(args, dry_run=True)
        assert capsys.readouterr().out == "", plan_text
        assert movie._shots_missing_stills(args, [1, 2, 3]) == [1], plan_text
        assert all(os.path.exists(p[k]) for k in (1, 2, 3)), plan_text
        assert not os.path.exists(os.path.join(story_dir, "redo")), plan_text


# --- Review Focus 2: with characters, only the group holding panel 1 reruns ---------------------------------

def test_sz_review_focus_2_with_characters_only_panel_1s_group_reruns(clean_env, monkeypatch, capsys):
    tmp = clean_env["tmp"]
    story_dir = sse._write_story(tmp)
    p = _stills(tmp, n=4)
    _rec(tmp, "seed_edits.json", "ltx-movie.seed-edits.v1", [{"n": 1, "status": "ok", "still_sha256": _sha(p[1])}])
    monkeypatch.setattr(movie, "_shots_stills_groups",
                        lambda story_md, members, locations=(): [((), [2, 3]), (("kyra",), [1, 4])])
    calls = []
    monkeypatch.setattr(movie, "_stream_and_tee", _recorder(calls))
    capsys.readouterr()
    assert movie._phase2_shots(_z(tmp), list(GROUP_CMD)) == 0
    assert [c[c.index("--only") + 1] for c in calls] == ["1,4"]
    assert calls[0][calls[0].index("--seed-image") + 1] == "/s.jpg"
    moved = glob.glob(os.path.join(story_dir, "redo", "*", "images", "panel_01.png"))
    assert len(moved) == 1
    out = capsys.readouterr().out.splitlines()
    assert "stills: moved %s -> %s %s" % (p[1], moved[0], MOVE) in out
    assert "stills group 1/2 (no character LoRAs; panels 2,3): every still exists; skipped" in out
    assert [os.path.exists(p[k]) for k in (1, 2, 3, 4)] == [False, True, True, True]


# --- Review Focus 3: --redo on the Z-Image path ---------------------------------------------------------------

def test_sz_review_focus_3_a_redo_on_the_zimage_path(clean_env):
    tmp = clean_env["tmp"]
    sse._write_story(tmp)
    args = sse._parse("--shots", "--seed-image", sse._seed1920(tmp), "--seed-edit-model", "as-is", "--redo", "2")
    assert movie._resolve_shots(args) == 0 and args.redo_panels == [2]
    assert movie._resolve_seed_edit(args) == 0 and args.seed_edit is None
    args.seed_context = None
    assert [p.__name__ for p in movie._phase_sequence(args)] == [
        "phase0_seed", "phase1_story", "phase_release_story_server", "phase_redo_shots", "phase2_stills",
        "phase3_manifest", "phase4_render"]
    _stills(tmp)
    assert movie._shots_missing_stills(_z(tmp, redo_panels=[3]), [1, 2, 3]) == [1, 3]
    assert movie._shots_missing_stills(_z(tmp, redo_panels=[3]), [2, 3]) == [3]
    assert movie._shots_missing_stills(sse._phase_args(tmp, seed_image=None, seed_edit=None, redo_panels=[3]),
                                       [1, 2, 3]) == [3]
