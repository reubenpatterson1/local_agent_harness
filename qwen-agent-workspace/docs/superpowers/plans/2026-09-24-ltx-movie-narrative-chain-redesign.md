# ltx-movie Narrative-Chain Redesign: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to carry out this plan task by task. Every step uses checkbox (`- [ ]`) syntax so progress can be tracked.
>
> **Save this document to:** `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/docs/superpowers/plans/2026-09-24-ltx-movie-narrative-chain-redesign.md`. The Baseline table (Task 0) and the Hardware Gate table (Task 13) are filled in inside this file. Per spec §11 and the "ephemeral scratchpad loses baselines" lesson, they are not recorded in `/private/tmp`.

**Goal:** Change `bin/ltx-movie` from "one independent still and clip per panel, hard-cut" to one continuous take. Panel 1 gets the only still: the `--seed-image` fitted without cropping, or z_image at 2W×2H. Clip 1 is I2V from that still. Clip N is I2V from the exact last frame of clip N-1. The clips are then stream-copy stitched. The video W×H comes from the seed's aspect ratio on ltx-2-mlx's 64 px grid. Every ComfyUI, wan and cctech backend and all the deploy tooling are removed.

**Architecture:** Approach A from the spec. The phase tools stay separate subprocesses. A new stdlib-at-import module, `ltx_image_fit.py`, owns all geometry: it derives dimensions and fits images with a letterbox, never a crop. `bin/ltx-story-manifest --chain` writes manifest schema v3, which adds a per-panel `conditioning` key (`still`/`chain`/`t2v`). `bin/ltx-mlx-render` holds the chain loop:
- It extracts the last frame of clip k-1 with ffmpeg and checks it (size and brightness) with ffprobe/ffmpeg.
- It content-screens that frame, renders clip k, and retries once inline.
- It stops the whole run on any failure in a chained manifest.
- Its provenance keys a chain clip on the bytes of its source clip, so an edit cascades forward on `--resume`.

`bin/ltx-movie` wires the flow together: Phase 0 derives geometry, Phase 2 is `--only 1`, Phase 3 is `--chain`, Phase 4 is `--on-panel-failure stop`.

**Tech Stack:** Python 3.13 (framework build at `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`), Pillow 12.3 (imported lazily only), ffmpeg/ffprobe 9.0.1, ltx-2-mlx (`~/ltx-2-mlx/.venv/bin/ltx-2-mlx`), z_image_skill. Tests are plain scripts: a `check()` helper, a `__main__` block, `OK n/n`, and the exit code as the result.

**Spec (single source of truth):** `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/docs/superpowers/specs/2026-09-24-ltx-movie-narrative-chain-redesign-design.md` (commit `3a3422f`, branch `ltx2-mlx-video-pipeline`).

**Workspace root `WS`:** `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace`. Every relative path below is relative to `WS`, and every command runs from `WS`.

---

## Global Constraints (copied from the spec; not negotiable)

**Geometry (`ltx_image_fit.py`, §5.1):**
```python
GRID_PX = 64            # ltx-2-mlx two-stage snap modulus (patchifiers.py snap_output_dimensions)
MIN_CELLS = 5           # 320 px minimum edge; stage-1 half-size edge 160 px = 5 latent cells
MAX_CELLS = 15          # 960 px maximum edge; with MIN_CELLS this bounds aspect to [1:3, 3:1]
MAX_AREA_CELLS = 77     # 704*448 / 64**2 -- the only MLX-measured area (acceptance run A1)
MIN_AREA_CELLS = 40     # 163,840 px = 0.52x of 704x448; resolution floor
PAD_TOLERANCE_PX = 8    # total residual pad (width deficit + height deficit) treated as "no bar"
DEFAULT_VIDEO_WIDTH = 704
DEFAULT_VIDEO_HEIGHT = 448
```
- Aspect bound: a seed outside 1:3 … 3:1 is rejected with exit 2, in Phase 0 and in `--dry-run`, before Phase 1 runs. Exactly 3:1 and exactly 1:3 are accepted.
- No cropping anywhere. The seed is scaled to fit, centred, and black-padded.
- With a seed, the video W×H is derived and `--video-width/--video-height` are rejected. Without a seed, the defaults are 704x448 and both values must be multiples of 64 and ≥ 64.
- `ltx2_mlx_video_skill.validate_geometry` requires multiples of 64 and a minimum of 64. That is the only change to that file.
- `SEED_DOWNSCALE_MAX_EDGE = 1024` and `SEED_MIN_EDGE = 64` are kept.

**Flow:**
- `ltx-movie --frames` defaults to **145** (6.04 s at 24 fps). `--length 60` resolves to 10 panels.
- Phase 2 is `--only 1`. In seed mode the still is W×H (the seed fitted into it). Otherwise z_image renders it at 2W×2H.
- Phase 3 is `--chain --image images/panel_01.png`.
- Phase 4 uses `--on-panel-failure stop` in stills mode and `skip` in `--no-stills`. It keeps `--retry-failed 1 --retry-idle 120 --max-consecutive-failures 3`.
- `--no-stills` is unchanged apart from the `{seconds}` figure: v2 manifest, t2v, independent loop.

**Manifest:** schema_version 3 is written only by `--chain`. The `--glob`, `--image` (without `--chain`) and `--no-images` modes keep schema_version 2, byte-for-byte.

**Chain loop:**
- `CHAIN_SEED_MIN_YAVG = 20` and `CHAIN_SEED_MIN_YRANGE = 10`.
- The last frame is selected by exact index `frames - 1`. `-sseof` is not used.
- Provenance is schema_version 2, and a chain unit is keyed on `chain_source_sha256`.
- Inline retry. The end-of-run retry pass never runs for a chained manifest.
- `stopped_reason` gains `chain_broken`, `chain_seed_invalid` and `chain_seed_blocked`.

**Deletion list (§10):**
- Tracked, removed with `git rm`: `wan_video_skill.py`, `bin/wan-generate`, `wan_ceiling.json`, `tests/test_wan_video_skill_offline.py`.
- Untracked, removed with `rm`/`rm -r`:
  - `comfyui_video_skill.py`, `comfyui_video_supervisor.py`, `comfyui_split_video.py`, `comfyui_custom_nodes/`
  - `cctech_ltx25_{convert,cpu,decoder,mlx}.py`, `cctech_ltx25_q8_layers.json`, `cctech_ltx25_{requantize,runtime,source}.py`
  - `scripts/deploy/`, `scripts/cctech_conv_decode_ab.py`, `scripts/cctech_repin_outputs.py`, `scripts/cctech_repin_sources.py`, `scripts/comfyui_frogjump_ab.py`, `scripts/comfyui_frogjump_cpu_diagnostic.py`, `scripts/verify_cctech_conversion.py`, `scripts/verify_cctech_requantization.py`
  - `tests/test_cctech_ltx25_{convert,cpu,decoder,mlx,requantize,runtime,source}.py`
  - `tests/test_comfyui_{frogjump_cpu_diagnostic,mlx_nodes,mlx_video_skill,split_nodes,split_video,video_skill,video_supervisor}.py`
  - `tests/test_verify_cctech_conversion.py`, `tests/test_deploy_package.py`
  - `tests/fixtures/{cctech_component_oracle.py,split_video_surviving_descendant_supervisor.py,mlx_surviving_descendants_supervisor.py,mlx_affine_int8_g64.json}`
  - `docs/comfyui-{mlx-backend,mlx-validation,video-skill}.md`
  - the ComfyUI/cctech/USB-deploy specs and plans listed exactly in Task 1.

**Process constraints:**
- **Do not revert, re-stage or "clean up" any pre-existing uncommitted hunk the spec does not name** (spec §2). The working tree has large uncommitted diffs in `bin/ltx-movie`, `bin/ltx-mlx-render`, `ltx2_mlx_video_skill.py`, `z_image_skill.py` and the two big test files. They include the explicit-content `Rules:` block in `STORY_PROMPT_TEMPLATE_NO_STILLS` and the `--story-server-stop-after-story` feature. Leave them as they are.
- **Gate rule:** pass/fail is decided by `python3 tests/<file>.py` and its exit code, never by a pytest count. The main thread re-runs every gate itself.
- **Kept-test rule:** every existing test not named in this plan as deleted or rewritten stays byte-identical. The exceptions this plan makes are in "Spec gaps resolved" (G1, G2, G3).
- **Source-text counters that existing kept tests pin.** New code, comments and docstrings must not add or remove occurrences of:
  - `_render_flags(args)`, which stays at exactly 4 in `bin/ltx-movie` (L17d/L46e);
  - `os.path.join(WS, "bin", "ltx-mlx-render")`, which stays at 4 (L17f/L46f);
  - `os.path.join(WS, "bin", "story-server")`, which stays at 2 (L46d);
  - `"--workspace", WS,`, which stays at 2 (L19a);
  - the literals `cmd += ["--image", args.seed_downscaled_path]`, `phase1_cmd += ["--image", paths["seed_downscaled"]]`, `\n        cmd += ["--seed-image", args.seed_image]` and `phase2_cmd += ["--seed-image", args.seed_image]` (exactly 1 each, L29c/d), `phases = (phase0_seed,) + phases`, `cmd += ["--user-prompt", prompt]`, `phase1_cmd += ["--user-prompt", prompt]`, `cmd_manifest += ["--fps", str(args.fps),`.
- **§12.1.5 grep gate:** no file under `bin *.py tests scripts` other than `tests/check_ltx_no_grad.py`, `tests/test_ltx_t2v_offline.py` and `tests/test_story_server.py` may contain `comfyui_|cctech_|wan_video_skill|wan-generate|COMFY_MLX|video_backend|video-backend`. Test code that has to name the removed flag builds the string by concatenation (G15).
- **Deletion method:** if the permission system blocks `rm` or `git rm`, **STOP** and return the exact remaining list to the user. Never replace a file with a stub or a redirect pointer.

## Review Focus: the five inputs most likely to break this

| # | Input / failure mode | Why it bites | Covered by |
|---|---|---|---|
| RF1 | **Seed image outside the 1:3 to 3:1 aspect bound** (e.g. a 3001x1000 banner, or a 1000x3001 phone screenshot) | It must fail with exit 2 before the 27B story call and before any GPU time, in real runs and in `--dry-run`. A silent clamp would crop, violating D2. | Task 2 F2 (ValueError and exact message); Task 5 L26h (no file written), L27k (dry-run exits 2), L50 (`phase1_story` never called) |
| RF2 | **Corrupted, black or flat last-frame extraction** (ffmpeg selects nothing, writes 0 bytes, or clip k-1 ends on a fade to black) | A black frame as clip k's conditioning image poisons every later clip. The loop must stop with `chain_seed_invalid` and name the remedy (edit panel k-1's `Motion:`). | Task 9 R23e-h (rc≠0, missing tmp, zero-byte tmp, OSError), R26b/c (black/flat), R27 (composition); Task 10 R28 (loop stops, later panels `not_attempted`, the prefix is concatenated) |
| RF3 | **Resuming after a mid-chain failure** (crash at panel 7, or an edited `Motion:` on panel 4) | Reuse must be exact and in order. A stale clip k+1 must never be reused once clip k's bytes change. The relaunch also needs `--force`, because the partial `movie.mp4` from the stopped run already exists. | Task 8 R18 (provenance keys); Task 10 R25 (prediction for unchanged, edited-prompt and new-clip-1-bytes cases), R24 (relaunch hint on `chain_broken`); Task 13 runbook notes the `--force` requirement |
| RF4 | **EXIF-rotated phone photo** (a JPEG stored landscape with `Orientation=6`) | Ignoring EXIF derives a landscape geometry for a portrait subject and lays the subject on its side. | Task 2 F7 (`load_oriented_rgb`), Task 5 L26i (`_prepare_seed_image` gives `(384, 512, 0)`); mutation M2 in Task 12 |
| RF5 | **Single-panel movie** (`--panels 1`) | It has no chain units, so the v3 manifest is not a chained manifest. The render must take the non-chain path: `skip` is allowed and nothing is extracted. A one-clip concat must still work. | Task 7 C5 (one-panel `--chain` manifest); Task 10 R32 (rc 0, no `prepare_chain_seed` call, skip allowed) |

## Spec gaps resolved during planning (decisions made here; the executor applies them as written and lists them in the hand-back)

| ID | Gap | Decision |
|---|---|---|
| G1 | Kept test L17c asserts the literal `"--glob", "panel_*.png"`, which §7.3 deletes. | Task 11 changes L17c to assert the new `--chain` literal and that `"--glob"` is gone. This is the only line of that test that changes. |
| G2 | Kept test L14b asserts that `--length 100` resolves to 10 panels. D6 makes it 17. | Task 11 changes L14b's expected value from 10 to 17. Only that line changes. |
| G3 | Rewritten test L15 contains L15y, which already fails at baseline: a pre-existing uncommitted edit removed its anchor text, and spec §2 forbids reverting that edit. | L15y is dropped from the rewritten L15. |
| G4 | §8.2 gives `check_chain_seed(png_path, width, height)`, but its message must name panel `unit["index"] - 1`, which the function cannot know. | The signature becomes `check_chain_seed(png_path, width, height, source_panel)`. `prepare_chain_seed` passes `unit["index"] - 1`. |
| G5 | §8.6 says a retry "re-extracts" the last frame. §8.4, the normative loop, just calls `render_panel` again. | Follow §8.4: the retry reuses the `.chainseed.png` from the first attempt. The bytes are identical because extraction is deterministic. `prepare_chain_seed` runs once per unit. |
| G6 | `phase0_seed` must print the post-EXIF source size, but `_prepare_seed_image` returns only `(violations, geometry)`. | Keep the spec signature. `phase0_seed` gets the size from `_image_fit().load_oriented_rgb(seed).size`, a second decode that runs once per run. |
| G7 | §5.8 does not say how the `<W>`/`<H>` placeholders reach the printed commands. | Set `args.video_width, args.video_height = "<W>", "<H>"` (strings), inside `--dry-run` only. |
| G8 | The skill format asks for a commit per task. Spec §2 forbids re-staging pre-existing hunks, most modified files contain such hunks, and the user's CLAUDE.md says to commit only when asked. | **No per-task commits.** Each task ends at a Checkpoint. Task 14 hands the commit decision to the user. The only staging is Task 1's `git rm` of four tracked files, which the spec itself prescribes. |
| G9 | Two call sites need image dimensions without PIL (R2a). | Add one helper, `ffprobe_image_size(path) -> ((w, h), None) \| (None, reason)`. |
| G10 | A v3 `still` panel whose path does not exist: the pre-existing normalization raises first. | That case keeps the pre-existing message, `panel %d: image_path does not exist or is not readable`. The §7.4 `still` message fires when `image_path` is null. |
| G11 | `tests/check_ltx2_mlx_no_forbidden_imports.py` prints `RESULT: ok`, not `OK n/n`. | Its gate is exit 0 plus `RESULT: ok`. The file is not edited. |
| G12 | The new M3h/M3i/M3j labels collide with `test_resolve_bin`'s existing M3h/M3i/M3j labels. | New labels read `M3h (geometry) …` and so on. |
| G13 | Duplicate-code risk between the real phases and their dry-run mirrors. | Add `_seed_geometry_line()` (Phase 0 and dry-run) and `_still_size()` (Phase 2 and dry-run), the same "one helper, two call sites" pattern `_render_flags` uses. |
| G14 | The §11.7 breakage "re-enable the end-of-run retry for chain manifests" is not observable through the loop alone, because `stopped_reason != None` already suppresses the retry pass. | R24 includes a direct `finish_run` call on a chain manifest with `stopped_reason=None`. |
| G15 | The spec requires tests that name the removed flag (L23, L24, R1), but the §12.1.5 grep over `tests/` must not match them. | Tests spell the flag as `"--video-" + "backend"` and `"video_" + "backend"`, with a comment explaining why. |
| G16 | Unspecified output for a blocked chain seed. | stderr `panel %d FAILED (chain seed): input content screen rejected %s (rc=%d)`. Unit `error` is `input content screen rejected %s (rc=%d)`. |
| G17 | The docstrings of `bin/ltx-movie` state "10.04s at the defaults", which becomes wrong. | Change those two numbers to 6.04 / 6.0417 (Task 11). No other docstring edits. |

---

## File Structure

| Path | Action | Responsibility after this work |
|---|---|---|
| `ltx_image_fit.py` | **Create** | The no-crop geometry module. Constants, `load_oriented_rgb`, `fit_pad_px`, `derive_video_dims`, `fit_letterbox`. Stdlib at import; PIL imported inside functions. |
| `tests/test_ltx_image_fit.py` | **Create** | Golden table, 2001-ratio sweep, letterbox markers, EXIF, AST guard. |
| `tests/test_ltx_story_manifest_chain.py` | **Create** | `--chain` v3 output, every §7.2 error, the panel-2 `Image:` warning, the single-panel case, v2 unchanged. |
| `ltx2_mlx_video_skill.py` | Modify `validate_geometry` only (lines 83-100) | 64-multiple, ≥ 64 geometry check. |
| `tests/test_ltx2_mlx_video_skill.py` | Modify `test_validate_geometry` | Adds M3h-M3l (geometry). |
| `bin/ltx-movie` | Modify | Chained templates; `build_story_prompt(seconds=)`; the validator; Phase 0 geometry; Phase 2 `--only 1`; Phase 3 `--chain`; Phase 4 policy; `--frames 145`; all backend flags removed. |
| `tests/test_ltx_movie_offline.py` | Modify | 12 tests deleted, the tests listed in spec §11.1 rewritten, 4 new tests. |
| `bin/ltx-story-images` | Modify | `_write_seed_panel` goes through `ltx_image_fit`; `_resize_center_crop` deleted; help text updated. |
| `tests/test_ltx_story_images.py` | Modify | I9 and `_marker_image` deleted, I10 rewritten. |
| `bin/ltx-story-manifest` | Modify | `--chain`, schema v3, docstring. |
| `bin/ltx-mlx-render` | Modify | Backend removal (P1/P3); v3 `load_manifest`; `build_units`; provenance v2; chain helpers; chain loop; in-order dry-run prediction; v3 still-aspect preflight. |
| `tests/test_ltx_mlx_render.py` | Modify | 3 bridge tests deleted, R1/R3/R4/R18/R20/R22 rewritten, 10 new tests. |
| everything in the Global Constraints deletion list | **Delete** | Removed backends and tooling. |
| `z_image_skill.py`, `bin/ltx-story-video`, `bin/ltx-chain`, `bin/qwen-agent`, `tests/test_ltx_story_video.py`, `tests/check_ltx_no_grad.py`, `tests/test_ltx_t2v_offline.py`, `tests/test_story_server.py` | **Not touched** | Out of scope (spec §5.7, §7.4, §10, §13). |

**Architectural choices and rejected alternatives**
1. **The chain loop lives in `bin/ltx-mlx-render`** (spec Approach A). Rejected: looping per clip in `bin/ltx-movie`, which would put N subprocess round-trips and N dry-runs in the orchestrator and duplicate the resume logic. Rejected: ltx-2-mlx `extend`, which is believed broken on the distilled-only pack (spec §13.7).
2. **Geometry in one module, `ltx_image_fit.py`.** `bin/ltx-movie` loads it by path, inside function bodies. `bin/ltx-story-images` imports it inside `_write_seed_panel`. Rejected: separate copies per tool, because three divergent crop copies caused this bug. Rejected: putting it in `z_image_skill.py`, which imports torch at module scope.
3. **Chain-seed validation uses ffprobe and ffmpeg subprocesses, not PIL.** Test R2a forbids PIL in `bin/ltx-mlx-render`, and the render process must stay free of heavy imports.
4. **Chain provenance is keyed on the source clip's bytes plus the frame index**, not on the PNG's bytes. A change in ffmpeg's PNG encoder cannot cause a spurious cascade, while any real change to clip k-1 re-renders k onwards.
5. **Loop tests stub `render_panel` and run the real `main()` and `finish_run`. Extraction and brightness tests run real ffmpeg.** A stub-only test of ffmpeg argv would miss a wrong frame index; the real test catches it (mutation M7).
6. **No per-task commits** (G8).

---

## Task 0: Snapshot and baseline (before any edit)

**Files:** Create `.claude/snapshots/narrative-chain-pre-<ts>/` (gitignored by `/.claude/snapshots/` in `WS/.gitignore`). Modify only this plan document's Baseline table.

**Depends on:** nothing. **Blocks:** every other task.

- [ ] **Step 1: Take a compressed snapshot of all project files.** It is the only recovery path for the untracked files Task 1 deletes.
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
SNAP=.claude/snapshots/narrative-chain-pre-$(date +%Y%m%d%H%M%S)
mkdir -p "$SNAP"
git rev-parse HEAD > "$SNAP/HEAD.sha"
git rev-parse --abbrev-ref HEAD > "$SNAP/branch"
git status --porcelain > "$SNAP/status.txt"
git diff HEAD -- . > "$SNAP/tracked.diff"
git ls-files --others --exclude-standard -z | tar --null -czf "$SNAP/untracked.tar.gz" -T -
echo "snapshot: $SNAP"
tar -tzf "$SNAP/untracked.tar.gz" | wc -l
git ls-files --others --exclude-standard | wc -l
```
Expected: the two counts are equal (93 at planning time), `HEAD.sha` is `3a3422f…`, and `tracked.diff` is non-empty.

- [ ] **Step 2: Run every §12.1 gate file directly and record the baseline.**
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
for f in tests/test_ltx_movie_offline.py tests/test_ltx_mlx_render.py tests/test_ltx_story_images.py tests/test_ltx2_mlx_video_skill.py tests/check_ltx2_mlx_no_forbidden_imports.py; do
  python3 "$f" > "/private/tmp/claude-502/baseline_$(basename $f).txt" 2>&1; rc=$?
  echo "$f rc=$rc last=$(tail -1 /private/tmp/claude-502/baseline_$(basename $f).txt)"
done
ls tests/test_ltx_image_fit.py tests/test_ltx_story_manifest_chain.py 2>&1
```
Copy each `rc=` and `last=` value into the table below. The planner observed these values on 2026-09-24; if the executor's values differ, record the difference and report it rather than proceeding silently.

**Baseline table (fill in):**

| Gate file | Planner-observed | Executor-observed |
|---|---|---|
| tests/test_ltx_movie_offline.py | rc 1; aborts with `ModuleNotFoundError: comfyui_mlx_video_skill` in `test_bridge_movie_preflight_precedes_all_work`. With the two bridge tests skipped in-process: 217/250, every failure a P2 `KeyError: 'image_rules'` except L15y. | rc 1; last line `ModuleNotFoundError: No module named 'comfyui_mlx_video_skill'`, raised from `bin/ltx-movie` line 1148 inside `test_bridge_movie_preflight_precedes_all_work` (matches planner) |
| tests/test_ltx_mlx_render.py | rc 1; `ModuleNotFoundError: comfyui_mlx_video_skill` at import (P1) | rc 1; last line `ModuleNotFoundError: No module named 'comfyui_mlx_video_skill'`, raised at import of `bin/ltx-mlx-render` line 48 (matches planner) |
| tests/test_ltx_story_images.py | rc 0; `OK 118/118` | rc 0; last line `OK 118/118` (matches planner) |
| tests/test_ltx2_mlx_video_skill.py | rc 0; `OK 133/133` | rc 0; last line `OK 133/133` (matches planner) |
| tests/check_ltx2_mlx_no_forbidden_imports.py | rc 0; `RESULT: ok` | rc 0; last line `RESULT: ok` (matches planner) |
| tests/test_ltx_image_fit.py | does not exist | confirmed: `ls` reports "No such file or directory" (matches planner) |
| tests/test_ltx_story_manifest_chain.py | does not exist | confirmed: `ls` reports "No such file or directory" (matches planner) |
| tests/test_ltx_story_video.py | not a gate (spec: TabError at import); not run | n/a (not run, per brief) |

- [ ] **Step 3: Checkpoint (do NOT commit, G8).** Success: the snapshot exists and the counts match, and the Baseline table is filled in this file.

---

## Task 1: Delete the ComfyUI / wan / cctech / deploy code, tests, scripts and docs

**Files:** delete everything listed in Step 1. Nothing is modified.

**Depends on:** Task 0. **Blocks:** Task 12's grep and `test -e` gates.

- [ ] **Step 1: Delete, in exactly this order.** If any command is refused by the permission system, **STOP**. Return the list of paths not yet deleted to the user verbatim. Do not stub or overwrite anything.
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
git rm -q wan_video_skill.py bin/wan-generate wan_ceiling.json tests/test_wan_video_skill_offline.py
rm -r comfyui_custom_nodes scripts/deploy
rm comfyui_video_skill.py comfyui_video_supervisor.py comfyui_split_video.py \
   cctech_ltx25_convert.py cctech_ltx25_cpu.py cctech_ltx25_decoder.py cctech_ltx25_mlx.py \
   cctech_ltx25_q8_layers.json cctech_ltx25_requantize.py cctech_ltx25_runtime.py cctech_ltx25_source.py
rm scripts/cctech_conv_decode_ab.py scripts/cctech_repin_outputs.py scripts/cctech_repin_sources.py \
   scripts/comfyui_frogjump_ab.py scripts/comfyui_frogjump_cpu_diagnostic.py \
   scripts/verify_cctech_conversion.py scripts/verify_cctech_requantization.py
rm tests/test_cctech_ltx25_convert.py tests/test_cctech_ltx25_cpu.py tests/test_cctech_ltx25_decoder.py \
   tests/test_cctech_ltx25_mlx.py tests/test_cctech_ltx25_requantize.py tests/test_cctech_ltx25_runtime.py \
   tests/test_cctech_ltx25_source.py \
   tests/test_comfyui_frogjump_cpu_diagnostic.py tests/test_comfyui_mlx_nodes.py tests/test_comfyui_mlx_video_skill.py \
   tests/test_comfyui_split_nodes.py tests/test_comfyui_split_video.py tests/test_comfyui_video_skill.py \
   tests/test_comfyui_video_supervisor.py \
   tests/test_verify_cctech_conversion.py tests/test_deploy_package.py \
   tests/fixtures/cctech_component_oracle.py tests/fixtures/split_video_surviving_descendant_supervisor.py \
   tests/fixtures/mlx_surviving_descendants_supervisor.py tests/fixtures/mlx_affine_int8_g64.json
rm docs/comfyui-mlx-backend.md docs/comfyui-mlx-validation.md docs/comfyui-video-skill.md \
   docs/superpowers/specs/2026-09-14-comfyui-ltx25-frogjump-ab-render.md \
   docs/superpowers/specs/2026-09-15-comfyui-video-skill-design.md \
   docs/superpowers/specs/2026-09-17-usb-deployment-package-spec.md \
   docs/superpowers/specs/2026-09-17-usb-deployment-package-spec.rev1.md \
   docs/superpowers/specs/2026-09-17-usb-deployment-package-spec.rev2.md \
   docs/superpowers/specs/2026-09-17-usb-deployment-package-spec.rev3.md \
   docs/superpowers/specs/2026-09-17-usb-deployment-package-spec.rev3.1.md \
   docs/superpowers/specs/2026-09-17-usb-deployment-package-spec-review.md \
   docs/superpowers/specs/2026-09-17-usb-deployment-package-spec-rev2-review.md \
   docs/superpowers/specs/2026-09-17-usb-deployment-package-spec-rev3-review.md \
   docs/superpowers/specs/2026-09-17-usb-deployment-package-tooling-review.md
rm docs/superpowers/plans/2026-09-15-comfyui-capacity-next-steps.md \
   docs/superpowers/plans/2026-09-15-comfyui-recovery-stability-proposal.md \
   docs/superpowers/plans/2026-09-15-comfyui-skill-progress.md \
   docs/superpowers/plans/2026-09-15-comfyui-split-process-implementation.md \
   docs/superpowers/plans/2026-09-15-comfyui-video-skill-implementation.md \
   docs/superpowers/plans/2026-09-16-cctech-conversion-contract.md \
   docs/superpowers/plans/2026-09-16-cctech-full-pipeline.md \
   docs/superpowers/plans/2026-09-16-cctech-q8-requantize-plan-review.md \
   docs/superpowers/plans/2026-09-16-cctech-q8-requantize-plan.md \
   docs/superpowers/plans/2026-09-16-cctech-runtime-contract.md \
   docs/superpowers/plans/2026-09-16-cctech-smaller-quant-investigation.md \
   docs/superpowers/plans/2026-09-16-comfyui-mlx-backend-progress.md \
   docs/superpowers/plans/2026-09-16-comfyui-mlx-backend.md \
   docs/superpowers/plans/2026-09-17-cctech-decode-gpu-options.md \
   docs/superpowers/plans/2026-09-17-cctech-decode-speedup-plan-review.md \
   docs/superpowers/plans/2026-09-17-cctech-decode-speedup-plan.md \
   docs/superpowers/plans/2026-09-17-cctech-decode-speedup-plan.rev1.md \
   docs/superpowers/plans/2026-09-17-deployment-package-inventory.md
```
Do not delete `tests/check_ltx_no_grad.py`, `tests/test_ltx_t2v_offline.py`, `tests/test_story_server.py`, `docs/superpowers/plans/2026-09-17-story-server-*.md`, `docs/superpowers/plans/2026-09-17-seed-image-vision-route-options.md`, any `__pycache__` directory, or the now-empty `tests/fixtures/` directory. A sourceless `.pyc` inside `__pycache__` is not importable (PEP 3147).

- [ ] **Step 2: Verify every path is gone.**
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
for p in wan_video_skill.py bin/wan-generate wan_ceiling.json tests/test_wan_video_skill_offline.py comfyui_custom_nodes scripts/deploy comfyui_video_skill.py comfyui_video_supervisor.py comfyui_split_video.py cctech_ltx25_convert.py cctech_ltx25_cpu.py cctech_ltx25_decoder.py cctech_ltx25_mlx.py cctech_ltx25_q8_layers.json cctech_ltx25_requantize.py cctech_ltx25_runtime.py cctech_ltx25_source.py scripts/cctech_conv_decode_ab.py scripts/cctech_repin_outputs.py scripts/cctech_repin_sources.py scripts/comfyui_frogjump_ab.py scripts/comfyui_frogjump_cpu_diagnostic.py scripts/verify_cctech_conversion.py scripts/verify_cctech_requantization.py tests/test_deploy_package.py tests/test_verify_cctech_conversion.py tests/fixtures/cctech_component_oracle.py tests/fixtures/split_video_surviving_descendant_supervisor.py tests/fixtures/mlx_surviving_descendants_supervisor.py tests/fixtures/mlx_affine_int8_g64.json docs/comfyui-mlx-backend.md docs/comfyui-mlx-validation.md docs/comfyui-video-skill.md; do test -e "$p" && echo "STILL PRESENT: $p"; done
ls tests/test_cctech_* tests/test_comfyui_* docs/superpowers/specs/*usb-deployment* docs/superpowers/specs/*comfyui* docs/superpowers/plans/*comfyui* docs/superpowers/plans/*cctech* docs/superpowers/plans/*deployment-package* 2>&1 | grep -v "No such file" ; echo "verify done"
/usr/bin/grep -rlI -E "comfyui_|cctech_|wan_video_skill|wan-generate|COMFY_MLX|video_backend|video-backend" bin *.py tests scripts --exclude-dir=__pycache__ | sort
```
Expected: no `STILL PRESENT` line, no leftover `ls` hit. The grep lists **exactly** `bin/ltx-mlx-render`, `bin/ltx-movie`, `tests/check_ltx_no_grad.py`, `tests/test_ltx_mlx_render.py`, `tests/test_ltx_movie_offline.py`, `tests/test_ltx_t2v_offline.py`, `tests/test_story_server.py`. The four non-allowlisted files are fixed in Tasks 4 and 8.

- [ ] **Step 3: Regression check on suites that must stay green.**
```bash
python3 tests/test_ltx_story_images.py; echo rc=$?
python3 tests/test_ltx2_mlx_video_skill.py; echo rc=$?
python3 tests/check_ltx2_mlx_no_forbidden_imports.py; echo rc=$?
```
Expected: rc 0 with `OK 118/118`; rc 0 with `OK 133/133`; rc 0 with `RESULT: ok`.

- [ ] **Step 4: Checkpoint (no commit).** Success: Step 2 and Step 3 are exactly as expected. `git status` shows the four `D ` staged deletions, and every pre-existing ` M` is unchanged.

---

## Task 2: `ltx_image_fit.py`, the no-crop geometry module

**Files:** Create `ltx_image_fit.py` and `tests/test_ltx_image_fit.py`.

**Interfaces produced (consumed by Tasks 5 and 6):** `load_oriented_rgb(path) -> PIL.Image.Image`; `fit_pad_px(src_w, src_h, width, height) -> (int, int, int)`; `derive_video_dims(src_w, src_h) -> (W, H, pad_px)`, which raises `ValueError`; `fit_letterbox(img, width, height) -> PIL.Image.Image`; plus the eight constants.

**Depends on:** Task 0.

- [ ] **Step 1: Write the failing test.** Create `tests/test_ltx_image_fit.py`:
```python
"""Plain-python (no pytest) offline tests for ltx_image_fit.py.

Run: python3 tests/test_ltx_image_fit.py
Prints PASS/FAIL per case, then "OK n/n" and exits 0, or exits 1 on any
failure. Offline only. GOLDEN is spec 2026-09-24 section 5.2, verbatim.
"""

import ast
import math
import os
import sys
import tempfile

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import ltx_image_fit as fit  # noqa: E402

_MODULE_PATH = os.path.join(WS, "ltx_image_fit.py")

TOTAL = 0
FAILED = 0


def check(name, condition, detail=""):
    global TOTAL, FAILED
    TOTAL += 1
    if condition:
        print("PASS %s" % name)
    else:
        FAILED += 1
        print("FAIL %s %s" % (name, detail))


GOLDEN = (
    ((704, 448), (704, 448, 0)),
    ((1280, 704), (704, 384, 6)),
    ((1920, 1080), (576, 320, 7)),
    ((1080, 1920), (320, 576, 7)),
    ((4032, 3024), (512, 384, 0)),
    ((3024, 4032), (384, 512, 0)),
    ((6000, 4000), (576, 384, 0)),
    ((1024, 1024), (512, 512, 0)),
    ((2560, 1080), (768, 320, 9)),
    ((1170, 2532), (320, 704, 11)),
    ((3000, 1000), (960, 320, 0)),
    ((1000, 3000), (320, 960, 0)),
    ((935, 1000), (512, 576, 28)),
    ((4000, 3000), (512, 384, 0)),
    ((800, 600), (512, 384, 0)),
    ((396, 704), (320, 576, 7)),
    ((1280, 427), (960, 320, 1)),
    ((704, 704), (512, 512, 0)),
)

RANGE_MESSAGE_3001 = ("seed image is 3001x1000 (aspect ratio 3.001:1), outside the supported "
                      "range 1:3 to 3:1; supply a seed image whose width/height ratio is "
                      "between 0.333 and 3.0")


def _value_error(fn, *a):
    try:
        fn(*a)
    except ValueError as e:
        return str(e)
    return None


def test_constants():
    for name, want in (("GRID_PX", 64), ("MIN_CELLS", 5), ("MAX_CELLS", 15),
                       ("MAX_AREA_CELLS", 77), ("MIN_AREA_CELLS", 40),
                       ("PAD_TOLERANCE_PX", 8), ("DEFAULT_VIDEO_WIDTH", 704),
                       ("DEFAULT_VIDEO_HEIGHT", 448)):
        got = getattr(fit, name, None)
        check("F0 %s == %d" % (name, want), got == want, "got %r" % (got,))


def test_fit_pad_px():
    check("F1a 1280x704 into 704x384 fills the height and leaves 6 px of width",
          fit.fit_pad_px(1280, 704, 704, 384) == (698, 384, 6),
          "got %r" % (fit.fit_pad_px(1280, 704, 704, 384),))
    check("F1b an exact-aspect source has no pad",
          fit.fit_pad_px(4000, 3000, 512, 384) == (512, 384, 0),
          "got %r" % (fit.fit_pad_px(4000, 3000, 512, 384),))
    check("F1c a tall source fills the height and pads the width",
          fit.fit_pad_px(400, 800, 512, 384) == (192, 384, 320),
          "got %r" % (fit.fit_pad_px(400, 800, 512, 384),))


def test_golden_table():
    for (w, h), want in GOLDEN:
        try:
            got = fit.derive_video_dims(w, h)
        except ValueError as e:
            got = "ValueError: %s" % e
        check("F1 %dx%d -> %r" % (w, h, want), got == want, "got %r" % (got,))


def test_range_errors():
    msg = _value_error(fit.derive_video_dims, 3001, 1000)
    check("F2a 3001x1000 (just wider than 3:1) raises ValueError", msg is not None)
    check("F2b the message is exactly the spec text", msg == RANGE_MESSAGE_3001, "got %r" % msg)
    msg = _value_error(fit.derive_video_dims, 1000, 3001)
    check("F2c 1000x3001 (just taller than 1:3) raises ValueError naming the range",
          msg is not None and "1:3 to 3:1" in msg and "1000x3001" in msg, "got %r" % msg)
    check("F2d exactly 3:1 is accepted", fit.derive_video_dims(3000, 1000) == (960, 320, 0))
    check("F2e exactly 1:3 is accepted", fit.derive_video_dims(1000, 3000) == (320, 960, 0))


def test_ratio_sweep():
    bad = []
    lo, hi = math.log(1 / 3.0), math.log(3.0)
    for i in range(2001):
        r = math.exp(lo + i * (hi - lo) / 2000)
        w, h = int(round(3000 * r)), 3000
        try:
            W, H, pad = fit.derive_video_dims(w, h)
        except ValueError as e:
            bad.append((w, h, "ValueError", str(e)))
            continue
        if (W % 64 or H % 64 or not 320 <= W <= 960 or not 320 <= H <= 960
                or (W // 64) * (H // 64) > 77 or pad < 0):
            bad.append((w, h, W, H, pad))
    check("F3 2001 log-spaced ratios 1:3..3:1: every size is a 64-multiple, each edge in "
          "[320, 960], area <= 77 cells", not bad, "first failures %r" % bad[:5])


def _letterbox_source(w, h):
    """Red field, a blue centred square, and a green marker touching the middle of
    each of the four edges."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (w, h), (255, 0, 0))
    draw = ImageDraw.Draw(img)
    sq = max(4, min(w, h) // 5)
    left, top = (w - sq) // 2, (h - sq) // 2
    draw.rectangle([left, top, left + sq - 1, top + sq - 1], fill=(0, 0, 255))
    e = max(4, min(w, h) // 10)
    draw.rectangle([(w - e) // 2, 0, (w - e) // 2 + e - 1, e - 1], fill=(0, 255, 0))
    draw.rectangle([(w - e) // 2, h - e, (w - e) // 2 + e - 1, h - 1], fill=(0, 255, 0))
    draw.rectangle([0, (h - e) // 2, e - 1, (h - e) // 2 + e - 1], fill=(0, 255, 0))
    draw.rectangle([w - e, (h - e) // 2, w - 1, (h - e) // 2 + e - 1], fill=(0, 255, 0))
    return img


def _green(p):
    return p[1] > 128 and p[0] < 128 and p[2] < 128


def test_fit_letterbox():
    W, H = 512, 384
    for w, h in ((800, 400), (400, 800), (1000, 1000), (2000, 600), (100, 100)):
        label = "%dx%d" % (w, h)
        out = fit.fit_letterbox(_letterbox_source(w, h), W, H)
        check("F5a %s output is exactly 512x384 RGB" % label,
              out.size == (W, H) and out.mode == "RGB", "got %r %r" % (out.size, out.mode))
        new_w, new_h, _pad = fit.fit_pad_px(w, h, W, H)
        x0, y0 = (W - new_w) // 2, (H - new_h) // 2
        pad_ok = True
        blue_x, blue_y = [], []
        for idx, p in enumerate(out.getdata()):
            x, y = idx % W, idx // W
            inside = x0 <= x < x0 + new_w and y0 <= y < y0 + new_h
            if not inside and p != (0, 0, 0):
                pad_ok = False
            if p[2] > 128 and p[0] < 128 and p[1] < 128:
                blue_x.append(x)
                blue_y.append(y)
        check("F5b %s every pad pixel is (0,0,0)" % label, pad_ok)
        check("F5c %s the centred square marker survives" % label, bool(blue_x))
        if blue_x:
            bw = max(blue_x) - min(blue_x) + 1
            bh = max(blue_y) - min(blue_y) + 1
            cx = (min(blue_x) + max(blue_x) + 1) / 2.0
            cy = (min(blue_y) + max(blue_y) + 1) / 2.0
            check("F5d %s the marker stays square (+-2 px)" % label, abs(bw - bh) <= 2,
                  "got %dx%d" % (bw, bh))
            check("F5e %s the marker stays centred (+-2 px)" % label,
                  abs(cx - W / 2.0) <= 2 and abs(cy - H / 2.0) <= 2,
                  "got (%.1f, %.1f)" % (cx, cy))
        edges = (out.getpixel((x0 + new_w // 2, y0 + 1)),
                 out.getpixel((x0 + new_w // 2, y0 + new_h - 2)),
                 out.getpixel((x0 + 1, y0 + new_h // 2)),
                 out.getpixel((x0 + new_w - 2, y0 + new_h // 2)))
        check("F5f %s markers at all four source edges survive (never cropped)" % label,
              all(_green(p) for p in edges), "got %r" % (edges,))


def test_load_oriented_rgb():
    from PIL import Image
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "exif6.jpg")
        img = Image.new("RGB", (400, 300), (200, 10, 10))
        exif = img.getexif()
        exif[0x0112] = 6
        img.save(path, format="JPEG", exif=exif)
        with Image.open(path) as raw:
            stored = raw.size
        out = fit.load_oriented_rgb(path)
        check("F7a the fixture JPEG is stored 400x300", stored == (400, 300), "got %r" % (stored,))
        check("F7b Orientation=6 is applied: 300x400", out.size == (300, 400),
              "got %r" % (out.size,))
        check("F7c the result is RGB", out.mode == "RGB", "got %r" % out.mode)
        check("F7d the oriented size derives the portrait geometry (384, 512, 0)",
              fit.derive_video_dims(*out.size) == (384, 512, 0),
              "got %r" % (fit.derive_video_dims(*out.size),))
        rgba = os.path.join(td, "rgba.png")
        Image.new("RGBA", (64, 64), (1, 2, 3, 128)).save(rgba, format="PNG")
        check("F7e an RGBA PNG loads as RGB", fit.load_oriented_rgb(rgba).mode == "RGB")


def test_no_toplevel_pil():
    with open(_MODULE_PATH) as f:
        tree = ast.parse(f.read(), filename=_MODULE_PATH)
    top = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            top += [a.name for a in node.names if a.name.split(".")[0] == "PIL"]
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "PIL":
            top.append(node.module)
    check("F8a no top-level PIL import", not top, "found %r" % top)
    in_func = any(isinstance(sub, ast.ImportFrom) and sub.module == "PIL"
                  for node in tree.body if isinstance(node, ast.FunctionDef)
                  for sub in ast.walk(node))
    check("F8b PIL is imported inside a function body", in_func)
    doc = ast.get_docstring(tree) or ""
    check("F8c the docstring states the no-crop policy, the 64 px grid source and the "
          "only measured area",
          "No-crop policy" in doc and "snap_output_dimensions" in doc and "704x448" in doc,
          "docstring=%r" % doc[:300])


if __name__ == "__main__":
    test_constants()
    test_fit_pad_px()
    test_golden_table()
    test_range_errors()
    test_ratio_sweep()
    test_fit_letterbox()
    test_load_oriented_rgb()
    test_no_toplevel_pil()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
```

- [ ] **Step 2: Run the test and confirm it fails.** Run `python3 tests/test_ltx_image_fit.py; echo rc=$?`. Expected: `ModuleNotFoundError: No module named 'ltx_image_fit'` and `rc=1`.

- [ ] **Step 3: Write the implementation.** Create `ltx_image_fit.py`:
```python
"""ltx_image_fit -- derive the ltx-2-mlx video geometry from a seed image, and fit
images into it without ever cropping them.

No-crop policy. Nothing in the ltx-movie pipeline crops the seed image. The video's
width and height are derived from the seed's own aspect ratio (derive_video_dims),
and the seed is then scaled to FIT inside that size with one uniform factor and
centred on a black canvas (fit_letterbox). The only padding is the residual gap the
64 px grid cannot close; up to PAD_TOLERANCE_PX of it counts as "no bar".

The 64 px grid. ltx-2-mlx's distilled pipeline is two-stage, and it calls
snap_output_dimensions(height, width, two_stage=True)
(ltx-core-mlx/src/ltx_core_mlx/components/patchifiers.py:127-177), which silently
floors both width and height to multiples of 64. Every size this module returns is a
multiple of GRID_PX, so the snap is a no-op, and ltx-2-mlx's two I2V conditioning
resizes (half size and full size) are exact scalings of a W x H still: its
resize_and_center_crop crops nothing.

The area cap. 704x448 (77 cells of 64x64) is the ONLY resolution ever measured on the
MLX path (acceptance run A1: 704x448 x 241 frames, 160 s per panel, 13.5 GiB), so
derived sizes never exceed that area. Raising the cap is a follow-up gated on a
hardware measurement.

Stdlib-only at import time: PIL is imported inside the functions that need it, so
bin/ltx-movie --dry-run and the offline tests can load this module without Pillow.
"""

GRID_PX = 64            # ltx-2-mlx two-stage snap modulus (patchifiers.py snap_output_dimensions)
MIN_CELLS = 5           # 320 px minimum edge; stage-1 half-size edge 160 px = 5 latent cells
MAX_CELLS = 15          # 960 px maximum edge; with MIN_CELLS this bounds aspect to [1:3, 3:1]
MAX_AREA_CELLS = 77     # 704*448 / 64**2 -- the only MLX-measured area (acceptance run A1)
MIN_AREA_CELLS = 40     # 163,840 px = 0.52x of 704x448; resolution floor
PAD_TOLERANCE_PX = 8    # total residual pad (width deficit + height deficit) treated as "no bar"
DEFAULT_VIDEO_WIDTH = 704
DEFAULT_VIDEO_HEIGHT = 448


def load_oriented_rgb(path):
    """Open path, apply its EXIF orientation, and return it as an RGB image.

    Every exception (missing file, not an image, Pillow not importable) propagates
    to the caller, which owns the error message."""
    from PIL import Image, ImageOps
    with Image.open(path) as img:
        img.load()
        out = ImageOps.exif_transpose(img).convert("RGB")
    return out


def fit_pad_px(src_w, src_h, width, height):
    """(new_w, new_h, pad_px) for scaling src_w x src_h to FIT inside width x height
    with one uniform factor. pad_px is the total residual gap: the width deficit plus
    the height deficit. Pure."""
    s = min(width / src_w, height / src_h)
    new_w = min(width, max(1, round(src_w * s)))
    new_h = min(height, max(1, round(src_h * s)))
    return new_w, new_h, (width - new_w) + (height - new_h)


def derive_video_dims(src_w, src_h):
    """(W, H, pad_px): the video geometry for a src_w x src_h seed. Pure and
    deterministic.

    Candidates are every (a, b) cell pair with MIN_CELLS <= a, b <= MAX_CELLS and
    MIN_AREA_CELLS <= a*b <= MAX_AREA_CELLS, at W = a*GRID_PX, H = b*GRID_PX. If any
    candidate leaves at most PAD_TOLERANCE_PX of residual pad, the largest area wins
    (ties: smaller pad, then larger a). Otherwise the smallest pad wins (ties: larger
    area, then larger a). Raises ValueError for a seed outside 1:3 .. 3:1; exactly
    3:1 and exactly 1:3 are accepted (integer comparison, no float rounding)."""
    if src_w * MIN_CELLS > src_h * MAX_CELLS or src_w * MAX_CELLS < src_h * MIN_CELLS:
        raise ValueError(
            "seed image is %dx%d (aspect ratio %.3f:1), outside the supported range 1:3 to "
            "3:1; supply a seed image whose width/height ratio is between 0.333 and 3.0"
            % (src_w, src_h, src_w / src_h))
    candidates = []
    for a in range(MIN_CELLS, MAX_CELLS + 1):
        for b in range(MIN_CELLS, MAX_CELLS + 1):
            if MIN_AREA_CELLS <= a * b <= MAX_AREA_CELLS:
                width, height = a * GRID_PX, b * GRID_PX
                pad = fit_pad_px(src_w, src_h, width, height)[2]
                candidates.append((a, b, width, height, pad))
    within = [c for c in candidates if c[4] <= PAD_TOLERANCE_PX]
    if within:
        best = min(within, key=lambda c: (-(c[0] * c[1]), c[4], -c[0]))
    else:
        best = min(candidates, key=lambda c: (c[4], -(c[0] * c[1]), -c[0]))
    return best[2], best[3], best[4]


def fit_letterbox(img, width, height):
    """img scaled to fit width x height (LANCZOS, one uniform factor) and pasted,
    centred, onto a black RGB width x height canvas. Never crops: the only non-image
    pixels are the residual gap fit_pad_px reports."""
    from PIL import Image
    new_w, new_h, _pad = fit_pad_px(img.width, img.height, width, height)
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    canvas.paste(resized, ((width - new_w) // 2, (height - new_h) // 2))
    return canvas
```

- [ ] **Step 4: Run the test and confirm it passes.** Run `python3 tests/test_ltx_image_fit.py; echo rc=$?`. Expected: no `FAIL` line, a final `OK n/n` with both numbers equal, and `rc=0`. (The planner validated the golden table, the sweep, the letterbox markers and the EXIF behaviour against a reference implementation on this host.)

- [ ] **Step 5: Checkpoint (no commit).** Success: rc 0, and `python3 -c "import ast,sys; t=ast.parse(open('ltx_image_fit.py').read()); print([n for n in t.body if isinstance(n,(ast.Import,ast.ImportFrom))])"` prints `[]`.

---

## Task 3: Tighten `validate_geometry` to 64-multiples

**Files:** Modify `ltx2_mlx_video_skill.py` (the function `validate_geometry`, currently lines 83-100) and `tests/test_ltx2_mlx_video_skill.py` (the function `test_validate_geometry`).

**Depends on:** Task 0.

- [ ] **Step 1: Write the failing test.** In `tests/test_ltx2_mlx_video_skill.py`, append these lines at the end of the body of `test_validate_geometry()`, directly after the `M3g` check and before the `# M3b: _resolve_bin` banner:
```python
    msg = _raises_value_error(skill.validate_geometry, 736, 448, 145)
    check("M3h (geometry) width 736 -- a 32- but not 64-multiple -- is rejected naming "
          "'multiple of 64'", msg is not None and "width" in msg and "multiple of 64" in msg,
          "got %r" % msg)
    msg = _raises_value_error(skill.validate_geometry, 704, 480, 145)
    check("M3i (geometry) height 480 is rejected", msg is not None and "height" in msg
          and "multiple of 64" in msg, "got %r" % msg)
    check("M3j (geometry) the 64x64x9 minimum is accepted",
          skill.validate_geometry(64, 64, 9) is None)
    msg = _raises_value_error(skill.validate_geometry, 736, 448, 145)
    check("M3k (geometry) the width message is the spec text",
          msg == "width must be a multiple of 64 (ltx-2-mlx distilled two-stage floors to 64; "
                 "patchifiers.py snap_output_dimensions), got 736", "got %r" % msg)
    msg = _raises_value_error(skill.validate_geometry, 0, 448, 9)
    check("M3l (geometry) the minimum message is the spec text",
          msg == "width must be >= 64, got 0", "got %r" % msg)
```

- [ ] **Step 2: Run the test and confirm it fails.** Run `python3 tests/test_ltx2_mlx_video_skill.py; echo rc=$?`. Expected: `FAIL M3h (geometry)…`, `FAIL M3i (geometry)…`, `FAIL M3k…`, `FAIL M3l…`, then `rc=1`.

- [ ] **Step 3: Write the implementation.** Replace the whole `validate_geometry` function with:
```python
def validate_geometry(width, height, num_frames):
    """Raise ValueError unless width/height are multiples of 64 (and at least 64) and
    num_frames sits on the 8k+1 lattice at or above 9. The distilled pipeline is
    two-stage and silently floors both edges to multiples of 64 (ltx-core-mlx
    patchifiers.py snap_output_dimensions), so a 32-multiple such as 736 would render
    at 704 and only then fail render_panel's uniformity check, after the full GPU
    spend. The VAE silently crops off-lattice frame counts instead of erroring, so
    this check is the only thing standing between a typo and a silently shorter
    clip."""
    if width % 64 != 0:
        raise ValueError("width must be a multiple of 64 (ltx-2-mlx distilled two-stage "
                         "floors to 64; patchifiers.py snap_output_dimensions), got %d" % width)
    if width < 64:
        raise ValueError("width must be >= 64, got %d" % width)
    if height % 64 != 0:
        raise ValueError("height must be a multiple of 64 (ltx-2-mlx distilled two-stage "
                         "floors to 64; patchifiers.py snap_output_dimensions), got %d" % height)
    if height < 64:
        raise ValueError("height must be >= 64, got %d" % height)
    if (num_frames - 1) % 8 != 0:
        raise ValueError("num_frames must satisfy (num_frames - 1) %% 8 == 0, got %d"
                         % num_frames)
    if num_frames < 9:
        raise ValueError("num_frames must be >= 9, got %d" % num_frames)
```
Do not touch anything else in this file, including the `DEFAULT_WIDTH` comment.

- [ ] **Step 4: Run the tests and confirm they pass.** Run `python3 tests/test_ltx2_mlx_video_skill.py; echo rc=$?` and expect `OK n/n` with `rc=0`. Kept checks M3b, M3c, M3f, M3g, M5c and M5d still pass: 700, 481, 0 and -32 are still rejected and 1024x576 is still accepted. Then run `python3 tests/check_ltx2_mlx_no_forbidden_imports.py; echo rc=$?` and expect `RESULT: ok` with `rc=0`.

- [ ] **Step 5: Checkpoint (no commit).**

---

## Task 4: `bin/ltx-movie`: chained templates, `build_story_prompt(seconds=)`, validator, backend flag removal

**Files:** Modify `bin/ltx-movie` and `tests/test_ltx_movie_offline.py`.

**Interfaces produced:**
- `build_story_prompt(narrative, story_id, panels, no_stills=False, seed_image=False, *, seconds)`
- `_clip_seconds(args) -> str`
- `_validate_story_md(story_md_path, expected_panels, no_stills=False)`
- `_chain_image_warnings(panels) -> list[str]`

**Depends on:** Task 1 (the bridge tests referenced deleted modules). **Blocks:** Tasks 5 and 11.

- [ ] **Step 1: Test-file surgery (delete, rewrite, add).** In `tests/test_ltx_movie_offline.py`:

1a. Add three imports at the top, after `import ast`:
```python
import contextlib
import inspect
import io
```

1b. **Delete** these top-level functions, together with the `# ---` banner comment blocks directly above each: `test_seed_preface_specifies_style_field`, `test_seed_preface_drops_verbatim_repetition`, `test_validate_story_md_require_style`, `test_require_style_call_site_guard`, `test_seed_preface_bans_restated_appearance`, `test_style_echo_warnings`, `test_style_echo_call_site_guard`, `test_style_content_warnings`, `test_band_prompt_and_content_call_site`, `test_comfyui_mlx_backend_flags`, `test_bridge_movie_preflight_precedes_all_work`, `test_bridge_movie_cli_without_pythonpath`. Also delete the module-level fixtures that only they use: `_ECHO_STYLE`, `_ECHO_BAD_IMAGE`, `_ECHO_GOOD_IMAGE`, `_ECHO_GREEK`, `_echo_panels`, `_BAND_GOOD_STYLE`, `_BAND_ECHO_STYLE_HITS`, and their comment lines. Keep `_StoryServerArgs`, `_phase_names`, `_write_md`, `_is_main_guard`.

1c. **Replace** `test_story_prompt_template` entirely with:
```python
def test_story_prompt_template():
    prompt = ltx_movie.build_story_prompt("some narrative", "some_id", 5, seconds="6")
    for phrase in ("ONE continuous take", "exact last frame", "Panel 1 has exactly three fields",
                   "Every later panel has exactly two fields", "15-35 words"):
        check("L5a prompt contains %r" % phrase, phrase in prompt, "got %r" % prompt[:800])
    check("L5b no Style: field anywhere", "Style:" not in prompt, "got %r" % prompt)
    check("L5c no braces survive rendering", "{" not in prompt and "}" not in prompt,
          "got %r" % prompt)
    check("L5d no image_rules placeholder", "image_rules" not in prompt)
    check("L5e formats narrative, story_id and panels",
          "some narrative" in prompt and '"some_id"' in prompt
          and "EXACTLY 5 panel sections" in prompt, "got %r" % prompt[:800])
    check("L5f formats the per-clip seconds", "built 6 seconds at a time" in prompt
          and "a 6-second continuation" in prompt, "got %r" % prompt[:800])
    check("L5g is exactly the template formatted with the four placeholders",
          prompt == ltx_movie.STORY_PROMPT_TEMPLATE.format(
              narrative="some narrative", story_id="some_id", panels=5, seconds="6"))
    check("L5h the stop-after-write terminator is kept",
          "Once the write_file call returns, stop immediately" in prompt)
    for no_stills in (False, True):
        for seed_image in (False, True):
            try:
                p = ltx_movie.build_story_prompt("n", "sid", 3, no_stills, seed_image, seconds="6")
                ok = "{" not in p and "}" not in p
            except KeyError:
                ok = False
            check("L5i no_stills=%s seed_image=%s renders without KeyError or braces"
                  % (no_stills, seed_image), ok)
    try:
        ltx_movie.build_story_prompt("n", "sid", 3)
        raised = False
    except TypeError:
        raised = True
    check("L5j seconds is keyword-only and required", raised)
```

1d. **Replace** `test_validate_story_md_missing_motion` entirely with:
```python
def test_validate_story_md_missing_motion():
    with tempfile.TemporaryDirectory() as td:
        good = _write_md(td, "good.md",
                         "# Story\n\n## Panel 1 — First\nImage: a scene one\n"
                         "Motion: she turns\nNarration: one.\n\n"
                         "## Panel 2 — Second\nMotion: she walks away\nNarration: two.\n")
        check("L7a panel 1 with three fields + panel 2 with two fields is valid",
              ltx_movie._validate_story_md(good, 2) == [],
              "got %r" % ltx_movie._validate_story_md(good, 2))

        no_motion_2 = _write_md(td, "no_motion_2.md",
                                "# Story\n\n## Panel 1 — First\nImage: a scene one\n"
                                "Motion: she turns\nNarration: one.\n\n"
                                "## Panel 2 — Second\nNarration: two.\n")
        v = ltx_movie._validate_story_md(no_motion_2, 2)
        check("L7b panel 2 missing Motion: is a violation",
              "panel 2: missing/empty Motion: field" in v, "got %r" % v)

        no_image_1 = _write_md(td, "no_image_1.md",
                               "# Story\n\n## Panel 1 — First\nMotion: she turns\n"
                               "Narration: one.\n\n"
                               "## Panel 2 — Second\nMotion: she walks away\nNarration: two.\n")
        v = ltx_movie._validate_story_md(no_image_1, 2)
        check("L7c panel 1 missing Image: is a violation",
              "panel 1: missing/empty Image: field" in v, "got %r" % v)

        image_2 = _write_md(td, "image_2.md",
                            "# Story\n\n## Panel 1 — First\nImage: a scene one\n"
                            "Motion: she turns\nNarration: one.\n\n"
                            "## Panel 2 — Second\nImage: an old-format picture\n"
                            "Motion: she walks away\nNarration: two.\n")
        check("L7d an Image: on panel 2 is NOT a violation (old-format story.md still renders)",
              ltx_movie._validate_story_md(image_2, 2) == [],
              "got %r" % ltx_movie._validate_story_md(image_2, 2))
        w = ltx_movie._chain_image_warnings(ltx_movie._load_story_panels(image_2))
        check("L7e it produces exactly one advisory warning naming panel 2",
              w == ["panel 2: has an Image: field, which is ignored -- panels after the first "
                    "continue from the previous clip's last frame"], "got %r" % w)
        check("L7f a panel-1-only Image: produces no warning",
              ltx_movie._chain_image_warnings(ltx_movie._load_story_panels(good)) == [])

        prompt_2 = _write_md(td, "prompt_2.md",
                             "# Story\n\n## Panel 1 — First\nImage: a scene one\n"
                             "Motion: she turns\nNarration: one.\n\n"
                             "## Panel 2 — Second\nPrompt: a collapsed field\n"
                             "Motion: she walks away\nNarration: two.\n")
        v = ltx_movie._validate_story_md(prompt_2, 2)
        check("L7g a Prompt: field in stills mode is a violation",
              "panel 2: has a Prompt: field; the chained flow expects Image:, Motion: and "
              "Narration: on panel 1 and Motion: and Narration: on later panels" in v,
              "got %r" % v)
        check("L7h the require_style parameter is gone",
              "require_style" not in inspect.signature(ltx_movie._validate_story_md).parameters)

    with open(_SCRIPT_PATH) as f:
        text = f.read()
    check("L7i the chain-image warning loop is guarded by --no-stills and appears once",
          text.count('    if not args.no_stills:\n'
                     '        for w in _chain_image_warnings(_load_story_panels(story_md)):\n'
                     '            print("Warning: %s" % w)\n') == 1)
    orphans = ("_style_echo_warnings", "_style_content_warnings", "_content_words", "_ECHO_",
               "_STYLE_BANNED_TOKENS", "require_style")
    check("L7j the Style-echo machinery is gone from bin/ltx-movie",
          not any(o in text for o in orphans) and "\nimport re\n" not in text,
          "still present: %r" % [o for o in orphans if o in text])
```

1e. **Replace** `test_no_stills_story_prompt_template` entirely with the following. It is identical to the current test except that L15m checks `6 seconds`, L15y is dropped (G3), L15j/L15k use `seconds=`, and L15i is kept:
```python
def test_no_stills_story_prompt_template():
    p = ltx_movie.build_story_prompt("some narrative", "some_id", 7, no_stills=True, seconds="6")
    check("L15a contains Prompt:", "Prompt: <" in p, "got %r" % p[:400])
    check("L15b contains Narration:", "Narration: <" in p)
    check("L15c keeps the VERBATIM consistency rule", "VERBATIM" in p)
    check("L15d states the rule applies to the Prompt: field",
          "full visual description in the Prompt: field" in p)
    check("L15e no Image: field", "Image: <" not in p)
    check("L15f no Motion: field", "Motion: <" not in p)
    check("L15g forbids emitting the old fields",
          "Do not emit an Image: or Motion: field." in p)
    check("L15h word band is 150-220", "150-220 words" in p, "got %r" % p[:600])
    check("L15l Prompt: line asks for a 7-10 sentence chronological paragraph",
          "one flowing paragraph of 7-10 sentences" in p
          and "in strict chronological order" in p, "got %r" % p[:1400])
    check("L15m Prompt: line demands enough beats to fill the clip's seconds",
          "fill the full 6 seconds instead of rushing the action" in p
          and "ten seconds" not in p, "got %r" % p[:1400])
    check("L15n Prompt: line no longer carries the old single-take framing",
          "ONE CONTINUOUS TEN-SECOND TAKE" not in p, "got %r" % p[:900])
    check("L15o Prompt: line keeps the no-cuts / no-new-plot rule",
          "no cuts, no new plot information beyond what this shot shows" in p,
          "got %r" % p[:900])
    check("L15p Prompt: line states the gemma4 caption element order",
          all(s in p for s in ("opens with the main action", "visible physical attributes",
                               "the setting and background", "the shot type",
                               "the lighting and colour"))
          and [p.index(s) for s in ("opens with the main action", "visible physical attributes",
                                    "the setting and background", "the shot type",
                                    "the lighting and colour")]
              == sorted(p.index(s) for s in ("opens with the main action",
                                             "visible physical attributes",
                                             "the setting and background", "the shot type",
                                             "the lighting and colour")),
          "got %r" % p[:1400])
    check("L15q a style line bans abstract mood words and the old intensifier rule is gone",
          'never "she looks sad" or any other mood word' in p
          and '"a vibrant crimson dress"' not in p, "got %r" % p[:1400])
    check("L15s Prompt: line names the temporal connectors",
          '"initially", "as", "then", "while", "simultaneously", "a moment later"' in p,
          "got %r" % p[:1400])
    check("L15t Prompt: line and style line both demand the present tense",
          p.count("in the present tense") >= 2, "got %r" % p[:1400])
    check("L15u Prompt: line prescribes the LTX shot-type vocabulary",
          "extreme wide shot, wide shot, medium shot, medium close-up, close-up, "
          "extreme close-up" in p, "got %r" % p[:1400])
    check("L15v Prompt: line prescribes the LTX camera-viewpoint vocabulary",
          "front-facing, back-facing, side view, over-the-shoulder, top-down, "
          "low-angle or high-angle" in p, "got %r" % p[:1400])
    check("L15w Prompt: line always states camera motion",
          "if the camera holds, say that it remains static" in p, "got %r" % p[:1400])
    check("L15x a style line requires a soundscape and forbids dialogue",
          "Sound is part of the shot" in p and "write no spoken dialogue" in p,
          "got %r" % p[:1400])
    check("L15r a style line bans scene-opener phrasing",
          'never open with "The scene opens with", "We see" or "There is"' in p,
          "got %r" % p[:900])
    check("L15i formats narrative/story_id/panels",
          "some narrative" in p and "some_id" in p and "EXACTLY 7 panel sections" in p)
    check("L15j equals the no-stills template formatted with the four placeholders",
          p == ltx_movie.STORY_PROMPT_TEMPLATE_NO_STILLS.format(
              narrative="some narrative", story_id="some_id", panels=7, seconds="6"))
    check("L15k seed_image=True does not change the no-stills prompt",
          ltx_movie.build_story_prompt("some narrative", "some_id", 7, True, True,
                                       seconds="6") == p)
```

1f. **Replace** `test_seed_prompt_preface` entirely with:
```python
def test_seed_prompt_preface():
    pre = ltx_movie.SEED_IMAGE_PREFACE
    post = ltx_movie.SEED_IMAGE_POSTFACE
    p_off = ltx_movie.build_story_prompt("n", "sid", 5, seconds="6")
    p_on = ltx_movie.build_story_prompt("n", "sid", 5, False, True, seconds="6")
    check("L25a the unseeded prompt is the plain template",
          p_off == ltx_movie.STORY_PROMPT_TEMPLATE.format(narrative="n", story_id="sid",
                                                          panels=5, seconds="6"))
    check("L25b the preface sentence appears only when seeded",
          "An image is attached to this message." in p_on
          and "An image is attached to this message." not in p_off)
    check("L25c the seeded prompt starts with SEED_IMAGE_PREFACE", p_on.startswith(pre))
    check("L25d the seeded prompt is preface + unseeded template + postface, exactly",
          p_on == pre + "\n\n" + p_off + "\n\n" + post, "got tail %r" % p_on[-400:])
    check("L25e the preface says the attached image IS the first frame",
          "IS the first frame" in pre)
    for phrase in ("faithful, literal description of what the attached image actually shows",
                   "not a generative prompt",
                   "Panel 1's Motion: must start from the exact pose and position shown in "
                   "the attached image."):
        check("L25f the preface contains %r" % phrase[:60], phrase in pre)
    check("L25g neither the preface nor the postface mentions Style: or FAR BAND",
          all("Style:" not in t and "FAR BAND" not in t for t in (pre, post)))
    check("L25h the assembled seeded prompt carries no Style: and no FAR BAND",
          "Style:" not in p_on and "FAR BAND" not in p_on)
    check("L25i --no-stills wins over --seed-image",
          ltx_movie.build_story_prompt("n", "sid", 5, True, True, seconds="6")
          == ltx_movie.build_story_prompt("n", "sid", 5, True, False, seconds="6"))
```

1g. **Replace** `test_seed_postface_overrides_last` entirely, keeping its L34 banner, with:
```python
def test_seed_postface_overrides_last():
    p_on = ltx_movie.build_story_prompt("n", "sid", 5, False, True, seconds="6")
    p_off = ltx_movie.build_story_prompt("n", "sid", 5, seconds="6")
    post = ltx_movie.SEED_IMAGE_POSTFACE
    check("L34a the postface is present only when seeded", post in p_on and post not in p_off)
    check("L34b the postface is the tail of the seeded prompt", p_on.endswith(post))
    check("L34c the seeded prompt starts with the preface",
          p_on.startswith(ltx_movie.SEED_IMAGE_PREFACE))
    check("L34d the postface restates the three-field / two-field contract",
          "Panel 1 has exactly three fields -- Image:, Motion:, Narration: --" in post
          and "Every later panel has exactly two fields -- Motion:, Narration: --" in post)
    check("L34e the postface ends with the template's own terminator",
          post.endswith("Do not verify the file with run_python or any other tool. "
                        "Emit no other text."))
    check("L34f the template's two-field rule appears BEFORE the postface restates it",
          p_on.index("Every later panel has exactly two fields, in this order")
          < p_on.index(post))
    check("L34g neither the preface nor the postface mentions Style: or FAR BAND",
          "Style:" not in post and "FAR BAND" not in post
          and "Style:" not in ltx_movie.SEED_IMAGE_PREFACE
          and "FAR BAND" not in ltx_movie.SEED_IMAGE_PREFACE)
```

1h. In `test_dry_run_prints_phases_and_prompt`, replace the last `check(...)` (the one about `'Do not verify the file with run_python'`) with:
```python
    check("L2 stdout contains the rendered template's no-verify instruction",
          "do NOT run run_python or any other tool to check it" in result.stdout,
          "stdout=%r" % result.stdout[:2000])
```

1i. In `test_removed_flags_rejected`, replace the tuple of `(flag, value)` pairs with the following (G15: the removed flag is built by concatenation):
```python
    # "--video-" + "backend": the spec's grep gate (12.1 item 5) must not match test sources.
    for flag, value in (("--min-frames", "25"), ("--max-frames", "57"),
                        ("--target-seconds", "30"), ("--keep-down", None),
                        ("--reanchor-every", "3"), ("--video-" + "backend", "mlx")):
```

1j. In `test_default_dry_run_plan_unchanged`, replace the `L18l` check with:
```python
    check("L18l default plan carries the chained story template",
          "Every later panel has exactly two fields" in out
          and "Motion: <110-160 words" not in out and "ONE CONTINUOUS TEN-SECOND TAKE" not in out,
          "got %r" % out)
```

1k. **Replace** the whole `if __name__ == "__main__":` block with:
```python
if __name__ == "__main__":
    test_parser_defaults()
    test_removed_flags_rejected()
    test_dry_run_prints_phases_and_prompt()
    test_ast_guard_no_toplevel_heavy_imports()
    test_sudo_n_not_sudo_s()
    test_story_prompt_template()
    test_lock_state()
    test_validate_story_md_missing_motion()
    test_resolve_length_math()
    test_length_conflicts()
    test_length_too_short()
    test_length_100_panels_and_tokens()
    test_phase1_scaling()
    test_phase1_nonzero_rc_checks_story_md_before_failing()
    test_no_stills_default()
    test_no_stills_orthogonal_to_length()
    test_no_stills_story_prompt_template()
    test_validate_story_md_no_stills()
    test_no_stills_phase_sequencing_source()
    test_no_stills_dry_run_plan()
    test_default_dry_run_plan_unchanged()
    test_phase1_qwen_agent_gets_workspace_flag()
    test_top5_rss_skips_none_memory_info()
    test_dry_run_plan_targets_mlx_render()
    test_seed_prompt_preface()
    test_phase0_seed_image()
    test_seed_dry_run_plan()
    test_seed_no_stills_conflict()
    test_seed_source_guards()
    test_seed_postface_overrides_last()
    test_story_server_flag_default()
    test_phase_sequence_ordering()
    test_phase_release_story_server()
    test_dry_run_story_server_block_ordering()
    test_dry_run_no_story_server_block_by_default()
    test_dry_run_story_server_block_with_no_stills()
    test_story_server_source_guards()
    test_main_block_completeness()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
```

- [ ] **Step 2: Run the test and confirm it fails.** Run `python3 tests/test_ltx_movie_offline.py; echo rc=$?`. Expected: `rc=1`. The first new test to fail is L2 (the dry-run still raises `KeyError: 'image_rules'`). Once the script reaches it, `test_story_prompt_template` raises `TypeError`/`KeyError`, because `seconds` is unknown and `{image_rules}` is unfilled.

- [ ] **Step 3: Write the implementation in `bin/ltx-movie`.**

3a. Delete the line `import re` (line 79). Its only user is `_content_words`, which is deleted in 3g.

3b. Replace `STORY_PROMPT_TEMPLATE` (lines 94-115) wholesale with:
```python
STORY_PROMPT_TEMPLATE = """You are authoring the shot list for a short narrated movie (story-id "{story_id}").

Narrative to adapt:
{narrative}

How this movie is made: it is ONE continuous take, built {seconds} seconds at a time. Panel 1's Image: field is rendered as a single still picture, and that picture becomes the movie's first frame. Every later panel is a {seconds}-second continuation that starts from the exact last frame of the panel before it. The picture is never re-described after Panel 1: the characters, their appearance, the setting, the lighting and the style all carry forward automatically from the frames already on screen. There are no cuts, no scene changes and no jumps in time or place between panels. If the story needs a new location, a new prop or a new character, it must arrive through visible movement inside a panel -- someone walks through a door, turns a corner, or picks something up.

Write the complete story to generated/stories/{story_id}/story.md using the write_file tool. The file must contain EXACTLY {panels} panel sections, numbered 1 through {panels} in order.

Panel 1 has exactly three fields, in this order:

## Panel 1 — <short title>
Image: <120-170 words describing the movie's opening frame as one still picture: every character who is on screen, each with their full visual description (apparent age group, build, skin tone, hair colour, length and style, clothing and accessories), where each one stands and which way they face, the setting and background, the lighting and colour palette, the shot type (exactly one of: extreme wide shot, wide shot, medium shot, medium close-up, close-up, extreme close-up), the camera viewpoint, and the rendering style. Introduce each character with a short referring phrase of at most four words, such as "the woman in grey", and use that exact phrase for them everywhere else in the file.>
Motion: <25-50 words: what the characters physically do during these first {seconds} seconds, and how the camera moves -- or that it stays static.>
Narration: <one sentence of voice-over narration>

Every later panel has exactly two fields, in this order, and no Image: field:

## Panel N — <short title>
Motion: <15-35 words in one or two plain sentences: what the characters physically do during these {seconds} seconds, continuing from where the previous panel left them. Name each character only by their referring phrase from Panel 1, word for word. Give at most two actions, and only actions that fit inside {seconds} seconds. Do not describe appearance, clothing, setting, lighting, colour, style, camera or lens -- all of that is already on screen.>
Narration: <one sentence of voice-over narration; vary the sentence length across panels rather than repeating a similar length every time>

Give the story a narrative arc -- an introduction, a middle, a climax and a conclusion -- carried by what the characters do from panel to panel and by the narration. Each panel should move the action forward instead of repeating the previous panel's movement.

Write the file in a single write_file call. Trust your first draft: do NOT read the file back, do NOT run run_python or any other tool to check it, and do NOT count or recount words. Once the write_file call returns, stop immediately and emit no further text or tool calls."""
```

3c. In `STORY_PROMPT_TEMPLATE_NO_STILLS` (line 131), change exactly the substring `carrying enough separate beats to fill the full ten seconds instead of rushing the action` to `carrying enough separate beats to fill the full {seconds} seconds instead of rushing the action`. Change nothing else in that template; the `Rules:` block stays as it is.

3d. Replace `SEED_IMAGE_PREFACE` (lines 140-160) and `SEED_IMAGE_POSTFACE` (lines 162-169) wholesale with:
```python
SEED_IMAGE_PREFACE = """An image is attached to this message. It IS the first frame of this movie: the pipeline uses the attached image itself as Panel 1's picture, so nothing you write is rendered into Panel 1's picture.

Before you write anything, look closely at the attached image. Panel 1's Image: field must be a faithful, literal description of what the attached image actually shows -- each person's apparent age group, build and body shape, skin tone, eye shape and colour, hair colour, length, style and texture, clothing and accessories, their pose and where they are in the frame, the setting, the lighting, the colour palette and the visual style. It is not a generative prompt, not an embellishment and not an invention: do not add people, objects or scenery that are not visible in the attached image, do not leave out the ones that are, and do not change anyone's age, gender or physical attributes unless the narrative directs it. Choose each person's short referring phrase from what is actually visible.

Panel 1's Motion: must start from the exact pose and position shown in the attached image."""

SEED_IMAGE_POSTFACE = """Reminder, because the attached image is the first frame: Panel 1 has exactly three fields -- Image:, Motion:, Narration: -- and its Image: field literally describes the attached image. Every later panel has exactly two fields -- Motion:, Narration: -- with no Image: field and no appearance, clothing, setting, lighting, style or camera words; characters are named only by their Panel 1 referring phrase.

Do not verify the file with run_python or any other tool. Emit no other text."""
```

3e. Replace `build_story_prompt` (lines 172-182) with the following. The postface comment is kept verbatim, as spec §6.1 requires:
```python
def build_story_prompt(narrative, story_id, panels, no_stills=False, seed_image=False, *,
                       seconds):
    template = STORY_PROMPT_TEMPLATE_NO_STILLS if no_stills else STORY_PROMPT_TEMPLATE
    rendered = template.format(narrative=narrative, story_id=story_id, panels=panels,
                               seconds=seconds)
    if seed_image and not no_stills:
        # The postface goes AFTER the rendered template on purpose. The template's
        # VERBATIM-repetition rule and its 70-90 word Image: budget are concrete and
        # imperative; a preface-only override of them sits ~1000 words upstream and lost
        # to them in the 2026-09-13 drift_red_test run, where every later panel re-typed
        # the full appearance list. Restating the two overrides last is the fix.
        return SEED_IMAGE_PREFACE + "\n\n" + rendered + "\n\n" + SEED_IMAGE_POSTFACE
    return rendered
```

3f. Delete the argument line `parser.add_argument("--video-backend", choices=["mlx", "comfyui-mlx"], default="mlx")` (line 220). In `_render_flags`, delete the line `"--video-backend", args.video_backend,` (line 313). In `main()`, delete the whole `if args.video_backend == "comfyui-mlx":` block (lines 1146-1159, through its `return 2`).

3g. Add `_clip_seconds` directly after `_target_seconds` (after line 297):
```python
def _clip_seconds(args):
    """The per-clip playback length the story templates quote, rounded to whole
    seconds: "6" at the defaults (145 frames @ 24 fps = 6.04 s)."""
    return "%.0f" % (args.frames / args.fps)
```

3h. Replace `_validate_story_md` (lines 394-450) with:
```python
def _validate_story_md(story_md_path, expected_panels, no_stills=False):
    """Load bin/ltx-story-manifest via SourceFileLoader and validate
    story_md_path against it. Returns a list of violation strings (empty list ==
    valid).

    Always: exactly expected_panels panels.
    Stills mode (the chained flow): panel 1 has non-empty Image:/Motion:/Narration:
    fields, every later panel has non-empty Motion:/Narration: fields, and no panel
    has a Prompt: field. An Image: field on a later panel is NOT a violation -- an
    old-format story.md still renders; the field is ignored and
    _chain_image_warnings reports it.
    --no-stills: every panel has non-empty Prompt:/Narration: fields and neither
    Image: nor Motion:.
    """
    violations = []
    manifest_tool_path = os.path.join(WS, "bin", "ltx-story-manifest")
    try:
        story_manifest = importlib.machinery.SourceFileLoader(
            "ltx_story_manifest_for_movie", manifest_tool_path
        ).load_module()
        _narrative, panels = story_manifest._parse_prompts_md(story_md_path)
    except OSError as e:
        return ["cannot read story.md: %s" % e]

    if len(panels) != expected_panels:
        violations.append(
            "expected exactly %d panels, found %d" % (expected_panels, len(panels))
        )

    for idx, p in enumerate(panels):
        num = p["number"]
        if no_stills:
            for label, key in (("Prompt", "prompt"), ("Narration", "narration")):
                if not p[key].strip():
                    violations.append("panel %d: missing/empty %s: field" % (num, label))
            if p["prompt"].strip() and (p["image"].strip() or p["motion"].strip()):
                violations.append(
                    "panel %d: has both Prompt: and Image:/Motion: fields; "
                    "--no-stills expects Prompt: only" % num
                )
        else:
            if idx == 0:
                required = (("Image", "image"), ("Motion", "motion"), ("Narration", "narration"))
            else:
                required = (("Motion", "motion"), ("Narration", "narration"))
            for label, key in required:
                if not p[key].strip():
                    violations.append("panel %d: missing/empty %s: field" % (num, label))
            if p["prompt"].strip():
                violations.append(
                    "panel %d: has a Prompt: field; the chained flow expects Image:, Motion: "
                    "and Narration: on panel 1 and Motion: and Narration: on later panels" % num
                )

    return violations
```

3i. Delete `_ECHO_STOPWORDS`, `_ECHO_MIN_STYLE_WORDS`, `_ECHO_MIN_OVERLAP`, `_ECHO_FRACTION` and their comments (lines 453-468). Delete `_content_words` (471-476), `_style_echo_warnings` (499-552), `_STYLE_BANNED_TOKENS` and its comment (555-574), and `_style_content_warnings` (577-608). **Keep** `_load_story_panels` exactly as it is. Directly after `_load_story_panels`, add:
```python
def _chain_image_warnings(panels):
    """Advisory warnings (never fatal): an Image: field on any panel after the first is
    ignored, because panels after the first continue from the previous clip's last
    frame. An old-format story.md written before the chained flow therefore still
    renders."""
    return ["panel %d: has an Image: field, which is ignored -- panels after the first "
            "continue from the previous clip's last frame" % p["number"]
            for p in panels[1:] if p["image"].strip()]
```

3j. In `phase1_story`, change the `prompt = build_story_prompt(...)` call (lines 761-762) to:
```python
        prompt = build_story_prompt(args.narrative, args.story_id, args.panels, args.no_stills,
                                     bool(getattr(args, "seed_image", None)),
                                     seconds=_clip_seconds(args))
```
Replace lines 807-808 (the `require_style = ...` line and the `violations = _validate_story_md(...)` line) with:
```python
    violations = _validate_story_md(story_md, args.panels, args.no_stills)
```
Replace lines 824-834 (the comment block and the two `for warning in ...` loops) with:
```python
    # Advisory only -- never changes the return code. Printed after the story dump so a
    # human reviewing it sees it directly above the prompt they are about to answer, and
    # printed under --no-review too so it lands in movie.log. An old-format story.md with
    # Image: on later panels still renders; those fields are ignored (spec D10).
    if not args.no_stills:
        for w in _chain_image_warnings(_load_story_panels(story_md)):
            print("Warning: %s" % w)
```

3k. In `_print_dry_run_plan`, change the `prompt = build_story_prompt(...)` call (lines 1045-1046) to:
```python
    prompt = build_story_prompt(args.narrative, args.story_id, args.panels, args.no_stills,
                                 bool(getattr(args, "seed_image", None)),
                                 seconds=_clip_seconds(args))
```

- [ ] **Step 4: Run the tests and confirm they pass.**
```bash
python3 tests/test_ltx_movie_offline.py; echo rc=$?
python3 bin/ltx-movie "a test narrative" --story-id gate-dry --dry-run --no-review > /private/tmp/claude-502/dry.txt; echo rc=$?
/usr/bin/grep -c '[{}]' /private/tmp/claude-502/dry.txt
```
Expected: the suite prints `OK n/n` with `rc=0`; the dry run gives `rc=0`; the grep count is `0` (P2 fixed).

- [ ] **Step 5: Checkpoint (no commit).** Success: Step 4 exactly as stated. `/usr/bin/grep -c "video_backend\|video-backend\|comfyui" bin/ltx-movie` prints `0`.

---

## Task 5: `bin/ltx-movie`: Phase 0 seed geometry, derived video dims, Phase 2 `--only 1`

**Files:** Modify `bin/ltx-movie` and `tests/test_ltx_movie_offline.py`.

**Interfaces produced:**
- `_image_fit()` (loads `ltx_image_fit.py` by path)
- `_seed_geometry(seed_path) -> (violations, geometry|None, img|None)`
- `_prepare_seed_image(seed_path, out_path) -> (violations, geometry|None)`
- `_seed_geometry_line(seed_path, src_size, geometry, llm_path) -> str`
- `_still_size(args) -> (w, h)`

**Depends on:** Tasks 2 and 4. **Blocks:** Task 11.

- [ ] **Step 1: Write the failing tests** in `tests/test_ltx_movie_offline.py`.

1a. In `test_parser_defaults`, replace the four lines checking `image_width`, `image_height`, `video_width` and `video_height` with:
```python
    check("L1 no --image-width/--image-height any more (the still size is derived)",
          not hasattr(args, "image_width") and not hasattr(args, "image_height"))
    check("L1 video_width defaults to None (derived from the seed, or 704 in main)",
          args.video_width is None, "got %r" % args.video_width)
    check("L1 video_height defaults to None (derived from the seed, or 448 in main)",
          args.video_height is None, "got %r" % args.video_height)
    check("L1 no video-backend attribute", not hasattr(args, "video_" + "backend"))
```

1b. In `test_removed_flags_rejected`, extend the tuple from Task 4 1i to end with `("--video-" + "backend", "mlx"), ("--image-width", "1280"), ("--image-height", "704")):`.

1c. **Replace** `test_phase0_seed_image` entirely with:
```python
def test_phase0_seed_image():
    from PIL import Image, ImageChops, ImageDraw

    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "out.png")

        missing = os.path.join(tmp, "missing.png")
        v, g = ltx_movie._prepare_seed_image(missing, out_path)
        check("L26a missing file -> violation names 'not found'",
              any("not found" in s for s in v), "got %r" % v)
        check("L26a missing file -> no geometry and no output",
              g is None and not os.path.exists(out_path))

        junk = os.path.join(tmp, "junk.png")
        with open(junk, "w") as f:
            f.write("not a real image xx")
        v, g = ltx_movie._prepare_seed_image(junk, out_path)
        check("L26b unreadable file -> violation names 'not a readable image'",
              any("not a readable image" in s for s in v) and g is None, "got %r" % v)

        tiny = os.path.join(tmp, "tiny.png")
        Image.new("RGB", (32, 32), (1, 2, 3)).save(tiny, format="PNG")
        v, g = ltx_movie._prepare_seed_image(tiny, out_path)
        check("L26c 32x32 -> violation names 'degenerate' and '32x32'",
              any("degenerate" in s and "32x32" in s for s in v) and g is None, "got %r" % v)

        big = os.path.join(tmp, "big.png")
        Image.new("RGB", (4000, 3000), (4, 5, 6)).save(big, format="PNG")
        v, g = ltx_movie._prepare_seed_image(big, out_path)
        check("L26d 4000x3000 -> no violations, geometry (512, 384, 0)",
              v == [] and g == (512, 384, 0), "got %r %r" % (v, g))
        with Image.open(out_path) as img:
            check("L26d the story-model copy is a 1024x768 PNG",
                  img.size == (1024, 768) and img.format == "PNG",
                  "got %r %r" % (img.size, img.format))

        under = os.path.join(tmp, "under.png")
        Image.new("RGB", (800, 600), (7, 8, 9)).save(under, format="PNG")
        v, g = ltx_movie._prepare_seed_image(under, out_path)
        check("L26e 800x600 -> (512, 384, 0)", v == [] and g == (512, 384, 0), "got %r %r" % (v, g))
        with Image.open(out_path) as img:
            check("L26e the copy is 1024x768", img.size == (1024, 768), "got %r" % (img.size,))

        at_cap = os.path.join(tmp, "at_cap.png")
        Image.new("RGB", (1024, 1024), (10, 11, 12)).save(at_cap, format="PNG")
        v, g = ltx_movie._prepare_seed_image(at_cap, out_path)
        check("L26f 1024x1024 -> (512, 512, 0)", v == [] and g == (512, 512, 0), "got %r %r" % (v, g))
        with Image.open(out_path) as img:
            check("L26f the copy is 1024x1024", img.size == (1024, 1024), "got %r" % (img.size,))

        rgba = os.path.join(tmp, "rgba.png")
        Image.new("RGBA", (200, 200), (1, 2, 3, 128)).save(rgba, format="PNG")
        v, g = ltx_movie._prepare_seed_image(rgba, out_path)
        check("L26g RGBA input -> no violations", v == [], "got %r" % v)
        with Image.open(out_path) as img:
            check("L26g the copy is RGB", img.mode == "RGB", "got %r" % img.mode)

        wide = os.path.join(tmp, "wide.png")
        Image.new("RGB", (3001, 1000), (13, 14, 15)).save(wide, format="PNG")
        wide_out = os.path.join(tmp, "wide_out.png")
        v, g = ltx_movie._prepare_seed_image(wide, wide_out)
        check("L26h 3001x1000 -> a violation naming '1:3 to 3:1', nothing written",
              any("1:3 to 3:1" in s for s in v) and g is None and not os.path.exists(wide_out),
              "got %r %r" % (v, g))

        exif_path = os.path.join(tmp, "phone.jpg")
        stored = Image.new("RGB", (400, 300), (200, 10, 10))
        exif = stored.getexif()
        exif[0x0112] = 6
        stored.save(exif_path, format="JPEG", exif=exif)
        v, g = ltx_movie._prepare_seed_image(exif_path, out_path)
        check("L26i a JPEG stored 400x300 with EXIF Orientation=6 -> (384, 512, 0)",
              v == [] and g == (384, 512, 0), "got %r %r" % (v, g))

        # L26j: the story-model copy and panel_01.png frame the SAME picture -- equal
        # aspect within 1 px of rounding, and a centred marker stays centred in both.
        src = Image.new("RGB", (900, 600), (255, 0, 0))
        draw = ImageDraw.Draw(src)
        left, top = int(round(450 - 30)), int(round(300 - 30))
        draw.rectangle([left, top, left + 60 - 1, top + 60 - 1], fill=(0, 0, 0))
        src_path = os.path.join(tmp, "marker.png")
        src.save(src_path, format="PNG")
        llm_out = os.path.join(tmp, "llm.png")
        panel_out = os.path.join(tmp, "panel_01.png")
        v, g = ltx_movie._prepare_seed_image(src_path, llm_out)
        ltx_story_images._write_seed_panel(src_path, panel_out, 576, 384)
        with Image.open(llm_out) as a, Image.open(panel_out) as b:
            a, b = a.convert("RGB"), b.convert("RGB")
            check("L26j 900x600 -> geometry (576, 384, 0) and a 1024x683 copy",
                  g == (576, 384, 0) and a.size == (1024, 683), "got %r %r" % (g, a.size))
            check("L26j the copy and panel_01.png have equal aspect within 1 px",
                  b.size == (576, 384) and abs(a.size[1] - a.size[0] * b.size[1] / float(b.size[0])) <= 1.0,
                  "got %r vs %r" % (a.size, b.size))
            for label, img in (("copy", a), ("panel_01", b)):
                bbox = ImageChops.difference(img, Image.new("RGB", img.size, (255, 0, 0))).getbbox()
                ok = bbox is not None and \
                    abs((bbox[0] + bbox[2]) / 2.0 - img.size[0] / 2.0) <= 2 and \
                    abs((bbox[1] + bbox[3]) / 2.0 - img.size[1] / 2.0) <= 2
                check("L26j the marker is centred (+-2 px) in the %s" % label, ok,
                      "bbox=%r size=%r" % (bbox, img.size))

    story_id = "_test_phase0_seed_%d" % os.getpid()
    story_dir = ltx_movie._story_dir(story_id)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            valid_seed = os.path.join(tmp, "valid.png")
            Image.new("RGB", (800, 600), (1, 2, 3)).save(valid_seed, format="PNG")
            args = ltx_movie.build_parser().parse_args(
                ["n", "--story-id", story_id, "--seed-image", valid_seed])
            rc = ltx_movie.phase0_seed(args)
            expected_path = ltx_movie._story_paths(story_id)["seed_downscaled"]
            check("L26k phase0_seed returns 0 for a valid seed", rc == 0, "got %r" % rc)
            check("L26k args.seed_downscaled_path is the expected path",
                  getattr(args, "seed_downscaled_path", None) == expected_path,
                  "got %r" % getattr(args, "seed_downscaled_path", None))
            check("L26k args.video_width/video_height are the derived 512x384",
                  (args.video_width, args.video_height) == (512, 384),
                  "got %r" % ((args.video_width, args.video_height),))
            check("L26k args.seed_pad_px is the residual pad", getattr(args, "seed_pad_px", None) == 0)

            args2 = ltx_movie.build_parser().parse_args(
                ["n", "--story-id", story_id, "--seed-image", os.path.join(tmp, "nope.png")])
            check("L26l phase0_seed returns 2 for a missing seed", ltx_movie.phase0_seed(args2) == 2)
    finally:
        shutil.rmtree(story_dir, ignore_errors=True)
```

1d. **Replace** `test_seed_dry_run_plan` entirely with:
```python
def test_seed_dry_run_plan():
    from PIL import Image
    story_id = "unittest-seed-%d" % os.getpid()

    def _val(line, flag):
        t = line.split()
        return t[t.index(flag) + 1] if flag in t else None

    with tempfile.TemporaryDirectory() as tmp:
        seed = os.path.join(tmp, "seed1920.png")
        Image.new("RGB", (1920, 1080), (40, 50, 60)).save(seed, format="PNG")
        result = subprocess.run(
            [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", story_id,
             "--panels", "3", "--seed-image", seed, "--dry-run"],
            capture_output=True, text=True, cwd=WS)
        out = result.stdout
        check("L27a exits 0", result.returncode == 0,
              "rc=%r stderr=%r" % (result.returncode, result.stderr))
        check("L27b stdout contains a Phase 0 block", "--- Phase 0: seed image ---" in out,
              "got %r" % out[:1500])
        check("L27b2 Phase 0 prints the derived geometry and residual pad",
              "video geometry 576x320" in out and "residual pad 7 px" in out,
              "got %r" % out[:2000])

        m = re.search(r"Command \(subprocess timeout \d+s\): (.*)", out)
        check("L27c phase-1 command line found", m is not None, "got %r" % out[:1500])
        if m:
            check("L27c phase-1 command carries --image with a seed_downscaled.png path",
                  re.search(r"--image \S*seed_downscaled\.png", m.group(1)) is not None,
                  "got %r" % m.group(1))

        phase2_lines = [l for l in out.splitlines() if "ltx-story-images" in l]
        check("L27d exactly one phase-2 command line found", len(phase2_lines) == 1,
              "got %r" % phase2_lines)
        if phase2_lines:
            check("L27d phase 2 renders panel 1 only, at the derived video size",
                  "--only 1 --width 576 --height 320" in phase2_lines[0], "got %r" % phase2_lines[0])
            check("L27d phase-2 command carries --seed-image with the ORIGINAL path",
                  ("--seed-image " + seed) in phase2_lines[0], "got %r" % phase2_lines[0])
            check("L27d phase-2 command does not carry the downscaled path",
                  "seed_downscaled" not in phase2_lines[0], "got %r" % phase2_lines[0])
            check("L27f --seed-image appears exactly once in the ltx-story-images command line",
                  phase2_lines[0].count("--seed-image") == 1, "got %r" % phase2_lines[0])

        render_lines = [l for l in out.splitlines() if "ltx-mlx-render" in l]
        check("L27l both render commands carry the derived --width 576 --height 320",
              len(render_lines) == 2
              and all(_val(l, "--width") == "576" and _val(l, "--height") == "320"
                      for l in render_lines), "got %r" % render_lines)
        check("L27e rendered prompt preview contains the preface sentence",
              "An image is attached to this message." in out, "got %r" % out[-2000:])
        check("L27m the dry run wrote no story-model copy",
              not os.path.exists(ltx_movie._story_paths(story_id)["seed_downscaled"]))

        wide = os.path.join(tmp, "wide.png")
        Image.new("RGB", (3001, 1000), (1, 1, 1)).save(wide, format="PNG")
        r = subprocess.run([sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", story_id,
                            "--seed-image", wide, "--dry-run"],
                           capture_output=True, text=True, cwd=WS)
        check("L27k an out-of-range seed fails the dry run with exit 2 naming the bound",
              r.returncode == 2 and "1:3 to 3:1" in r.stderr,
              "rc=%r stderr=%r" % (r.returncode, r.stderr))

    r = subprocess.run([sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", story_id,
                        "--seed-image", "/nonexistent/seed_for_test.png", "--dry-run"],
                       capture_output=True, text=True, cwd=WS)
    check("L27j a missing seed fails the dry run with exit 2",
          r.returncode == 2 and "--seed-image not found" in r.stderr,
          "rc=%r stderr=%r" % (r.returncode, r.stderr))

    plain = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-seed-off",
         "--panels", "3", "--dry-run"],
        capture_output=True, text=True, cwd=WS)
    check("L27g non-seeded dry-run prints no Phase 0", "Phase 0" not in plain.stdout,
          "got %r" % plain.stdout[:800])
    m = re.search(r"Command \(subprocess timeout \d+s\): (.*)", plain.stdout)
    check("L27h non-seeded phase-1 command carries no --image flag",
          m is not None and "--image " not in m.group(1), "got %r" % (m.group(1) if m else None))
    check("L27i non-seeded dry-run mentions no seed_downscaled anywhere",
          "seed_downscaled" not in plain.stdout, "got %r" % plain.stdout)
```

1e. In `test_seed_source_guards`, replace the `pil_in_func` block and its `L29b` check (from `pil_in_func = False` through the end of that `check(...)`) with:
```python
    def _is_fit_loader(call):
        return (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "SourceFileLoader"
                and any(isinstance(n, ast.Constant) and isinstance(n.value, str)
                        and "ltx_image_fit.py" in n.value for n in ast.walk(call)))

    loader_in_func = loader_at_top = False
    for node in tree.body:
        found = any(_is_fit_loader(sub) for sub in ast.walk(node))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            loader_in_func = loader_in_func or found
        else:
            loader_at_top = loader_at_top or found
    check("L29b bin/ltx-movie loads ltx_image_fit.py only inside a function body",
          loader_in_func and not loader_at_top,
          "in_func=%r at_top=%r" % (loader_in_func, loader_at_top))
    fit_path = os.path.join(WS, "ltx_image_fit.py")
    with open(fit_path) as f:
        fit_tree = ast.parse(f.read(), filename=fit_path)
    fit_top_pil = [n for n in fit_tree.body
                   if (isinstance(n, ast.ImportFrom) and n.module and n.module.split(".")[0] == "PIL")
                   or (isinstance(n, ast.Import) and any(a.name.split(".")[0] == "PIL" for a in n.names))]
    check("L29b2 ltx_image_fit.py has no top-level PIL import", not fit_top_pil)
```

1f. In `test_dry_run_plan_targets_mlx_render`, replace the `L24j` check with:
```python
    check("L24j Phase 2 renders panel 1 only, at twice the video size",
          "--only 1 --width 1408 --height 896" in out, "got %r" % out)
```

1g. Add three new test functions directly above the `# L40-L47` banner:
```python
# ---------------------------------------------------------------------------
# L48-L50: derived geometry guards in main()
# ---------------------------------------------------------------------------

def test_seed_with_explicit_video_dims_rejected():
    for flag in (["--video-width", "704"], ["--video-height", "448"]):
        r = subprocess.run([sys.executable, _SCRIPT_PATH, "n", "--story-id", "unittest-seed-dims",
                            "--seed-image", "/nonexistent/x.png"] + flag + ["--dry-run"],
                           capture_output=True, text=True, cwd=WS)
        check("L48a %s with --seed-image exits 2" % flag[0], r.returncode == 2,
              "rc=%r stderr=%r" % (r.returncode, r.stderr))
        check("L48b %s: stderr says the geometry is derived from --seed-image" % flag[0],
              "derived from --seed-image" in r.stderr, "stderr=%r" % r.stderr)


def test_video_dims_must_be_64_multiples():
    def _run(extra):
        return subprocess.run([sys.executable, _SCRIPT_PATH, "n", "--story-id",
                               "unittest-dims64"] + extra + ["--dry-run"],
                              capture_output=True, text=True, cwd=WS)
    r = _run(["--video-width", "736"])
    check("L49a --video-width 736 exits 2 naming 'multiples of 64' and the size",
          r.returncode == 2 and "multiples of 64" in r.stderr and "736x448" in r.stderr,
          "rc=%r stderr=%r" % (r.returncode, r.stderr))
    check("L49b --video-height 480 exits 2", _run(["--video-height", "480"]).returncode == 2)
    check("L49c --video-width 0 exits 2", _run(["--video-width", "0"]).returncode == 2)
    ok = _run(["--video-width", "512", "--video-height", "512"])
    check("L49d a 512x512 request is accepted and reaches the render flags",
          ok.returncode == 0 and "--width 512 --height 512" in ok.stdout,
          "rc=%r stderr=%r" % (ok.returncode, ok.stderr))


def test_out_of_range_seed_fails_before_phase1():
    from PIL import Image
    calls = []
    story_id = "_test_out_of_range_%d" % os.getpid()
    saved = (ltx_movie.phase1_story, ltx_movie._check_sudo_and_start_keepalive)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            seed = os.path.join(tmp, "wide.png")
            Image.new("RGB", (3001, 1000), (9, 9, 9)).save(seed, format="PNG")
            ltx_movie.phase1_story = lambda args: (calls.append(args.story_id) or 0)
            ltx_movie._check_sudo_and_start_keepalive = lambda: None
            err, out = io.StringIO(), io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
                rc = ltx_movie.main(["a narrative", "--story-id", story_id,
                                     "--seed-image", seed, "--no-review"])
            check("L50a main() returns 2 for a 3001x1000 seed", rc == 2, "rc=%r" % rc)
            check("L50b phase1_story was never called", calls == [], "calls=%r" % calls)
            check("L50c stderr names the 1:3 to 3:1 bound", "1:3 to 3:1" in err.getvalue(),
                  "stderr=%r" % err.getvalue())
            check("L50d no story-model copy was written",
                  not os.path.exists(ltx_movie._story_paths(story_id)["seed_downscaled"]))
    finally:
        ltx_movie.phase1_story, ltx_movie._check_sudo_and_start_keepalive = saved
        shutil.rmtree(ltx_movie._story_dir(story_id), ignore_errors=True)
```

1h. In the `__main__` block, insert these three lines immediately before `    test_main_block_completeness()`:
```python
    test_seed_with_explicit_video_dims_rejected()
    test_video_dims_must_be_64_multiples()
    test_out_of_range_seed_fails_before_phase1()
```

- [ ] **Step 2: Run the test and confirm it fails.** Run `python3 tests/test_ltx_movie_offline.py; echo rc=$?`. Expected: `FAIL L1 no --image-width…`, `FAIL L1 video_width defaults to None…`, `FAIL L23 --image-width is rejected…`, then an `AttributeError: … '_prepare_seed_image'` traceback. `rc=1`.

- [ ] **Step 3: Write the implementation in `bin/ltx-movie`.**

3a. In `build_parser`:
- Delete the two lines `--image-width` / `--image-height` (lines 215-216).
- Change `--video-width` and `--video-height` to `default=None`:
```python
    parser.add_argument("--video-width", dest="video_width", type=int, default=None)
    parser.add_argument("--video-height", dest="video_height", type=int, default=None)
```
- Replace the `--seed-image` help string (lines 200-203) with:
```python
                         help="image that becomes the movie's literal first frame: Phase 0 "
                              "derives the video width/height from its aspect ratio (1:3 to "
                              "3:1) and attaches a scaled copy to the Phase 1 story prompt; "
                              "Phase 2 fits the ORIGINAL (scaled, never cropped) into "
                              "panel_01.png at the video size. Incompatible with --no-stills "
                              "and with --video-width/--video-height.")
```

3b. Replace the Phase 0 section, from `def _crop_to_fill` through the end of `phase0_seed` (lines 659-745), with:
```python
def _image_fit():
    """bin/ltx-movie's handle on ltx_image_fit.py, the no-crop geometry module. Loaded by
    path and only from inside function bodies, so importing this file stays stdlib-only
    and --dry-run works from any cwd with no PYTHONPATH."""
    return importlib.machinery.SourceFileLoader(
        "ltx_image_fit", os.path.join(WS, "ltx_image_fit.py")).load_module()


def _seed_geometry(seed_path):
    """Validate seed_path and derive the video geometry from it. Writes nothing.

    Returns (violations, geometry, img): ([], (W, H, pad_px), the EXIF-oriented RGB
    image) on success, or ([one violation], None, None) at the first problem."""
    if not os.path.isfile(seed_path):
        return ["--seed-image not found: %s" % seed_path], None, None
    try:
        fit = _image_fit()
        img = fit.load_oriented_rgb(seed_path)
    except ImportError as e:
        return ["--seed-image needs Pillow, which is not importable: %s" % e], None, None
    except Exception as e:
        return (["--seed-image is not a readable image: %s: %s" % (type(e).__name__, e)],
                None, None)
    if min(img.size) < SEED_MIN_EDGE:
        return (["--seed-image is degenerate: %dx%d (each edge must be at least %d px)"
                 % (img.size[0], img.size[1], SEED_MIN_EDGE)], None, None)
    try:
        geometry = fit.derive_video_dims(*img.size)
    except ValueError as e:
        return [str(e)], None, None
    return [], geometry, img


def _prepare_seed_image(seed_path, out_path):
    """Validate the seed, derive (W, H, pad_px), and write the story model's copy:
    frame 0 exactly as it will be rendered (the seed fitted into W x H, never cropped),
    scaled so its long edge is SEED_DOWNSCALE_MAX_EDGE. The vision model therefore sees
    the same aspect and relative pad as panel_01.png, at a size where faces are legible.

    Returns (violations, geometry). On any violation nothing is written."""
    violations, geometry, img = _seed_geometry(seed_path)
    if violations:
        return violations, None
    width, height, _pad = geometry
    k = SEED_DOWNSCALE_MAX_EDGE / float(max(width, height))
    llm = _image_fit().fit_letterbox(img, round(width * k), round(height * k))
    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        llm.save(out_path, format="PNG")
    except OSError as e:
        return ["cannot write the downscaled seed copy to %s: %s" % (out_path, e)], None
    return [], geometry


def _seed_geometry_line(seed_path, src_size, geometry, llm_path):
    """The one geometry line Phase 0 and --dry-run both print."""
    width, height, pad = geometry
    return ("seed image OK: %s (%dx%d after EXIF orientation) -> video geometry %dx%d "
            "(residual pad %d px, %.2fx of the measured 704x448 area); story-model copy %s"
            % (seed_path, src_size[0], src_size[1], width, height, pad,
               (width * height) / (704.0 * 448), llm_path))


def phase0_seed(args):
    """Pre-flight --seed-image, derive the video geometry from it, and write the scaled
    copy that Phase 1 attaches.

    Runs first, before the 27B call and before any GPU time: a missing, corrupt,
    degenerate or out-of-range (outside 1:3 .. 3:1) seed fails here with exit 2. Phase 2
    works from the ORIGINAL file, never from this copy."""
    paths = _story_paths(args.story_id)
    print("=== Phase 0: seed image ===")
    violations, geometry = _prepare_seed_image(args.seed_image, paths["seed_downscaled"])
    if violations:
        for v in violations:
            print("Error: %s" % v, file=sys.stderr)
        return 2
    args.video_width, args.video_height, args.seed_pad_px = geometry
    args.seed_downscaled_path = paths["seed_downscaled"]
    src_size = _image_fit().load_oriented_rgb(args.seed_image).size
    print(_seed_geometry_line(args.seed_image, src_size, geometry, paths["seed_downscaled"]))
    return 0
```

3c. Directly above `def phase2_stills(args):`, add:
```python
def _still_size(args):
    """Phase 2's still size, shared by the real phase and its dry-run mirror. In seed
    mode it is the video size itself (the seed is fitted into it). Otherwise z_image
    renders panel 1 at twice the video size, which ltx-2-mlx then downscales exactly
    (1/4 and 1/2) for its two conditioning passes."""
    if getattr(args, "seed_image", None):
        return args.video_width, args.video_height
    return 2 * args.video_width, 2 * args.video_height
```
Then replace the `cmd = [...]` statement in `phase2_stills` (lines 849-852) with:
```python
    still_w, still_h = _still_size(args)
    cmd = [sys.executable, os.path.join(WS, "bin", "ltx-story-images"),
           "--story-md", paths["story_md"], "--out-dir", paths["images_dir"],
           "--only", "1", "--width", str(still_w), "--height", str(still_h),
           "--seed", str(args.image_seed)]
```
Leave the following `if getattr(args, "seed_image", None):` / `cmd += ["--seed-image", args.seed_image]` lines exactly as they are (L29d).

3d. In `_print_dry_run_plan`, make the following changes.

**(i)** Replace the start of the function, from `paths = _story_paths(args.story_id)` through the `prompt = build_story_prompt(...)` statement, with:
```python
    paths = _story_paths(args.story_id)
    geometry_line = None
    if getattr(args, "seed_image", None):
        # Resolve Phase 0's geometry before printing anything, so a bad seed fails the
        # dry run exactly as it would fail Phase 0 (exit 2). Nothing is written.
        violations, geometry, img = _seed_geometry(args.seed_image)
        if violations and violations[0].startswith("--seed-image needs Pillow"):
            args.video_width, args.video_height = "<W>", "<H>"
            geometry_line = ("video geometry: derived from the seed at Phase 0 "
                             "(Pillow not importable in this interpreter)")
        elif violations:
            for v in violations:
                print("Error: %s" % v, file=sys.stderr)
            return 2
        else:
            args.video_width, args.video_height = geometry[0], geometry[1]
            geometry_line = _seed_geometry_line(args.seed_image, img.size, geometry,
                                                paths["seed_downscaled"])
    max_tokens = _phase1_max_tokens(args.panels)
    timeout = _phase1_timeout(args.panels)
    prompt = build_story_prompt(args.narrative, args.story_id, args.panels, args.no_stills,
                                 bool(getattr(args, "seed_image", None)),
                                 seconds=_clip_seconds(args))
```

**(ii)** Replace the Phase 0 print block (the two `print(...)` calls between `print("--- Phase 0: seed image ---")` and the following `print()`) with:
```python
        print("Would validate %s (readable image, every edge >= %dpx, aspect 1:3 to 3:1), "
              "derive the video geometry from it, and write a scaled story-model copy "
              "(long edge %dpx) to %s. Phase 2 fits the ORIGINAL into panel_01.png at the "
              "video size; nothing is cropped."
              % (args.seed_image, SEED_MIN_EDGE, SEED_DOWNSCALE_MAX_EDGE,
                 paths["seed_downscaled"]))
        print(geometry_line)
```

**(iii)** Replace the `phase2_cmd = [...]` statement (lines 1087-1090) with:
```python
        still_w, still_h = _still_size(args)
        phase2_cmd = [sys.executable, os.path.join(WS, "bin", "ltx-story-images"),
                      "--story-md", paths["story_md"], "--out-dir", paths["images_dir"],
                      "--only", "1", "--width", str(still_w), "--height", str(still_h),
                      "--seed", str(args.image_seed)]
```
The following `if getattr(...)` / `phase2_cmd += ["--seed-image", args.seed_image]` lines stay.

3e. In `main()`, insert the following directly after `_resolve_length(args, raw_argv)`. The `--seed-image`/`--no-stills` conflict check stays where it is, after this block:
```python
    if getattr(args, "seed_image", None):
        if args.video_width is not None or args.video_height is not None:
            print("Error: video geometry is derived from --seed-image; omit "
                  "--video-width/--video-height", file=sys.stderr)
            return 2
    else:
        if args.video_width is None:
            args.video_width = 704
        if args.video_height is None:
            args.video_height = 448
        if (args.video_width % 64 or args.video_height % 64
                or args.video_width < 64 or args.video_height < 64):
            print("Error: --video-width/--video-height must be multiples of 64 (ltx-2-mlx "
                  "two-stage floors to 64), got %dx%d" % (args.video_width, args.video_height),
                  file=sys.stderr)
            return 2
```

- [ ] **Step 4: Run the tests and confirm they pass.**
```bash
python3 tests/test_ltx_movie_offline.py; echo rc=$?
/usr/bin/grep -c "image_width\|image_height\|_crop_to_fill\|_downscale_seed_image" bin/ltx-movie
```
Expected: `OK n/n` with `rc=0`, and the grep count is `0`.

- [ ] **Step 5: Checkpoint (no commit).**

---

## Task 6: `bin/ltx-story-images`: fit the seed, never crop it

**Files:** Modify `bin/ltx-story-images` and `tests/test_ltx_story_images.py`.

**Depends on:** Task 2.

- [ ] **Step 1: Write the failing test.** In `tests/test_ltx_story_images.py`:
- Delete the `# I9` banner block, `_marker_image`, and `test_resize_center_crop_geometry`. `_marker_image` has no other user once I10 is rewritten.
- Remove `    test_resize_center_crop_geometry()` from the `__main__` block.
- Replace `test_write_seed_panel` (and its I10 banner text) with:
```python
# ---------------------------------------------------------------------------
# I10: _write_seed_panel fits (never crops) the seed into an exact RGB PNG
# ---------------------------------------------------------------------------

def test_write_seed_panel():
    from PIL import Image
    colour = (200, 30, 40)

    def _near(p, want):
        return all(abs(a - b) <= 2 for a, b in zip(p, want))

    with tempfile.TemporaryDirectory() as tmp:
        square = os.path.join(tmp, "square.png")
        Image.new("RGB", (900, 900), colour).save(square, format="PNG")
        out_sq = os.path.join(tmp, "out_sq.png")
        story_images._write_seed_panel(square, out_sq, 512, 512)
        check("I10a output file exists", os.path.isfile(out_sq))
        with Image.open(out_sq) as img:
            check("I10b format is PNG", img.format == "PNG", "got %r" % img.format)
            check("I10c size is exactly 512x512", img.size == (512, 512), "got %r" % (img.size,))
            check("I10d mode is RGB", img.mode == "RGB", "got %r" % img.mode)
            corner = img.getpixel((0, 0))
            check("I10e a same-aspect source has no pad: the corner is the source colour",
                  _near(corner, colour), "got %r" % (corner,))

        wide = os.path.join(tmp, "wide.png")
        Image.new("RGB", (900, 600), colour).save(wide, format="PNG")
        out_wide = os.path.join(tmp, "out_wide.png")
        story_images._write_seed_panel(wide, out_wide, 512, 512)
        with Image.open(out_wide) as img:
            check("I10f size is exactly 512x512", img.size == (512, 512), "got %r" % (img.size,))
            rows = [img.getpixel((x, 0)) for x in range(0, 512, 16)] + \
                   [img.getpixel((x, 511)) for x in range(0, 512, 16)]
            check("I10g a wider source is letterboxed: the top and bottom rows are black",
                  all(p == (0, 0, 0) for p in rows), "got %r" % rows[:4])
            check("I10h the centre is the source colour", _near(img.getpixel((256, 256)), colour),
                  "got %r" % (img.getpixel((256, 256)),))
            check("I10i the full source width survives: both edge pixels at mid-height are "
                  "source-coloured (nothing cropped)",
                  _near(img.getpixel((0, 256)), colour) and _near(img.getpixel((511, 256)), colour),
                  "got %r %r" % (img.getpixel((0, 256)), img.getpixel((511, 256))))
```

- [ ] **Step 2: Run the test and confirm it fails.** Run `python3 tests/test_ltx_story_images.py; echo rc=$?`. Expected: `FAIL I10g …` (the old implementation crops a 900x600 source to fill, so there are no black rows) and `rc=1`.

- [ ] **Step 3: Write the implementation in `bin/ltx-story-images`.**
- Delete `_resize_center_crop` (lines 97-113).
- Replace `_write_seed_panel` (lines 116-127) with:
```python
def _write_seed_panel(seed_path, out_path, width, height):
    """Write seed_path to out_path as an RGB PNG of exactly width x height: EXIF
    orientation applied, scaled to fit (never cropped) and centred on a black
    width x height canvas (ltx_image_fit.fit_letterbox).

    ltx_image_fit is imported here and not at module scope on purpose: this file's
    docstring promises stdlib-only imports at import time, and
    tests/test_ltx_story_images.py guards that promise. ltx_image_fit itself imports
    PIL only inside its functions.
    """
    import ltx_image_fit
    ltx_image_fit.fit_letterbox(ltx_image_fit.load_oriented_rgb(seed_path),
                                width, height).save(out_path, format="PNG")
```
- Replace the `--seed-image` help (lines 81-85) with:
```python
                        help="image that becomes panel 1 verbatim: it is scaled to fit "
                             "(never cropped) and centred on a black --width x --height "
                             "canvas and saved as panel_01.png instead of being generated. "
                             "Panel 1 takes this path even with --force (there is no "
                             "txt2img output to regenerate).")
```
Nothing else in this file changes; the grounded `Style:` mode stays.

- [ ] **Step 4: Run the tests and confirm they pass.** Run `python3 tests/test_ltx_story_images.py; echo rc=$?` and expect `OK n/n` with `rc=0`; the I13 counts are unchanged. Then run `python3 tests/test_ltx_movie_offline.py; echo rc=$?` and expect `rc=0` (L26j now exercises the new `_write_seed_panel`).

- [ ] **Step 5: Checkpoint (no commit).** `/usr/bin/grep -c "center-crop\|_resize_center_crop" bin/ltx-story-images` prints `0`.

---

## Task 7: `bin/ltx-story-manifest --chain` (schema v3)

**Files:** Modify `bin/ltx-story-manifest`. Create `tests/test_ltx_story_manifest_chain.py`.

**Interface produced:** v3 manifest panels carry `"conditioning": "still"|"chain"`, with panel 1 `still` and panels 2..N `chain`. Consumed by Tasks 8, 10 and 11.

**Depends on:** Task 0.

- [ ] **Step 1: Write the failing test.** Create `tests/test_ltx_story_manifest_chain.py`:
```python
"""Plain-python (no pytest) offline tests for bin/ltx-story-manifest --chain
(manifest schema_version 3), plus the guarantee that --glob / --image / --no-images
still write schema_version 2 with no "conditioning" key.

Run: python3 tests/test_ltx_story_manifest_chain.py
Every case writes to generated/stories/<a throwaway story id>/ and removes it.
"""

import contextlib
import importlib.machinery
import io
import json
import os
import shutil
import sys
import tempfile

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

_MANIFEST_PATH = os.path.join(WS, "bin", "ltx-story-manifest")
story_manifest = importlib.machinery.SourceFileLoader(
    "ltx_story_manifest_chain_test", _MANIFEST_PATH).load_module()

TOTAL = 0
FAILED = 0

_V2_PANEL_KEYS = {"index", "image_path", "title", "panel_text", "narration", "narration_words",
                  "num_frames", "duration_s", "motion_prompt", "transition_to_next"}


def check(name, condition, detail=""):
    global TOTAL, FAILED
    TOTAL += 1
    if condition:
        print("PASS %s" % name)
    else:
        FAILED += 1
        print("FAIL %s %s" % (name, detail))


def _png(path, size=(64, 64)):
    from PIL import Image
    Image.new("RGB", size, (10, 20, 30)).save(path, format="PNG")
    return path


def _story(td, panels, name="story.md"):
    """panels: one dict per panel mapping label -> text, for the labels Image, Motion,
    Narration and Prompt (written in that order)."""
    lines = ["# Story", "", "a narrative", ""]
    for i, fields in enumerate(panels, start=1):
        lines.append("## Panel %d — Title %d" % (i, i))
        for label in ("Image", "Motion", "Narration", "Prompt"):
            if label in fields:
                lines.append("%s: %s" % (label, fields[label]))
        lines.append("")
    path = os.path.join(td, name)
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


def _run(argv):
    """main(argv) with stdout/stderr captured. parser.error's SystemExit becomes rc."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = story_manifest.main(argv)
        except SystemExit as e:
            rc = e.code
    return rc, out.getvalue(), err.getvalue()


def _sid(tag):
    return "_test_manifest_chain_%s_%d" % (tag, os.getpid())


def _manifest_path(story_id):
    return os.path.join(WS, "generated", "stories", story_id, "manifest.json")


def _load(story_id):
    with open(_manifest_path(story_id)) as f:
        return json.load(f)


def _cleanup(story_id):
    shutil.rmtree(os.path.join(WS, "generated", "stories", story_id), ignore_errors=True)


def _frame_args(n):
    return ["--fps", "24", "--target-seconds", str(n * 145 / 24.0),
            "--min-frames", "145", "--max-frames", "145", "--force"]


_THREE = [{"Image": "the opening frame", "Motion": "she turns", "Narration": "One."},
          {"Motion": "she walks to the door", "Narration": "Two."},
          {"Motion": "she opens it", "Narration": "Three."}]


def test_chain_three_panels():
    sid = _sid("three")
    try:
        with tempfile.TemporaryDirectory() as td:
            still = _png(os.path.join(td, "panel_01.png"))
            md = _story(td, _THREE)
            rc, out, err = _run(["--story-id", sid, "--prompts-md", md, "--chain",
                                 "--image", still] + _frame_args(3))
            check("C1a rc 0", rc == 0, "rc=%r err=%r" % (rc, err))
            m = _load(sid)
            p = m["panels"]
            check("C1b schema_version 3", m["schema_version"] == 3, "got %r" % m["schema_version"])
            check("C1c conditioning still/chain/chain",
                  [x.get("conditioning") for x in p] == ["still", "chain", "chain"],
                  "got %r" % [x.get("conditioning") for x in p])
            check("C1d panel 1 image_path is the absolute still",
                  p[0]["image_path"] == os.path.abspath(still), "got %r" % p[0]["image_path"])
            check("C1e panel 1 panel_text is Image:, motion_prompt is Motion:",
                  p[0]["panel_text"] == "the opening frame" and p[0]["motion_prompt"] == "she turns",
                  "got %r" % p[0])
            check("C1f panels 2-3 carry panel_text == motion_prompt == Motion:",
                  [(x["panel_text"], x["motion_prompt"]) for x in p[1:]]
                  == [("she walks to the door", "she walks to the door"),
                      ("she opens it", "she opens it")], "got %r" % p[1:])
            check("C1g panels 2-3 have image_path None",
                  all(x["image_path"] is None for x in p[1:]))
            check("C1h narration is carried", [x["narration"] for x in p] == ["One.", "Two.", "Three."])
            check("C1i every panel is 145 frames", [x["num_frames"] for x in p] == [145, 145, 145])
            check("C1j the summary table marks chained panels",
                  out.count("(chained)") == 2 and "panel_01.png" in out, "got %r" % out)
            check("C1k a v3 panel is the v2 key set plus conditioning",
                  all(set(x) == _V2_PANEL_KEYS | {"conditioning"} for x in p))
    finally:
        _cleanup(sid)


def test_chain_argument_errors():
    sid = _sid("argerr")
    try:
        with tempfile.TemporaryDirectory() as td:
            still = _png(os.path.join(td, "panel_01.png"))
            md = _story(td, _THREE)
            cases = (
                ("C2a --chain + --no-images",
                 ["--prompts-md", md, "--chain", "--image", still, "--no-images"],
                 "--chain is mutually exclusive with --glob and --no-images"),
                ("C2b --chain + --glob",
                 ["--prompts-md", md, "--chain", "--glob", "panel_*.png", "--images-dir", td],
                 "--chain is mutually exclusive with --glob and --no-images"),
                ("C2c --chain without --prompts-md", ["--chain", "--image", still],
                 "--chain requires --prompts-md"),
                ("C2d --chain with no --image", ["--prompts-md", md, "--chain"],
                 "--chain requires exactly one --image (panel 1's still)"),
                ("C2e --chain with two --image",
                 ["--prompts-md", md, "--chain", "--image", still, "--image", still],
                 "--chain requires exactly one --image (panel 1's still)"),
            )
            for label, extra, message in cases:
                rc, out, err = _run(["--story-id", sid] + extra + _frame_args(3))
                check("%s exits 2 with %r" % (label, message), rc == 2 and message in err,
                      "rc=%r err=%r" % (rc, err))
            check("C2f no manifest was written by any of them",
                  not os.path.exists(_manifest_path(sid)))
    finally:
        _cleanup(sid)


def test_chain_content_errors():
    sid = _sid("content")
    try:
        with tempfile.TemporaryDirectory() as td:
            still = _png(os.path.join(td, "panel_01.png"))
            cases = (
                ("C3a zero panels", [],
                 "Error: --chain requires --prompts-md to contain at least one panel section; found 0"),
                ("C3b panel 1 without Image:",
                 [{"Motion": "m", "Narration": "n"}],
                 "Error: --chain requires panel 1 to have a non-empty Image: field"),
                ("C3c panel 2 without Motion:",
                 [{"Image": "i", "Motion": "m", "Narration": "n"}, {"Narration": "n2"}],
                 "Error: --chain requires every panel to have a non-empty Motion: field; panel 2 has none"),
                ("C3d panel 2 with Prompt:",
                 [{"Image": "i", "Motion": "m", "Narration": "n"},
                  {"Motion": "m2", "Narration": "n2", "Prompt": "p"}],
                 "Error: --chain does not accept Prompt: fields; panel 2 has one"),
            )
            for n, (label, panels, message) in enumerate(cases):
                md = _story(td, panels, name="story_%d.md" % n)
                rc, out, err = _run(["--story-id", sid, "--prompts-md", md, "--chain",
                                     "--image", still] + _frame_args(max(1, len(panels))))
                check("%s exits 2 with the spec message" % label, rc == 2 and message in err,
                      "rc=%r err=%r" % (rc, err))
    finally:
        _cleanup(sid)


def test_chain_panel2_image_warning():
    sid = _sid("warn")
    try:
        with tempfile.TemporaryDirectory() as td:
            still = _png(os.path.join(td, "panel_01.png"))
            md = _story(td, [{"Image": "i1", "Motion": "m1", "Narration": "n1"},
                             {"Image": "an old-format picture", "Motion": "m2", "Narration": "n2"}])
            rc, out, err = _run(["--story-id", sid, "--prompts-md", md, "--chain",
                                 "--image", still] + _frame_args(2))
            check("C4a a panel-2 Image: is a warning, not an error", rc == 0, "rc=%r err=%r" % (rc, err))
            check("C4b the warning text is the spec text",
                  "WARNING: panel 2 has an Image: field; --chain ignores it (the panel continues "
                  "from the previous clip's last frame)" in out, "got %r" % out)
            p = _load(sid)["panels"]
            check("C4c panel 2's Image: text is ignored (panel_text is its Motion:)",
                  p[1]["panel_text"] == "m2" and p[1]["image_path"] is None, "got %r" % p[1])
    finally:
        _cleanup(sid)


def test_chain_single_panel():
    sid = _sid("single")
    try:
        with tempfile.TemporaryDirectory() as td:
            still = _png(os.path.join(td, "panel_01.png"))
            md = _story(td, _THREE[:1])
            rc, out, err = _run(["--story-id", sid, "--prompts-md", md, "--chain",
                                 "--image", still] + _frame_args(1))
            m = _load(sid) if rc == 0 else {}
            check("C5 a one-panel --chain story is a v3 manifest with a single still panel",
                  rc == 0 and m.get("schema_version") == 3
                  and [x["conditioning"] for x in m["panels"]] == ["still"],
                  "rc=%r err=%r m=%r" % (rc, err, m))
    finally:
        _cleanup(sid)


def test_chain_length_warning_uses_motion():
    sid = _sid("length")
    try:
        with tempfile.TemporaryDirectory() as td:
            still = _png(os.path.join(td, "panel_01.png"))
            md = _story(td, [{"Image": " ".join(["word"] * 200), "Motion": "she turns",
                              "Narration": "n1"},
                             {"Motion": " ".join(["step"] * 160), "Narration": "n2"}])
            rc, out, err = _run(["--story-id", sid, "--prompts-md", md, "--chain",
                                 "--image", still] + _frame_args(2))
            check("C6a a long panel-1 Image: does not warn (the video model receives Motion:)",
                  rc == 0 and "WARNING: unit 1 prompt" not in out, "got %r" % out)
            check("C6b a long panel-2 Motion: does warn",
                  "WARNING: unit 2 prompt is 160 words" in out, "got %r" % out)
    finally:
        _cleanup(sid)


def test_v2_modes_unchanged():
    sid = _sid("v2")
    try:
        with tempfile.TemporaryDirectory() as td:
            imgs = os.path.join(td, "images")
            os.makedirs(imgs)
            a = _png(os.path.join(imgs, "panel_01.png"))
            b = _png(os.path.join(imgs, "panel_02.png"))
            md = _story(td, [{"Image": "i1", "Motion": "m1", "Narration": "n1"},
                             {"Image": "i2", "Motion": "m2", "Narration": "n2"}])
            rc, out, err = _run(["--story-id", sid, "--prompts-md", md, "--glob", "panel_*.png",
                                 "--images-dir", imgs] + _frame_args(2))
            m = _load(sid) if rc == 0 else {}
            check("C7a --glob still writes schema_version 2 with the exact v2 panel keys",
                  rc == 0 and m.get("schema_version") == 2
                  and all(set(x) == _V2_PANEL_KEYS for x in m["panels"]),
                  "rc=%r err=%r" % (rc, err))
            rc, out, err = _run(["--story-id", sid, "--prompts-md", md, "--image", a,
                                 "--image", b] + _frame_args(2))
            m = _load(sid) if rc == 0 else {}
            check("C7b --image without --chain still writes schema_version 2, no conditioning",
                  rc == 0 and m.get("schema_version") == 2
                  and not any("conditioning" in x for x in m["panels"]),
                  "rc=%r err=%r" % (rc, err))
            nost = _story(td, [{"Prompt": "p1", "Narration": "n1"}], name="nost.md")
            rc, out, err = _run(["--story-id", sid, "--prompts-md", nost, "--no-images"]
                                + _frame_args(1))
            m = _load(sid) if rc == 0 else {}
            check("C7c --no-images still writes schema_version 2, no conditioning",
                  rc == 0 and m.get("schema_version") == 2
                  and not any("conditioning" in x for x in m["panels"]),
                  "rc=%r err=%r" % (rc, err))
    finally:
        _cleanup(sid)


if __name__ == "__main__":
    test_chain_three_panels()
    test_chain_argument_errors()
    test_chain_content_errors()
    test_chain_panel2_image_warning()
    test_chain_single_panel()
    test_chain_length_warning_uses_motion()
    test_v2_modes_unchanged()

    print("OK %d/%d" % (TOTAL - FAILED, TOTAL))
    sys.exit(0 if FAILED == 0 else 1)
```
Note on C3a: an empty `panels` list writes a story.md with no `## Panel` sections, which is the zero-panel case. `_frame_args(max(1, 0))` keeps the allocator arguments valid, and the chain check returns 2 before any frame allocation runs.

- [ ] **Step 2: Run the test and confirm it fails.** Run `python3 tests/test_ltx_story_manifest_chain.py; echo rc=$?`. Expected: C1a fails with `rc=2` and `unrecognized arguments: --chain`, a traceback follows at `_load` (`FileNotFoundError`), and `rc=1`.

- [ ] **Step 3: Write the implementation in `bin/ltx-story-manifest`.**

3a. In the module docstring, insert this block after the schema-v2 JSON block's closing `}` (line 48) and before `Dependencies:`:
```
Schema version 3 is written ONLY by --chain (the bin/ltx-movie chained flow). It is
schema version 2 plus one required per-panel key, "conditioning":
  "still" -- image_path is an existing, readable file (panel 1's still);
  "chain" -- index >= 2 and image_path is null: at render time bin/ltx-mlx-render
             conditions the panel on the exact last frame of the previous panel's clip;
  "t2v"   -- image_path is null (plain text-to-video).
--chain takes exactly one --image (panel 1's still) and a --prompts-md whose Panel 1
has Image:/Motion:/Narration: and whose later panels have Motion:/Narration:. Panel
1's panel_text is its Image: text; every panel's motion_prompt is its Motion: text,
and a chain panel's panel_text is its Motion: text too. --glob, --image without
--chain, and --no-images keep writing schema_version 2 exactly as before, with no
"conditioning" key.
```

3b. In `build_parser`, directly after the `--no-images` argument, add:
```python
    parser.add_argument("--chain", action="store_true", default=False,
                         help="chained flow (bin/ltx-movie): exactly one --image is panel 1's "
                              "still; every later panel is conditioned at render time on the "
                              "previous clip's last frame. Requires --prompts-md; mutually "
                              "exclusive with --glob and --no-images.")
```

3c. In `main()`, insert the following directly before `if args.no_images:` (line 305):
```python
    if args.chain:
        if args.no_images or args.glob:
            parser.error("--chain is mutually exclusive with --glob and --no-images")
        if not args.prompts_md:
            parser.error("--chain requires --prompts-md")
        if len(args.image or []) != 1:
            parser.error("--chain requires exactly one --image (panel 1's still)")
```

3d. Inside `if args.prompts_md:`, replace the existing panel-count check (the block starting `if not args.no_images and len(parsed_panels) != len(matched):`, lines 346-349) with:
```python
        if args.chain:
            if not parsed_panels:
                print("Error: --chain requires --prompts-md to contain at least one panel "
                      "section; found 0", file=sys.stderr)
                return 2
            if not parsed_panels[0]["image"].strip():
                print("Error: --chain requires panel 1 to have a non-empty Image: field",
                      file=sys.stderr)
                return 2
            for i, pt in enumerate(parsed_panels, start=1):
                if not pt["motion"].strip():
                    print("Error: --chain requires every panel to have a non-empty Motion: "
                          "field; panel %d has none" % i, file=sys.stderr)
                    return 2
            for i, pt in enumerate(parsed_panels, start=1):
                if pt["prompt"].strip():
                    print("Error: --chain does not accept Prompt: fields; panel %d has one" % i,
                          file=sys.stderr)
                    return 2
        elif not args.no_images and len(parsed_panels) != len(matched):
            print("Error: prompts.md has %d panels but %d images were selected"
                  % (len(parsed_panels), len(matched)), file=sys.stderr)
            return 2
```
Keep the existing Prompt-vs-Image/Motion conflict loop and the `if args.no_images:` Prompt loop unchanged. Directly before `prompt_texts = parsed_panels`, insert:
```python
        if args.chain:
            for i, pt in enumerate(parsed_panels[1:], start=2):
                if pt["image"].strip():
                    print("WARNING: panel %d has an Image: field; --chain ignores it (the panel "
                          "continues from the previous clip's last frame)" % i)
```

3e. Replace `n_panels = len(prompt_texts) if args.no_images else len(matched)` with:
```python
    n_panels = len(prompt_texts) if (args.no_images or args.chain) else len(matched)
```

3f. Replace the panel-assembly loop (lines 420-461, `panels = []` through the closing `})`) with:
```python
    panels = []
    for i in range(1, n_panels + 1):
        pt = prompt_texts[i - 1] if prompt_texts is not None else None
        conditioning = None
        if args.chain:
            title = pt["title"]
            narration = pt["narration"]
            motion_prompt = pt["motion"]
            if i == 1:
                image_path = matched[0]
                conditioning = "still"
                panel_text = pt["image"]
            else:
                image_path = None
                conditioning = "chain"
                panel_text = pt["motion"]
        else:
            image_path = matched[i - 1] if matched else None
            has_prompt = pt is not None and bool(pt["prompt"].strip())
            has_labels = pt is not None and (pt["image"] or pt["motion"] or pt["narration"])
            if has_prompt:
                # Collapsed form (DR2): one field is both the panel text and the
                # motion prompt. Checked FIRST, because a Prompt:-form panel also
                # has a Narration: label and would otherwise fall into has_labels.
                title = pt["title"]
                panel_text = pt["prompt"]
                motion_prompt = pt["prompt"]
                narration = pt["narration"]
            elif has_labels:
                title = pt["title"]
                panel_text = pt["image"] or ("panel %d" % i)
                motion_prompt = pt["motion"] or None
                narration = pt["narration"]
            elif pt is not None:
                title = pt["title"]
                panel_text = pt["text"] or ("panel %d" % i)
                motion_prompt = None
                narration = ""
            else:
                title = ""
                panel_text = "panel %d" % i
                motion_prompt = None
                narration = ""
        num_frames = frame_counts[i - 1]
        panel = {
            "index": i,
            "image_path": None if image_path is None else os.path.abspath(image_path),
            "title": title,
            "panel_text": panel_text,
            "narration": narration,
            "narration_words": len(narration.split()),
            "num_frames": num_frames,
            "duration_s": round(num_frames / args.fps, 3),
            "motion_prompt": motion_prompt,
            "transition_to_next": None,
        }
        if conditioning is not None:
            panel["conditioning"] = conditioning
        panels.append(panel)
```

3g. Replace the length-warning loop (lines 463-464) with:
```python
    for p in panels:
        # Chain mode: the video model receives the Motion: text, so that is what is measured.
        _prompt_length_warning(p["index"], p["motion_prompt"] if args.chain else p["panel_text"])
```

3h. In the `manifest = {...}` literal, change `"schema_version": 2,` to `"schema_version": 3 if args.chain else 2,`.

3i. In the summary table loop, replace the `basename = ...` line with:
```python
        basename = (os.path.basename(p["image_path"]) if p["image_path"]
                    else ("(chained)" if p.get("conditioning") == "chain" else "(no image)"))
```

- [ ] **Step 4: Run the tests and confirm they pass.** Run `python3 tests/test_ltx_story_manifest_chain.py; echo rc=$?` and expect `OK n/n` with `rc=0`. Then run `python3 tests/test_ltx_story_images.py; echo rc=$?` and expect `rc=0` (that suite loads the manifest parser).

- [ ] **Step 5: Checkpoint (no commit).**

---

## Task 8: `bin/ltx-mlx-render`: backend removal (P1/P3), v3 `load_manifest`, `build_units`, provenance v2

**Files:** Modify `bin/ltx-mlx-render` and `tests/test_ltx_mlx_render.py`.

**Interfaces produced:**
- Units carry `"conditioning"` and `"chain_source"`. A chain unit's `image_path` is `<clips>/panel_%02d.chainseed.png`.
- `build_clip_provenance` returns schema_version 2 with the keys `conditioning`, `chain_source_sha256` and `chain_frame_index`.

**Depends on:** Tasks 1 and 3. **Blocks:** Tasks 9 and 10.

- [ ] **Step 1: Test-file surgery.** In `tests/test_ltx_mlx_render.py`:

1a. Delete `test_comfyui_backend_preflight_and_fatal_stop`, `test_backend_clip_directories_estimates_and_sidecars` and `test_bridge_dry_actual_dispatch_and_unknown_direct_identity`. Remove their three calls from `__main__`.

1b. In `test_parser_defaults`, add after the `R1v` check:
```python
    # "video_" + "backend": the spec's grep gate (12.1 item 5) must not match test sources.
    check("R1af there is no video-backend flag",
          not hasattr(a, "video_" + "backend")
          and ("--video-" + "backend") not in render.build_parser().format_help())
```

1c. In `test_load_manifest`, append at the end of the `with` block, after `R3j`:
```python
        # v3 (bin/ltx-story-manifest --chain): conditioning is required and validated.
        def _v3(panels):
            return _write_manifest(td, panels, schema_version=3)

        good = _v3([{"index": 1, "image_path": img, "panel_text": "t", "conditioning": "still"},
                    {"index": 2, "image_path": None, "panel_text": "m", "conditioning": "chain"},
                    {"index": 3, "image_path": None, "panel_text": "x", "conditioning": "t2v"}])
        check("R3k a valid v3 still/chain/t2v manifest loads",
              [p["conditioning"] for p in render.load_manifest(good)["panels"]]
              == ["still", "chain", "t2v"])
        for label, panels, want in (
                ("R3l missing conditioning",
                 [{"index": 1, "image_path": img, "panel_text": "t"}],
                 "panel 1: conditioning must be one of still/chain/t2v, got None"),
                ("R3m unknown conditioning",
                 [{"index": 1, "image_path": img, "panel_text": "t", "conditioning": "bogus"}],
                 "panel 1: conditioning must be one of still/chain/t2v, got 'bogus'"),
                ("R3n still with a null image_path",
                 [{"index": 1, "image_path": None, "panel_text": "t", "conditioning": "still"}],
                 "panel 1: conditioning 'still' requires an existing, readable image_path"),
                ("R3o chain on panel 1",
                 [{"index": 1, "image_path": None, "panel_text": "t", "conditioning": "chain"}],
                 "panel 1: conditioning 'chain' requires index >= 2 and image_path null"),
                ("R3p chain with an image_path",
                 [{"index": 1, "image_path": img, "panel_text": "t", "conditioning": "still"},
                  {"index": 2, "image_path": img, "panel_text": "m", "conditioning": "chain"}],
                 "panel 2: conditioning 'chain' requires index >= 2 and image_path null"),
                ("R3q t2v with an image_path",
                 [{"index": 1, "image_path": img, "panel_text": "t", "conditioning": "t2v"}],
                 "panel 1: conditioning 't2v' requires image_path null")):
            msg = _load_error(_v3(panels))
            check("%s is rejected with the spec message" % label, msg == want, "got %r" % msg)

        derived = render.load_manifest(_write_manifest(td, [_panel(1, img), _panel(2, None)]))
        check("R3r v2 derives conditioning: image -> still, null -> t2v",
              [p["conditioning"] for p in derived["panels"]] == ["still", "t2v"])
        v1_path = os.path.join(td, "v1.json")
        with open(v1_path, "w") as f:
            json.dump({"story_id": "demo", "panels": [_panel(1, img), _panel(2, None)]}, f)
        check("R3s a v1 manifest (no schema_version) derives the same way",
              [p["conditioning"] for p in render.load_manifest(v1_path)["panels"]]
              == ["still", "t2v"])
```

1d. **Replace** `test_build_units` entirely with:
```python
def test_build_units():
    panels = [
        {"index": 1, "image_path": "/abs/p1.png", "panel_text": "text one",
         "motion_prompt": "motion one", "conditioning": "still"},
        {"index": 2, "image_path": None, "panel_text": "text two",
         "motion_prompt": None, "conditioning": "t2v"},
        {"index": 3, "image_path": "/abs/p3.png", "panel_text": "text three",
         "motion_prompt": "", "conditioning": "still"},
    ]
    units = render.build_units(panels, seed=100, clips_dir="/clips", run_root="/runs/r1")

    check("R4a one unit per panel", len(units) == 3, "got %d" % len(units))
    check("R4b prompt prefers motion_prompt", units[0]["prompt"] == "motion one",
          "got %r" % units[0]["prompt"])
    check("R4c prompt falls back to panel_text when motion_prompt is None",
          units[1]["prompt"] == "text two", "got %r" % units[1]["prompt"])
    check("R4d prompt falls back to panel_text when motion_prompt is empty",
          units[2]["prompt"] == "text three", "got %r" % units[2]["prompt"])
    check("R4e seed is base + i", [u["seed"] for u in units] == [101, 102, 103],
          "got %r" % [u["seed"] for u in units])
    check("R4f label is panel-<i>", [u["label"] for u in units] == ["panel-1", "panel-2", "panel-3"],
          "got %r" % [u["label"] for u in units])
    check("R4g clip path is panel_%02d.mp4",
          [os.path.basename(u["clip_path"]) for u in units]
          == ["panel_01.mp4", "panel_02.mp4", "panel_03.mp4"],
          "got %r" % [u["clip_path"] for u in units])
    check("R4h clips live under clips_dir",
          all(os.path.dirname(u["clip_path"]) == "/clips" for u in units))
    check("R4i log path is <run_root>/panel_%02d.log",
          units[1]["log_path"] == os.path.join("/runs/r1", "panel_02.log"),
          "got %r" % units[1]["log_path"])
    check("R4j image_path carried through for still/t2v, None stays None",
          [u["image_path"] for u in units] == ["/abs/p1.png", None, "/abs/p3.png"],
          "got %r" % [u["image_path"] for u in units])
    check("R4k log_path is None when run_root is None",
          render.build_units(panels, 0, "/clips")[0]["log_path"] is None)
    check("R4l unit keys are exactly the documented set",
          set(units[0]) == {"index", "label", "seed", "prompt", "image_path",
                            "clip_path", "log_path", "conditioning", "chain_source"},
          "got %r" % sorted(units[0]))
    check("R4m conditioning is carried and still/t2v units have no chain_source",
          [(u["conditioning"], u["chain_source"]) for u in units]
          == [("still", None), ("t2v", None), ("still", None)])

    chain = [
        {"index": 1, "image_path": "/abs/p1.png", "panel_text": "img", "motion_prompt": "m1",
         "conditioning": "still"},
        {"index": 2, "image_path": None, "panel_text": "m2", "motion_prompt": "m2",
         "conditioning": "chain"},
        {"index": 3, "image_path": None, "panel_text": "m3", "motion_prompt": "m3",
         "conditioning": "chain"},
    ]
    cu = render.build_units(chain, seed=0, clips_dir="/clips")
    check("R4n a still unit keeps its own image_path", cu[0]["image_path"] == "/abs/p1.png")
    check("R4o chain units read a derived <clips>/panel_%02d.chainseed.png",
          [u["image_path"] for u in cu[1:]]
          == ["/clips/panel_02.chainseed.png", "/clips/panel_03.chainseed.png"],
          "got %r" % [u["image_path"] for u in cu[1:]])
    check("R4p chain_source is the previous panel's clip",
          [u["chain_source"] for u in cu] == [None, "/clips/panel_01.mp4", "/clips/panel_02.mp4"],
          "got %r" % [u["chain_source"] for u in cu])
    check("R4q chain units keep seed + i and their Motion: prompt",
          [(u["seed"], u["prompt"]) for u in cu] == [(1, "m1"), (2, "m2"), (3, "m3")])
```

1e. **Replace** `test_clip_provenance_contract` entirely with:
```python
def test_clip_provenance_contract():
    from unittest import mock
    import hashlib
    with tempfile.TemporaryDirectory() as td:
        model = os.path.join(td,'model')
        os.mkdir(model)
        for name,data in [('z.safetensors',b'weights'),('config.json',b'{}'),('ignored.txt',b'ignored')]:
            with open(os.path.join(model,name),'wb') as handle: handle.write(data)
        image = os.path.join(td,'image.png')
        clip = os.path.join(td,'clip.mp4')
        with open(image,'wb') as handle: handle.write(b'image bytes')
        with open(clip,'wb') as handle: handle.write(b'video bytes')
        unit = dict(prompt='literal prompt\n',image_path=image,seed=4,clip_path=clip,
                    conditioning='still',chain_source=None)
        args = _stub_args(model=model)
        expected = render.build_clip_provenance(unit,args)
        check('R18 schema_version 2 and the ltx-2-mlx backend constant',
              expected['schema_version']==2 and expected['backend']=='ltx-2-mlx')
        check('R18 no VAE decode budget key','vae_decode_budget_gb' not in expected)
        check('R18 still provenance carries its conditioning and no chain keys',
              expected['conditioning']=='still' and expected['chain_source_sha256'] is None
              and expected['chain_frame_index'] is None)
        identity = expected['model_identity']
        check('R18 exact identity fields',set(identity)=={'resolved_path','snapshot_revision','files'})
        check('R18 canonical bundle and local revision',identity['resolved_path']==os.path.realpath(model)
              and identity['snapshot_revision'] is None)
        check('R18 sorted relevant metadata excludes unrelated files',
              [item['path'] for item in identity['files']]==['config.json','z.safetensors'])
        check('R18 file metadata records sizes and nanosecond mtimes',all(set(item)=={'path','size','mtime_ns'}
              and isinstance(item['mtime_ns'],int) for item in identity['files']))
        check('R18 exact prompt and image hashes',expected['prompt_sha256']==hashlib.sha256(b'literal prompt\n').hexdigest()
              and expected['image_sha256']==hashlib.sha256(b'image bytes').hexdigest())
        sidecar = clip+'.provenance.json'
        payload = dict(expected,output_sha256=hashlib.sha256(b'video bytes').hexdigest())
        def write(value):
            with open(sidecar,'w') as handle: json.dump(value,handle)
        with mock.patch.object(render,'clip_frame_count',return_value=241):
            check('R18 missing sidecar is never reusable',not render.clip_is_reusable(clip,241,expected))
            write(payload)
            check('R18 exact provenance reuses clip',render.clip_is_reusable(clip,241,expected))
            write(dict(reversed(list(payload.items()))))
            check('R18 reordered valid keys still reuse',render.clip_is_reusable(clip,241,expected))
            for name,value,comparison in (('schema_version',True,expected),('fps',24.0,expected),
                                           ('seed',True,dict(expected,seed=1)),('frames',float('nan'),expected)):
                malformed = dict(payload,**{name:value})
                write(malformed)
                check('R18 malformed numeric type %s=%r regenerates' % (name,value),
                      not render.clip_is_reusable(clip,241,comparison))
            for key in payload:
                changed = dict(payload)
                changed[key] = None if payload[key] is not None else 'changed'
                write(changed)
                check('R18 mismatched %s regenerates' % key,not render.clip_is_reusable(clip,241,expected))
            for value in (None,[],{},'bad',42):
                write(value)
                check('R18 malformed sidecar %r regenerates' % value,not render.clip_is_reusable(clip,241,expected))
            with open(sidecar,'w') as handle: handle.write('{broken')
            check('R18 corrupt JSON regenerates',not render.clip_is_reusable(clip,241,expected))
            write(payload)
            with open(clip,'wb') as handle: handle.write(b'changed video')
            check('R18 mutated clip checksum regenerates',not render.clip_is_reusable(clip,241,expected))
            with open(clip,'wb') as handle: handle.write(b'video bytes')
            with open(os.path.join(model,'config.json'),'ab') as handle: handle.write(b' ')
            current = render.build_clip_provenance(unit,args)
            check('R18 changed model metadata regenerates',not render.clip_is_reusable(clip,241,current))
            unknown = dict(expected,model_identity=None)
            write(dict(unknown,output_sha256=payload['output_sha256']))
            check('R18 unknown model identity cannot resume',not render.clip_is_reusable(clip,241,unknown))
        with mock.patch.object(render,'clip_frame_count',return_value=240):
            write(payload)
            check('R18 original frame count guard retained',not render.clip_is_reusable(clip,241,expected))
        no_image = render.build_clip_provenance(dict(unit,image_path=None,conditioning='t2v'),args)
        check('R18 T2V provenance hashes no image and no chain source',
              no_image['image_sha256'] is None and no_image['conditioning']=='t2v'
              and no_image['chain_source_sha256'] is None and no_image['chain_frame_index'] is None)
        chain_unit = dict(unit,image_path=os.path.join(td,'panel_02.chainseed.png'),
                          conditioning='chain',chain_source=clip)
        chained = render.build_clip_provenance(chain_unit,args)
        check('R18 chain provenance keys the SOURCE CLIP bytes, never the (absent) PNG',
              chained['image_sha256'] is None
              and chained['chain_source_sha256']==hashlib.sha256(b'video bytes').hexdigest())
        check('R18 chain provenance records the source frame index and its conditioning',
              chained['chain_frame_index']==args.frames-1 and chained['conditioning']=='chain')
```

1f. **Replace** `test_cached_model_metadata_and_io_failures` as follows. Delete the line `import comfyui_mlx_video_skill as bridge`. Keep everything from `with tempfile.TemporaryDirectory() as td:` through the `R20 broken existing snapshot` loop byte-identical. Replace the final `for backend in ('mlx','comfyui-mlx'):` block, still inside the outer `with`, with:
```python
        with _Harness(td,'provenanceio-mlx',1) as h:
            args = _stub_args(model=h.model)
            unit = render.build_units(render.load_manifest(h.manifest)['panels'],0,h.clips)[0]
            with mock.patch.object(render.os,'replace',side_effect=OSError('fixture publish denied')):
                result = render.render_panel(unit,args)
            check('R20 sidecar I/O maps to a failed unit',result['status']=='error' and result['clip'] is None)
            check('R20 sidecar I/O retains the clip and removes sidecar/temp',
                  os.path.isfile(unit['clip_path']) and not glob.glob(unit['clip_path']+'.provenance.json*'))
            check('R20 a verification failure is not fatal on the ltx-2-mlx backend',
                  not result.get('fatal'))
```

1g. **Replace** `test_provenance_rejects_changes_during_generation` entirely with:
```python
def test_provenance_rejects_changes_during_generation():
    from unittest import mock
    for changed in ('image','model'):
        with tempfile.TemporaryDirectory() as td:
            with _Harness(td,'toctou-'+changed,1) as h:
                unit = render.build_units(render.load_manifest(h.manifest)['panels'],0,h.clips)[0]
                args = _stub_args(model=h.model)
                original = render.SKILL.generate_video
                def mutate(*pos,**kwargs):
                    result = original(*pos,**kwargs)
                    target = unit['image_path'] if changed=='image' else os.path.join(h.model,'split_model.json')
                    with open(target,'ab') as handle: handle.write(b'changed')
                    return result
                with mock.patch.object(render.SKILL,'generate_video',side_effect=mutate):
                    result = render.render_panel(unit,args)
                check('R22 changed %s during generation fails without sidecar' % changed,
                      result['status']=='error' and not result.get('fatal')
                      and os.path.isfile(unit['clip_path'])
                      and not os.path.exists(unit['clip_path']+'.provenance.json'))
    with tempfile.TemporaryDirectory() as td:
        with _Harness(td,'identityresolved',1) as h:
            unit = render.build_units(render.load_manifest(h.manifest)['panels'],0,h.clips)[0]
            args = _stub_args(model='initially/uncached')
            with mock.patch.object(render,'model_identity',side_effect=[None,{'resolved_path':'new'}]):
                result = render.render_panel(unit,args)
            with open(unit['clip_path']+'.provenance.json') as handle: provenance = json.load(handle)
            check('R22 newly resolved identity is not adopted for generated clip',
                  result['status']=='ok' and provenance['model_identity'] is None)
```

- [ ] **Step 2: Run the test and confirm it fails.** Run `python3 tests/test_ltx_mlx_render.py; echo rc=$?`. Expected: `ModuleNotFoundError: No module named 'comfyui_mlx_video_skill'` at import, and `rc=1`.

- [ ] **Step 3: Write the implementation in `bin/ltx-mlx-render`.**
- Delete line 48, `import comfyui_mlx_video_skill as COMFY_MLX_SKILL  # noqa: E402`.
- Delete line 98, the `--video-backend` argument.
- In `load_manifest`, extend the docstring with the paragraph below, and replace the per-panel loop body from `if "image_path" not in panel ...` to the end of the loop with the code that follows it:
```
    Schema version 3 (bin/ltx-story-manifest --chain) requires a per-panel
    "conditioning" of still (an existing, readable image_path), chain (index >= 2,
    image_path null) or t2v (image_path null). For older schemas conditioning is
    derived: still when the panel has an image_path, else t2v -- so v1/v2 manifests
    behave exactly as before.
```
```python
        if "image_path" not in panel or panel.get("image_path") is None:
            panel["image_path"] = None
        else:
            image_path = panel["image_path"]
            if (not image_path or not os.path.isfile(image_path)
                    or not os.access(image_path, os.R_OK)):
                raise ValueError(
                    "panel %d: image_path does not exist or is not readable: %r"
                    % (index, image_path))

        if schema_version >= 3:
            conditioning = panel.get("conditioning")
            if conditioning not in ("still", "chain", "t2v"):
                raise ValueError("panel %d: conditioning must be one of still/chain/t2v, got %r"
                                 % (index, conditioning))
            if conditioning == "still" and panel["image_path"] is None:
                raise ValueError("panel %d: conditioning 'still' requires an existing, "
                                 "readable image_path" % index)
            if conditioning == "chain" and (index < 2 or panel["image_path"] is not None):
                raise ValueError("panel %d: conditioning 'chain' requires index >= 2 and "
                                 "image_path null" % index)
            if conditioning == "t2v" and panel["image_path"] is not None:
                raise ValueError("panel %d: conditioning 't2v' requires image_path null" % index)
        else:
            panel["conditioning"] = "still" if panel["image_path"] else "t2v"

        panel_text = panel.get("panel_text")
        if not isinstance(panel_text, str) or not panel_text.strip():
            raise ValueError("panel %d: panel_text is required and must be a "
                             "non-empty string" % index)
```
Also add `schema_version = data.get("schema_version", 1)` directly after `data = json.load(f)`.

- Replace `build_units` with:
```python
def build_units(panels, seed, clips_dir, run_root=None):
    """Return the ordered per-panel unit list.

    Each unit: {"index", "label", "seed", "prompt", "image_path", "clip_path",
    "log_path", "conditioning", "chain_source"}. seed is base + i and label is
    "panel-<i>", both identical to bin/ltx-story-video::build_units (:267) so the
    story_summary.json unit labels read the same way in
    bin/ltx-movie::_report_summary.

    A "chain" unit is conditioned on the exact last frame of the previous panel's
    clip: chain_source is that clip, and image_path is <clips_dir>/panel_%02d.chainseed.png,
    extracted at render time. Every other unit keeps the panel's own image_path and
    has chain_source None. panels must carry "conditioning" (load_manifest sets it).

    Every panel shares --frames/--width/--height/--frame-rate/--model and
    the low-ram + tiling settings; that uniformity is exactly what makes
    stream-copy concatenation valid, so it is NOT per-unit state."""
    units = []
    for i, panel in enumerate(panels, start=1):
        conditioning = panel["conditioning"]
        chained = conditioning == "chain"
        units.append({
            "index": i,
            "label": "panel-%d" % i,
            "seed": seed + i,
            "prompt": resolve_prompt(panel),
            "image_path": (os.path.join(clips_dir, "panel_%02d.chainseed.png" % i) if chained
                           else panel.get("image_path")),
            "clip_path": os.path.join(clips_dir, "panel_%02d.mp4" % i),
            "log_path": (os.path.join(run_root, "panel_%02d.log" % i)
                         if run_root else None),
            "conditioning": conditioning,
            "chain_source": (os.path.join(clips_dir, "panel_%02d.mp4" % (i - 1)) if chained
                             else None),
        })
    return units
```
- In `model_identity`, delete its first three lines: `import cctech_ltx25_runtime as source_runtime`, `if source_runtime.is_source_reference(model):` and `return source_runtime.model_identity(model)`.
- Replace `build_clip_provenance` with:
```python
def build_clip_provenance(unit, args, *, strict=False):
    """The exact generation identity a reusable clip must match. schema_version 2: every
    pre-redesign clip is deliberately non-reusable (it was conditioned on the old,
    cropped, independent stills). A chain unit is keyed on its SOURCE CLIP's bytes plus
    the frame index taken from it, not on the extracted PNG, so an ffmpeg PNG-encoder
    change cannot cascade a spurious re-render while any real change to clip k-1 does."""
    conditioning = unit["conditioning"]
    return {
        "schema_version": 2,
        "backend": "ltx-2-mlx",
        "model": args.model,
        "model_identity": model_identity(args.model, strict=strict),
        "prompt_sha256": hashlib.sha256(unit["prompt"].encode("utf-8")).hexdigest(),
        "conditioning": conditioning,
        "image_sha256": file_sha256(unit["image_path"]) if conditioning == "still" else None,
        "chain_source_sha256": (file_sha256(unit["chain_source"]) if conditioning == "chain"
                                else None),
        "chain_frame_index": args.frames - 1 if conditioning == "chain" else None,
        "seed": unit["seed"], "width": args.width, "height": args.height,
        "frames": args.frames, "fps": args.frame_rate, "low_ram": not args.no_low_ram,
        "tile_frames": args.tile_frames, "tile_spatial": args.tile_spatial,
    }
```
- In `print_dry_run`, replace the two lines `selected_skill = …` / `cmd = selected_skill.build_command(` with `cmd = SKILL.build_command(`, keeping the arguments. Replace the `estimate_seconds_per_panel(...)` call with:
```python
    secs, label = estimate_seconds_per_panel(
        story_dir_for(story_id), args.frames, args.width, args.height,
        (not args.no_low_ram), args.tile_frames, args.tile_spatial, args.model)
```
- In `render_panel`:
  - Delete both `if args.video_backend == "comfyui-mlx":` / `base["fatal"] = True` pairs (lines 652-653 and 696-697).
  - Replace the two lines `selected_skill = COMFY_MLX_SKILL if … else SKILL` / `clip = selected_skill.generate_video(` with the single line `clip = SKILL.generate_video(`.
  - Keep the `if getattr(e, "fatal", False):` branch.
- In `finish_run`'s `summary` literal, change the `"backend"` line to `"backend": "ltx-2-mlx",`.
- In `main()`, delete the `if args.video_backend == "comfyui-mlx":` block (lines 837-847). Replace the `clips_dir = args.clips_dir or os.path.join(...)` statement (lines 858-860) with `clips_dir = args.clips_dir or os.path.join(story_dir, "clips")`.

- [ ] **Step 4: Run the tests and confirm they pass.**
```bash
python3 bin/ltx-mlx-render --help > /dev/null; echo help_rc=$?
python3 tests/test_ltx_mlx_render.py; echo rc=$?
/usr/bin/grep -c "comfy\|COMFY\|cctech\|video_backend\|selected_skill" bin/ltx-mlx-render
```
Expected: `help_rc=0` (P1 fixed), `OK n/n` with `rc=0`, and the grep count is `0`.

- [ ] **Step 5: Checkpoint (no commit).**

---

## Task 9: `bin/ltx-mlx-render`: chain-seed helpers

**Files:** Modify `bin/ltx-mlx-render` and `tests/test_ltx_mlx_render.py`.

**Interfaces produced:**
- `CHAIN_SEED_MIN_YAVG = 20` and `CHAIN_SEED_MIN_YRANGE = 10`
- `ffprobe_image_size(path) -> ((w, h), None) | (None, reason)`
- `extract_last_frame(clip_path, out_png, frames) -> list[str]`
- `check_chain_seed(png_path, width, height, source_panel) -> list[str]` (G4)
- `prepare_chain_seed(unit, args) -> list[str]`

**Depends on:** Task 8.

- [ ] **Step 1: Write the failing tests.** Add these functions to `tests/test_ltx_mlx_render.py`, directly above `if __name__ == "__main__":`:
```python
# ---------------------------------------------------------------------------
# R23/R26/R27: chain-seed extraction and validation
# ---------------------------------------------------------------------------

def _rgb_framemd5(path, vf):
    """md5 of the single rgb24 frame ffmpeg produces for path under filter vf, or None."""
    proc = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-vf", vf,
                           "-fps_mode", "passthrough", "-f", "framemd5", "-"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    rows = [l for l in proc.stdout.splitlines() if l.strip() and not l.startswith("#")]
    if proc.returncode != 0 or len(rows) != 1:
        return None
    return rows[0].split(",")[-1].strip()


def test_extract_last_frame_argv():
    saved = render.subprocess.run
    seen = {}

    class _Ok(object):
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_ok(argv, **kw):
        seen["argv"], seen["kw"] = argv, kw
        with open(argv[-1], "wb") as f:
            f.write(b"PNGDATA")
        return _Ok()

    try:
        with tempfile.TemporaryDirectory() as td:
            out_png = os.path.join(td, "panel_02.chainseed.png")
            tmp_png = os.path.join(td, "panel_02.chainseed.tmp.png")
            render.subprocess.run = _fake_ok
            v = render.extract_last_frame("/c/panel_01.mp4", out_png, 145)
            check("R23a exact argv: select by exact index frames-1, passthrough, one frame, to .tmp.png",
                  seen.get("argv") == ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i",
                                       "/c/panel_01.mp4", "-vf", "select=eq(n\\,144)",
                                       "-fps_mode", "passthrough", "-frames:v", "1", tmp_png],
                  "got %r" % seen.get("argv"))
            check("R23b timeout=120", seen.get("kw", {}).get("timeout") == 120,
                  "got %r" % seen.get("kw"))
            check("R23c success returns []", v == [], "got %r" % v)
            check("R23d the tmp file is renamed onto the final path",
                  os.path.isfile(out_png) and not os.path.exists(tmp_png))

            class _Fail(object):
                returncode = 1
                stdout = ""
                stderr = "E1\nE2\nE3\nE4\nE5\nE6\n"
            render.subprocess.run = lambda argv, **kw: _Fail()
            v = render.extract_last_frame("/c/panel_01.mp4", out_png, 145)
            check("R23e rc!=0 -> one violation naming the clip and the last 5 stderr lines",
                  len(v) == 1 and v[0].startswith("clip /c/panel_01.mp4: last-frame extraction failed: ")
                  and "E6" in v[0] and "E2" in v[0] and "E1" not in v[0], "got %r" % v)

            render.subprocess.run = lambda argv, **kw: _Ok()
            os.remove(out_png)
            v = render.extract_last_frame("/c/panel_01.mp4", out_png, 145)
            check("R23f rc 0 but no file written -> a violation, nothing at the final path",
                  len(v) == 1 and "last-frame extraction failed" in v[0]
                  and not os.path.exists(out_png), "got %r" % v)

            def _fake_empty(argv, **kw):
                open(argv[-1], "wb").close()
                return _Ok()
            render.subprocess.run = _fake_empty
            v = render.extract_last_frame("/c/panel_01.mp4", out_png, 145)
            check("R23g a zero-byte frame -> a violation", len(v) == 1
                  and "last-frame extraction failed" in v[0], "got %r" % v)

            def _boom(argv, **kw):
                raise OSError("no ffmpeg here")
            render.subprocess.run = _boom
            v = render.extract_last_frame("/c/panel_01.mp4", out_png, 145)
            check("R23h OSError -> a violation carrying the exception text",
                  len(v) == 1 and "no ffmpeg here" in v[0], "got %r" % v)
    finally:
        render.subprocess.run = saved


def test_extract_last_frame_real_ffmpeg():
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("SKIP R23i-k real last-frame extraction: ffmpeg/ffprobe not on PATH")
        return
    with tempfile.TemporaryDirectory() as td:
        clip = os.path.join(td, "panel_01.mp4")
        proc = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
                               "testsrc2=size=64x64:rate=24", "-frames:v", "9", "-c:v", "libx264",
                               "-pix_fmt", "yuv420p", clip],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        check("R23i synthesized a 9-frame 64x64 h264 clip",
              proc.returncode == 0 and render.clip_frame_count(clip) == 9, proc.stdout[-400:])
        out_png = os.path.join(td, "panel_02.chainseed.png")
        v = render.extract_last_frame(clip, out_png, 9)
        check("R23j extraction succeeds and leaves no tmp file",
              v == [] and os.path.isfile(out_png)
              and not os.path.exists(os.path.join(td, "panel_02.chainseed.tmp.png")), "got %r" % v)
        want = _rgb_framemd5(clip, "select=eq(n\\,8),format=rgb24")
        got = _rgb_framemd5(out_png, "format=rgb24")
        not_last = _rgb_framemd5(clip, "select=eq(n\\,7),format=rgb24")
        check("R23k the PNG is exactly frame 8 -- the last -- and not frame 7",
              want is not None and got == want and not_last != want,
              "want=%r got=%r frame7=%r" % (want, got, not_last))


def test_check_chain_seed():
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("SKIP R26 check_chain_seed: ffmpeg/ffprobe not on PATH")
        return
    with tempfile.TemporaryDirectory() as td:
        def _still(name, source):
            path = os.path.join(td, name)
            p = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
                                source, "-frames:v", "1", path],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            return path if p.returncode == 0 else None
        black = _still("black.png", "color=c=black:s=64x64")
        grey = _still("grey.png", "color=c=0x808080:s=64x64")
        busy = _still("busy.png", "testsrc2=s=64x64")
        check("R26a synthesized black, flat-grey and testsrc2 frames", None not in (black, grey, busy))
        if None in (black, grey, busy):
            return
        v = render.check_chain_seed(black, 64, 64, 1)
        check("R26b a black frame is degenerate and names panel 1's Motion: as the remedy",
              len(v) == 1 and ("chain frame %s is degenerate (YAVG=" % black) in v[0]
              and "edit panel 1's Motion: in story.md" in v[0], "got %r" % v)
        v = render.check_chain_seed(grey, 64, 64, 4)
        check("R26c a flat grey frame (bright but no range) is degenerate",
              len(v) == 1 and "is degenerate" in v[0] and "edit panel 4's Motion:" in v[0],
              "got %r" % v)
        check("R26d a testsrc2 frame passes", render.check_chain_seed(busy, 64, 64, 1) == [],
              "got %r" % render.check_chain_seed(busy, 64, 64, 1))
        v = render.check_chain_seed(busy, 128, 64, 1)
        check("R26e the wrong size is a size violation",
              v == ["chain frame %s is 64x64, expected 128x64" % busy], "got %r" % v)
        missing = os.path.join(td, "missing.png")
        v = render.check_chain_seed(missing, 64, 64, 1)
        check("R26f a missing frame is an ffprobe failure",
              len(v) == 1 and v[0].startswith("chain frame %s: ffprobe failed: " % missing),
              "got %r" % v)


def test_prepare_chain_seed_composition():
    saved = (render.extract_last_frame, render.check_chain_seed)
    seen = []
    try:
        unit = {"index": 3, "chain_source": "/c/panel_02.mp4",
                "image_path": "/c/panel_03.chainseed.png"}
        args = _stub_args(frames=145, width=512, height=384)
        render.extract_last_frame = lambda clip, png, frames: (
            seen.append(("x", clip, png, frames)) or ["extract failed"])
        render.check_chain_seed = lambda png, w, h, src: (seen.append(("c", png, w, h, src)) or [])
        v = render.prepare_chain_seed(unit, args)
        check("R27a an extraction failure short-circuits the frame check",
              v == ["extract failed"]
              and seen == [("x", "/c/panel_02.mp4", "/c/panel_03.chainseed.png", 145)],
              "v=%r seen=%r" % (v, seen))
        seen[:] = []
        render.extract_last_frame = lambda clip, png, frames: (seen.append(("x",)) or [])
        render.check_chain_seed = lambda png, w, h, src: (
            seen.append(("c", png, w, h, src)) or ["bad frame"])
        v = render.prepare_chain_seed(unit, args)
        check("R27b after a clean extraction the frame is checked at --width x --height, "
              "naming panel index-1", v == ["bad frame"]
              and seen == [("x",), ("c", "/c/panel_03.chainseed.png", 512, 384, 2)],
              "v=%r seen=%r" % (v, seen))
    finally:
        render.extract_last_frame, render.check_chain_seed = saved
```
Add to `__main__`, directly after `test_failure_state_machine()`:
```python
    test_extract_last_frame_argv()
    test_extract_last_frame_real_ffmpeg()
    test_check_chain_seed()
    test_prepare_chain_seed_composition()
```

- [ ] **Step 2: Run the test and confirm it fails.** Run `python3 tests/test_ltx_mlx_render.py; echo rc=$?`. Expected: `AttributeError: module 'ltx_mlx_render' has no attribute 'extract_last_frame'` and `rc=1`.

- [ ] **Step 3: Write the implementation in `bin/ltx-mlx-render`.**
- Add `import re` to the imports, directly after `import os`.
- Directly after the `SUMMARY_KEYS = (...)` tuple, add:
```python
# A chained panel's conditioning frame is rejected as black or flat below these
# signalstats luma levels. Heuristics: limited-range black is Y=16.
CHAIN_SEED_MIN_YAVG = 20
CHAIN_SEED_MIN_YRANGE = 10
```
- Directly after `clip_is_reusable` (before `_REMEDY = ...`), add:
```python
def ffprobe_image_size(path):
    """((width, height), None) for an image file, or (None, reason) when ffprobe cannot
    say. ffprobe rather than PIL: this script imports no image library (R2a)."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)
    if proc.returncode != 0:
        return None, "rc=%d: %s" % (proc.returncode, proc.stderr.strip())
    try:
        stream = json.loads(proc.stdout)["streams"][0]
        return (int(stream["width"]), int(stream["height"])), None
    except (ValueError, KeyError, IndexError, TypeError) as e:
        return None, "unparseable ffprobe output (%s: %s)" % (type(e).__name__, e)


def extract_last_frame(clip_path, out_png, frames):
    """Write frame index frames-1 of clip_path -- its exact last frame -- to out_png.
    Returns [] on success, else one violation string.

    Selecting by exact index is deterministic because every ok or reused clip has
    already been verified at exactly --frames frames. -sseof is deliberately not used:
    it seeks by time, not to the last frame. The frame is written to a .tmp.png first
    and renamed, so a partial write is never mistaken for a frame."""
    tmp = out_png[:-len(".png")] + ".tmp.png"
    try:
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", clip_path,
             "-vf", "select=eq(n\\,%d)" % (frames - 1), "-fps_mode", "passthrough",
             "-frames:v", "1", tmp],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return ["clip %s: last-frame extraction failed: %s" % (clip_path, e)]
    if proc.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
        tail = "\n".join((proc.stderr or "").splitlines()[-5:])
        reason = tail or ("ffmpeg exited %d and wrote no frame %d to %s"
                          % (proc.returncode, frames - 1, tmp))
        return ["clip %s: last-frame extraction failed: %s" % (clip_path, reason)]
    os.replace(tmp, out_png)
    return []


def check_chain_seed(png_path, width, height, source_panel):
    """Validate an extracted chain frame: exactly width x height, and neither black nor
    flat by ffmpeg signalstats luma. source_panel is the panel whose clip the frame came
    from; the remedy names that panel's Motion:. Returns [] or one violation string."""
    size, error = ffprobe_image_size(png_path)
    if error:
        return ["chain frame %s: ffprobe failed: %s" % (png_path, error)]
    if size != (width, height):
        return ["chain frame %s is %dx%d, expected %dx%d"
                % (png_path, size[0], size[1], width, height)]
    try:
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-nostdin", "-i", png_path,
             "-vf", "signalstats,metadata=mode=print:file=-", "-f", "null", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ["chain frame %s: could not measure brightness" % png_path]
    stats = dict(re.findall(r"lavfi\.signalstats\.(YAVG|YMIN|YMAX)=([0-9.]+)",
                            proc.stdout or ""))
    if proc.returncode != 0 or set(stats) != {"YAVG", "YMIN", "YMAX"}:
        return ["chain frame %s: could not measure brightness" % png_path]
    yavg, ymin, ymax = float(stats["YAVG"]), float(stats["YMIN"]), float(stats["YMAX"])
    if yavg < CHAIN_SEED_MIN_YAVG or ymax - ymin < CHAIN_SEED_MIN_YRANGE:
        return ["chain frame %s is degenerate (YAVG=%.1f, YMIN=%.1f, YMAX=%.1f): black or "
                "flat; edit panel %d's Motion: in story.md to change it, then rerun -- the "
                "edited panel and every later panel re-render"
                % (png_path, yavg, ymin, ymax, source_panel)]
    return []


def prepare_chain_seed(unit, args):
    """Extract and validate a chain unit's conditioning frame. Returns [] when
    unit["image_path"] holds a usable frame, else the violations."""
    return (extract_last_frame(unit["chain_source"], unit["image_path"], args.frames)
            or check_chain_seed(unit["image_path"], args.width, args.height,
                                unit["index"] - 1))
```

- [ ] **Step 4: Run the tests and confirm they pass.** Run `python3 tests/test_ltx_mlx_render.py; echo rc=$?`. Expected: `OK n/n` with `rc=0`, with no `SKIP R23`/`SKIP R26` lines, since ffmpeg is on this host. Kept test R2a still passes because `re` is not a forbidden module.

- [ ] **Step 5: Checkpoint (no commit).**

---

## Task 10: `bin/ltx-mlx-render`: chain loop, in-order dry-run prediction, v3 still-aspect preflight

**Files:** Modify `bin/ltx-mlx-render` and `tests/test_ltx_mlx_render.py`.

**Depends on:** Tasks 8 and 9.

- [ ] **Step 1: Write the failing tests.** Add these to `tests/test_ltx_mlx_render.py`, directly above `if __name__ == "__main__":`:
```python
# ---------------------------------------------------------------------------
# R24/R25/R28-R32: the chain loop (a v3 --chain manifest through the REAL main()
# loop and the REAL finish_run; render_panel and the chain seed are scripted)
# ---------------------------------------------------------------------------

def _write_chain_manifest(td, story_id, n_panels):
    still = os.path.join(td, "%s_still.png" % story_id)
    with open(still, "wb") as f:
        f.write(b"png")
    panels = [{"index": 1, "image_path": still, "panel_text": "still image text",
               "motion_prompt": "motion 1", "conditioning": "still", "num_frames": 145}]
    for i in range(2, n_panels + 1):
        panels.append({"index": i, "image_path": None, "panel_text": "motion %d" % i,
                       "motion_prompt": "motion %d" % i, "conditioning": "chain",
                       "num_frames": 145})
    return _write_manifest(td, panels, story_id=story_id, schema_version=3), still


def _drive_chain(td, story_id, n_panels, extra_argv, script=None, seed_violations=None,
                 screen=None, still_probe=((704, 448), None)):
    """script[i] is the list of statuses successive render_panel calls on panel i
    return ("ok"/"error"); a panel missing from script always returns "ok".
    seed_violations[i] is what prepare_chain_seed returns for panel i (default []).
    screen replaces run_input_content_screen (default: always 0). still_probe is
    what ffprobe_image_size returns for the panel-1 still.
    Returns (rc, calls, summary, prepared, stdout, stderr)."""
    manifest, _still = _write_chain_manifest(td, story_id, n_panels)
    clips = os.path.join(td, "clips_%s" % story_id)
    out = os.path.join(td, "%s.mp4" % story_id)
    story_root = os.path.join(td, "story")
    os.makedirs(os.path.join(story_root, story_id), exist_ok=True)
    script = script or {}
    calls, prepared, attempts = [], [], {}

    def fake_render_panel(unit, args):
        i = unit["index"]
        calls.append(i)
        n = attempts.get(i, 0)
        attempts[i] = n + 1
        statuses = script.get(i, ["ok"])
        status = statuses[min(n, len(statuses) - 1)]
        if status == "ok":
            return {"unit": unit["label"], "status": "ok", "attempts": 1, "seconds": 1.0,
                    "clip": os.path.abspath(unit["clip_path"]), "resumed": False}
        return {"unit": unit["label"], "status": status, "attempts": 1, "seconds": 0.1,
                "clip": None, "rc": 1, "error": "stub failure"}

    def fake_prepare(unit, args):
        prepared.append(unit["index"])
        return list((seed_violations or {}).get(unit["index"], []))

    saved = (render.story_dir_for, render.render_panel, render.prepare_chain_seed,
             render.run_input_content_screen, render.SKILL._resolve_bin,
             render.ffprobe_image_size, render.probe_streams, render.assert_clips_uniform,
             render.build_concat_command)
    so, se = io.StringIO(), io.StringIO()
    try:
        render.story_dir_for = lambda sid: os.path.join(story_root, sid)
        render.render_panel = fake_render_panel
        render.prepare_chain_seed = fake_prepare
        render.run_input_content_screen = screen or (lambda paths: 0)
        render.SKILL._resolve_bin = lambda: sys.executable
        render.ffprobe_image_size = lambda path: still_probe
        render.probe_streams = lambda p: {"streams": []}
        render.assert_clips_uniform = lambda *a: None
        render.build_concat_command = lambda lp, o: [
            sys.executable, "-c", "import sys; open(sys.argv[1],'wb').write(b'MOVIE')", o]
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            rc = render.main([manifest, out, "--clips-dir", clips] + extra_argv)
    finally:
        (render.story_dir_for, render.render_panel, render.prepare_chain_seed,
         render.run_input_content_screen, render.SKILL._resolve_bin,
         render.ffprobe_image_size, render.probe_streams, render.assert_clips_uniform,
         render.build_concat_command) = saved
    found = glob.glob(os.path.join(story_root, story_id, "runs", "*", "story_summary.json"))
    summary = None
    if found:
        with open(max(found, key=os.path.getmtime)) as f:
            summary = json.load(f)
    return rc, calls, summary, prepared, so.getvalue(), se.getvalue()


def _clip_names(summary):
    return [os.path.basename(c) for c in (summary or {}).get("clips", [])]


def test_chain_manifest_rejects_skip_policy():
    with tempfile.TemporaryDirectory() as td:
        for extra, tag in (([], "R31a"), (["--dry-run"], "R31b")):
            rc, calls, summary, prepared, out, err = _drive_chain(
                td, "skipchain%s" % tag, 3, ["--skip-input-screen", "--on-panel-failure", "skip"] + extra)
            check("%s --on-panel-failure skip on a chained manifest exits 2 before any work" % tag,
                  rc == 2 and calls == [] and summary is None
                  and "--on-panel-failure skip is not allowed for a chained manifest: a skipped "
                      "panel leaves the next panel with no frame to continue from" in err,
                  "rc=%r calls=%r err=%r" % (rc, calls, err))


def test_chain_loop_inline_retry_then_stop():
    with tempfile.TemporaryDirectory() as td:
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "retrystop", 3, ["--skip-input-screen", "--retry-failed", "1", "--retry-idle", "0"],
            script={2: ["error", "error"]})
        check("R24a panel 2 fails twice -> exit 1", rc == 1, "rc=%r" % rc)
        check("R24b panel 2 was rendered twice (inline retry), panel 3 never",
              calls == [1, 2, 2], "calls=%r" % calls)
        check("R24c stopped_reason is chain_broken", s and s["stopped_reason"] == "chain_broken",
              "got %r" % (s or {}).get("stopped_reason"))
        check("R24d panel 3 is not_attempted",
              s and s["units"][2]["status"] == "not_attempted", "got %r" % (s or {}).get("units"))
        check("R24e the retry is recorded as attempt 2 with its first failure",
              s and s["units"][1]["attempts"] == 2 and s["units"][1]["first_failure"] == "error",
              "got %r" % (s or {}).get("units"))
        check("R24f the completed prefix (panel 1) is concatenated into the movie",
              _clip_names(s) == ["panel_01.mp4"] and s["output_path"] is not None,
              "got %r" % _clip_names(s))
        check("R24g the inline-retry banner and the relaunch hint are printed",
              "=== inline retry: panel 2 (chained; later panels depend on it) ===" in out
              and "relaunch:" in out, "got %r" % out[-1200:])
        check("R24h the chain seed is prepared once for panel 2 (the retry reuses it)",
              prepared == [2], "prepared=%r" % prepared)

    with tempfile.TemporaryDirectory() as td:
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "retryok", 3, ["--skip-input-screen", "--retry-failed", "1", "--retry-idle", "0"],
            script={2: ["error", "ok"]})
        check("R24i a successful inline retry completes the chain and exits 0",
              rc == 0 and calls == [1, 2, 2, 3] and prepared == [2, 3]
              and s["units"][1]["status"] == "ok" and s["units"][1]["attempts"] == 2
              and s["stopped_reason"] is None,
              "rc=%r calls=%r prepared=%r" % (rc, calls, prepared))

    with tempfile.TemporaryDirectory() as td:
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "noretry", 3, ["--skip-input-screen"], script={2: ["error"]})
        check("R24j without --retry-failed one failure is chain_broken",
              rc == 1 and calls == [1, 2] and s["stopped_reason"] == "chain_broken",
              "rc=%r calls=%r" % (rc, calls))

    with tempfile.TemporaryDirectory() as td:
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "p1fails", 3, ["--skip-input-screen", "--retry-failed", "1", "--retry-idle", "0"],
            script={1: ["error", "error"]})
        check("R24k panel 1 of a chained manifest also retries inline, then stops",
              rc == 1 and calls == [1, 1] and prepared == [] and s["stopped_reason"] == "chain_broken"
              and s["output_path"] is None, "rc=%r calls=%r" % (rc, calls))

    # G14: the end-of-run retry pass must never run for a chained manifest, even when
    # finish_run is reached with stopped_reason None.
    saved = (render.render_panel, render.probe_streams, render.assert_clips_uniform,
             render.build_concat_command)
    retried = []
    try:
        render.render_panel = lambda unit, args: (retried.append(unit["index"]) or {
            "unit": unit["label"], "status": "ok", "attempts": 1, "seconds": 0.0,
            "clip": "/a/2.mp4", "resumed": False})
        render.probe_streams = lambda p: {"streams": []}
        render.assert_clips_uniform = lambda *a: None
        render.build_concat_command = lambda lp, o: [
            sys.executable, "-c", "import sys; open(sys.argv[1],'wb').write(b'M')", o]
        with tempfile.TemporaryDirectory() as td:
            run_root = os.path.join(td, "run")
            os.makedirs(run_root)
            args = render.build_parser().parse_args(
                [os.path.join(td, "m.json"), os.path.join(td, "out.mp4"),
                 "--retry-failed", "1", "--retry-idle", "0"])
            panels = [{"index": 1, "image_path": "/s.png", "panel_text": "t", "motion_prompt": "m",
                       "conditioning": "still"},
                      {"index": 2, "image_path": None, "panel_text": "m2", "motion_prompt": "m2",
                       "conditioning": "chain"}]
            units = render.build_units(panels, 0, os.path.join(td, "clips"), run_root)
            ur = {1: {"unit": "panel-1", "status": "ok", "attempts": 1, "seconds": 1.0,
                      "clip": "/a/1.mp4", "resumed": False},
                  2: {"unit": "panel-2", "status": "error", "attempts": 1, "seconds": 0.1,
                      "clip": None, "rc": 1, "error": "x"}}
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                render.finish_run(args, ["m", "o"], {"schema_version": 3}, units, ur,
                                  {1: "/a/1.mp4"}, 1, None, run_root, "sid")
        check("R24l the end-of-run retry pass never runs for a chained manifest", retried == [],
              "retried=%r" % retried)
    finally:
        (render.render_panel, render.probe_streams, render.assert_clips_uniform,
         render.build_concat_command) = saved


def test_chain_loop_seed_invalid_stops():
    with tempfile.TemporaryDirectory() as td:
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "seedbad", 3, ["--skip-input-screen", "--retry-failed", "1", "--retry-idle", "0"],
            seed_violations={2: ["chain frame X is degenerate (YAVG=16.0, YMIN=16.0, YMAX=16.0)"]})
        check("R28a a degenerate chain frame stops the run before panel 2 renders",
              rc == 1 and calls == [1] and prepared == [2], "rc=%r calls=%r" % (rc, calls))
        check("R28b panel 2 is recorded chain_seed_invalid with 0 attempts and the reason",
              s and s["units"][1]["status"] == "chain_seed_invalid"
              and s["units"][1]["attempts"] == 0 and "degenerate" in s["units"][1]["error"],
              "got %r" % (s or {}).get("units"))
        check("R28c stopped_reason chain_seed_invalid; panel 3 not_attempted; prefix kept",
              s["stopped_reason"] == "chain_seed_invalid"
              and s["units"][2]["status"] == "not_attempted" and _clip_names(s) == ["panel_01.mp4"])
        check("R28d the operator sees 'panel 2 FAILED (chain seed):'",
              "panel 2 FAILED (chain seed): chain frame X is degenerate" in err, "got %r" % err)

    with tempfile.TemporaryDirectory() as td:
        screened = []

        def screen(paths):
            screened.append(list(paths))
            return 3 if any(p.endswith(".chainseed.png") for p in paths) else 0
        rc, calls, s, prepared, out, err = _drive_chain(td, "seedblocked", 3, [], screen=screen)
        check("R28e a chain frame that fails the content screen stops the run",
              rc == 1 and calls == [1] and s["units"][1]["status"] == "chain_seed_blocked"
              and s["stopped_reason"] == "chain_seed_blocked", "rc=%r calls=%r" % (rc, calls))
        check("R28f the still is screened at startup and the chain frame before its render",
              len(screened) == 2 and screened[0][0].endswith("seedblocked_still.png")
              and screened[1][0].endswith("panel_02.chainseed.png"), "got %r" % screened)

    with tempfile.TemporaryDirectory() as td:
        screened = []
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "noscreen", 3, ["--skip-input-screen"],
            screen=lambda paths: (screened.append(list(paths)) or 0))
        check("R28g --skip-input-screen also skips the chain-frame screen",
              rc == 0 and screened == [] and calls == [1, 2, 3], "rc=%r screened=%r" % (rc, screened))


def test_chain_resume_cascade():
    saved = render.clip_frame_count
    try:
        render.clip_frame_count = lambda p: 145
        with tempfile.TemporaryDirectory() as td:
            model = os.path.join(td, "model")
            os.makedirs(model)
            with open(os.path.join(model, "split_model.json"), "w") as f:
                f.write("{}")
            still = os.path.join(td, "still.png")
            with open(still, "wb") as f:
                f.write(b"still")
            clips = os.path.join(td, "clips")
            os.makedirs(clips)

            def _panels(p2="motion 2"):
                return [{"index": 1, "image_path": still, "panel_text": "img",
                         "motion_prompt": "motion 1", "conditioning": "still"},
                        {"index": 2, "image_path": None, "panel_text": p2, "motion_prompt": p2,
                         "conditioning": "chain"},
                        {"index": 3, "image_path": None, "panel_text": "motion 3",
                         "motion_prompt": "motion 3", "conditioning": "chain"}]

            args = _stub_args(model=model, frames=145, resume=True)
            units = render.build_units(_panels(), 0, clips)
            for u in units:  # an earlier, complete run, recorded in order
                with open(u["clip_path"], "wb") as f:
                    f.write(("clip %d" % u["index"]).encode())
                render.write_clip_provenance(u["clip_path"], render.build_clip_provenance(u, args))

            def _predict(us):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    render.print_dry_run(args, {"schema_version": 3}, us,
                                         "_cascade_%d" % os.getpid(), clips)
                out = buf.getvalue()
                m = re.search(r"resume: \d+ panel\(s\) would render: (\[.*\])", out)
                return (json.loads(m.group(1)) if m else None), out

            got, _ = _predict(units)
            check("R25a unchanged prompts reuse all three clips", got == [], "got %r" % got)
            got, out = _predict(render.build_units(_panels(p2="motion 2 edited"), 0, clips))
            check("R25b editing panel 2's Motion: reuses 1 and re-renders 2 and 3",
                  got == [2, 3], "got %r" % got)
            check("R25c the first render command conditions on panel 2's chain seed",
                  "panel_02.chainseed.png" in out.split("first render command:")[1].splitlines()[0],
                  "got %r" % out)
            with open(units[0]["clip_path"], "wb") as f:
                f.write(b"clip 1 re-rendered")
            render.write_clip_provenance(units[0]["clip_path"],
                                         render.build_clip_provenance(units[0], args))
            got, _ = _predict(units)
            check("R25d new clip-1 bytes (with a valid clip-1 sidecar) re-render 2 and 3",
                  got == [2, 3], "got %r" % got)
    finally:
        render.clip_frame_count = saved


def test_v3_still_aspect_preflight():
    with tempfile.TemporaryDirectory() as td:
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "aspectbad", 2, ["--skip-input-screen"], still_probe=((1280, 704), None))
        check("R29a a 1280x704 still against --width 704 --height 448 exits 2, no render",
              rc == 2 and calls == [] and s is None
              and "is 1280x704; its aspect ratio does not match --width x --height (704x448), "
                  "so ltx-2-mlx would crop it" in err, "rc=%r err=%r" % (rc, err))
        check("R29b no run root was created",
              not glob.glob(os.path.join(td, "story", "aspectbad", "runs", "*")))
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "aspectok", 2, ["--skip-input-screen"], still_probe=((1408, 896), None))
        check("R29c a 1408x896 still (2W x 2H) passes", rc == 0 and calls == [1, 2],
              "rc=%r err=%r" % (rc, err))
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "aspectprobe", 2, ["--skip-input-screen"], still_probe=(None, "rc=1: boom"))
        check("R29d an unmeasurable still exits 2", rc == 2 and "ffprobe failed: rc=1: boom" in err,
              "rc=%r err=%r" % (rc, err))
        probed = []
        saved = render.ffprobe_image_size
        render.ffprobe_image_size = lambda p: (probed.append(p) or ((1, 1), None))
        try:
            rc, cap, rendered, _ = _drive_main(td, "v2noprobe", 2, ["--on-panel-failure", "skip"],
                                               panel_status="ok")
        finally:
            render.ffprobe_image_size = saved
        check("R29e a schema_version 2 manifest is never aspect-probed",
              probed == [] and rendered == [1, 2], "probed=%r rendered=%r" % (probed, rendered))


def test_dry_run_chain_lines():
    with tempfile.TemporaryDirectory() as td:
        manifest, still = _write_chain_manifest(td, "drychain", 3)
        clips = os.path.join(td, "clips")
        os.makedirs(clips)
        r = _run_render([manifest, os.path.join(td, "movie.mp4"), "--clips-dir", clips,
                         "--frames", "145", "--dry-run"])
        o = r.stdout
        check("R30a a chained dry run exits 0", r.returncode == 0,
              "rc=%r stderr=%r" % (r.returncode, r.stderr))
        check("R30b panel 1 is I2V from the still", ("  panel  1: I2V %s" % still) in o, "got %r" % o)
        check("R30c panels 2-3 name the exact source frame and clip",
              ("  panel  2: I2V chained <- last frame (index 144) of %s"
               % os.path.join(clips, "panel_01.mp4")) in o
              and ("  panel  3: I2V chained <- last frame (index 144) of %s"
                   % os.path.join(clips, "panel_02.mp4")) in o, "got %r" % o)
        check("R30d the first render command conditions on the still",
              still in o.split("first render command:")[1].splitlines()[0], "got %r" % o)
        check("R30e the dry run wrote nothing", os.listdir(clips) == [])


def test_single_panel_v3_manifest_is_not_chained():
    with tempfile.TemporaryDirectory() as td:
        rc, calls, s, prepared, out, err = _drive_chain(td, "single", 1, ["--skip-input-screen"])
        check("R32a a one-panel v3 manifest renders its still and concatenates one clip",
              rc == 0 and calls == [1] and prepared == [] and _clip_names(s) == ["panel_01.mp4"],
              "rc=%r calls=%r" % (rc, calls))
        rc, calls, s, prepared, out, err = _drive_chain(
            td, "singleskip", 1, ["--skip-input-screen", "--on-panel-failure", "skip"])
        check("R32b it has no chain units, so --on-panel-failure skip is allowed",
              rc == 0 and calls == [1], "rc=%r err=%r" % (rc, err))
```
Add to `__main__`, directly after `test_prepare_chain_seed_composition()`:
```python
    test_chain_manifest_rejects_skip_policy()
    test_chain_loop_inline_retry_then_stop()
    test_chain_loop_seed_invalid_stops()
    test_chain_resume_cascade()
    test_v3_still_aspect_preflight()
    test_dry_run_chain_lines()
    test_single_panel_v3_manifest_is_not_chained()
```

- [ ] **Step 2: Run the test and confirm it fails.** Run `python3 tests/test_ltx_mlx_render.py; echo rc=$?`. Expected: `FAIL R31a…`, `FAIL R24b…` (panel 3 still renders, because there is no chain branch yet) and `FAIL R29a…`, then `rc=1`.

- [ ] **Step 3: Write the implementation in `bin/ltx-mlx-render`.**

3a. Replace `print_dry_run` with:
```python
def print_dry_run(args, manifest, units, story_id, clips_dir):
    """Resolve everything, touch nothing, print the plan, return 0.

    Deliberately does NOT check for the ltx-2-mlx binary or ffmpeg: a dry run
    must be usable on a machine that cannot render.

    The --resume prediction runs IN ORDER: a chained unit is predicted reusable only
    when the unit before it is predicted reusable too -- otherwise its source clip is
    about to be re-rendered -- and only then is its source clip hashed."""
    seconds_per_panel_play = args.frames / float(args.frame_rate)
    total_panels = len(units)

    print("manifest: %s" % os.path.abspath(args.manifest_path))
    print("story id: %s" % story_id)
    print("panels: %d" % total_panels)
    for unit in units:
        if unit["conditioning"] == "chain":
            print("  panel %2d: I2V chained <- last frame (index %d) of %s"
                  % (unit["index"], args.frames - 1, unit["chain_source"]))
        elif unit["image_path"]:
            print("  panel %2d: I2V %s" % (unit["index"], unit["image_path"]))
        else:
            print("  panel %2d: T2V (no conditioning image)" % unit["index"])
    print("clips dir: %s" % clips_dir)
    print("output: %s" % os.path.abspath(args.output_path))
    print("geometry: %dx%d, %d frames @ %d fps = %.2f s per panel"
          % (args.width, args.height, args.frames, args.frame_rate,
             seconds_per_panel_play))
    print("total: %d panels x %.2f s = %.2f s of finished movie"
          % (total_panels, seconds_per_panel_play,
             total_panels * seconds_per_panel_play))
    print("note: manifest per-panel num_frames is ignored; --frames %d is authoritative"
          % args.frames)

    would_skip = []
    would_render = []
    skipped = set()
    for unit in units:
        reusable = False
        if args.resume and (unit["conditioning"] != "chain" or unit["index"] - 1 in skipped):
            reusable = clip_is_reusable(unit["clip_path"], args.frames,
                                        build_clip_provenance(unit, args))
        if reusable:
            would_skip.append(unit)
            skipped.add(unit["index"])
        else:
            would_render.append(unit)

    if would_render:
        first = would_render[0]
        cmd = SKILL.build_command(
            prompt=first["prompt"], output_path=first["clip_path"],
            image_path=first["image_path"], width=args.width, height=args.height,
            num_frames=args.frames, frame_rate=args.frame_rate, seed=first["seed"],
            model=args.model, low_ram=(not args.no_low_ram),
            tile_frames=args.tile_frames, tile_spatial=args.tile_spatial)
        print("first render command: %s" % shlex.join(cmd))
    else:
        print("first render command: (none; all panels would be skipped)")

    if args.resume:
        print("resume: %d panel(s) would be skipped: %r"
              % (len(would_skip), [u["index"] for u in would_skip]))
        print("resume: %d panel(s) would render: %r"
              % (len(would_render), [u["index"] for u in would_render]))

    secs, label = estimate_seconds_per_panel(
        story_dir_for(story_id), args.frames, args.width, args.height,
        (not args.no_low_ram), args.tile_frames, args.tile_spatial, args.model)
    for line in format_estimate_lines(secs, label, len(would_render), total_panels):
        print(line)

    return 0
```

3b. In `finish_run`:
- Change the retry-pass comment and condition to:
```python
    # --- retry pass (opt-in). Never runs when the main loop already stopped, and never
    # for a chained manifest: its failures were already retried inline, in order.
    failed = [u for u in units
              if unit_results[u["index"]]["status"] not in ("ok", "not_attempted")]
    if (args.retry_failed and failed and stopped_reason is None
            and not any(u.get("conditioning") == "chain" for u in units)):
```
The body of the `if` is unchanged.
- Change `if stopped_reason == "consecutive_failures":` to `if stopped_reason in ("consecutive_failures", "chain_broken"):`.

3c. In `main()`, make three changes.

**(i)** Directly after `panels = manifest["panels"]`, insert:
```python
    # A chained manifest (any panel conditioned on the previous clip's last frame) cannot
    # skip a failed panel: the next one would have no frame to continue from. Checked
    # before the --dry-run short-circuit so the Phase 3 review gate refuses it too.
    chain_manifest = any(p["conditioning"] == "chain" for p in panels)
    if chain_manifest and args.on_panel_failure == "skip":
        print("Error: --on-panel-failure skip is not allowed for a chained manifest: a "
              "skipped panel leaves the next panel with no frame to continue from",
              file=sys.stderr)
        return 2
```

**(ii)** Directly after the ltx-2-mlx binary check (after its `return 2`) and before `try: os.makedirs(clips_dir, ...)`, insert:
```python
    # v3 still-aspect preflight: a still whose aspect differs from --width x --height
    # would be center-cropped by ltx-2-mlx's resize_and_center_crop. Refused here,
    # before any GPU time.
    if manifest.get("schema_version", 1) >= 3:
        for panel in panels:
            if panel["conditioning"] != "still":
                continue
            size, error = ffprobe_image_size(panel["image_path"])
            if error:
                print("Error: panel %d's still %s: ffprobe failed: %s"
                      % (panel["index"], panel["image_path"], error), file=sys.stderr)
                return 2
            if size[0] * args.height != size[1] * args.width:
                print("Error: panel %d's still %s is %dx%d; its aspect ratio does not match "
                      "--width x --height (%dx%d), so ltx-2-mlx would crop it"
                      % (panel["index"], panel["image_path"], size[0], size[1],
                         args.width, args.height), file=sys.stderr)
                return 2
```

**(iii)** Replace the per-unit loop, from `for unit in units:` through the end of the circuit-breaker `break` and before the `not_attempted` backfill loop, with:
```python
    for unit in units:
        i = unit["index"]
        if args.resume and clip_is_reusable(
                unit["clip_path"], args.frames, build_clip_provenance(unit, args)):
            print("panel %d: reusing %s (--resume)" % (i, unit["clip_path"]))
            unit_results[i] = {"unit": unit["label"], "status": "ok", "attempts": 0,
                               "seconds": 0.0,
                               "clip": os.path.abspath(unit["clip_path"]),
                               "resumed": True}
            clips_by_index[i] = os.path.abspath(unit["clip_path"])
            completed += 1
            consecutive_failures = 0
            continue

        print("=== panel %d/%d (%s) ===" % (i, len(units), unit["label"]))

        if unit["conditioning"] == "chain":
            seed_violations = prepare_chain_seed(unit, args)
            if seed_violations:
                for v in seed_violations:
                    print("panel %d FAILED (chain seed): %s" % (i, v), file=sys.stderr)
                unit_results[i] = {"unit": unit["label"], "status": "chain_seed_invalid",
                                   "attempts": 0, "seconds": 0.0, "clip": None,
                                   "resumed": False, "error": "; ".join(seed_violations)}
                stopped_reason = "chain_seed_invalid"
                break
            if not args.skip_input_screen:
                screen_rc = run_input_content_screen([unit["image_path"]])
                if screen_rc != 0:
                    error = ("input content screen rejected %s (rc=%d)"
                             % (unit["image_path"], screen_rc))
                    print("panel %d FAILED (chain seed): %s" % (i, error), file=sys.stderr)
                    unit_results[i] = {"unit": unit["label"], "status": "chain_seed_blocked",
                                       "attempts": 0, "seconds": 0.0, "clip": None,
                                       "resumed": False, "error": error}
                    stopped_reason = "chain_seed_blocked"
                    break

        result = render_panel(unit, args)
        unit_results[i] = result

        if result["status"] == "ok":
            clips_by_index[i] = result["clip"]
            completed += 1
            consecutive_failures = 0
            continue

        if result.get("fatal"):
            stopped_reason = "backend_failure"
            break

        if chain_manifest:
            # Every later panel depends on this clip, so a chained failure is retried
            # inline (never deferred to the end-of-run pass) and then stops the run; the
            # skip policy and the consecutive-failure breaker are not consulted.
            if args.retry_failed:
                print("=== inline retry: panel %d (chained; later panels depend on it) ===" % i)
                time.sleep(args.retry_idle)
                retry = render_panel(unit, args)
                retry["attempts"] = 2
                retry["first_failure"] = result["status"]
                unit_results[i] = retry
                if retry["status"] == "ok":
                    clips_by_index[i] = retry["clip"]
                    completed += 1
                    continue
            stopped_reason = "chain_broken"
            break

        consecutive_failures += 1
        # Checked in the same order as bin/ltx-story-video:927-929: the stop
        # policy wins first, then the consecutive-failure circuit breaker.
        if args.on_panel_failure == "stop":
            stopped_reason = "panel_failure"
            break
        if (args.max_consecutive_failures > 0
                and consecutive_failures >= args.max_consecutive_failures):
            stopped_reason = "consecutive_failures"
            break
```
The `not_attempted` backfill and the `return finish_run(...)` stay unchanged.

- [ ] **Step 4: Run the tests and confirm they pass.** Run `python3 tests/test_ltx_mlx_render.py; echo rc=$?`. Expected: `OK n/n` with `rc=0`. Every kept v2 loop test (R13o-z8, R15, R16) still passes unchanged.

- [ ] **Step 5: Checkpoint (no commit).**

---

## Task 11: `bin/ltx-movie` end-to-end wiring (Phase 3 `--chain`, Phase 4 policy, `--frames 145`, help text)

**Files:** Modify `bin/ltx-movie` and `tests/test_ltx_movie_offline.py`.

**Depends on:** Tasks 5, 7 and 10.

- [ ] **Step 1: Write the failing tests** in `tests/test_ltx_movie_offline.py`.

1a. In `test_parser_defaults`, replace the line `check("L1 frames == 241", ...)` with:
```python
    check("L1 frames == 145", args.frames == 145, "got %r" % args.frames)
    helptext = " ".join(ltx_movie.build_parser().format_help().split())
    check("L1 --frames help states 6.04s per clip",
          "145 frames @ 24 fps = 6.04s per clip." in helptext, "got %r" % helptext)
    check("L1 --length help states 6.04s per panel at the defaults",
          "6.04s per panel at the defaults" in helptext)
    check("L1 --panels help describes chained clips",
          "number of chained clips; panel 1 also gets the movie's one still image; "
          "mutually exclusive with --length" in helptext)
    check("L1 the description names the chained render",
          "every clip after the first continues from the previous clip's last frame" in helptext)
```

1b. **Replace** `test_resolve_length_math` with:
```python
def test_resolve_length_math():
    def _resolve(argv):
        args = ltx_movie.build_parser().parse_args(argv)
        ltx_movie._resolve_length(args, argv)
        return args.panels

    check("L8a --length 60 -> 10 panels (round(9.931) at 145/24)",
          _resolve(["n", "--story-id", "x", "--length", "60"]) == 10,
          "got %r" % _resolve(["n", "--story-id", "x", "--length", "60"]))
    check("L8b --length 12 -> 2 panels (round(1.986))",
          _resolve(["n", "--story-id", "x", "--length", "12"]) == 2,
          "got %r" % _resolve(["n", "--story-id", "x", "--length", "12"]))
    check("L8c the divisor tracks --frames: --length 100 --frames 121 -> 20 panels",
          _resolve(["n", "--story-id", "x", "--length", "100", "--frames", "121"]) == 20,
          "got %r" % _resolve(["n", "--story-id", "x", "--length", "100",
                               "--frames", "121"]))
    check("L8d --length is a no-op when absent",
          _resolve(["n", "--story-id", "x"]) == 15)
```

1c. **Replace** `test_length_too_short` with:
```python
def test_length_too_short():
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "narrative", "--story-id", "x",
         "--length", "8", "--dry-run"],
        capture_output=True, text=True, cwd=WS)
    check("L10a --length 8 exits 2", result.returncode == 2,
          "rc=%r stderr=%r" % (result.returncode, result.stderr))
    check("L10b the message names 6.04s per panel", "6.04s per panel" in result.stderr,
          "stderr=%r" % result.stderr)
    check("L10c the message names the resolved panel count",
          "resolves to 1 panel" in result.stderr, "stderr=%r" % result.stderr)
    check("L10d the message tells the operator what to do",
          "Raise --length or pass --panels directly." in result.stderr,
          "stderr=%r" % result.stderr)
    check("L10e there is no upper --length bound any more",
          subprocess.run([sys.executable, _SCRIPT_PATH, "narrative", "--story-id", "x",
                          "--length", "900", "--dry-run"],
                         capture_output=True, text=True, cwd=WS).returncode == 0)
```

1d. **Replace** `test_length_100_panels_and_tokens` with:
```python
def test_length_100_panels_and_tokens():
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "narrative", "--story-id", "x",
         "--length", "100", "--dry-run"],
        capture_output=True, text=True, cwd=WS)
    check("L11a --length 100 exits 0", result.returncode == 0,
          "rc=%r stderr=%r" % (result.returncode, result.stderr))
    check("L11b story prompt requests EXACTLY 17 panels (round(16.55) at 145/24)",
          "EXACTLY 17" in result.stdout, "stdout=%r" % result.stdout[:2000])
    m = re.search(r"--max-tokens\s+(\d+)", result.stdout)
    check("L11c --max-tokens present", m is not None)
    if m:
        check("L11d --max-tokens is max(4096, 17*550) == 9350", int(m.group(1)) == 9350,
              "got %s" % m.group(1))
```

1e. In `test_no_stills_orthogonal_to_length`, replace the `L14b` line with (G2):
```python
    check("L14b --length 100 resolves to 17 panels", plain == 17, "got %r" % plain)
```

1f. In `test_no_stills_phase_sequencing_source`, replace the `L17c` check with (G1):
```python
    check("L17c phase 3 swaps --chain/--image for --no-images",
          '"--no-images"' in text
          and '"--chain", "--image", os.path.join(paths["images_dir"], "panel_01.png")' in text
          and '"--glob"' not in text)
```

1g. In `test_no_stills_dry_run_plan`, append after `L18h`:
```python
    check("L18m --no-stills keeps --on-panel-failure skip and never chains",
          "--on-panel-failure skip" in out and "--chain" not in out, "got %r" % out)
```

1h. In `test_default_dry_run_plan_unchanged`, append after `L18l`:
```python
    check("L18n default Phase 3 is --chain --image .../images/panel_01.png",
          "--chain --image " in out and "images/panel_01.png" in out and "--glob" not in out,
          "got %r" % out)
    check("L18o default Phase 4 stops on a failed panel",
          "--on-panel-failure stop" in out and "--on-panel-failure skip" not in out,
          "got %r" % out)
    check("L18p no video-backend flag anywhere", ("--video-" + "backend") not in out)
```

1i. **Replace** `test_dry_run_plan_targets_mlx_render` entirely with:
```python
def test_dry_run_plan_targets_mlx_render():
    result = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-mlx",
         "--panels", "3", "--dry-run"],
        capture_output=True, text=True, cwd=WS)
    out = result.stdout
    check("L24a exits 0", result.returncode == 0,
          "rc=%r stderr=%r" % (result.returncode, result.stderr))
    check("L24b Phase 3 and Phase 4 both name bin/ltx-mlx-render",
          out.count("ltx-mlx-render") == 2, "got %d" % out.count("ltx-mlx-render"))
    check("L24c bin/ltx-story-video is never named", "ltx-story-video" not in out,
          "got %r" % out)
    check("L24d Phase 3 pins the manifest allocator to a flat 145 frames",
          "--min-frames 145 --max-frames 145" in out, "got %r" % out)
    check("L24e --target-seconds is computed as panels*frames/fps",
          "--target-seconds 18.125" in out, "got %r" % out)

    def _val(line, flag):
        t = line.split()
        return t[t.index(flag) + 1] if flag in t else None

    render_lines = [l for l in out.splitlines() if "ltx-mlx-render" in l]
    check("L24f exactly two ltx-mlx-render commands appear (Phase 3 probe, Phase 4 render)",
          len(render_lines) == 2, "got %r" % render_lines)
    for line in render_lines:
        for flag, want in (("--frames", "145"), ("--width", "704"), ("--height", "448"),
                           ("--frame-rate", "24"), ("--tile-frames", "1"),
                           ("--tile-spatial", "1")):
            check("L24f %r has %s %s" % (line.split()[0:2], flag, want),
                  _val(line, flag) == want,
                  "got %r in %r" % (_val(line, flag), line))
    check("L24g --resume is always passed", out.count("--resume") == 2, "got %r" % out)
    check("L24h --no-low-ram is absent by default", "--no-low-ram" not in out, "got %r" % out)
    check("L24i Phase 4 carries the chained failure policy",
          "--on-panel-failure stop" in out and "--retry-failed 1" in out
          and "--retry-idle 120" in out and "--max-consecutive-failures 3" in out
          and "--panel-timeout 7200" in out, "got %r" % out)
    check("L24j Phase 2 renders panel 1 only, at twice the video size",
          "--only 1 --width 1408 --height 896" in out, "got %r" % out)
    check("L24n no video-backend token anywhere", ("--video-" + "backend") not in out)
    check("L24o Phase 3 builds a chained manifest from panel 1's still",
          re.search(r"--chain --image \S*images/panel_01\.png", out) is not None, "got %r" % out)

    forced = subprocess.run(
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-mlx2",
         "--panels", "3", "--no-low-ram", "--force", "--dry-run"],
        capture_output=True, text=True, cwd=WS)
    check("L24k --no-low-ram propagates to both phases",
          forced.stdout.count("--no-low-ram") == 2, "got %r" % forced.stdout)

    def _render_lines(stdout):
        return [l for l in stdout.splitlines() if "ltx-mlx-render" in l]

    fl = _render_lines(forced.stdout)
    check("L24l --force reaches BOTH the Phase 3 probe and the Phase 4 render",
          len(fl) == 2 and all("--force" in l.split() for l in fl), "got %r" % fl)
    pl = _render_lines(out)
    check("L24m neither render command carries --force when it was not given",
          len(pl) == 2 and not any("--force" in l.split() for l in pl), "got %r" % pl)
```

1j. Add a new function directly above the `# L40-L47` banner:
```python
def test_phase4_flags_policy_by_mode():
    def _flags(extra):
        args = ltx_movie.build_parser().parse_args(["n", "--story-id", "x"] + extra)
        args.video_width, args.video_height = 704, 448
        return ltx_movie._phase4_flags(args)

    stills, nostills = _flags([]), _flags(["--no-stills"])
    check("L51a stills (chained) mode passes --on-panel-failure stop",
          stills[stills.index("--on-panel-failure") + 1] == "stop", "got %r" % stills)
    check("L51b --no-stills passes --on-panel-failure skip",
          nostills[nostills.index("--on-panel-failure") + 1] == "skip", "got %r" % nostills)
    for label, flags in (("stills", stills), ("no-stills", nostills)):
        joined = " ".join(flags)
        check("L51c %s keeps one retry, a 120 s idle and the 3-failure breaker" % label,
              "--retry-failed 1 --retry-idle 120 --max-consecutive-failures 3" in joined,
              "got %r" % joined)
        check("L51d %s carries no video-backend flag" % label,
              ("--video-" + "backend") not in flags)
```
Insert `    test_phase4_flags_policy_by_mode()` in `__main__`, directly before `    test_main_block_completeness()`.

- [ ] **Step 2: Run the test and confirm it fails.** Run `python3 tests/test_ltx_movie_offline.py; echo rc=$?`. Expected: `FAIL L1 frames == 145`, `FAIL L8a…`, `FAIL L17c…`, `FAIL L24d…`, `FAIL L51a…`, and others, then `rc=1`.

- [ ] **Step 3: Write the implementation in `bin/ltx-movie`.**
- `build_parser`: replace the `description=(...)` value with:
```python
        description=(
            "End-to-end orchestrator for the narrative-to-movie pipeline: story authoring "
            "(bin/qwen-agent), panel 1's still (bin/ltx-story-images --only 1), manifest + "
            "render dry-run (bin/ltx-story-manifest --chain, bin/ltx-mlx-render --dry-run), "
            "and the chained render (bin/ltx-mlx-render), in which every clip after the first "
            "continues from the previous clip's last frame. The wrapped phase tools remain "
            "individually usable."
        ),
```
- Replace the `--panels` help with `help="number of chained clips; panel 1 also gets the movie's one still image; mutually exclusive with --length")`, keeping `type=int, default=15`.
- In the `--length` help, change `"10.04s per panel at the defaults."` to `"6.04s per panel at the defaults."`.
- Replace the `--frames` argument with:
```python
    parser.add_argument("--frames", type=int, default=145,
                         help="flat per-panel frame count; must satisfy (n-1)%%8==0 and "
                              "n>=9. 145 frames @ 24 fps = 6.04s per clip.")
```
- Module docstring: change `(10.04s at the defaults)` to `(6.04s at the defaults)`. In the `_resolve_length` docstring, change `10.0417s at the defaults` to `6.0417s at the defaults` (G17).
- `phase3_manifest`: replace `cmd_manifest += ["--glob", "panel_*.png", "--images-dir", paths["images_dir"]]` with:
```python
        cmd_manifest += ["--chain", "--image", os.path.join(paths["images_dir"], "panel_01.png")]
```
- `_print_dry_run_plan`: replace `phase3_manifest_cmd += ["--glob", "panel_*.png", "--images-dir", paths["images_dir"]]` with:
```python
        phase3_manifest_cmd += ["--chain", "--image",
                                os.path.join(paths["images_dir"], "panel_01.png")]
```
- Replace `_phase4_flags` with:
```python
def _phase4_flags(args):
    """Phase 4 = the shared render flags plus the failure policy. A chained (stills-mode)
    render must stop on a failed panel -- the next clip would have no frame to continue
    from -- so it passes --on-panel-failure stop and relies on bin/ltx-mlx-render's
    inline retry; --no-stills renders independent clips and keeps skip. Both keep one
    retry, a 120 s idle before it and the 3-consecutive circuit breaker (which the
    render tool does not consult for a chained manifest)."""
    flags = _render_flags(args) + [
        "--panel-timeout", str(args.panel_timeout),
        "--on-panel-failure", "skip" if args.no_stills else "stop",
        "--retry-failed", "1",
        "--retry-idle", "120",
        "--max-consecutive-failures", "3"]
    return flags
```

- [ ] **Step 4: Run the tests and confirm they pass.**
```bash
python3 tests/test_ltx_movie_offline.py; echo rc=$?
python3 -c "t=open('bin/ltx-movie').read(); print(t.count('_render_flags(args)'), t.count('os.path.join(WS, \"bin\", \"ltx-mlx-render\")'), t.count('os.path.join(WS, \"bin\", \"story-server\")'), t.count('\"--workspace\", WS,'))"
```
Expected: `OK n/n` with `rc=0`, and the counters print `4 4 2 2`.

- [ ] **Step 5: Checkpoint (no commit).**

---

## Task 12: Offline acceptance gates, deliberate breakages, design review

**Files:** None are created or modified, except a temporary edit to one file per breakage, reverted immediately. Results go in the hand-back.

**Depends on:** Tasks 1-11.

- [ ] **Step 1: §12.1 items 1-3.** The **main thread** runs these itself; counts reported by an implementer do not count.
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
for f in tests/test_ltx_movie_offline.py tests/test_ltx_mlx_render.py tests/test_ltx_story_images.py tests/test_ltx2_mlx_video_skill.py tests/test_ltx_image_fit.py tests/test_ltx_story_manifest_chain.py tests/check_ltx2_mlx_no_forbidden_imports.py; do
  python3 "$f" > /private/tmp/claude-502/gate_$(basename $f).txt 2>&1; rc=$?
  echo "$f rc=$rc $(tail -1 /private/tmp/claude-502/gate_$(basename $f).txt)"
done
python3 bin/ltx-mlx-render --help > /dev/null; echo help_rc=$?
python3 bin/ltx-movie "a test narrative" --story-id gate-dry --dry-run --no-review > /private/tmp/claude-502/gate_dry.txt; echo dry_rc=$?
/usr/bin/grep -c '[{}]' /private/tmp/claude-502/gate_dry.txt
```
Expected:
- Each of the six test files exits `rc=0` with a final line `OK n/n` in which both numbers are equal.
- `check_ltx2_mlx_no_forbidden_imports.py` exits `rc=0` with `RESULT: ok` (G11).
- `help_rc=0`, `dry_rc=0`, and the grep count is `0`.

- [ ] **Step 2: §12.1 items 5 and 6.**
```bash
/usr/bin/grep -rlI -E "comfyui_|cctech_|wan_video_skill|wan-generate|COMFY_MLX|video_backend|video-backend" bin *.py tests scripts --exclude-dir=__pycache__ | sort
```
Expected: exactly the three lines `tests/check_ltx_no_grad.py`, `tests/test_ltx_t2v_offline.py` and `tests/test_story_server.py`. Then re-run the Task 1 Step 2 `test -e` loop and expect no `STILL PRESENT` line.

- [ ] **Step 3: §11.7 deliberate breakages (item 4).** Handle each row separately:
  1. Back the file up: `cp <file> /private/tmp/claude-502/mut.orig`.
  2. Apply exactly the listed edit.
  3. Run the owning test file(s) directly and confirm the exit code is **1**.
  4. Restore it: `cp /private/tmp/claude-502/mut.orig <file>`.
  5. Confirm the restore with `cmp <file> /private/tmp/claude-502/mut.orig && echo restored`.

  Record each row's exit code in the hand-back.

| # | File | Edit (old -> new) | Must exit 1 |
|---|---|---|---|
| M1 | ltx_image_fit.py | `    s = min(width / src_w, height / src_h)` -> `    s = max(width / src_w, height / src_h)` | tests/test_ltx_image_fit.py |
| M2 | ltx_image_fit.py | `        out = ImageOps.exif_transpose(img).convert("RGB")` -> `        out = img.convert("RGB")` | tests/test_ltx_image_fit.py **and** tests/test_ltx_movie_offline.py (L26i) |
| M3 | ltx_image_fit.py | `GRID_PX = 64 ` -> `GRID_PX = 32 ` | tests/test_ltx_image_fit.py |
| M4 | ltx_image_fit.py | `PAD_TOLERANCE_PX = 8 ` -> `PAD_TOLERANCE_PX = 16 ` | tests/test_ltx_image_fit.py (the 4:3 row becomes 576x448) |
| M5 | ltx2_mlx_video_skill.py | `    if width % 64 != 0:` -> `    if width % 32 != 0:` and `    if height % 64 != 0:` -> `    if height % 32 != 0:` | tests/test_ltx2_mlx_video_skill.py (M3h) |
| M6 | bin/ltx-mlx-render | `    if manifest.get("schema_version", 1) >= 3:` -> `    if False:` | tests/test_ltx_mlx_render.py (R29a) |
| M7 | bin/ltx-mlx-render | `"select=eq(n\\,%d)" % (frames - 1)` -> `"select=eq(n\\,%d)" % (frames - 2)` | tests/test_ltx_mlx_render.py (R23k) |
| M8 | bin/ltx-mlx-render | delete the two-line `"chain_source_sha256": ...` entry in `build_clip_provenance` | tests/test_ltx_mlx_render.py (R25d) |
| M9 | bin/ltx-mlx-render | in `finish_run`, `    if (args.retry_failed and failed and stopped_reason is None\n            and not any(u.get("conditioning") == "chain" for u in units)):` -> `    if args.retry_failed and failed and stopped_reason is None:` | tests/test_ltx_mlx_render.py (R24l) |
| M10 | bin/ltx-movie | append `\n\n{image_rules}` immediately before the closing `"""` of `STORY_PROMPT_TEMPLATE` | tests/test_ltx_movie_offline.py (L5 raises KeyError) |

  Negative control: after all ten restores, re-run Step 1 and confirm every gate is green again.

- [ ] **Step 4: Design review (user CLAUDE.md §3), main thread only.** Dispatch `design-reviewer` on this diff: `git diff -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest ltx2_mlx_video_skill.py`, plus the new files `ltx_image_fit.py`, `tests/test_ltx_image_fit.py` and `tests/test_ltx_story_manifest_chain.py`. Give the reviewer:
  - the spec path;
  - this plan's "Spec gaps resolved" table;
  - a statement that nothing is in flight;
  - a statement that the pre-existing uncommitted hunks are out of scope.

  Require a disposition table: one row per finding, verified or refuted before acting on it. If the verdict is NEEDS-FIX, the reviewer authors the patch and the executor only applies it.

- [ ] **Step 5: Checkpoint (no commit).** Success: Steps 1-3 exactly as expected, and the design review is resolved.

---

## Task 13: Hardware gate (REQUIRED, spec §12.2; the work is not done without it)

**Files:**
- Create `generated/hw_gate_seeds/{portrait,wide3x1,square}.png` (gitignored test inputs).
- Four new `generated/stories/hwgate-*-<ts>/` run directories.
- Record results in this plan document's "Hardware gate results" table.

**Depends on:** Task 12. It runs on this host with the GPU, the story server and the user present. It is executed by the **main thread**, not a subagent.

- [ ] **Step 1: Create the seed fixtures (test inputs only; the pipeline itself never crops).**
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
python3 - <<'PY'
import os, sys
from PIL import Image
sys.path.insert(0, ".")
import ltx_image_fit as fit
src = Image.open("generated/stories/final_e2e_verify/images/panel_01.png").convert("RGB")
assert src.size == (1280, 704), src.size
os.makedirs("generated/hw_gate_seeds", exist_ok=True)
for name, box, want in (("portrait", (622, 0, 1018, 704), (320, 576, 7)),
                        ("wide3x1", (0, 150, 1280, 577), (960, 320, 1)),
                        ("square", (468, 0, 1172, 704), (512, 512, 0))):
    im = src.crop(box)
    im.save("generated/hw_gate_seeds/%s.png" % name, format="PNG")
    got = fit.derive_video_dims(*im.size)
    print(name, im.size, got, "OK" if got == want else "MISMATCH %r" % (want,))
PY
```
Expected: `portrait (396, 704) (320, 576, 7) OK`, `wide3x1 (1280, 427) (960, 320, 1) OK`, `square (704, 704) (512, 512, 0) OK`. Then **view each fixture** with the Read tool (`generated/hw_gate_seeds/portrait.png`, `wide3x1.png`, `square.png`) and confirm the elderly bearded man in the flat cap and olive waxed coat is visible in all three. If he is not visible in one, stop and report; do not invent a different crop.

- [ ] **Step 2: Before each of the four runs, check the prerequisites (all must hold).**
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
bin/story-server vision; echo vision_rc=$?          # idempotent; exits 0 while loading
until curl -sf http://127.0.0.1:8177/v1/models > /dev/null; do sleep 15; done; bin/story-server status
pgrep -fl 'ltx-2-mlx|ComfyUI|z_image|mlx_lm' || echo "no other GPU job"
sysctl -n vm.swapusage                              # "used = N.NNM" must be < 3072.00M
```
- The `until` loop ends once the port binds (this can take several minutes).
- If `pgrep` lists any GPU job, wait for it to finish; do not kill it.
- If swap used is ≥ 3.0 GB, wait; it drains at roughly 32 MB/min and `purge` does not help.
- If Phase 1 later exits 2 immediately without contacting port 8177, check for `~/.qwen-serve-guard/stand-down` (a known open bug). Report it to the user; do not delete it.

- [ ] **Step 3: Launch each run, one at a time, as a single background Bash invocation** (`run_in_background`, no `nohup`/`&` wrapper around the whole thing). Set LABEL/SEED for the run:
  - run 1: `LABEL=portrait SEED=generated/hw_gate_seeds/portrait.png`
  - run 2: `LABEL=wide SEED=generated/hw_gate_seeds/wide3x1.png`
  - run 3: `LABEL=square SEED=generated/hw_gate_seeds/square.png`
  - run 4: `LABEL=noseed SEED=`
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
LABEL=portrait; SEED=generated/hw_gate_seeds/portrait.png
TS=$(date +%Y%m%d%H%M%S); SID=hwgate-$LABEL-$TS
NARR="An old fisherman in a flat cap and a waxed coat stands at a lighthouse railing as a storm rolls in over the sea. He grips the rail and watches the waves, then turns and walks toward the lighthouse door."
mkdir -p generated/stories/$SID
echo "$SID" > generated/hw_gate_seeds/last_$LABEL.sid
if [ -n "$SEED" ]; then SEEDARGS=(--seed-image "$SEED"); else SEEDARGS=(); fi
python3 bin/ltx-movie "$NARR" --story-id "$SID" --panels 2 "${SEEDARGS[@]}" --no-review --story-server-stop-after-story > generated/stories/$SID/console.txt 2>&1 < /dev/null &
PID=$!
OUT=generated/stories/$SID/hw_gate.json
python3 - "$OUT" "$PID" <<'PY'
import glob, json, os, subprocess, sys, time, psutil
out, pid = sys.argv[1], int(sys.argv[2])
story_dir = os.path.dirname(out)
samples = []
while psutil.pid_exists(pid):
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    lvl = subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
                         capture_output=True, text=True).stdout.strip()
    samples.append({"t": time.time(), "avail_gib": vm.available / 2**30,
                    "swap_used_gib": sw.used / 2**30, "pressure": int(lvl or 0)})
    time.sleep(2)
runs = glob.glob(os.path.join(story_dir, "runs", "*"))
t4 = max(os.stat(r).st_birthtime for r in runs) if runs else samples[0]["t"]
p4 = [s for s in samples if s["t"] >= t4] or samples
json.dump({"phase4_start": t4,
           "phase4_min_avail_gib": min(s["avail_gib"] for s in p4),
           "phase4_peak_used_gib": 48.0 - min(s["avail_gib"] for s in p4),
           "phase4_max_pressure": max(s["pressure"] for s in p4),
           "phase4_swap_delta_gib": max(s["swap_used_gib"] for s in p4) - p4[0]["swap_used_gib"],
           "samples": samples}, open(out, "w"), indent=2)
PY
wait $PID; echo $? > generated/stories/$SID/gate_rc.txt
```
Completion signal: `generated/stories/<SID>/gate_rc.txt` exists. A log line or a "background task exited" notification is not a completion signal; stat the file. Never reuse a story-id. If a run fails, relaunch it with a new `<ts>`. (A resume under the same id would also need `--force`, because a partial `movie.mp4` exists; resume is not the gate procedure.)

- [ ] **Step 4: Check each run against the pass criteria.** Use `W H SW SH` = `320 576 320 576` (portrait), `960 320 960 320` (wide), `512 512 512 512` (square), `704 448 1408 896` (noseed).
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
LABEL=portrait; W=320; H=576; SW=320; SH=576
SID=$(cat generated/hw_gate_seeds/last_$LABEL.sid)
python3 - "$SID" "$W" "$H" "$SW" "$SH" <<'PY'
import glob, json, os, re, subprocess, sys
sid = sys.argv[1]
W, H, SW, SH = (int(x) for x in sys.argv[2:6])
d = os.path.join("generated", "stories", sid)
res = {}
rc = open(os.path.join(d, "gate_rc.txt")).read().strip()
sums = glob.glob(os.path.join(d, "runs", "*", "story_summary.json"))
s = json.load(open(max(sums, key=os.path.getmtime))) if sums else {}
res["c1_exit0_and_2_of_2"] = rc == "0" and s.get("completed_units") == s.get("requested_units") == 2

def probe(path, sel, entries, count=False):
    cmd = (["ffprobe", "-v", "error", "-select_streams", sel] + (["-count_frames"] if count else [])
           + ["-show_entries", "stream=" + entries, "-of", "json", path])
    p = subprocess.run(cmd, capture_output=True, text=True)
    return (json.loads(p.stdout or "{}").get("streams") or [{}])[0]

movie = os.path.join(d, "movie.mp4")
vid = probe(movie, "v:0", "width,height,codec_name,nb_read_frames", count=True)
aud = probe(movie, "a:0", "codec_name")
res["c2_movie_geometry_290_frames_h264_aac"] = ((vid.get("width"), vid.get("height")) == (W, H)
    and str(vid.get("nb_read_frames")) == "290" and vid.get("codec_name") == "h264"
    and aud.get("codec_name") == "aac")
still = probe(os.path.join(d, "images", "panel_01.png"), "v:0", "width,height")
res["c3_still_size"] = (still.get("width"), still.get("height")) == (SW, SH)

def md5(path, vf):
    # -map 0:v:0 is required: without it, framemd5 also emits a row per audio
    # frame for any clip with an AAC track (every real clip here does, per c2),
    # so len(rows) == 1 would spuriously fail and this function would always
    # return None for a real clip. Found and fixed during the Task 13 hardware
    # gate run (portrait): manually verified via ffprobe/framemd5 that the
    # chainseed PNG and frame 144 of the source clip already matched exactly
    # (md5 ac2833aa09711810c612e6b20955113e) -- this was a gate-script bug, not
    # a pipeline defect.
    p = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-map", "0:v:0", "-vf", vf,
                        "-fps_mode", "passthrough", "-f", "framemd5", "-"], capture_output=True, text=True)
    rows = [l for l in p.stdout.splitlines() if l.strip() and not l.startswith("#")]
    return rows[0].split(",")[-1].strip() if p.returncode == 0 and len(rows) == 1 else None

seed_md5 = md5(os.path.join(d, "clips", "panel_02.chainseed.png"), "format=rgb24")
last_md5 = md5(os.path.join(d, "clips", "panel_01.mp4"), "select=eq(n\\,144),format=rgb24")
res["c4_chain_exactness"] = seed_md5 is not None and seed_md5 == last_md5
g = json.load(open(os.path.join(d, "hw_gate.json")))
res["c5_pressure_and_swap"] = g["phase4_max_pressure"] < 4 and g["phase4_swap_delta_gib"] <= 1.0
console = open(os.path.join(d, "console.txt"), errors="replace").read()
m = re.search(r"residual pad (\d+) px", console)
res["record"] = {"pad_px": int(m.group(1)) if m else 0,
                 "movie": vid, "still": still,
                 "peak_used_gib": round(g["phase4_peak_used_gib"], 2),
                 "max_pressure": g["phase4_max_pressure"],
                 "swap_delta_gib": round(g["phase4_swap_delta_gib"], 3),
                 "unit_seconds": [u.get("seconds") for u in s.get("units", [])]}
print(json.dumps(res, indent=2))
print("GATE", sid, "PASS" if all(ok for k, ok in res.items() if k.startswith("c")) else "FAIL")
PY
```
Expected: `GATE <SID> PASS` for all four runs. Any `FAIL` blocks completion. For a failure, first read `console.txt`, the newest `runs/*/story_summary.json`, `runs/*/panel_*.log` and `hw_gate.json`. Diagnose from what they show; do not re-run blind, and do not call it an OOM without evidence.

- [ ] **Step 5: Record the results in this document** (fill in the table):

**Hardware gate results (fill in):**

| Run | story-id | Derived W×H | pad_px | panel_01.png | s/panel (u1, u2) | peak used GiB | max pressure | swap Δ GiB | c1 | c2 | c3 | c4 | c5 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| portrait | hwgate-portrait-20260924194605 | 320x576 | 7 | 320x576 | 59.2, 58.0 | 32.5 | 1 | 0.002 | ✅ | ✅ | ✅ | ✅ | ✅ |
| wide 3:1 | hwgate-wide-20260924200339 | 960x320 | 1 | 960x320 | 92.6, 94.4 | 36.61 | 1 | 0.003 | ✅ | ✅ | ✅ | ✅ | ✅ |
| square | hwgate-square-20260924223703 | 512x512 | 0 | 512x512 | 78.0, 76.7 | 33.84 | 1 | 0.0 | ✅ | ✅ | ✅ | ✅ | ✅ |
| no seed | hwgate-noseed-20260924224926 | 704x448 | 0 | 1408x896 | 93.4, 92.2 | 30.18 | 1 | 0.0 | ✅ | ✅ | ✅ | ✅ | ✅ |

Notes:
- Model used for all four runs: `/Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8` (not the default `ltx-2.3-10eros-v1.2-dmd-mlx-q8`), per user decision after Task 12's design review found the default model absent from this host's HF cache (finding F1). Pass criteria c1-c5 are all model-agnostic (frame counts, geometry, chain exactness, memory), so they hold as designed.
- `c4_chain_exactness`'s check script had a bug (missing `-map 0:v:0` on the source-clip ffmpeg invocation), which produced a false FAIL on the portrait run's first check — fixed in this document's own Step 4 script (see the `md5()` helper above) after manually verifying byte-exact md5 equality with the correct invocation. All four runs shown above use the corrected script.
- Run 2 (wide) failed on its first attempt (SID `hwgate-wide-20260924195356`, not listed above) with a story-server connection-refused error — `--story-server-stop-after-story` stops the vision server after every run's Phase 1, so it must be restarted before each of the four runs, not just once at the start. Relaunched with a fresh story-id per the brief's own instructions; not reused.

- [ ] **Step 6: Human sign-off (required).** Give the user the four `generated/stories/<SID>/movie.mp4` paths and ask them to confirm, for each movie:
  1. the subject is not cropped relative to the seed;
  2. no black bar is visible beyond the computed residual pad (portrait 7 px, wide 1 px, square 0 px, no-seed 0 px);
  3. panel 2 continues from panel 1 without a scene change.

  Record their answer verbatim under the table. The work is complete only when all four runs PASS and the user signs off.

---

## Task 14: Hand-back and commit decision (user)

- [ ] **Step 1:** Report the following:
  - the Baseline table;
  - every gate's exit code and `OK n/n` line, taken from the main thread's own runs;
  - the M1-M10 exit codes;
  - the design-review disposition table;
  - the Hardware gate table and the user's sign-off;
  - the "Spec gaps resolved" G1-G17 list.
- [ ] **Step 2:** Ask the user how to commit. Most modified files carry pre-existing uncommitted hunks the spec forbids re-staging (G8), so the options are:
  - (a) commit only the new files plus the Task 1 deletions;
  - (b) commit-split each mixed file (stage a reconstructed clean copy, then restore the working-tree copy);
  - (c) leave everything uncommitted.

  Do nothing until the user chooses. Pushing is gated by the design-review hook and needs `push -u` for this branch.

---

## Self-Review

**1. Spec coverage checklist**

| Spec § | Requirement | Task |
|---|---|---|
| §2.1 P1 | `ltx-mlx-render` import fixed | 8 (Step 4 `--help`) |
| §2.1 P2 | `{image_rules}` KeyError | 4 (L5, dry-run brace check); M10 |
| §2.1 P3 | cctech import in `model_identity` | 8 |
| §3 D1 / §10 | deletions | 1, 12 Step 2 |
| §3 D2, §5.1-5.2 | no-crop module, constants, golden table | 2 |
| §3 D3, §5.3 | derived dims; flags removed; 64-multiple main checks | 5 |
| §3 D5, §5.5 | Phase 2 argv (`--only 1`, W×H or 2W×2H) | 5 |
| §3 D6, §5.3 | `--frames 145`, help texts, description | 11 |
| §3 D7 / §6.2 | panel-1 three fields, later panels Motion only | 4 |
| §3 D8 / §6.4 | no-stills `{seconds}` only | 4 (L15) |
| §3 D9 | chain-frame content screen | 10 (R28e-g) |
| §3 D10 / §6.5 | old story.md Image: warns, never fails | 4 (L7d/e), 7 (C4) |
| §3 D14 | out-of-range exits 2 before Phase 1, and in dry-run | 5 (L26h, L27k, L50) |
| §3 D15 / §12.2 | hardware gate | 13 |
| §3 D16 | Style machinery dropped | 4 (L7j, deletions) |
| §5.4 | `_seed_geometry`, `_prepare_seed_image`, `phase0_seed` messages | 5 |
| §5.6 | `bin/ltx-story-images` fit and help | 6 |
| §5.7 | `validate_geometry` 64; `_render_flags` loses the backend pair; v3 still-aspect preflight | 3, 4, 10 |
| §5.8 | dry-run geometry, Pillow placeholder, Phase 0 text | 5 |
| §6.1 | `build_story_prompt(seconds=)`, `_clip_seconds` | 4 |
| §6.3 | preface and postface wholesale | 4 |
| §6.5 | validator rules, orphans, warning loop | 4 |
| §7.1-7.3 | manifest v3, `--chain` errors and warning, Phase 3 argv | 7, 11 |
| §7.4 | `load_manifest` v3 and v2 derivation | 8 |
| §8.1 | units `conditioning`/`chain_source`/chainseed path | 8 |
| §8.2 | extract, check, prepare | 9 |
| §8.3 | provenance v2 | 8 |
| §8.4 | skip guard, chain branch, inline retry, `finish_run` changes | 10 |
| §8.5 | dry-run chain lines, in-order prediction | 10 |
| §8.7 | Phase 4 policy | 11 |
| §9 | backend removal inside kept files | 4, 8 |
| §11 | baseline, gate rule, kept-test rule, per-file test lists | 0, 2-11 |
| §11.7 | ten breakages | 12 Step 3 |
| §12.1 | offline gates 1-6 | 12 |
| §12.3 | success metrics | covered by 2 (crop layers 0), 7/10 (conditioning), 4 (fields), 12 (runnable), 1 (backends) |

**2. Placeholder scan.** Every code block holds complete code. No "TBD", "similar to Task N" or "add error handling" wording remains. Each error path shows its exact message. The two "fill in" tables are data-recording slots required by the spec, not code placeholders.

**3. Type and signature consistency across tasks**

| Symbol | Defined | Used by | Consistent |
|---|---|---|---|
| `derive_video_dims(src_w, src_h) -> (W, H, pad)` | T2 | T5 `_seed_geometry`, T13 Step 1 | yes |
| `fit_letterbox(img, width, height)` | T2 | T5 `_prepare_seed_image`, T6 `_write_seed_panel` | yes |
| `load_oriented_rgb(path)` | T2 | T5 (twice, G6), T6 | yes |
| `build_story_prompt(..., *, seconds)` | T4 | `phase1_story`, `_print_dry_run_plan`, tests L5/L15/L25/L34 | yes |
| `_validate_story_md(path, n, no_stills=False)` | T4 | `phase1_story`, L7, L16 | yes |
| `_prepare_seed_image(seed, out) -> (violations, geometry)` | T5 | `phase0_seed`, L26 | yes |
| `_seed_geometry(seed) -> (violations, geometry, img)` | T5 | `_prepare_seed_image`, `_print_dry_run_plan` | yes |
| `_still_size(args) -> (w, h)` | T5 | `phase2_stills`, `_print_dry_run_plan` | yes |
| panel `conditioning` key | T7 (writer), T8 (`load_manifest`) | T8 `build_units`, T10 loop and preflight | yes |
| unit keys `conditioning`, `chain_source` | T8 | T8 provenance, T9 `prepare_chain_seed`, T10 loop, dry-run, `finish_run` (`.get`) | yes |
| `ffprobe_image_size(path) -> ((w, h), None) \| (None, str)` | T9 | T9 `check_chain_seed`, T10 preflight; test stubs return the same shape | yes |
| `check_chain_seed(png, w, h, source_panel)` | T9 (G4) | `prepare_chain_seed` passes `unit["index"] - 1`; R26 and R27 use 4 args | yes |
| `extract_last_frame(clip, out_png, frames)` | T9 | `prepare_chain_seed`; R23/R27 stubs have 3 args | yes |
| `prepare_chain_seed(unit, args)` | T9 | T10 loop; `_drive_chain` stub `(unit, args)` | yes |

**4. Review Focus checklist**
- [ ] RF1 aspect bound: Task 2 F2a-e; Task 5 L26h, L27k, L50a-d; mutation none needed (F2 exact message).
- [ ] RF2 corrupt/black last frame: Task 9 R23e-h, R26b/c/f, R27a/b; Task 10 R28a-d; mutation M7 (wrong index caught by R23k).
- [ ] RF3 resume after a mid-chain failure: Task 8 R18 chain keys; Task 10 R25a-d, R24g (relaunch hint); mutation M8; Task 13 Step 3 `--force` note.
- [ ] RF4 EXIF-rotated photo: Task 2 F7a-d; Task 5 L26i; mutation M2 (caught in both files).
- [ ] RF5 single-panel movie: Task 7 C5; Task 10 R32a/b.

---

## Execution Handoff

**Plan complete. Save it to `docs/superpowers/plans/2026-09-24-ltx-movie-narrative-chain-redesign.md`. Two execution options:**

**1. Subagent-Driven (recommended).** A fresh `code-executor` subagent is dispatched for each task, strictly in order with no parallel dispatch. There is a mechanical spec-compliance diff plus review between tasks. Tasks 12 Step 4 and 13 run in the main thread.

**2. Native (Inline) Execution.** Execute the tasks in this session with superpowers:executing-plans, in batches with checkpoints.

**Which approach?**

**Recommendation: Subagent-Driven, sequential.** Tasks 4, 5 and 11 edit the same two big test files in sequence, and every task carries exact strings and pinned source counters where drift ships silently. Mistakes surface only after GPU hours in a hardware gate that only the main thread can run, and each test wastes a real render and a user sign-off. A fresh executor per task with a verify-before-next review is the cheapest insurance.
