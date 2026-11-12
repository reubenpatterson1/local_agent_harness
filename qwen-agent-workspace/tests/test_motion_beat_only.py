"""Tests for the motion-beat-only change in lora_catalog.py, bin/lora-catalog, story_engine.py and
bin/ltx-movie (docs/superpowers/specs/2026-11-12-motion-lora-beat-only-design.md, MB1-MB7:
MB-T1-MB-T6): a motion video LoRA is only ever a per-beat pick, a saved global or either scope on
a motion entry loads as beat with a warning and a new write of one is refused, L3 counts motion
and physics apart, and a global physics LoRA may share a panel with a per-beat motion LoRA.

Run from the workspace root:
python3 -m pytest -q -p no:cacheprovider tests/test_motion_beat_only.py

bin/lora-catalog runs as a subprocess with LORA_CATALOG_DIR under tmp_path; story_engine and
bin/ltx-movie are loaded as modules, and bin/ltx-movie's subprocess.run is recorded. No test
reaches a model server, a daemon or the Anthropic API. Stdlib and pytest.
"""

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
import story_engine_testutil as seu  # noqa: E402

se = importlib.machinery.SourceFileLoader(
    "story_engine_for_motion_beat_only", os.path.join(WS, "story_engine.py")).load_module()
ltx_movie = importlib.machinery.SourceFileLoader(
    "ltx_movie_for_motion_beat_only", os.path.join(WS, "bin", "ltx-movie")).load_module()

CLI = os.path.join(WS, "bin", "lora-catalog")
ARCH_UNVERIFIED = ("arch: architecture UNVERIFIED: none of the declared base models are on disk "
                   "yet; run bin/lora-check once the base is installed\n")
W = lora_catalog.MOTION_SCOPE_WARNING
MOTION_GLOBAL_L8 = ("plan: L8 scope: 'fast-motion' may only be a per-beat pick (its catalog "
                    "scope is beat), but it is a global pick; remove it from global and pick it "
                    "for the beats that need it")
CHECKS_ERROR = ("Error: plan.json LoRA picks fail the catalog checks (%s); rerun with "
                "--force-story or --no-auto-lora\n")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


def _entries(tmp_path):
    """film-grain (style), fast-motion (motion, scope either), slow-motion (motion), rain-physics
    and mist-physics (physics, scope either) and ink-stills (stills)."""
    files = str(tmp_path / "files")
    return [
        seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style"),
        seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion", scope="either"),
        seu.catalog_entry(seu.lora_file(files, "slow"), "slow-motion"),
        seu.catalog_entry(seu.lora_file(files, "rain"), "rain-physics", kind="physics",
                          scope="either"),
        seu.catalog_entry(seu.lora_file(files, "mist"), "mist-physics", kind="physics",
                          scope="either"),
        seu.catalog_entry(seu.lora_file(files, "ink"), "ink-stills", kind="style",
                          target="stills", base_models=[seu.STILLS_MODEL])]


def _ctx(ws, tmp_path, **kw):
    return seu.make_ctx(se, ws, catalog={"schema_version": 1, "entries": _entries(tmp_path)}, **kw)


def _pick(entry_id, strength=0.8):
    return {"id": entry_id, "strength": strength}


def _plan(ctx, loras):
    raw = seu.plan_json(ctx.mode, ctx.panels)
    raw["loras"] = dict({"global": [], "per_beat": {}, "stills": []}, **loras)
    return se.normalize_plan(ctx, raw)[0]


def _checks(ctx, loras):
    plan = loras if "schema" in loras else _plan(ctx, loras)
    compatible = dict((e["id"], e) for e in se.compatible_entries(ctx))
    catalog = dict((e["id"], e) for e in ctx.catalog["entries"])
    return se.lora_checks(ctx, plan, compatible, catalog)


def _cli(*argv):
    return subprocess.run([sys.executable, CLI] + list(argv), cwd=WS, capture_output=True,
                          text=True)


def _read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


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


# --- MB-T1 (MB1-MB4): entry_scope, validate_entry(for_write) and scope_warnings ------------------

def test_mbt1_a_motion_lora_is_read_as_beat_and_named(tmp_path, story_env):
    assert W == ("catalog entry %s has the scope %s, but a motion LoRA is only ever a per-beat "
                 "pick, so it is read as beat; clear it with bin/lora-catalog scope %s default")
    assert lora_catalog.SCOPES == ("global", "beat", "either")
    assert lora_catalog.DEFAULT_SCOPES == {"style": "global", "motion": "beat", "physics": "beat"}
    grain, fast_either, slow, rain, mist, ink = _entries(tmp_path)
    fast = dict(fast_either)
    fast.pop("scope")
    for scope in (None, "global", "beat", "either"):
        e = fast if scope is None else dict(fast, scope=scope)
        assert lora_catalog.entry_scope(e) == "beat"
        lora_catalog.validate_entry(e)
    for scope in ("global", "either"):
        with pytest.raises(lora_catalog.CatalogError) as exc:
            lora_catalog.validate_entry(dict(fast, scope=scope), for_write=True)
        assert str(exc.value) == ("entry fast-motion: scope must be beat for a motion LoRA, "
                                  "which is only ever a per-beat pick, got %r" % scope)
    with pytest.raises(lora_catalog.CatalogError) as exc:
        lora_catalog.validate_entry(dict(fast, scope="globl"), for_write=True)
    assert str(exc.value) == ("entry fast-motion: scope must be one of global, beat, either, "
                              "got 'globl'")
    stills_motion = dict(fast, target="stills", base_models=[seu.STILLS_MODEL], scope="global")
    lora_catalog.validate_entry(fast, for_write=True)
    lora_catalog.validate_entry(dict(fast, scope="beat"), for_write=True)
    for scope in lora_catalog.SCOPES:
        lora_catalog.validate_entry(dict(rain, scope=scope), for_write=True)
        assert lora_catalog.entry_scope(dict(rain, scope=scope)) == scope
    lora_catalog.validate_entry(dict(grain, scope="global"), for_write=True)
    lora_catalog.validate_entry(stills_motion, for_write=True)
    assert lora_catalog.entry_scope(stills_motion) is None
    entries = [grain, dict(fast, scope="either"), dict(fast, id="old-motion", scope="global"),
               dict(fast, id="new-motion", scope="beat"), fast, dict(rain, scope="global"),
               stills_motion]
    assert lora_catalog.scope_warnings(entries) == [
        W % ("fast-motion", "either", "fast-motion"), W % ("old-motion", "global", "old-motion")]
    path = seu.make_catalog(story_env["catalog"], _entries(tmp_path))
    before = _read_bytes(path)
    data = lora_catalog.load_catalog(path)
    by_id = dict((e["id"], e) for e in data["entries"])
    assert by_id["fast-motion"]["scope"] == "either"
    lora_catalog.save_catalog(path, data)
    assert _read_bytes(path) == before


# --- MB-T2 (MB3, MB4): bin/lora-catalog warns and refuses a non-beat motion scope ----------------

def test_mbt2_lora_catalog_warns_and_refuses_a_non_beat_motion_scope(tmp_path, story_env):
    files = str(tmp_path / "files")
    path = seu.make_catalog(story_env["catalog"], _entries(tmp_path))
    warn = "warning: " + W % ("fast-motion", "either", "fast-motion") + "\n"
    result = _cli("list")
    assert (result.returncode, result.stderr) == (0, warn)
    row = "%-24s %-9s %-7s %-7s %-14s %-24s %s"
    lines = result.stdout.splitlines()
    assert row % ("fast-motion", "motion", "video", "beat", "0.8 (0.5-1.0)", "",
                  seu.VIDEO_MODEL) in lines
    assert row % ("rain-physics", "physics", "video", "either", "0.8 (0.5-1.0)", "",
                  seu.VIDEO_MODEL) in lines
    result = _cli("list", "--json")
    assert (result.returncode, result.stderr) == (0, warn)
    listed = dict((e["id"], e) for e in json.loads(result.stdout)["entries"])
    assert listed["fast-motion"]["scope"] == "either"
    result = _cli("verify")
    assert (result.returncode, result.stderr) == (0, warn)
    base = ["--base-model", seu.VIDEO_MODEL, "--description", "a test LoRA", "--use-when",
            "a chase"]
    before = _read_bytes(path)
    for scope in ("global", "either"):
        result = _cli("add", seu.lora_file(files, "new"), "--id", "new-motion", "--kind", "motion",
                      "--target", "video", "--scope", scope, *base)
        assert (result.returncode, result.stdout, result.stderr) == (
            2, "", ARCH_UNVERIFIED + "Error: entry new-motion: scope must be beat for a motion "
            "LoRA, which is only ever a per-beat pick, got %r\n" % scope)
        result = _cli("scope", "fast-motion", scope)
        assert (result.returncode, result.stdout, result.stderr) == (
            2, "", "Error: entry fast-motion: scope must be beat for a motion LoRA, which is "
            "only ever a per-beat pick, got %r\n" % scope)
        assert _read_bytes(path) == before
    assert _cli("remove", "film-grain").returncode == 0
    loaded = dict((e["id"], e) for e in lora_catalog.load_catalog(path)["entries"])
    assert loaded["fast-motion"]["scope"] == "either"
    result = _cli("scope", "fast-motion", "beat")
    assert (result.returncode, result.stdout, result.stderr) == (
        0, "fast-motion: scope beat in %s\n" % path, "")
    result = _cli("scope", "fast-motion", "default")
    assert (result.returncode, result.stdout, result.stderr) == (
        0, "fast-motion: scope beat (the default for a motion LoRA) in %s\n" % path, "")
    loaded = dict((e["id"], e) for e in lora_catalog.load_catalog(path)["entries"])
    assert "scope" not in loaded["fast-motion"]
    result = _cli("scope", "rain-physics", "global")
    assert (result.returncode, result.stdout, result.stderr) == (
        0, "rain-physics: scope global in %s\n" % path, "")
    assert _cli("list").stderr == ""
    result = _cli("add", seu.lora_file(files, "beat"), "--id", "beat-motion", "--kind", "motion",
                  "--target", "video", "--scope", "beat", *base)
    assert result.returncode == 0, result.stderr
    loaded = dict((e["id"], e) for e in lora_catalog.load_catalog(path)["entries"])
    assert loaded["beat-motion"]["scope"] == "beat"


# --- MB-T3 (MB1, MB2, MB6): L3 counts motion and physics apart, motion is never global ----------

def test_mbt3_l3_counts_motion_and_physics_apart_and_motion_is_never_global(ws, tmp_path):
    ctx = _ctx(ws, tmp_path)
    assert _checks(ctx, {"global": [_pick("film-grain"), _pick("rain-physics")],
                         "per_beat": {"2": [_pick("fast-motion")]}}) == ([], [])
    assert _checks(ctx, {"global": [_pick("fast-motion")]}) == ([MOTION_GLOBAL_L8], [])
    l3_motion = ("beat 2: L3 motion: 2 motion LoRAs on this panel (fast-motion, slow-motion); at "
                 "most 1")
    l3_physics = ("beat 2: L3 physics: 2 physics LoRAs on this panel (rain-physics, "
                  "mist-physics); at most 1")
    assert _checks(ctx, {"per_beat": {"2": [_pick("fast-motion"), _pick("slow-motion")]}}) == (
        [], [l3_motion])
    assert _checks(ctx, {"global": [_pick("rain-physics")],
                         "per_beat": {"2": [_pick("mist-physics")]}}) == ([], [l3_physics])
    both = _checks(ctx, {"global": [_pick("rain-physics")],
                         "per_beat": {"2": [_pick("fast-motion"), _pick("slow-motion"),
                                            _pick("mist-physics")]}})
    assert both[1] == [l3_motion, l3_physics]
    pinned = ctx._replace(pinned=[{"path": "/p/m.safetensors", "strength": 1.0,
                                   "catalog_id": None, "kind": "motion"}])
    assert _checks(pinned, {"per_beat": {"1": [_pick("fast-motion")]}}) == (
        [], ["beat 1: L3 motion: 2 motion LoRAs on this panel (pinned LoRA, fast-motion); at "
             "most 1"])
    violation = se.parse_violation(l3_physics)
    assert (violation["id"], violation["name"], violation["scope"], violation["index"]) == (
        "L3", "physics", "beat", 2)
    groups = se.catalog_groups(ctx, se.compatible_entries(ctx))
    split = groups.index(se.LORA_BEAT_GROUP)
    line = dict((e["id"], se.catalog_line(e)) for e in _entries(tmp_path))
    for m in ("fast-motion", "slow-motion"):
        assert line[m] not in groups[:split] and line[m] in groups[split:]
    for p in ("rain-physics", "mist-physics"):
        assert line[p] in groups[:split] and line[p] in groups[split:]
    plan = _plan(ctx, {"global": [_pick("fast-motion", 0.9)],
                       "per_beat": {"1": [_pick("fast-motion", 0.7)]}})
    assert plan["loras"]["global"] == []
    assert plan["loras"]["per_beat"] == {"1": [_pick("fast-motion", 0.7)]}
    assert plan["lora_notes"] == [
        "plan: L6 duplicate: 'fast-motion' was picked both globally and for beat(s) 1; its "
        "catalog scope is beat, so the pipeline kept the per-beat picks and dropped the global "
        "pick"]


# --- MB-T4 (MB5): the paragraph and the hint -------------------------------------------------

def test_mbt4_the_paragraph_and_the_hint(ws, tmp_path):
    assert se.LORA_PICK_PARAGRAPH == (
        "an object with the keys global, per_beat and stills. Each pick is an object with the "
        "keys id and strength, taken from the LoRA catalog below; strength must lie inside that "
        "entry's range. The catalog lists each LoRA under the places where it may go. global is "
        "a list of picks applied to every panel, taken only from the LoRAs that may be global "
        "picks: at most one style LoRA, plus at most one physics LoRA that suits the whole "
        "movie. per_beat maps each beat number to a list of picks for that beat only, taken "
        "only from the LoRAs that may be per-beat picks, and each key is the beat number alone "
        'in double quotes: the key of beat 1 is "1"; a LoRA in global is never also in '
        "per_beat, and every beat may have at most one motion LoRA and at most one physics "
        "LoRA, counting global. stills is a list of at most one stills LoRA.")
    assert se.RECHECK_SCOPE_HINT == (
        "An L8 violation is a pick placed where its catalog scope does not allow: give a "
        "physics LoRA the scope either with bin/lora-catalog scope ID either (or the Scope "
        "select of its row in the movie UI's LoRAs tab), or pass --force-story to regenerate; "
        "a style LoRA is only ever a global pick and a motion LoRA only ever a per-beat pick, "
        "so a style LoRA picked for a beat or a motion LoRA picked globally needs "
        "--force-story.")
    for text in (se.LORA_PICK_PARAGRAPH, se.RECHECK_SCOPE_HINT):
        assert "motion or physics" not in text
        assert "{" not in text and "}" not in text
    for mode in ("chained", "no_stills", "shots"):
        c = _ctx(ws, tmp_path, mode=mode)
        assert se.LORA_PICK_PARAGRAPH in se.build_plan_prompt(c, se.compatible_entries(c), [])


# --- MB-T5 (MB6): the critic can put physics globally and motion on a beat -------------------

def test_mbt5_the_critic_can_put_physics_globally_and_motion_on_a_beat(ws, tmp_path):
    ctx = _ctx(ws, tmp_path)

    def patch(index, replacement):
        return {"target": "plan", "index": index, "field": "lora", "reason": "L3",
                "replacement": replacement}

    patches = [patch(0, [_pick("rain-physics")]), patch(2, [_pick("fast-motion")])]
    for order in (patches, patches[::-1]):
        state = {"plan": _plan(ctx, {}), "parts": []}
        new, applied, rejected = se.apply_patches(ctx, state, order, lora_allowed=True)
        assert sorted(p["index"] for p in applied) == [0, 2]
        assert rejected == []
        assert (new["plan"]["loras"]["global"], new["plan"]["loras"]["per_beat"]) == (
            [_pick("rain-physics")], {"2": [_pick("fast-motion")]})
        assert _checks(ctx, new["plan"]) == ([], [])
    new, applied, rejected = se.apply_patches(
        ctx, {"plan": _plan(ctx, {}), "parts": []}, [patch(0, [_pick("fast-motion")])],
        lora_allowed=True)
    assert applied == []
    assert [r["reason"] for r in rejected] == ["would break " + MOTION_GLOBAL_L8]


# --- MB-T6 (MB4, MB7): Phase 3 warns and writes a global physics with a beat motion ----------

def test_mbt6_phase_3_warns_and_writes_a_global_physics_with_a_beat_motion(
        tmp_path, monkeypatch, story_env, capsys):
    grain, fast, rain = [e for e in _entries(tmp_path)
                         if e["id"] in ("film-grain", "fast-motion", "rain-physics")]
    story_dir = _story(tmp_path, monkeypatch, story_env, [grain, fast, rain],
                       {"global": [_pick("rain-physics", 0.7)],
                        "per_beat": {"2": [_pick("fast-motion", 0.8)]}})
    path = os.path.join(story_dir, "catalog_loras.json")
    warn = "Warning: " + W % ("fast-motion", "either", "fast-motion") + "\n"
    capsys.readouterr()
    assert ltx_movie.phase3_manifest(_movie_args(*P3)) == 0
    assert capsys.readouterr().err.count(warn) == 1
    r = {"id": "rain-physics", "kind": "physics", "path": rain["path"],
         "sha256": rain["sha256"], "strength": 0.7, "triggers": []}
    f = {"id": "fast-motion", "kind": "motion", "path": fast["path"],
         "sha256": fast["sha256"], "strength": 0.8, "triggers": []}
    with open(path) as fh:
        assert json.load(fh)["panels"] == [[r], [r, f], [r]]
    os.remove(path)
    _write_plan(story_dir, {"global": [_pick("fast-motion", 0.7)]})
    capsys.readouterr()
    assert ltx_movie.phase3_manifest(_movie_args(*P3)) == 2
    want = warn + CHECKS_ERROR % MOTION_GLOBAL_L8 + se.RECHECK_SCOPE_HINT + "\n"
    assert capsys.readouterr().err == want
    assert ltx_movie.main(P3 + ["--dry-run"]) == 2
    assert capsys.readouterr().err == want
    assert not os.path.exists(path)
    _movie_args(*(P3 + ["--no-auto-lora"]))
    assert "Warning: catalog entry" not in capsys.readouterr().err
