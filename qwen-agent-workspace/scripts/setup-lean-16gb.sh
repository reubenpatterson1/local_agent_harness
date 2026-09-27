#!/bin/bash
# Sets up the story->image->video pipeline in seed-image mode on a 16GB M1
# Pro/Max MacBook Pro, using the leanest model combination validated on real
# 16GB hardware (see docs/16gb-m1-port.md and
# docs/superpowers/plans/2026-09-26-16gb-m1-port.md, Tasks 1-3).
#
# This is a single hand-set-up machine, not a repeatable deploy target: it
# does not use scripts/deploy/build_pkg.py / install_pkg.py, and it makes no
# changes to pipeline code (bin/ltx-movie, ltx2_mlx_video_skill.py,
# bin/story-server all already support every flag/env var this needs).
#
# Usage: bash scripts/setup-lean-16gb.sh
#
# What this does NOT do: pick --min-avail-gib for you, or decide whether
# `iogpu.wired_limit_mb` needs raising. Neither was captured during the real
# hardware validation run that found the model combination below (an
# accepted, explicitly flagged risk -- see docs/16gb-m1-port.md). This
# script prints the exact calibration recipe instead of guessing.

set -euo pipefail

WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WS"

# ---------------------------------------------------------------------------
# 1. Confirm ltx-2-mlx is installed
# ---------------------------------------------------------------------------

echo "=== 1. ltx-2-mlx ==="
if command -v ltx-2-mlx >/dev/null 2>&1; then
    echo "Found on PATH: $(command -v ltx-2-mlx)"
else
    echo "Not found on PATH. Installing to \$HOME/ltx-2-mlx-tool ..."
    if ! command -v uv >/dev/null 2>&1; then
        echo "Error: uv is not installed. Install it first:" >&2
        echo "  https://docs.astral.sh/uv/getting-started/installation/" >&2
        exit 1
    fi
    git clone https://github.com/dgrauet/ltx-2-mlx.git "$HOME/ltx-2-mlx-tool"
    (cd "$HOME/ltx-2-mlx-tool" && uv sync --all-extras)
fi
ltx-2-mlx --help >/dev/null
echo "ltx-2-mlx OK"

if ! command -v hf >/dev/null 2>&1; then
    echo "Error: the 'hf' CLI (huggingface_hub) is not installed or not on PATH." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 2. Download the three model packs (plain `hf download`, never --local-dir --
#    a flat, non-standard cache layout from --local-dir broke model
#    resolution during this port's own development and had to be manually
#    repaired; letting huggingface_hub manage its own cache avoids that).
# ---------------------------------------------------------------------------

export HF_HOME="${HF_HOME:-$HOME/hf_cache}"
mkdir -p "$HF_HOME"
echo "=== 2. Downloading models into HF_HOME=$HF_HOME ==="

echo "--- video DiT: dgrauet/ltx-2.3-mlx-q4 (distilled transformer only, ~19.6GB) ---"
hf download dgrauet/ltx-2.3-mlx-q4 \
    --include "connector.safetensors" \
    --include "transformer-distilled.safetensors" \
    --include "audio_vae.safetensors" \
    --include "vae_decoder.safetensors" \
    --include "vae_encoder.safetensors" \
    --include "vocoder.safetensors" \
    --include "config.json" \
    --include "embedded_config.json" \
    --include "quantize_config.json" \
    --include "split_model.json"

echo "--- text encoder: mlx-community/gemma-3-12b-it-qat-abliterated-lm-4bit (~6.85GB) ---"
echo "    (NOT the ltx-2-mlx default gemma-3-12b-it-4bit -- that OOM's on 16GB; this QAT"
echo "     variant is the one confirmed stable on real 16GB hardware.)"
hf download mlx-community/gemma-3-12b-it-qat-abliterated-lm-4bit

echo "--- vision LLM: alexgusevski/Huihui-Qwen3-VL-4B-Instruct-abliterated-q4-mlx (~3.1GB) ---"
VISION_MODEL_DIR="$(hf download alexgusevski/Huihui-Qwen3-VL-4B-Instruct-abliterated-q4-mlx)"

echo "All downloads complete (~29GB total)."

# ---------------------------------------------------------------------------
# 3. GPU wired-memory cap: report only. Whether this needs raising on this
#    specific 16GB target was never confirmed during validation (accepted
#    risk, docs/16gb-m1-port.md) -- the confirmed-stable run may or may not
#    have needed it. This script will not change a memory-safety sysctl for
#    you without that confirmation.
# ---------------------------------------------------------------------------

echo "=== 3. GPU wired-memory cap ==="
CURRENT_CAP="$(sysctl -n iogpu.wired_limit_mb 2>/dev/null || echo "0 (default, no cap set)")"
echo "Current iogpu.wired_limit_mb: $CURRENT_CAP"
echo "If a real run OOMs during the text-encoding stage (Gemma + connector loading,"
echo "before any video frames render), try raising it, e.g.:"
echo "  sudo sysctl iogpu.wired_limit_mb=14336   # 14GB, leaves ~2GB for macOS"
echo "Check after a reboot whether it reverted -- if so this needs a LaunchDaemon or"
echo "/etc/sysctl.conf entry to persist, which this script does not set up for you."

# ---------------------------------------------------------------------------
# 4. --min-avail-gib calibration. NEVER invented -- bin/ltx-movie's default
#    (25.0) will never pass its precondition check on a 16GB machine, and no
#    safe real value was captured during this port's validation run.
# ---------------------------------------------------------------------------

echo "=== 4. --min-avail-gib calibration (required, not automated) ==="
if [ -z "${MIN_AVAIL_GIB:-}" ]; then
    cat <<'EOF'
MIN_AVAIL_GIB is not set. This value was never measured on this machine and
must not be guessed -- bin/ltx-movie's own docs and this port's plan both say
so explicitly. To find it:

  1. Start a memory sampler in the background:
       ( while true; do date +%s; sysctl vm.swapusage; sleep 1; done \
         > ~/16gb-port-memlog.txt 2>&1 & echo $! > ~/16gb-port-memlog.pid )

  2. Run one real single-panel render with a near-zero probe value, so the
     precondition check itself doesn't block you from observing real usage:
       cd qwen-agent-workspace
       python3 bin/ltx-movie "A lighthouse on a rocky cliff at sunset" \
         --panels 1 --no-stills --story-id calibration-test \
         --model dgrauet/ltx-2.3-mlx-q4 \
         --gemma mlx-community/gemma-3-12b-it-qat-abliterated-lm-4bit \
         -W 640 -H 384 --frames 169 --frame-rate 24 \
         --min-avail-gib 0.1 --no-review

  3. Stop the sampler: kill "$(cat ~/16gb-port-memlog.pid)"

  4. Read ~/16gb-port-memlog.txt for the peak `used` swap value, and choose a
     --min-avail-gib with real headroom above it.

Then rerun this script with, e.g.: MIN_AVAIL_GIB=6.0 bash scripts/setup-lean-16gb.sh
EOF
    FINAL_COMMAND_READY=false
else
    echo "Using MIN_AVAIL_GIB=$MIN_AVAIL_GIB"
    FINAL_COMMAND_READY=true
fi

# ---------------------------------------------------------------------------
# 5. Print the exact command to run the pipeline
# ---------------------------------------------------------------------------

echo "=== 5. Pipeline command ==="
echo "Vision server (start before the render, stop when done):"
echo "  export STORY_SERVER_VISION_MODEL_DIR=\"$VISION_MODEL_DIR\""
echo "  export STORY_SERVER_VISION_GPU_MEM_UTIL=0.50"
echo "  bin/story-server vision"
echo
if [ "$FINAL_COMMAND_READY" = true ]; then
    echo "Render (from qwen-agent-workspace/):"
    echo "  python3 bin/ltx-movie \"<your narrative>\" \\"
    echo "    --story-id <your-story-id> --seed-image <path-to-a-real-photo> \\"
    echo "    --model dgrauet/ltx-2.3-mlx-q4 \\"
    echo "    --gemma mlx-community/gemma-3-12b-it-qat-abliterated-lm-4bit \\"
    echo "    -W 640 -H 384 --frames 169 --frame-rate 24 \\"
    echo "    --min-avail-gib $MIN_AVAIL_GIB"
else
    echo "Run step 4's calibration first, then rerun this script with MIN_AVAIL_GIB set"
    echo "to print the exact render command with a real, measured value filled in."
fi
