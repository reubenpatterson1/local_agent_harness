"""Tests for catalog LoRA scopes in the story engine
(docs/superpowers/specs/2026-11-10-lora-scope-design.md, LS4-LS6, LS8, LS9: LST4-LST9): the plan
prompt groups the catalog by scope, a pick its scope does not allow is the hard violation L8
that the planner retry and the critic repair, a LoRA picked both globally and for some beats
keeps one copy, and a re-check names L8 and how to restore a saved plan.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_lora_scope.py

Every model call goes to the fake bin/qwen-agent of a temp workspace (story_engine_testutil
make_ws); the dry-run test runs the real bin/ltx-movie --dry-run, which makes no model call. No
test reaches a model server, a daemon or the Anthropic API. Stdlib and pytest.
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

import story_engine_testutil as seu  # noqa: E402

se = importlib.machinery.SourceFileLoader(
    "story_engine_for_lora_scope", os.path.join(WS, "story_engine.py")).load_module()

NARRATIVE = "A courier carries a sealed letter across a rainy harbour town."
GLOBAL_L8 = ("plan: L8 scope: 'fast-motion' may only be a per-beat pick (its catalog scope is "
             "beat), but it is a global pick; remove it from global and pick it for the beats "
             "that need it")
BEAT_L8 = ("beat %d: L8 scope: 'film-grain' may only be a global pick (its catalog scope is "
           "global), but it is a pick for this beat; remove it from this beat, or move it to "
           "global if it suits the whole movie")
HINT = ("An L8 violation is a pick placed where its catalog scope does not allow: give a "
        "physics LoRA the scope either with bin/lora-catalog scope ID either (or the Scope "
        "select of its row in the movie UI's LoRAs tab), or pass --force-story to regenerate; "
        "a style LoRA is only ever a global pick and a motion LoRA only ever a per-beat pick, "
        "so a style LoRA picked for a beat or a motion LoRA picked globally needs "
        "--force-story.")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


def _entries(tmp_path, **scopes):
    """film-grain (style), fast-motion (motion), rain-physics (physics) and ink-stills (stills),
    each with the scope scopes[<first word of its id>] when given."""
    files = str(tmp_path / "files")
    return [
        seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style",
                          scope=scopes.get("film")),
        seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion", scope=scopes.get("fast")),
        seu.catalog_entry(seu.lora_file(files, "rain"), "rain-physics", kind="physics",
                          scope=scopes.get("rain")),
        seu.catalog_entry(seu.lora_file(files, "ink"), "ink-stills", kind="style",
                          target="stills", base_models=[seu.STILLS_MODEL])]


def _ctx(ws, tmp_path, entries=None, **kw):
    entries = _entries(tmp_path) if entries is None else entries
    return seu.make_ctx(se, ws, catalog={"schema_version": 1, "entries": entries}, **kw)


def _pick(entry_id, strength=0.8):
    return {"id": entry_id, "strength": strength}


def _plan(ctx, loras):
    raw = seu.plan_json(ctx.mode, ctx.panels)
    raw["loras"] = dict({"global": [], "per_beat": {}, "stills": []}, **loras)
    return se.normalize_plan(ctx, raw)[0]


def _checks(ctx, loras):
    plan = _plan(ctx, loras)
    compatible = dict((e["id"], e) for e in se.compatible_entries(ctx))
    catalog = dict((e["id"], e) for e in ctx.catalog["entries"])
    return se.lora_checks(ctx, plan, compatible, catalog)


def _catalog_file(story_env):
    return os.path.join(story_env["catalog"], "catalog.json")


# --- LST4 (LS4): the plan prompt groups the catalog by scope -----------------------------------

def test_lst4_the_plan_prompt_groups_the_catalog(ws, tmp_path):
    line = dict((e["id"], se.catalog_line(e)) for e in _entries(tmp_path))
    assert "{" not in se.LORA_PICK_PARAGRAPH and "}" not in se.LORA_PICK_PARAGRAPH
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
    ctx = _ctx(ws, tmp_path, entries=_entries(tmp_path, rain="either"))
    prompt = se.build_plan_prompt(ctx, se.compatible_entries(ctx), [])
    block = ("\n\nLoRA catalog (pick only from these):\n"
             "May be global picks (applied to every panel):\n" + line["film-grain"] + "\n"
             + line["rain-physics"] + "\nMay be per-beat picks (applied to their beat only):\n"
             + line["fast-motion"] + "\n" + line["rain-physics"]
             + "\nStills LoRAs (only for the stills pick):\n" + line["ink-stills"] + "\n\n")
    assert block in prompt
    pins = [{"path": "/p/a.safetensors", "strength": 1.0, "catalog_id": None, "kind": None}]
    stills_off = _ctx(ws, tmp_path, mode="no_stills")
    prompt = se.build_plan_prompt(stills_off, se.compatible_entries(stills_off), pins)
    assert ("May be per-beat picks (applied to their beat only):\n" + line["fast-motion"] + "\n"
            + line["rain-physics"] + "\nAlready applied to every panel by the user, not to be "
            "picked again:\n- a LoRA outside the catalog at strength 1.0\n\n") in prompt
    assert "Stills LoRAs" not in prompt
    files = str(tmp_path / "files")
    motion_only = _ctx(ws, tmp_path, entries=[
        seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion")])
    assert se.catalog_groups(motion_only, motion_only.catalog["entries"]) == [
        "May be global picks (applied to every panel):", "- none, so global stays empty",
        "May be per-beat picks (applied to their beat only):", line["fast-motion"]]
    style_only = _ctx(ws, tmp_path, entries=[_entries(tmp_path)[0]])
    assert se.catalog_groups(style_only, style_only.catalog["entries"]) == [
        "May be global picks (applied to every panel):", line["film-grain"],
        "May be per-beat picks (applied to their beat only):", "- none, so per_beat stays empty"]
    for mode in ("chained", "no_stills", "shots"):
        ctx = _ctx(ws, tmp_path, mode=mode)
        prompt = se.build_plan_prompt(ctx, se.compatible_entries(ctx), [])
        rest = prompt.replace(se.plan_reference(False), "")
        assert "{" not in rest and "}" not in rest, mode
        assert prompt.count("May be global picks (applied to every panel):") == 1, mode


# --- LST5 (LS5): L8 for a pick its catalog scope does not allow ---------------------------------

def test_lst5_a_pick_its_scope_does_not_allow_is_l8(ws, tmp_path):
    ctx = _ctx(ws, tmp_path)
    assert _checks(ctx, {"global": [_pick("fast-motion")]}) == ([GLOBAL_L8], [])
    assert _checks(ctx, {"global": [_pick("rain-physics")]})[0] == [
        GLOBAL_L8.replace("fast-motion", "rain-physics")]
    assert _checks(ctx, {"per_beat": {"1": [_pick("film-grain")], "3": [_pick("film-grain")]}}) == (
        [BEAT_L8 % 1, BEAT_L8 % 3], [])
    assert _checks(ctx, {"global": [_pick("film-grain")],
                         "per_beat": {"2": [_pick("fast-motion")]}}) == ([], [])
    assert [se.parse_violation(m) for m in (GLOBAL_L8, BEAT_L8 % 3)] == [
        {"id": "L8", "name": "scope", "scope": "plan", "index": None, "message": GLOBAL_L8},
        {"id": "L8", "name": "scope", "scope": "beat", "index": 3, "message": BEAT_L8 % 3}]
    either = _ctx(ws, tmp_path, entries=_entries(tmp_path, rain="either"))
    assert _checks(either, {"global": [_pick("rain-physics")]}) == ([], [])
    assert _checks(either, {"per_beat": {"2": [_pick("rain-physics")]}}) == ([], [])
    swapped = _ctx(ws, tmp_path, entries=_entries(tmp_path, rain="global"))
    assert _checks(swapped, {"global": [_pick("rain-physics")]}) == ([], [])
    assert _checks(swapped, {"per_beat": {"2": [_pick("rain-physics")]}})[0] == [
        (BEAT_L8 % 2).replace("film-grain", "rain-physics")]
    fast = dict((e["id"], e) for e in ctx.catalog["entries"])["fast-motion"]
    pinned = ctx._replace(pinned=[{"path": fast["path"], "strength": 0.8,
                                   "catalog_id": "fast-motion", "kind": "motion"}])
    assert _checks(pinned, {}) == ([], [])
    assert _checks(ctx, {"global": [_pick("film-grain"), _pick("film-grain", 0.7)]})[1] == [
        "plan: L2 style: 2 style LoRAs for every panel (film-grain, film-grain); at most 1"]
    assert _checks(ctx._replace(auto_lora=False), {"global": [_pick("fast-motion")]}) == ([], [])


# --- LST6 (LS6): one copy of a LoRA picked both globally and for some beats ---------------------

def test_lst6_a_global_and_per_beat_duplicate_keeps_one_copy(ws, tmp_path):
    for scope in (None, "global"):
        ctx = _ctx(ws, tmp_path, entries=_entries(tmp_path, film=scope, fast="either"))
        plan = _plan(ctx, {"global": [_pick("film-grain"), _pick("fast-motion")],
                           "per_beat": {"1": [_pick("film-grain", 0.6)],
                                        "2": [_pick("film-grain"), _pick("rain-physics")],
                                        "3": [_pick("film-grain")]}})
        assert plan["loras"]["global"] == [_pick("film-grain"), _pick("fast-motion")]
        assert plan["loras"]["per_beat"] == {"2": [_pick("rain-physics")]}
        assert plan["lora_notes"] == [
            "plan: L6 duplicate: 'film-grain' was picked both globally and for beat(s) 1, 2, 3; "
            "the pipeline kept the global pick and dropped the per-beat copies"]
        hard, advisory = _checks(ctx, {"global": [_pick("film-grain")],
                                       "per_beat": {"2": [_pick("film-grain")]}})
        assert hard == [] and advisory == [
            "plan: L6 duplicate: 'film-grain' was picked both globally and for beat(s) 2; the "
            "pipeline kept the global pick and dropped the per-beat copies"]
    ctx = _ctx(ws, tmp_path)
    plan = _plan(ctx, {"global": [_pick("fast-motion", 0.9), _pick("film-grain")],
                       "per_beat": {"3": [_pick("fast-motion", 0.6)],
                                    "1": [_pick("fast-motion", 0.7)]}})
    assert plan["loras"]["global"] == [_pick("film-grain")]
    assert plan["loras"]["per_beat"] == {"3": [_pick("fast-motion", 0.6)],
                                         "1": [_pick("fast-motion", 0.7)]}
    assert plan["lora_notes"] == [
        "plan: L6 duplicate: 'fast-motion' was picked both globally and for beat(s) 1, 3; its "
        "catalog scope is beat, so the pipeline kept the per-beat picks and dropped the global "
        "pick"]
    compatible = dict((e["id"], e) for e in se.compatible_entries(ctx))
    catalog = dict((e["id"], e) for e in ctx.catalog["entries"])
    assert se.lora_checks(ctx, plan, compatible, catalog) == ([], plan["lora_notes"])
    untouched = {"global": [_pick("film-grain"), _pick("nope")],
                 "per_beat": {"9": [_pick("film-grain")], "2": [_pick("nope")]}}
    plan = _plan(ctx, untouched)
    assert plan["loras"]["per_beat"] == untouched["per_beat"] and "lora_notes" not in plan
    assert list(_plan(ctx, {"global": [_pick("film-grain")]}))[-1] == "speech_notes"
    assert "lora_notes" not in _plan(ctx._replace(auto_lora=False), {
        "global": [_pick("film-grain")], "per_beat": {"2": [_pick("film-grain")]}})


# --- LST7 (LS5, LS8): the critic repairs an L8 pick --------------------------------------------

def _panel_script(mode, n):
    return dict((str(k), [seu.answer(seu.panel_json(mode, k))]) for k in range(1, n + 1))


def test_lst7_the_critic_moves_a_per_beat_lora_out_of_global(ws, tmp_path, monkeypatch, capsys):
    ctx = _ctx(ws, tmp_path, mode="shots")
    raw = seu.plan_json("shots", 3)
    raw["loras"] = {"global": [_pick("fast-motion")], "per_beat": {}, "stills": []}
    patches = [{"target": "plan", "index": 0, "field": "lora", "reason": "L8",
                "replacement": []},
               {"target": "plan", "index": 2, "field": "lora", "reason": "L8",
                "replacement": [_pick("fast-motion")]}]
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(raw), seu.answer(raw)],
                           panel=_panel_script("shots", 3),
                           critic=[seu.answer(seu.critic_json(verdict="revise", patches=patches))])
    rc, _advisories = se.run(ctx)
    assert rc == 0
    calls = seu.agent_log(log)
    assert [r["stage"] for r in calls] == ["plan", "plan", "panel", "panel", "panel", "critic"]
    assert ("YOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- " + GLOBAL_L8 + "\n") in (
        calls[1]["argv"][calls[1]["argv"].index("--user-prompt") + 1])
    critic = calls[-1]["argv"][calls[-1]["argv"].index("--user-prompt") + 1]
    assert "- [hard] " + GLOBAL_L8 + "\n" in critic
    line = dict((e["id"], se.catalog_line(e)) for e in ctx.catalog["entries"])
    assert ("from this catalog:\nMay be global picks (applied to every panel):\n"
            + line["film-grain"] + "\nMay be per-beat picks (applied to their beat only):\n"
            + line["fast-motion"] + "\n" + line["rain-physics"] + "\n- target") in critic
    assert line["ink-stills"] not in critic
    with open(os.path.join(ctx.story_dir, "story_rounds", "round_1", "plan.json"),
              encoding="utf-8") as f:
        loras = json.load(f)["loras"]
    assert (loras["global"], loras["per_beat"]) == ([], {"2": [_pick("fast-motion")]})
    assert "critic round 1 (local): continuity=8 story=8 renderability=8 verdict=revise; 2 " \
           "patch(es): 2 applied, 0 rejected" in capsys.readouterr().out
    state = {"plan": dict(_plan(ctx, {}), panels=3), "parts": []}
    _new, applied, rejected = se.apply_patches(ctx, state, [dict(patches[1], index=0)],
                                               lora_allowed=True)
    assert applied == [] and [r["reason"] for r in rejected] == ["would break " + GLOBAL_L8]


# --- LST8 (LS8): a saved plan the new defaults forbid, and how its scope restores it ------------

def test_lst8_recheck_names_l8_and_either_restores_a_saved_plan(ws, tmp_path, monkeypatch,
                                                                capsys):
    entries = _entries(tmp_path, rain="either")
    ctx = _ctx(ws, tmp_path, entries=entries, mode="shots")
    raw = seu.plan_json("shots", 3)
    raw["loras"] = {"global": [_pick("rain-physics")], "per_beat": {}, "stills": []}
    seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(raw)],
                     panel=_panel_script("shots", 3))
    assert se.run(ctx)[0] == 0
    capsys.readouterr()

    def never(*args):
        raise AssertionError("a shots re-check with a plan never runs the legacy validator")

    default = ctx._replace(catalog={"schema_version": 1, "entries": _entries(tmp_path)})
    assert se.recheck(default, never)[0] == 2
    err = capsys.readouterr().err
    assert "  - " + GLOBAL_L8.replace("fast-motion", "rain-physics") + "\n" in err
    assert err.endswith("rerun with --no-auto-lora, or pass --force-story to regenerate.\n"
                        + HINT + "\n")
    with open(os.path.join(ctx.story_dir, "story_checks.json"), encoding="utf-8") as f:
        assert [v["id"] for v in json.load(f)["hard"]] == ["L8"]
    assert se.recheck(ctx, never)[0] == 0
    assert HINT not in capsys.readouterr().err
    gone = ctx._replace(catalog={"schema_version": 1, "entries": []})
    assert se.recheck(gone, never)[0] == 2
    assert HINT not in capsys.readouterr().err


# --- LST9 (LS4, LS9): the dry run prints the grouped catalog -----------------------------------

def test_lst9_the_dry_run_prints_the_grouped_catalog(tmp_path, story_env):
    entries = _entries(tmp_path)
    seu.make_catalog(story_env["catalog"], entries[:2])
    story_dir = os.path.join(WS, "generated", "stories", "lst9-%d" % os.getpid())
    proc = subprocess.run([sys.executable, os.path.join(WS, "bin", "ltx-movie"), NARRATIVE,
                           "--story-id", os.path.basename(story_dir), "--dry-run", "--no-review",
                           "--shots", "--panels", "4"], cwd=WS, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert ("LoRA catalog (pick only from these):\nMay be global picks (applied to every "
            "panel):\n" + se.catalog_line(entries[0]) + "\nMay be per-beat picks (applied to "
            "their beat only):\n" + se.catalog_line(entries[1]) + "\n\n") in proc.stdout
    assert "Catalog LoRAs: 2 compatible entries in %s" % _catalog_file(story_env) in proc.stdout
    assert not os.path.exists(story_dir)
