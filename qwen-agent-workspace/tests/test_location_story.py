"""Tests for the location library's story use (docs/superpowers/specs/
2026-10-29-location-lora-design.md, Sections 4.3-4.6 and 6.7: LS1-LS14, with the plan's Review
Focus pins): the plan prompt's fixed places, plan normalisation, P21 location presence and the
L4 LoRA count.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_location_story.py
Stdlib plus pytest. No test reads the real HOME, renders, trains, runs Z-Image or the editor,
contacts a model server or touches port 8178: every model call goes to the fake bin/qwen-agent of
a temporary workspace (story_engine_testutil.make_ws), and every test runs under the autouse
story_env fixture (a temporary HOME, character library, location library and LoRA catalog). The
plan fixtures under tests/fixtures/location/ were written at d210c26, before story_engine.py was
edited (spec 6.3).
"""

import importlib.machinery
import json
import os
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import location_testutil as lt  # noqa: E402
import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


se = _load("story_engine_for_location_story", "story_engine.py")
cl = _load("character_lib_for_location_story", "character_lib.py")
ll = _load("location_lib_for_location_story", "location_lib.py")
FIXTURES = os.path.join(WS, "tests", "fixtures", "location")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    env = seu.set_story_env(monkeypatch, tmp_path)
    env["locations"] = os.path.join(str(tmp_path), "locations")
    os.makedirs(env["locations"], exist_ok=True)
    monkeypatch.setenv("LOCATION_LIBRARY_DIR", env["locations"])
    return env


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


# --- LS1: without locations, every plan prompt and plan.json is byte-identical (LK5) ---------

def test_ls1_without_locations_plan_prompts_and_plans_are_byte_identical(ws, story_env):
    seu.kyra(story_env["lib"])
    seu.ronin(story_env["lib"])
    members = cl.resolve_cast([(None, "kyra"), (None, "ronin")])
    for name, kw in (("plan_prompt_chained.txt", dict(mode="chained")),
                     ("plan_prompt_shots.txt", dict(mode="shots", panels=4)),
                     ("plan_prompt_chained_cast.txt", dict(mode="chained", members=members))):
        with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
            expected = f.read()
        assert se.build_plan_prompt(seu.make_ctx(se, ws, **kw), [], []) == expected, name
    plan, _shape = se.normalize_plan(seu.make_ctx(se, ws), seu.plan_json("chained", 3))
    with open(os.path.join(FIXTURES, "normalized_plan_chained.json"), encoding="utf-8") as f:
        assert json.dumps(plan, indent=2, sort_keys=True) == f.read()
    assert [sorted(entry) for entry in plan["locations"]] == [["id", "setting"]] * 2


# --- Task 6 helpers -------------------------------------------------------------------------

def _pin(name, description, trigger, attach=True):
    return ll.LocationPin(name, trigger, description, "/lib/%s/lora/video.safetensors" % name,
                          None, None, None, "dgrauet/ltx-2.3-mlx-q8", attach)


HARBOUR = _pin("harbour-street", lt.HARBOUR_DESC, "harboplc")
TEMPLE = _pin("temple-gate", lt.TEMPLE_DESC, "templplc")
P21 = ("plan: P21 location presence: %s (library location %s) is the location of no beat; every "
       "already-set place is in this movie, so give at least one beat the location %s")


def _raw(mode, n, beat_locations, own=("l3",)):
    """seu.plan_json(mode, n) with locations l1, l2 (the planner's own text) plus own, and beat k
    at beat_locations[k - 1]."""
    raw = seu.plan_json(mode, n)
    raw["locations"] = ([{"id": "l1", "setting": seu.HARBOUR}, {"id": "l2", "setting": seu.TEMPLE}]
                        + [{"id": i, "setting": "The setting is a quiet orchard of old apple "
                                                "trees on a grassy slope under a pale sky."}
                           for i in own])
    for beat, loc in zip(raw["beats"], beat_locations):
        beat["location"] = loc
    return raw


def _p21(ctx, raw):
    plan, shape = se.normalize_plan(ctx, raw)
    return [h for h in se.plan_checks(ctx, plan, shape)[0] if " P21 " in h]


# --- LS2, LS3, LS13, LS14: the constants, the plan prompt, the context, no new import (L3.3) --

def test_ls2_the_location_constants():
    assert se.LOCATION_FIXED_INTRO == (
        " The following places are already set; list them first in locations with exactly these "
        "ids and settings, and give your own places the next ids. Every one of them is in this "
        "movie: give each one's id as the location of at least one beat. When the narrative names "
        "or describes one of them, it means that place:")
    assert se.LOCATION_FIXED_LINE == '\n- id l%d, name "%s", setting "%s"'
    assert se.FIXED_SETTING == "The setting is %s."
    assert "background.@@LOCATION_FIXED@@\n" in se.PLAN_PROMPT_TEMPLATE
    assert se.PLAN_PROMPT_TEMPLATE.count("@@LOCATION_FIXED@@") == 1


def test_ls3_the_plan_prompt_lists_the_pinned_places(ws):
    prompt = se.build_plan_prompt(seu.make_ctx(se, ws, locations=[HARBOUR, TEMPLE]), [], [])
    fixed = (se.LOCATION_FIXED_INTRO
             + '\n- id l1, name "harbour-street", setting "The setting is %s."' % lt.HARBOUR_DESC
             + '\n- id l2, name "temple-gate", setting "The setting is %s."' % lt.TEMPLE_DESC)
    assert ("any crowd or other group of people in the background." + fixed + "\nprops: ") in prompt
    assert prompt.count(se.LOCATION_FIXED_INTRO) == 1
    one = se.build_plan_prompt(seu.make_ctx(se, ws, locations=[TEMPLE]), [], [])
    assert ('background.' + se.LOCATION_FIXED_INTRO
            + '\n- id l1, name "temple-gate", setting "The setting is %s."\nprops: '
            % lt.TEMPLE_DESC) in one
    plain = se.build_plan_prompt(seu.make_ctx(se, ws), [], [])
    assert "@@LOCATION_FIXED@@" not in plain and se.LOCATION_FIXED_INTRO not in plain
    assert "in the background.\nprops: " in plain


def test_ls13_story_context_defaults(ws):
    assert se.StoryContext._fields[-1] == "locations"
    assert se.StoryContext._field_defaults == {"clip_seconds": None, "panels_target": None,
                                               "length": None, "locations": (),
                                               "narration": True}
    assert seu.make_ctx(se, ws).locations == ()


def test_ls14_story_engine_gains_no_import():
    import ast
    import subprocess
    old = subprocess.run(["git", "-C", WS, "show", "d210c26:./story_engine.py"],
                         capture_output=True, text=True)
    if old.returncode != 0:
        pytest.skip("not a git checkout with d210c26")

    def imports(text):
        return sorted(ast.dump(node) for node in ast.walk(ast.parse(text))
                      if isinstance(node, (ast.Import, ast.ImportFrom)))

    with open(os.path.join(WS, "story_engine.py"), encoding="utf-8") as f:
        assert imports(f.read()) == imports(old.stdout)


# --- LS4, LS5: plan normalisation (L3.4) ----------------------------------------------------

def test_ls4_pinned_locations_are_l1_to_lk(ws):
    ctx = seu.make_ctx(se, ws, locations=[HARBOUR, TEMPLE])
    plan, _shape = se.normalize_plan(ctx, _raw("chained", 3, ["l1", "Harbour-Street", "l3"]))
    assert plan["locations"] == [
        {"id": "l1", "setting": "The setting is %s." % lt.HARBOUR_DESC,
         "location_name": "harbour-street"},
        {"id": "l2", "setting": "The setting is %s." % lt.TEMPLE_DESC,
         "location_name": "temple-gate"},
        {"id": "l3", "setting": ("The setting is a quiet orchard of old apple trees on a grassy "
                                 "slope under a pale sky."), "location_name": None}]
    assert [b["location"] for b in plan["beats"]] == ["l1", "l1", "l3"]
    raw = _raw("chained", 3, ["l1", "temple-gate", "l1"], own=())
    raw["locations"] = raw["locations"][:1]
    plan, _shape = se.normalize_plan(ctx, raw)
    assert [(e["id"], e["location_name"]) for e in plan["locations"]] == [
        ("l1", "harbour-street"), ("l2", "temple-gate")]
    assert [b["location"] for b in plan["beats"]] == ["l1", "l2", "l1"]
    raw = _raw("chained", 3, ["l2", "l2", "l3"], own=("l3",))
    raw["locations"] = raw["locations"][1:]
    plan, _shape = se.normalize_plan(seu.make_ctx(se, ws, locations=[HARBOUR]), raw)
    assert [(e["id"], e["location_name"]) for e in plan["locations"]] == [
        ("l1", "harbour-street"), ("l2", None), ("l3", None)]


def test_ls5_a_pinned_setting_is_fixed(ws):
    ctx = seu.make_ctx(se, ws, locations=[HARBOUR])
    raw = _raw("chained", 3, ["l1", "l1", "l2"])
    raw["locations"][0]["setting"] = "The setting is a different harbour the planner wrote."
    plan, _shape = se.normalize_plan(ctx, raw)
    assert plan["locations"][0]["setting"] == se.FIXED_SETTING % lt.HARBOUR_DESC
    assert se.patch_ranges(ctx, plan, True)[("plan", "location.setting")] == se.NOT_REPAIRED


# --- LS6, LS9, LS10, LS11: P21 and the LoRA count (L3.5, L3.6) ------------------------------

@pytest.mark.parametrize("mode", ["chained", "shots", "no_stills"])
def test_ls6_the_p21_matrix(ws, mode):
    ctx = seu.make_ctx(se, ws, mode=mode, locations=[HARBOUR, TEMPLE])
    for beats, missing in ((["l2", "l2", "l3"], ["l1"]), (["l1", "l3", "l1"], ["l2"]),
                           (["l3", "l3", "l3"], ["l1", "l2"])):
        found = _p21(ctx, _raw(mode, 3, beats))
        names = {"l1": "harbour-street", "l2": "temple-gate"}
        assert found == [P21 % (i, names[i], i) for i in missing], (mode, beats)
        parsed = se.parse_violation(found[0])
        assert (parsed["id"], parsed["name"], parsed["scope"]) == ("P21", "location presence",
                                                                   "plan")
    assert _p21(ctx, _raw(mode, 3, ["l1", "l2", "l3"])) == []
    assert _p21(ctx, _raw(mode, 3, ["l1", "l2", "l2"], own=("l3", "l4"))) == []
    assert _p21(seu.make_ctx(se, ws, mode=mode), _raw(mode, 3, ["l3", "l3", "l3"])) == []


def _engine_run(ws, tmp_path, monkeypatch, story_id, plans, members=(), locations=(HARBOUR,)):
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(p) for p in plans],
                           panel=dict((str(k), [seu.answer(seu.panel_json("chained", k))])
                                      for k in range(1, 4)))
    ctx = seu.make_ctx(se, ws, story_id=story_id, members=list(members),
                       locations=list(locations))
    rc, _advisories = se.run(ctx)
    return rc, ctx, seu.agent_log(log)


def test_ls8_two_plans_without_the_location_are_fatal(ws, tmp_path, monkeypatch, capsys):
    bad = _raw("chained", 3, ["l2", "l2", "l2"])
    capsys.readouterr()
    rc, ctx, log = _engine_run(ws, tmp_path, monkeypatch, "ls8", [bad, bad])
    assert rc == 1 and [r["stage"] for r in log] == ["plan", "plan"]
    assert capsys.readouterr().err == (
        "Error: the story model did not return a usable plan after 2 call(s)\n"
        "  - %s\nRaw replies are kept in %s. Rerun the same command to try again.\n"
        % (P21 % ("l1", "harbour-street", "l1"),
           os.path.join(ctx.story_dir, "story_rounds", "round_0")))
    for name in ("story.md", "plan.json"):
        assert not os.path.exists(os.path.join(ctx.story_dir, name)), name


def test_ls9_p21_and_p16_are_retried_together(ws, tmp_path, monkeypatch, story_env):
    seu.kyra(story_env["lib"])
    members = cl.resolve_cast([(None, "kyra")])
    bad = _raw("chained", 3, ["l2", "l2", "l2"])
    for beat in bad["beats"]:
        beat["cast"] = ["c2"]
    good = _raw("chained", 3, ["l1", "l2", "l1"])
    rc, _ctx, log = _engine_run(ws, tmp_path, monkeypatch, "ls9", [bad, good], members=members)
    assert rc == 0
    retry = [r for r in log if r["stage"] == "plan"][1]["argv"][-1]
    assert "\n- " + P21 % ("l1", "harbour-street", "l1") + "\n" in retry
    assert "\n- plan: P16 cast presence: c1 " in retry


def _lora_ctx(ws, tmp_path, story_env, attach):
    files = str(tmp_path / "files")
    entries = [seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style"),
               seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion")]
    seu.kyra(story_env["lib"])
    pinned = [{"path": seu.lora_file(files, "pinned"), "strength": 1.0, "catalog_id": None,
               "kind": None}]
    return seu.make_ctx(se, ws, members=cl.resolve_cast([(None, "kyra")]),
                        catalog={"schema_version": 1, "entries": entries}, pinned=pinned,
                        locations=[HARBOUR._replace(attach_video=attach)])


def test_ls10_l4_counts_an_attached_location(ws, tmp_path, story_env):
    for attach, expected in ((True, [
            "beat 1: L4 LoRA count: 5 LoRAs on this panel (pinned LoRA, film-grain, fast-motion, "
            "location harbour-street, character kyra); at most 4"]), (False, [])):
        ctx = _lora_ctx(ws, tmp_path / str(attach), story_env, attach)
        raw = _raw("chained", 3, ["l1", "l2", "l1"])
        raw["loras"] = {"global": [{"id": "film-grain", "strength": 0.8}],
                        "per_beat": {"1": [{"id": "fast-motion", "strength": 0.7}]}, "stills": []}
        plan, _shape = se.normalize_plan(ctx, raw)
        compatible = dict((e["id"], e) for e in se.compatible_entries(ctx))
        catalog = dict((e["id"], e) for e in ctx.catalog["entries"])
        hard, advisory = se.lora_checks(ctx, plan, compatible, catalog)
        assert hard == [] and [a for a in advisory if " L4 " in a] == expected, attach
        assert [a for a in advisory if " L3 " in a] == []


def test_ls11_shots_images_paste_the_fixed_setting(ws):
    ctx = seu.make_ctx(se, ws, mode="shots", locations=[HARBOUR])
    plan, _shape = se.normalize_plan(ctx, _raw("shots", 3, ["l1", "l2", "l1"]))
    for k in (1, 3):
        assert se.pasted_pieces(ctx, plan, k)["image"][0] == se.FIXED_SETTING % lt.HARBOUR_DESC
    assert se.pasted_pieces(ctx, plan, 2)["image"][0] == seu.TEMPLE


def test_ls12_recheck_never_runs_plan_checks(ws, tmp_path, monkeypatch):
    rc, ctx, _log = _engine_run(ws, tmp_path, monkeypatch, "ls12",
                                [_raw("chained", 3, ["l1", "l2", "l1"])])
    assert rc == 0

    def refuse(*args, **kwargs):
        raise AssertionError("recheck must not call plan_checks")

    monkeypatch.setattr(se, "plan_checks", refuse)
    rc, _advisories = se.recheck(ctx, lambda path, panels, no_stills=False: [])
    assert rc == 0


# --- LS7: the plan retry end to end through bin/ltx-movie (L3.5) -------------------------------

ltx_movie = _load("ltx_movie_for_location_story", os.path.join("bin", "ltx-movie"))


@pytest.fixture
def movie(tmp_path, monkeypatch):
    """A temp workspace with the fake agent; ltx_movie.WS points at it; no sudo check."""
    ws = seu.make_ws(tmp_path)
    monkeypatch.setattr(ltx_movie, "WS", ws)
    monkeypatch.setattr(ltx_movie, "_check_sudo_and_start_keepalive", lambda: None)
    return ws


def test_ls7_a_plan_without_the_location_is_retried(movie, tmp_path, monkeypatch, story_env):
    lt.harbour(story_env["locations"])
    log = seu.script_agent(
        monkeypatch, tmp_path,
        plan=[seu.answer(_raw("chained", 3, ["l2", "l2", "l2"])),
              seu.answer(_raw("chained", 3, ["l1", "l2", "l1"]))],
        panel=dict((str(k), [seu.answer(seu.panel_json("chained", k))]) for k in range(1, 4)))
    rc = ltx_movie.main(["A courier carries a sealed letter across a rainy harbour town.",
                         "--story-id", "ls7", "--panels", "3",
                         "--location", "harbour-street", "--story-only", "--no-review"])
    log = seu.agent_log(log)
    assert rc == 0
    assert [r["stage"] for r in log][:3] == ["plan", "plan", "panel"]
    assert ("YOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- "
            + P21 % ("l1", "harbour-street", "l1") + "\n") in log[1]["argv"][-1]
    with open(os.path.join(movie, "generated", "stories", "ls7", "plan.json")) as f:
        plan = json.load(f)
    assert plan["locations"][0] == {"id": "l1", "setting": se.FIXED_SETTING % lt.HARBOUR_DESC,
                                    "location_name": "harbour-street"}
    assert [b["location"] for b in plan["beats"]] == ["l1", "l2", "l1"]
