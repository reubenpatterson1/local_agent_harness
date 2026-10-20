"""movie-ui validation checks V1-V6 (movie-ui spec MUT3 rule 18, MUT4-MUT9).
Run from the workspace root: python3 -m pytest tests/test_movie_ui_checks.py -v
Every test runs under a temporary HOME against a stub workspace."""

import json
import os
import shutil

import pytest

import movie_ui_testutil as mt
import movie_ui_lib as lib


@pytest.fixture
def env(monkeypatch, tmp_path):
    state = mt.set_home(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    return {"state": state, "ws": ws, "tmp": str(tmp_path)}


def _errors(env, **overrides):
    return lib.validate_fields(mt.fields(env["ws"], **overrides), env["ws"], env["state"])


def _story(env, story_id="ronin-rescue", files=("story.md",)):
    sdir = os.path.join(env["ws"], "generated", "stories", story_id)
    os.makedirs(sdir, exist_ok=True)
    for name in files:
        with open(os.path.join(sdir, name), "w") as f:
            f.write("x")
    return sdir


def test_mut4_every_v1_error_alone(env):
    upload = os.path.join(env["state"], "uploads", "a" * 64 + ".png")
    with open(upload, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
    seed = "a" * 64 + ".png"
    assert _errors(env) == []
    table = [
        ({"story_id": "../x"}, "story id must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$ and must not contain '..'"),
        ({"story_id": "movie-ui-smoke"}, "story id movie-ui-smoke is reserved for smoke renders"),
        ({"narrative": "   "}, "narrative is required"),
        ({"narrative": None}, "narrative is required"),
        ({"narrative": "x" * 20001}, "narrative must be at most 20000 characters"),
        ({"narrative": " -x"}, "narrative must not start with '-'"),
        ({"narrative": "--force"}, "narrative must not start with '-'"),
        ({"goal": " . "}, "goal must be a single line of 1 to 300 characters"),
        ({"goal": "a\nb"}, "goal must be a single line of 1 to 300 characters"),
        ({"goal": "g" * 301}, "goal must be a single line of 1 to 300 characters"),
        ({"goal": "-x"}, "goal must not start with '-'"),
        ({"goal": "a\ud800"}, "goal contains invalid characters"),
        ({"narrative": "ok\x00"}, "narrative contains invalid characters"),
        ({"story_id": "Movie-UI-Smoke"}, "story id movie-ui-smoke is reserved for smoke renders"),
        ({"panels": 201}, "panels must be an integer from 1 to 200"),
        ({"video_loras": [{"id": None, "path": "/a\x00b", "strength": 1, "kind": None}]},
         "video LoRA 1: path contains invalid characters"),
        ({"video_loras": [{"id": None, "path": "/a\ud800b", "strength": 1, "kind": None}]},
         "video LoRA 1: path contains invalid characters"),
        ({"length": 30}, "give exactly one of panels or length"),
        ({"panels": None}, "give exactly one of panels or length"),
        ({"panels": 0}, "panels must be an integer from 1 to 200"),
        ({"panels": True}, "panels must be an integer from 1 to 200"),
        ({"panels": None, "length": 3601}, "length must be a number of seconds in (0, 3600]"),
        ({"panels": None, "length": False}, "length must be a number of seconds in (0, 3600]"),
        ({"panels": None, "length": 6}, "length resolves to 1 panel(s); the minimum is 2"),
        ({"fps": 121}, "fps must be an integer from 1 to 120"),
        ({"frames": 144}, "frames must satisfy (n-1)%8==0 and n>=9"),
        ({"frames": 1}, "frames must satisfy (n-1)%8==0 and n>=9"),
        ({"width": 700, "height": 448}, "width and height must both be multiples of 64 (at least 64)"),
        ({"width": 704}, "width and height must both be multiples of 64 (at least 64)"),
        ({"seed_upload": "b" * 64 + ".png"}, "seed image upload %s not found" % ("b" * 64 + ".png")),
        ({"mode": "fast"}, "mode must be chained, shots or no_stills"),
        ({"seed_upload": seed, "mode": "no_stills"}, "a seed image cannot be used with no-stills mode"),
        ({"seed_upload": seed, "mode": "shots"}, "a seed image cannot be used with shots mode"),
        ({"model": "-x"}, "model must be a model name or an absolute path"),
        ({"gemma": ""}, "gemma must be a model name or an absolute path"),
        ({"story_model": "a\tb"}, "story_model must be a model name or an absolute path"),
        ({"video_loras": [{"id": None, "path": "rel.safetensors", "strength": 1, "kind": None}]},
         "video LoRA 1: path must be absolute"),
        ({"stills_loras": [{"id": None, "path": "/a.safetensors", "strength": 0, "kind": None}]},
         "stills LoRA 1: strength must be in (0, 2]"),
        ({"video_loras": [{"id": "Bad_ID", "path": "/a.safetensors", "strength": 1, "kind": "style"}]},
         "video LoRA 1: bad catalog id"),
        ({"video_loras": [{"id": "pan", "path": "/a.safetensors", "strength": 1, "kind": None}]},
         "video LoRA 1: bad kind"),
        ({"video_loras": [{"id": None, "path": "/a.safetensors", "strength": 1, "kind": None},
                          {"id": None, "path": "/b/../a.safetensors", "strength": 1, "kind": None}]},
         "video LoRA /b/../a.safetensors is listed twice"),
        ({"characters": ["kyra", "kyra"]}, "characters must be distinct character names"),
        ({"characters": ["Kyra"]}, "characters must be distinct character names"),
        ({"judge": "yes"}, "judge must be true or false"),
        ({"panel_timeout": 59}, "panel_timeout must be an integer from 60 to 86400"),
        ({"action": "render"}, "unknown action"),
        ({"story_legacy": True, "judge": True}, "--story-legacy cannot be combined with --judge, --no-auto-lora or --goal"),
        ({"story_legacy": True, "goal": "tense"}, "--story-legacy cannot be combined with --judge, --no-auto-lora or --goal"),
    ]
    for overrides, message in table:
        assert _errors(env, **overrides) == [message], overrides
    assert _errors(env, seed_upload=seed, width=704, height=448) == ["give a seed image or a resolution, not both"]
    assert _errors(env, action="redo", mode="chained", redo=[1]) == ["redo needs shots mode", "redo needs an existing story.md"]
    _story(env)
    assert _errors(env, action="redo", mode="shots", redo=[]) == ["redo needs at least one panel number"]
    assert _errors(env, action="redo", mode="shots", redo=[2, 16]) == ["redo panel 16 is out of range (1..15)"]
    assert _errors(env, action="redo", mode="shots", redo=[2]) == []
    _story(env, files=("movie.mp4",))
    assert _errors(env, action="movie") == ['movie.mp4 already exists; tick "Overwrite movie.mp4" (--force)']
    assert _errors(env, action="movie", overwrite_movie=True) == []
    for bad in ("../x", "a/../b", "a..b", ".x", "x" * 81, "-x", "a b"):
        assert _errors(env, story_id=bad)[0].startswith("story id must match"), bad
    assert _errors(env, story_id="a.b-c_9") == []
    assert _errors(env, story_id="x" * 80) == []
    assert _errors(env, panels=200) == []
    assert _errors(env, narrative="x" * 20000) == []


def test_mut3_v1_rule_18_against_an_old_workspace(env):
    with open(os.path.join(mt.FIXTURES, "ltx-movie-help-old.txt"), encoding="utf-8") as f:
        mt.stub_config(env["ws"], {"ltx-movie --help": {"stdout": f.read()}})
    assert _errors(env, judge=True) == [
        "this workspace's bin/ltx-movie does not support --gemma",
        "this workspace's bin/ltx-movie does not support --judge",
        "this workspace's bin/ltx-movie does not support --story-only"]
    assert _errors(env, gemma=None, action="movie") == []


def test_mut9_v2_host_checks(env, monkeypatch):
    tmp = env["tmp"]
    binary = os.path.join(tmp, "ltx-2-mlx")
    tools = os.path.join(tmp, "tools")
    os.makedirs(tools)
    for name in ("ffmpeg", "ffprobe"):
        path = os.path.join(tools, name)
        with open(path, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(path, 0o755)
    monkeypatch.setenv("PATH", tools)
    monkeypatch.setenv("LTX2_MLX_BIN", binary)
    assert lib.render_check() == (False, "ltx-2-mlx binary not found or not executable: %s (set LTX2_MLX_BIN)" % binary)
    with open(binary, "w") as f:
        f.write("#!/bin/sh\n")
    os.chmod(binary, 0o755)
    assert lib.render_check() == (True, binary)
    monkeypatch.setenv("PATH", os.path.join(tmp, "empty"))
    assert lib.render_check() == (False, "ffmpeg not found on PATH; ffprobe not found on PATH")
    monkeypatch.delenv("LTX2_MLX_BIN")
    monkeypatch.setenv("LTX2_MLX_DIR", os.path.join(tmp, "ltxdir"))
    assert lib.ltx_bin() == os.path.join(tmp, "ltxdir", ".venv", "bin", "ltx-2-mlx")
    good_py = os.path.join(tmp, "good-python")
    bad_py = os.path.join(tmp, "bad-python")
    with open(good_py, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    with open(bad_py, "w") as f:
        f.write("#!/bin/sh\necho 'Traceback' >&2\necho \"ModuleNotFoundError: No module named 'torch'\" >&2\nexit 1\n")
    os.chmod(good_py, 0o755)
    os.chmod(bad_py, 0o755)
    assert lib.stills_check(env["ws"], good_py) == (True, "stills dependencies importable")
    assert lib.stills_check(env["ws"], bad_py) == (
        False, "stills dependencies not importable: ModuleNotFoundError: No module named 'torch'")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert lib.story_server_check(env["ws"]) == (True, "story server: SERVING vision")
    mt.stub_config(env["ws"], {"story-server status": {"stdout": "  state:          STOPPED\n"}})
    assert lib.story_server_check(env["ws"]) == (
        False, "story server is STOPPED; start it with bin/story-server vision (or text)")
    mt.stub_config(env["ws"], {"story-server status": {"exit": 4, "stderr": "story-server: /usr/sbin/lsof missing\n"}})
    assert lib.story_server_check(env["ws"]) == (
        False, "bin/story-server status exited 4: story-server: /usr/sbin/lsof missing")
    assert lib.judge_key_check() == (False, "--judge needs ANTHROPIC_API_KEY in movie-ui's environment")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-key")
    assert lib.judge_key_check() == (True, "ANTHROPIC_API_KEY is set")
    records = lib.host_checks(mt.fields(env["ws"]), env["ws"], good_py)
    assert [(r["name"], r["status"]) for r in records] == [
        ("render", "skip"), ("stills", "skip"), ("story server", "fail"), ("judge key", "skip")]
    assert records[0]["detail"] == "not needed for this action"
    mt.stub_config(env["ws"], {})
    _story(env)
    records = lib.host_checks(mt.fields(env["ws"], action="movie", judge=True, mode="no_stills"), env["ws"], good_py)
    assert [(r["name"], r["status"]) for r in records] == [
        ("render", "fail"), ("stills", "skip"), ("story server", "skip"), ("judge key", "pass")]


GOOD = {"model.safetensors": b"\x01" * 16, "embedded_config.json": b"{}"}


def test_mut5_v3_models_present_and_intact(env, monkeypatch):
    tmp = env["tmp"]
    ltx = os.path.join(tmp, "ltxcache")
    monkeypatch.setenv("LTX2_MLX_HF_HOME", ltx)
    hub = os.path.join(ltx, "hub")
    assert lib.ltx_hub() == hub
    repo = mt.make_hf_cache(ltx, "org/good", GOOD)
    ok, detail = lib.model_check("org/good", hub)
    assert ok and detail == os.path.join(repo, "snapshots", "0123456789abcdef0123456789abcdef01234567")
    sharded = {"model.safetensors.index.json": json.dumps({"weight_map": {"a": "model-00001.safetensors",
                                                                          "b": "model-00002.safetensors"}}).encode(),
               "model-00001.safetensors": b"\x01"}
    mt.make_hf_cache(ltx, "org/sharded", sharded)
    assert lib.model_check("org/sharded", hub) == (False, "missing shard: model-00002.safetensors")
    mt.make_hf_cache(ltx, "org/partial", GOOD, incomplete=3)
    assert lib.model_check("org/partial", hub) == (False, "download incomplete: 3 partial blob(s)")
    mt.make_hf_cache(ltx, "org/broken", GOOD, broken=("embedded_config.json",))
    assert lib.model_check("org/broken", hub) == (False, "broken file: embedded_config.json")
    mt.make_hf_cache(ltx, "org/empty", {"model.safetensors": b"", "x.json": b"{}"})
    assert lib.model_check("org/empty", hub) == (False, "empty file: model.safetensors")
    mt.make_hf_cache(ltx, "org/nosafe", {"config.json": b"{}"})
    assert lib.model_check("org/nosafe", hub) == (False, "no .safetensors file")
    mt.make_hf_cache(ltx, "org/badindex", {"m.safetensors.index.json": b"{", "m.safetensors": b"\x01"})
    assert lib.model_check("org/badindex", hub) == (False, "unreadable index: m.safetensors.index.json")
    assert lib.model_check("org/absent", hub) == (False, "org/absent is not in %s" % hub)
    two = mt.make_hf_cache(ltx, "org/two", GOOD, refs=False)
    os.makedirs(os.path.join(two, "snapshots", "another"))
    assert lib.model_check("org/two", hub) == (False, "cannot choose a snapshot of org/two (no refs/main)")
    shutil.rmtree(os.path.join(two, "snapshots", "another"))
    assert lib.model_check("org/two", hub)[0] is True
    local = os.path.join(tmp, "local-model")
    os.makedirs(local)
    with open(os.path.join(local, "model.safetensors"), "wb") as f:
        f.write(b"\x01")
    assert lib.model_check(local, hub) == (True, local)
    assert lib.model_check(os.path.join(tmp, "nope"), hub) == (False, "%s is not a directory" % os.path.join(tmp, "nope"))
    # Z-Image: the scoped hub when it holds the repo, else the default HF hub.
    scoped, default = os.path.join(tmp, "zhome"), os.path.join(tmp, "hfhome")
    monkeypatch.setenv("Z_IMAGE_HF_HOME", scoped)
    monkeypatch.setenv("HF_HOME", default)
    mt.make_hf_cache(default, lib.STILLS_BASE_MODEL, GOOD)
    assert lib.zimage_hub_for(lib.STILLS_BASE_MODEL) == os.path.join(default, "hub")
    mt.make_hf_cache(scoped, lib.STILLS_BASE_MODEL, GOOD)
    assert lib.zimage_hub_for(lib.STILLS_BASE_MODEL) == os.path.join(scoped, "hub")
    mt.make_hf_cache(ltx, lib.DEFAULT_MODEL, GOOD)
    records = lib.model_checks(mt.fields(env["ws"], action="movie"), env["ws"])
    assert [(r["name"], r["status"]) for r in records] == [
        ("video model %s" % lib.DEFAULT_MODEL, "pass"), ("gemma %s" % lib.DEFAULT_GEMMA, "fail"),
        ("Z-Image %s" % lib.STILLS_BASE_MODEL, "pass"),
        ("Z-Image text encoder %s" % lib.ZIMAGE_TEXT_ENCODER, "fail")]
    assert records[1]["detail"] == "%s is not in %s" % (lib.DEFAULT_GEMMA, hub)
    story = lib.model_checks(mt.fields(env["ws"]), env["ws"])
    assert [r["status"] for r in story] == ["skip"] * 4


def test_mu63_list_models(env, monkeypatch):
    tmp = env["tmp"]
    for var, sub in (("LTX2_MLX_HF_HOME", "l"), ("Z_IMAGE_HF_HOME", "z"), ("HF_HOME", "h")):
        monkeypatch.setenv(var, os.path.join(tmp, sub))
    mt.make_hf_cache(os.path.join(tmp, "l"), "org/b-model", GOOD)
    mt.make_hf_cache(os.path.join(tmp, "l"), "org/a--model", GOOD, incomplete=1)
    mt.make_hf_cache(os.path.join(tmp, "h"), "Tongyi-MAI/Z-Image-Turbo", GOOD)
    listing = lib.list_models()
    assert listing["hubs"] == {"ltx": os.path.join(tmp, "l", "hub"), "zimage": os.path.join(tmp, "z", "hub"),
                               "hf": os.path.join(tmp, "h", "hub")}
    rows = [(m["hub"], m["repo"], m["intact"], m["problems"], m["bytes"]) for m in listing["models"]]
    assert rows == [("hf", "Tongyi-MAI/Z-Image-Turbo", True, [], 18),
                    ("ltx", "org/a--model", False, ["download incomplete: 1 partial blob(s)"], 19),
                    ("ltx", "org/b-model", True, [], 18)]
