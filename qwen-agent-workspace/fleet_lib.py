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

import copy
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import re
import sys
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
NONCE_RETENTION = 120         # s, never scaled
STARTUP_HEALTH_DEADLINE = 120 # s, never scaled
PEER_HTTP_TIMEOUT = 5         # s, /health and /skills calls to peers
MODEL_PROBE_TIMEOUT = 5       # s
RUN_TIMEOUT = 900             # s, equals bin/qwen-agent SKILL_SUBPROCESS_TIMEOUT
FORWARD_TIMEOUT = 930         # s, RUN_TIMEOUT + 30: /delegate -> peer /run
GATE_TIMEOUT = 300            # s, the staged release's selftest
GIT_TIMEOUT = 120             # s, any single git subprocess
MAX_BODY = 1048576            # bytes, request body cap
MAX_START_ATTEMPTS = 3
KEEP_RELEASES = 3
FLEET_TAG_CHARS = 16
KNOWN_SKILLS = ("investigator", "analyst", "planner", "researcher")
FLEET_ENV_KEYS = ("QWEN_AGENT_FLEET_ID", "QWEN_AGENT_FLEET_TOKEN")
FLEET_ENV_PREFIX = "QWEN_AGENT_FLEET_"   # every env key with this prefix is stripped (F54a, F86)
TAG_RE = re.compile(r"^v(\d{4})\.(\d{2})\.(\d{2})(?:\.([1-9]\d*))?$")
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
DEPLOY_ROOT = "~/.local/share/qwen-agent"   # passed through os.path.expanduser at every use
WS_SUBDIR = "qwen-agent-workspace"          # the workspace directory inside a release worktree
LAUNCHD_LABEL = "com.qwen-agent.qwen-agentd"
SYSTEMD_UNIT = "qwen-agentd.service"
SUPERVISOR_RESTART_DELAY = 10 # s, launchd ThrottleInterval and systemd RestartSec
LOG_MAX_BYTES = 5242880       # 5 MB
LOG_BACKUPS = 3

# Every regex above is applied with .fullmatch(), never .match(): "$" alone also
# matches just before a trailing newline, so "mac-local\n" would otherwise pass.


class RegistryError(ValueError):
    """The registry cannot be read, fails the F7 schema, or lacks this host (F8, F9)."""


class FleetEnvError(ValueError):
    """fleet.env or a join string is malformed (F21, F25). Never carries secret text."""


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
        port_ok = _is_int(port) and 1 <= port <= 65535
        if not port_ok:
            errors.append("%s.port: must be an integer in 1..65535" % loc)
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

def fleet_env_path():
    """~/.config/qwen-agent/fleet.env, the only place the token is stored (F19)."""
    return os.path.expanduser("~/.config/qwen-agent/fleet.env")


def write_fleet_env(path, fleet_id, token):
    """Create fleet.env (dir 0700, file 0600). An existing file raises FileExistsError (F20)."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    os.chmod(directory, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write("%s=%s\n%s=%s\n" % (FLEET_ENV_KEYS[0], fleet_id, FLEET_ENV_KEYS[1], token))
        f.flush()
        os.fsync(f.fileno())


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
