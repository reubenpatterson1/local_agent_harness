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
run_check packages
run_check clock
run_check model
run_check searxng
run_check firewall
run_check linger

# ---------------------------------------------------------------------------
# Summary (P10) and exit status (P11)
# ---------------------------------------------------------------------------

print_summary
if [ $((N_FAIL + N_UNKNOWN)) -gt 0 ]; then
    exit 1
fi
exit 0
