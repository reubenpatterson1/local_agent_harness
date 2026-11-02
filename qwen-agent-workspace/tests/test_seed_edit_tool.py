"""Tests for bin/seed-edit, seed_edit_mflux_child.py and bin/seed-edit-setup (docs/superpowers/specs/
2026-11-02-seed-generator-design.md, Section 9: SGT1-SGT16, with the plan's Review Focus pins 3
and 4), and the seed models registry in them (docs/superpowers/specs/2026-11-02-seed-models-
design.md, Section 9.2: SQT1-SQT14, with that plan's Review Focus pins 1, 3, 4 and 5).

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py

Rules (spec Section 9):
- bin/seed-edit is loaded with importlib.machinery.SourceFileLoader("seed_edit_tool", path),
  importlib.util.spec_from_loader, importlib.util.module_from_spec and loader.exec_module (never
  the deprecated loader shortcut); seed_edit_mflux_child.py is a plain import.
- Every test sets HOME to tmp_path/home, removes HF_HUB_CACHE and every SEED_EDIT_* variable, and
  sets HF_HOME and Z_IMAGE_HF_HOME under tmp_path (the env fixture). HF caches are built with
  mt.make_hf_cache: one non-empty .safetensors file per repo, plus the Lightning file where needed.
- Process boundaries are stubbed, never crossed for real: the bf16 child through
  SEED_EDIT_QWENEDIT_SCRIPT (a Python stub run by sys.executable), the mflux child through
  SEED_EDIT_MFLUX_PYTHON (an executable stub whose shebang is sys.executable, beside a fake
  lib/python3.13/site-packages/mflux-<v>.dist-info/METADATA), and z_image_skill, content_safety
  and character_dataset through sys.modules fakes. Each stub records its argv, an env subset and
  its spec, and behaves per a config file its test writes. The fake assert_image_safe raises
  ContentSafetyError when the image's top-left pixel is pure red.
- tool.avail_gib, tool.total_gib, tool.missing_modules, tool.cpu_generator and tool.disk_free_gib
  are monkeypatched (cpu_generator returns the seed itself). Sources are real PNG, JPEG and GIF
  files drawn with PIL under tmp_path.
- No test uses the real HOME, loads a real model, runs bin/seed-edit-setup, or contacts a server.
  None touches port 8177 or 8178.
Stdlib, PIL and pytest.
"""

import glob
import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import types

import pytest
from PIL import Image

import movie_ui_testutil as mt
import movie_ui_lib as lib
import movie_ui_seedgen as seedgen

WS = mt.WS
TOOL_PATH = os.path.join(WS, "bin", "seed-edit")
PROMPT = "make it night"
RED = (255, 0, 0)
UP = "a" * 64 + ".png"
REV = "0123456789abcdef0123456789abcdef01234567"
R1, R2, R3, R4, R5 = ("se-20261102-141500-000%d" % i for i in range(1, 6))
RUN = "se-20261102-141500-a1b2"


def load_tool():
    loader = importlib.machinery.SourceFileLoader("seed_edit_tool", TOOL_PATH)
    spec = importlib.util.spec_from_loader("seed_edit_tool", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def png(path, size, color=(0, 128, 0)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def make_fakes(monkeypatch):
    """sys.modules fakes of content_safety, z_image_skill and character_dataset. calls["plan"] maps a
    seed (the fake generator) to "red" (blocked) or an exception the fake raises."""
    calls = {"safety": [], "zimage": [], "busy": None, "plan": {}}
    safety = types.ModuleType("content_safety")

    class ContentSafetyError(RuntimeError):
        pass

    def assert_image_safe(image, *, skill, prompt):
        calls["safety"].append({"skill": skill, "prompt": prompt, "size": image.size})
        if image.convert("RGB").getpixel((0, 0)) == RED:
            raise ContentSafetyError("CONTENT SAFETY BLOCK (fake)")

    safety.ContentSafetyError = ContentSafetyError
    safety.assert_image_safe = assert_image_safe
    zimage = types.ModuleType("z_image_skill")

    def generate_variation(seed_image, prompt, output_path=None, strength=0.45, generator=None, **kwargs):
        calls["zimage"].append({"size": seed_image.size, "mode": seed_image.mode, "prompt": prompt,
                                "strength": strength, "generator": generator, "output_path": output_path})
        action = calls["plan"].get(generator)
        if isinstance(action, BaseException):
            raise action
        image = Image.new("RGB", seed_image.size, RED if action == "red" else (0, 0, 200))
        assert_image_safe(image, skill="z_image_skill", prompt=prompt)
        return image

    zimage.generate_variation = generate_variation
    dataset = types.ModuleType("character_dataset")
    dataset.busy_process = lambda: calls["busy"]
    for name, module in (("content_safety", safety), ("z_image_skill", zimage), ("character_dataset", dataset)):
        monkeypatch.setitem(sys.modules, name, module)
    return calls


@pytest.fixture
def env(monkeypatch, tmp_path):
    tmp = str(tmp_path)
    home = os.path.join(tmp, "home")
    os.makedirs(home)
    monkeypatch.setenv("HOME", home)
    for key in list(os.environ):
        if key.startswith("SEED_EDIT_"):
            monkeypatch.delenv(key)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", os.path.join(tmp, "hf"))
    monkeypatch.setenv("Z_IMAGE_HF_HOME", os.path.join(tmp, "zi"))
    tool = load_tool()
    gens = []
    monkeypatch.setattr(tool, "avail_gib", lambda: 40.0)
    monkeypatch.setattr(tool, "total_gib", lambda: 48.0)
    monkeypatch.setattr(tool, "missing_modules", lambda names: [])
    monkeypatch.setattr(tool, "disk_free_gib", lambda path: 100.0)
    monkeypatch.setattr(tool, "cpu_generator", lambda seed: gens.append(seed) or seed)
    return {"tmp": tmp, "tool": tool, "gens": gens, "calls": make_fakes(monkeypatch), "mp": monkeypatch,
            "zhub": os.path.join(tmp, "zi", "hub"), "hfhub": os.path.join(tmp, "hf", "hub")}


def zimage_cache(env):
    for repo in (lib.STILLS_BASE_MODEL, lib.ZIMAGE_TEXT_ENCODER):
        mt.make_hf_cache(os.path.join(env["tmp"], "zi"), repo, {"x.safetensors": b"\x01" * 8})


def bf16_cache(env):
    root, tool = os.path.join(env["tmp"], "hf"), env["tool"]
    mt.make_hf_cache(root, tool.EDIT_MODEL, {"transformer/x.safetensors": b"\x01" * 8})
    mt.make_hf_cache(root, tool.EDIT_LORA_REPO, {tool.EDIT_LORA_FILE: b"\x01" * 8})


def mflux_weights(env, lora=True):
    """The q4 repo (and the Lightning repo) in the Z-Image hub; returns (q4 snapshot, Lightning path)."""
    root, tool = os.path.join(env["tmp"], "zi"), env["tool"]
    q4 = mt.make_hf_cache(root, tool.Q4_REPO, {"transformer/0.safetensors": b"\x01" * 8})
    path = None
    if lora:
        repo = mt.make_hf_cache(root, tool.EDIT_LORA_REPO, {tool.EDIT_LORA_FILE: b"\x01" * 8})
        path = os.path.join(repo, "snapshots", REV, tool.EDIT_LORA_FILE)
    return os.path.join(q4, "snapshots", REV), path


MFLUX_STUB = r'''#!__PYTHON__
"""Stub of the mflux child (tests only): records argv, env and spec, then obeys config.json."""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
with open(args[args.index("--spec") + 1], encoding="utf-8") as f:
    spec = json.load(f)
try:
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        config = json.load(f)
except OSError:
    config = {}
with open(os.path.join(HERE, "calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": sys.argv, "spec": spec,
                        "env": {k: os.environ.get(k) for k in ("HF_HUB_OFFLINE", "PYTHONUNBUFFERED")}}) + "\n")
time.sleep(config.get("sleep", 0))
from PIL import Image
for i, job in enumerate(spec["jobs"]):
    if config.get("fail_after") == i:
        print("boom", flush=True)
        sys.exit(1)
    if config.get("kill_after") == i:
        print("killed", flush=True)
        os.kill(os.getpid(), 9)
    color = (255, 0, 0) if job["n"] in config.get("red", []) else (0, 0, 200)
    Image.new("RGB", (spec["width"], spec["height"]), color).save(job["output_path"])
    print(config.get("prefix", "") + "seed-edit-child done %d 1.0" % job["n"], flush=True)
'''

QWENEDIT_STUB = r'''"""Stub of character_dataset.py qwenedit (tests only): records argv, env and spec, then obeys
config.json."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
with open(args[args.index("--spec") + 1], encoding="utf-8") as f:
    spec = json.load(f)
try:
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        config = json.load(f)
except OSError:
    config = {}
with open(os.path.join(HERE, "calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": [sys.executable] + sys.argv, "spec": spec,
                        "env": {k: os.environ.get(k) for k in ("PYTHONUNBUFFERED",)}}) + "\n")
from PIL import Image
for job in spec["jobs"]:
    name = os.path.basename(job["output_path"])
    status = "blocked" if int(name[5:7]) in config.get("blocked", []) else "ok"
    if status == "ok":
        Image.new("RGB", (job["width"], job["height"]), (0, 0, 200)).save(job["output_path"])
    print(config.get("prefix", "") + "%s %s 1.0s" % (name, status), flush=True)
sys.exit(config.get("exit", 0))
'''


def set_mflux_version(venv, text):
    """Replace the venv's mflux dist-info with one whose METADATA says Version: text (None: none)."""
    site = os.path.join(venv, "lib", "python3.13", "site-packages")
    for old in glob.glob(os.path.join(site, "mflux-*.dist-info")):
        os.remove(os.path.join(old, "METADATA"))
        os.rmdir(old)
    if text is not None:
        info = os.path.join(site, "mflux-%s.dist-info" % text)
        os.makedirs(info)
        with open(os.path.join(info, "METADATA"), "w", encoding="utf-8") as f:
            f.write("Metadata-Version: 2.1\nName: mflux\nVersion: %s\n" % text)


def mflux_venv(env, version="0.24.0"):
    """The stub venv python (SEED_EDIT_MFLUX_PYTHON) and its dist-info; returns (python, venv)."""
    venv = os.path.join(env["tmp"], "mflux-edit", ".venv")
    py = os.path.join(venv, "bin", "python")
    os.makedirs(os.path.dirname(py), exist_ok=True)
    with open(py, "w", encoding="utf-8") as f:
        f.write(MFLUX_STUB.replace("__PYTHON__", sys.executable))
    os.chmod(py, 0o755)
    set_mflux_version(venv, version)
    env["mp"].setenv("SEED_EDIT_MFLUX_PYTHON", py)
    return py, venv


def qwenedit_stub(env, config):
    path = os.path.join(env["tmp"], "qwenedit", "stub.py")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(QWENEDIT_STUB)
    stub_config(path, config)
    env["mp"].setenv("SEED_EDIT_QWENEDIT_SCRIPT", path)
    return path


def stub_config(stub, config):
    with open(os.path.join(os.path.dirname(stub), "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)


def stub_calls(stub):
    try:
        with open(os.path.join(os.path.dirname(stub), "calls.jsonl"), encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except OSError:
        return []


def run_tool(env, *extra, source=None, run=RUN, prompt=PROMPT, model="zimage"):
    """tool.main for one run directory <tmp>/runs/<run> (source: a 1536x1024 PNG by default);
    returns (exit code, run directory)."""
    if source is None:
        source = os.path.join(env["tmp"], "src.png")
        if not os.path.isfile(source):
            png(source, (1536, 1024))
    run_dir = os.path.join(env["tmp"], "runs", run)
    argv = ["--source", source, "--prompt", prompt, "--model", model, "--run-dir", run_dir] + list(extra)
    return env["tool"].main(argv), run_dir


def record_of(run_dir):
    return read_json(os.path.join(run_dir, "run.json"))


def statuses(run_dir):
    return [c["status"] for c in record_of(run_dir)["candidates"]]


def cand(run_dir, n):
    return os.path.join(run_dir, "cand_%02d.png" % n)


def plain(lines):
    """Candidate lines with the seconds replaced by S."""
    return [re.sub(r" [0-9]+\.[0-9]s$", " Ss", line) for line in lines]


# --- SGT1 (SG8): the canvas ----------------------------------------------------------------------------

CANVAS = [((1536, 1024), (1024, 672)), ((1024, 1024), (1024, 1024)), ((800, 600), (800, 592)),
          ((4000, 3000), (1024, 768)), ((3000, 4000), (768, 1024)), ((720, 1280), (576, 1024)),
          ((1023, 1023), (1008, 1008)), ((100, 70), (96, 64))]


def test_sgt1_the_canvas(env):
    tool = env["tool"]
    for (w0, h0), want in CANVAS:
        assert tool.canvas(w0, h0) == want, (w0, h0)
    with pytest.raises(tool.Refusal) as info:
        tool.canvas(100, 60)
    assert str(info.value) == "--source is too small: 100x60 gives a 96x48 canvas; each side must be at least 64 px"


# --- SGT2 (SG11, SG12, SG16, SG18): a Z-Image run ------------------------------------------------------

def test_sgt2_a_zimage_run(env, capsys):
    tool = env["tool"]
    zimage_cache(env)
    run_dir = os.path.join(env["tmp"], "runs", RUN)
    seen = []
    real_say = tool.say

    def spy(text):
        found = re.match(r"^candidate (\d+)/3 ", text)
        if found:
            n = int(found.group(1))
            seen.append((n, record_of(run_dir)["candidates"][n - 1]["status"], os.path.isfile(cand(run_dir, n))))
        real_say(text)

    env["mp"].setattr(tool, "say", spy)
    code, _run = run_tool(env, "--strength", "0.3", "--candidates", "3", "--seed", "100")
    assert code == 0
    assert env["gens"] == [101, 102, 103]
    assert [(c["size"], c["mode"], c["prompt"], c["strength"], c["output_path"]) for c in env["calls"]["zimage"]] == [
        ((1024, 672), "RGB", PROMPT, 0.3, None)] * 3
    assert env["calls"]["safety"] == [{"skill": "z_image_skill", "prompt": PROMPT, "size": (1024, 672)}] * 3
    for n in (1, 2, 3):
        with Image.open(cand(run_dir, n)) as img:
            assert img.size == (1024, 672)
    with open(os.path.join(env["tmp"], "src.png"), "rb") as f, open(os.path.join(run_dir, "source.png"), "rb") as g:
        assert f.read() == g.read()
    with Image.open(os.path.join(run_dir, "work", "source.png")) as img:
        assert img.size == (1536, 1024)
    record = record_of(run_dir)
    assert re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", record["created"])
    assert all(isinstance(c["seconds"], float) for c in record["candidates"])
    assert dict(record, created=None, candidates=[dict(c, seconds=None) for c in record["candidates"]]) == {
        "schema": "seed-edit.run.v1", "run": RUN, "created": None, "state": "done", "prompt": PROMPT,
        "model": "zimage", "backend": "zimage", "strength": 0.3, "seed": 100,
        "size": {"width": 1024, "height": 672}, "source_size": {"width": 1536, "height": 1024},
        "source": "source.png", "source_origin": None, "job": None, "error": None,
        "candidates": [{"n": n, "seed": 100 + n, "status": "ok", "seconds": None} for n in (1, 2, 3)]}
    out = capsys.readouterr().out.splitlines()
    assert out[:3] == ["seed-edit: run %s" % run_dir, "seed-edit: source 1536x1024 -> 1024x672",
                       "seed-edit: backend zimage (Z-Image img2img)"]
    assert plain(out[3:]) == ["candidate 1/3 ok Ss", "candidate 2/3 ok Ss", "candidate 3/3 ok Ss",
                              "seed-edit: done: 3 ok, 0 blocked, 0 failed"]
    assert seen == [(1, "ok", True), (2, "ok", True), (3, "ok", True)]


def test_sgt2_a_queued_record_keeps_created_origin_and_job(env):
    zimage_cache(env)
    run_dir = os.path.join(env["tmp"], "runs", RUN)
    os.makedirs(run_dir)
    origin = {"kind": "upload", "upload_id": UP}
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as f:
        json.dump({"created": "2026-11-02T14:15:00Z", "source_origin": origin, "job": "20261102-141500-a1b2",
                   "state": "queued", "prompt": "old"}, f)
    assert run_tool(env, "--candidates", "1", "--seed", "1")[0] == 0
    record = record_of(run_dir)
    assert (record["created"], record["source_origin"], record["job"]) == (
        "2026-11-02T14:15:00Z", origin, "20261102-141500-a1b2")
    assert (record["prompt"], record["state"]) == (PROMPT, "done")


# --- SGT3 (SG18): a blocked candidate ------------------------------------------------------------------

def test_sgt3_a_blocked_candidate(env, capsys):
    zimage_cache(env)
    env["calls"]["plan"][102] = "red"
    code, run_dir = run_tool(env, "--candidates", "3", "--seed", "100")
    assert code == 0
    assert [os.path.isfile(cand(run_dir, n)) for n in (1, 2, 3)] == [True, False, True]
    record = record_of(run_dir)
    assert statuses(run_dir) == ["ok", "blocked", "ok"]
    assert (record["state"], record["error"]) == ("done", None)
    assert isinstance(record["candidates"][1]["seconds"], float)
    out = capsys.readouterr().out.splitlines()
    assert plain(out[3:]) == ["candidate 1/3 ok Ss", "candidate 2/3 blocked Ss", "candidate 3/3 ok Ss",
                              "seed-edit: done: 2 ok, 1 blocked, 0 failed"]


# --- SGT4 (SG17, SG18): a Z-Image crash ----------------------------------------------------------------

def test_sgt4_a_zimage_crash(env, capsys):
    zimage_cache(env)
    env["calls"]["plan"][102] = RuntimeError("boom")
    run_dir = os.path.join(env["tmp"], "runs", RUN)
    for name in ("cand_09.part.png", "cand_09.pending.png"):
        png(os.path.join(run_dir, "work", name), (8, 8))
    code, _run = run_tool(env, "--candidates", "3", "--seed", "100")
    assert code == 1
    assert [os.path.isfile(cand(run_dir, n)) for n in (1, 2, 3)] == [True, False, False]
    record = record_of(run_dir)
    assert statuses(run_dir) == ["ok", "failed", "failed"]
    assert [c["seconds"] for c in record["candidates"][1:]] == [None, None]
    assert (record["state"], record["error"]) == ("failed", "Z-Image failed on candidate 2: RuntimeError: boom")
    out = capsys.readouterr().out.splitlines()
    assert plain(out[3:]) == ["candidate 1/3 ok Ss", "candidate 2/3 failed", "candidate 3/3 failed",
                              "seed-edit: done: 1 ok, 0 blocked, 2 failed"]
    assert glob.glob(os.path.join(run_dir, "work", "*.part.png")) == []
    assert glob.glob(os.path.join(run_dir, "work", "*.pending.png")) == []


# --- SGT5 (SG4): bad arguments -------------------------------------------------------------------------

BASE = ["--source", "SRC", "--prompt", PROMPT, "--model", "zimage", "--run-dir", "RUNDIR"]
ARG_CASES = [
    (["--probe", "--model", "qwen"], "--probe takes no other options"),
    (["--source", "SRC", "--prompt", PROMPT, "--model", "zimage"], "--source, --prompt, --model and --run-dir are required"),
    (BASE + ["--model", "flux"], "--model must be zimage or qwen"),
    (BASE + ["--prompt", "  "], "--prompt must not be empty"),
    (BASE + ["--prompt", "x" * 2001], "--prompt is longer than 2000 characters"),
    (BASE + ["--candidates", "0"], "--candidates must be an integer from 1 to 4"),
    (BASE + ["--candidates", "5"], "--candidates must be an integer from 1 to 4"),
    (BASE + ["--candidates", "x"], "--candidates must be an integer from 1 to 4"),
    (BASE + ["--candidates", "0", "--strength", "0.05"], "--candidates must be an integer from 1 to 4"),
    (BASE + ["--model", "qwen", "--strength", "0.3"], "--strength is only for --model zimage"),
    (BASE + ["--strength", "0.05"], "--strength must be a number from 0.10 to 0.90"),
    (BASE + ["--strength", "0.95"], "--strength must be a number from 0.10 to 0.90"),
    (BASE + ["--strength", "x"], "--strength must be a number from 0.10 to 0.90"),
    (BASE + ["--strength", "nan"], "--strength must be a number from 0.10 to 0.90"),
    (BASE + ["--seed", "-1"], "--seed must be an integer from 0 to 2147483647"),
    (BASE + ["--seed", "2147483648"], "--seed must be an integer from 0 to 2147483647"),
    (BASE + ["--seed", "1.5"], "--seed must be an integer from 0 to 2147483647"),
]


@pytest.mark.parametrize("argv,message", ARG_CASES, ids=["case%d" % (i + 1) for i in range(len(ARG_CASES))])
def test_sgt5_bad_arguments(env, capsys, argv, message):
    source = png(os.path.join(env["tmp"], "src.png"), (128, 128))
    run_dir = os.path.join(env["tmp"], "runs", RUN)
    argv = [source if a == "SRC" else run_dir if a == "RUNDIR" else a for a in argv]
    assert env["tool"].main(argv) == 2
    assert capsys.readouterr() == ("", "Error: %s\n" % message)
    assert not os.path.exists(run_dir)
    assert env["calls"]["zimage"] == []


# --- SGT6 (SG9, SG10, SG12): bad and odd sources -------------------------------------------------------

def test_sgt6_bad_and_odd_sources(env, capsys):
    zimage_cache(env)
    tmp = env["tmp"]
    gif = os.path.join(tmp, "anim.gif")
    Image.new("RGB", (200, 200)).save(gif)
    code, run_dir = run_tool(env, source=gif, run=R1)
    text = "--source must be a PNG, JPEG or WebP image (got GIF): %s" % gif
    assert code == 2 and capsys.readouterr().err == "Error: %s\n" % text
    record = record_of(run_dir)
    assert (record["state"], record["error"], record["backend"]) == ("failed", text, None)
    assert (record["size"], record["source_size"], record["source"]) == (None, None, None)
    assert statuses(run_dir) == ["failed"] * 4
    small = png(os.path.join(tmp, "small.png"), (100, 60))
    code, run_dir = run_tool(env, source=small, run=R2)
    text = "--source is too small: 100x60 gives a 96x48 canvas; each side must be at least 64 px"
    assert code == 2 and capsys.readouterr().err == "Error: %s\n" % text
    assert (record_of(run_dir)["error"], record_of(run_dir)["size"]) == (text, None)
    junk = os.path.join(tmp, "junk.png")
    with open(junk, "wb") as f:
        f.write(b"not an image")
    code, run_dir = run_tool(env, source=junk, run=R3)
    assert code == 2
    assert record_of(run_dir)["error"].startswith("cannot read --source %s: UnidentifiedImageError: " % junk)
    capsys.readouterr()
    outside = png(os.path.join(tmp, "elsewhere", "pic.png"), (300, 200), (10, 20, 30))
    code, run_dir = run_tool(env, "--candidates", "1", source=outside, run=R4)
    assert code == 0
    with open(outside, "rb") as f, open(os.path.join(run_dir, "source.png"), "rb") as g:
        assert f.read() == g.read()
    exif = Image.Exif()
    exif[0x0112] = 6
    jpeg = os.path.join(tmp, "phone.jpg")
    Image.new("RGB", (200, 100), (0, 200, 0)).save(jpeg, "JPEG", exif=exif.tobytes())
    code, run_dir = run_tool(env, "--candidates", "1", source=jpeg, run=R5)
    assert code == 0
    record = record_of(run_dir)
    assert (record["source"], record["source_size"], record["size"]) == (
        "source.jpg", {"width": 100, "height": 200}, {"width": 96, "height": 192})
    with Image.open(os.path.join(run_dir, "work", "source.png")) as img:
        assert img.size == (100, 200)
    with open(jpeg, "rb") as f, open(os.path.join(run_dir, "source.jpg"), "rb") as g:
        assert f.read() == g.read()
    assert env["calls"]["zimage"][-1]["size"] == (96, 192)


# --- SGT7 (SG13): preflight refusals -------------------------------------------------------------------

def _refused(run_dir, text, captured):
    record = record_of(run_dir)
    assert (record["state"], record["error"], record["backend"]) == ("failed", text, None)
    assert set(statuses(run_dir)) == {"failed"}
    assert captured.err.endswith("Error: %s\n" % text)


def test_sgt7_preflight_refusals(env, capsys):
    tool, mp, calls = env["tool"], env["mp"], env["calls"]
    zimage_cache(env)
    mp.setattr(tool, "disk_free_gib", lambda path: 1.5)
    code, run_dir = run_tool(env, run=R1)
    assert code == 2
    _refused(run_dir, "less than 2 GiB free on the disk holding %s (1.5 GiB free)" % run_dir, capsys.readouterr())
    mp.setattr(tool, "disk_free_gib", lambda path: 100.0)
    calls["busy"] = (4242, "bin/ltx-movie --story-id x")
    code, run_dir = run_tool(env, run=R2)
    assert code == 2
    _refused(run_dir, "another GPU process is running (pid 4242: bin/ltx-movie --story-id x); try again when "
                      "it ends", capsys.readouterr())
    calls["busy"] = None
    mp.setattr(tool, "missing_modules", lambda names: ["torch"])
    code, run_dir = run_tool(env, run=R3)
    assert code == 2
    _refused(run_dir, "Z-Image is unavailable: torch not importable by %s" % sys.executable, capsys.readouterr())
    mp.setattr(tool, "missing_modules", lambda names: [])
    mp.setattr(tool, "avail_gib", lambda: 10.0)
    mp.setattr(tool, "AVAIL_WAIT_S", 0)
    code, run_dir = run_tool(env, run=R4)
    assert code == 2
    captured = capsys.readouterr()
    assert "seed-edit: waiting up to 0 s for 20 GiB available (now 10.0 GiB)\n" in captured.out
    _refused(run_dir, "only 10.0 GiB available after waiting 0 s; Z-Image needs 20 GiB; free memory and retry",
             captured)
    py, _venv = mflux_venv(env)
    mflux_weights(env)
    code, run_dir = run_tool(env, run=R5, model="qwen")
    assert code == 2
    _refused(run_dir, "only 10.0 GiB available after waiting 0 s; mflux q4 needs 32 GiB; free memory and retry",
             capsys.readouterr())
    assert calls["zimage"] == [] and stub_calls(py) == []
    assert record_of(run_dir)["size"] == {"width": 1024, "height": 672}


# --- SGT8 (SG14): the run-time Qwen choice -------------------------------------------------------------

def _qwen_refusal(tool):
    with pytest.raises(tool.Refusal) as info:
        tool.choose_qwen()
    return str(info.value)


def test_sgt8_choose_qwen(env):
    tool, mp, tmp = env["tool"], env["mp"], env["tmp"]
    zhub, hfhub = env["zhub"], env["hfhub"]
    lora_file = tool.EDIT_LORA_FILE
    head = "Qwen-Image-Edit is unavailable: diffusers bf16: Qwen/Qwen-Image-Edit-2511 is not in %s; mflux q4: " % hfhub
    py = os.path.join(tmp, "mflux-edit", ".venv", "bin", "python")
    venv = os.path.dirname(os.path.dirname(py))
    mp.setenv("SEED_EDIT_MFLUX_PYTHON", py)
    assert _qwen_refusal(tool) == head + "no mflux venv at %s (run bin/seed-edit-setup)" % py
    mflux_venv(env, version=None)
    assert _qwen_refusal(tool) == head + "mflux is not installed in %s (run bin/seed-edit-setup)" % venv
    set_mflux_version(venv, "banana")
    assert _qwen_refusal(tool) == head + "cannot read the mflux version in %s" % venv
    set_mflux_version(venv, "0.21.0")
    assert _qwen_refusal(tool) == head + "mflux 0.21.0 in %s is older than 0.22.0 (run bin/seed-edit-setup)" % venv
    set_mflux_version(venv, "0.24.0")
    assert _qwen_refusal(tool) == head + (
        "mflux-community/qwen-image-edit-2511-mflux-q4 is not in %s or %s (run bin/seed-edit-setup)" % (zhub, hfhub))
    q4, _lora = mflux_weights(env, lora=False)
    assert _qwen_refusal(tool) == head + "Lightning LoRA %s is not in %s or %s (run bin/seed-edit-setup)" % (
        lora_file, zhub, hfhub)
    lora_repo = mt.make_hf_cache(os.path.join(tmp, "zi"), tool.EDIT_LORA_REPO, {lora_file: b"\x01" * 8})
    lora = os.path.join(lora_repo, "snapshots", REV, lora_file)
    paths = {}
    assert tool.choose_qwen(paths) == ("mflux-q4", "diffusers bf16: Qwen/Qwen-Image-Edit-2511 is not in %s" % hfhub)
    assert paths == {"q4_dir": q4, "lora_file": lora}
    assert tool.mflux_problem() == (None, q4, lora)
    mp.setenv("SEED_EDIT_LIGHTNING_FILE", "relative.safetensors")
    assert _qwen_refusal(tool) == head + "SEED_EDIT_LIGHTNING_FILE relative.safetensors is not a non-empty file"
    mp.delenv("SEED_EDIT_LIGHTNING_FILE")
    mp.setenv("SEED_EDIT_QWEN_Q4_DIR", "qwen-image-edit-2511-q4")
    assert _qwen_refusal(tool) == head + "SEED_EDIT_QWEN_Q4_DIR qwen-image-edit-2511-q4: not an absolute path"
    wrong = os.path.join(tmp, "models", "qwen-edit-q4")
    os.makedirs(wrong)
    mp.setenv("SEED_EDIT_QWEN_Q4_DIR", wrong)
    assert _qwen_refusal(tool) == head + (
        "SEED_EDIT_QWEN_Q4_DIR %s: the directory name must contain qwen-image-edit-2511" % wrong)
    right = os.path.join(tmp, "models", "QWEN-IMAGE-EDIT-2511-q4")
    os.makedirs(right)
    mp.setenv("SEED_EDIT_QWEN_Q4_DIR", right)
    assert _qwen_refusal(tool) == head + "SEED_EDIT_QWEN_Q4_DIR %s: no .safetensors file" % right
    with open(os.path.join(right, "model.safetensors"), "wb") as f:
        f.write(b"\x01" * 8)
    paths = {}
    assert tool.choose_qwen(paths)[0] == "mflux-q4" and paths == {"q4_dir": right, "lora_file": lora}
    mp.delenv("SEED_EDIT_QWEN_Q4_DIR")
    bf16_cache(env)
    mp.setattr(tool, "avail_gib", lambda: 70.0)
    assert tool.choose_qwen() == ("diffusers-bf16", "70.0 GiB available")
    mp.setattr(tool, "avail_gib", lambda: 40.0)
    assert tool.choose_qwen() == ("mflux-q4", "diffusers bf16: only 40.0 GiB available (needs 64)")


# --- SGT9 (SG20, SG21, SG22): the mflux child, screened in the parent ----------------------------------

def test_sgt9_the_mflux_child_screened_in_the_parent(env, capsys):
    py, _venv = mflux_venv(env)
    q4, lora = mflux_weights(env)
    stub_config(py, {"red": [2]})
    code, run_dir = run_tool(env, "--candidates", "3", "--seed", "100", model="qwen")
    assert code == 0
    work = os.path.join(run_dir, "work")
    calls = stub_calls(py)
    assert len(calls) == 1
    assert calls[0]["argv"] == [py, os.path.join(WS, "seed_edit_mflux_child.py"), "--spec",
                                os.path.join(work, "mflux_spec.json")]
    assert calls[0]["env"] == {"HF_HUB_OFFLINE": "1", "PYTHONUNBUFFERED": "1"}
    assert calls[0]["spec"] == {
        "model_path": q4, "lora_path": lora, "prompt": PROMPT, "source": os.path.join(work, "source.png"),
        "width": 1024, "height": 672, "steps": 8, "guidance": 1.0,
        "jobs": [{"n": n, "seed": 100 + n, "output_path": os.path.join(work, "cand_%02d.pending.png" % n)}
                 for n in (1, 2, 3)]}
    assert [os.path.isfile(cand(run_dir, n)) for n in (1, 2, 3)] == [True, False, True]
    assert not os.path.exists(os.path.join(work, "cand_02.pending.png"))
    record = record_of(run_dir)
    assert statuses(run_dir) == ["ok", "blocked", "ok"]
    assert [c["seconds"] for c in record["candidates"]] == [1.0, 1.0, 1.0]
    assert (record["backend"], record["state"], record["strength"]) == ("mflux-q4", "done", None)
    assert env["calls"]["safety"] == [{"skill": "seed_edit", "prompt": PROMPT, "size": (1024, 672)}] * 3
    out = capsys.readouterr().out.splitlines()
    assert "seed-edit: backend mflux-q4 (diffusers bf16: Qwen/Qwen-Image-Edit-2511 is not in %s)" % env["hfhub"] in out
    assert plain([line for line in out if line.startswith("candidate ")]) == [
        "candidate 1/3 ok Ss", "candidate 2/3 blocked Ss", "candidate 3/3 ok Ss"]


# --- SGT10 (SG17, SG20): the mflux child fails or times out --------------------------------------------

def test_sgt10_the_mflux_child_fails_or_times_out(env, capsys):
    tool = env["tool"]
    py, _venv = mflux_venv(env)
    mflux_weights(env)
    stub_config(py, {"fail_after": 1})
    code, run_dir = run_tool(env, "--candidates", "3", "--seed", "100", model="qwen", run=R1)
    assert code == 1
    record = record_of(run_dir)
    assert statuses(run_dir) == ["ok", "failed", "failed"]
    assert (record["state"], record["error"]) == ("failed", "mflux q4 child exited 1: boom")
    assert os.path.isfile(cand(run_dir, 1))
    out = capsys.readouterr().out.splitlines()
    assert "boom" in out and out[-3:] == ["candidate 2/3 failed", "candidate 3/3 failed",
                                         "seed-edit: done: 1 ok, 0 blocked, 2 failed"]
    env["mp"].setattr(tool, "CHILD_TIMEOUT_S", 1)
    stub_config(py, {"sleep": 30})
    started = time.monotonic()
    code, run_dir = run_tool(env, "--candidates", "3", "--seed", "100", model="qwen", run=R2)
    assert code == 1 and time.monotonic() - started < 20
    record = record_of(run_dir)
    assert statuses(run_dir) == ["failed"] * 3
    assert record["error"] == "mflux q4 child timed out after %d s" % tool.CHILD_TIMEOUT_S
    assert tool.CHILD is None
    env["mp"].setattr(tool, "CHILD_TIMEOUT_S", 3600)
    stub_config(py, {"kill_after": 1})
    code, run_dir = run_tool(env, "--candidates", "3", "--seed", "100", model="qwen", run=R3)
    assert code == 1
    record = record_of(run_dir)
    assert statuses(run_dir) == ["ok", "failed", "failed"]
    assert (record["state"], record["error"]) == ("failed", "mflux q4 child exited -9: killed")
    assert tool.CHILD is None


# --- SGT11 (SG19, SG22): the diffusers bf16 child ------------------------------------------------------

def test_sgt11_the_bf16_child(env, capsys):
    tool = env["tool"]
    bf16_cache(env)
    env["mp"].setattr(tool, "avail_gib", lambda: 70.0)
    stub = qwenedit_stub(env, {"blocked": [2]})
    code, run_dir = run_tool(env, "--candidates", "2", "--seed", "100", model="qwen")
    assert code == 0
    work = os.path.join(run_dir, "work")
    calls = stub_calls(stub)
    assert len(calls) == 1
    assert calls[0]["argv"] == [sys.executable, stub, "qwenedit", "--spec", os.path.join(work, "qwenedit_spec.json")]
    assert calls[0]["env"] == {"PYTHONUNBUFFERED": "1"}
    assert calls[0]["spec"] == {
        "image": os.path.join(work, "source.png"), "model": "Qwen/Qwen-Image-Edit-2511",
        "lora_repo": "lightx2v/Qwen-Image-Edit-2511-Lightning",
        "lora_file": "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors", "steps": 8, "true_cfg": 1.0,
        "skill": "seed_edit",
        "jobs": [{"prompt": PROMPT, "output_path": os.path.join(work, "cand_%02d.part.png" % n), "seed": 100 + n,
                  "width": 1024, "height": 672} for n in (1, 2)],
        "report_path": os.path.join(work, "qwenedit_report.json")}
    assert statuses(run_dir) == ["ok", "blocked"]
    assert [os.path.isfile(cand(run_dir, n)) for n in (1, 2)] == [True, False]
    assert record_of(run_dir)["backend"] == "diffusers-bf16"
    assert "seed-edit: backend diffusers-bf16 (70.0 GiB available)" in capsys.readouterr().out.splitlines()
    assert env["calls"]["safety"] == []


# --- SGT12 (SG6, SG12): an interrupt -------------------------------------------------------------------

def test_sgt12_an_interrupt(env, capsys):
    zimage_cache(env)
    env["calls"]["plan"][102] = KeyboardInterrupt()
    code, run_dir = run_tool(env, "--candidates", "3", "--seed", "100")
    assert code == 130
    record = record_of(run_dir)
    assert (record["state"], record["error"]) == ("cancelled", "interrupted")
    assert statuses(run_dir) == ["ok", "failed", "failed"]
    assert capsys.readouterr().err == "seed-edit: interrupted\n"


# --- SGT13 (SG15): the probe ---------------------------------------------------------------------------

HEAVY = {"torch", "PIL", "psutil", "diffusers", "transformers", "z_image_skill", "content_safety",
         "character_dataset"}


def test_sgt13_the_probe(env, capsys):
    tool, mp = env["tool"], env["mp"]
    zimage_cache(env)
    mflux_venv(env)
    mflux_weights(env)
    assert tool.probe() == {"zimage": {"ok": True, "reason": None, "backend": "zimage"},
                            "qwen": {"ok": True, "reason": None, "backend": "mflux-q4"}}
    assert tool.main(["--probe"]) == 0
    assert capsys.readouterr().out == json.dumps(tool.probe(), sort_keys=True) + "\n"
    bf16_cache(env)
    mp.setattr(tool, "total_gib", lambda: 128.0)
    assert tool.probe()["qwen"] == {"ok": True, "reason": None, "backend": "diffusers-bf16"}
    missing = os.path.join(env["tmp"], "none", "bin", "python")
    mp.setenv("SEED_EDIT_MFLUX_PYTHON", missing)
    mp.setattr(tool, "total_gib", lambda: 48.0)
    assert tool.probe()["qwen"] == {
        "ok": False, "backend": None,
        "reason": "diffusers bf16: needs a host with at least 64 GiB of memory (this host has 48.0 GiB); mflux q4: "
                  "no mflux venv at %s (run bin/seed-edit-setup)" % missing}
    mp.setattr(tool, "total_gib", lambda: None)
    assert tool.probe()["qwen"]["reason"].startswith("diffusers bf16: cannot read this host's memory size; ")
    proc = subprocess.run([sys.executable, "-X", "importtime", TOOL_PATH, "--probe"], capture_output=True,
                          text=True, timeout=60, cwd=env["tmp"])
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert len(lines) == 1 and set(json.loads(lines[0])) == {"zimage", "qwen"}
    imported = set(line.rsplit("|", 1)[1].strip().split(".")[0] for line in proc.stderr.splitlines()
                   if line.startswith("import time:") and line.count("|") == 2)
    assert "movie_ui_lib" in imported
    assert not imported & HEAVY, sorted(imported & HEAVY)


# --- SGT14 (spec 1.1): the mirrored constants ----------------------------------------------------------

def test_sgt14_the_mirrored_constants():
    import character_dataset
    tool = load_tool()
    for name in ("EDIT_MODEL", "EDIT_LORA_REPO", "EDIT_LORA_FILE", "EDIT_STEPS", "EDIT_TRUE_CFG", "AVAIL_WAIT_S"):
        assert getattr(tool, name) == getattr(character_dataset, name), name
    assert tool.BF16_MIN_AVAIL_GIB == character_dataset.EDIT_MIN_AVAIL_GIB
    assert tool.ZIMAGE_MIN_AVAIL_GIB == character_dataset.GENERATE_MIN_AVAIL_GIB
    assert tool.MIN_FREE_GIB == character_dataset.CREATE_MIN_FREE_GIB


# --- SQT10 (seed models SQ3, SQ4, SQ6): the registry pins -------------------------------------------------

RESEARCH = "Qwen Research License (non-commercial)"
LIGHTNING_PIN = {"repo": "lightx2v/Qwen-Image-Edit-2511-Lightning", "revision": "107d238d68b8387e32843d0b4a2e24ceb0d3ad86",
                 "file": "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors", "bytes": 849608296,
                 "scale": 1.0}
MFLUX_PATTERNS = ["model_index.json", "scheduler/*.json", "processor/**", "vae/*.json", "vae/*.safetensors",
                  "transformer/*.json", "transformer/*.safetensors", "text_encoder/*.json", "text_encoder/*.safetensors"]
C21 = "mflux.models.qwen21.variants.edit.qwen_image_21_edit.QwenImage21Edit"
C2511 = "mflux.models.qwen.variants.edit.qwen_image_edit.QwenImageEdit"
REGISTRY = [
    {"id": "qwen21-q4", "label": "Qwen-Image-2.1 q4", "family": "qwen21", "backend": "mflux",
     "repo": "mflux-community/qwen-image-2-1-mflux-q4", "revision": "b6c0fc76350650482d13aea89b316c28cd487f7f",
     "allow_patterns": None, "bytes": 10638928735, "quant": "q4", "mflux_class": C21, "mflux_config": "qwen_image_21",
     "steps": 40, "guidance": 1.0, "scheduler": "linear", "multiple": 32, "builtin_lora": None, "memory_gib": 20.0,
     "license": RESEARCH, "setup": True},
    {"id": "qwen21-q8", "label": "Qwen-Image-2.1 q8", "family": "qwen21", "backend": "mflux",
     "repo": "mflux-community/qwen-image-2-1-mflux-q8", "revision": "f5c8cc79a6741026a6057546012fba3b0a4b5b25",
     "allow_patterns": None, "bytes": 18460986297, "quant": "q8", "mflux_class": C21, "mflux_config": "qwen_image_21",
     "steps": 40, "guidance": 1.0, "scheduler": "linear", "multiple": 32, "builtin_lora": None, "memory_gib": 32.0,
     "license": RESEARCH, "setup": True},
    {"id": "qwen21-bf16", "label": "Qwen-Image-2.1 bf16", "family": "qwen21", "backend": "mflux",
     "repo": "Qwen/Qwen-Image-2.1", "revision": "d26bb61231c349cf6b7896fa83353113880e1ba3",
     "allow_patterns": MFLUX_PATTERNS, "bytes": 33131601593, "quant": "bf16", "mflux_class": C21,
     "mflux_config": "qwen_image_21", "steps": 40, "guidance": 1.0, "scheduler": "linear", "multiple": 32,
     "builtin_lora": None, "memory_gib": 56.0, "license": RESEARCH, "setup": True},
    {"id": "qwen2511-q4", "label": "Qwen-Image-Edit-2511 q4 (Lightning)", "family": "qwen2511", "backend": "mflux",
     "repo": "mflux-community/qwen-image-edit-2511-mflux-q4", "revision": "3c74aab7dd79e6a8148c329cbca78c00c049ec3b",
     "allow_patterns": None, "bytes": 28958989673, "quant": "q4", "mflux_class": C2511,
     "mflux_config": "qwen_image_edit_2511", "steps": 8, "guidance": 1.0, "scheduler": None, "multiple": 16,
     "builtin_lora": LIGHTNING_PIN, "memory_gib": 32.0, "license": "Apache-2.0", "setup": True},
    {"id": "qwen2511-bf16", "label": "Qwen-Image-Edit-2511 bf16 (Lightning, diffusers)", "family": "qwen2511",
     "backend": "diffusers", "repo": "Qwen/Qwen-Image-Edit-2511", "revision": None, "allow_patterns": None,
     "bytes": None, "quant": "bf16", "mflux_class": None, "mflux_config": None, "steps": 8, "guidance": 1.0,
     "scheduler": None, "multiple": 16, "builtin_lora": dict(LIGHTNING_PIN, revision=None), "memory_gib": 64.0,
     "license": "Apache-2.0", "setup": False},
]
LORA_REGISTRY = [
    {"id": "uncensored", "label": "Uncensored (abenzerps)", "family": "qwen21",
     "repo": "abenzerps/Qwen-Image-2.1-Uncensored-Quantized", "revision": "7959e658915f52274897fb573ffeda49de8dc16b",
     "file": "qwen-image-2.1-uncensored-lora.safetensors", "bytes": 33586704, "default_on": True,
     "default_scale": 1.0, "steps": None, "scheduler": None, "license": RESEARCH},
    {"id": "viggle-turbo", "label": "Viggle turbo 6-step", "family": "qwen21",
     "repo": "Viggle/Qwen-Image-2.1-viggle-turbo", "revision": "009a44a895ef85f7e643c80fdca9543795248867",
     "file": "Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors", "bytes": 679604800,
     "default_on": False, "default_scale": 1.0, "steps": 6, "scheduler": "viggle_turbo", "license": RESEARCH},
]


def test_sqt10_the_registry_pins():
    import character_dataset
    tool = load_tool()
    assert seedgen.QWEN_MODEL_IDS == ("qwen21-q4", "qwen21-q8", "qwen21-bf16", "qwen2511-q4", "qwen2511-bf16")
    assert seedgen.QWEN_LORA_IDS == ("uncensored", "viggle-turbo")
    assert [dict(m) for m in seedgen.QWEN_MODELS] == REGISTRY
    assert [dict(lora) for lora in seedgen.QWEN_LORAS] == LORA_REGISTRY
    assert (seedgen.DEFAULT_QWEN_MODEL, seedgen.LEGACY_QWEN_MODEL, seedgen.SCALE_MAX) == ("qwen21-q4", "qwen2511-q4", 2.0)
    assert seedgen.QWEN_FAMILIES == {"qwen21": "Qwen-Image-2.1", "qwen2511": "Qwen-Image-Edit-2511"}
    assert seedgen.QWEN21_PATTERNS == MFLUX_PATTERNS
    assert seedgen.QWEN21_REQUIRED == ("vae/config.json", "transformer/config.json", "text_encoder/config.json")
    for entry in seedgen.QWEN_MODELS + seedgen.QWEN_LORAS:
        assert entry["revision"] is None or re.fullmatch(r"[0-9a-f]{40}", entry["revision"]), entry["id"]
    assert all("allow_patterns" not in lora for lora in seedgen.QWEN_LORAS)
    for model_id in ("qwen2511-q4", "qwen2511-bf16"):
        entry = seedgen.qwen_model(model_id)
        assert entry["steps"] == tool.EDIT_STEPS
        assert (entry["builtin_lora"]["repo"], entry["builtin_lora"]["file"]) == (tool.EDIT_LORA_REPO, tool.EDIT_LORA_FILE)
    assert seedgen.qwen_model("qwen2511-bf16")["repo"] == tool.EDIT_MODEL
    assert seedgen.qwen_model("qwen2511-bf16")["memory_gib"] == character_dataset.EDIT_MIN_AVAIL_GIB
    assert [seedgen.default_loras(m) for m in seedgen.QWEN_MODEL_IDS] == [[{"id": "uncensored", "scale": 1.0}]] * 3 + [[]] * 2
    assert (seedgen.qwen_model("nope"), seedgen.qwen_lora("nope")) == (None, None)
    assert seedgen.registry_order([{"id": "viggle-turbo", "scale": 1}, {"id": "uncensored", "scale": 2}]) == [
        {"id": "uncensored", "scale": 2}, {"id": "viggle-turbo", "scale": 1}]


# --- Review Focus 3: prompts that look like shell or argparse input --------------------------------------

ODD_PROMPTS = ['say "hi" and \'bye\'', "line one\nline two\n\ttabbed", "$(rm -rf ~) `id` ; | & > < *",
               "make it night --model qwen --strength 0.9", "a=b --c=d -e", "emoji \U0001F3AC and ünïcödé",
               "x" * 1999 + "!"]


def test_sg_review_focus_3_prompts_survive_the_argv_round_trip(env):
    tool = env["tool"]
    zimage_cache(env)
    ws = os.path.join(env["tmp"], "ws")
    for i, text in enumerate(ODD_PROMPTS):
        run = "se-20261102-141500-%04x" % i
        run_dir = os.path.join(ws, "generated", "seeds", "runs", run)
        png(os.path.join(run_dir, "source.png"), (128, 96))
        assert seedgen.validate_run_request({"prompt": text, "model": "zimage", "source": {"upload_id": UP}})[1] is None
        fields = {"ws": ws, "run": run, "source_file": "source.png", "prompt": text, "model": "zimage",
                  "strength": 0.45, "candidates": 1, "seed": 5, "source": None}
        argv = lib.seed_edit_argv(fields, ws)
        assert argv[argv.index("--prompt") + 1] == text
        assert tool.main(argv[2:]) == 0, text
        assert record_of(run_dir)["prompt"] == text
        assert env["calls"]["zimage"][-1]["prompt"] == text


# --- Review Focus 4: progress bars in the children's lines ---------------------------------------------

def test_sg_review_focus_4_progress_bars_in_child_lines(env, capsys):
    tool = env["tool"]
    py, _venv = mflux_venv(env)
    mflux_weights(env)
    bar = "  0%|          | 0/8 [00:00<?, ?it/s]\r100%|##########| 8/8 [00:01<00:00]\r"
    stub_config(py, {"prefix": bar})
    code, run_dir = run_tool(env, "--candidates", "2", "--seed", "1", model="qwen", run=R1)
    assert code == 0 and statuses(run_dir) == ["ok", "ok"]
    assert "100%|##########| 8/8 [00:01<00:00]\nseed-edit-child done 1 1.0\n" in capsys.readouterr().out
    bf16_cache(env)
    env["mp"].setattr(tool, "avail_gib", lambda: 70.0)
    qwenedit_stub(env, {"prefix": "Loading pipeline components...: 100%|##########| 5/5\r"})
    code, run_dir = run_tool(env, "--candidates", "2", "--seed", "1", model="qwen", run=R2)
    assert code == 0 and statuses(run_dir) == ["ok", "ok"]
    assert record_of(run_dir)["backend"] == "diffusers-bf16"


# --- SGT15 (SG24, SG25, SG27): the mflux child ---------------------------------------------------------

def test_sgt15_the_mflux_child(monkeypatch, tmp_path, capsys):
    import seed_edit_mflux_child as child
    with open(os.path.join(WS, "seed_edit_mflux_child.py"), encoding="utf-8") as f:
        source = f.read()
    assert re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M) == [
        "argparse", "importlib.metadata", "json", "os", "re", "sys", "threading", "time"]
    for text, want in (("0.24.0", (0, 24, 0)), ("0.22.0", (0, 22, 0)), ("0.21.9", (0, 21, 9)), ("x", None),
                       (None, None)):
        assert child.parse_version(text) == want, text
    assert child.parse_version("0.21.9") < child.MIN_VERSION <= child.parse_version("0.22.0")
    monkeypatch.setattr(child, "exit_with_parent", lambda poll_s=2.0: None)
    monkeypatch.setattr(child.importlib.metadata, "version", lambda name: "0.21.0")
    missing = os.path.join(str(tmp_path), "missing-spec.json")
    assert child.main(["--spec", missing]) == 2
    assert capsys.readouterr().out == ("seed-edit-child: mflux 0.21.0 is missing or older than 0.22.0; refusing "
                                       "(it would run Qwen-Image-Edit-2509)\n")

    def not_installed(name):
        raise child.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(child.importlib.metadata, "version", not_installed)
    assert child.main(["--spec", missing]) == 2
    assert capsys.readouterr().out.startswith("seed-edit-child: mflux None is missing or older than 0.22.0")
    for text in ('guidance=spec["guidance"]', "bake_lora=False", 'negative_prompt=" "',
                 "ModelConfig.qwen_image_edit_2511()", "quantize=None", "lora_scales=[1.0]"):
        assert text in source, text


# --- SGT16 (SG66-SG69): bin/seed-edit-setup is read, never run ------------------------------------------

def _code_of(source, name):
    """The text of function name in source, without its docstring."""
    start = source.index("\ndef %s(" % name)
    text = source[start:source.index("\n\n\n", start)]
    doc = text.index('"""')
    return text[:doc] + text[text.index('"""', doc + 3) + 3:]


def test_sgt16_the_setup_script_is_read_never_run():
    with open(os.path.join(WS, "bin", "seed-edit-setup"), encoding="utf-8") as f:
        source = f.read()
    with open(TOOL_PATH, encoding="utf-8") as f:
        tool_source = f.read()
    assert source.startswith("#!/usr/bin/env python3\n")
    for text in ('"mflux==0.24.0"', "SETUP_MIN_FREE_GIB = 31.0", "HF_XET_CHUNK_CACHE_SIZE_BYTES", "cache_dir=hub",
                 'VENV = "~/mflux-edit/.venv"',
                 'DEFAULT_BASE_PYTHON = "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13"'):
        assert text in source, text
    assert "HF_TOKEN" not in source
    tool = load_tool()
    for name in ("Q4_REPO", "EDIT_LORA_REPO", "EDIT_LORA_FILE"):
        assert '%s = "%s"' % (name, getattr(tool, name)) in source, name
    for name in ("mflux_version", "find_lightning"):
        assert _code_of(source, name) == _code_of(tool_source, name), name


def test_sg_final_setup_resume_counts_what_is_present(env):
    """Final review F1: a resumed download is not refused for space it already used. bin/seed-edit-setup is
    loaded as a module (its main is never called; its top level only imports and assigns)."""
    path = os.path.join(WS, "bin", "seed-edit-setup")
    loader = importlib.machinery.SourceFileLoader("seed_edit_setup", path)
    spec = importlib.util.spec_from_loader("seed_edit_setup", loader)
    setup = importlib.util.module_from_spec(spec)
    loader.exec_module(setup)
    hub, venv = os.path.join(env["tmp"], "hub"), os.path.join(env["tmp"], "venv")
    assert setup.present_gib(hub, venv) == 0.0
    blobs = os.path.join(hub, lib.repo_dir_name(setup.Q4_REPO), "blobs")
    snap = os.path.join(hub, lib.repo_dir_name(setup.Q4_REPO), "snapshots", "abc")
    os.makedirs(blobs)
    os.makedirs(snap)
    with open(os.path.join(blobs, "abc.incomplete"), "wb") as f:
        f.truncate(3 * 2 ** 20)
    os.symlink(os.path.join(blobs, "abc.incomplete"), os.path.join(snap, "model.safetensors"))
    os.makedirs(os.path.join(venv, "bin"))
    with open(os.path.join(venv, "bin", "python"), "wb") as f:
        f.truncate(2 ** 20)
    got = setup.present_gib(hub, venv)
    assert 4 / 1024 <= got < 4 / 1024 + 0.001, got
    with open(path, encoding="utf-8") as f:
        source = f.read()
    assert 'HF_HUB_ENABLE_HF_TRANSFER="0"' in source and "already present" in source


def test_sg_final_a_phone_hdr_jpeg_is_a_jpeg(env):
    """Final review F3: an iOS/Android HDR JPEG carries an MPF secondary image, which Pillow names MPO."""
    zimage_cache(env)
    mpo = os.path.join(env["tmp"], "hdr-phone.jpg")
    Image.new("RGB", (300, 200), (0, 120, 200)).save(mpo, "MPO", save_all=True,
                                                     append_images=[Image.new("RGB", (75, 50))])
    with Image.open(mpo) as img:
        assert img.format == "MPO"
    code, run_dir = run_tool(env, "--candidates", "1", source=mpo, run=R1)
    assert code == 0
    record = record_of(run_dir)
    assert (record["source"], record["source_size"], record["size"]) == (
        "source.jpg", {"width": 300, "height": 200}, {"width": 288, "height": 192})
    with open(mpo, "rb") as f, open(os.path.join(run_dir, "source.jpg"), "rb") as g:
        assert f.read() == g.read()
