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


def test_t61_install_layout_and_idempotence(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    origin = Origin(tmp_path / "o", _registry(ftu.free_port()))
    proc = _install(home, origin)
    assert proc.returncode == 2
    assert proc.stderr == ("qwen-agentd: no release tags (vYYYY.MM.DD[.N]) at %s; tag a release first\n"
                           % origin.bare)
    origin.release("v2026.01.01")
    proc = _install(home, origin)
    assert proc.returncode == 0, proc.stderr
    d = _deploy(home)
    assert proc.stdout == ("installed v2026.01.01 at %s\n"
                           "next: run %s/current/qwen-agent-workspace/bin/qwen-agentd join --agent-id h1 "
                           "(or init-fleet --agent-id h1); the service retries every 10 s\n" % (d, d))
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(os.path.join(d, "qwen-agentd-launch")).st_mode) == 0o755
    assert stat.S_IMODE(os.stat(os.path.join(d, "update-state.json")).st_mode) == 0o600
    assert os.readlink(os.path.join(d, "current")) == "releases/v2026.01.01"
    assert os.path.isdir(os.path.join(d, "repo", "refs"))
    link = os.path.join(str(home), ".local", "bin", "qwen-agent")
    assert os.readlink(link) == os.path.join(d, "current", "qwen-agent-workspace", "bin", "qwen-agent")
    assert os.path.realpath(link) == os.path.realpath(
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
    assert proc.stdout == "installed v2026.01.01 at %s\n" % d
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
