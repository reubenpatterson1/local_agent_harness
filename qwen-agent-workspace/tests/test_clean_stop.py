"""Tests for bin/pipeline-stop and bin/story-server-restore (spec
docs/superpowers/specs/2026-10-21-clean-stop-design.md).

Run from the workspace root: python3 -m pytest tests/test_clean_stop.py
"""

import importlib.machinery
import os
import signal
import socket
import subprocess
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(WS, "tests"))

import test_story_server as tss  # noqa: E402  (VLR8 uses its _base_env stubs)
stop = importlib.machinery.SourceFileLoader(
    "pipeline_stop", os.path.join(WS, "bin", "pipeline-stop")).load_module()
RESTORE = os.path.join(WS, "bin", "story-server-restore")
PY = "/opt/homebrew/Cellar/python@3.12/3.12.15/Frameworks/Python.framework/Versions/3.12/" \
     "Resources/Python.app/Contents/MacOS/Python"


def test_cs1_classify():
    cases = [
        (PY + " /w/bin/character create kyra --seed-image /s.png", "job"),
        (PY + " /w/bin/character train kyra --video", "job"),
        (PY + " bin/action create kick --clip a.mp4", "job"),
        (PY + " bin/character create t --seed-image /h/.local/share/qwen-agent/movie-ui/uploads/"
              "ab.png --no-review", "job"),
        (PY + " /w/bin/ltx-movie a story --story-id s", "job"),
        ("/bin/bash /w/bin/character-train-vlm /py kyra --video", "job"),
        ("/bin/bash /w/bin/action-train-vlm /py kick", "job"),
        (PY + " /w/character_dataset.py qwenedit --spec /x.json", "worker"),
        (PY + " /w/character_dataset.py zimage --spec /x.json", "worker"),
        ("/x/.venv/bin/python /x/.venv/bin/ltx-2-mlx generate --model m", "worker"),
        ("/x/.venv/bin/python /x/.venv/bin/ltx-2-mlx train --config c", "worker"),
        ("/x/mflux/.venv/bin/mflux-train --config c", "worker"),
        (PY + " /w/bin/ltx-mlx-render m.json o.mp4", "worker"),
        (PY + " /w/bin/character list", None),
        (PY + " /w/bin/character show kyra", None),
        (PY + " bin/movie-ui", None),
        (PY + " /w/bin/movie-ui-job --grace 15.0 /j", None),
        ("/bin/bash /w/bin/story-server mlx-vision", None),
        ("/py -m mlx_vlm.server --model /m --port 8177", None),
        ("vim notes-ltx-2-mlx-train.txt", None),
    ]
    for command, kind in cases:
        assert stop.classify(command) == kind, command


def test_cs2_targets_and_descendants():
    rows = [(10, 1, PY + " /w/bin/character create kyra --no-review"),
            (11, 10, PY + " /w/character_dataset.py qwenedit --spec s"),
            (12, 11, "/usr/bin/some-helper"),
            (13, 10, "/bin/bash /w/bin/story-server mlx-vision"),
            (14, 13, "/py -m mlx_vlm.server --port 8177"),
            (20, 1, PY + " /w/bin/pipeline-stop")]
    found = stop.targets(rows, me={20, 1})
    assert {pid: kind for pid, (kind, _) in found.items()} == {10: "job", 11: "worker"}
    # The story server a cleanup started (13, 14) is never a descendant to signal.
    assert stop.descendants(rows, [10]) == {11, 12}


def test_cs3_shown_drops_the_interpreter():
    assert stop.shown(PY + " /w/bin/character create kyra") == "/w/bin/character create kyra"
    assert stop.shown("/bin/bash /w/bin/action-train-vlm") == "/bin/bash /w/bin/action-train-vlm"


def _fake_story_server(tmp_path, state="STOPPED", sleep=0, lock_delay="0", serve=True):
    """F-SS (VLM lifecycle spec 11.2): `status` prints SERVING mlx-vision once <tmp>/started
    exists, else `state`; `lockinfo` prints <tmp>/lockinfo, else a free lock; any other argument
    appends "<arg> sid=<sid> pgid=<pgid> ppid=<ppid> pid=<pid>" to calls.txt, then (unless
    lock_delay is "never") sleeps lock_delay and writes a held lockinfo line naming itself,
    sleeps `sleep`, touches <tmp>/started (when serve) and writes a free lockinfo line."""
    calls = tmp_path / "calls.txt"
    script = tmp_path / "story-server"
    script.write_text(
        "#!/bin/bash\n"
        "T='%s'\n"
        "if [ \"$1\" = status ]; then\n"
        "    if [ -e \"$T/started\" ]; then echo '  state:          SERVING mlx-vision'\n"
        "    else echo '  state:          %s'; fi\n"
        "    exit 0\n"
        "fi\n"
        "if [ \"$1\" = lockinfo ]; then\n"
        "    if [ -e \"$T/lockinfo\" ]; then cat \"$T/lockinfo\"; else echo 'lock: free path=x'; fi\n"
        "    exit 0\n"
        "fi\n"
        "echo \"$1 sid=$(/usr/bin/python3 -c 'import os; print(os.getsid(0))')"
        " pgid=$(ps -o pgid= -p $$ | tr -d ' ') ppid=$(ps -o ppid= -p $$ | tr -d ' ') pid=$$\""
        " >> \"$T/calls.txt\"\n"
        "if [ '%s' != never ]; then\n"
        "    sleep %s\n"
        "    echo \"lock: held pid=$$ cmd=$1 since=x path=x\" > \"$T/lockinfo\"\n"
        "fi\n"
        "sleep %s\n"
        "if [ '%s' = 1 ]; then touch \"$T/started\"; fi\n"
        "echo 'lock: free path=x' > \"$T/lockinfo\"\n"
        % (tmp_path, state, lock_delay, lock_delay, sleep, "1" if serve else "0"))
    script.chmod(0o755)
    return str(script), calls


def _calls(calls):
    """calls.txt as [{"arg", "sid", "pgid", "ppid", "pid"}] (ints for the numbers)."""
    out = []
    for line in calls.read_text().splitlines():
        words = line.split()
        row = {"arg": words[0]}
        row.update((k, int(v)) for k, v in (w.split("=", 1) for w in words[1:]))
        out.append(row)
    return out


def _detached_sleeper(seconds):
    """The pid of a `sleep` whose parent is launchd, so its exit is reaped at once (an unreaped
    child of this test would look alive to kill -0)."""
    out = subprocess.run(["/bin/sh", "-c", "/bin/sleep %s >/dev/null 2>&1 & echo $!" % seconds],
                         capture_output=True, text=True, timeout=10).stdout
    return int(out)


def _kill_fakes(calls):
    """Teardown: SIGKILL the process group of every fake start recorded in calls.txt."""
    if not calls.exists():
        return
    for row in _calls(calls):
        try:
            os.killpg(row["pgid"], signal.SIGKILL)
        except OSError:
            pass


def _run_restore(tmp_path, script, *args):
    env = dict(os.environ, STORY_SERVER_RESTORE_BIN=script, HOME=str(tmp_path))
    return subprocess.run([sys.executable, RESTORE] + list(args), env=env, capture_output=True,
                          text=True, timeout=30)


def test_cs4_restore_starts_in_its_own_session(tmp_path):
    script, calls = _fake_story_server(tmp_path)
    result = _run_restore(tmp_path, script, "--wait")
    assert result.returncode == 0, result.stderr
    assert "own session" in result.stdout
    line = calls.read_text().split()
    assert line[0] == "mlx-vision"
    # A new session: its process group is not the caller's.
    assert line[2] != "pgid=%d" % os.getpgid(0)


def test_cs5_restore_is_a_no_op_when_serving(tmp_path):
    script, calls = _fake_story_server(tmp_path, state="SERVING mlx-vision")
    result = _run_restore(tmp_path, script)
    assert result.returncode == 0 and "already serving mlx-vision" in result.stdout
    assert not calls.exists()


def test_cs6_restore_without_wait_returns_at_once(tmp_path):
    script, calls = _fake_story_server(tmp_path, sleep=5)
    started = time.monotonic()
    result = _run_restore(tmp_path, script)
    assert result.returncode == 0 and time.monotonic() - started < 4
    for _ in range(50):
        if calls.exists():
            break
        time.sleep(0.1)
    assert calls.read_text().startswith("mlx-vision")
    os.killpg(int(calls.read_text().split("pgid=")[1].split()[0]), signal.SIGTERM)


def test_cs7_restore_usage():
    result = subprocess.run([sys.executable, RESTORE, "a", "b"], capture_output=True, text=True)
    assert result.returncode == 2 and "usage" in result.stderr


# ---------------------------------------------------------------------------
# VLR1-VLR9, Review Focus 3: the lock-aware, double-forking restore (VLM lifecycle spec VRS1-VRS5)
# ---------------------------------------------------------------------------

def _wait_for(predicate, timeout):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met within %.1f s" % timeout)
        time.sleep(0.05)


def _ppid(pid):
    return subprocess.run(["/bin/ps", "-o", "ppid=", "-p", str(pid)], capture_output=True,
                          text=True).stdout.strip()


def test_vlr1_double_fork(tmp_path):
    script, calls = _fake_story_server(tmp_path, sleep=5)
    try:
        result = _run_restore(tmp_path, script)
        assert result.returncode == 0, result.stderr
        row = _calls(calls)[0]
        assert row["arg"] == "mlx-vision"
        # The launcher has exited by the time the restore returns (launch() waits for it), so
        # the start's parent is launchd; the fake's own early ppid snapshot can race that exit.
        assert _ppid(row["pid"]) == "1"
        assert row["sid"] != os.getsid(0) and row["pgid"] != os.getpgid(0)
        assert row["sid"] == row["pid"] == row["pgid"]
    finally:
        _kill_fakes(calls)


def test_vlr2_wait_returns_on_serving(tmp_path):
    script, calls = _fake_story_server(tmp_path, sleep=1)
    result = _run_restore(tmp_path, script, "--wait")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "started").exists()
    never = tmp_path / "never"
    never.mkdir()
    script, calls = _fake_story_server(never, sleep=1, serve=False)
    result = _run_restore(never, script, "--wait")
    assert result.returncode == 1
    assert _calls(calls)[0]["arg"] == "mlx-vision"


def test_vlr3_a_start_in_progress_starts_nothing(tmp_path):
    script, calls = _fake_story_server(tmp_path)
    sleeper = _detached_sleeper(3)
    (tmp_path / "lockinfo").write_text("lock: held pid=%d cmd=mlx-vision since=x path=x\n" % sleeper)
    result = _run_restore(tmp_path, script)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ("story-server-restore: a story-server mlx-vision start is already in "
                             "progress (pid %d)\n" % sleeper)
    assert not calls.exists()
    (tmp_path / "started").touch()
    started = time.monotonic()
    result = _run_restore(tmp_path, script, "--wait")
    assert result.returncode == 0, result.stderr
    assert time.monotonic() - started >= 1.0
    assert not tss._pid_alive(sleeper)
    assert not calls.exists()


def test_vlr4_a_stop_holder_does_not_block_a_launch(tmp_path):
    script, calls = _fake_story_server(tmp_path, sleep=1)
    (tmp_path / "lockinfo").write_text("lock: held pid=%d cmd=stop since=x path=x\n" % os.getpid())
    result = _run_restore(tmp_path, script)
    try:
        assert result.returncode == 0, result.stderr
        assert "starting story-server mlx-vision" in result.stdout
        _wait_for(calls.exists, 5)
        assert _calls(calls)[0]["arg"] == "mlx-vision"
    finally:
        _kill_fakes(calls)


def test_vlr5_wait_times_out(tmp_path):
    script, calls = _fake_story_server(tmp_path)
    sleeper = _detached_sleeper(30)
    (tmp_path / "lockinfo").write_text("lock: held pid=%d cmd=mlx-vision since=x path=x\n" % sleeper)
    env = dict(os.environ, STORY_SERVER_RESTORE_BIN=script, HOME=str(tmp_path),
               STORY_SERVER_RESTORE_WAIT_S="2")
    try:
        result = subprocess.run([sys.executable, RESTORE, "--wait"], env=env, capture_output=True,
                                text=True, timeout=30)
        assert result.returncode == 1
        assert result.stderr == ("story-server-restore: TIMEOUT: story-server mlx-vision did not "
                                 "finish within 2 s\n")
        assert not calls.exists()
    finally:
        os.kill(sleeper, signal.SIGKILL)


def test_vlr6_no_ps_scan():
    with open(RESTORE, encoding="utf-8") as f:
        source = f.read()
    assert '"ps"' not in source and "-axo" not in source and "start_in_progress" not in source


def test_vlr7_already_serving(tmp_path):
    script, calls = _fake_story_server(tmp_path, state="SERVING mlx-vision")
    result = _run_restore(tmp_path, script, "--wait")
    assert result.returncode == 0
    assert result.stdout == "story-server-restore: already serving mlx-vision\n"
    assert not calls.exists()


def test_vlr8_two_concurrent_restores_start_one_server(tmp_path):
    port = tss._free_port()
    env = tss._base_env(tmp_path, port)
    env["STUB_LOAD_DELAY"] = "3"
    env["STORY_SERVER_MLX_VISION_MODEL_ID"] = "test-mlx-vlm-model"
    env["STUB_MODEL_ID"] = "test-mlx-vlm-model"
    env["STORY_SERVER_RESTORE_BIN"] = tss.STORY_SERVER
    env["HOME"] = str(tmp_path)
    stub = env["STORY_SERVER_MLX_VLM_PYTHON"]
    try:
        procs = [subprocess.Popen([sys.executable, RESTORE], env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) for _ in range(2)]
        for p in procs:
            p.communicate(timeout=60)
            assert p.returncode == 0
        log = os.path.join(str(tmp_path), ".local", "share", "qwen-agent", "story-server-restore.log")
        _wait_for(lambda: "warm-up OK" in open(log).read(), 60)
        assert len(tss._pgrep(stub + " -m mlx_vlm.server")) == 1
        with open(log) as f:
            text = f.read()
        assert text.count("launched mlx-vision server, pid") == 1
        assert text.count("start (story-server pid") + text.count("already serving") <= 1
    finally:
        subprocess.run([tss.STORY_SERVER, "stop"], env=env, capture_output=True, timeout=90)


def test_vlr9_launch_waits_for_the_lock(tmp_path):
    cases = (("1", 30, 1.0, 5.0, "held"), ("never", 3, 3.0, 6.0, "free"),
             ("never", 30, 10.0, 13.0, None))
    for i, (lock_delay, sleep, low, high, lockinfo) in enumerate(cases):
        root = tmp_path / ("case%d" % i)
        root.mkdir()
        script, calls = _fake_story_server(root, sleep=sleep, lock_delay=lock_delay)
        try:
            started = time.monotonic()
            result = _run_restore(root, script)
            took = time.monotonic() - started
            assert result.returncode == 0, result.stderr
            assert low <= took < high, (lock_delay, sleep, took)
            if lockinfo == "held":
                assert (root / "lockinfo").read_text().startswith("lock: held pid=%d cmd=mlx-vision"
                                                                  % _calls(calls)[0]["pid"])
            elif lockinfo == "free":
                assert (root / "lockinfo").read_text() == "lock: free path=x\n"
            else:
                assert not (root / "lockinfo").exists()
        finally:
            _kill_fakes(calls)


def test_review_focus_3_restore_with_a_story_server_without_lockinfo(tmp_path):
    """A story-server from an older release prints its usage and exits 2 for `lockinfo`; the
    restore must read that as a free lock and still launch (spec VRS2)."""
    calls = tmp_path / "calls.txt"
    script = tmp_path / "story-server"
    script.write_text(
        "#!/bin/bash\n"
        "case \"$1\" in\n"
        "    status) echo '  state:          STOPPED'; exit 0 ;;\n"
        "    vision|text|mlx-vision|stop) echo \"$1 pid=$$\" >> '%s'; sleep 1; exit 0 ;;\n"
        "esac\n"
        "echo 'usage: story-server [vision|text|mlx-vision|status|stop]' >&2\n"
        "exit 2\n" % calls)
    script.chmod(0o755)
    result = _run_restore(tmp_path, str(script))
    assert result.returncode == 0, result.stderr
    assert "starting story-server mlx-vision" in result.stdout
    _wait_for(calls.exists, 5)
    assert calls.read_text().split()[0] == "mlx-vision"
