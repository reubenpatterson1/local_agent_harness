# 16GB M1 MacBook Pro Port — Design

## 1. Goal

Run the existing story→image→video pipeline (the same sequential I2V frame-chaining flow built on `z_image_skill.py` + `ltx2_mlx_video_skill.py` + `bin/story-server`) on a 16GB M1 Pro/Max MacBook Pro, in seed-image mode, with the smallest model variants that can plausibly fit — accepting a real quality/speed tradeoff versus the 48GB development machine.

This is explicitly **not** a repeat of the ltx-chain-deploy-package effort. There is no second deploy target, no fleet of installs, no credential-scanning/provenance machinery to build. This is a single personal machine, set up once by hand.

## 2. Why this is hard: the real constraint

The video-generation tool (`ltx-2-mlx`) streams the video diffusion transformer via `--low-ram`, but it does **not** stream its text-encoding stage: the Gemma text encoder plus a bf16-only connector are loaded together and freed only after being fully resident, before the DiT loads. This stage — not the DiT's quantization level — is the actual memory floor:

| LTX pack | Text-encoder + connector floor |
|---|---|
| LTX-2.5 (any quant) | ~19GB — rules it out entirely |
| LTX-2.3 (Gemma-3-12B-4bit + connector) | ~13.8GB |

A 16GB Mac's realistic usable budget for a single foreground ML workload is roughly 10–11GB, once macOS's own overhead and its GPU wired-memory working-set cap (~2/3 of total RAM by default on machines this size) are accounted for. **13.8GB is larger than that estimated safe budget.** This is the single biggest open risk in this whole port, and it cannot be resolved by picking a smaller DiT quant — only by (a) raising the GPU wired-memory cap manually via `sudo sysctl iogpu.wired_limit_mb` on the target machine itself, and (b) confirming empirically, on the real target hardware, that the stage actually loads without OOM or heavy swap thrashing.

Counterintuitively, seed-image mode is the *lighter* pipeline shape here, not text-only mode: text-only mode requires loading Z-Image (~29GB measured footprint) to generate panel 1's image, while seed-image mode skips Z-Image entirely and only needs a small vision-capable model for story generation. The user has confirmed seed-image mode with a small vision model as the target shape.

## 3. Model selection

| Stage | Model | Size | Why |
|---|---|---|---|
| Video DiT | `dgrauet/ltx-2.3-mlx-q4` (distilled transformer) | ~10.54GB (uniform int4, group_size 64) | Officially published by the same author as `ltx-2-mlx` itself; its own README documents the exact `ltx-2-mlx generate --distilled --model dgrauet/ltx-2.3-mlx-q4` invocation already matching this project's usage pattern — genuinely zero-new-code compatible. **Correction, 2026-09-26:** the previously-recommended `baa-ai/LTX-2.3-22B-RAM-12GB-MLX` (~9.97GB DiT) was found to require a custom per-layer mixed-precision quantization loader (its own `generate.py`, not the installed `ltx-2-mlx`'s standard `apply_quantization`, which only derives one uniform bit-width for the whole model) — using it would need new code, contradicting the user's "no new code" decision. `dgrauet`'s pack is ~1.2GB bigger but requires no new code. |
| Text encoder | `mlx-community/gemma-3-12b-it-qat-abliterated-lm-4bit` | ~6.85GB (2 safetensors shards, 5,357,465,200 + 1,999,038,214 bytes) | **Correction, 2026-09-26 (real hardware):** validated directly on the target 16GB M1 Pro/Max — the originally-planned `mlx-community/gemma-3-12b-it-4bit` OOM'd; this QAT (quantization-aware-trained) variant is smaller and loads cleanly. Confirmed stable with the unchanged video DiT below at `-W 640 -H 384 --frames 169 --frame-rate 24`. |
| Connector | (ships with the LTX-2.3 pack) | ~6.34GB | Must stay bf16 per `ltx-2-mlx`'s own constraints; cannot be quantized further. Byte-identical (same sha256) across the `dgrauet` and `baa-ai` packs — a fixed component of LTX-2.3, not specific to either quantization scheme. |
| Story/vision LLM | `alexgusevski/Huihui-Qwen3-VL-4B-Instruct-abliterated-q4-mlx` | ~3.11GB | Smallest vision-capable model found. **Confirmed, 2026-09-26 (real hardware):** served via the standard `bin/story-server vision` (vLLM-Metal) path at `STORY_SERVER_VISION_GPU_MEM_UTIL=0.50`, produced a valid, image-grounded story in a real multi-panel seed-image chain test — the previously-flagged "4B prose quality" risk did not materialize on this one run (still only one data point, see §8). |

No Wan, ComfyUI, mflux, or diffusers-based alternative is considered — this project deliberately removed all of those in favor of `z_image_skill.py` + `ltx2_mlx_video_skill.py` only (commit `8043a09`, 2026-09-25), and reintroducing any of them for this port would contradict that decision.

Total download footprint: DiT (~10.54GB) + Gemma (~6.85GB) + connector (~6.34GB) + the pack's smaller components (VAE encoder/decoder, audio VAE, vocoder — combined ~1.7GB) + vision model (~3.1GB) ≈ 28.5GB, well within the confirmed 100GB+ free space on the target disk.

## 4. Memory-safety adjustments

- **GPU wired-memory cap.** Raise via `sudo sysctl iogpu.wired_limit_mb=<value>` on the target machine directly (real terminal access there, unlike the current headless dev host). Whether this setting persists across reboot or needs a LaunchDaemon/`sysctl.conf` entry to survive one is unconfirmed — the setup script must check and handle whichever is true, determined during implementation, not assumed here.
- **`--min-avail-gib`.** `bin/ltx-movie` currently defaults this to 25.0, unreachable on a 16GB machine. The port needs an explicit, much lower value passed on every invocation — the exact number comes from real measurement during validation (Section 6), not a guess written into this spec.
- **`STORY_SERVER_VISION_GPU_MEM_UTIL`.** Already-supported env override; the existing default (0.70) reserves ~11.2GB on a 16GB machine for the vision server alone, which is likely too high once the video stage also needs headroom — this also gets a real value from validation, not assumed here.

## 5. Explicit non-goals

- No changes to `bin/ltx-movie`, `ltx2_mlx_video_skill.py`, `bin/story-server`, or any other pipeline code. Every mechanism needed (`--model`, `--min-avail-gib`, `STORY_SERVER_VISION_MODEL_DIR`, `STORY_SERVER_VISION_GPU_MEM_UTIL`) already exists as a flag or env var — the user has explicitly chosen raw explicit flags over adding a new `--profile` shortcut.
- No reuse of `scripts/deploy/build_pkg.py` / `install_pkg.py` — no credential scanning, no provenance checks, no manifest/schema machinery. This is a single hand-set-up machine, not a repeatable deploy target.
- No attempt to reduce below LTX-2.3 (no LTX-2.0, no diffusers-format LTX-Video 2B — the latter isn't supported by the installed `ltx-2-mlx` tool at all and would require a different runtime).
- No touching the in-progress, unrelated background download (`MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8`) — confirmed by the user as unrelated activity.

## 6. Validation plan (must happen in this order, on the real target hardware)

1. **Text-encoding-stage smoke test.** Confirm `Gemma-3-12B-4bit` + the LTX-2.3 connector load together without OOM or sustained heavy swapping. This is the single highest-risk unknown in the whole design. If this fails, stop — the LTX-2 model family may not be viable on 16GB at all, and the fallback options (a further-reduced-bit `--gemma` variant, or accepting the port isn't currently feasible) need a fresh decision with the user, not a silent workaround.
2. **Single-panel render**, conservative small geometry (exact resolution/frame count to be chosen empirically based on how much headroom step 1 leaves — no number is fixed here).
3. **Multi-panel chain test** (the project's actual sequential I2V frame-chaining flow, at least 2–3 panels) to confirm the full pipeline holds up across a story, not just one clip.
4. **Only after 1–3 succeed**, write the setup script and docs using the real flag values, geometry, and timings that worked — not predicted ones.

## 7. Deliverables

- `scripts/setup-lean-16gb.sh` — downloads the three models above to their expected local paths, performs (or documents, if it can't be automated) the `iogpu.wired_limit_mb` adjustment, and prints the resulting exact command line to run the pipeline with all required explicit flags.
- `docs/16gb-m1-port.md` — the exact flags/env vars to use, the quality/speed tradeoff versus the 48GB setup, and the known risks (unvalidated 4B vision-model prose quality at the current shortened seed-story prompt).

## 8. Open risks carried into implementation (not resolved by this spec)

- ~~Whether the ~13.8GB text-encoding stage actually loads on a real 16GB M1 Pro/Max at all~~ **RESOLVED, 2026-09-26 (real hardware):** the originally-planned Gemma variant OOM'd; swapping to `mlx-community/gemma-3-12b-it-qat-abliterated-lm-4bit` fixed it, confirmed stable at `-W 640 -H 384 --frames 169 --frame-rate 24` with the video DiT unchanged (`dgrauet/ltx-2.3-mlx-q4`).
- **Accepted risk, 2026-09-26 (flagged, not blocking):** the peak swap-used figure, whether `iogpu.wired_limit_mb` needed raising to reach the stable combination above, and the exact `--min-avail-gib` value used were not captured during that hardware session. Task 4's setup script and docs cannot cite real numbers for these three until a future session on the target machine records them (rerun Task 1 Step 4's memory sampler alongside the confirmed-stable command, or capture live next time it's run) — proceeding to Task 3 without them is a deliberate, accepted gap, not a silent one.
- 4B-class vision-model prose quality for multi-panel seed-story generation (a known, previously-flagged risk in this project's own prior research, never tested at the current, shortened prompt length) — still open, not exercised by this result.
- Whether the GPU wired-memory cap raise persists across reboots or needs a persistence mechanism — still open.
