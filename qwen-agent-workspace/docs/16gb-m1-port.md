# 16GB M1 MacBook Pro port

Runs the same story→image→video pipeline used on this project's 48GB
development machine on a 16GB M1 Pro/Max MacBook Pro, in seed-image mode,
with the smallest model variants that plausibly fit. This is a single
hand-set-up machine, not a repeatable deploy target — see
`docs/superpowers/specs/2026-09-26-16gb-m1-port-design.md` for the full
design rationale and `docs/superpowers/plans/2026-09-26-16gb-m1-port.md`
for the validation history this page summarizes.

## One-command setup

```
bash scripts/setup-lean-16gb.sh
```

Downloads the three models below, reports (but does not change) the GPU
wired-memory cap, and prints the exact pipeline command to run — once
you've done the one required calibration step (see below).

## Models (real hardware, confirmed 2026-09-26)

| Stage | Model | Size |
|---|---|---|
| Video DiT | `dgrauet/ltx-2.3-mlx-q4` (distilled transformer only) | ~19.6GB |
| Text encoder | `mlx-community/gemma-3-12b-it-qat-abliterated-lm-4bit` | ~6.85GB |
| Vision LLM (preferred, 2026-09-27) | `andrevp/Qwen3.5-9B-Distilled-OPUS-Heretic-MLX-VLM-8bit` via `mlx_vlm.server` | ~9GB |
| Vision LLM (original, full pipeline confirmed) | `alexgusevski/Huihui-Qwen3-VL-4B-Instruct-abliterated-q4-mlx` via `bin/story-server vision` | ~3.1GB |

The text encoder is **not** `ltx-2-mlx`'s own default
(`mlx-community/gemma-3-12b-it-4bit`) — that OOM'd on the real target
machine. This QAT (quantization-aware-trained) variant is the one that was
actually confirmed stable there. `bin/ltx-movie --gemma` (added for this
port, commit `59dfc2d`) is what makes overriding it possible at all.

## Hard requirement: always pass `--seed-image`

**Text-only mode (no `--seed-image`) does not work on this machine — confirmed by a
real failure, not just predicted.** Omitting `--seed-image` falls back to Z-Image-Turbo
for panel 1's still, and its base transformer alone is ~24.6GB (3 safetensors shards:
9.97 + 9.97 + 4.67GB) — 1.5x the entire machine's unified memory, before the text
encoder or any activations are even counted. No amount of text-encoder quantization
changes this; only the DiT's own size matters here, and it isn't quantized. Real
failure observed on this target:

```
panel 1 ERROR: MPS backend out of memory (MPS allocated: 19.80 GiB, other
allocations: 2.80 MiB, max allowed: 20.13 GiB). Tried to allocate 708.98 MiB on
private pool.
```

Every invocation of `bin/ltx-movie` on this machine must include `--seed-image <a
real photo>`.

## Confirmed-stable geometry

```
--model dgrauet/ltx-2.3-mlx-q4 \
--gemma mlx-community/gemma-3-12b-it-qat-abliterated-lm-4bit \
-W 640 -H 384 --frames 169 --frame-rate 24
```

**Preferred vision backend (2026-09-27): `andrevp/Qwen3.5-9B-Distilled-OPUS-Heretic-MLX-VLM-8bit` via `mlx_vlm.server`.**
Phase 1 releases the vision server before Phase 4 needs its memory back, so
there's no reason to stay small during story generation — this is the
chosen "biggest model that fits alone" choice. **Confirmed so far: Phase 1
only** (a real, image-grounded story generated successfully). Phase 2-4
completion with this backend has not yet been confirmed end to end.

```bash
python3 -m mlx_vlm.server --model "andrevp/Qwen3.5-9B-Distilled-OPUS-Heretic-MLX-VLM-8bit" --port 8177
```

```
python3 bin/ltx-movie "..." --seed-image <photo> --story-id <id> \
  --story-model "andrevp/Qwen3.5-9B-Distilled-OPUS-Heretic-MLX-VLM-8bit" \
  --no-story-server-stop-after-story \
  ... (the confirmed-stable geometry/model flags above)
```

`--story-model` is required — without it, `bin/ltx-movie` never tells `bin/qwen-agent`
which model to declare, so it falls back to a hardcoded default that doesn't match
whatever's actually serving (a real bug found and fixed this session, `bin/ltx-movie`
commit `6118804`). `--no-story-server-stop-after-story` is also required: `bin/story-server
stop` only recognizes `vllm serve`/`mtplx serve` command lines, so it can never
find or release `mlx_vlm.server` — **you must kill it yourself, and you must do
it before Phase 4 starts**, since with `--no-review` there is no pause point at
all between phases. If you don't kill it in time, Phase 4 (video DiT + Gemma)
will try to load while the ~9GB vision model is still resident.

**Not `mlx_lm.server`.** A real dead end hit on this exact port: `mlx_lm.server`
(the `mlx-lm` package) unconditionally rejects any multimodal request with
`Only 'text' content type is supported.` — hardcoded in its own source
(`mlx_lm/server.py`), regardless of which model is loaded or what model name is
declared. This is not fixable by matching `--story-model` to the server; the
server itself cannot process images at all. The correct tool for a real VLM
checkpoint is the separate `mlx_vlm` package's own server (`python3 -m
mlx_vlm.server`), confirmed to actually handle `image_url` content parts.

**Original, fully-validated alternative:** `alexgusevski/Huihui-Qwen3-VL-4B-Instruct-abliterated-q4-mlx`
via the standard `bin/story-server vision` path (`STORY_SERVER_VISION_GPU_MEM_UTIL=0.50`
vs. the 48GB machine's default of `0.70`) — this is the one with a full,
confirmed Phase 1-4 real-hardware pass (a real, image-grounded 3-panel chain,
movie.mp4 produced). No manual server lifecycle management needed; `bin/story-server`
handles start/stop/release itself.

## Required one-time calibration: `--min-avail-gib`

`bin/ltx-movie`'s default `--min-avail-gib` (25.0) will never pass its
precondition check on a 16GB machine, and no safe real value was captured
during this port's validation — that measurement was explicitly skipped in
favor of moving forward once a stable model/geometry combination was found
(an accepted, flagged risk, not an oversight). `scripts/setup-lean-16gb.sh`
prints the exact recipe: run one real single-panel render with a
near-zero probe value and a background swap sampler, read the peak swap
usage, and pick a `--min-avail-gib` with real headroom above it. Do this
once per machine before relying on unattended multi-panel runs.

## Quality/speed tradeoff vs. the 48GB setup

**Not yet measured.** The real-hardware validation that found this
combination confirmed it renders successfully and produces a valid,
image-grounded story, but did not record wall-clock render time per panel
or a side-by-side quality comparison against the 48GB machine's larger
models. Treat this port as functionally validated, not yet
performance-characterized — a future session should capture real timing
once the calibration above has also been done.

## Known risks

- **The 9B `mlx_vlm.server` path has no automated memory release.**
  `bin/story-server` cannot start, stop, or manage it — you must kill it
  manually, and you must do so before Phase 4 starts. Combined with
  `--no-review`, there is no pause point at all between phases, so this is
  genuinely timing-sensitive: watch the console for `=== Phase 4: render ===`
  and kill the server before that line appears, not after.
- **4B-class vision-model prose quality.** Confirmed working on one real
  3-panel chain test. This is one data point, not a guarantee across many
  different prompts — this project's own prior research flagged 4B-class
  prose quality as a real risk before any hardware validation existed.
- **`--min-avail-gib` and `iogpu.wired_limit_mb`.** See the calibration
  section above — both are still open per-machine unknowns, not defaults
  you can skip.
- **GPU wired-memory cap persistence across reboot.** Not tested. If you
  need to raise the cap and it doesn't survive a reboot, you'll need a
  LaunchDaemon or `/etc/sysctl.conf` entry — not set up by this port.
