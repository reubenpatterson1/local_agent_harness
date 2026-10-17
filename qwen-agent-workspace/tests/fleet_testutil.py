"""Shared helpers for the fleet test suites (fleet spec Section 11.2, D10).

Not a test module (pytest does not collect it). Loopback only: every server a
helper starts binds 127.0.0.1, and every daemon gets explicit beacon targets.
Every spawned process gets HOME=<tmp dir> and a QWEN_AGENT_SEARXNG_URL that points
at a closed port, so no test touches real user state or needs a running SearXNG.
"""

import http.client
import http.server
import importlib.machinery
import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
import fleet_lib  # noqa: E402

AGENTD = os.path.join(WS, "bin", "qwen-agentd")
QWEN_AGENT = os.path.join(WS, "bin", "qwen-agent")
TEST_FLEET_ID = "0123456789abcdef"
TEST_TOKEN = "5e" * 32
TEST_KEY = bytes.fromhex(TEST_TOKEN)
OTHER_FLEET_ID = "fedcba9876543210"
OTHER_TOKEN = "a7" * 32
INTEGRATION_SCALE = "0.1"
SELF_UPDATE_SCALE = "0.01"

_ISSUED_PORTS = set()
_DROP_PREFIXES = ("QWEN_AGENT_", "SKILL_ENDPOINT_", "SKILL_MODEL_")
_PROXY_KEYS = ("http_proxy", "https_proxy", "all_proxy", "no_proxy")


def load_script(name, path):
    """Import an extensionless script (bin/qwen-agentd, bin/qwen-agent) as a module."""
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def free_port():
    """A port free for both TCP and UDP on 127.0.0.1, never handed out twice per process."""
    for _ in range(20):
        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            tcp.bind(("127.0.0.1", 0))
            port = tcp.getsockname()[1]
            try:
                udp.bind(("127.0.0.1", port))
            except OSError:
                continue
        finally:
            tcp.close()
            udp.close()
        if port not in _ISSUED_PORTS:
            _ISSUED_PORTS.add(port)
            return port
    raise AssertionError("no free TCP+UDP port after 20 tries")


def clean_env(home, **extra):
    """os.environ without QWEN_AGENT_*, SKILL_ENDPOINT_*/SKILL_MODEL_* or proxy variables,
    with HOME=home and a SearXNG URL at a closed port; `extra` is applied last."""
    env = dict((k, v) for k, v in os.environ.items()
               if not k.startswith(_DROP_PREFIXES) and k.lower() not in _PROXY_KEYS)
    env["HOME"] = str(home)
    env["QWEN_AGENT_SEARXNG_URL"] = "http://127.0.0.1:%d" % free_port()
    env.update(extra)
    return env


def make_fleet(home, host_id, fleet_id=TEST_FLEET_ID, token=TEST_TOKEN):
    """Write <home>/agents/<host_id>/fleet.env; returns its path."""
    path = os.path.join(str(home), "agents", host_id, "fleet.env")
    fleet_lib.write_fleet_env(path, fleet_id, token)
    return path


# --- registry, stub model servers, daemons, HTTP helpers (Task 12) -------------------

_STARTED = []   # every Popen a helper started; kill_all() SIGKILLs their process groups
_STUBS = []     # every StubModelServer; kill_all() stops them


def write_registry(path, fleet_id, hosts):
    """Write a registry with every host at 127.0.0.1 and an explicit port.

    hosts: {host_id: {"port": int, "model_server": {"type", "url"}, "model": str,
                      "skills": [...], optional "role"}}
    """
    obj = {"protocol": 1, "fleet_id": fleet_id, "hosts": {}}
    for host_id, h in hosts.items():
        obj["hosts"][host_id] = {"role": h.get("role", "agent"), "address": "127.0.0.1",
                                 "port": h["port"], "model_server": h["model_server"],
                                 "model": h["model"], "skills": list(h["skills"])}
    with open(str(path), "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    return str(path)


class StubModelServer(object):
    """An OpenAI-shaped model server on 127.0.0.1 (spec 11.2).

    GET /v1/models lists `model` for both kinds; kind "ollama" also serves
    GET /api/tags. POST /v1/chat/completions records the parsed body in .requests
    and answers either one delegate_to_skill tool call (when delegate_skill is set
    and no message has role "tool") or `answer` plus " | <last tool result>".
    port=0 picks a free port; a fixed port lets a test start the stub late.
    """

    def __init__(self, kind, model, answer, delegate_skill=None, port=0):
        self.kind, self.model, self.answer, self.delegate_skill = kind, model, answer, delegate_skill
        self.requests = []
        self._lock = threading.Lock()
        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _json(self, obj, status=200):
                raw = json.dumps(obj).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/v1/models":
                    self._json({"object": "list", "data": [{"id": stub.model, "object": "model"}]})
                elif self.path == "/api/tags" and stub.kind == "ollama":
                    self._json({"models": [{"name": stub.model, "model": stub.model}]})
                else:
                    self._json({"error": "not found"}, 404)

            def do_POST(self):
                if self.path != "/v1/chat/completions":
                    return self._json({"error": "not found"}, 404)
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                with stub._lock:
                    stub.requests.append(body)
                tool_msgs = [m for m in body.get("messages") or [] if m.get("role") == "tool"]
                if stub.delegate_skill and not tool_msgs:
                    message = {"role": "assistant", "content": "", "tool_calls": [{
                        "id": "call_stub_1", "type": "function",
                        "function": {"name": "delegate_to_skill",
                                     "arguments": json.dumps({"skill": stub.delegate_skill,
                                                              "task": "stub task"})}}]}
                    finish = "tool_calls"
                else:
                    content = stub.answer
                    if tool_msgs:
                        content += " | " + str(tool_msgs[-1].get("content"))
                    message = {"role": "assistant", "content": content}
                    finish = "stop"
                self._json({"id": "stub", "object": "chat.completion", "model": stub.model,
                            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.port = self.httpd.server_address[1]
        self.url = "http://127.0.0.1:%d/v1" % self.port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        _STUBS.append(self)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def daemon_log_dir(home, host_id):
    """fleet_lib.log_dir(host_id) as it resolves under HOME=home: <home>/agents/<host_id>/logs."""
    return os.path.join(str(home), "agents", host_id, "logs")


def read_log(home, host_id):
    path = os.path.join(daemon_log_dir(home, host_id), "qwen-agentd.log")
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


class DaemonProc(object):
    def __init__(self, proc, home, host_id, port, beacon_port):
        self.proc, self.home, self.host_id, self.port, self.beacon_port = proc, home, host_id, port, beacon_port
        self.url = "http://127.0.0.1:%d" % port

    def log(self):
        return read_log(self.home, self.host_id)

    def kill(self):
        _kill(self.proc)


def _kill(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    proc.wait()


def kill_all():
    while _STARTED:
        _kill(_STARTED.pop())
    while _STUBS:
        _STUBS.pop().stop()


def targets(*ports):
    """A --beacon-targets value for loopback beacon ports ("none" when empty)."""
    return ",".join("127.0.0.1:%d" % p for p in ports) or "none"


def spawn(argv, env, home):
    """Start argv in a new session with stdout+stderr in <home>/<name>.out; tracked for kill_all."""
    out_path = os.path.join(str(home), "%s.out" % os.path.basename(argv[1]))
    out = open(out_path, "ab")
    try:
        proc = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                                start_new_session=True)
    finally:
        out.close()
    _STARTED.append(proc)
    return proc


def start_daemon(home, host_id, registry, beacon_port, beacon_targets, extra_args=(),
                 scale=INTEGRATION_SCALE, env_extra=None, wait=True):
    """Spawn `qwen-agentd run` for host_id; return once GET /peers answers 200 (10 s max)."""
    with open(str(registry), encoding="utf-8") as f:
        port = json.load(f)["hosts"][host_id].get("port", fleet_lib.DEFAULT_PORT)
    argv = [sys.executable, AGENTD, "run", "--registry", str(registry), "--beacon-port", str(beacon_port),
            "--beacon-targets", beacon_targets, "--timing-scale", scale] + list(extra_args)
    env = clean_env(home, QWEN_AGENT_HOST_ID=host_id, **(env_extra or {}))
    proc = spawn(argv, env, home)
    daemon = DaemonProc(proc, home, host_id, port, beacon_port)
    if not wait:
        return daemon
    deadline = time.monotonic() + 10
    while True:
        if proc.poll() is not None:
            raise AssertionError("qwen-agentd %s exited %s at startup" % (host_id, proc.returncode))
        try:
            if peers(port)[0] == 200:
                return daemon
        except (OSError, http.client.HTTPException):
            pass
        if time.monotonic() > deadline:
            raise AssertionError("qwen-agentd %s did not answer /peers within 10 s" % host_id)
        time.sleep(0.05)


def _request(port, method, path, body=None, headers=None, timeout=30, source=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout, source_address=source)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, resp.headers, resp.read()
    finally:
        conn.close()


def peers(port):
    """(status, parsed body or None) of loopback GET /peers."""
    status, _headers, raw = _request(port, "GET", "/peers", timeout=5)
    return status, (json.loads(raw) if raw else None)


def delegate(port, skill, task, host_id, timeout=120):
    """(status, parsed body or None) of loopback POST /delegate."""
    body = json.dumps({"skill": skill, "task": task, "host_id": host_id}).encode("utf-8")
    status, _headers, raw = _request(port, "POST", "/delegate", body,
                                     {"Content-Type": "application/json"}, timeout=timeout)
    return status, (json.loads(raw) if raw else None)


def signed(key, method, port, path, body=b"", timeout=30, nonce=None):
    """A request signed with fleet_lib.sign_request -> (status, headers, body, request_nonce)."""
    nonce = nonce or os.urandom(16).hex()
    headers = fleet_lib.sign_request(key, method, path, body, int(time.time()), nonce)
    if method == "POST":
        headers["Content-Type"] = "application/json"
    status, resp_headers, raw = _request(port, method, path, body if method == "POST" else None,
                                         headers, timeout=timeout)
    return status, resp_headers, raw, nonce


def response_ok(key, status, method, path, nonce, headers, body):
    """True iff the response carries a valid fleet signature for that request."""
    return fleet_lib.verify_response(key, status, method, path, nonce, headers, body,
                                     int(time.time()), fleet_lib.NonceCache()) == "ok"


def raw_request(port, method, path, headers, body=b"", source=None):
    """Send exactly these headers (no automatic Content-Length) -> (status, body)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10, source_address=source)
    try:
        conn.putrequest(method, path)
        for name, value in headers.items():
            conn.putheader(name, value)
        conn.endheaders()
        if body:
            conn.send(body)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def wait_until(predicate, timeout, interval=0.1):
    """Poll predicate() until truthy; return the elapsed seconds, or fail the test."""
    start = time.monotonic()
    while True:
        try:
            if predicate():
                return time.monotonic() - start
        except (OSError, http.client.HTTPException, ValueError):
            pass
        if time.monotonic() - start > timeout:
            raise AssertionError("condition not met within %.1f s" % timeout)
        time.sleep(interval)


# --- the standard three-daemon fleet (spec 11.5; Task 13) -----------------------------

STANDARD_HOSTS = (
    # name, model-server kind, skills, model, stub answer
    ("alpha", "vllm", [], "alpha-model", "ALPHA-ANSWER"),
    ("bravo", "ollama", ["researcher"], "bravo-model", "BRAVO-ANSWER"),
    ("charlie", "vllm", ["analyst"], "charlie-model", "CHARLIE-ANSWER"),
)


class Fleet(object):
    """alpha/bravo/charlie on 127.0.0.1, one shared test fleet, one registry listing all.

    Each daemon has its own HOME, stub model server, HTTP port and beacon port, and
    beacons to the other two (plus `extra_targets`). `beacons=False` gives every
    daemon --beacon-targets none. `extra_args` / `stub_kwargs` / `env_extra` are
    keyed by name. `extra_hosts` adds registry entries for hosts no daemon runs
    (for example an in-process fake peer). Nothing starts until start().
    """

    def __init__(self, root, names=("alpha", "bravo", "charlie"), beacons=True, extra_targets=(),
                 extra_args=None, stub_kwargs=None, extra_hosts=None, start_stubs=True, env_extra=None):
        self.root = str(root)
        self.names = list(names)
        self.beacons = beacons
        self.extra_targets = list(extra_targets)
        self.extra_args = extra_args or {}
        self.env_extra = env_extra or {}
        self.homes, self.ports, self.beacon_ports, self.stubs, self.daemons = {}, {}, {}, {}, {}
        self.server_ports = {}
        hosts = {}
        spec = dict((h[0], h) for h in STANDARD_HOSTS)
        for name in self.names:
            _n, kind, skills, model, answer = spec[name]
            home = os.path.join(self.root, name)
            os.makedirs(home)
            make_fleet(home, name)
            self.homes[name] = home
            self.ports[name] = free_port()
            self.beacon_ports[name] = free_port()
            if start_stubs:
                self.stubs[name] = StubModelServer(kind, model, answer, **(stub_kwargs or {}).get(name, {}))
                self.server_ports[name] = self.stubs[name].port
            else:
                self.server_ports[name] = free_port()
            url = "http://127.0.0.1:%d/v1" % self.server_ports[name]
            hosts[name] = {"port": self.ports[name], "model_server": {"type": kind, "url": url},
                           "model": model, "skills": skills}
        hosts.update(extra_hosts or {})
        self.registry = write_registry(os.path.join(self.root, "registry.json"), TEST_FLEET_ID, hosts)

    def start(self):
        for name in self.names:
            others = [self.beacon_ports[o] for o in self.names if o != name] if self.beacons else []
            self.daemons[name] = start_daemon(
                self.homes[name], name, self.registry, self.beacon_ports[name],
                targets(*(others + self.extra_targets)) if (self.beacons or self.extra_targets) else "none",
                self.extra_args.get(name, ()), env_extra=self.env_extra.get(name))
        return self

    def view(self, name):
        return peers(self.ports[name])[1]

    def peer_ids(self, name):
        return sorted(p["host_id"] for p in self.view(name)["peers"])

    def all_see_each_other(self, via=None):
        for name in self.names:
            view = self.view(name)
            expected = sorted(n for n in self.names if n != name)
            if sorted(p["host_id"] for p in view["peers"]) != expected:
                return False
            if via is not None and any(p["heard_via"] != via for p in view["peers"]):
                return False
        return True


def send_beacon(key, port_field, beacon_port):
    """Send one valid beacon advertising HTTP port `port_field` to a daemon's beacon port."""
    data = fleet_lib.make_beacon(key, port_field, int(time.time()), os.urandom(16).hex())
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(data, ("127.0.0.1", beacon_port))
    finally:
        sock.close()


# --- --qwen-agent-bin hook scripts (spec 11.2; Task 14) --------------------------------

CANNED_LINE = ('{"schema": "qwen-agent.oneshot.v1", "status": "ok", "answer": "CANNED", '
               '"error": null, "rounds": 1, "tool_calls": []}')

_HOOK_SOURCES = {
    "canned": (
        "import sys\n"
        "print(%r)\n"
        "sys.exit(0)\n" % CANNED_LINE
    ),
    "slow": (
        "import os, sys, time\n"
        "task = ''\n"
        "for arg in sys.argv[1:]:\n"
        "    if arg.startswith('--user-prompt='):\n"
        "        task = arg[len('--user-prompt='):]\n"
        "if task == 'garbage':\n"
        "    print('not json')\n"
        "    sys.exit(1)\n"
        "release = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'release-' + task)\n"
        "while not os.path.exists(release):\n"
        "    time.sleep(0.05)\n"
        "print(%r)\n"
        "sys.exit(0)\n" % CANNED_LINE
    ),
    "envdump": (
        "import json, os, sys\n"
        "with open(os.path.abspath(__file__) + '.json', 'w') as f:\n"
        "    json.dump({'argv': sys.argv, 'env': dict(os.environ)}, f)\n"
        "os.execv(sys.executable, [sys.executable, %r] + sys.argv[1:])\n" % QWEN_AGENT
    ),
}


def write_hook(path, kind):
    """Write an executable --qwen-agent-bin stand-in: "slow", "envdump" or "canned"."""
    with open(str(path), "w", encoding="utf-8") as f:
        f.write(_HOOK_SOURCES[kind])
    os.chmod(str(path), 0o755)
    return str(path)


def release_hook(hook_path, task):
    """Let the "slow" hook's run for `task` finish."""
    open(os.path.join(os.path.dirname(str(hook_path)), "release-" + task), "w").close()
