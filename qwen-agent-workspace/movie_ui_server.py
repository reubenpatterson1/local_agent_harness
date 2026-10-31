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
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

import fleet_lib
import movie_ui_batch as batch
import movie_ui_lib as lib

UI_WS = os.path.dirname(os.path.realpath(__file__))
STORE_LOCK = threading.Lock()   # MU18: guards queue.json, server-side status writes, dispatch
BATCH_LOCK = threading.Lock()   # batch forks BF2: batch.json read-modify-writes, submit planning;
                                # never held together with STORE_LOCK
MAX_BODY = 26214400             # 25 MiB (MU10)
UPLOAD_MAX = 20971520           # 20 MiB (MU53)
LOG_CHUNK = 262144              # MU58
HISTORY_MAX = 200               # MU67
FILE_CHUNK = 65536              # MU54
SAVED_TRACE_MAX = 33554432      # largest saved trace file read (32 MiB)
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
_ACTION = r"([a-z][a-z0-9-]{1,31})"
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
    ("POST", r"/api/models/download", "h_model_download", "/api/models/download"),
    ("GET", r"/api/characters", "h_characters", "/api/characters"),
    ("POST", r"/api/characters", "h_character_create", "/api/characters"),
    ("GET", r"/api/characters/" + _NAME, "h_character", "/api/characters/kyra"),
    ("POST", r"/api/characters/" + _NAME + r"/train", "h_character_train", "/api/characters/kyra/train"),
    ("POST", r"/api/characters/" + _NAME + r"/regenerate", "h_character_regenerate",
     "/api/characters/kyra/regenerate"),
    ("GET", r"/api/locations", "h_locations", "/api/locations"),
    ("POST", r"/api/locations", "h_location_create", "/api/locations"),
    ("GET", r"/api/locations/" + _NAME, "h_location", "/api/locations/harbour-street"),
    ("PATCH", r"/api/locations/" + _NAME, "h_location_patch", "/api/locations/harbour-street"),
    ("POST", r"/api/locations/" + _NAME + r"/train", "h_location_train",
     "/api/locations/harbour-street/train"),
    ("POST", r"/api/locations/" + _NAME + r"/regenerate", "h_location_regenerate",
     "/api/locations/harbour-street/regenerate"),
    ("GET", r"/api/actions", "h_actions", "/api/actions"),
    ("POST", r"/api/actions", "h_action_create", "/api/actions"),
    ("GET", r"/api/actions/" + _ACTION, "h_action", "/api/actions/roundhouse-kick"),
    ("POST", r"/api/actions/" + _ACTION + r"/train", "h_action_train", "/api/actions/roundhouse-kick/train"),
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
    ("GET", r"/api/batches", "h_batches", "/api/batches"),
    ("POST", r"/api/batches", "h_batch_create", "/api/batches"),
    ("POST", r"/api/batches/preview", "h_batch_preview", "/api/batches/preview"),
    ("GET", r"/api/batches/stories", "h_batch_stories", "/api/batches/stories"),
    ("GET", r"/api/batches/" + _ID, "h_batch", "/api/batches/" + _SAMPLE_ID),
    ("DELETE", r"/api/batches/" + _ID, "h_batch_delete", "/api/batches/" + _SAMPLE_ID),
    ("POST", r"/api/batches/" + _ID + r"/cancel", "h_batch_cancel", "/api/batches/" + _SAMPLE_ID + "/cancel"),
    ("POST", r"/api/batches/" + _ID + r"/resume", "h_batch_resume", "/api/batches/" + _SAMPLE_ID + "/resume"),
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
        self.batch_queue = []      # batch forks BF2: IDs of waiting batches, guarded by BATCH_LOCK
        self.batch_thread = None   # the batch-submitter thread while it runs (BF24, BF25)

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


TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{16,}")


def choose_token(environ=None):
    """The server token. MOVIE_UI_TOKEN, when set to a URL-safe secret (>=16 chars of
    [A-Za-z0-9_-]), is reused so the UI URL is stable/bookmarkable across restarts; a set-
    but-invalid value is reported and ignored. Otherwise a fresh random per-launch token
    (the secure default). Returns (token, note) where note is a warning string or None."""
    env = (environ if environ is not None else os.environ).get("MOVIE_UI_TOKEN")
    if env is not None and env.strip():
        env = env.strip()
        if re.fullmatch(TOKEN_RE, env):
            return env, None
        return (secrets.token_urlsafe(32),
                "ignoring MOVIE_UI_TOKEN: must be >=16 URL-safe chars ([A-Za-z0-9_-])")
    return secrets.token_urlsafe(32), None


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
        if self.command in ("POST", "PUT", "PATCH") or (self.command == "DELETE" and
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
            try:
                self.send_json(e.status, e.body)
            except ValueError:
                self.send_json(e.status, {"error": e.body["error"].encode("utf-8", "replace").decode("utf-8")})
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
    token, token_note = choose_token()
    if token_note:
        sys.stderr.write("movie-ui: %s\n" % token_note)
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
    batch_recovery(state)
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
    if errors or fields["action"] == "smoke":
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
        if fields["action"] == "smoke":
            lib.write_smoke_manifest(state, job_id)
            argv = lib.build_smoke_argv(fields, real, state, job_id)
            return lib.create_job(state, job_id, "smoke", real, None, None, argv, fields)["id"]
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
        _batch_job_cancelled(self.server, job_id)
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


def _lora_action(real, args, timeout=None):
    limit = lib.LIGHT_TIMEOUT if timeout is None else timeout
    run = lib.run_light(lib.tool_argv(real, "lora-catalog", *args), real, timeout=limit)
    if run["timed_out"]:
        raise ApiError(504, "lora-catalog timed out after %d s" % limit, run=run)
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
    no_arch_check = body.get("no_arch_check", False)
    if not isinstance(no_arch_check, bool):
        raise ApiError(400, "no_arch_check must be true or false")
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
    if no_arch_check:
        args.append("--no-arch-check")
    return 200, {"run": _lora_action(real, args, timeout=lib.VERIFY_TIMEOUT)}


def _h_lora_remove(self, groups, query, body):
    real = self.ws(body.get("ws"))
    entry_id = _typed(body, "id", "str", "a string")
    _check_arg("id", entry_id)
    return 200, {"run": _lora_action(real, ["remove", entry_id])}


VERIFY_LINE_RE = re.compile(r"^(OK|FAIL|WARN) (\S+?)(?:: (.*))?$")


def parse_verify(stdout):
    """[{"id", "ok", "problems"}] from lora-catalog verify's OK/FAIL lines, in first-seen order;
    an entry named by a WARN line also gets "warnings", which never changes "ok" (location
    library spec L4.5)."""
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
        elif m.group(1) == "WARN":
            entry.setdefault("warnings", []).append(m.group(3) or "")
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
    run = _lora_action(real, ["verify"] + ids, timeout=lib.VERIFY_TIMEOUT)
    return 200, {"run": run, "results": parse_verify(run["stdout"])}


def _h_models(self, groups, query, body):
    self.ws(query.get("ws"))
    return 200, lib.list_models()


REPO_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")


def _h_model_download(self, groups, query, body):
    """Queue a background job that fetches a HF repo into a cache hub (MU63b)."""
    real = self.ws(body.get("ws"))
    repo = body.get("repo")
    if not (isinstance(repo, str) and re.fullmatch(REPO_ID_RE, repo)):
        raise ApiError(400, "repo must be a Hugging Face id of the form org/name")
    hub = body.get("hub") or "ltx"
    if hub not in lib.DOWNLOAD_HUBS:
        raise ApiError(400, "hub must be one of %s" % ", ".join(lib.DOWNLOAD_HUBS))
    state = self.server.state
    with STORE_LOCK:
        job_id = lib.new_job_id(state)
        argv = lib.build_download_argv(repo, hub, real)
        fields = lib.compose_fields({})
        fields["repo"], fields["hub"] = repo, hub
        lib.create_job(state, job_id, "download", real, None, None, argv, fields)
    return 201, {"job": job_summary(self.server, job_id, lib.read_queue(state))}


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
    if seed_n is not None and not (isinstance(seed_n, int) and not isinstance(seed_n, bool) and 0 <= seed_n <= 2147483647):
        errors.append("seed must be an integer from 0 to 2147483647")
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
    seed = body.get("seed")
    if seed is not None and not (isinstance(seed, int) and not isinstance(seed, bool) and 0 <= seed <= 2147483647):
        raise ApiError(400, "invalid fields", errors=["seed must be an integer from 0 to 2147483647"])
    return create_character_job(self.server, "character-regenerate", real,
                                {"ws": real, "name": groups[0], "seed": seed})


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
MovieUIHandler.h_model_download = _h_model_download
MovieUIHandler.h_characters = _h_characters
MovieUIHandler.h_character = _h_character
MovieUIHandler.h_character_create = _h_character_create
MovieUIHandler.h_character_regenerate = _h_character_regenerate
MovieUIHandler.h_character_train = _h_character_train


# ---------------------------------------------------------------------------
# Locations: the location library (bin/location; location library spec L4.1, L4.2)
# ---------------------------------------------------------------------------

LOCATION_ROW_RE = re.compile(r"^(\S+)\s+(\S+)\s+(dataset|untrained|trained)\s+(text|photos)\s+"
                             r"(yes|no)\s+(yes|no)\s+(.+)$")
LOCATION_MIN_WORDS, LOCATION_MAX_WORDS, LOCATION_MAX_PHOTOS = 15, 40, 24


def parse_location_list(stdout):
    """The rows of bin/location list (spec L4.2)."""
    out = []
    for line in stdout.splitlines():
        if line.startswith("NAME ") or line.startswith("no locations in ") or not line.strip():
            continue
        m = INVALID_ROW_RE.match(line)
        if m:
            out.append({"name": m.group(1), "invalid": m.group(2)})
            continue
        m = LOCATION_ROW_RE.match(line)
        if m:
            out.append({"name": m.group(1), "trigger": m.group(2), "status": m.group(3),
                        "source": m.group(4), "video": m.group(5) == "yes",
                        "stills": m.group(6) == "yes", "description": m.group(7),
                        "invalid": None})
    return out


def location_description_errors(description):
    """The errors of one description string (spec L4.2); [] when it may be passed on."""
    if not isinstance(description, str):
        return ["description must be a string"]
    if not lib._argv_safe(description):
        return ["description contains invalid characters"]
    if description.strip().startswith("-"):
        return ["description must not start with '-'"]
    if "\n" in description or "\r" in description:
        return ["description must be one line"]
    if not LOCATION_MIN_WORDS <= len(description.split()) <= LOCATION_MAX_WORDS:
        return ["description must be 15 to 40 words"]
    return []


def _seed_errors(seed):
    if seed is not None and not (isinstance(seed, int) and not isinstance(seed, bool)
                                 and 0 <= seed <= 2147483647):
        return ["seed must be an integer from 0 to 2147483647"]
    return []


def location_create_errors(body, state):
    """The field rules of POST /api/locations, in order (spec L4.2); [] when they pass."""
    errors = []
    name, photos, description = body.get("name"), body.get("photo_uploads"), body.get("description")
    if not (isinstance(name, str) and lib.LOCATION_NAME_RE.fullmatch(name)):
        errors.append("location name must match [a-z][a-z0-9-]{1,23}")
    if photos is None:
        photos = []
    if not (isinstance(photos, list) and all(isinstance(p, str) for p in photos)):
        errors.append("photo_uploads must be a list of upload IDs")
        photos = []
    elif len(photos) > LOCATION_MAX_PHOTOS:
        errors.append("give at most 24 photos")
    else:
        for upload in photos:
            if not (lib.UPLOAD_ID_RE.fullmatch(upload)
                    and os.path.isfile(os.path.join(state, "uploads", upload))):
                errors.append("photo upload %s not found" % _fs_text(upload))
    if description not in (None, ""):
        errors += location_description_errors(description)
    if not photos and description in (None, ""):
        errors.append("give a description or at least one photo")
    trigger = body.get("trigger")
    if trigger not in (None, "") and not (isinstance(trigger, str)
                                          and re.fullmatch(r"[a-z][a-z0-9]{3,15}", trigger)):
        errors.append("trigger must match [a-z][a-z0-9]{3,15}")
    errors += _seed_errors(body.get("seed"))
    if not isinstance(body.get("force", False), bool):
        errors.append("force must be true or false")
    return errors


def create_location_job(server, kind, real, fields):
    with STORE_LOCK:
        job_id = lib.new_job_id(server.state)
        argv = lib.location_argv(kind, fields, real, server.state)
        lib.create_job(server.state, job_id, kind, real, None, fields["name"], argv, fields)
    return 201, {"job": job_summary(server, job_id, lib.read_queue(server.state))}


def _h_locations(self, groups, query, body):
    real = self.ws(query.get("ws"))
    run = tool_result("location", lib.run_light(lib.tool_argv(real, "location", "list"), real))
    return 200, {"locations": parse_location_list(run["stdout"])}


def _h_location(self, groups, query, body):
    real, name = self.ws(query.get("ws")), groups[0]
    run = tool_result("location", lib.run_light(lib.tool_argv(real, "location", "show", name), real))
    try:
        data, end = json.JSONDecoder().raw_decode(run["stdout"].lstrip())
    except ValueError:
        raise ApiError(502, "location printed unparsable output", run=run)
    rest = run["stdout"].lstrip()[end:]
    files = [{"status": m.group(1), "path": m.group(2)}
             for m in (FILE_LINE_RE.match(line) for line in rest.splitlines()) if m]
    loc_dir = next((os.path.dirname(f["path"]) for f in files
                    if f["path"].endswith("/location.json")), None)
    manifest, stills, sheet = None, [], None
    tests = {"video_lora": None, "video_control": None}
    if loc_dir is not None:
        try:
            with open(os.path.join(loc_dir, "manifest.json"), encoding="utf-8") as f:
                items = json.load(f).get("items")
            manifest = items if isinstance(items, list) else None
        except (OSError, ValueError, AttributeError):
            manifest = None
        for item in manifest or []:
            n = item.get("n") if isinstance(item, dict) else None
            if isinstance(n, int) and not isinstance(n, bool):
                path = os.path.join(loc_dir, "stills", "loc_%02d.png" % n)
                if os.path.isfile(path):
                    stills.append(path)
        path = os.path.join(loc_dir, "contact_sheet.jpg")
        sheet = path if os.path.isfile(path) else None
        for key, filename in (("video_lora", "video_lora.mp4"), ("video_control", "video_control.mp4")):
            path = os.path.join(loc_dir, "tests", filename)
            tests[key] = path if os.path.isfile(path) else None
    job = newest_job(self.server, ("location-create",), real, "character", name)
    return 200, {"location": data, "files": files, "manifest": manifest, "contact_sheet": sheet,
                 "stills": stills, "tests": tests,
                 "last_create_fields": job["fields"] if job is not None else None}


def _h_location_create(self, groups, query, body):
    real = self.ws(body.get("ws"))
    errors = location_create_errors(body, self.server.state)
    if errors:
        raise ApiError(400, "invalid fields", errors=errors)
    fields = {"ws": real, "name": body["name"], "photo_uploads": list(body.get("photo_uploads") or []),
              "description": body.get("description") or None, "trigger": body.get("trigger") or None,
              "seed": body.get("seed"), "force": body.get("force", False)}
    return create_location_job(self.server, "location-create", real, fields)


def _h_location_patch(self, groups, query, body):
    real = self.ws(body.get("ws"))
    errors = location_description_errors(body.get("description"))
    if errors:
        raise ApiError(400, "invalid fields", errors=errors)
    run = lib.run_light(lib.tool_argv(real, "location", "edit", groups[0], "--description",
                                      body["description"]), real)
    if run["timed_out"]:
        raise ApiError(504, "location timed out after %d s" % lib.LIGHT_TIMEOUT, run=run)
    if run["exit_code"] == 0:
        return 200, {"run": run}
    if run["exit_code"] == 2:
        message = lib.last_line(run["stderr"])
        raise ApiError(400, message[len("Error: "):] if message.startswith("Error: ") else message,
                       run=run)
    raise ApiError(502, "location exited %s" % run["exit_code"], run=run)


def _h_location_regenerate(self, groups, query, body):
    real = self.ws(body.get("ws"))
    seed, new_seed = body.get("seed"), body.get("new_seed", False)
    description, force = body.get("description"), body.get("force", False)
    errors = []
    if seed is not None and new_seed is True:
        errors.append("give seed or new_seed, not both")
    errors += _seed_errors(seed)
    if description not in (None, ""):
        errors += location_description_errors(description)
    for key, value in (("new_seed", new_seed), ("force", force)):
        if not isinstance(value, bool):
            errors.append("%s must be true or false" % key)
    if errors:
        raise ApiError(400, "invalid fields", errors=errors)
    return create_location_job(self.server, "location-regenerate", real,
                               {"ws": real, "name": groups[0], "seed": seed, "new_seed": new_seed,
                                "description": description or None, "force": force})


def _h_location_train(self, groups, query, body):
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
    return create_location_job(self.server, "location-train", real, fields)


MovieUIHandler.h_locations = _h_locations
MovieUIHandler.h_location = _h_location
MovieUIHandler.h_location_create = _h_location_create
MovieUIHandler.h_location_patch = _h_location_patch
MovieUIHandler.h_location_regenerate = _h_location_regenerate
MovieUIHandler.h_location_train = _h_location_train


# ---------------------------------------------------------------------------
# Actions: identity-agnostic motion LoRAs (bin/action)
# ---------------------------------------------------------------------------

ACTION_ROW_RE = re.compile(r"^(\S+)\s+(dataset|untrained|trained)\s+(\S+)\s+(.+)$")
ACTION_INVALID_RE = re.compile(r"^(\S+)\s+INVALID: (.*)$")
ACTION_TRIGGER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _'-]{0,39}")   # action_lib.TRIGGER_RE
ACTION_CLIP_EXTS = (".mp4", ".mov", ".m4v", ".webm", ".mkv")
ACTION_MAX_CLIPS = 64


def parse_action_list(stdout):
    """Rows of bin/action list."""
    out = []
    for line in stdout.splitlines():
        if line.startswith("name ") or line.startswith("(no actions)") or not line.strip():
            continue
        m = ACTION_INVALID_RE.match(line)
        if m:
            out.append({"name": m.group(1), "invalid": m.group(2)})
            continue
        m = ACTION_ROW_RE.match(line)
        if m:
            clips = m.group(3)
            out.append({"name": m.group(1), "status": m.group(2),
                        "clips": int(clips) if clips.isdigit() else None,
                        "trigger": m.group(4).strip(), "invalid": None})
    return out


def _h_actions(self, groups, query, body):
    real = self.ws(query.get("ws"))
    run = tool_result("action", lib.run_light(lib.tool_argv(real, "action", "list"), real))
    return 200, {"actions": parse_action_list(run["stdout"])}


def _h_action(self, groups, query, body):
    real, name = self.ws(query.get("ws")), groups[0]
    run = tool_result("action", lib.run_light(lib.tool_argv(real, "action", "show", name), real))
    try:
        data = json.loads(run["stdout"])
    except ValueError:
        raise ApiError(502, "action printed unparsable output", run=run)
    dataset = data.get("dataset") if isinstance(data, dict) else None
    sheet = dataset.get("contact_sheet") if isinstance(dataset, dict) else None
    clips = []
    if isinstance(sheet, str):
        clips_dir = os.path.join(os.path.dirname(sheet), "clips")
        try:
            clips = sorted(os.path.join(clips_dir, n) for n in os.listdir(clips_dir) if n.endswith(".mp4"))
        except OSError:
            clips = []
    job = newest_job(self.server, ("action-create",), real, "character", name)
    return 200, {"action": data, "contact_sheet": sheet if isinstance(sheet, str) else None, "clips": clips,
                 "last_create_fields": job["fields"] if job is not None else None}


def action_create_errors(body):
    """The field rules for POST /api/actions; [] when they pass."""
    errors = []
    name, trigger, descriptor = body.get("name"), body.get("trigger"), body.get("descriptor")
    clips, performers = body.get("clips"), body.get("performers")
    if not (isinstance(name, str) and lib.ACTION_NAME_RE.fullmatch(name)):
        errors.append("action name must match [a-z][a-z0-9-]{1,31}")
    if not (isinstance(trigger, str) and ACTION_TRIGGER_RE.fullmatch(trigger.strip())):
        errors.append("trigger must be a Motion: phrase of 1-40 letters, digits, spaces, _ ' or -")
    if not (isinstance(descriptor, str) and 8 <= len(descriptor.split()) <= 60):
        errors.append("descriptor must be 8 to 60 words")
    elif not lib._argv_safe(descriptor) or descriptor.strip().startswith("-") or "\n" in descriptor:
        errors.append("descriptor contains invalid characters")
    if not (isinstance(clips, list) and 1 <= len(clips) <= ACTION_MAX_CLIPS):
        errors.append("give 1 to %d clip paths" % ACTION_MAX_CLIPS)
    else:
        for path in clips:
            if not (isinstance(path, str) and os.path.isabs(path) and lib._argv_safe(path)):
                errors.append("clip %s must be an absolute path" % (_fs_text(path) if isinstance(path, str) else path,))
            elif not path.lower().endswith(ACTION_CLIP_EXTS):
                errors.append("clip %s is not a video (%s)" % (_fs_text(path), ", ".join(ACTION_CLIP_EXTS)))
            elif not os.path.isfile(path):
                errors.append("clip %s not found" % _fs_text(path))
    if not (isinstance(performers, int) and not isinstance(performers, bool) and 0 <= performers <= 1000):
        errors.append("performers must be an integer >= 0")
    for key in ("force", "regenerate"):
        if not isinstance(body.get(key, False), bool):
            errors.append("%s must be true or false" % key)
    return errors


def create_action_job(server, kind, real, fields):
    with STORE_LOCK:
        job_id = lib.new_job_id(server.state)
        argv = lib.action_argv(kind, fields, real)
        lib.create_job(server.state, job_id, kind, real, None, fields["name"], argv, fields)
    return 201, {"job": job_summary(server, job_id, lib.read_queue(server.state))}


def _h_action_create(self, groups, query, body):
    real = self.ws(body.get("ws"))
    errors = action_create_errors(body)
    if errors:
        raise ApiError(400, "invalid fields", errors=errors)
    fields = {"ws": real, "name": body["name"], "trigger": " ".join(body["trigger"].split()),
              "descriptor": " ".join(body["descriptor"].split()), "clips": list(body["clips"]),
              "performers": body["performers"], "force": body.get("force", False),
              "regenerate": body.get("regenerate", False)}
    return create_action_job(self.server, "action-create", real, fields)


def _h_action_train(self, groups, query, body):
    real = self.ws(body.get("ws"))
    return create_action_job(self.server, "action-train", real, {"ws": real, "name": groups[0]})


MovieUIHandler.h_actions = _h_actions
MovieUIHandler.h_action = _h_action
MovieUIHandler.h_action_create = _h_action_create
MovieUIHandler.h_action_train = _h_action_train


# ---------------------------------------------------------------------------
# Stories, story.md edits and /files (MU54, MU69, MU70)
# ---------------------------------------------------------------------------

PANEL_STILL_RE = re.compile(r"^panel_\d{2}\.png$")
PANEL_CLIP_RE = re.compile(r"^panel_\d{2}\.mp4$")


def _inside(path, base):
    """True when path's realpath lies strictly inside base's realpath (compared with a trailing separator)."""
    try:
        return os.path.realpath(path).startswith(os.path.realpath(base) + os.sep)
    except ValueError:
        return False


def _matching(directory, regex, base=None):
    try:
        paths = sorted(os.path.join(directory, n) for n in os.listdir(directory) if regex.fullmatch(n))
    except OSError:
        return []
    return [p for p in paths if base is None or _inside(p, base)]


def _json_in(base, path):
    """The parsed JSON at path, or None when it is outside base, unreadable, not UTF-8 or not strict JSON."""
    if not _inside(path, base):
        return None
    try:
        with open(path, "rb") as f:
            return json.loads(f.read().decode("utf-8"), parse_constant=_bad_constant)
    except (OSError, ValueError, RecursionError):
        return None


def _isfile_in(base, path):
    return _inside(path, base) and os.path.isfile(path)


def _checks_summary(checks):
    if not (isinstance(checks, dict) and isinstance(checks.get("hard"), list)
            and isinstance(checks.get("advisory"), list)):
        return None
    return {"source": checks.get("source"), "hard": len(checks["hard"]), "advisory": len(checks["advisory"]),
            "verdict": checks.get("verdict")}


def _h_stories(self, groups, query, body):
    real = self.ws(query.get("ws"))
    root = os.path.join(real, "generated", "stories")
    try:
        names = os.listdir(root)
    except OSError:
        names = []
    stories = []
    for name in names:
        sdir = os.path.join(root, name)
        if not (lib.valid_story_id(name) and name != lib.SMOKE_STORY_ID and os.path.isdir(sdir)
                and _inside(sdir, root)):
            continue
        try:
            mtime = os.stat(sdir).st_mtime
        except OSError:
            continue
        stories.append((mtime, {
            "id": name, "story_md": _isfile_in(sdir, os.path.join(sdir, "story.md")),
            "checks": _checks_summary(_json_in(sdir, os.path.join(sdir, "story_checks.json"))),
            "stills": len(_matching(os.path.join(sdir, "images"), PANEL_STILL_RE, sdir)),
            "clips": len(_matching(os.path.join(sdir, "clips"), PANEL_CLIP_RE, sdir)),
            "movie": _isfile_in(sdir, os.path.join(sdir, "movie.mp4")),
            "mtime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(mtime))}))
    stories.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    return 200, {"stories_dir": _fs_text(root), "stories": [s for _m, s in stories]}


def _story_dir(self, groups, value):
    real = self.ws(value)
    story_id = self.story_id(groups[0])
    sdir = lib.story_dir(real, story_id)
    root = os.path.join(real, "generated", "stories")
    if not (_inside(sdir, root) and os.path.isdir(sdir)):
        raise ApiError(404, "no story %s in %s" % (story_id, _fs_text(os.path.dirname(sdir))))
    return real, story_id, sdir


def _read_bytes(path, base):
    if not _inside(path, base):
        return None
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _h_story(self, groups, query, body):
    real, story_id, sdir = _story_dir(self, groups, query.get("ws"))
    raw = _read_bytes(os.path.join(sdir, "story.md"), sdir)
    plan = _json_in(sdir, os.path.join(sdir, "plan.json"))
    plan = plan if isinstance(plan, dict) else {}
    runs = os.path.join(sdir, "runs")
    try:
        run_names = sorted((n for n in os.listdir(runs)
                            if _isfile_in(sdir, os.path.join(runs, n, "story_summary.json"))), reverse=True)
    except OSError:
        run_names = []
    movie = os.path.join(sdir, "movie.mp4")
    try:
        files = sorted(_fs_text(n) for n in os.listdir(sdir))
    except OSError:
        files = []
    job = newest_job(self.server, ("story", "movie"), real, "story_id", story_id)
    return 200, {"id": story_id, "dir": _fs_text(sdir), "files": files,
                 "story_md": None if raw is None else {"text": raw.decode("utf-8", "replace"),
                                                       "sha256": hashlib.sha256(raw).hexdigest()},
                 "checks": _json_in(sdir, os.path.join(sdir, "story_checks.json")),
                 "plan_loras": plan.get("loras"), "plan_mode": plan.get("mode"),
                 "catalog_loras": _json_in(sdir, os.path.join(sdir, "catalog_loras.json")),
                 "stills": [_fs_text(p) for p in _matching(os.path.join(sdir, "images"), PANEL_STILL_RE, sdir)],
                 "clips": [_fs_text(p) for p in _matching(os.path.join(sdir, "clips"), PANEL_CLIP_RE, sdir)],
                 "movie": _fs_text(movie) if _isfile_in(sdir, movie) else None,
                 "summary": _json_in(sdir, os.path.join(runs, run_names[0], "story_summary.json")) if run_names else None,
                 "last_fields": job["fields"] if job is not None else None}


def _h_story_save(self, groups, query, body):
    real, story_id, sdir = _story_dir(self, groups, body.get("ws"))
    text, base = body.get("text"), body.get("base_sha256")
    if not isinstance(text, str):
        raise ApiError(400, "text must be a string")
    if base is not None and not (isinstance(base, str) and re.fullmatch(r"[0-9a-f]{64}", base)):
        raise ApiError(400, "base_sha256 must be 64 hex digits or null")
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError:
        raise ApiError(400, "text must be encodable as UTF-8")
    path = os.path.join(sdir, "story.md")
    if os.path.lexists(path) and not _inside(path, sdir):
        raise ApiError(404, "not found")
    with STORE_LOCK:
        for job_id in lib.active_job_ids(self.server.state):
            job = self.server.job(job_id)
            if job is not None and job["workspace"] == real and job["story_id"] == story_id:
                raise ApiError(409, "story %s is in use by job %s" % (story_id, job_id))
        raw = _read_bytes(path, sdir)
        if raw is None and os.path.lexists(path):
            raise ApiError(409, "story.md exists but cannot be read; fix its permissions and reload", sha256=None)
        current = None if raw is None else hashlib.sha256(raw).hexdigest()
        if current != base:
            raise ApiError(409, "story.md changed since it was loaded; reload it", sha256=current)
        backup = None
        if raw is not None:
            stem = "%s.bak-%s" % (path, time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
            backup, n = stem, 1
            while os.path.lexists(backup):
                n += 1
                backup = "%s-%d" % (stem, n)
            lib.write_bytes_atomic(backup, raw)
        lib.write_bytes_atomic(path, data)
    return 200, {"sha256": hashlib.sha256(data).hexdigest(), "backup": backup}


def _range_num(digits):
    """A Range number: leading zeros stripped, more than 18 digits counts as 10**18."""
    digits = digits.lstrip("0") or "0"
    return 10 ** 18 if len(digits) > 18 else int(digits)


def _h_files(self, groups, query, body):
    path = query.get("path")
    real_ws = self.ws(query.get("ws"))
    if not (isinstance(path, str) and os.path.isabs(path)):
        raise ApiError(400, "path must be an absolute path")
    if "\x00" in path:
        raise ApiError(404, "not found")
    try:
        real = os.path.realpath(path)
    except ValueError:
        raise ApiError(404, "not found")
    roots = (os.path.realpath(os.path.join(real_ws, "generated")),
             os.path.realpath(os.path.join(self.server.state, "uploads")))
    if not any(real.startswith(root + os.sep) for root in roots):
        raise ApiError(403, "path not allowed")
    if not os.path.isfile(real):
        raise ApiError(404, "not found")
    try:
        f = open(real, "rb")
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EPERM):
            raise ApiError(403, "path not allowed")
        raise ApiError(404, "not found")
    try:
        try:
            size = os.fstat(f.fileno()).st_size
        except OSError:
            raise ApiError(404, "not found")
        ctype = FILE_TYPES.get(os.path.splitext(real)[1].lower(), "application/octet-stream")
        start, end, status = 0, size - 1, 200
        m = RANGE_RE.match(self.headers.get("Range") or "")
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = _range_num(m.group(1))
                end = min(_range_num(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start, end = max(size - _range_num(m.group(2)), 0), size - 1
                if _range_num(m.group(2)) == 0:
                    start = size
            if start > end or start >= size:
                self.send_response(416)
                for key, value in (("Content-Range", "bytes */%d" % size), ("Content-Length", "0"),
                                   ("Accept-Ranges", "bytes"), ("X-Content-Type-Options", "nosniff"),
                                   ("Cache-Control", "no-store")):
                    self.send_header(key, value)
                self.end_headers()
                return None
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        for key, value in (("Accept-Ranges", "bytes"), ("X-Content-Type-Options", "nosniff"),
                           ("Cache-Control", "no-store")):
            self.send_header(key, value)
        self.end_headers()
        try:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(FILE_CHUNK, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)
        except OSError:
            pass
    finally:
        f.close()
    return None


MovieUIHandler.h_stories = _h_stories
MovieUIHandler.h_story = _h_story
MovieUIHandler.h_story_save = _h_story_save
MovieUIHandler.h_files = _h_files


# ---------------------------------------------------------------------------
# Batch forks: records, eligibility, planning and the preview
# (docs/superpowers/specs/2026-10-30-batch-forks-design.md, Sections 3.1-3.6)
# ---------------------------------------------------------------------------

def batch_path(state, batch_id):
    return os.path.join(state, "batches", batch_id, "batch.json")


def read_batch(state, batch_id):
    """batch.json of one batch as a dict, or None (spec 3.1)."""
    rec = lib.read_json(batch_path(state, batch_id))
    return rec if isinstance(rec, dict) else None


def list_batch_ids(state):
    """Sorted IDs of every batches/<id> directory whose name matches JOB_ID_RE and that has a
    readable batch.json."""
    try:
        names = os.listdir(os.path.join(state, "batches"))
    except OSError:
        return []
    return sorted(n for n in names if lib.JOB_ID_RE.fullmatch(n) and read_batch(state, n) is not None)


def next_batch_number(server, ws_real):
    """BF14 over this STATE's batch records and the workspace's story directory names."""
    records = [read_batch(server.state, i) for i in list_batch_ids(server.state)]
    try:
        names = os.listdir(os.path.join(ws_real, "generated", "stories"))
    except OSError:
        names = []
    return batch.next_number(records, names, ws_real)


def _story_listed(ws_real, story_id):
    """True for a story directory _h_stories lists (spec 3.4: the same directories)."""
    root = os.path.join(ws_real, "generated", "stories")
    sdir = os.path.join(root, story_id)
    return (lib.valid_story_id(story_id) and story_id != lib.SMOKE_STORY_ID and os.path.isdir(sdir)
            and _inside(sdir, root))


def _story_names(ws_real):
    try:
        names = os.listdir(os.path.join(ws_real, "generated", "stories"))
    except OSError:
        names = []
    return sorted(n for n in names if _story_listed(ws_real, n))


def job_index(server, ws_real):
    """Spec 3.4's one pass over the jobs, newest first: ({story_id: last_fields}, {story_id:
    busy job ID}). last_fields is the dict fields of the newest story or movie job of ws_real;
    the busy job is the newest job of ws_real that is queued, starting or running."""
    state = server.state
    queue = lib.read_queue(state)
    last, busy = {}, {}
    for job_id in sorted(lib.list_job_ids(state), reverse=True):
        job = server.job(job_id)
        if job is None or job.get("workspace") != ws_real:
            continue
        story_id = job.get("story_id")
        if job.get("kind") in ("story", "movie") and isinstance(job.get("fields"), dict) \
                and story_id not in last:
            last[story_id] = job["fields"]
        if story_id not in busy and lib.job_state(state, job_id, queue) in ("queued", "starting", "running"):
            busy[story_id] = job_id
    return last, busy


def stored_fields(server, ws_real, story_id):
    """BF41b: (code, fields, batch_id, number) of a story with no last_fields, from its fork.json
    and that fork's batch record. A fork.json that is not a regular file is ignored (isfile
    and not islink is the lstat S_ISREG rule of copy_plan)."""
    path = os.path.join(lib.story_dir(ws_real, story_id), "fork.json")
    fork_rec = lib.read_json(path, None) if os.path.isfile(path) and not os.path.islink(path) else None
    batch_rec = None
    if isinstance(fork_rec, dict) and isinstance(fork_rec.get("batch"), str) \
            and lib.JOB_ID_RE.fullmatch(fork_rec["batch"]):
        record = batch_path(server.state, fork_rec["batch"])
        if os.path.isfile(record):
            batch_rec = lib.read_json(record, {})
    return batch.fork_fallback(fork_rec, batch_rec, story_id, ws_real)


def originals_info(server, ws_real, story_ids):
    """{story_id: {"dir", "has_story", "busy_job", "fields", "code", "batch", "number"}}: what
    batch.plan_cells needs of each original. code is "job" when last_fields exists, else the
    BF41 code; fields is last_fields, else the BF41 "ok" fields, else None."""
    last, busy = job_index(server, ws_real)
    out = {}
    for story_id in story_ids:
        sdir = lib.story_dir(ws_real, story_id)
        info = {"dir": _story_listed(ws_real, story_id),
                "has_story": os.path.isfile(os.path.join(sdir, "story.md")),
                "busy_job": busy.get(story_id), "fields": None, "code": "job", "batch": None, "number": None}
        if story_id in last:
            info["fields"] = last[story_id]
        else:
            code, fields, batch_id, number = stored_fields(server, ws_real, story_id)
            info.update(code=code, fields=fields, batch=batch_id, number=number)
        out[story_id] = info
    return out


def _fields_source(info):
    """("job" or "batch" or None, fields_batch) of spec 3.4."""
    source = {"job": "job", "ok": "batch"}.get(info["code"])
    return source, ({"id": info["batch"], "number": info["number"]} if source == "batch" else None)


def story_status(server, ws_real):
    """GET /api/batches/stories rows (spec 3.4) for the story directories _h_stories lists."""
    names = _story_names(ws_real)
    infos = originals_info(server, ws_real, names)
    rows = []
    for story_id in names:
        info = infos[story_id]
        reason = batch.eligibility_reason(info["busy_job"], info["code"], info["batch"])
        source, source_batch = _fields_source(info)
        rows.append({"id": story_id, "eligible": reason is None, "reason": reason,
                     "busy_job": info["busy_job"], "fields_source": source, "fields_batch": source_batch})
    return rows


def plan_batch(server, clean, number):
    """BF23: (cells, originals) of clean ({"ws", "stories", "variants"}) planned as batch number;
    the one planning function behind preview, submit and each cell's turn."""
    ws_real, state = clean["ws"], server.state
    originals = originals_info(server, ws_real, clean["stories"])
    cells = batch.plan_cells(clean["stories"], clean["variants"], number, ws_real, state, originals,
                             lambda fields: lib.validate_fields(fields, ws_real, state),
                             lambda fork: os.path.lexists(lib.story_dir(ws_real, fork)))
    return cells, originals


PREVIEW_CELL_KEYS = ("story_id", "variant", "fork_id", "status", "reason", "level", "diff", "warnings")


def preview_cell(cell):
    return dict((key, cell[key]) for key in PREVIEW_CELL_KEYS)


def _movie_path(ws_real, story_id):
    path = os.path.join(lib.story_dir(ws_real, story_id), "movie.mp4")
    return path if os.path.isfile(path) else None


def preview_row(ws_real, story_id, info):
    source, source_batch = _fields_source(info)
    fields = info["fields"]
    return {"story_id": story_id,
            "fields": batch.original_fields(fields, story_id, ws_real) if fields is not None else None,
            "fields_source": source, "fields_batch": source_batch, "movie": _movie_path(ws_real, story_id)}


def _batch_request(body):
    """The clean request of a preview or submit body; 400 for a bad ws, then 400 invalid batch."""
    real = resolve_ws(body.get("ws"))
    clean, errors = batch.validate_request(body)
    if errors:
        raise ApiError(400, "invalid batch", errors=errors)
    clean["ws"] = real
    return clean


def _h_batch_stories(self, groups, query, body):
    return 200, {"stories": story_status(self.server, self.ws(query.get("ws")))}


def _h_batch_preview(self, groups, query, body):
    server = self.server
    clean = _batch_request(body)
    number = next_batch_number(server, clean["ws"])
    cells, originals = plan_batch(server, clean, number)
    return 200, {"number": number,
                 "rows": [preview_row(clean["ws"], s, originals[s]) for s in clean["stories"]],
                 "cells": [preview_cell(c) for c in cells], "totals": batch.totals(cells)}


MovieUIHandler.h_batch_stories = _h_batch_stories
MovieUIHandler.h_batch_preview = _h_batch_preview


# ---------------------------------------------------------------------------
# Batch forks: submit, the batch submitter, reconcile and the batch page
# (docs/superpowers/specs/2026-10-30-batch-forks-design.md, Sections 3.1, 4.1-4.5)
# ---------------------------------------------------------------------------

GIB = float(1024 ** 3)


def write_batch(state, rec):
    lib.write_json_atomic(batch_path(state, rec["id"]), rec)


def new_batch_id(state):
    """A fresh batch ID in the job-ID format, drawn again while batches/<id> exists (spec 3.1)."""
    while True:
        batch_id = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(2)
        if not os.path.lexists(os.path.join(state, "batches", batch_id)):
            return batch_id


def make_batch_record(clean, batch_id, number, cells):
    """The batch.json of a submit (spec 3.1, BF24): "ok" cells are pending, the others refused,
    and order is the BF27 submit order."""
    now = lib.utc_now()
    rcells = [{"story_id": c["story_id"], "variant": c["variant"], "fork_id": c["fork_id"],
               "status": "pending" if c["status"] == "ok" else "refused", "reason": c["reason"],
               "level": c["level"], "diff": c["diff"], "warnings": c["warnings"], "fields": None,
               "job_id": None, "copy_bytes": 0, "updated": now} for c in cells]
    return {"schema": batch.BATCH_SCHEMA, "id": batch_id, "number": number, "workspace": clean["ws"],
            "created": now, "status": "waiting", "cancel_requested": False,
            "stories": list(clean["stories"]), "variants": clean["variants"],
            "order": batch.submit_order(rcells, clean["stories"]), "cells": rcells}


def remove_fork(fdir, batch_id):
    """BF19: shutil.rmtree(fdir) only when <fdir>/fork.json names batch_id and fdir's own name;
    otherwise leave it and say so on stderr. Returns True when removed."""
    rec = lib.read_json(os.path.join(fdir, "fork.json"), None)
    if isinstance(rec, dict) and rec.get("batch") == batch_id and rec.get("fork_id") == os.path.basename(fdir):
        shutil.rmtree(fdir)
        return True
    sys.stderr.write("movie-ui: batch %s: not removing %s (no matching fork.json)\n" % (batch_id, fdir))
    return False


def fork_in_use(state, ws_real, fork_id, own_job=None):
    """The ID of a job other than own_job whose workspace is ws_real and whose story is fork_id
    (newest first), or None. Read from each job.json; takes no lock."""
    for job_id in sorted(lib.list_job_ids(state), reverse=True):
        if job_id == own_job:
            continue
        job = lib.read_job(lib.job_dir(state, job_id)) or {}
        if job.get("workspace") == ws_real and job.get("story_id") == fork_id:
            return job_id
    return None


def remove_unused_fork(state, ws_real, fdir, batch_id, own_job=None):
    """remove_fork, except while another job of ws_real names this fork's story: then the folder
    is kept and stderr says which job uses it. Returns True when removed."""
    user = fork_in_use(state, ws_real, os.path.basename(fdir), own_job)
    if user is not None:
        sys.stderr.write("movie-ui: batch %s: not removing %s (job %s uses it)\n" % (batch_id, fdir, user))
        return False
    return remove_fork(fdir, batch_id)


def _batch_kick(server):
    """BF24 step 4: start the batch submitter unless it runs. The caller holds BATCH_LOCK."""
    if server.batch_thread is None or not server.batch_thread.is_alive():
        server.batch_thread = threading.Thread(target=_batch_submitter, args=(server,),
                                               name="batch-submitter", daemon=True)
        server.batch_thread.start()


def _batch_submitter(server):
    """BF25: submit the queued batches one at a time, each cell in the batch's order."""
    state = server.state
    while True:
        with BATCH_LOCK:
            if not server.batch_queue:
                server.batch_thread = None
                return
            batch_id = server.batch_queue.pop(0)
            rec = read_batch(state, batch_id)
            if rec is None or rec.get("status") != "waiting":
                continue
            rec["status"] = "submitting"
            write_batch(state, rec)
        for index in rec["order"]:
            try:
                _submit_cell(server, batch_id, index)
            except Exception as e:  # BF26: a failed fork never stops the batch
                sys.stderr.write("movie-ui: batch %s cell %d: %s: %s\n"
                                 % (batch_id, index, type(e).__name__, e))
        with BATCH_LOCK:
            rec = read_batch(state, batch_id)
            if rec is not None:
                rec["status"] = "cancelled" if rec.get("cancel_requested") else "submitted"
                write_batch(state, rec)


def _cell_update(server, batch_id, index, changes):
    """Under BATCH_LOCK: apply changes to one cell of batch.json with a new "updated"; returns the
    record, or None when it is gone."""
    with BATCH_LOCK:
        rec = read_batch(server.state, batch_id)
        if rec is None:
            return None
        rec["cells"][index].update(changes, updated=lib.utc_now())
        write_batch(server.state, rec)
        return rec


def _submit_cell(server, batch_id, index):
    """BF28 step 1, then steps 2-9; an exception refuses the cell and removes its fork (BF26)."""
    with BATCH_LOCK:
        rec = read_batch(server.state, batch_id)
        if rec is None or rec["cells"][index].get("status") != "pending":
            return
        if rec.get("cancel_requested"):
            rec["cells"][index].update(status="cancelled", reason="batch cancelled", updated=lib.utc_now())
            write_batch(server.state, rec)
            return
        rec["cells"][index].update(status="forking", reason=None, updated=lib.utc_now())
        write_batch(server.state, rec)
    made = []
    try:
        _fork_cell(server, batch_id, index, made)
    except Exception as e:
        if made:
            remove_unused_fork(server.state, os.path.dirname(os.path.dirname(os.path.dirname(made[0]))),
                               made[0], batch_id)
        sys.stderr.write("movie-ui: batch %s: cell %d: internal error: %s: %s\n"
                         % (batch_id, index, type(e).__name__, e))
        _cell_update(server, batch_id, index,
                     {"status": "refused", "reason": "internal error: %s: %s" % (type(e).__name__, e)})


def _fork_cell(server, batch_id, index, made):
    """BF28 steps 2-9 for one forking cell. made holds the fork directory while an exception
    should remove it."""
    state = server.state
    rec = read_batch(state, batch_id)
    if rec is None:
        return
    ws_real = rec["workspace"]
    clean = {"ws": ws_real, "stories": rec["stories"], "variants": rec["variants"]}
    built = plan_batch(server, clean, rec["number"])[0][index]                       # 2
    if built["status"] != "ok":
        _cell_update(server, batch_id, index, {"status": "refused", "reason": built["reason"]})
        return
    story_id, fid, level = built["story_id"], built["fork_id"], built["level"]
    sdir, fdir = lib.story_dir(ws_real, story_id), lib.story_dir(ws_real, fid)
    plan = batch.copy_plan(sdir, level)                                               # 3
    copy_bytes = sum(n for _rel, n in plan)
    free = shutil.disk_usage(os.path.join(ws_real, "generated", "stories")).free
    if free - copy_bytes < batch.MIN_FREE_BYTES:
        _cell_update(server, batch_id, index, {"status": "refused", "copy_bytes": copy_bytes, "reason":
                     "not enough free space: %.1f GiB free, this fork copies %.1f GiB and at least 20 GiB "
                     "must stay free" % (free / GIB, copy_bytes / GIB)})
        return
    try:                                                                              # 4
        os.mkdir(fdir)
    except FileExistsError:
        _cell_update(server, batch_id, index, {"status": "refused", "copy_bytes": copy_bytes,
                                               "reason": "fork ID %s already exists; it is never overwritten" % fid})
        return
    except OSError as e:
        _cell_update(server, batch_id, index, {"status": "refused", "copy_bytes": copy_bytes, "reason":
                     "copy failed: %s: %s" % (e.strerror or e, e.filename or fdir)})
        return
    made.append(fdir)
    fork_rec = {"schema": batch.FORK_SCHEMA, "fork_id": fid, "source_story": story_id, "batch": batch_id,
                "variant": built["variant"], "label": rec["variants"][built["variant"] - 1]["label"],
                "level": level, "diff": built["diff"], "created": lib.utc_now()}
    try:
        lib.write_json_atomic(os.path.join(fdir, "fork.json"), fork_rec)
        for rel, _n in plan:
            target = os.path.join(fdir, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            src = os.path.join(sdir, rel)
            if os.path.islink(src) or os.path.islink(os.path.dirname(src)):  # re-check copy_plan's lstat
                raise OSError(errno.ELOOP, "a symlink, not copied", src)
            shutil.copy2(src, target)
    except OSError as e:
        if os.path.lexists(os.path.join(fdir, "fork.json")):
            remove_unused_fork(state, ws_real, fdir, batch_id)
        else:
            os.rmdir(fdir)
        del made[:]
        _cell_update(server, batch_id, index, {"status": "refused", "copy_bytes": copy_bytes, "reason":
                     "copy failed: %s: %s" % (e.strerror or e, e.filename or fdir)})
        return
    busy = job_index(server, ws_real)[1].get(story_id)                                # 5
    if busy is not None:
        remove_unused_fork(state, ws_real, fdir, batch_id)
        del made[:]
        _cell_update(server, batch_id, index, {"status": "refused", "copy_bytes": copy_bytes, "reason":
                     "story %s got a job (%s) while it was being forked; fork it again later" % (story_id, busy)})
        return
    checks = lib.run_checks(built["fields"], ws_real, state)                          # 6, no lock held
    if not lib.checks_pass(checks):
        remove_unused_fork(state, ws_real, fdir, batch_id)
        del made[:]
        _cell_update(server, batch_id, index, {"status": "refused", "copy_bytes": copy_bytes, "reason": "\n".join(
            "%s %s: %s" % (c["id"], c["name"], c["detail"]) for c in checks if c["status"] == "fail")})
        return
    with BATCH_LOCK:                                                                  # 7
        rec = read_batch(state, batch_id)
        if rec is None or rec.get("cancel_requested"):
            remove_unused_fork(state, ws_real, fdir, batch_id)
            del made[:]
            if rec is not None:
                rec["cells"][index].update(status="cancelled", reason="batch cancelled", copy_bytes=copy_bytes,
                                           updated=lib.utc_now())
                write_batch(state, rec)
            return
    job_id = create_compose_job(server, built["fields"])                              # 8
    del made[:]
    with BATCH_LOCK:                                                                  # 9
        rec = read_batch(state, batch_id)
        if rec is not None:
            rec["cells"][index].update(status="queued", reason=None, job_id=job_id, fields=built["fields"],
                                       level=level, diff=built["diff"], warnings=built["warnings"],
                                       copy_bytes=copy_bytes, updated=lib.utc_now())
            write_batch(state, rec)
        late = rec is None or bool(rec.get("cancel_requested"))
    if late:
        with STORE_LOCK:
            result = lib.cancel_job(state, job_id)
        if rec is not None:
            reconcile(server, batch_id)
        elif result == "cancelled":
            remove_unused_fork(state, ws_real, fdir, batch_id, own_job=job_id)


def reconcile(server, batch_id):
    """BF29 under BATCH_LOCK: every queued cell whose job was cancelled before it started loses its
    fork directory and becomes cancelled. Returns the record, or None when it is gone."""
    state = server.state
    with BATCH_LOCK:
        rec = read_batch(state, batch_id)
        if rec is None:
            return None
        changed = False
        for cell in rec["cells"]:
            job_id = cell.get("job_id")
            if cell.get("status") != "queued" or not (isinstance(job_id, str) and lib.JOB_ID_RE.fullmatch(job_id)):
                continue
            status = lib.read_status(lib.job_dir(state, job_id)) or {}
            if status.get("state") == "cancelled" and status.get("started") is None:
                remove_unused_fork(state, rec["workspace"], lib.story_dir(rec["workspace"], cell["fork_id"]),
                                   batch_id, own_job=job_id)
                cell.update(status="cancelled", reason="cancelled before it started", updated=lib.utc_now())
                changed = True
        if changed:
            write_batch(state, rec)
        return rec


def batch_view(server, rec):
    """The "view" of GET /api/batches/<id> (BF35): the originals' movies and, parallel to
    rec["cells"], each cell's display state, job summary, movie and whether its directory exists."""
    state, ws_real = server.state, rec["workspace"]
    queue = lib.read_queue(state)
    cells = []
    for cell in rec["cells"]:
        shown, job = cell["status"], None
        job_id = cell.get("job_id")
        if shown == "queued" and isinstance(job_id, str) and lib.JOB_ID_RE.fullmatch(job_id):
            if os.path.isdir(lib.job_dir(state, job_id)):
                job = job_summary(server, job_id, queue)
            shown = job["state"] if job is not None else "job deleted"
        cells.append({"state": shown, "job": job, "movie": _movie_path(ws_real, cell["fork_id"]),
                      "dir": os.path.isdir(lib.story_dir(ws_real, cell["fork_id"]))})
    return {"originals": dict((s, _movie_path(ws_real, s)) for s in rec["stories"]), "cells": cells}


def _known_batch(server, batch_id):
    """Reconcile batch_id (BF29) and return its record, or ApiError(404)."""
    rec = reconcile(server, batch_id)
    if rec is None:
        raise ApiError(404, "unknown batch %s" % batch_id)
    return rec


def _h_batches(self, groups, query, body):
    server = self.server
    real = self.ws(query.get("ws"))
    queue = lib.read_queue(server.state)
    out = []
    for batch_id in sorted(list_batch_ids(server.state), reverse=True):
        rec = read_batch(server.state, batch_id)
        if rec is None or rec.get("workspace") != real:
            continue
        rec = reconcile(server, batch_id) or rec
        done = sum(1 for c in rec["cells"] if isinstance(c.get("job_id"), str)
                   and lib.JOB_ID_RE.fullmatch(c["job_id"])
                   and lib.job_state(server.state, c["job_id"], queue) == "done")
        out.append({"id": rec["id"], "number": rec["number"], "created": rec["created"],
                    "status": rec["status"], "cells": len(rec["cells"]), "done": done})
    return 200, {"batches": out}


def _h_batch_create(self, groups, query, body):
    server = self.server
    state = server.state
    clean = _batch_request(body)
    with BATCH_LOCK:
        batch_id = new_batch_id(state)
        number = next_batch_number(server, clean["ws"])
        cells, _originals = plan_batch(server, clean, number)
        if not any(c["status"] == "ok" for c in cells):
            raise ApiError(409, "every cell was refused", cells=[preview_cell(c) for c in cells])
        rec = make_batch_record(clean, batch_id, number, cells)
        lib.make_dir(os.path.dirname(batch_path(state, batch_id)))
        write_batch(state, rec)
        server.batch_queue.append(batch_id)
        _batch_kick(server)
    pending = sum(1 for c in rec["cells"] if c["status"] == "pending")
    return 201, {"batch": {"id": batch_id, "number": number, "status": "waiting"}, "pending": pending,
                 "refused": len(rec["cells"]) - pending}


def _h_batch(self, groups, query, body):
    rec = _known_batch(self.server, groups[0])
    return 200, {"batch": rec, "view": batch_view(self.server, rec)}


MovieUIHandler.h_batches = _h_batches
MovieUIHandler.h_batch_create = _h_batch_create
MovieUIHandler.h_batch = _h_batch


# ---------------------------------------------------------------------------
# Batch forks: cancel, restart, submit remaining and delete
# (docs/superpowers/specs/2026-10-30-batch-forks-design.md, Section 4.4)
# ---------------------------------------------------------------------------

ACTIVE_JOB_STATES = ("queued", "starting", "running")


def _batch_job_cancelled(server, job_id):
    """BF30: reconcile the batch whose cells hold job_id, if there is one."""
    for batch_id in list_batch_ids(server.state):
        rec = read_batch(server.state, batch_id)
        if rec is not None and any(c.get("job_id") == job_id for c in rec.get("cells", [])):
            reconcile(server, batch_id)
            return


def batch_recovery(state):
    """BF32 at startup, before the server serves. A batch is recovered when it is waiting or
    submitting, or when any cell is still forking or pending (a restart soon after Cancel batch;
    review fix). A forking cell whose fork has a movie job created at or after the batch becomes
    queued with that job (and its fields); any other forking cell loses its fork. Without
    cancel_requested, those cells and every pending cell become interrupted and so does the batch;
    with it, they become cancelled ("batch cancelled"), adopted jobs are cancelled, and the batch
    is cancelled. One stderr line per recovered batch; a record that cannot be recovered is
    skipped with one stderr line and never stops the server starting."""
    for batch_id in list_batch_ids(state):
        try:
            _recover_batch(state, batch_id)
        except Exception as e:
            sys.stderr.write("movie-ui: batch %s: recovery skipped: %s: %s\n" % (batch_id, type(e).__name__, e))


def _recover_batch(state, batch_id):
    """batch_recovery for one record."""
    rec = read_batch(state, batch_id)
    if rec is None:
        return
    open_cells = any(c.get("status") in ("forking", "pending") for c in rec["cells"])
    if rec.get("status") not in ("waiting", "submitting") and not open_cells:
        return
    cancelled = bool(rec.get("cancel_requested"))
    jobs = {}
    for job_id in lib.list_job_ids(state):
        job = lib.read_job(lib.job_dir(state, job_id)) or {}
        if (job.get("kind") == "movie" and job.get("workspace") == rec["workspace"]
                and isinstance(job.get("created"), str) and job["created"] >= rec["created"]):
            jobs[job.get("story_id")] = (job_id, job)
    now = lib.utc_now()
    adopted = []
    for cell in rec["cells"]:
        if cell.get("status") == "forking" and cell["fork_id"] in jobs:
            job_id, job = jobs[cell["fork_id"]]
            cell.update(status="queued", reason=None, job_id=job_id, fields=job.get("fields"), updated=now)
            adopted.append(job_id)
        elif cell.get("status") == "forking":
            remove_unused_fork(state, rec["workspace"], lib.story_dir(rec["workspace"], cell["fork_id"]),
                               batch_id)
            if cancelled:
                cell.update(status="cancelled", reason="batch cancelled", updated=now)
            else:
                cell.update(status="interrupted", reason="the server stopped while this fork was being made",
                            updated=now)
        elif cell.get("status") == "pending":
            if cancelled:
                cell.update(status="cancelled", reason="batch cancelled", updated=now)
            else:
                cell.update(status="interrupted", reason="the server stopped before this fork was made",
                            updated=now)
    rec["status"] = "cancelled" if cancelled else "interrupted"
    write_batch(state, rec)
    if cancelled:
        for job_id in adopted:
            with STORE_LOCK:
                lib.cancel_job(state, job_id)
        sys.stderr.write("movie-ui: batch %s: cancelled (finished at restart)\n" % batch_id)
    else:
        sys.stderr.write("movie-ui: batch %s: interrupted (%d cell(s) to submit again)\n"
                         % (batch_id, sum(1 for c in rec["cells"] if c.get("status") == "interrupted")))


def _h_batch_cancel(self, groups, query, body):
    """BF31: stop the batch's pending cells, cancel its forks' jobs, reconcile, mark it cancelled."""
    server, batch_id = self.server, groups[0]
    state = server.state
    _known_batch(server, batch_id)
    with BATCH_LOCK:
        rec = read_batch(state, batch_id)
        if rec is None:
            raise ApiError(404, "unknown batch %s" % batch_id)
        queue = lib.read_queue(state)
        jobs = [c["job_id"] for c in rec["cells"] if c.get("status") == "queued"
                and isinstance(c.get("job_id"), str) and lib.JOB_ID_RE.fullmatch(c["job_id"])]
        if not (any(c.get("status") in ("pending", "forking") for c in rec["cells"])
                or any(lib.job_state(state, j, queue) in ACTIVE_JOB_STATES for j in jobs)):
            raise ApiError(409, "batch %s has nothing to cancel" % batch_id)
        if batch_id in server.batch_queue:
            server.batch_queue.remove(batch_id)
        rec["cancel_requested"] = True
        for cell in rec["cells"]:
            if cell.get("status") == "pending":
                cell.update(status="cancelled", reason="batch cancelled", updated=lib.utc_now())
        write_batch(state, rec)
    cancelled, cancelling = [], []
    for job_id in jobs:
        with STORE_LOCK:
            result = lib.cancel_job(state, job_id)
        if result == "cancelled":
            cancelled.append(job_id)
        elif result == "cancelling":
            cancelling.append(job_id)
    reconcile(server, batch_id)
    with BATCH_LOCK:
        rec = read_batch(state, batch_id)
        if rec is not None:
            rec["status"] = "cancelled"
            write_batch(state, rec)
    return 200, {"status": "cancelled", "cancelled": cancelled, "cancelling": cancelling}


def _h_batch_resume(self, groups, query, body):
    """BF33: an interrupted batch's interrupted cells go back to pending and the batch is queued."""
    server, batch_id = self.server, groups[0]
    _known_batch(server, batch_id)
    with BATCH_LOCK:
        rec = read_batch(server.state, batch_id)
        if rec is None:
            raise ApiError(404, "unknown batch %s" % batch_id)
        if rec.get("status") != "interrupted":
            raise ApiError(409, "batch %s was not interrupted" % batch_id)
        for cell in rec["cells"]:
            if cell.get("status") == "interrupted":
                cell.update(status="pending", reason=None, updated=lib.utc_now())
        rec["status"] = "waiting"
        write_batch(server.state, rec)
        server.batch_queue.append(batch_id)
        _batch_kick(server)
    return 200, {"status": "waiting", "pending": sum(1 for c in rec["cells"] if c["status"] == "pending")}


def _h_batch_delete(self, groups, query, body):
    """BF34: remove the batch record (never its forks or their jobs) unless it is still submitting."""
    server, batch_id = self.server, groups[0]
    _known_batch(server, batch_id)
    with BATCH_LOCK:
        rec = read_batch(server.state, batch_id)
        if rec is None:
            raise ApiError(404, "unknown batch %s" % batch_id)
        if rec.get("status") in ("waiting", "submitting"):
            raise ApiError(409, "batch %s is still submitting; cancel it first" % batch_id)
        try:
            shutil.rmtree(os.path.dirname(batch_path(server.state, batch_id)))
        except OSError as e:
            raise ApiError(500, "cannot delete batch %s: %s" % (batch_id, e.strerror or e))
    return 200, {"deleted": batch_id}


MovieUIHandler.h_batch_cancel = _h_batch_cancel
MovieUIHandler.h_batch_resume = _h_batch_resume
MovieUIHandler.h_batch_delete = _h_batch_delete


# ---------------------------------------------------------------------------
# Traces (MU20, MU71-MU74)
# ---------------------------------------------------------------------------

def trace_agents(ui_ws):
    """MU71: one entry per agent on disk, with its loopback daemon URL from the registry."""
    out = []
    for agent in fleet_lib.agent_ids_on_disk():
        a = fleet_lib.deploy_root(agent)
        current = os.path.join(a, "current")
        fleets = (os.path.join(current, fleet_lib.WS_SUBDIR, "fleets") if os.path.exists(current)
                  else os.path.join(ui_ws, "fleets"))
        port, files = fleet_lib.agent_port(fleets, agent)
        entry = {"id": agent, "port": port, "port_source": "registry", "url": None, "error": None}
        if not files:
            entry["port"], entry["port_source"] = fleet_lib.DEFAULT_PORT, "default"
        elif port is None:
            entry["port_source"] = None
            entry["error"] = "agent '%s' has different ports in %s in %s" % (agent, ", ".join(files), fleets)
        if entry["port"] is not None:
            entry["url"] = "http://127.0.0.1:%d" % entry["port"]
        out.append(entry)
    return out


def trace_error_text(message):
    """D9: fleet_lib's "daemon not reachable at" is shown as qwen-agentd status words it."""
    prefix = "daemon not reachable at "
    return "daemon: not reachable at " + message[len(prefix):] if message.startswith(prefix) else message


def _strict_loads(raw):
    """The strictly parsed JSON in raw (bytes), or None when it is not valid strict JSON."""
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=_bad_constant)
    except (ValueError, RecursionError):
        return None


def _strict(result, error, url):
    """(result, None) or (None, message): fleet_lib's result, refused when it holds NaN or Infinity."""
    if error is None:
        try:
            json.dumps(result, allow_nan=False)
        except ValueError:
            return None, "the daemon at %s returned an unrecognized trace response" % url
        return result, None
    return None, trace_error_text(error)


def trace_skew(result):
    """span_id of every record whose parent is present and starts after it (MU73)."""
    starts = dict((r["span_id"], r["start"]) for r in result["records"])
    return [r["span_id"] for r in result["records"]
            if r["parent_span_id"] in starts and r["start"] < starts[r["parent_span_id"]]]


def trace_view(agent, result, with_text):
    view = {"agent": agent, "result": result, "skew": trace_skew(result)}
    if with_text:
        view["text"] = "\n".join(fleet_lib.render_trace(result)) + "\n"
    return view


def _h_trace_agents(self, groups, query, body):
    return 200, {"default": default_agent(), "agents": trace_agents(self.server.ui_ws)}


def _h_traces_recent(self, groups, query, body):
    n_text = query.get("n", str(fleet_lib.TRACE_RECENT_DEFAULT))
    if not (N_RE.fullmatch(n_text) and 1 <= int(n_text) <= fleet_lib.TRACE_RECENT_MAX):
        raise ApiError(400, "n must be 1 to 100")
    n = int(n_text)
    agents = trace_agents(self.server.ui_ws)
    wanted = query.get("agent", "all")
    if wanted != "all":
        agents = [a for a in agents if a["id"] == wanted]
        if not agents:
            raise ApiError(404, "unknown agent")
    best, seen, errors = {}, {}, []
    for agent in agents:
        if agent["url"] is None:
            errors.append({"agent": agent["id"], "error": agent["error"]})
            continue
        result, error = _strict(*fleet_lib.fetch_recent(agent["url"], n), agent["url"])
        if error is not None:
            errors.append({"agent": agent["id"], "error": error})
            continue
        for item in result["traces"]:
            tid = item["trace_id"]
            seen.setdefault(tid, set()).add(agent["id"])
            old = best.get(tid)
            if old is None or (item["start"], agent["id"]) < (old[0]["start"], old[1]):
                best[tid] = (item, agent["id"])
    traces = []
    for tid, (item, _agent) in best.items():
        entry = dict(item)
        entry["seen_on"] = sorted(seen[tid])
        entry["agents"] = sorted(set(seen[tid]) | set(h.rpartition("@")[2] for h in item["delegated"]))
        traces.append(entry)
    traces.sort(key=lambda t: (-t["start"], t["trace_id"]))
    return 200, {"traces": traces[:n], "errors": errors}


def _agent_url(self, query):
    agents = dict((a["id"], a) for a in trace_agents(self.server.ui_ws))
    agent = query.get("agent") or default_agent()
    if not isinstance(agent, str) or agent not in agents:
        raise ApiError(404, "unknown agent")
    if agents[agent]["url"] is None:
        raise ApiError(502, agents[agent]["error"])
    return agent, agents[agent]["url"]


def _fetch(self, groups, query):
    agent, url = _agent_url(self, query)
    result, error = _strict(*fleet_lib.fetch_trace(url, groups[0]), url)
    if error is not None:
        raise ApiError(502, error)
    return agent, result


def _h_trace(self, groups, query, body):
    agent, result = _fetch(self, groups, query)
    return 200, trace_view(agent, result, query.get("format") == "text")


def _saved_path(server, trace_id):
    if not fleet_lib.valid_trace_id(trace_id):
        raise ApiError(404, "no saved trace %s" % trace_id)
    return os.path.join(server.state, "traces", trace_id + ".json")


def _h_trace_save(self, groups, query, body):
    agent, result = _fetch(self, groups, {"agent": body.get("agent")})
    path = _saved_path(self.server, groups[0])
    lib.write_json_atomic(path, {"schema": lib.SAVED_TRACE_SCHEMA, "trace_id": groups[0], "agent": agent,
                                 "saved_at": lib.utc_now(), "result": result})
    return 200, {"saved": groups[0], "path": path}


def load_saved(path, trace_id):
    """(envelope, valid) for one saved trace file; envelope is None when it does not parse strictly."""
    try:
        with open(path, "rb") as f:
            raw = f.read(SAVED_TRACE_MAX + 1)
    except OSError:
        return None, False
    obj = _strict_loads(raw) if len(raw) <= SAVED_TRACE_MAX else None
    if not isinstance(obj, dict):
        return None, False
    valid = (obj.get("schema") == lib.SAVED_TRACE_SCHEMA and obj.get("trace_id") == trace_id
             and fleet_lib.valid_trace_result(obj.get("result"), trace_id))
    return obj, valid


def _h_traces_saved(self, groups, query, body):
    root = os.path.join(self.server.state, "traces")
    try:
        names = sorted(os.listdir(root))
    except OSError:
        names = []
    out = []
    for name in names:
        trace_id = name[:-5]
        if not (name.endswith(".json") and fleet_lib.valid_trace_id(trace_id)):
            continue
        obj, valid = load_saved(os.path.join(root, name), trace_id)
        records = obj["result"]["records"] if valid else []
        agent = (obj or {}).get("agent") if valid else None
        saved_at = (obj or {}).get("saved_at") if valid else None
        out.append({"trace_id": trace_id, "agent": agent if isinstance(agent, str) else None,
                    "saved_at": saved_at if isinstance(saved_at, str) else None, "spans": len(records),
                    "start": min(r["start"] for r in records) if records else None, "invalid": not valid})
    out.sort(key=lambda s: s["trace_id"], reverse=True)
    out.sort(key=lambda s: s["saved_at"] or "", reverse=True)
    out.sort(key=lambda s: s["saved_at"] is None)
    return 200, {"saved": out}


def _h_trace_saved(self, groups, query, body):
    path = _saved_path(self.server, groups[0])
    if not os.path.isfile(path):
        raise ApiError(404, "no saved trace %s" % groups[0])
    obj, valid = load_saved(path, groups[0])
    if not valid:
        raise ApiError(422, "saved trace is invalid")
    return 200, trace_view(obj.get("agent"), obj["result"], True)


def _h_trace_saved_delete(self, groups, query, body):
    path = _saved_path(self.server, groups[0])
    try:
        os.unlink(path)
    except FileNotFoundError:
        raise ApiError(404, "no saved trace %s" % groups[0])
    return 200, {"deleted": groups[0]}


MovieUIHandler.h_trace_agents = _h_trace_agents
MovieUIHandler.h_traces_recent = _h_traces_recent
MovieUIHandler.h_trace = _h_trace
MovieUIHandler.h_trace_save = _h_trace_save
MovieUIHandler.h_traces_saved = _h_traces_saved
MovieUIHandler.h_trace_saved = _h_trace_saved
MovieUIHandler.h_trace_saved_delete = _h_trace_saved_delete
