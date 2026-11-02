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


# --- The probe stub and the environment (spec 9 rules) -----------------------------------------------

OK_MODELS = {"zimage": {"ok": True, "reason": None, "backend": "zimage"},
             "qwen": {"ok": True, "reason": None, "backend": "mflux-q4"}}


def stub_seed_edit(ws, models, exit=0, stderr="", sleep=0):
    """<ws>/bin/seed-edit as a stub: it sleeps `sleep` s, prints json.dumps(models) (models itself
    when it is a str) for --probe, writes stderr and exits with `exit`. Returns its path."""
    out = models if isinstance(models, str) else json.dumps(models)
    path = os.path.join(ws, "bin", "seed-edit")
    with open(path, "w", encoding="utf-8") as f:
        f.write("#!%s\nimport sys\nimport time\ntime.sleep(%r)\nif sys.argv[1:] == ['--probe']:\n"
                "    sys.stdout.write(%r + '\\n')\nsys.stderr.write(%r)\nsys.exit(%d)\n"
                % (sys.executable, sleep, out, stderr, exit))
    os.chmod(path, 0o755)
    return path


def clean_env(monkeypatch, tmp_path):
    """Spec 9: no HF_HUB_CACHE and no SEED_EDIT_* variable; HF_HOME and Z_IMAGE_HF_HOME under tmp_path."""
    for key in list(os.environ):
        if key.startswith("SEED_EDIT_"):
            monkeypatch.delenv(key)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", os.path.join(str(tmp_path), "hf"))
    monkeypatch.setenv("Z_IMAGE_HF_HOME", os.path.join(str(tmp_path), "zi"))


# --- SGT18 (SG28, SG29, SG31, SG32): job policy, argv and progress ------------------------------------

def test_sgt18_policy_argv_and_progress(monkeypatch, tmp_path):
    state = mt.set_home(monkeypatch, tmp_path)
    clean_env(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    assert lib.job_vlm("seed-edit", {}, ws, None) == "forbidden"
    run_dir = os.path.join(ws, "generated", "seeds", "runs", RUN)
    fields = {"ws": ws, "run": RUN, "source_file": "source.png", "prompt": "make it night", "model": "zimage",
              "strength": 0.3, "candidates": 3, "seed": 7, "source": {"kind": "upload", "upload_id": UP}}
    assert lib.seed_edit_argv(fields, ws) == [
        sys.executable, os.path.join(ws, "bin", "seed-edit"), "--source", os.path.join(run_dir, "source.png"),
        "--prompt", "make it night", "--model", "zimage", "--strength", "0.3", "--candidates", "3",
        "--seed", "7", "--run-dir", run_dir]
    qwen = dict(fields, model="qwen", strength=None, source_file="source.jpg")
    assert lib.seed_edit_argv(qwen, ws, py="/py") == [
        "/py", os.path.join(ws, "bin", "seed-edit"), "--source", os.path.join(run_dir, "source.jpg"),
        "--prompt", "make it night", "--model", "qwen", "--candidates", "3", "--seed", "7", "--run-dir", run_dir]
    job = {"id": "20261102-141500-a1b2", "workspace": ws, "story_id": None}
    parser = lib.ProgressParser("seed-edit", dict(fields, candidates=4))
    assert parser.snapshot(job, None, state) == {
        "kind": "seed-edit", "elapsed_s": None, "last_line": "", "face_problem": False,
        "candidates": {"total": 4, "done": 0, "ok": 0, "blocked": 0, "failed": 0, "current": 1}}
    lines = b"seed-edit: backend zimage (Z-Image img2img)\ncandidate 1/4 ok 1.0s\ncandidate 2/4 blocked 2.0s\n"
    parser.feed(lines)
    snap = parser.snapshot(job, None, state)
    assert snap["candidates"] == {"total": 4, "done": 2, "ok": 1, "blocked": 1, "failed": 0, "current": 3}
    assert snap["last_line"] == "candidate 2/4 blocked 2.0s"
    parser.feed(b"panel 3 ok: x\ncandidate 3/4 failed\ncandidate 4/4 failed\n")
    assert parser.snapshot(job, None, state)["candidates"] == {
        "total": 4, "done": 4, "ok": 1, "blocked": 1, "failed": 2, "current": None}
    assert parser.panels == {}
    bare = lib.ProgressParser("seed-edit", {"candidates": "4"})
    assert bare.snapshot(job, None, state)["candidates"] == {
        "total": None, "done": 0, "ok": 0, "blocked": 0, "failed": 0, "current": None}
    other = lib.ProgressParser("character-create", {"name": "kyra"})
    other.feed(lines)
    assert set(other.snapshot(job, None, state)) == {"kind", "elapsed_s", "last_line", "face_problem"}
    assert other.candidates == {}


# --- SGT19 (SG30): lib.seed_edit_check ---------------------------------------------------------------

def test_sgt19_seed_edit_check(monkeypatch, tmp_path):
    mt.set_home(monkeypatch, tmp_path)
    clean_env(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    stub_seed_edit(ws, OK_MODELS)
    assert lib.seed_edit_check(ws) == (OK_MODELS, None)
    extra = {"zimage": dict(OK_MODELS["zimage"], note=1), "qwen": OK_MODELS["qwen"], "other": 1}
    stub_seed_edit(ws, extra)
    assert lib.seed_edit_check(ws) == (OK_MODELS, None)
    stub_seed_edit(ws, OK_MODELS, exit=3, stderr="first\nnope\n")
    assert lib.seed_edit_check(ws) == (None, "bin/seed-edit --probe exited 3: nope")
    stub_seed_edit(ws, OK_MODELS, exit=3)
    assert lib.seed_edit_check(ws) == (None, "bin/seed-edit --probe exited 3: -")
    bad = [
        "not json",
        json.dumps({"zimage": dict(OK_MODELS["zimage"], ok="yes"), "qwen": OK_MODELS["qwen"]}),
        json.dumps({"zimage": OK_MODELS["zimage"]}),
        json.dumps([OK_MODELS]),
        json.dumps({"zimage": {"ok": True, "backend": "zimage"}, "qwen": OK_MODELS["qwen"]}),
        json.dumps({"zimage": dict(OK_MODELS["zimage"], reason=5), "qwen": OK_MODELS["qwen"]}),
        json.dumps({"zimage": OK_MODELS["zimage"], "qwen": dict(OK_MODELS["qwen"], backend=["x"])}),
    ]
    for printed in bad:
        stub_seed_edit(ws, printed)
        assert lib.seed_edit_check(ws) == (None, "bin/seed-edit --probe printed unparsable output"), printed
    monkeypatch.setattr(lib, "LIGHT_TIMEOUT", 1)
    stub_seed_edit(ws, OK_MODELS, sleep=2)
    assert lib.seed_edit_check(ws) == (None, "bin/seed-edit --probe timed out after 1 s")


# --- The HTTP tests: fixture and helpers (spec 9 rules) -----------------------------------------------

TIME_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
VIEW_KEYS = {"run", "dir", "created", "state", "prompt", "model", "backend", "strength", "seed", "size",
             "source_size", "source_origin", "error", "source", "candidates", "job"}
RA, RB = "se-20261101-100000-000a", "se-20261101-100000-000b"


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "0")
    monkeypatch.delenv("CHARACTER_LIBRARY_DIR", raising=False)
    state = mt.set_home(monkeypatch, tmp_path)
    clean_env(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    stub_seed_edit(ws, OK_MODELS)
    monkeypatch.setattr(srv, "seed_free_gib", lambda path: 100.0)
    running = mt.Running(state)
    yield {"state": state, "ws": ws, "tmp": str(tmp_path), "srv": running, "mp": monkeypatch}
    running.close()
    mt.kill_everything(state)


def _upload(s, data=mt.PNG, ctype="image/png"):
    status, _h, payload = mt.api(s, "POST", "/api/uploads", raw=data, headers={"Content-Type": ctype})
    assert status == 201, payload
    return payload["upload_id"]


def _body(ws, source, **overrides):
    body = {"ws": ws, "source": source, "prompt": "make it night", "model": "zimage", "strength": 0.45,
            "candidates": 2, "seed": 7}
    body.update(overrides)
    return body


def _create(s, body):
    return mt.api(s, "POST", "/api/seeds/runs", body=body)


def _runs_root(ws):
    return os.path.join(ws, "generated", "seeds", "runs")


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _record(run_dir):
    return json.loads(_read(os.path.join(run_dir, "run.json")).decode("utf-8"))


def _nothing_created(env):
    return (not os.path.exists(os.path.join(env["ws"], "generated", "seeds")) and lib.read_queue(env["state"]) == []
            and os.listdir(os.path.join(env["state"], "jobs")) == [])


def make_run(ws, run, cands, state="done", job=None, prompt="make it night", files=None):
    """A hand-made run under <ws>/generated/seeds/runs: source.png, run.json with one candidate per
    status in cands, and cand_NN.png (mt.PNG + bytes([n])) for every ok candidate, or for the n in
    files when files is given. Returns the run directory."""
    run_dir = os.path.join(_runs_root(ws), run)
    os.makedirs(run_dir)
    with open(os.path.join(run_dir, "source.png"), "wb") as f:
        f.write(mt.PNG + b"source")
    record = {"schema": "seed-edit.run.v1", "run": run, "created": "2026-11-02T14:15:00Z", "state": state,
              "prompt": prompt, "model": "zimage", "backend": "zimage", "strength": 0.45, "seed": 7,
              "size": {"width": 1024, "height": 672}, "source_size": {"width": 1536, "height": 1024},
              "source": "source.png", "source_origin": None, "job": job, "error": None,
              "candidates": [{"n": i + 1, "seed": 8 + i, "status": st,
                              "seconds": 1.0 if st in ("ok", "blocked") else None} for i, st in enumerate(cands)]}
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as f:
        json.dump(record, f)
    for i, st in enumerate(cands):
        if (files is None and st == "ok") or (files is not None and i + 1 in files):
            with open(os.path.join(run_dir, "cand_%02d.png" % (i + 1)), "wb") as f:
                f.write(mt.PNG + bytes([i + 1]))
    return run_dir


def set_status(run_dir, n, status):
    record = _record(run_dir)
    record["candidates"][n - 1]["status"] = status
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as f:
        json.dump(record, f)


def seed_job(state, ws, run):
    """A queued seed-edit job naming run (as the server would create it)."""
    job_id = lib.new_job_id(state)
    lib.create_job(state, job_id, "seed-edit", ws, None, None, ["true"], {"run": run, "candidates": 1})
    return job_id


# --- SGT20 (SG40): the routes ------------------------------------------------------------------------

SEED_ROUTES = [
    ("POST", r"/api/seeds/runs", "h_seed_run_create", "/api/seeds/runs"),
    ("GET", r"/api/seeds/runs", "h_seed_runs", "/api/seeds/runs"),
    ("GET", r"/api/seeds/runs/(se-[0-9]{8}-[0-9]{6}-[0-9a-f]{4})", "h_seed_run", "/api/seeds/runs/" + RUN),
    ("POST", r"/api/seeds/runs/(se-[0-9]{8}-[0-9]{6}-[0-9a-f]{4})/keep", "h_seed_keep",
     "/api/seeds/runs/" + RUN + "/keep"),
    ("POST", r"/api/seeds/runs/(se-[0-9]{8}-[0-9]{6}-[0-9a-f]{4})/use", "h_seed_use", "/api/seeds/runs/" + RUN + "/use"),
    ("GET", r"/api/seeds/folders", "h_seed_folders", "/api/seeds/folders"),
]


def test_sgt20_the_routes(env):
    s = env["srv"]
    routes = list(srv.ROUTES)
    i = routes.index(("POST", r"/api/uploads", "h_upload", "/api/uploads"))
    assert routes[i + 1:i + 7] == SEED_ROUTES
    assert len(srv.ROUTES) == 63
    for method, regex, name, sample in SEED_ROUTES:
        assert re.fullmatch(regex, sample), sample
        assert getattr(srv.MovieUIHandler, name) is getattr(srv, "_" + name), name
        for token in (None, "wrong-token"):
            assert mt.api(s, method, sample, body={} if method == "POST" else None, token=token)[::2] == (
                401, {"error": "missing or invalid token"}), (sample, token)
    assert mt.api(s, "DELETE", "/api/seeds/runs")[::2] == (405, {"error": "method not allowed"})
    assert mt.api(s, "GET", "/api/seeds/runs/se-junk?ws=" + env["ws"])[::2] == (404, {"error": "not found"})


# --- SGT21 (SG33, SG44, SG45): every 400, and nothing created ------------------------------------------

def test_sgt21_bad_requests_get_400_and_create_nothing(env):
    s, ws, tmp = env["srv"], env["ws"], env["tmp"]
    up = _upload(s)
    good = _body(ws, {"upload_id": up})
    no_ws = dict(good)
    del no_ws["ws"]
    cases = [(no_ws, "missing ws"), (dict(good, ws="relative/ws"), "ws must be an absolute path"),
             (dict(good, ws=tmp), "not a harness workspace (no bin/ltx-movie): %s" % tmp)]
    cases += [(dict(body, ws=ws), message) for body, message in REQUEST_CASES if "\ud800" not in str(body["prompt"])]
    cases += [(_body(ws, {"upload_id": UP}), "source upload %s not found" % UP),
              (_body(ws, {"run": RUN, "n": 1}), "unknown source run %s" % RUN),
              (_body(ws, {"character": "kyra", "still": "char_01.png"}), "unknown character still kyra/char_01.png")]
    for body, message in cases:
        assert _create(s, body)[::2] == (400, {"error": message}), message
    assert _nothing_created(env)


# --- SGT22 (SG37, SG44, SG45): every 409, and nothing created ------------------------------------------

def test_sgt22_conflicts_get_409_and_create_nothing(env):
    s, ws = env["srv"], env["ws"]
    up = _upload(s)
    reason = "diffusers bf16: needs a host with at least 64 GiB of memory (this host has 48.0 GiB); mflux q4: x"
    stub_seed_edit(ws, dict(OK_MODELS, qwen={"ok": False, "reason": reason, "backend": None}))
    assert _create(s, _body(ws, {"upload_id": up}, model="qwen", strength=None))[::2] == (
        409, {"error": "Qwen-Image-Edit is unavailable: " + reason})
    stub_seed_edit(ws, dict(OK_MODELS, zimage={"ok": False, "reason": "torch not importable by /py", "backend": None}))
    assert _create(s, _body(ws, {"upload_id": up}))[::2] == (
        409, {"error": "Z-Image is unavailable: torch not importable by /py"})
    stub_seed_edit(ws, OK_MODELS, exit=1, stderr="Traceback\nboom\n")
    assert _create(s, _body(ws, {"upload_id": up}))[::2] == (
        409, {"error": "cannot check the seed models: bin/seed-edit --probe exited 1: boom"})
    stub_seed_edit(ws, OK_MODELS)
    asked = []
    env["mp"].setattr(srv, "seed_free_gib", lambda path: asked.append(path) or 1.0)
    generated = os.path.join(ws, "generated")
    assert _create(s, _body(ws, {"upload_id": up}))[::2] == (
        409, {"error": "less than 2 GiB free on the disk holding %s (1.0 GiB free)" % generated})
    assert asked == [generated]
    assert _nothing_created(env)


# --- SGT23 (SG44, SG46, SG53): queue a run from an upload ----------------------------------------------

def test_sgt23_queue_a_run_from_an_upload(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    up = _upload(s, mt.PNG + b"src")
    status, _h, data = _create(s, _body(ws, {"upload_id": up}))
    assert status == 201, data
    view = data["run"]
    run = view["run"]
    assert seedgen.RUN_ID_RE.fullmatch(run)
    run_dir = os.path.join(_runs_root(ws), run)
    assert _read(os.path.join(run_dir, "source.png")) == mt.PNG + b"src"
    record = _record(run_dir)
    job_id = record["job"]
    assert lib.JOB_ID_RE.fullmatch(job_id) and TIME_RE.fullmatch(record["created"])
    assert dict(record, created=None) == {
        "schema": "seed-edit.run.v1", "run": run, "created": None, "state": "queued", "prompt": "make it night",
        "model": "zimage", "backend": None, "strength": 0.45, "seed": 7, "size": None, "source_size": None,
        "source": "source.png", "source_origin": {"kind": "upload", "upload_id": up}, "job": job_id, "error": None,
        "candidates": [{"n": 1, "seed": 8, "status": "pending", "seconds": None},
                       {"n": 2, "seed": 9, "status": "pending", "seconds": None}]}
    job = lib.read_job(lib.job_dir(state, job_id))
    assert (job["kind"], job["story_id"], job["character"], job["vlm"]) == ("seed-edit", None, None, "forbidden")
    assert job["fields"] == {"ws": ws, "run": run, "source_file": "source.png", "prompt": "make it night",
                             "model": "zimage", "strength": 0.45, "candidates": 2, "seed": 7,
                             "source": {"kind": "upload", "upload_id": up}}
    assert job["argv"] == lib.seed_edit_argv(job["fields"], ws)
    assert lib.read_queue(state) == [job_id]
    assert set(view) == VIEW_KEYS
    assert (view["state"], view["dir"], view["source"]) == ("queued", run_dir, os.path.join(run_dir, "source.png"))
    assert view["candidates"] == [{"n": 1, "seed": 8, "status": "pending", "seconds": None, "path": None},
                                  {"n": 2, "seed": 9, "status": "pending", "seconds": None, "path": None}]
    assert (view["job"]["id"], view["job"]["seed_run"], view["job"]["queue_position"]) == (job_id, run, 1)
    status, _h, data = _create(s, _body(ws, {"upload_id": up}, seed=None, candidates=None, strength=None))
    assert status == 201, data
    seed = data["run"]["seed"]
    assert 0 <= seed <= 2147483647 and data["run"]["strength"] == 0.45
    assert [c["seed"] for c in data["run"]["candidates"]] == [seed + 1, seed + 2, seed + 3, seed + 4]
    status, _h, data = _create(s, _body(ws, {"upload_id": up}, seed=0, model="qwen", strength=None, candidates=1))
    assert status == 201, data
    assert (data["run"]["seed"], data["run"]["strength"]) == (0, None)
    argv = lib.read_job(lib.job_dir(state, data["run"]["job"]["id"]))["argv"]
    assert "--strength" not in argv and argv[argv.index("--seed") + 1] == "0"


# --- SGT24 (SG44): a candidate of a finished run as the source -----------------------------------------

def test_sgt24_a_candidate_as_the_source(env):
    s, ws = env["srv"], env["ws"]
    run_dir = make_run(ws, RA, ["ok", "ok"])
    status, _h, data = _create(s, _body(ws, {"run": RA, "n": 2}))
    assert status == 201, data
    assert _read(os.path.join(data["run"]["dir"], "source.png")) == _read(os.path.join(run_dir, "cand_02.png"))
    assert data["run"]["source_origin"] == {"kind": "run", "run": RA, "n": 2}
    set_status(run_dir, 2, "blocked")
    no_ok = (400, {"error": "source run %s has no ok candidate 2" % RA})
    assert _create(s, _body(ws, {"run": RA, "n": 2}))[::2] == no_ok
    set_status(run_dir, 2, "ok")
    os.remove(os.path.join(run_dir, "cand_02.png"))
    assert _create(s, _body(ws, {"run": RA, "n": 2}))[::2] == no_ok
    assert _create(s, _body(ws, {"run": RA, "n": 3}))[::2] == (400, {"error": "source run %s has no ok candidate 3" % RA})
    assert _create(s, _body(ws, {"run": RB, "n": 1}))[::2] == (400, {"error": "unknown source run %s" % RB})
    assert len(os.listdir(_runs_root(ws))) == 2


# --- SGT25 (SG44): a character still as the source -----------------------------------------------------

def test_sgt25_a_character_still_as_the_source(env):
    s, ws, tmp, mp = env["srv"], env["ws"], env["tmp"], env["mp"]
    library = os.path.join(tmp, "lib")
    stills = os.path.join(library, "kyra", "dataset", "stills")
    os.makedirs(stills)
    with open(os.path.join(stills, "char_05.png"), "wb") as f:
        f.write(mt.PNG + b"kyra5")
    with open(os.path.join(tmp, "outside.png"), "wb") as f:
        f.write(mt.PNG + b"outside")
    os.symlink(os.path.join(tmp, "outside.png"), os.path.join(stills, "char_06.png"))
    mp.setenv("CHARACTER_LIBRARY_DIR", library)
    status, _h, data = _create(s, _body(ws, {"character": "kyra", "still": "char_05.png"}))
    assert status == 201, data
    assert _read(data["run"]["source"]) == mt.PNG + b"kyra5"
    assert data["run"]["source_origin"] == {"kind": "character", "character": "kyra", "still": "char_05.png"}
    for still in ("char_07.png", "char_06.png", "char_5.png"):
        assert _create(s, _body(ws, {"character": "kyra", "still": still}))[::2] == (
            400, {"error": "unknown character still kyra/%s" % still})
    mp.delenv("CHARACTER_LIBRARY_DIR")
    assert _create(s, _body(ws, {"character": "kyra", "still": "char_05.png"}))[::2] == (
        400, {"error": "unknown character still kyra/char_05.png"})
    own = os.path.join(ws, "generated", "characters", "kyra", "dataset", "stills")
    os.makedirs(own)
    with open(os.path.join(own, "char_05.png"), "wb") as f:
        f.write(mt.PNG + b"own5")
    status, _h, data = _create(s, _body(ws, {"character": "kyra", "still": "char_05.png"}))
    assert status == 201 and _read(data["run"]["source"]) == mt.PNG + b"own5"


# --- SGT26 (SG43, SG47): the runs list ------------------------------------------------------------------

def test_sgt26_the_runs_list(env):
    s, ws, state, tmp = env["srv"], env["ws"], env["state"], env["tmp"]
    assert mt.api(s, "GET", "/api/seeds/runs?ws=" + ws)[::2] == (200, {"runs": []})
    r1, r2, r3 = ("se-20261101-100000-000%d" % i for i in (1, 2, 3))
    d1 = make_run(ws, r1, ["ok", "blocked", "ok"], files=[1])
    make_run(ws, r2, ["pending", "pending"], state="queued", job=seed_job(state, ws, r2), prompt="second")
    make_run(ws, r3, ["pending"], state="running", job="20261101-000000-dead", prompt="third")
    os.makedirs(os.path.join(_runs_root(ws), "junk"))
    os.makedirs(os.path.join(_runs_root(ws), "se-20261101-100000-0004"))
    outside = make_run(os.path.join(tmp, "elsewhere"), "se-20261101-100000-0005", ["ok"])
    os.symlink(outside, os.path.join(_runs_root(ws), "se-20261101-100000-0005"))
    status, _h, data = mt.api(s, "GET", "/api/seeds/runs?ws=" + ws)
    assert status == 200
    runs = data["runs"]
    assert [r["run"] for r in runs] == [r3, r2, r1]
    assert all(set(r) == {"run", "created", "state", "prompt", "model", "backend", "count", "ok", "thumbs"}
               for r in runs)
    assert [(r["state"], r["prompt"], r["count"], r["ok"], r["thumbs"]) for r in runs[:2]] == [
        ("unknown", "third", 1, 0, []), ("queued", "second", 2, 0, [])]
    assert runs[2] == {"run": r1, "created": "2026-11-02T14:15:00Z", "state": "done", "prompt": "make it night",
                       "model": "zimage", "backend": "zimage", "count": 3, "ok": 2,
                       "thumbs": [os.path.join(d1, "cand_01.png")]}
    for i in range(201):
        make_run(ws, "se-20261103-%06d-0000" % i, [])
    runs = mt.api(s, "GET", "/api/seeds/runs?ws=" + ws)[2]["runs"]
    assert len(runs) == 200
    assert (runs[0]["run"], runs[-1]["run"]) == ("se-20261103-000200-0000", "se-20261103-000001-0000")


# --- SGT27 (SG42, SG43, SG48): one run's view ----------------------------------------------------------

def test_sgt27_the_run_view(env):
    s, ws, state, tmp = env["srv"], env["ws"], env["state"], env["tmp"]
    run_dir = make_run(ws, RA, ["ok", "blocked", "ok", "failed"], files=[1])
    status, _h, view = mt.api(s, "GET", "/api/seeds/runs/%s?ws=%s" % (RA, ws))
    assert status == 200 and set(view) == VIEW_KEYS
    assert view == {
        "run": RA, "dir": run_dir, "created": "2026-11-02T14:15:00Z", "state": "done", "prompt": "make it night",
        "model": "zimage", "backend": "zimage", "strength": 0.45, "seed": 7, "size": {"width": 1024, "height": 672},
        "source_size": {"width": 1536, "height": 1024}, "source_origin": None, "error": None,
        "source": os.path.join(run_dir, "source.png"),
        "candidates": [{"n": 1, "seed": 8, "status": "ok", "seconds": 1.0, "path": os.path.join(run_dir, "cand_01.png")},
                       {"n": 2, "seed": 9, "status": "blocked", "seconds": 1.0, "path": None},
                       {"n": 3, "seed": 10, "status": "ok", "seconds": 1.0, "path": None},
                       {"n": 4, "seed": 11, "status": "failed", "seconds": None, "path": None}],
        "job": None}
    job_id = seed_job(state, ws, RB)
    make_run(ws, RB, ["pending"], state="queued", job=job_id)
    view = mt.api(s, "GET", "/api/seeds/runs/%s?ws=%s" % (RB, ws))[2]
    assert (view["state"], view["job"]["state"], view["job"]["seed_run"]) == ("queued", "queued", RB)
    assert lib.cancel_job(state, job_id) == "cancelled"
    view = mt.api(s, "GET", "/api/seeds/runs/%s?ws=%s" % (RB, ws))[2]
    assert (view["state"], view["job"]["id"], view["job"]["state"]) == ("cancelled", job_id, "cancelled")
    missing = "se-20261101-999999-ffff"
    assert mt.api(s, "GET", "/api/seeds/runs/%s?ws=%s" % (missing, ws))[::2] == (
        404, {"error": "unknown seed run %s" % missing})
    outside = make_run(os.path.join(tmp, "elsewhere"), missing, ["ok"])
    os.symlink(outside, os.path.join(_runs_root(ws), missing))
    assert mt.api(s, "GET", "/api/seeds/runs/%s?ws=%s" % (missing, ws))[::2] == (
        404, {"error": "unknown seed run %s" % missing})


# --- SGT28 (SG50, SG51): Keep ----------------------------------------------------------------------------

def test_sgt28_keep(env):
    s, ws, tmp = env["srv"], env["ws"], env["tmp"]
    run_dir = make_run(ws, RA, ["ok", "blocked"])
    path = "/api/seeds/runs/%s/keep" % RA
    seeds = os.path.join(ws, "generated", "seeds")
    heroes = os.path.join(seeds, "heroes")
    for name in (RA + "-01.png", RA + "-01-2.png", RA + "-01-3.png"):
        assert mt.api(s, "POST", path, body={"ws": ws, "n": 1, "folder": "heroes"})[::2] == (
            201, {"folder": "heroes", "file": name, "path": os.path.join(heroes, name)})
        assert _read(os.path.join(heroes, name)) == _read(os.path.join(run_dir, "cand_01.png"))
    assert mt.api(s, "POST", path, body={"ws": ws, "n": 2, "folder": "heroes"})[::2] == (
        409, {"error": "candidate 2 of %s is blocked; only an ok candidate can be kept" % RA})
    for folder in ("", "runs", "Runs", "a..b", "-x", ".x", "A" * 65, "a/b", 5, None):
        assert mt.api(s, "POST", path, body={"ws": ws, "n": 1, "folder": folder})[::2] == (
            400, {"error": seedgen.FOLDER_MSG}), folder
    outside = os.path.join(tmp, "outside-folder")
    os.makedirs(outside)
    os.symlink(outside, os.path.join(seeds, "out"))
    assert mt.api(s, "POST", path, body={"ws": ws, "n": 1, "folder": "out"})[::2] == (
        409, {"error": "folder out resolves outside %s" % seeds})
    assert os.listdir(outside) == []
    for n in (0, 3, "1", None, True):
        assert mt.api(s, "POST", path, body={"ws": ws, "n": n, "folder": "heroes"})[::2] == (
            400, {"error": "n must be a candidate number from 1 to 2"}), n
    os.remove(os.path.join(run_dir, "cand_01.png"))
    assert mt.api(s, "POST", path, body={"ws": ws, "n": 1, "folder": "heroes"})[::2] == (
        409, {"error": "candidate 1 of %s has no image file" % RA})
    assert mt.api(s, "POST", "/api/seeds/runs/%s/keep" % RB, body={"ws": ws, "n": 1, "folder": "heroes"})[::2] == (
        404, {"error": "unknown seed run %s" % RB})
    assert sorted(os.listdir(heroes)) == [RA + "-01-2.png", RA + "-01-3.png", RA + "-01.png"]


# --- SGT29 (SG52, SG53): Use in Compose ----------------------------------------------------------------

def test_sgt29_use_registers_the_candidate_as_an_upload(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    run_dir = make_run(ws, RA, ["ok", "blocked"])
    data = _read(os.path.join(run_dir, "cand_01.png"))
    upload_id = hashlib.sha256(data).hexdigest() + ".png"
    want = {"upload_id": upload_id, "path": os.path.join(state, "uploads", upload_id), "bytes": len(data)}
    path = "/api/seeds/runs/%s/use" % RA
    assert mt.api(s, "POST", path, body={"ws": ws, "n": 1})[::2] == (201, want)
    assert _read(want["path"]) == data
    assert mt.api(s, "POST", "/api/uploads", raw=data, headers={"Content-Type": "image/png"})[::2] == (201, want)
    assert mt.api(s, "POST", path, body={"ws": ws, "n": 2})[::2] == (
        409, {"error": "candidate 2 of %s is blocked; only an ok candidate can be used" % RA})
    assert mt.api(s, "POST", path, body={"ws": ws, "n": 3})[::2] == (
        400, {"error": "n must be a candidate number from 1 to 2"})
    assert mt.api(s, "POST", "/api/uploads", raw=b"GIF89a", headers={"Content-Type": "image/png"})[::2] == (
        400, {"error": "file content is not image/png"})
    status, _h, out = mt.api(s, "POST", "/api/uploads", raw=mt.WEBP, headers={"Content-Type": "image/webp"})
    assert (status, out["upload_id"], out["bytes"]) == (201, hashlib.sha256(mt.WEBP).hexdigest() + ".webp", len(mt.WEBP))


# --- SGT30 (SG49): the seed folders ----------------------------------------------------------------------

def test_sgt30_the_seed_folders(env):
    s, ws, tmp = env["srv"], env["ws"], env["tmp"]
    seeds = os.path.join(ws, "generated", "seeds")
    assert mt.api(s, "GET", "/api/seeds/folders?ws=" + ws)[::2] == (200, {"root": seeds, "folders": []})
    heroes = os.path.join(seeds, "heroes")
    os.makedirs(os.path.join(heroes, "sub.png"))
    for name in ("a.png", "b.PNG", "c.jpg", "notes.txt"):
        with open(os.path.join(heroes, name), "wb") as f:
            f.write(mt.PNG)
    for name in ("runs", "Zeta", "alpha", "a..b"):
        os.makedirs(os.path.join(seeds, name), exist_ok=True)
    with open(os.path.join(seeds, "loose.png"), "wb") as f:
        f.write(mt.PNG)
    os.makedirs(os.path.join(tmp, "outside-folder"))
    os.symlink(os.path.join(tmp, "outside-folder"), os.path.join(seeds, "linked"))
    assert mt.api(s, "GET", "/api/seeds/folders?ws=" + ws)[::2] == (200, {"root": seeds, "folders": [
        {"folder": "alpha", "count": 0, "path": os.path.join(seeds, "alpha")},
        {"folder": "heroes", "count": 3, "path": heroes},
        {"folder": "Zeta", "count": 0, "path": os.path.join(seeds, "Zeta")}]})


# --- SGT31 (SG36, SG38): the seed_edit capability --------------------------------------------------------

def test_sgt31_the_seed_edit_capability(env):
    s, ws, tmp = env["srv"], env["ws"], env["tmp"]
    server = s.server
    assert mt.api(s, "GET", "/api/host")[2]["capabilities"]["seed_edit"] == {
        "ok": None, "reason": "probing", "checked": None, "models": None}
    server.probe_ws = ws
    good_py = os.path.join(tmp, "good-python")
    with open(good_py, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(good_py, 0o755)
    server.stills_py = good_py
    env["mp"].setenv("LTX2_MLX_BIN", os.path.join(tmp, "missing-ltx"))
    caps = mt.api(s, "GET", "/api/host?refresh=1")[2]["capabilities"]
    checked = caps["seed_edit"]["checked"]
    assert TIME_RE.fullmatch(checked)
    assert caps["seed_edit"] == {"ok": True, "reason": None, "checked": checked, "models": OK_MODELS}
    assert all(set(caps[key]) == {"ok", "reason", "checked"} for key in ("render", "stills", "story_server"))
    none_ok = {"zimage": {"ok": False, "reason": "z", "backend": None},
               "qwen": {"ok": False, "reason": "q", "backend": None}}
    stub_seed_edit(ws, none_ok)
    caps = mt.api(s, "GET", "/api/host?refresh=1")[2]["capabilities"]
    assert dict(caps["seed_edit"], checked=None) == {"ok": False, "reason": "Z-Image: z; Qwen-Image-Edit: q",
                                                     "checked": None, "models": none_ok}
    stub_seed_edit(ws, OK_MODELS, exit=1, stderr="boom\n")
    caps = mt.api(s, "GET", "/api/host?refresh=1")[2]["capabilities"]
    assert dict(caps["seed_edit"], checked=None) == {"ok": False, "reason": "bin/seed-edit --probe exited 1: boom",
                                                     "checked": None, "models": None}


# --- SGT32 (SG46): the job summary key -------------------------------------------------------------------

def test_sgt32_the_job_summary_key(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    status, _h, data = _create(s, _body(ws, {"upload_id": _upload(s)}))
    assert status == 201, data
    mt.make_job(state, ["true"], ws)
    queued = mt.api(s, "GET", "/api/jobs")[2]["queued"]
    assert [(j["kind"], j["seed_run"]) for j in queued] == [("seed-edit", data["run"]["run"]), ("movie", None)]


# --- Review Focus 1: phone JPEGs and WebP files keep their extension end to end ----------------------------

def test_sg_review_focus_1_jpeg_and_webp_sources_keep_their_extension(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    for data, ctype, ext in ((mt.JPEG + b"phone", "image/jpeg", "jpg"), (mt.WEBP + b"web", "image/webp", "webp")):
        status, _h, out = _create(s, _body(ws, {"upload_id": _upload(s, data, ctype)}))
        assert status == 201, out
        view = out["run"]
        name = "source." + ext
        assert view["source"] == os.path.join(view["dir"], name)
        assert _read(view["source"]) == data
        assert _record(view["dir"])["source"] == name
        assert sorted(os.listdir(view["dir"])) == ["run.json", name]
        job = lib.read_job(lib.job_dir(state, view["job"]["id"]))
        assert job["fields"]["source_file"] == name
        assert job["argv"][job["argv"].index("--source") + 1] == view["source"]


# --- Review Focus 2: Keep clicked four times at once -------------------------------------------------------

def test_sg_review_focus_2_keep_clicked_four_times_at_once(env):
    s, ws = env["srv"], env["ws"]
    run_dir = make_run(ws, RA, ["ok"])
    results = []

    def keep():
        results.append(mt.api(s, "POST", "/api/seeds/runs/%s/keep" % RA, body={"ws": ws, "n": 1, "folder": "heroes"}))

    threads = [threading.Thread(target=keep) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert sorted(r[0] for r in results) == [201] * 4
    names = sorted(r[2]["file"] for r in results)
    assert names == sorted([RA + "-01.png"] + [RA + "-01-%d.png" % k for k in (2, 3, 4)])
    for r in results:
        assert _read(r[2]["path"]) == _read(os.path.join(run_dir, "cand_01.png"))


# --- SGT33 (SG54-SG65): the static page ----------------------------------------------------------------

PAGE_IDS = ("tab-seeds", "panel-seeds", "se-file", "se-source-status", "se-source-img", "se-source-size", "se-prompt",
            "se-prompt-count", "se-model", "se-model-note", "se-strength-box", "se-strength", "se-candidates",
            "se-seed", "se-generate", "se-generate-reason", "se-run-title", "se-run-status", "se-folder-options",
            "se-grid", "se-runs", "se-folders")
JS_TEXTS = ('"/api/seeds/runs"', '"/api/seeds/folders"', '"/keep"', '"/use"', '"New seed from this"',
            '"Use in Compose"', '"Edit again"', '"Copy path"', '"blocked by content safety"', '"unavailable — "',
            '"selected — press Cmd+C"', '"seed run "', "navigator.clipboard", "S.timers.seeds",
            'const TABS = ["compose", "seeds", "stories", "batches", "characters", "locations", "actions", "loras", '
            '"jobs", "traces"];',
            '["jobs", "log", "host", "batch"]',
            "await Promise.all([loadCatalog(), loadCharacters(), loadLocations(), loadActions(), loadStories(), "
            "loadModels()]);",
            "    resetSeeds();\n    await loadOptions();\n", "    setupCompose();\n    setupSeeds();\n",
            "    updateLocationButtons();\n    updateSeedButtons();\n  }\n",
            '    if (name !== "seeds") { stopSeedPoll(); }\n    if (name === "seeds") { loadSeeds(); }\n',
            "    });\n    if (S.timers.seeds) { clearInterval(S.timers.seeds); S.timers.seeds = null; }\n"
            "    if (S.timers.traces) {",
            'return job.story_id || job.character || (job.seed_run ? "seed run " + job.seed_run : "") || '
            '(job.kind === "smoke" ? "smoke render" : "-");',
            'gallery.appendChild(el("figure", {cls: "se-still"}, [el("img", {src: fileUrl(p), alt: p}), '
            'button("New seed from this", function () { seedFromStill(name, p); })]));')
SEED_FUNCTIONS = ("seedCanvas", "setSeedSource", "onSeedSourceFile", "updateSeedButtons", "seedBody", "generateSeeds",
                  "openSeedRun", "pollSeedRun", "renderSeedRun", "seedRow", "keepSeed", "useSeed", "editSeedAgain",
                  "loadSeeds", "loadSeedRuns", "loadSeedFolders", "copySeedPath", "seedFromStill", "stopSeedPoll",
                  "resetSeeds", "setupSeeds")
CSS_RULES = (".se-grid { display: flex; flex-direction: column; gap: 12px; }",
             ".se-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: flex-start; }",
             ".se-img, .se-thumb { width: 320px; height: auto; border: 1px solid var(--line); }",
             ".se-actions { display: flex; flex-direction: column; gap: 4px; }",
             ".se-mini { width: 64px; height: auto; margin-right: 4px; }",
             ".gallery figure { margin: 0; display: flex; flex-direction: column; gap: 4px; }")


def _static_texts():
    static = os.path.join(WS, "static", "movie-ui")
    texts = {}
    for name in ("index.html", "app.js", "app.css"):
        with open(os.path.join(static, name), encoding="utf-8") as f:
            texts[name] = f.read()
    return static, texts


def test_sgt33_the_static_page():
    static, texts = _static_texts()
    html, js, css = texts["index.html"], texts["app.js"], texts["app.css"]
    for element in PAGE_IDS:
        assert html.count('id="%s"' % element) == 1, element
    assert html.index('id="tab-compose"') < html.index('id="tab-seeds"') < html.index('id="tab-stories"')
    assert html.index('id="panel-compose"') < html.index('id="panel-seeds"') < html.index('id="panel-stories"')
    assert '<img id="se-source-img" class="se-thumb" alt="source image" hidden>' in html
    assert '<option value="4" selected>4</option>' in html and 'placeholder="blank = random"' in html
    for text in JS_TEXTS:
        assert text in js, text
    for name in SEED_FUNCTIONS:
        assert js.count("function %s(" % name) == 1, name
    for rule in CSS_RULES:
        assert rule in css, rule
    for name, text in texts.items():
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\balert\(", r"\bconfirm\(", r"\bprompt\(",
                        r"\beval\(", r"new Function"):
            assert not re.search(pattern, text), (name, pattern)
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")], capture_output=True, text=True,
                              timeout=60)
        assert proc.returncode == 0, proc.stderr


# --- Review Focus 5: the page's canvas size matches the tool's ----------------------------------------------

CANVAS_CASES = [(1536, 1024), (1024, 1024), (800, 600), (4000, 3000), (3000, 4000), (720, 1280), (1023, 1023),
                (100, 70), (100, 60), (64, 64), (63, 100), (1025, 1), (2000, 1999), (1, 5000), (4032, 3024),
                (3024, 4032), (1080, 1920), (1920, 1080), (5000, 5000), (17, 17), (1040, 1040), (1041, 300),
                (8192, 64), (64, 8192), (1366, 768), (2048, 1365)]


def test_sg_review_focus_5_the_page_canvas_matches_the_tool(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader("seed_edit_tool", os.path.join(WS, "bin", "seed-edit"))
    spec = importlib.util.spec_from_loader("seed_edit_tool", loader)
    tool = importlib.util.module_from_spec(spec)
    loader.exec_module(tool)
    with open(os.path.join(WS, "static", "movie-ui", "app.js"), encoding="utf-8") as f:
        js = f.read()
    start = js.index("  function seedCanvas(w, h) {")
    end = js.index("\n  }\n", start) + len("\n  }\n")
    script = js[start:end] + "const SEED_LONG_EDGE = 1024;\nprocess.stdout.write(JSON.stringify(%s.map(function (c) { " \
        "return seedCanvas(c[0], c[1]); })));\n" % json.dumps(CANVAS_CASES)
    path = os.path.join(str(tmp_path), "canvas.js")
    with open(path, "w", encoding="utf-8") as f:
        f.write(script)
    proc = subprocess.run([node, path], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    for (w0, h0), got in zip(CANVAS_CASES, json.loads(proc.stdout)):
        try:
            want = dict(zip(("width", "height"), tool.canvas(w0, h0)))
        except tool.Refusal as e:
            found = re.search(r"gives a ([0-9]+)x([0-9]+) canvas", str(e))
            want = {"width": int(found.group(1)), "height": int(found.group(2))}
            assert min(got["width"], got["height"]) < 64, (w0, h0, got)
        assert got == want, (w0, h0)


# --- SGT34 (SG2, SG24): the new Python files are compiled and scanned; the tool's top-level imports ---------

def test_sgt34_the_new_python_files_and_the_tool_imports():
    with open(os.path.join(WS, "tests", "test_movie_ui_builder.py"), encoding="utf-8") as f:
        builder = f.read()
    start = builder.index("NEW_PY = (")
    new_py = builder[start:builder.index(")", start)]
    for rel in ("movie_ui_seedgen.py", "bin/seed-edit", "bin/seed-edit-setup", "seed_edit_mflux_child.py",
                "tests/test_seed_edit_tool.py", "tests/test_movie_ui_seedgen.py"):
        assert '"%s"' % rel in new_py, rel
    with open(os.path.join(WS, "bin", "seed-edit"), encoding="utf-8") as f:
        source = f.read()
    assert re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M) == [
        "argparse", "glob", "importlib.util", "json", "os", "re", "secrets", "shutil", "signal", "subprocess", "sys",
        "threading", "time", "movie_ui_lib"]


def test_sg_task6_review_page_guards():
    """Task 6 review: one seed poll at a time and never on a hidden tab; stale-workspace answers ignored; the
    Seeds lists reload on a workspace switch; Keep and Use disabled while their request runs; Generate's unknown
    outcome warns instead of offering a blind retry; a source that fails to load is dropped with a reason."""
    _static, texts = _static_texts()
    js = texts["app.js"]
    for text in ('    stopSeedPoll();\n    if (SEED_ACTIVE.indexOf(res.data.state) >= 0 && !$("#panel-seeds").hidden) {\n',
                 '    if (ws !== S.ws) { return; }\n    const body = clear($("#se-runs tbody"));\n',
                 '    if (ws !== S.ws) { return; }\n    const options = clear($("#se-folder-options"));\n',
                 'loadModels()]);\n    if (!$("#panel-seeds").hidden) { loadSeeds(); }\n',
                 'try { await keepSeed(run, cand.n, input, status); } finally { target.disabled = false; }',
                 'try { await useSeed(run, cand.n, status); } finally { target.disabled = false; }',
                 '"the request may have been queued — check Runs and Jobs before retrying"',
                 '$("#se-source-img").addEventListener("error", function () {',
                 '"the source image could not be loaded — pick it again"'):
        assert text in js, text
    assert js.count("S.timers.seeds = setInterval(") == 1
