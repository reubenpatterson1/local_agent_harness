"""Offline tests for bin/story-server (S1-S18, per
docs/superpowers/plans/2026-09-17-story-server-lifecycle-plan.md).

Run with: cd <workspace> && python3 -m pytest tests/test_story_server.py -q
(PATH python3 3.13.0 + pytest 8.3.4; /usr/bin/python3 3.9.6 has no pytest, but
bin/story-server still uses /usr/bin/python3 internally via $PY.)

No test ever binds the real port 8177, starts a real model, or touches Metal/MLX.
Every server-shaped process in this file is a stub bound to an ephemeral port
(_free_port) under a per-test tmp_path, and every test's teardown asserts that no
stub process it may have spawned survives.
"""

import json
import os
import re
import socket
import stat
import subprocess
import sys
import time

import pytest

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORY_SERVER = os.path.join(WS, "bin", "story-server")

DEFAULT_TEXT_MODEL_REPO = "Youssofal/Qwen3.6-27B-MTPLX-Optimized-Speed-V2"

STUB_SERVER_PY = '''
import http.server
import json
import os
import sys

PORT = int(sys.argv[1])
MODEL_ID = sys.argv[2] if len(sys.argv) > 2 else "qwen38-6bit"


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send_json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models":
            self._send_json(200, {"object": "list", "data": [
                {"id": MODEL_ID, "object": "model", "root": "qwen38-6bit"}
            ]})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        log_path = os.environ.get("STUB_POST_LOG")
        if log_path:
            with open(log_path, "a") as f:
                f.write(raw.decode("utf-8", "replace") + "\\n")
        if os.environ.get("STUB_CHAT_FAIL") == "1":
            self._send_json(500, {"error": "boom"})
        else:
            self._send_json(200, {"choices": [
                {"message": {"role": "assistant", "content": "ok"}}
            ]})


class Server(http.server.ThreadingHTTPServer):
    allow_reuse_address = True


srv = Server(("127.0.0.1", PORT), Handler)
srv.serve_forever()
'''

# stub-bin/vllm -- must be named `vllm` so `/bin/ps -o command=` contains the literal
# `vllm serve` that is_server_pid matches. No `exec` (SF-7): the python server runs as a
# foreground child, so the parent keeps its `vllm serve` argv (also the real parent+child
# shape), which is what makes S16 (idempotent second `vision` while SERVING) testable.
VLLM_STUB = """#!/bin/bash
sleep "${STUB_LOAD_DELAY:-1}"
if [ "${STUB_MODE:-bind}" = "never" ]; then while : ; do sleep 5; done; fi
/usr/bin/python3 "$STUB_SERVER_PY" "$STORY_SERVER_PORT" "${STUB_MODEL_ID:-qwen38-6bit}"
"""

# stub-bin/mtplx -- `--version` prints `mtplx ${STUB_MTPLX_VERSION:-2.10.1}` and exits 0.
#
# (R5, measured on hardware 2026-09-17 15:52) The real /opt/homebrew/bin/mtplx is a bash
# wrapper that `exec`s a venv console script which re-execs the framework Python as
# `Python -P -m mtplx.server.openai --model <dir> ... --port <port> ...` in the SAME pid.
# So the pid story-server records for text mode has NO `mtplx serve` in its argv, has no
# children, and holds the listening socket itself. This stub reproduces that exactly:
#   * `exec` (unlike the vllm stub, SF-7) so the recorded pid IS the python one;
#   * the literal tokens `-m mtplx.server.openai` and `--port <port>` in its argv, which
#     is what `is_server_pid` and `serve_cmd_pids` match on;
#   * `$STUB_SERVER_PY` is in argv in BOTH branches, including the never-bind one, so the
#     leak-detection fixture (which pgreps `tmp_path`) can still see and reap the process.
# stub_server.py ignores argv beyond [1] (port) and [2] (model id).
# The never-bind branch must stay a SINGLE line of python `-c` source: `ps -o command=`
# prints embedded newlines verbatim, which would split the process's ps line and hide the
# matched tokens from serve_cmd_pids' line-oriented awk.
MTPLX_STUB = """#!/bin/bash
if [ "${1:-}" = "--version" ]; then
    echo "mtplx ${STUB_MTPLX_VERSION:-2.10.1}"
    exit 0
fi
sleep "${STUB_LOAD_DELAY:-1}"
if [ "${STUB_MODE:-bind}" = "never" ]; then
    exec /usr/bin/python3 -c 'import time; time.sleep(600)' "$STUB_SERVER_PY" \
        -m mtplx.server.openai --port "$STORY_SERVER_PORT"
fi
exec /usr/bin/python3 "$STUB_SERVER_PY" "$STORY_SERVER_PORT" "${STUB_MODEL_ID:-qwen38-6bit}" \
    -m mtplx.server.openai --port "$STORY_SERVER_PORT" \
    --model-id "${STUB_MODEL_ID:-qwen38-6bit}"
"""

# stub-bin/mlx-vlm-python -- stands in for $STORY_SERVER_MLX_VLM_PYTHON. Two forms:
# `-c "import mlx_vlm"` (the M29 preflight import check: exit 0/1 per
# STUB_MLX_VLM_IMPORTABLE) and `-m mlx_vlm.server --model ... --port ...` (the real
# serve invocation). No `exec` (SF-7, mirrors VLLM_STUB): the python server runs as a
# foreground child, so `ps` sees THIS script's own `-m mlx_vlm.server ...` argv, which
# is what is_server_pid/serve_cmd_pids match on.
MLX_VLM_STUB = """#!/bin/bash
if [ "${1:-}" = "-c" ]; then
    if [ "${STUB_MLX_VLM_IMPORTABLE:-1}" = "1" ]; then exit 0; else exit 1; fi
fi
sleep "${STUB_LOAD_DELAY:-1}"
if [ "${STUB_MODE:-bind}" = "never" ]; then while : ; do sleep 5; done; fi
/usr/bin/python3 "$STUB_SERVER_PY" "$STORY_SERVER_PORT" "${STUB_MODEL_ID:-qwen38-6bit}"
"""


# ---------------------------------------------------------------------------
# harness helpers
# ---------------------------------------------------------------------------

def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _write_executable(path, content):
    with open(path, "w") as f:
        f.write(content)
    st = os.stat(path)
    os.chmod(path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _base_env(tmp_path, port):
    """A fresh STORY_SERVER_* environment rooted entirely under tmp_path. Never binds
    8177/8189; STORY_SERVER_PORT is always an ephemeral port from _free_port()."""
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir(exist_ok=True)
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir(exist_ok=True)
    vision_model_dir = tmp_path / "vision-model"
    vision_model_dir.mkdir(exist_ok=True)
    stub_server_py = tmp_path / "stub_server.py"
    stub_server_py.write_text(STUB_SERVER_PY)

    vllm_path = stub_bin / "vllm"
    _write_executable(str(vllm_path), VLLM_STUB)
    mtplx_path = stub_bin / "mtplx"
    _write_executable(str(mtplx_path), MTPLX_STUB)
    mlx_vlm_python_path = stub_bin / "mlx-vlm-python"
    _write_executable(str(mlx_vlm_python_path), MLX_VLM_STUB)

    env = dict(os.environ)
    env["STORY_SERVER_WS"] = str(ws_dir)
    env["STORY_SERVER_PORT"] = str(port)
    env["STORY_SERVER_STATE_DIR"] = str(state_dir)
    env["STORY_SERVER_VLLM_BIN"] = str(vllm_path)
    env["STORY_SERVER_MTPLX_BIN"] = str(mtplx_path)
    env["STORY_SERVER_VISION_MODEL_DIR"] = str(vision_model_dir)
    env["STORY_SERVER_MLX_VLM_PYTHON"] = str(mlx_vlm_python_path)
    env["STORY_SERVER_READY_POLL"] = "1"
    env["STORY_SERVER_WARM_TIMEOUT"] = "10"
    # engine_pids() is host-global, not port-scoped (plan D9/R8). Without this the
    # kill set of every `stop`/timeout/trap path in this suite would include a REAL
    # `VLLM::EngineCore` if one is alive on this host, and the suite would SIGKILL a
    # production vLLM that it never started.
    env["STORY_SERVER_ENGINE_SCAN"] = "0"
    env["STUB_SERVER_PY"] = str(stub_server_py)
    env["STUB_POST_LOG"] = str(tmp_path / "post.log")
    return env


def _run(args, env, timeout=30):
    proc = subprocess.run([STORY_SERVER] + list(args), env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def _pgrep(pattern):
    result = subprocess.run(["/usr/bin/pgrep", "-f", pattern],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    return [p for p in result.stdout.split() if p]


def _count_server_procs(env):
    """How many `vllm serve <vision-model-dir>` launcher processes are alive -- the
    'stub pid' count the plan's S3/S4/S16 cases assert on."""
    return len(_pgrep(env["STORY_SERVER_VISION_MODEL_DIR"]))


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _find_dead_pid():
    p = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
    p.wait()
    return p.pid


def _wait_for_port(port, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise AssertionError("port %d never opened" % port)


def _pid_cmd(pid):
    return subprocess.run(["/bin/ps", "-ww", "-o", "command=", "-p", str(pid)],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           text=True).stdout


def _wait_for_cmd(pid, needle, timeout=10):
    """Block until pid's `ps -o command=` contains needle; return that command text.

    The text-mode stub `exec`s, so its argv changes shape mid-life. Every assertion that
    depends on the post-exec (R5) shape must wait for it, or the case can silently grade
    the pre-exec `mtplx serve` argv instead and stop covering its mutation."""
    deadline = time.monotonic() + timeout
    cmd = ""
    while time.monotonic() < deadline:
        cmd = _pid_cmd(pid)
        if needle in cmd:
            return cmd
        time.sleep(0.1)
    raise AssertionError("pid %s argv never contained %r (last: %r)" % (pid, needle, cmd))


def _wait_for_file(path, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(path):
            return
        time.sleep(0.1)
    raise AssertionError("%s never appeared" % path)


@pytest.fixture(autouse=True)
def _no_leaked_stub_processes(tmp_path):
    yield
    pattern = str(tmp_path)
    # Detect first, clean up second. pkill-then-assert can never fail, so it silently
    # repairs a leak instead of reporting it; the settle window below absorbs the
    # normal case where a stub is mid-teardown when the test body returns.
    deadline = time.monotonic() + 5
    survivors = _pgrep(pattern)
    while survivors and time.monotonic() < deadline:
        time.sleep(0.2)
        survivors = _pgrep(pattern)
    subprocess.run(["/usr/bin/pkill", "-9", "-f", pattern],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    forced = _pgrep(pattern)
    deadline = time.monotonic() + 5
    while forced and time.monotonic() < deadline:
        time.sleep(0.2)
        forced = _pgrep(pattern)
    assert survivors == [], ("leaked stub process(es) matching %s: %s (SIGKILLed by "
                             "this fixture)" % (pattern, survivors))
    assert forced == [], "unkillable process(es) matching %s: %s" % (pattern, forced)


# ---------------------------------------------------------------------------
# S1
# ---------------------------------------------------------------------------

def test_s1_usage():
    for args in ([], ["bogus"], ["vision", "extra"]):
        proc = subprocess.run([STORY_SERVER] + args, env=dict(os.environ),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, timeout=10)
        assert proc.returncode == 2, args
        assert proc.stderr == "usage: story-server [vision|text|mlx-vision|status|stop]\n", args


# ---------------------------------------------------------------------------
# S2
# ---------------------------------------------------------------------------

def test_s2_missing_lsof(tmp_path):
    port = _free_port()
    env = _base_env(tmp_path, port)
    env["STORY_SERVER_LSOF"] = "/nonexistent/lsof"
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")

    rc, out, err = _run(["vision"], env)
    assert rc == 4
    assert "/nonexistent/lsof" in err
    assert "is missing or not executable" in err

    time.sleep(1)
    assert _count_server_procs(env) == 0
    assert not os.path.exists(mode_file)


# ---------------------------------------------------------------------------
# S3
# ---------------------------------------------------------------------------

def test_s3_happy_vision(tmp_path):
    port = _free_port()
    env = _base_env(tmp_path, port)
    env["STUB_LOAD_DELAY"] = "2"
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")

    rc, out, err = _run(["vision"], env, timeout=60)
    try:
        assert rc == 0
        assert "launched vision server, pid" in out          # M16
        assert "ready after" in out                            # M17
        assert "warm-up OK after" in out                       # M21
        with open(mode_file) as f:
            content = f.read()
        assert re.match(r"^vision \d+ \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n$", content)
        assert _count_server_procs(env) == 1
    finally:
        _run(["stop"], env, timeout=30)


# ---------------------------------------------------------------------------
# S4 + S5 (S5 continues S4's loader, per the plan)
# ---------------------------------------------------------------------------

def test_s4_s5_idempotence_during_load_and_stop(tmp_path):
    port = _free_port()
    env = _base_env(tmp_path, port)
    env["STUB_LOAD_DELAY"] = "30"
    env["STORY_SERVER_READY_TIMEOUT"] = "60"
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")
    standdown = os.path.join(env["STORY_SERVER_STATE_DIR"], "stand-down")

    proc1 = subprocess.Popen([STORY_SERVER, "vision"], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        _wait_for_file(mode_file, timeout=10)

        # S4: idempotence during load.
        rc2, out2, err2 = _run(["vision"], env, timeout=30)
        assert rc2 == 0
        assert "already running" in out2                       # M05
        assert _count_server_procs(env) == 1

        rc3, out3, err3 = _run(["text"], env, timeout=30)
        assert rc3 == 3
        assert "REFUSING" in err3 and "already running" in err3  # M06

        # S5: stop while the loader has not bound the port yet.
        with open(mode_file) as f:
            _mode, mode_pid_s, _ts = f.read().split()
        mode_pid = int(mode_pid_s)

        rc4, out4, err4 = _run(["stop"], env, timeout=90)
        assert rc4 == 0
        assert "stopped pid(s)" in out4 and mode_pid_s in out4  # M24
        assert not _pid_alive(mode_pid)
        assert not os.path.exists(mode_file)
        assert os.path.exists(standdown)

        out1, err1 = proc1.communicate(timeout=90)
        assert proc1.returncode == 5
        assert "FAILED" in err1                                 # M18
    finally:
        if proc1.poll() is None:
            proc1.kill()
            proc1.wait(timeout=10)


# ---------------------------------------------------------------------------
# S6
# ---------------------------------------------------------------------------

def test_s6_readiness_timeout(tmp_path):
    port = _free_port()
    env = _base_env(tmp_path, port)
    env["STUB_MODE"] = "never"
    env["STORY_SERVER_READY_TIMEOUT"] = "3"
    env["STORY_SERVER_READY_POLL"] = "1"
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")

    rc, out, err = _run(["vision"], env, timeout=30)
    assert rc == 5
    assert "TIMEOUT" in err
    assert not os.path.exists(mode_file)

    time.sleep(1)
    assert _count_server_procs(env) == 0


# ---------------------------------------------------------------------------
# S7
# ---------------------------------------------------------------------------

def test_s7_status_states(tmp_path):
    port = _free_port()
    env = _base_env(tmp_path, port)
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")

    # STOPPED
    rc, out, err = _run(["status"], env)
    assert rc == 0
    assert "state:          STOPPED" in out
    assert not os.path.exists(mode_file)

    # LOADING: a direct Popen of the stub (never binds) plus a hand-written mode file.
    loading_env = dict(env)
    loading_env["STUB_MODE"] = "never"
    proc = subprocess.Popen([env["STORY_SERVER_VLLM_BIN"], "serve"], env=loading_env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        recorded = "vision %d 2026-09-17T00:00:00Z\n" % proc.pid
        with open(mode_file, "w") as f:
            f.write(recorded)
        rc, out, err = _run(["status"], env)
        assert rc == 0
        assert "state:          LOADING vision" in out
        with open(mode_file) as f:
            assert f.read() == recorded   # status must not touch a stale/live mode file
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
    os.remove(mode_file)

    # SERVING: the stub actually bound.
    serving_env = dict(env)
    serving_env["STUB_LOAD_DELAY"] = "0"
    rc, out, err = _run(["vision"], serving_env, timeout=30)
    assert rc == 0
    try:
        rc, out, err = _run(["status"], env)
        assert rc == 0
        assert "state:          SERVING vision" in out
    finally:
        _run(["stop"], env, timeout=30)

    # FOREIGN: a decoy server, no mode file.
    assert not os.path.exists(mode_file)
    decoy = subprocess.Popen(
        [sys.executable, env["STUB_SERVER_PY"], str(port), "some-other-model"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _wait_for_port(port, timeout=10)
        rc, out, err = _run(["status"], env)
        assert rc == 0
        assert re.search(r"state:\s+FOREIGN pid \d+", out)
        assert not os.path.exists(mode_file)
    finally:
        decoy.terminate()
        decoy.wait(timeout=10)


# ---------------------------------------------------------------------------
# S8
# ---------------------------------------------------------------------------

def test_s8_json_extraction(tmp_path):
    port = _free_port()
    env = _base_env(tmp_path, port)
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")

    # decoy body: data[0].id == "some-other-model", root == "qwen38-6bit"
    decoy = subprocess.Popen(
        [sys.executable, env["STUB_SERVER_PY"], str(port), "some-other-model"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _wait_for_port(port, timeout=10)
        rc, out, err = _run(["vision"], env, timeout=30)
        assert rc == 3
        assert "not serving" in err          # M09
        assert "already serves" not in err   # not M08
    finally:
        decoy.terminate()
        decoy.wait(timeout=10)
    assert not os.path.exists(mode_file)

    # data[0].id == "qwen38-6bit"
    decoy2 = subprocess.Popen(
        [sys.executable, env["STUB_SERVER_PY"], str(port), "qwen38-6bit"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _wait_for_port(port, timeout=10)
        rc, out, err = _run(["vision"], env, timeout=30)
        assert rc == 3
        assert "already serves" in err       # M08
    finally:
        decoy2.terminate()
        decoy2.wait(timeout=10)


# ---------------------------------------------------------------------------
# S9
# ---------------------------------------------------------------------------

def test_s9_standdown(tmp_path):
    port = _free_port()
    env = _base_env(tmp_path, port)
    env["STUB_LOAD_DELAY"] = "0"
    standdown = os.path.join(env["STORY_SERVER_STATE_DIR"], "stand-down")

    assert not os.path.exists(standdown)
    rc, out, err = _run(["vision"], env, timeout=30)
    try:
        assert rc == 0
        assert "wrote the qwen-serve-guard stand-down marker" in out   # M14
        st = os.stat(standdown)
        assert stat.S_IMODE(st.st_mode) == 0o644
        with open(standdown) as f:
            content = f.read()
        assert "qwen3_xml" in content
        assert "story-server owns port" in content
    finally:
        _run(["stop"], env, timeout=30)

    sentinel = b"SENTINEL BYTES\n"
    with open(standdown, "wb") as f:
        f.write(sentinel)

    rc, out, err = _run(["vision"], env, timeout=30)
    try:
        assert rc == 0
        assert "stand-down marker already present, leaving its bytes unchanged" in out  # M15
        with open(standdown, "rb") as f:
            assert f.read() == sentinel
    finally:
        _run(["stop"], env, timeout=30)


# ---------------------------------------------------------------------------
# S10
# ---------------------------------------------------------------------------

def test_s10_stop_stale_mode_file(tmp_path):
    port = _free_port()
    env = _base_env(tmp_path, port)
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")
    standdown = os.path.join(env["STORY_SERVER_STATE_DIR"], "stand-down")

    with open(standdown, "w") as f:
        f.write("pre-existing sentinel\n")

    dead_pid = _find_dead_pid()
    with open(mode_file, "w") as f:
        f.write("vision %d 2026-09-17T00:00:00Z\n" % dead_pid)

    rc, out, err = _run(["stop"], env, timeout=30)
    assert rc == 0
    assert "nothing to stop" in out                                  # M23
    assert not os.path.exists(mode_file)
    with open(standdown) as f:
        assert f.read() == "pre-existing sentinel\n"
    assert "leaving the qwen-serve-guard stand-down marker in place" in out   # M26


# ---------------------------------------------------------------------------
# S11
# ---------------------------------------------------------------------------

def test_s11_stop_foreign_listener(tmp_path):
    port = _free_port()
    env = _base_env(tmp_path, port)
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")

    decoy = subprocess.Popen(
        [sys.executable, env["STUB_SERVER_PY"], str(port), "some-other-model"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _wait_for_port(port, timeout=10)
        rc, out, err = _run(["stop"], env, timeout=30)
        assert rc == 3
        assert "REFUSING" in err and "not a story server" in err     # M27
        assert _pid_alive(decoy.pid)
        # _pid_alive() is zombie-blind: kill(pid, 0) succeeds on a reaped-but-unwaited
        # child, so under the M-S11 mutation (kill every lsof pid) the pid assertion
        # above can still pass. Prove the decoy is still SERVING, which it cannot be.
        _wait_for_port(port, timeout=5)
        assert not os.path.exists(mode_file)
    finally:
        decoy.terminate()
        decoy.wait(timeout=10)


# ---------------------------------------------------------------------------
# S12
# ---------------------------------------------------------------------------

def test_s12_text_version_check(tmp_path):
    port = _free_port()
    env = _base_env(tmp_path, port)
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")

    env["STUB_MTPLX_VERSION"] = "2.9.0"
    rc, out, err = _run(["text"], env, timeout=30)
    assert rc == 4
    assert "REFUSING" in err and "mtplx 2.9.0" in err                # M13
    assert not os.path.exists(mode_file)
    assert len(_pgrep(env["STORY_SERVER_MTPLX_BIN"])) == 0

    env["STUB_MTPLX_VERSION"] = "2.10.1"
    env["STUB_LOAD_DELAY"] = "0"
    rc, out, err = _run(["text"], env, timeout=30)
    try:
        assert rc == 0
        assert "ready after" in out                                   # M17
        assert DEFAULT_TEXT_MODEL_REPO in out
    finally:
        _run(["stop"], env, timeout=30)


# ---------------------------------------------------------------------------
# S13
# ---------------------------------------------------------------------------

def test_s13_vision_preflight(tmp_path):
    port = _free_port()
    env = _base_env(tmp_path, port)
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")

    non_exec = tmp_path / "not-executable"
    non_exec.write_text("not a real binary\n")
    env["STORY_SERVER_VLLM_BIN"] = str(non_exec)
    rc, out, err = _run(["vision"], env, timeout=30)
    assert rc == 4
    assert "needs an executable" in err                               # M10
    assert not os.path.exists(mode_file)

    env2 = _base_env(tmp_path, port)
    dangling = tmp_path / "dangling-vision-model"
    missing_target = tmp_path / "does-not-exist-target"
    os.symlink(str(missing_target), str(dangling))
    env2["STORY_SERVER_VISION_MODEL_DIR"] = str(dangling)
    rc, out, err = _run(["vision"], env2, timeout=30)
    assert rc == 4
    assert "needs the model directory" in err                         # M11
    assert not os.path.exists(mode_file)

    # A symlink to an existing regular FILE. This is the only fixture that separates
    # `[ -d ]` from `[ -e ]`: both are false for a dangling link, so the dangling
    # sub-case above passes either way and gives the M-S13 mutation zero coverage.
    env3 = _base_env(tmp_path, port)
    file_target = tmp_path / "vision-model-target-file"
    file_target.write_text("not a directory\n")
    file_link = tmp_path / "file-vision-model"
    os.symlink(str(file_target), str(file_link))
    env3["STORY_SERVER_VISION_MODEL_DIR"] = str(file_link)
    rc, out, err = _run(["vision"], env3, timeout=30)
    assert rc == 4, "a symlink to a regular file must fail the [ -d ] preflight"
    assert "needs the model directory" in err                         # M11
    assert not os.path.exists(mode_file)


# ---------------------------------------------------------------------------
# S14
# ---------------------------------------------------------------------------

def test_s14_source_guards():
    with open(STORY_SERVER) as f:
        lines = f.readlines()
    text = "".join(lines)

    assert lines[0] == "#!/bin/bash\n"
    assert re.search(r"^set -u\s*$", text, re.MULTILINE)
    assert not re.search(r"^set -e\b", text, re.MULTILINE)

    expected_constants = {
        "STORY_SERVER_WS": "/Users/reubenpatterson/local_model_harness/qwen-agent-workspace",
        "STORY_SERVER_MODEL_ID": "qwen38-6bit",
        "STORY_SERVER_PORT": "8177",
        "STORY_SERVER_VISION_MODEL_DIR": "/Users/reubenpatterson/mlx_models/qwen3-vl",
        "STORY_SERVER_VLLM_BIN": "/Users/reubenpatterson/.venv-vllm-metal/bin/vllm",
        "STORY_SERVER_MTPLX_BIN": "/opt/homebrew/bin/mtplx",
        "STORY_SERVER_MTPLX_VERSION": "2.10.1",
        "STORY_SERVER_TEXT_MODEL_REPO": DEFAULT_TEXT_MODEL_REPO,
        "STORY_SERVER_STATE_DIR": "/Users/reubenpatterson/.qwen-serve-guard",
        "STORY_SERVER_LSOF": "/usr/sbin/lsof",
        "STORY_SERVER_PY": "/usr/bin/python3",
        "STORY_SERVER_READY_TIMEOUT": "840",
        "STORY_SERVER_READY_POLL": "5",
        "STORY_SERVER_WARM_TIMEOUT": "300",
        "STORY_SERVER_ENGINE_SCAN": "1",
        "STORY_SERVER_VISION_GPU_MEM_UTIL": "0.70",
        "STORY_SERVER_MLX_VISION_MODEL_ID": "andrevp/Qwen3.5-9B-Distilled-OPUS-Heretic-MLX-VLM-8bit",
        "STORY_SERVER_MLX_VLM_PYTHON": "python3",
        "STORY_SERVER_MLX_VISION_MAX_TOKENS": "16384",
    }
    assert len(expected_constants) == 19
    for name, default in expected_constants.items():
        pattern = r"\$\{%s:-%s\}" % (re.escape(name), re.escape(default))
        matches = re.findall(pattern, text)
        assert len(matches) == 1, "%s: expected exactly 1 occurrence, found %d" % (name, len(matches))

    for line in lines:
        stripped = line.strip()
        if "8177" in line and "STORY_SERVER_PORT" not in line and not stripped.startswith("#"):
            raise AssertionError("literal 8177 outside the PORT default/comments: %r" % line)

    # Code portions only (strip trailing comments): a prose comment is allowed to
    # mention these words while explaining why they are absent from the code.
    code_lines = [line.split("#", 1)[0] for line in lines]
    code_text = "\n".join(code_lines)

    for token in ("mapfile", "declare -A", "local -A", "${v,,}"):
        assert token not in code_text

    assert 'LSOF="${STORY_SERVER_LSOF:-/usr/sbin/lsof}"' in text

    assert "jq" not in code_text
    for line in code_lines:
        if "qwen38-6bit" in line:
            assert "grep" not in line


# ---------------------------------------------------------------------------
# S15
# ---------------------------------------------------------------------------

def test_s15_warmup(tmp_path):
    port = _free_port()
    env = _base_env(tmp_path, port)
    env["STUB_LOAD_DELAY"] = "0"
    post_log = env["STUB_POST_LOG"]

    rc, out, err = _run(["vision"], env, timeout=30)
    try:
        assert rc == 0
        assert "warm-up OK after" in out                              # M21
        with open(post_log) as f:
            post_lines = [l for l in f.read().splitlines() if l.strip()]
        assert len(post_lines) == 1
        payload = json.loads(post_lines[0])
        assert payload["model"] == "qwen38-6bit"
        assert payload["max_tokens"] == 8
    finally:
        _run(["stop"], env, timeout=30)

    if os.path.exists(post_log):
        os.remove(post_log)
    env["STUB_CHAT_FAIL"] = "1"
    rc, out, err = _run(["vision"], env, timeout=30)
    try:
        assert rc == 0
        assert "WARNING: warm-up produced no content" in out          # M22
        assert "warm-up OK after" not in out
    finally:
        _run(["stop"], env, timeout=30)


# ---------------------------------------------------------------------------
# S16
# ---------------------------------------------------------------------------

def test_s16_second_vision_while_serving(tmp_path):
    port = _free_port()
    env = _base_env(tmp_path, port)
    env["STUB_LOAD_DELAY"] = "0"
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")

    rc, out, err = _run(["vision"], env, timeout=30)
    try:
        assert rc == 0
        with open(mode_file, "rb") as f:
            before = f.read()

        rc2, out2, err2 = _run(["vision"], env, timeout=30)
        assert rc2 == 0
        assert "already running" in out2                              # M05

        with open(mode_file, "rb") as f:
            after = f.read()
        assert before == after
        assert _count_server_procs(env) == 1
    finally:
        _run(["stop"], env, timeout=30)


# ---------------------------------------------------------------------------
# S17 (R5)
# ---------------------------------------------------------------------------

def test_s17_text_serving_mode_pid_and_idempotence(tmp_path):
    """R5, reproduced on hardware 2026-09-17: with a real MTPLX serving, `is_server_pid`
    returned false because the argv is `... -m mtplx.server.openai ...` and never
    `mtplx serve`. Consequences: `status` printed `mode pid: dead` under
    `state: SERVING text`; a second `text` fell through to the S-2 port probe and REFUSED
    with M08 (`already serves ... in unknown mode`, exit 3) instead of M05/exit 0; and
    `vision` called the running mode `unknown` instead of `text`."""
    port = _free_port()
    env = _base_env(tmp_path, port)
    env["STUB_LOAD_DELAY"] = "0"
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")

    rc, out, err = _run(["text"], env, timeout=30)
    try:
        assert rc == 0, err
        assert "ready after" in out                                    # M17
        with open(mode_file) as f:
            recorded_mode, mode_pid_s, _ts = f.read().split()
        assert recorded_mode == "text"

        # The fixture is only faithful if the RECORDED pid carries the module argv and
        # not `mtplx serve`; otherwise S17 grades the wrong pattern (see _wait_for_cmd).
        recorded_cmd = _wait_for_cmd(mode_pid_s, " -m mtplx.server.openai ", timeout=10)
        assert "mtplx serve" not in recorded_cmd, recorded_cmd

        # (a) status: SERVING text with a live mode pid.
        rc, out, err = _run(["status"], env)
        assert rc == 0
        assert "state:          SERVING text" in out
        assert re.search(r"mode pid:\s+alive \(", out), out
        assert not re.search(r"mode pid:\s+dead", out), out
        # `alive` can only come from is_server_pid, and the recorded pid's argv was just
        # asserted to contain the module form and NOT `mtplx serve`, so this line is a
        # direct test of the new pattern. The command text itself is NOT asserted here:
        # PID_CMD_CHARS cuts at 240 and the stub's argv[0] (the framework Python, 126
        # chars) plus a pytest tmp_path push the token past that. On hardware the real
        # argv puts it at column 151, which is what Step 8c greps for.

        # (b) idempotence in the SERVING state (the text analogue of S16).
        with open(mode_file, "rb") as f:
            before = f.read()
        rc2, out2, err2 = _run(["text"], env, timeout=30)
        assert rc2 == 0, err2
        assert "a text server (pid %s) is already running" % mode_pid_s in out2   # M05
        assert "already serves" not in err2                            # not M08
        with open(mode_file, "rb") as f:
            assert f.read() == before
        assert len(_pgrep(env["STUB_SERVER_PY"])) == 1

        # (c) the other mode still refuses, and names `text`, not `unknown`.
        rc3, out3, err3 = _run(["vision"], env, timeout=30)
        assert rc3 == 3
        assert ("REFUSING: a text server (pid %s) is already running" % mode_pid_s) in err3   # M06
        assert "unknown" not in err3, err3
    finally:
        _run(["stop"], env, timeout=30)


# ---------------------------------------------------------------------------
# S18 (R5, MF-C for text)
# ---------------------------------------------------------------------------

def test_s18_stop_text_before_bind_via_serve_cmd_pids(tmp_path):
    """MF-C for text mode: the mode file is gone and the port was never bound, so
    `serve_cmd_pids` is the ONLY thing that can find the loading MTPLX. Its awk predicate
    must carry the R5 module literal or `stop` prints M23 and the loader survives holding
    the memory the render needs."""
    port = _free_port()
    env = _base_env(tmp_path, port)
    env["STUB_LOAD_DELAY"] = "0"
    env["STUB_MODE"] = "never"
    env["STORY_SERVER_READY_TIMEOUT"] = "60"
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")

    proc1 = subprocess.Popen([STORY_SERVER, "text"], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        _wait_for_file(mode_file, timeout=10)
        with open(mode_file) as f:
            _mode, mode_pid_s, _ts = f.read().split()
        mode_pid = int(mode_pid_s)
        cmd = _wait_for_cmd(mode_pid_s, " -m mtplx.server.openai ", timeout=10)
        assert "mtplx serve" not in cmd, cmd

        os.remove(mode_file)          # the Ctrl-C / hand-deleted case

        rc, out, err = _run(["stop"], env, timeout=90)
        assert rc == 0, err
        assert "stopped pid(s)" in out and mode_pid_s in out           # M24
        assert not _pid_alive(mode_pid)

        out1, err1 = proc1.communicate(timeout=90)
        assert proc1.returncode == 5
        assert "FAILED" in err1                                        # M18
    finally:
        if proc1.poll() is None:
            proc1.kill()
            proc1.wait(timeout=10)


# ---------------------------------------------------------------------------
# S19
# ---------------------------------------------------------------------------

def test_s19_vision_gpu_memory_utilization(tmp_path):
    """The vision spawn command passes --gpu-memory-utilization at the configured value
    (default 0.70), per the 2026-09-17 SC10 finding: vLLM-Metal's own default left only
    1.91 GiB available after load, which starved Phase 2-4's swap budget (comfyui_video_
    supervisor's PREFLIGHT_MAX_SWAP_GIB = 3.0). The vllm stub never `exec`s (SF-7), so its
    pid keeps the full `vllm serve ...` argv for as long as it is alive."""
    port = _free_port()
    env = _base_env(tmp_path, port)
    env["STUB_LOAD_DELAY"] = "0"
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")

    rc, out, err = _run(["vision"], env, timeout=30)
    try:
        assert rc == 0
        with open(mode_file) as f:
            _mode, mode_pid_s, _ts = f.read().split()
        cmd = _pid_cmd(int(mode_pid_s))
        assert "--gpu-memory-utilization 0.70" in cmd, cmd
    finally:
        _run(["stop"], env, timeout=30)


# ---------------------------------------------------------------------------
# S20 -- mlx-vision (added 2026-09-29 for the 16GB M1 port)
# ---------------------------------------------------------------------------

def test_s20_mlx_vision_preflight(tmp_path):
    port = _free_port()
    env = _base_env(tmp_path, port)
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")

    env["STORY_SERVER_MLX_VLM_PYTHON"] = "/nonexistent/mlx-vlm-python-xyz"
    rc, out, err = _run(["mlx-vision"], env, timeout=30)
    assert rc == 4
    assert "on PATH or as an absolute path" in err                      # M28
    assert not os.path.exists(mode_file)

    env2 = _base_env(tmp_path, port)
    env2["STUB_MLX_VLM_IMPORTABLE"] = "0"
    rc, out, err = _run(["mlx-vision"], env2, timeout=30)
    assert rc == 4
    assert "mlx_vlm package importable" in err                          # M29
    assert not os.path.exists(mode_file)


def test_s21_happy_mlx_vision(tmp_path):
    port = _free_port()
    env = _base_env(tmp_path, port)
    env["STUB_LOAD_DELAY"] = "2"
    env["STORY_SERVER_MLX_VISION_MODEL_ID"] = "test-mlx-vlm-model"
    env["STUB_MODEL_ID"] = "test-mlx-vlm-model"
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")

    rc, out, err = _run(["mlx-vision"], env, timeout=60)
    try:
        assert rc == 0
        assert "launched mlx-vision server, pid" in out          # M16
        assert "ready after" in out                               # M17
        assert "warm-up OK after" in out                          # M21
        with open(mode_file) as f:
            content = f.read()
        assert re.match(r"^mlx-vision \d+ \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n$", content)

        # is_server_pid/serve_cmd_pids recognize the mlx_vlm.server process: stop
        # must actually find and kill it, not refuse it as a foreign listener.
        rc2, out2, err2 = _run(["stop"], env, timeout=30)
        assert rc2 == 0
        assert "stopped pid(s)" in out2                            # M24
    finally:
        _run(["stop"], env, timeout=30)


def test_s23_mlx_vision_idempotent_during_load(tmp_path):
    """Isolates is_server_pid's mlx_vlm.server pattern specifically: the S-1
    mode-file guard (M05/M07) is the ONE code path with no serve_cmd_pids/
    probe_served_id fallback, unlike cmd_stop's deliberately redundant checks."""
    port = _free_port()
    env = _base_env(tmp_path, port)
    env["STUB_LOAD_DELAY"] = "30"
    env["STORY_SERVER_READY_TIMEOUT"] = "60"
    env["STORY_SERVER_MLX_VISION_MODEL_ID"] = "test-mlx-vlm-model"
    env["STUB_MODEL_ID"] = "test-mlx-vlm-model"
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")

    proc1 = subprocess.Popen([STORY_SERVER, "mlx-vision"], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        _wait_for_file(mode_file, timeout=10)

        rc2, out2, err2 = _run(["mlx-vision"], env, timeout=30)
        assert rc2 == 0
        assert "already running" in out2                          # M05, not M07

        rc3, out3, err3 = _run(["stop"], env, timeout=90)
        assert rc3 == 0

        out1, err1 = proc1.communicate(timeout=90)
        assert proc1.returncode == 5
    finally:
        if proc1.poll() is None:
            proc1.kill()
            proc1.wait(timeout=10)


def test_s22_mlx_vision_cross_mode_refusal(tmp_path):
    """The existing mode-file guard (S-1) is already generic across any two distinct
    MODE values -- this proves it also covers vision vs. mlx-vision, not just
    vision vs. text, with no code change needed there."""
    port = _free_port()
    env = _base_env(tmp_path, port)
    env["STUB_LOAD_DELAY"] = "30"
    env["STORY_SERVER_READY_TIMEOUT"] = "60"
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")

    proc1 = subprocess.Popen([STORY_SERVER, "vision"], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        _wait_for_file(mode_file, timeout=10)

        rc2, out2, err2 = _run(["mlx-vision"], env, timeout=30)
        assert rc2 == 3
        assert "REFUSING" in err2 and "already running" in err2   # M06

        rc3, out3, err3 = _run(["stop"], env, timeout=90)
        assert rc3 == 0

        out1, err1 = proc1.communicate(timeout=90)
        assert proc1.returncode == 5
    finally:
        if proc1.poll() is None:
            proc1.kill()
            proc1.wait(timeout=10)
