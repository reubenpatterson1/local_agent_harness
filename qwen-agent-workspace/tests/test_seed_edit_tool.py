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
- qe.avail_gib, qe.total_gib, qe.missing_modules, tool.cpu_generator and tool.disk_free_gib
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
    qe = tool.qe
    gens = []
    monkeypatch.setattr(qe, "avail_gib", lambda: 40.0)
    monkeypatch.setattr(qe, "total_gib", lambda: 48.0)
    monkeypatch.setattr(qe, "missing_modules", lambda names: [])
    monkeypatch.setattr(tool, "disk_free_gib", lambda path: 100.0)
    monkeypatch.setattr(tool, "cpu_generator", lambda seed: gens.append(seed) or seed)
    return {"tmp": tmp, "tool": tool, "qe": qe, "gens": gens, "calls": make_fakes(monkeypatch), "mp": monkeypatch,
            "zhub": os.path.join(tmp, "zi", "hub"), "hfhub": os.path.join(tmp, "hf", "hub")}


def zimage_cache(env):
    for repo in (lib.STILLS_BASE_MODEL, lib.ZIMAGE_TEXT_ENCODER):
        mt.make_hf_cache(os.path.join(env["tmp"], "zi"), repo, {"x.safetensors": b"\x01" * 8})


def bf16_cache(env):
    root, qe = os.path.join(env["tmp"], "hf"), env["qe"]
    mt.make_hf_cache(root, qe.EDIT_MODEL, {"transformer/x.safetensors": b"\x01" * 8})
    mt.make_hf_cache(root, qe.EDIT_LORA_REPO, {qe.EDIT_LORA_FILE: b"\x01" * 8})


def pinned_cache(root, repo, revision, files):
    """Seed models spec 9.1: mt.make_hf_cache without refs/main, its snapshot renamed to revision (the
    blob links are relative, so they keep working); returns the snapshot path."""
    repo_dir = mt.make_hf_cache(root, repo, files, refs=False)
    snapshot = os.path.join(repo_dir, "snapshots", revision)
    os.rename(os.path.join(repo_dir, "snapshots", REV), snapshot)
    return snapshot


QWEN21_FILES = {"vae/config.json": b"{}", "transformer/config.json": b"{}", "text_encoder/config.json": b"{}",
                "processor/tokenizer.json": b"{}", "transformer/0.safetensors": b"\x01" * 8}


def install_model(env, model_id, root="zi", files=None):
    """Registry model model_id's pinned snapshot under <tmp>/<root>/hub (zi: the Z-Image hub, hf: the
    default hub), plus its pinned built-in Lightning file; returns (snapshot, Lightning path or None)."""
    entry = seedgen.qwen_model(model_id)
    base = os.path.join(env["tmp"], root)
    if files is None:
        files = QWEN21_FILES if entry["family"] == "qwen21" else {"transformer/0.safetensors": b"\x01" * 8}
    snapshot = pinned_cache(base, entry["repo"], entry["revision"], files)
    lora = entry["builtin_lora"]
    if lora is None:
        return snapshot, None
    lightning = pinned_cache(base, lora["repo"], lora["revision"], {lora["file"]: b"\x01" * 8})
    return snapshot, os.path.join(lightning, lora["file"])


def install_lora(env, lora_id, root="zi"):
    """Registry LoRA lora_id's pinned file under <tmp>/<root>/hub; returns its snapshot path."""
    lora = seedgen.qwen_lora(lora_id)
    snapshot = pinned_cache(os.path.join(env["tmp"], root), lora["repo"], lora["revision"],
                            {lora["file"]: b"\x01" * 8})
    return os.path.join(snapshot, lora["file"])


def mflux_weights(env):
    """The pinned qwen2511-q4 snapshot and its pinned Lightning file in the Z-Image hub; returns
    (snapshot, Lightning path)."""
    return install_model(env, "qwen2511-q4")


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
    if job["n"] not in config.get("silent", []):
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
        "qwen_model": None, "loras": [], "steps": None, "scheduler": None,
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
    mp.setattr(env["qe"], "missing_modules", lambda names: ["torch"])
    code, run_dir = run_tool(env, run=R3)
    assert code == 2
    _refused(run_dir, "Z-Image is unavailable: torch not importable by %s" % sys.executable, capsys.readouterr())
    mp.setattr(env["qe"], "missing_modules", lambda names: [])
    mp.setattr(env["qe"], "avail_gib", lambda: 10.0)
    mp.setattr(env["qe"], "AVAIL_WAIT_S", 0)
    code, run_dir = run_tool(env, run=R4)
    assert code == 2
    captured = capsys.readouterr()
    assert "seed-edit: waiting up to 0 s for 20 GiB available (now 10.0 GiB)\n" in captured.out
    _refused(run_dir, "only 10.0 GiB available after waiting 0 s; Z-Image needs 20 GiB; free memory and retry",
             captured)
    py, _venv = mflux_venv(env)
    mflux_weights(env)
    code, run_dir = run_tool(env, "--qwen-model", "qwen2511-q4", run=R5, model="qwen")
    assert code == 2
    _refused(run_dir, "only 10.0 GiB available after waiting 0 s; Qwen-Image-Edit-2511 q4 (Lightning) needs 32 GiB; "
                      "free memory and retry", capsys.readouterr())
    assert calls["zimage"] == [] and stub_calls(py) == []
    assert record_of(run_dir)["size"] == {"width": 1024, "height": 672}


# --- SQT1 (seed models SQ14): the canvas floors to 32 for Qwen-Image-2.1 ---------------------------------

CANVAS_32 = [((1536, 1024), (1024, 672)), ((1024, 1024), (1024, 1024)), ((800, 600), (800, 576)),
             ((4000, 3000), (1024, 768)), ((3000, 4000), (768, 1024)), ((720, 1280), (576, 1024)),
             ((1023, 1023), (992, 992)), ((100, 70), (96, 64)), ((90, 90), (64, 64))]


def test_sqt1_the_canvas_for_qwen21(env):
    tool = env["tool"]
    for (w0, h0), want in CANVAS_32:
        assert tool.canvas(w0, h0, 32) == want, (w0, h0)
    with pytest.raises(tool.Refusal) as info:
        tool.canvas(100, 60, 32)
    assert str(info.value) == "--source is too small: 100x60 gives a 96x32 canvas; each side must be at least 64 px"
    for (w0, h0), want in CANVAS:
        assert tool.canvas(w0, h0) == tool.canvas(w0, h0, 16) == want, (w0, h0)


# --- SQT2 (seed models SQ12): --qwen-model and --lora ------------------------------------------------------

QBASE = ["--source", "SRC", "--prompt", PROMPT, "--model", "qwen", "--run-dir", "RUNDIR"]
Q21 = QBASE + ["--qwen-model", "qwen21-q4"]
SCALE_TEXT = "--lora uncensored scale must be a number above 0 and at most 2"
QARG_CASES = [
    (["--probe", "--lora", "uncensored=1"], "--probe takes no other options"),
    (["--probe", "--qwen-model", "qwen21-q4"], "--probe takes no other options"),
    (BASE + ["--qwen-model", "qwen21-q4"], "--qwen-model is only for --model qwen"),
    (BASE + ["--qwen-model", "x", "--lora", "y"], "--qwen-model is only for --model qwen"),
    (BASE + ["--lora", "uncensored=1"], "--lora is only for --model qwen"),
    (QBASE + ["--qwen-model", "flux"],
     "--qwen-model must be one of qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-q4, qwen2511-bf16"),
    (QBASE + ["--candidates", "0", "--qwen-model", "flux"], "--candidates must be an integer from 1 to 4"),
    (QBASE + ["--qwen-model", "flux", "--seed", "-1"],
     "--qwen-model must be one of qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-q4, qwen2511-bf16"),
    (Q21 + ["--lora", "uncensored"], "--lora must be ID=SCALE (got uncensored)"),
    (Q21 + ["--lora", "=1"], "--lora must be ID=SCALE (got =1)"),
    (Q21 + ["--lora", "Uncensored=1"], "--lora must be ID=SCALE (got Uncensored=1)"),
    (Q21 + ["--lora", "nope=1"], "--lora: unknown LoRA nope; known: uncensored, viggle-turbo"),
    (Q21 + ["--lora", "nope=1", "--lora", "x"], "--lora: unknown LoRA nope; known: uncensored, viggle-turbo"),
    (Q21 + ["--lora", "uncensored=1", "--lora", "uncensored=0.5"], "--lora uncensored is given twice"),
    (QBASE + ["--qwen-model", "qwen2511-q4", "--lora", "uncensored=1"],
     "--lora uncensored is for Qwen-Image-2.1, not Qwen-Image-Edit-2511 q4 (Lightning)"),
    (QBASE + ["--lora", "uncensored=1"],
     "--lora uncensored is for Qwen-Image-2.1, not Qwen-Image-Edit-2511 q4 (Lightning)"),
    (Q21 + ["--lora", "uncensored=0"], SCALE_TEXT),
    (Q21 + ["--lora", "uncensored=-1"], SCALE_TEXT),
    (Q21 + ["--lora", "uncensored=2.5"], SCALE_TEXT),
    (Q21 + ["--lora", "uncensored=x"], SCALE_TEXT),
    (Q21 + ["--lora", "uncensored=nan"], SCALE_TEXT),
    (Q21 + ["--lora", "uncensored=inf"], SCALE_TEXT),
    (Q21 + ["--lora", "uncensored=1", "--seed", "-1"], "--seed must be an integer from 0 to 2147483647"),
]


@pytest.mark.parametrize("argv,message", QARG_CASES, ids=["case%d" % (i + 1) for i in range(len(QARG_CASES))])
def test_sqt2_bad_qwen_arguments(env, capsys, argv, message):
    source = png(os.path.join(env["tmp"], "src.png"), (128, 128))
    run_dir = os.path.join(env["tmp"], "runs", RUN)
    argv = [source if a == "SRC" else run_dir if a == "RUNDIR" else a for a in argv]
    assert env["tool"].main(argv) == 2
    assert capsys.readouterr() == ("", "Error: %s\n" % message)
    assert not os.path.exists(run_dir)


def test_sqt2_the_cleaned_qwen_options(env):
    tool = env["tool"]

    def opts(*extra, model="qwen"):
        return tool.check_args(tool.parse(["--source", "s", "--prompt", PROMPT, "--model", model, "--run-dir", "r",
                                           "--seed", "1"] + list(extra)))

    got = opts()
    assert (got["qwen_model"], got["loras"]) == ("qwen2511-q4", [])
    got = opts("--qwen-model", "qwen21-q4", "--lora", "viggle-turbo=0.5", "--lora", "uncensored=1")
    assert (got["qwen_model"], got["loras"]) == ("qwen21-q4", [{"id": "uncensored", "scale": 1.0},
                                                              {"id": "viggle-turbo", "scale": 0.5}])
    assert opts("--qwen-model", "qwen21-q8", "--lora", "uncensored=2")["loras"] == [{"id": "uncensored", "scale": 2.0}]
    assert opts("--qwen-model", "qwen21-q4")["loras"] == []
    got = opts(model="zimage")
    assert (got["qwen_model"], got["loras"]) == (None, [])


# --- SQT3 (seed models SQ15-SQ17): the pinned registry lookups --------------------------------------------

def test_sqt3_the_pinned_lookups(env):
    qe, mp, zhub, hfhub = env["qe"], env["mp"], env["zhub"], env["hfhub"]
    hubs, where = [zhub, hfhub], "%s or %s" % (zhub, hfhub)
    q8 = seedgen.qwen_model("qwen21-q8")
    absent = ("mflux-community/qwen-image-2-1-mflux-q8@f5c8cc79a674 is not in %s "
              "(run bin/seed-edit-setup --model qwen21-q8)" % where)
    assert qe.weights_problem(q8, hubs) == (absent, None, None)
    mt.make_hf_cache(os.path.join(env["tmp"], "hf"), q8["repo"], QWEN21_FILES)
    assert qe.weights_problem(q8, hubs) == (absent, None, None)
    q8_snapshot, _none = install_model(env, "qwen21-q8")
    assert qe.weights_problem(q8, hubs) == (None, q8_snapshot, None)
    q4 = seedgen.qwen_model("qwen21-q4")
    snapshot, _none = install_model(env, "qwen21-q4")
    with open(os.path.join(os.path.dirname(os.path.dirname(snapshot)), "blobs", "partial0.incomplete"), "wb") as f:
        f.write(b"x")
    assert qe.weights_problem(q4, hubs) == (
        "mflux-community/qwen-image-2-1-mflux-q4: download incomplete: 1 partial blob(s) "
        "(run bin/seed-edit-setup --model qwen21-q4)", None, None)
    bf16 = seedgen.qwen_model("qwen21-bf16")
    files = dict(QWEN21_FILES)
    del files["vae/config.json"], files["processor/tokenizer.json"]
    install_model(env, "qwen21-bf16", files=files)
    assert qe.weights_problem(bf16, hubs) == (
        "Qwen/Qwen-Image-2.1: missing vae/config.json; missing processor/ (run bin/seed-edit-setup --model qwen21-bf16)",
        None, None)
    e2511 = seedgen.qwen_model("qwen2511-q4")
    only = pinned_cache(os.path.join(env["tmp"], "hf"), e2511["repo"], e2511["revision"],
                        {"transformer/0.safetensors": b"\x01" * 8})
    mt.make_hf_cache(os.path.join(env["tmp"], "zi"), qe.EDIT_LORA_REPO, {qe.EDIT_LORA_FILE: b"\x01" * 8})
    assert qe.weights_problem(e2511, hubs) == (
        "Lightning LoRA Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors is not in %s "
        "(run bin/seed-edit-setup --model qwen2511-q4)" % where, None, None)
    lightning = os.path.join(pinned_cache(os.path.join(env["tmp"], "hf"), qe.EDIT_LORA_REPO,
                                          e2511["builtin_lora"]["revision"], {qe.EDIT_LORA_FILE: b"\x01" * 8}),
                             qe.EDIT_LORA_FILE)
    assert qe.weights_problem(e2511, hubs) == (None, only, lightning)
    unc = seedgen.qwen_lora("uncensored")
    missing = ("qwen-image-2.1-uncensored-lora.safetensors is not in %s (run bin/seed-edit-setup --lora uncensored)"
               % where)
    assert qe.lora_problem(unc, hubs) == (missing, None)
    pinned_cache(os.path.join(env["tmp"], "zi"), unc["repo"], unc["revision"], {unc["file"]: b""})
    assert qe.lora_problem(unc, hubs) == (missing, None)
    found = install_lora(env, "uncensored", root="hf")
    assert qe.lora_problem(unc, hubs) == (None, found)
    py = os.path.join(env["tmp"], "mflux-edit", ".venv", "bin", "python")
    venv = os.path.dirname(os.path.dirname(py))
    mp.setenv("SEED_EDIT_MFLUX_PYTHON", py)
    hint = "(run bin/seed-edit-setup --model qwen21-q8)"
    assert qe.mflux_env_problem(q8) == "no mflux venv at %s %s" % (py, hint)
    mflux_venv(env, version=None)
    assert qe.mflux_env_problem(q8) == "mflux is not installed in %s %s" % (venv, hint)
    set_mflux_version(venv, "banana")
    assert qe.mflux_env_problem(q8) == "cannot read the mflux version in %s" % venv
    set_mflux_version(venv, "0.23.9")
    assert qe.mflux_env_problem(q8) == "mflux 0.23.9 in %s is older than 0.24.0 %s" % (venv, hint)
    assert qe.mflux_env_problem(q4) == ("mflux 0.23.9 in %s is older than 0.24.0 "
                                        "(run bin/seed-edit-setup --model qwen21-q4)" % venv)
    for version in ("0.24.0", "0.25.1"):
        set_mflux_version(venv, version)
        assert qe.mflux_env_problem(q8) is None
    assert qe.qwen_model_problem(q8) == (None, {"model_path": q8_snapshot, "builtin_lora": None})
    mp.setattr(qe, "missing_modules", lambda names: ["torch"])
    assert qe.qwen_model_problem(q8) == ("torch not importable by %s" % sys.executable, {})
    assert qe.qwen_hubs() == [zhub, hfhub]
    assert qe.MFLUX_MIN_VERSION == (0, 24, 0)
    with open(TOOL_PATH, encoding="utf-8") as f:
        source = f.read()
    for gone in ("SEED_EDIT_QWEN_Q4_DIR", "SEED_EDIT_LIGHTNING_FILE", "def choose_qwen(", "def mflux_problem(",
                 "BF16_MIN_AVAIL_GIB", "MFLUX_MIN_AVAIL_GIB", "Q4_REPO", "Q4_NAME_PART"):
        assert gone not in source, gone
    environ_re = r"os\.environ(?:\.get\(|\[)\"([A-Z0-9_]+)\""
    assert re.findall(environ_re, source) == []
    with open(os.path.join(WS, "qwen_edit.py"), encoding="utf-8") as f:
        assert set(re.findall(environ_re, f.read())) == {
            "SEED_EDIT_MFLUX_PYTHON", "SEED_EDIT_QWENEDIT_SCRIPT", "HF_HUB_CACHE", "HF_HOME"}


# --- SQT4 (seed models SQ18): the probe's new shape ---------------------------------------------------------

def test_sqt4_the_probe(env, capsys):
    tool, mp, zhub, hfhub = env["tool"], env["mp"], env["zhub"], env["hfhub"]
    where = "%s or %s" % (zhub, hfhub)
    zimage_cache(env)
    mflux_venv(env)

    def absent(model_id, revision):
        return "%s@%s is not in %s (run bin/seed-edit-setup --model %s)" % (
            seedgen.qwen_model(model_id)["repo"], revision, where, model_id)

    mem = "needs a host with at least %d GiB of memory (this host has 48.0 GiB)"
    nothing = {"qwen21-q4": absent("qwen21-q4", "b6c0fc763506"), "qwen21-q8": absent("qwen21-q8", "f5c8cc79a674"),
               "qwen21-bf16": mem % 56, "qwen2511-q4": absent("qwen2511-q4", "3c74aab7dd79"),
               "qwen2511-bf16": mem % 64}
    viggle = ("Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors is not in %s "
              "(run bin/seed-edit-setup --lora viggle-turbo)" % where)
    uncensored = ("qwen-image-2.1-uncensored-lora.safetensors is not in %s (run bin/seed-edit-setup --lora uncensored)"
                  % where)
    got = tool.probe()["qwen"]
    assert got == {"ok": False, "reason": "; ".join("%s: %s" % (i, nothing[i]) for i in seedgen.QWEN_MODEL_IDS),
                   "models": dict((i, {"ok": False, "reason": nothing[i]}) for i in seedgen.QWEN_MODEL_IDS),
                   "loras": {"uncensored": {"ok": False, "reason": uncensored},
                             "viggle-turbo": {"ok": False, "reason": viggle}}}
    install_model(env, "qwen21-q4")
    install_lora(env, "uncensored")
    models = dict((i, {"ok": False, "reason": nothing[i]}) for i in seedgen.QWEN_MODEL_IDS)
    models["qwen21-q4"] = {"ok": True, "reason": None}
    assert tool.probe() == {"zimage": {"ok": True, "reason": None, "backend": "zimage"},
                            "qwen": {"ok": True, "reason": None, "models": models,
                                     "loras": {"uncensored": {"ok": True, "reason": None},
                                               "viggle-turbo": {"ok": False, "reason": viggle}}}}
    assert tool.main(["--probe"]) == 0
    assert capsys.readouterr().out == json.dumps(tool.probe(), sort_keys=True) + "\n"
    install_model(env, "qwen21-bf16")
    mp.setattr(env["qe"], "total_gib", lambda: 128.0)
    got = tool.probe()["qwen"]
    assert got["models"]["qwen21-bf16"] == {"ok": True, "reason": None}
    assert "backend" not in got and set(got) == {"ok", "reason", "models", "loras"}
    mp.setattr(env["qe"], "total_gib", lambda: None)
    assert set(e["reason"] for e in tool.probe()["qwen"]["models"].values()) == {"cannot read this host's memory size"}


# --- SQT5 (seed models SQ7, SQ19-SQ23): every mflux selection's child spec, record and backend line ---------

SQT5_CASES = [
    ("qwen21-q4", ["uncensored=1.0"], ["uncensored"], [1.0], 40, "linear",
     "Qwen-Image-2.1 q4; LoRAs uncensored@1; 40 steps; scheduler linear"),
    ("qwen21-q4", ["viggle-turbo=1.0", "uncensored=0.5"], ["uncensored", "viggle-turbo"], [0.5, 1.0], 6,
     "viggle_turbo", "Qwen-Image-2.1 q4; LoRAs uncensored@0.5, viggle-turbo@1; 6 steps; scheduler viggle_turbo"),
    ("qwen21-q8", [], [], [], 40, "linear", "Qwen-Image-2.1 q8; LoRAs none; 40 steps; scheduler linear"),
    ("qwen21-bf16", ["uncensored=1.0"], ["uncensored"], [1.0], 40, "linear",
     "Qwen-Image-2.1 bf16; LoRAs uncensored@1; 40 steps; scheduler linear"),
    ("qwen2511-q4", [], ["lightning"], [1.0], 8, None,
     "Qwen-Image-Edit-2511 q4 (Lightning); LoRAs none; 8 steps; scheduler default"),
]


@pytest.mark.parametrize("model_id,loras,paths,scales,steps,scheduler,why", SQT5_CASES,
                         ids=["case%d" % (i + 1) for i in range(len(SQT5_CASES))])
def test_sqt5_the_mflux_selection(env, capsys, model_id, loras, paths, scales, steps, scheduler, why):
    env["mp"].setattr(env["qe"], "avail_gib", lambda: 128.0)
    py, _venv = mflux_venv(env)
    snapshot, lightning = install_model(env, model_id)
    found = {"lightning": lightning}
    for lora_id in ("uncensored", "viggle-turbo"):
        found[lora_id] = install_lora(env, lora_id)
    extra = ["--qwen-model", model_id, "--candidates", "2", "--seed", "100"]
    for value in loras:
        extra += ["--lora", value]
    code, run_dir = run_tool(env, *extra, model="qwen")
    assert code == 0
    work = os.path.join(run_dir, "work")
    calls = stub_calls(py)
    assert len(calls) == 1
    assert calls[0]["argv"] == [py, os.path.join(WS, "seed_edit_mflux_child.py"), "--spec",
                                os.path.join(work, "mflux_spec.json")]
    assert calls[0]["env"]["HF_HUB_OFFLINE"] == "1"
    entry = seedgen.qwen_model(model_id)
    assert calls[0]["spec"] == {
        "family": entry["family"], "model_path": snapshot, "lora_paths": [found[p] for p in paths],
        "lora_scales": scales, "width": 1024, "height": 672, "steps": steps, "guidance": 1.0,
        "scheduler": scheduler,
        "jobs": [{"n": n, "seed": 100 + n, "prompt": PROMPT, "source": os.path.join(work, "source.png"),
                  "output_path": os.path.join(work, "cand_%02d.pending.png" % n)} for n in (1, 2)]}
    assert all(p.startswith(env["zhub"]) and os.path.realpath(p) != p for p in calls[0]["spec"]["lora_paths"])
    record = record_of(run_dir)
    chosen = [{"id": v.split("=")[0], "scale": float(v.split("=")[1])} for v in loras]
    assert (record["backend"], record["state"]) == ("mflux", "done")
    assert {k: record[k] for k in ("qwen_model", "loras", "steps", "scheduler")} == seedgen.qwen_settings(
        model_id, chosen)
    assert (record["steps"], record["scheduler"]) == (steps, scheduler)
    assert "seed-edit: backend mflux (%s)" % why in capsys.readouterr().out.splitlines()


# --- SQT6 (seed models SQ24): content safety screens every candidate of every registry model --------------

def test_sqt6_content_safety_on_every_candidate_of_every_model(env, capsys):
    calls = env["calls"]
    env["mp"].setattr(env["qe"], "avail_gib", lambda: 70.0)
    py, _venv = mflux_venv(env)
    for model_id in ("qwen21-q4", "qwen21-q8", "qwen21-bf16", "qwen2511-q4"):
        install_model(env, model_id)
    for lora_id in ("uncensored", "viggle-turbo"):
        install_lora(env, lora_id)
    stub_config(py, {"red": [2]})
    cases = [("qwen2511-q4", [])]
    for model_id in ("qwen21-q4", "qwen21-q8", "qwen21-bf16"):
        cases += [(model_id, []), (model_id, ["uncensored=1"]), (model_id, ["viggle-turbo=1"]),
                  (model_id, ["uncensored=0.5", "viggle-turbo=1"])]
    for i, (model_id, loras) in enumerate(cases):
        calls["safety"] = []
        extra = ["--qwen-model", model_id, "--candidates", "3", "--seed", "100"]
        for value in loras:
            extra += ["--lora", value]
        code, run_dir = run_tool(env, *extra, model="qwen", run="se-20261102-141500-%04x" % i)
        assert code == 0, (model_id, loras)
        assert calls["safety"] == [{"skill": "seed_edit", "prompt": PROMPT, "size": (1024, 672)}] * 3, (model_id, loras)
        assert statuses(run_dir) == ["ok", "blocked", "ok"], (model_id, loras)
        assert [os.path.isfile(cand(run_dir, n)) for n in (1, 2, 3)] == [True, False, True], (model_id, loras)
        assert not os.path.exists(os.path.join(run_dir, "work", "cand_02.pending.png"))
    assert len(stub_calls(py)) == len(cases)
    bf16_cache(env)
    stub = qwenedit_stub(env, {"blocked": [2]})
    calls["safety"] = []
    code, run_dir = run_tool(env, "--qwen-model", "qwen2511-bf16", "--candidates", "3", "--seed", "100", model="qwen",
                             run="se-20261102-141500-ffff")
    assert code == 0
    work = os.path.join(run_dir, "work")
    spec = stub_calls(stub)[0]["spec"]
    assert spec == {
        "image": os.path.join(work, "source.png"), "model": "Qwen/Qwen-Image-Edit-2511",
        "lora_repo": "lightx2v/Qwen-Image-Edit-2511-Lightning",
        "lora_file": "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors", "steps": 8, "true_cfg": 1.0,
        "skill": "seed_edit",
        "jobs": [{"prompt": PROMPT, "output_path": os.path.join(work, "cand_%02d.part.png" % n), "seed": 100 + n,
                  "width": 1024, "height": 672} for n in (1, 2, 3)],
        "report_path": os.path.join(work, "qwenedit_report.json")}
    assert statuses(run_dir) == ["ok", "blocked", "ok"]
    assert [os.path.isfile(cand(run_dir, n)) for n in (1, 2, 3)] == [True, False, True]
    assert calls["safety"] == []


# --- SQT7 (seed models SQ13, SQ21): run-time refusals and the child failure text ----------------------------

def test_sqt7_run_time_refusals(env, capsys):
    qe, mp, zhub, hfhub = env["qe"], env["mp"], env["zhub"], env["hfhub"]
    where = "%s or %s" % (zhub, hfhub)
    py, venv = mflux_venv(env)
    install_model(env, "qwen21-q4")
    install_lora(env, "uncensored")
    cases = [
        (["--qwen-model", "qwen21-q8"], "Qwen-Image-2.1 q8 is unavailable: mflux-community/qwen-image-2-1-mflux-q8"
         "@f5c8cc79a674 is not in %s (run bin/seed-edit-setup --model qwen21-q8)" % where),
        (["--qwen-model", "qwen21-q4", "--lora", "uncensored=1", "--lora", "viggle-turbo=1"],
         "LoRA Viggle turbo 6-step is unavailable: Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors "
         "is not in %s (run bin/seed-edit-setup --lora viggle-turbo)" % where),
    ]
    for i, (extra, text) in enumerate(cases):
        code, run_dir = run_tool(env, *extra, model="qwen", run=(R1, R2)[i])
        assert code == 2
        _refused(run_dir, text, capsys.readouterr())
    mp.setattr(qe, "avail_gib", lambda: 10.0)
    mp.setattr(qe, "AVAIL_WAIT_S", 0)
    code, run_dir = run_tool(env, "--qwen-model", "qwen21-q4", model="qwen", run=R3)
    assert code == 2
    _refused(run_dir, "only 10.0 GiB available after waiting 0 s; Qwen-Image-2.1 q4 needs 20 GiB; free memory and retry",
             capsys.readouterr())
    bf16_cache(env)
    stub = qwenedit_stub(env, {})
    mp.setattr(qe, "avail_gib", lambda: 40.0)
    code, run_dir = run_tool(env, "--qwen-model", "qwen2511-bf16", model="qwen", run=R4)
    assert code == 2
    _refused(run_dir, "only 40.0 GiB available after waiting 0 s; Qwen-Image-Edit-2511 bf16 (Lightning, diffusers) "
                      "needs 64 GiB; free memory and retry", capsys.readouterr())
    set_mflux_version(venv, "0.23.0")
    code, run_dir = run_tool(env, "--qwen-model", "qwen21-q4", model="qwen", run=R5)
    assert code == 2
    _refused(run_dir, "Qwen-Image-2.1 q4 is unavailable: mflux 0.23.0 in %s is older than 0.24.0 "
                      "(run bin/seed-edit-setup --model qwen21-q4)" % venv, capsys.readouterr())
    assert stub_calls(py) == [] and stub_calls(stub) == []
    set_mflux_version(venv, "0.24.0")
    stub_config(py, {"fail_after": 1})
    code, run_dir = run_tool(env, "--qwen-model", "qwen21-q4", "--lora", "uncensored=1", "--candidates", "3",
                             model="qwen", run="se-20261102-141500-0006")
    assert code == 1
    assert record_of(run_dir)["error"] == "Qwen-Image-2.1 q4 child exited 1: boom"
    assert statuses(run_dir) == ["ok", "failed", "failed"]


# --- SGT9 (SG20, SG21, SG22): the mflux child, screened in the parent ----------------------------------
# --- SGT9 (SG20, SG21, SG22): the mflux child, screened in the parent ----------------------------------

def test_sgt9_the_mflux_child_screened_in_the_parent(env, capsys):
    py, _venv = mflux_venv(env)
    q4, lora = mflux_weights(env)
    stub_config(py, {"red": [2]})
    code, run_dir = run_tool(env, "--qwen-model", "qwen2511-q4", "--candidates", "3", "--seed", "100", model="qwen")
    assert code == 0
    work = os.path.join(run_dir, "work")
    calls = stub_calls(py)
    assert len(calls) == 1
    assert calls[0]["argv"] == [py, os.path.join(WS, "seed_edit_mflux_child.py"), "--spec",
                                os.path.join(work, "mflux_spec.json")]
    assert calls[0]["env"] == {"HF_HUB_OFFLINE": "1", "PYTHONUNBUFFERED": "1"}
    assert calls[0]["spec"] == {
        "family": "qwen2511", "model_path": q4, "lora_paths": [lora], "lora_scales": [1.0], "width": 1024,
        "height": 672, "steps": 8, "guidance": 1.0, "scheduler": None,
        "jobs": [{"n": n, "seed": 100 + n, "prompt": PROMPT, "source": os.path.join(work, "source.png"),
                  "output_path": os.path.join(work, "cand_%02d.pending.png" % n)} for n in (1, 2, 3)]}
    assert [os.path.isfile(cand(run_dir, n)) for n in (1, 2, 3)] == [True, False, True]
    assert not os.path.exists(os.path.join(work, "cand_02.pending.png"))
    record = record_of(run_dir)
    assert statuses(run_dir) == ["ok", "blocked", "ok"]
    assert [c["seconds"] for c in record["candidates"]] == [1.0, 1.0, 1.0]
    assert (record["backend"], record["state"], record["strength"]) == ("mflux", "done", None)
    assert env["calls"]["safety"] == [{"skill": "seed_edit", "prompt": PROMPT, "size": (1024, 672)}] * 3
    out = capsys.readouterr().out.splitlines()
    assert "seed-edit: backend mflux (Qwen-Image-Edit-2511 q4 (Lightning); LoRAs none; 8 steps; scheduler default)" in out
    assert plain([line for line in out if line.startswith("candidate ")]) == [
        "candidate 1/3 ok Ss", "candidate 2/3 blocked Ss", "candidate 3/3 ok Ss"]


# --- SGT10 (SG17, SG20): the mflux child fails or times out --------------------------------------------

def test_sgt10_the_mflux_child_fails_or_times_out(env, capsys):
    qe = env["qe"]
    py, _venv = mflux_venv(env)
    mflux_weights(env)
    stub_config(py, {"fail_after": 1})
    q4 = ["--qwen-model", "qwen2511-q4", "--candidates", "3", "--seed", "100"]
    code, run_dir = run_tool(env, *q4, model="qwen", run=R1)
    assert code == 1
    record = record_of(run_dir)
    assert statuses(run_dir) == ["ok", "failed", "failed"]
    assert (record["state"], record["error"]) == ("failed", "Qwen-Image-Edit-2511 q4 (Lightning) child exited 1: boom")
    assert os.path.isfile(cand(run_dir, 1))
    out = capsys.readouterr().out.splitlines()
    assert "boom" in out and out[-3:] == ["candidate 2/3 failed", "candidate 3/3 failed",
                                         "seed-edit: done: 1 ok, 0 blocked, 2 failed"]
    env["mp"].setattr(qe, "CHILD_TIMEOUT_S", 1)
    env["mp"].setattr(qe, "JOB_TIMEOUT_S", 0)
    stub_config(py, {"sleep": 30})
    started = time.monotonic()
    code, run_dir = run_tool(env, *q4, model="qwen", run=R2)
    assert code == 1 and time.monotonic() - started < 20
    record = record_of(run_dir)
    assert statuses(run_dir) == ["failed"] * 3
    assert record["error"] == "Qwen-Image-Edit-2511 q4 (Lightning) child timed out after %d s" % qe.CHILD_TIMEOUT_S
    assert qe.CHILD is None
    env["mp"].setattr(qe, "CHILD_TIMEOUT_S", 3600)
    stub_config(py, {"kill_after": 1})
    code, run_dir = run_tool(env, *q4, model="qwen", run=R3)
    assert code == 1
    record = record_of(run_dir)
    assert statuses(run_dir) == ["ok", "failed", "failed"]
    assert (record["state"], record["error"]) == ("failed", "Qwen-Image-Edit-2511 q4 (Lightning) child exited -9: killed")
    assert qe.CHILD is None


# --- SGT11 (SG19, SG22): the diffusers bf16 child ------------------------------------------------------

def test_sgt11_the_bf16_child(env, capsys):
    bf16_cache(env)
    env["mp"].setattr(env["qe"], "avail_gib", lambda: 70.0)
    stub = qwenedit_stub(env, {"blocked": [2]})
    code, run_dir = run_tool(env, "--qwen-model", "qwen2511-bf16", "--candidates", "2", "--seed", "100", model="qwen")
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
    assert record_of(run_dir)["backend"] == "diffusers"
    assert ("seed-edit: backend diffusers (Qwen-Image-Edit-2511 bf16 (Lightning, diffusers); LoRAs none; 8 steps; "
            "scheduler default)") in capsys.readouterr().out.splitlines()
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
    got = tool.probe()
    assert got["zimage"] == {"ok": True, "reason": None, "backend": "zimage"}
    assert (got["qwen"]["ok"], got["qwen"]["reason"], got["qwen"]["models"]["qwen2511-q4"]) == (
        True, None, {"ok": True, "reason": None})
    assert "backend" not in got["qwen"]
    assert tool.main(["--probe"]) == 0
    assert capsys.readouterr().out == json.dumps(tool.probe(), sort_keys=True) + "\n"
    bf16_cache(env)
    mp.setattr(env["qe"], "total_gib", lambda: 128.0)
    assert tool.probe()["qwen"]["models"]["qwen2511-bf16"] == {"ok": True, "reason": None}
    missing = os.path.join(env["tmp"], "none", "bin", "python")
    mp.setenv("SEED_EDIT_MFLUX_PYTHON", missing)
    assert tool.probe()["qwen"]["models"]["qwen2511-q4"] == {
        "ok": False, "reason": "no mflux venv at %s (run bin/seed-edit-setup --model qwen2511-q4)" % missing}
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
        assert getattr(tool.qe, name) == getattr(character_dataset, name), name
    assert seedgen.qwen_model("qwen2511-bf16")["memory_gib"] == character_dataset.EDIT_MIN_AVAIL_GIB
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
    assert [dict(m) for m in seedgen.QWEN_MODELS] == [dict(r, max_references=k, reference_gib=g) for r, (k, g) in zip(REGISTRY, ((10, 2.0), (10, 2.0), (10, 2.0), (1, 3.0), (3, 3.0)))]   # extra references XR8
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
        assert entry["steps"] == tool.qe.EDIT_STEPS
        assert (entry["builtin_lora"]["repo"], entry["builtin_lora"]["file"]) == (tool.qe.EDIT_LORA_REPO,
                                                                                   tool.qe.EDIT_LORA_FILE)
    assert seedgen.qwen_model("qwen2511-bf16")["repo"] == tool.qe.EDIT_MODEL
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
    qe = env["qe"]
    py, _venv = mflux_venv(env)
    mflux_weights(env)
    bar = "  0%|          | 0/8 [00:00<?, ?it/s]\r100%|##########| 8/8 [00:01<00:00]\r"
    stub_config(py, {"prefix": bar})
    code, run_dir = run_tool(env, "--qwen-model", "qwen2511-q4", "--candidates", "2", "--seed", "1", model="qwen", run=R1)
    assert code == 0 and statuses(run_dir) == ["ok", "ok"]
    assert "100%|##########| 8/8 [00:01<00:00]\nseed-edit-child done 1 1.0\n" in capsys.readouterr().out
    bf16_cache(env)
    env["mp"].setattr(qe, "avail_gib", lambda: 70.0)
    qwenedit_stub(env, {"prefix": "Loading pipeline components...: 100%|##########| 5/5\r"})
    code, run_dir = run_tool(env, "--qwen-model", "qwen2511-bf16", "--candidates", "2", "--seed", "1", model="qwen",
                             run=R2)
    assert code == 0 and statuses(run_dir) == ["ok", "ok"]
    assert record_of(run_dir)["backend"] == "diffusers"


# --- Review Focus 1: a 2.1 run gets a canvas of multiples of 32 from a source that is not one -------------

def test_sq_review_focus_1_the_qwen21_canvas_reaches_the_child(env):
    tool = env["tool"]
    py, _venv = mflux_venv(env)
    install_model(env, "qwen21-q4")
    install_model(env, "qwen2511-q4")
    zimage_cache(env)
    source = png(os.path.join(env["tmp"], "phone.png"), (800, 600))
    want = {"qwen21-q4": (800, 576), "qwen2511-q4": (800, 592)}
    for i, model_id in enumerate(("qwen21-q4", "qwen2511-q4")):
        code, run_dir = run_tool(env, "--qwen-model", model_id, "--candidates", "1", model="qwen", source=source,
                                 run=(R1, R2)[i])
        assert code == 0, model_id
        spec = stub_calls(py)[-1]["spec"]
        assert (spec["width"], spec["height"]) == want[model_id]
        assert record_of(run_dir)["size"] == {"width": want[model_id][0], "height": want[model_id][1]}
        with Image.open(cand(run_dir, 1)) as img:
            assert img.size == want[model_id]
    code, run_dir = run_tool(env, "--candidates", "1", source=source, run=R3)
    assert code == 0 and record_of(run_dir)["size"] == {"width": 800, "height": 592}


# --- Review Focus 3: a Qwen job queued before the registry still runs -------------------------------------------

def test_sq_review_focus_3_a_job_queued_before_the_registry(env):
    tool = env["tool"]
    py, _venv = mflux_venv(env)
    snapshot, lightning = mflux_weights(env)
    ws = os.path.join(env["tmp"], "ws")
    run_dir = os.path.join(ws, "generated", "seeds", "runs", RUN)
    png(os.path.join(run_dir, "source.png"), (300, 200))
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": "seed-edit.run.v1", "run": RUN, "created": "2026-11-02T14:15:00Z", "state": "queued",
                   "prompt": PROMPT, "model": "qwen", "backend": None, "job": "20261102-141500-a1b2"}, f)
    fields = {"ws": ws, "run": RUN, "source_file": "source.png", "prompt": PROMPT, "model": "qwen", "strength": None,
              "candidates": 1, "seed": 5, "source": None}
    argv = lib.seed_edit_argv(fields, ws)
    assert "--qwen-model" not in argv
    assert tool.main(argv[2:]) == 0
    record = record_of(run_dir)
    assert (record["state"], record["backend"], record["job"]) == ("done", "mflux", "20261102-141500-a1b2")
    assert {k: record[k] for k in ("qwen_model", "loras", "steps", "scheduler")} == seedgen.qwen_settings(
        "qwen2511-q4", [])
    spec = stub_calls(py)[0]["spec"]
    assert (spec["family"], spec["model_path"], spec["lora_paths"], spec["steps"]) == (
        "qwen2511", snapshot, [lightning], 8)


# --- Review Focus 5: the selection survives the request -> argv -> tool round trip ------------------------------

ROUND_TRIPS = [("qwen21-q4", [{"id": "viggle-turbo", "scale": 2}, {"id": "uncensored", "scale": 1e-06}]),
               ("qwen21-q8", [{"id": "uncensored", "scale": 0.1 + 0.2}]), ("qwen21-bf16", []), ("qwen2511-q4", []),
               ("qwen2511-bf16", []), ("qwen21-q4", None), (None, None)]


def test_sq_review_focus_5_the_selection_round_trip(env):
    tool = env["tool"]
    ws = os.path.join(env["tmp"], "ws")
    prompt = "make it night --qwen-model qwen21-bf16 --lora viggle-turbo=2 --model zimage"
    for model_id, loras in ROUND_TRIPS:
        body = {"prompt": prompt, "model": "qwen", "source": {"upload_id": UP}, "qwen_model": model_id, "loras": loras}
        clean, error = seedgen.validate_run_request(body)
        assert error is None, (model_id, loras)
        fields = {"ws": ws, "run": RUN, "source_file": "source.png", "prompt": prompt, "model": "qwen",
                  "strength": None, "qwen_model": clean["qwen_model"], "loras": clean["loras"], "candidates": 2,
                  "seed": 9, "source": clean["source"]}
        opts = tool.check_args(tool.parse(lib.seed_edit_argv(fields, ws)[2:]))
        assert opts["prompt"] == prompt
        assert (opts["qwen_model"], opts["loras"]) == (clean["qwen_model"], clean["loras"]), (model_id, loras)
        assert seedgen.qwen_settings(opts["qwen_model"], opts["loras"]) == seedgen.qwen_settings(
            clean["qwen_model"], clean["loras"])



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
    assert child.parse_version("0.23.9") < child.MIN_VERSION <= child.parse_version("0.24.0")
    monkeypatch.setattr(child, "exit_with_parent", lambda poll_s=2.0: None)
    monkeypatch.setattr(child.importlib.metadata, "version", lambda name: "0.23.0")
    missing = os.path.join(str(tmp_path), "missing-spec.json")
    assert child.main(["--spec", missing]) == 2
    assert capsys.readouterr().out == ("seed-edit-child: mflux 0.23.0 is missing or older than 0.24.0; refusing "
                                       "(run bin/seed-edit-setup)\n")

    def not_installed(name):
        raise child.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(child.importlib.metadata, "version", not_installed)
    assert child.main(["--spec", missing]) == 2
    assert capsys.readouterr().out.startswith("seed-edit-child: mflux None is missing or older than 0.24.0")
    for text in ("bake_lora=False", "quantize=None", '.convert("RGB").save('):
        assert text in source, text


# --- SQT8 (seed models SQ28, SQ29): the child in-process with fake mlx and mflux modules --------------------

def child_fakes(monkeypatch):
    """sys.modules fakes of mlx, mlx.core, ModelConfig's module and the two FAMILIES classes; returns the
    record {"init": [(class name, kwargs)], "generate": [(class name, kwargs)]}."""
    record = {"init": [], "generate": []}
    core = types.ModuleType("mlx.core")
    core.get_peak_memory = lambda: 2 ** 30
    mlx = types.ModuleType("mlx")
    mlx.core = core
    config_module = types.ModuleType("mflux.models.common.config.model_config")

    class ModelConfig(object):
        def __init__(self, name):
            self.model_name = name

        @staticmethod
        def qwen_image_21():
            return ModelConfig("Qwen/Qwen-Image-2.1")

        @staticmethod
        def qwen_image_edit_2511():
            return ModelConfig("Qwen/Qwen-Image-Edit-2511")

    config_module.ModelConfig = ModelConfig

    def fake_class(name):
        class Fake(object):
            def __init__(self, **kwargs):
                record["init"].append((name, kwargs))

            def generate_image(self, **kwargs):
                record["generate"].append((name, kwargs))
                return types.SimpleNamespace(image=Image.new("RGBA", (kwargs["width"], kwargs["height"]),
                                                             (0, 0, 200, 128)))
        return Fake

    modules = {"mlx": mlx, "mlx.core": core, "mflux.models.common.config.model_config": config_module}
    for family, (module_name, class_name, _config) in (
            ("qwen21", ("mflux.models.qwen21.variants.edit.qwen_image_21_edit", "QwenImage21Edit", None)),
            ("qwen2511", ("mflux.models.qwen.variants.edit.qwen_image_edit", "QwenImageEdit", None))):
        module = types.ModuleType(module_name)
        setattr(module, class_name, fake_class(class_name))
        modules[module_name] = module
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    return record


def child_spec(tmp_path, family, lora_paths, lora_scales, scheduler):
    tmp = str(tmp_path)
    spec = {"family": family, "model_path": os.path.join(tmp, "model"), "lora_paths": lora_paths,
            "lora_scales": lora_scales, "prompt": PROMPT, "source": os.path.join(tmp, "source.png"), "width": 64,
            "height": 96, "steps": 40, "guidance": 1.0, "scheduler": scheduler,
            "jobs": [{"n": 1, "seed": 11, "output_path": os.path.join(tmp, "cand_01.pending.png")}]}
    path = os.path.join(tmp, "spec-%s-%d.json" % (family, len(lora_paths)))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(spec, f)
    return path, spec


def test_sqt8_the_child_per_family(monkeypatch, tmp_path, capsys):
    import seed_edit_mflux_child as child
    monkeypatch.setattr(child, "exit_with_parent", lambda poll_s=2.0: None)
    monkeypatch.setattr(child.importlib.metadata, "version", lambda name: "0.24.0")
    record = child_fakes(monkeypatch)
    lora = os.path.join(str(tmp_path), "uncensored.safetensors")
    path, spec = child_spec(tmp_path, "qwen21", [lora], [1.0], "linear")
    assert child.main(["--spec", path]) == 0
    (name, init), = record["init"]
    assert name == "QwenImage21Edit"
    assert set(init) == {"model_path", "quantize", "model_config", "lora_paths", "lora_scales", "bake_lora"}
    assert (init["model_path"], init["quantize"], init["model_config"].model_name, init["lora_paths"],
            init["lora_scales"], init["bake_lora"]) == (spec["model_path"], None, "Qwen/Qwen-Image-2.1", [lora], [1.0],
                                                        False)
    (name, kwargs), = record["generate"]
    assert kwargs == {"seed": 11, "prompt": PROMPT, "image_paths": [spec["source"]], "num_inference_steps": 40,
                      "guidance": 1.0, "width": 64, "height": 96, "scheduler": "linear"}
    with Image.open(spec["jobs"][0]["output_path"]) as img:
        assert (img.mode, img.size) == ("RGB", (64, 96))
    out = capsys.readouterr().out.splitlines()
    assert out[0] == ('seed-edit-child: mflux 0.24.0, family qwen21, model Qwen/Qwen-Image-2.1, transformer overrides '
                      'None, scheduler linear, LoRAs [["uncensored.safetensors", 1.0]]')
    assert re.fullmatch(r"seed-edit-child done 1 [0-9]+\.[0-9]", out[-1])
    record["init"], record["generate"] = [], []
    path, spec = child_spec(tmp_path, "qwen21", [], [], "viggle_turbo")
    assert child.main(["--spec", path]) == 0
    assert (record["init"][0][1]["lora_paths"], record["init"][0][1]["lora_scales"]) == (None, None)
    assert record["generate"][0][1]["scheduler"] == "viggle_turbo"
    record["init"], record["generate"] = [], []
    lightning = os.path.join(str(tmp_path), "lightning.safetensors")
    path, spec = child_spec(tmp_path, "qwen2511", [lightning], [1.0], None)
    assert child.main(["--spec", path]) == 0
    (name, init), = record["init"]
    assert (name, init["model_config"].model_name, init["lora_paths"]) == (
        "QwenImageEdit", "Qwen/Qwen-Image-Edit-2511", [lightning])
    kwargs = record["generate"][0][1]
    assert kwargs["negative_prompt"] == " " and "scheduler" not in kwargs
    capsys.readouterr()
    record["init"], record["generate"] = [], []
    path, spec = child_spec(tmp_path, "x", [], [], None)
    assert child.main(["--spec", path]) == 2
    assert capsys.readouterr().out == "seed-edit-child: unknown model family 'x'; refusing\n"
    assert record == {"init": [], "generate": []}
    monkeypatch.setattr(child.importlib.metadata, "version", lambda name: "0.23.0")
    assert child.main(["--spec", os.path.join(str(tmp_path), "missing.json")]) == 2
    assert capsys.readouterr().out == ("seed-edit-child: mflux 0.23.0 is missing or older than 0.24.0; refusing "
                                       "(run bin/seed-edit-setup)\n")


# --- SQT9 (seed models SQ2, SQ28): the child's FAMILIES table mirrors the registry ----------------------------

def test_sqt9_the_child_mirrors_the_registry():
    import seed_edit_mflux_child as child
    tool = load_tool()
    for entry in seedgen.QWEN_MODELS:
        if entry["backend"] != "mflux":
            continue
        module_name, class_name = entry["mflux_class"].rsplit(".", 1)
        assert child.FAMILIES[entry["family"]] == (module_name, class_name, entry["mflux_config"]), entry["id"]
    assert set(child.FAMILIES) == set(seedgen.QWEN_FAMILIES)
    assert child.MIN_VERSION == tool.qe.MFLUX_MIN_VERSION == (0, 24, 0)
    with open(os.path.join(WS, "seed_edit_mflux_child.py"), encoding="utf-8") as f:
        source = f.read()
    assert re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M) == [
        "argparse", "importlib.metadata", "json", "os", "re", "sys", "threading", "time"]
    for text in ("bake_lora=False", "quantize=None", '.convert("RGB").save('):
        assert text in source, text


# --- bin/seed-edit-setup in-process (seed models spec 9.1) --------------------------------------------------

def load_setup():
    path = os.path.join(WS, "bin", "seed-edit-setup")
    loader = importlib.machinery.SourceFileLoader("seed_edit_setup", path)
    spec = importlib.util.spec_from_loader("seed_edit_setup", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def setup_env(env):
    """bin/seed-edit-setup loaded in-process with spec 9.1's replacements: subprocess.call and .run record
    their argv (and env) and return 0 (the probe's stdout is rec["probe"], "" by default), free_gib
    returns rec["free"] (100 GiB), venv_ready returns
    rec["ready"] (False), and SEED_EDIT_SETUP_PYTHON is an executable stub under tmp. Nothing is started,
    downloaded or installed."""
    setup = load_setup()
    mp, tmp = env["mp"], env["tmp"]
    base = os.path.join(tmp, "base-python")
    with open(base, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(base, 0o755)
    mp.setenv("SEED_EDIT_SETUP_PYTHON", base)
    rec = {"call": [], "run": [], "free": 100.0, "ready": False, "probe": ""}

    def call(argv, env=None):
        rec["call"].append({"argv": list(argv), "env": env})
        return 0

    def run(argv, **kwargs):
        rec["run"].append(list(argv))
        if argv[0] == base:
            return types.SimpleNamespace(returncode=0, stdout="3.13\n", stderr="")
        return types.SimpleNamespace(returncode=0, stdout=rec["probe"], stderr="")

    mp.setattr(setup.subprocess, "call", call)
    mp.setattr(setup.subprocess, "run", run)
    mp.setattr(setup, "free_gib", lambda path: rec["free"])
    mp.setattr(setup, "venv_ready", lambda py, venv: rec["ready"])
    venv = os.path.join(tmp, "home", "mflux-edit", ".venv")
    return dict(env, setup=setup, rec=rec, base=base, venv=venv, py=os.path.join(venv, "bin", "python"),
                hub=env["zhub"])


def mark_ready(e):
    """venv_ready answers True, and the venv python exists (as it does whenever the venv is ready)."""
    e["rec"]["ready"] = True
    os.makedirs(os.path.dirname(e["py"]), exist_ok=True)
    with open(e["py"], "w", encoding="utf-8") as f:
        f.write("")


def downloads(rec):
    """The item lists of the recorded DOWNLOAD calls."""
    return [json.loads(c["argv"][4]) for c in rec["call"] if c["argv"][1] == "-c"]


Q4_ITEM = {"kind": "snapshot", "repo": "mflux-community/qwen-image-2-1-mflux-q4",
           "revision": "b6c0fc76350650482d13aea89b316c28cd487f7f", "allow_patterns": None}
UNC_ITEM = {"kind": "file", "repo": "abenzerps/Qwen-Image-2.1-Uncensored-Quantized",
            "revision": "7959e658915f52274897fb573ffeda49de8dc16b", "file": "qwen-image-2.1-uncensored-lora.safetensors"}
VIG_ITEM = {"kind": "file", "repo": "Viggle/Qwen-Image-2.1-viggle-turbo",
            "revision": "009a44a895ef85f7e643c80fdca9543795248867",
            "file": "Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors"}
LIGHTNING_ITEM = {"kind": "file", "repo": "lightx2v/Qwen-Image-Edit-2511-Lightning",
                  "revision": "107d238d68b8387e32843d0b4a2e24ceb0d3ad86",
                  "file": "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors"}
RESEARCH_LINE = "seed-edit-setup: license: %s: Qwen Research License (non-commercial)"


# --- SQT11 (seed models SQ41-SQ44): the items of a selection ---------------------------------------------------

def test_sqt11_the_setup_items(setup_env, capsys):
    e = setup_env
    setup, rec = e["setup"], e["rec"]
    assert setup.main([]) == 0
    download = rec["call"][2]
    assert [c["argv"] for c in rec["call"]] == [
        [e["base"], "-m", "venv", e["venv"]], [e["py"], "-m", "pip", "install", "mflux==0.24.0"],
        [e["py"], "-c", setup.DOWNLOAD, e["hub"], download["argv"][4]]]
    assert downloads(rec) == [[Q4_ITEM, UNC_ITEM]]
    assert {k: download["env"][k] for k in ("HF_HOME", "HF_HUB_OFFLINE", "HF_XET_CHUNK_CACHE_SIZE_BYTES",
                                            "HF_HUB_ENABLE_HF_TRANSFER")} == {
        "HF_HOME": os.path.dirname(e["hub"]), "HF_HUB_OFFLINE": "0", "HF_XET_CHUNK_CACHE_SIZE_BYTES": "0",
        "HF_HUB_ENABLE_HF_TRANSFER": "0"}
    assert [e["base"], "-c", "import sys; print('%d.%d' % sys.version_info[:2])"] in rec["run"]
    assert [sys.executable, os.path.join(WS, "bin", "seed-edit"), "--probe"] in rec["run"]
    out = capsys.readouterr().out.splitlines()
    assert RESEARCH_LINE % "qwen21-q4" in out and RESEARCH_LINE % "uncensored" in out
    assert out[-1] == "seed-edit-setup: probe: unavailable: bin/seed-edit --probe printed unparsable output"
    cases = [(["--model", "qwen21-bf16", "--lora", "viggle-turbo", "--lora", "uncensored"],
              [{"kind": "snapshot", "repo": "Qwen/Qwen-Image-2.1", "revision": "d26bb61231c349cf6b7896fa83353113880e1ba3",
                "allow_patterns": seedgen.QWEN21_PATTERNS}, VIG_ITEM, UNC_ITEM]),
             (["--model", "qwen2511-q4"],
              [{"kind": "snapshot", "repo": "mflux-community/qwen-image-edit-2511-mflux-q4",
                "revision": "3c74aab7dd79e6a8148c329cbca78c00c049ec3b", "allow_patterns": None}, LIGHTNING_ITEM]),
             (["--lora", "viggle-turbo"], [VIG_ITEM]),
             (["--model", "qwen21-q4", "--model", "qwen21-q4", "--lora", "uncensored", "--lora", "uncensored"],
              [Q4_ITEM, UNC_ITEM])]
    mark_ready(e)
    for argv, want in cases:
        rec["call"] = []
        assert setup.main(argv) == 0, argv
        assert downloads(rec) == [want], argv
        assert [c["argv"][1] for c in rec["call"]] == ["-c"], argv
    lora_repos = set(lora["repo"] for lora in seedgen.QWEN_LORAS) | {"lightx2v/Qwen-Image-Edit-2511-Lightning"}
    for model_id in ("qwen21-q4", "qwen21-q8", "qwen21-bf16", "qwen2511-q4"):
        for loras in ([], ["uncensored"], ["viggle-turbo"], ["uncensored", "viggle-turbo"]):
            rec["call"] = []
            argv = ["--model", model_id]
            for lora_id in loras:
                argv += ["--lora", lora_id]
            assert setup.main(argv) == 0, argv
            items = downloads(rec)[0]
            assert [i["repo"] for i in items if i["kind"] == "snapshot"] == [seedgen.qwen_model(model_id)["repo"]]
            assert not [i for i in items if i["kind"] == "snapshot" and i["repo"] in lora_repos], argv
            assert [i["file"] for i in items if i["kind"] == "file" and i["repo"] != LIGHTNING_ITEM["repo"]] == [
                seedgen.qwen_lora(lora_id)["file"] for lora_id in loras]


# --- SQT12 (seed models SQ44 step 4): the per-selection free-space floor ---------------------------------------

def test_sqt12_the_free_space_floor(setup_env, capsys):
    e = setup_env
    setup, rec = e["setup"], e["rec"]
    def where():
        return min(setup.existing_ancestor(e["hub"]), setup.existing_ancestor(os.path.dirname(e["venv"])))

    rec["free"] = 5.0
    assert setup.main([]) == 2
    assert capsys.readouterr().err == (
        "Error: only 5.0 GiB free on %s; seed-edit-setup needs at least 13.9 GiB more (13.9 GiB in all, 0.0 GiB "
        "already present; qwen21-q4 ~9.91 GiB, uncensored ~0.03 GiB, mflux venv ~3 GiB, 1 GiB headroom)\n" % where())
    assert rec["call"] == [] and rec["run"] == []
    total = (10638928735 + 33586704) / 2 ** 30 + 3.0 + 1.0
    rec["free"] = total - 2 / 1024
    assert setup.main([]) == 2
    capsys.readouterr()
    blobs = os.path.join(e["hub"], lib.repo_dir_name("mflux-community/qwen-image-2-1-mflux-q4"), "blobs")
    os.makedirs(blobs)
    with open(os.path.join(blobs, "abc.incomplete"), "wb") as f:
        f.truncate(3 * 2 ** 20)
    assert setup.main([]) == 0
    assert downloads(rec) == [[Q4_ITEM, UNC_ITEM]]
    capsys.readouterr()
    rec["call"], rec["run"], rec["free"] = [], [], 5.0
    mark_ready(e)
    assert setup.main([]) == 2
    assert capsys.readouterr().err == (
        "Error: only 5.0 GiB free on %s; seed-edit-setup needs at least 10.9 GiB more (10.9 GiB in all, 0.0 GiB "
        "already present; qwen21-q4 ~9.91 GiB, uncensored ~0.03 GiB, 1 GiB headroom)\n" % where())
    os.remove(os.path.join(blobs, "abc.incomplete"))
    pinned_cache(os.path.join(e["tmp"], "zi"), Q4_ITEM["repo"], Q4_ITEM["revision"], QWEN21_FILES)
    install_lora(e, "uncensored")
    assert setup.main([]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "seed-edit-setup: nothing to do" and rec["call"] == []
    assert out[2].startswith("seed-edit-setup: model qwen21-q4 %s: " % os.path.join(
        e["hub"], lib.repo_dir_name(Q4_ITEM["repo"]), "snapshots", Q4_ITEM["revision"]))


def test_sg_final_setup_resume_counts_what_is_present(setup_env, capsys):
    """Final review F1, re-based on seed models SQ44 step 4: a resumed download is not refused for space it
    already used: a 3 MiB partial blob in the q4 repo and a 1 MiB venv python count as present."""
    e = setup_env
    setup, rec = e["setup"], e["rec"]
    blobs = os.path.join(e["hub"], lib.repo_dir_name("mflux-community/qwen-image-2-1-mflux-q4"), "blobs")
    os.makedirs(blobs)
    with open(os.path.join(blobs, "abc.incomplete"), "wb") as f:
        f.truncate(3 * 2 ** 20)
    os.makedirs(os.path.dirname(e["py"]))
    with open(e["py"], "wb") as f:
        f.truncate(2 ** 20)
    total = (10638928735 + 33586704) / 2 ** 30 + 3.0 + 1.0
    rec["free"] = total - 3.5 / 1024
    assert setup.main([]) == 0
    assert [c["argv"][1] for c in rec["call"]] == ["-m", "-c"]
    capsys.readouterr()
    rec["free"] = total - 4.5 / 1024
    assert setup.main([]) == 2
    assert re.fullmatch(r"Error: only [0-9.]+ GiB free on .+; seed-edit-setup needs at least 13\.9 GiB more \(13\.9 GiB "
                        r"in all, 0\.0 GiB already present; qwen21-q4 ~9\.91 GiB, uncensored ~0\.03 GiB, mflux venv "
                        r"~3 GiB, 1 GiB headroom\)\n", capsys.readouterr().err)
    with open(os.path.join(WS, "bin", "seed-edit-setup"), encoding="utf-8") as f:
        source = f.read()
    assert 'HF_HUB_ENABLE_HF_TRANSFER="0"' in source and "already present" in source


# --- SQT13 (seed models SQ41): the refusals before anything else ------------------------------------------------

def test_sqt13_the_setup_refusals(setup_env, capsys):
    e = setup_env
    setup, rec = e["setup"], e["rec"]
    known = "qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-q4, qwen2511-bf16"
    bf16 = ("qwen2511-bf16 is not installed by seed-edit-setup: it runs the diffusers weights of "
            "Qwen/Qwen-Image-Edit-2511 and lightx2v/Qwen-Image-Edit-2511-Lightning from the default Hugging Face "
            "cache (%s)" % e["hfhub"])
    cases = [(["--model", "flux"], "unknown --model flux; known: %s" % known),
             (["--model", "qwen2511-bf16"], bf16),
             (["--model", "qwen2511-bf16", "--model", "flux"], "unknown --model flux; known: %s" % known),
             (["--lora", "nope"], "unknown --lora nope; known: uncensored, viggle-turbo"),
             (["--lora", "nope", "--model", "qwen2511-bf16"], bf16)]
    for argv, text in cases:
        assert setup.main(argv) == 2, argv
        assert capsys.readouterr().err == "Error: %s\n" % text, argv
    e["mp"].setenv("SEED_EDIT_MFLUX_PYTHON", "/x/python")
    assert setup.main([]) == 2
    assert capsys.readouterr().err == ("Error: SEED_EDIT_MFLUX_PYTHON is set; unset it to set up the default venv at "
                                       "~/mflux-edit/.venv\n")
    assert setup.main(["--model", "flux"]) == 2
    assert capsys.readouterr().err.startswith("Error: unknown --model flux")
    assert rec["call"] == [] and rec["run"] == []


# --- SQT14 (seed models SQ44 step 8): the DOWNLOAD script ----------------------------------------------------------

def test_sqt14_the_download_script(monkeypatch, tmp_path):
    setup = load_setup()
    calls = []
    fake = types.ModuleType("huggingface_hub")

    def snapshot_download(**kwargs):
        calls.append(("snapshot_download", kwargs))
        return "/snapshot"

    def hf_hub_download(**kwargs):
        calls.append(("hf_hub_download", kwargs))
        return "/file"

    fake.snapshot_download, fake.hf_hub_download = snapshot_download, hf_hub_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake)
    hub = os.path.join(str(tmp_path), "hub")
    items = [dict(Q4_ITEM, allow_patterns=["a/*.json"]), UNC_ITEM]
    monkeypatch.setattr(sys, "argv", ["-c", hub, json.dumps(items)])
    exec(compile(setup.DOWNLOAD, "DOWNLOAD", "exec"), {})
    assert calls == [
        ("snapshot_download", {"repo_id": Q4_ITEM["repo"], "revision": Q4_ITEM["revision"], "allow_patterns": ["a/*.json"],
                               "cache_dir": hub}),
        ("hf_hub_download", {"repo_id": UNC_ITEM["repo"], "filename": UNC_ITEM["file"], "revision": UNC_ITEM["revision"],
                             "cache_dir": hub})]


# --- Review Focus 4: a host holding a 2511 q4 snapshot from an older main ----------------------------------------

def test_sq_review_focus_4_an_old_main_2511_snapshot(setup_env, capsys):
    e = setup_env
    setup, rec, qe = e["setup"], e["rec"], e["qe"]
    entry = seedgen.qwen_model("qwen2511-q4")
    old = mt.make_hf_cache(os.path.join(e["tmp"], "zi"), entry["repo"], {"transformer/0.safetensors": b"\x01" * (4 * 2 ** 20)})
    mt.make_hf_cache(os.path.join(e["tmp"], "zi"), qe.EDIT_LORA_REPO, {qe.EDIT_LORA_FILE: b"\x01" * 8})
    assert qe.weights_problem(entry, qe.qwen_hubs())[0] == (
        "mflux-community/qwen-image-edit-2511-mflux-q4@3c74aab7dd79 is not in %s or %s "
        "(run bin/seed-edit-setup --model qwen2511-q4)" % (e["zhub"], e["hfhub"]))
    mark_ready(e)
    total = (entry["bytes"] + entry["builtin_lora"]["bytes"]) / 2 ** 30 + 1.0
    rec["free"] = total - 2 / 1024
    assert setup.main(["--model", "qwen2511-q4"]) == 2
    where = min(setup.existing_ancestor(e["hub"]), setup.existing_ancestor(os.path.dirname(e["venv"])))
    assert capsys.readouterr().err == (
        "Error: only 28.8 GiB free on %s; seed-edit-setup needs at least 28.8 GiB more (28.8 GiB in all, 0.0 GiB "
        "already present; qwen2511-q4 ~26.97 GiB, lightning ~0.79 GiB, 1 GiB headroom)\n" % where)
    assert rec["call"] == []
    rec["free"] = total
    assert setup.main(["--model", "qwen2511-q4"]) == 0
    assert downloads(rec) == [[{"kind": "snapshot", "repo": entry["repo"], "revision": entry["revision"],
                                "allow_patterns": None}, LIGHTNING_ITEM]]
    out = capsys.readouterr().out.splitlines()
    assert "seed-edit-setup: license: qwen2511-q4: Apache-2.0" in out
    assert "seed-edit-setup: license: lightning: Apache-2.0" in out
    assert os.path.isdir(os.path.join(old, "snapshots", REV))


# --- Final fix wave (seed models spec 14a items A, B, C, G, I) -----------------------------------------------------

def test_sq_final_a_the_floor_counts_only_the_pinned_revision(setup_env, capsys):
    """Item A: present counts each needed item's pinned snapshot (each realpath once) and the partial blobs whose
    finished blob is absent; another revision's snapshot and blobs and a stale .incomplete sidecar are not
    counted."""
    e = setup_env
    setup, rec = e["setup"], e["rec"]
    files = dict(QWEN21_FILES)
    files["transformer/0.safetensors"] = b"\x01" * (3 * 2 ** 20)
    del files["processor/tokenizer.json"]
    snapshot = pinned_cache(os.path.join(e["tmp"], "zi"), Q4_ITEM["repo"], Q4_ITEM["revision"], files)
    weights = os.path.join(snapshot, "transformer", "0.safetensors")
    os.symlink(os.readlink(weights), os.path.join(snapshot, "transformer", "1.safetensors"))
    repo_dir = os.path.dirname(os.path.dirname(snapshot))
    blobs = os.path.join(repo_dir, "blobs")
    for name, size in (("old0", 5 * 2 ** 20), ("beef", 8), ("beef.incomplete", 2 * 2 ** 20)):
        with open(os.path.join(blobs, name), "wb") as f:
            f.truncate(size)
    old = os.path.join(repo_dir, "snapshots", REV, "transformer")
    os.makedirs(old)
    os.symlink(os.path.join("..", "..", "..", "blobs", "old0"), os.path.join(old, "old.safetensors"))
    unc_blobs = os.path.join(e["hub"], lib.repo_dir_name(UNC_ITEM["repo"]), "blobs")
    os.makedirs(unc_blobs)
    with open(os.path.join(unc_blobs, "cafe.incomplete"), "wb") as f:
        f.truncate(2 ** 20)
    needed = setup.items_of(["qwen21-q4"], ["uncensored"])
    assert [setup.item_ok(item, e["hub"]) for item in needed] == [False, False]
    assert setup.partial_blobs(repo_dir) == []
    assert setup.partial_blobs(os.path.dirname(unc_blobs)) == [os.path.join(unc_blobs, "cafe.incomplete")]
    assert setup.partial_blobs(os.path.join(e["tmp"], "nowhere")) == []
    assert setup.present_gib(e["hub"], needed) == pytest.approx((4 * 2 ** 20 + 6) / 2 ** 30, abs=1e-12)
    total = (10638928735 + 33586704) / 2 ** 30 + 3.0 + 1.0
    rec["free"] = total - 4.1 / 1024
    assert setup.main([]) == 2
    assert "seed-edit-setup needs at least" in capsys.readouterr().err
    assert rec["call"] == []
    rec["free"] = total - 3.9 / 1024
    assert setup.main([]) == 0
    assert downloads(rec) == [[Q4_ITEM, UNC_ITEM]]


def test_sq_final_b_no_token_reaches_the_mflux_child(env):
    """Item B: the mflux child's env has no HF_TOKEN or HUGGING_FACE_HUB_TOKEN even when this process has them
    (dummy values), and has HF_HUB_DISABLE_IMPLICIT_TOKEN=1 beside SG20's HF_HUB_OFFLINE=1. No assert compares
    the whole env dict: it holds this process's environment, which a failure message would print."""
    tool, mp = env["tool"], env["mp"]
    mp.setenv("HF_TOKEN", "dummy-not-a-token")
    mp.setenv("HUGGING_FACE_HUB_TOKEN", "dummy-not-a-token")
    mp.delenv("HF_HUB_DISABLE_IMPLICIT_TOKEN", raising=False)
    mflux_venv(env)
    install_model(env, "qwen21-q4")
    install_lora(env, "uncensored")
    seen, real = [], env["qe"].run_child

    def spy(argv, child_env, on_line, timeout_s, log_path=None):
        seen.append(dict(child_env))
        return real(argv, child_env, on_line, timeout_s, log_path)

    mp.setattr(env["qe"], "run_child", spy)
    code, run_dir = run_tool(env, "--qwen-model", "qwen21-q4", "--lora", "uncensored=1", "--candidates", "1",
                             model="qwen")
    assert code == 0 and statuses(run_dir) == ["ok"]
    assert len(seen) == 1
    child = seen[0]
    assert sorted(k for k in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN") if k in child) == []
    assert (child["HF_HUB_DISABLE_IMPLICIT_TOKEN"], child["HF_HUB_OFFLINE"], child["PYTHONUNBUFFERED"]) == (
        "1", "1", "1")
    assert child["HOME"] == os.environ["HOME"]
    assert os.environ["HF_TOKEN"] == "dummy-not-a-token"


def test_sq_final_b_no_token_reaches_the_download(setup_env):
    """Item B (amends SQ45, SQT18): the download child's env has no HF_TOKEN or HUGGING_FACE_HUB_TOKEN even when
    this process has them (dummy values), has HF_HUB_DISABLE_IMPLICIT_TOKEN=1 and keeps SQ44 step 8's four values;
    seedgen.hf_child_env is the one rule both scripts use. No assert compares the whole env dict (a failure
    message would print this process's environment)."""
    e = setup_env
    setup, rec, mp = e["setup"], e["rec"], e["mp"]
    mp.setenv("HF_TOKEN", "dummy-not-a-token")
    mp.setenv("HUGGING_FACE_HUB_TOKEN", "dummy-not-a-token")
    mp.delenv("HF_HUB_DISABLE_IMPLICIT_TOKEN", raising=False)
    assert setup.main([]) == 0
    calls = [c for c in rec["call"] if c["argv"][1] == "-c"]
    assert len(calls) == 1
    child = calls[0]["env"]
    assert sorted(k for k in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN") if k in child) == []
    assert {k: child[k] for k in ("HF_HUB_DISABLE_IMPLICIT_TOKEN", "HF_HOME", "HF_HUB_OFFLINE",
                                  "HF_XET_CHUNK_CACHE_SIZE_BYTES", "HF_HUB_ENABLE_HF_TRANSFER")} == {
        "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "HF_HOME": os.path.dirname(e["hub"]), "HF_HUB_OFFLINE": "0",
        "HF_XET_CHUNK_CACHE_SIZE_BYTES": "0", "HF_HUB_ENABLE_HF_TRANSFER": "0"}
    assert child["HOME"] == os.environ["HOME"]
    assert seedgen.HF_TOKEN_VARS == ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")
    given = {"HF_TOKEN": "dummy", "HUGGING_FACE_HUB_TOKEN": "dummy", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "0", "A": "1"}
    assert seedgen.hf_child_env(given, B="2") == {"A": "1", "B": "2", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1"}
    assert given["HF_TOKEN"] == "dummy"


def test_sq_final_c_an_orphan_partial_blob_is_named(setup_env, capsys):
    """Item C: a partial blob the pinned download never completes (an older-main download left it) still blocks
    the pinned snapshot after a download that exited 0: setup names each such file, says to delete it, prints the
    report and exits 1; once it is deleted the snapshot is intact."""
    e = setup_env
    setup, rec = e["setup"], e["rec"]
    mark_ready(e)
    snapshot, _none = install_model(e, "qwen21-q4")
    install_lora(e, "uncensored")
    orphan = os.path.join(os.path.dirname(os.path.dirname(snapshot)), "blobs", "dead.incomplete")
    with open(orphan, "wb") as f:
        f.write(b"x")
    assert setup.main([]) == 1
    captured = capsys.readouterr()
    assert downloads(rec) == [[Q4_ITEM]]
    out = captured.out.splitlines()
    line = ("seed-edit-setup: orphan partial blob %s blocks qwen21-q4 (it is not part of "
            "mflux-community/qwen-image-2-1-mflux-q4@b6c0fc763506); delete it" % orphan)
    assert out.count(line) == 1
    assert out.index(line) < [x.startswith("seed-edit-setup: venv ") for x in out].index(True)
    assert captured.err == ("Error: 1 orphan partial blob(s) left by an earlier download block the pinned snapshot; "
                            "delete the file(s) listed above, then re-run bin/seed-edit-setup\n")
    os.remove(orphan)
    rec["call"] = []
    assert setup.main([]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "seed-edit-setup: nothing to do"
    assert rec["call"] == []


def test_sq_final_g_the_setup_probe_lines(setup_env, capsys):
    """Item G (SQ44 step 9): one probe line per selected model, then per selected LoRA, in selection order, from
    the last line of bin/seed-edit --probe; an answer missing a selected ID, or not the probe's shape, prints the
    unparsable line once."""
    e = setup_env
    setup, rec = e["setup"], e["rec"]
    mark_ready(e)
    models = dict((i, {"ok": True, "reason": None}) for i in seedgen.QWEN_MODEL_IDS)
    models["qwen21-q8"] = {"ok": False, "reason": "q8 is not here"}
    loras = {"uncensored": {"ok": True, "reason": None}, "viggle-turbo": {"ok": False, "reason": "viggle is not here"}}
    answer = {"zimage": {"ok": True, "reason": None, "backend": "zimage"},
              "qwen": {"ok": True, "reason": None, "models": models, "loras": loras}}
    rec["probe"] = "a log line\n" + json.dumps(answer) + "\n"
    argv = ["--model", "qwen21-q8", "--model", "qwen21-q4", "--lora", "viggle-turbo", "--lora", "uncensored"]
    assert setup.main(argv) == 0
    assert capsys.readouterr().out.splitlines()[-4:] == [
        "seed-edit-setup: probe: qwen21-q8 unavailable: q8 is not here", "seed-edit-setup: probe: qwen21-q4 ok",
        "seed-edit-setup: probe: viggle-turbo unavailable: viggle is not here", "seed-edit-setup: probe: uncensored ok"]
    assert rec["run"][-1] == [sys.executable, os.path.join(WS, "bin", "seed-edit"), "--probe"]
    del models["qwen21-q4"]
    unparsable = "seed-edit-setup: probe: unavailable: bin/seed-edit --probe printed unparsable output"
    for text in (json.dumps(answer), "", "{", "[]", json.dumps({"qwen": None})):
        rec["probe"] = text
        assert setup.main(argv) == 0, text
        out = capsys.readouterr().out.splitlines()
        assert out[-1] == unparsable and out.count(unparsable) == 1, text
        assert not [x for x in out if x.startswith("seed-edit-setup: probe: qwen")], text


def test_sq_final_i_the_default_selection_follows_the_registry(setup_env):
    """Item I (SQ41): no option selects DEFAULT_QWEN_MODEL and the LoRAs seedgen.default_loras gives it."""
    e = setup_env
    setup = e["setup"]
    none = types.SimpleNamespace(model=None, lora=None)
    assert setup.selection(none) == ((["qwen21-q4"], ["uncensored"]), None)
    asked = []

    def default_loras(model_id):
        asked.append(model_id)
        return [{"id": "viggle-turbo", "scale": 1.0}]

    e["mp"].setattr(setup.seedgen, "default_loras", default_loras)
    assert setup.selection(none) == ((["qwen21-q4"], ["viggle-turbo"]), None)
    assert asked == ["qwen21-q4"]


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


# --- QET12 (qwen edit models QE19-QE23, QEK3): the tool on top of qwen_edit.py behaves as before -------------

QET12_CASES = SQT5_CASES + [("qwen2511-bf16", [], [], [], 8, None,
                             "Qwen-Image-Edit-2511 bf16 (Lightning, diffusers); LoRAs none; 8 steps; scheduler default")]


@pytest.mark.parametrize("model_id,loras,paths,scales,steps,scheduler,why", QET12_CASES,
                         ids=["case%d" % (i + 1) for i in range(len(QET12_CASES))])
def test_qet12_the_tool_on_qwen_edit_behaves_as_before(env, capsys, model_id, loras, paths, scales, steps,
                                                        scheduler, why):
    env["mp"].setattr(env["qe"], "avail_gib", lambda: 128.0)
    entry = seedgen.qwen_model(model_id)
    if entry["backend"] == "mflux":
        py, _venv = mflux_venv(env)
        snapshot, lightning = install_model(env, model_id)
        found = {"lightning": lightning}
        for lora_id in ("uncensored", "viggle-turbo"):
            found[lora_id] = install_lora(env, lora_id)
    else:
        bf16_cache(env)
        stub = qwenedit_stub(env, {})
    extra = ["--qwen-model", model_id, "--candidates", "2", "--seed", "100"]
    for value in loras:
        extra += ["--lora", value]
    code, run_dir = run_tool(env, *extra, model="qwen")
    assert code == 0
    work = os.path.join(run_dir, "work")
    record = record_of(run_dir)
    chosen = [{"id": v.split("=")[0], "scale": float(v.split("=")[1])} for v in loras]
    expected = {"schema": "seed-edit.run.v1", "run": RUN, "created": None, "state": "done", "prompt": PROMPT,
                "model": "qwen", "backend": entry["backend"], "strength": None, "seed": 100,
                "size": {"width": 1024, "height": 672}, "source_size": {"width": 1536, "height": 1024},
                "source": "source.png", "source_origin": None, "job": None, "error": None,
                "candidates": [{"n": n, "seed": 100 + n, "status": "ok", "seconds": None} for n in (1, 2)]}
    expected.update(seedgen.qwen_settings(model_id, chosen))
    assert dict(record, created=None, candidates=[dict(c, seconds=None) for c in record["candidates"]]) == expected
    for n in (1, 2):
        with Image.open(cand(run_dir, n)) as img:
            assert img.size == (1024, 672)
    assert glob.glob(os.path.join(work, "*.part.png")) + glob.glob(os.path.join(work, "*.pending.png")) == []
    out = [line for line in capsys.readouterr().out.splitlines() if line.startswith(("seed-edit: ", "candidate "))]
    assert plain(out) == ["seed-edit: run %s" % run_dir, "seed-edit: source 1536x1024 -> 1024x672",
                          "seed-edit: backend %s (%s)" % (entry["backend"], why), "candidate 1/2 ok Ss",
                          "candidate 2/2 ok Ss", "seed-edit: done: 2 ok, 0 blocked, 0 failed"]
    if entry["backend"] == "mflux":
        (call,) = stub_calls(py)
        assert call["spec"] == {
            "family": entry["family"], "model_path": snapshot, "lora_paths": [found[p] for p in paths],
            "lora_scales": scales, "width": 1024, "height": 672, "steps": steps, "guidance": 1.0,
            "scheduler": scheduler,
            "jobs": [{"n": n, "seed": 100 + n, "prompt": PROMPT, "source": os.path.join(work, "source.png"),
                      "output_path": os.path.join(work, "cand_%02d.pending.png" % n)} for n in (1, 2)]}
    else:
        (call,) = stub_calls(stub)
        assert call["spec"] == {
            "image": os.path.join(work, "source.png"), "model": "Qwen/Qwen-Image-Edit-2511",
            "lora_repo": "lightx2v/Qwen-Image-Edit-2511-Lightning",
            "lora_file": "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors", "steps": 8, "true_cfg": 1.0,
            "skill": "seed_edit",
            "jobs": [{"prompt": PROMPT, "output_path": os.path.join(work, "cand_%02d.part.png" % n), "seed": 100 + n,
                      "width": 1024, "height": 672} for n in (1, 2)],
            "report_path": os.path.join(work, "qwenedit_report.json")}
    with open(TOOL_PATH, encoding="utf-8") as f:
        source = f.read()
    for gone in ("def run_child(", "def weights_problem(", "CHILD_TIMEOUT_S", "import subprocess", "import threading"):
        assert gone not in source, gone


# --- Review Focus 2: a Cancel during a Qwen run kills the Qwen child -----------------------------------------

def test_qe_review_focus_2_an_interrupt_kills_the_qwen_child(env, capsys):
    tool, qe, mp = env["tool"], env["qe"], env["mp"]
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    try:
        mp.setattr(qe, "CHILD", proc)
        qe.kill_running_child()
        assert proc.wait(timeout=10) == -9
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    killed = []
    mp.setattr(qe, "kill_running_child", lambda: killed.append(True))

    def interrupted(ctx):
        raise KeyboardInterrupt

    mp.setattr(tool, "run", interrupted)
    code, run_dir = run_tool(env, "--qwen-model", "qwen21-q4", model="qwen", run=R1)
    assert (code, killed) == (130, [True])
    record = record_of(run_dir)
    assert (record["state"], record["error"]) == ("cancelled", "interrupted")
    assert capsys.readouterr().err == "seed-edit: interrupted\n"
