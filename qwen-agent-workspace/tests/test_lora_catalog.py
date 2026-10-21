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
import shlex
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


def test_lct31_io_errors_are_reported_not_raised(tmp_path, story_env, monkeypatch, capsys):
    files = str(tmp_path / "files")
    entry = seu.catalog_entry(seu.lora_file(files, "m"), "fast-motion")

    def boom(path):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(lora_catalog, "file_sha256", boom)
    assert lora_catalog.verify_entry(entry, [entry], {}) == [
        "%s is missing or unreadable" % entry["path"]]
    cli = importlib.machinery.SourceFileLoader("lora_catalog_cli", LORA_CATALOG_CLI).load_module()
    lora = seu.lora_file(files, "n")
    assert cli.main(_add_argv(lora, "n-motion")) == 2
    assert capsys.readouterr().err == "Error: %s is not a readable file\n" % lora
    assert _catalog_bytes(story_env) is None
    monkeypatch.undo()
    seu.set_story_env(monkeypatch, tmp_path)

    def full(path, data):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(lora_catalog, "save_catalog", full)
    path = os.path.join(story_env["catalog"], "catalog.json")
    assert cli.main(_add_argv(lora, "n-motion")) == 2
    assert capsys.readouterr().err == "Error: cannot write %s: No space left on device\n" % path
    monkeypatch.undo()
    seu.set_story_env(monkeypatch, tmp_path)
    ro = tmp_path / "ro"
    ro.mkdir()
    os.chmod(str(ro), 0o500)
    try:
        monkeypatch.setenv("LORA_CATALOG_DIR", str(ro / "loras"))
        assert cli.main(_add_argv(lora, "n-motion")) == 2
        assert capsys.readouterr().err == "Error: cannot write %s: Permission denied\n" % (
            ro / "loras")
    finally:
        os.chmod(str(ro), 0o700)
    absent = tmp_path / "absent"
    monkeypatch.setenv("LORA_CATALOG_DIR", str(absent))
    assert cli.main(["remove", "x"]) == 2
    assert capsys.readouterr().err == "Error: no catalog entry x\n"
    assert not absent.exists()
    seu.kyra(story_env["lib"])
    char_json = os.path.join(story_env["lib"], "kyra", "character.json")
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", story_env["lib"])
    os.chmod(char_json, 0)
    try:
        assert lora_catalog.fold_characters(WS) == []
        assert lora_catalog.character_paths(WS) == {}
    finally:
        os.chmod(char_json, 0o600)
    deep = str(tmp_path / "deep.json")
    with open(deep, "w") as f:
        f.write("[" * 100000 + "]" * 100000)
    with pytest.raises(lora_catalog.CatalogError):
        lora_catalog.load_catalog(deep)
    body = b"[" * 100000 + b"]" * 100000
    header = str(tmp_path / "deep.safetensors")
    with open(header, "wb") as f:
        f.write(len(body).to_bytes(8, "little") + body)
    with pytest.raises(lora_catalog.CatalogError):
        lora_catalog.read_safetensors_header(header)


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


# --- LCT16-LCT18: bin/ltx-story-manifest --catalog-loras, bin/ltx-story-images --lora-trigger ---

story_manifest = importlib.machinery.SourceFileLoader(
    "ltx_story_manifest_for_lora_catalog", os.path.join(WS, "bin", "ltx-story-manifest")).load_module()
story_images = importlib.machinery.SourceFileLoader(
    "ltx_story_images_for_lora_catalog", os.path.join(WS, "bin", "ltx-story-images")).load_module()
CHAIN_STORY = """# Test

## Panel 1 — One
Image: A courier stands on a wet quay beside the boats.
Motion: The courier pushes off.
Narration: It rained.

## Panel 2 — Two
Motion: The courier pedals hard.
Narration: It rained more.

## Panel 3 — Three
Motion: FASTMO blur as the courier arrives.
Narration: It stopped.
"""


def _manifest_inputs(tmp_path, monkeypatch, lists):
    from PIL import Image
    ws = seu.make_ws(tmp_path)
    monkeypatch.setattr(story_manifest, "WS", ws)
    story_md = str(tmp_path / "story.md")
    with open(story_md, "w", encoding="utf-8") as f:
        f.write(CHAIN_STORY)
    image = str(tmp_path / "panel_01.png")
    Image.new("RGB", (64, 64), (9, 9, 9)).save(image)
    catalog_path = str(tmp_path / "catalog_loras.json")
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump({"schema": "ltx-movie.catalog-loras.v1", "story_id": "m1", "panels": lists}, f)
    argv = ["--story-id", "m1", "--prompts-md", story_md, "--chain", "--image", image,
            "--fps", "24", "--target-seconds", "18.125", "--min-frames", "145",
            "--max-frames", "145", "--force", "--catalog-loras", catalog_path]
    return ws, argv, catalog_path


def _entry(tmp_path, entry_id, kind, strength, triggers):
    path = seu.lora_file(str(tmp_path / "files"), entry_id)
    return {"id": entry_id, "kind": kind, "path": path, "sha256": seu.sha256_file(path),
            "strength": strength, "triggers": triggers}


def test_lct16_manifest_catalog_loras(tmp_path, monkeypatch, capsys):
    fast = _entry(tmp_path, "fast-motion", "motion", 0.7, ["fastmo"])
    grain = _entry(tmp_path, "film-grain", "style", 0.8, ["grainfilm"])
    ws, argv, catalog_path = _manifest_inputs(tmp_path, monkeypatch, [[grain], [fast, grain], [fast]])
    assert story_manifest.main(argv) == 0
    out = capsys.readouterr().out
    assert out.endswith("catalog: panel 1: film-grain@0.8\ncatalog: panel 2: fast-motion@0.7, "
                        "film-grain@0.8\ncatalog: panel 3: fast-motion@0.7\n")
    with open(os.path.join(ws, "generated", "stories", "m1", "manifest.json")) as f:
        manifest = json.load(f)
    panels = manifest["panels"]
    assert [p["catalog_loras"] for p in panels] == [[grain], [fast, grain], [fast]]
    assert [p["motion_prompt"] for p in panels] == [
        "grainfilm. The courier pushes off.", "fastmo, grainfilm. The courier pedals hard.",
        "FASTMO blur as the courier arrives."]
    assert panels[0]["panel_text"] == "A courier stands on a wet quay beside the boats."
    assert manifest["schema_version"] == 3
    bad_cases = [
        ([[grain], [fast]], "panels must be a list of exactly 3 lists"),
        ([[dict(grain, path="rel.safetensors")], [], []],
         "panel 1 entry 1: path must be an absolute path to a readable file, got 'rel.safetensors'"),
        ([[grain, dict(grain, id="other-grain")], [], []],
         "panel 1 has more than one style or motion/physics LoRA"),
        ([[grain, grain], [], []], "panel 1 lists a LoRA twice"),
        ([[dict(grain, strength=True)], [], []],
         "panel 1 entry 1: strength must be a number in (0, 2], got True"),
        ([[dict(grain, extra=1)], [], []],
         "panel 1 entry 1: must be an object with exactly the keys id, kind, path, sha256, "
         "strength, triggers"),
    ]
    for lists, reason in bad_cases:
        with open(catalog_path, "w", encoding="utf-8") as f:
            json.dump({"schema": "ltx-movie.catalog-loras.v1", "story_id": "m1", "panels": lists}, f)
        assert story_manifest.main(argv) == 2
        assert capsys.readouterr().err == "Error: --catalog-loras %s: %s\n" % (catalog_path, reason)
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump({"schema": "other"}, f)
    assert story_manifest.main(argv) == 2
    glob_argv = ["--story-id", "m1", "--glob", "panel_*.png", "--catalog-loras", catalog_path]
    with pytest.raises(SystemExit) as exc:
        story_manifest.main(glob_argv)
    assert exc.value.code == 2
    assert "--catalog-loras requires --chain, --shots or --no-images" in capsys.readouterr().err


def test_lct17_manifest_without_catalog_is_unchanged(tmp_path):
    regression = importlib.machinery.SourceFileLoader(
        "casting_regression_for_lct17", os.path.join(WS, "tests", "test_casting_regression.py")
    ).load_module()
    text = regression.b2_text(str(tmp_path))
    with open(regression.GOLDEN_B2, encoding="utf-8") as f:
        assert text == f.read()
    assert "catalog_loras" not in text


def test_lct18_story_images_lora_trigger(tmp_path, capsys):
    story_md = str(tmp_path / "story.md")
    with open(story_md, "w", encoding="utf-8") as f:
        f.write(CHAIN_STORY.replace("Motion: The courier pedals hard.",
                                    "Image: Inkstyle courier on the quay.\nMotion: The courier "
                                    "pedals hard."))
    out_dir = str(tmp_path / "images")
    base = ["--story-md", story_md, "--out-dir", out_dir, "--only", "1,2", "--dry-run"]
    assert story_images.main(base) == 0
    plain = capsys.readouterr().out.splitlines()
    assert plain[0].endswith(" | 'A courier stands on a wet quay beside the boats.'")
    assert story_images.main(base + ["--lora-trigger", "inkstyle", "--lora-trigger", "ink2"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].endswith(" | 'inkstyle, ink2. A courier stands on a wet quay beside the boats.'")
    assert lines[2].endswith(" | 'ink2. Inkstyle courier on the quay.'")
    assert lines[1] == lines[3] == "    loras: none"
    assert not os.path.exists(out_dir)


# --- LCT19-LCT25, LCT30: bin/ltx-mlx-render catalog_loras (LC17, 1.4) ------------------------

render = importlib.machinery.SourceFileLoader(
    "ltx_mlx_render_for_lora_catalog", os.path.join(WS, "bin", "ltx-mlx-render")).load_module()


def _still(directory):
    from PIL import Image
    path = os.path.join(str(directory), "panel_01.png")
    Image.new("RGB", (64, 64), (40, 40, 40)).save(path)
    return path


def _chain_panels(directory, catalog_by_panel, characters=None):
    image = _still(directory)
    panels = []
    for i, entries in enumerate(catalog_by_panel, start=1):
        panel = {"index": i, "image_path": image if i == 1 else None,
                 "conditioning": "still" if i == 1 else "chain",
                 "panel_text": "panel %d text" % i, "motion_prompt": "panel %d motion" % i,
                 "catalog_loras": entries}
        if characters and i in characters:
            panel["characters"] = characters[i]
        panels.append(panel)
    return panels


def _write_render_manifest(directory, panels, story_id="cat-render"):
    path = os.path.join(str(directory), "manifest.json")
    with open(path, "w") as f:
        json.dump({"schema_version": 3, "story_id": story_id, "fps": 24, "panels": panels}, f)
    return path


class _RenderHarness(object):
    """bin/ltx-mlx-render's main() in-process with generate_video, probe_streams,
    assert_clips_uniform, build_concat_command, clip_frame_count and prepare_chain_seed stubbed
    (as tests/test_casting_pipeline.py's _CastHarness); every stub render writes 128 bytes
    unique to that call."""

    def __init__(self, monkeypatch, directory, panels):
        self.dir = str(directory)
        self.received = []
        self.renders = [0]
        self.manifest = _write_render_manifest(self.dir, panels)
        self.model = os.path.join(self.dir, "model-fixture")
        os.makedirs(self.model, exist_ok=True)
        with open(os.path.join(self.model, "split_model.json"), "w") as f:
            json.dump({"recipe": "ltx-2.5"}, f)
        self.clips = os.path.join(self.dir, "clips")
        os.makedirs(self.clips, exist_ok=True)
        self.out = os.path.join(self.dir, "movie.mp4")
        fake_bin = os.path.join(self.dir, "fake-ltx")
        with open(fake_bin, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(fake_bin, 0o755)
        harness = self

        def _gen(prompt, output_path, image_path=None, **kw):
            harness.renders[0] += 1
            index = int(os.path.basename(output_path)[len("panel_"):-len(".mp4")])
            harness.received.append((index, kw))
            with open(output_path, "wb") as f:
                f.write(("render %d" % harness.renders[0]).encode().ljust(128, b"\0"))
            return os.path.abspath(output_path)

        def _seed(unit, args):
            with open(unit["image_path"], "wb") as f:
                f.write(b"seed")
            return []

        monkeypatch.setattr(render.SKILL, "generate_video", _gen)
        monkeypatch.setattr(render.SKILL, "LTX2_MLX_BIN", fake_bin)
        monkeypatch.setattr(render, "probe_streams", lambda p: {"streams": []})
        monkeypatch.setattr(render, "assert_clips_uniform", lambda pairs, w, h, fr: None)
        monkeypatch.setattr(render, "build_concat_command", lambda lp, out: [
            sys.executable, "-c", "import sys; open(sys.argv[1],'wb').write(b'MOVIE')", out])
        monkeypatch.setattr(render, "clip_frame_count", lambda p: 241)
        monkeypatch.setattr(render, "prepare_chain_seed", _seed)
        monkeypatch.setattr(render, "story_dir_for",
                            lambda sid: os.path.join(harness.dir, "stories", sid))

    def run(self, *extra):
        return render.main([self.manifest, self.out, "--clips-dir", self.clips,
                            "--skip-input-screen", "--model", self.model, "--width", "64",
                            "--height", "64"] + list(extra))

    def loras(self, index):
        return [kw.get("loras") for i, kw in self.received if i == index][-1]


def _render_entries(tmp_path):
    fast = _entry(tmp_path, "fast-motion", "motion", 0.7, ["fastmo"])
    grain = _entry(tmp_path, "film-grain", "style", 0.8, ["grainfilm"])
    return fast, grain


def test_lct19_load_manifest_validates_catalog_loras(tmp_path):
    fast, grain = _render_entries(tmp_path)
    good = _write_render_manifest(tmp_path, _chain_panels(tmp_path, [[fast, grain], [], [fast]]))
    assert render.load_manifest(good)["panels"][0]["catalog_loras"] == [fast, grain]
    cases = [
        ({"x": 1}, "panel 1: catalog_loras must be a list"),
        ([dict(fast, extra=1)], "panel 1: catalog_loras entry must have exactly the keys id, "
                                "kind, path, sha256, strength, triggers"),
        ([dict(fast, kind="character")], "panel 1: catalog_loras fast-motion: kind must be "
                                         "style, motion or physics, got 'character'"),
        ([dict(fast, path="/no/such.safetensors")], "panel 1: catalog_loras fast-motion: path is "
                                                    "not a readable file: '/no/such.safetensors'"),
        ([dict(fast, strength=3)], "panel 1: catalog_loras fast-motion: strength must be a number "
                                   "in (0, 2], got 3"),
        ([fast, fast], "panel 1: catalog_loras lists a LoRA twice"),
        ([grain, dict(grain, id="big-style")], "panel 1: catalog_loras has more than one style or "
                                               "motion/physics LoRA"),
    ]
    for entries, message in cases:
        path = _write_render_manifest(tmp_path, _chain_panels(tmp_path, [entries, [], []]))
        with pytest.raises(ValueError) as exc:
            render.load_manifest(path)
        assert str(exc.value) == message


def test_lct20_unit_lora_order(tmp_path, story_env):
    fast, grain = _render_entries(tmp_path)
    seu.kyra(story_env["lib"])
    video = os.path.join(story_env["lib"], "kyra", "lora", "video.safetensors")
    character = {"name": "kyra", "phrase": "the woman in grey", "trigger": "kyrawmn",
                 "video_lora": video, "strength": 1.0}
    panels = _chain_panels(tmp_path, [[fast, grain], [], []], characters={1: [character]})
    data = render.load_manifest(_write_render_manifest(tmp_path, panels))
    units = render.build_units(data["panels"], 0, str(tmp_path / "clips"),
                               global_loras=[{"path": "/g.safetensors", "strength": 0.5}])
    assert units[0]["loras"] == [
        {"kind": "catalog", "name": "fast-motion", "path": fast["path"], "strength": 0.7,
         "catalog_id": "fast-motion"},
        {"kind": "global", "name": None, "path": "/g.safetensors", "strength": 0.5},
        {"kind": "catalog", "name": "film-grain", "path": grain["path"], "strength": 0.8,
         "catalog_id": "film-grain"},
        {"kind": "character", "name": "kyra", "path": video, "strength": 1.0}]
    assert units[1]["loras"] == [{"kind": "global", "name": None, "path": "/g.safetensors",
                                  "strength": 0.5}]


def test_lct21_provenance(tmp_path, monkeypatch):
    import hashlib
    monkeypatch.setattr(render, "model_identity", lambda model, strict=False: None)
    fast, _grain = _render_entries(tmp_path)
    global_lora = seu.lora_file(str(tmp_path / "files"), "global")
    args = render.build_parser().parse_args(["/m.json", "/o.mp4", "--model", "M"])
    unit = {"index": 1, "label": "panel-1", "seed": 1, "prompt": "p", "image_path": None,
            "clip_path": "/c/panel_01.mp4", "log_path": None, "conditioning": "t2v",
            "chain_source": None,
            "loras": [{"kind": "global", "name": None, "path": global_lora, "strength": 1.0}]}
    assert render.build_clip_provenance(unit, args) == {
        "schema_version": 2, "backend": "ltx-2-mlx", "model": "M", "model_identity": None,
        "gemma": args.gemma, "lora_path": None,
        "prompt_sha256": hashlib.sha256(b"p").hexdigest(), "conditioning": "t2v",
        "image_sha256": None, "chain_source_sha256": None, "chain_frame_index": None,
        "image_crf": None, "seed": 1,
        "width": args.width, "height": args.height, "frames": args.frames,
        "fps": args.frame_rate, "low_ram": True, "tile_frames": 1, "tile_spatial": 1,
        "loras": [{"kind": "global", "path": global_lora, "sha256": seu.sha256_file(global_lora),
                   "strength": 1.0}]}
    unit["loras"].append({"kind": "catalog", "name": "fast-motion", "path": fast["path"],
                          "strength": 0.7, "catalog_id": "fast-motion"})
    assert render.build_clip_provenance(unit, args)["loras"][1] == {
        "kind": "catalog", "path": fast["path"], "sha256": fast["sha256"], "strength": 0.7,
        "catalog_id": "fast-motion"}


def test_lct22_sha_and_duplicate_checks(tmp_path, monkeypatch, capsys, story_env):
    fast, grain = _render_entries(tmp_path)
    harness = _RenderHarness(monkeypatch, tmp_path, _chain_panels(tmp_path, [[], [fast], []]))
    with open(fast["path"], "r+b") as f:
        f.seek(-1, 2)
        f.write(b"\x07")
    for extra in (["--dry-run"], []):
        assert harness.run(*extra) == 2
        assert capsys.readouterr().err == (
            "Error: panel 2: catalog LoRA fast-motion does not match its cataloged sha256; the "
            "file changed since bin/lora-catalog add (run bin/lora-catalog verify)\n")
    assert harness.received == []
    fast, grain = _render_entries(tmp_path / "again")
    _write_render_manifest(tmp_path, _chain_panels(tmp_path, [[], [fast], []]))
    assert harness.run("--dry-run", "--lora", fast["path"] + ":0.5") == 2
    assert capsys.readouterr().err == (
        "Error: catalog LoRA fast-motion (panel 2) is also passed with --lora; pass it once\n")
    seu.kyra(story_env["lib"])
    video = os.path.join(story_env["lib"], "kyra", "lora", "video.safetensors")
    clash = dict(fast, path=video, sha256=seu.sha256_file(video))
    character = {"name": "kyra", "phrase": "p", "trigger": "kyrawmn", "video_lora": video,
                 "strength": 1.0}
    _write_render_manifest(tmp_path, _chain_panels(tmp_path, [[], [clash], []],
                                                   characters={2: [character]}))
    assert harness.run("--dry-run") == 2
    assert capsys.readouterr().err == (
        "Error: catalog LoRA fast-motion (panel 2) is also character kyra's video LoRA\n")


def test_lct23_dry_run_lists_catalog_loras(tmp_path, monkeypatch, capsys):
    fast, grain = _render_entries(tmp_path)
    harness = _RenderHarness(monkeypatch, tmp_path,
                             _chain_panels(tmp_path, [[fast, grain], [fast], []]))
    assert harness.run("--dry-run") == 0
    out = capsys.readouterr().out
    assert ("            lora: %s @ 0.7 (fast-motion)\n            lora: %s @ 0.8 (film-grain)\n"
            % (fast["path"], grain["path"])) in out
    command = [l for l in out.splitlines() if l.startswith("first render command: ")][0]
    assert (" --lora %s 0.7 --lora %s 0.8 --distilled " % (fast["path"], grain["path"])) in command


def test_lct24_per_panel_loras_reach_generate_video(tmp_path, monkeypatch):
    fast, grain = _render_entries(tmp_path)
    harness = _RenderHarness(monkeypatch, tmp_path, _chain_panels(tmp_path, [[grain], [fast, grain],
                                                                             []]))
    assert harness.run() == 0
    assert harness.loras(1) == [(grain["path"], 0.8)]
    assert harness.loras(2) == [(fast["path"], 0.7), (grain["path"], 0.8)]
    assert harness.loras(3) is None


def test_lct25_resume_with_catalog_loras(tmp_path, monkeypatch):
    fast, grain = _render_entries(tmp_path)
    harness = _RenderHarness(monkeypatch, tmp_path, _chain_panels(tmp_path, [[], [fast], []]))
    assert harness.run() == 0
    assert [i for i, _kw in harness.received] == [1, 2, 3]
    harness.received[:] = []
    assert harness.run("--resume", "--force") == 0
    assert harness.received == []
    _write_render_manifest(tmp_path, _chain_panels(tmp_path, [[], [dict(fast, strength=0.8)], []]))
    assert harness.run("--resume", "--force") == 0
    assert [i for i, _kw in harness.received] == [2, 3]


def test_lct30_chained_manifest_per_panel_units(tmp_path, monkeypatch, capsys):
    fast, grain = _render_entries(tmp_path)
    panels = _chain_panels(tmp_path, [[grain], [fast, grain], [grain]])
    data = render.load_manifest(_write_render_manifest(tmp_path, panels))
    units = render.build_units(data["panels"], 0, str(tmp_path / "clips"))
    assert [[l["name"] for l in u["loras"]] for u in units] == [
        ["film-grain"], ["fast-motion", "film-grain"], ["film-grain"]]
    harness = _RenderHarness(monkeypatch, tmp_path, panels)
    assert harness.run("--dry-run", "--on-panel-failure", "stop") == 0
    assert "panel  2: I2V chained" in capsys.readouterr().out


def test_lct20b_motion_first_stable_partition(tmp_path, monkeypatch, capsys, story_env):
    style = _entry(tmp_path, "aa-style", "style", 0.8, ["aastyle"])
    motion = _entry(tmp_path, "zz-motion", "motion", 0.7, ["zzmo"])
    seu.kyra(story_env["lib"])
    video = os.path.join(story_env["lib"], "kyra", "lora", "video.safetensors")
    character = {"name": "kyra", "phrase": "the woman in grey", "trigger": "kyrawmn",
                 "video_lora": video, "strength": 1.0}
    user = seu.lora_file(str(tmp_path / "files"), "user")
    panels = _chain_panels(tmp_path, [[style, motion], [], []], characters={1: [character]})
    data = render.load_manifest(_write_render_manifest(tmp_path, panels))
    units = render.build_units(data["panels"], 0, str(tmp_path / "clips"),
                               global_loras=[{"path": user, "strength": 0.5}])
    expected = [motion["path"], user, style["path"], video]
    assert [l["path"] for l in units[0]["loras"]] == expected
    harness = _RenderHarness(monkeypatch, tmp_path, panels)
    assert harness.run("--dry-run", "--lora", user + ":0.5") == 0
    out = capsys.readouterr().out
    command = [l for l in out.splitlines() if l.startswith("first render command: ")][0]
    argv = shlex.split(command[len("first render command: "):])
    paths = [argv[i + 1] for i, a in enumerate(argv) if a == "--lora"]
    assert paths == expected
