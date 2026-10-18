"""Shared helpers for tests/test_story_engine.py and tests/test_lora_catalog.py (robust story
engine and LoRA catalog spec, docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md
Section 5.2).

Not a test module (pytest does not collect it). Every helper writes under a tmp_path the caller
passes in; nothing here reads or writes the real HOME, generated/loras/ or generated/characters/.
REAL_CATALOG_STAT is captured when this module is first imported, so RST63 can prove the real
catalog file was never touched during the session.
"""

import hashlib
import json
import os
import struct
import sys

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TESTS = os.path.join(WS, "tests")
sys.path.insert(0, WS)
sys.path.insert(0, TESTS)

import fleet_testutil  # noqa: E402

REAL_CATALOG = os.path.join(WS, "generated", "loras", "catalog.json")


def _stat_or_none(path):
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_size, info.st_mtime_ns)


REAL_CATALOG_STAT = _stat_or_none(REAL_CATALOG)

DESC_K = "a young woman with long black hair pinned up with jade hairpins wearing a grey kimono"
DESC_R = "a lean man in his late thirties with a topknot and a scarred brow wearing an indigo haori"
VIDEO_BYTES = b"fake-video-lora!"
STILLS_BYTES = b"fake-stills-lora"
CHARACTER_BASE_MODEL = "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8"
VIDEO_MODEL = "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8"
STILLS_MODEL = "Tongyi-MAI/Z-Image-Turbo"


def set_story_env(monkeypatch, tmp_path):
    """Section 5.1's environment for one test: HOME, CHARACTER_LIBRARY_DIR and LORA_CATALOG_DIR
    under tmp_path, QWEN_AGENT_DAEMON_URL at a closed loopback port, STORY_PIPELINE_LOGGED=1,
    and no ANTHROPIC_API_KEY. Returns {"home", "lib", "catalog"} (paths as str)."""
    home = os.path.join(str(tmp_path), "home")
    lib = os.path.join(str(tmp_path), "characters")
    catalog = os.path.join(str(tmp_path), "loras")
    for path in (home, lib, catalog):
        os.makedirs(path, exist_ok=True)
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", lib)
    monkeypatch.setenv("LORA_CATALOG_DIR", catalog)
    monkeypatch.setenv("QWEN_AGENT_DAEMON_URL", "http://127.0.0.1:%d" % fleet_testutil.free_port())
    monkeypatch.setenv("STORY_PIPELINE_LOGGED", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_AGENT_PREFLIGHT_DONE", raising=False)
    return {"home": home, "lib": lib, "catalog": catalog}


def fake_safetensors(path, rank, alpha, pairs=True, metadata=None, data=b"\x00" * 16):
    """Write a minimal safetensors file: an 8-byte little-endian header length, the JSON
    header (one lora_A tensor of shape [rank, 8], plus its lora_B pair when pairs, plus
    __metadata__ with lora_alpha when alpha is not None, merged with metadata), then data.
    Returns path."""
    header = {"blocks.0.attn.to_q.lora_A.weight":
              {"dtype": "F16", "shape": [rank, 8], "data_offsets": [0, 8]}}
    if pairs:
        header["blocks.0.attn.to_q.lora_B.weight"] = {"dtype": "F16", "shape": [8, rank],
                                                     "data_offsets": [8, 16]}
    meta = {}
    if alpha is not None:
        meta["lora_alpha"] = str(alpha)
    meta.update(metadata or {})
    if meta:
        header["__metadata__"] = meta
    raw = json.dumps(header).encode("utf-8")
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(raw)) + raw + data)
    return path


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def catalog_entry(path, entry_id, kind="motion", target="video", triggers=(), rank=16,
                  base_models=(VIDEO_MODEL,), default_strength=0.8, strength_range=(0.5, 1.0),
                  description="a test LoRA", use_when="a test fits", avoid_when=""):
    """A valid catalog entry for the existing file at path (sha256 and bytes from the file)."""
    return {"id": entry_id, "kind": kind, "path": os.path.abspath(path),
            "sha256": sha256_file(path), "bytes": os.path.getsize(path),
            "base_models": list(base_models), "target": target, "triggers": list(triggers),
            "rank": rank, "alpha": rank, "default_strength": default_strength,
            "strength_range": list(strength_range), "description": description,
            "use_when": use_when, "avoid_when": avoid_when, "added_at": "2026-10-17T12:00:00Z"}


def make_catalog(directory, entries):
    """Write <directory>/catalog.json with the given entries (sorted by id) and return its
    path. The directory is created."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "catalog.json")
    data = {"schema_version": 1, "entries": sorted(entries, key=lambda e: e["id"])}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def lora_file(directory, name, rank=16, alpha=None, pairs=True):
    """A fake safetensors LoRA <directory>/<name>.safetensors (alpha defaults to rank)."""
    os.makedirs(directory, exist_ok=True)
    return fake_safetensors(os.path.join(directory, name + ".safetensors"), rank,
                            rank if alpha is None else alpha, pairs=pairs)


def make_character(lib, name, trigger, phrase, class_noun, descriptor, stills=True,
                   strength=None, base_model=CHARACTER_BASE_MODEL):
    """Write a valid trained character.json under lib/name (character library spec 2.2 shape):
    a 16-byte lora/video.safetensors, plus a 16-byte lora/stills.safetensors when stills, each
    entry with its real sha256. Returns the dict."""
    cdir = os.path.join(lib, name)
    os.makedirs(os.path.join(cdir, "lora"), exist_ok=True)
    dataset = {"reference": "char_00", "kept": 24, "total": 25, "min_score": 7,
               "face_height": 0.38,
               "contact_sheet": os.path.join(cdir, "dataset", "contact_sheet.jpg")}
    video_path = os.path.join(cdir, "lora", "video.safetensors")
    with open(video_path, "wb") as f:
        f.write(VIDEO_BYTES)
    video = {"path": video_path, "sha256": hashlib.sha256(VIDEO_BYTES).hexdigest(),
             "base_model": base_model, "rank": 32, "alpha": 32, "steps": 1000,
             "trained_at": "2026-10-06T02:00:00Z", "sample_path": None, "control_path": None}
    stills_entry = None
    if stills:
        stills_path = os.path.join(cdir, "lora", "stills.safetensors")
        with open(stills_path, "wb") as f:
            f.write(STILLS_BYTES)
        stills_entry = {"path": stills_path, "sha256": hashlib.sha256(STILLS_BYTES).hexdigest(),
                        "base_model": STILLS_MODEL, "rank": 16, "alpha": 16, "steps": 2400,
                        "trained_at": "2026-10-06T03:00:00Z", "sample_path": None,
                        "control_path": None}
    data = {"schema_version": 1, "name": name, "trigger": trigger, "class_noun": class_noun,
            "referring_phrase": phrase, "descriptor": descriptor, "seed": 0,
            "source": {"type": "seed_image", "path": "/fixtures/seed.png"},
            "strength": strength, "status": "trained", "created_at": "2026-10-06T01:02:03Z",
            "dataset": dataset, "loras": {"video": video, "stills": stills_entry},
            "stills_skip_reason": None}
    with open(os.path.join(cdir, "character.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def kyra(lib, **kw):
    return make_character(lib, "kyra", "kyrawmn", "the woman in grey", "woman", DESC_K, **kw)


def ronin(lib, **kw):
    return make_character(lib, "ronin", "roninmn", "the ronin", "man", DESC_R, **kw)


def make_untrained(lib, name):
    """A valid untrained character (no LoRAs) under lib/name."""
    data = make_character(lib, name, name + "trg", "the " + name, "person",
                          "an old man with a white beard wearing a saffron robe and beads")
    data["status"] = "untrained"
    data["loras"] = {"video": None, "stills": None}
    with open(os.path.join(lib, name, "character.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data
