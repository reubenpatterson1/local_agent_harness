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
