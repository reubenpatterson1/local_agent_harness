# Fleet Host Prep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `scripts/fleet-host-prep.sh`, one bash script that checks the seven fleet rollout R0 prerequisites (platform, packages, clock, model, searxng, firewall, linger) on macOS and Ubuntu and, with `--apply`, fixes each failing one, plus `tests/test_fleet_host_prep.py`, which runs the real script against fakes only.

**Architecture:** One bash file with no arrays and no external utilities beyond `dirname`, `mkdir`, `cp` and the commands each check reads or fixes with. A shared `run_check` driver applies the spec's P12 protocol to seven check functions: `ck_NAME` runs the read-only test and picks the fix, `t_NAME` repeats the test for the re-check, and each fix function lists its commands through `step`, so the printed `fix:` line and the commands `--apply` runs come from one list. The tests run the real script under `/bin/bash` with `PATH` set to a stub directory of bash wrappers around one Python dispatcher (`FAKEBIN`) that logs every call and keeps the fake host's state in JSON.

**Tech Stack:** bash 3.2.57 (`/bin/bash`, macOS) and bash 5.2.21 (Ubuntu 24.04); Python 3.13.0 with pytest 8.3.4 (Mac) and Python 3.12.3 with pytest 9.0.2 (.168), standard library only; the existing `fleet_lib.py` (`probe_url`, `parse_loaded_models`), unchanged.

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-10-17-fleet-host-prep-design.md` (commit `2182f41`, branch `qwen-agent-redteam`; the later commit `05ecb0b` changed only live step L6, which this plan's acceptance section follows). The spec is binding; this plan changes no design decision. Where the spec is silent or contradicts itself, the ruling is listed in "Plan decisions" at the end, and each ruling is pinned by code shown in its task.

## Global Constraints

Copied verbatim from the spec. Every task's requirements include this section.

- (0.2) No other file changes. In particular, nothing under `scripts/deploy/` changes: that directory is the ltx-chain package, and [FLEET] T72 requires it to be unchanged. The script must not be placed there.
- (P1) `scripts/fleet-host-prep.sh`, mode `0755` (git records the executable bit). The first line is exactly `#!/usr/bin/env bash`.
- (P2) The script must behave identically under bash 3.2.57 and bash 5.2.
- (P2) Forbidden constructs: `declare -A`, `local -A`, `typeset -A`; `mapfile`, `readarray`; `${x,}`, `${x,,}`, `${x^}`, `${x^^}`; `|&`, `;&`, `;;&`; `coproc`; negative array indices; `declare -n` and `local -n` (namerefs); `[[ -v`; `&>>`; `{var}>` file-descriptor allocation; `${x@Q}` and other `@` transforms; `shopt -s globstar`; `wait -n`; `$EPOCHSECONDS`, `$EPOCHREALTIME`.
- (P2) **No arrays at all.** No `name=(...)` assignment, no `declare -a`, `local -a` or `read -a`. Reading `${BASH_REMATCH[1]}` and `${BASH_SOURCE[0]}` is allowed. Lists of command words travel as function positional parameters (`"$@"`).
- (P2) Regexes used with `[[ ... =~ ... ]]` are stored in a variable and used unquoted on the right-hand side (`[[ $x =~ $re ]]`).
- (P2) Assignments that capture an exit status are written as `out=$(cmd); rc=$?` with `out` declared earlier (`local out rc` on its own line). `local out=$(cmd)` loses the status.
- (P3) Near the top: `set -u` and `set -o pipefail`. **Never** `set -e`: every check must run even after another fails. Then `export LC_ALL=C`. There are no `trap`s.
- (P4) Apart from the commands each check reads or fixes with (Sections 3-4), the only external utilities the script uses are `dirname`, `mkdir` and `cp`. Everything else (string tests, parsing, loops, arithmetic) uses bash builtins. In particular there is no `grep`, `sed`, `awk`, `cat`, `tr`, `head`, `cut` or `mktemp`.
- (P4) Messages always name the script literally as `fleet-host-prep.sh`, never `$0`.
- (P8) The strings `api/tags` and `/models` must not appear anywhere in the script, comments included (H15 checks this), so that the URL logic lives only in `fleet_lib`.
- (P9) **Invariant:** plain `sudo` (with neither `-v` nor `-n`) appears only in fix commands.
- (3.4) Every `curl` call starts with exactly `curl -sS --noproxy '*' --max-time 5` (every probe is loopback or LAN, and the Mac runs Netskope). `sntp` is called as `sntp -t 3 time.apple.com`.
- (P17) The script never contains the strings `fleet.env`, `QWEN_AGENT_FLEET` or `.config/qwen-agent`. It reads no environment variable except `HOME`, `PATH` and `FLEET_PREP_SOCKETFILTERFW`. It never runs `qwen-agentd`.
- (6.1) pytest, stdlib only. The file must pass on the Mac (bash 3.2, Python 3.13, pytest 8.3.4) and on .168 (bash 5.2, Python 3.12, pytest 9.0.2). The suite must take under 120 s on the Mac.
- (6.1) `ENV` is built from scratch and never copies `os.environ`. The real HOME is never used, and no real sudo, apt, dnf, docker, ufw, firewall-cmd, loginctl, timedatectl, systemsetup, socketfilterfw, sntp, ollama or pip ever runs.
- (S5) No test that passed before the change fails after it ([FLEET] T70 procedure).

Plan execution rules (this plan's, not the spec's):

- `WS` = `/Users/reubenpatterson/local_agent_harness/qwen-agent-workspace`. Run every command from `WS` unless a step says otherwise. The git root is one level up, so `git status` paths carry the `qwen-agent-workspace/` prefix. Branch `qwen-agent-redteam`.
- Run tests as `python3 -m pytest tests/test_fleet_host_prep.py -q -p no:cacheprovider` (Python 3.13.0, pytest 8.3.4). Every run first prints a `pytest_asyncio` `PytestDeprecationWarning` about `asyncio_default_fixture_loop_scope`; it is expected and is not a failure. macOS has no `timeout` command; do not use it.
- Never run `scripts/fleet-host-prep.sh` directly on this Mac while executing Tasks 1-8: `--apply` calls real `sudo`, `docker`, `ufw` and more. Only the test file runs it, always with the stub `PATH`. Live runs are the human-run acceptance section at the end.
- Every code block in this plan is copied exactly, byte for byte, with the Write or Edit tool. A block marked "append" is added at the very end of the file and begins with the empty lines shown in the block. A block marked "insert" replaces the two anchor lines shown with the block, which ends with the same two anchor lines. Never retype a block from the spec when this plan shows it.
- The two files this plan creates are the only files any task stages: `git add scripts/fleet-host-prep.sh tests/test_fleet_host_prep.py`, then check `git diff --cached --name-only` before each commit. The working tree has unrelated untracked paths (`../.DS_Store`, `../.claude/`, `../agent/__pycache__/`, `../bin/`); never stage them. Every commit message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Measured on this Mac on 2026-10-17 with the exact code below: the test file grows 28 -> 36 -> 58 -> 81 -> 111 -> 125 tests over Tasks 2-7 and takes about 1, 2, 12, 35, 62 and 80 s. All 125 pass under `/bin/bash` 3.2.57.

## Review Focus

The five input classes below are implied by the spec, are the ones most likely to hit a real user first, and no spec H-test exercises them. Each is pinned by a test in the task that owns its code.

1. **A Hugging Face model id with a `/`** (`--model DreamFast/Qwen3-VL-4b-Heretic`, live step L6 on vision-185). Expected: the name passes through `PY_HAS_MODEL` and every message unchanged, so the line is `PASS model: 'DreamFast/Qwen3-VL-4b-Heretic' served by vllm at http://127.0.0.1:8177/v1/models`. Test: `test_review_focus_1_hugging_face_model_id` (Task 5).
2. **The script run by a relative path from another directory** (`cd /tmp/qa-prep && bash qwen-agent-workspace/scripts/fleet-host-prep.sh ...`). Expected: `WS` still resolves to the checkout, so `fleet_lib` loads and `--apply` copies the checkout's own `searxng/` files. Test: `test_review_focus_2_relative_invocation_from_another_directory` (Task 5).
3. **An empty value from an unset shell variable** (`--model "$M"` with `M` unset, likewise `--model-server-type`, `--lan-cidr`, `--port`). Expected: the same usage error as a missing or invalid value, exit 2, no system command run. Test: `test_review_focus_3_empty_values_from_unset_variables` (Task 2).
4. **A model URL whose server answers non-200** (a vLLM `--model-url http://127.0.0.1:8177` without `/v1` probes `/models`, which vLLM answers with 404). Expected: `FAIL model: vllm not reachable at http://127.0.0.1:8177/models (HTTP 404)`, which shows the probed URL so the user sees the missing `/v1`; no fix runs. Test: `test_review_focus_4_model_url_answering_404` (Task 5).
5. **A HOME path that contains a space.** Expected: the fix commands receive the path as one argument and work, and the `+` lines quote it (`+ mkdir -p '<SX>'`) so they stay copy-pasteable. Test: `test_review_focus_5_home_with_a_space` (Task 5).

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `scripts/fleet-host-prep.sh` | Create (Task 2), extend (Tasks 3-7); mode 0755 | The script: constants, helpers, the seven checks, CLI parsing and validation, root refusal, `sudo -v`, the check sequence, the summary. |
| `tests/test_fleet_host_prep.py` | Create (Task 2), append (Tasks 3-7) | The harness (`FAKEBIN` dispatcher, wrappers, state, `run()`, assertion helpers) and every H-test of spec Section 6.3 plus the Review Focus tests. |

The script's section order at the end of Task 7, top to bottom (each section starts with a three-line `# ----` banner): header comment and shell options; Constants; Command-line helpers; Output and the check protocol; platform; packages; clock; model; searxng; firewall; linger; Argument parsing; Validation and defaults; Root refusal; sudo; The checks, in order; Summary and exit status. This is spec Section 8's order (constants, functions, parsing, validation, root check, `sudo -v`, checks, summary, exit). Two anchors stay fixed for every later edit: the two lines

```bash
# ---------------------------------------------------------------------------
# Argument parsing (P5)
```

(each task's new functions are inserted directly above them), and the `run_check ...` lines of the check sequence (each task adds its `run_check` line after the previous check's).

The check-function contract, used by every check (Task 3 defines it; Tasks 3-7 follow it):

- `ck_NAME` sets `CK_RESULT` (`pass`, `fail`, `unknown` or `skip`) and `CK_DETAIL`. After `fail` or `unknown` it also sets `CK_FIXLINE`, and when an automatic fix exists it calls `set_fix fix_NAME...` (which sets `CK_FIX` and builds `CK_FIXLINE` from the fix function's steps). It may set `CK_POLLS` and `CK_SLEEP` (defaults 1 and 0) for the re-check.
- `t_NAME` repeats only the read-only test and sets only `CK_RESULT` and `CK_DETAIL`. It must exist for every check that can have an automatic fix.
- A fix function is a list of `step WORD...` calls, every one but the last followed by `|| return`.

---

### Task 1: Baseline record (orchestrator; no code, no commit)

Implements S5's "before" half ([FLEET] T70). Nothing is written into the repository.

**Files:**
- Create (outside git, excluded by `.git/info/exclude`, never staged): `/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-hostprep/base-commit.txt` and `baseline-pytest.txt`.

**Interfaces:** Consumes nothing. Produces the two baseline files that Task 8 compares against.

- [ ] **Step 1: Confirm the starting point.**

```bash
cd /Users/reubenpatterson/local_agent_harness/qwen-agent-workspace
git branch --show-current     # expected: qwen-agent-redteam
git log -1 --format=%h        # expected: 05ecb0b, or a later docs-only commit (for example one that adds this plan)
git status --short            # expected: only ?? ../.DS_Store, ?? ../.claude/, ?? ../agent/__pycache__/, ?? ../bin/
ls scripts/fleet-host-prep.sh tests/test_fleet_host_prep.py 2>&1   # expected: two "No such file or directory" lines
/bin/bash --version | head -1 # expected: GNU bash, version 3.2.57(1)-release (arm64-apple-darwin25)
mkdir -p /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-hostprep
git rev-parse HEAD > /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-hostprep/base-commit.txt
```

- [ ] **Step 2: Record the full-suite baseline (several minutes).**

```bash
python3 -m pytest tests/ -q -rA -p no:cacheprovider > /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-hostprep/baseline-pytest.txt 2>&1
tail -1 /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-hostprep/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-hostprep/baseline-pytest.txt
```

Expected: the last line reads `1 failed, <P> passed, 1 skipped, <W> warnings in ...`, and the only `FAILED` line is `FAILED tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` (pre-existing and unrelated). The skip is `tests/test_fleet_lib.py` T25, which skips until rollout creates `fleet.env`. Write `<P>` down: Task 8 expects exactly `<P> + 125` passes. If the failure or skip set differs, write what you saw into `baseline-notes.txt` in the same directory and continue; Task 8 compares against what was recorded.

---

### Task 2: Script skeleton, CLI, validation and root refusal; the test harness

Implements P1-P8 (constants, parsing, validation, defaults, root refusal) and the whole Section 6.2 harness. Tests: H6 (every rejected input, help, root), H12, H15(b), H23, Review Focus 3.

**Files:**
- Create: `scripts/fleet-host-prep.sh` (mode 0755).
- Create: `tests/test_fleet_host_prep.py`.

**Interfaces:**
- Consumes: `fleet_lib.py` (read only, through the script's probes in later tasks); `searxng/docker-compose.yml` and `searxng/settings.yml` (read only).
- Produces in the script: globals `WS`, `SOCKETFILTERFW`, `SX`, `NL`, `OLLAMA_URL_DEFAULT`, `VLLM_URL_DEFAULT`, `SEARXNG_URL_DEFAULT`, `LAN_CIDR_DEFAULT`, `PORT_DEFAULT`, `SEARXNG_CONTAINER`, `PY_VERSION`, `PY_PYTEST`, `PY_EXE`, `PY_PROBE_URL`, `PY_HAS_MODEL`, `RE_CIDR`, `RE_PORT`, `RE_OFFSET`, `RE_APP`, `USAGE`; after validation `TYPE`, `MODEL`, `MODEL_URL`, `SEARXNG_URL`, `NO_SEARXNG` (`0`/`1`), `LAN_CIDR`, `PORT`, `APPLY` (`0`/`1`), all with defaults applied; functions `usage_error MESSAGE`, `valid_cidr VALUE`, `valid_port VALUE`. The file ends with the Root refusal block's `fi`. The anchor lines `# ---...` / `# Argument parsing (P5)` exist exactly once.
- Produces in the test file (every later task appends to it and uses these names): `WS`, `SCRIPT`, `FAKE_NAMES`, `REAL_TOOLS`, `LINUX_ABSENT`, `MAC_ABSENT`, `ALL_FAIL_ABSENT`, `LINUX_ARGS`, `MAC_ARGS`, `WRAPPER`, `FORBIDDEN`, `LINE_FORMS`, `USAGE`, `ufw_row(to, action, frm, comment="") -> str`, `UFW_HEAD`, `UFW_OK`, `UFW_NONE`, `PYTHON_EXE`, `DEFAULT_STATE`, `FAKEBIN`, `linux_state(**overrides) -> dict`, `mac_state(**overrides) -> dict`, `all_fail_state(**overrides) -> dict`, `class Run` (attributes `tmp`, `home`, `sx`, `sfw`, `rc`, `out`, `err`, `lines`, `state`; methods `calls() -> list`, `named(name, *prefix) -> list`, `status(check) -> str`, `fix_after(check) -> str`), the session fixture `harness_dir`, `run(args, state=None, absent=LINUX_ABSENT, home_name="home", cwd=None, script=SCRIPT) -> Run`, `plus_lines(stdout) -> list`, `status_lines(stdout) -> list`, `mutating(calls) -> list`, `script_text() -> str`, `_usage_error(r, message)`.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_fleet_host_prep.py` with exactly:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail.**

Run: `python3 -m pytest tests/test_fleet_host_prep.py -q -p no:cacheprovider 2>&1 | tail -1`
Expected: `28 failed in ...` (the script does not exist: `run()` gets bash exit 127 and `script_text()` raises `FileNotFoundError`).

- [ ] **Step 3: Write the script.** Create `scripts/fleet-host-prep.sh` with exactly the block below, then make it executable:

```bash
#!/usr/bin/env bash
# fleet-host-prep.sh -- check, and with --apply fix, the qwen-agent fleet
# rollout prerequisites on this host. It automates step R0 of the fleet spec
# (docs/superpowers/specs/2026-10-16-fleet-discovery-self-update-design.md,
# Section 12) and runs unchanged on macOS (/bin/bash 3.2) and Linux (bash 5).
#
# Usage: fleet-host-prep.sh --model-server-type {ollama|vllm} --model NAME
#                           [--model-url URL] [--searxng-url URL | --no-searxng]
#                           [--lan-cidr CIDR] [--port N] [--apply]
#
# The seven checks, in this order:
#   platform  macOS or Linux, and the Linux package manager
#   packages  python3 >= 3.9, git and pytest
#   clock     the clock is NTP-synchronized
#   model     the model server serves --model
#   searxng   SearXNG answers (skipped with --no-searxng)
#   firewall  the LAN may reach the fleet port, TCP and UDP
#   linger    systemd user lingering is on (Linux only)
#
# Without --apply the script only reads state and reports: it changes
# nothing. With --apply it runs the fix for each failing check (asking for
# your sudo password once), then checks again.
#
# It never reads, writes or names the fleet secret file or any fleet
# variable, and it never runs qwen-agentd.
#
# Test seam: FLEET_PREP_SOCKETFILTERFW overrides the path of macOS's
# socketfilterfw (default /usr/libexec/ApplicationFirewall/socketfilterfw).
# Only tests/test_fleet_host_prep.py sets it.
#
# Spec: docs/superpowers/specs/2026-10-17-fleet-host-prep-design.md

set -u
set -o pipefail
export LC_ALL=C

# ---------------------------------------------------------------------------
# Constants (P4, P8, P18)
# ---------------------------------------------------------------------------

WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SOCKETFILTERFW="${FLEET_PREP_SOCKETFILTERFW:-/usr/libexec/ApplicationFirewall/socketfilterfw}"
SX="$HOME/.local/share/qwen-agent/searxng"
NL=$'\n'

OLLAMA_URL_DEFAULT='http://127.0.0.1:11434/v1'
VLLM_URL_DEFAULT='http://127.0.0.1:8177/v1'
SEARXNG_URL_DEFAULT='http://127.0.0.1:8888/'
LAN_CIDR_DEFAULT='192.168.1.0/24'
PORT_DEFAULT='8190'
SEARXNG_CONTAINER='qwen-agent-searxng'

# Python probes (P8): fixed strings, used verbatim; the tests match them.
PY_VERSION='import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'
PY_PYTEST='import pytest'
PY_EXE='import os, subprocess; print(os.path.realpath(subprocess.check_output(["/bin/ps", "-o", "comm=", "-p", str(os.getpid())]).decode().strip()))'
PY_PROBE_URL='import sys; sys.path.insert(0, sys.argv[1]); import fleet_lib; print(fleet_lib.probe_url({"type": sys.argv[2], "url": sys.argv[3]}))'
PY_HAS_MODEL='import sys; sys.path.insert(0, sys.argv[1]); import fleet_lib; names = sorted(fleet_lib.parse_loaded_models(sys.argv[2], sys.stdin.buffer.read())); print(", ".join(names)); sys.exit(0 if sys.argv[3] in names else 3)'

# Regexes are used unquoted on the right of =~ (P2).
RE_CIDR='^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})/([0-9]{1,2})$'
RE_PORT='^[1-9][0-9]{3,4}$'
RE_OFFSET='^[+-]?[0-9]+(\.[0-9]+)?$'
RE_APP='^[0-9]+ : (.*[^ ])[ ]*$'

USAGE="Usage: fleet-host-prep.sh --model-server-type {ollama|vllm} --model NAME
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
2 usage error, or run as root."

# ---------------------------------------------------------------------------
# Command-line helpers (P5-P6)
# ---------------------------------------------------------------------------

# usage_error MESSAGE: report a usage error on stderr and exit 2.
usage_error() {
    printf 'fleet-host-prep.sh: %s\n' "$1" >&2
    printf '%s\n' "Run 'fleet-host-prep.sh --help' for usage." >&2
    exit 2
}

# valid_cidr VALUE: an IPv4 network with zero host bits (P6 item 5).
valid_cidr() {
    local o1 o2 o3 o4 len ip
    if ! [[ $1 =~ $RE_CIDR ]]; then
        return 1
    fi
    o1=$((10#${BASH_REMATCH[1]}))
    o2=$((10#${BASH_REMATCH[2]}))
    o3=$((10#${BASH_REMATCH[3]}))
    o4=$((10#${BASH_REMATCH[4]}))
    len=$((10#${BASH_REMATCH[5]}))
    if [ "$o1" -gt 255 ] || [ "$o2" -gt 255 ] || [ "$o3" -gt 255 ] || [ "$o4" -gt 255 ] || [ "$len" -gt 32 ]; then
        return 1
    fi
    ip=$(( (o1 << 24) | (o2 << 16) | (o3 << 8) | o4 ))
    if [ "$len" -eq 0 ]; then
        [ "$ip" -eq 0 ]
        return
    fi
    [ $(( ip & ((1 << (32 - len)) - 1) )) -eq 0 ]
}

# valid_port VALUE: a decimal integer from 1024 to 65535, no leading zero (P6 item 6).
valid_port() {
    if ! [[ $1 =~ $RE_PORT ]]; then
        return 1
    fi
    [ $((10#$1)) -ge 1024 ] && [ $((10#$1)) -le 65535 ]
}

# ---------------------------------------------------------------------------
# Argument parsing (P5)
# ---------------------------------------------------------------------------

TYPE=''
HAVE_TYPE=0
MODEL=''
MODEL_URL=''
HAVE_MODEL_URL=0
SEARXNG_URL=''
HAVE_SEARXNG_URL=0
NO_SEARXNG=0
LAN_CIDR=''
HAVE_LAN_CIDR=0
PORT=''
HAVE_PORT=0
APPLY=0

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help)
            printf '%s\n' "$USAGE"
            exit 0
            ;;
        --apply)
            APPLY=1
            shift
            ;;
        --no-searxng)
            NO_SEARXNG=1
            shift
            ;;
        --model-server-type|--model|--model-url|--searxng-url|--lan-cidr|--port)
            if [ $# -lt 2 ]; then
                usage_error "$1 needs a value"
            fi
            case "$2" in
                --*) usage_error "$1 needs a value" ;;
            esac
            case "$1" in
                --model-server-type) TYPE="$2"; HAVE_TYPE=1 ;;
                --model) MODEL="$2" ;;
                --model-url) MODEL_URL="$2"; HAVE_MODEL_URL=1 ;;
                --searxng-url) SEARXNG_URL="$2"; HAVE_SEARXNG_URL=1 ;;
                --lan-cidr) LAN_CIDR="$2"; HAVE_LAN_CIDR=1 ;;
                --port) PORT="$2"; HAVE_PORT=1 ;;
            esac
            shift 2
            ;;
        *)
            usage_error "unknown argument '$1'"
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Validation and defaults (P6)
# ---------------------------------------------------------------------------

if [ "$HAVE_TYPE" = 0 ]; then
    usage_error 'missing --model-server-type'
fi
case "$TYPE" in
    ollama|vllm) ;;
    *) usage_error "--model-server-type must be ollama or vllm, got '$TYPE'" ;;
esac
if [ -z "$MODEL" ]; then
    usage_error 'missing --model'
fi
if [ "$NO_SEARXNG" = 1 ] && [ "$HAVE_SEARXNG_URL" = 1 ]; then
    usage_error '--no-searxng and --searxng-url cannot be used together'
fi
if [ "$HAVE_LAN_CIDR" = 1 ] && ! valid_cidr "$LAN_CIDR"; then
    usage_error "--lan-cidr must be an IPv4 network with zero host bits, e.g. 192.168.1.0/24, got '$LAN_CIDR'"
fi
if [ "$HAVE_PORT" = 1 ] && ! valid_port "$PORT"; then
    usage_error "--port must be a decimal integer from 1024 to 65535, got '$PORT'"
fi

if [ "$HAVE_MODEL_URL" = 0 ]; then
    if [ "$TYPE" = ollama ]; then
        MODEL_URL="$OLLAMA_URL_DEFAULT"
    else
        MODEL_URL="$VLLM_URL_DEFAULT"
    fi
fi
if [ "$HAVE_SEARXNG_URL" = 0 ]; then
    SEARXNG_URL="$SEARXNG_URL_DEFAULT"
fi
if [ "$HAVE_LAN_CIDR" = 0 ]; then
    LAN_CIDR="$LAN_CIDR_DEFAULT"
fi
if [ "$HAVE_PORT" = 0 ]; then
    PORT="$PORT_DEFAULT"
fi

# ---------------------------------------------------------------------------
# Root refusal (P7)
# ---------------------------------------------------------------------------

MY_UID=$(id -u 2>/dev/null)
if [ "$MY_UID" = 0 ]; then
    printf '%s\n' 'fleet-host-prep.sh: refusing to run as root; run as the user who will run the fleet daemon (fixes use sudo)' >&2
    exit 2
fi
```

```bash
chmod 0755 scripts/fleet-host-prep.sh
/bin/bash -n scripts/fleet-host-prep.sh && echo syntax-ok
```

Expected: `syntax-ok`.

- [ ] **Step 4: Run the tests to verify they pass.**

Run: `python3 -m pytest tests/test_fleet_host_prep.py -q -p no:cacheprovider 2>&1 | tail -1`
Expected: `28 passed in ...` (about 1 s).

- [ ] **Step 5: Commit.**

```bash
git add scripts/fleet-host-prep.sh tests/test_fleet_host_prep.py
git diff --cached --name-only   # expected: exactly qwen-agent-workspace/scripts/fleet-host-prep.sh and qwen-agent-workspace/tests/test_fleet_host_prep.py
git ls-files -s scripts/fleet-host-prep.sh | cut -c1-6   # expected: 100755
git commit -F - <<'EOF'
fleet-host-prep: script skeleton, CLI, validation, root refusal (P1-P8)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 3: Output protocol, check driver, `sudo -v`, platform check, summary

Implements P9 (`sudo -v` and its failure), P10 (status, `fix:` and `+` lines, the summary), P11 (exit status), P12 (`run_check`, `run_fix`, the fix-line rendering) and P13's platform check including the unsupported-OS stop. Tests: H21, H22, the platform lines, the `sudo -v` ordering half of H3 and H5.

**Files:**
- Modify: `scripts/fleet-host-prep.sh` (insert above the anchor; append at the end).
- Modify: `tests/test_fleet_host_prep.py` (append).

**Interfaces:**
- Consumes: Task 2's globals, `APPLY`, and the anchor lines.
- Produces: counters `N_PASS`, `N_FIXED`, `N_FAIL`, `N_UNKNOWN`, `N_SKIP`; `render WORD...` (prints the P10 rendering, no newline); `emit STATUS CHECK DETAIL [FIXLINE]`; `print_summary`; `run_fix WORD...` (sets `FIX_RC`, returns it); `step WORD...` (uses `FIX_MODE` `line` or `run`); `set_fix FN`; `run_check NAME` (the contract in File Structure; uses `CK_RESULT`, `CK_DETAIL`, `CK_FIXLINE`, `CK_FIX`, `CK_POLLS`, `CK_SLEEP`); globals `OS` (`mac`, `linux`, or empty for an unsupported OS) and `PKG` (`apt`, `dnf` or `none`); `ck_platform`. In the check sequence, the exact lines `run_check platform` / `if [ -z "$OS" ]; then` / `    print_summary` / `    exit 1` / `fi`, which Task 4 extends.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_fleet_host_prep.py` (the block begins with two empty lines):

```python


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
```

- [ ] **Step 2: Run the tests to verify the new ones fail.**

Run: `python3 -m pytest tests/test_fleet_host_prep.py -q -p no:cacheprovider 2>&1 | tail -1`
Expected: `8 failed, 28 passed in ...` (the 8 new tests fail: the script prints nothing after the root check).

- [ ] **Step 3: Insert the helpers and the platform check.** In `scripts/fleet-host-prep.sh`, replace these two anchor lines (they occur once):

```bash
# ---------------------------------------------------------------------------
# Argument parsing (P5)
```

with this block, which ends with the same two anchor lines:

```bash
# ---------------------------------------------------------------------------
# Output and the check protocol (P10-P12)
# ---------------------------------------------------------------------------

N_PASS=0
N_FIXED=0
N_FAIL=0
N_UNKNOWN=0
N_SKIP=0

# render WORD...: print the words as one copy-pasteable command (P10). A word
# with a space is quoted: --name='value' for a --name=value word, else 'word'.
render() {
    local out='' w
    for w in "$@"; do
        case "$w" in
            *' '*)
                case "$w" in
                    --*=*) w="${w%%=*}='${w#*=}'" ;;
                    *) w="'$w'" ;;
                esac
                ;;
        esac
        if [ -z "$out" ]; then
            out="$w"
        else
            out="$out $w"
        fi
    done
    printf '%s' "$out"
}

# emit STATUS CHECK DETAIL [FIXLINE]: print a status line, count it, and
# print the fix line after a FAIL or UNKNOWN.
emit() {
    printf '%s %s: %s\n' "$1" "$2" "$3"
    case "$1" in
        PASS) N_PASS=$((N_PASS + 1)) ;;
        FIXED) N_FIXED=$((N_FIXED + 1)) ;;
        FAIL) N_FAIL=$((N_FAIL + 1)); printf '  fix: %s\n' "$4" ;;
        UNKNOWN) N_UNKNOWN=$((N_UNKNOWN + 1)); printf '  fix: %s\n' "$4" ;;
        SKIP) N_SKIP=$((N_SKIP + 1)) ;;
    esac
}

print_summary() {
    printf 'summary: %s pass, %s fixed, %s fail, %s unknown, %s skip\n' \
        "$N_PASS" "$N_FIXED" "$N_FAIL" "$N_UNKNOWN" "$N_SKIP"
}

# run_fix WORD...: print the + line, then run the command with inherited
# stdout and stderr. FIX_RC is its exit status.
run_fix() {
    printf '+ %s\n' "$(render "$@")"
    "$@"
    FIX_RC=$?
    return "$FIX_RC"
}

# step WORD...: one command of a fix function. With FIX_MODE=line it appends
# the rendered command to CK_FIXLINE (joined by ' && '); with FIX_MODE=run it
# runs it through run_fix. A fix function is written as a list of steps, each
# but the last followed by '|| return', so its fix line and the commands it
# runs can never disagree.
step() {
    if [ "$FIX_MODE" = line ]; then
        CK_FIXLINE="${CK_FIXLINE:+$CK_FIXLINE && }$(render "$@")"
        return 0
    fi
    run_fix "$@"
}

# set_fix FN: FN is the automatic fix for this failure; its steps become the
# fix line.
set_fix() {
    CK_FIX="$1"
    CK_FIXLINE=''
    FIX_MODE=line
    "$1"
}

# run_check NAME (P12). ck_NAME runs the read-only test and sets CK_RESULT
# (pass, fail, unknown or skip) and CK_DETAIL; after a fail or unknown it
# also sets CK_FIXLINE and, when an automatic fix exists, CK_FIX (through
# set_fix), and it may set CK_POLLS and CK_SLEEP for the re-check. The
# re-check calls t_NAME, which repeats the test and sets only CK_RESULT and
# CK_DETAIL.
run_check() {
    local name="$1" pre fixline i
    CK_RESULT=''
    CK_DETAIL=''
    CK_FIXLINE=''
    CK_FIX=''
    CK_POLLS=1
    CK_SLEEP=0
    "ck_$name"
    case "$CK_RESULT" in
        pass) emit PASS "$name" "$CK_DETAIL"; return ;;
        skip) emit SKIP "$name" "$CK_DETAIL"; return ;;
        unknown) emit UNKNOWN "$name" "$CK_DETAIL" "$CK_FIXLINE"; return ;;
    esac
    if [ "$APPLY" != 1 ] || [ -z "$CK_FIX" ]; then
        emit FAIL "$name" "$CK_DETAIL" "$CK_FIXLINE"
        return
    fi
    pre="$CK_DETAIL"
    fixline="$CK_FIXLINE"
    FIX_RC=0
    FIX_MODE=run
    "$CK_FIX"
    if [ "$FIX_RC" -ne 0 ]; then
        emit FAIL "$name" "$pre (fix exited $FIX_RC)" "$fixline"
        return
    fi
    i=1
    while :; do
        "t_$name"
        if [ "$CK_RESULT" = pass ] || [ "$i" -ge "$CK_POLLS" ]; then
            break
        fi
        sleep "$CK_SLEEP"
        i=$((i + 1))
    done
    if [ "$CK_RESULT" = pass ]; then
        emit FIXED "$name" "$CK_DETAIL"
    else
        emit FAIL "$name" "$CK_DETAIL (fix did not take)" "$fixline"
    fi
}

# ---------------------------------------------------------------------------
# platform (P13)
# ---------------------------------------------------------------------------

OS=''
PKG='none'

ck_platform() {
    local os v rc
    os=$(uname -s 2>/dev/null)
    case "$os" in
        Darwin)
            v=$(sw_vers -productVersion 2>/dev/null)
            rc=$?
            if [ "$rc" -ne 0 ]; then
                v='unknown'
            fi
            OS='mac'
            CK_RESULT=pass
            CK_DETAIL="macOS $v"
            ;;
        Linux)
            OS='linux'
            CK_RESULT=pass
            if command -v apt-get >/dev/null 2>&1; then
                PKG='apt'
                CK_DETAIL='linux/apt'
            elif command -v dnf >/dev/null 2>&1; then
                PKG='dnf'
                CK_DETAIL='linux/dnf'
            else
                CK_DETAIL='linux (no apt-get/dnf: packages must be installed by hand)'
            fi
            ;;
        *)
            CK_RESULT=fail
            CK_DETAIL="unsupported OS '$os'"
            CK_FIXLINE='this script supports macOS (Darwin) and Linux only'
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Argument parsing (P5)
```

- [ ] **Step 4: Append the sudo, check-sequence and summary sections.** Append to the end of `scripts/fleet-host-prep.sh` (the file currently ends with the Root refusal block's `fi`; the block begins with one empty line):

```bash

# ---------------------------------------------------------------------------
# sudo (P9)
# ---------------------------------------------------------------------------

if [ "$APPLY" = 1 ]; then
    sudo -v
    SUDO_RC=$?
    if [ "$SUDO_RC" -ne 0 ]; then
        emit FAIL sudo "'sudo -v' failed (exit $SUDO_RC); nothing was changed" \
            're-run from an interactive terminal and enter your password, or run without --apply'
        print_summary
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# The checks, in order (P12-P16)
# ---------------------------------------------------------------------------

run_check platform
if [ -z "$OS" ]; then
    print_summary
    exit 1
fi

# ---------------------------------------------------------------------------
# Summary (P10) and exit status (P11)
# ---------------------------------------------------------------------------

print_summary
if [ $((N_FAIL + N_UNKNOWN)) -gt 0 ]; then
    exit 1
fi
exit 0
```

- [ ] **Step 5: Run the tests to verify they pass.**

Run: `python3 -m pytest tests/test_fleet_host_prep.py -q -p no:cacheprovider 2>&1 | tail -1`
Expected: `36 passed in ...` (about 2 s).

- [ ] **Step 6: Commit.**

```bash
git add scripts/fleet-host-prep.sh tests/test_fleet_host_prep.py
git diff --cached --name-only   # expected: exactly the two files
git commit -F - <<'EOF'
fleet-host-prep: output protocol, check driver, sudo -v, platform (P9-P13)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 4: packages and clock checks

Implements P13a (packages, with the apt, dnf, no-package-manager, macOS-pip and macOS-manual cases) and P13's clock check (Linux `timedatectl` with the 15-step poll; macOS `sntp` with the integer-part comparison). Tests: H4(b) pre-fix detail, H4(c), H11, H20, H25, and the package-manager fix lines.

**Files:**
- Modify: `scripts/fleet-host-prep.sh` (insert above the anchor; extend the check sequence).
- Modify: `tests/test_fleet_host_prep.py` (append).

**Interfaces:**
- Consumes: Task 3's `run_check` contract, `set_fix`, `step`, `OS`, `PKG`; Task 2's `PY_VERSION`, `PY_PYTEST`, `RE_OFFSET`, `NL`.
- Produces: `PK_PY`, `PK_GIT`, `PK_PYTEST` (`0`/`1`, set by `t_packages`); `t_packages`, `ck_packages`, `fix_packages_apt`, `fix_packages_dnf`, `fix_packages_pip`; `t_clock`, `t_clock_linux`, `t_clock_mac`, `ck_clock`, `fix_clock_linux`, `fix_clock_mac`. In the test file: `APT_FIX` (used again in Task 7) and `SNTP_TAIL`. The check-sequence line `run_check clock`, which Task 5 extends.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_fleet_host_prep.py` (the block begins with two empty lines):

```python


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
```

- [ ] **Step 2: Run the tests to verify the new ones fail.**

Run: `python3 -m pytest tests/test_fleet_host_prep.py -q -p no:cacheprovider 2>&1 | tail -1`
Expected: `22 failed, 36 passed in ...` (no `packages` or `clock` status line exists yet).

- [ ] **Step 3: Insert the packages and clock checks.** In `scripts/fleet-host-prep.sh`, replace these two anchor lines (they occur once):

```bash
# ---------------------------------------------------------------------------
# Argument parsing (P5)
```

with this block, which ends with the same two anchor lines:

```bash
# ---------------------------------------------------------------------------
# packages (P13a)
# ---------------------------------------------------------------------------

PK_PY=0
PK_GIT=0
PK_PYTEST=0

t_packages() {
    local missing=''
    PK_PY=0
    PK_GIT=0
    PK_PYTEST=0
    if command -v python3 >/dev/null 2>&1 && python3 -c "$PY_VERSION" >/dev/null 2>&1; then
        PK_PY=1
    fi
    if git --version >/dev/null 2>&1; then
        PK_GIT=1
    fi
    if [ "$PK_PY" = 1 ] && python3 -c "$PY_PYTEST" >/dev/null 2>&1; then
        PK_PYTEST=1
    fi
    if [ "$PK_PY" = 1 ] && [ "$PK_GIT" = 1 ] && [ "$PK_PYTEST" = 1 ]; then
        CK_RESULT=pass
        CK_DETAIL='python3 >= 3.9, git, pytest'
        return
    fi
    if [ "$PK_PY" != 1 ]; then
        missing='python3 >= 3.9'
    fi
    if [ "$PK_GIT" != 1 ]; then
        missing="${missing:+$missing, }git"
    fi
    if [ "$PK_PYTEST" != 1 ]; then
        missing="${missing:+$missing, }pytest"
    fi
    CK_RESULT=fail
    CK_DETAIL="missing: $missing"
}

ck_packages() {
    t_packages
    if [ "$CK_RESULT" = pass ]; then
        return
    fi
    if [ "$OS" = linux ]; then
        case "$PKG" in
            apt) set_fix fix_packages_apt ;;
            dnf) set_fix fix_packages_dnf ;;
            *) CK_FIXLINE="install python3 (>= 3.9), git and pytest with this host's package manager, then re-run" ;;
        esac
    elif [ "$PK_PY" != 1 ] || [ "$PK_GIT" != 1 ]; then
        CK_FIXLINE='xcode-select --install (or install Python >= 3.9 from python.org), then re-run'
    else
        set_fix fix_packages_pip
    fi
}

fix_packages_apt() {
    step sudo apt-get update || return
    step sudo apt-get install -y python3 git python3-pytest
}

fix_packages_dnf() {
    step sudo dnf install -y python3 git python3-pytest
}

fix_packages_pip() {
    step python3 -m pip install --user pytest
}

# ---------------------------------------------------------------------------
# clock (P13)
# ---------------------------------------------------------------------------

t_clock() {
    if [ "$OS" = linux ]; then
        t_clock_linux
    else
        t_clock_mac
    fi
}

t_clock_linux() {
    local out rc
    out=$(timedatectl show -p NTPSynchronized 2>/dev/null)
    rc=$?
    CK_RESULT=fail
    if [ "$rc" -ne 0 ]; then
        CK_DETAIL="timedatectl show failed (exit $rc)"
    elif [ "$out" = 'NTPSynchronized=yes' ]; then
        CK_RESULT=pass
        CK_DETAIL='NTPSynchronized=yes'
    else
        CK_DETAIL="$out"
    fi
}

# |offset| < 5 s exactly when the integer part of the offset is < 5.
t_clock_mac() {
    local out rc line tok rest t ip
    out=$(sntp -t 3 time.apple.com 2>/dev/null)
    rc=$?
    CK_RESULT=fail
    if [ "$rc" -ne 0 ]; then
        CK_DETAIL="sntp failed (exit $rc)"
        return
    fi
    line="${out%%"$NL"*}"
    read -r tok rest <<<"$line"
    if ! [[ $tok =~ $RE_OFFSET ]]; then
        CK_DETAIL="unparseable sntp output '$line'"
        return
    fi
    t="${tok#[+-]}"
    ip="${t%%.*}"
    if [ "${#ip}" -gt 9 ] || [ $((10#$ip)) -ge 5 ]; then
        CK_DETAIL="offset $tok s from time.apple.com (limit 5 s)"
        return
    fi
    CK_RESULT=pass
    CK_DETAIL="offset $tok s from time.apple.com"
}

ck_clock() {
    CK_RESULT=fail
    if [ "$OS" = linux ]; then
        if ! command -v timedatectl >/dev/null 2>&1; then
            CK_DETAIL='timedatectl not found'
            CK_FIXLINE='enable NTP time synchronization on this host by hand, then re-run'
            return
        fi
    elif ! command -v sntp >/dev/null 2>&1; then
        CK_DETAIL='sntp not found'
        CK_FIXLINE='turn on System Settings > General > Date & Time > Set time and date automatically'
        return
    fi
    t_clock
    if [ "$CK_RESULT" = pass ]; then
        return
    fi
    if [ "$OS" = linux ]; then
        set_fix fix_clock_linux
    else
        set_fix fix_clock_mac
    fi
    CK_POLLS=15
    CK_SLEEP=2
}

fix_clock_linux() {
    step sudo timedatectl set-ntp true
}

fix_clock_mac() {
    step sudo systemsetup -setusingnetworktime on
}

# ---------------------------------------------------------------------------
# Argument parsing (P5)
```

- [ ] **Step 4: Add the two checks to the sequence.** In `scripts/fleet-host-prep.sh`, replace (occurs once):

```bash
run_check platform
if [ -z "$OS" ]; then
    print_summary
    exit 1
fi
```

with:

```bash
run_check platform
if [ -z "$OS" ]; then
    print_summary
    exit 1
fi
run_check packages
run_check clock
```

- [ ] **Step 5: Run the tests to verify they pass.**

Run: `python3 -m pytest tests/test_fleet_host_prep.py -q -p no:cacheprovider 2>&1 | tail -1`
Expected: `58 passed in ...` (about 12 s).

- [ ] **Step 6: Commit.**

```bash
git add scripts/fleet-host-prep.sh tests/test_fleet_host_prep.py
git diff --cached --name-only   # expected: exactly the two files
git commit -F - <<'EOF'
fleet-host-prep: packages and clock checks (P13, P13a)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 5: model and searxng checks

Implements P14: the model check through `fleet_lib.probe_url` and `fleet_lib.parse_loaded_models` with its four fix cases, and the searxng check with `--no-searxng`, the custom-URL case, the check-mode fix line, and the `--apply` path (Docker absent, `docker ps` failure, `docker start`, or `mkdir`/`cp`/`compose` into the stable directory `SX`, then the 30-probe poll). Tests: H9(a)-(g), H10, H13, H15(a), (c)-(g), the H26 status lines, Review Focus 1, 2, 4 and 5.

**Files:**
- Modify: `scripts/fleet-host-prep.sh` (insert above the anchor; extend the check sequence).
- Modify: `tests/test_fleet_host_prep.py` (append).

**Interfaces:**
- Consumes: Task 3's contract and helpers (`render`, `step`, `set_fix`); Task 2's `WS`, `SX`, `TYPE`, `MODEL`, `MODEL_URL`, `SEARXNG_URL`, `NO_SEARXNG`, `OLLAMA_URL_DEFAULT`, `SEARXNG_URL_DEFAULT`, `SEARXNG_CONTAINER`, `PY_PROBE_URL`, `PY_HAS_MODEL`, `NL`.
- Produces: `MD_KIND` (`lib`, `down`, `missing` or empty), `MD_PROBE`; `t_model`, `ck_model`, `fix_model`; `DOCKER_SUDO` (`0`/`1`), `SX_START` (`0`/`1`); `t_searxng`, `docker_words FN ARG...`, `ck_searxng`, `fix_searxng`. In the test file: `OLLAMA_PROBE`, `VLLM_PROBE`, `SEARXNG_DEFAULT`, `shown(word) -> str`, `model_curls(r)`, `searxng_curls(r)`, `compose_plus_lines(r, docker="docker") -> list`, `assert_searxng_copied(r)` (all used again in Task 7). The check-sequence line `run_check searxng`, which Task 6 extends.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_fleet_host_prep.py` (the block begins with two empty lines):

```python


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
```

- [ ] **Step 2: Run the tests to verify the new ones fail.**

Run: `python3 -m pytest tests/test_fleet_host_prep.py -q -p no:cacheprovider 2>&1 | tail -1`
Expected: `23 failed, 58 passed in ...`.

- [ ] **Step 3: Insert the model and searxng checks.** In `scripts/fleet-host-prep.sh`, replace these two anchor lines (they occur once):

```bash
# ---------------------------------------------------------------------------
# Argument parsing (P5)
```

with this block, which ends with the same two anchor lines:

```bash
# ---------------------------------------------------------------------------
# model (P14)
# ---------------------------------------------------------------------------

MD_KIND=''
MD_PROBE=''

# t_model sets MD_KIND after a failure: lib (fleet_lib cannot be used), down
# (the server does not answer 200) or missing (the model is not served).
t_model() {
    local out rc code body names
    MD_KIND='lib'
    CK_RESULT=fail
    CK_DETAIL="python3 cannot load fleet_lib from $WS"
    if ! command -v python3 >/dev/null 2>&1; then
        return
    fi
    MD_PROBE=$(python3 -I -B -c "$PY_PROBE_URL" "$WS" "$TYPE" "$MODEL_URL" 2>/dev/null)
    rc=$?
    if [ "$rc" -ne 0 ] || [ -z "$MD_PROBE" ]; then
        return
    fi
    out=$(curl -sS --noproxy '*' --max-time 5 -w '\n%{http_code}' "$MD_PROBE" 2>/dev/null)
    rc=$?
    MD_KIND='down'
    if [ "$rc" -ne 0 ]; then
        CK_DETAIL="$TYPE not reachable at $MD_PROBE (curl exit $rc)"
        return
    fi
    code="${out##*"$NL"}"
    body="${out%"$NL"*}"
    if [ "$code" != 200 ]; then
        CK_DETAIL="$TYPE not reachable at $MD_PROBE (HTTP $code)"
        return
    fi
    names=$(python3 -I -B -c "$PY_HAS_MODEL" "$WS" "$TYPE" "$MODEL" <<<"$body" 2>/dev/null)
    rc=$?
    case "$rc" in
        0)
            MD_KIND=''
            CK_RESULT=pass
            CK_DETAIL="'$MODEL' served by $TYPE at $MD_PROBE"
            ;;
        3)
            MD_KIND='missing'
            CK_DETAIL="'$MODEL' not served by $TYPE at $MD_PROBE (serving: ${names:-none})"
            ;;
        *)
            MD_KIND='lib'
            ;;
    esac
}

ck_model() {
    t_model
    if [ "$CK_RESULT" = pass ]; then
        return
    fi
    case "$MD_KIND" in
        lib)
            CK_FIXLINE="needs python3 >= 3.9 (see packages) and $WS/fleet_lib.py from a complete checkout"
            ;;
        down)
            CK_FIXLINE="start the $TYPE model server at $MODEL_URL; this script never starts model servers"
            ;;
        missing)
            if [ "$TYPE" = vllm ]; then
                CK_FIXLINE="start vllm-metal serving '$MODEL' at $MODEL_URL by hand; this script never starts, restarts or pulls for vLLM"
            elif [ "$MODEL_URL" != "$OLLAMA_URL_DEFAULT" ]; then
                CK_FIXLINE="pull '$MODEL' into the Ollama server at $MODEL_URL by hand"
            elif ! command -v ollama >/dev/null 2>&1; then
                CK_FIXLINE="the ollama CLI is not on PATH; pull '$MODEL' by hand (this script never installs Ollama)"
            else
                set_fix fix_model
            fi
            ;;
    esac
}

fix_model() {
    step ollama pull "$MODEL"
}

# ---------------------------------------------------------------------------
# searxng (P14)
# ---------------------------------------------------------------------------

DOCKER_SUDO=0
SX_START=0

t_searxng() {
    local code rc
    code=$(curl -sS --noproxy '*' --max-time 5 -o /dev/null -w '%{http_code}' "$SEARXNG_URL" 2>/dev/null)
    rc=$?
    CK_RESULT=fail
    if [ "$rc" -ne 0 ]; then
        CK_DETAIL="no answer at $SEARXNG_URL (curl exit $rc)"
    elif [ "$code" = 200 ]; then
        CK_RESULT=pass
        CK_DETAIL="HTTP 200 at $SEARXNG_URL"
    else
        CK_DETAIL="HTTP $code at $SEARXNG_URL"
    fi
}

# docker_words FN ARG...: call FN with the docker command words (docker, or
# sudo docker for a Linux user outside the docker group), then ARG...
docker_words() {
    local fn="$1"
    shift
    if [ "$DOCKER_SUDO" = 1 ]; then
        "$fn" sudo docker "$@"
    else
        "$fn" docker "$@"
    fi
}

ck_searxng() {
    local names rc line
    if [ "$NO_SEARXNG" = 1 ]; then
        CK_RESULT=skip
        CK_DETAIL='disabled by --no-searxng'
        return
    fi
    t_searxng
    if [ "$CK_RESULT" = pass ]; then
        return
    fi
    if [ "$SEARXNG_URL" != "$SEARXNG_URL_DEFAULT" ]; then
        CK_FIXLINE="check that $SEARXNG_URL is up and that no_proxy covers its host; if this host cannot run SearXNG, set QWEN_AGENT_SEARXNG_URL with the systemd drop-in described in R0 of the fleet spec"
        return
    fi
    DOCKER_SUDO=0
    if [ "$OS" = linux ]; then
        case " $(id -nG 2>/dev/null) " in
            *' docker '*) ;;
            *) DOCKER_SUDO=1 ;;
        esac
    fi
    if [ "$APPLY" != 1 ]; then
        CK_FIXLINE="$(docker_words render start "$SEARXNG_CONTAINER") if that container exists, else: $(render mkdir -p "$SX") && $(render cp "$WS/searxng/docker-compose.yml" "$WS/searxng/settings.yml" "$SX/") && $(docker_words render compose -p "$SEARXNG_CONTAINER" -f "$SX/docker-compose.yml" up -d) (or re-run with --apply)"
        return
    fi
    if ! command -v docker >/dev/null 2>&1; then
        CK_DETAIL="$CK_DETAIL; Docker not installed (this script never installs Docker)"
        CK_FIXLINE='install Docker, or use another SearXNG instance through QWEN_AGENT_SEARXNG_URL (fleet spec R0), then re-run'
        return
    fi
    if [ "$DOCKER_SUDO" = 1 ]; then
        names=$(sudo -n docker ps -a --format '{{.Names}}' 2>/dev/null)
        rc=$?
    else
        names=$(docker ps -a --format '{{.Names}}' 2>/dev/null)
        rc=$?
    fi
    if [ "$rc" -ne 0 ]; then
        CK_DETAIL="$CK_DETAIL; 'docker ps -a' failed (exit $rc): is the Docker daemon running?"
        CK_FIXLINE='start Docker, then re-run'
        return
    fi
    SX_START=0
    while IFS= read -r line; do
        if [ "$line" = "$SEARXNG_CONTAINER" ]; then
            SX_START=1
        fi
    done <<<"$names"
    set_fix fix_searxng
    CK_POLLS=30
    CK_SLEEP=1
}

# The stable directory SX keeps the bind-mounted settings.yml alive across
# reboots (spec P14): never a temporary clone or a release directory.
fix_searxng() {
    if [ "$SX_START" = 1 ]; then
        docker_words step start "$SEARXNG_CONTAINER"
        return
    fi
    step mkdir -p "$SX" || return
    step cp "$WS/searxng/docker-compose.yml" "$WS/searxng/settings.yml" "$SX/" || return
    docker_words step compose -p "$SEARXNG_CONTAINER" -f "$SX/docker-compose.yml" up -d
}

# ---------------------------------------------------------------------------
# Argument parsing (P5)
```

- [ ] **Step 4: Add the two checks to the sequence.** In `scripts/fleet-host-prep.sh`, replace (occurs once):

```bash
run_check clock
```

with:

```bash
run_check clock
run_check model
run_check searxng
```

- [ ] **Step 5: Run the tests to verify they pass.**

Run: `python3 -m pytest tests/test_fleet_host_prep.py -q -p no:cacheprovider 2>&1 | tail -1`
Expected: `81 passed in ...` (about 35 s).

- [ ] **Step 6: Commit.**

```bash
git add scripts/fleet-host-prep.sh tests/test_fleet_host_prep.py
git diff --cached --name-only   # expected: exactly the two files
git commit -F - <<'EOF'
fleet-host-prep: model and searxng checks (P14)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 6: firewall check

Implements P15: macOS (the application firewall's global state, block-all, the running `python3` image through `PY_EXE`, the `--listapps` parse, `--add`/`--unblockapp`) and Linux (ufw and firewalld detection, the UNKNOWN reads through `sudo -n`, the ufw row scan, the firewalld rich rules, the both-active manual FAIL), all keyed on `--port` and `--lan-cidr`. Tests: H8 (status and fix lines), H16, H17(a)-(d), H18, H19(a)-(h), and H6's accepted values.

**Files:**
- Modify: `scripts/fleet-host-prep.sh` (insert above the anchor; extend the check sequence).
- Modify: `tests/test_fleet_host_prep.py` (append).

**Interfaces:**
- Consumes: Task 3's contract and helpers; Task 2's `SOCKETFILTERFW`, `LAN_CIDR`, `PORT`, `APPLY`, `PY_EXE`, `RE_APP`, `NL`.
- Produces: `FW_KIND` (`settings`, `blockall`, `exe`, `app`, `unknown`, `ufw_weird`, `both`, `ufw`, `firewalld`), `FW_READ`, `FW_EXE`, `FW_LISTED`, `FW_MISS_TCP`, `FW_MISS_UDP`, `FW_RULE_TCP`, `FW_RULE_UDP`; `t_firewall`, `t_firewall_mac`, `fw_missing TCP_OK UDP_OK`, `t_firewall_linux`, `ck_firewall`, `fix_firewall_mac`, `fix_firewall_ufw`, `fix_firewall_firewalld`. In the test file: `LAN`, `SFW_ON`, `rich(port, proto, cidr=LAN)`, `rich_plus(port, proto)`, `FWD_ABSENT`, `rich_rule_adds(r)`. The check-sequence line `run_check firewall`, which Task 7 extends.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_fleet_host_prep.py` (the block begins with two empty lines):

```python


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
```

- [ ] **Step 2: Run the tests to verify the new ones fail.**

Run: `python3 -m pytest tests/test_fleet_host_prep.py -q -p no:cacheprovider 2>&1 | tail -1`
Expected: `30 failed, 81 passed in ...`.

- [ ] **Step 3: Insert the firewall check.** In `scripts/fleet-host-prep.sh`, replace these two anchor lines (they occur once):

```bash
# ---------------------------------------------------------------------------
# Argument parsing (P5)
```

with this block, which ends with the same two anchor lines:

```bash
# ---------------------------------------------------------------------------
# firewall (P15)
# ---------------------------------------------------------------------------

# t_firewall sets FW_KIND after a fail or unknown: settings, blockall, exe or
# app (macOS); unknown, ufw_weird, both, ufw or firewalld (Linux).
FW_KIND=''
FW_READ=''
FW_EXE=''
FW_LISTED=0
FW_MISS_TCP=0
FW_MISS_UDP=0
FW_RULE_TCP=''
FW_RULE_UDP=''

t_firewall() {
    if [ "$OS" = mac ]; then
        t_firewall_mac
    else
        t_firewall_linux
    fi
}

t_firewall_mac() {
    local out rc line next allowed blockall
    FW_KIND='settings'
    CK_RESULT=fail
    if [ ! -x "$SOCKETFILTERFW" ]; then
        CK_DETAIL="$SOCKETFILTERFW not found"
        return
    fi
    out=$("$SOCKETFILTERFW" --getglobalstate 2>/dev/null)
    blockall=0
    case "$out" in
        *'State = 0'*)
            CK_RESULT=pass
            CK_DETAIL='application firewall off'
            return
            ;;
        *'State = 1'*) ;;
        *'State = 2'*) blockall=1 ;;
        *)
            CK_DETAIL="unrecognized socketfilterfw output '${out%%"$NL"*}'"
            return
            ;;
    esac
    if [ "$blockall" = 0 ]; then
        out=$("$SOCKETFILTERFW" --getblockall 2>/dev/null)
        case "$out" in
            *enabled*|*ENABLED*) blockall=1 ;;
        esac
    fi
    if [ "$blockall" = 1 ]; then
        FW_KIND='blockall'
        CK_DETAIL='block all incoming connections is on'
        return
    fi
    FW_KIND='exe'
    CK_DETAIL='cannot resolve the python3 binary'
    if ! command -v python3 >/dev/null 2>&1; then
        return
    fi
    FW_EXE=$(python3 -I -B -c "$PY_EXE" 2>/dev/null)
    rc=$?
    if [ "$rc" -ne 0 ] || [ -z "$FW_EXE" ]; then
        return
    fi
    out=$("$SOCKETFILTERFW" --listapps 2>/dev/null)
    FW_LISTED=0
    allowed=0
    next=0
    while IFS= read -r line; do
        if [ "$next" = 1 ]; then
            case "$line" in
                *'(Allow incoming connections)'*) allowed=1 ;;
            esac
        fi
        next=0
        if [[ $line =~ $RE_APP ]] && [ "${BASH_REMATCH[1]}" = "$FW_EXE" ]; then
            FW_LISTED=1
            next=1
        fi
    done <<<"$out"
    if [ "$allowed" = 1 ]; then
        CK_RESULT=pass
        CK_DETAIL="application firewall on; $FW_EXE allowed"
        return
    fi
    FW_KIND='app'
    CK_DETAIL="application firewall on; $FW_EXE not allowed"
}

# fw_missing TCP_OK UDP_OK: print the missing protocols (tcp, udp).
fw_missing() {
    if [ "$1" = 0 ] && [ "$2" = 0 ]; then
        printf '%s' 'tcp, udp'
    elif [ "$1" = 0 ]; then
        printf '%s' 'tcp'
    else
        printf '%s' 'udp'
    fi
}

t_firewall_linux() {
    local ufw=0 fwd=0 active=0 out rc first f1 f2 f3 rest line tcp=0 udp=0
    FW_RULE_TCP="rule family=\"ipv4\" source address=\"$LAN_CIDR\" port port=\"$PORT\" protocol=\"tcp\" accept"
    FW_RULE_UDP="rule family=\"ipv4\" source address=\"$LAN_CIDR\" port port=\"$PORT\" protocol=\"udp\" accept"
    if command -v ufw >/dev/null 2>&1; then
        ufw=1
    fi
    if command -v firewall-cmd >/dev/null 2>&1; then
        out=$(firewall-cmd --state 2>/dev/null)
        if [ "$out" = running ]; then
            fwd=1
        fi
    fi
    CK_RESULT=fail
    if [ "$ufw" = 1 ]; then
        out=$(sudo -n ufw status 2>/dev/null)
        rc=$?
        if [ "$rc" -ne 0 ]; then
            CK_RESULT=unknown
            CK_DETAIL='cannot read ufw rules without sudo'
            FW_KIND='unknown'
            FW_READ='sudo ufw status'
            return
        fi
        first="${out%%"$NL"*}"
        case "$first" in
            'Status: inactive') ;;
            'Status: active') active=1 ;;
            *)
                CK_DETAIL="unrecognized 'ufw status' output '$first'"
                FW_KIND='ufw_weird'
                return
                ;;
        esac
    fi
    if [ "$active" = 1 ] && [ "$fwd" = 1 ]; then
        CK_DETAIL='ufw and firewalld are both active'
        FW_KIND='both'
    elif [ "$active" = 1 ]; then
        while read -r f1 f2 f3 rest; do
            if [ "$f2" != ALLOW ]; then
                continue
            fi
            if [ "$f3" != "$LAN_CIDR" ] && [ "$f3" != Anywhere ]; then
                continue
            fi
            case "$f1" in
                "$PORT") tcp=1; udp=1 ;;
                "$PORT/tcp") tcp=1 ;;
                "$PORT/udp") udp=1 ;;
            esac
        done <<<"$out"
        if [ "$tcp" = 1 ] && [ "$udp" = 1 ]; then
            CK_RESULT=pass
            CK_DETAIL="ufw allows $PORT tcp+udp from $LAN_CIDR"
        else
            CK_DETAIL="ufw active; no rule allows $PORT $(fw_missing "$tcp" "$udp") from $LAN_CIDR"
            FW_KIND='ufw'
        fi
    elif [ "$fwd" = 1 ]; then
        out=$(sudo -n firewall-cmd --permanent --list-rich-rules 2>/dev/null)
        rc=$?
        if [ "$rc" -ne 0 ]; then
            CK_RESULT=unknown
            CK_DETAIL='cannot read firewalld rules without sudo'
            FW_KIND='unknown'
            FW_READ='sudo firewall-cmd --permanent --list-rich-rules'
            return
        fi
        while IFS= read -r line; do
            if [ "$line" = "$FW_RULE_TCP" ]; then
                tcp=1
            fi
            if [ "$line" = "$FW_RULE_UDP" ]; then
                udp=1
            fi
        done <<<"$out"
        FW_MISS_TCP=$((1 - tcp))
        FW_MISS_UDP=$((1 - udp))
        if [ "$tcp" = 1 ] && [ "$udp" = 1 ]; then
            CK_RESULT=pass
            CK_DETAIL="firewalld allows $PORT tcp+udp from $LAN_CIDR"
        else
            CK_DETAIL="firewalld running; missing rich rules for $PORT $(fw_missing "$tcp" "$udp") from $LAN_CIDR"
            FW_KIND='firewalld'
        fi
    elif [ "$ufw" = 1 ]; then
        CK_RESULT=pass
        CK_DETAIL='ufw inactive'
    else
        CK_RESULT=pass
        CK_DETAIL='no host firewall active'
    fi
}

ck_firewall() {
    t_firewall
    if [ "$CK_RESULT" = pass ]; then
        return
    fi
    case "$FW_KIND" in
        settings)
            CK_FIXLINE='check System Settings > Network > Firewall by hand'
            ;;
        blockall)
            CK_FIXLINE='turn off System Settings > Network > Firewall > Options > Block all incoming connections; this script never changes it'
            ;;
        exe)
            CK_FIXLINE='fix the packages check first, then re-run'
            ;;
        app)
            set_fix fix_firewall_mac
            ;;
        unknown)
            if [ "$APPLY" = 1 ]; then
                CK_FIXLINE="'sudo -n' failed even after 'sudo -v'; run '$FW_READ' by hand"
            else
                CK_FIXLINE="run 'sudo -v' first, or use --apply"
            fi
            ;;
        ufw_weird)
            CK_FIXLINE="check 'sudo ufw status' by hand"
            ;;
        both)
            CK_FIXLINE="allow TCP and UDP $PORT from $LAN_CIDR in both firewalls by hand: sudo ufw allow from $LAN_CIDR to any port $PORT; and the two firewalld rich rules and reload shown in the fleet-host-prep spec P15"
            ;;
        ufw)
            set_fix fix_firewall_ufw
            ;;
        firewalld)
            set_fix fix_firewall_firewalld
            ;;
    esac
}

fix_firewall_mac() {
    if [ "$FW_LISTED" != 1 ]; then
        step sudo "$SOCKETFILTERFW" --add "$FW_EXE" || return
    fi
    step sudo "$SOCKETFILTERFW" --unblockapp "$FW_EXE"
}

fix_firewall_ufw() {
    step sudo ufw allow from "$LAN_CIDR" to any port "$PORT"
}

fix_firewall_firewalld() {
    if [ "$FW_MISS_TCP" = 1 ]; then
        step sudo firewall-cmd --permanent "--add-rich-rule=$FW_RULE_TCP" || return
    fi
    if [ "$FW_MISS_UDP" = 1 ]; then
        step sudo firewall-cmd --permanent "--add-rich-rule=$FW_RULE_UDP" || return
    fi
    step sudo firewall-cmd --reload
}

# ---------------------------------------------------------------------------
# Argument parsing (P5)
```

- [ ] **Step 4: Add the check to the sequence.** In `scripts/fleet-host-prep.sh`, replace (occurs once):

```bash
run_check searxng
```

with:

```bash
run_check searxng
run_check firewall
```

- [ ] **Step 5: Run the tests to verify they pass.**

Run: `python3 -m pytest tests/test_fleet_host_prep.py -q -p no:cacheprovider 2>&1 | tail -1`
Expected: `111 passed in ...` (about 62 s).

- [ ] **Step 6: Commit.**

```bash
git add scripts/fleet-host-prep.sh tests/test_fleet_host_prep.py
git diff --cached --name-only   # expected: exactly the two files
git commit -F - <<'EOF'
fleet-host-prep: firewall check (P15)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 7: linger check and whole-run tests

Implements P16 (linger, the last check) and closes the spec's whole-run requirements. Tests: the linger cases, H4(a), H1, H2(a)-(b), H3 (with H14 and H24), H4(b)'s later-fixes half, H5, H7, and the H8 and H26 summary counts. The H5 cases pass before this task's code exists (a passing host runs no fix with or without the linger check); they are here because they assert the whole run.

**Files:**
- Modify: `scripts/fleet-host-prep.sh` (insert above the anchor; extend the check sequence).
- Modify: `tests/test_fleet_host_prep.py` (append).

**Interfaces:**
- Consumes: Task 3's contract and helpers; `OS`; Tasks 4-5's test helpers `APT_FIX`, `OLLAMA_PROBE`, `VLLM_PROBE`, `SEARXNG_DEFAULT`, `shown`, `compose_plus_lines`, `assert_searxng_copied`.
- Produces: `LINGER_USER`; `t_linger`, `ck_linger`, `fix_linger`. In the test file: `CHECKS`, `assert_line_forms(r, allowed_extra=())`. The final check sequence (seven `run_check` lines).

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_fleet_host_prep.py` (the block begins with two empty lines):

```python


# ---------------------------------------------------------------------------
# Task 7: linger and whole runs (H1-H5, H4a, H7, H8 and H26 summaries, H14, H24)
# ---------------------------------------------------------------------------

CHECKS = ["platform", "packages", "clock", "model", "searxng", "firewall", "linger"]


def assert_line_forms(r, allowed_extra=()):
    for line in r.lines:
        if line in allowed_extra:
            continue
        assert any(re.fullmatch(form, line) for form in LINE_FORMS), line


def test_linger_check_mode():
    r = run(LINUX_ARGS, linux_state(linger="no"))
    assert r.status("linger") == "FAIL linger: Linger=no for tester"
    assert r.fix_after("linger") == "  fix: sudo loginctl enable-linger tester"
    assert mutating(r.calls()) == []
    assert r.rc == 1


def test_linger_fix():
    r = run(LINUX_ARGS + ["--apply"], linux_state(linger="no"))
    assert plus_lines(r.out) == ["+ sudo loginctl enable-linger tester"]
    assert r.status("linger") == "FIXED linger: Linger=yes for tester"
    assert r.rc == 0


def test_h4a_linger_fix_that_does_not_take():
    r = run(LINUX_ARGS + ["--apply"], linux_state(linger="no", fix={"linger": "noop"}))
    assert r.status("linger") == "FAIL linger: Linger=no for tester (fix did not take)"
    assert r.fix_after("linger") == "  fix: sudo loginctl enable-linger tester"
    assert r.rc == 1


def test_linger_without_loginctl():
    r = run(LINUX_ARGS + ["--apply"], linux_state(linger="no"), LINUX_ABSENT | {"loginctl"})
    assert r.status("linger") == "FAIL linger: loginctl not found"
    assert r.fix_after("linger") == ("  fix: the fleet service needs systemd user services; enable lingering "
                                     "for tester by hand")
    assert plus_lines(r.out) == []
    assert r.rc == 1


def test_h1_check_mode_all_fail_changes_nothing():
    r = run(LINUX_ARGS, all_fail_state(), ALL_FAIL_ABSENT)
    sx = r.sx
    assert r.lines == [
        "PASS platform: linux/apt",
        "FAIL packages: missing: python3 >= 3.9, git, pytest",
        "  fix: " + APT_FIX,
        "FAIL clock: NTPSynchronized=no",
        "  fix: sudo timedatectl set-ntp true",
        "FAIL model: 'qwen3.5:9b' not served by ollama at %s (serving: other-model:1b)" % OLLAMA_PROBE,
        "  fix: ollama pull qwen3.5:9b",
        "FAIL searxng: no answer at %s (curl exit 7)" % SEARXNG_DEFAULT,
        "  fix: docker start qwen-agent-searxng if that container exists, else: mkdir -p %s && cp %s %s %s && "
        "docker compose -p qwen-agent-searxng -f %s up -d (or re-run with --apply)"
        % (shown(sx), shown(WS + "/searxng/docker-compose.yml"), shown(WS + "/searxng/settings.yml"),
           shown(sx + "/"), shown(sx + "/docker-compose.yml")),
        "FAIL firewall: ufw active; no rule allows 8190 tcp, udp from 192.168.1.0/24",
        "  fix: sudo ufw allow from 192.168.1.0/24 to any port 8190",
        "FAIL linger: Linger=no for tester",
        "  fix: sudo loginctl enable-linger tester",
        "summary: 1 pass, 0 fixed, 6 fail, 0 unknown, 0 skip",
    ]
    assert [l.split(" ")[1] for l in status_lines(r.out)] == [c + ":" for c in CHECKS]
    assert mutating(r.calls()) == []
    assert r.named("docker") == [] and r.named("ollama") == []
    assert not os.path.exists(r.sx)
    assert_line_forms(r)
    assert r.rc == 1


def test_h2a_linux_all_pass():
    r = run(LINUX_ARGS)
    assert r.lines == [
        "PASS platform: linux/apt",
        "PASS packages: python3 >= 3.9, git, pytest",
        "PASS clock: NTPSynchronized=yes",
        "PASS model: 'qwen3.5:9b' served by ollama at " + OLLAMA_PROBE,
        "PASS searxng: HTTP 200 at " + SEARXNG_DEFAULT,
        "PASS firewall: ufw allows 8190 tcp+udp from 192.168.1.0/24",
        "PASS linger: Linger=yes for tester",
        "summary: 7 pass, 0 fixed, 0 fail, 0 unknown, 0 skip",
    ]
    assert r.rc == 0


def test_h2b_macos_all_pass():
    r = run(MAC_ARGS, mac_state(containers=["qwen-agent-searxng"]), MAC_ABSENT)
    assert r.lines == [
        "PASS platform: macOS 26.5.2",
        "PASS packages: python3 >= 3.9, git, pytest",
        "PASS clock: offset +0.003142 s from time.apple.com",
        "PASS model: 'qwen38-6bit' served by vllm at " + VLLM_PROBE,
        "PASS searxng: HTTP 200 at " + SEARXNG_DEFAULT,
        "PASS firewall: application firewall off",
        "SKIP linger: not applicable on macOS",
        "summary: 6 pass, 0 fixed, 0 fail, 0 unknown, 1 skip",
    ]
    assert r.rc == 0


def test_h3_apply_all_fail_fixes_everything():
    r = run(LINUX_ARGS + ["--apply"], all_fail_state(), ALL_FAIL_ABSENT)
    names = [(c["name"], c["argv"]) for c in r.calls()]
    assert names.count(("sudo", ["-v"])) == 1
    assert names.index(("id", ["-u"])) < names.index(("sudo", ["-v"])) < names.index(("uname", ["-s"]))
    assert plus_lines(r.out) == [
        "+ sudo apt-get update",
        "+ sudo apt-get install -y python3 git python3-pytest",
        "+ sudo timedatectl set-ntp true",
        "+ ollama pull qwen3.5:9b",
    ] + compose_plus_lines(r) + [
        "+ sudo ufw allow from 192.168.1.0/24 to any port 8190",
        "+ sudo loginctl enable-linger tester",
    ]
    assert [l.split(" ", 2)[:2] for l in status_lines(r.out)] == (
        [["PASS", "platform:"]] + [["FIXED", c + ":"] for c in CHECKS[1:]])
    fixed_model = "FIXED model: 'qwen3.5:9b' served by ollama at " + OLLAMA_PROBE
    assert r.lines.index("+ ollama pull qwen3.5:9b") < r.lines.index("pulling manifest") < r.lines.index(fixed_model)
    assert r.lines[-1] == "summary: 1 pass, 6 fixed, 0 fail, 0 unknown, 0 skip"
    assert_searxng_copied(r)
    # H14: every curl call starts with the fixed probe settings.
    assert r.named("curl") != []
    assert all(c["argv"][:5] == ["-sS", "--noproxy", "*", "--max-time", "5"] for c in r.named("curl"))
    # H24
    assert_line_forms(r, allowed_extra=("pulling manifest",))
    assert r.rc == 0


def test_h4b_a_failed_fix_does_not_stop_later_checks():
    r = run(LINUX_ARGS + ["--apply"], all_fail_state(fix={"packages": "exit:100"}), ALL_FAIL_ABSENT)
    assert r.status("packages") == "FAIL packages: missing: python3 >= 3.9, git, pytest (fix exited 100)"
    for name, prefix in (("timedatectl", "set-ntp"), ("ollama", "pull"), ("docker", "compose"),
                         ("ufw", "allow"), ("loginctl", "enable-linger")):
        assert r.named(name, prefix) != [], name
    assert r.lines[-1] == "summary: 1 pass, 5 fixed, 1 fail, 0 unknown, 0 skip"
    assert r.rc == 1


@pytest.mark.parametrize("args,state,absent", [
    (LINUX_ARGS, linux_state(), LINUX_ABSENT),
    (MAC_ARGS, mac_state(containers=["qwen-agent-searxng"]), MAC_ABSENT),
], ids=["linux", "macos"])
def test_h5_apply_on_a_passing_host_changes_nothing(args, state, absent):
    r = run(args + ["--apply"], state, absent)
    assert plus_lines(r.out) == [] and mutating(r.calls()) == []
    assert len(r.named("sudo", "-v")) == 1
    assert r.rc == 0


def test_h7_no_package_manager_still_fixes_linger():
    r = run(LINUX_ARGS + ["--apply"], linux_state(linger="no"), {"apt-get", "dnf", "sntp", "git"})
    assert r.status("platform") == "PASS platform: linux (no apt-get/dnf: packages must be installed by hand)"
    assert r.status("packages") == "FAIL packages: missing: git"
    assert r.fix_after("packages") == ("  fix: install python3 (>= 3.9), git and pytest with this host's "
                                       "package manager, then re-run")
    assert r.status("linger") == "FIXED linger: Linger=yes for tester"
    assert r.rc == 1


def test_h8_summary_counts_unknown():
    r = run(LINUX_ARGS, linux_state(sudo_n_ok=False))
    assert r.lines[-1] == "summary: 6 pass, 0 fixed, 0 fail, 1 unknown, 0 skip"
    assert r.rc == 1


def test_h26_summary_counts_skips():
    r = run(LINUX_ARGS + ["--no-searxng"], linux_state(searxng="down"))
    assert r.lines[-1] == "summary: 6 pass, 0 fixed, 0 fail, 0 unknown, 1 skip"
    assert r.rc == 0
    r = run(MAC_ARGS + ["--no-searxng"], mac_state(), MAC_ABSENT)
    assert r.lines[-1] == "summary: 5 pass, 0 fixed, 0 fail, 0 unknown, 2 skip"
    assert r.rc == 0
```

- [ ] **Step 2: Run the tests to verify the new ones fail.**

Run: `python3 -m pytest tests/test_fleet_host_prep.py -q -p no:cacheprovider 2>&1 | tail -1`
Expected: `12 failed, 113 passed in ...` (the two `test_h5_apply_on_a_passing_host_changes_nothing` cases pass already, see above).

- [ ] **Step 3: Insert the linger check.** In `scripts/fleet-host-prep.sh`, replace these two anchor lines (they occur once):

```bash
# ---------------------------------------------------------------------------
# Argument parsing (P5)
```

with this block, which ends with the same two anchor lines:

```bash
# ---------------------------------------------------------------------------
# linger (P16)
# ---------------------------------------------------------------------------

LINGER_USER=''

t_linger() {
    local out rc
    out=$(loginctl show-user "$LINGER_USER" -p Linger 2>/dev/null)
    rc=$?
    CK_RESULT=fail
    if [ "$rc" -ne 0 ]; then
        CK_DETAIL="'loginctl show-user' failed (exit $rc) for $LINGER_USER"
    elif [ "$out" = 'Linger=yes' ]; then
        CK_RESULT=pass
        CK_DETAIL="Linger=yes for $LINGER_USER"
    else
        CK_DETAIL="$out for $LINGER_USER"
    fi
}

ck_linger() {
    if [ "$OS" = mac ]; then
        CK_RESULT=skip
        CK_DETAIL='not applicable on macOS'
        return
    fi
    LINGER_USER=$(id -un 2>/dev/null)
    if ! command -v loginctl >/dev/null 2>&1; then
        CK_RESULT=fail
        CK_DETAIL='loginctl not found'
        CK_FIXLINE="the fleet service needs systemd user services; enable lingering for $LINGER_USER by hand"
        return
    fi
    t_linger
    if [ "$CK_RESULT" = pass ]; then
        return
    fi
    set_fix fix_linger
}

fix_linger() {
    step sudo loginctl enable-linger "$LINGER_USER"
}

# ---------------------------------------------------------------------------
# Argument parsing (P5)
```

- [ ] **Step 4: Add the check to the sequence.** In `scripts/fleet-host-prep.sh`, replace (occurs once):

```bash
run_check firewall
```

with:

```bash
run_check firewall
run_check linger
```

- [ ] **Step 5: Run the tests to verify they pass.**

Run: `python3 -m pytest tests/test_fleet_host_prep.py -q -p no:cacheprovider 2>&1 | tail -1`
Expected: `125 passed in ...` (about 80 s; it must be under 120 s, spec 6.1).

- [ ] **Step 6: Commit.**

```bash
git add scripts/fleet-host-prep.sh tests/test_fleet_host_prep.py
git diff --cached --name-only   # expected: exactly the two files
git commit -F - <<'EOF'
fleet-host-prep: linger check and whole-run tests (P16, H1-H5)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 8: Full-suite regression, untouched files, static review (no code)

Implements S5 on the Mac ([FLEET] T70), [FLEET] T72, and the H23 review. No file is changed and nothing is committed unless a defect is found; then fix it in the task that owns the code, re-run that task's Step 5, and re-run this task.

**Files:** none modified. Reads Task 1's baseline files. Writes `final-pytest.txt` and `vars.txt` into `/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-hostprep/`.

**Interfaces:** Consumes every earlier task.

- [ ] **Step 1: The new test file on its own, with timing.**

Run: `python3 -m pytest tests/test_fleet_host_prep.py -q -p no:cacheprovider 2>&1 | tail -1`
Expected: `125 passed in <T>s` with `<T>` under 120.

- [ ] **Step 2: S5, the full suite against the baseline (several minutes).**

```bash
python3 -m pytest tests/ -q -rA -p no:cacheprovider > /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-hostprep/final-pytest.txt 2>&1
tail -1 /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-hostprep/final-pytest.txt
grep -E '^(FAILED|ERROR)' /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-hostprep/final-pytest.txt
cd /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-hostprep
comm -23 <(grep '^PASSED' baseline-pytest.txt | sort) <(grep '^PASSED' final-pytest.txt | sort)
grep -c '^PASSED tests/test_fleet_host_prep.py::' final-pytest.txt
cd /Users/reubenpatterson/local_agent_harness/qwen-agent-workspace
```

Expected: the last line reads `1 failed, <P + 125> passed, 1 skipped, ...` with `<P>` from Task 1; the only `FAILED` line is the baseline's `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike`; `comm` prints nothing (no baseline pass was lost); the count is `125`.

- [ ] **Step 3: T72 and the file list (from the repo root).**

```bash
cd /Users/reubenpatterson/local_agent_harness
BASE=$(cat .superpowers/sdd/2026-10-17-hostprep/base-commit.txt)
git diff --quiet "$BASE" -- qwen-agent-workspace/scripts/deploy qwen-agent-workspace/fleet_lib.py qwen-agent-workspace/searxng && echo untouched-ok
git diff --name-only "$BASE"
git ls-files -s qwen-agent-workspace/scripts/fleet-host-prep.sh | cut -c1-6
git status --short
cd qwen-agent-workspace
```

Expected: `untouched-ok`; the name list is exactly `qwen-agent-workspace/scripts/fleet-host-prep.sh` and `qwen-agent-workspace/tests/test_fleet_host_prep.py`; the mode is `100755`; `git status --short` shows only the four unrelated untracked paths from Task 1.

- [ ] **Step 4: H23 and P4 review aids.**

```bash
S=scripts/fleet-host-prep.sh
LC_ALL=C comm -23 \
  <(grep -v '^[[:space:]]*#' "$S" | grep -oE '\$\{?[A-Za-z_][A-Za-z0-9_]*' | tr -d '${' | LC_ALL=C sort -u) \
  <(grep -v '^[[:space:]]*#' "$S" | grep -oE '^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*=' | tr -d ' =' | LC_ALL=C sort -u) \
  | tr '\n' ' ' | tee /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-hostprep/vars.txt; echo
grep -v '^[[:space:]]*#' "$S" | grep -nwE 'grep|sed|awk|cat|tr|head|cut|mktemp'; echo "utility-scan rc=$?"
grep -nE 'fleet\.env|QWEN_AGENT_FLEET|\.config/qwen-agent|api/tags|/models' "$S"; echo "string-scan rc=$?"
```

Expected, exactly: `BASH_REMATCH BASH_SOURCE FLEET_PREP_SOCKETFILTERFW HOME active f1 f2 f3 fn name tok w`, then `utility-scan rc=1`, then `string-scan rc=1`. In the variable list, the four upper-case names are the only environment or bash-provided reads (H23); the lower-case ones are function locals set by `local x=...` (`active`, `fn`, `name`), `read` (`f1`, `f2`, `f3`, `tok`) or `for` (`w`).

- [ ] **Step 5: Code review.** Dispatch a `design-reviewer` (Opus, high effort) over `git diff $(cat /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-hostprep/base-commit.txt)..HEAD` with this plan and the spec. At minimum it checks: the five Review Focus items; that plain `sudo` occurs only inside fix functions (P9 invariant; `grep -n 'sudo' scripts/fleet-host-prep.sh`); that every read's stderr goes to `/dev/null` and no fix command's output is captured (P10); every "Plan decisions" ruling below. A NEEDS-FIX verdict comes with an exact patch; apply it in the owning task's code, re-run Steps 1-4, and commit with that task's message prefix.

---

## Live acceptance (human-run after Task 8; spec Section 7)

Not an executor task: these steps run the script for real, with real `sudo`, on two hosts. The script must be committed and pushed on `qwen-agent-redteam` before L2.

| Step | Host | Command | Pass |
|---|---|---|---|
| L1 | Mac | `bash ~/local_agent_harness/qwen-agent-workspace/scripts/fleet-host-prep.sh --model-server-type vllm --model qwen38-6bit` | exit 0, or each `FAIL` line names a real gap (S1) |
| L2 | .168, interactive ssh, after `git clone --depth 1 --branch qwen-agent-redteam ... /tmp/qa-prep` | `bash /tmp/qa-prep/qwen-agent-workspace/scripts/fleet-host-prep.sh --model-server-type ollama --model qwen3.5:9b` | `FAIL searxng`, `UNKNOWN firewall`, other checks PASS, exit 1 (S2) |
| L3 | .168, run by the user | the same with `--apply` | exit 0 (S3); `curl -s 'http://127.0.0.1:8888/search?q=test&format=json'` returns JSON; `sudo ufw status` shows `8190 ALLOW 192.168.1.0/24` |
| L4 | .168 | the same `--apply` again | no `+ ` line, exit 0 (S4); then `rm -rf /tmp/qa-prep` |
| L6 | vision-185 (macOS, 192.168.1.185) | From a temp clone (`git clone --depth 1 --branch qwen-agent-redteam https://github.com/reubenpatterson1/local_agent_harness.git /tmp/qa-prep`; .185's `~/local_agent_harness` is an older checkout and is not used): `bash /tmp/qa-prep/qwen-agent-workspace/scripts/fleet-host-prep.sh --model-server-type vllm --model DreamFast/Qwen3-VL-4b-Heretic --no-searxng`, then `rm -rf /tmp/qa-prep` (mlx_vlm 0.7.2 on `:8177`) | `SKIP searxng: disabled by --no-searxng`, `SKIP linger`, `PASS model: 'DreamFast/Qwen3-VL-4b-Heretic' served by vllm at http://127.0.0.1:8177/v1/models`; exit 0, or with `--apply` added for any other FAIL (spec R7) |
| L5 | all hosts | `python3 -m pytest tests/ -q -rA` from `WS` ([FLEET] T70) | S5. On .168 this is the first run of `tests/test_fleet_host_prep.py` under bash 5.2.21, Python 3.12.3 and pytest 9.0.2: all 125 must pass there too. |

Use an interactive session for every `--apply` (spec R1: `sudo -v` needs a TTY). The live-only behaviors are real `sudo` prompting (P9), real ufw/firewalld after a fix, Docker bind mounts surviving a reboot (P14), and the Python.app firewall identity (P15, spec C1: unverified until a fleet host runs with the macOS firewall on).

---

## Coverage

### Requirements (P) to tasks

| ID | Task | ID | Task |
|---|---|---|---|
| P1 | 2 (header, mode) | P11 | 3 |
| P2 | 2 (H12 scan, re-run every task) | P12 | 3 (driver), 4-7 (each check's fix and re-check) |
| P3 | 2 | P13 platform | 3 |
| P4 | 2; 8 Step 4 (utility scan) | P13 clock | 4 |
| P5 | 2 | P13a | 4 |
| P6 | 2 (rejections), 6 (accepted values) | P14 | 5 |
| P7 | 2 | P15 | 6 |
| P8 | 2 (constants, H15b), 5 (use), 6 (`PY_EXE`) | P16 | 7 |
| P9 | 3 (`sudo -v`), 6 (`sudo -n` reads, UNKNOWN) | P17 | 2 (H23), 8 Step 4 |
| P10 | 3 (format), 7 (H24) | P18 | 2 (constant), 6 (H19g) |

### Tests (H) to tasks and test names

| H | Task | Test(s) |
|---|---|---|
| H1 | 7 | `test_h1_check_mode_all_fail_changes_nothing` |
| H2 | 3 (platform lines), 7 | `test_platform_lines`, `test_h2a_linux_all_pass`, `test_h2b_macos_all_pass` |
| H3 | 3 (sudo order), 4 (apt lines), 7 | `test_sudo_v_runs_once_with_apply_before_any_check`, `test_packages_apt_fix_runs_update_then_install`, `test_h3_apply_all_fail_fixes_everything` |
| H4 | 4 (b pre-fix detail, c), 7 (a, b later fixes) | `test_h4b_packages_fix_exit_keeps_the_pre_fix_detail`, `test_h4c_apt_update_failure_stops_the_install`, `test_h4a_linger_fix_that_does_not_take`, `test_h4b_a_failed_fix_does_not_stop_later_checks` |
| H5 | 7 | `test_h5_apply_on_a_passing_host_changes_nothing` (linux, macos) |
| H6 | 2 (rejections, help, root), 6 (accepted) | `test_h6_usage_errors` (21 cases), `test_h6_root_is_refused_after_validation`, `test_h6_help` (2), `test_h6_accepted_values` (3) |
| H7 | 4 (packages line), 7 | `test_packages_without_a_package_manager_has_no_automatic_fix`, `test_h7_no_package_manager_still_fixes_linger` |
| H8 | 6, 7 (summary) | `test_h8_ufw_unreadable_without_sudo_is_unknown`, `test_h8_summary_counts_unknown` |
| H9 | 5 | `test_h9a_...` through `test_h9g_...` |
| H10 | 5 | `test_h10_vllm_missing_model_is_never_fixed` |
| H11 | 4 | `test_h11_macos_clock_offsets` (7), `test_h11_macos_clock_failures`, `test_h11_macos_clock_fix` |
| H12 | 2 | `test_h12_file_rules_and_bash_compatibility` |
| H13 | 5 | `test_h13_custom_searxng_url_runs_no_docker` |
| H14 | 7 | inside `test_h3_apply_all_fail_fixes_everything` |
| H15 | 2 (b), 5 (a, c-g) | `test_h15b_model_url_logic_lives_in_fleet_lib`, `test_h15a_...`, `test_h15c_...` through `test_h15g_...` |
| H16 | 6 | `test_h16_ufw_rules_that_admit_the_lan` (4), `test_h16_ufw_rules_that_do_not` (6), `test_h16_ufw_status_variants`, `test_h16_non_default_port` |
| H17 | 6 | `test_h17a_...`, `test_h17b_...`, `test_h17_firewalld_check_mode`, `test_h17c_...`, `test_h17d_...` |
| H18 | 6 | `test_h18_ufw_and_firewalld_both_active` |
| H19 | 6 | `test_h19_macos_application_firewall` (a, b, g, h), `test_h19c_...`, `test_h19d_...`, `test_h19e_...` (2), `test_h19f_...`, `test_macos_firewall_on_without_python3` |
| H20 | 4 | `test_h20a_...`, `test_h20b_...`, `test_h20c_...`, `test_linux_clock_check_mode` |
| H21 | 3 | `test_h21_unsupported_platform_stops_at_once` |
| H22 | 3 | `test_h22_sudo_v_failure_changes_nothing` |
| H23 | 2, 8 Step 4 | `test_h23_no_secret_strings` |
| H24 | 7 | `assert_line_forms` in H1 and H3 |
| H25 | 4 | `test_h25_macos_pip_installs_only_pytest`, `test_h25_macos_without_python_or_git_never_runs_xcode_select` (2) |
| H26 | 5 (lines), 7 (summaries) | `test_h26_no_searxng_skips_the_check`, `test_h26_summary_counts_skips` |

### Success criteria (S)

| S | Automated | Live |
|---|---|---|
| S1 | H2(b), H11, H19 (Task 4, 6, 7) | L1 |
| S2 | H8, H9 check mode (Tasks 5-7) | L2 |
| S3 | H3 (Task 7) | L3 |
| S4 | H5 (Task 7) | L4 |
| S5 | Task 8 Steps 1-2 | L5 |

### Review Focus to tests

| Item | Test | Task |
|---|---|---|
| 1 Hugging Face model id | `test_review_focus_1_hugging_face_model_id` | 5 |
| 2 relative invocation | `test_review_focus_2_relative_invocation_from_another_directory` | 5 |
| 3 empty values | `test_review_focus_3_empty_values_from_unset_variables` | 2 |
| 4 model URL answering 404 | `test_review_focus_4_model_url_answering_404` | 5 |
| 5 HOME with a space | `test_review_focus_5_home_with_a_space` | 5 |

---

## Plan decisions (where the spec is silent or self-contradictory)

The spec's design is unchanged. Each item is a value the spec does not fix, or a conflict the plan resolves; each is pinned by code shown in its task.

**Spec conflicts resolved (proposed rulings for the user):**

1. **P1 vs P17/H23, the header's "never touches `fleet.env`" (Task 2).** P1 asks the header to state that the script never touches `fleet.env`; P17 and H23 forbid the string `fleet.env` anywhere in the script text, comments included. The header says "It never reads, writes or names the fleet secret file or any fleet variable" instead. Alternative (needs a spec change): exempt comments from H23.
2. **The harness keeps one `<tmp>` per session, not per test (Task 2).** On this Mac the first exec of every newly written file costs about 100 ms (measured: 0.13 s first exec, 0.003 s after; a hard link or symlink to an already-run file is fast). With fresh wrappers per run, 81 tests took 81 s at Task 5 and the full file would exceed spec 6.1's 120 s. The harness writes each wrapper once (exact Section 6.2 content, mode 0755) into `<tmp>/pristine/`, and every run resets the rest of `<tmp>` and hard-links the wrappers it needs into `<tmp>/stub/`; the apt-get/dnf fake's "create the python3 and git wrappers" also hard-links. Each run still gets an empty `HOME`, a fresh `state.json` and `calls.jsonl`, and the from-scratch `ENV`. Consequence: `Run` snapshots the call log and final state at construction, and a test must check files under `HOME` before its next `run()`.

**Values chosen by this plan:**

3. A value flag given an empty string counts as given: `--model ""` is `missing --model` (P6 says "absent or empty"), `--model-server-type ""`, `--lan-cidr ""` and `--port ""` fail their validation with `got ''`, and `--model-url ""` or `--searxng-url ""` keep the empty value (P6 does not validate URLs). Pinned by Review Focus 3.
4. A custom `--model-url` with no `ollama` CLI on PATH gets the custom-URL fix line (`pull '<MODEL>' into the Ollama server at <MODEL_URL> by hand`): P14's table lists that row before the not-on-PATH row.
5. A re-check that ends UNKNOWN (for example `sudo -n` failing after a fix) is reported as `FAIL <check>: <detail> (fix did not take)`: P12 reports any re-check that does not pass that way.
6. The usage text is a double-quoted bash string, because its `--port` line contains an apostrophe ("daemon's"). It contains no `$`, backquote, backslash or double quote, so it prints verbatim. The Python probes stay single-quoted (P8).
7. In check mode, the searxng fix line renders its paths with P10's quoting, like a `+` line (spec: "A `fix:` line uses the same rendering for the commands it lists").
8. Harness additions beyond Section 6.2's tables: state key `model_code` (default `200`; any other value makes the model-listing curl print `{"detail": "Not Found"}` and that code, exit 0), used only by Review Focus 4; `absent` may contain `"socketfilterfw"` to leave out that fake, used only by `test_h19f_unrecognized_or_missing_socketfilterfw` for P15's `<SFW> not found` branch; `loginctl show-user` and `enable-linger` accept only the state's `user` (any other argv exits 99, catching argv drift).
9. Tests beyond Section 6.3 (named in their tasks): the platform lines, package-manager fix lines, Linux clock check mode, model missing/pull, the searxng check-mode fix line, firewalld check mode, macOS firewall without python3, the linger cases, and the five Review Focus tests.

**Known residual risks (not covered by any automated test):**

- bash 5.2 / Ubuntu: the draft was run only under bash 3.2.57 on this Mac; L5 on .168 is the first bash 5.2 run.
- Two spec branches have no fake to drive them: `sw_vers` exiting nonzero (`macOS unknown`) and `loginctl show-user` exiting nonzero (`'loginctl show-user' failed (exit N) for <U>`). Both are one-line branches; review them by reading.
- `--lan-cidr` with a leading-zero octet (`192.168.001.0/24`) passes P6, but ufw and firewalld print the normalized network, so the check can never match what the fix adds and `--apply` ends `fix did not take`. A `/32` network likely behaves the same with ufw, which prints a bare address. P6 is binding; this is reported, not changed.
- P4's `WS` line runs `cd` on a relative directory when the script is invoked by a relative path; with `CDPATH` exported in the caller's environment, `cd` can resolve through `CDPATH`. The spec fixes that line verbatim; invoke the script by an absolute path (as R0 does) when `CDPATH` is set.
