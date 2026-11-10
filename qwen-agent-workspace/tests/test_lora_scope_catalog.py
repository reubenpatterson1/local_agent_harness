"""Tests for catalog LoRA scopes in lora_catalog.py and bin/lora-catalog
(docs/superpowers/specs/2026-11-10-lora-scope-design.md, LS1-LS3: LST1-LST3): a catalog entry's
optional scope (global, beat or either; by default global for style and beat for motion and
physics), bin/lora-catalog add --scope, the scope subcommand and the SCOPE column of list.

Run from the workspace root:
python3 -m pytest -q -p no:cacheprovider tests/test_lora_scope_catalog.py

LoRA files are a few bytes under tmp_path; bin/lora-catalog runs as a subprocess with
LORA_CATALOG_DIR under tmp_path. Nothing renders and no server is contacted. Stdlib and pytest.
"""

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

CLI = os.path.join(WS, "bin", "lora-catalog")
ARCH_UNVERIFIED = ("arch: architecture UNVERIFIED: none of the declared base models are on disk "
                   "yet; run bin/lora-check once the base is installed\n")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


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


def _cli(*argv):
    return subprocess.run([sys.executable, CLI] + list(argv), cwd=WS, capture_output=True,
                          text=True)


def _catalog_file(story_env):
    return os.path.join(story_env["catalog"], "catalog.json")


def _read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


# --- LST1 (LS1, LS2): the scope field in lora_catalog.py --------------------------------------

def test_lst1_the_scope_field_and_its_defaults(tmp_path, story_env):
    assert lora_catalog.SCOPES == ("global", "beat", "either")
    assert lora_catalog.DEFAULT_SCOPES == {"style": "global", "motion": "beat", "physics": "beat"}
    assert lora_catalog.OPTIONAL_ENTRY_KEYS == ("scope",)
    assert len(lora_catalog.ENTRY_KEYS) == 16 and "scope" not in lora_catalog.ENTRY_KEYS
    grain, fast, rain, ink = _entries(tmp_path)
    assert [lora_catalog.entry_scope(e) for e in (grain, fast, rain, ink)] == [
        "global", "beat", "beat", None]
    for scope in lora_catalog.SCOPES:
        for entry in ((grain, fast, ink) if scope == "global" else (fast, ink)):
            lora_catalog.validate_entry(dict(entry, scope=scope))
        assert lora_catalog.entry_scope(dict(fast, scope=scope)) == scope
    assert lora_catalog.entry_scope(dict(ink, scope="beat")) is None
    for character in (dict(fast, id="char:kyra", kind="character"),):
        assert lora_catalog.entry_scope(character) is None
    for bad in ("globl", None, ["beat"], "", "Beat"):
        with pytest.raises(lora_catalog.CatalogError) as exc:
            lora_catalog.validate_entry(dict(fast, scope=bad))
        assert str(exc.value) == ("entry fast-motion: scope must be one of global, beat, either, "
                                  "got %r" % (bad,))
    with pytest.raises(lora_catalog.CatalogError) as exc:
        lora_catalog.validate_entry(dict(fast, extra=1))
    assert str(exc.value) == "entry fast-motion: unexpected keys extra"
    path = seu.make_catalog(story_env["catalog"], [grain, fast, rain, ink])
    before = _read_bytes(path)
    data = lora_catalog.load_catalog(path)
    assert all("scope" not in e for e in data["entries"])
    lora_catalog.save_catalog(path, data)
    assert _read_bytes(path) == before
    scoped = dict(fast, scope="either")
    lora_catalog.save_catalog(path, {"schema_version": 1, "entries": [grain, scoped, rain, ink]})
    saved = lora_catalog.load_catalog(path)["entries"]
    assert [e["id"] for e in saved] == ["fast-motion", "film-grain", "ink-stills", "rain-physics"]
    assert saved[0] == scoped and list(saved[0])[-1] == "scope"


# --- LST2 (LS3): bin/lora-catalog add --scope and the SCOPE column of list ---------------------

def test_lst2_add_scope_and_the_list_column(tmp_path, story_env):
    files = str(tmp_path / "files")
    path = _catalog_file(story_env)
    base = ["--base-model", seu.VIDEO_MODEL, "--description", "a test LoRA",
            "--use-when", "a chase"]
    fight = seu.lora_file(files, "fight")
    result = _cli("add", fight, "--id", "fight-motion", "--kind", "motion", "--target", "video",
                  "--scope", "either", *base)
    assert (result.returncode, result.stderr) == (0, ARCH_UNVERIFIED), result.stderr
    entry = lora_catalog.load_catalog(path)["entries"][0]
    assert entry["scope"] == "either" and list(entry)[-1] == "scope"
    plain = seu.lora_file(files, "plain")
    assert _cli("add", plain, "--id", "plain-motion", "--kind", "motion", "--target", "video",
                *base).returncode == 0
    assert "scope" not in lora_catalog.load_catalog(path)["entries"][1]
    before = _read_bytes(path)
    ink = seu.lora_file(files, "ink")
    result = _cli("add", ink, "--id", "ink-stills", "--kind", "style", "--target", "stills",
                  "--scope", "global", "--base-model", seu.STILLS_MODEL, "--description", "ink",
                  "--use-when", "ink")
    assert (result.returncode, result.stdout, result.stderr) == (
        2, "", "Error: --scope applies only to video LoRAs; a stills LoRA is only ever the "
               "stills pick\n")
    result = _cli("add", ink, "--id", "ink-motion", "--kind", "motion", "--target", "video",
                  "--scope", "anywhere", *base)
    assert result.returncode == 2 and "invalid choice: 'anywhere'" in result.stderr
    assert _read_bytes(path) == before
    assert _cli("add", ink, "--id", "ink-stills", "--kind", "style", "--target", "stills",
                "--base-model", seu.STILLS_MODEL, "--description", "ink",
                "--use-when", "ink").returncode == 0
    grain = seu.lora_file(files, "grain")
    assert _cli("add", grain, "--id", "film-grain", "--kind", "style", "--target", "video",
                *base).returncode == 0
    row = "%-24s %-9s %-7s %-7s %-14s %-24s %s"
    assert _cli("list").stdout.splitlines() == [
        row % ("ID", "KIND", "TARGET", "SCOPE", "STRENGTH", "TRIGGERS", "BASE_MODELS"),
        row % ("fight-motion", "motion", "video", "either", "1.0 (0.5-1.0)", "", seu.VIDEO_MODEL),
        row % ("film-grain", "style", "video", "global", "1.0 (0.5-1.0)", "", seu.VIDEO_MODEL),
        row % ("ink-stills", "style", "stills", "-", "1.0 (0.5-1.0)", "", seu.STILLS_MODEL),
        row % ("plain-motion", "motion", "video", "beat", "1.0 (0.5-1.0)", "", seu.VIDEO_MODEL)]
    listed = json.loads(_cli("list", "--json").stdout)["entries"]
    assert [e.get("scope") for e in listed] == ["either", None, None, None]


# --- LST3 (LS3): bin/lora-catalog scope ID SCOPE -------------------------------------------------

def test_lst3_the_scope_subcommand(tmp_path, story_env):
    path = _catalog_file(story_env)
    assert _cli("scope", "fast-motion", "beat").stderr == "Error: no catalog entry fast-motion\n"
    grain, fast, rain, ink = _entries(tmp_path)
    seu.make_catalog(story_env["catalog"], [grain, fast, rain, ink])
    result = _cli("scope", "fast-motion", "global")
    assert (result.returncode, result.stdout, result.stderr) == (
        0, "fast-motion: scope global in %s\n" % path, "")
    entries = lora_catalog.load_catalog(path)["entries"]
    assert entries == [dict(fast, scope="global"), grain, ink, rain]
    assert _cli("scope", "fast-motion", "either").returncode == 0
    assert lora_catalog.load_catalog(path)["entries"][0] == dict(fast, scope="either")
    result = _cli("scope", "fast-motion", "default")
    assert (result.returncode, result.stdout) == (
        0, "fast-motion: scope beat (the default for a motion LoRA) in %s\n" % path)
    assert lora_catalog.load_catalog(path)["entries"] == [fast, grain, ink, rain]
    before = _read_bytes(path)
    for argv, stderr in (
            (["scope", "nope", "beat"], "Error: no catalog entry nope\n"),
            (["scope", "ink-stills", "beat"],
             "Error: ink-stills is a stills LoRA; scope applies only to video LoRAs\n"),
            (["scope", "char:kyra", "beat"],
             "Error: char:kyra is a library character; it is cast with bin/ltx-movie "
             "--character and has no scope\n")):
        result = _cli(*argv)
        assert (result.returncode, result.stdout, result.stderr) == (2, "", stderr), argv
    result = _cli("scope", "fast-motion", "anywhere")
    assert result.returncode == 2 and "invalid choice: 'anywhere'" in result.stderr
    assert _read_bytes(path) == before
    with open(path, "w", encoding="utf-8") as f:
        f.write("[]")
    result = _cli("scope", "fast-motion", "beat")
    assert result.returncode == 2 and result.stderr.startswith("Error: %s: top level" % path)
