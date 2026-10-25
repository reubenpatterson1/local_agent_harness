"""Tests for the VLM lifecycle at job boundaries (docs/superpowers/specs/2026-10-25-vlm-lifecycle-
design.md, Section 11: VL1-VL28 and Review Focus 1, 2, 4, 5): the per-job vlm policy, the
port-scoped health check, the runner's preflight and postflight, the startup restore, V2's warn
and the page gate.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_vlm_lifecycle.py
Stdlib plus pytest. Every story-server and story-server-restore here is F-TOOLS (make_fake_tools),
every VLM is F-HTTP (FakeVLM) on an ephemeral 127.0.0.1 port, every HOME is temporary, and the
conftest's vlm_lifecycle_isolation keeps the lifecycle off unless a test turns it on with
lifecycle_on(); VL22 alone runs the real bin/story-server-restore, against a fake story-server.
"""

import fcntl
import http.server
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time

import pytest

import movie_ui_testutil as mt
import movie_ui_lib as lib


@pytest.fixture
def state(monkeypatch, tmp_path):
    path = mt.set_home(monkeypatch, tmp_path)
    monkeypatch.setattr(lib, "VLM_RECOVERY", [])
    monkeypatch.setattr(lib, "RESTORERS", [])
    yield path
    mt.kill_everything(path)


@pytest.fixture
def http_env(monkeypatch, tmp_path):
    state = mt.set_home(monkeypatch, tmp_path)
    monkeypatch.setattr(lib, "VLM_RECOVERY", [])
    ws = mt.make_stub_workspace(tmp_path)
    running = mt.Running(state)
    yield {"state": state, "ws": ws, "srv": running, "tmp": str(tmp_path)}
    running.close()
    mt.kill_everything(state)


def _write_story(ws, story_id):
    sdir = lib.story_dir(ws, story_id)
    os.makedirs(sdir, exist_ok=True)
    with open(os.path.join(sdir, "story.md"), "w", encoding="utf-8") as f:
        f.write("## Panel 1 -- Shot 1\nImage: a quiet road.\nMotion: the camera drifts.\n")


# --- the constants, the switches and the isolation (spec 2.5, VR1, 11.1) ---------------------

def test_vlm_constants_and_isolation(tmp_path):
    assert (lib.VLM_MODE, lib.VLM_POLICIES) == ("mlx-vision", ("required", "forbidden", "any"))
    assert (lib.VLM_STATUS_TIMEOUT_S, lib.VLM_HTTP_TIMEOUT_S, lib.VLM_COMPLETION_TIMEOUT_S,
            lib.VLM_PREFLIGHT_TIMEOUT_S, lib.VLM_POSTFLIGHT_TIMEOUT_S, lib.VLM_TOOL_KILL_WAIT_S,
            lib.VLM_MAX_BODY) == (60, 10, 120, 6900, 90, 5, 1048576)
    assert lib.VLM_RESTORE_LOG_TEXT == "~/.local/share/qwen-agent/story-server-restore.log"
    assert isinstance(lib.VLM_RECOVERY, list) and isinstance(lib.RESTORERS, list)
    assert os.environ["MOVIE_UI_VLM_LIFECYCLE"] == "0"
    assert os.environ["MOVIE_UI_VLM_TOOLS"] == str(tmp_path / "no-vlm-tools")
    assert not os.path.exists(os.environ["MOVIE_UI_VLM_TOOLS"])
    assert os.environ["MOVIE_UI_VLM_PORT"] == "9"
    assert lib.vlm_lifecycle_enabled() is False


def test_vlm_environment_helpers(monkeypatch):
    for name in ("MOVIE_UI_VLM_LIFECYCLE", "MOVIE_UI_VLM_TOOLS", "MOVIE_UI_VLM_PORT"):
        monkeypatch.delenv(name)
    assert lib.vlm_lifecycle_enabled() is True
    assert lib.vlm_tools_dir() == os.path.join(mt.WS, "bin")
    assert lib.vlm_tools_dir("/ui") == "/ui/bin"
    assert lib.vlm_port() == 8177
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "yes")
    assert lib.vlm_lifecycle_enabled() is True
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "0")
    assert lib.vlm_lifecycle_enabled() is False
    monkeypatch.setenv("MOVIE_UI_VLM_TOOLS", "")
    assert lib.vlm_tools_dir("/ui") == "/ui/bin"
    monkeypatch.setenv("MOVIE_UI_VLM_TOOLS", "/t")
    assert lib.vlm_tools_dir("/ui") == "/t" and lib.vlm_tools_dir() == "/t"
    monkeypatch.setenv("MOVIE_UI_VLM_PORT", "1234")
    assert lib.vlm_port() == 1234


# --- VL1-VL5: the policy (VP1-VP4) -------------------------------------------------------------

def test_vl1_job_vlm(tmp_path):
    ws = str(tmp_path)
    for kind in ("story", "character-create", "character-regenerate"):
        assert lib.job_vlm(kind, {}, ws, None) == "required", kind
    for kind in ("smoke", "character-train", "action-train"):
        assert lib.job_vlm(kind, {}, ws, None) == "forbidden", kind
    for kind in ("action-create", "download", "something-new"):
        assert lib.job_vlm(kind, {}, ws, None) == "any", kind
    assert lib.job_vlm("movie", {"action": "movie"}, ws, "s1") == "required"
    assert lib.job_vlm("movie", {"action": "movie"}, ws, None) == "required"
    assert lib.job_vlm("movie", None, ws, "") == "required"
    assert lib.job_vlm("movie", {"action": "redo"}, ws, "s1") == "forbidden"
    _write_story(ws, "s1")
    assert lib.job_vlm("movie", {"action": "movie"}, ws, "s1") == "forbidden"
    assert lib.job_vlm("movie", {"action": "redo"}, ws, "s1") == "forbidden"
    assert lib.job_vlm("movie", {"action": "movie"}, ws, "s2") == "required"


def test_vl2_jobs_carry_their_vlm_policy(http_env, monkeypatch, tmp_path):
    s, ws, state = http_env["srv"], http_env["ws"], http_env["state"]
    mt.smoke_host(monkeypatch, tmp_path)
    _write_story(ws, "written")

    def created(method_path, body):
        status, _h, payload = mt.api(s, "POST", method_path, body=body)
        assert status == 201, (method_path, payload)
        return lib.read_job(lib.job_dir(state, payload["job"]["id"]))

    compose = (("story", mt.fields(ws), "required"),
               ("regenerate", mt.fields(ws, action="regenerate"), "required"),
               ("movie without story.md", mt.fields(ws, action="movie", story_id="fresh",
                                                    mode="no_stills"), "required"),
               ("movie with story.md", mt.fields(ws, action="movie", story_id="written",
                                                 mode="no_stills"), "forbidden"),
               ("smoke", mt.fields(ws, action="smoke"), "forbidden"))
    for name, body, policy in compose:
        assert created("/api/jobs", body)["vlm"] == policy, name
    character = {"ws": ws, "name": "kyra", "phrase": "the young woman", "class_noun": "woman",
                 "descriptor": "a tall young woman", "trigger": None, "seed": None,
                 "seed_upload": None, "force": False}
    routes = (("/api/characters", character, "character-create", "required"),
              ("/api/characters/kyra/regenerate", {"ws": ws}, "character-regenerate", "required"),
              ("/api/characters/kyra/train", {"ws": ws, "video": True}, "character-train",
               "forbidden"),
              ("/api/actions/roundhouse-kick/train", {"ws": ws}, "action-train", "forbidden"),
              ("/api/models/download", {"ws": ws, "repo": "org/name"}, "download", "any"))
    for path, body, kind, policy in routes:
        job = created(path, body)
        assert (job["kind"], job["vlm"]) == (kind, policy), path
        assert list(job)[-2:] == ["vlm", "created"]
    # The two kinds no HTTP test can submit on this host (redo needs the stills stack, an action
    # create needs real clips) go through the same create_job.
    for kind, fields, story_id, policy in (("movie", {"action": "redo"}, "written", "forbidden"),
                                           ("action-create", {"name": "kick"}, None, "any")):
        job = lib.create_job(state, lib.new_job_id(state), kind, ws, story_id, None, ["x"], fields)
        assert job["vlm"] == policy, kind


def test_vl3_effective_vlm(tmp_path):
    ws = str(tmp_path)
    movie = {"kind": "movie", "workspace": ws, "story_id": "s1", "fields": {"action": "movie"},
             "vlm": "required"}
    assert lib.effective_vlm(movie) == "required"
    _write_story(ws, "s1")
    assert lib.effective_vlm(movie) == "forbidden"
    assert lib.effective_vlm(dict(movie, vlm="bogus")) == "forbidden"
    assert lib.effective_vlm({"kind": "story"}) == "any"
    assert lib.effective_vlm({"kind": "story", "vlm": "bogus"}) == "any"
    assert lib.effective_vlm({"kind": "story", "vlm": "required"}) == "required"
    assert lib.effective_vlm({"kind": "smoke", "vlm": "forbidden"}) == "forbidden"


def test_vl4_next_queued_job(state, tmp_path):
    ws = str(tmp_path)
    assert lib.next_queued_job(state) == (None, None)
    done = mt.make_job(state, ["x"], ws, kind="smoke")
    lib.write_status(lib.job_dir(state, done), {"state": "cancelled", "exit_code": None,
                                                "ended": lib.utc_now()})
    gone = mt.make_job(state, ["x"], ws, kind="smoke")
    os.unlink(os.path.join(lib.job_dir(state, gone), "job.json"))
    nxt = mt.make_job(state, ["x"], ws, kind="download")
    job_id, job = lib.next_queued_job(state)
    assert job_id == nxt and job["kind"] == "download"
    assert lib.read_queue(state) == [done, gone, nxt]
    lib.write_queue(state, [done, gone])
    assert lib.next_queued_job(state) == (None, None)


def test_vl5_vlm_restore_wanted(state, tmp_path):
    ws = str(tmp_path)
    assert lib.vlm_restore_wanted(state) == (True, "queue empty")
    for kind, wanted, text in (("story", True, "next job %s needs it"),
                               ("smoke", False, "next job %s runs without it"),
                               ("download", False, "next job %s is vlm=any")):
        lib.write_queue(state, [])
        job_id = mt.make_job(state, ["x"], ws, kind=kind)
        assert lib.vlm_restore_wanted(state) == (wanted, text % job_id), kind


# --- F-TOOLS and F-HTTP (spec 11.2) ------------------------------------------------------------

MODEL = "test-vlm-model"
COMPLETION = {"model": MODEL, "max_tokens": 1,
              "messages": [{"role": "user", "content": "Reply with the single word ok"}]}

FAKE_TOOL_SOURCE = r'''
import fcntl
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
args = sys.argv[1:]
record = {"tool": TOOL, "argv": args, "pid": os.getpid(), "ppid": os.getppid(),
          "pgid": os.getpgid(0), "sid": os.getsid(0), "t": time.time()}
probe = os.environ.get("FAKE_PROBE_JOB_DIR")
if probe and TOOL == "story-server-restore":
    fd = os.open(os.path.join(probe, "lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record["job_lock_held"] = False
        fcntl.flock(fd, fcntl.LOCK_UN)
    except BlockingIOError:
        record["job_lock_held"] = True
    os.close(fd)
    try:
        with open(os.path.join(probe, "status.json"), encoding="utf-8") as f:
            record["job_state"] = json.load(f).get("state")
    except (OSError, ValueError):
        record["job_state"] = None
with open(os.path.join(HERE, "calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps(record) + "\n")
try:
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        config = json.load(f)
except (OSError, ValueError):
    config = {}


def set_state(text):
    with open(os.path.join(HERE, "vlm_state"), "w", encoding="utf-8") as f:
        f.write(text)


if TOOL == "story-server":
    if args == ["status"]:
        entry = config.get("status", {})
        time.sleep(entry.get("sleep", 0))
        with open(os.path.join(HERE, "vlm_state"), encoding="utf-8") as f:
            vlm_state = f.read().strip()
        sys.stdout.write(entry.get("stdout", "story-server status  X\n  state:          %s\n"
                                             "  health:         HTTP 200 model=%s\n"
                                             % (vlm_state, PARAMS["model"])))
        sys.exit(entry.get("exit", 0))
    if args == ["stop"]:
        set_state("STOPPED")
        sys.exit(PARAMS["stop_rc"])
    if args == ["lockinfo"]:
        sys.stdout.write("lock: free path=x\n")
        sys.exit(0)
    sys.exit(0)
if "--wait" in args:
    time.sleep(PARAMS["restore_sleep"])
    if PARAMS["serve_on_restore"]:
        set_state("SERVING mlx-vision")
    sys.exit(PARAMS["restore_rc"])
sys.exit(0)
'''


def make_fake_tools(tmp, model, stop_rc=0, restore_rc=0, restore_sleep=0, serve_on_restore=True):
    """F-TOOLS: <tmp>/tools/story-server and story-server-restore, #!sys.executable scripts that
    append one JSON line per call to <tmp>/tools/calls.jsonl and share <tmp>/tools/vlm_state
    (initially STOPPED); <tmp>/tools/config.json {"status": {"exit", "sleep", "stdout"}}
    overrides status. Returns the tools directory."""
    tools = os.path.join(str(tmp), "tools")
    os.makedirs(tools, exist_ok=True)
    params = {"model": model, "stop_rc": stop_rc, "restore_rc": restore_rc,
              "restore_sleep": restore_sleep, "serve_on_restore": serve_on_restore}
    for tool in ("story-server", "story-server-restore"):
        path = os.path.join(tools, tool)
        with open(path, "w", encoding="utf-8") as f:
            f.write("#!%s\nTOOL = %r\nPARAMS = %r\n%s" % (sys.executable, tool, params,
                                                         FAKE_TOOL_SOURCE))
        os.chmod(path, 0o755)
    set_vlm_state(tools, "STOPPED")
    return tools


def set_vlm_state(tools, text):
    with open(os.path.join(tools, "vlm_state"), "w", encoding="utf-8") as f:
        f.write(text)


def set_tool_config(tools, config):
    with open(os.path.join(tools, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)


def tool_calls(tools, include_status=False):
    try:
        with open(os.path.join(tools, "calls.jsonl"), encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
    except OSError:
        rows = []
    return [r for r in rows if include_status or r["argv"] != ["status"]]


def call_names(tools, include_status=False):
    out = []
    for row in tool_calls(tools, include_status):
        if row["tool"] == "story-server-restore":
            out.append("restore --wait" if "--wait" in row["argv"] else "restore")
        else:
            out.append(" ".join(row["argv"]))
    return out


def lifecycle_on(monkeypatch, tools, port):
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "1")
    monkeypatch.setenv("MOVIE_UI_VLM_TOOLS", tools)
    monkeypatch.setenv("MOVIE_UI_VLM_PORT", str(port))
    monkeypatch.setattr(lib, "VLM_RECOVERY", [])


class FakeVLM(object):
    """F-HTTP: a ThreadingHTTPServer on 127.0.0.1:0 serving GET /v1/models (models, or the raw
    bytes models_raw, with models_status) and POST /v1/chat/completions (completion_body after
    completion_delay s, with completion_status; a list status is consumed one per request, its
    last value repeating). Every request is recorded as (method, path, JSON body or None)."""

    def __init__(self, models, models_status=200, completion_status=200, completion_body=None,
                 completion_delay=0, models_raw=None):
        self.models, self.models_status, self.models_raw = models, models_status, models_raw
        self.completion_status, self.completion_body = completion_status, completion_body
        self.completion_delay = completion_delay
        self.requests = []
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, status, raw):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except OSError:
                    pass

            def do_GET(self):
                fake.requests.append(("GET", self.path, None))
                raw = fake.models_raw
                if raw is None:
                    raw = json.dumps({"object": "list", "data": fake.models}).encode("utf-8")
                self._reply(fake.models_status, raw)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                fake.requests.append(("POST", self.path, json.loads(raw.decode("utf-8")) if raw else None))
                time.sleep(fake.completion_delay)
                status = fake.completion_status
                if isinstance(status, list):
                    status = status.pop(0) if len(status) > 1 else status[0]
                body = fake.completion_body
                if body is None:
                    body = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
                self._reply(status, json.dumps(body).encode("utf-8"))

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def vlm():
    fake = FakeVLM([{"id": "other-cached-model", "loaded": False}, {"id": MODEL, "loaded": True}])
    yield fake
    fake.close()


def _free_closed_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# --- VL6-VL8, Review Focus 4: the health check (VR4) -------------------------------------------

def test_vl6_health_happy_path(tmp_path, vlm):
    tools = make_fake_tools(tmp_path, MODEL)
    set_vlm_state(tools, "SERVING mlx-vision")
    assert lib.vlm_health(tools, vlm.port) == (True, "%s on 127.0.0.1:%d" % (MODEL, vlm.port))
    assert call_names(tools, include_status=True) == ["status"]


def test_vl7_health_problems(tmp_path):
    tools = make_fake_tools(tmp_path, MODEL)
    set_vlm_state(tools, "SERVING mlx-vision")
    serving = [{"id": MODEL, "loaded": True}]

    def health(fake=None, **kw):
        port = fake.port if fake is not None else _free_closed_port()
        try:
            return lib.vlm_health(tools, port, **kw)
        finally:
            if fake is not None:
                fake.close()

    set_tool_config(tools, {"status": {"sleep": 3}})
    assert health(status_timeout=1) == (False, "bin/story-server status timed out after 1 s")    # H1
    set_tool_config(tools, {"status": {"exit": 4}})
    assert health() == (False, "bin/story-server status exited 4")                                # H2
    set_tool_config(tools, {})
    set_vlm_state(tools, "LOADING mlx-vision")
    assert health() == (False, "story server is LOADING mlx-vision, not SERVING mlx-vision")      # H3
    set_tool_config(tools, {"status": {"stdout": "story-server status  X\n"}})
    assert health() == (False, "story server is UNKNOWN, not SERVING mlx-vision")
    set_tool_config(tools, {"status": {"stdout": "  state:          SERVING mlx-vision\n"
                                                 "  health:         HTTP 000 model=none\n"}})
    assert health() == (False, "bin/story-server status printed no served model")                # H9
    set_tool_config(tools, {"status": {"stdout": "  state:          SERVING mlx-vision\n"}})
    assert health() == (False, "bin/story-server status printed no served model")
    set_tool_config(tools, {})
    set_vlm_state(tools, "SERVING mlx-vision")
    assert health(FakeVLM(serving, models_status=503)) == (False, "GET /v1/models failed: HTTP 503")
    assert health(FakeVLM(serving, models_raw=b"{")) == (False, "GET /v1/models failed: invalid JSON")
    assert health(FakeVLM(serving, models_raw=b'{"data": {}}')) == (
        False, "GET /v1/models failed: invalid JSON")
    assert health() == (False, "GET /v1/models failed: ConnectionRefusedError")                   # H4
    assert health(FakeVLM([{"id": "other", "loaded": True}])) == (
        False, "GET /v1/models does not list %s" % MODEL)                                       # H5
    assert health(FakeVLM([{"id": MODEL, "loaded": False}])) == (
        False, "%s is listed by /v1/models but not loaded" % MODEL)                             # H6
    assert health(FakeVLM([{"id": MODEL}]))[0] is True
    assert health(FakeVLM(serving, completion_status=500)) == (False, "completion failed: HTTP 500")
    assert health(FakeVLM(serving, completion_delay=3), completion_timeout=1) == (
        False, "completion failed: TimeoutError")                                               # H7
    assert health(FakeVLM(serving, completion_body={"choices": []})) == (
        False, "completion reply has no choices")                                               # H8
    assert health(FakeVLM(serving, completion_body={"text": "ok"})) == (
        False, "completion reply has no choices")


def test_vl8_health_request_shape(tmp_path, vlm):
    tools = make_fake_tools(tmp_path, MODEL)
    set_vlm_state(tools, "SERVING mlx-vision")
    assert lib.vlm_health(tools, vlm.port)[0] is True
    assert vlm.requests == [("GET", "/v1/models", None), ("POST", "/v1/chat/completions", COMPLETION)]
    other = FakeVLM([{"id": "other", "loaded": True}])
    try:
        assert lib.vlm_health(tools, other.port)[1] == "GET /v1/models does not list %s" % MODEL
        assert other.requests == [("GET", "/v1/models", None)]
    finally:
        other.close()


def test_review_focus_4_models_reply_not_utf8_or_oversized(tmp_path):
    tools = make_fake_tools(tmp_path, MODEL)
    set_vlm_state(tools, "SERVING mlx-vision")
    big = b'{"data": [' + b" " * lib.VLM_MAX_BODY + b'{"id": "%s", "loaded": true}]}' % MODEL.encode()
    for raw in (b'{"data": [{"id": "\xff\xfe"}]}', big):
        fake = FakeVLM([], models_raw=raw)
        try:
            assert lib.vlm_health(tools, fake.port) == (False, "GET /v1/models failed: invalid JSON")
            assert [r[0] for r in fake.requests] == ["GET"]
        finally:
            fake.close()


# --- VL3, VL9-VL16, VL28, Review Focus 5: the preflight (VR2, VR3) -----------------------------

REQUIRED = {"kind": "story", "vlm": "required"}
RESTORE_EXIT_1 = ("bin/story-server-restore mlx-vision --wait exited 1 "
                  "(see ~/.local/share/qwen-agent/story-server-restore.log)")


def _say_lines(capsys):
    return [line for line in capsys.readouterr().out.splitlines() if line.startswith("[movie-ui] ")]


def _preflight(tmp_path, job, tools, port, **kw):
    return lib.vlm_preflight(job, str(tmp_path / "cancel"), tools=tools, port=port, **kw)


def test_vl3_preflight_reports_a_recomputed_movie_policy(tmp_path, vlm, capsys):
    ws = str(tmp_path / "ws")
    tools = make_fake_tools(tmp_path, MODEL)
    movie = {"kind": "movie", "workspace": ws, "story_id": "s1", "fields": {"action": "movie"},
             "vlm": "required"}
    _write_story(ws, "s1")
    assert _preflight(tmp_path, movie, tools, vlm.port) == ("ok", None)
    assert _say_lines(capsys)[0] == ("[movie-ui] vlm: job.json says vlm=required; story.md exists now, "
                                     "so vlm=forbidden")
    assert call_names(tools) == ["stop"]
    os.unlink(os.path.join(lib.story_dir(ws, "s1"), "story.md"))
    movie["vlm"] = "forbidden"
    assert _preflight(tmp_path, movie, tools, vlm.port) == ("ok", None)
    assert _say_lines(capsys)[0] == ("[movie-ui] vlm: job.json says vlm=forbidden; story.md is missing "
                                     "now, so vlm=required")
    movie["vlm"] = "required"
    assert _preflight(tmp_path, movie, tools, vlm.port) == ("ok", None)
    assert "job.json says" not in " ".join(_say_lines(capsys))


def test_vl9_preflight_required_and_healthy(tmp_path, vlm, capsys):
    tools = make_fake_tools(tmp_path, MODEL)
    assert _preflight(tmp_path, REQUIRED, tools, vlm.port) == ("ok", None)
    assert call_names(tools) == ["restore --wait"]
    assert call_names(tools, include_status=True) == ["restore --wait", "status"]
    assert _say_lines(capsys) == [
        "[movie-ui] vlm: preflight: this job needs the VLM (vlm=required)",
        "[movie-ui] vlm: running: %s mlx-vision --wait" % os.path.join(tools, "story-server-restore"),
        "[movie-ui] vlm: healthy: %s on 127.0.0.1:%d" % (MODEL, vlm.port)]


def test_vl10_preflight_unhealthy_then_healthy(tmp_path, capsys):
    tools = make_fake_tools(tmp_path, MODEL)
    fake = FakeVLM([{"id": MODEL, "loaded": True}], completion_status=[500, 200])
    try:
        assert _preflight(tmp_path, REQUIRED, tools, fake.port) == ("ok", None)
    finally:
        fake.close()
    assert call_names(tools) == ["restore --wait", "stop", "restore --wait"]
    lines = _say_lines(capsys)
    assert "[movie-ui] vlm: unhealthy: completion failed: HTTP 500; restarting it once" in lines
    assert lines[-1] == "[movie-ui] vlm: healthy: %s on 127.0.0.1:%d" % (MODEL, fake.port)


def test_vl11_preflight_unhealthy_twice(tmp_path):
    tools = make_fake_tools(tmp_path, MODEL)
    fake = FakeVLM([{"id": MODEL, "loaded": True}], completion_status=500)
    try:
        assert _preflight(tmp_path, REQUIRED, tools, fake.port) == (
            "failed", "VLM preflight failed after one restart: completion failed: HTTP 500")
    finally:
        fake.close()
    assert call_names(tools) == ["restore --wait", "stop", "restore --wait"]


def test_vl12_preflight_restore_fails_twice(tmp_path, vlm):
    tools = make_fake_tools(tmp_path, MODEL, restore_rc=1)
    assert _preflight(tmp_path, REQUIRED, tools, vlm.port) == (
        "failed", "VLM preflight failed after one restart: " + RESTORE_EXIT_1)
    assert call_names(tools) == ["restore --wait", "stop", "restore --wait"]
    # The one status call is _vlm_other_mode's; no health check ran.
    assert call_names(tools, include_status=True) == ["restore --wait", "status", "stop",
                                                      "restore --wait"]
    assert vlm.requests == []


def test_vl13_preflight_forbidden(tmp_path, vlm, capsys):
    tools = make_fake_tools(tmp_path, MODEL)
    job = {"kind": "smoke", "vlm": "forbidden"}
    assert _preflight(tmp_path, job, tools, vlm.port) == ("ok", None)
    assert call_names(tools, include_status=True) == ["stop"]
    assert _say_lines(capsys) == [
        "[movie-ui] vlm: preflight: this job runs without the VLM (vlm=forbidden)",
        "[movie-ui] vlm: running: %s stop" % os.path.join(tools, "story-server"),
        "[movie-ui] vlm: stopped for this job"]
    failing = make_fake_tools(tmp_path / "rc3", MODEL, stop_rc=3)
    assert _preflight(tmp_path, job, failing, vlm.port) == (
        "failed", "VLM preflight failed: bin/story-server stop exited 3; the log above shows why")


def test_vl14_preflight_any(tmp_path, vlm, capsys):
    tools = make_fake_tools(tmp_path, MODEL)
    assert _preflight(tmp_path, {"kind": "download", "vlm": "any"}, tools, vlm.port) == ("ok", None)
    assert _preflight(tmp_path, {"kind": "download"}, tools, vlm.port) == ("ok", None)
    assert tool_calls(tools, include_status=True) == []
    assert _say_lines(capsys) == ["[movie-ui] vlm: preflight: vlm=any; the VLM is left as it is"] * 2


def test_vl15_cancel_during_preflight(tmp_path, vlm):
    tools = make_fake_tools(tmp_path, MODEL, restore_sleep=30)
    cancel = tmp_path / "cancel"
    threading.Timer(1.0, cancel.touch).start()
    started = time.monotonic()
    assert _preflight(tmp_path, REQUIRED, tools, vlm.port) == ("cancelled", None)
    assert time.monotonic() - started < 8
    row = tool_calls(tools)[0]
    assert row["tool"] == "story-server-restore"
    assert not mt.pid_alive(row["pid"])


def test_vl16_preflight_timeout(tmp_path, vlm):
    tools = make_fake_tools(tmp_path, MODEL, restore_sleep=30)
    started = time.monotonic()
    assert _preflight(tmp_path, REQUIRED, tools, vlm.port, timeout=2) == (
        "failed", "VLM preflight timed out after 2 s")
    assert time.monotonic() - started < 10
    assert not mt.pid_alive(tool_calls(tools)[0]["pid"])


def test_vl28_another_mode_fails_without_a_stop(tmp_path, vlm):
    for i, state_text, mode in ((0, "SERVING vision", "vision"), (1, "LOADING text", "text")):
        tools = make_fake_tools(tmp_path / str(i), MODEL, restore_rc=1, serve_on_restore=False)
        set_vlm_state(tools, state_text)
        assert _preflight(tmp_path, REQUIRED, tools, vlm.port) == (
            "failed", "VLM preflight failed: the story server runs in %s mode, not mlx-vision; stop "
                      "it with bin/story-server stop and resubmit" % mode)
        assert call_names(tools, include_status=True) == ["restore --wait", "status"]
    tools = make_fake_tools(tmp_path / "foreign", MODEL, restore_rc=1, serve_on_restore=False)
    set_vlm_state(tools, "FOREIGN pid 5")
    assert _preflight(tmp_path, REQUIRED, tools, vlm.port) == (
        "failed", "VLM preflight failed after one restart: " + RESTORE_EXIT_1)
    assert call_names(tools) == ["restore --wait", "stop", "restore --wait"]


def test_review_focus_5_tools_path_with_a_space(tmp_path, vlm, capsys):
    tools = make_fake_tools(tmp_path / "my ui ws", MODEL)
    assert " " in tools
    assert _preflight(tmp_path, REQUIRED, tools, vlm.port) == ("ok", None)
    restore = os.path.join(tools, "story-server-restore")
    assert _say_lines(capsys)[1] == "[movie-ui] vlm: running: '%s' mlx-vision --wait" % restore
    assert call_names(tools) == ["restore --wait"]


# --- VL17-VL21, Review Focus 1: the runner's preflight and postflight (VR1, VR5) ----------------

STATUS_KEYS_FAILED = {"state", "dispatched", "runner_pid", "pgid", "started", "exit_code", "ended",
                      "error"}


def _final(state, job_id, timeout=30):
    return mt.wait_until(lambda: mt.status_of(state, job_id).get("state") in lib.FINISHED_STATES
                         and mt.status_of(state, job_id), timeout)


def _child_probe(path):
    """A job argv whose child records its own start time and STORY_SERVER_ENGINE_SCAN."""
    return mt.py_argv("import json, os, time\n"
                      "json.dump({'t': time.time(), 'scan': os.environ.get('STORY_SERVER_ENGINE_SCAN')}, "
                      "open(%r, 'w'))\n" % path)


def test_vl17_required_job_end_to_end(state, tmp_path, vlm, monkeypatch):
    tools = make_fake_tools(tmp_path, MODEL)
    lifecycle_on(monkeypatch, tools, vlm.port)
    probe = str(tmp_path / "child.json")
    job_id = mt.make_job(state, _child_probe(probe), str(tmp_path), kind="story")
    assert mt.dispatch(state, job_id).wait(timeout=60) == 0
    assert mt.status_of(state, job_id)["state"] == "done"
    lines = mt.read_log(state, job_id).splitlines()
    started = [i for i, line in enumerate(lines) if line.startswith("[movie-ui] started pid ")][0]
    assert [line for line in lines[:started] if line.startswith("[movie-ui] vlm:")] == [
        "[movie-ui] vlm: preflight: this job needs the VLM (vlm=required)",
        "[movie-ui] vlm: running: %s mlx-vision --wait" % os.path.join(tools, "story-server-restore"),
        "[movie-ui] vlm: healthy: %s on 127.0.0.1:%d" % (MODEL, vlm.port)]
    with open(probe) as f:
        child = json.load(f)
    assert child["scan"] == "0"
    rows = tool_calls(tools, include_status=True)
    assert [r["argv"] for r in rows if r["t"] < child["t"]] == [["mlx-vision", "--wait"], ["status"]]
    assert call_names(tools, include_status=True) == ["restore --wait", "status", "restore"]
    # The lifecycle off: no tool runs, and the child still gets STORY_SERVER_ENGINE_SCAN=0 (VR1).
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "0")
    probe_off = str(tmp_path / "child-off.json")
    off = mt.make_job(state, _child_probe(probe_off), str(tmp_path), kind="story")
    assert mt.dispatch(state, off).wait(timeout=60) == 0
    with open(probe_off) as f:
        assert json.load(f)["scan"] == "0"
    assert len(tool_calls(tools, include_status=True)) == 3
    assert "[movie-ui] vlm:" not in mt.read_log(state, off)


def test_vl18_preflight_failure_end_to_end(state, tmp_path, vlm, monkeypatch):
    tools = make_fake_tools(tmp_path, MODEL, restore_rc=1)
    lifecycle_on(monkeypatch, tools, vlm.port)
    job_id = mt.make_job(state, mt.py_argv("print('the child ran')"), str(tmp_path), kind="story")
    assert mt.dispatch(state, job_id).wait(timeout=60) == 1
    status = mt.status_of(state, job_id)
    assert set(status) == STATUS_KEYS_FAILED
    assert (status["state"], status["pgid"], status["started"], status["exit_code"]) == (
        "failed", None, None, None)
    assert status["error"] == "VLM preflight failed after one restart: " + RESTORE_EXIT_1
    assert call_names(tools) == ["restore --wait", "stop", "restore --wait", "restore"]
    log = mt.read_log(state, job_id)
    assert "the child ran" not in log and "[movie-ui] started pid" not in log
    assert "[movie-ui] " + status["error"] + "\n" in log
    assert "[movie-ui] vlm: postflight: restoring the VLM in its own session (queue empty)\n" in log


def test_vl19_postflight_runs_under_the_job_lock_after_the_final_status(state, tmp_path, vlm,
                                                                         monkeypatch):
    tools = make_fake_tools(tmp_path, MODEL)
    lifecycle_on(monkeypatch, tools, vlm.port)
    job_id = mt.make_job(state, mt.py_argv("import time; time.sleep(0.5)"), str(tmp_path),
                         kind="smoke")
    monkeypatch.setenv("FAKE_PROBE_JOB_DIR", lib.job_dir(state, job_id))
    assert mt.dispatch(state, job_id).wait(timeout=60) == 0
    status = mt.status_of(state, job_id)
    assert status["state"] == "done"
    restores = [r for r in tool_calls(tools) if r["tool"] == "story-server-restore"]
    assert len(restores) == 1 and restores[0]["argv"] == ["mlx-vision"]
    assert restores[0]["job_lock_held"] is True
    assert restores[0]["job_state"] == "done"
    assert restores[0]["pgid"] != status["pgid"]
    assert not lib.group_alive(status["pgid"])


def test_vl20_postflight_decisions(state, tmp_path, vlm, monkeypatch, capsys):
    tools = make_fake_tools(tmp_path, MODEL)
    lifecycle_on(monkeypatch, tools, vlm.port)
    ws = str(tmp_path)
    restore = os.path.join(tools, "story-server-restore")
    lib.vlm_postflight(state)
    assert call_names(tools) == ["restore"]
    assert _say_lines(capsys) == [
        "[movie-ui] vlm: postflight: restoring the VLM in its own session (queue empty)",
        "[movie-ui] vlm: running: %s mlx-vision" % restore]
    nxt = mt.make_job(state, ["x"], ws, kind="story")
    lib.vlm_postflight(state)
    assert call_names(tools) == ["restore", "restore"]
    assert _say_lines(capsys)[0] == ("[movie-ui] vlm: postflight: restoring the VLM in its own "
                                     "session (next job %s needs it)" % nxt)
    for kind, why in (("smoke", "next job %s runs without it"), ("download", "next job %s is vlm=any")):
        lib.write_queue(state, [])
        nxt = mt.make_job(state, ["x"], ws, kind=kind)
        lib.vlm_postflight(state)
        assert call_names(tools) == ["restore", "restore"], kind
        assert _say_lines(capsys) == ["[movie-ui] vlm: postflight: not restoring the VLM (%s)"
                                      % (why % nxt)]
    lib.write_queue(state, [])
    failing = str(tmp_path / "failing-tools")
    os.makedirs(failing)
    with open(os.path.join(failing, "story-server-restore"), "w") as f:
        f.write("#!/bin/sh\nexit 3\n")
    os.chmod(os.path.join(failing, "story-server-restore"), 0o755)
    monkeypatch.setenv("MOVIE_UI_VLM_TOOLS", failing)
    lib.vlm_postflight(state)
    assert _say_lines(capsys)[-1] == "[movie-ui] vlm: postflight: bin/story-server-restore exited 3"
    missing = str(tmp_path / "missing-tools")
    monkeypatch.setenv("MOVIE_UI_VLM_TOOLS", missing)
    lib.vlm_postflight(state)
    assert _say_lines(capsys)[-1] == ("[movie-ui] vlm: postflight: cannot run %s: No such file or "
                                      "directory" % os.path.join(missing, "story-server-restore"))


def test_vl21_back_to_back_renders_do_not_reload(state, tmp_path, vlm, monkeypatch):
    tools = make_fake_tools(tmp_path, MODEL)
    lifecycle_on(monkeypatch, tools, vlm.port)
    ws = str(tmp_path)
    first = mt.make_job(state, mt.py_argv("print('render 1')"), ws, kind="smoke")
    second = mt.make_job(state, mt.py_argv("print('render 2')"), ws, kind="smoke")
    assert lib.dispatch_tick(state, mt.WS) == first
    mt.wait_until(lambda: lib.dispatch_tick(state, mt.WS) == second, 30)
    _final(state, second)
    mt.wait_until(lambda: call_names(tools)[-1:] == ["restore"], 30)
    assert call_names(tools) == ["stop", "stop", "restore"]
    assert tool_calls(tools)[-1]["t"] >= lib.parse_utc(mt.status_of(state, second)["ended"])
    assert ("[movie-ui] vlm: postflight: not restoring the VLM (next job %s runs without it)"
            % second) in mt.read_log(state, first)
    log = mt.read_log(state, second)
    assert log.index("[movie-ui] exit 0 (done)") < log.index(
        "[movie-ui] vlm: postflight: restoring the VLM in its own session (queue empty)")


def test_review_focus_1_story_then_movie_of_the_same_story(state, tmp_path, vlm, monkeypatch):
    tools = make_fake_tools(tmp_path, MODEL)
    lifecycle_on(monkeypatch, tools, vlm.port)
    ws = str(tmp_path / "ws")
    os.makedirs(ws)
    sdir = lib.story_dir(ws, "s1")
    write_story = mt.py_argv("import os\nos.makedirs(%r, exist_ok=True)\n"
                             "open(os.path.join(%r, 'story.md'), 'w').write('## Panel 1\\n')\n"
                             % (sdir, sdir))
    story = mt.make_job(state, write_story, ws, kind="story", fields={"action": "story"})
    movie = mt.make_job(state, mt.py_argv("print('render')"), ws, kind="movie",
                        fields={"action": "movie"})
    assert lib.read_job(lib.job_dir(state, movie))["vlm"] == "required"
    assert lib.dispatch_tick(state, mt.WS) == story
    mt.wait_until(lambda: lib.dispatch_tick(state, mt.WS) == movie, 60)
    _final(state, movie)
    mt.wait_until(lambda: call_names(tools)[-1:] == ["restore"], 30)
    assert call_names(tools) == ["restore --wait", "stop", "restore"]
    assert mt.status_of(state, story)["state"] == "done"
    assert mt.status_of(state, movie)["state"] == "done"
    assert ("[movie-ui] vlm: postflight: not restoring the VLM (next job %s runs without it)"
            % movie) in mt.read_log(state, story)
    log = mt.read_log(state, movie)
    assert ("[movie-ui] vlm: job.json says vlm=required; story.md exists now, so vlm=forbidden"
            in log)
    assert log.index("[movie-ui] vlm: stopped for this job") < log.index("[movie-ui] started pid")
