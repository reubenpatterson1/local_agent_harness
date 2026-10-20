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
    real = os.path.realpath(value)
    if not (os.path.isdir(real) and os.path.isfile(os.path.join(real, "bin", "ltx-movie"))):
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
            sys.stderr.write("movie-ui: %s %s -> %d\n" % (self.command, self.path.partition("?")[0], status))

    # -- responses --------------------------------------------------------------------------

    def _write(self, data):
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_json(self, status, obj, headers=()):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
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
        if self.command in ("POST", "PUT"):
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
        except ApiError as e:
            self.send_json(e.status, e.body)
            return
        except Exception as e:
            self._logged_500 = True
            sys.stderr.write("movie-ui: %s %s -> 500 (%s: %s)\n" % (self.command, path, type(e).__name__, e))
            self.send_json(500, {"error": "internal error"})
            return
        if result is not None:
            self.send_json(result[0], result[1])

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
            obj = json.loads(self.rfile.read(n).decode("utf-8"))
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
