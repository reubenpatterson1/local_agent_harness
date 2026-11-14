# Extra reference images: every Qwen edit of a run may also take user pictures (a location, a prop, a style), up to the edit model's reference limit, when the host runs with --no-low-ram

Date: 2026-11-13

Status: design spec and implementation plan in one document.

**The user's goal:** one Qwen edit can take up to 10 reference images: its own pictures (the seed, the context picture or the two cast stills) and then user-attached **extra references** (a location, a prop, a style), each named in the edit prompt.

**The user's approved design (binding; Section 0.2 lists it verbatim with what this spec adds).** Choices this spec makes beyond it are marked **[spec choice]**. The implementer makes no design decisions.

**Where.**
- Worktree `$S/xr-wt`, branch `extra-refs`, at `fcd5d86` (Merge PR #22, motion-beat-only). `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`. `WS` is `qwen-agent-workspace/`. Every path is relative to `WS`, and every line number is verified at `fcd5d86`.
- At `fcd5d86` every `PIPELINE_FILES` member is byte-identical to `bff48f7208183b87862e21d9eb798fca53994860`, the current `test_mut26` BASELINE (`tests/test_movie_ui_builder.py:293`; checked with `git diff --quiet bff48f7 HEAD -- <PIPELINE_FILES>`).
- `/Users/reubenpatterson/local_agent_harness` is never touched, except through the worktree. The user's other Mac (macstudio) is never accessed.

**Builds on** **[QE]** `docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md`, **[SE]** `2026-11-05-compose-shots-seed-edit-design.md`, **[CR]** `2026-11-09-shots-multi-reference-stills-design.md`, **[CX]** `2026-11-10-seeded-shots-context-design.md`, **[ZE]** `2026-11-11-shots-zimage-engine-design.md` and **[BF]** `2026-10-30-batch-forks-design.md`. Every requirement of those specs stays in force except where Section 8 names it as amended.

**IDs.** Requirements **XR1-XR24**, tests **XR-T1-XR-T23**, KPIs **XRK1-XRK8**, live checks **XR-LV0-XR-LV10**, edits **Q1-Q5** (`qwen_edit.py`), **G1-G6** (`movie_ui_seedgen.py`), **M1-M27** (`bin/ltx-movie`), **U1-U16** (movie UI), **E1-E14** (existing tests and fixtures). At `fcd5d86`, `git grep -nE "\bXR[0-9]+\b|XR-T[0-9]|XRK[0-9]|XR-LV[0-9]"` finds nothing.

**Terms.**
- A **Qwen edit** is one `qwen_edit.run_jobs` job made by `bin/ltx-movie`.
- Its **own pictures** are the reference images it has without this feature: the oriented seed (Phase 1c and seeded shots), the seed and the context picture (seed context), or the two cast reference stills (cast refs).
- An **extra reference** (an **extra**) is one `--extra-ref` picture with its optional caption.
- A job's **total** is its own pictures plus the extras.
- The **edit path** of a run is the one of the four below that makes its Qwen edits (Section 0.1).

---

## 0. Scope

### 0.1 Every Qwen edit `bin/ltx-movie` makes today (verified at `fcd5d86`)

`bin/ltx-movie` calls `qwen_edit.run_jobs` in exactly four places (`grep -n "run_jobs(" bin/ltx-movie`: `:2651`, `:2864`, `:3076`, `:3454`). Every one of them can take extras; no path has to refuse them.

| Path | Function | Jobs | Own pictures | Prompt built in | Reuse rule |
|---|---|---|---|---|---|
| P1 chained panel 1 (Phase 1c) | `phase_seed_edit` `:2608-2676` | one job, `run_jobs(..., [job], ...)` `:2647-2651` | 1: `seed-original.png` | `_panel1_edit_prompt` `:2585-2592` (no prefix, no `"The new shot: "`) | `key` `:2629-2630`; reuse `:2636-2640` (`all(k in old and old[k] == v ...)`); record `seed_edit.json` `:2657-2664` |
| P2 seeded shots | `_shots_seed_plan` `:2733-2766`, `_phase2_shots_seed` `:2780-2890` | one batch `:2859-2865` | 1: `seed-original.png` | `_shots_seed_prompts` `:2696-2707` (`SHOTS_SEED_EDIT_PREFIX` `:163-167` + text) | `keys[n]` `:2755-2756`; reuse `:2759-2762`; record `seed_edits.json` |
| P3 seed context (still and frame) | `_seed_context_plan` `:2919-2955`, `_seed_context_reusable` `:2970-2982`, `_seed_context_edit` `:3007-3090`; callers `_phase2_seed_context` `:3106-3149` and `phase_seed_context_frames` `:3163-3282` | one job per edited panel `:3035-3046`, `:3076` | 1 (kind `none`: panel 1 and every location change) or 2 (seed and context picture, in `--seed-context-order`) | `:2949` (`SHOTS_SEED_EDIT_PREFIX` or `SEED_CONTEXT_PREFIX` `:208-215`) | `base[n]` `:2950-2951` plus `context`; reuse `:2978-2982`; record `seed_context_edits.json` |
| P4 cast refs (unseeded shots) | `_cast_refs_plan` `:3318-3369`, `_phase2_cast_refs_batch` `:3372-3481` | one batch `:3446-3456` | 2: the two cast stills, in cast order | `_cast_refs_prompt` `:3308-3315` (`CAST_REFS_EDIT_PREFIX` `:181-186`) | `keys[n]` `:3358-3359`; reuse `:3362-3365`; record `cast_ref_edits.json` |

- **Chained panel 1 uses the same `run_jobs` path** (P1). It is one job with one `source`; adding `"sources"` is the PR #15 multi-reference job schema ([CR] CR3), which both children read (`seed_edit_mflux_child.py:95`, `character_dataset.py` `child_qwenedit`). So P1 takes extras.
- **No other Qwen edit runs in `bin/ltx-movie`.** Panels 2..N of a chained movie are clips of the previous clip's last frame, and unseeded shots panels without a cast pair are Z-Image stills (`_phase2_shots` `:2513-2552`); neither is a Qwen edit, so neither gets extras.
- **The Z-Image seed path** (`--shots --seed-image --seed-edit-model as-is`, [ZE] ZE1, `_shots_zimage_seed` `:2443-2447`) has no edit: panel 1 is the seed, and every other panel is a Z-Image still. A chained run with `as-is` (or with no `--seed-edit-model`) uses the seed unedited. Both are refused with `--extra-ref` (XR3).

### 0.2 The user's approved design (binding; verbatim in substance, then what this spec adds)

1. **Inputs.** Compose gets an "Extra references" list of up to 9 uploaded images, each with an optional caption (e.g. "the sword", "the throne room"). CLI: `--extra-ref PATH[:caption]`, repeatable. Extras are copied into the story folder with their sha256. A rerun with a changed extra (content, caption, order or count) re-renders the edits that used it, following the existing reusable/changed mechanisms of the seed-context and cast-refs phases.
2. **Where they apply.** Every Qwen edit job in the run gets the extras appended to its reference list, in all paths: seeded shots (seed + extras), seed context (seed, context image, then extras), cast refs (cast stills, then extras), and chained panel 1. The order is always primary, then cast or context, then extras. The edit prompt gains one sentence naming each extra by caption and picture number; extras without a caption get a neutral wording.
3. **Cap tied to low-RAM.**
   - Each Qwen registry model gets `max_references`: 10 for `qwen21-q4`/`q8`/`bf16`, 3 for `qwen2511-bf16`, 1 for `qwen2511-q4`.
   - In the default low-RAM mode the effective total stays at 2 as today, so extras are refused with a clear message, and the Compose control is disabled.
   - With `--no-low-ram`, the model's own `max_references` applies. `QWEN_LTX_AUTOTUNE=1` sets it on hosts with at least 96 GiB.
   - A cap overrun is refused before any job starts, never as a mid-run crash.
   - A total over 4 prints a quality warning.
   - The per-job timeout weight scales with the number of references, and the memory floor gets a per-reference increment.
4. **Out of scope (user decision B):** cast characters stay at 2 per panel; the planner and plan prompts are not changed; per-panel extras; the Seeds, Locations and Characters tabs; the Z-Image path (refusal preferred, consistent with PR #21).
5. **Validation and UI:** movie_ui_lib V1 rules (mirroring the shots-zimage rule-8 pattern), the movie_ui_server upload endpoint for extras, the Compose fields, batch forks (extras carry into forks unchanged, as `seed_upload` does), and the low-RAM gate on the existing No low-RAM checkbox (the extras control is disabled, with an explanatory note, unless it is checked).

**What this spec adds** (each justified in Section 1):
- the low-RAM rule "no extras at all" (Decision 2);
- the exact prompt sentence and where it goes (Decision 4);
- `reference_gib` and the floor formula (Decision 6);
- the timeout formula 3 x n (Decision 7);
- `max_references` enforced twice (Decision 5);
- the copy as an oriented PNG keyed by the source bytes' sha256 (Decision 3);
- the `PATH[:CAPTION]` parse rule and the caption rules (Decision 8);
- reusing `POST /api/uploads` instead of a new endpoint (Decision 10);
- the server's 400 for the model cap (Decision 11);
- the batch level `stills` and the seed group (Decision 12);
- the refusal of `--seed-edit-model as-is` and of runs with no Qwen edit (XR3);
- the unused-extras note when a cast-refs run has no pair panel (XR13);
- `output_resolution` left unchanged (Decision 9).

### 0.3 Grounding (verified at `fcd5d86`)

**`bin/ltx-movie` (pinned, 4292 lines).**
- Top-level imports `:136-149` (`glob` is imported). **No top-level `import re`** (`tests/test_ltx_movie_offline.py` L7j; CRT17; CXT9). This spec adds no import.
- Module docstring: the Seed edit paragraph ends `:118-119` with `... as\n--shots does without a seed.`; the Seed context paragraph `:121-127`; the Cast references paragraph `:129-133` is last. CRT17 (`tests/test_ltx_movie_cast_refs.py:595`) pins that the docstring ENDS with the Cast references paragraph. CXT9 (`tests/test_ltx_movie_seed_context.py:577-584`) pins the Seed context paragraph followed by "Cast references". SZ10 pins the Seed edit sentence. So the new paragraph goes between Seed edit and Seed context.
- Constants: `SEED_CONTEXT_REDO_NOTE` `:223-224` is the last constant before `STORY_PROMPT_TEMPLATE` `:226`.
- Parser: `--seed-context-order` `:536-539`, `--story-model` `:540`, `--no-low-ram` `:562-566` (dest `no_low_ram`, store_true, no `--low-ram` flag).
- `main` `:4158-4283`:
  - autotune `:4164-4173`: when `QWEN_LTX_AUTOTUNE` is non-empty, `ltx2_mlx_video_skill.maybe_autotune_apply` (`ltx2_mlx_video_skill.py:133-153`) sets `args.no_low_ram = True` on a host of at least `AUTOTUNE_BIG_GIB = 96` GiB (`:88`, `AUTOTUNE_BIG["low_ram"] = False` `:89`, transform `lambda v: not v` `:4167`), unless `--no-low-ram` is on the command line. `QWEN_LTX_MEM_GIB` overrides the detected size (`:87`, `:96-101`);
  - then the resolvers in order: `_resolve_shots` `:4213`, `_resolve_casting`, ..., `_resolve_seed_edit` `:4231`, `_resolve_cast_refs` `:4234`, `_resolve_seed_context` `:4237-4239`;
  - then the dry run `:4241-4242`, the lockfile `:4248-4260`, and the phases `:4273-4277`.
- **How the edit phases learn the effective low-RAM mode (XR4):**
  - Autotune is applied at `:4171`, before every resolver.
  - `_resolve_extra_refs` (new) runs right after `_resolve_seed_context`, so it reads the final `args.no_low_ram`.
  - It decides once, before the lockfile and before any phase: it either refuses (exit 2) or sets `args.extra_refs`.
  - The edit phases read only `args.extra_refs`; none of them reads `no_low_ram`.
  - The phase order (Phase 1c before Phase 2, frame mode's interleaved renders) therefore cannot change the decision.
- Helpers: `_image_fit` `:936-941` (`ltx_image_fit.load_oriented_rgb` `:51-60` raises on any unreadable file); `_qwen_edit` `:960-963`; `_sha256_file` `:2686-2693`; `_write_seed_edit_record` `:2600-2605`; `_shots_seed_entries` `:2710-2722`; `_write_shots_seed_record` `:2725-2730`.
- The dry run: `_print_dry_run_plan` `:3942`; its Phase 3 header `print("--- Phase 3: manifest + dry-run ---")` occurs once, at `:4084`.

**`qwen_edit.py` (not pinned; in `NEW_PY`).**
- `MULTI_REFERENCE_TIMEOUT_FACTOR = 6` `:51`; `MULTI_REFERENCE_REFUSED` `:52-56`.
- `memory_problem(entry)` `:266-273` is used by `selection_problem` `:463-470` and `bin/seed-edit:256`.
- `memory_floor(model_id)` `:416-417`; `jobs_timeout` `:429-433` (weight 6 for any job with two or more sources).
- `run_jobs` `:477-592`: the multi-reference refusal `:482-484`, the diffusers `"images"` key `:506-507`, the mflux `spec_job` `"sources"` `:534-539`, and the timeout `:575`.
- **Every fake qwen_edit in the tests** (`tests/test_ltx_movie_seed_edit.py:67`, `tests/test_ltx_movie_shots_seed.py:104`, and their subclasses in the cast-refs and seed-context tests) copies the real `memory_floor`. So an optional second parameter keeps every existing call working.

**`seed_edit_mflux_child.py`** (unchanged): `images = job["sources"] if "sources" in job else [source]` `:95`, passed as `image_paths`. mflux `QwenImage21Edit.generate_image` raises above 10 reference images. On this Mac's mflux 0.21.0 source (`~/mflux/.venv/.../qwen21/variants/edit/qwen_image_21_edit.py`), each reference is resized to about `output_resolution` (default 1024) squared, which is about 4096 tokens, and the reference latents are concatenated into the transformer input at every step (no reference cache). Inferred for the pinned 0.24.0.

**`movie_ui_seedgen.py` (not pinned).** `QWEN_MODELS` `:47-77`; `registry_view` `:289-298` lists the keys the page sees. Pins:
- SQT10 (`tests/test_seed_edit_tool.py:1098-1143`) compares `[dict(m) for m in seedgen.QWEN_MODELS]` with a literal `REGISTRY`;
- SQT16 (`tests/test_movie_ui_seedgen.py:334-358`) compares `registry_view()` with a literal.

Both are edited (E1, E2).

**Movie UI.**
- `movie_ui_lib.py`: `DEFAULT_FIELDS` `:942-955` (32 keys); `FIELD_FLAGS` `:960-974` (31 entries, last `seed_edit`); `build_argv` `:1024-1084` (seed block `:1035-1039`); `_rule_seed_edit` `:1134-1148`; `validate_fields` `:1500-1618` (rule 8, the shots-zimage pattern, `:1559-1576`; rule 12d `:1585`; rule 18, the help-flag check, `:1614-1618`); `UPLOAD_ID_RE` `:36`. The library cannot import `movie_ui_seedgen` at its top level, because seedgen imports it.
- `movie_ui_server.py`:
  - `POST /api/uploads` (`:104`, `_h_upload` `:1174-1180`, `store_upload` `:1164-1171`) stores `<state>/uploads/<sha256>.<ext>`, written once. It allows PNG, JPEG and WebP with a magic-byte check (`UPLOAD_TYPES` `:57-58`), and at most 20 MiB (`UPLOAD_MAX` `:43`, `_upload_refusal` `:478-483`). Uploads are never pruned;
  - `_fields_body` `:760-770` cleans the seed edit selection (QE57, 400 on error);
  - `_h_job_create` `:845-857`; `_h_seed_folder` `:950-983` (each seed row is `dict(fields, ...)` `:914`).
- `movie_ui_batch.py`: `GROUPS` `:34`; `FIELD_LEVELS` `:38-47`; `merge` `:196-217` (the seed rules `:207-215`).
- `static/movie-ui/index.html`: the `c-sq-qwen-box` `:91-98` (`c-sq-reason` `:97`); No low-RAM checkbox `:141`.
- `static/movie-ui/app.js`:
  - `S` `:25`; `composeSeedEditActive` `:414-419`; `composeEngineUpdate` `:444-463`; `composeFields` `:465-506`; `updateComposeButtons` `:583-630` (SD29 comment `:614`); `uploadFile` `:632-637`; `onSeedFile` `:639-653`; `fillCompose` `:870-924`; `setupCompose` `:926-`; `seedQwenEntry` `:1874-1877`; `qwenPicker` `:1906-` (`p.state.model`);
  - **SZ17/SZ18** (`tests/test_movie_ui_shots_zimage.py:245-300`) run the real `composeFields` and `fillCompose` in node with a fake page (`FAKE_COMPOSE`) that defines only a fixed set of names. So `composeFields` must not call a new function; it reads `S.extrasOn` instead (U5).
- **Pins on counts and texts edited in Task 2:**
  - `len(FIELD_FLAGS) == 31`: LU10 `tests/test_location_ui.py:267`, MUT3 `tests/test_movie_ui_builder.py:137`, QET33 `tests/test_movie_ui_qwen_edit.py:116`, SET21 `tests/test_movie_ui_shots_seed.py:157`;
  - `len(payload["supported"]) == 31`: MU14 `tests/test_movie_ui_http.py:225`;
  - `(27, 5, 32)`: BT1 `tests/test_movie_ui_batch.py:79`, QET37 `tests/test_movie_ui_qwen_edit.py:352`;
  - `EXPECTED_LEVELS`: `tests/test_movie_ui_batch.py:29-38`;
  - `GROUPS`: QET37 `:354-355`;
  - `FLAGS`: `tests/test_movie_ui_shots_seed.py:38-43`;
  - MUT3's `current - old` set: `tests/test_movie_ui_builder.py:130-132`;
  - the help fixture `tests/fixtures/movie_ui/ltx-movie-help-current.txt` (what the stub workspace's `bin/ltx-movie --help` prints, `tests/movie_ui_testutil.py:184-187`).

**Prompt pins.**
- `SHOTS_SEED_EDIT_PREFIX`, `CAST_REFS_EDIT_PREFIX` and `SEED_CONTEXT_PREFIX` are pinned verbatim: SET5 `PREFIX`, the CR tests' `PREFIX`, the CX tests' `SEED_PREFIX`, `CONTEXT_PREFIX` and `SWAPPED_PREFIX`. None of them changes: the sentence is inserted into each built prompt, and only when the run has extras.
- The only sha256 pins on prompt text are on `story_engine.FORMAT_REFERENCE` (`tests/test_shot_format.py:488`; `tests/test_chained_end_frames.py:1073-1127`). This change does not touch `story_engine.py` (confirmed).

**Pipeline-file pin.** `PIPELINE_FILES` (`tests/test_movie_ui_builder.py:223-228`) includes `bin/ltx-movie` and `ltx2_mlx_video_skill.py`. It does not include `qwen_edit.py`, `movie_ui_seedgen.py` or any movie UI file. Only `bin/ltx-movie` changes among the pinned files, so `test_mut26` fails from Task 1 until Task 3 moves its BASELINE. `NEW_PY` is not extended ([CR] CR15: QET11 pins its tail).

### 0.4 Deliverables

| # | File | Pinned | Task | Change |
|---|---|---|---|---|
| D1 | `qwen_edit.py` | no | 1 | `entry_floor`, `memory_problem(entry, references=1)`, `memory_floor(model_id, references=1)`, `max_references`, `reference_memory_problem`, `jobs_timeout` 3 x n, the `run_jobs` cap guard (Q1-Q5) |
| D2 | `movie_ui_seedgen.py` | no | 1 | `max_references` and `reference_gib` in every registry entry; `max_references` in `registry_view` (G1-G6) |
| D3 | `bin/ltx-movie` | **yes** | 1 | flag, resolver, constants, helpers, the four edit paths, dry run, docstring (M1-M27) |
| D4 | `tests/test_qwen_edit_extra_refs.py` | — | 1 | new, XR-T1-XR-T5 |
| D5 | `tests/test_ltx_movie_extra_refs.py` | — | 1 | new, XR-T6-XR-T18 |
| D6 | `tests/test_seed_edit_tool.py`, `tests/test_movie_ui_seedgen.py` | — | 1 | SQT10 and SQT16 learn the two registry keys (E1, E2) |
| D7 | `movie_ui_lib.py`, `movie_ui_server.py`, `movie_ui_batch.py`, `static/movie-ui/index.html`, `static/movie-ui/app.js` | no | 2 | the `extra_refs` field, flag, argv, V1 rule 12e, the 400 cap, batch level and merge, the Compose control (U1-U16) |
| D8 | `tests/test_movie_ui_extra_refs.py` | — | 2 | new, XR-T19-XR-T23 |
| D9 | `tests/fixtures/movie_ui/ltx-movie-help-current.txt` and seven existing UI tests | — | 2 | the help fixture learns `--extra-ref`; the field and flag counts (E3-E14) |
| D10 | `tests/test_movie_ui_builder.py` | — | 3 | only `test_mut26`'s BASELINE and comment chain (XR24) |

Untouched: `seed_edit_mflux_child.py`, `character_dataset.py`, `character_lib.py`, `story_engine.py`, `bin/ltx-story-images`, `bin/ltx-story-manifest`, `bin/ltx-mlx-render`, `bin/seed-edit`, `ltx2_mlx_video_skill.py`, `movie_ui_seedfolder.py`, `content_safety.py`, `location_dataset.py`, every other test.

### 0.5 Out of scope

- Cast characters per panel stay at 2 (`story_engine.MAX_CAST`, the left/right position wording). The planner and plan prompts are not changed: Phase 1 is not told about the extras. A prop or place appears in a panel's `Image:` text only when the narrative mentions it (Risk R6).
- Per-panel extras (every Qwen edit of the run gets every extra).
- The Seeds, Locations and Characters tabs (`bin/seed-edit`, `location_dataset.py`, `character_dataset.py` jobs have no `"sources"` and are unchanged).
- The Z-Image stills path and the unedited seed (`as-is`): refused (XR3).
- Lowering `output_resolution` or the reference budget in `seed_edit_mflux_child.py`. **Decided: out of scope** (Decision 9).
- A batch-editor control for `extra_refs` (it is settable through the batch API like `seed_edit_model`, which has no editor control either).
- Content-screening the extra pictures themselves (outputs are screened as today; Risk R7).
- Running a real model, server, render or download in tests; any agent access to macstudio.

### 0.6 Success criteria (KPIs)

| ID | Criterion | Verified by |
|---|---|---|
| XRK1 | The full suite has no failure beyond the baseline F0 recorded at `fcd5d86` (expected `2 failed, 2791 passed, 2 skipped`: `test_d2_copied_literals_match_the_spike`, `test_rst62_import_sets`). The final run is `2 failed, P0+23 passed, 2 skipped` | gate, V1 |
| XRK2 | Without `--extra-ref` (or with `extra_refs: []`) nothing changes: every existing test outside the twelve listed in Section 5.2 passes unedited (in particular SET5-SET15, QET26-QET32, CRT7-CRT18, CXT1-CXT20, SZ1-SZ18 and QET3/QET4/CRT1-CRT6). No `extra_refs/` directory is written, and no record entry gains a key | the unchanged suites, XR-T10, XR-T11 |
| XRK3 | Every refusal (Section 3) happens in `main` before the lockfile and before any phase: exit 2, one `Error:` line, `run_jobs` never called, nothing written under the story directory | XR-T6, XR-T8 |
| XRK4 | Every Qwen edit of the run lists, in order, its own pictures and then every extra's copy; every prompt carries the XR11 sentence with the right picture numbers | XR-T9, XR-T10, XR-T12, XR-T13, XR-T14, XR-T18 |
| XRK5 | An unchanged rerun reuses every edit. A change of any extra's bytes, caption, order or count, or its removal, re-edits exactly the edits that used extras (every edit of the run), and the old stills are moved aside | XR-T11, XR-T12, XR-T13 |
| XRK6 | Live sweep (XR-LV1-XR-LV5, `qwen21-q4`, totals 2, 3, 4, 6 and 10): no child timeout, and every job's `mlx peak memory` is at most `memory_floor("qwen21-q4", total)` (20, 22, 24, 28, 36 GiB). Seconds per panel are recorded | XR-LV1-XR-LV5, report script |
| XRK7 | Live identity at totals 2, 3 and 4: in at least 2 of the 3 panels the seed person keeps their face, hair and clothing; and each captioned extra that a panel's `Image:` mentions is recognisable in at least 2 of the panels that mention it. Totals 6 and 10 are recorded as decision inputs (no pass bar) | XR-LV1-XR-LV5 |
| XRK8 | Live low-RAM refusal: without `--no-low-ram` and without autotune, the exact XR4 `Error:` line, exit 2, and no `extra_refs/` directory. With `QWEN_LTX_AUTOTUNE=1` on the 128 GB host, the same command passes its dry run | XR-LV6, XR-LV7 |

Every XR requirement and XR-T test is a must-have. Every live-check row is a must-have for the user's decision, except XR-LV9 (`qwen2511-bf16`), which may read "not run: <reason>" when that model is not installed. There are no nice-to-haves.

---

## 1. Decisions

1. **Which edit an extra joins (XR3).** The run's edit path is the cast-reference edits when `args.cast_refs` is set, else the seed-context edits when `args.seed_context` is set, else the seed edit when `args.seed_edit` is set (Phase 1c when chained, every still with `--shots`). These are mutually exclusive by the existing resolvers: cast refs refuses `--seed-image`, and seed context needs it. The own-picture count is 2, 2 and 1. For a seed-context run it is 2, the maximum: kind `none` panels have 1. **[spec choice]**
2. **Low-RAM means no extras at all (XR4).** The binding design says "in the default low-RAM mode the effective total stays at 2 as today, so extras are refused". A seed edit with one extra would also total 2. The spec still refuses it, as the binding text says, so that the rule is one sentence on the CLI and one disabled control in Compose (open question 1). **[spec choice: the literal reading]**
3. **The copy (XR6, XR7).** Each extra is written into `<story>/extra_refs/extra_KK.png` (K = 1..9 in `--extra-ref` order) as its EXIF-oriented RGB PNG, the same treatment the seed gets (`seed-original.png`). It is written by each edit phase just before its jobs, so a dry run writes nothing. Stale `extra_*.png` files are removed. The key's `sha256` is the sha256 of the **user's file bytes**, computed once by the resolver, exactly as `source_sha256` is the seed file's sha256 (`:2627-2628`), so the plan can decide reuse before any copy exists. The key item is `{"file", "caption", "sha256"}`: it holds no absolute path, because paths differ between hosts ([CR] CR9 `source_paths` precedent). **[spec choice]**
4. **The prompt sentence (XR11).**
   - The sentence is inserted just before the first `"The new shot: "` of the built prompt: after every prefix sentence (and after the cast-refs position sentence), right before the panel's own text.
   - P1's prompt has no prefix, so there the sentence goes in front.
   - Each extra is "Picture N, the Nth input image, shows CAPTION", or "Picture N, the Nth input image, is one more reference picture" without a caption. The parts are joined with "; ", then ". Use it only where the shot below calls for it. " (one extra) or ". Use each of them only where the shot below calls for it. " (several).
   - "Picture N, the Nth input image" matches the existing prefixes, which name pictures both ways: qwen21 tags `<imageN>`, diffusers writes `Picture N:` ([CR] Decision 4).
   - The prefixes themselves are unchanged, so every existing prompt pin holds. **[spec choice]**
5. **`max_references` is enforced twice (XR8).**
   - By `bin/ltx-movie`'s resolver, before any phase: the user-facing refusal names the model, its cap and how many `--extra-ref` fit.
   - By `qwen_edit.run_jobs`, as a guard before any child: no caller can hand a child more pictures than its model takes.
   - The diffusers child has no hard limit; 3 is the registry policy (the 2511 model card: best with 1-3 input images).
6. **The memory floor (XR9).** `floor(entry, n) = memory_gib + reference_gib x max(0, n - 2)`, with `reference_gib` = 2.0 for the qwen21 family and 3.0 for the qwen2511 family. **[spec choice]**
   - The registry floors stay valid for one and two pictures: the cast-refs and seed-context runs already edit with two at the unchanged floors. So the increment starts at the third, and every existing floor and `wait_for_memory` argument is unchanged.
   - 2.0 GiB: the investigator's estimate from the measured upstream 31.5 GB peak for two references on q8, the 1024² reference budget (about 4096 tokens each), and the qwen21 transformer (32 blocks of width 4096 in the local mflux source). At bf16, each reference token costs about 0.5 MiB of keys and values across the blocks, so 4096 tokens cost about 2 GiB. That is inferred, and XR-LV1-XR-LV5 measure it (XRK6).
   - 3.0 GiB for qwen2511: diffusers on MPS keeps a larger allocator cache, and the 2511 VL tower encodes every picture again.
   - The floor gates the host's total memory at resolve time (`reference_memory_problem`, not in a dry run or `--story-only`) and the available-memory wait before each child (`wait_for_memory(memory_floor(model, n))`). qwen21-q4 at 10 references needs 36 GiB; qwen21-bf16 needs 72 GiB.
7. **The timeout (XR10).** A job with n >= 2 sources counts `MULTI_REFERENCE_TIMEOUT_FACTOR x n / 2` = 3n jobs: 6 for two, exactly as today (CRT1 holds), 9 for three, 30 for ten.
   - Cost model, from [CR] Decision 7: an output of 2304 tokens (1024x576 at 16 px per token) plus 4096 tokens per reference; the MLP grows linearly with the tokens and the attention with their square.
   - So 10 references cost about 0.7 x 6.8 + 0.3 x 6.8² ≈ 18 times a one-reference edit, and 3n (30) leaves about 1.6x headroom. At two references the estimate is about 2 times, and the factor of 6 already left 3x.
   - The timeout only bounds a hang. One ten-picture panel gets max(3600, 600 x 30) = 18000 s. **[spec choice]**
8. **`PATH[:CAPTION]` (XR1, XR2).**
   - When the whole value is an existing file, it is the path and there is no caption. Otherwise the value is split at its **last** `":"`, and the left part must be an existing file. So a caption cannot contain `":"`, but a path that contains `":"` still works without a caption.
   - The caption is stripped of whitespace, then of trailing `"."` and whitespace again (so it ends cleanly before "; "). An empty caption is no caption.
   - The caption is at most 60 characters, with no control character (below U+0020, or U+007F).
   - The same rules hold in Compose V1, where the caption arrives as its own field. **[spec choice]**
9. **`output_resolution` stays 1024 (out of scope).**
   - Lowering the reference budget to 512 would quarter each reference's tokens, but it means passing a new `generate_image` keyword from `seed_edit_mflux_child.py`. That keyword exists in the local 0.21.0 source and is unverified on the pinned 0.24.0.
   - It would also change every multi-reference edit's quality (cast refs and seed context included), and it needs its own A/B.
   - So it is not trivial in the sense of the brief. Follow-up F2.
10. **Uploads reuse `POST /api/uploads` (XR16).** The seed's upload endpoint is already generic: content-addressed `<state>/uploads/<sha256>.<ext>`, the PNG/JPEG/WebP magic check, 20 MiB, write-once, never pruned. A second endpoint would duplicate it byte for byte. The extras field holds upload IDs, as `seed_upload` does. **[spec choice]**
11. **The model cap in the UI is a 400 from the server (XR18).** The model is known only after `_fields_body` cleans the selection (the QE57 precedent: a bad selection is a 400). `movie_ui_lib` cannot import the registry. So V1 (rule 12e) checks the model-independent rules, `_fields_body` refuses a count over the selected model's cap, and `bin/ltx-movie` (through V6, the dry run) stays the final gate. **[spec choice]**
12. **Batch forks (XR20).**
    - `extra_refs` has level `stills`: a change re-edits stills and keeps the story.
    - It joins the seed group in `GROUPS`, so a variant is classified together with the seed and edit model.
    - A fork carries it unchanged. It is cleared to `[]` exactly where a fork already clears `seed_edit_model` (a resolution variant, a `seed_upload: null` variant, and a chained `as-is` story forked to shots), so a fork never keeps extras without an edit.
    - A render-level fork reuses the copied `seed_edits.json` entries, because the extras key holds content hashes, not story paths.
13. **The Compose control (XR19).**
    - It sits inside the existing `c-sq-qwen-box`, which is visible exactly when a seed edit applies (not for the Z-Image engine).
    - It is disabled, with a note, unless No low-RAM mode is ticked, a Qwen model is selected, and that model takes more than one picture.
    - The list is kept while disabled. In that state `composeFields` sends `extra_refs: []`, so the user's uploads survive toggling.
    - The UI requires the explicit tick even when the server's environment would autotune (Risk R10). **[spec choice]**

---

## 2. Architecture and requirements

### 2.1 Architecture

```
bin/ltx-movie ... [--seed-image S --seed-edit-model ID | --shots --cast-refs-model ID ...] --no-low-ram
              --extra-ref A.png:the sword --extra-ref B.png ...
  main: parse -> autotune (may set no_low_ram) -> ... _resolve_seed_edit -> _resolve_cast_refs
        -> _resolve_seed_context -> _resolve_extra_refs (XR1-XR4, XR8, XR9, XR23; sets args.extra_refs)
        -> [dry run: ... _print_extra_refs_plan (XR14)] -> lockfile -> phases
  P1 phase_seed_edit / P2 _phase2_shots_seed / P3 _seed_context_edit / P4 _phase2_cast_refs_batch:
        prompt = _extra_refs_prompt(args, prompt, own)            (XR11; at plan time, so keys see it)
        key   += _extra_refs_item(args)  {"extras": [{file, caption, sha256}, ...]}   (XR7)
        reuse  also needs entry.get("extras") == key.get("extras")                     (XR7)
        _extra_refs_note(args); _extra_refs_write(args)  -> <story>/extra_refs/extra_KK.png   (XR6, XR13)
        job = _extra_refs_job(args, job)   sources = own pictures + extras' copies         (XR12)
        qe.wait_for_memory(qe.memory_floor(model, _edit_references(jobs)))               (XR9)
        qe.run_jobs(...)  -> guard: len(sources) <= max_references; timeout weight 3n     (XR8, XR10)
        record entry  += _extra_refs_item(args)  (last key)                              (XR7)
movie-ui Compose: extra_refs [{upload_id, caption}] -> V1 rule 12e -> _fields_body cap (400)
        -> build_argv: --extra-ref <state>/uploads/<id>[:caption]  -> V6 dry run -> job
```

---

### 2.2 Requirements

**`qwen_edit.py` and `movie_ui_seedgen.py` (Task 1).**

- **XR8 (registry and guard).**
  - Every `QWEN_MODELS` entry gains `"max_references"` and `"reference_gib"`, placed right after `"memory_gib"`: `qwen21-q4`, `qwen21-q8` and `qwen21-bf16` get `10, 2.0`; `qwen2511-q4` gets `1, 3.0`; `qwen2511-bf16` gets `3, 3.0`. `registry_view` adds `"max_references"` after `"memory_gib"` (G1-G6).
  - `qwen_edit.max_references(model_id)` returns the entry's value.
  - `run_jobs` raises `Unavailable("<label> takes at most <cap> reference images per edit; job <n> lists <k>")` before the install check and before any child, when a job's `"sources"` lists more than the cap. This check runs after the existing multi-reference refusal, so `qwen2511-q4` with two sources still gets the CR1 text (Q5).
- **XR9 (floor).** `qwen_edit.entry_floor(entry, references=1)` returns `memory_gib + reference_gib x max(0, references - 2)`. The other functions use it:
  - `memory_problem(entry, references=1)`, with the same text as today and the raised floor in it;
  - `memory_floor(model_id, references=1)`;
  - `reference_memory_problem(model_id, references)`, which returns `None` or `"<label> with <n> reference images is unavailable: <memory_problem text>"` (Q2, Q3).
- **XR10 (timeout).** `jobs_timeout`: a job whose `"sources"` lists n >= 2 images weighs `MULTI_REFERENCE_TIMEOUT_FACTOR * n // 2`; any other job weighs 1 (Q4). `MULTI_REFERENCE_TIMEOUT_FACTOR` stays 6.

**`bin/ltx-movie` (Task 1).**

- **XR1 (flag).** `--extra-ref` (dest `extra_ref_specs`, `action="append"`, default `None`, metavar `PATH[:CAPTION]`), right after `--seed-context-order`. The exact help text is in M3, pinned by XR-T17.
- **XR2 (values).** `_resolve_extra_refs` parses each value by Decision 8. It refuses, in this order, each with one `Error:` line and exit 2:
  - more than `EXTRA_REFS_MAX` = 9 values;
  - a value whose path is not an existing file;
  - a bad caption;
  - a file `ltx_image_fit.load_oriented_rgb` cannot read;
  - two values with the same file bytes (sha256).
- **XR3 (the edit path).**
  - `--seed-edit-model as-is` is refused first (`EXTRA_REFS_AS_IS_ERROR`).
  - Otherwise `_extra_refs_edit(args)` gives `(model_id, own, words)`: cast refs `(cast model, 2, "the two characters' reference stills")`, else seed context `(seed model, 2, "the seed and the context picture")`, else seed edit `(seed model, 1, "the seed")`.
  - When it returns `None` (no Qwen edit in the run: no seed edit model, plain unseeded shots, or a cast-refs no-op with fewer than two cast members), the run is refused (`EXTRA_REFS_NO_EDIT_ERROR`).
- **XR4 (low-RAM).** `args.no_low_ram` false → refused (`EXTRA_REFS_LOW_RAM_ERROR`). It is read after autotune (Section 0.3).
- **XR5 (constants).** M2 adds them all: `EXTRA_REFS_MAX`, `EXTRA_REFS_WARN_ABOVE`, `EXTRA_REFS_CAPTION_MAX`, `EXTRA_REFS_DIR`, `EXTRA_REFS_ANCHOR`, `EXTRA_REFS_ORDINALS`, `EXTRA_REFS_NO_CAPTION`, `EXTRA_REFS_USE_ONE`, `EXTRA_REFS_USE_MANY`, the three error texts, the warning and the unused note.
- **XR6 (copies).** `_extra_refs_paths(args)` gives `<story>/extra_refs/extra_KK.png` in order. `_extra_refs_write(args)` first removes every other `extra_*.png` there, then writes each copy through `<path>.tmp` and `os.replace`. Each edit phase calls it once, after its header and before its first job (P1 and P2 only when there is something to edit, P3 before its panel loop, P4 before its jobs).
- **XR7 (key and record).**
  - `_extra_refs_item(args)` is `{"extras": [{"file", "caption", "sha256"}, ...]}` with extras, else `{}`.
  - It is merged into every key: P1 `key`, P2 `keys[n]`, P3 `base[n]`, P4 `keys[n]`. It is merged as the **last** key of every record entry and of `seed_edit.json`.
  - Every reuse test also requires `entry.get("extras") == key.get("extras")`. So a record with extras is never reused by a run without extras, and a record without extras is reused by a run without extras exactly as today.
- **XR11 (prompt).** `_extra_refs_prompt(args, prompt, first)` (Decision 4) is applied where each path builds its prompts:
  - P1 after its empty-prompt check, with `first` = 1;
  - P2 to every `(n, prompt)` after the empty check, with `first` = 1;
  - P3 per panel, with `first` = 1 for kind `none` and 2 otherwise;
  - P4 to every pair prompt, with `first` = 2.
- **XR12 (sources).** `_extra_refs_job(args, job)` sets `job["sources"] = (job["sources"] or [job["source"]]) + _extra_refs_paths(args)` when the run has extras. `"source"` stays the first own picture. So the order is: the seed, then the context picture (in its `--seed-context-order` place) or the two cast stills, then the extras in `--extra-ref` order. Without extras the job is unchanged (no `"sources"` key for P1 and P2).
- **XR9 (wait).** Each phase's `qe.wait_for_memory(qe.memory_floor(model_id), ...)` becomes `qe.memory_floor(model_id, _edit_references(jobs))`, where `_edit_references(jobs)` is the largest `len(job["sources"])`, or 1 for a job without sources. Values are unchanged for one or two pictures.
- **XR13 (lines).** `_extra_refs_note(args)` prints one line per edit phase, right before the copies are written:
  `extra refs: every Qwen edit here also gets <k> extra reference pictures after its own: <copy path> ("<caption>"); <copy path> (no caption)`.
  A cast-refs run whose story has no pair panel also prints `EXTRA_REFS_UNUSED_NOTE` after `CAST_REFS_NONE_NOTE`.
- **XR14 (dry run).** With extras, `_print_dry_run_plan` prints an `--- Extra references ---` block, then a blank line, right before `--- Phase 3: manifest + dry-run ---` (Section 3). It writes nothing and reads no weights.
- **XR15 (docstring and help).** The Extra references paragraph (M1) goes between the Seed edit and Seed context paragraphs. The help text is M3's.
- **XR21 (byte-identical default).** Every new path is gated by `args.extra_refs` being non-empty (set only by XR1-XR4), read with `getattr(args, "extra_refs", None) or []`. So hand-built `argparse.Namespace` test arguments without it behave as before. The new `memory_floor` argument returns the old value for one or two pictures.
- **XR23 (warning).** When the total (own + extras) is above `EXTRA_REFS_WARN_ABOVE` = 4, the resolver prints `EXTRA_REFS_MANY_WARNING` to stdout once.
- **XR9 (host check).** Unless `--dry-run` or `--story-only`, the resolver calls `qe.reference_memory_problem(model_id, total)`; a problem is refused (`Error: --extra-ref: <text>`). It runs last, after the cap check and the warning.

**Movie UI (Task 2).**

- **XR16 (field, flag, argv).**
  - `DEFAULT_FIELDS["extra_refs"] = []`, right after `seed_edit_loras`.
  - `FIELD_FLAGS` gains `("extra_refs", ("--extra-ref",))` right before `seed_edit`, which stays last.
  - `build_argv` adds `["--extra-ref", extra_ref_arg(state, item)]` per item, inside the seed block, after the seed-edit flags. `extra_ref_arg` is `<state>/uploads/<upload_id>`, plus `":" + caption.strip()` when the stripped caption is not empty.
- **XR17 (V1 rule 12e).** `_rule_extra_refs(fields, state)` runs right after rule 12d. The exact texts are in Section 3.
- **XR18 (server cap).** In `_fields_body`, after the selection is cleaned and only for a registry model:
  - with `max_references == 1` and at least one extra: 400 `"<label> reads only the first picture, so it takes no extra references"`;
  - otherwise, when `1 + len(extra_refs) > max_references`: 400 `"<label> takes at most <cap> reference images per edit (the seed and <cap - 1> extra references); this request has <k> extra references"`.
- **XR19 (Compose).** Section 1 Decision 13 and edits U9-U15: the `c-xr-box`, `composeExtrasModel`, `composeExtrasUpdate` (which sets `S.extrasOn`), `onExtraFile`, the `composeFields` line, the `fillCompose` restore, and the `setupCompose` listeners.
- **XR20 (batch).** Decision 12; edits U6, U7.

**Task 3.**

- **XR22.** `NEW_PY` is not extended ([CR] CR15). The three new test files meet the `NEW_PY` rules by construction: no `load_module(`, no `urllib`; they use `SourceFileLoader` + `exec_module`. Each task compiles them on Python 3.9 and 3.13.
- **XR24.** `test_mut26`'s BASELINE moves once, after the last code commit (Task 1's commit is the last one touching `bin/ltx-movie`), in a test-only commit.

---

## 3. Messages and text (exact)

`<value>` is the `--extra-ref` value as given; `<label>` is the registry label (`qwen_edit.label`).

| Condition | Where | Text | Effect |
|---|---|---|---|
| `--seed-edit-model as-is` | `_resolve_extra_refs` | `Error: --extra-ref cannot be combined with --seed-edit-model as-is: the seed is used unedited (with --shots, the Z-Image engine renders every other still), so no Qwen edit would see the extra references; choose a Qwen --seed-edit-model ID` | exit 2 |
| no Qwen edit in the run | same | `Error: --extra-ref needs a Qwen edit in this run: --seed-image with --seed-edit-model ID (panel 1 in chained mode, every still with --shots), or --shots with --cast-refs-model ID and at least two cast characters` | exit 2 |
| low-RAM mode | same | `Error: --extra-ref needs --no-low-ram: in low-RAM mode (the default) a Qwen edit takes at most 2 reference images, so extra references are off; on a host with at least 96 GiB of memory pass --no-low-ram, or set QWEN_LTX_AUTOTUNE=1 to turn it on there automatically` | exit 2 |
| more than 9 | same | `Error: --extra-ref is given <k> times; at most 9 extra references are allowed` | exit 2 |
| no such file | same | `Error: --extra-ref <value>: no such image file (the form is PATH or PATH:CAPTION, and a caption cannot contain ':')` | exit 2 |
| bad caption | same | `Error: --extra-ref <value>: the caption must be at most 60 characters with no control characters` | exit 2 |
| unreadable | same | `Error: --extra-ref <value>: cannot read it as an image (<ExceptionType>: <message>)` | exit 2 |
| same bytes | same | `Error: --extra-ref <first value> and <value> are the same image bytes; give each extra reference once` | exit 2 |
| model takes 1 picture | same | `Error: --extra-ref: <label> reads only the first input image, so it takes no extra references; choose a qwen21 model (up to 9) or qwen2511-bf16 (up to 2)` | exit 2 |
| over the cap | same | `Error: --extra-ref: <label> takes at most <cap> reference images per edit, and each edit of this run would take <total> (<words>, then <k> extra references); give at most <cap - own> --extra-ref` | exit 2 |
| over 4 in total | same | `Warning: --extra-ref: each Qwen edit of this run takes up to <total> reference images (<words>, then <k> extra references); above 4 the edit models are past the 1 to 3 input images they are tuned for, so faces, clothing and props can blend or drift: check every still` | stdout, once; continues |
| host memory | same | `Error: --extra-ref: <label> with <total> reference images is unavailable: needs a host with at least <floor> GiB of memory (this host has <t> GiB)` | exit 2 (not in a dry run or `--story-only`) |
| cast refs, no pair panel | Phase 2 | `note: --extra-ref: no panel is a cast-reference Qwen edit, so the extra references are not used` | stdout, after `CAST_REFS_NONE_NOTE` |
| edit phase | P1-P4 | `extra refs: every Qwen edit here also gets <k> extra reference pictures after its own: <path> ("<caption>"); <path> (no caption)` | stdout |
| over the model cap at run time | `qwen_edit.run_jobs` | `<label> takes at most <cap> reference images per edit; job <n> lists <k>` | `Unavailable` (each phase turns it into its existing failure line) |

`<words>` is `the seed`, `the seed and the context picture` or `the two characters' reference stills`. `<floor>` is printed with `%g`.

**The prompt sentence** (`_extra_refs_prompt`). Examples, with `first` = 1 and the captions `the sword` and none:

```
...leave out anyone the new shot does not describe. Picture 2, the second input image, shows the sword; Picture 3, the third input image, is one more reference picture. Use each of them only where the shot below calls for it. The new shot: <Image: text> <Style: text>
```

With one extra:

```
Picture 2, the second input image, shows the sword. Use it only where the shot below calls for it. 
```

Here the sentence ends with one space. In P1 (no anchor), the sentence is the prompt's first text. With `first` = 2 (cast refs and seed-context context panels) the numbers start at 3 ("the third input image"). Nine extras with `first` = 1 run to "Picture 10, the tenth input image".

**The dry-run block** (XR14):

```
--- Extra references ---
Would add <k> extra reference pictures to every Qwen edit of this run with <label>, after the edit's own pictures (<words>), each named in the edit prompt by its picture number and caption; each edit takes up to <own + k> of the model's <cap> reference images. They are copied into <story dir>/extra_refs when the edits run; a changed picture, caption, order or count re-edits every still that used it.
  extra 1: <absolute source path> ("<caption>")
  extra 2: <absolute source path> (no caption)

--- Phase 3: manifest + dry-run ---
```

**V1 rule 12e** (`movie_ui_lib._rule_extra_refs`), in this order:

| Condition | Text |
|---|---|
| not a list, more than 9 items, or an item that is not a dict with exactly the keys `upload_id` and `caption` | `extra references must be a list of at most 9 {upload_id, caption} items` (the only line) |
| item k's upload is not an `UPLOAD_ID_RE` id of an existing `<state>/uploads/` file | `extra reference <k>: upload <id> not found` |
| item k's caption is not `None`, and is not a str with 1 to 60 characters after strip, with no `:`, no control character and argv-safe | `extra reference <k>: caption must be 1 to 60 characters with no ':' and no control characters` |
| the same upload twice | `extra references must be distinct images` |
| items, and no seed or a seed edit model of `None` or `as-is` | `extra references need a seed image and a Qwen seed edit model (not as-is)` |
| items, and `no_low_ram` is not `True` | `extra references need No low-RAM mode (--no-low-ram): in low-RAM mode a Qwen edit takes at most 2 pictures` |

**Compose notes** (app.js, `#c-xr-note`):
- `XR_LOW_RAM_NOTE = "Extra references need No low-RAM mode (under Advanced): in low-RAM mode every Qwen edit takes at most 2 pictures. Tick it only on a host with at least 96 GiB of memory."`
- `XR_AS_IS_NOTE = "Extra references need a Qwen edit of the seed; the seed as-is is not edited."`
- The model takes one picture: `<label> reads only the first picture, so it takes no extra references.`
- Over the cap: `<label> takes at most <max> extra references; remove <k - max>.`
- Otherwise: `Each Qwen edit gets the seed as Picture 1, then these pictures in order (up to <max> with <label>). A caption names what a picture shows, e.g. the sword. More than 4 pictures in all can blend faces, clothing and props.`

None of the new stdout lines matches the movie-ui progress patterns (`^panel (\d+) ok: `, `^panel (\d+): reusing `, `^panel (\d+) FAILED \(`, `^=== panel (\d+)/(\d+) \(`, `^=== Phase ...`).

---

## 4. What changes for existing runs and records

| Reader / writer | Verdict |
|---|---|
| Every run without `--extra-ref` | Unchanged: `args.extra_refs` is `[]`. No helper adds a key, prints a line or writes a file. `memory_floor(model, 1 or 2)` equals today's floor, and `jobs_timeout` is unchanged for one and two pictures (CRT1 holds) |
| Existing `seed_edit.json`, `seed_edits.json`, `seed_context_edits.json`, `cast_ref_edits.json` | No entry has `"extras"`, so `entry.get("extras") is None == key.get("extras")` without extras, and they are reused as today. A run with extras re-edits them (their prompt and `extras` differ) |
| `bin/seed-edit`, `character_dataset.py`, `location_dataset.py` (`run_jobs` callers without `sources`) | Unchanged: the guard counts `"sources"` only, and their memory checks call `memory_problem(entry)` with the default |
| The registry pins | SQT10 and SQT16 are edited (E1, E2); every other reader of `QWEN_MODELS` ignores the new keys |
| `bin/ltx-movie --help` | One new option; `lib.help_flags` sees `--extra-ref`, which the new `FIELD_FLAGS` entry maps |
| Old saved Compose jobs (fields without `extra_refs`) | `compose_fields` fills `[]`; their argv is unchanged |
| Render-level batch forks of a story with extras | The fork copies `seed_edits.json` (`COPY_FILES["render"]`) and reuses every still, because the extras key holds content hashes. The fork's `extra_refs/` copies are written only if it edits |
| The deploy package (`scripts/deploy/build_pkg.py` ships `bin/ltx-movie`, not `qwen_edit.py`) | `--extra-ref` without a Qwen edit gets the "needs a Qwen edit" refusal; with one, the seed-edit resolver already refuses there |

---

## 5. Tests

### 5.1 New tests

Header style: as `tests/test_qwen_edit_cast_refs.py` and `tests/test_ltx_movie_cast_refs.py` (a docstring naming this spec, the run line, "No test loads a model, renders, contacts a server or touches port 8177 or 8178. Stdlib, PIL and pytest.").
- `tests/test_ltx_movie_extra_refs.py` loads `bin/ltx-movie` as `ltx_movie_xr` (SourceFileLoader, spec_from_loader, module_from_spec, exec_module).
- It imports, unchanged, `_FakeShotsQwenEdit`, `_phase_args`, `_write_story`, `_seed1920`, `_seed_jpeg`, `_prompt` (as `sse_prompt`), `_sha`, `_still`, `_record`, `PREFIX`, `ENTRY_KEYS`, `UNC` from `test_ltx_movie_shots_seed`; `qe_fake` (the fixture, under its own name), `_edit_args`, `_files`, `_write_story`, `PROMPT` from `test_ltx_movie_seed_edit` (as `se_*` aliases except the fixture); `ctx_env` (the fixture), `_args`, `_story`, `_prompt`, `IMAGES` from `test_ltx_movie_seed_context` (as `cx_*` except the fixture); `_FakeCastRefsQwenEdit`, `_cast`, `_story`, `_args`, `_prompt`, `cast_env` from `test_ltx_movie_cast_refs` (as `cr_*`; `cast_env` imported under its own name so pytest finds it); and `_bf16_cache`, `_mflux_ready`, `env` from `test_qwen_edit`. `tests/test_movie_ui_extra_refs.py` imports `env`, `_upload`, `_compose`, `UP` from `test_movie_ui_qwen_edit`, and `FAKE_COMPOSE`, `_compose_page_code`, `_node`, `_page`, `_function` from `test_movie_ui_shots_zimage`; its state directory is `mt.set_home(monkeypatch, tmp_path)` where no `env` fixture is used.

**Shared helpers of `tests/test_ltx_movie_extra_refs.py`:**
- `_xr(fake)` adds what the resolver needs to any fixture's fake (the instance its `_qwen_edit` patch returns) and returns it: `fake.max_references = qwen_edit.max_references`, `fake.multi_reference_problem = qwen_edit.multi_reference_problem`, `fake.MULTI_REFERENCE_MODEL_IDS = qwen_edit.MULTI_REFERENCE_MODEL_IDS`, `fake.memory_answer = None`, `fake.calls["reference_memory_problem"] = []`, and `fake.reference_memory_problem = lambda model_id, references: fake.calls["reference_memory_problem"].append((model_id, references)) or fake.memory_answer`.
- `xr_env` fixture: as `clean_env` of `tests/test_ltx_movie_shots_seed.py:141-156` with `_xr(_FakeShotsQwenEdit())`, plus `monkeypatch.delenv("QWEN_LTX_AUTOTUNE", raising=False)` and `monkeypatch.delenv("QWEN_LTX_MEM_GIB", raising=False)`. Returns `{"tmp", "fake"}`.
- `_pic(tmp, name, color, size=(64, 48))` writes `<tmp>/x/<name>.png` and returns its path. `_extras(tmp, *specs)` resolves through `movie._resolve_extra_refs` on a `Namespace(extra_ref_specs=list(specs), seed_edit_model="qwen21-q4", cast_refs=None, seed_context=None, seed_edit={"qwen_model": "qwen21-q4", "loras": UNC}, no_low_ram=True, dry_run=True, story_only=False)`, asserts it returns 0, and returns `args.extra_refs`.
- `SENT1 = "Picture 2, the second input image, shows the sword; Picture 3, the third input image, is one more reference picture. Use each of them only where the shot below calls for it. "` (the sword, then no caption, with `first` = 1).
- `def _with(prompt, sentence): i = prompt.index("The new shot: "); return prompt[:i] + sentence + prompt[i:]`.

| Test | File, task | Exact assertions |
|---|---|---|
| **XR-T1** `test_xrt1_the_registry` | `test_qwen_edit_extra_refs.py`, 1 | `[(m["id"], m["max_references"], m["reference_gib"]) for m in seedgen.QWEN_MODELS] == [("qwen21-q4", 10, 2.0), ("qwen21-q8", 10, 2.0), ("qwen21-bf16", 10, 2.0), ("qwen2511-q4", 1, 3.0), ("qwen2511-bf16", 3, 3.0)]`. For every model, `list(m)` has `"max_references", "reference_gib"` right after `"memory_gib"`. `[v["max_references"] for v in seedgen.registry_view()["models"]] == [10, 10, 10, 1, 3]`, and each view's keys have `"max_references"` right after `"memory_gib"`. `[qe.max_references(i) for i in qe.MODEL_IDS] == [10, 10, 10, 1, 3]` |
| **XR-T2** `test_xrt2_the_memory_floor` | same, 1 | `[qe.memory_floor("qwen21-q4", n) for n in (1, 2, 3, 4, 6, 10)] == [20.0, 20.0, 22.0, 24.0, 28.0, 36.0]`; `qe.memory_floor("qwen21-q4") == 20.0`; `qe.memory_floor("qwen21-bf16", 10) == 72.0`; `qe.memory_floor("qwen2511-bf16", 3) == 67.0`; `qe.entry_floor(seedgen.qwen_model("qwen21-q8"), 4) == 36.0`. With `monkeypatch.setattr(qe, "total_gib", lambda: 32.0)`: `qe.memory_problem(seedgen.qwen_model("qwen21-q4")) is None`; `qe.memory_problem(seedgen.qwen_model("qwen21-q4"), 10) == "needs a host with at least 36 GiB of memory (this host has 32.0 GiB)"`; `qe.reference_memory_problem("qwen21-q4", 8) is None` (32 GiB); `qe.reference_memory_problem("qwen21-q4", 10) == "Qwen-Image-2.1 q4 with 10 reference images is unavailable: needs a host with at least 36 GiB of memory (this host has 32.0 GiB)"`; `qe.selection_problem("qwen21-q4", [])` does not mention "reference images" (with `install_problem` monkeypatched to return `(None, {})`, it is `None`) |
| **XR-T3** `test_xrt3_the_timeout_scales_with_the_references` | same, 1 | `qe.MULTI_REFERENCE_TIMEOUT_FACTOR == 6`. For n in (1, 6, 7, 24), `qe.jobs_timeout([{"n": 1}] * n) == qe.child_timeout(n)`. `[qe.jobs_timeout([{"n": 1, "sources": ["a"] * k}]) for k in (1, 2, 3, 4, 6, 10)] == [3600, 3600, 5400, 7200, 10800, 18000]`. `qe.jobs_timeout([{"n": 1, "sources": ["a", "b"]}] * 3) == 10800` (CRT1's value). `qe.jobs_timeout([{"n": 1, "sources": ["a"] * 10}, {"n": 2}]) == 18600` |
| **XR-T4** `test_xrt4_run_jobs_refuses_more_than_the_cap_mflux` | same, 1 | `py, _s, _l = _mflux_ready(env)` (the CRT2 setup). Eleven distinct 64x48 PNGs `r[0..10]`, and a job helper `job(k) = {"n": 1, "seed": 7, "prompt": "p", "source": r[0], "sources": r[:k], "stage_path": <out>/cand_01.pending.png, "output_path": <out>/cand_01.png}`. `qe.run_jobs("qwen21-q4", UNC, [job(11)], 1024, 576, "x", work)` raises `qe.Unavailable` with `str == "Qwen-Image-2.1 q4 takes at most 10 reference images per edit; job 1 lists 11"`, and `st.stub_calls(py) == []`. With the `run_child` spy of CRT2, `run_jobs(..., [job(10)], ...)` returns failure `None`; the one stub call's `spec["jobs"][0]["sources"] == r[:10]`; and the spy saw `[18000]`. With `_mflux_ready(env, "qwen2511-q4")`, a two-source job raises CR1's text exactly (`"Qwen-Image-Edit-2511 q4 (Lightning) cannot edit with several reference images: " + qe.MULTI_REFERENCE_REFUSED["qwen2511-q4"]`) |
| **XR-T5** `test_xrt5_run_jobs_refuses_more_than_the_cap_diffusers` | same, 1 | `_bf16_cache(env)`; `stub = st.qwenedit_stub(env, {})`. `run_jobs("qwen2511-bf16", [], [job(4)], ...)` raises with `str == "Qwen-Image-Edit-2511 bf16 (Lightning, diffusers) takes at most 3 reference images per edit; job 1 lists 4"`, and `st.stub_calls(stub) == []`. `run_jobs(..., [job(3)], ...)` succeeds, and the spec item has `"images" == r[:3]` |
| **XR-T6** `test_xrt6_the_refusals` | `test_ltx_movie_extra_refs.py`, 1 | Each case calls `movie._resolve_extra_refs(ns)` on an `argparse.Namespace` with the keys of `_extras` and the overrides shown. Each returns 2, with `capsys.readouterr().err` equal to the Section 3 line plus `"\n"`, an empty stdout, and `ns.extra_refs == []`.<br>(a) `seed_edit_model="as-is", seed_edit=None`: AS_IS.<br>(b) `seed_edit_model=None, seed_edit=None`: NO_EDIT.<br>(c) a cast-refs no-op, `seed_edit=None, seed_edit_model=None, cast_refs=None, cast_refs_model="qwen21-q4"` (fewer than two cast members): NO_EDIT.<br>(d) `no_low_ram=False`: LOW_RAM.<br>(e) ten valid values: `"Error: --extra-ref is given 10 times; at most 9 extra references are allowed\n"`.<br>(f) `"<tmp>/x/nope.png"`, and `"<a>:the sword: ornate"` (a = an existing file): the "no such image file" line with the value as given.<br>(g) `"<a>:" + "x" * 61` and `"<a>:the\tsword"`: the caption line.<br>(h) a text file `bad.png` (`b"not an image"`): err starts with `"Error: --extra-ref %s: cannot read it as an image (UnidentifiedImageError: " % bad`.<br>(i) `[a, copy_of_a]` (same bytes, two names): `"Error: --extra-ref %s and %s are the same image bytes; give each extra reference once\n" % (a, copy_of_a)`.<br>(j) `seed_edit={"qwen_model": "qwen2511-q4", "loras": []}` with one extra: the "reads only the first input image" line with label `Qwen-Image-Edit-2511 q4 (Lightning)`.<br>(k) `qwen2511-bf16` seed edit with 3 extras: `"Error: --extra-ref: Qwen-Image-Edit-2511 bf16 (Lightning, diffusers) takes at most 3 reference images per edit, and each edit of this run would take 4 (the seed, then 3 extra references); give at most 2 --extra-ref\n"`.<br>(l) `cast_refs={"qwen_model": "qwen2511-bf16", "loras": [], "stills": {}}` with 2 extras: `... would take 4 (the two characters' reference stills, then 2 extra references); give at most 1 --extra-ref`.<br>(m) `seed_context={"mode": "still", "order": "seed-first"}` with qwen21-q4 and 9 extras: `"Error: --extra-ref: Qwen-Image-2.1 q4 takes at most 10 reference images per edit, and each edit of this run would take 11 (the seed and the context picture, then 9 extra references); give at most 8 --extra-ref\n"` (the over-4 warning is not printed, because the cap check comes first).<br>(n) `dry_run=False` with 2 extras and `fake.memory_answer = "Qwen-Image-2.1 q4 with 3 reference images is unavailable: needs a host with at least 22 GiB of memory (this host has 16.0 GiB)"`: err is `"Error: --extra-ref: " + that + "\n"`, and `fake.calls["reference_memory_problem"] == [("qwen21-q4", 3)]`.<br>**None of (a)-(e) calls `movie._qwen_edit`:** the fixture's fake is replaced by `lambda: pytest.fail("loaded")` for them |
| **XR-T7** `test_xrt7_the_resolved_extras` | same, 1 | `a = _pic(tmp, "a", (200, 0, 0))`, `b = _pic(tmp, "b", (0, 200, 0))`, `c = _pic(tmp, "c", (0, 0, 200))`. `_extras(tmp, a + ":  the sword. ", b, c + ":")` equals `[{"path": os.path.abspath(a), "caption": "the sword", "sha256": _sha(a), "file": "extra_refs/extra_01.png"}, {"path": os.path.abspath(b), "caption": None, "sha256": _sha(b), "file": "extra_refs/extra_02.png"}, {"path": os.path.abspath(c), "caption": None, "sha256": _sha(c), "file": "extra_refs/extra_03.png"}]`. A file literally named `<tmp>/x/d:e.png` (no caption) resolves with that path and caption `None`. With no values (`extra_ref_specs=None`), the call returns 0, `ns.extra_refs == []`, and `_qwen_edit` is not called. **Warning:** four extras on a qwen21-q4 seed edit (total 5) return 0, and stdout is exactly `"Warning: --extra-ref: each Qwen edit of this run takes up to 5 reference images (the seed, then 4 extra references); above 4 the edit models are past the 1 to 3 input images they are tuned for, so faces, clothing and props can blend or drift: check every still\n"`. Three extras (total 4) print nothing. In a dry run, `fake.calls["reference_memory_problem"] == []` |
| **XR-T8** `test_xrt8_low_ram_is_read_after_autotune` | same, 1 | Through `movie.main(argv)` with `argv = ["a narrative", "--story-id", "s1", "--dry-run", "--no-review", "--no-auto-lora", "--shots", "--seed-image", _seed1920(tmp), "--seed-edit-model", "qwen21-q4", "--extra-ref", a + ":the sword"]`:<br>(1) no autotune variable: `rc == 2`, and the stderr's last line is LOW_RAM;<br>(2) `+ ["--no-low-ram"]`: `rc == 0`, and stdout has the block of XR-T16;<br>(3) `QWEN_LTX_AUTOTUNE=1` and `QWEN_LTX_MEM_GIB=128`, without `--no-low-ram`: `rc == 0`, `"no_low_ram=True" in err`, and stdout has `"--- Extra references ---"`;<br>(4) `QWEN_LTX_AUTOTUNE=1` and `QWEN_LTX_MEM_GIB=64`: `rc == 2`, with LOW_RAM.<br>In every case `fake.calls["run_jobs"] == []`, and `<tmp>/stories/s1/extra_refs` does not exist |
| **XR-T9** `test_xrt9_the_prompt_sentence` | same, 1 | The constants: `movie.EXTRA_REFS_ANCHOR == "The new shot: "`, `movie.EXTRA_REFS_ORDINALS == ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth")`, `movie.EXTRA_REFS_NO_CAPTION == "is one more reference picture"`, `movie.EXTRA_REFS_USE_ONE == ". Use it only where the shot below calls for it. "`, `movie.EXTRA_REFS_USE_MANY == ". Use each of them only where the shot below calls for it. "`, `(movie.EXTRA_REFS_MAX, movie.EXTRA_REFS_WARN_ABOVE, movie.EXTRA_REFS_CAPTION_MAX, movie.EXTRA_REFS_DIR) == (9, 4, 60, "extra_refs")`.<br>With `ns.extra_refs = []`, `_extra_refs_prompt(ns, P, 1) is P`, for `P = PREFIX + "x"`.<br>With the sword and no caption: `_extra_refs_prompt(ns, PREFIX + "x", 1) == _with(PREFIX + "x", SENT1)`. P1's form `_extra_refs_prompt(ns, "A gate.", 1) == SENT1 + "A gate."`. With `first=2`, the numbers are `Picture 3, the third` and `Picture 4, the fourth`.<br>One extra, "the throne room": `... == _with(P, "Picture 2, the second input image, shows the throne room. Use it only where the shot below calls for it. ")`.<br>The cast-refs prompt with its position sentence, `cr_prompt(2)`: the sentence lands after `"is on the right. "` and right before `"The new shot: "`.<br>Nine extras with `first=1`: the sentence ends `"Picture 10, the tenth input image, is one more reference picture. Use each of them only where the shot below calls for it. "` |
| **XR-T10** `test_xrt10_seeded_shots_with_extras` | same, 1 | `story_dir = _write_story(tmp)`. `x1 = _seed_jpeg(<tmp>/x/x1.jpg, (200, 0, 0))` (oriented 100x200) and `x2 = _pic(tmp, "x2", (0, 200, 0))`. `args = _phase_args(tmp, extra_refs=_extras(tmp, x1 + ":the sword", x2))`. A stale `<story>/extra_refs/extra_03.png` is written first.<br>`movie._phase2_shots_seed(args) == 0`, and its one `run_jobs` call has jobs `[{"n": n, "seed": 3, "prompt": _with(sse_prompt(n), SENT1), "source": original, "sources": [original, e1, e2], "stage_path": ..., "output_path": ...} for n in (1, 2, 3)]` (`e1`, `e2` = `<story>/extra_refs/extra_01.png`, `extra_02.png`).<br>`fake.calls["wait_for_memory"] == [(22.0, "Qwen-Image-2.1 q4", "ltx-movie")]`.<br>`e1` is a PNG of size `(100, 200)` and `e2` of `(64, 48)`; `extra_03.png` is gone.<br>Every record entry has `list(entry) == ENTRY_KEYS + ["extras"]`, and `entry["extras"] == [{"file": "extra_refs/extra_01.png", "caption": "the sword", "sha256": _sha(x1)}, {"file": "extra_refs/extra_02.png", "caption": None, "sha256": _sha(x2)}]`.<br>Stdout lines: `[<the unchanged header>, 'extra refs: every Qwen edit here also gets 2 extra reference pictures after its own: %s ("the sword"); %s (no caption)' % (e1, e2), <the three panel lines>, "seed edits: 3 panel stills written"]` |
| **XR-T11** `test_xrt11_reuse_and_change` | same, 1 | After XR-T10's first run (a fresh `_phase_args` each time), with `n_calls` = the number of `run_jobs` calls and `jobs[-1]` = the last call's panels:<br>(1) the same extras: no new call; stdout has `"seed edits: every panel's still is a recorded edit of the same seed image, prompt, seed and settings; nothing to edit"`;<br>(2) caption `"the long sword"`: panels `[1, 2, 3]`, and the three old stills are moved into `redo/<stamp>-<pid>/images/`;<br>(3) new bytes for `x2` (colour `(0, 0, 250)`): `[1, 2, 3]`;<br>(4) the two extras swapped: `[1, 2, 3]`;<br>(5) only `x1`: `[1, 2, 3]`;<br>(6) no extras (`extra_refs=[]`): `[1, 2, 3]`, the jobs have no `"sources"` key, and the entries have no `"extras"`;<br>(7) no extras again: no new call;<br>(8) `--redo 2` (`redo_panels=[2]`) with the extras of (5): `[1, 2, 3]` once, because the prompts changed, then `redo_panels=[2]` again: `[2]` |
| **XR-T12** `test_xrt12_phase_1c_with_extras` | same, 1 | The `qe_fake` fixture (`tests/test_ltx_movie_seed_edit.py:92-105`), with `_xr(qe_fake)`. `se_write_story(tmp_path)`; `files = se_files(story_dir)`. `args = se_edit_args(tmp_path)` plus `args.extra_refs = _extras(tmp, x + ":the throne room")`. `movie.phase_seed_edit(args) == 0`. Its job is `{"n": 1, "seed": 3, "prompt": "Picture 2, the second input image, shows the throne room. Use it only where the shot below calls for it. " + se_PROMPT, "source": files["original"], "sources": [files["original"], <story>/extra_refs/extra_01.png], "stage_path": ..., "output_path": ...}`. `wait_for_memory == [(20.0, "Qwen-Image-2.1 q4", "ltx-movie")]`. `list(record)` is QET28's key list plus `["extras"]`. A rerun reuses it (stdout `seed edit: reusing ...`, no new call). The caption `"the hall"` makes one new call. A record written without extras (QET28's run, then `args.extra_refs = []`) is reused by a run without extras |
| **XR-T13** `test_xrt13_seed_context_with_extras` | same, 1 | The `ctx_env` fixture (`tests/test_ltx_movie_seed_context.py:114-126`), with `_xr(ctx_env["fake"])`. `story_dir = cx_story(tmp)` (panels 1, 3 kind `none`; 2, 4 context). `args = cx_args(tmp, extra_refs=_extras(tmp, x1 + ":the sword", x2))`. `movie._phase2_seed_context(args) == 0`.<br>The jobs in call order: panel 1 `sources == [orig, e1, e2]` with prompt `_with(cx_prompt(1), SENT1)`; panel 2 `sources == [orig, still_1, e1, e2]` with prompt `_with(cx_prompt(2), SENT1.replace("Picture 3, the third", "Picture 4, the fourth").replace("Picture 2, the second", "Picture 3, the third"))` (the second replace runs after the first); panel 3 as panel 1; panel 4 as panel 2 with `still_3`.<br>`wait_for_memory` floors: `[22.0, 24.0, 22.0, 24.0]`. Every entry has `"extras"` as its last key.<br>With `seed_context={"mode": "still", "order": "context-first"}` and `redo_panels=[2]`, panel 2's `sources == [still_1, orig, e1, e2]`.<br>An unchanged rerun edits nothing |
| **XR-T14** `test_xrt14_cast_refs_with_extras` | same, 1 | `cast_env`; `members = cr_cast(lib)`; `cr_story(tmp)`; `args = cr_args(tmp, members, extra_refs=_extras(tmp, x + ":the throne room"))`; `fake = _xr(cast_env["fake"])`.<br>`movie.phase2_stills(args)` (with `_catalog_stills_flags` stubbed to `(None, [])`, as CRT11) returns 0. The Z-Image groups are for panels 1 and 3 only.<br>The one `run_jobs` call's jobs are `[(n, cr_prompt(n) with "Picture 3, the third input image, shows the throne room. Use it only where the shot below calls for it. " inserted before "The new shot: ", [k00, r00, e1]) for n in (2, 4)]`, with `"source" == k00`.<br>`wait_for_memory` floor `22.0`; the entries' last key is `"extras"`.<br>A story with no pair panel (`cr_story(tmp, images=[IMAGES[0], IMAGES[2]])`) prints `CAST_REFS_NONE_NOTE` then `"note: --extra-ref: no panel is a cast-reference Qwen edit, so the extra references are not used"`, makes no `run_jobs` call, and writes no `extra_refs/` |
| **XR-T15** `test_xrt15_frame_mode_writes_the_copies_before_its_loop` | same, 1 | Source pin, read from the `bin/ltx-movie` text, inside the slice from `def phase_seed_context_frames(args):` to `def _cast_refs_paths(story_dir):`: it contains exactly once `'    fit.load_oriented_rgb(args.seed_image).save(files["original"], format="PNG")\n    _extra_refs_note(args)\n    _extra_refs_write(args)\n    placeholder = os.path.join(files["work"], "placeholder.png")\n'`. `_seed_context_edit`'s slice (to `def _seed_context_stop(`) contains `"    _extra_refs_job(args, job)\n    fit = _image_fit()\n"` and `qe.memory_floor(model_id, _edit_references([job]))` |
| **XR-T16** `test_xrt16_the_dry_run` | same, 1 | `out = movie.main(argv)` (XR-T8's argv plus `--no-low-ram`, with two extras `a + ":the sword"` and `b`): `rc == 0`. With `lines = out.splitlines()` and `i = lines.index("--- Extra references ---")`, `lines[i:i + 6] == ["--- Extra references ---", "Would add 2 extra reference pictures to every Qwen edit of this run with Qwen-Image-2.1 q4, after the edit's own pictures (the seed), each named in the edit prompt by its picture number and caption; each edit takes up to 3 of the model's 10 reference images. They are copied into %s when the edits run; a changed picture, caption, order or count re-edits every still that used it." % <tmp>/stories/s1/extra_refs, '  extra 1: %s ("the sword")' % a, "  extra 2: %s (no caption)" % b, "", "--- Phase 3: manifest + dry-run ---"]`. `fake.calls == {"selection_problem": [], "wait_for_memory": [], "run_jobs": [], "reference_memory_problem": []}`, and nothing exists under `<tmp>/stories/s1/extra_refs`. Without `--extra-ref`, `"--- Extra references ---" not in out` |
| **XR-T17** `test_xrt17_help_and_docstring` | same, 1 | The `--extra-ref` action has `help == M3's text`, `dest == "extra_ref_specs"`, `metavar == "PATH[:CAPTION]"` and `default is None`. `" ".join(movie.__doc__.split())` contains M1's paragraph (whitespace-collapsed), followed by `" Seed context (docs/"`, and still ends with CRT17's `DOC`. `"\nimport re\n" not in <bin/ltx-movie text>` |
| **XR-T18** `test_xrt18_the_real_runner` | same, 1 | The SET15 setup (`_mflux_ready(env)`, the real `qwen_edit`, `_story_dir` under tmp) with `_phase_args(tmp, extra_refs=<two extras>)`, and CRT2's `run_child` spy. `_phase2_shots_seed(args) == 0`. The one stub call's jobs have `"sources" == [original, e1, e2]` for n = 1, 2, 3, and the spy saw `[16200]` (3 jobs x 9 x 600). `env["calls"]["safety"]` has three entries with skill `ltx_movie_shots_seed_edit` and the extras prompts. The records have `"extras"` |
| **XR-T19** `test_xrt19_fields_flags_and_argv` | `test_movie_ui_extra_refs.py`, 2 | `keys = list(lib.DEFAULT_FIELDS)`; `keys[keys.index("seed_edit_loras") + 1] == "extra_refs"`; `lib.DEFAULT_FIELDS["extra_refs"] == []`; `len(lib.DEFAULT_FIELDS) == 33`; `lib.FIELD_FLAGS[-2:] == (("extra_refs", ("--extra-ref",)), ("seed_edit", ("--seed-edit-model", "--seed-edit-lora")))`; `len(lib.FIELD_FLAGS) == 32`. With uploads `U2 = "b" * 64 + ".png"` and `U3 = "c" * 64 + ".jpg"` written to `<state>/uploads/`, `base = mt.fields(WS, seed_upload=UP, action="movie", seed_edit_model="qwen21-q4", seed_edit_loras=UNC, no_low_ram=True, extra_refs=[{"upload_id": U2, "caption": " the sword "}, {"upload_id": U3, "caption": None}])`, `argv = lib.build_argv(base, WS, state)`, and `i = argv.index("--seed-edit-lora")`: `argv[i + 2:i + 6] == ["--extra-ref", os.path.join(state, "uploads", U2) + ":the sword", "--extra-ref", os.path.join(state, "uploads", U3)]`. `lib.extra_ref_arg(state, {"upload_id": U2, "caption": "  "}) == os.path.join(state, "uploads", U2)`. `lib.build_argv(dict(base, extra_refs=[]), WS, state)` has no `"--extra-ref"`. `lib.compose_fields({})["extra_refs"] == []` |
| **XR-T20** `test_xrt20_v1_rule_12e` | same, 2 | `lib._rule_extra_refs(f, state)` for each case of Section 3's rule-12e table gives exactly its line(s): `"x"`, a list of 10, `[{"upload_id": U2}]`, an unknown upload, captions `""`, `"a:b"`, `"x" * 61`, `"a\nb"`, the same upload twice, `seed_upload=None`, `seed_edit_model="as-is"`, `seed_edit_model=None` and `no_low_ram=False`. The valid base gives `[]`. `lib.validate_fields(dict(base, no_low_ram=False), WS, state)` contains the low-RAM line, right after any rule-12d lines (here none) |
| **XR-T21** `test_xrt21_the_server_cap_and_preview` | same, 2 | The `env` fixture, `_upload` and `_compose` of `tests/test_movie_ui_qwen_edit.py`. Three distinct uploads `x1..x3` (distinct PNG bytes). `POST /api/preview` with `_compose(ws, up, seed_edit_model="qwen2511-bf16", seed_edit_loras=[], no_low_ram=True, extra_refs=<3 items>)` gives `(400, {"error": "Qwen-Image-Edit-2511 bf16 (Lightning, diffusers) takes at most 3 reference images per edit (the seed and 2 extra references); this request has 3 extra references"})`. With 2 items: 200, `payload["errors"] == []`, and `payload["command"].count("--extra-ref ") == 2`. `qwen2511-q4` with 1 item: `(400, {"error": "Qwen-Image-Edit-2511 q4 (Lightning) reads only the first picture, so it takes no extra references"})`. `POST /api/jobs` with the 3-item body is also that 400, and `lib.list_job_ids(state) == []`. The `qwen21-q4` body with 2 items and `no_low_ram=False` gives a preview 200 with `payload["errors"] == ["extra references need No low-RAM mode (--no-low-ram): in low-RAM mode a Qwen edit takes at most 2 pictures"]` |
| **XR-T22** `test_xrt22_batch_levels_groups_and_merge` | same, 2 | `batch.FIELD_LEVELS["extra_refs"] == "stills"`; `batch.GROUPS[1] == ("width", "height", "seed_upload", "seed_edit_model", "seed_edit_loras", "extra_refs")`. `seeded = lib.compose_fields({"ws": "/ws", "action": "movie", "story_id": "s1", "narrative": "N", "seed_upload": UP, "seed_edit_model": "qwen21-q4", "seed_edit_loras": UNC, "no_low_ram": True, "extra_refs": XR})`. A `{"panels": 12}` fork keeps `fork["extra_refs"] == XR`. `{"width": 768, "height": 512}` and `{"seed_upload": None}` forks give `[]`. A chained `as-is` story forked to `{"mode": "shots"}` gives `seed_edit_model is None` and `extra_refs == []`. `batch.validate_request` accepts a variant `{"extra_refs": []}` (no `key` error). `batch.classify(seeded, dict(seeded, extra_refs=[]), "s1", "/ws", state, True)[0] == "stills"` |
| **XR-T23** `test_xrt23_the_compose_control` | same, 2 | `index.html` contains once U15's seven `c-xr` lines (as one block), and `html.index('id="c-sq-shots-note"') < html.index('id="c-xr-box"') < html.index('id="c-sq-reason"')`. `app.js` contains once each:<br>- `function composeExtrasModel() {`, `function composeExtrasUpdate() {`, `async function onExtraFile() {`;<br>- the U9 `S` text `composeEngine: "qwen", extraRefs: [], extraKey: "", extrasOn: false, `;<br>- U11's `composeFields` line;<br>- `    composeExtrasUpdate();\n    // Seed-folder spec SD29: the folder mode of the Compose buttons.\n` inside `updateComposeButtons`;<br>- U13's two `fillCompose` lines;<br>- U14's two `setupCompose` lines.<br>`XR_LOW_RAM_NOTE` and `XR_AS_IS_NOTE` equal Section 3's texts. The page bans of QET38 hold. When node exists: `node --check app.js` passes. Run with SZ17's `FAKE_COMPOSE` plus `S.extrasOn = true; S.extraRefs = [{upload_id: "u1", caption: " the sword "}, {upload_id: "u2", caption: ""}]`, `composeFields("story").extra_refs` is `[{"upload_id": "u1", "caption": "the sword"}, {"upload_id": "u2", "caption": null}]`; with `S.extrasOn = false` it is `[]`; and `fillCompose({extra_refs: [{upload_id: "u3", caption: null}]})` leaves `S.extraRefs == [{upload_id: "u3", caption: ""}]` and `S.extraKey == ""` |

Before any code change, Task 1's two new files give `18 failed`, and Task 2's gives `5 failed` (with Task 1's code in place). After the change, all 23 pass.

### 5.2 Existing tests and fixtures edited (all still pass; none is removed)

Each edit is an Edit-tool replacement whose Old text occurs exactly once.

**Task 1:**
- **E1 `tests/test_seed_edit_tool.py:1143` (SQT10).** Old: `    assert [dict(m) for m in seedgen.QWEN_MODELS] == REGISTRY`. New: `    assert [dict(m) for m in seedgen.QWEN_MODELS] == [dict(r, max_references=k, reference_gib=g) for r, (k, g) in zip(REGISTRY, ((10, 2.0), (10, 2.0), (10, 2.0), (1, 3.0), (3, 3.0)))]   # extra references XR8`. Dict equality ignores key order, and XR-T1 pins the order.
- **E2 `tests/test_movie_ui_seedgen.py:339` (SQT16's helper).** Old: `                "scheduler": scheduler, "multiple": multiple, "memory_gib": memory, "license": license,`. New: `                "scheduler": scheduler, "multiple": multiple, "memory_gib": memory,\n                "max_references": {"qwen21-q4": 10, "qwen21-q8": 10, "qwen21-bf16": 10, "qwen2511-q4": 1,\n                                   "qwen2511-bf16": 3}[model_id], "license": license,`.

**Task 2:**
- **E3 `tests/fixtures/movie_ui/ltx-movie-help-current.txt`.** Old (the line plus the next option line):
  ```
                          listed means no LoRA
    --panels PANELS       number of chained clips; panel 1 also gets the movie's
  ```
  New: the first line, then `  --extra-ref PATH[:CAPTION]`, then `                        an extra reference picture for every Qwen edit of the`, then `                        run (repeatable)`, then the second line.
- **E4 `tests/test_movie_ui_builder.py:132` (MUT3).** Old: `                             "--location-strength", "--seed-edit-model", "--seed-edit-lora"}`. New: `                             "--location-strength", "--seed-edit-model", "--seed-edit-lora", "--extra-ref"}`.
- **E5 `tests/test_movie_ui_builder.py:137`.** Old: `    assert set(supported) == {k for k, _flags in lib.FIELD_FLAGS} and len(supported) == 31`. New: the same with `== 32`.
- **E6 `tests/test_location_ui.py:267`** and **E7 `tests/test_movie_ui_shots_seed.py:157`.** Old: `    assert len(lib.FIELD_FLAGS) == 31`. New: `    assert len(lib.FIELD_FLAGS) == 32`. This text also occurs in `test_movie_ui_qwen_edit.py`, but each Edit is per file and occurs once there.
- **E8 `tests/test_movie_ui_qwen_edit.py:116`.** The same edit as E6.
- **E9 `tests/test_movie_ui_shots_seed.py:42-43` (SET21's `FLAGS`).** Old: `         "--seed-edit-lora"}`. New: `         "--seed-edit-lora", "--extra-ref"}`.
- **E10 `tests/test_movie_ui_qwen_edit.py:352`** and **E11 `tests/test_movie_ui_batch.py:79`.** Old: `(len(batch.FIELD_LEVELS), len(batch.FIXED_KEYS), len(lib.DEFAULT_FIELDS)) == (27, 5, 32)`. New: `... == (28, 5, 33)`.
- **E12 `tests/test_movie_ui_qwen_edit.py:354-355` (QET37).** Old: `                            ("width", "height", "seed_upload", "seed_edit_model", "seed_edit_loras"))`. New: `                            ("width", "height", "seed_upload", "seed_edit_model", "seed_edit_loras", "extra_refs"))`.
- **E13 `tests/test_movie_ui_batch.py:33` (`EXPECTED_LEVELS`).** Old: `    "seed_edit_model": "stills", "seed_edit_loras": "stills",`. New: `    "seed_edit_model": "stills", "seed_edit_loras": "stills", "extra_refs": "stills",`.
- **E14 `tests/test_movie_ui_http.py:225` (MU14).** Old: `    assert all(payload["supported"].values()) and len(payload["supported"]) == 31`. New: the same with `== 32`.

### 5.3 Mutation check (run once before Task 3)

Each of these, applied to a copy of the Task 2 tree, makes at least one XR-T or edited test fail:
- `entry_floor` counting from the first or the second picture;
- `jobs_timeout` keeping the flat 6;
- the `run_jobs` guard missing, or running before the CR1 refusal;
- `_resolve_extra_refs` reading `no_low_ram` before autotune (moving its call above `_autotuned`);
- the as-is check after the no-edit check;
- no extras clause in any one of the four reuse tests;
- `_extra_refs_item` missing from any one key;
- the sentence at the prompt's end instead of before the anchor;
- `first` = 1 for a context panel;
- `_extra_refs_job` putting the extras first;
- `_extra_refs_write` not removing stale copies;
- the dry run writing a copy;
- `composeFields` calling `composeExtrasOn` (SZ17 fails);
- the merge keeping extras on a `seed_upload: null` fork;
- `_fields_body` without the cap.

---

## 6. Live checks on macstudio (the user runs these; the assistant never accesses macstudio)

**Preparation.** In `~/local_agent_harness`: `git fetch && git checkout extra-refs`. Run `bin/seed-edit-setup --model qwen21-q4 --lora uncensored` if it is not installed. Pick one portrait photo of one person (`SEED`) and nine pictures for the extras. Every run is zsh (`${=...}` is not needed: the flags are arrays). Each sweep row uses a NEW story id with a COPY of one base story, so the prompts are the same in every row. At the render gate ("Review the plan and the estimated render time above. Enter to render, ..."), the stills are done: press Ctrl-C there. Unrecorded rows read "not run (awaiting the user)".

```zsh
cd ~/local_agent_harness/qwen-agent-workspace
SEED=~/test_runs/seeds/queen.jpg        # the user's portrait photo
X=~/test_runs/extras                    # throne.png sword.png style.png crown.png banner.png horse.png shield.png lantern.png map.png
NARR="A young queen walks into the throne room holding a sword, puts on the crown under the royal banner, then rides out on her horse with a shield and a lantern and reads a map by lamplight, painted in the painting style."
BASE=(--shots --seed-image $SEED --seed-edit-model qwen21-q4 --seed-edit-lora uncensored=1.0 --panels 3 --no-auto-lora --speech-only)
REFS=(--extra-ref "$X/throne.png:the throne room" --extra-ref "$X/sword.png:the sword" --extra-ref "$X/style.png:the painting style"
      --extra-ref "$X/crown.png:the crown" --extra-ref "$X/banner.png:the royal banner" --extra-ref "$X/horse.png:the horse"
      --extra-ref "$X/shield.png:the shield" --extra-ref "$X/lantern.png:the lantern" --extra-ref "$X/map.png:the map")
copy() { mkdir -p generated/stories/$2 && cp generated/stories/$1/story.md generated/stories/$1/plan.json generated/stories/$2/; }
```

**Report script** (run inside each `generated/stories/<id>/`):

```bash
python3 - <<'EOF'
import json, os, re
rec = json.load(open("seed_edits.json"))
for e in rec["panels"]:
    extras = e.get("extras") or []
    print("panel", e["n"], e["status"], "%ss" % e["seconds"], "pictures", 1 + len(extras),
          [x["caption"] for x in extras], len(e["prompt"].split()), "words", e["error"] or "")
log = open("iterate-story.log", encoding="utf-8", errors="replace").read() if os.path.exists("iterate-story.log") else ""
peaks = [float(x) for x in re.findall(r"mlx peak memory ([0-9.]+) GiB", log)]
print("mlx peak GiB per job", peaks, "max", max(peaks) if peaks else None)
print("timed out" if "timed out" in log else "no timeout line in iterate-story.log")
print("copies", sorted(os.listdir("extra_refs")) if os.path.isdir("extra_refs") else [])
EOF
```

| Row | Steps | Record | Pass |
|---|---|---|---|
| XR-LV0 | `bin/ltx-movie "$NARR" --story-id xr_base $BASE --story-only` | `generated/stories/xr_base/story.md`; which panels' `Image:` mention which props | the story exists (the base of XR-LV1-XR-LV5) |
| XR-LV1 | total 2: `copy xr_base xr_n2; /usr/bin/time -l bin/ltx-movie "$NARR" --story-id xr_n2 $BASE --no-low-ram ${REFS[1,2]}` | the `extra refs:` line; the report; `/usr/bin/time`'s "maximum resident set size"; per panel: seed person held (face, hair, clothing; Y/N); the throne room recognisable where mentioned (Y/N) | XRK6 (peak at most 20 GiB, no timeout); XRK7 |
| XR-LV2 | total 3: as XR-LV1 with id `xr_n3` and `${REFS[1,4]}` | the same, plus the sword | XRK6 (at most 22 GiB); XRK7 |
| XR-LV3 | total 4: id `xr_n4`, `${REFS[1,6]}` | the same, plus the painting style | XRK6 (at most 24 GiB); XRK7 |
| XR-LV4 | total 6: id `xr_n6`, `${REFS[1,10]}`; expect the over-4 `Warning:` line | the same, all five props | XRK6 (at most 28 GiB); identity recorded |
| XR-LV5 | total 10: id `xr_n10`, `${REFS[1,18]}`; expect the warning | the same, all nine | XRK6 (at most 36 GiB); identity recorded |
| XR-LV6 | low-RAM refusal: `env -u QWEN_LTX_AUTOTUNE bin/ltx-movie "$NARR" --story-id xr_lowram $BASE ${REFS[1,2]} --dry-run; echo exit $?` | stderr | XRK8: exactly the LOW_RAM `Error:` line, `exit 2`, and no `generated/stories/xr_lowram/extra_refs` |
| XR-LV7 | autotune: `QWEN_LTX_AUTOTUNE=1 bin/ltx-movie "$NARR" --story-id xr_auto $BASE ${REFS[1,2]} --dry-run; echo exit $?` | stderr and stdout | XRK8: `autotune (QWEN_LTX_AUTOTUNE): ... no_low_ram=True`, the `--- Extra references ---` block, `exit 0` |
| XR-LV8 | reuse: rerun XR-LV3's command exactly; then rerun it with `the sword` changed to `the long sword` | the first rerun prints `seed edits: every panel's still is a recorded edit ...; nothing to edit` and starts no child; the second moves all three stills into `redo/<stamp>-<pid>/images/` and edits panels 1,2,3 | XRK5 |
| XR-LV9 | `qwen2511-bf16`, total 3: `copy xr_base xr_bf16; bin/ltx-movie "$NARR" --story-id xr_bf16 ${BASE:/qwen21-q4/qwen2511-bf16} --no-low-ram ${REFS[1,4]}` (remove `--seed-edit-lora uncensored=1.0` from the array first: the uncensored LoRA is for qwen21) | as XR-LV1 (no mlx peak line: diffusers); or "not run: <reason>" when it refuses `... is unavailable: ...` | recorded |
| XR-LV10 | chained panel 1 and Compose: (a) `bin/ltx-movie "$NARR" --story-id xr_chain --seed-image $SEED --seed-edit-model qwen21-q4 --panels 3 --no-auto-lora --speech-only --no-low-ram ${REFS[1,4]}`, then Ctrl-C at the gate; (b) in the movie UI Compose with a seed and a Qwen model: the Extra references box is disabled, with the low-RAM note, until No low-RAM mode is ticked; then add two images with captions, and the command shows two `--extra-ref`; selecting Qwen-Image-Edit-2511 q4 shows the "reads only the first picture" note and drops `--extra-ref` from the command | (a) `seed_edit.json` has `"extras"` as its last key; `seed-edited.png` shows the throne room and the sword where panel 1's `Image:` mentions them; (b) as described | recorded |

**If XRK6 fails** (a peak above the floor), the next step is open question 2: raise `reference_gib` to the measured per-reference slope.

---

## 7. Risks (rulings), follow-ups and open questions

**Risks.**
- **R1 Quality above 4 pictures.** The 2511 card says the model is best with 1-3 inputs. qwen21 takes 10, but untested on these prompts. The warning says so; XR-LV4 and XR-LV5 measure it.
- **R2 Prefix wording.** The existing prefixes speak of one or two pictures:
  - the seeded shots prefix says "Edit this photo", for Picture 1;
  - the seed context prefix says "from two pictures";
  - the cast refs prefix says "Take only these two people from the pictures".
  
  The extras sentence follows them and names each extra, and the prefixes are pinned and unchanged. If the live checks show extras ignored, a follow-up rewords the prefixes when extras are present (F3).
- **R3 Memory and time numbers are inferred** (Decisions 6, 7); XRK6 measures memory, and the timeout only bounds a hang.
- **R4 Picture-number binding.** Whether "Picture N" binds to the Nth image in qwen21 (which tags `<imageN>`) is inferred, as in [CR] R4. Caption-less extras bind only by number.
- **R5 Resolution.** Each reference costs about 4096 tokens at the unchanged `output_resolution` (Decision 9). Ten references at a 2048x1152 cast-refs output come to about 50k tokens.
- **R6 The story does not know the extras.** Phase 1 is unchanged, so a prop appears in an `Image:` text only when the narrative mentions it. The sentence says "only where the shot below calls for it", so an unmentioned prop should stay out.
- **R7 Inputs are not screened.** As with the seed and the cast stills, the extras are the user's own files, and only the outputs are screened.
- **R8 Prompt length.** Nine extras add about 120 words on top of [CR] R8's prompts; the text-encoder limit is unverified.
- **R9 A file changed between the resolver and the edit phase** is copied with its new bytes, while the key keeps the resolver's sha256. The next run sees the mismatch and re-edits. A file deleted there makes the copy raise a traceback (as a deleted seed would today).
- **R10 The UI needs the explicit tick** even when the server's environment autotunes `no_low_ram` (Decision 13); the CLI does not need it.

**Follow-ups (not in this spec).** F1 per-panel extras; F2 `output_resolution` 512 for many references (Decision 9); F3 prefix rewording when extras are present (R2); F4 telling the planner about the extras' captions (R6); F5 a batch-editor control for `extra_refs`.

**Open questions (for after the live checks).**
1. **Low-RAM with one extra on a seed edit** (total 2, today's maximum) is refused by the literal reading of the binding design. Should it be allowed?
2. **`reference_gib`** (2.0 qwen21, 3.0 qwen2511) is inferred. Keep it, or set it from XR-LV1-XR-LV5's measured slope?
3. **The timeout weight 3n.** Keep it once XR-LV5's seconds are known?
4. **`qwen2511-bf16` cap 3.** Keep it, or raise it if XR-LV9 holds identity at 3?

---

## 8. Amended requirements of earlier specs

| Item | Status |
|---|---|
| [CR] CR2 (a job with two or more sources counts 6) | amended by XR10: n >= 2 sources count 3n (6 for two, unchanged) |
| [CR] CR3 (`sources` 1..N) | extended: at most `max_references` (XR8) |
| [QE] QE7, SQ16 (`memory_gib` floor) | extended by XR9: `+ reference_gib x max(0, n - 2)`; unchanged for one and two pictures |
| [SE] SE12-SE15, [CX] CX5-CX9, [CR] CR9, [QE] QE48 records and keys | extended by XR7: an `"extras"` item (key and last entry key) only with extras |
| [SE] SET21 "no new field flag" | amended: one new field flag, `extra_refs` (XR16) |
| [BF] BF4 levels, GROUPS | extended by XR20 |
| [CR] 0.6 / F3 and [CX] 0.6 "CLI only" | unchanged for cast refs and seed context: Compose offers extras for the seed edit paths only (chained panel 1 and seeded shots), which are the Compose cells with a Qwen edit |

---

## Plan

**House rules** (every task):
- Work only in `$S/xr-wt`. Never touch `/Users/reubenpatterson/local_agent_harness` directly.
- Never stash, reset, amend, rebase, push or open a PR.
- Never access macstudio (no ssh, no scp, no reading its files). Never contact a server, render, run a model, or run tests against the real HOME.
- Edit tracked files with the Edit or Write tool. Each Edit's Old text must occur exactly once in its file when it is applied; if it does not, stop and report.
- Every changed `.py` file and every new test file must compile on `/usr/bin/python3` (3.9) and `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`; `bin/ltx-movie` is checked with `python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" bin/ltx-movie` on both.
- Stage only the paths the task names, and check `git diff --cached --name-only` before every commit. End each commit with a second `-m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`.
- The PR is merged with a merge commit only.

**Replay (spec check, done by the spec author).**
- Every Old text below occurs exactly once in its file at `fcd5d86` (checked by script: 62 edits, plus U6, E3, E7, E8 and E11 by hand).
- Q1-Q5, G1-G6, M1-M27, E1 and E2 were applied by script to a `git archive` copy of `fcd5d86` (`$S/xr-replay`). `bin/ltx-movie`, `qwen_edit.py` and `movie_ui_seedgen.py` parse on Python 3.9.6 and 3.13.0. The existing suites `test_qwen_edit`, `test_qwen_edit_cast_refs`, `test_seed_edit_tool`, `test_movie_ui_seedgen`, `test_ltx_movie_seed_edit`, `test_ltx_movie_shots_seed`, `test_ltx_movie_cast_refs`, `test_ltx_movie_seed_context`, `test_ltx_movie_seed_context_frame`, `test_ltx_movie_shots_zimage` and `test_ltx2_autotune` gave `289 passed`, and `tests/test_ltx_movie_offline.py` gave `OK 347/347`.
- A throwaway smoke test (not a deliverable) confirmed:
  - the resolved captions;
  - three sources per seeded shots job, and the wait floor 22.0;
  - the stale copy removed, and the copy oriented to 100x200;
  - `extras` as the last entry key;
  - reuse, then a re-edit without extras, then reuse;
  - the AS_IS, NO_EDIT, LOW_RAM and cap texts;
  - the dry-run block;
  - autotune turning `no_low_ram` on;
  - `jobs_timeout` 18000 and the floor 36.0 for ten pictures.
- U1-U15 and E3-E14 were applied on top. The movie-UI suites (`test_movie_ui_qwen_edit`, `_shots_seed`, `_shots_zimage` with node, `_batch`, `_batch_zimage`, `_builder`, `_http`, `_checks`, `_seedfolder`, `test_location_ui`, `_seams`, `_seedgen`) gave `401 passed, 1 skipped`. `node --check app.js` passed. The rule-12e texts, the argv, the merge and the batch level were checked directly.

### Before Task 1 (controller)

1. `git -C $S/xr-wt rev-parse HEAD` is `fcd5d86...`, and `git status --short` (outside `docs/`) is empty.
2. Snapshot: `tar czf $S/snapshot-pre-xr-fcd5d86.tgz --exclude generated -C $S/xr-wt qwen-agent-workspace`.
3. Baseline: `cd $S/xr-wt/qwen-agent-workspace && python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $S/xr-baseline/baseline-pytest.txt 2>&1`. Record its summary line as P0 and its failing tests as F0. The spec author already ran it at `fcd5d86` (this file, `$S/xr-baseline/baseline-pytest.txt`): `2 failed, 2791 passed, 2 skipped` in 20:49, with F0 = `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`, and `test_mut26` passing. Reuse it while HEAD is still `fcd5d86` plus this spec. Then write `$S/xr-baseline/baseline-ok-lines.txt` with the five `OK n/n` lines (`tests/test_ltx_movie_offline.py` 347/347, image_oneshot 25/25, danger_auto_approve 57/57, context_budget 68/68, session_memory 205/205), as `$S/mb-baseline/base-run.sh` does.
4. The gate for a task is `$S/mb-baseline/gate-run.sh`, copied to `$S/xr-baseline/gate-run.sh` with `mb-` replaced by `xr-`. It passes when no baseline PASSED test is lost (except `test_mut26` between Task 1 and Task 3, and the two flaky timing tests `test_tr27_fanout_two_rounds_and_missing_reasons` and `test_trt45_query_endpoints_refuse_browsers_and_bad_queries`, which must pass when rerun alone), and every new test passes.
5. Check that every Old text below occurs exactly once in its file.

### Task 1: the registry, the runner and `bin/ltx-movie`, with their tests (one commit)

**Q1 `qwen_edit.py:10-12` (docstring).** Old:
```python
child timeout is max(CHILD_TIMEOUT_S, JOB_TIMEOUT_S x jobs) seconds, where a job with several reference images
(its "sources" list, docs/superpowers/specs/2026-11-09-shots-multi-reference-stills-design.md) counts
MULTI_REFERENCE_TIMEOUT_FACTOR jobs.
```
New:
```python
child timeout is max(CHILD_TIMEOUT_S, JOB_TIMEOUT_S x jobs) seconds, where a job with n >= 2 reference images
(its "sources" list, docs/superpowers/specs/2026-11-09-shots-multi-reference-stills-design.md) counts
MULTI_REFERENCE_TIMEOUT_FACTOR x n / 2 jobs; a job may list at most its model's max_references images, and the
memory floor grows by reference_gib for every image above two
(docs/superpowers/specs/2026-11-13-extra-reference-images-design.md).
```

**Q2 `qwen_edit.py:266-273`.** Old:
```python
def memory_problem(entry):
    """Seed models SQ16: None when this host's total memory reaches the entry's floor, else why not."""
    t = total_gib()
    if t is None:
        return "cannot read this host's memory size"
    if t < entry["memory_gib"]:
        return "needs a host with at least %g GiB of memory (this host has %.1f GiB)" % (entry["memory_gib"], t)
    return None
```
New:
```python
def entry_floor(entry, references=1):
    """The memory floor in GiB of a registry entry editing with references images (extra references spec XR9):
    memory_gib, plus reference_gib for every reference image above two."""
    return entry["memory_gib"] + entry["reference_gib"] * max(0, references - 2)


def memory_problem(entry, references=1):
    """Seed models SQ16: None when this host's total memory reaches the entry's floor (with references images,
    extra references spec XR9), else why not."""
    t = total_gib()
    if t is None:
        return "cannot read this host's memory size"
    floor = entry_floor(entry, references)
    if t < floor:
        return "needs a host with at least %g GiB of memory (this host has %.1f GiB)" % (floor, t)
    return None
```

**Q3 `qwen_edit.py:416-417`.** Old:
```python
def memory_floor(model_id):
    return seedgen.qwen_model(model_id)["memory_gib"]
```
New:
```python
def memory_floor(model_id, references=1):
    return entry_floor(seedgen.qwen_model(model_id), references)


def max_references(model_id):
    """The most reference images one edit job of model_id may list (extra references spec XR8)."""
    return seedgen.qwen_model(model_id)["max_references"]


def reference_memory_problem(model_id, references):
    """None when this host's total memory reaches model_id's floor with references images (extra references spec
    XR9), else the refusal text."""
    entry = seedgen.qwen_model(model_id)
    problem = memory_problem(entry, references)
    if problem is None:
        return None
    return "%s with %d reference images is unavailable: %s" % (entry["label"], references, problem)
```

**Q4 `qwen_edit.py:430-433`.** Old:
```python
    """The child timeout for jobs (cast refs spec CR2): child_timeout(len(jobs)) when no job lists more than one
    source; a job whose "sources" lists two or more images counts MULTI_REFERENCE_TIMEOUT_FACTOR jobs."""
    weight = sum(MULTI_REFERENCE_TIMEOUT_FACTOR if len(job.get("sources") or ()) > 1 else 1 for job in jobs)
    return max(CHILD_TIMEOUT_S, JOB_TIMEOUT_S * weight)
```
New:
```python
    """The child timeout for jobs (cast refs spec CR2): child_timeout(len(jobs)) when no job lists more than one
    source; a job whose "sources" lists n >= 2 images counts MULTI_REFERENCE_TIMEOUT_FACTOR x n / 2 jobs (6 for two,
    as before, and 30 for ten; extra references spec XR10)."""
    weight = 0
    for job in jobs:
        n = len(job.get("sources") or ())
        weight += MULTI_REFERENCE_TIMEOUT_FACTOR * n // 2 if n > 1 else 1
    return max(CHILD_TIMEOUT_S, JOB_TIMEOUT_S * weight)
```

**Q5 `qwen_edit.py:483-484`.** Old:
```python
    if refused is not None and any(len(job.get("sources") or ()) > 1 for job in jobs):
        raise Unavailable("%s cannot edit with several reference images: %s" % (entry["label"], refused))
```
New:
```python
    if refused is not None and any(len(job.get("sources") or ()) > 1 for job in jobs):
        raise Unavailable("%s cannot edit with several reference images: %s" % (entry["label"], refused))
    for job in jobs:
        if len(job.get("sources") or ()) > entry["max_references"]:      # extra references XR8
            raise Unavailable("%s takes at most %d reference images per edit; job %d lists %d"
                              % (entry["label"], entry["max_references"], job["n"], len(job["sources"])))
```

**G1-G5 `movie_ui_seedgen.py:53, 59, 65, 71, 76`.** Each Old is one registry line; each New inserts the two keys after `"memory_gib"`:
- G1 Old `     "memory_gib": 20.0, "license": QWEN_RESEARCH, "setup": True},` New `     "memory_gib": 20.0, "max_references": 10, "reference_gib": 2.0, "license": QWEN_RESEARCH, "setup": True},`
- G2 Old `     "memory_gib": 32.0, "license": QWEN_RESEARCH, "setup": True},` New `     "memory_gib": 32.0, "max_references": 10, "reference_gib": 2.0, "license": QWEN_RESEARCH, "setup": True},`
- G3 Old `     "memory_gib": 56.0, "license": QWEN_RESEARCH, "setup": True},` New `     "memory_gib": 56.0, "max_references": 10, "reference_gib": 2.0, "license": QWEN_RESEARCH, "setup": True},`
- G4 Old `     "memory_gib": 32.0, "license": "Apache-2.0", "setup": True},` New `     "memory_gib": 32.0, "max_references": 1, "reference_gib": 3.0, "license": "Apache-2.0", "setup": True},`
- G5 Old `     "memory_gib": 64.0, "license": "Apache-2.0", "setup": False},` New `     "memory_gib": 64.0, "max_references": 3, "reference_gib": 3.0, "license": "Apache-2.0", "setup": False},`

**G6 `movie_ui_seedgen.py:293`.** Old: `               "memory_gib": m["memory_gib"], "license": m["license"],`. New: `               "memory_gib": m["memory_gib"], "max_references": m["max_references"], "license": m["license"],`.

**M1 `bin/ltx-movie:119-121` (docstring).** Old:
```
--shots does without a seed.

Seed context (docs/superpowers/specs/2026-11-10-seeded-shots-context-design.md), a test option: in shots mode with
```
New:
```
--shots does without a seed.

Extra references (docs/superpowers/specs/2026-11-13-extra-reference-images-design.md): --extra-ref PATH[:CAPTION]
(repeatable, at most 9) adds the user's pictures (a location, a prop, a style) to every Qwen edit of the run, after
the edit's own pictures (the seed, the context picture or the two cast stills), each named in the edit prompt by its
picture number and caption. It needs --no-low-ram (QWEN_LTX_AUTOTUNE=1 sets it on a host with at least 96 GiB) and
at most the edit model's max_references pictures per edit; a changed extra re-edits every still that used it.

Seed context (docs/superpowers/specs/2026-11-10-seeded-shots-context-design.md), a test option: in shots mode with
```

**M2 `bin/ltx-movie:223-224` (constants).** Old:
```python
SEED_CONTEXT_REDO_NOTE = ("note: seed context: --redo %s also re-edits panels %s: their context picture is %s, so "
                          "it changes with it, up to the next location change")
```
New: the same two lines, then:
```python
# Extra references (docs/superpowers/specs/2026-11-13-extra-reference-images-design.md, XR5): the user's pictures
# added to every Qwen edit of the run after its own pictures, named in the prompt just before "The new shot: ".
EXTRA_REFS_MAX = 9
EXTRA_REFS_WARN_ABOVE = 4
EXTRA_REFS_CAPTION_MAX = 60
EXTRA_REFS_DIR = "extra_refs"
EXTRA_REFS_ANCHOR = "The new shot: "
EXTRA_REFS_ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth")
EXTRA_REFS_NO_CAPTION = "is one more reference picture"
EXTRA_REFS_USE_ONE = ". Use it only where the shot below calls for it. "
EXTRA_REFS_USE_MANY = ". Use each of them only where the shot below calls for it. "
EXTRA_REFS_AS_IS_ERROR = ("Error: --extra-ref cannot be combined with --seed-edit-model as-is: the seed is used unedited "
                          "(with --shots, the Z-Image engine renders every other still), so no Qwen edit would see "
                          "the extra references; choose a Qwen --seed-edit-model ID")
EXTRA_REFS_NO_EDIT_ERROR = ("Error: --extra-ref needs a Qwen edit in this run: --seed-image with --seed-edit-model ID "
                            "(panel 1 in chained mode, every still with --shots), or --shots with --cast-refs-model ID "
                            "and at least two cast characters")
EXTRA_REFS_LOW_RAM_ERROR = ("Error: --extra-ref needs --no-low-ram: in low-RAM mode (the default) a Qwen edit takes at "
                            "most 2 reference images, so extra references are off; on a host with at least 96 GiB of "
                            "memory pass --no-low-ram, or set QWEN_LTX_AUTOTUNE=1 to turn it on there automatically")
EXTRA_REFS_MANY_WARNING = ("Warning: --extra-ref: each Qwen edit of this run takes up to %d reference images (%s, then %d "
                           "extra references); above 4 the edit models are past the 1 to 3 input images they are tuned "
                           "for, so faces, clothing and props can blend or drift: check every still")
EXTRA_REFS_UNUSED_NOTE = ("note: --extra-ref: no panel is a cast-reference Qwen edit, so the extra references are not "
                          "used")
```

**M3 `bin/ltx-movie:538-539` (the flag).** Old:
```python
                         help="with --seed-context: seed-first (the default) makes the seed Picture 1 and the "
                              "context picture Picture 2; context-first swaps them")
```
New: the same two lines, then:
```python
    parser.add_argument("--extra-ref", dest="extra_ref_specs", action="append", default=None,
                         metavar="PATH[:CAPTION]",
                         help="an extra reference picture (a location, a prop, a style) for every Qwen edit of the "
                              "run, after the edit's own pictures (the seed, the context picture or the two cast "
                              "stills); repeatable, at most 9, in picture order. CAPTION (at most 60 characters, no "
                              "':') names what it shows, e.g. 'the sword', in the edit prompt. Needs a Qwen edit "
                              "(--seed-edit-model ID, or --cast-refs-model) and --no-low-ram, and at most the edit "
                              "model's max_references pictures per edit (10 for qwen21, 3 for qwen2511-bf16, 1 for "
                              "qwen2511-q4). See docs/superpowers/specs/2026-11-13-extra-reference-images-design.md.")
```

**M4 `bin/ltx-movie:1281-1282` (the resolver and the helpers, after `_resolve_seed_context`).** Old:
```python
    args.seed_context = {"mode": mode, "order": order or "seed-first"}
    return 0
```
New: the same two lines, then:
```python


def _extra_refs_edit(args):
    """(model ID, the number of its own pictures, their words) of the run's Qwen edit that extra references join
    (extra references spec XR3), or None when the run has no Qwen edit: the cast-reference edits, else the
    seed-context edits, else the seed edit (Phase 1c in chained mode, every shots still with --shots)."""
    if getattr(args, "cast_refs", None):
        return args.cast_refs["qwen_model"], 2, "the two characters' reference stills"
    if getattr(args, "seed_context", None):
        return args.seed_edit["qwen_model"], 2, "the seed and the context picture"
    if getattr(args, "seed_edit", None):
        return args.seed_edit["qwen_model"], 1, "the seed"
    return None


def _resolve_extra_refs(args):
    """--extra-ref (extra references spec XR1-XR4, XR8, XR9, XR23): sets args.extra_refs to [] (none) or one
    {"path", "caption", "sha256", "file"} per value, in order. main calls it after autotune and after the seed edit,
    cast refs and seed context resolvers, so the low-RAM mode and the run's Qwen edit are final. Returns 0, or 2
    after one Error: line, before the lockfile and any phase. A dry run and --story-only check no host memory."""
    specs = getattr(args, "extra_ref_specs", None) or []
    args.extra_refs = []
    if not specs:
        return 0
    if getattr(args, "seed_edit_model", None) == "as-is":
        print(EXTRA_REFS_AS_IS_ERROR, file=sys.stderr)
        return 2
    edit = _extra_refs_edit(args)
    if edit is None:
        print(EXTRA_REFS_NO_EDIT_ERROR, file=sys.stderr)
        return 2
    if not args.no_low_ram:
        print(EXTRA_REFS_LOW_RAM_ERROR, file=sys.stderr)
        return 2
    if len(specs) > EXTRA_REFS_MAX:
        print("Error: --extra-ref is given %d times; at most %d extra references are allowed"
              % (len(specs), EXTRA_REFS_MAX), file=sys.stderr)
        return 2
    fit = _image_fit()
    extras, seen = [], {}
    for k, value in enumerate(specs, start=1):
        path, caption = value, None
        if not os.path.isfile(value) and ":" in value:
            path, caption = value.rsplit(":", 1)
        if not os.path.isfile(path):
            print("Error: --extra-ref %s: no such image file (the form is PATH or PATH:CAPTION, and a caption cannot "
                  "contain ':')" % value, file=sys.stderr)
            return 2
        if caption is not None:
            caption = caption.strip().rstrip(".").strip() or None
        if caption is not None and (len(caption) > EXTRA_REFS_CAPTION_MAX
                                    or any(ord(ch) < 0x20 or ord(ch) == 0x7f for ch in caption)):
            print("Error: --extra-ref %s: the caption must be at most %d characters with no control characters"
                  % (value, EXTRA_REFS_CAPTION_MAX), file=sys.stderr)
            return 2
        try:
            fit.load_oriented_rgb(path)
        except Exception as e:      # extra references XR2: an Error: line, never a traceback
            print("Error: --extra-ref %s: cannot read it as an image (%s: %s)" % (value, type(e).__name__, e),
                  file=sys.stderr)
            return 2
        digest = _sha256_file(path)
        if digest in seen:
            print("Error: --extra-ref %s and %s are the same image bytes; give each extra reference once"
                  % (seen[digest], value), file=sys.stderr)
            return 2
        seen[digest] = value
        extras.append({"path": os.path.abspath(path), "caption": caption, "sha256": digest,
                       "file": os.path.join(EXTRA_REFS_DIR, "extra_%02d.png" % k)})
    qe = _qwen_edit()
    model_id, own, words = edit
    cap, total = qe.max_references(model_id), own + len(extras)
    if cap == 1:
        print("Error: --extra-ref: %s reads only the first input image, so it takes no extra references; choose a "
              "qwen21 model (up to 9) or qwen2511-bf16 (up to 2)" % qe.label(model_id), file=sys.stderr)
        return 2
    if total > cap:
        print("Error: --extra-ref: %s takes at most %d reference images per edit, and each edit of this run would "
              "take %d (%s, then %d extra references); give at most %d --extra-ref"
              % (qe.label(model_id), cap, total, words, len(extras), cap - own), file=sys.stderr)
        return 2
    if total > EXTRA_REFS_WARN_ABOVE:
        print(EXTRA_REFS_MANY_WARNING % (total, words, len(extras)))
    if not args.dry_run and not args.story_only:
        problem = qe.reference_memory_problem(model_id, total)
        if problem is not None:
            print("Error: --extra-ref: %s" % problem, file=sys.stderr)
            return 2
    args.extra_refs = extras
    return 0


def _extra_refs_paths(args):
    """The absolute paths of the story's copies of the extra references, in picture order (extra references XR6)."""
    story_dir = _story_paths(args.story_id)["story_dir"]
    return [os.path.join(story_dir, extra["file"]) for extra in getattr(args, "extra_refs", None) or []]


def _extra_refs_write(args):
    """Write every extra reference, oriented, as a PNG at its _extra_refs_paths path, after removing every other
    extra_*.png of <story>/extra_refs/ (extra references XR6). Does nothing without extra references."""
    extras = getattr(args, "extra_refs", None) or []
    if not extras:
        return
    fit = _image_fit()
    paths = _extra_refs_paths(args)
    folder = os.path.dirname(paths[0])
    os.makedirs(folder, exist_ok=True)
    for old in glob.glob(os.path.join(folder, "extra_*.png")):
        if old not in paths:
            os.remove(old)
    for extra, path in zip(extras, paths):
        fit.load_oriented_rgb(extra["path"]).save(path + ".tmp", format="PNG")
        os.replace(path + ".tmp", path)


def _extra_refs_item(args):
    """{"extras": [{"file", "caption", "sha256"}, ...]}, the item every edit key and record entry of a run with extra
    references carries (extra references XR7), or {} without them."""
    extras = getattr(args, "extra_refs", None) or []
    if not extras:
        return {}
    return {"extras": [{"file": e["file"], "caption": e["caption"], "sha256": e["sha256"]} for e in extras]}


def _extra_refs_prompt(args, prompt, first):
    """prompt with the extra references' sentence (extra references XR11) inserted just before its first
    EXTRA_REFS_ANCHOR, or in front when it has none (Phase 1c); first is the number of the edit's own pictures.
    prompt itself without extra references."""
    extras = getattr(args, "extra_refs", None) or []
    if not extras:
        return prompt
    items = []
    for k, extra in enumerate(extras, start=first + 1):
        items.append("Picture %d, the %s input image, %s" % (
            k, EXTRA_REFS_ORDINALS[k - 1], "shows " + extra["caption"] if extra["caption"] else EXTRA_REFS_NO_CAPTION))
    sentence = "; ".join(items) + (EXTRA_REFS_USE_ONE if len(extras) == 1 else EXTRA_REFS_USE_MANY)
    at = prompt.find(EXTRA_REFS_ANCHOR)
    return prompt[:at] + sentence + prompt[at:] if at >= 0 else sentence + prompt


def _extra_refs_job(args, job):
    """job, with the extra references' copies appended to its "sources" (its own pictures, else [its source]) when
    the run has any (extra references XR12); job itself otherwise."""
    paths = _extra_refs_paths(args)
    if paths:
        job["sources"] = list(job.get("sources") or [job["source"]]) + paths
    return job


def _edit_references(jobs):
    """The most reference images any of jobs edits with: its "sources", else 1 (extra references XR9)."""
    return max(len(job.get("sources") or [job["source"]]) for job in jobs)


def _extra_refs_note(args):
    """Print an edit phase's extra references line (extra references XR13); nothing without extra references."""
    extras = getattr(args, "extra_refs", None) or []
    if extras:
        print("extra refs: every Qwen edit here also gets %d extra reference pictures after its own: %s" % (
            len(extras), "; ".join("%s (%s)" % (path, '"%s"' % e["caption"] if e["caption"] else "no caption")
                                   for e, path in zip(extras, _extra_refs_paths(args)))))
```

**M5 `bin/ltx-movie:2626-2630` (P1 prompt and key).** Old:
```python
    width, height = _seed_edit_size(args, qe.multiple(model_id))
    with open(args.seed_image, "rb") as f:
        source_sha256 = hashlib.sha256(f.read()).hexdigest()
    key = dict(qe.settings(model_id, loras), source_sha256=source_sha256, prompt=prompt,
               seed=args.image_seed, width=width, height=height)
```
New:
```python
    prompt = _extra_refs_prompt(args, prompt, 1)          # extra references XR11
    width, height = _seed_edit_size(args, qe.multiple(model_id))
    with open(args.seed_image, "rb") as f:
        source_sha256 = hashlib.sha256(f.read()).hexdigest()
    key = dict(qe.settings(model_id, loras), source_sha256=source_sha256, prompt=prompt,
               seed=args.image_seed, width=width, height=height, **_extra_refs_item(args))
```

**M6 `bin/ltx-movie:2636-2637` (P1 reuse).** Old:
```python
    if (isinstance(old, dict) and old.get("status") == "ok" and os.path.isfile(files["edited"])
            and all(k in old and old[k] == v for k, v in key.items())):
```
New:
```python
    if (isinstance(old, dict) and old.get("status") == "ok" and os.path.isfile(files["edited"])
            and all(k in old and old[k] == v for k, v in key.items())
            and old.get("extras") == key.get("extras")):
```

**M7 `bin/ltx-movie:2647-2651` (P1 job and wait).** Old:
```python
    job = {"n": 1, "seed": args.image_seed, "prompt": prompt, "source": files["original"],
           "stage_path": files["stage"], "output_path": files["edited"]}
    try:
        qe.wait_for_memory(qe.memory_floor(model_id), label, tag="ltx-movie")
```
New:
```python
    _extra_refs_note(args)
    _extra_refs_write(args)
    job = _extra_refs_job(args, {"n": 1, "seed": args.image_seed, "prompt": prompt, "source": files["original"],
                                 "stage_path": files["stage"], "output_path": files["edited"]})
    try:
        qe.wait_for_memory(qe.memory_floor(model_id, _edit_references([job])), label, tag="ltx-movie")
```

**M8 `bin/ltx-movie:2664` (P1 record).** Old:
```python
        "seconds": result["seconds"] if result is not None else None, "error": failure})
```
New:
```python
        "seconds": result["seconds"] if result is not None else None, "error": failure, **_extra_refs_item(args)})
```

**M9 `bin/ltx-movie:2744-2747` (P2 prompts).** Old:
```python
    for n, prompt in prompts:
        if not prompt:
            return "panel %d of %s has no Image: description to edit the seed with" % (n, paths["story_md"]), None
    size = _seed_edit_size(args, qe.multiple(model_id))
```
New:
```python
    for n, prompt in prompts:
        if not prompt:
            return "panel %d of %s has no Image: description to edit the seed with" % (n, paths["story_md"]), None
    prompts = [(n, _extra_refs_prompt(args, prompt, 1)) for n, prompt in prompts]     # extra references XR11
    size = _seed_edit_size(args, qe.multiple(model_id))
```

**M10 `bin/ltx-movie:2755-2761` (P2 key and reuse).** Old:
```python
        keys[n] = dict(settings, source_sha256=source_sha256, prompt=prompt, seed=args.image_seed,
                       width=size[0], height=size[1], still_width=still[0], still_height=still[1])
        entry = entries.get(n)
        path = os.path.join(paths["images_dir"], "panel_%02d.png" % n)
        if (n not in redo and isinstance(entry, dict) and entry.get("status") == "ok"
                and all(k in entry and entry[k] == v for k, v in keys[n].items())
```
New:
```python
        keys[n] = dict(settings, source_sha256=source_sha256, prompt=prompt, seed=args.image_seed,
                       width=size[0], height=size[1], still_width=still[0], still_height=still[1],
                       **_extra_refs_item(args))
        entry = entries.get(n)
        path = os.path.join(paths["images_dir"], "panel_%02d.png" % n)
        if (n not in redo and isinstance(entry, dict) and entry.get("status") == "ok"
                and all(k in entry and entry[k] == v for k, v in keys[n].items())
                and entry.get("extras") == keys[n].get("extras")
```

**M11 `bin/ltx-movie:2840-2844` (P2 record entry).** Old:
```python
                "output": "seed_edits/panel_%02d.png" % n if ok else None,
                "still": "images/panel_%02d.png" % n if ok else None,
                "still_sha256": (_sha256_file(os.path.join(paths["images_dir"], "panel_%02d.png" % n))
                                 if ok else None),
                "seconds": seconds, "error": error_text}
```
New: the same, with the last line `                "seconds": seconds, "error": error_text, **_extra_refs_item(args)}`.

**M12 `bin/ltx-movie:2859-2863` (P2 jobs and wait).** Old:
```python
    jobs = [{"n": n, "seed": args.image_seed, "prompt": prompts[n], "source": files["original"],
             "stage_path": os.path.join(files["work"], "panel_%02d.pending.png" % n),
             "output_path": os.path.join(files["work"], "panel_%02d.png" % n)} for n in todo]
    try:
        qe.wait_for_memory(qe.memory_floor(model_id), label, tag="ltx-movie")
```
New:
```python
    _extra_refs_note(args)
    _extra_refs_write(args)
    jobs = [_extra_refs_job(args, {"n": n, "seed": args.image_seed, "prompt": prompts[n], "source": files["original"],
                                   "stage_path": os.path.join(files["work"], "panel_%02d.pending.png" % n),
                                   "output_path": os.path.join(files["work"], "panel_%02d.png" % n)}) for n in todo]
    try:
        qe.wait_for_memory(qe.memory_floor(model_id, _edit_references(jobs)), label, tag="ltx-movie")
```

**M13 `bin/ltx-movie:2949-2951` (P3 prompt and base key).** Old:
```python
        prompts[n] = SHOTS_SEED_EDIT_PREFIX + text if kinds[n] == "none" else _seed_context_prompt(order, text)
        base[n] = dict(settings, source_sha256=source_sha256, prompt=prompts[n], seed=args.image_seed,
                       width=size[0], height=size[1], still_width=still[0], still_height=still[1])
```
New:
```python
        prompts[n] = SHOTS_SEED_EDIT_PREFIX + text if kinds[n] == "none" else _seed_context_prompt(order, text)
        prompts[n] = _extra_refs_prompt(args, prompts[n], 1 if kinds[n] == "none" else 2)   # extra references XR11
        base[n] = dict(settings, source_sha256=source_sha256, prompt=prompts[n], seed=args.image_seed,
                       width=size[0], height=size[1], still_width=still[0], still_height=still[1],
                       **_extra_refs_item(args))
```

**M14 `bin/ltx-movie:2981-2982` (P3 reuse).** Old:
```python
            and all(k in entry and entry[k] == v for k, v in key.items())
            and os.path.isfile(path) and entry.get("still_sha256") == _sha256_file(path))
```
New:
```python
            and all(k in entry and entry[k] == v for k, v in key.items())
            and entry.get("extras") == key.get("extras")
            and os.path.isfile(path) and entry.get("still_sha256") == _sha256_file(path))
```

**M15 `bin/ltx-movie:3043-3047` (P3 job).** Old:
```python
        job["source"] = job["sources"][0]
        print("seed context: panel %d: Picture %d is the seed (%s), Picture %d is %s (%s)"
              % (n, 3 - context["picture"], files["original"], context["picture"],
                 SEED_CONTEXT_PICTURES[context["kind"]] % (n - 1), path))
    fit = _image_fit()
```
New:
```python
        job["source"] = job["sources"][0]
        print("seed context: panel %d: Picture %d is the seed (%s), Picture %d is %s (%s)"
              % (n, 3 - context["picture"], files["original"], context["picture"],
                 SEED_CONTEXT_PICTURES[context["kind"]] % (n - 1), path))
    _extra_refs_job(args, job)
    fit = _image_fit()
```

**M16 `bin/ltx-movie:3061` (P3 record entry).** Old:
```python
                "still_sha256": _sha256_file(still) if ok else None, "seconds": seconds, "error": error_text}
```
New:
```python
                "still_sha256": _sha256_file(still) if ok else None, "seconds": seconds, "error": error_text,
                **_extra_refs_item(args)}
```

**M17 `bin/ltx-movie:3075-3076` (P3 wait).** Old:
```python
        qe.wait_for_memory(qe.memory_floor(model_id), label, tag="ltx-movie")
        results, failure = qe.run_jobs(model_id, loras, [job], width, height, SEED_CONTEXT_SKILL, files["work"],
```
New:
```python
        qe.wait_for_memory(qe.memory_floor(model_id, _edit_references([job])), label, tag="ltx-movie")
        results, failure = qe.run_jobs(model_id, loras, [job], width, height, SEED_CONTEXT_SKILL, files["work"],
```

**M18 `bin/ltx-movie:3131-3132` (still mode's copies).** Old:
```python
    _image_fit().load_oriented_rgb(args.seed_image).save(files["original"], format="PNG")
    archive = os.path.join(paths["story_dir"], "redo", "%s-%d" % (
```
New:
```python
    _image_fit().load_oriented_rgb(args.seed_image).save(files["original"], format="PNG")
    _extra_refs_note(args)
    _extra_refs_write(args)
    archive = os.path.join(paths["story_dir"], "redo", "%s-%d" % (
```

**M19 `bin/ltx-movie:3198-3199` (frame mode's copies).** Old:
```python
    fit.load_oriented_rgb(args.seed_image).save(files["original"], format="PNG")
    placeholder = os.path.join(files["work"], "placeholder.png")
```
New:
```python
    fit.load_oriented_rgb(args.seed_image).save(files["original"], format="PNG")
    _extra_refs_note(args)
    _extra_refs_write(args)
    placeholder = os.path.join(files["work"], "placeholder.png")
```

**M20 `bin/ltx-movie:3345` (P4 prompt).** Old: `            prompts[n] = _cast_refs_prompt(lib, pairs[n], text)`. New: `            prompts[n] = _extra_refs_prompt(args, _cast_refs_prompt(lib, pairs[n], text), 2)`.

**M21 `bin/ltx-movie:3358-3363` (P4 key and reuse).** Old:
```python
        keys[n] = dict(settings, sources=sources, prompt=prompts[n], seed=args.image_seed, width=size[0],
                       height=size[1], still_width=still[0], still_height=still[1])
        entry = entries.get(n)
        path = os.path.join(paths["images_dir"], "panel_%02d.png" % n)
        if (n not in redo and isinstance(entry, dict) and entry.get("status") == "ok"
                and all(k in entry and entry[k] == v for k, v in keys[n].items())
```
New:
```python
        keys[n] = dict(settings, sources=sources, prompt=prompts[n], seed=args.image_seed, width=size[0],
                       height=size[1], still_width=still[0], still_height=still[1], **_extra_refs_item(args))
        entry = entries.get(n)
        path = os.path.join(paths["images_dir"], "panel_%02d.png" % n)
        if (n not in redo and isinstance(entry, dict) and entry.get("status") == "ok"
                and all(k in entry and entry[k] == v for k, v in keys[n].items())
                and entry.get("extras") == keys[n].get("extras")
```

**M22 `bin/ltx-movie:3427-3431` (P4 record entry).** Old:
```python
                "output": "cast_ref_edits/panel_%02d.png" % n if ok else None,
                "still": "images/panel_%02d.png" % n if ok else None,
                "still_sha256": (_sha256_file(os.path.join(paths["images_dir"], "panel_%02d.png" % n))
                                 if ok else None),
                "seconds": seconds, "error": error_text}
```
New: the same, with the last line `                "seconds": seconds, "error": error_text, **_extra_refs_item(args)}`.

**M23 `bin/ltx-movie:3446-3453` (P4 jobs and wait).** Old:
```python
    jobs = []
    for n in todo:
        sources = [stills[m.name] for m in plan["pairs"][n]]
        jobs.append({"n": n, "seed": args.image_seed, "prompt": plan["prompts"][n], "source": sources[0],
                     "sources": sources, "stage_path": os.path.join(files["work"], "panel_%02d.pending.png" % n),
                     "output_path": os.path.join(files["work"], "panel_%02d.png" % n)})
    try:
        qe.wait_for_memory(qe.memory_floor(model_id), label, tag="ltx-movie")
```
New:
```python
    _extra_refs_note(args)
    _extra_refs_write(args)
    jobs = []
    for n in todo:
        sources = [stills[m.name] for m in plan["pairs"][n]]
        jobs.append(_extra_refs_job(args, {
            "n": n, "seed": args.image_seed, "prompt": plan["prompts"][n], "source": sources[0], "sources": sources,
            "stage_path": os.path.join(files["work"], "panel_%02d.pending.png" % n),
            "output_path": os.path.join(files["work"], "panel_%02d.png" % n)}))
    try:
        qe.wait_for_memory(qe.memory_floor(model_id, _edit_references(jobs)), label, tag="ltx-movie")
```

**M24 `bin/ltx-movie:3494-3496` (the unused note).** Old:
```python
    if not plan["pairs"]:
        print(CAST_REFS_NONE_NOTE)
        return _phase2_shots(args, cmd)
```
New:
```python
    if not plan["pairs"]:
        print(CAST_REFS_NONE_NOTE)
        if getattr(args, "extra_refs", None):
            print(EXTRA_REFS_UNUSED_NOTE)
        return _phase2_shots(args, cmd)
```

**M25 `bin/ltx-movie:3942-3943` (the dry-run printer, before `_print_dry_run_plan`).** Old:
```python
def _print_dry_run_plan(args):
    paths = _story_paths(args.story_id)
```
New:
```python
def _print_extra_refs_plan(args):
    """The dry run's extra references block (extra references spec XR14). Reads; never writes."""
    qe = _qwen_edit()
    model_id, own, words = _extra_refs_edit(args)
    extras = args.extra_refs
    print("--- Extra references ---")
    print("Would add %d extra reference pictures to every Qwen edit of this run with %s, after the edit's own pictures "
          "(%s), each named in the edit prompt by its picture number and caption; each edit takes up to %d of the "
          "model's %d reference images. They are copied into %s when the edits run; a changed picture, caption, order "
          "or count re-edits every still that used it."
          % (len(extras), qe.label(model_id), words, own + len(extras), qe.max_references(model_id),
             os.path.join(_story_paths(args.story_id)["story_dir"], EXTRA_REFS_DIR)))
    for k, extra in enumerate(extras, start=1):
        print("  extra %d: %s (%s)" % (k, extra["path"],
                                       '"%s"' % extra["caption"] if extra["caption"] else "no caption"))


def _print_dry_run_plan(args):
    paths = _story_paths(args.story_id)
```

**M26 `bin/ltx-movie:4084`.** Old: `    print("--- Phase 3: manifest + dry-run ---")`. New:
```python
    if getattr(args, "extra_refs", None):
        _print_extra_refs_plan(args)
        print()
    print("--- Phase 3: manifest + dry-run ---")
```

**M27 `bin/ltx-movie:4237-4239` (main).** Old:
```python
    rc = _resolve_seed_context(args)
    if rc:
        return rc
```
New:
```python
    rc = _resolve_seed_context(args)
    if rc:
        return rc
    rc = _resolve_extra_refs(args)       # extra references XR4: after autotune and every edit resolver
    if rc:
        return rc
```

**Tests.** Create `tests/test_qwen_edit_extra_refs.py` (XR-T1-XR-T5) and `tests/test_ltx_movie_extra_refs.py` (XR-T6-XR-T18) as Section 5.1 specifies, in that order, with one `# --- XR-Tn (XRk): <title> ---` divider per test. Apply E1 and E2.

**Steps.**
1. Create the two new test files first, and run `python3 -B -m pytest -q -p no:cacheprovider tests/test_qwen_edit_extra_refs.py tests/test_ltx_movie_extra_refs.py`. Expected: `18 failed` (red), because `qwen_edit.max_references` and `movie._resolve_extra_refs` do not exist. No test fails on an import error of the test file itself.
2. Apply Q1-Q5, G1-G6, M1-M27, E1 and E2.
3. Run `python3 -B -m pytest -q -p no:cacheprovider tests/test_qwen_edit_extra_refs.py tests/test_ltx_movie_extra_refs.py tests/test_qwen_edit.py tests/test_qwen_edit_cast_refs.py tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py tests/test_ltx_movie_seed_edit.py tests/test_ltx_movie_shots_seed.py tests/test_ltx_movie_cast_refs.py tests/test_ltx_movie_seed_context.py tests/test_ltx_movie_seed_context_frame.py tests/test_ltx_movie_shots_zimage.py tests/test_ltx2_autotune.py`. Expected: no failure except F0 members.
4. Compile on both Pythons: `py_compile` of `qwen_edit.py movie_ui_seedgen.py tests/test_qwen_edit_extra_refs.py tests/test_ltx_movie_extra_refs.py`, and the `ast.parse` check of `bin/ltx-movie`.
5. Run `python3 tests/test_ltx_movie_offline.py`. Expected: `OK 347/347`.
6. Run the gate (`zsh $S/xr-baseline/gate-run.sh`). Expected: compared with F0, the only new failure is `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged`, and the 18 new tests pass.
7. Stage exactly `qwen_edit.py movie_ui_seedgen.py bin/ltx-movie tests/test_qwen_edit_extra_refs.py tests/test_ltx_movie_extra_refs.py tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py` (under `qwen-agent-workspace/`).
8. Commit: `git commit -m "qwen_edit, seedgen, ltx-movie: --extra-ref adds up to 9 user pictures to every Qwen edit of the run after its own pictures, named in the prompt, keyed for reuse, capped by the model's max_references and refused in low-RAM mode; the memory floor and the timeout grow with the references (extra-refs XR1-XR15, XR21, XR23)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`.

### Task 2: the movie UI (one commit)

**U1 `movie_ui_lib.py:946` (`DEFAULT_FIELDS`).** Old: `    "width": None, "height": None, "seed_upload": None, "seed_edit_model": None, "seed_edit_loras": None,`. New: the same line, then `    "extra_refs": [],`.

**U2 `movie_ui_lib.py:973` (`FIELD_FLAGS`).** Old: `    ("no_review", ("--no-review",)), ("seed_edit", ("--seed-edit-model", "--seed-edit-lora")),`. New:
```python
    ("no_review", ("--no-review",)), ("extra_refs", ("--extra-ref",)),
    ("seed_edit", ("--seed-edit-model", "--seed-edit-lora")),
```

**U3 `movie_ui_lib.py:1037-1040` (`build_argv`).** Old:
```python
        if fields.get("seed_edit_model") is not None:
            argv += qwen_edit_flags("--seed-edit-model", "--seed-edit-lora", fields["seed_edit_model"],
                                    fields.get("seed_edit_loras"))
    elif fields["width"] is not None and fields["height"] is not None:
```
New:
```python
        if fields.get("seed_edit_model") is not None:
            argv += qwen_edit_flags("--seed-edit-model", "--seed-edit-lora", fields["seed_edit_model"],
                                    fields.get("seed_edit_loras"))
        for item in fields.get("extra_refs") or []:        # extra references spec XR16
            argv += ["--extra-ref", extra_ref_arg(state, item)]
    elif fields["width"] is not None and fields["height"] is not None:
```

**U4 `movie_ui_lib.py:1151` (rule 12e and the argv helper, before `location_argv`).** Old: `def location_argv(kind, fields, ws_real, state, py=sys.executable):`. New:
```python
EXTRA_REFS_MAX = 9                     # bin/ltx-movie EXTRA_REFS_MAX
EXTRA_REFS_CAPTION_MAX = 60            # bin/ltx-movie EXTRA_REFS_CAPTION_MAX


def extra_ref_arg(state, item):
    """--extra-ref's value for one extra_refs item (extra references spec XR16): <state>/uploads/<upload_id>, then
    ":" and the stripped caption when it has one."""
    path = os.path.join(state, "uploads", item["upload_id"])
    caption = (item.get("caption") or "").strip()
    return path + ":" + caption if caption else path


def _rule_extra_refs(fields, state):
    """V1 rule 12e (extra references spec XR17): the Compose extra references' shape and what they need."""
    items = fields.get("extra_refs")
    if not (isinstance(items, list) and len(items) <= EXTRA_REFS_MAX
            and all(isinstance(i, dict) and set(i) == {"upload_id", "caption"} for i in items)):
        return ["extra references must be a list of at most 9 {upload_id, caption} items"]
    errors = []
    for k, item in enumerate(items, start=1):
        upload, caption = item["upload_id"], item["caption"]
        if not (isinstance(upload, str) and UPLOAD_ID_RE.fullmatch(upload)
                and os.path.isfile(os.path.join(state, "uploads", upload))):
            errors.append("extra reference %d: upload %s not found" % (k, upload))
        if caption is not None and not (isinstance(caption, str) and _argv_safe(caption)
                                        and 1 <= len(caption.strip()) <= EXTRA_REFS_CAPTION_MAX
                                        and ":" not in caption
                                        and all(ord(ch) >= 0x20 and ord(ch) != 0x7f for ch in caption)):
            errors.append("extra reference %d: caption must be 1 to 60 characters with no ':' and no control "
                          "characters" % k)
    uploads = [repr(i["upload_id"]) for i in items]
    if len(set(uploads)) != len(uploads):
        errors.append("extra references must be distinct images")
    if items and (fields.get("seed_upload") is None or fields.get("seed_edit_model") in (None, "as-is")):
        errors.append("extra references need a seed image and a Qwen seed edit model (not as-is)")
    if items and fields.get("no_low_ram") is not True:
        errors.append("extra references need No low-RAM mode (--no-low-ram): in low-RAM mode a Qwen edit takes at "
                      "most 2 pictures")
    return errors


def location_argv(kind, fields, ws_real, state, py=sys.executable):
```

**U5 `movie_ui_lib.py:1585`.** Old: `    errors += _rule_seed_edit(fields)                                        # 12d`. New: the same line, then `    errors += _rule_extra_refs(fields, state)                                # 12e`.

**U6 `movie_ui_batch.py:34, 42`.**
- Old: `GROUPS = (("panels", "length"), ("width", "height", "seed_upload", "seed_edit_model", "seed_edit_loras"))`. New:
  ```python
  GROUPS = (("panels", "length"),
            ("width", "height", "seed_upload", "seed_edit_model", "seed_edit_loras", "extra_refs"))
  ```
- Old: `    "seed_edit_model": "stills", "seed_edit_loras": "stills",`. New: `    "seed_edit_model": "stills", "seed_edit_loras": "stills", "extra_refs": "stills",`.

**U7 `movie_ui_batch.py:207-215` (`merge`).** Old:
```python
        elif key in ("width", "height"):
            fork["seed_upload"] = None
            fork["seed_edit_model"] = fork["seed_edit_loras"] = None
        elif key == "seed_upload" and value is not None:
            fork["width"] = fork["height"] = None
        elif key == "seed_upload" and value is None:
            fork["seed_edit_model"] = fork["seed_edit_loras"] = None      # rule 12d: no edit without a seed
    if fork["mode"] == "shots" and orig["mode"] != "shots" and fork["seed_edit_model"] == "as-is":
        fork["seed_edit_model"] = None      # Z-Image is chosen in Compose only, never by a fork
```
New:
```python
        elif key in ("width", "height"):
            fork["seed_upload"] = None
            fork["seed_edit_model"] = fork["seed_edit_loras"] = None
            fork["extra_refs"] = []                                       # rule 12e: no extras without an edit
        elif key == "seed_upload" and value is not None:
            fork["width"] = fork["height"] = None
        elif key == "seed_upload" and value is None:
            fork["seed_edit_model"] = fork["seed_edit_loras"] = None      # rule 12d: no edit without a seed
            fork["extra_refs"] = []                                       # rule 12e: no extras without an edit
    if fork["mode"] == "shots" and orig["mode"] != "shots" and fork["seed_edit_model"] == "as-is":
        fork["seed_edit_model"] = None      # Z-Image is chosen in Compose only, never by a fork
        fork["extra_refs"] = []             # rule 12e: no extras without an edit
```

**U8 `movie_ui_server.py:769-770` (`_fields_body`).** Old:
```python
        fields["seed_edit_model"], fields["seed_edit_loras"] = model_id, loras
    return fields
```
New:
```python
        fields["seed_edit_model"], fields["seed_edit_loras"] = model_id, loras
        extras, entry = fields.get("extra_refs"), seedgen.qwen_model(model_id)
        if isinstance(extras, list) and extras and entry["max_references"] == 1:     # extra references XR18
            raise ApiError(400, "%s reads only the first picture, so it takes no extra references" % entry["label"])
        if isinstance(extras, list) and 1 + len(extras) > entry["max_references"]:
            raise ApiError(400, "%s takes at most %d reference images per edit (the seed and %d extra references); "
                                "this request has %d extra references"
                           % (entry["label"], entry["max_references"], entry["max_references"] - 1, len(extras)))
    return fields
```

**U9 `static/movie-ui/app.js:25` (`S`).** Old: `seedOrigin: null, composeEngine: "qwen", composeAction: "story",`. New: `seedOrigin: null, composeEngine: "qwen", extraRefs: [], extraKey: "", extrasOn: false, composeAction: "story",`.

**U10 `app.js:465` (the new functions, before `composeFields`).** Old: `  function composeFields(action) {`. New:
```js
  // Extra references spec XR19: up to the model's max_references - 1 extra pictures after the seed, only for a
  // Qwen edit of the seed in No low-RAM mode; otherwise the control is disabled and the note says why.
  // composeExtrasUpdate sets S.extrasOn, which composeFields reads.
  const XR_LOW_RAM_NOTE = "Extra references need No low-RAM mode (under Advanced): in low-RAM mode every Qwen edit " +
    "takes at most 2 pictures. Tick it only on a host with at least 96 GiB of memory.";
  const XR_AS_IS_NOTE = "Extra references need a Qwen edit of the seed; the seed as-is is not edited.";
  function composeExtrasModel() {
    const model = COMPOSE_PICKER.state ? COMPOSE_PICKER.state.model : null;
    return model && model !== "as-is" ? seedQwenEntry(model) : null;
  }

  function composeExtrasUpdate() {
    const supported = (S.options && S.options.supported) || {};
    const entry = composeExtrasModel();
    const max = entry ? entry.max_references - 1 : 0;
    const lowRam = !$("#c-no-low-ram").checked;
    const zimage = $("#c-mode").value === "shots" && S.composeEngine === "zimage";
    S.extrasOn = supported.extra_refs !== false && composeSeedEditActive() && !lowRam && !zimage && max > 0;
    let note;
    if (lowRam) { note = XR_LOW_RAM_NOTE; }
    else if (!entry) { note = COMPOSE_PICKER.state ? XR_AS_IS_NOTE : "checking models…"; }
    else if (max < 1) { note = entry.label + " reads only the first picture, so it takes no extra references."; }
    else if (S.extraRefs.length > max) {
      note = entry.label + " takes at most " + max + " extra references; remove " + (S.extraRefs.length - max) + ".";
    } else {
      note = "Each Qwen edit gets the seed as Picture 1, then these pictures in order (up to " + max + " with " +
        entry.label + "). A caption names what a picture shows, e.g. the sword. More than 4 pictures in all can " +
        "blend faces, clothing and props.";
    }
    $("#c-xr-note").textContent = note;
    $("#c-xr-add").disabled = !S.extrasOn || S.extraRefs.length >= max;
    const key = JSON.stringify([S.extrasOn, S.extraRefs.map(function (x) { return x.upload_id; })]);
    if (key === S.extraKey) { return; }
    S.extraKey = key;
    const list = clear($("#c-xr-list"));
    S.extraRefs.forEach(function (x, i) {
      const caption = el("input", {type: "text", maxlength: "60", size: "24", placeholder: "caption, e.g. the sword"});
      caption.value = x.caption;
      caption.disabled = !S.extrasOn;
      caption.addEventListener("input", function () { x.caption = caption.value; });
      const remove = el("button", {type: "button", text: "Remove"});
      remove.addEventListener("click", function () {
        S.extraRefs.splice(i, 1);
        updateComposeButtons();
        preview();
      });
      list.appendChild(el("li", {}, ["Picture " + (i + 2) + ": upload " + x.upload_id.slice(0, 12) + " ", caption, " ",
        remove]));
    });
  }

  async function onExtraFile() {
    const file = $("#c-xr-file").files[0];
    $("#c-xr-file").value = "";
    if (!file) { return; }
    $("#c-xr-status").textContent = "uploading...";
    try {
      const id = await uploadFile(file);
      if (S.extraRefs.some(function (x) { return x.upload_id === id; })) {
        $("#c-xr-status").textContent = "that image is already an extra reference";
      } else {
        S.extraRefs.push({upload_id: id, caption: ""});
        $("#c-xr-status").textContent = "uploaded " + id.slice(0, 12);
      }
    } catch (err) {
      $("#c-xr-status").textContent = String(err.message);
    }
    updateComposeButtons();
    preview();
  }

  function composeFields(action) {
```

**U11 `app.js:482` (`composeFields`).** Old: `      seed_edit_model: seedEdit ? seedEdit.model : null, seed_edit_loras: seedEdit && seedEdit.model !== "as-is" ? seedEdit.loras : null,`. New: the same line, then `      extra_refs: S.extrasOn ? S.extraRefs.map(function (x) { return {upload_id: x.upload_id, caption: x.caption.trim() || null}; }) : [],`.

**U12 `app.js:614` (`updateComposeButtons`).** Old: `    // Seed-folder spec SD29: the folder mode of the Compose buttons.`. New: `    composeExtrasUpdate();` then the same line.

**U13 `app.js:890` (`fillCompose`).** Old: `    COMPOSE_PICKER.select(f.seed_edit_model || "as-is", f.seed_edit_loras || []);`. New: the same line, then:
```js
    S.extraRefs = (f.extra_refs || []).map(function (x) { return {upload_id: x.upload_id, caption: x.caption || ""}; });
    S.extraKey = "";
```

**U14 `app.js:935` (`setupCompose`).** Old: `    $("#c-seed-file").addEventListener("change", onSeedFile);`. New: the same line, then:
```js
    $("#c-xr-add").addEventListener("click", function () { $("#c-xr-file").click(); });
    $("#c-xr-file").addEventListener("change", onExtraFile);
```

**U15 `static/movie-ui/index.html:97`.** Old: `          <span id="c-sq-reason" class="muted"></span>`. New:
```html
          <div id="c-xr-box" data-field="extra_refs">
            <h3>Extra references <button id="c-xr-add" type="button">Add image…</button></h3>
            <input id="c-xr-file" type="file" accept="image/png,image/jpeg,image/webp" hidden>
            <span id="c-xr-status" class="muted"></span>
            <p id="c-xr-note" class="muted"></p>
            <ol id="c-xr-list"></ol>
          </div>
          <span id="c-sq-reason" class="muted"></span>
```
XR-T23's "U15 block" means these seven `c-xr` lines.

**U16.** Create `tests/test_movie_ui_extra_refs.py` (XR-T19-XR-T23), and apply E3-E14.

**Steps.**
1. Create the new test file first. `pytest tests/test_movie_ui_extra_refs.py` gives `5 failed`.
2. Apply U1-U15 and E3-E14.
3. Run `python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_extra_refs.py tests/test_movie_ui_qwen_edit.py tests/test_movie_ui_shots_seed.py tests/test_movie_ui_shots_zimage.py tests/test_movie_ui_batch.py tests/test_movie_ui_batch_zimage.py tests/test_movie_ui_builder.py tests/test_movie_ui_http.py tests/test_movie_ui_checks.py tests/test_movie_ui_seedfolder.py tests/test_location_ui.py tests/test_movie_ui_seams.py`. Expected: no failure except `test_mut26` and F0 members. Then run `node --check static/movie-ui/app.js` when node is installed, and compile `movie_ui_lib.py movie_ui_server.py movie_ui_batch.py tests/test_movie_ui_extra_refs.py` on both Pythons.
4. Run the gate. Expected: the only new failure is `test_mut26`, and the 23 new tests pass.
5. Stage exactly `movie_ui_lib.py movie_ui_server.py movie_ui_batch.py static/movie-ui/index.html static/movie-ui/app.js tests/test_movie_ui_extra_refs.py tests/fixtures/movie_ui/ltx-movie-help-current.txt tests/test_movie_ui_builder.py tests/test_location_ui.py tests/test_movie_ui_shots_seed.py tests/test_movie_ui_qwen_edit.py tests/test_movie_ui_batch.py tests/test_movie_ui_http.py`. `tests/test_movie_ui_builder.py` carries only E4 and E5 here; its BASELINE moves in Task 3.
6. Commit: `git commit -m "movie-ui: Compose extra references (up to the model's cap, disabled unless No low-RAM mode), V1 rule 12e, the server's model cap and the batch level (extra-refs XR16-XR20)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`.

### Task 3: the `test_mut26` re-baseline (a test-only commit; never amend)

1. `T1=$(git -C $S/xr-wt log -n1 --format=%H -- qwen-agent-workspace/bin/ltx-movie)`. It must be Task 1's commit.
2. Check that `git -C $S/xr-wt diff --name-only $T1 HEAD -- <every PIPELINE_FILES path under qwen-agent-workspace/>` prints nothing.
3. Edit `tests/test_movie_ui_builder.py:291`: the chain's last clause `then to bff48f7208183b87862e21d9eb798fca53994860 (motion-beat-only).` becomes `then to bff48f7208183b87862e21d9eb798fca53994860 (motion-beat-only), then to $T1 (extra-refs).`, with the full 40-character sha written in.
4. Edit `:293`: `    BASELINE = "bff48f7208183b87862e21d9eb798fca53994860"` becomes `    BASELINE = "$T1"`.
5. `pytest tests/test_movie_ui_builder.py -k mut26` passes. Stage only `tests/test_movie_ui_builder.py`, and commit with `-m "tests/test_movie_ui_builder.py: test_mut26 BASELINE moves to the extra-refs commit" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`.

### Verification (controller)

- **V1.** Run the full suite. Compared test by test with the baseline: no test changed from passed to failed or disappeared; the failures are exactly F0; the new tests are the 23 of XRK1, and all pass. `python3 tests/test_ltx_movie_offline.py` still prints `OK 347/347`, and the other four OK lines are unchanged.
- **V2.** `git diff --name-only fcd5d86 HEAD` lists exactly the files of Section 0.4 (D1-D10) plus this spec. Among `PIPELINE_FILES`, only `bin/ltx-movie` differs from `bff48f7`.
- **V3.** Run the mutation check of 5.3 on copies of the tree.
- **V4.** An Opus design review of the three commits against this spec, before the PR.
