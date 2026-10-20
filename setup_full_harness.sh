#!/bin/bash
#
# setup_full_harness.sh — provision the ENTIRE qwen-agent production harness
# on this Apple Silicon host (M1 Ultra / 128 GB), at the largest practical
# model sizes. Staged and resumable: each stage is idempotent and can be run
# on its own.
#
#   bash setup_full_harness.sh                 # run every stage in order
#   bash setup_full_harness.sh text vision     # run only the named stage(s)
#
# Stages: brew  text  vision  image  video_mlx  video_torch  searxng  mflux  finalize
#
# RUN AS YOUR NORMAL USER (not sudo). Prereq: setup_host.sh already installed
# Homebrew + python@3.12 + Docker.
#
set -uo pipefail

# ---- tunables ---------------------------------------------------------------
# Prebuilt MLX quant (no local conversion). 8-bit = near-lossless on 128 GB.
# NOTE: Qwen3.8-27B is a MULTIMODAL (image-text-to-text) model, so it is served
# by mlx_vlm.server, not mlx_lm.server. This repo has the full preprocessor
# config set (unlike some trimmed exports), so it loads correctly in mlx_vlm.
# Alternatives: ailexleon/...-mlx-6Bit, ailexleon/...-mlx-4Bit.
TEXT_REPO="${TEXT_REPO:-ailexleon/Huihui-Qwen3.8-27B-abliterated-mlx-8Bit}"
# A local mlx_lm conversion already produced a TEXT-ONLY 8-bit model at the
# path below (no vision preprocessor) — exactly the researcher role; served by
# mlx_lm.server. Vision is the separate 32B model (stage_vision). stage_text
# reuses this dir if present and only downloads TEXT_REPO as a fallback.
TEXT_OUT="${TEXT_OUT:-$HOME/mlx_models/Huihui-Qwen3.8-27B-abliterated-mlx-8bit}"
# Only a 4-bit MLX build is prebuilt; on 128 GB we convert the bf16 base to
# 8-bit locally (higher fidelity for OCR-in-images and clip/still judging).
VISION_BASE="huihui-ai/Huihui-Qwen3-VL-32B-Instruct-abliterated"
VISION_QBITS="${VISION_QBITS:-8}"
VISION_DIR="$HOME/mlx_models/qwen3-vl"
LTX2_VIDEO="dgrauet/ltx-2.3-mlx-q8"
LTX2_GEMMA="mlx-community/gemma-3-12b-it-4bit"
LTX_TORCH="Lightricks/LTX-Video-0.9.8-13B-distilled"

MLX_VENV="$HOME/mlx-serve"                         # created by setup_host.sh (mlx-vlm); we add mlx-lm
IMG_VENV="$HOME/img-gen"                           # created by setup_image_skills.sh
LTX2_DIR="$HOME/ltx-2-mlx"
LTX2_HF="$HOME/ltx-2-mlx/hf_cache"
MFLUX_VENV="$HOME/mflux/.venv"
REPO="$HOME/local_agent_harness"
WORKSPACE="$REPO/qwen-agent-workspace"
SX_DST="$HOME/.local/share/qwen-agent/searxng"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\n\033[1;33m[warn] %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31m[error] %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] && die "Do not run with sudo. Run as your normal user."
if ! command -v brew >/dev/null 2>&1 && [ -x /opt/homebrew/bin/brew ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi
command -v brew >/dev/null 2>&1 || die "Homebrew missing. Run setup_host.sh first."
PY="$(brew --prefix)/opt/python@3.12/bin/python3.12"; [ -x "$PY" ] || PY=python3.12

# download helper: snapshot a repo into an explicit local dir (venv-agnostic)
hf_to_dir() { # repo localdir [venv]
  local repo="$1" dir="$2" venv="${3:-$MLX_VENV}"
  mkdir -p "$dir"
  "$venv/bin/python" - "$repo" "$dir" <<'PY'
import sys
from huggingface_hub import snapshot_download
import os
repo, dir = sys.argv[1], sys.argv[2]
print(f"[hf] {repo} -> {dir}")
snapshot_download(repo_id=repo, local_dir=dir, token=os.environ.get("HF_TOKEN"))
print(f"[hf] done: {repo}")
PY
}
hf_to_cache() { # repo [HF_HOME] [venv]
  local repo="$1" hfhome="${2:-}" venv="${3:-$IMG_VENV}"
  [ -n "$hfhome" ] && export HF_HOME="$hfhome"
  "$venv/bin/python" - "$repo" <<'PY'
import sys, os
from huggingface_hub import snapshot_download
repo = sys.argv[1]
print(f"[hf] {repo} -> HF_HOME={os.environ.get('HF_HOME','default')}")
snapshot_download(repo_id=repo, token=os.environ.get("HF_TOKEN"))
print(f"[hf] done: {repo}")
PY
}

# ---- stages -----------------------------------------------------------------
stage_brew() {
  say "Homebrew CLI deps: ffmpeg, uv"
  brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg || die "ffmpeg install failed"
  brew list uv      >/dev/null 2>&1 || brew install uv      || die "uv install failed"
  command -v ffmpeg >/dev/null || die "ffmpeg not on PATH after install"
  say "ffmpeg: $(ffmpeg -version | head -1)"
}

stage_text() {
  say "Text LLM: prebuilt MLX quant $TEXT_REPO -> $TEXT_OUT"
  [ -d "$MLX_VENV" ] || { "$PY" -m venv "$MLX_VENV"; "$MLX_VENV/bin/pip" install -U pip >/dev/null; }
  "$MLX_VENV/bin/pip" install -U mlx-lm mlx-vlm huggingface_hub >/dev/null || die "mlx-lm install failed"
  if [ -f "$TEXT_OUT/config.json" ]; then
    say "Already present: $TEXT_OUT"
  else
    hf_to_dir "$TEXT_REPO" "$TEXT_OUT" "$MLX_VENV" || die "text model download failed"
  fi
  say "Text model ready at $TEXT_OUT"
}

stage_vision() {
  say "Vision VLM: convert $VISION_BASE -> MLX ${VISION_QBITS}-bit at $VISION_DIR"
  [ -d "$MLX_VENV" ] || die "run 'text' stage first (creates mlx venv)"
  "$MLX_VENV/bin/pip" install -U mlx-vlm >/dev/null
  if [ -f "$VISION_DIR/config.json" ] && ls "$VISION_DIR"/*.safetensors >/dev/null 2>&1 \
     && grep -q "\"bits\": *$VISION_QBITS" "$VISION_DIR/config.json" 2>/dev/null; then
    say "Already converted (${VISION_QBITS}-bit): $VISION_DIR"
  else
    rm -rf "$VISION_DIR"   # clear any partial/4-bit contents
    "$MLX_VENV/bin/python" -m mlx_vlm convert --hf-path "$VISION_BASE" \
      -q --q-bits "$VISION_QBITS" --mlx-path "$VISION_DIR" || die "vision convert failed"
  fi
  say "Vision model ready at $VISION_DIR"
}

stage_image() {
  say "Image skills (z_image + flux)"
  if [ -x "$WORKSPACE/setup_image_skills.sh" ]; then
    bash "$WORKSPACE/setup_image_skills.sh" || warn "image skills setup returned non-zero"
  else warn "setup_image_skills.sh not found; skipping"; fi
}

stage_video_mlx() {
  say "LTX-2 MLX video via ltx-2-mlx (uv)"
  command -v uv >/dev/null 2>&1 || die "uv missing; run 'brew' stage"
  if [ ! -x "$LTX2_DIR/.venv/bin/ltx-2-mlx" ]; then
    [ -d "$LTX2_DIR/.git" ] || git clone https://github.com/dgrauet/ltx-2-mlx.git "$LTX2_DIR" || die "ltx-2-mlx clone failed"
    ( cd "$LTX2_DIR" && uv sync --all-extras ) || die "uv sync failed"
  fi
  say "Downloading LTX-2 video models into $LTX2_HF (large; ~40 GB)"
  mkdir -p "$LTX2_HF"
  hf_to_cache "$LTX2_VIDEO" "$LTX2_HF" "$MLX_VENV" || warn "LTX-2 DiT download failed (repo may be gated/renamed — verify $LTX2_VIDEO)"
  hf_to_cache "$LTX2_GEMMA" "$LTX2_HF" "$MLX_VENV" || warn "gemma encoder download failed"
}

stage_video_torch() {
  say "Legacy torch LTX-Video 13B ($LTX_TORCH, ~27 GB) into default HF cache"
  [ -d "$IMG_VENV" ] || die "run 'image' stage first (creates torch venv)"
  hf_to_cache "$LTX_TORCH" "" "$IMG_VENV" || warn "torch LTX-Video download failed (may need HF_TOKEN)"
}

stage_searxng() {
  say "SearXNG (Docker) on 127.0.0.1:8888"
  docker info >/dev/null 2>&1 || { warn "Docker daemon not running; start Docker Desktop and re-run 'searxng'"; return; }
  mkdir -p "$SX_DST"
  cp "$WORKSPACE/searxng/docker-compose.yml" "$SX_DST/" 2>/dev/null || cp "$REPO/qwen-agent-workspace/searxng/docker-compose.yml" "$SX_DST/"
  cp "$WORKSPACE/searxng/settings.yml" "$SX_DST/" 2>/dev/null || true
  ( cd "$SX_DST" && docker compose -p qwen-agent-searxng up -d ) || warn "SearXNG compose up failed"
  sleep 3; curl -s "http://127.0.0.1:8888/" >/dev/null 2>&1 && say "SearXNG responding" || warn "SearXNG not answering yet"
}

stage_mflux() {
  say "mflux (stills LoRA training) venv at $MFLUX_VENV"
  mkdir -p "$(dirname "$MFLUX_VENV")"
  [ -d "$MFLUX_VENV" ] || "$PY" -m venv "$MFLUX_VENV"
  "$MFLUX_VENV/bin/pip" install -U pip >/dev/null
  "$MFLUX_VENV/bin/pip" install -U mflux >/dev/null || warn "mflux install failed (optional; only needed for LoRA training)"
}

stage_finalize() {
  say "Finalizing: make harness bin/ executable"
  chmod +x "$WORKSPACE"/bin/* 2>/dev/null || true
  cat <<EOF

============================================================
 Full harness provisioned (automatable parts).

 ONE server for everything. The 32B vision model handles BOTH the
 tool-calling story/agent path AND image scoring -- validated: it passes
 qwen-agent's tool-calling preflight. Serve it on :8177:

      $MLX_VENV/bin/python -m mlx_vlm server \\
        --model $VISION_DIR --host 127.0.0.1 --port 8177

 Then (one server is up; run one task at a time):
   * Video (story auto-detects the served model -- no --model needed):
       cd $WORKSPACE && ./bin/ltx-movie "..." --story-id my_movie --story-context-window 32768
       (mlx_vlm /v1/models reports no context length, so qwen-agent assumes
        16384 unless you pass --story-context-window / --context-window.)
   * Character stills (two-source, auto model-name resolution):
       cd $WORKSPACE && CHARACTER_TWO_SOURCE=1 QWEN_AGENT_VLM_MODEL=auto \\
         $IMG_VENV/bin/python bin/character create NAME --descriptor "..." --class NOUN --phrase "..."
   * Image gen:   $IMG_VENV/bin/python z_image_skill.py "..." out.png
   * SearXNG:     http://127.0.0.1:8888/

 Faster text-only alternative (optional): the 27B is converted to a text-only
 MLX model at $TEXT_OUT; serve it with mlx_lm for quicker story decode when no
 vision is needed (ltx-movie still auto-detects it):
      $MLX_VENV/bin/python -m mlx_lm server --model $TEXT_OUT --host 127.0.0.1 --port 8177

 STILL NEEDS YOU:
   * export ANTHROPIC_API_KEY=...   (judge-story / judge-clips / judge-stills / iterate-story)
   * Start the server (above) yourself before the agent -- the repo's vLLM-Metal
     auto-start (qwen-serve-guard) is not installed.
   * story-server 'text' mode (mtplx) is skipped (peripheral, not installed).
============================================================
EOF
}

# ---- driver -----------------------------------------------------------------
ALL=(brew text vision image video_mlx video_torch searxng mflux finalize)
STAGES=("$@"); [ ${#STAGES[@]} -eq 0 ] && STAGES=("${ALL[@]}")
for s in "${STAGES[@]}"; do
  case "$s" in
    brew|text|vision|image|video_mlx|video_torch|searxng|mflux|finalize) "stage_$s" ;;
    *) die "unknown stage '$s' (valid: ${ALL[*]})" ;;
  esac
done
