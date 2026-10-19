"""Shared helpers for the movie-ui tests (movie-ui spec 14.2,
docs/superpowers/specs/2026-10-19-movie-ui-design.md).

Not a test module (pytest does not collect it). Every helper writes under a directory the caller
passes in; nothing here reads or writes the real HOME, renders, or contacts a real server.
"""

import http.client
import http.server
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TESTS = os.path.join(WS, "tests")
FIXTURES = os.path.join(TESTS, "fixtures", "movie_ui")
sys.path.insert(0, WS)

import fleet_lib  # noqa: E402
import movie_ui_lib  # noqa: E402


def set_home(monkeypatch, tmp_path, grace=0.5):
    """HOME=<tmp>/home, CANCEL_GRACE_S=grace, no ANTHROPIC_API_KEY; returns the created STATE."""
    home = os.path.join(str(tmp_path), "home")
    os.makedirs(home, exist_ok=True)
    monkeypatch.setenv("HOME", home)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(movie_ui_lib, "CANCEL_GRACE_S", grace)
    state = movie_ui_lib.state_dir()
    movie_ui_lib.ensure_state(state)
    return state


def wait_until(predicate, timeout, interval=0.05):
    """Poll predicate() until truthy; return its value, or fail the test."""
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError("condition not met within %.1f s" % timeout)
        time.sleep(interval)


def py_argv(code):
    """[sys.executable, "-c", code]: a real child process for runner tests."""
    return [sys.executable, "-c", code]


def make_job(state, argv, workspace, kind="movie", story_id="s1", fields=None, status=None):
    """Create a queued job (as the server does under STORE_LOCK); with status, also write it and
    drop the job from the queue. Returns the job ID."""
    job_id = movie_ui_lib.new_job_id(state)
    movie_ui_lib.create_job(state, job_id, kind, workspace, story_id, None, argv,
                            fields or {"action": "movie", "mode": "chained"})
    if status is not None:
        movie_ui_lib.write_queue(state, [i for i in movie_ui_lib.read_queue(state) if i != job_id])
        movie_ui_lib.write_status(movie_ui_lib.job_dir(state, job_id), status)
    return job_id


def dispatch(state, job_id):
    """Write the "starting" status and launch the runner, as dispatch_tick does; returns the Popen."""
    jdir = movie_ui_lib.job_dir(state, job_id)
    movie_ui_lib.write_queue(state, [i for i in movie_ui_lib.read_queue(state) if i != job_id])
    movie_ui_lib.write_status(jdir, {"state": "starting", "dispatched": movie_ui_lib.utc_now()})
    return movie_ui_lib.launch_runner(state, job_id, WS)


def cancel_marker(state, job_id):
    """Create the job's cancel marker, as cancel_job does for a starting or running job (MU17)."""
    movie_ui_lib.write_bytes_atomic(os.path.join(movie_ui_lib.job_dir(state, job_id), "cancel"), b"")


def status_of(state, job_id):
    return movie_ui_lib.read_status(movie_ui_lib.job_dir(state, job_id)) or {}


def read_log(state, job_id):
    with open(os.path.join(movie_ui_lib.job_dir(state, job_id), "log.txt"), "rb") as f:
        return f.read().decode("utf-8", "replace")


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return True
    return not out.stdout.decode("ascii", "replace").strip().startswith("Z")


def kill_everything(state):
    """Teardown: SIGKILL every job's recorded group and every launched runner."""
    for job_id in movie_ui_lib.list_job_ids(state):
        pgid = status_of(state, job_id).get("pgid")
        if isinstance(pgid, int) and pgid > 1:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except OSError:
                pass
    for proc in list(movie_ui_lib.RUNNERS):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            pass
    del movie_ui_lib.RUNNERS[:]
