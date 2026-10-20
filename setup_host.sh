#!/bin/bash
#
# setup_host.sh — provision this Apple Silicon host for the local_agent_harness
# red-team range + an mlx-vlm model server.
#
# RUN AS YOUR NORMAL USER (NOT sudo):   bash ~/local_agent_harness/setup_host.sh
# It will ask for your password once and cache it for the sudo-only steps.
#
set -uo pipefail

MODEL="mlx-community/Qwen3-VL-30B-A3B-Instruct-8bit"
VENV="$HOME/mlx-serve"
REPO="$HOME/local_agent_harness"
SERVE_LOG="$HOME/mlx-serve.log"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\n\033[1;33m[warn] %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31m[error] %s\033[0m\n' "$*" >&2; exit 1; }

# --- guard: must NOT be root (Homebrew refuses) --------------------------------
[ "$(id -u)" -eq 0 ] && die "Do not run with sudo. Run as your normal user: bash $0"

# --- cache sudo credentials up front, keep alive ------------------------------
say "Caching sudo credentials (enter your login password)…"
sudo -v || die "sudo authentication failed."
# keep-alive: refresh sudo timestamp until this script exits
( while true; do sudo -n true; sleep 50; kill -0 "$$" 2>/dev/null || exit; done ) 2>/dev/null &
SUDO_KEEPALIVE=$!
trap 'kill "$SUDO_KEEPALIVE" 2>/dev/null' EXIT

# --- 1. Xcode Command Line Tools (non-interactive via softwareupdate) ---------
if xcode-select -p >/dev/null 2>&1; then
  say "Command Line Tools already installed."
else
  say "Installing Command Line Tools (headless)…"
  TMP=/tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
  sudo touch "$TMP"
  PROD=$(softwareupdate -l 2>/dev/null \
          | awk '/Label: Command Line Tools/{sub(/^.*Label: /,""); print}' \
          | sort -V | tail -n1)
  if [ -n "$PROD" ]; then
    sudo softwareupdate -i "$PROD" --verbose || warn "softwareupdate CLT install returned non-zero."
  else
    warn "Could not find a CLT label via softwareupdate; falling back to the GUI installer."
    xcode-select --install || true
    echo "If a dialog appeared, click Install and wait for it to finish, then re-run this script."
  fi
  sudo rm -f "$TMP"
  xcode-select -p >/dev/null 2>&1 || die "CLT still not present. Complete the install and re-run."
fi
say "git: $(git --version 2>&1)"

# --- 2. Homebrew --------------------------------------------------------------
if ! command -v brew >/dev/null 2>&1 && [ -x /opt/homebrew/bin/brew ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi
if ! command -v brew >/dev/null 2>&1; then
  say "Installing Homebrew…"
  NONINTERACTIVE=1 /bin/bash -c \
    "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
    || die "Homebrew install failed."
  if ! grep -q 'brew shellenv' "$HOME/.zprofile" 2>/dev/null; then
    echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> "$HOME/.zprofile"
  fi
  eval "$(/opt/homebrew/bin/brew shellenv)"
else
  say "Homebrew present: $(brew --version | head -1)"
fi

# --- 3. Docker Desktop --------------------------------------------------------
if [ -d "/Applications/Docker.app" ]; then
  say "Docker Desktop already installed."
else
  say "Installing Docker Desktop…"
  brew install --cask docker-desktop 2>/dev/null \
    || brew install --cask docker \
    || die "Docker Desktop cask install failed."
fi

say "Launching Docker Desktop and waiting for the daemon…"
open -a Docker || warn "Could not auto-launch Docker; open it from Applications."
for i in $(seq 1 60); do
  if docker info >/dev/null 2>&1; then break; fi
  sleep 3
done
docker info >/dev/null 2>&1 || warn "Docker daemon not ready yet. Finish Docker's first-run setup, then re-run the range-build step at the bottom."

# --- 4. Python 3.12 + mlx-vlm venv -------------------------------------------
if ! brew list python@3.12 >/dev/null 2>&1; then
  say "Installing python@3.12…"
  brew install python@3.12 || die "python@3.12 install failed."
fi
PY=$(brew --prefix)/opt/python@3.12/bin/python3.12
[ -x "$PY" ] || PY=python3.12

say "Creating mlx-vlm venv at $VENV …"
"$PY" -m venv "$VENV" || die "venv creation failed."
"$VENV/bin/pip" install -U pip >/dev/null
say "Installing mlx-vlm (this pulls mlx + huggingface_hub)…"
"$VENV/bin/pip" install -U mlx-vlm || die "mlx-vlm install failed."

# --- 5. Build + start the Docker range ---------------------------------------
if docker info >/dev/null 2>&1; then
  say "Building and starting the range…"
  ( cd "$REPO" && docker compose build && docker compose up -d && docker compose ps ) \
    || warn "Range build/up failed — check Docker and re-run: cd $REPO && docker compose build && docker compose up -d"
else
  warn "Skipping range build because Docker daemon isn't ready."
fi

# --- 6. Compose the tuned serve command (probe flags that vary by version) ----
say "Determining mlx-vlm server flags for 128K context + 8-bit KV cache…"
HELP="$("$VENV/bin/python" -m mlx_vlm.server --help 2>&1 || true)"
SERVE_ARGS=(--model "$MODEL" --host 0.0.0.0 --port 11434 --max-tokens 4096)
grep -q -- '--kv-bits'     <<<"$HELP" && SERVE_ARGS+=(--kv-bits 8)
grep -q -- '--max-kv-size' <<<"$HELP" && SERVE_ARGS+=(--max-kv-size 131072)

cat <<EOF

============================================================
 Setup complete (or as far as Docker allowed).

 START THE MODEL SERVER in its own Terminal tab (first run
 downloads ~32 GB and it must keep running):

   $VENV/bin/python -m mlx_vlm.server ${SERVE_ARGS[*]}

 Or run it in the background, logging to $SERVE_LOG:

   nohup $VENV/bin/python -m mlx_vlm.server ${SERVE_ARGS[*]} > "$SERVE_LOG" 2>&1 &

 Then verify:
   curl -s http://127.0.0.1:11434/v1/models

 Range status:
   cd $REPO && docker compose ps
============================================================
EOF
