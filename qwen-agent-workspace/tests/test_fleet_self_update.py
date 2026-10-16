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
    return os.path.join(str(home), ".local", "share", "qwen-agent")


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
                           "next: run %s/current/qwen-agent-workspace/bin/qwen-agentd join (or init-fleet); "
                           "the service retries every 10 s\n" % (d, d))
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
    assert os.path.exists(os.path.join(ftu.daemon_log_dir(home), "gate-v2026.01.01.log"))
    assert not os.path.exists(os.path.join(str(home), "Library", "LaunchAgents"))
    assert not os.path.exists(os.path.join(str(home), ".config", "systemd"))
    origin.release("v2026.01.02")
    ftu.make_fleet(home, ftu.TEST_FLEET_ID, secrets.token_hex(32))
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
    assert (proc.returncode, proc.stderr) == (2, "qwen-agentd: invalid --host-id 'Mac_Local'\n")
    origin = Origin(tmp_path / "o", _registry(ftu.free_port()))
    origin.append("tests/test_fleet_lib.py", "\n\ndef test_gate_must_fail():\n    assert False\n")
    origin.release("v2026.01.01")
    proc = _install(home, origin)
    assert proc.returncode == 2
    assert proc.stderr == ("qwen-agentd: first release v2026.01.01 failed its gate (selftest exit 1); see %s\n"
                           % os.path.join(ftu.daemon_log_dir(home), "gate-v2026.01.01.log"))
    assert not os.path.lexists(os.path.join(_deploy(home), "current"))


def test_service_definitions():
    agentd = ftu.load_script("qwen_agentd_services", ftu.AGENTD)
    plist = agentd.launchd_plist_dict("/usr/bin/python3", "/h/.local/share/qwen-agent", "mac-local",
                                      "/h/Library/Logs/qwen-agentd")
    assert plist == {
        "Label": "com.qwen-agent.qwen-agentd",
        "ProgramArguments": ["/usr/bin/python3", "/h/.local/share/qwen-agent/qwen-agentd-launch"],
        "EnvironmentVariables": {"QWEN_AGENT_HOST_ID": "mac-local",
                                 "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
        "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10,
        "StandardOutPath": "/h/Library/Logs/qwen-agentd/launchd.out",
        "StandardErrorPath": "/h/Library/Logs/qwen-agentd/launchd.err"}
    assert plistlib.loads(plistlib.dumps(plist)) == plist
    assert agentd.systemd_unit_text("/usr/bin/python3", "/home/u/.local/share/qwen-agent", "ollama-168") == (
        "[Unit]\nDescription=qwen-agent fleet daemon\nStartLimitIntervalSec=0\n\n"
        "[Service]\nExecStart=/usr/bin/python3 /home/u/.local/share/qwen-agent/qwen-agentd-launch\n"
        "Environment=QWEN_AGENT_HOST_ID=ollama-168\nRestart=always\nRestartSec=10\n\n"
        "[Install]\nWantedBy=default.target\n")


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
