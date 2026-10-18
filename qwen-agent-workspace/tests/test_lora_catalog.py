"""Tests for the LoRA catalog (docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md
Section 5.4, LCT1-LCT30): lora_catalog.py, bin/lora-catalog, and the catalog's path through
bin/ltx-movie, bin/ltx-story-manifest, bin/ltx-story-images and bin/ltx-mlx-render.

Run from the workspace root: python3 -m pytest tests/test_lora_catalog.py
Plain pytest asserts only. Every test runs under Section 5.1's environment (the autouse
story_env fixture): HOME, CHARACTER_LIBRARY_DIR and LORA_CATALOG_DIR under tmp_path, the daemon
URL at a closed port. LoRA files are a few bytes; nothing renders.
"""

import ast
import importlib.machinery
import json
import os
import re
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import lora_catalog  # noqa: E402
import story_engine_testutil as seu  # noqa: E402

LORA_CATALOG_CLI = os.path.join(WS, "bin", "lora-catalog")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


def _top_level_imports(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module)
    return names


# --- LCT1-LCT6, LCT26: lora_catalog.py (LC1-LC6, LC18) ------------------------------------

def test_lct1_import_set_and_stills_base_model():
    assert _top_level_imports(os.path.join(WS, "lora_catalog.py")) == {
        "datetime", "fcntl", "hashlib", "importlib.machinery", "json", "os", "re", "struct",
        "uuid"}
    with open(os.path.join(WS, "z_image_skill.py"), encoding="utf-8") as f:
        literal = re.search(r'^BASE_MODEL_ID = "([^"]+)"', f.read(), re.MULTILINE).group(1)
    assert lora_catalog.STILLS_BASE_MODEL == literal == "Tongyi-MAI/Z-Image-Turbo"
    assert lora_catalog.KINDS == ("style", "motion", "physics")
    assert lora_catalog.TARGETS == ("video", "stills")
    assert lora_catalog.MAX_TRIGGERS == 4 and lora_catalog.TEXT_MAX == 300
    assert len(lora_catalog.ENTRY_KEYS) == 16
    assert lora_catalog.CATALOG_ENV == "LORA_CATALOG_DIR" and lora_catalog.SCHEMA_VERSION == 1


def test_lct2_catalog_path(monkeypatch, tmp_path, story_env):
    assert lora_catalog.catalog_path("/ws") == os.path.join(story_env["catalog"], "catalog.json")
    monkeypatch.delenv("LORA_CATALOG_DIR")
    assert lora_catalog.catalog_path("/ws") == "/ws/generated/loras/catalog.json"
    assert lora_catalog.catalog_dir("/ws") == "/ws/generated/loras"
    absent = str(tmp_path / "nowhere" / "catalog.json")
    assert lora_catalog.load_catalog(absent) == {"schema_version": 1, "entries": []}


def _valid_entry(tmp_path):
    path = seu.lora_file(str(tmp_path / "files"), "m", rank=16)
    return seu.catalog_entry(path, "fast-motion", triggers=["fastmo"])


def test_lct3_entry_validation(tmp_path):
    base = _valid_entry(tmp_path)
    lora_catalog.validate_entry(base)
    cases = [
        (lambda e: e.pop("use_when"), "missing keys use_when"),
        (lambda e: e.update(extra=1), "unexpected keys extra"),
        (lambda e: e.update(id="Bad_id"), "id must match"),
        (lambda e: e.update(id="char:kyra"), "id must match"),
        (lambda e: e.update(kind="character"), "kind must be one of"),
        (lambda e: e.update(target="audio"), "target must be one of"),
        (lambda e: e.update(path="relative/x.safetensors"), "path must be an absolute path"),
        (lambda e: e.update(sha256="ABC"), "sha256 must be 64 lowercase hex"),
        (lambda e: e.update(bytes=0), "bytes must be an int >= 1"),
        (lambda e: e.update(bytes=True), "bytes must be an int >= 1"),
        (lambda e: e.update(base_models=[]), "base_models must be a non-empty list"),
        (lambda e: e.update(base_models=[""]), "base_models must be a non-empty list"),
        (lambda e: e.update(triggers=["a", "b", "c", "d", "e"]), "triggers must be a list of at most 4"),
        (lambda e: e.update(triggers=["-bad"]), "triggers item must match"),
        (lambda e: e.update(triggers=["Same", "same"]), "triggers must not repeat"),
        (lambda e: e.update(rank=0), "rank must be an int >= 1"),
        (lambda e: e.update(alpha=8), "alpha must equal rank (16); ltx-2-mlx fuses B@A*strength "
                                     "with no alpha/rank scaling (fuse_loras.py), so this LoRA "
                                     "would render at the wrong strength"),
        (lambda e: e.update(default_strength=True), "default_strength must be a number"),
        (lambda e: e.update(strength_range=[0.5]), "strength_range must be a list of two numbers"),
        (lambda e: e.update(default_strength=1.2), "strength_range and default_strength must satisfy"),
        (lambda e: e.update(strength_range=[0, 1.0]), "strength_range and default_strength must satisfy"),
        (lambda e: e.update(strength_range=[0.5, 2.5]), "strength_range and default_strength must satisfy"),
        (lambda e: e.update(description=""), "description must be a string of 1 to 300"),
        (lambda e: e.update(use_when="x" * 301), "use_when must be a string of 1 to 300"),
        (lambda e: e.update(avoid_when=None), "avoid_when must be a string of 0 to 300"),
        (lambda e: e.update(added_at="2026-10-17 12:00:00"), "added_at must be a UTC timestamp"),
    ]
    for mutate, needle in cases:
        entry = json.loads(json.dumps(base))
        mutate(entry)
        with pytest.raises(lora_catalog.CatalogError) as exc:
            lora_catalog.validate_entry(entry)
        assert needle in str(exc.value), (needle, str(exc.value))
    other = dict(base, id="other", path=base["path"], triggers=["FASTMO"])
    for data, needle in (({"schema_version": 1}, "top level"),
                         ({"schema_version": 2, "entries": []}, "schema_version: must be 1"),
                         ({"schema_version": 1, "entries": {}}, "entries: must be a list"),
                         ({"schema_version": 1, "entries": [base, dict(base)]},
                          "id fast-motion is listed more than once"),
                         ({"schema_version": 1, "entries": [base, other]},
                          "trigger FASTMO is used by both fast-motion and other")):
        with pytest.raises(lora_catalog.CatalogError) as exc:
            lora_catalog.validate_catalog(data)
        assert needle in str(exc.value), (needle, str(exc.value))
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(lora_catalog.CatalogError) as exc:
        lora_catalog.load_catalog(str(bad))
    assert str(exc.value).startswith(str(bad) + ": not valid JSON")


def test_lct3b_save_sorts_and_is_atomic(tmp_path):
    base = _valid_entry(tmp_path)
    path = str(tmp_path / "cat" / "catalog.json")
    os.makedirs(os.path.dirname(path))
    second = dict(base, id="alpha-grain", kind="style", triggers=[])
    lora_catalog.save_catalog(path, {"schema_version": 1, "entries": [base, second]})
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert text.endswith("}\n")
    assert [e["id"] for e in json.loads(text)["entries"]] == ["alpha-grain", "fast-motion"]
    assert os.listdir(os.path.dirname(path)) == ["catalog.json"]
    assert lora_catalog.load_catalog(path)["entries"][1] == base


def test_lct4_safetensors_header(tmp_path):
    path = seu.fake_safetensors(str(tmp_path / "a.safetensors"), 32, 32)
    header = lora_catalog.read_safetensors_header(path)
    assert lora_catalog.rank_alpha(header) == (32, 32)
    assert lora_catalog.has_lora_pairs(header) is True
    for key in ("lora_alpha", "alpha", "ss_network_alpha"):
        path = seu.fake_safetensors(str(tmp_path / ("%s.safetensors" % key)), 8, None,
                                    metadata={key: "8.0"})
        assert lora_catalog.rank_alpha(lora_catalog.read_safetensors_header(path)) == (8, 8)
    path = seu.fake_safetensors(str(tmp_path / "frac.safetensors"), 8, None,
                                metadata={"lora_alpha": "4.5"})
    assert lora_catalog.rank_alpha(lora_catalog.read_safetensors_header(path)) == (8, None)
    kohya = {"lora_unet_blocks_0.lora_down.weight": {"dtype": "F16", "shape": [4, 8],
                                                     "data_offsets": [0, 8]},
             "__metadata__": {"ss_network_dim": "4", "ss_network_alpha": "4"}}
    raw = json.dumps(kohya).encode("utf-8")
    path = str(tmp_path / "kohya.safetensors")
    with open(path, "wb") as f:
        f.write(len(raw).to_bytes(8, "little") + raw)
    header = lora_catalog.read_safetensors_header(path)
    assert lora_catalog.has_lora_pairs(header) is False
    assert lora_catalog.rank_alpha(header) == (4, 4)
    unpaired = lora_catalog.read_safetensors_header(
        seu.fake_safetensors(str(tmp_path / "u.safetensors"), 8, 8, pairs=False))
    assert lora_catalog.has_lora_pairs(unpaired) is False
    for name, content in (("short.safetensors", b"\x01\x02"),
                          ("zero.safetensors", (0).to_bytes(8, "little")),
                          ("huge.safetensors", (200 * 1024 * 1024).to_bytes(8, "little")),
                          ("trunc.safetensors", (50).to_bytes(8, "little") + b"{}"),
                          ("notjson.safetensors", (4).to_bytes(8, "little") + b"nope")):
        path = str(tmp_path / name)
        with open(path, "wb") as f:
            f.write(content)
        with pytest.raises(lora_catalog.CatalogError) as exc:
            lora_catalog.read_safetensors_header(path)
        assert str(exc.value) == "%s: not a safetensors file" % path


def test_lct5_character_folding(story_env):
    lib = story_env["lib"]
    seu.kyra(lib, strength=0.6)
    seu.make_untrained(lib, "monk")
    before = sorted(os.listdir(story_env["catalog"]))
    folded = lora_catalog.fold_characters(WS)
    assert [e["id"] for e in folded] == ["char:kyra"]
    entry = folded[0]
    assert entry["kind"] == "character" and entry["target"] == "video"
    assert entry["triggers"] == ["kyrawmn"]
    assert entry["base_models"] == [seu.CHARACTER_BASE_MODEL]
    assert entry["default_strength"] == 0.6 and entry["strength_range"] is None
    assert entry["bytes"] is None and entry["rank"] == entry["alpha"] == 32
    assert entry["description"] == seu.DESC_K
    assert entry["use_when"] == "cast with bin/ltx-movie --character kyra"
    assert entry["path"] == os.path.join(lib, "kyra", "lora", "video.safetensors")
    assert lora_catalog.character_triggers(WS) == {"kyrawmn": "kyra", "monktrg": "monk"}
    assert sorted(os.listdir(story_env["catalog"])) == before


def test_lct6a_compatibility(tmp_path):
    entry = {"base_models": ["MLXBits/pack", str(tmp_path / "models" / "pack")]}
    assert lora_catalog.compatible(entry, "MLXBits/pack") is True
    assert lora_catalog.compatible(entry, "MLXBits/other") is False
    os.makedirs(str(tmp_path / "models" / "pack"))
    os.symlink(str(tmp_path / "models" / "pack"), str(tmp_path / "link"))
    assert lora_catalog.compatible(entry, str(tmp_path / "link")) is True
    assert lora_catalog.compatible({"base_models": [lora_catalog.STILLS_BASE_MODEL]},
                                   "Tongyi-MAI/Z-Image-Turbo") is True


def test_lct26_prefix_triggers():
    p = "The courier pedals hard."
    assert lora_catalog.prefix_triggers(p, []) == p
    assert lora_catalog.prefix_triggers(p, ["fastmo", "grainfilm"]) == "fastmo, grainfilm. " + p
    assert lora_catalog.prefix_triggers("FASTMO courier", ["fastmo"]) == "FASTMO courier"
    assert lora_catalog.prefix_triggers(p, ["fastmo", "FastMo", "x"]) == "fastmo, x. " + p
    assert lora_catalog.prefix_triggers("the fastmo-like blur", ["fastmo"]) == (
        "fastmo. the fastmo-like blur")


# --- LCT7-LCT12, LCT29: bin/lora-catalog (LC7-LC11, LC20) ---------------------------------

def _cli(*argv):
    return subprocess.run([sys.executable, LORA_CATALOG_CLI] + list(argv), cwd=WS,
                          capture_output=True, text=True)


def _add_argv(path, entry_id, *extra, **kw):
    argv = ["add", path, "--id", entry_id, "--kind", kw.get("kind", "motion"),
            "--target", kw.get("target", "video"), "--base-model", seu.VIDEO_MODEL,
            "--description", "fast motion blur", "--use-when", "a chase or a sprint"]
    return argv + list(extra)


def _catalog_bytes(story_env):
    path = os.path.join(story_env["catalog"], "catalog.json")
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def test_lct7_add_happy_path(tmp_path, story_env):
    files = str(tmp_path / "files")
    zeta = seu.lora_file(files, "zeta", rank=16)
    alpha = seu.lora_file(files, "alpha", rank=8)
    result = _cli(*_add_argv(zeta, "zeta-motion", "--trigger", "zetamo",
                             "--default-strength", "0.7", "--strength-range", "0.4,0.9",
                             "--avoid-when", "a still scene"))
    assert result.returncode == 0, result.stderr
    path = os.path.join(story_env["catalog"], "catalog.json")
    sha = seu.sha256_file(zeta)
    assert result.stdout == "added zeta-motion (motion, video, rank 16, sha256 %s...) to %s\n" % (
        sha[:12], path)
    assert result.stderr == ""
    entry = lora_catalog.load_catalog(path)["entries"][0]
    assert entry == {
        "id": "zeta-motion", "kind": "motion", "path": os.path.abspath(zeta), "sha256": sha,
        "bytes": os.path.getsize(zeta), "base_models": [seu.VIDEO_MODEL], "target": "video",
        "triggers": ["zetamo"], "rank": 16, "alpha": 16, "default_strength": 0.7,
        "strength_range": [0.4, 0.9], "description": "fast motion blur",
        "use_when": "a chase or a sprint", "avoid_when": "a still scene",
        "added_at": entry["added_at"]}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", entry["added_at"])
    result = _cli(*_add_argv(alpha, "alpha-grain", kind="style"))
    assert result.returncode == 0, result.stderr
    data = lora_catalog.load_catalog(path)
    assert [e["id"] for e in data["entries"]] == ["alpha-grain", "zeta-motion"]
    assert data["entries"][0]["default_strength"] == 1.0
    assert data["entries"][0]["strength_range"] == [0.5, 1.0]
    assert data["entries"][0]["avoid_when"] == ""
    assert sorted(os.listdir(story_env["catalog"])) == [".lock", "catalog.json"]
    assert oct(os.stat(os.path.join(story_env["catalog"], ".lock")).st_mode & 0o777) == "0o600"


def test_lct8_add_errors_leave_the_catalog_unchanged(tmp_path, story_env):
    files = str(tmp_path / "files")
    first = seu.lora_file(files, "first", rank=16)
    assert _cli(*_add_argv(first, "first-motion", "--trigger", "firstmo")).returncode == 0
    seu.kyra(story_env["lib"])
    kyra_video = os.path.join(story_env["lib"], "kyra", "lora", "video.safetensors")
    seu.fake_safetensors(kyra_video, 32, 32)
    cases = [
        (_add_argv(seu.lora_file(files, "a", rank=16), "first-motion"),
         "Error: catalog entry first-motion already exists\n"),
        (_add_argv(first, "second-motion"),
         "Error: %s is already cataloged as first-motion\n" % first),
        (_add_argv(kyra_video, "kyra-copy"),
         "Error: %s is character kyra's video LoRA; cast it with bin/ltx-movie --character\n"
         % kyra_video),
        (_add_argv(seu.lora_file(files, "b", rank=16), "b-motion", "--trigger", "FIRSTMO"),
         "Error: trigger FIRSTMO is already catalog entry first-motion's trigger\n"),
        (_add_argv(seu.lora_file(files, "c", rank=16), "c-motion", "--trigger", "kyrawmn"),
         "Error: trigger kyrawmn is character kyra's trigger\n"),
        (_add_argv(seu.lora_file(files, "d", rank=16, alpha=8), "d-motion"),
         "Error: entry d-motion: alpha must equal rank (16); ltx-2-mlx fuses B@A*strength with "
         "no alpha/rank scaling (fuse_loras.py), so this LoRA would render at the wrong "
         "strength\n"),
        (_add_argv(seu.lora_file(files, "e", rank=16, pairs=False), "e-motion"),
         "Error: %s has no lora_A/lora_B weight pairs; the ltx-2-mlx fuser would ignore it\n"
         % os.path.join(files, "e.safetensors")),
        (_add_argv(seu.fake_safetensors(os.path.join(files, "f.safetensors"), 16, None),
                   "f-motion"),
         "Error: cannot read the LoRA alpha from the safetensors header; pass --alpha\n"),
        (_add_argv(seu.lora_file(files, "g", rank=16), "g-motion", "--default-strength", "1.5"),
         "Error: entry g-motion: strength_range and default_strength must satisfy 0 < lo <= "
         "default <= hi <= 2, got range [0.5, 1.0] and default 1.5\n"),
        (_add_argv(os.path.join(files, "missing.safetensors"), "h-motion"),
         "Error: %s is not a readable file\n" % os.path.join(files, "missing.safetensors")),
        (_add_argv(seu.lora_file(files, "i", rank=16), "i-motion", "--strength-range", "0.5"),
         "Error: --strength-range must be LO,HI, got '0.5'\n"),
    ]
    before = _catalog_bytes(story_env)
    for argv, stderr in cases:
        result = _cli(*argv)
        assert (result.returncode, result.stdout, result.stderr) == (2, "", stderr), argv
        assert _catalog_bytes(story_env) == before
    ok = _cli(*_add_argv(seu.fake_safetensors(os.path.join(files, "j.safetensors"), 16, None),
                         "j-motion", "--alpha", "16"))
    assert ok.returncode == 0, ok.stderr


def test_lct9_list(tmp_path, story_env):
    path = os.path.join(story_env["catalog"], "catalog.json")
    empty = _cli("list")
    assert (empty.returncode, empty.stdout) == (0, "no LoRAs in %s\n" % path)
    seu.kyra(story_env["lib"])
    header = lora_catalog_row("ID", "KIND", "TARGET", "STRENGTH", "TRIGGERS", "BASE_MODELS")
    kyra_row = lora_catalog_row("char:kyra", "character", "video", "0.8", "kyrawmn",
                                seu.CHARACTER_BASE_MODEL)
    only_chars = _cli("list")
    assert only_chars.stdout == "no LoRAs in %s\n%s\n%s\n" % (path, header, kyra_row)
    files = str(tmp_path / "files")
    motion = seu.catalog_entry(seu.lora_file(files, "m"), "fast-motion", triggers=["fastmo"])
    stills = seu.catalog_entry(seu.lora_file(files, "s"), "ink-stills", kind="style",
                               target="stills", base_models=[seu.STILLS_MODEL],
                               default_strength=0.9, strength_range=[0.6, 1.2])
    seu.make_catalog(story_env["catalog"], [motion, stills])
    table = _cli("list")
    assert table.returncode == 0
    assert table.stdout.splitlines() == [
        header,
        lora_catalog_row("fast-motion", "motion", "video", "0.8 (0.5-1.0)", "fastmo",
                         seu.VIDEO_MODEL),
        lora_catalog_row("ink-stills", "style", "stills", "0.9 (0.6-1.2)", "",
                         seu.STILLS_MODEL),
        kyra_row]
    filtered = _cli("list", "--model", seu.STILLS_MODEL)
    assert filtered.stdout.splitlines() == [
        header, lora_catalog_row("ink-stills", "style", "stills", "0.9 (0.6-1.2)", "",
                                 seu.STILLS_MODEL)]
    as_json = json.loads(_cli("list", "--json").stdout)
    assert list(as_json) == ["catalog", "entries", "characters"]
    assert as_json["catalog"] == path
    assert [e["id"] for e in as_json["entries"]] == ["fast-motion", "ink-stills"]
    assert [c["id"] for c in as_json["characters"]] == ["char:kyra"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("[]")
    broken = _cli("list")
    assert broken.returncode == 2 and broken.stderr.startswith("Error: %s: top level" % path)


def lora_catalog_row(*cells):
    return "%-24s %-9s %-7s %-14s %-24s %s" % cells


def test_lct10_remove(tmp_path, story_env):
    files = str(tmp_path / "files")
    lora = seu.lora_file(files, "m")
    with open(lora, "rb") as f:
        lora_bytes = f.read()
    seu.make_catalog(story_env["catalog"], [seu.catalog_entry(lora, "fast-motion")])
    path = os.path.join(story_env["catalog"], "catalog.json")
    unknown = _cli("remove", "nope")
    assert (unknown.returncode, unknown.stderr) == (2, "Error: no catalog entry nope\n")
    char = _cli("remove", "char:kyra")
    assert (char.returncode, char.stderr) == (
        2, "Error: char:kyra is a library character; manage it with bin/character\n")
    ok = _cli("remove", "fast-motion")
    assert (ok.returncode, ok.stdout) == (0, "removed fast-motion from %s\n" % path)
    assert lora_catalog.load_catalog(path)["entries"] == []
    with open(lora, "rb") as f:
        assert f.read() == lora_bytes


def test_lct11_verify(tmp_path, story_env):
    files = str(tmp_path / "files")
    good = seu.catalog_entry(seu.lora_file(files, "good"), "good-motion", triggers=["goodmo"])
    seu.make_catalog(story_env["catalog"], [good])
    clean = _cli("verify")
    assert (clean.returncode, clean.stdout) == (0, "OK good-motion\nverified 1 entry: 0 problem(s)\n")
    grown = seu.catalog_entry(seu.lora_file(files, "grown"), "grown-motion")
    with open(grown["path"], "ab") as f:
        f.write(b"extra")
    same = seu.catalog_entry(seu.lora_file(files, "same"), "same-size")
    with open(same["path"], "r+b") as f:
        f.seek(-1, 2)
        f.write(b"\x01")
    gone = seu.catalog_entry(seu.lora_file(files, "gone"), "gone-motion")
    os.remove(gone["path"])
    ranked = seu.catalog_entry(seu.lora_file(files, "ranked", rank=16), "ranked-motion", rank=8)
    clash = seu.catalog_entry(seu.lora_file(files, "clash"), "clash-motion", triggers=["kyrawmn"])
    seu.kyra(story_env["lib"])
    seu.make_catalog(story_env["catalog"], [good, grown, same, gone, ranked, clash])
    result = _cli("verify")
    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "FAIL clash-motion: trigger kyrawmn is also character kyra's trigger",
        "FAIL gone-motion: %s is missing or unreadable" % gone["path"],
        "OK good-motion",
        "FAIL grown-motion: size is %d bytes; the catalog records %d"
        % (grown["bytes"] + 5, grown["bytes"]),
        "FAIL ranked-motion: the header's rank 16 differs from the recorded rank 8",
        "FAIL ranked-motion: the header's alpha 16 differs from the recorded alpha 8",
        "FAIL same-size: sha256 differs from the catalog; the file changed since it was added",
        "FAIL char:kyra: trigger kyrawmn is also catalog entry clash-motion's trigger",
        "verified 6 entries: 7 problem(s)"]
    one = _cli("verify", "good-motion")
    assert (one.returncode, one.stdout) == (0, "OK good-motion\nverified 1 entry: 0 problem(s)\n")
    missing = _cli("verify", "nope")
    assert (missing.returncode, missing.stderr) == (2, "Error: no catalog entry nope\n")


def test_lct12_concurrent_adds_both_land(tmp_path, story_env):
    files = str(tmp_path / "files")
    procs = [subprocess.Popen([sys.executable, LORA_CATALOG_CLI]
                              + _add_argv(seu.lora_file(files, name), name + "-motion"),
                              cwd=WS, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for name in ("one", "two")]
    for proc in procs:
        out, err = proc.communicate(timeout=60)
        assert proc.returncode == 0, err
    path = os.path.join(story_env["catalog"], "catalog.json")
    assert [e["id"] for e in lora_catalog.load_catalog(path)["entries"]] == [
        "one-motion", "two-motion"]
    assert not [n for n in os.listdir(story_env["catalog"]) if n.endswith(".tmp")]


def test_lct29_lora_catalog_exit_codes(tmp_path, story_env):
    files = str(tmp_path / "files")
    lora = seu.lora_file(files, "m")
    table = [
        (["list"], 0),
        (_add_argv(lora, "fast-motion"), 0),
        (_add_argv(lora, "fast-motion"), 2),
        (["verify"], 0),
        (["verify", "nope"], 2),
        (["remove", "nope"], 2),
        (["remove", "fast-motion"], 0),
        (["bogus"], 2),
        (["add", lora], 2),
    ]
    for argv, rc in table:
        assert _cli(*argv).returncode == rc, argv
    assert _cli(*_add_argv(lora, "fast-motion")).returncode == 0
    os.remove(lora)
    assert _cli("verify").returncode == 1


def test_lct27_deploy_pipeline_files():
    build_pkg = importlib.machinery.SourceFileLoader(
        "build_pkg_for_lct27", os.path.join(WS, "scripts", "deploy", "build_pkg.py")).load_module()
    files = list(build_pkg.PIPELINE_FILES)
    at = files.index("character_lib.py")
    assert files[at + 1:at + 3] == ["story_engine.py", "lora_catalog.py"]
    assert "bin/lora-catalog" not in files and "fleet_lib.py" not in files


# --- LCT13: pins in bin/ltx-movie's story context (LC12) ------------------------------------

ltx_movie = importlib.machinery.SourceFileLoader(
    "ltx_movie_for_lora_catalog", os.path.join(WS, "bin", "ltx-movie")).load_module()


def _movie_args(*argv):
    args = ltx_movie.build_parser().parse_args(list(argv))
    args.video_width, args.video_height = 704, 448
    for resolve in (ltx_movie._resolve_shots, ltx_movie._resolve_casting,
                    ltx_movie._resolve_global_loras, ltx_movie._resolve_story_engine):
        assert resolve(args) == 0
    return args


def test_lct13_pins(tmp_path, story_env):
    files = str(tmp_path / "files")
    fast = seu.lora_file(files, "fast")
    other = seu.lora_file(files, "other")
    seu.make_catalog(story_env["catalog"], [seu.catalog_entry(fast, "fast-motion")])
    args = _movie_args("n", "--story-id", "p1", "--lora", fast + ":0.7", "--lora", other)
    assert ltx_movie._story_context(args).pinned == [
        {"path": fast, "strength": 0.7, "catalog_id": "fast-motion", "kind": "motion"},
        {"path": other, "strength": 1.0, "catalog_id": None, "kind": None}]
    flags = ltx_movie._render_flags(args)
    assert flags[flags.index("--lora"):flags.index("--lora") + 4] == [
        "--lora", fast + ":0.7", "--lora", other + ":1.0"]
    legacy = _movie_args("n", "--story-id", "p1", "--lora", other)
    assert ltx_movie._story_context(legacy).pinned == [
        {"path": other, "strength": 1.0, "catalog_id": None, "kind": None}]
    assert ltx_movie._render_flags(legacy)[16:18] == ["--lora", other]
    assert "--lora" not in ltx_movie._render_flags(_movie_args("n", "--story-id", "p1"))


# --- LCT14, LCT15: the catalog flags of Phases 2 and 3 in bin/ltx-movie (LC13, LC14) ---------

class _Done(object):
    returncode = 0


def _catalog_story(tmp_path, monkeypatch, story_env, stills=False, extra=()):
    """A temp workspace (ltx_movie.WS) with a 3-panel chained story whose plan.json picks
    film-grain (global style) and fast-motion (beat 2); returns (ws, story_dir, entries)."""
    ws = seu.make_ws(tmp_path)
    monkeypatch.setattr(ltx_movie, "WS", ws)
    files = str(tmp_path / "files")
    grain = seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style",
                              triggers=["grainfilm"])
    fast = seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion", triggers=["fastmo"])
    ink = seu.catalog_entry(seu.lora_file(files, "ink"), "ink-stills", kind="style",
                            target="stills", base_models=[seu.STILLS_MODEL], triggers=["inkstyle"])
    seu.make_catalog(story_env["catalog"], [grain, fast, ink] + list(extra))
    story_dir = os.path.join(ws, "generated", "stories", "c1")
    os.makedirs(story_dir)
    loras = {"global": [{"id": "film-grain", "strength": 0.8}],
             "per_beat": {"2": [{"id": "fast-motion", "strength": 0.7}]},
             "stills": [{"id": "ink-stills", "strength": 0.8}] if stills else []}
    with open(os.path.join(story_dir, "plan.json"), "w") as f:
        json.dump({"schema": "ltx-movie.plan.v1", "mode": "chained", "panels": 3,
                   "title": "T", "logline": "x", "cast": [], "locations": [], "props": [],
                   "beats": [], "loras": loras}, f)
    with open(os.path.join(story_dir, "story.md"), "w") as f:
        f.write("# T\n\n## Panel 1 — A\nImage: The woman in grey waits.\nMotion: x\n"
                "Narration: y\n")
    return ws, story_dir, {"film-grain": grain, "fast-motion": fast, "ink-stills": ink}


def _recorded(monkeypatch):
    calls = []
    monkeypatch.setattr(ltx_movie.subprocess, "run",
                        lambda cmd, **kw: calls.append(list(cmd)) or _Done())
    return calls


def _item(entry, strength):
    return {"id": entry["id"], "kind": entry["kind"], "path": entry["path"],
            "sha256": entry["sha256"], "strength": strength, "triggers": entry["triggers"]}


def test_lct14_phase3_catalog_loras(tmp_path, monkeypatch, story_env, capsys):
    ws, story_dir, entries = _catalog_story(tmp_path, monkeypatch, story_env)
    calls = _recorded(monkeypatch)
    args = _movie_args("n", "--story-id", "c1", "--panels", "3", "--no-review")
    assert ltx_movie.phase3_manifest(args) == 0
    path = os.path.join(story_dir, "catalog_loras.json")
    grain, fast = _item(entries["film-grain"], 0.8), _item(entries["fast-motion"], 0.7)
    with open(path) as f:
        assert json.load(f) == {"schema": "ltx-movie.catalog-loras.v1", "story_id": "c1",
                                "panels": [[grain], [fast, grain], [grain]]}
    assert calls[0][-2:] == ["--catalog-loras", path]
    os.remove(path)
    for flags in (["--no-auto-lora"], ["--story-legacy"]):
        calls[:] = []
        assert ltx_movie.phase3_manifest(_movie_args("n", "--story-id", "c1", "--panels", "3",
                                                     "--no-review", *flags)) == 0
        assert "--catalog-loras" not in calls[0] and not os.path.exists(path)
    capsys.readouterr()
    assert ltx_movie.main(["n", "--story-id", "c1", "--panels", "3", "--dry-run",
                           "--no-review"]) == 0
    manifest_line = [l for l in capsys.readouterr().out.splitlines()
                     if "ltx-story-manifest" in l][0]
    assert manifest_line.endswith(" --catalog-loras " + path)
    assert not os.path.exists(path)
    assert ltx_movie.main(["n", "--story-id", "c1", "--panels", "3", "--dry-run", "--no-review",
                           "--force-story"]) == 0
    assert "--catalog-loras" not in capsys.readouterr().out
    with open(entries["fast-motion"]["path"], "ab") as f:
        f.write(b"x")
    assert ltx_movie.phase3_manifest(args) == 2
    assert capsys.readouterr().err == (
        "Error: catalog LoRA fast-motion changed since it was cataloged (%s); run "
        "bin/lora-catalog verify\n" % entries["fast-motion"]["path"])
    seu.make_catalog(story_env["catalog"], [entries["film-grain"]])
    args = _movie_args("n", "--story-id", "c1", "--panels", "3", "--no-review")
    assert ltx_movie.phase3_manifest(args) == 2
    assert capsys.readouterr().err == (
        "Error: plan.json picks catalog LoRA fast-motion, which is no longer in the catalog; "
        "re-add it with bin/lora-catalog add, or rerun with --no-auto-lora\n")


def test_lct15_phase2_stills_pick(tmp_path, monkeypatch, story_env, capsys):
    seu.kyra(story_env["lib"])
    ws, story_dir, entries = _catalog_story(tmp_path, monkeypatch, story_env, stills=True)
    calls = _recorded(monkeypatch)
    args = _movie_args("n", "--story-id", "c1", "--panels", "3", "--no-review", "--character",
                       "kyra")
    assert ltx_movie.phase2_stills(args) == 0
    ink = entries["ink-stills"]["path"]
    cmd = calls[0]
    at = cmd.index("--cast")
    assert cmd[at - 4:at + 2] == ["--lora", ink + ":0.8", "--lora-trigger", "inkstyle", "--cast",
                                  "the woman in grey=kyra"]
    capsys.readouterr()
    assert ltx_movie.main(["n", "--story-id", "c1", "--panels", "3", "--dry-run", "--no-review",
                           "--character", "kyra"]) == 0
    line = [l for l in capsys.readouterr().out.splitlines() if "ltx-story-images" in l][0]
    assert ("--lora %s:0.8 --lora-trigger inkstyle --cast" % ink) in line
    calls[:] = []
    assert ltx_movie.phase2_stills(_movie_args("n", "--story-id", "c1", "--panels", "3",
                                               "--no-review", "--no-auto-lora")) == 0
    assert "--lora-trigger" not in calls[0] and "--lora" not in calls[0]


def test_story_focus_4_a_cataloged_lora_deleted_after_phase_1(tmp_path, monkeypatch, story_env,
                                                               capsys):
    ws, story_dir, entries = _catalog_story(tmp_path, monkeypatch, story_env, stills=True)
    _recorded(monkeypatch)
    args = _movie_args("n", "--story-id", "c1", "--panels", "3", "--no-review")
    os.remove(entries["fast-motion"]["path"])
    os.remove(entries["ink-stills"]["path"])
    assert ltx_movie.phase3_manifest(args) == 2
    assert capsys.readouterr().err == (
        "Error: catalog LoRA fast-motion changed since it was cataloged (%s); run "
        "bin/lora-catalog verify\n" % entries["fast-motion"]["path"])
    assert ltx_movie.phase2_stills(args) == 2
    assert capsys.readouterr().err == (
        "Error: catalog LoRA ink-stills changed since it was cataloged (%s); run "
        "bin/lora-catalog verify\n" % entries["ink-stills"]["path"])
    assert not os.path.exists(os.path.join(story_dir, "catalog_loras.json"))


# --- fix round 1: a malformed or invalid plan.json never feeds picks into Phases 2 and 3 -------

MALFORMED = ("Error: plan.json has malformed LoRA picks; rerun with --force-story or "
             "--no-auto-lora\n")


def _edit_plan(story_dir, edit):
    path = os.path.join(story_dir, "plan.json")
    with open(path) as f:
        plan = json.load(f)
    edit(plan)
    with open(path, "w") as f:
        json.dump(plan, f)


def _p3(*extra):
    return _movie_args("n", "--story-id", "c1", "--panels", "3", "--no-review", *extra)


def test_fix1_plan_missing_beats_gives_no_flags(tmp_path, monkeypatch, story_env, capsys):
    ws, story_dir, entries = _catalog_story(tmp_path, monkeypatch, story_env)
    _edit_plan(story_dir, lambda plan: plan.pop("beats"))
    calls = _recorded(monkeypatch)
    assert ltx_movie.phase3_manifest(_p3()) == 0
    assert "--catalog-loras" not in calls[0]
    assert not os.path.exists(os.path.join(story_dir, "catalog_loras.json"))


def test_fix1_malformed_picks_exit_2(tmp_path, monkeypatch, story_env, capsys):
    ws, story_dir, entries = _catalog_story(tmp_path, monkeypatch, story_env)
    _recorded(monkeypatch)

    def bad_global(plan):
        plan["loras"]["global"] = ["film-grain"]

    def bad_beat(plan):
        plan["loras"]["per_beat"] = []

    for edit in (bad_global, bad_beat):
        _edit_plan(story_dir, edit)
        assert ltx_movie.phase3_manifest(_p3()) == 2
        assert capsys.readouterr().err == MALFORMED
        assert not os.path.exists(os.path.join(story_dir, "catalog_loras.json"))


def test_fix1_picks_failing_lora_checks_exit_2(tmp_path, monkeypatch, story_env, capsys):
    ws, story_dir, entries = _catalog_story(tmp_path, monkeypatch, story_env)
    _recorded(monkeypatch)

    def loud(plan):
        plan["loras"]["global"][0]["strength"] = 99

    _edit_plan(story_dir, loud)
    assert ltx_movie.phase3_manifest(_p3()) == 2
    assert capsys.readouterr().err.startswith("Error: plan.json LoRA picks fail the catalog checks (")
    assert not os.path.exists(os.path.join(story_dir, "catalog_loras.json"))


def test_fix1_mismatch_and_dry_run_cases(tmp_path, monkeypatch, story_env, capsys):
    ws, story_dir, entries = _catalog_story(tmp_path, monkeypatch, story_env)
    calls = _recorded(monkeypatch)
    assert ltx_movie.phase3_manifest(_movie_args("n", "--story-id", "c1", "--panels", "4",
                                                 "--no-review")) == 0
    assert "--catalog-loras" not in calls[0]
    capsys.readouterr()
    assert ltx_movie.main(["n", "--story-id", "c1", "--panels", "3", "--dry-run",
                           "--no-review"]) == 0
    assert "--catalog-loras" in capsys.readouterr().out
    seu.make_catalog(story_env["catalog"], [entries["film-grain"]])
    assert ltx_movie.main(["n", "--story-id", "c1", "--panels", "3", "--dry-run",
                           "--no-review"]) == 2
    assert capsys.readouterr().err == (
        "Error: plan.json picks catalog LoRA fast-motion, which is no longer in the catalog; "
        "re-add it with bin/lora-catalog add, or rerun with --no-auto-lora\n")
    os.remove(os.path.join(story_dir, "story.md"))
    seu.make_catalog(story_env["catalog"], list(entries.values()))
    assert ltx_movie.main(["n", "--story-id", "c1", "--panels", "3", "--dry-run",
                           "--no-review"]) == 0
    assert "--catalog-loras" not in capsys.readouterr().out
