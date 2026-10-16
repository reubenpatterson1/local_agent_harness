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
    assert agentd.main(["init-fleet"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 4
    assert out[0].startswith("fleet_id: ")
    fleet_id = out[0][len("fleet_id: "):]
    assert fleet_lib.FLEET_ID_RE.fullmatch(fleet_id)
    assert out[1] == "join string (shown once; copy it to each other host over ssh):"
    assert out[3] == ("next: create fleets/%s.json (see the fleet spec, Section 2.4), commit, "
                      "tag a release" % fleet_id)
    path = fleet_lib.fleet_env_path()
    assert fleet_lib.parse_join_string(out[2]) == fleet_lib.load_fleet_env(path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert agentd.main(["init-fleet"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ("qwen-agentd: %s already exists; remove it first to create a new fleet\n" % path)


def test_cli_join(agentd, capsys, monkeypatch):
    s = fleet_lib.make_join_string(ftu.TEST_FLEET_ID, ftu.TEST_TOKEN)
    assert agentd.main(["join", "not-a-join-string"]) == 2
    assert capsys.readouterr().err == "qwen-agentd: invalid join string\n"
    prompts = []
    monkeypatch.setattr(agentd.getpass, "getpass", lambda prompt: prompts.append(prompt) or s + "\n")
    assert agentd.main(["join"]) == 0
    assert prompts == ["join string: "]
    assert capsys.readouterr().out == "qwen-agentd: joined fleet %s\n" % ftu.TEST_FLEET_ID
    path = fleet_lib.fleet_env_path()
    assert fleet_lib.load_fleet_env(path) == (ftu.TEST_FLEET_ID, ftu.TEST_TOKEN)
    assert agentd.main(["join", s]) == 0
    assert capsys.readouterr().out == "qwen-agentd: already joined fleet %s\n" % ftu.TEST_FLEET_ID
    other = fleet_lib.make_join_string(ftu.OTHER_FLEET_ID, ftu.OTHER_TOKEN)
    assert agentd.main(["join", other]) == 2
    assert capsys.readouterr().err == ("qwen-agentd: %s exists for a different fleet; remove it first\n" % path)


def test_cli_internal_error_is_one_line(agentd, capsys, monkeypatch):
    def boom(*args):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(agentd.fleet_lib, "write_fleet_env", boom)
    assert agentd.main(["init-fleet"]) == 1
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
    ftu.make_fleet(home)
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
    log_dir = ftu.daemon_log_dir(daemon.home)
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
    env_path = os.path.join(str(home), ".config", "qwen-agent", "fleet.env")

    proc = _run_agentd(home, base, {"QWEN_AGENT_HOST_ID": "alpha"})
    assert proc.returncode == 2
    assert proc.stderr == ("qwen-agentd: %s not found; run qwen-agentd init-fleet or qwen-agentd join\n"
                           % env_path)
    ftu.make_fleet(home)

    proc = _run_agentd(home, base)
    assert proc.returncode == 2
    assert proc.stderr == "qwen-agentd: QWEN_AGENT_HOST_ID is not set; valid IDs: alpha, bravo\n"

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
    proc = _run_agentd(home, base, {"QWEN_AGENT_HOST_ID": "alpha"})
    assert proc.returncode == 2
    assert proc.stderr == ("qwen-agentd: TCP port %d is already in use (is another qwen-agentd running?)\n"
                           % port)
    proc = _run_agentd(home, ["run", "--registry", registry, "--beacon-targets", "none",
                              "--beacon-port", str(first.beacon_port)], {"QWEN_AGENT_HOST_ID": "bravo"})
    assert (proc.returncode, proc.stderr) == (2, "qwen-agentd: UDP port %d is already in use\n" % first.beacon_port)
    assert "Traceback" not in first.log()
    assert "ERROR MainThread qwen-agentd: QWEN_AGENT_HOST_ID is not set" in ftu.read_log(home)


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
