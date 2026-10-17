# fleet-host-prep -- Design Spec (rollout R0 prerequisites check and fix)

Date: 2026-10-17
Status: The user approved every design decision in the 2026-10-17 brief: check mode by default and `--apply` to fix; the CLI; the seven checks and their order; the sudo policy; the output format; the SearXNG stable directory; reuse of `fleet_lib`; the test harness rules; and live acceptance. This document writes those decisions down precisely enough to implement them without reopening any. Two user-approved amendments (2026-10-17) add `--no-searxng` and `--port N`. Every value the brief left open is marked **[spec choice]** with a one-line reason, and Section 9 collects them all. No design decision is left open.

Repository: `/Users/reubenpatterson/local_agent_harness`, branch `qwen-agent-redteam`, HEAD `55ee4d5` when this was written. `WS` is `qwen-agent-workspace/`, and relative paths are relative to `WS`.

Parent spec: `docs/superpowers/specs/2026-10-16-fleet-discovery-self-update-design.md`, called **[FLEET]** below. This script automates [FLEET] Section 12 step R0, which now points here. Nothing in [FLEET] changes except R0.

ID conventions: `P<n>` is a requirement, `H<n>` is a test, and `S<n>` is a success criterion. These prefixes do not clash with [FLEET]'s F, T and K IDs.

---

## 0. Purpose and scope

### 0.1 Purpose

Rollout step R0 used to be a list of manual checks for each host. This script turns R0 into one command that runs unchanged on the Mac (`mac-local`, macOS, `/bin/bash` 3.2.57) and on .168 (`ollama-168`, Ubuntu 24.04, bash 5.2.21). By default it only reads state and reports. With `--apply` it also runs the fix for each failing check, then checks again.

### 0.2 Deliverables

| ID | Path | What |
|---|---|---|
| D1 | `scripts/fleet-host-prep.sh` | the script, mode `0755` |
| D2 | `tests/test_fleet_host_prep.py` | the pytest file (Section 6) |
| D3 | [FLEET] Section 12 R0 | already edited, as part of this spec |

No other file changes. In particular, nothing under `scripts/deploy/` changes: that directory is the ltx-chain package, and [FLEET] T72 requires it to be unchanged. The script must not be placed there.

### 0.3 Out of scope (explicit)

- `init-fleet`, `join`, `install`, and anything in R1 or later. The script stops before R1.
- Reading, writing, or naming `fleet.env`, `QWEN_AGENT_FLEET_*`, or any secret.
- Installing Docker, installing Ollama, or installing Xcode Command Line Tools. (The script only prints `xcode-select --install` as a manual instruction.)
- Starting, restarting, or pulling a model into any vLLM server. Starting an Ollama server.
- Turning a firewall on or off, or changing the macOS "block all incoming connections" setting.
- Hosts other than macOS and Linux. Package managers other than apt and dnf.
- Linux firewalls other than ufw and firewalld (for example, raw nftables or iptables rules).

### 0.4 Observed host state (2026-10-17, read-only)

| Item | .168 (`ollama-168`) | Mac (`mac-local`) |
|---|---|---|
| OS, bash | Ubuntu 24.04.4, bash 5.2.21 | macOS 26.5.2, `/bin/bash` 3.2.57 |
| Packages | apt-get; Python 3.12.3; git 2.43.0; pytest 9.0.2 | python3 = `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3` (3.13.0); `/usr/bin/sntp` |
| Clock | `NTPSynchronized=yes`; no `sntp` | `sntp -t 3 time.apple.com` printed `+0.035082 +/- 0.008554 time.apple.com 2620:149:a10:4000::31` |
| Model | Ollama serving `qwen3.5:9b` on `*:11434` | vllm-metal on `:8177` serving `qwen38-6bit` |
| SearXNG | not running; Docker 29.1.3 + Compose 2.40.3; user `reuben` is in the `docker` group | running from the dev-checkout compose on `127.0.0.1:8888`, container `qwen-agent-searxng` |
| Firewall | ufw active (rules unreadable without sudo; sudo needs a password); firewalld absent | application firewall off: `Firewall is disabled. (State = 0)` |
| Linger | `Linger=yes` | n/a |

Facts checked on the Mac while writing this spec. They are the reason for P15's design.

- `socketfilterfw --getglobalstate`, `--getblockall` and `--listapps` all work without root.
- `socketfilterfw --getappblocked <path>` prints `Incoming connection to <path> is permitted.` even for an app that is **not** in the firewall list (tested with `/bin/ls`). It therefore cannot tell whether an app was ever added, so P15 parses `--listapps` instead.
- `--listapps` prints `Total number of apps = N ` and then, for each app, two lines: `<i> : <path> ` (with a trailing space) and `             (Allow incoming connections)`.
- A python.org framework `python3` is a stub that re-executes as `.../Versions/3.13/Resources/Python.app/Contents/MacOS/Python`. That second binary is the process the firewall sees (`ps -o comm=` on the running interpreter's own PID shows it). `os.path.realpath(sys.executable)` instead gives `.../bin/python3.13`, which is the wrong binary. P15 therefore resolves the running image, not `sys.executable`. **This changes the brief's resolution command; see Section 10, item C1.**

Sources for output formats: ufw's `get_status` (`src/backend_iptables.py`) builds each rule row with `"%-26s %-12s%-26s%s%s\n"` (To, Action, From, then attributes, then ` # comment`). An incoming rule shows action `ALLOW`, an outgoing rule `ALLOW OUT`. A port-only rule with protocol `any` shows as `8190`, and IPv6 rows end their To field with ` (v6)`. firewalld's `Rich_Rule.__str__` (`src/firewall/core/rich.py`) builds `rule family="ipv4" source address="<a>" port port="<p>" protocol="<proto>" accept`.

### 0.5 Success criteria

| ID | Criterion |
|---|---|
| S1 | Check mode on the Mac exits 0, or prints a precise `FAIL` line for each real gap. |
| S2 | Check mode on .168 prints `FAIL searxng` and `UNKNOWN firewall`, `PASS` for every other check, and exits 1. |
| S3 | `--apply` on .168, run by the user, exits 0. |
| S4 | A second `--apply` run on .168 prints no `+ ` line and exits 0. |
| S5 | `tests/test_fleet_host_prep.py` passes on both hosts. No test that passed before the change fails after it ([FLEET] T70 procedure). |

### 0.6 Must-have vs nice-to-have

Everything in Sections 1-6 is a must-have. Nice-to-haves, not to be built: distro version in the platform line; a `--json` output mode; fixing Linux firewalls other than ufw and firewalld.

---

## 1. File, interpreter and shell rules

- **P1. File.** `scripts/fleet-host-prep.sh`, mode `0755` (git records the executable bit). The first line is exactly `#!/usr/bin/env bash`. After it comes a header comment block, in the style of `scripts/setup-lean-16gb.sh`. The block states: the purpose (automates [FLEET] R0); the usage line from P5; the seven checks; that check mode changes nothing; that the script never touches `fleet.env`; the test seam `FLEET_PREP_SOCKETFILTERFW` (P18); and a pointer to this spec.
- **P2. Bash compatibility.** The script must behave identically under bash 3.2.57 and bash 5.2.
  - Forbidden constructs:
    - `declare -A`, `local -A`, `typeset -A`
    - `mapfile`, `readarray`
    - `${x,}`, `${x,,}`, `${x^}`, `${x^^}`
    - `|&`, `;&`, `;;&`
    - `coproc`
    - negative array indices
    - `declare -n` and `local -n` (namerefs)
    - `[[ -v`
    - `&>>`
    - `{var}>` file-descriptor allocation
    - `${x@Q}` and other `@` transforms
    - `shopt -s globstar`
    - `wait -n`
    - `$EPOCHSECONDS`, `$EPOCHREALTIME`
  - **No arrays at all.** No `name=(...)` assignment, no `declare -a`, `local -a` or `read -a`. **[spec choice: bash < 4.4 treats `"${arr[@]}"` of an empty array as unbound under `set -u`; with no arrays, that trap cannot occur.]** Reading `${BASH_REMATCH[1]}` and `${BASH_SOURCE[0]}` is allowed. Lists of command words travel as function positional parameters (`"$@"`).
  - Regexes used with `[[ ... =~ ... ]]` are stored in a variable and used unquoted on the right-hand side (`[[ $x =~ $re ]]`). This behaves the same in 3.2 and 5.2.
  - Assignments that capture an exit status are written as `out=$(cmd); rc=$?` with `out` declared earlier (`local out rc` on its own line). `local out=$(cmd)` loses the status.
- **P3. Shell options and environment.** Near the top: `set -u` and `set -o pipefail`. **Never** `set -e`: every check must run even after another fails. Then `export LC_ALL=C`. **[spec choice: `ufw` and other tools translate their output, and the parser matches English text.]** There are no `trap`s. Ctrl-C ends the script with bash's default behavior.
- **P4. Locating the workspace.** `WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"`. All repo paths come from `WS`: `$WS/fleet_lib.py`, `$WS/searxng/docker-compose.yml`, `$WS/searxng/settings.yml`. The script does not `cd`.
  - External commands are invoked by bare name through `PATH`. There are two exceptions: `$SOCKETFILTERFW` (P18), and `/bin/ps` inside the Python probe `PY_EXE` (P8).
  - Apart from the commands each check reads or fixes with (Sections 3-4), the only external utilities the script uses are `dirname`, `mkdir` and `cp`. Everything else (string tests, parsing, loops, arithmetic) uses bash builtins. In particular there is no `grep`, `sed`, `awk`, `cat`, `tr`, `head`, `cut` or `mktemp`. Section 6's harness depends on this list.
  - Messages always name the script literally as `fleet-host-prep.sh`, never `$0`. **[spec choice: deterministic output for tests and docs.]**

## 2. CLI

- **P5. Arguments.** The usage text, printed exactly by `-h` and `--help` to stdout:

  ```
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
  ```

  Parsing is a `while [ $# -gt 0 ]; case "$1" in ... esac` loop.
  - `-h`/`--help`: print the usage and exit 0 at once. Nothing else runs, not even `id`.
  - `--apply` and `--no-searxng` take no value. Every other flag except `-h`/`--help` is a value flag.
  - Value flags take the **next** argument. A value flag that is last, or whose next argument starts with `--`, is a usage error `<flag> needs a value`. **[spec choice: catches `--model --apply`.]**
  - Repeating a flag: the last value wins.
  - `--flag=value` is not supported. It is an `unknown argument '<arg>'` error. **[spec choice: one syntax, fewer branches.]**
  - Any argument not listed above is an `unknown argument '<arg>'` error.
- **P6. Validation, after parsing, in this order.** The first failure prints two lines to stderr, `fleet-host-prep.sh: <problem>` and then `Run 'fleet-host-prep.sh --help' for usage.`, and exits 2.
  1. `--model-server-type` absent: `missing --model-server-type`.
  2. Its value not exactly `ollama` or `vllm`: `--model-server-type must be ollama or vllm, got '<v>'`.
  3. `--model` absent or empty: `missing --model`.
  4. `--no-searxng` and `--searxng-url` both given (in either order): `--no-searxng and --searxng-url cannot be used together`.
  5. `--lan-cidr` invalid: `--lan-cidr must be an IPv4 network with zero host bits, e.g. 192.168.1.0/24, got '<v>'`. **[spec choice]** A valid value:
     - matches `^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})/([0-9]{1,2})$`;
     - has each octet `<= 255` (use `10#` in arithmetic) and a prefix length `<= 32`;
     - has zero host bits: with `ip = (o1<<24)|(o2<<16)|(o3<<8)|o4`, `ip & ((1 << (32 - len)) - 1) == 0`, where a prefix length of 0 requires `ip == 0`. bash 3.2 arithmetic is 64-bit, so this is safe.

     Reason for zero host bits: ufw and firewalld display the normalized network address, so a check against `192.168.1.5/24` would never match what the fix adds.
  6. `--port` invalid: `--port must be a decimal integer from 1024 to 65535, got '<v>'`. A valid value matches `^[1-9][0-9]{3,4}$` and satisfies `1024 <= v <= 65535` (compare with `10#$v`). **[spec choice: no leading zeros, so the value is printed and matched in ufw and firewalld output exactly as ufw normalizes it.]**

  Defaults are applied after validation:
  - `MODEL_URL`: `http://127.0.0.1:11434/v1` (ollama) or `http://127.0.0.1:8177/v1` (vllm).
  - `SEARXNG_URL`: `http://127.0.0.1:8888/`.
  - `LAN_CIDR`: `192.168.1.0/24`.
  - `PORT`: `8190`.
  - `NO_SEARXNG`: `0` (`1` with `--no-searxng`).
  - `APPLY`: `0`.

  `--model-url` and `--searxng-url` are not validated.
- **P7. Root refusal.** After P6, if `id -u` prints `0`, print `fleet-host-prep.sh: refusing to run as root; run as the user who will run the fleet daemon (fixes use sudo)` to stderr and exit 2. Usage errors take precedence over the root check. **[spec choice: no system commands run before the arguments are known to be good.]**

## 3. Execution model

### 3.1 Python probes (fixed strings)

- **P8.** Each Python snippet is a single-quoted bash constant containing no single quotes, used verbatim. Section 6's `python3` shim matches the first three by exact argv.

  | Name | argv after `python3` | Purpose |
  |---|---|---|
  | `PY_VERSION` | `-c` `import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)` | exit 0 iff the version is >= 3.9 |
  | `PY_PYTEST` | `-c` `import pytest` | exit 0 iff pytest imports (user site enabled, as `install` checks it, [FLEET] F91) |
  | `PY_EXE` | `-I` `-B` `-c` `import os, subprocess; print(os.path.realpath(subprocess.check_output(["/bin/ps", "-o", "comm=", "-p", str(os.getpid())]).decode().strip()))` | the real binary the interpreter runs as (macOS only) |
  | `PY_PROBE_URL` | `-I` `-B` `-c` `import sys; sys.path.insert(0, sys.argv[1]); import fleet_lib; print(fleet_lib.probe_url({"type": sys.argv[2], "url": sys.argv[3]}))` `"$WS"` `"$TYPE"` `"$MODEL_URL"` | the model listing URL ([FLEET] F13) |
  | `PY_HAS_MODEL` | `-I` `-B` `-c` `import sys; sys.path.insert(0, sys.argv[1]); import fleet_lib; names = sorted(fleet_lib.parse_loaded_models(sys.argv[2], sys.stdin.buffer.read())); print(", ".join(names)); sys.exit(0 if sys.argv[3] in names else 3)` `"$WS"` `"$TYPE"` `"$MODEL"`, with the response body on stdin through `<<<"$body"` | prints the served names; exit 0 = present, 3 = absent, anything else = failure ([FLEET] F14) |

  The fleet_lib probes use `-I -B`. **[spec choice: `-I` keeps `PYTHON*` variables and the current directory out of the import path (fleet_lib is stdlib-only); `-B` keeps `__pycache__` out of the checkout.]** `PY_VERSION` and `PY_PYTEST` deliberately omit `-I`, so a `pip install --user` pytest is visible, exactly as `qwen-agentd install` sees it. Importing `fleet_lib` has no side effects: its module docstring guarantees it, and a 2026-10-17 audit of its top-level statements found only imports, constants, compiled regexes, and def and class statements. `fleet_lib.probe_url(model_server)` reads only `model_server["type"]` and `model_server["url"]`. `fleet_lib.parse_loaded_models(server_type, body_bytes)` returns a set and never raises. The strings `api/tags` and `/models` must not appear anywhere in the script, comments included (H15 checks this), so that the URL logic lives only in `fleet_lib`.

### 3.2 sudo

- **P9.** With `--apply`, run `sudo -v` once after P7 and before the first check. Print no `+` line for it, since it changes nothing. If it exits with a nonzero status `N`, print:

  ```
  FAIL sudo: 'sudo -v' failed (exit N); nothing was changed
    fix: re-run from an interactive terminal and enter your password, or run without --apply
  summary: 0 pass, 0 fixed, 1 fail, 0 unknown, 0 skip
  ```

  Then exit 1. No check runs.
  - Every read that needs root uses `sudo -n <cmd>`, in both modes. The reads are `ufw status`, `firewall-cmd --permanent --list-rich-rules`, and, on Linux for a user outside the `docker` group, `docker ps -a ...`. Reads that need no root are run without sudo.
  - Every fix that needs root uses plain `sudo <cmd>`.

  **Invariant:** plain `sudo` (with neither `-v` nor `-n`) appears only in fix commands. Tests rely on this.
- When `sudo -n` fails for a read, the check's status is `UNKNOWN`. Its fix line is `run 'sudo -v' first, or use --apply` in check mode. In `--apply` mode it is `'sudo -n' failed even after 'sudo -v'; run '<the read command with plain sudo>' by hand`. An UNKNOWN check runs no fix.

### 3.3 Output

- **P10. Lines.** Everything goes to stdout except usage and root errors (stderr), and except the stdout and stderr of fix commands, which are inherited and stream through unchanged (for example `ollama pull` progress, apt and compose output). Probe and read commands have their stdout captured and their stderr sent to `/dev/null`.
  - Status line: `<STATUS> <check>: <detail>`. `STATUS` is one of `PASS`, `FAIL`, `FIXED`, `SKIP`, `UNKNOWN`. `<check>` is one of `platform`, `packages`, `clock`, `model`, `searxng`, `firewall`, `linger` (or `sudo`, P9 only). Each check prints exactly one status line.
  - Every `FAIL` and `UNKNOWN` line is followed at once by `  fix: <text>`: two spaces, `fix:`, one space. A fix with several commands joins them with ` && `.
  - Before running each fix command, the script prints `+ <command>`. Each word is printed as-is and separated by one space, except for a word that contains a space:
    - if the word starts with `--` and contains `=`, it is printed as `<text up to and including the first =>'<rest>'`;
    - otherwise it is printed as `'<word>'`.

    No word ever contains a single quote. Example: `+ sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="192.168.1.0/24" port port="8190" protocol="tcp" accept'`. **[spec choice: produces copy-pasteable commands and matches the brief's notation.]** A `fix:` line uses the same rendering for the commands it lists.
  - The `+` lines for a check come before that check's status line. The status line is printed after the fix and the re-check.
  - The last line is `summary: <p> pass, <x> fixed, <f> fail, <u> unknown, <s> skip`, always with all five counts. **[spec choice]** It is printed by every run that gets past P7, including P9's sudo failure and an unsupported platform.
- **P11. Exit status.** 0 iff no check ended `FAIL` or `UNKNOWN`. 1 otherwise. 2 for P5-P7.

### 3.4 Check protocol

- **P12.** Every check follows one procedure (a helper, called here `run_check`, so all checks share it):
  1. Run the check's read-only test. It yields pass or fail and a detail string, or UNKNOWN (P9), or SKIP.
  2. If pass: `PASS`. If SKIP: `SKIP`. If UNKNOWN: `UNKNOWN` plus its fix line.
  3. If fail and **not** `--apply`, or if no automatic fix exists for this failure: `FAIL <check>: <detail>` plus the fix line.
  4. If fail, `--apply`, and an automatic fix exists: run the fix commands in order, each preceded by its `+` line (through a helper `run_fix word...`, which prints the `+` line and runs `"$@"`).
     - If a fix command exits with nonzero `N`, stop the remaining commands and print `FAIL <check>: <pre-fix detail> (fix exited N)` plus the fix line.
     - Otherwise re-check. For `clock` and `searxng` the re-check is a bounded poll (P13, P14). If the re-check passes: `FIXED <check>: <re-check's pass detail>`. If it fails: `FAIL <check>: <re-check's fail detail> (fix did not take)` plus the fix line.
  5. Continue with the next check whatever the outcome. The only exception is P13's unsupported platform.

  **Idempotence:** a check that passes runs no fix, so `--apply` on a host where everything passes runs no mutating command. `sudo -v` and the reads are allowed.
- **Probe settings.** Every `curl` call starts with exactly `curl -sS --noproxy '*' --max-time 5` (every probe is loopback or LAN, and the Mac runs Netskope). `sntp` is called as `sntp -t 3 time.apple.com`. The polls count iterations instead of reading a clock: P13 does up to 15 re-checks with `sleep 2` between consecutive re-checks (at most 14 sleeps); P14 does up to 30 probes with `sleep 1` between them (at most 29 sleeps). **[spec choice: 30 s and 30 s; counting iterations makes the tests deterministic.]**

---

## 4. The checks, in order

`SX` below is `$HOME/.local/share/qwen-agent/searxng`. `SFW` is `$SOCKETFILTERFW` (P18). `U` is the output of `id -un`.

### P13. `platform` and `clock`

**platform.** Read `uname -s`.

| Condition | Line |
|---|---|
| `Darwin` | `PASS platform: macOS <v>`, where `<v>` is `sw_vers -productVersion`'s stdout, or `unknown` if that exits nonzero |
| `Linux` and `apt-get` on PATH (`command -v`) | `PASS platform: linux/apt` |
| `Linux`, no `apt-get`, and `dnf` on PATH | `PASS platform: linux/dnf` |
| `Linux`, neither | `PASS platform: linux (no apt-get/dnf: packages must be installed by hand)` |
| anything else | `FAIL platform: unsupported OS '<uname output>'`, then `  fix: this script supports macOS (Darwin) and Linux only`, then the summary line, then exit 1. No other check runs. |

The platform decides `OS` (`mac` or `linux`) and `PKG` (`apt`, `dnf` or `none`) for the later checks.

**packages** is P13a below; `clock` follows it here.

**clock, Linux.**
- `timedatectl` not on PATH: `FAIL clock: timedatectl not found`, fix `enable NTP time synchronization on this host by hand, then re-run`. No automatic fix.
- Otherwise the test is `timedatectl show -p NTPSynchronized`. It passes iff stdout is exactly `NTPSynchronized=yes`. The pass detail is `NTPSynchronized=yes`. The fail detail is the stdout line as printed (for example `NTPSynchronized=no`), or `timedatectl show failed (exit N)` when it exits nonzero.
- Fix: `sudo timedatectl set-ntp true`. The re-check polls up to 15 times with `sleep 2` between polls. **[spec choice: NTP sync can lag the setting by seconds.]**

**clock, macOS.**
- `sntp` not on PATH: `FAIL clock: sntp not found`, fix `turn on System Settings > General > Date & Time > Set time and date automatically`. No automatic fix.
- Otherwise run `sntp -t 3 time.apple.com`.
  - A nonzero exit `N` fails with `sntp failed (exit N)`.
  - Otherwise take the first whitespace-separated token `tok` of the first stdout line. If `tok` does not match `^[+-]?[0-9]+(\.[0-9]+)?$`, fail with `unparseable sntp output '<first line>'`.
  - Otherwise strip one leading sign and take the integer part `ip="${t%%.*}"`. If `ip` is longer than 9 digits, or `(( 10#$ip >= 5 ))`, fail with `offset <tok> s from time.apple.com (limit 5 s)`. Otherwise pass with `offset <tok> s from time.apple.com`.

  This is pure bash, with no `awk`: |offset| < 5.0 exactly when the integer part is < 5.
- Fix, for any of these fail cases when `sntp` exists: `sudo systemsetup -setusingnetworktime on`. The re-check polls as on Linux.

### P13a. `packages`

The test, in this order:
- python ok: `command -v python3` succeeds **and** `python3 $PY_VERSION` exits 0.
- git ok: `git --version` exits 0, with output discarded. **[spec choice: macOS ships a `/usr/bin/git` shim even without Command Line Tools, so `command -v` alone gives a false pass; this is the same test `install` runs.]**
- pytest ok: python is ok **and** `python3 $PY_PYTEST` exits 0.

It passes iff all three are ok, with detail `python3 >= 3.9, git, pytest`. It fails with `missing: <items>`, where the items are, in order, whichever of `python3 >= 3.9`, `git`, `pytest` are not ok, joined by `, `.

**[spec choice: one check line, not three, because the brief's all-pass test expects exactly 7 status lines and Linux has one combined fix.]**

| Host | Automatic fix (run with `--apply`) | Fix line |
|---|---|---|
| linux/apt | `sudo apt-get update`, then `sudo apt-get install -y python3 git python3-pytest` | `sudo apt-get update && sudo apt-get install -y python3 git python3-pytest` |
| linux/dnf | `sudo dnf install -y python3 git python3-pytest` | the same command |
| linux, no apt/dnf | none | `install python3 (>= 3.9), git and pytest with this host's package manager, then re-run` |
| macOS, python or git not ok | none (never run) | `xcode-select --install (or install Python >= 3.9 from python.org), then re-run` |
| macOS, only pytest not ok | `python3 -m pip install --user pytest` | the same command |

The re-check runs once.

### P14. `model` and `searxng`

**model.**
1. If `command -v python3` fails, or `python3 -I -B -c "$PY_PROBE_URL" ...` exits nonzero or prints nothing: `FAIL model: python3 cannot load fleet_lib from <WS>`, fix `needs python3 >= 3.9 (see packages) and <WS>/fleet_lib.py from a complete checkout`. No automatic fix.
2. `PROBE` is that output. Run `out=$(curl -sS --noproxy '*' --max-time 5 -w '\n%{http_code}' "$PROBE" 2>/dev/null); rc=$?`.
   - If `rc != 0`, fail with `<type> not reachable at <PROBE> (curl exit <rc>)`.
   - Otherwise, with `NL=$'\n'`: `code="${out##*"$NL"}"` and `body="${out%"$NL"*}"`. If `code` is not `200`, fail with `<type> not reachable at <PROBE> (HTTP <code>)`.

   Both of these fail cases are **server down**. Fix line: `start the <type> model server at <MODEL_URL>; this script never starts model servers`. No automatic fix. **[spec choice: `ollama pull` against a server that is down cannot succeed.]**
3. Run `names=$(python3 -I -B -c "$PY_HAS_MODEL" "$WS" "$TYPE" "$MODEL" <<<"$body"); prc=$?`.
   - `prc` 0: `PASS model: '<MODEL>' served by <type> at <PROBE>`.
   - `prc` 3: **model missing**, with detail `'<MODEL>' not served by <type> at <PROBE> (serving: <names, or none if empty>)`.
   - any other `prc`: as in step 1.

**model, missing-model fix**, by case:

| Case | Automatic fix | Fix line |
|---|---|---|
| ollama, `MODEL_URL` exactly the ollama default, `ollama` on PATH | `ollama pull <MODEL>` (output streams; re-check once) | `ollama pull <MODEL>` |
| ollama, custom `MODEL_URL` | none | `pull '<MODEL>' into the Ollama server at <MODEL_URL> by hand` |
| ollama, `ollama` not on PATH | none | `the ollama CLI is not on PATH; pull '<MODEL>' by hand (this script never installs Ollama)` |
| vllm | none | `start vllm-metal serving '<MODEL>' at <MODEL_URL> by hand; this script never starts, restarts or pulls for vLLM` |

The custom-URL case has no automatic fix. **[spec choice: `ollama pull` targets the CLI's default server, which may not be the one at a custom `--model-url`.]**

**searxng.**
- With `--no-searxng`: `SKIP searxng: disabled by --no-searxng`. No `curl` call for SearXNG, no `docker` call, and no fix, in both modes. A SKIP never fails the run (P11). The model check's own `curl` call is not affected.
- Otherwise the test is `code=$(curl -sS --noproxy '*' --max-time 5 -o /dev/null -w '%{http_code}' "$SEARXNG_URL" 2>/dev/null); rc=$?`.
  - Pass iff `rc` is 0 and `code` is `200`, with detail `HTTP 200 at <SEARXNG_URL>`.
  - Fail with `no answer at <SEARXNG_URL> (curl exit <rc>)` when `rc` is nonzero, or `HTTP <code> at <SEARXNG_URL>` otherwise.
- **Custom URL** (`SEARXNG_URL` is not exactly `http://127.0.0.1:8888/`): no automatic fix. Fix line: `check that <SEARXNG_URL> is up and that no_proxy covers its host; if this host cannot run SearXNG, set QWEN_AGENT_SEARXNG_URL with the systemd drop-in described in R0 of the fleet spec`. No `docker` command runs.
- **Default URL.**
  - `DOCKER` is `docker` on macOS, and on Linux when the word `docker` is in `id -nG` (match `" $(id -nG) "` against `*" docker "*`). Otherwise it is `sudo docker`, and the read is `sudo -n docker`.
  - Check mode runs no `docker` command. Its fix line, with every `docker` replaced by `sudo docker` when `DOCKER` is `sudo docker`, is: `docker start qwen-agent-searxng if that container exists, else: mkdir -p <SX> && cp <WS>/searxng/docker-compose.yml <WS>/searxng/settings.yml <SX>/ && docker compose -p qwen-agent-searxng -f <SX>/docker-compose.yml up -d (or re-run with --apply)`.
  - In `--apply` mode:
    1. `docker` not on PATH: `FAIL searxng: <fail detail>; Docker not installed (this script never installs Docker)`, fix `install Docker, or use another SearXNG instance through QWEN_AGENT_SEARXNG_URL (fleet spec R0), then re-run`.
    2. Read the container names: `docker ps -a --format '{{.Names}}'`, run directly or through `sudo -n` (see `DOCKER` above). If it exits with nonzero `N` (in either form, since a `sudo -n` failure is not distinguishable here and cannot happen after a successful `sudo -v` with normal sudoers): `FAIL searxng: <fail detail>; 'docker ps -a' failed (exit N): is the Docker daemon running?`, fix `start Docker, then re-run`.
    3. If one output line is exactly `qwen-agent-searxng`, run the fix `<DOCKER> start qwen-agent-searxng`. This avoids a name conflict with the container from the Mac's dev-checkout compose project.
    4. Otherwise run the fix commands, in order:

       ```
       mkdir -p <SX>
       cp <WS>/searxng/docker-compose.yml <WS>/searxng/settings.yml <SX>/
       <DOCKER> compose -p qwen-agent-searxng -f <SX>/docker-compose.yml up -d
       ```

       `cp` overwrites existing copies.
    5. The re-check polls up to 30 probes with `sleep 1` between them.

  Reason for the stable directory: compose bind-mounts `./settings.yml` relative to the compose file. If the script ran compose from `/tmp/qa-prep` (deleted in R0) or from a release directory (pruned by self-update, [FLEET] F88a), the source would vanish, and after a reboot Docker would silently mount an empty directory. `SX` sits under the deploy root `D`, which `install` later chmods to `0700` without touching other entries ([FLEET] F80, F91). Pruning touches only `D/releases/`. A `0700` parent does not affect the container, because the bind mount is resolved by the root-owned Docker daemon.

### P15. `firewall`

The firewall must admit port `PORT` (`--port`, default 8190), TCP and UDP, from `LAN_CIDR`. Below, `<PORT>` stands for its value. The macOS application firewall allows by binary, not by port, so `PORT` does not affect the macOS branch or its messages. **[spec choice: the macOS messages stay port-free because the rule they describe is port-free.]**

**macOS.** `SFW --getglobalstate`, then:

| Output contains | Result |
|---|---|
| `State = 0` | `PASS firewall: application firewall off` |
| `State = 1` or `State = 2` | firewall on; continue below |
| neither, or `SFW` not executable (`[ -x ]`) | `FAIL firewall: unrecognized socketfilterfw output '<first line>'` (or `FAIL firewall: <SFW> not found`), fix `check System Settings > Network > Firewall by hand`. No automatic fix. |

With the firewall on:
1. If the state is 2, or `SFW --getblockall` output contains `enabled` or `ENABLED`: `FAIL firewall: block all incoming connections is on`, fix `turn off System Settings > Network > Firewall > Options > Block all incoming connections; this script never changes it`. No automatic fix. **[spec choice: block-all overrides per-app rules, and it is a security setting the user must change.]**
2. `EXE` is the output of `python3 -I -B -c "$PY_EXE"`. If python3 is missing, the probe exits nonzero, or the output is empty: `FAIL firewall: cannot resolve the python3 binary`, fix `fix the packages check first, then re-run`.
3. Parse `SFW --listapps` with a `while IFS= read -r line` loop over a here-string.
   - A line is an entry line when it matches `^[0-9]+ : (.*[^ ])[ ]*$`, and `${BASH_REMATCH[1]}` is its path.
   - `EXE` is **listed** when one entry's path equals `EXE`.
   - It is **allowed** when the line right after that entry line contains `(Allow incoming connections)`.
4. Allowed: `PASS firewall: application firewall on; <EXE> allowed`. Otherwise: fail with `application firewall on; <EXE> not allowed`.
   - Fix when not listed: `sudo <SFW> --add <EXE>`, then `sudo <SFW> --unblockapp <EXE>`.
   - Fix when listed but blocked: only `sudo <SFW> --unblockapp <EXE>`. **[spec choice: does not rely on what `--add` does for an app that is already listed.]**
   - The fix line lists the same commands. The re-check runs once.

The daemon must be installed with this same `python3` ([FLEET] F90 records `sys.executable` of `install`; R0 says so).

**Linux.**
1. `UFW=1` iff `command -v ufw`. `FWD=1` iff `command -v firewall-cmd` and `firewall-cmd --state` (no sudo) prints exactly `running`.
2. If `UFW=1`, read `sudo -n ufw status`.
   - A nonzero exit gives `UNKNOWN firewall: cannot read ufw rules without sudo` (P9; the read command, shown with plain sudo, is `sudo ufw status`).
   - First line `Status: inactive` gives `UFW_ACTIVE=0`. `Status: active` gives `UFW_ACTIVE=1`.
   - Any other first line gives `FAIL firewall: unrecognized 'ufw status' output '<line>'`, fix `check 'sudo ufw status' by hand`.
Steps 3-6 form one if/elif chain, evaluated in this order; the first matching branch decides.
3. `UFW_ACTIVE=1` and `FWD=1`: `FAIL firewall: ufw and firewalld are both active`, fix `allow TCP and UDP <PORT> from <CIDR> in both firewalls by hand: sudo ufw allow from <CIDR> to any port <PORT>; and the two firewalld rich rules and reload shown in the fleet-host-prep spec P15`. No automatic fix. **[spec choice: running both is unusual and they can conflict; the script does not guess which one governs.]**
4. Else if `UFW_ACTIVE=1`: scan the status lines with `while read -r f1 f2 f3 rest` (default IFS).
   - A line **allows** when `f2` is `ALLOW` and `f3` is `<CIDR>` or `Anywhere`. **[spec choice: a broader `Anywhere` allow still admits the LAN.]**
   - `f1` equal to `<PORT>` covers TCP and UDP, `<PORT>/tcp` covers TCP, `<PORT>/udp` covers UDP. A row for any other port (for example `8190` when `PORT` is `8191`) covers nothing.
   - Every other line is ignored. This excludes `(v6)` rows (where `f2` is `(v6)`), interface rows (`<PORT> on eth0`, where `f2` is `on`), `DENY`, `LIMIT` and `REJECT` rows, `ALLOW OUT` rows (where `f3` is `OUT`), rows with a destination address, and the header lines.
   - It passes iff TCP and UDP are both covered, with detail `ufw allows <PORT> tcp+udp from <CIDR>`. Otherwise it fails with `ufw active; no rule allows <PORT> <missing> from <CIDR>`, where `<missing>` is `tcp, udp`, `tcp` or `udp`.
   - Fix (one command, which covers both protocols): `sudo ufw allow from <CIDR> to any port <PORT>`. The re-check runs once.
5. Else if `FWD=1`: read `sudo -n firewall-cmd --permanent --list-rich-rules`. A nonzero exit gives UNKNOWN, `cannot read firewalld rules without sudo`, with the read command shown as `sudo firewall-cmd --permanent --list-rich-rules`.
   - `RULE_tcp` and `RULE_udp` are exactly `rule family="ipv4" source address="<CIDR>" port port="<PORT>" protocol="<proto>" accept`.
   - It passes iff each of them equals some output line, with detail `firewalld allows <PORT> tcp+udp from <CIDR>`. Otherwise it fails with `firewalld running; missing rich rules for <PORT> <missing> from <CIDR>`.
   - Fix: `sudo firewall-cmd --permanent --add-rich-rule=<RULE_p>` for each **missing** protocol, in the order tcp then udp, then `sudo firewall-cmd --reload`. **[spec choice: adds only what is missing, so the script never depends on `ALREADY_ENABLED` exit codes.]** The re-check runs once.
6. Else if `UFW=1` (so ufw is inactive and firewalld is not running): `PASS firewall: ufw inactive`. Else (`UFW=0`, `FWD=0`): `PASS firewall: no host firewall active`.

Known limitation: the check reads only the rules shown by `ufw status` and firewalld's default zone. It does not read ufw's default incoming policy, the order of rules (a `DENY` above an `ALLOW`), or firewalld zone bindings by source. A host that admits `PORT` some other way gets a redundant rule from `--apply`. That is harmless.

### P16. `linger`

- macOS: `SKIP linger: not applicable on macOS`.
- Linux, `loginctl` not on PATH: `FAIL linger: loginctl not found`, fix `the fleet service needs systemd user services; enable lingering for <U> by hand`.
- Linux: the test is `loginctl show-user "<U>" -p Linger`. It passes iff the exit status is 0 and stdout is exactly `Linger=yes`, with detail `Linger=yes for <U>`.
  - It fails with `Linger=<v> for <U>` when stdout is `Linger=<v>`.
  - It fails with `'loginctl show-user' failed (exit N) for <U>` when loginctl exits nonzero (a user with no session and no linger).
  - Fix: `sudo loginctl enable-linger <U>`. The re-check runs once.

## 5. Scope guards

- **P17. No secrets.** The script never contains the strings `fleet.env`, `QWEN_AGENT_FLEET` or `.config/qwen-agent`. It reads no environment variable except `HOME`, `PATH` and `FLEET_PREP_SOCKETFILTERFW`. It never runs `qwen-agentd`. It never writes outside `SX` (through the fix commands' `mkdir` and `cp`), except through fix commands that change system state (apt, dnf, pip, docker, ufw, firewall-cmd, loginctl, timedatectl, systemsetup, socketfilterfw, ollama).
- **P18. Test seam.** `SOCKETFILTERFW="${FLEET_PREP_SOCKETFILTERFW:-/usr/libexec/ApplicationFirewall/socketfilterfw}"`. This is the script's only environment seam; the header comment documents it as a test seam. Every other test control comes from `PATH`.

---

## 6. Tests (`tests/test_fleet_host_prep.py`)

### 6.1 Rules

- pytest, stdlib only. The file must pass on the Mac (bash 3.2, Python 3.13, pytest 8.3.4) and on .168 (bash 5.2, Python 3.12, pytest 9.0.2). The suite must take under 120 s on the Mac.
- `WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))` and `SCRIPT = os.path.join(WS, "scripts", "fleet-host-prep.sh")`. The tests run the real script against the real `fleet_lib.py` and the real `searxng/` files.
- Every run uses `subprocess.run(["/bin/bash", SCRIPT, *args], env=ENV, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)`. `ENV` is built from scratch and never copies `os.environ`:
  - `PATH=<tmp>/stub`
  - `HOME=<tmp>/home` (created empty)
  - `TMPDIR=<tmp>/t`
  - `FLEET_PREP_SOCKETFILTERFW=<tmp>/sfw/socketfilterfw`

  The real HOME is never used, and no real sudo, apt, dnf, docker, ufw, firewall-cmd, loginctl, timedatectl, systemsetup, socketfilterfw, sntp, ollama or pip ever runs.

### 6.2 Harness

The test file writes a dispatcher `<tmp>/fakebin.py` (its source is a string constant in the test file) and a JSON state file `<tmp>/state.json`.

**Stub directory `<tmp>/stub`.**
- Each fake command `NAME` is a bash wrapper, mode `0755`, with exactly this content:

  ```
  #!/bin/bash
  exec '<sys.executable>' -I -B '<tmp>/fakebin.py' '<tmp>' 'NAME' "$@"
  ```
- The real tools `dirname`, `mkdir` and `cp` are symlinks to `shutil.which(name)`, resolved with the test process's own PATH. A command absent from the stub directory does not exist for that test.
- `FAKE_NAMES` are `uname sw_vers id sudo python3 git apt-get dnf timedatectl sntp systemsetup curl ollama docker ufw firewall-cmd loginctl sleep xcode-select`.
- `socketfilterfw` is the same kind of wrapper, at `<tmp>/sfw/socketfilterfw`, which is not on PATH.
- Each scenario names an `absent` set of FAKE_NAMES whose wrappers are not created.
  - Linux default: `absent = {"dnf", "sntp"}`.
  - macOS default: `absent = {"apt-get", "dnf", "timedatectl", "loginctl", "ufw", "firewall-cmd"}`.
- `xcode-select` and `sw_vers` are always present, so a forbidden call is recorded.

**Dispatcher.** `fakebin.py <tmp> <name> args...`:
1. Load `state.json`.
2. Compute its stdout, stderr, exit code and state change from the table below.
3. Write `state.json` back, then append one JSON line `{"name": name, "argv": args, "rc": rc}` to `<tmp>/calls.jsonl`.
4. Exit.

`sudo` with a command, and the `python3` pass-through, append their line with `"rc": null` and then `os.execv` (sudo execs `<tmp>/stub/<cmd>`; the pass-through execs `sys.executable`). Any argv not listed in the table exits **99** with `unexpected argv` on stderr. Every test asserts that no call has `rc == 99`. This catches argv drift between the script and the fakes.

**State keys and defaults** (Linux all-pass; the `mac_state()` helper overrides the macOS keys):

| Key | Default | Meaning |
|---|---|---|
| `os` | `"Linux"` | `uname -s` output |
| `macos_version` | `"26.5.2"` | |
| `uid`, `user`, `groups` | `1000`, `"tester"`, `"tester docker"` | `id` outputs |
| `sudo_v_exit` | `0` | |
| `sudo_n_ok` | `true` | |
| `py_ok`, `pytest_ok` | `true`, `true` | |
| `clock_linux` | `"yes"` | |
| `sntp_out`, `sntp_exit` | `"+0.003142 +/- 0.010472 time.apple.com 17.253.4.125"`, `0` | |
| `model` | `"ok"` | `ok`, `missing` or `down` |
| `model_name` | `"qwen3.5:9b"` | |
| `searxng` | `"ok"` | `ok` or `down` |
| `containers` | `[]` | |
| `docker_ps_exit` | `0` | |
| `ufw_out` | `UFW_OK` (below) | |
| `firewalld` | `"not running"` | |
| `firewalld_rules` | `[]` | |
| `linger` | `"yes"` | |
| `sfw_global` | `"Firewall is disabled. (State = 0)"` | |
| `sfw_blockall` | `"Firewall has block all state set to disabled."` | |
| `sfw_apps` | `[]` | list of `[path, "allow" or "block"]` |
| `python_exe` | `"/opt/fakepy/Python.app/Contents/MacOS/Python"` | |
| `fix` | `{}` | |
| `lag` | `{}` | |
| `pending_lag` | `{}` | |

`UFW_OK` is `"Status: active\n\nTo                         Action      From\n--                         ------      ----\n"` followed by the rows `"%-26s %-12s%-26s\n" % ("22/tcp", "ALLOW", "Anywhere")`, `... % ("8190", "ALLOW", "192.168.1.0/24")` and `... % ("22/tcp (v6)", "ALLOW", "Anywhere (v6)")`. `UFW_NONE` is the same without the 8190 row.

**Fix control.**
- `fix[<group>]` is `"ok"` (the default when absent), `"noop"` (exit 0 and change nothing) or `"exit:N"` (exit N and change nothing).
- The groups are: `apt_update` (`apt-get update`); `packages` (apt-get or dnf install, pip install); `clock` (`timedatectl set-ntp`, `systemsetup`); `model` (`ollama pull`); `searxng` (`docker start`, `docker compose`); `firewall` (`ufw allow`, `firewall-cmd --add-rich-rule`/`--reload`, `socketfilterfw --add`/`--unblockapp`); `linger` (`loginctl enable-linger`).
- `lag[<k>] = n`, for `k` in `clock` and `searxng`: when an `ok` fix for `k` succeeds, set `pending_lag[k] = n`. Each later read of `k` (`timedatectl show`, or the searxng curl) while `pending_lag[k] > 0` reports the failing value and decrements the counter.

**Accepted argv and behavior** (an argv not listed exits 99):

| Fake | argv | Behavior |
|---|---|---|
| `uname` | `-s` | print `os` |
| `sw_vers` | `-productVersion` | print `macos_version` |
| `id` | `-u` / `-un` / `-nG` | print `uid` / `user` / `groups` |
| `sudo` | `-v` | exit `sudo_v_exit` |
| `sudo` | `-n CMD ...` | if not `sudo_n_ok`: stderr `sudo: a password is required`, exit 1; else resolve and exec `CMD ...` as in the next row |
| `sudo` | `CMD ...` | resolve `CMD`: if it contains `/`, use it as-is (the socketfilterfw path); else `<stub>/CMD`. If that file does not exist, stderr `sudo: CMD: command not found`, exit 1; else exec it with the remaining args |
| `python3` | `-c PY_VERSION` | exit 0 if `py_ok` else 1 |
| `python3` | `-c PY_PYTEST` | exit 0 if `py_ok and pytest_ok` else 1 |
| `python3` | `-I -B -c PY_EXE` | print `python_exe` |
| `python3` | `-m pip install --user pytest` | group `packages`: `pytest_ok = true` |
| `python3` | anything else | pass-through to the real interpreter |
| `git` | `--version` | print `git version 2.43.0` |
| `apt-get` | `update` | group `apt_update`; no state change |
| `apt-get` | `install -y python3 git python3-pytest` | group `packages`: create the `python3` and `git` wrappers if absent; `py_ok = pytest_ok = true` |
| `dnf` | `install -y python3 git python3-pytest` | same as apt-get install |
| `timedatectl` | `show -p NTPSynchronized` | print `NTPSynchronized=<clock_linux>` (or `no` while lagging) |
| `timedatectl` | `set-ntp true` | group `clock`: `clock_linux = "yes"` |
| `sntp` | `-t 3 time.apple.com` | print `sntp_out`, exit `sntp_exit` |
| `systemsetup` | `-setusingnetworktime on` | group `clock`: `sntp_out = "+0.001000 +/- 0.010000 time.apple.com 17.253.4.125"`, `sntp_exit = 0` |
| `curl` | `-sS --noproxy * --max-time 5 -w \n%{http_code} URL` (the `\n` is the two characters `\` and `n`), where URL ends `/api/tags` or `/models` | `down`: print `\n000` as a real newline, exit 7. Else print the body, then a newline, then `200`. The body for `/api/tags` is `{"models": [{"name": n, "model": n} for n in served]}`; for `/models` it is `{"object": "list", "data": [{"id": n, "object": "model"} for n in served]}`. `served = [model_name, "other-model:1b"]` if `ok`, else `["other-model:1b"]`. |
| `curl` | `-sS --noproxy * --max-time 5 -o /dev/null -w %{http_code} URL` | `searxng` `down` (or lagging): print `000`, exit 7; `ok`: print `200` |
| `ollama` | `pull M` | print `pulling manifest`; group `model`: `model = "ok"`, `model_name = M` |
| `docker` | `ps -a --format {{.Names}}` | print `containers`, one per line; exit `docker_ps_exit` |
| `docker` | `start qwen-agent-searxng` | exit 1 if the name is not in `containers`; group `searxng`: `searxng = "ok"` |
| `docker` | `compose -p qwen-agent-searxng -f F up -d` | exit 14 unless `F` and `dirname(F)/settings.yml` both exist; group `searxng`: append `qwen-agent-searxng` to `containers`, `searxng = "ok"` |
| `ufw` | `status` | print `ufw_out` |
| `ufw` | `allow from C to any port P` | group `firewall`: append the row `"%-26s %-12s%-26s\n" % (P, "ALLOW", C)` to `ufw_out` |
| `firewall-cmd` | `--state` | print `firewalld`; exit 0 if it is `running`, else 252 |
| `firewall-cmd` | `--permanent --list-rich-rules` | print `firewalld_rules`, one per line |
| `firewall-cmd` | `--permanent --add-rich-rule=R` | group `firewall`: append `R` |
| `firewall-cmd` | `--reload` | group `firewall`: no state change |
| `loginctl` | `show-user <user> -p Linger` | print `Linger=<linger>` |
| `loginctl` | `enable-linger <user>` | group `linger`: `linger = "yes"` |
| `sleep` | `1` or `2` | exit 0 at once |
| `socketfilterfw` | `--getglobalstate` / `--getblockall` | print `sfw_global` / `sfw_blockall` |
| `socketfilterfw` | `--listapps` | print `Total number of apps = N `, then for app `i` (1-based): `"%d : %s " % (i, path)` and `"             (%s incoming connections)" % ("Allow" or "Block")` |
| `socketfilterfw` | `--add P` | group `firewall`: append `[P, "block"]` if not present |
| `socketfilterfw` | `--unblockapp P` | group `firewall`: set P to `"allow"` |
| `xcode-select` | any | exit 99 |

**Assertion helpers.**
- `calls()` parses `calls.jsonl`.
- `plus_lines(stdout)` returns the lines that start with `+ `.
- `status_lines(stdout)` returns the lines that match `^(PASS|FAIL|FIXED|SKIP|UNKNOWN) [a-z]+: `.
- `mutating(calls)` returns the calls that are any of:
  - `sudo` whose `argv[0]` is not `-v` or `-n`;
  - any `apt-get`, `dnf`, `xcode-select` or `systemsetup` call;
  - `ollama pull`;
  - `docker start` or `docker compose`;
  - `ufw allow`;
  - `firewall-cmd --permanent --add-rich-rule=...` or `firewall-cmd --reload`;
  - `loginctl enable-linger`;
  - `timedatectl set-ntp`;
  - `socketfilterfw --add` or `--unblockapp`;
  - `python3 -m pip`.

  The test also asserts that `<tmp>/home/.local/share/qwen-agent/searxng` does not exist.
- Default args: Linux `--model-server-type ollama --model qwen3.5:9b`; macOS `--model-server-type vllm --model qwen38-6bit` with `model_name = "qwen38-6bit"`.
- "Linux all-fail" state:
  - `py_ok=false`, `pytest_ok=false`, with `git` absent;
  - `clock_linux="no"`;
  - `model="missing"`;
  - `searxng="down"` with `containers=[]`;
  - `ufw_out=UFW_NONE`;
  - `linger="no"`.

### 6.3 Test table

| ID | Covers | Procedure and pass condition |
|---|---|---|
| H1 | P8-P12, P17 | Check mode, Linux all-fail. Exit 1. `mutating(calls) == []`; no `docker` or `ollama` call; stable dir absent. The status lines are: `platform` PASS and six FAIL, in P13-P16 order. Each FAIL line is followed directly by a `  fix: ` line. The last line is `summary: 1 pass, 0 fixed, 6 fail, 0 unknown, 0 skip`. |
| H2 | P10-P16 | (a) Linux all-pass: exactly 7 status lines, all PASS, in the order platform, packages, clock, model, searxng, firewall, linger; `PASS platform: linux/apt`; summary `7 pass, 0 fixed, 0 fail, 0 unknown, 0 skip`; exit 0. (b) macOS all-pass (`containers=["qwen-agent-searxng"]`): 6 PASS and `SKIP linger: not applicable on macOS`; `PASS platform: macOS 26.5.2`; `PASS firewall: application firewall off`; exit 0. |
| H3 | P9, P12, P13-P16 | `--apply`, Linux all-fail. Exactly one `sudo -v` call. It comes after `id -u` and before the first `uname` call. `plus_lines` equals, in order (with `<H>` the tmp HOME and `SX=<H>/.local/share/qwen-agent/searxng`): `+ sudo apt-get update`; `+ sudo apt-get install -y python3 git python3-pytest`; `+ sudo timedatectl set-ntp true`; `+ ollama pull qwen3.5:9b`; `+ mkdir -p <SX>`; `+ cp <WS>/searxng/docker-compose.yml <WS>/searxng/settings.yml <SX>/`; `+ docker compose -p qwen-agent-searxng -f <SX>/docker-compose.yml up -d`; `+ sudo ufw allow from 192.168.1.0/24 to any port 8190`; `+ sudo loginctl enable-linger tester`. Status lines: platform PASS, the other six FIXED. Exit 0. The copied files are byte-identical to the repo's. `pulling manifest` appears between `+ ollama pull` and `FIXED model`. |
| H4 | P12 | (a) `fix.linger="noop"`: `FAIL linger: Linger=no for tester (fix did not take)` plus a fix line; exit 1. (b) `fix.packages="exit:100"`: `FAIL packages: missing: python3 >= 3.9, git, pytest (fix exited 100)`, and the later fixes (`timedatectl set-ntp`, ... `loginctl enable-linger`) still run. (c) `fix.apt_update="exit:100"`: `+ sudo apt-get update` is printed, no `apt-get install` call is made, and the line ends `(fix exited 100)`. |
| H5 | P12 | `--apply` on Linux all-pass and on macOS all-pass: exit 0, `plus_lines == []`, `mutating == []`, exactly one `sudo -v`. |
| H6 | P5-P7 | Each exits 2 with stderr starting `fleet-host-prep.sh: ` and makes no `sudo` or `uname` call: `uid=0` with valid args (message contains `refusing to run as root`); missing `--model`; missing `--model-server-type`; `--model-server-type llama`; `--bogus`; `--model` as the last arg; `--model --apply`; `--model=qwen3.5:9b`; `--lan-cidr` set to `192.168.1.0/33`, `300.1.1.0/24`, `192.168.1.5/24` or `192.168.1.0`; `--port` set to `1023`, `65536`, `0`, `abc`, `08191` or `8190.0`; `--port` as the last arg; `--no-searxng --searxng-url http://127.0.0.1:8888/` and the reverse order (message contains `cannot be used together`); `--no-searxng=1`. `-h` and `--help`: exit 0, stdout starts `Usage: fleet-host-prep.sh`, and `calls()` is empty. `--lan-cidr 10.0.0.0/8` is accepted (all-pass with `ufw_out` carrying a `10.0.0.0/8` row, exit 0). `--port 1024` and `--port 65535` are accepted (all-pass with `ufw_out` carrying a row for that port, exit 0). |
| H7 | P13a | `--apply`, Linux, `absent` includes `apt-get` and `dnf`, `git` absent, `linger="no"`: `PASS platform: linux (no apt-get/dnf: ...)`; `FAIL packages: missing: git` with `  fix: install python3 (>= 3.9), git and pytest with this host's package manager, then re-run`; `FIXED linger`; exit 1. |
| H8 | P9, P15 | Check mode, `sudo_n_ok=false`, ufw present: `UNKNOWN firewall: cannot read ufw rules without sudo` and `  fix: run 'sudo -v' first, or use --apply`; summary `6 pass, 0 fixed, 0 fail, 1 unknown, 0 skip`; exit 1. Same with `--apply`: the fix line is `  fix: 'sudo -n' failed even after 'sudo -v'; run 'sudo ufw status' by hand` and there is no `ufw allow` call. |
| H9 | P14 | `--apply`, `searxng="down"`. (a) `groups="tester docker"`, no container: the `docker ps` and `docker compose` calls are direct (no sudo); the compose fake's file check passes (proves the copy happened first); FIXED. (b) `groups="tester"`: the calls include `sudo -n docker ps -a --format {{.Names}}`, and the `+` line is `+ sudo docker compose -p ...`; FIXED. (c) `containers=["qwen-agent-searxng"]`: `+ docker start qwen-agent-searxng`, no compose call, stable dir absent; FIXED. (d) `docker` absent: `FAIL searxng: no answer at http://127.0.0.1:8888/ (curl exit 7); Docker not installed (this script never installs Docker)`, no docker call. (e) `lag.searxng=5`: FIXED, and exactly 5 `sleep 1` calls. (f) `fix.searxng="noop"`: FAIL `... (fix did not take)`, 1 + 30 searxng curl calls, 29 `sleep 1` calls. (g) `docker_ps_exit=1`: FAIL containing `'docker ps -a' failed (exit 1)`. |
| H10 | P14 | macOS args (vllm), `model="missing"`, `--apply`: `FAIL model: 'qwen38-6bit' not served by vllm at http://127.0.0.1:8177/v1/models (serving: other-model:1b)` and `  fix: start vllm-metal serving 'qwen38-6bit' at http://127.0.0.1:8177/v1 by hand; this script never starts, restarts or pulls for vLLM`; no `ollama` call and no `docker` call; exit 1. |
| H11 | P13 | macOS clock, check mode, `sntp_out` first token: `+0.01` PASS, `-0.25` PASS, `+4.999` PASS, `4` PASS, `12.3` FAIL `(limit 5 s)`, `-7.5` FAIL, `5.0` FAIL, `garbage` FAIL `unparseable sntp output 'garbage ...'`; `sntp_exit=1` gives `FAIL clock: sntp failed (exit 1)`; `sntp` absent gives `FAIL clock: sntp not found`. With `--apply`, `sntp_out` set to `12.3 +/- 0.01 time.apple.com 1.2.3.4`: `+ sudo systemsetup -setusingnetworktime on`, then `FIXED clock: offset +0.001000 s from time.apple.com`. |
| H12 | P1, P2 | `/bin/bash -n SCRIPT` exits 0. The script's first line is `#!/usr/bin/env bash`, and `os.stat(SCRIPT).st_mode & 0o777 == 0o755`. A scan of the script, with comment lines (first non-blank character `#`) removed, matches none of `FORBIDDEN` (Section 6.4) under `re.search(..., re.M)`. The script contains `set -u` and `set -o pipefail`. |
| H13 | P14 | `--searxng-url http://127.0.0.1:9999/`, `searxng="down"`, `--apply`: FAIL searxng whose fix line contains `QWEN_AGENT_SEARXNG_URL` and `no_proxy`; no `docker` call. |
| H14 | P12 | In H3's run, every `curl` call's argv starts `-sS --noproxy * --max-time 5`. |
| H15 | P8, P14 | (a) Linux all-pass: the model curl URL is `http://127.0.0.1:11434/api/tags`. macOS: `http://127.0.0.1:8177/v1/models`. `--model-url http://127.0.0.1:11434` (no `/v1`) still gives `.../api/tags`. (b) The script text contains `fleet_lib.probe_url` and `fleet_lib.parse_loaded_models`, and does not contain `api/tags` or `/models`. (c) `model="down"`, `--apply`: `FAIL model: ollama not reachable at http://127.0.0.1:11434/api/tags (curl exit 7)`, no `ollama` call. (d) `ollama` absent, `model="missing"`, `--apply`: FAIL with the not-on-PATH fix line. (e) `--model-url http://127.0.0.1:11500/v1`, `model="missing"`, `--apply`: FAIL with the `by hand` line, no `ollama` call. (f) `fix.model="exit:1"`: `(fix exited 1)`. (g) `python3` absent: `FAIL model: python3 cannot load fleet_lib from <WS>`. |
| H16 | P15 | ufw parsing, check mode, `ufw_out` = the header plus these rows (as `"%-26s %-12s%-26s"`, with an optional ` # fleet` comment). PASS: `8190 ALLOW 192.168.1.0/24`; `8190/tcp` + `8190/udp` rows; `8190 ALLOW Anywhere`; `8190 ALLOW 192.168.1.0/24 # fleet`. FAIL with the missing protocols shown: only `8190/tcp` (`udp`); only `8190 (v6) ALLOW Anywhere (v6)` (`tcp, udp`); `8190 DENY 192.168.1.0/24`; `8190 ALLOW OUT 192.168.1.0/24`; `8190 ALLOW 10.0.0.0/8`; `8190 on eth0 ALLOW 192.168.1.0/24`. `Status: inactive` gives `PASS firewall: ufw inactive`. `ufw` absent and firewalld not running gives `PASS firewall: no host firewall active`. `ufw_out="weird"` gives `FAIL firewall: unrecognized 'ufw status' output 'weird'`. Non-default port, `--port 8191`: the default `UFW_OK` (an `8190` row only) gives `FAIL firewall: ufw active; no rule allows 8191 tcp, udp from 192.168.1.0/24` with `  fix: sudo ufw allow from 192.168.1.0/24 to any port 8191`; a `8191 ALLOW 192.168.1.0/24` row gives `PASS firewall: ufw allows 8191 tcp+udp from 192.168.1.0/24`; `8191/tcp` + `8190/udp` rows give FAIL (`udp`). With `--apply` and `UFW_OK`: `+ sudo ufw allow from 192.168.1.0/24 to any port 8191`, then FIXED. |
| H17 | P15 | `absent += {"ufw"}`, `firewalld="running"`. (a) No rules, `--apply`: `plus_lines` are the tcp `--add-rich-rule='...'` line (exact text in P10's example), the matching udp line, then `+ sudo firewall-cmd --reload`; `FIXED firewall: firewalld allows 8190 tcp+udp from 192.168.1.0/24`. (b) The tcp rule present: only the udp add and the reload. (c) `sudo_n_ok=false`, check mode: UNKNOWN. (d) `--port 8191 --apply` with both 8190 rich rules present: the plus lines are the tcp and udp `--add-rich-rule` lines with `port="8191"`, then the reload, then `FIXED firewall: firewalld allows 8191 tcp+udp from 192.168.1.0/24`; the 8190 rules are untouched. |
| H18 | P15 | ufw `UFW_OK` and `firewalld="running"`, `--apply`: `FAIL firewall: ufw and firewalld are both active`, with no `ufw allow` and no `firewall-cmd --add-rich-rule` call. With `--port 8191`, the fix line contains `to any port 8191` and does not contain `8190`. |
| H19 | P15, P18 | macOS, `sfw_global="Firewall is enabled. (State = 1)"`. (a) `sfw_apps=[[python_exe,"allow"]]`: `PASS firewall: application firewall on; <python_exe> allowed`. (b) `sfw_apps=[]`, `--apply`: `+ sudo <tmp>/sfw/socketfilterfw --add <python_exe>`, then `+ sudo <tmp>/sfw/socketfilterfw --unblockapp <python_exe>`, then FIXED. (c) `[[python_exe,"block"]]`, `--apply`: only the `--unblockapp` line, then FIXED. (d) `sfw_apps=[["/usr/bin/python3","allow"]]`: FAIL (a different path does not count). (e) `sfw_blockall="Firewall has block all state set to enabled."`, `--apply`: FAIL block all, with no `--add` call. (f) `sfw_global="gibberish"`: FAIL unrecognized. (g) Every socketfilterfw call is logged under the fake, which proves the env seam is used. (h) (a) and (b) repeated with `--port 8191` print the same lines, with no port in them. |
| H20 | P13 | Linux clock, `--apply`, `clock_linux="no"`. (a) `lag.clock=3`: FIXED, exactly 3 `sleep 2` calls. (b) `fix.clock="noop"`: `FAIL clock: NTPSynchronized=no (fix did not take)`, 16 `timedatectl show` calls in total, 14 `sleep 2` calls. (c) `timedatectl` absent: FAIL `timedatectl not found`, no `set-ntp` call. |
| H21 | P13 | `os="FreeBSD"`: stdout is exactly `FAIL platform: unsupported OS 'FreeBSD'`, the fix line, and `summary: 0 pass, 0 fixed, 1 fail, 0 unknown, 0 skip`; exit 1; `calls()` holds only `id -u` and `uname -s`. |
| H22 | P9 | `--apply`, `sudo_v_exit=1`: stdout is exactly P9's three lines with `exit 1`; exit 1; `calls()` holds only `id -u` and `sudo -v`. |
| H23 | P17 | The script text contains none of `fleet.env`, `QWEN_AGENT_FLEET` or `.config/qwen-agent`. Its only `${NAME...}` or `$NAME` reads of variables that are not set by the script are `HOME`, `PATH`, `FLEET_PREP_SOCKETFILTERFW`, `BASH_SOURCE` and `BASH_REMATCH` (checked by review; there is no automated test of variable provenance). |
| H24 | P10 | In H1 and H3, every stdout line except the fakes' own fix output (`pulling manifest`, excluded by exact text) fully matches one regex in `LINE_FORMS` (Section 6.4). |
| H26 | P6, P14 | `--no-searxng`. (a) Linux all-pass, check mode, `searxng="down"`: `SKIP searxng: disabled by --no-searxng`; summary `6 pass, 0 fixed, 0 fail, 0 unknown, 1 skip`; exit 0; no `curl` call whose argv contains `-o` (the SearXNG form); no `docker` call. (b) The same with `--apply`, `containers=[]`: the same SKIP line, `plus_lines == []`, no SearXNG curl, no docker call, stable dir absent, exit 0. (c) macOS all-pass (vllm args) with `--no-searxng`: `5 pass, 0 fixed, 0 fail, 0 unknown, 2 skip`, exit 0. |
| H25 | P13a | macOS, `pytest_ok=false`, `--apply`: `+ python3 -m pip install --user pytest`, then `FIXED packages`. macOS, `py_ok=false`, `--apply`: FAIL with the `xcode-select --install` fix line, and no `xcode-select` call. |

### 6.4 Regex lists (Python literals, copied verbatim into the test file)

```python
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
```

`LINE_FORMS` entries are applied with `re.fullmatch`.

Every requirement has a test, except P17's variable-provenance clause (review only, as H23 says). The following are live-only: real `sudo` prompting (P9); real `ufw` and `firewall-cmd` behavior after a fix; real Docker bind mounts surviving a reboot (P14); and the real Python.app firewall identity (P15). They are covered by Section 7.

---

## 7. Live acceptance (human-run, after implementation and review)

| Step | Host | Command | Pass |
|---|---|---|---|
| L1 | Mac | `bash ~/local_agent_harness/qwen-agent-workspace/scripts/fleet-host-prep.sh --model-server-type vllm --model qwen38-6bit` | exit 0, or each `FAIL` line names a real gap (S1) |
| L2 | .168, interactive ssh, after `git clone --depth 1 --branch qwen-agent-redteam ... /tmp/qa-prep` | `bash /tmp/qa-prep/qwen-agent-workspace/scripts/fleet-host-prep.sh --model-server-type ollama --model qwen3.5:9b` | `FAIL searxng`, `UNKNOWN firewall`, other checks PASS, exit 1 (S2) |
| L3 | .168, run by the user | the same with `--apply` | exit 0 (S3); `curl -s 'http://127.0.0.1:8888/search?q=test&format=json'` returns JSON; `sudo ufw status` shows `8190 ALLOW 192.168.1.0/24` |
| L4 | .168 | the same `--apply` again | no `+ ` line, exit 0 (S4); then `rm -rf /tmp/qa-prep` |
| L6 | vision-185 (macOS, 192.168.1.185) | `bash ~/local_agent_harness/qwen-agent-workspace/scripts/fleet-host-prep.sh --model-server-type vllm --model DreamFast/Qwen3-VL-4b-Heretic --no-searxng`. The model server is mlx_vlm 0.7.2 on `:8177`, with an OpenAI-compatible `/v1/models`. | `SKIP searxng: disabled by --no-searxng`, `SKIP linger`, `PASS model: 'DreamFast/Qwen3-VL-4b-Heretic' served by vllm at http://127.0.0.1:8177/v1/models`; exit 0, or with `--apply` added for any other FAIL (see R7) |
| L5 | all hosts | `python3 -m pytest tests/ -q -rA` from `WS` (the [FLEET] T70 procedure) | S5 |

The script must be committed and pushed on `qwen-agent-redteam` before L2.

## 8. Implementation notes for the executor (binding)

- Order of top-level steps:
  1. constants (P8, P18)
  2. functions
  3. argument parsing (P5)
  4. validation (P6)
  5. root check (P7)
  6. `sudo -v` (P9)
  7. the checks: platform, packages, clock, model, searxng, firewall, linger
  8. summary
  9. exit
- The counters (`N_PASS`, `N_FIXED`, `N_FAIL`, `N_UNKNOWN`, `N_SKIP`) are plain integer variables updated by the status-printing helper.
- Each check is one shell function that sets the globals `CK_RESULT` (`pass`, `fail`, `unknown` or `skip`), `CK_DETAIL` and `CK_FIXLINE`, plus a fix function or the empty string. `run_check` drives them as in P12.

## 9. Values chosen by the spec

1. P2: no arrays at all, to avoid the bash < 4.4 empty-array `set -u` failure.
2. P3: `export LC_ALL=C`, so tool output is English.
3. P4: messages name the script literally `fleet-host-prep.sh`.
4. P5: a value flag followed by an argument starting with `--` counts as missing its value.
5. P5: `--flag=value` is rejected as an unknown argument.
6. P6: the `--lan-cidr` regex, octet and length bounds, and the zero-host-bits rule.
7. P7: usage errors are reported before the root check.
8. P8: the fleet_lib probes run with `-I -B`, and `PY_HAS_MODEL` exits 3 for "absent".
9. P10: the `+` and `fix:` quoting rule (`--name='value with spaces'`).
10. P10: the summary format; it is printed after P9's sudo failure and after an unsupported platform.
11. P12: the clock poll (15 re-checks, 2 s apart) and the SearXNG poll (30 probes, 1 s apart), both counted in iterations.
12. P13: the macOS clock comparison uses the integer part, in pure bash, capped at 9 digits.
13. P13a: `packages` is one check line; git is checked with `git --version`.
14. P14: no `ollama pull` when the server is down or `--model-url` is not the default.
15. P14: container names are read with `docker ps -a --format '{{.Names}}'` and an exact line match.
16. P15: macOS reads `--listapps`, not `--getappblocked`; `EXE` is the running image (`ps -o comm=`).
17. P15: macOS block-all is a manual FAIL; `--add` runs only when the app is not listed.
18. P15: ufw and firewalld both active is a manual FAIL.
19. P15: a ufw `Anywhere` allow counts as covering the LAN.
20. P15: firewalld adds only the missing rich rules, then reloads.
21. Section 6: the dispatcher, state-file and fix-group harness; exit 99 for unexpected argv.
22. P6: `--no-searxng` with `--searxng-url` is checked fourth (after `--model`), and `--port` sixth (after `--lan-cidr`).
23. P6: `--port` rejects leading zeros (`^[1-9][0-9]{3,4}$`, then 1024-65535).
24. P15: the macOS firewall messages do not mention the port, because the macOS rule is per binary.

## 10. Contradictions and risks

- **C1. The brief's firewall path resolution is wrong for framework Pythons (resolved).** `os.path.realpath(sys.executable)` gives `.../bin/python3.13`, but the process that opens sockets is `.../Resources/Python.app/Contents/MacOS/Python` (verified on this Mac for python.org 3.13 and CLT 3.9). P15 uses `PY_EXE` (the running image). The firewall is off on the Mac today, so this matters only if it is turned on. Resolution: the coordinator approved keeping the `--listapps` parse and the running-image path (`PY_EXE`) as specified. Whether macOS keys the allow rule to that inner binary or to the bundle is **unverified**. Neither the Mac nor any live step can verify it while the Mac's application firewall is off. It must be checked the first time a fleet host runs with the firewall on.
- **R1. sudo needs a TTY.** `ssh host 'bash fleet-host-prep.sh ... --apply'` without `-t` fails at `sudo -v` (exit 1, nothing changed). R0 says to use an interactive session.
- **R2. First SearXNG start on .168 pulls the digest-pinned image** from Docker Hub inside `compose up`, which has no timeout. After `up`, SearXNG must answer within 30 s, or the check reports `fix did not take`. A re-run then passes without changes, since the container is up.
- **R3. `pip install --user` fails on an externally managed Python** (Homebrew, PEP 668). The script reports `(fix exited N)`. The Mac's python.org build is not affected.
- **R4. `ufw` must be on PATH.** On a host whose PATH lacks `/usr/sbin`, an active ufw would be missed and the check would report `no host firewall active`. The default PATHs on Ubuntu and Fedora include `/usr/sbin`. The script does not add it (that would break test isolation).
- **R5. `systemsetup -setusingnetworktime`** may require Full Disk Access for the terminal on recent macOS. If so, the fix exits nonzero and the user turns the setting on in System Settings.
- **R6. `--port` covers the firewall only.** It does not change the fleet daemon itself. [FLEET] F30's default beacon target is `255.255.255.255:8190`. Whether a daemon on another port sends or receives beacons on its own port is for the follow-up multi-agent spec to decide. A host whose firewall admits only `--port 8191` may still need 8190/udp for beacons.
- **R7. mlx_vlm lists cached models, not just the loaded one.** mlx_vlm's `/v1/models` (vision-185) lists every cached model with a `loaded` flag. `fleet_lib.parse_loaded_models("vllm", ...)` collects every `id` and ignores `loaded`, so the model check passes for a cached model that is not loaded. [FLEET] F14's skill verification has the same behavior. This is accepted for host prep: the model is on disk, and the first request loads it.
