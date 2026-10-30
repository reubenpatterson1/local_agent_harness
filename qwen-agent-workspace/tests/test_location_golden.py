"""The character golden record of the location library's training refactor
(docs/superpowers/specs/2026-10-29-location-lora-design.md, Sections 3.10, 6.3 and 6.6: LG1-LG3,
KPI LK4).

golden_record() trains a temporary untrained character through character_dataset.train_video and
character_dataset.train_stills, with every heavy step faked, in four cases: the video happy path,
a video preprocess that exits 1, the stills happy path and a stills compat-gate reject. It returns
one JSON text holding, per case, the outcome, every fake call (argv, cwd, HF_HOME, generate
kwargs, child spec and step), the training config text, character.json, stdout, stderr and the
sorted file list of the character directory. tests/fixtures/location/character_train_golden.json
is that text as captured at d210c26, before character_dataset.py was refactored:

    python3 tests/test_location_golden.py --write-fixture     (from the workspace root)

LG1 requires the current code to reproduce it byte for byte.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_location_golden.py
Stdlib plus pytest (and PIL, which character_dataset imports). No test reads the real HOME,
renders, trains, runs Z-Image or the editor, contacts a model server or touches port 8178: the
autouse story_env fixture puts HOME, CHARACTER_LIBRARY_DIR, LOCATION_LIBRARY_DIR and
LORA_CATALOG_DIR under tmp_path, golden_record() points them at its own temporary root, and
run_logged, SKILL.generate_video and run_zimage_child are fakes. Every patch inside
golden_record() is a unittest.mock patch, so this module also runs as a script.
"""

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import zipfile
from unittest import mock

import pytest
from PIL import Image

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import character_dataset  # noqa: E402
import character_lib  # noqa: E402
import story_engine_testutil as seu  # noqa: E402

FIXTURE = os.path.join(WS, "tests", "fixtures", "location", "character_train_golden.json")
DESCRIPTOR = "a young woman with long black hair pinned up with jade hairpins wearing a grey kimono"
NOW = "2026-10-29T00:00:00Z"
STAMP_RE = re.compile(r"\d{8}T\d{6}Z")
TWO_MODULE_KEYS = ["layers.0.attention.to_q.lora_A.weight", "layers.0.attention.to_q.lora_B.weight",
                   "layers.0.attention.to_k.lora_A.weight", "layers.0.attention.to_k.lora_B.weight"]


def _untrained(lib):
    """An untrained kyra with a real dataset layout: 25 tiny stills, and captions, 1-frame
    "videos" and manifest items for the 24 kept ones (n 5 is the dropped still); copied from
    tests/test_character_dataset.py's make_character and _untrained."""
    cdir = os.path.join(lib, "kyra")
    os.makedirs(os.path.join(cdir, "lora"), exist_ok=True)
    data = {"schema_version": 1, "name": "kyra", "trigger": "kyrawmn", "class_noun": "woman",
            "referring_phrase": "the woman in grey", "descriptor": DESCRIPTOR, "seed": 0,
            "source": {"type": "seed_image", "path": "/fixtures/seed.png"},
            "strength": None, "status": "untrained", "created_at": "2026-10-06T01:02:03Z",
            "dataset": {"reference": "char_00", "kept": 24, "total": 25, "min_score": 7,
                        "face_height": 0.38,
                        "contact_sheet": os.path.join(cdir, "dataset", "contact_sheet.jpg")},
            "loras": {"video": None, "stills": None}, "stills_skip_reason": None}
    kept_ns = [n for n in range(25) if n != 5]
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


def _safetensors_bytes(keys):
    header = {"__metadata__": {"format": "pt"}}
    for i, key in enumerate(keys):
        header[key] = {"dtype": "F32", "shape": [1], "data_offsets": [4 * i, 4 * i + 4]}
    raw = json.dumps(header).encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw + b"\0" * (4 * len(keys))


def _video_fakes(calls, preprocess_rc):
    """run_logged and SKILL.generate_video fakes (tests/test_character_dataset.py:579-614)."""

    def _run(cmd, log_path, cwd, env, timeout_s):
        calls.append({"fake": "run_logged", "argv": list(cmd), "cwd": cwd,
                      "hf_home": env.get("HF_HOME"), "log": log_path, "timeout_s": timeout_s})
        if cmd[1] == "preprocess":
            out_dir = cmd[cmd.index("-o") + 1]
            videos = cmd[cmd.index("--videos") + 1]
            latent_dir = os.path.join(out_dir, ".precomputed", "latents")
            os.makedirs(latent_dir)
            for i in range(len(os.listdir(videos))):
                open(os.path.join(latent_dir, "l%02d.safetensors" % i), "wb").close()
            return preprocess_rc
        ckpt_dir = os.path.join(os.path.dirname(cmd[cmd.index("--config") + 1]), "out",
                                "checkpoints")
        os.makedirs(ckpt_dir)
        with open(os.path.join(ckpt_dir, character_dataset.VIDEO_FINAL_CKPT), "wb") as f:
            f.write(b"lora")
        return 0

    def _generate(prompt, output_path, **kwargs):
        calls.append({"fake": "generate_video", "prompt": prompt, "output_path": output_path,
                      "kwargs": kwargs})
        with open(output_path, "wb") as f:
            f.write(b"mp4")
        return output_path

    return [(character_dataset, "run_logged", _run),
            (character_dataset.SKILL, "generate_video", _generate)]


def _stills_fakes(calls, injected):
    """run_logged (mflux-train) and run_zimage_child fakes (tests/test_character_dataset.py:
    968-998)."""

    def _run(cmd, log_path, cwd, env, timeout_s):
        calls.append({"fake": "run_logged", "argv": list(cmd), "cwd": cwd,
                      "hf_home": env.get("HF_HOME"), "log": log_path, "timeout_s": timeout_s})
        with open(cmd[cmd.index("--config") + 1]) as f:
            config = json.load(f)
        out = config["checkpoint"]["output_path"]
        zip_path = os.path.join(out, "checkpoints",
                                "%07d_checkpoint.zip" % config["checkpoint"]["save_frequency"])
        os.makedirs(os.path.dirname(zip_path))
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("0002400_adapter.safetensors", _safetensors_bytes(TWO_MODULE_KEYS))
        return 0

    def _child(spec, char_dir, step):
        calls.append({"fake": "run_zimage_child", "spec": spec, "dir": char_dir, "step": step})
        for job in spec["jobs"]:
            Image.new("RGB", (16, 10), (1, 2, 3)).save(job["output_path"])
        return {"jobs": [{"output_path": j["output_path"], "status": "ok", "seconds": 1.0}
                         for j in spec["jobs"]],
                "injected_lora_modules": injected if spec["loras"] else None}

    return [(character_dataset, "run_logged", _run),
            (character_dataset, "run_zimage_child", _child)]


CASES = (
    ("train_video ok", "video", 0, character_dataset.train_video),
    ("train_video preprocess exit 1", "video", 1, character_dataset.train_video),
    ("train_stills ok", "stills", 2, character_dataset.train_stills),
    ("train_stills compat reject", "stills", 1, character_dataset.train_stills),
)


def _case(root, kind, value, train):
    """One case under the fresh directory root: the record dict of spec 6.3 step 4."""
    lib = os.path.join(root, "characters")
    dev = os.path.join(root, "dev-model")
    os.makedirs(dev)
    with open(os.path.join(dev, "transformer-dev.safetensors"), "wb") as f:
        f.write(b"dev")
    test_model = os.path.join(root, "test-model")
    os.makedirs(test_model)
    stub = os.path.join(root, "stub-bin")
    with open(stub, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(stub, 0o755)
    calls = []
    fakes = _video_fakes(calls, value) if kind == "video" else _stills_fakes(calls, value)
    out, err = io.StringIO(), io.StringIO()
    env = {"HOME": os.path.join(root, "home"), "CHARACTER_LIBRARY_DIR": lib,
           "LOCATION_LIBRARY_DIR": os.path.join(root, "locations"),
           "LORA_CATALOG_DIR": os.path.join(root, "loras")}
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.dict(os.environ, env))
        for target, name, replacement in [
                (character_dataset, "TRAIN_MODEL_DIR", dev),
                (character_dataset, "TEST_MODEL_DIR", test_model),
                (character_dataset.SKILL, "LTX2_MLX_BIN", stub),
                (character_dataset, "MFLUX_TRAIN", stub),
                (character_lib, "utc_now", lambda: NOW)] + fakes:
            stack.enter_context(mock.patch.object(target, name, replacement))
        data = _untrained(lib)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            outcome = train(data)
    char_dir = os.path.join(lib, "kyra")
    config = None
    for rel in (("train", "video", "train.yaml"), ("train", "stills", "train.json")):
        path = os.path.join(char_dir, *rel)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                config = f.read()
    with open(os.path.join(char_dir, "character.json"), encoding="utf-8") as f:
        character_json = f.read()
    files = []
    for dirpath, _dirnames, filenames in os.walk(char_dir):
        files += [os.path.relpath(os.path.join(dirpath, n), char_dir) for n in filenames]
    return {"outcome": outcome, "calls": calls, "config": config,
            "character_json": character_json, "stdout": out.getvalue(), "stderr": err.getvalue(),
            "files": sorted(files)}


def golden_record():
    """The golden JSON text of spec 6.3 (ends with one newline)."""
    top = tempfile.mkdtemp(prefix="location-golden-")
    try:
        record = {}
        for k, (label, kind, value, train) in enumerate(CASES, start=1):
            root = os.path.join(top, "case%d" % k)
            os.makedirs(root)
            record[label] = _case(root, kind, value, train)
        text = json.dumps(record, indent=2, sort_keys=True)
    finally:
        shutil.rmtree(top, ignore_errors=True)
    replacements = [(os.path.realpath(top), "<TMP>"), (top, "<TMP>"),
                    (character_dataset.SKILL.LTX2_MLX_HF_HOME, "<LTX2_MLX_HF_HOME>"),
                    (character_dataset.SKILL.LTX2_MLX_DIR, "<LTX2_MLX_DIR>"),
                    (character_dataset.MFLUX_HF_HOME, "<MFLUX_HF_HOME>")]
    for value, token in sorted(replacements, key=lambda item: -len(item[0])):
        text = text.replace(value, token)
    return STAMP_RE.sub("<STAMP>", text) + "\n"


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    """HOME and every library directory under tmp_path for each test (spec 6.2)."""
    env = seu.set_story_env(monkeypatch, tmp_path)
    env["locations"] = os.path.join(str(tmp_path), "locations")
    monkeypatch.setenv("LOCATION_LIBRARY_DIR", env["locations"])
    return env


def test_lg1_the_character_golden_record_is_unchanged():
    with open(FIXTURE, encoding="utf-8") as f:
        expected = f.read()
    assert golden_record() == expected
    assert hashlib.sha256(expected.encode("utf-8")).hexdigest() == hashlib.sha256(
        golden_record().encode("utf-8")).hexdigest()


def main(argv):
    if argv != ["--write-fixture"]:
        print("usage: python3 tests/test_location_golden.py --write-fixture", file=sys.stderr)
        return 2
    text = golden_record()
    os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
    with open(FIXTURE, "w", encoding="utf-8") as f:
        f.write(text)
    print("wrote %s (%d bytes, sha256 %s)" % (FIXTURE, len(text.encode("utf-8")),
                                              hashlib.sha256(text.encode("utf-8")).hexdigest()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
