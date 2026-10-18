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
