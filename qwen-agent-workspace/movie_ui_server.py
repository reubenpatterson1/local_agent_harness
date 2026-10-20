"""movie_ui_server -- the HTTP side of movie-ui: the hardened loopback server, the route table,
the JSON API, /files, the dispatcher and capability-probe threads, the trace proxy and main().

See docs/superpowers/specs/2026-10-19-movie-ui-design.md (the movie-ui spec, piece F).
Standard library only, plus movie_ui_lib and this workspace's own fleet_lib (read-only names
only, GC7). Outbound HTTP goes only through fleet_lib's http.client helpers (GC3); query strings
are parsed by the local parse_query. Valid on Python 3.9 and 3.13 (GC1).
"""

import argparse
import errno
import fcntl
import hashlib
import hmac
import http.server
import json
import os
import platform
import re
import secrets
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time

import fleet_lib
import movie_ui_lib as lib

UI_WS = os.path.dirname(os.path.realpath(__file__))
STORE_LOCK = threading.Lock()   # MU18: guards queue.json, server-side status writes, dispatch
MAX_BODY = 26214400             # 25 MiB (MU10)
UPLOAD_MAX = 20971520           # 20 MiB (MU53)
LOG_CHUNK = 262144              # MU58
HISTORY_MAX = 200               # MU67
FILE_CHUNK = 65536              # MU54
TOKEN_HEADER = "X-Movie-UI-Token"
PAGE_CSP = ("default-src 'self'; img-src 'self' blob:; media-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/static/app.css": ("app.css", "text/css; charset=utf-8")}
OFFSET_RE = re.compile(r"^[0-9]{1,15}$")
N_RE = re.compile(r"^[0-9]{1,3}$")
RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
UPLOAD_TYPES = {"image/png": ("png", b"\x89PNG\r\n\x1a\n"), "image/jpeg": ("jpg", b"\xff\xd8\xff"),
                "image/webp": ("webp", None)}
FILE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
              ".mp4": "video/mp4", ".json": "application/json", ".md": "text/plain; charset=utf-8",
              ".txt": "text/plain; charset=utf-8", ".log": "text/plain; charset=utf-8"}

_ID = r"([0-9]{8}-[0-9]{6}-[0-9a-f]{4})"
_STORY = r"([A-Za-z0-9][A-Za-z0-9._-]{0,79})"
_NAME = r"([a-z][a-z0-9-]{1,23})"
_TRACE = r"([0-9a-f]{32})"
_SAMPLE_ID = "20261019-142233-a1b2"
_SAMPLE_TRACE = "0123456789abcdef0123456789abcdef"

# MU11: (method, regex, handler name, sample path), matched with re.fullmatch in this order.
ROUTES = [
    ("GET", r"/api/host", "h_host", "/api/host"),
    ("GET", r"/api/workspaces", "h_workspaces", "/api/workspaces"),
    ("GET", r"/api/options", "h_options", "/api/options"),
    ("GET", r"/api/loras", "h_loras", "/api/loras"),
    ("POST", r"/api/loras", "h_lora_add", "/api/loras"),
    ("POST", r"/api/loras/remove", "h_lora_remove", "/api/loras/remove"),
    ("POST", r"/api/loras/verify", "h_lora_verify", "/api/loras/verify"),
    ("GET", r"/api/models", "h_models", "/api/models"),
    ("GET", r"/api/characters", "h_characters", "/api/characters"),
    ("POST", r"/api/characters", "h_character_create", "/api/characters"),
    ("GET", r"/api/characters/" + _NAME, "h_character", "/api/characters/kyra"),
    ("POST", r"/api/characters/" + _NAME + r"/train", "h_character_train", "/api/characters/kyra/train"),
    ("POST", r"/api/characters/" + _NAME + r"/regenerate", "h_character_regenerate",
     "/api/characters/kyra/regenerate"),
    ("POST", r"/api/uploads", "h_upload", "/api/uploads"),
    ("POST", r"/api/preview", "h_preview", "/api/preview"),
    ("POST", r"/api/validate", "h_validate", "/api/validate"),
    ("GET", r"/api/jobs", "h_jobs", "/api/jobs"),
    ("POST", r"/api/jobs", "h_job_create", "/api/jobs"),
    ("GET", r"/api/jobs/" + _ID, "h_job", "/api/jobs/" + _SAMPLE_ID),
    ("DELETE", r"/api/jobs/" + _ID, "h_job_delete", "/api/jobs/" + _SAMPLE_ID),
    ("GET", r"/api/jobs/" + _ID + r"/log", "h_job_log", "/api/jobs/" + _SAMPLE_ID + "/log"),
    ("POST", r"/api/jobs/" + _ID + r"/cancel", "h_job_cancel", "/api/jobs/" + _SAMPLE_ID + "/cancel"),
    ("POST", r"/api/jobs/" + _ID + r"/kill-orphan", "h_job_kill_orphan",
     "/api/jobs/" + _SAMPLE_ID + "/kill-orphan"),
    ("POST", r"/api/queue/move", "h_queue_move", "/api/queue/move"),
    ("GET", r"/api/stories", "h_stories", "/api/stories"),
    ("GET", r"/api/stories/" + _STORY, "h_story", "/api/stories/ronin-rescue"),
    ("PUT", r"/api/stories/" + _STORY + r"/story\.md", "h_story_save", "/api/stories/ronin-rescue/story.md"),
    ("GET", r"/api/traces/agents", "h_trace_agents", "/api/traces/agents"),
    ("GET", r"/api/traces/recent", "h_traces_recent", "/api/traces/recent"),
    ("GET", r"/api/traces/saved", "h_traces_saved", "/api/traces/saved"),
    ("GET", r"/api/traces/saved/" + _TRACE, "h_trace_saved", "/api/traces/saved/" + _SAMPLE_TRACE),
    ("DELETE", r"/api/traces/saved/" + _TRACE, "h_trace_saved_delete", "/api/traces/saved/" + _SAMPLE_TRACE),
    ("GET", r"/api/traces/" + _TRACE, "h_trace", "/api/traces/" + _SAMPLE_TRACE),
    ("POST", r"/api/traces/" + _TRACE + r"/save", "h_trace_save", "/api/traces/" + _SAMPLE_TRACE + "/save"),
    ("GET", r"/files", "h_files", "/files"),
]


class ApiError(Exception):
    """Raised by a handler to answer status with {"error": message, **extra}."""

    def __init__(self, status, message, **extra):
        Exception.__init__(self, message)
        self.status, self.body = status, dict({"error": message}, **extra)


def percent_decode(text):
    """+ becomes a space and %XX a byte; the bytes are decoded UTF-8 strictly (MU13). Raises
    ValueError on invalid UTF-8."""
    raw = text.replace("+", " ").encode("latin-1", "strict")
    out, i = bytearray(), 0
    while i < len(raw):
        if raw[i:i + 1] == b"%" and re.fullmatch(rb"[0-9A-Fa-f]{2}", raw[i + 1:i + 3]):
            out.append(int(raw[i + 1:i + 3], 16))
            i += 3
        else:
            out.append(raw[i])
            i += 1
    return bytes(out).decode("utf-8", "strict")


def parse_query(qs):
    """{key: value} from a query string; a repeated key keeps the last value (MU13). Raises
    ValueError on a decode error."""
    out = {}
    for item in qs.split("&"):
        if not item:
            continue
        key, _sep, value = item.partition("=")
        out[percent_decode(key)] = percent_decode(value)
    return out


def resolve_ws(value):
    """The realpath of a harness workspace, or ApiError(400) (MU14)."""
    if not isinstance(value, str):
        raise ApiError(400, "missing ws")
    if not os.path.isabs(value):
        raise ApiError(400, "ws must be an absolute path")
    try:
        real = os.path.realpath(value)
        found = "\x00" not in value and os.path.isdir(real) and \
            os.path.isfile(os.path.join(real, "bin", "ltx-movie"))
    except ValueError:
        found = False
    if not found:
        raise ApiError(400, "not a harness workspace (no bin/ltx-movie): %s" % value)
    return real


class MovieUIServer(http.server.ThreadingHTTPServer):
    """The movie-ui server bound to 127.0.0.1 (MU4). probe_ws and stills_py are the workspace and
    interpreter the capability probe uses (the UI workspace and sys.executable; tests change them)."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port, handler, state, ui_ws, token):
        http.server.ThreadingHTTPServer.__init__(self, ("127.0.0.1", port), handler)
        self.port = self.server_address[1]
        self.state = state
        self.ui_ws = os.path.realpath(ui_ws)
        self.token = token
        self.probe_ws = self.ui_ws
        self.stills_py = sys.executable
        self.cap_lock = threading.Lock()
        self.capabilities = dict((k, {"ok": None, "reason": "probing", "checked": None})
                                 for k in ("render", "stills", "story_server"))
        self.parser_lock = threading.Lock()
        self.parsers = {}
        self.job_cache = {}

    def refresh_capabilities(self):
        """Re-run MU60's three probes against probe_ws and store the results."""
        results = {"render": lib.render_check(), "stills": lib.stills_check(self.probe_ws, self.stills_py),
                   "story_server": lib.story_server_check(self.probe_ws)}
        checked = lib.utc_now()
        with self.cap_lock:
            for key, (ok, detail) in results.items():
                reason = detail if (key == "story_server" or not ok) else None
                self.capabilities[key] = {"ok": ok, "reason": reason, "checked": checked}

    def capability_snapshot(self):
        with self.cap_lock:
            return dict((k, dict(v)) for k, v in self.capabilities.items())

    def job(self, job_id):
        """job.json of job_id (immutable, cached by ID; MU32), or None."""
        if job_id not in self.job_cache:
            job = lib.read_job(lib.job_dir(self.state, job_id))
            if job is None:
                return None
            self.job_cache[job_id] = job
        return self.job_cache[job_id]

    def progress(self, job_id, job, status):
        """The MU56 object, feeding the job's parser the new bytes of log.txt (at most 1 MiB)."""
        with self.parser_lock:
            parser = self.parsers.get(job_id)
            if parser is None:
                parser = self.parsers[job_id] = lib.ProgressParser(job["kind"], job["fields"])
            try:
                with open(os.path.join(lib.job_dir(self.state, job_id), "log.txt"), "rb") as f:
                    f.seek(parser.offset)
                    parser.feed(f.read(lib.FEED_MAX))
            except OSError:
                pass
            return parser.snapshot(job, status, self.state)


def _bad_constant(name):
    raise ValueError("invalid JSON constant: %s" % name)


def _printable(text):
    """text with every control character shown as \\xNN and every non-ASCII character escaped (MU7)."""
    text = "".join("\\x%02x" % ord(c) if (ord(c) < 0x20 or ord(c) == 0x7f) else c for c in text)
    return text.encode("ascii", "backslashreplace").decode("ascii")


def make_server(port, state, ui_ws, token):
    """A MovieUIServer on ("127.0.0.1", port); port 0 picks a free port (MU4). Raises OSError."""
    return MovieUIServer(port, MovieUIHandler, state, ui_ws, token)


class MovieUIHandler(http.server.BaseHTTPRequestHandler):
    """MU9-MU14: Host, Origin, static, token, route, body, dispatch."""

    protocol_version = "HTTP/1.0"
    timeout = 30
    server_version = "movie-ui"

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_PUT(self):
        self._handle()

    def do_DELETE(self):
        self._handle()

    def __getattr__(self, name):
        """Every HTTP method goes through the full check order (MU10)."""
        if name.startswith("do_"):
            return self._handle
        raise AttributeError(name)

    def send_error(self, code, message=None, explain=None):
        if message is None:
            message = self.responses.get(code, ("error",))[0]
        if self.request_version == "HTTP/0.9":
            self.request_version = "HTTP/1.0"   # a refused request line still gets a status line and headers
        self.send_json(code, {"error": message})

    def log_message(self, fmt, *args):
        """Nothing: the default request log would print ?t=<token> (MU7)."""

    def log_request(self, code="-", size="-"):
        if getattr(self, "_logged_500", False):
            return
        try:
            status = int(code)
        except (TypeError, ValueError):
            return
        if status >= 500:
            sys.stderr.write(_printable("movie-ui: %s %s -> %d" % (
                getattr(self, "command", None) or "", getattr(self, "path", "").partition("?")[0], status)) + "\n")

    # -- responses --------------------------------------------------------------------------

    def _write(self, data):
        try:
            self.wfile.write(data)
        except OSError:
            pass

    def send_json(self, status, obj, headers=()):
        body = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()
        self._write(body)

    def _send_static(self, name, content_type):
        try:
            with open(os.path.join(self.server.ui_ws, "static", "movie-ui", name), "rb") as f:
                body = f.read()
        except OSError:
            self.send_json(404, {"error": "not found"})
            return
        self.send_response(200)
        for key, value in (("Content-Type", content_type), ("Content-Length", str(len(body))),
                           ("Content-Security-Policy", PAGE_CSP), ("X-Frame-Options", "DENY"),
                           ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"),
                           ("Cache-Control", "no-store")):
            self.send_header(key, value)
        self.end_headers()
        self._write(body)

    # -- the check order (MU10) -------------------------------------------------------------

    def _token_ok(self, value):
        return isinstance(value, str) and hmac.compare_digest(value.encode("utf-8"),
                                                              self.server.token.encode("utf-8"))

    def _handle(self):
        path, _sep, qs = self.path.partition("?")
        port = self.server.port
        if self.headers.get("Host") not in ("127.0.0.1:%d" % port, "localhost:%d" % port):
            self.send_json(403, {"error": "forbidden host"})
            return
        origin = self.headers.get("Origin")
        if origin is not None and origin not in ("http://127.0.0.1:%d" % port, "http://localhost:%d" % port):
            self.send_json(403, {"error": "forbidden origin"})
            return
        if self.command == "GET" and path in STATIC:
            self._send_static(*STATIC[path])
            return
        if path.startswith("/api/") or path == "/files":
            ok = self._token_ok(self.headers.get(TOKEN_HEADER))
            if not ok and path == "/files":
                try:
                    ok = self._token_ok(parse_query(qs).get("t"))
                except ValueError:
                    ok = False
            if not ok:
                self.send_json(401, {"error": "missing or invalid token"})
                return
        matched, route = False, None
        for method, regex, name, _sample in ROUTES:
            m = re.fullmatch(regex, path)
            if m:
                matched = True
                if method == self.command:
                    route = (name, m.groups())
                    break
        if route is None:
            self.send_json(405 if matched else 404, {"error": "method not allowed" if matched else "not found"})
            return
        body = None
        if self.command in ("POST", "PUT") or (self.command == "DELETE" and
                                                (self.headers.get("Content-Length") or "0").strip() != "0"):
            body = self._read_body(path)
            if body is None:
                return
        try:
            query = parse_query(qs)
        except ValueError:
            self.send_json(400, {"error": "invalid query string"})
            return
        try:
            result = getattr(self, route[0])(route[1], query, body)
            if result is not None:
                self.send_json(result[0], result[1])
        except ApiError as e:
            self.send_json(e.status, e.body)
            return
        except Exception as e:
            self._logged_500 = True
            sys.stderr.write(_printable("movie-ui: %s %s -> 500 (%s: %s)" % (
                self.command, path, type(e).__name__, e)) + "\n")
            self.send_json(500, {"error": "internal error"})

    def _read_body(self, path):
        """The parsed JSON object (or the raw bytes for POST /api/uploads), or None after an error
        response (MU10 step 6)."""
        length = self.headers.get("Content-Length")
        if length is None:
            self.send_json(411, {"error": "Content-Length required"})
            return None
        if not re.fullmatch(r"[0-9]{1,15}", length.strip()):
            self.send_json(400, {"error": "invalid Content-Length"})
            return None
        n = int(length.strip())
        if n > MAX_BODY:
            self.send_json(413, {"error": "request body too large"})
            return None
        media = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if self.command == "POST" and path == "/api/uploads":
            return self.rfile.read(n) if media in UPLOAD_TYPES and n <= UPLOAD_MAX else self._upload_refusal(media, n)
        if media != "application/json":
            self.send_json(415, {"error": "unsupported content type"})
            return None
        try:
            obj = json.loads(self.rfile.read(n).decode("utf-8"), parse_constant=_bad_constant)
            json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (UnicodeDecodeError, ValueError, RecursionError):
            self.send_json(400, {"error": "invalid JSON body"})
            return None
        if not isinstance(obj, dict):
            self.send_json(400, {"error": "body must be a JSON object"})
            return None
        return obj

    def _upload_refusal(self, media, n):
        if media not in UPLOAD_TYPES:
            self.send_json(415, {"error": "unsupported content type"})
        else:
            self.send_json(413, {"error": "upload larger than 20 MiB"})
        return None

    # -- helpers ----------------------------------------------------------------------------

    def ws(self, value):
        return resolve_ws(value)

    def story_id(self, value):
        """A URL story ID that also passes MU38's ".." rule, else ApiError(404)."""
        if not lib.valid_story_id(value):
            raise ApiError(404, "not found")
        return value


# ---------------------------------------------------------------------------
# Workspaces, versions, host and options (MU33-MU35, MU45-MU47, MU60)
# ---------------------------------------------------------------------------

def default_agent():
    """MU35: the default command's wrapper agent when it is on disk, else the only agent, else None."""
    ids = fleet_lib.agent_ids_on_disk()
    kind, found = fleet_lib.classify_command_path(fleet_lib.default_command_path())
    if kind == "wrapper" and found in ids:
        return found
    return ids[0] if len(ids) == 1 else None


def _has_ltx_movie(ws_path):
    return os.path.isfile(os.path.join(ws_path, "bin", "ltx-movie"))


def default_workspace(ui_ws):
    """MU34: an installed UI defaults to its agent's current workspace, else the UI workspace."""
    ui = os.path.realpath(ui_ws)
    root = os.path.realpath(os.path.expanduser("~/agents"))
    parts = os.path.relpath(ui, root).split(os.sep)
    if len(parts) == 4 and parts[0] not in ("", "..") and parts[1] == "releases" and parts[3] == fleet_lib.WS_SUBDIR:
        try:
            current = os.path.join(fleet_lib.deploy_root(default_agent() or parts[0]), "current",
                                   fleet_lib.WS_SUBDIR)
        except ValueError:
            return ui
        if _has_ltx_movie(current):
            return current
    return ui


def _git_commit(path):
    try:
        proc = subprocess.run(["git", "-C", path, "rev-parse", "--short", "HEAD"], stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = proc.stdout.decode("utf-8", "replace").strip()
    return text if proc.returncode == 0 and text else None


def _story_count(real):
    try:
        names = os.listdir(os.path.join(real, "generated", "stories"))
    except OSError:
        return 0
    return sum(1 for n in names if lib.valid_story_id(n) and n != lib.SMOKE_STORY_ID
               and os.path.isdir(os.path.join(real, "generated", "stories", n)))


def list_workspaces(ui_ws):
    """MU33: installed current and release workspaces of every agent, then the UI's own."""
    entries, by_real = [], {}

    def add(entry):
        real = entry["realpath"]
        if real in by_real:
            by_real[real]["is_current"] = by_real[real]["is_current"] or entry["is_current"]
            by_real[real]["is_ui"] = by_real[real]["is_ui"] or entry["is_ui"]
            return
        by_real[real] = entry
        entries.append(entry)

    for agent in fleet_lib.agent_ids_on_disk():
        a = fleet_lib.deploy_root(agent)
        releases = os.path.join(a, "releases")
        current_real = None
        cur_ws = os.path.join(a, "current", fleet_lib.WS_SUBDIR)
        cur_tag = os.path.basename(os.path.realpath(os.path.join(a, "current")))
        if _has_ltx_movie(cur_ws):
            current_real = os.path.realpath(cur_ws)
            tag = cur_tag if fleet_lib.tag_key(cur_tag) is not None else None
            add({"path": cur_ws, "realpath": current_real, "agent": agent, "tag": tag, "commit": None,
                 "is_current": True, "is_ui": False, "kind": "current"})
        try:
            present = os.listdir(releases)
        except OSError:
            present = []
        state = fleet_lib.read_state(os.path.join(a, "update-state.json"))
        doomed = set(fleet_lib.releases_to_prune(present, cur_tag, state))
        for name in sorted((n for n in present if fleet_lib.tag_key(n) is not None), key=fleet_lib.tag_key,
                           reverse=True):
            rel_ws = os.path.join(releases, name, fleet_lib.WS_SUBDIR)
            if not _has_ltx_movie(rel_ws):
                continue
            real = os.path.realpath(rel_ws)
            if name in doomed:
                prune = ("kept_for_data" if fleet_lib.release_holds_data(os.path.join(releases, name))
                         else "would_prune")
            else:
                prune = "kept"
            add({"path": rel_ws, "realpath": real, "agent": agent, "tag": name, "commit": None,
                 "is_current": real == current_real, "is_ui": False, "kind": "release", "prune": prune,
                 "data_bytes": lib._tree_bytes(os.path.join(real, "generated"))})
    ui = os.path.realpath(ui_ws)
    if ui in by_real:
        by_real[ui]["is_ui"] = True
    else:
        add({"path": ui, "realpath": ui, "agent": None, "tag": None, "commit": _git_commit(ui),
             "is_current": False, "is_ui": True, "kind": "ui"})
    out = []
    for e in entries:
        kind = e.pop("kind")
        if kind == "current":
            label = "%s current (%s)" % (e["agent"], e["tag"] or "unknown tag")
        elif kind == "release":
            label = "%s %s" % (e["agent"], e["tag"])
        else:
            label = "this checkout (%s)" % (e["commit"] or "unknown commit")
        e["label"] = label
        e.setdefault("prune", None)
        e.setdefault("data_bytes", None)
        e["stories"] = _story_count(e["realpath"])
        out.append(dict((k, e[k]) for k in ("path", "realpath", "label", "agent", "tag", "commit",
                                            "is_current", "is_ui", "stories", "prune", "data_bytes")))
    return out


def _running_job(state):
    for job_id in lib.active_job_ids(state):
        return job_id
    return None


def _h_host(self, groups, query, body):
    if query.get("refresh") == "1":
        self.server.refresh_capabilities()
    state = self.server.state
    return 200, {"host": socket.gethostname(), "platform": sys.platform, "python": platform.python_version(),
                 "port": self.server.port, "state_dir": state, "ui_workspace": self.server.ui_ws,
                 "default_workspace": default_workspace(self.server.ui_ws), "default_agent": default_agent(),
                 "api_key_present": bool(os.environ.get("ANTHROPIC_API_KEY")),
                 "capabilities": self.server.capability_snapshot(),
                 "running_job": _running_job(state), "queue_length": len(lib.read_queue(state))}


def _h_workspaces(self, groups, query, body):
    return 200, {"default": default_workspace(self.server.ui_ws), "workspaces": list_workspaces(self.server.ui_ws)}


def _h_options(self, groups, query, body):
    real = self.ws(query.get("ws"))
    flags, error = lib.help_flags(real)
    return 200, {"workspace": real, "help_ok": flags is not None, "help_error": error,
                 "flags": sorted(flags or ()), "supported": lib.supported_map(flags),
                 "defaults": dict(lib.OPTION_DEFAULTS)}


MovieUIHandler.h_host = _h_host
MovieUIHandler.h_workspaces = _h_workspaces
MovieUIHandler.h_options = _h_options


def _dispatcher_loop(server, stop):
    """MU30: one dispatch tick per second under STORE_LOCK; errors are logged, never fatal."""
    while not stop.wait(1.0):
        try:
            with STORE_LOCK:
                lib.dispatch_tick(server.state, server.ui_ws)
        except Exception as e:
            sys.stderr.write("movie-ui: dispatcher: %s: %s\n" % (type(e).__name__, e))


def _probe_once(server):
    try:
        server.refresh_capabilities()
    except Exception as e:
        sys.stderr.write("movie-ui: capability probe: %s: %s\n" % (type(e).__name__, e))


def start_threads(server):
    """Start the dispatcher (MU30) and capability-probe (MU60) threads, both daemon; returns the
    Event that stops the dispatcher."""
    stop = threading.Event()
    threading.Thread(target=_dispatcher_loop, args=(server, stop), name="dispatcher", daemon=True).start()
    threading.Thread(target=_probe_once, args=(server,), name="probe", daemon=True).start()
    return stop


_LOCK_FD = []


def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt


def main(argv):
    """bin/movie-ui (MU1-MU7). Returns the exit code."""
    parser = argparse.ArgumentParser(prog="movie-ui", description="The locally hosted movie page.")
    parser.add_argument("--port", default="8999", help="TCP port on 127.0.0.1 (default 8999)")
    args = parser.parse_args(argv)
    if not (re.fullmatch(r"[0-9]{1,5}", args.port) and 1024 <= int(args.port) <= 65535):
        sys.stderr.write("movie-ui: invalid --port %s (1024 to 65535)\n" % args.port)
        return 2
    port = int(args.port)
    state = lib.state_dir()
    lib.ensure_state(state)
    lock_path = os.path.join(state, "server.lock")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        sys.stderr.write("movie-ui: another movie-ui is already running on this host (lock held: %s)\n"
                         % lock_path)
        return 2
    _LOCK_FD.append(fd)
    token = secrets.token_urlsafe(32)
    try:
        server = make_server(port, state, UI_WS, token)
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            sys.stderr.write("movie-ui: port %d on 127.0.0.1 is in use; pass --port N\n" % port)
        else:
            sys.stderr.write("movie-ui: cannot listen on 127.0.0.1:%d: %s\n" % (port, e.strerror or e))
        return 2
    with STORE_LOCK:
        lib.startup_recovery(state)
    stop = start_threads(server)
    signal.signal(signal.SIGTERM, _raise_interrupt)
    sys.stdout.write("movie-ui: http://127.0.0.1:%d/?t=%s\n" % (server.port, token))
    sys.stdout.write("movie-ui: state %s; Ctrl-C stops the server (running jobs keep running)\n" % state)
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    stop.set()
    server.server_close()
    sys.stdout.write("movie-ui: stopped\n")
    sys.stdout.flush()
    return 0


# ---------------------------------------------------------------------------
# Compose and jobs (MU44, MU58, MU66-MU68)
# ---------------------------------------------------------------------------

COMPOSE_KINDS = {"story": "story", "regenerate": "story", "movie": "movie", "redo": "movie"}


def job_summary(server, job_id, queue):
    """MU67's summary object for one job, or None when job.json is unreadable."""
    job = server.job(job_id)
    if job is None:
        return None
    status = lib.read_status(lib.job_dir(server.state, job_id)) or {}
    state = lib.job_state(server.state, job_id, queue)
    return {"id": job_id, "kind": job["kind"], "state": state, "workspace": job["workspace"],
            "story_id": job["story_id"], "character": job["character"], "created": job["created"],
            "started": status.get("started"), "ended": status.get("ended"), "exit_code": status.get("exit_code"),
            "error": status.get("error"), "queue_position": queue.index(job_id) + 1 if state == "queued" else None,
            "command": shlex.join(job["argv"]),
            "progress": server.progress(job_id, job, status) if state in lib.ACTIVE_STATES else None}


def _fields_body(body):
    fields = lib.compose_fields(body)
    fields["ws"] = resolve_ws(body.get("ws"))
    return fields


def _preview(server, fields):
    errors = lib.validate_fields(fields, fields["ws"], server.state)
    if errors:
        return None, errors
    return lib.build_argv(fields, fields["ws"], server.state), errors


def _h_preview(self, groups, query, body):
    fields = _fields_body(body)
    argv, errors = _preview(self.server, fields)
    return 200, {"argv": argv, "command": shlex.join(argv) if argv else None, "errors": errors}


def _h_validate(self, groups, query, body):
    fields = _fields_body(body)
    checks = lib.run_checks(fields, fields["ws"], self.server.state)
    argv, _errors = _preview(self.server, fields)
    return 200, {"ok": lib.checks_pass(checks), "checks": checks, "argv": argv,
                 "command": shlex.join(argv) if argv else None}


def create_compose_job(server, fields):
    """Create the queued job of a validated compose submission; returns its ID."""
    state, real = server.state, fields["ws"]
    with STORE_LOCK:
        job_id = lib.new_job_id(state)
        argv = lib.build_argv(fields, real, state)
        return lib.create_job(state, job_id, COMPOSE_KINDS[fields["action"]], real, fields["story_id"], None,
                              argv, fields)["id"]


def _h_job_create(self, groups, query, body):
    fields = _fields_body(body)
    checks = lib.run_checks(fields, fields["ws"], self.server.state)
    if not lib.checks_pass(checks):
        raise ApiError(409, "validation failed", checks=checks)
    job_id = create_compose_job(self.server, fields)
    return 201, {"job": job_summary(self.server, job_id, lib.read_queue(self.server.state)), "checks": checks}


def _h_jobs(self, groups, query, body):
    server = self.server
    queue = lib.read_queue(server.state)
    running, history = None, []
    for job_id in sorted(lib.list_job_ids(server.state), reverse=True):
        summary = job_summary(server, job_id, queue)
        if summary is None:
            continue
        if summary["state"] in lib.ACTIVE_STATES and running is None:
            running = summary
        elif summary["state"] in lib.FINISHED_STATES and len(history) < HISTORY_MAX:
            history.append(summary)
    queued = [s for s in (job_summary(server, i, queue) for i in queue) if s is not None]
    blocked_by = None
    for job_id in lib.list_job_ids(server.state):
        info = lib.orphan_info(lib.read_status(lib.job_dir(server.state, job_id)))
        if info is not None:
            blocked_by = {"job": job_id, "pgid": info["pgid"]}
            break
    return 200, {"running": running, "queued": queued, "history": history, "blocked_by": blocked_by}


def _known_job(server, job_id):
    job = server.job(job_id) if os.path.isdir(lib.job_dir(server.state, job_id)) else None
    if job is None:
        raise ApiError(404, "unknown job %s" % job_id)
    return job


def _h_job(self, groups, query, body):
    server, job_id = self.server, groups[0]
    job = _known_job(server, job_id)
    status = lib.read_status(lib.job_dir(server.state, job_id))
    if status is None:
        shown = {"state": lib.job_state(server.state, job_id, lib.read_queue(server.state))}
    else:
        shown = status
    return 200, {"job": job, "status": shown,
                 "progress": server.progress(job_id, job, status) if status is not None else None,
                 "orphan": lib.orphan_info(status),
                 "window": {"start": (status or {}).get("started"), "end": (status or {}).get("ended")}}


def utf8_cut(data):
    """data without a trailing incomplete UTF-8 sequence (at most 3 bytes are dropped; MU58)."""
    for back in range(1, min(3, len(data)) + 1):
        byte = data[-back]
        if byte & 0xC0 == 0x80:
            continue
        need = 2 if byte & 0xE0 == 0xC0 else 3 if byte & 0xF0 == 0xE0 else 4 if byte & 0xF8 == 0xF0 else 1
        return data[:-back] if need > back else data
    return data


def _h_job_log(self, groups, query, body):
    server, job_id = self.server, groups[0]
    offset = query.get("offset", "0")
    if not OFFSET_RE.fullmatch(offset):
        raise ApiError(400, "invalid offset")
    _known_job(server, job_id)
    n = int(offset)
    path = os.path.join(lib.job_dir(server.state, job_id), "log.txt")
    try:
        with open(path, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            if n >= size:
                data = b""
            else:
                f.seek(n)
                data = f.read(min(LOG_CHUNK, size - n))
                finished = lib.job_state(server.state, job_id, lib.read_queue(server.state)) in lib.FINISHED_STATES
                if not (n + len(data) >= size and finished):
                    data = utf8_cut(data)
    except OSError:
        raise ApiError(404, "unknown job %s" % job_id)
    nxt = size if n >= size else n + len(data)
    return 200, {"offset": n, "next_offset": nxt, "size": size, "eof": nxt >= size,
                 "text": data.decode("utf-8", "replace")}


def _h_job_cancel(self, groups, query, body):
    job_id = groups[0]
    _known_job(self.server, job_id)
    with STORE_LOCK:
        result = lib.cancel_job(self.server.state, job_id)
    if result == "cancelled":
        return 200, {"state": "cancelled"}
    if result == "cancelling":
        return 202, {"state": "cancelling"}
    raise ApiError(409, "job %s is not queued or running" % job_id)


def _h_queue_move(self, groups, query, body):
    job_id, direction = body.get("id"), body.get("direction")
    if direction not in ("up", "down"):
        raise ApiError(400, "direction must be up or down")
    if not (isinstance(job_id, str) and lib.JOB_ID_RE.fullmatch(job_id)):
        raise ApiError(409, "job %s is not queued" % (job_id,))
    with STORE_LOCK:
        queue = lib.move_job(self.server.state, job_id, direction)
    if queue is None:
        raise ApiError(409, "job %s is not queued" % job_id)
    return 200, {"queued": queue}


def _h_job_delete(self, groups, query, body):
    job_id = groups[0]
    _known_job(self.server, job_id)
    state = self.server.state
    try:
        with STORE_LOCK:
            info = lib.orphan_info(lib.read_status(lib.job_dir(state, job_id)))
            body = body or {}
            if info is not None and not (set(body) == {"confirm"} and body["confirm"] is True):
                raise ApiError(409, "job %s still has a live process group %d; kill it first, or delete "
                                    "with confirm to unblock the queue anyway" % (job_id, info["pgid"]))
            try:
                deleted = lib.delete_job(state, job_id)
            except OSError as e:
                raise ApiError(500, "cannot delete job %s: %s" % (job_id, e.strerror or e))
        if not deleted:
            raise ApiError(409, "job %s is not finished" % job_id)
        return 200, {"deleted": job_id}
    finally:
        if not os.path.isdir(lib.job_dir(state, job_id)):
            self.server.job_cache.pop(job_id, None)
            with self.server.parser_lock:
                self.server.parsers.pop(job_id, None)


def _h_job_kill_orphan(self, groups, query, body):
    job_id = groups[0]
    if body.get("confirm") is not True:
        raise ApiError(400, "confirm must be true")
    _known_job(self.server, job_id)
    with STORE_LOCK:
        try:
            pgid = lib.kill_orphan(self.server.state, job_id)
        except PermissionError as e:
            info = lib.orphan_info(lib.read_status(lib.job_dir(self.server.state, job_id)))
            raise ApiError(409, "cannot kill process group %s: %s" % (info["pgid"] if info else "?", e.strerror or e))
    if pgid is None:
        raise ApiError(409, "job %s has no live orphan process group" % job_id)
    return 200, {"killed": pgid}


MovieUIHandler.h_preview = _h_preview
MovieUIHandler.h_validate = _h_validate
MovieUIHandler.h_job_create = _h_job_create
MovieUIHandler.h_jobs = _h_jobs
MovieUIHandler.h_job = _h_job
MovieUIHandler.h_job_log = _h_job_log
MovieUIHandler.h_job_cancel = _h_job_cancel
MovieUIHandler.h_queue_move = _h_queue_move
MovieUIHandler.h_job_delete = _h_job_delete
MovieUIHandler.h_job_kill_orphan = _h_job_kill_orphan


# ---------------------------------------------------------------------------
# Uploads, LoRAs, models and characters (MU53, MU59, MU61-MU65)
# ---------------------------------------------------------------------------

def _fs_text(name):
    """Text safe for JSON/ApiError from a filesystem name that may hold surrogateescape characters."""
    return name.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def tool_result(tool, run):
    """MU59: 504 on a timeout, 502 on a non-zero exit (ApiError), else run."""
    if run["timed_out"]:
        raise ApiError(504, "%s timed out after %d s" % (tool, lib.LIGHT_TIMEOUT), run=run)
    if run["exit_code"] != 0:
        raise ApiError(502, "%s exited %s" % (tool, run["exit_code"]), run=run)
    return run


def _h_upload(self, groups, query, body):
    media = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    ext, magic = UPLOAD_TYPES[media]
    ok = (body[:4] == b"RIFF" and body[8:12] == b"WEBP") if magic is None else body.startswith(magic)
    if not ok:
        raise ApiError(400, "file content is not %s" % media)
    upload_id = "%s.%s" % (hashlib.sha256(body).hexdigest(), ext)
    path = os.path.join(self.server.state, "uploads", upload_id)
    if not os.path.isfile(path):
        lib.write_bytes_atomic(path, body)
    return 201, {"upload_id": upload_id, "path": path, "bytes": len(body)}


def _h_loras(self, groups, query, body):
    real = self.ws(query.get("ws"))
    model = query.get("model")
    if model:
        _check_arg("model", model)
    args = ["list", "--json"] + (["--model", model] if model else [])
    run = tool_result("lora-catalog", lib.run_light(lib.tool_argv(real, "lora-catalog", *args), real))
    try:
        obj = json.loads(run["stdout"])
        if not isinstance(obj, dict):
            raise ValueError
    except ValueError:
        raise ApiError(502, "lora-catalog printed unparsable output", run=run)
    obj["model"] = model or None
    return 200, obj


def _check_arg(key, value):
    """400 unless value can be a safe, non-flag-like argv element."""
    if not lib._argv_safe(value):
        raise ApiError(400, "%s contains invalid characters" % key)
    if value.startswith("-"):
        raise ApiError(400, "%s must not start with '-'" % key)


def _lora_action(real, args):
    run = lib.run_light(lib.tool_argv(real, "lora-catalog", *args), real)
    if run["timed_out"]:
        raise ApiError(504, "lora-catalog timed out after %d s" % lib.LIGHT_TIMEOUT, run=run)
    return run


def _typed(body, key, kind, name, optional=False):
    value = body.get(key)
    if value is None and optional:
        return None
    ok = {"str": isinstance(value, str),
          "str list": isinstance(value, list) and all(isinstance(v, str) for v in value),
          "number": isinstance(value, (int, float)) and not isinstance(value, bool),
          "int": isinstance(value, int) and not isinstance(value, bool),
          "pair": (isinstance(value, list) and len(value) == 2
                   and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value))}[kind]
    if not ok:
        raise ApiError(400, "%s must be %s" % (key, name))
    return value


def _h_lora_add(self, groups, query, body):
    real = self.ws(body.get("ws"))
    path = _typed(body, "path", "str", "a string")
    entry_id = _typed(body, "id", "str", "a string")
    kind = _typed(body, "kind", "str", "a string")
    target = _typed(body, "target", "str", "a string")
    base_models = _typed(body, "base_models", "str list", "a list of strings")
    triggers = _typed(body, "triggers", "str list", "a list of strings")
    description = _typed(body, "description", "str", "a string")
    use_when = _typed(body, "use_when", "str", "a string")
    avoid_when = _typed(body, "avoid_when", "str", "a string", optional=True)
    strength = _typed(body, "default_strength", "number", "a number")
    lo, hi = _typed(body, "strength_range", "pair", "a list of two numbers")
    rank = _typed(body, "rank", "int", "an integer or null", optional=True)
    alpha = _typed(body, "alpha", "int", "an integer or null", optional=True)
    if not path.startswith("/"):
        raise ApiError(400, "path must be an absolute path")
    for key, value in (("path", path), ("id", entry_id), ("kind", kind), ("target", target),
                       ("description", description), ("use_when", use_when), ("avoid_when", avoid_when),
                       ("base_models", base_models), ("triggers", triggers)):
        for item in (value if isinstance(value, list) else [value]):
            if item is None:
                continue
            if not lib._argv_safe(item):
                raise ApiError(400, "%s contains invalid characters" % key)
            if key != "path" and item.startswith("-"):
                raise ApiError(400, "%s must not start with '-'" % key)
    args = ["add", path, "--id", entry_id, "--kind", kind, "--target", target]
    for m in base_models:
        args += ["--base-model", m]
    for t in triggers:
        args += ["--trigger", t]
    args += ["--description", description, "--use-when", use_when]
    if avoid_when:
        args += ["--avoid-when", avoid_when]
    args += ["--default-strength", repr(float(strength)),
             "--strength-range", "%s,%s" % (repr(float(lo)), repr(float(hi)))]
    if rank is not None:
        args += ["--rank", str(rank)]
    if alpha is not None:
        args += ["--alpha", str(alpha)]
    return 200, {"run": _lora_action(real, args)}


def _h_lora_remove(self, groups, query, body):
    real = self.ws(body.get("ws"))
    entry_id = _typed(body, "id", "str", "a string")
    _check_arg("id", entry_id)
    return 200, {"run": _lora_action(real, ["remove", entry_id])}


VERIFY_LINE_RE = re.compile(r"^(OK|FAIL) (\S+?)(?:: (.*))?$")


def parse_verify(stdout):
    """[{"id", "ok", "problems"}] from lora-catalog verify's OK/FAIL lines, in first-seen order."""
    results, by_id = [], {}
    for line in stdout.splitlines():
        m = VERIFY_LINE_RE.match(line)
        if not m:
            continue
        entry = by_id.get(m.group(2))
        if entry is None:
            entry = by_id[m.group(2)] = {"id": m.group(2), "ok": True, "problems": []}
            results.append(entry)
        if m.group(1) == "FAIL":
            entry["ok"] = False
            entry["problems"].append(m.group(3) or "")
    return results


def _h_lora_verify(self, groups, query, body):
    real = self.ws(body.get("ws"))
    ids = body.get("ids")
    if ids is None:
        ids = []
    if not (isinstance(ids, list) and all(isinstance(i, str) for i in ids)):
        raise ApiError(400, "ids must be a list of strings")
    for item in ids:
        _check_arg("ids", item)
    run = _lora_action(real, ["verify"] + ids)
    return 200, {"run": run, "results": parse_verify(run["stdout"])}


def _h_models(self, groups, query, body):
    self.ws(query.get("ws"))
    return 200, lib.list_models()


LIST_ROW_RE = re.compile(r"^(\S+)\s+(\S+)\s+(dataset|untrained|trained)\s+(yes|no)\s+(yes|no)\s+(.+)$")
INVALID_ROW_RE = re.compile(r"^(\S+)\s+\(invalid: (.*)\)$")
FILE_LINE_RE = re.compile(r"^  (ok|MISSING)\s+(.+)$")
STILL_FILE_RE = re.compile(r"^char_[0-9]{2}\.png$")


def parse_character_list(stdout):
    """MU64: rows of bin/character list."""
    out = []
    for line in stdout.splitlines():
        if line.startswith("NAME ") or line.startswith("no characters in ") or not line.strip():
            continue
        m = INVALID_ROW_RE.match(line)
        if m:
            out.append({"name": m.group(1), "invalid": m.group(2)})
            continue
        m = LIST_ROW_RE.match(line)
        if m:
            out.append({"name": m.group(1), "trigger": m.group(2), "status": m.group(3),
                        "video": m.group(4) == "yes", "stills": m.group(5) == "yes", "phrase": m.group(6),
                        "invalid": None})
    return out


def _h_characters(self, groups, query, body):
    real = self.ws(query.get("ws"))
    run = tool_result("character", lib.run_light(lib.tool_argv(real, "character", "list"), real))
    return 200, {"characters": parse_character_list(run["stdout"])}


def newest_job(server, kinds, ws_real, key, value):
    """The newest job of one of kinds whose workspace is ws_real and job[key] == value, or None."""
    for job_id in sorted(lib.list_job_ids(server.state), reverse=True):
        job = server.job(job_id)
        if job is not None and job["kind"] in kinds and job["workspace"] == ws_real and job.get(key) == value:
            return job
    return None


def _h_character(self, groups, query, body):
    real, name = self.ws(query.get("ws")), groups[0]
    run = tool_result("character", lib.run_light(lib.tool_argv(real, "character", "show", name), real))
    try:
        data, end = json.JSONDecoder().raw_decode(run["stdout"].lstrip())
    except ValueError:
        raise ApiError(502, "character printed unparsable output", run=run)
    rest = run["stdout"].lstrip()[end:]
    files = [{"status": m.group(1), "path": m.group(2)}
             for m in (FILE_LINE_RE.match(line) for line in rest.splitlines()) if m]
    dataset = None
    sheet = (data.get("dataset") or {}).get("contact_sheet") if isinstance(data, dict) else None
    if isinstance(sheet, str):
        stills_dir = os.path.join(os.path.dirname(sheet), "stills")
        try:
            stills = sorted(os.path.join(stills_dir, n) for n in os.listdir(stills_dir)
                            if STILL_FILE_RE.fullmatch(n) and os.path.isfile(os.path.join(stills_dir, n)))
        except OSError:
            stills = []
        dataset = {"contact_sheet": sheet, "stills": stills}
    job = newest_job(self.server, ("character-create",), real, "character", name)
    face = False
    if job is not None:
        parser = lib.ProgressParser(job["kind"], job["fields"])
        try:
            with open(os.path.join(lib.job_dir(self.server.state, job["id"]), "log.txt"), "rb") as f:
                parser.feed(f.read() + b"\n")
        except OSError:
            pass
        face = parser.face_problem
    return 200, {"character": data, "files": files, "dataset": dataset, "face_problem": face,
                 "last_create_fields": job["fields"] if job is not None else None}


PHRASE_MAX = 200


def character_create_errors(body, state):
    """MU65's field rules for POST /api/characters; [] when they pass."""
    errors = []
    name, phrase = body.get("name"), body.get("phrase")
    seed = body.get("seed_upload")
    if seed == "":
        seed = None
    descriptor, class_noun = body.get("descriptor"), body.get("class_noun")
    trigger, seed_n, force = body.get("trigger"), body.get("seed"), body.get("force", False)
    if not (isinstance(name, str) and lib.CHARACTER_NAME_RE.fullmatch(name)):
        errors.append("character name must match [a-z][a-z0-9-]{1,23}")
    if not (isinstance(phrase, str) and 1 <= len(phrase.strip()) and len(phrase) <= PHRASE_MAX
            and "\n" not in phrase and "\r" not in phrase):
        errors.append("phrase is required")
    elif not lib._argv_safe(phrase):
        errors.append("phrase contains invalid characters")
    elif phrase.strip().startswith("-"):
        errors.append("phrase must not start with '-'")
    if (seed is None) == (descriptor is None or descriptor == ""):
        errors.append("give exactly one of a seed image or a descriptor")
    if descriptor not in (None, "") and not class_noun:
        errors.append("a descriptor needs a class noun")
    if descriptor not in (None, "") and not isinstance(descriptor, str):
        errors.append("descriptor must be a string")
    elif descriptor not in (None, "") and not lib._argv_safe(descriptor):
        errors.append("descriptor contains invalid characters")
    elif descriptor not in (None, "") and descriptor.strip().startswith("-"):
        errors.append("descriptor must not start with '-'")
    if class_noun not in (None, "") and not (isinstance(class_noun, str) and re.fullmatch(r"[a-z]{3,12}", class_noun)):
        errors.append("class noun must match [a-z]{3,12}")
    if trigger not in (None, "") and not (isinstance(trigger, str) and re.fullmatch(r"[a-z][a-z0-9]{3,15}", trigger)):
        errors.append("trigger must match [a-z][a-z0-9]{3,15}")
    if seed_n is not None and not (isinstance(seed_n, int) and not isinstance(seed_n, bool) and seed_n >= 0):
        errors.append("seed must be an integer >= 0")
    if seed is not None and not (isinstance(seed, str) and lib.UPLOAD_ID_RE.fullmatch(seed)
                                 and os.path.isfile(os.path.join(state, "uploads", seed))):
        errors.append("seed image upload %s not found" % (_fs_text(seed) if isinstance(seed, str) else seed,))
    if not isinstance(force, bool):
        errors.append("force must be true or false")
    return errors


def create_character_job(server, kind, real, fields):
    with STORE_LOCK:
        job_id = lib.new_job_id(server.state)
        argv = lib.character_argv(kind, fields, real, server.state)
        lib.create_job(server.state, job_id, kind, real, None, fields["name"], argv, fields)
    return 201, {"job": job_summary(server, job_id, lib.read_queue(server.state))}


def _h_character_create(self, groups, query, body):
    real = self.ws(body.get("ws"))
    errors = character_create_errors(body, self.server.state)
    if errors:
        raise ApiError(400, "invalid fields", errors=errors)
    fields = dict((k, body.get(k)) for k in ("name", "phrase", "class_noun", "descriptor", "trigger", "seed",
                                              "seed_upload"))
    for key in ("class_noun", "descriptor", "trigger", "seed_upload"):
        if fields[key] == "":
            fields[key] = None
    fields["force"] = body.get("force", False)
    fields["ws"] = real
    return create_character_job(self.server, "character-create", real, fields)


def _h_character_regenerate(self, groups, query, body):
    real = self.ws(body.get("ws"))
    return create_character_job(self.server, "character-regenerate", real, {"ws": real, "name": groups[0]})


def _h_character_train(self, groups, query, body):
    real = self.ws(body.get("ws"))
    fields = {"ws": real, "name": groups[0]}
    errors = []
    for key in ("video", "stills", "force"):
        value = body.get(key, False)
        if not isinstance(value, bool):
            errors.append("%s must be true or false" % key)
        fields[key] = value
    if not errors and not (fields["video"] or fields["stills"]):
        errors.append("choose video, stills or both")
    if errors:
        raise ApiError(400, "invalid fields", errors=errors)
    return create_character_job(self.server, "character-train", real, fields)


MovieUIHandler.h_upload = _h_upload
MovieUIHandler.h_loras = _h_loras
MovieUIHandler.h_lora_add = _h_lora_add
MovieUIHandler.h_lora_remove = _h_lora_remove
MovieUIHandler.h_lora_verify = _h_lora_verify
MovieUIHandler.h_models = _h_models
MovieUIHandler.h_characters = _h_characters
MovieUIHandler.h_character = _h_character
MovieUIHandler.h_character_create = _h_character_create
MovieUIHandler.h_character_regenerate = _h_character_regenerate
MovieUIHandler.h_character_train = _h_character_train
