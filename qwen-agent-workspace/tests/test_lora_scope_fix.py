"""Tests for the lora-scope fix round
(docs/superpowers/specs/2026-11-10-lora-scope-design.md, "Fix round (review findings)", A1-A4:
LST12-LST16): a style LoRA's scope may only be global, a LoRA the critic moves between global
and a beat keeps one copy in either patch order, Phase 3 and the dry run name the fix for an
L8, and a lora_notes value that is not a list of strings adds no advisory.

Run from the workspace root:
python3 -m pytest -q -p no:cacheprovider tests/test_lora_scope_fix.py

bin/lora-catalog runs as a subprocess with LORA_CATALOG_DIR under tmp_path; story_engine and
bin/ltx-movie are loaded as modules, and bin/ltx-movie's subprocess.run is recorded; the movie
UI server runs against the stub workspace of movie_ui_testutil under a temporary HOME. No test
reaches a model server, a daemon or the Anthropic API. Stdlib and pytest.
"""

import copy
import importlib.machinery
import json
import os
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import lora_catalog  # noqa: E402
import movie_ui_testutil as mt  # noqa: E402
import story_engine_testutil as seu  # noqa: E402

se = importlib.machinery.SourceFileLoader(
    "story_engine_for_lora_scope_fix", os.path.join(WS, "story_engine.py")).load_module()
ltx_movie = importlib.machinery.SourceFileLoader(
    "ltx_movie_for_lora_scope_fix", os.path.join(WS, "bin", "ltx-movie")).load_module()

CLI = os.path.join(WS, "bin", "lora-catalog")
GLOBAL_L8 = ("plan: L8 scope: 'fast-motion' may only be a per-beat pick (its catalog scope is "
             "beat), but it is a global pick; remove it from global and pick it for the beats "
             "that need it")
BEAT_L8 = ("beat 2: L8 scope: 'film-grain' may only be a global pick (its catalog scope is "
           "global), but it is a pick for this beat; remove it from this beat, or move it to "
           "global if it suits the whole movie")
CHECKS_ERROR = ("Error: plan.json LoRA picks fail the catalog checks (%s); rerun with "
                "--force-story or --no-auto-lora\n")


@pytest.fixture
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ui(monkeypatch, tmp_path):
    state = mt.set_home(monkeypatch, tmp_path)
    workspace = mt.make_stub_workspace(tmp_path)
    running = mt.Running(state)
    yield {"ws": workspace, "srv": running}
    running.close()
    mt.kill_everything(state)


def _entries(tmp_path):
    """film-grain (style) and fast-motion (motion), with no scope."""
    files = str(tmp_path / "files")
    return [seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style"),
            seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion")]


def _pick(entry_id, strength=0.8):
    return {"id": entry_id, "strength": strength}


def _cli(*argv):
    return subprocess.run([sys.executable, CLI] + list(argv), cwd=WS, capture_output=True,
                          text=True)


def _read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _plan(ctx, loras):
    raw = seu.plan_json(ctx.mode, ctx.panels)
    raw["loras"] = dict({"global": [], "per_beat": {}, "stills": []}, **loras)
    return se.normalize_plan(ctx, raw)[0]


def _checks(ctx, plan):
    compatible = dict((e["id"], e) for e in se.compatible_entries(ctx))
    catalog = dict((e["id"], e) for e in ctx.catalog["entries"])
    return se.lora_checks(ctx, plan, compatible, catalog)


# --- LST12 (A1): a style LoRA's scope is only ever global -------------------------------------

def test_lst12_a_style_lora_is_only_ever_global(tmp_path, story_env):
    grain, fast = _entries(tmp_path)
    for scope in ("beat", "either"):
        with pytest.raises(lora_catalog.CatalogError) as exc:
            lora_catalog.validate_entry(dict(grain, scope=scope))
        assert str(exc.value) == ("entry film-grain: scope must be global for a style LoRA, "
                                  "which applies to every panel, got %r; edit catalog.json by "
                                  "hand: remove the scope key or set it to global" % scope)
        assert lora_catalog.entry_scope(dict(grain, scope=scope)) == "global"
    lora_catalog.validate_entry(dict(grain, scope="global"))
    lora_catalog.validate_entry(dict(grain, target="stills", base_models=[seu.STILLS_MODEL],
                                     scope="beat"))
    path = seu.make_catalog(story_env["catalog"], [dict(grain, scope="either"), fast])
    with pytest.raises(lora_catalog.CatalogError) as exc:
        lora_catalog.load_catalog(path)
    assert str(exc.value) == ("%s: entry film-grain: scope must be global for a style LoRA, "
                              "which applies to every panel, got 'either'; edit catalog.json by "
                              "hand: remove the scope key or set it to global" % path)
    seu.make_catalog(story_env["catalog"], [grain, fast])
    before = _read_bytes(path)
    ink = seu.lora_file(str(tmp_path / "files"), "ink")
    base = ["--target", "video", "--base-model", seu.VIDEO_MODEL, "--description", "ink",
            "--use-when", "ink"]
    for scope in ("beat", "either"):
        result = _cli("add", ink, "--id", "ink-style", "--kind", "style", "--scope", scope, *base)
        assert (result.returncode, result.stdout, result.stderr) == (
            2, "", "Error: --scope %s applies only to motion and physics LoRAs; a style LoRA is "
                   "only ever a global pick\n" % scope)
        result = _cli("scope", "film-grain", scope)
        assert (result.returncode, result.stdout, result.stderr) == (
            2, "", "Error: film-grain is a style LoRA; a style LoRA is only ever a global pick, "
                   "so its scope is global or default\n")
    assert _read_bytes(path) == before
    result = _cli("scope", "film-grain", "global")
    assert (result.returncode, result.stdout) == (0, "film-grain: scope global in %s\n" % path)
    result = _cli("scope", "film-grain", "default")
    assert (result.returncode, result.stdout) == (
        0, "film-grain: scope global (the default for a style LoRA) in %s\n" % path)
    assert _read_bytes(path) == before
    assert _cli("add", ink, "--id", "ink-style", "--kind", "style", "--scope", "global",
                *base).returncode == 0
    added = [e for e in lora_catalog.load_catalog(path)["entries"] if e["id"] == "ink-style"]
    assert added[0]["scope"] == "global"
    ctx = seu.make_ctx(se, seu.make_ws(tmp_path), catalog={
        "schema_version": 1, "entries": [dict(grain, scope="either"), fast]})
    assert se.catalog_groups(ctx, ctx.catalog["entries"]) == [
        se.LORA_GLOBAL_GROUP, se.catalog_line(grain), se.LORA_BEAT_GROUP, se.catalog_line(fast)]
    assert _checks(ctx, _plan(ctx, {"per_beat": {"2": [_pick("film-grain")]}})) == (
        [BEAT_L8], [])


# --- LST13 (A1): the movie UI never sends a per-beat scope for a style LoRA ---------------------

def test_lst13_the_movie_ui_gives_a_style_lora_no_per_beat_scope(ui):
    s, ws = ui["srv"], ui["ws"]
    add = {"ws": ws, "path": "/l/grain.safetensors", "id": "grain", "kind": "style",
           "target": "video", "base_models": ["M1"], "triggers": [], "description": "a look",
           "use_when": "always", "avoid_when": "", "default_strength": 0.8,
           "strength_range": [0.5, 1], "rank": 16, "alpha": None}
    for scope in ("beat", "either"):
        assert mt.api(s, "POST", "/api/loras", body=dict(add, scope=scope))[::2] == (
            400, {"error": "scope must be global or null for a style LoRA"}), scope
    assert mt.stub_calls(ws) == []
    for body, tail in ((dict(add, scope="global"), ["--rank", "16", "--scope", "global"]),
                       (dict(add, scope=None), ["--kind", "style"]),
                       (dict(add, kind="motion", scope="beat"),
                        ["--rank", "16", "--scope", "beat"])):
        status, _h, payload = mt.api(s, "POST", "/api/loras", body=body)
        assert status == 200, payload
        argv = mt.stub_calls(ws)[-1]["argv"]
        assert argv[argv.index(tail[0]):argv.index(tail[0]) + len(tail)] == tail
    assert "--scope" not in mt.stub_calls(ws)[1]["argv"]
    with open(os.path.join(WS, "static", "movie-ui", "index.html"), encoding="utf-8") as f:
        html = f.read()
    assert ("Where the story planner may put a physics video LoRA: global applies it to "
            "every panel, beat only to the beats it suits, either lets the planner choose; the "
            "default is beat. A style LoRA is always global, a motion LoRA is always per-beat, "
            "and a stills LoRA has no scope, so the select is off for all three.</span>") in html


# --- LST14 (A2): a LoRA the critic moves keeps one copy, in either patch order -------------------

def test_lst14_a_moved_lora_keeps_one_copy_in_either_patch_order(tmp_path, story_env):
    ctx = seu.make_ctx(se, seu.make_ws(tmp_path),
                       catalog={"schema_version": 1, "entries": _entries(tmp_path)})

    def patch(index, replacement):
        return {"target": "plan", "index": index, "field": "lora", "reason": "L8",
                "replacement": replacement}

    for start, patches, want in (
            ({"per_beat": {"2": [_pick("film-grain")]}},
             [patch(0, [_pick("film-grain")]), patch(2, [])], ([_pick("film-grain")], {})),
            ({"global": [_pick("fast-motion")]},
             [patch(2, [_pick("fast-motion")]), patch(0, [])],
             ([], {"2": [_pick("fast-motion")]}))):
        for order in (patches, patches[::-1]):
            state = {"plan": _plan(ctx, start), "parts": []}
            kept = copy.deepcopy(state)
            new, applied, rejected = se.apply_patches(ctx, state, order, lora_allowed=True)
            loras = new["plan"]["loras"]
            assert (loras["global"], loras["per_beat"]) == want, order
            assert sorted(p["index"] for p in applied) == [0, 2] and rejected == [], order
            assert _checks(ctx, new["plan"]) == ([], []) and "lora_notes" not in new["plan"]
            assert state == kept
    state = {"plan": _plan(ctx, {}), "parts": []}
    new, applied, rejected = se.apply_patches(
        ctx, state, [patch(0, [_pick("fast-motion")]), patch(3, [])], lora_allowed=True)
    assert [p["index"] for p in applied] == [3]
    assert [r["reason"] for r in rejected] == ["would break " + GLOBAL_L8]
    assert new["plan"]["loras"]["global"] == []


# --- LST15 (A3): Phase 3 and the dry run name the fix for an L8 ---------------------------------

class _Done(object):
    returncode = 0


def _movie_args(*argv):
    args = ltx_movie.build_parser().parse_args(list(argv))
    args.video_width, args.video_height = 704, 448
    for resolve in (ltx_movie._resolve_shots, ltx_movie._resolve_casting,
                    ltx_movie._resolve_global_loras, ltx_movie._resolve_story_engine):
        assert resolve(args) == 0
    return args


def _write_plan(story_dir, loras, **extra):
    plan = {"schema": "ltx-movie.plan.v1", "mode": "chained", "panels": 3, "title": "T",
            "logline": "x", "cast": [], "locations": [], "props": [], "beats": [],
            "loras": dict({"global": [], "per_beat": {}, "stills": []}, **loras)}
    with open(os.path.join(story_dir, "plan.json"), "w") as f:
        json.dump(dict(plan, **extra), f)


def _story(tmp_path, monkeypatch, story_env, entries, loras, **extra):
    """A temp workspace (ltx_movie.WS) whose 3-panel chained story c1 has these picks; returns
    its story directory. bin/ltx-movie's subprocess.run is recorded, never run."""
    ws = seu.make_ws(tmp_path)
    monkeypatch.setattr(ltx_movie, "WS", ws)
    monkeypatch.setattr(ltx_movie.subprocess, "run", lambda cmd, **kw: _Done())
    seu.make_catalog(story_env["catalog"], entries)
    story_dir = os.path.join(ws, "generated", "stories", "c1")
    os.makedirs(story_dir)
    _write_plan(story_dir, loras, **extra)
    with open(os.path.join(story_dir, "story.md"), "w") as f:
        f.write("# T\n\n## Panel 1 — A\nImage: The woman in grey waits.\nMotion: x\n"
                "Narration: y\n")
    return story_dir


P3 = ["n", "--story-id", "c1", "--panels", "3", "--no-review"]


def test_lst15_phase_3_and_the_dry_run_name_the_l8_fix(tmp_path, monkeypatch, story_env, capsys):
    grain, fast = _entries(tmp_path)
    story_dir = _story(tmp_path, monkeypatch, story_env, [grain, fast],
                       {"global": [_pick("fast-motion", 0.7)]})
    path = os.path.join(story_dir, "catalog_loras.json")
    capsys.readouterr()
    assert ltx_movie.phase3_manifest(_movie_args(*P3)) == 2
    assert capsys.readouterr().err == CHECKS_ERROR % GLOBAL_L8 + se.RECHECK_SCOPE_HINT + "\n"
    assert ltx_movie.main(P3 + ["--dry-run"]) == 2
    assert capsys.readouterr().err == CHECKS_ERROR % GLOBAL_L8 + se.RECHECK_SCOPE_HINT + "\n"
    assert not os.path.exists(path)
    rain = seu.catalog_entry(seu.lora_file(str(tmp_path / "files"), "rain"), "rain-physics",
                             kind="physics", scope="either")
    seu.make_catalog(story_env["catalog"], [grain, fast, rain])
    _write_plan(story_dir, {"global": [_pick("rain-physics", 0.7)]})
    assert ltx_movie.phase3_manifest(_movie_args(*P3)) == 0
    item = {"id": "rain-physics", "kind": "physics", "path": rain["path"],
            "sha256": rain["sha256"], "strength": 0.7, "triggers": []}
    with open(path) as f:
        assert json.load(f)["panels"] == [[item], [item], [item]]
    os.remove(path)
    _write_plan(story_dir, {"per_beat": {"2": [_pick("film-grain")]}})
    capsys.readouterr()
    assert ltx_movie.phase3_manifest(_movie_args(*P3)) == 2
    assert capsys.readouterr().err == CHECKS_ERROR % BEAT_L8 + se.RECHECK_SCOPE_HINT + "\n"
    _write_plan(story_dir, {"global": [_pick("film-grain", 99)]})
    assert ltx_movie.phase3_manifest(_movie_args(*P3)) == 2
    assert capsys.readouterr().err == CHECKS_ERROR % (
        "plan: L5 strength: 'film-grain' strength 99.0 is outside (0, 2], which the renderer "
        "refuses")
    assert not os.path.exists(path)


# --- LST16 (A4): lora_notes that are not a list of strings add no advisory -----------------------

def test_lst16_lora_notes_that_are_not_a_list_of_strings_add_no_advisory(tmp_path, monkeypatch,
                                                                          story_env):
    grain, fast = _entries(tmp_path)
    story_dir = _story(tmp_path, monkeypatch, story_env, [grain, fast],
                       {"global": [_pick("film-grain")]}, lora_notes=None)
    assert ltx_movie.phase3_manifest(_movie_args(*P3)) == 0
    assert os.path.exists(os.path.join(story_dir, "catalog_loras.json"))
    ctx = seu.make_ctx(se, ltx_movie.WS, catalog={"schema_version": 1, "entries": [grain, fast]})
    plan = _plan(ctx, {"global": [_pick("film-grain")]})
    note = ("plan: L6 duplicate: 'film-grain' was picked both globally and for beat(s) 2; the "
            "pipeline kept the global pick and dropped the per-beat copies")
    for notes, advisory in (("a note", []), (None, []), (3, []), ({"a": "b"}, []),
                            ([1, None, note], [note]), ([note], [note])):
        assert _checks(ctx, dict(plan, lora_notes=notes)) == ([], advisory), notes
