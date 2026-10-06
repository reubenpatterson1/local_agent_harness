"""Tests for casting through the movie pipeline (spec docs/superpowers/specs/
2026-10-05-character-library-design.md Section 9.5, P1-P49).

Run from the workspace root: python3 -m pytest tests/test_casting_pipeline.py
Plain pytest asserts only (no check() helper). No GPU, no model, no network: the render
harness stubs SKILL.generate_video (a fresh copy of the tests/test_ltx_mlx_render.py
_Harness pattern, not an import), Z-Image runs against fake torch/z_image_skill/
content_safety modules, and every character library lives under tmp_path through
$CHARACTER_LIBRARY_DIR.
"""

import contextlib
import glob
import hashlib
import importlib.machinery
import io
import json
import os
import subprocess
import sys
import types

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import character_lib  # noqa: E402
import ltx2_mlx_video_skill as SKILL  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


render = _load("ltx_mlx_render_casting", "bin/ltx-mlx-render")
story_manifest = _load("ltx_story_manifest_casting", "bin/ltx-story-manifest")
story_images = _load("ltx_story_images_casting", "bin/ltx-story-images")
ltx_movie = _load("ltx_movie_casting", "bin/ltx-movie")

# --- shared fixtures (spec 9.1) --------------------------------------------------------
DESCRIPTOR = "a young woman with long black hair pinned up with jade hairpins wearing a grey kimono"
VIDEO_BYTES = b"fake-video-lora!"
STILLS_BYTES = b"fake-stills-lora"


@pytest.fixture
def lib_dir(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", str(lib))
    return str(lib)


def make_character(lib, name="kyra", trigger="kyrawmn", phrase="the woman in grey",
                   class_noun="woman", status="trained", stills=False, strength=None):
    """Write a valid character.json (spec 2.2 shape) under lib/name and return the dict. A
    trained character also gets a 16-byte lora/video.safetensors, plus a 16-byte
    lora/stills.safetensors when stills is true; each entry carries the real sha256."""
    cdir = os.path.join(lib, name)
    os.makedirs(os.path.join(cdir, "lora"), exist_ok=True)
    dataset = None
    if status in ("untrained", "trained"):
        dataset = {"reference": "char_00", "kept": 24, "total": 25, "min_score": 7,
                   "face_height": 0.38,
                   "contact_sheet": os.path.join(cdir, "dataset", "contact_sheet.jpg")}
    video = stills_entry = None
    if status == "trained":
        video_path = os.path.join(cdir, "lora", "video.safetensors")
        with open(video_path, "wb") as f:
            f.write(VIDEO_BYTES)
        video = {"path": video_path, "sha256": hashlib.sha256(VIDEO_BYTES).hexdigest(),
                 "base_model": "/models/ltx-2.3-mlx-q8-dev", "rank": 32, "alpha": 32,
                 "steps": 1000, "trained_at": "2026-10-06T02:00:00Z",
                 "sample_path": None, "control_path": None}
        if stills:
            stills_path = os.path.join(cdir, "lora", "stills.safetensors")
            with open(stills_path, "wb") as f:
                f.write(STILLS_BYTES)
            stills_entry = {"path": stills_path,
                            "sha256": hashlib.sha256(STILLS_BYTES).hexdigest(),
                            "base_model": "Tongyi-MAI/Z-Image-Turbo", "rank": 16, "alpha": 16,
                            "steps": 2400, "trained_at": "2026-10-06T03:00:00Z",
                            "sample_path": None, "control_path": None}
    data = {"schema_version": 1, "name": name, "trigger": trigger, "class_noun": class_noun,
            "referring_phrase": phrase, "descriptor": DESCRIPTOR, "seed": 0,
            "source": {"type": "seed_image", "path": "/fixtures/seed.png"},
            "strength": strength, "status": status, "created_at": "2026-10-06T01:02:03Z",
            "dataset": dataset, "loras": {"video": video, "stills": stills_entry},
            "stills_skip_reason": None}
    with open(os.path.join(cdir, "character.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def _ronin(lib, **kw):
    return make_character(lib, name="ronin", trigger="roninmn", phrase="the ronin",
                          class_noun="man", **kw)


# --- P1-P5: ltx2_mlx_video_skill multi-LoRA argv and validation (spec 5.1) -------------
def _argv(**extra):
    return SKILL.build_command(prompt="p", output_path="/o.mp4", image_path="/i.png",
                               width=704, height=448, num_frames=145, frame_rate=24, seed=1,
                               model="M", gemma="G", **extra)


def test_p1_loras_follow_the_gemma_value(monkeypatch):
    monkeypatch.setattr(SKILL, "LTX2_MLX_BIN", "/bin/ltx")
    plain = _argv()
    cast = _argv(loras=[("/a.safetensors", 1.0), ("/b.safetensors", 0.8)])
    at = plain.index("--gemma") + 2
    assert cast == plain[:at] + ["--lora", "/a.safetensors", "1.0",
                                 "--lora", "/b.safetensors", "0.8"] + plain[at:]


def test_p2_empty_or_none_loras_change_nothing(monkeypatch):
    monkeypatch.setattr(SKILL, "LTX2_MLX_BIN", "/bin/ltx")
    assert _argv(loras=[]) == _argv()
    assert _argv(loras=None) == _argv()


def test_p3_lora_path_and_loras_are_exclusive():
    with pytest.raises(ValueError) as info:
        _argv(lora_path="/x", loras=[("/a", 1.0)])
    assert str(info.value) == "lora_path and loras are mutually exclusive"


def test_p4_generate_video_rejects_bad_loras(tmp_path, monkeypatch):
    def _never(*args, **kwargs):
        raise AssertionError("subprocess.Popen ran")
    monkeypatch.setattr(SKILL.subprocess, "Popen", _never)
    good = str(tmp_path / "a.safetensors")
    with open(good, "wb") as f:
        f.write(b"x")
    missing = str(tmp_path / "missing.safetensors")
    out = str(tmp_path / "o.mp4")
    cases = [
        ({"loras": {good: 1.0}},
         "loras must be a list of (path, strength) pairs, got %r" % ({good: 1.0},)),
        ({"loras": [(good, 1.0, 2)]},
         "loras[0] must be a (path, strength) pair, got %r" % ((good, 1.0, 2),)),
        ({"loras": [(missing, 1.0)]}, "loras[0]: path is not a readable file: %r" % missing),
        ({"loras": [(good, 0)]}, "loras[0]: strength must be a number in (0, 2], got 0"),
        ({"loras": [(good, 2.5)]}, "loras[0]: strength must be a number in (0, 2], got 2.5"),
        ({"loras": [(good, True)]}, "loras[0]: strength must be a number in (0, 2], got True"),
        ({"loras": [(good, "1")]}, "loras[0]: strength must be a number in (0, 2], got '1'"),
        ({"loras": [(good, 1.0)], "lora_path": good}, "lora_path and loras are mutually exclusive"),
    ]
    for kwargs, message in cases:
        with pytest.raises(ValueError) as info:
            SKILL.generate_video("p", out, width=704, height=448, num_frames=145,
                                 frame_rate=24, **kwargs)
        assert str(info.value) == message


def test_p5_child_argv_carries_the_lora_once(tmp_path, monkeypatch):
    stub = tmp_path / "ltx-stub"
    stub.write_text("#!%s\n"
                    "import json, os, sys\n"
                    "argv = sys.argv[1:]\n"
                    "with open(os.environ['CASTING_STUB_ARGV'], 'w') as f:\n"
                    "    json.dump(argv, f)\n"
                    "with open(argv[argv.index('--output') + 1], 'wb') as f:\n"
                    "    f.write(b'mp4')\n" % sys.executable)
    stub.chmod(0o755)
    argv_file = tmp_path / "argv.json"
    monkeypatch.setenv("CASTING_STUB_ARGV", str(argv_file))
    monkeypatch.setattr(SKILL, "LTX2_MLX_BIN", str(stub))
    monkeypatch.setattr(SKILL, "LTX2_MLX_DIR", str(tmp_path))
    lora = str(tmp_path / "k.safetensors")
    with open(lora, "wb") as f:
        f.write(b"lora")
    SKILL.generate_video("p", str(tmp_path / "o.mp4"), width=704, height=448, num_frames=145,
                         frame_rate=24, loras=[(lora, 0.6)], force=True)
    argv = json.loads(argv_file.read_text())
    windows = [argv[i:i + 3] for i in range(len(argv) - 2)]
    assert windows.count(["--lora", lora, "0.6"]) == 1
    assert argv.count("--lora") == 1


def test_p60_parse_lora_spec_table():
    parse = SKILL.parse_lora_spec
    assert parse("a.safetensors") == ("a.safetensors", 1.0, False)
    assert parse("a.safetensors:0.5") == ("a.safetensors", 0.5, True)
    assert parse("/p/a:b.safetensors:0.8") == ("/p/a:b.safetensors", 0.8, True)
    assert parse("org/repo:main") == ("org/repo:main", 1.0, False)
    assert parse(":0.5") == (":0.5", 1.0, False)
    assert parse("a.safetensors:2") == ("a.safetensors", 2.0, True)
    for bad in ("a.safetensors:0", "a.safetensors:2.5", "a.safetensors:-1", "a.safetensors:nan",
                "a.safetensors:inf", ""):
        with pytest.raises(ValueError):
            parse(bad)


def test_p74_strength_two_is_the_upper_bound(tmp_path, monkeypatch):
    stub = tmp_path / "ltx-stub"
    stub.write_text("#!%s\n"
                    "import json, os, sys\n"
                    "argv = sys.argv[1:]\n"
                    "with open(os.environ['CASTING_STUB_ARGV'], 'w') as f:\n"
                    "    json.dump(argv, f)\n"
                    "with open(argv[argv.index('--output') + 1], 'wb') as f:\n"
                    "    f.write(b'mp4')\n" % sys.executable)
    stub.chmod(0o755)
    argv_file = tmp_path / "argv.json"
    monkeypatch.setenv("CASTING_STUB_ARGV", str(argv_file))
    monkeypatch.setattr(SKILL, "LTX2_MLX_BIN", str(stub))
    monkeypatch.setattr(SKILL, "LTX2_MLX_DIR", str(tmp_path))
    g, k = str(tmp_path / "g.safetensors"), str(tmp_path / "k.safetensors")
    for path in (g, k):
        with open(path, "wb") as f:
            f.write(b"lora")
    SKILL.generate_video("p", str(tmp_path / "o.mp4"), width=704, height=448, num_frames=145,
                         frame_rate=24, loras=[(g, 2.0), (k, 1.0)], force=True)
    argv = json.loads(argv_file.read_text())
    at = argv.index("--lora")
    assert argv[at:at + 6] == ["--lora", g, "2.0", "--lora", k, "1.0"]
    with pytest.raises(ValueError):
        SKILL.generate_video("p", str(tmp_path / "o2.mp4"), width=704, height=448,
                             num_frames=145, frame_rate=24, loras=[(g, 2.0001)], force=True)
