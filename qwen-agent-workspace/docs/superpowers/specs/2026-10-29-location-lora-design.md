# Location library: location LoRAs, pinned per panel

Date: 2026-10-29

Status: design spec. The user approved the design section by section (S1 dataset, S2 training and record, S3 story use, S4 movie UI and lora-check; S5 errors and testing was drafted for review). This document carries those sections without reopening them. Every detail the approved design left open is decided here, marked **[spec choice]**, and listed in Section 10. The implementer makes no design decisions.

Repository: `/Users/reubenpatterson/local_agent_harness`, branch `qwen-agent-redteam`, HEAD `d210c26` (`d210c2695c7bd82ac27f7f4e058ecd3bef1b1241`). `WS` is `qwen-agent-workspace/`. Every relative path is relative to `WS`, and every line number cites the code at `d210c26`.

Specs this one builds on, cited by tag:
- **[CL]** `docs/superpowers/specs/2026-10-05-character-library-design.md`: the character library, `character.json`, the dataset/training pipeline, casting.
- **[SE]** `docs/superpowers/specs/2026-10-21-character-seed-edit-design.md`: Qwen-Image-Edit-2511 + Lightning editing (E1, E5-E7, E14).
- **[ACT]** `docs/superpowers/specs/2026-10-20-action-lora-motion-library-design.md`: the action library (the second library cloned from [CL]).
- **[PCP]** `docs/superpowers/specs/2026-10-27-pinned-cast-presence-design.md`: P16, the retry-then-fatal plan check this spec's P21 copies.
- **[MUI]** `docs/superpowers/specs/2026-10-19-movie-ui-design.md`: movie-ui routes, jobs, V1 rules, `/files`.
- **[RSC]** `docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md`: the story engine, `plan.json`, the LoRA catalog, `catalog_loras`.

Terms:
- A **location** is one entry in the location library: a name, a trigger token, a 15-40 word description of the place's persistent features, a dataset of 24 people-free stills, and up to two LoRAs (one LTX-2.3 video LoRA, one Z-Image stills LoRA).
- A **pinned** location is one given to `bin/ltx-movie --location NAME` (or picked in movie-ui Compose). Its plan entry carries `"location_name"`.
- A panel is **at** a location when its plan beat's `location` id is that location's plan id.

Requirement ids: L1.x dataset, L2.x training and record, L3.x story use, L4.x movie UI and lora-check, L5.x errors. Tests: LL (location_lib), LD (location_dataset), LT (bin/location CLI), LG (character golden), LS (story engine), LP (pipeline: ltx-movie, manifest, images, render), LU (movie UI), LC (lora-check). KPIs: LK.

---

## 0. Purpose and scope

### 0.1 Purpose

A story's places are only as stable as the planner's setting sentence and the video model's guess. A harbour street drawn in panel 2 is a different street in panel 6. The character library fixed this for people: a trigger-trained LoRA attached per panel. This feature adds the same for places.

The user creates a location from a text description or from photos. `bin/location` builds a 24-still people-free dataset, trains a Z-Image stills LoRA and an LTX-2.3 video LoRA, and records both. The user pins up to 3 locations in a story. The planner must set at least one beat at each pinned location, with the location's fixed setting sentence. The LoRAs and trigger then apply **only** to the panels whose beat is set at that location, attached deterministically from `plan.json` (no text matching).

### 0.2 Grounding (verified at `d210c26`)

**Character machinery reused (`character_dataset.py`, 1904 lines).**
- VLM: `VLM_URL`/`MODELS_URL`/`VLM_MODEL` `:57-62`; `extract_json` `:230-247`; `image_data_url` `:354-361`; `vlm_call` `:364-389` (temperature 0, so a bare retry repeats; every retry quotes the rejection); `vlm_ready` `:469-473`; `wait_for_vlm` `:516-523`.
- Story server: `story_server` `:476-482`; `restore_story_server` `:485-495`; `story_server_state` `:498-513`. The create flow stops the server, waits for memory, runs the image child, and restores in a `finally` (detached on interrupt, `--wait` otherwise) `:980-1008`.
- Gates: `busy_process` `:535-556` (markers include `character_dataset.py zimage` and `character_dataset.py qwenedit`, `:553-554`); `free_gib` `:559-566`; `library_lock` `:586-613` (lock file `<character library>/.lock`); `wait_for_avail` `:526-532`; thresholds `CREATE_MIN_FREE_GIB 2.0`, `TRAIN_MIN_FREE_GIB_PER_KIND 8.0`, `TRAIN_MIN_AVAIL_GIB 30.0`, `GENERATE_MIN_AVAIL_GIB 20.0`, `EDIT_MIN_AVAIL_GIB 64.0`, `VLM_WAIT_S`, `AVAIL_WAIT_S` `:180`, `:194-199`.
- Processes: `run_logged` `:616-654` (watchdog SIGKILL, returns -9 on timeout); `step_log_path` `:657-660`; `run_zimage_child` `:1746-1762`; `run_edit_child` `:1765-1781`; `child_qwenedit` `:1798-1835` (one `spec["image"]` for every job `:1815-1816`; skill `"character_edit"` `:1825`); `child_zimage` `:1838-1883`; `edit_models_missing` `:831-844`.
- Dataset: `STYLE` `:64`; `SHOTS` `:65-72`; `SHOT_ALIASES` `:190-191`; `CHECK_ATTEMPTS = 3` `:183`; `wrap_still` (1-frame h264) `:769-782`; `verify_ffprobe` `:392-404`; `_write_sheet` `:785-800` (hard-codes `char_%02d.png`, `:793`); `describe` retry-and-shorten pattern `:715-742`; `score_still` `:745-762`; status rule `:1068`; too-few-kept exit 3 `:1081-1090`; abort handling `:911-916`.
- Training: `VIDEO_TRAIN_CONFIG_TEMPLATE` (rank 32, alpha 32, lr 2e-4, 1000 steps, checkpoints every 250) `:1332-1388`; `video_train_config` `:1391-1395`; `preprocess_argv` (512x320, `--max-frames 1`) `:1398-1400`; `train_argv` (`--low-ram`) `:1403-1404`; `_video_failed` `:1407-1410`; `train_video(data)` `:1413-1488`; `train(args)` preflight order `:1491-1566`; `stills_epochs`/`stills_train_config` (Z-Image-Turbo, rank 16, ~672 steps) `:1573-1604`; `train_stills(data)` with the compat gate `:1641-1741`; `TRAIN_MODEL_DIR`/`TEST_MODEL_DIR` `:201-202`; `TEST_SEED = 42` `:219`.
- Create: `create(args)` `:1118-1302`; the seed is persisted only under the lock after every preflight `:1240-1251`; a trained character's regenerate is refused `:1144-1146`; `_regenerate` `:1305-1325`.

**`character_lib.py` (1482 lines, stdlib).** `NAME_RE` `:30`, `TRIGGER_RE` `:31`, `MIN_SCORE = 7` `:38`, `MIN_KEEP = 12` `:39`, `DEFAULT_CHARACTER_STRENGTH = 0.8` `:40`, `TRIGGER_REGISTRY`/`LOCK_NAME`/`SHA256_RE`/`UTC_RE` `:178-181`, `utc_now` `:270-271`, `validate_character` `:360-455`, `load_character` `:458-469`, `write_character` (atomic) `:472-485`, `list_names` `:488-493`, `registered_triggers` `:496-516`, `register_trigger` `:519-523`, `auto_trigger` `:526-539`, `resolve_cast` `:558-597`, `prefix_character_triggers` `:905-919`, `usable_characters`/`format_available_line`/`character_table_lines` `:1444-1482`, `SHOTS_SETTING_MIN_WORDS = 12` `:50` (shots S-rule at `:1297`).

**CLIs.** `bin/character` parser `:49-80`, list/show `:83-108`, PIL/psutil re-exec under `$CHARACTER_PYTHON` `:117-128`, signal handling (SIGINT/SIGTERM/SIGHUP → KeyboardInterrupt, exit 130) `:135-152`. `bin/character-train-vlm` `:1-40` (stops the VLM, always restores it). `bin/action-train-vlm` is the same script renamed (`diff` shows names only). `action_dataset.py:238` records `INFERENCE_MODEL = "dgrauet/ltx-2.3-mlx-q8"` as a LoRA's base; `:251-258` reuses `character_dataset.busy_process`/`story_server_state`.

**Story engine (`story_engine.py`, 4997 lines, stdlib).** `LORA_PANEL_LIMIT = 4` `:82`; `StoryContext` `:92-97` (defaults for the last four fields); `PLAN_PROMPT_TEMPLATE` `:314-354`, whose locations sentence is `:335-338` ("setting is one sentence of 12 to 45 words that starts with \"The setting is\""); `_fill` `:468-476`; `CAST_FIXED_INTRO`/`CAST_FIXED_LINE` `:1055-1060`; `build_plan_prompt` `:1063-1134` (the `@@CAST_FIXED@@` fragment `:1104`); `normalize_plan` `:1233-1308` (pinned cast re-insert `:1253-1259`, locations `:1262-1268`, beats `:1270-1287`); `_setting_length` (advisory 12-45, 25% tolerance) `:1611-1614`; `_setting_problems` (hard: starts "The setting is ", one sentence split on `[.!?]\s+`) `:1617-1625`; `pasted_pieces` pastes the beat's setting into every Image (chained panel 1, shots) `:2028-2049`; `plan_checks` `:2091-2293` (undefined beat location is P2 hard `:2137-2139`; P16 `:2234-2245`); `lora_checks` with L4 `:2300-2414` (`loras_k` `:2378-2381`, L4 `:2387-2390`); critic patch ranges mark `location.setting` `NOT_REPAIRED` `:3917`; `plan_round` retries any `plan_checks` hard message with "YOUR PREVIOUS REPLY WAS REJECTED" `:4414-4446`; fatal filter `("P1", "P2", "P16", "P17")` `:4640`; `recheck` never calls `plan_checks` `:4890`. P1-P20 are taken; P21 is free.

**`bin/ltx-movie` (2643 lines).** `--model` default `dgrauet/ltx-2.3-mlx-q8` `:323`; `--character`/`--cast`/`--character-strength`/`--action` `:343-368`; `_character_lib()` path loader `:790-794`; `_resolve_casting` `:837-893` (`--character-strength` without a cast is an error `:845-847`; `--no-stills` refused `:849-852`; existing-story phrase check exit 2 `:886-890`); `_resolve_global_loras` `:901-941`; `_resolve_story_engine` legacy flag list `:1041-1052`; `_cast_flags` `:1136-1144`; `_story_pins` `:1403-1420`; `_story_context` `:1494-1523`; `_phase1_robust` `:1678-1732`; `phase2_stills` `:1909-1944` (cast flags `:1929`); `_shots_stills_groups` `:1951-1971`; `_phase2_shots` `:1983-2018`; `phase3_manifest` `:2097-2150` (cast flags `:2118`); `_print_shots_stills_plan` `:2334-2353`; `_print_dry_run_plan` `:2356-2497` (cast block `:2386-2392`, cast flags `:2447`, `:2472`); `main` resolution order `:2576-2590`. `tests/test_ltx_movie_offline.py` counts source strings in this file (`_render_flags(args)` ×4, `os.path.join(WS, "bin", "ltx-mlx-render")` ×4, `os.path.join(WS, "bin", "story-server")` ×2, `["--lora", args.stills_lora_path]` ×2, `:127`, `:722-729`, `:1586-1593`).

**`bin/ltx-story-manifest` (962 lines).** `--cast` requires `--chain` or `--shots` `:572`; `_casting_plan` (plan.json beats → per-panel cast; one note line when unusable) `:401-442`; the casting block, with the plan-attached trigger prefix (`prefix_character_triggers`) `:866-894`; catalog LoRAs and trigger prefix `:896-906`; summary prints `:947-957`. Tests patch `story_manifest.WS` (`tests/test_casting_pipeline.py:686`).

**`bin/ltx-story-images` (490 lines).** Stdlib at import; casting builds `char_plans` `:295-311`; legacy route `:313-314`; `plans` `:334-339`; one LoRA set per process `:340-344`; `--lora-trigger` prefix `:345-352`. `tests/test_ltx_story_images.py:581-592` (I20) requires `_compose_prompt(` exactly 3 times and `_panel_seed(args.seed, i, grounded)` exactly twice in the file.

**`bin/ltx-mlx-render` (1456 lines).** `load_manifest` validates `characters` `:236-257` and `catalog_loras` `:259-272`; `build_units` LoRA order catalog motion/physics, global, catalog style, characters `:349-364`; `video_only_lora` strips audio-stream modules `:475-520`; `use_video_only_character_loras` `:523-528`; provenance includes every unit LoRA with its sha256 `:556-563`; legacy route and duplicate checks `:1208-1250`; `use_video_only_character_loras(units)` `:1346`. No render-side LoRA-count advisory exists; the only 4-per-panel advisory is story_engine L4.

**`bin/lora-check` (423 lines).** `_core` `:87-99`; `lora_targets` `:108-124`; `base_linear_map` considers only `.weight` keys `:159-161`; `_match_base` `:181-189`; `static_check` `:192-238` (any problem text on a passing check makes it FAIL, `:238`); `main` output `:404-419`. The ltx-2-mlx fuser matches a bare key: `prefix = key[: -len(".weight")] if key.endswith(".weight") else key` (`~/ltx-2-mlx/packages/ltx-core-mlx/src/ltx_core_mlx/loader/fuse_loras.py:103-105`). The low-RAM path attaches each LoRA as `BlockLoraSource(..., block_prefix=LTXV_LORA_BLOCK_PREFIX)` (`~/ltx-2-mlx/packages/ltx-pipelines-mlx/src/ltx_pipelines_mlx/_base.py:413-434`; `LTXV_LORA_BLOCK_PREFIX = "transformer_blocks."`, `ltx-core-mlx/.../loader/sd_ops.py:159`), which skips every key outside it (`ltx-core-mlx/.../loader/block_streaming.py:85`).

**`bin/lora-catalog` (307 lines).** `_arch_gate` `:43-66`; `--no-arch-check` `:90-92`; the gate prints `arch: ...` lines to stderr `:142-148`; `cmd_verify` prints `OK id`/`FAIL id: problem` and `verified N entr(y|ies): P problem(s)` `:265-297`. `lora_catalog.compatible` `:343-352`; `lora_catalog.prefix_triggers` `:355-368`.

**movie-ui.** `movie_ui_server.py`: `_NAME` `:57`; `ROUTES` `:64-107` (40 routes; `tests/test_movie_ui_http.py:43` asserts 40); bodies are read only for POST/PUT/DELETE `:378`; `__getattr__` routes every `do_*` through `_handle` `:274-278`; `_h_upload` `:940-950`; `_h_lora_add` `:1001-1042`; `parse_verify` `:1052-1069`; `newest_job` `:1142-1148`; `_h_character` `:1151-1181`; `character_create_errors` `:1188-1227`; `create_character_job` `:1230-1235`; `_h_character_train` `:1262-1275`; `/files` allows `<ws>/generated/**` `:1590-1593`. `movie_ui_lib.py`: `job_vlm` `:421-435`; `DEFAULT_FIELDS` `:891-904`; `FIELD_FLAGS` `:908-922` (28 entries, asserted by `tests/test_movie_ui_builder.py:135`); `build_argv` `:963-1015`; `action_argv` `:1040-1054`; `character_argv` `:1057-1086`; `tool_argv` `:1119-1121`; `validate_fields` characters rule `:1401-1404`; `ProgressParser.snapshot` gives non-story jobs `elapsed_s` + `last_line` `:2155-2157`. `static/movie-ui/app.js`: `TABS` `:284`; init `:263`; compose field collection `:384-387`; field restore `:518-520`; characters `:774-879`; LoRA tab `:968-1066`; `setupCharacters()` `:1493`. `static/movie-ui/index.html`: Compose cast `:113`; Characters `:165-195`; LoRAs & Models `:222-252`. `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` `:264-294` pins pipeline files to `BASELINE = ff757afb...`.

**Baseline failures on this Mac at `d210c26`** (not caused by this work): `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`. They must fail identically after the change.

### 0.3 Deliverables

| # | File | Change |
|---|---|---|
| G1 | `location_lib.py` (new, stdlib) | schema, validation, library I/O, triggers, resolution, plan reader (L1.1, L2.6-L2.9, L3.2, L3.7) |
| G2 | `location_dataset.py` (new) | create, regenerate, edit, train (L1.2-L1.12, L2.2-L2.5) |
| G3 | `bin/location` (new), `bin/location-train-vlm` (new) | CLI (L1.2, L2.1) |
| G4 | `character_dataset.py` | L2.10 refactor (`train_video_lora`, `train_stills_lora`), L1.8 child extension; character behaviour byte-identical |
| G5 | `story_engine.py` | L3.3-L3.6 |
| G6 | `bin/ltx-movie` | L3.1, L3.2, L3.8, L3.10 |
| G7 | `bin/ltx-story-manifest` | L3.7 |
| G8 | `bin/ltx-story-images` | L3.8 |
| G9 | `bin/ltx-mlx-render` | L3.9 |
| G10 | `bin/iterate-story` | L3.11 |
| G11 | `movie_ui_lib.py`, `movie_ui_server.py`, `static/movie-ui/{index.html,app.js}` | L4.1-L4.6 |
| G12 | `bin/lora-check`, `bin/lora-catalog` | L4.7, L4.8 |
| G13 | tests (new files) and fixtures | Section 6 |
| G14 | existing tests | only the edits of Section 6.9 |
| G15 | `tests/test_movie_ui_builder.py::test_mut26` | `BASELINE` re-baseline in a separate test-only follow-up commit |

### 0.4 Out of scope

- Motion clips for locations (locations train on 1-frame stills only, like characters).
- Planner auto-pick of locations (only pinned locations get LoRAs; the planner never chooses one).
- A `location` kind in the LoRA catalog (locations are not catalog entries and are not folded like characters).
- More than one location per beat (a beat has one `location` id, `story_engine.py:1280`).
- Resume of interrupted training (as for characters, a rerun starts over).
- Leak tests for location LoRAs (per-panel scoping makes them moot).
- `--no-stills` movies, `--story-legacy` and `--story-prompt-override` with locations (refused, L3.1).
- Re-checking existing stories for P21 (`recheck` is unchanged).
- A `bin/ltx-movie --list-locations` flag.

### 0.5 Success criteria (KPIs)

| ID | Criterion | Verified by |
|---|---|---|
| LK1 | `python3 -m pytest tests/ -q -rA` from `WS` has no new failures: the only failures are `test_d2_copied_literals_match_the_spike` and `test_rst62_import_sets`, with their `d210c26` messages; the pass count is the pre-implementation count plus every new test. Measured after the G15 commit. | full run |
| LK2 | `python3 tests/test_ltx_movie_offline.py` prints `OK 347/347` (no new failures). | offline check |
| LK3 | `/usr/bin/python3` (3.9) and `python3` (3.13) both `py_compile` every new and changed Python file and `bin/` script. | LL1 |
| LK4 | **Character byte-identity.** The golden record of `train_video`/`train_stills` (argv, cwd, HF_HOME, `train.yaml`, `train.json`, child specs, `character.json`, stdout, stderr, files) is byte-identical before and after L2.10; every existing `tests/test_character_*.py` test passes unedited (except the baseline `test_d2`). | LG1-LG3 |
| LK5 | **No-location byte-identity.** Without `--location`: plan prompts, normalised `plan.json`, the manifest, `images.json` plans, render units and clip provenance are identical to `d210c26`. | LS1, LP14, LP19 |
| LK6 | **Dataset shape, 100% offline.** Text mode writes exactly the 24 L1.5 prompts. Photo mode with P photos (P in 1, 3, 5, 24) yields exactly 24 stills: P fitted photos and 24-P edits, round-robin over the photos. | LD5, LD9 |
| LK7 | **Deterministic attach, 100%.** In chained and shots modes, every panel whose beat location is a pinned, attachable location gets exactly one `locations` entry and the trigger prefix; every other panel gets none. | LP5-LP8 |
| LK8 | **Presence.** A plan that leaves a pinned location out of every beat gets exactly one P21 per missing location; a corrected second reply ends rc 0 after 2 plan calls; two bad replies end rc 1 with the fatal message and no story.md. | LS6-LS9 |
| LK9 | **lora-check.** A synthetic 1724-pair ComfyUI-style LTX-2.3 LoRA whose 290 targets are bare 2-D tables is not FAIL against a synthetic base with those tables; it reports `44 of 1724 modules are outside the transformer blocks ...`; PASS/FAIL and exit codes of every existing lora-check, lora-catalog add and verify case are unchanged. | LC1-LC8 |
| LK10 | No test reads the real HOME, renders, trains, runs Z-Image or the editor, contacts a model server, or touches port 8178; the only server is an in-test movie-UI server on 127.0.0.1. | review, Section 6.1 |

### 0.6 Must-have and nice-to-have

Every L requirement and every test in Section 6 is a must-have. Nothing else is built. Not built: anything in 0.4; a preview stop for location datasets (D11); a strength editor in the UI.

---

## 1. Architecture

### 1.1 Flow

```
bin/location create NAME (--description TEXT | --photo PATH ...)
  preflights -> [photo mode, no description: VLM drafts it from the first 5 photos]
  -> location.json (status dataset) -> stop story server -> Z-Image 24 stills (text)
     | fit photos + Qwen-Image-Edit top-up edits (photos) -> restore story server
  -> VLM check per still -> keep/drop -> captions + 1-frame mp4s + manifest + contact sheet
  -> status untrained (>= 12 kept) | dataset (exit 3)
bin/location train NAME            (via bin/location-train-vlm from movie-ui)
  -> character_dataset.train_video_lora (ltx-2-mlx, rank 32, 1000 steps) + 2 test clips
  -> character_dataset.train_stills_lora (mflux Z-Image-Turbo, rank 16) + compat gate
  -> status trained
bin/ltx-movie ... --location NAME [--location-strength S]
  Phase 1: plan locations l1..lK fixed ("The setting is <description>."), P21 presence
  Phase 2: ltx-story-images attaches the stills LoRA + trigger to panels at the location
  Phase 3: ltx-story-manifest: panel["locations"] + trigger prefix from plan.json beats
  Phase 4: ltx-mlx-render fuses catalog motion/physics, global, style, LOCATION, characters
```

### 1.2 Module boundaries and import rules **[spec choice]**

- `location_lib.py`: stdlib only. It loads `character_lib.py` by path (`importlib.machinery.SourceFileLoader("character_lib", os.path.join(WS, "character_lib.py"))`) inside the functions that need it, never at import. `bin/location list`/`show`, `bin/ltx-movie`, `bin/ltx-story-manifest` and `bin/ltx-story-images` use only this module. The three pipeline tools load it by path inside function bodies, and only when `--location` is given, the way they load `character_lib` (`bin/ltx-movie:790-794`).
- `location_dataset.py`: stdlib, PIL, psutil, `location_lib`, `character_lib` and `character_dataset` (imported at top level with `sys.path.insert(0, WS)`). It never imports torch, diffusers or z_image_skill: all image work runs in `character_dataset.py`'s own child processes (`run_zimage_child`, `run_edit_child`), so `busy_process`'s markers (`character_dataset.py:553-554`) cover location work unchanged.
- `story_engine.py` gains no import. It reads pinned locations by attribute (`.name`, `.description`, `.attach_video`) from `ctx.locations`.
- `bin/location` re-executes itself under `$CHARACTER_PYTHON` (default `~/img-gen/bin/python`) when `create`, `train` or `edit` cannot import PIL or psutil, with the marker `LOCATION_REEXEC=1`, exactly as `bin/character:117-128`.

### 1.3 Names **[spec choice]**

- Library root: `location_lib.library_dir()` = `$LOCATION_LIBRARY_DIR` when set (test infrastructure only), else `WS/generated/locations` (gitignored via `generated/`).
- Record: `location.json`, `schema_version` 1. Trigger registry: `<library>/.triggers`.
- Lock: the **character** library lock (`character_dataset.library_lock()`, `<character library>/.lock`). One heavy dataset or training job runs at a time across characters and locations (D14).
- Still files: `loc_NN.png`, `NN` = 01..24.

---

## 2. L1 Dataset

### 2.1 Layout (L1.1)

```
generated/locations/
  .triggers                      append-only "<trigger> <name>\n"
  <name>/
    location.json
    photos/photo_NN.png          photo mode: EXIF-oriented RGB copy of input NN, full size
    stills/loc_NN.png            24 stills, 1024x640 (photo, edit or generated)
    captions/loc_NN.txt          kept stills only
    videos/loc_NN.mp4            kept stills only; 1-frame h264 (character_dataset.wrap_still)
    manifest.json                L1.10
    contact_sheet.jpg            L1.11
    train/video/..., train/stills/...
    lora/video.safetensors, lora/stills.safetensors | lora/stills.rejected.safetensors
    tests/video_lora.mp4, tests/video_control.mp4, tests/stills_lora.png, tests/stills_control.png
    logs/<UTC %Y%m%dT%H%M%SZ>-<step>.log (+ .spec.json/.report.json for image children)
```
The approved list (`stills/`, `manifest.json`, `contact_sheet.jpg`, `location.json`, `logs/`) is extended with `photos/`, `captions/`, `videos/`, `train/`, `lora/`, `tests/` because ltx-2-mlx preprocess needs matching `videos/` and `captions/` directories and regenerate needs the photos **[spec choice]**.

### 2.2 `bin/location` CLI (L1.2)

```
bin/location create NAME [--description TEXT] [--photo PATH ...] [--trigger WORD] [--seed N] [--force]
bin/location create NAME --regenerate [--seed N | --new-seed] [--description TEXT] [--force]
bin/location train NAME [--video] [--stills] [--force]
bin/location edit NAME --description TEXT
bin/location list
bin/location show NAME
```
- `--photo` is repeatable (`action="append"`, dest `photos`), 1-24 paths. With photos, `create` is photo mode; without, text mode and `--description` is required.
- `--force`: at create and regenerate, keep user photos whose check shows people or is unparseable; at regenerate, also allow regenerating a trained location, deleting its LoRAs (D12). At train, retrain an existing LoRA (as `bin/character train --force`).
- `edit` saves a new description for a **photo** location (D13).
- Exit codes: 0 success; 1 runtime failure; 2 argument or precondition failure; 3 create/regenerate kept fewer than 12 stills.
- Signals: SIGINT, SIGTERM and SIGHUP raise KeyboardInterrupt; the top level prints `location: interrupted` and exits 130 (copy of `bin/character:135-152`).
- `list` and `show` import `location_lib` only.

`list` prints `location_lib.location_table_lines()`:
- header `LIST_ROW_FORMAT % ("NAME", "TRIGGER", "STATUS", "SOURCE", "VIDEO", "STILLS", "DESCRIPTION")` with `LIST_ROW_FORMAT = "%-16s %-16s %-9s %-6s %-5s %-6s %s"`;
- one row per location: name, trigger, status, source (`text`/`photos`), `yes`/`no` for each LoRA, the full description;
- an unloadable record: `"%-16s (invalid: %s)" % (name, error)`;
- an empty library: `no locations in <library_dir()>`.

`show NAME` prints `json.dumps(data, indent=2, ensure_ascii=False)`, then `files:`, then `"  %-8s %s" % ("ok" | "MISSING", path)` for, in order: `location.json` (always first), each `photos/photo_NN.png` (photo mode), `contact_sheet.jpg` when `dataset` is set, each recorded LoRA path, and `tests/video_lora.mp4`, `tests/video_control.mp4` when `loras.video` is set. An unknown or invalid location: `Error: <LocationError>`, exit 2.

### 2.3 Description rule (L1.3)

`location_lib.normalize_description(text)`: collapse whitespace runs to one space, strip, drop one trailing `"."` and strip again, lower-case the first character when it is upper-case. `location_lib.validate_description(text)` raises `LocationError("description: <reason>")` unless, in this order:
1. `text` is a str equal to `text.strip()`;
2. `15 <= len(text.split()) <= 40` ("must be 15-40 words, got N");
3. it starts with `"a "`, `"an "` or `"the "` ("must start with \"a \", \"an \" or \"the \"");
4. it contains none of `. ! ? " \n \r` ("must be one noun phrase with no . ! ? or double quote").

**The arithmetic (exact).** The fixed setting is `"The setting is " + description + "."`, so its word count is `3 + W`, where W is the description's word count. The planner rule is 12-45 words (`story_engine.py:335-338`); the P4 advisory fires outside 12-45 beyond a 25% tolerance (`:1611-1614`); the shots S-rule needs at least 12 (`character_lib.py:50`, `:1297`). With `15 <= W <= 40` the setting has 18 to 43 words, inside 12-45 with 2 words of headroom; the widest W that would still fit is 9-42. Rule 4 keeps the setting one sentence for `_setting_problems` (`:1617-1625`), and the `"` ban keeps the quoted plan-prompt line (L3.3) well formed.

### 2.4 Trigger (L1.4)

- A given `--trigger` must match `character_lib.TRIGGER_RE` (`[a-z][a-z0-9]{3,15}`), must not be in `location_lib.all_triggers()` (the location registry and records, plus `character_lib.registered_triggers()`), and must not be a word of the description (`re.findall(r"[a-z0-9]+", description.lower())`).
- Otherwise `location_lib.auto_trigger(name, description, taken)` returns `character_lib.auto_trigger(name, "place", taken, avoid=<the description words>)` with `taken = all_triggers()`. Examples: `("harbour-street", ...)` → `"harboplc"`; with `"harboplc"` taken → `"harboplc2"`; `("old-mill", ...)` → `"oldmiplc"`.
- The trigger is registered (`<library>/.triggers`) when the location directory is first created, so a failed create still reserves it, as [CL] 2.4.

### 2.5 Text mode (L1.5)

24 Z-Image text2img jobs at 1024x640, every job seeded with `location.json` `seed`, run as one `character_dataset.run_zimage_child({"jobs": [...], "loras": None}, loc_dir, "generate")`.

```python
STYLE = character_dataset.STYLE        # "photorealistic live-action film still, natural light"
TIMES = ("dawn", "midday", "golden hour", "dusk", "night")
WEATHERS = ("clear", "overcast", "rain", "fog", "snow")        # "snow" only from the check
TIME_PHRASES = {"dawn": "at dawn", "midday": "at midday", "golden hour": "at golden hour",
                "dusk": "at dusk", "night": "at night"}
WEATHER_PHRASES = {"clear": "under a clear sky", "overcast": "under an overcast sky",
                   "rain": "in the rain", "fog": "in fog"}

def gen_prompt(view, time, weather, description):
    return "%s of %s, %s, %s, empty of people. %s." % (
        view, description, TIME_PHRASES[time], WEATHER_PHRASES[weather], STYLE)
```

`VARIANTS` (exact, in order; still n = position):

| n | view | time | weather |
|---|---|---|---|
| 1 | Extreme wide establishing shot | dawn | clear |
| 2 | Extreme wide establishing shot | midday | overcast |
| 3 | Extreme wide establishing shot | golden hour | fog |
| 4 | Extreme wide establishing shot | night | fog |
| 5 | Wide shot from a high vantage point | midday | clear |
| 6 | Wide shot from a high vantage point | dusk | overcast |
| 7 | Wide shot from a high vantage point | dawn | fog |
| 8 | Wide shot from a high vantage point | night | rain |
| 9 | Ground-level view looking along the length | golden hour | clear |
| 10 | Ground-level view looking along the length | midday | rain |
| 11 | Ground-level view looking along the length | dusk | fog |
| 12 | Ground-level view looking along the length | night | clear |
| 13 | Low-angle upward view | midday | overcast |
| 14 | Low-angle upward view | dawn | overcast |
| 15 | Low-angle upward view | dusk | rain |
| 16 | Low-angle upward view | golden hour | fog |
| 17 | Medium shot of a single detail | midday | overcast |
| 18 | Medium shot of a single detail | golden hour | rain |
| 19 | Medium shot of a single detail | night | clear |
| 20 | Medium shot of a single detail | dawn | rain |
| 21 | Close-up of a surface texture or sign | dawn | clear |
| 22 | Close-up of a surface texture or sign | dusk | fog |
| 23 | Close-up of a surface texture or sign | golden hour | overcast |
| 24 | Close-up of a surface texture or sign | night | rain |

Coverage: each view 4 times with 4 distinct times; times dawn 5, midday 5, golden hour 5, dusk 4, night 5; each of clear, overcast, rain, fog 6 times **[spec choice]**. Example, n 11: `"Ground-level view looking along the length of a narrow cobbled harbour street ..., at dusk, in fog, empty of people. photorealistic live-action film still, natural light."` (lower-case `photorealistic` after the full stop, as `character_dataset.gen_prompt` `:333-336`).

### 2.6 Photo mode (L1.6)

1. **Inputs.** 1 to `MAX_PHOTOS = 24` photos. Each must exist and load with `ltx_image_fit.load_oriented_rgb`. Its centred 16:10 crop, `crop_w = min(w, h * 16 // 10)` and `crop_h = min(h, w * 10 // 16)`, must be at least `512x320` **[spec choice; lowered from 768x480 on 2026-10-30]**. A crop below 768x480 is accepted with the stdout line `warning: --photo PATH: its CWxCH crop is upscaled F.FFx to 1024x640; stills built from it will be softer`. Two inputs with the same sha256 are refused.
2. **Copies.** `photos/photo_NN.png` = the oriented RGB image, PNG, full size; `photos[k] = {"path": <absolute input path>, "sha256": <sha256 of the input file bytes>}`.
3. **Fit.** `stills/loc_NN.png` (NN = 1..P) = `ImageOps.fit(img, (1024, 640), Image.LANCZOS, centering=(0.5, 0.5))`. Photos are kept as-is otherwise.
4. **Description.** When `--description` is absent, `location_dataset.describe(photo_paths[:5])` drafts it (L1.7) and `create` prints `description (drafted by the vision model; change it with bin/location edit NAME --description TEXT): <text>`.
5. **Top-up.** When P < 24, `E = 24 - P` edits. Edit j (1..E) is still `n = P + j`; its source is the fitted still of photo `((j - 1) % P) + 1`; its instruction is `EDIT_PROMPT % EDIT_CONDITIONS[j - 1]`. All E edits run in one `character_dataset.run_edit_child(spec, loc_dir, "edit")` (L1.8). Edits change time, weather or season only, never the camera.
6. **Story server.** Text mode, and photo mode with E > 0, stop the story server, wait for `GENERATE_MIN_AVAIL_GIB` (Z-Image) or `EDIT_MIN_AVAIL_GIB` (edits) available, run the child, and restore exactly as `character_dataset.py:980-1008` (detached restore on interrupt; `--wait` plus `wait_for_vlm(VLM_WAIT_S)` otherwise; the restore runs in a `finally`). Photo mode with P = 24 never stops the server.

```python
EDIT_PROMPT = ("Keep this exact place and viewpoint: the same buildings, structures, ground, "
               "signs, materials and colours, seen from the same camera position with the same "
               "framing. Change only the time of day and the conditions: show it %s, %s. No "
               "people anywhere in the image. Photorealistic live-action film still, natural "
               "light.")
EDIT_CONDITIONS = [
    ("at dusk", "under a clear sky"), ("at night", "in light rain"), ("at dawn", "in thick fog"),
    ("at midday", "under an overcast sky"), ("at golden hour", "under a clear sky"),
    ("at night", "under a clear sky"), ("at midday", "in winter with fresh snow on the ground"),
    ("at dusk", "in heavy rain"), ("at dawn", "under an overcast sky"),
    ("at golden hour", "in autumn with fallen leaves on the ground"), ("at midday", "in light fog"),
    ("at night", "in fog"), ("at dawn", "under a clear sky"), ("at dusk", "under an overcast sky"),
    ("at midday", "in the rain"), ("at golden hour", "in light haze"),
    ("at night", "in winter with snow falling"), ("at dawn", "in light rain"),
    ("at midday", "in summer under a clear sky"), ("at dusk", "in fog"),
    ("at golden hour", "under an overcast sky"), ("at night", "in heavy rain"),
    ("at midday", "in spring under a clear sky"),
]                                                    # 23 entries: P = 1 needs 23 edits
```
The CLI help and the UI say: angles come only from the photos; 3-5 photos from different spots are recommended.

### 2.7 VLM describe (L1.7)

`describe(paths)`: content = `[{"type": "text", "text": DESCRIBE_PROMPT}]` + one `image_url` part per path (`character_dataset.image_data_url`). Up to `DESCRIBE_ATTEMPTS = 3` calls through `character_dataset.vlm_call`:
- a reply whose `description` has more than 40 words is sent back alone as `DESCRIBE_SHORTEN % text` (text only);
- any other rejection retries with the images plus `DESCRIBE_RETRY % (error, reply)`;
- a reply passes when `extract_json` gives a dict whose `description` is a str and `validate_description(normalize_description(it))` passes.
After 3 failures: `DatasetError("describe failed: <error>; last reply: <reply!r>")`, exit 1, nothing written.

```python
DESCRIBE_PROMPT = (
    'These photos show one place. Describe it for an image generator that must redraw the same '
    'place recognisably from many viewpoints, at any time of day and in any weather. Reply with '
    'only a JSON object with one key. "description": one noun phrase of 15 to 40 words that '
    'starts with "a", "an" or "the" and captures only the place\'s persistent features: its '
    'architecture and structures, materials and surfaces, signage, colour palette, era and the '
    'ground. Leave out people, vehicles, animals, the time of day, the weather, the lighting, the '
    'season, the camera and the image style. Use commas, not full stops.')
DESCRIBE_SHORTEN = (
    'Shorten this place description to one noun phrase of 20 to 35 words that starts with "a", '
    '"an" or "the". Keep the architecture, materials, signage, palette, era and ground; drop '
    'repetition and the least distinctive details; use commas and no full stops. Reply with only '
    'a JSON object with one key, "description": the shortened phrase.\n\nDescription: %s')
DESCRIBE_RETRY = (
    'Your previous reply was rejected: %s. Previous reply: %s\n'
    'Reply again with only the JSON object. Keep "description" one noun phrase of 15 to 40 words '
    'starting with "a", "an" or "the", with commas and no full stops.')
```

### 2.8 Edit child extension (L1.8, in `character_dataset.py`)

`child_qwenedit` (`:1798-1835`) changes in exactly two places:
- each job's source is `job.get("image", spec["image"])`; each distinct path is opened once (`Image.open(path).convert("RGB")`) and cached in a dict for the run;
- the content screen's skill is `spec.get("skill", "character_edit")`.

A character spec has no per-job `image` and no `skill`, so its behaviour is unchanged. The location spec: `{"image": <first job's source>, "skill": "location_edit", "model": EDIT_MODEL, "lora_repo": EDIT_LORA_REPO, "lora_file": EDIT_LORA_FILE, "steps": EDIT_STEPS, "true_cfg": EDIT_TRUE_CFG, "jobs": [{"image": <source still>, "prompt": ..., "output_path": stills/loc_NN.png, "seed": data["seed"], "width": 1024, "height": 640}, ...]}`. Before any work, photo mode with E > 0 runs `character_dataset.edit_models_missing()` and refuses with the download command when either repo is not cached (as [SE] E7).

### 2.9 Check, keep and caption (L1.9)

Every still is checked after the server is restored, in n order, with up to `character_dataset.CHECK_ATTEMPTS` (3) calls; each retry appends `CHECK_RETRY % (error, reply, extra)`. A RuntimeError from `vlm_call` propagates (exit 1).

| Still | Prompt | Images | Scored |
|---|---|---|---|
| text mode, generated | `CHECK_TEXT_PROMPT.replace("@@DESCRIPTION@@", description)` | the still | yes |
| photo mode, edit | `CHECK_PHOTO_PROMPT` | `stills/loc_01.png`, the still | yes |
| photo mode, user photo | `TAG_PROMPT` | the still | no |

```python
_KEYS = ('"people_visible": true when any person or part of a person is visible anywhere in '
         'the image, else false. "shot": exactly one of extreme wide shot, wide shot, medium '
         'shot, medium close-up, close-up, extreme close-up. "time_of_day": exactly one of dawn, '
         'midday, golden hour, dusk, night. "weather": exactly one of clear, overcast, rain, fog, '
         'snow.')
CHECK_TEXT_PROMPT = (
    'The image is a candidate picture of this place: @@DESCRIPTION@@. Reply with only a JSON '
    'object with five keys. "match_score": an integer from 1 to 10 for how clearly the image '
    'shows this place, with its architecture, materials, signage, palette, era and ground, where '
    '10 is unmistakably this place and 1 is a different place. ' + _KEYS)
CHECK_PHOTO_PROMPT = (
    'The first image shows the reference place. The second image is a candidate picture, which '
    'may show the same place from another viewpoint, at another time of day, in other weather or '
    'in another season. Reply with only a JSON object with five keys. "match_score": an integer '
    'from 1 to 10 for how clearly the candidate shows the same place as the reference, comparing '
    'its architecture, materials, signage, palette and ground and ignoring the time of day, '
    'weather and season, where 10 is unmistakably the same place and 1 is a different place. '
    + _KEYS)
TAG_PROMPT = 'Reply with only a JSON object with four keys describing this image. ' + _KEYS
CHECK_RETRY = ('Your previous reply was rejected: %s. Previous reply: %s\n'
               'Reply again with only the JSON object, using exactly the listed values for '
               '"shot", "time_of_day" and "weather" and true or false for "people_visible"%s.')
# extra: ', and an integer from 1 to 10 for "match_score"' when scored, else ''
TIME_ALIASES = {"noon": "midday", "day": "midday", "daytime": "midday", "sunrise": "dawn",
                "sunset": "golden hour", "evening": "dusk", "twilight": "dusk"}
WEATHER_ALIASES = {"sunny": "clear", "cloudy": "overcast", "rainy": "rain", "foggy": "fog",
                   "mist": "fog", "misty": "fog", "haze": "fog", "hazy": "fog", "snowy": "snow"}
```

`validate_location_check(d, scored)` returns `{"match_score": int | None, "people_visible": bool, "shot": str, "time_of_day": str, "weather": str}` or raises ValueError: `match_score` (scored only) an int, not bool, 1-10; `people_visible` a bool; `shot` lower-cased, stripped, mapped by `character_dataset.SHOT_ALIASES`, in `character_dataset.SHOTS`; `time_of_day` lower-cased, mapped by `TIME_ALIASES`, in `TIMES`; `weather` lower-cased, mapped by `WEATHER_ALIASES`, in `WEATHERS`. Three unparseable replies give `(None, "unparseable: <error>")`.

**Keep rule** (`MIN_SCORE = 7`, `MIN_KEEP = 12`, from `location_lib`):

| Still | Kept when | Drop reason |
|---|---|---|
| generated or edit, no file (content screen) | never | `blocked by the content screen` |
| generated or edit | parseable, `match_score >= 7`, `people_visible` false | `unparseable: ...`, `score N`, or `people visible` (first that applies, in that order) |
| user photo | parseable and `people_visible` false; or `--force` | `people visible (pass --force to keep it)`, `unparseable: ... (pass --force to keep it)` |

A user photo kept only by `--force` records reason `kept by --force: people visible` or `kept by --force: unparseable: ...`.

**Caption** of a kept still: `parts = [trigger] + [v for v in (shot, time_of_day, weather) if v] + (["empty of people"] if people_visible is False else [])`; `caption = ", ".join(parts) + ", " + STYLE + "."`. A forced unparseable photo is `"<trigger>, " + STYLE + "."`. The place itself is never in the caption, so the trigger absorbs it. Example: `"harboplc, wide shot, dusk, fog, empty of people, photorealistic live-action film still, natural light."`

Each kept still gets `captions/loc_NN.txt` and `videos/loc_NN.mp4` (`character_dataset.wrap_still` then `verify_ffprobe`).

### 2.10 Manifest (L1.10)

`manifest.json` = `{"source": "text" | "photos", "trigger", "description", "seed", "min_score": 7, "reference": "loc_01" | null (photo mode / text mode), "generator": "Z-Image" | "<EDIT_MODEL> + <EDIT_LORA_FILE>, 8 steps" | "photos only", "items": [...]}` with one item per n 1..24: `{"n", "source": "photo" | "edit" | "generated", "photo": <1-based photo index> | null, "prompt": <generation or edit prompt> | null, "match_score": int | null, "people_visible": bool | null, "shot", "time_of_day", "weather" (str, "" when unknown), "kept": bool, "reason": str | null, "caption": str | null}`.

### 2.11 Contact sheet (L1.11)

`location_dataset.write_contact_sheet(items, stills_dir, out_path)`: 5 columns of 256x160 thumbnails with a 20-px label row each, under a 24-px banner. Banner text: `"kept K of T (need 12)"`. Cell label: `"%02d %s %s %s" % (n, source[0].upper(), score_text, verdict)`, where `score_text` is `"s%d" % match_score` when `match_score` is not None, else `"s-"`, and `verdict` is `"kept"` or the drop reason truncated to 28 characters. A dropped cell gets a 4-px red outline. A missing still is a black cell. JPEG quality 90.

### 2.12 Create and regenerate order (L1.12)

**create** (mirrors `character_dataset.create`, `:1118-1302`), every refusal exit 2 unless noted:
1. `validate_name`; `--new-seed` without `--regenerate`; an existing location directory.
2. Photos (L1.6 step 1); `--description` normalised and validated; neither photos nor description.
3. `--seed` in 0..2147483647 (default 0); `--trigger` (L1.4).
4. Photo mode with P < 24: `edit_models_missing()`.
5. Under `character_dataset.library_lock()`: `busy_process()`, `free_gib(library) >= CREATE_MIN_FREE_GIB`, `vlm_ready()`.
6. Photo mode without a description: `describe` (exit 1 on failure, nothing written).
7. Trigger (auto when not given). Create directories, save photo copies, `register_trigger`, write `location.json` (status `dataset`, `dataset` null, LoRAs null).
8. Build (L1.5/L1.6, L1.9-L1.11). Write `dataset = {"kept", "total": 24, "min_score": 7, "contact_sheet"}` and `status = "untrained" if kept >= 12 else "dataset"`. Print the n/score/kept/caption table, `dataset: K/24 stills kept (minimum 12) in <dir>`, `contact sheet: <path>`, then the next step: `next: review the contact sheet, then run bin/location train NAME`. Exit 0, or 3 with L5.1's too-few message. A DatasetError or RuntimeError prints `Error: ...` and exits 1 (status stays `dataset`). KeyboardInterrupt/EOFError prints `Error: aborted; the stills made so far are kept in <dir>; run bin/location create NAME --regenerate to start again` and exits 1.

**regenerate**:
1. `load_location`; `--photo`/`--trigger` refused; `--seed` and `--new-seed` exclusive; seed range.
2. `--description`: text mode → normalised, validated, becomes the new description; photo mode → refused (L5.1).
3. Trained and no `--force` → refused.
4. Photo mode with fewer than 24 photos: `edit_models_missing()`.
5. Lock, busy, disk, VLM (as create step 5).
6. Under the lock only, persist: the new seed (`--new-seed`: `0 if seed >= 2147483647 else seed + 1`), the new description; when trained with `--force`, delete `lora/`, `tests/`, `train/`, set both LoRAs, `trained_at` and `stills_skip_reason` to null. Set `status = "dataset"`, `dataset = None`; write.
7. Delete `stills/`, `captions/`, `videos/`, `manifest.json`, `contact_sheet.jpg` (keep `photos/`, `logs/`); rebuild exactly as create step 8, from `photos/photo_NN.png` in photo mode.

**edit**: `load_location`; text mode refused; description normalised and validated; under the lock, write it and print `description: <text>`; exit 0.

### 2.13 Acceptance (L1)

- A text create with fakes writes exactly the 24 L1.5 prompts, seeded with `seed`, stops and restores the story server once, and with 12 or more passing checks ends `untrained`, exit 0.
- A photo create with P photos writes P fitted stills and 24-P edit jobs whose sources follow the round-robin rule and whose prompts follow `EDIT_CONDITIONS` order.
- User photos with people are dropped without `--force` and kept with it; edits and generated stills with score < 7 or people are always dropped.
- Fewer than 12 kept: exit 3, status `dataset`, the contact sheet banner and cells say why.
- Tests: LD1-LD18, LT1-LT8, LL2-LL5.

---

## 3. L2 Training and record

### 3.1 `bin/location train` and the wrapper (L2.1)

`bin/location train NAME [--video] [--stills] [--force]`; neither flag means both. `bin/location-train-vlm <python> <name> [--video] [--stills] [--force]` is `bin/character-train-vlm` with every `character-train-vlm` replaced by `location-train-vlm` and the command `"$PY" "$DIR/location" train "$@"`.

### 3.2 Train preflights (L2.2)

`location_dataset.train(args)`, in this order (mirrors `character_dataset.train`, `:1491-1566`), each refusal exit 2:
1. `load_location`.
2. Status `dataset`: `location NAME has no accepted dataset (status dataset, K of 24 stills kept, need 12); fix it with bin/location create NAME --regenerate` (K is `dataset.kept`, or 0 when `dataset` is null).
3. For each requested kind with a recorded LoRA and no `--force`: `location NAME already has a KIND LoRA (PATH); pass --force to retrain it`.
4. `character_dataset.library_lock()`; `busy_process()`; `story_server_state() == "STOPPED"`; available memory `>= TRAIN_MIN_AVAIL_GIB`; `free_gib(loc_dir) >= TRAIN_MIN_FREE_GIB_PER_KIND * len(requested)`; video: `TRAIN_MODEL_DIR` holds `transformer-dev.safetensors` and neither `transformer.safetensors` nor `transformer-distilled.safetensors`, `TEST_MODEL_DIR` exists, `SKILL.LTX2_MLX_BIN` is executable. Messages: the character texts with "bin/character" → "bin/location".
5. Stills requested and `MFLUX_TRAIN` not executable: `stills_skip_reason = "mflux-train not found at <path>"`, written, printed, stills dropped from the run.
6. Video (L2.3) → `"failed"` returns 1. Stills (L2.4).
7. Return 1 when the video test failed, stills training failed, or stills were explicitly requested and skipped; else 0 (as `:1563-1566`).

### 3.3 Video LoRA (L2.3)

`character_dataset.train_video_lora(loc_dir, loc_dir/videos, loc_dir/captions, prompt, "location NAME stays STATUS", recorded, tested)` with `prompt = "%s, wide establishing shot at dusk, empty of people." % trigger`. Settings are exactly the character's (1-frame clips 512x320, rank 32/alpha 32, lr 2e-4, 1000 steps, checkpoint every 250, base `ltx-2.3-mlx-q8-dev`) because the core is the character code. `recorded(entry)` sets `loras.video = {"path", "sha256", "base_model": "dgrauet/ltx-2.3-mlx-q8", "rank": 32, "alpha": 32, "steps": 1000}`, `trained_at = utc_now()`, `status = "trained"`, and writes. The two test clips are `tests/video_lora.mp4` (with the LoRA at 1.0) and `tests/video_control.mp4` (without), 512x320x25 at 24 fps, seed 42, model `TEST_MODEL_DIR`. `tested(key, path)` records nothing (the paths are fixed); after the run, print `video LoRA: PATH (sha256 HEX)`, `trigger-only A/B (compare by eye; the LoRA clip should show the place, the control a different place):`, `  with LoRA: <path or None>`, `  control:   <path or None>`.

### 3.4 Stills LoRA (L2.4)

`character_dataset.train_stills_lora(loc_dir, pairs, prompt, seed, kept_ok, skipped)` with `pairs` = `(stills/loc_NN.png, captions/loc_NN.txt)` for every kept n in manifest order, the same `prompt`, and the location seed. Settings and the compat gate are the character's. `kept_ok(entry, sample, control)` sets `loras.stills = {"path", "sha256", "base_model": "Tongyi-MAI/Z-Image-Turbo", "rank": 16, "alpha": 16, "steps": total_steps}`, `stills_skip_reason = None`, writes. `skipped(reason)` sets `stills_skip_reason = reason` and writes; the adapter is kept as `lora/stills.rejected.safetensors`; the location stays usable for video.

### 3.5 Audio stripping (L2.5)

Location video LoRAs are rendered through `video_only_lora` like character LoRAs (L3.9).

### 3.6 `location.json` (L2.6)

```json
{
  "schema_version": 1,
  "name": "harbour-street",
  "trigger": "harboplc",
  "description": "a narrow cobbled harbour street lined with tall weathered stone warehouses, green wooden shutters, rusted iron mooring rings and faded red fishmonger signs above wet granite quays",
  "source": "photos",
  "photos": [{"path": "/Users/me/photos/harbour1.jpg", "sha256": "<64 hex>"}],
  "seed": 0,
  "status": "trained",
  "created_at": "2026-10-29T10:00:00Z",
  "trained_at": "2026-10-29T12:00:00Z",
  "dataset": {"kept": 21, "total": 24, "min_score": 7,
              "contact_sheet": "/.../generated/locations/harbour-street/contact_sheet.jpg"},
  "loras": {
    "video": {"path": "/.../lora/video.safetensors", "sha256": "<64 hex>",
              "base_model": "dgrauet/ltx-2.3-mlx-q8", "rank": 32, "alpha": 32, "steps": 1000},
    "stills": null
  },
  "stills_skip_reason": "mflux adapter incompatible with z_image_skill: ...",
  "strength": null
}
```
`dataset` is an addition to the approved field list, needed for the MIN_KEEP consistency rule **[spec choice]**.

### 3.7 Validation (L2.7)

`location_lib.validate_location(data, name=None)` raises `LocationError("<field>: <reason>")`; `load_location` wraps it as `invalid location.json for NAME: <field>: <reason>` and an absent file as `unknown location: NAME (no PATH)`.

| Field | Rule |
|---|---|
| top level | dict with exactly `{schema_version, name, trigger, description, source, photos, seed, status, created_at, trained_at, dataset, loras, stills_skip_reason, strength}` |
| `schema_version` | int, not bool, `== 1` |
| `name` | `NAME_RE = re.compile(r"[a-z][a-z0-9-]{1,23}")` fullmatch; equals `name` when given |
| `trigger` | `character_lib.TRIGGER_RE` fullmatch; not a word of the description |
| `description` | `validate_description` |
| `source` | `"text"` or `"photos"` |
| `photos` | `[]` when `text`; 1-24 dicts with exactly `{path, sha256}` (`path` absolute str or null; `sha256` `SHA256_RE`) when `photos` |
| `seed` | int, not bool, `>= 0` |
| `status` | `dataset`, `untrained` or `trained` |
| `created_at` | `UTC_RE` |
| `trained_at` | null or `UTC_RE` |
| `dataset` | null or dict with exactly `{kept, total, min_score, contact_sheet}`; ints with `0 <= kept <= total`; `min_score` 1-10; absolute path |
| `loras` | dict with exactly `{video, stills}`; each null or a dict with exactly `{path, sha256, base_model, rank, alpha, steps}`: absolute path, `SHA256_RE`, non-empty str, int `>= 1`, int `== rank`, int `>= 1` |
| `stills_skip_reason` | null or non-empty str |
| `strength` | null or int/float, not bool, `0 < v <= 1.0` |
| consistency | `status == "trained"` exactly when `loras.video` is set, exactly when `trained_at` is set; `untrained`/`trained` require `dataset` with `kept >= MIN_KEEP` |

`write_location` validates, then writes atomically (`<path>.<uuid4 hex>.tmp`, `os.replace`), as `character_lib.write_character` `:472-485`. File existence is not checked by validation.

### 3.8 Base model and compatibility (L2.8)

`location_lib.VIDEO_BASE_MODEL = "dgrauet/ltx-2.3-mlx-q8"`. `location_lib.model_compatible(base_model, model)` is True when `model == base_model`, or when `base_model == VIDEO_BASE_MODEL` and `os.path.realpath(os.path.expanduser(model)) == os.path.realpath(os.path.join(os.path.expanduser(os.environ.get("LTX2_MLX_DIR", "~/ltx-2-mlx")), "models", "ltx-2.3-mlx-q8"))` (the local copy the test clips render with) **[spec choice]**. Otherwise the video LoRA is not attached (L3.1). Stills LoRAs always attach: their base is Z-Image-Turbo whatever `--model` is.

### 3.9 Resolution (L2.9)

```python
LocationPin = collections.namedtuple("LocationPin", [
    "name", "trigger", "description", "video_lora", "stills_lora", "stills_skip_reason",
    "strength", "base_model", "attach_video"])
```
`resolve_locations(names)`: more than `MAX_LOCATIONS = 3` → `LocationError("at most 3 locations, got N")`; a repeated name → `LocationError("location NAME is pinned more than once")`; per name, a load failure, a status other than `trained`, or a video LoRA that is not a readable non-empty file → `UnusableLocationError` (`location NAME is not trained (status S); run bin/location train NAME`, `location NAME's video LoRA is missing or empty: PATH`); a recorded stills LoRA that is not readable and non-empty → `LocationError`; two pins sharing a trigger → `LocationError`. Returns pins in order with `attach_video=True`. `usable_locations()` = sorted names that resolve alone; `format_available_line(names)` = `available locations: a, b` or `available locations: none (create one with bin/location create)`.

### 3.10 Character refactor (L2.10, `character_dataset.py`)

Two new functions hold the bodies of `train_video` and `train_stills`; the old functions become wrappers with unchanged signatures. Both cores call the module-global names (`run_logged`, `run_zimage_child`, `step_log_path`, `SKILL.generate_video`, `_sha256`, `character_lib.utc_now`, the constants) so every existing monkeypatch keeps working.

```python
def train_video_lora(owner_dir, videos_dir, captions_dir, prompt, failed_note, recorded, tested):
    """Preprocess, train, copy and A/B-test a video LoRA (character library spec 4.8; location
    library spec L2.10). Returns "ok", "failed" or "test_failed". recorded(entry) is called once,
    after the final checkpoint is copied to <owner_dir>/lora/video.safetensors, with
    {"path", "sha256", "rank", "alpha", "steps"}; tested(key, path) after each successful test
    clip ("sample_path" then "control_path"). failed_note ends the failure line."""

def train_stills_lora(owner_dir, pairs, prompt, seed, kept_ok, skipped):
    """Train a stills LoRA with mflux on pairs [(png, txt)] and keep it only if it passes the
    compat gate (character library spec 4.9; location library spec L2.10). Returns "ok",
    "skipped" or "failed". kept_ok(entry, sample_path, control_path) with {"path", "sha256",
    "rank", "alpha", "steps"}; skipped(reason) with the full stills_skip_reason."""
```

- `train_video_lora` is `:1413-1488` with: `char_dir` → `owner_dir`; `dataset/videos` and `dataset/captions` → the arguments; `trigger_test_prompt(...)` → `prompt`; `_video_failed(data, step, rc, log)` → `_video_failed(failed_note, step, rc, log)` printing `"Error: video LoRA training failed at %s (exit %s); log: %s; %s" % (step, rc, log, failed_note)`; the record writes → `recorded(...)`/`tested(...)`. The final four prints move to the character wrapper.
- `train_stills_lora` is `:1641-1741` with: `char_dir` → `owner_dir`; the manifest read and the copy loop → copy each `(png, txt)` to `train/stills/data/<basename>`; `len(kept_ns)` → `len(pairs)`; `data["seed"]` → `seed`; the reject branch → `skipped(full_reason)` then the existing print; the success branch → `kept_ok(...)` then the existing three prints.
- `train_video(data)` computes `prompt = trigger_test_prompt(trigger, class_noun)`, `failed_note = "character %s stays %s" % (name, status)`, `recorded` (sets `loras.video` with `base_model=TRAIN_MODEL_DIR`, `trained_at=character_lib.utc_now()`, `sample_path=None`, `control_path=None`, `status="trained"`, writes), `tested` (sets the key, writes), calls the core, and prints the existing four lines.
- `train_stills(data)` reads `dataset/manifest.json` kept n, builds the `char_NN` pairs, and calls the core with callbacks that build the existing entry (`base_model "Tongyi-MAI/Z-Image-Turbo"`, `trained_at`, `sample_path`, `control_path`) and `stills_skip_reason`.
- The only reorder: `train_stills` now reads `manifest.json` before `train/stills` is recreated. Every observable output on the paths LG1-LG3 and the existing D20-D34 tests exercise is identical.

### 3.11 Acceptance (L2)

- `train` with fakes records both LoRAs with the exact entry shapes, writes the two test clip requests (prompt, 512x320x25, seed 42, with and without the LoRA), and ends `trained`.
- Every preflight refusal happens before any training process starts, in the L2.2 order.
- A compat-gate failure leaves `stills.rejected.safetensors`, `stills_skip_reason` set, status `trained` (video ok), exit 0 (1 with `--stills`).
- The character golden record is byte-identical before and after (LK4).
- Tests: LD19-LD24, LL6-LL9, LG1-LG3, LT9-LT10.

---

## 4. L3 Story use

### 4.1 `bin/ltx-movie` flags and resolution (L3.1)

Parser, directly after `--character-strength` (`:355-360`):
```python
    parser.add_argument("--location", dest="locations", action="append", default=None,
                         metavar="NAME",
                         help="pin a trained location from generated/locations/ (repeatable, at "
                              "most 3): the story plan sets at least one beat there with the "
                              "location's fixed setting, and only the panels set there render "
                              "with its LoRAs and trigger. See docs/superpowers/specs/"
                              "2026-10-29-location-lora-design.md.")
    parser.add_argument("--location-strength", dest="location_strength", type=float,
                         default=None,
                         help="LoRA strength for each pinned location without its own "
                              "location.json strength (default 0.8), on every panel set there")
```

`_resolve_story_engine`'s legacy flag list (`:1044-1048`) gains `("--location", bool(args.locations))`, so `--location` with `--story-legacy` or `--story-prompt-override` prints the existing `Error: --location needs the default story engine; it cannot be combined with ...` and exits 2.

New `_location_lib()` (path loader, like `_character_lib`) and `_resolve_locations(args)`, called in `main` right after `_resolve_story_engine` (`:2588-2590`) and before the dry-run branch. Returns 0 or 2 after one `Error:` line; sets `args.location_pins` and `args.location_strength`:
1. No `--location`: `--location-strength` given → `Error: --location-strength requires --location`; else `args.location_pins = []`, return 0.
2. `--no-stills` → `Error: --location is not supported with --no-stills: location LoRAs attach to chained or shots panels`.
3. Strength = `--location-strength` or `location_lib.DEFAULT_LOCATION_STRENGTH` (0.8); outside `(0, 1]` → `Error: --location-strength must be in (0, 1], got S`.
4. `resolve_locations(names)`: `UnusableLocationError` → its message plus `format_available_line(usable_locations())`; `LocationError` → its message.
5. A pin whose trigger equals a cast member's trigger → `Error: location NAME and character CNAME share the trigger T`.
6. For each pin with `not model_compatible(pin.base_model, args.model)`: `pin._replace(attach_video=False)` and `Warning: location NAME's video LoRA was trained for BASE, not --model MODEL; it is not attached, and the panels set there render without it (its setting and stills LoRA still apply)` on stderr.
7. Existing story (L3.2).

### 4.2 Story pins (L3.2)

Pins are recorded in `plan.json`: each pinned plan location carries `"location_name"` (L3.4), as cast entries carry `"cast_name"`. When `story.md` exists and `--force-story` is not given, `_resolve_locations` reads `location_lib.plan_location_names(story_dir)`:
- it returns None when `plan.json` is missing, not a JSON object, not `ltx-movie.plan.v1`, or its `locations` is not a list of objects; else the set of non-empty str `location_name` values;
- None and `--location` given: `note: <story_dir>/plan.json is not a usable plan; --location gets no LoRA in this story (location LoRAs attach only to planned beats)`, continue;
- a set different from `set(names)` (either direction, including a story with pinned locations and no `--location`): `Error: story ID was planned with the locations [A, B], not --location [C]; pass the same --location flags, or --force-story to plan a new story` (sorted, comma-joined, `none` for the empty set), exit 2 **[spec choice]**.

### 4.3 Plan prompt (L3.3, `story_engine.py`)

- `StoryContext` (`:92-97`) gains a last field `"locations"`; defaults become `(True, None, None, None, ())`.
- `_story_context` (`bin/ltx-movie:1515-1523`) passes `locations=list(getattr(args, "location_pins", None) or [])`.
- `PLAN_PROMPT_TEMPLATE` line `:338` `"background.\n"` becomes `"background.@@LOCATION_FIXED@@\n"`.
- New constants immediately after `CAST_FIXED_LINE` (`:1060`), with the comment `# Location library spec L3.3: the pinned places, by library name, each set in a beat.`:

```python
LOCATION_FIXED_INTRO = (" The following places are already set; list them first in locations "
                        "with exactly these ids and settings, and give your own places the next "
                        "ids. Every one of them is in this movie: give each one's id as the "
                        "location of at least one beat. When the narrative names or describes "
                        "one of them, it means that place:")
LOCATION_FIXED_LINE = '\n- id l%d, name "%s", setting "%s"'
FIXED_SETTING = "The setting is %s."
```
- In `build_plan_prompt`, after the cast block (`:1075-1078`): `location_fixed = ""`; when `ctx.locations`: `LOCATION_FIXED_INTRO` + `LOCATION_FIXED_LINE % (i, pin.name, FIXED_SETTING % pin.description)` for each pin from 1. The fragment `("@@LOCATION_FIXED@@", location_fixed)` follows `("@@CAST_FIXED@@", cast_fixed)` (`:1104`).
- Without pins the token becomes `""`, so every plan prompt is byte-identical to `d210c26` (LS1 fixtures).

### 4.4 Plan normalisation (L3.4)

Immediately before `plan["locations"] = locations` (`:1268`):
```python
    # Location library spec L3.4: pinned locations are l1..lK with their library setting.
    if ctx.locations:
        for entry in locations:
            entry["location_name"] = None
        for i, pin in enumerate(ctx.locations, start=1):
            fixed = {"id": "l%d" % i, "setting": FIXED_SETTING % pin.description,
                     "location_name": pin.name}
            at = [j for j, entry in enumerate(locations) if entry["id"] == fixed["id"]]
            if at:
                locations[at[0]] = fixed
            else:
                locations.insert(i - 1, fixed)
```
Immediately before `plan["beats"] = beats` (`:1287`):
```python
    if ctx.locations:
        by_name = dict((pin.name, "l%d" % i) for i, pin in enumerate(ctx.locations, start=1))
        for beat in beats:
            beat["location"] = by_name.get(beat["location"].lower(), beat["location"])
```
A beat location written as a pinned library name resolves to its id **[spec choice]**. Without pins, no location entry gains a key and `plan.json` is byte-identical. The critic and `judge-story --patches` cannot change a pinned setting: `location.setting` is `NOT_REPAIRED` (`:3917`).

### 4.5 P21 location presence (L3.5)

Immediately before `# Speaker attribution spec SA2, D3` (`:2246`):
```python
    # Location library spec L3.5: every library location is the location of some beat.
    used = set(beat["location"] for beat in beats)
    for entry in plan["locations"]:
        if entry.get("location_name") and entry["id"] not in used:
            hard.append("plan: P21 location presence: %s (library location %s) is the location "
                        "of no beat; every already-set place is in this movie, so give at least "
                        "one beat the location %s" % (entry["id"], entry["location_name"],
                                                       entry["id"]))
```
- The `plan_checks` docstring's hard list gains ", P21 (a library location that is the location of no beat; location library spec L3.5)".
- `plan_round` already retries it (`:4433-4446`); `PLAN_MAX_CALLS` stays 2.
- The fatal filter (`:4640`) becomes `("P1", "P2", "P16", "P17", "P21")`, with the comment line extended by "or sets no beat at a library location". Exhaustion prints the existing three-part error and exits 1 with no story.md and no plan.json.
- `_VIOLATION_RE` parses `plan: P21 location presence: ...` (id `P21`, name `location presence`, scope `plan`).

### 4.6 L4 count (L3.6)

In `lora_checks`, before the per-beat loop: `by_location = {l["id"]: l for l in plan["locations"]}` and `attached = set(pin.name for pin in ctx.locations if pin.attach_video)`. In the loop, `loc = by_location.get(beat.get("location"), {}).get("location_name")`, and `loras_k` (`:2378-2381`) inserts `[("location " + loc, "location", None, None)] if loc in attached else []` after the per-beat picks and before the characters. L4 therefore counts the location LoRA; L3 does not (its kind is not motion/physics). No render-side advisory is added; none exists (0.2).

### 4.7 Manifest attach (L3.7, `bin/ltx-story-manifest`)

- Parser: `--location NAME` (append, dest `location`) and `--location-strength` (float). `--location` without `--chain`/`--shots` → `parser.error("--location requires --chain or --shots")`; `--location-strength` without `--location` → `parser.error("--location-strength requires --location")`.
- After the casting block (`:866-894`) and before the catalog block (`:896`), when `args.location`:
  1. `pins = location_lib.resolve_locations(args.location)`; `LocationError` → `Error: <message>`, exit 2. Strength default 0.8, `(0, 1]` else exit 2.
  2. `per_panel, note = location_lib.plan_panel_locations(os.path.join(WS, "generated", "stories", args.story_id), n_panels, [p.name for p in pins])`; print `note` when not None.
  3. For each panel: `name = per_panel[i]`; with a name, `p["locations"] = [{"name": name, "video_lora": pin.video_lora, "strength": pin.strength if pin.strength is not None else strength}]` and `p["motion_prompt"] = location_lib.prefix_location_trigger(p["motion_prompt"], pin.trigger)`; else `p["locations"] = []`.
  4. `WARNING: location NAME is the location of no panel's beat in plan.json; it gets no LoRA` for each unused pin.
- After the cast summary (`:947-951`): `location: panel %d: %s@%s` for each panel with a location.
- Trigger order on a panel: catalog triggers, then the location trigger, then character triggers (`"cattrig. harboplc. kyrawmn. ..."`) because the location step runs after casting and before the catalog step.
- `schema_version` stays 3 (the key is optional).

`location_lib.plan_panel_locations(story_dir, n_panels, names)` → `(list of n_panels name-or-None, note-or-None)`:
- missing `plan.json`: all None, note `note: there is no plan.json for this story; no location LoRAs are attached (location LoRAs attach only to planned beats)`;
- unusable: all None, note `note: plan.json is not usable for locations (REASON); no location LoRAs are attached`, REASON one of `it is unreadable or not a JSON object`, `its schema is not ltx-movie.plan.v1`, `its locations are not a list of objects`, `it has B beats for N panels`, `beat K has no location id`;
- usable: panel k's name is `by_id.get(beats[k-1]["location"])` when it is in `names`, else None; `by_id` maps each location entry's str `id` to its `location_name`.

`location_lib.prefix_location_trigger(prompt, trigger)`: `prompt` when `trigger` already occurs as a whole word (`(?<![\w-])T(?![\w-])`, case-insensitive), else `trigger + ". " + prompt` (the rule of `character_lib.prefix_character_triggers`, `:905-919`, for one trigger).

### 4.8 Stills attach (L3.8, `bin/ltx-story-images` and `bin/ltx-movie`)

`bin/ltx-story-images`:
- Parser: `--location NAME` (append), `--location-strength` (float). `--location-strength` without `--location` → `Error: --location-strength requires --location`, exit 2.
- After casting is resolved (`:273`), when `args.location`: resolve (exit 2 on error); strength (default 0.8); `per_panel, note = plan_panel_locations(os.path.dirname(os.path.abspath(args.story_md)), len(panels), names)`; print the note; `WARNING: location NAME has no stills LoRA (REASON); its trigger is not added to Image: prompts and its panels render without it` for a pin without one.
- `loc_plans[i] = (trigger, {"kind": "location", "name": name, "path": pin.stills_lora, "strength": s})` for each selected generated panel at a pin with a stills LoRA (`s` = pin strength or `--location-strength`; panel 1 with `--seed-image` is skipped).
- The legacy-route test (`:313`) also requires `not loc_plans`; a global `--lora` equal to a location stills LoRA → `Error: --lora PATH is also location NAME's stills LoRA; pass it once`, exit 2.
- `plans` (`:334-339`) are built when `members or global_stills or loc_plans`: `plans[i] = (prefix_location_trigger(prompt, trigger), global_stills + [entry] + chars)` for a location panel, else as today. The prompt comes from `char_plans` or `compose(panels[i - 1]["image"], style)`. The new code calls `compose(` only, so `_compose_prompt(` stays at exactly 3 occurrences and `_panel_seed(args.seed, i, grounded)` at 2 (I20).
- The one-set-per-process refusal (`:340-344`) and the `--lora-trigger` prefix (`:345-352`) are unchanged and run after.

`bin/ltx-movie`:
- `_location_flags(args, video=False)`: `[]` without pins; else `["--location", NAME]` per pin (only `attach_video` pins when `video`) plus `["--location-strength", repr(float(args.location_strength))]`; `[]` when no pin qualifies. Appended right after `_cast_flags(args)` at `:1929` and `:2447` (stills) and `:2118` and `:2472` (`video=True`).
- `_shots_stills_groups(story_md_path, members, locations=())`: with pins that have a stills LoRA, per-panel names come from `plan_panel_locations(os.path.dirname(story_md_path), len(panels), names)`, and a panel's key becomes `names + ("location " + name,)`. With `locations=()` the output is unchanged (existing `test_shots_mode.py:1333-1347`). Both callers (`:1990`, `:2345`) pass `getattr(args, "location_pins", None) or []`.
- The dry run prints, after the cast block (`:2386-2392`), `--- Locations ---` and one line per pin: `location: NAME (trigger T; video LoRA PATH; stills LoRA PATH or "none: REASON"; strength S)`, with ` -- video LoRA not attached: trained for BASE` appended for a non-attachable pin.
- The new code adds no occurrence of the strings `tests/test_ltx_movie_offline.py` counts (0.2).

In chained mode only panel 1 gets a still, so only panel 1 can carry a location stills LoRA.

### 4.9 Render (L3.9, `bin/ltx-mlx-render`)

- `load_manifest`, after the `characters` block (`:236-257`): an optional `locations` list; each entry a dict with a non-empty str `name`, no repeats, an absolute readable `video_lora`, a number (not bool) `strength` in `(0, 1]`; at most one entry per panel. Errors: `panel N: locations must be a list`, `panel N: every locations entry needs a non-empty name`, `panel N: at most one location per panel`, `panel N: location NAME's video_lora is not a readable file: PATH`, `panel N: location NAME's strength must be a number in (0, 1], got S`.
- `build_units`, between the catalog style units and the characters (`:360-361`): `loras += [{"kind": "location", "name": l["name"], "path": l["video_lora"], "strength": float(l["strength"])} for l in (panel.get("locations") or [])]`. Final order: catalog motion/physics, global, catalog style, location, characters.
- `main`: `location_entries` (like `cast_entries`, `:1208`); the legacy route (`:1211`) also requires `not location_entries`; a global `--lora` equal to a location LoRA → `Error: --lora PATH is also location NAME's video LoRA (panel N); pass it once`; a catalog LoRA equal to the panel's location LoRA → `Error: catalog LoRA ID (panel N) is also location NAME's video LoRA`.
- `use_video_only_character_loras` (`:523-528`) rewrites kinds `("character", "location")`; its docstring says "character and location".
- Provenance includes the location LoRA automatically (`:556-563`); panels without one keep identical provenance, so `--resume` reuses them.
- Model mismatch never reaches the render: ltx-movie does not pass the pin to the manifest (L3.1 step 6).

### 4.10 Phase 1 warnings (L3.10)

After a generated or re-checked story, `_phase1_robust` (`:1721-1731`) prints nothing new; P21 guarantees presence for generated stories. No post-writer check is added.

### 4.11 `bin/iterate-story` (L3.11)

`build_engine_cmd` (`bin/iterate-story:260-282`), after the cast loop: `for entry in plan.get("locations") or []: if isinstance(entry, dict) and entry.get("location_name"): cmd += ["--location", entry["location_name"]]`. The strength is not recorded and defaults to 0.8 **[spec choice]**.

### 4.12 Acceptance (L3)

- With pins, the plan prompt carries the intro and one line per pin; without pins it is byte-identical.
- A normalised plan has pinned entries `l1..lK` with `FIXED_SETTING`; P21 fires once per pinned location in no beat; retry then fatal as P16.
- The manifest attaches exactly the beats at pinned locations, in chained and shots modes; a legacy story gets the note and no LoRA.
- Stills: chained panel 1 and shots panels at a location get the stills LoRA and trigger; shots groups split by location.
- Render order puts the location between style and characters; the location LoRA is audio-stripped.
- Tests: LS1-LS14, LP1-LP20.

---

## 5. L4 Movie UI and lora-check

### 5.1 Routes and jobs (L4.1)

New `ROUTES` entries, after the character routes (`:74-79`), using `_NAME`:
```python
    ("GET", r"/api/locations", "h_locations", "/api/locations"),
    ("POST", r"/api/locations", "h_location_create", "/api/locations"),
    ("GET", r"/api/locations/" + _NAME, "h_location", "/api/locations/harbour-street"),
    ("PATCH", r"/api/locations/" + _NAME, "h_location_patch", "/api/locations/harbour-street"),
    ("POST", r"/api/locations/" + _NAME + r"/train", "h_location_train",
     "/api/locations/harbour-street/train"),
    ("POST", r"/api/locations/" + _NAME + r"/regenerate", "h_location_regenerate",
     "/api/locations/harbour-street/regenerate"),
```
`_handle` (`:378`) reads a body for `("POST", "PUT", "PATCH")`. Jobs: `location-create` and `location-regenerate` need the VLM (`job_vlm` returns `"required"`), `location-train` needs it stopped (`"forbidden"`). Each job is created like `create_character_job` with `character=fields["name"]`, so the Jobs table shows the name and progress is `elapsed_s` + `last_line` (`movie_ui_lib.py:2155-2157`).

`movie_ui_lib.location_argv(kind, fields, ws_real, state, py=sys.executable)`:
- `location-create`: `[py, <ws>/bin/location, "create", name]` + `["--description", d]` when set + `["--photo", <state>/uploads/<id>]` per upload + `["--trigger", t]` when set + `["--seed", str(n)]` when set + `["--force"]` when true;
- `location-regenerate`: `[py, <ws>/bin/location, "create", name, "--regenerate"]` + `["--seed", str(n)]` or `["--new-seed"]` + `["--description", d]` when set + `["--force"]` when true;
- `location-train`: `[<ws>/bin/location-train-vlm, py, name]` + `--video`/`--stills`/`--force` as set.

### 5.2 Handlers (L4.2)

- `GET /api/locations?ws=`: `location list` (light run) → `{"locations": [...]}` from `LOCATION_ROW_RE = re.compile(r"^(\S+)\s+(\S+)\s+(dataset|untrained|trained)\s+(text|photos)\s+(yes|no)\s+(yes|no)\s+(.+)$")` → `{"name", "trigger", "status", "source", "video", "stills", "description", "invalid": None}`; invalid rows → `{"name", "invalid"}`; header and `no locations in` lines skipped.
- `GET /api/locations/<n>?ws=`: `location show NAME`; JSON via `raw_decode`, `files` via `FILE_LINE_RE` (`movie_ui_server.py:1114`); the location dir is the directory of the first files path ending `/location.json`. Response `{"location", "files", "manifest": <manifest.json items> | null, "contact_sheet": <path if a file> | null, "stills": [<dir>/stills/loc_NN.png for each manifest item whose file exists], "tests": {"video_lora": path | null, "video_control": path | null}, "last_create_fields": <newest location-create job fields> | null}`. A non-zero exit → 502.
- `POST /api/locations` (`location_create_errors`, then a `location-create` job). Rules, in order: `name` matches `[a-z][a-z0-9-]{1,23}`; `photo_uploads` is a list of at most 24 strings, each `UPLOAD_ID_RE` with an existing upload (`photo upload ID not found`, `give at most 24 photos`); `description` null/`""` or a str that is argv-safe, does not start with `-`, has no newline and has 15-40 words (`description must be 15 to 40 words`); no photos and no description (`give a description or at least one photo`); `trigger` null/`""` or `[a-z][a-z0-9]{3,15}`; `seed` null or int 0..2147483647; `force` bool. Errors → 400 `{"error": "invalid fields", "errors": [...]}`.
- `PATCH /api/locations/<n>`: body `{"ws", "description"}` with the description rules above; runs `location edit NAME --description TEXT` (light). Exit 0 → 200 `{"run"}`; exit 2 → 400 `{"error": <stderr last line without "Error: ">, "run"}` (this is how a text location's PATCH is refused); timeout → 504; other → 502.
- `POST /api/locations/<n>/regenerate`: body `{"ws", "seed"?, "new_seed"?, "description"?, "force"?}`; `seed` with `new_seed` true → 400 `give seed or new_seed, not both`; seed range; description rules; `force` and `new_seed` bools → `location-regenerate` job.
- `POST /api/locations/<n>/train`: the `_h_character_train` rules (`:1262-1275`) → `location-train` job.

### 5.3 Compose (L4.3)

- `DEFAULT_FIELDS` gains `"locations": []` and `"location_strength": None`; `FIELD_FLAGS` gains `("locations", ("--location",))` and `("location_strength", ("--location-strength",))` after `characters`.
- V1 rule 12c, after rule 12b (`:1405`): `locations` is a list of at most 3 distinct `[a-z][a-z0-9-]{1,23}` names (`locations must be at most 3 distinct location names`); `location_strength` null or a number in `(0, 1]` (`location strength must be a number in (0, 1]`); `location_strength` with no locations (`location strength needs at least one location`); locations with mode `no_stills` (`locations need chained or shots mode`).
- `build_argv`, after the `--character` loop (`:991-992`): `--location NAME` per name; then `--location-strength repr(float(s))` when locations are non-empty and `location_strength` is not None.

### 5.4 Page (L4.4)

`index.html`:
- `<button id="tab-locations" type="button" class="tab">Locations</button>` after `tab-characters`; `TABS` becomes `["compose", "stories", "characters", "locations", "actions", "loras", "jobs", "traces"]`; `showTab` calls `loadLocations()` for it; init's `Promise.all` (`:263`) adds `loadLocations()`; `setupLocations()` follows `setupCharacters()` (`:1493`).
- Compose, after `c-characters` (`:113`): `<label data-field="locations">Locations <select id="c-locations" multiple size="3"></select></label>` with `<span id="c-locations-note" class="muted"></span>`, and `<label data-field="location_strength">Location strength <input id="c-location-strength" type="number" min="0.05" max="1" step="0.05" placeholder="0.8"></label>`. The select lists trained locations only (`name (first 6 words of description...)`). Selecting a 4th deselects it and sets the note to `at most 3 locations`. Field collection adds `locations` (selected values) and `location_strength: numberOrNull("#c-location-strength")`; field restore selects saved names and fills the strength.
- `<section id="panel-locations" class="panel" hidden>`:
  - `lo-list` table: Name, Status, Source, Video, Stills, Description; a row click opens the detail.
  - Create form: `lo-name`; `lo-description` (`<textarea rows="3" cols="70">`) with `lo-words` showing `N words (15-40)`; `lo-trigger` (placeholder `blank = auto`); `lo-seed`; `lo-photos` (`<input type="file" multiple accept="image/png,image/jpeg,image/webp">`); the note `<p id="lo-angles-note" class="muted">Angles come only from your photos: every extra still keeps one photo's exact viewpoint and changes only its time of day, weather or season. For a varied dataset, upload 3-5 photos taken from different spots. Without photos, the 24 stills are drawn from the description.</p>`; `lo-create` and `lo-create-status`. Create is disabled while the name is invalid, more than 24 photos are chosen, or the description is non-empty and outside 15-40 words, or there are no photos and the description is outside 15-40 words. Photos upload one by one through the existing `uploadFile` (`:468`), then `POST /api/locations`.
  - Detail `lo-detail`: `lo-title` (`name (status, source)`); `lo-sheet` (the contact sheet image); `lo-stills`, one card per manifest item with the still, `photo`/`edit`/`generated`, `score N` or `score -`, `people` or `no people`, the caption, and `kept` or `dropped: REASON`; `lo-desc-edit` (textarea, the current description) with `lo-desc-save`, labelled `Save description` (photo mode, PATCH) or `Regenerate with this description` (text mode, POST regenerate with `description` and `force` from `lo-force`); `lo-regen` (`Regenerate (new seed)`, POST regenerate `{new_seed: true, force}`); `lo-force` checkbox `Force` with the title `keeps photos that show people; allows regenerating a trained location, which deletes its LoRAs`; `lo-accept` (`Accept dataset`, shows the train form); `lo-status`.
  - Train form `lo-train-form` (hidden until Accept): `lo-train-video` (checked), `lo-train-stills` (checked), `lo-train-force`, `lo-train`, `lo-train-reason`. Train is disabled with `fewer than 12 stills kept; regenerate the dataset` while the status is `dataset`, and goes through the existing `gate(..., ["render"])`.
  - `lo-tests`: when `tests.video_lora` and `tests.video_control` are set, two `<video controls>` side by side (`fileUrl(path)`), captioned `with the LoRA` and `without (control)`.
- No inline script or handler; everything is wired in `app.js` (the page CSP).

### 5.5 LoRAs & Models tab (L4.5)

- Add a LoRA gains `<label><input id="l-no-arch-check" type="checkbox"> Skip architecture check</label> <span class="muted">The LoRA is cataloged even if bin/lora-check says it does not fit the base model; a mismatched LoRA fails or does nothing at render.</span>`.
- `app.js` sends `no_arch_check: $("#l-no-arch-check").checked`. `_h_lora_add` reads `no_arch_check` (optional, default false; not a bool → 400 `no_arch_check must be true or false`) and appends `--no-arch-check` last. Output is shown in `#l-output` as now.
- The Verify column: `verdicts[r.id] = (r.ok ? "ok" : r.problems.join("; ")) + (r.warnings && r.warnings.length ? " | warning: " + r.warnings.join("; ") : "")`.
- `parse_verify`: `VERIFY_LINE_RE = re.compile(r"^(OK|FAIL|WARN) (\S+?)(?:: (.*))?$")`; every result gets `"warnings": []`; a `WARN` line appends its text and does not change `ok`.

### 5.6 Tool stubs (L4.6, tests only)

`tests/movie_ui_testutil.py`: `STUB_TOOLS` gains `"location"`; `STUB_SOURCE` prints `no locations in <ws>/generated/locations` for `location list` without a config entry. `tests/fixtures/movie_ui/ltx-movie-help-current.txt` gains the `--location NAME` and `--location-strength LOCATION_STRENGTH` lines exactly as `bin/ltx-movie --help` prints them after G6.

### 5.7 lora-check fix 1: bare 2-D parameters (L4.7)

In `base_linear_map` (`:158-177`), the loop also takes a key that does not end with `.weight`, does not end with any of `_QUANT_SUFFIXES` (`.scales`, `.biases`, `.zeros`, `.qweight`, `.qzeros`) or `.bias`, and has a 2-D shape: `out[_core(key)] = (shape[0], shape[1], False)` via `out.setdefault(...)` (a `.weight`-derived entry is never replaced). Such a key's quantized flag is False (scale/shift tables are F32 and unquantized). LoRA modules are matched as today (`_match_base`, out/in dims). So `transformer_blocks.N.scale_shift_table` `[9, 4096]`, top-level `scale_shift_table` `[2, 4096]` and the audio/prompt/a2v variants are base targets, as the ltx-2-mlx fuser already treats them (`fuse_loras.py:103-105`).

### 5.8 lora-check fix 2: the low-RAM warning (L4.8)

- `bin/lora-check` gains `LOW_RAM_WARNING = ("%d of %d modules are outside the transformer blocks and are skipped in low-RAM mode; render with --no-low-ram to use them")` and `low_ram_skipped(header)` → `(outside, total)`: `total = len(lora_targets(header))`, `outside` = modules whose name does not start with `"transformer_blocks."`. `static_check`'s signature, statuses and problems are unchanged.
- `main`: for a `video` target with `outside > 0`, the result gains `"warnings": [LOW_RAM_WARNING % (outside, total)]` (every result gets `"warnings"`, `[]` by default); text output prints `"    ! " + warning` after the problem lines. The status, the summary line and the exit code are unchanged.
- `bin/lora-catalog add`, video target: after the header is read and the arch gate (if any) has run, print `warning: <LOW_RAM_WARNING>` to stderr, also with `--no-arch-check`. The add's result and exit code are unchanged.
- `bin/lora-catalog verify`: for each selected video entry whose header reads, after that entry's `OK`/`FAIL` lines, print `WARN <id>: <LOW_RAM_WARNING>` when `outside > 0`. Neither the problem count nor the exit code changes. `lora-catalog` loads the checker with its existing `_load_checker()`; a load failure prints no warning.

### 5.9 Acceptance (L4)

- Every new route needs the token; PATCH reads its body; create, regenerate and train build the exact argv; text-mode PATCH is a 400 with the tool's message.
- Compose emits `--location`/`--location-strength` exactly when chosen; V1 refuses more than 3, a bad strength, a strength without locations, and no_stills with locations.
- lora-check matches bare tables, warns on low-RAM skips, and never changes PASS/FAIL or exit codes; the UI shows the warning in the Verify column.
- Tests: LU1-LU14, LC1-LC8.

---

## 6. L5 Errors and testing

### 6.1 Error table (L5.1)

| Condition | Where | Message (`Error: ` prefix unless noted) | Exit / effect |
|---|---|---|---|
| bad name | create/train/edit/show | `location name must match [a-z][a-z0-9-]{1,23}, got 'X'` | 2 |
| duplicate name | create | `location NAME already exists (DIR); use --regenerate to rebuild its dataset` | 2 |
| description word count / form | create, regenerate, edit | `--description: description: must be 15-40 words, got N` (and the other L1.3 reasons) | 2 |
| no photos and no description | create | `create needs --description or at least one --photo` | 2 |
| more than 24 photos | create | `at most 24 --photo, got N` | 2 |
| unreadable photo | create | `--photo is not a readable image: PATH: <error>` | 2 |
| missing photo | create | `--photo not found: PATH` | 2 |
| too-small photo | create | `--photo PATH is WxH; its centred 16:10 crop is CWxCH, smaller than the 512x320 minimum` | 2 |
| duplicate photo | create | `--photo PATH is the same file as photo K` | 2 |
| trigger taken / bad / description word | create | `trigger T is already used by NAME; triggers are never reused` / the TRIGGER_RE message / `trigger T must not be a word of the description` | 2 |
| editor not cached | create, regenerate (photo, P < 24) | `the photo editor is not downloaded: REPOS; download it with: hf download ...` | 2 |
| lock held | create/regenerate/edit/train | the existing `another bin/character create/train is running (pid N); run one at a time` | 2 |
| busy render/training | create/regenerate/train | `a render or training process is running (pid N: CMD); bin/location never trains or generates concurrently with a render` | 2 |
| disk below 2 GiB | create | `only X GiB free at LIB; create needs 2 GiB` | 2 |
| VLM down at preflight | create/regenerate | `the vision model M is not being served at URL; start it with: bin/story-server mlx-vision` | 2 |
| describe fails 3 times | create (photo, no description) | `describe failed: <reason>; last reply: <reply>` | 1, nothing written |
| VLM request fails mid-run | create/regenerate | `VLM request failed: ...` | 1, status `dataset` |
| check unparseable 3 times | create/regenerate | none (the still's reason is `unparseable: ...`) | still dropped (photo kept with `--force`) |
| Z-Image/edit child exits non-zero or times out | create/regenerate | `Z-Image child process exited N; log: PATH` / `Qwen-Image-Edit child process exited N; log: PATH` (N = -9 on timeout) | 1 after the server restore, status `dataset` |
| memory wait timeout | create/regenerate | `timed out waiting for N GiB available memory after stopping the story server` | 1 |
| server does not come back | create/regenerate | `timed out waiting for the vision server to come back` | 1 |
| fewer than 12 kept | create/regenerate | `only K/24 stills kept (need 12): <counts by reason, e.g. "5 people visible, 4 score below 7, 2 blocked by the content screen">; the dataset is kept in DIR; <fix>` with fix (text) `run bin/location create NAME --regenerate --new-seed, or --regenerate --description TEXT with a clearer description` or (photos) `create a new location with more photos that show no people, or run bin/location create NAME --regenerate --new-seed (--force keeps photos that show people)` | 3, status `dataset`, banner on the sheet |
| interrupt during create | create/regenerate | `aborted; the stills made so far are kept in DIR; run bin/location create NAME --regenerate to start again` | 1 (130 from a signal), detached restore |
| regenerate a trained location | regenerate | `location NAME is trained; regenerating its dataset deletes its LoRAs. Pass --force to regenerate it anyway` | 2 |
| `--description` on a photo regenerate | regenerate | `a photo location's stills come from its photos; change its description with bin/location edit NAME --description TEXT` | 2 |
| `edit` on a text location | edit | `location NAME is a text location: its stills are drawn from its description; run bin/location create NAME --regenerate --description TEXT (add --force when it is trained)` | 2 |
| train preflights | train | L2.2 | 2 |
| interrupted training | train | `location: interrupted` | 130; no resume, rerun train (with `--force` if a LoRA was recorded) |
| video training fails | train | `video LoRA training failed at STEP (exit N); log: PATH; location NAME stays STATUS` | 1, nothing recorded |
| stills compat gate fails | train | `stills LoRA skipped: mflux adapter incompatible with z_image_skill: ...; the video LoRA is unaffected` (stdout) | 0 (1 with `--stills`); `stills.rejected.safetensors` |
| unknown / untrained location pinned | ltx-movie, manifest, images | the UnusableLocationError text; ltx-movie adds `available locations: ...` | 2 |
| location deleted after Phase 1 | manifest | `Error: unknown location: NAME (no PATH)` | manifest 2 → ltx-movie Phase 3 exit 1 |
| more than 3 locations | ltx-movie, manifest, images, V1 | `at most 3 locations, got N` / V1 message | 2 / 400 |
| `--location-strength` without `--location` | ltx-movie, manifest, images | `--location-strength requires --location` | 2 |
| `--location` with `--no-stills` / legacy engine | ltx-movie | L3.1 | 2 |
| pinned location in no beat after the re-ask | Phase 1 | the three-part fatal error with the P21 message | 1, no story.md |
| reused story, different pins | ltx-movie | L3.2 | 2 |
| legacy story.md, no usable plan.json | ltx-movie, manifest, images | the `note:` lines of L3.2/L3.7 | continues, no location LoRA |
| model mismatch | ltx-movie | `Warning: location NAME's video LoRA was trained for BASE, not --model MODEL; ...` | continues, video LoRA not attached |
| UI field errors | movie-ui | 400 `invalid fields` with the L4.2/L4.3 lines | no job |

### 6.2 Test rules

- stdlib plus pytest; modules loaded by path with `importlib.machinery.SourceFileLoader` under test-unique names, as `tests/test_pinned_cast.py` does.
- Every test sets `HOME`, `CHARACTER_LIBRARY_DIR`, `LOCATION_LIBRARY_DIR` and `LORA_CATALOG_DIR` under `tmp_path`. `tests/story_engine_testutil.set_story_env` gains `LOCATION_LIBRARY_DIR = <tmp>/locations` (returned as `"locations"`), and `LINKED_FILES` gains `"location_lib.py"`.
- No real VLM, Z-Image, editor, mflux, ltx-2-mlx or render: `vlm_call`, `vlm_ready`, `story_server`, `restore_story_server`, `wait_for_avail`, `wait_for_vlm`, `story_server_state`, `busy_process`, `free_gib`, `edit_models_missing`, `run_logged`, `run_zimage_child`, `run_edit_child`, `SKILL.generate_video` and `psutil.virtual_memory` are replaced by fakes (the patterns of `tests/test_character_dataset.py:579-641` and `:968-998`). Real ffmpeg/ffprobe are used only for `wrap_still`, as the character tests do.
- The only server is the in-test movie-UI server on 127.0.0.1 (`movie_ui_testutil`). No test opens port 8177 or 8178.
- A new helper module `tests/location_testutil.py` (not collected) provides `make_location(lib, name, trigger, description, status="trained", source="text", stills=False, strength=None)`, which writes a valid `location.json` (L2.7) and, when trained, a 16-byte `lora/video.safetensors` (and `lora/stills.safetensors` when `stills`) with their real sha256, mirroring `tests/test_character_dataset.py:make_character` (`:50-88`).
- Each new test file's docstring states these rules.

### 6.3 Fixtures, generated at `d210c26` before any edit

**`tests/fixtures/location/character_train_golden.json`** is written by `python3 tests/test_location_golden.py --write-fixture` from `WS`, **before `character_dataset.py` is edited**. The test module's `golden_record()`:
1. creates a temp root; patches (with `unittest.mock.patch.object`/`patch.dict`, so it also runs as a script) `CHARACTER_LIBRARY_DIR`, `HOME`, `character_dataset.TRAIN_MODEL_DIR`/`TEST_MODEL_DIR` (temp dirs), `SKILL.LTX2_MLX_BIN` and `MFLUX_TRAIN` (an executable stub), `character_lib.utc_now` (returns `"2026-10-29T00:00:00Z"`), and the video fakes (`run_logged` and `SKILL.generate_video` as `tests/test_character_dataset.py:579-614`) and stills fakes (as `:968-998`);
2. builds an untrained character exactly as `_untrained` (`:554-576`);
3. runs four cases with stdout/stderr captured by `contextlib.redirect_stdout/redirect_stderr`: `train_video` happy path; `train_video` with preprocess exit 1; `train_stills` happy path; `train_stills` with `injected=1` (compat reject);
4. records per case: the outcome; every fake call (argv, cwd, `env["HF_HOME"]`, generate kwargs, child spec and step); `train.yaml` text or `train.json`; `character.json`; stdout; stderr; the sorted relative file list under the character dir;
5. serialises with `json.dumps(record, indent=2, sort_keys=True)`, replaces the temp root with `<TMP>`, and replaces `\d{8}T\d{6}Z` with `<STAMP>`.

**`tests/fixtures/location/`** plan fixtures, written before `story_engine.py` is edited:
```python
import importlib.machinery, json, os, sys, tempfile
WS = os.getcwd(); sys.path.insert(0, os.path.join(WS, "tests"))
import story_engine_testutil as seu
tmp = tempfile.mkdtemp(); lib_dir = os.path.join(tmp, "characters"); os.makedirs(lib_dir)
os.environ["CHARACTER_LIBRARY_DIR"] = lib_dir; os.environ["HOME"] = tmp
se = importlib.machinery.SourceFileLoader("se_loc_fix", os.path.join(WS, "story_engine.py")).load_module()
cl = importlib.machinery.SourceFileLoader("cl_loc_fix", os.path.join(WS, "character_lib.py")).load_module()
seu.kyra(lib_dir); seu.ronin(lib_dir)
members = cl.resolve_cast([(None, "kyra"), (None, "ronin")])
ws = seu.make_ws(tempfile.mkdtemp())
out = os.path.join(WS, "tests", "fixtures", "location"); os.makedirs(out, exist_ok=True)
for name, kw in {"plan_prompt_chained.txt": dict(mode="chained"),
                 "plan_prompt_shots.txt": dict(mode="shots", panels=4),
                 "plan_prompt_chained_cast.txt": dict(mode="chained", members=members)}.items():
    with open(os.path.join(out, name), "w", encoding="utf-8") as f:
        f.write(se.build_plan_prompt(seu.make_ctx(se, ws, **kw), [], []))
plan, _shape = se.normalize_plan(seu.make_ctx(se, ws), seu.plan_json("chained", 3))
with open(os.path.join(out, "normalized_plan_chained.json"), "w", encoding="utf-8") as f:
    json.dump(plan, f, indent=2, sort_keys=True)
```

### 6.4 `tests/test_location_lib.py` (LL)

| ID | Covers (exact assertions) |
|---|---|
| LL1 | **Compile.** `py_compile` under `/usr/bin/python3` and `sys.executable` of `location_lib.py`, `location_dataset.py`, `bin/location`, `story_engine.py`, `character_dataset.py`, `bin/ltx-movie`, `bin/ltx-story-manifest`, `bin/ltx-story-images`, `bin/ltx-mlx-render`, `bin/iterate-story`, `bin/lora-check`, `bin/lora-catalog`, `movie_ui_lib.py`, `movie_ui_server.py`; `bash -n bin/location-train-vlm` (LK3) |
| LL2 | **Description rule.** `normalize_description("  The  old mill by the weir.")` → `"the old mill by the weir"`; 15 and 40 words pass; 14 and 41 fail with `must be 15-40 words`; `"a quay. With ..."`, `"a quay! ..."`, a `"` and a newline each fail with the rule-4 message; a start other than a/an/the fails |
| LL3 | **Arithmetic.** For W in 15..40, `len(("The setting is %s." % d).split()) == W + 3` and `_setting_problems` and `_setting_length` (story_engine) return no problem; for W = 15 the shots S-rule minimum (12) holds |
| LL4 | **Triggers.** `auto_trigger("harbour-street", D, set())` → `"harboplc"`; with it taken → `"harboplc2"`; a character trigger in the character registry is in `all_triggers()`; a description word is never chosen |
| LL5 | **Registry.** `register_trigger` appends `"<t> <name>\n"`; `registered_triggers()` unions the registry and records; triggers are never reused after a failed create |
| LL6 | **Validation table.** Every row of L2.7: a valid trained, untrained, text and photo record pass; each single-field violation raises `LocationError` whose message starts with the field name; the consistency rules (trained without video, video without trained_at, untrained with 11 kept) fail |
| LL7 | **I/O.** `write_location` is atomic (no `.tmp` left on success or on a validation error); `load_location` wraps errors as `invalid location.json for NAME: ...` and an absent record as `unknown location: NAME (no PATH)`; `list_names` skips non-matching dirs |
| LL8 | **Resolution.** `resolve_locations` returns pins with `attach_video=True`; 4 names → `at most 3 locations, got 4`; a repeat; untrained → UnusableLocationError text; an empty video LoRA; a missing recorded stills LoRA; a shared trigger. `format_available_line([])` and with two names |
| LL9 | **Model compatibility.** True for `"dgrauet/ltx-2.3-mlx-q8"`; True for the `LTX2_MLX_DIR/models/ltx-2.3-mlx-q8` path (temp `LTX2_MLX_DIR`, symlinked path too); False for `MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8` and `~/ltx-2-mlx/models/ltx-2.5-mlx-q8` |
| LL10 | **Trigger prefix.** `prefix_location_trigger("A street.", "harboplc")` → `"harboplc. A street."`; unchanged when present as a whole word (any case); not matched inside `xharboplc` |
| LL11 | **Plan reader.** `plan_panel_locations`: missing plan → all None + the missing note; each unusable REASON gives its note; a usable plan maps pinned names only; an unpinned or unknown id gives None. `plan_location_names`: None for missing/bad, the set otherwise |
| LL12 | **Table.** `location_table_lines()` header, a row with the exact `LIST_ROW_FORMAT`, an invalid row, the empty-library line |
| LL13 | **Stdlib only.** Importing `location_lib` in a subprocess with `-I` loads no `PIL`, `psutil`, `torch` or `character_dataset` module, and `character_lib` only after `all_triggers()` is called |
| LL14 | **Strength rule.** `strength` 1.0 passes, 0 and 1.01 and `True` fail |

### 6.5 `tests/test_location_dataset.py` (LD) and `tests/test_location_tool.py` (LT)

| ID | Covers |
|---|---|
| LD1 | `VARIANTS` equals the L1.5 table written out in the test; the time/weather counts and per-view distinct times; `gen_prompt` for n 1, 11 and 24 equals the literal strings |
| LD2 | `EDIT_PROMPT`, `EDIT_CONDITIONS` (23 entries), `DESCRIBE_*`, `CHECK_*`, `TAG_PROMPT`, `CHECK_RETRY` equal the Section 2 literals written out in the test |
| LD3 | `validate_location_check`: scored and unscored; each alias; bool score refused; bad shot/time/weather refused |
| LD4 | Check retries: an unparseable first reply → the second call carries `CHECK_RETRY` with the error and reply; three unparseable → `(None, "unparseable: ...")`; a RuntimeError propagates |
| LD5 | **Text create (LK6).** Fakes record one Z-Image child spec with the 24 `gen_prompt` jobs, `seed`, 1024x640, `loras: None`, step `generate`; `story_server("stop")` once; restore with `wait=True`; 24 text-scored checks; with 20 passes and 4 fails → `untrained`, `dataset.kept == 20`, exit 0, `next:` line printed |
| LD6 | Photo fit: a 4000x3000 photo becomes a 1024x640 centred crop (pixel-compared with `ImageOps.fit`); `photo_NN.png` is the oriented original; the record's `photos` has the path and the file sha256 |
| LD7 | Photo size: 512x320 accepted (crop 512x320); 511x320 refused (crop 511x319); 2000x319 refused (crop 510x319); the exact refusal text. LD26: 750x422 accepted with the 1.52x warning; no warning on a refusal |
| LD8 | Photo describe: without `--description`, `describe` gets the first 5 photos; a 45-word reply triggers `DESCRIBE_SHORTEN` with text only; a 10-word reply triggers `DESCRIBE_RETRY` with images; 3 failures → exit 1 and no location dir |
| LD9 | **Round robin (LK6).** For P in 1, 3, 5: the edit spec has `24 - P` jobs; job j's `image` is `stills/loc_%02d.png % (((j-1) % P) + 1)`, prompt `EDIT_PROMPT % EDIT_CONDITIONS[j-1]`, output `loc_%02d.png % (P + j)`, `skill == "location_edit"`; P = 24 runs no edit child and never stops the server |
| LD10 | Edit-model gate: `edit_models_missing()` non-empty → exit 2 before any VLM call or directory |
| LD11 | Keep rules: generated score 6 → `score 6`; score 9 with people → `people visible`; blocked file → `blocked by the content screen`; user photo with people dropped, and kept with `--force` with the `kept by --force:` reason; a forced unparseable photo captioned `"<trigger>, " + STYLE + "."` |
| LD12 | Captions: the exact example caption; `empty of people` absent when people are visible |
| LD13 | `manifest.json` item shape for each source; `reference` and `generator` values per mode |
| LD14 | Contact sheet: 5 columns, banner text `kept K of 24 (need 12)`, a red outline on a dropped cell (pixel check), labels per L1.11 |
| LD15 | **Too few (exit 3).** 11 kept → exit 3, status `dataset`, the exact message with the counts by reason and the mode's fix |
| LD16 | Child failure and timeout (`run_zimage_child` raises DatasetError with exit -9) → exit 1, the story server restored, status `dataset` |
| LD17 | Interrupt during the child → detached restore (`wait=False`), the abort message, exit 1 |
| LD18 | **Child extension (character_dataset).** With fake torch/diffusers (as `test_d44_child_qwenedit`), a spec with per-job `image` opens each distinct path once and edits each job from its own image; `skill` reaches `content_safety`; a character-shaped spec behaves exactly as before (same calls) |
| LD19 | Train preflight order (as `test_d26`): each refusal in the L2.2 order with the location texts; no process started |
| LD20 | Train video: the core is called with `videos`/`captions`, the L2.3 prompt and failed note; the record's `loras.video` has exactly the six keys with `base_model "dgrauet/ltx-2.3-mlx-q8"`; `trained_at` set; two generate calls (with LoRA at 1.0, without), 512x320x25, seed 42 |
| LD21 | Train stills: pairs are the kept `loc_NN` pairs in manifest order; the six-key entry; `stills_skip_reason` cleared |
| LD22 | Compat reject: `stills.rejected.safetensors`, `stills_skip_reason` starts `mflux adapter incompatible with z_image_skill: `, exit 0; with `--stills` exit 1 |
| LD23 | Retrain needs `--force`; `--force` retrains video and leaves stills |
| LD24 | Regenerate: seed rules; text `--description` replaces it; photo `--description` refused; trained without `--force` refused; trained with `--force` deletes `lora/`, `tests/`, `train/` and nulls the LoRAs; `photos/` and `logs/` survive; the seed is persisted only after every preflight passed (a refused run leaves the record unchanged) |
| LT1 | `bin/location --help` and each subcommand's `--help` exit 0 and list the L1.2 flags |
| LT2 | `list`/`show` run under `-I` with only stdlib importable (no PIL on `sys.path` via a temp `PYTHONPATH` shim) |
| LT3 | `show` prints the record then `files:` with `location.json` first and ok/MISSING per path |
| LT4 | Create argument refusals of L5.1 (name, duplicate, words, no input, >24 photos, missing/unreadable/small/duplicate photo, trigger rules, `--new-seed` without `--regenerate`) each exit 2 with the exact text and create nothing |
| LT5 | `--regenerate` refusals: `--photo`, `--trigger`, `--seed` with `--new-seed`, out-of-range seed |
| LT6 | `edit`: photo location saved and printed; text location refused with the L5.1 text; under a held lock → exit 2 |
| LT7 | PIL missing → re-exec under `$CHARACTER_PYTHON` once (marker `LOCATION_REEXEC`), as `bin/character` |
| LT8 | SIGTERM during a faked long create → `location: interrupted`, exit 130 |
| LT9 | `bin/location-train-vlm`: with stub `story-server`, `story-server-restore` and `location`, it stops the VLM, runs `location train NAME --video`, restores on exit 0, on exit 1 and on SIGTERM (as the character-train-vlm tests) |
| LT10 | `train` with neither flag requests both kinds; disk need is 16 GiB for both |

### 6.6 `tests/test_location_golden.py` (LG)

| ID | Covers |
|---|---|
| LG1 | `golden_record()` after L2.10 equals `tests/fixtures/location/character_train_golden.json` byte for byte (LK4) |
| LG2 | `train_video_lora` and `train_stills_lora` exist with the L2.10 signatures; `train_video(data)` and `train_stills(data)` still take one argument |
| LG3 | Running `tests/test_character_dataset.py` and `tests/test_character_tool.py` in a subprocess gives only the baseline `test_d2` failure |

### 6.7 `tests/test_location_story.py` (LS)

Helpers: `HARBOUR_DESC` (a 24-word description), `TEMPLE_DESC` (a 30-word description); `_pin(name, desc, attach=True)` builds a `location_lib.LocationPin`; contexts via `seu.make_ctx(se, ws, locations=[...])`.

| ID | Covers |
|---|---|
| LS1 | **Byte identity (LK5).** The three plan-prompt fixtures and `normalized_plan_chained.json` equal the current outputs for the same contexts; no plan location has `location_name` without pins |
| LS2 | Constants equal the L3.3 literals; `PLAN_PROMPT_TEMPLATE` contains `"background.@@LOCATION_FIXED@@\n"` |
| LS3 | With two pins the prompt contains `LOCATION_FIXED_INTRO + '\n- id l1, name "harbour-street", setting "The setting is %s."' % HARBOUR_DESC + '\n- id l2, name "temple-gate", setting "The setting is %s."' % TEMPLE_DESC`, directly after the locations sentence |
| LS4 | `normalize_plan` with pins: a raw plan with its own l1 and l2 → pinned l1, l2 replace them; a raw plan with only l1 → l2 inserted at index 1; unpinned entries get `location_name: None`; a beat location `"Harbour-Street"` becomes `"l1"` |
| LS5 | Setting is fixed: the raw plan's own l1 setting is discarded for `FIXED_SETTING % description`; `patch_ranges` still marks `location.setting` NOT_REPAIRED |
| LS6 | **P21 matrix (LK8).** For modes chained, shots, no_stills and missing sets `{l1}`, `{l2}`, `{l1, l2}`: exactly one P21 per missing pin in plan order, the exact text, `parse_violation` id `P21` scope `plan`; the complementary plan gives none; an unpinned location in no beat gives none |
| LS7 | **E2E retry.** `ltx_movie.main([...,"--location","harbour-street","--story-only","--no-review"])` through `seu.script_agent`: first plan reply misses l1, second has it → rc 0; stages start `["plan", "plan", "panel"]`; the second prompt contains `"YOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- " + <P21 message>`; `plan.json` l1 has `location_name "harbour-street"` |
| LS8 | **E2E exhausted.** Engine level, two bad replies → rc 1; stderr is the three-part fatal error with the P21 line; no story.md, no plan.json |
| LS9 | P21 together with P16: both messages listed in the retry |
| LS10 | **L4.** A beat at an attachable pin with 3 other LoRAs → L4 lists `location harbour-street` between the per-beat picks and the characters; a non-attachable pin is not counted |
| LS11 | Shots mode: every Image of a beat at l1 pastes `FIXED_SETTING % HARBOUR_DESC` (via `pasted_pieces`) |
| LS12 | `recheck` never calls `plan_checks` with pins (monkeypatched to raise) and returns as before |
| LS13 | `StoryContext` defaults: a context built without `locations` has `()`; `test_story_engine.make_ctx` contexts are unchanged |
| LS14 | `story_engine.py` gains no import line (AST comparison of import nodes with `d210c26` via `git show`, skipped outside a git checkout) |

### 6.8 `tests/test_location_pipeline.py` (LP) and `tests/test_location_ui.py` (LU) and `tests/test_lora_check_fixes.py` (LC)

| ID | Covers |
|---|---|
| LP1 | `_resolve_locations`: no flags → `[]`; strength without location; `--no-stills`; legacy engine (`--story-legacy`); strength range; unknown location with the available line; shared trigger with a cast member |
| LP2 | Model mismatch: `--model MLXBits/...` → the warning, `attach_video False`; `_location_flags(args, video=True)` is `[]`; stills flags still list the pin |
| LP3 | Existing story: matching pins pass; different pins (both directions) → exit 2 with the exact text; `--force-story` skips the check; no plan.json → the note |
| LP4 | Dry run prints the Locations block and the location flags in the Phase 2 and Phase 3 commands; no file is written |
| LP5 | **Manifest chained (LK7).** plan beats `[l1, l2, l1]` with pins harbour (l1) only → panels 1 and 3 get `locations` with `video_lora`, strength 0.8, and `"harboplc. "` prefixed; panel 2 `[]`; summary lines |
| LP6 | **Manifest shots (LK7).** the same with `--shots` and three images |
| LP7 | Manifest with cast and catalog: motion_prompt `"cattrig. harboplc. kyrawmn. ..."`; the record strength 0.6 wins over `--location-strength 0.9` |
| LP8 | Manifest legacy: no plan.json → the note once, every panel `locations == []`; an unusable plan (wrong beat count) → its note; an unused pin → the WARNING |
| LP9 | Manifest parser errors: `--location` without `--chain`/`--shots`; strength without location |
| LP10 | **Images chained.** `--dry-run` with `--only 1`: panel 1's loras line lists `harbour-street=<stills path>@0.8`, its prompt starts `harboplc. `; panel 1 with `--seed-image` gets none |
| LP11 | Images shots: panels at l1 get the location entry between global and character entries; a pin without a stills LoRA → the WARNING and no trigger; one-set refusal across different locations; `--lora` equal to the stills LoRA refused |
| LP12 | I20 counts: `_compose_prompt(` == 3 and `_panel_seed(args.seed, i, grounded)` == 2 after the change (the existing test passes) |
| LP13 | `_shots_stills_groups` with pins splits groups by `location NAME`; without pins equals the `test_shots_mode.py` expectations |
| LP14 | **Render units.** A manifest panel with characters, catalog style and motion, a global LoRA and a location → unit LoRA kinds in order `catalog, global, catalog, location, character`; without `locations` the units equal `d210c26`'s for the same manifest |
| LP15 | `load_manifest` location errors (each L3.9 message) |
| LP16 | Render duplicates: global `--lora` equal to the location LoRA; catalog equal to it |
| LP17 | Legacy route: one `--lora PATH` at 1.0 with a location panel → merged route (`args.lora_path is None`) |
| LP18 | `use_video_only_character_loras` rewrites a location LoRA with audio keys to the stripped copy (synthetic safetensors, `VIDEO_ONLY_LORA_DIR` in tmp) |
| LP19 | Provenance: a panel without a location has identical provenance to `d210c26`; adding a location changes only that panel's |
| LP20 | iterate-story `build_engine_cmd` adds `--location NAME` per pinned plan entry and nothing for an unpinned plan |
| LU1 | `ROUTES` has 46 entries; every new route needs the token (extends `test_mut18`) |
| LU2 | PATCH bodies are read; a PATCH without Content-Length → 411 |
| LU3 | `GET /api/locations` parses rows and invalid rows from stub output |
| LU4 | `GET /api/locations/<n>` returns manifest items, stills that exist, the sheet, tests clips and `last_create_fields` |
| LU5 | `POST /api/locations` text and photo bodies → exact argv; every L4.2 error line in order |
| LU6 | PATCH photo → 200 and argv `location edit NAME --description TEXT`; stub exit 2 → 400 with the stub's message; exit 1 → 502 |
| LU7 | Regenerate argv for new_seed, seed, description, force; seed with new_seed → 400 |
| LU8 | Train argv via `location-train-vlm`; `choose video, stills or both` |
| LU9 | `job_vlm`: create/regenerate `required`, train `forbidden` |
| LU10 | `build_argv` adds `--location`/`--location-strength`; V1 rule 12c messages; `FIELD_FLAGS` has 30 entries |
| LU11 | `_h_lora_add` appends `--no-arch-check` when true; non-bool → 400 |
| LU12 | `parse_verify` with OK, FAIL and WARN lines: warnings collected, `ok` unchanged |
| LU13 | Static page: ids `tab-locations`, `panel-locations`, `lo-*` (every id in L4.4), `c-locations`, `c-location-strength`, `l-no-arch-check` exist; `TABS` lists `locations`; the angles note text; no inline `on*=` attribute or inline script |
| LU14 | A `location-create` job's progress snapshot has `kind`, `elapsed_s` and `last_line` |
| LC1 | **Fix 1.** A base with `transformer.transformer_blocks.0.scale_shift_table [9, 4096]`, `transformer.scale_shift_table [2, 4096]` and linear weights; a LoRA on those tables and linears → PASS (was FAIL with `target modules absent`) |
| LC2 | `.scales`/`.biases` 2-D keys of a quantized weight are not base targets; a `.weight` entry is never replaced by a bare key |
| LC3 | **LK9.** A synthetic 1724-pair LoRA: 48 blocks × 29 linears (1392) + 42 top-level linears + 288 block tables (6 × 48) + 2 top-level tables, against a matching synthetic base → status not FAIL, no `absent` problem; `low_ram_skipped` → `(44, 1724)` |
| LC4 | `bin/lora-check --json`: `warnings == ["44 of 1724 modules are outside the transformer blocks and are skipped in low-RAM mode; render with --no-low-ram to use them"]`; text output has the `    ! ` line; exit 0; a stills target never warns |
| LC5 | `static_check` signature and return shape unchanged; `_action_lora_arch_ok` (ltx-movie) still unpacks it |
| LC6 | `lora-catalog add` (video) prints the `warning:` line with and without `--no-arch-check`; exit codes and catalog contents unchanged |
| LC7 | `lora-catalog verify` prints `WARN id: ...` after the entry's OK line; the summary line and exit code are unchanged |
| LC8 | A character LoRA trained by ltx-2-mlx (all keys under `transformer_blocks.`) gives no warning |

### 6.9 Existing tests that change (only these)

| Test | Reason and exact edit |
|---|---|
| `tests/test_movie_ui_http.py::test_mut18_every_api_route_needs_the_token` (`:43`) | `len(srv.ROUTES) == 40` becomes `== 46` |
| `tests/test_movie_ui_builder.py::test_mut3_help_flags_fixtures_real_help_and_cache` (`:115-140`) | `ALL_MU37_FLAGS` gains `"--location", "--location-strength"`; `current - old` gains them; `len(supported) == 28` becomes `== 30` |
| `tests/fixtures/movie_ui/ltx-movie-help-current.txt` | the two new flag lines (L4.6) |
| `tests/movie_ui_testutil.py` | `STUB_TOOLS` and `STUB_SOURCE` (L4.6) |
| `tests/story_engine_testutil.py` | `set_story_env` and `LINKED_FILES` (6.2) |
| `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` | G15, separate test-only follow-up commit: `BASELINE` becomes the feature commit's SHA; the comment's last item gains `, then to <sha> (location library).` |

Every other existing test passes unedited, in particular `tests/test_character_dataset.py`, `tests/test_character_tool.py`, `tests/test_shots_mode.py`, `tests/test_ltx_story_images.py`, `tests/test_casting_pipeline.py`, `tests/test_dialogue.py`, `tests/test_pinned_cast.py`, `tests/test_story_engine.py`, `tests/test_ltx_mlx_render.py`, `tests/test_lora_compat.py`, `tests/test_lora_catalog.py`, `tests/test_movie_ui_*.py` and `tests/test_ltx_movie_offline.py`.

---

## 7. Interactions and back-compat

| Area | Behaviour after this change |
|---|---|
| Runs without `--location` | Byte-identical plan prompts, plan.json, manifest, images.json plans, render units and provenance (LK5) |
| Character create/train | Byte-identical (LK4). Character create does not check location triggers (D21) |
| Character and location jobs | One at a time: both take the character library lock |
| `--resume` | A panel whose location LoRA was retrained re-renders (provenance sha256); others are reused |
| Critic, judge-story | Cannot change a pinned setting (`location.setting` NOT_REPAIRED) |
| `recheck` | Unchanged; P21 is not applied to existing stories |
| movie-ui story/regenerate jobs | Phase 1 with the same `--location`; a P21 exhaustion is a failed job with the fatal stderr |
| movie-ui movie job on an existing story | Must pass the same locations (L3.2 exit 2 otherwise) |
| LoRA catalog | Unchanged; locations are not entries and are not folded |
| lora-check / lora-catalog | New warnings only; PASS/FAIL, problem counts and exit codes unchanged |

---

## 8. Rollout

1. Snapshot (house rule): `tar czf <scratchpad>/snapshot-pre-location-d210c26.tgz` of `WS`, excluding `generated/`.
2. At `d210c26`, before any edit: record the full-suite pass count and failure list; write `tests/test_location_golden.py` and run `python3 tests/test_location_golden.py --write-fixture`; run the 6.3 plan-fixture script.
3. Implement G1-G14 in one feature commit.
4. Run LK1-LK10 and the full suite.
5. Opus design review of the diff against this spec.
6. The test-only follow-up commit G15, then measure LK1.
7. Live checks, post-merge, this Mac only, not a merge gate: `bin/location create harbour-street --description "<24 words>"`, review the sheet, `bin/location train harbour-street`, then `bin/ltx-movie "<narrative at a harbour and a temple>" --panels 3 --story-id loc-live-1 --location harbour-street --story-only --no-review` and record whether plan.json pins l1 in a beat; optionally render and compare the panels at the location with a run without `--location`. Never on macstudio.

PR note (in substance): "New location library (`bin/location`, movie-ui Locations tab). Pin up to 3 trained locations with `--location`; the plan sets beats there with the location's fixed setting (P21: retried once, then exit 1), and only those panels get the location's LoRAs and trigger. lora-check now matches bare scale/shift tables and warns about LoRA modules the low-RAM render skips."

---

## 9. Risks

- **R1. Photo locations have few angles.** Edits never move the camera, so a 1-photo location is 24 versions of one viewpoint and its LoRA may push every panel toward that framing. The UI and help recommend 3-5 photos from different spots.
- **R2. Description vs. narrative.** The planner must place story action in a fixed setting it did not write; P21 forces at least one beat there. A narrative that never mentions the place can still pass P21 with an unnatural beat.
- **R3. Lock message.** A location job holding the shared lock makes a character create print "another bin/character create/train is running"; the text is accurate about the lock, not the tool.
- **R4. Character triggers do not check location triggers.** A later `bin/character create --trigger` could reuse a location's trigger; location creates check both ways only on their side (D21).
- **R5. LoRA count.** A panel with a style LoRA, a motion LoRA, a location and two characters has 5 LoRAs; L4 advises, nothing caps.
- **R6. Model aliasing.** Only the HF id and its local `ltx-2.3-mlx-q8` copy count as the base; any other path to the same weights is treated as a mismatch (warning, no LoRA).
- **R7. Seed image with a pinned location.** The seed image is the first frame; if it shows a different place, beat 1 at the pinned location contradicts it. No carve-out sentence is added.

---

## 10. Decisions made by the spec author

1. **Setting arithmetic.** `"The setting is <d>."` has W+3 words; 15-40 gives 18-43, inside 12-45 (and the shots minimum 12).
2. **Description form.** Starts with a/an/the; no `. ! ? "` or newline; normalised (whitespace, one trailing period, first letter lower-case).
3. **Layout.** The approved list gains `photos/`, `captions/`, `videos/`, `train/`, `lora/`, `tests/`; stills are `loc_NN.png`, n 1-24.
4. **Prompt wording.** View phrases read as "<View> of <description>"; time and weather placeholders are phrases ("at dusk", "in fog"); STYLE is the character STYLE.
5. **The 24 variants** (table L1.5): each view 4 times with 4 distinct times; times 5/5/5/4/5; each weather 6.
6. **Edits.** The exact EDIT_PROMPT, 23 EDIT_CONDITIONS (with 5 season variants), sources are the fitted photo stills, round robin `((j-1) % P) + 1`.
7. **Photo limits.** At most 24 photos; the 16:10 crop must be at least 512x320 (below 768x480 it is upscaled with a warning); duplicate files are refused.
8. **Three check prompts** (text-scored, photo-scored against photo 1, tag-only for user photos); vocabularies TIMES and WEATHERS (with snow) and their aliases.
9. **Keep and caption details.** `--force` also keeps unparseable user photos; `empty of people` is dropped from a caption when people are visible.
10. **Describe.** Uses the first 5 photos; 3 attempts with shorten/retry as the character describe.
11. **No preview stop** for location datasets.
12. **`--force` has two meanings at regenerate:** keep people photos, and allow regenerating a trained location (deleting its LoRAs).
13. **`bin/location edit`** is added so PATCH can save a photo location's description; it takes the lock and refuses text locations.
14. **Shared lock.** Locations use the character library lock, so one heavy job runs at a time across both libraries.
15. **Child reuse.** Locations run character_dataset's zimage/qwenedit children; qwenedit gains an optional per-job `image` and spec `skill`.
16. **Refactor shape.** Core `train_video_lora`/`train_stills_lora` plus unchanged one-argument wrappers; the cores keep calling module globals so existing monkeypatches work.
17. **Record additions.** A `dataset` object; LoRA entries have exactly 6 keys; `trained_at` is top-level; `photos[].path` is absolute or null.
18. **Stills test prompt** equals the video test prompt; the stills test images are written but not recorded.
19. **Model compatibility.** The recorded base is `dgrauet/ltx-2.3-mlx-q8`; it also matches `$LTX2_MLX_DIR/models/ltx-2.3-mlx-q8`; on a mismatch only the video LoRA is dropped and the stills LoRA still attaches.
20. **Strength.** Range (0, 1]; the record's strength wins over `--location-strength` (as characters).
21. **Triggers.** Class noun "place" for auto triggers; description words avoided; uniqueness checked against characters and locations on the location side only.
22. **Refusals.** `--location` is refused with `--no-stills`, `--story-legacy` and `--story-prompt-override`; the brief's "--story-file" is read as `--story-prompt-override`.
23. **Pin mismatch.** On an existing story, different pins in either direction exit 2; no usable plan.json gives a note and no LoRA.
24. **`location_name`** is added to plan locations only when locations are pinned (byte identity otherwise).
25. **A beat location written as a pinned library name** resolves to its id.
26. **P21** id, name and text; fatal alongside P1, P2, P16, P17.
27. **L4 counts the location LoRA** only when it is attached; no render-side advisory is added (none exists).
28. **Manifest entry** keys are `{name, video_lora, strength}`; trigger order catalog, location, character; at most one location per panel.
29. **Stills.** Shots stills groups are keyed by characters plus `location NAME`; the location stills strength is the location strength; order global, location, characters.
30. **lora-check output.** Warnings use a separate `warnings` field and `    ! ` lines; `static_check` is unchanged; `lora-catalog add` prints `warning:` even with `--no-arch-check`; `verify` prints `WARN id:` lines; counts and exit codes are unchanged; the UI Verify column appends the warning.
31. **UI flows.** PATCH only saves (photo mode; text mode gets the tool's 400); a text description change goes through Regenerate; Regenerate uses a new seed; one Force checkbox; up to 3 locations in Compose.
32. **iterate-story** passes `--location` from plan.json, at the default strength.
33. **No `--list-locations`** and no catalog folding of locations.
34. **Tests.** The file names, fixtures and existing-test edits of Section 6.

---

## 11. Open questions

None blocking. Two choices to confirm, both resolved above:
- **Q1.** Should `bin/character create` also refuse a trigger that a location already uses (R4)? This spec leaves character code unchanged.
- **Q2.** Is the dual meaning of `--force` at regenerate (D12) acceptable, or should "regenerate a trained location" get its own flag (for example `--discard-loras`)?
