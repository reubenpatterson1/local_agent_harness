"""Self-update tests: install, staging, the gate, switch and rollback (fleet spec 11.6, D9).

Run from the workspace root: python3 -m pytest tests/test_fleet_self_update.py -v
Each test builds its own local bare origin repo from copies of this workspace's
fleet files, installs into HOME=<tmp>/home with --no-service, and (from Task 18 on)
runs a test supervisor that emulates launchd/systemd at --timing-scale 0.01. No
network, no real service, no real user state.

The fleet token here is random per test (secrets.token_hex), never the literal
test token: the gate's selftest runs T25 against HOME's fleet.env, and the literal
test token is written in tests/fleet_testutil.py and tests/test_fleet_lib.py,
which every fixture release contains.
"""

import json
import os
import plistlib
import secrets
import shutil
import signal
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

RELEASE_FILES = ("fleet_lib.py", "bin/qwen-agent", "bin/qwen-agentd", "bin/qwen-agentd-launch",
                 "tests/test_fleet_lib.py", "tests/fleet_testutil.py")


@pytest.fixture(autouse=True)
def _reap_processes():
    yield
    ftu.kill_all()


def _git(cwd, *args):
    env = dict(os.environ, HOME=str(cwd), GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
               GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.invalid")
    subprocess.run(["git"] + list(args), cwd=str(cwd), env=env, check=True, capture_output=True)


class Origin(object):
    """A source checkout plus a bare origin; each release is a commit + tag pushed to origin."""

    def __init__(self, root, registry):
        self.root = str(root)
        self.src = os.path.join(self.root, "src")
        self.bare = os.path.join(self.root, "origin.git")
        os.makedirs(self.src)
        _git(self.root, "init", "-q", "--bare", "--initial-branch=main", self.bare)
        _git(self.src, "init", "-q")
        ws = os.path.join(self.src, fleet_lib.WS_SUBDIR)
        for rel in RELEASE_FILES:
            dest = os.path.join(ws, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(os.path.join(WS, rel), dest)
        self.registry_rel = os.path.join("fleets", ftu.TEST_FLEET_ID + ".json")
        self.write(self.registry_rel, json.dumps(registry, indent=2))
        self.write("docs/RELEASE.md", "first\n")
        _git(self.src, "add", "-A")
        _git(self.src, "commit", "-q", "-m", "base")
        self.base = True

    def write(self, rel, text):
        path = os.path.join(self.src, fleet_lib.WS_SUBDIR, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def append(self, rel, text):
        path = os.path.join(self.src, fleet_lib.WS_SUBDIR, rel)
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)

    def release(self, tag, parent=None, change=None):
        """Tag a release: the current commit when it is the first, else a new commit on
        `parent` (a tag; default: the current HEAD) changed by change(origin)."""
        if not self.base:
            if parent is not None:
                _git(self.src, "checkout", "-q", "--detach", parent)
            if change is None:
                self.write("docs/RELEASE.md", "release %s\n" % tag)
            else:
                change(self)
        self.base = False
        _git(self.src, "add", "-A")
        _git(self.src, "commit", "-q", "--allow-empty", "-m", tag)
        _git(self.src, "tag", tag)
        # The branch matters: `git fetch origin --tags` in a bare clone with no fetch
        # refspec also fetches the remote HEAD, and fails if origin has no branch.
        _git(self.src, "push", "-q", "--force", self.bare, "HEAD:refs/heads/main", "refs/tags/%s" % tag)


def _registry(port, skills=(), server_url=None):
    return {"protocol": 1, "fleet_id": ftu.TEST_FLEET_ID, "hosts": {"h1": {
        "role": "agent", "address": "127.0.0.1", "port": port,
        "model_server": {"type": "vllm", "url": server_url or "http://127.0.0.1:%d/v1" % ftu.free_port()},
        "model": "h1-model", "skills": list(skills)}}}


def _install(home, origin):
    return subprocess.run([sys.executable, ftu.AGENTD, "install", "--host-id", "h1", "--origin", origin.bare,
                           "--no-service"], env=ftu.clean_env(home), capture_output=True, text=True, timeout=300)


def _deploy(home):
    return os.path.join(str(home), "agents", "h1")


def test_t61_install_layout_and_idempotence(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    port = ftu.free_port()
    origin = Origin(tmp_path / "o", _registry(port))
    proc = _install(home, origin)
    assert proc.returncode == 2
    assert proc.stderr == ("qwen-agentd: no release tags (vYYYY.MM.DD[.N]) at %s; tag a release first\n"
                           % origin.bare)
    origin.release("v2026.01.01")
    proc = _install(home, origin)
    assert proc.returncode == 0, proc.stderr
    d = _deploy(home)
    bindir = os.path.join(str(home), ".local", "bin")
    lines = ("installed v2026.01.01 at %s\n" % d
             + "command: %s/qwen-agent-h1 (daemon port %d)\n" % (bindir, port)
             + "default: %s/qwen-agent runs agent h1\n" % bindir)
    assert proc.stdout == lines + ("next: run %s/current/qwen-agent-workspace/bin/qwen-agentd join --agent-id h1 "
                                   "(or init-fleet --agent-id h1); the service retries every 10 s\n" % d)
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(os.path.join(d, "qwen-agentd-launch")).st_mode) == 0o755
    assert stat.S_IMODE(os.stat(os.path.join(d, "update-state.json")).st_mode) == 0o600
    assert os.readlink(os.path.join(d, "current")) == "releases/v2026.01.01"
    assert os.path.isdir(os.path.join(d, "repo", "refs"))
    monkeypatch.setenv("HOME", str(home))
    wrapper = fleet_lib.wrapper_bytes("h1", port)
    for name in ("qwen-agent", "qwen-agent-h1"):
        path = os.path.join(bindir, name)
        assert os.path.isfile(path) and not os.path.islink(path)
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o755
        with open(path, "rb") as f:
            assert f.read() == wrapper
    target = os.path.join(d, "current", "qwen-agent-workspace", "bin", "qwen-agent")
    assert wrapper.decode("utf-8").splitlines()[-1] == "exec '%s' \"$@\"" % target
    assert os.path.realpath(target) == os.path.realpath(
        os.path.join(d, "releases", "v2026.01.01", "qwen-agent-workspace", "bin", "qwen-agent"))
    state = fleet_lib.read_state(os.path.join(d, "update-state.json"))
    assert state == {"from": None, "to": "v2026.01.01", "status": "ok", "attempts": 0, "bad_tags": []}
    assert os.path.exists(os.path.join(ftu.daemon_log_dir(home, "h1"), "gate-v2026.01.01.log"))
    assert not os.path.exists(os.path.join(str(home), "Library", "LaunchAgents"))
    assert not os.path.exists(os.path.join(str(home), ".config", "systemd"))
    origin.release("v2026.01.02")
    ftu.make_fleet(home, "h1", ftu.TEST_FLEET_ID, secrets.token_hex(32))
    proc = _install(home, origin)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == lines
    assert os.readlink(os.path.join(d, "current")) == "releases/v2026.01.01"
    assert fleet_lib.read_state(os.path.join(d, "update-state.json")) == state


def test_install_rejects_bad_host_id_and_failing_first_release(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    proc = subprocess.run([sys.executable, ftu.AGENTD, "install", "--host-id", "Mac_Local", "--no-service"],
                          env=ftu.clean_env(home), capture_output=True, text=True, timeout=60)
    assert (proc.returncode, proc.stderr) == (2, "qwen-agentd: invalid --agent-id 'Mac_Local'\n")
    origin = Origin(tmp_path / "o", _registry(ftu.free_port()))
    origin.append("tests/test_fleet_lib.py", "\n\ndef test_gate_must_fail():\n    assert False\n")
    origin.release("v2026.01.01")
    proc = _install(home, origin)
    assert proc.returncode == 2
    assert proc.stderr == ("qwen-agentd: first release v2026.01.01 failed its gate (selftest exit 1); see %s\n"
                           % os.path.join(ftu.daemon_log_dir(home, "h1"), "gate-v2026.01.01.log"))
    assert not os.path.lexists(os.path.join(_deploy(home), "current"))


def test_service_definitions():
    agentd = ftu.load_script("qwen_agentd_services", ftu.AGENTD)
    plist = agentd.launchd_plist_dict("/usr/bin/python3", "/h/agents/mac-local", "mac-local",
                                      "/h/agents/mac-local/logs")
    assert plist == {
        "Label": "com.qwen-agent.qwen-agentd.mac-local",
        "ProgramArguments": ["/usr/bin/python3", "/h/agents/mac-local/qwen-agentd-launch"],
        "EnvironmentVariables": {"QWEN_AGENT_HOST_ID": "mac-local",
                                 "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
        "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10,
        "StandardOutPath": "/h/agents/mac-local/logs/launchd.out",
        "StandardErrorPath": "/h/agents/mac-local/logs/launchd.err"}
    assert plistlib.loads(plistlib.dumps(plist)) == plist
    assert agentd.systemd_unit_text("/usr/bin/python3", "/home/u/agents/ollama-168", "ollama-168") == (
        "[Unit]\nDescription=qwen-agent fleet daemon\nStartLimitIntervalSec=0\n\n"
        "[Service]\nExecStart=/usr/bin/python3 /home/u/agents/ollama-168/qwen-agentd-launch\n"
        "Environment=QWEN_AGENT_HOST_ID=ollama-168\nRestart=always\nRestartSec=10\n\n"
        "[Install]\nWantedBy=default.target\n")


def test_mt23_install_service_is_per_agent(tmp_path, monkeypatch):
    """MT23: two agents in one HOME get two plists or two units, each loaded under its own name.
    subprocess.run is recorded, so no real launchctl or systemctl ever runs."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    agentd = ftu.load_script("qwen_agentd_mt23", ftu.AGENTD)
    calls = []

    def record(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(agentd.subprocess, "run", record)
    py = "/usr/bin/python3"
    monkeypatch.setattr(agentd.sys, "platform", "darwin")
    domain = "gui/%d" % os.getuid()
    expected = []
    for x in ("a", "b"):
        ok, path = agentd.install_service(py, fleet_lib.deploy_root(x), x)
        assert ok and path == os.path.join(str(home), "Library", "LaunchAgents",
                                           "com.qwen-agent.qwen-agentd.%s.plist" % x)
        with open(path, "rb") as f:
            plist = plistlib.loads(f.read())
        assert plist["Label"] == "com.qwen-agent.qwen-agentd." + x
        assert plist["EnvironmentVariables"]["QWEN_AGENT_HOST_ID"] == x
        assert plist["StandardErrorPath"] == os.path.join(fleet_lib.log_dir(x), "launchd.err")
        expected += [["launchctl", "bootout", "%s/com.qwen-agent.qwen-agentd.%s" % (domain, x)],
                     ["launchctl", "bootstrap", domain, path]]
    assert calls == expected
    del calls[:]
    monkeypatch.setattr(agentd.sys, "platform", "linux")
    expected = []
    for x in ("a", "b"):
        ok, path = agentd.install_service(py, fleet_lib.deploy_root(x), x)
        unit = "qwen-agentd-%s.service" % x
        assert ok and path == os.path.join(str(home), ".config", "systemd", "user", unit)
        with open(path, encoding="utf-8") as f:
            assert f.read() == agentd.systemd_unit_text(py, fleet_lib.deploy_root(x), x)
        expected += [["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", unit],
                     ["systemctl", "--user", "restart", unit]]
    assert calls == expected


def test_linger_check(monkeypatch):
    agentd = ftu.load_script("qwen_agentd_linger", ftu.AGENTD)
    outputs = {"yes": "Linger=yes\n", "no": "Linger=no\n"}
    for key, expected in (("yes", True), ("no", False)):
        monkeypatch.setattr(agentd.subprocess, "run",
                            lambda *a, **k: subprocess.CompletedProcess(a[0], 0, outputs[key], ""))
        assert agentd.linger_enabled("u") is expected

    def missing(*a, **k):
        raise FileNotFoundError("loginctl")
    monkeypatch.setattr(agentd.subprocess, "run", missing)
    assert agentd.linger_enabled("u") is False


def test_stage_recovers_from_interrupted_worktree_add(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    origin = Origin(tmp_path / "o", _registry(ftu.free_port()))
    origin.release("v2026.01.01")
    assert _install(home, origin).returncode == 0
    origin.release("v2026.01.02")
    d = _deploy(home)
    repo = os.path.join(d, "repo")
    _git(repo, "fetch", "-q", "origin", "--tags")
    agentd = ftu.load_script("qwen_agentd_stage", ftu.AGENTD)
    lines = []
    log = lambda level, msg: lines.append((level, msg))
    path = os.path.join(d, "releases", "v2026.01.02")
    # (a) locked registration, directory present (a killed `worktree add`)
    _git(repo, "worktree", "add", "-q", "--detach", "--lock", path, "refs/tags/v2026.01.02")
    assert agentd.stage_release(d, "v2026.01.02", log) == (True, "")
    # (b) unlocked registration whose directory is gone
    shutil.rmtree(path)
    assert agentd.stage_release(d, "v2026.01.02", log) == (True, "")
    # (c) locked registration whose directory is gone
    _git(repo, "worktree", "lock", path)
    shutil.rmtree(path)
    assert agentd.stage_release(d, "v2026.01.02", log) == (True, "")
    assert os.path.isfile(os.path.join(path, fleet_lib.WS_SUBDIR, "bin", "qwen-agentd"))
    assert lines == []


# --- T60, T62, T63: switch, gate failure, crash rollback, dirty tree, busy host (F84-F89, F102) ---

UPDATE_PERIOD = (fleet_lib.UPDATE_INTERVAL + fleet_lib.UPDATE_JITTER) * float(ftu.SELF_UPDATE_SCALE)


class Supervisor(object):
    """Emulates launchd/systemd: run D/qwen-agentd-launch, restart it 0.2 s after each exit."""

    def __init__(self, home, extra_args=()):
        self.home = str(home)
        self.d = _deploy(home)
        self.beacon_port = ftu.free_port()
        self.extra_args = list(extra_args)
        self.pids = []
        self.proc = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        env = ftu.clean_env(self.home, QWEN_AGENT_HOST_ID="h1")
        while not self._stop.is_set():
            argv = [sys.executable, os.path.join(self.d, "qwen-agentd-launch"), "--beacon-targets", "none",
                    "--beacon-port", str(self.beacon_port), "--timing-scale", ftu.SELF_UPDATE_SCALE] + self.extra_args
            self.proc = ftu.spawn(argv, env, self.home)
            self.pids.append(self.proc.pid)
            self.proc.wait()
            if self._stop.wait(0.2):
                return

    def close(self):
        self._stop.set()
        if self.proc is not None:
            ftu._kill(self.proc)
        self._thread.join(5)


def _setup(tmp_path, skills=(), server_url=None):
    """Origin with v2026.01.01, installed, fleet.env with a random token -> (origin, home, key, port)."""
    home = tmp_path / "home"
    home.mkdir()
    port = ftu.free_port()
    origin = Origin(tmp_path / "o", _registry(port, skills, server_url))
    origin.release("v2026.01.01")
    proc = _install(home, origin)
    assert proc.returncode == 0, proc.stderr
    token = secrets.token_hex(32)
    ftu.make_fleet(home, "h1", ftu.TEST_FLEET_ID, token)
    return origin, home, bytes.fromhex(token), port


def _version(key, port):
    status, _headers, body, _nonce = ftu.signed(key, "GET", port, "/health", timeout=5)
    return json.loads(body)["version"] if status == 200 else None


def _state(home):
    return fleet_lib.read_state(os.path.join(_deploy(home), "update-state.json"))


def test_t60_switch_gate_failure_and_crash_rollback(tmp_path):
    origin, home, key, port = _setup(tmp_path)
    sup = Supervisor(home)
    try:
        ftu.wait_until(lambda: _version(key, port) == "v2026.01.01", 20)
        # (1) a good release: exec in place, then the self-check marks it ok.
        origin.release("v2026.01.02")
        ftu.wait_until(lambda: _version(key, port) == "v2026.01.02" and _state(home)["status"] == "ok", 60)
        state = _state(home)
        assert (state["from"], state["to"]) == ("v2026.01.01", "v2026.01.02")
        assert len(sup.pids) == 1
        status = subprocess.run([sys.executable, ftu.AGENTD, "status", "--port", str(port)],
                                env=ftu.clean_env(home), capture_output=True, text=True, timeout=30)
        assert status.stdout.splitlines()[0].startswith("daemon: http://127.0.0.1:%d (version v2026.01.02, "
                                                        "host_id h1, discovery poll)" % port)
        assert status.stdout.splitlines()[-1] == ("update: status=ok from=v2026.01.01 to=v2026.01.02 "
                                                  "attempts=0 bad_tags=-")
        # (2) a release whose own unit tests fail: marked bad, unstaged, never switched to.
        origin.release("v2026.01.03", parent="v2026.01.02", change=lambda o: o.append(
            "tests/test_fleet_lib.py", "\n\ndef test_gate_must_fail():\n    assert False\n"))
        ftu.wait_until(lambda: "v2026.01.03" in _state(home)["bad_tags"], 60)
        assert _version(key, port) == "v2026.01.02"
        assert not os.path.exists(os.path.join(_deploy(home), "releases", "v2026.01.03"))
        # (3) a release that passes the gate but cannot start (registry {}): rolled back.
        origin.release("v2026.01.04", parent="v2026.01.02",
                       change=lambda o: o.write(o.registry_rel, "{}"))
        ftu.wait_until(lambda: _state(home)["status"] == "rolled_back", 90)
        state = _state(home)
        assert state["to"] == "v2026.01.04"
        assert set(state["bad_tags"]) >= {"v2026.01.03", "v2026.01.04"}
        assert os.readlink(os.path.join(_deploy(home), "current")) == "releases/v2026.01.02"
        ftu.wait_until(lambda: _version(key, port) == "v2026.01.02", 20)
        log = ftu.read_log(home, "h1")
        assert "update: switching v2026.01.01 -> v2026.01.02" in log
        assert "update: now running v2026.01.02 (from v2026.01.01)" in log
        assert "update: v2026.01.03 failed its gate (selftest exit 1); marked bad" in log
    finally:
        sup.close()


def test_t62_dirty_tree_blocks_the_update(tmp_path):
    origin, home, key, port = _setup(tmp_path)
    sup = Supervisor(home)
    try:
        ftu.wait_until(lambda: _version(key, port) == "v2026.01.01", 20)
        doc = os.path.join(_deploy(home), "current", "qwen-agent-workspace", "docs", "RELEASE.md")
        with open(doc, "a") as f:
            f.write("local edit\n")
        origin.release("v2026.01.02")
        time.sleep(3 * UPDATE_PERIOD)
        assert _version(key, port) == "v2026.01.01"
        assert ("WARNING updater update: v2026.01.02 available but the current release has modified "
                "tracked files; not updating") in ftu.read_log(home, "h1")
        subprocess.run(["git", "-C", os.path.join(_deploy(home), "current"), "checkout", "--", "."],
                       check=True, capture_output=True, env=ftu.clean_env(home))
        ftu.wait_until(lambda: _version(key, port) == "v2026.01.02", 2 * UPDATE_PERIOD + 10)
    finally:
        sup.close()


def test_t63_update_waits_for_an_in_flight_run(tmp_path):
    stub = ftu.StubModelServer("vllm", "h1-model", "unused")
    hook = ftu.write_hook(os.path.join(str(tmp_path), "hook-slow"), "slow")
    origin, home, key, port = _setup(tmp_path, skills=("planner",), server_url=stub.url)
    sup = Supervisor(home, extra_args=["--qwen-agent-bin", hook])
    try:
        ftu.wait_until(lambda: _version(key, port) == "v2026.01.01", 20)
        body = json.dumps({"skill": "planner", "task": "hold", "request_id": "r1"}).encode()
        result = {}
        held = threading.Thread(target=lambda: result.update(
            run=ftu.signed(key, "POST", port, "/run", body, timeout=300)[0]))
        held.start()
        ftu.wait_until(lambda: json.loads(ftu.signed(key, "GET", port, "/skills")[2])["skills"][0]["busy"], 10)
        origin.release("v2026.01.02")
        time.sleep(3 * UPDATE_PERIOD)
        assert _version(key, port) == "v2026.01.01"
        assert "INFO updater update: v2026.01.02 deferred: a run is in flight" in ftu.read_log(home, "h1")
        ftu.release_hook(hook, "hold")
        held.join(30)
        assert result["run"] == 200
        ftu.wait_until(lambda: _version(key, port) == "v2026.01.02", 2 * UPDATE_PERIOD + 10)
    finally:
        sup.close()


# --- multi-agent hosts: install per agent, the generated commands (M3, M11-M13, M24-M26) ---

def _agentd(home, *args):
    return subprocess.run([sys.executable, ftu.AGENTD] + list(args), env=ftu.clean_env(home),
                          capture_output=True, text=True, timeout=300)


def _install_agent(home, origin, host_id, *extra):
    return _agentd(home, "install", "--agent-id", host_id, "--origin", origin.bare, "--no-service", *extra)


def _two_agent_origin(tmp_path):
    """Origin whose registry lists h1 and h2 on their own free ports, tagged v2026.01.01."""
    home = tmp_path / "home"
    home.mkdir()
    p1, p2 = ftu.free_port(), ftu.free_port()
    registry = _registry(p1)
    registry["hosts"]["h2"] = dict(registry["hosts"]["h1"], port=p2, model="h2-model")
    origin = Origin(tmp_path / "o", registry)
    origin.release("v2026.01.01")
    return home, origin, p1, p2


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _paths(home):
    """(qwen-agent-h1, qwen-agent-h2, qwen-agent) under <home>/.local/bin."""
    bindir = os.path.join(str(home), ".local", "bin")
    return (os.path.join(bindir, "qwen-agent-h1"), os.path.join(bindir, "qwen-agent-h2"),
            os.path.join(bindir, "qwen-agent"))


def test_mt20_two_agents_one_home(tmp_path, monkeypatch):
    home, origin, p1, p2 = _two_agent_origin(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    w1, w2 = fleet_lib.wrapper_bytes("h1", p1), fleet_lib.wrapper_bytes("h2", p2)
    cmd1, cmd2, default = _paths(home)
    a1, a2 = os.path.join(str(home), "agents", "h1"), os.path.join(str(home), "agents", "h2")
    # (1) the first agent sets the default
    proc = _install_agent(home, origin, "h1")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == (
        "installed v2026.01.01 at %s\n" % a1
        + "command: %s (daemon port %d)\n" % (cmd1, p1)
        + "default: %s runs agent h1\n" % default
        + "next: run %s/current/qwen-agent-workspace/bin/qwen-agentd join --agent-id h1 "
          "(or init-fleet --agent-id h1); the service retries every 10 s\n" % a1)
    for path in (cmd1, default):
        assert os.path.isfile(path) and not os.path.islink(path)
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o755
        assert _read(path) == w1
    # (2) a second agent (through the --host-id alias) leaves the default alone
    proc = _agentd(home, "install", "--host-id", "h2", "--origin", origin.bare, "--no-service")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[:3] == [
        "installed v2026.01.01 at %s" % a2, "command: %s (daemon port %d)" % (cmd2, p2),
        "default: %s unchanged; pass --default to make it run agent h2" % default]
    assert _read(cmd2) == w2 and _read(default) == w1
    for root in (a1, a2):
        for name in ("repo", "current", "update-state.json", "qwen-agentd-launch"):
            assert os.path.lexists(os.path.join(root, name)), (root, name)
        assert os.path.realpath(os.path.join(root, "current")) == os.path.join(root, "releases", "v2026.01.01")
    # (3) --default moves the default to h2
    proc = _install_agent(home, origin, "h2", "--default")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[2] == "default: %s runs agent h2" % default
    assert _read(default) == w2
    # (4) re-installing h1 rewrites its own command and keeps h2 as the default
    fleet_lib.write_wrapper(cmd1, fleet_lib.wrapper_bytes("h1", 1024))
    proc = _install_agent(home, origin, "h1")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[1:3] == [
        "command: %s (daemon port %d)" % (cmd1, p1),
        "default: %s unchanged; pass --default to make it run agent h1" % default]
    assert _read(cmd1) == w1 and _read(default) == w2
    # (5) h2 takes h1's fleet secret without seeing it
    token = secrets.token_hex(32)
    ftu.make_fleet(home, "h1", ftu.TEST_FLEET_ID, token)
    proc = _agentd(home, "join", "--agent-id", "h2", "--from-agent", "h1")
    assert (proc.returncode, proc.stderr) == (0, "")
    assert proc.stdout == "qwen-agentd: joined fleet %s (copied from agent h1)\n" % ftu.TEST_FLEET_ID
    assert token not in proc.stdout
    env2 = os.path.join(a2, "fleet.env")
    assert stat.S_IMODE(os.stat(env2).st_mode) == 0o600
    assert _read(env2) == _read(os.path.join(a1, "fleet.env"))
    # (6) nothing was written outside the two agent roots, ~/.local/bin and the origin
    allowed = (os.path.join(str(home), "agents"), os.path.join(str(home), ".local", "bin"), str(tmp_path / "o"))
    for root, dirs, files in os.walk(str(tmp_path)):
        for name in dirs + files:
            path = os.path.join(root, name)
            assert any(path == a or path.startswith(a + os.sep) or a.startswith(path + os.sep)
                       for a in allowed), path


def test_mt21_commands_are_never_clobbered(tmp_path, monkeypatch):
    home, origin, _p1, p2 = _two_agent_origin(tmp_path)
    cmd1, _cmd2, default = _paths(home)
    assert _install_agent(home, origin, "h1").returncode == 0
    # (a) a hand-written qwen-agent-h1 is kept, with a warning and no command: line
    with open(cmd1, "w") as f:
        f.write("#!/bin/sh\necho mine\n")
    proc = _install_agent(home, origin, "h1")
    assert proc.returncode == 0, proc.stderr
    assert ("qwen-agentd: warning: not replacing %s: not a symlink or a qwen-agentd wrapper" % cmd1) in proc.stderr
    assert _read(cmd1) == b"#!/bin/sh\necho mine\n"
    assert not any(line.startswith("command: ") for line in proc.stdout.splitlines())
    # (b) a hand-written default is kept even with --default; stdout has no default: line
    with open(default, "w") as f:
        f.write("#!/bin/sh\necho default\n")
    proc = _install_agent(home, origin, "h1", "--default")
    assert proc.returncode == 0, proc.stderr
    assert ("qwen-agentd: warning: not replacing %s: not a symlink or a qwen-agentd wrapper" % default) in proc.stderr
    assert _read(default) == b"#!/bin/sh\necho default\n"
    assert not any(line.startswith("default: ") for line in proc.stdout.splitlines())
    # (c) a dangling symlink (the Mac's old dev link) is kept without --default, replaced with it
    os.unlink(default)
    os.symlink("/nonexistent", default)
    proc = _install_agent(home, origin, "h2")
    assert proc.returncode == 0, proc.stderr
    assert "default: %s unchanged; pass --default to make it run agent h2" % default in proc.stdout.splitlines()
    assert os.readlink(default) == "/nonexistent"
    proc = _install_agent(home, origin, "h2", "--default")
    assert proc.returncode == 0, proc.stderr
    assert not os.path.islink(default)
    monkeypatch.setenv("HOME", str(home))
    assert _read(default) == fleet_lib.wrapper_bytes("h2", p2)


def test_mt22_install_port_from_the_release_registry(tmp_path, monkeypatch):
    home, origin, _p1, _p2 = _two_agent_origin(tmp_path)
    # (a) an agent missing from every registry warns and uses 8190
    proc = _install_agent(home, origin, "h3")
    assert proc.returncode == 0, proc.stderr
    assert ("qwen-agentd: warning: agent 'h3' is not in any registry of release v2026.01.01; "
            "its commands use port 8190") in proc.stderr
    monkeypatch.setenv("HOME", str(home))
    assert _read(os.path.join(str(home), ".local", "bin", "qwen-agent-h3")) == fleet_lib.wrapper_bytes("h3", 8190)
    # (b) two registries of one release that disagree on h1's port: exit 2
    home2 = tmp_path / "home2"
    home2.mkdir()
    origin2 = Origin(tmp_path / "o2", _registry(ftu.free_port()))
    other = _registry(ftu.free_port())
    other["fleet_id"] = ftu.OTHER_FLEET_ID
    origin2.write(os.path.join("fleets", ftu.OTHER_FLEET_ID + ".json"), json.dumps(other, indent=2))
    origin2.release("v2026.01.01")
    proc = _install_agent(home2, origin2, "h1")
    assert proc.returncode == 2
    assert proc.stderr == ("qwen-agentd: agent 'h1' has different ports in 0123456789abcdef.json, "
                           "fedcba9876543210.json of release v2026.01.01\n")
