"""Tests for location_lib.py (docs/superpowers/specs/2026-10-29-location-lora-design.md,
Sections 2.2-2.4, 3.6-3.9 and 4.7, test table 6.4: LL1-LL14): the description and trigger rules,
the location.json schema, library I/O, resolution of pinned locations, model compatibility, the
trigger prefix and the plan reader.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_location_lib.py
Stdlib plus pytest. No test reads the real HOME, renders, trains, runs Z-Image or the editor,
contacts a model server or touches port 8178: every test runs under the autouse env fixture
(HOME, CHARACTER_LIBRARY_DIR, LOCATION_LIBRARY_DIR and LORA_CATALOG_DIR under tmp_path), and every
LoRA file is a few bytes.
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

import location_testutil as lt  # noqa: E402
import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


ll = _load("location_lib_for_tests", "location_lib.py")
cl = _load("character_lib_for_location_tests", "character_lib.py")
se = _load("story_engine_for_location_lib", "story_engine.py")


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


def _words(n, start="a"):
    """A valid description of exactly n words: start, then n - 1 distinct stone words."""
    return " ".join([start] + ["stone%d" % k for k in range(1, n)])


def _raises(fn, *args):
    with pytest.raises(ll.LocationError) as info:
        fn(*args)
    return str(info.value)


# --- LL2, LL3: the description rule and its arithmetic (L1.3) ------------------------------

def test_ll2_the_description_rule():
    assert ll.normalize_description("  The  old mill by the weir.") == "the old mill by the weir"
    assert ll.normalize_description("A quay\n with  boats") == "a quay with boats"
    assert ll.normalize_description(7) == 7
    ll.validate_description(_words(15))
    ll.validate_description(_words(40))
    assert _raises(ll.validate_description, _words(14)) == "description: must be 15-40 words, got 14"
    assert _raises(ll.validate_description, _words(41)) == "description: must be 15-40 words, got 41"
    rule4 = "description: must be one noun phrase with no . ! ? or double quote"
    body = " ".join("stone%d" % k for k in range(1, 20))
    for text in ("a quay. With " + body, "a quay! " + body, 'a quay "old" ' + body,
                 "a quay\n" + body, "a quay\r" + body, "a quay? " + body):
        assert _raises(ll.validate_description, text) == rule4, text
    assert _raises(ll.validate_description, "one quay " + body) == (
        'description: must start with "a ", "an " or "the "')
    assert _raises(ll.validate_description, " a quay " + body).startswith(
        "description: must be a string without leading or trailing whitespace")
    assert _raises(ll.validate_description, None).startswith("description: must be a string")
    for start in ("a", "an", "the"):
        ll.validate_description(_words(20, start))
    ll.validate_description(lt.HARBOUR_DESC)
    ll.validate_description(lt.TEMPLE_DESC)
    ll.validate_description(lt.MILL_DESC)
    assert [len(d.split()) for d in (lt.HARBOUR_DESC, lt.TEMPLE_DESC, lt.MILL_DESC)] == [24, 30, 20]


def test_ll3_the_setting_arithmetic():
    for w in range(15, 41):
        description = _words(w)
        ll.validate_description(description)
        setting = "The setting is %s." % description
        assert len(setting.split()) == w + 3
        assert se._setting_problems(setting) == []
        assert se._setting_length(setting) is None
    assert 15 + 3 >= cl.SHOTS_SETTING_MIN_WORDS == 12
    assert (ll.DESCRIPTION_MIN_WORDS, ll.DESCRIPTION_MAX_WORDS) == (15, 40)


# --- LL4, LL5: triggers and the registry (L1.4) ---------------------------------------------

def test_ll4_triggers(env):
    assert ll.TRIGGER_RE.pattern == cl.TRIGGER_RE.pattern
    assert ll.NAME_RE.pattern == cl.NAME_RE.pattern
    assert ll.auto_trigger("harbour-street", lt.HARBOUR_DESC, set()) == "harboplc"
    assert ll.auto_trigger("harbour-street", lt.HARBOUR_DESC, {"harboplc"}) == "harboplc2"
    assert ll.auto_trigger("old-mill", lt.MILL_DESC, set()) == "oldmiplc"
    assert ll.auto_trigger("harbour-street", "a harboplc " + lt.HARBOUR_DESC[2:], set()) == (
        "harboplc2")
    cl.register_trigger("kyrawmn", "kyra")
    owners = ll.all_triggers()
    assert owners["kyrawmn"] == "character kyra"
    ll.register_trigger("harboplc", "harbour-street")
    assert ll.all_triggers()["harboplc"] == "location harbour-street"
    ll.validate_trigger("harbour1")
    assert _raises(ll.validate_trigger, "Bad") == "trigger must match [a-z][a-z0-9]{3,15}, got 'Bad'"
    assert _raises(ll.validate_trigger, "harbour", lt.HARBOUR_DESC) == (
        "trigger harbour must not be a word of the description")
    ll.validate_trigger("harboplc", lt.HARBOUR_DESC)
    assert ll.description_words("A Quay, with 2 boats") == ["a", "quay", "with", "2", "boats"]


def test_ll5_the_registry(env):
    lib = env["locations"]
    ll.register_trigger("harboplc", "harbour-street")
    with open(os.path.join(lib, ".triggers"), encoding="utf-8") as f:
        assert f.read() == "harboplc harbour-street\n"
    lt.temple(lib)
    assert ll.registered_triggers() == {"harboplc": "harbour-street", "templplc": "temple-gate"}
    # A failed create leaves its trigger registered: never reused.
    ll.register_trigger("deadpplc", "dead-place")
    assert "deadpplc" in ll.registered_triggers()
    assert ll.auto_trigger("dead-place", lt.MILL_DESC, set(ll.all_triggers())) == "deadpplc2"


# --- LL6, LL14: the validation table (L2.7) -------------------------------------------------

def _valid(env, **kw):
    return lt.make_location(env["locations"], "harbour-street", "harboplc", lt.HARBOUR_DESC, **kw)


def test_ll6_the_validation_table(env):
    for kw in (dict(), dict(status="untrained"), dict(status="dataset"), dict(source="photos"),
               dict(stills=True), dict(strength=0.6)):
        ll.validate_location(_valid(env, **kw), name="harbour-street")
    base = _valid(env, stills=True)
    cases = [
        (lambda d: d.pop("strength"), "top level"),
        (lambda d: d.update(extra=1), "top level"),
        (lambda d: d.update(schema_version=2), "schema_version"),
        (lambda d: d.update(schema_version=True), "schema_version"),
        (lambda d: d.update(name="Bad_name"), "name"),
        (lambda d: d.update(trigger="Harbo"), "trigger"),
        (lambda d: d.update(trigger="harbour"), "trigger"),
        (lambda d: d.update(description="a quay"), "description"),
        (lambda d: d.update(source="video"), "source"),
        (lambda d: d.update(photos=[{"path": "/p.jpg", "sha256": "0" * 64}]), "photos"),
        (lambda d: d.update(source="photos", photos=[]), "photos"),
        (lambda d: d.update(source="photos", photos=[{"path": "rel.jpg", "sha256": "0" * 64}]),
         "photos"),
        (lambda d: d.update(source="photos", photos=[{"path": None, "sha256": "XY"}]), "photos"),
        (lambda d: d.update(seed=-1), "seed"),
        (lambda d: d.update(seed=True), "seed"),
        (lambda d: d.update(status="ready"), "status"),
        (lambda d: d.update(created_at="2026-10-29 10:00:00"), "created_at"),
        (lambda d: d.update(trained_at="yesterday"), "trained_at"),
        (lambda d: d["dataset"].update(kept=25), "dataset"),
        (lambda d: d["dataset"].update(min_score=0), "dataset"),
        (lambda d: d["dataset"].update(contact_sheet="sheet.jpg"), "dataset"),
        (lambda d: d["dataset"].pop("min_score"), "dataset"),
        (lambda d: d["loras"].pop("stills"), "loras"),
        (lambda d: d["loras"]["video"].update(path="lora.safetensors"), "loras.video"),
        (lambda d: d["loras"]["video"].update(sha256="ABC"), "loras.video"),
        (lambda d: d["loras"]["video"].update(base_model=""), "loras.video"),
        (lambda d: d["loras"]["video"].update(rank=0), "loras.video"),
        (lambda d: d["loras"]["video"].update(alpha=16), "loras.video"),
        (lambda d: d["loras"]["video"].update(steps=0), "loras.video"),
        (lambda d: d["loras"]["stills"].update(extra=1), "loras.stills"),
        (lambda d: d.update(stills_skip_reason=""), "stills_skip_reason"),
        (lambda d: d.update(strength=0), "strength"),
        # Consistency: trained exactly when loras.video and trained_at are set; untrained and
        # trained need a dataset with at least MIN_KEEP kept stills.
        (lambda d: d["loras"].update(video=None), "status"),
        (lambda d: d.update(trained_at=None), "trained_at"),
        (lambda d: d.update(status="untrained"), "status"),
        (lambda d: d.update(dataset=None), "status"),
        (lambda d: d["dataset"].update(kept=11), "status"),
    ]
    for mutate, field in cases:
        data = json.loads(json.dumps(base))
        mutate(data)
        message = _raises(ll.validate_location, data)
        assert message.startswith(field + ":"), (field, message)
    untrained = _valid(env, status="untrained")
    untrained["dataset"]["kept"] = 11
    assert _raises(ll.validate_location, untrained) == (
        "status: 'untrained' requires a dataset with at least 12 kept stills")
    assert _raises(ll.validate_location, dict(_valid(env), name="harbour-street"),
                   "other-name").startswith("name: 'harbour-street' does not match")


def test_ll14_the_strength_rule(env):
    ll.validate_location(_valid(env, strength=1.0))
    ll.validate_location(_valid(env, strength=1))
    for bad in (0, 1.01, True, "0.5", -0.2):
        assert _raises(ll.validate_location, _valid(env, strength=bad)).startswith(
            "strength: must be null or a number in (0, 1]"), bad


# --- LL7: library I/O -----------------------------------------------------------------------

def test_ll7_io(env):
    lib = env["locations"]
    data = lt.harbour(lib)
    ldir = os.path.join(lib, "harbour-street")
    data["strength"] = 0.5
    ll.write_location(data)
    assert ll.load_location("harbour-street")["strength"] == 0.5
    assert [n for n in os.listdir(ldir) if n.endswith(".tmp")] == []
    with open(os.path.join(ldir, "location.json"), encoding="utf-8") as f:
        before = f.read()
    assert before.endswith("}\n")
    data["strength"] = 2.0
    with pytest.raises(ll.LocationError):
        ll.write_location(data)
    with open(os.path.join(ldir, "location.json"), encoding="utf-8") as f:
        assert f.read() == before
    assert [n for n in os.listdir(ldir) if n.endswith(".tmp")] == []
    path = os.path.join(lib, "nowhere", "location.json")
    assert _raises(ll.load_location, "nowhere") == "unknown location: nowhere (no %s)" % path
    os.makedirs(os.path.join(lib, "broken"))
    with open(os.path.join(lib, "broken", "location.json"), "w") as f:
        f.write("{bad")
    assert _raises(ll.load_location, "broken").startswith("invalid location.json for broken: ")
    assert _raises(ll.load_location, "Bad") == (
        "location name must match [a-z][a-z0-9-]{1,23}, got 'Bad'")
    os.makedirs(os.path.join(lib, "Not_A_Name"))
    os.makedirs(os.path.join(lib, "empty-dir"))
    assert ll.list_names() == ["broken", "harbour-street"]
    assert ll.library_dir() == lib
    assert ll.location_dir("x") == os.path.join(lib, "x")


# --- LL8, LL9: resolution and model compatibility (L2.8, L2.9) ------------------------------

def test_ll8_resolution(env):
    lib = env["locations"]
    harbour = lt.harbour(lib, stills=True, strength=0.6)
    lt.temple(lib)
    lt.mill(lib, status="untrained")
    pins = ll.resolve_locations(["harbour-street", "temple-gate"])
    assert pins[0] == ll.LocationPin(
        "harbour-street", "harboplc", lt.HARBOUR_DESC, harbour["loras"]["video"]["path"],
        harbour["loras"]["stills"]["path"], None, 0.6, "dgrauet/ltx-2.3-mlx-q8", True)
    assert (pins[1].name, pins[1].stills_lora, pins[1].strength, pins[1].attach_video) == (
        "temple-gate", None, None, True)
    assert _raises(ll.resolve_locations, ["a", "b", "c", "d"]) == "at most 3 locations, got 4"
    assert _raises(ll.resolve_locations, ["temple-gate", "temple-gate"]) == (
        "location temple-gate is pinned more than once")
    with pytest.raises(ll.UnusableLocationError) as info:
        ll.resolve_locations(["old-mill"])
    assert str(info.value) == ("location old-mill is not trained (status untrained); run "
                               "bin/location train old-mill")
    with pytest.raises(ll.UnusableLocationError) as info:
        ll.resolve_locations(["nowhere"])
    assert str(info.value).startswith("unknown location: nowhere (no ")
    open(os.path.join(lib, "temple-gate", "lora", "video.safetensors"), "wb").close()
    with pytest.raises(ll.UnusableLocationError) as info:
        ll.resolve_locations(["temple-gate"])
    assert str(info.value) == "location temple-gate's video LoRA is missing or empty: %s" % (
        os.path.join(lib, "temple-gate", "lora", "video.safetensors"))
    os.remove(harbour["loras"]["stills"]["path"])
    with pytest.raises(ll.LocationError) as info:
        ll.resolve_locations(["harbour-street"])
    assert not isinstance(info.value, ll.UnusableLocationError)
    assert str(info.value) == "location harbour-street's stills LoRA is missing or empty: %s" % (
        harbour["loras"]["stills"]["path"])
    lt.make_location(lib, "dock-one", "dockplc", lt.HARBOUR_DESC)
    lt.make_location(lib, "dock-two", "dockplc", lt.MILL_DESC)
    assert _raises(ll.resolve_locations, ["dock-one", "dock-two"]) == (
        "locations dock-one and dock-two share the trigger dockplc")
    assert ll.usable_locations() == ["dock-one", "dock-two"]
    assert ll.format_available_line([]) == (
        "available locations: none (create one with bin/location create)")
    assert ll.format_available_line(["dock-one", "dock-two"]) == (
        "available locations: dock-one, dock-two")
    assert ll.resolve_locations([]) == []


def test_ll9_model_compatibility(env, monkeypatch, tmp_path):
    mlx = tmp_path / "ltx-2-mlx"
    (mlx / "models" / "ltx-2.3-mlx-q8").mkdir(parents=True)
    os.symlink(str(mlx / "models" / "ltx-2.3-mlx-q8"), str(tmp_path / "q8-link"))
    monkeypatch.setenv("LTX2_MLX_DIR", str(mlx))
    base = ll.VIDEO_BASE_MODEL
    assert base == "dgrauet/ltx-2.3-mlx-q8"
    assert ll.model_compatible(base, "dgrauet/ltx-2.3-mlx-q8") is True
    assert ll.model_compatible(base, str(mlx / "models" / "ltx-2.3-mlx-q8")) is True
    assert ll.model_compatible(base, str(tmp_path / "q8-link")) is True
    assert ll.model_compatible(base, "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8") is False
    assert ll.model_compatible(base, "~/ltx-2-mlx/models/ltx-2.5-mlx-q8") is False
    assert ll.model_compatible("other/base", "other/base") is True
    assert ll.model_compatible("other/base", str(mlx / "models" / "ltx-2.3-mlx-q8")) is False


# --- LL10, LL11: the trigger prefix and the plan reader (L3.7) -------------------------------

def test_ll10_the_trigger_prefix():
    assert ll.prefix_location_trigger("A street.", "harboplc") == "harboplc. A street."
    for prompt in ("harboplc. A street.", "A HARBOPLC street.", "The street (Harboplc) waits."):
        assert ll.prefix_location_trigger(prompt, "harboplc") == prompt
    assert ll.prefix_location_trigger("A xharboplc street.", "harboplc") == (
        "harboplc. A xharboplc street.")
    assert ll.prefix_location_trigger("A harboplc-x street.", "harboplc") == (
        "harboplc. A harboplc-x street.")


def test_ll11_the_plan_reader(tmp_path):
    story = str(tmp_path / "story")
    os.makedirs(story)
    assert ll.plan_panel_locations(story, 2, ["harbour-street"]) == ([None, None], (
        "note: there is no plan.json for this story; no location LoRAs are attached (location "
        "LoRAs attach only to planned beats)"))
    assert ll.plan_location_names(story) is None
    path = os.path.join(story, "plan.json")
    note = "note: plan.json is not usable for locations (%s); no location LoRAs are attached"
    for text, reason in (("{bad", "it is unreadable or not a JSON object"),
                         ("[]", "it is unreadable or not a JSON object"),
                         ('{"schema": "x"}', "its schema is not ltx-movie.plan.v1"),
                         ('{"schema": "ltx-movie.plan.v1", "locations": "l1"}',
                          "its locations are not a list of objects"),
                         ('{"schema": "ltx-movie.plan.v1", "locations": ["l1"]}',
                          "its locations are not a list of objects")):
        with open(path, "w") as f:
            f.write(text)
        assert ll.plan_panel_locations(story, 2, ["harbour-street"]) == ([None, None],
                                                                         note % reason), text
        assert ll.plan_location_names(story) is None, text
    lt.write_plan(story, ["l1", "l2", "l1"])
    assert ll.plan_panel_locations(story, 2, ["harbour-street"]) == (
        [None, None], note % "it has 3 beats for 2 panels")
    plan = lt.write_plan(story, ["l1", "l2"])
    plan["beats"][1]["location"] = ""
    with open(path, "w") as f:
        json.dump(plan, f)
    assert ll.plan_panel_locations(story, 2, ["harbour-street"]) == (
        [None, None], note % "beat 2 has no location id")
    lt.write_plan(story, ["l1", "l2", "l1", "l9", "l3"],
                  pinned=(("l1", "harbour-street"), ("l3", "temple-gate")))
    assert ll.plan_panel_locations(story, 5, ["harbour-street"]) == (
        ["harbour-street", None, "harbour-street", None, None], None)
    assert ll.plan_panel_locations(story, 5, ["harbour-street", "temple-gate"]) == (
        ["harbour-street", None, "harbour-street", None, "temple-gate"], None)
    assert ll.plan_panel_locations(story, 5, []) == ([None] * 5, None)
    assert ll.plan_location_names(story) == {"harbour-street", "temple-gate"}
    lt.write_plan(story, ["l1"], pinned=())
    assert ll.plan_location_names(story) == set()


# --- LL12: the library table (bin/location list) --------------------------------------------

def test_ll12_the_table(env):
    lib = env["locations"]
    assert ll.location_table_lines() == ["no locations in %s" % lib]
    lt.harbour(lib, stills=True)
    lt.mill(lib, status="untrained", source="photos")
    os.makedirs(os.path.join(lib, "bad-one"))
    with open(os.path.join(lib, "bad-one", "location.json"), "w") as f:
        f.write("{bad")
    lines = ll.location_table_lines()
    assert ll.LIST_ROW_FORMAT == "%-16s %-16s %-9s %-6s %-5s %-6s %s"
    assert lines[0] == ("NAME             TRIGGER          STATUS    SOURCE VIDEO STILLS "
                        "DESCRIPTION")
    assert lines[1].startswith("bad-one          (invalid: invalid location.json for bad-one: ")
    assert lines[2] == ("harbour-street   harboplc         trained   text   yes   yes    "
                        + lt.HARBOUR_DESC)
    assert lines[3] == ("old-mill         oldmiplc         untrained photos no    no     "
                        + lt.MILL_DESC)
    assert len(lines) == 4


# --- LL13: stdlib only, character_lib loaded only for triggers (spec 1.2) --------------------

def test_ll13_location_lib_is_stdlib_only(env, tmp_path):
    script = (
        "import importlib.machinery, sys\n"
        "m = importlib.machinery.SourceFileLoader('location_lib', %r).load_module()\n"
        "heavy = ('PIL', 'psutil', 'torch', 'character_dataset', 'character_lib')\n"
        "print(sorted(n for n in heavy if n in sys.modules))\n"
        "m.location_table_lines(); m.resolve_locations([]); m.usable_locations()\n"
        "print(sorted(n for n in heavy if n in sys.modules))\n"
        "m.all_triggers()\n"
        "print(sorted(n for n in heavy if n in sys.modules))\n"
    ) % os.path.join(WS, "location_lib.py")
    proc = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True,
                          env=dict(os.environ), cwd=str(tmp_path), timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == ["[]", "[]", "['character_lib']"]


# --- LL1: every new and changed file compiles under both Pythons (LK3) ------------------------

COMPILED = ("location_lib.py", "location_dataset.py", "bin/location", "story_engine.py",
            "character_dataset.py", "bin/ltx-movie", "bin/ltx-story-manifest",
            "bin/ltx-story-images", "bin/ltx-mlx-render", "bin/iterate-story", "bin/lora-check",
            "bin/lora-catalog", "movie_ui_lib.py", "movie_ui_server.py")


@pytest.mark.parametrize("python", ["/usr/bin/python3", sys.executable])
def test_ll1_every_new_and_changed_file_compiles(python, tmp_path):
    if not os.path.isfile(python):
        pytest.skip("%s is not installed" % python)
    script = ("import os, py_compile, sys\n"
              "out = sys.argv[1]\n"
              "for k, path in enumerate(sys.argv[2:]):\n"
              "    py_compile.compile(path, cfile=os.path.join(out, '%d.pyc' % k), doraise=True)\n"
              "print('compiled %d' % (len(sys.argv) - 2))\n")
    proc = subprocess.run([python, "-B", "-c", script, str(tmp_path)]
                          + [os.path.join(WS, rel) for rel in COMPILED],
                          capture_output=True, text=True, timeout=300)
    assert (proc.returncode, proc.stdout) == (0, "compiled 14\n"), proc.stderr
    bash = subprocess.run(["bash", "-n", os.path.join(WS, "bin", "location-train-vlm")],
                          capture_output=True, text=True, timeout=60)
    assert bash.returncode == 0, bash.stderr


def test_ll15_an_unreadable_record_is_a_location_error(env):
    if os.geteuid() == 0:
        pytest.skip("root reads anything")
    lt.harbour(env["locations"])
    path = os.path.join(env["locations"], "harbour-street", "location.json")
    os.chmod(path, 0)
    try:
        assert _raises(ll.load_location, "harbour-street").startswith(
            "invalid location.json for harbour-street:")
        names = ll.usable_locations()
        assert isinstance(names, list)
        assert "harbour-street" not in names
    finally:
        os.chmod(path, 0o644)
