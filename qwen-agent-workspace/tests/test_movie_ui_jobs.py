"""movie-ui job store, runner, cancel, liveness, queue and server process tests (movie-ui spec
MUT10-MUT15). Run from the workspace root: python3 -m pytest tests/test_movie_ui_jobs.py -v
Every test runs under a temporary HOME; children are sys.executable -c scripts."""

import fcntl
import http.client
import json
import os
import re
import signal
import socket
import stat
import subprocess
import sys
import time

import pytest

import movie_ui_testutil as mt
import movie_ui_lib as lib

STATUS_KEYS_FINAL = {"state", "dispatched", "runner_pid", "pgid", "started", "exit_code", "ended"}


@pytest.fixture
def state(monkeypatch, tmp_path):
    path = mt.set_home(monkeypatch, tmp_path)
    yield path
    mt.kill_everything(path)


def _final(state, job_id, timeout=20):
    return mt.wait_until(lambda: mt.status_of(state, job_id).get("state") in lib.FINISHED_STATES
                         and mt.status_of(state, job_id), timeout)


def _final_within_2s_of_cancel_log(state, job_id):
    """Ruling F3: the final status is observed within 2.0 s of the first log line containing
    "[movie-ui] cancel: SIGTERM" (polling status.json after that line appears)."""
    mt.wait_until(lambda: "[movie-ui] cancel: SIGTERM" in mt.read_log(state, job_id), 10)
    t_log = time.monotonic()
    status = _final(state, job_id)
    assert time.monotonic() - t_log < 2.0
    return status


def test_store_writes_atomically_with_private_modes(state, tmp_path):
    for name in lib.STATE_SUBDIRS:
        assert stat.S_IMODE(os.stat(os.path.join(state, name)).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(state).st_mode) == 0o700
    assert re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", lib.utc_now())
    path = os.path.join(state, "x.json")
    lib.write_json_atomic(path, {"a": "é"})
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert lib.read_json(path) == {"a": "é"}
    assert [n for n in os.listdir(state) if ".tmp-" in n] == []
    job_id = lib.new_job_id(state)
    assert lib.JOB_ID_RE.fullmatch(job_id)
    for bad in ("20261019-142233-a1b", "20261019-142233-A1B2", "20261019-142233-a1b2\n", "x"):
        assert not lib.JOB_ID_RE.fullmatch(bad)
    job = lib.create_job(state, job_id, "movie", str(tmp_path), "s1", None, ["/bin/echo", "hi"], {"action": "movie"})
    jdir = lib.job_dir(state, job_id)
    assert stat.S_IMODE(os.stat(jdir).st_mode) == 0o700
    assert lib.read_job(jdir) == job
    assert set(job) == {"schema", "id", "kind", "workspace", "story_id", "character", "argv", "fields", "created"}
    assert job["schema"] == "movie-ui.job.v1"
    assert os.path.getsize(os.path.join(jdir, "log.txt")) == 0
    assert lib.read_status(jdir) is None
    assert lib.read_queue(state) == [job_id]
    with open(lib.queue_path(state), "w") as f:
        f.write("{not json")
    assert lib.read_queue(state) == []


def test_mut10_runner_outcomes_status_and_log(state, tmp_path):
    ok = mt.make_job(state, mt.py_argv("print('hello from the child')"), str(tmp_path))
    bad = mt.make_job(state, mt.py_argv("import sys; sys.stderr.write('boom\\n'); sys.exit(3)"), str(tmp_path))
    gone = mt.make_job(state, [os.path.join(str(tmp_path), "no-such-binary")], str(tmp_path))
    for job_id in (ok, bad, gone):
        mt.dispatch(state, job_id)
    s_ok, s_bad, s_gone = _final(state, ok), _final(state, bad), _final(state, gone)
    assert s_ok["state"] == "done" and s_ok["exit_code"] == 0
    assert s_bad["state"] == "failed" and s_bad["exit_code"] == 3
    assert set(s_ok) == STATUS_KEYS_FINAL and set(s_bad) == STATUS_KEYS_FINAL
    assert s_ok["pgid"] != s_ok["runner_pid"] and isinstance(s_ok["pgid"], int)
    assert set(s_gone) == STATUS_KEYS_FINAL | {"error"}
    assert s_gone["state"] == "failed" and s_gone["pgid"] is None and s_gone["started"] is None
    assert s_gone["exit_code"] is None and s_gone["error"].startswith("cannot start: ")
    log = mt.wait_until(lambda: "[movie-ui] exit 0 (done)" in mt.read_log(state, ok) and mt.read_log(state, ok), 5)
    assert "hello from the child\n" in log
    assert re.search(r"^\[movie-ui\] started pid [0-9]+: .+ -c ", log, re.M)
    bad_log = mt.wait_until(lambda: "[movie-ui] exit 3 (failed)" in mt.read_log(state, bad)
                            and mt.read_log(state, bad), 5)
    assert "boom\n" in bad_log
    assert "[movie-ui] cannot start: " in mt.wait_until(lambda: mt.read_log(state, gone), 5)


def test_mut12_runner_started_directly_without_a_server(state, tmp_path):
    job_id = mt.make_job(state, mt.py_argv("print('direct')"), str(tmp_path))
    jdir = lib.job_dir(state, job_id)
    lib.write_status(jdir, {"state": "starting", "dispatched": lib.utc_now()})
    proc = subprocess.run([sys.executable, os.path.join(mt.WS, "bin", "movie-ui-job"), "--grace", "0.5", jdir],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    status = lib.read_status(jdir)
    assert status["state"] == "done" and status["exit_code"] == 0
    assert "[movie-ui] exit 0 (done)" in proc.stdout
    again = subprocess.run([sys.executable, os.path.join(mt.WS, "bin", "movie-ui-job"), jdir],
                           capture_output=True, text=True, timeout=30)
    assert again.returncode == 3
    assert again.stdout == "[movie-ui] job is done; nothing to run\n"


def _ready_file(tmp_path, name):
    return os.path.join(str(tmp_path), name)


def test_mut11_cancel_term_then_kill_and_same_group_grandchild(state, tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "CANCEL_GRACE_S", 1.0)
    ready = _ready_file(tmp_path, "ready")
    polite = mt.make_job(state, mt.py_argv("import time; open(%r, 'w').write('1'); time.sleep(60)" % ready),
                         str(tmp_path))
    mt.dispatch(state, polite)
    mt.wait_until(lambda: os.path.exists(ready), 10)
    t0 = time.monotonic()
    mt.cancel_marker(state, polite)
    status = _final_within_2s_of_cancel_log(state, polite)
    assert status["state"] == "cancelled" and status["exit_code"] == -signal.SIGTERM
    assert time.monotonic() - t0 < 1.0 + 1.0 + 1.0
    assert "[movie-ui] cancel: SIGTERM to process group(s) %d" % status["pgid"] in mt.read_log(state, polite)

    ready2, grand = _ready_file(tmp_path, "ready2"), _ready_file(tmp_path, "grand")
    code = ("import signal, subprocess, sys, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "g = subprocess.Popen([sys.executable, '-c', 'import signal, time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'])\n"
            "open(%r, 'w').write(str(g.pid))\n"
            "open(%r, 'w').write('1')\n"
            "time.sleep(60)\n" % (grand, ready2))
    stubborn = mt.make_job(state, mt.py_argv(code), str(tmp_path))
    mt.dispatch(state, stubborn)
    mt.wait_until(lambda: os.path.exists(ready2), 10)
    grand_pid = int(open(grand).read())
    t0 = time.monotonic()
    mt.cancel_marker(state, stubborn)
    status = _final(state, stubborn)
    assert status["state"] == "cancelled" and status["exit_code"] == -signal.SIGKILL
    assert time.monotonic() - t0 < 1.0 + 1.0 + 1.0
    log = mt.read_log(state, stubborn)
    assert "[movie-ui] cancel: SIGKILL to process group(s) %d" % status["pgid"] in log
    mt.wait_until(lambda: not mt.pid_alive(grand_pid), 5)
    assert not lib.group_alive(status["pgid"])


def test_runner_refuses_a_job_that_is_not_starting(state, tmp_path):
    job_id = mt.make_job(state, mt.py_argv("print(1)"), str(tmp_path))
    jdir = lib.job_dir(state, job_id)
    proc = subprocess.run([sys.executable, os.path.join(mt.WS, "bin", "movie-ui-job"), jdir],
                          capture_output=True, text=True, timeout=30)
    assert (proc.returncode, proc.stdout) == (3, "[movie-ui] job is unknown; nothing to run\n")
    assert lib.read_status(jdir) is None
