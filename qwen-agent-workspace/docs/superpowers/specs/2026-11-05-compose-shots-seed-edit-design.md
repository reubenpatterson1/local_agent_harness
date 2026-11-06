# Compose shots mode with a seed image: every panel's still is a Qwen edit of the original seed

Date: 2026-11-05

Status: design spec. User request (2026-11-05): "spec using Qwen image edit mflux to enable seed image and the shots mode in Compose so the panels would be created from the initial seed for all the panels." The binding earlier decision stands: Z-Image-Turbo makes every image that is created from text; the Qwen registry is used only for edits and for Compose with a seed image ([QE] §0.0 items 1 and 4). This spec extends item 4 to shots mode. Every design choice is made here and marked **[spec choice]** where the request leaves it open; Section 13 lists the open questions that only live checks can settle. The implementer makes no design decisions.

Repository `/Users/reubenpatterson/local_agent_harness`. Worktree `$S/ss-wt`, branch `shots-seed-edit` off `bdeb3ae` (the merge of PR #10, qwen-edit-models). `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`. `WS` is `qwen-agent-workspace/`. Every path is relative to `WS`; every line number cites `bdeb3ae`.

Builds on **[QE]** `docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md` (read in full; merged as PR #10), **[SHOTS]** `2026-10-06-shots-mode-design.md`, **[MU]** `2026-10-19-movie-ui-design.md`, **[SD]** `2026-11-01-seed-folder-compose-design.md`, **[BF]** `2026-10-30-batch-forks-design.md`. Every requirement of those specs stays in force except where Section 11 names it as amended.

Requirement IDs are **SE1-SE34**, tests **SET1-SET21**, KPIs **SEK1-SEK10**, live checks **L1-L5**. A grep of the worktree at `bdeb3ae` found no file using `SE<n>`, `SET<n>` or `SEK<n>`.

Terms (as [QE]): a **registry model** is one `movie_ui_seedgen.QWEN_MODELS` entry; a **selection** is a registry model ID plus `[{"id", "scale"}]`; a **settings block** is `qwen_edit.settings(model_id, loras)`, exactly `{"qwen_model": {"id", "repo"}, "loras": [{"id", "repo", "file", "scale"}], "steps", "scheduler"}`. **Shots seed mode** is a `bin/ltx-movie` run with `--shots` and `--seed-image` (Compose: mode `shots` with a seed image or a seed folder).

---

## 0. Scope

### 0.1 The request, as binding rules

1. Shots mode WITH a seed image: every panel's still is a Qwen edit of the ORIGINAL seed image (never of another panel's still, never of a previous clip's frame), each driven by that panel's own `Image:` text.
2. Shots mode WITHOUT a seed image is unchanged (Z-Image-Turbo per stills-LoRA group, `bin/ltx-story-images`).
3. Chained mode (with or without a seed, with or without `--seed-edit-model`) is unchanged, including Phase 1c and `seed_edit.json`.
4. All N edits of one Phase 2 run go through `qwen_edit.run_jobs` as ONE batch in ONE child load.
5. Content safety screens every output; any blocked or failed panel fails the job. No silent fallback to the unedited seed or to Z-Image.
6. Z-Image stays for every image made from text; nothing here adds a Qwen text-to-image path.

### 0.2 What shots mode does with a seed image today (verified at `bdeb3ae`)

- **CLI: refused.** `main` runs `_resolve_shots` (`bin/ltx-movie:2903`) before casting, the story engine, `_resolve_seed_edit` (`:2921`), the dry run, the lockfile and every phase. `_resolve_shots` (`:1238-1284`) returns 2 at `:1251-1255` with `Error: --shots is not supported with --seed-image: the seed image can be only panel 1's still, and the seed-image story preface describes the chained flow`. The dry run is refused the same way. `--seed-edit-model` is therefore never reached in shots mode; there is no shots-specific handling of it anywhere.
- **If the refusal were removed with no other change**, the run would be wrong in four ways: QE44 (`_phase_sequence`, `:2840-2842`) would insert Phase 1c (one edit, for panel 1 only); `phase2_stills` adds `--seed-image` to the Phase 2 command (`:2093-2096`) and `_phase2_shots` copies that command into every stills-group run (`:2170-2206`), so the group holding panel 1 would rewrite `panel_01.png` from the seed (`bin/ltx-story-images:471-491`, regardless of an existing file) and every other panel would be Z-Image; the legacy story prompt would prepend `SEED_IMAGE_PREFACE`/`SEED_IMAGE_POSTFACE` (`:225-234`, applied at `:247-253` for any non-no-stills mode), whose postface says "Every later panel has exactly two fields -- Motion:, Narration: -- with no Image: field", contradicting the shots template (`:188-223`) that requires an `Image:` on every panel.
- **movie-ui V1 rule 8: refused.** `movie_ui_lib.py:1564-1565` adds `a seed image cannot be used with shots mode`, so `/api/preview` lists it, `/api/validate` fails V1, `/api/jobs` answers 409 `validation failed`, and every seed-folder row is refused (`tests/test_movie_ui_seedfolder.py:544-562`, SDT17).
- **The page: no gating of the seed controls by mode.** The Seed image and Seed folder radios stay usable in shots mode and `composeFields` sends `seed_upload` (`static/movie-ui/app.js:427-462`), so the V1 text appears in the preview errors. `composeSeedEditActive` (`app.js:413-417`) is true only when the mode is `chained`, so in shots mode the `c-sq` picker is hidden and `seed_edit_model` is sent as `null`.

### 0.3 Grounding (verified at `bdeb3ae`)

**`bin/ltx-movie` (pinned).**
- Top-level imports are stdlib (`argparse`, `glob`, `importlib.machinery`, `json`, `os`, `shlex`, `subprocess`, `sys`, `threading`, `time`) plus `pipeline_log` (`:115-128`); **there is no top-level `import hashlib`** — `phase_seed_edit` imports it inside the function (`:2268`). [QE] QE40 said it would be top-level; the code differs. This spec follows the code (local import).
- `SEED_EDIT_SKILL`, `SEED_EDIT_SCHEMA` `:135-137`; `STORY_PROMPT_TEMPLATE_SHOTS` `:188-223`; `SEED_IMAGE_PREFACE` `:225-229`; `SEED_IMAGE_POSTFACE` `:231-234`; `build_story_prompt` `:236-254` (seed branch `:247-253`).
- Parser: `--seed-image` `:307-313`, `--seed-edit-model` `:314-319`, `--seed-edit-lora` `:320-323`, `--image-seed` (default 0) `:338`, `--stills-lora` (`_RepeatableLoraAction`, so `args.stills_lora_path_specs`) `:353`, `--shots` `:402-409`, `--redo` `:410-414`, `--min-avail-gib` (default 25.0) `:464`.
- `_load_story_panels` `:732-750` (panel dicts with `"image"`); `_image_fit` `:811-816`; `_qwen_edit` (loads `qwen_edit.py` by path) `:835-838`.
- `_resolve_seed_edit` `:990-1029` (rows 1-9 of QE43; row 9 skips the host check under `--dry-run`/`--story-only`).
- `_resolve_global_loras` `:1062-1102`; `_catalog_plan` `:1710-1731`; `_catalog_stills_flags` `:1824-1845`.
- `_resolve_shots` `:1238-1284`; `phase0_seed` `:1392-1411` (video geometry from the seed, multiples of 64).
- `_story_context` `:1669-1700` (passes `seed_agent_image` in every mode); `_phase1_robust` `:1854-1908`; `_phase1_shots_finish` (legacy engine, shots) `:1971-2069`.
- `_still_size` (twice the video size) `:2076-2082`; `phase2_stills` `:2085-2123` (header `:2087`, shots dispatch `:2109-2110`); `_panel_list` `:2126-2127`; `_shots_stills_groups` `:2130-2158`; `_shots_missing_stills` `:2161-2167`; `_phase2_shots` `:2170-2206`; `phase_release_story_server` `:2209-2227`.
- Phase 1c: `_seed_edit_paths` `:2230-2236`; `_panel1_edit_prompt` `:2239-2246`; `_seed_edit_size` `:2249-2251`; `_write_seed_edit_record` `:2254-2259`; `phase_seed_edit` `:2262-2330` (clears the old record, `seed-edited.png` and the stage file before an edit `:2296-2298`).
- `_redo_moves` `:2333-2347` (archive layout `<story>/redo/<stamp>-<pid>/images/…`); `phase_redo_shots` `:2350-2375`.
- `_shots_image_flags` `:2379-2385`; `phase3_manifest` `:2388-2442` (shots: `--shots` + one `--image images/panel_NN.png` per panel, `:2396-2397`); `_phase4_flags` `:596-610` (shots: `--on-panel-failure skip`).
- Dry run: `_print_shots_stills_plan` `:2626-2646`; `_print_dry_run_plan` `:2649-2817` (Phase 0 text `:2700-2707`; Phase 1c block `:2731-2743`; Phase 2 block `:2745-2775`); `_phase_sequence` `:2824-2845` (QE44 insertion `:2840-2842`); `main` `:2848-2967`.

**Story engines.**
- Robust engine (`story_engine.py`, pinned, untouched here): the plan call receives the seed image in every mode (`:4891`) and its prompt gets `SEED_PARAGRAPH` (`:380-384`, inserted at `:1142-1144`): "It IS the first frame of this movie. Describe every person it shows faithfully in cast … make beat 1 start from the exact scene it shows." Panel calls get the image and `SEED_PANEL` ("describe in image exactly what it shows") **only in chained mode for panel 1** (`:4073`, `:4928`). So in shots mode no panel's `Image:` is written as a literal description of the seed; the cast descriptions in the plan come from the seed.
- Shots stories copy each on-screen character's full description from the `## Characters` section into every `Image:` (template `:206-210`; S9 repair `_shots_repair_s9` `:1923-1953`).

**`bin/ltx-story-images` (pinned, untouched).** Z-Image only; `--seed-image` makes panel 1 a letterboxed copy of the seed (`:471-491`); a generated panel whose file exists is skipped without `--force` (`:493-497`); `tests/test_ltx_story_images.py` pins source counts (`"source": "seed"` ×3, `"source": "generated"` ×4 at `:399-402`; `_compose_prompt(` ×3 at `:591`) and its stdlib-only import-time promise.

**`qwen_edit.py` (unpinned, untouched).** `CHILD_TIMEOUT_S = 3600`, `JOB_TIMEOUT_S = 600` (`:47-48`); `wait_for_memory(floor, label, tag)` `:267`; `child_timeout(n) = max(3600, 600 n)` `:411-412`; `run_jobs(model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None, noun="job")` `:456-…` (mflux: screens every output in the parent with `content_safety.assert_image_safe(rgb, skill=skill, prompt=job["prompt"])`, a blocked stage file is deleted, `on_result` fires after the file is at `output_path`; legacy `qwen2511-bf16`: the `character_dataset.py qwenedit` child screens each job with the spec's skill and per-job prompt, `character_dataset.child_qwenedit` `:1908-…`). Memory floors from the registry: `qwen21-q4` 20, `qwen21-q8` 32, `qwen21-bf16` 56, `qwen2511-q4` 32, `qwen2511-bf16` 64 GiB; multiples 32 (2.1) and 16 (2511) (`tests/test_qwen_edit.py` QET2).

**Downstream of Phase 2 in shots mode (verified: nothing assumes a chained start frame).** Phase 3 builds a `--shots` manifest in which every panel is conditioned on its own `images/panel_NN.png` (`bin/ltx-story-manifest` schema 3, `conditioning "still"`); `bin/ltx-mlx-render` keys each still unit's clip reuse on `image_sha256` (`:561-577`), so a changed still re-renders its clip under `--resume`; `conditioning "chain"` (previous clip's last frame) is never used in shots mode. `images/images.json` has no reader outside `bin/ltx-story-images` (grep of `bin/`, `*.py`); `movie_ui_batch` only copies it.

**movie-ui.**
- `movie_ui_lib.py`: `DEFAULT_FIELDS` `:942-955`; `FIELD_FLAGS` (31 entries, last `seed_edit`) `:960-974`; `build_argv` (`--seed-image` then `qwen_edit_flags` inside `if fields["seed_upload"]` `:1027-1031`; `--shots` `:1047-1048`) `:1016-1073`; `help_flags`/`supported_map` `:1310-1339`; `validate_fields` rule 8 `:1559-1565`, rule 12d `:1574`, rule 16 (redo needs shots) `:1584-1597`, rule 18 `:1603-1608`; `stills_needed` `:1771-1772`; `dry_run_check` (V6) `:2218-2224`; `PHASE_RE` `:2255`; `STILL_NAME_RE` `:2270`; `job_phases` `:2288-2298`; the Phase 2 stills progress (`expected` = the panel count in shots mode) `:2416-2424`; `job_vlm` `:421-436`; `cancel_groups`/`cancel_tree` signal every descendant process group (`:268-299`), which includes the Qwen child's own session.
- `movie_ui_server.py`: `COMPOSE_KINDS` (`redo` → `movie`) `:739`; `_fields_body` (cleans a named seed-edit selection, 400) `:759-769`; `edit_availability` `:777-780`; `_h_job_create` (409 only for action `movie`) `:844-856`; `_h_seed_folder` `:949-` (409 for action `movie`).
- `movie_ui_batch.py`: `GROUPS` `:34`; `FIELD_LEVELS` (`seed_edit_model`, `seed_edit_loras` at `stills`; `mode`, `seed_upload` at `replan`) `:38-46`; `COPY_FILES` `:50-55`; `merge` `:196-214`; `copy_plan` `:436-`.
- Page: `index.html` Compose `c-sq` block `:90-98`; `app.js` `COMPOSE_PICKER = qwenPicker("c-sq", true)` `:50`; `composeSeedEditActive` `:413-417`; `composeSeedDefault` `:421-425`; `composeFields` `:427-462`; `updateComposeButtons` `:539-571` (picker block `:545-555`); `onSeedFile` `:580-594`; `onFolderPick` `:610-638`; `fillCompose` `:811-` (`COMPOSE_PICKER.select(f.seed_edit_model || "as-is", …)` `:830`); `setupCompose` (panel-wide `change` → `updateComposeButtons(); preview();`) `:866-`; `qwenPicker` (as built; its `enabled` is `id === "as-is" || (Boolean(seedQwenEntry(id)) && !(probe(id) && probe(id).ok === false))`, pinned by QET38).

**Tests.** `tests/test_movie_ui_builder.py`: `NEW_PY` `:213-219`; `PIPELINE_FILES` (includes `bin/ltx-movie`, `bin/ltx-story-images`, `story_engine.py`) `:222-227`; `test_mut26` `BASELINE = "d2cf22881a733bb49b97c4388b22466b589ec1f0"` `:271-299`. Texts this spec changes are pinned at `tests/test_shots_mode.py:936-938` (S33), `tests/test_movie_ui_checks.py:76` (MUT4), `tests/test_movie_ui_seedfolder.py:560` (SDT17).

### 0.4 Deliverables

| # | File | Pinned | Change |
|---|---|---|---|
| D1 | `bin/ltx-movie` | **yes** (`PIPELINE_FILES`) | shots seed mode: rules, Phase 2 branch, record, dry run, help (Section 3) |
| D2 | `movie_ui_lib.py` | no | V1 rule 8, `job_phases` (SE23, SE26) |
| D3 | `movie_ui_server.py` | no | 409 for `redo` too (SE25) |
| D4 | `movie_ui_batch.py` | no | `COPY_FILES["render"]` gains `seed_edits.json` (SE27) |
| D5 | `static/movie-ui/index.html` | no | picker label span, shots note (SE29) |
| D6 | `static/movie-ui/app.js` | no | picker active in shots mode, as-is disabled there (SE30, SE31) |
| D7 | tests | — | SET1-SET21 and the Section 6.3 edits |
| D8 | `tests/test_movie_ui_builder.py` | — | `test_mut26` BASELINE, in its own test-only commit (Section 9.3) |

Untouched (verified callers suffice): `bin/ltx-story-images`, `story_engine.py`, `qwen_edit.py`, `seed_edit_mflux_child.py`, `movie_ui_seedgen.py`, `content_safety.py`, `ltx_image_fit.py`, `bin/ltx-story-manifest`, `bin/ltx-mlx-render`, `scripts/deploy/build_pkg.py`, `static/movie-ui/app.css`, every other `PIPELINE_FILES` member.

### 0.5 Out of scope

- Any Qwen text-to-image; any Z-Image fallback for a blocked or failed edit.
- Shots panels conditioned on another panel's still (multi-reference edits), per-panel model choice, a different model for panels that show no seed person (Open question 3).
- Changes to `bin/ltx-story-images`, `story_engine.py` (including `SEED_PARAGRAPH`) or `qwen_edit.py`.
- Chained mode behaviour, including the existing re-edit in chained render-level batch forks (Section 12 item 9).
- A batch-page control for the edit model (as [QE]).
- Editing at the still size (2W × 2H); this spec edits at the video size (SE18, Open question 4).
- Relaxing V2 "stills" (the Z-Image dependency probe) for shots seed mode (Section 12 item 10).
- Running a real model, server, render or download in tests; any agent access to macstudio.

### 0.6 Success criteria (KPIs)

| ID | Criterion | Verified by |
|---|---|---|
| SEK1 | `python3 -m pytest tests/ -q -rA` from `WS` has no failure beyond those recorded at `bdeb3ae` in step 9.1.3 (expected: `test_d2_copied_literals_match_the_spike`, `test_rst62_import_sets`, per [QE] QEK1) | 9.1 gate |
| SEK2 | `python3 tests/test_ltx_movie_offline.py` prints the same `OK n/n` line as at `bdeb3ae` (expected `OK 347/347`); no check is added to or removed from that file | 9.1 gate |
| SEK3 | Unchanged paths: chained (with seed, with seed + `--seed-edit-model`, without seed) and shots without seed keep their phase tuples, Phase 2 commands and dry-run lines | SET3, SET4, SET14, the existing QET26-QET32 and S-tests unchanged |
| SEK4 | One child per Phase 2 run: `run_jobs` is called exactly once, with exactly the panels to edit, in panel order; zero times when every still is reused | SET5, SET9, SET15 |
| SEK5 | Every output is screened (skill `ltx_movie_shots_seed_edit`, the job's own prompt); a blocked or failed panel makes Phase 2 exit 1 with no still for that panel and no fallback | SET6, SET7, SET15 |
| SEK6 | A failed, blocked or interrupted batch leaves no `ok` record entry for any panel whose still was not written in that run; finished panels are reused by the next run | SET7, SET8 |
| SEK7 | L1: the user judges that at least 10 of the 12 panels show the seed's person recognisably (face, hair, clothing) | L1 |
| SEK8 | L1: the user judges that at least 8 of the 12 panels are visibly a different shot from the seed (pose, place or framing), not the seed again | L1 |
| SEK9 | L1: Phase 2 of a 12-panel run with `qwen21-q4` + `uncensored` finishes without a timeout; seconds per panel recorded | L1 |
| SEK10 | At least 20 GiB free on the disk holding `WS` before the gate runs | 9.1 |

### 0.7 Must-haves and nice-to-haves

Every SE requirement and SET test is a must-have. L4 is optional. There are no nice-to-haves.

---

## 1. Decisions (the six questions, decided and justified)

**1. Which stage runs the N edits: Phase 2 inside `bin/ltx-movie`, as the shots seed branch of `phase2_stills`.** **[spec choice]**
- Not `bin/ltx-story-images`: it is pinned too, but the real cost is larger than a baseline move — it is a Z-Image tool whose stdlib-only import promise and source-count pins (I13, I21) a Qwen branch breaks, and `_phase2_shots` runs it once per stills-LoRA group (`:2170-2206`), so the edits would split across groups and load the Qwen model once per group, violating rule 0.1.4.
- Not a Phase 1c before Phase 2: in shots seed mode the edits ARE the stills. Running them as Phase 2 (a) keeps the movie-ui stills progress working with no UI change (`movie_ui_lib.py:2416-2424` counts `images/panel_NN.png` against the panel count during phase "2"), (b) keeps `job_phases` and the phase tuple shapes of shots mode (no new phase), (c) lets `--redo` work unchanged (it moves the redo panels' stills aside before Phase 2, `phase_redo_shots`), and (d) never calls `bin/ltx-story-images`, so `bin/ltx-story-images` stays untouched. QE44's Phase 1c insertion is switched off in shots mode (SE7).
- `bin/ltx-movie` is pinned (`PIPELINE_FILES`), as it was for PR #10: one deliberate edit and one test-only `test_mut26` baseline commit (Section 9.3).
- The batch is one `qwen_edit.run_jobs` call with jobs `[{n, seed, prompt, source = seed-original.png, stage_path, output_path}]` for every panel to edit: one mflux child load, `child_timeout(len(jobs))`, the registry memory floor, per-output screening.

**2. The per-panel prompt: `SHOTS_SEED_EDIT_PREFIX` + `_compose_prompt(Image:, Style:)`, no trigger words.** **[spec choice]**
- The panel's `Image:` text (with the story's `Style:` text, joined exactly as `bin/ltx-story-images` joins them) is the shot description; the full shot prompt (Motion, Narration) is not used: motion is the video model's job and narration is not visual.
- Cast and location trigger tokens, location trigger prefixes and catalog `--lora-trigger` words are Z-Image LoRA tokens; they are NOT inserted (no Z-Image LoRA runs, so a trigger would be noise in a Qwen prompt).
- In shots mode the robust engine never writes a panel's `Image:` as a literal description of the seed (Section 0.3), so the PR #10 "panel 1 describes the seed literally" issue does not apply to panels 2..N; panel 1 will usually be close to the seed, because the plan prompt asks beat 1 to start from the seed's scene — that is the intended opening shot.
- Identity: every panel is an edit of the same original, so drift cannot compound (unlike a chain). The `Image:` field repeats each character's full description from `## Characters` (written from the seed by the plan call), which reinforces the seed's look.
- "Every panel looks the same" risk: instruction-tuned edit models tend to keep the source's pose and composition when given a scene description. Mitigation (unmeasured; L1/SEK8 measure it): a fixed instruction prefix that asks to keep each seed person's face, hair, skin tone, build and clothing and to change pose, action, place, background, lighting, framing and camera, and to leave out anyone the shot does not describe. Its exact text is SE1.
- Pinned cast (`--character`): the Cast block still fixes phrases and descriptions in the story and the character video LoRAs still apply in Phases 3-4; the character's stills LoRA does not apply. When the library character is not the person in the seed, the edit is pulled between the description and the source; the user should use a seed that shows the cast character (Section 12 item 3).
- Characters who are not in the seed have no visual anchor; each panel invents them from text (Section 12 item 2, Open question 3).

**3. Model and LoRA selection: the Compose picker (`COMPOSE_PICKER`, `c-sq`), with "Seed as-is" disabled in shots mode.**
- "Seed as-is (no edit)" cannot make N different stills, so in shots mode its option is disabled and relabelled `Seed as-is (no edit) — chained mode only`; when the picker's current choice is as-is (a Seeds-tab "Use" seed, or a loaded job) it is reset to the registry default (`qwen21-q4` + `uncensored` @ 1.0, `COMPOSE_PICKER.select(null, null)`). The picker's label reads `Every panel from the seed` in shots mode, `Panel 1 from the seed` otherwise. `qwenPicker` itself is not changed (QET38 pins its `enabled`); the Compose wiring does this after `COMPOSE_PICKER.update()` (SE31).
- CLI: `--shots --seed-image` requires `--seed-edit-model ID` (absent or `as-is` refused, SE2). **[spec choice]** No silent default model on the CLI, matching [QE]'s "absent means as-is" for Compose: a hand-run never picks a model the user did not name.
- Memory floor: `qe.memory_floor(model_id)` after Phase 1b's `--min-avail-gib` wait (unchanged). Timeout: `qwen_edit.child_timeout(n)` for the n panels being edited: 3600 s for 1-6 panels, 7200 s for 12, 9000 s for 15, 14400 s for 24. A timeout keeps every finished panel (SE16), so a rerun continues.
- Z-Image LoRAs: `--stills-lora` is refused in shots seed mode (an explicit user choice that would be ignored, SE2); V1 refuses non-empty `stills_loras` (SE23). Character and location stills LoRAs and the plan's catalog stills pick are not refused (characters and locations also shape the story and the video); Phase 2 prints one note (SE14). The page shows a note under the picker (SE29).

**4. Output, record, resume.**
- Size: each edit at the video size floored to the model's multiple (`_seed_edit_size`, unchanged; the geometry is already a multiple of 64), then fitted with `ltx_image_fit.fit_letterbox` into `images/panel_NN.png` at `_still_size` (2W × 2H). Same aspect, so no bars. **[spec choice]** Video size, not still size: 4× fewer pixels per edit for N edits; `ltx-2-mlx` conditions at most at the video size, so the 2× upscale loses little (Open question 4).
- Record: a NEW file `<story>/seed_edits.json` (schema `ltx-movie.seed-edits.v1`) with one entry per panel. Chained mode's `seed_edit.json` (QE48) is unchanged and never written in shots seed mode. **[spec choice]** A separate file keeps the PR #10 record and its reuse rule byte-for-byte.
- Reuse: a panel is reused iff its entry is `ok`, its key (seed bytes' sha256, prompt, seed, edit size, still size, settings block) equals this run's, `images/panel_NN.png` exists and its sha256 equals the entry's `still_sha256`, and it is not a `--redo` panel. Every other panel is edited; its existing still is moved aside (never deleted) into `<story>/redo/<stamp>-<pid>/images/` (the `--redo` archive layout). **[spec choice]** keyed reuse, as PR #10's Phase 1c, rather than shots mode's existence-only rule: a hand-edited `Image:` line or a changed model re-edits exactly the affected panels.
- The PR #10 final-fix guarantee, for N panels: before the child starts, the entries of every panel about to be edited are removed from `seed_edits.json` (written atomically); each entry is written again only when its result is known (`ok` after the still is in place, `blocked`), and `failed` after the batch. An interrupted run therefore leaves `ok` entries only for stills it finished.
- Any blocked panel: the whole batch still runs to its end (the other panels are kept and reused next time), then Phase 2 exits 1. No fallback.

**5. Batch forks, dry run, story server, gating, video stage.**
- Batch forks: no new field; `seed_edit_model`/`seed_edit_loras` stay at level `stills` (a stills fork copies no stills and no record, so every panel is re-edited with the fork's selection). A `render` fork copies `images/panel_NN.png` and, with SE27, `seed_edits.json`, so its Phase 2 reuses every still. `merge` unchanged.
- Dry run: prints the shots seed Phase 2 block (no `bin/ltx-story-images` command, no Phase 1c block) and, with an existing story.md, which panels would be edited and which reused; reads no weights.
- Story server: unchanged. Phase 1b stops it and waits for `--min-avail-gib` before Phase 2; the movie-ui VLM policy is unchanged (a movie with story.md is `forbidden`, else `required`; postflight restore as today).
- UI gating: no new `FIELD_FLAGS` entry, because no flag is new. **[spec choice]** A pre-PR #10 workspace lacks `--seed-edit-model`, so V1 rule 18 refuses it; a PR #10-era workspace (`bdeb3ae` up to this feature) has the flags but refuses `--shots` with `--seed-image`, and the V6 dry-run check fails with that CLI text, so nothing is queued. A help-text capability marker was rejected as a new mechanism for a one-merge window.
- Video stage: nothing downstream assumes a chained start frame in shots mode (Section 0.3).

**6. Flag surface: no new flag.** The CLI change is the `_resolve_shots` rules (SE2), the Phase 2 branch, three help texts and the docstring.

---

## 2. Architecture

```
bin/ltx-movie --shots --seed-image P --seed-edit-model ID [--seed-edit-lora ID=S ...]
  _resolve_shots (SE2) -> _resolve_seed_edit (unchanged; sets args.seed_edit) -> phases:
  Phase 0 seed -> Phase 1 story (robust engine) -> Phase 1b -> [Redo] -> Phase 2 stills:
      phase2_stills -> _phase2_shots_seed (SE15)
          _shots_seed_plan: prompts, keys, reuse / todo (read-only)
          move stale stills aside, clear todo entries, write seed-original.png
          qwen_edit.wait_for_memory -> qwen_edit.run_jobs(N todo jobs, one child)
              on_result: fit into images/panel_NN.png, record entry
  -> Phase 3 manifest (--shots, unchanged) -> Phase 4 render (unchanged)
movie-ui: picker active in shots mode (as-is disabled) -> V1 rule 8 (SE23) -> 409 probe (SE25) -> same argv builder
```

---

## 3. `bin/ltx-movie` (pinned; SE1-SE22)

### 3.1 Constants

- **SE1.** Directly after `SEED_EDIT_SCHEMA = …` (`:137`), add exactly:

```python
# Shots seed edits (docs/superpowers/specs/2026-11-05-compose-shots-seed-edit-design.md, SE1): in shots mode
# with a seed image every panel's still is a Qwen edit of the original seed.
SHOTS_SEED_EDIT_SKILL = "ltx_movie_shots_seed_edit"
SHOTS_SEED_EDITS_SCHEMA = "ltx-movie.seed-edits.v1"
SHOTS_SEED_EDIT_PREFIX = (
    "Edit this photo into a new shot of the same film. Every person from the photo who appears in the new "
    "shot keeps exactly the same face, hair, skin tone, build and clothing. Change their pose and action, "
    "the place, the background, the lighting, the framing and the camera angle to match the new shot, and "
    "leave out anyone the new shot does not describe. The new shot: ")
SHOTS_SEED_LORA_NOTE = ("note: Z-Image stills LoRAs (character, location and catalog stills LoRAs) do not apply "
                        "to Qwen edits; every panel's still is edited without them")
```

### 3.2 Option rules

- **SE2.** In `_resolve_shots`, the block `:1251-1255` (the seed refusal) is replaced by exactly:

```python
    if getattr(args, "seed_image", None):
        # Shots seed edits SE2: every panel's still is a Qwen edit of the seed.
        if args.story_legacy or args.story_prompt_override is not None:
            print("Error: --shots with --seed-image needs the default story engine; it cannot be combined "
                  "with %s" % ("--story-legacy" if args.story_legacy else "--story-prompt-override"),
                  file=sys.stderr)
            return 2
        if args.seed_edit_model in (None, "as-is"):
            print("Error: --shots with --seed-image needs --seed-edit-model ID: every panel's still is a Qwen "
                  "edit of the seed, so the seed cannot be used as-is", file=sys.stderr)
            return 2
        if getattr(args, "stills_lora_path_specs", None):
            print("Error: --stills-lora cannot be combined with --shots and --seed-image: every panel's still "
                  "is a Qwen edit of the seed, and Z-Image stills LoRAs do not apply to it", file=sys.stderr)
            return 2
```
  Execution then continues to the existing `if args.redo is None: return 0` and the `--redo` rules (unchanged). The legacy engine is refused because its seed preface and postface describe the chained flow (Section 0.2). The rules apply to every run, including `--dry-run` and `--story-only` **[spec choice]** (one rule, no exceptions; the page always sends the model).
- **SE3.** `_resolve_seed_edit` is unchanged. After SE2, a shots seed run that reaches it always names a model other than `as-is`, so on exit 0 `args.seed_edit` is `{"qwen_model", "loras"}`; its rows 6-9 (no `qwen_edit.py`, unknown model, bad LoRA, host check outside `--dry-run`/`--story-only`) apply unchanged.

### 3.3 Help and docstring

- **SE4.** Three help strings become exactly (the Python string literals may be split across lines as the surrounding code does):
  - `--seed-image`: `image that becomes the movie's literal first frame: Phase 0 derives the video width/height from its aspect ratio (1:3 to 3:1) and attaches a scaled copy to the Phase 1 story prompt; Phase 2 fits the ORIGINAL (scaled, never cropped) into panel_01.png at twice the video size, same as z_image, so ltx-2-mlx's own downscale keeps more real detail. With --shots, Phase 2 instead edits the ORIGINAL into every panel's still (see --seed-edit-model). Incompatible with --no-stills and with --video-width/--video-height.`
  - `--seed-edit-model`: `with --seed-image: edit the seed into panel 1 with a Qwen registry edit model (qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-q4, qwen2511-bf16), prompted by panel 1's Image: text after Phase 1 and screened with content safety; as-is, like leaving the flag out, uses the seed unchanged. With --shots it is required and as-is is refused: every panel's still is an edit of the seed, each prompted by its own Image: text. See docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md and 2026-11-05-compose-shots-seed-edit-design.md.`
  - `--shots`: `shots mode: every panel is its own shot with its own Image: still and is rendered from that still (no chaining; cuts between panels). Phase 1 uses the shots story template and enforces the shot rules (one action per Motion:, at most two cast characters per shot), Phase 2 renders a still for every panel, and every cast character LoRA defaults to 0.8. With --seed-image, every panel's still is instead a Qwen edit of the seed (--seed-edit-model ID, required). See docs/superpowers/specs/2026-10-06-shots-mode-design.md.`
- **SE5.** The module docstring's "Shots mode" paragraph (`:89-98`) gains, after its last sentence (`… so that only they re-render.`), the sentence: ` With --seed-image (docs/superpowers/specs/2026-11-05-compose-shots-seed-edit-design.md), Phase 2 instead edits the seed into every panel's still with the Qwen model of --seed-edit-model (required), in one child, each panel prompted by its own Image: text, screened, recorded in seed_edits.json and reused on a rerun when nothing changed.`

### 3.4 Story prompt and phase sequence

- **SE6.** `build_story_prompt`'s seed branch condition (`:247`) becomes `if seed_image and not no_stills and not shots:`, with the comment line `# Shots seed edits SE6: the seed preface describes the chained flow; shots stories keep the shots template.` directly above the existing comment. In shots mode the prompt (written to `story_prompt.txt` by `_write_story_prompt`) is then the plain shots template; the robust engine still attaches the seed and `SEED_PARAGRAPH` itself. Every non-shots prompt is unchanged.
- **SE7.** In `_phase_sequence`, the condition at `:2840` becomes `if (getattr(args, "seed_edit", None) and phase2_stills in phases and not getattr(args, "shots", False)):` (body unchanged). Shots seed tuples are therefore the ordinary shots tuples: `(phase0_seed, phase1_story, phase_release_story_server, [phase_redo_shots,] phase2_stills, phase3_manifest, phase4_render)`; `--story-only` gives `(phase0_seed, phase1_story)`. Every non-shots tuple is unchanged.

### 3.5 Phase 2 in shots seed mode

- **SE8.** In `phase2_stills`, directly after `print("=== Phase 2: stills ===")` (`:2087`), add:

```python
    if getattr(args, "shots", False) and getattr(args, "seed_image", None):
        return _phase2_shots_seed(args)       # shots seed edits SE8: every still is a Qwen edit of the seed
```
  Nothing else in `phase2_stills` changes; `bin/ltx-story-images` is never run in shots seed mode.
- **SE9 - SE15.** The following functions are added, in this order, directly after `phase_seed_edit` (after `:2330`, before `_redo_moves`). The code is load-bearing; type it as written.

```python
def _shots_seed_paths(story_dir):
    """The shots seed edits' files in the story directory (shots seed edits spec SE9)."""
    return {"original": os.path.join(story_dir, "seed-original.png"),
            "record": os.path.join(story_dir, "seed_edits.json"),
            "work": os.path.join(story_dir, "seed_edits")}


def _sha256_file(path):
    """The sha256 hex digest of path's bytes (shots seed edits spec SE10)."""
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _shots_seed_prompts(story_md):
    """[(n, prompt)] for every panel of story.md (shots seed edits spec SE11): SHOTS_SEED_EDIT_PREFIX, then panel
    n's Image: text joined with the story's Style: text exactly as bin/ltx-story-images joins them. prompt is ""
    for a panel with no Image: text; [] when story.md has no panels."""
    panels = _load_story_panels(story_md)
    if not panels:
        return []
    images = importlib.machinery.SourceFileLoader(
        "ltx_story_images_for_movie", os.path.join(WS, "bin", "ltx-story-images")).load_module()
    style = images._style_text(panels)
    return [(n, SHOTS_SEED_EDIT_PREFIX + images._compose_prompt(p["image"], style) if p["image"].strip() else "")
            for n, p in enumerate(panels, start=1)]


def _shots_seed_entries(record_path):
    """{n: entry} of seed_edits.json (shots seed edits spec SE12), or {} when it is missing, unreadable or not
    this schema."""
    try:
        with open(record_path, encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError):
        return {}
    if not (isinstance(record, dict) and record.get("schema") == SHOTS_SEED_EDITS_SCHEMA
            and isinstance(record.get("panels"), list)):
        return {}
    return dict((e["n"], e) for e in record["panels"]
                if isinstance(e, dict) and isinstance(e.get("n"), int) and not isinstance(e.get("n"), bool))


def _write_shots_seed_record(path, entries, total):
    """seed_edits.json with the entries of panels 1..total in panel order, written atomically (SE12)."""
    _write_seed_edit_record(path, {"schema": SHOTS_SEED_EDITS_SCHEMA,
                                   "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                   "panels": [entries[n] for n in sorted(entries) if 1 <= n <= total]})


def _shots_seed_plan(args, qe):
    """Phase 2's shots seed-edit plan, read-only (shots seed edits spec SE13): (error, plan). error is the text of
    an Error: line or None; plan is {"prompts": [(n, prompt)], "size": (W, H), "still": (SW, SH), "keys": {n: key},
    "entries": {n: entry}, "reuse": [n], "todo": [n]}. A panel is reused iff it is not a --redo panel, its entry is
    ok with every key item equal, and images/panel_NN.png exists with the entry's still_sha256."""
    paths = _story_paths(args.story_id)
    files = _shots_seed_paths(paths["story_dir"])
    model_id, loras = args.seed_edit["qwen_model"], args.seed_edit["loras"]
    prompts = _shots_seed_prompts(paths["story_md"])
    if not prompts:
        return "%s has no panels to edit the seed into" % paths["story_md"], None
    for n, prompt in prompts:
        if not prompt:
            return "panel %d of %s has no Image: description to edit the seed with" % (n, paths["story_md"]), None
    size = _seed_edit_size(args, qe.multiple(model_id))
    still = _still_size(args)
    source_sha256 = _sha256_file(args.seed_image)
    settings = qe.settings(model_id, loras)
    entries = _shots_seed_entries(files["record"])
    redo = set(getattr(args, "redo_panels", None) or [])
    keys, reuse, todo = {}, [], []
    for n, prompt in prompts:
        keys[n] = dict(settings, source_sha256=source_sha256, prompt=prompt, seed=args.image_seed,
                       width=size[0], height=size[1], still_width=still[0], still_height=still[1])
        entry = entries.get(n)
        path = os.path.join(paths["images_dir"], "panel_%02d.png" % n)
        if (n not in redo and isinstance(entry, dict) and entry.get("status") == "ok"
                and all(k in entry and entry[k] == v for k, v in keys[n].items())
                and os.path.isfile(path) and entry.get("still_sha256") == _sha256_file(path)):
            reuse.append(n)
        else:
            todo.append(n)
    return None, {"prompts": prompts, "size": size, "still": still, "keys": keys, "entries": entries,
                  "reuse": reuse, "todo": todo}


def _shots_seed_lora_note(args):
    """True when a Z-Image stills LoRA would have applied (shots seed edits spec SE14): a cast character or pinned
    location with a stills LoRA, or plan.json's catalog stills pick."""
    if any(m.stills_lora for m in getattr(args, "cast_members", None) or []):
        return True
    if any(pin.stills_lora for pin in getattr(args, "location_pins", None) or []):
        return True
    plan = _catalog_plan(args)
    return bool(plan and plan["loras"].get("stills"))


def _phase2_shots_seed(args):
    """Phase 2 in shots mode with a seed image (shots seed edits spec SE15): every panel's still is a Qwen edit of the
    original seed, prompted by SHOTS_SEED_EDIT_PREFIX and that panel's own Image: (and Style:) text, in one
    qwen_edit.run_jobs batch, screened with content safety, fitted into images/panel_NN.png at the still size and
    recorded per panel in seed_edits.json. Recorded edits of the same seed bytes, prompt, seed, sizes and settings
    are reused; every other panel's existing still is moved aside first. Returns 0 or 1; a blocked or failed panel
    fails the phase after the batch, with no fallback to the unedited seed or to Z-Image."""
    qe = _qwen_edit()
    paths = _story_paths(args.story_id)
    files = _shots_seed_paths(paths["story_dir"])
    model_id, loras = args.seed_edit["qwen_model"], args.seed_edit["loras"]
    label = qe.label(model_id)
    error, plan = _shots_seed_plan(args, qe)
    if error is not None:
        print("Error: %s" % error, file=sys.stderr)
        return 1
    if _shots_seed_lora_note(args):
        print(SHOTS_SEED_LORA_NOTE)
    entries, todo, total = plan["entries"], plan["todo"], len(plan["prompts"])
    if plan["reuse"]:
        print("seed edits: reusing the stills of panels %s (recorded edits of the same seed image, prompt, seed "
              "and settings)" % _panel_list(plan["reuse"]))
    if not todo:
        print("seed edits: every panel's still is a recorded edit of the same seed image, prompt, seed and "
              "settings; nothing to edit")
        return 0
    os.makedirs(paths["images_dir"], exist_ok=True)
    os.makedirs(files["work"], exist_ok=True)
    archive = os.path.join(paths["story_dir"], "redo", "%s-%d" % (
        time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid()), "images")
    for n in todo:
        still = os.path.join(paths["images_dir"], "panel_%02d.png" % n)
        if os.path.lexists(still):
            os.makedirs(archive, exist_ok=True)
            moved = os.path.join(archive, os.path.basename(still))
            os.replace(still, moved)
            print("seed edits: moved %s -> %s (not a recorded edit of this seed image, prompt, seed and settings)"
                  % (still, moved))
        for name in ("panel_%02d.png" % n, "panel_%02d.pending.png" % n):
            if os.path.lexists(os.path.join(files["work"], name)):
                os.remove(os.path.join(files["work"], name))
        entries.pop(n, None)
    _write_shots_seed_record(files["record"], entries, total)
    fit = _image_fit()
    fit.load_oriented_rgb(args.seed_image).save(files["original"], format="PNG")
    (width, height), (still_w, still_h) = plan["size"], plan["still"]
    prompts = dict(plan["prompts"])
    print("seed edits: %s; %dx%d, fitted into %dx%d stills; seed %d; panels %s of %d, each prompted by its own "
          "Image: text" % (qe.generator_text(model_id, loras), width, height, still_w, still_h, args.image_seed,
                           _panel_list(todo), total))

    def record_entry(n, status, seconds, error_text):
        key = plan["keys"][n]
        ok = status == "ok"
        return {"n": n, "status": status, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "label": label, "source": os.path.abspath(args.seed_image), "source_sha256": key["source_sha256"],
                "original": os.path.basename(files["original"]), "prompt": key["prompt"], "seed": key["seed"],
                "width": key["width"], "height": key["height"], "still_width": key["still_width"],
                "still_height": key["still_height"], "qwen_model": key["qwen_model"], "loras": key["loras"],
                "steps": key["steps"], "scheduler": key["scheduler"],
                "output": "seed_edits/panel_%02d.png" % n if ok else None,
                "still": "images/panel_%02d.png" % n if ok else None,
                "still_sha256": (_sha256_file(os.path.join(paths["images_dir"], "panel_%02d.png" % n))
                                 if ok else None),
                "seconds": seconds, "error": error_text}

    def on_result(result):
        n = result["n"]
        if result["status"] == "ok":
            still = os.path.join(paths["images_dir"], "panel_%02d.png" % n)
            fit.fit_letterbox(fit.load_oriented_rgb(result["output_path"]), still_w, still_h).save(
                still + ".tmp", format="PNG")
            os.replace(still + ".tmp", still)
            print("panel %d -> %s (Qwen edit of the seed, %.1fs)" % (n, still, result["seconds"]))
        else:
            print("panel %d BLOCKED: the content screen blocked the Qwen edit of the seed" % n)
        entries[n] = record_entry(n, result["status"], result["seconds"], None)
        _write_shots_seed_record(files["record"], entries, total)

    jobs = [{"n": n, "seed": args.image_seed, "prompt": prompts[n], "source": files["original"],
             "stage_path": os.path.join(files["work"], "panel_%02d.pending.png" % n),
             "output_path": os.path.join(files["work"], "panel_%02d.png" % n)} for n in todo]
    try:
        qe.wait_for_memory(qe.memory_floor(model_id), label, tag="ltx-movie")
        results, failure = qe.run_jobs(model_id, loras, jobs, width, height, SHOTS_SEED_EDIT_SKILL, files["work"],
                                       on_result=on_result, noun="panel")
    except qe.Unavailable as e:
        results, failure = None, str(e)
    status = dict((r["n"], r["status"]) for r in results or [])
    ok = [n for n in todo if status.get(n) == "ok"]
    blocked = [n for n in todo if status.get(n) == "blocked"]
    failed = [n for n in todo if n not in ok and n not in blocked]
    if failed and failure is None:
        failure = "%s reported no result for panels %s" % (label, _panel_list(failed))
    if failed:
        for n in failed:
            entries[n] = record_entry(n, "failed", None, failure)
        _write_shots_seed_record(files["record"], entries, total)
    if failure is not None:
        print("Error: the seed edits failed: %s (kept: %s; edited on the next run: %s)"
              % (failure, _panel_list(sorted(plan["reuse"] + ok)) or "none", _panel_list(sorted(failed + blocked))),
              file=sys.stderr)
    if blocked:
        print("Error: the content screen blocked the Qwen edit of the seed (%s) for panels %s of story %s; the movie "
              "stops here rather than use an unscreened, unedited or text-rendered still. Change those panels' Image: "
              "lines in %s, then rerun: every other panel's recorded still is reused"
              % (label, _panel_list(blocked), args.story_id, paths["story_md"]), file=sys.stderr)
    if failure is not None or blocked:
        return 1
    print("seed edits: %d panel stills written" % len(ok))
    return 0
```

Binding notes on the code above:

- **SE9 Files.** `<story>/seed-original.png` (the EXIF-oriented seed as PNG, the edit source; the same name and content as chained mode's, [QE] QE45); `<story>/seed_edits.json` (the record); `<story>/seed_edits/` (the work directory: `mflux_spec.json` or `qwenedit_spec.json` and `qwenedit_report.json` written by `run_jobs`, `panel_NN.pending.png` stages, `panel_NN.png` raw edits at the edit size, kept for inspection); `<story>/images/panel_NN.png` (the stills Phases 3-4 use); `<story>/redo/<stamp>-<pid>/images/panel_NN.png` (stale stills moved aside). The file the user passed is never modified. `images/images.json` is not written (it has no reader; an older one stays as it is).
- **SE11 Prompt.** Exactly `SHOTS_SEED_EDIT_PREFIX + _compose_prompt(Image:, Style:)`; no trigger word of any kind is inserted (Section 1 item 2). Prompts travel in the spec JSON file, never in argv (as [QE] §14).
- **SE12 Record.** `seed_edits.json` is `{"schema": "ltx-movie.seed-edits.v1", "updated": "<UTC %Y-%m-%dT%H:%M:%SZ>", "panels": [entry, …]}` in panel order, and each entry has exactly these keys in this order: `n`, `status` (`ok` / `blocked` / `failed`), `created`, `label`, `source` (absolute `--seed-image` path), `source_sha256`, `original` (`seed-original.png`), `prompt`, `seed`, `width`, `height` (edit size), `still_width`, `still_height`, `qwen_model`, `loras`, `steps`, `scheduler` (the settings block), `output` (`seed_edits/panel_NN.png` when ok, else `null`), `still` (`images/panel_NN.png` when ok, else `null`), `still_sha256` (when ok, else `null`), `seconds` (the child's float, `null` for failed), `error` (the failure text for failed, else `null`). Paths in entries are relative to the story directory, so a batch fork's copy stays valid. Entries of panels above the story's panel count are dropped on every write.
- **SE13 Seed and key.** Every panel's seed is `--image-seed` (default 0), pinned like shots mode's Z-Image stills ([SHOTS] 5.10) **[spec choice]**, so a `--redo` of an unchanged panel reproduces it (Open question 2). The reuse key is the settings block plus `source_sha256` (of the `--seed-image` file's bytes), `prompt`, `seed`, `width`, `height`, `still_width`, `still_height`.
- **SE14 LoRA note.** `SHOTS_SEED_LORA_NOTE` is printed once, before any other Phase 2 line except the header, when SE14's function is true; nothing is refused for it.
- **SE15 Output lines.** None of the new lines matches the movie-ui render progress patterns (`^panel (\d+) ok: `, `^panel (\d+): reusing `, `^panel (\d+) FAILED \(`, `^=== panel (\d+)/(\d+) \(`, `movie_ui_lib.py:2256-2261`), so the render panel table is not polluted; the stills counter (`images/panel_NN.png` count against the panel count) shows Phase 2 progress. The temporary file `panel_NN.png.tmp` does not match `STILL_NAME_RE`.

### 3.6 Failure semantics

- **SE16. Interruption.** Before the child starts, the todo panels' entries are removed and their stills moved aside, and the record is written; each result's entry is written only after its still is in place (`ok`) or its block is known. A Ctrl-C (`KeyboardInterrupt`), a movie-ui cancel (`cancel_tree` SIGTERMs every descendant group, including the child's session) or an exception in `on_result` kills the child through `qwen_edit.run_child`'s `finally` and leaves `ok` entries only for finished stills; the next run reuses them and edits the rest.
- **SE17. Blocked, failed, unavailable.** The batch runs to its end; then: any failure (child exit, timeout, missing result, or `qwen_edit.Unavailable` from the memory wait or the install check) prints the failure line; any blocked panel prints the blocked line; either returns 1, so the movie stops before Phase 3. A failure caught as `Unavailable` marks every todo panel `failed` with that text. There is no fallback. A rerun of an unchanged blocked panel reproduces the block (pinned seed), as the blocked text says.
- **SE18. Sizes.** Edit size `_seed_edit_size(args, qe.multiple(model_id))` (the video size; unchanged by the floor since the geometry is a multiple of 64); still size `_still_size(args)`; fitted with `ltx_image_fit.fit_letterbox`; the aspects are equal, so no bar is added.

### 3.7 Dry run

- **SE19.** New function, directly after `_print_shots_stills_plan` (after `:2646`):

```python
def _print_shots_seed_plan(args):
    """Phase 2's dry-run lines in shots mode with a seed image (shots seed edits spec SE19). Reads; never writes."""
    qe = _qwen_edit()
    paths = _story_paths(args.story_id)
    model_id, loras = args.seed_edit["qwen_model"], args.seed_edit["loras"]
    known = isinstance(args.video_width, int)
    size = "%dx%d" % _seed_edit_size(args, qe.multiple(model_id)) if known else "<W>x<H>"
    still = "%dx%d" % _still_size(args) if known else "<2W>x<2H>"
    print("Would edit the seed into every panel's still with %s at %s, seed %d, in one Qwen child: each panel is "
          "prompted by the shots seed-edit instruction and its own Image: text (and the Style: text) from story.md, "
          "screened with content safety (skill %s), fitted (never cropped) into %s at %s and recorded in %s. "
          "Z-Image and stills LoRAs are not used. A blocked or failed panel stops the run after the batch; a rerun "
          "reuses every recorded edit."
          % (qe.generator_text(model_id, loras), size, args.image_seed, SHOTS_SEED_EDIT_SKILL,
             os.path.join(paths["images_dir"], "panel_NN.png"), still,
             _shots_seed_paths(paths["story_dir"])["record"]))
    if args.force_story or not known or not os.path.exists(paths["story_md"]):
        print("Panels: decided at Phase 2, from story.md after Phase 1")
        return
    error, plan = _shots_seed_plan(args, qe)
    if error is not None:
        print("Panels: Phase 2 would stop: %s" % error)
        return
    print("Panels to edit: %s; reused: %s"
          % (_panel_list(plan["todo"]) or "none", _panel_list(plan["reuse"]) or "none"))
```
  In `_print_dry_run_plan`, the line `if args.no_stills:` (`:2745`) becomes `elif args.no_stills:` preceded by exactly:

```python
    if getattr(args, "shots", False) and getattr(args, "seed_image", None):
        print("--- Phase 2: stills ---")
        _print_shots_seed_plan(args)
        print()
```
  Everything inside the existing no-stills and stills branches is unchanged. The dry run reads no weights (`selection_problem` is not called, SE3) and writes nothing.
- **SE20.** In `_print_dry_run_plan`:
  - The Phase 0 print (`:2702-2707`) becomes:
    ```python
        print("Would validate %s (readable image, every edge >= %dpx, aspect 1:3 to 3:1), "
              "derive the video geometry from it, and write a scaled story-model copy "
              "(long edge %dpx) to %s. %s"
              % (args.seed_image, SEED_MIN_EDGE, SEED_DOWNSCALE_MAX_EDGE, paths["seed_downscaled"],
                 "Phase 2 edits the ORIGINAL into every panel's still with the Qwen edit model; nothing is cropped."
                 if getattr(args, "shots", False) else
                 "Phase 2 fits the ORIGINAL into panel_01.png at twice the video size; nothing is cropped."))
    ```
    (byte-identical output for every non-shots run).
  - The Phase 1c block condition (`:2731`) becomes `if getattr(args, "seed_edit", None) and not getattr(args, "shots", False):`.

### 3.8 Unchanged downstream and packaging

- **SE21.** Phase 3 and Phase 4 are unchanged: the `--shots` manifest conditions every panel on its own `images/panel_NN.png`; `--resume` re-renders exactly the clips whose still bytes changed (`image_sha256` provenance). Phase 1b is unchanged.
- **SE22.** The deploy package (`scripts/deploy/build_pkg.py`, unchanged) ships `bin/ltx-movie` but not `qwen_edit.py`: there `--shots --seed-image` without a model gets the SE2 text and with a model QE43 row 6 (`--seed-edit-model needs <WS>/qwen_edit.py, which this workspace does not have`).

---

## 4. movie-ui (SE23-SE34)

- **SE23. V1 rule 8.** In `validate_fields` (`movie_ui_lib.py:1559-1565`), the branch `elif seed is not None and mode == "shots": errors.append("a seed image cannot be used with shots mode")` is replaced by:

```python
    elif seed is not None and mode == "shots":
        # Shots seed edits SE23: every panel's still is a Qwen edit of the seed.
        if fields.get("seed_edit_model") in (None, "as-is"):
            errors.append("a seed image in shots mode needs a Qwen edit model: every panel's still is an edit of "
                          "the seed, so the seed cannot be used as-is")
        if fields.get("story_legacy") is True:
            errors.append("a seed image in shots mode needs the default story engine; it cannot be combined with "
                          "--story-legacy")
        if isinstance(fields.get("stills_loras"), list) and fields["stills_loras"]:
            errors.append("stills LoRAs do not apply in shots mode with a seed image: every panel's still is a "
                          "Qwen edit of the seed")
```
  The seed-folder path gets the same rule per row (rows set `seed_upload` and run V1). Rule 12d and rule 18 are unchanged.
- **SE24. Argv.** `build_argv` is unchanged: with a seed and a model it already emits `--seed-image <upload> --seed-edit-model ID [--seed-edit-lora ID=S …]` before `--model`, and `--shots` later (`:1027-1048`).
- **SE25. 409.** In `_h_job_create` (`movie_ui_server.py:849`), `fields["action"] == "movie"` becomes `fields["action"] in ("movie", "redo")`. A redo of a shots seed story re-edits its redo panels, so its selection is probed before queueing (redo needs shots mode, V1 rule 16, so this never applies to chained). `_h_seed_folder` is unchanged (seed-folder jobs are never `redo`). The 409 texts are QE57's.
- **SE26. Phases.** `job_phases` (`movie_ui_lib.py:2295-2296`) becomes:
    ```python
    edit = (["1c"] if kind == "movie" and fields.get("seed_upload") and fields.get("mode") != "shots"
            and fields.get("seed_edit_model") not in (None, "as-is") else [])
    ```
  Shots seed jobs: `["0", "1", "1b", "2", "3", "4"]`, and `["0", "1", "1b", "redo", "2", "3", "4"]` for `redo`. Chained results unchanged.
- **SE27. Batch copy.** `COPY_FILES["render"]` (`movie_ui_batch.py:51-52`) becomes `("story.md", "plan.json", "story_checks.json", "story_prompt.txt", "catalog_loras.json", "manifest.json", "seed_edits.json")`; `stills` and `replan` unchanged. A render fork of a shots seed story then reuses every still (same upload bytes, same prompts, copied stills and record). `FIELD_LEVELS`, `GROUPS` and `merge` are unchanged.
- **SE28. Flags.** `FIELD_FLAGS` is unchanged (31 entries); `supported.seed_edit` gates the picker as today (Section 1 item 5).
- **SE29. `index.html`.** In the Compose `c-sq` block (`:92`, `:95`):
  - `<label>Panel 1 from the seed <select id="c-sq-qwen-model"></select></label>` becomes `<label><span id="c-sq-label">Panel 1 from the seed</span> <select id="c-sq-qwen-model"></select></label>`.
  - Directly after `<p id="c-sq-qwen-note" class="muted"></p>` add (same indentation): `<p id="c-sq-shots-note" class="muted" hidden>Every panel's still is a Qwen edit of the seed, prompted by that panel's own Image: text. Z-Image is not used: stills LoRAs, and the stills LoRAs of characters and locations, do not apply (characters and locations still shape the story and the video).</p>`
- **SE30. `composeSeedEditActive`** (`app.js:413-417`) becomes exactly:

```js
  function composeSeedEditActive() {
    const supported = (S.options && S.options.supported) || {};
    const mode = $("#c-mode").value;
    return supported.seed_edit !== false && (mode === "chained" || mode === "shots")
      && (($("#c-res-seed").checked && Boolean(S.seedUpload)) || $("#c-res-folder").checked);
  }
```
  `composeFields`, `composeSeedDefault`, `fillCompose` and `qwenPicker` are unchanged; `composeFields` therefore sends the picker's selection in shots mode too.
- **SE31. `updateComposeButtons`.** The two lines `const seedEditOn = composeSeedEditActive();` and `show($("#c-sq-qwen-box"), seedEditOn);` (`:546-547`) become exactly:

```js
    const seedEditOn = composeSeedEditActive();
    // Shots seed edits spec SE31: in shots mode every panel is an edit of the seed, so "Seed as-is" is not offered.
    const shotsSeed = seedEditOn && mode === "shots";
    if (shotsSeed && COMPOSE_PICKER.state && COMPOSE_PICKER.state.model === "as-is") {
      COMPOSE_PICKER.select(null, null);
      COMPOSE_PICKER.update();
    }
    const asIsOption = $("#c-sq-qwen-model").options[0];
    if (asIsOption && asIsOption.value === "as-is") {
      asIsOption.disabled = shotsSeed;
      asIsOption.textContent = shotsSeed ? "Seed as-is (no edit) — chained mode only" : "Seed as-is (no edit)";
    }
    $("#c-sq-label").textContent = mode === "shots" ? "Every panel from the seed" : "Panel 1 from the seed";
    show($("#c-sq-shots-note"), shotsSeed);
    show($("#c-sq-qwen-box"), seedEditOn);
```
  (`COMPOSE_PICKER.update()` directly above stays.) Behaviour: a Seeds-tab "Use" seed or a loaded job with as-is shows `Qwen-Image-2.1 q4` + Uncensored at 1 once the mode is shots; switching back to chained keeps the chosen model (as-is is selectable again). `setupCompose`'s panel-wide `change` listener already runs `updateComposeButtons(); preview();` on a mode change.
- **SE32.** All new page text goes in through markup or `textContent`; the page bans (`https?://`, `\son[a-z]+=`, `style=`, `alert(`, `confirm(`, `prompt(`, `eval(`, `new Function`) still hold.
- **SE33. `NEW_PY`.** `tests/test_movie_ui_builder.py` `NEW_PY` gains, after `"tests/test_movie_ui_qwen_edit.py"`, the entries `"tests/test_ltx_movie_shots_seed.py"`, `"tests/test_movie_ui_shots_seed.py"` (in the tests commit).
- **SE34. Unchanged.** VLM policy (`job_vlm`), `stills_needed` (V2 still probes Z-Image in shots seed mode), the seams job (chained only), `_fields_body` (it already cleans a named selection in any mode).

---

## 5. Errors and messages

| Condition | Where | Text | Effect |
|---|---|---|---|
| `--shots --seed-image` with `--story-legacy` / `--story-prompt-override` | `bin/ltx-movie` `_resolve_shots` | `Error: --shots with --seed-image needs the default story engine; it cannot be combined with --story-legacy` (or `… --story-prompt-override`) | exit 2, before any phase |
| `--shots --seed-image` without a model, or `as-is` | same | `Error: --shots with --seed-image needs --seed-edit-model ID: every panel's still is a Qwen edit of the seed, so the seed cannot be used as-is` | exit 2 |
| `--shots --seed-image --stills-lora …` | same | `Error: --stills-lora cannot be combined with --shots and --seed-image: every panel's still is a Qwen edit of the seed, and Z-Image stills LoRAs do not apply to it` | exit 2 |
| model rules | `_resolve_seed_edit` | QE43 rows 6-9, unchanged | exit 2 |
| story.md has no panels | Phase 2 | `Error: <story.md> has no panels to edit the seed into` | exit 1, nothing written |
| a panel without `Image:` | Phase 2 | `Error: panel <n> of <story.md> has no Image: description to edit the seed with` | exit 1, nothing written |
| child failure, timeout, missing result, memory wait, install check | Phase 2 | `Error: the seed edits failed: <failure> (kept: <panels or none>; edited on the next run: <panels>)` | exit 1; failed entries recorded |
| any blocked panel | Phase 2 | `Error: the content screen blocked the Qwen edit of the seed (<label>) for panels <list> of story <id>; the movie stops here rather than use an unscreened, unedited or text-rendered still. Change those panels' Image: lines in <story.md>, then rerun: every other panel's recorded still is reused` | exit 1; blocked entries recorded |
| info | Phase 2 | `seed edits: reusing the stills of panels <list> (recorded edits of the same seed image, prompt, seed and settings)`; `seed edits: every panel's still is a recorded edit of the same seed image, prompt, seed and settings; nothing to edit`; `seed edits: moved <src> -> <dst> (not a recorded edit of this seed image, prompt, seed and settings)`; `seed edits: <generator_text>; <W>x<H>, fitted into <SW>x<SH> stills; seed <s>; panels <list> of <N>, each prompted by its own Image: text`; `panel <n> -> <still> (Qwen edit of the seed, <s>s)`; `panel <n> BLOCKED: the content screen blocked the Qwen edit of the seed`; `seed edits: <k> panel stills written`; `SHOTS_SEED_LORA_NOTE` | stdout |
| V1 rule 8 | movie-ui | the three SE23 texts | V1 fail (preview errors; 409 `validation failed`; seed-folder row refused) |
| selection unavailable | `/api/jobs` (`movie`, `redo`), `/api/jobs/seed-folder` | QE57 409 texts | nothing queued |
| PR #10-era workspace | V6 | the old CLI text `Error: --shots is not supported with --seed-image: …` in the dry-run detail | 409 `validation failed` |

---

## 6. Tests

### 6.1 Rules

- [QE] §11.1 holds: no real model, no real HOME, no server other than the in-test `127.0.0.1` one, no port 8177/8178, no render, no download. Every test sets `HOME`, `HF_HOME`, `Z_IMAGE_HF_HOME` under `tmp_path` and removes `HF_HUB_CACHE` and every `SEED_EDIT_*` variable.
- Both new files load `bin/ltx-movie` with `SourceFileLoader` + `spec_from_loader` + `module_from_spec` + `exec_module` (never `load_module(`), no `urllib`, and are listed in `NEW_PY` (SE33).
- `tests/test_ltx_movie_shots_seed.py` patches `movie._story_dir` to `<tmp>/stories/<id>` and `movie._qwen_edit` to either the multi-job fake below or (SET15 only) the test's imported `qwen_edit` module — never the real `_qwen_edit()` loader (it re-executes `qwen_edit.py` and would undo the test's patches).
- **The multi-job fake** `_FakeShotsQwenEdit`: the real `MODEL_IDS`, `SelectionError`, `Unavailable`, `cli_selection`, `settings`, `label`, `multiple`, `memory_floor`, `generator_text` of `qwen_edit`; recorders for `selection_problem`, `wait_for_memory` (raises `self.wait_error` when set) and `run_jobs`. `run_jobs` records `{"model_id", "loras", "jobs", "size", "skill", "work_dir", "noun"}`; then for each job in order with `outcome = self.outcomes.get(n, "ok")`: `"ok"` → write a `(width, height)` RGB PNG of colour `(0, 0, 40 * n)` at `output_path`, call `on_result({"n", "output_path", "status": "ok", "seconds": 12.5})`; `"blocked"` → `on_result(… "blocked" …)` with no file; `"stop"` → stop processing jobs (the remaining jobs and this one are `failed`); after `on_result` of the job numbered `self.interrupt_after`, raise `KeyboardInterrupt`. It returns `(results, self.failure)` with results in job order (`failed` with `seconds None` for unprocessed jobs).
- Story fixture `SHOTS_STORY`: a shots story.md with a title, a summary, `## Characters` (one line), and three panels each with `Image:`, `Motion:`, `Narration:`, panel 1 also with `Style:`; `IMAGES = [...]`, `STYLE = "..."` constants so the expected prompts are `PREFIX + IMAGES[n-1] + " " + STYLE`.
- Phase args: `argparse.Namespace(story_id="s1", seed_image=<tmp>/seed.jpg (the QET28 EXIF-6 JPEG helper), video_width=704, video_height=448, image_seed=3, seed_edit={"qwen_model": "qwen21-q4", "loras": UNC}, shots=True, redo_panels=[], cast_members=[], location_pins=[], story_engine="robust", no_auto_lora=True, panels=3, force_story=False, global_stills_loras=[], stills_lora_path=None)` (SET4's no-seed case uses the same with `seed_image=None`). SET15 also patches `movie._story_dir` and writes `SHOTS_STORY`.

### 6.2 New tests

`tests/test_ltx_movie_shots_seed.py`:

| ID | Covers | Test |
|---|---|---|
| SET1 | SE2 | `movie._resolve_shots(build_parser().parse_args([...]))` with `--shots --seed-image <png>` and: no model; `--seed-edit-model as-is`; `--seed-edit-model qwen21-q4 --story-legacy`; `--seed-edit-model qwen21-q4 --story-prompt-override <file>`; `--seed-edit-model qwen21-q4 --stills-lora <file>` → each returns 2 and stderr is exactly the Section 5 text; `--seed-edit-model qwen21-q4` → returns 0 (and `--redo 2` with an existing story.md → 0 with `redo_panels == [2]`) |
| SET2 | SE6 | `build_story_prompt("N", "sid", 3, False, True, seconds="6", shots=True) == build_story_prompt("N", "sid", 3, seconds="6", shots=True)`; the chained seed prompt still starts with `SEED_IMAGE_PREFACE` and ends with `SEED_IMAGE_POSTFACE` |
| SET3 | SE7, SEK3 | `_phase_sequence` names: shots seed with `seed_edit` and the release → `(phase0_seed, phase1_story, phase_release_story_server, phase2_stills, phase3_manifest, phase4_render)`; plus `redo_panels=[2]` → `phase_redo_shots` before `phase2_stills`; `story_only` → `(phase0_seed, phase1_story)`; the same args with `shots=False` still contain `phase_seed_edit` before `phase2_stills` |
| SET4 | SE8, SEK3 | `phase2_stills` with shots seed args: `_phase2_shots_seed` (patched recorder returning 0) called once; `subprocess.run`, `_stream_and_tee` and `_phase2_shots` never called. Shots without a seed: `_phase2_shots` called once with a command containing no `--seed-image` |
| SET5 | SE9-SE13, SE15, SE18, SEK4 | fake all ok: one `run_jobs` call with `noun "panel"`, skill `ltx_movie_shots_seed_edit`, size `(704, 448)`, work `<story>/seed_edits`, jobs exactly `[{"n": n, "seed": 3, "prompt": PREFIX + IMAGES[n-1] + " " + STYLE, "source": <story>/seed-original.png, "stage_path": <story>/seed_edits/panel_0n.pending.png, "output_path": <story>/seed_edits/panel_0n.png} for n in 1..3]`; `wait_for_memory` saw `(20.0, "Qwen-Image-2.1 q4", "ltx-movie")`; `seed-original.png` is 100×200 (oriented); `images/panel_0n.png` exist at 1408×896; `seed_edits.json` has the schema, three entries with exactly the SE12 keys in order, status ok, `still_sha256` equal to each file's sha256, `output`/`still` relative paths; stdout has the plan line and three `panel n -> … (Qwen edit of the seed, 12.5s)` lines and `seed edits: 3 panel stills written`; return 0 |
| SET6 | SE17, SEK5 | `outcomes {2: "blocked"}` → return 1; stderr is exactly the blocked text for panels `2`; entries ok/blocked/ok (blocked: `output`, `still`, `still_sha256` null, `seconds` 12.5); `images/panel_02.png` absent, 1 and 3 present |
| SET7 | SE16, SE17, SEK6 | `outcomes {2: "stop"}`, `failure "Qwen-Image-2.1 q4 child exited 1: boom"` → return 1, stderr `Error: the seed edits failed: Qwen-Image-2.1 q4 child exited 1: boom (kept: 1; edited on the next run: 2,3)`; entries ok/failed/failed with that `error`; a second call with the fake reset to all ok → `run_jobs` jobs are panels 2 and 3 only, stdout has `seed edits: reusing the stills of panels 1 (…)` |
| SET8 | SE16, SEK6 | a first all-ok run; then panels 2 and 3's `Image:` text changes; then a run with `interrupt_after 2` raises `KeyboardInterrupt`; afterwards `seed_edits.json` has an ok entry for 1 (old) and 2 (new prompt) and NO entry for 3; the old `panel_03.png` is under `<story>/redo/*/images/`; a third run edits only panel 3 |
| SET9 | SE13, SEK4 | after an all-ok run: an identical call makes no `run_jobs` and no `wait_for_memory` call and prints the nothing-to-edit line; then, one at a time from a fresh all-ok state: new seed bytes, `image_seed` 4, model `qwen21-q8`, LoRA scale 0.5 → every panel edited; panel 2's `Image:` edited → only 2, with the old still moved to `redo/<stamp>-<pid>/images/panel_02.png` and the move line printed; `panel_03.png` overwritten with other bytes → only 3; `redo_panels [1]` → only 1 |
| SET10 | SE17 | `wait_error = Unavailable("only 10.0 GiB available after waiting 0 s; Qwen-Image-2.1 q4 needs 20 GiB; free memory and retry")` → return 1, stderr `Error: the seed edits failed: only 10.0 GiB … retry (kept: none; edited on the next run: 1,2,3)`, three failed entries, no `run_jobs` call |
| SET11 | SE14 | a cast member object with `stills_lora="/x.safetensors"` → stdout contains `SHOTS_SEED_LORA_NOTE` once; with none → not at all |
| SET12 | SE13 | a story whose panel 2 has no `Image:` → return 1, stderr `Error: panel 2 of <story.md> has no Image: description to edit the seed with`; no `seed-original.png`, no `seed_edits.json`, no `run_jobs` call |
| SET13 | SE19, SE20 | `main([narrative, "--story-id", "s1", "--shots", "--seed-image", png, "--seed-edit-model", "qwen21-q4", "--dry-run", "--no-review", "--no-auto-lora"])` with the fake: rc 0; the Phase 0 text ends `Phase 2 edits the ORIGINAL into every panel's still with the Qwen edit model; nothing is cropped.`; no `--- Phase 1c: seed edit ---`; the Phase 2 block has the SE19 sentence and `Panels: decided at Phase 2, from story.md after Phase 1`; no `ltx-story-images` in the output; `selection_problem` never called. With story.md and a record making 1 and 3 reusable → `Panels to edit: 2; reused: 1,3` |
| SET14 | SEK3 | chained dry runs (`--seed-image`, then with `--seed-edit-model qwen21-q4`) still contain `Phase 2 fits the ORIGINAL into panel_01.png at twice the video size; nothing is cropped.` and (with the model) `--- Phase 1c: seed edit ---`; a shots dry run without a seed contains `Stills groups: computed from story.md after Phase 1` |
| SET15 | SE15, SEK4, SEK5 | integration: the real `qwen_edit` with `test_qwen_edit`'s `env` fixture and `_mflux_ready` (import them: `from test_qwen_edit import env, _mflux_ready  # noqa: F401`), the stub config `{"red": [2]}`, `movie._qwen_edit = lambda: qe`: `_phase2_shots_seed` returns 1; the stub's `calls.jsonl` has exactly one line whose spec jobs carry each panel's own prompt and `source == <story>/seed-original.png`; the fake screen saw exactly three calls, skill `ltx_movie_shots_seed_edit`, each with its job's prompt, size `(704, 448)`; stills 1 and 3 exist at 1408×896; 2 does not |

`tests/test_movie_ui_shots_seed.py` (reuse `tests/test_movie_ui_checks.py`'s V1 pattern with its own `env` fixture copy, and `tests/test_movie_ui_qwen_edit.py`'s server `env`, `_upload`, `_job`, `_compose`, `_probe` by import):

| ID | Covers | Test |
|---|---|---|
| SET16 | SE23 | `validate_fields` with `seed_upload` and `mode "shots"`: model `None` and `"as-is"` → exactly `["a seed image in shots mode needs a Qwen edit model: every panel's still is an edit of the seed, so the seed cannot be used as-is"]`; model `qwen21-q4` → `[]`; with `story_legacy True` → the story-engine text; with one stills LoRA item → the stills text; chained with a seed and no model → `[]` (unchanged) |
| SET17 | SE24, SE26 | `build_argv` for shots seed + `qwen21-q4` + uncensored: `--seed-image <upload> --seed-edit-model qwen21-q4 --seed-edit-lora uncensored=1.0` directly after `--frames`, and `--shots` present; `job_phases("movie", shots seed + model)` → `["0", "1", "1b", "2", "3", "4"]`; action `redo` → `["0", "1", "1b", "redo", "2", "3", "4"]`; chained unchanged (`["0", "1", "1b", "1c", "2", "3", "4"]`) |
| SET18 | SE25 | over HTTP: `/api/jobs` shots seed + `qwen21-q8` with the probe saying unavailable → 409 `Qwen-Image-2.1 q8 is unavailable: <reason>`, nothing queued; the same with action `redo` (story.md present, `redo [2]`) → 409; available → 201 and the job's argv has `--shots` and `--seed-edit-model qwen21-q8`; seed folder, mode shots, with a model → every row ok and 201 queued; without a model → every row refused with the SE23 text |
| SET19 | SE27 | `copy_plan(sdir, "render")` lists `seed_edits.json` when it exists; `"stills"` and `"replan"` do not |
| SET20 | SE29-SE32 | static page: `index.html` contains `<label><span id="c-sq-label">Panel 1 from the seed</span> <select id="c-sq-qwen-model"></select></label>` and the SE29 note line exactly, each id once, both inside `id="c-sq-qwen-box"`; `app.js`'s `composeSeedEditActive` body contains `(mode === "chained" || mode === "shots")`; `updateComposeButtons` contains the SE31 lines verbatim (from `const shotsSeed` through `show($("#c-sq-shots-note"), shotsSeed);`); the page bans; `node --check app.js` when `node` exists |
| SET21 | SE28 | `len(lib.FIELD_FLAGS) == 31` and no entry names a new flag |

The picker's behaviour in a browser is covered by Section 7.

### 6.3 Existing tests to change (tests commit; not `test_mut26`)

| Test | Exact edit |
|---|---|
| `tests/test_shots_mode.py` S33 (`:936-938`) | expected text → `Error: --shots with --seed-image needs --seed-edit-model ID: every panel's still is a Qwen edit of the seed, so the seed cannot be used as-is` |
| `tests/test_movie_ui_checks.py` MUT4 (`:76`) | expected text → `a seed image in shots mode needs a Qwen edit model: every panel's still is an edit of the seed, so the seed cannot be used as-is` |
| `tests/test_movie_ui_seedfolder.py` SDT17 (`:560`) | reason → the same SE23 text |
| `tests/test_movie_ui_builder.py` `NEW_PY` | SE33 |

No other existing test changes; a test that fails for any other reason is a defect in the implementation, not in the test.

---

## 7. Browser check (agent, before the merge; not pytest, not macstudio)

[QE] §11.4's throwaway demo under `$S/ssedemo/` (stub probe: `qwen21-q4`, `qwen2511-q4`, `uncensored` ok; `qwen21-q8` not installed; a stub `bin/ltx-movie --help` with the seed-edit flags). Pass when:
1. Compose, upload a seed, mode Shots: the picker shows, label `Every panel from the seed`, `Qwen-Image-2.1 q4` + Uncensored at 1, the shots note visible; the preview command has `--seed-edit-model qwen21-q4 --seed-edit-lora uncensored=1.0` and `--shots`.
2. Seeds → Use → Compose, mode Shots: the as-is option reads `Seed as-is (no edit) — chained mode only`, is disabled, and the selection is `Qwen-Image-2.1 q4` + Uncensored; mode Chained: the label is `Panel 1 from the seed`, as-is enabled, the note hidden.
3. Shots without a seed (Size): no picker; the command has no seed-edit flag.
4. Shots + seed + a stills LoRA row: the preview errors list the SE23 stills text.
5. The browser console shows no error.

---

## 8. Live checks on macstudio (run by the user; the agent has no access)

Preparation: check out `shots-seed-edit` on macstudio; `bin/seed-edit-setup --model qwen21-q4 --lora uncensored` (and `--model qwen2511-q4` for L4). Until a row is run it is recorded "not run (awaiting the user)".

| Row | Steps | Record | Pass |
|---|---|---|---|
| L1 | movie-ui Compose: upload a medium-shot photo of one person, mode Shots, panels 12, default picker (`qwen21-q4` + uncensored), a narrative that moves through at least three places, Run all | `seed_edits.json` (status and seconds per panel), Phase 2 wall clock from the job log, `seed-original.png` beside `images/panel_01..12.png`; per panel two yes/no judgements: same person as the seed? visibly a different shot from the seed? | SEK7 (≥ 10/12 same person), SEK8 (≥ 8/12 different shot), SEK9 (no timeout) |
| L2 | rerun L1's story with Overwrite ticked after cancelling the job in the movie-ui during Phase 2 once at least three stills exist (stills counter) | `seed_edits.json` right after the cancel; the rerun's `seed edits: reusing the stills of panels …` line and its plan line | finished panels reused (not re-edited); no unfinished panel had an ok entry after the cancel; the rerun's plan line lists exactly the rest |
| L3 | the Section 7 steps 1-4 on the real page | screenshots or notes | every step as described |
| L4 (optional) | L1's narrative and seed with `qwen2511-q4` (8 steps) | the same records | seconds per panel and the two judgements, for comparison with L1 |
| L5 | chained regression: [QE] L3(a) (chained, uploaded seed, default model) | `seed_edit.json`, Phase 1c in the log | Phase 1c runs and panel 1 is the edit, as before |

---

## 9. Pass bar, rollout and the pinned-file baseline

### 9.1 Gate

1. Snapshot `WS` (house rule): `tar czf $S/snapshot-pre-sse-bdeb3ae.tgz` excluding `generated/`.
2. `df -g` shows ≥ 20 GiB free on the disk holding `WS` (SEK10).
3. Record at `bdeb3ae`: `python3 -m pytest tests/ -q -rA` failures and counts, and the `python3 tests/test_ltx_movie_offline.py` line.
4. After the commits of 9.2: SEK1 and SEK2 against step 3's record.
5. The browser check (Section 7) passes; an Opus design review of the diff against this spec is clean.
6. L1-L3 and L5 pass once the user runs them; push and merge only on the user's go.

### 9.2 Commits (in order)

1. **Feature commit:** D1-D6 (`bin/ltx-movie` is the only pinned file). `test_mut26` fails from here until commit 3 (expected; precedent).
2. **Tests commit:** D7 (new tests, Section 6.3 edits, `NEW_PY`), never `test_mut26`.
3. **Baseline commit (test-only, D8):** only `tests/test_movie_ui_builder.py`'s `test_mut26`, per 9.3.

### 9.3 `test_mut26` re-baseline

1. After every commit that touches a `PIPELINE_FILES` member has landed, take `S = git rev-parse HEAD`; check `git diff --quiet S -- <PIPELINE_FILES>` (exit 0) and that `git diff --name-only bdeb3ae S -- <PIPELINE_FILES>` lists exactly `qwen-agent-workspace/bin/ltx-movie`.
2. Set `BASELINE = "<S>"` and extend the comment's last clause: `… then to d2cf22881a733bb49b97c4388b22466b589ec1f0 (qwen-edit-models: Phase 1c clears the old record before an edit), then to <S> (shots seed edits).` (the final period moves to after the new clause). Nothing else in the file changes in this commit.
3. Commit with only that file staged. A later fix to a pinned file gets a new test-only baseline commit the same way (never amend).
4. `scripts/deploy/build_pkg.py` needs no change: it records `bin/ltx-movie`'s sha256 at build time and requires it committed and clean, but pins no fixed content ([QE] §0.1, re-checked: `build_pkg.py:384` lists it; `tests/test_deploy_pkg.py:1264` compares against the file's own sha256).

---

## 10. What stays unchanged

- Chained mode: Phase 1c, `seed_edit.json`, its reuse rule, the Phase 2 `--seed-image` substitution, the dry-run Phase 0 text and Phase 1c block (SEK3).
- Shots mode without a seed: Z-Image stills per stills-LoRA group through `bin/ltx-story-images`, existence-only reuse, the dry-run group lines.
- `bin/ltx-story-images`, `story_engine.py`, `qwen_edit.py`, `seed_edit_mflux_child.py`, `content_safety.py`, the registry and its defaults (`qwen21-q4` + `uncensored` @ 1.0), the memory floors, `child_timeout`.
- Phase 3, Phase 4, `--resume` provenance, Phase 1b and the movie-ui VLM policy.
- `FIELD_FLAGS`, `DEFAULT_FIELDS`, `build_argv`, `FIELD_LEVELS`, `GROUPS`, `merge`, the batch page.
- Seeds, Locations and Characters tabs and tools.

---

## 11. Amended requirements of earlier specs

| Item | Status |
|---|---|
| [SHOTS] 0.x/E-S2 and 5.1 (`--shots` with `--seed-image` refused) | amended by SE2 (allowed with `--seed-edit-model ID`, refused otherwise with the new texts) |
| [SHOTS] 5.5 (Phase 2 = one `bin/ltx-story-images` run per stills-LoRA group) | not in shots seed mode (SE8) |
| seed-image prompt preface ([2026-09-12] seed image spec, `build_story_prompt`) | amended by SE6 (not in shots mode) |
| [QE] §0.3 "A Qwen edit of … shots-mode panels" (out of scope) and §16 item 2 | superseded by this spec for shots mode |
| [QE] QE44 (Phase 1c insertion), QE50 (dry-run Phase 1c block, Phase 0 text) | amended by SE7, SE20 (not in shots mode) |
| [QE] QE57 (409 for action `movie`), QE67 (`composeSeedEditActive` chained only), QE69 (`job_phases` 1c) | amended by SE25, SE30, SE26 |
| [MU] V1 rule 8 (`a seed image cannot be used with shots mode`) | amended by SE23 |
| [SD] SDT17 (refusal text) | amended by Section 6.3 |
| [BF] BF16 (`COPY_FILES`) | amended by SE27 |

---

## 12. Open risks

1. **Every panel may look like the seed.** Edit models tend to keep the source's pose and framing; the prefix and the shot-specific `Image:` text are the only levers here, and neither is measured (L1/SEK8). Levers after L1: prefix wording, per-panel seeds, the LoRA strength (Open questions 1-2).
2. **Characters not in the seed** are invented from text on every panel with no stills LoRA to anchor them, so they can differ between panels.
3. **A cast library character that is not the seed's person** gets a description that disagrees with the source; the edit blends them. Guidance: use a seed that shows the cast character.
4. **Run time.** 12 panels at 40 steps (`qwen21-q4`) is unmeasured on macstudio; the child timeout is 7200 s. A timeout keeps the finished panels (SE16), so a rerun continues, but a single slow host may need several reruns (Open question 5).
5. **Prompt length.** Prefix + `Image:` (80-170 words) + `Style:` is about 150-260 words; the Qwen text encoder's limit in mflux was not verified (a truncation would cut the end of `Style:` first).
6. **Detail.** Stills are 2× upscales of video-size edits; Z-Image shots stills are native 2× renders (Open question 4).
7. **Content screen.** One blocked panel stops the movie by design; with the pinned seed an unchanged rerun reproduces the block.
8. **PR #10-era workspace** selected in the movie-ui: the picker shows in shots mode and the job is refused only at V6 with the old CLI text.
9. **Chained render-level forks re-run Phase 1c** (existing behaviour: `seed_edit.json`/`seed-edited.png` are not in `COPY_FILES`); observed, not changed here.
10. **V2 "stills"** still requires the Z-Image dependencies in shots seed mode, where Phase 2 does not use them.
11. A stale `images/images.json` from an earlier Z-Image run of the same story stays in `images/` (no reader).
12. The seed's aspect vs the video geometry (residual pad): how mflux resizes a source whose aspect differs slightly from W × H is unverified (as in PR #10).

## 13. Open questions (for after the live checks)

1. After L1: does the prefix keep identity and change the shot well enough, or should it be reworded (a constant change)?
2. After L1: pinned `--image-seed` for every panel (this spec) or `--image-seed + n`?
3. After L1: should panels that show no seed person be rendered by Z-Image (with their character stills LoRA) instead of edited?
4. After L1: edit at the video size (this spec, as [QE]) or at the still size?
5. After L1/L4: is `JOB_TIMEOUT_S = 600` enough per panel for `qwen21-q4` at 40 steps?
6. Should chained render forks copy `seed_edit.json` and `seed-edited.png` (Section 12 item 9)?
7. Should V2 skip the Z-Image probe in shots seed mode (Section 12 item 10)?
