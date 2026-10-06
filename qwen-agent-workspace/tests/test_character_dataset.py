"""Tests for character_dataset.py (spec docs/superpowers/specs/
2026-10-05-character-library-design.md Section 9.3, D1-D37).

Run from the workspace root: python3 -m pytest tests/test_character_dataset.py
Plain pytest asserts only (no check() helper). No network, no GPU, no real VLM, no real
training: every VLM call, story-server call, training subprocess and Z-Image child is
replaced by a fake. Real ffmpeg/ffprobe are used where the spec says so.
"""

import argparse
import ast
import base64
import collections
import hashlib
import io
import json
import os
import struct
import subprocess
import sys
import time
import types
import zipfile

import pytest
from PIL import Image

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import character_dataset  # noqa: E402
import character_lib  # noqa: E402
from character_dataset import DatasetError  # noqa: E402

SPIKE = os.path.join(WS, "generated", "charlora", "tools", "make_dataset_seed.py")

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


def _spike_literals():
    with open(SPIKE, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=SPIKE)
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(
                node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return values


def _ok(fn, *args):
    fn(*args)


def _bad(fn, *args):
    with pytest.raises(ValueError):
        fn(*args)


# --- D1-D6: ported helpers, prompts, face box, test prompt (spec 4.1, 4.5) ----------------
def test_d1_spike_self_test_ported(tmp_path):
    cd = character_dataset
    _ok(cd.extract_json, '{"a":1}')
    _ok(cd.extract_json, '```json\n{"b":2}\n```')
    _ok(cd.extract_json, 'here is result: {"c":3}')
    _bad(cd.extract_json, "not json at all")
    _bad(cd.extract_json, '[1,2,3]')
    good_desc = {"class_noun": "woman",
                 "descriptor": "a young woman with brown hair and blue eyes wearing a red jacket"}
    assert cd.validate_description(good_desc) == ("woman", good_desc["descriptor"])
    assert cd.validate_description({
        "class_noun": "man",
        "descriptor": "An older man with grey hair and a beard wearing a brown coat"})[1] == (
        "an older man with grey hair and a beard wearing a brown coat")
    _bad(cd.validate_description, {"class_noun": "woman", "descriptor": "a " + " ".join(["word"] * 60)})
    _bad(cd.validate_description, {"class_noun": "woman"})
    assert cd.validate_description({"class_noun": "Woman ",
                                    "descriptor": good_desc["descriptor"]})[0] == "woman"
    _bad(cd.validate_description, {"class_noun": "young woman",
                                   "descriptor": good_desc["descriptor"]})
    good_check = {"identity_score": 8, "shot": "medium shot",
                  "pose": "walking toward the camera", "setting": "a park"}
    assert cd.validate_check(good_check) == good_check
    _bad(cd.validate_check, {"identity_score": True, "shot": "medium shot", "pose": "standing",
                             "setting": "a park"})
    _bad(cd.validate_check, {"identity_score": 11, "shot": "medium shot", "pose": "standing",
                             "setting": "a park"})
    _bad(cd.validate_check, {"identity_score": 7, "shot": "full shot", "pose": "standing",
                             "setting": "a park"})
    assert cd.validate_check({"identity_score": 7, "shot": "medium shot", "pose": "standing",
                              "setting": "in a park."})["setting"] == "a park"
    _bad(cd.validate_check, {"identity_score": 7, "shot": "medium shot",
                             "pose": "one two three four five six seven eight nine ten eleven "
                                     "twelve thirteen", "setting": "a park"})
    assert cd.gen_prompt("medium shot", "walking toward the camera", "a city street",
                         "a young woman with brown hair") == (
        "Medium shot of a young woman with brown hair, walking toward the camera, in a city "
        "street. %s." % cd.STYLE)
    assert cd.caption("kyrawmn", "woman", {"identity_score": 9, "shot": "medium shot",
                                           "pose": "walking toward the camera",
                                           "setting": "a city street"}) == (
        "kyrawmn woman, medium shot, walking toward the camera, in a city street, %s." % cd.STYLE)
    path = str(tmp_path / "big.png")
    Image.new("RGB", (2000, 1000), (100, 150, 200)).save(path)
    url = cd.image_data_url(path, max_side=768)
    assert url.startswith("data:image/jpeg;base64,")
    img = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert max(img.size) <= 768


def test_d2_copied_literals_match_the_spike():
    spike = _spike_literals()
    for name in ("VARIANTS", "SHOTS", "STYLE", "CHECK_PROMPT"):
        assert getattr(character_dataset, name) == spike[name], name
    assert len(character_dataset.VARIANTS) == 24


def test_d3_describe_prompt():
    assert character_dataset.DESCRIBE_PROMPT == (
        'Describe the main character in this image for an image generator that must redraw the same '
        'person in many different poses and places. Reply with only a JSON object with two keys. '
        '"class_noun": one lowercase word for what they are (for example woman, man, girl, boy, person). '
        '"descriptor": one noun phrase of at most 45 words that starts with "a" or "an" and covers only '
        'what is visible about the character themselves: apparent age group, apparent ethnicity when it '
        'is visible, build, skin tone, hair colour, length and style, notable facial features, and the '
        'clothing and accessories they would wear anywhere. Leave out anything that belongs to this one '
        'situation rather than to the person: footwear, gear or props that are visible only because of '
        'what they are doing here (for example riding boots while riding, or a tool they are using), '
        'anything they are holding, and any animal or vehicle. Do not mention the background, the pose, '
        'the action, the camera, the lighting or the image style.')
    for phrase in ("apparent ethnicity when it is visible", "riding boots while riding",
                   "anything they are holding"):
        assert phrase in character_dataset.DESCRIBE_PROMPT


def test_d4_validate_face_values():
    assert character_dataset.validate_face({"face_box": [100, 200, 300, 500]}) == 0.3
    assert character_dataset.validate_face({"face_box": None}) is None
    assert character_dataset.validate_face({"face_box": [0, 0, 1000, 1000]}) == 1.0


def test_d5_validate_face_rejects():
    for reply in ({}, {"face_box": [1, 2, 3]}, {"face_box": [1, 2, 3, True]},
                  {"face_box": [300, 200, 100, 500]}, {"face_box": [0, 0, 1001, 10]},
                  {"face_box": "box"}):
        _bad(character_dataset.validate_face, reply)


def test_d6_trigger_test_prompt():
    assert character_dataset.trigger_test_prompt("kyrawmn", "woman") == (
        "kyrawmn woman, medium shot, standing and facing the camera, photorealistic live-action "
        "film still, natural light.")


# --- D15-D19: contact sheet, safety gates, run_logged (spec 4.7, 4.8, 4.12) ---------------
def test_d15_contact_sheet(tmp_path):
    stills = tmp_path / "stills"
    stills.mkdir()
    items = []
    for n in range(25):
        if n != 7:
            Image.new("RGB", (1024, 640), (40, 120, 200)).save(str(stills / ("char_%02d.png" % n)))
        items.append({"n": n, "identity_score": 9, "kept": n not in (5, 7)})
    out = str(tmp_path / "sheet.jpg")
    character_dataset.write_contact_sheet(items, str(stills), out)
    with Image.open(out) as sheet:
        assert sheet.format == "JPEG"
        assert sheet.size == (1280, 900)
        r, g, b = sheet.convert("RGB").getpixel(((5 % 5) * 256 + 1, (5 // 5) * 180 + 1))
        assert r > 200 and g < 60
        cx, cy = (7 % 5) * 256 + 128, (7 // 5) * 180 + 80
        assert max(sheet.convert("RGB").getpixel((cx, cy))) < 30


STATUS_SERVING = ("story-server status  2026-10-05T12:00:00Z\n"
                  "  state:          SERVING vision\n"
                  "  port 8177:      LISTEN pid 15362\n"
                  "  health:         HTTP 200 model=qwen38-6bit\n")


def test_d16_story_server_state(monkeypatch):
    replies = [(0, STATUS_SERVING), (0, STATUS_SERVING.replace("SERVING vision", "STOPPED")),
               (0, STATUS_SERVING.replace("SERVING vision", "LOADING vision")),
               (1, "story-server: something went wrong\n"), OSError("no such file")]

    def _run(cmd, **kwargs):
        assert cmd == [character_dataset.STORY_SERVER, "status"]
        assert kwargs["timeout"] == 60
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return subprocess.CompletedProcess(cmd, reply[0], reply[1], "")

    monkeypatch.setattr(character_dataset.subprocess, "run", _run)
    assert [character_dataset.story_server_state() for _ in range(5)] == [
        "SERVING vision", "STOPPED", "LOADING vision", "UNKNOWN", "UNKNOWN"]


class _FakeProc(object):
    def __init__(self, pid, cmdline):
        self.info = {"pid": pid, "cmdline": cmdline}


def test_d17_busy_process(monkeypatch):
    cmdlines = [["/x/ltx-2-mlx", "generate", "--model", "m"],
                ["python3", "bin/ltx-mlx-render", "m.json", "o.mp4"],
                ["/x/mflux-train", "--config", "c"],
                ["vim", "notes-ltx-2-mlx.txt"],
                ["python3", "character_dataset.py", "zimage", "--spec", "s"]]
    results = []
    for cmdline in cmdlines:
        monkeypatch.setattr(character_dataset.psutil, "process_iter",
                            lambda attrs, c=cmdline: iter([_FakeProc(4242, c)]))
        results.append(character_dataset.busy_process())
    assert results[0] == (4242, "/x/ltx-2-mlx generate --model m")
    assert results[1] == (4242, "python3 bin/ltx-mlx-render m.json o.mp4")
    assert results[2] == (4242, "/x/mflux-train --config c")
    assert results[3] is None
    assert results[4] == (4242, "python3 character_dataset.py zimage --spec s")


def test_d18_library_lock(lib_dir):
    lock = os.path.join(lib_dir, ".lock")
    with character_dataset.library_lock():
        with open(lock) as f:
            assert f.read() == str(os.getpid())
    assert not os.path.exists(lock)
    with open(lock, "w") as f:
        f.write(str(os.getppid()))
    with pytest.raises(DatasetError) as info:
        with character_dataset.library_lock():
            pass
    assert str(info.value) == ("another bin/character create/train is running (pid %d); run "
                               "one at a time" % os.getppid())
    with open(lock, "w") as f:
        f.write("99999999")
    with character_dataset.library_lock():
        with open(lock) as f:
            assert f.read() == str(os.getpid())
    assert not os.path.exists(lock)


def test_d19_run_logged(tmp_path):
    log = str(tmp_path / "a.log")
    assert character_dataset.run_logged(["sh", "-c", "echo a; echo b 1>&2; exit 3"], log, "/",
                                        os.environ, 10) == 3
    with open(log) as f:
        assert f.read() == "a\nb\n"
    started = time.monotonic()
    assert character_dataset.run_logged(["sleep", "5"], str(tmp_path / "b.log"), "/",
                                        os.environ, 1) == -9
    assert time.monotonic() - started < 3


# --- D35-D37: the Z-Image child protocol and the import rule (spec 1.2, 4.9) -------------
def test_d35_child_zimage(tmp_path, monkeypatch):
    calls = []

    class _ModuleDict(dict):
        pass

    class _Generator(object):
        def __init__(self, device):
            pass

        def manual_seed(self, seed):
            return self

    class _Blocked(Exception):
        pass

    def _generate(prompt, **kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise _Blocked("blocked")

    modules = [types.SimpleNamespace(lora_A=_ModuleDict(lora0=1)) for _ in range(3)]
    modules.append(types.SimpleNamespace(lora_A=_ModuleDict(other=1)))
    modules.append(types.SimpleNamespace())
    fake_torch = types.ModuleType("torch")
    fake_torch.Generator = _Generator
    fake_torch.nn = types.SimpleNamespace(ModuleDict=_ModuleDict)
    fake_zimage = types.ModuleType("z_image_skill")
    fake_zimage.generate_image = _generate
    fake_zimage._pipeline = types.SimpleNamespace(
        transformer=types.SimpleNamespace(modules=lambda: iter(modules)))
    fake_safety = types.ModuleType("content_safety")
    fake_safety.ContentSafetyError = _Blocked
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "z_image_skill", fake_zimage)
    monkeypatch.setitem(sys.modules, "content_safety", fake_safety)
    report_path = str(tmp_path / "report.json")
    spec = {"jobs": [{"prompt": "p%d" % i, "output_path": str(tmp_path / ("%d.png" % i)),
                      "seed": 42, "width": 1024, "height": 640} for i in range(3)],
            "loras": [["/x/a.safetensors", 1.0]], "report_path": report_path}
    spec_path = str(tmp_path / "spec.json")
    with open(spec_path, "w") as f:
        json.dump(spec, f)
    assert character_dataset.main(["zimage", "--spec", spec_path]) == 0
    with open(report_path) as f:
        report = json.load(f)
    assert [j["status"] for j in report["jobs"]] == ["ok", "blocked", "ok"]
    assert report["injected_lora_modules"] == 3
    assert all(kw["loras"] == [("/x/a.safetensors", 1.0)] for kw in calls)
    assert len(calls) == 3


def test_d36_child_failure_names_the_log(tmp_path, monkeypatch):
    monkeypatch.setattr(character_dataset, "run_logged", lambda *a, **kw: 1)
    with pytest.raises(DatasetError) as info:
        character_dataset.run_zimage_child({"jobs": [], "loras": None}, str(tmp_path), "generate")
    message = str(info.value)
    assert message.startswith("Z-Image child process exited 1; log: %s" % os.path.join(
        str(tmp_path), "logs"))
    assert message.endswith("-generate.log")


def test_d37_no_heavy_top_level_imports():
    path = os.path.join(WS, "character_dataset.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    roots = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
    assert roots and not roots & {"torch", "z_image_skill", "content_safety", "diffusers"}


def test_d38_run_logged_kills_child_on_interrupt(tmp_path, monkeypatch):
    procs = []
    real_popen = subprocess.Popen

    def _popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        procs.append(proc)
        return proc

    monkeypatch.setattr(character_dataset.subprocess, "Popen", _popen)

    class _Out(object):
        def write(self, text):
            if procs:
                raise KeyboardInterrupt()

        def flush(self):
            pass

    monkeypatch.setattr(character_dataset.sys, "stdout", _Out())
    with pytest.raises(KeyboardInterrupt):
        character_dataset.run_logged(["sh", "-c", "echo start; sleep 30"],
                                     str(tmp_path / "c.log"), "/", os.environ, 60)
    assert len(procs) == 1
    assert procs[0].poll() is not None
    assert procs[0].returncode == -9


def test_d39_image_data_url_applies_exif_orientation(tmp_path):
    path = str(tmp_path / "rot.jpg")
    img = Image.new("RGB", (200, 100), (10, 20, 30))
    exif = img.getexif()
    exif[0x0112] = 6
    img.save(path, format="JPEG", exif=exif.tobytes())
    url = character_dataset.image_data_url(path)
    data = base64.b64decode(url.split(",", 1)[1])
    assert Image.open(io.BytesIO(data)).size == (100, 200)


# --- D7, D8, D20-D28: video LoRA training and train() (spec 4.8, 4.11) -------------------
def test_d7_video_train_config():
    text = character_dataset.video_train_config("/d/pre", "p, q.", "/d/out")
    assert text == character_dataset.VIDEO_TRAIN_CONFIG_TEMPLATE.format(
        model_path=json.dumps(character_dataset.TRAIN_MODEL_DIR),
        gemma=json.dumps(character_dataset.SKILL.GEMMA_MODEL_ID),
        data_root='"/d/pre"', validation_prompt='"p, q."', output_dir='"/d/out"')
    lines = text.splitlines()
    for line in ('  model_path: "%s"' % character_dataset.TRAIN_MODEL_DIR,
                 '  preprocessed_data_root: "/d/pre"', '    - "p, q."', 'output_dir: "/d/out"',
                 "  rank: 32", "  alpha: 32", "  steps: 1000", "  interval: 250",
                 "  keep_last_n: 10"):
        assert line in lines, line
    assert "{" not in text


def test_d8_preprocess_and_train_argv():
    cd = character_dataset
    assert cd.preprocess_argv("/v", "/c", "/o") == [
        cd.SKILL.LTX2_MLX_BIN, "preprocess", "--videos", "/v", "--captions", "/c", "-o", "/o",
        "-m", cd.TRAIN_MODEL_DIR, "-H", "320", "-W", "512", "--max-frames", "1"]
    assert cd.train_argv("/t.yaml") == [cd.SKILL.LTX2_MLX_BIN, "train", "--config", "/t.yaml",
                                        "--low-ram"]


def _untrained(lib, name="kyra", kept=24):
    """An untrained character with a real dataset layout: 25 tiny stills, and captions,
    1-frame "videos" and manifest items for the kept ones (n 5 is the dropped still)."""
    data = make_character(lib, name=name, status="untrained")
    data["dataset"]["kept"] = kept
    cdir = os.path.join(lib, name)
    kept_ns = [n for n in range(25) if n != 5][:kept]
    for sub in ("stills", "captions", "videos"):
        os.makedirs(os.path.join(cdir, "dataset", sub), exist_ok=True)
    items = []
    for n in range(25):
        Image.new("RGB", (8, 8), (n, n, n)).save(os.path.join(cdir, "dataset", "stills",
                                                              "char_%02d.png" % n))
        if n in kept_ns:
            with open(os.path.join(cdir, "dataset", "captions", "char_%02d.txt" % n), "w") as f:
                f.write("kyrawmn woman, close-up, n %d" % n)
            with open(os.path.join(cdir, "dataset", "videos", "char_%02d.mp4" % n), "wb") as f:
                f.write(b"mp4")
        items.append({"n": n, "kept": n in kept_ns})
    with open(os.path.join(cdir, "dataset", "manifest.json"), "w") as f:
        json.dump({"items": items}, f)
    character_lib.write_character(data)
    return data


def _fake_video_tools(monkeypatch, preprocess_rc=0, latents=None, train_rc=0,
                      write_checkpoint=True, fail_test=None):
    """run_logged and SKILL.generate_video fakes; returns the dict of recorded calls."""
    record = {"run": [], "generate": []}

    def _run(cmd, log_path, cwd, env, timeout_s):
        record["run"].append({"cmd": cmd, "log": log_path, "cwd": cwd, "env": env})
        if cmd[1] == "preprocess":
            out_dir = cmd[cmd.index("-o") + 1]
            videos = cmd[cmd.index("--videos") + 1]
            latent_dir = os.path.join(out_dir, ".precomputed", "latents")
            os.makedirs(latent_dir)
            count = len(os.listdir(videos)) if latents is None else latents
            for i in range(count):
                open(os.path.join(latent_dir, "l%02d.safetensors" % i), "wb").close()
            return preprocess_rc
        vdir = os.path.dirname(cmd[cmd.index("--config") + 1])
        if write_checkpoint:
            ckpt_dir = os.path.join(vdir, "out", "checkpoints")
            os.makedirs(ckpt_dir)
            with open(os.path.join(ckpt_dir, character_dataset.VIDEO_FINAL_CKPT), "wb") as f:
                f.write(b"lora")
        return train_rc

    def _generate(prompt, output_path, **kwargs):
        record["generate"].append(dict(kwargs, prompt=prompt, output_path=output_path))
        if fail_test is not None and len(record["generate"]) == fail_test:
            raise character_dataset.SKILL.Ltx2MlxError("stub render failure")
        with open(output_path, "wb") as f:
            f.write(b"mp4")
        return output_path

    monkeypatch.setattr(character_dataset, "run_logged", _run)
    monkeypatch.setattr(character_dataset.SKILL, "generate_video", _generate)
    return record


_Memory = collections.namedtuple("_Memory", "available")


def _train_ready(monkeypatch, tmp_path):
    """Every train() preflight passes: no busy process, server STOPPED, 64 GiB available,
    100 GiB free, a valid dev-model dir, a test-model dir, and executable stub binaries."""
    dev = tmp_path / "dev-model"
    dev.mkdir(parents=True)
    (dev / "transformer-dev.safetensors").write_bytes(b"dev")
    test_model = tmp_path / "test-model"
    test_model.mkdir(parents=True)
    stub = tmp_path / "stub-bin"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    monkeypatch.setattr(character_dataset, "busy_process", lambda: None)
    monkeypatch.setattr(character_dataset, "story_server_state", lambda: "STOPPED")
    monkeypatch.setattr(character_dataset.psutil, "virtual_memory",
                        lambda: _Memory(64.0 * 2 ** 30))
    monkeypatch.setattr(character_dataset, "free_gib", lambda path: 100.0)
    monkeypatch.setattr(character_dataset, "TRAIN_MODEL_DIR", str(dev))
    monkeypatch.setattr(character_dataset, "TEST_MODEL_DIR", str(test_model))
    monkeypatch.setattr(character_dataset.SKILL, "LTX2_MLX_BIN", str(stub))
    monkeypatch.setattr(character_dataset, "MFLUX_TRAIN", str(stub))
    return dev


def _train_args(name="kyra", video=False, stills=False, force=False):
    return argparse.Namespace(command="train", name=name, video=video, stills=stills, force=force)


def _load(name="kyra"):
    return character_lib.load_character(name)


def test_d20_train_video_happy_path(lib_dir, monkeypatch):
    data = _untrained(lib_dir)
    record = _fake_video_tools(monkeypatch)
    assert character_dataset.train_video(data) == "ok"
    lora = os.path.join(lib_dir, "kyra", "lora", "video.safetensors")
    with open(lora, "rb") as f:
        assert f.read() == b"lora"
    saved = _load()
    entry = saved["loras"]["video"]
    assert saved["status"] == "trained"
    assert entry["sha256"] == hashlib.sha256(b"lora").hexdigest()
    assert (entry["rank"], entry["alpha"], entry["steps"]) == (32, 32, 1000)
    assert entry["sample_path"] == os.path.join(lib_dir, "kyra", "tests", "video_lora.mp4")
    assert entry["control_path"] == os.path.join(lib_dir, "kyra", "tests", "video_control.mp4")
    first, second = record["generate"]
    assert first["loras"] == [(lora, 1.0)]
    assert (first["width"], first["height"], first["num_frames"], first["seed"]) == (512, 320, 25, 42)
    assert first["model"] == character_dataset.TEST_MODEL_DIR
    assert first["image_path"] is None
    assert "loras" not in second
    assert [r["cmd"][1] for r in record["run"]] == ["preprocess", "train"]
    assert all(r["env"]["HF_HOME"] == character_dataset.SKILL.LTX2_MLX_HF_HOME
               and r["cwd"] == character_dataset.SKILL.LTX2_MLX_DIR for r in record["run"])


def test_d21_preprocess_failure(lib_dir, monkeypatch, capsys):
    data = _untrained(lib_dir)
    _fake_video_tools(monkeypatch, preprocess_rc=1)
    assert character_dataset.train_video(data) == "failed"
    err = capsys.readouterr().err
    assert "failed at preprocess (exit 1)" in err
    assert "log: %s" % os.path.join(lib_dir, "kyra", "logs") in err
    assert "-preprocess.log" in err
    assert _load()["status"] == "untrained"
    assert not os.path.exists(os.path.join(lib_dir, "kyra", "lora", "video.safetensors"))


def test_d22_latent_count_mismatch(lib_dir, monkeypatch, capsys):
    data = _untrained(lib_dir)
    _fake_video_tools(monkeypatch, latents=23)
    assert character_dataset.train_video(data) == "failed"
    assert "preprocess wrote 23 latents for 24 videos" in capsys.readouterr().err


def test_d23_missing_final_checkpoint(lib_dir, monkeypatch, capsys):
    data = _untrained(lib_dir)
    _fake_video_tools(monkeypatch, write_checkpoint=False)
    assert character_dataset.train_video(data) == "failed"
    assert "failed at train" in capsys.readouterr().err


def test_d24_test_render_failure_keeps_the_lora(tmp_path, lib_dir, monkeypatch, capsys):
    data = _untrained(lib_dir)
    _fake_video_tools(monkeypatch, fail_test=1)
    assert character_dataset.train_video(data) == "test_failed"
    saved = _load()
    assert saved["status"] == "trained"
    assert saved["loras"]["video"]["sample_path"] is None
    assert saved["loras"]["video"]["control_path"] is not None
    assert "Error: video test render failed: stub render failure" in capsys.readouterr().err

    _untrained(lib_dir, name="ronin")
    _fake_video_tools(monkeypatch, fail_test=1)
    _train_ready(monkeypatch, tmp_path)
    stills_calls = []
    monkeypatch.setattr(character_dataset, "train_stills",
                        lambda d: stills_calls.append(d["name"]) or "ok", raising=False)
    assert character_dataset.train(_train_args("ronin")) == 1
    assert stills_calls == ["ronin"]


def test_d25_stale_training_dir_is_removed(lib_dir, monkeypatch):
    data = _untrained(lib_dir)
    stale = os.path.join(lib_dir, "kyra", "train", "video", "stale.txt")
    os.makedirs(os.path.dirname(stale))
    with open(stale, "w") as f:
        f.write("old")
    _fake_video_tools(monkeypatch)
    assert character_dataset.train_video(data) == "ok"
    assert not os.path.exists(stale)


def test_d26_preflight_order(tmp_path, lib_dir, monkeypatch, capsys):
    _untrained(lib_dir)
    char_dir = os.path.join(lib_dir, "kyra")

    def _never(data):
        raise AssertionError("train_video ran")

    def _case(name, override, message):
        with monkeypatch.context() as m:
            dev = _train_ready(m, tmp_path / name)
            m.setattr(character_dataset, "train_video", _never)
            override(m, dev)
            assert character_dataset.train(_train_args()) == 2, name
        assert capsys.readouterr().err == message + "\n", name

    lock = os.path.join(lib_dir, ".lock")

    def _hold_lock(m, dev):
        with open(lock, "w") as f:
            f.write(str(os.getppid()))

    _case("lock", _hold_lock, "Error: another bin/character create/train is running (pid %d); "
          "run one at a time" % os.getppid())
    os.remove(lock)
    _case("busy", lambda m, dev: m.setattr(character_dataset, "busy_process",
                                           lambda: (4242, "python3 bin/ltx-mlx-render m.json")),
          "Error: a render or training process is running (pid 4242: python3 bin/ltx-mlx-render "
          "m.json); bin/character never trains or generates concurrently with a render")
    _case("server", lambda m, dev: m.setattr(character_dataset, "story_server_state",
                                             lambda: "SERVING vision"),
          "Error: the story server is SERVING vision; stop it first with bin/story-server stop "
          "(training needs its memory)")
    _case("memory", lambda m, dev: m.setattr(character_dataset.psutil, "virtual_memory",
                                             lambda: _Memory(29.9 * 2 ** 30)),
          "Error: only 29.9 GiB of memory is available; training needs 30 GiB (quit "
          "memory-heavy apps and retry)")
    _case("disk", lambda m, dev: m.setattr(character_dataset, "free_gib", lambda path: 15.9),
          "Error: only 15.9 GiB free at %s; training video and stills needs 16 GiB" % char_dir)

    def _distilled(m, dev):
        (dev / "transformer-distilled.safetensors").write_bytes(b"x")

    _case("dev", _distilled,
          "Error: %s must contain transformer-dev.safetensors and neither "
          "transformer.safetensors nor transformer-distilled.safetensors (the trainer would "
          "pick those first)" % (tmp_path / "dev" / "dev-model"))

    def _server_and_memory(m, dev):
        m.setattr(character_dataset, "story_server_state", lambda: "SERVING vision")
        m.setattr(character_dataset.psutil, "virtual_memory", lambda: _Memory(29.9 * 2 ** 30))

    _case("order", _server_and_memory,
          "Error: the story server is SERVING vision; stop it first with bin/story-server stop "
          "(training needs its memory)")
    assert not os.path.exists(lock)


def test_d27_existing_lora_needs_force(tmp_path, lib_dir, monkeypatch, capsys):
    make_character(lib_dir)
    _train_ready(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(character_dataset, "train_video",
                        lambda data: calls.append(data["name"]) or "ok")
    assert character_dataset.train(_train_args(video=True)) == 2
    assert capsys.readouterr().err == (
        "Error: character kyra already has a video LoRA (%s); pass --force to retrain it\n"
        % os.path.join(lib_dir, "kyra", "lora", "video.safetensors"))
    assert calls == []
    assert character_dataset.train(_train_args(video=True, force=True)) == 0
    assert calls == ["kyra"]


def test_d28_missing_mflux_skips_stills(tmp_path, lib_dir, monkeypatch, capsys):
    _untrained(lib_dir)
    _train_ready(monkeypatch, tmp_path)
    missing = str(tmp_path / "no-mflux" / "mflux-train")
    monkeypatch.setattr(character_dataset, "MFLUX_TRAIN", missing)
    calls = []
    monkeypatch.setattr(character_dataset, "train_video",
                        lambda data: calls.append(data["name"]) or "ok")
    assert character_dataset.train(_train_args()) == 0
    assert calls == ["kyra"]
    assert _load()["stills_skip_reason"] == "mflux-train not found at %s" % missing
    assert ("stills LoRA skipped: mflux-train not found at %s; install mflux as described in "
            "docs/superpowers/specs/2026-10-05-character-library-design.md section 4.10"
            % missing) in capsys.readouterr().out
    assert character_dataset.train(_train_args(stills=True)) == 1
    assert calls == ["kyra"]
