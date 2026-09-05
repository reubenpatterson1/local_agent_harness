# Spec: text-to-video chain rendering mode (`--no-stills`) for the narrative-movie pipeline

**Status:** Design approved section-by-section. Two **verification tasks must be completed as the first
implementation steps** (Section 13, OQ1 and OQ2) before the rest is built on top of them; both are
unverified technical assumptions, not open design decisions. Every design decision is settled and must be
implemented as written.
**Date:** 2026-09-04
**Type:** Additive rendering mode across four existing tools (`bin/ltx-movie`, `bin/ltx-story-manifest`,
`bin/ltx-story-video`, `bin/ltx-chain`), plus one relaxation of an existing validator. No new files, no new
dependency, no new schema version.
**Author target model:** written for a Sonnet `code-executor`. Every design choice is resolved here except
the items explicitly listed in Section 13, which are unresolved and must be answered first.

**Files this spec touches (all absolute, all in the git repo copy):**

| Path | Change |
| --- | --- |
| `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/bin/ltx-movie` | new `--no-stills` and `--reanchor-every` flags; alternate story-prompt template; Phase 2 skip; Phase 3/4 flag threading; dry-run plan text |
| `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/bin/ltx-story-manifest` | `Prompt:` label accepted by `_parse_prompts_md`; new `--no-images` panel source; `image_path: null` panels |
| `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/bin/ltx-story-video` | new `--engine {per-panel,chain}` (default `per-panel`) and `--reanchor-every N` (default 5); chain-engine unit builder + render path; relaxed manifest validation for null `image_path`; dry-run engine/group annotation |
| `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/bin/ltx-chain` | `_continue_settings_mismatch` no longer compares `prompt`; `--continue-from` re-encodes stage 1 when the requested prompt differs from the base's |
| `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/tests/test_ltx_movie_offline.py` | new offline cases (Section 9.1) |
| `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/tests/test_ltx_story_video.py` | new offline cases (Section 9.1) |
| `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/tests/test_ltx_chain.py` | updated `_continue_settings_mismatch` cases (Section 9.1) |

**Not touched:** `ltx_video_skill.py` (its T2V branch, stage split, ceiling check, and `_release_page_cache`
are all used as-is — see Section 0 and OQ1), `mps_guard.py`, `content_safety.py`, `bin/ltx-story-images`
(it is simply not invoked under `--no-stills`), `bin/ltx-generate`, `bin/ltx-host-prep`,
`bin/ltx-host-restore`, `z_image_skill.py`. The `WS` constant inside each tool
(`/Users/reubenpatterson/qwen-agent-workspace`) is **left exactly as it is** — there are two copies of this
workspace on the host and normalizing that constant is out of scope for this spec.

**Parent specs (both still authoritative; nothing in them is superseded):**

- **[NMP]** `docs/specs/2026-08-27-narrative-movie-pipeline-design.md` — the four-phase pipeline, manifest
  v2 schema, and the frame-allocation algorithm this mode extends. Every schema field, the `n = 1 + 8k`
  lattice, `_snap_frames`/`_allocate_frames`, and the Phase-D operator flags are unchanged here.
- **[MFC]** `docs/specs/2026-08-25-ltx-multiframe-conditioning-and-ceiling-sweep-design.md` — the
  conditioning data model (`conditions` array in `request.json`), the frame-lattice/geometry constraints,
  and the ceiling pre-check that the chain engine inherits without modification.

---

## 0. Ground truth verified against the installed source

All claims below were read directly from the repo copy at
`/Users/reubenpatterson/local_model_harness/qwen-agent-workspace` on 2026-09-04. Line numbers are as-read
on that date. Nothing in this section is inferred.

**G1 — `bin/ltx-movie` today.**
- `STORY_PROMPT_TEMPLATE` is lines 82–96; it emits `Image:` (70–90 words), `Motion:` (15–40 words), and
  `Narration:` per panel, and carries the recurring-character verbatim-repetition rule as its second-to-last
  paragraph.
- `_resolve_length` is lines 146–183: `--length` sets `args.panels = max(2, round(length / 2.0))` and
  `args.target_seconds = args.length`, and is mutually exclusive with `--panels`/`--target-seconds`.
- `_validate_story_md` (line 242) loads `bin/ltx-story-manifest` via `SourceFileLoader`, calls
  `_parse_prompts_md`, and requires a non-empty `Image`, `Motion`, **and** `Narration` for every panel.
- `phase3_manifest` (line 411) runs `bin/ltx-story-manifest` with `--glob 'panel_*.png' --images-dir
  <story>/images`, then `bin/ltx-story-video ... --mode per-panel --dry-run`.
- `_wait_for_avail` (line 459) is called **once**, at the top of `phase4_render` (line 524), before
  `bin/ltx-story-video` is launched. It is *not* a per-panel gate (see Section 11, correction C1).
- `_print_dry_run_plan` (line 557) prints, per phase, the exact command line it would run, plus the fully
  rendered story prompt.

**G2 — `bin/ltx-story-manifest` today.**
- `_PANEL_LABEL_RE = re.compile(r"^(Image|Motion|Narration):\s*(.*)$")` (line 66). `Prompt:` is not a
  recognized label; a `Prompt:` line today falls through to the "append to the currently open field" branch
  (line 202) or is dropped entirely when no field is open.
- `main()` requires exactly one of `--glob` / `--image` ("one of --glob or --image is required"), then
  Pillow-verifies every selected file, then requires `len(parsed_panels) == len(matched)`. **The panel list
  is derived from the matched image list** (`for i, image_path in enumerate(matched, start=1)`, line 374),
  so with zero images there are zero panels and the tool cannot run at all.
- `panel_text` is `pt["image"] or ("panel %d" % i)` and `motion_prompt` is `pt["motion"] or None` (lines
  379–380).

**G3 — `bin/ltx-story-video` today.**
- `load_manifest` **hard-requires** every panel's `image_path` to exist and be readable ("panel %d:
  image_path does not exist or is not readable"), and requires a non-empty `panel_text`.
- `build_units` (line 198) builds one unit per panel in `per-panel` mode with
  `conditions=[{image_path, frame_index: 0, strength: 1.0}]`, `seed = args.seed + i`, `label = "panel-%d" % i`,
  and `prompt = _resolve_motion_prompt(panel)` (`motion_prompt or panel_text`).
- `_build_request` (line 283) sets `"image_path": conditions[0]["image_path"]` — **it index-0s the
  conditions list**, so an empty `conditions` raises `IndexError` today.
- Step 4 runs `L._validate_geometry` and `L._check_ceiling(width, height, unit["num_frames"],
  unit["conditions"], False)` per unit before the host is touched. `_check_ceiling` computes
  `extra_conditions = sum(1 for c in conditions if c["frame_index"] != 0)` (`ltx_video_skill.py` line 318),
  which is `0` for an empty list — **an empty `conditions` list is safe here, no change needed**.
- Step 7 (`--dry-run`) prints one line per unit (`index | label | seed | frames | conditions | prompt`) plus
  a `TOTAL` line, and returns before any prep/screen/GPU work.
- The render loop spawns stages 1→2→3 per unit into `<run_root>/<label>/`, keys results on `unit["index"]`
  (never append order), treats a stage-3 content block as terminal regardless of `--on-unit-failure`, and
  supports `--on-unit-failure skip`, `--max-consecutive-failures`, `--retry-failed 1`, `--retry-idle`.
- `_await_gpu_reclaim()` runs before every unit's stage 1 and again before stage 2; `time.sleep(args.settle)`
  precedes stage 2. `L._release_page_cache(cell, request["image_path"], unit["prompt"], None)` runs after
  every unit's stage 1.
- It prints `run root: %s` at line 565.

**G4 — `bin/ltx-chain --continue-from` today (added in commit 37a64aa).**
- Continuation requires, in the base run dir: `embeds.pt`, at least one `frames/frame_*.png`, and a readable
  `request.json`. Missing any one is exit 2 with a specific message.
- `_CONTINUE_CHECKED_FIELDS` (line 144) is, verbatim:
  `["prompt", "negative_prompt", "width", "height", "num_frames", "fps", "frame_rate", "wide", "seed"]`.
  **`negative_prompt` is in this list** — the brainstormed enumeration in Section 3's decision D4 omitted it;
  D4's governing rule keeps it validated. `prompt` and `num_frames` are both removed from this list by D4
  and D7; every other entry stays. See Section 6.1.
- `_continue_settings_mismatch` compares each field of the base `request.json` against the corresponding
  `args` attribute and returns the **first** mismatch as an error string.
- In continuation mode the positional `image_path` is used only for existence validation/logging; the actual
  frame-0 conditioning image is `os.path.abspath(base_frames[-1])`.
- Continuation mode **skips stage 1** and copies the base's `embeds.pt` into every segment cell
  (`print("=== continuation mode: reusing base run embeds.pt (skipping stage 1) ===")` at line 329;
  `shutil.copyfile(base_embeds, os.path.join(cell, "embeds.pt"))` at line 369).
- Continuation mode **prepends the base run's frames** to the concatenated output
  (`all_frames = list(base_frames) if args.continue_from else []`), so its output mp4 is base+segments, not
  the new segment alone.
- Continuation mode **skips the ceiling pre-check**, printing "note: ceiling pre-check skipped (base
  generation already gated this geometry; mps_guard remains the backstop)".
- Segment `i` uses seed `args.seed + i` (`_segment_seed`).
- It prints `run root: %s` at line 325; its run root is `<WS>/generated/ltx_chains/<run_id>`.
- It has `--no-prep` and `--keep-down`, and `bin/ltx-generate` line 350 already nests it exactly this way:
  `bin/ltx-chain --continue-from "$BASE_RUN_DIR" --segments "$CHAIN" --no-prep --keep-down --force ...`.

**G5 — `ltx_video_skill.py` stage 2 rejects a prompt/embeds mismatch.** Line 470 loads `embeds.pt` and lines
471–487 raise `RuntimeError("stale embeds.pt: it was encoded for prompt=%r negative_prompt=%r but
request.json now asks for prompt=%r negative_prompt=%r")` when `data["meta"]["prompt"] != request["prompt"]`
or the negative prompts differ. **Consequence, load-bearing for this whole design:** relaxing
`_continue_settings_mismatch` alone is *not* sufficient to let a continuation use a new prompt — the
continuation would still die in stage 2 on stale embeds, because continuation mode reuses the base's
`embeds.pt` (G4). Section 6.2 is therefore mandatory, not optional.

**G6 — `ltx_video_skill.py` T2V path.** `mode == "t2v"` (line 512) calls the same `LTXConditionPipeline`
with `conditions=None`, `prompt=None`, and the four embed/mask tensors; `conditions=[]` (an empty list) is
documented in-source as **incorrect** and must never be passed to the pipeline. A fresh run's `request.json`
(lines 908–934) records `"image_path": None`, `"mode": "t2v" if image_path is None else "i2v"`, and
`"conditions": []` for T2V. Stage 2 writes `frames/frame_%05d.png` (line 586) — the same naming
`bin/ltx-chain`'s `frames/frame_*.png` glob expects. `_release_page_cache` already handles
`image_path is None` (line 702, the `--t2v --resume` hint branch). `_check_ceiling` is called with
`conditions=[]` for T2V and, per G3, tolerates it.

**G7 — what `mode` a request without the key gets.** `_stage2_denoise` reads `request.get("mode", "i2v")`
(line 511). `bin/ltx-story-video::_build_request` and `bin/ltx-chain::_build_request` both omit `mode`
today, so every request they write is treated as `i2v`. Openers must therefore write `"mode": "t2v"`
explicitly (Section 5.3).

---

## 1. Purpose, scope, and success criteria

### 1.1 Purpose

Add a rendering mode to the narrative-to-movie pipeline that goes from story text to video **without ever
generating a still image as an intermediate anchor frame**. The first shot of each "chain group" is produced
by LTX-Video's native text-to-video path; every later shot in the group is produced by I2V last-frame
chaining from the shot before it. Groups are re-anchored (a fresh T2V restart) every `--reanchor-every`
panels to bound accumulated visual drift (Section 7).

### 1.2 Scope

**In scope:** `--no-stills` on `bin/ltx-movie`; a collapsed `Prompt:` story field; a no-images manifest
source; `--engine chain` + `--reanchor-every` on `bin/ltx-story-video`; the `bin/ltx-chain` prompt-match
relaxation and its mandatory companion re-encode (Section 6.2); dry-run visibility of group structure.

**Explicitly out of scope:**
- `--engine chain` combined with `--mode transitions`. Rejected at parse time (Section 5.1); the transitions
  engine needs two panel images per unit by construction.
- Any automated drift metric or drift-scoring artifact. Drift severity is judged by watching real output
  (Section 7).
- Audio, narration TTS, subtitles.
- Changing the frame allocator, the manifest schema version, the `n = 1 + 8k` lattice, or any `mps_guard`
  gate or constant.
- Cross-group visual continuity. A group boundary is a hard cut, by design.
- Removing or reworking `bin/ltx-story-images` or the still-based path in any way.
- Making the `WS` constant consistent between the two workspace copies.

### 1.3 Success criteria

The feature is correct and complete when all of the following hold:

1. **Zero behavior change without the new flags.** `bin/ltx-story-video` invoked exactly as today (no
   `--engine`) produces byte-identical unit lists, request shapes, run-dir layout, `story_summary.json`
   fields, log lines, and exit codes. `bin/ltx-movie` without `--no-stills` runs all four phases exactly as
   today, including the unchanged `STORY_PROMPT_TEMPLATE`. `bin/ltx-generate --chain N` (which nests
   `ltx-chain --continue-from` with a prompt identical to the base's) behaves exactly as today, including
   still skipping stage 1.
2. **`--no-stills` never invokes `bin/ltx-story-images`.** Verified by the Section 9.1 dry-run test: the
   printed plan contains no `ltx-story-images` command, and `phase2_stills` is not called.
3. **Story authoring emits the collapsed field.** With `--no-stills`, `story.md` panels carry exactly
   `Prompt:` and `Narration:`; `_validate_story_md` requires both non-empty and does not require
   `Image:`/`Motion:`.
4. **Manifest.** `bin/ltx-story-manifest --no-images --prompts-md <story.md>` writes a `schema_version: 2`
   manifest whose panel count equals the story's panel count, whose `image_path` is `null` for every panel,
   whose `panel_text` and `motion_prompt` both equal that panel's collapsed `Prompt:` text, and whose
   `num_frames` values are exactly what the unchanged allocator produces for the same narration word counts
   (bit-identical to what the still-based path would have produced for the same `story.md` narrations).
5. **Grouping.** For `N` panels and `--reanchor-every R`, panel index `i` (1-based) is an **opener** iff
   `(i - 1) % R == 0`, and a **follower** otherwise. 15 panels at `R=5` gives openers `{1, 6, 11}`. A final
   short group (1 or 2 panels) is normal, never an error.
6. **Openers render via T2V.** An opener's request has `"mode": "t2v"`, `"image_path": null`,
   `"conditions": []`, and the panel's own `motion_prompt` and `num_frames`.
7. **Followers render via chaining on their own prompt.** A follower's generated frames are conditioned at
   frame 0 on the immediately preceding panel's last generated frame, and the text embeddings actually used
   for that generation encode the **follower's own** `motion_prompt` — not the opener's. (Proven by the
   absence of any "stale embeds.pt" failure plus the follower's `request.json`/`embeds.pt` meta agreeing on
   the follower's prompt.)
8. **Output shape is engine-agnostic.** Each panel's frames land in `<run_root>/panel-<i>/frames/frame_*.png`
   regardless of engine, and `build_frame_sequence` / `_concat_and_export` are called with the same
   arguments they would receive from the per-panel engine. No concat-side code inspects the engine.
9. **Dry run shows the plan.** `--engine chain --dry-run` prints, per panel, whether it is an opener (T2V) or
   a follower (chain, naming the panel it continues from), plus the group membership, plus the unchanged
   frame-allocation and `TOTAL` lines. It touches no server, no GPU, and no model.
10. **A real end-to-end run completes.** One `bin/ltx-movie --no-stills --length <10..20>` run produces a
    playable `movie.mp4` covering at least one full group plus one follower, with
    `completed_units == requested_units` in `story_summary.json`.
11. **Offline tests pass.** `python3 tests/test_ltx_movie_offline.py`, `tests/test_ltx_story_video.py`,
    `tests/test_ltx_chain.py`, `tests/test_ltx_t2v_offline.py`, `tests/check_ltx_no_forbidden_calls.py`,
    `tests/check_ltx_no_grad.py`, and `tests/check_ltx_safety_gate.py` all pass.
12. **Followers keep their own allocated length.** A follower whose `num_frames` differs from its
    predecessor's renders at its **own** `num_frames` (D7): the run does not abort, nothing is coerced, and
    the panel's frame count in `story_summary.json`'s `unit_frames` equals the manifest's `num_frames` for
    that panel. The movie's `actual_total_frames` therefore equals the manifest's `total_num_frames` when
    every unit completes, exactly as in the per-panel engine.

---

## 2. Invariants

- **I1. Strictly additive.** Every new code path is entered only via `--no-stills` (`ltx-movie`) or
  `--engine chain` (`ltx-story-video`). Both default off. No existing default changes value.
- **I2. Allocation is untouched.** `_snap_frames`, `_allocate_frames`, the `sum(f) ≡ N (mod 8)` invariant,
  and the `[--min-frames, --max-frames]` envelope behave exactly as in [NMP §3]. `--panels`,
  `--target-seconds`, and `--length` resolve scene count and total duration exactly as today; `--no-stills`
  changes only *how* a panel is rendered, never *how many* panels exist or *how long* the movie is.
- **I3. Safety gates unchanged.** `mps_guard` gates and constants, the stage-2 watermark cap, the sentinel,
  the per-unit `_check_ceiling`/`_validate_geometry` pre-check, and the stage-3 generated-frame content
  screen are all unchanged and still run for every opener and every follower. A stage-3 content block stays
  terminal for the whole run regardless of `--on-unit-failure`.
- **I4. One host prep per run.** `bin/ltx-story-video` remains the only process that preps and restores the
  host in a `--no-stills` run. Any nested `bin/ltx-chain` invocation runs with `--no-prep --keep-down`
  (Section 5.4), matching the precedent at `bin/ltx-generate` line 350.
- **I5. No new dependency.** Standard library plus the already-imported `psutil`, `PIL`, `torch`,
  `diffusers`. `bin/ltx-story-manifest` stays stdlib+Pillow and must not gain a torch/diffusers import;
  `bin/ltx-story-video` and `bin/ltx-chain` keep their existing "no torch in the parent process" property,
  so the new code must not import torch, diffusers, or `content_safety` at module scope.
- **I6. Schema version stays 2.** A `null` `image_path` is a legal manifest-v2 panel value in this mode; no
  `schema_version: 3` is introduced. Manifests with non-null `image_path` keep validating exactly as today.
- **I7. Ordering safety.** The chain engine reuses the existing `unit_frames_by_index` dict keyed on
  `unit["index"]` and the existing order-safe concat rebuild. No list-append ordering is introduced.

---

## 3. Approved decisions (normative)

Recorded verbatim in substance from the approved brainstorm. Where an approved statement needed a factual
correction against the source, the correction is in Section 11 and the corrected form is what governs.

- **D1.** `bin/ltx-movie` gains `--no-stills`. When set: Phase 1 uses the alternate prompt template with a
  collapsed `Prompt:` field (merging today's `Image:` and `Motion:` fields into one field describing the
  shot's content, setting, and motion together); `Narration:` is unchanged; the recurring-character
  verbatim-repetition rule still applies, now to the collapsed `Prompt:` field. Phase 2 is skipped entirely
  — `bin/ltx-story-images` is not called at all. Phase 3 runs as today with the same allocator, but the
  panel parser accepts `Prompt:` as an alternate to `Image:`/`Motion:`, writing it into `motion_prompt` with
  `image_path` null for that panel. Phase 4 is invoked with `--engine chain` and `--reanchor-every N`
  threaded through.
- **D2.** `bin/ltx-story-video` gains `--engine {per-panel,chain}`, default `per-panel`, and
  `--reanchor-every N`, default `5` (meaningful only with `--engine chain`).
- **D3.** Chain-engine mechanics. Panels are walked in groups of `--reanchor-every`. The group's first panel
  (the **opener**) is generated by pure text-to-video using that panel's `motion_prompt` and its allocated
  `num_frames`. Each later panel in the group (a **follower**) is generated by
  `bin/ltx-chain --continue-from <previous panel's run dir> --segments 1` using the **follower's own**
  `motion_prompt`. The next group's opener always starts a fresh T2V generation and deliberately does not
  continue visual continuity from the prior group's last panel; that cut is the drift-control mechanism.
  Each panel's output is written as its own clip in the same output shape/naming `bin/ltx-story-video`
  already uses per panel; the downstream concatenation is unaware of which engine produced each clip.
  Groups need not divide evenly — a final short group is fine.
- **D4.** `bin/ltx-chain::_continue_settings_mismatch` no longer requires the continuation's prompt to equal
  the base run's `request.json` prompt. This is what allows each follower panel to describe new narrative
  content while still visually continuing from the previous panel's last frame. See D7, which removes a
  second field from the same check.
- **D5.** `--panels`, `--target-seconds`, and `--length` are unchanged and orthogonal to `--no-stills`.
- **D6.** No automated drift metric is built. Judging drift severity from real output is the intended
  method, not a gap to fill.
- **D7 (2026-09-04, resolving the `num_frames` conflict).** `_continue_settings_mismatch` **also** no longer
  requires the continuation's `num_frames` to equal the base run's. `prompt` and `num_frames` are the only
  two fields removed; `negative_prompt`, `width`, `height`, `fps`, `frame_rate`, `wide`, and `seed` remain
  validated and remain hard errors on mismatch (Section 8). Rationale: this preserves the
  narration-proportional frame allocator **exactly as today for every panel, including followers inside a
  chain group** — a follower keeps its own allocated length instead of being forced to its predecessor's.
  Chaining conditions visually on the previous segment's last frame only; it is **not** being assumed to
  carry any hard technical dependency on matching segment lengths. The residual risk — that generation may
  behave incorrectly when the lengths differ — is unverified and tracked as OQ2, to be closed as an early
  implementation step.
- **D8 (added scope, required companion changes).** Two changes are necessary consequences of D1–D7 rather
  than fresh decisions, and are in scope: the **forced stage-1 re-encode** when a continuation's prompt
  differs from its base's (Section 6.2, Section 12.1 A1), and the **`--no-stills` precondition fixes** in
  `bin/ltx-story-manifest` and `bin/ltx-story-video` (Section 12.1 A2).

---

## 4. `bin/ltx-movie` — `--no-stills`

### 4.1 New flags

| Flag | Type | Default | Behavior |
| --- | --- | --- | --- |
| `--no-stills` | `store_true` | `False` | Enables the text-to-video chain mode described in this spec. |
| `--reanchor-every N` | `int` | `5` | Threaded to `bin/ltx-story-video --reanchor-every N`. Requires `--no-stills`. |

Validation, added in `main()` after `_resolve_length(args, raw_argv)` and using the existing
`_flag_explicit(raw_argv, ...)` helper (same style as the `--length` conflict checks):

- `--reanchor-every` explicitly given without `--no-stills` → print to stderr, verbatim:
  `Error: --reanchor-every requires --no-stills (it only applies to the chain engine)` and `sys.exit(2)`.
- `--reanchor-every` given a value `< 1` → print `Error: --reanchor-every must be >= 1, got %d` and
  `sys.exit(2)`.
- `--no-stills` has **no interaction** with `--panels`, `--target-seconds`, `--length`, `--force-story`,
  `--force`, `--no-review`, or `--dry-run`. They are fully orthogonal; do not add any cross-check between
  them.
- `--image-width`, `--image-height`, `--image-seed` are accepted and ignored under `--no-stills` (Phase 2
  never runs). Do not error, and do not print a warning: they are already defaulted flags and silence keeps
  scripted invocations working.

### 4.2 Alternate story-prompt template

Add a module-level constant `STORY_PROMPT_TEMPLATE_NO_STILLS` immediately after the existing
`STORY_PROMPT_TEMPLATE` (which is unchanged), with exactly this text:

```
You are authoring the shot list for a short narrated movie (story-id "{story_id}").

Narrative to adapt:
{narrative}

Write the complete story to generated/stories/{story_id}/story.md using the write_file tool. The file must contain EXACTLY {panels} panel sections, numbered 1 through {panels} in order, each in exactly this format:

## Panel N — <short title>
Prompt: <a single video prompt, 85-130 words, describing the shot's visual content, setting, lighting, lens/shot choice, AND the camera motion and subject motion within the shot, together in one continuous description -- no new plot information beyond what this shot shows>
Narration: <one sentence of voice-over narration; vary the sentence length across panels rather than repeating a similar length every time>

The FIRST time a recurring character (or other recurring visual element) appears, write out their full visual description in the Prompt: field. Every later panel in which that same character appears must repeat that exact description VERBATIM -- word for word, not paraphrased -- so the character stays visually consistent across panels.

Do not emit an Image: or Motion: field. Do not verify the file with run_python or any other tool. Emit no other text.
```

`build_story_prompt` gains a third parameter: `build_story_prompt(narrative, story_id, panels,
no_stills=False)`, selecting `STORY_PROMPT_TEMPLATE_NO_STILLS` when `no_stills` is true and
`STORY_PROMPT_TEMPLATE` otherwise, with the same `.format(narrative=..., story_id=..., panels=...)` call.
Existing three-argument callers keep working unchanged.

The `85-130` word range is the sum of the two ranges being merged (70–90 plus 15–40), floored/capped to a
single band, and is deliberately kept under the 150-word threshold that both
`bin/ltx-story-manifest::_prompt_length_warning` and `bin/ltx-story-video`'s step-6 check warn at.

`_phase1_max_tokens(panels)` and `_phase1_timeout(panels)` are unchanged (`max(4096, panels * 350)` and
`max(900, panels * 60)`); the collapsed field is not longer than the two it replaces.

### 4.3 `_validate_story_md`

Signature becomes `_validate_story_md(story_md_path, expected_panels, no_stills=False)`. The panel-count
check is unchanged. The per-panel field check becomes:

- `no_stills=False` (today's path, unchanged): require non-empty `Image`, `Motion`, `Narration`.
- `no_stills=True`: require non-empty `Prompt` and `Narration`. Additionally, if a panel has a non-empty
  `Prompt` **and** a non-empty `Image` or `Motion`, append the violation
  `panel %d: has both Prompt: and Image:/Motion: fields; --no-stills expects Prompt: only`.

Violation strings keep the existing `"panel %d: missing/empty %s: field"` format, and the existing
"Hand-edit ... and rerun" hint text is unchanged.

### 4.4 Phase sequencing

`main()`'s phase loop currently iterates
`(phase1_story, phase2_stills, phase3_manifest, phase4_render)`. Under `--no-stills` it iterates
`(phase1_story, phase3_manifest, phase4_render)`. Build the tuple conditionally; do not add a
"skip" early-return inside `phase2_stills`, so that the tool's own log never contains a Phase-2 banner in
this mode.

`phase3_manifest`, under `--no-stills`:
- `cmd_manifest` replaces `--glob 'panel_*.png' --images-dir <story>/images` with `--no-images`. Every other
  argument (`--story-id`, `--prompts-md`, `--fps`, `--target-seconds`, `--min-frames`, `--max-frames`,
  `--force`) is unchanged and in the same order.
- `cmd_dryrun` gains `--engine chain --reanchor-every <N>` after `--mode per-panel`, keeping `--dry-run`
  last.

`phase4_render`, under `--no-stills`: the command gains `--engine chain --reanchor-every <N>` immediately
after `--mode per-panel`. Everything else (`--on-unit-failure skip --retry-failed 1 --retry-idle 120
--max-consecutive-failures 3`, plus `--force` when set) is unchanged. `_wait_for_avail` is still called once
before launch, with the same `--min-avail-gib`/`--avail-timeout` semantics.

### 4.5 `--dry-run` plan output

`_print_dry_run_plan` under `--no-stills`:
- The `--- Phase 1: story ---` block prints the rendered **no-stills** prompt.
- The `--- Phase 2: stills ---` block is replaced by exactly one line:
  `--- Phase 2: stills --- SKIPPED (--no-stills: no anchor stills are generated)`.
- The Phase 3 and Phase 4 blocks print the commands including `--no-images` and
  `--engine chain --reanchor-every N` respectively.
- `--dry-run` still never shells out to any wrapped tool, so the per-panel opener/follower table
  (Section 5.6) is *not* printed here; it comes from `bin/ltx-story-video --dry-run` during a real Phase 3.

---

## 5. `bin/ltx-story-video` — the chain engine

### 5.1 New flags and validation

| Flag | Type | Default | Behavior |
| --- | --- | --- | --- |
| `--engine` | `choices=["per-panel", "chain"]` | `"per-panel"` | `per-panel` is today's engine, bit-for-bit. `chain` selects the T2V+chaining engine. |
| `--reanchor-every` | `int` | `5` | Group size for `--engine chain`. Ignored (not an error) under `--engine per-panel`. |

Validation, added immediately after `parser.parse_args`:

- `--engine chain` with `--mode transitions` → `parser.error("--engine chain requires --mode per-panel "
  "(the transitions engine needs a panel image per unit)")`.
- `--reanchor-every < 1` → `parser.error("--reanchor-every must be >= 1")`.

The asymmetry with Section 4.1 is deliberate, not an inconsistency: `bin/ltx-movie` **rejects** an explicit
`--reanchor-every` without `--no-stills` (it is an operator-facing wrapper, and a silently ignored flag there
would hide a typo'd intent), while `bin/ltx-story-video` **ignores** it under `--engine per-panel` (it is
the machine-facing tool, and the wrapper always passes the pair together). Implement both as written.

### 5.2 Manifest validation with null `image_path`

`load_manifest` gains a keyword parameter: `load_manifest(path, allow_null_image_path=False)`. `main()`
calls it with `allow_null_image_path=(args.engine == "chain")`.

- `allow_null_image_path=False`: unchanged. Every panel's `image_path` must exist and be readable.
- `allow_null_image_path=True`: a panel whose `image_path` is `None` or absent is accepted and normalized to
  `None`. A panel whose `image_path` is a non-empty string is still fully validated (must exist, must be
  readable) with today's exact error message — a mixed manifest is legal and the string paths are still
  checked. Every other check (contiguous 1-based `index`, non-empty `panel_text`, and for
  `schema_version >= 2` the positive `(num_frames - 1) % 8 == 0` `num_frames`) is unchanged.

Under `--engine chain`, `image_path` is never read for conditioning: openers condition on nothing and
followers condition on the previous panel's generated frame. A non-null `image_path` in a chain-engine
manifest is therefore ignored for rendering, which is intentional and requires no warning.

### 5.3 Unit construction

`build_units` gains two keyword parameters: `build_units(panels, mode, num_frames, seed, engine="per-panel",
reanchor_every=5)`. For `engine == "per-panel"` the function body is untouched.

For `engine == "chain"` (which implies `mode == "per-panel"` per Section 5.1), for each panel at 1-based
index `i`:

```python
{
  "index": i,
  "label": "panel-%d" % i,
  "seed": seed + i,
  "prompt": _resolve_motion_prompt(panel),          # unchanged helper: motion_prompt or panel_text
  "num_frames": panel.get("num_frames") or num_frames,
  "conditions": [],                                  # always empty in this engine
  "role": "opener" if (i - 1) % reanchor_every == 0 else "follower",
  "group": (i - 1) // reanchor_every + 1,            # 1-based group number
  "continue_from_index": None if (i - 1) % reanchor_every == 0 else i - 1,
}
```

`label`, `seed`, `prompt`, and `num_frames` are computed exactly as the per-panel engine computes them, so a
chain-engine run and a per-panel run over the same manifest produce identical labels, seeds, prompts, and
frame counts. `conditions` is empty for **both** roles: an opener has no conditioning image at all, and a
follower's conditioning image is a *generated* frame path that does not exist until the previous panel
finishes, so it can never be part of the statically built unit list. `role`, `group`, and
`continue_from_index` are new keys present only in this engine.

Steps 4–6 of `main()` are unchanged and require no engine branch: `_validate_geometry` is per-unit;
`_check_ceiling(..., unit["conditions"], False)` tolerates the empty list (G3); the total-frame cap and the
prompt-length warnings read only `num_frames` and `prompt`.

**Opener request shape.** `_build_request` gains a keyword parameter `mode_field=None` and builds
`"image_path"` defensively:

```python
"image_path": conditions[0]["image_path"] if conditions else None,
```

and includes `"mode": mode_field` only when `mode_field is not None`. Openers are built with
`mode_field="t2v"`, producing `{"image_path": None, "mode": "t2v", "conditions": [], ...}` with every other
field as today. Per-panel-engine and transitions-engine requests pass `mode_field=None` and are therefore
byte-identical to today's (no `mode` key at all → `request.get("mode", "i2v")` → `i2v`, per G7).

### 5.4 Rendering an opener

Openers are rendered by the **existing** in-process loop, unchanged: `_await_gpu_reclaim()` → `_spawn_stage(1,
cell)` → `L._release_page_cache(cell, request["image_path"], unit["prompt"], None)` (safe with
`image_path=None`, per G6) → `_await_gpu_reclaim()` → `time.sleep(args.settle)` → `_spawn_stage(2, cell,
stage2_env)` → `_spawn_stage(3, cell)`. The cell is `<run_root>/panel-<i>/` and frames land in
`<run_root>/panel-<i>/frames/frame_*.png`. All failure handling (`stage1_error`, `sentinel_abort`,
`stage2_error`, `stage3_error`, `content_blocked`), `--on-unit-failure`,
`--max-consecutive-failures`, `_unit_boundary_pause`, and the `--retry-failed 1` retry pass apply
unchanged. **No new failure mode is introduced for openers.**

The only difference from a per-panel unit is the request content (Section 5.3), which the stages already
handle: `mode == "t2v"` selects `ltx_video_skill.py`'s T2V branch (G6).

### 5.5 Rendering a follower

A follower is rendered by a nested `bin/ltx-chain` subprocess. Preconditions, all checked before spawning:

1. The panel at `continue_from_index` completed successfully in this run (its index is in
   `unit_frames_by_index`). If it did not — which can only happen under `--on-unit-failure skip`, when the
   predecessor failed — the follower is **not attempted**: record
   `{"unit": label, "status": "skipped_no_base", "base": "panel-<k>"}` in `unit_results`, print
   `unit %s SKIPPED (chain base panel-%d did not complete)`, increment `consecutive_failures`, honor
   `--on-unit-failure`/`--max-consecutive-failures` exactly as any other per-unit failure does, and continue.
   A `skipped_no_base` follower is eligible for the retry pass only if its base completed by then; otherwise
   it is skipped again with the same status.
2. `base_run_dir = <run_root>/panel-<continue_from_index>` contains `embeds.pt`, `request.json`, and at least
   one `frames/frame_*.png`. All three are written by the predecessor's own stages, so their absence is a
   code bug — see Section 8, row 4.

Invocation (argument order exactly as written; `<base_seed>` is the predecessor unit's `seed`, i.e.
`args.seed + continue_from_index`):

```
python3 <WS>/bin/ltx-chain \
    --continue-from <base_run_dir> \
    --segments 1 \
    --no-prep --keep-down --force \
    --width <args.width> --height <args.height> \
    --num-frames <this unit's num_frames> \
    --fps <args.fps> --frame-rate <args.frame_rate> \
    --seed <base_seed> \
    --settle <args.settle> \
    --negative-prompt <args.negative_prompt> \
    [--wide] [--allow-override] [--relax-supply] \
    <base_run_dir>/frames/<last frame basename> \
    <this unit's prompt> \
    <run_root>/panel-<i>/_chain_scratch.mp4
```

Rationale for each non-obvious argument, all forced by G4:

- `--no-prep --keep-down`: `bin/ltx-story-video` already prepped the host and owns the restore in its own
  `try/finally`. Without these, the nested `ltx-chain` would run `bin/ltx-host-prep` again and, on exit, run
  `bin/ltx-host-restore` — bringing the vLLM servers **back up in the middle of the render**. This is the
  same pairing `bin/ltx-generate` line 350 already uses for nested chaining (I4).
- `--force`: `_chain_scratch.mp4` may exist from a retry attempt.
- `--num-frames <this unit's num_frames>`: the follower's **own** allocated length, which will normally
  differ from the predecessor's. This is legal because D7 removes `num_frames` from the validated set; the
  follower keeps its narration-proportional length and is never coerced to its predecessor's (Section 6.1,
  Section 6.3).
- `--seed <base_seed>`: `seed` is still validated against the base request (D4/D7), and `ltx-chain` then uses
  `base_seed + 1` for its single segment — which equals `args.seed + i`, i.e. exactly the seed the per-panel
  engine would have used for panel `i`. This is a coincidence of the two seed conventions and is load-bearing;
  do not "simplify" it by passing `args.seed + i`, which would fail the base-seed match.
- The positional `image_path`: `ltx-chain` requires this path to exist even though continuation mode ignores
  it for conditioning (G4). Passing the predecessor's last frame — the very image continuation mode will use
  — keeps the log honest and the check satisfied.
- `--negative-prompt`: passed explicitly because `negative_prompt` remains a validated match field (D4/G4).
- `_chain_scratch.mp4` is a throwaway. `ltx-chain` writes base+segment frames into it (G4); the file is
  **deleted immediately after the frames are harvested**, on both the success and failure paths.

**Frame harvest.** Capture the child's stdout (`subprocess.run(..., stdout=PIPE, stderr=STDOUT, text=True)`),
echo it to this process's stdout, and parse the **last** line whose stripped form starts with `run root: `
to get the chain run root. Then the follower's frames are
`sorted(glob.glob(os.path.join(chain_run_root, "seg1", "frames", "frame_*.png")))`.

Only `seg1`'s frames are used. `ltx-chain`'s own concatenated mp4 prepends the base run's frames (G4) and
must never be treated as this panel's clip — using it would duplicate the predecessor's frames in the movie.

These harvested paths are stored in `unit_frames_by_index[unit["index"]]` exactly like an in-process unit's
frames, so `build_frame_sequence` and `_concat_and_export` see one flat list of PNG paths per panel and
remain completely engine-unaware (criterion 8). The frames stay where `ltx-chain` wrote them
(`<WS>/generated/ltx_chains/<chain_run_id>/seg1/frames/`); do not copy or move them. Record the chain run
root in that unit's result dict as `"chain_run_root": <path>` so the movie's provenance is traceable from
`story_summary.json`.

**Follower outcome mapping.** From the child's exit code and stdout:

| Child signal | `unit_results[...]["status"]` | Run-level effect |
| --- | --- | --- |
| rc 0 and `seg1` frames count == unit `num_frames` | `"ok"` | `completed += 1`, `consecutive_failures = 0` |
| stdout contains `BLOCKED by content safety` | `"content_blocked"` | terminal for the whole run, exactly as an in-process block: set `content_blocked = True` and `break` |
| rc != 0, or rc 0 with a frame count != `num_frames` | `"chain_error"` with `"rc"` and the last 40 stdout lines written to `<run_root>/panel-<i>/chain.log` | counts as a unit failure: honor `--on-unit-failure`, `--max-consecutive-failures`, and eligibility for the `--retry-failed 1` pass |
| child stdout has no `run root: ` line | `"chain_error"` with reason `"could not determine chain run root from ltx-chain output"` | same as `chain_error` |
| one of the seven still-validated settings mismatched (`negative_prompt`, `width`, `height`, `fps`, `frame_rate`, `wide`, `seed`) | hard abort — see the "still-validated settings" row of Section 8 | run stops immediately |
| the follower's `num_frames` differs from its base's | **not a signal at all** — no longer validated (D7); the follower simply renders at its own length | none |

`_unit_boundary_pause(args.unit_pause)` runs after a follower exactly as after an in-process unit. A
follower's retry in the `--retry-failed` pass re-runs the whole nested `ltx-chain` invocation from scratch
(there is no partial state to reuse); delete `_chain_scratch.mp4` first.

### 5.6 `--dry-run` output

Under `--engine chain`, step 7's dry-run block prints the same header and `TOTAL` line, with the per-unit
line extended to name the role and the base, and a group header before each group's first panel:

```
=== dry run: 12 unit(s), mode=per-panel, engine=chain, reanchor-every=5 ===
--- group 1 (panels 1-5) ---
1 | panel-1 | seed=1 | frames=41 (1.71s) | T2V opener | prompt='...'
2 | panel-2 | seed=2 | frames=33 (1.38s) | chain follower <- panel-1 | prompt='...'
3 | panel-3 | seed=3 | frames=49 (2.04s) | chain follower <- panel-2 | prompt='...'
4 | panel-4 | seed=4 | frames=41 (1.71s) | chain follower <- panel-3 | prompt='...'
5 | panel-5 | seed=5 | frames=33 (1.38s) | chain follower <- panel-4 | prompt='...'
--- group 2 (panels 6-10) ---
...
--- group 3 (panels 11-12) ---
11 | panel-11 | seed=11 | frames=41 (1.71s) | T2V opener | prompt='...'
12 | panel-12 | seed=12 | frames=33 (1.38s) | chain follower <- panel-11 | prompt='...'
TOTAL 480 frames, 20.00s
```

`prompt` is truncated to 120 characters, as today. The `conditions=[...]` field is dropped from the line in
this engine (it is always empty and would be noise); under `--engine per-panel` the dry-run line is
unchanged, including the `conditions=[...]` field and the `=== dry run: %d unit(s), mode=%s ===` header.

The group header's panel range is `min(group panels)`–`max(group panels)`, so a short final group prints its
real, shorter range (criterion 5).

### 5.7 `story_summary.json`

Same `schema_version: 2` summary object, with three added keys and no removed or renamed keys:

- `"engine"`: `"per-panel"` or `"chain"`.
- `"reanchor_every"`: the integer in effect, or `null` under `--engine per-panel`.
- `"groups"`: under `--engine chain`, a list of `{"group": int, "panels": [int, ...], "opener": int}`;
  `null` under `--engine per-panel`.

Per-unit result dicts for followers additionally carry `"chain_run_root"` (Section 5.5). Existing keys and
their meanings are unchanged, so `bin/ltx-movie::_report_summary` needs no change.

---

## 6. `bin/ltx-chain` changes

### 6.1 Drop the `prompt` and `num_frames` equality checks (D4 + D7)

Remove `"prompt"` **and** `"num_frames"` from `_CONTINUE_CHECKED_FIELDS` (line 144), leaving, verbatim:

```python
_CONTINUE_CHECKED_FIELDS = [
    "negative_prompt", "width", "height", "fps",
    "frame_rate", "wide", "seed",
]
```

These seven remaining fields are the complete "must match, hard error on mismatch" set. `prompt` and
`num_frames` are the complete set of dropped fields. No other field is added or removed.

`_continue_settings_mismatch`'s body, error-message format, and first-mismatch-wins behavior are unchanged.
Update its docstring: the parenthetical list of matched settings drops `prompt` and `num_frames` and gains
these two sentences: "The prompt is deliberately NOT matched: a continuation is allowed to describe new
narrative content while still continuing visually from the base's last frame. num_frames is deliberately NOT
matched either: a continuation is allowed its own length, because chaining conditions only on the base's last
frame and carries no dependency on matching segment lengths (see
docs/specs/2026-09-04-ltx-text-to-video-chain-pipeline-design.md Section 6 and D7)."

Update the `--continue-from` help text's "The positional image_path is used only for validation/logging in
this mode." sentence to also state that the positional `prompt` is now the continuation's own prompt and need
not match the base's, and that `--num-frames` may differ from the base's.

`bin/ltx-generate --chain N` is unaffected by this change: it always passes a prompt identical to the base's,
so it always takes Section 6.2's identical-prompt branch and its behavior is unchanged.

### 6.2 Encode the continuation's own prompt when it differs (mandatory companion change)

Per G5, dropping the equality check alone would leave every follower dying in stage 2 with `stale
embeds.pt`, because continuation mode reuses the base's `embeds.pt`. Therefore, in continuation mode:

- If the requested `prompt` **equals** the base `request.json`'s `prompt`: behavior is exactly as today —
  skip stage 1, print `=== continuation mode: reusing base run embeds.pt (skipping stage 1) ===`, and copy
  the base `embeds.pt` into each segment cell. This is the path `bin/ltx-generate --chain N` takes, so that
  tool's behavior and its stage-1 saving are preserved bit-for-bit (criterion 1).
- If the requested `prompt` **differs** from the base's: run stage 1 for the requested prompt, using the same
  `_base` cell construction the fresh-chain path already uses (`os.makedirs(<run_root>/_base)`, write
  `_build_request(input_image, args.prompt, ...)`, `_spawn_stage(1, base)`, then
  `base_embeds = os.path.join(base, "embeds.pt")`), and copy those embeds into each segment cell. Print
  `=== continuation mode: prompt differs from base; encoding this continuation's own prompt (stage 1) ===`
  before it. A stage-1 failure here is handled exactly as the fresh-chain path handles it: write the tail to
  stderr and `raise RuntimeError("stage1 failed with exit code %d" % rc1)`.

The cost is one extra T5 encode per follower panel — the same per-unit stage-1 cost the existing per-panel
engine already pays for every unit (`bin/ltx-story-video`'s "Load-bearing per unit (not just once, unlike
ltx-chain)" comment), so this introduces no new memory regime and needs no new gate.

Everything else about continuation mode is unchanged: base-artifact existence checks, `input_image =
os.path.abspath(base_frames[-1])`, the skipped ceiling pre-check and its printed note, base-frame prepending
in the output mp4, `chain_summary.json`, and the exit-code contract.

**C6 correction:** `bin/ltx-chain` had no `L._release_page_cache(...)` call anywhere before this task
(`git show HEAD:qwen-agent-workspace/bin/ltx-chain | grep -n "_release_page_cache"` returns nothing). The
differing-prompt branch above adds one, immediately after its stage-1 `_spawn_stage(1, base)` call succeeds:
`L._release_page_cache(base, None, args.prompt, None)`. This is load-bearing for the same reason
`bin/ltx-story-video` already calls it after every unit's stage 1 (that script's own "Load-bearing per unit
(not just once, unlike ltx-chain)" comment, `bin/ltx-story-video` lines 620-623 and 737-738): stage 1 mmaps
~18 GiB of T5 shards, which depresses `psutil.virtual_memory().available` and can fail stage 2's G1b gate
(`mps_guard._supply_gate_ok`, `mps_guard.py` line 317) — that gate refuses if *either* the `avail_gib` arm or
the `supply_gib` arm falls short of `required_gib` (a conjunction of both metrics, not either alone; see the
function's own docstring and inline comment on the `or`). The call is placed in the `else` branch of `if
args.continue_from and args.prompt == base_request_dict["prompt"]:` inside `bin/ltx-chain`'s step-5 block, and
that `else` branch is reached in two situations: (a) a fresh chain with no `--continue-from` at all, and (b) a
continuation whose prompt differs from the base's. Consequently the release call fires for every stage-1
encode in that block, not just the continuation case. This is intentional: on the fresh-chain path the extra
purge is harmless (the prior `bin/ltx-host-prep` `sudo purge` already evicted the pages), while on the
continuation path (typically invoked with `--no-prep`) it is strictly required, because nothing else evicts
those pages before this continuation's own stage 2 runs.

This broader-than-originally-described scope was found during the final whole-branch review (2026-09-05); the
broader scope was confirmed benign and deliberately kept as-is (not narrowed to gate on `--continue-from`),
because `bin/ltx-generate --chain N`'s same-prompt path never reaches this `else` branch at all — it always
takes the other branch, reusing the base's `embeds.pt` — and is therefore provably unaffected by this call's
placement.

### 6.3 Geometry gating after D7

Once a continuation may carry its own `num_frames`, continuation mode's "the base already gated this
geometry" justification for skipping `L._check_ceiling` no longer strictly holds — a continuation asking for
*more* frames than its base was never gated by the base's pre-check. Two facts make this safe for this
design, and both must be preserved:

1. `bin/ltx-chain`'s step-1 `L._validate_geometry(args.width, args.height, args.num_frames)` runs
   unconditionally, in continuation mode too, so the `n = 1 + 8k` lattice and the resolution constraints are
   still enforced for the continuation's own length.
2. `bin/ltx-story-video`'s step-4 pre-check already runs `L._check_ceiling(args.width, args.height,
   unit["num_frames"], unit["conditions"], False)` for **every** unit — openers and followers alike — before
   the host is touched (G3). In a `--no-stills` run, therefore, every follower's `num_frames` is
   ceiling-checked by the parent before any nested `ltx-chain` is spawned.

Do **not** add a ceiling pre-check to `bin/ltx-chain`'s continuation path (it would double-gate this
design's followers and change `bin/ltx-generate --chain N`'s behavior). Do **not** remove
`bin/ltx-story-video`'s step-4 per-unit check, which is what makes fact 2 true. `mps_guard`'s watermark cap
and sentinel remain the runtime backstop in all cases. A hand-run `bin/ltx-chain --continue-from` with a
larger `--num-frames` than its base is gated only by `mps_guard`, which is the same posture continuation
mode has today.

---

## 7. Drift control: why periodic re-anchoring

Chained I2V generation conditions each segment on the previous segment's *actual rendered* last frame, so
every segment inherits the previous segment's error. This accumulates: faces, proportions, and color balance
degrade visibly by roughly segment 8–10 of an unbroken chain.

Three mitigations were considered. Accepting unbounded drift was rejected (the tail of a long movie becomes
unusable). Hard-capping total chain length was rejected (it caps movie length, not drift). **Periodic
re-anchoring was chosen:** every `--reanchor-every` panels, the chain is abandoned and a fresh T2V generation
starts a new group. Because no chain is ever longer than `--reanchor-every` segments, accumulated drift can
never exceed what is observed *within* one group — drift becomes a bounded, tunable quantity instead of a
function of movie length.

The cost is a visible hard cut at each group boundary, since the new opener has no visual relationship to
the previous panel's last frame. That trade — visible cuts for bounded drift — is deliberate and accepted.
Per-shot visual consistency across a cut is carried by text alone: the recurring-character
verbatim-repetition rule in the `Prompt:` field (Section 4.2) is the only continuity mechanism across a group
boundary, which is exactly why that rule is retained in the collapsed field.

No automated drift metric is built (D6). `--reanchor-every` is tuned by watching real output and lowering it
if the end of a group looks degraded.

---

## 8. Error handling

| Case | Required behavior |
| --- | --- |
| Panels don't divide evenly by `--reanchor-every` | **Not an error.** The final group is simply shorter (1 or 2 panels is normal). The dry-run group header prints its real range. |
| Group opener (T2V) generation fails (stage 1/2/3 error, sentinel abort, OOM, timeout) | Exactly today's per-unit handling: status recorded, `--on-unit-failure` honored, `--max-consecutive-failures` counted, eligible for the `--retry-failed 1` pass. **No new failure mode.** |
| Follower generation fails for a non-validation reason (GPU error, OOM, timeout, nonzero `ltx-chain` exit) | Status `chain_error`; same `--on-unit-failure` / `--max-consecutive-failures` / retry-pass behavior as any per-panel failure today. |
| A follower's still-validated settings fail `_continue_settings_mismatch` — `negative_prompt`, `width`, `height`, `fps`, `frame_rate`, `wide`, `seed` (this is the complete list; `prompt` and `num_frames` are no longer validated, per D4/D7) | **Hard, loud, immediate abort of the whole run.** Print to stderr: `INTERNAL ERROR: chain follower panel-%d failed --continue-from settings validation against panel-%d: %s. Every panel in one run shares these settings by construction, so this is a code bug, not an operator error.` then set `stopped_reason = "chain_settings_mismatch"`, write `story_summary.json`, and return 1. **Never** add a fallback, a coercion, or a retry for this case. Detected by the child's exit code 2 together with `does not match requested` in its stdout. |
| A follower's `num_frames` differs from its predecessor's | **Normal and expected**, not an error: the narration-proportional allocator routinely produces different lengths for adjacent panels (D7). The follower renders at its own allocated length. No warning, no coercion, no note. |
| A follower's predecessor never completed (only reachable under `--on-unit-failure skip`) | Status `skipped_no_base`; counted as a unit failure; not attempted. See Section 5.5 precondition 1. |
| A follower's base run dir is missing `embeds.pt` / `request.json` / `frames/` | Same hard-abort treatment as the settings mismatch row, with `stopped_reason = "chain_base_incomplete"`: those artifacts are written by the predecessor's own stages, so their absence is a code bug. Detected by the child's exit code 2 together with `--continue-from run has no` in its stdout. |
| Content safety block on any generated frame, opener or follower | Terminal for the whole run, regardless of `--on-unit-failure` — the existing, never-skippable policy. For a follower, detected via `BLOCKED by content safety` in the nested `ltx-chain` stdout. |
| `--no-stills` with `--force-story` / `--force` / `--dry-run` | No special interaction. Fully orthogonal; add no cross-checks. |
| `--no-stills` `--dry-run` | Must show the Phase-2 skip and the Phase 3/4 commands with the new flags (Section 4.5). The opener/follower table comes from `bin/ltx-story-video --dry-run` (Section 5.6) so grouping can be sanity-checked before any GPU time is spent — same spirit as today's frame-allocation preview. |
| Memory / GPU gating | Unchanged in every respect (Section 11, C1): `_wait_for_avail` once per Phase-4 launch; `_await_gpu_reclaim` plus `mps_guard.preflight` per stage, for openers and followers alike. A nested `ltx-chain` follower runs the same `_await_gpu_reclaim` + `--settle` + `mps_guard` sequence inside its own segment loop. |
| `--no-images` manifest with a panel lacking `Prompt:` | `bin/ltx-story-manifest` exits 2: `Error: --no-images requires every panel to have a non-empty Prompt: field; panel %d has none`. |
| A panel with both `Prompt:` and `Image:`/`Motion:` | `bin/ltx-story-manifest` exits 2: `Error: panel %d has both a Prompt: field and an Image:/Motion: field; use one form or the other`. `bin/ltx-movie::_validate_story_md` reports the same condition as a violation (Section 4.3) so it is caught in Phase 1, before Phase 3. |

---

## 9. Testing plan

### 9.1 Offline / unit (no GPU, no servers, no model)

All new cases follow the existing plain-python `check(name, condition, detail)` convention of each target
file (no pytest), and each file must still end with `OK n/n` and exit 0.

In `tests/test_ltx_movie_offline.py`:
1. `--no-stills` parser default is `False`; `--reanchor-every` default is `5`.
2. `--reanchor-every 3` without `--no-stills` exits 2 with the Section 4.1 message.
3. `build_story_prompt(..., no_stills=True)` contains `Prompt:`, contains `Narration:`, contains the
   `VERBATIM` consistency sentence, and contains neither `Image:` nor `Motion:`; the three-argument call is
   unchanged from today's template.
4. `_validate_story_md(..., no_stills=True)` on a fixture with `Prompt:`+`Narration:` returns `[]`; on a
   fixture missing `Prompt:` returns a `missing/empty Prompt: field` violation; on a fixture with both
   `Prompt:` and `Image:` returns the both-forms violation.
5. `--no-stills --dry-run` output contains `SKIPPED (--no-stills`, contains `--no-images`, contains
   `--engine chain`, contains `--reanchor-every`, and contains no `ltx-story-images` substring.
6. `--no-stills` is orthogonal to `--length`: `--no-stills --length 30` resolves to the same
   `args.panels`/`args.target_seconds` as `--length 30` alone.

In `tests/test_ltx_story_video.py`:
7. `_parse_prompts_md` on a `Prompt:`-form fixture yields `p["prompt"]` with the wrapped continuation lines
   space-joined, and `p["image"] == p["motion"] == ""`; on today's `Image:`/`Motion:` fixture, `p["prompt"]
   == ""` and `image`/`motion` are unchanged (back-compat).
8. `build_units(..., engine="chain", reanchor_every=5)` over 12 panels: openers are exactly indices
   `{1, 6, 11}`; `continue_from_index` is `i - 1` for every follower and `None` for every opener; `group` is
   `[1,1,1,1,1,2,2,2,2,2,3,3]`; every unit's `conditions == []`; `label`, `seed`, `prompt`, and `num_frames`
   are identical to the same call with `engine="per-panel"`. Repeat for `reanchor_every=1` (every panel an
   opener), `reanchor_every=5` with 5 panels (exactly one group), and `reanchor_every=5` with 6 panels (a
   1-panel final group).
9. `build_units(..., engine="per-panel")` output is unchanged, including the absence of the `role`/`group`/
   `continue_from_index` keys.
10. `load_manifest(path, allow_null_image_path=True)` accepts null `image_path` panels and still rejects an
    index gap, an empty `panel_text`, and a bad v2 `num_frames`; `load_manifest(path)` (default) still
    rejects a null `image_path` with today's exact message.
11. `_build_request(..., conditions=[], mode_field="t2v")` yields `image_path is None`, `mode == "t2v"`,
    `conditions == []`; `_build_request(..., conditions=[c], mode_field=None)` yields a dict with **no**
    `mode` key and today's `image_path`.
12. `--engine chain --mode transitions` exits 2; `--reanchor-every 0` exits 2.
13. An AST guard asserting the nested `ltx-chain` argument list in the chain path contains the literal
    strings `--no-prep`, `--keep-down`, `--segments`, and `--continue-from` — the I4 invariant, in the same
    style as the file's existing `test_ast_guard_*` cases.
14. An AST/source guard asserting the follower frame harvest globs `seg1`, so nobody "simplifies" it into
    reading `ltx-chain`'s output mp4 or the whole chain run root.

In `tests/test_ltx_chain.py`:
15. `_continue_settings_mismatch` returns `None` when only the prompt differs, `None` when only
    `num_frames` differs, and still returns the first-mismatch message for a differing `width`, `height`,
    `fps`, `frame_rate`, `wide`, `seed`, and `negative_prompt` (one case each).
16. `chain._CONTINUE_CHECKED_FIELDS` equals, as a set, exactly
    `{"negative_prompt", "width", "height", "fps", "frame_rate", "wide", "seed"}` — asserted as an exact set
    equality, so neither a re-added `prompt`/`num_frames` nor a newly dropped field passes silently.
17. `_continue_settings_mismatch` returns `None` when the prompt **and** `num_frames` both differ
    simultaneously (the normal follower case: new prompt, new allocated length).

`bin/ltx-story-manifest` `--no-images` cases (existing manifest tests live in
`tests/test_ltx_story_video.py`, so they go there): `--no-images` with `--glob` or `--image` exits 2;
`--no-images` without `--prompts-md` exits 2; `--no-images` with a `Prompt:`-form `story.md` writes a
manifest whose panel count equals the story's, whose `image_path` is `null` throughout, whose `panel_text`
and `motion_prompt` are both the collapsed prompt, and whose `num_frames` list is bit-identical to the
image-driven run over the same narrations.

### 9.2 Integration (cheap, no model)

`--dry-run` is the integration check for the entire decision pipeline — panel count, frame allocation, and
engine/group assignment — without loading any model or touching any server. Required checks:
`bin/ltx-movie --no-stills --dry-run` (phase plan), then a real Phase 3 producing a manifest and
`bin/ltx-story-video ... --engine chain --reanchor-every 5 --dry-run` (per-panel opener/follower table plus
`TOTAL`).

### 9.3 One real generation run (required, not optional)

A single short live run — a small story with `--length` in the 10–20 s range, which at the 2 s chunk basis
gives 5–10 panels and therefore 1–2 chain groups — is **required before this feature is considered
validated**. Its purpose is specifically to resolve OQ1 and OQ2 (Section 13) and to confirm criterion 7 (a
follower really renders its own prompt, no `stale embeds.pt` failure), criterion 12 (a follower renders at
its own allocated length), and criterion 10.

Because the allocator is narration-paced, this run will naturally contain followers whose `num_frames`
differs from their predecessor's — which is precisely OQ2's live test. Before launching it, confirm from the
Phase-3 dry-run table that at least one follower's `frames=` value differs from its predecessor's; if the
narrations happen to allocate uniformly, hand-edit `manifest.json`'s `num_frames` values (staying on the
`n = 1 + 8k` lattice) so at least one boundary is uneven in each direction.

Command (run it exactly as the [NMP §1 Phase D] runbook prescribes: `sudo -v` first, detached):

```
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
sudo -v
nohup python3 bin/ltx-movie "<short narrative>" --story-id t2v_chain_smoke \
    --no-stills --length 16 --reanchor-every 5 --no-review \
    > generated/stories/t2v_chain_smoke/movie_launch.log 2>&1 & disown
```

### 9.3.1 Live run outcome (2026-09-04/05) — criterion 7 confirmed live; criterion 10 NOT met

Story: `t2v_chain_smoke`, narrative "A lighthouse keeper watches a storm roll in over three nights.",
`--length 16 --reanchor-every 5` → 8 panels, 2 chain groups (openers at panel-1 and panel-6), naturally
uneven follower boundaries in both directions (`[57, 49, 49, 49, 57, 41, 41, 41]` frames) — the manifest
allocator required no hand-edit to exercise OQ2's boundary live, exactly as this section predicted.

**Two real, pre-existing bugs (unrelated to `--no-stills`, both fixed and committed) blocked the run before
any GPU work could start:**
- `bin/ltx-movie`'s Phase 1 never passed `--workspace` to `qwen-agent`, so it silently wrote `story.md` into
  `qwen-agent`'s own default workspace (the separate, hand-edited PATH copy) instead of the repo tree
  `ltx-movie` itself reads from — `qwen-agent` exited 0 (it succeeded, just in the wrong tree), so no
  diagnostic ever surfaced. Fixed: commit `6e5776e`.
- `_top5_rss()` (a `bin/ltx-movie` memory-diagnostic helper called every 120 s by `_wait_for_avail`) crashed
  with `AttributeError` whenever `psutil.process_iter` yielded a process with `memory_info=None` — a normal
  occurrence, not just the `NoSuchProcess`/`AccessDenied` cases it already handled. Fixed: commit `687f83a`.

**Host environment findings, all outside this feature's code:** the host runs an MTPLX or vLLM 27B model
server on demand for other work (`qwen-agent`, interactive use), and it competes directly with LTX-Video
generation for both host RAM and Metal/MPS GPU memory — confirmed via `mps_guard`'s own `gpu_other_gib`
accounting (a resident MTPLX instance held 22–25 GiB of GPU memory, independent of host RAM being otherwise
plentiful). `bin/ltx-host-prep`'s `pkill -f 'vllm.*8177'` does not match an MTPLX process, so it cannot stop
one; `bin/ltx-story-video`'s own internal prep step hard-refuses (exit 2) if the port is still open after
prep's 60 s wait, rather than retrying. Across many attempts, stage 1's ~18 GiB T5-shard page-cache growth
consistently left available memory 4–8 GiB short of stage 2's 32.2 GiB gate; `sudo purge` cannot run
non-interactively in this environment (no TTY/cached credential reachable from a spawned subprocess), so
each recovery required a human running it directly, at the right moment, in their own terminal.

**One deliberate, reverted experiment.** With explicit, informed user approval — after surfacing that this
exact scenario (`avail` failing while `supply` alone passes) is the documented 2026-08-25 forced-reboot
thrash incident `mps_guard.py`'s own comments warn against — the stage-2 `required_gib` gate was temporarily
capped at 25 GiB to test whether the measured shortfall (consistently 27–29 GiB avail) was conservative. It
was not: the very next attempt produced a real `sentinel_abort` (swap usage 96%, swap grew 3.83→16.32 GiB)
before completing panel-1 — the exact failure mode the gate exists to prevent, caught by the sentinel rather
than escalating to a freeze, but with zero forward progress gained. The edit was reverted immediately
(`git diff mps_guard.py` confirmed byte-identical to its committed state afterward); this file was never
committed to and remains completely unmodified by this feature.

**What was, and was not, confirmed live, across roughly a dozen attempts:**
- **Criterion 7 (a follower renders its own prompt, no stale-`embeds.pt` failure) — CONFIRMED.** In the one
  attempt that got furthest (before the host-contention findings above were fully understood), panel-1 (T2V
  opener, 57 frames) rendered to completion. Panel-2 (chain follower, 49 frames, `--continue-from` panel-1)
  then completed **stage 1** cleanly: its `embeds.pt` was verified to encode its own prompt (distinct from
  panel-1's), the `=== continuation mode: prompt differs from base; encoding this continuation's own
  prompt (stage 1) ===` banner printed, and the C6 page-cache release fired (`avail 28.31 → 42.93 GiB`).
  Panel-2 then failed at stage 2 to a genuine `sentinel_abort` (available memory collapsed to 0.84 GiB) —
  a real host-capacity limit, not a code defect; the sentinel and the subsequent
  `consecutive_failures` circuit breaker both fired exactly as designed.
- **Criterion 10 (movie.mp4 exists, `completed_units == requested_units`) — NOT MET.** No attempt completed
  more than 1 of 8 units; several completed 0. `story_summary.json`/`movie.mp4` reflecting a full run were
  never produced.
- **Criterion 12 (a follower renders at its own allocated length, differing from its predecessor's) —
  PARTIALLY CONFIRMED.** Panel-2's stage 1 ran against its own 49-frame allocation (differing from panel-1's
  57), but stage 2 never completed for any follower in any attempt, so no follower's final rendered frame
  count was ever directly observed. OQ2's dedicated live probe (Task 5, both directions, `25→49` and
  `49→25`) already closed this property with direct evidence independent of this run (Section 13, OQ2) — this
  run's partial evidence is consistent with, but does not independently re-confirm, that closure.

**Disposition, by explicit user decision (2026-09-05): accept the evidence gathered above in place of a
full 8/8 completion.** OQ1 and OQ2 (Section 13) were already `CLOSED-PASS` from Tasks 4 and 5's dedicated
live probes before this run began, and remain closed on that evidence — this run adds a second, independent,
full-pipeline confirmation of the OQ1/criterion-7 property (a real `--engine chain` follower correctly
re-encoding its own differing prompt) but does not itself close OQ1/OQ2. Criterion 10 is recorded as **not
met on this host at this time**, for reasons entirely of host memory/GPU capacity and a competing model
server, not of any defect found in this feature's code — every offline test (Task 24: 4 suites, 3 checks,
zero findings) and every task-level and this-run's-own diagnostic evidence is consistent with the chain
engine being correctly implemented. A future attempt on a host with more sustained memory/GPU headroom (or
with the competing model server permanently unavailable rather than merely stopped) would be needed to
produce a full completed run for criterion 10.

### 9.3.2 Update (2026-09-05): full 8/8 completion achieved — criterion 10 now MET

A subsequent run, `my_test2` (same narrative/`--length 16 --reanchor-every 5` shape, launched by the user
directly after all fixes from 9.3.1 — the `--workspace` fix, the `_top5_rss` fix, and with the competing
MTPLX/vLLM server stopped before launch — **completed fully**: `story_summary.json` records
`"requested_units": 8, "completed_units": 8, "stopped_reason": null,
"actual_total_frames": 384 == "intended_total_frames": 384`, with `movie.mp4` produced. All 8 panels'
`status` is `"ok"`; per-panel frame counts (`[57, 41, 33, 57, 41, 41, 57, 57]`) show genuine per-panel
variation across both chain groups, consistent with the narration-proportional allocator. Both chain groups
rendered as designed: group 1 (panels 1–5, opener panel-1) and group 2 (panels 6–8, opener panel-6), each
follower's `chain_run_root` present and distinct.

**Criterion 10 (movie.mp4 exists, `completed_units == requested_units`) is now MET**, superseding 9.3.1's
"NOT MET" disposition — the earlier failures were entirely attributable to the host-capacity/competing-server
conditions documented in 9.3.1, not to any defect in the chain engine, and resolving those conditions (server
stopped, sufficient memory margin) let the identical code complete a full run on the first subsequent attempt.
The 9.3.1 record is left unmodified above as an honest account of the debugging path that led here, per this
project's convention of recording what actually happened rather than only the final state.

### 9.4 Not built

No automated drift-quantification metric, no drift regression fixture, and no perceptual scoring. Drift is
judged by watching the output (D6, Section 7).

---

## 10. Must-haves vs. nice-to-haves

**Must-have (this spec is incomplete without all of them):** success criteria 1–11 in Section 1.3; every
invariant in Section 2; the whole of Sections 4, 5, and 6; the error-handling table in Section 8; the offline
tests in 9.1; the dry-run integration check in 9.2; the one real run in 9.3.

**Nice-to-have (do not implement now; listed so nobody adds them speculatively):**
- Cross-group continuity via a soft last-frame condition at the opener (would defeat Section 7's purpose).
- Per-group seed derivation schemes beyond the existing `seed + i`.
- Reusing one T5 encode across a whole group (the follower re-encode in Section 6.2 is per-panel by design).
- Copying follower frames out of `generated/ltx_chains/` into the story run root for tidiness.
- A `--reanchor-every auto` heuristic.

---

## 11. Corrections to the brainstormed framing

**C1 — memory gating is not a per-generation `_wait_for_avail`.** The brainstorm stated that
`_wait_for_avail` "applies before every generation call, opener or follower, exactly as it does per-panel
today." As read (G1), `_wait_for_avail` is called **once**, at the top of `phase4_render`, before
`bin/ltx-story-video` is launched — it is not, and never was, a per-panel gate. The actual per-generation
gating is `_await_gpu_reclaim()` plus `time.sleep(args.settle)` plus `mps_guard.preflight` inside each
spawned stage. The *intent* of the decision holds exactly: **all of these mechanisms are unchanged**, and
they apply to openers and followers alike, including inside the nested `ltx-chain` segment loop. Nothing in
this spec alters any of them.

**C2 — `negative_prompt` was omitted from D4's enumeration.** `_CONTINUE_CHECKED_FIELDS` contains
`negative_prompt` (G4), which the brainstormed enumeration did not list. It remains validated (Section 6.1).
The authoritative validated set after D4 and D7 is exactly: `negative_prompt`, `width`, `height`, `fps`,
`frame_rate`, `wide`, `seed`.

**C3 — the `num_frames` validation conflict, found during this spec's drafting and resolved by D7.** As
originally approved, D4 kept `num_frames` in the validated set while [NMP §3]'s proportional allocator gives
adjacent panels different frame counts — so nearly every follower would have hard-aborted the run. This was
raised as a blocking open question and **resolved on 2026-09-04 by D7**: `num_frames` is removed from the
validated set, the allocator is preserved untouched, and each follower renders at its own length. The
residual, unverified technical risk that generation itself may misbehave when the lengths differ is now
tracked as OQ2 (Section 13) — the *decision* is closed, the *verification* is not.

**C4 — relaxing `_continue_settings_mismatch` is necessary but not sufficient.** Per G5, stage 2
independently rejects a `request.json` prompt that disagrees with `embeds.pt`'s recorded prompt, and
continuation mode reuses the base's `embeds.pt`. Section 6.2 is therefore a mandatory companion change, not
an enhancement — recorded as approved added scope in D8 / Section 12.1 A1, not as an open question.

---

## 12. Added scope and derived requirements

### 12.1 Approved added scope (D8) — required companion changes, in scope, no confirmation pending

These two items are necessary implementation consequences of the approved design, not fresh design
decisions. They are in scope and must be implemented.

**A1 — forced stage-1 re-encode when a continuation's prompt differs from its base's.** An `embeds.pt` is
only valid for the prompt it was encoded from; reusing the base's for a new prompt either hard-fails (G5's
`stale embeds.pt` check) or, if that check were bypassed, would silently generate against the **wrong text
conditioning**. So `bin/ltx-chain`'s continuation path must re-encode stage 1 for the new prompt instead of
copying the base's `embeds.pt` (Section 6.2). Because every follower in this design's chain engine always
carries its own new prompt (never identical to its predecessor's), **followers always re-encode stage 1** in
practice. `bin/ltx-generate --chain N` uses one prompt throughout and must continue to skip the re-encode
exactly as it does today: the change is strictly additive and conditional, with zero behavior change to the
existing same-prompt chain path.

**A2 — `--no-stills` precondition fixes.** Two existing hard preconditions block a zero-image run and must
be handled explicitly for the chain-engine opener case (T2V: no image, no conditions at all):

- `bin/ltx-story-manifest` gains `--no-images` (Section 4.4 / 5.2): mutually exclusive with
  `--glob`/`--image`, requires `--prompts-md`, derives the panel count from the parsed panels, skips the
  Pillow sanity check and the panels-vs-images count check, and writes `image_path: null`. Today the tool
  derives its entire panel list from a matched image glob and requires `--glob` or `--image` (G2), so with
  zero images it cannot run at all.
- `bin/ltx-story-video`: `load_manifest` currently hard-rejects a null `image_path`, and `_build_request`
  does `conditions[0]["image_path"]`, which raises `IndexError` on an opener's empty conditions (G3). Both
  need the explicit handling specified in Sections 5.2 and 5.3.

### 12.2 Other derived requirements

Forced by the source as read (Section 0), each with exactly one mechanically correct form, so they are
specified normatively above rather than left open. Itemized here because they add surface area beyond the
approved decision list. (The gaps at DR1, DR3, and DR5 are intentional: those three items were promoted
into Section 12.1's approved added scope and keep their original numbers there for reference stability —
DR1 → A2's `--no-images`, DR3 → A2's null-`image_path`/empty-`conditions` handling, DR5 → A1.)

- **DR2.** `_PANEL_LABEL_RE` becomes `^(Image|Motion|Narration|Prompt):\s*(.*)$` and the parsed panel dict
  gains a `"prompt"` key (`""` when the label is absent), preserving the load-bearing v1 `text` whole-body
  join. Panel assembly: when `pt["prompt"]` is non-empty, `panel_text` **and** `motion_prompt` both become
  that text; otherwise today's `Image:`/`Motion:` rules apply verbatim. `panel_text` must be non-empty
  because `load_manifest` requires it (G3).
- **DR4.** The nested `ltx-chain` invocation's `--no-prep --keep-down --force`, its `--seed <base_seed>`,
  its positional `image_path`, and the `seg1`-only frame harvest with `_chain_scratch.mp4` deletion
  (Section 5.5), all forced by G4.
- **DR6.** The collapsed field's `85-130` word band (Section 4.2), derived as the sum of the two merged
  ranges and kept below the existing 150-word truncation warning. See OQ3.
- **DR7.** `--engine chain` + `--mode transitions` rejected at parse time, and `skipped_no_base` as a
  follower status (Sections 5.1, 5.5).
- **DR8.** Geometry gating after D7: `bin/ltx-story-video`'s step-4 per-unit `_check_ceiling` is what covers
  a follower whose `num_frames` exceeds its base's, and must not be removed (Section 6.3).

---

## 13. Open questions — UNRESOLVED

Nothing in this section is settled. OQ1 and OQ2 are **unverified technical assumptions** that this design
sits on top of; both must be closed as the **first implementation steps**, before any code that depends on
them is written, and neither may be silently assumed safe. OQ3 and OQ4 are lower-stakes confirmations that do
not block starting.

**Previously listed here and now closed:** the `num_frames`-validation conflict (resolved 2026-09-04 by D7;
see Section 11 C3 — its residual *verification* risk is OQ2 below), the Section 6.2 stage-1 re-encode scope
expansion (now approved added scope, D8 / Section 12.1 A1), and the `--no-images` / null-`image_path` /
empty-`conditions` precondition fixes (now approved added scope, D8 / Section 12.1 A2).

### OQ1 (recorded verbatim from the approved brainstorm) — first implementation step

**`ltx-generate --t2v`'s output directory shape is unverified as a `--continue-from` base.**
`bin/ltx-chain --continue-from BASE_RUN_DIR` mode (added in commit 37a64aa) expects the base run directory
to contain `embeds.pt` (stage-1 text encoding, so it can skip re-encoding) and the base run's last generated
frame, plus a `request.json` recording the generation settings for the mismatch-validation check — all
currently written by `ltx-chain`'s own fresh-chain / `ltx-generate`'s I2V-with-`--chain` code path. Whether
`ltx-generate --t2v`'s pure-T2V output directory (`ltx_video_skill.py`'s T2V branch, lines ~511-551 per
prior research) writes these same artifacts in the same shape has NOT been verified by reading that code
path specifically — today `--t2v` and `--chain` are mutually exclusive in `ltx-generate` precisely because
chaining has always required an image, so this exact combination (T2V output feeding into a chain
continuation) has never been exercised in this codebase. **This must be verified — by reading
`ltx_video_skill.py`'s T2V output-writing code and/or a small live test — as the FIRST implementation
step**, before the rest of this design is built on top of it. If the shapes don't match, the T2V code path
will need to be extended to write a compatible `embeds.pt`/last-frame/`request.json`, which is additional
scope not yet designed.

*Partial evidence gathered while writing this spec (does NOT close OQ1; live verification is still
required).* Reading `ltx_video_skill.py` (G6/G7) shows a fresh T2V run writes `request.json` with
`"image_path": None`, `"mode": "t2v"`, `"conditions": []` and all seven settings fields that
`_continue_settings_mismatch` still reads after D4/D7; stage 1 writes `embeds.pt` at the run-dir root
unconditionally (text-only, no image involvement — [MFC §2 I2]); and stage 2 writes `frames/frame_%05d.png`, matching
`ltx-chain`'s `frames/frame_*.png` glob. On paper the shape looks compatible. Three things remain unverified
and can only be closed live: (a) whether an actual T2V run's run-dir contents match this reading with no
missing artifact; (b) whether `bin/ltx-story-video`'s **opener cell** (which this spec renders in-process via
`_spawn_stage`, not via `bin/ltx-generate --t2v`) is equally valid as a `--continue-from` base — it should
be, since the cell layout is the same, but it has never been exercised; and (c) whether the T2V branch's
`conditions=None` pipeline call has any run-dir side effect not visible in the code read. Until a live run
confirms all three, treat OQ1 as open.

**CLOSED-PASS 2026-09-04.** Both required live bases were exercised end to end against the PATH copy
(`/Users/reubenpatterson/qwen-agent-workspace`) and both `--continue-from` continuations succeeded, closing
all three previously-open sub-questions.

*Base 1 — a real `bin/ltx-generate --t2v` output directory.*
Run root: `/Users/reubenpatterson/qwen-agent-workspace/generated/ltx_runs/20260904T174455Z-8284ee71`.
`request.json` field dump (matches the static-read prediction exactly):
```
{'image_path': None, 'mode': 't2v', 'conditions': [], 'prompt': 'a slow drone shot over an empty stone
courtyard at dawn, soft mist, no people', 'negative_prompt': 'worst quality, inconsistent motion, blurry,
jittery, distorted', 'width': 512, 'height': 512, 'num_frames': 25, 'fps': 24, 'frame_rate': 24, 'wide':
False, 'seed': 0}
```
`embeds.pt` and 25 `frames/frame_*.png` both present. Continuing from it with `bin/ltx-chain
--continue-from` (identical prompt/settings, isolating OQ1 from OQ2) produced chain run root
`/Users/reubenpatterson/qwen-agent-workspace/generated/ltx_chains/20260904T180832Z-281dd2c9`: printed
`=== continuation mode: reusing base run embeds.pt (skipping stage 1) ===`, exited 0, and
`seg1/frames/` holds exactly **25** PNGs; `chain_summary.json` reports `"completed_segments": 1`.

*Base 2 — a hand-built `bin/ltx-story-video` opener cell* (`request.json` written directly with
`image_path=null, mode="t2v", conditions=[]`, then all three stages run via
`python3 ltx_video_skill.py --stage {1,2,3} --run-dir ...`, exactly the `_spawn_stage` subprocess shape
`bin/ltx-story-video` uses, never via `bin/ltx-generate --t2v`). Cell dir (outside the repo, a scratch
location; the shape is what's under test, not its path):
`/private/tmp/claude-502/-Users-reubenpatterson-local-model-harness/a5204472-4feb-44e2-895e-19af2c0b74f7/scratchpad/oq1_cell`.
Same `embeds.pt` + 25 `frames/frame_*.png` shape produced. Continuing from it (seed=1, matching the cell's
own recorded seed) produced chain run root
`/Users/reubenpatterson/qwen-agent-workspace/generated/ltx_chains/20260904T182509Z-260d0c95`: same
`=== continuation mode: reusing base run embeds.pt (skipping stage 1) ===` marker, exit 0, `seg1/frames/`
holds exactly **25** PNGs, `chain_summary.json` reports `"completed_segments": 1`.

Both bases are therefore confirmed valid `--continue-from` inputs: (a) an actual T2V run's run-dir contents
carry no missing artifact; (b) the opener-cell shape is equally valid, empirically now exercised, not just
inferred from identical code paths; (c) no run-dir side effect of the `conditions=None` pipeline call broke
either continuation. Proceed to Task 5.

### OQ2 — first implementation step: a differing `num_frames` across a `--continue-from` boundary is unverified

**D7 removes the `num_frames` equality check; it does not establish that generation is correct or safe when
the lengths actually differ.** What has been decided is only that the *validation* is removed, on the
reasoning that chaining conditions visually on the base's last frame alone and carries no known dependency
on matching segment lengths. That reasoning is **not verified**: nobody has read
`ltx_video_skill.py`'s / `pipeline_ltx_condition.py`'s latent-preparation and conditioning code with this
specific question in mind, and no live run has ever chained a continuation whose `num_frames` differs from
its base's. This combination has never been exercised in this codebase — until now `--continue-from`
refused it outright, so there is zero empirical evidence either way.

Concretely unverified, and each must be answered:

- Does anything in the conditioning/latent path derive a shape, index, or coordinate from the **base's**
  `num_frames` rather than the continuation's own? Per [MFC §0], a frame-0 image condition is hard-written
  into the latent grid at `latents[:, :, :num_cond_frames]` and involves no `frame_index` arithmetic, which
  suggests independence — but that was read for a *fresh* run's geometry, not across a continuation
  boundary, and the continuation reuses only a PNG plus an `embeds.pt`, both length-agnostic on their face.
- Does the reused/re-encoded `embeds.pt` carry any length-dependent state? [MFC §2 I2] asserts stage 1 is a
  pure function of `prompt` + `negative_prompt` + `MAX_SEQUENCE_LENGTH`, which implies no — confirm it holds
  with differing continuation lengths.
- Does per-unit memory behavior stay inside the gates when a longer continuation follows a shorter base?
  Section 6.3 argues the parent's step-4 `_check_ceiling` covers this; confirm against a real run's
  `peaks_stage2.json`.
- Is output *quality* across the boundary unaffected — no seam artifact, stutter, or motion discontinuity
  attributable to the length change rather than to ordinary chaining drift?

**Verification method, required as an early implementation step, alongside/immediately after OQ1:** read the
latent-preparation and conditioning code path for length dependence, then run one live two-segment
continuation in which the second segment's `num_frames` differs from the first's (e.g. 25 → 49 and 49 → 25,
both on the `n = 1 + 8k` lattice), and inspect the frames and `peaks_stage2.json`. If a real dependency
turns up, it is additional scope not yet designed, and OQ2 must be brought back to the user rather than
worked around in code.

**CLOSED-PASS 2026-09-04.**

Static read (installed `diffusers/pipelines/ltx/pipeline_ltx_condition.py`,
`/Users/reubenpatterson/Library/Python/3.13/lib/python/site-packages/diffusers/pipelines/ltx/pipeline_ltx_condition.py`,
and `ltx_video_skill.py` / `bin/ltx-chain` in `/Users/reubenpatterson/qwen-agent-workspace`), answering the four
concretely-unverified points above:

1. **No shape/index/coordinate in the conditioning/latent path is derived from a base run's `num_frames`.**
   `ltx_video_skill.py` lines 543 and 569 pass `num_frames=request["num_frames"]` — this call's own request
   dict — into both stage-2 pipeline invocations. `pipeline_ltx_condition.py` line 689:
   `num_latent_frames = (num_frames - 1) // self.vae_temporal_compression_ratio + 1` is computed purely from
   the `num_frames` argument of *this* call (threaded through from `__call__` line 1151, itself the caller's
   own `num_frames`, line 862/916). The frame-0 image condition writes at
   `latents[:, :, :num_cond_frames]` (lines 726–729, the `if frame_index == 0:` branch — the branch always
   taken for a single-PNG image condition, since `ltx_video_skill.py` line 160 always sets
   `"frame_index": 0` for image conditions), against `latents` allocated at lines 693–705 with shape
   `(batch_size, num_channels_latents, num_latent_frames, latent_height, latent_width)` — entirely a function
   of this call's own `num_frames`/`height`/`width`. `conditioning_mask` (line 792) is
   `condition_latent_frames_mask.gather(1, video_ids[:, 0])`, where both operands (`condition_latent_frames_mask`,
   lines 708–710; `video_ids`, lines 782–790) are sized from this call's own `num_latent_frames`. Nothing here
   references a prior call.
2. **`embeds.pt` carries no length-dependent state.** `ltx_video_skill.py` `_stage1_encode` (lines 334–412):
   `_encode()` (lines 369–384) is a function of `request["prompt"]` / `request["negative_prompt"]` tokenized
   with `max_length=MAX_SEQUENCE_LENGTH` (line 375; `MAX_SEQUENCE_LENGTH = 256` at line 96). The saved dict
   (lines 394–411) contains only `prompt_embeds`, `prompt_attention_mask`, `negative_prompt_embeds`,
   `negative_prompt_attention_mask`, and a `meta` block of `model_id`/`prompt`/`negative_prompt`/
   `max_sequence_length`/`dtype`/`diffusers_version`/`transformers_version`. No `num_frames`, `width`,
   `height`, `fps`, or `seed` appears anywhere in it.
3. **A continuation reuses only a PNG path plus `embeds.pt` at generation time; `base_request_dict` has no
   other reader.** `bin/ltx-chain` line 313–314: `input_image = os.path.abspath(base_frames[-1]) if
   args.continue_from ...`, where `base_frames` is the sorted glob of the base run's `frames/frame_*.png`
   (line 239). `grep -n "base_request_dict" bin/ltx-chain` returns exactly two lines: the assignment (line
   251, `base_request_dict = json.load(f)`) and its single use (line 256,
   `mismatch = _continue_settings_mismatch(base_request_dict, args)`) — a pure comparison against `args`
   (`_CONTINUE_CHECKED_FIELDS`, lines 144–147: `prompt, negative_prompt, width, height, num_frames, fps,
   frame_rate, wide, seed`) that only produces an error string on mismatch and feeds nothing from the base
   into generation. This is precisely the check D7 removes.
4. **`ltx-chain`'s geometry validation for the continuation's own length runs unconditionally.**
   `bin/ltx-chain` line 224, `L._validate_geometry(args.width, args.height, args.num_frames)`, executes
   inside the top-level `try` at lines 223–227, which precedes the `if args.continue_from:` block starting at
   line 232 — it is not nested inside it, so a continuation's own requested length is still lattice-checked
   regardless of `--continue-from`.

Live probe, two directions, both on the `n = 1 + 8k` lattice at 512×512 (ceiling 73 frames per
`ltx_ceiling.json` — neither 25 nor 49 tests a ceiling edge), executed against the unmodified,
installed `bin/ltx-chain` (`base_request_dict`'s only reader per point 3 above is the mismatch
comparison, so editing a copy's `request.json` `num_frames` to match the continuation's requested value —
while the real on-disk frame count is left untouched — exercises "a continuation whose length differs
from what the base actually generated" without any code change):

- **Direction A, 25 → 49** (Task 4's real 25-frame T2V base, copy's `request.json` `num_frames` edited to
  49, continuation run with `--num-frames 49`): run root
  `/Users/reubenpatterson/qwen-agent-workspace/generated/ltx_chains/20260904T183130Z-40106346`. Exit 0.
  `seg1/frames/` held **49** PNGs (the requested value, not the base's real 25).
  `seg1/peaks_stage2.json`: `mps_driver_gib=28.95`, `mps_current_gib=27.19` (cap =
  `mps_guard.FRACTION_STAGE2` (0.82) × host total 48.0 GiB = 39.36 GiB — well under). No
  `sentinel_abort` line in `seg1/mem_stage2.jsonl`. Visual check of the base's last frame plus seg1's
  first three and last three frames: continuous composition across the boundary, ordinary chaining
  drift only, no seam/stutter/discontinuity attributable to the length change.
- **Direction B, 49 → 25** (a fresh 49-frame T2V base generated via `bin/ltx-generate --t2v --num-frames
  49 ...`, run dir `/Users/reubenpatterson/qwen-agent-workspace/generated/ltx_runs/20260904T183401Z-7e56a17b`;
  copy's `request.json` `num_frames` edited to 25, continuation run with `--num-frames 25`): run root
  `/Users/reubenpatterson/qwen-agent-workspace/generated/ltx_chains/20260904T185124Z-8483de07`. Exit 0.
  `seg1/frames/` held **25** PNGs (the requested value, not the base's real 49).
  `seg1/peaks_stage2.json`: `mps_driver_gib=28.37`, `mps_current_gib=26.94` (same 39.36 GiB cap — well
  under). No `sentinel_abort` line in `seg1/mem_stage2.jsonl`. Visual check of the base's last frame plus
  seg1's first three and last three frames: continuous, ordinary drift only, qualitatively the same as
  Direction A — no direction-specific seam.

Both directions exit 0, both `seg1` frame counts equal the requested value (not the base's actual
generated length), no sentinel abort in either direction, both peaks well under cap, and neither
direction shows a length-attributable seam. No real dependency on matching base/continuation
`num_frames` turned up anywhere in the conditioning/latent path, `embeds.pt`, or `ltx-chain`'s
continuation plumbing. OQ2 is closed; Task 6 (removing the `num_frames` equality check) may proceed.

### OQ3 — confirm the derived word band

Section 12.2's DR6 (the `85-130` word band for the collapsed `Prompt:` field) was derived, not approved:
it is the sum of the two merged ranges, kept under the existing 150-word truncation warning. Confirm the
band or supply a replacement. Non-blocking — a wrong band degrades prompt quality, it does not break
anything.

### OQ4 — where follower frames live

Section 5.5 leaves a follower's frames in `<WS>/generated/ltx_chains/<chain_run_id>/seg1/frames/` rather
than under the story's own `<run_root>/panel-<i>/frames/`, so a `--no-stills` movie's frames are split across
two directory trees and the story run root is no longer self-contained. This satisfies D3's "same output
shape/naming" requirement at the *clip list* level (the concat sees one flat PNG list per panel, engine-
unaware) but not at the *directory* level. Confirm this is acceptable, or specify a copy/move step. Note
that `generated/ltx_chains/` is not currently pruned by anything, so a long `--no-stills` run leaves frames
there indefinitely.

## 14. Environment reconciliation (2026-09-04)

During implementation planning, a blocking conflict was found between this spec's "leave `WS` exactly as
it is" constraint and Section 9.3's mandatory live validation run: the repo copy's `bin/ltx-story-manifest`,
`bin/ltx-story-video`, and `bin/ltx-chain` all hardcode `WS = "/Users/reubenpatterson/qwen-agent-workspace"`
(the separate, hand-edited PATH copy), while `bin/ltx-movie` already resolves `WS` relative to itself (the
repo). Consequences verified in-source: `<repo>/generated/` does not exist, so `bin/ltx-movie`'s Phase 3 is
already broken in the repo copy today, independent of this feature; and the PATH copy's `ltx_video_skill.py`
has had `content_safety.assert_frames_safe` removed from stage 3 entirely (confirmed by `diff`), so any run
through the PATH copy would violate Invariant I3.

**User decision: R1.** Repoint `WS` in `bin/ltx-story-manifest`, `bin/ltx-story-video`, and `bin/ltx-chain`
to `os.path.dirname(os.path.dirname(os.path.realpath(__file__)))` — identical to `bin/ltx-movie`'s existing
pattern — making the repo copy fully self-contained and safety-gated. `tests/check_ltx_safety_gate.py`'s
`DEFAULT_TARGET` (a related instance of the same pattern, found while recording Task 1's baseline) is
repointed the same way in the same batch. This is a deliberate, scoped deviation from the "leave WS alone"
constraint in the preamble — the constraint is superseded for these three tools and this one test script
by this section. Operational consequence: `~/qwen-agent-workspace/generated/` is no longer where this
tool's output lands; `<repo>/generated/` is.

Implemented as plan Task 5.5 (inserted after Task 5, before Task 6). Task 1's baseline suites were
re-run afterward to confirm no regression from the four `WS`/`DEFAULT_TARGET` edits alone.
