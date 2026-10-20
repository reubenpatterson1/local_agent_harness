#!/bin/bash
#
# setup_image_skills.sh — provision the PyTorch/diffusers image-generation
# stack for the qwen-agent-workspace skills (z_image_skill.py, flux_skill.py)
# on this Apple Silicon host, at full bf16 (highest quality; no quantization).
#
# Prereq: setup_host.sh already ran (Homebrew + python@3.12 present).
# RUN AS YOUR NORMAL USER:  bash ~/local_agent_harness/qwen-agent-workspace/setup_image_skills.sh
#
set -uo pipefail

VENV="$HOME/img-gen"
WORKSPACE="$HOME/local_agent_harness/qwen-agent-workspace"
HF_HUB="$HOME/hf_home/hub"          # z_image_skill's default fast-cache (Z_IMAGE_HF_HOME=~/hf_home)

Z_BASE="Tongyi-MAI/Z-Image-Turbo"
Z_TEXT_ENCODER="BennyDaBall/Qwen3-4b-Z-Image-Turbo-AbliteratedV1"
# Flux is the A/B alternative skill; prefetched too (same venv). Comment out to skip.
FLUX_MODEL="SicariusSicariiStuff/flux.1dev-abliteratedv2"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\n\033[1;33m[warn] %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31m[error] %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] && die "Do not run with sudo. Run as your normal user."

# --- Homebrew python ----------------------------------------------------------
if ! command -v brew >/dev/null 2>&1 && [ -x /opt/homebrew/bin/brew ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi
command -v brew >/dev/null 2>&1 || die "Homebrew not found. Run setup_host.sh first."
PY="$(brew --prefix)/opt/python@3.12/bin/python3.12"
[ -x "$PY" ] || PY=python3.12

# --- venv + deps --------------------------------------------------------------
say "Creating image-gen venv at $VENV …"
"$PY" -m venv "$VENV" || die "venv creation failed."
"$VENV/bin/pip" install -U pip >/dev/null

say "Installing PyTorch + diffusers stack (MPS build)…"
"$VENV/bin/pip" install -U \
    torch torchvision \
    diffusers transformers accelerate safetensors \
    sentencepiece protobuf numpy pillow huggingface_hub \
  || die "pip install of the image stack failed."

# Z-Image needs ZImagePipeline; fall back to diffusers git main if the release lacks it.
say "Verifying ZImagePipeline is available…"
if ! "$VENV/bin/python" -c "from diffusers import ZImagePipeline, ZImageTransformer2DModel" 2>/dev/null; then
  warn "Released diffusers lacks ZImagePipeline; installing diffusers from git main…"
  "$VENV/bin/pip" install -U "git+https://github.com/huggingface/diffusers" \
    || die "diffusers git install failed."
  "$VENV/bin/python" -c "from diffusers import ZImagePipeline, ZImageTransformer2DModel" \
    || die "ZImagePipeline still unavailable after git install."
fi
say "diffusers: $("$VENV/bin/python" -c 'import diffusers; print(diffusers.__version__)')"
say "torch MPS available: $("$VENV/bin/python" -c 'import torch; print(torch.backends.mps.is_available())')"

# --- prefetch models into the skill's fast cache ------------------------------
mkdir -p "$HF_HUB"
say "Downloading Z-Image models into $HF_HUB (this is ~20 GB)…"
HF_HUB="$HF_HUB" "$VENV/bin/python" - "$Z_BASE" "$Z_TEXT_ENCODER" <<'PY'
import os, sys
from huggingface_hub import snapshot_download
cache = os.environ["HF_HUB"]
token = os.environ.get("HF_TOKEN")
for repo in sys.argv[1:]:
    print(f"[prefetch] {repo} -> {cache}")
    snapshot_download(repo_id=repo, cache_dir=cache, token=token)
    print(f"[prefetch] done: {repo}")
PY
[ $? -eq 0 ] || warn "Z-Image prefetch hit an error (see above). The skill will still work but may re-download."

if [ -n "${FLUX_MODEL:-}" ]; then
  say "Downloading Flux model ($FLUX_MODEL, ~24 GB) into the default HF cache…"
  "$VENV/bin/python" - "$FLUX_MODEL" <<'PY'
import os, sys
from huggingface_hub import snapshot_download
token = os.environ.get("HF_TOKEN")
repo = sys.argv[1]
print(f"[prefetch] {repo}")
try:
    snapshot_download(repo_id=repo, token=token)
    print(f"[prefetch] done: {repo}")
except Exception as e:
    print(f"[prefetch] flux skipped/failed (may need HF_TOKEN): {e}")
PY
fi

cat <<EOF

============================================================
 Image-gen stack ready (full bf16 — highest quality).

 Generate with Z-Image (run from the workspace so the local
 content_safety module is importable):

   cd $WORKSPACE
   $VENV/bin/python z_image_skill.py "a lighthouse at dawn" ~/zimg_test.png

 Flux A/B alternative:
   $VENV/bin/python flux_skill.py "a lighthouse at dawn" ~/flux_test.png

 Notes:
   * Z_IMAGE_QUANTIZE_WEIGHTS is intentionally UNSET (full bf16).
   * First Z-Image run also pulls the NSFW output-gate classifier
     (Falconsai/nsfw_image_detection, small) used by content_safety.
============================================================
EOF
