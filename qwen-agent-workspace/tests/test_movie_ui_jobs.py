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
    status = _final_within_2s_of_cancel_log(state, stubborn)
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


def test_atomic_write_failure_reraises_and_leaves_no_tmp_file(state, monkeypatch):
    path = os.path.join(state, "y.json")

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(lib.os, "replace", boom)
    with pytest.raises(OSError):
        lib.write_bytes_atomic(path, b"data")
    assert [n for n in os.listdir(state) if n.startswith("y.json.tmp-")] == []
    assert not os.path.exists(path)


def test_mut11_cancel_reaches_a_grandchild_in_its_own_session(state, tmp_path, monkeypatch):
    """D1: the render's ltx-2-mlx runs with start_new_session=True (ltx2_mlx_video_skill.py:341)."""
    monkeypatch.setattr(lib, "CANCEL_GRACE_S", 1.0)
    ready, grand = _ready_file(tmp_path, "ready"), _ready_file(tmp_path, "grand")
    code = ("import subprocess, sys, time\n"
            "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)\n"
            "open(%r, 'w').write(str(g.pid))\n"
            "open(%r, 'w').write('1')\n"
            "time.sleep(60)\n" % (grand, ready))
    job_id = mt.make_job(state, mt.py_argv(code), str(tmp_path))
    mt.dispatch(state, job_id)
    mt.wait_until(lambda: os.path.exists(ready), 10)
    grand_pid = int(open(grand).read())
    assert os.getpgid(grand_pid) == grand_pid
    t0 = time.monotonic()
    mt.cancel_marker(state, job_id)
    status = _final(state, job_id)
    assert status["state"] == "cancelled"
    mt.wait_until(lambda: not mt.pid_alive(grand_pid), 5)
    assert time.monotonic() - t0 < 16
    log = mt.read_log(state, job_id)
    assert "[movie-ui] cancel: SIGTERM to process group(s) %s" % " ".join(
        str(g) for g in sorted((status["pgid"], grand_pid))) in log


def test_descendant_groups_and_the_ps_fallback(monkeypatch, capsys):
    table = [(10, 1, 10), (11, 10, 10), (12, 11, 12), (13, 12, 12), (14, 1, 14), (15, 14, 15)]
    assert lib.descendant_groups(10, table) == [10, 12]
    assert lib.descendant_groups(14, table) == [14, 15]
    assert lib.descendant_groups(99, table) == [99]
    rows = lib.process_table()
    assert rows and (os.getpid(), os.getppid(), os.getpgid(0)) in rows
    monkeypatch.setattr(lib, "process_table", lambda: None)
    assert lib.cancel_groups(4242) == [4242]
    assert capsys.readouterr().out == "[movie-ui] ps failed; signalling process group 4242 only\n"


def _lock_held(state, job_id):
    fd = os.open(os.path.join(lib.job_dir(state, job_id), "lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


def test_mut13_liveness_recovery_lost_and_orphans(state, tmp_path):
    ready = _ready_file(tmp_path, "ready")
    job_id = mt.make_job(state, mt.py_argv("import time; open(%r, 'w').write('1'); time.sleep(60)" % ready),
                         str(tmp_path))
    runner = mt.dispatch(state, job_id)
    mt.wait_until(lambda: os.path.exists(ready), 10)
    jdir = lib.job_dir(state, job_id)
    assert lib.job_alive(jdir) is True
    lib.startup_recovery(state)
    assert mt.status_of(state, job_id)["state"] == "running"
    pgid = mt.status_of(state, job_id)["pgid"]
    os.kill(runner.pid, signal.SIGKILL)
    runner.wait(5)
    assert lib.job_alive(jdir) is False
    lost = mt.status_of(state, job_id)
    assert lost["state"] == "lost" and lost["exit_code"] is None and lost["ended"] is None
    assert lost["pgid"] == pgid and lib.parse_utc(lost["detected"]) is not None
    assert lib.orphan_info(lost) == {"pgid": pgid, "alive": True}
    assert lib.kill_orphan(state, job_id) == pgid
    mt.wait_until(lambda: not lib.group_alive(pgid), 5)
    assert lib.orphan_info(mt.status_of(state, job_id)) is None
    assert lib.kill_orphan(state, job_id) is None
    # A running job with no runner at startup, and a starting job past the 10 s grace, are lost.
    dead = mt.make_job(state, ["true"], str(tmp_path), status={"state": "running", "dispatched": lib.utc_now(),
                                                               "runner_pid": 1, "pgid": None, "started": lib.utc_now()})
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 60))
    stale = mt.make_job(state, ["true"], str(tmp_path), status={"state": "starting", "dispatched": old})
    fresh = mt.make_job(state, ["true"], str(tmp_path), status={"state": "starting", "dispatched": lib.utc_now()})
    lib.startup_recovery(state)
    assert mt.status_of(state, dead)["state"] == "lost"
    assert mt.status_of(state, stale)["state"] == "lost"
    assert mt.status_of(state, fresh)["state"] == "starting"
    assert lib.job_alive(lib.job_dir(state, fresh)) is True


def test_mut14_queue_fifo_one_runner_at_a_time_and_actions(state, tmp_path):
    ws = str(tmp_path)
    ids = [mt.make_job(state, mt.py_argv("import time; time.sleep(0.6)"), ws) for _ in range(3)]
    assert lib.read_queue(state) == ids
    launched, max_held = [], 0
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        got = lib.dispatch_tick(state, mt.WS)
        if got:
            launched.append(got)
        max_held = max(max_held, sum(1 for i in ids if _lock_held(state, i)))
        if all(mt.status_of(state, i).get("state") == "done" for i in ids):
            break
        time.sleep(0.1)
    assert launched == ids
    assert max_held == 1
    starts = [mt.status_of(state, i)["started"] for i in ids]
    assert starts == sorted(starts)
    # move, cancel, no-ops, and the queue across a restart
    a, b, c = (mt.make_job(state, ["true"], ws) for _ in range(3))
    assert lib.move_job(state, c, "up") == [a, c, b]
    assert lib.move_job(state, a, "up") == [a, c, b]
    assert lib.move_job(state, b, "down") == [a, c, b]
    assert lib.move_job(state, ids[0], "up") is None
    assert lib.cancel_job(state, c) == "cancelled"
    assert lib.read_queue(state) == [a, b]
    assert mt.status_of(state, c) == {"state": "cancelled", "exit_code": None, "ended": mt.status_of(state, c)["ended"]}
    assert lib.parse_utc(mt.status_of(state, c)["ended"]) is not None
    assert lib.cancel_job(state, c) is None
    lib.write_queue(state, lib.read_queue(state) + ["bogus", c, a, "20261019-000000-ffff"])
    lib.startup_recovery(state)
    assert lib.read_queue(state) == [a, b]
    assert lib.delete_job(state, a) is False
    assert lib.delete_job(state, c) is True and not os.path.exists(lib.job_dir(state, c))
    # a job whose workspace was removed by self-update
    gone = os.path.join(ws, "pruned-release")
    os.mkdir(gone)
    lost_ws = mt.make_job(state, ["true"], gone)
    lib.write_queue(state, [lost_ws, a, b])
    os.rmdir(gone)
    assert lib.dispatch_tick(state, mt.WS) == a
    assert mt.status_of(state, lost_ws) == {"state": "failed", "exit_code": None,
                                            "ended": mt.status_of(state, lost_ws)["ended"],
                                            "error": "workspace no longer exists (removed by self-update)"}
    assert lib.parse_utc(mt.status_of(state, lost_ws)["ended"]) is not None
    assert lib.read_queue(state) == [b]


def test_review_focus_3_cancel_while_starting(state, tmp_path):
    """Review Focus 3: Cancel pressed in the instant between dispatch and the runner's start."""
    job_id = mt.make_job(state, mt.py_argv("open(%r, 'w').write('ran')" % _ready_file(tmp_path, "ran")),
                         str(tmp_path))
    jdir = lib.job_dir(state, job_id)
    lib.write_queue(state, [])
    lib.write_status(jdir, {"state": "starting", "dispatched": lib.utc_now()})
    assert lib.cancel_job(state, job_id) == "cancelling"
    proc = subprocess.run([sys.executable, os.path.join(mt.WS, "bin", "movie-ui-job"), jdir],
                          capture_output=True, text=True, timeout=30)
    assert (proc.returncode, proc.stdout) == (0, "[movie-ui] cancelled before start\n")
    status = lib.read_status(jdir)
    assert status == {"state": "cancelled", "exit_code": None, "ended": status["ended"]}
    assert not os.path.exists(_ready_file(tmp_path, "ran"))


def test_delete_job_raises_when_removal_fails(state, tmp_path, monkeypatch):
    job_id = mt.make_job(state, ["true"], str(tmp_path),
                         status={"state": "done", "exit_code": 0, "ended": lib.utc_now()})

    def boom(*args, **kwargs):
        raise OSError("boom")
    monkeypatch.setattr(lib.shutil, "rmtree", boom)
    with pytest.raises(OSError):
        lib.delete_job(state, job_id)


def test_dispatch_tick_waits_for_a_live_orphan_group(state, tmp_path):
    proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        pgid = os.getpgid(proc.pid)
        lost = mt.make_job(state, ["true"], str(tmp_path),
                           status={"state": "lost", "exit_code": None, "ended": None, "pgid": pgid,
                                   "detected": lib.utc_now()})
        queued = mt.make_job(state, ["true"], str(tmp_path))
        assert lib.orphan_info(mt.status_of(state, lost)) == {"pgid": pgid, "alive": True}
        assert lib.dispatch_tick(state, mt.WS) is None
        assert lib.read_queue(state) == [queued]
        os.killpg(pgid, signal.SIGKILL)
        proc.wait(5)
        mt.wait_until(lambda: not lib.group_alive(pgid), 5)
        assert lib.dispatch_tick(state, mt.WS) == queued
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.wait(5)


def test_dispatch_tick_waits_for_a_fresh_starting_job(state, tmp_path):
    fresh = mt.make_job(state, ["true"], str(tmp_path),
                        status={"state": "starting", "dispatched": lib.utc_now()})
    queued = mt.make_job(state, ["true"], str(tmp_path))
    assert lib.dispatch_tick(state, mt.WS) is None
    assert lib.read_queue(state) == [queued]
    assert mt.status_of(state, fresh)["state"] == "starting"


def _start_ui(ui, home, port):
    env = dict(os.environ, HOME=home, PYTHONUNBUFFERED="1")
    env.pop("ANTHROPIC_API_KEY", None)
    return subprocess.Popen([sys.executable, os.path.join(ui, "bin", "movie-ui"), "--port", str(port)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)


def test_mut15_bin_movie_ui_lock_port_and_startup_lines(tmp_path):
    home = os.path.join(str(tmp_path), "home")
    os.makedirs(home)
    ui = mt.copy_ui(tmp_path)
    port = mt.free_port()
    first = _start_ui(ui, home, port)
    try:
        line1 = first.stdout.readline()
        line2 = first.stdout.readline()
        state = os.path.join(home, ".local", "share", "qwen-agent", "movie-ui")
        m = re.fullmatch(r"movie-ui: http://127\.0\.0\.1:%d/\?t=([A-Za-z0-9_-]{43})\n" % port, line1)
        assert m, line1
        assert line2 == "movie-ui: state %s; Ctrl-C stops the server (running jobs keep running)\n" % state
        token = m.group(1)
        for name in ("jobs", "uploads", "traces", "smoke"):
            assert stat.S_IMODE(os.stat(os.path.join(state, name)).st_mode) == 0o700
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/api/host", headers={"X-Movie-UI-Token": token})
        resp = conn.getresponse()
        body = json.loads(resp.read())
        conn.close()
        assert resp.status == 200 and body["port"] == port and body["ui_workspace"] == os.path.realpath(ui)
        second = _start_ui(ui, home, mt.free_port())
        out, err = second.communicate(timeout=30)
        assert second.returncode == 2 and out == ""
        assert err == ("movie-ui: another movie-ui is already running on this host (lock held: %s)\n"
                       % os.path.join(state, "server.lock"))
    finally:
        first.send_signal(signal.SIGTERM)
        out, err = first.communicate(timeout=30)
    assert first.returncode == 0 and out == "movie-ui: stopped\n" and err == ""
    held = socket.socket()
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    busy_port = held.getsockname()[1]
    try:
        busy = _start_ui(ui, home, busy_port)
        out, err = busy.communicate(timeout=30)
    finally:
        held.close()
    assert (busy.returncode, err) == (2, "movie-ui: port %d on 127.0.0.1 is in use; pass --port N\n" % busy_port)
    for bad in ("80", "65536", "x"):
        low = _start_ui(ui, home, bad)
        out, err = low.communicate(timeout=30)
        assert (low.returncode, err) == (2, "movie-ui: invalid --port %s (1024 to 65535)\n" % bad)


def test_orphan_info_ignores_the_servers_own_group():
    status = {"state": "lost", "pgid": os.getpgrp()}
    assert lib.orphan_info(status) is None


def test_final2_oversized_orphan_pgid_is_ignored(state, tmp_path):
    lost = mt.make_job(state, ["true"], str(tmp_path),
                       status={"state": "lost", "exit_code": None, "ended": None, "pgid": 2 ** 31,
                               "detected": lib.utc_now()})
    queued = mt.make_job(state, ["true"], str(tmp_path))
    try:
        assert lib.orphan_info(mt.status_of(state, lost)) is None
        assert lib.dispatch_tick(state, mt.WS) == queued
    finally:
        # mt.kill_everything would os.killpg the oversized pgid and overflow
        lib.write_status(lib.job_dir(state, lost), {"state": "lost", "pgid": None})
