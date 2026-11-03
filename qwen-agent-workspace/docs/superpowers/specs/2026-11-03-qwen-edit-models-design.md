# Qwen edit models for Locations, Characters and Compose seed panel 1: one shared edit runner, the Seeds registry everywhere an image is edited

Date: 2026-11-03

Status: design spec. The user approved the design (scratchpad `qem-design-notes.md`, Sections 1-3) on 2026-11-02/03. This document carries that design without reopening it. Each detail the notes leave open is decided here and marked **[spec choice]**; Section 15 lists them all. Section 16 lists the points where the notes and the code disagree, with a recommendation; no design was changed silently. The implementer makes no design decisions.

Repository `/Users/reubenpatterson/local_agent_harness`. Worktree `$S/qem-wt`, branch `qwen-edit-models` off `qwen-agent-redteam` at `a62d477` (the merge of PR #9, seed models). `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`. `WS` is `qwen-agent-workspace/`. Every path is relative to `WS`; every line number cites `a62d477`.

Builds on **[SQ]** `docs/superpowers/specs/2026-11-02-seed-models-design.md` (including its §14a), **[SG]** `2026-11-02-seed-generator-design.md`, **[LOC]** `2026-10-29-location-lora-design.md`, **[LY]** `2026-11-02-location-yield-design.md` and **[CSE]** `2026-10-21-character-seed-edit-design.md`. Every requirement of those specs stays in force except where this spec names it as amended (Section 13.4).

Requirement IDs are **QE1-QE70**, tests **QET1-QET39**, KPIs **QEK1-QEK9**, live checks **L1-L4**. A grep at `a62d477` found no spec, plan, test or source file using `QE<n>`, `QET<n>` or `QEK<n>`.

Terms (as [SQ]): a **registry model** is one `movie_ui_seedgen.QWEN_MODELS` entry; a **registry LoRA** one `QWEN_LORAS` entry; a **selection** is one registry model ID plus a list `[{"id", "scale"}]` of registry LoRAs of its family in registry order. The **legacy model** is `qwen2511-bf16` (today's diffusers route through `character_dataset.py qwenedit`). A **settings block** is the dict `movie_ui_seedgen.qwen_settings(model_id, loras)` returns: exactly `{"qwen_model": {"id", "repo"}, "loras": [{"id", "repo", "file", "scale"}], "steps", "scheduler"}` (`movie_ui_seedgen.py:246-261`).

---

## 0. Scope

### 0.0 The approved design (binding summary)

1. Z-Image-Turbo stays for every image that is created from text. The Qwen registry applies only to edits and to Compose panel 1 when a seed image is used. No Qwen text-to-image anywhere.
2. Locations: text-made stills and their top-ups stay Z-Image. Photo-made edits, their top-up rounds and Regenerate use the Qwen selection.
3. Characters: descriptor and two-source datasets stay Z-Image. Seed-image dataset edits and Regenerate use the Qwen selection.
4. Compose with a seed image: panel 1 is a Qwen edit of the seed prompted by panel 1's description; panels 2..N are unchanged. Without a seed image Compose is unchanged. The picker's first entry is "Seed as-is (no edit)". Seeds from the Seeds tab "Use" default to as-is; uploads and seed-folder seeds default to `qwen21-q4` + `uncensored`. The record keeps which was used.
5. Default everywhere else: `qwen21-q4` + `uncensored` @ 1.0. `qwen2511-bf16` stays selectable for A/B.
6. `content_safety.assert_image_safe` screens every output, always.
7. One shared, importable, unpinned module `qwen_edit.py`; Seeds is refactored onto it with its behaviour unchanged; `qwen2511-bf16` keeps the `character_dataset.py qwenedit` child; the mflux child takes per-job prompt and source and still accepts the old spec; the memory floor is the registry entry's `memory_gib`; the child timeout scales with the job count; `busy_process` sees the Qwen child.
8. Pinned files changed deliberately: `character_dataset.py`, `bin/character`, `character_lib.py`, `bin/ltx-movie`; `bin/ltx-story-images` stays untouched; `test_mut26`'s BASELINE moves in one separate test-only commit.
9. Live checks are run by the user on macstudio; the agent has no access to it.

### 0.1 Grounding (verified at `a62d477`)

**Seeds tool and child.**
- `bin/seed-edit` constants `:66-90` (`AVAIL_WAIT_S` `:74`, `CHILD_TIMEOUT_S = 3600` `:75`, `EDIT_MODEL`..`EDIT_TRUE_CFG` `:76-80`, `MFLUX_MIN_VERSION` `:81`, `MFLUX_GUIDANCE` `:82`, `DEFAULT_MFLUX_PYTHON` `:83`, `SAFETY_SKILL = "seed_edit"` `:84`, `BF16_LINE_RE` `:88`, `MFLUX_LINE_RE` `:89`, `CHILD` `:90`); `check_loras` `:122-146`; `check_args` `:149-204` (`--model qwen` without `--qwen-model` → `LEGACY_QWEN_MODEL` `:192`); `canvas` `:211-223`; host and registry checks `missing_modules` `:285-295`, `modules_problem` `:298-300`, `default_hub` `:303-307`, `mflux_python` `:310-311`, `zimage_problem` `:314-323`, `find_lightning` `:326-337`, `bf16_problem` `:340-351`, `mflux_version` `:354-375`, `pinned_snapshot` `:378-386`, `pinned_file` `:389-397`, `weights_problem` `:400-423`, `qwen_hubs` `:426-428`, `mflux_env_problem` `:431-447`, `lora_problem` `:450-456`, `qwen_model_problem` `:459-473`, `memory_problem` `:476-483`, `avail_gib` `:268-270`, `total_gib` `:273-277`; `probe` `:486-503`; `wait_for_memory` `:506-520`; `preflight` `:523-560`; `finish` `:615-626`; `run_zimage` `:661-683`; `_kill_group` `:686-690`; `run_child` (fixed `CHILD_TIMEOUT_S` timer `:712`) `:693-727`; `run_qwen_child` `:730-746`; `run_bf16` `:749-772`; `run_mflux` (spec with spec-level `prompt`/`source` `:787-793`, parent screening `:795-809`, `hf_child_env` `:813`) `:775-813`; `run` `:820-848`; `main` (interrupt kills `CHILD` `:870-880`) `:851-882`.
- `seed_edit_mflux_child.py`: one `prompt` and one `source` for every job, `image_paths=[spec["source"]]`, `"prompt": spec["prompt"]` `:89-91`.
- `movie_ui_seedgen.py`: registry `:35-94`; `_qwen_fields` `:124-157`; `qwen_settings` `:246-261`; `registry_view` `:281-290`; `availability_error(models, detail, clean)` `:303-321`; `hf_child_env` `:324-333`. Top-level imports `re`, `secrets`, `time`, `movie_ui_lib` (`:13-17`); nothing uses `lib` at import time.

**Characters** (`character_dataset.py`, pinned).
- `EDIT_MODEL`..`EDIT_TRUE_CFG` `:164-168`; `EDIT_MIN_AVAIL_GIB = 64.0` `:180`; `EDIT_CHILD_TIMEOUT_S = 7200` `:181`; `GENERATE_MIN_AVAIL_GIB` `:197`; `AVAIL_WAIT_S` `:199`.
- `busy_process` markers `:549-555` (no `bin/seed-edit`, no `seed_edit_mflux_child.py`).
- `step_log_path` `:657-660`; `edit_models_missing` (HF `local_files_only` lookups of the 2511 repo and Lightning file) `:831-844`.
- `_generate_edits` builds `spec_for(entries)` (spec-level `image` = `seed.png`, jobs without `image`, 1024×640, `data["seed"]`) and runs `run_edit_child` once, or twice with the preview review `:919-944`.
- `_build_dataset`: memory floor `EDIT_MIN_AVAIL_GIB if seed_mode` `:986`; manifest `"generator"` `"%s + %s, %d steps" % (EDIT_MODEL, EDIT_LORA_FILE, EDIT_STEPS)` in seed mode `:1051-1057`.
- `create`: regenerate refusal text `:1130-1135`; `seed_mode` for regenerate `:1147` and create `:1210`; seed-mode editor check `:1216-1221`; seed persisted under the lock `:1240-1252`; new `character.json` dict `:1293-1300`.
- **The record survives the wipe.** `_regenerate` deletes `dataset/` (keeping only `dataset/description.json`) `:1305-1325`; `character.json` lives at `<library>/<name>/character.json` (`character_lib.character_json_path`, `character_lib.py:266-267`), outside `dataset/`. A key added to `character.json` is therefore kept by `data` and rewritten by `_regenerate`'s `write_character` (`:1324`).
- Stills-LoRA test renders: `run_zimage_child(...)` `:1712` and `:1739` (Z-Image, stay unchanged).
- `run_edit_child` (qwenedit child through `run_logged`, `EDIT_CHILD_TIMEOUT_S`) `:1806-1822`; `child_qwenedit` (per-job `image`, spec `skill`, screens, saves only safe images, prints `<basename> ok|blocked <s>s`) `:1839-1883`.
- `character_lib.py` (pinned): `_TOP_LEVEL_KEYS` `:228-231` and `validate_character` refuses missing and extra keys `:365-370`.
- `bin/character` (pinned): docstring `:5-35`, parser `:49-80`, dispatch `:129-132`.

**Locations** (unpinned).
- `location_dataset.py`: `_child_spec` edit spec (per-job `image`, `skill "location_edit"`, the legacy keys) `:477-493`; `_render` floor `character_dataset.EDIT_MIN_AVAIL_GIB` `:496-504`; `_record` generator string `:577-600`; `_build_dataset` with top-up rounds reusing `_child_spec` `:620-702`; `_edit_models_problem` `:743-748`; `create` (edit check when `photos and len(photos) < 24` `:822-825`, record dict `:854-859`) `:785-861`; `_regenerate` (edit check `:890-893`, persist under the lock `:913-921`) `:864-931`.
- `location_lib.py`: `_TOP_LEVEL_KEYS` `:55-57`; `validate_location` refuses missing and extra keys `:193-198`.
- `bin/location`: docstring `:2-28`, parser `:47-83`.

**Compose** (`bin/ltx-movie`, pinned).
- Top-level imports stdlib + `pipeline_log` `:110-123`; modules loaded by path inside functions (`_image_fit` `:793-798`, `_character_lib` `:801-805`, `_location_lib` `:808-814`).
- `SEED_IMAGE_PREFACE` `:217-221`: with a seed, Panel 1's `Image:` field "must be a faithful, literal description of what the attached image actually shows".
- Parser `:283-496` (`--seed-image` `:299-306`, `--image-seed` default 0 `:320`).
- `_story_paths` `:608-619`; `_load_story_panels` (via `bin/ltx-story-manifest`'s parser) `:714-732`.
- `_resolve_shots` refuses `--shots` with `--seed-image` `:1185-1189`; `main` refuses `--seed-image` with `--no-stills` `:2701-2705`.
- `phase0_seed` derives `video_width`/`video_height` (multiples of 64, `ltx_image_fit.GRID_PX`) from the seed `:1326-1344`.
- `_still_size` = twice the video size `:2010-2016`; `phase2_stills` passes `--seed-image args.seed_image` `:2027-2028`; `_shots_stills_groups` already loads `bin/ltx-story-images` by path `:2073-2075`.
- `phase_release_story_server` (Phase 1b) `:2141-2159`.
- Dry run `_print_dry_run_plan` `:2478-2630` (Phase 1b block `:2545-2550`, Phase 2 seed `:2570-2571`).
- `_phase_sequence` `:2637-2655`; `main` resolve chain `:2712-2730`, dry run `:2732-2733`, phases `:2764-2768`.
- **The Phase 1/2 boundary.** After Phase 1 (and Phase 1b, the default), `story.md` holds Panel 1's `Image:` field and an optional `Style:` field; `bin/ltx-story-images` would render panel 1 from `_compose_prompt(Image:, Style:)` (`bin/ltx-story-images:206-222`, `_style_text` `:194-204`) and, with `--seed-image`, instead always rewrites `panel_01.png` from the seed through `_write_seed_panel` (`fit_letterbox`, `:179-191`; panel 1 path `:471-491`, regardless of an existing file). Passing the edited image as `--seed-image` therefore reaches panel 1 with no change to `bin/ltx-story-images`.
- "Grounded mode" (`bin/ltx-story-images:351`) is a story with a `Style:` line; it pins the stills seed. It does not change the seed-image path.
- `story_engine.py` with a seed: `SEED_PANEL` (`:2910-2913`) and `SEED_PARAGRAPH` (`:380-384`) also make Panel 1's image a literal description of the seed.

**movie-ui.**
- `movie_ui_lib.py` is standard library only (`:5`, GC2). `DEFAULT_FIELDS` `:942-955`; `FIELD_FLAGS` (30 entries) `:960-974`; `compose_fields` `:977-986`; `build_argv` (`--seed-image` `:1027-1028`) `:1016-1073`; `location_argv` `:1120-1147`; `character_argv` `:1167-1196`; `seed_edit_argv` `:1199-1214`; `parse_help_flags`/`help_flags`/`supported_map` `:1262-1300`; `validate_fields` (rule 12c `:1534`, rule 18 refuses an unsupported flag `:1563-1567`) `:1461-1567`; `seed_edit_check` `:1688-1709`; `PHASE_RE` (`\d+b?`) `:2215`; `job_phases` `:2248-2256`.
- `movie_ui_server.py`: initial `seed_edit` capability with the registry `:215-216`; `refresh_capabilities` `:223-234`; `_fields_body` `:759-762`; `_h_job_create` `:826-833`; `_h_seed_folder` `:926-954`; `character_create_errors` `:1419-1451`; `_h_character_create` `:1469-1481`; `_h_character_seed_folder` `:1537-1568`; `_h_character_regenerate` `:1571-1577`; `_h_seed_run_create` `:1737-1784`; `_h_seed_use` (stores the candidate as an upload, no origin kept) `:1878-1886`; `location_create_errors` `:1969-1998`; `_h_location_create` `:2053-2061`; `_h_location_regenerate` `:2082-2099`.
- `movie_ui_batch.py`: `GROUPS` `:34`; `FIELD_LEVELS` `:38-45`; `merge` `:194-212`.
- Page: `index.html` Compose Resolution fieldset `:66-90`; Seeds Qwen box `:178-183`; Characters form `:267-280`, detail `:291-300`; Locations form `:313-321`, detail `:322-335`. `app.js`: `S` `:22-26`; `S.seeds` `:57`; `renderBadges` (calls all four tab updaters) `:226-249`; `loadOptions` (`[data-field]` gating) `:304-316`; `composeFields` `:406-439`; `updateComposeButtons` `:516-538`; `onSeedFile` `:547-560`; `onFolderPick` `:576-600`; `fillCompose` `:776-`; `setupCompose` `:829-`; Seeds picker `seedRegistry` `:1773`, `seedQwenEntry` `:1775-1778`, `seedLoraEntry` `:1780-1783`, `seedMultiple` `:1785-1788`, `readSeedQwen` `:1790-1801`, `renderSeedQwen` `:1803-1874`, `seedLoraBody` `:1876-1884`, `seedModelText` `:1886-1899`, `updateSeedButtons` `:1924-2011`, `seedBody` `:2013-2025`; `useSeed` `:2162-2174`; `setupSeeds` `:2268-2287`; `openCharacter` `:2313-2329`; `updateCharacterButtons` `:2331-2351`; `createCharacter` `:2353-2380`; `setupCharacters` `:2382-2412`; `openLocation` `:2472-2512`; `updateLocationButtons` `:2514-2526`; `createLocation` `:2528-2546`; `setupLocations` `:2548-2585`.

**Tests.**
- `tests/test_movie_ui_builder.py`: `NEW_PY` `:213-218`; `PIPELINE_FILES` `:220-225`; `test_mut25` compile `:228-235` and source scan (forbids `load_module(`, `urllib`, …; import allow-list only for `NEW_PY[:2]` = `movie_ui_lib.py`, `movie_ui_server.py`) `:238-266`; `test_mut26` with `BASELINE = "38005c3bfee25daf73da231692609fc0b8d25892"` and its "then to <sha> (<what>)" comment chain `:269-299`.
- `tests/test_seed_edit_tool.py` patches `tool.avail_gib`, `tool.total_gib`, `tool.missing_modules` in its `env` fixture `:113-133` and calls or patches moved names in 38 places; `tests/test_movie_ui_seedgen.py` pins the Seeds page texts (`SEED_FUNCTIONS` `:1122-1126`, `QWEN_JS_TEXTS` `:1178-1191`, `test_sq_final_d_e_f_page_guards` `:1240-1260`), SQT18 (`:1336-1361`) and SGT34 (`:1316-1331`).
- `tests/test_location_ui.py:267` and `tests/test_movie_ui_builder.py:137` pin `len(FIELD_FLAGS) == 30`; `tests/test_movie_ui_batch.py:76-78` pins `(25, 5, 30)`.
- `tests/test_ltx_movie_offline.py` prints `OK 347/347`; its `L41` cases pin `_phase_sequence` (`:1433-1462`).

**Deploy package.** `scripts/deploy/build_pkg.py:383-386` lists `bin/ltx-movie` among the A1 `PIPELINE_FILES`; the package copies it, records its sha256 at build time and requires it committed and clean against `HEAD` (`git_file_state` `:1218-1238`). **It does not pin `bin/ltx-movie`'s content to a fixed hash, so it needs no edit.** A1 does not ship `qwen_edit.py`, `movie_ui_lib.py`, `movie_ui_seedgen.py` or `seed_edit_mflux_child.py` (QE46 covers that).

### 0.2 Deliverables

| # | File | Change |
|---|---|---|
| D1 | `qwen_edit.py` (new, unpinned) | the shared selection checks and edit runner (§2) |
| D2 | `seed_edit_mflux_child.py` | per-job prompt and source, old spec still accepted (§3) |
| D3 | `bin/seed-edit` | refactored onto D1, behaviour unchanged (§4) |
| D4 | `movie_ui_seedgen.py` | `qwen_selection` made public and parameterised (QE51) |
| D5 | `location_lib.py` | optional `edit` key (§5.3) |
| D6 | `location_dataset.py` | selection for photo edits, record, manifest, floor (§5) |
| D7 | `bin/location` | `--qwen-model`, `--lora` (§5.1) |
| D8 | `character_lib.py` (pinned) | optional `edit` key (§6.3) |
| D9 | `character_dataset.py` (pinned) | selection for seed edits, routing in `run_edit_child`, busy markers (§6) |
| D10 | `bin/character` (pinned) | `--qwen-model`, `--lora` (§6.1) |
| D11 | `bin/ltx-movie` (pinned) | `--seed-edit-model`, `--seed-edit-lora`, Phase 1c (§7) |
| D12 | `movie_ui_lib.py` | fields, flags, argv, V1 rule 12d, phases (§8.1) |
| D13 | `movie_ui_server.py` | 400/409 and forwarding for Compose, Locations, Characters (§8.2) |
| D14 | `movie_ui_batch.py` | levels, groups, merge for the two new fields (§8.3) |
| D15 | `static/movie-ui/index.html`, `static/movie-ui/app.js` | `qwenPicker` and its six mounts on four tabs (§9) |
| D16 | tests | QET1-QET39 and the §11.3 edits |
| D17 | `tests/test_movie_ui_builder.py` | `test_mut26` BASELINE, in its own test-only commit (§13.3) |

Untouched: `bin/ltx-story-images`, `story_engine.py`, `bin/seed-edit-setup`, `content_safety.py`, `z_image_skill.py`, `mps_guard.py`, `movie_ui_seedfolder.py`, `scripts/deploy/build_pkg.py`, `static/movie-ui/app.css` (the picker reuses `.se-loras`/`.se-lora`), every other `PIPELINE_FILES` member.

### 0.3 Out of scope

- Qwen text-to-image anywhere (Z-Image keeps every text-made still, top-up, stills-LoRA test render and Compose panel without a seed).
- People-removal edits on user photos.
- Z-Image LoRAs on Qwen models (and Qwen LoRAs on Z-Image); the registry LoRAs only.
- Any change to `bin/ltx-story-images` or `story_engine.py` (including the seed prefaces, see Section 16 item 1).
- Seeds-tab features beyond the refactor; `bin/seed-edit-setup` changes; free-form repo IDs or paths; user-editable steps or guidance; multi-reference edits.
- A Qwen edit of Compose panels 2..N, of shots-mode panels or of a no-stills movie.
- A batch-fork control for the edit model (the fields exist for the invariants of §8.3; the batch page does not expose them).
- Running a real model, a real server, setup, a render or a download in tests; any agent access to macstudio.

### 0.4 Success criteria (KPIs)

| ID | Criterion | Verified by |
|---|---|---|
| QEK1 | `python3 -m pytest tests/ -q -rA` from `WS` has no failure beyond `test_d2_copied_literals_match_the_spike` and `test_rst62_import_sets` | §13.1 gate |
| QEK2 | `python3 tests/test_ltx_movie_offline.py` prints `OK 347/347` (no check added to or removed from that file) | §13.1 gate |
| QEK3 | Seeds behaviour unchanged: every Seeds test passes after the mechanical §11.3 edits; run.json, candidate files and stdout lines of every SQT5/SQT6/SGT9-SGT11 case are as before; only the mflux spec shape changes (per-job `prompt`/`source`) | QET12, §11.3 |
| QEK4 | Default `bin/ltx-movie` unchanged: without `--seed-edit-model` (or with `as-is`) the phase tuple, the Phase 2 command and the dry-run output are byte-identical to `a62d477` | QET26, QET31 |
| QEK5 | Content safety screens every output on every path (mflux in the parent, legacy in the child), a blocked output never gets its final name, a blocked Compose seed fails the job | QET5, QET7, QET18, QET29 |
| QEK6 | L1: `qwen21-q4` + `uncensored` keeps at least as many stills as `qwen2511-bf16` with no more top-up rounds | L1 |
| QEK7 | L2: `qwen21-q4` identity pass rate is no lower than `qwen2511-bf16`'s | L2 |
| QEK8 | L3: the user judges that panel 1 follows its description while keeping the seed's person and look; a Seeds-Use seed stays as-is | L3 |
| QEK9 | At least 20 GiB free on the disk holding `WS` before the gate runs | §13.1 |

### 0.5 Must-haves and nice-to-haves

Every QE requirement and QET test is a must-have. L4 is optional (notes). There are no nice-to-haves.

---

## 1. Architecture

```
Seeds  (bin/seed-edit) ──────────────┐
Locations (bin/location → location_dataset ─┐            ┌─ install_problem / selection_problem / memory_floor
Characters (bin/character → character_dataset)─ run_edit_child ─┤
                                     │ (legacy qwen2511-bf16: unchanged qwenedit child via run_logged)
Compose (bin/ltx-movie Phase 1c) ────┴──────────────────── qwen_edit.run_jobs(model, loras, jobs, …)
                                                               ├─ mflux entries: seed_edit_mflux_child.py (per-job prompt/source),
                                                               │    HF token stripped, every output screened in this process
                                                               └─ qwen2511-bf16: character_dataset.py qwenedit (screens itself)
movie-ui: picker (6 mounts) → request fields → seedgen.qwen_selection (400) → bin/seed-edit --probe (409) → explicit CLI flags
```

- **QE1.** `qwen_edit.py` sits in `WS` beside `movie_ui_seedgen.py`. Its top-level imports are exactly `glob`, `importlib.util`, `json`, `os`, `re`, `signal`, `subprocess`, `sys`, `threading`, `time`, `movie_ui_lib`, `movie_ui_seedgen` (as `lib`, `seedgen`), in that order. It never imports `character_dataset`, PIL, psutil, torch, `content_safety` or mflux at top level (each is imported inside the function that uses it). Python 3.9 and 3.13. It is added to `NEW_PY` (QE70), so `test_mut25` compiles and scans it.
- **QE2.** `movie_ui_lib.py` and `movie_ui_server.py` do **not** import `qwen_edit` **[spec choice]**: the server's 400 rules use `movie_ui_seedgen` (already allowed), its 409 rule uses `bin/seed-edit --probe` (as Seeds). The `test_mut25` allow-list is unchanged (Section 16 item 4).
- **QE3.** Callers: `bin/seed-edit` (`import qwen_edit as qe` at top, after `movie_ui_seedgen`); `location_dataset.py` and `character_dataset.py` (`import qwen_edit  # noqa: E402` at top, after their existing workspace imports); `bin/ltx-movie` (loaded by path inside functions only, QE41).
- **QE4.** The legacy model keeps today's routes: Locations and Characters through `character_dataset.run_edit_child`'s existing body (byte-identical qwenedit spec, `run_logged`, `EDIT_CHILD_TIMEOUT_S`, logs under `logs/`); Seeds and Compose through `qwen_edit.run_jobs`, which spawns the same `character_dataset.py qwenedit` child exactly as `bin/seed-edit` does today.

---

## 2. `qwen_edit.py` (QE5-QE16)

### 2.1 Constants and exceptions

- **QE5.** Module constants, typed exactly:

```python
WS = os.path.dirname(os.path.realpath(__file__))
EDIT_MODEL = "Qwen/Qwen-Image-Edit-2511"                                  # character_dataset.EDIT_MODEL
EDIT_LORA_REPO = "lightx2v/Qwen-Image-Edit-2511-Lightning"                # character_dataset.EDIT_LORA_REPO
EDIT_LORA_FILE = "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors"
EDIT_STEPS = 8
EDIT_TRUE_CFG = 1.0
LEGACY_EDIT_MODEL = "qwen2511-bf16"
MODEL_IDS = seedgen.QWEN_MODEL_IDS
MFLUX_MIN_VERSION = (0, 24, 0)
MFLUX_GUIDANCE = 1.0
DEFAULT_MFLUX_PYTHON = "~/mflux-edit/.venv/bin/python"   # expanded at use
AVAIL_WAIT_S = 600               # character_dataset.AVAIL_WAIT_S
CHILD_TIMEOUT_S = 3600           # the timeout floor (bin/seed-edit's former fixed timeout)
JOB_TIMEOUT_S = 600              # the budget per job above the floor
MFLUX_LINE_RE = re.compile(r"^seed-edit-child done (\d+) ([0-9]+\.[0-9])$")
QWENEDIT_LINE_RE = re.compile(r"^(\S+) (ok|blocked) ([0-9]+\.[0-9])s$")
CHILD = None    # the running Qwen child's Popen, or None


class SelectionError(Exception):
    """A bad edit-model or LoRA option; the message is the refusal text."""


class Unavailable(Exception):
    """The selection cannot run here now; the message is the refusal text."""
```

### 2.2 Functions moved verbatim from `bin/seed-edit`

- **QE6.** These functions move from `bin/seed-edit` into `qwen_edit.py` with their names, bodies and docstrings unchanged except as noted: `avail_gib` `:268-270`, `total_gib` `:273-277`, `missing_modules` `:285-295`, `modules_problem` `:298-300`, `default_hub` `:303-307`, `mflux_python` `:310-311`, `find_lightning` `:326-337`, `bf16_problem` `:340-351`, `mflux_version` `:354-375`, `pinned_snapshot` `:378-386`, `pinned_file` `:389-397`, `weights_problem` `:400-423`, `qwen_hubs` `:426-428`, `mflux_env_problem` `:431-447`, `lora_problem` `:450-456`, `qwen_model_problem` `:459-473`, `memory_problem` `:476-483`, `_kill_group` `:686-690`. `mflux_version`, `default_hub`, `pinned_snapshot`, `pinned_file` and `weights_problem` stay byte-identical to `bin/seed-edit-setup`'s copies (SQT18 now compares setup with `qwen_edit.py`, §11.3).
- **QE7.** `wait_for_memory(floor, label, tag="seed-edit")` is `bin/seed-edit:506-520` with two changes: the waiting line is `print("%s: waiting up to %d s for %g GiB available (now %.1f GiB)" % (tag, AVAIL_WAIT_S, floor, now), flush=True)`, and the refusal raises `Unavailable` with the unchanged text `only %.1f GiB available after waiting %d s; %s needs %g GiB; free memory and retry`.
- **QE8.** `run_child(argv, env, on_line, timeout_s, log_path=None)` is `bin/seed-edit:693-727` with two changes: the timer is `threading.Timer(timeout_s, on_timeout)`; when `log_path` is not `None` the file is opened once with `open(log_path, "a", encoding="utf-8")` before the read loop and every line is written to it (`line` as read, then `flush()`) after it is echoed to stdout; the file is closed in the `finally`. It still sets and clears the module global `CHILD`.
- **QE9.** `kill_running_child()`: `if CHILD is not None: _kill_group(CHILD.pid)`.

### 2.3 New pure helpers

```python
def check_lora_args(values, entry, flag="--lora"):
    """bin/seed-edit's check_loras (seed models SQ12 rows 12-16) with the flag name as a parameter:
    the cleaned [{"id", "scale"}] in registry order, or SelectionError."""
    # body: bin/seed-edit:125-146 with Refusal -> SelectionError and every literal "--lora" -> flag


def cli_selection(model_arg, lora_args, model_flag="--qwen-model", lora_flag="--lora"):
    """(model_id, loras) of a tool's edit-model options, or SelectionError (qwen edit models QE10)."""
    if model_arg is None:
        if lora_args is not None:
            raise SelectionError("%s needs %s" % (lora_flag, model_flag))
        return seedgen.DEFAULT_QWEN_MODEL, seedgen.default_loras(seedgen.DEFAULT_QWEN_MODEL)
    if model_arg not in MODEL_IDS:
        raise SelectionError("%s must be one of %s" % (model_flag, ", ".join(MODEL_IDS)))
    return model_arg, check_lora_args(lora_args or [], seedgen.qwen_model(model_arg), lora_flag)


def settings(model_id, loras):
    return seedgen.qwen_settings(model_id, loras)


def selection_of(edit):
    """(model_id, [{"id", "scale"}]) of a recorded settings block."""
    return edit["qwen_model"]["id"], [{"id": l["id"], "scale": l["scale"]} for l in edit["loras"]]


def label(model_id):
    return seedgen.qwen_model(model_id)["label"]


def multiple(model_id):
    return seedgen.qwen_model(model_id)["multiple"]


def memory_floor(model_id):
    return seedgen.qwen_model(model_id)["memory_gib"]


def child_timeout(n_jobs):
    return max(CHILD_TIMEOUT_S, JOB_TIMEOUT_S * n_jobs)


def generator_text(model_id, loras):
    """The manifest "generator" string of a selection; the legacy model keeps today's exact text."""
    if model_id == LEGACY_EDIT_MODEL:
        return "%s + %s, %d steps" % (EDIT_MODEL, EDIT_LORA_FILE, EDIT_STEPS)
    entry, chosen = seedgen.qwen_model(model_id), seedgen.qwen_settings(model_id, loras)
    listed = ", ".join("%s@%g" % (l["id"], l["scale"]) for l in chosen["loras"]) or "none"
    return "%s (%s) + LoRAs %s, %d steps" % (entry["label"], entry["repo"], listed, chosen["steps"])
```

- **QE10. CLI rule** (binding notes, Section 2 "Shared"): neither option → the registry default (`qwen21-q4` with `[{"id": "uncensored", "scale": 1.0}]`); `--qwen-model` given → exactly the listed LoRAs (none listed → none). **[spec choice]** `--lora` without `--qwen-model` is refused (`--lora needs --qwen-model`), so a lone LoRA never silently picks a model.
- **QE11. Timeout** **[spec choice]**: `child_timeout(n) = max(3600, 600 × n)`: 3600 s for 1-6 jobs (every Seeds run, 1-4 candidates, keeps its limit; the Characters preview of 6 too), 4200 s for 7, 10800 s for 18 (the Characters edits after the preview), 13800 s for 23 (a one-photo location), 14400 s for 24. Justification: the legacy route allows 7200 s for 24 Lightning edits (300 s each, `character_dataset.py:181`); 2.1 runs 40 steps instead of 8, so 600 s per job gives twice the legacy per-edit budget, and the 3600 s floor covers the model load of a short run. L1 records the real seconds per still (Open question 3).
- `generator_text` examples: `qwen21-q4` + uncensored 1.0 → `Qwen-Image-2.1 q4 (mflux-community/qwen-image-2-1-mflux-q4) + LoRAs uncensored@1, 40 steps`; `qwen21-q8` + uncensored 0.5 + viggle-turbo 1 → `Qwen-Image-2.1 q8 (mflux-community/qwen-image-2-1-mflux-q8) + LoRAs uncensored@0.5, viggle-turbo@1, 6 steps`; `qwen2511-q4` → `Qwen-Image-Edit-2511 q4 (Lightning) (mflux-community/qwen-image-edit-2511-mflux-q4) + LoRAs none, 8 steps`; `qwen2511-bf16` → `Qwen/Qwen-Image-Edit-2511 + Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors, 8 steps` (today's string).

### 2.4 Selection checks

```python
def install_problem(model_id, loras):
    """(None, paths) when the selection is installed, else (refusal text, {}); paths is
    {"model_path", "builtin_lora", "lora_paths"} ({} entries for the diffusers model). The texts are
    bin/seed-edit's SQ21 steps 1-2."""
    entry = seedgen.qwen_model(model_id)
    problem, paths = qwen_model_problem(entry)
    if problem is not None:
        return "%s is unavailable: %s" % (entry["label"], problem), {}
    lora_paths = []
    for item in seedgen.registry_order(loras):
        lora = seedgen.qwen_lora(item["id"])
        problem, path = lora_problem(lora, qwen_hubs())
        if problem is not None:
            return "LoRA %s is unavailable: %s" % (lora["label"], problem), {}
        lora_paths.append(path)
    return None, dict(paths, lora_paths=lora_paths)


def selection_problem(model_id, loras):
    """None when the selection can run on this host (its total memory reaches the entry's memory_gib
    and it is installed), else the refusal text. Memory first, as the probe (seed models SQ18)."""
    entry = seedgen.qwen_model(model_id)
    memory = memory_problem(entry)
    if memory is not None:
        return "%s is unavailable: %s" % (entry["label"], memory)
    return install_problem(model_id, loras)[0]
```

- **QE12. Memory floor.** Every edit waits for the selected entry's `memory_gib` available (`qwen21-q4` 20, `qwen21-q8` 32, `qwen21-bf16` 56, `qwen2511-q4` 32, `qwen2511-bf16` 64): Seeds and Compose through `wait_for_memory`, Locations and Characters through their unchanged `_with_story_server_stopped`/`wait_for_avail` (story server stopped first, restored after, unchanged). The hard-coded 64 GiB edit floor applies only when the legacy model is selected (it equals that entry's `memory_gib`).

### 2.5 `run_jobs`

- **QE13. Signature and contract.** `run_jobs(model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None, noun="job")` → `(results, failure)`.
  - `jobs`: a non-empty list of `{"n": int (unique, ≥ 1), "seed": int, "prompt": str, "source": absolute path, "stage_path": absolute path, "output_path": absolute path}`; every `os.path.basename(stage_path)` is unique.
  - `results`: one dict per job, in job order, `{"n", "output_path", "status": "ok" | "blocked" | "failed", "seconds": float | None}` (`failed` = the child never reported it; `seconds` is `None` then).
  - `failure`: `None`, or exactly one of `"<label> child timed out after <t> s"` (`t = child_timeout(len(jobs))`), `"<label> child exited <code>: <last non-blank child line or ->"`, `"<label> child exited 0 without finishing <noun> <n>"` (the first job, in job order, with no result).
  - `on_result(result)` is called once per job as soon as its status is known (`ok` or `blocked`), after its file is in place; never for `failed`.
  - An `ok` job's image is at `output_path`; a `blocked` or `failed` job has no file at `output_path` or `stage_path` written by this call (a `blocked` stage file is deleted).
  - Raises `Unavailable(text)` when `install_problem` fails (a model removed since the caller's preflight). Any exception from screening or a file operation propagates (the child is killed by `run_child`'s `finally`).
- **QE14. Body** (load-bearing; typed as written):

```python
def run_jobs(model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None, noun="job"):
    """Run one Qwen edit child over jobs and screen every output (qwen edit models spec QE13-QE16)."""
    entry = seedgen.qwen_model(model_id)
    problem, paths = install_problem(model_id, loras)
    if problem is not None:
        raise Unavailable(problem)
    os.makedirs(work_dir, exist_ok=True)
    chosen = seedgen.qwen_settings(model_id, loras)
    by_n = dict((job["n"], job) for job in jobs)
    done = {}

    def finish(n, status, seconds):
        done[n] = (status, seconds)
        if on_result is not None:
            on_result({"n": n, "output_path": by_n[n]["output_path"], "status": status, "seconds": seconds})

    if entry["backend"] == "diffusers":
        first = jobs[0]["source"]
        spec_jobs = []
        for job in jobs:
            item = {"prompt": job["prompt"], "output_path": job["stage_path"], "seed": job["seed"],
                    "width": width, "height": height}
            if job["source"] != first:
                item["image"] = job["source"]
            spec_jobs.append(item)
        spec_path = os.path.join(work_dir, "qwenedit_spec.json")
        lib.write_json_atomic(spec_path, {
            "image": first, "model": EDIT_MODEL, "lora_repo": EDIT_LORA_REPO, "lora_file": EDIT_LORA_FILE,
            "steps": EDIT_STEPS, "true_cfg": EDIT_TRUE_CFG, "skill": skill, "jobs": spec_jobs,
            "report_path": os.path.join(work_dir, "qwenedit_report.json")})
        by_stage = dict((os.path.basename(job["stage_path"]), job["n"]) for job in jobs)
        script = os.environ.get("SEED_EDIT_QWENEDIT_SCRIPT") or os.path.join(WS, "character_dataset.py")
        argv = [sys.executable, script, "qwenedit", "--spec", spec_path]
        env = dict(os.environ, PYTHONUNBUFFERED="1")

        def handle(line):
            match = QWENEDIT_LINE_RE.match(line)
            n = by_stage.get(match.group(1)) if match else None
            if n is None or n in done:
                return
            if match.group(2) == "ok":
                os.replace(by_n[n]["stage_path"], by_n[n]["output_path"])
            finish(n, match.group(2), float(match.group(3)))
    else:
        import content_safety
        from PIL import Image
        builtin = entry["builtin_lora"]
        ordered = seedgen.registry_order(loras)
        spec_path = os.path.join(work_dir, "mflux_spec.json")
        lib.write_json_atomic(spec_path, {
            "family": entry["family"], "model_path": paths["model_path"],
            "lora_paths": ([paths["builtin_lora"]] if builtin is not None else []) + paths["lora_paths"],
            "lora_scales": ([builtin["scale"]] if builtin is not None else []) + [item["scale"] for item in ordered],
            "width": width, "height": height, "steps": chosen["steps"], "guidance": MFLUX_GUIDANCE,
            "scheduler": chosen["scheduler"],
            "jobs": [{"n": job["n"], "seed": job["seed"], "prompt": job["prompt"], "source": job["source"],
                      "output_path": job["stage_path"]} for job in jobs]})
        argv = [mflux_python(), os.path.join(WS, "seed_edit_mflux_child.py"), "--spec", spec_path]
        env = seedgen.hf_child_env(os.environ, PYTHONUNBUFFERED="1", HF_HUB_OFFLINE="1")

        def handle(line):
            match = MFLUX_LINE_RE.match(line)
            n = int(match.group(1)) if match else None
            if n not in by_n or n in done:
                return
            job = by_n[n]
            with Image.open(job["stage_path"]) as img:
                rgb = img.convert("RGB")
            try:
                content_safety.assert_image_safe(rgb, skill=skill, prompt=job["prompt"])
            except content_safety.ContentSafetyError:
                os.remove(job["stage_path"])
                finish(n, "blocked", float(match.group(2)))
                return
            os.replace(job["stage_path"], job["output_path"])
            finish(n, "ok", float(match.group(2)))

    last = [""]

    def on_line(line):
        if line.strip():
            last[0] = line.strip()
        handle(line)

    timeout = child_timeout(len(jobs))
    code, timed_out = run_child(argv, env, on_line, timeout, log_path)
    failure = None
    if timed_out:
        failure = "%s child timed out after %d s" % (entry["label"], timeout)
    elif code != 0:
        failure = "%s child exited %d: %s" % (entry["label"], code, last[0] or "-")
    else:
        missing = [job["n"] for job in jobs if job["n"] not in done]
        if missing:
            failure = "%s child exited 0 without finishing %s %d" % (entry["label"], noun, missing[0])
    results = [{"n": job["n"], "output_path": job["output_path"],
                "status": done[job["n"]][0] if job["n"] in done else "failed",
                "seconds": done[job["n"]][1] if job["n"] in done else None} for job in jobs]
    return results, failure
```

- **QE15.** For the mflux backends the spec no longer has spec-level `prompt`/`source`: every job carries them (QE17). The mflux child's environment always comes from `seedgen.hf_child_env` (no `HF_TOKEN`, no `HUGGING_FACE_HUB_TOKEN`, `HF_HUB_DISABLE_IMPLICIT_TOKEN=1`, `HF_HUB_OFFLINE=1`). The diffusers child keeps `dict(os.environ, PYTHONUNBUFFERED="1")` (seed models §14a item B kept it; Section 14).
- **QE16.** The legacy spec written by `run_jobs` for a run whose jobs share one source equals byte-for-byte what `bin/seed-edit`'s `run_bf16` writes today (`:754-759`), so SGT11 and SQT6's bf16 dict hold unchanged.

---

## 3. `seed_edit_mflux_child.py` (QE17-QE18)

- **QE17.** The job loop (`:87-100`) reads each job's own prompt and source, falling back to the spec-level values of the old shape. Lines `:89-91` become exactly:

```python
        prompt = job["prompt"] if "prompt" in job else spec["prompt"]
        source = job["source"] if "source" in job else spec["source"]
        kwargs = {"seed": job["seed"], "prompt": prompt, "image_paths": [source],
                  "num_inference_steps": spec["steps"], "guidance": spec["guidance"],
                  "width": spec["width"], "height": spec["height"]}
```
  Everything else (gates, family dispatch, LoRA lists, `bake_lora=False`, `quantize=None`, `.convert("RGB").save(`, the two printed lines, exit codes) is unchanged. A spec in the old shape (spec-level `prompt`/`source`, jobs without them) produces exactly today's calls (QET10).
- **QE18.** The docstring's "The spec carries …" sentence becomes: `The spec carries family, model_path, lora_paths and lora_scales (equal-length lists, possibly empty), width, height, steps, guidance (always 1.0), scheduler (qwen21 only) and jobs, each {n, seed, prompt, source, output_path}; a spec-level prompt and source (the shape before docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md) are used for jobs that carry none.`

---

## 4. `bin/seed-edit` refactor (QE19-QE23)

- **QE19. Imports.** Top-level imports become exactly `argparse`, `glob`, `json`, `os`, `re`, `secrets`, `shutil`, `signal`, `sys`, `time`, `movie_ui_lib as lib`, `movie_ui_seedgen as seedgen`, `qwen_edit as qe` (the last three after `sys.path.insert`). `importlib.util`, `subprocess` and `threading` are dropped (only moved code used them).
- **QE20. Removed from `bin/seed-edit`:** the QE6 functions, `wait_for_memory`, `run_child`, `run_qwen_child`, `run_bf16`, `run_mflux`, `pending_candidate`, `check_loras`, and the constants `AVAIL_WAIT_S`, `CHILD_TIMEOUT_S`, `EDIT_MODEL`, `EDIT_LORA_REPO`, `EDIT_LORA_FILE`, `EDIT_STEPS`, `EDIT_TRUE_CFG`, `MFLUX_MIN_VERSION`, `MFLUX_GUIDANCE`, `DEFAULT_MFLUX_PYTHON`, `BF16_LINE_RE`, `MFLUX_LINE_RE`, `CHILD`. Kept unchanged: `LONG_EDGE`, `MULTIPLE`, `MIN_SIDE`, `PROMPT_MAX`, `SEED_MAX`, `STRENGTH_DEFAULT`, `MIN_FREE_GIB`, `ZIMAGE_MIN_AVAIL_GIB`, `SAFETY_SKILL`, `BACKEND_LABELS`, `EXTS`, `Refusal`, `say`, `error`, `parse`, `canvas`, `read_source`, `prepare_source`, `disk_free_gib`, `cpu_generator`, `new_record`, `write_run`, `final_path`, `part_path`, `pending_path`, `first_pending`, `finish`, `fail_rest`, `refuse`, `cleanup`, `run_zimage`, `_interrupt`.
- **QE21. Rewired calls** (texts unchanged):
  - `check_args` row 12-16: `loras = qe.check_lora_args(args.lora or [], seedgen.qwen_model(qwen_model))` inside `try/except qe.SelectionError as e: raise Refusal(str(e))`.
  - `zimage_problem`: `qe.modules_problem(...)`.
  - `probe`: `qe.qwen_hubs()`, `qe.memory_problem`, `qe.qwen_model_problem`, `qe.lora_problem`.
  - `preflight`, Z-Image branch: `qe.wait_for_memory(ZIMAGE_MIN_AVAIL_GIB, ctx["label"])` in `try/except qe.Unavailable as e: raise Refusal(str(e))`. Qwen branch, replacing `:543-556`:
    ```python
    entry = seedgen.qwen_model(opts["qwen_model"])
    ctx["entry"], ctx["label"] = entry, entry["label"]
    problem, _paths = qe.install_problem(entry["id"], opts["loras"])
    if problem is not None:
        raise Refusal(problem)
    try:
        qe.wait_for_memory(entry["memory_gib"], entry["label"])
    except qe.Unavailable as e:
        raise Refusal(str(e))
    ```
    (the `ctx["paths"]`/`ctx["lora_paths"]` keys are no longer set; the why-text lines `:557-560` are unchanged).
  - `run`'s runner map: `{"zimage": run_zimage, "diffusers": run_qwen, "mflux": run_qwen}`.
  - `main`'s interrupt branch: `qe.kill_running_child()` replaces `:871-873`.
- **QE22. `run_qwen(ctx)`** (new):
    ```python
    def run_qwen(ctx):
        """SG19, SG20, seed models SQ23, qwen edit models QE22: every candidate through qwen_edit.run_jobs;
        returns None or the SG17 text. The bf16 child stages cand_NN.part.png, mflux cand_NN.pending.png."""
        opts, rec, entry = ctx["opts"], ctx["record"], ctx["entry"]
        stage = pending_path if entry["backend"] == "mflux" else part_path
        jobs = [{"n": c["n"], "seed": c["seed"], "prompt": opts["prompt"],
                 "source": os.path.join(ctx["work"], "source.png"), "stage_path": stage(ctx, c["n"]),
                 "output_path": final_path(ctx, c["n"])} for c in rec["candidates"]]
        _results, failure = qe.run_jobs(entry["id"], opts["loras"], jobs, ctx["width"], ctx["height"], SAFETY_SKILL,
                                        ctx["work"], on_result=lambda r: finish(ctx, r["n"], r["status"], r["seconds"]),
                                        noun="candidate")
        return failure
    ```
  A `qe.Unavailable` raised here reaches `run`'s `except Exception` and becomes `<label> failed on candidate <n>: Unavailable: <text>` (only possible when weights disappear between preflight and run).
- **QE23.** Docstring: the "Environment:" paragraph reads `Environment (read by qwen_edit.py): SEED_EDIT_MFLUX_PYTHON …` with the same variable list; one sentence is added: `The Qwen checks and the child run live in qwen_edit.py (docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md); the child timeout is max(3600, 600 x candidates) s.` Everything SQ12-SQ27 specifies about arguments, texts, probe, run.json and exit codes is unchanged.

---

## 5. Locations (QE24-QE31)

### 5.1 `bin/location` (QE24)

- **QE24.** The `create` sub-parser gains, after `--new-seed`:
    ```python
    p.add_argument("--qwen-model", dest="qwen_model", default=None, metavar="ID",
                   help="photo locations: the Qwen edit model of the edits (qwen21-q4, qwen21-q8, qwen21-bf16, "
                        "qwen2511-q4, qwen2511-bf16; default qwen21-q4 with its default LoRAs)")
    p.add_argument("--lora", dest="lora", action="append", default=None, metavar="ID=SCALE",
                   help="with --qwen-model: a registry LoRA of its family, 0 < SCALE <= 2 (repeatable); none listed "
                        "means no LoRA")
    ```
  The docstring usage lines become `bin/location create NAME [--description TEXT] [--photo PATH ...] [--trigger WORD] [--seed N] [--force] [--qwen-model ID] [--lora ID=SCALE ...]` and `bin/location create NAME --regenerate [--seed N | --new-seed] [--description TEXT] [--force] [--qwen-model ID] [--lora ID=SCALE ...]`, and one sentence is added after the photo sentence: `Photo edits (and their top-up rounds) use the Qwen edit model of --qwen-model (default qwen21-q4 with the uncensored LoRA); text stills stay Z-Image.`

### 5.2 `location_dataset.py` (QE25-QE30)

- **QE25. Option rules** (`PHOTO_ONLY = "--qwen-model and --lora apply only to photo locations"`; the code reads `getattr(args, "qwen_model", None)` and `getattr(args, "lora", None)`, so `argparse.Namespace` objects without them still work):
  - `create`: directly after the `create needs --description or at least one --photo` refusal (`:808-809`): if no photo and either option is not `None` → `_error(PHOTO_ONLY)`; if photos → `model_id, loras = qwen_edit.cli_selection(qwen_model, lora)` (`SelectionError` → `_error(str(e))`).
  - `_regenerate`: directly after the `--regenerate takes no --photo or --trigger` refusal (`:872-874`): a text location with either option → `_error(PHOTO_ONLY)`; a photo location → `cli_selection` as above.
  - Both refusals exit 2 before the lock; nothing is written.
- **QE26. Preflight.** `_edit_models_problem()` becomes `_edit_models_problem(model_id, loras)`: for `qwen_edit.LEGACY_EDIT_MODEL` its body is unchanged (`edit_models_missing` and the `the photo editor is not downloaded: …` text); for any other model it returns `character_dataset.edit_selection_problem(model_id, loras)` (QE34). Both callers (`:823`, `:891`) pass the selection; the condition `len(photos) < location_lib.TOTAL_STILLS` is unchanged.
- **QE27. Record.** A photo location's `location.json` gets `"edit": qwen_edit.settings(model_id, loras)`: in `create`'s new record dict (after `"strength": None`), and in `_regenerate` under the lock together with the seed and description (`data["edit"] = …` before `write_location`, `:919-921`). A text location never has the key. Before `build_dataset` both commands print `edit model: <qwen_edit.generator_text(model_id, loras)>` for a photo location with fewer than 24 photos.
- **QE28. The child spec.** `_child_spec`'s edit spec (`:488-493`) gains `"edit": {"qwen_model": model_id, "loras": loras}` with `(model_id, loras) = qwen_edit.selection_of(data["edit"])`; every other key, including the legacy keys, is unchanged. Top-up rounds call `_child_spec` with the same `data`, so they reuse the run's selection (QET17).
- **QE29. Memory floor.** `_render`'s edit branch uses `qwen_edit.memory_floor(spec["edit"]["qwen_model"])` instead of `character_dataset.EDIT_MIN_AVAIL_GIB` (`:503`); the generate branch is unchanged.
- **QE30. Manifest.** In `_record`, when `child == "edit"` the `"generator"` value is `qwen_edit.generator_text(*qwen_edit.selection_of(data["edit"]))` and the manifest gains `"edit": data["edit"]` directly after `"generator"`; key order: `source, trigger, description, seed, min_score, reference, generator, edit, variant_set, rounds, items`. For text locations and photos-only builds the manifest has no `edit` key and is otherwise unchanged (LD13 holds).
- The module docstring's "Qwen-Image-Edit-2511 edits" becomes "Qwen edits (the registry model of location.json's edit key; docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md)".

### 5.3 `location_lib.py` (QE31)

- **QE31.** New module constants and function (the function is byte-identical in `character_lib.py`, QE38):

```python
_OPTIONAL_KEYS = frozenset(["edit"])
_EDIT_KEYS = frozenset(["qwen_model", "loras", "steps", "scheduler"])
_EDIT_MODEL_KEYS = frozenset(["id", "repo"])
_EDIT_LORA_KEYS = frozenset(["id", "repo", "file", "scale"])


def _edit_problem(edit):
    """The problem of a recorded Qwen edit settings block (qwen edit models spec QE31), or None. Shape
    only: the registry is not consulted."""
    if not isinstance(edit, dict) or set(edit) != _EDIT_KEYS:
        return "must be an object with exactly the keys loras, qwen_model, scheduler, steps, got %r" % (edit,)
    model = edit["qwen_model"]
    if not (isinstance(model, dict) and set(model) == _EDIT_MODEL_KEYS
            and all(isinstance(model[k], str) and model[k] for k in ("id", "repo"))):
        return "qwen_model must be an object with exactly the keys id and repo, both non-empty strings, got %r" % (model,)
    loras = edit["loras"]
    if not (isinstance(loras, list) and all(
            isinstance(l, dict) and set(l) == _EDIT_LORA_KEYS
            and all(isinstance(l[k], str) and l[k] for k in ("id", "repo", "file"))
            and _is_number(l["scale"]) and 0 < l["scale"] <= 2 for l in loras)):
        return ("loras must be a list of objects with exactly the keys file, id, repo (non-empty strings) and "
                "scale (a number in (0, 2]), got %r" % (loras,))
    if not _is_int(edit["steps"]) or edit["steps"] < 1:
        return "steps must be an int >= 1, got %r" % (edit["steps"],)
    if edit["scheduler"] is not None and not (isinstance(edit["scheduler"], str) and edit["scheduler"]):
        return "scheduler must be null or a non-empty string, got %r" % (edit["scheduler"],)
    return None
```
  `validate_location`: the extra-keys check (`:196`) becomes `extra = sorted(set(data) - _TOP_LEVEL_KEYS - _OPTIONAL_KEYS)`; at the end of the function: `if "edit" in data:` → `data["source"] != "photos"` raises `LocationError("edit: only a photo location records an edit model")`; else `problem = _edit_problem(data["edit"])` and a problem raises `LocationError("edit: " + problem)`. `location.json` files without `edit` load exactly as before. The module docstring's schema sentence gains `(schema_version 1, with the optional edit key of docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md)`.

---

## 6. Characters (QE32-QE39)

### 6.1 `bin/character` (pinned, QE32)

- **QE32.** The `create` sub-parser gains, after `--no-review`, the two QE24 arguments with the help texts `"seed-image characters: the Qwen edit model of the dataset edits (qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-q4, qwen2511-bf16; default qwen21-q4 with its default LoRAs)"` and the QE24 `--lora` text. Docstring usage lines: the first and third gain ` [--qwen-model ID] [--lora ID=SCALE ...]`; the sentence `A --seed-image create poses the seed itself with Qwen-Image-Edit-2511 (Lightning 8-step), editing 6 preview stills …` becomes `A --seed-image create poses the seed itself with a Qwen edit model (--qwen-model; default Qwen-Image-2.1 q4 with the uncensored LoRA; qwen2511-bf16 is the earlier Qwen-Image-Edit-2511 Lightning route), editing 6 preview stills …`. Nothing else in the file changes.

### 6.2 `character_dataset.py` (pinned, QE33-QE37)

- **QE33. Routing in `run_edit_child`.** `import qwen_edit  # noqa: E402` is added after `import ltx2_mlx_video_skill as SKILL` (`:49`). `run_edit_child(spec, char_dir, step)` keeps its signature; its new first lines:
    ```python
    edit = spec.get("edit")
    if edit is not None and edit["qwen_model"] != qwen_edit.LEGACY_EDIT_MODEL:
        return _run_registry_edit(spec, edit, char_dir, step)
    spec = dict((k, v) for k, v in spec.items() if k != "edit")
    ```
  followed by the unchanged body (so the legacy qwenedit spec file is byte-identical to today's). New function:
    ```python
    def _run_registry_edit(spec, edit, char_dir, step):
        """run_edit_child for a registry model other than qwen2511-bf16 (qwen edit models spec QE33): the jobs
        through qwen_edit.run_jobs, logged to logs/<stamp>-<step>.log, staged as <stem>.pending.png beside each
        output, screened with spec["skill"] (default character_edit). Returns run_edit_child's report shape."""
        log = step_log_path(char_dir, step)
        jobs = [{"n": i, "seed": job["seed"], "prompt": job["prompt"], "source": job.get("image", spec["image"]),
                 "stage_path": os.path.splitext(job["output_path"])[0] + ".pending.png",
                 "output_path": job["output_path"]} for i, job in enumerate(spec["jobs"], 1)]
        print("Running: %s edit of %d stills; log: %s" % (qwen_edit.label(edit["qwen_model"]), len(jobs), log))
        sys.stdout.flush()
        try:
            results, failure = qwen_edit.run_jobs(edit["qwen_model"], edit["loras"], jobs, spec["jobs"][0]["width"],
                                                  spec["jobs"][0]["height"], spec.get("skill", "character_edit"),
                                                  log[:-len(".log")], log_path=log)
        except qwen_edit.Unavailable as e:
            raise DatasetError(str(e))
        if failure is not None:
            error = DatasetError("%s; log: %s" % (failure, log))
            error.log_path = log
            raise error
        return {"jobs": [{"output_path": r["output_path"], "status": r["status"], "seconds": r["seconds"]}
                         for r in results]}
    ```
  (Every Locations and Characters job is 1024×640, a multiple of 32 and 16, so the first job's size is every job's size. The work directory `logs/<stamp>-<step>/` holds `mflux_spec.json`.)
- **QE34.** New function after `edit_models_missing` (`:844`):
    ```python
    def edit_selection_problem(model_id, loras):
        """None when a registry edit selection other than qwen2511-bf16 is installed and fits this host's
        memory, else the reason (qwen edit models spec QE34). qwen2511-bf16 stays checked by
        edit_models_missing. Called through this module so a test fake applies to bin/location too."""
        return qwen_edit.selection_problem(model_id, loras)
    ```
- **QE35. `busy_process`.** The condition (`:549-555`) becomes:
    ```python
        joined = " ".join(cmdline)
        seed_tool = (any(a == "bin/seed-edit" or a.endswith("/bin/seed-edit") for a in cmdline)
                     and "--probe" not in cmdline)
        if (("ltx-2-mlx" in joined
             and any(t in cmdline for t in ("generate", "train", "preprocess")))
                or seed_tool
                or any(marker in joined for marker in (
                    "mflux-train", "bin/ltx-movie", "bin/ltx-mlx-render",
                    "bin/ltx-story-images", "character_dataset.py zimage",
                    "character_dataset.py qwenedit", "seed_edit_mflux_child.py"))):
            return pid, joined[:120]
    ```
  **[spec choice]** `bin/seed-edit --probe` (the movie-ui's capability probe, no GPU) and `bin/seed-edit-setup` (downloads, no GPU; the argv element ends with `/bin/seed-edit-setup`) are not busy. The docstring's first sentence gains `, Seeds or Qwen edit (seed_edit_mflux_child.py)`.
- **QE36. `create` options** (`SEED_ONLY = "--qwen-model and --lora apply only to seed-image characters"`; `qwen_args = (getattr(args, "qwen_model", None), getattr(args, "lora", None))`):
  - regenerate branch, directly after `seed_mode = …` (`:1147`): `if not seed_mode and qwen_args != (None, None): return _error(SEED_ONLY)`. The `--regenerate takes no …` refusal (`:1130-1135`) and its text are unchanged **[spec choice]** (three tests pin the text; the two new options are simply not refused there).
  - create branch, directly after `seed_mode = seed_path is not None` (`:1210`): the same refusal.
  - after both branches, before the review check (`:1212`): `if seed_mode:` → `edit_model, edit_loras = qwen_edit.cli_selection(*qwen_args)` (`SelectionError` → `_error(str(e))`).
  - the seed-mode editor check (`:1216-1221`): for `qwen_edit.LEGACY_EDIT_MODEL` unchanged; otherwise `problem = edit_selection_problem(edit_model, edit_loras)` and a problem → `_error(problem)`.
  - regenerate persistence (`:1240-1252`), replaced by:
    ```python
            if data is not None:
                changed = new_seed != old_seed
                if seed_mode:
                    new_edit = qwen_edit.settings(edit_model, edit_loras)
                    changed = changed or data.get("edit") != new_edit
                    data["edit"] = new_edit
                data["seed"] = new_seed
                if changed:
                    try:
                        character_lib.write_character(data)
                    except character_lib.CharacterError as e:
                        return _error(e)
                print("seed: %d -> %d" % (old_seed, new_seed) if new_seed != old_seed
                      else "seed: %d (unchanged)" % old_seed)
                if seed_mode:
                    print("edit model: %s" % qwen_edit.generator_text(edit_model, edit_loras))
                return _regenerate(data, review)
    ```
  - new record (`:1293-1300`): when `seed_path is not None` the dict gains `"edit": qwen_edit.settings(edit_model, edit_loras)` after `"stills_skip_reason": None`; before `return build_dataset(...)` a seed-image create prints the same `edit model: …` line.
- **QE37. Build.** `_generate_edits`' `spec_for` gains `"edit": {"qwen_model": m, "loras": l}` with `(m, l) = qwen_edit.selection_of(data["edit"])`. `_build_dataset`: `min_gib = qwen_edit.memory_floor(data["edit"]["qwen_model"]["id"]) if seed_mode else GENERATE_MIN_AVAIL_GIB` (`:986`); the manifest's `"generator"` in seed mode is `qwen_edit.generator_text(*qwen_edit.selection_of(data["edit"]))` and the manifest gains `"edit": data["edit"]` directly after `"generator"` in seed mode only. `EDIT_MIN_AVAIL_GIB` stays (the mirror SGT14 and SQT10 pin against the registry's `qwen2511-bf16` floor) **[spec choice]**. The stills-LoRA test renders (`:1712`, `:1739`) and every descriptor or two-source path are unchanged. The module docstring sentence `Seed-image datasets are edits of the seed (qwenedit, …)` becomes `Seed-image datasets are edits of the seed with the Qwen registry model of character.json's edit key (qwen_edit.run_jobs; the qwenedit child for qwen2511-bf16; docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md)`.

### 6.3 `character_lib.py` (pinned, QE38-QE39)

- **QE38.** The QE31 constants and `_edit_problem` are added byte-identical (QET23 compares the function's code). `validate_character`'s extra-keys check (`:368`) subtracts `_OPTIONAL_KEYS`; at its end: `if "edit" in data:` → `data["source"].get("type") != "seed_image"` raises `CharacterError("edit: only a seed-image character records an edit model")`; else a problem raises `CharacterError("edit: " + problem)`.
- **QE39.** Where the record lives: `character.json` at `<library>/<name>/`; `_regenerate` wipes only `<library>/<name>/dataset/` (`character_dataset.py:1315-1321`), so `edit` survives Regenerate (QET22). A `character.json` without `edit` (every character made before this feature) loads and renders exactly as before.

---

## 7. Compose: `bin/ltx-movie` (pinned, QE40-QE50)

### 7.1 Options

- **QE40.** `build_parser` gains, directly after `--seed-image` (`:306`):
    ```python
    parser.add_argument("--seed-edit-model", dest="seed_edit_model", default=None, metavar="ID|as-is",
                         help="with --seed-image: edit the seed into panel 1 with a Qwen registry edit model "
                              "(qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-q4, qwen2511-bf16), prompted by panel 1's "
                              "Image: text after Phase 1 and screened with content safety; as-is, like leaving the "
                              "flag out, uses the seed unchanged. See docs/superpowers/specs/"
                              "2026-11-03-qwen-edit-models-design.md.")
    parser.add_argument("--seed-edit-lora", dest="seed_edit_loras", action="append", default=None,
                         metavar="ID=SCALE",
                         help="with --seed-edit-model ID: a registry LoRA of that model's family, 0 < SCALE <= 2 "
                              "(repeatable); none listed means no LoRA")
    ```
  Top-level `import hashlib` is added (alphabetical, after `glob`); no other top-level import changes.
- **QE41.** New loader beside `_location_lib`:
    ```python
    def _qwen_edit():
        """qwen_edit.py (qwen edit models spec QE41), loaded by path and only when --seed-edit-model names a
        registry model, so a run without it, a dry run without it and the deploy package never read it."""
        return importlib.machinery.SourceFileLoader("qwen_edit", os.path.join(WS, "qwen_edit.py")).load_module()
    ```
- **QE42.** `main` calls `rc = _resolve_seed_edit(args)` directly after `_resolve_locations` (`:2728-2730`), returning `rc` when non-zero.
- **QE43. `_resolve_seed_edit(args)`** sets `args.seed_edit` to `None` (seed as-is) or `{"qwen_model": ID, "loras": [{"id", "scale"}]}`; rules in order, each `print("Error: <text>", file=sys.stderr)` and return 2:

  | # | Condition | Text |
  |---|---|---|
  | 1 | `seed_edit_loras` given, `seed_edit_model` absent | `--seed-edit-lora needs --seed-edit-model` |
  | 2 | `seed_edit_model` absent | (no error; `args.seed_edit = None`, return 0) |
  | 3 | no `--seed-image` | `--seed-edit-model needs --seed-image` |
  | 4 | `as-is` with any `--seed-edit-lora` | `--seed-edit-lora cannot be combined with --seed-edit-model as-is` |
  | 5 | `as-is` | (no error; `args.seed_edit = None`, return 0) |
  | 6 | `<WS>/qwen_edit.py` is not a file | `--seed-edit-model needs <WS>/qwen_edit.py, which this workspace does not have` |
  | 7 | the value not in `qe.MODEL_IDS` | `--seed-edit-model must be as-is or one of qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-q4, qwen2511-bf16` |
  | 8 | `qe.cli_selection(model, loras, "--seed-edit-model", "--seed-edit-lora")` raises | its text (for example `--seed-edit-lora uncensored is for Qwen-Image-2.1, not Qwen-Image-Edit-2511 q4 (Lightning)`) |
  | 9 | neither `--dry-run` nor `--story-only`, and `qe.selection_problem(id, loras)` is not `None` | `--seed-edit-model <id>: <problem>` (for example `--seed-edit-model qwen21-q8: Qwen-Image-2.1 q8 is unavailable: …(run bin/seed-edit-setup --model qwen21-q8)`) |

  The `--shots` + seed and `--no-stills` + seed refusals stay earlier (`:1185-1189`, `:2701-2705`). Rule 9 runs before the lockfile and Phase 0, so a missing model never costs a story call **[spec choice]**; a dry run reads no weights.

### 7.2 Phase 1c

- **QE44. Sequence.** In `_phase_sequence`, after the redo insertion and before the Phase 0 prefix:
    ```python
    if getattr(args, "seed_edit", None) and phase2_stills in phases:
        cut = phases.index(phase2_stills)
        phases = phases[:cut] + (phase_seed_edit,) + phases[cut:]
    ```
  So the edit runs after Phase 1 and Phase 1b (the story server stopped and `--min-avail-gib` reached) and before Phase 2. `--story-only` never runs it. Without `args.seed_edit` every tuple equals today's (L41).
- **QE45. Files** (in the story directory; `SEED_EDIT_SKILL = "ltx_movie_seed_edit"`, `SEED_EDIT_SCHEMA = "ltx-movie.seed-edit.v1"`):
    ```python
    def _seed_edit_paths(story_dir):
        return {"original": os.path.join(story_dir, "seed-original.png"),
                "edited": os.path.join(story_dir, "seed-edited.png"),
                "record": os.path.join(story_dir, "seed_edit.json"),
                "work": os.path.join(story_dir, "seed_edit_work"),
                "stage": os.path.join(story_dir, "seed_edit_work", "seed-edited.pending.png")}
    ```
  `seed-original.png` is the seed as the pipeline sees it (`ltx_image_fit.load_oriented_rgb`, saved as PNG) **[spec choice]**: it is the edit's source (mflux does not apply EXIF orientation) and the kept original the notes ask for. The file the user passed is never modified.
- **QE46. The prompt** **[spec choice]**: the exact text Phase 2 would render panel 1 from without a seed:
    ```python
    def _panel1_edit_prompt(story_md):
        """Panel 1's Image: text plus the story's Style: text, joined as bin/ltx-story-images joins them, or ""."""
        panels = _load_story_panels(story_md)
        if not panels:
            return ""
        images = importlib.machinery.SourceFileLoader(
            "ltx_story_images_for_movie", os.path.join(WS, "bin", "ltx-story-images")).load_module()
        return images._compose_prompt(panels[0]["image"], images._style_text(panels))
    ```
  (`bin/ltx-story-images` is only read, as `_shots_stills_groups` already does.)
- **QE47. Size.** `_seed_edit_size(args, multiple)` → `(args.video_width // multiple * multiple, args.video_height // multiple * multiple)` with `multiple = qe.multiple(model_id)` (32 for 2.1, 16 for 2511). Phase 0's geometry is a multiple of 64, so today this floor never changes the size (it guards future geometry). Phase 2 then fits the edited image into `panel_01.png` at twice the video size with the existing `fit_letterbox`; the aspect is the video's, so no bar is added (Section 16 item 5).
- **QE48. `phase_seed_edit(args)`**, steps in order:
  1. `qe = _qwen_edit()`; `paths = _story_paths(args.story_id)`; `files = _seed_edit_paths(paths["story_dir"])`; `model_id, loras = args.seed_edit["qwen_model"], args.seed_edit["loras"]`; `label = qe.label(model_id)`; print `=== Phase 1c: seed edit ===`.
  2. `prompt = _panel1_edit_prompt(paths["story_md"])`; empty → stderr `Error: panel 1 of <story.md path> has no Image: description to edit the seed with`, return 1.
  3. `width, height = _seed_edit_size(args, qe.multiple(model_id))`; `source_sha256` = sha256 hex of the `--seed-image` file's bytes.
  4. `key = dict(qe.settings(model_id, loras), source_sha256=…, prompt=prompt, seed=args.image_seed, width=width, height=height)`. If `seed_edit.json` reads (`json.load`; `OSError`/`ValueError` → none) as a dict with `status == "ok"`, `seed-edited.png` exists and every `key` item equals the record's → print `seed edit: reusing <edited path> (same seed image, prompt, seed and settings)`, set `args.seed_edited_path = files["edited"]`, return 0 **[spec choice]** (a rerun after a later-phase failure, the documented recovery path, does not redo the edit).
  5. Write `seed-original.png`; delete `seed-edited.png` and the stage file if present; print `seed edit: <qe.generator_text(model_id, loras)>; <W>x<H>; seed <image_seed>; prompt: panel 1's Image: text (<len> characters)`.
  6. `qe.wait_for_memory(qe.memory_floor(model_id), label, tag="ltx-movie")`, then `results, failure = qe.run_jobs(model_id, loras, [{"n": 1, "seed": args.image_seed, "prompt": prompt, "source": files["original"], "stage_path": files["stage"], "output_path": files["edited"]}], width, height, SEED_EDIT_SKILL, files["work"])`; a `qe.Unavailable` from either sets `failure = str(e)` and `results = None`.
  7. Write `seed_edit.json` atomically (`<path>.tmp`, `json.dump(..., indent=2)`, `os.replace`) with exactly: `schema` (`ltx-movie.seed-edit.v1`), `created` (`time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())`), `status` (`ok` / `blocked` / `failed`), `label`, `source` (absolute path of `--seed-image`), `source_sha256`, `original` (`seed-original.png`), `output` (`seed-edited.png` when ok, else `null`), `prompt`, `seed`, `width`, `height`, `qwen_model`, `loras`, `steps`, `scheduler` (the settings block), `seconds` (the job's, else `null`), `error` (`failure` or `null`).
  8. `failure` → stderr `Error: the seed edit failed: <failure>`, return 1.
  9. `blocked` → stderr `Error: the content screen blocked the edited seed image (<label>) for story <story id>; the movie stops here rather than use an unscreened or unedited panel 1. Change panel 1's Image: line in <story.md path>, or rerun with --seed-edit-model as-is to use the seed unchanged`, return 1. There is no fallback to the unedited seed.
  10. ok → `args.seed_edited_path = files["edited"]`; print `seed edit: <edited path> (<seconds:.1f> s)`; return 0.
- **QE49. Phase 2.** `phase2_stills` (`:2027-2028`) passes `--seed-image` `getattr(args, "seed_edited_path", None) or args.seed_image`. Without an edit the command is unchanged.
- **QE50. Dry run.** Directly after the Redo block (`:2552-2558`), when `args.seed_edit`: print `--- Phase 1c: seed edit ---`, then `Would edit the seed with <generator_text> at <W>x<H> (or <W>x<H> literally when Pillow is not importable), seed <image_seed>, prompted by panel 1's Image: text (and its Style: text) from story.md; every output is screened with content safety (skill ltx_movie_seed_edit); writes <seed-original.png>, <seed-edited.png> and <seed_edit.json> paths. A blocked or failed edit stops the run.`, then an empty line. The Phase 2 dry-run command (`:2570-2571`) passes the `seed-edited.png` path when `args.seed_edit`, else `args.seed_image`. The Phase 0 text is unchanged. The module docstring gains one paragraph: `Seed edit (docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md): --seed-edit-model ID turns the --seed-image into panel 1 with a Qwen registry edit model in Phase 1c (after the story, before the stills), prompted by panel 1's Image: text; the edit is screened, recorded in seed_edit.json and passed to Phase 2 as its --seed-image. Absent, or as-is, the seed is used unchanged.`
- A deployed package without `qwen_edit.py` (Section 0.1) refuses `--seed-edit-model <id>` with rule 6 of QE43; `as-is` and the absent flag work there.

---

## 8. movie-ui library, server and batch (QE51-QE60)

### 8.1 `movie_ui_seedgen.py` and `movie_ui_lib.py`

- **QE51. `seedgen.qwen_selection(model_id, loras, model_key="qwen_model", loras_key="loras")`** → `(model_id, loras, None)` or `(None, None, error)`: `_qwen_fields`' qwen branch (`:133-157`) moved verbatim with two changes: the model text is `"unknown %s %s" % (model_key, model_id)` and both list texts are `"%s must be a list of {id, scale}" % loras_key`. `_qwen_fields(body, model)` keeps its zimage branch and returns `qwen_selection(body.get("qwen_model"), body.get("loras"))` for qwen (identical results and texts; SQT15 holds). Null/absent model → `DEFAULT_QWEN_MODEL`; null/absent loras → that model's `default_loras`; explicit `[]` → none.
- **QE52. Fields and flags.** `DEFAULT_FIELDS` gains `"seed_edit_model": None, "seed_edit_loras": None` directly after `"seed_upload": None`. `FIELD_FLAGS` gains, as its last entry, `("seed_edit", ("--seed-edit-model", "--seed-edit-lora"))` (31 entries). New helper:
    ```python
    def qwen_edit_flags(model_flag, lora_flag, model_id, loras):
        """[model_flag, model_id] then lora_flag ID=SCALE per LoRA, SCALE as repr(float) (qwen edit models QE52)."""
        argv = [model_flag, model_id]
        for lora in loras or []:
            argv += [lora_flag, "%s=%r" % (lora["id"], float(lora["scale"]))]
        return argv
    ```
- **QE53. Argv.**
  - `build_argv`: inside `if fields["seed_upload"]:` after the `--seed-image` pair: `if fields.get("seed_edit_model") is not None: argv += qwen_edit_flags("--seed-edit-model", "--seed-edit-lora", fields["seed_edit_model"], fields.get("seed_edit_loras"))`. Example: `[…, "--fps", "24", "--frames", "145", "--seed-image", <upload path>, "--seed-edit-model", "qwen21-q4", "--seed-edit-lora", "uncensored=1.0", "--model", …]`. `as-is` gives `["--seed-edit-model", "as-is"]` at the same place.
  - `location_argv`: create, after the `--seed` pair and before `--force`; regenerate, after the `--description` pair and before `--force`: `if fields.get("qwen_model") is not None: argv += qwen_edit_flags("--qwen-model", "--lora", fields["qwen_model"], fields.get("loras"))`.
  - `character_argv`: regenerate, after the `--seed` pair; create, after the `--seed` pair and before `--force`: the same.
  - Fields without these keys (every job made before this feature) give today's argv.
- **QE54. V1 rule 12d** (structural; the registry is checked by the server, QE55), `SEED_EDIT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")`, called directly after rule 12c (`:1534`):
    ```python
    def _rule_seed_edit(fields):
        """V1 rule 12d (qwen edit models QE54): the shape of the Compose seed edit fields."""
        model, loras, seed = fields.get("seed_edit_model"), fields.get("seed_edit_loras"), fields.get("seed_upload")
        errors = []
        if not (model is None or (isinstance(model, str) and SEED_EDIT_ID_RE.fullmatch(model))):
            errors.append("seed edit model must be as-is or a Qwen model ID")
        if not (loras is None or (isinstance(loras, list) and len(loras) <= 4 and all(
                isinstance(i, dict) and set(i) == {"id", "scale"} and isinstance(i["id"], str)
                and SEED_EDIT_ID_RE.fullmatch(i["id"]) and _is_number(i["scale"]) for i in loras))):
            errors.append("seed edit LoRAs must be a list of at most 4 {id, scale} items")
        if model is not None and seed is None:
            errors.append("a seed edit model needs a seed image")
        if loras is not None and model in (None, "as-is"):
            errors.append("seed edit LoRAs need a seed edit model other than as-is")
        return errors
    ```
  Rule 18 (`:1563-1567`) already refuses the flags on a workspace whose `bin/ltx-movie --help` lacks them.
- **QE69. Phases.** `PHASE_RE` becomes `r"^=== Phase (\d+[bc]?): (.+?)(?: \(rewrite (\d+) of (\d+)\))? ===$"`. `job_phases` inserts `"1c"` directly after `"1b"` when `kind == "movie"`, `fields.get("seed_upload")` and `fields.get("seed_edit_model") not in (None, "as-is")`; every other result is unchanged.

### 8.2 `movie_ui_server.py`

- **QE55. Shared helper.**
    ```python
    def edit_availability(real, model_id, loras):
        """The 409 text of a Qwen edit selection (seed models SQ31 rules through bin/seed-edit --probe), or None."""
        models, detail = lib.seed_edit_check(real, seedgen.QWEN_MODEL_IDS, seedgen.QWEN_LORA_IDS)
        return seedgen.availability_error(models, detail, {"model": "qwen", "qwen_model": model_id, "loras": loras})
    ```
- **QE56. Forwarding rule** **[spec choice]**: for Compose, Locations and Characters the server validates, checks and forwards only a selection the request names. A request that omits both fields (null or absent) gets no flag: Compose then uses the seed as-is, Locations and Characters the CLI default (`qwen21-q4` + uncensored). The page always sends explicit values (§9). Existing API callers, batch forks of old jobs and every existing server test keep today's argv.
- **QE57. Compose.**
  - `_fields_body`: after `compose_fields`, when `fields["seed_edit_model"]` is neither `None` nor `"as-is"`: `model_id, loras, error = seedgen.qwen_selection(fields["seed_edit_model"], fields["seed_edit_loras"], "seed_edit_model", "seed_edit_loras")`; `error` → `ApiError(400, error)`; else store both cleaned values (null loras → the family defaults, registry order, floats). This covers `/api/preview`, `/api/validate`, `/api/jobs` and `/api/jobs/seed-folder`.
  - 400 texts: `unknown seed_edit_model <v>`, `seed_edit_loras must be a list of {id, scale}`, `unknown LoRA <id>`, `LoRA <id> is listed twice`, `LoRA <id> is for Qwen-Image-2.1, not <model label>`, `LoRA <id> scale must be a number above 0 and at most 2`; the V1 rule 12d texts arrive in the V1 check record as today.
  - 409: `_h_job_create` after `checks_pass`, and `_h_seed_folder` after `validate_request` when not a preview: when `fields["action"] == "movie"`, the seed is set (Compose) or the request is a seed folder, and the model is a registry ID → `edit_availability(...)`; a text → `ApiError(409, text)`, nothing queued. A story-only action never needs the model (Phase 1c does not run).
- **QE58. Locations.**
  - `location_create_errors`, appended rules: `given = body.get("qwen_model") is not None or body.get("loras") is not None`; `given and not photos` → `qwen_model and loras apply only to photo locations`; `given and photos` → `qwen_selection(...)`'s error, if any.
  - `_h_location_create`: when `given and photos`: cleaned `model_id, loras`; when `1 <= len(photos) < 24`, `edit_availability` → 409; `fields` gains `"qwen_model"` and `"loras"` (only then).
  - `_h_location_regenerate`: when `given`: `record = lib.read_json(os.path.join(os.environ.get("LOCATION_LIBRARY_DIR") or os.path.join(real, "generated", "locations"), groups[0], "location.json"))`; `isinstance(record, dict) and record.get("source") == "text"` → error `qwen_model and loras apply only to photo locations`; otherwise `qwen_selection`'s error; then (no errors) the cleaned selection, 409 when the record is a dict with fewer than 24 `photos` or unreadable (the tool decides then), and `fields` gains both keys.
- **QE59. Characters.**
  - `character_create_errors`, appended rules: `given and seed is None` → `qwen_model and loras apply only to seed-image characters`; `given and seed` → `qwen_selection`'s error.
  - `_h_character_create`: `given and seed` → cleaned selection, `edit_availability` → 409, `fields` gains both keys.
  - `_h_character_seed_folder`: before `_character_rows`, when `given`: `qwen_selection(...)`, an error → `ApiError(400, error)`; not a preview → `edit_availability` → 409; each queued job's `fields` gains both keys (the same selection for every seed).
  - `_h_character_regenerate`: when `given`: `record = lib.read_json(<CHARACTER_LIBRARY_DIR or <ws>/generated/characters>/<name>/character.json)`; a dict whose `source.type` is `descriptor` → 400 `qwen_model and loras apply only to seed-image characters`; else `qwen_selection`'s error; then 409 and both keys. Errors use each handler's existing shape (`ApiError(400, "invalid fields", errors=[...])` for create/regenerate, `ApiError(400, text)` for the seed folder).

### 8.3 `movie_ui_batch.py` (QE60)

- **QE60.** `FIELD_LEVELS` gains `"seed_edit_model": "stills", "seed_edit_loras": "stills"` (a new edit needs a new panel 1, and a fork at that level copies `story.md` and re-runs Phases 1c-4). `GROUPS` becomes `(("panels", "length"), ("width", "height", "seed_upload", "seed_edit_model", "seed_edit_loras"))`. In `merge`, the `width`/`height` branch also sets `fork["seed_edit_model"] = fork["seed_edit_loras"] = None`, and a new branch `elif key == "seed_upload" and value is None:` sets the same two keys to `None` (a fork without a seed must not carry an edit, rule 12d). The batch page does not offer the fields (out of scope).

---

## 9. The page (QE61-QE68)

### 9.1 The component

- **QE61.** `app.js` gains one function, `qwenPicker(prefix, asIs)`, defined after `seedModelText` (the order `seedRegistry`, `seedQwenEntry`, `seedLoraEntry`, `seedMultiple` stays, as two node tests slice it). It returns an object with `state`, `key`, `wanted` and the methods `select(model, loras)`, `update()`, `read()`, `render()`, `selection()`, `reason()`, `multiple()`, `listen(onChange)`. It never touches the DOM before `update()`. `readSeedQwen`, `renderSeedQwen` and `seedLoraBody` are removed (absorbed); `seedRegistry`, `seedQwenEntry`, `seedLoraEntry`, `seedMultiple`, `seedModelText` stay. The code (load-bearing; typed as written):

```js
  // Qwen edit models spec QE61: one Qwen edit model + LoRA picker. prefix names its elements:
  // <prefix>-qwen-box, -qwen-model, -steps, -loras, -qwen-note, -lora-<id>, -lora-scale-<id>, -lora-note-<id>.
  // asIs puts "Seed as-is (no edit)" first (Compose). Nothing touches the DOM before update().
  function qwenPicker(prefix, asIs) {
    const p = {state: null, key: "", wanted: null};
    function node(suffix) { return $("#" + prefix + suffix); }
    function rows() { return document.querySelectorAll("#" + prefix + "-loras .se-lora"); }
    function probe(id) {
      const models = capability("seed_edit").models;
      return models && models.qwen.models[id];
    }
    function enabled(id) { return id === "as-is" || !(probe(id) && probe(id).ok === false); }
    function fresh(wanted) {
      const registry = seedRegistry();
      const loras = {};
      registry.loras.forEach(function (l) {
        const listed = wanted && wanted.loras ? wanted.loras.filter(function (w) { return w.id === l.id; })[0] : null;
        loras[l.id] = {checked: wanted && wanted.loras ? Boolean(listed) : l.default_on,
                       scale: String(listed ? listed.scale : l.default_scale)};
      });
      return {model: wanted && wanted.model ? wanted.model : registry.default_model, loras: loras};
    }
    p.select = function (model, loras) {
      p.wanted = {model: model, loras: loras};
      p.state = null;
      p.key = "";
    };
    p.update = function () {
      if (!p.state && seedRegistry()) {
        p.state = fresh(p.wanted);
        p.wanted = null;
      } else {
        p.read();
      }
      p.render();
    };
    p.read = function () {
      if (!p.state) { return; }
      const select = node("-qwen-model");
      if (select.value) { p.state.model = select.value; }
      Array.prototype.forEach.call(rows(), function (row) {
        const id = row.dataset.lora;
        const box = node("-lora-" + id);
        if (!box.disabled) { p.state.loras[id].checked = box.checked; }
        p.state.loras[id].scale = node("-lora-scale-" + id).value;
      });
    };
    p.render = function () {
      const registry = seedRegistry();
      const select = node("-qwen-model");
      if (!registry) {
        clear(select);
        node("-steps").textContent = "checking models…";
        return;
      }
      const cap = capability("seed_edit");
      const models = cap.models;
      const state = p.state;
      function loraProbe(id) { return models && models.qwen.loras[id]; }
      const ids = (asIs ? ["as-is"] : []).concat(registry.models.map(function (m) { return m.id; }));
      if (select.options.length !== ids.length) {
        clear(select);
        ids.forEach(function (id) { select.appendChild(el("option", {value: id})); });
      }
      ids.forEach(function (id, i) {
        const option = select.options[i];
        option.textContent = id === "as-is" ? "Seed as-is (no edit)"
          : seedQwenEntry(id).label + (enabled(id) ? "" : " — unavailable");
        option.disabled = !enabled(id);
      });
      let chosen = state.model;
      if (!enabled(chosen)) {
        const first = registry.models.filter(function (m) { return enabled(m.id); })[0];
        if (enabled(registry.default_model)) { chosen = registry.default_model; }
        else if (first) { chosen = first.id; }
      }
      state.model = chosen;
      select.value = chosen;
      const parts = registry.models.filter(function (m) { return !enabled(m.id); }).map(function (m) {
        return m.label + " — " + probe(m.id).reason;
      });
      node("-qwen-note").textContent = parts.length ? "Unavailable here: " + parts.join("; ") : "";
      if (chosen === "as-is") {
        if (p.key !== "as-is") { p.key = "as-is"; clear(node("-loras")); }
        node("-steps").textContent = "";
        return;
      }
      const entry = seedQwenEntry(chosen);
      const loras = registry.loras.filter(function (l) { return l.family === entry.family; });
      function loraOk(id) { return loraProbe(id) ? loraProbe(id).ok === true : false; }
      function loraNote(l) {
        if (loraOk(l.id)) { return l.license + (l.steps ? "; " + l.steps + " steps, scheduler " + l.scheduler : ""); }
        const found = loraProbe(l.id);
        return "unavailable — " + (found ? found.reason : ((cap.ok === false && cap.reason) || "probing"));
      }
      const key = entry.family + "|" + JSON.stringify(loras.map(function (l) { return [l.id, loraOk(l.id), loraNote(l)]; }));
      if (key !== p.key) {
        p.key = key;
        const box = clear(node("-loras"));
        if (entry.family === "qwen2511") {
          box.appendChild(el("span", {cls: "muted", text: "Lightning 8-step LoRA built in (not selectable)"}));
        }
        else {
          loras.forEach(function (l) {
            const ok = loraOk(l.id);
            const saved = state.loras[l.id];
            const checkbox = el("input", {type: "checkbox", id: prefix + "-lora-" + l.id});
            checkbox.checked = saved.checked && ok;
            checkbox.disabled = !ok;
            const scale = el("input", {type: "number", id: prefix + "-lora-scale-" + l.id, min: "0", max: "2", step: "0.05", value: saved.scale});
            scale.disabled = !ok;
            const note = el("span", {cls: "muted", id: prefix + "-lora-note-" + l.id, text: loraNote(l)});
            box.appendChild(el("div", {cls: "se-lora", data: {lora: l.id}}, [el("label", {}, [checkbox, " " + l.label]),
              el("label", {}, ["strength ", scale]), note]));
          });
        }
      }
      const turbo = loras.filter(function (l) {
        const box = node("-lora-" + l.id);
        return l.steps && box && !box.disabled && box.checked;
      })[0];
      node("-steps").textContent = turbo ? turbo.steps + " steps (turbo)"
        : entry.steps + " steps" + (entry.family === "qwen2511" ? " (Lightning)" : "");
    };
    p.selection = function () {
      if (!p.state) { return null; }
      if (p.state.model === "as-is") { return {model: "as-is", loras: []}; }
      const out = [];
      Array.prototype.forEach.call(rows(), function (row) {
        const id = row.dataset.lora;
        const box = node("-lora-" + id);
        if (!box.disabled && box.checked) { out.push({id: id, scale: Number(node("-lora-scale-" + id).value)}); }
      });
      return {model: p.state.model, loras: out};
    };
    p.reason = function () {
      const cap = capability("seed_edit");
      const models = cap.models;
      if (!p.state) {
        return models ? "Qwen-Image unavailable: the server sent no Qwen model list (restart the movie-ui server)"
          : "checking models…";
      }
      if (p.state.model === "as-is") { return ""; }
      if (!models) { return cap.ok === false ? "cannot check the Qwen edit models: " + cap.reason : "checking models…"; }
      const chosen = seedQwenEntry(p.state.model);
      const found = models.qwen.models[p.state.model];
      if (!(found && found.ok === true)) {
        return (chosen ? chosen.label : p.state.model) + " unavailable: " + ((found && found.reason) || "probing");
      }
      let text = "";
      Array.prototype.forEach.call(rows(), function (row) {
        const id = row.dataset.lora;
        const box = node("-lora-" + id);
        const s = Number(node("-lora-scale-" + id).value);
        if (!text && !box.disabled && box.checked && !(Number.isFinite(s) && s > 0 && s <= 2)) {
          text = "LoRA " + seedLoraEntry(id).label + " strength must be above 0 and at most 2";
        }
      });
      return text;
    };
    p.multiple = function () {
      const entry = p.state ? seedQwenEntry(p.state.model) : null;
      return entry ? entry.multiple : 16;
    };
    p.listen = function (onChange) {
      ["input", "change"].forEach(function (type) { node("-qwen-box").addEventListener(type, onChange); });
    };
    return p;
  }
```

- **QE62. Mounts** (six containers on the four tabs the notes name) **[spec choice]**: the notes' "Regenerate preselects the last-used choice" needs a visible control in the Locations and Characters detail views, so those tabs mount the component twice (create form and Regenerate row). Directly after `S.seeds = …` (`:57`):
    ```js
  // Qwen edit models spec QE62: the picker's mounts.
  const SEED_PICKER = qwenPicker("se", false);
  const LOCATION_PICKER = qwenPicker("lo-cq", false);
  const LOCATION_REGEN_PICKER = qwenPicker("lo-rq", false);
  const CHARACTER_PICKER = qwenPicker("ch-cq", false);
  const CHARACTER_REGEN_PICKER = qwenPicker("ch-rq", false);
  const COMPOSE_PICKER = qwenPicker("c-sq", true);
    ```
  `S.seeds` becomes `{source: null, natural: null, run: null, view: null, rows: {}, busy: false}`; `S` gains `seedOrigin: null` (after `seedUpload: null`).

### 9.2 HTML

- **QE63.** Seeds keeps `#se-qwen-box` exactly (`index.html:178-183`). New blocks, each typed exactly (2-space indentation as the surrounding markup):
  - Locations form, directly after the Photos label (`:318`), inside the grid:
    ```html
    <div id="lo-cq-qwen-box" class="wide" hidden>
      <label>Qwen edit model (photo edits) <select id="lo-cq-qwen-model"></select></label>
      <span id="lo-cq-steps" class="muted"></span>
      <div id="lo-cq-loras" class="se-loras"></div>
      <p id="lo-cq-qwen-note" class="muted"></p>
      <span id="lo-cq-reason" class="muted"></span>
    </div>
    ```
  - Locations detail, directly after the row holding `#lo-regen` (`:330-335`): the same block with prefix `lo-rq` and the label `Qwen edit model for Regenerate`.
  - Characters form, directly after `<ul id="ch-folder-list" …>` (`:279`): prefix `ch-cq`, label `Qwen edit model (seed-image edits)`.
  - Characters detail, directly after the row holding `#ch-regenerate` (`:294-300`): prefix `ch-rq`, label `Qwen edit model for Regenerate`.
  - Compose Resolution fieldset, directly after `<ul id="c-folder-list" …>` (`:89`):
    ```html
      <div data-field="seed_edit" class="wide">
        <div id="c-sq-qwen-box" hidden>
          <label>Panel 1 from the seed <select id="c-sq-qwen-model"></select></label>
          <span id="c-sq-steps" class="muted"></span>
          <div id="c-sq-loras" class="se-loras"></div>
          <p id="c-sq-qwen-note" class="muted"></p>
          <span id="c-sq-reason" class="muted"></span>
        </div>
      </div>
    ```
    `loadOptions`' `[data-field]` gating hides the wrapper when the workspace's `bin/ltx-movie` lacks the flags (`supported.seed_edit === false`).

### 9.3 Wiring

- **QE64. Seeds.** `updateSeedButtons` replaces its first block (`:1927-1934`: `const registry`, the `S.seeds.qwen` initialisation, `readSeedQwen()`, `renderSeedQwen()`) with `SEED_PICKER.update();`; its `qwenReason` block (`:1967-1987`) becomes `let qwenReason = ""; if (model === "qwen" && models) { qwenReason = SEED_PICKER.reason(); }`. `seedMultiple()` → `return $("#se-model").value === "qwen" ? SEED_PICKER.multiple() : 16;`. `seedBody` ends `qwen_model: model === "qwen" ? SEED_PICKER.selection().model : null, loras: model === "qwen" ? SEED_PICKER.selection().loras : null};`. No listener is added (the panel-wide `input`/`change` listener stays, `:2286`). Every Seeds text, ID, title, the Runs cell and Edit-again/workspace-switch persistence behave as before (SQ48-SQ56).
- **QE65. Locations.**
  - `updateLocationButtons` appends:
    ```js
    const photosOn = photos > 0;
    LOCATION_PICKER.update();
    show($("#lo-cq-qwen-box"), photosOn);
    const createReason = photosOn ? LOCATION_PICKER.reason() : "";
    $("#lo-cq-reason").textContent = createReason;
    if (createReason) { $("#lo-create").disabled = true; }
    const photoLocation = Boolean(S.location && S.location.location.source === "photos");
    LOCATION_REGEN_PICKER.update();
    show($("#lo-rq-qwen-box"), photoLocation);
    const regenReason = photoLocation ? LOCATION_REGEN_PICKER.reason() : "";
    $("#lo-rq-reason").textContent = regenReason;
    $("#lo-regen").disabled = Boolean(regenReason);
    ```
  - `openLocation`, before its `updateLocationButtons()`: for a photo location, `const e = loc.edit; LOCATION_REGEN_PICKER.select(e ? e.qwen_model.id : "qwen2511-bf16", e ? e.loras.map(function (l) { return {id: l.id, scale: l.scale}; }) : []);` (a location made before this feature preselects the legacy model).
  - `createLocation`'s body gains `qwen_model: uploads.length ? LOCATION_PICKER.selection().model : null, loras: uploads.length ? LOCATION_PICKER.selection().loras : null`.
  - `#lo-regen`'s body gains, for a photo location, `qwen_model: LOCATION_REGEN_PICKER.selection().model, loras: LOCATION_REGEN_PICKER.selection().loras`. The text-location "Regenerate with this description" body is unchanged.
  - `setupLocations` adds `LOCATION_PICKER.listen(updateLocationButtons); LOCATION_REGEN_PICKER.listen(updateLocationButtons);`.
- **QE66. Characters.**
  - `updateCharacterButtons`, directly after the `status === "dataset"` block (`:2335-2338`):
    ```js
    const seedOn = FOLDER_BOXES.characters.mode() || $("#ch-seed-file").files.length > 0;
    CHARACTER_PICKER.update();
    show($("#ch-cq-qwen-box"), seedOn);
    const createReason = seedOn ? CHARACTER_PICKER.reason() : "";
    $("#ch-cq-reason").textContent = createReason;
    if (createReason) { $("#ch-create").disabled = true; }
    const seedCharacter = Boolean(S.character && S.character.character.source.type === "seed_image");
    CHARACTER_REGEN_PICKER.update();
    show($("#ch-rq-qwen-box"), seedCharacter);
    const regenReason = seedCharacter ? CHARACTER_REGEN_PICKER.reason() : "";
    $("#ch-rq-reason").textContent = regenReason;
    $("#ch-regenerate").disabled = Boolean(regenReason);
    ```
  - `openCharacter`, before `updateCharacterButtons()`: for a seed-image character, the QE65 `select` call with `res.data.character.edit` (legacy → `"qwen2511-bf16"`, `[]`).
  - `createCharacter`: the single-seed body gains `qwen_model: file ? CHARACTER_PICKER.selection().model : null, loras: file ? CHARACTER_PICKER.selection().loras : null`; the folder `openFolderConfirm` base gains `qwen_model: CHARACTER_PICKER.selection().model, loras: CHARACTER_PICKER.selection().loras`.
  - `#ch-regenerate`'s body gains, for a seed-image character, the regenerate picker's `qwen_model` and `loras`.
  - `setupCharacters` adds `CHARACTER_PICKER.listen(updateCharacterButtons); CHARACTER_REGEN_PICKER.listen(updateCharacterButtons); $("#ch-seed-file").addEventListener("change", updateCharacterButtons);`.
- **QE67. Compose.**
    ```js
  function composeSeedEditActive() {
    const supported = (S.options && S.options.supported) || {};
    return supported.seed_edit !== false && $("#c-mode").value === "chained"
      && (($("#c-res-seed").checked && Boolean(S.seedUpload)) || $("#c-res-folder").checked);
  }

  // Qwen edit models spec QE67: a Seeds-tab "Use" seed defaults to as-is, an upload or a seed folder to the
  // registry default (qwen21-q4 + its default LoRAs). The origin is kept in S.seedOrigin.
  function composeSeedDefault(origin) {
    S.seedOrigin = origin;
    if (origin === "seeds") { COMPOSE_PICKER.select("as-is", []); }
    else { COMPOSE_PICKER.select(null, null); }
  }
    ```
  - Callers: `useSeed` after `S.seedUpload = uploadId;` → `composeSeedDefault("seeds");`; `onSeedFile` after a successful upload → `composeSeedDefault("upload");`; `onFolderPick`'s success branch after `box.select();` → `if (box === FOLDER_BOXES.compose) { composeSeedDefault("folder"); }`; `fillCompose` (loading a job's fields) → `S.seedOrigin = "job"; COMPOSE_PICKER.select(f.seed_edit_model || "as-is", f.seed_edit_loras || []);` (a job made before this feature, or with the field omitted, shows as-is, which is what it ran).
  - `updateComposeButtons`, directly after `show($("#c-check-seams-box"), …)`:
    ```js
    COMPOSE_PICKER.update();
    const seedEditOn = composeSeedEditActive();
    show($("#c-sq-qwen-box"), seedEditOn);
    const seedEditReason = seedEditOn ? COMPOSE_PICKER.reason() : "";
    $("#c-sq-reason").textContent = seedEditReason;
    if (seedEditReason) {
      $("#c-run-all").disabled = true;
      const runReason = $("#c-run-all-reason");
      runReason.textContent = runReason.textContent ? runReason.textContent + "; " + seedEditReason : seedEditReason;
    }
    ```
  - `composeFields`: before its `return`, `const seedEdit = composeSeedEditActive() ? COMPOSE_PICKER.selection() : null;`; the returned object gains, after `seed_upload`, `seed_edit_model: seedEdit ? seedEdit.model : null, seed_edit_loras: seedEdit && seedEdit.model !== "as-is" ? seedEdit.loras : null,`. The seed-folder bodies are built from `composeFields` (`:866`, `:874`), so they carry both.
  - `setupCompose` adds `COMPOSE_PICKER.listen(function () { updateComposeButtons(); preview(); });`.
  - `renderBadges` already calls the four tab updaters (`:245-248`), so every mount re-renders on a capability change.
- **QE68.** Every node is built with `el()`/`clear()`, server text goes in through `textContent`; the page bans (`https?://`, `\son[a-z]+=`, `style=`, `alert(`, `confirm(`, `prompt(`, `eval(`, `new Function`) still hold.

---

## 10. Errors and messages

| Condition | Where | Text | Effect |
|---|---|---|---|
| `--lora` without `--qwen-model` | `bin/location`, `bin/character` | `--lora needs --qwen-model` | exit 2, nothing written |
| bad `--qwen-model` | same | `--qwen-model must be one of qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-q4, qwen2511-bf16` | exit 2 |
| bad `--lora` | same | SQ12 rows 12-16 texts (`--lora must be ID=SCALE (got <v>)`, `--lora: unknown LoRA <id>; known: uncensored, viggle-turbo`, `--lora <id> is given twice`, `--lora <id> is for <family>, not <label>`, `--lora <id> scale must be a number above 0 and at most 2`) | exit 2 |
| options on a text location | `bin/location` | `--qwen-model and --lora apply only to photo locations` | exit 2 |
| options on a descriptor character | `bin/character` | `--qwen-model and --lora apply only to seed-image characters` | exit 2 |
| selection not installed / host too small | `bin/location`, `bin/character` | `<label> is unavailable: <reason>` / `LoRA <label> is unavailable: <reason>` (reasons name `bin/seed-edit-setup --model <id>` / `--lora <id>`, or the memory figure) | exit 2 before the lock |
| legacy model not downloaded | same | unchanged `the photo editor …` / `the seed-image editor is not downloaded: …` | exit 2 |
| child fails or times out | Locations, Characters (registry route) | `<label> child exited <c>: <line>; log: <log>` / `<label> child timed out after <t> s; log: <log>` | exit 1 (DatasetError) |
| bad `location.json`/`character.json` `edit` | `location_lib`, `character_lib` | `edit: <QE31 text>`, `edit: only a photo location records an edit model`, `edit: only a seed-image character records an edit model` | load refused |
| Compose option rules | `bin/ltx-movie` | QE43 rows 1-9 | exit 2 before any phase |
| panel 1 has no Image: text | Phase 1c | `panel 1 of <path> has no Image: description to edit the seed with` | exit 1 |
| edit failed / memory wait failed | Phase 1c | `the seed edit failed: <failure or wait text>` | exit 1, `seed_edit.json` status failed |
| edited seed blocked | Phase 1c | QE48 step 9 text | exit 1, `seed_edit.json` status blocked, no Phase 2 |
| server 400 | `/api/jobs`, `/api/preview`, `/api/validate`, `/api/jobs/seed-folder`, `/api/locations[/…/regenerate]`, `/api/characters[/…/regenerate]`, `/api/characters/seed-folder` | QE57-QE59 texts | nothing created |
| server 409 | same (submits only) | SQ31's `<label> is unavailable: <reason>` / `LoRA <label> is unavailable: <reason>` / `cannot check the seed models: <detail>` | nothing created |

---

## 11. Tests

### 11.1 Rules

- No test loads a real model, uses the real HOME, runs `bin/seed-edit-setup`, renders, downloads, or contacts a server other than the in-test `127.0.0.1` one; none touches port 8177 or 8178. Every test sets `HOME`, `HF_HOME`, `Z_IMAGE_HF_HOME` under `tmp_path`, removes `HF_HUB_CACHE` and every `SEED_EDIT_*` variable (the [SQ] §9.1 rules).
- Process boundaries are stubbed as in `tests/test_seed_edit_tool.py`: the mflux child through `SEED_EDIT_MFLUX_PYTHON` (its `MFLUX_STUB`, extended to record each job's `prompt`/`source`), the legacy child through `SEED_EDIT_QWENEDIT_SCRIPT` (its `QWENEDIT_STUB`), `content_safety` through a `sys.modules` fake whose `assert_image_safe` blocks a pure-red top-left pixel and records `(skill, prompt, size)`.
- The new files `tests/test_qwen_edit.py`, `tests/test_ltx_movie_seed_edit.py`, `tests/test_movie_ui_qwen_edit.py` are added to `NEW_PY` and follow its scan: bin scripts are loaded with `SourceFileLoader` + `spec_from_loader` + `module_from_spec` + `exec_module` (never `load_module(`), no `urllib`.
- No check is added to `tests/test_ltx_movie_offline.py` (QEK2); the Compose tests are pytest tests in `tests/test_ltx_movie_seed_edit.py`.
- **QE70.** `NEW_PY` (`tests/test_movie_ui_builder.py:213-218`) gains, after `"tests/test_movie_ui_seedgen.py"`, the entries `"qwen_edit.py"`, `"tests/test_qwen_edit.py"`, `"tests/test_ltx_movie_seed_edit.py"`, `"tests/test_movie_ui_qwen_edit.py"` (so `NEW_PY[:2]` is unchanged and `test_mut25` compiles and scans them on `/usr/bin/python3` and the venv python).
- `MFLUX_STUB` gains one config key, `"silent"`: a list of job numbers whose `seed-edit-child done` line it does not print (it still writes their image), for QET6's "exited 0 without finishing" case; and its `calls.jsonl` record keeps the whole spec (it already does), so the per-job `prompt`/`source` are visible.

### 11.2 New tests

`tests/test_qwen_edit.py` (`import qwen_edit as qe`; stubs and fakes as §11.1):

| ID | Covers | Test |
|---|---|---|
| QET1 | QE10 | `cli_selection`: `(None, None)` → `("qwen21-q4", [{"id": "uncensored", "scale": 1.0}])`; `("qwen21-q8", None)` → `("qwen21-q8", [])`; `("qwen21-q4", ["viggle-turbo=0.5", "uncensored=1"])` → registry order; `(None, ["uncensored=1"])` → `--lora needs --qwen-model`; every SQ12 row 11-16 text with `--qwen-model`/`--lora` and again with `--seed-edit-model`/`--seed-edit-lora` |
| QET2 | QE9-QE12 | `generator_text` for the four §2.3 examples exactly; `label`, `multiple`, `memory_floor` per entry; `install_problem` absent model / absent LoRA texts (pinned caches as SQT3); `selection_problem` at `total_gib` 16 for `qwen21-q4` → `Qwen-Image-2.1 q4 is unavailable: needs a host with at least 20 GiB of memory (this host has 16.0 GiB)`; installed at 48 → `None` |
| QET3 | QE11 | `child_timeout(n)` for n = 1, 4, 6, 7, 18, 23, 24 → 3600, 3600, 3600, 4200, 10800, 13800, 14400 |
| QET4 | QE13-QE15 | `run_jobs("qwen21-q4", uncensored 1.0, 3 jobs with three different prompts and two sources)` against the mflux stub: argv `[py, <WS>/seed_edit_mflux_child.py, "--spec", <work>/mflux_spec.json]`; the spec equals the QE14 dict exactly (per-job `prompt`/`source`, no spec-level ones, pinned snapshot paths); the child env has neither token key (dummy tokens set in `os.environ`), `HF_HUB_DISABLE_IMPLICIT_TOKEN == "1"`, `HF_HUB_OFFLINE == "1"` (no assert prints the env) |
| QET5 | QE13, QE14 | screening: job 2 drawn red → the fake screen saw exactly 3 calls, each with the caller's skill (`location_edit`) and that job's prompt; results `ok, blocked, ok`; job 2's stage and output absent; `on_result` called 3 times in completion order with files already in place; ok stages gone |
| QET6 | QE13 | failures: stub `fail_after 1` → failure `Qwen-Image-2.1 q4 child exited 1: boom`, results `ok, failed, failed`; `CHILD_TIMEOUT_S = 1`, `JOB_TIMEOUT_S = 0`, stub sleeps 30 → `… child timed out after 1 s` in < 20 s and `qe.CHILD is None`; the stub with `{"silent": [2]}` → `… child exited 0 without finishing job 2` (and `noun="candidate"` → `… candidate 2`) |
| QET7 | QE4, QE14, QE16 | `qwen2511-bf16` (avail 70, `bf16_cache`): argv `[sys.executable, <stub>, "qwenedit", "--spec", <work>/qwenedit_spec.json]`; spec dict exactly (skill, `report_path`, per-job `image` only on jobs whose source differs from job 1's); env `PYTHONUNBUFFERED == "1"`; a `blocked` line → no output, status blocked; the parent's fake screen is never called |
| QET8 | QE8, QE11 | a spy on `qe.run_child` receives `timeout_s == child_timeout(len(jobs))` and the given `log_path`; with `log_path` set, every child line is appended to that file |
| QET9 | QE7 | `wait_for_memory(20, "Qwen-Image-2.1 q4", tag="ltx-movie")` with `avail_gib` 10, `AVAIL_WAIT_S` 0 → prints `ltx-movie: waiting up to 0 s for 20 GiB available (now 10.0 GiB)` and raises `Unavailable("only 10.0 GiB available after waiting 0 s; Qwen-Image-2.1 q4 needs 20 GiB; free memory and retry")` |
| QET10 | QE17, QE18 | the child in-process with SQT8's fakes: a new-shape qwen21 spec with two jobs of different prompt/source → `generate_image` kwargs carry each job's `prompt` and `image_paths == [its source]`; the old shape (spec-level `prompt`/`source`, jobs without) → every call uses the spec-level values, exactly SQT8's kwargs |
| QET11 | QE1, QE70 | `qwen_edit.py`'s top-level imports equal the QE1 list; `python -X importtime -c "import qwen_edit"` (cwd `WS`) imports none of `torch, PIL, psutil, diffusers, transformers, content_safety, character_dataset, z_image_skill`; `NEW_PY` lists the four new files |

`tests/test_seed_edit_tool.py` (in addition to §11.3):

| ID | Covers | Test |
|---|---|---|
| QET12 | QE19-QE23, QEK3 | parametrized over SQT5's five cases plus `qwen2511-bf16`: `run.json` (minus `created` and seconds), the candidate files and the stdout lines (seconds masked) are equal to the values SQT5/SGT11 pin today; the mflux spec equals SQT5's dict with `prompt`/`source` moved into every job; `bin/seed-edit` source has no `def run_child(`, `def weights_problem(`, `CHILD_TIMEOUT_S`, `import subprocess`, `import threading` |

`tests/test_location_dataset.py`, `tests/test_location_lib.py`, `tests/test_location_tool.py`:

| ID | Covers | Test |
|---|---|---|
| QET13 | QE25, QE27-QE30 | a 2-photo create without options (`_Fakes`, QE34 faked to `None`): the one child spec has `"edit": {"qwen_model": "qwen21-q4", "loras": [{"id": "uncensored", "scale": 1.0}]}`, `skill "location_edit"`, per-job `image`; `location.json["edit"] == qwen_edit.settings("qwen21-q4", …)`; the manifest's `generator` is the §2.3 text and `edit` follows it; the fake `wait_for_avail` saw floor 20.0; stdout has the `edit model: …` line. With `qwen_model="qwen2511-bf16"`: the spec's `edit` names it, the generator is today's string, the floor 64.0 |
| QET14 | QE25 | text create with `qwen_model="qwen21-q4"` and with `lora=["uncensored=1"]` → exit 2, `Error: --qwen-model and --lora apply only to photo locations`, no directory; text regenerate with options → the same, `location.json` untouched; photo create with `lora` only → `--lora needs --qwen-model`; `qwen_model="flux"` → the QE10 text |
| QET15 | QE31 | `validate_location`: a photo record with a valid `edit` round-trips through `write_location`/`load_location`; a record without `edit` loads; each `_edit_problem` text for one bad shape per rule (not a dict, missing key, bad `qwen_model`, bad lora item, scale 0 and 2.5, steps 0, scheduler `""`); a text record with `edit` → `edit: only a photo location records an edit model`; `_edit_problem`'s code (SQT18's `_code_of`) is identical in `location_lib.py` and `character_lib.py` |
| QET16 | QE25, QE27 | regenerate: a legacy photo location (no `edit`) regenerated with `qwen_model="qwen21-q8"` records `qwen21-q8` under the lock with the seed; without options it records the registry default; with `qwen2511-bf16` the child spec's legacy keys equal today's and `edit` names `qwen2511-bf16` |
| QET17 | QE28 | a top-up run (LYD's `rounds`/`skip_n` pattern): every child spec of rounds 1-3 carries the same `edit` |
| QET18 | QE33 | `character_dataset.run_edit_child` routing with `qwen_edit.run_jobs` and `run_logged` replaced by recorders: a spec without `edit` and one with `qwen2511-bf16` → `run_logged` with the qwenedit argv and a spec file without an `edit` key, byte-equal to today's; `qwen21-q4` → `run_jobs(…)` with jobs `{n, seed, prompt, source = job image or spec image, stage_path = <stem>.pending.png, output_path}`, size 1024×640, the spec's skill (default `character_edit`), work dir = the log stem, `log_path` = the `.log`; returns the report shape; a failure → `DatasetError("<failure>; log: <log>")` with `.log_path`; `qwen_edit.Unavailable` → `DatasetError(<text>)` |
| QET19 | QE24 | `bin/location --help`'s create usage names `--qwen-model ID` and `--lora ID=SCALE`; the parser yields `qwen_model`/`lora` |

`tests/test_character_tool.py`, `tests/test_character_lib.py`, `tests/test_character_dataset.py`:

| ID | Covers | Test |
|---|---|---|
| QET20 | QE36, QE37 | a seed-image create (`--no-review`, `_Fakes`, QE34 faked): the child spec's `edit` is the registry default; `character.json["edit"]` the settings block; manifest generator and `edit`; floor 20.0 passed to `wait_for_avail`; with `--qwen-model qwen2511-bf16` the legacy editor check (`edit_models_missing`) is the one consulted and the generator is today's string |
| QET21 | QE36 | descriptor create and regenerate with `--qwen-model qwen21-q4` → exit 2 with the SEED_ONLY text, nothing created or rewritten; `--lora uncensored=1` alone → `--lora needs --qwen-model` |
| QET22 | QE36, QE39 | a seed character created with `qwen21-q4`, then `--regenerate --new-seed --qwen-model qwen21-q8 --lora uncensored=0.5`: `character.json` (outside `dataset/`) keeps an `edit` naming `qwen21-q8` after `dataset/` was wiped and rebuilt; `dataset/description.json` kept; a regenerate with no options and the same seed rewrites `edit` to the registry default (seed line `seed: N (unchanged)`) |
| QET23 | QE38 | `validate_character`: optional `edit` round-trips; a record without it loads; a descriptor record with `edit` → `edit: only a seed-image character records an edit model`; the QE31 bad shapes give the `edit: …` texts |
| QET24 | QE37 | `train --stills` on a seed character with `edit` qwen21-q4: `run_zimage_child` is called for `test-stills-lora` and `test-stills-control` exactly as today and a `qwen_edit.run_jobs` recorder is never called |
| QET25 | QE35 | `busy_process` with a fake `psutil.process_iter`: cmdlines `[py, "/w/seed_edit_mflux_child.py", "--spec", "s"]` and `[py, "/w/bin/seed-edit", "--source", …]` are busy; `[py, "/w/bin/seed-edit", "--probe"]` and `[py, "/w/bin/seed-edit-setup"]` are not; every marker that was busy before still is |

`tests/test_ltx_movie_seed_edit.py` (bin/ltx-movie loaded per §11.1 as `ltx_movie_qe`; `_story_dir` patched to `tmp_path/stories/<id>`; `_qwen_edit` patched to return a fake module exposing `MODEL_IDS`, the real `cli_selection`, `SelectionError`, `Unavailable`, `settings`, `label`, `multiple`, `memory_floor`, `generator_text` from the real `qwen_edit`, and recorders for `selection_problem`, `wait_for_memory`, `run_jobs`):

| ID | Covers | Test |
|---|---|---|
| QET26 | QE40-QE44, QEK4 | parser: both flags exist with `--seed-edit-lora` repeatable; `_resolve_seed_edit` for each QE43 row (exact texts; row 9 only outside `--dry-run`/`--story-only`); absent and `as-is` → `args.seed_edit is None`; for L41's eight argument sets `_phase_sequence` is unchanged with `seed_edit = None` |
| QET27 | QE44 | with `seed_edit` set and a seed: `(phase0_seed, phase1_story, phase_release_story_server, phase_seed_edit, phase2_stills, phase3_manifest, phase4_render)`, and without the release `(phase0_seed, phase1_story, phase_seed_edit, phase2_stills, …)`; `story_only` → `(phase0_seed, phase1_story)` |
| QET28 | QE45-QE49 | `phase_seed_edit` on a story.md whose panel 1 has `Image:` and a `Style:` line, `video_width/height` 704×448, `image_seed` 3, `qwen21-q4`: `run_jobs` got one job `{n 1, seed 3, prompt == _compose_prompt(Image, Style), source = seed-original.png, stage_path, output_path = seed-edited.png}`, size 704×448, skill `ltx_movie_seed_edit`, work `seed_edit_work`; `wait_for_memory(20.0, "Qwen-Image-2.1 q4", tag="ltx-movie")`; `seed-original.png` is the oriented seed; `seed_edit.json` has exactly the QE48 keys with status ok; `phase2_stills` (with `subprocess.run` recorded) passes `--seed-image <seed-edited.png>`; with `qwen2511-q4` and a 720×448 geometry the size floors to 720×448 (16) and with `qwen21-q4` to 704×448 (32) |
| QET29 | QE48 step 9 | the fake `run_jobs` returns `blocked` → return 1, the exact stderr text, `seed_edit.json` status blocked with `output` null, no `seed-edited.png`, and the phase loop stops before Phase 2; a failure text → `Error: the seed edit failed: <text>`, status failed |
| QET30 | QE48 step 4 | a second call with the same inputs reuses (no `run_jobs` call, the reuse line); changing the seed file bytes, the prompt, `image_seed`, the model or a LoRA scale each re-runs the edit |
| QET31 | QE50, QEK4 | `main([... "--seed-image", png, "--dry-run", "--no-review"])` output is byte-identical with no flag and with `--seed-edit-model as-is`; with `--seed-edit-model qwen21-q4` it adds the Phase 1c block after Phase 1b and the Phase 2 command's `--seed-image` is `<story>/seed-edited.png`; no weights are read (the `selection_problem` recorder is not called) |
| QET32 | QE43 row 6 | with `os.path.isfile` reporting `qwen_edit.py` absent, `--seed-edit-model qwen21-q4` exits 2 with the row-6 text; `as-is` still runs the dry run |

`tests/test_movie_ui_qwen_edit.py` (the in-test server and stub workspace of `tests/movie_ui_testutil.py`; `lib.seed_edit_check` replaced with a recorder returning SQ18-shaped models):

| ID | Covers | Test |
|---|---|---|
| QET33 | QE52-QE54, QE69 | `DEFAULT_FIELDS` has both keys (`None`); `FIELD_FLAGS[-1] == ("seed_edit", ("--seed-edit-model", "--seed-edit-lora"))` and 31 entries; `build_argv` places the flags right after `--seed-image` and only with a seed; `as-is` → `--seed-edit-model as-is`; `location_argv`/`character_argv` exact lists with and without `qwen_model`; each rule 12d text; `job_phases("movie", {seed, seed_edit_model "qwen21-q4"}) == ["0", "1", "1b", "1c", "2", "3", "4"]`; `PHASE_RE` matches `=== Phase 1c: seed edit ===` |
| QET34 | QE56, QE57 | Compose over HTTP: each 400 text (preview and job create); `as-is` and omitted → 201 with no or `as-is` flags and no probe call; a registry model with the probe saying unavailable → 409 `Qwen-Image-2.1 q8 is unavailable: <reason>`, nothing queued; `action "story"` with a model → 201 without a probe call; seed folder: 409 once before any row, preview 200 without a probe |
| QET35 | QE58 | Locations: photo create without fields → today's argv (no probe); with `{qwen_model: "qwen21-q4", loras: [{id: "uncensored", scale: 0.5}]}` → argv ends `--qwen-model qwen21-q4 --lora uncensored=0.5` and fields gain both keys; text create with fields → 400 `qwen_model and loras apply only to photo locations`; unavailable → 409; regenerate of a text record with fields → 400; of a photo record → flags; omitted → today's argv |
| QET36 | QE59 | Characters: create with a seed and fields → flags, 409 when unavailable; descriptor + fields → 400 SEED_ONLY text; seed folder with fields → every queued job's fields and argv carry the same selection, and without fields the SD pin `set(fields) == {…}` holds; regenerate of a descriptor record with fields → 400 |
| QET37 | QE60 | batch: `set(FIELD_LEVELS) | set(FIXED_KEYS) == set(DEFAULT_FIELDS)`, `(27, 5, 32)`; both new keys at `stills`; `GROUPS`; `merge` with a `width` variant, and with `seed_upload: None`, clears both keys |
| QET38 | QE61-QE63, QE68 | static page: the 30 new IDs (`<p>-qwen-box`, `<p>-qwen-model`, `<p>-steps`, `<p>-loras`, `<p>-qwen-note`, `<p>-reason` for `<p>` in `lo-cq`, `lo-rq`, `ch-cq`, `ch-rq`, `c-sq`) appear once each in `index.html`, and `id="c-sq-qwen-box"` sits inside the `<div data-field="seed_edit" class="wide">` wrapper; the Seeds block is unchanged (SQT22's `QWEN_BOX`); `app.js` defines `function qwenPicker(prefix, asIs) {` once and contains `"Seed as-is (no edit)"` and the six `const …_PICKER = qwenPicker(` lines of QE62; the page bans; `node --check app.js` when node exists |
| QET39 | QE67 | `app.js` contains `composeSeedDefault("seeds");` inside `useSeed`, `composeSeedDefault("upload");` inside `onSeedFile`, `composeSeedDefault("folder")` inside `onFolderPick`, `COMPOSE_PICKER.select(f.seed_edit_model || "as-is", f.seed_edit_loras || []);` inside `fillCompose`, and the two `composeFields` lines of QE67 |

The picker's behaviour in a browser is covered by the §11.4 browser check, not by a pytest DOM fake.

### 11.3 Existing tests to change (in the tests commit; not `test_mut26`)

| Test | Exact edit |
|---|---|
| `tests/test_seed_edit_tool.py` `env` fixture | `qe = tool.qe`; `avail_gib`, `total_gib`, `missing_modules` are patched on `qe`; `disk_free_gib`, `cpu_generator` stay on `tool`; the returned dict gains `"qe": qe` |
| same file, every other use of a moved name | each `setattr(tool, NAME, …)` and `tool.NAME` with NAME in {`avail_gib`, `total_gib`, `missing_modules`, `AVAIL_WAIT_S`, `CHILD_TIMEOUT_S`, `CHILD`, `run_child`, `weights_problem`, `lora_problem`, `mflux_env_problem`, `qwen_model_problem`, `qwen_hubs`, `MFLUX_MIN_VERSION`, `EDIT_MODEL`, `EDIT_LORA_REPO`, `EDIT_LORA_FILE`, `EDIT_STEPS`, `EDIT_TRUE_CFG`} uses `qe` (`bf16_cache`, SGT7, SGT10, SGT11, SGT13, SGT14, SQT3-SQT7, SQT10, review focus 4, `test_sq_final_b_no_token_reaches_the_mflux_child`) |
| SQT3 env-var grep | reads `qwen_edit.py` (same four names); a second assert: `bin/seed-edit` source reads no `os.environ` name |
| SQT5, SGT9, review focus 1 and 3 spec dicts | drop spec-level `prompt`/`source`; every job gains `"prompt": PROMPT` (or the review's prompt) and `"source": <work>/source.png` |
| SGT10 timeout case | also `env["mp"].setattr(qe, "JOB_TIMEOUT_S", 0)`; the text stays `… timed out after 1 s`; `qe.CHILD is None` |
| `test_sq_final_b_no_token_reaches_the_mflux_child` | the spy is `def spy(argv, child_env, on_line, timeout_s, log_path=None)` on `qe.run_child` and passes all arguments through |
| `tests/test_movie_ui_seedgen.py` SQT18 | `tool` source is `qwen_edit.py` (the five functions compared with `bin/seed-edit-setup`) |
| SGT34 | the `bin/seed-edit` import list is QE19's |
| SGT33 `SEED_FUNCTIONS` | drop `renderSeedQwen`, `readSeedQwen`, `seedLoraBody` |
| SQT22 `QWEN_JS_TEXTS` | `'"se-lora-scale-"'` → `'prefix + "-lora-scale-"'`; `'"se-lora-note-"'` → `'prefix + "-lora-note-"'`; `qwen_model: model === "qwen" ? S.seeds.qwen.model : null` → `qwen_model: model === "qwen" ? SEED_PICKER.selection().model : null`; `loras: model === "qwen" ? seedLoraBody() : null` → `loras: model === "qwen" ? SEED_PICKER.selection().loras : null`; the `S.seeds = {…}` line → QE62's; the other texts stay |
| `test_sq_final_d_e_f_page_guards` | the item E block is replaced by two texts: `'      if (!p.state) {\n        return models ? "Qwen-Image unavailable: the server sent no Qwen model list (restart the movie-ui server)"\n'` and `'let qwenReason = ""; if (model === "qwen" && models) { qwenReason = SEED_PICKER.reason(); }'` (QE64's line); the `cap/models/state` block → `'      const cap = capability("seed_edit");\n      const models = cap.models;\n      const state = p.state;\n'`; the note line → `'const note = el("span", {cls: "muted", id: prefix + "-lora-note-" + l.id, text: loraNote(l)});'`; the other four texts and both node runs stay |
| `tests/test_location_dataset.py` `_Fakes` | adds `monkeypatch.setattr(character_dataset, "edit_selection_problem", lambda model_id, loras: None)` |
| `tests/test_character_tool.py` `_Fakes`, `tests/test_location_tool.py` fakes (`:60-61`) | the same line |
| `tests/test_location_dataset.py` old-mill block (`:650-654`) | expects `qwen_edit.generator_text("qwen21-q4", [{"id": "uncensored", "scale": 1.0}])` |
| `tests/test_character_tool.py` K19 (`:535`) | `manifest["generator"] == qwen_edit.generator_text("qwen21-q4", [{"id": "uncensored", "scale": 1.0}])` |
| `tests/test_location_ui.py:267`, `tests/test_movie_ui_builder.py:137` | 30 → 31 |
| `tests/test_movie_ui_batch.py:78` and `EXPECTED_LEVELS` | `(27, 5, 32)`; `EXPECTED_LEVELS` gains the two `stills` keys |
| `tests/test_movie_ui_builder.py` `NEW_PY` | gains `"qwen_edit.py"`, `"tests/test_qwen_edit.py"`, `"tests/test_ltx_movie_seed_edit.py"`, `"tests/test_movie_ui_qwen_edit.py"` (after the seed files) |

The QE64 `qwenReason` line in the d/e/f row is typed once, exactly as QE64 gives it. No other existing test changes; a test that fails for any other reason is a defect in the implementation, not in the test.

### 11.4 Browser check (before the merge; not pytest)

[SQ] §9.5's throwaway demo under `$S/qemdemo/` with the same stub probe (`qwen21-q4`, `qwen2511-q4`, `uncensored` ok; `qwen21-q8` not installed; `qwen21-bf16`, `qwen2511-bf16` memory texts; `viggle-turbo` not installed) plus a stub `bin/ltx-movie --help` that lists the two flags and one demo photo location (with `edit` qwen21-q4 + uncensored 0.5), one legacy photo location (no `edit`), one seed-image character with `edit` qwen21-q4. Pass when:
1. Seeds: [SQ] §9.5 cases 1-8 still pass.
2. Locations: choosing photos shows the create picker at `Qwen-Image-2.1 q4`, Uncensored at 1, `40 steps`; Create queues a job whose command ends `--qwen-model qwen21-q4 --lora uncensored=1.0`. Opening the demo location shows the Regenerate picker at q4 + Uncensored 0.5. Opening the legacy location preselects `qwen2511-bf16`; this stub probe disables that entry, so the picker shows SQ51's fallback `Qwen-Image-2.1 q4` with Uncensored unchecked (the preselection listed no LoRA) and an empty reason line. A text location shows no picker.
3. Characters: choosing a seed file shows the create picker; folder mode shows it too; the character detail preselects q4 + uncensored 1; a descriptor character shows no regenerate picker.
4. Compose: after Seeds → Use, the picker shows `Seed as-is (no edit)` and the preview command has `--seed-edit-model as-is`; after a file upload it shows `Qwen-Image-2.1 q4` + Uncensored and the command has `--seed-edit-model qwen21-q4 --seed-edit-lora uncensored=1.0`; choosing `Qwen-Image-2.1 q8 — unavailable` is impossible; shots mode or Size hides the picker; with the stub help lacking the flags the picker is hidden and the command has no seed-edit flag.
5. The browser console shows no error.

---

## 12. Live checks on macstudio (run by the user; the agent has no access)

Preparation (M0): on macstudio, check out `qwen-edit-models`; `bin/seed-edit-setup --model qwen21-q4 --lora uncensored` (and, for L4, the same on the 48 GB Mac); the `qwen2511-bf16` side needs the full `Qwen/Qwen-Image-Edit-2511` weights and the Lightning file in the default HF cache (`hf download Qwen/Qwen-Image-Edit-2511`; `hf download lightx2v/Qwen-Image-Edit-2511-Lightning Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors`). Until a row is run it is recorded "not run (awaiting the user)".

| Row | Steps | Record | Pass |
|---|---|---|---|
| L1 | the NYC subway photo location (1 photo, 23 edits), twice with the same photo, description and seed: `bin/location create subway-21 --photo P --description D --seed 0 --qwen-model qwen21-q4 --lora uncensored=1` and `… subway-2511 … --qwen-model qwen2511-bf16` | for each: stills kept of 24 and edits kept of 23 (manifest), top-up rounds run, seconds per still (the `seed-edit-child done` lines for 2.1; the `loc_NN.png ok <s>s` lines for 2511), the highest `mlx peak memory` line (2.1; 2511 bf16: not measured), wall-clock | QEK6: 2.1 kept ≥ 2511 kept and 2.1 rounds ≤ 2511 rounds |
| L2 | one seed-image character twice (same seed image, phrase, seed, `--no-review`): `--qwen-model qwen21-q4 --lora uncensored=1` vs `--qwen-model qwen2511-bf16`; then `bin/character train <name> --stills` for both and one 3-panel shots movie per character with the same narrative and seed | identity pass rate = kept edits / 24 for each; the two stills-LoRA sample images; a one-line judgment per movie panel | QEK7: 2.1 pass rate ≥ 2511 pass rate |
| L3 | Compose in the movie-ui: (a) upload a seed photo of a person, keep the default (`qwen21-q4` + uncensored), Run all; (b) a Seeds-tab candidate → Use → keep `Seed as-is (no edit)`, Run all | (a) `seed_edit.json` (status, seconds, prompt), `seed-original.png` vs `seed-edited.png` vs `images/panel_01.png`; (b) no `seed_edit.json`, the Phase 2 log line names the original seed | QEK8: the user judges (a) follows panel 1's description while keeping the person and look; (b) is the seed unchanged |
| L4 (optional) | on the 48 GB Mac: a photo location with `qwen21-q4`; then the Locations form with `qwen2511-bf16` selected | the job result; the picker's `— unavailable` reason | q4 runs to `dataset`/`untrained`; 2511 bf16 is unselectable with `needs a host with at least 64 GiB of memory (this host has 48.0 GiB)` |

---

## 13. Pass bar, rollout and the pinned-file baseline

### 13.1 Gate

1. Snapshot `WS` (house rule): `tar czf $S/snapshot-pre-qem-a62d477.tgz` excluding `generated/`.
2. `df -g` shows ≥ 20 GiB free on the disk holding `WS` (QEK9).
3. Record the full-suite counts at `a62d477` (`python3 -m pytest tests/ -q -rA`).
4. After the commits of 13.2: `python3 -m pytest tests/ -q -rA` from `WS` fails only `test_d2_copied_literals_match_the_spike` and `test_rst62_import_sets` (QEK1); `python3 tests/test_ltx_movie_offline.py` prints `OK 347/347` (QEK2).
5. The browser check (§11.4) passes; an Opus design review of the diff against this spec is clean.
6. L1-L3 pass once the user runs them; push and merge only on the user's go.

### 13.2 Commits (in order)

1. **Feature commit(s):** D1-D15 (including the four pinned files). `test_mut26` fails from here until commit 3 (expected; precedent).
2. **Tests commit:** D16 (new tests and the §11.3 edits, including `NEW_PY`), never `test_mut26`.
3. **Baseline commit (test-only, D17):** only `tests/test_movie_ui_builder.py`'s `test_mut26`, per 13.3.

### 13.3 `test_mut26` re-baseline

1. After every commit that touches a `PIPELINE_FILES` member has landed, take `S = git rev-parse HEAD` (40 hex digits) and check `git diff --quiet S -- <PIPELINE_FILES>` (exit 0) and that the only pinned files changed since `a62d477` are `bin/character`, `bin/ltx-movie`, `character_dataset.py`, `character_lib.py` (`git diff --name-only a62d477 S -- <PIPELINE_FILES>`).
2. Set `BASELINE = "<S>"` and extend the comment's last clause: `… then to 38005c3bfee25daf73da231692609fc0b8d25892 (chained end frames), then to <S> (qwen-edit-models).` (the final period moves to after the new clause). Nothing else in the file changes in this commit.
3. Commit with only that file staged. If a later fix touches a pinned file, add a new test-only baseline commit the same way (never amend).
4. `scripts/deploy/build_pkg.py` needs no change (Section 0.1).

### 13.4 Amended requirements of earlier specs

| Item | Status |
|---|---|
| [SQ] SQ13, SQ15-SQ17, SQ21-SQ23 (where the code lives) | amended: the functions live in `qwen_edit.py` (QE6-QE14); texts and behaviour unchanged |
| [SQ] SQ23 (mflux spec shape) | amended by QE14 (per-job `prompt`/`source`) |
| [SG] SG21 (fixed 3600 s child timer) | amended by QE11 (`max(3600, 600 × n)`; 3600 for every Seeds run) |
| [SQ] SQ28 (child body) | amended by QE17 |
| [SQ] SQ50-SQ53 (Seeds picker functions) | amended by QE61, QE64 (one component; same texts and behaviour) |
| [LOC] 2.6, 2.9, 2.10, [LY] LY12 (edit model, floor, manifest) | amended by QE25-QE30 |
| [CSE] E2-E7 (the 2511 editor for every seed dataset) | amended by QE33-QE37 (registry selection; 2511 bf16 as the legacy choice) |
| character library spec 4.12 (busy markers) | amended by QE35 |
| movie-ui MU37 (`FIELD_FLAGS`), MU36 (`DEFAULT_FIELDS`), MU56 phases | amended by QE52, QE69 |
| batch forks BF4 (levels) | amended by QE60 |

---

## 14. Security

- **No Hugging Face token in a child.** Every mflux child (Seeds, Locations, Characters, Compose) is started by `qwen_edit.run_jobs` with `seedgen.hf_child_env(os.environ, PYTHONUNBUFFERED="1", HF_HUB_OFFLINE="1")`: no `HF_TOKEN`, no `HUGGING_FACE_HUB_TOKEN`, `HF_HUB_DISABLE_IMPLICIT_TOKEN=1`, offline. QET4 pins it with dummy token values and never prints an env. The diffusers child keeps today's environment ([SQ] §14a item B left it unchanged; it loads with `local_files_only=True`).
- **Content safety always.** Every output of every registry model passes `content_safety.assert_image_safe` before it gets its final name: in the parent for mflux (skill `seed_edit`, `location_edit`, `character_edit` or `ltx_movie_seed_edit`, prompt = the job's prompt), in the legacy child with the spec's skill. No field, option, environment variable or LoRA turns it off. A blocked file is deleted; a blocked Compose seed fails the job with no fallback (QE48).
- **Fixed registry, local files.** Only registry IDs reach any tool; every model path is a pinned local snapshot and every LoRA a pinned local file; `bake_lora=False`; no free-form repo ID or path anywhere (V1 rule 12d and `qwen_selection` refuse anything else).
- **No shell, no prompt in argv.** Panel 1's text and every edit prompt travel in JSON spec files; subprocesses are argv lists.
- **Licences.** `qwen21-*` and `uncensored` are under the Qwen Research License (non-commercial), accepted by the user in [SQ]; the page shows the licence next to each LoRA as today.

---

## 15. Decisions made in this spec

1. **Edit prompt for Compose** = `_compose_prompt(panel 1 Image:, Style:)`, the text Phase 2 would render panel 1 from (QE46).
2. **Compose seed** = `--image-seed` (default 0), the movie's stills seed (QE48).
3. **Kept original** = `seed-original.png`, the EXIF-oriented seed as PNG, also the edit's source (QE45).
4. **Phase 1c** after Phase 1b and before Phase 2; `--story-only` and the dry run never edit; the dry run reads no weights (QE43, QE44, QE50).
5. **Reuse** of an ok `seed-edited.png` when seed bytes, prompt, seed, size and settings are equal (QE48 step 4).
6. **Timeout** `max(3600, 600 × jobs)` (QE11).
7. **Lone `--lora`** refused (`--lora needs --qwen-model`); `--seed-edit-lora` without a model or with `as-is` refused (QE10, QE43).
8. **Selection check order** memory, then installation, as the probe (QE12).
9. **Legacy routes kept verbatim:** Locations/Characters `run_edit_child`'s body for `qwen2511-bf16`; Seeds/Compose spawn the same child from `qwen_edit` (QE4, QE33).
10. **Server forwarding:** only a selection the request names is validated, probed and forwarded; omission → no flag (Compose as-is, Locations/Characters the CLI default) (QE56). The Seeds-Use origin is kept on the page (`S.seedOrigin`), not on the server (QE67, Section 16 item 3).
11. **Six mounts on four tabs:** create form and Regenerate row for Locations and Characters (QE62).
12. **`edit` key** = the settings block, optional, shape-validated in both libs by one byte-identical function, only on photo locations / seed-image characters (QE31, QE38).
13. **Manifest** gains `edit` only when edits ran; legacy generator string kept byte-for-byte (QE30, QE37, `generator_text`).
14. **`busy_process`** ignores `bin/seed-edit --probe` and `bin/seed-edit-setup` (QE35).
15. **`EDIT_MIN_AVAIL_GIB`** kept as the pinned mirror; **`--regenerate` refusal text** unchanged (QE36, QE37).
16. **No import of `qwen_edit` in `movie_ui_lib`/`movie_ui_server`**; the mut25 allow-list stays (QE2).
17. **Compose V1 rule 12d structural in `movie_ui_lib`, registry rules in the server's `_fields_body`** (QE54, QE57), because `movie_ui_lib` is standard library only and cannot import `movie_ui_seedgen` (which imports it).
18. **409 only for submits that run the edit** (Compose `movie`, seed folders, photo locations with fewer than 24 photos, seed characters) (QE57-QE59).
19. **Batch:** the two fields at level `stills`, grouped with the seed, cleared with it (QE60).
20. **No `build_pkg.py` change**; a package without `qwen_edit.py` refuses `--seed-edit-model ID` (QE43 row 6).
21. **Locations/Characters CLI default** (binding notes): a hand-run `--regenerate` without options uses the registry default, not the recorded choice; the page sends the recorded choice explicitly.

## 16. Conflicts with the approved design

1. **Panel 1's description is a literal description of the seed.** With a seed image both story engines tell the writer that Panel 1's `Image:` field must literally describe the attached image (`bin/ltx-movie:217-221`, `story_engine.py:380-384`, `:2910-2913`). Prompting the edit with that text asks the model to redraw what the seed already shows, so the edit will mostly re-render the seed (model and LoRA effects, mild changes) rather than move it toward a different opening frame; L3's "panel 1 follows its description" is close to automatic. **Recommendation:** implement as approved (this spec) and decide after L3. If the user wants panel 1 to depart from the seed, the follow-up is a seed-edit variant of the two seed prefaces (Phase 1 describes the opening frame from the narrative while keeping the seed's people), which edits `story_engine.py` and `bin/ltx-movie` prompts and is out of scope here (Open question 1).
2. **"Shots mode: Z-Image txt2img with LoRAs, as today" for panels 2..N.** A seed image cannot be used with shots mode (`bin/ltx-movie:1185-1189`; V1 rule 8, `movie_ui_lib.py:1525-1526`), so with a seed only the chained flow exists. **Recommendation:** keep the refusal; this spec covers chained mode only (the picker hides in shots mode).
3. **"Seeds 'Use' upload is tagged so the UI/server preselect as-is."** The server cannot tag reliably (uploads are content-addressed; the same bytes can arrive by Use or by upload), and a server-side default by origin would change old jobs' fields and batch forks (they carry no seed-edit field). **Recommendation (taken, QE56/QE67):** the page keeps the origin (`S.seedOrigin`) and always sends an explicit value; the server treats an omitted field as as-is, which is the Seeds-Use default and keeps every existing run unchanged.
4. **"mut25 allow-list must admit qwen_edit if movie_ui_lib/server import it."** They do not need to (QE2), so the allow-list is unchanged. No action.
5. **"Size = movie width × height rounded to the model multiple, then the existing letterbox."** The video geometry is already a multiple of 64, so the rounding never changes it, and Phase 2 builds `panel_01.png` at twice the video size (`bin/ltx-movie:2010-2016`), so the edited image is upscaled 2× where an unedited seed photo usually is not. **Recommendation:** keep the approved size (memory and time) and judge at L3; if panel 1 looks soft, the alternative is to edit at `2W × 2H` capped at a 1024 px long edge (a one-line `_seed_edit_size` change) — Open question 2.
6. **"If build_pkg.py (~:383-386) pins bin/ltx-movie content, update it."** It does not pin content (Section 0.1). No action.

## 17. Open questions

1. After L3: should a later change let Phase 1 describe a panel 1 that departs from the seed (Section 16 item 1)?
2. After L3: edit at the video size (approved) or at the still size (Section 16 item 5)?
3. After L1/L2: is `JOB_TIMEOUT_S = 600` right for `qwen21-q4`/`bf16` at 40 steps on macstudio (a constant change)?
4. After L1/L2: is the `uncensored` strength 1.0 the right default for photo and identity edits (a registry data change)?
