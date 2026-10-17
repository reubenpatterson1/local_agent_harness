"""Tests for scripts/fleet-host-prep.sh (host-prep spec, Section 6).

Run from the workspace root: python3 -m pytest tests/test_fleet_host_prep.py -v

Every test runs the real script under /bin/bash against the real fleet_lib.py
and searxng/ files, with an environment built from scratch: PATH is a stub
directory of fakes (bash wrappers around one Python dispatcher, FAKEBIN), HOME
is an empty temporary directory, and FLEET_PREP_SOCKETFILTERFW points at a
fake. No real sudo, apt, dnf, docker, ufw, firewall-cmd, loginctl,
timedatectl, systemsetup, socketfilterfw, sntp, ollama or pip ever runs, and
the real HOME is never used.
"""

import copy
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SCRIPT = os.path.join(WS, "scripts", "fleet-host-prep.sh")

FAKE_NAMES = ("uname sw_vers id sudo python3 git apt-get dnf timedatectl sntp systemsetup "
              "curl ollama docker ufw firewall-cmd loginctl sleep xcode-select").split()
REAL_TOOLS = ("dirname", "mkdir", "cp")
LINUX_ABSENT = frozenset({"dnf", "sntp"})
MAC_ABSENT = frozenset({"apt-get", "dnf", "timedatectl", "loginctl", "ufw", "firewall-cmd"})
LINUX_ARGS = ["--model-server-type", "ollama", "--model", "qwen3.5:9b"]
MAC_ARGS = ["--model-server-type", "vllm", "--model", "qwen38-6bit"]

WRAPPER = "#!/bin/bash\nexec '{exe}' -I -B '{tmp}/fakebin.py' '{tmp}' '{name}' \"$@\"\n"

# Section 6.4, verbatim.
FORBIDDEN = [
    r"\bdeclare\s+-[aAn]", r"\blocal\s+-[aAn]", r"\btypeset\s+-A", r"\bread\s+(-[a-zA-Z]*\s+)*-a\b",
    r"\bmapfile\b", r"\breadarray\b",
    r"\$\{[A-Za-z_][A-Za-z0-9_]*(,,?|\^\^?)\}",
    r"\|&", r";;?&", r"\bcoproc\b", r"\[-[0-9]+\]\}",
    r"\[\[\s+-v\s", r"&>>", r"(^|[^$A-Za-z0-9_])\{[A-Za-z_][A-Za-z0-9_]*\}[<>]",
    r"@[QEPAa]\}", r"globstar", r"\bwait\s+-n\b", r"EPOCH(SECONDS|REALTIME)",
    r"^\s*[A-Za-z_][A-Za-z0-9_]*=\(", r"\b(local|declare)\s+[A-Za-z_][A-Za-z0-9_]*=\(",
    r"\bset\s+-[a-z]*e",
]
LINE_FORMS = [
    r"(PASS|FAIL|FIXED|SKIP|UNKNOWN) [a-z]+: .+",
    r"  fix: .+",
    r"\+ .+",
    r"summary: [0-9]+ pass, [0-9]+ fixed, [0-9]+ fail, [0-9]+ unknown, [0-9]+ skip",
]

USAGE = """\
Usage: fleet-host-prep.sh --model-server-type {ollama|vllm} --model NAME
                          [--model-url URL] [--searxng-url URL | --no-searxng]
                          [--lan-cidr CIDR] [--port N] [--apply]

Checks the qwen-agent fleet rollout prerequisites (R0) on this host: platform,
packages, clock, model, searxng, firewall, linger. Changes nothing unless
--apply is given.

  --model-server-type   ollama or vllm (required)
  --model NAME          the model this host must serve (required)
  --model-url URL       default: http://127.0.0.1:11434/v1 (ollama),
                        http://127.0.0.1:8177/v1 (vllm)
  --searxng-url URL     default: http://127.0.0.1:8888/
  --no-searxng          skip the searxng check (a host that serves only no-tools skills)
  --lan-cidr CIDR       fleet LAN that must reach the fleet port; default: 192.168.1.0/24
  --port N              the fleet daemon's TCP and UDP port, 1024-65535; default: 8190
  --apply               fix failing checks (asks for your sudo password once)
  -h, --help            show this help

Exit status: 0 all checks pass; 1 a check failed or is unknown;
2 usage error, or run as root.
"""


def ufw_row(to, action, frm, comment=""):
    return "%-26s %-12s%-26s%s\n" % (to, action, frm, comment)


UFW_HEAD = ("Status: active\n\nTo                         Action      From\n"
            "--                         ------      ----\n")
UFW_OK = (UFW_HEAD + ufw_row("22/tcp", "ALLOW", "Anywhere") + ufw_row("8190", "ALLOW", "192.168.1.0/24")
          + ufw_row("22/tcp (v6)", "ALLOW", "Anywhere (v6)"))
UFW_NONE = UFW_HEAD + ufw_row("22/tcp", "ALLOW", "Anywhere") + ufw_row("22/tcp (v6)", "ALLOW", "Anywhere (v6)")
PYTHON_EXE = "/opt/fakepy/Python.app/Contents/MacOS/Python"

# Section 6.2 state keys and defaults: a Linux host where every check passes.
# model_code is a plan addition (Review Focus 4): the HTTP status the model
# server answers with.
DEFAULT_STATE = {
    "os": "Linux",
    "macos_version": "26.5.2",
    "uid": 1000,
    "user": "tester",
    "groups": "tester docker",
    "sudo_v_exit": 0,
    "sudo_n_ok": True,
    "py_ok": True,
    "pytest_ok": True,
    "clock_linux": "yes",
    "sntp_out": "+0.003142 +/- 0.010472 time.apple.com 17.253.4.125",
    "sntp_exit": 0,
    "model": "ok",
    "model_name": "qwen3.5:9b",
    "model_code": 200,
    "searxng": "ok",
    "containers": [],
    "docker_ps_exit": 0,
    "ufw_out": UFW_OK,
    "firewalld": "not running",
    "firewalld_rules": [],
    "linger": "yes",
    "sfw_global": "Firewall is disabled. (State = 0)",
    "sfw_blockall": "Firewall has block all state set to disabled.",
    "sfw_apps": [],
    "python_exe": PYTHON_EXE,
    "fix": {},
    "lag": {},
    "pending_lag": {},
}

FAKEBIN = r'''
"""Fake commands for tests/test_fleet_host_prep.py: fakebin.py TMP NAME ARGS..."""
import json
import os
import sys

TMP, NAME, ARGS = sys.argv[1], sys.argv[2], sys.argv[3:]
STUB = os.path.join(TMP, "stub")
STATE = os.path.join(TMP, "state.json")
CALLS = os.path.join(TMP, "calls.jsonl")
WRAPPER = "#!/bin/bash\nexec '{exe}' -I -B '{tmp}/fakebin.py' '{tmp}' '{name}' \"$@\"\n"

PY_VERSION = "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"
PY_PYTEST = "import pytest"
PY_EXE = ('import os, subprocess; print(os.path.realpath(subprocess.check_output('
          '["/bin/ps", "-o", "comm=", "-p", str(os.getpid())]).decode().strip()))')
CURL = ["-sS", "--noproxy", "*", "--max-time", "5"]
UNEXPECTED = ("", "unexpected argv\n", 99)


def ufw_row(to, action, frm):
    return "%-26s %-12s%-26s\n" % (to, action, frm)


def add_wrapper(name):
    """Install the wrapper for NAME (a hard link to the harness's pristine copy)."""
    path = os.path.join(STUB, name)
    if not os.path.exists(path):
        os.link(os.path.join(TMP, "pristine", name), path)


def group(state, name, change):
    """Run a fix group: 'ok' applies change (and arms the lag), 'noop' does
    nothing, 'exit:N' does nothing and exits N."""
    mode = state["fix"].get(name, "ok")
    if mode == "noop":
        return 0
    if mode.startswith("exit:"):
        return int(mode[len("exit:"):])
    change()
    if name in state["lag"]:
        state["pending_lag"][name] = state["lag"][name]
    return 0


def lagging(state, key):
    n = state["pending_lag"].get(key, 0)
    if n > 0:
        state["pending_lag"][key] = n - 1
        return True
    return False


def sudo_exec(cmd):
    path = cmd[0] if "/" in cmd[0] else os.path.join(STUB, cmd[0])
    if not os.path.exists(path):
        return ("", "sudo: %s: command not found\n" % cmd[0], 1)
    return ("exec", path, [path] + cmd[1:])


def model_body(state, url):
    served = ([state["model_name"]] if state["model"] == "ok" else []) + ["other-model:1b"]
    if url.endswith("/api/tags"):
        return json.dumps({"models": [{"name": n, "model": n} for n in served]})
    return json.dumps({"object": "list", "data": [{"id": n, "object": "model"} for n in served]})


def install_packages(state):
    add_wrapper("python3")
    add_wrapper("git")
    state["py_ok"] = True
    state["pytest_ok"] = True


def set_sntp_ok(state):
    state["sntp_out"] = "+0.001000 +/- 0.010000 time.apple.com 17.253.4.125"
    state["sntp_exit"] = 0


def compose_up(state):
    state["containers"].append("qwen-agent-searxng")
    state["searxng"] = "ok"


def sfw_add(state, path):
    if path not in [p for p, _ in state["sfw_apps"]]:
        state["sfw_apps"].append([path, "block"])


def sfw_unblock(state, path):
    for app in state["sfw_apps"]:
        if app[0] == path:
            app[1] = "allow"


def listapps(state):
    lines = ["Total number of apps = %d " % len(state["sfw_apps"])]
    for i, (path, mode) in enumerate(state["sfw_apps"], 1):
        lines.append("%d : %s " % (i, path))
        lines.append("             (%s incoming connections)" % ("Allow" if mode == "allow" else "Block"))
    return "\n".join(lines) + "\n"


def dispatch(state):
    """Return (stdout, stderr, rc), or ("exec", path, argv)."""
    n, a = NAME, ARGS
    if n == "uname" and a == ["-s"]:
        return (state["os"] + "\n", "", 0)
    if n == "sw_vers" and a == ["-productVersion"]:
        return (state["macos_version"] + "\n", "", 0)
    if n == "id" and a in (["-u"], ["-un"], ["-nG"]):
        key = {"-u": "uid", "-un": "user", "-nG": "groups"}[a[0]]
        return ("%s\n" % state[key], "", 0)
    if n == "sudo":
        if a == ["-v"]:
            return ("", "", state["sudo_v_exit"])
        if a[:1] == ["-n"] and len(a) > 1:
            if not state["sudo_n_ok"]:
                return ("", "sudo: a password is required\n", 1)
            return sudo_exec(a[1:])
        if a and not a[0].startswith("-"):
            return sudo_exec(a)
        return UNEXPECTED
    if n == "python3":
        if a == ["-c", PY_VERSION]:
            return ("", "", 0 if state["py_ok"] else 1)
        if a == ["-c", PY_PYTEST]:
            return ("", "", 0 if state["py_ok"] and state["pytest_ok"] else 1)
        if a == ["-I", "-B", "-c", PY_EXE]:
            return (state["python_exe"] + "\n", "", 0)
        if a == ["-m", "pip", "install", "--user", "pytest"]:
            return ("", "", group(state, "packages", lambda: state.update(pytest_ok=True)))
        return ("exec", sys.executable, [sys.executable] + a)
    if n == "git" and a == ["--version"]:
        return ("git version 2.43.0\n", "", 0)
    if n == "apt-get" and a == ["update"]:
        return ("", "", group(state, "apt_update", lambda: None))
    if n in ("apt-get", "dnf") and a == ["install", "-y", "python3", "git", "python3-pytest"]:
        return ("", "", group(state, "packages", lambda: install_packages(state)))
    if n == "timedatectl" and a == ["show", "-p", "NTPSynchronized"]:
        value = "no" if lagging(state, "clock") else state["clock_linux"]
        return ("NTPSynchronized=%s\n" % value, "", 0)
    if n == "timedatectl" and a == ["set-ntp", "true"]:
        return ("", "", group(state, "clock", lambda: state.update(clock_linux="yes")))
    if n == "sntp" and a == ["-t", "3", "time.apple.com"]:
        return (state["sntp_out"] + "\n", "", state["sntp_exit"])
    if n == "systemsetup" and a == ["-setusingnetworktime", "on"]:
        return ("", "", group(state, "clock", lambda: set_sntp_ok(state)))
    if n == "curl" and a[:5] == CURL:
        rest = a[5:]
        if (len(rest) == 3 and rest[:2] == ["-w", "\\n%{http_code}"]
                and (rest[2].endswith("/api/tags") or rest[2].endswith("/models"))):
            if state["model"] == "down":
                return ("\n000", "curl: (7) Failed to connect\n", 7)
            if state["model_code"] != 200:
                return ('{"detail": "Not Found"}\n%d' % state["model_code"], "", 0)
            return (model_body(state, rest[2]) + "\n200", "", 0)
        if len(rest) == 5 and rest[:4] == ["-o", "/dev/null", "-w", "%{http_code}"]:
            if state["searxng"] == "down" or lagging(state, "searxng"):
                return ("000", "curl: (7) Failed to connect\n", 7)
            return ("200", "", 0)
        return UNEXPECTED
    if n == "ollama" and len(a) == 2 and a[0] == "pull":
        def pulled():
            state["model"] = "ok"
            state["model_name"] = a[1]
        return ("pulling manifest\n", "", group(state, "model", pulled))
    if n == "docker":
        if a == ["ps", "-a", "--format", "{{.Names}}"]:
            return ("".join(c + "\n" for c in state["containers"]), "", state["docker_ps_exit"])
        if a == ["start", "qwen-agent-searxng"]:
            if "qwen-agent-searxng" not in state["containers"]:
                return ("", "Error: No such container: qwen-agent-searxng\n", 1)
            return ("", "", group(state, "searxng", lambda: state.update(searxng="ok")))
        if (len(a) == 7 and a[:3] == ["compose", "-p", "qwen-agent-searxng"] and a[3] == "-f"
                and a[5:] == ["up", "-d"]):
            settings = os.path.join(os.path.dirname(a[4]), "settings.yml")
            if not (os.path.isfile(a[4]) and os.path.isfile(settings)):
                return ("", "compose: missing %s or %s\n" % (a[4], settings), 14)
            return ("", "", group(state, "searxng", lambda: compose_up(state)))
        return UNEXPECTED
    if n == "ufw":
        if a == ["status"]:
            return (state["ufw_out"], "", 0)
        if len(a) == 7 and a[:2] == ["allow", "from"] and a[3:6] == ["to", "any", "port"]:
            def allow():
                state["ufw_out"] += ufw_row(a[6], "ALLOW", a[2])
            return ("", "", group(state, "firewall", allow))
        return UNEXPECTED
    if n == "firewall-cmd":
        if a == ["--state"]:
            return (state["firewalld"] + "\n", "", 0 if state["firewalld"] == "running" else 252)
        if a == ["--permanent", "--list-rich-rules"]:
            return ("".join(r + "\n" for r in state["firewalld_rules"]), "", 0)
        if len(a) == 2 and a[0] == "--permanent" and a[1].startswith("--add-rich-rule="):
            rule = a[1][len("--add-rich-rule="):]
            return ("", "", group(state, "firewall", lambda: state["firewalld_rules"].append(rule)))
        if a == ["--reload"]:
            return ("", "", group(state, "firewall", lambda: None))
        return UNEXPECTED
    if n == "loginctl":
        if a == ["show-user", state["user"], "-p", "Linger"]:
            return ("Linger=%s\n" % state["linger"], "", 0)
        if a == ["enable-linger", state["user"]]:
            return ("", "", group(state, "linger", lambda: state.update(linger="yes")))
        return UNEXPECTED
    if n == "sleep" and a in (["1"], ["2"]):
        return ("", "", 0)
    if n == "socketfilterfw":
        if a == ["--getglobalstate"]:
            return (state["sfw_global"] + "\n", "", 0)
        if a == ["--getblockall"]:
            return (state["sfw_blockall"] + "\n", "", 0)
        if a == ["--listapps"]:
            return (listapps(state), "", 0)
        if len(a) == 2 and a[0] == "--add":
            return ("", "", group(state, "firewall", lambda: sfw_add(state, a[1])))
        if len(a) == 2 and a[0] == "--unblockapp":
            return ("", "", group(state, "firewall", lambda: sfw_unblock(state, a[1])))
        return UNEXPECTED
    return UNEXPECTED


def main():
    with open(STATE) as f:
        state = json.load(f)
    result = dispatch(state)
    with open(STATE, "w") as f:
        json.dump(state, f)
    rc = None if result[0] == "exec" else result[2]
    with open(CALLS, "a") as f:
        f.write(json.dumps({"name": NAME, "argv": ARGS, "rc": rc}) + "\n")
    if result[0] == "exec":
        sys.stdout.flush()
        os.execv(result[1], result[2])
    sys.stdout.write(result[0])
    sys.stderr.write(result[1])
    sys.stdout.flush()
    sys.exit(result[2])


main()
'''


def linux_state(**overrides):
    state = copy.deepcopy(DEFAULT_STATE)
    state.update(overrides)
    return state


def mac_state(**overrides):
    state = linux_state(os="Darwin", model_name="qwen38-6bit")
    state.update(overrides)
    return state


def all_fail_state(**overrides):
    """Section 6.2 "Linux all-fail"; run it with absent=ALL_FAIL_ABSENT."""
    state = linux_state(py_ok=False, pytest_ok=False, clock_linux="no", model="missing",
                        searxng="down", containers=[], ufw_out=UFW_NONE, linger="no")
    state.update(overrides)
    return state


ALL_FAIL_ABSENT = LINUX_ABSENT | {"git"}


class Run:
    """One script run: rc, out, err, lines, and snapshots of the fake-call log
    and of the fakes' final state.

    Every run reuses the one harness directory, so check files under home or
    sx before the next run() call."""

    def __init__(self, tmp, home, proc):
        self.tmp = tmp
        self.home = home
        self.sx = os.path.join(home, ".local", "share", "qwen-agent", "searxng")
        self.sfw = os.path.join(tmp, "sfw", "socketfilterfw")
        self.rc = proc.returncode
        self.out = proc.stdout
        self.err = proc.stderr
        self.lines = proc.stdout.splitlines()
        path = os.path.join(tmp, "calls.jsonl")
        self._calls = []
        if os.path.exists(path):
            with open(path) as f:
                self._calls = [json.loads(line) for line in f]
        with open(os.path.join(tmp, "state.json")) as f:
            self.state = json.load(f)

    def calls(self):
        return copy.deepcopy(self._calls)

    def named(self, name, *prefix):
        """Calls of fake NAME whose argv starts with PREFIX."""
        return [c for c in self.calls() if c["name"] == name and c["argv"][:len(prefix)] == list(prefix)]

    def status(self, check):
        """The one status line for CHECK."""
        found = [l for l in status_lines(self.out) if l.split(" ", 2)[1] == check + ":"]
        assert len(found) == 1, (check, self.out)
        return found[0]

    def fix_after(self, check):
        """The line right after CHECK's status line."""
        i = self.lines.index(self.status(check))
        return self.lines[i + 1]


# One harness directory <tmp> for the whole session. Its pristine/ holds one
# wrapper per fake (Section 6.2 content, mode 0755), written once; each run
# resets everything else in <tmp> and hard-links the wrappers it needs into
# stub/. Reason: on macOS the first exec of every newly written file costs
# about 100 ms (measured 2026-10-17), and a fresh set of wrappers per run would
# push this file past the spec's 120 s limit. A hard link shares the already
# checked file, so only the session's first exec of each wrapper pays.
HARNESS = {}


@pytest.fixture(scope="session", autouse=True)
def harness_dir(tmp_path_factory):
    tmp = str(tmp_path_factory.mktemp("hostprep"))
    pristine = os.path.join(tmp, "pristine")
    os.makedirs(pristine)
    for name in FAKE_NAMES + ["socketfilterfw"]:
        path = os.path.join(pristine, name)
        with open(path, "w") as f:
            f.write(WRAPPER.format(exe=sys.executable, tmp=tmp, name=name))
        os.chmod(path, 0o755)
    HARNESS["tmp"] = tmp
    yield tmp


def run(args, state=None, absent=LINUX_ABSENT, home_name="home", cwd=None, script=SCRIPT):
    """Run the script once. ABSENT names the fakes left out of stub/; it may
    also hold "socketfilterfw" to leave out the socketfilterfw fake."""
    tmp = HARNESS["tmp"]
    for entry in os.listdir(tmp):
        if entry != "pristine":
            path = os.path.join(tmp, entry)
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
    stub = os.path.join(tmp, "stub")
    home = os.path.join(tmp, home_name)
    for d in (stub, home, os.path.join(tmp, "t"), os.path.join(tmp, "sfw")):
        os.makedirs(d)
    with open(os.path.join(tmp, "fakebin.py"), "w") as f:
        f.write(FAKEBIN)
    with open(os.path.join(tmp, "state.json"), "w") as f:
        json.dump(linux_state() if state is None else state, f)
    for name in FAKE_NAMES:
        if name not in absent:
            os.link(os.path.join(tmp, "pristine", name), os.path.join(stub, name))
    for name in REAL_TOOLS:
        os.symlink(shutil.which(name), os.path.join(stub, name))
    sfw = os.path.join(tmp, "sfw", "socketfilterfw")
    if "socketfilterfw" not in absent:
        os.link(os.path.join(tmp, "pristine", "socketfilterfw"), sfw)
    env = {"PATH": stub, "HOME": home, "TMPDIR": os.path.join(tmp, "t"),
           "FLEET_PREP_SOCKETFILTERFW": sfw}
    proc = subprocess.run(["/bin/bash", script] + list(args), env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=60, cwd=cwd)
    result = Run(tmp, home, proc)
    assert [c for c in result.calls() if c["rc"] == 99] == [], (result.calls(), proc.stderr)
    return result


def plus_lines(stdout):
    return [l for l in stdout.splitlines() if l.startswith("+ ")]


def status_lines(stdout):
    return [l for l in stdout.splitlines() if re.match(r"^(PASS|FAIL|FIXED|SKIP|UNKNOWN) [a-z]+: ", l)]


def mutating(calls):
    found = []
    for c in calls:
        n, a = c["name"], c["argv"]
        if ((n == "sudo" and a[:1] not in (["-v"], ["-n"]))
                or n in ("apt-get", "dnf", "xcode-select", "systemsetup")
                or (n == "ollama" and a[:1] == ["pull"])
                or (n == "docker" and a[:1] in (["start"], ["compose"]))
                or (n == "ufw" and a[:1] == ["allow"])
                or (n == "firewall-cmd" and (a == ["--reload"]
                                             or any(x.startswith("--add-rich-rule=") for x in a)))
                or (n == "loginctl" and a[:1] == ["enable-linger"])
                or (n == "timedatectl" and a[:1] == ["set-ntp"])
                or (n == "socketfilterfw" and a[:1] in (["--add"], ["--unblockapp"]))
                or (n == "python3" and a[:2] == ["-m", "pip"])):
            found.append(c)
    return found


def script_text():
    with open(SCRIPT) as f:
        return f.read()


# ---------------------------------------------------------------------------
# Task 2: file rules, CLI, validation, root refusal (H6, H12, H15b, H23, Review Focus 3)
# ---------------------------------------------------------------------------

def _usage_error(r, message):
    assert r.rc == 2, (r.out, r.err)
    assert r.err == ("fleet-host-prep.sh: %s\nRun 'fleet-host-prep.sh --help' for usage.\n" % message)
    assert r.out == ""
    assert r.named("sudo") == [] and r.named("uname") == []


H6_REJECTED = [
    (["--model-server-type", "ollama"], "missing --model"),
    (["--model", "qwen3.5:9b"], "missing --model-server-type"),
    (["--model-server-type", "llama", "--model", "qwen3.5:9b"],
     "--model-server-type must be ollama or vllm, got 'llama'"),
    (LINUX_ARGS + ["--bogus"], "unknown argument '--bogus'"),
    (["--model-server-type", "ollama", "--model"], "--model needs a value"),
    (["--model-server-type", "ollama", "--model", "--apply"], "--model needs a value"),
    (["--model-server-type", "ollama", "--model=qwen3.5:9b"], "unknown argument '--model=qwen3.5:9b'"),
    (LINUX_ARGS + ["--port"], "--port needs a value"),
    (LINUX_ARGS + ["--no-searxng", "--searxng-url", "http://127.0.0.1:8888/"],
     "--no-searxng and --searxng-url cannot be used together"),
    (LINUX_ARGS + ["--searxng-url", "http://127.0.0.1:8888/", "--no-searxng"],
     "--no-searxng and --searxng-url cannot be used together"),
    (LINUX_ARGS + ["--no-searxng=1"], "unknown argument '--no-searxng=1'"),
] + [
    (LINUX_ARGS + ["--lan-cidr", v],
     "--lan-cidr must be an IPv4 network with zero host bits, e.g. 192.168.1.0/24, got '%s'" % v)
    for v in ("192.168.1.0/33", "300.1.1.0/24", "192.168.1.5/24", "192.168.1.0")
] + [
    (LINUX_ARGS + ["--port", v], "--port must be a decimal integer from 1024 to 65535, got '%s'" % v)
    for v in ("1023", "65536", "0", "abc", "08191", "8190.0")
]


@pytest.mark.parametrize("args,message", H6_REJECTED)
def test_h6_usage_errors(args, message):
    _usage_error(run(args), message)


def test_h6_root_is_refused_after_validation():
    r = run(LINUX_ARGS + ["--apply"], linux_state(uid=0))
    assert r.rc == 2
    assert r.err == ("fleet-host-prep.sh: refusing to run as root; run as the user who will run "
                     "the fleet daemon (fixes use sudo)\n")
    assert [(c["name"], c["argv"]) for c in r.calls()] == [("id", ["-u"])]
    # Usage errors take precedence over the root check: id is never called.
    r = run(["--model", "x"], linux_state(uid=0))
    assert r.rc == 2 and r.calls() == []


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_h6_help(flag):
    r = run(LINUX_ARGS + [flag, "--bogus"])
    assert r.rc == 0
    assert r.out == USAGE
    assert r.calls() == []


def test_review_focus_3_empty_values_from_unset_variables():
    # `--model "$M"` with M unset passes an empty string, not nothing.
    _usage_error(run(["--model-server-type", "ollama", "--model", ""]), "missing --model")
    _usage_error(run(["--model-server-type", "", "--model", "x"]),
                 "--model-server-type must be ollama or vllm, got ''")
    _usage_error(run(LINUX_ARGS + ["--lan-cidr", ""]),
                 "--lan-cidr must be an IPv4 network with zero host bits, e.g. 192.168.1.0/24, got ''")
    _usage_error(run(LINUX_ARGS + ["--port", ""]),
                 "--port must be a decimal integer from 1024 to 65535, got ''")


def test_h12_file_rules_and_bash_compatibility():
    assert subprocess.run(["/bin/bash", "-n", SCRIPT]).returncode == 0
    text = script_text()
    assert text.split("\n", 1)[0] == "#!/usr/bin/env bash"
    assert os.stat(SCRIPT).st_mode & 0o777 == 0o755
    code = "\n".join(l for l in text.split("\n") if not l.lstrip().startswith("#"))
    for pattern in FORBIDDEN:
        assert not re.search(pattern, code, re.M), pattern
    assert "set -u" in code and "set -o pipefail" in code


def test_h15b_model_url_logic_lives_in_fleet_lib():
    text = script_text()
    assert "fleet_lib.probe_url" in text and "fleet_lib.parse_loaded_models" in text
    assert "api/tags" not in text and "/models" not in text


def test_h23_no_secret_strings():
    text = script_text()
    for s in ("fleet.env", "QWEN_AGENT_FLEET", ".config/qwen-agent"):
        assert s not in text


# ---------------------------------------------------------------------------
# Task 3: output protocol, sudo, platform (H21, H22, P9, P13)
# ---------------------------------------------------------------------------

def test_h21_unsupported_platform_stops_at_once():
    r = run(LINUX_ARGS, linux_state(os="FreeBSD"))
    assert r.rc == 1
    assert r.out == ("FAIL platform: unsupported OS 'FreeBSD'\n"
                     "  fix: this script supports macOS (Darwin) and Linux only\n"
                     "summary: 0 pass, 0 fixed, 1 fail, 0 unknown, 0 skip\n")
    assert [(c["name"], c["argv"]) for c in r.calls()] == [("id", ["-u"]), ("uname", ["-s"])]


def test_h22_sudo_v_failure_changes_nothing():
    r = run(LINUX_ARGS + ["--apply"], linux_state(sudo_v_exit=1))
    assert r.rc == 1
    assert r.out == ("FAIL sudo: 'sudo -v' failed (exit 1); nothing was changed\n"
                     "  fix: re-run from an interactive terminal and enter your password, or run without --apply\n"
                     "summary: 0 pass, 0 fixed, 1 fail, 0 unknown, 0 skip\n")
    assert [(c["name"], c["argv"]) for c in r.calls()] == [("id", ["-u"]), ("sudo", ["-v"])]


@pytest.mark.parametrize("state,absent,line", [
    (linux_state(), LINUX_ABSENT, "PASS platform: linux/apt"),
    (linux_state(), {"apt-get", "sntp"}, "PASS platform: linux/dnf"),
    (linux_state(), {"apt-get", "dnf", "sntp"},
     "PASS platform: linux (no apt-get/dnf: packages must be installed by hand)"),
    (mac_state(), MAC_ABSENT, "PASS platform: macOS 26.5.2"),
], ids=["apt", "dnf", "no-package-manager", "macos"])
def test_platform_lines(state, absent, line):
    args = MAC_ARGS if state["os"] == "Darwin" else LINUX_ARGS
    r = run(args, state, absent)
    assert r.lines[0] == line
    assert r.status("platform") == line


def test_sudo_v_runs_once_with_apply_before_any_check():
    r = run(LINUX_ARGS + ["--apply"])
    names = [(c["name"], c["argv"]) for c in r.calls()]
    assert names.count(("sudo", ["-v"])) == 1
    assert names.index(("id", ["-u"])) < names.index(("sudo", ["-v"])) < names.index(("uname", ["-s"]))
    assert r.lines[-1].startswith("summary: ")
    assert r.rc == 0


def test_check_mode_never_runs_sudo_v():
    r = run(LINUX_ARGS)
    assert r.named("sudo", "-v") == []
    assert r.lines[-1].startswith("summary: ")
    assert r.rc == 0


# ---------------------------------------------------------------------------
# Task 4: packages and clock (H4b, H4c, H11, H20, H25, P13a)
# ---------------------------------------------------------------------------

APT_FIX = "sudo apt-get update && sudo apt-get install -y python3 git python3-pytest"


def test_packages_linux_check_mode_reports_every_missing_item():
    r = run(LINUX_ARGS, linux_state(py_ok=False, pytest_ok=False), ALL_FAIL_ABSENT)
    assert r.status("packages") == "FAIL packages: missing: python3 >= 3.9, git, pytest"
    assert r.fix_after("packages") == "  fix: " + APT_FIX
    assert mutating(r.calls()) == []
    assert r.rc == 1


def test_packages_apt_fix_runs_update_then_install():
    r = run(LINUX_ARGS + ["--apply"], linux_state(py_ok=False, pytest_ok=False), ALL_FAIL_ABSENT)
    assert plus_lines(r.out) == ["+ sudo apt-get update",
                                 "+ sudo apt-get install -y python3 git python3-pytest"]
    assert r.status("packages") == "FIXED packages: python3 >= 3.9, git, pytest"
    assert r.rc == 0


def test_packages_dnf_fix():
    r = run(LINUX_ARGS + ["--apply"], linux_state(py_ok=False), {"apt-get", "sntp", "git"})
    assert r.status("platform") == "PASS platform: linux/dnf"
    assert plus_lines(r.out) == ["+ sudo dnf install -y python3 git python3-pytest"]
    assert r.status("packages") == "FIXED packages: python3 >= 3.9, git, pytest"
    assert r.rc == 0


def test_h4b_packages_fix_exit_keeps_the_pre_fix_detail():
    r = run(LINUX_ARGS + ["--apply"],
            linux_state(py_ok=False, pytest_ok=False, fix={"packages": "exit:100"}), ALL_FAIL_ABSENT)
    assert r.status("packages") == "FAIL packages: missing: python3 >= 3.9, git, pytest (fix exited 100)"
    assert r.fix_after("packages") == "  fix: " + APT_FIX
    assert r.rc == 1


def test_h4c_apt_update_failure_stops_the_install():
    r = run(LINUX_ARGS + ["--apply"],
            linux_state(py_ok=False, pytest_ok=False, fix={"apt_update": "exit:100"}), ALL_FAIL_ABSENT)
    assert plus_lines(r.out) == ["+ sudo apt-get update"]
    assert r.named("apt-get", "install") == []
    assert r.status("packages").endswith("(fix exited 100)")
    assert r.rc == 1


def test_packages_without_a_package_manager_has_no_automatic_fix():
    for extra in ([], ["--apply"]):
        r = run(LINUX_ARGS + extra, linux_state(), {"apt-get", "dnf", "sntp", "git"})
        assert r.status("packages") == "FAIL packages: missing: git"
        assert r.fix_after("packages") == ("  fix: install python3 (>= 3.9), git and pytest with this "
                                           "host's package manager, then re-run")
        assert plus_lines(r.out) == []
        assert r.rc == 1


def test_h25_macos_pip_installs_only_pytest():
    r = run(MAC_ARGS + ["--apply"], mac_state(pytest_ok=False), MAC_ABSENT)
    assert plus_lines(r.out) == ["+ python3 -m pip install --user pytest"]
    assert r.status("packages") == "FIXED packages: python3 >= 3.9, git, pytest"
    assert r.rc == 0


@pytest.mark.parametrize("state,absent,missing", [
    (mac_state(py_ok=False), MAC_ABSENT, "python3 >= 3.9, pytest"),
    (mac_state(), MAC_ABSENT | {"git"}, "git"),
], ids=["no-python", "no-git"])
def test_h25_macos_without_python_or_git_never_runs_xcode_select(state, absent, missing):
    r = run(MAC_ARGS + ["--apply"], state, absent)
    assert r.status("packages") == "FAIL packages: missing: " + missing
    assert r.fix_after("packages") == ("  fix: xcode-select --install (or install Python >= 3.9 "
                                       "from python.org), then re-run")
    assert r.named("xcode-select") == []
    assert plus_lines(r.out) == []
    assert r.rc == 1


SNTP_TAIL = " +/- 0.010472 time.apple.com 17.253.4.125"


@pytest.mark.parametrize("tok,ok", [
    ("+0.01", True), ("-0.25", True), ("+4.999", True), ("4", True),
    ("12.3", False), ("-7.5", False), ("5.0", False),
])
def test_h11_macos_clock_offsets(tok, ok):
    r = run(MAC_ARGS, mac_state(sntp_out=tok + SNTP_TAIL), MAC_ABSENT)
    if ok:
        assert r.status("clock") == "PASS clock: offset %s s from time.apple.com" % tok
        assert r.rc == 0
    else:
        assert r.status("clock") == "FAIL clock: offset %s s from time.apple.com (limit 5 s)" % tok
        assert r.fix_after("clock") == "  fix: sudo systemsetup -setusingnetworktime on"
        assert r.rc == 1
    assert mutating(r.calls()) == []


def test_h11_macos_clock_failures():
    r = run(MAC_ARGS, mac_state(sntp_out="garbage from sntp"), MAC_ABSENT)
    assert r.status("clock") == "FAIL clock: unparseable sntp output 'garbage from sntp'"
    r = run(MAC_ARGS, mac_state(sntp_exit=1), MAC_ABSENT)
    assert r.status("clock") == "FAIL clock: sntp failed (exit 1)"
    assert r.fix_after("clock") == "  fix: sudo systemsetup -setusingnetworktime on"
    r = run(MAC_ARGS + ["--apply"], mac_state(), MAC_ABSENT | {"sntp"})
    assert r.status("clock") == "FAIL clock: sntp not found"
    assert r.fix_after("clock") == ("  fix: turn on System Settings > General > Date & Time > "
                                    "Set time and date automatically")
    assert r.named("systemsetup") == []
    assert r.rc == 1


def test_h11_macos_clock_fix():
    r = run(MAC_ARGS + ["--apply"],
            mac_state(sntp_out="12.3 +/- 0.01 time.apple.com 1.2.3.4"), MAC_ABSENT)
    assert plus_lines(r.out) == ["+ sudo systemsetup -setusingnetworktime on"]
    assert r.status("clock") == "FIXED clock: offset +0.001000 s from time.apple.com"
    assert r.rc == 0


def test_linux_clock_check_mode():
    r = run(LINUX_ARGS, linux_state(clock_linux="no"))
    assert r.status("clock") == "FAIL clock: NTPSynchronized=no"
    assert r.fix_after("clock") == "  fix: sudo timedatectl set-ntp true"
    assert mutating(r.calls()) == []
    assert r.rc == 1


def test_h20a_linux_clock_poll_waits_for_sync():
    r = run(LINUX_ARGS + ["--apply"], linux_state(clock_linux="no", lag={"clock": 3}))
    assert plus_lines(r.out) == ["+ sudo timedatectl set-ntp true"]
    assert r.status("clock") == "FIXED clock: NTPSynchronized=yes"
    assert len(r.named("sleep", "2")) == 3
    assert r.rc == 0


def test_h20b_linux_clock_poll_gives_up_after_15_rechecks():
    r = run(LINUX_ARGS + ["--apply"], linux_state(clock_linux="no", fix={"clock": "noop"}))
    assert r.status("clock") == "FAIL clock: NTPSynchronized=no (fix did not take)"
    assert r.fix_after("clock") == "  fix: sudo timedatectl set-ntp true"
    assert len(r.named("timedatectl", "show")) == 16
    assert len(r.named("sleep", "2")) == 14
    assert r.rc == 1


def test_h20c_linux_without_timedatectl():
    r = run(LINUX_ARGS + ["--apply"], linux_state(clock_linux="no"), LINUX_ABSENT | {"timedatectl"})
    assert r.status("clock") == "FAIL clock: timedatectl not found"
    assert r.fix_after("clock") == "  fix: enable NTP time synchronization on this host by hand, then re-run"
    assert r.named("sudo", "timedatectl") == []
    assert r.rc == 1


# ---------------------------------------------------------------------------
# Task 5: model and searxng (H9, H10, H13, H15, H26 lines, Review Focus 1, 2, 4, 5)
# ---------------------------------------------------------------------------

OLLAMA_PROBE = "http://127.0.0.1:11434/api/tags"
VLLM_PROBE = "http://127.0.0.1:8177/v1/models"
SEARXNG_DEFAULT = "http://127.0.0.1:8888/"


def shown(word):
    """A path as the script prints it in + and fix: lines (P10)."""
    return "'%s'" % word if " " in word else word


def model_curls(r):
    return [c for c in r.named("curl") if "-w" in c["argv"] and "-o" not in c["argv"]]


def searxng_curls(r):
    return [c for c in r.named("curl") if "-o" in c["argv"]]


def compose_plus_lines(r, docker="docker"):
    sx = r.sx
    return ["+ mkdir -p %s" % shown(sx),
            "+ cp %s %s %s" % (shown(WS + "/searxng/docker-compose.yml"), shown(WS + "/searxng/settings.yml"),
                               shown(sx + "/")),
            "+ %s compose -p qwen-agent-searxng -f %s up -d" % (docker, shown(sx + "/docker-compose.yml"))]


def assert_searxng_copied(r):
    for name in ("docker-compose.yml", "settings.yml"):
        with open(os.path.join(WS, "searxng", name), "rb") as f:
            want = f.read()
        with open(os.path.join(r.sx, name), "rb") as f:
            assert f.read() == want, name


def test_h15a_model_probe_urls_come_from_fleet_lib():
    r = run(LINUX_ARGS)
    assert [c["argv"][-1] for c in model_curls(r)] == [OLLAMA_PROBE]
    assert r.status("model") == "PASS model: 'qwen3.5:9b' served by ollama at " + OLLAMA_PROBE
    r = run(MAC_ARGS, mac_state(), MAC_ABSENT)
    assert [c["argv"][-1] for c in model_curls(r)] == [VLLM_PROBE]
    assert r.status("model") == "PASS model: 'qwen38-6bit' served by vllm at " + VLLM_PROBE
    r = run(LINUX_ARGS + ["--model-url", "http://127.0.0.1:11434"])
    assert [c["argv"][-1] for c in model_curls(r)] == [OLLAMA_PROBE]
    assert r.rc == 0


def test_model_missing_check_mode():
    r = run(LINUX_ARGS, linux_state(model="missing"))
    assert r.status("model") == ("FAIL model: 'qwen3.5:9b' not served by ollama at %s "
                                 "(serving: other-model:1b)" % OLLAMA_PROBE)
    assert r.fix_after("model") == "  fix: ollama pull qwen3.5:9b"
    assert r.named("ollama") == []
    assert r.rc == 1


def test_model_pull_streams_and_rechecks():
    r = run(LINUX_ARGS + ["--apply"], linux_state(model="missing"))
    fixed = "FIXED model: 'qwen3.5:9b' served by ollama at " + OLLAMA_PROBE
    assert plus_lines(r.out) == ["+ ollama pull qwen3.5:9b"]
    assert r.lines.index("+ ollama pull qwen3.5:9b") < r.lines.index("pulling manifest") < r.lines.index(fixed)
    assert len(model_curls(r)) == 2
    assert r.rc == 0


def test_h15c_model_server_down_is_never_pulled():
    r = run(LINUX_ARGS + ["--apply"], linux_state(model="down"))
    assert r.status("model") == "FAIL model: ollama not reachable at %s (curl exit 7)" % OLLAMA_PROBE
    assert r.fix_after("model") == ("  fix: start the ollama model server at http://127.0.0.1:11434/v1; "
                                    "this script never starts model servers")
    assert r.named("ollama") == []
    assert r.rc == 1


def test_h15d_ollama_cli_absent():
    r = run(LINUX_ARGS + ["--apply"], linux_state(model="missing"), LINUX_ABSENT | {"ollama"})
    assert r.status("model").startswith("FAIL model: 'qwen3.5:9b' not served by ollama")
    assert r.fix_after("model") == ("  fix: the ollama CLI is not on PATH; pull 'qwen3.5:9b' by hand "
                                    "(this script never installs Ollama)")
    assert r.rc == 1


def test_h15e_custom_ollama_url_is_never_pulled():
    r = run(LINUX_ARGS + ["--apply", "--model-url", "http://127.0.0.1:11500/v1"],
            linux_state(model="missing"))
    assert r.status("model") == ("FAIL model: 'qwen3.5:9b' not served by ollama at "
                                 "http://127.0.0.1:11500/api/tags (serving: other-model:1b)")
    assert r.fix_after("model") == "  fix: pull 'qwen3.5:9b' into the Ollama server at http://127.0.0.1:11500/v1 by hand"
    assert r.named("ollama") == []
    assert r.rc == 1


def test_h15f_pull_failure():
    r = run(LINUX_ARGS + ["--apply"], linux_state(model="missing", fix={"model": "exit:1"}))
    assert r.status("model") == ("FAIL model: 'qwen3.5:9b' not served by ollama at %s "
                                 "(serving: other-model:1b) (fix exited 1)" % OLLAMA_PROBE)
    assert r.fix_after("model") == "  fix: ollama pull qwen3.5:9b"
    assert r.rc == 1


def test_h15g_python3_absent():
    r = run(LINUX_ARGS, linux_state(), LINUX_ABSENT | {"python3"})
    assert r.status("model") == "FAIL model: python3 cannot load fleet_lib from " + WS
    assert r.fix_after("model") == ("  fix: needs python3 >= 3.9 (see packages) and %s/fleet_lib.py "
                                    "from a complete checkout" % WS)
    assert model_curls(r) == []
    assert r.rc == 1


def test_h10_vllm_missing_model_is_never_fixed():
    r = run(MAC_ARGS + ["--apply"], mac_state(model="missing"), MAC_ABSENT)
    assert r.status("model") == ("FAIL model: 'qwen38-6bit' not served by vllm at %s "
                                 "(serving: other-model:1b)" % VLLM_PROBE)
    assert r.fix_after("model") == ("  fix: start vllm-metal serving 'qwen38-6bit' at http://127.0.0.1:8177/v1 "
                                    "by hand; this script never starts, restarts or pulls for vLLM")
    assert r.named("ollama") == [] and r.named("docker") == []
    assert r.rc == 1


def test_searxng_check_mode_fix_line_runs_no_docker():
    for groups, d in (("tester docker", "docker"), ("tester", "sudo docker")):
        r = run(LINUX_ARGS, linux_state(searxng="down", groups=groups))
        assert r.status("searxng") == "FAIL searxng: no answer at %s (curl exit 7)" % SEARXNG_DEFAULT
        sx = r.sx
        assert r.fix_after("searxng") == (
            "  fix: %s start qwen-agent-searxng if that container exists, else: mkdir -p %s && cp %s %s %s && "
            "%s compose -p qwen-agent-searxng -f %s up -d (or re-run with --apply)"
            % (d, shown(sx), shown(WS + "/searxng/docker-compose.yml"), shown(WS + "/searxng/settings.yml"),
               shown(sx + "/"), d, shown(sx + "/docker-compose.yml")))
        assert r.named("docker") == [] and mutating(r.calls()) == []
        assert not os.path.exists(r.sx)
        assert r.rc == 1


def test_h9a_compose_in_docker_group():
    r = run(LINUX_ARGS + ["--apply"], linux_state(searxng="down"))
    assert plus_lines(r.out) == compose_plus_lines(r)
    assert r.named("docker", "ps") != [] and r.named("sudo", "-n", "docker") == []
    assert [c["rc"] for c in r.named("docker", "compose")] == [0]
    assert r.status("searxng") == "FIXED searxng: HTTP 200 at " + SEARXNG_DEFAULT
    assert_searxng_copied(r)
    assert r.rc == 0


def test_h9b_compose_outside_docker_group_uses_sudo():
    r = run(LINUX_ARGS + ["--apply"], linux_state(searxng="down", groups="tester"))
    assert ["-n", "docker", "ps", "-a", "--format", "{{.Names}}"] in [c["argv"] for c in r.named("sudo")]
    assert plus_lines(r.out) == compose_plus_lines(r, "sudo docker")
    assert r.status("searxng") == "FIXED searxng: HTTP 200 at " + SEARXNG_DEFAULT
    assert r.rc == 0


def test_h9c_existing_container_is_started():
    r = run(LINUX_ARGS + ["--apply"], linux_state(searxng="down", containers=["qwen-agent-searxng"]))
    assert plus_lines(r.out) == ["+ docker start qwen-agent-searxng"]
    assert r.named("docker", "compose") == []
    assert not os.path.exists(r.sx)
    assert r.status("searxng") == "FIXED searxng: HTTP 200 at " + SEARXNG_DEFAULT
    assert r.rc == 0


def test_h9d_docker_absent():
    r = run(LINUX_ARGS + ["--apply"], linux_state(searxng="down"), LINUX_ABSENT | {"docker"})
    assert r.status("searxng") == ("FAIL searxng: no answer at %s (curl exit 7); Docker not installed "
                                   "(this script never installs Docker)" % SEARXNG_DEFAULT)
    assert r.fix_after("searxng") == ("  fix: install Docker, or use another SearXNG instance through "
                                      "QWEN_AGENT_SEARXNG_URL (fleet spec R0), then re-run")
    assert r.named("docker") == [] and plus_lines(r.out) == []
    assert r.rc == 1


def test_h9e_searxng_poll_waits_for_the_container():
    r = run(LINUX_ARGS + ["--apply"], linux_state(searxng="down", lag={"searxng": 5}))
    assert r.status("searxng") == "FIXED searxng: HTTP 200 at " + SEARXNG_DEFAULT
    assert len(r.named("sleep", "1")) == 5
    assert r.rc == 0


def test_h9f_searxng_poll_gives_up_after_30_probes():
    r = run(LINUX_ARGS + ["--apply"], linux_state(searxng="down", fix={"searxng": "noop"}))
    assert r.status("searxng") == ("FAIL searxng: no answer at %s (curl exit 7) (fix did not take)"
                                   % SEARXNG_DEFAULT)
    assert r.fix_after("searxng") == "  fix: " + " && ".join(l[2:] for l in compose_plus_lines(r))
    assert len(searxng_curls(r)) == 31
    assert len(r.named("sleep", "1")) == 29
    assert r.rc == 1


def test_h9g_docker_ps_failure():
    r = run(LINUX_ARGS + ["--apply"], linux_state(searxng="down", docker_ps_exit=1))
    assert r.status("searxng") == ("FAIL searxng: no answer at %s (curl exit 7); 'docker ps -a' failed "
                                   "(exit 1): is the Docker daemon running?" % SEARXNG_DEFAULT)
    assert r.fix_after("searxng") == "  fix: start Docker, then re-run"
    assert r.named("docker", "compose") == [] and plus_lines(r.out) == []
    assert r.rc == 1


def test_h13_custom_searxng_url_runs_no_docker():
    r = run(LINUX_ARGS + ["--apply", "--searxng-url", "http://127.0.0.1:9999/"],
            linux_state(searxng="down"))
    assert r.status("searxng") == "FAIL searxng: no answer at http://127.0.0.1:9999/ (curl exit 7)"
    fix = r.fix_after("searxng")
    assert "QWEN_AGENT_SEARXNG_URL" in fix and "no_proxy" in fix
    assert fix == ("  fix: check that http://127.0.0.1:9999/ is up and that no_proxy covers its host; if this "
                   "host cannot run SearXNG, set QWEN_AGENT_SEARXNG_URL with the systemd drop-in described "
                   "in R0 of the fleet spec")
    assert r.named("docker") == [] and plus_lines(r.out) == []
    assert r.rc == 1


def test_h26_no_searxng_skips_the_check():
    for extra in ([], ["--apply"]):
        r = run(LINUX_ARGS + ["--no-searxng"] + extra, linux_state(searxng="down"))
        assert r.status("searxng") == "SKIP searxng: disabled by --no-searxng"
        assert searxng_curls(r) == [] and len(model_curls(r)) == 1
        assert r.named("docker") == [] and plus_lines(r.out) == []
        assert not os.path.exists(r.sx)
        assert r.rc == 0


def test_review_focus_2_relative_invocation_from_another_directory():
    # R0 on .168: cd into the clone and run the script by a relative path.
    rel = os.path.join(os.path.basename(WS), "scripts", "fleet-host-prep.sh")
    r = run(LINUX_ARGS + ["--apply"], linux_state(searxng="down"),
            cwd=os.path.dirname(WS), script=rel)
    assert r.status("model") == "PASS model: 'qwen3.5:9b' served by ollama at " + OLLAMA_PROBE
    assert plus_lines(r.out) == compose_plus_lines(r)
    assert_searxng_copied(r)
    assert r.rc == 0


def test_review_focus_5_home_with_a_space():
    r = run(LINUX_ARGS + ["--apply"], linux_state(searxng="down"), home_name="home dir")
    assert " " in r.sx
    assert plus_lines(r.out) == compose_plus_lines(r)
    assert plus_lines(r.out)[0] == "+ mkdir -p '%s'" % r.sx
    assert r.status("searxng") == "FIXED searxng: HTTP 200 at " + SEARXNG_DEFAULT
    assert_searxng_copied(r)
    assert r.rc == 0


def test_review_focus_1_hugging_face_model_id():
    name = "DreamFast/Qwen3-VL-4b-Heretic"
    r = run(["--model-server-type", "vllm", "--model", name, "--no-searxng"],
            mac_state(model_name=name), MAC_ABSENT)
    assert r.status("model") == "PASS model: '%s' served by vllm at %s" % (name, VLLM_PROBE)
    assert r.status("searxng") == "SKIP searxng: disabled by --no-searxng"
    assert r.rc == 0


def test_review_focus_4_model_url_answering_404():
    # A vLLM --model-url without /v1 probes /models, which vLLM answers with 404.
    r = run(MAC_ARGS + ["--apply", "--model-url", "http://127.0.0.1:8177"],
            mac_state(model_code=404), MAC_ABSENT)
    assert r.status("model") == "FAIL model: vllm not reachable at http://127.0.0.1:8177/models (HTTP 404)"
    assert r.fix_after("model") == ("  fix: start the vllm model server at http://127.0.0.1:8177; "
                                    "this script never starts model servers")
    assert plus_lines(r.out) == []
    assert r.rc == 1


# ---------------------------------------------------------------------------
# Task 6: firewall (H6 accepted values, H8, H16-H19)
# ---------------------------------------------------------------------------

LAN = "192.168.1.0/24"
SFW_ON = "Firewall is enabled. (State = 1)"


def rich(port, proto, cidr=LAN):
    return 'rule family="ipv4" source address="%s" port port="%s" protocol="%s" accept' % (cidr, port, proto)


def rich_plus(port, proto):
    return "+ sudo firewall-cmd --permanent --add-rich-rule='%s'" % rich(port, proto)


FWD_ABSENT = LINUX_ABSENT | {"ufw"}


def rich_rule_adds(r):
    return [c for c in r.named("firewall-cmd") if any(a.startswith("--add-rich-rule=") for a in c["argv"])]


def test_h8_ufw_unreadable_without_sudo_is_unknown():
    r = run(LINUX_ARGS, linux_state(sudo_n_ok=False))
    assert r.status("firewall") == "UNKNOWN firewall: cannot read ufw rules without sudo"
    assert r.fix_after("firewall") == "  fix: run 'sudo -v' first, or use --apply"
    assert r.rc == 1
    r = run(LINUX_ARGS + ["--apply"], linux_state(sudo_n_ok=False))
    assert r.status("firewall") == "UNKNOWN firewall: cannot read ufw rules without sudo"
    assert r.fix_after("firewall") == "  fix: 'sudo -n' failed even after 'sudo -v'; run 'sudo ufw status' by hand"
    assert r.named("ufw", "allow") == [] and plus_lines(r.out) == []
    assert r.rc == 1


@pytest.mark.parametrize("rows", [
    [ufw_row("8190", "ALLOW", LAN)],
    [ufw_row("8190/tcp", "ALLOW", LAN), ufw_row("8190/udp", "ALLOW", LAN)],
    [ufw_row("8190", "ALLOW", "Anywhere")],
    [ufw_row("8190", "ALLOW", LAN, " # fleet")],
], ids=["port", "tcp-and-udp", "anywhere", "comment"])
def test_h16_ufw_rules_that_admit_the_lan(rows):
    r = run(LINUX_ARGS, linux_state(ufw_out=UFW_HEAD + "".join(rows)))
    assert r.status("firewall") == "PASS firewall: ufw allows 8190 tcp+udp from " + LAN
    assert r.rc == 0


@pytest.mark.parametrize("rows,missing", [
    ([ufw_row("8190/tcp", "ALLOW", LAN)], "udp"),
    ([ufw_row("8190 (v6)", "ALLOW", "Anywhere (v6)")], "tcp, udp"),
    ([ufw_row("8190", "DENY", LAN)], "tcp, udp"),
    ([ufw_row("8190", "ALLOW OUT", LAN)], "tcp, udp"),
    ([ufw_row("8190", "ALLOW", "10.0.0.0/8")], "tcp, udp"),
    ([ufw_row("8190 on eth0", "ALLOW", LAN)], "tcp, udp"),
], ids=["tcp-only", "v6-only", "deny", "allow-out", "other-network", "interface"])
def test_h16_ufw_rules_that_do_not(rows, missing):
    r = run(LINUX_ARGS, linux_state(ufw_out=UFW_HEAD + "".join(rows)))
    assert r.status("firewall") == "FAIL firewall: ufw active; no rule allows 8190 %s from %s" % (missing, LAN)
    assert r.fix_after("firewall") == "  fix: sudo ufw allow from 192.168.1.0/24 to any port 8190"
    assert mutating(r.calls()) == []
    assert r.rc == 1


def test_h16_ufw_status_variants():
    r = run(LINUX_ARGS, linux_state(ufw_out="Status: inactive\n"))
    assert r.status("firewall") == "PASS firewall: ufw inactive"
    r = run(LINUX_ARGS, linux_state(), LINUX_ABSENT | {"ufw"})
    assert r.status("firewall") == "PASS firewall: no host firewall active"
    assert r.rc == 0
    r = run(LINUX_ARGS, linux_state(ufw_out="weird"))
    assert r.status("firewall") == "FAIL firewall: unrecognized 'ufw status' output 'weird'"
    assert r.fix_after("firewall") == "  fix: check 'sudo ufw status' by hand"
    assert r.rc == 1


def test_h16_non_default_port():
    args = LINUX_ARGS + ["--port", "8191"]
    r = run(args, linux_state())
    assert r.status("firewall") == "FAIL firewall: ufw active; no rule allows 8191 tcp, udp from " + LAN
    assert r.fix_after("firewall") == "  fix: sudo ufw allow from 192.168.1.0/24 to any port 8191"
    r = run(args, linux_state(ufw_out=UFW_HEAD + ufw_row("8191", "ALLOW", LAN)))
    assert r.status("firewall") == "PASS firewall: ufw allows 8191 tcp+udp from " + LAN
    r = run(args, linux_state(ufw_out=UFW_HEAD + ufw_row("8191/tcp", "ALLOW", LAN) + ufw_row("8190/udp", "ALLOW", LAN)))
    assert r.status("firewall") == "FAIL firewall: ufw active; no rule allows 8191 udp from " + LAN
    r = run(args + ["--apply"], linux_state())
    assert plus_lines(r.out) == ["+ sudo ufw allow from 192.168.1.0/24 to any port 8191"]
    assert r.status("firewall") == "FIXED firewall: ufw allows 8191 tcp+udp from " + LAN
    assert r.rc == 0


def test_h17a_firewalld_adds_both_rules_then_reloads():
    r = run(LINUX_ARGS + ["--apply"], linux_state(firewalld="running"), FWD_ABSENT)
    assert plus_lines(r.out) == [rich_plus("8190", "tcp"), rich_plus("8190", "udp"), "+ sudo firewall-cmd --reload"]
    assert plus_lines(r.out)[0] == ("+ sudo firewall-cmd --permanent --add-rich-rule='rule family=\"ipv4\" "
                                    "source address=\"192.168.1.0/24\" port port=\"8190\" protocol=\"tcp\" accept'")
    assert r.status("firewall") == "FIXED firewall: firewalld allows 8190 tcp+udp from " + LAN
    assert r.rc == 0


def test_h17b_firewalld_adds_only_the_missing_rule():
    r = run(LINUX_ARGS + ["--apply"], linux_state(firewalld="running", firewalld_rules=[rich("8190", "tcp")]),
            FWD_ABSENT)
    assert plus_lines(r.out) == [rich_plus("8190", "udp"), "+ sudo firewall-cmd --reload"]
    assert r.status("firewall") == "FIXED firewall: firewalld allows 8190 tcp+udp from " + LAN


def test_h17_firewalld_check_mode():
    r = run(LINUX_ARGS, linux_state(firewalld="running"), FWD_ABSENT)
    assert r.status("firewall") == "FAIL firewall: firewalld running; missing rich rules for 8190 tcp, udp from " + LAN
    assert r.fix_after("firewall") == "  fix: " + " && ".join(
        l[2:] for l in (rich_plus("8190", "tcp"), rich_plus("8190", "udp"), "+ sudo firewall-cmd --reload"))
    assert mutating(r.calls()) == []
    assert r.rc == 1


def test_h17c_firewalld_unreadable_without_sudo():
    r = run(LINUX_ARGS, linux_state(firewalld="running", sudo_n_ok=False), FWD_ABSENT)
    assert r.status("firewall") == "UNKNOWN firewall: cannot read firewalld rules without sudo"
    assert r.fix_after("firewall") == "  fix: run 'sudo -v' first, or use --apply"
    r = run(LINUX_ARGS + ["--apply"], linux_state(firewalld="running", sudo_n_ok=False), FWD_ABSENT)
    assert r.fix_after("firewall") == ("  fix: 'sudo -n' failed even after 'sudo -v'; run "
                                       "'sudo firewall-cmd --permanent --list-rich-rules' by hand")
    assert rich_rule_adds(r) == [] and plus_lines(r.out) == []
    assert r.rc == 1


def test_h17d_firewalld_non_default_port_leaves_8190_alone():
    rules = [rich("8190", "tcp"), rich("8190", "udp")]
    r = run(LINUX_ARGS + ["--port", "8191", "--apply"], linux_state(firewalld="running", firewalld_rules=rules),
            FWD_ABSENT)
    assert plus_lines(r.out) == [rich_plus("8191", "tcp"), rich_plus("8191", "udp"), "+ sudo firewall-cmd --reload"]
    assert r.status("firewall") == "FIXED firewall: firewalld allows 8191 tcp+udp from " + LAN
    assert r.state["firewalld_rules"] == rules + [rich("8191", "tcp"), rich("8191", "udp")]


def test_h18_ufw_and_firewalld_both_active():
    r = run(LINUX_ARGS + ["--apply"], linux_state(firewalld="running"))
    assert r.status("firewall") == "FAIL firewall: ufw and firewalld are both active"
    assert r.fix_after("firewall") == (
        "  fix: allow TCP and UDP 8190 from 192.168.1.0/24 in both firewalls by hand: sudo ufw allow from "
        "192.168.1.0/24 to any port 8190; and the two firewalld rich rules and reload shown in the "
        "fleet-host-prep spec P15")
    assert r.named("ufw", "allow") == [] and rich_rule_adds(r) == []
    assert r.rc == 1
    r = run(LINUX_ARGS + ["--apply", "--port", "8191"], linux_state(firewalld="running"))
    fix = r.fix_after("firewall")
    assert "to any port 8191" in fix and "8190" not in fix


@pytest.mark.parametrize("extra", [[], ["--port", "8191"]], ids=["default-port", "port-8191"])
def test_h19_macos_application_firewall(extra):
    exe = PYTHON_EXE
    r = run(MAC_ARGS + extra, mac_state(sfw_global=SFW_ON, sfw_apps=[[exe, "allow"]]), MAC_ABSENT)
    assert r.status("firewall") == "PASS firewall: application firewall on; %s allowed" % exe
    assert [c["argv"] for c in r.named("socketfilterfw")] == [["--getglobalstate"], ["--getblockall"], ["--listapps"]]
    assert r.rc == 0
    r = run(MAC_ARGS + extra + ["--apply"], mac_state(sfw_global=SFW_ON), MAC_ABSENT)
    assert plus_lines(r.out) == ["+ sudo %s --add %s" % (r.sfw, exe), "+ sudo %s --unblockapp %s" % (r.sfw, exe)]
    assert r.status("firewall") == "FIXED firewall: application firewall on; %s allowed" % exe
    assert r.rc == 0


def test_h19c_listed_but_blocked_is_only_unblocked():
    r = run(MAC_ARGS + ["--apply"], mac_state(sfw_global=SFW_ON, sfw_apps=[[PYTHON_EXE, "block"]]), MAC_ABSENT)
    assert plus_lines(r.out) == ["+ sudo %s --unblockapp %s" % (r.sfw, PYTHON_EXE)]
    assert r.status("firewall") == "FIXED firewall: application firewall on; %s allowed" % PYTHON_EXE


def test_h19d_another_python_does_not_count():
    r = run(MAC_ARGS, mac_state(sfw_global=SFW_ON, sfw_apps=[["/usr/bin/python3", "allow"]]), MAC_ABSENT)
    assert r.status("firewall") == "FAIL firewall: application firewall on; %s not allowed" % PYTHON_EXE
    assert r.fix_after("firewall") == "  fix: sudo %s --add %s && sudo %s --unblockapp %s" % (
        r.sfw, PYTHON_EXE, r.sfw, PYTHON_EXE)
    assert mutating(r.calls()) == []
    assert r.rc == 1


@pytest.mark.parametrize("state", [
    mac_state(sfw_global=SFW_ON, sfw_blockall="Firewall has block all state set to enabled."),
    mac_state(sfw_global="Firewall is blocking all non-essential incoming connections. (State = 2)"),
], ids=["blockall-enabled", "state-2"])
def test_h19e_block_all_is_never_changed(state):
    r = run(MAC_ARGS + ["--apply"], state, MAC_ABSENT)
    assert r.status("firewall") == "FAIL firewall: block all incoming connections is on"
    assert r.fix_after("firewall") == ("  fix: turn off System Settings > Network > Firewall > Options > Block all "
                                       "incoming connections; this script never changes it")
    assert r.named("socketfilterfw", "--add") == [] and plus_lines(r.out) == []
    assert r.rc == 1


def test_h19f_unrecognized_or_missing_socketfilterfw():
    r = run(MAC_ARGS, mac_state(sfw_global="gibberish"), MAC_ABSENT)
    assert r.status("firewall") == "FAIL firewall: unrecognized socketfilterfw output 'gibberish'"
    assert r.fix_after("firewall") == "  fix: check System Settings > Network > Firewall by hand"
    r = run(MAC_ARGS, mac_state(), MAC_ABSENT | {"socketfilterfw"})
    assert r.status("firewall") == "FAIL firewall: %s not found" % r.sfw
    assert r.fix_after("firewall") == "  fix: check System Settings > Network > Firewall by hand"
    assert r.rc == 1


def test_macos_firewall_on_without_python3():
    r = run(MAC_ARGS, mac_state(sfw_global=SFW_ON), MAC_ABSENT | {"python3"})
    assert r.status("firewall") == "FAIL firewall: cannot resolve the python3 binary"
    assert r.fix_after("firewall") == "  fix: fix the packages check first, then re-run"
    assert r.rc == 1


@pytest.mark.parametrize("extra,row", [
    (["--lan-cidr", "10.0.0.0/8"], ufw_row("8190", "ALLOW", "10.0.0.0/8")),
    (["--port", "1024"], ufw_row("1024", "ALLOW", LAN)),
    (["--port", "65535"], ufw_row("65535", "ALLOW", LAN)),
], ids=["cidr-10/8", "port-1024", "port-65535"])
def test_h6_accepted_values(extra, row):
    r = run(LINUX_ARGS + extra, linux_state(ufw_out=UFW_HEAD + row))
    assert r.status("firewall").startswith("PASS firewall: ufw allows ")
    assert r.rc == 0
