"""Tests for the seed generator's movie-ui side (docs/superpowers/specs/2026-11-02-seed-generator-
design.md, Section 9: SGT17-SGT34, with the plan's Review Focus pins 1, 2 and 5): the pure module
movie_ui_seedgen, the movie_ui_lib hooks (job policy, argv, probe, progress), the six
/api/seeds/ routes, the seed_edit capability, the job summary key and the static page.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedgen.py

Rules (spec Section 9):
- The HTTP tests use the env fixture (like tests/test_movie_ui_seedfolder.py's): mt.set_home,
  mt.make_stub_workspace and the in-test mt.Running server on 127.0.0.1, with
  CHARACTER_LIBRARY_DIR removed unless a test sets it.
- Every test that touches the environment sets HOME under tmp_path, removes HF_HUB_CACHE and
  every SEED_EDIT_* variable, and sets HF_HOME and Z_IMAGE_HF_HOME under tmp_path.
- The workspace's bin/seed-edit is the stub written by stub_seed_edit(ws, models, ...); it prints
  json.dumps(models) for --probe. srv.seed_free_gib is replaced by a stub. Uploads go through
  POST /api/uploads with magic-number bytes (mt.PNG, mt.JPEG, mt.WEBP plus a suffix).
- No test uses the real HOME, loads a model, runs bin/seed-edit-setup, or contacts a server other
  than the in-test 127.0.0.1 one. None touches port 8177 or 8178. The VLM lifecycle is off
  (conftest.py). No test dispatches a job (the HTTP tests only queue).
Stdlib plus pytest.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

import pytest

import movie_ui_testutil as mt
import movie_ui_lib as lib
import movie_ui_seedgen as seedgen
import movie_ui_server as srv

WS = mt.WS
UP = "a" * 64 + ".png"
RUN = "se-20261102-141500-a1b2"


# --- SGT17 (SG33-SG37): the pure module -------------------------------------------------------------

def _req(**overrides):
    body = {"ws": "/abs/ws", "source": {"upload_id": UP}, "prompt": "make it night", "model": "zimage",
            "strength": 0.45, "candidates": 2, "seed": 7}
    body.update(overrides)
    return body


SOURCE_MSG = "source must be {upload_id}, {run, n} or {character, still}"
REQUEST_CASES = [
    (_req(prompt=5), "prompt is required"),
    (_req(prompt="   "), "prompt is required"),
    (_req(prompt="x" * 2001), "prompt is longer than 2000 characters"),
    (_req(prompt="a\x00b"), "prompt contains invalid characters"),
    (_req(prompt="a\ud800b"), "prompt contains invalid characters"),
    (_req(prompt="  -x"), "prompt must not start with '-'"),
    (_req(model="flux"), "model must be zimage or qwen"),
    (_req(model=None), "model must be zimage or qwen"),
    (_req(model="qwen", strength=0.5), "strength is only for zimage"),
    (_req(strength=0.05), "strength must be a number from 0.10 to 0.90"),
    (_req(strength=0.95), "strength must be a number from 0.10 to 0.90"),
    (_req(strength="0.5"), "strength must be a number from 0.10 to 0.90"),
    (_req(strength=True), "strength must be a number from 0.10 to 0.90"),
    (_req(candidates=0), "candidates must be an integer from 1 to 4"),
    (_req(candidates=5), "candidates must be an integer from 1 to 4"),
    (_req(candidates=2.0), "candidates must be an integer from 1 to 4"),
    (_req(candidates="2"), "candidates must be an integer from 1 to 4"),
    (_req(seed=-1), "seed must be an integer from 0 to 2147483647"),
    (_req(seed=2147483648), "seed must be an integer from 0 to 2147483647"),
    (_req(seed="7"), "seed must be an integer from 0 to 2147483647"),
    (_req(source="x"), SOURCE_MSG),
    (_req(source={}), SOURCE_MSG),
    (_req(source={"upload_id": 5}), SOURCE_MSG),
    (_req(source={"upload_id": UP, "run": RUN}), SOURCE_MSG),
    (_req(source={"run": RUN, "n": "1"}), SOURCE_MSG),
    (_req(source={"run": RUN, "n": True}), SOURCE_MSG),
    (_req(source={"character": "kyra"}), SOURCE_MSG),
    (_req(source={"upload_id": "x.png"}), "source upload x.png not found"),
    (_req(source={"run": "junk", "n": 1}), "unknown source run junk"),
    (_req(source={"run": RUN, "n": 5}), "source run %s has no ok candidate 5" % RUN),
    (_req(source={"run": RUN, "n": 0}), "source run %s has no ok candidate 0" % RUN),
    (_req(source={"character": "Kyra", "still": "char_01.png"}), "unknown character still Kyra/char_01.png"),
    (_req(source={"character": "kyra", "still": "char_1.png"}), "unknown character still kyra/char_1.png"),
]


@pytest.mark.parametrize("body,message", REQUEST_CASES, ids=["case%d" % (i + 1) for i in range(len(REQUEST_CASES))])
def test_sgt17_validate_run_request_refusals(body, message):
    assert seedgen.validate_run_request(body) == (None, message)


def test_sgt17_validate_run_request_order_and_defaults():
    assert seedgen.validate_run_request(_req(prompt="", model="flux")) == (None, "prompt is required")
    assert seedgen.validate_run_request(_req(model="flux", seed=-1)) == (None, "model must be zimage or qwen")
    assert seedgen.validate_run_request(_req(candidates=0, source="x")) == (
        None, "candidates must be an integer from 1 to 4")
    clean, error = seedgen.validate_run_request(_req(extra=1))
    assert error is None
    assert clean == {"prompt": "make it night", "model": "zimage", "strength": 0.45, "candidates": 2, "seed": 7,
                     "source": {"kind": "upload", "upload_id": UP}}
    bare = {"prompt": " a quiet street at dusk ", "model": "zimage", "source": {"run": RUN, "n": 3}}
    clean, error = seedgen.validate_run_request(bare)
    assert error is None
    assert clean == {"prompt": " a quiet street at dusk ", "model": "zimage", "strength": 0.45,
                     "candidates": 4, "seed": None, "source": {"kind": "run", "run": RUN, "n": 3}}
    assert isinstance(seedgen.validate_run_request(_req(strength=1 / 2))[0]["strength"], float)
    assert seedgen.validate_run_request(_req(strength=None, candidates=None, seed=None))[0]["strength"] == 0.45
    clean, error = seedgen.validate_run_request(_req(model="qwen", strength=None,
                                                     source={"character": "kyra", "still": "char_05.png"}))
    assert error is None and clean["strength"] is None
    assert clean["source"] == {"kind": "character", "character": "kyra", "still": "char_05.png"}
    assert seedgen.validate_run_request(_req(prompt="x" * 2000))[1] is None


def test_sgt17_folders_run_ids_and_keep_names():
    for name in ("heroes", "a.b-c_d", "A" * 64, "9lives"):
        assert seedgen.valid_folder(name) is True, name
    for name in ("", "runs", "Runs", "RUNS", "a..b", "-x", ".x", "A" * 65, "a/b", 5, None):
        assert seedgen.valid_folder(name) is False, name
    assert seedgen.FOLDER_MSG == ("folder must be 1 to 64 letters, digits, '.', '_' or '-', start with a letter "
                                  "or digit, contain no '..' and not be 'runs'")
    assert seedgen.RUN_ID_RE.fullmatch(seedgen.new_run_id())
    assert seedgen.keep_name(RUN, 2, 1) == RUN + "-02.png"
    assert seedgen.keep_name(RUN, 2, 3) == RUN + "-02-3.png"


def test_sgt17_capability_and_availability():
    ok_z = {"ok": True, "reason": None, "backend": "zimage"}
    no_z = {"ok": False, "reason": "torch not importable by /py", "backend": None}
    ok_q = {"ok": True, "reason": None, "backend": "mflux-q4"}
    no_q = {"ok": False, "reason": "diffusers bf16: x; mflux q4: y", "backend": None}
    both = {"zimage": ok_z, "qwen": ok_q}
    assert seedgen.capability(both, None, "T") == {"ok": True, "reason": None, "checked": "T", "models": both}
    partial = {"zimage": ok_z, "qwen": no_q}
    assert seedgen.capability(partial, None, "T") == {"ok": True, "reason": None, "checked": "T", "models": partial}
    none_ok = {"zimage": no_z, "qwen": no_q}
    assert seedgen.capability(none_ok, None, "T") == {
        "ok": False, "reason": "Z-Image: torch not importable by /py; Qwen-Image-Edit: diffusers bf16: x; mflux q4: y",
        "checked": "T", "models": none_ok}
    assert seedgen.capability(None, "bin/seed-edit --probe exited 1: boom", "T") == {
        "ok": False, "reason": "bin/seed-edit --probe exited 1: boom", "checked": "T", "models": None}
    assert seedgen.availability_error(both, None, "qwen") is None
    assert seedgen.availability_error(partial, None, "zimage") is None
    assert seedgen.availability_error(partial, None, "qwen") == (
        "Qwen-Image-Edit is unavailable: diffusers bf16: x; mflux q4: y")
    assert seedgen.availability_error(none_ok, None, "zimage") == "Z-Image is unavailable: torch not importable by /py"
    assert seedgen.availability_error(None, "boom", "zimage") == "cannot check the seed models: boom"


def test_sgt17_the_module_imports():
    with open(os.path.join(WS, "movie_ui_seedgen.py"), encoding="utf-8") as f:
        source = f.read()
    assert sorted(re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M)) == [
        "movie_ui_lib", "re", "secrets", "time"]
