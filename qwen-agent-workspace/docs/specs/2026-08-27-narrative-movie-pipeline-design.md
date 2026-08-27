# Spec: narrative movie pipeline — operator runbook, manifest v2, and the decode-split decision rule

**Status:** Documentation of the implemented Phase B (steps 4-9). Phase A (the `mps_guard` two-tier
persistence sentinel) already landed and is out of scope here.
**Date:** 2026-08-27
**Type:** Operator runbook + schema/algorithm reference for the story-to-video pipeline
(`bin/ltx-story-manifest`, `bin/ltx-story-images`, `bin/ltx-story-video`).

---

## 1. Four-phase operator runbook

The pipeline runs in four phases. Phases A-C are offline/cheap and can be repeated freely; Phase D is
the one that touches the vLLM servers and the GPU.

### Phase A — story authoring (one qwen-agent turn)

Ask qwen-agent, in one turn, to write a `story.md` using the v2 panel format: a `# <Story Title>`
heading, an optional narrative paragraph, then one `## Panel N — <title>` section per panel, each
containing exactly three labeled fields:

```
## Panel 1 — The Bully's Playground
Image: <the still-image prompt for this panel, fed to bin/ltx-story-images>
Motion: <the camera/motion prompt for this panel's video unit>
Narration: <the voice-over/caption line for this panel>
```

Save it to `generated/stories/<story_id>/story.md`. `Image:`/`Motion:`/`Narration:` values may wrap
onto following unlabeled lines (space-joined) — see Section 2.

### Phase B — panel images (`bin/ltx-story-images`, servers up)

```
cd /Users/reubenpatterson/qwen-agent-workspace
python3 bin/ltx-story-images \
    --story-md generated/stories/<story_id>/story.md \
    --out-dir  generated/stories/<story_id>/panels \
    --width 1024 --height 1024 --seed 0
```

Renders one `panel_NN.png` per `Image:` field via `z_image_skill.generate_image`, writing
`panels/images.json` (schema below skipped here — see the tool's own docstring). One blocked/failed
panel does not lose the rest of the batch; re-run with `--force` to regenerate a specific `--only N,M`
subset.

### Phase C — manifest + dry-run review (offline)

```
python3 bin/ltx-story-manifest \
    --story-id <story_id> \
    --prompts-md generated/stories/<story_id>/story.md \
    --glob 'panel_*.png' --images-dir generated/stories/<story_id>/panels \
    --target-seconds 30 --fps 24 --pace proportional \
    --force

python3 bin/ltx-story-video generated/stories/<story_id>/manifest.json \
    generated/stories/<story_id>/story_per_panel.mp4 \
    --mode per-panel --dry-run
```

Review the printed per-unit frame counts and the `TOTAL ... frames` line before spending any GPU
time. Nothing in Phase C touches the servers.

### Phase D — the run (sudo-launched, servers touched)

```
sudo -v   # non-interactive page-cache purge in stage 1 needs a cached sudo ticket
cd /Users/reubenpatterson/qwen-agent-workspace
nohup python3 bin/ltx-story-video generated/stories/<story_id>/manifest.json \
    generated/stories/<story_id>/story_per_panel.mp4 --mode per-panel \
    --on-unit-failure skip --retry-failed 1 --retry-idle 120 --max-consecutive-failures 3 \
    > generated/stories/<story_id>/per_panel.log 2>&1 & disown
```

`--on-unit-failure skip` keeps going past individual unit failures instead of aborting the whole run;
`--max-consecutive-failures 3` trips a circuit breaker if the host is degraded (three failures in a
row), printing the exact relaunch command instead of burning through every remaining unit one at a
time; `--retry-failed 1 --retry-idle 120` gives every unit that failed in the main pass exactly one
second attempt, after idling 120s to let swap reclaim (see Section 4 for how strong that idle's
evidence actually is). Tail `per_panel.log`; `generated/stories/<story_id>/runs/<run_id>/story_summary.json`
records the final per-unit outcome, `stopped_reason`, and both the intended and actual total frame
counts.

---

## 2. Manifest v2 schema

`bin/ltx-story-manifest` always writes `schema_version: 2` now; `bin/ltx-story-video` still accepts
`schema_version: 1` manifests unchanged (its own default `--num-frames` becomes the per-unit fallback
when a panel carries no `num_frames` of its own).

```json
{
  "schema_version": 2,
  "story_id": "string",
  "title": "string",
  "narrative": "string",
  "created_at": "ISO8601 string",
  "fps": 24,
  "target_seconds": 30.0,
  "pace": "proportional",
  "total_num_frames": 719,
  "total_duration_s": 29.958,
  "panels": [
    {
      "index": 1,
      "image_path": "/absolute/path/panel_01.png",
      "title": "string, may be empty",
      "panel_text": "non-empty string, required (from the Image: field when v2-labeled)",
      "narration": "string, may be empty",
      "narration_words": 6,
      "num_frames": 41,
      "duration_s": 1.708,
      "motion_prompt": "string or null (from the Motion: field, null only when empty)",
      "transition_to_next": null
    }
  ]
}
```

`pace` is one of `"proportional"` (weight = word count of `Narration`), `"equal"` (weight = 1 for
every panel), `"explicit"` (an explicit `--frames` override was used), or `"legacy"` (no `--prompts-md`
was given at all — the pre-v2 scaffold-only workflow, which has no narration/duration concept and
keeps a fixed 49-frame-per-panel default instead of running the allocator; see Section 3.4).

---

## 3. The allocation algorithm

### 3.1 Goal

Given `N` panels, a `--target-seconds @ --fps` budget, and an `[--min-frames, --max-frames]` envelope
(each endpoint required to satisfy `(n-1) % 8 == 0` and `9 <= min <= max`, the VAE's own temporal
constraint — see `ltx_video_skill._validate_geometry`), assign each panel a frame count on the
`n = 1 + 8k` lattice such that the panels' relative weights (word count of their `Narration`, or equal)
are respected as closely as the lattice allows, and the sum lands as close to `round(target_seconds *
fps)` as the lattice allows.

### 3.2 `_snap_frames(x)`

Round `x` to the nearest lattice point `n = 1 + 8k, k >= 1` (so `n >= 9`); an exact tie between the two
neighboring lattice points resolves **down**.

### 3.3 `_allocate_frames(weights, target_frames, min_frames, max_frames)`

1. `raw[i] = weights[i] / sum(weights) * target_frames`.
2. `f[i] = clamp(_snap_frames(raw[i]), min_frames, max_frames)`.
3. Reconciliation, bounded at 1000 iterations: while `|target_frames - sum(f)| >= 8`, move one lattice
   step (±8) into/out of the smallest/largest eligible `f[i]` (ties broken toward the lowest index),
   never past `[min_frames, max_frames]`.

**The mod-8 congruence, and why the loop terminates:** every `f[i]` is `≡ 1 (mod 8)`, so
`sum(f) ≡ N (mod 8)` is an *invariant* of the whole reconciliation loop — no single ±8 step can change
it. That means `|target_frames - sum(f)| < 8` is the exact optimum reachable on this lattice, not an
approximation to tighten further; the loop is correct to stop there, and a well-meaning "let's just
keep going until it's exact" rewrite would spin until the 1000-iteration bound and still never
converge for any `target_frames !≡ N (mod 8)`.

### 3.4 CLI-level behavior

- `--pace proportional` (the default) requires every panel to have a non-empty `Narration` — this is
  only enforced when `--prompts-md` was given at all; the legacy scaffold-only workflow (no
  `--prompts-md`) has no narration concept and keeps a fixed 49-frame default per panel instead
  (Section 2's `"legacy"` pace value).
- If `|target_frames - sum(f)| > 8` after allocation, the tool exits 2 naming the requested target,
  the achievable range `[N*min_frames, N*max_frames]`, and the `sum ≡ N (mod 8)` congruence, and
  suggests changing the panel count or `--min-frames`/`--max-frames`.
- `--frames` (repeatable, one int per panel) bypasses the allocator entirely and is mutually exclusive
  with `--pace`.

---

## 4. 2026-08-27 swap-abort measurement summary

Before Phase A's two-tier persistence sentinel landed, every `robot_story_photoreal` per-panel run
(`per_panel.log`, `per_panel_diag.log`, `per_panel_fix_verify.log`, `per_panel_retry.log`,
`per_panel_retry2.log`, all under
`generated/stories/robot_story_photoreal/`) hit repeated `sentinel_abort` failures in stage 2, always
during the pipeline's own device-transfer/load step (`pipeline.to(...)`) rather than during actual
denoising or decode — e.g.:

```
generated/stories/robot_story_photoreal/per_panel_diag.log:49:
unit panel-1 FAILED (sentinel_abort, rc=75): swap grew 3.93 GiB (from 10.44 to 14.37),
above 2.0, and absolute usage 14.37 exceeds floor 6.5
```

Raw traces for every such abort (one directory per run, one `mem_stage2.jsonl`/`peaks_stage2.json`
per unit cell) live under `generated/stories/robot_story_photoreal/runs/<run_id>/<label>/`, e.g.
`generated/stories/robot_story_photoreal/runs/20260826T224522Z-35166b34/panel-3/`. The fix (Phase A,
already landed and green across all suites) was the two-tier persistence sentinel in `mps_guard.py`:
a single-sample swap spike during the load step is no longer treated as a hard abort signal by
itself; a sustained, persistent climb still is.

`--retry-idle 120` (Phase D, Section 1) is deliberately conservative given the same evidence base: the
only supporting datum for an idle-based swap reclaim is a 6.6 → 3.3 GiB reduction observed over
**hours** of host idle between sessions, whereas in-stage traces from the same runs show swap
receding roughly 2 GiB within 15 seconds on its own, with no pause at all. `--retry-idle`/`--unit-pause`
are therefore an inexpensive hedge, not a proven fix — treat any large improvement they appear to
produce with suspicion until it's been isolated from the sentinel fix itself.

---

## 5. Decode-split decision rule

Do **not** split `vae.decode()` across the current 57-frame ceiling speculatively. Only revisit it if
one of the following is actually observed:

1. A smoke-test unit's `peaks_stage2.json["mps_driver_gib"] >= 30.0` **at 57 frames** (the field is
   written per-unit at `generated/stories/<story_id>/runs/<run_id>/<label>/peaks_stage2.json`; compare
   against the measured value there, not a guess).
2. An actual MPS out-of-memory error raised from inside `vae.decode()` (as opposed to a sentinel abort
   during load/denoise, which Section 4's fix already addresses).
3. A future story genuinely wants more than 57 frames per unit (i.e. `--max-frames > 57`), which is
   outside every measured ceiling entry today.

Any one of these three is sufficient to justify the added complexity; none of them has been observed
as of this writing, so no decode-split work is scheduled.
