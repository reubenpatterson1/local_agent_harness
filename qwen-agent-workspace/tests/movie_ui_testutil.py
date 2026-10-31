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


# ---------------------------------------------------------------------------
# The stub workspace
# ---------------------------------------------------------------------------

STUB_TOOLS = ("ltx-movie", "lora-catalog", "character", "ltx-mlx-render", "story-server",
              "location")

STUB_SOURCE = r'''
import json
import os
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
FIXTURES = __FIXTURES__
args = sys.argv[1:]
if TOOL in ("ltx-movie", "ltx-mlx-render"):
    sub = "--help" if "--help" in args else ("--dry-run" if "--dry-run" in args else "run")
else:
    sub = args[0] if args else ""
with open(os.path.join(WS, "stub_calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps({"tool": TOOL, "sub": sub, "argv": args, "cwd": os.getcwd(),
                        "env": {k: os.environ.get(k) for k in ("STORY_PIPELINE_LOGGED", "PYTHONUNBUFFERED",
                                                               "ANTHROPIC_API_KEY")}}) + "\n")
try:
    with open(os.path.join(WS, "stub_config.json"), encoding="utf-8") as f:
        config = json.load(f)
except (OSError, ValueError):
    config = {}
entry = config.get(" ".join([TOOL] + args), config.get(TOOL + " " + sub, config.get(TOOL)))


def opt(name, default=None):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default


def emit(text, delay=0.0):
    for line in text.splitlines(True):
        sys.stdout.write(line)
        sys.stdout.flush()
        if delay:
            time.sleep(delay)


def write_file(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


if entry is not None:
    time.sleep(entry.get("sleep", 0))
    for rel, text in entry.get("write", {}).items():
        write_file(os.path.join(WS, rel), text.encode("utf-8"))
    emit(entry.get("stdout", ""))
    sys.stderr.write(entry.get("stderr", ""))
    sys.exit(entry.get("exit", 0))
if TOOL == "ltx-movie" and sub == "--help":
    with open(os.path.join(FIXTURES, "ltx-movie-help-current.txt"), encoding="utf-8") as f:
        emit(f.read())
    sys.exit(0)
if TOOL == "ltx-movie" and sub == "run":
    sdir = os.path.join(WS, "generated", "stories", opt("--story-id", "story"))
    panels = int(opt("--panels", "2"))
    if "--story-only" in args:
        emit("=== Phase 1: story ===\n", 0.05)
        text = "".join("## Panel %d -- Shot %d\nImage: a quiet road.\nMotion: the camera drifts.\n\n" % (i, i)
                       for i in range(1, panels + 1))
        write_file(os.path.join(sdir, "story.md"), text.encode("utf-8"))
        emit("story.md written: %s\n" % os.path.join(sdir, "story.md"))
        sys.exit(0)
    for phase in ("=== Phase 1: story ===", "=== Phase 1b: release the story server ===", "=== Phase 2: stills ==="):
        emit(phase + "\n", 0.05)
    write_file(os.path.join(sdir, "images", "panel_01.png"), b"\x89PNG\r\n\x1a\n")
    emit("=== Phase 3: manifest + dry-run ===\npanels: %d\n=== Phase 4: render ===\n" % panels, 0.05)
    for i in range(1, panels + 1):
        emit("=== panel %d/%d (panel-%d) ===\n" % (i, panels, i), 0.1)
        write_file(os.path.join(sdir, "clips", "panel_%02d.mp4" % i), b"\x00\x00\x00\x18ftypmp42")
        emit("panel %d ok: %s (0.1s)\n" % (i, os.path.join(sdir, "clips", "panel_%02d.mp4" % i)), 0.05)
    write_file(os.path.join(sdir, "movie.mp4"), b"\x00\x00\x00\x18ftypmp42")
    emit("=== render summary (ok) ===\n")
    sys.exit(0)
if TOOL == "ltx-mlx-render" and sub == "run":
    clips = opt("--clips-dir")
    emit("=== panel 1/1 (panel-1) ===\n", 0.05)
    write_file(os.path.join(clips, "panel_01.mp4"), b"\x00\x00\x00\x18ftypmp42")
    emit("panel 1 ok: %s (0.1s)\n" % os.path.join(clips, "panel_01.mp4"))
    sys.exit(0)
if TOOL == "lora-catalog" and sub == "list":
    emit(json.dumps({"catalog": os.path.join(WS, "generated", "loras", "catalog.json"), "entries": [],
                     "characters": []}) + "\n")
    sys.exit(0)
if TOOL == "lora-catalog" and sub == "verify":
    for entry_id in args[1:]:
        emit("OK %s\n" % entry_id)
    emit("verified %d entries: 0 problem(s)\n" % len(args[1:]))
    sys.exit(0)
if TOOL == "character" and sub == "list":
    emit("no characters in %s\n" % os.path.join(WS, "generated", "characters"))
    sys.exit(0)
if TOOL == "location" and sub == "list":
    emit("no locations in %s\n" % os.path.join(WS, "generated", "locations"))
    sys.exit(0)
if TOOL == "story-server" and sub == "status":
    emit("story-server status  2026-10-19T00:00:00Z\n  state:          SERVING vision\n")
    sys.exit(0)
sys.exit(0)
'''


def _write_exec(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def make_stub_workspace(tmp):
    """<tmp>/ws with executable stubs of ltx-movie, lora-catalog, character, ltx-mlx-render,
    location (Python) and story-server (sh, running bin/.story-server.py); returns the workspace
    realpath.

    Each stub appends {"tool", "sub", "argv", "cwd", "env"} as one JSON line to
    <ws>/stub_calls.jsonl and obeys <ws>/stub_config.json: {key: {"exit", "stdout", "stderr",
    "sleep", "write": {relpath: text}}}, where the first key found of "<tool> <every argument>",
    "<tool> <sub>" and "<tool>" applies. sub is the first argument, or for ltx-movie and
    ltx-mlx-render "--help", "--dry-run" or "run". Without a
    config entry: ltx-movie --help prints the current help fixture; ltx-movie runs write story.md
    (--story-only) or stills, clips and movie.mp4 with the real progress markers; lora-catalog list
    prints an empty catalog; location list prints an empty location library; story-server status
    reports SERVING vision; everything else exits 0.
    """
    ws = os.path.join(str(tmp), "ws")
    os.makedirs(os.path.join(ws, "bin"), exist_ok=True)
    os.makedirs(os.path.join(ws, "generated", "stories"), exist_ok=True)
    body = STUB_SOURCE.replace("__FIXTURES__", repr(FIXTURES))
    for tool in STUB_TOOLS:
        source = "#!%s\nTOOL = %r\n%s" % (sys.executable, tool, body)
        if tool == "story-server":
            _write_exec(os.path.join(ws, "bin", ".story-server.py"), source)
            _write_exec(os.path.join(ws, "bin", "story-server"),
                        "#!/bin/sh\nexec '%s' \"$(dirname \"$0\")/.story-server.py\" \"$@\"\n" % sys.executable)
        else:
            _write_exec(os.path.join(ws, "bin", tool), source)
    return os.path.realpath(ws)


def stub_config(ws, config):
    with open(os.path.join(ws, "stub_config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)


def stub_calls(ws):
    try:
        with open(os.path.join(ws, "stub_calls.jsonl"), encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except OSError:
        return []


def fields(ws, **overrides):
    """A valid MU36 field object for ws (action story) with overrides applied."""
    out = movie_ui_lib.compose_fields({"ws": ws, "story_id": "ronin-rescue",
                                       "narrative": "A ronin rescues a child from a burning village."})
    out.update(overrides)
    return out


# ---------------------------------------------------------------------------
# HF caches
# ---------------------------------------------------------------------------

def make_hf_cache(root, repo, files, refs=True, incomplete=0, broken=()):
    """<root>/hub/models--org--name/{blobs, snapshots/<rev>, refs/main} with every snapshot file a
    symlink into blobs. files maps relpath -> bytes; broken lists relpaths whose blob is missing.
    Returns the repo directory."""
    rev = "0123456789abcdef0123456789abcdef01234567"
    repo_dir = os.path.join(str(root), "hub", "models--" + repo.replace("/", "--"))
    blobs = os.path.join(repo_dir, "blobs")
    snap = os.path.join(repo_dir, "snapshots", rev)
    os.makedirs(blobs, exist_ok=True)
    os.makedirs(snap, exist_ok=True)
    for i, (rel, data) in enumerate(sorted(files.items())):
        blob = os.path.join(blobs, "blob%04d" % i)
        if rel not in broken:
            with open(blob, "wb") as f:
                f.write(data)
        link = os.path.join(snap, rel)
        os.makedirs(os.path.dirname(link), exist_ok=True)
        os.symlink(os.path.relpath(blob, os.path.dirname(link)), link)
    for i in range(incomplete):
        with open(os.path.join(blobs, "partial%d.incomplete" % i), "wb") as f:
            f.write(b"x")
    if refs:
        os.makedirs(os.path.join(repo_dir, "refs"), exist_ok=True)
        with open(os.path.join(repo_dir, "refs", "main"), "w") as f:
            f.write(rev + "\n")
    return repo_dir


# ---------------------------------------------------------------------------
# Safetensors files
# ---------------------------------------------------------------------------

def fake_safetensors(path, header=None, n=None):
    """A minimal safetensors file: 8-byte little-endian header length, then the JSON header."""
    raw = json.dumps(header if header is not None else {"__metadata__": {}}).encode("utf-8")
    with open(path, "wb") as f:
        f.write((len(raw) if n is None else n).to_bytes(8, "little") + raw)
    return path


# ---------------------------------------------------------------------------
# In-process HTTP
# ---------------------------------------------------------------------------

TOKEN = "test-token-not-a-secret"


class Running(object):
    """A movie-ui server on 127.0.0.1:<free port>, serving on a thread."""

    def __init__(self, state, ui_ws=WS):
        import movie_ui_server
        self.server = movie_ui_server.make_server(0, state, ui_ws, TOKEN)
        self.port = self.server.port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def api(server, method, path, body=None, token=TOKEN, headers=None, raw=None):
    """One http.client request to a Running server; returns (status, headers dict, parsed JSON
    or bytes). body is sent as JSON; raw is sent as-is."""
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=60)
    hdrs = {"Host": "127.0.0.1:%d" % server.port}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    if raw is not None:
        data = raw
    if token is not None:
        hdrs["X-Movie-UI-Token"] = token
    hdrs.update(headers or {})
    try:
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for key, value in hdrs.items():
            if value is not None:
                conn.putheader(key, value)
        if data is not None and "Content-Length" not in hdrs:
            conn.putheader("Content-Length", str(len(data)))
        conn.endheaders()
        if data is not None:
            conn.send(data)
        resp = conn.getresponse()
        payload = resp.read()
        result_headers = dict((k.lower(), v) for k, v in resp.getheaders())
        if result_headers.get("content-type", "").startswith("application/json"):
            payload = json.loads(payload.decode("utf-8"))
        return resp.status, result_headers, payload
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Agents, registries and a copy of the UI
# ---------------------------------------------------------------------------

def registry(host_ids, port):
    """A valid fleet registry naming host_ids, every host at port."""
    hosts = {}
    for host_id in host_ids:
        hosts[host_id] = {"role": "agent", "address": "127.0.0.1", "port": port,
                          "model_server": {"type": "vllm", "url": "http://127.0.0.1:9/v1"},
                          "model": "m", "skills": []}
    return {"protocol": 1, "fleet_id": "0123456789abcdef", "hosts": hosts}


def make_agents_home(home, agents):
    """With HOME already set to home, build ~/agents/<id> for each agents item
    {id: {"current": tag or None, "releases": {tag: {"data": bool, "bytes": n}}, "state": dict or None,
    "port": int or None, "ports": [int, ...] (one registry file each), "fleet_env": bool (an empty
    fleet.env, so an agent without current is on disk), "default": bool (the ~/.local/bin/qwen-agent
    wrapper names it)}}. Returns {id: deploy root}."""
    roots = {}
    for agent, spec in agents.items():
        a = os.path.join(str(home), "agents", agent)
        roots[agent] = a
        os.makedirs(os.path.join(a, "releases"), exist_ok=True)
        for tag, rel in spec.get("releases", {}).items():
            ws = os.path.join(a, "releases", tag, fleet_lib.WS_SUBDIR)
            os.makedirs(os.path.join(ws, "bin"), exist_ok=True)
            with open(os.path.join(ws, "bin", "ltx-movie"), "w") as f:
                f.write("#!/bin/sh\n")
            if rel.get("data"):
                story = os.path.join(ws, "generated", "stories", "old-story")
                os.makedirs(story, exist_ok=True)
                with open(os.path.join(story, "story.md"), "wb") as f:
                    f.write(b"x" * rel.get("bytes", 10))
            fleets = os.path.join(ws, "fleets")
            os.makedirs(fleets, exist_ok=True)
            ports = spec.get("ports") or ([spec["port"]] if spec.get("port") else [])
            for i, port in enumerate(ports):
                with open(os.path.join(fleets, "f%d.json" % i), "w") as f:
                    json.dump(registry([agent], port), f)
        if spec.get("current"):
            os.symlink(os.path.join("releases", spec["current"]), os.path.join(a, "current"))
        if spec.get("fleet_env"):
            open(os.path.join(a, "fleet.env"), "w").close()
        if spec.get("state") is not None:
            with open(os.path.join(a, "update-state.json"), "w") as f:
                json.dump(spec["state"], f)
        if spec.get("default"):
            bindir = os.path.join(str(home), ".local", "bin")
            os.makedirs(bindir, exist_ok=True)
            with open(os.path.join(bindir, "qwen-agent"), "wb") as f:
                f.write(fleet_lib.wrapper_bytes(agent, spec.get("port") or fleet_lib.DEFAULT_PORT))
    return roots


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def copy_ui(tmp):
    """A copy of the movie-ui files (bin/movie-ui, bin/movie-ui-job, movie_ui_lib.py,
    movie_ui_server.py, fleet_lib.py, static/movie-ui) plus the stub tools, so a subprocess
    bin/movie-ui probes stubs instead of this checkout's real bin/story-server. Returns its root."""
    root = make_stub_workspace(os.path.join(str(tmp), "ui"))
    for rel in ("bin/movie-ui", "bin/movie-ui-job", "movie_ui_lib.py", "movie_ui_server.py", "fleet_lib.py",
                "movie_ui_batch.py"):
        shutil.copy2(os.path.join(WS, rel), os.path.join(root, rel))
    static = os.path.join(WS, "static", "movie-ui")
    if os.path.isdir(static):
        shutil.copytree(static, os.path.join(root, "static", "movie-ui"))
    return root


# ---------------------------------------------------------------------------
# Upload bytes: magic numbers only, never decoded pictures
# ---------------------------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 24


# ---------------------------------------------------------------------------
# Trace records and a fake daemon
# ---------------------------------------------------------------------------

def trace_record(trace_id, span_id, parent, agent, start, kind="turn", name="planner", dur_ms=1000,
                 status="ok"):
    attrs = {"turn": {"rounds": 1, "tool_calls": 0},
             "run": {"skill": "planner", "request_id": "r1", "http": 200, "images": 0, "image_bytes": 0}}[kind]
    return {"v": 1, "trace_id": trace_id, "span_id": span_id, "parent_span_id": parent, "agent": agent,
            "kind": kind, "name": name, "start": start, "dur_ms": dur_ms, "status": status, "attrs": attrs}


class FakeDaemon(object):
    """http.server on 127.0.0.1:<free port> answering GET /traces/recent?n= and GET /trace?id= with
    canned bodies (recent: a dict, traces: {trace_id: result dict}); records each request's headers."""

    def __init__(self, agent, recent=None, traces=None, status=200):
        self.agent, self.recent, self.traces, self.status = agent, recent, traces or {}, status
        self.requests = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def do_GET(self):
                outer.requests.append({"path": self.path, "headers": dict(self.headers.items())})
                if self.path.startswith("/traces/recent"):
                    obj = outer.recent if outer.recent is not None else {
                        "schema": fleet_lib.RECENT_SCHEMA, "agent": outer.agent, "traces": []}
                elif self.path.startswith("/trace?id="):
                    obj = outer.traces.get(self.path[len("/trace?id="):])
                else:
                    obj = None
                code = outer.status if obj is not None else 404
                data = json.dumps(obj if obj is not None else {"error": "not found"}).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


# ---------------------------------------------------------------------------
# V7 smoke render host
# ---------------------------------------------------------------------------

def smoke_host(monkeypatch, tmp_path):
    """A host where V2 render passes and V3 finds the default video model and gemma: stub
    ffmpeg, ffprobe and ltx-2-mlx on PATH and LTX2_MLX_BIN, and an LTX HF cache holding both."""
    tools = os.path.join(str(tmp_path), "tools")
    os.makedirs(tools, exist_ok=True)
    for name in ("ffmpeg", "ffprobe", "ltx-2-mlx"):
        path = os.path.join(tools, name)
        with open(path, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(path, 0o755)
    monkeypatch.setenv("PATH", tools + os.pathsep + "/usr/bin:/bin")
    monkeypatch.setenv("LTX2_MLX_BIN", os.path.join(tools, "ltx-2-mlx"))
    cache = os.path.join(str(tmp_path), "ltxcache")
    monkeypatch.setenv("LTX2_MLX_HF_HOME", cache)
    for repo in (movie_ui_lib.DEFAULT_MODEL, movie_ui_lib.DEFAULT_GEMMA):
        make_hf_cache(cache, repo, {"model.safetensors": b"\x01" * 8})
