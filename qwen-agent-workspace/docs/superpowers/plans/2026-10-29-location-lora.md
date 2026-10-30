# Location LoRA Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A location library, the place counterpart of the character library. `bin/location` builds a 24-still people-free dataset of a place, from a description (Z-Image) or from 1-24 photos (the photos plus Qwen-Image-Edit-2511 time/weather/season edits), has the vision model check every still, and trains an LTX-2.3 video LoRA and a Z-Image stills LoRA. `bin/ltx-movie --location NAME` (up to 3) pins trained locations: the planner must set at least one beat at each, with the location's fixed setting (P21, retried once, then exit 1), and only the panels whose `plan.json` beat is set there get the location's LoRAs and trigger. The movie UI gains a Locations tab and Compose fields. `bin/lora-check` matches bare scale/shift tables and warns about LoRA modules the low-RAM render skips.

**Architecture:**
- **Fixtures first (Task 1).** The character training golden record and the four plan fixtures are captured at `d210c26`, before any edit to `character_dataset.py` or `story_engine.py` (spec 6.3, 8 step 2).
- **`location_lib.py` (Task 2, new, stdlib).** The `location.json` schema and validation, library I/O, the description and trigger rules, `resolve_locations` into `LocationPin`, model compatibility, the trigger prefix and the `plan.json` reader. Every pipeline tool loads it by path.
- **`character_dataset.py` (Task 3).** L2.10: `train_video_lora`/`train_stills_lora` cores behind the unchanged `train_video`/`train_stills` wrappers (the golden record proves byte identity); L1.8: the qwenedit child takes a per-job `image` and a spec `skill`.
- **`location_dataset.py` and `bin/location` (Tasks 4, 5, new).** Create, regenerate and edit (Task 4); train and `bin/location-train-vlm` (Task 5). All image work runs in `character_dataset`'s own children; every gate and VLM call goes through the `character_dataset` module.
- **`story_engine.py` (Task 6).** The `LOCATION_FIXED_*` plan-prompt block, the pinned `l1..lK` entries with `location_name`, P21 (hard, fatal like P16) and the L4 count.
- **Pipeline tools (Tasks 7-10).** `bin/ltx-story-manifest` attaches `locations` and the trigger per planned beat (Task 7); `bin/ltx-story-images` attaches the stills LoRA (Task 8); `bin/ltx-mlx-render` validates and fuses the location LoRA between style and characters, audio-stripped (Task 9); `bin/ltx-movie` resolves and passes the pins, checks a reused story, prints the dry run, splits shots stills groups, and `bin/iterate-story` regenerates with the plan's locations (Task 10).
- **movie UI (Tasks 11, 12).** Routes, handlers, jobs, Compose fields, V1 rule 12c, `--no-arch-check` and WARN lines (Task 11); the page (Task 12).
- **`bin/lora-check`, `bin/lora-catalog` (Task 13).** L4.7, L4.8, and LL1's compile check of every changed file.
- **Task 14** is the controller's whole-branch review, then the one test-only re-baseline commit (`test_mut18`, `test_mut3` with its help fixture and `test_mut26` from spec 6.9, plus `test_mu14` and `test_spt1a`, which pin the same counts and fields; Plan ruling LR29), then LK1-LK10 and the hand-off.
- **Tests:** eight new files: `tests/test_location_golden.py` (LG), `tests/test_location_lib.py` (LL), `tests/test_location_dataset.py` (LD), `tests/test_location_tool.py` (LT), `tests/test_location_story.py` (LS), `tests/test_location_pipeline.py` (LP), `tests/test_location_ui.py` (LU), `tests/test_lora_check_fixes.py` (LC), plus the helper `tests/location_testutil.py`: 141 test functions with the parametrized cases (see "Coverage").

**Tech Stack:**
- Python 3.13 (`python3` = `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`, pytest 8.3.4, Pillow and psutil installed). Python 3.9.6 (`/usr/bin/python3`) is used for the compile check only. Every new and changed file runs on both.
- `location_lib.py`, `story_engine.py`, `bin/ltx-movie`, `bin/ltx-story-images` (at import), `bin/ltx-mlx-render`, `bin/iterate-story`, `bin/lora-check`, `bin/lora-catalog`, `movie_ui_lib.py` and `movie_ui_server.py` stay standard library only. `location_dataset.py` adds PIL and psutil, as `character_dataset.py` does; `bin/ltx-story-manifest` already imports PIL.
- Test helpers: `tests/story_engine_testutil.py` (`set_story_env`, `make_ws`, `make_ctx`, `plan_json`, `panel_json`, `answer`, `script_agent`, `agent_log`, `kyra`, `ronin`, `catalog_entry`, `lora_file`, `sha256_file`) and `tests/movie_ui_testutil.py` (`set_home`, `make_stub_workspace`, `Running`, `api`, `stub_config`, `stub_calls`, `fields`, `kill_everything`, `PNG`).
- Real `ffmpeg`/`ffprobe` wrap the kept stills in the dataset tests, as the character tests do. `git show d210c26:...` gives the pre-change modules that LS14, LP14, LP19, LC1 and LC3 compare with (skipped outside a git checkout that has `d210c26`). `node --check` checks `app.js` when `node` is installed (LU13).

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-10-29-location-lora-design.md`, committed at `509e28d` on `qwen-agent-redteam`; its code citations are at `d210c26`, whose code tree `509e28d` has unchanged (`509e28d` adds only the spec). The user approved the design section by section (spec Status) and **accepted the spec's defaults for its open questions Q1 and Q2 (spec 11)**: `bin/character create` stays unchanged and does not refuse a location's trigger (Q1, R4, D21), and `--force` at `bin/location create --regenerate` keeps both meanings, keeping people photos and allowing a trained location to be regenerated, which deletes its LoRAs (Q2, D12). The spec is binding. This plan changes behaviour only where the spec's text and its own tests, or the repository's existing tests that spec 6.9 keeps unedited, cannot both hold. Each such case is a numbered ruling in "Plan rulings", marked **[defect]**; the other rulings fill a detail the spec leaves open, marked **[reading]**.

## Global Constraints

From the spec, verbatim (section in brackets):

- [Status] "Every detail the approved design left open is decided here, marked **[spec choice]**, and listed in Section 10. This document carries those sections without reopening them. The implementer makes no design decisions."
- [0.2] "**Baseline failures on this Mac at `d210c26`** (not caused by this work): `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`. They must fail identically after the change."
- [0.4 Out of scope] "Motion clips for locations (locations train on 1-frame stills only, like characters). Planner auto-pick of locations (only pinned locations get LoRAs; the planner never chooses one). A `location` kind in the LoRA catalog (locations are not catalog entries and are not folded like characters). More than one location per beat (a beat has one `location` id, `story_engine.py:1280`). Resume of interrupted training (as for characters, a rerun starts over). Leak tests for location LoRAs (per-panel scoping makes them moot). `--no-stills` movies, `--story-legacy` and `--story-prompt-override` with locations (refused, L3.1). Re-checking existing stories for P21 (`recheck` is unchanged). A `bin/ltx-movie --list-locations` flag."
- [0.5] The KPIs, verbatim:

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

- [0.6] "Every L requirement and every test in Section 6 is a must-have. Nothing else is built. Not built: anything in 0.4; a preview stop for location datasets (D11); a strength editor in the UI."
- [1.2] "`location_lib.py`: stdlib only. It loads `character_lib.py` by path (`importlib.machinery.SourceFileLoader("character_lib", os.path.join(WS, "character_lib.py"))`) inside the functions that need it, never at import. `bin/location list`/`show`, `bin/ltx-movie`, `bin/ltx-story-manifest` and `bin/ltx-story-images` use only this module. The three pipeline tools load it by path inside function bodies, and only when `--location` is given, the way they load `character_lib` (`bin/ltx-movie:790-794`)." "`location_dataset.py`: stdlib, PIL, psutil, `location_lib`, `character_lib` and `character_dataset` (imported at top level with `sys.path.insert(0, WS)`). It never imports torch, diffusers or z_image_skill: all image work runs in `character_dataset.py`'s own child processes (`run_zimage_child`, `run_edit_child`), so `busy_process`'s markers (`character_dataset.py:553-554`) cover location work unchanged." "`story_engine.py` gains no import. It reads pinned locations by attribute (`.name`, `.description`, `.attach_video`) from `ctx.locations`." "`bin/location` re-executes itself under `$CHARACTER_PYTHON` (default `~/img-gen/bin/python`) when `create`, `train` or `edit` cannot import PIL or psutil, with the marker `LOCATION_REEXEC=1`, exactly as `bin/character:117-128`."
- [1.3] "Library root: `location_lib.library_dir()` = `$LOCATION_LIBRARY_DIR` when set (test infrastructure only), else `WS/generated/locations` (gitignored via `generated/`). Record: `location.json`, `schema_version` 1. Trigger registry: `<library>/.triggers`. Lock: the **character** library lock (`character_dataset.library_lock()`, `<character library>/.lock`). One heavy dataset or training job runs at a time across characters and locations (D14). Still files: `loc_NN.png`, `NN` = 01..24."
- [Fixed values, spec 2.3, 2.6, 2.9, 3.8, 3.9, 4.1] description "`15 <= len(text.split()) <= 40`"; photos "1 to `MAX_PHOTOS = 24`", crop "at least `768x480`"; "`MIN_SCORE = 7`, `MIN_KEEP = 12`"; "`MAX_LOCATIONS = 3`"; "`location_lib.VIDEO_BASE_MODEL = "dgrauet/ltx-2.3-mlx-q8"`"; "`location_lib.DEFAULT_LOCATION_STRENGTH` (0.8)", "outside `(0, 1]`" refused; stills 1024x640; video LoRA "rank 32/alpha 32, lr 2e-4, 1000 steps, checkpoint every 250"; test clips "512x320x25 at 24 fps, seed 42".
- [6.2 Test rules] "stdlib plus pytest; modules loaded by path with `importlib.machinery.SourceFileLoader` under test-unique names, as `tests/test_pinned_cast.py` does." "Every test sets `HOME`, `CHARACTER_LIBRARY_DIR`, `LOCATION_LIBRARY_DIR` and `LORA_CATALOG_DIR` under `tmp_path`. `tests/story_engine_testutil.set_story_env` gains `LOCATION_LIBRARY_DIR = <tmp>/locations` (returned as `"locations"`), and `LINKED_FILES` gains `"location_lib.py"`." "No real VLM, Z-Image, editor, mflux, ltx-2-mlx or render: `vlm_call`, `vlm_ready`, `story_server`, `restore_story_server`, `wait_for_avail`, `wait_for_vlm`, `story_server_state`, `busy_process`, `free_gib`, `edit_models_missing`, `run_logged`, `run_zimage_child`, `run_edit_child`, `SKILL.generate_video` and `psutil.virtual_memory` are replaced by fakes (the patterns of `tests/test_character_dataset.py:579-641` and `:968-998`). Real ffmpeg/ffprobe are used only for `wrap_still`, as the character tests do." "The only server is the in-test movie-UI server on 127.0.0.1 (`movie_ui_testutil`). No test opens port 8177 or 8178." "Each new test file's docstring states these rules."
- [6.9 Existing tests that change (only these)] "`tests/test_movie_ui_http.py::test_mut18_every_api_route_needs_the_token` (`:43`) | `len(srv.ROUTES) == 40` becomes `== 46`"; "`tests/test_movie_ui_builder.py::test_mut3_help_flags_fixtures_real_help_and_cache` (`:115-140`) | `ALL_MU37_FLAGS` gains `"--location", "--location-strength"`; `current - old` gains them; `len(supported) == 28` becomes `== 30`"; "`tests/fixtures/movie_ui/ltx-movie-help-current.txt` | the two new flag lines (L4.6)"; "`tests/movie_ui_testutil.py` | `STUB_TOOLS` and `STUB_SOURCE` (L4.6)"; "`tests/story_engine_testutil.py` | `set_story_env` and `LINKED_FILES` (6.2)"; "`tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` | G15, separate test-only follow-up commit: `BASELINE` becomes the feature commit's SHA; the comment's last item gains `, then to <sha> (location library).`" "Every other existing test passes unedited". (Two more existing tests pin what the spec changes; Plan ruling LR29 re-baselines them in the same commit.)
- [8 Rollout] "1. Snapshot (house rule): `tar czf <scratchpad>/snapshot-pre-location-d210c26.tgz` of `WS`, excluding `generated/`. 2. At `d210c26`, before any edit: record the full-suite pass count and failure list; write `tests/test_location_golden.py` and run `python3 tests/test_location_golden.py --write-fixture`; run the 6.3 plan-fixture script. 3. Implement G1-G14 in one feature commit. 4. Run LK1-LK10 and the full suite. 5. Opus design review of the diff against this spec. 6. The test-only follow-up commit G15, then measure LK1. 7. Live checks, post-merge, this Mac only, not a merge gate ... Never on macstudio." (Step 3's single feature commit is split per task; see Plan ruling LR16.)
- [8] PR note (required, in substance): "New location library (`bin/location`, movie-ui Locations tab). Pin up to 3 trained locations with `--location`; the plan sets beats there with the location's fixed setting (P21: retried once, then exit 1), and only those panels get the location's LoRAs and trigger. lora-check now matches bare scale/shift tables and warns about LoRA modules the low-RAM render skips."

Controller rules, verbatim. Every task's requirements include them:

- Tests never use the real HOME, never render, never contact servers. An in-test 127.0.0.1 movie-UI server is allowed.
- Never touch port 8178. Watchdogs are port-scoped.
- Executors edit tracked files with the Edit tool.
- Never stage .DS_Store, .claude/, agent/__pycache__/, repo-root bin/, qwen-agent-workspace/bin/action-from-dir, pin-sh2.json or story_bible_pin-sh2.json.
- Never git stash, reset or checkout other people's work.
- Commit trailer: "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>".
- No push. Pushing requires the user's approval, and the coordinator does it.
- Never read, cat, grep or source ~/.zshenv or any fleet.env, and never print env values.
- Never ssh/scp/rsync/HTTP to the macstudio host.
- No network.

House rules (from the prior plans; every task's requirements include them):

- **Where work happens.**
  - This Mac only. No ssh, scp, rsync, curl or HTTP to any other host, and never touch macstudio. Use no network. The movie-UI tests start servers on `127.0.0.1` inside the test; nothing else listens.
  - Never start, stop or contact a model server (`:8177`, `:8178`). Never render, train, or load a model.
- **The main checkout.** Never touch the main checkout `/Users/reubenpatterson/local_agent_harness`. Every command runs in the worktree `$S/loc-wt`. The only exception is the controller's `git worktree add` in "Before Task 1".
- **Python.** Every new or changed file must run on Python 3.9.6 and 3.13. So use none of: the `match` statement, `X | Y` type expressions, the walrus operator, `str.removeprefix`, `zip(strict=)` and parenthesised context managers. The code blocks below use none of them.
- **Editing.**
  - Executors make every change to a tracked file with the Edit tool. Each new file is created with the Write tool in the step that names it, and edited with the Edit tool from then on.
  - Never use `rm`, `sed -i`, a redirect or a script to change a tracked file. The only generated files are the Task 1 fixtures, which `tests/test_location_golden.py --write-fixture` and the spec 6.3 script write (spec 8 step 2).
- **Git.**
  - Stage only the paths a task names, and check `git diff --cached --name-only` before every commit.
  - Every commit command passes the trailer as a second `-m`.
  - Push is a separate step that needs the user's approval. No task pushes.
- **Paths.**
  - `S` = `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`.
  - `WS` = `$S/loc-wt/qwen-agent-workspace`, and `D` = `$S/loc-baseline`.
  - The git root is `$S/loc-wt`, so `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix.
  - Run every command from `WS`. Shell variables do not persist between commands, so every block defines the variables it uses.
- **Code blocks** are copied byte for byte.
  - An Edit step's old text must occur exactly once in the file at that moment. If it does not, stop and report; do not adapt it.
  - Every Create and Edit below was replayed in order on a scratch checkout of `d210c26`, where each old text occurred exactly once at its turn (see "Execution handoff").
- **The compile check** (Step 4 of each code task) is this command, with the task's Python files as `FILES`. Expected: two lines, `compiled N` for 3.9 and then for 3.13.

```bash
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' FILES; done
```

## Review Focus

These five inputs and failure modes are the ones most likely to reach a user first, and no LL, LD, LT, LG, LS, LP, LU or LC row exercises them. Each is pinned by a test in the task that owns its code.

1. **A new description that contains the location's trigger word.** This happens with `bin/location edit`, with a text location's `create --regenerate --description`, and with `--force` on a trained location.
   - Without a check, `write_location` raises inside the library lock. With `--force` on a trained location, that is after `lora/`, `tests/` and `train/` are deleted, so the user gets a traceback and loses the LoRAs.
   - Expected: refused before the lock with `Error: --description: trigger T must not be a word of the description`, exit 2. `location.json` and the LoRA files are untouched (Plan ruling LR7).
   - Test: `test_review_focus_1_a_new_description_with_the_trigger_is_refused` (Task 4).
2. **A place name with accents** (`café`, `Montréal`).
   - The description rules accept non-ASCII words. `location.json` is written with `ensure_ascii=False`. The movie UI runs `bin/location list` and `show` with whatever locale its server has.
   - Expected: the create succeeds. The auto trigger is built from the ASCII letters of the name (`cafetplc`). `list` and `show` exit 0 and print the description in UTF-8 under `LC_ALL=C`.
   - Test: `test_review_focus_2_an_accented_place_name_round_trips` (Task 4).
3. **A location deleted or renamed between Phase 1 and Phase 3.** Spec L5.1 names this row ("manifest 2 → ltx-movie Phase 3 exit 1"), but no LP row tests it.
   - Expected: `bin/ltx-story-manifest` exits 2 with `Error: unknown location: NAME (no PATH)` and writes no `manifest.json`. `bin/ltx-movie`'s existing Phase 3 check turns that into exit 1.
   - Test: `test_review_focus_3_a_location_deleted_after_phase_1` (Task 7).
4. **A plan with more beats than the `--panels` target.** This is the soft panel count spec's case: a target of 3 and a 4-beat plan.
   - The attach must follow `story.md`'s 4 panels and the plan's 4 beats, not the target.
   - Expected: panels 2 and 4, the beats at `l1`, get the location. Panels 1 and 3 get `[]`.
   - Test: `test_review_focus_4_a_plan_with_more_beats_than_the_target` (Task 7).
5. **Compose fields saved before the upgrade.** A job's `fields` without `locations` or `location_strength` is reloaded into Compose or the Stories tab and posted back.
   - Expected: `compose_fields` fills `[]` and `None`, V1 passes, and the argv gains no `--location` or `--location-strength`.
   - Test: `test_review_focus_5_fields_saved_before_the_upgrade` (Task 11).

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `location_lib.py` | Create (Task 2) | The `location.json` schema (`validate_location`, `load_location`, `write_location`), names, the description rule, triggers and the registry, `resolve_locations` → `LocationPin`, `usable_locations`, `model_compatible`, `location_table_lines`, `plan_location_names`, `plan_panel_locations`, `prefix_location_trigger`. Stdlib only. |
| `location_dataset.py` | Create (Task 4), extend (Task 5) | The L1.5 variants and prompts, photo loading and fitting, `describe`, `check_still`, `validate_location_check`, `caption`, the contact sheet, `build_dataset`, `create`, `_regenerate`, `edit` (T4); `train` through the character cores (T5). |
| `bin/location` | Create (Task 4), extend (Task 5) | The CLI: `create`, `edit`, `list`, `show` (T4), `train` (T5); the PIL/psutil re-exec; `run()` with the signal path. |
| `bin/location-train-vlm` | Create (Task 5) | `bin/character-train-vlm` for locations: stop the VLM, train, always restore it. |
| `character_dataset.py` | Modify (Task 3) | `train_video_lora` and `train_stills_lora` cores; the unchanged `train_video`/`train_stills` wrappers; the qwenedit child's per-job `image` and spec `skill`. |
| `story_engine.py` | Modify (Task 6) | `StoryContext.locations`, `LOCATION_FIXED_INTRO`/`LOCATION_FIXED_LINE`/`FIXED_SETTING`, the plan-prompt block, the pinned `l1..lK` with `location_name`, P21 and its fatal filter, the L4 count. |
| `bin/ltx-story-manifest` | Modify (Task 7) | `--location`, `--location-strength`; per-panel `locations` and the trigger prefix from `plan.json`; the summary lines. |
| `bin/ltx-story-images` | Modify (Task 8) | `--location`, `--location-strength`; the per-panel stills LoRA and trigger; the duplicate and legacy-route rules. |
| `bin/ltx-mlx-render` | Modify (Task 9) | `locations` validation, the `location` unit LoRA between style and characters, its audio strip, the duplicate checks and the legacy route. |
| `bin/ltx-movie` | Modify (Task 10) | `--location`, `--location-strength`; `_resolve_locations`, `_check_story_locations`, `_location_flags`; the shots stills groups; the dry-run Locations block; `_story_context`'s `locations`. |
| `bin/iterate-story` | Modify (Task 10) | `build_engine_cmd` passes the plan's `location_name`s. |
| `movie_ui_lib.py` | Modify (Task 11) | `job_vlm` kinds, `DEFAULT_FIELDS`, `FIELD_FLAGS`, `LOCATION_NAME_RE`, `build_argv`, V1 rule 12c, `location_argv`. |
| `movie_ui_server.py` | Modify (Task 11) | The six `/api/locations` routes and handlers, PATCH bodies, `--no-arch-check`, the WARN lines of `parse_verify`. |
| `static/movie-ui/index.html`, `static/movie-ui/app.js` | Modify (Task 12) | The Locations tab, Compose's Locations and Location strength fields, the LoRA tab's Skip architecture check and the Verify column's warnings. |
| `bin/lora-check` | Modify (Task 13) | Bare 2-D base parameters; `LOW_RAM_WARNING`, `low_ram_skipped`, `low_ram_warning`; the `warnings` field and `    ! ` lines. |
| `bin/lora-catalog` | Modify (Task 13) | The `warning:` line of `add` and the `WARN id:` lines of `verify`. |
| `tests/location_testutil.py` | Create (Task 2) | `make_location`, `harbour`, `temple`, `mill`, `write_plan` and the description literals. |
| `tests/test_location_golden.py` | Create (Task 1), extend (Task 3) | LG1-LG3 and `--write-fixture`. |
| `tests/fixtures/location/*` | Create (Task 1, generated) | `character_train_golden.json`, `plan_prompt_chained.txt`, `plan_prompt_shots.txt`, `plan_prompt_chained_cast.txt`, `normalized_plan_chained.json`. |
| `tests/test_location_lib.py` | Create (Task 2), extend (Task 13) | LL2-LL14 (T2), LL1 (T13). |
| `tests/test_location_dataset.py` | Create (Task 3), extend (Tasks 4, 5) | LD18 (T3), LD1-LD17 and LD24 (T4), LD19-LD23 (T5). |
| `tests/test_location_tool.py` | Create (Task 4), extend (Task 5) | LT1-LT8 and Review Focus 1, 2 (T4); LT1b, LT9, LT10 (T5). |
| `tests/test_location_story.py` | Create (Task 1), extend (Tasks 6, 10) | LS1 (T1); LS2-LS6 and LS8-LS14 (T6); LS7 (T10). |
| `tests/test_location_pipeline.py` | Create (Task 7), extend (Tasks 8-10) | LP5-LP9 and Review Focus 3, 4 (T7); LP10-LP12 (T8); LP14-LP19 (T9); LP1-LP4, LP13, LP20 (T10). |
| `tests/test_location_ui.py` | Create (Task 11), extend (Task 12) | LU1-LU12, LU14 and Review Focus 5 (T11); LU13 (T12). |
| `tests/test_lora_check_fixes.py` | Create (Task 13) | LC1-LC8 and the LR1 pin LC9. |
| `tests/story_engine_testutil.py` | Modify (Task 2) | `set_story_env`'s `LOCATION_LIBRARY_DIR`, `LINKED_FILES`'s `location_lib.py` (spec 6.2, 6.9). |
| `tests/movie_ui_testutil.py` | Modify (Task 11) | `STUB_TOOLS` gains `location`; `STUB_SOURCE`'s `location list` (spec L4.6, 6.9). |
| `tests/test_movie_ui_http.py`, `tests/test_movie_ui_builder.py`, `tests/fixtures/movie_ui/ltx-movie-help-current.txt`, `tests/test_soft_panel_count.py` | Modify (Task 14 only) | The spec 6.9 re-baselines of `test_mut18`, `test_mut3` (with its fixture) and `test_mut26`, and Plan ruling LR29's `test_mu14` and `test_spt1a`, in one test-only commit. |

**Task split.** Each task is one layer a reviewer can accept or reject on its own diff, with its own failing tests first:
- Task 1 captures the byte-identity references before anything changes.
- Tasks 2-5 build the library (record, character refactor, dataset, training), each testable without the story pipeline.
- Task 6 is the planner. Tasks 7-9 are the three downstream tools (manifest, stills, render); Task 10 is the orchestrator that passes them the flags.
- Tasks 11-12 are the UI server and the page. Task 13 is lora-check. Task 14 is the review, the test-only re-baseline and the KPIs.

## Between tasks: the existing suite (approach B, and why)

**The choice.** Feature tasks do **not** edit the existing tests whose assertions the new behaviour changes:
- the three that spec 6.9 re-baselines (`test_mut18`, `test_mut3` with its help fixture, `test_mut26`);
- the two that pin the same counts and fields but that spec 6.9 misses (`test_mu14_ws_parameter_errors_and_options` and `test_spt1a_engine_constants`; Plan ruling LR29).

They stay red from the task that first breaks them until Task 14's one test-only commit, as the spec (6.9, 0.3 G15) and the controller require. Every other existing test must stay green in every task (spec 6.9: "Every other existing test passes unedited").

The two test-infrastructure edits that spec 6.9 also lists are not re-baselines, and the new tests need them, so they land with the first task that uses them:
- `tests/story_engine_testutil.py` (`set_story_env`, `LINKED_FILES`): Task 2.
- `tests/movie_ui_testutil.py` (`STUB_TOOLS`, `STUB_SOURCE`): Task 11.

**Precision.** The list below was measured: the plan's own replay ran the full suite after Task 13 and after Task 14 on a scratch checkout of `d210c26` (see "Execution handoff"). After Task 13 exactly these five existing tests failed, besides the two baseline failures:

| Code | Cause | First task |
|---|---|---|
| G15 | `test_mut26`: any edit to a `PIPELINE_FILES` entry (`character_dataset.py` is the first) | 3 |
| SC | `test_spt1a_engine_constants`: `StoryContext` gains a last field `locations` with the default `()` (L3.3) | 6 |
| R18 | `test_mut18_every_api_route_needs_the_token`: `ROUTES` has 46 entries, not 40 (L4.1) | 11 |
| R3 | `test_mut3_help_flags_fixtures_real_help_and_cache` and `test_mu14_ws_parameter_errors_and_options`: `FIELD_FLAGS` has 30 entries, not 28 (L4.3), and the stub workspace's help fixture lacks `--location` until Task 14 | 11 |

The expected-failure list, written to `$D/expected-failures.txt` in "Before Task 1" Step 4. A line is `T<first task> <node id> <code>`.

```text
# location library plan: existing tests expected to fail from the given task until Task 14
T3 tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged G15
T6 tests/test_soft_panel_count.py::test_spt1a_engine_constants SC
T11 tests/test_movie_ui_http.py::test_mut18_every_api_route_needs_the_token R18
T11 tests/test_movie_ui_builder.py::test_mut3_help_flags_fixtures_real_help_and_cache R3
T11 tests/test_movie_ui_http.py::test_mu14_ws_parameter_errors_and_options R3
```

**Gate rule** (Step 4 of every code task):
1. Every test in the new files (`tests/test_location_*.py`, `tests/test_lora_check_fixes.py`) passes.
2. The two baseline failures fail with the same messages.
3. Every lost baseline pass is listed for a task at or before this one in `$D/expected-failures.txt`.
4. `tests/test_ltx_movie_offline.py` prints `OK 347/347`.

**When the gate prints `GATE STOP`:**
- The executor stops and reports the UNEXPECTED ids together with `python3 -B -m pytest -q -p no:cacheprovider --tb=short <ids>` output.
- The controller has an Opus reviewer rule on each id. A lost pass that the list does not name is a defect in this task's code; the controller writes the exact fix, and the gate reruns. The list grows only for `tests/test_fleet_tracing.py::test_trt41a_trace_cli_on_one_agent` (below).

`tests/test_fleet_tracing.py::test_trt41a_trace_cli_on_one_agent` is timing-sensitive and unrelated to this plan. If the gate lists it as UNEXPECTED, rerun it alone (`python3 -B -m pytest -q -p no:cacheprovider tests/test_fleet_tracing.py -k trt41a`). If it passes alone, the controller appends `T<N> tests/test_fleet_tracing.py::test_trt41a_trace_cli_on_one_agent flaky`, and Task 14 rechecks it.

**Must stay green in every task** (spec 6.9's named files): `tests/test_character_dataset.py` (except the baseline `test_d2`), `tests/test_character_tool.py`, `tests/test_shots_mode.py`, `tests/test_ltx_story_images.py`, `tests/test_casting_pipeline.py`, `tests/test_dialogue.py`, `tests/test_pinned_cast.py`, `tests/test_story_engine.py` (except the baseline `test_rst62`), `tests/test_ltx_mlx_render.py`, `tests/test_lora_compat.py`, `tests/test_lora_catalog.py`, every `tests/test_movie_ui_*.py` test other than the three listed, every `tests/test_soft_panel_count.py` test other than `test_spt1a`, and `tests/test_ltx_movie_offline.py`. None is in the list, so a failure there stops the gate.

---

## Before Task 1: the plan commit, the worktree, the snapshot, the baseline (controller; no code)

- [ ] **Step 1: Confirm the plan commit on `qwen-agent-redteam`.**

The plan was committed on the branch as `docs(plan): location LoRA library implementation plan`, directly on top of the spec commit `509e28d`.

```bash
cd /Users/reubenpatterson/local_agent_harness
git branch --show-current          # expected: qwen-agent-redteam
git log -2 --format=%s             # expected: docs(plan): location LoRA library implementation plan, then docs(spec): location library — location LoRAs pinned per panel, lora-check fixes
git rev-parse HEAD~1               # expected: 509e28d... (the spec commit)
```

- [ ] **Step 2: Create the worktree and confirm the tree.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
git -C /Users/reubenpatterson/local_agent_harness worktree add -b loc-impl $S/loc-wt qwen-agent-redteam
WS=$S/loc-wt/qwen-agent-workspace
cd $WS
git branch --show-current                                   # expected: loc-impl
git log -1 --format=%s                                      # expected: docs(plan): location LoRA library implementation plan
git diff --stat d210c26 HEAD -- . ':(exclude)docs' | tail -1   # expected: no output
git status --short                                          # expected: no output
ls location_lib.py tests/test_location_lib.py 2>&1 | grep -c "No such file"   # expected: 2
wc -l character_dataset.py story_engine.py bin/ltx-movie bin/ltx-story-manifest bin/ltx-story-images bin/ltx-mlx-render bin/lora-check bin/lora-catalog movie_ui_server.py movie_ui_lib.py | tail -11
grep -c "ff757afbc0a801f2029628871c684ce4d98b4811" tests/test_movie_ui_builder.py   # expected: 2
```

Expected `wc -l` counts (spec 0.2): `character_dataset.py` 1904, `story_engine.py` 4997, `bin/ltx-movie` 2643, `bin/ltx-story-manifest` 962, `bin/ltx-story-images` 490, `bin/ltx-mlx-render` 1456, `bin/lora-check` 423, `bin/lora-catalog` 307, `movie_ui_server.py` 1863, `movie_ui_lib.py` 2224. If any value differs, stop and report: every Edit below was written against this tree.

- [ ] **Step 3: Take the compressed snapshot (house rule; spec 8 step 1).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
tar czf $S/snapshot-pre-location-d210c26.tgz --exclude qwen-agent-workspace/generated -C $S/loc-wt qwen-agent-workspace
tar tzf $S/snapshot-pre-location-d210c26.tgz | grep -c '^qwen-agent-workspace/character_dataset.py$'   # expected: 1
```

- [ ] **Step 4: Record a fresh baseline at `d210c26` and write the gate files (about 16 minutes; spec 8 step 2).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/loc-baseline
mkdir -p $D
cd $S/loc-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
grep -c '^PASSED ' $D/baseline-pytest.txt
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1 | tee $D/baseline-offline.txt
```

Expected (measured on the plan's replay at `d210c26`):
- a summary of `2 failed, 1987 passed, 2 skipped` (the warning count and time vary);
- exactly two `FAILED` lines: `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets - AssertionError: b...`;
- `1987`;
- `OK 347/347`.

If the numbers differ, the recorded file is still the baseline. Report the difference, and use the recorded pass count wherever this plan says 1987.

Then write three scratch files with the Write tool. They are outside the repository and never staged.

1. `$D/expected-failures.txt`: exactly the `text` block of "Between tasks" above.
2. `$D/gate.py`:

```python
"""The task gate of the location library plan: a full pytest -rA run against the baseline."""
import re
import sys

base_file, run_file, expected_file, task = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
NEW_FILES = ("tests/test_location_golden.py::", "tests/test_location_lib.py::",
             "tests/test_location_dataset.py::", "tests/test_location_tool.py::",
             "tests/test_location_story.py::", "tests/test_location_pipeline.py::",
             "tests/test_location_ui.py::", "tests/test_lora_check_fixes.py::")


def status(path):
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            match = re.match(r"^(PASSED|FAILED|ERROR|SKIPPED) (\S+)", line)
            if match:
                out[match.group(2)] = match.group(1)
    return out


base, now = status(base_file), status(run_file)
expected = []
with open(expected_file, encoding="utf-8") as f:
    for line in f:
        parts = line.split()
        if parts and not line.startswith("#") and int(parts[0][1:]) <= task:
            expected.append(parts[1])


def listed(test):
    return any(test == e or test.startswith(e + "[") for e in expected)


lost = sorted(t for t, s in base.items() if s == "PASSED" and now.get(t) != "PASSED")
unexpected = [t for t in lost if not listed(t)]
mine = sorted(t for t in now if t.startswith(NEW_FILES))
broken = [t for t in mine if now[t] != "PASSED"]
old_failures = sorted(t for t, s in base.items() if s in ("FAILED", "ERROR"))
still = [t for t in old_failures if now.get(t) in ("FAILED", "ERROR")]
print("lost %d (listed %d, unexpected %d); new-file tests %d, not passing %d; baseline "
      "failures still failing %d of %d" % (len(lost), len(lost) - len(unexpected),
                                          len(unexpected), len(mine), len(broken), len(still),
                                          len(old_failures)))
for t in lost:
    print("LOST", t, "listed" if listed(t) else "UNEXPECTED")
for t in broken:
    print("NEW-FILE-FAIL", t, now[t])
print("GATE", "PASS" if not unexpected and not broken else "STOP")
```

3. `$D/plan_fixtures.py`: the spec 6.3 plan-fixture script, verbatim, plus one final `print` line:

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
print("wrote 4 plan fixtures to %s" % out)
```

**The gate block** (Step 4 of every code task; `N` is the task number). It is a full run of about 16 minutes, which may run in the background:

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/loc-baseline
N=1
cd $S/loc-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/task-$N-pytest.txt 2>&1; tail -1 $D/task-$N-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/task-$N-pytest.txt $D/expected-failures.txt $N
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1
```

Expected: `GATE PASS`, `new-file tests <count>, not passing 0`, `baseline failures still failing 2 of 2`, and `OK 347/347`. Each task's Step 4 gives its count. On `GATE STOP`, follow the gate rule ("Between tasks").

---

### Task 1: Capture the golden fixtures at `d210c26` (spec 6.3, 8 step 2; LG1, LS1)

This task changes no pipeline file. It writes the two byte-identity references before `character_dataset.py` and `story_engine.py` are edited (spec 8 step 2), and the tests that compare the current code with them:
- `tests/fixtures/location/character_train_golden.json`: the golden record of `train_video`/`train_stills` (spec 6.3), written by `python3 tests/test_location_golden.py --write-fixture`.
- `tests/fixtures/location/plan_prompt_chained.txt`, `plan_prompt_shots.txt`, `plan_prompt_chained_cast.txt`, `normalized_plan_chained.json`: the spec 6.3 plan fixtures, written by `$D/plan_fixtures.py`.
- LG1 (the golden record) and LS1 (the plan prompts and the normalised plan), which pass against `d210c26` and must keep passing through Task 14 (LK4, LK5).

The golden record replaces, besides the spec's `<TMP>` and `<STAMP>`, the three host paths that the record holds (`SKILL.LTX2_MLX_HF_HOME`, `SKILL.LTX2_MLX_DIR`, `character_dataset.MFLUX_HF_HOME`) with `<LTX2_MLX_HF_HOME>`, `<LTX2_MLX_DIR>` and `<MFLUX_HF_HOME>`, so the committed fixture names no path under the real HOME (Plan ruling LR24). Each of the four cases runs in its own fresh directory under one temporary root.

**Files:**
- Create: `tests/test_location_golden.py`, `tests/test_location_story.py` (LS1 only; Tasks 6 and 10 append).
- Create (generated, Step 3): the five files under `tests/fixtures/location/`.
- Read only: `character_dataset.py` (`train_video` `:1413-1488`, `train_stills` `:1641-1741`, `VIDEO_FINAL_CKPT` `:205`, `MFLUX_HF_HOME` `:211`), `character_lib.py` (`write_character` `:472-485`, `utc_now` `:270-271`), `story_engine.py` (`build_plan_prompt` `:1063-1134`, `normalize_plan` `:1233-1308`), `tests/story_engine_testutil.py` (`kyra` `:161`, `ronin` `:165`, `make_ws` `:241`, `make_ctx` `:294`, `plan_json` `:363`).

**Interfaces:**
- Consumes (existing): `character_dataset.train_video(data) -> str`, `character_dataset.train_stills(data) -> str`, `character_dataset.SKILL.LTX2_MLX_BIN`, `SKILL.generate_video`, `run_logged(cmd, log_path, cwd, env, timeout_s) -> int`, `run_zimage_child(spec, char_dir, step) -> dict`; `story_engine.build_plan_prompt(ctx, compatible, pins) -> str`, `story_engine.normalize_plan(ctx, raw) -> (plan, shape)`; `seu.set_story_env`, `seu.make_ws`, `seu.make_ctx`, `seu.plan_json`, `seu.kyra`, `seu.ronin`; `character_lib.resolve_cast(entries) -> [CastMember]`.
- Produces:
  - `tests/test_location_golden.py`: `golden_record() -> str` (the JSON text, one trailing newline), `main(argv) -> int` (`--write-fixture`), the constants `FIXTURE`, `NOW = "2026-10-29T00:00:00Z"`, `CASES` (4 tuples `(label, kind, value, train)`), the autouse `story_env` fixture, and `test_lg1_the_character_golden_record_is_unchanged`.
  - `tests/test_location_story.py`: the header (`WS`, `seu`, `se`, `cl`, `FIXTURES`, the autouse `story_env` fixture that also sets `LOCATION_LIBRARY_DIR`, the `ws` fixture) and `test_ls1_without_locations_plan_prompts_and_plans_are_byte_identical`.

- [ ] **Step 1: Write the failing tests.**

**1.1.** Create `tests/test_location_golden.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""The character golden record of the location library's training refactor
(docs/superpowers/specs/2026-10-29-location-lora-design.md, Sections 3.10, 6.3 and 6.6: LG1-LG3,
KPI LK4).

golden_record() trains a temporary untrained character through character_dataset.train_video and
character_dataset.train_stills, with every heavy step faked, in four cases: the video happy path,
a video preprocess that exits 1, the stills happy path and a stills compat-gate reject. It returns
one JSON text holding, per case, the outcome, every fake call (argv, cwd, HF_HOME, generate
kwargs, child spec and step), the training config text, character.json, stdout, stderr and the
sorted file list of the character directory. tests/fixtures/location/character_train_golden.json
is that text as captured at d210c26, before character_dataset.py was refactored:

    python3 tests/test_location_golden.py --write-fixture     (from the workspace root)

LG1 requires the current code to reproduce it byte for byte.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_location_golden.py
Stdlib plus pytest (and PIL, which character_dataset imports). No test reads the real HOME,
renders, trains, runs Z-Image or the editor, contacts a model server or touches port 8178: the
autouse story_env fixture puts HOME, CHARACTER_LIBRARY_DIR, LOCATION_LIBRARY_DIR and
LORA_CATALOG_DIR under tmp_path, golden_record() points them at its own temporary root, and
run_logged, SKILL.generate_video and run_zimage_child are fakes. Every patch inside
golden_record() is a unittest.mock patch, so this module also runs as a script.
"""

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import zipfile
from unittest import mock

import pytest
from PIL import Image

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import character_dataset  # noqa: E402
import character_lib  # noqa: E402
import story_engine_testutil as seu  # noqa: E402

FIXTURE = os.path.join(WS, "tests", "fixtures", "location", "character_train_golden.json")
DESCRIPTOR = "a young woman with long black hair pinned up with jade hairpins wearing a grey kimono"
NOW = "2026-10-29T00:00:00Z"
STAMP_RE = re.compile(r"\d{8}T\d{6}Z")
TWO_MODULE_KEYS = ["layers.0.attention.to_q.lora_A.weight", "layers.0.attention.to_q.lora_B.weight",
                   "layers.0.attention.to_k.lora_A.weight", "layers.0.attention.to_k.lora_B.weight"]


def _untrained(lib):
    """An untrained kyra with a real dataset layout: 25 tiny stills, and captions, 1-frame
    "videos" and manifest items for the 24 kept ones (n 5 is the dropped still); copied from
    tests/test_character_dataset.py's make_character and _untrained."""
    cdir = os.path.join(lib, "kyra")
    os.makedirs(os.path.join(cdir, "lora"), exist_ok=True)
    data = {"schema_version": 1, "name": "kyra", "trigger": "kyrawmn", "class_noun": "woman",
            "referring_phrase": "the woman in grey", "descriptor": DESCRIPTOR, "seed": 0,
            "source": {"type": "seed_image", "path": "/fixtures/seed.png"},
            "strength": None, "status": "untrained", "created_at": "2026-10-06T01:02:03Z",
            "dataset": {"reference": "char_00", "kept": 24, "total": 25, "min_score": 7,
                        "face_height": 0.38,
                        "contact_sheet": os.path.join(cdir, "dataset", "contact_sheet.jpg")},
            "loras": {"video": None, "stills": None}, "stills_skip_reason": None}
    kept_ns = [n for n in range(25) if n != 5]
    for sub in ("stills", "captions", "videos"):
        os.makedirs(os.path.join(cdir, "dataset", sub), exist_ok=True)
    items = []
    for n in range(25):
        Image.new("RGB", (8, 8), (n, n, n)).save(os.path.join(cdir, "dataset", "stills",
                                                              "char_%02d.png" % n))
        if n in kept_ns:
            with open(os.path.join(cdir, "dataset", "captions", "char_%02d.txt" % n), "w") as f:
                f.write("kyrawmn woman, close-up, n %d" % n)
            with open(os.path.join(cdir, "dataset", "videos", "char_%02d.mp4" % n), "wb") as f:
                f.write(b"mp4")
        items.append({"n": n, "kept": n in kept_ns})
    with open(os.path.join(cdir, "dataset", "manifest.json"), "w") as f:
        json.dump({"items": items}, f)
    character_lib.write_character(data)
    return data


def _safetensors_bytes(keys):
    header = {"__metadata__": {"format": "pt"}}
    for i, key in enumerate(keys):
        header[key] = {"dtype": "F32", "shape": [1], "data_offsets": [4 * i, 4 * i + 4]}
    raw = json.dumps(header).encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw + b"\0" * (4 * len(keys))


def _video_fakes(calls, preprocess_rc):
    """run_logged and SKILL.generate_video fakes (tests/test_character_dataset.py:579-614)."""

    def _run(cmd, log_path, cwd, env, timeout_s):
        calls.append({"fake": "run_logged", "argv": list(cmd), "cwd": cwd,
                      "hf_home": env.get("HF_HOME"), "log": log_path, "timeout_s": timeout_s})
        if cmd[1] == "preprocess":
            out_dir = cmd[cmd.index("-o") + 1]
            videos = cmd[cmd.index("--videos") + 1]
            latent_dir = os.path.join(out_dir, ".precomputed", "latents")
            os.makedirs(latent_dir)
            for i in range(len(os.listdir(videos))):
                open(os.path.join(latent_dir, "l%02d.safetensors" % i), "wb").close()
            return preprocess_rc
        ckpt_dir = os.path.join(os.path.dirname(cmd[cmd.index("--config") + 1]), "out",
                                "checkpoints")
        os.makedirs(ckpt_dir)
        with open(os.path.join(ckpt_dir, character_dataset.VIDEO_FINAL_CKPT), "wb") as f:
            f.write(b"lora")
        return 0

    def _generate(prompt, output_path, **kwargs):
        calls.append({"fake": "generate_video", "prompt": prompt, "output_path": output_path,
                      "kwargs": kwargs})
        with open(output_path, "wb") as f:
            f.write(b"mp4")
        return output_path

    return [(character_dataset, "run_logged", _run),
            (character_dataset.SKILL, "generate_video", _generate)]


def _stills_fakes(calls, injected):
    """run_logged (mflux-train) and run_zimage_child fakes (tests/test_character_dataset.py:
    968-998)."""

    def _run(cmd, log_path, cwd, env, timeout_s):
        calls.append({"fake": "run_logged", "argv": list(cmd), "cwd": cwd,
                      "hf_home": env.get("HF_HOME"), "log": log_path, "timeout_s": timeout_s})
        with open(cmd[cmd.index("--config") + 1]) as f:
            config = json.load(f)
        out = config["checkpoint"]["output_path"]
        zip_path = os.path.join(out, "checkpoints",
                                "%07d_checkpoint.zip" % config["checkpoint"]["save_frequency"])
        os.makedirs(os.path.dirname(zip_path))
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("0002400_adapter.safetensors", _safetensors_bytes(TWO_MODULE_KEYS))
        return 0

    def _child(spec, char_dir, step):
        calls.append({"fake": "run_zimage_child", "spec": spec, "dir": char_dir, "step": step})
        for job in spec["jobs"]:
            Image.new("RGB", (16, 10), (1, 2, 3)).save(job["output_path"])
        return {"jobs": [{"output_path": j["output_path"], "status": "ok", "seconds": 1.0}
                         for j in spec["jobs"]],
                "injected_lora_modules": injected if spec["loras"] else None}

    return [(character_dataset, "run_logged", _run),
            (character_dataset, "run_zimage_child", _child)]


CASES = (
    ("train_video ok", "video", 0, character_dataset.train_video),
    ("train_video preprocess exit 1", "video", 1, character_dataset.train_video),
    ("train_stills ok", "stills", 2, character_dataset.train_stills),
    ("train_stills compat reject", "stills", 1, character_dataset.train_stills),
)


def _case(root, kind, value, train):
    """One case under the fresh directory root: the record dict of spec 6.3 step 4."""
    lib = os.path.join(root, "characters")
    dev = os.path.join(root, "dev-model")
    os.makedirs(dev)
    with open(os.path.join(dev, "transformer-dev.safetensors"), "wb") as f:
        f.write(b"dev")
    test_model = os.path.join(root, "test-model")
    os.makedirs(test_model)
    stub = os.path.join(root, "stub-bin")
    with open(stub, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(stub, 0o755)
    calls = []
    fakes = _video_fakes(calls, value) if kind == "video" else _stills_fakes(calls, value)
    out, err = io.StringIO(), io.StringIO()
    env = {"HOME": os.path.join(root, "home"), "CHARACTER_LIBRARY_DIR": lib,
           "LOCATION_LIBRARY_DIR": os.path.join(root, "locations"),
           "LORA_CATALOG_DIR": os.path.join(root, "loras")}
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.dict(os.environ, env))
        for target, name, replacement in [
                (character_dataset, "TRAIN_MODEL_DIR", dev),
                (character_dataset, "TEST_MODEL_DIR", test_model),
                (character_dataset.SKILL, "LTX2_MLX_BIN", stub),
                (character_dataset, "MFLUX_TRAIN", stub),
                (character_lib, "utc_now", lambda: NOW)] + fakes:
            stack.enter_context(mock.patch.object(target, name, replacement))
        data = _untrained(lib)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            outcome = train(data)
    char_dir = os.path.join(lib, "kyra")
    config = None
    for rel in (("train", "video", "train.yaml"), ("train", "stills", "train.json")):
        path = os.path.join(char_dir, *rel)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                config = f.read()
    with open(os.path.join(char_dir, "character.json"), encoding="utf-8") as f:
        character_json = f.read()
    files = []
    for dirpath, _dirnames, filenames in os.walk(char_dir):
        files += [os.path.relpath(os.path.join(dirpath, n), char_dir) for n in filenames]
    return {"outcome": outcome, "calls": calls, "config": config,
            "character_json": character_json, "stdout": out.getvalue(), "stderr": err.getvalue(),
            "files": sorted(files)}


def golden_record():
    """The golden JSON text of spec 6.3 (ends with one newline)."""
    top = tempfile.mkdtemp(prefix="location-golden-")
    try:
        record = {}
        for k, (label, kind, value, train) in enumerate(CASES, start=1):
            root = os.path.join(top, "case%d" % k)
            os.makedirs(root)
            record[label] = _case(root, kind, value, train)
        text = json.dumps(record, indent=2, sort_keys=True)
    finally:
        shutil.rmtree(top, ignore_errors=True)
    replacements = [(os.path.realpath(top), "<TMP>"), (top, "<TMP>"),
                    (character_dataset.SKILL.LTX2_MLX_HF_HOME, "<LTX2_MLX_HF_HOME>"),
                    (character_dataset.SKILL.LTX2_MLX_DIR, "<LTX2_MLX_DIR>"),
                    (character_dataset.MFLUX_HF_HOME, "<MFLUX_HF_HOME>")]
    for value, token in sorted(replacements, key=lambda item: -len(item[0])):
        text = text.replace(value, token)
    return STAMP_RE.sub("<STAMP>", text) + "\n"


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    """HOME and every library directory under tmp_path for each test (spec 6.2)."""
    env = seu.set_story_env(monkeypatch, tmp_path)
    env["locations"] = os.path.join(str(tmp_path), "locations")
    monkeypatch.setenv("LOCATION_LIBRARY_DIR", env["locations"])
    return env


def test_lg1_the_character_golden_record_is_unchanged():
    with open(FIXTURE, encoding="utf-8") as f:
        expected = f.read()
    assert golden_record() == expected
    assert hashlib.sha256(expected.encode("utf-8")).hexdigest() == hashlib.sha256(
        golden_record().encode("utf-8")).hexdigest()


def main(argv):
    if argv != ["--write-fixture"]:
        print("usage: python3 tests/test_location_golden.py --write-fixture", file=sys.stderr)
        return 2
    text = golden_record()
    os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
    with open(FIXTURE, "w", encoding="utf-8") as f:
        f.write(text)
    print("wrote %s (%d bytes, sha256 %s)" % (FIXTURE, len(text.encode("utf-8")),
                                              hashlib.sha256(text.encode("utf-8")).hexdigest()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

**1.2.** Create `tests/test_location_story.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""Tests for the location library's story use (docs/superpowers/specs/
2026-10-29-location-lora-design.md, Sections 4.3-4.6 and 6.7: LS1-LS14, with the plan's Review
Focus pins): the plan prompt's fixed places, plan normalisation, P21 location presence and the
L4 LoRA count.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_location_story.py
Stdlib plus pytest. No test reads the real HOME, renders, trains, runs Z-Image or the editor,
contacts a model server or touches port 8178: every model call goes to the fake bin/qwen-agent of
a temporary workspace (story_engine_testutil.make_ws), and every test runs under the autouse
story_env fixture (a temporary HOME, character library, location library and LoRA catalog). The
plan fixtures under tests/fixtures/location/ were written at d210c26, before story_engine.py was
edited (spec 6.3).
"""

import importlib.machinery
import json
import os
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


se = _load("story_engine_for_location_story", "story_engine.py")
cl = _load("character_lib_for_location_story", "character_lib.py")
FIXTURES = os.path.join(WS, "tests", "fixtures", "location")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    env = seu.set_story_env(monkeypatch, tmp_path)
    env["locations"] = os.path.join(str(tmp_path), "locations")
    os.makedirs(env["locations"], exist_ok=True)
    monkeypatch.setenv("LOCATION_LIBRARY_DIR", env["locations"])
    return env


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


# --- LS1: without locations, every plan prompt and plan.json is byte-identical (LK5) ---------

def test_ls1_without_locations_plan_prompts_and_plans_are_byte_identical(ws, story_env):
    seu.kyra(story_env["lib"])
    seu.ronin(story_env["lib"])
    members = cl.resolve_cast([(None, "kyra"), (None, "ronin")])
    for name, kw in (("plan_prompt_chained.txt", dict(mode="chained")),
                     ("plan_prompt_shots.txt", dict(mode="shots", panels=4)),
                     ("plan_prompt_chained_cast.txt", dict(mode="chained", members=members))):
        with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
            expected = f.read()
        assert se.build_plan_prompt(seu.make_ctx(se, ws, **kw), [], []) == expected, name
    plan, _shape = se.normalize_plan(seu.make_ctx(se, ws), seu.plan_json("chained", 3))
    with open(os.path.join(FIXTURES, "normalized_plan_chained.json"), encoding="utf-8") as f:
        assert json.dumps(plan, indent=2, sort_keys=True) == f.read()
    assert [sorted(entry) for entry in plan["locations"]] == [["id", "setting"]] * 2
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_golden.py tests/test_location_story.py 2>&1 | tail -1
```

Expected: `2 failed` (both fixtures are missing: `FileNotFoundError` for `character_train_golden.json` and `plan_prompt_chained.txt`).

- [ ] **Step 3: Write the fixtures (no code change).**

The fixtures are generated, not hand-written (spec 8 step 2). `$D/plan_fixtures.py` was written in "Before Task 1" Step 4. Run both commands from `WS`:

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/loc-baseline
cd $S/loc-wt/qwen-agent-workspace
git diff --quiet d210c26 -- character_dataset.py story_engine.py && echo "unedited at d210c26"
python3 -B tests/test_location_golden.py --write-fixture
python3 -B $D/plan_fixtures.py
ls tests/fixtures/location/
shasum -a 256 tests/fixtures/location/*
```

Expected:
- `unedited at d210c26`;
- `wrote .../tests/fixtures/location/character_train_golden.json (37451 bytes, sha256 8dd90aea39df434eafafaefa72a392f9d496619206022f8e869d257beac7db28)`;
- `wrote 4 plan fixtures to .../tests/fixtures/location`;
- the five files `character_train_golden.json`, `normalized_plan_chained.json`, `plan_prompt_chained.txt`, `plan_prompt_chained_cast.txt`, `plan_prompt_shots.txt`.

The golden record's size and sha256 were measured on the plan's replay. If they differ, report both values and continue: the fixture written here, at `d210c26`, is the reference. Run `--write-fixture` a second time: the sha256 must not change (the record is deterministic).

- [ ] **Step 4: Run the new tests and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_golden.py tests/test_location_story.py 2>&1 | tail -1
```

Expected: `2 passed`. Run the compile check with `FILES` = `tests/test_location_golden.py tests/test_location_story.py`; expected: `compiled 2` twice. Then run the gate block with `N=1`. Expected: `GATE PASS`, `new-file tests 2, not passing 0`, `baseline failures still failing 2 of 2` and `OK 347/347`, with no `LOST` line.

- [ ] **Step 5: Commit (test-only).**

```bash
git add tests/test_location_golden.py tests/test_location_story.py tests/fixtures/location/character_train_golden.json tests/fixtures/location/normalized_plan_chained.json tests/fixtures/location/plan_prompt_chained.txt tests/fixtures/location/plan_prompt_chained_cast.txt tests/fixtures/location/plan_prompt_shots.txt
git diff --cached --name-only    # expected: exactly those 7 paths, with the qwen-agent-workspace/ prefix
git commit -m "test(location): capture the character training golden record and the plan fixtures at d210c26 (spec 6.3; LG1, LS1)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `location_lib.py`, the record and its rules (L1.1, L1.3, L1.4, L2.6-L2.9, L3.2, L3.7 reader; LL2-LL14)

This task implements:
- L1.1/1.3 names: `library_dir`, `location_dir`, `location_json_path` (`$LOCATION_LIBRARY_DIR` or `WS/generated/locations`).
- L1.3: `normalize_description` and `validate_description` (rules 1-4, in order).
- L1.4: `TRIGGER_RE`, `validate_trigger`, `description_words`, the `.triggers` registry (`registered_triggers`, `register_trigger`), `all_triggers` (locations and characters) and `auto_trigger` (class noun `"place"`).
- L2.6, L2.7: `validate_location` (every row of the spec 3.7 table, consistency last), `load_location`, `write_location` (atomic), `list_names`.
- L2.8: `VIDEO_BASE_MODEL`, `model_compatible`.
- L2.9: `LocationPin`, `UnusableLocationError`, `resolve_locations`, `usable_locations`, `format_available_line`.
- L1.2 `list`: `LIST_ROW_FORMAT`, `location_table_lines`.
- L3.2 and L3.7: `plan_location_names`, `plan_panel_locations`, `prefix_location_trigger`.
- Spec 6.2: `tests/location_testutil.py` (`make_location` and helpers) and the `story_engine_testutil` edits (`set_story_env` sets and returns `LOCATION_LIBRARY_DIR`; `LINKED_FILES` gains `location_lib.py`).

`_character_lib()` reuses `sys.modules["character_lib"]` when it came from the same file, as `bin/lora-check`'s `_load` does, so a by-path load never re-executes a caller's module (Plan ruling LR19). `all_triggers()` names each owner as `location NAME` or `character NAME`, so the create refusal says which library owns a taken trigger (Plan ruling LR8).

Tests: LL2-LL14 in the new `tests/test_location_lib.py` (LL1, the compile check of every changed file, is added in Task 13, when every file it names exists).

**Files:**
- Create: `location_lib.py`, `tests/location_testutil.py`, `tests/test_location_lib.py`.
- Modify: `tests/story_engine_testutil.py`: `set_story_env` (`:46-57` and its return `:64`), `LINKED_FILES` (`:182-183`).
- Read only: `character_lib.py` (`NAME_RE`/`TRIGGER_RE` `:30-31`, `registered_triggers` `:496-516`, `register_trigger` `:519-523`, `auto_trigger` `:526-539`, `resolve_cast` `:558-597`, `prefix_character_triggers` `:905-919`, `character_table_lines` `:1467-1482`, `SHOTS_SETTING_MIN_WORDS` `:50`), `story_engine.py` (`_setting_length` `:1611-1614`, `_setting_problems` `:1617-1625`).

**Interfaces:**
- Consumes (existing): `character_lib.registered_triggers() -> {trigger: name}`, `character_lib.auto_trigger(name, class_noun, taken, avoid=()) -> str`, `character_lib.register_trigger(trigger, name)`; `story_engine._setting_problems(setting) -> [str]`, `story_engine._setting_length(setting) -> str or None` (LL3 only).
- Produces, in `location_lib` (every later task uses these names exactly):
  - constants `LIBRARY_ENV`, `SCHEMA_VERSION = 1`, `NAME_RE`, `TRIGGER_RE`, `SHA256_RE`, `UTC_RE`, `TRIGGER_REGISTRY = ".triggers"`, `STATUSES`, `SOURCES`, `MIN_SCORE = 7`, `MIN_KEEP = 12`, `TOTAL_STILLS = 24`, `MAX_PHOTOS = 24`, `MAX_LOCATIONS = 3`, `DESCRIPTION_MIN_WORDS = 15`, `DESCRIPTION_MAX_WORDS = 40`, `DEFAULT_LOCATION_STRENGTH = 0.8`, `TRIGGER_CLASS_NOUN = "place"`, `VIDEO_BASE_MODEL = "dgrauet/ltx-2.3-mlx-q8"`, `STILLS_BASE_MODEL = "Tongyi-MAI/Z-Image-Turbo"`, `PLAN_SCHEMA`, `LIST_ROW_FORMAT`, `NO_LOCATIONS_AVAILABLE`, `NO_PLAN_NOTE`, `UNUSABLE_PLAN_NOTE`;
  - `class LocationError(Exception)`, `class UnusableLocationError(LocationError)`;
  - `LocationPin = namedtuple("LocationPin", ["name", "trigger", "description", "video_lora", "stills_lora", "stills_skip_reason", "strength", "base_model", "attach_video"])`;
  - `library_dir() -> str`, `location_dir(name) -> str`, `location_json_path(name) -> str`, `utc_now() -> str`;
  - `validate_name(name)`, `normalize_description(text) -> str`, `validate_description(text)`, `description_words(description) -> [str]`, `validate_trigger(trigger, description=None)`;
  - `validate_location(data, name=None)`, `load_location(name) -> dict`, `write_location(data)`, `list_names() -> [str]`;
  - `registered_triggers() -> {trigger: name}`, `register_trigger(trigger, name)`, `all_triggers() -> {trigger: "location NAME" or "character NAME"}`, `auto_trigger(name, description, taken) -> str`;
  - `model_compatible(base_model, model) -> bool`, `resolve_locations(names) -> [LocationPin]`, `usable_locations() -> [str]`, `format_available_line(names) -> str`, `location_table_lines() -> [str]`;
  - `plan_location_names(story_dir) -> set or None`, `plan_panel_locations(story_dir, n_panels, names) -> ([str or None], str or None)`, `prefix_location_trigger(prompt, trigger) -> str`.
- Produces, in `tests/location_testutil.py`: `VIDEO_BYTES`, `STILLS_BYTES`, `HARBOUR_DESC` (24 words), `TEMPLE_DESC` (30), `MILL_DESC` (20), `make_location(lib, name, trigger, description, status="trained", source="text", stills=False, strength=None) -> dict`, `harbour(lib, **kw)` (`harbour-street`, `harboplc`), `temple(lib, **kw)` (`temple-gate`, `templplc`), `mill(lib, **kw)` (`old-mill`, `oldmiplc`), `write_plan(story_dir, beat_locations, pinned=(("l1", "harbour-street"),), extra=()) -> dict`.
- Produces, in `tests/story_engine_testutil.py`: `set_story_env(...)` returns `{"home", "lib", "catalog", "locations"}`.

- [ ] **Step 1: Write the failing tests.**

**1.1.** Create `tests/location_testutil.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""Shared helpers for the location library tests (docs/superpowers/specs/
2026-10-29-location-lora-design.md, Section 6.2).

Not a test module (pytest does not collect it). Every helper writes under a directory the caller
passes in; nothing here reads or writes the real HOME, renders, trains or contacts a server.
"""

import hashlib
import json
import os

VIDEO_BYTES = b"fake-place-lora!"
STILLS_BYTES = b"fake-place-still"
VIDEO_BASE_MODEL = "dgrauet/ltx-2.3-mlx-q8"
STILLS_BASE_MODEL = "Tongyi-MAI/Z-Image-Turbo"
# 24, 30 and 20 words; none contains a period, an exclamation or question mark, or a double quote.
HARBOUR_DESC = ("a narrow cobbled harbour street lined with weathered stone warehouses, green wooden "
                "shutters, rusted mooring rings and faded red fishmonger signs above granite quays")
TEMPLE_DESC = ("an old hillside temple gate of red lacquered timber with a curved tiled roof, stone "
               "lanterns, worn granite steps, paper prayer charms and tall cedar trees behind a "
               "mossy wall")
MILL_DESC = ("an old timber water mill beside a shallow weir with a mossy wheel, a slate roof and a "
             "cobbled yard")


def make_location(lib, name, trigger, description, status="trained", source="text", stills=False,
                  strength=None):
    """Write a valid location.json (location library spec 3.6, 3.7) under lib/name and return
    the dict. untrained and trained records get a 21-of-24 dataset; a trained one also gets a
    16-byte lora/video.safetensors (base dgrauet/ltx-2.3-mlx-q8), plus a 16-byte
    lora/stills.safetensors when stills, each entry with its real sha256. A photos record lists
    one photo."""
    ldir = os.path.join(lib, name)
    os.makedirs(os.path.join(ldir, "lora"), exist_ok=True)
    dataset = None
    if status in ("untrained", "trained"):
        dataset = {"kept": 21, "total": 24, "min_score": 7,
                   "contact_sheet": os.path.join(ldir, "contact_sheet.jpg")}
    video = stills_entry = trained_at = None
    if status == "trained":
        video_path = os.path.join(ldir, "lora", "video.safetensors")
        with open(video_path, "wb") as f:
            f.write(VIDEO_BYTES)
        video = {"path": video_path, "sha256": hashlib.sha256(VIDEO_BYTES).hexdigest(),
                 "base_model": VIDEO_BASE_MODEL, "rank": 32, "alpha": 32, "steps": 1000}
        trained_at = "2026-10-29T12:00:00Z"
        if stills:
            stills_path = os.path.join(ldir, "lora", "stills.safetensors")
            with open(stills_path, "wb") as f:
                f.write(STILLS_BYTES)
            stills_entry = {"path": stills_path,
                            "sha256": hashlib.sha256(STILLS_BYTES).hexdigest(),
                            "base_model": STILLS_BASE_MODEL, "rank": 16, "alpha": 16,
                            "steps": 672}
    photos = []
    if source == "photos":
        photos = [{"path": "/fixtures/photos/%s_01.jpg" % name,
                   "sha256": hashlib.sha256(name.encode("utf-8")).hexdigest()}]
    data = {"schema_version": 1, "name": name, "trigger": trigger, "description": description,
            "source": source, "photos": photos, "seed": 0, "status": status,
            "created_at": "2026-10-29T10:00:00Z", "trained_at": trained_at, "dataset": dataset,
            "loras": {"video": video, "stills": stills_entry}, "stills_skip_reason": None,
            "strength": strength}
    with open(os.path.join(ldir, "location.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def harbour(lib, **kw):
    return make_location(lib, "harbour-street", "harboplc", HARBOUR_DESC, **kw)


def temple(lib, **kw):
    return make_location(lib, "temple-gate", "templplc", TEMPLE_DESC, **kw)


def mill(lib, **kw):
    return make_location(lib, "old-mill", "oldmiplc", MILL_DESC, **kw)


def write_plan(story_dir, beat_locations, pinned=(("l1", "harbour-street"),), extra=()):
    """A minimal usable plan.json in story_dir: locations l1.. (location_name from pinned, else
    null; plus extra ids), one beat per entry of beat_locations, each at that location id.
    Returns the plan dict."""
    os.makedirs(story_dir, exist_ok=True)
    names = dict(pinned)
    ids = sorted(set(list(names) + list(extra) + list(beat_locations)))
    plan = {"schema": "ltx-movie.plan.v1", "mode": "chained", "panels": len(beat_locations),
            "cast": [], "props": [],
            "locations": [{"id": i, "setting": "The setting is a place %s." % i,
                           "location_name": names.get(i)} for i in ids],
            "beats": [{"index": k, "location": loc, "cast": []}
                      for k, loc in enumerate(beat_locations, start=1)],
            "loras": {"global": [], "per_beat": {}, "stills": [], "pinned": []}}
    with open(os.path.join(story_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)
    return plan
```

**1.2.** Create `tests/test_location_lib.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""Tests for location_lib.py (docs/superpowers/specs/2026-10-29-location-lora-design.md,
Sections 2.2-2.4, 3.6-3.9 and 4.7, test table 6.4: LL1-LL14): the description and trigger rules,
the location.json schema, library I/O, resolution of pinned locations, model compatibility, the
trigger prefix and the plan reader.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_location_lib.py
Stdlib plus pytest. No test reads the real HOME, renders, trains, runs Z-Image or the editor,
contacts a model server or touches port 8178: every test runs under the autouse env fixture
(HOME, CHARACTER_LIBRARY_DIR, LOCATION_LIBRARY_DIR and LORA_CATALOG_DIR under tmp_path), and every
LoRA file is a few bytes.
"""

import importlib.machinery
import json
import os
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import location_testutil as lt  # noqa: E402
import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


ll = _load("location_lib_for_tests", "location_lib.py")
cl = _load("character_lib_for_location_tests", "character_lib.py")
se = _load("story_engine_for_location_lib", "story_engine.py")


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


def _words(n, start="a"):
    """A valid description of exactly n words: start, then n - 1 distinct stone words."""
    return " ".join([start] + ["stone%d" % k for k in range(1, n)])


def _raises(fn, *args):
    with pytest.raises(ll.LocationError) as info:
        fn(*args)
    return str(info.value)


# --- LL2, LL3: the description rule and its arithmetic (L1.3) ------------------------------

def test_ll2_the_description_rule():
    assert ll.normalize_description("  The  old mill by the weir.") == "the old mill by the weir"
    assert ll.normalize_description("A quay\n with  boats") == "a quay with boats"
    assert ll.normalize_description(7) == 7
    ll.validate_description(_words(15))
    ll.validate_description(_words(40))
    assert _raises(ll.validate_description, _words(14)) == "description: must be 15-40 words, got 14"
    assert _raises(ll.validate_description, _words(41)) == "description: must be 15-40 words, got 41"
    rule4 = "description: must be one noun phrase with no . ! ? or double quote"
    body = " ".join("stone%d" % k for k in range(1, 20))
    for text in ("a quay. With " + body, "a quay! " + body, 'a quay "old" ' + body,
                 "a quay\n" + body, "a quay\r" + body, "a quay? " + body):
        assert _raises(ll.validate_description, text) == rule4, text
    assert _raises(ll.validate_description, "one quay " + body) == (
        'description: must start with "a ", "an " or "the "')
    assert _raises(ll.validate_description, " a quay " + body).startswith(
        "description: must be a string without leading or trailing whitespace")
    assert _raises(ll.validate_description, None).startswith("description: must be a string")
    for start in ("a", "an", "the"):
        ll.validate_description(_words(20, start))
    ll.validate_description(lt.HARBOUR_DESC)
    ll.validate_description(lt.TEMPLE_DESC)
    ll.validate_description(lt.MILL_DESC)
    assert [len(d.split()) for d in (lt.HARBOUR_DESC, lt.TEMPLE_DESC, lt.MILL_DESC)] == [24, 30, 20]


def test_ll3_the_setting_arithmetic():
    for w in range(15, 41):
        description = _words(w)
        ll.validate_description(description)
        setting = "The setting is %s." % description
        assert len(setting.split()) == w + 3
        assert se._setting_problems(setting) == []
        assert se._setting_length(setting) is None
    assert 15 + 3 >= cl.SHOTS_SETTING_MIN_WORDS == 12
    assert (ll.DESCRIPTION_MIN_WORDS, ll.DESCRIPTION_MAX_WORDS) == (15, 40)


# --- LL4, LL5: triggers and the registry (L1.4) ---------------------------------------------

def test_ll4_triggers(env):
    assert ll.TRIGGER_RE.pattern == cl.TRIGGER_RE.pattern
    assert ll.NAME_RE.pattern == cl.NAME_RE.pattern
    assert ll.auto_trigger("harbour-street", lt.HARBOUR_DESC, set()) == "harboplc"
    assert ll.auto_trigger("harbour-street", lt.HARBOUR_DESC, {"harboplc"}) == "harboplc2"
    assert ll.auto_trigger("old-mill", lt.MILL_DESC, set()) == "oldmiplc"
    assert ll.auto_trigger("harbour-street", "a harboplc " + lt.HARBOUR_DESC[2:], set()) == (
        "harboplc2")
    cl.register_trigger("kyrawmn", "kyra")
    owners = ll.all_triggers()
    assert owners["kyrawmn"] == "character kyra"
    ll.register_trigger("harboplc", "harbour-street")
    assert ll.all_triggers()["harboplc"] == "location harbour-street"
    ll.validate_trigger("harbour1")
    assert _raises(ll.validate_trigger, "Bad") == "trigger must match [a-z][a-z0-9]{3,15}, got 'Bad'"
    assert _raises(ll.validate_trigger, "harbour", lt.HARBOUR_DESC) == (
        "trigger harbour must not be a word of the description")
    ll.validate_trigger("harboplc", lt.HARBOUR_DESC)
    assert ll.description_words("A Quay, with 2 boats") == ["a", "quay", "with", "2", "boats"]


def test_ll5_the_registry(env):
    lib = env["locations"]
    ll.register_trigger("harboplc", "harbour-street")
    with open(os.path.join(lib, ".triggers"), encoding="utf-8") as f:
        assert f.read() == "harboplc harbour-street\n"
    lt.temple(lib)
    assert ll.registered_triggers() == {"harboplc": "harbour-street", "templplc": "temple-gate"}
    # A failed create leaves its trigger registered: never reused.
    ll.register_trigger("deadpplc", "dead-place")
    assert "deadpplc" in ll.registered_triggers()
    assert ll.auto_trigger("dead-place", lt.MILL_DESC, set(ll.all_triggers())) == "deadpplc2"


# --- LL6, LL14: the validation table (L2.7) -------------------------------------------------

def _valid(env, **kw):
    return lt.make_location(env["locations"], "harbour-street", "harboplc", lt.HARBOUR_DESC, **kw)


def test_ll6_the_validation_table(env):
    for kw in (dict(), dict(status="untrained"), dict(status="dataset"), dict(source="photos"),
               dict(stills=True), dict(strength=0.6)):
        ll.validate_location(_valid(env, **kw), name="harbour-street")
    base = _valid(env, stills=True)
    cases = [
        (lambda d: d.pop("strength"), "top level"),
        (lambda d: d.update(extra=1), "top level"),
        (lambda d: d.update(schema_version=2), "schema_version"),
        (lambda d: d.update(schema_version=True), "schema_version"),
        (lambda d: d.update(name="Bad_name"), "name"),
        (lambda d: d.update(trigger="Harbo"), "trigger"),
        (lambda d: d.update(trigger="harbour"), "trigger"),
        (lambda d: d.update(description="a quay"), "description"),
        (lambda d: d.update(source="video"), "source"),
        (lambda d: d.update(photos=[{"path": "/p.jpg", "sha256": "0" * 64}]), "photos"),
        (lambda d: d.update(source="photos", photos=[]), "photos"),
        (lambda d: d.update(source="photos", photos=[{"path": "rel.jpg", "sha256": "0" * 64}]),
         "photos"),
        (lambda d: d.update(source="photos", photos=[{"path": None, "sha256": "XY"}]), "photos"),
        (lambda d: d.update(seed=-1), "seed"),
        (lambda d: d.update(seed=True), "seed"),
        (lambda d: d.update(status="ready"), "status"),
        (lambda d: d.update(created_at="2026-10-29 10:00:00"), "created_at"),
        (lambda d: d.update(trained_at="yesterday"), "trained_at"),
        (lambda d: d["dataset"].update(kept=25), "dataset"),
        (lambda d: d["dataset"].update(min_score=0), "dataset"),
        (lambda d: d["dataset"].update(contact_sheet="sheet.jpg"), "dataset"),
        (lambda d: d["dataset"].pop("min_score"), "dataset"),
        (lambda d: d["loras"].pop("stills"), "loras"),
        (lambda d: d["loras"]["video"].update(path="lora.safetensors"), "loras.video"),
        (lambda d: d["loras"]["video"].update(sha256="ABC"), "loras.video"),
        (lambda d: d["loras"]["video"].update(base_model=""), "loras.video"),
        (lambda d: d["loras"]["video"].update(rank=0), "loras.video"),
        (lambda d: d["loras"]["video"].update(alpha=16), "loras.video"),
        (lambda d: d["loras"]["video"].update(steps=0), "loras.video"),
        (lambda d: d["loras"]["stills"].update(extra=1), "loras.stills"),
        (lambda d: d.update(stills_skip_reason=""), "stills_skip_reason"),
        (lambda d: d.update(strength=0), "strength"),
        # Consistency: trained exactly when loras.video and trained_at are set; untrained and
        # trained need a dataset with at least MIN_KEEP kept stills.
        (lambda d: d["loras"].update(video=None), "status"),
        (lambda d: d.update(trained_at=None), "trained_at"),
        (lambda d: d.update(status="untrained"), "status"),
        (lambda d: d.update(dataset=None), "status"),
        (lambda d: d["dataset"].update(kept=11), "status"),
    ]
    for mutate, field in cases:
        data = json.loads(json.dumps(base))
        mutate(data)
        message = _raises(ll.validate_location, data)
        assert message.startswith(field + ":"), (field, message)
    untrained = _valid(env, status="untrained")
    untrained["dataset"]["kept"] = 11
    assert _raises(ll.validate_location, untrained) == (
        "status: 'untrained' requires a dataset with at least 12 kept stills")
    assert _raises(ll.validate_location, dict(_valid(env), name="harbour-street"),
                   "other-name").startswith("name: 'harbour-street' does not match")


def test_ll14_the_strength_rule(env):
    ll.validate_location(_valid(env, strength=1.0))
    ll.validate_location(_valid(env, strength=1))
    for bad in (0, 1.01, True, "0.5", -0.2):
        assert _raises(ll.validate_location, _valid(env, strength=bad)).startswith(
            "strength: must be null or a number in (0, 1]"), bad


# --- LL7: library I/O -----------------------------------------------------------------------

def test_ll7_io(env):
    lib = env["locations"]
    data = lt.harbour(lib)
    ldir = os.path.join(lib, "harbour-street")
    data["strength"] = 0.5
    ll.write_location(data)
    assert ll.load_location("harbour-street")["strength"] == 0.5
    assert [n for n in os.listdir(ldir) if n.endswith(".tmp")] == []
    with open(os.path.join(ldir, "location.json"), encoding="utf-8") as f:
        before = f.read()
    assert before.endswith("}\n")
    data["strength"] = 2.0
    with pytest.raises(ll.LocationError):
        ll.write_location(data)
    with open(os.path.join(ldir, "location.json"), encoding="utf-8") as f:
        assert f.read() == before
    assert [n for n in os.listdir(ldir) if n.endswith(".tmp")] == []
    path = os.path.join(lib, "nowhere", "location.json")
    assert _raises(ll.load_location, "nowhere") == "unknown location: nowhere (no %s)" % path
    os.makedirs(os.path.join(lib, "broken"))
    with open(os.path.join(lib, "broken", "location.json"), "w") as f:
        f.write("{bad")
    assert _raises(ll.load_location, "broken").startswith("invalid location.json for broken: ")
    assert _raises(ll.load_location, "Bad") == (
        "location name must match [a-z][a-z0-9-]{1,23}, got 'Bad'")
    os.makedirs(os.path.join(lib, "Not_A_Name"))
    os.makedirs(os.path.join(lib, "empty-dir"))
    assert ll.list_names() == ["broken", "harbour-street"]
    assert ll.library_dir() == lib
    assert ll.location_dir("x") == os.path.join(lib, "x")


# --- LL8, LL9: resolution and model compatibility (L2.8, L2.9) ------------------------------

def test_ll8_resolution(env):
    lib = env["locations"]
    harbour = lt.harbour(lib, stills=True, strength=0.6)
    lt.temple(lib)
    lt.mill(lib, status="untrained")
    pins = ll.resolve_locations(["harbour-street", "temple-gate"])
    assert pins[0] == ll.LocationPin(
        "harbour-street", "harboplc", lt.HARBOUR_DESC, harbour["loras"]["video"]["path"],
        harbour["loras"]["stills"]["path"], None, 0.6, "dgrauet/ltx-2.3-mlx-q8", True)
    assert (pins[1].name, pins[1].stills_lora, pins[1].strength, pins[1].attach_video) == (
        "temple-gate", None, None, True)
    assert _raises(ll.resolve_locations, ["a", "b", "c", "d"]) == "at most 3 locations, got 4"
    assert _raises(ll.resolve_locations, ["temple-gate", "temple-gate"]) == (
        "location temple-gate is pinned more than once")
    with pytest.raises(ll.UnusableLocationError) as info:
        ll.resolve_locations(["old-mill"])
    assert str(info.value) == ("location old-mill is not trained (status untrained); run "
                               "bin/location train old-mill")
    with pytest.raises(ll.UnusableLocationError) as info:
        ll.resolve_locations(["nowhere"])
    assert str(info.value).startswith("unknown location: nowhere (no ")
    open(os.path.join(lib, "temple-gate", "lora", "video.safetensors"), "wb").close()
    with pytest.raises(ll.UnusableLocationError) as info:
        ll.resolve_locations(["temple-gate"])
    assert str(info.value) == "location temple-gate's video LoRA is missing or empty: %s" % (
        os.path.join(lib, "temple-gate", "lora", "video.safetensors"))
    os.remove(harbour["loras"]["stills"]["path"])
    with pytest.raises(ll.LocationError) as info:
        ll.resolve_locations(["harbour-street"])
    assert not isinstance(info.value, ll.UnusableLocationError)
    assert str(info.value) == "location harbour-street's stills LoRA is missing or empty: %s" % (
        harbour["loras"]["stills"]["path"])
    lt.make_location(lib, "dock-one", "dockplc", lt.HARBOUR_DESC)
    lt.make_location(lib, "dock-two", "dockplc", lt.MILL_DESC)
    assert _raises(ll.resolve_locations, ["dock-one", "dock-two"]) == (
        "locations dock-one and dock-two share the trigger dockplc")
    assert ll.usable_locations() == ["dock-one", "dock-two"]
    assert ll.format_available_line([]) == (
        "available locations: none (create one with bin/location create)")
    assert ll.format_available_line(["dock-one", "dock-two"]) == (
        "available locations: dock-one, dock-two")
    assert ll.resolve_locations([]) == []


def test_ll9_model_compatibility(env, monkeypatch, tmp_path):
    mlx = tmp_path / "ltx-2-mlx"
    (mlx / "models" / "ltx-2.3-mlx-q8").mkdir(parents=True)
    os.symlink(str(mlx / "models" / "ltx-2.3-mlx-q8"), str(tmp_path / "q8-link"))
    monkeypatch.setenv("LTX2_MLX_DIR", str(mlx))
    base = ll.VIDEO_BASE_MODEL
    assert base == "dgrauet/ltx-2.3-mlx-q8"
    assert ll.model_compatible(base, "dgrauet/ltx-2.3-mlx-q8") is True
    assert ll.model_compatible(base, str(mlx / "models" / "ltx-2.3-mlx-q8")) is True
    assert ll.model_compatible(base, str(tmp_path / "q8-link")) is True
    assert ll.model_compatible(base, "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8") is False
    assert ll.model_compatible(base, "~/ltx-2-mlx/models/ltx-2.5-mlx-q8") is False
    assert ll.model_compatible("other/base", "other/base") is True
    assert ll.model_compatible("other/base", str(mlx / "models" / "ltx-2.3-mlx-q8")) is False


# --- LL10, LL11: the trigger prefix and the plan reader (L3.7) -------------------------------

def test_ll10_the_trigger_prefix():
    assert ll.prefix_location_trigger("A street.", "harboplc") == "harboplc. A street."
    for prompt in ("harboplc. A street.", "A HARBOPLC street.", "The street (Harboplc) waits."):
        assert ll.prefix_location_trigger(prompt, "harboplc") == prompt
    assert ll.prefix_location_trigger("A xharboplc street.", "harboplc") == (
        "harboplc. A xharboplc street.")
    assert ll.prefix_location_trigger("A harboplc-x street.", "harboplc") == (
        "harboplc. A harboplc-x street.")


def test_ll11_the_plan_reader(tmp_path):
    story = str(tmp_path / "story")
    os.makedirs(story)
    assert ll.plan_panel_locations(story, 2, ["harbour-street"]) == ([None, None], (
        "note: there is no plan.json for this story; no location LoRAs are attached (location "
        "LoRAs attach only to planned beats)"))
    assert ll.plan_location_names(story) is None
    path = os.path.join(story, "plan.json")
    note = "note: plan.json is not usable for locations (%s); no location LoRAs are attached"
    for text, reason in (("{bad", "it is unreadable or not a JSON object"),
                         ("[]", "it is unreadable or not a JSON object"),
                         ('{"schema": "x"}', "its schema is not ltx-movie.plan.v1"),
                         ('{"schema": "ltx-movie.plan.v1", "locations": "l1"}',
                          "its locations are not a list of objects"),
                         ('{"schema": "ltx-movie.plan.v1", "locations": ["l1"]}',
                          "its locations are not a list of objects")):
        with open(path, "w") as f:
            f.write(text)
        assert ll.plan_panel_locations(story, 2, ["harbour-street"]) == ([None, None],
                                                                         note % reason), text
        assert ll.plan_location_names(story) is None, text
    lt.write_plan(story, ["l1", "l2", "l1"])
    assert ll.plan_panel_locations(story, 2, ["harbour-street"]) == (
        [None, None], note % "it has 3 beats for 2 panels")
    plan = lt.write_plan(story, ["l1", "l2"])
    plan["beats"][1]["location"] = ""
    with open(path, "w") as f:
        json.dump(plan, f)
    assert ll.plan_panel_locations(story, 2, ["harbour-street"]) == (
        [None, None], note % "beat 2 has no location id")
    lt.write_plan(story, ["l1", "l2", "l1", "l9", "l3"],
                  pinned=(("l1", "harbour-street"), ("l3", "temple-gate")))
    assert ll.plan_panel_locations(story, 5, ["harbour-street"]) == (
        ["harbour-street", None, "harbour-street", None, None], None)
    assert ll.plan_panel_locations(story, 5, ["harbour-street", "temple-gate"]) == (
        ["harbour-street", None, "harbour-street", None, "temple-gate"], None)
    assert ll.plan_panel_locations(story, 5, []) == ([None] * 5, None)
    assert ll.plan_location_names(story) == {"harbour-street", "temple-gate"}
    lt.write_plan(story, ["l1"], pinned=())
    assert ll.plan_location_names(story) == set()


# --- LL12: the library table (bin/location list) --------------------------------------------

def test_ll12_the_table(env):
    lib = env["locations"]
    assert ll.location_table_lines() == ["no locations in %s" % lib]
    lt.harbour(lib, stills=True)
    lt.mill(lib, status="untrained", source="photos")
    os.makedirs(os.path.join(lib, "bad-one"))
    with open(os.path.join(lib, "bad-one", "location.json"), "w") as f:
        f.write("{bad")
    lines = ll.location_table_lines()
    assert ll.LIST_ROW_FORMAT == "%-16s %-16s %-9s %-6s %-5s %-6s %s"
    assert lines[0] == ("NAME             TRIGGER          STATUS    SOURCE VIDEO STILLS "
                        "DESCRIPTION")
    assert lines[1].startswith("bad-one          (invalid: invalid location.json for bad-one: ")
    assert lines[2] == ("harbour-street   harboplc         trained   text   yes   yes    "
                        + lt.HARBOUR_DESC)
    assert lines[3] == ("old-mill         oldmiplc         untrained photos no    no     "
                        + lt.MILL_DESC)
    assert len(lines) == 4


# --- LL13: stdlib only, character_lib loaded only for triggers (spec 1.2) --------------------

def test_ll13_location_lib_is_stdlib_only(env, tmp_path):
    script = (
        "import importlib.machinery, sys\n"
        "m = importlib.machinery.SourceFileLoader('location_lib', %r).load_module()\n"
        "heavy = ('PIL', 'psutil', 'torch', 'character_dataset', 'character_lib')\n"
        "print(sorted(n for n in heavy if n in sys.modules))\n"
        "m.location_table_lines(); m.resolve_locations([]); m.usable_locations()\n"
        "print(sorted(n for n in heavy if n in sys.modules))\n"
        "m.all_triggers()\n"
        "print(sorted(n for n in heavy if n in sys.modules))\n"
    ) % os.path.join(WS, "location_lib.py")
    proc = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True,
                          env=dict(os.environ), cwd=str(tmp_path), timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == ["[]", "[]", "['character_lib']"]
```

**1.3.** Edit `tests/story_engine_testutil.py`: replace this text, which occurs exactly once:

```python
def set_story_env(monkeypatch, tmp_path):
    """Section 5.1's environment for one test: HOME, CHARACTER_LIBRARY_DIR and LORA_CATALOG_DIR
    under tmp_path, QWEN_AGENT_DAEMON_URL at a closed loopback port, STORY_PIPELINE_LOGGED=1,
    and no ANTHROPIC_API_KEY. Returns {"home", "lib", "catalog"} (paths as str)."""
    home = os.path.join(str(tmp_path), "home")
    lib = os.path.join(str(tmp_path), "characters")
    catalog = os.path.join(str(tmp_path), "loras")
    for path in (home, lib, catalog):
        os.makedirs(path, exist_ok=True)
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", lib)
    monkeypatch.setenv("LORA_CATALOG_DIR", catalog)
```

with:

```python
def set_story_env(monkeypatch, tmp_path):
    """Section 5.1's environment for one test: HOME, CHARACTER_LIBRARY_DIR, LOCATION_LIBRARY_DIR
    (location library spec 6.2) and LORA_CATALOG_DIR under tmp_path, QWEN_AGENT_DAEMON_URL at a
    closed loopback port, STORY_PIPELINE_LOGGED=1, and no ANTHROPIC_API_KEY. Returns {"home",
    "lib", "catalog", "locations"} (paths as str)."""
    home = os.path.join(str(tmp_path), "home")
    lib = os.path.join(str(tmp_path), "characters")
    catalog = os.path.join(str(tmp_path), "loras")
    locations = os.path.join(str(tmp_path), "locations")
    for path in (home, lib, catalog, locations):
        os.makedirs(path, exist_ok=True)
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", lib)
    monkeypatch.setenv("LORA_CATALOG_DIR", catalog)
    monkeypatch.setenv("LOCATION_LIBRARY_DIR", locations)
```

**1.4.** Edit `tests/story_engine_testutil.py`: replace this text, which occurs exactly once:

```python
    return {"home": home, "lib": lib, "catalog": catalog}
```

with:

```python
    return {"home": home, "lib": lib, "catalog": catalog, "locations": locations}
```

**1.5.** Edit `tests/story_engine_testutil.py`: replace this text, which occurs exactly once:

```python
LINKED_FILES = ("character_lib.py", "story_engine.py", "lora_catalog.py", "fleet_lib.py",
                "pipeline_log.py", "ltx_image_fit.py", "ltx2_mlx_video_skill.py")
```

with:

```python
LINKED_FILES = ("character_lib.py", "story_engine.py", "lora_catalog.py", "fleet_lib.py",
                "pipeline_log.py", "ltx_image_fit.py", "ltx2_mlx_video_skill.py", "location_lib.py")
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_lib.py 2>&1 | tail -1
```

Expected: `1 error` (collection: `FileNotFoundError` for `location_lib.py`).

- [ ] **Step 3: Implement.**

**3.1.** Create `location_lib.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""location_lib -- the location library's schema, validation, triggers, resolution and plan reader.

Stdlib only. This module is the single owner of the location.json schema (schema_version 1), of
the location name, description and trigger rules, of resolving pinned locations (--location NAME)
into LocationPin records, and of reading a story's plan.json for the panels set at a pinned
location. bin/location list/show import it at top level; bin/ltx-movie, bin/ltx-story-manifest
and bin/ltx-story-images load it by path, and only when --location is given. It loads
character_lib.py by path, and only inside the trigger functions that need the character registry.

The library root is $LOCATION_LIBRARY_DIR when set (test infrastructure only), else
<workspace>/generated/locations.

See docs/superpowers/specs/2026-10-29-location-lora-design.md, Sections 1.3, 2.1-2.4, 3.6-3.9,
4.2 and 4.7.
"""

import collections
import datetime
import importlib.machinery
import json
import os
import re
import sys
import uuid

WS = os.path.dirname(os.path.realpath(__file__))
LIBRARY_ENV = "LOCATION_LIBRARY_DIR"
SCHEMA_VERSION = 1
NAME_RE = re.compile(r"[a-z][a-z0-9-]{1,23}")
TRIGGER_RE = re.compile(r"[a-z][a-z0-9]{3,15}")          # character_lib.TRIGGER_RE
SHA256_RE = re.compile(r"[0-9a-f]{64}")
UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
TRIGGER_REGISTRY = ".triggers"
STATUSES = ("dataset", "untrained", "trained")
SOURCES = ("text", "photos")
MIN_SCORE = 7
MIN_KEEP = 12
TOTAL_STILLS = 24
MAX_PHOTOS = 24
MAX_LOCATIONS = 3
DESCRIPTION_MIN_WORDS = 15
DESCRIPTION_MAX_WORDS = 40
DEFAULT_LOCATION_STRENGTH = 0.8
TRIGGER_CLASS_NOUN = "place"
VIDEO_BASE_MODEL = "dgrauet/ltx-2.3-mlx-q8"
STILLS_BASE_MODEL = "Tongyi-MAI/Z-Image-Turbo"
PLAN_SCHEMA = "ltx-movie.plan.v1"
LIST_ROW_FORMAT = "%-16s %-16s %-9s %-6s %-5s %-6s %s"
NO_LOCATIONS_AVAILABLE = "available locations: none (create one with bin/location create)"
NO_PLAN_NOTE = ("note: there is no plan.json for this story; no location LoRAs are attached "
                "(location LoRAs attach only to planned beats)")
UNUSABLE_PLAN_NOTE = ("note: plan.json is not usable for locations (%s); no location LoRAs are "
                      "attached")

_TOP_LEVEL_KEYS = frozenset([
    "schema_version", "name", "trigger", "description", "source", "photos", "seed", "status",
    "created_at", "trained_at", "dataset", "loras", "stills_skip_reason", "strength"])
_DATASET_KEYS = frozenset(["kept", "total", "min_score", "contact_sheet"])
_LORA_KEYS = frozenset(["path", "sha256", "base_model", "rank", "alpha", "steps"])
_PHOTO_KEYS = frozenset(["path", "sha256"])
_WORD_RE = re.compile(r"[a-z0-9]+")
_FORBIDDEN_CHARS = (".", "!", "?", '"', "\n", "\r")


class LocationError(Exception):
    """A location library problem: bad input, a missing or invalid record, or a pin that cannot
    be resolved. The message is printed after "Error: "."""


class UnusableLocationError(LocationError):
    """The named location does not exist, cannot be loaded, or cannot render (not trained, or
    its video LoRA is missing or empty). bin/ltx-movie appends
    format_available_line(usable_locations()) (spec 3.9)."""


LocationPin = collections.namedtuple("LocationPin", [
    "name", "trigger", "description", "video_lora", "stills_lora", "stills_skip_reason",
    "strength", "base_model", "attach_video"])


def library_dir():
    return os.environ.get(LIBRARY_ENV) or os.path.join(WS, "generated", "locations")


def location_dir(name):
    return os.path.join(library_dir(), name)


def location_json_path(name):
    return os.path.join(library_dir(), name, "location.json")


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _character_lib():
    """character_lib.py loaded by path (spec 1.2); the copy already in sys.modules is reused
    when it was loaded from the same file, so a caller's character_lib state is never reset."""
    path = os.path.join(WS, "character_lib.py")
    loaded = sys.modules.get("character_lib")
    if loaded is not None and os.path.realpath(getattr(loaded, "__file__", None) or "") \
            == os.path.realpath(path):
        return loaded
    return importlib.machinery.SourceFileLoader("character_lib", path).load_module()


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_abs_path(value):
    return isinstance(value, str) and os.path.isabs(value)


def validate_name(name):
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise LocationError("location name must match [a-z][a-z0-9-]{1,23}, got %r" % (name,))


def normalize_description(text):
    """Whitespace runs collapsed to one space, stripped, one trailing "." dropped and stripped
    again, the first character lower-cased when it is upper-case (spec 2.3). A non-string is
    returned unchanged (validate_description refuses it)."""
    if not isinstance(text, str):
        return text
    text = " ".join(text.split())
    if text.endswith("."):
        text = text[:-1].strip()
    if text[:1].isupper():
        text = text[0].lower() + text[1:]
    return text


def validate_description(text):
    """The description rule of spec 2.3. Raises LocationError("description: <reason>")."""
    if not isinstance(text, str) or text != text.strip():
        raise LocationError("description: must be a string without leading or trailing "
                            "whitespace, got %r" % (text,))
    words = len(text.split())
    if not DESCRIPTION_MIN_WORDS <= words <= DESCRIPTION_MAX_WORDS:
        raise LocationError("description: must be 15-40 words, got %d" % words)
    if not text.startswith(("a ", "an ", "the ")):
        raise LocationError('description: must start with "a ", "an " or "the "')
    if any(c in text for c in _FORBIDDEN_CHARS):
        raise LocationError("description: must be one noun phrase with no . ! ? or double quote")


def description_words(description):
    """The lower-case words of a description, as the trigger rule compares them (spec 2.4)."""
    return _WORD_RE.findall(description.lower())


def validate_trigger(trigger, description=None):
    """The given-trigger rules of spec 2.4 that need no registry: TRIGGER_RE, and (when the
    description is known) not a word of the description."""
    if not isinstance(trigger, str) or not TRIGGER_RE.fullmatch(trigger):
        raise LocationError("trigger must match [a-z][a-z0-9]{3,15}, got %r" % (trigger,))
    if description is not None and trigger in description_words(description):
        raise LocationError("trigger %s must not be a word of the description" % trigger)


def _validate_lora_entry(field, entry):
    if not isinstance(entry, dict) or set(entry) != _LORA_KEYS:
        raise LocationError("%s: must be null or an object with exactly the keys %s, got %r"
                            % (field, ", ".join(sorted(_LORA_KEYS)), entry))
    if not _is_abs_path(entry["path"]):
        raise LocationError("%s: path must be an absolute path, got %r" % (field, entry["path"]))
    if not isinstance(entry["sha256"], str) or not SHA256_RE.fullmatch(entry["sha256"]):
        raise LocationError("%s: sha256 must be 64 lowercase hex characters, got %r"
                            % (field, entry["sha256"]))
    if not isinstance(entry["base_model"], str) or not entry["base_model"]:
        raise LocationError("%s: base_model must be a non-empty string, got %r"
                            % (field, entry["base_model"]))
    if not _is_int(entry["rank"]) or entry["rank"] < 1:
        raise LocationError("%s: rank must be an int >= 1, got %r" % (field, entry["rank"]))
    if not _is_int(entry["alpha"]) or entry["alpha"] != entry["rank"]:
        raise LocationError("%s: alpha must be an int equal to rank (%r), got %r"
                            % (field, entry["rank"], entry["alpha"]))
    if not _is_int(entry["steps"]) or entry["steps"] < 1:
        raise LocationError("%s: steps must be an int >= 1, got %r" % (field, entry["steps"]))


def validate_location(data, name=None):
    """Strict schema_version 1 validation (spec 3.7). Raises LocationError("<field>: <reason>").
    File existence is not checked here."""
    if not isinstance(data, dict):
        raise LocationError("top level: must be a JSON object, got %s" % type(data).__name__)
    missing = sorted(_TOP_LEVEL_KEYS - set(data))
    if missing:
        raise LocationError("top level: missing keys %s" % ", ".join(missing))
    extra = sorted(set(data) - _TOP_LEVEL_KEYS)
    if extra:
        raise LocationError("top level: unexpected keys %s" % ", ".join(extra))
    if not _is_int(data["schema_version"]) or data["schema_version"] != SCHEMA_VERSION:
        raise LocationError("schema_version: must be %d, got %r"
                            % (SCHEMA_VERSION, data["schema_version"]))
    if not isinstance(data["name"], str) or not NAME_RE.fullmatch(data["name"]):
        raise LocationError("name: must match [a-z][a-z0-9-]{1,23}, got %r" % (data["name"],))
    if name is not None and data["name"] != name:
        raise LocationError("name: %r does not match its directory name %r" % (data["name"], name))
    trigger = data["trigger"]
    if not isinstance(trigger, str) or not TRIGGER_RE.fullmatch(trigger):
        raise LocationError("trigger: must match [a-z][a-z0-9]{3,15}, got %r" % (trigger,))
    validate_description(data["description"])
    if trigger in description_words(data["description"]):
        raise LocationError("trigger: %r must not be a word of the description" % (trigger,))
    if data["source"] not in SOURCES:
        raise LocationError('source: must be "text" or "photos", got %r' % (data["source"],))
    photos = data["photos"]
    if data["source"] == "text":
        if photos != []:
            raise LocationError("photos: must be [] for a text location, got %r" % (photos,))
    else:
        if not isinstance(photos, list) or not 1 <= len(photos) <= MAX_PHOTOS:
            raise LocationError("photos: must be a list of 1 to 24 objects for a photo location, "
                                "got %r" % (photos,))
        for k, photo in enumerate(photos, start=1):
            if (not isinstance(photo, dict) or set(photo) != _PHOTO_KEYS
                    or not (photo["path"] is None or _is_abs_path(photo["path"]))
                    or not isinstance(photo["sha256"], str)
                    or not SHA256_RE.fullmatch(photo["sha256"])):
                raise LocationError("photos: item %d must be an object with exactly the keys path "
                                    "(absolute or null) and sha256 (64 lowercase hex), got %r"
                                    % (k, photo))
    if not _is_int(data["seed"]) or data["seed"] < 0:
        raise LocationError("seed: must be an int >= 0, got %r" % (data["seed"],))
    if data["status"] not in STATUSES:
        raise LocationError("status: must be one of %s, got %r"
                            % (", ".join(STATUSES), data["status"]))
    if not isinstance(data["created_at"], str) or not UTC_RE.fullmatch(data["created_at"]):
        raise LocationError("created_at: must be a UTC timestamp YYYY-MM-DDTHH:MM:SSZ, got %r"
                            % (data["created_at"],))
    trained_at = data["trained_at"]
    if trained_at is not None and (not isinstance(trained_at, str)
                                   or not UTC_RE.fullmatch(trained_at)):
        raise LocationError("trained_at: must be null or a UTC timestamp YYYY-MM-DDTHH:MM:SSZ, "
                            "got %r" % (trained_at,))
    dataset = data["dataset"]
    if dataset is not None:
        if not isinstance(dataset, dict) or set(dataset) != _DATASET_KEYS:
            raise LocationError("dataset: must be null or an object with exactly the keys %s, "
                                "got %r" % (", ".join(sorted(_DATASET_KEYS)), dataset))
        if (not _is_int(dataset["kept"]) or not _is_int(dataset["total"])
                or not 0 <= dataset["kept"] <= dataset["total"]):
            raise LocationError("dataset: kept and total must be ints with 0 <= kept <= total, "
                                "got kept=%r total=%r" % (dataset["kept"], dataset["total"]))
        if not _is_int(dataset["min_score"]) or not 1 <= dataset["min_score"] <= 10:
            raise LocationError("dataset: min_score must be an int from 1 to 10, got %r"
                                % (dataset["min_score"],))
        if not _is_abs_path(dataset["contact_sheet"]):
            raise LocationError("dataset: contact_sheet must be an absolute path, got %r"
                                % (dataset["contact_sheet"],))
    loras = data["loras"]
    if not isinstance(loras, dict) or set(loras) != {"video", "stills"}:
        raise LocationError("loras: must be an object with exactly the keys stills, video, got %r"
                            % (loras,))
    for kind in ("video", "stills"):
        if loras[kind] is not None:
            _validate_lora_entry("loras.%s" % kind, loras[kind])
    reason = data["stills_skip_reason"]
    if reason is not None and (not isinstance(reason, str) or not reason):
        raise LocationError("stills_skip_reason: must be null or a non-empty string, got %r"
                            % (reason,))
    strength = data["strength"]
    if strength is not None and (not _is_number(strength) or not 0 < strength <= 1.0):
        raise LocationError("strength: must be null or a number in (0, 1], got %r" % (strength,))
    trained = data["status"] == "trained"
    if trained != (loras["video"] is not None):
        raise LocationError('status: %r is inconsistent with loras.video (%s); status is '
                            '"trained" exactly when a video LoRA is recorded'
                            % (data["status"], "null" if loras["video"] is None else "set"))
    if trained != (trained_at is not None):
        raise LocationError('trained_at: %r is inconsistent with status %r; trained_at is set '
                            'exactly when status is "trained"' % (trained_at, data["status"]))
    if data["status"] in ("untrained", "trained") and (dataset is None
                                                        or dataset["kept"] < MIN_KEEP):
        raise LocationError("status: %r requires a dataset with at least %d kept stills"
                            % (data["status"], MIN_KEEP))


def load_location(name):
    validate_name(name)
    path = location_json_path(name)
    if not os.path.isfile(path):
        raise LocationError("unknown location: %s (no %s)" % (name, path))
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        validate_location(data, name=name)
    except (ValueError, LocationError) as e:
        raise LocationError("invalid location.json for %s: %s" % (name, e))
    return data


def write_location(data):
    """Validate, then atomically replace <lib>/<name>/location.json. The directory must already
    exist."""
    validate_location(data)
    path = location_json_path(data["name"])
    temporary = "%s.%s.tmp" % (path, uuid.uuid4().hex)
    try:
        with open(temporary, "x", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def list_names():
    lib = library_dir()
    if not os.path.isdir(lib):
        return []
    return sorted(n for n in os.listdir(lib)
                  if NAME_RE.fullmatch(n) and os.path.isfile(location_json_path(n)))


def registered_triggers():
    """{trigger: location name}: the .triggers registry, then every readable location.json
    trigger. Registry entries win on conflict; triggers are never reused (spec 2.4)."""
    triggers = {}
    registry = os.path.join(library_dir(), TRIGGER_REGISTRY)
    if os.path.isfile(registry):
        with open(registry, encoding="utf-8") as f:
            for line in f:
                fields = line.split()
                if len(fields) == 2:
                    triggers.setdefault(fields[0], fields[1])
    for name in list_names():
        try:
            with open(location_json_path(name), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        trigger = data.get("trigger") if isinstance(data, dict) else None
        if isinstance(trigger, str):
            triggers.setdefault(trigger, name)
    return triggers


def register_trigger(trigger, name):
    lib = library_dir()
    os.makedirs(lib, exist_ok=True)
    with open(os.path.join(lib, TRIGGER_REGISTRY), "a", encoding="utf-8") as f:
        f.write("%s %s\n" % (trigger, name))


def all_triggers():
    """{trigger: owner}: every location trigger (owner "location NAME"), then every character
    trigger (owner "character NAME", character_lib.registered_triggers()). A location trigger
    wins on conflict (spec 2.4)."""
    owners = dict((t, "location %s" % n) for t, n in registered_triggers().items())
    for trigger, name in _character_lib().registered_triggers().items():
        owners.setdefault(trigger, "character %s" % name)
    return owners


def auto_trigger(name, description, taken):
    """The rare-token trigger of spec 2.4: character_lib.auto_trigger with the class noun
    "place", avoiding the description's words."""
    return _character_lib().auto_trigger(name, TRIGGER_CLASS_NOUN, taken,
                                         avoid=description_words(description))


def model_compatible(base_model, model):
    """True when a video LoRA trained for base_model may attach to bin/ltx-movie --model model
    (spec 3.8): the same id, or the recorded HF base and its local ltx-2-mlx copy."""
    if model == base_model:
        return True
    if base_model != VIDEO_BASE_MODEL:
        return False
    local = os.path.join(os.path.expanduser(os.environ.get("LTX2_MLX_DIR", "~/ltx-2-mlx")),
                         "models", "ltx-2.3-mlx-q8")
    return os.path.realpath(os.path.expanduser(model)) == os.path.realpath(local)


def _readable_nonempty(path):
    return os.path.isfile(path) and os.access(path, os.R_OK) and os.path.getsize(path) > 0


def _pin(name):
    try:
        data = load_location(name)
    except LocationError as e:
        raise UnusableLocationError(str(e))
    if data["status"] != "trained":
        raise UnusableLocationError("location %s is not trained (status %s); run bin/location "
                                    "train %s" % (name, data["status"], name))
    video = data["loras"]["video"]
    if not _readable_nonempty(video["path"]):
        raise UnusableLocationError("location %s's video LoRA is missing or empty: %s"
                                    % (name, video["path"]))
    stills = data["loras"]["stills"]["path"] if data["loras"]["stills"] else None
    if stills is not None and not _readable_nonempty(stills):
        raise LocationError("location %s's stills LoRA is missing or empty: %s" % (name, stills))
    return LocationPin(name, data["trigger"], data["description"], video["path"], stills,
                       data["stills_skip_reason"], data["strength"], video["base_model"], True)


def resolve_locations(names):
    """[LocationPin] for --location NAME ... in order, every one with attach_video=True (spec
    3.9). Raises LocationError (UnusableLocationError for a location that cannot render)."""
    names = list(names)
    if len(names) > MAX_LOCATIONS:
        raise LocationError("at most 3 locations, got %d" % len(names))
    for name in names:
        if names.count(name) > 1:
            raise LocationError("location %s is pinned more than once" % name)
    pins = [_pin(name) for name in names]
    by_trigger = {}
    for pin in pins:
        if pin.trigger in by_trigger:
            raise LocationError("locations %s and %s share the trigger %s"
                                % (by_trigger[pin.trigger], pin.name, pin.trigger))
        by_trigger[pin.trigger] = pin.name
    return pins


def usable_locations():
    """Sorted names of the library locations that resolve_locations accepts on their own."""
    usable = []
    for name in list_names():
        try:
            resolve_locations([name])
        except LocationError:
            continue
        usable.append(name)
    return usable


def format_available_line(names):
    """One line naming the usable locations; names is usable_locations()'s list."""
    if not names:
        return NO_LOCATIONS_AVAILABLE
    return "available locations: " + ", ".join(names)


def location_table_lines():
    """The library table printed by bin/location list (spec 2.2)."""
    names = list_names()
    if not names:
        return ["no locations in %s" % library_dir()]
    lines = [LIST_ROW_FORMAT % ("NAME", "TRIGGER", "STATUS", "SOURCE", "VIDEO", "STILLS",
                                "DESCRIPTION")]
    for name in names:
        try:
            data = load_location(name)
        except LocationError as e:
            lines.append("%-16s (invalid: %s)" % (name, e))
            continue
        lines.append(LIST_ROW_FORMAT % (
            name, data["trigger"], data["status"], data["source"],
            "yes" if data["loras"]["video"] else "no",
            "yes" if data["loras"]["stills"] else "no", data["description"]))
    return lines


def _read_plan(story_dir):
    """(plan, None) for a usable plan.json of story_dir, (None, reason) for an unusable one, or
    (None, None) when there is no plan.json. Usable: a JSON object of PLAN_SCHEMA whose
    locations are a list of objects."""
    path = os.path.join(story_dir, "plan.json")
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, ValueError):
        plan = None
    if not isinstance(plan, dict):
        return None, "it is unreadable or not a JSON object"
    if plan.get("schema") != PLAN_SCHEMA:
        return None, "its schema is not ltx-movie.plan.v1"
    if (not isinstance(plan.get("locations"), list)
            or not all(isinstance(e, dict) for e in plan["locations"])):
        return None, "its locations are not a list of objects"
    return plan, None


def plan_location_names(story_dir):
    """The set of library location names story_dir's plan.json pins (its location entries'
    non-empty "location_name" strings), or None when there is no usable plan.json (spec 4.2)."""
    plan, _reason = _read_plan(story_dir)
    if plan is None:
        return None
    return set(e["location_name"] for e in plan["locations"]
               if isinstance(e.get("location_name"), str) and e["location_name"])


def plan_panel_locations(story_dir, n_panels, names):
    """([library location name or None for each of n_panels panels], note or None) from
    story_dir's plan.json (spec 4.7): panel k carries the name of beat k's location when that
    location entry's location_name is in names. Without a usable plan every panel is None and
    the note says why."""
    empty = [None] * n_panels
    plan, reason = _read_plan(story_dir)
    if plan is None and reason is None:
        return empty, NO_PLAN_NOTE
    if plan is not None:
        beats = plan.get("beats") if isinstance(plan.get("beats"), list) else []
        if len(beats) != n_panels:
            reason = "it has %d beats for %d panels" % (len(beats), n_panels)
        else:
            for k, beat in enumerate(beats, start=1):
                if (not isinstance(beat, dict) or not isinstance(beat.get("location"), str)
                        or not beat["location"]):
                    reason = "beat %d has no location id" % k
                    break
    if reason is not None:
        return empty, UNUSABLE_PLAN_NOTE % reason
    by_id = {}
    for entry in plan["locations"]:
        if isinstance(entry.get("id"), str):
            by_id.setdefault(entry["id"], entry.get("location_name"))
    out = []
    for beat in plan["beats"]:
        name = by_id.get(beat["location"])
        out.append(name if name in names else None)
    return out, None


def prefix_location_trigger(prompt, trigger):
    """prompt with "<trigger>. " in front unless the trigger already occurs in it as a whole
    word, in any case (spec 4.7; the rule of character_lib.prefix_character_triggers)."""
    if re.search(r"(?<![\w-])" + re.escape(trigger) + r"(?![\w-])", prompt, re.IGNORECASE):
        return prompt
    return trigger + ". " + prompt
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_lib.py tests/test_location_story.py tests/test_location_golden.py 2>&1 | tail -1
```

Expected: `15 passed`. Run the compile check with `FILES` = `location_lib.py tests/location_testutil.py tests/test_location_lib.py tests/story_engine_testutil.py`; expected: `compiled 4` twice. Then run the gate block with `N=2`. Expected: `GATE PASS`, `new-file tests 15, not passing 0`, `baseline failures still failing 2 of 2` and `OK 347/347`, with no `LOST` line.

- [ ] **Step 5: Commit.**

```bash
git add location_lib.py tests/location_testutil.py tests/test_location_lib.py tests/story_engine_testutil.py
git diff --cached --name-only    # expected: those 4 paths
git commit -m "feat(location): location_lib, the location.json schema, triggers, resolution and the plan reader (L1.1, L1.3, L1.4, L2.6-L2.9, L3.2, L3.7; LL2-LL14)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `character_dataset.py`: the training cores and the edit child (L2.10, L1.8; LG1-LG3, LD18)

This task implements:
- L2.10: `train_video_lora(owner_dir, videos_dir, captions_dir, prompt, failed_note, recorded, tested)` and `train_stills_lora(owner_dir, pairs, prompt, seed, kept_ok, skipped)` hold the bodies of `train_video` and `train_stills`. The old functions become wrappers with unchanged signatures. The cores call the module globals (`run_logged`, `run_zimage_child`, `step_log_path`, `SKILL.generate_video`, `_sha256`, the constants), so every existing monkeypatch keeps working.
  - `_video_failed(failed_note, step, rc, log)` prints `"Error: video LoRA training failed at %s (exit %s); log: %s; %s"`, which for a character is the old text.
  - The character wrappers build the entries in the old key order (`path, sha256, base_model, rank, alpha, steps, trained_at, sample_path, control_path`), so `character.json` is byte-identical.
  - `train_stills` reads `manifest.json` before `train/stills` is recreated: the spec's one reorder.
- L1.8: `child_qwenedit` edits each job's `job.get("image", spec["image"])`, opening each distinct path once, and screens with `spec.get("skill", "character_edit")`.

Tests: LG2 and LG3 are appended to `tests/test_location_golden.py`; LD18 starts the new `tests/test_location_dataset.py` (Task 4 adds `location_dataset` to its header). LG1 and LG3 pass before and after this task; LG2 and LD18 fail before it. This is the first edit to a `PIPELINE_FILES` entry, so `test_mut26` fails from here until Task 14 (code G15).

**Files:**
- Modify: `character_dataset.py`: `_video_failed` and `train_video` (`:1407-1482` and `:1486-1488`), `train_stills` (`:1641-1660`, `:1667-1673`, `:1680`, `:1691-1697`, `:1711-1741`), `child_qwenedit` (`:1799-1800`, `:1814-1820`, `:1825`).
- Modify: `tests/test_location_golden.py` (Task 1's file: the imports and before `main`).
- Create: `tests/test_location_dataset.py`.

**Interfaces:**
- Consumes (existing): the Task 1 `golden_record()` and `FIXTURE`; `character_dataset.main(["qwenedit", "--spec", path]) -> int`; `character_lib.character_dir`, `character_lib.write_character`, `character_lib.utc_now`.
- Produces, in `character_dataset`:
  - `train_video_lora(owner_dir, videos_dir, captions_dir, prompt, failed_note, recorded, tested) -> "ok" | "failed" | "test_failed"`; `recorded(entry)` once with `{"path", "sha256", "rank", "alpha", "steps"}` after `<owner_dir>/lora/video.safetensors` is copied; `tested(key, path)` after each successful test clip, `key` in `("sample_path", "control_path")`.
  - `train_stills_lora(owner_dir, pairs, prompt, seed, kept_ok, skipped) -> "ok" | "skipped" | "failed"`; `pairs` is `[(png path, txt path)]`; `kept_ok(entry, sample_path, control_path)` with the same five keys; `skipped(reason)` with the full `"mflux adapter incompatible with z_image_skill: ..."` text.
  - `train_video(data)`, `train_stills(data)`: unchanged signatures and behaviour.
  - `child_qwenedit(spec_path)`: a job may carry `"image"`; a spec may carry `"skill"`.
- Produces, in `tests/test_location_dataset.py`: the header (`WS`, `character_dataset`, `seu`, the autouse `env` fixture) and `_fake_edit_stack(monkeypatch, calls)`.

- [ ] **Step 1: Write the failing tests.**

**1.1.** Edit `tests/test_location_golden.py`: replace this text, which occurs exactly once:

```python
def main(argv):
    if argv != ["--write-fixture"]:
```

with:

```python
def test_lg2_the_training_cores_and_their_wrappers():
    import inspect
    assert list(inspect.signature(character_dataset.train_video_lora).parameters) == [
        "owner_dir", "videos_dir", "captions_dir", "prompt", "failed_note", "recorded", "tested"]
    assert list(inspect.signature(character_dataset.train_stills_lora).parameters) == [
        "owner_dir", "pairs", "prompt", "seed", "kept_ok", "skipped"]
    assert list(inspect.signature(character_dataset.train_video).parameters) == ["data"]
    assert list(inspect.signature(character_dataset.train_stills).parameters) == ["data"]


def test_lg3_the_character_tests_pass_unedited(tmp_path):
    proc = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "-rf", "tests/test_character_dataset.py", "tests/test_character_tool.py"],
                          cwd=WS, capture_output=True, text=True, timeout=1800,
                          env=dict(os.environ))
    failed = sorted(line.split()[1] for line in proc.stdout.splitlines()
                    if line.startswith("FAILED "))
    assert failed in ([], ["tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike"]), (
        proc.stdout[-3000:])
    assert " passed" in proc.stdout.splitlines()[-1], proc.stdout[-3000:]


def main(argv):
    if argv != ["--write-fixture"]:
```

**1.2.** Edit `tests/test_location_golden.py`: replace this text, which occurs exactly once:

```python
import shutil
import struct
import sys
```

with:

```python
import shutil
import struct
import subprocess
import sys
```

**1.3.** Create `tests/test_location_dataset.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""Tests for the location library's dataset builder and trainer (docs/superpowers/specs/
2026-10-29-location-lora-design.md, Sections 2.5-2.12 and 3.2-3.4, test table 6.5: LD1-LD24, with
the plan's Review Focus pins): location_dataset.py, and the qwenedit child extension in
character_dataset.py (LD18).

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_location_dataset.py
Stdlib plus pytest and PIL. No test reads the real HOME, renders, trains, runs Z-Image or the
editor, contacts a model server or touches port 8178: vlm_call, vlm_ready, story_server,
restore_story_server, wait_for_avail, wait_for_vlm, story_server_state, busy_process, free_gib,
edit_models_missing, run_logged, run_zimage_child, run_edit_child, SKILL.generate_video and
psutil.virtual_memory are fakes (the patterns of tests/test_character_dataset.py:579-641 and
:968-998), and every library lives under tmp_path (HOME, CHARACTER_LIBRARY_DIR,
LOCATION_LIBRARY_DIR and LORA_CATALOG_DIR). Real ffmpeg/ffprobe wrap the kept stills, as the
character tests do.
"""

import argparse
import json
import os
import sys
import types

import pytest
from PIL import Image

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import character_dataset  # noqa: E402
import story_engine_testutil as seu  # noqa: E402


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


# --- LD18: the qwenedit child takes a per-job image and a spec skill (L1.8) -----------------

def _fake_edit_stack(monkeypatch, calls):
    """Fake torch, diffusers, huggingface_hub and content_safety for child_qwenedit (as
    tests/test_character_dataset.py's test_d44_child_qwenedit); records pipe calls, the screen's
    skill and every Image.open path."""

    class _Blocked(Exception):
        pass

    class _Generator(object):
        def __init__(self, device):
            pass

        def manual_seed(self, seed):
            self.seed = seed
            return self

    class _Pipe(object):
        def to(self, device):
            return self

        def load_lora_weights(self, path):
            calls["lora"] = path

        def set_progress_bar_config(self, **kwargs):
            pass

        def __call__(self, **kwargs):
            calls["pipe"].append(kwargs)
            return types.SimpleNamespace(images=[Image.new("RGB", (kwargs["width"],
                                                                  kwargs["height"]), (0, 255, 0))])

    def _assert_safe(image, skill, prompt):
        calls["skills"].append(skill)

    fake_torch = types.ModuleType("torch")
    fake_torch.Generator = _Generator
    fake_torch.bfloat16 = "bf16"
    fake_torch.backends = types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: True))
    fake_diffusers = types.ModuleType("diffusers")
    fake_diffusers.QwenImageEditPlusPipeline = types.SimpleNamespace(
        from_pretrained=lambda model, **kwargs: _Pipe())
    fake_hub = types.ModuleType("huggingface_hub")
    fake_hub.hf_hub_download = lambda repo, name, local_files_only: "/cache/%s/%s" % (repo, name)
    fake_safety = types.ModuleType("content_safety")
    fake_safety.ContentSafetyError = _Blocked
    fake_safety.assert_image_safe = _assert_safe
    for name, module in (("torch", fake_torch), ("diffusers", fake_diffusers),
                         ("huggingface_hub", fake_hub), ("content_safety", fake_safety)):
        monkeypatch.setitem(sys.modules, name, module)
    real_open = Image.open

    def _open(path, *args, **kwargs):
        calls["opened"].append(path)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(character_dataset.Image, "open", _open)


def test_ld18_the_qwenedit_child_takes_a_per_job_image_and_skill(tmp_path, monkeypatch):
    a, b = str(tmp_path / "a.png"), str(tmp_path / "b.png")
    Image.new("RGB", (300, 200), (10, 20, 30)).save(a)
    Image.new("RGB", (200, 300), (40, 50, 60)).save(b)

    def _spec(name, jobs, **extra):
        spec = dict({"image": a, "model": "M", "lora_repo": "R", "lora_file": "F.safetensors",
                     "steps": 8, "true_cfg": 1.0,
                     "report_path": str(tmp_path / ("%s.report.json" % name)), "jobs": jobs},
                    **extra)
        path = str(tmp_path / ("%s.spec.json" % name))
        with open(path, "w") as f:
            json.dump(spec, f)
        return path

    def _job(k, image=None):
        job = {"prompt": "edit %d" % k, "output_path": str(tmp_path / ("out_%d.png" % k)),
               "seed": 5, "width": 64, "height": 40}
        if image is not None:
            job["image"] = image
        return job

    calls = {"pipe": [], "skills": [], "opened": [], "lora": None}
    _fake_edit_stack(monkeypatch, calls)
    path = _spec("loc", [_job(1, a), _job(2, b), _job(3, a), _job(4, b)], skill="location_edit")
    assert character_dataset.main(["qwenedit", "--spec", path]) == 0
    assert calls["opened"] == [a, b]
    assert [c["image"][0].size for c in calls["pipe"]] == [(300, 200), (200, 300), (300, 200),
                                                         (200, 300)]
    assert calls["skills"] == ["location_edit"] * 4
    with open(str(tmp_path / "loc.report.json")) as f:
        assert [j["status"] for j in json.load(f)["jobs"]] == ["ok"] * 4
    # A character-shaped spec (no per-job image, no skill) behaves exactly as before.
    calls.update(pipe=[], skills=[], opened=[])
    path = _spec("char", [_job(5), _job(6)])
    assert character_dataset.main(["qwenedit", "--spec", path]) == 0
    assert calls["opened"] == [a]
    assert [c["image"][0].size for c in calls["pipe"]] == [(300, 200), (300, 200)]
    assert calls["skills"] == ["character_edit"] * 2
    assert [(c["prompt"], c["num_inference_steps"], c["true_cfg_scale"], c["generator"].seed)
            for c in calls["pipe"]] == [("edit 5", 8, 1.0, 5), ("edit 6", 8, 1.0, 5)]
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_golden.py tests/test_location_dataset.py 2>&1 | tail -1
```

Expected: `2 failed, 2 passed` (LG2: `train_video_lora` does not exist; LD18: the per-job image is ignored; LG1 and LG3 pass). LG3 runs the character suites in a subprocess and takes about 45 seconds.

- [ ] **Step 3: Implement.**

**3.1.** Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
def _video_failed(data, step, rc, log):
    print("Error: video LoRA training failed at %s (exit %s); log: %s; character %s stays %s"
          % (step, rc, log, data["name"], data["status"]), file=sys.stderr)
    return "failed"


def train_video(data):
    """Preprocess, train, record and A/B-test the video LoRA (spec 4.8). Returns "ok",
    "failed" (nothing recorded) or "test_failed" (the LoRA is recorded; a test render
    failed)."""
    name = data["name"]
    char_dir = character_lib.character_dir(name)
    vdir = os.path.join(char_dir, "train", "video")
    if os.path.exists(vdir):
        shutil.rmtree(vdir)
    os.makedirs(vdir)
    for sub in ("lora", "tests", "logs"):
        os.makedirs(os.path.join(char_dir, sub), exist_ok=True)
    prompt = trigger_test_prompt(data["trigger"], data["class_noun"])
    config_path = os.path.join(vdir, "train.yaml")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(video_train_config(os.path.join(vdir, "preprocessed"), prompt,
                                   os.path.join(vdir, "out")))
    env = dict(os.environ, HF_HOME=SKILL.LTX2_MLX_HF_HOME)
    videos = os.path.join(char_dir, "dataset", "videos")

    log = step_log_path(char_dir, "preprocess")
    rc = run_logged(preprocess_argv(videos, os.path.join(char_dir, "dataset", "captions"),
                                    os.path.join(vdir, "preprocessed")),
                    log, SKILL.LTX2_MLX_DIR, env, PREPROCESS_TIMEOUT_S)
    if rc != 0:
        return _video_failed(data, "preprocess", rc, log)
    latents = os.path.join(vdir, "preprocessed", ".precomputed", "latents")
    n_lat = len(os.listdir(latents)) if os.path.isdir(latents) else 0
    n_vid = len(glob.glob(os.path.join(videos, "*.mp4")))
    if n_lat != n_vid:
        print("Error: preprocess wrote %d latents for %d videos; log: %s" % (n_lat, n_vid, log),
              file=sys.stderr)
        return "failed"

    log = step_log_path(char_dir, "train")
    rc = run_logged(train_argv(config_path), log, SKILL.LTX2_MLX_DIR, env, VIDEO_TRAIN_TIMEOUT_S)
    final = os.path.join(vdir, "out", "checkpoints", VIDEO_FINAL_CKPT)
    if rc != 0 or not os.path.isfile(final) or os.path.getsize(final) == 0:
        return _video_failed(data, "train", rc, log)

    lora_path = os.path.join(char_dir, "lora", "video.safetensors")
    shutil.copy2(final, lora_path + ".tmp")
    os.replace(lora_path + ".tmp", lora_path)
    data["loras"]["video"] = {"path": lora_path, "sha256": _sha256(lora_path),
                              "base_model": TRAIN_MODEL_DIR, "rank": VIDEO_RANK,
                              "alpha": VIDEO_RANK, "steps": VIDEO_STEPS,
                              "trained_at": character_lib.utc_now(),
                              "sample_path": None, "control_path": None}
    data["status"] = "trained"
    character_lib.write_character(data)

    test_failed = False
    for key, filename, step, extra in (
            ("sample_path", "video_lora.mp4", "test-video-lora", {"loras": [(lora_path, 1.0)]}),
            ("control_path", "video_control.mp4", "test-video-control", {})):
        out = os.path.join(char_dir, "tests", filename)
        try:
            SKILL.generate_video(prompt, out, image_path=None, width=512, height=320,
                                 num_frames=25, frame_rate=24, seed=TEST_SEED,
                                 model=TEST_MODEL_DIR, gemma=SKILL.GEMMA_MODEL_ID, low_ram=True,
                                 log_path=step_log_path(char_dir, step),
                                 timeout_s=TEST_RENDER_TIMEOUT_S, force=True, **extra)
        except (ValueError, SKILL.Ltx2MlxError) as e:
            print("Error: video test render failed: %s" % e, file=sys.stderr)
            test_failed = True
            continue
        data["loras"]["video"][key] = out
        character_lib.write_character(data)

    entry = data["loras"]["video"]
```

with:

```python
def _video_failed(failed_note, step, rc, log):
    print("Error: video LoRA training failed at %s (exit %s); log: %s; %s"
          % (step, rc, log, failed_note), file=sys.stderr)
    return "failed"


def train_video_lora(owner_dir, videos_dir, captions_dir, prompt, failed_note, recorded, tested):
    """Preprocess, train, copy and A/B-test a video LoRA (character library spec 4.8; location
    library spec L2.10). Returns "ok", "failed" or "test_failed". recorded(entry) is called once,
    after the final checkpoint is copied to <owner_dir>/lora/video.safetensors, with
    {"path", "sha256", "rank", "alpha", "steps"}; tested(key, path) after each successful test
    clip ("sample_path" then "control_path"). failed_note ends the failure line."""
    vdir = os.path.join(owner_dir, "train", "video")
    if os.path.exists(vdir):
        shutil.rmtree(vdir)
    os.makedirs(vdir)
    for sub in ("lora", "tests", "logs"):
        os.makedirs(os.path.join(owner_dir, sub), exist_ok=True)
    config_path = os.path.join(vdir, "train.yaml")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(video_train_config(os.path.join(vdir, "preprocessed"), prompt,
                                   os.path.join(vdir, "out")))
    env = dict(os.environ, HF_HOME=SKILL.LTX2_MLX_HF_HOME)

    log = step_log_path(owner_dir, "preprocess")
    rc = run_logged(preprocess_argv(videos_dir, captions_dir, os.path.join(vdir, "preprocessed")),
                    log, SKILL.LTX2_MLX_DIR, env, PREPROCESS_TIMEOUT_S)
    if rc != 0:
        return _video_failed(failed_note, "preprocess", rc, log)
    latents = os.path.join(vdir, "preprocessed", ".precomputed", "latents")
    n_lat = len(os.listdir(latents)) if os.path.isdir(latents) else 0
    n_vid = len(glob.glob(os.path.join(videos_dir, "*.mp4")))
    if n_lat != n_vid:
        print("Error: preprocess wrote %d latents for %d videos; log: %s" % (n_lat, n_vid, log),
              file=sys.stderr)
        return "failed"

    log = step_log_path(owner_dir, "train")
    rc = run_logged(train_argv(config_path), log, SKILL.LTX2_MLX_DIR, env, VIDEO_TRAIN_TIMEOUT_S)
    final = os.path.join(vdir, "out", "checkpoints", VIDEO_FINAL_CKPT)
    if rc != 0 or not os.path.isfile(final) or os.path.getsize(final) == 0:
        return _video_failed(failed_note, "train", rc, log)

    lora_path = os.path.join(owner_dir, "lora", "video.safetensors")
    shutil.copy2(final, lora_path + ".tmp")
    os.replace(lora_path + ".tmp", lora_path)
    recorded({"path": lora_path, "sha256": _sha256(lora_path), "rank": VIDEO_RANK,
              "alpha": VIDEO_RANK, "steps": VIDEO_STEPS})

    test_failed = False
    for key, filename, step, extra in (
            ("sample_path", "video_lora.mp4", "test-video-lora", {"loras": [(lora_path, 1.0)]}),
            ("control_path", "video_control.mp4", "test-video-control", {})):
        out = os.path.join(owner_dir, "tests", filename)
        try:
            SKILL.generate_video(prompt, out, image_path=None, width=512, height=320,
                                 num_frames=25, frame_rate=24, seed=TEST_SEED,
                                 model=TEST_MODEL_DIR, gemma=SKILL.GEMMA_MODEL_ID, low_ram=True,
                                 log_path=step_log_path(owner_dir, step),
                                 timeout_s=TEST_RENDER_TIMEOUT_S, force=True, **extra)
        except (ValueError, SKILL.Ltx2MlxError) as e:
            print("Error: video test render failed: %s" % e, file=sys.stderr)
            test_failed = True
            continue
        tested(key, out)
    return "test_failed" if test_failed else "ok"


def train_video(data):
    """Preprocess, train, record and A/B-test the video LoRA (spec 4.8). Returns "ok",
    "failed" (nothing recorded) or "test_failed" (the LoRA is recorded; a test render
    failed). The work is train_video_lora's (location library spec L2.10)."""
    name = data["name"]
    char_dir = character_lib.character_dir(name)

    def recorded(entry):
        data["loras"]["video"] = {"path": entry["path"], "sha256": entry["sha256"],
                                  "base_model": TRAIN_MODEL_DIR, "rank": entry["rank"],
                                  "alpha": entry["alpha"], "steps": entry["steps"],
                                  "trained_at": character_lib.utc_now(),
                                  "sample_path": None, "control_path": None}
        data["status"] = "trained"
        character_lib.write_character(data)

    def tested(key, path):
        data["loras"]["video"][key] = path
        character_lib.write_character(data)

    outcome = train_video_lora(char_dir, os.path.join(char_dir, "dataset", "videos"),
                               os.path.join(char_dir, "dataset", "captions"),
                               trigger_test_prompt(data["trigger"], data["class_noun"]),
                               "character %s stays %s" % (name, data["status"]), recorded, tested)
    if outcome == "failed":
        return outcome
    lora_path = data["loras"]["video"]["path"]
    entry = data["loras"]["video"]
```

**3.2.** Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
    print("  with LoRA: %s" % entry["sample_path"])
    print("  control:   %s" % entry["control_path"])
    return "test_failed" if test_failed else "ok"
```

with:

```python
    print("  with LoRA: %s" % entry["sample_path"])
    print("  control:   %s" % entry["control_path"])
    return outcome
```

**3.3.** Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
def train_stills(data):
    """Train the stills LoRA with mflux and keep it only if it passes the compat gate (spec
    4.9). Returns "ok", "skipped" (incompatible; the reason is recorded) or "failed"."""
    name = data["name"]
    char_dir = character_lib.character_dir(name)
    sdir = os.path.join(char_dir, "train", "stills")
    if os.path.exists(sdir):
        shutil.rmtree(sdir)
    os.makedirs(os.path.join(sdir, "data"))
    out = os.path.join(sdir, "out")
    for sub in ("lora", "tests", "logs"):
        os.makedirs(os.path.join(char_dir, sub), exist_ok=True)
    with open(os.path.join(char_dir, "dataset", "manifest.json"), encoding="utf-8") as f:
        kept_ns = [item["n"] for item in json.load(f)["items"] if item["kept"]]
    for n in kept_ns:
        for sub, ext in (("stills", "png"), ("captions", "txt")):
            shutil.copy2(os.path.join(char_dir, "dataset", sub, "char_%02d.%s" % (n, ext)),
                         os.path.join(sdir, "data", "char_%02d.%s" % (n, ext)))
    prompt = trigger_test_prompt(data["trigger"], data["class_noun"])
    with open(os.path.join(sdir, "data", "preview_1.txt"), "w", encoding="utf-8") as f:
```

with:

```python
def train_stills_lora(owner_dir, pairs, prompt, seed, kept_ok, skipped):
    """Train a stills LoRA with mflux on pairs [(png, txt)] and keep it only if it passes the
    compat gate (character library spec 4.9; location library spec L2.10). Returns "ok",
    "skipped" or "failed". kept_ok(entry, sample_path, control_path) with {"path", "sha256",
    "rank", "alpha", "steps"}; skipped(reason) with the full stills_skip_reason."""
    sdir = os.path.join(owner_dir, "train", "stills")
    if os.path.exists(sdir):
        shutil.rmtree(sdir)
    os.makedirs(os.path.join(sdir, "data"))
    out = os.path.join(sdir, "out")
    for sub in ("lora", "tests", "logs"):
        os.makedirs(os.path.join(owner_dir, sub), exist_ok=True)
    for png, txt in pairs:
        for src in (png, txt):
            shutil.copy2(src, os.path.join(sdir, "data", os.path.basename(src)))
    with open(os.path.join(sdir, "data", "preview_1.txt"), "w", encoding="utf-8") as f:
```

**3.4.** Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
    config_path = os.path.join(sdir, "train.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(stills_train_config(os.path.join(sdir, "data"), out, data["seed"],
                                      len(kept_ns)), f, indent=2)
    _num_epochs, total_steps, _save = stills_epochs(len(kept_ns))

    log = step_log_path(char_dir, "train-stills")
```

with:

```python
    config_path = os.path.join(sdir, "train.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(stills_train_config(os.path.join(sdir, "data"), out, seed, len(pairs)), f,
                  indent=2)
    _num_epochs, total_steps, _save = stills_epochs(len(pairs))

    log = step_log_path(owner_dir, "train-stills")
```

**3.5.** Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
    candidate = os.path.join(char_dir, "lora", "stills.candidate.safetensors")
```

with:

```python
    candidate = os.path.join(owner_dir, "lora", "stills.candidate.safetensors")
```

**3.6.** Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
    sample = os.path.join(char_dir, "tests", "stills_lora.png")
    job = {"prompt": prompt, "output_path": sample, "seed": TEST_SEED, "width": 1024,
           "height": 640}
    report = child_error = None
    try:
        report = run_zimage_child({"jobs": [job], "loras": [[candidate, 1.0]]}, char_dir,
                                  "test-stills-lora")
```

with:

```python
    sample = os.path.join(owner_dir, "tests", "stills_lora.png")
    job = {"prompt": prompt, "output_path": sample, "seed": TEST_SEED, "width": 1024,
           "height": 640}
    report = child_error = None
    try:
        report = run_zimage_child({"jobs": [job], "loras": [[candidate, 1.0]]}, owner_dir,
                                  "test-stills-lora")
```

**3.7.** Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
    if reason is not None:
        os.replace(candidate, os.path.join(char_dir, "lora", "stills.rejected.safetensors"))
        data["stills_skip_reason"] = "mflux adapter incompatible with z_image_skill: " + reason
        character_lib.write_character(data)
        print("stills LoRA skipped: %s; the video LoRA is unaffected" % data["stills_skip_reason"])
        return "skipped"

    stills_path = os.path.join(char_dir, "lora", "stills.safetensors")
    os.replace(candidate, stills_path)
    control = os.path.join(char_dir, "tests", "stills_control.png")
    control_path = None
    try:
        control_report = run_zimage_child({"jobs": [dict(job, output_path=control)],
                                           "loras": None}, char_dir, "test-stills-control")
        if control_report["jobs"][0]["status"] == "ok":
            control_path = control
    except DatasetError as e:
        print("Error: stills control render failed: %s" % e, file=sys.stderr)
    data["loras"]["stills"] = {"path": stills_path, "sha256": _sha256(stills_path),
                               "base_model": "Tongyi-MAI/Z-Image-Turbo", "rank": STILLS_RANK,
                               "alpha": STILLS_RANK, "steps": total_steps,
                               "trained_at": character_lib.utc_now(),
                               "sample_path": (sample if report["jobs"][0]["status"] == "ok"
                                               else None),
                               "control_path": control_path}
    data["stills_skip_reason"] = None
    character_lib.write_character(data)
    print("stills LoRA: %s" % stills_path)
    print("  with LoRA: %s" % data["loras"]["stills"]["sample_path"])
    print("  control:   %s" % control_path)
    return "ok"
```

with:

```python
    if reason is not None:
        os.replace(candidate, os.path.join(owner_dir, "lora", "stills.rejected.safetensors"))
        full_reason = "mflux adapter incompatible with z_image_skill: " + reason
        skipped(full_reason)
        print("stills LoRA skipped: %s; the video LoRA is unaffected" % full_reason)
        return "skipped"

    stills_path = os.path.join(owner_dir, "lora", "stills.safetensors")
    os.replace(candidate, stills_path)
    control = os.path.join(owner_dir, "tests", "stills_control.png")
    control_path = None
    try:
        control_report = run_zimage_child({"jobs": [dict(job, output_path=control)],
                                           "loras": None}, owner_dir, "test-stills-control")
        if control_report["jobs"][0]["status"] == "ok":
            control_path = control
    except DatasetError as e:
        print("Error: stills control render failed: %s" % e, file=sys.stderr)
    sample_path = sample if report["jobs"][0]["status"] == "ok" else None
    kept_ok({"path": stills_path, "sha256": _sha256(stills_path), "rank": STILLS_RANK,
             "alpha": STILLS_RANK, "steps": total_steps}, sample_path, control_path)
    print("stills LoRA: %s" % stills_path)
    print("  with LoRA: %s" % sample_path)
    print("  control:   %s" % control_path)
    return "ok"


def train_stills(data):
    """Train the stills LoRA with mflux and keep it only if it passes the compat gate (spec
    4.9). Returns "ok", "skipped" (incompatible; the reason is recorded) or "failed". The work
    is train_stills_lora's (location library spec L2.10)."""
    name = data["name"]
    char_dir = character_lib.character_dir(name)
    with open(os.path.join(char_dir, "dataset", "manifest.json"), encoding="utf-8") as f:
        kept_ns = [item["n"] for item in json.load(f)["items"] if item["kept"]]
    pairs = [(os.path.join(char_dir, "dataset", "stills", "char_%02d.png" % n),
              os.path.join(char_dir, "dataset", "captions", "char_%02d.txt" % n))
             for n in kept_ns]

    def kept_ok(entry, sample_path, control_path):
        data["loras"]["stills"] = {"path": entry["path"], "sha256": entry["sha256"],
                                   "base_model": "Tongyi-MAI/Z-Image-Turbo",
                                   "rank": entry["rank"], "alpha": entry["alpha"],
                                   "steps": entry["steps"],
                                   "trained_at": character_lib.utc_now(),
                                   "sample_path": sample_path, "control_path": control_path}
        data["stills_skip_reason"] = None
        character_lib.write_character(data)

    def skipped(reason):
        data["stills_skip_reason"] = reason
        character_lib.write_character(data)

    return train_stills_lora(char_dir, pairs,
                             trigger_test_prompt(data["trigger"], data["class_noun"]),
                             data["seed"], kept_ok, skipped)
```

**3.8.** Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
    """The child side of run_edit_child: load the editor and its Lightning LoRA from the local
    cache, edit spec["image"] into every job, screen each result, write the report."""
```

with:

```python
    """The child side of run_edit_child: load the editor and its Lightning LoRA from the local
    cache, edit each job's image (job["image"], else spec["image"]; location library spec L1.8)
    into every job, screen each result with spec["skill"] (default "character_edit"), write the
    report."""
```

**3.9.** Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
    pipe.set_progress_bar_config(disable=True)
    with Image.open(spec["image"]) as img:
        source = img.convert("RGB")
    jobs = []
    for job in spec["jobs"]:
        started = time.monotonic()
        image = pipe(image=[source], prompt=job["prompt"], negative_prompt=" ",
```

with:

```python
    pipe.set_progress_bar_config(disable=True)
    sources = {}
    jobs = []
    for job in spec["jobs"]:
        path = job.get("image", spec["image"])
        if path not in sources:
            with Image.open(path) as img:
                sources[path] = img.convert("RGB")
        source = sources[path]
        started = time.monotonic()
        image = pipe(image=[source], prompt=job["prompt"], negative_prompt=" ",
```

**3.10.** Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
            content_safety.assert_image_safe(image, skill="character_edit", prompt=job["prompt"])
```

with:

```python
            content_safety.assert_image_safe(image, skill=spec.get("skill", "character_edit"),
                                             prompt=job["prompt"])
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_golden.py tests/test_location_dataset.py 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider tests/test_character_dataset.py tests/test_character_tool.py 2>&1 | tail -1
```

Expected: `4 passed`, then `1 failed, N passed` where the one failure is the baseline `test_d2_copied_literals_match_the_spike` and N is the baseline count of those two files. LG1 passing is LK4: the golden record is byte-identical after the refactor. Run the compile check with `FILES` = `character_dataset.py tests/test_location_golden.py tests/test_location_dataset.py`; expected: `compiled 3` twice. Then run the gate block with `N=3`. Expected: `GATE PASS`, `new-file tests 18, not passing 0`, `baseline failures still failing 2 of 2`, `OK 347/347`, and one `LOST ... test_mut26_pipeline_files_are_unchanged listed`.

- [ ] **Step 5: Commit.**

```bash
git add character_dataset.py tests/test_location_golden.py tests/test_location_dataset.py
git diff --cached --name-only    # expected: those 3 paths
git commit -m "refactor(character): train_video_lora and train_stills_lora cores behind unchanged wrappers; the qwenedit child takes a per-job image and a skill (L2.10, L1.8; LG1-LG3, LD18)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Location datasets: `location_dataset.py` create, regenerate, edit and `bin/location` (L1.2-L1.12, L5.1; LD1-LD17, LD24, LT1-LT8, Review Focus 1, 2)

This task implements:
- L1.5: `STYLE`, `TIMES`, `WEATHERS`, `TIME_PHRASES`, `WEATHER_PHRASES`, `VARIANTS` (the 24-row table) and `gen_prompt`.
- L1.6: photo loading (`_load_photos`: 1-24 photos, readable, the 768x480 centred 16:10 crop, no duplicate sha256), the oriented `photos/photo_NN.png` copies, the `ImageOps.fit` 1024x640 stills, `EDIT_PROMPT`/`EDIT_CONDITIONS` and the round-robin top-up.
- L1.7: `describe(paths)` with `DESCRIBE_PROMPT`, `DESCRIBE_SHORTEN` (text only, for a description over 40 words) and `DESCRIBE_RETRY`.
- L1.8: the edit spec (`"skill": "location_edit"`, a per-job `"image"`) and the `edit_models_missing` gate.
- L1.9: `CHECK_TEXT_PROMPT`, `CHECK_PHOTO_PROMPT`, `TAG_PROMPT`, `CHECK_RETRY`, `SCORE_RETRY_EXTRA`, the aliases, `validate_location_check`, `check_still`, the keep rules and `caption`.
- L1.10, L1.11: `manifest.json` and `write_contact_sheet` (5 columns of 256x160, a 20-px label row, a 24-px banner, red outlines, black missing cells).
- L1.12: `create`, `_regenerate` and `edit` in the spec's order, with `_with_story_server_stopped` (`character_dataset.py:980-1008`'s stop, wait and restore), every gate through `character_dataset`, and the exit codes 0, 1, 2 and 3.
- L1.2: `bin/location` with `create`, `edit`, `list` and `show`; the PIL/psutil re-exec with `LOCATION_REEXEC`; the signal path in `run()` (Plan ruling LR6). Task 5 adds `train`.
- L5.1: every create, regenerate and edit row of the error table.

The rulings this task carries:
- LR5: an interrupt inside the dataset build prints the abort line and exits 1, as `bin/character` does; an interrupt elsewhere exits 130 with `location: interrupted`.
- LR7 (Review Focus 1): a new description that contains the trigger is refused before the lock.
- LR8: the trigger owner is named as `location NAME` or `character NAME`.
- LR9: the regenerate refusal text for `--photo`/`--trigger`.
- LR10: a regenerate prints the seed line, as `bin/character` does.
- LR14: LT2 runs under `-I` with a meta-path blocker.

**Files:**
- Create: `location_dataset.py`, `bin/location` (mode 755; the Write tool, then `chmod 755 bin/location` in Step 3).
- Modify: `tests/test_location_dataset.py` (Task 3's file: the imports, the `ld`/`ll` loaders after them, and the end of the file).
- Create: `tests/test_location_tool.py`.
- Read only: `character_dataset.py` (`STYLE` `:64`, `SHOTS` `:65-72`, `extract_json` `:230-247`, `image_data_url` `:354-361`, `vlm_call` `:364-389`, `CHECK_ATTEMPTS` `:183`, `SHOT_ALIASES` `:190-191`, the thresholds `:194-199`, `story_server` `:476-482`, `restore_story_server` `:485-495`, `wait_for_vlm` `:516-523`, `wait_for_avail` `:526-532`, `busy_process` `:535-556`, `free_gib` `:559-566`, `library_lock` `:586-613`, `wrap_still` `:769-782`, `verify_ffprobe` `:392-404`, `edit_models_missing` `:831-844`, `EDIT_MODEL`...`EDIT_TRUE_CFG` `:164-168`, `run_zimage_child` `:1746-1762`, `run_edit_child` `:1765-1781`), `ltx_image_fit.py` (`load_oriented_rgb` `:51-60`), `bin/character` (`:83-152`).

**Interfaces:**
- Consumes: everything Task 2 produces in `location_lib`; from `character_dataset`: `DatasetError`, `STYLE`, `SHOTS`, `SHOT_ALIASES`, `CHECK_ATTEMPTS`, `CREATE_MIN_FREE_GIB`, `GENERATE_MIN_AVAIL_GIB`, `EDIT_MIN_AVAIL_GIB`, `AVAIL_WAIT_S`, `VLM_WAIT_S`, `VLM_MODEL`, `MODELS_URL`, `VLM_SERVE_MODE`, `EDIT_MODEL`, `EDIT_LORA_REPO`, `EDIT_LORA_FILE`, `EDIT_STEPS`, `EDIT_TRUE_CFG`, `extract_json`, `image_data_url`, `vlm_call`, `vlm_ready`, `story_server`, `restore_story_server`, `wait_for_vlm`, `wait_for_avail`, `busy_process`, `free_gib`, `library_lock`, `edit_models_missing`, `run_zimage_child`, `run_edit_child`, `wrap_still`, `verify_ffprobe`; `ltx_image_fit.load_oriented_rgb(path) -> PIL.Image`.
- Produces, in `location_dataset`:
  - the constants above, `WIDTH, HEIGHT = 1024, 640`, `SEED_MAX`, `MIN_CROP_W, MIN_CROP_H = 768, 480`, `DESCRIBE_PHOTOS = 5`, `DESCRIBE_ATTEMPTS = 3`, `REASON_GROUPS`, `BLOCKED`, `FORCE_HINT`;
  - `gen_prompt(view, time, weather, description) -> str`, `still_path(loc_dir, n) -> str`, `photo_copy_path(loc_dir, k) -> str`, `_sha256(path) -> str`;
  - `describe(paths) -> str` (raises `DatasetError`), `validate_location_check(d, scored) -> dict` (raises `ValueError`), `check_still(prompt, paths, scored) -> (dict or None, None or str)`, `caption(trigger, check) -> str`, `cell_label(item) -> str`, `write_contact_sheet(items, stills_dir, out_path)`, `reason_counts(items) -> str`;
  - `build_dataset(data, force=False) -> 0 | 1 | 3`, `create(args) -> 0 | 1 | 2 | 3`, `_regenerate(args)`, `edit(args) -> 0 | 2`; `args` is the `bin/location create` namespace (`name`, `description`, `photos`, `trigger`, `seed`, `force`, `regenerate`, `new_seed`) or the `edit` namespace (`name`, `description`).
- Produces, in `bin/location`: `build_parser()`, `cmd_list()`, `cmd_show(name)`, `main(argv=None) -> int`, `run(argv=None) -> int`, `ANGLES_NOTE`.
- Produces, in the tests: `_Fakes(monkeypatch, replies=None, describe=(), skip=(), child_error=None, missing=(), vlm_up=True)` (with `.vlm_calls`, `.server_calls`, `.child_specs`, `.checks()`), `_kind(parts)`, `_create_args(name="harbour-street", **kw)`, `_photos(tmp_path, count, size=(800, 500), start=0)`, `PASS`; in `tests/test_location_tool.py`: `tool`, `ll`, `_fakes(monkeypatch, vlm_up=True)`, `_photo`, `_subprocess`, `CAFE_DESC`.

- [ ] **Step 1: Write the failing tests.**

**1.1.** Edit `tests/test_location_dataset.py`: replace this text, which occurs exactly once:

```python
import argparse
import json
import os
import sys
import types
```

with:

```python
import argparse
import importlib.machinery
import json
import os
import re
import sys
import types
```

**1.2.** Edit `tests/test_location_dataset.py`: replace this text, which occurs exactly once:

```python
import character_dataset  # noqa: E402
import story_engine_testutil as seu  # noqa: E402
```

with:

```python
import character_dataset  # noqa: E402
import location_testutil as lt  # noqa: E402
import story_engine_testutil as seu  # noqa: E402

ld = importlib.machinery.SourceFileLoader(
    "location_dataset_for_tests", os.path.join(WS, "location_dataset.py")).load_module()
ll = ld.location_lib
```

**1.3.** Edit `tests/test_location_dataset.py`: replace this text, which occurs exactly once:

```python
    assert [(c["prompt"], c["num_inference_steps"], c["true_cfg_scale"], c["generator"].seed)
            for c in calls["pipe"]] == [("edit 5", 8, 1.0, 5), ("edit 6", 8, 1.0, 5)]
```

with:

```python
    assert [(c["prompt"], c["num_inference_steps"], c["true_cfg_scale"], c["generator"].seed)
            for c in calls["pipe"]] == [("edit 5", 8, 1.0, 5), ("edit 6", 8, 1.0, 5)]


# --- Task 4 helpers: the create/regenerate fakes (spec 6.2) ---------------------------------

PASS = {"match_score": 9, "people_visible": False, "shot": "wide shot", "time_of_day": "dusk",
        "weather": "fog"}


class _Fakes(object):
    """The spec 6.2 fakes for create, regenerate and edit: a VLM that answers describe replies in
    order and check replies by still number (replies[n] is a dict, a string sent as is, an
    exception raised, or a list of those, one per attempt; default PASS), the story server, every
    gate, and image children that write 1024x640 solid PNGs for their jobs (except the 1-based
    job numbers in skip, which are blocked) or raise child_error. image_data_url is replaced by
    "file:<path>", so a check call names its still."""

    def __init__(self, monkeypatch, replies=None, describe=(), skip=(), child_error=None,
                 missing=(), vlm_up=True):
        self.replies, self.describe = dict(replies or {}), list(describe)
        self.vlm_calls, self.server_calls, self.child_specs = [], [], []
        self.skip, self.child_error, self.missing = set(skip), child_error, list(missing)
        self.attempt = 0
        fakes = self

        def _vlm(parts, max_tokens=600):
            fakes.vlm_calls.append(parts)
            if _kind(parts) == "describe":
                return fakes.describe.pop(0)
            fakes.attempt = fakes.attempt + 1 if _kind(parts) == "retry" else 0
            url = [p["image_url"]["url"] for p in parts if p["type"] == "image_url"][-1]
            reply = fakes.replies.get(int(re.search(r"loc_(\d+)\.png$", url).group(1)), PASS)
            if isinstance(reply, list):
                reply = reply[min(fakes.attempt, len(reply) - 1)]
            if isinstance(reply, Exception):
                raise reply
            return reply if isinstance(reply, str) else json.dumps(reply)

        def _child(spec, loc_dir, step):
            fakes.child_specs.append((json.loads(json.dumps(spec)), step))
            if fakes.child_error is not None:
                raise fakes.child_error
            jobs = []
            for i, job in enumerate(spec["jobs"], 1):
                if i in fakes.skip:
                    jobs.append({"output_path": job["output_path"], "status": "blocked",
                                 "seconds": 0.0})
                    continue
                if "image" in job:
                    assert os.path.isfile(job["image"]), job["image"]
                Image.new("RGB", (job["width"], job["height"]), (60, 90, 120)).save(
                    job["output_path"])
                jobs.append({"output_path": job["output_path"], "status": "ok", "seconds": 1.0})
            return {"jobs": jobs, "injected_lora_modules": None}

        monkeypatch.setattr(character_dataset, "image_data_url",
                            lambda path, max_side=768: "file:" + path)
        monkeypatch.setattr(character_dataset, "vlm_call", _vlm)
        monkeypatch.setattr(character_dataset, "run_zimage_child", _child)
        monkeypatch.setattr(character_dataset, "run_edit_child", _child)
        monkeypatch.setattr(character_dataset, "edit_models_missing", lambda: list(fakes.missing))
        monkeypatch.setattr(character_dataset, "restore_story_server",
                            lambda wait=False: fakes.server_calls.append(
                                "restore-wait" if wait else "restore") or 0)
        monkeypatch.setattr(character_dataset, "story_server",
                            lambda cmd: fakes.server_calls.append(cmd) or 0)
        monkeypatch.setattr(character_dataset, "wait_for_vlm", lambda timeout_s: True)
        monkeypatch.setattr(character_dataset, "wait_for_avail", lambda gib, timeout_s: True)
        monkeypatch.setattr(character_dataset, "vlm_ready", lambda: vlm_up)
        monkeypatch.setattr(character_dataset, "busy_process", lambda: None)
        monkeypatch.setattr(character_dataset, "story_server_state", lambda: "STOPPED")
        monkeypatch.setattr(character_dataset, "free_gib", lambda path: 100.0)

    def checks(self):
        """The first attempt of every check call, in order: (prompt text, image urls)."""
        out = []
        for parts in self.vlm_calls:
            if _kind(parts) == "check":
                out.append((parts[0]["text"],
                            [p["image_url"]["url"] for p in parts if p["type"] == "image_url"]))
        return out


def _kind(parts):
    """"describe" (a describe or shorten call), "retry" (a check retry) or "check"."""
    text = parts[0]["text"]
    if text == ld.DESCRIBE_PROMPT or text.startswith("Shorten this place description"):
        return "describe"
    if parts[-1]["type"] == "text" and parts[-1]["text"].startswith(
            "Your previous reply was rejected"):
        return "retry"
    return "check"


def _create_args(name="harbour-street", **kw):
    args = dict(command="create", name=name, description=None, photos=None, trigger=None,
                seed=None, force=False, regenerate=False, new_seed=False)
    args.update(kw)
    return argparse.Namespace(**args)


def _photos(tmp_path, count, size=(800, 500), start=0):
    """count distinct solid photos (each a different colour), as absolute paths."""
    out = []
    for k in range(start, start + count):
        path = str(tmp_path / ("photo_in_%02d.png" % k))
        Image.new("RGB", size, (k * 9 % 256, 255 - k * 7 % 256, 40)).save(path)
        out.append(path)
    return out


def _record(env, name="harbour-street"):
    return ll.load_location(name)


def _manifest(env, name="harbour-street"):
    with open(os.path.join(env["locations"], name, "manifest.json")) as f:
        return json.load(f)


def _err_line(capsys):
    return capsys.readouterr().err.strip().splitlines()[-1]


# --- LD1, LD2, LD3: the literals and the check validator (L1.5-L1.9) ------------------------

def test_ld1_the_24_variants_and_gen_prompt():
    views = ["Extreme wide establishing shot", "Wide shot from a high vantage point",
             "Ground-level view looking along the length", "Low-angle upward view",
             "Medium shot of a single detail", "Close-up of a surface texture or sign"]
    times = [("dawn", "clear"), ("midday", "overcast"), ("golden hour", "fog"), ("night", "fog"),
             ("midday", "clear"), ("dusk", "overcast"), ("dawn", "fog"), ("night", "rain"),
             ("golden hour", "clear"), ("midday", "rain"), ("dusk", "fog"), ("night", "clear"),
             ("midday", "overcast"), ("dawn", "overcast"), ("dusk", "rain"), ("golden hour", "fog"),
             ("midday", "overcast"), ("golden hour", "rain"), ("night", "clear"), ("dawn", "rain"),
             ("dawn", "clear"), ("dusk", "fog"), ("golden hour", "overcast"), ("night", "rain")]
    assert ld.VARIANTS == [(views[k // 4],) + times[k] for k in range(24)]
    counts = dict((t, sum(1 for v in ld.VARIANTS if v[1] == t)) for t in ld.TIMES)
    assert counts == {"dawn": 5, "midday": 5, "golden hour": 5, "dusk": 4, "night": 5}
    assert dict((w, sum(1 for v in ld.VARIANTS if v[2] == w)) for w in ld.WEATHERS) == {
        "clear": 6, "overcast": 6, "rain": 6, "fog": 6, "snow": 0}
    for view in views:
        assert len(set(v[1] for v in ld.VARIANTS if v[0] == view)) == 4
    assert ld.TIMES == ("dawn", "midday", "golden hour", "dusk", "night")
    assert ld.WEATHERS == ("clear", "overcast", "rain", "fog", "snow")
    assert ld.STYLE == "photorealistic live-action film still, natural light"
    d = lt.HARBOUR_DESC
    assert ld.gen_prompt(*(ld.VARIANTS[0] + (d,))) == (
        "Extreme wide establishing shot of %s, at dawn, under a clear sky, empty of people. "
        "photorealistic live-action film still, natural light." % d)
    assert ld.gen_prompt(*(ld.VARIANTS[10] + (d,))) == (
        "Ground-level view looking along the length of %s, at dusk, in fog, empty of people. "
        "photorealistic live-action film still, natural light." % d)
    assert ld.gen_prompt(*(ld.VARIANTS[23] + (d,))) == (
        "Close-up of a surface texture or sign of %s, at night, in the rain, empty of people. "
        "photorealistic live-action film still, natural light." % d)


def test_ld2_the_section_2_literals():
    assert ld.EDIT_PROMPT == (
        "Keep this exact place and viewpoint: the same buildings, structures, ground, signs, "
        "materials and colours, seen from the same camera position with the same framing. Change "
        "only the time of day and the conditions: show it %s, %s. No people anywhere in the "
        "image. Photorealistic live-action film still, natural light.")
    assert ld.EDIT_CONDITIONS == [
        ("at dusk", "under a clear sky"), ("at night", "in light rain"),
        ("at dawn", "in thick fog"), ("at midday", "under an overcast sky"),
        ("at golden hour", "under a clear sky"), ("at night", "under a clear sky"),
        ("at midday", "in winter with fresh snow on the ground"), ("at dusk", "in heavy rain"),
        ("at dawn", "under an overcast sky"),
        ("at golden hour", "in autumn with fallen leaves on the ground"),
        ("at midday", "in light fog"), ("at night", "in fog"), ("at dawn", "under a clear sky"),
        ("at dusk", "under an overcast sky"), ("at midday", "in the rain"),
        ("at golden hour", "in light haze"), ("at night", "in winter with snow falling"),
        ("at dawn", "in light rain"), ("at midday", "in summer under a clear sky"),
        ("at dusk", "in fog"), ("at golden hour", "under an overcast sky"),
        ("at night", "in heavy rain"), ("at midday", "in spring under a clear sky")]
    assert len(ld.EDIT_CONDITIONS) == 23
    assert ld.DESCRIBE_PROMPT == (
        'These photos show one place. Describe it for an image generator that must redraw the '
        'same place recognisably from many viewpoints, at any time of day and in any weather. '
        'Reply with only a JSON object with one key. "description": one noun phrase of 15 to 40 '
        'words that starts with "a", "an" or "the" and captures only the place\'s persistent '
        'features: its architecture and structures, materials and surfaces, signage, colour '
        'palette, era and the ground. Leave out people, vehicles, animals, the time of day, the '
        'weather, the lighting, the season, the camera and the image style. Use commas, not full '
        'stops.')
    assert ld.DESCRIBE_SHORTEN == (
        'Shorten this place description to one noun phrase of 20 to 35 words that starts with '
        '"a", "an" or "the". Keep the architecture, materials, signage, palette, era and ground; '
        'drop repetition and the least distinctive details; use commas and no full stops. Reply '
        'with only a JSON object with one key, "description": the shortened phrase.\n\n'
        'Description: %s')
    assert ld.DESCRIBE_RETRY == (
        'Your previous reply was rejected: %s. Previous reply: %s\n'
        'Reply again with only the JSON object. Keep "description" one noun phrase of 15 to 40 '
        'words starting with "a", "an" or "the", with commas and no full stops.')
    keys = ('"people_visible": true when any person or part of a person is visible anywhere in '
            'the image, else false. "shot": exactly one of extreme wide shot, wide shot, medium '
            'shot, medium close-up, close-up, extreme close-up. "time_of_day": exactly one of '
            'dawn, midday, golden hour, dusk, night. "weather": exactly one of clear, overcast, '
            'rain, fog, snow.')
    assert ld.CHECK_TEXT_PROMPT == (
        'The image is a candidate picture of this place: @@DESCRIPTION@@. Reply with only a JSON '
        'object with five keys. "match_score": an integer from 1 to 10 for how clearly the image '
        'shows this place, with its architecture, materials, signage, palette, era and ground, '
        'where 10 is unmistakably this place and 1 is a different place. ' + keys)
    assert ld.CHECK_PHOTO_PROMPT == (
        'The first image shows the reference place. The second image is a candidate picture, '
        'which may show the same place from another viewpoint, at another time of day, in other '
        'weather or in another season. Reply with only a JSON object with five keys. '
        '"match_score": an integer from 1 to 10 for how clearly the candidate shows the same '
        'place as the reference, comparing its architecture, materials, signage, palette and '
        'ground and ignoring the time of day, weather and season, where 10 is unmistakably the '
        'same place and 1 is a different place. ' + keys)
    assert ld.TAG_PROMPT == 'Reply with only a JSON object with four keys describing this image. ' + keys
    assert ld.CHECK_RETRY == (
        'Your previous reply was rejected: %s. Previous reply: %s\n'
        'Reply again with only the JSON object, using exactly the listed values for "shot", '
        '"time_of_day" and "weather" and true or false for "people_visible"%s.')
    assert ld.SCORE_RETRY_EXTRA == ', and an integer from 1 to 10 for "match_score"'
    assert ld.TIME_ALIASES == {"noon": "midday", "day": "midday", "daytime": "midday",
                               "sunrise": "dawn", "sunset": "golden hour", "evening": "dusk",
                               "twilight": "dusk"}
    assert ld.WEATHER_ALIASES == {"sunny": "clear", "cloudy": "overcast", "rainy": "rain",
                                  "foggy": "fog", "mist": "fog", "misty": "fog", "haze": "fog",
                                  "hazy": "fog", "snowy": "snow"}


def test_ld3_validate_location_check():
    v = ld.validate_location_check
    assert v(PASS, True) == PASS
    assert v({"people_visible": True, "shot": " Full Shot ", "time_of_day": "Sunset",
              "weather": "misty"}, False) == {"match_score": None, "people_visible": True,
                                              "shot": "wide shot", "time_of_day": "golden hour",
                                              "weather": "fog"}
    for alias, value in ld.TIME_ALIASES.items():
        assert v(dict(PASS, time_of_day=alias), True)["time_of_day"] == value
    for alias, value in ld.WEATHER_ALIASES.items():
        assert v(dict(PASS, weather=alias), True)["weather"] == value
    assert v(dict(PASS, weather="snow"), True)["weather"] == "snow"
    for bad, scored in ((dict(PASS, match_score=True), True), (dict(PASS, match_score=11), True),
                        (dict(PASS, match_score="9"), True), (dict(PASS, match_score=0), True),
                        ({k: PASS[k] for k in PASS if k != "match_score"}, True),
                        (dict(PASS, people_visible="no"), False), (dict(PASS, shot="aerial"), False),
                        (dict(PASS, time_of_day="afternoon"), False),
                        (dict(PASS, weather="storm"), False), (dict(PASS, shot=3), False)):
        with pytest.raises(ValueError):
            v(bad, scored)


def test_ld4_check_retries_quote_the_rejection(env, monkeypatch, tmp_path):
    png = str(tmp_path / "loc_01.png")
    Image.new("RGB", (64, 40)).save(png)
    fakes = _Fakes(monkeypatch, replies={1: ["not json", json.dumps(PASS)]})
    check, reason = ld.check_still(ld.TAG_PROMPT, [png], False)
    assert reason is None and check["shot"] == "wide shot"
    first, second = fakes.vlm_calls
    assert len(first) == 2 and len(second) == 3
    assert second[-1]["text"] == ld.CHECK_RETRY % ("no JSON object found in text", "not json", "")
    fakes = _Fakes(monkeypatch, replies={1: ["nope", "nope", json.dumps(dict(PASS, shot="x"))]})
    check, reason = ld.check_still(ld.CHECK_TEXT_PROMPT, [png], True)
    assert check is None and reason.startswith("unparseable: shot 'x' is not one of ")
    assert fakes.vlm_calls[1][-1]["text"].endswith(ld.SCORE_RETRY_EXTRA + ".")
    assert len(fakes.vlm_calls) == 3
    _Fakes(monkeypatch, replies={1: RuntimeError("VLM request failed: boom")})
    with pytest.raises(RuntimeError):
        ld.check_still(ld.TAG_PROMPT, [png], False)


# --- LD5: a text create (LK6) ---------------------------------------------------------------

def test_ld5_a_text_create(env, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, replies=dict((n, dict(PASS, match_score=3)) for n in range(21, 25)))
    assert ld.create(_create_args(description="The " + lt.HARBOUR_DESC[2:] + ".", seed=7)) == 0
    ldir = os.path.join(env["locations"], "harbour-street")
    ((spec, step),) = fakes.child_specs
    description = "the " + lt.HARBOUR_DESC[2:]
    assert step == "generate" and spec["loras"] is None
    assert spec["jobs"] == [{"prompt": ld.gen_prompt(view, time, weather, description),
                             "output_path": os.path.join(ldir, "stills", "loc_%02d.png" % n),
                             "seed": 7, "width": 1024, "height": 640}
                            for n, (view, time, weather) in enumerate(ld.VARIANTS, start=1)]
    assert fakes.server_calls == ["stop", "restore-wait"]
    stills = os.path.join(ldir, "stills")
    assert fakes.checks() == [(ld.CHECK_TEXT_PROMPT.replace("@@DESCRIPTION@@", description),
                               ["file:" + os.path.join(stills, "loc_%02d.png" % n)])
                              for n in range(1, 25)]
    data = _record(env)
    assert (data["status"], data["dataset"]["kept"], data["dataset"]["total"]) == ("untrained", 20, 24)
    assert (data["source"], data["photos"], data["trigger"], data["seed"]) == ("text", [], "harboplc", 7)
    assert data["dataset"]["contact_sheet"] == os.path.join(ldir, "contact_sheet.jpg")
    out = capsys.readouterr().out
    assert "dataset: 20/24 stills kept (minimum 12) in %s\n" % ldir in out
    assert out.endswith("next: review the contact sheet, then run bin/location train "
                        "harbour-street\n")
    assert sorted(os.listdir(os.path.join(ldir, "captions"))) == ["loc_%02d.txt" % n
                                                                  for n in range(1, 21)]
    assert sorted(os.listdir(os.path.join(ldir, "videos"))) == ["loc_%02d.mp4" % n
                                                                for n in range(1, 21)]
    with open(os.path.join(env["locations"], ".triggers")) as f:
        assert f.read() == "harboplc harbour-street\n"


# --- LD6-LD10: photo mode (L1.6, L1.7, L1.8) ------------------------------------------------

def test_ld6_a_photo_is_fitted_and_copied_oriented(env, monkeypatch, tmp_path):
    from PIL import ImageOps
    path = str(tmp_path / "rotated.jpg")
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (4000, 3000), (200, 120, 40)).save(path, exif=exif)
    import ltx_image_fit
    oriented = ltx_image_fit.load_oriented_rgb(path)
    assert oriented.size == (3000, 4000)
    _Fakes(monkeypatch)
    assert ld.create(_create_args(photos=[path], description=lt.HARBOUR_DESC)) == 0
    ldir = os.path.join(env["locations"], "harbour-street")
    with Image.open(os.path.join(ldir, "photos", "photo_01.png")) as copy:
        assert copy.size == (3000, 4000) and copy.tobytes() == oriented.tobytes()
    with Image.open(os.path.join(ldir, "stills", "loc_01.png")) as still:
        expected = ImageOps.fit(oriented, (1024, 640), Image.LANCZOS, centering=(0.5, 0.5))
        assert still.size == (1024, 640) and still.tobytes() == expected.tobytes()
    data = _record(env)
    assert data["photos"] == [{"path": path, "sha256": ld._sha256(path)}]
    assert data["source"] == "photos"


def test_ld7_the_photo_size_rule(env, monkeypatch, tmp_path, capsys):
    _Fakes(monkeypatch, vlm_up=False)
    ok = _photos(tmp_path, 1, size=(768, 480))
    assert ld.create(_create_args(photos=ok, description=lt.HARBOUR_DESC)) == 2
    assert _err_line(capsys).startswith("Error: the vision model ")
    for size, crop in (((767, 480), "767x479"), ((2000, 479), "766x479")):
        path = _photos(tmp_path, 1, size=size, start=size[0])[0]
        assert ld.create(_create_args(photos=[path], description=lt.HARBOUR_DESC)) == 2
        assert _err_line(capsys) == (
            "Error: --photo %s is %dx%d; its centred 16:10 crop is %s, smaller than the 768x480 "
            "minimum" % (path, size[0], size[1], crop))
    assert os.listdir(env["locations"]) == []


def test_ld8_the_drafted_description(env, monkeypatch, tmp_path, capsys):
    paths = _photos(tmp_path, 6)
    long_text = "the " + " ".join("stone%d" % k for k in range(44))
    short_text = "a quay with boats"
    fakes = _Fakes(monkeypatch, describe=[json.dumps({"description": long_text}),
                                          json.dumps({"description": short_text}),
                                          json.dumps({"description": "The " + lt.HARBOUR_DESC[2:]
                                                      + "."})])
    assert ld.create(_create_args(photos=paths)) == 0
    first, second, third = fakes.vlm_calls[:3]
    assert first[0]["text"] == ld.DESCRIBE_PROMPT
    assert [p["image_url"]["url"] for p in first[1:]] == ["file:" + p for p in paths[:5]]
    assert second == [{"type": "text", "text": ld.DESCRIBE_SHORTEN % long_text}]
    assert third[:6] == first and third[6]["text"] == ld.DESCRIBE_RETRY % (
        "description: must be 15-40 words, got 4", json.dumps({"description": short_text}))
    assert _record(env)["description"] == "the " + lt.HARBOUR_DESC[2:]
    assert ("description (drafted by the vision model; change it with bin/location edit "
            "harbour-street --description TEXT): the " + lt.HARBOUR_DESC[2:]) in capsys.readouterr().out
    _Fakes(monkeypatch, describe=["no json"] * 3)
    assert ld.create(_create_args(name="old-mill", photos=paths)) == 1
    assert _err_line(capsys).startswith(
        "Error: describe failed: no JSON object found in text; last reply: 'no json'")
    assert not os.path.exists(os.path.join(env["locations"], "old-mill"))


@pytest.mark.parametrize("count", [1, 3, 5, 24])
def test_ld9_the_round_robin_top_up(env, monkeypatch, tmp_path, count):
    paths = _photos(tmp_path, count, size=(768, 480))
    fakes = _Fakes(monkeypatch)
    assert ld.create(_create_args(photos=paths, description=lt.HARBOUR_DESC, seed=3)) == 0
    ldir = os.path.join(env["locations"], "harbour-street")
    stills = os.path.join(ldir, "stills")
    assert sorted(os.listdir(stills)) == ["loc_%02d.png" % n for n in range(1, 25)]
    if count == 24:
        assert fakes.child_specs == [] and fakes.server_calls == []
        assert _manifest(env)["generator"] == "photos only"
        return
    ((spec, step),) = fakes.child_specs
    assert step == "edit" and spec["skill"] == "location_edit"
    assert spec["image"] == os.path.join(stills, "loc_01.png")
    assert (spec["model"], spec["lora_repo"], spec["lora_file"], spec["steps"], spec["true_cfg"]) == (
        character_dataset.EDIT_MODEL, character_dataset.EDIT_LORA_REPO,
        character_dataset.EDIT_LORA_FILE, 8, 1.0)
    assert spec["jobs"] == [{"image": os.path.join(stills, "loc_%02d.png" % (((j - 1) % count) + 1)),
                             "prompt": ld.EDIT_PROMPT % ld.EDIT_CONDITIONS[j - 1],
                             "output_path": os.path.join(stills, "loc_%02d.png" % (count + j)),
                             "seed": 3, "width": 1024, "height": 640}
                            for j in range(1, 25 - count)]
    assert fakes.server_calls == ["stop", "restore-wait"]
    ref = "file:" + os.path.join(stills, "loc_01.png")
    assert fakes.checks() == (
        [(ld.TAG_PROMPT, ["file:" + os.path.join(stills, "loc_%02d.png" % n)])
         for n in range(1, count + 1)]
        + [(ld.CHECK_PHOTO_PROMPT, [ref, "file:" + os.path.join(stills, "loc_%02d.png" % n)])
           for n in range(count + 1, 25)])


def test_ld10_the_edit_model_gate(env, monkeypatch, tmp_path, capsys):
    fakes = _Fakes(monkeypatch, missing=["Qwen/Qwen-Image-Edit-2511"])
    assert ld.create(_create_args(photos=_photos(tmp_path, 2), description=lt.HARBOUR_DESC)) == 2
    assert _err_line(capsys) == (
        "Error: the photo editor is not downloaded: Qwen/Qwen-Image-Edit-2511; download it with: "
        "hf download Qwen/Qwen-Image-Edit-2511")
    assert fakes.vlm_calls == [] and os.listdir(env["locations"]) == []


# --- LD11-LD15: keep rules, captions, manifest, contact sheet, too few (L1.9-L1.11) ---------

def test_ld11_the_keep_rules(env, monkeypatch, tmp_path):
    _Fakes(monkeypatch, replies={2: dict(PASS, match_score=6),
                                 3: dict(PASS, people_visible=True), 5: ["x", "x", "x"]}, skip=[4])
    assert ld.create(_create_args(description=lt.HARBOUR_DESC)) == 0
    items = _manifest(env)["items"]
    assert [(i["n"], i["kept"], i["reason"]) for i in items[:5]] == [
        (1, True, None), (2, False, "score 6"), (3, False, "people visible"),
        (4, False, "blocked by the content screen"),
        (5, False, "unparseable: no JSON object found in text")]
    paths = _photos(tmp_path, 3)
    replies = {1: dict(PASS, people_visible=True), 2: ["x", "x", "x"],
               4: dict(PASS, people_visible=True), 5: dict(PASS, match_score=6)}
    _Fakes(monkeypatch, replies=replies)
    assert ld.create(_create_args(name="dock-one", photos=paths, description=lt.MILL_DESC)) == 0
    items = _manifest(env, "dock-one")["items"]
    assert [(i["n"], i["kept"], i["reason"]) for i in items[:5]] == [
        (1, False, "people visible (pass --force to keep it)"),
        (2, False, "unparseable: no JSON object found in text (pass --force to keep it)"),
        (3, True, None), (4, False, "people visible"), (5, False, "score 6")]
    _Fakes(monkeypatch, replies=replies)
    assert ld.create(_create_args(name="dock-two", photos=paths, description=lt.MILL_DESC,
                                  force=True)) == 0
    items = _manifest(env, "dock-two")["items"]
    trigger = _record(env, "dock-two")["trigger"]
    assert [(i["n"], i["kept"], i["reason"]) for i in items[:5]] == [
        (1, True, "kept by --force: people visible"),
        (2, True, "kept by --force: unparseable: no JSON object found in text"),
        (3, True, None), (4, False, "people visible"), (5, False, "score 6")]
    assert items[1]["caption"] == trigger + ", " + ld.STYLE + "."


def test_ld12_captions():
    assert ld.caption("harboplc", PASS) == (
        "harboplc, wide shot, dusk, fog, empty of people, photorealistic live-action film still, "
        "natural light.")
    assert ld.caption("harboplc", dict(PASS, people_visible=True)) == (
        "harboplc, wide shot, dusk, fog, photorealistic live-action film still, natural light.")
    assert ld.caption("harboplc", None) == (
        "harboplc, photorealistic live-action film still, natural light.")


def test_ld13_the_manifest(env, monkeypatch, tmp_path):
    _Fakes(monkeypatch, skip=[3])
    assert ld.create(_create_args(description=lt.HARBOUR_DESC, seed=4)) == 0
    manifest = _manifest(env)
    assert {k: manifest[k] for k in manifest if k != "items"} == {
        "source": "text", "trigger": "harboplc", "description": lt.HARBOUR_DESC, "seed": 4,
        "min_score": 7, "reference": None, "generator": "Z-Image"}
    first, blocked = manifest["items"][0], manifest["items"][2]
    assert first == {"n": 1, "source": "generated", "photo": None,
                     "prompt": ld.gen_prompt(*(ld.VARIANTS[0] + (lt.HARBOUR_DESC,))),
                     "match_score": 9, "people_visible": False, "shot": "wide shot",
                     "time_of_day": "dusk", "weather": "fog", "kept": True, "reason": None,
                     "caption": ld.caption("harboplc", PASS)}
    assert blocked == {"n": 3, "source": "generated", "photo": None,
                       "prompt": ld.gen_prompt(*(ld.VARIANTS[2] + (lt.HARBOUR_DESC,))),
                       "match_score": None, "people_visible": None, "shot": "", "time_of_day": "",
                       "weather": "", "kept": False, "reason": "blocked by the content screen",
                       "caption": None}
    _Fakes(monkeypatch)
    assert ld.create(_create_args(name="old-mill", photos=_photos(tmp_path, 2),
                                  description=lt.MILL_DESC)) == 0
    manifest = _manifest(env, "old-mill")
    assert (manifest["source"], manifest["reference"], manifest["generator"]) == (
        "photos", "loc_01", "Qwen/Qwen-Image-Edit-2511 + "
        "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors, 8 steps")
    photo, edit = manifest["items"][1], manifest["items"][2]
    assert (photo["source"], photo["photo"], photo["prompt"], photo["match_score"]) == (
        "photo", 2, None, None)
    assert (edit["source"], edit["photo"], edit["prompt"], edit["match_score"]) == (
        "edit", 1, ld.EDIT_PROMPT % ld.EDIT_CONDITIONS[0], 9)
    assert list(edit) == ["n", "source", "photo", "prompt", "match_score", "people_visible",
                          "shot", "time_of_day", "weather", "kept", "reason", "caption"]


def test_ld14_the_contact_sheet(tmp_path, monkeypatch):
    stills = tmp_path / "stills"
    stills.mkdir()
    items = []
    for n in range(1, 25):
        if n != 7:
            Image.new("RGB", (1024, 640), (0, 200, 0)).save(str(stills / ("loc_%02d.png" % n)))
        kept = n not in (2, 7)
        items.append({"n": n, "source": "photo" if n == 1 else "generated",
                      "match_score": None if n in (1, 7) else 9 - (n == 2) * 3, "kept": kept,
                      "reason": None if kept else ("score 6" if n == 2 else
                                                   "blocked by the content screen")})
    texts = []
    real_text = ld.ImageDraw.ImageDraw.text
    monkeypatch.setattr(ld.ImageDraw.ImageDraw, "text",
                        lambda self, xy, text, **kw: texts.append((xy, text)) or real_text(
                            self, xy, text, **kw))
    out = str(tmp_path / "sheet.jpg")
    ld.write_contact_sheet(items, str(stills), out)
    assert texts[0] == ((4, 6), "kept 22 of 24 (need 12)")
    assert [t for _xy, t in texts[1:4]] == ["01 P s- kept", "02 G s6 score 6",
                                            "03 G s9 kept"]
    assert texts[7] == ((256 + 4, 24 + 180 + 160 + 3), "07 G s- blocked by the content scree")
    with Image.open(out) as sheet:
        assert sheet.size == (5 * 256, 24 + 5 * 180)
        assert sheet.getpixel((256 + 1, 24 + 1))[0] > 200 and sheet.getpixel((256 + 1, 24 + 1))[1] < 80
        assert sheet.getpixel((128, 24 + 80))[1] > 150
        assert sheet.getpixel((128, 24 + 1))[0] < 80
        assert max(sheet.getpixel((256 + 128, 180 + 24 + 80))) < 40


def test_ld15_too_few_stills_exit_3(env, monkeypatch, tmp_path, capsys):
    replies = dict((n, dict(PASS, people_visible=True)) for n in range(12, 17))
    replies.update((n, dict(PASS, match_score=3)) for n in range(17, 21))
    replies.update((n, ["x", "x", "x"]) for n in (23, 24))
    _Fakes(monkeypatch, replies=replies, skip=[21, 22])
    assert ld.create(_create_args(description=lt.HARBOUR_DESC)) == 3
    ldir = os.path.join(env["locations"], "harbour-street")
    assert _err_line(capsys) == (
        "Error: only 11/24 stills kept (need 12): 5 people visible, 4 score below 7, 2 blocked by "
        "the content screen, 2 unparseable; the dataset is kept in %s; run bin/location create "
        "harbour-street --regenerate --new-seed, or --regenerate --description TEXT with a "
        "clearer description" % ldir)
    data = _record(env)
    assert (data["status"], data["dataset"]["kept"]) == ("dataset", 11)
    assert os.path.isfile(os.path.join(ldir, "contact_sheet.jpg"))
    _Fakes(monkeypatch, replies=dict((n, dict(PASS, match_score=2)) for n in range(2, 25)))
    assert ld.create(_create_args(name="old-mill", photos=_photos(tmp_path, 1),
                                  description=lt.MILL_DESC)) == 3
    assert _err_line(capsys).endswith(
        "; create a new location with more photos that show no people, or run bin/location "
        "create old-mill --regenerate --new-seed (--force keeps photos that show people)")


# --- LD16, LD17: a failing or interrupted image child (L5.1) --------------------------------

def test_ld16_a_failed_child_restores_the_server(env, monkeypatch, capsys):
    error = character_dataset.DatasetError("Z-Image child process exited -9; log: /x/logs/g.log")
    fakes = _Fakes(monkeypatch, child_error=error)
    assert ld.create(_create_args(description=lt.HARBOUR_DESC)) == 1
    assert fakes.server_calls == ["stop", "restore-wait"]
    assert _err_line(capsys) == "Error: Z-Image child process exited -9; log: /x/logs/g.log"
    assert _record(env)["status"] == "dataset" and fakes.vlm_calls == []
    monkeypatch.setattr(character_dataset, "wait_for_avail", lambda gib, timeout_s: False)
    assert ld.create(_create_args(name="old-mill", description=lt.MILL_DESC)) == 1
    assert _err_line(capsys) == ("Error: timed out waiting for 20 GiB available memory after "
                                 "stopping the story server")
    monkeypatch.setattr(character_dataset, "wait_for_avail", lambda gib, timeout_s: True)
    monkeypatch.setattr(character_dataset, "wait_for_vlm", lambda timeout_s: False)
    fakes.child_error = None
    assert ld.create(_create_args(name="dock-one", description=lt.TEMPLE_DESC)) == 1
    assert _err_line(capsys) == "Error: timed out waiting for the vision server to come back"


def test_ld17_an_interrupt_restores_detached(env, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, child_error=KeyboardInterrupt())
    assert ld.create(_create_args(description=lt.HARBOUR_DESC)) == 1
    assert fakes.server_calls == ["stop", "restore"]
    ldir = os.path.join(env["locations"], "harbour-street")
    assert _err_line(capsys) == (
        "Error: aborted; the stills made so far are kept in %s; run bin/location create "
        "harbour-street --regenerate to start again" % ldir)
    assert _record(env)["status"] == "dataset"


# --- LD24: regenerate (L1.12) ----------------------------------------------------------------

def _text_location(env, monkeypatch, **kw):
    _Fakes(monkeypatch)
    assert ld.create(_create_args(description=lt.HARBOUR_DESC, **kw)) == 0
    return os.path.join(env["locations"], "harbour-street")


def _train_record(ldir):
    """Mark the location trained, with a video LoRA, test clips and a train/ dir."""
    data = ll.load_location("harbour-street")
    for sub in ("lora", "tests", "train"):
        os.makedirs(os.path.join(ldir, sub), exist_ok=True)
    with open(os.path.join(ldir, "lora", "video.safetensors"), "wb") as f:
        f.write(lt.VIDEO_BYTES)
    data["loras"]["video"] = {"path": os.path.join(ldir, "lora", "video.safetensors"),
                              "sha256": ld._sha256(os.path.join(ldir, "lora", "video.safetensors")),
                              "base_model": "dgrauet/ltx-2.3-mlx-q8", "rank": 32, "alpha": 32,
                              "steps": 1000}
    data["status"], data["trained_at"] = "trained", "2026-10-29T12:00:00Z"
    data["stills_skip_reason"] = "mflux-train not found at /x"
    ll.write_location(data)


def test_ld24_regenerate(env, monkeypatch, tmp_path, capsys):
    ldir = _text_location(env, monkeypatch, seed=5)
    _Fakes(monkeypatch)
    assert ld.create(_create_args(regenerate=True, new_seed=True)) == 0
    assert _record(env)["seed"] == 6 and "seed: 5 -> 6" in capsys.readouterr().out
    assert ld.create(_create_args(regenerate=True, seed=40)) == 0
    assert _record(env)["seed"] == 40
    data = _record(env)
    data["seed"] = 2147483647
    ll.write_location(data)
    assert ld.create(_create_args(regenerate=True, new_seed=True)) == 0
    assert _record(env)["seed"] == 0
    fakes = _Fakes(monkeypatch)
    assert ld.create(_create_args(regenerate=True, description=lt.MILL_DESC.replace(
        "an old", "An old") + ".")) == 0
    assert _record(env)["description"] == lt.MILL_DESC
    assert fakes.child_specs[0][0]["jobs"][0]["prompt"] == ld.gen_prompt(
        *(ld.VARIANTS[0] + (lt.MILL_DESC,)))
    # A refused run leaves location.json byte for byte as it was (the seed is persisted only
    # after every preflight passed).
    with open(os.path.join(ldir, "location.json"), "rb") as f:
        before = f.read()
    _Fakes(monkeypatch, vlm_up=False)
    assert ld.create(_create_args(regenerate=True, new_seed=True)) == 2
    with open(os.path.join(ldir, "location.json"), "rb") as f:
        assert f.read() == before
    _train_record(ldir)
    _Fakes(monkeypatch)
    assert ld.create(_create_args(regenerate=True)) == 2
    assert _err_line(capsys) == (
        "Error: location harbour-street is trained; regenerating its dataset deletes its LoRAs. "
        "Pass --force to regenerate it anyway")
    os.makedirs(os.path.join(ldir, "logs"), exist_ok=True)
    with open(os.path.join(ldir, "logs", "keep.log"), "w") as f:
        f.write("x")
    assert ld.create(_create_args(regenerate=True, force=True)) == 0
    data = _record(env)
    assert data["loras"] == {"video": None, "stills": None}
    assert (data["status"], data["trained_at"], data["stills_skip_reason"]) == (
        "untrained", None, None)
    for sub in ("lora", "tests", "train"):
        assert not os.path.exists(os.path.join(ldir, sub)), sub
    assert os.path.isfile(os.path.join(ldir, "logs", "keep.log"))
    _Fakes(monkeypatch)
    paths = _photos(tmp_path, 2)
    assert ld.create(_create_args(name="old-mill", photos=paths, description=lt.MILL_DESC)) == 0
    mdir = os.path.join(env["locations"], "old-mill")
    assert ld.create(_create_args(name="old-mill", regenerate=True,
                                  description=lt.HARBOUR_DESC)) == 2
    assert _err_line(capsys) == (
        "Error: a photo location's stills come from its photos; change its description with "
        "bin/location edit old-mill --description TEXT")
    fakes = _Fakes(monkeypatch)
    assert ld.create(_create_args(name="old-mill", regenerate=True, new_seed=True)) == 0
    assert sorted(os.listdir(os.path.join(mdir, "photos"))) == ["photo_01.png", "photo_02.png"]
    assert fakes.child_specs[0][0]["jobs"][0]["image"] == os.path.join(mdir, "stills", "loc_01.png")
```

**1.4.** Create `tests/test_location_tool.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""Tests for bin/location end to end (docs/superpowers/specs/2026-10-29-location-lora-design.md,
Sections 2.2, 2.12, 3.1 and 6.1, test table 6.5: LT1-LT10, with the plan's Review Focus pins).

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_location_tool.py
Stdlib plus pytest and PIL. No test reads the real HOME, renders, trains, runs Z-Image or the
editor, contacts a model server or touches port 8178: the VLM, the story server, the gates and the
image children are fakes (spec 6.2), the bin/location-train-vlm checks run against stub tools in
a temporary bin/, and every library lives under tmp_path (HOME, CHARACTER_LIBRARY_DIR,
LOCATION_LIBRARY_DIR and LORA_CATALOG_DIR). Real ffmpeg/ffprobe wrap the kept stills.
"""

import importlib.machinery
import json
import os
import shutil
import signal
import subprocess
import sys
import time

import pytest
from PIL import Image

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import character_dataset  # noqa: E402
import location_testutil as lt  # noqa: E402
import story_engine_testutil as seu  # noqa: E402

TOOL_PATH = os.path.join(WS, "bin", "location")
tool = importlib.machinery.SourceFileLoader("location_tool", TOOL_PATH).load_module()
ll = tool.location_lib
CAFE_DESC = ("a small café terrace in Montréal with wrought iron chairs, striped awnings, cracked "
             "terracotta tiles and a faded blue sign above the door")
PASS = {"match_score": 9, "people_visible": False, "shot": "wide shot", "time_of_day": "dusk",
        "weather": "fog"}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


def _fakes(monkeypatch, vlm_up=True):
    """Every create/edit gate passes, the VLM passes every check, and the Z-Image child writes
    solid 1024x640 stills; returns the story-server call list."""
    calls = []

    def _child(spec, loc_dir, step):
        for job in spec["jobs"]:
            Image.new("RGB", (1024, 640), (60, 90, 120)).save(job["output_path"])
        return {"jobs": [{"output_path": j["output_path"], "status": "ok", "seconds": 1.0}
                         for j in spec["jobs"]], "injected_lora_modules": None}

    monkeypatch.setattr(character_dataset, "image_data_url", lambda path, max_side=768: "file:" + path)
    monkeypatch.setattr(character_dataset, "vlm_call", lambda parts, max_tokens=600: json.dumps(PASS))
    monkeypatch.setattr(character_dataset, "run_zimage_child", _child)
    monkeypatch.setattr(character_dataset, "run_edit_child", _child)
    monkeypatch.setattr(character_dataset, "edit_models_missing", lambda: [])
    monkeypatch.setattr(character_dataset, "restore_story_server",
                        lambda wait=False: calls.append("restore") or 0)
    monkeypatch.setattr(character_dataset, "story_server", lambda cmd: calls.append(cmd) or 0)
    monkeypatch.setattr(character_dataset, "wait_for_vlm", lambda timeout_s: True)
    monkeypatch.setattr(character_dataset, "wait_for_avail", lambda gib, timeout_s: True)
    monkeypatch.setattr(character_dataset, "vlm_ready", lambda: vlm_up)
    monkeypatch.setattr(character_dataset, "busy_process", lambda: None)
    monkeypatch.setattr(character_dataset, "story_server_state", lambda: "STOPPED")
    monkeypatch.setattr(character_dataset, "free_gib", lambda path: 100.0)
    return calls


def _photo(tmp_path, name, size=(800, 500), colour=(10, 20, 30)):
    path = str(tmp_path / name)
    Image.new("RGB", size, colour).save(path)
    return path


def _tree(lib):
    return sorted(os.listdir(lib)) if os.path.isdir(lib) else []


def _subprocess(args, env=None, timeout=120):
    return subprocess.run([sys.executable, "-B", TOOL_PATH] + list(args), capture_output=True,
                          text=True, env=env or dict(os.environ), timeout=timeout)


# --- LT1-LT3: help, the stdlib-only list/show, show's output (L1.2) ------------------------

def test_lt1_help(env):
    top = _subprocess(["--help"])
    assert top.returncode == 0
    for command in ("create", "edit", "list", "show"):
        assert command in top.stdout
    create = _subprocess(["create", "--help"])
    assert create.returncode == 0
    for flag in ("--description TEXT", "--photo PATH", "--trigger WORD", "--seed N", "--force",
                 "--regenerate", "--new-seed"):
        assert flag in create.stdout, flag
    assert "3-5 photos" in " ".join(create.stdout.split())
    edit = _subprocess(["edit", "--help"])
    assert edit.returncode == 0 and "--description TEXT" in edit.stdout
    for command in ("list", "show"):
        assert _subprocess([command, "--help"]).returncode == 0


def test_lt2_list_and_show_need_only_the_standard_library(env):
    lt.harbour(env["locations"])
    script = (
        "import importlib.abc, importlib.machinery, sys\n"
        "class Block(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ('PIL', 'psutil', 'character_dataset',\n"
        "                                  'location_dataset', 'character_lib'):\n"
        "            raise ImportError('blocked: ' + name)\n"
        "        return None\n"
        "sys.meta_path.insert(0, Block())\n"
        "m = importlib.machinery.SourceFileLoader('location_tool', %r).load_module()\n"
        "print(m.main(['list']), m.main(['show', 'harbour-street']))\n"
    ) % TOOL_PATH
    proc = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True,
                          env=dict(os.environ), timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[-1] == "0 0"
    assert "harbour-street   harboplc" in proc.stdout


def test_lt3_show(env, capsys):
    lib = env["locations"]
    data = lt.make_location(lib, "old-mill", "oldmiplc", lt.MILL_DESC, source="photos",
                            stills=True)
    ldir = os.path.join(lib, "old-mill")
    open(os.path.join(lib, "old-mill", "contact_sheet.jpg"), "wb").close()
    assert tool.main(["show", "old-mill"]) == 0
    out = capsys.readouterr().out
    record, files = out.split("files:\n")
    assert json.loads(record) == data
    assert files.splitlines() == [
        "  ok       %s" % os.path.join(ldir, "location.json"),
        "  MISSING  %s" % os.path.join(ldir, "photos", "photo_01.png"),
        "  ok       %s" % os.path.join(ldir, "contact_sheet.jpg"),
        "  ok       %s" % os.path.join(ldir, "lora", "video.safetensors"),
        "  ok       %s" % os.path.join(ldir, "lora", "stills.safetensors"),
        "  MISSING  %s" % os.path.join(ldir, "tests", "video_lora.mp4"),
        "  MISSING  %s" % os.path.join(ldir, "tests", "video_control.mp4")]
    lt.harbour(lib, status="dataset")
    assert tool.main(["show", "harbour-street"]) == 0
    assert capsys.readouterr().out.split("files:\n")[1].splitlines() == [
        "  ok       %s" % os.path.join(lib, "harbour-street", "location.json")]
    assert tool.main(["show", "nowhere"]) == 2
    assert capsys.readouterr().err == "Error: unknown location: nowhere (no %s)\n" % (
        os.path.join(lib, "nowhere", "location.json"))
    assert tool.main(["show", "Bad"]) == 2
    assert capsys.readouterr().err == (
        "Error: location name must match [a-z][a-z0-9-]{1,23}, got 'Bad'\n")
    assert tool.main(["list"]) == 0
    assert capsys.readouterr().out.splitlines()[0].startswith("NAME             TRIGGER")


# --- LT4, LT5: argument refusals (L5.1) -----------------------------------------------------

def test_lt4_create_argument_refusals(env, monkeypatch, tmp_path, capsys):
    lib = env["locations"]
    _fakes(monkeypatch)
    lt.harbour(lib, status="dataset")
    ll.register_trigger("harboplc", "harbour-street")
    import character_lib
    character_lib.register_trigger("kyrawmn", "kyra")
    a = _photo(tmp_path, "a.png")
    copy = str(tmp_path / "copy-of-a.png")
    shutil.copy2(a, copy)
    text = str(tmp_path / "notes.png")
    with open(text, "w") as f:
        f.write("not an image")
    small = _photo(tmp_path, "small.png", size=(600, 400))
    missing = str(tmp_path / "missing.png")
    d = ["--description", lt.MILL_DESC]
    cases = [
        (["create", "Bad_Name"] + d,
         "location name must match [a-z][a-z0-9-]{1,23}, got 'Bad_Name'"),
        (["create", "harbour-street"] + d,
         "location harbour-street already exists (%s); use --regenerate to rebuild its dataset"
         % os.path.join(lib, "harbour-street")),
        (["create", "old-mill", "--description", "a quay with boats"],
         "--description: description: must be 15-40 words, got 4"),
        (["create", "old-mill", "--description", "one " + lt.MILL_DESC[3:]],
         '--description: description: must start with "a ", "an " or "the "'),
        (["create", "old-mill", "--description", lt.MILL_DESC.replace(" a slate", ". A slate")],
         "--description: description: must be one noun phrase with no . ! ? or double quote"),
        (["create", "old-mill"], "create needs --description or at least one --photo"),
        (["create", "old-mill"] + ["--photo", a] * 25, "at most 24 --photo, got 25"),
        (["create", "old-mill", "--photo", missing], "--photo not found: %s" % missing),
        (["create", "old-mill", "--photo", small],
         "--photo %s is 600x400; its centred 16:10 crop is 600x375, smaller than the 768x480 "
         "minimum" % small),
        (["create", "old-mill", "--photo", a, "--photo", copy],
         "--photo %s is the same file as photo 1" % copy),
        (["create", "old-mill", "--trigger", "harboplc"] + d,
         "trigger harboplc is already used by location harbour-street; triggers are never reused"),
        (["create", "old-mill", "--trigger", "kyrawmn"] + d,
         "trigger kyrawmn is already used by character kyra; triggers are never reused"),
        (["create", "old-mill", "--trigger", "Bad"] + d,
         "trigger must match [a-z][a-z0-9]{3,15}, got 'Bad'"),
        (["create", "old-mill", "--trigger", "weir"] + d,
         "trigger weir must not be a word of the description"),
        (["create", "old-mill", "--new-seed"] + d, "--new-seed needs --regenerate"),
        (["create", "old-mill", "--seed", "2147483648"] + d,
         "--seed must be between 0 and 2147483647"),
    ]
    before = _tree(lib)
    for argv, message in cases:
        assert tool.main(argv) == 2, argv
        assert capsys.readouterr().err == "Error: %s\n" % message, argv
    assert tool.main(["create", "old-mill", "--photo", text]) == 2
    assert capsys.readouterr().err.startswith("Error: --photo is not a readable image: %s: " % text)
    assert _tree(lib) == before
    with open(os.path.join(lib, ".triggers")) as f:
        assert f.read() == "harboplc harbour-street\n"


def test_lt5_regenerate_refusals(env, monkeypatch, tmp_path, capsys):
    _fakes(monkeypatch)
    lt.harbour(env["locations"], status="untrained")
    with open(os.path.join(env["locations"], "harbour-street", "location.json"), "rb") as f:
        before = f.read()
    flag_message = ("--regenerate takes no --photo or --trigger: a location keeps the photos and "
                    "the trigger it was created with")
    for extra, message in ((["--photo", _photo(tmp_path, "p.png")], flag_message),
                           (["--trigger", "harbtwo"], flag_message),
                           (["--seed", "1", "--new-seed"], "give --seed or --new-seed, not both"),
                           (["--seed", "2147483648"], "--seed must be between 0 and 2147483647"),
                           (["--seed", "-1"], "--seed must be between 0 and 2147483647")):
        assert tool.main(["create", "harbour-street", "--regenerate"] + extra) == 2, extra
        assert capsys.readouterr().err == "Error: %s\n" % message, extra
    assert tool.main(["create", "nowhere", "--regenerate"]) == 2
    assert capsys.readouterr().err.startswith("Error: unknown location: nowhere (no ")
    with open(os.path.join(env["locations"], "harbour-street", "location.json"), "rb") as f:
        assert f.read() == before


# --- LT6: edit (L1.12) ------------------------------------------------------------------------

def test_lt6_edit(env, monkeypatch, capsys):
    lib = env["locations"]
    lt.mill(lib, status="untrained", source="photos")
    lt.harbour(lib, status="untrained")
    new = "The " + lt.TEMPLE_DESC[3:] + "."
    assert tool.main(["edit", "old-mill", "--description", new]) == 0
    assert capsys.readouterr().out == "description: the %s\n" % lt.TEMPLE_DESC[3:]
    assert ll.load_location("old-mill")["description"] == "the " + lt.TEMPLE_DESC[3:]
    assert not os.path.exists(os.path.join(env["lib"], ".lock"))
    assert tool.main(["edit", "harbour-street", "--description", lt.TEMPLE_DESC]) == 2
    assert capsys.readouterr().err == (
        "Error: location harbour-street is a text location: its stills are drawn from its "
        "description; run bin/location create harbour-street --regenerate --description TEXT "
        "(add --force when it is trained)\n")
    assert tool.main(["edit", "old-mill", "--description", "a mill"]) == 2
    assert capsys.readouterr().err == "Error: --description: description: must be 15-40 words, got 2\n"
    os.makedirs(env["lib"], exist_ok=True)
    with open(os.path.join(env["lib"], ".lock"), "w") as f:
        f.write(str(os.getppid()))
    assert tool.main(["edit", "old-mill", "--description", lt.MILL_DESC]) == 2
    assert capsys.readouterr().err == (
        "Error: another bin/character create/train is running (pid %d); run one at a time\n"
        % os.getppid())
    assert ll.load_location("old-mill")["description"] == "the " + lt.TEMPLE_DESC[3:]


# --- LT7, LT8: the re-exec and the signal path (L1.2) ----------------------------------------

def test_lt7_missing_pil_re_executes_under_character_python(env, tmp_path):
    shim = tmp_path / "shim" / "PIL"
    shim.mkdir(parents=True)
    (shim / "__init__.py").write_text("raise ImportError('no PIL here')\n")
    log = str(tmp_path / "reexec.json")
    stub = tmp_path / "fake-python"
    stub.write_text("#!%s\nimport json, os, sys\njson.dump({'argv': sys.argv, 'marker': "
                    "os.environ.get('LOCATION_REEXEC')}, open(%r, 'w'))\n" % (sys.executable, log))
    stub.chmod(0o755)
    run_env = dict(os.environ, PYTHONPATH=str(tmp_path / "shim"), CHARACTER_PYTHON=str(stub))
    run_env.pop("LOCATION_REEXEC", None)
    argv = ["create", "old-mill", "--description", lt.MILL_DESC]
    proc = _subprocess(argv, env=run_env)
    assert proc.returncode == 0, proc.stderr
    with open(log) as f:
        record = json.load(f)
    assert record == {"argv": [str(stub), os.path.realpath(TOOL_PATH)] + argv, "marker": "1"}
    os.remove(log)
    proc = _subprocess(argv, env=dict(run_env, LOCATION_REEXEC="1"))
    assert proc.returncode == 1 and "ImportError: no PIL here" in proc.stderr
    assert not os.path.exists(log)
    listed = _subprocess(["list"], env=run_env)
    assert listed.returncode == 0 and not os.path.exists(log)


def test_lt8_sigterm_during_a_create_exits_130(env, tmp_path):
    marker = str(tmp_path / "waiting")
    driver = tmp_path / "driver.py"
    driver.write_text(
        "import importlib.machinery, os, sys, time\n"
        "sys.path.insert(0, %r)\n"
        "import character_dataset\n"
        "def _slow_ready():\n"
        "    open(%r, 'w').close()\n"
        "    time.sleep(60)\n"
        "    return True\n"
        "character_dataset.vlm_ready = _slow_ready\n"
        "character_dataset.busy_process = lambda: None\n"
        "character_dataset.free_gib = lambda path: 100.0\n"
        "tool = importlib.machinery.SourceFileLoader('location_tool', %r).load_module()\n"
        "sys.exit(tool.run(['create', 'old-mill', '--description', %r]))\n"
        % (WS, marker, TOOL_PATH, lt.MILL_DESC))
    proc = subprocess.Popen([sys.executable, "-B", str(driver)], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=dict(os.environ))
    try:
        deadline = time.monotonic() + 60
        while not os.path.exists(marker):
            assert time.monotonic() < deadline and proc.poll() is None, proc.stderr.read()
            time.sleep(0.05)
        proc.send_signal(signal.SIGTERM)
        _out, err = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 130
    assert err.endswith("location: interrupted\n")
    assert not os.path.exists(os.path.join(env["lib"], ".lock"))
    assert not os.path.exists(os.path.join(env["locations"], "old-mill"))


# --- Review Focus 1, 2 --------------------------------------------------------------------------

def test_review_focus_1_a_new_description_with_the_trigger_is_refused(env, monkeypatch, capsys):
    lib = env["locations"]
    _fakes(monkeypatch)
    lt.mill(lib, status="untrained", source="photos")
    trained = lt.harbour(lib)
    ldir = os.path.join(lib, "harbour-street")
    with open(os.path.join(lib, "old-mill", "location.json"), "rb") as f:
        mill_before = f.read()
    with open(os.path.join(ldir, "location.json"), "rb") as f:
        harbour_before = f.read()
    assert tool.main(["edit", "old-mill", "--description",
                      lt.MILL_DESC.replace("mossy wheel", "oldmiplc wheel")]) == 2
    assert capsys.readouterr().err == (
        "Error: --description: trigger oldmiplc must not be a word of the description\n")
    assert tool.main(["create", "harbour-street", "--regenerate", "--force", "--description",
                      lt.HARBOUR_DESC.replace("granite quays", "harboplc quays")]) == 2
    assert capsys.readouterr().err == (
        "Error: --description: trigger harboplc must not be a word of the description\n")
    with open(os.path.join(lib, "old-mill", "location.json"), "rb") as f:
        assert f.read() == mill_before
    with open(os.path.join(ldir, "location.json"), "rb") as f:
        assert f.read() == harbour_before
    assert os.path.isfile(trained["loras"]["video"]["path"])


def test_review_focus_2_an_accented_place_name_round_trips(env, monkeypatch, capsys):
    _fakes(monkeypatch)
    assert tool.main(["create", "cafe-terrace", "--description", CAFE_DESC]) == 0
    capsys.readouterr()
    data = ll.load_location("cafe-terrace")
    assert (data["description"], data["trigger"], data["status"]) == (
        CAFE_DESC, "cafetplc", "untrained")
    with open(os.path.join(env["locations"], "cafe-terrace", "location.json"), "rb") as f:
        assert "café terrace in Montréal".encode("utf-8") in f.read()
    c_locale = dict(os.environ, LC_ALL="C", LANG="C")
    c_locale.pop("PYTHONIOENCODING", None)
    for argv in (["list"], ["show", "cafe-terrace"]):
        proc = subprocess.run([sys.executable, "-B", TOOL_PATH] + argv, capture_output=True,
                              env=c_locale, timeout=60)
        assert proc.returncode == 0, proc.stderr
        assert CAFE_DESC in proc.stdout.decode("utf-8"), argv
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_dataset.py tests/test_location_tool.py 2>&1 | tail -1
```

Expected: `2 errors` (collection: `location_dataset.py` and `bin/location` do not exist).

- [ ] **Step 3: Implement.**

**3.1.** Create `location_dataset.py` with exactly this content (the Write tool; the file ends with one newline):

```python
#!/usr/bin/env python3
"""location_dataset -- the dataset builder and trainer behind bin/location
(docs/superpowers/specs/2026-10-29-location-lora-design.md, Sections 2 and 3).

A location's dataset is 24 people-free 1024x640 stills: 24 Z-Image text2img stills of the
description (text mode), or the user's photos plus Qwen-Image-Edit-2511 edits of them that change
only the time of day, the weather or the season (photo mode). The vision model checks every
still; the kept ones get a trigger-led caption and a 1-frame mp4. Training reuses
character_dataset.train_video_lora and train_stills_lora.

Top-level imports are stdlib, PIL, character_dataset and location_lib. All
image work runs in character_dataset's own child processes (run_zimage_child, run_edit_child),
so character_dataset.busy_process's markers cover location work. Every gate, VLM call and child
is called through the character_dataset module, so a test fake there applies here too.
"""

import contextlib
import hashlib
import json
import os
import shutil
import sys

from PIL import Image, ImageDraw, ImageOps

WS = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, WS)

import character_dataset  # noqa: E402
import location_lib  # noqa: E402

DatasetError = character_dataset.DatasetError
STYLE = character_dataset.STYLE        # "photorealistic live-action film still, natural light"
WIDTH, HEIGHT = 1024, 640
SEED_MAX = 2147483647
MIN_CROP_W, MIN_CROP_H = 768, 480
DESCRIBE_PHOTOS = 5

# Spec 2.5: the 24 text-mode stills.
TIMES = ("dawn", "midday", "golden hour", "dusk", "night")
WEATHERS = ("clear", "overcast", "rain", "fog", "snow")        # "snow" only from the check
TIME_PHRASES = {"dawn": "at dawn", "midday": "at midday", "golden hour": "at golden hour",
                "dusk": "at dusk", "night": "at night"}
WEATHER_PHRASES = {"clear": "under a clear sky", "overcast": "under an overcast sky",
                   "rain": "in the rain", "fog": "in fog"}
VARIANTS = [
    # (view, time, weather), still n = position
    ("Extreme wide establishing shot", "dawn", "clear"),
    ("Extreme wide establishing shot", "midday", "overcast"),
    ("Extreme wide establishing shot", "golden hour", "fog"),
    ("Extreme wide establishing shot", "night", "fog"),
    ("Wide shot from a high vantage point", "midday", "clear"),
    ("Wide shot from a high vantage point", "dusk", "overcast"),
    ("Wide shot from a high vantage point", "dawn", "fog"),
    ("Wide shot from a high vantage point", "night", "rain"),
    ("Ground-level view looking along the length", "golden hour", "clear"),
    ("Ground-level view looking along the length", "midday", "rain"),
    ("Ground-level view looking along the length", "dusk", "fog"),
    ("Ground-level view looking along the length", "night", "clear"),
    ("Low-angle upward view", "midday", "overcast"),
    ("Low-angle upward view", "dawn", "overcast"),
    ("Low-angle upward view", "dusk", "rain"),
    ("Low-angle upward view", "golden hour", "fog"),
    ("Medium shot of a single detail", "midday", "overcast"),
    ("Medium shot of a single detail", "golden hour", "rain"),
    ("Medium shot of a single detail", "night", "clear"),
    ("Medium shot of a single detail", "dawn", "rain"),
    ("Close-up of a surface texture or sign", "dawn", "clear"),
    ("Close-up of a surface texture or sign", "dusk", "fog"),
    ("Close-up of a surface texture or sign", "golden hour", "overcast"),
    ("Close-up of a surface texture or sign", "night", "rain"),
]


def gen_prompt(view, time, weather, description):
    return "%s of %s, %s, %s, empty of people. %s." % (
        view, description, TIME_PHRASES[time], WEATHER_PHRASES[weather], STYLE)


# Spec 2.6: the photo-mode top-up edits; edit j (1-based) uses EDIT_CONDITIONS[j - 1].
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

# Spec 2.7: the vision model drafts a photo location's description.
DESCRIBE_ATTEMPTS = 3
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

# Spec 2.9: the three check prompts.
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
SCORE_RETRY_EXTRA = ', and an integer from 1 to 10 for "match_score"'
TIME_ALIASES = {"noon": "midday", "day": "midday", "daytime": "midday", "sunrise": "dawn",
                "sunset": "golden hour", "evening": "dusk", "twilight": "dusk"}
WEATHER_ALIASES = {"sunny": "clear", "cloudy": "overcast", "rainy": "rain", "foggy": "fog",
                   "mist": "fog", "misty": "fog", "haze": "fog", "hazy": "fog", "snowy": "snow"}

# Spec 2.12, 6.1: the reason groups of the too-few message, in this order.
REASON_GROUPS = (("people visible", "people visible"), ("score ", "score below 7"),
                 ("blocked by the content screen", "blocked by the content screen"),
                 ("unparseable", "unparseable"))
BLOCKED = "blocked by the content screen"
FORCE_HINT = " (pass --force to keep it)"


def _error(message):
    print("Error: %s" % message, file=sys.stderr)
    return 2


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def still_path(loc_dir, n):
    return os.path.join(loc_dir, "stills", "loc_%02d.png" % n)


def photo_copy_path(loc_dir, k):
    return os.path.join(loc_dir, "photos", "photo_%02d.png" % k)


# ---------------------------------------------------------------------------
# VLM helpers (spec 2.7, 2.9)
# ---------------------------------------------------------------------------

def _image_parts(paths):
    return [{"type": "image_url", "image_url": {"url": character_dataset.image_data_url(p)}}
            for p in paths]


def describe(paths):
    """The vision model's description of the place in the photos at paths (spec 2.7): a
    normalised, valid description. Raises DatasetError after DESCRIBE_ATTEMPTS failures."""
    content = [{"type": "text", "text": DESCRIBE_PROMPT}] + _image_parts(paths)
    reply, error, too_long = None, None, None
    for _attempt in range(DESCRIBE_ATTEMPTS):
        # The call is at temperature 0, so a bare retry repeats the same reply: a too-long
        # description is sent back alone to be shortened, any other rejection is quoted.
        if too_long is not None:
            parts = [{"type": "text", "text": DESCRIBE_SHORTEN % too_long}]
        elif error is not None:
            parts = content + [{"type": "text", "text": DESCRIBE_RETRY % (error, reply)}]
        else:
            parts = content
        reply = character_dataset.vlm_call(parts)
        too_long = None
        try:
            d = character_dataset.extract_json(reply)
            text = d.get("description")
            if not isinstance(text, str):
                raise ValueError('"description" must be a string')
            text = location_lib.normalize_description(text)
            if len(text.split()) > location_lib.DESCRIPTION_MAX_WORDS:
                too_long = text
            location_lib.validate_description(text)
            return text
        except (ValueError, location_lib.LocationError) as e:
            error = e
    raise DatasetError("describe failed: %s; last reply: %r" % (error, reply))


def validate_location_check(d, scored):
    """The normalised check of spec 2.9: {"match_score": int or None, "people_visible": bool,
    "shot", "time_of_day", "weather"}. Raises ValueError on any malformed reply."""
    score = None
    if scored:
        if "match_score" not in d:
            raise ValueError("missing key: match_score")
        score = d["match_score"]
        if isinstance(score, bool) or not isinstance(score, int):
            raise ValueError("match_score must be an integer, got %r" % (score,))
        if not 1 <= score <= 10:
            raise ValueError("match_score must be 1-10, got %d" % score)
    if not isinstance(d.get("people_visible"), bool):
        raise ValueError("people_visible must be true or false, got %r" % (d.get("people_visible"),))
    out = {"match_score": score, "people_visible": d["people_visible"]}
    for key, aliases, allowed in (("shot", character_dataset.SHOT_ALIASES, character_dataset.SHOTS),
                                  ("time_of_day", TIME_ALIASES, TIMES),
                                  ("weather", WEATHER_ALIASES, WEATHERS)):
        value = d.get(key)
        if not isinstance(value, str):
            raise ValueError("%s must be a string, got %r" % (key, value))
        value = value.lower().strip()
        value = aliases.get(value, value)
        if value not in allowed:
            raise ValueError("%s %r is not one of %s" % (key, value, ", ".join(allowed)))
        out[key] = value
    return out


def check_still(prompt, paths, scored):
    """(check, None), or (None, "unparseable: <error>") after CHECK_ATTEMPTS unparseable replies
    (spec 2.9). A RuntimeError from the VLM call propagates."""
    content = [{"type": "text", "text": prompt}] + _image_parts(paths)
    extra = SCORE_RETRY_EXTRA if scored else ""
    reply, error = None, None
    for _attempt in range(character_dataset.CHECK_ATTEMPTS):
        parts = content if error is None else content + [
            {"type": "text", "text": CHECK_RETRY % (error, reply, extra)}]
        reply = character_dataset.vlm_call(parts)
        try:
            return validate_location_check(character_dataset.extract_json(reply), scored), None
        except ValueError as e:
            error = e
    return None, "unparseable: %s" % error


def caption(trigger, check):
    """The training caption of a kept still (spec 2.9); check None is a forced unparseable
    photo."""
    if check is None:
        return "%s, %s." % (trigger, STYLE)
    parts = [trigger] + [v for v in (check["shot"], check["time_of_day"], check["weather"]) if v]
    if check["people_visible"] is False:
        parts.append("empty of people")
    return ", ".join(parts) + ", " + STYLE + "."


# ---------------------------------------------------------------------------
# The contact sheet (spec 2.11)
# ---------------------------------------------------------------------------

def write_contact_sheet(items, stills_dir, out_path):
    """5 columns of 256x160 thumbnails, each with a 20-px label row, under a 24-px banner; a
    dropped cell is outlined in red, a missing still is a black cell."""
    cols, tw, th, lh, banner = 5, 256, 160, 20, 24
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, banner + rows * (th + lh)), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    kept = sum(1 for item in items if item["kept"])
    draw.text((4, 6), "kept %d of %d (need %d)" % (kept, len(items), location_lib.MIN_KEEP),
              fill=(255, 255, 255))
    for k, item in enumerate(items):
        x, y = (k % cols) * tw, banner + (k // cols) * (th + lh)
        path = os.path.join(stills_dir, "loc_%02d.png" % item["n"])
        if os.path.isfile(path):
            with Image.open(path) as img:
                sheet.paste(img.convert("RGB").resize((tw, th), Image.LANCZOS), (x, y))
        if not item["kept"]:
            draw.rectangle([x, y, x + tw - 1, y + th - 1], outline=(255, 0, 0), width=4)
        draw.text((x + 4, y + th + 3), cell_label(item), fill=(255, 255, 255))
    sheet.save(out_path, format="JPEG", quality=90)


def cell_label(item):
    score = "s%d" % item["match_score"] if item["match_score"] is not None else "s-"
    verdict = "kept" if item["kept"] else (item["reason"] or "")[:28]
    return "%02d %s %s %s" % (item["n"], item["source"][0].upper(), score, verdict)


# ---------------------------------------------------------------------------
# Building the dataset (spec 2.5, 2.6, 2.8-2.12)
# ---------------------------------------------------------------------------

def _with_story_server_stopped(min_gib, work):
    """Stop the story server, wait for min_gib available, run work(), and restore the server in
    a finally: detached after an interrupt, else with --wait and a wait for the VLM (spec 2.6
    step 6; character_dataset.py:980-1008)."""
    interrupted = False
    rc = character_dataset.story_server("stop")
    if rc != 0:
        print("warning: story-server stop returned %d" % rc, file=sys.stderr)
    try:
        if not character_dataset.wait_for_avail(min_gib, character_dataset.AVAIL_WAIT_S):
            raise DatasetError("timed out waiting for %d GiB available memory after stopping the "
                               "story server" % min_gib)
        work()
    except (KeyboardInterrupt, EOFError):
        interrupted = True
        raise
    finally:
        if interrupted:
            character_dataset.restore_story_server()
        else:
            rc = character_dataset.restore_story_server(wait=True)
            if rc != 0:
                print("warning: story-server-restore %s --wait returned %d"
                      % (character_dataset.VLM_SERVE_MODE, rc), file=sys.stderr)
            if not character_dataset.wait_for_vlm(character_dataset.VLM_WAIT_S):
                raise DatasetError("timed out waiting for the vision server to come back")


def _plan(data, loc_dir):
    """[{"n", "source", "photo", "prompt"}] for the 24 stills, and the image child to run:
    ("generate", spec), ("edit", spec) or (None, None)."""
    if data["source"] == "text":
        plan = [{"n": n, "source": "generated", "photo": None,
                 "prompt": gen_prompt(view, time, weather, data["description"])}
                for n, (view, time, weather) in enumerate(VARIANTS, start=1)]
        jobs = [{"prompt": e["prompt"], "output_path": still_path(loc_dir, e["n"]),
                 "seed": data["seed"], "width": WIDTH, "height": HEIGHT} for e in plan]
        return plan, ("generate", {"jobs": jobs, "loras": None})
    p = len(data["photos"])
    plan = [{"n": k, "source": "photo", "photo": k, "prompt": None} for k in range(1, p + 1)]
    for j in range(1, location_lib.TOTAL_STILLS - p + 1):
        plan.append({"n": p + j, "source": "edit", "photo": ((j - 1) % p) + 1,
                     "prompt": EDIT_PROMPT % EDIT_CONDITIONS[j - 1]})
    edits = [e for e in plan if e["source"] == "edit"]
    if not edits:
        return plan, (None, None)
    jobs = [{"image": still_path(loc_dir, e["photo"]), "prompt": e["prompt"],
             "output_path": still_path(loc_dir, e["n"]), "seed": data["seed"], "width": WIDTH,
             "height": HEIGHT} for e in edits]
    spec = {"image": jobs[0]["image"], "skill": "location_edit",
            "model": character_dataset.EDIT_MODEL, "lora_repo": character_dataset.EDIT_LORA_REPO,
            "lora_file": character_dataset.EDIT_LORA_FILE, "steps": character_dataset.EDIT_STEPS,
            "true_cfg": character_dataset.EDIT_TRUE_CFG, "jobs": jobs}
    return plan, ("edit", spec)


def _check_entry(data, loc_dir, entry, force):
    """The manifest item of one still (spec 2.9, 2.10)."""
    item = {"n": entry["n"], "source": entry["source"], "photo": entry["photo"],
            "prompt": entry["prompt"], "match_score": None, "people_visible": None, "shot": "",
            "time_of_day": "", "weather": "", "kept": False, "reason": None, "caption": None}
    png = still_path(loc_dir, entry["n"])
    if not os.path.isfile(png):
        item["reason"] = BLOCKED
        return item
    if entry["source"] == "generated":
        check, unparseable = check_still(
            CHECK_TEXT_PROMPT.replace("@@DESCRIPTION@@", data["description"]), [png], True)
    elif entry["source"] == "edit":
        check, unparseable = check_still(CHECK_PHOTO_PROMPT, [still_path(loc_dir, 1), png], True)
    else:
        check, unparseable = check_still(TAG_PROMPT, [png], False)
    if check is not None:
        for key in ("match_score", "people_visible", "shot", "time_of_day", "weather"):
            item[key] = check[key]
    if entry["source"] == "photo":
        problem = unparseable if check is None else (
            "people visible" if check["people_visible"] else None)
        if problem is None:
            item["kept"] = True
        elif force:
            item["kept"], item["reason"] = True, "kept by --force: " + problem
        else:
            item["reason"] = problem + FORCE_HINT
    elif check is None:
        item["reason"] = unparseable
    elif check["match_score"] < location_lib.MIN_SCORE:
        item["reason"] = "score %d" % check["match_score"]
    elif check["people_visible"]:
        item["reason"] = "people visible"
    else:
        item["kept"] = True
    if item["kept"]:
        item["caption"] = caption(data["trigger"], check)
        with open(os.path.join(loc_dir, "captions", "loc_%02d.txt" % entry["n"]), "w",
                  encoding="utf-8") as f:
            f.write(item["caption"])
        mp4 = os.path.join(loc_dir, "videos", "loc_%02d.mp4" % entry["n"])
        character_dataset.wrap_still(png, mp4)
        character_dataset.verify_ffprobe(mp4)
    return item


def reason_counts(items):
    """The too-few message's counts by reason, e.g. "5 people visible, 4 score below 7"."""
    counts = []
    for prefix, label in REASON_GROUPS:
        n = sum(1 for item in items if not item["kept"] and (item["reason"] or "").startswith(prefix))
        if n:
            counts.append("%d %s" % (n, label))
    return ", ".join(counts)


def build_dataset(data, force=False):
    """Make, check, caption and wrap the 24 stills of location.json data; write manifest.json,
    contact_sheet.jpg and the updated location.json. Returns 0, 1 (a DatasetError or
    RuntimeError, printed, or an abort; status stays "dataset") or 3 (fewer than MIN_KEEP kept)."""
    try:
        return _build_dataset(data, force)
    except (DatasetError, RuntimeError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nError: aborted; the stills made so far are kept in %s; run bin/location create "
              "%s --regenerate to start again"
              % (location_lib.location_dir(data["name"]), data["name"]), file=sys.stderr)
        return 1


def _build_dataset(data, force):
    name = data["name"]
    loc_dir = location_lib.location_dir(name)
    plan, (child, spec) = _plan(data, loc_dir)
    for k in range(1, len(data["photos"]) + 1):
        with Image.open(photo_copy_path(loc_dir, k)) as img:
            ImageOps.fit(img.convert("RGB"), (WIDTH, HEIGHT), Image.LANCZOS,
                         centering=(0.5, 0.5)).save(still_path(loc_dir, k))
    if child == "generate":
        print("=== generate: %d stills ===" % len(spec["jobs"]), flush=True)
        _with_story_server_stopped(character_dataset.GENERATE_MIN_AVAIL_GIB, lambda: (
            character_dataset.run_zimage_child(spec, loc_dir, "generate")))
    elif child == "edit":
        print("=== edit: %d stills ===" % len(spec["jobs"]), flush=True)
        _with_story_server_stopped(character_dataset.EDIT_MIN_AVAIL_GIB, lambda: (
            character_dataset.run_edit_child(spec, loc_dir, "edit")))

    print("=== check ===", flush=True)
    items = [_check_entry(data, loc_dir, entry, force) for entry in plan]
    photo_mode = data["source"] == "photos"
    manifest = {"source": data["source"], "trigger": data["trigger"],
                "description": data["description"], "seed": data["seed"],
                "min_score": location_lib.MIN_SCORE, "reference": "loc_01" if photo_mode else None,
                "generator": ("Z-Image" if not photo_mode
                              else "%s + %s, %d steps" % (character_dataset.EDIT_MODEL,
                                                          character_dataset.EDIT_LORA_FILE,
                                                          character_dataset.EDIT_STEPS)
                              if child == "edit" else "photos only"),
                "items": items}
    with open(os.path.join(loc_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    sheet = os.path.join(loc_dir, "contact_sheet.jpg")
    write_contact_sheet(items, os.path.join(loc_dir, "stills"), sheet)

    kept = sum(1 for item in items if item["kept"])
    data["dataset"] = {"kept": kept, "total": location_lib.TOTAL_STILLS,
                       "min_score": location_lib.MIN_SCORE, "contact_sheet": sheet}
    data["status"] = "untrained" if kept >= location_lib.MIN_KEEP else "dataset"
    location_lib.write_location(data)

    print("%-4s %-6s %-5s %s" % ("n", "score", "kept", "caption"))
    for item in items:
        print("%-4d %-6s %-5s %s" % (item["n"], "-" if item["match_score"] is None
                                     else item["match_score"], str(item["kept"]),
                                     item["caption"] or "(dropped: %s)" % item["reason"]))
    print("dataset: %d/%d stills kept (minimum %d) in %s"
          % (kept, location_lib.TOTAL_STILLS, location_lib.MIN_KEEP, loc_dir))
    print("contact sheet: %s" % sheet)
    if kept < location_lib.MIN_KEEP:
        if photo_mode:
            fix = ("create a new location with more photos that show no people, or run "
                   "bin/location create %s --regenerate --new-seed (--force keeps photos that "
                   "show people)" % name)
        else:
            fix = ("run bin/location create %s --regenerate --new-seed, or --regenerate "
                   "--description TEXT with a clearer description" % name)
        print("Error: only %d/%d stills kept (need %d): %s; the dataset is kept in %s; %s"
              % (kept, location_lib.TOTAL_STILLS, location_lib.MIN_KEEP, reason_counts(items),
                 loc_dir, fix), file=sys.stderr)
        return 3
    print("next: review the contact sheet, then run bin/location train %s" % name)
    return 0


# ---------------------------------------------------------------------------
# create, regenerate, edit (spec 2.12)
# ---------------------------------------------------------------------------

def _load_photos(paths):
    """([(absolute path, oriented RGB image, sha256)], None) or (None, error message) for the
    --photo paths (spec 2.6 step 1)."""
    import ltx_image_fit
    if len(paths) > location_lib.MAX_PHOTOS:
        return None, "at most 24 --photo, got %d" % len(paths)
    loaded, seen = [], {}
    for k, given in enumerate(paths, start=1):
        path = os.path.abspath(given)
        if not os.path.isfile(path):
            return None, "--photo not found: %s" % path
        try:
            img = ltx_image_fit.load_oriented_rgb(path)
        except Exception as e:
            return None, "--photo is not a readable image: %s: %s" % (path, e)
        w, h = img.size
        crop_w, crop_h = min(w, h * 16 // 10), min(h, w * 10 // 16)
        if crop_w < MIN_CROP_W or crop_h < MIN_CROP_H:
            return None, ("--photo %s is %dx%d; its centred 16:10 crop is %dx%d, smaller than the "
                          "768x480 minimum" % (path, w, h, crop_w, crop_h))
        sha = _sha256(path)
        if sha in seen:
            return None, "--photo %s is the same file as photo %d" % (path, seen[sha])
        seen[sha] = k
        loaded.append((path, img, sha))
    return loaded, None


def _edit_models_problem():
    missing = character_dataset.edit_models_missing()
    if not missing:
        return None
    return ("the photo editor is not downloaded: %s; download it with: %s"
            % (", ".join(missing), "; ".join("hf download %s" % m for m in missing)))


def _gates(stack):
    """The lock, busy, disk and VLM preflights of spec 2.12 create step 5, holding the lock on
    stack; the error message, or None when every one passes."""
    try:
        stack.enter_context(character_dataset.library_lock())
    except DatasetError as e:
        return str(e)
    busy = character_dataset.busy_process()
    if busy is not None:
        return ("a render or training process is running (pid %d: %s); bin/location never trains "
                "or generates concurrently with a render" % busy)
    lib = location_lib.library_dir()
    free = character_dataset.free_gib(lib)
    if free < character_dataset.CREATE_MIN_FREE_GIB:
        return "only %.1f GiB free at %s; create needs 2 GiB" % (free, lib)
    if not character_dataset.vlm_ready():
        return ("the vision model %s is not being served at %s; start it with: bin/story-server %s"
                % (character_dataset.VLM_MODEL, character_dataset.MODELS_URL,
                   character_dataset.VLM_SERVE_MODE))
    return None


def _description_arg(text, trigger=None):
    """(normalised description, None) or (None, error message) for --description TEXT."""
    description = location_lib.normalize_description(text)
    try:
        location_lib.validate_description(description)
        if trigger is not None:
            location_lib.validate_trigger(trigger, description)
    except location_lib.LocationError as e:
        return None, "--description: %s" % e
    return description, None


def create(args):
    """bin/location create NAME (spec 2.12). Returns 0, 1, 2 or 3."""
    name = args.name
    try:
        location_lib.validate_name(name)
    except location_lib.LocationError as e:
        return _error(e)
    if args.regenerate:
        return _regenerate(args)
    if args.new_seed:
        return _error("--new-seed needs --regenerate")
    loc_dir = location_lib.location_dir(name)
    if os.path.exists(loc_dir):
        return _error("location %s already exists (%s); use --regenerate to rebuild its dataset"
                      % (name, loc_dir))
    photos, problem = _load_photos(args.photos or [])
    if problem:
        return _error(problem)
    description = None
    if args.description is not None:
        description, problem = _description_arg(args.description)
        if problem:
            return _error(problem)
    if not photos and description is None:
        return _error("create needs --description or at least one --photo")
    seed = args.seed if args.seed is not None else 0
    if not 0 <= seed <= SEED_MAX:
        return _error("--seed must be between 0 and 2147483647")
    if args.trigger is not None:
        try:
            location_lib.validate_trigger(args.trigger, description)
        except location_lib.LocationError as e:
            return _error(e)
        owner = location_lib.all_triggers().get(args.trigger)
        if owner is not None:
            return _error("trigger %s is already used by %s; triggers are never reused"
                          % (args.trigger, owner))
    if photos and len(photos) < location_lib.TOTAL_STILLS:
        problem = _edit_models_problem()
        if problem:
            return _error(problem)

    with contextlib.ExitStack() as stack:
        problem = _gates(stack)
        if problem:
            return _error(problem)
        if description is None:
            try:
                description = describe([p for p, _img, _sha in photos[:DESCRIBE_PHOTOS]])
            except (DatasetError, RuntimeError) as e:
                print("Error: %s" % e, file=sys.stderr)
                return 1
            print("description (drafted by the vision model; change it with bin/location edit %s "
                  "--description TEXT): %s" % (name, description))
        if args.trigger is not None:
            try:
                location_lib.validate_trigger(args.trigger, description)
            except location_lib.LocationError as e:
                return _error(e)
            trigger = args.trigger
        else:
            trigger = location_lib.auto_trigger(name, description,
                                                set(location_lib.all_triggers()))
        subs = ["stills", "captions", "videos", "logs"] + (["photos"] if photos else [])
        for sub in subs:
            os.makedirs(os.path.join(loc_dir, sub), exist_ok=True)
        for k, (_path, img, _sha) in enumerate(photos, start=1):
            img.save(photo_copy_path(loc_dir, k), format="PNG")
        location_lib.register_trigger(trigger, name)
        data = {"schema_version": location_lib.SCHEMA_VERSION, "name": name, "trigger": trigger,
                "description": description, "source": "photos" if photos else "text",
                "photos": [{"path": path, "sha256": sha} for path, _img, sha in photos],
                "seed": seed, "status": "dataset", "created_at": location_lib.utc_now(),
                "trained_at": None, "dataset": None, "loras": {"video": None, "stills": None},
                "stills_skip_reason": None, "strength": None}
        location_lib.write_location(data)
        return build_dataset(data, args.force)


def _regenerate(args):
    """create NAME --regenerate (spec 2.12): every refusal before the lock leaves location.json
    untouched; the new seed and description are persisted only under the lock."""
    name = args.name
    try:
        data = location_lib.load_location(name)
    except location_lib.LocationError as e:
        return _error(e)
    if args.photos or args.trigger is not None:
        return _error("--regenerate takes no --photo or --trigger: a location keeps the photos and "
                      "the trigger it was created with")
    if args.seed is not None and args.new_seed:
        return _error("give --seed or --new-seed, not both")
    if args.seed is not None and not 0 <= args.seed <= SEED_MAX:
        return _error("--seed must be between 0 and 2147483647")
    description = data["description"]
    if args.description is not None:
        if data["source"] == "photos":
            return _error("a photo location's stills come from its photos; change its description "
                          "with bin/location edit %s --description TEXT" % name)
        description, problem = _description_arg(args.description, data["trigger"])
        if problem:
            return _error(problem)
    if data["status"] == "trained" and not args.force:
        return _error("location %s is trained; regenerating its dataset deletes its LoRAs. Pass "
                      "--force to regenerate it anyway" % name)
    if data["source"] == "photos" and len(data["photos"]) < location_lib.TOTAL_STILLS:
        problem = _edit_models_problem()
        if problem:
            return _error(problem)
    old_seed = data["seed"]
    if args.new_seed:
        new_seed = 0 if old_seed >= SEED_MAX else old_seed + 1
    elif args.seed is not None:
        new_seed = args.seed
    else:
        new_seed = old_seed
    loc_dir = location_lib.location_dir(name)

    with contextlib.ExitStack() as stack:
        problem = _gates(stack)
        if problem:
            return _error(problem)
        if data["status"] == "trained":
            for sub in ("lora", "tests", "train"):
                shutil.rmtree(os.path.join(loc_dir, sub), ignore_errors=True)
            data["loras"] = {"video": None, "stills": None}
            data["trained_at"] = None
            data["stills_skip_reason"] = None
        data["seed"], data["description"] = new_seed, description
        data["status"], data["dataset"] = "dataset", None
        location_lib.write_location(data)
        print("seed: %d -> %d" % (old_seed, new_seed) if new_seed != old_seed
              else "seed: %d (unchanged)" % old_seed)
        for sub in ("stills", "captions", "videos"):
            shutil.rmtree(os.path.join(loc_dir, sub), ignore_errors=True)
            os.makedirs(os.path.join(loc_dir, sub))
        for rel in ("manifest.json", "contact_sheet.jpg"):
            with contextlib.suppress(FileNotFoundError):
                os.remove(os.path.join(loc_dir, rel))
        os.makedirs(os.path.join(loc_dir, "logs"), exist_ok=True)
        return build_dataset(data, args.force)


def edit(args):
    """bin/location edit NAME --description TEXT (spec 2.12): a photo location's new
    description, saved under the library lock. Returns 0 or 2."""
    name = args.name
    try:
        data = location_lib.load_location(name)
    except location_lib.LocationError as e:
        return _error(e)
    if data["source"] == "text":
        return _error("location %s is a text location: its stills are drawn from its description; "
                      "run bin/location create %s --regenerate --description TEXT (add --force "
                      "when it is trained)" % (name, name))
    description, problem = _description_arg(args.description, data["trigger"])
    if problem:
        return _error(problem)
    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(character_dataset.library_lock())
        except DatasetError as e:
            return _error(e)
        data = location_lib.load_location(name)
        data["description"] = description
        location_lib.write_location(data)
    print("description: %s" % description)
    return 0
```

**3.2.** Create `bin/location` with exactly this content (the Write tool; the file ends with one newline):

```python
#!/usr/bin/env python3
"""location -- build, train and inspect the location LoRA library (generated/locations/).

  bin/location create NAME [--description TEXT] [--photo PATH ...] [--trigger WORD] [--seed N]
                           [--force]
  bin/location create NAME --regenerate [--seed N | --new-seed] [--description TEXT] [--force]
  bin/location edit NAME --description TEXT
  bin/location list
  bin/location show NAME

create builds a location's 24-still people-free dataset and stops for review (contact_sheet.jpg).
Without --photo the 24 stills are drawn from --description by Z-Image. With --photo (1-24 photos)
the stills are the photos plus Qwen-Image-Edit-2511 edits of them that change only the time of
day, the weather or the season: angles come only from the photos, so 3-5 photos taken from
different spots are recommended; without --description the vision model drafts one from the first
5 photos. edit saves a photo location's new description. list and show read the library only. A
trained location is pinned in a movie with bin/ltx-movie --location NAME.

Exit codes: 0 success, 1 runtime failure, 2 argument or precondition failure, 3 create kept fewer
than 12 stills.

list/show import location_lib only (stdlib); create and edit import location_dataset, which needs
PIL and psutil: without them bin/location re-executes itself under $CHARACTER_PYTHON (default
~/img-gen/bin/python). See docs/superpowers/specs/2026-10-29-location-lora-design.md.
"""

import argparse
import json
import os
import signal
import sys

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import location_lib  # noqa: E402

ANGLES_NOTE = ("Angles come only from the photos: every extra still keeps one photo's exact "
               "viewpoint and changes only its time of day, weather or season, so 3-5 photos "
               "taken from different spots are recommended.")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="location",
        description="Build, train and inspect the location LoRA library (generated/locations/).")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True
    p = sub.add_parser("create", help="build a location's 24-still dataset and stop for review",
                       description="Build a location's 24-still people-free dataset. "
                                   + ANGLES_NOTE)
    p.add_argument("name", metavar="NAME")
    p.add_argument("--description", default=None, metavar="TEXT",
                   help="the place's persistent features: one noun phrase of 15-40 words that "
                        "starts with a, an or the (required without --photo; drafted by the "
                        "vision model from the first 5 photos when omitted)")
    p.add_argument("--photo", dest="photos", action="append", default=None, metavar="PATH",
                   help="a photo of the place (repeatable, 1-24). " + ANGLES_NOTE)
    p.add_argument("--trigger", default=None, metavar="WORD")
    p.add_argument("--seed", type=int, default=None, metavar="N")
    p.add_argument("--force", action="store_true",
                   help="keep user photos that show people or whose check is unparseable; with "
                        "--regenerate, also regenerate a trained location, deleting its LoRAs")
    p.add_argument("--regenerate", action="store_true",
                   help="rebuild an existing location's dataset")
    p.add_argument("--new-seed", dest="new_seed", action="store_true",
                   help="with --regenerate: use the stored seed + 1")
    e = sub.add_parser("edit", help="save a photo location's new description")
    e.add_argument("name", metavar="NAME")
    e.add_argument("--description", required=True, metavar="TEXT")
    sub.add_parser("list", help="list every location")
    s = sub.add_parser("show", help="print one location's record and file status")
    s.add_argument("name", metavar="NAME")
    return parser


def cmd_list():
    print("\n".join(location_lib.location_table_lines()))
    return 0


def cmd_show(name):
    try:
        data = location_lib.load_location(name)
    except location_lib.LocationError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print("files:")
    loc_dir = location_lib.location_dir(name)
    paths = [location_lib.location_json_path(name)]
    paths += [os.path.join(loc_dir, "photos", "photo_%02d.png" % k)
              for k in range(1, len(data["photos"]) + 1)]
    if data["dataset"] is not None:
        paths.append(data["dataset"]["contact_sheet"])
    for kind in ("video", "stills"):
        if data["loras"][kind] is not None:
            paths.append(data["loras"][kind]["path"])
    if data["loras"]["video"] is not None:
        paths += [os.path.join(loc_dir, "tests", "video_lora.mp4"),
                  os.path.join(loc_dir, "tests", "video_control.mp4")]
    for p in paths:
        print("  %-8s %s" % ("ok" if os.path.isfile(p) else "MISSING", p))
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "list":
        return cmd_list()
    if args.command == "show":
        return cmd_show(args.name)
    try:
        import PIL  # noqa: F401
        import psutil  # noqa: F401
    except ImportError:
        # A venv's python is a symlink to its base interpreter, so the marker (not a path
        # comparison) is what stops a second re-exec.
        py = os.environ.get("CHARACTER_PYTHON", os.path.expanduser("~/img-gen/bin/python"))
        if os.access(py, os.X_OK) and not os.environ.get("LOCATION_REEXEC"):
            os.environ["LOCATION_REEXEC"] = "1"
            os.execv(py, [py, os.path.realpath(__file__)]
                     + (sys.argv[1:] if argv is None else list(argv)))
        raise
    import location_dataset
    if args.command == "create":
        return location_dataset.create(args)
    return location_dataset.edit(args)


def _interrupt(signum, frame):
    raise KeyboardInterrupt


def run(argv=None):
    """The command-line entry: SIGINT, SIGTERM and SIGHUP raise KeyboardInterrupt (as
    bin/character), so the image child is killed and the story server restored; an interrupt
    that reaches this level prints "location: interrupted" and returns 130."""
    # SIGINT too: a job started in the background by a script inherits SIGINT ignored, and
    # Python then never installs its own Ctrl-C handler.
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _interrupt)
    try:
        return main(argv)
    except KeyboardInterrupt:
        print("location: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(run())
```

Then make the new tool executable (a mode change, not a content change):

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
chmod 755 bin/location
ls -l bin/location | cut -c1-10    # expected: -rwxr-xr-x
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_dataset.py tests/test_location_tool.py 2>&1 | tail -1
```

Expected: `32 passed` (about 35 seconds; the dataset tests wrap stills with the real ffmpeg). Run the compile check with `FILES` = `location_dataset.py bin/location tests/test_location_dataset.py tests/test_location_tool.py`; expected: `compiled 4` twice. Then run the gate block with `N=4`. Expected: `GATE PASS`, `new-file tests 49, not passing 0`, `baseline failures still failing 2 of 2`, `OK 347/347`, and the one listed `test_mut26` LOST line.

- [ ] **Step 5: Commit.**

```bash
git add location_dataset.py bin/location tests/test_location_dataset.py tests/test_location_tool.py
git diff --cached --name-only    # expected: those 4 paths
git commit -m "feat(location): bin/location create, regenerate, edit, list and show: text and photo datasets, the vision check, captions, manifest and contact sheet (L1.2-L1.12, L5.1; LD1-LD17, LD24, LT1-LT8, Review Focus 1, 2)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Training: `location_dataset.train`, `bin/location train`, `bin/location-train-vlm` (L2.1-L2.5; LD19-LD23, LT1b, LT9, LT10)

This task implements:
- L2.1: `bin/location train NAME [--video] [--stills] [--force]` (neither flag means both) and `bin/location-train-vlm <python> <name> [flags]`. The wrapper's body is `bin/character-train-vlm` with every `character-train-vlm` replaced by `location-train-vlm` and the command `"$PY" "$DIR/location" train "$@"`; its header comment names the location training (Plan ruling LR22).
- L2.2: `train(args)` with the preflights in the spec's order, each exit 2 with the character text, `bin/character` replaced by `bin/location`.
- L2.3: `_train_video` through `character_dataset.train_video_lora`, with the prompt `"<trigger>, wide establishing shot at dusk, empty of people."`, the failed note `location NAME stays STATUS`, the six-key `loras.video` (base `dgrauet/ltx-2.3-mlx-q8`), `trained_at`, status `trained`, and the four printed lines.
- L2.4: `_train_stills` through `character_dataset.train_stills_lora`, with the kept `loc_NN` pairs in manifest order, the six-key `loras.stills` (base `Tongyi-MAI/Z-Image-Turbo`) and `stills_skip_reason` (set on a compat reject, cleared on success).
- L2.5 needs no code here: Task 9 audio-strips location LoRAs at render.

**Files:**
- Modify: `location_dataset.py` (Task 4's file: the docstring's import sentence, the imports, after `FORCE_HINT`, the end of the file), `bin/location` (Task 4's file: the usage lines, the docstring, the parser, `main`).
- Create: `bin/location-train-vlm` (mode 755).
- Modify: `tests/test_location_dataset.py`, `tests/test_location_tool.py` (append).
- Read only: `character_dataset.py` (`train(args)` `:1491-1566`, `TRAIN_MIN_AVAIL_GIB` and `TRAIN_MIN_FREE_GIB_PER_KIND` `:195-196`, `TRAIN_MODEL_DIR`/`TEST_MODEL_DIR` `:201-202`, `MFLUX_TRAIN` `:209-210`, `stills_epochs` `:1573-1578`, `stills_train_config` `:1581-1604`), `bin/character-train-vlm` (`:1-40`).

**Interfaces:**
- Consumes: Task 3's `train_video_lora` and `train_stills_lora`; Task 2's `load_location`, `write_location`, `location_dir`, `utc_now`, `VIDEO_BASE_MODEL`, `STILLS_BASE_MODEL`; `character_dataset.psutil` (the same module as `location_dataset.psutil`), `character_dataset.TRAIN_MODEL_DIR`, `TEST_MODEL_DIR`, `SKILL.LTX2_MLX_BIN`, `MFLUX_TRAIN`, `TRAIN_MIN_AVAIL_GIB`, `TRAIN_MIN_FREE_GIB_PER_KIND`.
- Produces, in `location_dataset`: `TEST_PROMPT = "%s, wide establishing shot at dusk, empty of people."`, `SKIP_INSTALL_HINT`, `_train_video(data) -> outcome`, `_train_stills(data) -> outcome`, `train(args) -> 0 | 1 | 2` (`args`: `name`, `video`, `stills`, `force`).
- Produces, in `bin/location`: the `train` subcommand. In `bin/location-train-vlm`: the wrapper.

- [ ] **Step 1: Write the failing tests.**

**1.1.** Edit `tests/test_location_dataset.py`: replace this text, which occurs exactly once:

```python
    assert fakes.child_specs[0][0]["jobs"][0]["image"] == os.path.join(mdir, "stills", "loc_01.png")
```

with:

```python
    assert fakes.child_specs[0][0]["jobs"][0]["image"] == os.path.join(mdir, "stills", "loc_01.png")


# --- Task 5 helpers: a location ready to train, and the training fakes ------------------------

def _untrained_location(env, kept=21):
    """An untrained harbour-street with a real dataset layout: 24 tiny stills, and captions,
    1-frame "videos" and manifest items for the kept ones (n 1..kept)."""
    ldir = os.path.join(env["locations"], "harbour-street")
    for sub in ("stills", "captions", "videos"):
        os.makedirs(os.path.join(ldir, sub), exist_ok=True)
    items = []
    for n in range(1, 25):
        Image.new("RGB", (8, 8), (n, n, n)).save(os.path.join(ldir, "stills", "loc_%02d.png" % n))
        if n <= kept:
            with open(os.path.join(ldir, "captions", "loc_%02d.txt" % n), "w") as f:
                f.write("harboplc, wide shot, n %d" % n)
            with open(os.path.join(ldir, "videos", "loc_%02d.mp4" % n), "wb") as f:
                f.write(b"mp4")
        items.append({"n": n, "kept": n <= kept})
    with open(os.path.join(ldir, "manifest.json"), "w") as f:
        json.dump({"items": items}, f)
    data = lt.harbour(env["locations"], status="untrained")
    data["dataset"]["kept"] = kept
    ll.write_location(data)
    return data


def _fake_video_tools(monkeypatch, preprocess_rc=0):
    """run_logged and SKILL.generate_video fakes (tests/test_character_dataset.py:579-614);
    returns the recorded calls."""
    record = {"run": [], "generate": []}

    def _run(cmd, log_path, cwd, env, timeout_s):
        record["run"].append({"cmd": cmd, "cwd": cwd, "env": env})
        if cmd[1] == "preprocess":
            out_dir = cmd[cmd.index("-o") + 1]
            latent_dir = os.path.join(out_dir, ".precomputed", "latents")
            os.makedirs(latent_dir)
            for i in range(len(os.listdir(cmd[cmd.index("--videos") + 1]))):
                open(os.path.join(latent_dir, "l%02d.safetensors" % i), "wb").close()
            return preprocess_rc
        ckpt_dir = os.path.join(os.path.dirname(cmd[cmd.index("--config") + 1]), "out",
                                "checkpoints")
        os.makedirs(ckpt_dir)
        with open(os.path.join(ckpt_dir, character_dataset.VIDEO_FINAL_CKPT), "wb") as f:
            f.write(b"lora")
        return 0

    def _generate(prompt, output_path, **kwargs):
        record["generate"].append(dict(kwargs, prompt=prompt, output_path=output_path))
        with open(output_path, "wb") as f:
            f.write(b"mp4")
        return output_path

    monkeypatch.setattr(character_dataset, "run_logged", _run)
    monkeypatch.setattr(character_dataset.SKILL, "generate_video", _generate)
    return record


def _fake_stills_tools(monkeypatch, injected=2):
    """run_logged (mflux-train) and run_zimage_child fakes (tests/test_character_dataset.py:
    968-998); returns the recorded calls."""
    import struct
    import zipfile
    record = {"run": [], "children": []}
    keys = ["layers.0.attention.to_q.lora_A.weight", "layers.0.attention.to_q.lora_B.weight",
            "layers.0.attention.to_k.lora_A.weight", "layers.0.attention.to_k.lora_B.weight"]
    header = {"__metadata__": {"format": "pt"}}
    for i, key in enumerate(keys):
        header[key] = {"dtype": "F32", "shape": [1], "data_offsets": [4 * i, 4 * i + 4]}
    raw = json.dumps(header).encode("utf-8")
    adapter = struct.pack("<Q", len(raw)) + raw + b"\0" * 16

    def _run(cmd, log_path, cwd, env, timeout_s):
        record["run"].append({"cmd": cmd, "cwd": cwd, "env": env})
        with open(cmd[cmd.index("--config") + 1]) as f:
            config = json.load(f)
        out = config["checkpoint"]["output_path"]
        zip_path = os.path.join(out, "checkpoints",
                                "%07d_checkpoint.zip" % config["checkpoint"]["save_frequency"])
        os.makedirs(os.path.dirname(zip_path))
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("0000672_adapter.safetensors", adapter)
        return 0

    def _child(spec, loc_dir, step):
        record["children"].append((spec, step))
        for job in spec["jobs"]:
            Image.new("RGB", (16, 10), (1, 2, 3)).save(job["output_path"])
        return {"jobs": [{"output_path": j["output_path"], "status": "ok", "seconds": 1.0}
                         for j in spec["jobs"]],
                "injected_lora_modules": injected if spec["loras"] else None}

    monkeypatch.setattr(character_dataset, "run_logged", _run)
    monkeypatch.setattr(character_dataset, "run_zimage_child", _child)
    return record


class _Memory(object):
    def __init__(self, available):
        self.available = available


def _train_ready(monkeypatch, tmp_path):
    """Every train preflight passes: no busy process, server STOPPED, 64 GiB available, 100 GiB
    free, a valid dev-model dir, a test-model dir and executable stub binaries."""
    dev = tmp_path / "dev-model"
    dev.mkdir(parents=True)
    (dev / "transformer-dev.safetensors").write_bytes(b"dev")
    test_model = tmp_path / "test-model"
    test_model.mkdir(parents=True)
    stub = tmp_path / "stub-bin"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    monkeypatch.setattr(character_dataset, "busy_process", lambda: None)
    monkeypatch.setattr(character_dataset, "story_server_state", lambda: "STOPPED")
    monkeypatch.setattr(character_dataset.psutil, "virtual_memory", lambda: _Memory(64.0 * 2 ** 30))
    monkeypatch.setattr(character_dataset, "free_gib", lambda path: 100.0)
    monkeypatch.setattr(character_dataset, "TRAIN_MODEL_DIR", str(dev))
    monkeypatch.setattr(character_dataset, "TEST_MODEL_DIR", str(test_model))
    monkeypatch.setattr(character_dataset.SKILL, "LTX2_MLX_BIN", str(stub))
    monkeypatch.setattr(character_dataset, "MFLUX_TRAIN", str(stub))
    monkeypatch.setattr(ll, "utc_now", lambda: "2026-10-29T12:34:56Z")
    return dev


def _train_args(video=False, stills=False, force=False):
    return argparse.Namespace(command="train", name="harbour-street", video=video, stills=stills,
                              force=force)


# --- LD19-LD23: training (L2.2-L2.4) ----------------------------------------------------------

def test_ld19_the_train_preflight_order(env, monkeypatch, tmp_path, capsys):
    _untrained_location(env)
    ldir = os.path.join(env["locations"], "harbour-street")

    def _never(*args):
        raise AssertionError("a training core ran")

    def _case(name, override, message):
        with monkeypatch.context() as m:
            dev = _train_ready(m, tmp_path / name)
            m.setattr(character_dataset, "train_video_lora", _never)
            m.setattr(character_dataset, "train_stills_lora", _never)
            override(m, dev)
            assert ld.train(_train_args()) == 2, name
        assert capsys.readouterr().err == "Error: " + message + "\n", name

    lock = os.path.join(env["lib"], ".lock")

    def _hold_lock(m, dev):
        os.makedirs(env["lib"], exist_ok=True)
        with open(lock, "w") as f:
            f.write(str(os.getppid()))

    _case("lock", _hold_lock, "another bin/character create/train is running (pid %d); run one "
          "at a time" % os.getppid())
    os.remove(lock)
    _case("busy", lambda m, dev: m.setattr(character_dataset, "busy_process",
                                           lambda: (4242, "python3 bin/ltx-mlx-render m.json")),
          "a render or training process is running (pid 4242: python3 bin/ltx-mlx-render "
          "m.json); bin/location never trains or generates concurrently with a render")
    _case("server", lambda m, dev: m.setattr(character_dataset, "story_server_state",
                                             lambda: "SERVING mlx-vision"),
          "the story server is SERVING mlx-vision; stop it first with bin/story-server stop "
          "(training needs its memory)")

    def _server_and_memory(m, dev):
        m.setattr(character_dataset, "story_server_state", lambda: "UNKNOWN")
        m.setattr(character_dataset.psutil, "virtual_memory", lambda: _Memory(29.9 * 2 ** 30))

    _case("order", _server_and_memory, "the story server is UNKNOWN; stop it first with "
          "bin/story-server stop (training needs its memory)")
    _case("memory", lambda m, dev: m.setattr(character_dataset.psutil, "virtual_memory",
                                             lambda: _Memory(29.9 * 2 ** 30)),
          "only 29.9 GiB of memory is available; training needs 30 GiB (quit memory-heavy apps "
          "and retry)")
    _case("disk", lambda m, dev: m.setattr(character_dataset, "free_gib", lambda path: 15.9),
          "only 15.9 GiB free at %s; training video and stills needs 16 GiB" % ldir)
    _case("dev", lambda m, dev: (dev / "transformer-distilled.safetensors").write_bytes(b"x"),
          "%s must contain transformer-dev.safetensors and neither transformer.safetensors nor "
          "transformer-distilled.safetensors (the trainer would pick those first)"
          % (tmp_path / "dev" / "dev-model"))
    _case("test-model", lambda m, dev: m.setattr(character_dataset, "TEST_MODEL_DIR",
                                                 str(tmp_path / "nowhere")),
          "test-render model not found: %s" % (tmp_path / "nowhere"))
    _case("binary", lambda m, dev: m.setattr(character_dataset.SKILL, "LTX2_MLX_BIN",
                                             str(tmp_path / "no-bin")),
          "ltx-2-mlx binary not found or not executable: %s" % (tmp_path / "no-bin"))
    assert not os.path.exists(lock)
    data = ll.load_location("harbour-street")
    data["status"], data["dataset"] = "dataset", None
    ll.write_location(data)
    assert ld.train(_train_args()) == 2
    assert capsys.readouterr().err == (
        "Error: location harbour-street has no accepted dataset (status dataset, 0 of 24 stills "
        "kept, need 12); fix it with bin/location create harbour-street --regenerate\n")
    data["dataset"] = {"kept": 9, "total": 24, "min_score": 7,
                       "contact_sheet": os.path.join(ldir, "contact_sheet.jpg")}
    ll.write_location(data)
    assert ld.train(_train_args()) == 2
    assert "(status dataset, 9 of 24 stills kept, need 12)" in capsys.readouterr().err


def test_ld20_the_video_lora(env, monkeypatch, tmp_path, capsys):
    _untrained_location(env)
    ldir = os.path.join(env["locations"], "harbour-street")
    _train_ready(monkeypatch, tmp_path)
    record = _fake_video_tools(monkeypatch)
    assert ld.train(_train_args(video=True)) == 0
    data = ll.load_location("harbour-street")
    lora = os.path.join(ldir, "lora", "video.safetensors")
    assert data["loras"]["video"] == {"path": lora, "sha256": ld._sha256(lora),
                                      "base_model": "dgrauet/ltx-2.3-mlx-q8", "rank": 32,
                                      "alpha": 32, "steps": 1000}
    assert (data["status"], data["trained_at"], data["loras"]["stills"]) == (
        "trained", "2026-10-29T12:34:56Z", None)
    preprocess, train = record["run"]
    assert preprocess["cmd"][preprocess["cmd"].index("--videos") + 1] == os.path.join(ldir, "videos")
    assert preprocess["cmd"][preprocess["cmd"].index("--captions") + 1] == os.path.join(ldir,
                                                                                    "captions")
    with open(os.path.join(ldir, "train", "video", "train.yaml")) as f:
        assert '"harboplc, wide establishing shot at dusk, empty of people."' in f.read()
    first, second = record["generate"]
    prompt = "harboplc, wide establishing shot at dusk, empty of people."
    assert (first["prompt"], first["loras"], first["width"], first["height"], first["num_frames"],
            first["seed"], first["model"]) == (prompt, [(lora, 1.0)], 512, 320, 25, 42,
                                               character_dataset.TEST_MODEL_DIR)
    assert first["output_path"] == os.path.join(ldir, "tests", "video_lora.mp4")
    assert "loras" not in second and second["output_path"] == os.path.join(ldir, "tests",
                                                                            "video_control.mp4")
    out = capsys.readouterr().out
    assert ("video LoRA: %s (sha256 %s)\ntrigger-only A/B (compare by eye; the LoRA clip should "
            "show the place, the control a different place):\n  with LoRA: %s\n  control:   %s\n"
            % (lora, ld._sha256(lora), first["output_path"], second["output_path"])) in out
    _fake_video_tools(monkeypatch, preprocess_rc=1)
    assert ld.train(_train_args(video=True, force=True)) == 1
    err = capsys.readouterr().err
    assert "Error: video LoRA training failed at preprocess (exit 1); log: " in err
    assert err.endswith("; location harbour-street stays trained\n")


def test_ld21_the_stills_lora(env, monkeypatch, tmp_path):
    data = _untrained_location(env, kept=21)
    data["stills_skip_reason"] = "mflux-train not found at /x"
    ll.write_location(data)
    ldir = os.path.join(env["locations"], "harbour-street")
    _train_ready(monkeypatch, tmp_path)
    record = _fake_stills_tools(monkeypatch)
    assert ld.train(_train_args(stills=True)) == 0
    data = ll.load_location("harbour-street")
    stills = os.path.join(ldir, "lora", "stills.safetensors")
    steps = character_dataset.stills_epochs(21)[1]
    assert data["loras"]["stills"] == {"path": stills, "sha256": ld._sha256(stills),
                                       "base_model": "Tongyi-MAI/Z-Image-Turbo", "rank": 16,
                                       "alpha": 16, "steps": steps}
    assert (data["stills_skip_reason"], data["status"]) == (None, "untrained")
    data_dir = os.path.join(ldir, "train", "stills", "data")
    assert sorted(os.listdir(data_dir)) == sorted(
        ["loc_%02d.png" % n for n in range(1, 22)] + ["loc_%02d.txt" % n for n in range(1, 22)]
        + ["preview_1.txt"])
    with open(os.path.join(ldir, "train", "stills", "train.json")) as f:
        assert json.load(f) == character_dataset.stills_train_config(
            data_dir, os.path.join(ldir, "train", "stills", "out"), 0, 21)
    (gate, gate_step), (control, control_step) = record["children"]
    assert (gate_step, control_step) == ("test-stills-lora", "test-stills-control")
    assert gate["jobs"][0]["prompt"] == "harboplc, wide establishing shot at dusk, empty of people."
    assert os.path.isfile(os.path.join(ldir, "tests", "stills_lora.png"))


def test_ld22_a_compat_reject_keeps_the_location_usable(env, monkeypatch, tmp_path, capsys):
    _untrained_location(env)
    ldir = os.path.join(env["locations"], "harbour-street")
    _train_ready(monkeypatch, tmp_path)
    _fake_video_tools(monkeypatch)
    video_run = character_dataset.run_logged
    _fake_stills_tools(monkeypatch, injected=1)
    stills_run = character_dataset.run_logged
    monkeypatch.setattr(character_dataset, "run_logged", lambda cmd, *rest: (
        stills_run if cmd[1] == "--config" else video_run)(cmd, *rest))
    assert ld.train(_train_args()) == 0
    data = ll.load_location("harbour-street")
    assert os.path.isfile(os.path.join(ldir, "lora", "stills.rejected.safetensors"))
    assert not os.path.exists(os.path.join(ldir, "lora", "stills.safetensors"))
    assert data["stills_skip_reason"] == (
        "mflux adapter incompatible with z_image_skill: only 1 of 2 LoRA modules in the adapter "
        "matched the Z-Image transformer")
    assert (data["status"], data["loras"]["stills"]) == ("trained", None)
    assert data["loras"]["video"] is not None
    assert ("stills LoRA skipped: %s; the video LoRA is unaffected" % data["stills_skip_reason"]
            in capsys.readouterr().out)
    pin = ll.resolve_locations(["harbour-street"])[0]
    assert (pin.stills_lora, pin.stills_skip_reason) == (None, data["stills_skip_reason"])
    assert ld.train(_train_args(stills=True)) == 1


def test_ld23_a_retrain_needs_force(env, monkeypatch, tmp_path, capsys):
    data = lt.harbour(env["locations"], stills=True)
    _train_ready(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(character_dataset, "train_video_lora",
                        lambda *args: calls.append("video") or "ok")
    monkeypatch.setattr(character_dataset, "train_stills_lora",
                        lambda *args: calls.append("stills") or "ok")
    assert ld.train(_train_args(video=True)) == 2
    assert capsys.readouterr().err == (
        "Error: location harbour-street already has a video LoRA (%s); pass --force to retrain "
        "it\n" % data["loras"]["video"]["path"])
    assert ld.train(_train_args()) == 2 and calls == []
    capsys.readouterr()
    assert ld.train(_train_args(video=True, force=True)) == 0
    assert calls == ["video"]
    assert ll.load_location("harbour-street")["loras"]["stills"] == data["loras"]["stills"]
```

**1.2.** Edit `tests/test_location_tool.py`: replace this text, which occurs exactly once:

```python
        assert CAFE_DESC in proc.stdout.decode("utf-8"), argv
```

with:

```python
        assert CAFE_DESC in proc.stdout.decode("utf-8"), argv


# --- LT9, LT10: bin/location-train-vlm and train's kinds (L2.1, L2.2) -------------------------

def test_lt1b_train_help(env):
    proc = _subprocess(["train", "--help"])
    assert proc.returncode == 0
    for flag in ("--video", "--stills", "--force"):
        assert flag in proc.stdout, flag


def _vlm_wrapper_bin(tmp_path, location_body):
    """A temporary bin/ holding a copy of bin/location-train-vlm and stub story-server,
    story-server-restore and location scripts that log their arguments to calls.log."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shutil.copy2(os.path.join(WS, "bin", "location-train-vlm"), str(bindir / "location-train-vlm"))
    log = tmp_path / "calls.log"
    for name, body in (("story-server", 'echo "story-server $*" >> %s\n' % log),
                       ("story-server-restore", 'echo "story-server-restore $*" >> %s\n' % log),
                       ("location", 'echo "location $*" >> %s\n%s' % (log, location_body))):
        path = bindir / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)
    return str(bindir / "location-train-vlm"), log


def test_lt9_location_train_vlm(env, tmp_path):
    with open(os.path.join(WS, "bin", "location-train-vlm"), encoding="utf-8") as f:
        script = f.read().split("\n")
    with open(os.path.join(WS, "bin", "character-train-vlm"), encoding="utf-8") as f:
        character = f.read().split("\n")
    assert script[1].startswith("# location-train-vlm -- run a location training")
    assert script[5:] == [line.replace("character-train-vlm", "location-train-vlm").replace(
        '"$PY" "$DIR/character" train "$@"', '"$PY" "$DIR/location" train "$@"')
        for line in character[5:]]
    assert os.access(os.path.join(WS, "bin", "location-train-vlm"), os.X_OK)
    for rc in (0, 1):
        case = tmp_path / ("rc%d" % rc)
        case.mkdir()
        wrapper, log = _vlm_wrapper_bin(case, "exit %d\n" % rc)
        proc = subprocess.run(["/bin/bash", wrapper, "/bin/sh", "harbour-street", "--video"],
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == rc, proc.stderr
        assert log.read_text().splitlines() == ["story-server stop",
                                                "location train harbour-street --video",
                                                "story-server-restore mlx-vision --wait"]
        assert "location-train-vlm: training exited %d" % rc in proc.stderr
    case = tmp_path / "signal"
    case.mkdir()
    marker = case / "running"
    wrapper, log = _vlm_wrapper_bin(case, "touch %s\nsleep 30\n" % marker)
    proc = subprocess.Popen(["/bin/bash", wrapper, "/bin/sh", "harbour-street"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        deadline = time.monotonic() + 30
        while not marker.exists():
            assert time.monotonic() < deadline
            time.sleep(0.05)
        os.killpg(proc.pid, signal.SIGTERM)
        _out, err = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
    assert proc.returncode == 130
    assert "location-train-vlm: interrupted; restarting the VLM in the background" in err
    assert log.read_text().splitlines() == ["story-server stop", "location train harbour-street",
                                            "story-server-restore mlx-vision"]


def test_lt10_train_with_neither_flag_trains_both(env, monkeypatch, tmp_path, capsys):
    lt.harbour(env["locations"], status="untrained")
    ldir = os.path.join(env["locations"], "harbour-street")
    with open(os.path.join(ldir, "manifest.json"), "w") as f:
        json.dump({"items": [{"n": n, "kept": n <= 21} for n in range(1, 25)]}, f)
    dev = tmp_path / "dev-model"
    dev.mkdir()
    (dev / "transformer-dev.safetensors").write_bytes(b"dev")
    stub = tmp_path / "stub-bin"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    monkeypatch.setattr(character_dataset, "busy_process", lambda: None)
    monkeypatch.setattr(character_dataset, "story_server_state", lambda: "STOPPED")
    monkeypatch.setattr(character_dataset.psutil, "virtual_memory",
                        lambda: type("M", (), {"available": 64.0 * 2 ** 30})())
    monkeypatch.setattr(character_dataset, "TRAIN_MODEL_DIR", str(dev))
    monkeypatch.setattr(character_dataset, "TEST_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(character_dataset.SKILL, "LTX2_MLX_BIN", str(stub))
    monkeypatch.setattr(character_dataset, "MFLUX_TRAIN", str(stub))
    calls = []

    def _video_core(owner_dir, videos, captions, prompt, note, recorded, tested):
        calls.append("video")
        if len(calls) == 1:
            return "failed"
        path = os.path.join(owner_dir, "lora", "video.safetensors")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"lora")
        recorded({"path": path, "sha256": "0" * 64, "rank": 32, "alpha": 32, "steps": 1000})
        return "test_failed"

    monkeypatch.setattr(character_dataset, "train_video_lora", _video_core)
    monkeypatch.setattr(character_dataset, "train_stills_lora",
                        lambda *args: calls.append("stills") or "ok")
    monkeypatch.setattr(character_dataset, "free_gib", lambda path: 15.9)
    assert tool.main(["train", "harbour-street"]) == 2
    assert capsys.readouterr().err == (
        "Error: only 15.9 GiB free at %s; training video and stills needs 16 GiB\n" % ldir)
    assert tool.main(["train", "harbour-street", "--video"]) == 1
    assert calls == ["video"]
    monkeypatch.setattr(character_dataset, "free_gib", lambda path: 16.0)
    assert tool.main(["train", "harbour-street"]) == 1
    assert calls == ["video", "video", "stills"]
    assert ll.load_location("harbour-street")["status"] == "trained"
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_dataset.py tests/test_location_tool.py 2>&1 | tail -1
```

Expected: `8 failed, 32 passed` (LD19-LD23: `train` does not exist; LT1b: no `train` subcommand; LT9: no `bin/location-train-vlm`; LT10: no `train` subcommand).

- [ ] **Step 3: Implement.**

**3.1.** Edit `location_dataset.py`: replace this text, which occurs exactly once:

```python
Top-level imports are stdlib, PIL, character_dataset and location_lib. All
```

with:

```python
Top-level imports are stdlib, PIL, psutil, character_dataset and location_lib. All
```

**3.2.** Edit `location_dataset.py`: replace this text, which occurs exactly once:

```python
import shutil
import sys

from PIL import Image, ImageDraw, ImageOps
```

with:

```python
import shutil
import sys

import psutil
from PIL import Image, ImageDraw, ImageOps
```

**3.3.** Edit `location_dataset.py`: replace this text, which occurs exactly once:

```python
FORCE_HINT = " (pass --force to keep it)"
```

with:

```python
FORCE_HINT = " (pass --force to keep it)"
# Spec 3.3, 3.4: the trigger-only test prompt of both LoRAs.
TEST_PROMPT = "%s, wide establishing shot at dusk, empty of people."
SKIP_INSTALL_HINT = ("install mflux as described in "
                     "docs/superpowers/specs/2026-10-05-character-library-design.md section 4.10")
```

**3.4.** Edit `location_dataset.py`: replace this text, which occurs exactly once:

```python
    print("description: %s" % description)
    return 0
```

with:

```python
    print("description: %s" % description)
    return 0


# ---------------------------------------------------------------------------
# train (spec 3.1-3.4)
# ---------------------------------------------------------------------------

def _train_video(data):
    """The video LoRA through character_dataset.train_video_lora (spec 3.3). Returns its
    outcome."""
    name = data["name"]
    loc_dir = location_lib.location_dir(name)
    clips = {}

    def recorded(entry):
        data["loras"]["video"] = {"path": entry["path"], "sha256": entry["sha256"],
                                  "base_model": location_lib.VIDEO_BASE_MODEL,
                                  "rank": entry["rank"], "alpha": entry["alpha"],
                                  "steps": entry["steps"]}
        data["trained_at"] = location_lib.utc_now()
        data["status"] = "trained"
        location_lib.write_location(data)

    def tested(key, path):
        clips[key] = path

    outcome = character_dataset.train_video_lora(
        loc_dir, os.path.join(loc_dir, "videos"), os.path.join(loc_dir, "captions"),
        TEST_PROMPT % data["trigger"], "location %s stays %s" % (name, data["status"]),
        recorded, tested)
    if outcome == "failed":
        return outcome
    entry = data["loras"]["video"]
    print("video LoRA: %s (sha256 %s)" % (entry["path"], entry["sha256"]))
    print("trigger-only A/B (compare by eye; the LoRA clip should show the place, the control a "
          "different place):")
    print("  with LoRA: %s" % clips.get("sample_path"))
    print("  control:   %s" % clips.get("control_path"))
    return outcome


def _train_stills(data):
    """The stills LoRA through character_dataset.train_stills_lora (spec 3.4). Returns its
    outcome."""
    loc_dir = location_lib.location_dir(data["name"])
    with open(os.path.join(loc_dir, "manifest.json"), encoding="utf-8") as f:
        kept_ns = [item["n"] for item in json.load(f)["items"] if item["kept"]]
    pairs = [(still_path(loc_dir, n), os.path.join(loc_dir, "captions", "loc_%02d.txt" % n))
             for n in kept_ns]

    def kept_ok(entry, sample_path, control_path):
        data["loras"]["stills"] = {"path": entry["path"], "sha256": entry["sha256"],
                                   "base_model": location_lib.STILLS_BASE_MODEL,
                                   "rank": entry["rank"], "alpha": entry["alpha"],
                                   "steps": entry["steps"]}
        data["stills_skip_reason"] = None
        location_lib.write_location(data)

    def skipped(reason):
        data["stills_skip_reason"] = reason
        location_lib.write_location(data)

    return character_dataset.train_stills_lora(loc_dir, pairs, TEST_PROMPT % data["trigger"],
                                               data["seed"], kept_ok, skipped)


def train(args):
    """bin/location train NAME (spec 3.2). Returns 0, 1 or 2."""
    name = args.name
    try:
        data = location_lib.load_location(name)
    except location_lib.LocationError as e:
        return _error(e)
    if data["status"] == "dataset":
        kept = data["dataset"]["kept"] if data["dataset"] else 0
        return _error("location %s has no accepted dataset (status dataset, %d of 24 stills kept, "
                      "need 12); fix it with bin/location create %s --regenerate"
                      % (name, kept, name))
    requested = [k for k in ("video", "stills") if getattr(args, k)] or ["video", "stills"]
    explicit_stills = args.stills
    for kind in requested:
        if data["loras"][kind] is not None and not args.force:
            return _error("location %s already has a %s LoRA (%s); pass --force to retrain it"
                          % (name, kind, data["loras"][kind]["path"]))
    loc_dir = location_lib.location_dir(name)

    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(character_dataset.library_lock())
        except DatasetError as e:
            return _error(e)
        busy = character_dataset.busy_process()
        if busy is not None:
            return _error("a render or training process is running (pid %d: %s); bin/location "
                          "never trains or generates concurrently with a render" % busy)
        state = character_dataset.story_server_state()
        if state != "STOPPED":
            return _error("the story server is %s; stop it first with bin/story-server stop "
                          "(training needs its memory)" % state)
        avail = psutil.virtual_memory().available / 2 ** 30
        if avail < character_dataset.TRAIN_MIN_AVAIL_GIB:
            return _error("only %.1f GiB of memory is available; training needs 30 GiB (quit "
                          "memory-heavy apps and retry)" % avail)
        need = character_dataset.TRAIN_MIN_FREE_GIB_PER_KIND * len(requested)
        free = character_dataset.free_gib(loc_dir)
        if free < need:
            return _error("only %.1f GiB free at %s; training %s needs %d GiB"
                          % (free, loc_dir, " and ".join(requested), need))
        if "video" in requested:
            model_dir = character_dataset.TRAIN_MODEL_DIR
            if (not os.path.isfile(os.path.join(model_dir, "transformer-dev.safetensors"))
                    or os.path.exists(os.path.join(model_dir, "transformer.safetensors"))
                    or os.path.exists(os.path.join(model_dir,
                                                   "transformer-distilled.safetensors"))):
                return _error("%s must contain transformer-dev.safetensors and neither "
                              "transformer.safetensors nor transformer-distilled.safetensors "
                              "(the trainer would pick those first)" % model_dir)
            if not os.path.isdir(character_dataset.TEST_MODEL_DIR):
                return _error("test-render model not found: %s" % character_dataset.TEST_MODEL_DIR)
            binary = character_dataset.SKILL.LTX2_MLX_BIN
            if not (os.path.isfile(binary) and os.access(binary, os.X_OK)):
                return _error("ltx-2-mlx binary not found or not executable: %s" % binary)

        stills_outcome = "ok"
        mflux = character_dataset.MFLUX_TRAIN
        if "stills" in requested and not (os.path.isfile(mflux) and os.access(mflux, os.X_OK)):
            data["stills_skip_reason"] = "mflux-train not found at %s" % mflux
            location_lib.write_location(data)
            print("stills LoRA skipped: %s; %s" % (data["stills_skip_reason"], SKIP_INSTALL_HINT))
            requested.remove("stills")
            stills_outcome = "skipped"

        video_outcome = "ok"
        if "video" in requested:
            video_outcome = _train_video(data)
            if video_outcome == "failed":
                return 1
        if "stills" in requested:
            stills_outcome = _train_stills(data)
        if (video_outcome == "test_failed" or stills_outcome == "failed"
                or (stills_outcome == "skipped" and explicit_stills)):
            return 1
        return 0
```

**3.5.** Edit `bin/location`: replace this text, which occurs exactly once:

```python
  bin/location edit NAME --description TEXT
```

with:

```python
  bin/location train NAME [--video] [--stills] [--force]
  bin/location edit NAME --description TEXT
```

**3.6.** Edit `bin/location`: replace this text, which occurs exactly once:

```python
5 photos. edit saves a photo location's new description. list and show read the library only. A
trained location is pinned in a movie with bin/ltx-movie --location NAME.
```

with:

```python
5 photos. train trains the video LoRA (ltx-2-mlx) and, when mflux is installed and its adapter
passes the compat gate, the stills LoRA; neither flag means both. edit saves a photo location's
new description. list and show read the library only. A trained location is pinned in a movie
with bin/ltx-movie --location NAME.
```

**3.7.** Edit `bin/location`: replace this text, which occurs exactly once:

```python
list/show import location_lib only (stdlib); create and edit import location_dataset, which needs
```

with:

```python
list/show import location_lib only (stdlib); create, train and edit import location_dataset, which needs
```

**3.8.** Edit `bin/location`: replace this text, which occurs exactly once:

```python
    e = sub.add_parser("edit", help="save a photo location's new description")
```

with:

```python
    t = sub.add_parser("train", help="train the video LoRA and/or the stills LoRA")
    t.add_argument("name", metavar="NAME")
    t.add_argument("--video", action="store_true")
    t.add_argument("--stills", action="store_true")
    t.add_argument("--force", action="store_true", help="retrain a LoRA that already exists")
    e = sub.add_parser("edit", help="save a photo location's new description")
```

**3.9.** Edit `bin/location`: replace this text, which occurs exactly once:

```python
    if args.command == "create":
        return location_dataset.create(args)
    return location_dataset.edit(args)
```

with:

```python
    if args.command == "create":
        return location_dataset.create(args)
    if args.command == "edit":
        return location_dataset.edit(args)
    return location_dataset.train(args)
```

**3.10.** Create `bin/location-train-vlm` with exactly this content (the Write tool; the file ends with one newline):

```bash
#!/bin/bash
# location-train-vlm -- run a location training with the VLM stopped (training reuses
# its ~34 GB), then ALWAYS bring the VLM back. This lets the movie-ui Locations tab's Train
# button train without a manual `story-server stop` / restart: bin/location train's
# story-server gate stays a safety net, because we stop the VLM before training.
#
# Usage: location-train-vlm <python> <name> [--video] [--stills] [--force]
# The VLM is restarted on success, failure, OR cancellation (SIGINT/SIGTERM).
set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
SS="$DIR/story-server"

# story-server-restore starts the VLM in its own session, so a movie-ui Cancel (which kills
# every process group of this job) cannot take the restarted server down with it. On a signal
# it returns at once (the start continues detached) so the job exits inside the cancel grace.
restart_vlm() {
  echo "location-train-vlm: restarting the VLM (story-server mlx-vision)" >&2
  "$DIR/story-server-restore" mlx-vision --wait >/dev/null 2>&1 \
    || echo "location-train-vlm: WARNING: VLM restart failed; run 'bin/story-server mlx-vision'" >&2
}
on_signal() {
  trap - EXIT INT TERM
  echo "location-train-vlm: interrupted; restarting the VLM in the background" >&2
  "$DIR/story-server-restore" mlx-vision >/dev/null 2>&1
  exit 130
}
trap restart_vlm EXIT
trap on_signal INT TERM

[ "$#" -ge 2 ] || { echo "usage: location-train-vlm <python> <name> [--video] [--stills] [--force]" >&2; exit 2; }
PY="$1"; shift

echo "location-train-vlm: stopping the VLM to free memory for training"
"$SS" stop >/dev/null 2>&1 || true

"$PY" "$DIR/location" train "$@"
rc=$?
echo "location-train-vlm: training exited $rc" >&2
exit "$rc"   # the EXIT trap restarts the VLM
```

Then make the wrapper executable:

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
chmod 755 bin/location-train-vlm
ls -l bin/location-train-vlm | cut -c1-10    # expected: -rwxr-xr-x
bash -n bin/location-train-vlm && echo "bash ok"
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_dataset.py tests/test_location_tool.py 2>&1 | tail -1
```

Expected: `40 passed`. Run the compile check with `FILES` = `location_dataset.py bin/location tests/test_location_dataset.py tests/test_location_tool.py`; expected: `compiled 4` twice. Then run the gate block with `N=5`. Expected: `GATE PASS`, `new-file tests 57, not passing 0`, `baseline failures still failing 2 of 2`, `OK 347/347`, and the listed `test_mut26` line.

- [ ] **Step 5: Commit.**

```bash
git add location_dataset.py bin/location bin/location-train-vlm tests/test_location_dataset.py tests/test_location_tool.py
git diff --cached --name-only    # expected: those 5 paths
git commit -m "feat(location): bin/location train and location-train-vlm: the video and stills LoRAs through the character training cores (L2.1-L2.5; LD19-LD23, LT1b, LT9, LT10)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The planner: fixed places, `l1..lK`, P21 and the L4 count (L3.3-L3.6; LS2-LS6, LS8-LS14)

This task implements:
- L3.3: `StoryContext` gains a last field `locations` (defaults `(True, None, None, None, ())`); `PLAN_PROMPT_TEMPLATE`'s `"background.\n"` becomes `"background.@@LOCATION_FIXED@@\n"`; `LOCATION_FIXED_INTRO`, `LOCATION_FIXED_LINE` and `FIXED_SETTING` follow `CAST_FIXED_LINE`; `build_plan_prompt` fills `@@LOCATION_FIXED@@` right after `@@CAST_FIXED@@`. Without pins the token becomes `""`, so every prompt is byte-identical (LS1).
- L3.4: `normalize_plan` sets `location_name: None` on every raw location when pins exist, replaces or inserts the pinned `l1..lK` with `FIXED_SETTING % description`, and maps a beat location written as a pinned library name (any case) to its id.
- L3.5: P21 before the SA2 block, the `plan_checks` docstring, and the fatal filter `("P1", "P2", "P16", "P17", "P21")` with its comment. `plan_round` already retries it; `_VIOLATION_RE` already parses it.
- L3.6: `lora_checks` counts `location NAME` for a beat at an attached pin, between the per-beat picks and the characters.

`story_engine.py` gains no import (LS14). LS7 (the end-to-end retry through `bin/ltx-movie`) belongs to Task 10, because it needs `--location`.

**Files:**
- Modify: `story_engine.py`: `StoryContext` (`:97-98`) and its comment (`:106-107`), the template (`:338`), after `CAST_FIXED_LINE` (`:1060`), `build_plan_prompt`'s cast block (`:1077-1078`) and fragments (`:1104`), `normalize_plan` (`:1267-1268`, `:1286-1287`), the `plan_checks` docstring (`:2095-2096`), before SA2 (`:2246`), `lora_checks` (`:2375-2381`), the fatal filter (`:4638-4640`).
- Modify: `tests/test_location_story.py` (Task 1's file: the imports, the loaders, the end of the file).

**Interfaces:**
- Consumes: Task 2's `location_lib.LocationPin` (tests only; `story_engine` reads `.name`, `.description`, `.attach_video` by attribute); `seu.plan_json`, `seu.panel_json`, `seu.make_ctx`, `seu.script_agent`, `seu.answer`, `seu.agent_log`, `seu.HARBOUR`, `seu.TEMPLE`, `seu.catalog_entry`, `seu.lora_file`.
- Produces, in `story_engine`: `StoryContext(..., locations=())`, `LOCATION_FIXED_INTRO`, `LOCATION_FIXED_LINE`, `FIXED_SETTING`; plan location entries gain `"location_name"` (only with pins); `plan_checks` emits `plan: P21 location presence: ...`; `lora_checks` counts `("location " + name, "location", None, None)`.
- Produces, in the tests: `_pin(name, description, trigger, attach=True)`, `HARBOUR`, `TEMPLE`, `P21` (the format), `_raw(mode, n, beat_locations, own=("l3",))`, `_p21(ctx, raw)`, `_engine_run(ws, tmp_path, monkeypatch, story_id, plans, members=(), locations=(HARBOUR,))`.

- [ ] **Step 1: Write the failing tests.**

**1.1.** Edit `tests/test_location_story.py`: replace this text, which occurs exactly once:

```python
import story_engine_testutil as seu  # noqa: E402
```

with:

```python
import location_testutil as lt  # noqa: E402
import story_engine_testutil as seu  # noqa: E402
```

**1.2.** Edit `tests/test_location_story.py`: replace this text, which occurs exactly once:

```python
cl = _load("character_lib_for_location_story", "character_lib.py")
```

with:

```python
cl = _load("character_lib_for_location_story", "character_lib.py")
ll = _load("location_lib_for_location_story", "location_lib.py")
```

**1.3.** Edit `tests/test_location_story.py`: replace this text, which occurs exactly once:

```python
    assert [sorted(entry) for entry in plan["locations"]] == [["id", "setting"]] * 2
```

with:

```python
    assert [sorted(entry) for entry in plan["locations"]] == [["id", "setting"]] * 2


# --- Task 6 helpers -------------------------------------------------------------------------

def _pin(name, description, trigger, attach=True):
    return ll.LocationPin(name, trigger, description, "/lib/%s/lora/video.safetensors" % name,
                          None, None, None, "dgrauet/ltx-2.3-mlx-q8", attach)


HARBOUR = _pin("harbour-street", lt.HARBOUR_DESC, "harboplc")
TEMPLE = _pin("temple-gate", lt.TEMPLE_DESC, "templplc")
P21 = ("plan: P21 location presence: %s (library location %s) is the location of no beat; every "
       "already-set place is in this movie, so give at least one beat the location %s")


def _raw(mode, n, beat_locations, own=("l3",)):
    """seu.plan_json(mode, n) with locations l1, l2 (the planner's own text) plus own, and beat k
    at beat_locations[k - 1]."""
    raw = seu.plan_json(mode, n)
    raw["locations"] = ([{"id": "l1", "setting": seu.HARBOUR}, {"id": "l2", "setting": seu.TEMPLE}]
                        + [{"id": i, "setting": "The setting is a quiet orchard of old apple "
                                                "trees on a grassy slope under a pale sky."}
                           for i in own])
    for beat, loc in zip(raw["beats"], beat_locations):
        beat["location"] = loc
    return raw


def _p21(ctx, raw):
    plan, shape = se.normalize_plan(ctx, raw)
    return [h for h in se.plan_checks(ctx, plan, shape)[0] if " P21 " in h]


# --- LS2, LS3, LS13, LS14: the constants, the plan prompt, the context, no new import (L3.3) --

def test_ls2_the_location_constants():
    assert se.LOCATION_FIXED_INTRO == (
        " The following places are already set; list them first in locations with exactly these "
        "ids and settings, and give your own places the next ids. Every one of them is in this "
        "movie: give each one's id as the location of at least one beat. When the narrative names "
        "or describes one of them, it means that place:")
    assert se.LOCATION_FIXED_LINE == '\n- id l%d, name "%s", setting "%s"'
    assert se.FIXED_SETTING == "The setting is %s."
    assert "background.@@LOCATION_FIXED@@\n" in se.PLAN_PROMPT_TEMPLATE
    assert se.PLAN_PROMPT_TEMPLATE.count("@@LOCATION_FIXED@@") == 1


def test_ls3_the_plan_prompt_lists_the_pinned_places(ws):
    prompt = se.build_plan_prompt(seu.make_ctx(se, ws, locations=[HARBOUR, TEMPLE]), [], [])
    fixed = (se.LOCATION_FIXED_INTRO
             + '\n- id l1, name "harbour-street", setting "The setting is %s."' % lt.HARBOUR_DESC
             + '\n- id l2, name "temple-gate", setting "The setting is %s."' % lt.TEMPLE_DESC)
    assert ("any crowd or other group of people in the background." + fixed + "\nprops: ") in prompt
    assert prompt.count(se.LOCATION_FIXED_INTRO) == 1
    one = se.build_plan_prompt(seu.make_ctx(se, ws, locations=[TEMPLE]), [], [])
    assert ('background.' + se.LOCATION_FIXED_INTRO
            + '\n- id l1, name "temple-gate", setting "The setting is %s."\nprops: '
            % lt.TEMPLE_DESC) in one
    plain = se.build_plan_prompt(seu.make_ctx(se, ws), [], [])
    assert "@@LOCATION_FIXED@@" not in plain and se.LOCATION_FIXED_INTRO not in plain
    assert "in the background.\nprops: " in plain


def test_ls13_story_context_defaults(ws):
    assert se.StoryContext._fields[-1] == "locations"
    assert se.StoryContext._field_defaults == {"clip_seconds": None, "panels_target": None,
                                               "length": None, "locations": (),
                                               "narration": True}
    assert seu.make_ctx(se, ws).locations == ()


def test_ls14_story_engine_gains_no_import():
    import ast
    import subprocess
    old = subprocess.run(["git", "-C", WS, "show", "d210c26:./story_engine.py"],
                         capture_output=True, text=True)
    if old.returncode != 0:
        pytest.skip("not a git checkout with d210c26")

    def imports(text):
        return sorted(ast.dump(node) for node in ast.walk(ast.parse(text))
                      if isinstance(node, (ast.Import, ast.ImportFrom)))

    with open(os.path.join(WS, "story_engine.py"), encoding="utf-8") as f:
        assert imports(f.read()) == imports(old.stdout)


# --- LS4, LS5: plan normalisation (L3.4) ----------------------------------------------------

def test_ls4_pinned_locations_are_l1_to_lk(ws):
    ctx = seu.make_ctx(se, ws, locations=[HARBOUR, TEMPLE])
    plan, _shape = se.normalize_plan(ctx, _raw("chained", 3, ["l1", "Harbour-Street", "l3"]))
    assert plan["locations"] == [
        {"id": "l1", "setting": "The setting is %s." % lt.HARBOUR_DESC,
         "location_name": "harbour-street"},
        {"id": "l2", "setting": "The setting is %s." % lt.TEMPLE_DESC,
         "location_name": "temple-gate"},
        {"id": "l3", "setting": ("The setting is a quiet orchard of old apple trees on a grassy "
                                 "slope under a pale sky."), "location_name": None}]
    assert [b["location"] for b in plan["beats"]] == ["l1", "l1", "l3"]
    raw = _raw("chained", 3, ["l1", "temple-gate", "l1"], own=())
    raw["locations"] = raw["locations"][:1]
    plan, _shape = se.normalize_plan(ctx, raw)
    assert [(e["id"], e["location_name"]) for e in plan["locations"]] == [
        ("l1", "harbour-street"), ("l2", "temple-gate")]
    assert [b["location"] for b in plan["beats"]] == ["l1", "l2", "l1"]
    raw = _raw("chained", 3, ["l2", "l2", "l3"], own=("l3",))
    raw["locations"] = raw["locations"][1:]
    plan, _shape = se.normalize_plan(seu.make_ctx(se, ws, locations=[HARBOUR]), raw)
    assert [(e["id"], e["location_name"]) for e in plan["locations"]] == [
        ("l1", "harbour-street"), ("l2", None), ("l3", None)]


def test_ls5_a_pinned_setting_is_fixed(ws):
    ctx = seu.make_ctx(se, ws, locations=[HARBOUR])
    raw = _raw("chained", 3, ["l1", "l1", "l2"])
    raw["locations"][0]["setting"] = "The setting is a different harbour the planner wrote."
    plan, _shape = se.normalize_plan(ctx, raw)
    assert plan["locations"][0]["setting"] == se.FIXED_SETTING % lt.HARBOUR_DESC
    assert se.patch_ranges(ctx, plan, True)[("plan", "location.setting")] == se.NOT_REPAIRED


# --- LS6, LS9, LS10, LS11: P21 and the LoRA count (L3.5, L3.6) ------------------------------

@pytest.mark.parametrize("mode", ["chained", "shots", "no_stills"])
def test_ls6_the_p21_matrix(ws, mode):
    ctx = seu.make_ctx(se, ws, mode=mode, locations=[HARBOUR, TEMPLE])
    for beats, missing in ((["l2", "l2", "l3"], ["l1"]), (["l1", "l3", "l1"], ["l2"]),
                           (["l3", "l3", "l3"], ["l1", "l2"])):
        found = _p21(ctx, _raw(mode, 3, beats))
        names = {"l1": "harbour-street", "l2": "temple-gate"}
        assert found == [P21 % (i, names[i], i) for i in missing], (mode, beats)
        parsed = se.parse_violation(found[0])
        assert (parsed["id"], parsed["name"], parsed["scope"]) == ("P21", "location presence",
                                                                   "plan")
    assert _p21(ctx, _raw(mode, 3, ["l1", "l2", "l3"])) == []
    assert _p21(ctx, _raw(mode, 3, ["l1", "l2", "l2"], own=("l3", "l4"))) == []
    assert _p21(seu.make_ctx(se, ws, mode=mode), _raw(mode, 3, ["l3", "l3", "l3"])) == []


def _engine_run(ws, tmp_path, monkeypatch, story_id, plans, members=(), locations=(HARBOUR,)):
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(p) for p in plans],
                           panel=dict((str(k), [seu.answer(seu.panel_json("chained", k))])
                                      for k in range(1, 4)))
    ctx = seu.make_ctx(se, ws, story_id=story_id, members=list(members),
                       locations=list(locations))
    rc, _advisories = se.run(ctx)
    return rc, ctx, seu.agent_log(log)


def test_ls8_two_plans_without_the_location_are_fatal(ws, tmp_path, monkeypatch, capsys):
    bad = _raw("chained", 3, ["l2", "l2", "l2"])
    capsys.readouterr()
    rc, ctx, log = _engine_run(ws, tmp_path, monkeypatch, "ls8", [bad, bad])
    assert rc == 1 and [r["stage"] for r in log] == ["plan", "plan"]
    assert capsys.readouterr().err == (
        "Error: the story model did not return a usable plan after 2 call(s)\n"
        "  - %s\nRaw replies are kept in %s. Rerun the same command to try again.\n"
        % (P21 % ("l1", "harbour-street", "l1"),
           os.path.join(ctx.story_dir, "story_rounds", "round_0")))
    for name in ("story.md", "plan.json"):
        assert not os.path.exists(os.path.join(ctx.story_dir, name)), name


def test_ls9_p21_and_p16_are_retried_together(ws, tmp_path, monkeypatch, story_env):
    seu.kyra(story_env["lib"])
    members = cl.resolve_cast([(None, "kyra")])
    bad = _raw("chained", 3, ["l2", "l2", "l2"])
    for beat in bad["beats"]:
        beat["cast"] = ["c2"]
    good = _raw("chained", 3, ["l1", "l2", "l1"])
    rc, _ctx, log = _engine_run(ws, tmp_path, monkeypatch, "ls9", [bad, good], members=members)
    assert rc == 0
    retry = [r for r in log if r["stage"] == "plan"][1]["argv"][-1]
    assert "\n- " + P21 % ("l1", "harbour-street", "l1") + "\n" in retry
    assert "\n- plan: P16 cast presence: c1 " in retry


def _lora_ctx(ws, tmp_path, story_env, attach):
    files = str(tmp_path / "files")
    entries = [seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style"),
               seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion")]
    seu.kyra(story_env["lib"])
    pinned = [{"path": seu.lora_file(files, "pinned"), "strength": 1.0, "catalog_id": None,
               "kind": None}]
    return seu.make_ctx(se, ws, members=cl.resolve_cast([(None, "kyra")]),
                        catalog={"schema_version": 1, "entries": entries}, pinned=pinned,
                        locations=[HARBOUR._replace(attach_video=attach)])


def test_ls10_l4_counts_an_attached_location(ws, tmp_path, story_env):
    for attach, expected in ((True, [
            "beat 1: L4 LoRA count: 5 LoRAs on this panel (pinned LoRA, film-grain, fast-motion, "
            "location harbour-street, character kyra); at most 4"]), (False, [])):
        ctx = _lora_ctx(ws, tmp_path / str(attach), story_env, attach)
        raw = _raw("chained", 3, ["l1", "l2", "l1"])
        raw["loras"] = {"global": [{"id": "film-grain", "strength": 0.8}],
                        "per_beat": {"1": [{"id": "fast-motion", "strength": 0.7}]}, "stills": []}
        plan, _shape = se.normalize_plan(ctx, raw)
        compatible = dict((e["id"], e) for e in se.compatible_entries(ctx))
        catalog = dict((e["id"], e) for e in ctx.catalog["entries"])
        hard, advisory = se.lora_checks(ctx, plan, compatible, catalog)
        assert hard == [] and [a for a in advisory if " L4 " in a] == expected, attach
        assert [a for a in advisory if " L3 " in a] == []


def test_ls11_shots_images_paste_the_fixed_setting(ws):
    ctx = seu.make_ctx(se, ws, mode="shots", locations=[HARBOUR])
    plan, _shape = se.normalize_plan(ctx, _raw("shots", 3, ["l1", "l2", "l1"]))
    for k in (1, 3):
        assert se.pasted_pieces(ctx, plan, k)["image"][0] == se.FIXED_SETTING % lt.HARBOUR_DESC
    assert se.pasted_pieces(ctx, plan, 2)["image"][0] == seu.TEMPLE


def test_ls12_recheck_never_runs_plan_checks(ws, tmp_path, monkeypatch):
    rc, ctx, _log = _engine_run(ws, tmp_path, monkeypatch, "ls12",
                                [_raw("chained", 3, ["l1", "l2", "l1"])])
    assert rc == 0

    def refuse(*args, **kwargs):
        raise AssertionError("recheck must not call plan_checks")

    monkeypatch.setattr(se, "plan_checks", refuse)
    rc, _advisories = se.recheck(ctx, lambda path, panels, no_stills=False: [])
    assert rc == 0
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_story.py 2>&1 | tail -1
```

Expected: `13 failed, 2 passed` (LS1 and LS14 already hold).

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "panels_target", "length"],
    defaults=(True, None, None, None))
```

with:

```python
    "panels_target", "length", "locations"],
    defaults=(True, None, None, None, ()))
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
# Plan ruling SPR2: length is bin/ltx-movie's --length in seconds when --length sized the movie
# (None otherwise); the panel-count hints then name --length, never --panels.
```

with:

```python
# Plan ruling SPR2: length is bin/ltx-movie's --length in seconds when --length sized the movie
# (None otherwise); the panel-count hints then name --length, never --panels.
# Location library spec L3.3: locations is the pinned location_lib.LocationPin list of
# bin/ltx-movie --location ((): none); this module reads only their name, description and
# attach_video.
```

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "background.\n"
```

with:

```python
    "background.@@LOCATION_FIXED@@\n"
```

**3.4.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
CAST_FIXED_LINE = '\n- id c%d, name "%s", phrase "%s", descriptor "%s"'
```

with:

```python
CAST_FIXED_LINE = '\n- id c%d, name "%s", phrase "%s", descriptor "%s"'
# Location library spec L3.3: the pinned places, by library name, each set in a beat.
LOCATION_FIXED_INTRO = (" The following places are already set; list them first in locations "
                        "with exactly these ids and settings, and give your own places the next "
                        "ids. Every one of them is in this movie: give each one's id as the "
                        "location of at least one beat. When the narrative names or describes "
                        "one of them, it means that place:")
LOCATION_FIXED_LINE = '\n- id l%d, name "%s", setting "%s"'
FIXED_SETTING = "The setting is %s."
```

**3.5.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        for i, member in enumerate(ctx.members, start=1):
            cast_fixed += CAST_FIXED_LINE % (i, member.name, member.phrase, member.descriptor)
```

with:

```python
        for i, member in enumerate(ctx.members, start=1):
            cast_fixed += CAST_FIXED_LINE % (i, member.name, member.phrase, member.descriptor)
    location_fixed = ""
    if ctx.locations:
        location_fixed = LOCATION_FIXED_INTRO
        for i, pin in enumerate(ctx.locations, start=1):
            location_fixed += LOCATION_FIXED_LINE % (i, pin.name, FIXED_SETTING % pin.description)
```

**3.6.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        ("@@CAST_FIXED@@", cast_fixed),
```

with:

```python
        ("@@CAST_FIXED@@", cast_fixed),
        ("@@LOCATION_FIXED@@", location_fixed),
```

**3.7.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        locations.append({"id": _clean_str(item.get("id")), "setting": setting})
    plan["locations"] = locations
```

with:

```python
        locations.append({"id": _clean_str(item.get("id")), "setting": setting})
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
    plan["locations"] = locations
```

**3.8.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
            "lines": _clean_lines(item.get("lines"))})
    plan["beats"] = beats
```

with:

```python
            "lines": _clean_lines(item.get("lines"))})
    if ctx.locations:
        by_name = dict((pin.name, "l%d" % i) for i, pin in enumerate(ctx.locations, start=1))
        for beat in beats:
            beat["location"] = by_name.get(beat["location"].lower(), beat["location"])
    plan["beats"] = beats
```

**3.9.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    presence spec PC1) and P17 (a spoken line given to a speaker other than the one the narrative
    names; speaker attribution spec SA2); every other P message is advisory (dialogue spec
```

with:

```python
    presence spec PC1), P17 (a spoken line given to a speaker other than the one the narrative
    names; speaker attribution spec SA2) and P21 (a library location that is the location of no
    beat; location library spec L3.5); every other P message is advisory (dialogue spec
```

**3.10.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    # Speaker attribution spec SA2, D3: a spoken line keeps the speaker the narrative names.
```

with:

```python
    # Location library spec L3.5: every library location is the location of some beat.
    used = set(beat["location"] for beat in beats)
    for entry in plan["locations"]:
        if entry.get("location_name") and entry["id"] not in used:
            hard.append("plan: P21 location presence: %s (library location %s) is the location "
                        "of no beat; every already-set place is in this movie, so give at least "
                        "one beat the location %s" % (entry["id"], entry["location_name"],
                                                       entry["id"]))
    # Speaker attribution spec SA2, D3: a spoken line keeps the speaker the narrative names.
```

**3.11.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    pin_paths = {os.path.realpath(p["path"]) for p in pins}
    for k in range(1, n + 1):
        beat = plan["beats"][k - 1] if k <= len(plan["beats"]) else {"cast": []}
        loras_k = ([(pin_label(p), p.get("kind"), p.get("catalog_id"), None) for p in pins]
                   + [(e["id"], e["kind"], e["id"], e["path"]) for e in global_picks]
                   + [(e["id"], e["kind"], e["id"], e["path"]) for e in per_beat.get(k, [])]
                   + [("character " + by_cast[c]["cast_name"], "character", None, None)
```

with:

```python
    pin_paths = {os.path.realpath(p["path"]) for p in pins}
    # Location library spec L3.6: an attached pinned location's video LoRA counts for L4.
    by_location = {l["id"]: l for l in plan["locations"]}
    attached = set(pin.name for pin in ctx.locations if pin.attach_video)
    for k in range(1, n + 1):
        beat = plan["beats"][k - 1] if k <= len(plan["beats"]) else {"cast": []}
        loc = by_location.get(beat.get("location"), {}).get("location_name")
        loras_k = ([(pin_label(p), p.get("kind"), p.get("catalog_id"), None) for p in pins]
                   + [(e["id"], e["kind"], e["id"], e["path"]) for e in global_picks]
                   + [(e["id"], e["kind"], e["id"], e["path"]) for e in per_beat.get(k, [])]
                   + ([("location " + loc, "location", None, None)] if loc in attached else [])
                   + [("character " + by_cast[c]["cast_name"], "character", None, None)
```

**3.12.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        # Pinned cast presence spec PC2, speaker attribution spec SA3: a plan that drops a library
        # character or gives a spoken line to the wrong speaker is not usable.
        fatal = ([h for h in found[2] if parse_violation(h)["id"] in ("P1", "P2", "P16", "P17")]
```

with:

```python
        # Pinned cast presence spec PC2, speaker attribution spec SA3: a plan that drops a library
        # character or gives a spoken line to the wrong speaker, or sets no beat at a library
        # location (location library spec L3.5), is not usable.
        fatal = ([h for h in found[2]
                  if parse_violation(h)["id"] in ("P1", "P2", "P16", "P17", "P21")]
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_story.py 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider tests/test_story_engine.py tests/test_pinned_cast.py tests/test_dialogue.py tests/test_lora_catalog.py 2>&1 | tail -1
```

Expected: `15 passed`; then `1 failed, N passed`, the one failure being the baseline `test_rst62_import_sets` with its `d210c26` message. `tests/test_soft_panel_count.py::test_spt1a_engine_constants` now fails on purpose (code SC, re-baselined in Task 14). Run the compile check with `FILES` = `story_engine.py tests/test_location_story.py`; expected: `compiled 2` twice. Then run the gate block with `N=6`. Expected: `GATE PASS`, `new-file tests 71, not passing 0`, `baseline failures still failing 2 of 2`, `OK 347/347`, and two listed LOST lines: `test_mut26` and `test_spt1a_engine_constants` (code SC).

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_location_story.py
git diff --cached --name-only    # expected: those 2 paths
git commit -m "feat(story): pinned locations are l1..lK with their fixed setting; P21 retries, then fails, a plan that sets no beat at one; L4 counts an attached location (L3.3-L3.6; LS2-LS6, LS8-LS14)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: `bin/ltx-story-manifest`: per-panel locations from `plan.json` (L3.7; LP5-LP9, Review Focus 3, 4)

This task implements:
- L3.7 parser: `--location NAME` (append, dest `location`) and `--location-strength` (float), refused with `parser.error` without `--chain`/`--shots` and without `--location` respectively.
- L3.7 attach, after the casting block and before the catalog block: `resolve_locations` (exit 2 on error), the strength (exit 2 outside `(0, 1]`), `plan_panel_locations` (its note printed), each panel's `locations` (`[]` or one `{"name", "video_lora", "strength"}`) and the trigger prefix, and the `WARNING` for an unused pin (only with a usable plan; Plan ruling LR15).
- L3.7 summary: `location: panel %d: %s@%s` after the cast summary.
- Trigger order on a panel: catalog, then location, then character triggers, because the step runs after casting and before the catalog prefix.
- `schema_version` stays 3 (the key is optional). The docstring gains a `--location` paragraph.

**Files:**
- Modify: `bin/ltx-story-manifest`: the docstring (`:75`), after `_lora_catalog` (`:196-198`), the parser (`:174-176`), `main`'s checks (`:576-577`), after the casting block (`:892-894`), after the cast summary (`:950-951`).
- Create: `tests/test_location_pipeline.py` (Tasks 8-10 append).
- Read only: `bin/ltx-story-manifest` (`_casting_plan` `:401-442`, the catalog block `:896-906`).

**Interfaces:**
- Consumes: Task 2's `resolve_locations`, `DEFAULT_LOCATION_STRENGTH`, `plan_panel_locations`, `prefix_location_trigger`, `LocationError`; `tests/location_testutil.write_plan`.
- Produces, in `bin/ltx-story-manifest`: `_location_lib()`; the flags above; manifest panels with `"locations"` whenever `--location` is given.
- Produces, in the tests: the header (`WS`, `lt`, `seu`, `_load`, `manifest`, the autouse `story_env`), `CHAIN_STORY`, `SHOTS_STORY`, `_manifest_story(tmp_path, monkeypatch, story_id="lp", text=CHAIN_STORY, beats=("l1", "l2", "l1"))`, `_manifest_argv(story_id, story_md, images, shots=False, *extra)`, `_panels(story_dir)`.

- [ ] **Step 1: Write the failing tests.**

**1.1.** Create `tests/test_location_pipeline.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""Tests for the location library's pipeline path (docs/superpowers/specs/
2026-10-29-location-lora-design.md, Sections 4.1, 4.2 and 4.7-4.11, test table 6.8: LP1-LP20,
with the plan's Review Focus pins): bin/ltx-story-manifest's per-panel attach,
bin/ltx-story-images' stills attach, bin/ltx-mlx-render's units, bin/ltx-movie's flags and
resolution, and bin/iterate-story.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_location_pipeline.py
Stdlib plus pytest and PIL. No test reads the real HOME, renders, trains, runs Z-Image or the
editor, contacts a model server or touches port 8178: every tool runs in-process against a
temporary workspace (story_engine_testutil.make_ws; each module's WS is patched to it), every
model call goes to that workspace's fake bin/qwen-agent, subprocess launches of the pipeline
tools are recorded instead of run, and every library lives under tmp_path (the autouse story_env
fixture: HOME, CHARACTER_LIBRARY_DIR, LOCATION_LIBRARY_DIR and LORA_CATALOG_DIR).
"""

import importlib.machinery
import json
import os
import shutil
import subprocess
import sys

import pytest
from PIL import Image

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import location_testutil as lt  # noqa: E402
import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


manifest = _load("ltx_story_manifest_for_location", os.path.join("bin", "ltx-story-manifest"))


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


CHAIN_STORY = """# The Harbour

A courier crosses a harbour town to a temple gate and back.

## Panel 1 — Quay
Image: A wide shot of the courier on a stone quay. Photorealistic live-action film still.
Motion: The courier walks along the quay; the camera tracks.
Narration: She hurries.

## Panel 2 — Gate
Motion: The courier climbs the temple steps.
Narration: She climbs.

## Panel 3 — Return
Motion: The courier runs back along the quay.
Narration: She returns.
"""
SHOTS_STORY = """# The Harbour

A courier crosses a harbour town to a temple gate and back.

## Panel 1 — Quay
Image: A wide shot of the courier on a stone quay.
Motion: The courier walks along the quay.
Narration: She hurries.

## Panel 2 — Gate
Image: A wide shot of the courier at a temple gate.
Motion: The courier climbs the temple steps.
Narration: She climbs.

## Panel 3 — Return
Image: A wide shot of the courier on the quay again.
Motion: The courier runs back along the quay.
Narration: She returns.
"""


def _manifest_story(tmp_path, monkeypatch, story_id="lp", text=CHAIN_STORY,
                    beats=("l1", "l2", "l1")):
    """A temporary workspace (manifest.WS) with generated/stories/<story_id>/story.md, one 64x64
    still per panel and, when beats is not None, a plan.json whose beat k is at beats[k - 1]
    (l1 is harbour-street). Returns (ws, story_dir, story_md, images)."""
    ws = seu.make_ws(tmp_path)
    monkeypatch.setattr(manifest, "WS", ws)
    story_dir = os.path.join(ws, "generated", "stories", story_id)
    os.makedirs(story_dir)
    story_md = os.path.join(story_dir, "story.md")
    with open(story_md, "w", encoding="utf-8") as f:
        f.write(text)
    images = []
    for k in range(1, text.count("## Panel ") + 1):
        images.append(os.path.join(story_dir, "panel_%02d.png" % k))
        Image.new("RGB", (64, 64), (90, 90, 90)).save(images[-1])
    if beats is not None:
        lt.write_plan(story_dir, list(beats))
    return ws, story_dir, story_md, images


def _manifest_argv(story_id, story_md, images, shots=False, *extra):
    mode = ["--shots"] + sum([["--image", i] for i in images], []) if shots else [
        "--chain", "--image", images[0]]
    return (["--story-id", story_id, "--prompts-md", story_md] + mode
            + ["--fps", "24", "--target-seconds", "18.125", "--min-frames", "145",
               "--max-frames", "145", "--force"] + list(extra))


def _panels(story_dir):
    with open(os.path.join(story_dir, "manifest.json")) as f:
        return json.load(f)["panels"]


# --- LP5-LP9, Review Focus 3, 4: bin/ltx-story-manifest (L3.7) -------------------------------

@pytest.mark.parametrize("shots", [False, True])
def test_lp5_lp6_the_manifest_attaches_the_planned_beats(tmp_path, monkeypatch, capsys,
                                                         story_env, shots):
    harbour = lt.harbour(story_env["locations"])
    text = SHOTS_STORY if shots else CHAIN_STORY
    ws, story_dir, story_md, images = _manifest_story(tmp_path, monkeypatch, text=text)
    capsys.readouterr()
    assert manifest.main(_manifest_argv("lp", story_md, images, shots,
                                        "--location", "harbour-street")) == 0
    out = capsys.readouterr().out
    panels = _panels(story_dir)
    entry = {"name": "harbour-street", "video_lora": harbour["loras"]["video"]["path"],
             "strength": 0.8}
    assert [p["locations"] for p in panels] == [[entry], [], [entry]]
    assert [p["motion_prompt"] for p in panels] == [
        "harboplc. The courier walks along the quay" + ("." if shots else "; the camera tracks."),
        "The courier climbs the temple steps.", "harboplc. The courier runs back along the quay."]
    assert "location: panel 1: harbour-street@0.8\nlocation: panel 3: harbour-street@0.8\n" in out
    assert "location: panel 2" not in out


def test_lp7_trigger_order_and_the_record_strength(tmp_path, monkeypatch, capsys, story_env):
    lt.harbour(story_env["locations"], strength=0.6)
    seu.kyra(story_env["lib"])
    ws, story_dir, story_md, images = _manifest_story(tmp_path, monkeypatch)
    plan = lt.write_plan(story_dir, ["l1", "l2", "l1"])
    plan["cast"] = [{"id": "c1", "phrase": "the woman in grey", "descriptor": seu.DESC_K,
                     "cast_name": "kyra"}]
    plan["beats"][0]["cast"] = ["c1"]
    with open(os.path.join(story_dir, "plan.json"), "w") as f:
        json.dump(plan, f)
    lora = seu.lora_file(str(tmp_path / "files"), "cat")
    entry = {"id": "cat-style", "kind": "style", "path": lora, "sha256": seu.sha256_file(lora),
             "strength": 0.7, "triggers": ["cattrig"]}
    catalog = os.path.join(story_dir, "catalog_loras.json")
    with open(catalog, "w") as f:
        json.dump({"schema": "ltx-movie.catalog-loras.v1", "story_id": "lp",
                   "panels": [[entry], [], []]}, f)
    assert manifest.main(_manifest_argv(
        "lp", story_md, images, False, "--cast", "the woman in grey=kyra", "--location",
        "harbour-street", "--location-strength", "0.9", "--catalog-loras", catalog)) == 0
    panels = _panels(story_dir)
    assert panels[0]["motion_prompt"] == (
        "cattrig. harboplc. kyrawmn. The courier walks along the quay; the camera tracks.")
    assert [l["strength"] for p in panels for l in p["locations"]] == [0.6, 0.6]
    assert "location: panel 1: harbour-street@0.6" in capsys.readouterr().out


def test_lp8_without_a_usable_plan_no_panel_gets_a_location(tmp_path, monkeypatch, capsys,
                                                            story_env):
    lt.harbour(story_env["locations"])
    lt.temple(story_env["locations"])
    ws, story_dir, story_md, images = _manifest_story(tmp_path, monkeypatch, beats=None)
    capsys.readouterr()
    assert manifest.main(_manifest_argv("lp", story_md, images, False,
                                        "--location", "harbour-street")) == 0
    out = capsys.readouterr().out
    assert out.count("note: there is no plan.json for this story; no location LoRAs are "
                     "attached (location LoRAs attach only to planned beats)\n") == 1
    assert "WARNING" not in out
    assert [p["locations"] for p in _panels(story_dir)] == [[], [], []]
    assert [p["motion_prompt"][:9] for p in _panels(story_dir)] == ["The couri"] * 3
    lt.write_plan(story_dir, ["l1", "l1"])
    assert manifest.main(_manifest_argv("lp", story_md, images, False,
                                        "--location", "harbour-street")) == 0
    assert ("note: plan.json is not usable for locations (it has 2 beats for 3 panels); no "
            "location LoRAs are attached\n") in capsys.readouterr().out
    lt.write_plan(story_dir, ["l1", "l2", "l1"])
    assert manifest.main(_manifest_argv("lp", story_md, images, False, "--location",
                                        "harbour-street", "--location", "temple-gate")) == 0
    out = capsys.readouterr().out
    assert ("WARNING: location temple-gate is the location of no panel's beat in plan.json; it "
            "gets no LoRA\n") in out
    assert "harbour-street is the location of no" not in out


def test_lp9_manifest_argument_errors(tmp_path, monkeypatch, capsys, story_env):
    lt.harbour(story_env["locations"])
    ws, story_dir, story_md, images = _manifest_story(tmp_path, monkeypatch)
    base = ["--story-id", "lp", "--prompts-md", story_md, "--image", images[0], "--force"]
    with pytest.raises(SystemExit) as info:
        manifest.main(base + ["--location", "harbour-street"])
    assert info.value.code == 2
    assert "--location requires --chain or --shots" in capsys.readouterr().err
    with pytest.raises(SystemExit) as info:
        manifest.main(_manifest_argv("lp", story_md, images, False, "--location-strength", "0.5"))
    assert info.value.code == 2
    assert "--location-strength requires --location" in capsys.readouterr().err
    for bad in ("0", "1.5"):
        assert manifest.main(_manifest_argv("lp", story_md, images, False, "--location",
                                            "harbour-street", "--location-strength", bad)) == 2
        assert capsys.readouterr().err == (
            "Error: --location-strength must be in (0, 1], got %r\n" % float(bad))
    assert manifest.main(_manifest_argv("lp", story_md, images, False, "--location", "a",
                                        "--location", "b", "--location", "c", "--location",
                                        "d")) == 2
    assert capsys.readouterr().err == "Error: at most 3 locations, got 4\n"


def test_review_focus_3_a_location_deleted_after_phase_1(tmp_path, monkeypatch, capsys,
                                                         story_env):
    lt.harbour(story_env["locations"])
    ws, story_dir, story_md, images = _manifest_story(tmp_path, monkeypatch)
    shutil.rmtree(os.path.join(story_env["locations"], "harbour-street"))
    assert manifest.main(_manifest_argv("lp", story_md, images, False,
                                        "--location", "harbour-street")) == 2
    assert capsys.readouterr().err == "Error: unknown location: harbour-street (no %s)\n" % (
        os.path.join(story_env["locations"], "harbour-street", "location.json"))
    assert not os.path.exists(os.path.join(story_dir, "manifest.json"))


def test_review_focus_4_a_plan_with_more_beats_than_the_target(tmp_path, monkeypatch, story_env):
    lt.harbour(story_env["locations"])
    four = CHAIN_STORY + ("\n## Panel 4 — Home\nMotion: The courier rests by the harbour "
                          "wall.\nNarration: She rests.\n")
    ws, story_dir, story_md, images = _manifest_story(tmp_path, monkeypatch, text=four,
                                                      beats=("l2", "l1", "l2", "l1"))
    plan_path = os.path.join(story_dir, "plan.json")
    with open(plan_path) as f:
        plan = json.load(f)
    plan["panels_target"] = 3
    with open(plan_path, "w") as f:
        json.dump(plan, f)
    argv = _manifest_argv("lp", story_md, images, False, "--location", "harbour-street")
    argv[argv.index("--target-seconds") + 1] = "24.167"
    assert manifest.main(argv) == 0
    assert [bool(p["locations"]) for p in _panels(story_dir)] == [False, True, False, True]
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_pipeline.py 2>&1 | tail -1
```

Expected: `7 failed` (argparse rejects `--location`).

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
only when --cast is given, a Narration: line has a colon or a panel has a Dialogue: line.
```

with:

```python
only when --cast is given, a Narration: line has a colon or a panel has a Dialogue: line.

--location NAME (repeatable, --chain or --shots only) pins a trained location from the location
library (generated/locations/NAME, see docs/superpowers/specs/2026-10-29-location-lora-design.md
L3.7). Every panel whose plan.json beat is set at that location gets an optional "locations" list
with one {"name", "video_lora", "strength"} entry (the location's own location.json strength,
else --location-strength, default 0.8), and the location's trigger is prefixed to its
motion_prompt after the cast triggers and before the catalog triggers; every other panel gets an
empty list. Without a usable plan.json no panel gets one, and a note says why. location_lib.py is
loaded by path only when --location is given.
```

**3.2.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
def _lora_catalog():
    return importlib.machinery.SourceFileLoader(
        "lora_catalog", os.path.join(WS, "lora_catalog.py")).load_module()
```

with:

```python
def _lora_catalog():
    return importlib.machinery.SourceFileLoader(
        "lora_catalog", os.path.join(WS, "lora_catalog.py")).load_module()


def _location_lib():
    return importlib.machinery.SourceFileLoader(
        "location_lib", os.path.join(WS, "location_lib.py")).load_module()
```

**3.3.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
                         help="LoRA strength for each cast character without its own "
                              "character.json strength (default 0.8, provisional), the same in "
                              "every panel")
```

with:

```python
                         help="LoRA strength for each cast character without its own "
                              "character.json strength (default 0.8, provisional), the same in "
                              "every panel")
    parser.add_argument("--location", dest="location", action="append", default=None,
                         metavar="NAME",
                         help="pin a trained location (generated/locations/NAME; repeatable, "
                              "--chain or --shots only): every panel whose plan.json beat is set "
                              "there gets a 'locations' entry with its video LoRA and strength, "
                              "and its trigger is prefixed to the panel's motion_prompt")
    parser.add_argument("--location-strength", dest="location_strength", type=float,
                         default=None,
                         help="LoRA strength for each location without its own location.json "
                              "strength (default 0.8)")
```

**3.4.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
    if args.character_strength is not None and not args.cast:
        parser.error("--character-strength requires --cast")
```

with:

```python
    if args.character_strength is not None and not args.cast:
        parser.error("--character-strength requires --cast")
    if args.location and not (args.chain or args.shots):
        parser.error("--location requires --chain or --shots")
    if args.location_strength is not None and not args.location:
        parser.error("--location-strength requires --location")
```

**3.5.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
                print("WARNING: cast phrase %r (character %s) occurs in no panel's %s text; "
                      "that character gets no LoRA"
                      % (m.phrase, m.name, "Image: or Motion:" if args.shots else "Motion:"))
```

with:

```python
                print("WARNING: cast phrase %r (character %s) occurs in no panel's %s text; "
                      "that character gets no LoRA"
                      % (m.phrase, m.name, "Image: or Motion:" if args.shots else "Motion:"))

    if args.location:
        # Location library spec L3.7: only the panels whose plan.json beat is set at a pinned
        # location get its video LoRA and trigger.
        location_lib = _location_lib()
        try:
            pins = location_lib.resolve_locations(args.location)
        except location_lib.LocationError as e:
            print("Error: %s" % e, file=sys.stderr)
            return 2
        location_strength = (args.location_strength if args.location_strength is not None
                             else location_lib.DEFAULT_LOCATION_STRENGTH)
        if not 0 < location_strength <= 1.0:
            print("Error: --location-strength must be in (0, 1], got %r" % location_strength,
                  file=sys.stderr)
            return 2
        by_pin = dict((pin.name, pin) for pin in pins)
        per_panel, note = location_lib.plan_panel_locations(
            os.path.join(WS, "generated", "stories", args.story_id), n_panels,
            [pin.name for pin in pins])
        if note is not None:
            print(note)
        for p, name in zip(panels, per_panel):
            if name is None:
                p["locations"] = []
                continue
            pin = by_pin[name]
            p["locations"] = [{"name": name, "video_lora": pin.video_lora,
                               "strength": (pin.strength if pin.strength is not None
                                            else location_strength)}]
            p["motion_prompt"] = location_lib.prefix_location_trigger(p["motion_prompt"],
                                                                      pin.trigger)
        if note is None:
            for pin in pins:
                if pin.name not in per_panel:
                    print("WARNING: location %s is the location of no panel's beat in plan.json; "
                          "it gets no LoRA" % pin.name)
```

**3.6.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
                print("cast: panel %d: %s" % (p["index"], ", ".join(
                    "%s@%s" % (c["name"], repr(c["strength"])) for c in p["characters"])))
```

with:

```python
                print("cast: panel %d: %s" % (p["index"], ", ".join(
                    "%s@%s" % (c["name"], repr(c["strength"])) for c in p["characters"])))
    if args.location:
        for p in panels:
            for entry in p["locations"]:
                print("location: panel %d: %s@%s" % (p["index"], entry["name"],
                                                     repr(float(entry["strength"]))))
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_pipeline.py tests/test_casting_pipeline.py tests/test_ltx_story_manifest_chain.py 2>&1 | tail -1
```

Expected: every test passes. Run the compile check with `FILES` = `bin/ltx-story-manifest tests/test_location_pipeline.py`; expected: `compiled 2` twice. Then run the gate block with `N=7`. Expected: `GATE PASS`, `new-file tests 78, not passing 0`, `baseline failures still failing 2 of 2`, `OK 347/347`, and the two listed LOST lines of Task 6.

- [ ] **Step 5: Commit.**

```bash
git add bin/ltx-story-manifest tests/test_location_pipeline.py
git diff --cached --name-only    # expected: those 2 paths
git commit -m "feat(ltx-story-manifest): --location attaches the location's video LoRA and trigger to the panels whose plan.json beat is set there (L3.7; LP5-LP9, Review Focus 3, 4)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: `bin/ltx-story-images`: the stills LoRA on the panels set at a location (L3.8 images; LP10-LP12)

This task implements L3.8's `bin/ltx-story-images` half:
- The parser gains `--location NAME` (append) and `--location-strength` (float). `--location-strength` without `--location` exits 2 with `Error: --location-strength requires --location`.
- After casting is resolved: `resolve_locations` (exit 2), the strength, `plan_panel_locations` on the `plan.json` beside `--story-md` (its note printed), and the `WARNING` for a pin without a stills LoRA.
- `loc_plans[i] = (trigger, {"kind": "location", "name", "path", "strength"})` for each selected generated panel at a pin with a stills LoRA. Panel 1 with `--seed-image` is skipped.
- The legacy-route test also needs `not loc_plans`. A global `--lora` equal to an attached location stills LoRA exits 2 with `Error: --lora PATH is also location NAME's stills LoRA; pass it once`.
- `plans` are built when `members or global_stills or loc_plans`. A location panel gets `prefix_location_trigger(prompt, trigger)` and `global_stills + [entry] + chars`.
- The new code calls `compose(` only, so `_compose_prompt(` stays at 3 occurrences and `_panel_seed(args.seed, i, grounded)` at 2 (I20, LP12). The one-set-per-process refusal and the `--lora-trigger` prefix are unchanged and run after.

The `bin/ltx-movie` half of L3.8 (the flags it passes and the shots stills groups) is Task 10.

**Files:**
- Modify: `bin/ltx-story-images`: the docstring (`:55`), the parser (`:137`), after `_character_lib` (`:144-146`), after casting (`:269-274`), the legacy-route test (`:313`), the member duplicate check and `plans` (`:329-339`).
- Modify: `tests/test_location_pipeline.py` (append).
- Read only: `tests/test_ltx_story_images.py` (I20 `:581-592`).

**Interfaces:**
- Consumes: Task 2's `resolve_locations`, `DEFAULT_LOCATION_STRENGTH`, `plan_panel_locations`, `prefix_location_trigger`, `LocationError`.
- Produces, in `bin/ltx-story-images`: `_location_lib()`, the flags above, and `images.json` plan entries with a `{"kind": "location", ...}` LoRA.
- Produces, in the tests: `images`, `IMAGES_STORY`, `_images_story(tmp_path, beats=("l1", "l2", "l1"), pinned=(("l1", "harbour-street"),))`, `_images(story_md, out_dir, *extra)`.

- [ ] **Step 1: Write the failing tests.**

**1.1.** Edit `tests/test_location_pipeline.py`: replace this text, which occurs exactly once:

```python
    assert [bool(p["locations"]) for p in _panels(story_dir)] == [False, True, False, True]
```

with:

```python
    assert [bool(p["locations"]) for p in _panels(story_dir)] == [False, True, False, True]


# --- LP10-LP12: bin/ltx-story-images (L3.8) ---------------------------------------------------

images = _load("ltx_story_images_for_location", os.path.join("bin", "ltx-story-images"))
IMAGES_STORY = """# The Harbour

A courier crosses a harbour town.

## Panel 1 — Quay
Image: A wide shot of the woman in grey on a stone quay.
Motion: The woman in grey walks along the quay.

## Panel 2 — Gate
Image: A wide shot of the woman in grey at a temple gate.
Motion: The woman in grey climbs the temple steps.

## Panel 3 — Return
Image: A wide shot of the woman in grey on the quay again.
Motion: The woman in grey runs back along the quay.
"""


def _images_story(tmp_path, beats=("l1", "l2", "l1"), pinned=(("l1", "harbour-street"),)):
    story_dir = str(tmp_path / "story")
    os.makedirs(story_dir)
    story_md = os.path.join(story_dir, "story.md")
    with open(story_md, "w", encoding="utf-8") as f:
        f.write(IMAGES_STORY)
    lt.write_plan(story_dir, list(beats), pinned=pinned)
    return story_md, os.path.join(story_dir, "images")


def _images(story_md, out_dir, *extra):
    return images.main(["--story-md", story_md, "--out-dir", out_dir, "--dry-run"] + list(extra))


def test_lp10_chained_panel_1_gets_the_stills_lora(tmp_path, capsys, story_env):
    harbour = lt.harbour(story_env["locations"], stills=True)
    story_md, out = _images_story(tmp_path)
    capsys.readouterr()
    assert _images(story_md, out, "--only", "1", "--location", "harbour-street") == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == ["1 | %s | %r" % (os.path.join(out, "panel_01.png"),
                                      "harboplc. A wide shot of the woman in grey on a stone quay."),
                     "    loras: harbour-street=%s@0.8" % harbour["loras"]["stills"]["path"]]
    seed = str(tmp_path / "seed.png")
    Image.new("RGB", (64, 64)).save(seed)
    assert _images(story_md, out, "--only", "1", "--seed-image", seed, "--location",
                   "harbour-street", "--location-strength", "0.5") == 0
    assert capsys.readouterr().out.splitlines() == [
        "1 | %s | seed: %s" % (os.path.join(out, "panel_01.png"), seed)]


def test_lp11_shots_order_warning_one_set_and_duplicates(tmp_path, capsys, story_env):
    harbour = lt.harbour(story_env["locations"], stills=True)
    temple = lt.temple(story_env["locations"])
    seu.kyra(story_env["lib"])
    kyra_stills = os.path.join(story_env["lib"], "kyra", "lora", "stills.safetensors")
    glob_lora = seu.lora_file(str(tmp_path / "files"), "grain")
    story_md, out = _images_story(tmp_path, pinned=(("l1", "harbour-street"),
                                                    ("l2", "temple-gate")))
    capsys.readouterr()
    common = ["--shots", "--cast", "the woman in grey=kyra", "--lora", glob_lora + ":0.5",
              "--location", "harbour-street", "--location", "temple-gate"]
    assert _images(story_md, out, "--only", "1", *common) == 0
    out_lines = capsys.readouterr().out.splitlines()
    assert ("WARNING: location temple-gate has no stills LoRA (not trained); its trigger is not "
            "added to Image: prompts and its panels render without it") in out_lines
    assert out_lines[-1] == "    loras: global=%s@0.5, harbour-street=%s@0.8, kyra=%s@0.8" % (
        os.path.abspath(glob_lora), harbour["loras"]["stills"]["path"], kyra_stills)
    assert "'harboplc. A wide shot of the kyrawmn woman in grey on a stone quay." in out_lines[-2]
    assert _images(story_md, out, "--only", "2", *common) == 0
    out_lines = capsys.readouterr().out.splitlines()
    assert "templplc" not in out_lines[-2]
    assert out_lines[-1] == "    loras: global=%s@0.5, kyra=%s@0.8" % (
        os.path.abspath(glob_lora), kyra_stills)
    assert _images(story_md, out, "--only", "1,2", *common) == 2
    assert capsys.readouterr().err == (
        "Error: the selected panels need different stills LoRA sets (z_image_skill loads one set "
        "per process); run one --only panel per invocation\n")
    assert _images(story_md, out, "--only", "1,3", *common) == 0
    capsys.readouterr()
    for given in (harbour["loras"]["stills"]["path"] + ":0.5", harbour["loras"]["stills"]["path"]):
        assert _images(story_md, out, "--only", "1", "--lora", given, "--location",
                       "harbour-street") == 2
        assert capsys.readouterr().err == (
            "Error: --lora %s is also location harbour-street's stills LoRA; pass it once\n"
            % harbour["loras"]["stills"]["path"])
    assert _images(story_md, out, "--only", "1", "--location-strength", "0.5") == 2
    assert capsys.readouterr().err == "Error: --location-strength requires --location\n"
    assert _images(story_md, out, "--only", "1", "--location", "nowhere") == 2
    assert capsys.readouterr().err.startswith("Error: unknown location: nowhere (no ")
    assert temple["loras"]["stills"] is None


def test_lp12_the_i20_source_counts_hold():
    with open(os.path.join(WS, "bin", "ltx-story-images"), encoding="utf-8") as f:
        source = f.read()
    assert source.count("_compose_prompt(") == 3
    assert source.count("_panel_seed(args.seed, i, grounded)") == 2
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_pipeline.py 2>&1 | tail -1
```

Expected: `2 failed, 8 passed` (LP10 and LP11; LP12's counts already hold).

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/ltx-story-images`: replace this text, which occurs exactly once:

```python
--shots (bin/ltx-movie --shots) pins every generated panel's seed to --seed and gives
```

with:

```python
Locations: --location NAME (repeatable) pins a trained location from the location library
(docs/superpowers/specs/2026-10-29-location-lora-design.md L3.8). A selected generated panel whose
plan.json beat (the plan.json beside --story-md) is set at a pinned location that has a stills
LoRA gets that LoRA, between the global and the character LoRAs, at the location's own strength
or --location-strength (default 0.8), and the location's trigger in front of its prompt. A pinned
location without a stills LoRA gets a warning and no trigger. location_lib.py is loaded by path
only when --location is given.

--shots (bin/ltx-movie --shots) pins every generated panel's seed to --seed and gives
```

**3.2.** Edit `bin/ltx-story-images`: replace this text, which occurs exactly once:

```python
    parser.add_argument("--lora-trigger", dest="lora_trigger", action="append", default=None,
```

with:

```python
    parser.add_argument("--location", dest="location", action="append", default=None,
                        metavar="NAME",
                        help="pin a trained location (generated/locations/NAME, repeatable): a "
                             "panel whose plan.json beat is set there is generated with its "
                             "stills LoRA and its trigger in front of the prompt")
    parser.add_argument("--location-strength", dest="location_strength", type=float,
                        default=None,
                        help="stills LoRA strength for each location without its own "
                             "location.json strength (default 0.8)")
    parser.add_argument("--lora-trigger", dest="lora_trigger", action="append", default=None,
```

**3.3.** Edit `bin/ltx-story-images`: replace this text, which occurs exactly once:

```python
def _character_lib():
    return importlib.machinery.SourceFileLoader(
        "character_lib", os.path.join(WS, "character_lib.py")).load_module()
```

with:

```python
def _character_lib():
    return importlib.machinery.SourceFileLoader(
        "character_lib", os.path.join(WS, "character_lib.py")).load_module()


def _location_lib():
    return importlib.machinery.SourceFileLoader(
        "location_lib", os.path.join(WS, "location_lib.py")).load_module()
```

**3.4.** Edit `bin/ltx-story-images`: replace this text, which occurs exactly once:

```python
        try:
            members = lib.resolve_cast([lib.parse_cast_arg(v) for v in args.cast])
        except lib.CharacterError as e:
            print("Error: %s" % e, file=sys.stderr)
            return 2
    import ltx2_mlx_video_skill
```

with:

```python
        try:
            members = lib.resolve_cast([lib.parse_cast_arg(v) for v in args.cast])
        except lib.CharacterError as e:
            print("Error: %s" % e, file=sys.stderr)
            return 2
    # Location library spec L3.8: (trigger, stills LoRA entry) for each selected generated panel
    # whose plan.json beat is set at a pinned location with a stills LoRA.
    location_lib, loc_plans = None, {}
    if args.location_strength is not None and not args.location:
        print("Error: --location-strength requires --location", file=sys.stderr)
        return 2
    if args.location:
        location_lib = _location_lib()
        try:
            pins = location_lib.resolve_locations(args.location)
        except location_lib.LocationError as e:
            print("Error: %s" % e, file=sys.stderr)
            return 2
        location_strength = (args.location_strength if args.location_strength is not None
                             else location_lib.DEFAULT_LOCATION_STRENGTH)
        if not 0 < location_strength <= 1.0:
            print("Error: --location-strength must be in (0, 1], got %r" % location_strength,
                  file=sys.stderr)
            return 2
        per_panel, note = location_lib.plan_panel_locations(
            os.path.dirname(os.path.abspath(args.story_md)), len(panels),
            [pin.name for pin in pins])
        if note is not None:
            print(note)
        for pin in pins:
            if not pin.stills_lora:
                print("WARNING: location %s has no stills LoRA (%s); its trigger is not added to "
                      "Image: prompts and its panels render without it"
                      % (pin.name, pin.stills_skip_reason or "not trained"))
        by_pin = dict((pin.name, pin) for pin in pins)
        for i in selected_indices:
            if args.seed_image is not None and i == 1:
                continue
            pin = by_pin.get(per_panel[i - 1])
            if pin is not None and pin.stills_lora:
                loc_plans[i] = (pin.trigger, {"kind": "location", "name": pin.name,
                                              "path": pin.stills_lora,
                                              "strength": (pin.strength if pin.strength is not None
                                                           else location_strength)})
    import ltx2_mlx_video_skill
```

**3.5.** Edit `bin/ltx-story-images`: replace this text, which occurs exactly once:

```python
    if len(parsed) == 1 and parsed[0][1] == 1.0 and not any(v[1] for v in char_plans.values()):
```

with:

```python
    if (len(parsed) == 1 and parsed[0][1] == 1.0 and not any(v[1] for v in char_plans.values())
            and not loc_plans):
```

**3.6.** Edit `bin/ltx-story-images`: replace this text, which occurs exactly once:

```python
        for m in members:
            if m.stills_lora and os.path.realpath(m.stills_lora) in seen:
                print("Error: --lora %s is also character %s's stills LoRA; pass it once"
                      % (seen[os.path.realpath(m.stills_lora)], m.name), file=sys.stderr)
                return 2
    if members or global_stills:
        for i in selected_indices:
            if args.seed_image is not None and i == 1:
                continue
            prompt, chars = char_plans.get(i, (compose(panels[i - 1]["image"], style), []))
            plans[i] = (prompt, global_stills + chars)
```

with:

```python
        for m in members:
            if m.stills_lora and os.path.realpath(m.stills_lora) in seen:
                print("Error: --lora %s is also character %s's stills LoRA; pass it once"
                      % (seen[os.path.realpath(m.stills_lora)], m.name), file=sys.stderr)
                return 2
        for _trigger, entry in loc_plans.values():
            if os.path.realpath(entry["path"]) in seen:
                print("Error: --lora %s is also location %s's stills LoRA; pass it once"
                      % (seen[os.path.realpath(entry["path"])], entry["name"]), file=sys.stderr)
                return 2
    if members or global_stills or loc_plans:
        for i in selected_indices:
            if args.seed_image is not None and i == 1:
                continue
            prompt, chars = char_plans.get(i, (compose(panels[i - 1]["image"], style), []))
            if i in loc_plans:
                trigger, entry = loc_plans[i]
                plans[i] = (location_lib.prefix_location_trigger(prompt, trigger),
                            global_stills + [entry] + chars)
            else:
                plans[i] = (prompt, global_stills + chars)
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_pipeline.py tests/test_ltx_story_images.py tests/test_shots_mode.py 2>&1 | tail -1
```

Expected: every test passes. Run the compile check with `FILES` = `bin/ltx-story-images tests/test_location_pipeline.py`; expected: `compiled 2` twice. Then run the gate block with `N=8`. Expected: `GATE PASS`, `new-file tests 81, not passing 0`, `baseline failures still failing 2 of 2`, `OK 347/347`, and the two listed LOST lines of Task 6.

- [ ] **Step 5: Commit.**

```bash
git add bin/ltx-story-images tests/test_location_pipeline.py
git diff --cached --name-only    # expected: those 2 paths
git commit -m "feat(ltx-story-images): --location generates the panels set at a location with its stills LoRA and trigger (L3.8; LP10-LP12)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: `bin/ltx-mlx-render`: the location LoRA between style and characters (L3.9, L2.5; LP14-LP19)

This task implements:
- L3.9 `load_manifest`: an optional `locations` list per panel, validated in the spec's message order: a list; each entry a dict with a non-empty `name`; at most one per panel; an absolute readable `video_lora`; a number (not bool) strength in `(0, 1]`.
- L3.9 `build_units`: `{"kind": "location", "name", "path", "strength": float}` between the catalog style units and the characters.
- L2.5, L3.9: `use_video_only_character_loras` rewrites kinds `("character", "location")`.
- L3.9 `main`: `location_entries`; the legacy route also needs `not location_entries`; a global `--lora` or a catalog LoRA equal to a location LoRA is refused with the spec's two messages.
- Provenance includes the location LoRA through the existing unit loop; a panel without one keeps identical provenance (LP19), so `--resume` reuses it.

**Files:**
- Modify: `bin/ltx-mlx-render`: after the `characters` block (`:254-257`), `build_units` (`:360-361`), `use_video_only_character_loras` (`:523-527`), `main` (`:1209-1211`, `:1229-1231`, `:1241-1245`).
- Modify: `tests/test_location_pipeline.py` (append).
- Read only: `bin/ltx-mlx-render` (`build_clip_provenance` `:531-565`, `print_dry_run` `:857-891`), `tests/test_video_only_lora.py`.

**Interfaces:**
- Consumes: manifest panels with `"locations"` (Task 7's shape).
- Produces, in `bin/ltx-mlx-render`: unit LoRAs of kind `"location"`; `build_clip_provenance` entries of kind `"location"`.
- Produces, in the tests: `render`, `_render_at_d210c26(tmp_path)`, `_lora(tmp_path, name)`, `_render_panels(tmp_path, with_location=True)`, `_manifest_file(tmp_path, panels, name="manifest.json")`, `_render_dry_run(tmp_path, panels, *extra)`, `_audio_lora(path)`.

- [ ] **Step 1: Write the failing tests.**

**1.1.** Edit `tests/test_location_pipeline.py`: replace this text, which occurs exactly once:

```python
    assert source.count("_panel_seed(args.seed, i, grounded)") == 2
```

with:

```python
    assert source.count("_panel_seed(args.seed, i, grounded)") == 2


# --- LP14-LP19: bin/ltx-mlx-render (L3.9) ------------------------------------------------------

render = _load("ltx_mlx_render_for_location", os.path.join("bin", "ltx-mlx-render"))


def _render_at_d210c26(tmp_path):
    """bin/ltx-mlx-render as it was at d210c26, loaded from git show (skips outside a git
    checkout that has d210c26)."""
    old = subprocess.run(["git", "-C", WS, "show", "d210c26:./bin/ltx-mlx-render"],
                         capture_output=True, text=True)
    if old.returncode != 0:
        pytest.skip("not a git checkout with d210c26")
    path = str(tmp_path / "ltx_mlx_render_d210c26.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(old.stdout)
    return importlib.machinery.SourceFileLoader("ltx_mlx_render_d210c26", path).load_module()


def _lora(tmp_path, name):
    return seu.lora_file(str(tmp_path / "loras"), name)


def _render_panels(tmp_path, with_location=True):
    """Three t2v panels: panel 2 has a character, a catalog style and a catalog motion LoRA and,
    with_location, a location."""
    character, style, motion, place = (_lora(tmp_path, n) for n in ("kyra", "grain", "fast",
                                                                     "harbour"))
    catalog = [{"id": "film-grain", "kind": "style", "path": style,
                "sha256": seu.sha256_file(style), "strength": 0.6, "triggers": []},
               {"id": "fast-motion", "kind": "motion", "path": motion,
                "sha256": seu.sha256_file(motion), "strength": 0.7, "triggers": []}]
    panels = [{"index": k, "image_path": None, "panel_text": "text %d" % k,
               "motion_prompt": "motion %d" % k, "conditioning": "t2v"} for k in (1, 2, 3)]
    panels[1]["characters"] = [{"name": "kyra", "phrase": "the woman in grey",
                                "trigger": "kyrawmn", "video_lora": character, "strength": 0.8}]
    panels[1]["catalog_loras"] = catalog
    if with_location:
        panels[1]["locations"] = [{"name": "harbour-street", "video_lora": place,
                                   "strength": 0.8}]
    return panels, place


def test_lp14_the_render_unit_order(tmp_path):
    panels, place = _render_panels(tmp_path)
    globals_ = [{"path": _lora(tmp_path, "global"), "strength": 1.0}]
    units = render.build_units(json.loads(json.dumps(panels)), 0, "/clips", global_loras=globals_)
    assert [(l["kind"], l["name"]) for l in units[1]["loras"]] == [
        ("catalog", "fast-motion"), ("global", None), ("catalog", "film-grain"),
        ("location", "harbour-street"), ("character", "kyra")]
    assert units[1]["loras"][3] == {"kind": "location", "name": "harbour-street", "path": place,
                                    "strength": 0.8}
    assert "loras" in units[0] and [l["kind"] for l in units[0]["loras"]] == ["global"]
    old = _render_at_d210c26(tmp_path)
    plain, _place = _render_panels(tmp_path, with_location=False)
    assert render.build_units(json.loads(json.dumps(plain)), 0, "/clips",
                              global_loras=globals_) == old.build_units(
        json.loads(json.dumps(plain)), 0, "/clips", global_loras=globals_)


def _manifest_file(tmp_path, panels, name="manifest.json"):
    path = str(tmp_path / name)
    with open(path, "w") as f:
        json.dump({"schema_version": 3, "story_id": "location-lp", "panels": panels}, f)
    return path


def test_lp15_load_manifest_location_errors(tmp_path):
    panels, place = _render_panels(tmp_path)
    assert render.load_manifest(_manifest_file(tmp_path, panels))["panels"][1]["locations"] == [
        {"name": "harbour-street", "video_lora": place, "strength": 0.8}]
    good = {"name": "harbour-street", "video_lora": place, "strength": 0.8}
    for value, message in (
            ("harbour-street", "panel 2: locations must be a list"),
            ([dict(good, name="")], "panel 2: every locations entry needs a non-empty name"),
            (["harbour-street"], "panel 2: every locations entry needs a non-empty name"),
            ([good, dict(good, name="temple-gate")], "panel 2: at most one location per panel"),
            ([dict(good, video_lora="relative.safetensors")],
             "panel 2: location harbour-street's video_lora is not a readable file: "
             "relative.safetensors"),
            ([dict(good, video_lora=str(tmp_path / "missing.safetensors"))],
             "panel 2: location harbour-street's video_lora is not a readable file: %s"
             % (tmp_path / "missing.safetensors")),
            ([dict(good, strength=1.5)],
             "panel 2: location harbour-street's strength must be a number in (0, 1], got 1.5"),
            ([dict(good, strength=True)],
             "panel 2: location harbour-street's strength must be a number in (0, 1], got True")):
        bad = json.loads(json.dumps(panels))
        bad[1]["locations"] = value
        with pytest.raises(ValueError) as info:
            render.load_manifest(_manifest_file(tmp_path, bad))
        assert str(info.value) == message, value
    empty = json.loads(json.dumps(panels))
    empty[1]["locations"] = []
    render.load_manifest(_manifest_file(tmp_path, empty))


def _render_dry_run(tmp_path, panels, *extra):
    model = tmp_path / "model"
    model.mkdir(exist_ok=True)
    return render.main([_manifest_file(tmp_path, panels), str(tmp_path / "out.mp4"), "--dry-run",
                        "--model", str(model), "--clips-dir", str(tmp_path / "clips")]
                       + list(extra))


def test_lp16_render_refuses_a_location_lora_given_twice(tmp_path, capsys):
    panels, place = _render_panels(tmp_path)
    assert _render_dry_run(tmp_path, panels, "--lora", place + ":0.5") == 2
    assert capsys.readouterr().err == (
        "Error: --lora %s is also location harbour-street's video LoRA (panel 2); pass it once\n"
        % place)
    twice = json.loads(json.dumps(panels))
    twice[1]["catalog_loras"][0]["path"] = place
    twice[1]["catalog_loras"][0]["sha256"] = seu.sha256_file(place)
    assert _render_dry_run(tmp_path, twice) == 2
    assert capsys.readouterr().err == (
        "Error: catalog LoRA film-grain (panel 2) is also location harbour-street's video LoRA\n")


def test_lp17_a_location_panel_takes_the_merged_route(tmp_path, capsys):
    panels = [{"index": 1, "image_path": None, "panel_text": "text", "motion_prompt": "motion",
               "conditioning": "t2v",
               "locations": [{"name": "harbour-street", "video_lora": _lora(tmp_path, "place"),
                              "strength": 0.8}]}]
    one = _lora(tmp_path, "global")
    assert _render_dry_run(tmp_path, panels, "--lora", one) == 0
    out = capsys.readouterr().out
    assert "            lora: %s @ 1.0 (global)\n" % one in out
    assert "            lora: %s @ 0.8 (harbour-street)\n" % panels[0]["locations"][0][
        "video_lora"] in out
    plain = [dict(panels[0])]
    del plain[0]["locations"]
    assert _render_dry_run(tmp_path, plain, "--lora", one) == 0
    assert "(global)" not in capsys.readouterr().out


def _audio_lora(path):
    """A safetensors LoRA with one video and one audio-stream module (tests/
    test_video_only_lora.py's layout)."""
    import struct
    header, data = {"__metadata__": {"lora_alpha": "8"}}, b""
    for i, module in enumerate(("attn1.to_q", "audio_attn1.to_q")):
        for j, part in enumerate(("lora_A", "lora_B")):
            name = "diffusion_model.transformer_blocks.0." + module + "." + part + ".weight"
            header[name] = {"dtype": "F32", "shape": [1], "data_offsets": [len(data), len(data) + 4]}
            data += struct.pack("<f", float(10 * i + j + 1))
    blob = json.dumps(header).encode("utf-8")
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(blob)) + blob + data)
    return path


def test_lp18_location_loras_render_without_audio_modules(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "VIDEO_ONLY_LORA_DIR", str(tmp_path / "cache"))
    src = _audio_lora(str(tmp_path / "place.safetensors"))
    units = [{"loras": [{"kind": "location", "path": src}, {"kind": "global", "path": src},
                        {"kind": "character", "path": src}]}]
    render.use_video_only_character_loras(units)
    location, global_lora, character = [l["path"] for l in units[0]["loras"]]
    assert location == character != src and global_lora == src
    assert os.path.dirname(location) == str(tmp_path / "cache")
    with open(location, "rb") as f:
        import struct
        header = json.loads(f.read(struct.unpack("<Q", f.read(8))[0]))
    assert sorted(k for k in header if k != "__metadata__") == [
        "diffusion_model.transformer_blocks.0.attn1.to_q.lora_A.weight",
        "diffusion_model.transformer_blocks.0.attn1.to_q.lora_B.weight"]


def test_lp19_provenance_changes_only_for_the_location_panel(tmp_path):
    old = _render_at_d210c26(tmp_path)
    model = tmp_path / "model"
    model.mkdir()
    args = render.build_parser().parse_args([str(tmp_path / "m.json"), str(tmp_path / "o.mp4"),
                                             "--model", str(model)])
    plain, _place = _render_panels(tmp_path, with_location=False)
    located, _place = _render_panels(tmp_path)
    before = [old.build_clip_provenance(u, args)
              for u in old.build_units(json.loads(json.dumps(plain)), 0, "/clips")]
    after = [render.build_clip_provenance(u, args)
             for u in render.build_units(json.loads(json.dumps(located)), 0, "/clips")]
    unchanged = [render.build_clip_provenance(u, args)
                 for u in render.build_units(json.loads(json.dumps(plain)), 0, "/clips")]
    assert unchanged == before
    assert (after[0], after[2]) == (before[0], before[2])
    assert after[1] != before[1]
    assert [l["kind"] for l in after[1]["loras"]] == ["catalog", "catalog", "location", "character"]
    assert after[1]["loras"][2]["sha256"] == seu.sha256_file(located[1]["locations"][0]["video_lora"])
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_pipeline.py 2>&1 | tail -1
```

Expected: `6 failed, 10 passed` (LP14-LP19).

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/ltx-mlx-render`: replace this text, which occurs exactly once:

```python
                if (isinstance(strength, bool) or not isinstance(strength, (int, float))
                        or not 0 < strength <= 1.0):
                    raise ValueError("panel %d: character %s's strength must be a number in (0, 1], "
                                     "got %r" % (index, name, strength))
```

with:

```python
                if (isinstance(strength, bool) or not isinstance(strength, (int, float))
                        or not 0 < strength <= 1.0):
                    raise ValueError("panel %d: character %s's strength must be a number in (0, 1], "
                                     "got %r" % (index, name, strength))

        # Location library spec L3.9: an optional list of at most one pinned location.
        if "locations" in panel:
            locations = panel["locations"]
            if not isinstance(locations, list):
                raise ValueError("panel %d: locations must be a list" % index)
            for entry in locations:
                name = entry.get("name") if isinstance(entry, dict) else None
                if not isinstance(name, str) or not name:
                    raise ValueError("panel %d: every locations entry needs a non-empty name"
                                     % index)
            if len(locations) > 1:
                raise ValueError("panel %d: at most one location per panel" % index)
            for entry in locations:
                lora = entry.get("video_lora")
                if (not isinstance(lora, str) or not os.path.isabs(lora) or not os.path.isfile(lora)
                        or not os.access(lora, os.R_OK)):
                    raise ValueError("panel %d: location %s's video_lora is not a readable file: %s"
                                     % (index, entry["name"], lora))
                strength = entry.get("strength")
                if (isinstance(strength, bool) or not isinstance(strength, (int, float))
                        or not 0 < strength <= 1.0):
                    raise ValueError("panel %d: location %s's strength must be a number in (0, 1], "
                                     "got %r" % (index, entry["name"], strength))
```

**3.2.** Edit `bin/ltx-mlx-render`: replace this text, which occurs exactly once:

```python
        loras += catalog_units[n_lead:]
        loras += [{"kind": "character", "name": c["name"], "path": c["video_lora"],
```

with:

```python
        loras += catalog_units[n_lead:]
        loras += [{"kind": "location", "name": l["name"], "path": l["video_lora"],
                   "strength": float(l["strength"])} for l in (panel.get("locations") or [])]
        loras += [{"kind": "character", "name": c["name"], "path": c["video_lora"],
```

**3.3.** Edit `bin/ltx-mlx-render`: replace this text, which occurs exactly once:

```python
def use_video_only_character_loras(units):
    """Point every character LoRA of units at its video_only_lora copy (in place)."""
    for unit in units:
        for lora in unit.get("loras") or ():
            if lora["kind"] == "character":
```

with:

```python
def use_video_only_character_loras(units):
    """Point every character and location LoRA of units at its video_only_lora copy (in place;
    location library spec L3.9)."""
    for unit in units:
        for lora in unit.get("loras") or ():
            if lora["kind"] in ("character", "location"):
```

**3.4.** Edit `bin/ltx-mlx-render`: replace this text, which occurs exactly once:

```python
    catalog_entries = [(p["index"], e) for p in panels for e in (p.get("catalog_loras") or [])]
    args.global_loras = []
    if len(parsed) == 1 and parsed[0][1] == 1.0 and not cast_entries and not catalog_entries:
```

with:

```python
    catalog_entries = [(p["index"], e) for p in panels for e in (p.get("catalog_loras") or [])]
    location_entries = [(p["index"], l) for p in panels for l in (p.get("locations") or [])]
    args.global_loras = []
    if (len(parsed) == 1 and parsed[0][1] == 1.0 and not cast_entries and not catalog_entries
            and not location_entries):
```

**3.5.** Edit `bin/ltx-mlx-render`: replace this text, which occurs exactly once:

```python
                print("Error: --lora %s is also character %s's video LoRA (panel %d); pass it "
                      "once" % (seen[real], c["name"], index), file=sys.stderr)
                return 2
```

with:

```python
                print("Error: --lora %s is also character %s's video LoRA (panel %d); pass it "
                      "once" % (seen[real], c["name"], index), file=sys.stderr)
                return 2
        for index, l in location_entries:
            real = os.path.realpath(l["video_lora"])
            if real in seen:
                print("Error: --lora %s is also location %s's video LoRA (panel %d); pass it "
                      "once" % (seen[real], l["name"], index), file=sys.stderr)
                return 2
```

**3.6.** Edit `bin/ltx-mlx-render`: replace this text, which occurs exactly once:

```python
            for c in by_index[index].get("characters") or []:
                if os.path.realpath(c["video_lora"]) == real:
                    print("Error: catalog LoRA %s (panel %d) is also character %s's video LoRA"
                          % (entry["id"], index, c["name"]), file=sys.stderr)
                    return 2
```

with:

```python
            for c in by_index[index].get("characters") or []:
                if os.path.realpath(c["video_lora"]) == real:
                    print("Error: catalog LoRA %s (panel %d) is also character %s's video LoRA"
                          % (entry["id"], index, c["name"]), file=sys.stderr)
                    return 2
            for l in by_index[index].get("locations") or []:
                if os.path.realpath(l["video_lora"]) == real:
                    print("Error: catalog LoRA %s (panel %d) is also location %s's video LoRA"
                          % (entry["id"], index, l["name"]), file=sys.stderr)
                    return 2
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_pipeline.py tests/test_ltx_mlx_render.py tests/test_video_only_lora.py 2>&1 | tail -1
```

Expected: every test passes. Run the compile check with `FILES` = `bin/ltx-mlx-render tests/test_location_pipeline.py`; expected: `compiled 2` twice. Then run the gate block with `N=9`. Expected: `GATE PASS`, `new-file tests 87, not passing 0`, `baseline failures still failing 2 of 2`, `OK 347/347`, and the two listed LOST lines of Task 6.

- [ ] **Step 5: Commit.**

```bash
git add bin/ltx-mlx-render tests/test_location_pipeline.py
git diff --cached --name-only    # expected: those 2 paths
git commit -m "feat(ltx-mlx-render): fuse a panel's location LoRA between the style and the characters, audio-stripped, and refuse it twice (L3.9, L2.5; LP14-LP19)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: `bin/ltx-movie` and `bin/iterate-story`: pin, check, pass on (L3.1, L3.2, L3.8 movie, L3.10, L3.11; LP1-LP4, LP13, LP20, LS7)

This task implements:
- L3.1: `--location` (dest `locations`, append) and `--location-strength`, verbatim from the spec, directly after `--character-strength`.
  - `_resolve_story_engine`'s legacy list gains `("--location", bool(args.locations))`.
  - `_location_lib()`.
  - `_resolve_locations(args)`, called in `main` right after `_resolve_story_engine`, with the spec's seven steps in order. It sets `args.location_pins` and `args.location_strength`.
- L3.2: `_check_story_locations(args, names)`, the existing-story check, runs with and without `--location` (Plan ruling LR4): a different set in either direction exits 2; no usable `plan.json` gives the note only when `--location` is given.
- L3.8: `_location_flags(args, video=False)` is appended right after `_cast_flags(args)` in `phase2_stills` and the dry run's Phase 2 (stills), and in `phase3_manifest` and the dry run's Phase 3 (`video=True`).
  - `_shots_stills_groups(story_md_path, members, locations=())` splits by `location NAME`; both callers pass the pins.
  - The dry run prints `--- Locations ---` after the cast block.
  - `_story_context` passes `locations`.
- L3.10: no new code (`_phase1_robust` is unchanged).
- L3.11: `bin/iterate-story`'s `build_engine_cmd` passes `--location` for each plan location with a `location_name`, at the default strength.

The new code adds no occurrence of the strings `tests/test_ltx_movie_offline.py` counts, and no import (`test_rst62`'s `bin/ltx-movie` set is unchanged). `_location_lib()` loads `location_lib.py` from this tool's own workspace, not `WS`, so a test that points `WS` at a partial workspace (`tests/test_shots_mode.py`'s `movie_ws`) still gets it for the reused-story check (Plan ruling LR30). `bin/iterate-story` is folded into this task because its change is four lines with one test (Plan ruling LR27).

**Files:**
- Modify: `bin/ltx-movie`: the parser (`:359-360`), after `_character_lib` (`:790-794`), after `_resolve_casting` (`:891-893`), the legacy list (`:1046-1047`), after `_cast_flags` (`:1144`), `_story_context` (`:1523`), `phase2_stills` (`:1928-1931`), `_shots_stills_groups` (`:1951-1956`, `:1966-1968`), `_phase2_shots` (`:1990-1991`), `phase3_manifest` (`:2118`), `_print_shots_stills_plan` (`:2345-2346`), the dry-run cast block (`:2389-2392`), the dry-run Phase 2 (`:2446-2447`) and Phase 3 (`:2472`), `main` (`:2588-2592`).
- Modify: `bin/iterate-story`: `build_engine_cmd` (`:270-272`).
- Modify: `tests/test_location_pipeline.py`, `tests/test_location_story.py` (append).

**Interfaces:**
- Consumes: Task 2's `resolve_locations`, `UnusableLocationError`, `LocationError`, `usable_locations`, `format_available_line`, `model_compatible`, `plan_location_names`, `plan_panel_locations`, `DEFAULT_LOCATION_STRENGTH`; Task 6's `StoryContext.locations`; Tasks 7 and 8's `--location`/`--location-strength`.
- Produces, in `bin/ltx-movie`: `args.locations`, `args.location_strength`, `args.location_pins` (`[LocationPin]`, `attach_video` False on a model mismatch), `_location_lib()`, `_resolve_locations(args) -> 0 | 2`, `_check_story_locations(args, names) -> 0 | 2`, `_location_flags(args, video=False) -> [str]`, `_shots_stills_groups(story_md_path, members, locations=())`.
- Produces, in `bin/iterate-story`: `build_engine_cmd(...)` with `--location NAME` after the `--character` flags.
- Produces, in the tests: `ltx_movie`, `NARRATIVE`, the `movie` fixture, `_movie_args(*argv)`, `_existing_story(movie, story_id, pinned)`, `iterate_story`.

- [ ] **Step 1: Write the failing tests.**

**1.1.** Edit `tests/test_location_pipeline.py`: replace this text, which occurs exactly once:

```python
    assert after[1]["loras"][2]["sha256"] == seu.sha256_file(located[1]["locations"][0]["video_lora"])
```

with:

```python
    assert after[1]["loras"][2]["sha256"] == seu.sha256_file(located[1]["locations"][0]["video_lora"])


# --- LP1-LP4, LP13: bin/ltx-movie (L3.1, L3.2, L3.8) --------------------------------------------

ltx_movie = _load("ltx_movie_for_location", os.path.join("bin", "ltx-movie"))
NARRATIVE = "A courier carries a sealed letter across a rainy harbour town to a temple gate."


@pytest.fixture
def movie(tmp_path, monkeypatch):
    """A temp workspace with the fake agent; ltx_movie.WS points at it; no sudo check."""
    ws = seu.make_ws(tmp_path)
    monkeypatch.setattr(ltx_movie, "WS", ws)
    monkeypatch.setattr(ltx_movie, "_check_sudo_and_start_keepalive", lambda: None)
    return ws


def _movie_args(*argv):
    """bin/ltx-movie's args after every resolver that runs before _resolve_locations."""
    args = ltx_movie.build_parser().parse_args(list(argv))
    args.video_width, args.video_height = 704, 448
    for resolve in (ltx_movie._resolve_shots, ltx_movie._resolve_casting,
                    ltx_movie._resolve_global_loras, ltx_movie._resolve_story_engine):
        assert resolve(args) == 0
    return args


def test_lp1_resolve_locations(movie, capsys, story_env):
    harbour = lt.harbour(story_env["locations"])
    args = _movie_args(NARRATIVE, "--story-id", "lp1")
    assert ltx_movie._resolve_locations(args) == 0 and args.location_pins == []
    args = _movie_args(NARRATIVE, "--story-id", "lp1", "--location", "harbour-street")
    assert ltx_movie._resolve_locations(args) == 0
    assert [p.name for p in args.location_pins] == ["harbour-street"]
    assert args.location_pins[0].attach_video is True and args.location_strength == 0.8
    assert args.location_pins[0].video_lora == harbour["loras"]["video"]["path"]
    capsys.readouterr()
    for extra, message in (
            (["--location-strength", "0.5"], "Error: --location-strength requires --location"),
            (["--location", "harbour-street", "--no-stills"],
             "Error: --location is not supported with --no-stills: location LoRAs attach to "
             "chained or shots panels"),
            (["--location", "harbour-street", "--location-strength", "1.5"],
             "Error: --location-strength must be in (0, 1], got 1.5"),
            (["--location", "harbour-street", "--story-legacy"],
             "Error: --location needs the default story engine; it cannot be combined with "
             "--story-legacy")):
        assert ltx_movie.main([NARRATIVE, "--story-id", "lp1", "--dry-run"] + extra) == 2, extra
        assert capsys.readouterr().err == message + "\n", extra
    assert ltx_movie.main([NARRATIVE, "--story-id", "lp1", "--dry-run", "--location",
                           "nowhere"]) == 2
    assert capsys.readouterr().err == (
        "Error: unknown location: nowhere (no %s)\navailable locations: harbour-street\n"
        % os.path.join(story_env["locations"], "nowhere", "location.json"))
    seu.kyra(story_env["lib"])
    lt.make_location(story_env["locations"], "kyra-quay", "kyrawmn", lt.MILL_DESC)
    assert ltx_movie.main([NARRATIVE, "--story-id", "lp1", "--dry-run", "--character", "kyra",
                           "--location", "kyra-quay"]) == 2
    assert capsys.readouterr().err == (
        "Error: location kyra-quay and character kyra share the trigger kyrawmn\n")


def test_lp2_a_model_mismatch_drops_only_the_video_lora(movie, capsys, story_env):
    lt.harbour(story_env["locations"], stills=True)
    model = "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8"
    args = _movie_args(NARRATIVE, "--story-id", "lp2", "--location", "harbour-street",
                       "--model", model)
    capsys.readouterr()
    assert ltx_movie._resolve_locations(args) == 0
    assert capsys.readouterr().err == (
        "Warning: location harbour-street's video LoRA was trained for dgrauet/ltx-2.3-mlx-q8, "
        "not --model %s; it is not attached, and the panels set there render without it (its "
        "setting and stills LoRA still apply)\n" % model)
    assert args.location_pins[0].attach_video is False
    assert ltx_movie._location_flags(args, video=True) == []
    assert ltx_movie._location_flags(args) == ["--location", "harbour-street",
                                               "--location-strength", "0.8"]
    assert ltx_movie._story_context(args).locations == args.location_pins


def _existing_story(movie, story_id, pinned):
    story_dir = os.path.join(movie, "generated", "stories", story_id)
    os.makedirs(story_dir)
    with open(os.path.join(story_dir, "story.md"), "w") as f:
        f.write("# T\n\n## Panel 1 — A\nImage: x\nMotion: y\n")
    if pinned is not None:
        lt.write_plan(story_dir, ["l1"], pinned=pinned)
    return story_dir


def test_lp3_an_existing_story_keeps_its_locations(movie, capsys, story_env):
    lt.harbour(story_env["locations"])
    lt.temple(story_env["locations"])
    _existing_story(movie, "lp3", (("l1", "harbour-street"),))
    args = _movie_args(NARRATIVE, "--story-id", "lp3", "--location", "harbour-street")
    assert ltx_movie._resolve_locations(args) == 0
    capsys.readouterr()
    for flags, given in ((["--location", "temple-gate"], "temple-gate"),
                         (["--location", "harbour-street", "--location", "temple-gate"],
                          "harbour-street, temple-gate"), ([], "none")):
        args = _movie_args(NARRATIVE, "--story-id", "lp3", *flags)
        assert ltx_movie._resolve_locations(args) == 2, flags
        assert capsys.readouterr().err == (
            "Error: story lp3 was planned with the locations [harbour-street], not --location "
            "[%s]; pass the same --location flags, or --force-story to plan a new story\n" % given)
    _existing_story(movie, "lp3b", ())
    args = _movie_args(NARRATIVE, "--story-id", "lp3b", "--location", "harbour-street")
    assert ltx_movie._resolve_locations(args) == 2
    assert "planned with the locations [none], not --location [harbour-street]" in (
        capsys.readouterr().err)
    args = _movie_args(NARRATIVE, "--story-id", "lp3b")
    assert ltx_movie._resolve_locations(args) == 0 and args.location_pins == []
    args = _movie_args(NARRATIVE, "--story-id", "lp3", "--location", "temple-gate",
                       "--force-story")
    assert ltx_movie._resolve_locations(args) == 0
    story_dir = _existing_story(movie, "lp3c", None)
    args = _movie_args(NARRATIVE, "--story-id", "lp3c", "--location", "harbour-street")
    assert ltx_movie._resolve_locations(args) == 0
    assert capsys.readouterr().out == (
        "note: %s is not a usable plan; --location gets no LoRA in this story (location LoRAs "
        "attach only to planned beats)\n" % os.path.join(story_dir, "plan.json"))
    assert ltx_movie._resolve_locations(_movie_args(NARRATIVE, "--story-id", "lp3c")) == 0
    assert capsys.readouterr().out == ""


def test_lp4_the_dry_run_lists_the_locations(movie, capsys, story_env):
    harbour = lt.harbour(story_env["locations"])
    capsys.readouterr()
    assert ltx_movie.main([NARRATIVE, "--story-id", "lp4", "--panels", "3", "--dry-run",
                           "--no-review", "--location", "harbour-street",
                           "--location-strength", "0.7"]) == 0
    out = capsys.readouterr().out
    assert ("--- Locations ---\nlocation: harbour-street (trigger harboplc; video LoRA %s; stills "
            "LoRA none: not trained; strength 0.7)\n\n" % harbour["loras"]["video"]["path"]) in out
    phase2 = [l for l in out.splitlines() if "ltx-story-images" in l and l.startswith("Command:")]
    phase3 = [l for l in out.splitlines() if "ltx-story-manifest" in l and l.startswith("Command:")]
    assert len(phase2) == 1 and phase2[0].endswith(
        " --location harbour-street --location-strength 0.7")
    assert len(phase3) == 1 and phase3[0].endswith(
        " --force --location harbour-street --location-strength 0.7")
    assert not os.path.exists(os.path.join(movie, "generated", "stories", "lp4"))
    assert ltx_movie.main([NARRATIVE, "--story-id", "lp4", "--panels", "3", "--dry-run",
                           "--no-review", "--location", "harbour-street", "--model",
                           "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8"]) == 0
    out = capsys.readouterr().out
    assert "strength 0.8) -- video LoRA not attached: trained for dgrauet/ltx-2.3-mlx-q8\n" in out
    phase3 = [l for l in out.splitlines() if "ltx-story-manifest" in l and l.startswith("Command:")]
    assert "--location" not in phase3[0]
    plain = ltx_movie.main([NARRATIVE, "--story-id", "lp4", "--panels", "3", "--dry-run",
                            "--no-review"])
    assert plain == 0 and "Locations" not in capsys.readouterr().out


def test_lp13_shots_stills_groups_split_by_location(movie, tmp_path, story_env):
    lt.harbour(story_env["locations"], stills=True)
    lt.temple(story_env["locations"])
    story_md, _out = _images_story(tmp_path, pinned=(("l1", "harbour-street"),
                                                     ("l2", "temple-gate")))
    pins = ltx_movie._location_lib().resolve_locations(["harbour-street", "temple-gate"])
    assert ltx_movie._shots_stills_groups(story_md, []) == [((), [1, 2, 3])]
    assert ltx_movie._shots_stills_groups(story_md, [], []) == [((), [1, 2, 3])]
    assert ltx_movie._shots_stills_groups(story_md, [], pins) == [
        ((), [2]), (("location harbour-street",), [1, 3])]
    seu.kyra(story_env["lib"])
    members = ltx_movie._character_lib().resolve_cast([(None, "kyra")])
    assert ltx_movie._shots_stills_groups(story_md, members, pins) == [
        (("kyra",), [2]), (("kyra", "location harbour-street"), [1, 3])]


# --- LP20: bin/iterate-story regenerates with the plan's locations (L3.11) ---------------------

iterate_story = _load("iterate_story_for_location", os.path.join("bin", "iterate-story"))


def test_lp20_iterate_story_passes_the_pinned_locations():
    plan = {"narrative": NARRATIVE, "panels": 3, "mode": "chained", "seed_image": None,
            "goal": None, "cast": [{"id": "c1", "phrase": "the woman in grey",
                                    "cast_name": "kyra"}],
            "locations": [{"id": "l1", "setting": "x", "location_name": "harbour-street"},
                          {"id": "l2", "setting": "y", "location_name": None},
                          {"id": "l3", "setting": "z", "location_name": "temple-gate"}],
            "loras": {"pinned": []}}
    cmd = iterate_story.build_engine_cmd("s", plan)
    assert cmd[cmd.index("--character"):cmd.index("--force-story")] == [
        "--character", "kyra", "--location", "harbour-street", "--location", "temple-gate"]
    for locations in ([{"id": "l1", "setting": "x", "location_name": None}], [{"id": "l1"}],
                      ["l1"]):
        assert "--location" not in iterate_story.build_engine_cmd("s", dict(plan,
                                                                            locations=locations))
    old = dict(plan)
    del old["locations"]
    assert "--location" not in iterate_story.build_engine_cmd("s", old)
```

**1.2.** Edit `tests/test_location_story.py`: replace this text, which occurs exactly once:

```python
    rc, _advisories = se.recheck(ctx, lambda path, panels, no_stills=False: [])
    assert rc == 0
```

with:

```python
    rc, _advisories = se.recheck(ctx, lambda path, panels, no_stills=False: [])
    assert rc == 0


# --- LS7: the plan retry end to end through bin/ltx-movie (L3.5) -------------------------------

ltx_movie = _load("ltx_movie_for_location_story", os.path.join("bin", "ltx-movie"))


@pytest.fixture
def movie(tmp_path, monkeypatch):
    """A temp workspace with the fake agent; ltx_movie.WS points at it; no sudo check."""
    ws = seu.make_ws(tmp_path)
    monkeypatch.setattr(ltx_movie, "WS", ws)
    monkeypatch.setattr(ltx_movie, "_check_sudo_and_start_keepalive", lambda: None)
    return ws


def test_ls7_a_plan_without_the_location_is_retried(movie, tmp_path, monkeypatch, story_env):
    lt.harbour(story_env["locations"])
    log = seu.script_agent(
        monkeypatch, tmp_path,
        plan=[seu.answer(_raw("chained", 3, ["l2", "l2", "l2"])),
              seu.answer(_raw("chained", 3, ["l1", "l2", "l1"]))],
        panel=dict((str(k), [seu.answer(seu.panel_json("chained", k))]) for k in range(1, 4)))
    rc = ltx_movie.main(["A courier carries a sealed letter across a rainy harbour town.",
                         "--story-id", "ls7", "--panels", "3",
                         "--location", "harbour-street", "--story-only", "--no-review"])
    log = seu.agent_log(log)
    assert rc == 0
    assert [r["stage"] for r in log][:3] == ["plan", "plan", "panel"]
    assert ("YOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- "
            + P21 % ("l1", "harbour-street", "l1") + "\n") in log[1]["argv"][-1]
    with open(os.path.join(movie, "generated", "stories", "ls7", "plan.json")) as f:
        plan = json.load(f)
    assert plan["locations"][0] == {"id": "l1", "setting": se.FIXED_SETTING % lt.HARBOUR_DESC,
                                    "location_name": "harbour-street"}
    assert [b["location"] for b in plan["beats"]] == ["l1", "l2", "l1"]
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_pipeline.py tests/test_location_story.py 2>&1 | tail -1
```

Expected: `7 failed, 31 passed` (LP1-LP4, LP13, LP20 and LS7).

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/iterate-story`: replace this text, which occurs exactly once:

```python
    for entry in plan["cast"]:
        if entry.get("cast_name"):
            cmd += ["--character", entry["cast_name"]]
```

with:

```python
    for entry in plan["cast"]:
        if entry.get("cast_name"):
            cmd += ["--character", entry["cast_name"]]
    # Location library spec L3.11: the plan's pinned locations, at the default strength.
    for entry in plan.get("locations") or []:
        if isinstance(entry, dict) and entry.get("location_name"):
            cmd += ["--location", entry["location_name"]]
```

**3.2.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
                              "every clip of the story, alone or with others; a panel still of "
                              "exactly one character uses 1.0")
```

with:

```python
                              "every clip of the story, alone or with others; a panel still of "
                              "exactly one character uses 1.0")
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

**3.3.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
def _character_lib():
    """character_lib.py, loaded by path and only when casting or --shots is used, so an uncast
    run without --shots never reads it (spec 1.2; shots spec 8)."""
    return importlib.machinery.SourceFileLoader(
        "character_lib", os.path.join(WS, "character_lib.py")).load_module()
```

with:

```python
def _character_lib():
    """character_lib.py, loaded by path and only when casting or --shots is used, so an uncast
    run without --shots never reads it (spec 1.2; shots spec 8)."""
    return importlib.machinery.SourceFileLoader(
        "character_lib", os.path.join(WS, "character_lib.py")).load_module()


def _location_lib():
    """location_lib.py, loaded by path and only when --location is given or an existing story is
    reused (location library spec 1.2, L3.2). It comes from this tool's own workspace, which is WS
    except under a test that points WS at a partial copy of the workspace."""
    return importlib.machinery.SourceFileLoader(
        "location_lib", os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
                                     "location_lib.py")).load_module()
```

**3.4.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    args.character_strength = strength
    args.cast_members = members
    return 0
```

with:

```python
    args.character_strength = strength
    args.cast_members = members
    return 0


def _resolve_locations(args):
    """Validate and resolve --location/--location-strength into args.location_pins (the
    location_lib.LocationPin list) and args.location_strength (location library spec L3.1,
    L3.2). Returns 0, or 2 after one Error: line. Touches nothing."""
    names = args.locations or []
    args.location_pins = []
    if not names:
        if args.location_strength is not None:
            print("Error: --location-strength requires --location", file=sys.stderr)
            return 2
        return _check_story_locations(args, names)
    if args.no_stills:
        print("Error: --location is not supported with --no-stills: location LoRAs attach to "
              "chained or shots panels", file=sys.stderr)
        return 2
    lib = _location_lib()
    strength = (args.location_strength if args.location_strength is not None
                else lib.DEFAULT_LOCATION_STRENGTH)
    if not 0 < strength <= 1.0:
        print("Error: --location-strength must be in (0, 1], got %r" % strength, file=sys.stderr)
        return 2
    try:
        pins = lib.resolve_locations(names)
    except lib.UnusableLocationError as e:
        print("Error: %s" % e, file=sys.stderr)
        print(lib.format_available_line(lib.usable_locations()), file=sys.stderr)
        return 2
    except lib.LocationError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    cast_triggers = dict((m.trigger, m.name) for m in (getattr(args, "cast_members", None) or []))
    for pin in pins:
        if pin.trigger in cast_triggers:
            print("Error: location %s and character %s share the trigger %s"
                  % (pin.name, cast_triggers[pin.trigger], pin.trigger), file=sys.stderr)
            return 2
    for k, pin in enumerate(pins):
        if not lib.model_compatible(pin.base_model, args.model):
            pins[k] = pin._replace(attach_video=False)
            print("Warning: location %s's video LoRA was trained for %s, not --model %s; it is not "
                  "attached, and the panels set there render without it (its setting and stills "
                  "LoRA still apply)" % (pin.name, pin.base_model, args.model), file=sys.stderr)
    rc = _check_story_locations(args, names)
    if rc:
        return rc
    args.location_pins = pins
    args.location_strength = strength
    return 0


def _check_story_locations(args, names):
    """Location library spec L3.2: a reused story.md keeps the locations its plan.json pinned,
    in both directions. Returns 0, or 2 after one Error: line; a story without a usable
    plan.json gets a note when --location is given."""
    story_md = _story_paths(args.story_id)["story_md"]
    if args.force_story or not os.path.exists(story_md):
        return 0
    story_dir = os.path.dirname(story_md)
    found = _location_lib().plan_location_names(story_dir)
    if found is None:
        if names:
            print("note: %s is not a usable plan; --location gets no LoRA in this story (location "
                  "LoRAs attach only to planned beats)" % os.path.join(story_dir, "plan.json"))
        return 0
    if found != set(names):
        print("Error: story %s was planned with the locations [%s], not --location [%s]; pass "
              "the same --location flags, or --force-story to plan a new story"
              % (args.story_id, ", ".join(sorted(found)) or "none",
                 ", ".join(sorted(set(names))) or "none"), file=sys.stderr)
        return 2
    return 0
```

**3.5.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
                            ("--no-narration", args.no_narration),
                            ("--speech-only", args.speech_only)):
```

with:

```python
                            ("--no-narration", args.no_narration),
                            ("--speech-only", args.speech_only),
                            ("--location", bool(args.locations))):
```

**3.6.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    return flags + ["--character-strength", repr(float(args.character_strength))]
```

with:

```python
    return flags + ["--character-strength", repr(float(args.character_strength))]


def _location_flags(args, video=False):
    """--location NAME per pinned location (with video, only those whose video LoRA attaches),
    then --location-strength; [] when none qualifies (location library spec L3.8)."""
    pins = [pin for pin in (getattr(args, "location_pins", None) or [])
            if pin.attach_video or not video]
    if not pins:
        return []
    flags = []
    for pin in pins:
        flags += ["--location", pin.name]
    return flags + ["--location-strength", repr(float(args.location_strength))]
```

**3.7.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
        panels_target=getattr(args, "panels_target", None), length=getattr(args, "length", None))
```

with:

```python
        panels_target=getattr(args, "panels_target", None), length=getattr(args, "length", None),
        locations=list(getattr(args, "location_pins", None) or []))
```

**3.8.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    cmd += catalog_flags
    cmd += _cast_flags(args)
    if getattr(args, "shots", False):
        return _phase2_shots(args, cmd)
```

with:

```python
    cmd += catalog_flags
    cmd += _cast_flags(args)
    cmd += _location_flags(args)
    if getattr(args, "shots", False):
        return _phase2_shots(args, cmd)
```

**3.9.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
def _shots_stills_groups(story_md_path, members):
    """[(names, [panel numbers])]: shots-mode panels grouped by the cast characters whose stills
    LoRAs bin/ltx-story-images will load for them -- the same _compose_prompt(Image:, Style:) +
    cast_text(insert=members with a stills LoRA) match it performs, so every group is one LoRA
    set (shots spec 5.5). Sorted by (len(names), names); panels ascending, 1-based by position.
    Uncast: one group of every panel."""
```

with:

```python
def _shots_stills_groups(story_md_path, members, locations=()):
    """[(names, [panel numbers])]: shots-mode panels grouped by the cast characters whose stills
    LoRAs bin/ltx-story-images will load for them -- the same _compose_prompt(Image:, Style:) +
    cast_text(insert=members with a stills LoRA) match it performs, so every group is one LoRA
    set (shots spec 5.5). Sorted by (len(names), names); panels ascending, 1-based by position.
    Uncast: one group of every panel. A panel whose plan.json beat is set at a pinned location
    with a stills LoRA adds "location NAME" to its names (location library spec L3.8)."""
```

**3.10.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
            by_panel[i] = tuple(lib.cast_text(images._compose_prompt(p["image"], style), members,
                                              insert=insert)[1])
    groups = {}
```

with:

```python
            by_panel[i] = tuple(lib.cast_text(images._compose_prompt(p["image"], style), members,
                                              insert=insert)[1])
    names = [pin.name for pin in locations if pin.stills_lora]
    if names:
        per_panel, _note = _location_lib().plan_panel_locations(os.path.dirname(story_md_path),
                                                                len(panels), names)
        for i, name in enumerate(per_panel, start=1):
            if name is not None:
                by_panel[i] += ("location " + name,)
    groups = {}
```

**3.11.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    groups = _shots_stills_groups(paths["story_md"], getattr(args, "cast_members", None) or [])
    os.makedirs(paths["images_dir"], exist_ok=True)
```

with:

```python
    groups = _shots_stills_groups(paths["story_md"], getattr(args, "cast_members", None) or [],
                                  getattr(args, "location_pins", None) or [])
    os.makedirs(paths["images_dir"], exist_ok=True)
```

**3.12.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    cmd_manifest += _cast_flags(args)
```

with:

```python
    cmd_manifest += _cast_flags(args)
    cmd_manifest += _location_flags(args, video=True)
```

**3.13.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    groups = _shots_stills_groups(story_md, getattr(args, "cast_members", None) or [])
    for k, (names, panels) in enumerate(groups, start=1):
```

with:

```python
    groups = _shots_stills_groups(story_md, getattr(args, "cast_members", None) or [],
                                  getattr(args, "location_pins", None) or [])
    for k, (names, panels) in enumerate(groups, start=1):
```

**3.14.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
            print('cast: %s as "%s" (trigger %s; video LoRA %s; stills LoRA %s)'
                  % (m.name, m.phrase, m.trigger, m.video_lora,
                     m.stills_lora or "none: " + (m.stills_skip_reason or "not trained")))
        print()
```

with:

```python
            print('cast: %s as "%s" (trigger %s; video LoRA %s; stills LoRA %s)'
                  % (m.name, m.phrase, m.trigger, m.video_lora,
                     m.stills_lora or "none: " + (m.stills_skip_reason or "not trained")))
        print()

    if getattr(args, "location_pins", None):
        print("--- Locations ---")
        for pin in args.location_pins:
            strength = pin.strength if pin.strength is not None else args.location_strength
            line = ("location: %s (trigger %s; video LoRA %s; stills LoRA %s; strength %s)"
                    % (pin.name, pin.trigger, pin.video_lora,
                       pin.stills_lora or "none: " + (pin.stills_skip_reason or "not trained"),
                       repr(float(strength))))
            if not pin.attach_video:
                line += " -- video LoRA not attached: trained for %s" % pin.base_model
            print(line)
        print()
```

**3.15.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
        phase2_cmd += catalog_flags
        phase2_cmd += _cast_flags(args)
```

with:

```python
        phase2_cmd += catalog_flags
        phase2_cmd += _cast_flags(args)
        phase2_cmd += _location_flags(args)
```

**3.16.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    phase3_manifest_cmd += _cast_flags(args)
```

with:

```python
    phase3_manifest_cmd += _cast_flags(args)
    phase3_manifest_cmd += _location_flags(args, video=True)
```

**3.17.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    rc = _resolve_story_engine(args)
    if rc:
        return rc

    if args.dry_run:
```

with:

```python
    rc = _resolve_story_engine(args)
    if rc:
        return rc
    rc = _resolve_locations(args)
    if rc:
        return rc

    if args.dry_run:
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_pipeline.py tests/test_location_story.py tests/test_iterate_story.py 2>&1 | tail -1
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1
```

Expected: every test passes; `OK 347/347`. Run the compile check with `FILES` = `bin/ltx-movie bin/iterate-story tests/test_location_pipeline.py tests/test_location_story.py`; expected: `compiled 4` twice. Then run the gate block with `N=10`. Expected: `GATE PASS`, `new-file tests 94, not passing 0`, `baseline failures still failing 2 of 2`, `OK 347/347`, and the two listed LOST lines of Task 6.

- [ ] **Step 5: Commit.**

```bash
git add bin/ltx-movie bin/iterate-story tests/test_location_pipeline.py tests/test_location_story.py
git diff --cached --name-only    # expected: those 4 paths
git commit -m "feat(ltx-movie): --location pins up to 3 trained locations, checks a reused story's pins, passes them to stills and manifest, and iterate-story keeps them (L3.1, L3.2, L3.8, L3.11; LP1-LP4, LP13, LP20, LS7)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: movie UI server: routes, jobs, Compose fields, `--no-arch-check`, WARN lines (L4.1-L4.3, L4.5 server, L4.6; LU1-LU12, LU14, Review Focus 5)

This task implements:
- L4.1:
  - The six `ROUTES` entries after the character routes.
  - `_handle` reads a body for `("POST", "PUT", "PATCH")`.
  - `job_vlm`: `location-create`/`location-regenerate` are `required`, `location-train` is `forbidden`.
  - `movie_ui_lib.location_argv(kind, fields, ws_real, state, py=sys.executable)` and `create_location_job`, whose jobs carry `character=fields["name"]`.
- L4.2: `parse_location_list` (`LOCATION_ROW_RE`), `_h_locations`, `_h_location` (the detail), `location_create_errors` and `_h_location_create`, `_h_location_patch` (exit 0 → 200; exit 2 → 400 with the tool's message; timeout → 504; else 502), `_h_location_regenerate`, `_h_location_train`.
- L4.3: `DEFAULT_FIELDS` gains `"locations": []` and `"location_strength": None`; `FIELD_FLAGS` gains the two entries after `characters` (30 entries); `build_argv` adds `--location` per name and `--location-strength` when set; V1 rule 12c (`_rule_locations`) after rule 12b.
- L4.5, server side: `_h_lora_add` reads `no_arch_check` (optional bool, 400 otherwise) and appends `--no-arch-check` last. `parse_verify` reads `WARN` lines; an entry gets `"warnings"` only when a `WARN` line names it (Plan ruling LR2).
- L4.6: `tests/movie_ui_testutil.py`: `STUB_TOOLS` gains `"location"`, and the stub prints `no locations in <ws>/generated/locations` for `location list`.

The message texts that the spec leaves open are fixed in Plan ruling LR12. `test_mut18` (46 routes), `test_mut3` and `test_mu14` (30 `FIELD_FLAGS`) fail from this task until Task 14 (codes R18, R3).

**Files:**
- Modify: `movie_ui_lib.py`: `job_vlm` (`:424-425`, `:433-434`), `DEFAULT_FIELDS` (`:901`), after `LIGHT_TIMEOUT` (`:906`), `FIELD_FLAGS` (`:915`), `build_argv` (`:991-992`), before `action_argv` (`:1040`), rule 12b (`:1405`).
- Modify: `movie_ui_server.py`: `ROUTES` (`:78-79`), `_handle` (`:378`), `_h_lora_add` (`:1015-1016`, `:1040-1042`), `VERIFY_LINE_RE` and `parse_verify` (`:1052-1056`, `:1066-1069`), after `MovieUIHandler.h_character_train` (`:1289`).
- Modify: `tests/movie_ui_testutil.py`: `STUB_TOOLS` (`:131`), `STUB_SOURCE`'s `character list` branch (`:223-225`), `make_stub_workspace`'s docstring (`:240-241`, `:250`).
- Create: `tests/test_location_ui.py` (Task 12 appends).

**Interfaces:**
- Consumes (existing): `lib.run_light`, `lib.tool_argv`, `lib.create_job(state, job_id, kind, workspace, story_id, character, argv, fields)`, `lib.new_job_id`, `lib.read_queue`, `lib.last_line`, `lib._argv_safe`, `lib.UPLOAD_ID_RE`, `lib.LIGHT_TIMEOUT`, `lib.ProgressParser`, `lib.parse_utc`; `movie_ui_server.tool_result`, `newest_job`, `job_summary`, `INVALID_ROW_RE`, `FILE_LINE_RE`, `ApiError`, `STORE_LOCK`, `_fs_text`.
- Produces, in `movie_ui_lib`: `LOCATION_NAME_RE`, `_rule_locations(fields) -> [str]`, `location_argv(kind, fields, ws_real, state, py=sys.executable) -> [str]`.
- Produces, in `movie_ui_server`: `LOCATION_ROW_RE`, `LOCATION_MIN_WORDS`, `LOCATION_MAX_WORDS`, `LOCATION_MAX_PHOTOS`, `parse_location_list(stdout)`, `location_description_errors(description) -> [str]`, `_seed_errors(seed)`, `location_create_errors(body, state) -> [str]`, `create_location_job(server, kind, real, fields)`, and `MovieUIHandler.h_locations`, `h_location`, `h_location_create`, `h_location_patch`, `h_location_regenerate`, `h_location_train`.
- Produces, in the tests: the `env` fixture, `DESC`, `NEW_ROUTES`, `_job_argv(state, payload)`, `_upload(s, data)`.

- [ ] **Step 1: Write the failing tests.**

**1.1.** Edit `tests/movie_ui_testutil.py`: replace this text, which occurs exactly once:

```python
STUB_TOOLS = ("ltx-movie", "lora-catalog", "character", "ltx-mlx-render", "story-server")
```

with:

```python
STUB_TOOLS = ("ltx-movie", "lora-catalog", "character", "ltx-mlx-render", "story-server",
              "location")
```

**1.2.** Edit `tests/movie_ui_testutil.py`: replace this text, which occurs exactly once:

```python
if TOOL == "character" and sub == "list":
    emit("no characters in %s\n" % os.path.join(WS, "generated", "characters"))
    sys.exit(0)
```

with:

```python
if TOOL == "character" and sub == "list":
    emit("no characters in %s\n" % os.path.join(WS, "generated", "characters"))
    sys.exit(0)
if TOOL == "location" and sub == "list":
    emit("no locations in %s\n" % os.path.join(WS, "generated", "locations"))
    sys.exit(0)
```

**1.3.** Edit `tests/movie_ui_testutil.py`: replace this text, which occurs exactly once:

```python
    """<tmp>/ws with executable stubs of ltx-movie, lora-catalog, character, ltx-mlx-render (Python)
    and story-server (sh, running bin/.story-server.py); returns the workspace realpath.
```

with:

```python
    """<tmp>/ws with executable stubs of ltx-movie, lora-catalog, character, ltx-mlx-render,
    location (Python) and story-server (sh, running bin/.story-server.py); returns the workspace
    realpath.
```

**1.4.** Edit `tests/movie_ui_testutil.py`: replace this text, which occurs exactly once:

```python
    prints an empty catalog; story-server status reports SERVING vision; everything else exits 0.
```

with:

```python
    prints an empty catalog; location list prints an empty location library; story-server status
    reports SERVING vision; everything else exits 0.
```

**1.5.** Create `tests/test_location_ui.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""Tests for the location library in movie-ui (docs/superpowers/specs/
2026-10-29-location-lora-design.md, Section 5, test table 6.8: LU1-LU14, with the plan's Review
Focus pin): the /api/locations routes and jobs, Compose's --location fields and V1 rule 12c, the
LoRAs & Models tab's --no-arch-check and WARN lines, and the static page.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_location_ui.py
Stdlib plus pytest. No test reads the real HOME, renders, trains, contacts a model server or
touches port 8178: every server is an in-test movie-ui server on 127.0.0.1 under a temporary HOME
(movie_ui_testutil), every tool it runs is a stub in a temporary workspace, and no job is ever
dispatched.
"""

import json
import os
import re
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import movie_ui_lib as lib  # noqa: E402
import movie_ui_server as srv  # noqa: E402
import movie_ui_testutil as mt  # noqa: E402

DESC = ("a narrow cobbled harbour street lined with weathered stone warehouses, green wooden "
        "shutters, rusted mooring rings and faded red fishmonger signs above granite quays")
NEW_ROUTES = [("GET", "/api/locations"), ("POST", "/api/locations"),
              ("GET", "/api/locations/harbour-street"), ("PATCH", "/api/locations/harbour-street"),
              ("POST", "/api/locations/harbour-street/train"),
              ("POST", "/api/locations/harbour-street/regenerate")]


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCATION_LIBRARY_DIR", str(tmp_path / "locations"))
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", str(tmp_path / "characters"))
    monkeypatch.setenv("LORA_CATALOG_DIR", str(tmp_path / "loras"))
    state = mt.set_home(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    running = mt.Running(state)
    yield {"state": state, "ws": ws, "tmp": str(tmp_path), "srv": running}
    running.close()
    mt.kill_everything(state)


def _job_argv(state, payload):
    return lib.read_job(lib.job_dir(state, payload["job"]["id"]))["argv"]


def _upload(s, data):
    status, _h, payload = mt.api(s, "POST", "/api/uploads", raw=data,
                                 headers={"Content-Type": "image/png"})
    assert status == 201
    return payload["upload_id"]


# --- LU1, LU2: the routes, the token and PATCH bodies (L4.1) -----------------------------------

def test_lu1_the_location_routes_need_the_token(env):
    s = env["srv"]
    assert len(srv.ROUTES) == 46
    assert [(m, sample) for m, _r, _n, sample in srv.ROUTES if "/locations" in sample] == NEW_ROUTES
    for method, regex, name, sample in srv.ROUTES:
        if (method, sample) not in NEW_ROUTES:
            continue
        assert re.fullmatch(regex, sample) and hasattr(srv.MovieUIHandler, name), name
        body = {} if method in ("POST", "PUT", "PATCH") else None
        for token in (None, "wrong-token"):
            status, _h, payload = mt.api(s, method, sample, body=body, token=token)
            assert (status, payload) == (401, {"error": "missing or invalid token"}), (method, sample)
    assert mt.api(s, "DELETE", "/api/locations/harbour-street")[0] == 405


def test_lu2_patch_bodies_are_read(env):
    s, ws = env["srv"], env["ws"]
    status, _h, payload = mt.api(s, "PATCH", "/api/locations/harbour-street")
    assert (status, payload) == (411, {"error": "Content-Length required"})
    status, _h, payload = mt.api(s, "PATCH", "/api/locations/harbour-street", raw=b"{bad",
                                 headers={"Content-Type": "application/json"})
    assert (status, payload) == (400, {"error": "invalid JSON body"})
    status, _h, payload = mt.api(s, "PATCH", "/api/locations/harbour-street",
                                 body={"ws": ws, "description": DESC})
    assert status == 200 and payload["run"]["exit_code"] == 0


# --- LU3, LU4: the list and the detail (L4.2) --------------------------------------------------

def test_lu3_the_location_list(env):
    s, ws = env["srv"], env["ws"]
    assert mt.api(s, "GET", "/api/locations?ws=" + ws)[2] == {"locations": []}
    mt.stub_config(ws, {"location list": {"stdout": (
        "NAME             TRIGGER          STATUS    SOURCE VIDEO STILLS DESCRIPTION\n"
        "bad-one          (invalid: invalid location.json for bad-one: top level: x)\n"
        "harbour-street   harboplc         trained   text   yes   no     " + DESC + "\n"
        "old-mill         oldmiplc         untrained photos no    no     an old mill by a weir\n")}})
    assert mt.api(s, "GET", "/api/locations?ws=" + ws)[2] == {"locations": [
        {"name": "bad-one", "invalid": "invalid location.json for bad-one: top level: x"},
        {"name": "harbour-street", "trigger": "harboplc", "status": "trained", "source": "text",
         "video": True, "stills": False, "description": DESC, "invalid": None},
        {"name": "old-mill", "trigger": "oldmiplc", "status": "untrained", "source": "photos",
         "video": False, "stills": False, "description": "an old mill by a weir", "invalid": None}]}
    mt.stub_config(ws, {"location list": {"exit": 1, "stderr": "Traceback\n"}})
    assert mt.api(s, "GET", "/api/locations?ws=" + ws)[0] == 502


def test_lu4_the_location_detail(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    ldir = os.path.join(env["tmp"], "locations", "harbour-street")
    for sub in ("stills", "tests"):
        os.makedirs(os.path.join(ldir, sub))
    items = [{"n": n, "source": "generated", "kept": n != 2} for n in (1, 2, 3)]
    with open(os.path.join(ldir, "manifest.json"), "w") as f:
        json.dump({"items": items}, f)
    for rel in ("stills/loc_01.png", "stills/loc_03.png", "contact_sheet.jpg",
                "tests/video_lora.mp4"):
        open(os.path.join(ldir, rel), "wb").close()
    record = {"name": "harbour-street", "status": "trained", "source": "text"}
    files = "files:\n  ok       %s\n  MISSING  %s\n" % (os.path.join(ldir, "location.json"),
                                                       os.path.join(ldir, "lora", "x.safetensors"))
    mt.stub_config(ws, {"location show harbour-street": {
        "stdout": json.dumps(record, indent=2) + "\n" + files}})
    detail = mt.api(s, "GET", "/api/locations/harbour-street?ws=" + ws)[2]
    assert detail == {
        "location": record,
        "files": [{"status": "ok", "path": os.path.join(ldir, "location.json")},
                  {"status": "MISSING", "path": os.path.join(ldir, "lora", "x.safetensors")}],
        "manifest": items,
        "contact_sheet": os.path.join(ldir, "contact_sheet.jpg"),
        "stills": [os.path.join(ldir, "stills", "loc_01.png"),
                   os.path.join(ldir, "stills", "loc_03.png")],
        "tests": {"video_lora": os.path.join(ldir, "tests", "video_lora.mp4"),
                  "video_control": None},
        "last_create_fields": None}
    status, _h, payload = mt.api(s, "POST", "/api/locations",
                                 body={"ws": ws, "name": "harbour-street", "description": DESC})
    assert status == 201
    detail = mt.api(s, "GET", "/api/locations/harbour-street?ws=" + ws)[2]
    assert detail["last_create_fields"]["description"] == DESC
    os.remove(os.path.join(ldir, "manifest.json"))
    detail = mt.api(s, "GET", "/api/locations/harbour-street?ws=" + ws)[2]
    assert (detail["manifest"], detail["stills"]) == (None, [])
    mt.stub_config(ws, {"location show harbour-street": {"exit": 2,
                                                         "stderr": "Error: unknown location\n"}})
    assert mt.api(s, "GET", "/api/locations/harbour-street?ws=" + ws)[0] == 502


# --- LU5-LU9: create, edit, regenerate and train jobs (L4.1, L4.2) -----------------------------

def test_lu5_create_argv_and_errors(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    status, _h, payload = mt.api(s, "POST", "/api/locations",
                                 body={"ws": ws, "name": "harbour-street", "description": DESC,
                                       "trigger": "harbtrg", "seed": 7, "force": True})
    assert status == 201 and payload["job"]["kind"] == "location-create"
    assert payload["job"]["character"] == "harbour-street"
    argv = _job_argv(state, payload)
    assert os.path.basename(argv[1]) == "location"
    assert argv[2:] == ["create", "harbour-street", "--description", DESC, "--trigger", "harbtrg",
                        "--seed", "7", "--force"]
    one, two = _upload(s, mt.PNG), _upload(s, mt.PNG + b"x")
    status, _h, payload = mt.api(s, "POST", "/api/locations",
                                 body={"ws": ws, "name": "old-mill", "photo_uploads": [one, two],
                                       "description": "", "trigger": "", "seed": None})
    assert status == 201
    assert _job_argv(state, payload)[2:] == [
        "create", "old-mill", "--photo", os.path.join(state, "uploads", one),
        "--photo", os.path.join(state, "uploads", two)]
    missing = "0" * 64 + ".png"
    status, _h, payload = mt.api(s, "POST", "/api/locations", body={
        "ws": ws, "name": "Bad", "photo_uploads": [missing], "description": "a short one",
        "trigger": "Bad", "seed": -1, "force": "yes"})
    assert (status, payload["error"]) == (400, "invalid fields")
    assert payload["errors"] == ["location name must match [a-z][a-z0-9-]{1,23}",
                                 "photo upload %s not found" % missing,
                                 "description must be 15 to 40 words",
                                 "trigger must match [a-z][a-z0-9]{3,15}",
                                 "seed must be an integer from 0 to 2147483647",
                                 "force must be true or false"]
    for body, errors in (({"photo_uploads": [one] * 25}, ["give at most 24 photos"]),
                         ({"photo_uploads": "x"}, ["photo_uploads must be a list of upload IDs",
                                                   "give a description or at least one photo"]),
                         ({}, ["give a description or at least one photo"]),
                         ({"description": "-" + DESC}, ["description must not start with '-'"]),
                         ({"description": DESC.replace(" shutters,", "\nshutters,")},
                          ["description must be one line"]),
                         ({"description": DESC + "\x00"}, ["description contains invalid characters"]),
                         ({"description": 5}, ["description must be a string"])):
        status, _h, payload = mt.api(s, "POST", "/api/locations",
                                     body=dict({"ws": ws, "name": "old-mill"}, **body))
        assert (status, payload["errors"]) == (400, errors), body


def test_lu6_patch_saves_a_photo_description(env):
    s, ws = env["srv"], env["ws"]
    status, _h, payload = mt.api(s, "PATCH", "/api/locations/old-mill",
                                 body={"ws": ws, "description": DESC})
    assert status == 200 and mt.stub_calls(ws)[-1]["argv"] == ["edit", "old-mill",
                                                                "--description", DESC]
    text = ("Error: location harbour-street is a text location: its stills are drawn from its "
            "description; run bin/location create harbour-street --regenerate --description TEXT "
            "(add --force when it is trained)\n")
    mt.stub_config(ws, {"location edit": {"exit": 2, "stderr": text}})
    status, _h, payload = mt.api(s, "PATCH", "/api/locations/harbour-street",
                                 body={"ws": ws, "description": DESC})
    assert (status, payload["error"]) == (400, text[len("Error: "):].strip())
    assert payload["run"]["exit_code"] == 2
    mt.stub_config(ws, {"location edit": {"exit": 1, "stderr": "Traceback\n"}})
    status, _h, payload = mt.api(s, "PATCH", "/api/locations/harbour-street",
                                 body={"ws": ws, "description": DESC})
    assert (status, payload["error"]) == (502, "location exited 1")
    status, _h, payload = mt.api(s, "PATCH", "/api/locations/harbour-street",
                                 body={"ws": ws, "description": "a quay"})
    assert (status, payload) == (400, {"error": "invalid fields",
                                       "errors": ["description must be 15 to 40 words"]})


def test_lu7_regenerate_argv(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    for body, tail in (({"new_seed": True}, ["--new-seed"]), ({"seed": 9}, ["--seed", "9"]),
                       ({"description": DESC, "force": True}, ["--description", DESC, "--force"]),
                       ({}, [])):
        status, _h, payload = mt.api(s, "POST", "/api/locations/harbour-street/regenerate",
                                     body=dict({"ws": ws}, **body))
        assert status == 201 and payload["job"]["kind"] == "location-regenerate", body
        assert _job_argv(state, payload)[2:] == ["create", "harbour-street", "--regenerate"] + tail
    for body, errors in (({"seed": 3, "new_seed": True}, ["give seed or new_seed, not both"]),
                         ({"seed": True}, ["seed must be an integer from 0 to 2147483647"]),
                         ({"new_seed": "yes"}, ["new_seed must be true or false"]),
                         ({"force": 1}, ["force must be true or false"]),
                         ({"description": "a quay"}, ["description must be 15 to 40 words"])):
        status, _h, payload = mt.api(s, "POST", "/api/locations/harbour-street/regenerate",
                                     body=dict({"ws": ws}, **body))
        assert (status, payload) == (400, {"error": "invalid fields", "errors": errors}), body


def test_lu8_train_argv(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    status, _h, payload = mt.api(s, "POST", "/api/locations/harbour-street/train", body={"ws": ws})
    assert (status, payload) == (400, {"error": "invalid fields",
                                       "errors": ["choose video, stills or both"]})
    status, _h, payload = mt.api(s, "POST", "/api/locations/harbour-street/train",
                                 body={"ws": ws, "video": True, "stills": True, "force": True})
    argv = _job_argv(state, payload)
    assert status == 201 and payload["job"]["kind"] == "location-train"
    assert argv[0] == os.path.join(ws, "bin", "location-train-vlm")
    assert argv[2:] == ["harbour-street", "--video", "--stills", "--force"]
    status, _h, payload = mt.api(s, "POST", "/api/locations/harbour-street/train",
                                 body={"ws": ws, "video": "yes"})
    assert (status, payload["errors"]) == (400, ["video must be true or false"])


def test_lu9_job_vlm_policy(tmp_path):
    for kind, policy in (("location-create", "required"), ("location-regenerate", "required"),
                         ("location-train", "forbidden")):
        assert lib.job_vlm(kind, {}, str(tmp_path), None) == policy, kind


# --- LU10, Review Focus 5: Compose (L4.3) ------------------------------------------------------

def test_lu10_compose_fields_flags_and_rule_12c(env):
    state = env["state"]
    assert len(lib.FIELD_FLAGS) == 30
    keys = [k for k, _flags in lib.FIELD_FLAGS]
    assert keys[keys.index("characters") + 1:keys.index("characters") + 3] == [
        "locations", "location_strength"]
    assert dict(lib.FIELD_FLAGS)["locations"] == ("--location",)
    assert dict(lib.FIELD_FLAGS)["location_strength"] == ("--location-strength",)
    assert (lib.DEFAULT_FIELDS["locations"], lib.DEFAULT_FIELDS["location_strength"]) == ([], None)
    fields = mt.fields(mt.WS, characters=["kyra"], locations=["harbour-street", "temple-gate"],
                       location_strength=0.6)
    argv = lib.build_argv(fields, mt.WS, state)
    at = argv.index("--character")
    assert argv[at:at + 7] == ["--character", "kyra", "--location", "harbour-street",
                               "--location", "temple-gate", "--location-strength"]
    assert argv[at + 7] == "0.6"
    assert lib.validate_fields(fields, mt.WS, state) == []
    no_strength = lib.build_argv(mt.fields(mt.WS, locations=["harbour-street"]), mt.WS, state)
    assert "--location-strength" not in no_strength and "--location" in no_strength
    for overrides, errors in (
            (dict(locations=["a1", "b1", "c1", "d1"]), ["locations must be at most 3 distinct location names"]),
            (dict(locations=["a1", "a1"]), ["locations must be at most 3 distinct location names"]),
            (dict(locations=["Bad"]), ["locations must be at most 3 distinct location names"]),
            (dict(locations="harbour-street"), ["locations must be at most 3 distinct location names",
                                                ]),
            (dict(locations=["a1"], location_strength=1.5), ["location strength must be a number in (0, 1]"]),
            (dict(locations=["a1"], location_strength=True), ["location strength must be a number in (0, 1]"]),
            (dict(location_strength=0.5), ["location strength needs at least one location"]),
            (dict(locations=["a1"], mode="no_stills"), ["locations need chained or shots mode"])):
        found = lib.validate_fields(mt.fields(mt.WS, **overrides), mt.WS, state)
        assert [e for e in found if "location" in e] == errors, overrides


def test_review_focus_5_fields_saved_before_the_upgrade(env):
    state = env["state"]
    old = dict(mt.fields(mt.WS, characters=["kyra"]))
    del old["locations"], old["location_strength"]
    composed = lib.compose_fields(old)
    assert (composed["locations"], composed["location_strength"]) == ([], None)
    assert lib.validate_fields(composed, mt.WS, state) == []
    assert "--location" not in lib.build_argv(composed, mt.WS, state)
    assert "--location-strength" not in lib.build_argv(composed, mt.WS, state)


# --- LU11, LU12: the LoRAs & Models tab (L4.5) -------------------------------------------------

def test_lu11_lora_add_no_arch_check(env):
    s, ws = env["srv"], env["ws"]
    add = {"ws": ws, "path": "/l/pan.safetensors", "id": "pan", "kind": "motion", "target": "video",
           "base_models": ["M1"], "triggers": [], "description": "a pan", "use_when": "pans",
           "avoid_when": "", "default_strength": 0.8, "strength_range": [0.5, 1], "rank": None,
           "alpha": 8}
    for value, tail in ((True, ["--alpha", "8", "--no-arch-check"]), (False, ["--alpha", "8"]),
                        (None, ["--alpha", "8"])):
        body = dict(add) if value is None else dict(add, no_arch_check=value)
        assert mt.api(s, "POST", "/api/loras", body=body)[0] == 200
        assert mt.stub_calls(ws)[-1]["argv"][-len(tail):] == tail, value
    assert mt.api(s, "POST", "/api/loras", body=dict(add, no_arch_check="yes"))[:3:2] == (
        400, {"error": "no_arch_check must be true or false"})


def test_lu12_parse_verify_collects_warnings():
    assert srv.parse_verify(
        "OK ink\nFAIL pan: sha256 changed\nWARN pan: 44 of 1724 modules are outside the "
        "transformer blocks and are skipped in low-RAM mode; render with --no-low-ram to use "
        "them\nOK comfy\nWARN comfy: 2 of 9 modules are outside\nverified 3 entries: 1 problem(s)\n") == [
        {"id": "ink", "ok": True, "problems": []},
        {"id": "pan", "ok": False, "problems": ["sha256 changed"],
         "warnings": ["44 of 1724 modules are outside the transformer blocks and are skipped in "
                      "low-RAM mode; render with --no-low-ram to use them"]},
        {"id": "comfy", "ok": True, "problems": [], "warnings": ["2 of 9 modules are outside"]}]


# --- LU14: a location job's progress (L4.1) ----------------------------------------------------

def test_lu14_a_location_job_reports_elapsed_and_last_line(env):
    parser = lib.ProgressParser("location-create", {"name": "harbour-street"})
    parser.feed(b"=== generate: 24 stills ===\n=== check ===\n")
    started = "2026-10-29T10:00:00Z"
    snap = parser.snapshot({"id": "x", "kind": "location-create", "workspace": env["ws"],
                            "story_id": None}, {"started": started}, env["state"],
                           now=lib.parse_utc(started) + 5)
    assert (snap["kind"], snap["elapsed_s"], snap["last_line"]) == ("location-create", 5,
                                                                   "=== check ===")
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_ui.py 2>&1 | tail -1
```

Expected: `13 failed, 1 passed` (LU14 already holds: a non-story job's snapshot is generic).

- [ ] **Step 3: Implement.**

**3.1.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    if kind in ("story", "character-create", "character-regenerate"):
        return "required"
```

with:

```python
    if kind in ("story", "character-create", "character-regenerate", "location-create",
                "location-regenerate"):
        return "required"
```

**3.2.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    if kind in ("smoke", "character-train", "action-train"):
        return "forbidden"
```

with:

```python
    if kind in ("smoke", "character-train", "action-train", "location-train"):
        return "forbidden"
```

**3.3.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    "characters": [], "action_loras": [],
```

with:

```python
    "characters": [], "locations": [], "location_strength": None, "action_loras": [],
```

**3.4.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
LIGHT_TIMEOUT = 60
```

with:

```python
LIGHT_TIMEOUT = 60
LOCATION_NAME_RE = re.compile(r"[a-z][a-z0-9-]{1,23}")   # location_lib.NAME_RE
```

**3.5.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    ("characters", ("--character",)), ("action_loras", ("--action",)),
```

with:

```python
    ("characters", ("--character",)), ("locations", ("--location",)),
    ("location_strength", ("--location-strength",)), ("action_loras", ("--action",)),
```

**3.6.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    for name in fields["characters"]:
        argv += ["--character", name]
```

with:

```python
    for name in fields["characters"]:
        argv += ["--character", name]
    # Location library spec L4.3: the pinned locations, then their strength.
    for name in fields["locations"]:
        argv += ["--location", name]
    if fields["locations"] and fields["location_strength"] is not None:
        argv += ["--location-strength", repr(float(fields["location_strength"]))]
```

**3.7.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
def action_argv(kind, fields, ws_real, py=sys.executable):
```

with:

```python
def _rule_locations(fields):
    """V1 rule 12c (location library spec L4.3): at most 3 distinct location names, a strength
    in (0, 1] only with a location, and no locations in no_stills mode."""
    errors = []
    names = fields.get("locations")
    if not (isinstance(names, list) and len(names) <= 3 and len(set(map(repr, names))) == len(names)
            and all(isinstance(n, str) and LOCATION_NAME_RE.fullmatch(n) for n in names)):
        errors.append("locations must be at most 3 distinct location names")
    pinned = isinstance(names, list) and len(names) > 0
    strength = fields.get("location_strength")
    if strength is not None and not (isinstance(strength, (int, float))
                                     and not isinstance(strength, bool) and 0 < strength <= 1):
        errors.append("location strength must be a number in (0, 1]")
    if strength is not None and not pinned:
        errors.append("location strength needs at least one location")
    if pinned and fields.get("mode") == "no_stills":
        errors.append("locations need chained or shots mode")
    return errors


def location_argv(kind, fields, ws_real, state, py=sys.executable):
    """The bin/location argv of a location-create, -regenerate or -train job (location library
    spec L4.1)."""
    if kind == "location-train":
        # Like character-train-vlm: stop the VLM for training's memory, always restart it.
        return ([os.path.join(ws_real, "bin", "location-train-vlm"), py, fields["name"]]
                + (["--video"] if fields.get("video") else [])
                + (["--stills"] if fields.get("stills") else [])
                + (["--force"] if fields.get("force") else []))
    argv = [py, os.path.join(ws_real, "bin", "location"), "create", fields["name"]]
    if kind == "location-regenerate":
        argv.append("--regenerate")
        if fields.get("seed") is not None:
            argv += ["--seed", str(fields["seed"])]
        elif fields.get("new_seed"):
            argv.append("--new-seed")
        if fields.get("description"):
            argv += ["--description", fields["description"]]
        return argv + (["--force"] if fields.get("force") else [])
    if fields.get("description"):
        argv += ["--description", fields["description"]]
    for upload in fields.get("photo_uploads") or []:
        argv += ["--photo", os.path.join(state, "uploads", upload)]
    if fields.get("trigger"):
        argv += ["--trigger", fields["trigger"]]
    if fields.get("seed") is not None:
        argv += ["--seed", str(fields["seed"])]
    return argv + (["--force"] if fields.get("force") else [])


def action_argv(kind, fields, ws_real, py=sys.executable):
```

**3.8.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    errors += _rule_actions(fields)                                          # 12b
```

with:

```python
    errors += _rule_actions(fields)                                          # 12b
    errors += _rule_locations(fields)                                        # 12c
```

**3.9.** Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    ("POST", r"/api/characters/" + _NAME + r"/regenerate", "h_character_regenerate",
     "/api/characters/kyra/regenerate"),
```

with:

```python
    ("POST", r"/api/characters/" + _NAME + r"/regenerate", "h_character_regenerate",
     "/api/characters/kyra/regenerate"),
    ("GET", r"/api/locations", "h_locations", "/api/locations"),
    ("POST", r"/api/locations", "h_location_create", "/api/locations"),
    ("GET", r"/api/locations/" + _NAME, "h_location", "/api/locations/harbour-street"),
    ("PATCH", r"/api/locations/" + _NAME, "h_location_patch", "/api/locations/harbour-street"),
    ("POST", r"/api/locations/" + _NAME + r"/train", "h_location_train",
     "/api/locations/harbour-street/train"),
    ("POST", r"/api/locations/" + _NAME + r"/regenerate", "h_location_regenerate",
     "/api/locations/harbour-street/regenerate"),
```

**3.10.** Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
        if self.command in ("POST", "PUT") or (self.command == "DELETE" and
```

with:

```python
        if self.command in ("POST", "PUT", "PATCH") or (self.command == "DELETE" and
```

**3.11.** Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    alpha = _typed(body, "alpha", "int", "an integer or null", optional=True)
    if not path.startswith("/"):
```

with:

```python
    alpha = _typed(body, "alpha", "int", "an integer or null", optional=True)
    no_arch_check = body.get("no_arch_check", False)
    if not isinstance(no_arch_check, bool):
        raise ApiError(400, "no_arch_check must be true or false")
    if not path.startswith("/"):
```

**3.12.** Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    if alpha is not None:
        args += ["--alpha", str(alpha)]
    return 200, {"run": _lora_action(real, args, timeout=lib.VERIFY_TIMEOUT)}
```

with:

```python
    if alpha is not None:
        args += ["--alpha", str(alpha)]
    if no_arch_check:
        args.append("--no-arch-check")
    return 200, {"run": _lora_action(real, args, timeout=lib.VERIFY_TIMEOUT)}
```

**3.13.** Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
VERIFY_LINE_RE = re.compile(r"^(OK|FAIL) (\S+?)(?:: (.*))?$")


def parse_verify(stdout):
    """[{"id", "ok", "problems"}] from lora-catalog verify's OK/FAIL lines, in first-seen order."""
```

with:

```python
VERIFY_LINE_RE = re.compile(r"^(OK|FAIL|WARN) (\S+?)(?:: (.*))?$")


def parse_verify(stdout):
    """[{"id", "ok", "problems"}] from lora-catalog verify's OK/FAIL lines, in first-seen order;
    an entry named by a WARN line also gets "warnings", which never changes "ok" (location
    library spec L4.5)."""
```

**3.14.** Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
        if m.group(1) == "FAIL":
            entry["ok"] = False
            entry["problems"].append(m.group(3) or "")
    return results
```

with:

```python
        if m.group(1) == "FAIL":
            entry["ok"] = False
            entry["problems"].append(m.group(3) or "")
        elif m.group(1) == "WARN":
            entry.setdefault("warnings", []).append(m.group(3) or "")
    return results
```

**3.15.** Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
MovieUIHandler.h_character_train = _h_character_train
```

with:

```python
MovieUIHandler.h_character_train = _h_character_train


# ---------------------------------------------------------------------------
# Locations: the location library (bin/location; location library spec L4.1, L4.2)
# ---------------------------------------------------------------------------

LOCATION_ROW_RE = re.compile(r"^(\S+)\s+(\S+)\s+(dataset|untrained|trained)\s+(text|photos)\s+"
                             r"(yes|no)\s+(yes|no)\s+(.+)$")
LOCATION_MIN_WORDS, LOCATION_MAX_WORDS, LOCATION_MAX_PHOTOS = 15, 40, 24


def parse_location_list(stdout):
    """The rows of bin/location list (spec L4.2)."""
    out = []
    for line in stdout.splitlines():
        if line.startswith("NAME ") or line.startswith("no locations in ") or not line.strip():
            continue
        m = INVALID_ROW_RE.match(line)
        if m:
            out.append({"name": m.group(1), "invalid": m.group(2)})
            continue
        m = LOCATION_ROW_RE.match(line)
        if m:
            out.append({"name": m.group(1), "trigger": m.group(2), "status": m.group(3),
                        "source": m.group(4), "video": m.group(5) == "yes",
                        "stills": m.group(6) == "yes", "description": m.group(7),
                        "invalid": None})
    return out


def location_description_errors(description):
    """The errors of one description string (spec L4.2); [] when it may be passed on."""
    if not isinstance(description, str):
        return ["description must be a string"]
    if not lib._argv_safe(description):
        return ["description contains invalid characters"]
    if description.strip().startswith("-"):
        return ["description must not start with '-'"]
    if "\n" in description or "\r" in description:
        return ["description must be one line"]
    if not LOCATION_MIN_WORDS <= len(description.split()) <= LOCATION_MAX_WORDS:
        return ["description must be 15 to 40 words"]
    return []


def _seed_errors(seed):
    if seed is not None and not (isinstance(seed, int) and not isinstance(seed, bool)
                                 and 0 <= seed <= 2147483647):
        return ["seed must be an integer from 0 to 2147483647"]
    return []


def location_create_errors(body, state):
    """The field rules of POST /api/locations, in order (spec L4.2); [] when they pass."""
    errors = []
    name, photos, description = body.get("name"), body.get("photo_uploads"), body.get("description")
    if not (isinstance(name, str) and lib.LOCATION_NAME_RE.fullmatch(name)):
        errors.append("location name must match [a-z][a-z0-9-]{1,23}")
    if photos is None:
        photos = []
    if not (isinstance(photos, list) and all(isinstance(p, str) for p in photos)):
        errors.append("photo_uploads must be a list of upload IDs")
        photos = []
    elif len(photos) > LOCATION_MAX_PHOTOS:
        errors.append("give at most 24 photos")
    else:
        for upload in photos:
            if not (lib.UPLOAD_ID_RE.fullmatch(upload)
                    and os.path.isfile(os.path.join(state, "uploads", upload))):
                errors.append("photo upload %s not found" % _fs_text(upload))
    if description not in (None, ""):
        errors += location_description_errors(description)
    if not photos and description in (None, ""):
        errors.append("give a description or at least one photo")
    trigger = body.get("trigger")
    if trigger not in (None, "") and not (isinstance(trigger, str)
                                          and re.fullmatch(r"[a-z][a-z0-9]{3,15}", trigger)):
        errors.append("trigger must match [a-z][a-z0-9]{3,15}")
    errors += _seed_errors(body.get("seed"))
    if not isinstance(body.get("force", False), bool):
        errors.append("force must be true or false")
    return errors


def create_location_job(server, kind, real, fields):
    with STORE_LOCK:
        job_id = lib.new_job_id(server.state)
        argv = lib.location_argv(kind, fields, real, server.state)
        lib.create_job(server.state, job_id, kind, real, None, fields["name"], argv, fields)
    return 201, {"job": job_summary(server, job_id, lib.read_queue(server.state))}


def _h_locations(self, groups, query, body):
    real = self.ws(query.get("ws"))
    run = tool_result("location", lib.run_light(lib.tool_argv(real, "location", "list"), real))
    return 200, {"locations": parse_location_list(run["stdout"])}


def _h_location(self, groups, query, body):
    real, name = self.ws(query.get("ws")), groups[0]
    run = tool_result("location", lib.run_light(lib.tool_argv(real, "location", "show", name), real))
    try:
        data, end = json.JSONDecoder().raw_decode(run["stdout"].lstrip())
    except ValueError:
        raise ApiError(502, "location printed unparsable output", run=run)
    rest = run["stdout"].lstrip()[end:]
    files = [{"status": m.group(1), "path": m.group(2)}
             for m in (FILE_LINE_RE.match(line) for line in rest.splitlines()) if m]
    loc_dir = next((os.path.dirname(f["path"]) for f in files
                    if f["path"].endswith("/location.json")), None)
    manifest, stills, sheet = None, [], None
    tests = {"video_lora": None, "video_control": None}
    if loc_dir is not None:
        try:
            with open(os.path.join(loc_dir, "manifest.json"), encoding="utf-8") as f:
                items = json.load(f).get("items")
            manifest = items if isinstance(items, list) else None
        except (OSError, ValueError, AttributeError):
            manifest = None
        for item in manifest or []:
            n = item.get("n") if isinstance(item, dict) else None
            if isinstance(n, int) and not isinstance(n, bool):
                path = os.path.join(loc_dir, "stills", "loc_%02d.png" % n)
                if os.path.isfile(path):
                    stills.append(path)
        path = os.path.join(loc_dir, "contact_sheet.jpg")
        sheet = path if os.path.isfile(path) else None
        for key, filename in (("video_lora", "video_lora.mp4"), ("video_control", "video_control.mp4")):
            path = os.path.join(loc_dir, "tests", filename)
            tests[key] = path if os.path.isfile(path) else None
    job = newest_job(self.server, ("location-create",), real, "character", name)
    return 200, {"location": data, "files": files, "manifest": manifest, "contact_sheet": sheet,
                 "stills": stills, "tests": tests,
                 "last_create_fields": job["fields"] if job is not None else None}


def _h_location_create(self, groups, query, body):
    real = self.ws(body.get("ws"))
    errors = location_create_errors(body, self.server.state)
    if errors:
        raise ApiError(400, "invalid fields", errors=errors)
    fields = {"ws": real, "name": body["name"], "photo_uploads": list(body.get("photo_uploads") or []),
              "description": body.get("description") or None, "trigger": body.get("trigger") or None,
              "seed": body.get("seed"), "force": body.get("force", False)}
    return create_location_job(self.server, "location-create", real, fields)


def _h_location_patch(self, groups, query, body):
    real = self.ws(body.get("ws"))
    errors = location_description_errors(body.get("description"))
    if errors:
        raise ApiError(400, "invalid fields", errors=errors)
    run = lib.run_light(lib.tool_argv(real, "location", "edit", groups[0], "--description",
                                      body["description"]), real)
    if run["timed_out"]:
        raise ApiError(504, "location timed out after %d s" % lib.LIGHT_TIMEOUT, run=run)
    if run["exit_code"] == 0:
        return 200, {"run": run}
    if run["exit_code"] == 2:
        message = lib.last_line(run["stderr"])
        raise ApiError(400, message[len("Error: "):] if message.startswith("Error: ") else message,
                       run=run)
    raise ApiError(502, "location exited %s" % run["exit_code"], run=run)


def _h_location_regenerate(self, groups, query, body):
    real = self.ws(body.get("ws"))
    seed, new_seed = body.get("seed"), body.get("new_seed", False)
    description, force = body.get("description"), body.get("force", False)
    errors = []
    if seed is not None and new_seed is True:
        errors.append("give seed or new_seed, not both")
    errors += _seed_errors(seed)
    if description not in (None, ""):
        errors += location_description_errors(description)
    for key, value in (("new_seed", new_seed), ("force", force)):
        if not isinstance(value, bool):
            errors.append("%s must be true or false" % key)
    if errors:
        raise ApiError(400, "invalid fields", errors=errors)
    return create_location_job(self.server, "location-regenerate", real,
                               {"ws": real, "name": groups[0], "seed": seed, "new_seed": new_seed,
                                "description": description or None, "force": force})


def _h_location_train(self, groups, query, body):
    real = self.ws(body.get("ws"))
    fields = {"ws": real, "name": groups[0]}
    errors = []
    for key in ("video", "stills", "force"):
        value = body.get(key, False)
        if not isinstance(value, bool):
            errors.append("%s must be true or false" % key)
        fields[key] = value
    if not errors and not (fields["video"] or fields["stills"]):
        errors.append("choose video, stills or both")
    if errors:
        raise ApiError(400, "invalid fields", errors=errors)
    return create_location_job(self.server, "location-train", real, fields)


MovieUIHandler.h_locations = _h_locations
MovieUIHandler.h_location = _h_location
MovieUIHandler.h_location_create = _h_location_create
MovieUIHandler.h_location_patch = _h_location_patch
MovieUIHandler.h_location_regenerate = _h_location_regenerate
MovieUIHandler.h_location_train = _h_location_train
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_ui.py 2>&1 | tail -1
```

Expected: `14 passed`. Run the compile check with `FILES` = `movie_ui_lib.py movie_ui_server.py tests/movie_ui_testutil.py tests/test_location_ui.py`; expected: `compiled 4` twice. Then run the gate block with `N=11`. Expected: `GATE PASS`, `new-file tests 108, not passing 0`, `baseline failures still failing 2 of 2`, `OK 347/347`, and five listed LOST lines: `test_mut26`, `test_spt1a_engine_constants`, `test_mut18_every_api_route_needs_the_token`, `test_mut3_help_flags_fixtures_real_help_and_cache` and `test_mu14_ws_parameter_errors_and_options`.

- [ ] **Step 5: Commit.**

```bash
git add movie_ui_lib.py movie_ui_server.py tests/movie_ui_testutil.py tests/test_location_ui.py
git diff --cached --name-only    # expected: those 4 paths
git commit -m "feat(movie-ui): /api/locations routes and jobs, Compose --location fields with V1 rule 12c, --no-arch-check and WARN lines (L4.1-L4.3, L4.5, L4.6; LU1-LU12, LU14, Review Focus 5)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: movie UI page: the Locations tab and the Compose fields (L4.4, L4.5 page; LU13)

This task implements:
- L4.4 `index.html`: the `tab-locations` button after `tab-characters`; Compose's `c-locations` (with `c-locations-note`) and `c-location-strength` after `c-characters`; the `panel-locations` section with every `lo-*` id and the angles note text verbatim. No inline script or handler.
- L4.4 `app.js`:
  - `TABS`, `showTab`, init's `Promise.all` (`loadLocations()`), `setupLocations()` after `setupCharacters()`, and the field collection and restore.
  - The select lists trained locations only, as `name (first 6 words...)`. A 4th selection is dropped with the note `at most 3 locations`.
  - The create form: the word counter and the disabled rule; photos upload one by one through `uploadFile`; the description's whitespace is collapsed before it is sent.
  - The detail: the sheet, one card per manifest item, Save or Regenerate with this description, Regenerate (new seed), Force, Accept and the train form gated by `["render"]`.
  - The two test clips, captioned `with the LoRA` and `without (control)`.
- L4.5 page: the Skip architecture check label and note; `no_arch_check` in the add body; the Verify column appends `| warning: ...`.

A manifest item whose `people_visible` is null shows `people -` (Plan ruling LR21).

**Files:**
- Modify: `static/movie-ui/index.html`: the nav (`:35`), Compose (`:113`), after `panel-characters` (`:192-195`), the LoRA form (`:239`).
- Modify: `static/movie-ui/app.js`: the state (`:11`), `renderBadges` (`:212-214`), `selectWorkspace` (`:263`), `TABS` (`:284`), `showTab` (`:292`), `composeFields` (`:384`), `fillCompose` (`:518-520`), before the actions section (`:881`), `loadCatalogTable` (`:1016`), the add body (`:1060`), `start` (`:1493`).
- Modify: `tests/test_location_ui.py` (append; the imports).
- Read only: `tests/test_movie_ui_http.py` (`test_mut24_page_headers_and_asset_rules` `:1023-1050`: no `https?://`, ` on*=`, `style=`, `alert(`, `confirm(`, `prompt(`, `eval(` in any page file).

**Interfaces:**
- Consumes: Task 11's routes and response shapes (`/api/locations` → `{"locations": [...]}`; the detail `{"location", "files", "manifest", "contact_sheet", "stills", "tests", "last_create_fields"}`; job creation → 201 `{"job"}`; errors → `{"error", "errors"?}`); the page's existing `api`, `el`, `clear`, `show`, `enc`, `fileUrl`, `gate`, `askConfirm`, `uploadFile`, `pollJobs`, `preview`, `numberOrNull`, `textOrNull`, `wsQuery`.
- Produces, in `app.js`: `wordCount`, `firstWords`, `oneLine`, `errorText`, `loadLocations`, `onLocationPick`, `openLocation`, `updateLocationButtons`, `createLocation`, `setupLocations`; `S.locations`, `S.location`, `S.locationPick`.

- [ ] **Step 1: Write the failing test.**

**1.1.** Edit `tests/test_location_ui.py`: replace this text, which occurs exactly once:

```python
    assert (snap["kind"], snap["elapsed_s"], snap["last_line"]) == ("location-create", 5,
                                                                   "=== check ===")
```

with:

```python
    assert (snap["kind"], snap["elapsed_s"], snap["last_line"]) == ("location-create", 5,
                                                                   "=== check ===")


# --- LU13: the static page (L4.4, L4.5) --------------------------------------------------------

LO_IDS = ("lo-list", "lo-name", "lo-description", "lo-words", "lo-trigger", "lo-seed", "lo-photos",
          "lo-angles-note", "lo-create", "lo-create-status", "lo-detail", "lo-title", "lo-sheet",
          "lo-stills", "lo-desc-edit", "lo-desc-save", "lo-regen", "lo-force", "lo-accept",
          "lo-status", "lo-train-form", "lo-train-video", "lo-train-stills", "lo-train-force",
          "lo-train", "lo-train-reason", "lo-tests")


def test_lu13_the_static_page():
    static = os.path.join(WS, "static", "movie-ui")
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(static, "app.js"), encoding="utf-8") as f:
        js = f.read()
    for element in ("tab-locations", "panel-locations", "c-locations", "c-locations-note",
                    "c-location-strength", "l-no-arch-check") + LO_IDS:
        assert html.count('id="%s"' % element) == 1, element
        if element not in ("panel-locations", "tab-locations", "lo-angles-note"):
            assert '"#%s' % element in js, element
    assert html.index('id="tab-characters"') < html.index('id="tab-locations"') < html.index(
        'id="tab-actions"')
    assert html.index('id="c-characters"') < html.index('id="c-locations"') < html.index(
        'id="c-actions"')
    assert ('<p id="lo-angles-note" class="muted">Angles come only from your photos: every extra '
            "still keeps one photo's exact viewpoint and changes only its time of day, weather or "
            "season. For a varied dataset, upload 3-5 photos taken from different spots. Without "
            "photos, the 24 stills are drawn from the description.</p>") in html
    assert '<select id="c-locations" multiple size="3"></select>' in html
    assert ('<input id="c-location-strength" type="number" min="0.05" max="1" step="0.05" '
            'placeholder="0.8">') in html
    assert '<textarea id="lo-description" rows="3" cols="70"></textarea>' in html
    assert ('<input id="lo-photos" type="file" multiple accept="image/png,image/jpeg,image/webp">'
            in html)
    assert ('<label><input id="l-no-arch-check" type="checkbox"> Skip architecture check</label> '
            '<span class="muted">The LoRA is cataloged even if bin/lora-check says it does not fit '
            'the base model; a mismatched LoRA fails or does nothing at render.</span>') in html
    assert ('const TABS = ["compose", "stories", "characters", "locations", "actions", "loras", '
            '"jobs", "traces"];') in js
    assert ("loadCatalog(), loadCharacters(), loadLocations(), loadActions(), loadStories(), "
            "loadModels()") in js
    for text in ('"at most 3 locations"', '"with the LoRA"', '"without (control)"',
                 '"Save description"', '"Regenerate with this description"',
                 '"fewer than 12 stills kept; regenerate the dataset"', '" words (15-40)"',
                 "no_arch_check: $(\"#l-no-arch-check\").checked",
                 'location_strength: numberOrNull("#c-location-strength")',
                 '(r.ok ? "ok" : r.problems.join("; ")) + (r.warnings && r.warnings.length ? " | '
                 'warning: " + r.warnings.join("; ") : "")', "setupLocations();",
                 'if (name === "locations") { loadLocations(); }'):
        assert text in js, text
    for pattern in (r"\son[a-z]+=", r"style=", r"<script>"):
        assert not re.search(pattern, html), pattern
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")],
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr
```

**1.2.** Edit `tests/test_location_ui.py`: replace this text, which occurs exactly once:

```python
import json
import os
import re
import sys
```

with:

```python
import json
import os
import re
import shutil
import subprocess
import sys
```

- [ ] **Step 2: Run it and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_ui.py 2>&1 | tail -1
```

Expected: `1 failed, 14 passed` (LU13).

- [ ] **Step 3: Implement.**

**3.1.** Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
  <button id="tab-characters" type="button" class="tab">Characters</button>
```

with:

```html
  <button id="tab-characters" type="button" class="tab">Characters</button>
  <button id="tab-locations" type="button" class="tab">Locations</button>
```

**3.2.** Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
    <label data-field="characters">Cast <select id="c-characters" multiple size="4"></select></label>
```

with:

```html
    <label data-field="characters">Cast <select id="c-characters" multiple size="4"></select></label>
    <label data-field="locations">Locations <select id="c-locations" multiple size="3"></select> <span id="c-locations-note" class="muted"></span></label>
    <label data-field="location_strength">Location strength <input id="c-location-strength" type="number" min="0.05" max="1" step="0.05" placeholder="0.8"></label>
```

**3.3.** Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
      <button id="ch-train" type="button">Train</button> <span id="ch-train-reason" class="muted"></span>
    </div>
  </div>
</section>
```

with:

```html
      <button id="ch-train" type="button">Train</button> <span id="ch-train-reason" class="muted"></span>
    </div>
  </div>
</section>

<section id="panel-locations" class="panel" hidden>
  <table id="lo-list" class="list"><thead><tr><th>Name</th><th>Status</th><th>Source</th><th>Video</th><th>Stills</th><th>Description</th></tr></thead><tbody></tbody></table>
  <h3>New location</h3>
  <div class="grid">
    <label>Name <input id="lo-name" type="text" size="24" placeholder="harbour-street"></label>
    <label class="wide">Description <textarea id="lo-description" rows="3" cols="70"></textarea> <span id="lo-words" class="muted">0 words (15-40)</span></label>
    <label>Trigger <input id="lo-trigger" type="text" size="16" placeholder="blank = auto"></label>
    <label>Seed <input id="lo-seed" type="number" min="0"></label>
    <label class="wide">Photos <input id="lo-photos" type="file" multiple accept="image/png,image/jpeg,image/webp"></label>
  </div>
  <p id="lo-angles-note" class="muted">Angles come only from your photos: every extra still keeps one photo's exact viewpoint and changes only its time of day, weather or season. For a varied dataset, upload 3-5 photos taken from different spots. Without photos, the 24 stills are drawn from the description.</p>
  <div class="row"><button id="lo-create" type="button" disabled>Create</button> <span id="lo-create-status" class="muted"></span></div>
  <div id="lo-detail" hidden>
    <h2 id="lo-title"></h2>
    <div class="gallery"><img id="lo-sheet" class="sheet" alt="contact sheet" hidden></div>
    <div id="lo-stills" class="gallery"></div>
    <div class="row">
      <label class="wide">Description <textarea id="lo-desc-edit" rows="3" cols="70"></textarea></label>
      <button id="lo-desc-save" type="button">Save description</button>
    </div>
    <div class="row">
      <button id="lo-regen" type="button">Regenerate (new seed)</button>
      <label title="keeps photos that show people; allows regenerating a trained location, which deletes its LoRAs"><input id="lo-force" type="checkbox"> Force</label>
      <button id="lo-accept" type="button">Accept dataset</button>
      <span id="lo-status" class="muted"></span>
    </div>
    <div id="lo-train-form" hidden>
      <label><input id="lo-train-video" type="checkbox" checked> Video LoRA</label>
      <label><input id="lo-train-stills" type="checkbox" checked> Stills LoRA</label>
      <label><input id="lo-train-force" type="checkbox"> Force</label>
      <button id="lo-train" type="button">Train</button> <span id="lo-train-reason" class="muted"></span>
    </div>
    <div id="lo-tests" class="gallery"></div>
  </div>
</section>
```

**3.4.** Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
    <label>Alpha <input id="l-alpha" type="number" min="1"></label>
```

with:

```html
    <label>Alpha <input id="l-alpha" type="number" min="1"></label>
    <label><input id="l-no-arch-check" type="checkbox"> Skip architecture check</label> <span class="muted">The LoRA is cataloged even if bin/lora-check says it does not fit the base model; a mismatched LoRA fails or does nothing at render.</span>
```

**3.5.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    characters: [], seedUpload: null, composeAction: "story", story: null, character: null, action: null, selectedJob: null, logOffset: 0,
```

with:

```js
    characters: [], locations: [], location: null, locationPick: [], seedUpload: null, composeAction: "story", story: null, character: null, action: null, selectedJob: null, logOffset: 0,
```

**3.6.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    updateComposeButtons();
    updateCharacterButtons();
  }
```

with:

```js
    updateComposeButtons();
    updateCharacterButtons();
    updateLocationButtons();
  }
```

**3.7.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    await Promise.all([loadCatalog(), loadCharacters(), loadActions(), loadStories(), loadModels()]);
```

with:

```js
    await Promise.all([loadCatalog(), loadCharacters(), loadLocations(), loadActions(), loadStories(), loadModels()]);
```

**3.8.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
  const TABS = ["compose", "stories", "characters", "actions", "loras", "jobs", "traces"];
```

with:

```js
  const TABS = ["compose", "stories", "characters", "locations", "actions", "loras", "jobs", "traces"];
```

**3.9.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    if (name === "characters") { loadCharacters(); }
```

with:

```js
    if (name === "characters") { loadCharacters(); }
    if (name === "locations") { loadLocations(); }
```

**3.10.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
      characters: Array.prototype.map.call($("#c-characters").selectedOptions, function (o) { return o.value; }),
```

with:

```js
      characters: Array.prototype.map.call($("#c-characters").selectedOptions, function (o) { return o.value; }),
      locations: Array.prototype.map.call($("#c-locations").selectedOptions, function (o) { return o.value; }),
      location_strength: numberOrNull("#c-location-strength"),
```

**3.11.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    Array.prototype.forEach.call($("#c-characters").options, function (o) {
      o.selected = (f.characters || []).indexOf(o.value) >= 0;
    });
```

with:

```js
    Array.prototype.forEach.call($("#c-characters").options, function (o) {
      o.selected = (f.characters || []).indexOf(o.value) >= 0;
    });
    Array.prototype.forEach.call($("#c-locations").options, function (o) {
      o.selected = (f.locations || []).indexOf(o.value) >= 0;
    });
    S.locationPick = (f.locations || []).slice();
    $("#c-location-strength").value = f.location_strength === null || f.location_strength === undefined
      ? "" : f.location_strength;
```

**3.12.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
  // --- actions (motion LoRAs, bin/action) ----------------------------------------------
```

with:

```js
  // --- locations (location library spec L4.4) ------------------------------------------

  function wordCount(text) { return String(text || "").split(/\s+/).filter(Boolean).length; }

  function firstWords(text, n) {
    const words = String(text || "").split(/\s+/).filter(Boolean);
    return words.slice(0, n).join(" ") + (words.length > n ? "..." : "");
  }

  function oneLine(selector) { return $(selector).value.replace(/\s+/g, " ").trim(); }

  function errorText(res) {
    return (res.data && (res.data.errors || [res.data.error]).join("; ")) || ("http " + res.status);
  }

  async function loadLocations() {
    if (!S.ws) { return; }
    const res = await api("GET", "/api/locations" + wsQuery());
    S.locations = res.status === 200 ? res.data.locations : [];
    const body = clear($("#lo-list tbody"));
    const pick = $("#c-locations");
    const chosen = Array.prototype.map.call(pick.selectedOptions, function (o) { return o.value; });
    clear(pick);
    S.locations.forEach(function (l) {
      const row = el("tr", {data: {location: l.name}, cls: "clickable"}, l.invalid ?
        [el("td", {text: l.name}), el("td", {text: "invalid: " + l.invalid}), el("td"), el("td"), el("td"), el("td")] :
        [el("td", {text: l.name}), el("td", {text: l.status}), el("td", {text: l.source}),
         el("td", {text: l.video ? "yes" : "no"}), el("td", {text: l.stills ? "yes" : "no"}),
         el("td", {text: l.description})]);
      row.addEventListener("click", function () { openLocation(l.name); });
      body.appendChild(row);
      if (l.status === "trained") {
        const option = el("option", {value: l.name, text: l.name + " (" + firstWords(l.description, 6) + ")"});
        option.selected = chosen.indexOf(l.name) >= 0;
        pick.appendChild(option);
      }
    });
    S.locationPick = Array.prototype.map.call(pick.selectedOptions, function (o) { return o.value; });
  }

  function onLocationPick() {
    const pick = $("#c-locations");
    if (pick.selectedOptions.length > 3) {
      Array.prototype.forEach.call(pick.options, function (o) {
        if (o.selected && S.locationPick.indexOf(o.value) < 0) { o.selected = false; }
      });
      $("#c-locations-note").textContent = "at most 3 locations";
    } else {
      $("#c-locations-note").textContent = "";
    }
    S.locationPick = Array.prototype.map.call(pick.selectedOptions, function (o) { return o.value; });
    preview();
  }

  async function openLocation(name) {
    const res = await api("GET", "/api/locations/" + enc(name) + wsQuery());
    if (res.status !== 200) { $("#lo-status").textContent = errorText(res); return; }
    S.location = res.data;
    const loc = res.data.location;
    show($("#lo-detail"), true);
    $("#lo-title").textContent = name + " (" + loc.status + ", " + loc.source + ")";
    const sheet = $("#lo-sheet");
    if (res.data.contact_sheet) { sheet.src = fileUrl(res.data.contact_sheet); }
    show(sheet, Boolean(res.data.contact_sheet));
    const byN = {};
    res.data.stills.forEach(function (p) {
      const m = /loc_(\d+)\.png$/.exec(p);
      if (m) { byN[Number(m[1])] = p; }
    });
    const stills = clear($("#lo-stills"));
    (res.data.manifest || []).forEach(function (item) {
      const parts = [];
      if (byN[item.n]) { parts.push(el("img", {src: fileUrl(byN[item.n]), alt: "still " + item.n})); }
      const people = item.people_visible === null ? "people -" : (item.people_visible ? "people" : "no people");
      parts.push(el("figcaption", {text: [item.source, item.match_score === null ? "score -" : "score " + item.match_score,
        people, item.caption || "", item.kept ? "kept" : "dropped: " + (item.reason || "")].join("; ")}));
      stills.appendChild(el("figure", {}, parts));
    });
    $("#lo-desc-edit").value = loc.description || "";
    $("#lo-desc-save").textContent = loc.source === "photos" ? "Save description" : "Regenerate with this description";
    show($("#lo-train-form"), false);
    const tests = clear($("#lo-tests"));
    if (res.data.tests.video_lora && res.data.tests.video_control) {
      [["video_lora", "with the LoRA"], ["video_control", "without (control)"]].forEach(function (t) {
        tests.appendChild(el("figure", {}, [el("video", {src: fileUrl(res.data.tests[t[0]]), controls: ""}),
          el("figcaption", {text: t[1]})]));
      });
    }
    $("#lo-status").textContent = "";
    updateLocationButtons();
  }

  function updateLocationButtons() {
    const words = wordCount($("#lo-description").value);
    const photos = $("#lo-photos").files.length;
    const okWords = words >= 15 && words <= 40;
    $("#lo-words").textContent = words + " words (15-40)";
    $("#lo-create").disabled = !/^[a-z][a-z0-9-]{1,23}$/.test($("#lo-name").value.trim()) || photos > 24
      || (words > 0 && !okWords) || (photos === 0 && !okWords);
    gate($("#lo-train"), $("#lo-train-reason"), ["render"]);
    if (S.location && S.location.location.status === "dataset") {
      $("#lo-train").disabled = true;
      $("#lo-train-reason").textContent = "fewer than 12 stills kept; regenerate the dataset";
    }
  }

  async function createLocation() {
    const status = $("#lo-create-status");
    const files = Array.prototype.slice.call($("#lo-photos").files);
    const uploads = [];
    try {
      for (let i = 0; i < files.length; i += 1) {
        status.textContent = "uploading photo " + (i + 1) + " of " + files.length + "...";
        uploads.push(await uploadFile(files[i]));
      }
    } catch (err) {
      status.textContent = String(err.message);
      return;
    }
    const res = await api("POST", "/api/locations", {ws: S.ws, name: $("#lo-name").value.trim(),
      description: oneLine("#lo-description") || null, photo_uploads: uploads, trigger: textOrNull("#lo-trigger"),
      seed: numberOrNull("#lo-seed"), force: false});
    status.textContent = res.status === 201 ? "queued job " + res.data.job.id : errorText(res);
    if (res.status === 201) { pollJobs(); }
  }

  function setupLocations() {
    $("#lo-name").addEventListener("input", updateLocationButtons);
    $("#lo-description").addEventListener("input", updateLocationButtons);
    $("#lo-photos").addEventListener("change", updateLocationButtons);
    $("#lo-create").addEventListener("click", createLocation);
    $("#c-locations").addEventListener("change", onLocationPick);
    $("#lo-accept").addEventListener("click", function () { show($("#lo-train-form"), true); });
    $("#lo-desc-save").addEventListener("click", async function () {
      const loc = S.location.location;
      const res = loc.source === "photos"
        ? await api("PATCH", "/api/locations/" + enc(loc.name), {ws: S.ws, description: oneLine("#lo-desc-edit")})
        : await api("POST", "/api/locations/" + enc(loc.name) + "/regenerate",
                    {ws: S.ws, description: oneLine("#lo-desc-edit"), force: $("#lo-force").checked});
      $("#lo-status").textContent = res.status === 200 ? "description saved"
        : res.status === 201 ? "queued job " + res.data.job.id : errorText(res);
      if (res.status === 200) { openLocation(loc.name); loadLocations(); }
      if (res.status === 201) { pollJobs(); }
    });
    $("#lo-regen").addEventListener("click", async function () {
      const name = S.location.location.name;
      if (!(await askConfirm("Regenerate the dataset of " + name + " with a new seed?"))) { return; }
      const res = await api("POST", "/api/locations/" + enc(name) + "/regenerate",
                            {ws: S.ws, new_seed: true, force: $("#lo-force").checked});
      $("#lo-status").textContent = res.status === 201 ? "queued job " + res.data.job.id : errorText(res);
      if (res.status === 201) { pollJobs(); }
    });
    $("#lo-train").addEventListener("click", async function () {
      const name = S.location.location.name;
      const res = await api("POST", "/api/locations/" + enc(name) + "/train",
                            {ws: S.ws, video: $("#lo-train-video").checked, stills: $("#lo-train-stills").checked,
                             force: $("#lo-train-force").checked});
      $("#lo-train-reason").textContent = res.status === 201 ? "queued job " + res.data.job.id : errorText(res);
      if (res.status === 201) { pollJobs(); }
    });
    updateLocationButtons();
  }

  // --- actions (motion LoRAs, bin/action) ----------------------------------------------
```

**3.13.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    (results || []).forEach(function (r) { verdicts[r.id] = r.ok ? "ok" : r.problems.join("; "); });
```

with:

```js
    (results || []).forEach(function (r) {
      verdicts[r.id] = (r.ok ? "ok" : r.problems.join("; ")) + (r.warnings && r.warnings.length ? " | warning: " + r.warnings.join("; ") : "");
    });
```

**3.14.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
        rank: numberOrNull("#l-rank"), alpha: numberOrNull("#l-alpha")};
```

with:

```js
        rank: numberOrNull("#l-rank"), alpha: numberOrNull("#l-alpha"),
        no_arch_check: $("#l-no-arch-check").checked};
```

**3.15.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    setupCharacters();
```

with:

```js
    setupCharacters();
    setupLocations();
```

- [ ] **Step 4: Run the new tests and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_ui.py tests/test_movie_ui_http.py -k "location or mut24 or regenerate_seed" 2>&1 | tail -1
command -v node >/dev/null && node --check static/movie-ui/app.js && echo "node ok"
```

Expected: every selected test passes; `node ok` when `node` is installed. Run the compile check with `FILES` = `tests/test_location_ui.py`; expected: `compiled 1` twice. Then run the gate block with `N=12`. Expected: `GATE PASS`, `new-file tests 109, not passing 0`, `baseline failures still failing 2 of 2`, `OK 347/347`, and the same five listed LOST lines as Task 11.

- [ ] **Step 5: Commit.**

```bash
git add static/movie-ui/index.html static/movie-ui/app.js tests/test_location_ui.py
git diff --cached --name-only    # expected: those 3 paths
git commit -m "feat(movie-ui): the Locations tab, Compose's Locations and Location strength, and the LoRA tab's Skip architecture check and warnings (L4.4, L4.5; LU13)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: `bin/lora-check` and `bin/lora-catalog`: bare tables and the low-RAM warning (L4.7, L4.8; LC1-LC9, LL1)

This task implements:
- L4.7: `base_linear_map` also takes a key that does not end with `.weight`, `_QUANT_SUFFIXES` or `.bias` and has a 2-D shape, via `out.setdefault(_core(key), (shape[0], shape[1], False))`. A `.weight` entry always wins.
- L4.8, `bin/lora-check`: `LOW_RAM_WARNING`, `low_ram_skipped(header) -> (outside, total)` and `low_ram_warning(header)`, which is the text when `0 < outside < total`, else None (Plan ruling LR1).
  - In `main`, every result gets `"warnings"` (`[]` by default; a `video` target gets the warning).
  - Text output prints `"    ! " + warning` after the problem lines.
  - `static_check`, every status, the summary line and the exit code are unchanged.
- L4.8, `bin/lora-catalog`: `_checker_or_none()`.
  - `add` prints `warning: <text>` on stderr for a video target, after the arch gate (if any) has run, with or without `--no-arch-check`.
  - `verify` prints `WARN <id>: <text>` after a video entry's `OK`/`FAIL` lines. No problem count and no exit code changes.
- LL1: every new and changed Python file and `bin/` script compiles under `/usr/bin/python3` and `sys.executable`; `bash -n bin/location-train-vlm` (LK3). It is added here because the last file it names is changed in this task.

**Files:**
- Modify: `bin/lora-check`: `base_linear_map` (`:158-162`), before `_match_base` (`:181`), `main` (`:395-402`, `:411-412`).
- Modify: `bin/lora-catalog`: before `_arch_gate` (`:43`), `cmd_add` (`:146-148`), `cmd_verify` (`:276-284`).
- Create: `tests/test_lora_check_fixes.py`. Modify: `tests/test_location_lib.py` (append LL1).
- Read only: `tests/test_lora_compat.py`, `tests/test_lora_catalog.py` (`test_lct7_add_happy_path` `:255-275`, `test_lct11_verify` `:401-437`), `~/ltx-2-mlx/.../fuse_loras.py:103-105` (cited by the spec; not opened by any step).

**Interfaces:**
- Consumes (existing): `lora_catalog.read_safetensors_header`, `CatalogError`, `LORA_A_SUFFIX`; `bin/lora-check`'s `lora_targets`, `_core`, `_shape`, `_QUANT_SUFFIXES`, `static_check`.
- Produces, in `bin/lora-check`: `LOW_RAM_WARNING`, `low_ram_skipped(header)`, `low_ram_warning(header)`, the results' `"warnings"`. In `bin/lora-catalog`: `_checker_or_none()`.
- Produces, in the tests: `write_safetensors`, `_modules`, `comfy_lora`, `mlx_base`, `_old_checker(tmp_path, monkeypatch)`, `WARNING`, `COMPILED`.

- [ ] **Step 1: Write the failing tests.**

**1.1.** Create `tests/test_lora_check_fixes.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""Tests for the location library's two bin/lora-check fixes (docs/superpowers/specs/
2026-10-29-location-lora-design.md, Sections 5.7 and 5.8, test table 6.8: LC1-LC8, KPI LK9, with
the plan's ruling pin LC9): bare 2-D base parameters (scale/shift tables) are base targets, and a
LoRA whose modules lie partly outside the transformer blocks gets a low-RAM warning from
bin/lora-check, bin/lora-catalog add and bin/lora-catalog verify, without changing any PASS/FAIL
status, problem count or exit code.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_lora_check_fixes.py
Stdlib plus pytest. Every LoRA and base model is a synthetic safetensors file (a header and
zeroed data) under tmp_path; no test reads the real HOME, renders, contacts a model server or
touches port 8178 (the autouse story_env fixture: HOME, CHARACTER_LIBRARY_DIR,
LOCATION_LIBRARY_DIR and LORA_CATALOG_DIR under tmp_path; no HF_HOME).
"""

import importlib.machinery
import inspect
import json
import math
import os
import struct
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402

CHECK_PATH = os.path.join(WS, "bin", "lora-check")
CATALOG_CLI = os.path.join(WS, "bin", "lora-catalog")
chk = importlib.machinery.SourceFileLoader("lora_check_for_location", CHECK_PATH).load_module()
_BYTES = {"F32": 4, "BF16": 2, "F16": 2, "U32": 4}
TABLES = ("scale_shift_table", "audio_scale_shift_table", "prompt_scale_shift_table",
          "audio_prompt_scale_shift_table", "scale_shift_table_a2v_ca_video",
          "scale_shift_table_a2v_ca_audio")
WARNING = ("44 of 1724 modules are outside the transformer blocks and are skipped in low-RAM "
           "mode; render with --no-low-ram to use them")
ARCH_UNVERIFIED = ("arch: architecture UNVERIFIED: none of the declared base models are on disk "
                   "yet; run bin/lora-check once the base is installed\n")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


def write_safetensors(path, tensors, metadata=None):
    """tensors: {name: (dtype, shape)}, in order; zeroed data with consistent offsets (as
    tests/test_lora_compat.py)."""
    header, offset = {}, 0
    for name, (dtype, shape) in tensors.items():
        nbytes = _BYTES[dtype] * math.prod(shape)
        header[name] = {"dtype": dtype, "shape": shape, "data_offsets": [offset, offset + nbytes]}
        offset += nbytes
    if metadata:
        header["__metadata__"] = {k: str(v) for k, v in metadata.items()}
    blob = json.dumps(header).encode("utf-8")
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(blob)) + blob + b"\x00" * offset)
    return path


def _modules(blocks=48, linears=29, top_linears=42):
    """[(module, out, in)]: per block the linears and the six tables, then the top-level linears
    and the two top-level tables (the measured 1724-pair ComfyUI LTX-2.3 layout)."""
    out = []
    for b in range(blocks):
        out += [("transformer_blocks.%d.lin%02d" % (b, k), 8, 8) for k in range(linears)]
        out += [("transformer_blocks.%d.%s" % (b, t), 9, 8) for t in TABLES]
    out += [("top%02d" % k, 8, 8) for k in range(top_linears)]
    out += [(t, 2, 8) for t in TABLES[:2]]
    return out


def comfy_lora(path, modules, rank=4):
    tensors = {}
    for module, out_f, in_f in modules:
        tensors["diffusion_model.%s.lora_A.weight" % module] = ("F32", [rank, in_f])
        tensors["diffusion_model.%s.lora_B.weight" % module] = ("F32", [out_f, rank])
    return write_safetensors(path, tensors, metadata={"lora_alpha": rank})


def mlx_base(directory, modules):
    """A bf16 base whose linears are <module>.weight and whose tables are bare 2-D keys."""
    os.makedirs(directory, exist_ok=True)
    tensors = {}
    for module, out_f, in_f in modules:
        name = "transformer.%s" % module
        tensors[name if "table" in module else name + ".weight"] = ("BF16", [out_f, in_f])
    write_safetensors(os.path.join(directory, "model.safetensors"), tensors)
    return directory


def _old_checker(tmp_path, monkeypatch):
    """bin/lora-check as it was at d210c26, from git show (skips outside a git checkout that has
    d210c26); QWEN_AGENT_WORKSPACE points its lora_catalog load at this workspace."""
    old = subprocess.run(["git", "-C", WS, "show", "d210c26:./bin/lora-check"],
                         capture_output=True, text=True)
    if old.returncode != 0:
        pytest.skip("not a git checkout with d210c26")
    path = str(tmp_path / "lora_check_d210c26.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(old.stdout)
    with monkeypatch.context() as m:
        m.setenv("QWEN_AGENT_WORKSPACE", WS)
        return importlib.machinery.SourceFileLoader("lora_check_d210c26", path).load_module()


# --- LC1, LC2: bare 2-D parameters are base targets (L4.7) -------------------------------------

def test_lc1_scale_shift_tables_match(tmp_path, monkeypatch):
    modules = [("transformer_blocks.0.attn1.to_q", 64, 64),
               ("transformer_blocks.0.scale_shift_table", 9, 4096), ("scale_shift_table", 2, 4096)]
    base = mlx_base(str(tmp_path / "base"), modules)
    lora = comfy_lora(str(tmp_path / "tables.safetensors"), modules, rank=8)
    assert chk.base_linear_map(base) == {"transformer_blocks.0.attn1.to_q": (64, 64, False),
                                         "transformer_blocks.0.scale_shift_table": (9, 4096, False),
                                         "scale_shift_table": (2, 4096, False)}
    assert chk.static_check(lora, base) == ("PASS", [])
    status, problems = _old_checker(tmp_path, monkeypatch).static_check(lora, base)
    assert status == "FAIL" and "2/3 target modules absent from the base" in problems[0]


def test_lc2_quant_keys_are_not_targets_and_weight_entries_win(tmp_path):
    base = str(tmp_path / "qbase")
    os.makedirs(base)
    with open(os.path.join(base, "config.json"), "w") as f:
        json.dump({"quantization": {"bits": 8, "group_size": 64}}, f)
    write_safetensors(os.path.join(base, "model.safetensors"), {
        "transformer.blocks.0.attn.to_q.weight": ("U32", [128, 32]),
        "transformer.blocks.0.attn.to_q.scales": ("F16", [128, 2]),
        "transformer.blocks.0.attn.to_q.biases": ("F16", [128, 2]),
        "transformer.blocks.0.attn.to_q.bias": ("F16", [128, 2]),
        "transformer.blocks.0.attn.to_k.qzeros": ("F16", [128, 2])})
    assert chk.base_linear_map(base) == {"blocks.0.attn.to_q": (128, 128, True)}
    for order in ("bare first", "weight first"):
        other = str(tmp_path / order.replace(" ", "-"))
        os.makedirs(other)
        tensors = [("transformer.x", ("BF16", [9, 9])), ("transformer.x.weight", ("BF16", [4, 8]))]
        write_safetensors(os.path.join(other, "model.safetensors"),
                          dict(tensors if order == "bare first" else tensors[::-1]))
        assert chk.base_linear_map(other) == {"x": (4, 8, False)}, order


# --- LC3, LC4, LC8, LC9: the 1724-pair LoRA and the low-RAM warning (L4.8, LK9) ---------------

def test_lc3_the_1724_pair_lora_is_not_fail(tmp_path, monkeypatch):
    modules = _modules()
    assert len(modules) == 48 * 29 + 288 + 42 + 2 == 1724
    base = mlx_base(str(tmp_path / "base"), modules)
    lora = comfy_lora(str(tmp_path / "comfy.safetensors"), modules)
    status, problems = chk.static_check(lora, base)
    assert status != "FAIL" and not any("absent" in p for p in problems), problems
    header = chk.lc.read_safetensors_header(lora)
    assert chk.low_ram_skipped(header) == (44, 1724)
    assert chk.LOW_RAM_WARNING % (44, 1724) == WARNING
    assert chk.low_ram_warning(header) == WARNING
    status, problems = _old_checker(tmp_path, monkeypatch).static_check(lora, base)
    assert status == "FAIL" and "290/1724 target modules absent" in problems[0]


def test_lc4_lora_check_reports_the_warning(tmp_path, capsys):
    modules = _modules()
    base = mlx_base(str(tmp_path / "base"), modules)
    lora = comfy_lora(str(tmp_path / "comfy.safetensors"), modules)
    assert chk.main(["--json", "--video-base", base, lora]) == 0
    (result,) = json.loads(capsys.readouterr().out)["results"]
    assert (result["target"], result["status"], result["warnings"]) == ("video", "PASS", [WARNING])
    assert chk.main(["--video-base", base, lora]) == 0
    out = capsys.readouterr().out
    assert "[PASS] %s  (video, arg)\n    ! %s\n" % (lora, WARNING) in out
    assert out.endswith("\n1 checked, 0 FAIL, 0 unverified/partial\n")
    stills = write_safetensors(str(tmp_path / "stills.safetensors"), {
        "single_blocks.0.img_attn.lora_A.weight": ("F32", [4, 8]),
        "single_blocks.0.img_attn.lora_B.weight": ("F32", [8, 4])}, metadata={"lora_alpha": 4})
    assert chk.main(["--json", "--stills-base", str(tmp_path / "none"), stills]) == 0
    (result,) = json.loads(capsys.readouterr().out)["results"]
    assert (result["target"], result["warnings"]) == ("stills", [])


def test_lc8_a_character_lora_gives_no_warning(tmp_path, capsys):
    modules = [("transformer_blocks.%d.attn1.to_q" % b, 8, 8) for b in range(3)]
    base = mlx_base(str(tmp_path / "base"), modules)
    lora = str(tmp_path / "character.safetensors")
    tensors = {}
    for module, _out, _in in modules:
        tensors[module + ".lora_A.weight"] = ("F32", [4, 8])
        tensors[module + ".lora_B.weight"] = ("F32", [8, 4])
    write_safetensors(lora, tensors, metadata={"lora_alpha": 4})
    header = chk.lc.read_safetensors_header(lora)
    assert chk.low_ram_skipped(header) == (0, 3) and chk.low_ram_warning(header) is None
    assert chk.main(["--json", "--video-base", base, lora]) == 0
    assert json.loads(capsys.readouterr().out)["results"][0]["warnings"] == []


def test_lc9_a_lora_with_no_module_in_the_blocks_gives_no_warning(tmp_path):
    # Plan ruling: the warning is for a LoRA the low-RAM path skips in part; a LoRA with no module
    # under transformer_blocks. (the synthetic fixtures of the existing catalog tests) gets none.
    lora = seu.lora_file(str(tmp_path), "fake")
    header = chk.lc.read_safetensors_header(lora)
    assert chk.low_ram_skipped(header) == (1, 1) and chk.low_ram_warning(header) is None


def test_lc5_static_check_is_unchanged():
    assert list(inspect.signature(chk.static_check).parameters) == ["lora_path", "base_dir"]
    with open(os.path.join(WS, "bin", "ltx-movie"), encoding="utf-8") as f:
        assert "status, problems = checker.static_check(path, base)" in f.read()


# --- LC6, LC7: bin/lora-catalog add and verify (L4.8) --------------------------------------------

def _catalog(*argv):
    return subprocess.run([sys.executable, CATALOG_CLI] + list(argv), cwd=WS, capture_output=True,
                          text=True, timeout=300)


def test_lc6_lc7_lora_catalog_warns_and_keeps_its_exit_codes(tmp_path, story_env):
    lora = comfy_lora(str(tmp_path / "comfy.safetensors"), _modules())
    add = ["add", lora, "--kind", "motion", "--target", "video", "--base-model", seu.VIDEO_MODEL,
           "--description", "a comfy motion", "--use-when", "a chase"]
    first = _catalog(*(add[:2] + ["--id", "comfy-one"] + add[2:]))
    assert (first.returncode, first.stderr) == (0, ARCH_UNVERIFIED + "warning: %s\n" % WARNING)
    assert first.stdout.startswith("added comfy-one (motion, video, rank 4, sha256 ")
    copy = str(tmp_path / "comfy-copy.safetensors")
    with open(lora, "rb") as src, open(copy, "wb") as dst:
        dst.write(src.read() + b"\x00")
    second = _catalog(*(["add", copy, "--id", "comfy-two"] + add[2:] + ["--no-arch-check"]))
    assert (second.returncode, second.stderr) == (0, "warning: %s\n" % WARNING)
    with open(os.path.join(story_env["catalog"], "catalog.json")) as f:
        assert [e["id"] for e in json.load(f)["entries"]] == ["comfy-one", "comfy-two"]
    plain = seu.lora_file(str(tmp_path / "files"), "plain")
    third = _catalog(*(["add", plain, "--id", "plain-motion"] + add[2:]))
    assert (third.returncode, third.stderr) == (0, ARCH_UNVERIFIED)
    verify = _catalog("verify")
    assert verify.returncode == 0
    assert verify.stdout == ("OK comfy-one\nWARN comfy-one: %s\nOK comfy-two\nWARN comfy-two: %s\n"
                             "OK plain-motion\nverified 3 entries: 0 problem(s)\n" % (WARNING,
                                                                                    WARNING))
    os.remove(copy)
    broken = _catalog("verify")
    assert broken.returncode == 1
    lines = broken.stdout.splitlines()
    assert lines[:2] == ["OK comfy-one", "WARN comfy-one: %s" % WARNING]
    assert lines[2].startswith("FAIL comfy-two: ") and not any(
        line.startswith("WARN comfy-two") for line in lines)
    assert lines[-1].startswith("verified 3 entries: ") and lines[-1].endswith(" problem(s)")
```

**1.2.** Edit `tests/test_location_lib.py`: replace this text, which occurs exactly once:

```python
    assert proc.stdout.splitlines() == ["[]", "[]", "['character_lib']"]
```

with:

```python
    assert proc.stdout.splitlines() == ["[]", "[]", "['character_lib']"]


# --- LL1: every new and changed file compiles under both Pythons (LK3) ------------------------

COMPILED = ("location_lib.py", "location_dataset.py", "bin/location", "story_engine.py",
            "character_dataset.py", "bin/ltx-movie", "bin/ltx-story-manifest",
            "bin/ltx-story-images", "bin/ltx-mlx-render", "bin/iterate-story", "bin/lora-check",
            "bin/lora-catalog", "movie_ui_lib.py", "movie_ui_server.py")


@pytest.mark.parametrize("python", ["/usr/bin/python3", sys.executable])
def test_ll1_every_new_and_changed_file_compiles(python, tmp_path):
    if not os.path.isfile(python):
        pytest.skip("%s is not installed" % python)
    script = ("import os, py_compile, sys\n"
              "out = sys.argv[1]\n"
              "for k, path in enumerate(sys.argv[2:]):\n"
              "    py_compile.compile(path, cfile=os.path.join(out, '%d.pyc' % k), doraise=True)\n"
              "print('compiled %d' % (len(sys.argv) - 2))\n")
    proc = subprocess.run([python, "-B", "-c", script, str(tmp_path)]
                          + [os.path.join(WS, rel) for rel in COMPILED],
                          capture_output=True, text=True, timeout=300)
    assert (proc.returncode, proc.stdout) == (0, "compiled 14\n"), proc.stderr
    bash = subprocess.run(["bash", "-n", os.path.join(WS, "bin", "location-train-vlm")],
                          capture_output=True, text=True, timeout=60)
    assert bash.returncode == 0, bash.stderr
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_lib.py tests/test_lora_check_fixes.py 2>&1 | tail -1
```

Expected: `6 failed, 17 passed` (LC1, LC3, LC4, LC6/LC7, LC8 and LC9; LC2, LC5 and both LL1 cases already hold).

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/lora-check`: replace this text, which occurs exactly once:

```python
    out = {}
    for key in merged:
        if not key.endswith(".weight"):
            continue
        core = _core(key)
```

with:

```python
    out = {}
    for key in merged:
        if not key.endswith(".weight"):
            # Location library spec L4.7: a bare 2-D parameter (a scale/shift table) is a base
            # target too, as the ltx-2-mlx fuser treats it (fuse_loras.py:103-105); a .weight
            # entry is never replaced by one.
            if not key.endswith(_QUANT_SUFFIXES + (".bias",)):
                bshape = _shape(merged, key)
                if bshape and len(bshape) == 2:
                    out.setdefault(_core(key), (bshape[0], bshape[1], False))
            continue
        core = _core(key)
```

**3.2.** Edit `bin/lora-check`: replace this text, which occurs exactly once:

```python
def _match_base(base_map, module):
```

with:

```python
# Location library spec L4.8: the ltx-2-mlx low-RAM path loads only transformer_blocks.* LoRA keys
# (BlockLoraSource with block_prefix LTXV_LORA_BLOCK_PREFIX), so it skips every other module.
LOW_RAM_WARNING = ("%d of %d modules are outside the transformer blocks and are skipped in low-RAM "
                   "mode; render with --no-low-ram to use them")


def low_ram_skipped(header):
    """(outside, total): how many of the LoRA's target modules (lora_targets) lie outside the
    transformer blocks, and how many there are."""
    targets = lora_targets(header)
    outside = sum(1 for module in targets if not module.startswith("transformer_blocks."))
    return outside, len(targets)


def low_ram_warning(header):
    """LOW_RAM_WARNING for a LoRA that the low-RAM path skips in part (some, not all, of its
    modules outside the transformer blocks), else None."""
    outside, total = low_ram_skipped(header)
    return LOW_RAM_WARNING % (outside, total) if 0 < outside < total else None


def _match_base(base_map, module):
```

**3.3.** Edit `bin/lora-check`: replace this text, which occurs exactly once:

```python
        quarantined = False
        if status == "FAIL":
            any_fail = True
            if args.quarantine and source.startswith("catalog:"):
                quarantined = bool(quarantine_catalog_entry(path))
        results.append({"path": path, "target": target, "source": source,
                        "status": status, "problems": problems,
                        "quarantined": quarantined})
```

with:

```python
        warnings = []
        if target == "video":
            try:
                warning = low_ram_warning(lc.read_safetensors_header(path))
            except lc.CatalogError:
                warning = None
            if warning:
                warnings.append(warning)
        quarantined = False
        if status == "FAIL":
            any_fail = True
            if args.quarantine and source.startswith("catalog:"):
                quarantined = bool(quarantine_catalog_entry(path))
        results.append({"path": path, "target": target, "source": source,
                        "status": status, "problems": problems,
                        "quarantined": quarantined, "warnings": warnings})
```

**3.4.** Edit `bin/lora-check`: replace this text, which occurs exactly once:

```python
            for p in r["problems"]:
                print("    - " + p)
```

with:

```python
            for p in r["problems"]:
                print("    - " + p)
            for w in r["warnings"]:
                print("    ! " + w)
```

**3.5.** Edit `bin/lora-catalog`: replace this text, which occurs exactly once:

```python
def _arch_gate(path, target, base_models):
```

with:

```python
def _checker_or_none():
    """bin/lora-check as a module, or None when it cannot be loaded (the low-RAM warning is then
    skipped; location library spec L4.8)."""
    try:
        return _load_checker()
    except Exception:  # noqa: BLE001 - tooling problem must not block cataloging
        return None


def _arch_gate(path, target, base_models):
```

**3.6.** Edit `bin/lora-catalog`: replace this text, which occurs exactly once:

```python
            if not ok:
                return _error("refusing to catalog %s: it does not match the base architecture "
                              "(use --no-arch-check to override)" % args.path)
```

with:

```python
            if not ok:
                return _error("refusing to catalog %s: it does not match the base architecture "
                              "(use --no-arch-check to override)" % args.path)
        if args.target == "video":
            checker = _checker_or_none()
            warning = checker.low_ram_warning(header) if checker is not None else None
            if warning:
                print("warning: %s" % warning, file=sys.stderr)
```

**3.7.** Edit `bin/lora-catalog`: replace this text, which occurs exactly once:

```python
    char_triggers = lora_catalog.character_triggers(WS)
    problems = 0
    for entry in selected:
        found = lora_catalog.verify_entry(entry, entries, char_triggers)
        if not found:
            print("OK %s" % entry["id"])
        for problem in found:
            print("FAIL %s: %s" % (entry["id"], problem))
        problems += len(found)
```

with:

```python
    char_triggers = lora_catalog.character_triggers(WS)
    checker = _checker_or_none()
    problems = 0
    for entry in selected:
        found = lora_catalog.verify_entry(entry, entries, char_triggers)
        if not found:
            print("OK %s" % entry["id"])
        for problem in found:
            print("FAIL %s: %s" % (entry["id"], problem))
        problems += len(found)
        if checker is not None and entry["target"] == "video":
            try:
                warning = checker.low_ram_warning(
                    lora_catalog.read_safetensors_header(entry["path"]))
            except lora_catalog.CatalogError:
                warning = None
            if warning:
                print("WARN %s: %s" % (entry["id"], warning))
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_lib.py tests/test_lora_check_fixes.py tests/test_lora_compat.py tests/test_lora_catalog.py 2>&1 | tail -1
```

Expected: every test passes. Run the compile check with `FILES` = `bin/lora-check bin/lora-catalog tests/test_lora_check_fixes.py tests/test_location_lib.py`; expected: `compiled 4` twice. Then run the gate block with `N=13`. Expected: `GATE PASS`, `new-file tests 119, not passing 0`, `baseline failures still failing 2 of 2`, `OK 347/347`, and the same five listed LOST lines as Task 11. The run's summary is `7 failed, 2101 passed, 2 skipped` (the two baseline failures and the five listed tests; 1987 - 5 + 119 passed), as measured on the plan's replay.

- [ ] **Step 5: Commit.**

```bash
git add bin/lora-check bin/lora-catalog tests/test_lora_check_fixes.py tests/test_location_lib.py
git diff --cached --name-only    # expected: those 4 paths
git commit -m "fix(lora-check): match bare scale/shift tables and warn about LoRA modules the low-RAM render skips; lora-catalog add and verify show the warning (L4.7, L4.8; LC1-LC9, LL1)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Whole-branch review, the test-only re-baseline (`test_mut18`, `test_mut3`, `test_mut26`, and `test_mu14`, `test_spt1a`), LK1-LK10 and the hand-off

**Files:**
- Modify (test-only, Step 3):
  - `tests/test_movie_ui_http.py`: `test_mut18` `:43`, `test_mu14_ws_parameter_errors_and_options` `:224`;
  - `tests/test_movie_ui_builder.py`: `ALL_MU37_FLAGS` `:117`, `test_mut3` `:130-131` and `:136`, `test_mut26`'s comment `:283` and `BASELINE` `:285`;
  - `tests/fixtures/movie_ui/ltx-movie-help-current.txt`: after the `--character-strength` entry, `:89-91`;
  - `tests/test_soft_panel_count.py`: `test_spt1a_engine_constants` `:179-181`.

**Interfaces:**
- Consumes: the commits of Tasks 1-13.
- Produces: the one test-only re-baseline commit (spec 6.9, 0.3 G15), `$D/final-pytest.txt`, and the hand-off report.

- [ ] **Step 1: Design review (controller; spec 8 step 5).**
  - Ask an Opus `design-reviewer` to review `git diff d210c26..HEAD -- qwen-agent-workspace` against the spec, this plan's rulings and the Review Focus.
  - Fix every finding in a new commit on the owning task's files, then rerun that task's Step 4.
  - The re-baseline below comes after the review, so `test_mut26`'s baseline is the last pipeline commit, fixes included.

- [ ] **Step 2: Find the last pipeline commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
git log -1 --format='%H %s' -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py
```

Expected: one line: a 40-character SHA, then the subject of Task 13's commit (it touches `bin/lora-catalog`), or of a Step 1 fix commit that touched a `PIPELINE_FILES` entry. In Step 3, **SHA** means exactly those 40 characters, typed in place of the word `SHA`.

- [ ] **Step 3: The re-baseline edits (spec 6.9; test-only).**

**3.1.** Edit `tests/fixtures/movie_ui/ltx-movie-help-current.txt`: replace this text, which occurs exactly once:

```text
                        with --shots, where every cast character uses this
                        strength
  --action NAME[:STRENGTH]
```

with:

```text
                        with --shots, where every cast character uses this
                        strength
  --location NAME       pin a trained location from generated/locations/
                        (repeatable, at most 3): the story plan sets at least
                        one beat there with the location's fixed setting, and
                        only the panels set there render with its LoRAs and
                        trigger. See
                        docs/superpowers/specs/2026-10-29-location-lora-
                        design.md.
  --location-strength LOCATION_STRENGTH
                        LoRA strength for each pinned location without its own
                        location.json strength (default 0.8), on every panel
                        set there
  --action NAME[:STRENGTH]
```

**3.2.** Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
                  "--lora", "--stills-lora", "--character", "--action", "--no-auto-lora", "--no-narration", "--speech-only", "--story-legacy", "--judge",
```

with:

```python
                  "--lora", "--stills-lora", "--character", "--location", "--location-strength", "--action", "--no-auto-lora", "--no-narration", "--speech-only", "--story-legacy", "--judge",
```

**3.3.** Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
    assert current - old == {"--story-only", "--story-legacy", "--no-auto-lora", "--judge", "--goal", "--gemma",
                             "--no-narration", "--speech-only", "--action"}
```

with:

```python
    assert current - old == {"--story-only", "--story-legacy", "--no-auto-lora", "--judge", "--goal", "--gemma",
                             "--no-narration", "--speech-only", "--action", "--location",
                             "--location-strength"}
```

**3.4.** Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
    assert set(supported) == {k for k, _flags in lib.FIELD_FLAGS} and len(supported) == 28
```

with:

```python
    assert set(supported) == {k for k, _flags in lib.FIELD_FLAGS} and len(supported) == 30
```

**3.5.** Edit `tests/test_movie_ui_http.py`: replace this text, which occurs exactly once:

```python
    assert len(srv.ROUTES) == 40
```

with:

```python
    assert len(srv.ROUTES) == 46
```

**3.6.** Edit `tests/test_movie_ui_http.py`: replace this text, which occurs exactly once:

```python
    assert all(payload["supported"].values()) and len(payload["supported"]) == 28
```

with:

```python
    assert all(payload["supported"].values()) and len(payload["supported"]) == 30
```

**3.7.** Edit `tests/test_soft_panel_count.py`: replace this text, which occurs exactly once:

```python
    assert se.StoryContext._fields[-2:] == ("panels_target", "length")
    assert se.StoryContext._field_defaults == {"narration": True, "clip_seconds": None,
                                               "panels_target": None, "length": None}
```

with:

```python
    assert se.StoryContext._fields[-3:] == ("panels_target", "length", "locations")
    assert se.StoryContext._field_defaults == {"narration": True, "clip_seconds": None,
                                               "panels_target": None, "length": None,
                                               "locations": ()}
```

**3.8.** Edit `tests/test_movie_ui_builder.py` (`test_mut26`'s comment): replace this text, which occurs exactly once:

```python
then to ff757afbc0a801f2029628871c684ce4d98b4811 (soft panel count).
```

with:

```python
then to ff757afbc0a801f2029628871c684ce4d98b4811 (soft panel count), then to SHA (location library).
```

**3.9.** Edit `tests/test_movie_ui_builder.py` (`test_mut26`'s baseline): replace this text, which occurs exactly once:

```python
    BASELINE = "ff757afbc0a801f2029628871c684ce4d98b4811"
```

with:

```python
    BASELINE = "SHA"
```

**3.10.** Run this check:

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
SHA=$(git log -1 --format=%H -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py)
grep -c "$SHA" tests/test_movie_ui_builder.py
grep -c "(soft panel count), then to $SHA (location library)." tests/test_movie_ui_builder.py
grep -c "    BASELINE = \"$SHA\"" tests/test_movie_ui_builder.py
diff <(COLUMNS=80 python3 -B bin/ltx-movie --help | awk '/^  --location NAME/,/^  --action/' | sed '$d') <(awk '/^  --location NAME/,/^  --action/' tests/fixtures/movie_ui/ltx-movie-help-current.txt | sed '$d') && echo "fixture lines match the real help"
git diff --numstat -- tests/
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py tests/test_movie_ui_http.py tests/test_soft_panel_count.py -k "mut3 or mut18 or mut26 or mu14 or spt1a" 2>&1 | tail -1
```

Expected, in order: `2`, `1`, `1`, `fixture lines match the real help`, then four numstat lines (`11	0	qwen-agent-workspace/tests/fixtures/movie_ui/ltx-movie-help-current.txt`, `6	5	qwen-agent-workspace/tests/test_movie_ui_builder.py`, `2	2	qwen-agent-workspace/tests/test_movie_ui_http.py`, `3	2	qwen-agent-workspace/tests/test_soft_panel_count.py`), then `6 passed` (`test_mut3`, the two `test_mut18` tests, `test_mut26`, `test_mu14` and `test_spt1a`) with the deselected count. If a value differs, fix the Edit, not this command.

- [ ] **Step 4: Commit (test-only; spec 6.9, G15).**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
git add tests/test_movie_ui_http.py tests/test_movie_ui_builder.py tests/fixtures/movie_ui/ltx-movie-help-current.txt tests/test_soft_panel_count.py
git diff --cached --name-only    # expected: only those 4 paths
git commit -m "test: re-baseline mut18 (46 routes), mut3 and mu14 (the --location flags; 30 FIELD_FLAGS), spt1a (StoryContext.locations) and mut26 to the location library pipeline commit (spec 6.9, G15; plan ruling LR29)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: LK1, LK2: the full suite against the baseline (about 16 minutes).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/loc-baseline
cd $S/loc-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/final-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt; tail -1 $D/final-pytest.txt
diff <(grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt | sort) <(grep -E '^(FAILED|ERROR)' $D/final-pytest.txt | sort) && echo "same failures, same messages"
diff <(grep -E '^PASSED' $D/baseline-pytest.txt | sort) <(grep -E '^PASSED' $D/final-pytest.txt | sort) | grep '^<' || echo "no lost pass"
grep -cE '^PASSED tests/(test_location_|test_lora_check_fixes)' $D/final-pytest.txt
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1
```

Expected:
- the final summary `2 failed, 2106 passed, 2 skipped`: the baseline's `2 failed, 1987 passed, 2 skipped` plus the 119 new test cases;
- `same failures, same messages` (LK1), `no lost pass`, `119` and `OK 347/347` (LK2).

If `test_trt41a` failed in one run only, rerun it alone and record both results. Any other difference: stop and report.

- [ ] **Step 6: LK3-LK10: the remaining KPIs.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/loc-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_lib.py -k ll1 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_golden.py::test_lg1_the_character_golden_record_is_unchanged tests/test_location_golden.py::test_lg3_the_character_tests_pass_unedited tests/test_location_story.py::test_ls1_without_locations_plan_prompts_and_plans_are_byte_identical 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_pipeline.py -k "lp14 or lp19 or lp5 or lp7 or lp8" 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_dataset.py -k "ld5 or ld9" 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider tests/test_location_story.py -k "ls6 or ls7 or ls8 or ls9" 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider tests/test_lora_check_fixes.py 2>&1 | tail -1
git diff d210c26 -- story_engine.py | grep -E '^[+-]\s*(import|from) ' || echo "story_engine: no import change"
git diff d210c26 -- bin/ltx-movie bin/ltx-story-images bin/ltx-mlx-render bin/iterate-story bin/lora-check bin/lora-catalog movie_ui_lib.py movie_ui_server.py | grep -E '^\+(import|from) ' || echo "pipeline tools: no top-level import added"
grep -nE "127\.0\.0\.1:81|localhost|expanduser\(|urlopen|http\.client|import requests" tests/test_location_*.py tests/test_lora_check_fixes.py tests/location_testutil.py || echo "no server port, real HOME or HTTP client in the new tests"
```

Expected, in order:
- LK3: `2 passed`;
- LK4, LK5: `3 passed`;
- LK5, LK7: `6 passed`;
- LK6: `5 passed`;
- LK8: `6 passed`;
- LK9: `8 passed`;
- `story_engine: no import change` and `pipeline tools: no top-level import added`;
- LK10: `no server port, real HOME or HTTP client in the new tests`. The movie-UI tests reach their in-test `127.0.0.1` server through `movie_ui_testutil.api`.

- [ ] **Step 7: Hand-off (controller; not an executor step).**
  - Report the branch `loc-impl` and its 14 commits (13 task commits and the re-baseline), with LK1-LK10.
  - Push and the merge into `qwen-agent-redteam` are a separate step that needs the user's approval.
  - Put the spec 8 PR note in the PR description.
  - The live checks below run after the merge.

---

## Post-merge: live checks (coordinator only; spec 8 step 7; not a task and not a merge gate)

The coordinator runs these after the merge, never an implementer:
- They start the vision and story servers, which load models on `:8177`, and they generate and train. Every run needs the user's go-ahead.
- This Mac only, never macstudio. Never touch `:8178`. Never read `~/.zshenv` or `fleet.env`.

Steps:
- [ ] `bin/location create harbour-street --description "<24 words>"`, then review `generated/locations/harbour-street/contact_sheet.jpg`.
- [ ] `bin/location train harbour-street`.
- [ ] `bin/ltx-movie "<narrative at a harbour and a temple>" --panels 3 --story-id loc-live-1 --location harbour-street --story-only --no-review`. Record whether `plan.json` sets `l1` in a beat, and the P21 retries in `story_rounds/round_0`.
- [ ] Optionally render, and compare the panels at the location with a run without `--location`.

---

## Coverage

### Spec coverage: requirement → task

| Requirement | Task (step) |
|---|---|
| L1.1 layout | 2 (names, `library_dir`), 4 (the directories `create` makes) |
| L1.2 CLI | 4 (`create`, `edit`, `list`, `show`, exit codes, signals, re-exec), 5 (`train`) |
| L1.3 description rule | 2 (`normalize_description`, `validate_description`) |
| L1.4 trigger | 2 (`TRIGGER_RE`, registry, `all_triggers`, `auto_trigger`), 4 (the create checks) |
| L1.5 text mode | 4 (`VARIANTS`, `gen_prompt`, the Z-Image child) |
| L1.6 photo mode | 4 (`_load_photos`, copies, fit, top-up, server dance) |
| L1.7 VLM describe | 4 (`describe`) |
| L1.8 edit child | 3 (`child_qwenedit`), 4 (the location edit spec, the model gate) |
| L1.9 check, keep, caption | 4 (`check_still`, `validate_location_check`, `_check_entry`, `caption`) |
| L1.10 manifest | 4 |
| L1.11 contact sheet | 4 (`write_contact_sheet`, `cell_label`) |
| L1.12 create/regenerate/edit order | 4 |
| L2.1 train CLI, wrapper | 5 |
| L2.2 train preflights | 5 |
| L2.3 video LoRA | 3 (`train_video_lora`), 5 (`_train_video`) |
| L2.4 stills LoRA | 3 (`train_stills_lora`), 5 (`_train_stills`) |
| L2.5 audio stripping | 9 (`use_video_only_character_loras`) |
| L2.6 `location.json` | 2 (schema), 4 (create writes it), 5 (train records) |
| L2.7 validation | 2 |
| L2.8 base model, compatibility | 2 (`model_compatible`), 10 (the mismatch warning) |
| L2.9 resolution | 2 |
| L2.10 character refactor | 3 |
| L3.1 ltx-movie flags, resolution | 10 |
| L3.2 story pins | 2 (`plan_location_names`), 6 (`location_name`), 10 (`_check_story_locations`) |
| L3.3 plan prompt | 6 |
| L3.4 plan normalisation | 6 |
| L3.5 P21 | 6 (the check, the fatal filter), 10 (LS7 end to end) |
| L3.6 L4 count | 6 |
| L3.7 manifest attach | 2 (`plan_panel_locations`, `prefix_location_trigger`), 7 |
| L3.8 stills attach | 8 (`bin/ltx-story-images`), 10 (`_location_flags`, shots groups, dry run) |
| L3.9 render | 9 |
| L3.10 Phase 1 warnings | 10 (no code; `_phase1_robust` unchanged) |
| L3.11 iterate-story | 10 |
| L4.1 routes and jobs | 11 |
| L4.2 handlers | 11 |
| L4.3 Compose | 11 (fields, flags, `build_argv`, rule 12c), 12 (the page fields) |
| L4.4 page | 12 |
| L4.5 LoRAs & Models tab | 11 (`no_arch_check`, `parse_verify`), 12 (the checkbox, the Verify column) |
| L4.6 tool stubs and help fixture | 11 (`movie_ui_testutil`), 14 (the help fixture) |
| L4.7 lora-check bare tables | 13 |
| L4.8 low-RAM warning | 13 |
| L5.1 error table | 4 (create, regenerate, edit rows), 5 (train rows), 7 (manifest rows, Review Focus 3), 8, 9, 10 (ltx-movie rows), 11 (UI rows) |
| 6.2 test rules, helpers | 2 (`set_story_env`, `LINKED_FILES`, `location_testutil`), every test file's docstring |
| 6.3 fixtures | 1 |
| 6.9 existing tests | 2, 11 (infrastructure), 14 (the re-baseline commit, with LR29's two additions) |
| 8 rollout | Before Task 1 (snapshot, baseline), 1 (fixtures), 2-13 (feature commits), 14 (review, G15, LK1-LK10, hand-off), Post-merge (live checks) |
| G1-G15 | G1 2; G2 4, 5; G3 4, 5; G4 3; G5 6; G6 10; G7 7; G8 8; G9 9; G10 10; G11 11, 12; G12 13; G13 1-13; G14 2, 11, 14; G15 14 |

### KPI → task

| KPI | Measured by |
|---|---|
| LK1 | Before Task 1 Step 4 (baseline); every Step 4 gate; Task 14 Step 5 |
| LK2 | every Step 4 gate; Task 10 Step 4; Task 14 Step 5 |
| LK3 | Task 13 (LL1); every task's compile check; Task 14 Step 6 |
| LK4 | Task 1 (LG1 captured), Task 3 (LG1-LG3 after the refactor), Task 14 Step 6 |
| LK5 | Task 1 (LS1), Task 6 (LS1 after the engine change), Task 9 (LP14, LP19), Task 14 Step 6 |
| LK6 | Task 4 (LD5, LD9), Task 14 Step 6 |
| LK7 | Task 7 (LP5-LP8), Task 14 Step 6 |
| LK8 | Task 6 (LS6, LS8, LS9), Task 10 (LS7), Task 14 Step 6 |
| LK9 | Task 13 (LC1-LC8, and LR1's LC9), Task 14 Step 6 |
| LK10 | every new test file's docstring and fakes; Task 14 Step 1 (review) and Step 6 (the grep) |

### Test IDs and their owning task (each is owned by exactly one task)

| IDs | Task | File |
|---|---|---|
| LG1 | 1 | `tests/test_location_golden.py` |
| LS1 | 1 | `tests/test_location_story.py` |
| LL2-LL14 | 2 | `tests/test_location_lib.py` |
| LG2, LG3, LD18 | 3 | `tests/test_location_golden.py`, `tests/test_location_dataset.py` |
| LD1-LD17, LD24, LT1-LT8, Review Focus 1, 2 | 4 | `tests/test_location_dataset.py`, `tests/test_location_tool.py` |
| LD19-LD23, LT1b (the `train` help part of LT1), LT9, LT10 | 5 | the same two files |
| LS2-LS6, LS8-LS14 | 6 | `tests/test_location_story.py` |
| LP5-LP9, Review Focus 3, 4 | 7 | `tests/test_location_pipeline.py` |
| LP10-LP12 | 8 | `tests/test_location_pipeline.py` |
| LP14-LP19 | 9 | `tests/test_location_pipeline.py` |
| LP1-LP4, LP13, LP20, LS7 | 10 | `tests/test_location_pipeline.py`, `tests/test_location_story.py` |
| LU1-LU12, LU14, Review Focus 5 | 11 | `tests/test_location_ui.py` |
| LU13 | 12 | `tests/test_location_ui.py` |
| LC1-LC8, LC9 (Plan ruling LR1), LL1 | 13 | `tests/test_lora_check_fixes.py`, `tests/test_location_lib.py` |
| `test_mut18`, `test_mut3`, `test_mut26` re-baselines, and LR29's `test_mu14`, `test_spt1a` | 14 | the spec 6.9 files, `tests/test_soft_panel_count.py` |

Totals: 112 test functions, 119 cases with the parametrizations (LD9 has 4 cases, LS6 3, LP5/LP6 2, LL1 2). Cumulative new-file cases after each task: 2, 15, 18, 49, 57, 71, 78, 81, 87, 94, 108, 109, 119.

### Self-review

- **Spec coverage.** Every requirement L1.1-L5.1 and every KPI LK1-LK10 maps to a task in the tables above. Every test group (LL, LD, LT, LG, LS, LP, LU, LC) has real test code in its task's Step 1. G1-G15 each have a step.
- **Placeholders.**
  - The only symbolic values are `$S`, `$WS`, `$D` and `N` (the gate block), each defined in its block or in the house rules.
  - The word `SHA` in Task 14 Step 3 is the value Step 2 prints.
  - No step says "add error handling", "TBD" or "similar to Task N". Every Edit names its old text, which occurs exactly once at its turn (checked by replay).
- **Type and name consistency.** The names below appear with the same signature in every task that uses them:
  - `LocationPin` (9 fields, `attach_video` last).
  - `resolve_locations(names) -> [LocationPin]`.
  - `plan_panel_locations(story_dir, n_panels, names) -> (list, note)`.
  - `plan_location_names(story_dir) -> set or None`.
  - `prefix_location_trigger(prompt, trigger)`.
  - `model_compatible(base_model, model)`.
  - `train_video_lora(owner_dir, videos_dir, captions_dir, prompt, failed_note, recorded, tested)`.
  - `train_stills_lora(owner_dir, pairs, prompt, seed, kept_ok, skipped)`.
  - `_location_flags(args, video=False)`.
  - `_shots_stills_groups(story_md_path, members, locations=())`.
  - `location_argv(kind, fields, ws_real, state, py=sys.executable)`.
  - `low_ram_skipped(header) -> (outside, total)` and `low_ram_warning(header)`.

  The manifest entry is `{"name", "video_lora", "strength"}` in Tasks 7, 9 and the tests. The stills entry is `{"kind": "location", "name", "path", "strength"}` in Task 8 and the tests. The test helpers `lt.harbour`/`lt.temple`/`lt.mill` and `lt.write_plan` have one signature everywhere.
- **Review Focus.** Five inputs, each with a pinning test in its owning task (Tasks 4, 4, 7, 7 and 11).

## Plan rulings (where the spec's text and its own tests, or the existing tests it keeps unedited, cannot both hold, or the spec needs a reading)

**[defect]** rulings change behaviour from what the spec literally writes. The controller should confirm LR1, LR2, LR7 and LR29 with the user before Tasks 4, 6, 11 and 13 start. **[reading]** rulings fill a detail the spec leaves open.

1. **LR1 [defect]: the low-RAM warning is for a LoRA the low-RAM path skips in part.** `low_ram_warning(header)` returns the text only when `0 < outside < total`.
   - Spec L4.8 warns whenever `outside > 0`. The repository's synthetic test LoRA (`story_engine_testutil.fake_safetensors`) has one module, `blocks.0.attn.to_q`, which is outside `transformer_blocks.`.
   - With the literal rule, `bin/lora-catalog add` would print a `warning:` line in `test_lct7_add_happy_path` (`result.stderr == ARCH_UNVERIFIED`). `verify` would print `WARN` lines in `test_lct11_verify` (`tests/test_lora_catalog.py:401-437`, exact stdout). Spec 6.9 keeps those tests unedited.
   - What it costs: a LoRA with no module under `transformer_blocks.` has no LTX block module at all, so the low-RAM path skips it entirely. That is a foreign or misnamed LoRA. It gets no warning, and the existing arch gate is what reports it. LK9's `44 of 1724` case and LC8 are unchanged.
   - Tested by LC9 and by the unedited `tests/test_lora_catalog.py`.
   - Spec amendment (L4.8): "`outside` = modules whose name does not start with `"transformer_blocks."`; the warning is given when `0 < outside < total`".
2. **LR2 [defect]: `parse_verify` adds `"warnings"` only to an entry a `WARN` line names.**
   - Spec L4.5 says every result gets `"warnings": []`. `tests/test_movie_ui_http.py:624` asserts the exact result dicts `{"id", "ok", "problems"}`.
   - The page's Verify expression (`r.warnings && r.warnings.length ? ...`) already handles an absent key.
   - `bin/lora-check`'s JSON results do get `"warnings": []` always, as the spec says (no existing test compares them exactly).
   - Tested by LU12 and the unedited `test_movie_ui_http.py`.
3. **LR3 [defect in a test row]: LS10 needs four other LoRAs.** L4 fires above `LORA_PANEL_LIMIT = 4` (`story_engine.py:2387`). "A beat at an attachable pin with 3 other LoRAs" has 4 LoRAs, which is not above the limit.
   - LS10 uses a pinned global LoRA, a global style pick, a per-beat motion pick, the location and a cast character: 5 LoRAs.
   - With `attach_video=False` the same beat has 4, and no L4.
4. **LR4 [reading]: the reused-story check (L3.2) also runs without `--location`.**
   - L3.1's step 1 returns early without `--location`, but L3.2 requires an exit 2 "in either direction, including a story with pinned locations and no `--location`".
   - So `_resolve_locations` calls `_check_story_locations` in both branches. It loads `location_lib` by path to read `plan.json` only when `story.md` exists and `--force-story` is not given.
   - A story planned without pins gives the empty set, so a run without `--location` prints and changes nothing (LK5).
   - Spec 1.2's "only when `--location` is given" is read as applying to attaching LoRAs, not to this read.
5. **LR5 [reading]: the exit code of an interrupt** (L5.1 "1 (130 from a signal)").
   - An interrupt inside the dataset build prints the abort line, restores the server detached, and exits 1. This is `build_dataset`'s `except (KeyboardInterrupt, EOFError)`, as in `bin/character`.
   - An interrupt anywhere else (preflights, describe, training) reaches `run()`, which prints `location: interrupted` and exits 130.
   - `bin/location` raises KeyboardInterrupt for SIGINT, SIGTERM and SIGHUP alike, as `bin/character` does, so the two cannot be told apart otherwise. LT8 signals during a preflight; LD17 interrupts the image child.
6. **LR6 [reading]: `bin/location`'s entry is a `run(argv=None)` function.** The `__main__` block calls `sys.exit(run())`.
   - `run()` has exactly `bin/character:135-152`'s body: the three handlers, `location: interrupted`, 130.
   - LT8 then drives the real signal path in a subprocess, with fakes installed by a driver script.
7. **LR7 [defect]: a new description that contains the trigger word is refused before the lock.**
   - `edit`, and a text location's `--regenerate --description`, run `validate_trigger(trigger, description)`. The refusal is `--description: trigger T must not be a word of the description`, exit 2.
   - Without the check, `write_location` raises inside the lock. With `--force` on a trained location, that is after `lora/`, `tests/` and `train/` are deleted.
   - Tested by Review Focus 1.
8. **LR8 [reading]: trigger ownership names the library.** `all_triggers()` maps each trigger to `location NAME` or `character NAME`, and the create refusal is `trigger T is already used by location NAME; ...` or `... by character NAME; ...` (L5.1's `NAME`, with the kind added). A location trigger wins a conflict.
9. **LR9 [reading]: the regenerate refusal for `--photo`/`--trigger`.** L1.12 says only "refused". The text is `--regenerate takes no --photo or --trigger: a location keeps the photos and the trigger it was created with`, exit 2, checked after `load_location`.
10. **LR10 [reading]: a regenerate prints `seed: A -> B` or `seed: A (unchanged)`**, as `character_dataset.create` does, after persisting under the lock.
11. **LR11 [reading]: `describe` normalises a reply before its checks.** The 40-word shorten test and `validate_description` both run on `normalize_description(text)`. A non-string `"description"` is a rejection that is quoted in the retry.
12. **LR12 [reading]: UI messages the spec leaves open.** These are:
    - `photo_uploads must be a list of upload IDs`;
    - `description must be a string`;
    - `description contains invalid characters`;
    - `description must not start with '-'`;
    - `description must be one line`;
    - `new_seed must be true or false`.

    The spec's own texts are kept verbatim. A regenerate body with `seed` and `new_seed: true` is a 400 `invalid fields` with `errors: ["give seed or new_seed, not both"]`, like the other field errors.
13. **LR13 [reading]: render message formats.** `panel N: location NAME's video_lora is not a readable file: PATH` prints the value with `%s`, as the spec writes it. The strength message prints it with `%r`, as the character message does.
14. **LR14 [defect in a test row]: LT2 runs under `-I` with a meta-path blocker.** `-I` ignores `PYTHONPATH`, so the spec's "temp `PYTHONPATH` shim" cannot hide PIL from an isolated interpreter.
    - The `-I` child installs a `sys.meta_path` finder that refuses `PIL`, `psutil`, `character_dataset`, `location_dataset` and `character_lib`, then runs `main(["list"])` and `main(["show", NAME])`.
    - LT7 (the re-exec) uses the `PYTHONPATH` shim, without `-I`.
15. **LR15 [reading]: the manifest's unused-pin `WARNING` needs a usable plan.** Without one, the note alone says why no pin attaches.
16. **LR16 [reading]: one commit per task.** That is 13 task commits, then Task 14's test-only re-baseline, instead of spec 8 step 3's single feature commit, as in the prior plans. `test_mut26`'s `BASELINE` is the last commit that touches a `PIPELINE_FILES` entry.
17. **LR17 [reading]: the re-baseline is one test-only commit after the review.** It holds `test_mut18`, `test_mut3` with its help fixture, and `test_mut26`, as the controller asked. Spec 6.9 lists `test_mut26` as the separate follow-up; the other two join it.
18. **LR18 [reading]: the help fixture gains the two option entries only.** They are exactly as `bin/ltx-movie --help` prints them at 80 columns (Task 14 Step 3.8 diffs them). The fixture's usage block already differs from the real help and is left as it is; `parse_help_flags` reads option lines only.
19. **LR19 [reading]: `location_lib._character_lib()` reuses the loaded module.** It reuses `sys.modules["character_lib"]` when that module came from the same file, as `bin/lora-check`'s `_load` does. A by-path load never re-executes, and so never resets, a caller's `character_lib`.
20. **LR20 [reading]: LP17 observes the merged route through the dry run.** On the merged route the global LoRA is a unit LoRA (`lora: PATH @ 1.0 (global)`); on the legacy route it is not.
21. **LR21 [reading]: a manifest item with `people_visible: null`** (a blocked or unparseable still) shows `people -` on its card, as the missing score shows `score -`.
22. **LR22 [reading]: `bin/location-train-vlm`'s header comment names the location training.** Its body is the name-replaced `bin/character-train-vlm`, which LT9 pins line by line. `bin/action-train-vlm` set the precedent of a rewritten header.
23. **LR23 [reading]: the `d210c26` comparisons use `git show d210c26:./FILE`.** These are LS14, LP14, LP19, LC1 and LC3, and they skip outside a git checkout that has `d210c26`; the worktree has it.
24. **LR24 [reading]: the golden record holds no host path.** Besides `<TMP>` and `<STAMP>`, it replaces `SKILL.LTX2_MLX_HF_HOME`, `SKILL.LTX2_MLX_DIR` and `character_dataset.MFLUX_HF_HOME`, longest first, with `<LTX2_MLX_HF_HOME>`, `<LTX2_MLX_DIR>` and `<MFLUX_HF_HOME>`. Each case runs in its own directory under one temporary root, so a case never sees another's files.
25. **LR25 [reading]: test placement.** LL1 is in Task 13, where the last file it compiles changes. LS7 is in Task 10, where `--location` exists. LD18 opens `tests/test_location_dataset.py` in Task 3, and Task 4 adds the `location_dataset` loader to its header.
26. **LR26 [reading]: LT10 fakes the cores.** `train_video_lora` is replaced by a fake that calls `recorded` like the real core, so `_train_video`'s report sees an entry.
27. **LR27 [reading]: `bin/iterate-story` is folded into Task 10.** Its change is four lines with one test.
28. **LR28 [reading]: the page collapses whitespace** in a description before POST and PATCH. A textarea's line breaks would otherwise fail the server's `description must be one line`, which still refuses a raw newline.

29. **LR29 [defect]: two more existing tests change, in Task 14's test-only commit.** Spec 6.9's list is incomplete. The plan's full-suite replay after Task 13 found two tests that pin exactly what the spec changes:
    - `tests/test_movie_ui_http.py::test_mu14_ws_parameter_errors_and_options` asserts `len(payload["supported"]) == 28` (L4.3 makes 30). It also asserts `all(supported.values())`, which holds again once the help fixture lists `--location` (Task 14).
    - `tests/test_soft_panel_count.py::test_spt1a_engine_constants` asserts `StoryContext._fields[-2:] == ("panels_target", "length")` and the four defaults. L3.3 makes `locations` the last field, with the default `()`.

    Both edits keep each assertion's intent: the count becomes 30; the field check becomes the last three fields and five defaults. No implementation choice avoids them: the spec fixes the count, and fixes `locations` as the last field.
30. **LR30 [reading]: `bin/ltx-movie` loads `location_lib.py` from its own workspace.** The path is `os.path.dirname(os.path.dirname(os.path.realpath(__file__)))`, which equals `WS` outside tests.
    - Why: `tests/test_shots_mode.py::test_s51_dry_run_existing_story_with_redo` points `ltx_movie.WS` at a partial workspace (its `movie_ws` fixture links `bin/`, `character_lib.py`, `story_engine.py` and `lora_catalog.py` only) and dry-runs an existing story. LR4's reused-story check would then fail with `FileNotFoundError`.
    - `bin/ltx-story-manifest` and `bin/ltx-story-images` keep loading from `WS`; their tests link it, and they read it only with `--location`.

## Questions for controller

1. **Q1 (LR1).** Keep the warning to partly-skipped LoRAs, or apply the spec's `outside > 0` rule? Applying it means re-baselining `test_lct7_add_happy_path` and the `tests/test_lora_catalog.py` verify cases in Task 14's test-only commit. Spec 6.9 would then need to list them.
2. **Q2 (LR4).** Confirm that a run without `--location` on a story whose `plan.json` pins locations exits 2. Spec L3.2 says so; L3.1's step 1 reads as if it returns first.
3. **Q3 (LR5).** Confirm the exit codes: 1 after the abort line inside the build, and 130 elsewhere.
4. **Q4 (LR7).** Confirm the extra refusal: a new description that names the trigger is refused at `edit` and at a text `--regenerate --description`.
5. **Q5 (LR29).** Confirm that `test_mu14` and `test_spt1a` join the test-only re-baseline commit with the three spec 6.9 tests.

## Spec defects found (for the spec author)

1. L4.8's `outside > 0` warning breaks `tests/test_lora_catalog.py`'s exact-output add and verify cases (LR1).
2. L4.5's "every result gets `"warnings": []`" breaks `tests/test_movie_ui_http.py:624` (LR2).
3. LS10's "3 other LoRAs" do not reach L4's limit (LR3).
4. L3.1 step 1's early return contradicts L3.2's "including a story with pinned locations and no `--location`" (LR4).
5. L5.1's "1 (130 from a signal)" cannot be implemented as two codes for one KeyboardInterrupt (LR5).
6. A new description that contains the trigger is not handled: `validate_location` would raise inside the lock (LR7).
7. L1.12 gives no text for the regenerate `--photo`/`--trigger` refusal (LR9).
8. LT2's "`-I` ... via a temp `PYTHONPATH` shim": `-I` ignores `PYTHONPATH` (LR14).
9. Spec 6.9 misses `test_mu14_ws_parameter_errors_and_options` (the 28 `FIELD_FLAGS`) and `test_spt1a_engine_constants` (`StoryContext`'s last fields), which the spec's own changes break (LR29).
10. Spec 1.2's "load it the way they load `character_lib`" (from `WS`) meets a test workspace without `location_lib.py` once L3.2 runs without `--location` (LR4, LR30).

## Execution handoff

Plan complete and saved to `qwen-agent-workspace/docs/superpowers/plans/2026-10-29-location-lora.md`.

**How it was checked.** Every Create, Edit and generating command of Tasks 1-14 lives in one data file per task, and this plan's code blocks are rendered from those files. A script replayed them in order on a scratch git checkout of `d210c26` (a clone, never the main checkout), the way an executor applies them: an exactly-once check on every old text, and files created with their exact bytes.
- **Edits.** Each old text occurred exactly once at its turn. The Files sections' line ranges are the old texts' positions in the `d210c26` files.
- **Fixtures.** Task 1's commands wrote the five fixtures at `d210c26`. A second `--write-fixture` gave the same sha256, and LG1 passed again after Task 3's refactor (LK4).
- **Fail first, then pass.** After each task's Step 1 alone, and after the whole task, the task's test files gave the Step 2 and Step 4 summaries quoted in each task. The cumulative new-file counts were 2, 15, 18, 49, 57, 71, 78, 81, 87, 94, 108, 109 and 119.
- **The full suite** was run three times.
  - At `d210c26`: `2 failed, 1987 passed, 2 skipped`, `OK 347/347`.
  - After Task 13 (first draft): it lost the three spec 6.9 tests. It also lost `test_mu14` and `test_spt1a`, which spec 6.9 misses (Plan ruling LR29), and `test_s51_dry_run_existing_story_with_redo`, a defect of the draft. The five tests became the expected-failure list in "Between tasks", and Plan ruling LR30 fixed `test_s51`.
  - After Task 14, with a placeholder `test_mut26` SHA: `2 failed, 2105 passed, 3 skipped`, the two failures being exactly the baseline's, with the same messages, and `OK 347/347`. The only baseline pass not passing was `test_mut26`, which skipped because the placeholder commit does not exist. In the worktree it passes, which gives Task 14 Step 5's `2 failed, 2106 passed, 2 skipped`.
- **Task 14.** The re-baseline made `test_mut3`, both `test_mut18` tests, `test_mu14` and `test_spt1a` pass, and the fixture lines matched the real `--help`. The real `test_mut26` needs the worktree's commits and is checked by Task 14 Step 3.10.
- **Compile.** Every new and changed file compiled under Python 3.9.6 and 3.13 (LL1), `bash -n bin/location-train-vlm` passed, and `node --check static/movie-ui/app.js` passed.
- **Not run.** No server other than the in-test movie-UI servers, no model and no network. Everything was written under `$S/locplan/`.

Please review the plan. Which execution approach would you prefer?
- **Subagent-driven.** A fresh Sonnet `code-executor` implements each task in `$S/loc-wt` on branch `loc-impl`, and a fresh Opus reviewer checks it before the next one starts. A whole-branch review follows at the end (Task 14 Step 1).
- **Native.** One session implements every task, then one fresh Opus reviewer checks the whole branch.

I recommend subagent-driven. Tasks 4-13 each consume names and data shapes from the tasks before them (`LocationPin`, the cores' callbacks, `plan_panel_locations`, the manifest entry, `_location_flags`). Five rulings change spec behaviour or its test list (LR1, LR2, LR4, LR7, LR29) and should be confirmed before their tasks. A mistake in Tasks 7-9 would silently attach a location LoRA to the wrong panels.
