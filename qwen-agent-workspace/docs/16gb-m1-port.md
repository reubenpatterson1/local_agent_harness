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
| Vision LLM | `alexgusevski/Huihui-Qwen3-VL-4B-Instruct-abliterated-q4-mlx` | ~3.1GB |

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

Vision server: `STORY_SERVER_VISION_GPU_MEM_UTIL=0.50` (vs. the 48GB
machine's default of `0.70`), served via the standard `bin/story-server
vision` path. This produced a real, image-grounded 3-panel seed-image
chain successfully.

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
