"""bin/qwen-agentd tests: CLI subcommands and single-machine multi-daemon integration
(fleet spec Section 11.5, D8).

Run from the workspace root: python3 -m pytest tests/test_fleet_integration.py -v
Loopback only. Every daemon runs with --timing-scale 0.1, explicit beacon targets,
and HOME=<tmp dir>; the autouse fixture SIGKILLs every process group a test
started and stops every stub server. Time bounds below are the spec's bounds
scaled by 0.1.
"""

import errno
import http.client
import http.server
import json
import os
import re
import signal
import socket
import stat
import struct
import subprocess
import sys
import threading
import time

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
import fleet_lib  # noqa: E402
import fleet_testutil as ftu  # noqa: E402


# --- CLI: init-fleet, join, selftest, top-level errors (F23, F26, F92, F93, F99) ---------

@pytest.fixture
def agentd(monkeypatch, tmp_path):
    """bin/qwen-agentd imported in-process with HOME pointed at an empty temp dir."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return ftu.load_script("qwen_agentd_cli", ftu.AGENTD)


def test_cli_init_fleet(agentd, capsys):
    assert agentd.main(["init-fleet", "--agent-id", "alpha"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 4
    assert out[0].startswith("fleet_id: ")
    fleet_id = out[0][len("fleet_id: "):]
    assert fleet_lib.FLEET_ID_RE.fullmatch(fleet_id)
    assert out[1] == "join string (shown once; copy it to each other host over ssh):"
    assert out[3] == ("next: create fleets/%s.json (see the fleet spec, Section 2.4), commit, "
                      "tag a release" % fleet_id)
    path = fleet_lib.fleet_env_path("alpha")
    assert fleet_lib.parse_join_string(out[2]) == fleet_lib.load_fleet_env(path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert agentd.main(["init-fleet", "--agent-id", "alpha"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ("qwen-agentd: %s already exists; remove it first to create a new fleet\n" % path)


def test_cli_join(agentd, capsys, monkeypatch):
    s = fleet_lib.make_join_string(ftu.TEST_FLEET_ID, ftu.TEST_TOKEN)
    assert agentd.main(["join", "--agent-id", "alpha", "not-a-join-string"]) == 2
    assert capsys.readouterr().err == "qwen-agentd: invalid join string\n"
    prompts = []
    monkeypatch.setattr(agentd.getpass, "getpass", lambda prompt: prompts.append(prompt) or s + "\n")
    assert agentd.main(["join", "--agent-id", "alpha"]) == 0
    assert prompts == ["join string: "]
    assert capsys.readouterr().out == "qwen-agentd: joined fleet %s\n" % ftu.TEST_FLEET_ID
    path = fleet_lib.fleet_env_path("alpha")
    assert fleet_lib.load_fleet_env(path) == (ftu.TEST_FLEET_ID, ftu.TEST_TOKEN)
    assert agentd.main(["join", "--agent-id", "alpha", s]) == 0
    assert capsys.readouterr().out == "qwen-agentd: already joined fleet %s\n" % ftu.TEST_FLEET_ID
    other = fleet_lib.make_join_string(ftu.OTHER_FLEET_ID, ftu.OTHER_TOKEN)
    assert agentd.main(["join", "--agent-id", "alpha", other]) == 2
    assert capsys.readouterr().err == ("qwen-agentd: %s exists for a different fleet; remove it first\n" % path)


def test_cli_internal_error_is_one_line(agentd, capsys, monkeypatch):
    def boom(*args):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(agentd.fleet_lib, "write_fleet_env", boom)
    assert agentd.main(["init-fleet", "--agent-id", "alpha"]) == 1
    err = capsys.readouterr().err
    assert err == "qwen-agentd: internal error: RuntimeError: disk on fire\n"
    assert "Traceback" not in err


def test_cli_selftest_runs_the_unit_suite(tmp_path):
    env = ftu.clean_env(tmp_path, QWEN_AGENT_FLEET_TOKEN=ftu.TEST_TOKEN)
    proc = subprocess.run([sys.executable, ftu.AGENTD, "selftest"], env=env, cwd=str(tmp_path),
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert " passed" in proc.stdout


def test_cli_unknown_subcommand_exits_2(tmp_path):
    proc = subprocess.run([sys.executable, ftu.AGENTD, "frobnicate"], env=ftu.clean_env(tmp_path),
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 2 and "Traceback" not in proc.stderr
    assert "invalid choice: 'frobnicate'" in proc.stderr


# --- run: startup, endpoints, status, logging (F41-F46, F55, F94-F101, F107, F108) -----

@pytest.fixture(autouse=True)
def _reap_processes():
    yield
    ftu.kill_all()


def _single(tmp_path, skills=("researcher",), kind="ollama", start_stub=True, extra_args=()):
    """One daemon 'alpha' with its own stub model server; returns (daemon, stub, registry)."""
    home = tmp_path / "alpha"
    home.mkdir()
    ftu.make_fleet(home, "alpha")
    stub = ftu.StubModelServer(kind, "alpha-model", "ALPHA-ANSWER") if start_stub else None
    stub_url = stub.url if stub else "http://127.0.0.1:%d/v1" % ftu.free_port()
    registry = ftu.write_registry(tmp_path / "registry.json", ftu.TEST_FLEET_ID, {
        "alpha": {"port": ftu.free_port(), "model_server": {"type": kind, "url": stub_url},
                  "model": "alpha-model", "skills": list(skills)}})
    daemon = ftu.start_daemon(home, "alpha", registry, ftu.free_port(), "none", extra_args)
    return daemon, stub, registry


def _run_agentd(home, args, env_extra=None, timeout=20):
    env = ftu.clean_env(home, **(env_extra or {}))
    return subprocess.run([sys.executable, ftu.AGENTD] + list(args), env=env, capture_output=True,
                          text=True, timeout=timeout)


def test_t47_signatures_and_loopback_rules(tmp_path):
    daemon, _stub, _registry = _single(tmp_path)
    status, _h, body = ftu._request(daemon.port, "GET", "/health")
    assert (status, body) == (401, b"")
    status, headers, body, nonce = ftu.signed(ftu.TEST_KEY, "GET", daemon.port, "/health")
    assert status == 200 and ftu.response_ok(ftu.TEST_KEY, status, "GET", "/health", nonce, headers, body)
    health = json.loads(body)
    assert health == {"host_id": "alpha", "role": "agent", "version": "dev", "proto": 1, "discovery": "poll"}
    status, headers, body, nonce = ftu.signed(ftu.TEST_KEY, "GET", daemon.port, "/nowhere")
    assert status == 404 and json.loads(body) == {"error": "not found"}
    assert ftu.response_ok(ftu.TEST_KEY, 404, "GET", "/nowhere", nonce, headers, body)
    assert ftu._request(daemon.port, "GET", "/nowhere")[0::2] == (401, b"")
    status, _h, body, _n = ftu.signed(bytes.fromhex(ftu.OTHER_TOKEN), "GET", daemon.port, "/health")
    assert (status, body) == (401, b"")
    if sys.platform.startswith("linux"):
        before = daemon.log()
        for method, path in (("GET", "/peers"), ("POST", "/delegate")):
            status, body = ftu.raw_request(daemon.port, method, path, {"Content-Length": "0"},
                                           source=("127.0.0.2", 0))
            assert (status, body) == (403, b"")
        assert daemon.log() == before


def test_run_endpoints_and_peers_view(tmp_path):
    daemon, _stub, _registry = _single(tmp_path)
    status, headers, body, nonce = ftu.signed(ftu.TEST_KEY, "GET", daemon.port, "/skills")
    assert status == 200 and ftu.response_ok(ftu.TEST_KEY, 200, "GET", "/skills", nonce, headers, body)
    assert json.loads(body) == {"host_id": "alpha", "skills": [
        {"skill": "researcher", "model": "alpha-model", "verified": True, "busy": False}]}
    status, view = ftu.peers(daemon.port)
    assert status == 200 and fleet_lib.valid_view(view)
    assert view["schema"] == "qwen-agentd.peers.v1" and view["peers"] == []
    assert view["self"] == {"host_id": "alpha", "role": "agent", "version": "dev", "proto": 1,
                            "discovery": "poll",
                            "skills": [{"skill": "researcher", "model": "alpha-model",
                                        "verified": True, "busy": False}]}
    log = daemon.log()
    assert ("qwen-agentd dev started host_id=alpha port=%d beacon_port=%d beacon_targets=0 "
            "skills=researcher:verified" % (daemon.port, daemon.beacon_port)) in log
    log_dir = ftu.daemon_log_dir(daemon.home, "alpha")
    assert stat.S_IMODE(os.stat(log_dir).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(os.path.join(log_dir, "qwen-agentd.log")).st_mode) == 0o600
    daemon.proc.send_signal(signal.SIGTERM)
    assert daemon.proc.wait(timeout=10) == 0


def test_run_model_down_offers_nothing(tmp_path):
    daemon, _stub, _registry = _single(tmp_path, start_stub=False)
    status, _h, body, _n = ftu.signed(ftu.TEST_KEY, "GET", daemon.port, "/skills")
    assert json.loads(body)["skills"][0]["verified"] is False
    assert "WARNING MainThread skill 'researcher' not offered: model 'alpha-model' not present at " in daemon.log()


def test_run_startup_errors(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    port = ftu.free_port()
    registry = ftu.write_registry(tmp_path / "registry.json", ftu.TEST_FLEET_ID, {
        "alpha": {"port": port, "model_server": {"type": "vllm", "url": "http://127.0.0.1:9/v1"},
                  "model": "m", "skills": []},
        "bravo": {"port": ftu.free_port(), "model_server": {"type": "vllm", "url": "http://127.0.0.1:9/v1"},
                  "model": "m", "skills": []}})
    base = ["run", "--registry", registry, "--beacon-targets", "none", "--beacon-port", str(ftu.free_port())]
    env_path = os.path.join(str(home), "agents", "alpha", "fleet.env")

    proc = _run_agentd(home, base, {"QWEN_AGENT_HOST_ID": "alpha"})
    assert proc.returncode == 2
    assert proc.stderr == ("qwen-agentd: %s not found; run qwen-agentd init-fleet --agent-id alpha or "
                           "qwen-agentd join --agent-id alpha\n" % env_path)
    ftu.make_fleet(home, "alpha")

    proc = _run_agentd(home, base)
    assert proc.returncode == 2
    assert proc.stderr == "qwen-agentd: QWEN_AGENT_HOST_ID is not set; agents on this machine: alpha\n"

    ftu.make_fleet(home, "charlie")
    proc = _run_agentd(home, base, {"QWEN_AGENT_HOST_ID": "charlie"})
    assert proc.stderr == ("qwen-agentd: host_id 'charlie' is not in the fleet registry; "
                           "valid IDs: alpha, bravo\n") and proc.returncode == 2

    bad = tmp_path / "bad.json"
    bad.write_text('{"protocol": 2}', encoding="utf-8")
    proc = _run_agentd(home, ["run", "--registry", str(bad), "--beacon-targets", "none"],
                       {"QWEN_AGENT_HOST_ID": "alpha"})
    assert proc.returncode == 2 and proc.stderr.startswith("qwen-agentd: invalid registry %s:\n  " % bad)

    proc = _run_agentd(home, ["run", "--beacon-targets", "none"], {"QWEN_AGENT_HOST_ID": "alpha"})
    default = os.path.join(WS, "fleets", ftu.TEST_FLEET_ID + ".json")
    assert proc.returncode == 2
    assert proc.stderr.startswith("qwen-agentd: cannot read registry %s: FileNotFoundError: " % default)

    for flags, message in ((["--beacon-targets", "10.0.0.1"], "qwen-agentd: invalid --beacon-targets"),
                           (["--beacon-targets", "300.0.0.1:1"], "qwen-agentd: invalid --beacon-targets"),
                           (["--beacon-port", "0"], "qwen-agentd: invalid --beacon-port"),
                           (["--timing-scale", "0"], "qwen-agentd: invalid --timing-scale"),
                           (["--timing-scale", "1.5"], "qwen-agentd: invalid --timing-scale"),
                           (["--qwen-agent-bin", "/nonexistent/qa"], "qwen-agentd: --qwen-agent-bin not found: /nonexistent/qa")):
        proc = _run_agentd(home, base + flags, {"QWEN_AGENT_HOST_ID": "alpha"})
        assert (proc.returncode, proc.stderr) == (2, message + "\n"), flags

    first = ftu.start_daemon(home, "alpha", registry, ftu.free_port(), "none")
    ftu.make_fleet(home, "bravo")
    proc = _run_agentd(home, base, {"QWEN_AGENT_HOST_ID": "alpha"})
    assert proc.returncode == 2
    assert proc.stderr == ("qwen-agentd: TCP port %d is already in use (is another qwen-agentd running?)\n"
                           % port)
    proc = _run_agentd(home, ["run", "--registry", registry, "--beacon-targets", "none",
                              "--beacon-port", str(first.beacon_port)], {"QWEN_AGENT_HOST_ID": "bravo"})
    assert (proc.returncode, proc.stderr) == (2, "qwen-agentd: UDP port %d is already in use\n" % first.beacon_port)
    assert "Traceback" not in first.log()


def test_status_command(tmp_path):
    daemon, _stub, _registry = _single(tmp_path)
    proc = _run_agentd(daemon.home, ["status", "--port", str(daemon.port)])
    assert proc.returncode == 0
    assert proc.stdout == ("daemon: %s (version dev, host_id alpha, discovery poll)\n"
                           "skills: researcher=verified\n"
                           "peers: none\n"
                           "update: not installed\n" % daemon.url)
    daemon.kill()
    proc = _run_agentd(daemon.home, ["status", "--port", str(daemon.port)])
    assert proc.returncode == 1
    assert proc.stdout == "daemon: not reachable at %s\nupdate: not installed\n" % daemon.url


def test_daemon_never_uses_urllib_request():
    """Review Focus 4 (daemon side): every fleet HTTP client is http.client (F44)."""
    with open(ftu.AGENTD, encoding="utf-8") as f:
        source = f.read()
    assert "urllib.request" not in source and "urlopen" not in source


def test_clock_skew_warns_once_per_source_ip(tmp_path):
    """F33: a correctly signed request or beacon more than 60 s off is rejected, and logs
    one WARNING per source IP per process, whichever arrives first."""
    alpha, _stub, _registry = _single(tmp_path)
    for _ in range(2):
        nonce = os.urandom(16).hex()
        headers = fleet_lib.sign_request(ftu.TEST_KEY, "GET", "/health", b"", int(time.time()) - 120, nonce)
        status, _h, body = ftu._request(alpha.port, "GET", "/health", headers=headers)
        assert (status, body) == (401, b"")
    data = fleet_lib.make_beacon(ftu.TEST_KEY, 1, int(time.time()) + 300, os.urandom(16).hex())
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(data, ("127.0.0.1", alpha.beacon_port))
    sock.close()
    time.sleep(1.0)
    log = alpha.log()
    assert log.count("exceeds 60s; check NTP on both hosts") == 1
    assert "WARNING " in log and re.search(
        r"clock skew of -12[01]s from 127\.0\.0\.1 exceeds 60s; check NTP on both hosts", log)


def test_loopback_routes_reject_browser_style_requests(tmp_path):
    daemon, _stub, _registry = _single(tmp_path)
    assert ftu.peers(daemon.port)[0] == 200
    status, _h, body = ftu._request(daemon.port, "GET", "/peers", headers={"Origin": "http://evil.example"})
    assert (status, body) == (403, b"")
    status, _h, body = ftu._request(daemon.port, "GET", "/peers",
                                    headers={"Host": "evil.example:%d" % daemon.port})
    assert (status, body) == (403, b"")
    payload = json.dumps({"skill": "researcher", "task": "x", "host_id": "alpha"}).encode("utf-8")
    status, _h, body = ftu._request(daemon.port, "POST", "/delegate", payload, {"Content-Type": "text/plain"})
    assert (status, body) == (403, b"")


def test_http_server_errors_have_no_body(tmp_path):
    daemon, _stub, _registry = _single(tmp_path)
    sock = socket.create_connection(("127.0.0.1", daemon.port), timeout=10)
    try:
        sock.sendall(b"HEAD /health HTTP/1.0\r\n\r\n")
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    finally:
        sock.close()
    head, _sep, rest = data.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.0 501") and b"Content-Length: 0" in head
    assert rest == b"" and b"<" not in data


def test_connection_reset_mid_request_is_not_logged(tmp_path):
    daemon, _stub, _registry = _single(tmp_path)
    for _ in range(5):
        sock = socket.create_connection(("127.0.0.1", daemon.port), timeout=10)
        sock.sendall(b"POST /run HTTP/1.0\r\nContent-Length: 1000\r\n\r\nabc")
        time.sleep(0.05)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        sock.close()
    time.sleep(1.0)
    assert "http handler error" not in daemon.log()
    assert ftu.peers(daemon.port)[0] == 200


# --- discovery and liveness (F11, F30-F40, F104, F105; K1, K2, K4) -----------------------

def _log_lines(daemon):
    return [line for line in daemon.log().splitlines() if line.strip()]


def test_t40_beacon_discovery_within_45s_scaled(tmp_path):
    fleet = ftu.Fleet(tmp_path).start()
    ftu.wait_until(fleet.all_see_each_other, 4.5)
    for name in fleet.names:
        assert fleet.view(name)["self"]["discovery"] == "beacon"
    proc = _run_agentd(fleet.homes["alpha"], ["status", "--port", str(fleet.ports["alpha"])])
    lines = proc.stdout.splitlines()
    assert proc.returncode == 0
    assert lines[0] == "daemon: %s (version dev, host_id alpha, discovery beacon)" % fleet.daemons["alpha"].url
    assert lines[1] == "skills: none"
    peer_lines = sorted(line for line in lines if line.startswith("peer "))
    assert len(peer_lines) == 2
    assert peer_lines[0].startswith("peer bravo 127.0.0.1:%d version dev via beacon age " % fleet.ports["bravo"])
    assert peer_lines[0].endswith("s skills researcher=verified")
    assert peer_lines[1].endswith("s skills analyst=verified")
    assert lines[-1] == "update: not installed"


def test_t41_poll_discovery_within_75s_scaled(tmp_path):
    fleet = ftu.Fleet(tmp_path, beacons=False).start()
    ftu.wait_until(lambda: fleet.all_see_each_other(via="poll"), 7.5)
    for name in fleet.names:
        assert fleet.view(name)["self"]["discovery"] == "poll"


def test_t42_killed_host_leaves_within_90s_scaled(tmp_path):
    fleet = ftu.Fleet(tmp_path).start()
    ftu.wait_until(fleet.all_see_each_other, 4.5)
    fleet.daemons["charlie"].kill()
    ftu.wait_until(lambda: "charlie" not in fleet.peer_ids("alpha") + fleet.peer_ids("bravo"), 9.0)
    ftu.wait_until(lambda: "INFO housekeeping peer charlie down" in fleet.daemons["alpha"].log(), 1.0)
    log = fleet.daemons["alpha"].log()
    assert "INFO housekeeping peer bravo live at 127.0.0.1:%d (version dev, via beacon)" % fleet.ports["bravo"] in log


def test_t45_foreign_fleet_is_invisible_and_silent(tmp_path):
    fleet = ftu.Fleet(tmp_path).start()
    ftu.wait_until(fleet.all_see_each_other, 4.5)
    time.sleep(1.0)  # let housekeeping log the live transitions before counting lines
    alpha = fleet.daemons["alpha"]
    before = _log_lines(alpha)
    echo_home = os.path.join(str(tmp_path), "echo")
    os.makedirs(echo_home)
    ftu.make_fleet(echo_home, "echo", ftu.OTHER_FLEET_ID, ftu.OTHER_TOKEN)
    echo_port = ftu.free_port()
    echo_registry = ftu.write_registry(os.path.join(str(tmp_path), "echo-registry.json"), ftu.OTHER_FLEET_ID, {
        "echo": {"port": echo_port, "model_server": {"type": "vllm", "url": "http://127.0.0.1:9/v1"},
                 "model": "m", "skills": ["researcher"]},
        "alpha": {"port": fleet.ports["alpha"], "model_server": {"type": "vllm", "url": "http://127.0.0.1:9/v1"},
                  "model": "m", "skills": []}})
    echo = ftu.start_daemon(echo_home, "echo", echo_registry, ftu.free_port(),
                            ftu.targets(fleet.beacon_ports["alpha"], fleet.beacon_ports["bravo"]))
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        for name in ("alpha", "bravo"):
            assert all(p["port"] != echo_port for p in fleet.view(name)["peers"])
        time.sleep(0.5)
    assert ftu.peers(echo.port)[1]["peers"] == []
    echo.kill()
    assert _log_lines(alpha) == before


def test_t49_model_server_comes_back(tmp_path):
    fleet = ftu.Fleet(tmp_path, names=("alpha", "bravo"), start_stubs=False)
    fleet.start()
    bravo = fleet.daemons["bravo"]
    status, _h, body, _n = ftu.signed(ftu.TEST_KEY, "GET", bravo.port, "/skills")
    assert status == 200 and json.loads(body)["skills"][0]["verified"] is False
    status, _h, body, _n = ftu.signed(ftu.TEST_KEY, "GET", bravo.port, "/health")
    assert status == 200
    ftu.wait_until(lambda: fleet.peer_ids("alpha") == ["bravo"], 4.5)
    ftu.StubModelServer("ollama", "bravo-model", "B", port=fleet.server_ports["bravo"])
    ftu.wait_until(lambda: json.loads(ftu.signed(ftu.TEST_KEY, "GET", bravo.port, "/skills")[2])
                   ["skills"][0]["verified"] is True, 6.0 + 2.0)
    ftu.wait_until(lambda: "INFO prober skill 'researcher' offered: model 'bravo-model' present" in bravo.log(), 1.0)


def test_review_focus_1_own_beacon_echo_is_silent(tmp_path):
    """Review Focus 1: with the production 255.255.255.255 target, every host hears its
    own beacon. It must be dropped silently (it is a replay), never bound as a peer."""
    home = tmp_path / "solo"
    home.mkdir()
    ftu.make_fleet(home, "solo")
    beacon_port = ftu.free_port()
    registry = ftu.write_registry(tmp_path / "registry.json", ftu.TEST_FLEET_ID, {
        "solo": {"port": ftu.free_port(), "model_server": {"type": "vllm", "url": "http://127.0.0.1:9/v1"},
                 "model": "m", "skills": []}})
    solo = ftu.start_daemon(home, "solo", registry, beacon_port, ftu.targets(beacon_port))
    time.sleep(7.0)  # two scaled beacon intervals plus one poll cycle
    view = ftu.peers(solo.port)[1]
    assert view["peers"] == [] and view["self"]["discovery"] == "poll"
    assert len(_log_lines(solo)) == 1 and " started host_id=solo " in solo.log()


def test_unregistered_same_fleet_host_warns_once(tmp_path):
    """F11: a same-fleet daemon whose host_id is not in this registry is ignored, with
    exactly one WARNING however often it beacons."""
    fleet = ftu.Fleet(tmp_path, names=("alpha",))
    fleet.start()
    zulu_home = os.path.join(str(tmp_path), "zulu")
    os.makedirs(zulu_home)
    ftu.make_fleet(zulu_home, "zulu")
    zulu_registry = ftu.write_registry(os.path.join(str(tmp_path), "zulu-registry.json"), ftu.TEST_FLEET_ID, {
        "zulu": {"port": ftu.free_port(), "model_server": {"type": "vllm", "url": "http://127.0.0.1:9/v1"},
                 "model": "m", "skills": []}})
    ftu.start_daemon(zulu_home, "zulu", zulu_registry, ftu.free_port(), ftu.targets(fleet.beacon_ports["alpha"]))
    alpha = fleet.daemons["alpha"]
    ftu.wait_until(lambda: "ignoring unregistered host_id 'zulu' at 127.0.0.1" in alpha.log(), 4.5)
    time.sleep(4.0)
    assert alpha.log().count("ignoring unregistered host_id 'zulu'") == 1
    assert fleet.peer_ids("alpha") == []


# --- POST /run (F47-F54c) ----------------------------------------------------------------

def _run_body(skill, task, request_id="req-1"):
    return json.dumps({"skill": skill, "task": task, "request_id": request_id}).encode("utf-8")


def _signed_run(port, body):
    status, headers, raw, nonce = ftu.signed(ftu.TEST_KEY, "POST", port, "/run", body, timeout=60)
    assert ftu.response_ok(ftu.TEST_KEY, status, "POST", "/run", nonce, headers, raw), status
    return status, raw


def _bravo_with_hook(tmp_path, kind):
    hook = ftu.write_hook(os.path.join(str(tmp_path), "hook-%s" % kind), kind)
    fleet = ftu.Fleet(tmp_path, names=("bravo",), extra_args={"bravo": ["--qwen-agent-bin", hook]}).start()
    return fleet, hook


def test_t48_run_endpoint(tmp_path):
    fleet, hook = _bravo_with_hook(tmp_path, "slow")
    port = fleet.ports["bravo"]
    for body in (b"not json", b"[]", json.dumps({"skill": "researcher", "task": "x"}).encode(),
                 _run_body("researcher", "   "), _run_body("researcher", "x", "bad id!"),
                 json.dumps({"skill": "researcher", "task": 5, "request_id": "r"}).encode(),
                 json.dumps({"skill": "researcher", "task": "x", "request_id": "r", "more": 1}).encode()):
        assert _signed_run(port, body) == (400, b'{"error":"bad request"}'), body
    assert _signed_run(port, _run_body("analyst", "x")) == (400, b'{"error":"skill not served: analyst"}')

    nonce = os.urandom(16).hex()
    headers = fleet_lib.sign_request(ftu.TEST_KEY, "POST", "/run", b"", int(time.time()), nonce)
    assert ftu.raw_request(port, "POST", "/run", headers) == (411, b"")
    headers = dict(headers, **{"Content-Length": str(fleet_lib.MAX_BODY + 1)})
    assert ftu.raw_request(port, "POST", "/run", headers) == (413, b"")
    assert ftu._request(port, "POST", "/run", _run_body("researcher", "x"),
                        {"Content-Type": "application/json"})[0::2] == (401, b"")
    body = _run_body("researcher", "replayed")
    nonce = os.urandom(16).hex()
    headers = fleet_lib.sign_request(ftu.TEST_KEY, "POST", "/run", body, int(time.time()), nonce)
    ftu.release_hook(hook, "replayed")
    assert ftu._request(port, "POST", "/run", body, dict(headers))[0] == 200
    assert ftu._request(port, "POST", "/run", body, dict(headers))[0::2] == (401, b"")

    result = {}
    first = threading.Thread(target=lambda: result.update(first=_signed_run(port, _run_body("researcher", "one"))))
    first.start()
    ftu.wait_until(lambda: json.loads(ftu.signed(ftu.TEST_KEY, "GET", port, "/skills")[2])
                   ["skills"][0]["busy"] is True, 10)
    assert _signed_run(port, _run_body("researcher", "two", "req-2")) == (409, b'{"error":"busy"}')
    ftu.release_hook(hook, "one")
    first.join(30)
    assert result["first"] == (200, ftu.CANNED_LINE.encode("utf-8"))
    assert _signed_run(port, _run_body("researcher", "garbage")) == \
        (502, b'{"error":"skill produced no parseable output (exit code 1)"}')
    log = fleet.daemons["bravo"].log()
    assert "run start skill=researcher request_id=req-1 task_chars=3" in log
    assert "run end skill=researcher request_id=req-1 http=200 status=ok seconds=" in log
    assert "run end skill=researcher request_id=req-1 http=502 status=- seconds=" in log
    assert "one" not in [w for line in log.splitlines() for w in line.split()]
    stderr_path = os.path.join(ftu.daemon_log_dir(fleet.homes["bravo"], "bravo"), "last-run.stderr")
    assert stat.S_IMODE(os.stat(stderr_path).st_mode) == 0o600


# --- POST /delegate (F65-F68, F29j, F106) --------------------------------------------

class _FakePeer(object):
    """An in-process registered peer 'delta' that signs its responses with the fleet key.

    mode "busy": /run answers a signed 409. mode "badsig": /run answers 200 signed with
    a different key.
    """

    def __init__(self, port):
        self.mode = "busy"
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):
                pass

            def _reply(self, status, obj, key=ftu.TEST_KEY):
                raw = fleet_lib.canonical_json(obj)
                headers = fleet_lib.sign_response(key, status, self.command, self.path,
                                                  self.headers.get("X-Fleet-Nonce"), raw,
                                                  int(time.time()), os.urandom(16).hex())
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/health":
                    self._reply(200, {"host_id": "delta", "role": "agent", "version": "dev",
                                      "proto": 1, "discovery": "beacon"})
                else:
                    self._reply(200, {"host_id": "delta", "skills": [
                        {"skill": "researcher", "model": "delta-model", "verified": True, "busy": False}]})

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if outer.mode == "busy":
                    self._reply(409, {"error": "busy"})
                else:
                    self._reply(200, {"schema": "qwen-agent.oneshot.v1", "status": "ok", "answer": "FORGED",
                                      "error": None, "rounds": 1, "tool_calls": []},
                                key=bytes.fromhex(ftu.OTHER_TOKEN))

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_t44_delegate_outcomes_and_failover(tmp_path):
    delta_port = ftu.free_port()
    fleet = ftu.Fleet(tmp_path, extra_hosts={"delta": {
        "port": delta_port, "model_server": {"type": "vllm", "url": "http://127.0.0.1:9/v1"},
        "model": "delta-model", "skills": ["researcher"]}})
    delta = _FakePeer(delta_port)
    try:
        fleet.start()
        alpha_port = fleet.ports["alpha"]
        ftu.wait_until(lambda: "bravo" in fleet.peer_ids("alpha"), 4.5)

        def bind_delta():
            ftu.send_beacon(ftu.TEST_KEY, delta_port, fleet.beacon_ports["alpha"])
            ftu.wait_until(lambda: "delta" in fleet.peer_ids("alpha"), 3.0)

        bind_delta()
        delta.mode = "busy"
        assert ftu.delegate(alpha_port, "researcher", "t", "delta") == \
            (200, {"outcome": "busy", "envelope": None, "detail": ""})
        delta.mode = "badsig"
        bind_delta()
        assert ftu.delegate(alpha_port, "researcher", "t", "delta") == \
            (200, {"outcome": "bad_signature", "envelope": None, "detail": ""})

        alpha_url = fleet.daemons["alpha"].url

        def attempt(host_id):
            return fleet_lib.delegate_once(alpha_url, "researcher", "t", host_id)[:2]

        for mode, outcome in (("busy", "busy"), ("badsig", "bad_signature")):
            delta.mode = mode
            bind_delta()
            result = fleet_lib.failover(["delta", "bravo"], attempt)
            assert result["outcome"] == "ok" and result["host_id"] == "bravo"
            assert result["tried"] == [("delta", outcome)]
            assert result["envelope"]["answer"] == "BRAVO-ANSWER"

        assert ftu.delegate(alpha_port, "researcher", "t", "charlie") == \
            (200, {"outcome": "not_live", "envelope": None, "detail": ""})
        assert ftu.delegate(alpha_port, "researcher", "t", "alpha")[1]["outcome"] == "not_live"
        assert ftu.delegate(alpha_port, "researcher", "t", "nobody")[1]["outcome"] == "not_live"
        for body in (b"[]", b'{"skill": "researcher", "task": "t"}',
                     b'{"skill": "coder", "task": "t", "host_id": "bravo"}',
                     b'{"skill": "researcher", "task": " ", "host_id": "bravo"}',
                     b'{"skill": "researcher", "task": "t", "host_id": "Bravo"}'):
            status, _h, raw = ftu._request(alpha_port, "POST", "/delegate", body,
                                           {"Content-Type": "application/json"})
            assert (status, json.loads(raw)) == (400, {"error": "bad request"}), body
        log = fleet.daemons["alpha"].log()
        assert "delegate skill=researcher host=charlie request_id=- outcome=not_live seconds=" in log
        assert "outcome=bad_signature" in log and "outcome=ok" in log and "FORGED" not in log
    finally:
        delta.close()


def test_review_focus_5_delegate_while_run_lock_held(tmp_path):
    """Review Focus 5: a /run child that delegates goes through its own daemon while that
    daemon holds run_lock. /delegate must not wait on, or answer 409 because of, it."""
    hook = ftu.write_hook(os.path.join(str(tmp_path), "hook-slow"), "slow")
    fleet = ftu.Fleet(tmp_path, names=("bravo", "charlie"),
                      extra_args={"bravo": ["--qwen-agent-bin", hook]}).start()
    ftu.wait_until(lambda: fleet.peer_ids("bravo") == ["charlie"], 4.5)
    held = threading.Thread(target=lambda: ftu.signed(ftu.TEST_KEY, "POST", fleet.ports["bravo"], "/run",
                                                       _run_body("researcher", "hold"), timeout=60))
    held.start()
    ftu.wait_until(lambda: json.loads(ftu.signed(ftu.TEST_KEY, "GET", fleet.ports["bravo"], "/skills")[2])
                   ["skills"][0]["busy"] is True, 10)
    started = time.monotonic()
    status, result = ftu.delegate(fleet.ports["bravo"], "analyst", "check this", "charlie", timeout=60)
    assert status == 200 and result["outcome"] == "ok"
    assert result["envelope"]["answer"] == "CHARLIE-ANSWER"
    assert time.monotonic() - started < 30
    ftu.release_hook(hook, "hold")
    held.join(30)


# --- cross-host round trip through the real harness (K3, K5; F50-F54a, F65-F69, F76, F109) ---

def _harness(fleet, home):
    """Run the real bin/qwen-agent one-shot on alpha's stub, routed through alpha's daemon."""
    env = ftu.clean_env(home, QWEN_AGENT_DAEMON_URL=fleet.daemons["alpha"].url)
    assert not any(k.startswith("SKILL_") for k in env)
    return subprocess.run([sys.executable, ftu.QWEN_AGENT, "--user-prompt=go",
                           "--base-url=%s" % fleet.stubs["alpha"].url, "--model=alpha-model"],
                          env=env, capture_output=True, text=True, timeout=120)


def test_t43_researcher_runs_on_the_peer(tmp_path):
    fleet = ftu.Fleet(tmp_path, stub_kwargs={"alpha": {"delegate_skill": "researcher"}}).start()
    ftu.wait_until(lambda: "bravo" in fleet.peer_ids("alpha"), 4.5)
    home = tmp_path / "caller"
    home.mkdir()
    proc = _harness(fleet, home)
    assert proc.returncode == 0, proc.stderr
    envelope = json.loads(proc.stdout.strip().splitlines()[-1])
    assert envelope["status"] == "ok" and "BRAVO-ANSWER" in envelope["answer"]
    assert "[delegating to researcher on bravo, up to 900s...]" in proc.stderr
    assert any(r.get("reasoning_effort") == "none" for r in fleet.stubs["bravo"].requests)
    assert not any("reasoning_effort" in r for r in fleet.stubs["alpha"].requests)
    bravo_log = fleet.daemons["bravo"].log()
    assert "run start skill=researcher request_id=" in bravo_log
    assert "http=200 status=ok seconds=" in bravo_log
    assert "delegate skill=researcher host=bravo request_id=" in fleet.daemons["alpha"].log()
    assert "outcome=ok seconds=" in fleet.daemons["alpha"].log()


def test_t46_no_secret_leaves_the_daemon(tmp_path):
    hook = ftu.write_hook(os.path.join(str(tmp_path), "hook-envdump"), "envdump")
    sniffer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sniff_port = ftu.free_port()
    sniffer.bind(("127.0.0.1", sniff_port))
    sniffer.settimeout(0.2)
    try:
        fleet = ftu.Fleet(tmp_path, names=("alpha", "bravo"), extra_targets=[sniff_port],
                          stub_kwargs={"alpha": {"delegate_skill": "researcher"}},
                          extra_args={"bravo": ["--qwen-agent-bin", hook]}).start()
        ftu.wait_until(lambda: "bravo" in fleet.peer_ids("alpha"), 4.5)
        home = tmp_path / "caller"
        home.mkdir()
        proc = _harness(fleet, home)
        assert proc.returncode == 0, proc.stderr
        assert "[delegating to researcher on bravo, up to 900s...]" in proc.stderr
        status, delegated = ftu.delegate(fleet.ports["alpha"], "researcher", "again", "bravo")
        assert status == 200 and delegated["outcome"] == "ok", delegated
        bodies = [json.dumps(fleet.view("alpha")).encode(), json.dumps(delegated).encode()]
        datagrams = []
        while True:
            try:
                datagrams.append(sniffer.recvfrom(4096)[0])
            except socket.timeout:
                break
    finally:
        sniffer.close()
    assert datagrams, "the sniffer heard no beacons"
    with open(hook + ".json", encoding="utf-8") as f:
        dumped = json.load(f)
    env = dumped["env"]
    assert not any(k.startswith("QWEN_AGENT_FLEET_") for k in env)
    assert not any(ftu.TEST_TOKEN in v for v in env.values())
    assert env["QWEN_AGENT_DAEMON_URL"] == fleet.daemons["bravo"].url
    bravo_url = "http://127.0.0.1:%d/v1" % fleet.server_ports["bravo"]
    assert dumped["argv"][1:] == ["--skill=researcher", "--user-prompt=again", "--base-url=%s" % bravo_url,
                                  "--model=bravo-model", "--model-server-type=ollama"]
    needles = (ftu.TEST_TOKEN.encode("ascii"), ftu.TEST_KEY,
               fleet_lib.make_join_string(ftu.TEST_FLEET_ID, ftu.TEST_TOKEN).encode("ascii"))
    blobs = list(datagrams) + bodies
    for name in fleet.names:
        log_dir = ftu.daemon_log_dir(fleet.homes[name], name)
        for entry in os.listdir(log_dir):
            with open(os.path.join(log_dir, entry), "rb") as f:
                blobs.append(f.read())
    for blob in blobs:
        for needle in needles:
            assert needle not in blob


# --- multi-agent hosts: run identity, init-fleet/join resolution, status agent (M22, M27, M28, M30, M31) ---

def _identity_registry(tmp_path):
    return ftu.write_registry(tmp_path / "id-registry.json", ftu.TEST_FLEET_ID, {
        "alpha": {"port": ftu.free_port(), "model_server": {"type": "vllm", "url": "http://127.0.0.1:9/v1"},
                  "model": "m", "skills": []}})


def test_mt11_run_identity_errors_before_logging(tmp_path):
    registry = _identity_registry(tmp_path)
    base = ["run", "--registry", registry, "--beacon-targets", "none", "--beacon-port", str(ftu.free_port())]
    empty = tmp_path / "empty"
    empty.mkdir()
    proc = _run_agentd(empty, base)
    assert (proc.returncode, proc.stderr) == (
        2, "qwen-agentd: QWEN_AGENT_HOST_ID is not set; agents on this machine: none\n")
    assert not os.path.lexists(str(empty / "agents"))
    home = tmp_path / "home"
    home.mkdir()
    ftu.make_fleet(home, "alpha")
    proc = _run_agentd(home, base)
    assert (proc.returncode, proc.stderr) == (
        2, "qwen-agentd: QWEN_AGENT_HOST_ID is not set; agents on this machine: alpha\n")
    proc = _run_agentd(home, base, {"QWEN_AGENT_HOST_ID": "Bad_Id"})
    assert (proc.returncode, proc.stderr) == (2, "qwen-agentd: invalid QWEN_AGENT_HOST_ID 'Bad_Id'\n")
    charlie = home / "agents" / "charlie"
    proc = _run_agentd(home, base, {"QWEN_AGENT_HOST_ID": "charlie"})
    assert (proc.returncode, proc.stderr) == (
        2, "qwen-agentd: %s not found; run qwen-agentd init-fleet --agent-id charlie or "
           "qwen-agentd join --agent-id charlie\n" % (charlie / "fleet.env"))
    assert not os.path.lexists(str(charlie))
    ftu.make_fleet(home, "charlie")
    proc = _run_agentd(home, base, {"QWEN_AGENT_HOST_ID": "charlie"})
    message = "qwen-agentd: host_id 'charlie' is not in the fleet registry; valid IDs: alpha"
    assert (proc.returncode, proc.stderr) == (2, message + "\n")
    assert "ERROR MainThread " + message in ftu.read_log(home, "charlie")


def test_multi_agent_focus_3_host_id_with_stray_whitespace_is_rejected(tmp_path):
    """Multi-agent Review Focus 3: QWEN_AGENT_HOST_ID with a stray space or newline (a plist, unit or
    shell typo) is refused by name, and nothing is created under ~/agents."""
    registry = _identity_registry(tmp_path)
    base = ["run", "--registry", registry, "--beacon-targets", "none", "--beacon-port", str(ftu.free_port())]
    home = tmp_path / "home"
    home.mkdir()
    ftu.make_fleet(home, "alpha")
    for value in ("alpha ", "alpha\n", " alpha"):
        proc = _run_agentd(home, base, {"QWEN_AGENT_HOST_ID": value})
        assert (proc.returncode, proc.stderr) == (2, "qwen-agentd: invalid QWEN_AGENT_HOST_ID '%s'\n" % value)
    assert os.listdir(str(home / "agents")) == ["alpha"]
    assert os.listdir(str(home / "agents" / "alpha")) == ["fleet.env"]


def test_mt13_init_fleet_and_join_resolve_the_agent(agentd, capsys, monkeypatch, tmp_path):
    agents = tmp_path / "home" / "agents"
    assert agentd.main(["init-fleet"]) == 2
    assert capsys.readouterr() == ("", "qwen-agentd: no agent found in %s; pass --agent-id ID\n" % agents)
    assert agentd.main(["init-fleet", "--agent-id", "alpha"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 4 and out[0].startswith("fleet_id: ")
    assert stat.S_IMODE(os.stat(str(agents / "alpha")).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(fleet_lib.fleet_env_path("alpha")).st_mode) == 0o600
    assert agentd.main(["init-fleet"]) == 2
    assert capsys.readouterr().err == ("qwen-agentd: %s already exists; remove it first to create a new fleet\n"
                                       % fleet_lib.fleet_env_path("alpha"))
    ftu.make_fleet(tmp_path / "home", "bravo")

    def no_prompt(prompt):
        raise AssertionError("join prompted for the secret")
    monkeypatch.setattr(agentd.getpass, "getpass", no_prompt)
    assert agentd.main(["join"]) == 2
    assert capsys.readouterr() == (
        "", "qwen-agentd: more than one agent in %s (alpha, bravo); pass --agent-id ID\n" % agents)
    s = fleet_lib.make_join_string(ftu.TEST_FLEET_ID, ftu.TEST_TOKEN)
    assert agentd.main(["join", "--host-id", "erin", s]) == 0
    assert capsys.readouterr() == ("qwen-agentd: joined fleet %s\n" % ftu.TEST_FLEET_ID, "")
    assert fleet_lib.load_fleet_env(fleet_lib.fleet_env_path("erin")) == (ftu.TEST_FLEET_ID, ftu.TEST_TOKEN)


def test_multi_agent_focus_4_mistyped_agent_id_never_prompts(agentd, capsys, monkeypatch, tmp_path):
    """Multi-agent Review Focus 4: a mistyped --agent-id (an upper-case letter, a path) on join or
    init-fleet is refused before the hidden prompt asks for the secret, and nothing is
    created under ~/agents."""
    prompts = []
    monkeypatch.setattr(agentd.getpass, "getpass", lambda prompt: prompts.append(prompt) or "")
    for bad in ("Mac-Local", "../mac-local", "mac-local/x"):
        for argv in (["join", "--agent-id", bad], ["init-fleet", "--agent-id", bad]):
            assert agentd.main(argv) == 2
            assert capsys.readouterr() == ("", "qwen-agentd: invalid --agent-id '%s'\n" % bad)
    assert prompts == []
    assert not os.path.lexists(str(tmp_path / "home" / "agents"))
    assert not os.path.lexists(str(tmp_path / "mac-local"))


def test_mt12_status_update_line_agent(tmp_path):
    daemon, _stub, _registry = _single(tmp_path)
    ftu.make_fleet(daemon.home, "bravo")
    proc = _run_agentd(daemon.home, ["status", "--port", str(daemon.port)])
    assert proc.returncode == 0 and proc.stdout.splitlines()[-1] == "update: not installed"
    fleet_lib.write_state(os.path.join(str(daemon.home), "agents", "alpha", "update-state.json"),
                          {"from": None, "to": "v2026.01.01", "status": "ok", "attempts": 0, "bad_tags": []})
    installed = "update: status=ok from=- to=v2026.01.01 attempts=0 bad_tags=-"
    proc = _run_agentd(daemon.home, ["status", "--port", str(daemon.port)])
    assert proc.returncode == 0 and proc.stdout.splitlines()[-1] == installed
    proc = _run_agentd(daemon.home, ["status", "--agent-id", "alpha", "--port", str(daemon.port)])
    assert proc.returncode == 0 and proc.stdout.splitlines()[-1] == installed
    proc = _run_agentd(daemon.home, ["status", "--agent-id", "Bad", "--port", str(daemon.port)])
    assert (proc.returncode, proc.stdout, proc.stderr) == (2, "", "qwen-agentd: invalid --agent-id 'Bad'\n")
    daemon.kill()
    proc = _run_agentd(daemon.home, ["status", "--port", str(daemon.port)])
    assert proc.returncode == 1
    assert proc.stdout == "daemon: not reachable at %s\nupdate: not installed\n" % daemon.url


# --- multi-agent hosts: join --from-agent (M29, M36) -------------------------------------

def _no_token_in(token, *texts):
    """True when no text contains the token or any 16-character substring of it."""
    pieces = [token[i:i + 16] for i in range(len(token) - 15)]
    return not any(p in t for t in texts for p in pieces)


def test_mt13_join_from_agent(agentd, capsys, monkeypatch, tmp_path):
    def no_prompt(prompt):
        raise AssertionError("join prompted for the secret")
    monkeypatch.setattr(agentd.getpass, "getpass", no_prompt)
    assert agentd.main(["init-fleet", "--agent-id", "alpha"]) == 0
    capsys.readouterr()
    fid, token = fleet_lib.load_fleet_env(fleet_lib.fleet_env_path("alpha"))
    assert agentd.main(["join", "--agent-id", "bravo", "--from-agent", "alpha"]) == 0
    out, err = capsys.readouterr()
    assert (out, err) == ("qwen-agentd: joined fleet %s (copied from agent alpha)\n" % fid, "")
    assert _no_token_in(token, out, err)
    bravo = fleet_lib.fleet_env_path("bravo")
    with open(fleet_lib.fleet_env_path("alpha"), "rb") as fa, open(bravo, "rb") as fb:
        assert fa.read() == fb.read()
    assert stat.S_IMODE(os.stat(bravo).st_mode) == 0o600
    assert not os.path.lexists(bravo + ".tmp")
    assert agentd.main(["join", "--agent-id", "bravo", "--from-agent", "alpha"]) == 0
    assert capsys.readouterr() == ("qwen-agentd: already joined fleet %s\n" % fid, "")
    s = fleet_lib.make_join_string(fid, token)
    for argv, message in (
            (["--agent-id", "alpha", "--from-agent", "alpha"], "qwen-agentd: --from-agent names agent 'alpha' itself"),
            (["--agent-id", "carol", "--from-agent", "dave"],
             "qwen-agentd: %s not found; agent 'dave' has not joined a fleet" % fleet_lib.fleet_env_path("dave")),
            (["--agent-id", "carol", "--from-agent", "Bad_Id"], "qwen-agentd: invalid --from-agent 'Bad_Id'"),
            (["--agent-id", "carol", "--from-agent", "alpha", s],
             "qwen-agentd: join takes STRING or --from-agent, not both")):
        assert agentd.main(["join"] + argv) == 2, argv
        out, err = capsys.readouterr()
        assert (out, err) == ("", message + "\n"), argv
        assert _no_token_in(token, out, err)
    assert not os.path.lexists(fleet_lib.deploy_root("carol"))
    os.unlink(bravo)
    fleet_lib.write_fleet_env(bravo, ftu.OTHER_FLEET_ID, ftu.OTHER_TOKEN)
    assert agentd.main(["join", "--agent-id", "bravo", "--from-agent", "alpha"]) == 2
    assert capsys.readouterr() == ("", "qwen-agentd: %s exists for a different fleet; remove it first\n" % bravo)
    assert fleet_lib.load_fleet_env(bravo) == (ftu.OTHER_FLEET_ID, ftu.OTHER_TOKEN)


def test_multi_agent_focus_5_from_agent_with_a_loose_secret_file(agentd, capsys, tmp_path):
    """Multi-agent Review Focus 5: the source agent's fleet.env was copied around and is now mode 0644.
    join --from-agent refuses with F21's chmod hint, writes nothing for the target agent,
    and prints no part of the token."""
    assert agentd.main(["init-fleet", "--agent-id", "alpha"]) == 0
    capsys.readouterr()
    source = fleet_lib.fleet_env_path("alpha")
    _fid, token = fleet_lib.load_fleet_env(source)
    os.chmod(source, 0o644)
    assert agentd.main(["join", "--agent-id", "bravo", "--from-agent", "alpha"]) == 2
    out, err = capsys.readouterr()
    assert (out, err) == ("", "qwen-agentd: %s must be mode 0600 (chmod 600 %s)\n" % (source, source))
    assert _no_token_in(token, out, err)
    assert not os.path.lexists(fleet_lib.deploy_root("bravo"))
