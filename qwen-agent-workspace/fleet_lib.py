"""fleet_lib -- pure, importable logic for the qwen-agent fleet.

Registry, trust (fleet.env and join strings), signing, liveness, routing and the
self-update decisions all live here so that they can be unit tested without a
daemon. bin/qwen-agentd holds the CLI, threads, sockets and subprocesses;
bin/qwen-agent loads this file lazily and only for routing.
See docs/superpowers/specs/2026-10-16-fleet-discovery-self-update-design.md.

Standard library only. Nothing here opens a socket or starts a process at import
time; fetch_view and delegate_once open a connection only when called. Valid on
Python 3.9 and 3.13: no `X | Y` annotations, no `match`, no 3.10+ APIs.
"""

import base64
import copy
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import re
import secrets
import threading
import time

PROTOCOL = 1
DEFAULT_PORT = 8190
BEACON_INTERVAL = 30          # s, scaled by --timing-scale
POLL_INTERVAL = 60            # s, scaled
LIVE_WINDOW = 90              # s, scaled
REPROBE_INTERVAL = 60         # s, scaled
PEER_REFRESH_INTERVAL = 60    # s, scaled
HOUSEKEEPING_INTERVAL = 5     # s, scaled
UPDATE_INTERVAL = 900         # s, scaled
UPDATE_JITTER = 120           # s, scaled; uniform in [0, UPDATE_JITTER]
SKEW_WINDOW = 60              # s, never scaled
NONCE_RETENTION = 2 * SKEW_WINDOW + 2  # s, never scaled; > acceptance window (F29 replay)
STARTUP_HEALTH_DEADLINE = 120 # s, never scaled
PEER_HTTP_TIMEOUT = 5         # s, /health and /skills calls to peers
MODEL_PROBE_TIMEOUT = 5       # s
RUN_TIMEOUT = 900             # s, equals bin/qwen-agent SKILL_SUBPROCESS_TIMEOUT
FORWARD_TIMEOUT = 930         # s, RUN_TIMEOUT + 30: /delegate -> peer /run
GATE_TIMEOUT = 300            # s, the staged release's selftest
GIT_TIMEOUT = 120             # s, any single git subprocess
MAX_BODY = 1048576            # bytes, request body cap
MAX_IMAGE_BODY = 25165824     # bytes (24 MiB), request body cap for POST /run and POST /delegate only
MAX_IMAGES = 4                # images per request
MAX_IMAGE_BYTES = 16777216    # bytes (16 MiB), decoded total of all images in one request
LARGE_BODY_SLOTS = 2          # concurrent POST /run bodies over MAX_BODY a daemon reads (V13)
MAX_START_ATTEMPTS = 3
KEEP_RELEASES = 3
FLEET_TAG_CHARS = 16
KNOWN_SKILLS = ("investigator", "analyst", "planner", "researcher", "vision")
VISION_SKILL = "vision"
IMAGE_MAGIC = (("image/png", b"\x89PNG\r\n\x1a\n"), ("image/jpeg", b"\xff\xd8\xff"))
IMAGE_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg"}
FLEET_ENV_KEYS = ("QWEN_AGENT_FLEET_ID", "QWEN_AGENT_FLEET_TOKEN")
FLEET_ENV_PREFIX = "QWEN_AGENT_FLEET_"   # every env key with this prefix is stripped (F54a, F86)
TAG_RE = re.compile(r"^v([0-9]{4})\.([0-9]{2})\.([0-9]{2})(?:\.([1-9][0-9]*))?$")
HOST_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
FLEET_ID_RE = re.compile(r"^[0-9a-f]{16}$")
TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
JOIN_PREFIX = "qaf1"
LOOPBACK_CLIENTS = ("127.0.0.1", "::1")   # client addresses allowed on loopback-only endpoints (F42)
LOCAL = "@local"              # route_candidates' marker for "run on this host" (F59); cannot match HOST_ID_RE
PEERS_SCHEMA = "qwen-agentd.peers.v1"
ONESHOT_SCHEMA = "qwen-agent.oneshot.v1"   # equals bin/qwen-agent ONESHOT_SCHEMA
DEFAULT_DAEMON_URL = "http://127.0.0.1:8190"
DAEMON_URL_RE = re.compile(r"^http://127\.0\.0\.1:([0-9]{1,5})$")
VIEW_TIMEOUT = 2              # s, bin/qwen-agent GET /peers; never scaled
DELEGATE_CLIENT_TIMEOUT = 960 # s, bin/qwen-agent POST /delegate = FORWARD_TIMEOUT + 30; never scaled
ORIGIN_URL = "https://github.com/reubenpatterson1/local_agent_harness.git"
WS_SUBDIR = "qwen-agent-workspace"          # the workspace directory inside a release worktree
LAUNCHD_LABEL = "com.qwen-agent.qwen-agentd"   # the base of launchd_label(<id>) (multi-agent spec M6)
AGENTS_DIR = "~/agents"                     # A(<id>) = ~/agents/<id>, expanded at every use (multi-agent spec M2)
LOGS_SUBDIR = "logs"                        # A(<id>)/logs (multi-agent spec M5)
FLEET_ENV_NAME = "fleet.env"                # A(<id>)/fleet.env (multi-agent spec M4)
SYSTEMD_UNIT_FMT = "qwen-agentd-%s.service" # systemd_unit(<id>) (multi-agent spec M6)
BIN_DIR = "~/.local/bin"                    # where the agent commands live (multi-agent spec M8)
COMMAND_NAME = "qwen-agent"                 # ~/.local/bin/qwen-agent and qwen-agent-<id> (multi-agent spec M8)
MIN_PORT = 1024                             # lowest registry port (multi-agent spec M7)
BROADCAST_ADDR = "255.255.255.255"          # the default beacon target address (multi-agent spec M16)
WRAPPER_MARKER = "# qwen-agentd wrapper"    # the line that marks a generated command (multi-agent spec M9)
WRAPPER_ID_PREFIX = "# agent-id: "          # the wrapper line that names its agent (multi-agent spec M9)
WRAPPER_MAX_BYTES = 65536                   # a larger file is never a wrapper (multi-agent spec M10)
SUPERVISOR_RESTART_DELAY = 10 # s, launchd ThrottleInterval and systemd RestartSec
LOG_MAX_BYTES = 5242880       # 5 MB
LOG_BACKUPS = 3
RUN_TMP_SUBDIR = "tmp"        # A(<id>)/tmp holds one private directory per image run (V17)
RUN_TMP_PREFIX = "images-"    # prefix of each run's directory; stale ones are removed at startup (V19)
# --- tracing (docs/superpowers/specs/2026-10-17-fleet-tracing-design.md) ---
TRACE_FILE_NAME = "trace.jsonl"     # A(<id>)/logs/trace.jsonl, rotated LOG_MAX_BYTES x LOG_BACKUPS (TR10)
TRACE_SCHEMA = "qwen-agentd.trace.v1"     # loopback GET /trace?id= response (TR27)
RECENT_SCHEMA = "qwen-agentd.recent.v1"   # loopback GET /traces/recent response (TR28)
TRACE_RECORD_VERSION = 1
TRACE_KINDS = ("turn", "model", "tool", "delegate", "run", "agent")
TRACE_POSTED_KINDS = ("turn", "model", "tool")    # the kinds a qwen-agent may POST /spans
TRACE_ENV_ID = "QWEN_AGENT_TRACE_ID"
TRACE_ENV_PARENT = "QWEN_AGENT_PARENT_SPAN"
TRACE_SPAN_MAX_BYTES = 8192         # POST /spans body cap (TR9)
TRACE_TEXT_CHARS = 256              # longest tool key or outcome attribute
TRACE_COUNT_MAX = 10 ** 15          # largest integer attribute
TRACE_DUR_MAX_MS = 10 ** 10
TRACE_MAX_RECORDS = 2000            # records one agent returns for one trace
TRACE_QUERY_MAX_BYTES = MAX_BODY - 4096   # their encoded size; 4 KiB is left for the envelope
TRACE_POST_TIMEOUT = 2              # s, bin/qwen-agent POST /spans; never scaled
TRACE_FANOUT_DEADLINE = PEER_HTTP_TIMEOUT + 1   # s, one fan-out round to peers; never scaled
TRACE_QUERY_TIMEOUT = 20            # s, a client's GET /trace?id= (two fan-out rounds plus margin)
TRACE_RECENT_TIMEOUT = 5            # s, a client's GET /traces/recent
TRACE_RECENT_DEFAULT = 10
TRACE_RECENT_MAX = 100
TRACE_CLIENT_MAX_BYTES = 33554432   # largest /trace?id= or /traces/recent response a client reads
TRACE_ID_RE = re.compile(r"[0-9a-f]{32}")
SPAN_ID_RE = re.compile(r"[0-9a-f]{16}")
TRACE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:@+-]{0,127}")
TRACE_TOKEN_RE = re.compile(r"[a-z][a-z_]{0,31}")
_TRACE_TEXT_BAD_RE = re.compile(r"[\x00-\x1f\x7f]")

# Every regex above is applied with .fullmatch(), never .match(): "$" alone also
# matches just before a trailing newline, so "mac-local\n" would otherwise pass.


class RegistryError(ValueError):
    """The registry cannot be read, fails the F7 schema, or lacks this host (F8, F9)."""


class FleetEnvError(ValueError):
    """fleet.env or a join string is malformed (F21, F25). Never carries secret text."""


class ImageError(ValueError):
    """An images field fails validate_images or request_images (vision spec V5, V6)."""

    def __init__(self, status, reason):
        ValueError.__init__(self, reason)
        self.status = status    # 400 or 413
        self.reason = reason    # exact text sent as {"error": reason}


def _is_int(value):
    """True for a real int. bool is an int subclass and is rejected (F7 rules 2 and 8)."""
    return isinstance(value, int) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# Section 2: registry and self-identity (F5-F11, F18)
# ---------------------------------------------------------------------------

_REGISTRY_KEYS = frozenset(("protocol", "fleet_id", "hosts"))
_HOST_KEYS = frozenset(("role", "address", "port", "model_server", "model", "skills"))
_HOST_REQUIRED = _HOST_KEYS - frozenset(("port",))
_ROLES = ("orchestrator", "agent")
_SERVER_TYPES = ("ollama", "vllm")


def validate_registry(obj, expected_fleet_id):
    """Every F7 violation in obj, as "location: message" strings. [] means valid.

    Collects all failures instead of stopping at the first. Each independent
    violation produces exactly one string.
    """
    if not isinstance(obj, dict):
        return ["registry: must be a JSON object"]
    errors = []
    keys = set(obj)
    for key in sorted(_REGISTRY_KEYS - keys):
        errors.append("registry: missing key '%s'" % key)
    for key in sorted(keys - _REGISTRY_KEYS):
        errors.append("registry: unexpected key '%s'" % key)
    if "protocol" in obj and not (_is_int(obj["protocol"]) and obj["protocol"] == PROTOCOL):
        errors.append("protocol: must be the integer %d" % PROTOCOL)
    if "fleet_id" in obj:
        fleet_id = obj["fleet_id"]
        if not (isinstance(fleet_id, str) and FLEET_ID_RE.fullmatch(fleet_id)):
            errors.append("fleet_id: must be 16 lowercase hex characters")
        elif fleet_id != expected_fleet_id:
            errors.append("fleet_id: '%s' does not match this host's fleet_id '%s'"
                          % (fleet_id, expected_fleet_id))
    if "hosts" in obj:
        errors.extend(_validate_hosts(obj["hosts"]))
    return errors


def _validate_hosts(hosts):
    if not isinstance(hosts, dict) or not hosts:
        return ["hosts: must be a non-empty object"]
    errors = []
    used = {}
    for host_id in sorted(hosts):
        loc = "hosts.%s" % host_id
        if not HOST_ID_RE.fullmatch(host_id):
            errors.append("%s: host_id must match %s" % (loc, HOST_ID_RE.pattern))
        host = hosts[host_id]
        if not isinstance(host, dict):
            errors.append("%s: must be an object" % loc)
            continue
        keys = set(host)
        for key in sorted(_HOST_REQUIRED - keys):
            errors.append("%s: missing key '%s'" % (loc, key))
        for key in sorted(keys - _HOST_KEYS):
            errors.append("%s: unexpected key '%s'" % (loc, key))
        if "role" in host and host["role"] not in _ROLES:
            errors.append("%s.role: must be 'orchestrator' or 'agent'" % loc)
        address_ok = False
        if "address" in host:
            try:
                if not isinstance(host["address"], str):
                    raise ValueError("not a string")
                ipaddress.IPv4Address(host["address"])
                address_ok = True
            except ValueError:
                errors.append("%s.address: must be an IPv4 dotted quad" % loc)
        port = host.get("port", DEFAULT_PORT)
        port_ok = _is_int(port) and MIN_PORT <= port <= 65535
        if not port_ok:
            errors.append("%s.port: must be an integer in %d..65535" % (loc, MIN_PORT))
        if "model_server" in host:
            errors.extend(_validate_model_server(loc + ".model_server", host["model_server"]))
        if "model" in host and not (isinstance(host["model"], str) and host["model"] != ""):
            errors.append("%s.model: must be a non-empty string" % loc)
        if "skills" in host:
            errors.extend(_validate_skills(loc + ".skills", host["skills"]))
        if address_ok and port_ok:
            pair = (host["address"], port)
            if pair in used:
                errors.append("%s: address %s:%d is already used by hosts.%s"
                              % (loc, pair[0], pair[1], used[pair]))
            else:
                used[pair] = host_id
    return errors


def _validate_model_server(loc, server):
    if not isinstance(server, dict) or set(server) != {"type", "url"}:
        return ["%s: must be an object with exactly the keys 'type' and 'url'" % loc]
    errors = []
    if server["type"] not in _SERVER_TYPES:
        errors.append("%s.type: must be 'ollama' or 'vllm'" % loc)
    url = server["url"]
    if not (isinstance(url, str) and url.startswith("http://")):
        errors.append("%s.url: must be a string starting with http://" % loc)
    elif server["type"] == "ollama" and not url.endswith("/v1"):
        errors.append("%s.url: an ollama url must end with /v1" % loc)
    return errors


def _validate_skills(loc, skills):
    if not isinstance(skills, list):
        return ["%s: must be a list" % loc]
    errors = []
    seen = []
    for index, skill in enumerate(skills):
        if not isinstance(skill, str) or skill not in KNOWN_SKILLS:
            errors.append("%s[%d]: must be one of %s" % (loc, index, ", ".join(KNOWN_SKILLS)))
        elif skill in seen:
            errors.append("%s[%d]: duplicate skill '%s'" % (loc, index, skill))
        else:
            seen.append(skill)
    return errors


def load_registry(path, expected_fleet_id):
    """Read, validate and return the registry with `port` filled in on every host (F8)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.loads(f.read())
    except (OSError, ValueError, RecursionError) as e:
        raise RegistryError("cannot read registry %s: %s: %s" % (path, type(e).__name__, e))
    errors = validate_registry(obj, expected_fleet_id)
    if errors:
        raise RegistryError("invalid registry %s:\n  " % path + "\n  ".join(errors))
    registry = copy.deepcopy(obj)
    for host in registry["hosts"].values():
        host.setdefault("port", DEFAULT_PORT)
    return registry


def self_entry(registry, host_id):
    """This host's registry entry; host identity comes only from QWEN_AGENT_HOST_ID (F9, F10)."""
    if host_id not in registry["hosts"]:
        raise RegistryError("host_id '%s' is not in the fleet registry; valid IDs: %s"
                            % (host_id, ", ".join(sorted(registry["hosts"]))))
    return registry["hosts"][host_id]


# ---------------------------------------------------------------------------
# Section 3: trust -- fleet.env and join strings (F19-F28)
# ---------------------------------------------------------------------------

def fleet_env_path(host_id):
    """A(<id>)/fleet.env, the only place this agent's token is stored (F19, multi-agent spec M4)."""
    return os.path.join(deploy_root(host_id), FLEET_ENV_NAME)


def write_fleet_env(path, fleet_id, token):
    """Create fleet.env atomically (dir 0700, file 0600) through <path>.tmp and os.link.

    An existing path raises FileExistsError and is never replaced (F20, multi-agent spec M4).
    """
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    os.chmod(directory, 0o700)
    tmp = path + ".tmp"
    if os.path.lexists(tmp):
        os.unlink(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write("%s=%s\n%s=%s\n" % (FLEET_ENV_KEYS[0], fleet_id, FLEET_ENV_KEYS[1], token))
        f.flush()
        os.fsync(f.fileno())
    try:
        os.link(tmp, path)
    finally:
        os.unlink(tmp)


def load_fleet_env(path):
    """(fleet_id, token) from fleet.env. A missing file raises FileNotFoundError (F21)."""
    st = os.stat(path)
    if st.st_mode & 0o077:
        raise FleetEnvError("%s must be mode 0600 (chmod 600 %s)" % (path, path))
    malformed = FleetEnvError("%s is malformed" % path)
    try:
        with open(path, "r", encoding="ascii", newline="") as f:
            content = f.read()
    except UnicodeDecodeError:
        raise malformed from None
    lines = content.split("\n")
    if len(lines) != 3 or lines[2] != "":
        raise malformed
    values = []
    for line, key, value_re in zip(lines[:2], FLEET_ENV_KEYS, (FLEET_ID_RE, TOKEN_RE)):
        name, sep, value = line.partition("=")
        if name != key or sep != "=" or not value_re.fullmatch(value):
            raise malformed
        values.append(value)
    return values[0], values[1]


def _join_check(fleet_id, token):
    return hashlib.sha256((fleet_id + ":" + token).encode("ascii")).hexdigest()[:8]


def make_join_string(fleet_id, token):
    """qaf1.<fleet_id>.<token>.<8-hex check>; shown once by init-fleet, never stored (F24)."""
    return JOIN_PREFIX + "." + fleet_id + "." + token + "." + _join_check(fleet_id, token)


def parse_join_string(s):
    """(fleet_id, token) from a join string. Surrounding whitespace is ignored (F25).

    Every failure raises FleetEnvError("invalid join string"), which carries no part
    of the input.
    """
    parts = s.strip().split(".") if isinstance(s, str) else []
    if (len(parts) != 4 or parts[0] != JOIN_PREFIX
            or not FLEET_ID_RE.fullmatch(parts[1]) or not TOKEN_RE.fullmatch(parts[2])
            or parts[3] != _join_check(parts[1], parts[2])):
        raise FleetEnvError("invalid join string")
    return parts[1], parts[2]


def token_key(token):
    """The 32-byte HMAC key; the daemon keeps only this after startup (F27)."""
    return bytes.fromhex(token)


# ---------------------------------------------------------------------------
# Section 4: signing primitives (F29b-F29j)
# ---------------------------------------------------------------------------

_BEACON_KEYS = frozenset(("proto", "fleet_tag", "port", "ts", "nonce", "sig"))
_HDR_TS_RE = re.compile(r"[0-9]{1,15}")
_HDR_NONCE_RE = re.compile(r"[0-9a-f]{32}")
_HDR_SIG_RE = re.compile(r"[0-9a-f]{64}")


def fleet_tag(key):
    """The 16-hex fleet marker carried by every beacon (F29b)."""
    return hmac.new(key, b"fleet-tag", hashlib.sha256).hexdigest()[:FLEET_TAG_CHARS]


def canonical_json(obj):
    """The one JSON encoding signed and sent everywhere in the fleet (F29c)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _hmac_hex(key, data):
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def _safe_equal(a, b):
    """Constant-time compare of two str values that never raises.

    hmac.compare_digest raises TypeError on non-ASCII str; attacker-chosen text
    (a beacon field, a header) must simply fail to match instead.
    """
    try:
        return hmac.compare_digest(a.encode("ascii"), b.encode("ascii"))
    except UnicodeEncodeError:
        return False


class NonceCache(object):
    """Nonces seen within the last `retention` seconds of `clock()` (F29d)."""

    def __init__(self, retention=NONCE_RETENTION, clock=time.time):
        self.retention = retention
        self.clock = clock
        self._seen = {}
        self._lock = threading.Lock()

    def check_and_add(self, nonce):
        """False if nonce was added less than `retention` seconds ago; else record it, True."""
        with self._lock:
            now = self.clock()
            added = self._seen.get(nonce)
            if added is not None and now - added < self.retention:
                return False
            self._seen[nonce] = now
            return True

    def seen(self, nonce):
        """True if nonce was added less than `retention` seconds ago. Never records it (vision spec V8)."""
        with self._lock:
            added = self._seen.get(nonce)
            return added is not None and self.clock() - added < self.retention

    def prune(self):
        with self._lock:
            now = self.clock()
            for nonce in [n for n, added in self._seen.items() if now - added >= self.retention]:
                del self._seen[nonce]

    def __len__(self):
        with self._lock:
            return len(self._seen)


def make_beacon(key, port, now, nonce):
    """A signed beacon: no host_id, skills or version ever cross in one (F29f)."""
    beacon = {"proto": PROTOCOL, "fleet_tag": fleet_tag(key), "port": port, "ts": now, "nonce": nonce}
    beacon["sig"] = _hmac_hex(key, canonical_json(beacon))
    return canonical_json(beacon)


def verify_beacon(key, data, now, cache):
    """(status, beacon or None) with status in ok/malformed/foreign/bad_sig/skew/replay (F29g)."""
    try:
        beacon = json.loads(data)
    except (ValueError, RecursionError):
        return "malformed", None
    if not isinstance(beacon, dict) or set(beacon) != _BEACON_KEYS:
        return "malformed", None
    if not all(_is_int(beacon[k]) for k in ("proto", "port", "ts")):
        return "malformed", None
    if not all(isinstance(beacon[k], str) for k in ("fleet_tag", "nonce", "sig")):
        return "malformed", None
    if beacon["proto"] != PROTOCOL:
        return "malformed", None
    if not _safe_equal(beacon["fleet_tag"], fleet_tag(key)):
        return "foreign", None
    unsigned = dict((k, v) for k, v in beacon.items() if k != "sig")
    if not _safe_equal(beacon["sig"], _hmac_hex(key, canonical_json(unsigned))):
        return "bad_sig", None
    if abs(now - beacon["ts"]) > SKEW_WINDOW:
        return "skew", beacon
    if not cache.check_and_add(beacon["nonce"]):
        return "replay", None
    return "ok", beacon


def _sha256_hex(body):
    return hashlib.sha256(body).hexdigest()


def _request_input(method, path, ts_text, nonce, body):
    return ("qwen-agentd-req-v1\n" + method + "\n" + path + "\n" + ts_text + "\n" + nonce
            + "\n" + _sha256_hex(body)).encode("ascii")


def _response_input(status_code, method, path, request_nonce, ts_text, nonce, body):
    return ("qwen-agentd-resp-v1\n" + str(status_code) + "\n" + method + "\n" + path + "\n"
            + request_nonce + "\n" + ts_text + "\n" + nonce + "\n" + _sha256_hex(body)).encode("ascii")


def _signature_headers(headers):
    """(ts_text, nonce, sig) from X-Fleet-* headers, or None when any is missing or malformed."""
    try:
        values = tuple(headers.get(name) for name in ("X-Fleet-Ts", "X-Fleet-Nonce", "X-Fleet-Sig"))
    except Exception:
        return None
    if not all(isinstance(v, str) for v in values):
        return None
    ts_text, nonce, sig = values
    if not (_HDR_TS_RE.fullmatch(ts_text) and _HDR_NONCE_RE.fullmatch(nonce)
            and _HDR_SIG_RE.fullmatch(sig)):
        return None
    return values


def _verify_signed(key, build_input, headers, now, cache):
    parsed = _signature_headers(headers)
    if parsed is None:
        return "bad"
    ts_text, nonce, sig = parsed
    try:
        expected = _hmac_hex(key, build_input(ts_text, nonce))
    except UnicodeEncodeError:
        return "bad"
    if not hmac.compare_digest(sig, expected):
        return "bad"
    if abs(now - int(ts_text)) > SKEW_WINDOW:
        return "skew"
    if not cache.check_and_add(nonce):
        return "replay"
    return "ok"


def sign_request(key, method, path, body, now, nonce):
    """The three X-Fleet-* request headers (F29h)."""
    ts_text = str(now)
    return {"X-Fleet-Ts": ts_text, "X-Fleet-Nonce": nonce,
            "X-Fleet-Sig": _hmac_hex(key, _request_input(method, path, ts_text, nonce, body))}


def verify_request(key, method, path, headers, body, now, cache):
    """"ok", "bad", "skew" or "replay": headers, then signature, then skew, then replay (F29h)."""
    return _verify_signed(
        key, lambda ts_text, nonce: _request_input(method, path, ts_text, nonce, body),
        headers, now, cache)


def prefilter_request(headers, now, cache):
    """"ok", "bad", "skew" or "replay" from a request's X-Fleet-* headers alone (vision spec V9).

    For a POST /run body over MAX_BODY, before the body is read. The signature covers
    sha256(body), so it cannot be checked yet: this checks the headers' presence and
    format, then the timestamp skew, then that the nonce is unseen. It never records
    the nonce; verify_request does, after the body is read.
    """
    parsed = _signature_headers(headers)
    if parsed is None:
        return "bad"
    ts_text, nonce, _sig = parsed
    if abs(now - int(ts_text)) > SKEW_WINDOW:
        return "skew"
    if cache.seen(nonce):
        return "replay"
    return "ok"


def sign_response(key, status_code, method, path, request_nonce, body, now, nonce):
    """The three X-Fleet-* response headers, bound to the request's nonce (F29i)."""
    ts_text = str(now)
    return {"X-Fleet-Ts": ts_text, "X-Fleet-Nonce": nonce,
            "X-Fleet-Sig": _hmac_hex(key, _response_input(status_code, method, path, request_nonce,
                                                          ts_text, nonce, body))}


def verify_response(key, status_code, method, path, request_nonce, headers, body, now, cache):
    """Same statuses and order as verify_request (F29i)."""
    return _verify_signed(
        key, lambda ts_text, nonce: _response_input(status_code, method, path, request_nonce,
                                                    ts_text, nonce, body),
        headers, now, cache)


# ---------------------------------------------------------------------------
# Section 2.3 and 6.5: skill verification and the /run child environment
# (F13-F15, F54a)
# ---------------------------------------------------------------------------

def probe_url(model_server):
    """The model-listing URL of a registry model_server entry (F13)."""
    url = model_server["url"].rstrip("/")
    if model_server["type"] == "ollama":
        if url.endswith("/v1"):
            url = url[:-len("/v1")]
        return url + "/api/tags"
    return url + "/models"


def parse_loaded_models(server_type, body_bytes):
    """Model names from a probe_url response body; any parse error or shape gives set() (F14)."""
    try:
        data = json.loads(body_bytes)
        if server_type == "vllm":
            return {item["id"] for item in data["data"] if isinstance(item.get("id"), str)}
        if server_type == "ollama":
            names = set()
            for item in data["models"]:
                for field in ("name", "model"):
                    value = item.get(field)
                    if isinstance(value, str):
                        names.add(value)
            return names
    except Exception:
        return set()
    return set()


def verify_skills(entry, loaded):
    """[{skill, model, verified}] in registry order (F15)."""
    return [{"skill": s, "model": entry["model"], "verified": entry["model"] in loaded}
            for s in entry["skills"]]


def build_child_env(environ, daemon_url, trace=None):
    """A new env for a /run child: no fleet secrets, no SKILL_* overrides (F54a), and no
    inherited trace; trace=(trace_id, parent_span_id) sets the child's (tracing spec TR8)."""
    env = {}
    for key, value in environ.items():
        if key.startswith(FLEET_ENV_PREFIX):
            continue
        if key.startswith("SKILL_ENDPOINT_") or key.startswith("SKILL_MODEL_"):
            continue
        if key in (TRACE_ENV_ID, TRACE_ENV_PARENT):
            continue
        env[key] = value
    env["QWEN_AGENT_DAEMON_URL"] = daemon_url
    if trace is not None:
        env[TRACE_ENV_ID], env[TRACE_ENV_PARENT] = trace
    return env


# ---------------------------------------------------------------------------
# Vision: images on the wire (vision spec V4-V7)
# ---------------------------------------------------------------------------

def validate_images(images):
    """Decode a wire `images` list -> [(media_type, bytes)]; raise ImageError at the first failure.

    Checks, per item in order: shape, media_type, data, base64, magic bytes, then the
    running decoded total (vision spec V5). 0 items is valid here; request_images
    decides which skills need images.
    """
    if not isinstance(images, list):
        raise ImageError(400, "images must be a list")
    if len(images) > MAX_IMAGES:
        raise ImageError(400, "at most %d images are allowed (got %d)" % (MAX_IMAGES, len(images)))
    magic = dict(IMAGE_MAGIC)
    decoded = []
    total = 0
    for index, item in enumerate(images):
        loc = "images[%d]" % index
        if not (isinstance(item, dict) and set(item) == {"media_type", "data"}):
            raise ImageError(400, "%s must be an object with exactly the keys media_type and data" % loc)
        media_type, data = item["media_type"], item["data"]
        if not (isinstance(media_type, str) and media_type in magic):
            raise ImageError(400, "%s.media_type must be image/png or image/jpeg" % loc)
        if not (isinstance(data, str) and data != ""):
            raise ImageError(400, "%s.data must be a non-empty base64 string" % loc)
        try:
            raw = base64.b64decode(data, validate=True)
        except ValueError:
            raise ImageError(400, "%s.data is not valid base64" % loc)
        if not raw.startswith(magic[media_type]):
            raise ImageError(400, "%s does not match its media_type %s" % (loc, media_type))
        total += len(raw)
        if total > MAX_IMAGE_BYTES:
            raise ImageError(413, "images exceed %d bytes in total" % MAX_IMAGE_BYTES)
        decoded.append((media_type, raw))
    return decoded


def request_images(req):
    """Decoded images of a /delegate or /run body, or None when it has none (vision spec V6)."""
    if "images" in req:
        if req["skill"] != VISION_SKILL:
            raise ImageError(400, "images are only accepted for skill vision")
        decoded = validate_images(req["images"])
        if not decoded:
            raise ImageError(400, "skill vision requires 1 to %d images" % MAX_IMAGES)
        return decoded
    if req["skill"] == VISION_SKILL:
        raise ImageError(400, "skill vision requires 1 to %d images" % MAX_IMAGES)
    return None


_IMAGE_ROUTES = (("signed", "run"), ("loopback", "delegate"))


def body_cap(kind, name):
    """Largest request body accepted on a route: MAX_IMAGE_BODY for /run and /delegate, else MAX_BODY."""
    return MAX_IMAGE_BODY if (kind, name) in _IMAGE_ROUTES else MAX_BODY


# ---------------------------------------------------------------------------
# Section 5.3: liveness table (F34, F35)
# ---------------------------------------------------------------------------

PEER_FIELDS = ("host_id", "address", "port", "role", "version", "proto", "compatible",
               "skills", "heard_via", "age")


class LivenessTable(object):
    """Registered, bound, recently heard peers, keyed by host_id (F35)."""

    def __init__(self, registry, self_host_id, live_window, clock=time.time):
        self._registered = sorted(registry["hosts"])
        self._self = self_host_id
        self._window = live_window
        self._clock = clock
        self._lock = threading.Lock()
        self._records = {}
        self._reported = {}

    def _live(self, record, now):
        # A beacon alone cannot keep a record live: it also needs a signed refresh
        # within four windows, or it ages out and the next beacon triggers a re-bind.
        return (now - record["last_heard"] <= self._window
                and now - record["last_refresh"] <= 4 * self._window)

    def bind(self, host_id, address, port, health, skills, via):
        """Create or replace host_id's record after a successful signed /health + /skills.

        A record of another host_id at the same (address, port) is dropped: that
        daemon has been replaced, and heard() matches records by address (F34).
        """
        with self._lock:
            now = self._clock()
            for other in [h for h, r in self._records.items()
                          if h != host_id and r["address"] == address and r["port"] == port]:
                del self._records[other]
            self._records[host_id] = {
                "address": address, "port": port,
                "role": health["role"], "version": health["version"], "proto": health["proto"],
                "compatible": health["proto"] == PROTOCOL,
                "skills": copy.deepcopy(skills),
                "last_heard": now, "heard_via": via, "last_refresh": now,
            }

    def heard(self, address, port, via):
        """Refresh last_heard of the LIVE record at (address, port); its host_id, else None.

        A record that has aged out is not revived here: the caller then schedules a
        bind attempt, so a restarted peer is re-checked by signed /health (decision 5).
        """
        with self._lock:
            now = self._clock()
            for host_id, record in self._records.items():
                if record["address"] == address and record["port"] == port and self._live(record, now):
                    record["last_heard"] = now
                    record["heard_via"] = via
                    return host_id
            return None

    def refresh(self, host_id, health, skills, via):
        with self._lock:
            record = self._records.get(host_id)
            if record is None:
                return
            now = self._clock()
            record.update(role=health["role"], version=health["version"], proto=health["proto"],
                          compatible=health["proto"] == PROTOCOL, skills=copy.deepcopy(skills),
                          last_heard=now, last_refresh=now, heard_via=via)

    def record(self, host_id):
        """A copy of host_id's record (live or not), or None."""
        with self._lock:
            record = self._records.get(host_id)
            return copy.deepcopy(record) if record is not None else None

    def is_live(self, host_id):
        with self._lock:
            record = self._records.get(host_id)
            return record is not None and self._live(record, self._clock())

    def live_peers(self):
        """Live records as F55 peer dicts, last_heard descending, then host_id ascending."""
        with self._lock:
            now = self._clock()
            rows = []
            for host_id, r in self._records.items():
                if not self._live(r, now):
                    continue
                rows.append((-r["last_heard"], host_id, {
                    "host_id": host_id, "address": r["address"], "port": r["port"],
                    "role": r["role"], "version": r["version"], "proto": r["proto"],
                    "compatible": r["compatible"], "skills": copy.deepcopy(r["skills"]),
                    "heard_via": r["heard_via"], "age": round(now - r["last_heard"], 1),
                }))
            rows.sort(key=lambda row: (row[0], row[1]))
            return [row[2] for row in rows]

    def unheard_registered(self):
        with self._lock:
            now = self._clock()
            return [h for h in self._registered
                    if h != self._self
                    and not (h in self._records and self._live(self._records[h], now))]

    def due_for_refresh(self, interval):
        with self._lock:
            now = self._clock()
            return sorted(h for h, r in self._records.items()
                          if self._live(r, now) and now - r["last_refresh"] >= interval)

    def transitions(self):
        """[(host_id, "live" | "down")] changed since the previous call, each reported once."""
        with self._lock:
            now = self._clock()
            changes = []
            for host_id in sorted(set(self._records) | set(self._reported)):
                record = self._records.get(host_id)
                state = "live" if record is not None and self._live(record, now) else "down"
                if state != self._reported.get(host_id, "down"):
                    self._reported[host_id] = state
                    changes.append((host_id, state))
            return changes

    def heard_beacon_within(self, window):
        with self._lock:
            now = self._clock()
            return any(r["heard_via"] == "beacon" and now - r["last_heard"] <= window
                       for r in self._records.values())


# ---------------------------------------------------------------------------
# Sections 6.1 and 7: HTTP routing table, fleet routing, and the bin/qwen-agent
# clients (F42, F57-F64, F68)
# ---------------------------------------------------------------------------

_ROUTES = {
    ("GET", "/health"): ("signed", "health"),
    ("GET", "/skills"): ("signed", "skills"),
    ("POST", "/run"): ("signed", "run"),
    ("GET", "/peers"): ("loopback", "peers"),
    ("POST", "/delegate"): ("loopback", "delegate"),
}


def is_loopback_client(ip):
    """Exact string match on the client address (F42); ::ffff:127.0.0.1 is NOT loopback."""
    return ip in LOOPBACK_CLIENTS


def http_route(method, path):
    """(kind, name) for a request; ("unknown", None) for every other pair (F42)."""
    return _ROUTES.get((method, path), ("unknown", None))


def serves_skill(skills, skill):
    """True iff a skills list (/skills or fleet-view shape) has `skill` with verified True (F57)."""
    return any(isinstance(item, dict) and item.get("skill") == skill and item.get("verified") is True
               for item in skills)


def route_candidates(skill, view):
    """[LOCAL] when this host serves skill verified, else eligible peer host_ids in view order (F59)."""
    if serves_skill(view["self"]["skills"], skill):
        return [LOCAL]
    return [peer["host_id"] for peer in view["peers"]
            if peer.get("compatible") is True and serves_skill(peer["skills"], skill)]


def delegate_enum(targets, view):
    """The delegate_to_skill enum filtered to targets something live serves (F60)."""
    return [t for t in targets if route_candidates(t, view)]


def _valid_skill_list(skills):
    return isinstance(skills, list) and all(
        isinstance(i, dict) and isinstance(i.get("skill"), str) and isinstance(i.get("verified"), bool)
        for i in skills)


def valid_view(obj):
    """True iff obj has the F61 shape of a qwen-agentd.peers.v1 fleet view. Never raises."""
    try:
        if not (isinstance(obj, dict) and obj.get("schema") == PEERS_SCHEMA):
            return False
        me = obj.get("self")
        if not (isinstance(me, dict) and isinstance(me.get("host_id"), str) and _valid_skill_list(me.get("skills"))):
            return False
        peers = obj.get("peers")
        if not isinstance(peers, list):
            return False
        for peer in peers:
            if not (isinstance(peer, dict) and isinstance(peer.get("host_id"), str)
                    and isinstance(peer.get("compatible"), bool) and _valid_skill_list(peer.get("skills"))):
                return False
        return True
    except Exception:
        return False


def failover(candidates, attempt):
    """Try candidates in order until one returns "ok" (F68). attempt(host_id) -> (outcome, envelope)."""
    tried = []
    for host_id in candidates:
        try:
            outcome, envelope = attempt(host_id)
        except Exception:
            outcome, envelope = "error", None
        if outcome == "ok":
            return {"outcome": "ok", "host_id": host_id, "envelope": envelope, "tried": tried}
        tried.append((host_id, outcome))
    return {"outcome": "exhausted", "host_id": None, "envelope": None, "tried": tried}


def daemon_url_from_env(environ):
    """(url, warning) from QWEN_AGENT_DAEMON_URL; only http://127.0.0.1:<port> is accepted (F63)."""
    value = environ.get("QWEN_AGENT_DAEMON_URL", "")
    if value == "":
        return DEFAULT_DAEMON_URL, None
    match = DAEMON_URL_RE.fullmatch(value)
    if match and 1 <= int(match.group(1)) <= 65535:
        return value, None
    return None, ("qwen-agent: warning: ignoring QWEN_AGENT_DAEMON_URL=%s: it must be "
                  "http://127.0.0.1:<port>; fleet routing disabled" % value)


def _loopback_port(daemon_url):
    return int(DAEMON_URL_RE.fullmatch(daemon_url).group(1))


def fetch_view(daemon_url):
    """(view, warning) from GET /peers on the local daemon (F64).

    http.client, never urllib, so no proxy setting can intercept it (F44). A
    missing daemon is the normal case and returns (None, None) silently.
    """
    if daemon_url is None:
        return None, None
    conn = http.client.HTTPConnection("127.0.0.1", _loopback_port(daemon_url), timeout=VIEW_TIMEOUT)
    try:
        conn.request("GET", "/peers")
        resp = conn.getresponse()
        status = resp.status
        body = resp.read(MAX_BODY + 1)
    except (OSError, http.client.HTTPException):
        return None, None
    finally:
        conn.close()
    warning = ("qwen-agent: warning: qwen-agentd at %s returned an unrecognized fleet view; "
               "fleet routing disabled" % daemon_url)
    if status != 200:
        return None, warning
    try:
        view = json.loads(body)
    except (ValueError, RecursionError):
        return None, warning
    if not valid_view(view):
        return None, warning
    return view, None


def _post_delegate(daemon_url, request):
    """(status, raw, None) of one loopback POST /delegate, or (None, None, <ExcType>)."""
    try:
        body = canonical_json(request)
        conn = http.client.HTTPConnection("127.0.0.1", _loopback_port(daemon_url),
                                          timeout=DELEGATE_CLIENT_TIMEOUT)
        try:
            conn.request("POST", "/delegate", body=body,
                         headers={"Content-Type": "application/json", "Content-Length": str(len(body))})
            resp = conn.getresponse()
            return resp.status, resp.read(MAX_BODY + 1), None
        finally:
            conn.close()
    except Exception as e:
        return None, None, type(e).__name__


def delegate_once(daemon_url, skill, task, host_id, images=None, trace=None):
    """POST /delegate for one named peer -> (outcome, envelope, detail). Never raises (F68).

    images is the wire list (vision spec V10, V20); trace is the {"trace_id", "parent_span_id"}
    field (tracing spec TR15). A daemon that answers a traced body 400 {"error": "bad request"}
    predates tracing; the same request is sent once more without the field.
    """
    if daemon_url is None:
        return "daemon_error", None, "no daemon"
    request = {"skill": skill, "task": task, "host_id": host_id}
    if images is not None:
        request["images"] = images
    if trace is not None:
        request["trace"] = trace
    status, raw, error = _post_delegate(daemon_url, request)
    if trace is not None and status == 400 and _json_loads_or_none(raw) == {"error": "bad request"}:
        del request["trace"]
        status, raw, error = _post_delegate(daemon_url, request)
    if error is not None:
        return "daemon_error", None, error
    if status != 200:
        return "daemon_error", None, "http %d" % status
    try:
        obj = json.loads(raw)
    except (ValueError, RecursionError):
        return "daemon_error", None, "bad response"
    if not (isinstance(obj, dict) and isinstance(obj.get("outcome"), str)
            and isinstance(obj.get("detail"), str) and "envelope" in obj):
        return "daemon_error", None, "bad response"
    if obj["outcome"] == "ok" and not (isinstance(obj["envelope"], dict)
                                       and obj["envelope"].get("schema") == ONESHOT_SCHEMA):
        return "daemon_error", None, "bad response"
    return obj["outcome"], obj["envelope"], obj["detail"]


# ---------------------------------------------------------------------------
# Sections 9 and 10.5: deploy root, releases, update state, the update cycle,
# and the log directory (F80-F85a, F88a, F107)
# ---------------------------------------------------------------------------

_STATUSES = ("ok", "pending", "rolled_back")


def deploy_root(host_id):
    """A(<id>) = ~/agents/<id>, this agent's root (multi-agent spec M2)."""
    _check_agent_id(host_id)
    return os.path.join(os.path.expanduser(AGENTS_DIR), host_id)


def log_dir(host_id):
    """A(<id>)/logs, this agent's log directory on every platform (F107, multi-agent spec M5)."""
    return os.path.join(deploy_root(host_id), LOGS_SUBDIR)


def tag_key(tag):
    """(year, month, day, n) for a release tag, else None. Tags compare only by this (F81)."""
    if not isinstance(tag, str):
        return None
    match = TAG_RE.fullmatch(tag)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4) or 0))


def select_candidate(tags, current, bad_tags, is_ancestor):
    """The highest tag newer than current that descends from it and is not bad (F85a)."""
    ck = tag_key(current)
    if ck is None:
        return None
    newer = [t for t in set(tags)
             if tag_key(t) is not None and tag_key(t) > ck and t not in bad_tags]
    for t in sorted(newer, key=tag_key, reverse=True):
        if is_ancestor(current, t):
            return t
    return None


def _default_state():
    return {"from": None, "to": None, "status": "ok", "attempts": 0, "bad_tags": []}


def _valid_state(state):
    return (isinstance(state, dict)
            and set(state) == {"from", "to", "status", "attempts", "bad_tags"}
            and (state["from"] is None or isinstance(state["from"], str))
            and (state["to"] is None or isinstance(state["to"], str))
            and isinstance(state["status"], str) and state["status"] in _STATUSES
            and _is_int(state["attempts"]) and state["attempts"] >= 0
            and isinstance(state["bad_tags"], list)
            and all(isinstance(t, str) for t in state["bad_tags"]))


def read_state(path):
    """The update state, or the default state when missing or invalid. Never raises (F83)."""
    try:
        with open(path, "rb") as f:
            state = json.loads(f.read())
    except Exception:
        return _default_state()
    return state if _valid_state(state) else _default_state()


def write_state(path, state):
    """Atomically replace the state file with canonical JSON plus a newline, mode 0600 (F83)."""
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(canonical_json(state) + b"\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def releases_to_prune(present, current, state):
    """Release names to unstage: never current, state["from"], or the 3 newest (F88a)."""
    cands = [n for n in present if tag_key(n) is not None]
    keep = {current}
    if state.get("from") is not None:
        keep.add(state["from"])
    keep.update(sorted(cands, key=tag_key, reverse=True)[:KEEP_RELEASES])
    return sorted([n for n in cands if n not in keep], key=tag_key)


def release_version(repo_root, deploy_root):
    """The tag when repo_root is D/releases/<tag>/qwen-agent-workspace, else "dev" (F82)."""
    rr = os.path.realpath(repo_root)
    parent = os.path.dirname(rr)
    if (os.path.basename(rr) == WS_SUBDIR
            and os.path.dirname(parent) == os.path.realpath(os.path.join(deploy_root, "releases"))
            and tag_key(os.path.basename(parent)) is not None):
        return os.path.basename(parent)
    return "dev"


def run_update_cycle(ctx):
    """One self-update cycle over the F85 ctx interface; returns the outcome string (F84, F85)."""
    ok, detail = ctx.fetch()
    if not ok:
        ctx.log("WARNING", "update: git fetch failed (%s); retrying next cycle" % detail)
        return "fetch_failed"
    state = ctx.read_state()
    cur = ctx.current_tag()
    cand = select_candidate(ctx.list_tags(), cur, state["bad_tags"], ctx.is_ancestor)
    if cand is None:
        return "up_to_date"
    if ctx.is_dirty():
        ctx.log("WARNING", "update: %s available but the current release has modified tracked "
                           "files; not updating" % cand)
        return "dirty"
    if not ctx.try_lock():
        ctx.log("INFO", "update: %s deferred: a run is in flight" % cand)
        return "busy"
    held = [True]

    def release():
        if held[0]:
            held[0] = False
            ctx.unlock()

    try:
        ok, detail = ctx.stage(cand)
        if not ok:
            release()
            ctx.log("WARNING", "update: staging %s failed (%s)" % (cand, detail))
            return "stage_failed"
        ok, detail = ctx.gate(cand)
        if not ok:
            state = ctx.read_state()
            if cand not in state["bad_tags"]:
                state["bad_tags"].append(cand)
            ctx.write_state(state)
            ctx.unstage(cand)
            release()
            ctx.log("WARNING", "update: %s failed its gate (%s); marked bad" % (cand, detail))
            return "gate_failed"
        prev = ctx.read_state()
        ctx.write_state({"from": cur, "to": cand, "status": "pending", "attempts": 0,
                         "bad_tags": prev["bad_tags"]})
        ctx.log("INFO", "update: switching %s -> %s" % (cur, cand))
        try:
            ctx.swap(cand)
        except Exception as e:
            ctx.write_state(prev)
            release()
            ctx.log("ERROR", "update: swap to %s failed (%s: %s)" % (cand, type(e).__name__, e))
            return "error"
    except Exception as e:
        release()
        ctx.log("ERROR", "update: %s: %s" % (type(e).__name__, e))
        return "error"
    ctx.restart()
    return "switched"


# ---------------------------------------------------------------------------
# Multi-agent hosts: agent IDs, service names, commands and agent resolution
# (docs/superpowers/specs/2026-10-17-fleet-multi-agent-hosts-design.md)
# ---------------------------------------------------------------------------

def _check_agent_id(host_id):
    """ValueError unless host_id is a valid agent ID; no path is built from a bad one (multi-agent spec M2)."""
    if not isinstance(host_id, str) or not HOST_ID_RE.fullmatch(host_id):
        raise ValueError("invalid agent id %r" % (host_id,))


_TOKEN_RUN_RE = re.compile(r"[0-9a-f]{64}")


def shown_value(value):
    """'<value>' for an error message, unless it holds a token-shaped run (multi-agent spec MK5)."""
    if isinstance(value, str) and _TOKEN_RUN_RE.search(value):
        return "(a value that looks like a join string; not shown)"
    return "'%s'" % (value,)


def launchd_label(host_id):
    """com.qwen-agent.qwen-agentd.<id>, this agent's LaunchAgent label (multi-agent spec M6)."""
    _check_agent_id(host_id)
    return LAUNCHD_LABEL + "." + host_id


def systemd_unit(host_id):
    """qwen-agentd-<id>.service, this agent's systemd user unit (multi-agent spec M6)."""
    _check_agent_id(host_id)
    return SYSTEMD_UNIT_FMT % host_id


def command_path(host_id):
    """~/.local/bin/qwen-agent-<id>, this agent's command (multi-agent spec M8)."""
    _check_agent_id(host_id)
    return os.path.join(os.path.expanduser(BIN_DIR), COMMAND_NAME + "-" + host_id)


def default_command_path():
    """~/.local/bin/qwen-agent, the default agent's command (multi-agent spec M8)."""
    return os.path.join(os.path.expanduser(BIN_DIR), COMMAND_NAME)


def agent_ids_on_disk():
    """Sorted IDs of the directories in ~/agents that hold fleet.env or current (multi-agent spec M21)."""
    root = os.path.expanduser(AGENTS_DIR)
    try:
        names = os.listdir(root)
    except OSError:
        return []
    found = []
    for name in names:
        path = os.path.join(root, name)
        if (HOST_ID_RE.fullmatch(name) and os.path.isdir(path)
                and (os.path.lexists(os.path.join(path, FLEET_ENV_NAME))
                     or os.path.lexists(os.path.join(path, "current")))):
            found.append(name)
    return sorted(found)


def resolve_agent(explicit):
    """(host_id, None) or (None, stderr message) for an optional --agent-id (multi-agent spec M22)."""
    if explicit is not None:
        if isinstance(explicit, str) and HOST_ID_RE.fullmatch(explicit):
            return explicit, None
        return None, "qwen-agentd: invalid --agent-id %s" % shown_value(explicit)
    root = os.path.expanduser(AGENTS_DIR)
    ids = agent_ids_on_disk()
    if len(ids) == 1:
        return ids[0], None
    if not ids:
        return None, "qwen-agentd: no agent found in %s; pass --agent-id ID" % root
    return None, "qwen-agentd: more than one agent in %s (%s); pass --agent-id ID" % (root, ", ".join(ids))


def default_beacon_targets(registry):
    """One broadcast target per distinct registry port, ascending (multi-agent spec M16)."""
    ports = set(h.get("port", DEFAULT_PORT) for h in registry["hosts"].values())
    return [(BROADCAST_ADDR, p) for p in sorted(ports)]


def agent_port(fleets_dir, host_id):
    """(port or None, files): host_id's port in the valid registries of fleets_dir (multi-agent spec M24).

    files lists, sorted, every *.json in fleets_dir that parses, passes validate_registry
    against its own fleet_id, and has host_id in hosts. port is None unless all of them
    agree. Unreadable files are skipped; a missing directory gives (None, []).
    """
    try:
        names = sorted(os.listdir(fleets_dir))
    except OSError:
        return None, []
    files = []
    ports = set()
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(fleets_dir, name), "r", encoding="utf-8") as f:
                obj = json.loads(f.read())
        except (OSError, ValueError, RecursionError):
            continue
        if not (isinstance(obj, dict) and isinstance(obj.get("hosts"), dict) and host_id in obj["hosts"]
                and validate_registry(obj, obj.get("fleet_id")) == []):
            continue
        files.append(name)
        ports.add(obj["hosts"][host_id].get("port", DEFAULT_PORT))
    if len(ports) == 1:
        return ports.pop(), files
    return None, files


def _sh_single_quote(s):
    """s as one POSIX sh single-quoted word, ' written as '\\'' (multi-agent spec M9)."""
    return "'" + s.replace("'", "'\\''") + "'"


def wrapper_bytes(host_id, port):
    """The exact wrapper file for one agent (multi-agent spec M9)."""
    _check_agent_id(host_id)
    if not (_is_int(port) and MIN_PORT <= port <= 65535):
        raise ValueError("invalid port %r" % (port,))
    target = os.path.join(deploy_root(host_id), "current", WS_SUBDIR, "bin", "qwen-agent")
    return ("#!/bin/sh\n"
            + WRAPPER_MARKER + "\n"
            + WRAPPER_ID_PREFIX + host_id + "\n"
            + "QWEN_AGENT_DAEMON_URL=http://127.0.0.1:%d\n" % port
            + "export QWEN_AGENT_DAEMON_URL\n"
            + "exec " + _sh_single_quote(target) + ' "$@"\n').encode("utf-8")


def is_wrapper(data):
    """True when one whole line of data equals WRAPPER_MARKER (multi-agent spec M10)."""
    return WRAPPER_MARKER.encode("ascii") in data.split(b"\n")


def wrapper_agent_id(data):
    """The agent ID on the first "# agent-id: " line of data, or None (multi-agent spec M10)."""
    prefix = WRAPPER_ID_PREFIX.encode("ascii")
    for line in data.split(b"\n"):
        if line.startswith(prefix):
            try:
                value = line[len(prefix):].decode("ascii")
            except UnicodeDecodeError:
                return None
            return value if HOST_ID_RE.fullmatch(value) else None
    return None


def classify_command_path(path):
    """(kind, found_id): "absent", "symlink", "wrapper" (with its agent ID) or "other" (multi-agent spec M10)."""
    if not os.path.lexists(path):
        return "absent", None
    if os.path.islink(path):
        return "symlink", None
    if os.path.isfile(path):
        try:
            with open(path, "rb") as f:
                data = f.read(WRAPPER_MAX_BYTES + 1)
        except OSError:
            return "other", None
        if len(data) <= WRAPPER_MAX_BYTES and is_wrapper(data):
            return "wrapper", wrapper_agent_id(data)
    return "other", None


def write_wrapper(path, data):
    """Atomically replace path (a symlink itself, never its target) with data, mode 0755 (multi-agent spec M10)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    if os.path.lexists(tmp):
        os.unlink(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o755)
    try:
        with os.fdopen(fd, "wb") as f:
            os.fchmod(f.fileno(), 0o755)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def agent_command_action(kind):
    """The action for ~/.local/bin/qwen-agent-<id> of this kind: "write" or "refuse" (multi-agent spec M11)."""
    return "write" if kind in ("absent", "symlink", "wrapper") else "refuse"


def default_command_action(kind, found_id, host_id, make_default):
    """The action for ~/.local/bin/qwen-agent: "write", "refuse" or "keep" (multi-agent spec M12)."""
    if kind == "absent":
        return "write"
    if kind == "wrapper" and found_id == host_id:
        return "write"
    if make_default and kind in ("symlink", "wrapper"):
        return "write"
    if make_default and kind == "other":
        return "refuse"
    return "keep"


# ---------------------------------------------------------------------------
# Tracing: IDs, records, the store, the clients and the tree (tracing spec)
# ---------------------------------------------------------------------------

def _valid_id(value, regex):
    return isinstance(value, str) and regex.fullmatch(value) is not None and value.strip("0") != ""


def valid_trace_id(value):
    """True for 32 lowercase hex characters, not all zero (W3C trace-id shape)."""
    return _valid_id(value, TRACE_ID_RE)


def valid_span_id(value):
    """True for 16 lowercase hex characters, not all zero (W3C parent-id shape)."""
    return _valid_id(value, SPAN_ID_RE)


def new_trace_id():
    """A fresh trace ID from secrets.token_hex(16); the all-zero value is drawn again."""
    while True:
        value = secrets.token_hex(16)
        if valid_trace_id(value):
            return value


def new_span_id():
    """A fresh span ID from secrets.token_hex(8); the all-zero value is drawn again."""
    while True:
        value = secrets.token_hex(8)
        if valid_span_id(value):
            return value


_TRACE_KEYS = frozenset(("v", "trace_id", "span_id", "parent_span_id", "agent", "kind", "name",
                         "start", "dur_ms", "status", "attrs"))
_TRACE_ATTRS = {
    "turn": {"rounds": "int", "tool_calls": "int"},
    "model": {"call": "int", "tools": "bool", "prompt_tokens": "int?", "completion_tokens": "int?",
              "finish_reason": "token?", "http": "int?"},
    "tool": {"round": "int", "decision": "token", "key": "text", "outcome": "text", "error": "bool"},
    "delegate": {"skill": "name", "target": "agent", "request_id": "reqid?", "http": "int?",
                 "images": "int"},
    "run": {"skill": "name", "request_id": "reqid", "http": "int", "images": "int", "image_bytes": "int"},
    "agent": {"skill": "name", "request_id": "reqid", "http": "int", "envelope_status": "token?"},
}


def make_record(trace_id, span_id, parent_span_id, agent, kind, name, start, t0, status, attrs, now=None):
    """One finished span (tracing spec TR4). agent None gives the /spans form, without "agent".

    start is round(time.time(), 3) at the span's start; t0 is time.monotonic() then, so
    dur_ms is immune to wall-clock steps. now (a monotonic time) is for tests.
    """
    end = time.monotonic() if now is None else now
    record = {"v": TRACE_RECORD_VERSION, "trace_id": trace_id, "span_id": span_id,
              "parent_span_id": parent_span_id, "kind": kind, "name": name, "start": start,
              "dur_ms": max(0, int(round((end - t0) * 1000))), "status": status, "attrs": attrs}
    if agent is not None:
        record["agent"] = agent
    return record


def _trace_attr_ok(kind, value):
    if kind.endswith("?"):
        if value is None:
            return True
        kind = kind[:-1]
    if kind == "int":
        return _is_int(value) and 0 <= value <= TRACE_COUNT_MAX
    if kind == "bool":
        return isinstance(value, bool)
    if not isinstance(value, str):
        return False
    if kind == "text":
        return len(value) <= TRACE_TEXT_CHARS and _TRACE_TEXT_BAD_RE.search(value) is None
    regex = {"token": TRACE_TOKEN_RE, "name": TRACE_NAME_RE, "agent": HOST_ID_RE, "reqid": REQUEST_ID_RE}[kind]
    return regex.fullmatch(value) is not None


def trace_record_error(rec, posted=False):
    """None for a valid trace record, else the name of its first bad field (tracing spec TR4).

    posted=True checks the /spans form: no "agent", and only TRACE_POSTED_KINDS. Never raises;
    the result never contains any part of rec.
    """
    try:
        if not isinstance(rec, dict):
            return "record"
        if set(rec) != (_TRACE_KEYS - {"agent"} if posted else _TRACE_KEYS):
            return "keys"
        if not (_is_int(rec["v"]) and rec["v"] == TRACE_RECORD_VERSION):
            return "v"
        if not valid_trace_id(rec["trace_id"]):
            return "trace_id"
        if not valid_span_id(rec["span_id"]):
            return "span_id"
        parent = rec["parent_span_id"]
        if parent is not None and not (valid_span_id(parent) and parent != rec["span_id"]):
            return "parent_span_id"
        if not posted and not (isinstance(rec["agent"], str) and HOST_ID_RE.fullmatch(rec["agent"])):
            return "agent"
        if not (isinstance(rec["kind"], str) and rec["kind"] in (TRACE_POSTED_KINDS if posted else TRACE_KINDS)):
            return "kind"
        if not (isinstance(rec["name"], str) and TRACE_NAME_RE.fullmatch(rec["name"])):
            return "name"
        start = rec["start"]
        if not ((_is_int(start) or isinstance(start, float)) and 0 <= start < 10 ** 11):
            return "start"
        if not (_is_int(rec["dur_ms"]) and 0 <= rec["dur_ms"] <= TRACE_DUR_MAX_MS):
            return "dur_ms"
        if not (isinstance(rec["status"], str) and TRACE_TOKEN_RE.fullmatch(rec["status"])):
            return "status"
        schema = _TRACE_ATTRS[rec["kind"]]
        attrs = rec["attrs"]
        if not (isinstance(attrs, dict) and set(attrs) == set(schema)):
            return "attrs"
        for key in sorted(schema):
            if not _trace_attr_ok(schema[key], attrs[key]):
                return "attrs." + key
        return None
    except Exception:
        return "record"


def trace_name(value):
    """value when it is a valid span name, else "unknown"."""
    return value if isinstance(value, str) and TRACE_NAME_RE.fullmatch(value) else "unknown"


def trace_skill(value):
    """A skill for a span: a KNOWN_SKILLS member, else "unknown" (a /run body's skill is unchecked text)."""
    return value if isinstance(value, str) and value in KNOWN_SKILLS else "unknown"


def trace_token(value):
    """value when it matches TRACE_TOKEN_RE, else None (envelope statuses, finish_reason)."""
    return value if isinstance(value, str) and TRACE_TOKEN_RE.fullmatch(value) else None


def trace_count(value):
    """value when it is an int attribute (usage token counts), else None."""
    return value if _is_int(value) and 0 <= value <= TRACE_COUNT_MAX else None


def run_status(http, envelope_status):
    """The status of a run span (tracing spec TR4)."""
    if http == 200 and envelope_status == "ok":
        return "ok"
    return "busy" if http == 409 else "error"


def valid_trace_field(obj):
    """True for {"trace_id", "parent_span_id"} with valid IDs and no other key (tracing spec TR7)."""
    return (isinstance(obj, dict) and set(obj) == {"trace_id", "parent_span_id"}
            and valid_trace_id(obj["trace_id"]) and valid_span_id(obj["parent_span_id"]))


def trace_context(field):
    """(trace_id, parent_span_id) from a validated trace field, or a new trace with no parent."""
    if field is None:
        return new_trace_id(), None
    return field["trace_id"], field["parent_span_id"]


def trace_env_context(environ):
    """(trace_id, parent_span_id) from QWEN_AGENT_TRACE_ID and QWEN_AGENT_PARENT_SPAN when both are valid, else None."""
    trace_id, parent = environ.get(TRACE_ENV_ID, ""), environ.get(TRACE_ENV_PARENT, "")
    if valid_trace_id(trace_id) and valid_span_id(parent):
        return trace_id, parent
    return None


def _json_loads_or_none(raw):
    try:
        return json.loads(raw)
    except (ValueError, RecursionError, TypeError):
        return None


def valid_trace_result(obj, trace_id):
    """True iff obj is a GET /trace?id=<trace_id> result (tracing spec TR14, TR27). Never raises."""
    try:
        if not (isinstance(obj, dict) and obj.get("schema") == TRACE_SCHEMA and obj.get("trace_id") == trace_id):
            return False
        records, missing, truncated = obj.get("records"), obj.get("missing"), obj.get("truncated")
        if not (isinstance(records, list) and all(trace_record_error(r) is None for r in records)):
            return False
        if not (isinstance(missing, list) and all(
                isinstance(m, dict) and set(m) == {"agent", "reason"}
                and isinstance(m["agent"], str) and isinstance(m["reason"], str) for m in missing)):
            return False
        return isinstance(truncated, list) and all(
            isinstance(t, dict) and set(t) == {"agent", "count"}
            and isinstance(t["agent"], str) and _is_int(t["count"]) for t in truncated)
    except Exception:
        return False


_RECENT_KEYS = frozenset(("trace_id", "start", "dur_ms", "status", "kind", "name", "spans", "delegated"))


def valid_recent_result(obj):
    """True iff obj is a GET /traces/recent result (tracing spec TR14, TR28). Never raises."""
    try:
        if not (isinstance(obj, dict) and obj.get("schema") == RECENT_SCHEMA
                and isinstance(obj.get("agent"), str) and HOST_ID_RE.fullmatch(obj["agent"])
                and isinstance(obj.get("traces"), list)):
            return False
        for t in obj["traces"]:
            if not (isinstance(t, dict) and set(t) == _RECENT_KEYS and valid_trace_id(t["trace_id"])
                    and (_is_int(t["start"]) or isinstance(t["start"], float))
                    and _is_int(t["dur_ms"]) and _is_int(t["spans"])
                    and isinstance(t["status"], str) and TRACE_TOKEN_RE.fullmatch(t["status"])
                    and isinstance(t["kind"], str) and t["kind"] in TRACE_KINDS
                    and isinstance(t["name"], str) and TRACE_NAME_RE.fullmatch(t["name"])
                    and isinstance(t["delegated"], list) and all(isinstance(d, str) for d in t["delegated"])):
                return False
        return True
    except Exception:
        return False


def post_span(daemon_url, record, timeout=TRACE_POST_TIMEOUT):
    """True iff the local daemon accepted one finished span (loopback POST /spans, tracing spec TR22)."""
    if daemon_url is None:
        return False
    try:
        body = canonical_json(record)
        conn = http.client.HTTPConnection("127.0.0.1", _loopback_port(daemon_url), timeout=timeout)
        try:
            conn.request("POST", "/spans", body=body,
                         headers={"Content-Type": "application/json", "Content-Length": str(len(body))})
            resp = conn.getresponse()
            status = resp.status
            resp.read(MAX_BODY + 1)
        finally:
            conn.close()
    except Exception:
        return False
    return status == 200


def _loopback_get(daemon_url, path, timeout):
    try:
        conn = http.client.HTTPConnection("127.0.0.1", _loopback_port(daemon_url), timeout=timeout)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            return resp.status, resp.read(TRACE_CLIENT_MAX_BYTES + 1)
        finally:
            conn.close()
    except Exception:
        return None, None


def _loopback_result(daemon_url, status, raw, check):
    if status is None:
        return None, "daemon not reachable at %s" % daemon_url
    if status in (401, 404):
        return None, "the daemon at %s has no trace support (http %d)" % (daemon_url, status)
    if status != 200:
        return None, "the daemon at %s answered http %d" % (daemon_url, status)
    obj = _json_loads_or_none(raw) if len(raw) <= TRACE_CLIENT_MAX_BYTES else None
    if not check(obj):
        return None, "the daemon at %s returned an unrecognized trace response" % daemon_url
    return obj, None


def fetch_trace(daemon_url, trace_id):
    """(result, None) or (None, message) for loopback GET /trace?id=<trace_id> (tracing spec TR27)."""
    status, raw = _loopback_get(daemon_url, "/trace?id=" + trace_id, TRACE_QUERY_TIMEOUT)
    return _loopback_result(daemon_url, status, raw, lambda obj: valid_trace_result(obj, trace_id))


def fetch_recent(daemon_url, n):
    """(result, None) or (None, message) for loopback GET /traces/recent?n=<n> (tracing spec TR28)."""
    status, raw = _loopback_get(daemon_url, "/traces/recent?n=%d" % n, TRACE_RECENT_TIMEOUT)
    return _loopback_result(daemon_url, status, raw, valid_recent_result)
