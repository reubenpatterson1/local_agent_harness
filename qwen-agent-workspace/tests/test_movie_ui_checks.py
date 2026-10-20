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


def test_mut5_v3_stale_index_refs_and_walk_cap(env, monkeypatch):
    tmp = env["tmp"]
    ltx = os.path.join(tmp, "ltxcache")
    monkeypatch.setenv("LTX2_MLX_HF_HOME", ltx)
    hub = os.path.join(ltx, "hub")
    five = json.dumps({"weight_map": {"k%d" % i: "model-0000%d-of-00005.safetensors" % i for i in range(5)}}).encode()
    stale = {"model.safetensors.index.json": five, "a.safetensors": b"\x01", "b.safetensors": b"\x02"}
    repo = mt.make_hf_cache(ltx, "org/stale", stale)
    snap = os.path.join(repo, "snapshots", "0123456789abcdef0123456789abcdef01234567")
    assert lib.model_check("org/stale", hub) == (True, snap + "; index lists none of the present shards; ignored")
    some = dict(stale, **{"model-00000-of-00005.safetensors": b"\x01"})
    mt.make_hf_cache(ltx, "org/some", some)
    ok, detail = lib.model_check("org/some", hub)
    assert not ok and "missing shard: model-00001-of-00005.safetensors" in detail
    # an undecodable refs/main is treated as unreadable (single snapshot still chosen)
    with open(os.path.join(repo, "refs", "main"), "wb") as f:
        f.write(b"\xff\xfe")
    assert lib.model_check("org/stale", hub)[0] is True
    # absolute-path walk cap
    local = os.path.join(tmp, "big-model")
    os.makedirs(local)
    for i in range(5):
        with open(os.path.join(local, "f%d.safetensors" % i), "wb") as f:
            f.write(b"\x01")
    monkeypatch.setattr(lib, "MAX_MODEL_WALK_ENTRIES", 3)
    assert lib.model_check(local, hub) == (False, "too many files under %s (more than 3)" % local)


def _entry(entry_id, target="video", kind="motion", path=None, rng=(0.5, 1.0)):
    return {"id": entry_id, "kind": kind, "path": path or "/loras/%s.safetensors" % entry_id, "target": target,
            "strength_range": list(rng), "base_models": []}


def _catalog(env, video=(), stills=(), verify=None, extra=None):
    """Stub `lora-catalog list --model M --json` for the video model and the stills base model."""
    config = dict(extra or {})
    for model, entries in ((lib.DEFAULT_MODEL, video), (lib.STILLS_BASE_MODEL, stills)):
        config["lora-catalog list --model %s --json" % model] = {
            "stdout": json.dumps({"catalog": "/c", "entries": list(entries), "characters": []})}
    if verify is not None:
        config["lora-catalog verify"] = verify
    mt.stub_config(env["ws"], config)
    return config


def _item(entry, strength=0.8):
    return {"id": entry["id"], "path": entry["path"], "strength": strength, "kind": entry["kind"]}


def test_mut6_v4_loras_intact(env):
    ws = env["ws"]
    pan, ink = _entry("pan"), _entry("ink", target="stills", kind="style")
    _catalog(env, video=[pan], stills=[ink])
    records = lib.lora_checks(mt.fields(ws), ws, {})
    assert records == [lib.check("V4", "catalog verify", "pass", "OK ink\nOK pan\nverified 2 entries: 0 problem(s)\n")]
    verify_calls = [c["argv"] for c in mt.stub_calls(ws) if c["sub"] == "verify"]
    assert verify_calls == [["verify", "ink", "pan"]]
    stray = _entry("stray", target="stills", kind="style")
    _catalog(env, video=[pan, stray], stills=[ink])
    records = lib.lora_checks(mt.fields(ws, mode="no_stills"), ws, {})
    assert mt.stub_calls(ws)[-1]["argv"] == ["verify", "pan"]
    assert records == [lib.check("V4", "catalog verify", "pass", "OK pan\nverified 1 entries: 0 problem(s)\n")]
    records = lib.lora_checks(mt.fields(ws, story_legacy=True), ws, {})
    assert records == [lib.check("V4", "catalog verify", "skip", "no catalog LoRA chosen or pickable")]
    _catalog(env, video=[pan], stills=[ink],
             verify={"exit": 1, "stdout": "FAIL pan: sha256 changed since it was cataloged\nverified 1 entry: 1 problem(s)\n"})
    records = lib.lora_checks(mt.fields(ws, auto_lora=False, video_loras=[_item(pan)]), ws, {})
    assert records[0]["status"] == "fail" and "FAIL pan: sha256 changed" in records[0]["detail"]
    tmp = env["tmp"]
    good = mt.fake_safetensors(os.path.join(tmp, "good.safetensors"))
    short = os.path.join(tmp, "short.safetensors")
    with open(short, "wb") as f:
        f.write(b"\x10\x00")
    zero = mt.fake_safetensors(os.path.join(tmp, "zero.safetensors"), n=0)
    trunc = mt.fake_safetensors(os.path.join(tmp, "trunc.safetensors"), n=500)
    notjson = os.path.join(tmp, "notjson.safetensors")
    with open(notjson, "wb") as f:
        f.write((4).to_bytes(8, "little") + b"[1] ")
    missing = os.path.join(tmp, "missing.safetensors")
    free = [{"id": None, "path": p, "strength": 1.0, "kind": None} for p in (good, short, zero, trunc, notjson, missing)]
    records = lib.lora_checks(mt.fields(ws, auto_lora=False, video_loras=free[:3], stills_loras=free[3:]), ws, {})
    assert [(r["name"], r["status"], r["detail"]) for r in records[1:]] == [
        ("LoRA file " + good, "pass", good + ": safetensors header ok"),
        ("LoRA file " + short, "fail", short + ": not a safetensors file"),
        ("LoRA file " + zero, "fail", zero + ": not a safetensors file"),
        ("LoRA file " + trunc, "fail", trunc + ": not a safetensors file"),
        ("LoRA file " + notjson, "fail", notjson + ": not a safetensors file"),
        ("LoRA file " + missing, "fail", missing + " is not a readable file")]


def _character(name, status="trained", video_base="/ltx/models/ltx-2.3-mlx-q8-dev",
               stills_base=lib.STILLS_BASE_MODEL, exit_code=0):
    """{"character show <name>": stub entry} printing the JSON then the files: block (D6)."""
    data = {"name": name, "status": status,
            "loras": {"video": {"base_model": video_base} if video_base else None,
                      "stills": {"base_model": stills_base} if stills_base else None}}
    text = json.dumps(data, indent=2) + "\nfiles:\n  ok       /lib/%s/seed.png\n" % name
    entry = {"stdout": text} if exit_code == 0 else {"exit": exit_code, "stderr": "Error: no character %s\n" % name}
    return {"character show %s" % name: entry}


def test_mut7_v5_compatible(env):
    ws = env["ws"]
    pan, ink, ink2 = _entry("pan"), _entry("ink", target="stills", kind="style"), _entry("ink2", target="stills",
                                                                                          kind="style")
    _catalog(env, video=[pan], stills=[ink, ink2])
    ok = lib.compat_checks(mt.fields(ws, video_loras=[_item(pan)], stills_loras=[_item(ink)]), ws, {})
    assert ok[0] == lib.check("V5", "catalog compatibility", "pass", "every catalog LoRA is compatible")
    assert ok[1] == lib.check("V5", "characters", "skip", "no character cast")
    cases = [
        ({"video_loras": [_item(ink)]}, "ink is not a video LoRA compatible with %s" % lib.DEFAULT_MODEL),
        ({"stills_loras": [_item(pan)]}, "pan is not a stills LoRA compatible with %s" % lib.STILLS_BASE_MODEL),
        ({"video_loras": [dict(_item(pan), path="/elsewhere.safetensors")]},
         "pan: path or kind differs from the catalog; reload the LoRA list"),
        ({"video_loras": [dict(_item(pan), kind="physics")]}, "pan: path or kind differs from the catalog; reload the LoRA list"),
        ({"video_loras": [_item(pan, 1.5)]}, "pan: strength 1.5 is outside 0.5-1.0"),
        ({"stills_loras": [_item(ink), _item(ink2)]}, "at most one style LoRA among the stills LoRAs"),
    ]
    for overrides, message in cases:
        record = lib.compat_checks(mt.fields(ws, **overrides), ws, {})[0]
        assert (record["status"], record["detail"]) == ("fail", message), overrides
    assert lib.compat_checks(mt.fields(ws), ws, {})[0] == lib.check("V5", "catalog compatibility", "skip",
                                                                    "no catalog LoRA chosen")
    extra = {}
    for spec in (_character("kyra"), _character("ronin", status="untrained", video_base=None),
                 _character("mei", stills_base="other/model"), _character("hana", video_base=lib.DEFAULT_MODEL),
                 _character("ghost", exit_code=2)):
        extra.update(spec)
    _catalog(env, video=[pan], stills=[ink, ink2], extra=extra)
    records = lib.compat_checks(mt.fields(ws, characters=["kyra", "ronin", "mei", "hana", "ghost"]), ws, {})
    assert [(r["name"], r["status"], r["detail"]) for r in records[1:]] == [
        ("character kyra", "pass", "trained"),
        ("character kyra video base model", "skip",
         "video LoRA trained on /ltx/models/ltx-2.3-mlx-q8-dev; bin/ltx-movie does not check this against --model %s"
         % lib.DEFAULT_MODEL),
        ("character ronin", "fail", "character ronin is not trained (status untrained)"),
        ("character mei", "fail", "character mei's stills LoRA is for other/model, not %s" % lib.STILLS_BASE_MODEL),
        ("character mei video base model", "skip",
         "video LoRA trained on /ltx/models/ltx-2.3-mlx-q8-dev; bin/ltx-movie does not check this against --model %s"
         % lib.DEFAULT_MODEL),
        ("character hana", "pass", "trained"),
        ("character hana video base model", "pass", "trained on %s" % lib.DEFAULT_MODEL),
        ("character ghost", "fail", "Error: no character ghost")]


def test_mut8_v6_dry_run(env, monkeypatch):
    ws = env["ws"]
    fields = mt.fields(ws, action="movie")
    record = lib.dry_run_check(fields, ws, env["state"])
    assert record == lib.check("V6", "dry run", "pass", "")
    call = mt.stub_calls(ws)[-1]
    assert call["argv"][-2:] == ["--no-review", "--dry-run"] and call["env"]["STORY_PIPELINE_LOGGED"] == "1"
    assert call["cwd"] == ws
    mt.stub_config(ws, {"ltx-movie --dry-run": {"exit": 2, "stderr": "Error: --redo needs --shots\n"}})
    record = lib.dry_run_check(fields, ws, env["state"])
    assert (record["status"], record["detail"]) == ("fail", "Error: --redo needs --shots\n")
    monkeypatch.setattr(lib, "DRY_RUN_TIMEOUT", 1)
    mt.stub_config(ws, {"ltx-movie --dry-run": {"sleep": 3}})
    record = lib.dry_run_check(fields, ws, env["state"])
    assert (record["status"], record["detail"]) == ("fail", "bin/ltx-movie --dry-run timed out after 1 s")


def test_mu43_run_checks_order_and_v1_short_circuit(env, monkeypatch):
    ws = env["ws"]
    bad = lib.run_checks(mt.fields(ws, panels=0), ws, env["state"])
    assert [(r["id"], r["name"], r["status"]) for r in bad] == [
        ("V1", "fields", "fail"), ("V2", "host can run it", "skip"), ("V3", "models present and intact", "skip"),
        ("V4", "LoRAs intact", "skip"), ("V5", "compatible", "skip"), ("V6", "dry run", "skip")]
    assert bad[1]["detail"] == "skipped: V1 failed"
    good = lib.run_checks(mt.fields(ws), ws, env["state"])
    assert [(r["id"], r["name"], r["status"]) for r in good] == [
        ("V1", "fields", "pass"), ("V2", "render", "skip"), ("V2", "stills", "skip"),
        ("V2", "story server", "pass"), ("V2", "judge key", "skip"),
        ("V3", "video model %s" % lib.DEFAULT_MODEL, "skip"), ("V3", "gemma %s" % lib.DEFAULT_GEMMA, "skip"),
        ("V3", "Z-Image %s" % lib.STILLS_BASE_MODEL, "skip"),
        ("V3", "Z-Image text encoder %s" % lib.ZIMAGE_TEXT_ENCODER, "skip"),
        ("V4", "catalog verify", "skip"), ("V5", "catalog compatibility", "skip"), ("V5", "characters", "skip"),
        ("V6", "dry run", "pass")]
    assert lib.checks_pass(good) and not lib.checks_pass(bad)
    assert len(lib.check("V6", "dry run", "fail", "x" * 30000)["detail"]) == 20000


def test_v4_auto_set_fail_does_not_block_but_chosen_fail_does(env):
    ws = env["ws"]
    pan, ink = _entry("pan"), _entry("ink", target="stills", kind="style")
    out = "OK pan\nFAIL ink: sha256 changed since it was cataloged\nverified 2 entries: 1 problem(s)\n"
    _catalog(env, video=[pan], stills=[ink], verify={"exit": 1, "stdout": out})
    records = lib.lora_checks(mt.fields(ws, auto_lora=True, video_loras=[_item(pan)]), ws, {})
    assert [(r["name"], r["status"]) for r in records] == [("catalog verify", "pass"), ("LoRAs auto set", "skip")]
    assert records[1]["detail"] == "the planner will skip these entries:\nFAIL ink: sha256 changed since it was cataloged"
    records = lib.lora_checks(mt.fields(ws, auto_lora=True, video_loras=[_item(pan)], stills_loras=[_item(ink)]), ws, {})
    assert (records[0]["status"], records[0]["detail"]) == ("fail", "FAIL ink: sha256 changed since it was cataloged")
    _catalog(env, video=[pan], stills=[ink], verify={"exit": 2, "stderr": "Error: no catalog entry pan\n"})
    records = lib.lora_checks(mt.fields(ws, auto_lora=True), ws, {})
    assert [(r["status"], r["detail"]) for r in records] == [("fail", "Error: no catalog entry pan\n")]


def _timed_out(argv, cwd, env=None, timeout=None):
    return {"argv": list(argv), "exit_code": None, "stdout": "partial", "stderr": "", "timed_out": True}


def test_v4_verify_timeout_is_reported(env, monkeypatch):
    ws = env["ws"]
    pan = _entry("pan")
    monkeypatch.setattr(lib, "run_light", _timed_out)
    records = lib.lora_checks(mt.fields(ws, auto_lora=False, video_loras=[_item(pan)]), ws, {})
    assert records == [lib.check("V4", "catalog verify", "fail", "bin/lora-catalog verify timed out after 300 s")]


def test_v5_character_show_timeout_is_reported(env, monkeypatch):
    ws = env["ws"]
    monkeypatch.setattr(lib, "run_light", _timed_out)
    records = lib.compat_checks(mt.fields(ws, characters=["kyra"]), ws, {})
    assert records[-1] == lib.check("V5", "character kyra", "fail",
                                    "bin/character show kyra timed out after %d s" % lib.LIGHT_TIMEOUT)
