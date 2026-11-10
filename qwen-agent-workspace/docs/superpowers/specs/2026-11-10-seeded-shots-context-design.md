# Seeded shots context: each seeded shots still also sees the previous moment of the scene (a test option)

Date: 2026-11-10

Status: design spec and implementation plan in one document. **The user's goal:** "the closest to seamless we can get" while keeping the shots-mode stills quality, same-scene cuts first. Today, in seeded shots mode (`--shots --seed-image`), every panel's still is an independent Qwen edit of the seed, so each panel redraws the place and the background from the seed alone and a scene's shots do not cohere. This spec adds the opt-in `--seed-context {still,frame}`: each panel after the first becomes a TWO-image Qwen edit, the seed (the people) plus the previous moment of the scene (the previous panel's still, or the exact last frame of the previous panel's clip). It is a TEST OPTION: absent, the behaviour is byte-identical. Choices this spec makes beyond the controller's decisions are marked **[spec choice]**. The implementer makes no design decisions.

Repository `/Users/reubenpatterson/local_agent_harness` (never touched by this plan). Worktree `$S/sc-wt`, branch `seed-context`, off `29e3a89` (the merge of PR #15, shots-multiref). `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`. `WS` is `qwen-agent-workspace/`. Every path is relative to `WS`, and every line number cites `29e3a89`. At `29e3a89` every `PIPELINE_FILES` member is byte-identical to `c537fedcab9fbdfce3181063aa9b8b0f6eff9b5f`, the current `test_mut26` BASELINE (`tests/test_movie_ui_builder.py:293`), and the tree of `29e3a89` equals that of `31cc82e` (both checked with `git diff --quiet`).

Builds on **[SE]** `docs/superpowers/specs/2026-11-05-compose-shots-seed-edit-design.md`, **[CR]** `2026-11-09-shots-multi-reference-stills-design.md`, **[QE]** `2026-11-03-qwen-edit-models-design.md`, **[SI]** `2026-11-07-seeded-no-identity-sentence-design.md`, **[SHOTS]** `2026-10-06-shots-mode-design.md` and **[CE]** `2026-10-30-chained-end-frames-design.md`. Every requirement of those specs stays in force except where Section 10 names it as amended.

Requirement IDs are **CX1-CX21**, tests **CXT1-CXT20**, KPIs **CXK1-CXK12**, live checks **L1-L6**. At `29e3a89`, `git grep -nE "\bCX[0-9]+\b|\bCXT[0-9]+\b|\bCXK[0-9]+\b"` finds nothing.

Terms: a **context picture** is the second reference image of a panel's edit: the previous panel's fitted still (`still` mode) or the exact last frame of the previous panel's clip (`frame` mode). A panel's **kind** is `none` (a single-image edit of the seed, exactly as seeded shots prompts it today) or the mode (`still` or `frame`, a two-image edit). A **location change** is a panel after panel 1 whose setting sentence differs from the previous panel's (CX4). A panel's **cascade** is the run of later panels whose context picture comes, directly or through each other, from its still (CX7).

The plan is split so that the controller can ship still mode alone: **Task 1** (still mode, one commit) is complete and gated by itself; **Task 2** (frame mode, one commit) builds on it; the whole-branch review's fix is one more code commit after Task 2 (Amendment A1, Section 13); **Task 3** is the `test_mut26` re-baseline (a test-only commit after the last code commit). Shipping still mode only = Task 1, then Task 3.

---

## 0. Scope

### 0.1 What happens today (verified at `29e3a89`)

- `phase2_stills` (`bin/ltx-movie:2254-2296`) sends a seeded shots run to `_phase2_shots_seed` (`:2257-2258`, `:2617-2727`): `_shots_seed_plan` (`:2570-2603`) builds every panel's prompt as `SHOTS_SEED_EDIT_PREFIX` (`:152-156`, "... Change their pose and action, the place, the background, the lighting, the framing and the camera angle ...") plus its `Image:` and `Style:` text; ONE `qwen_edit.run_jobs` batch edits the oriented seed (`seed-original.png`) into every panel at the video size floored to the model's multiple (`_seed_edit_size`, `:2432-2434`), and each output is fitted into `images/panel_NN.png` at 2W x 2H (`_still_size`, `:2245-2251`), screened and recorded in `seed_edits.json` (schema `ltx-movie.seed-edits.v1`). Reuse is per panel by key equality plus the still's sha256 (SE13).
- Nothing in the seed edit sees another panel: the place is re-imagined from the seed in every shot.
- PR #15 added what this spec needs: a `run_jobs` job may carry `"sources"` (several reference images, the first being its `"source"`; [CR] CR3), `qwen_edit.multi_reference_problem` refuses `qwen2511-q4` ([CR] CR1), `qwen_edit.jobs_timeout` counts a multi-reference job as 6 jobs ([CR] CR2), and `_shots_seed_entries` / `_write_shots_seed_record` take a `schema` ([CR] CR9).
- Phase 3 builds a `--shots` manifest from every `images/panel_NN.png` (`phase3_manifest`, `:3007-3058`); Phase 4 runs `bin/ltx-mlx-render` once with `--resume` (`phase4_render`, `:3146-3168`; `_phase4_flags` passes `--on-panel-failure skip` for `--shots`, `:663-677`). A clip is reused when its provenance matches, including its still's `image_sha256` (`bin/ltx-mlx-render:558-591`, `:1400-1410`).

### 0.2 The controller's decisions (binding; then what this spec adds)

1. Opt-in `--seed-context {still,frame}`, only with `--shots --seed-image` and a multi-reference-capable `--seed-edit-model`; absent = byte-identical.
2. Panel N >= 2 is a two-image edit with `sources=[seed (Picture 1, identity), context (Picture 2, scene)]`; panel 1 stays the single-image seed edit.
3. A new `SHOTS_SEED_CONTEXT_PREFIX`-style prompt naming Picture 1 the people and Picture 2 the previous moment of the scene (keep place, background, props, time of day, lighting, colour palette and who stands on which side; take nothing else, not faces, clothing, blur or grain), change pose/action/framing/camera angle, then the panel's `Image:`/`Style:` text; no "change the place" wording for context panels.
4. `still`: the context is the fitted still of panel N-1; serial Phase 2, one `run_jobs` call per panel; reuse the seed-edit plan/entries/record helpers with a new schema and record `seed_context_edits.json` (`ltx-movie.seed-context-edits.v1`); entries add `context {kind, file, sha256}`; a changed panel j invalidates the later panels that see it; `--redo N` cascades and prints a note.
5. `frame`: the context is the exact last frame of clip N-1; an interleaved loop (still k, clip k, last frame k, still k+1); the full manifest is built once with the fitted seed as the placeholder for stills not yet made; for each k a `manifest_upto.json` of panels 1..k and `bin/ltx-mlx-render --resume`; the last frame comes from `bin/ltx-mlx-render`'s `extract_last_frame` and `check_chain_seed`, loaded by path; a final full render reuses every clip. A failed or blocked still or clip stops the run.
6. Location change: when a panel's setting sentence differs from the previous panel's (deterministic, no model call), that panel is a single-image seed edit (context kind `none`) with the ordinary `SHOTS_SEED_EDIT_PREFIX`.
7. Seed first, context second; `--seed-context-order` only if tiny.
8. Models: `qwen21-q4`/`q8`/`bf16` and `qwen2511-bf16`; `qwen2511-q4` refused; `as-is` refused.
9. Refusals (exit 2, one `Error:` line each): without `--shots`, `--seed-image` or `--seed-edit-model`; with `--cast-refs-model`; `--no-stills`; `as-is`; `qwen2511-q4`; frame mode with a non-stop failure policy.
10. Output size as today's seeded shots (edit at the video size, fit into 2W x 2H stills); CLI only; timeout `jobs_timeout`; pinned-file re-baseline in a final test-only commit; never amend.

**What this spec adds** (each justified in Section 1): the setting-sentence rule (CX4), the forced cascade and the cascade entry clearing (CX7), `--seed-context-order` (CX1, Decision 2), the prompt's exact wording including "leave out anyone the new shot does not describe" (CX3), one child log per panel (CX8), the frame mode's placement as Phase 2 with Phases 3 and 4 kept (CX15), its up-front `movie.mp4` guard, its review gate, its per-render memory gate and its frame extraction only when the next panel needs it (CX16-CX19), the `_phase3_manifest_cmd` and `_render_tool` refactors (CX16, CX15), and the live-check arms and report script (Section 7).

### 0.3 Feasibility (verified or inferred)

| Item | Evidence | Status |
|---|---|---|
| Two-image edits on `qwen21-*` and `qwen2511-bf16` | [CR] Section 0.3: mflux `QwenImage21Edit` takes `image_paths` (up to 10); diffusers `QwenImageEditPlusPipeline` takes `image=[...]`; PR #15 wired both children (`seed_edit_mflux_child.py:92-93`, `character_dataset.py` `child_qwenedit`) | verified (source read and PR #15 tests); behaviour on these prompts inferred |
| `qwen2511-q4` | silently uses image 1 only ([CR] Section 0.3) | refused via `qe.multi_reference_problem` |
| A partial manifest (panels 1..k of N) | `load_manifest` (`bin/ltx-mlx-render:176-304`) checks only contiguous indices from 1, the image paths, `conditioning` and per-panel fields; it never reads `total_num_frames` or `target_seconds`. `finish_run` (`:1070-1191`) derives `requested_units`, `intended_total_frames` and `actual_total_frames` from `len(units)` and `completed` (`:1166-1169`). `estimate_seconds_per_panel` (`:819-867`) ignores resumed units | **verified** by reading, and proven by CXT17, which drives the real `main()` on the partial manifests (summaries `requested_units` 1, 2, 3; `intended_total_frames` 145, 290, 435) |
| Clip reuse across the partial runs and the final run | provenance (`build_clip_provenance`, `:558-591`) keys on model, gemma, LoRAs, prompt sha256, conditioning, the still's sha256, seed (`--seed` + index), size and frames; none depends on the manifest's length or on `--on-panel-failure`; the clips dir comes from the manifest's `story_id` (`:1298-1300`) | **verified** by CXT17 (the final full render and a rerun generate nothing) |
| The Qwen child is gone before each clip renders | `qwen_edit.run_child` waits for the child (`proc.wait()`, `qwen_edit.py:339`) before `run_jobs` returns; the render is started after it | verified (source); ordering pinned by CXT13 |
| The investigator's "temp work dir" | not needed: the partial renders write their summaries under `<story>/runs/` like any run, `_report_summary` reads the newest one (Phase 4's), and every intermediate file lives in `<story>/seed_context_edits/` | design consequence |

### 0.4 Grounding (verified at `29e3a89`)

**`bin/ltx-movie` (pinned).**
- Top-level imports: `argparse`, `glob`, `importlib.machinery`, `json`, `os`, `shlex`, `subprocess`, `sys`, `threading`, `time`, `pipeline_log` (`:125-138`). **No top-level `import re`:** `tests/test_ltx_movie_offline.py:432-434` (check L7j) asserts `"\nimport re\n" not in text` and that none of `_style_echo_warnings`, `_style_content_warnings`, `_content_words`, `_ECHO_`, `_STYLE_BANNED_TOKENS`, `require_style` occurs. This spec needs no regex in `bin/ltx-movie`: the sentence split and the setting-sentence pattern are `character_lib`'s (CX4).
- Module docstring: the Seed edit paragraph `:113-116`, the Cast references paragraph `:118-122` (last). CRT17 (`tests/test_ltx_movie_cast_refs.py:595`) pins that the docstring ENDS with the Cast references paragraph, and SE5 (`tests/test_ltx_movie_shots_seed.py:331`) pins the text "... reused on a rerun when nothing changed. Story engine": the new paragraph goes between Seed edit and Cast references.
- Constants: `SHOTS_SEED_*` `:150-158`, `CAST_REFS_*` `:162-185`. Parser: `--cast-refs-model` `:470-477`, `--cast-refs-lora` `:478-481`, `--story-model` `:482`.
- `_qwen_edit` `:902-905`; `_resolve_seed_edit` `:1057-1096`; `_resolve_cast_refs` `:1127-1187` (refuses `--cast-refs-model` with `--seed-image` at `:1142-1145`); `_resolve_shots` `:1396-1452` (`--shots --no-stills` refused at `:1405-1408`; `--shots --seed-image` without a registry `--seed-edit-model` refused at `:1415-1418`).
- `_still_size` `:2245`; `phase2_stills` `:2254` (seeded shots dispatch `:2257-2258`); `_seed_edit_size` `:2432`; `_write_seed_edit_record` `:2437`; `_sha256_file` `:2523`; `_shots_seed_entries` `:2547`; `_write_shots_seed_record` `:2562`; `_shots_seed_lora_note` `:2606`; `_phase2_shots_seed` `:2617-2727`; `_cast_refs_paths` `:2730`; `phase_redo_shots` `:2969-2992`; `_shots_image_flags` `:2998`; `phase3_manifest` `:3007-3058`; `# phase 4: render` `:3061`; `_wait_for_avail` `:3080`; `_stream_and_tee` `:3104-3114` (opens its log with `"w"`); `phase4_render` `:3146-3168` (render command `:3159-3160`); `_print_shots_seed_plan` `:3269`; `_print_cast_refs_plan` `:3296`; `_print_dry_run_plan` `:3327` (seeded shots Phase 2 branch `:3424-3427`); `_phase_sequence` `:3509-3530`; `main` `:3533` (`_resolve_cast_refs` call `:3609-3611`).
- **Source-literal pins that constrain the frame mode** (no existing test may be edited): `os.path.join(WS, "bin", "ltx-mlx-render")` occurs exactly 4 times (L17f `tests/test_ltx_movie_offline.py:726-729`, L46f `:1591-1593`, RST50 `tests/test_story_engine.py:2428`); `_render_flags(args)` exactly 4 times (L17d `:721-723`, L46e `:1588-1590`, RST50); and no `no_stills` between `def phase2_stills(args):` and `def phase3_manifest` (L17b `:713-716`). Hence `_render_tool()` takes phase4_render's literal (CX15) and `_phase3_manifest_cmd` is defined after `phase3_manifest` (CX16).

**`character_lib.py` (pinned, untouched).** `_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")` `:126`; `_SETTING_SENTENCE_RE = re.compile(r"""["“]?the\s+setting\s+is\b""", re.IGNORECASE)` `:172`; the S12 check (`:1329-1333`) requires every shots `Image:` to hold a setting sentence. `story_engine.pasted_pieces` (`:2257-2280`) pastes the beat location's setting sentence first in every shots `Image:`.

**`bin/ltx-mlx-render` (pinned, untouched).** `extract_last_frame(clip_path, out_png, frames)` `:647-670` (frame index `frames - 1`, written through a `.tmp.png`, returns `[]` or one violation); `check_chain_seed(png_path, width, height, source_panel)` `:673-700` (size and luma checks); `main` `:1194-1488`.

**`qwen_edit.py` (unpinned, untouched).** `jobs_timeout` `:429-433`; `run_jobs` `:477-592`; `run_child` appends its log (`open(log_path, "a")`, `:331`).

**Tests.** `tests/test_movie_ui_builder.py`: `NEW_PY` `:213-221`, `PIPELINE_FILES` `:223-228`, `test_mut26` `:272-302` (comment chain ends `:291`, BASELINE `:293`). `tests/test_qwen_edit.py` QET11 pins the exact tail of `NEW_PY`, so CX21 leaves `NEW_PY` alone ([CR] CR15 precedent). `tests/test_ltx_movie_shots_seed.py` provides `_FakeShotsQwenEdit`, `PANEL_QWENEDIT_STUB`, `_story_md`, `_write_story`, `_seed1920`, reused by the new tests unchanged.

### 0.5 Deliverables

| # | File | Pinned | Task | Change |
|---|---|---|---|---|
| D1 | `bin/ltx-movie` | **yes** | 1 | flags, resolver, constants, plan, reuse, per-panel edit, still-mode Phase 2, dry run, docstring (CX1-CX13; edits M1-M9) |
| D2 | `tests/test_ltx_movie_seed_context.py` | — | 1 (2 edits it) | new, CXT1-CXT11 |
| D3 | `bin/ltx-movie` | **yes** | 2 | frame mode, `_render_tool`, `_phase3_manifest_cmd`, the phase tuple, dry-run lines (CX14-CX20; edits F1-F10); the A1 fix commit then deletes `_seed_context_frame_flags` (Section 13) |
| D4 | `tests/test_ltx_movie_seed_context_frame.py` | — | 2 | new, CXT12-CXT19; the A1 fix commit edits CXT12, CXT13, CXT17 and CXT18 and adds CXT20 (Section 13) |
| D5 | `tests/test_movie_ui_builder.py` | — | 3 | only `test_mut26`'s BASELINE and comment chain (CX21) |

Untouched: `qwen_edit.py`, `seed_edit_mflux_child.py`, `character_dataset.py`, `character_lib.py`, `story_engine.py`, `bin/ltx-story-images`, `bin/ltx-story-manifest`, `bin/ltx-mlx-render`, `content_safety.py`, `movie_ui_*.py`, `static/movie-ui/*`, every other test. **PR #15's code is not changed:** no PR #15 line is edited; M1, M2, M3, M6, M7 and M9 only anchor on PR #15 text (the Cast references docstring word, `CAST_REFS_LORA_NOTE`, the `--cast-refs-lora` help, `def _cast_refs_paths`, `def _print_cast_refs_plan`, the `_resolve_cast_refs` call) and insert next to it. Existing non-PR #15 code that changes: `phase2_stills` (2 lines added), `_print_dry_run_plan` (the seeded-shots Phase 2 call becomes an if/else), `main` (one resolver call), and in Task 2 `phase3_manifest` (its command building moves into `_phase3_manifest_cmd`, unchanged behaviour), `phase4_render` (its render path comes from `_render_tool()`, same argv) and `_phase_sequence` (3 lines).

### 0.6 Out of scope

- Unseeded shots, chained mode, `--no-stills` (refused by existing rules).
- Any left/right/side reading in code: "who stands on which side of the frame" is fixed prompt wording only.
- Combining with `--cast-refs-model` (refused), `qwen2511-q4` multi-image (refused; [CR] follow-up F1).
- A movie-ui control (CLI only; follow-up F1).
- Context for a location change (a revisited place gets no picture of its earlier shots; follow-up F3).
- Changing `qwen_edit.py`, the children, `bin/ltx-mlx-render`, the timeout rule or the default seeded shots path.
- Running a real model, server, render or download in tests; any agent access to macstudio.

### 0.7 Success criteria (KPIs)

| ID | Criterion | Verified by |
|---|---|---|
| CXK1 | The full suite has no failure beyond the baseline recorded at `29e3a89`. Final run (Tasks 1, 2, the A1 fix commit and Task 3) `2 failed, P0+20 passed, 2 skipped` (P0 = the baseline PASSED count, expected 2698); still mode only (Tasks 1 and 3) `2 failed, P0+11 passed, 2 skipped` | gate, V1 |
| CXK2 | Between `29e3a89` and the final commit the only pinned file changed is `bin/ltx-movie`: numstat `381 1` after Task 1, `200 30` for Task 2 alone, `6 12` for the A1 fix commit alone, `569 25` overall; the only other non-docs files are the two new test files and `test_mut26`'s two lines | V1 |
| CXK3 | Without `--seed-context` nothing changes: `phase2_stills` calls `_phase2_shots_seed(args)`, no `seed_context_edits*` file appears, the phase tuples are unchanged, Phase 3's and Phase 4's commands are unchanged, and no existing test is edited except `test_mut26`'s BASELINE | CXT7, CXT12, the unchanged suites |
| CXK4 | Still mode: one `run_jobs` call (one child) per edited panel, in panel order; each context panel's job has `sources` [seed, previous panel's still] (swapped with `context-first`), and that still is the one written in this run | CXT3, CXT4, CXT10, CXT11 |
| CXK5 | Frame mode: for every panel k the order is edit k (child exited), memory gate, render on panels 1..k, last frame of clip k (when panel k+1 needs it), then edit k+1 with that frame as its context | CXT13 |
| CXK6 | Every blocked or failed still, failed clip (after its one retry, A1), bad frame, unloadable tool or failed manifest stops the run with one `Error:` line and exit 1 (2 for an existing `movie.mp4`); no exception other than KeyboardInterrupt/SystemExit escapes as a traceback | CXT6, CXT14, CXT15 |
| CXK7 | L2 (B1, `qwen21-q4`): judge-stills `visual_continuity` at least A0's + 2 | L2, report |
| CXK8 | L2: the manual "same person as the seed" mean at least A0's - 0.5, and its per-panel slope at least -0.1 | L2, report |
| CXK9 | L2: judge-stills `rendering_quality` at least A0's - 1 | L2, report |
| CXK10 | Wall clock: B1's Phase 2 at most 2.5 x A0's Phase 2; F1's total at most 1.5 x A0's total | L2, L4, report |
| CXK11 | Frame mode counts as worth it only if F1's judge-clips `seam_continuity` is at least B1's + 1.5 | L4, report |
| CXK12 | No child timed out in any arm (the entries' `error` fields and `arm.log`'s `child timed out after` lines); seconds per edit and mlx peak GiB recorded for every arm; the `qwen2511-bf16` rows recorded or "not run: <reason>" | L1-L6, report |

Every CX requirement and CXT test is a must-have. CXK7-CXK12 are read only from complete arms (Section 7's completion gate, A2): a KPI reading an incomplete arm prints `n/a (incomplete)`, never PASS. CXK7-CXK11 are the user's decision inputs for B1, B2 and F1 on `qwen21-q4` and for the `-bf16` arms; there are no nice-to-haves.

---

## 1. Decisions

1. **Where.** Still mode is a seeded-shots branch of `phase2_stills` taken only when `args.seed_context` is set (CX10); frame mode replaces `phase2_stills` in the phase tuple with `phase_seed_context_frames` (CX15). `bin/ltx-story-images`, `bin/ltx-story-manifest` and `bin/ltx-mlx-render` are pinned and untouched.
2. **Picture order flag: included** **[spec choice]**. `--seed-context-order {seed-first,context-first}` costs one prompt template with picture-number slots (`SEED_CONTEXT_PREFIX`), one `sources` order switch and one key item (`context.picture`): about 12 code lines. The picture order is the one lever the controller asked to A/B (arm B2); without the flag that arm would need a follow-up. Kind `none` panels ignore it (their key has `picture: None`), so switching the order re-edits only context panels.
3. **Location change = a different setting sentence (CX4)** **[spec choice]**. The setting sentence is the first sentence of the panel's `Image:` text, split with `character_lib._SENTENCE_SPLIT_RE`, that matches `character_lib._SETTING_SENTENCE_RE` (the S12 pattern), with whitespace collapsed; two panels are at the same place when the strings are equal (`None == None` counts as the same place). The robust engine pastes the beat location's sentence word for word as the first piece of every shots `Image:` (`story_engine.py:2272`), and S12 requires one in every panel, so equality of that sentence is exactly "same plan location" for engine-written stories; no model call and no new regex in `bin/ltx-movie`.
4. **Prompt (CX3).** Kind `none` panels keep today's seeded-shots prompt byte for byte (`SHOTS_SEED_EDIT_PREFIX` + text), so panel 1 of an A0 run and of a B1 run get the same prompt, seed and size. Context panels get `SEED_CONTEXT_PREFIX` (the controller's wording, plus "leave out anyone the new shot does not describe" carried over from `SHOTS_SEED_EDIT_PREFIX`, because a context picture can show people the new shot omits) **[spec choice]**. It names each picture as "Picture N, the first/second input image" in both template styles, as [CR] CR8 does (qwen21 tags `<imageN>`, diffusers writes `Picture N:`).
5. **Reuse and the forced cascade (CX7)** **[spec choice]**. A panel is reused when it is not a `--redo` panel, its entry is `ok` with every key item equal (the seed-edit key plus `context`), its still exists with the recorded sha256, AND, for a context panel, panel N-1 was not edited earlier in this run. The last clause makes the cascade unconditional: a re-edited still re-edits every panel that sees it even if the model happened to reproduce the same bytes, which is the controller's "a changed panel j invalidates j+1..". The cascade stops at the next kind `none` panel, because such a panel does not see panel N-1; this is the exact dependency, and the `--redo` note lists exactly the panels it adds. When a panel is about to be edited, its cascade's entries are cleared too, so an interrupted run never leaves an `ok` entry whose context picture predates a re-edit.
6. **Serial children (CX10).** One `qwen_edit.run_jobs([job])` call per edited panel: a running child cannot be handed an output produced after it started, and the parent screens and renames each output only after the child's done line. Each child's log is its own `seed_context_edits/child-NN.log`, removed before the call (the runner appends), so its "mlx peak memory" line is that panel's peak (PR #15 review lesson). Cost: one model load per edited panel (Risk R1).
7. **Errors, not fallbacks (CX8, CX19).** The first blocked or failed panel stops Phase 2: a later panel would otherwise see a missing or stale context. Every `Exception` from the memory wait or the batch (including `on_result`'s fit) becomes a `failed` entry and one `Error:` line (PR #15 review lesson); `KeyboardInterrupt` and `SystemExit` propagate as today.
8. **Frame mode as Phase 2 (CX15)** **[spec choice]**. The interleaved loop runs where Phase 2 runs; Phase 3 then rebuilds `manifest.json` with every real still and shows its unchanged dry-run gate, and Phase 4 renders with `--resume` (every clip reused) and concatenates: that is the controller's "final full render". So the manifest builder, the render tool and the summary report are reused, not duplicated.
9. **Frame mode details (CX16-CX19)** **[spec choice]**. The manifest is built once, before any edit, with `seed_context_edits/placeholder.png` (the seed fitted into 2W x 2H) as every panel's still, so a broken story fails before GPU time. For each k, `seed_context_edits/manifest_upto.json` is that manifest's panels 1..k with their real stills; the partial render writes `seed_context_edits/upto.mp4` (deleted before and after) and logs to `seed_context_edits/render-KK.log`; its flags are Phase 4's, unchanged (`_phase4_flags(args)`: `--on-panel-failure skip` for `--shots`, `--retry-failed 1`, `--retry-idle 120`; Amendment A1), so `--resume` and the retry settings match Phase 4. With skip only clip k renders in the partial render (clips 1..k-1 are reused), `bin/ltx-mlx-render`'s end-of-run retry pass retries it once, and a clip still failing makes the render exit non-zero, which stops the run. (A `stop` policy would set `stopped_reason`, and the retry pass runs only when `stopped_reason` is `None`, so it would silently disable the retry.) `_wait_for_avail` runs before every partial render (the Qwen child has exited). The last frame of clip k is extracted to `seed_context_edits/frame_KK.png` and checked only when panel k+1 is a frame panel. An existing `movie.mp4` without `--force` is refused up front (Phase 4 would refuse it after hours of work). Unless `--no-review`, one gate prompt precedes the first edit, because the frame loop spends GPU time before Phase 3's gate.
10. **No failure-policy refusal** (controller decision 9's last item). `bin/ltx-movie` has no failure-policy option: `_phase4_flags` hard-codes `skip` for `--shots`. Frame mode passes Phase 4's flags unchanged (skip plus one retry, Amendment A1); a clip that still fails after the retry makes the partial render exit non-zero, which stops the run, so there is nothing to refuse; CXT12 pins the flags and CXT20 the retry.
11. **Size (CX5).** The edit size is `_seed_edit_size` (the video size floored to the model's multiple) and every output is fitted into the 2W x 2H still, exactly as A0. Picture 1 is the oriented original seed (`seed-original.png`, its own aspect); the still-mode context is a 2W x 2H still and the frame-mode context a W x H frame. Phase 0 derives W x H from the seed's aspect (snapped to multiples of 64), so the three aspects differ only by that snap (Risk R4).
12. **Timeout.** `jobs_timeout([job])`: a two-image job counts 6, so its child gets max(3600, 600 x 6) = 3600 s, the same as a one-image job's floor. No change to `qwen_edit.py`.
13. **CLI only for v1** **[spec choice]**, as [CR] decision 9 (a Compose control touches at least six files and several pins).
14. **Records.** `seed_context_edits.json` through the PR #15 helpers with `SEED_CONTEXT_SCHEMA`; the skill `ltx_movie_seed_context_edit` labels every output of this mode, kind `none` included **[spec choice]**.

---

## 2. Architecture

```
bin/ltx-movie --shots --seed-image SEED --seed-edit-model ID --seed-context still|frame [--seed-context-order ...]
  main: ... _resolve_seed_edit -> _resolve_cast_refs -> _resolve_seed_context (CX2; sets args.seed_context)
  Phase 0 -> Phase 1 -> Phase 1b -> [Redo]
  still: Phase 2 = phase2_stills -> _phase2_seed_context (CX10)
           _seed_context_plan (read-only): prompts, kinds (none at panel 1 and every location change), base keys
           for n = 1..N: context = images/panel_{n-1}.png (kind still) ; reuse? (_seed_context_reusable)
                         else _seed_context_edit: move old still aside, clear entries (n + cascade), one
                         qwen_edit.run_jobs([job with sources]) -> fit into images/panel_NN.png -> record
         Phase 3 (unchanged) -> Phase 4 (unchanged; --resume re-renders clips whose still changed)
  frame: Phase 2 = phase_seed_context_frames (CX15-CX19)
           movie.mp4 guard -> plan -> placeholder.png -> _phase3_manifest_cmd(placeholders) -> manifest.json
           -> load bin/ltx-mlx-render -> [gate]
           for k = 1..N: still k (context = seed_context_edits/frame_{k-1}.png) as above
                         -> manifest_upto.json (panels 1..k, real stills) -> _wait_for_avail
                         -> bin/ltx-mlx-render manifest_upto.json upto.mp4 <Phase 4's flags> (clips 1..k-1 reused)
                         -> if panel k+1 is a frame panel: extract_last_frame(clip k) + check_chain_seed
         Phase 3 (rebuilds manifest.json with the real stills; its gate) -> Phase 4 (reuses every clip, concatenates)
```

---

## 3. Requirements

### Task 1: still mode (`bin/ltx-movie`, edits M1-M9)

- **CX1. Flags** (M3): `--seed-context` (dest `seed_context_mode`, `choices=["still"]` after Task 1, `["still", "frame"]` after Task 2, default `None`) and `--seed-context-order` (dest `seed_context_order`, `choices=["seed-first", "context-first"]`, default `None`, meaning seed-first). Exact help texts in M3 (F3), pinned by CXT9 and CXT19.
- **CX2. `_resolve_seed_context(args)`** (M4), called from `main` right after `_resolve_cast_refs` (M9). Sets `args.seed_context` to `None` or `{"mode": MODE, "order": ORDER}`. Rules in order, each refusal one `Error:` line and return 2:
  1. no `--seed-context`: with `--seed-context-order` refuse, else `None`;
  2. no `--shots`: refuse (this also covers `--no-stills` without `--shots`; `--shots --no-stills` is refused earlier by `_resolve_shots`, and `--seed-image --no-stills` by `main`);
  3. no `--seed-image`: refuse;
  4. `--cast-refs-model` given: refuse (reached only when called directly: with a seed image `_resolve_cast_refs` refuses first, with its own consistent text);
  5. `args.seed_edit` is `None` (no registry `--seed-edit-model`, `as-is` included): refuse (through `main`, `_resolve_shots` refuses first with SE2's text);
  6. `qe.multi_reference_problem(model)` is not `None` (`qwen2511-q4`): refuse with that text;
  7. set the dict and return 0. No weights are read (the selection was checked by `_resolve_seed_edit`).
- **CX3. Constants and prompts** (M2, M6): `SEED_CONTEXT_SKILL = "ltx_movie_seed_context_edit"`, `SEED_CONTEXT_SCHEMA = "ltx-movie.seed-context-edits.v1"`, `SEED_CONTEXT_PREFIX` (with `%(people)d`, `%(people_nth)s`, `%(scene)d`, `%(scene_nth)s`), `SEED_CONTEXT_KINDS`, `SEED_CONTEXT_PICTURES`, `SEED_CONTEXT_CHANGE_NOTE`, `SEED_CONTEXT_REDO_NOTE`. `_seed_context_prompt(order, text)`: seed-first fills people 1/first and scene 2/second; context-first the reverse; then `text`.
- **CX4. `_seed_context_setting(lib, image)`** (M6): Decision 3.
- **CX5. `_seed_context_paths` and `_seed_context_plan(args, qe)`** (M6), read-only: `(error, plan)`. Errors: no panels (`"<story.md> has no panels to edit the seed into"`), a panel without `Image:` text (`"panel <n> of <story.md> has no Image: description to edit the seed with"`), the same texts as SE. Kinds: panel 1 and every location change `none`, else the mode. Prompts: kind `none` = `SHOTS_SEED_EDIT_PREFIX + _compose_prompt(Image, Style)`; else `_seed_context_prompt(order, _compose_prompt(Image, Style))`. `base[n]` = the SE13 key: `qe.settings(model, loras)` plus `source_sha256` (the seed's bytes), `prompt`, `seed` (`--image-seed`), `width`, `height` (the edit size), `still_width`, `still_height`. `changes` lists the location changes; `entries` come from `_shots_seed_entries(record, SEED_CONTEXT_SCHEMA)`.
- **CX6. `_seed_context_context(args, plan, n, path)`** (M6): `{"kind": "none", "file": None, "sha256": None, "picture": None}` for kind `none`; else `{"kind": KIND, "file": <path relative to the story dir>, "sha256": <its sha256, or None while it does not exist>, "picture": 2 (seed-first) or 1 (context-first)}`.
- **CX7. Reuse and cascade** (M6): `_seed_context_reusable` (Decision 5), `_seed_context_cascade(plan, start)` (the panels after start up to the next kind `none` panel), and `_seed_context_notes`: the location-change line when there is one, and `SEED_CONTEXT_REDO_NOTE` when `--redo` panels add panels by cascade.
- **CX8. `_seed_context_edit(args, qe, plan, n, path, context, archive)`** (M6): moves an existing `images/panel_NN.png` into `<story>/redo/<stamp>-<pid>/images/` (printing the moved line), removes `seed_context_edits/panel_NN.png`, `panel_NN.pending.png` and `child-NN.log`, clears the entries of n and its cascade and writes the record, prints the panel's describe line, then runs `qe.wait_for_memory(qe.memory_floor(model), label, tag="ltx-movie")` and `qe.run_jobs(model, loras, [job], W, H, SEED_CONTEXT_SKILL, work, log_path=work/child-NN.log, on_result=..., noun="panel")`. The job is `{"n", "seed", "prompt", "source": seed-original.png, "stage_path", "output_path"}`; a context job adds `"sources"` (seed-first `[seed, context]`, context-first `[context, seed]`) and its `"source"` is `sources[0]`. `on_result` fits an ok output into the still and records the entry; a blocked result records a `blocked` entry. `qe.Unavailable` gives its text; any other `Exception` gives `"<Type>: <message>"`; a missing result gives `"<label> reported no result for panel <n>"`; a failed panel records a `failed` entry with that error. Returns `(status, failure)`. `_seed_context_stop` prints the stop line (Section 4).
- **CX9. The record** `<story>/seed_context_edits.json` = `{"schema": "ltx-movie.seed-context-edits.v1", "updated", "panels": [entry...]}`; each entry has exactly these keys in this order: `n`, `status`, `created`, `label`, `source`, `source_sha256`, `original`, `context`, `prompt`, `seed`, `width`, `height`, `still_width`, `still_height`, `qwen_model`, `loras`, `steps`, `scheduler`, `output` (`seed_context_edits/panel_NN.png` or `None`), `still` (`images/panel_NN.png` or `None`), `still_sha256`, `seconds`, `error`.
- **CX10. `_phase2_seed_context(args)`** (M6) and the dispatch (M5): plan error -> exit 1; `SHOTS_SEED_LORA_NOTE` when a Z-Image stills LoRA would have applied (`_shots_seed_lora_note`, as SE14); the notes; the header line; writes `seed-original.png` (the oriented seed, as SE); then for n = 1..N: the context picture is `images/panel_{n-1}.png`; reuse (one reuse line) or `_seed_context_edit`; the first non-ok panel stops with exit 1; finally `seed context: <edited> panel stills written, <reused> reused`.
- **CX11. Dry run** (M7, M8): `_print_seed_context_plan(args)` prints one sentence (model, size, seed, picture order, context kind, skill, still path and size, record), then either `Panels: decided at Phase 2, from story.md after Phase 1` (with `--force-story`, unknown geometry or no story.md) or `Location changes (single-image edits): <list or none>` and `Panels to edit: <list or none>; reused: <list or none>`, computed with the same `_seed_context_reusable` and the forced cascade. It writes nothing and reads no weights.
- **CX12. Byte-identical default.** Every new path is gated by `args.seed_context` (set only by CX2). Without it, `phase2_stills`, `_print_dry_run_plan` and `main` run exactly as before.
- **CX13. Docstring** (M1): the Seed context paragraph between the Seed edit and Cast references paragraphs, pinned by CXT9.

### Task 2: frame mode (`bin/ltx-movie`, edits F1-F10)

- **CX14. Flag and texts** (F1-F3): `--seed-context frame` accepted; help and docstring extended (pinned by CXT19 and the edited CXT9); `SEED_CONTEXT_KINDS["frame"]`, `SEED_CONTEXT_PICTURES["frame"]`, `SEED_CONTEXT_FRAME_GATE`.
- **CX15. Phase tuple and the render tool** (F4, F7, F10): `_phase_sequence` replaces `phase2_stills` with `phase_seed_context_frames` when `args.seed_context["mode"] == "frame"` (after every other insertion, so `[Redo]` stays before it); `_render_tool()` returns `os.path.join(WS, "bin", "ltx-mlx-render")` and is used by `phase4_render` (same argv), the partial renders and `_ltx_render()` (the module, loaded by path with `SourceFileLoader(...).load_module()` like every other loader in `bin/ltx-movie`).
- **CX16. The manifest** (F5, F6, F4): `_phase3_manifest_cmd(args, image_flags=None)` holds Phase 3's command building verbatim (returns `(0, cmd)` or `(2, None)` after the catalog error) and is defined after `phase3_manifest`; frame mode calls it with `["--image", placeholder] * N`, runs it through `_stream_and_tee` (log `seed_context_edits/manifest.log`), reads `manifest.json` and refuses one whose panel count differs from story.md's. `manifest_upto.json` is written with `_write_seed_edit_record`.
- **CX17. The partial render** (F4; Amendment A1): `[sys.executable, _render_tool(), manifest_upto.json, upto.mp4] + _phase4_flags(args)` through `_stream_and_tee` (log `render-KK.log`), after `_wait_for_avail(args.min_avail_gib, args.avail_timeout)`: Phase 4's flags unchanged (`--on-panel-failure skip`, `--retry-failed 1`, `--retry-idle 120`), so a failed clip k is retried once by the render tool's retry pass. A nonzero exit (clip k still failing after the retry) stops the run (exit 1). There is no `_seed_context_frame_flags`.
- **CX18. The context frame** (F4): when panel k+1 is a frame panel, `render.extract_last_frame(clips/panel_KK.mp4, seed_context_edits/frame_KK.png, args.frames)` then `render.check_chain_seed(frame, args.video_width, args.video_height, k)`; any violation stops the run.
- **CX19. Guards and failures** (F4): the `movie.mp4` guard (exit 2), a failed manifest build, an unreadable manifest, an unloadable render tool, a blocked or failed still, a failed render, a bad frame and a failed memory gate each stop with one `Error:` line and exit 1; exceptions from the tool load and the frame extraction become `"<Type>: <message>"`. The review gate (`SEED_CONTEXT_FRAME_GATE`) precedes the first edit unless `--no-review`.
- **CX20. Frame dry run** (F8, F9): the CX11 sentence (with the frame kind), the `Frame mode: ...` line, and after the location-change line `Panels to edit: decided panel by panel during the run: ...` (a context picture depends on clips this run renders).

### Task 3

- **CX21.** `test_mut26`'s BASELINE moves once, after the last code commit, to that commit (Task 3). `NEW_PY` is not extended: QET11 pins its tail, as [CR] CR15 found; both new test files meet the `NEW_PY` rules by construction (no `load_module(`, no `urllib`; `SourceFileLoader` + `exec_module`) and each task compiles them on Python 3.9 and 3.13.

---

## 4. Errors and messages

| Condition | Where | Text | Effect |
|---|---|---|---|
| `--seed-context-order` alone | `_resolve_seed_context` | `Error: --seed-context-order needs --seed-context` | exit 2 |
| no `--shots` (also `--no-stills` alone) | same | `Error: --seed-context needs --shots: it conditions each seeded shots still on the previous panel` | exit 2 |
| `--shots --no-stills` | `_resolve_shots` (existing) | `Error: --shots needs Phase 2's per-panel stills; it cannot be combined with --no-stills` | exit 2 |
| no `--seed-image` | `_resolve_seed_context` | `Error: --seed-context needs --seed-image: every shots still is then a Qwen edit of the seed` | exit 2 |
| with `--cast-refs-model` | `_resolve_cast_refs` (existing, first) / `_resolve_seed_context` (direct call) | `Error: --cast-refs-model cannot be combined with --seed-image: with a seed image every shots still is already a Qwen edit of the seed` / `Error: --seed-context cannot be combined with --cast-refs-model: with a seed image every shots still is already a Qwen edit of the seed` | exit 2 |
| no registry `--seed-edit-model` (`as-is` included) | `_resolve_shots` (existing, first) / `_resolve_seed_context` (direct call) | SE2's `Error: --shots with --seed-image needs --seed-edit-model ID: ...` / `Error: --seed-context needs --seed-edit-model ID, a Qwen registry edit model (as-is is refused): every shots still is a Qwen edit of the seed` | exit 2 |
| `qwen2511-q4` | `_resolve_seed_context` | `Error: --seed-context needs a --seed-edit-model that edits with several pictures; qwen2511-q4 is refused: <CR1 text>` | exit 2 |
| story.md without panels / a panel without `Image:` | Phase 2 | `Error: <story.md> has no panels to edit the seed into` / `Error: panel <n> of <story.md> has no Image: description to edit the seed with` | exit 1, nothing edited |
| info | Phase 2 | `seed context: location changes at panels <list> (the Image: setting sentence differs from the previous panel's): each of them is a single-image edit of the seed, like panel 1`; `note: seed context: --redo <list> also re-edits panels <list>: their context picture is <kind text>, so it changes with it, up to the next location change`; `seed context: <generator_text>; <W>x<H>, fitted into <SW>x<SH> stills; seed <s>; <N> panels in order, one Qwen child per edited panel; the seed is Picture <a> and <kind text> is Picture <b>`; `seed context: panel <n>: reusing <still> (a recorded edit of the same seed image, context picture, prompt, seed and settings)`; `seed context: moved <src> -> <dst> (not a recorded edit of this seed image, context picture, prompt, seed and settings)`; `seed context: panel 1: a single-image edit of the seed`; `seed context: panel <n>: a single-image edit of the seed (a location change: its setting sentence differs from panel <n-1>'s)`; `seed context: panel <n>: Picture <a> is the seed (<path>), Picture <b> is <panel n-1's still / the last frame of panel n-1's clip> (<path>)`; `panel <n> -> <still> (seed-context Qwen edit, <s>s)`; `panel <n> BLOCKED: the content screen blocked the seed-context Qwen edit`; `seed context: <k> panel stills written, <r> reused` (frame mode adds `; every clip is made, so Phase 4 reuses them all`) | stdout |
| blocked panel | Phase 2 | `Error: the content screen blocked the seed-context Qwen edit (<label>) of panel <n> of story <id>; the movie stops here rather than use an unscreened, unedited or text-rendered still. Change that panel's Image: line in <story.md>, then rerun: every recorded still before it is reused` | exit 1 |
| failed panel (child failure, timeout, missing result, memory wait, install check, any exception) | Phase 2 | `Error: the seed-context edit of panel <n> failed: <failure>; the stills before it are kept, and a rerun continues from panel <n>` | exit 1; `failed` entry |
| frame: `movie.mp4` exists, no `--force` | frame Phase 2 | `Error: <movie.mp4> already exists; pass --force to overwrite` | exit 2, nothing run |
| frame: manifest build | same | `Error: ltx-story-manifest exited <rc>; see <manifest.log>` / `Error: cannot read <manifest.json>: <reason>` / `Error: <manifest.json> has <a> panels and <story.md> has <b>` | exit 1 |
| frame: tool load | same | `Error: cannot load <WS>/bin/ltx-mlx-render: <Type>: <message>` | exit 1 |
| frame: render | same | `Error: ltx-mlx-render exited <rc> on panels 1-<k>, so panel <k>'s clip is not made; frame mode stops here (see <render-KK.log>); a rerun reuses every recorded still and finished clip` | exit 1 |
| frame: frame check | same | `Error: panel <k+1>'s context frame (the last frame of <clip>): <violations or Type: message>` | exit 1 |
| frame: info | same | `seed context: the manifest, built once with <placeholder> as every panel's still until it is made; log: <manifest.log>`; `seed context: panel <k>: its clip (bin/ltx-mlx-render --resume on panels 1-<k>); log: <render-KK.log>`; `seed context: panel <k+1>: the last frame of <clip> -> <frame>`; the gate `Frame mode renders every panel's clip right after its still, before the next still is edited. Enter to start, Ctrl-C to abort: ` | stdout / input |

No new stdout line matches the movie-ui render progress patterns (`^panel (\d+) ok: `, `^panel (\d+): reusing `, `^panel (\d+) FAILED \(`, `^=== panel (\d+)/(\d+) \(`); frame mode's partial renders print those lines themselves during Phase 2 (CLI only; Review Focus 9).

## 5. Audit: everything the change touches or could touch

| Reader / writer | Where | Verdict |
|---|---|---|
| `_phase2_shots_seed`, `seed_edits.json` | default seeded shots | Not called with `--seed-context`; unchanged without it (CXT7, SET1-SET15 unedited). The two records are separate, and each mode's reuse checks its own record plus the still's sha256, so alternating modes on one story re-edits rather than reusing a foreign still. |
| `qwen_edit.run_jobs` | per edited panel | Existing API; `sources` only on context jobs; `jobs_timeout` unchanged. |
| `_shots_seed_entries`, `_write_shots_seed_record`, `_write_seed_edit_record` | record and `manifest_upto.json` | Called with `SEED_CONTEXT_SCHEMA`; their defaults are unchanged (CRT15). |
| `images/panel_NN.png` | Phase 3, Phase 4 `--resume` | Same names and size; a re-edited still re-renders its clip. |
| `--redo` | `phase_redo_shots` | Moves the redo panels' stills and clips (and `movie.mp4`) as today; Phase 2 re-edits them and their cascade (note). Its "every other panel's still and clip is reused" line is inaccurate for cascaded panels; the Phase 2 note corrects it (Review Focus 5). |
| `phase3_manifest` | Phase 3 | Same command, built by `_phase3_manifest_cmd` (CXT12; test_lora_catalog, test_dialogue unedited). |
| `phase4_render` | Phase 4 | Same argv via `_render_tool()` (CXT12). |
| `<story>/runs/*/story_summary.json` | `_report_summary`, `estimate_seconds_per_panel` | Frame mode adds one summary per partial render; `_report_summary` reads the newest (Phase 4's); the estimate skips resumed units. |
| `clips/panel_NN.mp4` | frame mode, Phase 4 | Rendered by the partial runs, reused by Phase 4 (CXT17). |
| movie-ui | Compose, progress | Never passes the flag; `help_flags` sees two new flags that no field maps. |
| deploy package | `scripts/deploy/build_pkg.py` | Ships `bin/ltx-movie`, not `qwen_edit.py`: `--seed-edit-model` already fails there, so `--seed-context` is unreachable. |

---

## 6. Tests

Two new files; their full text is in the Plan (Task 1 Step 1, Task 2 Step 1). They follow [QE] §11.1: no real model, HOME, server, render or download. The Qwen side is `test_ltx_movie_shots_seed._FakeShotsQwenEdit` extended in-file, or the real `qwen_edit` with the stub children of `tests/test_seed_edit_tool.py`; the render side is an in-file fake of `_stream_and_tee` and `_ltx_render`, or the real `bin/ltx-mlx-render` `main()` with its generator, probes, concat and content screen stubbed.

`tests/test_ltx_movie_seed_context.py` (Task 1; Task 2 edits CXT9's three pins):

| ID | Covers | Asserts |
|---|---|---|
| CXT1 | CX2 | every refusal text, called directly and through `main` (`--shots --no-stills`, no `--seed-edit-model`, `as-is`, `qwen2511-q4`, `--cast-refs-model`, `--no-stills` alone); the resolved dict for the four allowed models and for `context-first` |
| CXT2 | CX3-CX5 | the setting sentence (whitespace collapsed, case-insensitive start, none); kinds `{1: none, 2: still, 3: none, 4: still}` and changes `[3]` for a harbour-then-market story; every prompt exactly, in both orders; the base key; a one-place story (no change) and a story whose only setting sentence is in panel 3 (changes `[3, 4]`); the two plan errors; nothing written |
| CXT3 | CX6, CX8-CX10 | `phase2_stills` end to end: four `run_jobs` calls with the exact one-job lists (sources only for panels 2 and 4), the event log (each context pixel is the still written earlier in the run), the per-panel child logs, four memory waits, `seed-original.png`, the 1408x896 stills, the record (schema, key order, every entry, the context items), no A0 file, and every stdout line |
| CXT4 | CX3, CX6 | `context-first`: the swapped prompt, `source` and `sources`, the picture order seen by the child, `picture: 1` entries and the describe and header lines |
| CXT5 | CX7 | an identical rerun reuses all four (exact lines); a changed panel 2 re-edits only 2 (old still archived); a changed panel 1 re-edits 1 and 2 although the fake reproduces panel 1's bytes (forced cascade); a changed panel 3 re-edits 3 and 4; `--redo 1` re-edits 1 and 2 with the exact note; `--redo 1,3` all four; `--redo 2` only 2 and no note; switching the order re-edits 2 and 4; a new seed, image seed or model re-edits all; an overwritten still re-edits it and its cascade |
| CXT6 | CX8 | a blocked panel stops the phase at that panel (exact error; later panels not attempted); the rerun continues; a timed-out child, a missing result, a memory wait and an `OSError` raised by the runner each give exit 1, the exact `Error:` line and a `failed` entry, never a traceback; `KeyboardInterrupt` propagates with the finished entries kept and the cascade's cleared, so the rerun edits only panel 4 |
| CXT7 | CX12 | without the flag `phase2_stills` calls `_phase2_shots_seed(args)`, writes no `seed_context_edits*` file and prints only the Phase 2 header; the phase tuple is the same with and without still mode |
| CXT8 | CX11 | the dry run through `main`: the exact sentence and the "decided at Phase 2" line; the `context-first` wording; with a story and a record: `Location changes (single-image edits): 3`, `Panels to edit: 3,4; reused: 1,2`, and `1,2,3,4` with `--redo 1`; nothing written, no host check |
| CXT9 | CX1, CX13 | both help texts, the choices, the docstring paragraph (followed by the Cast references paragraph), no top-level `import re`, no L7j orphan name |
| CXT10 | CX8 | the event order over a one-place story: the child of panel n starts only after panel n-1's fit, with `sources` `[seed-original.png, panel_{n-1}.png]` |
| CXT11 | CX8 | the real runner, mflux stub: one child per panel, `sources` in the spec jobs, every output screened with `ltx_movie_seed_context_edit` at 704x448, each child log holding only its own run (a stale line is gone after a rerun), a block on the rerun; the diffusers stub: the `images` lists, the skill, and a block that stops the phase |

`tests/test_ltx_movie_seed_context_frame.py` (Task 2):

| ID | Covers | Asserts |
|---|---|---|
| CXT12 | CX14, CX15, CX17 | `--seed-context frame` resolves; the frame phase tuples (with release, with `--redo`, `--story-only`) and still mode's unchanged tuple; the partial-render flags are Phase 4's (`_phase4_flags`: `--on-panel-failure skip`, `--retry-failed 1`, `--resume`; A1); `_render_tool`; `_phase3_manifest_cmd` with and without placeholders; `phase4_render`'s argv unchanged |
| CXT13 | CX15-CX18 | the exact event list of a four-panel run (manifest build; edit 1; memory gate; render 1; frame 1 and its check; edit 2 with frame 1's pixel; ...; no frame for the location change or the last panel); the placeholder; the build command and log; every partial render command and log; each `manifest_upto.json`'s panels; the record's frame context items; the stdout lines |
| CXT14 | CX19 | an existing `movie.mp4` (exit 2, nothing run), a failed manifest build and an unloadable render tool (exit 1, no edit) |
| CXT15 | CX18, CX19 | a blocked still stops before its clip; a failed render, a bad frame and an extraction exception give the exact `Error:` lines; a failed memory gate renders nothing; the review gate's exact prompt |
| CXT16 | CX16, CX18 | reruns: everything reused (renders and frames still run, no edit); a changed clip 1 re-renders it and re-edits panel 2 only; a changed panel 1 re-edits 1 and 2; `--redo 3` re-edits 3 and 4 with the frame note |
| CXT17 | CX16, CX17 | the real `bin/ltx-mlx-render` `main()` in-process: partial run k renders only clip k (seeds 1, 2, 3); the summaries' `requested_units`, `completed_units`, `intended_total_frames` and `actual_total_frames` are 1/2/3, 145/290/435, `on_panel_failure` `skip` and `stopped_reason` `None` (A1); a full render of all panels and a frame-mode rerun with `--force` generate nothing; the clip provenance's `image_sha256` is the real still's |
| CXT18 | CX20 | the frame dry run: the sentence, the `Frame mode:` line, the later lines equal still mode's; with a story, the location-change line and the "decided panel by panel" line; nothing written or run |
| CXT19 | CX14 | the frame help text, the choices and the docstring sentence |
| CXT20 | CX17 | (A1) the real `bin/ltx-mlx-render` `main()` in a one-panel frame run: the generator fails once, then succeeds on the retry pass (`--retry-idle` 0 in the test); `phase_seed_context_frames` returns 0, the generator ran twice, the one summary has `completed_units` 1, `on_panel_failure` `skip`, `stopped_reason` `None`, and its unit is `ok` with `attempts` 2 and `first_failure` set (`error`) |

Before any code change: Task 1's file gives `10 failed, 1 passed` (CXT7 pins today's behaviour and passes before and after). With Task 1 in place, Task 2's file gives `3 failed, 5 errors` (the five tests using the `frame_env` fixture error at setup because `_ltx_render` does not exist yet). After both: 19 passed; after the A1 fix commit: 20 passed.

**Mutation check** (scratch replay, `$S/sc-tools/mutate.py`): each mutation of the final `bin/ltx-movie` made at least one new test fail: dropping the forced cascade 1, the `except Exception` of the edit 1, the child-log removal 1, the location-change rule 8, the cascade entry clearing 1, the picture order 1, the `context` key item 1, the still-mode dispatch 1, the frame `stop` policy 2 (void since A1 removed that policy; not re-run), the frame memory gate 2, the frame extraction's `except Exception` 1, the real stills in `manifest_upto.json` 2, the `movie.mp4` guard 2, the frame phase tuple 1.

No existing test is edited except `test_mut26`'s BASELINE (Task 3); the A1 fix commit edits only this spec's own new file `tests/test_ltx_movie_seed_context_frame.py`. No fixture is regenerated.

---

## 7. Live checks on macstudio (the user runs these; the assistant never accesses macstudio)

**Preparation.**
- In `~/local_agent_harness`: `git fetch && git checkout seed-context`.
- `bin/seed-edit-setup --model qwen21-q4 --lora uncensored`, if not installed. For L3, `Qwen/Qwen-Image-Edit-2511` and its Lightning LoRA must be in the default hub and diffusers importable; if `bin/ltx-movie ... --seed-edit-model qwen2511-bf16` refuses with `... is unavailable: <reason>`, record L3 "not run: <reason>".
- Pick `SRC`, a seeded shots story recorded on macstudio (made with `--shots --seed-image`), with at least 8 panels and at least 2 locations, and `SEED`, its seed image. Every arm except Ch runs on a NEW story id with a COPY of SRC's `story.md` and `plan.json`, so every arm edits the same prompts. Unrecorded rows read "not run (awaiting the user)".

```zsh
cd ~/local_agent_harness/qwen-agent-workspace
SRC=<recorded seeded shots story id>; SEED=<its seed image>; N=<its panel count>
grep '^cmd: ' generated/stories/$SRC/iterate-story.log | tail -1      # the source run's flags
EXTRA=(<the source run's other flags: --model, --gemma, --story-model, --fps, --frames, --speech-only, ...>)
Q4=(--seed-edit-model qwen21-q4 --seed-edit-lora uncensored=1.0); BF=(--seed-edit-model qwen2511-bf16)
copy() { mkdir -p generated/stories/$2 && cp generated/stories/$1/story.md generated/stories/$1/plan.json generated/stories/$2/; }
narr() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["narrative"])' generated/stories/$1/plan.json; }
stamp() { python3 -u -c 'import io, sys, time
for line in io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace"):
    sys.stdout.write("%.1f %s" % (time.time(), line))
    sys.stdout.flush()'; }
arm() { local id=$1; shift; copy $SRC $id
  PYTHONUNBUFFERED=1 bin/ltx-movie "$(narr $SRC)" --story-id $id --shots --seed-image $SEED --panels $N --no-review \
    "${EXTRA[@]}" "$@" < /dev/null 2>&1 | stamp > generated/stories/$id/arm.log; }
copy $SRC sc_dry; bin/ltx-movie "$(narr $SRC)" --story-id sc_dry --shots --seed-image $SEED --panels $N "${EXTRA[@]}" \
  "${Q4[@]}" --seed-context still --dry-run > generated/stories/sc_dry/dry-run.txt
grep -E '^(Location changes|Panels to edit)' generated/stories/sc_dry/dry-run.txt
awk -v n=$N -F': ' '/^Location changes \(single-image edits\): /{k=($2=="none")?0:split($2,c,","); r=0; p=1
  for(i=1;i<=k;i++){if(c[i]-p>r)r=c[i]-p; p=c[i]}; if(n+1-p>r)r=n+1-p
  printf "context panels: %d of %d; longest same-place run: %d panels\n", n-1-k, n, r}' generated/stories/sc_dry/dry-run.txt
```

**Precondition (A3).** The dry run prints no per-panel kinds; its `Location changes (single-image edits): <list or none>` line is the source. The `awk` line derives `context panels: <K> of <N>; longest same-place run: <R> panels`, where K = N - 1 - (the number of location changes) is the number of panels 2..N whose kind is `still` (or `frame`), and R is the longest run of consecutive panels between location changes (panel 1 and each change start a run). The live checks need at least one location change, K >= 3, and ideally R >= 3 (two context panels in a row, so the chain is exercised); otherwise pick another SRC. With K < 3, B1 and B2 edit nearly every panel with A0's prompt (a kind `none` prompt is A0's byte for byte), so CXK7 and the other B1/B2 comparisons would differ from A0 for a non-model reason. If the `awk` line prints nothing, the dry run printed `Panels: decided at Phase 2 ...` or `Panels: Phase 2 would stop: ...` instead; fix that first. Every arm writes `generated/stories/<id>/arm.log`, each line prefixed with its epoch time; `PYTHONUNBUFFERED=1` keeps the times exact. `--no-review` with `< /dev/null` runs unattended.

The arms (run them in this order; each is a full run through Phase 4):

```zsh
arm sc_a0_q4 "${Q4[@]}"                                                          # L1  A0
arm sc_b1_q4 "${Q4[@]}" --seed-context still                                     # L2  B1
arm sc_b2_q4 "${Q4[@]}" --seed-context still --seed-context-order context-first  # L2  B2
arm sc_a0_bf16 "${BF[@]}"                                                        # L3  A0-bf16
arm sc_b1_bf16 "${BF[@]}" --seed-context still                                   # L3  B1-bf16
arm sc_f1_q4 "${Q4[@]}" --seed-context frame                                     # L4  F1
mkdir -p generated/stories/sc_ch_q4                                              # L5  Ch: chained, its own story.md
PYTHONUNBUFFERED=1 bin/ltx-movie "$(narr $SRC)" --story-id sc_ch_q4 --seed-image $SEED --panels $N --no-review \
  "${EXTRA[@]}" "${Q4[@]}" < /dev/null 2>&1 | stamp > generated/stories/sc_ch_q4/arm.log
```

| Row | Arm | Record | Pass |
|---|---|---|---|
| L1 | A0, today's seeded shots on `qwen21-q4` + uncensored | the report row | the baseline of L2 and L4 |
| L2 | B1 (still mode, seed first) and B2 (still mode, context first) | the report rows; in `arm.log`, `seed context: location changes at panels ...` and one `seed context: panel <n>: Picture ... is the seed ...` line per context panel | CXK7, CXK8, CXK9 and CXK10 (Phase 2) for B1 and for B2, each against A0 |
| L3 | A0-bf16 and B1-bf16 on `qwen2511-bf16` | the report rows | CXK7-CXK10 for B1-bf16 against A0-bf16, or "not run: <reason>" |
| L4 | F1 (frame mode) | the report row; in `arm.log`, per panel the edit, `seed context: panel <k>: its clip (...)` and `seed context: panel <k+1>: the last frame of ...`, in that order | CXK10 (total) against A0; CXK11 against B1 |
| L5 | Ch (chained mode with the Phase 1c seed edit, the one-take seam reference; it writes its own chained story.md from the narrative) | the report row | reference only: B1's and F1's `seam_continuity` next to a one-take movie |
| L6 | reuse and `--redo`, after the report (commands at the end of this section) | B1 rerun: `seed context: 0 panel stills written, <N> reused` and no `seed-edit-child` line; redo: `note: seed context: --redo 2 also re-edits panels ...` (absent when panel 3 is a location change) and only those panels edited; F1 rerun: no edit, and the partial renders print `panel <k>: reusing ...` for every earlier clip | reuse and `--redo` as CX7 describes |

**Judging** (needs `ANTHROPIC_API_KEY`), after every arm has rendered:

```zsh
for id in sc_a0_q4 sc_b1_q4 sc_b2_q4 sc_f1_q4 sc_a0_bf16 sc_b1_bf16 sc_ch_q4; do
  bin/judge-stills --story-id $id; bin/judge-clips --story-id $id; done
```

Then, per arm, score every panel 1-10 for "the same person as the seed" (open `$SEED` beside `images/panel_NN.png`; for Ch, beside `images/panel_01.png` and `clips/panel_02.chainseed.png` .. `clips/panel_NN.chainseed.png`) and write the scores, one per line in panel order, to `generated/stories/<id>/identity.txt`. `bin/judge-clips` has no identity score; its per-clip `temporal_stability` (identity drift inside a clip) is reported as a secondary number.

**Report script.** Run it in `qwen-agent-workspace` with `$N` (the panel count every arm ran with) first, then the arms as `NAME=story-id` (`A0`, `B1`, `B2`, `F1`, `Ch`, and the `-bf16` names; an arm named `X-bf16` is compared with `A0-bf16`):

```bash
python3 - $N A0=sc_a0_q4 B1=sc_b1_q4 B2=sc_b2_q4 F1=sc_f1_q4 Ch=sc_ch_q4 A0-bf16=sc_a0_bf16 B1-bf16=sc_b1_bf16 <<'EOF'
import json
import os
import re
import sys

ROOT = os.path.join("generated", "stories")
N = int(sys.argv[1])                                    # the panel count every arm ran with (--panels $N)
ARMS = dict(a.split("=", 1) for a in sys.argv[2:])     # e.g. A0=sc_a0_q4 B1=sc_b1_q4 ... A0-bf16=sc_a0_bf16
DONE_RE = re.compile(r"^DONE: all (\d+) panels completed -> (.*)$")     # bin/ltx-mlx-render, echoed by Phase 4
TIMEOUT_TEXT = "child timed out after"                                    # qwen_edit.run_jobs's failure text


def load(story, name):
    try:
        with open(os.path.join(ROOT, story, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def log_lines(story):
    """(timestamp, text) of every line of arm.log (the timestamping pipe writes "<epoch seconds> <line>")."""
    out = []
    try:
        with open(os.path.join(ROOT, story, "arm.log"), encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r"^(\d+\.\d) (.*)$", line.rstrip("\n"))
                if m:
                    out.append((float(m.group(1)), m.group(2)))
    except OSError:
        pass
    return out


def edits(story):
    """(record file, entries): seed_context_edits.json (B and F arms, one child per panel), seed_edits.json (A0, one
    child for every panel) or seed_edit.json (Ch, Phase 1c's single edit)."""
    for name in ("seed_context_edits.json", "seed_edits.json"):
        record = load(story, name)
        if isinstance(record, dict) and isinstance(record.get("panels"), list):
            return name, record["panels"]
    record = load(story, "seed_edit.json")
    return ("seed_edit.json", [record]) if isinstance(record, dict) else (None, [])


def incomplete(story, name, entries, lines):
    """Why the arm did not finish ([] when it did): movie.mp4 must exist, arm.log must hold Phase 4's
    "DONE: all <N> panels completed -> <story>/movie.mp4" (a frame-mode partial render's DONE line names upto.mp4 and
    does not count), and the record must hold one ok entry per panel 1..N (Ch: its one Phase 1c entry)."""
    reasons = []
    if not os.path.isfile(os.path.join(ROOT, story, "movie.mp4")):
        reasons.append("no movie.mp4")
    movie = os.sep + os.path.join(ROOT, story, "movie.mp4")
    if not any(m and int(m.group(1)) == N and m.group(2).endswith(movie)
               for m in (DONE_RE.match(text) for _t, text in lines)):
        reasons.append("no 'DONE: all %d panels completed -> ...%s' line in arm.log" % (N, movie))
    if name is None:
        reasons.append("no record")
    else:
        want = 1 if name == "seed_edit.json" else N
        numbers = sorted(e.get("n") or 0 for e in entries) if name != "seed_edit.json" else None
        if (len(entries) != want or any(e.get("status") != "ok" for e in entries)
                or numbers not in (None, list(range(1, N + 1)))):
            reasons.append("%s: %d entries, statuses %s (want %d, all ok)"
                           % (name, len(entries), ",".join(str(e.get("status")) for e in entries), want))
    return reasons


def identity(story):
    """(mean, least-squares slope per panel) of identity.txt: the user's 1-10 'same person as the seed' score of
    every panel, one number per line in panel order."""
    try:
        with open(os.path.join(ROOT, story, "identity.txt"), encoding="utf-8") as f:
            scores = [float(x) for x in f.read().split()]
    except (OSError, ValueError):
        return None, None
    if not scores:
        return None, None
    n, mean = len(scores), sum(scores) / len(scores)
    if n < 2:
        return mean, None
    mx = (n + 1) / 2.0
    slope = (sum((x - mx) * (y - mean) for x, y in zip(range(1, n + 1), scores))
             / sum((x - mx) ** 2 for x in range(1, n + 1)))
    return mean, slope


def row(arm, story):
    lines = log_lines(story)
    stamps = dict()
    for t, text in lines:
        for key, head in (("p2", "=== Phase 2"), ("p3", "=== Phase 3")):
            if key not in stamps and text.startswith(head):
                stamps[key] = t
    name, entries = edits(story)
    reasons = incomplete(story, name, entries, lines)
    seconds = [e["seconds"] for e in entries if isinstance(e.get("seconds"), (int, float))]
    peaks = [float(x) for _t, text in lines for x in re.findall(r"seed-edit-child: mlx peak memory ([0-9.]+) GiB", text)]
    stills = (load(story, "stills_judgment.json") or {}).get("scores") or {}
    clips = load(story, "clips_judgment.json") or {}
    stability = [c["temporal_stability"] for c in clips.get("clips") or [] if "temporal_stability" in c]
    mean, slope = identity(story)
    return {
        "arm": arm, "story": story, "record": name, "complete": not reasons, "incomplete": reasons,
        "status": [e.get("status") for e in entries],
        "context": [((e.get("context") or {}).get("kind") or "-") for e in entries],
        "edit_s_total": round(sum(seconds), 1) if seconds else None,
        "edit_s_mean": round(sum(seconds) / len(seconds), 1) if seconds else None,
        "timed_out": [e.get("n") for e in entries if TIMEOUT_TEXT in str(e.get("error") or "")],
        "timed_out_log_lines": sum(1 for _t, text in lines if TIMEOUT_TEXT in text),
        "peak_gib_max": max(peaks) if peaks else None,
        "peak_kind": (None if not peaks else "per-panel child" if name == "seed_context_edits.json"
                      else "cumulative peak of one child"),
        "phase2_s": round(stamps["p3"] - stamps["p2"], 1) if "p2" in stamps and "p3" in stamps else None,
        "total_s": round(lines[-1][0] - lines[0][0], 1) if lines else None,
        "prompt_fidelity": stills.get("prompt_fidelity"), "visual_continuity": stills.get("visual_continuity"),
        "rendering_quality": stills.get("rendering_quality"),
        "seam_continuity": (clips.get("movie") or {}).get("seam_continuity"),
        "temporal_stability_mean": round(sum(stability) / len(stability), 2) if stability else None,
        "identity_mean": round(mean, 2) if mean is not None else None,
        "identity_slope": round(slope, 3) if slope is not None else None}


rows = dict((arm, row(arm, story)) for arm, story in ARMS.items())
for r in rows.values():
    print(json.dumps(r))


def check(label, arms, ok, *values):
    """One KPI line. n/a (incomplete) when any arm it reads did not finish, n/a (missing) when a value is absent;
    only then PASS or FAIL."""
    unfinished = [a for a in arms if not rows[a]["complete"]]
    if unfinished:
        print("%-48s n/a (incomplete) %s" % (label, "; ".join("%s: %s" % (a, ", ".join(rows[a]["incomplete"]))
                                                               for a in unfinished)))
    elif any(v is None for v in values):
        print("%-48s n/a (missing: %s)" % (label, ", ".join(str(v) for v in values)))
    else:
        print("%-48s %s %s" % (label, "PASS" if ok() else "FAIL", values))


for arm, r in rows.items():
    base_arm = "A0" + arm[2:] if arm[:2] in ("B1", "B2", "F1") else None
    if base_arm is None:
        continue
    if base_arm not in rows:
        print("%-48s n/a (missing arm %s)" % ("%s against %s" % (arm, base_arm), base_arm))
        continue
    a = rows[base_arm]
    check("%s visual_continuity >= %s + 2" % (arm, base_arm), [arm, base_arm],
          lambda: r["visual_continuity"] >= a["visual_continuity"] + 2, r["visual_continuity"],
          a["visual_continuity"])
    check("%s identity mean >= %s - 0.5" % (arm, base_arm), [arm, base_arm],
          lambda: r["identity_mean"] >= a["identity_mean"] - 0.5, r["identity_mean"], a["identity_mean"])
    check("%s identity slope >= -0.1 per panel" % arm, [arm], lambda: r["identity_slope"] >= -0.1,
          r["identity_slope"])
    check("%s rendering_quality >= %s - 1" % (arm, base_arm), [arm, base_arm],
          lambda: r["rendering_quality"] >= a["rendering_quality"] - 1, r["rendering_quality"],
          a["rendering_quality"])
    if arm.startswith("F1"):
        check("%s total wall clock <= 1.5 x %s" % (arm, base_arm), [arm, base_arm],
              lambda: r["total_s"] <= 1.5 * a["total_s"], r["total_s"], a["total_s"])
        still_arm = "B1" + arm[2:]
        if still_arm in rows:
            b = rows[still_arm]
            check("%s seam_continuity >= %s + 1.5 (frame worth it)" % (arm, still_arm), [arm, still_arm],
                  lambda: r["seam_continuity"] >= b["seam_continuity"] + 1.5, r["seam_continuity"],
                  b["seam_continuity"])
    else:
        check("%s Phase 2 wall clock <= 2.5 x %s" % (arm, base_arm), [arm, base_arm],
              lambda: r["phase2_s"] <= 2.5 * a["phase2_s"], r["phase2_s"], a["phase2_s"])


for arm, r in rows.items():
    if r["timed_out"] or r["timed_out_log_lines"]:      # a recorded timeout fails CXK12 whether or not the arm finished
        print("%-48s FAIL %s" % ("%s no child timed out" % arm,
                                 (r["record"], r["timed_out"], r["timed_out_log_lines"])))
    else:
        check("%s no child timed out" % arm, [arm], lambda: True, r["record"])
EOF
```

It prints one JSON row per arm, then one PASS/FAIL/n-a line per KPI.

**Completion gate (A2).** An arm's row has `complete` true only when all three hold, and `incomplete` lists the ones that fail: (1) `generated/stories/<id>/movie.mp4` exists; (2) `arm.log` holds Phase 4's completion line `DONE: all <N> panels completed -> <...>/generated/stories/<id>/movie.mp4`, which `bin/ltx-mlx-render` prints (`:1184`) only when every panel completed and the movie was written, and which `phase4_render`'s `_stream_and_tee` echoes into `bin/ltx-movie`'s stdout (`bin/ltx-movie` prints no completion line of its own; with skip, a run that lost a panel prints `STOPPED EARLY: <c>/<N> panels completed` and may still write a shorter `movie.mp4`, and a frame-mode partial render prints the same `DONE:` words for `seed_context_edits/upto.mp4`, which does not count); (3) the record holds exactly one `ok` entry for each panel 1..N (`seed_context_edits.json`, `seed_edits.json`; Ch's `seed_edit.json` is one Phase 1c entry, which must be `ok`). Every KPI line that reads an incomplete arm, whether the arm itself, its base arm (`A0` or `A0-bf16`) or, for CXK11, `B1`, prints `n/a (incomplete) <arm>: <reasons>`, never PASS or FAIL: an arm that stopped early has a short wall clock and was judged on a partial movie, which would PASS CXK10 and CXK11 falsely. The one exception is CXK12: `timed_out` (the record entries whose `error` holds `child timed out after`, from `qwen_edit.run_jobs`'s failure text `<label> child timed out after <s> s`, `qwen_edit.py:579`) and `timed_out_log_lines` (the `arm.log` lines holding it: the parent prints that failure in its `Error:` line, so a timeout whose entry a later step cleared or overwrote still counts) make CXK12 FAIL whether or not the arm finished, because a child timeout always stops the run and would otherwise never show; an arm with neither prints PASS when complete and `n/a (incomplete)` otherwise. A missing base arm prints `n/a (missing arm A0)`.

Fixes of the PR #15 L4 script's faults, each tested on synthetic arms during the replay (and the completion gate on synthetic arms by Amendment A2, Section 13): the timeout check matches the exact text `child timed out after` in the record entries' `error` fields and in `arm.log`, never a looser `timed out` (`bin/ltx-movie`'s Phase 1 `Error: qwen-agent timed out after <s>s writing story.md` is not a Qwen edit child); peak memory comes from `arm.log`'s `seed-edit-child: mlx peak memory` lines and is labelled `per-panel child` for B and F arms (one child per panel, each log removed before its child) and `cumulative peak of one child` for A0 (one child for all panels, so each line is a running maximum); only the mflux children print that line, so the `-bf16` rows show `null` peaks; the wall clock comes from the timestamps (`=== Phase 2` to `=== Phase 3`, and first to last line), never from the edit seconds alone; a missing arm or file prints `n/a`, never PASS.

**Last, L6** (after the report: the redo changes B1's stills and record):

```zsh
rerun() { local id=$1 log=$2; shift 2
  bin/ltx-movie "$(narr $SRC)" --story-id $id --shots --seed-image $SEED --panels $N --no-review "${EXTRA[@]}" "$@" \
    < /dev/null 2>&1 | tee generated/stories/$id/$log; }
rerun sc_b1_q4 rerun.log "${Q4[@]}" --seed-context still --force
rerun sc_b1_q4 redo.log "${Q4[@]}" --seed-context still --redo 2 --force
rerun sc_f1_q4 rerun.log "${Q4[@]}" --seed-context frame --force
```

**If L2 fails**, the report shows where: no `visual_continuity` gain means the model ignores Picture 2 (Risk R3: look at B2); a negative identity slope means drift accumulates along the chain (Risk R2); a long Phase 2 means model loads dominate (Risk R1: compare `edit_s_total` with `phase2_s`).

---

## 8. Review focus

1. **The forced cascade and its end (CX7).** A re-edited still re-edits every panel up to the next location change, even when the bytes repeat; the entries of that cascade are cleared before the edit, so an interrupted run is safe (CXT6). The controller's wording was "j+1..N" and "--redo N cascades to N..end"; this spec stops at the next location change, because a location-change panel does not see panel N-1, and the note lists exactly the added panels. Confirm.
2. **The location-change rule (CX4).** The first `The setting is` sentence by character_lib's split; equality after whitespace collapse; `None == None` is "same place". Two pinned locations with identical setting sentences would read as one place. character_lib's split does not end a sentence at a closing quote (`quay." She`), so a quoted setting sentence swallows the next sentence and reads as a change: deterministic and harmless (a single-image edit, today's behaviour).
3. **The prompt (CX3).** Picture numbers in both template styles; "who stands on which side of the frame" is fixed wording, with no code reading sides (out of scope, per the PR #15 review). Kind `none` prompts are byte-identical to A0's.
4. **Exceptions (CX8, CX19).** `on_result` runs inside `run_jobs`, so a fit error is caught as a failed panel; the move into `redo/` and the record writes happen outside the `try`, as in SE15 (an `OSError` there is a traceback, as today).
5. **`--redo` messages.** `phase_redo_shots` still prints "every other panel's still and clip is reused"; Phase 2's note then lists the cascade. In frame mode the cascade's clips re-render (their stills change) and `bin/ltx-mlx-render` overwrites them without archiving, as it does for any changed still today.
6. **Frame mode's manifest and render path (CX15-CX17).** One manifest build with placeholders (a broken story fails before any GPU time); partial manifests verified against the real tool (CXT17); `upto.mp4` deleted around each render; the `movie.mp4` guard up front; two review gates (the frame gate, then Phase 3's unchanged gate, where every clip is reused).
7. **The literal-count pins (Section 0.4).** `_render_tool()` takes `phase4_render`'s render-path literal so that L17f, L46f and RST50 keep counting 4, although frame mode adds a render invocation; the partial render calls `_phase4_flags(args)` (A1; `_seed_context_frame_flags` is gone) so `_render_flags(args)` stays at 4; `_phase3_manifest_cmd` sits after `phase3_manifest` for L17b. The pins are kept, not edited; judge whether that honours their intent (every render goes to `bin/ltx-mlx-render`; Phase 3 and 4 flags come from one helper).
8. **Memory and ordering (CXK5).** The Qwen child has exited before each render (`run_child` waits); `qe.wait_for_memory` before each edit; `_wait_for_avail` before each partial render.
9. **Overhead of the partial renders.** Every partial render starts a Python process, re-screens its k input stills in one content-screen subprocess and re-verifies clips 1..k-1 (ffprobe, sha256): N(N+1)/2 still screens per run. Its render progress lines (`panel <n>: reusing ...`) appear during Phase 2; movie-ui never runs this mode.
10. **Child logs and peak memory (CX8).** One log per panel child, removed before the child; the mflux child prints one peak line per job.
11. **Timeout.** A two-image child gets 3600 s (`jobs_timeout`), the one-image floor; a hang costs at most one hour per panel.
12. **Content safety.** Every output is screened (`ltx_movie_seed_context_edit`; mflux in this process, diffusers in its child); the context pictures are this run's own screened stills or frames of its own clips; the partial renders screen their input stills again, as Phase 4 does.

## 9. Risks the user should know (rulings)

- **R1 Run time.** One Qwen model load per edited panel (A0 loads once). For N panels on `qwen21-q4` that is N loads; CXK10 caps still mode's Phase 2 at 2.5 x A0. Frame mode adds N partial render processes, each with a content screen.
- **R2 Drift along the chain.** Each still is conditioned on the previous one, so blur, grain, colour shift or identity drift can accumulate panel by panel within a scene. The prompt asks for the people from the seed only and nothing but the scene from Picture 2; the identity slope (CXK8) measures it. A location change resets the chain to the seed.
- **R3 Picture binding.** The model may take faces or clothing from the context picture (which shows the same people, edited earlier) or ignore it. B2 measures the order.
- **R4 Aspect.** Picture 1 is the original seed at its own aspect; the still-mode context is 2W x 2H and the frame-mode context W x H, both from Phase 0's seed-derived geometry (snapped to multiples of 64), so the aspects differ by that snap only; each pipeline resizes references by area (inferred, [CR] Section 0.3). The edit canvas is the video size floored to the model's multiple, as A0.
- **R5 The frame is a video frame.** W x H only (e.g. 576 x 320 for a 16:9 seed), possibly motion-blurred and mid-action; the prompt says not to take blur or grain. Frame mode also needs every clip before the next still, so a single slow clip, or a clip that still fails after its one retry (A1), blocks the rest of the run.
- **R6 Location detection.** Only the setting sentence decides; a story whose writer varied the sentence for the same place reads as a change (single-image edit, safe), and one place written with another place's sentence reads as no change (a context picture from the wrong place).
- **R7 Content screen.** A blocked panel stops the run (by design); with the pinned `--image-seed` an unchanged rerun reproduces the block.
- **R8 Memory.** Qwen and LTX alternate per panel in frame mode; `_wait_for_avail` gates each render at `--min-avail-gib` (default 25 GiB) and waits up to `--avail-timeout`.
- **R9 `qwen2511-q4`** is unavailable for this option (refused).

## 10. Amended requirements of earlier specs

| Item | Status |
|---|---|
| [SE] SE8 (Phase 2 of a seeded shots run is `_phase2_shots_seed`) | with `--seed-context still`, Phase 2 is `_phase2_seed_context` (CX10); with `frame`, `phase_seed_context_frames` replaces Phase 2 (CX15) |
| [SE] Section 0.5 "Shots panels conditioned on another panel's still (multi-reference edits)" out of scope | now a test option for seeded shots (this spec) |
| [SHOTS] 5.7 (Phase 3's manifest command) | built by `_phase3_manifest_cmd` (CX16); same command |
| Phase 4's render command | its path comes from `_render_tool()` (CX15); same argv |

## 11. Follow-ups (not in this spec)

- F1 A movie-ui Compose control.
- F2 Skip a frame-mode partial render when clip k is already reusable (run the render tool's reuse check in-process), to cut R1's render overhead on reruns.
- F3 A revisited location gets the last still of its previous scene as its context picture.
- F4 An anchor context (the scene's first still instead of panel N-1) if R2 shows drift.
- F5 Seed plus cast references in one edit ([CR] F2).
- F6 Make the better picture order, and still mode itself, the default after the live checks.
- F7 (review) Task 1's ok-result-plus-failure case: when `run_jobs` returns an `ok` result for the panel and a failure string (the child finished the panel, then exited non-zero or timed out), `_seed_context_edit` records the entry `ok` but the phase reports the panel failed and stops; a rerun reuses that entry. Decide whether such an entry is `failed` or the phase continues.
- F8 (review) Frame-panel reuse is keyed on the extracted `frame_KK.png`'s sha256; key it on the clip's bytes plus the frame index instead, as `build_clip_provenance` keys a clip, so a re-extraction cannot change the key by itself.
- F9 (review) An interrupted frame run leaves `manifest.json` built with `placeholder.png` stills; anything reading it before Phase 3 rebuilds it sees placeholders. Remove or mark it on interruption.
- F10 (review) The extracted frame enters Qwen as Picture 2 without its own content screen (its clip's input still was screened, the frame itself is not): a consistency gap with every other picture this mode feeds a model.
- F11 (review) Test gaps: CXT17 fakes `ltx-story-manifest` rather than running it; CXT15's memory-gate failure is silent (no `Error:` line asserted); CXT16 has no case where clip 2 re-renders.
- F12 (review) A partial render that exits 0 without making clip k goes unnoticed when panel k+1 is a location change (no frame is extracted, so nothing reads clip k until Phase 4): check that `clips/panel_KK.mp4` exists after every partial render.

## 12. Open questions (for after the live checks; none blocks implementation)

1. Confirm Review Focus 1: the cascade stops at the next location change (this spec) rather than running to the last panel.
2. If B1 passes CXK7-CXK10, should `--seed-context still` become the default for seeded shots?
3. If F1 is not worth it (CXK11), keep frame mode as an option or remove it?

---

## 13. Amendments (after the whole-branch review)

The Plan's Old/New blocks and test text below stay as the historical Task 1 and Task 2 commits (`114f801`, `96b51e9`); these amendments override them where they differ, and Sections 0-12 already state the amended behaviour.

### Amendment A1 (post-review fix commit)

- **Finding (must-fix).** Task 2's partial render passed `--on-panel-failure stop` (`_seed_context_frame_flags`). With `stop`, `bin/ltx-mlx-render` sets `stopped_reason = "panel_failure"` on the first failed panel (`:1473-1475`), and `finish_run`'s retry pass runs only when `stopped_reason is None` (`:1098`), so `--retry-failed 1` was silently off in every partial render: one transient failure stopped hours of work without the retry Phase 4 gives every other shots clip.
- **Code.** One code commit after Task 2 (`755d4c4`, "ltx-movie: --seed-context frame renders each clip with Phase 4's flags (skip plus one retry), a failed clip still stops the run (seed context review fix)"), touching only `bin/ltx-movie` and `tests/test_ltx_movie_seed_context_frame.py`. In `bin/ltx-movie`: `_seed_context_frame_flags` is deleted; the partial render's command is `[sys.executable, _render_tool(), upto_json, upto_mp4] + _phase4_flags(args)` (CX17); `phase_seed_context_frames`'s docstring says each partial render uses Phase 4's flags (skip plus one retry) and a clip still failing after the retry makes `bin/ltx-mlx-render` exit non-zero, which stops the run; the dry-run `Frame mode:` line (CX20) reads `... (<manifest_upto.json>; Phase 4's flags: skip plus one retry; logs <render-NN.log>) ... A clip still failing after the retry stops the run. ...` in place of `--on-panel-failure stop` and `A failed clip stops the run.` With skip, only clip k renders per partial render (clips 1..k-1 are reused), the retry pass retries it once, and a clip still failing leaves `completed < len(units)`, so the tool prints `STOPPED EARLY` and exits 1 and frame mode stops with the CX19 render error, exactly as before.
- **Tests.** CXT12 pins `_phase4_flags(fargs)` (`skip`, `--retry-failed 1`, `--resume`) and Phase 4's unchanged argv; CXT13 expects `_phase4_flags(args)` in every partial render command; CXT17 expects `on_panel_failure` `skip` with `stopped_reason` `None` in the three partial summaries; CXT18 pins the new `Frame mode:` line; new CXT20 (Section 6). The new-test count is 20 (CXT1-CXT20: 11 in `tests/test_ltx_movie_seed_context.py`, 9 in `tests/test_ltx_movie_seed_context_frame.py`).
- **Numstat.** The fix commit alone: `bin/ltx-movie` `6 12`, `tests/test_ltx_movie_seed_context_frame.py` `77 12`. `bin/ltx-movie` from `29e3a89`: `569 25` (was `575 25`); from Task 1's commit: `194 30` (Task 2 alone stays `200 30`).
- **Task 3 and the gate.** Task 3 runs after the fix commit and re-baselines `test_mut26` to THAT commit (the last commit touching `bin/ltx-movie`), not to Task 2's. Its gate expects `2 failed, P0+20 passed, 2 skipped` with P0 = 2698 (both test files included) and `new tests 20, not passing 0`. The mutation "frame `stop` policy" (Section 6) no longer applies; this amendment did not re-run `$S/sc-tools/mutate.py`.

### Amendment A2 (the report script's completion gate)

Section 7's report script takes `$N` first and gates every arm on completion (Section 7, "Completion gate"): `movie.mp4` exists, `arm.log` holds Phase 4's `DONE: all <N> panels completed -> .../<id>/movie.mp4` line, and the record holds N `ok` entries (Ch: its one `ok` Phase 1c entry). A KPI reading an incomplete arm prints `n/a (incomplete)`; CXK12 also counts `arm.log` lines holding `child timed out after` and FAILs on any timeout. Proved on synthetic arms (N = 4) in `$S/sc-report` (`make_arms.py` writes them, `report_from_spec.py` is the script extracted from this spec): a complete A0 and B1 give PASS lines; F1 stopped at panel 3's clip with a short total, two partial `DONE: all 1/2 panels completed -> .../upto.mp4` lines and no `movie.mp4` (the old script printed PASS for its wall clock and seam KPIs) prints `n/a (incomplete)` on every KPI; B2 with a timed-out panel-2 child prints `n/a (incomplete)` on its comparisons and FAIL on CXK12; B1-bf16 with every entry `ok` but an `Error: ... failed` line and no `DONE` line (the old script printed PASS on four KPIs) prints `n/a (incomplete)`; with an A0 that printed `STOPPED EARLY: 3/4` and wrote a short `movie.mp4`, every KPI of the complete B1 prints `n/a (incomplete) A0: ...`.

### Amendment A3 (the live-check precondition)

Section 7's dry run is saved to `generated/stories/sc_dry/dry-run.txt`, and an `awk` line derives the number of context panels and the longest same-place run from its `Location changes (single-image edits):` line (no code change: the dry run prints no per-panel kinds). The live checks need at least one location change, at least 3 context panels and ideally a same-place run of at least 3 panels.

### Amendment A9 (`stamp()`)

`stamp()` reads stdin through `io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")`, so one non-UTF-8 byte from a child becomes U+FFFD instead of a `UnicodeDecodeError` that kills the pipe (and with it `bin/ltx-movie`, on its next write, by `SIGPIPE`).

---

## Plan

**House rules** (every task):
- Work only in `$S/sc-wt`. Never touch `/Users/reubenpatterson/local_agent_harness`.
- Never stash, reset, amend, push or open a PR. Never access macstudio (no ssh, scp or reading its files).
- Never contact a server, render, run a model, ssh to any host, or run tests against the real HOME.
- Edit tracked files with the Edit or Write tool. Each Edit's old text occurs exactly once in the file at the time it is applied. If it does not, stop and report.
- Every changed `.py` file and both new test files compile on `/usr/bin/python3` (3.9) and `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`.
- Stage only the paths the task names, and check `git diff --cached --name-only` before every commit.
- End each commit with a second `-m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`.

**Replay.**
- Every step below was replayed in scratch copies of the worktree at `29e3a89` (rsync without `.git`): `$S/sc-base` (untouched), `$S/sc-t1` (Task 1 only), `$S/sc-replay` and `$S/sc-check` (Tasks 1 and 2).
- Task 1's file gave `10 failed, 1 passed` before its edits and `11 passed` after. Task 2's file gave `3 failed, 5 errors` before its edits (with Task 1 in place) and, with Task 1's file, `19 passed` after.
- Every Old/New block below was applied by script, in order, to a fresh copy (`$S/sc-check2`) with each Old occurring exactly once (also with its trailing newline removed), and the result was byte-identical to the replayed files.
- `git diff --no-index --numstat` gave `bin/ltx-movie` `381 1` (Task 1), `200 30` (Task 2 alone), `575 25` (both), and `8 4` for Task 2's edits to `tests/test_ltx_movie_seed_context.py`.
- Both Pythons compiled `bin/ltx-movie`, both test files and the report script. The full-suite replay is in "Replay result" at the end.
- These replay results are Tasks 1 and 2 as written; Section 13 records the post-review fix commit (A1), its counts and the re-proved report script (A2).

### Before Task 1: the snapshot, the baseline and the gate files (controller)

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/sc-baseline; mkdir -p $D
cd $S/sc-wt/qwen-agent-workspace
git branch --show-current                                     # seed-context
git diff --stat 29e3a89 HEAD -- . ':(exclude)docs' | tail -1  # no output (only this spec is committed)
git status --short                                            # no output
wc -l bin/ltx-movie tests/test_movie_ui_builder.py            # 3664, 302
ls -l $S/snapshot-pre-sc-29e3a89.tgz || tar czf $S/snapshot-pre-sc-29e3a89.tgz --exclude generated -C $S/sc-wt qwen-agent-workspace
df -g . | tail -1                                             # at least 5 GiB free
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1; tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
grep -c '^PASSED ' $D/baseline-pytest.txt                     # record as P0
for f in tests/test_ltx_movie_offline.py tests/test_qwen_agent_image_oneshot.py tests/test_qwen_agent_danger_auto_approve.py tests/test_qwen_agent_context_budget.py tests/test_qwen_agent_session_memory.py; do echo "$f $(python3 -B $f 2>&1 | tail -1)"; done > $D/baseline-ok-lines.txt
grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $D/baseline-pytest.txt   # 1
```

Expected:
- The summary is `2 failed, 2698 passed, 2 skipped`: the shots-multiref Task 3 result (`$S/mr-baseline/task-3-pytest.txt`), on a tree identical to `29e3a89` (`31cc82e` and `29e3a89` have no diff).
- The only `FAILED` lines are `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`. There is no `ERROR` line, and `test_mut26` passes.
- `baseline-ok-lines.txt` holds `OK 347/347`, `OK 25/25`, `OK 57/57`, `OK 68/68`, `OK 205/205`.

If `test_tr27_fanout_two_rounds_and_missing_reasons`, `test_trt45_query_endpoints_refuse_browsers_and_bad_queries` or `test_trt46_post_spans_validation_cap_and_store` also fails, rerun the three alone; `3 passed` means the baseline stands (the replay's untouched copy saw `test_trt46` fail once in the full run and pass alone: a daemon start-up flake). Any other difference: stop and report.

Then write the gate files (scratch, never staged) from the shots-multiref plan's:

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/sc-baseline
python3 - "$S/mr-baseline/gate.py" "$D/gate.py" <<'EOF'
import sys
s = open(sys.argv[1], encoding="utf-8").read()
old = 'NEW_FILES = ("tests/test_qwen_edit_cast_refs.py::", "tests/test_ltx_movie_cast_refs.py::",)'
assert s.count(old) == 1, old
s = s.replace(old, 'NEW_FILES = ("tests/test_ltx_movie_seed_context.py::", "tests/test_ltx_movie_seed_context_frame.py::")')
open(sys.argv[2], "w", encoding="utf-8").write(s)
EOF
sed -e 's#/mr-baseline#/sc-baseline#' -e 's#/mr-wt/#/sc-wt/#' \
    -e 's#test_trt45_query_endpoints_refuse_browsers_and_bad_queries 2>&1#test_trt45_query_endpoints_refuse_browsers_and_bad_queries tests/test_fleet_tracing.py::test_trt46_post_spans_validation_cap_and_store 2>\&1#' \
    $S/mr-baseline/gate-run.sh > $D/gate-run.sh; chmod +x $D/gate-run.sh
cat > $D/expected-failures.txt <<'EOF'
# seeded shots context plan: baseline passes allowed to be lost. Columns: first task, last task, test id, note
1 2 tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged bin/ltx-movie changes in Tasks 1 and 2; Task 3 moves BASELINE
1 3 tests/test_fleet_tracing.py::test_tr27_fanout_two_rounds_and_missing_reasons flaky timing test; every gate block reruns it alone, where it must pass
1 3 tests/test_fleet_tracing.py::test_trt45_query_endpoints_refuse_browsers_and_bad_queries flaky timing test; every gate block reruns it alone, where it must pass
1 3 tests/test_fleet_tracing.py::test_trt46_post_spans_validation_cap_and_store flaky daemon start-up test; every gate block reruns it alone, where it must pass
EOF
grep -c sc-baseline $D/gate-run.sh; grep -c /sc-wt/ $D/gate-run.sh; grep -c "_seed_context_frame.py::" $D/gate.py; grep -c test_trt46 $D/gate-run.sh   # 1, 1, 1, 1
```

**The gate** for task N is `zsh $S/sc-baseline/gate-run.sh N`: a full `pytest -rA` run of about 20 minutes, compared test by test with the baseline. It prints `disk ok`, the pytest summary, the gate line, `GATE PASS`, `3 passed` for the flake rerun, and `ATK2 OK lines unchanged`. On `GATE STOP`, stop and report the `UNEXPECTED` or `NEW-TEST-FAIL` ids with `python3 -B -m pytest -q -p no:cacheprovider --tb=short <ids>`.

### Task 1: `--seed-context still` in `bin/ltx-movie` (one commit)

**Files:** `bin/ltx-movie` (pinned), `tests/test_ltx_movie_seed_context.py` (new).

- [ ] **Step 1: Write `tests/test_ltx_movie_seed_context.py`** with the Write tool, exactly (the file ends with a single newline after the last line):

```python
"""Tests for bin/ltx-movie's --seed-context still (docs/superpowers/specs/2026-11-10-seeded-shots-context-design.md,
CX1-CX13: CXT1-CXT11): in seeded shots mode every panel after the first is a two-image Qwen edit of the seed and the
previous panel's still, one child per panel in panel order, screened, fitted, recorded in seed_context_edits.json
and reused on a rerun; panel 1 and every location change (a different Image: setting sentence) stay single-image
edits of the seed.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_ltx_movie_seed_context.py

bin/ltx-movie is loaded with SourceFileLoader, spec_from_loader, module_from_spec and exec_module as ltx_movie_sctx.
The ctx_env fixture sets HOME, HF_HOME and Z_IMAGE_HF_HOME under tmp_path, removes HF_HUB_CACHE and every
SEED_EDIT_* variable, and patches _story_dir to <tmp>/stories/<id> and _qwen_edit to _FakeContextQwenEdit (the
shots seed tests' multi-job fake plus the multi-reference table, a log_path recorder, an event log of the centre
pixel of every source at call time, and an exception to raise). CXT11 uses the real qwen_edit with the stub children
of tests/test_seed_edit_tool.py. No test loads a model, renders, contacts a server or touches port 8177 or 8178.
Stdlib, PIL and pytest.
"""

import argparse
import glob
import hashlib
import importlib.machinery
import importlib.util
import json
import os

import pytest
from PIL import Image

import movie_ui_testutil as mt
import qwen_edit
import test_seed_edit_tool as st
from test_ltx_movie_shots_seed import PANEL_QWENEDIT_STUB, _FakeShotsQwenEdit, _seed1920, _story_md, _write_story
from test_qwen_edit import _bf16_cache, _mflux_ready, env  # noqa: F401

WS = mt.WS
UNC = [{"id": "uncensored", "scale": 1.0}]
SEED_PREFIX = ("Edit this photo into a new shot of the same film. Every person from the photo who appears in the new "
               "shot keeps exactly the same face, hair, skin tone, build and clothing. Change their pose and action, "
               "the place, the background, the lighting, the framing and the camera angle to match the new shot, and "
               "leave out anyone the new shot does not describe. The new shot: ")
CONTEXT_PREFIX = (
    "Make the next shot of the same film from two pictures. Picture 1, the first input image, shows the people: "
    "everyone in the new shot keeps exactly the face, hair, skin tone, build and clothing they have in Picture 1. "
    "Picture 2, the second input image, is the previous moment of this scene: keep its place, background, props, "
    "time of day, lighting, colour palette and who stands on which side of the frame, and take nothing else from it: "
    "not the faces, the clothing, any blur or the grain. Change the pose, the action, the framing and the camera "
    "angle to match the new shot, and leave out anyone the new shot does not describe. The new shot: ")
SWAPPED_PREFIX = (
    "Make the next shot of the same film from two pictures. Picture 2, the second input image, shows the people: "
    "everyone in the new shot keeps exactly the face, hair, skin tone, build and clothing they have in Picture 2. "
    "Picture 1, the first input image, is the previous moment of this scene: keep its place, background, props, "
    "time of day, lighting, colour palette and who stands on which side of the frame, and take nothing else from it: "
    "not the faces, the clothing, any blur or the grain. Change the pose, the action, the framing and the camera "
    "angle to match the new shot, and leave out anyone the new shot does not describe. The new shot: ")
HARBOUR = "The setting is a rain-soaked stone harbour at night, wet cobbles underfoot, under amber lamplight."
MARKET = "The setting is a covered fish market hall at dawn, a wet stone floor, under cold white strip lights."
IMAGES = [HARBOUR + " She stands at the end of the quay facing right; medium shot, eye level.",
          HARBOUR + " She runs along the quay toward the camera; wide shot, low angle.",
          MARKET + " She walks between the fish stalls; medium shot, eye level.",
          MARKET + " She looks down at a crate of silver fish; close-up, high angle."]
STYLE = "Muted teal and amber colour with soft film grain."
SEED = (0, 200, 0)
ENTRY_KEYS = ["n", "status", "created", "label", "source", "source_sha256", "original", "context", "prompt", "seed",
              "width", "height", "still_width", "still_height", "qwen_model", "loras", "steps", "scheduler", "output",
              "still", "still_sha256", "seconds", "error"]
CHANGE_LINE = ("seed context: location changes at panels %s (the Image: setting sentence differs from the previous "
               "panel's): each of them is a single-image edit of the seed, like panel 1")
NONE_CONTEXT = {"kind": "none", "file": None, "sha256": None, "picture": None}


def _load_movie():
    path = os.path.join(WS, "bin", "ltx-movie")
    loader = importlib.machinery.SourceFileLoader("ltx_movie_sctx", path)
    spec = importlib.util.spec_from_loader("ltx_movie_sctx", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


movie = _load_movie()


def _pixel(path):
    with Image.open(path) as img:
        return img.convert("RGB").getpixel((img.width // 2, img.height // 2))


class _FakeContextQwenEdit(_FakeShotsQwenEdit):
    """The shots seed tests' multi-job fake (job n writes colour (0, 0, 40 * n)), plus multi_reference_problem;
    run_jobs records log_path in logs and ("edit", n, [centre pixel of every source at call time]) in events, and
    raises error when it is set."""
    MULTI_REFERENCE_MODEL_IDS = qwen_edit.MULTI_REFERENCE_MODEL_IDS

    def __init__(self):
        _FakeShotsQwenEdit.__init__(self)
        self.multi_reference_problem = qwen_edit.multi_reference_problem
        self.logs, self.events, self.error = [], [], None

    def run_jobs(self, model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None,
                 noun="job"):
        self.logs.append(log_path)
        for job in jobs:
            self.events.append(("edit", job["n"], [_pixel(p) for p in job.get("sources", [job["source"]])]))
        if self.error is not None:
            self.calls["run_jobs"].append({"jobs": [dict(j) for j in jobs]})
            raise self.error
        return _FakeShotsQwenEdit.run_jobs(self, model_id, loras, jobs, width, height, skill, work_dir,
                                           on_result=on_result, noun=noun)


@pytest.fixture
def ctx_env(monkeypatch, tmp_path):
    """The module docstring's environment. Returns {"tmp", "fake"}."""
    tmp = str(tmp_path)
    monkeypatch.setenv("HOME", os.path.join(tmp, "home"))
    for key in list(os.environ):
        if key.startswith("SEED_EDIT_"):
            monkeypatch.delenv(key)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", os.path.join(tmp, "hf"))
    monkeypatch.setenv("Z_IMAGE_HF_HOME", os.path.join(tmp, "zi"))
    fake = _FakeContextQwenEdit()
    monkeypatch.setattr(movie, "_qwen_edit", lambda: fake)
    monkeypatch.setattr(movie, "_story_dir", lambda story_id: os.path.join(tmp, "stories", story_id))
    return {"tmp": tmp, "fake": fake}


def _story(tmp, images=IMAGES, story_id="s1"):
    return _write_story(tmp, story_id, _story_md(images, STYLE))


def _args(tmp, **overrides):
    """A seeded shots run of story s1 at 704x448 (stills 1408x896), image seed 3, qwen21-q4 + uncensored, with
    --seed-context still (seed-first) and the 200x100 green PNG seed <tmp>/seed.png."""
    seed = os.path.join(tmp, "seed.png")
    if not os.path.isfile(seed):
        st.png(seed, (200, 100), SEED)
    values = dict(story_id="s1", seed_image=seed, video_width=704, video_height=448, image_seed=3,
                  seed_edit={"qwen_model": "qwen21-q4", "loras": UNC}, shots=True, redo_panels=[],
                  cast_members=[], location_pins=[], story_engine="robust", no_auto_lora=True, panels=4,
                  force_story=False, global_stills_loras=[], stills_lora_path=None,
                  seed_context={"mode": "still", "order": "seed-first"})
    values.update(overrides)
    return argparse.Namespace(**values)


def _record(story_dir):
    with open(os.path.join(story_dir, "seed_context_edits.json"), encoding="utf-8") as f:
        return json.load(f)


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _still(story_dir, n):
    return os.path.join(story_dir, "images", "panel_%02d.png" % n)


def _edited(fake, since=0):
    """The panel of every run_jobs call from call number since on."""
    return [call["jobs"][0]["n"] for call in fake.calls["run_jobs"][since:]]


def _prompt(n, images=IMAGES, prefix=None):
    if prefix is None:
        prefix = SEED_PREFIX if n in (1, 3) else CONTEXT_PREFIX
    return prefix + images[n - 1] + " " + STYLE


# --- CXT1 (CX2): the option rules ---------------------------------------------------------------------------------

def _parse(*extra):
    args = movie.build_parser().parse_args(["a narrative", "--story-id", "s1"] + list(extra))
    args.seed_edit = None
    return args


def test_cxt1_the_option_rules(ctx_env, capsys):
    tmp = ctx_env["tmp"]
    seed = st.png(os.path.join(tmp, "seed.png"), (64, 64))
    q4 = {"qwen_model": "qwen21-q4", "loras": UNC}
    args = _parse()
    assert (args.seed_context_mode, args.seed_context_order) == (None, None)
    assert movie._resolve_seed_context(args) == 0 and args.seed_context is None
    shots = ["--shots", "--seed-image", seed, "--seed-context", "still"]
    cases = [(("--seed-context-order", "context-first"), None, "Error: --seed-context-order needs --seed-context\n"),
             (("--seed-context", "still"), q4,
              "Error: --seed-context needs --shots: it conditions each seeded shots still on the previous panel\n"),
             (("--shots", "--seed-context", "still"), q4,
              "Error: --seed-context needs --seed-image: every shots still is then a Qwen edit of the seed\n"),
             (tuple(shots + ["--cast-refs-model", "qwen21-q4"]), q4,
              "Error: --seed-context cannot be combined with --cast-refs-model: with a seed image every shots still "
              "is already a Qwen edit of the seed\n"),
             (tuple(shots), None,
              "Error: --seed-context needs --seed-edit-model ID, a Qwen registry edit model (as-is is refused): every "
              "shots still is a Qwen edit of the seed\n"),
             (tuple(shots), {"qwen_model": "qwen2511-q4", "loras": []},
              "Error: --seed-context needs a --seed-edit-model that edits with several pictures; qwen2511-q4 is "
              "refused: " + qwen_edit.MULTI_REFERENCE_REFUSED["qwen2511-q4"] + "\n")]
    for extra, edit, text in cases:
        args = _parse(*extra)
        args.seed_edit = edit
        assert movie._resolve_seed_context(args) == 2, extra
        assert capsys.readouterr() == ("", text), extra
        assert args.seed_context is None
    for model in ("qwen21-q4", "qwen21-q8", "qwen21-bf16", "qwen2511-bf16"):
        args = _parse(*shots)
        args.seed_edit = {"qwen_model": model, "loras": []}
        assert movie._resolve_seed_context(args) == 0
        assert args.seed_context == {"mode": "still", "order": "seed-first"}
    args = _parse(*(shots + ["--seed-context-order", "context-first"]))
    args.seed_edit = q4
    assert movie._resolve_seed_context(args) == 0
    assert args.seed_context == {"mode": "still", "order": "context-first"}
    assert capsys.readouterr() == ("", "")
    base = ["n", "--story-id", "s1", "--dry-run", "--seed-context", "still"]
    for extra, text in (
            (["--shots", "--no-stills"],
             "Error: --shots needs Phase 2's per-panel stills; it cannot be combined with --no-stills\n"),
            (["--shots", "--seed-image", seed],
             "Error: --shots with --seed-image needs --seed-edit-model ID: every panel's still is a Qwen edit of the "
             "seed, so the seed cannot be used as-is\n"),
            (["--shots", "--seed-image", seed, "--seed-edit-model", "as-is"],
             "Error: --shots with --seed-image needs --seed-edit-model ID: every panel's still is a Qwen edit of the "
             "seed, so the seed cannot be used as-is\n"),
            (["--shots", "--seed-image", seed, "--seed-edit-model", "qwen2511-q4"],
             "Error: --seed-context needs a --seed-edit-model that edits with several pictures; qwen2511-q4 is "
             "refused: " + qwen_edit.MULTI_REFERENCE_REFUSED["qwen2511-q4"] + "\n"),
            (["--shots", "--seed-image", seed, "--seed-edit-model", "qwen21-q4", "--cast-refs-model", "qwen21-q4"],
             "Error: --cast-refs-model cannot be combined with --seed-image: with a seed image every shots still is "
             "already a Qwen edit of the seed\n"),
            (["--no-stills"], "Error: --seed-context needs --shots: it conditions each seeded shots still on the "
                              "previous panel\n")):
        assert movie.main(base + extra) == 2, extra
        assert capsys.readouterr().err == text, extra


# --- CXT2 (CX3, CX4, CX5): the setting sentence, the kinds, the prompts and the key --------------------------------

def test_cxt2_the_plan(ctx_env):
    tmp, fake = ctx_env["tmp"], ctx_env["fake"]
    lib = movie._character_lib()
    setting = movie._seed_context_setting
    assert setting(lib, IMAGES[0]) == HARBOUR and setting(lib, IMAGES[2]) == MARKET
    assert setting(lib, "She waits. The setting is  a quay\n at night. Rain falls.") == (
        "The setting is a quay at night.")
    assert setting(lib, "the setting is a quay at dusk. She waits.") == "the setting is a quay at dusk."
    assert setting(lib, "She waits on the quay. Rain falls.") is None
    story_dir = _story(tmp)
    args = _args(tmp)
    error, plan = movie._seed_context_plan(args, fake)
    assert error is None
    assert plan["kinds"] == {1: "none", 2: "still", 3: "none", 4: "still"} and plan["changes"] == [3]
    assert plan["prompts"] == dict((n, _prompt(n)) for n in (1, 2, 3, 4))
    assert (plan["size"], plan["still"], plan["total"], plan["entries"]) == ((704, 448), (1408, 896), 4, {})
    assert plan["base"][2] == dict(qwen_edit.settings("qwen21-q4", UNC), source_sha256=_sha(args.seed_image),
                                   prompt=_prompt(2), seed=3, width=704, height=448, still_width=1408,
                                   still_height=896)
    _error, plan = movie._seed_context_plan(_args(tmp, seed_context={"mode": "still", "order": "context-first"}),
                                            fake)
    assert plan["prompts"] == {1: _prompt(1), 2: _prompt(2, prefix=SWAPPED_PREFIX), 3: _prompt(3),
                               4: _prompt(4, prefix=SWAPPED_PREFIX)}
    one_place = [IMAGES[0], IMAGES[1], HARBOUR + " She sits.", "She stands up. " + HARBOUR]
    _story(tmp, one_place)
    _error, plan = movie._seed_context_plan(args, fake)
    assert (plan["kinds"], plan["changes"]) == ({1: "none", 2: "still", 3: "still", 4: "still"}, [])
    _story(tmp, ["She waits.", "She runs.", HARBOUR + " She sits.", "She stands."])
    _error, plan = movie._seed_context_plan(args, fake)
    assert (plan["kinds"], plan["changes"]) == ({1: "none", 2: "still", 3: "none", 4: "none"}, [3, 4])
    story_md = os.path.join(story_dir, "story.md")
    _write_story(tmp, "s1", _story_md([IMAGES[0], None, IMAGES[2]], STYLE))
    assert movie._seed_context_plan(args, fake) == (
        "panel 2 of %s has no Image: description to edit the seed with" % story_md, None)
    _write_story(tmp, "s1", "# Empty\n\nNo panels.\n")
    assert movie._seed_context_plan(args, fake) == ("%s has no panels to edit the seed into" % story_md, None)
    assert fake.calls["run_jobs"] == [] and not os.path.exists(os.path.join(story_dir, "seed_context_edits.json"))


# --- CXT3 (CX6, CX8, CX10): one child per panel, in order, each context the previous panel's fresh still ---------

def test_cxt3_every_panel_in_order(ctx_env, capsys):
    tmp, fake = ctx_env["tmp"], ctx_env["fake"]
    story_dir = _story(tmp)
    args = _args(tmp)
    assert movie.phase2_stills(args) == 0
    work = os.path.join(story_dir, "seed_context_edits")
    original = os.path.join(story_dir, "seed-original.png")
    stage = lambda n: os.path.join(work, "panel_%02d.pending.png" % n)   # noqa: E731
    output = lambda n: os.path.join(work, "panel_%02d.png" % n)          # noqa: E731
    jobs = [{"n": 1, "seed": 3, "prompt": _prompt(1), "source": original, "stage_path": stage(1),
             "output_path": output(1)},
            {"n": 2, "seed": 3, "prompt": _prompt(2), "source": original, "stage_path": stage(2),
             "output_path": output(2), "sources": [original, _still(story_dir, 1)]},
            {"n": 3, "seed": 3, "prompt": _prompt(3), "source": original, "stage_path": stage(3),
             "output_path": output(3)},
            {"n": 4, "seed": 3, "prompt": _prompt(4), "source": original, "stage_path": stage(4),
             "output_path": output(4), "sources": [original, _still(story_dir, 3)]}]
    assert fake.calls["run_jobs"] == [{"model_id": "qwen21-q4", "loras": UNC, "jobs": [job], "size": (704, 448),
                                       "skill": "ltx_movie_seed_context_edit", "work_dir": work, "noun": "panel"}
                                      for job in jobs]
    assert fake.events == [("edit", 1, [SEED]), ("edit", 2, [SEED, (0, 0, 40)]), ("edit", 3, [SEED]),
                           ("edit", 4, [SEED, (0, 0, 120)])]
    assert fake.logs == [os.path.join(work, "child-%02d.log" % n) for n in (1, 2, 3, 4)]
    assert fake.calls["wait_for_memory"] == [(20.0, "Qwen-Image-2.1 q4", "ltx-movie")] * 4
    with Image.open(original) as img:
        assert (img.format, img.size) == ("PNG", (200, 100))
    record = _record(story_dir)
    assert list(record) == ["schema", "updated", "panels"] and record["schema"] == "ltx-movie.seed-context-edits.v1"
    settings = qwen_edit.settings("qwen21-q4", UNC)
    for n, entry in enumerate(record["panels"], start=1):
        with Image.open(_still(story_dir, n)) as img:
            assert (img.format, img.size, img.getpixel((5, 5))) == ("PNG", (1408, 896), (0, 0, 40 * n))
        assert list(entry) == ENTRY_KEYS
        context = NONE_CONTEXT if n in (1, 3) else {"kind": "still", "file": "images/panel_%02d.png" % (n - 1),
                                                    "sha256": _sha(_still(story_dir, n - 1)), "picture": 2}
        assert dict(entry, created=None) == {
            "n": n, "status": "ok", "created": None, "label": "Qwen-Image-2.1 q4",
            "source": os.path.abspath(args.seed_image), "source_sha256": _sha(args.seed_image),
            "original": "seed-original.png", "context": context, "prompt": _prompt(n), "seed": 3, "width": 704,
            "height": 448, "still_width": 1408, "still_height": 896, "qwen_model": settings["qwen_model"],
            "loras": settings["loras"], "steps": 40, "scheduler": "linear",
            "output": "seed_context_edits/panel_%02d.png" % n, "still": "images/panel_%02d.png" % n,
            "still_sha256": _sha(_still(story_dir, n)), "seconds": 12.5, "error": None}
    assert [len(record["panels"])] == [4]
    for name in ("seed_edits.json", "seed_edits", "redo", os.path.join("images", "images.json")):
        assert not os.path.exists(os.path.join(story_dir, name)), name
    assert capsys.readouterr().out.splitlines() == [
        "=== Phase 2: stills ===", CHANGE_LINE % "3",
        "seed context: %s; 704x448, fitted into 1408x896 stills; seed 3; 4 panels in order, one Qwen child per edited "
        "panel; the seed is Picture 1 and the previous panel's still is Picture 2"
        % qwen_edit.generator_text("qwen21-q4", UNC),
        "seed context: panel 1: a single-image edit of the seed",
        "panel 1 -> %s (seed-context Qwen edit, 12.5s)" % _still(story_dir, 1),
        "seed context: panel 2: Picture 1 is the seed (%s), Picture 2 is panel 1's still (%s)"
        % (original, _still(story_dir, 1)),
        "panel 2 -> %s (seed-context Qwen edit, 12.5s)" % _still(story_dir, 2),
        "seed context: panel 3: a single-image edit of the seed (a location change: its setting sentence differs "
        "from panel 2's)",
        "panel 3 -> %s (seed-context Qwen edit, 12.5s)" % _still(story_dir, 3),
        "seed context: panel 4: Picture 1 is the seed (%s), Picture 2 is panel 3's still (%s)"
        % (original, _still(story_dir, 3)),
        "panel 4 -> %s (seed-context Qwen edit, 12.5s)" % _still(story_dir, 4),
        "seed context: 4 panel stills written, 0 reused"]


# --- CXT4 (CX3, CX6): --seed-context-order context-first swaps the pictures and the prompt -----------------------

def test_cxt4_context_first(ctx_env, capsys):
    tmp, fake = ctx_env["tmp"], ctx_env["fake"]
    story_dir = _story(tmp)
    args = _args(tmp, seed_context={"mode": "still", "order": "context-first"})
    assert movie._phase2_seed_context(args) == 0
    original = os.path.join(story_dir, "seed-original.png")
    job = fake.calls["run_jobs"][1]["jobs"][0]
    assert (job["prompt"], job["source"], job["sources"]) == (
        _prompt(2, prefix=SWAPPED_PREFIX), _still(story_dir, 1), [_still(story_dir, 1), original])
    assert fake.events[1] == ("edit", 2, [(0, 0, 40), SEED])
    assert "sources" not in fake.calls["run_jobs"][2]["jobs"][0]
    entries = _record(story_dir)["panels"]
    assert [e["context"]["picture"] for e in entries] == [None, 1, None, 1]
    out = capsys.readouterr().out.splitlines()
    assert ("seed context: panel 2: Picture 2 is the seed (%s), Picture 1 is panel 1's still (%s)"
            % (original, _still(story_dir, 1))) in out
    assert out[1].endswith("the seed is Picture 2 and the previous panel's still is Picture 1")


# --- CXT5 (CX7): a rerun reuses unchanged panels; a changed still re-edits the panels that see it ---------------

def test_cxt5_reuse_and_the_cascade(ctx_env, capsys):
    tmp, fake = ctx_env["tmp"], ctx_env["fake"]
    story_dir = _story(tmp)
    assert movie._phase2_seed_context(_args(tmp)) == 0
    capsys.readouterr()

    def rerun(images=IMAGES, **overrides):
        """The panels a rerun edits."""
        _story(tmp, images)
        before = len(fake.calls["run_jobs"])
        assert movie._phase2_seed_context(_args(tmp, **overrides)) == 0
        return _edited(fake, before)

    assert rerun() == []
    out = capsys.readouterr().out.splitlines()
    assert out[2:] == ["seed context: panel %d: reusing %s (a recorded edit of the same seed image, context picture, "
                       "prompt, seed and settings)" % (n, _still(story_dir, n)) for n in (1, 2, 3, 4)] + [
        "seed context: 0 panel stills written, 4 reused"]
    old_02 = _sha(_still(story_dir, 2))
    changed = list(IMAGES)
    changed[1] = IMAGES[1] + " Gulls circle overhead."
    assert rerun(changed) == [2]
    (moved,) = glob.glob(os.path.join(story_dir, "redo", "*", "images", "panel_02.png"))
    assert _sha(moved) == old_02
    assert ("seed context: moved %s -> %s (not a recorded edit of this seed image, context picture, prompt, seed and "
            "settings)" % (_still(story_dir, 2), moved)) in capsys.readouterr().out.splitlines()
    assert rerun() == [2]
    first = list(IMAGES)
    first[0] = IMAGES[0] + " Rain falls."
    assert rerun(first) == [1, 2]
    assert rerun() == [1, 2]
    third = list(IMAGES)
    third[2] = IMAGES[2] + " Gulls cry."
    assert rerun(third) == [3, 4]
    assert rerun() == [3, 4]
    capsys.readouterr()
    assert rerun(redo_panels=[1]) == [1, 2]
    assert capsys.readouterr().out.splitlines()[1] == (
        "note: seed context: --redo 1 also re-edits panels 2: their context picture is the previous panel's still, "
        "so it changes with it, up to the next location change")
    assert rerun(redo_panels=[1, 3]) == [1, 2, 3, 4]
    assert "note: seed context: --redo 1,3 also re-edits panels 2,4: " in capsys.readouterr().out
    assert rerun(redo_panels=[2]) == [2]
    assert "--redo" not in capsys.readouterr().out
    assert rerun(seed_context={"mode": "still", "order": "context-first"}) == [2, 4]
    assert rerun() == [2, 4]
    other = st.png(os.path.join(tmp, "seed-red.png"), (200, 100), (200, 0, 0))
    assert rerun(seed_image=other) == [1, 2, 3, 4]
    assert rerun() == [1, 2, 3, 4]
    assert rerun(image_seed=4) == [1, 2, 3, 4]
    assert rerun() == [1, 2, 3, 4]
    Image.new("RGB", (1408, 896), (9, 9, 9)).save(_still(story_dir, 2))
    assert rerun() == [2]
    Image.new("RGB", (1408, 896), (9, 9, 9)).save(_still(story_dir, 1))
    assert rerun() == [1, 2]
    assert rerun(seed_edit={"qwen_model": "qwen21-q8", "loras": []}) == [1, 2, 3, 4]


# --- CXT6 (CX8): a blocked or failed panel stops the phase at that panel, with no fallback and no traceback ------

def test_cxt6_blocked_failed_and_raising_panels(ctx_env, capsys):
    tmp, fake = ctx_env["tmp"], ctx_env["fake"]
    story_dir = _story(tmp)
    story_md = os.path.join(story_dir, "story.md")
    fake.outcomes = {2: "blocked"}
    assert movie._phase2_seed_context(_args(tmp)) == 1
    captured = capsys.readouterr()
    assert captured.err == (
        "Error: the content screen blocked the seed-context Qwen edit (Qwen-Image-2.1 q4) of panel 2 of story s1; the "
        "movie stops here rather than use an unscreened, unedited or text-rendered still. Change that panel's Image: "
        "line in %s, then rerun: every recorded still before it is reused\n" % story_md)
    assert "panel 2 BLOCKED: the content screen blocked the seed-context Qwen edit" in captured.out.splitlines()
    assert _edited(fake) == [1, 2]
    assert [(e["n"], e["status"], e["still"]) for e in _record(story_dir)["panels"]] == [
        (1, "ok", "images/panel_01.png"), (2, "blocked", None)]
    assert [os.path.exists(_still(story_dir, n)) for n in (1, 2, 3, 4)] == [True, False, False, False]
    fake.reset()
    assert movie._phase2_seed_context(_args(tmp)) == 0
    assert _edited(fake) == [1, 2, 2, 3, 4]
    fake.outcomes, fake.failure = {3: "stop"}, "Qwen-Image-2.1 q4 child timed out after 3600 s"
    capsys.readouterr()
    assert movie._phase2_seed_context(_args(tmp, redo_panels=[3])) == 1
    assert capsys.readouterr().err == (
        "Error: the seed-context edit of panel 3 failed: Qwen-Image-2.1 q4 child timed out after 3600 s; the stills "
        "before it are kept, and a rerun continues from panel 3\n")
    assert _edited(fake) == [1, 2, 2, 3, 4, 3]
    assert [(e["n"], e["status"], e["seconds"], e["error"]) for e in _record(story_dir)["panels"]] == [
        (1, "ok", 12.5, None), (2, "ok", 12.5, None),
        (3, "failed", None, "Qwen-Image-2.1 q4 child timed out after 3600 s")]
    assert os.path.isfile(_still(story_dir, 4)) and not os.path.exists(_still(story_dir, 3))
    fake.reset()
    fake.outcomes = {3: "stop"}
    assert movie._phase2_seed_context(_args(tmp)) == 1
    assert "failed: Qwen-Image-2.1 q4 reported no result for panel 3; " in capsys.readouterr().err
    fake.reset()
    text = "only 3.0 GiB available after waiting 600 s; Qwen-Image-2.1 q4 needs 20 GiB; free memory and retry"
    fake.wait_error = qwen_edit.Unavailable(text)
    assert movie._phase2_seed_context(_args(tmp)) == 1
    assert capsys.readouterr().err == ("Error: the seed-context edit of panel 3 failed: %s; the stills before it are "
                                       "kept, and a rerun continues from panel 3\n" % text)
    assert _record(story_dir)["panels"][2]["error"] == text
    fake.reset()
    fake.error = OSError("disk full")
    assert movie._phase2_seed_context(_args(tmp)) == 1
    assert capsys.readouterr().err == ("Error: the seed-context edit of panel 3 failed: OSError: disk full; the stills "
                                       "before it are kept, and a rerun continues from panel 3\n")
    assert [(e["n"], e["status"], e["error"]) for e in _record(story_dir)["panels"]][2] == (
        3, "failed", "OSError: disk full")
    fake.error = None
    fake.interrupt_after = 3
    with pytest.raises(KeyboardInterrupt):
        movie._phase2_seed_context(_args(tmp))
    assert [(e["n"], e["status"]) for e in _record(story_dir)["panels"]] == [(1, "ok"), (2, "ok"), (3, "ok")]
    fake.reset()
    capsys.readouterr()
    before = len(fake.calls["run_jobs"])
    assert movie._phase2_seed_context(_args(tmp)) == 0
    assert _edited(fake, before) == [4]


# --- CXT7 (CX12): without the flag nothing changes ------------------------------------------------------------------

def test_cxt7_without_the_flag(ctx_env, monkeypatch, capsys):
    tmp, fake = ctx_env["tmp"], ctx_env["fake"]
    story_dir = _story(tmp)
    seen = []
    monkeypatch.setattr(movie, "_phase2_shots_seed", lambda args: seen.append(args) or 0)
    args = _args(tmp, seed_context=None)
    assert movie.phase2_stills(args) == 0
    assert seen == [args] and fake.calls["run_jobs"] == []
    assert not os.path.exists(os.path.join(story_dir, "seed_context_edits.json"))
    assert not os.path.exists(os.path.join(story_dir, "seed_context_edits"))
    assert capsys.readouterr().out == "=== Phase 2: stills ===\n"
    for context in (None, {"mode": "still", "order": "seed-first"}):
        seq = argparse.Namespace(no_stills=False, story_server_stop_after_story=True, seed_image="x.png",
                                 story_only=False, shots=True, redo_panels=[], seed_edit={"qwen_model": "qwen21-q4"},
                                 seed_context=context)
        assert [p.__name__ for p in movie._phase_sequence(seq)] == [
            "phase0_seed", "phase1_story", "phase_release_story_server", "phase2_stills", "phase3_manifest",
            "phase4_render"]


# --- CXT8 (CX11): the dry run ---------------------------------------------------------------------------------------

DRY = ("Would edit the seed into every panel's still with %s at 576x320, seed 0, one Qwen child per edited panel, in "
       "panel order: panel 1 and every panel whose Image: setting sentence differs from the previous panel's are "
       "single-image edits of the seed (the shots seed-edit instruction); every other panel is a two-image edit with "
       "the seed as Picture 1 and the previous panel's still as Picture 2 (the seed-context instruction). Each is "
       "prompted by its own Image: text (and the Style: text) from story.md, screened with content safety (skill "
       "ltx_movie_seed_context_edit), fitted (never cropped) into %s at 1152x640 and recorded in %s. Z-Image and "
       "stills LoRAs are not used. A blocked or failed panel stops the run; a rerun reuses every recorded edit whose "
       "context picture is unchanged.")


def _dry(capsys, *extra):
    rc = movie.main(["a narrative", "--story-id", "s1", "--dry-run", "--no-review", "--no-auto-lora"] + list(extra))
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    return captured.out.splitlines()


def test_cxt8_the_dry_run(ctx_env, capsys):
    tmp, fake = ctx_env["tmp"], ctx_env["fake"]
    seed = _seed1920(tmp)
    story_dir = os.path.join(tmp, "stories", "s1")
    flags = ("--shots", "--seed-image", seed, "--seed-edit-model", "qwen21-q4", "--seed-context", "still")
    lines = _dry(capsys, *flags)
    i = lines.index("--- Phase 2: stills ---")
    assert lines[i:i + 5] == [
        "--- Phase 2: stills ---",
        DRY % (qwen_edit.generator_text("qwen21-q4", []), os.path.join(story_dir, "images", "panel_NN.png"),
               os.path.join(story_dir, "seed_context_edits.json")),
        "Panels: decided at Phase 2, from story.md after Phase 1", "", "--- Phase 3: manifest + dry-run ---"]
    swapped = _dry(capsys, *(flags + ("--seed-context-order", "context-first")))
    assert ("with the seed as Picture 2 and the previous panel's still as Picture 1 (the seed-context instruction)"
            in swapped[i + 1])
    _story(tmp)
    args = _args(tmp, seed_image=seed, video_width=576, video_height=320, image_seed=0,
                 seed_edit={"qwen_model": "qwen21-q4", "loras": []})
    assert movie._phase2_seed_context(args) == 0
    third = list(IMAGES)
    third[2] = IMAGES[2] + " Gulls cry."
    _story(tmp, third)
    lines = _dry(capsys, *flags)
    i = lines.index("--- Phase 2: stills ---")
    assert lines[i + 2:i + 5] == ["Location changes (single-image edits): 3", "Panels to edit: 3,4; reused: 1,2", ""]
    lines = _dry(capsys, *(flags + ("--redo", "1", "--panels", "4")))
    assert "Panels to edit: 1,2,3,4; reused: none" in lines
    assert len(fake.calls["run_jobs"]) == 4 and fake.calls["selection_problem"] == []
    assert not os.path.exists(os.path.join(story_dir, "redo"))
    assert _record(story_dir)["panels"][2]["prompt"] == _prompt(3)


# --- CXT9 (CX1, CX13): the help texts and the docstring paragraph ------------------------------------------------

HELP = {
    "--seed-context": (
        "a test option for --shots with --seed-image: every panel after the first is a two-image Qwen edit of the "
        "seed (the people) and the previous panel's still (the scene), one Qwen child per panel in panel order, "
        "recorded in seed_context_edits.json; panel 1 and every panel whose Image: setting sentence differs from the "
        "previous panel's stay single-image edits of the seed. Needs a --seed-edit-model that edits with several "
        "pictures (qwen2511-q4 is refused). See docs/superpowers/specs/2026-11-10-seeded-shots-context-design.md."),
    "--seed-context-order": ("with --seed-context: seed-first (the default) makes the seed Picture 1 and the context "
                             "picture Picture 2; context-first swaps them")}
DOC = ("Seed context (docs/superpowers/specs/2026-11-10-seeded-shots-context-design.md), a test option: in shots mode "
       "with --seed-image, --seed-context still makes every panel after the first a two-image Qwen edit of the seed "
       "(the people) and the previous panel's still (the scene), one Qwen child per panel in panel order, recorded in "
       "seed_context_edits.json; panel 1 and every panel whose Image: setting sentence differs from the previous "
       "panel's stay single-image edits of the seed. Absent, Phase 2 is unchanged. Cast references")


def test_cxt9_the_help_texts_and_the_docstring():
    actions = dict((a.option_strings[0], a) for a in movie.build_parser()._actions if a.option_strings)
    for flag, text in HELP.items():
        assert actions[flag].help == text, flag
    assert actions["--seed-context"].choices == ["still"]
    assert actions["--seed-context-order"].choices == ["seed-first", "context-first"]
    assert DOC in " ".join(movie.__doc__.split())
    with open(os.path.join(WS, "bin", "ltx-movie"), encoding="utf-8") as f:
        text = f.read()
    assert "\nimport re\n" not in text
    for orphan in ("_style_echo_warnings", "_style_content_warnings", "_content_words", "_ECHO_",
                   "_STYLE_BANNED_TOKENS", "require_style"):
        assert orphan not in text, orphan


# --- CXT10 (CX8): the panel order of the edits is the event order -------------------------------------------------

def test_cxt10_each_context_still_exists_before_its_edit(ctx_env, monkeypatch):
    tmp, fake = ctx_env["tmp"], ctx_env["fake"]
    story_dir = _story(tmp, [IMAGES[0], IMAGES[1], HARBOUR + " She sits.", HARBOUR + " She stands."])
    events = []
    real_fit = movie._image_fit

    class _Fit(object):
        def __init__(self, mod):
            self.mod = mod
            self.load_oriented_rgb = mod.load_oriented_rgb

        def fit_letterbox(self, img, width, height):
            events.append(("fit", img.getpixel((0, 0))[2] // 40))
            return self.mod.fit_letterbox(img, width, height)

    monkeypatch.setattr(movie, "_image_fit", lambda: _Fit(real_fit()))
    real_run = fake.run_jobs

    def run_jobs(model_id, loras, jobs, *a, **k):
        events.append(("child", jobs[0]["n"], [os.path.basename(p) for p in jobs[0].get("sources", [])]))
        return real_run(model_id, loras, jobs, *a, **k)

    monkeypatch.setattr(fake, "run_jobs", run_jobs)
    assert movie._phase2_seed_context(_args(tmp)) == 0
    assert events == [("child", 1, []), ("fit", 1), ("child", 2, ["seed-original.png", "panel_01.png"]), ("fit", 2),
                      ("child", 3, ["seed-original.png", "panel_02.png"]), ("fit", 3),
                      ("child", 4, ["seed-original.png", "panel_03.png"]), ("fit", 4)]
    assert fake.events == [("edit", 1, [SEED]), ("edit", 2, [SEED, (0, 0, 40)]), ("edit", 3, [SEED, (0, 0, 80)]),
                           ("edit", 4, [SEED, (0, 0, 120)])]
    assert os.path.isfile(_still(story_dir, 4))


# --- CXT11 (CX8): the real runner: one child per panel, the two sources, every output screened ---------------------

def test_cxt11_the_real_runner(env):
    py, _snapshot, _lora = _mflux_ready(env)
    tmp, mp = env["tmp"], env["mp"]
    mp.setattr(movie, "_qwen_edit", lambda: qwen_edit)
    mp.setattr(movie, "_story_dir", lambda story_id: os.path.join(tmp, "stories", story_id))
    images = IMAGES[:2] + [HARBOUR + " She sits on a bollard; medium shot, eye level."]
    story_dir = _story(tmp, images)
    work = os.path.join(story_dir, "seed_context_edits")
    original = os.path.join(story_dir, "seed-original.png")
    args = _args(tmp, panels=3)
    prompts = [_prompt(1, images), _prompt(2, images), _prompt(3, images, prefix=CONTEXT_PREFIX)]
    assert movie._phase2_seed_context(args) == 0
    calls = st.stub_calls(py)
    assert [[(j["n"], j["prompt"], j["source"], j.get("sources")) for j in c["spec"]["jobs"]] for c in calls] == [
        [(1, prompts[0], original, None)], [(2, prompts[1], original, [original, _still(story_dir, 1)])],
        [(3, prompts[2], original, [original, _still(story_dir, 2)])]]
    assert env["calls"]["safety"] == [{"skill": "ltx_movie_seed_context_edit", "prompt": p, "size": (704, 448)}
                                      for p in prompts]
    for n in (1, 2, 3):
        with open(os.path.join(work, "child-%02d.log" % n), encoding="utf-8") as f:
            assert f.read() == "seed-edit-child done %d 1.0\n" % n
    with open(os.path.join(work, "child-02.log"), "a", encoding="utf-8") as f:
        f.write("an older run's line\n")
    st.stub_config(py, {"red": [3]})
    assert movie._phase2_seed_context(_args(tmp, panels=3, redo_panels=[2])) == 1
    assert [c["spec"]["jobs"][0]["n"] for c in st.stub_calls(py)] == [1, 2, 3, 2, 3]
    with open(os.path.join(work, "child-02.log"), encoding="utf-8") as f:
        assert f.read() == "seed-edit-child done 2 1.0\n"
    assert [e["status"] for e in _record(story_dir)["panels"]] == ["ok", "ok", "blocked"]
    stub = st.qwenedit_stub(env, {"blocked": [2]})
    with open(stub, "w", encoding="utf-8") as f:
        f.write(PANEL_QWENEDIT_STUB)
    _bf16_cache(env)
    mp.setattr(qwen_edit, "avail_gib", lambda: 80.0)
    _story(tmp, images, story_id="s2")
    bf16 = _args(tmp, story_id="s2", panels=3, seed_edit={"qwen_model": "qwen2511-bf16", "loras": []})
    assert movie._phase2_seed_context(bf16) == 1
    s2 = os.path.join(tmp, "stories", "s2")
    calls = st.stub_calls(stub)
    assert [c["spec"]["jobs"] for c in calls] == [
        [{"prompt": _prompt(1, images), "output_path": os.path.join(s2, "seed_context_edits", "panel_01.pending.png"),
          "seed": 3, "width": 704, "height": 448}],
        [{"prompt": _prompt(2, images), "output_path": os.path.join(s2, "seed_context_edits", "panel_02.pending.png"),
          "seed": 3, "width": 704, "height": 448, "images": [os.path.join(s2, "seed-original.png"),
                                                             _still(s2, 1)]}]]
    assert [c["spec"]["skill"] for c in calls] == ["ltx_movie_seed_context_edit"] * 2
    assert [e["status"] for e in _record(s2)["panels"]] == ["ok", "blocked"]
```

- [ ] **Step 2: Check that the new tests fail first.** `python3 -B -m pytest -q -p no:cacheprovider tests/test_ltx_movie_seed_context.py 2>&1 | tail -1` prints `10 failed, 1 passed, ...`; the one pass is `test_cxt7_without_the_flag` (it pins today's behaviour). The failures are AttributeErrors on the new functions, `SystemExit: 2` for the unknown `--seed-context` flag, and assertion errors, never import errors.

- [ ] **Step 3: Nine Edits** (M1-M9 to `bin/ltx-movie`), in this order. Each Old text occurs exactly once at the time it is applied.

**M1** (`bin/ltx-movie`, the docstring paragraph, CX13). Old:
```python
passed to Phase 2 as its --seed-image. Absent, or as-is, the seed is used unchanged.

Cast references
```
New:
```python
passed to Phase 2 as its --seed-image. Absent, or as-is, the seed is used unchanged.

Seed context (docs/superpowers/specs/2026-11-10-seeded-shots-context-design.md), a test option: in shots mode with
--seed-image, --seed-context still makes every panel after the first a two-image Qwen edit of the seed (the people)
and the previous panel's still (the scene), one Qwen child per panel in panel order, recorded in
seed_context_edits.json; panel 1 and every panel whose Image: setting sentence differs from the previous panel's
stay single-image edits of the seed. Absent, Phase 2 is unchanged.

Cast references
```

**M2** (`bin/ltx-movie`, the constants, CX3). Old:
```python
CAST_REFS_LORA_NOTE = ("note: Z-Image stills LoRAs (character, location, catalog and --stills-lora) do not apply to "
                       "the cast-reference panels %s: they are Qwen edits of the two characters' reference stills; "
                       "every other panel keeps its Z-Image stills LoRAs")
```
New:
```python
CAST_REFS_LORA_NOTE = ("note: Z-Image stills LoRAs (character, location, catalog and --stills-lora) do not apply to "
                       "the cast-reference panels %s: they are Qwen edits of the two characters' reference stills; "
                       "every other panel keeps its Z-Image stills LoRAs")
# Seed context (docs/superpowers/specs/2026-11-10-seeded-shots-context-design.md, CX3), a test option: in seeded
# shots mode every panel after the first is a two-image Qwen edit of the seed (the people) and the previous moment
# of the scene, unless its setting sentence changes.
SEED_CONTEXT_SKILL = "ltx_movie_seed_context_edit"
SEED_CONTEXT_SCHEMA = "ltx-movie.seed-context-edits.v1"
SEED_CONTEXT_PREFIX = (
    "Make the next shot of the same film from two pictures. Picture %(people)d, the %(people_nth)s input image, "
    "shows the people: everyone in the new shot keeps exactly the face, hair, skin tone, build and clothing they "
    "have in Picture %(people)d. Picture %(scene)d, the %(scene_nth)s input image, is the previous moment of this "
    "scene: keep its place, background, props, time of day, lighting, colour palette and who stands on which side "
    "of the frame, and take nothing else from it: not the faces, the clothing, any blur or the grain. Change the "
    "pose, the action, the framing and the camera angle to match the new shot, and leave out anyone the new shot "
    "does not describe. The new shot: ")
SEED_CONTEXT_KINDS = {"still": "the previous panel's still"}
SEED_CONTEXT_PICTURES = {"still": "panel %d's still"}
SEED_CONTEXT_CHANGE_NOTE = ("seed context: location changes at panels %s (the Image: setting sentence differs from "
                            "the previous panel's): each of them is a single-image edit of the seed, like panel 1")
SEED_CONTEXT_REDO_NOTE = ("note: seed context: --redo %s also re-edits panels %s: their context picture is %s, so "
                          "it changes with it, up to the next location change")
```

**M3** (`bin/ltx-movie`, the two flags, CX1). Old:
```python
                         help="with --cast-refs-model ID: a registry LoRA of that model's family, 0 < SCALE <= 2 "
                              "(repeatable); none listed means no LoRA")
```
New:
```python
                         help="with --cast-refs-model ID: a registry LoRA of that model's family, 0 < SCALE <= 2 "
                              "(repeatable); none listed means no LoRA")
    parser.add_argument("--seed-context", dest="seed_context_mode", choices=["still"], default=None,
                         help="a test option for --shots with --seed-image: every panel after the first is a "
                              "two-image Qwen edit of the seed (the people) and the previous panel's still (the "
                              "scene), one Qwen child per panel in panel order, recorded in "
                              "seed_context_edits.json; panel 1 and every panel whose Image: setting sentence "
                              "differs from the previous panel's stay single-image edits of the seed. Needs a "
                              "--seed-edit-model that edits with several pictures (qwen2511-q4 is refused). See "
                              "docs/superpowers/specs/2026-11-10-seeded-shots-context-design.md.")
    parser.add_argument("--seed-context-order", dest="seed_context_order", choices=["seed-first", "context-first"],
                         default=None,
                         help="with --seed-context: seed-first (the default) makes the seed Picture 1 and the "
                              "context picture Picture 2; context-first swaps them")
```

**M4** (`bin/ltx-movie`, the resolver, CX2). Old:
```python
def _check_story_locations(args, names):
```
New:
```python
def _resolve_seed_context(args):
    """--seed-context/--seed-context-order (seed context spec CX2): sets args.seed_context to None (off) or
    {"mode": the --seed-context value, "order": "seed-first" | "context-first"}. Returns 0, or 2 after one Error:
    line. Reads no weights: the edit model is --seed-edit-model's, which _resolve_seed_edit has already checked."""
    mode, order = args.seed_context_mode, args.seed_context_order
    args.seed_context = None
    if mode is None:
        if order is not None:
            print("Error: --seed-context-order needs --seed-context", file=sys.stderr)
            return 2
        return 0
    if not args.shots:
        print("Error: --seed-context needs --shots: it conditions each seeded shots still on the previous panel",
              file=sys.stderr)
        return 2
    if not getattr(args, "seed_image", None):
        print("Error: --seed-context needs --seed-image: every shots still is then a Qwen edit of the seed",
              file=sys.stderr)
        return 2
    if getattr(args, "cast_refs_model", None) is not None:
        print("Error: --seed-context cannot be combined with --cast-refs-model: with a seed image every shots still "
              "is already a Qwen edit of the seed", file=sys.stderr)
        return 2
    edit = getattr(args, "seed_edit", None)
    if not edit:
        print("Error: --seed-context needs --seed-edit-model ID, a Qwen registry edit model (as-is is refused): "
              "every shots still is a Qwen edit of the seed", file=sys.stderr)
        return 2
    problem = _qwen_edit().multi_reference_problem(edit["qwen_model"])
    if problem is not None:
        print("Error: --seed-context needs a --seed-edit-model that edits with several pictures; %s is refused: %s"
              % (edit["qwen_model"], problem), file=sys.stderr)
        return 2
    args.seed_context = {"mode": mode, "order": order or "seed-first"}
    return 0


def _check_story_locations(args, names):
```

**M5** (`bin/ltx-movie`, the Phase 2 dispatch, CX10). Old:
```python
        return _phase2_shots_seed(args)       # shots seed edits SE8: every still is a Qwen edit of the seed
```
New:
```python
        if getattr(args, "seed_context", None):
            return _phase2_seed_context(args)     # seed context CX10: each still also sees the previous panel's
        return _phase2_shots_seed(args)       # shots seed edits SE8: every still is a Qwen edit of the seed
```

**M6** (`bin/ltx-movie`, the plan, the reuse rule, the per-panel edit and still-mode Phase 2, CX3-CX10). Old:
```python
def _cast_refs_paths(story_dir):
```
New:
```python
def _seed_context_paths(story_dir):
    """The seed-context edits' files in the story directory (seed context spec CX5)."""
    return {"original": os.path.join(story_dir, "seed-original.png"),
            "record": os.path.join(story_dir, "seed_context_edits.json"),
            "work": os.path.join(story_dir, "seed_context_edits")}


def _seed_context_setting(lib, image):
    """The setting sentence of an Image: text (seed context spec CX4): its first sentence, split as character_lib
    splits sentences, that starts with "The setting is" (character_lib's S12 pattern), with its whitespace collapsed;
    None when it has none."""
    for sentence in lib._SENTENCE_SPLIT_RE.split(image.strip()):
        if lib._SETTING_SENTENCE_RE.match(sentence):
            return " ".join(sentence.split())
    return None


def _seed_context_prompt(order, text):
    """A context panel's edit prompt (seed context spec CX3): SEED_CONTEXT_PREFIX with the seed as Picture 1 and the
    context picture as Picture 2 (order seed-first), or the other way round (context-first), then text."""
    people, scene = (1, 2) if order == "seed-first" else (2, 1)
    nth = {1: "first", 2: "second"}
    return SEED_CONTEXT_PREFIX % {"people": people, "people_nth": nth[people], "scene": scene,
                                  "scene_nth": nth[scene]} + text


def _seed_context_plan(args, qe):
    """Phase 2's seed-context plan, read-only (seed context spec CX5): (error, plan). error is the text of an Error:
    line or None. plan is {"prompts": {n: prompt}, "kinds": {n: "none" or the mode}, "changes": [n], "size": (W, H),
    "still": (SW, SH), "base": {n: the key without its "context" item}, "entries": {n: entry}, "total": the panel
    count}. Panel 1 and every panel whose setting sentence (_seed_context_setting) differs from the previous panel's
    are kind "none", prompted exactly as seeded shots prompts them (SHOTS_SEED_EDIT_PREFIX); the location changes
    are those panels after panel 1. Every other panel is prompted by _seed_context_prompt."""
    paths = _story_paths(args.story_id)
    files = _seed_context_paths(paths["story_dir"])
    model_id, loras = args.seed_edit["qwen_model"], args.seed_edit["loras"]
    mode, order = args.seed_context["mode"], args.seed_context["order"]
    panels = _load_story_panels(paths["story_md"])
    if not panels:
        return "%s has no panels to edit the seed into" % paths["story_md"], None
    for n, p in enumerate(panels, start=1):
        if not p["image"].strip():
            return "panel %d of %s has no Image: description to edit the seed with" % (n, paths["story_md"]), None
    lib = _character_lib()
    images = importlib.machinery.SourceFileLoader(
        "ltx_story_images_for_movie", os.path.join(WS, "bin", "ltx-story-images")).load_module()
    style = images._style_text(panels)
    settings_of = [_seed_context_setting(lib, p["image"]) for p in panels]
    size = _seed_edit_size(args, qe.multiple(model_id))
    still = _still_size(args)
    source_sha256 = _sha256_file(args.seed_image)
    settings = qe.settings(model_id, loras)
    prompts, kinds, base = {}, {}, {}
    for n, p in enumerate(panels, start=1):
        text = images._compose_prompt(p["image"], style)
        kinds[n] = "none" if n == 1 or settings_of[n - 1] != settings_of[n - 2] else mode
        prompts[n] = SHOTS_SEED_EDIT_PREFIX + text if kinds[n] == "none" else _seed_context_prompt(order, text)
        base[n] = dict(settings, source_sha256=source_sha256, prompt=prompts[n], seed=args.image_seed,
                       width=size[0], height=size[1], still_width=still[0], still_height=still[1])
    return None, {"prompts": prompts, "kinds": kinds, "changes": [n for n in sorted(kinds) if n > 1
                                                                  and kinds[n] == "none"],
                  "size": size, "still": still, "base": base,
                  "entries": _shots_seed_entries(files["record"], SEED_CONTEXT_SCHEMA), "total": len(panels)}


def _seed_context_context(args, plan, n, path):
    """The "context" item of panel n's key (seed context spec CX6): {"kind", "file", "sha256", "picture"}. path is
    the context picture's file (unused for kind "none"); file is its path relative to the story directory; sha256 is
    its digest, or None while it does not exist; picture is its picture number."""
    kind = plan["kinds"][n]
    if kind == "none":
        return {"kind": "none", "file": None, "sha256": None, "picture": None}
    return {"kind": kind, "file": os.path.relpath(path, _story_paths(args.story_id)["story_dir"]),
            "sha256": _sha256_file(path) if os.path.isfile(path) else None,
            "picture": 2 if args.seed_context["order"] == "seed-first" else 1}


def _seed_context_reusable(args, plan, n, context, changed):
    """True when panel n's recorded still is reused (seed context spec CX7): n is not a --redo panel; it is kind
    "none" or panel n-1 is not in changed (the panels whose still was edited earlier in this run); its entry is ok
    with every key item equal (the base key plus context); and images/panel_NN.png exists with the entry's
    still_sha256."""
    key = dict(plan["base"][n], context=context)
    entry = plan["entries"].get(n)
    path = os.path.join(_story_paths(args.story_id)["images_dir"], "panel_%02d.png" % n)
    return (n not in set(getattr(args, "redo_panels", None) or [])
            and (context["kind"] == "none" or n - 1 not in changed)
            and isinstance(entry, dict) and entry.get("status") == "ok"
            and all(k in entry and entry[k] == v for k, v in key.items())
            and os.path.isfile(path) and entry.get("still_sha256") == _sha256_file(path))


def _seed_context_cascade(plan, start):
    """The panels after start whose context picture comes from start's still, directly or through each other: start+1,
    start+2, ... up to the next kind "none" panel (seed context spec CX7)."""
    out = []
    n = start + 1
    while n <= plan["total"] and plan["kinds"][n] != "none":
        out.append(n)
        n += 1
    return out


def _seed_context_notes(args, plan):
    """The location-change line and the --redo cascade note (seed context spec CX7, CX10)."""
    if plan["changes"]:
        print(SEED_CONTEXT_CHANGE_NOTE % _panel_list(plan["changes"]))
    redo = getattr(args, "redo_panels", None) or []
    extra = sorted(set(m for r in redo for m in _seed_context_cascade(plan, r)) - set(redo))
    if extra:
        print(SEED_CONTEXT_REDO_NOTE % (_panel_list(redo), _panel_list(extra),
                                        SEED_CONTEXT_KINDS[args.seed_context["mode"]]))


def _seed_context_edit(args, qe, plan, n, path, context, archive):
    """Edit panel n's still (seed context spec CX8): one qwen_edit.run_jobs call with one job, after moving an
    existing images/panel_NN.png into archive and clearing the panel's work files, its child log, its entry and the
    entries of the panels that see its still (_seed_context_cascade), which are edited again after it. A kind "none"
    job edits the seed alone; any other job also carries "sources", the seed and the context picture path in picture
    order. The output is screened, fitted into images/panel_NN.png and recorded. Returns (status, failure): status
    is ok, blocked or failed; failure is the failure text or None. Any Exception (not KeyboardInterrupt or
    SystemExit) raised by the memory wait or the batch becomes a failed entry and a failure text."""
    paths = _story_paths(args.story_id)
    files = _seed_context_paths(paths["story_dir"])
    model_id, loras = args.seed_edit["qwen_model"], args.seed_edit["loras"]
    label = qe.label(model_id)
    entries, total = plan["entries"], plan["total"]
    (width, height), (still_w, still_h) = plan["size"], plan["still"]
    still = os.path.join(paths["images_dir"], "panel_%02d.png" % n)
    if os.path.lexists(still):
        os.makedirs(archive, exist_ok=True)
        moved = os.path.join(archive, os.path.basename(still))
        os.replace(still, moved)
        print("seed context: moved %s -> %s (not a recorded edit of this seed image, context picture, prompt, seed "
              "and settings)" % (still, moved))
    log_path = os.path.join(files["work"], "child-%02d.log" % n)
    for name in ("panel_%02d.png" % n, "panel_%02d.pending.png" % n, os.path.basename(log_path)):
        if os.path.lexists(os.path.join(files["work"], name)):
            os.remove(os.path.join(files["work"], name))
    for m in [n] + _seed_context_cascade(plan, n):
        entries.pop(m, None)
    _write_shots_seed_record(files["record"], entries, total, SEED_CONTEXT_SCHEMA)
    job = {"n": n, "seed": args.image_seed, "prompt": plan["prompts"][n], "source": files["original"],
           "stage_path": os.path.join(files["work"], "panel_%02d.pending.png" % n),
           "output_path": os.path.join(files["work"], "panel_%02d.png" % n)}
    if context["kind"] == "none":
        print("seed context: panel %d: a single-image edit of the seed%s"
              % (n, "" if n == 1 else " (a location change: its setting sentence differs from panel %d's)" % (n - 1)))
    else:
        job["sources"] = [files["original"], path] if context["picture"] == 2 else [path, files["original"]]
        job["source"] = job["sources"][0]
        print("seed context: panel %d: Picture %d is the seed (%s), Picture %d is %s (%s)"
              % (n, 3 - context["picture"], files["original"], context["picture"],
                 SEED_CONTEXT_PICTURES[context["kind"]] % (n - 1), path))
    fit = _image_fit()

    def record_entry(status, seconds, error_text):
        key = dict(plan["base"][n], context=context)
        ok = status == "ok"
        return {"n": n, "status": status, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "label": label, "source": os.path.abspath(args.seed_image), "source_sha256": key["source_sha256"],
                "original": os.path.basename(files["original"]), "context": key["context"], "prompt": key["prompt"],
                "seed": key["seed"], "width": key["width"], "height": key["height"],
                "still_width": key["still_width"], "still_height": key["still_height"],
                "qwen_model": key["qwen_model"], "loras": key["loras"], "steps": key["steps"],
                "scheduler": key["scheduler"],
                "output": "seed_context_edits/panel_%02d.png" % n if ok else None,
                "still": "images/panel_%02d.png" % n if ok else None,
                "still_sha256": _sha256_file(still) if ok else None, "seconds": seconds, "error": error_text}

    def on_result(result):
        if result["status"] == "ok":
            fit.fit_letterbox(fit.load_oriented_rgb(result["output_path"]), still_w, still_h).save(
                still + ".tmp", format="PNG")
            os.replace(still + ".tmp", still)
            print("panel %d -> %s (seed-context Qwen edit, %.1fs)" % (n, still, result["seconds"]))
        else:
            print("panel %d BLOCKED: the content screen blocked the seed-context Qwen edit" % n)
        entries[n] = record_entry(result["status"], result["seconds"], None)
        _write_shots_seed_record(files["record"], entries, total, SEED_CONTEXT_SCHEMA)

    try:
        qe.wait_for_memory(qe.memory_floor(model_id), label, tag="ltx-movie")
        results, failure = qe.run_jobs(model_id, loras, [job], width, height, SEED_CONTEXT_SKILL, files["work"],
                                       log_path=log_path, on_result=on_result, noun="panel")
    except qe.Unavailable as e:
        results, failure = None, str(e)
    except Exception as e:      # seed context CX8: a failed entry and an Error: line, never a traceback
        results, failure = None, "%s: %s" % (type(e).__name__, e)
    status = results[0]["status"] if results else "failed"
    if status not in ("ok", "blocked"):
        status = "failed"
    if status == "failed":
        if failure is None:
            failure = "%s reported no result for panel %d" % (label, n)
        entries[n] = record_entry("failed", None, failure)
        _write_shots_seed_record(files["record"], entries, total, SEED_CONTEXT_SCHEMA)
    return status, failure


def _seed_context_stop(args, plan, n, status, failure, label):
    """The Error: line of a panel that stops the seed-context edits (seed context spec CX8)."""
    paths = _story_paths(args.story_id)
    if failure is not None:
        print("Error: the seed-context edit of panel %d failed: %s; the stills before it are kept, and a rerun "
              "continues from panel %d" % (n, failure, n), file=sys.stderr)
    else:
        print("Error: the content screen blocked the seed-context Qwen edit (%s) of panel %d of story %s; the movie "
              "stops here rather than use an unscreened, unedited or text-rendered still. Change that panel's Image: "
              "line in %s, then rerun: every recorded still before it is reused"
              % (label, n, args.story_id, paths["story_md"]), file=sys.stderr)


def _phase2_seed_context(args):
    """Phase 2 in seeded shots mode with --seed-context still (seed context spec CX10): every panel's still is a Qwen
    edit of the original seed, in panel order, one qwen_edit.run_jobs call (one child) per edited panel: a kind
    "none" panel (panel 1 and every location change) edits the seed alone, every other panel the seed and the
    previous panel's still. A panel is reused by _seed_context_reusable. The first blocked or failed panel stops the
    phase (exit 1), with no fallback."""
    qe = _qwen_edit()
    paths = _story_paths(args.story_id)
    files = _seed_context_paths(paths["story_dir"])
    model_id, loras = args.seed_edit["qwen_model"], args.seed_edit["loras"]
    error, plan = _seed_context_plan(args, qe)
    if error is not None:
        print("Error: %s" % error, file=sys.stderr)
        return 1
    if _shots_seed_lora_note(args):
        print(SHOTS_SEED_LORA_NOTE)
    _seed_context_notes(args, plan)
    (width, height), (still_w, still_h) = plan["size"], plan["still"]
    picture = 2 if args.seed_context["order"] == "seed-first" else 1
    print("seed context: %s; %dx%d, fitted into %dx%d stills; seed %d; %d panels in order, one Qwen child per edited "
          "panel; the seed is Picture %d and %s is Picture %d" % (
              qe.generator_text(model_id, loras), width, height, still_w, still_h, args.image_seed, plan["total"],
              3 - picture, SEED_CONTEXT_KINDS[args.seed_context["mode"]], picture))
    os.makedirs(paths["images_dir"], exist_ok=True)
    os.makedirs(files["work"], exist_ok=True)
    _image_fit().load_oriented_rgb(args.seed_image).save(files["original"], format="PNG")
    archive = os.path.join(paths["story_dir"], "redo", "%s-%d" % (
        time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid()), "images")
    changed, reused = set(), []
    for n in range(1, plan["total"] + 1):
        path = os.path.join(paths["images_dir"], "panel_%02d.png" % (n - 1))
        context = _seed_context_context(args, plan, n, path)
        if _seed_context_reusable(args, plan, n, context, changed):
            reused.append(n)
            print("seed context: panel %d: reusing %s (a recorded edit of the same seed image, context picture, "
                  "prompt, seed and settings)" % (n, os.path.join(paths["images_dir"], "panel_%02d.png" % n)))
            continue
        status, failure = _seed_context_edit(args, qe, plan, n, path, context, archive)
        changed.add(n)
        if failure is not None or status != "ok":
            _seed_context_stop(args, plan, n, status, failure, qe.label(model_id))
            return 1
    print("seed context: %d panel stills written, %d reused" % (len(changed), len(reused)))
    return 0


def _cast_refs_paths(story_dir):
```

**M7** (`bin/ltx-movie`, the dry-run lines, CX11). Old:
```python
def _print_cast_refs_plan(args, cmd):
```
New:
```python
def _print_seed_context_plan(args):
    """Phase 2's dry-run lines in seeded shots mode with --seed-context (seed context spec CX11). Reads; never
    writes."""
    qe = _qwen_edit()
    paths = _story_paths(args.story_id)
    model_id, loras = args.seed_edit["qwen_model"], args.seed_edit["loras"]
    known = isinstance(args.video_width, int)
    size = "%dx%d" % _seed_edit_size(args, qe.multiple(model_id)) if known else "<W>x<H>"
    still = "%dx%d" % _still_size(args) if known else "<2W>x<2H>"
    picture = 2 if args.seed_context["order"] == "seed-first" else 1
    print("Would edit the seed into every panel's still with %s at %s, seed %d, one Qwen child per edited panel, in "
          "panel order: panel 1 and every panel whose Image: setting sentence differs from the previous panel's are "
          "single-image edits of the seed (the shots seed-edit instruction); every other panel is a two-image edit "
          "with the seed as Picture %d and %s as Picture %d (the seed-context instruction). Each is prompted by its "
          "own Image: text (and the Style: text) from story.md, screened with content safety (skill %s), fitted "
          "(never cropped) into %s at %s and recorded in %s. Z-Image and stills LoRAs are not used. A blocked or "
          "failed panel stops the run; a rerun reuses every recorded edit whose context picture is unchanged."
          % (qe.generator_text(model_id, loras), size, args.image_seed, 3 - picture,
             SEED_CONTEXT_KINDS[args.seed_context["mode"]], picture, SEED_CONTEXT_SKILL,
             os.path.join(paths["images_dir"], "panel_NN.png"), still,
             _seed_context_paths(paths["story_dir"])["record"]))
    if args.force_story or not known or not os.path.exists(paths["story_md"]):
        print("Panels: decided at Phase 2, from story.md after Phase 1")
        return
    error, plan = _seed_context_plan(args, qe)
    if error is not None:
        print("Panels: Phase 2 would stop: %s" % error)
        return
    print("Location changes (single-image edits): %s" % (_panel_list(plan["changes"]) or "none"))
    changed, reused = set(), []
    for n in range(1, plan["total"] + 1):
        path = os.path.join(paths["images_dir"], "panel_%02d.png" % (n - 1))
        if _seed_context_reusable(args, plan, n, _seed_context_context(args, plan, n, path), changed):
            reused.append(n)
        else:
            changed.add(n)
    print("Panels to edit: %s; reused: %s" % (_panel_list(sorted(changed)) or "none", _panel_list(reused) or "none"))


def _print_cast_refs_plan(args, cmd):
```

**M8** (`bin/ltx-movie`, the dry-run dispatch, CX11). Old:
```python
        print("--- Phase 2: stills ---")
        _print_shots_seed_plan(args)
```
New:
```python
        print("--- Phase 2: stills ---")
        if getattr(args, "seed_context", None):
            _print_seed_context_plan(args)
        else:
            _print_shots_seed_plan(args)
```

**M9** (`bin/ltx-movie`, the resolver call in main, CX2). Old:
```python
    rc = _resolve_cast_refs(args)
    if rc:
        return rc
```
New:
```python
    rc = _resolve_cast_refs(args)
    if rc:
        return rc
    rc = _resolve_seed_context(args)
    if rc:
        return rc
```

No other line of `bin/ltx-movie` changes.

- [ ] **Step 4: Verify.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/sc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_ltx_movie_seed_context.py 2>&1 | tail -1     # 11 passed
python3 -B -m pytest -q -p no:cacheprovider tests/test_shots_mode.py tests/test_ltx_movie_shots_seed.py tests/test_ltx_movie_seed_edit.py tests/test_ltx_movie_cast_refs.py tests/test_dialogue.py tests/test_casting_pipeline.py tests/test_location_pipeline.py tests/test_movie_ui_builder.py tests/test_movie_ui_shots_seed.py 2>&1 | grep -E '^FAILED|passed|failed'
    # only test_mut26_pipeline_files_are_unchanged fails (expected)
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1      # OK 347/347
git diff --numstat                                             # 381 1 bin/ltx-movie
grep -c "seed_context" bin/ltx-movie                           # 57
grep -c "^import re$" bin/ltx-movie                            # 0
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' bin/ltx-movie tests/test_ltx_movie_seed_context.py; done   # compiled 2, twice
zsh $S/sc-baseline/gate-run.sh 1
```
Expected gate output: the summary `3 failed, P0+10 passed, 2 skipped`; `lost 1 (listed 1, unexpected 0); new tests 11, not passing 0; baseline failures still failing 2 of 2`; `GATE PASS`, `3 passed` and `ATK2 OK lines unchanged`. The single loss is `test_mut26` (`bin/ltx-movie` differs from BASELINE).

- [ ] **Step 5: Commit.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/sc-wt/qwen-agent-workspace
git add bin/ltx-movie tests/test_ltx_movie_seed_context.py
git diff --cached --name-only | wc -l    # 2
git commit -m "ltx-movie: --seed-context still, a test option: in seeded shots mode each panel after the first is a two-image Qwen edit of the seed and the previous panel's still, one child per panel, recorded in seed_context_edits.json; location changes stay single-image edits (seeded-shots-context CX1-CX13, CXT1-CXT11)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

**To ship still mode alone**, skip Task 2 and run Task 3 next (its SHA is then the Task 1 commit; its gate expects `2 failed, P0+11 passed, 2 skipped` and `new tests 11`).

### Task 2: `--seed-context frame` in `bin/ltx-movie` (one commit)

**Files:** `bin/ltx-movie` (pinned), `tests/test_ltx_movie_seed_context_frame.py` (new), `tests/test_ltx_movie_seed_context.py` (three pins of CXT9).

- [ ] **Step 1: Write `tests/test_ltx_movie_seed_context_frame.py`** with the Write tool, exactly (the file ends with a single newline after the last line):

```python
"""Tests for bin/ltx-movie's --seed-context frame (docs/superpowers/specs/2026-11-10-seeded-shots-context-design.md,
CX14-CX20: CXT12-CXT19): Phase 2 makes each still, then its clip (bin/ltx-mlx-render --resume on a manifest of the
panels so far), then extracts the clip's exact last frame as the next panel's context picture; Phases 3 and 4 reuse
every clip.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_ltx_movie_seed_context_frame.py

The module under test is tests/test_ltx_movie_seed_context.py's movie, with its ctx_env fixture and Qwen fake. The
frame fixture adds: _stream_and_tee as a fake that writes manifest.json for a bin/ltx-story-manifest command and,
for a bin/ltx-mlx-render command, writes clips/panel_NN.mp4 whose bytes name the panel's motion, its still's sha256
and a per-panel variant; _ltx_render as a fake module whose extract_last_frame writes a 704x448 PNG whose colour
follows the clip bytes; _wait_for_avail as a recorder. Every fake appends to the Qwen fake's events, so one list holds
the order of every step. CXT16 drives the real bin/ltx-mlx-render main() in-process instead (its generator, probes,
concat and content screen stubbed, as tests/test_ltx_mlx_render.py's _Harness does). No test loads a model, renders,
contacts a server or touches port 8177 or 8178. Stdlib, PIL and pytest.
"""

import builtins
import glob
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import sys
import types

import pytest
from PIL import Image

import movie_ui_testutil as mt
import qwen_edit
from test_ltx_movie_seed_context import (HARBOUR, IMAGES, SEED, _args, _edited, _pixel, _record, _story,  # noqa: F401
                                         ctx_env, movie)

WS = mt.WS
FRAME = {"mode": "frame", "order": "seed-first"}
UNC_LIST = [{"id": "uncensored", "scale": 1.0}]
RENDER_KEYS = dict(frames=145, fps=24, model="M", gemma="G", tile_frames=1, tile_spatial=1, lora_path=None,
                   no_low_ram=False, force=False, panel_timeout=7200, no_stills=False, min_avail_gib=25.0,
                   avail_timeout=1800, no_review=True, speech_delivery="beats", no_narration=False,
                   speech_only=False)


def _frame_args(tmp, **overrides):
    values = dict(RENDER_KEYS, seed_context=FRAME)
    values.update(overrides)
    return _args(tmp, **values)


def _colour(clip):
    with open(clip, "rb") as f:
        data = f.read()
    return (int(os.path.basename(clip)[6:8]) * 40, 100, sum(data) % 251)


@pytest.fixture
def frame_env(ctx_env, monkeypatch):
    """The module docstring's fakes. Returns ctx_env plus {"events", "rc", "variant", "violations", "rendered",
    "uptos", "cmds", "frame_error"}."""
    tmp, fake = ctx_env["tmp"], ctx_env["fake"]
    events = fake.events
    state = {"events": events, "rc": {}, "manifest_rc": [0], "variant": {}, "violations": {}, "rendered": [],
             "uptos": [], "cmds": [], "frame_error": [None]}

    def stream(cmd, log_path):
        state["cmds"].append((list(cmd), log_path))
        story_dir = os.path.join(tmp, "stories", "s1")
        if os.path.basename(cmd[1]) == "ltx-story-manifest":
            images = [cmd[i + 1] for i, word in enumerate(cmd) if word == "--image"]
            events.append(("manifest", len(images)))
            panels = [{"index": i, "image_path": image, "conditioning": "still", "panel_text": "panel %d" % i,
                       "motion_prompt": "motion %d" % i, "num_frames": 145} for i, image in enumerate(images, 1)]
            with open(os.path.join(story_dir, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump({"schema_version": 3, "story_id": "s1", "fps": 24, "panels": panels}, f)
            return state["manifest_rc"][0]
        with open(cmd[2], encoding="utf-8") as f:
            upto = json.load(f)
        k = len(upto["panels"])
        state["uptos"].append(upto)
        events.append(("render", k))
        os.makedirs(os.path.join(story_dir, "clips"), exist_ok=True)
        for p in upto["panels"]:
            with open(p["image_path"], "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
            data = ("%s %s %s" % (p["motion_prompt"], digest, state["variant"].get(p["index"], ""))).encode()
            clip = os.path.join(story_dir, "clips", "panel_%02d.mp4" % p["index"])
            if not os.path.isfile(clip) or open(clip, "rb").read() != data:
                with open(clip, "wb") as f:
                    f.write(data)
                state["rendered"].append(p["index"])
        with open(cmd[3], "wb") as f:
            f.write(b"MOVIE")
        return state["rc"].get(k, 0)

    def extract_last_frame(clip, out_png, frames):
        events.append(("frame", int(os.path.basename(clip)[6:8]), frames))
        if state["frame_error"][0] is not None:
            raise state["frame_error"][0]
        Image.new("RGB", (704, 448), _colour(clip)).save(out_png)
        return []

    def check_chain_seed(png_path, width, height, source_panel):
        events.append(("check", source_panel, (width, height)))
        return state["violations"].get(source_panel, [])

    monkeypatch.setattr(movie, "_stream_and_tee", stream)
    monkeypatch.setattr(movie, "_ltx_render", lambda: types.SimpleNamespace(
        extract_last_frame=extract_last_frame, check_chain_seed=check_chain_seed))
    monkeypatch.setattr(movie, "_wait_for_avail", lambda gib, timeout: events.append(("avail", gib, timeout)) or True)
    return dict(ctx_env, **state)


def _work(tmp, *names):
    return os.path.join(tmp, "stories", "s1", "seed_context_edits", *names)


def _clip(tmp, n):
    return os.path.join(tmp, "stories", "s1", "clips", "panel_%02d.mp4" % n)


# --- CXT12 (CX14, CX15, CX17): the flag, the phase tuple, the render flags and the shared helpers -------------------

def test_cxt12_the_flag_the_phases_and_the_helpers(ctx_env, monkeypatch, capsys):
    tmp = ctx_env["tmp"]
    args = movie.build_parser().parse_args(["n", "--story-id", "s1", "--shots", "--seed-image", "x.png",
                                            "--seed-context", "frame"])
    args.seed_edit = {"qwen_model": "qwen21-q4", "loras": UNC_LIST}
    assert movie._resolve_seed_context(args) == 0 and args.seed_context == FRAME
    seq = dict(no_stills=False, story_server_stop_after_story=True, seed_image="x.png", story_only=False, shots=True,
               redo_panels=[], seed_edit={"qwen_model": "qwen21-q4"}, seed_context=FRAME)
    names = lambda **kw: [p.__name__ for p in movie._phase_sequence(types.SimpleNamespace(**dict(seq, **kw)))]  # noqa
    assert names() == ["phase0_seed", "phase1_story", "phase_release_story_server", "phase_seed_context_frames",
                       "phase3_manifest", "phase4_render"]
    assert names(redo_panels=[2], story_server_stop_after_story=False) == [
        "phase0_seed", "phase1_story", "phase_redo_shots", "phase_seed_context_frames", "phase3_manifest",
        "phase4_render"]
    assert names(story_only=True) == ["phase0_seed", "phase1_story"]
    assert "phase2_stills" in names(seed_context={"mode": "still", "order": "seed-first"})
    fargs = _frame_args(tmp)
    flags = movie._seed_context_frame_flags(fargs)
    phase4 = movie._phase4_flags(fargs)
    assert phase4[phase4.index("--on-panel-failure") + 1] == "skip"
    assert flags == phase4[:phase4.index("--on-panel-failure") + 1] + ["stop"] + phase4[
        phase4.index("--on-panel-failure") + 2:]
    assert "--resume" in flags and movie._phase4_flags(fargs) == phase4
    assert movie._render_tool() == os.path.join(WS, "bin", "ltx-mlx-render")
    _story(tmp)
    rc, cmd = movie._phase3_manifest_cmd(fargs)
    assert rc == 0 and cmd[:2] == [sys.executable, os.path.join(WS, "bin", "ltx-story-manifest")]
    assert cmd[cmd.index("--shots") + 1:cmd.index("--fps")] == movie._shots_image_flags(fargs)
    rc, placeholder_cmd = movie._phase3_manifest_cmd(fargs, ["--image", "P"] * 4)
    assert placeholder_cmd[placeholder_cmd.index("--shots") + 1:placeholder_cmd.index("--fps")] == ["--image", "P"] * 4
    assert [w for w in placeholder_cmd if w != "P"] == [w for w in cmd if not w.endswith(".png")]
    seen = []
    monkeypatch.setattr(movie, "_stream_and_tee", lambda c, log: seen.append((c, log)) or 0)
    monkeypatch.setattr(movie, "_wait_for_avail", lambda gib, timeout: True)
    monkeypatch.setattr(movie, "_report_summary", lambda a, m, d: 0)
    assert movie.phase4_render(fargs) == 0
    story_dir = os.path.join(tmp, "stories", "s1")
    assert seen == [([sys.executable, os.path.join(WS, "bin", "ltx-mlx-render"),
                      os.path.join(story_dir, "manifest.json"), os.path.join(story_dir, "movie.mp4")] + phase4,
                     os.path.join(story_dir, "movie.log"))]



# --- CXT13 (CX15-CX18): still, clip, frame, in that order; the frame is the next panel's context picture ----------

def test_cxt13_the_interleaved_order(frame_env, capsys):
    tmp, fake, events = frame_env["tmp"], frame_env["fake"], frame_env["events"]
    story_dir = _story(tmp)
    args = _frame_args(tmp)
    assert movie.phase_seed_context_frames(args) == 0
    f1, f3 = _work(tmp, "frame_01.png"), _work(tmp, "frame_03.png")
    avail = ("avail", 25.0, 1800)
    assert events == [("manifest", 4),
                      ("edit", 1, [SEED]), avail, ("render", 1), ("frame", 1, 145), ("check", 1, (704, 448)),
                      ("edit", 2, [SEED, _colour(_clip(tmp, 1))]), avail, ("render", 2),
                      ("edit", 3, [SEED]), avail, ("render", 3), ("frame", 3, 145), ("check", 3, (704, 448)),
                      ("edit", 4, [SEED, _colour(_clip(tmp, 3))]), avail, ("render", 4)]
    original = os.path.join(story_dir, "seed-original.png")
    assert [c["jobs"][0].get("sources") for c in fake.calls["run_jobs"]] == [None, [original, f1], None, [original, f3]]
    placeholder = _work(tmp, "placeholder.png")
    with Image.open(placeholder) as img:
        assert (img.size, _pixel(placeholder)) == ((1408, 896), SEED)
    (build, build_log), renders = frame_env["cmds"][0], frame_env["cmds"][1:]
    assert build_log == _work(tmp, "manifest.log")
    assert build[build.index("--shots") + 1:build.index("--fps")] == ["--image", placeholder] * 4
    upto_json, upto_mp4 = _work(tmp, "manifest_upto.json"), _work(tmp, "upto.mp4")
    assert [(c, log) for c, log in renders] == [
        ([sys.executable, os.path.join(WS, "bin", "ltx-mlx-render"), upto_json, upto_mp4]
         + movie._seed_context_frame_flags(args), _work(tmp, "render-%02d.log" % k)) for k in (1, 2, 3, 4)]
    with open(os.path.join(story_dir, "manifest.json"), encoding="utf-8") as f:
        built = json.load(f)["panels"]
    for k, upto in enumerate(frame_env["uptos"], start=1):
        assert upto["panels"] == [dict(p, image_path=os.path.join(story_dir, "images", "panel_%02d.png" % p["index"]))
                                  for p in built[:k]]
    assert frame_env["rendered"] == [1, 2, 3, 4] and not os.path.exists(upto_mp4)
    entries = _record(story_dir)["panels"]
    assert [e["context"] for e in entries] == [
        {"kind": "none", "file": None, "sha256": None, "picture": None},
        {"kind": "frame", "file": "seed_context_edits/frame_01.png", "sha256": _sha(f1), "picture": 2},
        {"kind": "none", "file": None, "sha256": None, "picture": None},
        {"kind": "frame", "file": "seed_context_edits/frame_03.png", "sha256": _sha(f3), "picture": 2}]
    assert not os.path.exists(_work(tmp, "frame_02.png")) and not os.path.exists(_work(tmp, "frame_04.png"))
    out = capsys.readouterr().out.splitlines()
    assert out[:3] == ["=== Phase 2: stills and clips, panel by panel (seed context frame) ===",
                       "seed context: location changes at panels 3 (the Image: setting sentence differs from the "
                       "previous panel's): each of them is a single-image edit of the seed, like panel 1",
                       "seed context: %s; 704x448, fitted into 1408x896 stills; seed 3; 4 panels in order, one Qwen "
                       "child per edited panel; the seed is Picture 1 and the last frame of the previous panel's clip "
                       "is Picture 2" % qwen_edit.generator_text("qwen21-q4", UNC_LIST)]
    assert ("seed context: the manifest, built once with %s as every panel's still until it is made; log: %s"
            % (placeholder, _work(tmp, "manifest.log"))) in out
    assert ("seed context: panel 2: Picture 1 is the seed (%s), Picture 2 is the last frame of panel 1's clip (%s)"
            % (original, f1)) in out
    assert "seed context: panel 1: its clip (bin/ltx-mlx-render --resume on panels 1-1); log: %s" % _work(
        tmp, "render-01.log") in out
    assert "seed context: panel 2: the last frame of %s -> %s" % (_clip(tmp, 1), f1) in out
    assert out[-1] == "seed context: 4 panel stills written, 0 reused; every clip is made, so Phase 4 reuses them all"


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# --- CXT14 (CX19): the guards before any edit: an existing movie, a failed manifest build, no render tool ---------

def test_cxt14_the_guards_before_any_edit(frame_env, monkeypatch, capsys):
    tmp, fake, events = frame_env["tmp"], frame_env["fake"], frame_env["events"]
    story_dir = _story(tmp)
    args = _frame_args(tmp)
    with open(os.path.join(story_dir, "movie.mp4"), "wb") as f:
        f.write(b"old")
    assert movie.phase_seed_context_frames(args) == 2
    assert capsys.readouterr().err == ("Error: %s already exists; pass --force to overwrite\n"
                                       % os.path.join(story_dir, "movie.mp4"))
    assert events == [] and frame_env["cmds"] == []
    os.remove(os.path.join(story_dir, "movie.mp4"))
    frame_env["manifest_rc"][0] = 1
    assert movie.phase_seed_context_frames(args) == 1
    assert capsys.readouterr().err == "Error: ltx-story-manifest exited 1; see %s\n" % _work(tmp, "manifest.log")
    assert fake.calls["run_jobs"] == []
    frame_env["manifest_rc"][0] = 0
    monkeypatch.setattr(movie, "_ltx_render", lambda: (_ for _ in ()).throw(SyntaxError("bad line")))
    assert movie.phase_seed_context_frames(args) == 1
    assert capsys.readouterr().err == ("Error: cannot load %s: SyntaxError: bad line\n"
                                       % os.path.join(WS, "bin", "ltx-mlx-render"))
    assert fake.calls["run_jobs"] == []


# --- CXT15 (CX18, CX19): a blocked still, a failed clip, a bad frame or memory stop the run; the review gate ----

def test_cxt15_still_clip_and_frame_failures(frame_env, monkeypatch, capsys):
    tmp, fake, events = frame_env["tmp"], frame_env["fake"], frame_env["events"]
    story_dir = _story(tmp)
    args = _frame_args(tmp)
    fake.outcomes = {2: "blocked"}
    assert movie.phase_seed_context_frames(args) == 1
    assert "Error: the content screen blocked the seed-context Qwen edit (Qwen-Image-2.1 q4) of panel 2 " in (
        capsys.readouterr().err)
    assert events[-1][:2] == ("edit", 2) and ("render", 2) not in events
    fake.reset()
    del events[:]
    frame_env["rc"][2] = 1
    assert movie.phase_seed_context_frames(args) == 1
    assert capsys.readouterr().err == (
        "Error: ltx-mlx-render exited 1 on panels 1-2, so panel 2's clip is not made; frame mode stops here (see %s); "
        "a rerun reuses every recorded still and finished clip\n" % _work(tmp, "render-02.log"))
    assert events[-1] == ("render", 2) and _edited(fake)[-1] == 2
    frame_env["rc"].clear()
    del events[:]
    frame_env["violations"][1] = ["chain frame %s is degenerate" % _work(tmp, "frame_01.png")]
    assert movie.phase_seed_context_frames(args) == 1
    assert capsys.readouterr().err == ("Error: panel 2's context frame (the last frame of %s): chain frame %s is "
                                       "degenerate\n" % (_clip(tmp, 1), _work(tmp, "frame_01.png")))
    assert events[-1] == ("check", 1, (704, 448))
    frame_env["violations"].clear()
    frame_env["frame_error"][0] = RuntimeError("ffmpeg vanished")
    del events[:]
    assert movie.phase_seed_context_frames(args) == 1
    assert capsys.readouterr().err == ("Error: panel 2's context frame (the last frame of %s): RuntimeError: ffmpeg "
                                       "vanished\n" % _clip(tmp, 1))
    frame_env["frame_error"][0] = None
    monkeypatch.setattr(movie, "_wait_for_avail", lambda gib, timeout: False)
    del events[:]
    assert movie.phase_seed_context_frames(args) == 1
    assert not any(e[0] == "render" for e in events)
    monkeypatch.setattr(movie, "_wait_for_avail", lambda gib, timeout: True)
    prompts = []
    monkeypatch.setattr(builtins, "input", lambda prompt: prompts.append(prompt) or "")
    del events[:]
    assert movie.phase_seed_context_frames(_frame_args(tmp, no_review=False)) == 0
    assert prompts == ["Frame mode renders every panel's clip right after its still, before the next still is "
                       "edited. Enter to start, Ctrl-C to abort: "]
    assert [e["status"] for e in _record(story_dir)["panels"]] == ["ok"] * 4


# --- CXT16 (CX16, CX18): a rerun reuses stills by record and clips by --resume; a changed clip re-edits ------------

def test_cxt16_reruns(frame_env, capsys):
    tmp, fake, events = frame_env["tmp"], frame_env["fake"], frame_env["events"]
    _story(tmp)
    assert movie.phase_seed_context_frames(_frame_args(tmp)) == 0

    def rerun(images=IMAGES, **overrides):
        """(the panels a rerun edits, the clips it renders)."""
        _story(tmp, images)
        before, rendered = len(fake.calls["run_jobs"]), len(frame_env["rendered"])
        del events[:]
        assert movie.phase_seed_context_frames(_frame_args(tmp, **overrides)) == 0
        return _edited(fake, before), frame_env["rendered"][rendered:]

    assert rerun() == ([], [])
    assert [e for e in events if e[0] in ("render", "frame")] == [("render", 1), ("frame", 1, 145), ("render", 2),
                                                                  ("render", 3), ("frame", 3, 145), ("render", 4)]
    assert capsys.readouterr().out.splitlines()[-1] == (
        "seed context: 0 panel stills written, 4 reused; every clip is made, so Phase 4 reuses them all")
    frame_env["variant"][1] = "a new motion"
    assert rerun() == ([2], [1])
    assert rerun() == ([], [])
    first = list(IMAGES)
    first[0] = IMAGES[0] + " Rain falls."
    assert rerun(first) == ([1, 2], [])
    capsys.readouterr()
    assert rerun(first, redo_panels=[3]) == ([3, 4], [])
    assert ("note: seed context: --redo 3 also re-edits panels 4: their context picture is the last frame of the "
            "previous panel's clip, so it changes with it, up to the next location change"
            in capsys.readouterr().out.splitlines())


# --- CXT17 (CX16, CX17): the real bin/ltx-mlx-render accepts the partial manifests and reuses their clips -----------

def _load_render():
    path = os.path.join(WS, "bin", "ltx-mlx-render")
    loader = importlib.machinery.SourceFileLoader("ltx_mlx_render_sctx", path)
    spec = importlib.util.spec_from_loader("ltx_mlx_render_sctx", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_cxt17_the_real_render_tool(ctx_env, monkeypatch, capsys):
    tmp, fake = ctx_env["tmp"], ctx_env["fake"]
    render = _load_render()
    model = os.path.join(tmp, "model-fixture")
    os.makedirs(model)
    with open(os.path.join(model, "split_model.json"), "w") as f:
        json.dump({"recipe": "ltx-2.5"}, f)
    fake_bin = os.path.join(tmp, "fake-ltx")
    with open(fake_bin, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(fake_bin, 0o755)
    generated, screened, frames = [], [], []

    def generate_video(prompt, output_path, image_path=None, **kw):
        generated.append((int(os.path.basename(output_path)[6:8]), kw["seed"], _pixel(image_path)))
        with open(output_path, "wb") as f:
            f.write(b"clip " + prompt.encode())
        return os.path.abspath(output_path)

    def extract_last_frame(clip, out_png, n_frames):
        frames.append((os.path.basename(clip), n_frames))
        Image.new("RGB", (704, 448), (90, 90, 90)).save(out_png)
        return []

    monkeypatch.setattr(render.SKILL, "generate_video", generate_video)
    monkeypatch.setattr(render.SKILL, "LTX2_MLX_BIN", fake_bin)
    monkeypatch.setattr(render, "shutil", types.SimpleNamespace(which=lambda tool: "/usr/bin/" + tool))
    monkeypatch.setattr(render, "probe_streams", lambda p: {"streams": []})
    monkeypatch.setattr(render, "assert_clips_uniform", lambda pairs, w, h, fr: None)
    monkeypatch.setattr(render, "build_concat_command", lambda lp, out: [
        sys.executable, "-c", "import sys; open(sys.argv[1], 'wb').write(b'MOVIE')", out])
    monkeypatch.setattr(render, "clip_frame_count", lambda p: 145)
    monkeypatch.setattr(render, "ffprobe_image_size", lambda p: ((1408, 896), None))
    monkeypatch.setattr(render, "run_input_content_screen", lambda paths: screened.append(len(paths)) or 0)
    monkeypatch.setattr(render, "story_dir_for", lambda story_id: os.path.join(tmp, "stories", story_id))
    monkeypatch.setattr(render, "extract_last_frame", extract_last_frame)
    monkeypatch.setattr(render, "check_chain_seed", lambda png, w, h, source: [])
    story_dir = os.path.join(tmp, "stories", "s1")

    def stream(cmd, log_path):
        if os.path.basename(cmd[1]) == "ltx-story-manifest":
            images = [cmd[i + 1] for i, word in enumerate(cmd) if word == "--image"]
            panels = [{"index": i, "image_path": image, "conditioning": "still", "panel_text": "panel %d" % i,
                       "motion_prompt": "motion %d" % i, "num_frames": 145} for i, image in enumerate(images, 1)]
            with open(os.path.join(story_dir, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump({"schema_version": 3, "story_id": "s1", "fps": 24, "panels": panels}, f)
            return 0
        assert cmd[:2] == [sys.executable, os.path.join(WS, "bin", "ltx-mlx-render")]
        return render.main(cmd[2:])

    monkeypatch.setattr(movie, "_stream_and_tee", stream)
    monkeypatch.setattr(movie, "_ltx_render", lambda: render)
    monkeypatch.setattr(movie, "_wait_for_avail", lambda gib, timeout: True)
    _story(tmp, IMAGES[:2] + [HARBOUR + " She sits on a bollard; medium shot, eye level."])
    args = _frame_args(tmp, panels=3, model=model)
    assert movie.phase_seed_context_frames(args) == 0
    assert generated == [(1, 1, (0, 0, 40)), (2, 2, (0, 0, 80)), (3, 3, (0, 0, 120))]
    assert frames == [("panel_01.mp4", 145), ("panel_02.mp4", 145)]
    assert screened == [1, 2, 3]
    summaries = []
    for path in sorted(glob.glob(os.path.join(story_dir, "runs", "*", "story_summary.json")),
                       key=lambda p: os.path.getmtime(p)):
        with open(path, encoding="utf-8") as f:
            summaries.append(json.load(f))
    assert [(s["requested_units"], s["completed_units"], s["intended_total_frames"], s["actual_total_frames"],
             [u["resumed"] for u in s["units"]], s["on_panel_failure"], s["stopped_reason"]) for s in summaries] == [
        (1, 1, 145, 145, [False], "stop", None), (2, 2, 290, 290, [True, False], "stop", None),
        (3, 3, 435, 435, [True, True, False], "stop", None)]
    assert [e["context"]["kind"] for e in _record(story_dir)["panels"]] == ["none", "frame", "frame"]
    final = _work(tmp, "manifest_upto.json")
    assert render.main([final, os.path.join(story_dir, "movie.mp4")] + movie._phase4_flags(args)) == 0
    assert len(generated) == 3
    del generated[:]
    capsys.readouterr()
    assert movie.phase_seed_context_frames(args) == 2
    assert movie.phase_seed_context_frames(_frame_args(tmp, panels=3, model=model, force=True)) == 0
    assert generated == [] and _edited(fake)[3:] == []
    with open(os.path.join(story_dir, "clips", "panel_02.mp4.provenance.json"), encoding="utf-8") as f:
        assert json.load(f)["image_sha256"] == _sha(os.path.join(story_dir, "images", "panel_02.png"))


# --- CXT18 (CX20): the frame mode's dry run ----------------------------------------------------------------------

def test_cxt18_the_dry_run(frame_env, capsys):
    tmp = frame_env["tmp"]
    from test_ltx_movie_shots_seed import _seed1920
    seed = _seed1920(tmp)
    story_dir = os.path.join(tmp, "stories", "s1")
    base = ["a narrative", "--story-id", "s1", "--dry-run", "--no-review", "--no-auto-lora", "--shots",
            "--seed-image", seed, "--seed-edit-model", "qwen21-q4", "--seed-context"]

    def dry(mode):
        assert movie.main(base + [mode]) == 0
        return capsys.readouterr().out.splitlines()

    still, frame = dry("still"), dry("frame")
    i = frame.index("--- Phase 2: stills ---")
    work = os.path.join(story_dir, "seed_context_edits")
    assert frame[i + 1] == still[i + 1].replace("the previous panel's still", "the last frame of the previous "
                                                                          "panel's clip")
    assert frame[i + 2] == (
        "Frame mode: Phase 2 also renders each panel's clip right after its still, with bin/ltx-mlx-render --resume "
        "on a manifest of the panels so far (%s; --on-panel-failure stop; logs %s), and the exact last frame of clip "
        "k is panel k+1's context picture. A failed clip stops the run. Phases 3 and 4 then build the final manifest "
        "and reuse every clip." % (os.path.join(work, "manifest_upto.json"), os.path.join(work, "render-NN.log")))
    assert frame[i + 3] == "Panels: decided at Phase 2, from story.md after Phase 1"
    assert frame[i + 4:] == still[i + 3:]
    _story(tmp)
    lines = dry("frame")
    assert lines[i + 3:i + 5] == [
        "Location changes (single-image edits): 3",
        "Panels to edit: decided panel by panel during the run: a context picture is the last frame of a clip this "
        "run renders or reuses"]
    assert frame_env["fake"].calls["run_jobs"] == [] and frame_env["cmds"] == []
    assert not os.path.exists(work)


# --- CXT19 (CX14): the help text and the docstring ---------------------------------------------------------------

HELP = ("a test option for --shots with --seed-image: every panel after the first is a two-image Qwen edit of the "
        "seed (the people) and the previous panel's still (the scene), one Qwen child per panel in panel order, "
        "recorded in seed_context_edits.json; panel 1 and every panel whose Image: setting sentence differs from the "
        "previous panel's stay single-image edits of the seed. frame uses the exact last frame of the previous panel's "
        "clip instead, rendering each clip right after its still; a failed still or clip stops the run. Needs a "
        "--seed-edit-model that edits with several pictures (qwen2511-q4 is refused). See docs/superpowers/specs/"
        "2026-11-10-seeded-shots-context-design.md.")
DOC = ("stay single-image edits of the seed. --seed-context frame uses the exact last frame of the previous panel's "
       "clip instead: Phase 2 then renders each clip right after its still (bin/ltx-mlx-render --resume on the panels "
       "so far), and Phases 3 and 4 reuse every clip. Absent, Phase 2 is unchanged. Cast references")


def test_cxt19_the_help_text_and_the_docstring():
    actions = dict((a.option_strings[0], a) for a in movie.build_parser()._actions if a.option_strings)
    assert actions["--seed-context"].help == HELP
    assert actions["--seed-context"].choices == ["still", "frame"]
    assert DOC in " ".join(movie.__doc__.split())
```

- [ ] **Step 2: Check that the new tests fail first.** `python3 -B -m pytest -q -p no:cacheprovider tests/test_ltx_movie_seed_context_frame.py 2>&1 | tail -1` prints `3 failed, 5 errors in ...`: CXT12 (`SystemExit: 2`, `frame` is not a choice yet), CXT17 and CXT19 fail; the five tests that use the `frame_env` fixture error at setup (`movie` has no `_ltx_render`).

- [ ] **Step 3: Thirteen Edits**: F1-F10 to `bin/ltx-movie`, then T1-T3 to `tests/test_ltx_movie_seed_context.py`, in this order. Each Old text occurs exactly once at the time it is applied.

**F1** (`bin/ltx-movie`, the docstring, CX14). Old:
```python
--seed-image, --seed-context still makes every panel after the first a two-image Qwen edit of the seed (the people)
and the previous panel's still (the scene), one Qwen child per panel in panel order, recorded in
seed_context_edits.json; panel 1 and every panel whose Image: setting sentence differs from the previous panel's
stay single-image edits of the seed. Absent, Phase 2 is unchanged.
```
New:
```python
--seed-image, --seed-context still makes every panel after the first a two-image Qwen edit of the seed (the people)
and the previous panel's still (the scene), one Qwen child per panel in panel order, recorded in
seed_context_edits.json; panel 1 and every panel whose Image: setting sentence differs from the previous panel's
stay single-image edits of the seed. --seed-context frame uses the exact last frame of the previous panel's clip
instead: Phase 2 then renders each clip right after its still (bin/ltx-mlx-render --resume on the panels so far),
and Phases 3 and 4 reuse every clip. Absent, Phase 2 is unchanged.
```

**F2** (`bin/ltx-movie`, the frame constants, CX14). Old:
```python
SEED_CONTEXT_KINDS = {"still": "the previous panel's still"}
SEED_CONTEXT_PICTURES = {"still": "panel %d's still"}
```
New:
```python
SEED_CONTEXT_KINDS = {"still": "the previous panel's still",
                      "frame": "the last frame of the previous panel's clip"}
SEED_CONTEXT_PICTURES = {"still": "panel %d's still", "frame": "the last frame of panel %d's clip"}
SEED_CONTEXT_FRAME_GATE = ("Frame mode renders every panel's clip right after its still, before the next still is "
                           "edited. Enter to start, Ctrl-C to abort: ")
```

**F3** (`bin/ltx-movie`, the flag, CX14). Old:
```python
    parser.add_argument("--seed-context", dest="seed_context_mode", choices=["still"], default=None,
                         help="a test option for --shots with --seed-image: every panel after the first is a "
                              "two-image Qwen edit of the seed (the people) and the previous panel's still (the "
                              "scene), one Qwen child per panel in panel order, recorded in "
                              "seed_context_edits.json; panel 1 and every panel whose Image: setting sentence "
                              "differs from the previous panel's stay single-image edits of the seed. Needs a "
                              "--seed-edit-model that edits with several pictures (qwen2511-q4 is refused). See "
                              "docs/superpowers/specs/2026-11-10-seeded-shots-context-design.md.")
```
New:
```python
    parser.add_argument("--seed-context", dest="seed_context_mode", choices=["still", "frame"], default=None,
                         help="a test option for --shots with --seed-image: every panel after the first is a "
                              "two-image Qwen edit of the seed (the people) and the previous panel's still (the "
                              "scene), one Qwen child per panel in panel order, recorded in "
                              "seed_context_edits.json; panel 1 and every panel whose Image: setting sentence "
                              "differs from the previous panel's stay single-image edits of the seed. frame uses the "
                              "exact last frame of the previous panel's clip instead, rendering each clip right "
                              "after its still; a failed still or clip stops the run. Needs a --seed-edit-model "
                              "that edits with several pictures (qwen2511-q4 is refused). See "
                              "docs/superpowers/specs/2026-11-10-seeded-shots-context-design.md.")
```

**F4** (`bin/ltx-movie`, the render tool, the frame flags and the frame-mode Phase 2, CX15-CX19; the frame flags are deleted again by Amendment A1). Old:
```python
def _cast_refs_paths(story_dir):
```
New:
```python
def _render_tool():
    """bin/ltx-mlx-render's path: Phase 4 renders with it, and --seed-context frame renders with it and loads it for
    extract_last_frame and check_chain_seed (seed context spec CX15)."""
    return os.path.join(WS, "bin", "ltx-mlx-render")


def _ltx_render():
    """bin/ltx-mlx-render, loaded by path and only by --seed-context frame (seed context spec CX15)."""
    return importlib.machinery.SourceFileLoader("ltx_mlx_render_for_movie", _render_tool()).load_module()


def _seed_context_frame_flags(args):
    """Phase 4's bin/ltx-mlx-render flags with --on-panel-failure stop (seed context spec CX17): in frame mode a clip
    is the next panel's context, so a failed clip stops the run."""
    flags = _phase4_flags(args)
    flags[flags.index("--on-panel-failure") + 1] = "stop"
    return flags


def phase_seed_context_frames(args):
    """Phase 2 in seeded shots mode with --seed-context frame (seed context spec CX15-CX19), in place of
    phase2_stills: the manifest is built once with a placeholder still for every panel; then, for each panel k in
    order, still k is reused or edited (the context picture of a kind "frame" panel is the exact last frame of clip
    k-1), a manifest of panels 1..k with their real stills is written to seed_context_edits/manifest_upto.json and
    bin/ltx-movie runs bin/ltx-mlx-render --resume on it (clips 1..k-1 are reused, clip k renders), and clip k's last
    frame is extracted and checked when panel k+1 needs it. Phase 3 and Phase 4 then rebuild the manifest and reuse
    every clip. The first blocked or failed still, failed clip or bad frame stops the run, with no fallback."""
    print("=== Phase 2: stills and clips, panel by panel (seed context frame) ===")
    qe = _qwen_edit()
    paths = _story_paths(args.story_id)
    files = _seed_context_paths(paths["story_dir"])
    model_id, loras = args.seed_edit["qwen_model"], args.seed_edit["loras"]
    if os.path.exists(paths["movie_path"]) and not args.force:
        print("Error: %s already exists; pass --force to overwrite" % paths["movie_path"], file=sys.stderr)
        return 2
    error, plan = _seed_context_plan(args, qe)
    if error is not None:
        print("Error: %s" % error, file=sys.stderr)
        return 1
    if _shots_seed_lora_note(args):
        print(SHOTS_SEED_LORA_NOTE)
    _seed_context_notes(args, plan)
    (width, height), (still_w, still_h) = plan["size"], plan["still"]
    picture = 2 if args.seed_context["order"] == "seed-first" else 1
    total = plan["total"]
    print("seed context: %s; %dx%d, fitted into %dx%d stills; seed %d; %d panels in order, one Qwen child per edited "
          "panel; the seed is Picture %d and %s is Picture %d" % (
              qe.generator_text(model_id, loras), width, height, still_w, still_h, args.image_seed, total,
              3 - picture, SEED_CONTEXT_KINDS["frame"], picture))
    os.makedirs(paths["images_dir"], exist_ok=True)
    os.makedirs(files["work"], exist_ok=True)
    fit = _image_fit()
    fit.load_oriented_rgb(args.seed_image).save(files["original"], format="PNG")
    placeholder = os.path.join(files["work"], "placeholder.png")
    fit.fit_letterbox(fit.load_oriented_rgb(args.seed_image), still_w, still_h).save(placeholder, format="PNG")
    rc, cmd = _phase3_manifest_cmd(args, ["--image", placeholder] * total)
    if rc:
        return rc
    log = os.path.join(files["work"], "manifest.log")
    print("seed context: the manifest, built once with %s as every panel's still until it is made; log: %s"
          % (placeholder, log))
    print("Running: %s" % shlex.join(cmd))
    rc = _stream_and_tee(cmd, log)
    if rc != 0:
        print("Error: ltx-story-manifest exited %d; see %s" % (rc, log), file=sys.stderr)
        return 1
    try:
        with open(paths["manifest_path"], encoding="utf-8") as f:
            manifest = json.load(f)
        panels = list(manifest["panels"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        print("Error: cannot read %s: %s" % (paths["manifest_path"], e), file=sys.stderr)
        return 1
    if len(panels) != total:
        print("Error: %s has %d panels and %s has %d" % (paths["manifest_path"], len(panels), paths["story_md"], total),
              file=sys.stderr)
        return 1
    try:
        render = _ltx_render()
    except Exception as e:      # seed context CX19: an Error: line, never a traceback
        print("Error: cannot load %s: %s: %s" % (_render_tool(), type(e).__name__, e), file=sys.stderr)
        return 1
    if not args.no_review:
        input(SEED_CONTEXT_FRAME_GATE)
    archive = os.path.join(paths["story_dir"], "redo", "%s-%d" % (
        time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid()), "images")
    upto_json = os.path.join(files["work"], "manifest_upto.json")
    upto_mp4 = os.path.join(files["work"], "upto.mp4")
    changed, reused = set(), []
    for k in range(1, total + 1):
        path = os.path.join(files["work"], "frame_%02d.png" % (k - 1))
        context = _seed_context_context(args, plan, k, path)
        if _seed_context_reusable(args, plan, k, context, changed):
            reused.append(k)
            print("seed context: panel %d: reusing %s (a recorded edit of the same seed image, context picture, "
                  "prompt, seed and settings)" % (k, os.path.join(paths["images_dir"], "panel_%02d.png" % k)))
        else:
            status, failure = _seed_context_edit(args, qe, plan, k, path, context, archive)
            changed.add(k)
            if failure is not None or status != "ok":
                _seed_context_stop(args, plan, k, status, failure, qe.label(model_id))
                return 1
        _write_seed_edit_record(upto_json, dict(manifest, panels=[
            dict(p, image_path=os.path.abspath(os.path.join(paths["images_dir"], "panel_%02d.png" % j)))
            for j, p in enumerate(panels[:k], start=1)]))
        if os.path.lexists(upto_mp4):
            os.remove(upto_mp4)
        if not _wait_for_avail(args.min_avail_gib, args.avail_timeout):
            return 1
        cmd = [sys.executable, _render_tool(), upto_json, upto_mp4] + _seed_context_frame_flags(args)
        log = os.path.join(files["work"], "render-%02d.log" % k)
        print("seed context: panel %d: its clip (bin/ltx-mlx-render --resume on panels 1-%d); log: %s" % (k, k, log))
        print("Running: %s" % shlex.join(cmd))
        rc = _stream_and_tee(cmd, log)
        if rc != 0:
            print("Error: ltx-mlx-render exited %d on panels 1-%d, so panel %d's clip is not made; frame mode stops "
                  "here (see %s); a rerun reuses every recorded still and finished clip" % (rc, k, k, log),
                  file=sys.stderr)
            return 1
        if os.path.lexists(upto_mp4):
            os.remove(upto_mp4)
        if k < total and plan["kinds"][k + 1] == "frame":
            frame = os.path.join(files["work"], "frame_%02d.png" % k)
            clip = os.path.join(paths["story_dir"], "clips", "panel_%02d.mp4" % k)
            try:
                problems = (render.extract_last_frame(clip, frame, args.frames)
                            or render.check_chain_seed(frame, args.video_width, args.video_height, k))
            except Exception as e:      # seed context CX19: an Error: line, never a traceback
                problems = ["%s: %s" % (type(e).__name__, e)]
            if problems:
                print("Error: panel %d's context frame (the last frame of %s): %s" % (k + 1, clip, "; ".join(problems)),
                      file=sys.stderr)
                return 1
            print("seed context: panel %d: the last frame of %s -> %s" % (k + 1, clip, frame))
    print("seed context: %d panel stills written, %d reused; every clip is made, so Phase 4 reuses them all"
          % (len(changed), len(reused)))
    return 0


def _cast_refs_paths(story_dir):
```

**F5** (`bin/ltx-movie`, phase3_manifest uses _phase3_manifest_cmd, CX16). Old:
```python
def phase3_manifest(args):
    paths = _story_paths(args.story_id)
    print("=== Phase 3: manifest + dry-run ===")

    cmd_manifest = [sys.executable, os.path.join(WS, "bin", "ltx-story-manifest"),
                     "--story-id", args.story_id, "--prompts-md", paths["story_md"]]
    if args.no_stills:
        cmd_manifest += ["--no-images"]
    elif getattr(args, "shots", False):
        cmd_manifest += ["--shots"] + _shots_image_flags(args)
    else:
        cmd_manifest += ["--chain", "--image", os.path.join(paths["images_dir"], "panel_01.png")]
    cmd_manifest += ["--fps", str(args.fps),
                     "--target-seconds", str(_target_seconds(args)),
                     "--min-frames", str(args.frames),
                     "--max-frames", str(args.frames),
                     "--force"]
    if getattr(args, "no_narration", False) or getattr(args, "speech_only", False):
        cmd_manifest += ["--pace", "equal"]
    if getattr(args, "speech_delivery", "beats") != "beats":
        cmd_manifest += ["--speech-delivery", args.speech_delivery]
    cmd_manifest += _cast_flags(args)
    cmd_manifest += _location_flags(args, video=True)
    error, catalog_lists = _catalog_panel_loras(args)
    if error:
        print(error, file=sys.stderr)
        return 2
    if catalog_lists is not None:
        catalog_path = os.path.join(paths["story_dir"], "catalog_loras.json")
        _write_catalog_loras(args, catalog_path, catalog_lists)
        cmd_manifest += ["--catalog-loras", catalog_path]
    print("Running: %s" % shlex.join(cmd_manifest))
```
New:
```python
def phase3_manifest(args):
    paths = _story_paths(args.story_id)
    print("=== Phase 3: manifest + dry-run ===")

    rc, cmd_manifest = _phase3_manifest_cmd(args)
    if rc:
        return rc
    print("Running: %s" % shlex.join(cmd_manifest))
```

**F6** (`bin/ltx-movie`, _phase3_manifest_cmd, CX16). Old:
```python
# ---------------------------------------------------------------------------
# phase 4: render
```
New:
```python
def _phase3_manifest_cmd(args, image_flags=None):
    """(rc, cmd): Phase 3's bin/ltx-story-manifest command with rc 0, or (2, None) after printing the catalog error.
    In shots mode its --image flags are image_flags when given (--seed-context frame's placeholders, seed context
    spec CX16), else _shots_image_flags(args). Writes catalog_loras.json when the plan picks catalog LoRAs."""
    paths = _story_paths(args.story_id)
    cmd_manifest = [sys.executable, os.path.join(WS, "bin", "ltx-story-manifest"),
                     "--story-id", args.story_id, "--prompts-md", paths["story_md"]]
    if args.no_stills:
        cmd_manifest += ["--no-images"]
    elif getattr(args, "shots", False):
        cmd_manifest += ["--shots"] + (_shots_image_flags(args) if image_flags is None else list(image_flags))
    else:
        cmd_manifest += ["--chain", "--image", os.path.join(paths["images_dir"], "panel_01.png")]
    cmd_manifest += ["--fps", str(args.fps),
                     "--target-seconds", str(_target_seconds(args)),
                     "--min-frames", str(args.frames),
                     "--max-frames", str(args.frames),
                     "--force"]
    if getattr(args, "no_narration", False) or getattr(args, "speech_only", False):
        cmd_manifest += ["--pace", "equal"]
    if getattr(args, "speech_delivery", "beats") != "beats":
        cmd_manifest += ["--speech-delivery", args.speech_delivery]
    cmd_manifest += _cast_flags(args)
    cmd_manifest += _location_flags(args, video=True)
    error, catalog_lists = _catalog_panel_loras(args)
    if error:
        print(error, file=sys.stderr)
        return 2, None
    if catalog_lists is not None:
        catalog_path = os.path.join(paths["story_dir"], "catalog_loras.json")
        _write_catalog_loras(args, catalog_path, catalog_lists)
        cmd_manifest += ["--catalog-loras", catalog_path]
    return 0, cmd_manifest


# ---------------------------------------------------------------------------
# phase 4: render
```

**F7** (`bin/ltx-movie`, phase4_render's render path, CX15). Old:
```python
    cmd = [sys.executable, os.path.join(WS, "bin", "ltx-mlx-render"),
           paths["manifest_path"], movie_path] + _phase4_flags(args)
```
New:
```python
    cmd = [sys.executable, _render_tool(), paths["manifest_path"], movie_path] + _phase4_flags(args)
```

**F8** (`bin/ltx-movie`, the frame dry-run panels line, CX20). Old:
```python
    print("Location changes (single-image edits): %s" % (_panel_list(plan["changes"]) or "none"))
    changed, reused = set(), []
```
New:
```python
    print("Location changes (single-image edits): %s" % (_panel_list(plan["changes"]) or "none"))
    if args.seed_context["mode"] == "frame":
        print("Panels to edit: decided panel by panel during the run: a context picture is the last frame of a clip "
              "this run renders or reuses")
        return
    changed, reused = set(), []
```

**F9** (`bin/ltx-movie`, the frame dry-run line, CX20). Old:
```python
    if args.force_story or not known or not os.path.exists(paths["story_md"]):
        print("Panels: decided at Phase 2, from story.md after Phase 1")
        return
    error, plan = _seed_context_plan(args, qe)
```
New:
```python
    if args.seed_context["mode"] == "frame":
        work = _seed_context_paths(paths["story_dir"])["work"]
        print("Frame mode: Phase 2 also renders each panel's clip right after its still, with bin/ltx-mlx-render "
              "--resume on a manifest of the panels so far (%s; --on-panel-failure stop; logs %s), and the exact last "
              "frame of clip k is panel k+1's context picture. A failed clip stops the run. Phases 3 and 4 then build "
              "the final manifest and reuse every clip."
              % (os.path.join(work, "manifest_upto.json"), os.path.join(work, "render-NN.log")))
    if args.force_story or not known or not os.path.exists(paths["story_md"]):
        print("Panels: decided at Phase 2, from story.md after Phase 1")
        return
    error, plan = _seed_context_plan(args, qe)
```

**F10** (`bin/ltx-movie`, the phase tuple, CX15). Old:
```python
    if getattr(args, "seed_image", None):
        phases = (phase0_seed,) + phases
    return phases
```
New:
```python
    if getattr(args, "seed_image", None):
        phases = (phase0_seed,) + phases
    if (getattr(args, "seed_context", None) or {}).get("mode") == "frame":
        # Seed context CX15: the frame mode's Phase 2 renders every clip as it goes; Phases 3 and 4 reuse them.
        phases = tuple(phase_seed_context_frames if p is phase2_stills else p for p in phases)
    return phases
```

No other line of `bin/ltx-movie` changes.

**Superseded by Amendment A1 (Section 13).** The blocks above are the Task 2 commit as made (`96b51e9`). Its `--on-panel-failure stop` (F4's `_seed_context_frame_flags` and its call, F4's docstring sentence, F9's `--on-panel-failure stop; ...` and `A failed clip stops the run.`) and Step 1's pins of it (CXT12, CXT13, CXT17, CXT18) are replaced by the A1 fix commit, which uses Phase 4's flags unchanged and adds CXT20. Task 2's own expected counts below (`19 passed`, `P0+18`) are those of the Task 2 commit.

**T1** (`tests/test_ltx_movie_seed_context.py`, CXT9's --seed-context help text). Old:
```python
        "previous panel's stay single-image edits of the seed. Needs a --seed-edit-model that edits with several "
        "pictures (qwen2511-q4 is refused). See docs/superpowers/specs/2026-11-10-seeded-shots-context-design.md."),
```
New:
```python
        "previous panel's stay single-image edits of the seed. frame uses the exact last frame of the previous "
        "panel's clip instead, rendering each clip right after its still; a failed still or clip stops the run. "
        "Needs a --seed-edit-model that edits with several pictures (qwen2511-q4 is refused). See "
        "docs/superpowers/specs/2026-11-10-seeded-shots-context-design.md."),
```

**T2** (`tests/test_ltx_movie_seed_context.py`, CXT9's docstring text). Old:
```python
       "panel's stay single-image edits of the seed. Absent, Phase 2 is unchanged. Cast references")
```
New:
```python
       "panel's stay single-image edits of the seed. --seed-context frame uses the exact last frame of the previous "
       "panel's clip instead: Phase 2 then renders each clip right after its still (bin/ltx-mlx-render --resume on "
       "the panels so far), and Phases 3 and 4 reuse every clip. Absent, Phase 2 is unchanged. Cast references")
```

**T3** (`tests/test_ltx_movie_seed_context.py`, CXT9's choices). Old:
```python
    assert actions["--seed-context"].choices == ["still"]
```
New:
```python
    assert actions["--seed-context"].choices == ["still", "frame"]
```

No other line of `tests/test_ltx_movie_seed_context.py` changes.

- [ ] **Step 4: Verify.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/sc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_ltx_movie_seed_context.py tests/test_ltx_movie_seed_context_frame.py 2>&1 | tail -1   # 19 passed
python3 -B -m pytest -q -p no:cacheprovider tests/test_shots_mode.py tests/test_ltx_movie_shots_seed.py tests/test_ltx_movie_seed_edit.py tests/test_ltx_movie_cast_refs.py tests/test_dialogue.py tests/test_casting_pipeline.py tests/test_location_pipeline.py tests/test_movie_ui_builder.py tests/test_lora_catalog.py tests/test_story_engine.py 2>&1 | grep -E '^FAILED|passed|failed'
    # only test_rst62_import_sets (baseline) and test_mut26_pipeline_files_are_unchanged (expected) fail
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1      # OK 347/347
git diff --numstat                                             # 200 30 bin/ltx-movie; 8 4 tests/test_ltx_movie_seed_context.py
grep -c "seed_context" bin/ltx-movie                           # 74
grep -c 'os.path.join(WS, "bin", "ltx-mlx-render")' bin/ltx-movie   # 4
grep -c "_render_flags(args)" bin/ltx-movie                    # 4
grep -c "^import re$" bin/ltx-movie                            # 0
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' bin/ltx-movie tests/test_ltx_movie_seed_context.py tests/test_ltx_movie_seed_context_frame.py; done   # compiled 3, twice
zsh $S/sc-baseline/gate-run.sh 2
```
Expected gate output: the summary `3 failed, P0+18 passed, 2 skipped`; `lost 1 (listed 1, unexpected 0); new tests 19, not passing 0; baseline failures still failing 2 of 2`; `GATE PASS`, `3 passed` and `ATK2 OK lines unchanged`.

- [ ] **Step 5: Commit.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/sc-wt/qwen-agent-workspace
git add bin/ltx-movie tests/test_ltx_movie_seed_context.py tests/test_ltx_movie_seed_context_frame.py
git diff --cached --name-only | wc -l    # 3
git commit -m "ltx-movie: --seed-context frame: each seeded shots still also sees the last frame of the previous panel's clip; Phase 2 renders every clip right after its still, and Phases 3 and 4 reuse them (seeded-shots-context CX14-CX20, CXT12-CXT19)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 3: the `test_mut26` re-baseline (a test-only commit; never amend)

The baseline chain moves from `c537fed` (shots-multiref) to the last code commit: the A1 fix commit after Task 2 (Amendment A1; not Task 2's commit), or Task 1's when still mode ships alone.

- [ ] **Step 1:**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/sc-wt/qwen-agent-workspace
SHA=$(git log -1 --format=%H -- bin/ltx-movie); echo $SHA
test "$SHA" = "$(git rev-parse HEAD)" && echo "SHA is HEAD"
git diff --name-only c537fedcab9fbdfce3181063aa9b8b0f6eff9b5f $SHA -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py
```
Expected: a 40-hex `SHA`; `SHA is HEAD`; exactly one path, `qwen-agent-workspace/bin/ltx-movie`. The 23 paths are written out because zsh does not word-split a variable.

- [ ] **Step 2: Two Edits to `tests/test_movie_ui_builder.py`.** Type the 40 characters of `SHA` where the word SHA appears.
  - Replace `then to c537fedcab9fbdfce3181063aa9b8b0f6eff9b5f (shots-multiref).` with `then to c537fedcab9fbdfce3181063aa9b8b0f6eff9b5f (shots-multiref), then to SHA (seeded-shots-context).` (once, at the end of the long comment line `:291`).
  - Replace `    BASELINE = "c537fedcab9fbdfce3181063aa9b8b0f6eff9b5f"` (`:293`) with `    BASELINE = "SHA"`.

- [ ] **Step 3: Verify and commit.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/sc-wt/qwen-agent-workspace
SHA=$(git rev-parse HEAD)
grep -c "    BASELINE = \"$SHA\"" tests/test_movie_ui_builder.py                                        # 1
grep -c "(shots-multiref), then to $SHA (seeded-shots-context)\.$" tests/test_movie_ui_builder.py      # 1
git diff --stat -- tests/test_movie_ui_builder.py | tail -1        # 1 file changed, 2 insertions(+), 2 deletions(-)
zsh $S/sc-baseline/gate-run.sh 3
git add tests/test_movie_ui_builder.py
git diff --cached --name-only    # exactly qwen-agent-workspace/tests/test_movie_ui_builder.py
git commit -m "tests/test_movie_ui_builder.py: test_mut26 BASELINE moves to the seeded-shots-context commit" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Expected gate output: the summary `2 failed, P0+20 passed, 2 skipped` (P0 = 2698; still mode alone: `P0+11`); `lost 0 (listed 0, unexpected 0); new tests 20, not passing 0` (still mode alone: `11`); `baseline failures still failing 2 of 2`; `GATE PASS`, `3 passed` and `ATK2 OK lines unchanged`; `grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $S/sc-baseline/task-3-pytest.txt` prints `1`.

### Verification (controller)

- **V1:** confirm CXK1 and CXK2 from Task 3's gate output and:
  - `git diff --numstat 29e3a89 HEAD -- bin/ltx-movie`: `569 25` with the A1 fix commit (Task 2 without it: `575 25`; still mode alone: `381 1`)
  - `git diff --name-only 29e3a89 HEAD | grep -v '^qwen-agent-workspace/docs/' | wc -l`: `4` (`bin/ltx-movie`, the two new test files, `tests/test_movie_ui_builder.py`; still mode alone: `3`)
  - `git diff 29e3a89 HEAD -- qwen_edit.py seed_edit_mflux_child.py character_dataset.py character_lib.py story_engine.py bin/ltx-story-images bin/ltx-story-manifest bin/ltx-mlx-render movie_ui_lib.py static | wc -l`: `0`
- **V2:** an Opus design review (the `design-reviewer` agent) of the commits against this spec, with Section 8 as the focus. A finding is fixed in a new commit. If that commit touches a pinned file, another Task 3-style baseline commit follows, and V1 runs again.
- **V3:** live checks L1-L6 (Section 7). The user runs them on macstudio; the assistant never does.

### Replay result

The full suite was run on rsync copies of the worktree at `29e3a89` (no `.git`) with `python3 -B -m pytest tests/ -q -rA -p no:cacheprovider --continue-on-collection-errors`:

| Copy | Result |
|---|---|
| `$S/sc-base` (untouched) | `3 failed, 2691 passed, 8 skipped` |
| `$S/sc-t1` (Task 1 as written) | `2 failed, 2703 passed, 8 skipped` |
| `$S/sc-check` (Tasks 1 and 2 as written) | `2 failed, 2711 passed, 8 skipped` |

Test by test, with this plan's `gate.py` and `expected-failures.txt` run on the copies' outputs: Task 1 `lost 0 (listed 0, unexpected 0); new tests 11, not passing 0; baseline failures still failing 2 of 2`, `GATE PASS`; Tasks 1-2 `lost 0 (listed 0, unexpected 0); new tests 19, not passing 0; baseline failures still failing 2 of 2`, `GATE PASS`.
- 2703 = 2691 + 11 + 1 and 2711 = 2691 + 19 + 1. The extra pass is `tests/test_fleet_tracing.py::test_trt46_post_spans_validation_cap_and_store`, which failed in the untouched copy's run (`qwen-agentd alpha exited 2 at startup`), passed when rerun alone, and passed in both later runs: a start-up flake, hence its line in `expected-failures.txt` and in the gate's rerun.
- The 2 failures are the known `test_d2_copied_literals_match_the_spike` and `test_rst62_import_sets`. The 8 skips are the copies not being git worktrees (`not a git checkout`: `test_mut26` and the 5 `d210c26` tests) plus 2 host-only skips; in `$S/sc-wt` those 6 tests run, which is why the gates expect `2 skipped`, and `test_mut26` fails until Task 3.
- In the final copy `python3 -B tests/test_ltx_movie_offline.py` printed `OK 347/347`, and the other four OK lines were unchanged (`OK 25/25`, `OK 57/57`, `OK 68/68`, `OK 205/205`).
- A third copy (`$S/sc-replay`) ran the same code with an earlier numbering of the frame tests (CXT14b for today's CXT15): `2 failed, 2711 passed, 8 skipped`, with the same failures and skips.

**Found while writing and replaying the tests, and fixed in this plan:**
1. With the forced cascade alone, a run interrupted after re-editing panel 3 left panel 4's old `ok` entry; when the re-edit reproduced panel 3's bytes, the rerun reused panel 4. `_seed_context_edit` now clears its cascade's entries before the edit (CXT6's last assertion; mutation "cascade entry pop").
2. `character_lib`'s sentence split does not end a sentence at a closing quote, so a quoted setting sentence swallows the next sentence (Review Focus 2); CXT2 pins the unquoted and the lower-case forms instead.
3. A frame-mode rerun after Phase 4 meets the `movie.mp4` guard; CXT17 asserts the exit 2 and reruns with `--force`.
4. Before the replay, reading the pins showed that a fifth `os.path.join(WS, "bin", "ltx-mlx-render")` (L17f, L46f, RST50), a fifth `_render_flags(args)` (L17d, L46e, RST50) or a `no_stills` between `phase2_stills` and `phase3_manifest` (L17b) would fail existing tests: `_render_tool()`, `_seed_context_frame_flags` (built on `_phase4_flags`) and the placement of `_phase3_manifest_cmd` keep them true, and the final copy passes them. (After Amendment A1 the partial render calls `_phase4_flags(args)` directly, which keeps the `_render_flags(args)` count at 4 as well.)
