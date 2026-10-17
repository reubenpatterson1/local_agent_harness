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
