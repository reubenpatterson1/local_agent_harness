# Seed-Folder Compose Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One job per image of a picked folder, in two places.
- **Compose.** The Resolution fieldset gains a third choice, "Seed folder". Every PNG, JPEG or WebP image directly in the folder is uploaded and becomes its own ordinary story or movie job, sharing the Compose narrative and settings. Each job's story ID is made from its file name; the Story ID field becomes an optional prefix.
- **Characters.** The New character form gains a "Seed folder (one character per image)" checkbox. Every image becomes one `character-create` job, named from its file name, sharing the form's referring phrase and seed; the Name field becomes an optional prefix.
- In both, a confirm table shows every seed with its ID or name and OK or the reason it is refused, and Queue submits only the OK seeds, in file-name order, each tagged "seed folder" on the Jobs page.

**Architecture:**
- **`movie_ui_seedfolder.py` (Task 1, new, pure).** The constants; the shared candidate loop `first_free`; the story-ID rules (`seed_stem`, `valid_prefix`, `story_id_for`, `assign_story_ids`) and `taken_names`; the character-name rules (`character_stem`, `valid_character_prefix`, `character_name_for`, `assign_character_names`) and `character_taken_names`; the request checks (`_seeds_and_preview`, `validate_request`, `validate_character_request`); `row_reason`, `new_run_id` and `seed_tag`. It never writes and never starts a process.
- **`movie_ui_lib.py` (Task 2).** `shared_checks` (V2-V5) is split out of `run_checks`, which returns the same records in the same order.
- **`movie_ui_server.py` (Tasks 3, 4).**
  - Task 3, Compose: `POST /api/jobs/seed-folder` and `_h_seed_folder`; `seed_taken`, `seed_rows` (steps 1-4 with no lock), `_dry_runs` (4 plain threads) and `_seed_response`; `_compose_job_locked`, split out of `create_compose_job` so one `STORE_LOCK` hold can create many jobs; the `seed_folder` key of `job_summary`.
  - Task 4, Characters: `POST /api/characters/seed-folder` and `_h_character_seed_folder`; `character_taken`, `_character_rows` and `_character_response`; `_character_job_locked`, split out of `create_character_job`; `_phrase_errors` and `_seed_number_errors`, moved out of `character_create_errors` unchanged.
- **The page (Tasks 5, 6).** Task 5: `FOLDER_BOXES` and `part`, one box-parameterised copy of the folder functions (pick, upload loop, list, confirm table, Queue, Cancel), the Compose Seed folder radio, list and confirm table, and the Jobs tag. Task 6: the Characters checkbox, list and confirm table, wired to the same functions. `app.css` is unchanged.
- **Task 7** is the one test-only re-baseline commit of spec 6.1.
- **Verification** (controller, not an implementer task): the pass bar (spec 7), the browser check (spec 6.2), the Opus design review and the live checks (spec 6.3).
- **Tests:** one new file, `tests/test_movie_ui_seedfolder.py`: SDT1-SDT37 and five Review Focus pins, 78 test cases in all.

**Tech Stack:**
- Python 3.13 (`python3` = `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`, pytest 8.3.4). Python 3.9.6 (`/usr/bin/python3`) is used for the compile check only. Every new and changed Python file runs on both.
- `movie_ui_seedfolder.py`, `movie_ui_lib.py` and `movie_ui_server.py` stay standard library only. The page is vanilla ES2017 with no modules.
- Test helpers: `tests/movie_ui_testutil.py` (`set_home`, `make_stub_workspace`, `Running`, `api`, `make_job`, `fields`, `stub_config`, `stub_calls`, `kill_everything`, `PNG`). `node --check` checks `app.js` when `node` is installed (this Mac has `/opt/homebrew/bin/node`).

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-11-01-seed-folder-compose-design.md`, as amended at `a9d5aa1` on `seed-folder` (the Characters addendum; first committed at `604a221`).
- Its code citations are at `e94ebb0`. `604a221` and `a9d5aa1` change only the spec, so every line number below (cited "at a9d5aa1") is also `e94ebb0`'s.
- The user approved the design and the Characters addendum (spec Status). The spec is binding. Requirements SD1-SD50, tests SDT1-SDT37.
- This plan changes behaviour only where the spec cannot work as written. Each such case is a numbered ruling in "Plan rulings", marked **[defect]**. The other rulings fill a detail the spec leaves open and are marked **[reading]**.

## Global Constraints

From the spec, verbatim (section in brackets):

- [Status] "The implementer makes no design decisions."
- [0.2] "Untouched: every pipeline file (`bin/ltx-movie`, `bin/character`, `character_lib.py`, `character_dataset.py` and the rest of `PIPELINE_FILES`), `movie_ui_batch.py`, the behaviour of `/api/preview`, `/api/validate`, `/api/jobs` and `/api/characters`, and the Batches page. `test_mut26` passes unedited."
- [0.3 Out of scope] "The seed generator tab (prompt + seed → edited seed, Z-Image img2img or Qwen-Image-Edit). It is a separate later spec. A `--seed-dir` CLI flag. Any Batches-page entry or batch record for a run. Subfolders, typed paths, and reading a folder on the server. In Characters folder mode: a per-run `--force`, a shared class noun, descriptor or trigger, and a command preview."
- [0.4] "Every SD requirement and every SDT test is a must-have. There are no nice-to-haves."
- [SD1] "`movie_ui_seedfolder.py` imports only `re`, `secrets`, `time`, `unicodedata` and `movie_ui_lib as lib`. It is Python 3.9-compatible, never writes, and never starts a process."
- [SD4] "Nothing new is stored: no state file, no state subdirectory, no queue type, no job kind. A run's only trace is the `seed_folder` key in each job's fields (SD20)."
- [1.1, 2.4] The constants: `SEEDS_MAX = 100`, `PREFIX_MAX = 40`, `ID_MAX = 80`, `DRY_RUN_WORKERS = 4`, `RUN_ID_RE = re.compile(r"^sf-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")`, `_OUTSIDE = re.compile(r"[^A-Za-z0-9._-]+")`, `CHAR_MAX = 24`, `CHAR_PREFIX_MAX = 12`; `app.js`: `const SEEDS_MAX = 100;`, `const SEED_TYPES = ["image/png", "image/jpeg", "image/webp"];`, `const SEED_COLLATOR = new Intl.Collator("en", {numeric: true});`.
- [SD17] "Neither `STORE_LOCK` nor `BATCH_LOCK` is held" during the dry runs. [SD20] "Steps 1-4 never run under `STORE_LOCK`. The lock covers only the listing, `job_index`, ID assignment and job creation."
- [SD42] "Folder mode never forces." `class_noun`, `descriptor`, `trigger` and `force` "are ignored and forced to `null`, `null`, `null` and `false`".
- [SD35] "Every new identifier passes the `test_mut24` patterns (no `confirm(`, no `on…=`, no `style=`)." [0.1] The page bans `https?://`, `\son[a-z]+=`, `style=`, `\balert\(`, `\bconfirm\(`, `\bprompt\(`, `\beval\(` and `new Function` in `index.html`, `app.js` and `app.css`; the `c-run-all`/`c-check-seams-box` lines that `test_ct27` pins stay unchanged.
- [6 Rules] "The HTTP tests use an `env` fixture like `tests/test_movie_ui_seams.py:41-48`: `mt.set_home`, `mt.make_stub_workspace` and the in-test `mt.Running` server on 127.0.0.1." "`lib.shared_checks` is monkeypatched to `lambda fields, ws_real, py=None: [lib.check("V2", "render", "pass", "stub")]` in every HTTP test except where a test patches it otherwise." "The Characters tests (SDT26-SDT37) use the same file and fixture, `monkeypatch.delenv("CHARACTER_LIBRARY_DIR", raising=False)` unless a test sets it, and the stub `bin/character` (never run, because no test dispatches a job)." "No test uses the real HOME, renders, or contacts a real server. None touches port 8177 or 8178. The VLM lifecycle is off (`conftest.py`). No test ever starts a job."
- [6.1] The only edits to existing tests, in "one test-only commit, after the feature commit": `test_mut18` ("2 new routes (SD11, SD41): `== 55` becomes `== 57`"), `test_lu1` (`== 55` becomes `== 57`), `test_mut2` (the key set gains `"seed_folder"`), `NEW_PY` (gains `"movie_ui_seedfolder.py"` and `"tests/test_movie_ui_seedfolder.py"`), `test_mut25_source_scan_of_new_python_files` (the `allowed` set gains `"movie_ui_seedfolder"`), `copy_ui` (the copied list gains `"movie_ui_seedfolder.py"`). "The new module and test file must contain none of `test_mut25`'s patterns anywhere, docstrings and comments included: no `urllib`, no `X | None` text, and no line that starts with `match ` and ends with `:`."
- [7 Pass bar] "1. Every new test (SDT1-SDT37) passes. 2. `python3 -m pytest tests/ -q -rA` from `WS` has no new failures beyond the 2 known baseline failures: `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`. 3. `python3 tests/test_ltx_movie_offline.py` prints `OK 347/347`. 4. The Compose live check (§6.3) passes. 5. The Characters live check (§6.3) passes when the user gives the go. Without the go it is recorded as not run, and that does not block the merge."
- [8 Rollout] "1. Snapshot `WS` (house rule): `tar czf $S/snapshot-pre-seedfolder-e94ebb0.tgz`, excluding `generated/`. 2. At `e94ebb0`, record the full-suite counts and failure list, and the offline line. 3. Feature commit: G1-G4 plus `tests/test_movie_ui_seedfolder.py`. 4. Test-only commit: §6.1. 5. Run §7 items 1-3 and the browser check (steps 1-12), then an Opus design review of the diff against this spec, then the Compose live check, then the Characters live check if the user gives the go." Step 3's single feature commit is split into one commit per task (Plan ruling PR1).

Controller rules (one line each; every task's requirements include them):

- Tests never use the real HOME, never render, and never contact real servers (an in-test 127.0.0.1 server is OK).
- Never touch :8178 (and never start, stop or contact :8177).
- No new third-party imports in the server (`movie_ui_server.py` gains only `import movie_ui_seedfolder as seedfolder`).
- Commit trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>".
- Never stage .DS_Store, .claude/, agent/__pycache__/, repo-root bin/, qwen-agent-workspace/bin/action-from-dir, pin-sh2.json, story_bible_*.json, .superpowers/.
- Never read, cat, grep or source ~/.zshenv or any fleet.env, and never print tokens or secrets.
- Never ssh, scp, rsync or HTTP to macstudio, and never read or suggest copying its files.
- Pipeline files unchanged, so `test_mut26` holds.
- Never push. Push and merge are a separate step that needs the user's approval.

House rules (from the prior plans; every task's requirements include them):

- **Where work happens.** This Mac only, no network. The movie-UI tests start servers on `127.0.0.1` inside the test; nothing else listens. Never render, train, or load a model. No job ever runs in a task.
- **The checkout.** Never touch the main checkout `/Users/reubenpatterson/local_agent_harness`. Every command runs in the worktree `$S/seedf-wt`, on branch `seed-folder`. Never git stash, reset or check out other people's work.
- **Python.** Every new or changed file must run on Python 3.9.6 and 3.13. So use none of: the `match` statement, `X | Y` type expressions, the walrus operator, `str.removeprefix`, `zip(strict=)` and parenthesised context managers. The code blocks below use none of them.
- **Editing.** Executors make every change to a tracked file with the Edit tool. Each new file is created with the Write tool in the step that names it, and edited with the Edit tool from then on. Never use `rm`, `sed -i`, a redirect or a script to change a tracked file.
- **Git.** Stage only the paths a task names, and check `git diff --cached --name-only` before every commit. Every commit command passes the trailer as a second `-m`.
- **Paths.**
  - `S` = `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`.
  - `WS` = `$S/seedf-wt/qwen-agent-workspace`, and `D` = `$S/seedf-baseline`.
  - The git root is `$S/seedf-wt`, so `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix.
  - Run every command from `WS`. Shell variables do not persist between commands, so every block defines the variables it uses.
- **Code blocks** are copied byte for byte. An Edit step's old text must occur exactly once in the file at that moment, with or without its last newline. If it does not, stop and report; do not adapt it. Every Create and Edit below was replayed in order on a scratch copy of `a9d5aa1`'s `WS`, and each old text occurred exactly once at its turn (see "Execution handoff").
- **The compile check** (Step 4 of each code task) is this command, with the task's Python files as `FILES`. Expected: two lines, `compiled N` for 3.9 and then for 3.13.

```bash
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' FILES; done
```

## Review Focus

These five inputs and failure modes are the ones most likely to reach a user first, the spec implies them, and no SDT row exercises them. Each is pinned by a test in the task that owns its code. The tests are named `test_sf_review_focus_N_...` (Plan ruling PR17).

1. **Phone and camera exports as characters: timestamp-only and non-Latin file names** (`20241101_123456.jpg`, `20241101_123457.jpg`, `日本.png`, `Café ☕ día.png`).
   - SD36 strips leading digits, so every timestamp name and every non-Latin name collapses to `char`. SDT26 checks single names as a pure function only; over HTTP the names travel through JSON, the job fields, `job.json`, the argv and the Jobs summary.
   - Expected: characters `char`, `char-2`, `char-3`, `cafe-dia`; each argv's `create <name>` is that name; every copy of the file name (`fields.seed_folder.name`, `GET /api/jobs`'s `seed_folder.name`) is the exact original text.
   - Test: `test_sf_review_focus_1_timestamp_and_non_latin_names_as_characters` (Task 4).
2. **A refused seed ahead of a seed with the same stem** (a broken `beach.png` next to a good `beach.jpg`).
   - SD20 [spec choice]: only the ok rows draw final IDs. So the table's provisional `beach-2` for the good seed becomes `beach` at Queue, and the user sees the ID change in the table.
   - Expected: preview rows `beach` (refused) and `beach-2` (ok); queue rows `beach` (refused) and `beach` (ok); the job's story is `beach`.
   - Test: `test_sf_review_focus_2_a_refused_seed_does_not_push_a_later_seed_to_a_suffix` (Task 3).
3. **Queue clicked twice, or the same folder queued from two tabs at once.**
   - Both requests run steps 1-4 with no lock and draw the same provisional IDs. Only the final assignment under `STORE_LOCK`, which sees the other run's queued jobs as busy, keeps them apart.
   - Expected: both answer 201; one run gets `a`, `b` and the other `a-2`, `b-2`; four jobs with four distinct stories; each run's jobs share its own `run`.
   - Test: `test_sf_review_focus_3_two_queue_requests_at_once` (Task 3).
4. **A thumbnail or icon smaller than 64 px, refused by the real dry-run path** (no monkeypatched `dry_run_check`).
   - SDT15 replaces `lib.dry_run_check`, so the real `stdout + stderr` detail and `last_line` are never exercised. The stub `ltx-movie --dry-run` here exits 2 with the pipeline's `Error: --seed-image …` line on stderr and nothing on stdout, as `bin/ltx-movie` does (spec 0.1).
   - Expected: every row `refused` with `dry run failed: Error: --seed-image is degenerate: 8x8 (each edge must be at least 64 px)`; the preview answers 200 with `ok` false, and Queue answers 409 and creates nothing.
   - Test: `test_sf_review_focus_4_a_too_small_image_refused_by_the_real_dry_run` (Task 3).
5. **The command preview's sample story ID disagreeing with the confirm table.**
   - SD30's `sampleStoryId` is a JavaScript copy of SD5 and SD7's first candidate. A drift (Unicode, emoji surrogate pairs, the 80-character cut) would show one story ID in the command and another in the table.
   - Expected: for 20 names (the SD10 rows without a suffix, tabs, empty names, dots, `ß`, the `ﬁ` ligature, `☕`, an emoji, a 100-character name with a 40-character prefix), node's `sampleStoryId(name, prefix)` equals Python's `story_id_for(seed_stem(name), prefix, set())`.
   - Test: `test_sf_review_focus_5_the_page_sample_id_matches_the_server` (Task 5; skipped when `node` is absent).

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `movie_ui_seedfolder.py` | Create (Task 1) | The seed-folder core: constants, `first_free`, the story-ID and character-name rules, both taken sets, `_seeds_and_preview`, `validate_request`, `validate_character_request`, `row_reason`, `new_run_id`, `seed_tag`. Never writes. |
| `movie_ui_lib.py` | Modify (Task 2) | `shared_checks` (V2-V5); `run_checks` returns `[v1] + shared_checks(...) + [dry_run_check(...)]`. |
| `movie_ui_server.py` | Modify (Tasks 3, 4) | T3: `import movie_ui_seedfolder as seedfolder`, the Compose route, `job_summary`'s `seed_folder`, `_compose_job_locked`, `seed_taken`, `_dry_runs`, `seed_rows`, `_seed_response`, `_h_seed_folder`. T4: the Characters route, `_phrase_errors`, `_seed_number_errors`, `_character_job_locked`, `character_taken`, `_character_rows`, `_character_response`, `_h_character_seed_folder`. |
| `static/movie-ui/index.html` | Modify (Tasks 5, 6) | T5: the Story ID label span, the Seed folder radio, list and confirm table. T6: the Name label span, the Characters checkbox, list and confirm table. |
| `static/movie-ui/app.js` | Modify (Tasks 5, 6) | T5: the constants, `FOLDER_BOXES` and `part`, folder mode in `composeFields`, `preview` and `updateComposeButtons`, the shared folder functions, the Compose wiring, the Jobs tag. T6: folder mode in `updateCharacterButtons` and `createCharacter`, the Characters wiring. |
| `tests/test_movie_ui_seedfolder.py` | Create (Task 1), extend (Tasks 2-6) | SDT1-SDT9, SDT26, SDT27 (T1); SDT10 (T2); SDT12-SDT24, Review Focus 2-4 (T3); SDT11, SDT28-SDT36, Review Focus 1 (T4); SDT25, Review Focus 5 (T5); SDT37 (T6). |
| `tests/test_movie_ui_http.py`, `tests/test_location_ui.py`, `tests/test_movie_ui_builder.py`, `tests/movie_ui_testutil.py` | Modify (Task 7 only) | The spec 6.1 re-baseline. |

**Task split.** Each task is the smallest unit with its own test cycle and a reviewer gate:
- Task 1 is the pure core, which every later task consumes.
- Task 2 is a behaviour-preserving refactor of `run_checks` with its own pin (SDT10).
- Task 3 is the Compose endpoint, and Task 4 the Characters endpoint. The routes, handlers, the `_locked` splits and the `job_summary` key are tested only through the endpoints, so each endpoint ships whole with its tests. SDT11 asserts 57 routes (both endpoints), so Task 4 owns it (Plan ruling PR19).
- Task 5 is the shared folder code and the Compose page; Task 6 wires the Characters form to the same functions.
- Task 7 is the spec 6.1 test-only commit.

The browser check, the pass bar, the design review and the live checks need a person, a browser or a running movie-ui, so they are the controller's "Verification" section, not an implementer task. The spec requires no docs or README change.

## Between tasks: the existing suite

**The choice.** Feature tasks do **not** edit the existing tests whose assertions the feature changes (spec 6.1). Those tests stay red from the task that first breaks them until Task 7's one test-only commit. Every other existing test must stay green in every task.

**Precision.** The list below was measured on the plan's replay (see "Execution handoff"): after Task 6, `tests/test_movie_ui_http.py`, `test_location_ui.py`, `test_movie_ui_seams.py`, `test_movie_ui_builder.py`, `test_movie_ui_batch.py`, `test_movie_ui_checks.py` and `test_movie_ui_progress.py` lost exactly the four passes below; the existing Characters tests (`test_mu64_mu65_character_endpoints`, `test_mu65_character_create_errors_flaglike_and_unsafe`, `test_fix13_character_empty_seed_upload_is_none`) stayed green. `test_mut15` was not run in the replay (it starts a `bin/movie-ui` process); its cause was confirmed by importing `movie_ui_server` from a copy made like `copy_ui` (`ModuleNotFoundError: No module named 'movie_ui_seedfolder'`).

| Code | Cause | First task |
|---|---|---|
| R57 | `test_mut18_every_api_route_needs_the_token` and `test_lu1_the_location_routes_need_the_token`: `ROUTES` has 56 entries after Task 3 and 57 after Task 4, not 55 | 3 |
| KEYS | `test_mut2_preview_argv_is_the_job_argv`: a job summary has 15 keys (`seed_folder`), not the 14 the test lists | 3 |
| IMP | `test_mut25_source_scan_of_new_python_files`: `movie_ui_server.py` imports `movie_ui_seedfolder`, which the `allowed` set lacks | 3 |
| CPY | `test_mut15_bin_movie_ui_lock_port_and_startup_lines`: `copy_ui` does not copy `movie_ui_seedfolder.py`, so the copied `bin/movie-ui` cannot import `movie_ui_server` and prints nothing | 3 |

`NEW_PY`'s missing entries break nothing (they only widen the compile and scan); Task 7 adds them.

**Expected failures**, written to `$D/expected-failures.txt` in "Before Task 1" Step 3. A line is `T<first task> <test id> <reason>`:

```text
# seed-folder plan: existing tests expected to fail from the given task until Task 7
T3 tests/test_movie_ui_http.py::test_mut18_every_api_route_needs_the_token R57
T3 tests/test_location_ui.py::test_lu1_the_location_routes_need_the_token R57
T3 tests/test_movie_ui_http.py::test_mut2_preview_argv_is_the_job_argv KEYS
T3 tests/test_movie_ui_builder.py::test_mut25_source_scan_of_new_python_files IMP
T3 tests/test_movie_ui_jobs.py::test_mut15_bin_movie_ui_lock_port_and_startup_lines CPY
```

**Gate rule** (Step 4 of every code task):
1. Every new test passes. A new test is one in `tests/test_movie_ui_seedfolder.py`, or any test ID the baseline does not have.
2. The baseline failures fail with the same messages.
3. Every lost baseline pass is listed for a task at or before this one in `$D/expected-failures.txt`.
4. `tests/test_ltx_movie_offline.py` prints the same last line as at the baseline.

**When the gate prints `GATE STOP`:**
- The executor stops and reports the UNEXPECTED or NEW-TEST-FAIL IDs, together with the output of `python3 -B -m pytest -q -p no:cacheprovider --tb=short <ids>`.
- The controller has an Opus reviewer rule on each ID. A lost pass that the list does not name is a defect in this task's code. The controller writes the exact fix, and the gate reruns.
- The list grows only for the timing-sensitive tests below.

**Timing-sensitive tests unrelated to this plan.** These are `tests/test_fleet_tracing.py::test_trt41a_trace_cli_on_one_agent` and `tests/test_fleet_integration.py::test_t47_signatures_and_loopback_rules`. If the gate lists one of them as UNEXPECTED, rerun it alone with `python3 -B -m pytest -q -p no:cacheprovider <node id>`. If it passes alone, the controller appends `T<N> <node id> flaky` to `$D/expected-failures.txt`, and Verification V1 rechecks it.

**Must stay green in every task:** every `tests/test_movie_ui_*.py` test other than the four listed; every `tests/test_location_ui.py` test other than `test_lu1`; `tests/test_vlm_lifecycle.py`, `tests/test_soft_panel_count.py`, `tests/test_location_lib.py` and `tests/test_model_download.py`. In particular `test_ct27_the_static_page`, `test_bt13_the_static_page`, `test_lu13_the_static_page`, `test_mut24_page_headers_and_asset_rules`, `test_vl26_page_gate_and_warn_style`, the three Characters tests named above and `test_mut26_pipeline_files_are_unchanged`. None is in the list, so a failure there stops the gate.

---

## Before Task 1: the plan commit, the snapshot, the baseline (controller; no code)

- [ ] **Step 1: Confirm the plan commit and the tree.**

The plan is committed on `seed-folder` as `docs: seed-folder Compose implementation plan`, directly on top of the amended spec commit `a9d5aa1`.

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/seedf-wt/qwen-agent-workspace
git branch --show-current                                   # expected: seed-folder
git log -4 --format=%h' '%s                                 # expected: <plan sha> docs: seed-folder Compose implementation plan, then a9d5aa1, 604a221, e94ebb0
git diff --stat e94ebb0 HEAD -- . ':(exclude)docs' | tail -1   # expected: no output
git status --short                                          # expected: no output
ls movie_ui_seedfolder.py tests/test_movie_ui_seedfolder.py 2>&1 | grep -c "No such file"   # expected: 2
wc -l movie_ui_lib.py movie_ui_server.py static/movie-ui/index.html static/movie-ui/app.js tests/movie_ui_testutil.py tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_builder.py | tail -9
```

Expected `wc -l` counts (at `a9d5aa1`): `movie_ui_lib.py` 2335, `movie_ui_server.py` 2843, `index.html` 396, `app.js` 2378, `movie_ui_testutil.py` 553, `test_movie_ui_http.py` 1792, `test_location_ui.py` 425, `test_movie_ui_builder.py` 296. If any value differs, stop and report: every Edit below was written against this tree.

- [ ] **Step 2: Take the compressed snapshot (house rule; spec 8 step 1).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
tar czf $S/snapshot-pre-seedfolder-e94ebb0.tgz --exclude qwen-agent-workspace/generated -C $S/seedf-wt qwen-agent-workspace
tar tzf $S/snapshot-pre-seedfolder-e94ebb0.tgz | grep -c '^qwen-agent-workspace/movie_ui_server.py$'   # expected: 1
```

- [ ] **Step 3: Record a fresh baseline and write the gate files (about 17 minutes; spec 8 step 2).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/seedf-baseline
mkdir -p $D
cd $S/seedf-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
grep -c '^PASSED ' $D/baseline-pytest.txt
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1 | tee $D/baseline-offline.txt
```

Expected: the failures include the spec 7 pair, `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`, and the offline line is `OK 347/347`. Whatever this run records **is** the baseline. Report its summary line, its `FAILED`/`ERROR` lines, the pass count and the offline line. Every later "baseline" in this plan means these files.

Then write two scratch files with the Write tool. They are outside the repository and never staged.

1. `$D/expected-failures.txt`: exactly the `text` block of "Between tasks" above.
2. `$D/gate.py`: exactly this (the batch-forks plan's gate with `NEW_FILES` naming the new test file). If the controller already has a gate script that reads `T<n> <test-id> <note>` lines, it may use that instead.

```python
"""The task gate of the seed-folder plan: a full pytest -rA run against the baseline. A new test
is one of the new file or any test ID the baseline does not have."""
import re
import sys

base_file, run_file, expected_file, task = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
NEW_FILES = ("tests/test_movie_ui_seedfolder.py::",)


def status(path):
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            found = re.match(r"^(PASSED|FAILED|ERROR|SKIPPED) (\S+)", line)
            if found:
                out[found.group(2)] = found.group(1)
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
mine = sorted(t for t in now if t.startswith(NEW_FILES) or t not in base)
broken = [t for t in mine if now[t] != "PASSED"]
old_failures = sorted(t for t, s in base.items() if s in ("FAILED", "ERROR"))
still = [t for t in old_failures if now.get(t) in ("FAILED", "ERROR")]
print("lost %d (listed %d, unexpected %d); new tests %d, not passing %d; baseline "
      "failures still failing %d of %d" % (len(lost), len(lost) - len(unexpected),
                                          len(unexpected), len(mine), len(broken), len(still),
                                          len(old_failures)))
for t in lost:
    print("LOST", t, "listed" if listed(t) else "UNEXPECTED")
for t in broken:
    print("NEW-TEST-FAIL", t, now[t])
print("GATE", "PASS" if not unexpected and not broken else "STOP")
```

**The gate block** (Step 4 of every code task; `N` is the task number). It is a full run of about 17 minutes, which may run in the background:

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/seedf-baseline
N=1
cd $S/seedf-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/task-$N-pytest.txt 2>&1; tail -1 $D/task-$N-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/task-$N-pytest.txt $D/expected-failures.txt $N
diff <(python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1) $D/baseline-offline.txt && echo "offline unchanged"
```

Expected: `GATE PASS`, `new tests <count>, not passing 0`, `baseline failures still failing B of B` (B = the baseline's failure count), and `offline unchanged`. Each task's Step 4 gives its count and its `LOST ... listed` lines. On `GATE STOP`, follow the gate rule ("Between tasks").

---

### Task 1: `movie_ui_seedfolder.py`, the pure core (SD1, SD5-SD10, SD12, SD13, SD18, SD22, SD23, SD36-SD38, SD40, SD43 rows 4-8; SDT1-SDT9, SDT26, SDT27)

This task implements:
- Spec 1.1's and 2.4's constants.
- SD5 `seed_stem`, SD6 `valid_prefix`, SD7 `first_free` and `story_id_for`, SD8 `assign_story_ids`, SD36 `character_stem`, as the spec's code, verbatim.
- SD37 `valid_character_prefix`, SD38 `character_name_for` and `assign_character_names`.
- SD9 `taken_names` and SD39 `character_taken_names` (the server sides are Tasks 3 and 4).
- SD12/SD13 `_seeds_and_preview` (rows 4-7, shared) and `validate_request` (rows 2-7; row 1 is the server's `_fields_body`, Task 3); SD43 `validate_character_request` (rows 4-8; rows 1-3 are the server's, Task 4). Rule 5 is checked for every item before rule 6 (Plan ruling PR2).
- SD18 `row_reason`, SD22 `new_run_id`, SD23 `seed_tag`.

Tests: SDT1-SDT9, SDT26 and SDT27 in the new `tests/test_movie_ui_seedfolder.py`. Its imports of `json`, `shutil`, `subprocess`, `threading` and `time` are for Tasks 3-6, which append to the file.

**Files:**
- Create: `movie_ui_seedfolder.py`, `tests/test_movie_ui_seedfolder.py`.
- Read only (at a9d5aa1): `movie_ui_lib.py`: `STORY_ID_RE` `:37`, `CHARACTER_NAME_RE` `:38`, `SMOKE_STORY_ID` `:40`, `last_line` `:1234-1237`, `check` `:1298-1300`, `valid_story_id` `:1319-1321`, `DRY_RUN_TIMEOUT` `:1889`.

**Interfaces:**
- Consumes (existing, `movie_ui_lib`): `valid_story_id(story_id) -> bool`, `CHARACTER_NAME_RE`, `SMOKE_STORY_ID` (`"movie-ui-smoke"`), `DRY_RUN_TIMEOUT` (60), `last_line(text) -> str`; in tests also `check(check_id, name, status, detail="") -> dict`.
- Produces, in `movie_ui_seedfolder` (later tasks use these names exactly):
  - `SEEDS_MAX`, `PREFIX_MAX`, `ID_MAX`, `DRY_RUN_WORKERS`, `RUN_ID_RE`, `_OUTSIDE`, `CHAR_MAX`, `CHAR_PREFIX_MAX`;
  - `first_free(head, stem, taken, limit, trim) -> str` (`taken` is a set of lower-case names; not modified);
  - `seed_stem(name) -> str`, `valid_prefix(prefix) -> bool`, `story_id_for(stem, prefix, taken) -> str`, `assign_story_ids(names, prefix, taken) -> [str]`;
  - `character_stem(name) -> str`, `valid_character_prefix(prefix) -> bool`, `character_name_for(stem, prefix, taken) -> str`, `assign_character_names(names, prefix, taken) -> [str]`;
  - `taken_names(listing, busy_story_ids) -> set of str`, `character_taken_names(listing, busy_names) -> set of str` (non-strings are skipped);
  - `_seeds_and_preview(body) -> (seeds, preview, None)` or `(None, None, message)`; `seeds` is `[{"name": str, "upload_id": <as sent, None when absent>}]`;
  - `validate_request(body) -> (clean, None)` or `(None, message)`; `clean` is `{"prefix": str, "action": "movie" or "story", "seeds": [...], "preview": bool, "check_seams": bool}`;
  - `validate_character_request(body) -> (clean, None)` or `(None, message)`; `clean` is `{"prefix": str, "seeds": [...], "preview": bool}`;
  - `row_reason(v1, v6) -> (status, reason)` with status `"ok"`, `"refused"` or `"skipped"` and reason a str or None;
  - `new_run_id() -> str` (matches `RUN_ID_RE`);
  - `seed_tag(fields) -> {"run": str, "name": str} or None`.

- [ ] **Step 1: Write the failing tests.**

Create `tests/test_movie_ui_seedfolder.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""Tests for seed-folder Compose and Characters (docs/superpowers/specs/2026-11-01-seed-folder-
compose-design.md, Section 6: SDT1-SDT37, with the plan's Review Focus pins 1-5): the pure module
movie_ui_seedfolder, lib.shared_checks, POST /api/jobs/seed-folder, POST
/api/characters/seed-folder and the static page.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedfolder.py

Rules (spec Section 6):
- The HTTP tests use the env fixture: mt.set_home, mt.make_stub_workspace and the in-test
  mt.Running server on 127.0.0.1. Uploads go through POST /api/uploads with mt.PNG + bytes([i])
  (distinct IDs) or mt.PNG (the same ID).
- lib.shared_checks is replaced by a pass stub (one V2 record) in every HTTP test, except where
  a test replaces it otherwise. V1 runs for real (stub workspace, current help fixture). V6 runs
  the stub bin/ltx-movie --dry-run (exit 0) unless the test replaces lib.dry_run_check.
- The Characters tests use the same fixture, which removes CHARACTER_LIBRARY_DIR unless a test
  sets it, and the stub bin/character (never run, because no test dispatches a job).
- No test uses the real HOME, renders, or contacts a real server. None touches port 8177 or
  8178. The VLM lifecycle is off (conftest.py). No test ever starts a job.
Stdlib plus pytest.
"""

import json
import os
import random
import re
import shutil
import string
import subprocess
import threading
import time

import pytest

import movie_ui_testutil as mt
import movie_ui_lib as lib
import movie_ui_seedfolder as seedfolder
import movie_ui_server as srv

WS = mt.WS
P40 = "p" * 40
UP = "a" * 64 + ".png"
DEGENERATE = "Error: --seed-image is degenerate: 8x8 (each edge must be at least 64 px)"
PREFIX_MSG = "story ID prefix must be a valid story ID of at most 40 characters"
SEEDS_MSG = "seeds must be a list of 1 to 100 items"
PREVIEW_MSG = "preview must be true or false"
CPREFIX_MSG = "character name prefix must match [a-z][a-z0-9-]{1,23} and be at most 12 characters"


# --- SDT1 (SD5, SD7, SD8, SD10): the examples of spec 2.3 ---------------------------------------

# (names, prefix, taken, result); taken None stands for taken_names([], []) (row 13).
EXAMPLES = [
    (["beach.png"], "", set(), ["beach"]),
    (["beach.png", "beach.jpg"], "", set(), ["beach", "beach-2"]),
    (["Beach Day!.webp"], "temple", set(), ["temple-Beach-Day"]),
    (["__01.png"], "", set(), ["01"]),
    (["日本.png"], "", set(), ["seed"]),
    (["beach.png"], "", {"beach", "beach-2"}, ["beach-3"]),
    (["Beach.png"], "", {"beach"}, ["Beach-2"]),
    (["Beach Day.final.png"], "", set(), ["Beach-Day.final"]),
    (["Café.png"], "", set(), ["Cafe"]),
    (["a..b.png", "a -- b.png"], "", set(), ["a.b", "a-b"]),
    ([".png"], "", set(), ["png"]),
    (["Beach.png", "beach.jpg"], "", set(), ["Beach", "beach-2"]),
    (["movie-ui-smoke.png"], "", None, ["movie-ui-smoke-2"]),
    (["a" * 100 + ".png"], P40, set(), [P40 + "-" + "a" * 39]),
    (["a" * 100 + ".png"], P40, {(P40 + "-" + "a" * 39).lower()}, [P40 + "-" + "a" * 37 + "-2"]),
    (["a" * 77 + "-bc.png"], "", {("a" * 77 + "-bc").lower()}, ["a" * 77 + "-2"]),
    (["x.png"], "", {"x"} | set("x-%d" % k for k in range(2, 1000)), ["x-1000"]),
]


@pytest.mark.parametrize("names,prefix,taken,want", EXAMPLES,
                         ids=["row%d" % (i + 1) for i in range(len(EXAMPLES))])
def test_sdt1_the_story_id_examples(names, prefix, taken, want):
    taken = seedfolder.taken_names([], []) if taken is None else taken
    assert seedfolder.assign_story_ids(names, prefix, taken) == want


# --- SDT2 (SD5): seed_stem edge cases --------------------------------------------------------------

def test_sdt2_seed_stem_edge_cases():
    for name, want in (("", "seed"), ("...", "seed"), ("-_-.png", "seed"), ("a\tb.png", "a-b"),
                       ("x.tar.gz", "x.tar")):
        assert seedfolder.seed_stem(name) == want, name


# --- SDT3 (SD6, SD7): prefixes and the 80-character cut ---------------------------------------------

def test_sdt3_prefixes_and_the_80_character_cut():
    for prefix in ("", "temple", P40):
        assert seedfolder.valid_prefix(prefix) is True, prefix
    for prefix in ("p" * 41, "-x", "a..b", "a/b", 5):
        assert seedfolder.valid_prefix(prefix) is False, prefix
    story_id = seedfolder.story_id_for(seedfolder.seed_stem("b" * 120 + ".png"), "", set())
    assert story_id == "b" * 80 and len(story_id) == 80


# --- SDT4 (SD7, SD9): case-insensitive collisions keep the file's case -------------------------------

def test_sdt4_case_insensitive_collisions_keep_the_file_case():
    assert seedfolder.assign_story_ids(["beach.png"], "", seedfolder.taken_names(["BEACH"], [])) == [
        "beach-2"]
    assert seedfolder.assign_story_ids(["BEACH.png"], "", {"beach"}) == ["BEACH-2"]


# --- SDT5 (SD9): the taken set from a listing and the busy jobs --------------------------------------

def test_sdt5_the_taken_set_from_a_listing(tmp_path):
    stories = os.path.join(str(tmp_path), "generated", "stories")
    os.makedirs(os.path.join(stories, "d1"))
    with open(os.path.join(stories, "f1"), "w") as f:
        f.write("x")
    os.symlink(os.path.join(stories, "missing"), os.path.join(stories, "l1"))
    os.symlink(os.path.join(stories, "d1"), os.path.join(stories, "l2"))
    got = seedfolder.taken_names(os.listdir(stories), {"Busy": "j", None: "k"})
    assert got == {"d1", "f1", "l1", "l2", "busy", "movie-ui-smoke"}


# --- SDT6 (SD8): taken is not modified; the loop bound holds ------------------------------------------

def test_sdt6_taken_is_not_modified_and_the_loop_bound_holds():
    taken = {"beach"}
    assert seedfolder.assign_story_ids(["beach.png", "beach.png"], "", taken) == ["beach-2", "beach-3"]
    assert taken == {"beach"}
    many = {"x"} | set("x-%d" % k for k in range(2, 1000))
    assert len(many) == 999
    assert seedfolder.story_id_for("x", "", many) == "x-1000"
    assert seedfolder.first_free("", "ab", {"ab"}, 4, "-") == "ab-2"
    assert seedfolder.first_free("p-", "abcdef", set(), 6, "-") == "p-abcd"


# --- SDT7 (SD5-SD8): a random property check -----------------------------------------------------

ALPHABET = string.ascii_letters + string.digits + " ._-!/\t" + "é日ßﬁ"
PREFIX_HEAD = string.ascii_letters + string.digits
PREFIX_TAIL = PREFIX_HEAD + "._-"


def _random_prefix(rng):
    while True:
        prefix = rng.choice(PREFIX_HEAD) + "".join(rng.choice(PREFIX_TAIL)
                                                   for _ in range(rng.randint(0, 39)))
        if seedfolder.valid_prefix(prefix):
            return prefix


def test_sdt7_random_names_always_give_valid_distinct_ids():
    rng = random.Random(20261101)
    outputs = []
    for _case in range(3000):
        names = ["".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 120)))
                 for _ in range(rng.randint(1, 5))]
        prefix = "" if rng.random() < 0.5 else _random_prefix(rng)
        taken = set(s.lower() for s in rng.sample(outputs, min(len(outputs), rng.randint(0, 20))))
        ids = seedfolder.assign_story_ids(names, prefix, taken)
        assert len(ids) == len(names)
        folded = [s.lower() for s in ids]
        assert len(set(folded)) == len(folded), ids
        for story_id in ids:
            assert lib.valid_story_id(story_id), story_id
            assert ".." not in story_id and len(story_id) <= 80, story_id
            assert story_id.lower() not in taken, story_id
            if prefix:
                assert story_id.startswith(prefix + "-"), (prefix, story_id)
        outputs.extend(ids)


# --- SDT8 (SD12, SD13): validate_request ------------------------------------------------------------

def _req(**overrides):
    body = {"ws": "/abs/ws", "action": "story", "story_id": "", "narrative": "A courier crosses a quay.",
            "seeds": [{"name": "a.png", "upload_id": UP}], "preview": True}
    body.update(overrides)
    return body


def test_sdt8_validate_request_refusals():
    without_preview = _req()
    del without_preview["preview"]
    cases = [
        (_req(action="smoke"), "action must be movie or story"),
        (_req(action=None), "action must be movie or story"),
        (_req(action="redo", seeds=[]), "action must be movie or story"),
        (_req(story_id=5), PREFIX_MSG),
        (_req(story_id="-x"), PREFIX_MSG),
        (_req(story_id="p" * 41), PREFIX_MSG),
        (_req(seeds="a.png"), SEEDS_MSG),
        (_req(seeds=[]), SEEDS_MSG),
        (_req(seeds=[{"name": "a.png"}] * 101), SEEDS_MSG),
        (_req(seeds=[{"name": "a.png"}, "b.png"]), "seed 2 must be an object"),
        (_req(seeds=[{"name": 5}, "x"]), "seed 2 must be an object"),
        (_req(seeds=[{"name": 5}, {"name": "b.png"}]), "seed 1: name must be a string without '/'"),
        (_req(seeds=[{"upload_id": UP}]), "seed 1: name must be a string without '/'"),
        (_req(seeds=[{"name": "a.png"}, {"name": "sub/b.png"}]),
         "seed 2: name must be a string without '/'"),
        (_req(preview="true"), PREVIEW_MSG),
        (_req(preview=None), PREVIEW_MSG),
        (_req(preview=1), PREVIEW_MSG),
        (without_preview, PREVIEW_MSG),
    ]
    for body, message in cases:
        assert seedfolder.validate_request(body) == (None, message), (body, message)


def test_sdt8_validate_request_accepts():
    no_prefix = _req()
    del no_prefix["story_id"]
    for body in (no_prefix, _req(story_id=None), _req(story_id="")):
        clean, error = seedfolder.validate_request(body)
        assert error is None and clean["prefix"] == ""
    seeds = [{"name": "s%d.png" % i, "upload_id": UP, "extra": 1} for i in range(100)]
    clean, error = seedfolder.validate_request(_req(story_id="temple", action="movie", seeds=seeds,
                                                    preview=False, check_seams=True))
    assert error is None
    assert clean == {"prefix": "temple", "action": "movie",
                     "seeds": [{"name": "s%d.png" % i, "upload_id": UP} for i in range(100)],
                     "preview": False, "check_seams": True}
    assert seedfolder.validate_request(_req(check_seams="yes"))[0]["check_seams"] is False
    assert seedfolder.validate_request(_req(seeds=[{"name": "a.png"}]))[0]["seeds"] == [
        {"name": "a.png", "upload_id": None}]
    no_action = _req()
    del no_action["action"]
    assert seedfolder.validate_request(no_action)[0]["action"] == "story"


# --- SDT9 (SD1, SD18, SD22, SD23): imports, reasons, the run ID and the tag -------------------------

def test_sdt9_the_module_imports():
    with open(os.path.join(WS, "movie_ui_seedfolder.py"), encoding="utf-8") as f:
        source = f.read()
    assert sorted(re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M)) == [
        "movie_ui_lib", "re", "secrets", "time", "unicodedata"]


def _v6(status, detail):
    return lib.check("V6", "dry run", status, detail)


def test_sdt9_row_reasons():
    v1_pass = lib.check("V1", "fields", "pass", "")
    v1_fail = lib.check("V1", "fields", "fail", "narrative is required\nfps must be an integer from 1 to 120")
    timeout = "bin/ltx-movie --dry-run timed out after %d s" % lib.DRY_RUN_TIMEOUT
    assert seedfolder.row_reason(v1_fail, _v6("skip", "skipped: V1 failed")) == (
        "refused", "narrative is required; fps must be an integer from 1 to 120")
    assert seedfolder.row_reason(v1_pass, _v6("skip", "skipped: shared checks failed")) == (
        "skipped", "skipped: shared checks failed")
    assert seedfolder.row_reason(v1_pass, _v6("fail", timeout)) == (
        "refused", "dry run timed out after %d s" % lib.DRY_RUN_TIMEOUT)
    assert seedfolder.row_reason(v1_pass, _v6("fail", "plan\n" + DEGENERATE + "\n")) == (
        "refused", "dry run failed: " + DEGENERATE)
    assert seedfolder.row_reason(v1_pass, _v6("fail", "")) == ("refused", "dry run failed")
    assert seedfolder.row_reason(v1_pass, _v6("pass", "")) == ("ok", None)


def test_sdt9_the_run_id_and_the_seed_tag():
    assert seedfolder.RUN_ID_RE.fullmatch(seedfolder.new_run_id())
    tag = {"run": "sf-20261101-120000-ab12", "name": "a.png"}
    assert seedfolder.seed_tag({"seed_folder": dict(tag, extra=1)}) == tag
    for fields in (None, "x", {}, {"seed_folder": None}, {"seed_folder": "x"},
                   {"seed_folder": {"name": "a.png"}}, {"seed_folder": {"run": 5, "name": "a.png"}},
                   {"seed_folder": {"run": "r"}}, {"seed_folder": {"run": "r", "name": None}}):
        assert seedfolder.seed_tag(fields) is None, fields


# --- SDT26 (SD36, SD38, SD40): the character-name examples of spec 2.4 ---------------------------

CHAR_EXAMPLES = [
    (["Kyra.png"], "", set(), ["kyra"]),
    (["Kyra.png", "kyra.jpg"], "", set(), ["kyra", "kyra-2"]),
    (["Old Man #2.webp"], "temple", set(), ["temple-old-man-2"]),
    (["01_hero.png"], "", set(), ["hero"]),
    (["日本.png"], "", set(), ["char"]),
    (["a.png"], "", set(), ["a-char"]),
    (["kyra.png"], "", {"kyra", "kyra-2"}, ["kyra-3"]),
    (["Café Owner.png"], "", set(), ["cafe-owner"]),
    (["x" * 30 + ".png"], "", set(), ["x" * 24]),
    (["x" * 30 + ".png"], "", {"x" * 24}, ["x" * 22 + "-2"]),
    (["abcdefghij-klm.png"], "p" * 12, set(), ["p" * 12 + "-abcdefghij"]),
    (["2049.png"], "", set(), ["char"]),
    (["shot_01.png", "Shot 01.png"], "", set(), ["shot-01", "shot-01-2"]),
]


@pytest.mark.parametrize("names,prefix,taken,want", CHAR_EXAMPLES,
                         ids=["row%d" % (i + 1) for i in range(len(CHAR_EXAMPLES))])
def test_sdt26_the_character_name_examples(names, prefix, taken, want):
    assert seedfolder.assign_character_names(names, prefix, taken) == want


# --- SDT27 (SD36-SD38): character prefixes and a random property check ---------------------------

def test_sdt27_character_prefixes():
    for prefix in ("", "temple", "p" * 12):
        assert seedfolder.valid_character_prefix(prefix) is True, prefix
    for prefix in ("p" * 13, "a", "1ab", "Ab", "a_b", 5):
        assert seedfolder.valid_character_prefix(prefix) is False, prefix


CHAR_ALPHABET = ALPHABET + string.ascii_uppercase
CHAR_PREFIX_TAIL = string.ascii_lowercase + string.digits + "-"


def test_sdt27_random_names_always_give_valid_character_names():
    rng = random.Random(20261102)
    outputs = []
    for _case in range(3000):
        names = ["".join(rng.choice(CHAR_ALPHABET) for _ in range(rng.randint(0, 120)))
                 for _ in range(rng.randint(1, 5))]
        prefix = "" if rng.random() < 0.5 else rng.choice(string.ascii_lowercase) + "".join(
            rng.choice(CHAR_PREFIX_TAIL) for _ in range(rng.randint(1, 11)))
        assert seedfolder.valid_character_prefix(prefix), prefix
        taken = set(rng.sample(outputs, min(len(outputs), rng.randint(0, 20))))
        got = seedfolder.assign_character_names(names, prefix, taken)
        assert len(got) == len(names) and len(set(got)) == len(got), got
        for name in got:
            assert lib.CHARACTER_NAME_RE.fullmatch(name), name
            assert name not in taken, name
            if prefix:
                assert name.startswith(prefix + "-"), (prefix, name)
        outputs.extend(got)
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedfolder.py 2>&1 | tail -1
```

Expected: `1 error` (collection: `ModuleNotFoundError: No module named 'movie_ui_seedfolder'`).

- [ ] **Step 3: Implement.**

Create `movie_ui_seedfolder.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""movie_ui_seedfolder -- seed-folder Compose and Characters: the pure core of one job per seed
image (docs/superpowers/specs/2026-11-01-seed-folder-compose-design.md, deliverable G1).

The constants (spec 1.1, 2.4), the shared candidate loop first_free and the story-ID rules (2.1),
the taken sets (2.2, 2.4), the character-name rules (2.4), the request checks of
POST /api/jobs/seed-folder (3.1) and POST /api/characters/seed-folder (3.5), the status and
reason of a row (3.2), the run ID (3.3) and the seed-folder tag of a job (3.4).

Standard library plus movie_ui_lib only (SD1). Valid on Python 3.9 and 3.13. This module never
writes and never starts a process. Every function is pure except new_run_id, which reads the
clock and draws random digits.
"""

import re
import secrets
import time
import unicodedata

import movie_ui_lib as lib

SEEDS_MAX = 100
PREFIX_MAX = 40
ID_MAX = 80                                   # STORY_ID_RE, movie_ui_lib.py:37
DRY_RUN_WORKERS = 4
RUN_ID_RE = re.compile(r"^sf-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
_OUTSIDE = re.compile(r"[^A-Za-z0-9._-]+")
CHAR_MAX = 24                                 # CHARACTER_NAME_RE, movie_ui_lib.py:38
CHAR_PREFIX_MAX = 12


# ---------------------------------------------------------------------------
# Story IDs (spec 2.1, 2.2)
# ---------------------------------------------------------------------------

def seed_stem(name):
    """Rules 1-4: the cleaned stem of a seed's file name; never empty."""
    dot = name.rfind(".")
    stem = name[:dot] if dot > 0 else name                                    # 1
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")   # 2
    stem = _OUTSIDE.sub("-", stem)                                            # 3
    stem = re.sub(r"\.{2,}", ".", stem)
    stem = re.sub(r"-{2,}", "-", stem)
    stem = re.sub(r"^[^A-Za-z0-9]+", "", stem).rstrip("-._")                  # 4
    return stem or "seed"


def valid_prefix(prefix):
    """SD6: the prefix is "" or a valid story ID of at most PREFIX_MAX characters. It is used
    exactly as typed."""
    return prefix == "" or (lib.valid_story_id(prefix) and len(prefix) <= PREFIX_MAX)


def first_free(head, stem, taken, limit, trim):
    """The first free head + cut stem [+ "-k"] of at most limit characters (SD7, SD38)."""
    def candidate(suffix):
        room = limit - len(head) - len(suffix)
        return head + stem[:room].rstrip(trim) + suffix

    first = candidate("")
    if first.lower() not in taken:
        return first
    for k in range(2, 12 * (len(taken) + 1) + 10):
        name = candidate("-%d" % k)
        if name.lower() not in taken:
            return name
    raise AssertionError("no free name")      # unreachable (bound below)


def story_id_for(stem, prefix, taken):
    """Rules 5-7: the first free story ID for one stem (SD7)."""
    return first_free(prefix + "-" if prefix else "", stem, taken, ID_MAX, "-._")


def assign_story_ids(names, prefix, taken):
    """Rules 1-7 for every name in order; taken is not modified (SD8)."""
    seen = set(taken)
    out = []
    for name in names:
        story_id = story_id_for(seed_stem(name), prefix, seen)
        seen.add(story_id.lower())
        out.append(story_id)
    return out


def taken_names(listing, busy_story_ids):
    """SD9: the lower-case names a seed's story ID must avoid: the listing of
    generated/stories, the story IDs of the busy jobs (strings only) and movie-ui-smoke."""
    return ({n.lower() for n in listing} | {s.lower() for s in busy_story_ids if isinstance(s, str)}
            | {lib.SMOKE_STORY_ID})


# ---------------------------------------------------------------------------
# Character names (spec 2.4)
# ---------------------------------------------------------------------------

def character_stem(name):
    """Character name rules 1-6 (SD36): lower case, at least 2 characters."""
    dot = name.rfind(".")
    stem = name[:dot] if dot > 0 else name                                    # 1 (as SD5)
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii").lower()   # 2, 3
    stem = re.sub(r"[^a-z0-9]+", "-", stem)                                   # 4
    stem = re.sub(r"^[^a-z]+", "", stem).rstrip("-")                          # 5
    if len(stem) < 2:                                                         # 6
        stem = stem + "-char" if stem else "char"
    return stem


def valid_character_prefix(prefix):
    """SD37: the prefix is "" or a character name of at most CHAR_PREFIX_MAX characters. It is
    used exactly as typed."""
    return prefix == "" or (isinstance(prefix, str) and lib.CHARACTER_NAME_RE.fullmatch(prefix) is not None
                            and len(prefix) <= CHAR_PREFIX_MAX)


def character_name_for(stem, prefix, taken):
    """SD38: the first free character name for one stem, through SD7's first_free."""
    return first_free(prefix + "-" if prefix else "", stem, taken, CHAR_MAX, "-")


def assign_character_names(names, prefix, taken):
    """SD38: SD8's loop with the character rules; taken is not modified."""
    seen = set(taken)
    out = []
    for name in names:
        character = character_name_for(character_stem(name), prefix, seen)
        seen.add(character.lower())
        out.append(character)
    return out


def character_taken_names(listing, busy_names):
    """SD39: the lower-cased library listing and the busy jobs' character names (strings only)."""
    return {n.lower() for n in listing} | {s.lower() for s in busy_names if isinstance(s, str)}


# ---------------------------------------------------------------------------
# The requests (spec 3.1, 3.5)
# ---------------------------------------------------------------------------

def _seeds_and_preview(body):
    """SD13 rows 4-7, shared by both endpoints (SD43): (seeds, preview, None) or (None, None,
    message). Rule 5 is checked for every item before rule 6 (plan ruling PR2). seeds is
    [{"name", "upload_id"}]; upload_id is the item's value, or None when the item has none."""
    seeds = body.get("seeds")
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= SEEDS_MAX:
        return None, None, "seeds must be a list of 1 to 100 items"
    for k, item in enumerate(seeds, 1):
        if not isinstance(item, dict):
            return None, None, "seed %d must be an object" % k
    for k, item in enumerate(seeds, 1):
        name = item.get("name")
        if not isinstance(name, str) or "/" in name:
            return None, None, "seed %d: name must be a string without '/'" % k
    preview = body.get("preview")
    if not isinstance(preview, bool):
        return None, None, "preview must be true or false"
    return [{"name": item["name"], "upload_id": item.get("upload_id")} for item in seeds], preview, None


def validate_request(body):
    """SD12, SD13 rows 2-7: (clean, None), or (None, the message of the first failing rule).
    clean is {"prefix", "action", "seeds", "preview", "check_seams"}."""
    action = body.get("action", "story")
    if action not in ("movie", "story"):
        return None, "action must be movie or story"
    prefix = body.get("story_id")
    if prefix is None:
        prefix = ""
    if not isinstance(prefix, str) or not valid_prefix(prefix):
        return None, "story ID prefix must be a valid story ID of at most 40 characters"
    seeds, preview, error = _seeds_and_preview(body)
    if error is not None:
        return None, error
    return {"prefix": prefix, "action": action, "seeds": seeds, "preview": preview,
            "check_seams": body.get("check_seams") is True}, None


def validate_character_request(body):
    """SD43 rows 4-8: (clean, None), or (None, the message of the first failing rule). clean is
    {"prefix", "seeds", "preview"}; the prefix is the body's "name"."""
    prefix = body.get("name")
    if prefix is None:
        prefix = ""
    if not valid_character_prefix(prefix):
        return None, "character name prefix must match [a-z][a-z0-9-]{1,23} and be at most 12 characters"
    seeds, preview, error = _seeds_and_preview(body)
    if error is not None:
        return None, error
    return {"prefix": prefix, "seeds": seeds, "preview": preview}, None


# ---------------------------------------------------------------------------
# Rows, the run ID and the tag (spec 3.2-3.4)
# ---------------------------------------------------------------------------

def row_reason(v1, v6):
    """SD18: (status, reason) of a row from its V1 and V6 records, in the table's order."""
    if v1["status"] == "fail":
        return "refused", v1["detail"].replace("\n", "; ")
    if v6["status"] == "skip" and v6["detail"] == "skipped: shared checks failed":
        return "skipped", "skipped: shared checks failed"
    if v6["status"] == "fail":
        if v6["detail"] == "bin/ltx-movie --dry-run timed out after %d s" % lib.DRY_RUN_TIMEOUT:
            return "refused", "dry run timed out after %d s" % lib.DRY_RUN_TIMEOUT
        line = lib.last_line(v6["detail"])
        return "refused", ("dry run failed: " + line) if line else "dry run failed"
    return "ok", None


def new_run_id():
    """SD22: "sf-" + UTC %Y%m%d-%H%M%S + "-" + 4 hex digits (matches RUN_ID_RE). A display tag
    only, so there is no uniqueness loop."""
    return "sf-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(2)


def seed_tag(fields):
    """SD23: {"run", "name"} of a job's fields["seed_folder"] when both are strings, else None."""
    value = fields.get("seed_folder") if isinstance(fields, dict) else None
    if isinstance(value, dict) and isinstance(value.get("run"), str) and isinstance(value.get("name"), str):
        return {"run": value["run"], "name": value["name"]}
    return None
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedfolder.py 2>&1 | tail -1
```

Expected: `43 passed` (SDT1's 17 rows, SDT2-SDT7 one each, SDT8 two, SDT9 three, SDT26's 13 rows, SDT27 two). Run the compile check with `FILES` = `movie_ui_seedfolder.py tests/test_movie_ui_seedfolder.py`; expected: `compiled 2` twice. Then run the gate block with `N=1`. Expected: `GATE PASS`, `lost 0`, `new tests 43, not passing 0`, all the baseline failures still failing, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
git add movie_ui_seedfolder.py tests/test_movie_ui_seedfolder.py
git diff --cached --name-only    # expected: those 2 paths
git commit -m "feat(movie-ui): movie_ui_seedfolder, the pure core of seed-folder Compose and Characters: first_free, story IDs, character names, taken sets, request checks, row reasons, run ID, tag (SD1, SD5-SD10, SD12, SD13, SD18, SD22, SD23, SD36-SD40, SD43; SDT1-SDT9, SDT26, SDT27)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `lib.shared_checks`, split out of `run_checks` (SD2; SDT10)

This task implements SD2: `shared_checks(fields, ws_real, py=sys.executable)` directly above `run_checks`, and `run_checks`'s last statement becomes `return [v1] + shared_checks(fields, ws_real, py) + [dry_run_check(fields, ws_real, state)]`. The `cache = {}` line moves into `shared_checks`. The V1 and smoke branches are untouched, and the records and their order are unchanged, so `/api/validate` and `/api/jobs` are unchanged.

Tests: SDT10, appended to `tests/test_movie_ui_seedfolder.py` as one test (Plan ruling PR13).

**Files:**
- Modify: `movie_ui_lib.py`: `run_checks` `:2115-2126` (at a9d5aa1); `tests/test_movie_ui_seedfolder.py` (append after Task 1's last test).
- Read only: `movie_ui_lib.py`: `host_checks` `:1666`, `model_checks` `:1815`, `lora_checks` `:1939`, `compat_checks` `:2013`, `dry_run_check` `:2102-2108`, `V_GROUP_NAMES` `:2111-2112`.

**Interfaces:**
- Consumes (existing): `host_checks(fields, ws_real, py=sys.executable) -> [record]`, `model_checks(fields, ws_real) -> [record]`, `lora_checks(fields, ws_real, cache, smoke=False) -> [record]`, `compat_checks(fields, ws_real, cache, smoke=False) -> [record]`; tests: `mt.set_home`, `mt.make_stub_workspace`, `mt.fields`.
- Produces: `lib.shared_checks(fields, ws_real, py=sys.executable) -> [record]` (V2, V3, V4, V5 in order; Task 3 calls it as `lib.shared_checks(fields, ws)`, and the HTTP tests replace it).

- [ ] **Step 1: Write the failing test.**

Edit `tests/test_movie_ui_seedfolder.py`: replace this text, which occurs exactly once:

```python
            if prefix:
                assert name.startswith(prefix + "-"), (prefix, name)
        outputs.extend(got)
```

with:

```python
            if prefix:
                assert name.startswith(prefix + "-"), (prefix, name)
        outputs.extend(got)


# --- SDT10 (SD2): lib.shared_checks is V2-V5 of run_checks ----------------------------------------

def test_sdt10_shared_checks_split(monkeypatch, tmp_path):
    state = mt.set_home(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    tagged = []
    for name, check_id in (("host_checks", "V2"), ("model_checks", "V3"), ("lora_checks", "V4"),
                           ("compat_checks", "V5")):
        record = lib.check(check_id, name, "pass", "tagged " + name)
        tagged.append(record)
        monkeypatch.setattr(lib, name, (lambda r: lambda *args, **kwargs: [r])(record))
    dry = lib.check("V6", "dry run", "pass", "tagged dry_run_check")
    monkeypatch.setattr(lib, "dry_run_check", lambda fields, ws_real, st: dry)
    fields = mt.fields(ws)
    assert lib.run_checks(fields, ws, state) == [lib.check("V1", "fields", "pass", "")] + tagged + [dry]
    assert lib.shared_checks(fields, ws) == tagged
    assert lib.run_checks(mt.fields(ws, panels=0), ws, state) == (
        [lib.check("V1", "fields", "fail", "panels must be an integer from 1 to 200")]
        + [lib.check(i, n, "skip", "skipped: V1 failed") for i, n in lib.V_GROUP_NAMES])
```

- [ ] **Step 2: Run it and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedfolder.py::test_sdt10_shared_checks_split 2>&1 | tail -1
```

Expected: `1 failed` (`AttributeError: module 'movie_ui_lib' has no attribute 'shared_checks'`).

- [ ] **Step 3: Implement.**

Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
def run_checks(fields, ws_real, state, py=sys.executable):
    """MU43: V1; on a V1 failure one skip per V2-V6; otherwise V2-V6 in order, no short circuit."""
    errors = validate_fields(fields, ws_real, state)
    v1 = check("V1", "fields", "fail" if errors else "pass", "\n".join(errors))
    if errors:
        return [v1] + [check(i, n, "skip", "skipped: V1 failed") for i, n in V_GROUP_NAMES]
    if fields["action"] == "smoke":
        return [v1] + smoke_checks(fields, ws_real)
    cache = {}
    return ([v1] + host_checks(fields, ws_real, py) + model_checks(fields, ws_real)
            + lora_checks(fields, ws_real, cache) + compat_checks(fields, ws_real, cache)
            + [dry_run_check(fields, ws_real, state)])
```

with:

```python
def shared_checks(fields, ws_real, py=sys.executable):
    """V2-V5 of run_checks for fields that passed V1 (seed-folder spec SD2, SD16)."""
    cache = {}
    return (host_checks(fields, ws_real, py) + model_checks(fields, ws_real)
            + lora_checks(fields, ws_real, cache) + compat_checks(fields, ws_real, cache))


def run_checks(fields, ws_real, state, py=sys.executable):
    """MU43: V1; on a V1 failure one skip per V2-V6; otherwise V2-V6 in order, no short circuit."""
    errors = validate_fields(fields, ws_real, state)
    v1 = check("V1", "fields", "fail" if errors else "pass", "\n".join(errors))
    if errors:
        return [v1] + [check(i, n, "skip", "skipped: V1 failed") for i, n in V_GROUP_NAMES]
    if fields["action"] == "smoke":
        return [v1] + smoke_checks(fields, ws_real)
    return [v1] + shared_checks(fields, ws_real, py) + [dry_run_check(fields, ws_real, state)]
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedfolder.py 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_checks.py 2>&1 | tail -1
```

Expected: `44 passed`, then `14 passed` (the existing V1-V7 tests are unchanged). Run the compile check with `FILES` = `movie_ui_lib.py tests/test_movie_ui_seedfolder.py`; expected: `compiled 2` twice. Then run the gate block with `N=2`. Expected: `GATE PASS`, `lost 0`, `new tests 44, not passing 0`, all the baseline failures still failing, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
git add movie_ui_lib.py tests/test_movie_ui_seedfolder.py
git diff --cached --name-only    # expected: those 2 paths
git commit -m "refactor(movie-ui): lib.shared_checks, V2-V5 of run_checks, with the same records in the same order (seed-folder SD2; SDT10)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `POST /api/jobs/seed-folder`, `_compose_job_locked` and the job tag (SD3, SD4, SD9, SD11-SD25; SDT12-SDT24, Review Focus 2-4)

This task implements:
- G3's import, `import movie_ui_seedfolder as seedfolder`, after `import movie_ui_lib as lib`.
- SD11: the route, directly after `POST /api/jobs`, and `MovieUIHandler.h_seed_folder = _h_seed_folder` in the block at `:955-964`. (SDT11, which asserts 57 routes, is Task 4's; Plan ruling PR19.)
- SD23: `job_summary` gains `"seed_folder": seedfolder.seed_tag(job.get("fields"))` (15 keys).
- SD3: `_compose_job_locked(server, fields, seams=False)` holds `create_compose_job`'s body, with the docstring plus "The caller holds STORE_LOCK."; `create_compose_job` becomes `with STORE_LOCK: return _compose_job_locked(server, fields, seams)`. The batch submitter's call (`:2352`) is unchanged.
- SD9 `seed_taken`; SD14-SD18 `seed_rows` (steps 1-4, no lock; an `upload_id` that is not a non-empty string is `seed image upload missing`); SD17 `_dry_runs` (at most 4 plain `threading.Thread` workers, a shared counter under a local lock, a raising dry run gives a V6 fail); SD21 `_seed_response`; SD12, SD13, SD19, SD20 `_h_seed_folder`. The row dict and `_seed_response` are plan names (Plan ruling PR10).
- SD4, SD24, SD25 need no code of their own: nothing new is stored, `lib.compose_fields` already drops `seeds` and `seed_folder`, and `lib.create_job` already writes `job.json` before `queue.json`. SDT19, SDT23 and SDT24 pin them.

Tests: SDT12-SDT24 and Review Focus 2-4, appended to `tests/test_movie_ui_seedfolder.py`, with the spec 6 `env` fixture (which installs the `shared_checks` pass stub and removes `CHARACTER_LIBRARY_DIR`; Plan ruling PR9) and helpers. SDT20 is three tests (Plan ruling PR8).

**Files:**
- Modify (at a9d5aa1): `movie_ui_server.py`: the imports `:31-32`, `ROUTES` `:100`, `job_summary` `:735`, `create_compose_job` `:779-795`, the end of `_h_job_create` `:803-805` (the new section is inserted after it, before `_h_jobs` `:808`), `MovieUIHandler.h_job_create` `:957`; `tests/test_movie_ui_seedfolder.py` (append after SDT10).
- Read only: `movie_ui_server.py`: `STORE_LOCK` `:35`, `BATCH_LOCK` `:36`, `ApiError` `:131-136`, `resolve_ws` `:166-180`, `_handle`'s 500 branch `:435-439`, `_fields_body` `:738-741`, `_create_seams_job` `:765-776`, `job_index` `:2000-2017`; `movie_ui_lib.py`: `create_job` `:174-190`, `build_argv` `:1016-1073`, `validate_fields` `:1443-1549`, `dry_run_check` `:2102-2108`.

**Interfaces:**
- Consumes: Task 1's `seedfolder.validate_request`, `assign_story_ids`, `taken_names`, `row_reason`, `new_run_id`, `seed_tag`, `DRY_RUN_WORKERS`, `RUN_ID_RE` (tests); Task 2's `lib.shared_checks(fields, ws_real)`. Existing: `_fields_body(body) -> fields` (raises `ApiError(400)` for `ws`), `job_index(server, ws_real) -> ({story_id: fields}, {story_id: job_id})`, `job_summary(server, job_id, queue) -> dict`, `lib.validate_fields(fields, ws_real, state) -> [str]`, `lib.dry_run_check(fields, ws_real, state) -> record`, `lib.checks_pass(checks) -> bool`, `lib.read_queue(state) -> [str]`, `lib.create_job(state, job_id, kind, workspace, story_id, character, argv, fields) -> dict`.
- Produces, in `movie_ui_server`:
  - `_compose_job_locked(server, fields, seams=False) -> job_id` (the caller holds `STORE_LOCK`); `create_compose_job(server, fields, seams=False) -> job_id` (same behaviour as before);
  - `seed_taken(server, ws_real) -> set of str`;
  - `_dry_runs(server, rows) -> None` (sets each row's `"v6"`);
  - `seed_rows(server, fields, clean) -> (rows, shared)`; each row is `{"name", "upload_id", "story_id", "fields", "v1", "v6", "status", "reason"}`;
  - `_seed_response(server, rows, shared, run=None, job_ids=None) -> dict` (the SD21 body; `job_ids` maps a row index to its job ID);
  - `_h_seed_folder(self, groups, query, body) -> (status, body)` and `MovieUIHandler.h_seed_folder`;
  - `job_summary`'s new key `"seed_folder"`.
- The SD21 body that Task 5 consumes: `{"ok": bool, "shared_checks": [record], "queued": int, "refused": int, "run": str or null, "seeds": [{"name", "upload_id", "story_id", "status", "reason", "checks": [V1, V6], "job": summary or null}]}`; 400 is `{"error": message}`.

- [ ] **Step 1: Write the failing tests.**

Edit `tests/test_movie_ui_seedfolder.py`: replace this text, which occurs exactly once:

```python
        [lib.check("V1", "fields", "fail", "panels must be an integer from 1 to 200")]
        + [lib.check(i, n, "skip", "skipped: V1 failed") for i, n in lib.V_GROUP_NAMES])
```

with:

```python
        [lib.check("V1", "fields", "fail", "panels must be an integer from 1 to 200")]
        + [lib.check(i, n, "skip", "skipped: V1 failed") for i, n in lib.V_GROUP_NAMES])


# --- The HTTP tests: fixture and helpers (spec 6 rules) ---------------------------------------------

PASS_V2 = lib.check("V2", "render", "pass", "stub")


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "0")
    monkeypatch.delenv("CHARACTER_LIBRARY_DIR", raising=False)
    state = mt.set_home(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    monkeypatch.setattr(lib, "shared_checks", lambda fields, ws_real, py=None: [PASS_V2])
    running = mt.Running(state)
    yield {"state": state, "ws": ws, "tmp": str(tmp_path), "srv": running}
    running.close()
    mt.kill_everything(state)


def _upload(s, data=mt.PNG):
    status, _h, payload = mt.api(s, "POST", "/api/uploads", raw=data,
                                 headers={"Content-Type": "image/png"})
    assert status == 201, payload
    return payload["upload_id"]


def _seeds(s, names, same=False):
    """[{"name", "upload_id"}], one upload per name: mt.PNG + bytes([i]), or mt.PNG for every
    name when same."""
    return [{"name": name, "upload_id": _upload(s, mt.PNG if same else mt.PNG + bytes([i]))}
            for i, name in enumerate(names)]


def _body(ws, seeds, preview, **overrides):
    """A seed-folder request: the stub workspace's valid Compose fields with no prefix."""
    body = dict(mt.fields(ws, story_id=""), seeds=seeds, preview=preview)
    body.update(overrides)
    return body


def _post(s, body):
    return mt.api(s, "POST", "/api/jobs/seed-folder", body=body)


def _job(state, job_id):
    return lib.read_job(lib.job_dir(state, job_id))


def _upload_path(state, seed):
    return os.path.join(state, "uploads", seed["upload_id"])


def _nothing_created(state):
    return lib.list_job_ids(state) == [] and os.listdir(os.path.join(state, "jobs")) == [] and \
        lib.read_queue(state) == []


# --- SDT12 (SD13): malformed requests get 400 and run nothing ----------------------------------------

def test_sdt12_malformed_requests_get_400(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["a.png"])
    good = _body(ws, seeds, True)
    no_ws = dict(good)
    del no_ws["ws"]
    no_preview = dict(good)
    del no_preview["preview"]
    cases = [
        (no_ws, "missing ws"),
        (dict(good, ws="relative/ws"), "ws must be an absolute path"),
        (dict(good, ws=env["tmp"]), "not a harness workspace (no bin/ltx-movie): %s" % env["tmp"]),
        (dict(good, action="regenerate"), "action must be movie or story"),
        (dict(good, story_id="-x"), PREFIX_MSG),
        (dict(good, seeds=[]), SEEDS_MSG),
        (dict(good, seeds=["a.png"]), "seed 1 must be an object"),
        (dict(good, seeds=[{"name": "x/a.png", "upload_id": seeds[0]["upload_id"]}]),
         "seed 1: name must be a string without '/'"),
        (dict(good, preview="yes"), PREVIEW_MSG),
        (no_preview, PREVIEW_MSG),
    ]
    for body, message in cases:
        assert _post(s, body)[::2] == (400, {"error": message}), message
    assert _nothing_created(state)
    assert [c for c in mt.stub_calls(ws) if c["sub"] == "--dry-run"] == []


# --- SDT13 (SD14, SD19, SD21): a preview creates nothing ---------------------------------------------

def test_sdt13_a_preview_creates_nothing(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    names = ["shot10.png", "shot2.png", "Beach Day!.webp"]
    seeds = _seeds(s, names)
    uploads = sorted(os.listdir(os.path.join(state, "uploads")))
    status, _h, data = _post(s, _body(ws, seeds, True))
    assert status == 200, data
    assert set(data) == {"ok", "shared_checks", "queued", "refused", "run", "seeds"}
    assert (data["ok"], data["queued"], data["run"], data["refused"]) == (True, 0, None, 0)
    assert data["shared_checks"] == [PASS_V2]
    assert [r["name"] for r in data["seeds"]] == names
    assert [r["story_id"] for r in data["seeds"]] == ["shot10", "shot2", "Beach-Day"]
    for row, seed in zip(data["seeds"], seeds):
        assert set(row) == {"name", "upload_id", "story_id", "status", "reason", "checks", "job"}
        assert (row["upload_id"], row["status"], row["reason"], row["job"]) == (
            seed["upload_id"], "ok", None, None)
        assert [(c["id"], c["status"]) for c in row["checks"]] == [("V1", "pass"), ("V6", "pass")]
    assert _nothing_created(state)
    assert os.listdir(os.path.join(ws, "generated", "stories")) == []
    assert sorted(os.listdir(os.path.join(state, "uploads"))) == uploads


# --- SDT14 (SD14, SD15, SD20, SD21): queue story jobs in seed order ------------------------------------

def test_sdt14_queue_story_jobs_in_seed_order(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["Beach Day!.webp", "shot2.png", "shot10.png"])
    status, _h, data = _post(s, _body(ws, seeds, False, action="story", story_id="temple"))
    assert status == 201, data
    assert (data["ok"], data["queued"], data["refused"]) == (True, 3, 0)
    ids = ["temple-Beach-Day", "temple-shot2", "temple-shot10"]
    assert [r["story_id"] for r in data["seeds"]] == ids
    queue = lib.read_queue(state)
    assert len(queue) == 3 and queue == [r["job"]["id"] for r in data["seeds"]]
    for job_id, story_id, seed in zip(queue, ids, seeds):
        job = _job(state, job_id)
        assert (job["kind"], job["story_id"]) == ("story", story_id)
        argv = job["argv"]
        assert argv[argv.index("--story-id") + 1] == story_id
        assert argv[argv.index("--seed-image") + 1] == _upload_path(state, seed)
        assert "--story-only" in argv
        assert job["fields"]["seed_upload"] == seed["upload_id"]
        assert job["fields"]["width"] is None and job["fields"]["height"] is None
    dry = [c for c in mt.stub_calls(ws) if c["tool"] == "ltx-movie" and c["sub"] == "--dry-run"]
    assert len(dry) == 3
    seen = dict((c["argv"][c["argv"].index("--story-id") + 1], c["argv"][c["argv"].index("--seed-image") + 1])
                for c in dry)
    assert seen == dict((story_id, _upload_path(state, seed)) for story_id, seed in zip(ids, seeds))


# --- SDT15 (SD15, SD18, SD20): refused rows and the one queued seed -----------------------------------

def test_sdt15_refused_rows_and_the_one_queued_seed(env, monkeypatch):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["s1.png", "s2.png", "s3.png", "s4.png", "s5.png", "s6.png"])
    unknown = "f" * 64 + ".png"
    seeds[0]["upload_id"] = unknown
    seeds[1]["upload_id"] = 7
    seeds[5]["upload_id"] = ""
    timeout = "bin/ltx-movie --dry-run timed out after %d s" % lib.DRY_RUN_TIMEOUT

    def dry_run(fields, ws_real, st):
        detail = {"s3": "plan\n" + DEGENERATE + "\n", "s4": timeout}.get(fields["story_id"])
        return lib.check("V6", "dry run", "fail" if detail else "pass", detail or "")

    monkeypatch.setattr(lib, "dry_run_check", dry_run)
    status, _h, data = _post(s, _body(ws, seeds, False))
    assert status == 201, data
    assert (data["ok"], data["queued"], data["refused"]) == (True, 1, 5)
    assert [(r["status"], r["reason"]) for r in data["seeds"]] == [
        ("refused", "seed image upload %s not found" % unknown),
        ("refused", "seed image upload missing"),
        ("refused", "dry run failed: " + DEGENERATE),
        ("refused", "dry run timed out after 60 s"),
        ("ok", None),
        ("refused", "seed image upload missing")]
    assert (data["seeds"][1]["upload_id"], data["seeds"][5]["upload_id"]) == (7, "")
    assert data["seeds"][0]["checks"][1] == lib.check("V6", "dry run", "skip", "skipped: V1 failed")
    assert [r["job"] is None for r in data["seeds"]] == [True, True, True, True, False, True]
    assert lib.read_queue(state) == [data["seeds"][4]["job"]["id"]]
    assert len(lib.list_job_ids(state)) == 1


# --- SDT16 (SD16, SD20, SD21): a failed shared check skips every seed ----------------------------------

def test_sdt16_a_failed_shared_check_skips_every_seed(env, monkeypatch):
    s, ws, state = env["srv"], env["ws"], env["state"]
    failing = [lib.check("V2", "render", "fail", "ffmpeg not found on PATH")]
    monkeypatch.setattr(lib, "shared_checks", lambda fields, ws_real, py=None: list(failing))
    calls = []

    def dry_run(fields, ws_real, st):
        calls.append(fields["story_id"])
        return lib.check("V6", "dry run", "pass")

    monkeypatch.setattr(lib, "dry_run_check", dry_run)
    seeds = _seeds(s, ["a.png", "b.png"])
    for preview, code in ((True, 200), (False, 409)):
        status, _h, data = _post(s, _body(ws, seeds, preview))
        assert status == code, data
        assert "error" not in data
        assert (data["ok"], data["queued"], data["run"], data["refused"]) == (False, 0, None, 2)
        assert data["shared_checks"] == failing
        assert [(r["status"], r["reason"]) for r in data["seeds"]] == [
            ("skipped", "skipped: shared checks failed")] * 2
        assert [r["checks"][1] for r in data["seeds"]] == [
            lib.check("V6", "dry run", "skip", "skipped: shared checks failed")] * 2
    assert calls == []
    assert _nothing_created(state)


# --- SDT17 (SD15, SD16, SD20): shots mode refuses every seed before the shared checks ------------------

def test_sdt17_shots_mode_refuses_every_seed(env, monkeypatch):
    s, ws, state = env["srv"], env["ws"], env["state"]
    calls = []

    def shared(fields, ws_real, py=None):
        calls.append(fields["story_id"])
        return [PASS_V2]

    monkeypatch.setattr(lib, "shared_checks", shared)
    seeds = _seeds(s, ["a.png", "b.png"])
    for preview, code in ((True, 200), (False, 409)):
        status, _h, data = _post(s, _body(ws, seeds, preview, action="movie", mode="shots"))
        assert status == code, data
        assert (data["ok"], data["queued"], data["shared_checks"]) == (False, 0, [])
        assert [(r["status"], r["reason"]) for r in data["seeds"]] == [
            ("refused", "a seed image cannot be used with shots mode")] * 2
    assert calls == []
    assert _nothing_created(state)


# --- SDT18 (SD20): seams jobs follow their movies ------------------------------------------------------

def test_sdt18_seams_jobs_follow_their_movies(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["m1.png", "m2.png"])
    status, _h, data = _post(s, _body(ws, seeds, False, action="movie", mode="chained", check_seams=True))
    assert status == 201 and data["queued"] == 2, data
    m1, m2 = [r["job"]["id"] for r in data["seeds"]]
    queue = lib.read_queue(state)
    assert len(queue) == 4 and (queue[0], queue[2]) == (m1, m2)
    for movie, seams in ((m1, queue[1]), (m2, queue[3])):
        assert _job(state, movie)["kind"] == "movie"
        job = _job(state, seams)
        assert job["kind"] == "seams"
        assert job["fields"] == {"ws": ws, "story_id": _job(state, movie)["story_id"], "after": movie}
    before = lib.read_queue(state)
    status, _h, data = _post(s, _body(ws, seeds, False, action="movie", mode="chained", check_seams=False))
    assert status == 201, data
    assert lib.read_queue(state) == before + [r["job"]["id"] for r in data["seeds"]]
    before = lib.read_queue(state)
    status, _h, data = _post(s, _body(ws, seeds, False, action="story", check_seams=True))
    assert status == 201, data
    assert lib.read_queue(state) == before + [r["job"]["id"] for r in data["seeds"]]


# --- SDT19 (SD20, SD23, SD24): the seed-folder tag -----------------------------------------------------

def test_sdt19_the_seed_folder_tag(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    names = ["Beach Day!.webp", "shot2.png", "shot10.png"]
    status, _h, data = _post(s, _body(ws, _seeds(s, names), False, story_id="temple"))
    assert status == 201, data
    run = data["run"]
    assert seedfolder.RUN_ID_RE.fullmatch(run)
    for row, name in zip(data["seeds"], names):
        fields = _job(state, row["job"]["id"])["fields"]
        assert fields["seed_folder"] == {"run": run, "name": name}
        assert row["job"]["seed_folder"] == {"run": run, "name": name}
        bare = dict(fields)
        del bare["seed_folder"]
        assert "seed_folder" not in lib.compose_fields(fields)
        assert lib.compose_fields(fields) == lib.compose_fields(bare)
    other = mt.make_job(env["state"], ["true"], ws, story_id="other")
    queued = mt.api(s, "GET", "/api/jobs")[2]["queued"]
    tags = dict((j["id"], j["seed_folder"]) for j in queued)
    assert tags[other] is None
    assert [tags[r["job"]["id"]] for r in data["seeds"]] == [{"run": run, "name": n} for n in names]
    assert all(len(j) == 15 for j in queued)


# --- SDT20 (SD9, SD14, SD20): final IDs avoid new stories and busy jobs ---------------------------------

def test_sdt20a_a_story_made_between_preview_and_queue(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["beach.png"])
    assert _post(s, _body(ws, seeds, True))[2]["seeds"][0]["story_id"] == "beach"
    os.makedirs(os.path.join(ws, "generated", "stories", "beach"))
    status, _h, data = _post(s, _body(ws, seeds, False))
    assert status == 201, data
    assert data["seeds"][0]["story_id"] == "beach-2"
    assert _job(state, data["seeds"][0]["job"]["id"])["story_id"] == "beach-2"


def test_sdt20b_a_story_made_during_the_dry_run(env, monkeypatch):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seen = []

    def dry_run(fields, ws_real, st):
        seen.append(fields["story_id"])
        os.makedirs(os.path.join(ws_real, "generated", "stories", "Beach"), exist_ok=True)
        return lib.check("V6", "dry run", "pass")

    monkeypatch.setattr(lib, "dry_run_check", dry_run)
    status, _h, data = _post(s, _body(ws, _seeds(s, ["beach.png"]), False))
    assert status == 201, data
    assert seen == ["beach"]
    assert data["seeds"][0]["story_id"] == "beach-2"
    assert _job(state, data["seeds"][0]["job"]["id"])["story_id"] == "beach-2"


def test_sdt20c_busy_jobs_take_their_story_ids(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    mt.make_job(state, ["true"], ws, story_id="BEACH")
    mt.make_job(state, ["true"], ws, story_id="shore",
                status={"state": "running", "dispatched": lib.utc_now()})
    status, _h, data = _post(s, _body(ws, _seeds(s, ["beach.png", "shore.png"]), False))
    assert status == 201, data
    assert [r["story_id"] for r in data["seeds"]] == ["beach-2", "shore-2"]


# --- SDT21 (SD17): four dry runs at a time, with no lock held ---------------------------------------

def test_sdt21_four_dry_runs_at_a_time_with_no_lock_held(env, monkeypatch):
    s, ws = env["srv"], env["ws"]
    guard = threading.Lock()
    counts = {"now": 0, "max": 0, "ran": 0}
    locks = []

    def probe():
        got = []
        for lock in (srv.STORE_LOCK, srv.BATCH_LOCK):
            ok = lock.acquire(timeout=1)
            if ok:
                lock.release()
            got.append(ok)
        locks.append(got)

    def dry_run(fields, ws_real, st):
        with guard:
            counts["now"] += 1
            counts["max"] = max(counts["max"], counts["now"])
        other = threading.Thread(target=probe)
        other.start()
        other.join()
        time.sleep(0.3)
        with guard:
            counts["now"] -= 1
            counts["ran"] += 1
        return lib.check("V6", "dry run", "pass")

    monkeypatch.setattr(lib, "dry_run_check", dry_run)
    status, _h, data = _post(s, _body(ws, _seeds(s, ["s%d.png" % i for i in range(10)]), True))
    assert status == 200, data
    assert (counts["max"], counts["ran"]) == (4, 10)
    assert locks == [[True, True]] * 10


# --- SDT22 (SD8, SD20): the same image twice -----------------------------------------------------------

def test_sdt22_the_same_image_twice(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["a.png", "a.png"], same=True)
    assert seeds[0]["upload_id"] == seeds[1]["upload_id"]
    status, _h, data = _post(s, _body(ws, seeds, False))
    assert status == 201 and data["queued"] == 2, data
    assert [r["story_id"] for r in data["seeds"]] == ["a", "a-2"]
    argvs = [_job(state, r["job"]["id"])["argv"] for r in data["seeds"]]
    assert [a[a.index("--seed-image") + 1] for a in argvs] == [_upload_path(state, seeds[0])] * 2


# --- SDT23 (SD25): a failure mid-queue keeps the earlier jobs ------------------------------------------

def test_sdt23_a_failure_mid_queue_keeps_the_earlier_jobs(env, monkeypatch):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["a.png", "b.png", "c.png"])
    real = lib.create_job
    calls = []

    def flaky(*args, **kwargs):
        calls.append(args[1])
        if len(calls) == 2:
            raise OSError(28, "No space left on device")
        return real(*args, **kwargs)

    monkeypatch.setattr(lib, "create_job", flaky)
    assert _post(s, _body(ws, seeds, False))[::2] == (500, {"error": "internal error"})
    first = calls[0]
    assert _job(state, first)["story_id"] == "a"
    assert lib.read_queue(state) == [first] and lib.list_job_ids(state) == [first]
    assert srv.STORE_LOCK.acquire(timeout=1)
    srv.STORE_LOCK.release()


# --- SDT24 (SD24): the compose routes ignore seed-folder keys ------------------------------------------

def test_sdt24_the_compose_routes_ignore_seed_folder_keys(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    upload = _upload(s)
    plain = mt.fields(ws, seed_upload=upload)
    extra = dict(plain, seeds=[{"name": "a.png", "upload_id": upload}],
                 seed_folder={"run": "sf-20261101-120000-ab12", "name": "a.png"})
    status, _h, created = mt.api(s, "POST", "/api/jobs", body=extra)
    assert status == 201, created
    fields = _job(state, created["job"]["id"])["fields"]
    assert "seeds" not in fields and "seed_folder" not in fields
    assert created["job"]["seed_folder"] is None
    assert mt.api(s, "POST", "/api/validate", body=extra)[::2] == mt.api(
        s, "POST", "/api/validate", body=plain)[::2]


# --- Review Focus 2-4 (the plan's Review Focus section) -------------------------------------------------

def test_sf_review_focus_2_a_refused_seed_does_not_push_a_later_seed_to_a_suffix(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = [{"name": "beach.png", "upload_id": "f" * 64 + ".png"},
             {"name": "beach.jpg", "upload_id": _upload(s)}]
    preview = _post(s, _body(ws, seeds, True))[2]
    assert [(r["story_id"], r["status"]) for r in preview["seeds"]] == [("beach", "refused"), ("beach-2", "ok")]
    status, _h, data = _post(s, _body(ws, seeds, False))
    assert status == 201, data
    assert [(r["story_id"], r["status"]) for r in data["seeds"]] == [("beach", "refused"), ("beach", "ok")]
    assert _job(state, data["seeds"][1]["job"]["id"])["story_id"] == "beach"


def test_sf_review_focus_3_two_queue_requests_at_once(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["a.png", "b.png"])
    results = []

    def post():
        results.append(_post(s, _body(ws, seeds, False)))

    threads = [threading.Thread(target=post) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r[0] for r in results) == [201, 201]
    assert sorted([row["story_id"] for row in r[2]["seeds"]] for r in results) == [["a", "b"], ["a-2", "b-2"]]
    assert sorted(_job(state, i)["story_id"] for i in lib.list_job_ids(state)) == ["a", "a-2", "b", "b-2"]
    for _status, _h, data in results:
        assert set(row["job"]["seed_folder"]["run"] for row in data["seeds"]) == {data["run"]}


def test_sf_review_focus_4_a_too_small_image_refused_by_the_real_dry_run(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    mt.stub_config(ws, {"ltx-movie --dry-run": {"exit": 2, "stdout": "", "stderr": DEGENERATE + "\n"}})
    seeds = _seeds(s, ["thumb.png", "icon.png"])
    status, _h, data = _post(s, _body(ws, seeds, True))
    assert status == 200, data
    assert (data["ok"], data["refused"]) == (False, 2)
    assert [(r["status"], r["reason"]) for r in data["seeds"]] == [("refused", "dry run failed: " + DEGENERATE)] * 2
    assert [r["checks"][1]["status"] for r in data["seeds"]] == ["fail", "fail"]
    status, _h, data = _post(s, _body(ws, seeds, False))
    assert status == 409, data
    assert _nothing_created(state)
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedfolder.py 2>&1 | tail -1
```

Expected: `18 failed, 44 passed`. Every new HTTP test fails: the route answers 404 (`not found`), and SDT24 fails on `created["job"]["seed_folder"]` (`KeyError`).

- [ ] **Step 3: Implement.**

**3.1.** The import. Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
import movie_ui_batch as batch
import movie_ui_lib as lib
```

with:

```python
import movie_ui_batch as batch
import movie_ui_lib as lib
import movie_ui_seedfolder as seedfolder
```

**3.2.** The route (SD11). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    ("POST", r"/api/jobs", "h_job_create", "/api/jobs"),
```

with:

```python
    ("POST", r"/api/jobs", "h_job_create", "/api/jobs"),
    ("POST", r"/api/jobs/seed-folder", "h_seed_folder", "/api/jobs/seed-folder"),
```

**3.3.** The job tag (SD23). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
            "progress": server.progress(job_id, job, status) if state in lib.ACTIVE_STATES else None}
```

with:

```python
            "progress": server.progress(job_id, job, status) if state in lib.ACTIVE_STATES else None,
            "seed_folder": seedfolder.seed_tag(job.get("fields"))}
```

**3.4.** `_compose_job_locked` (SD3). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
def create_compose_job(server, fields, seams=False):
    """Create the queued job of a validated compose submission; returns its ID. With seams, a
    chained movie's seams job is queued right behind it under the same STORE_LOCK hold, with the
    movie as its "after" (chained end frames spec CE14, D12)."""
    state, real = server.state, fields["ws"]
    with STORE_LOCK:
        job_id = lib.new_job_id(state)
        if fields["action"] == "smoke":
            lib.write_smoke_manifest(state, job_id)
            argv = lib.build_smoke_argv(fields, real, state, job_id)
            return lib.create_job(state, job_id, "smoke", real, None, None, argv, fields)["id"]
        argv = lib.build_argv(fields, real, state)
        job_id = lib.create_job(state, job_id, COMPOSE_KINDS[fields["action"]], real, fields["story_id"],
                                None, argv, fields)["id"]
        if seams and fields["action"] == "movie" and fields["mode"] == "chained":
            _create_seams_job(state, real, fields["story_id"], after=job_id)
        return job_id
```

with:

```python
def _compose_job_locked(server, fields, seams=False):
    """Create the queued job of a validated compose submission; returns its ID. With seams, a
    chained movie's seams job is queued right behind it under the same STORE_LOCK hold, with the
    movie as its "after" (chained end frames spec CE14, D12). The caller holds STORE_LOCK."""
    state, real = server.state, fields["ws"]
    job_id = lib.new_job_id(state)
    if fields["action"] == "smoke":
        lib.write_smoke_manifest(state, job_id)
        argv = lib.build_smoke_argv(fields, real, state, job_id)
        return lib.create_job(state, job_id, "smoke", real, None, None, argv, fields)["id"]
    argv = lib.build_argv(fields, real, state)
    job_id = lib.create_job(state, job_id, COMPOSE_KINDS[fields["action"]], real, fields["story_id"],
                            None, argv, fields)["id"]
    if seams and fields["action"] == "movie" and fields["mode"] == "chained":
        _create_seams_job(state, real, fields["story_id"], after=job_id)
    return job_id


def create_compose_job(server, fields, seams=False):
    """Create the queued job of a validated compose submission; returns its ID. With seams, a
    chained movie's seams job is queued right behind it under the same STORE_LOCK hold, with the
    movie as its "after" (chained end frames spec CE14, D12)."""
    with STORE_LOCK:
        return _compose_job_locked(server, fields, seams)
```

**3.5.** The seed-folder section (SD9, SD12-SD21). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    job_id = create_compose_job(self.server, fields,
                                seams=isinstance(body, dict) and body.get("check_seams") is True)
    return 201, {"job": job_summary(self.server, job_id, lib.read_queue(self.server.state)), "checks": checks}
```

with:

```python
    job_id = create_compose_job(self.server, fields,
                                seams=isinstance(body, dict) and body.get("check_seams") is True)
    return 201, {"job": job_summary(self.server, job_id, lib.read_queue(self.server.state)), "checks": checks}


# ---------------------------------------------------------------------------
# Seed-folder Compose (docs/superpowers/specs/2026-11-01-seed-folder-compose-design.md, Section 3)
# ---------------------------------------------------------------------------

def seed_taken(server, ws_real):
    """SD9: the lower-case names a seed's story ID must avoid."""
    try:
        names = os.listdir(os.path.join(ws_real, "generated", "stories"))
    except OSError:
        names = []
    return seedfolder.taken_names(names, job_index(server, ws_real)[1])


def _dry_runs(server, rows):
    """SD17: V6 (lib.dry_run_check) for each of rows, at most seedfolder.DRY_RUN_WORKERS at a
    time on plain threads that take the next index from a shared counter; sets row["v6"]. A dry
    run that raises gives a V6 fail record. Neither STORE_LOCK nor BATCH_LOCK is held."""
    state = server.state
    guard = threading.Lock()
    nxt = [0]

    def work():
        while True:
            with guard:
                i = nxt[0]
                nxt[0] += 1
            if i >= len(rows):
                return
            row = rows[i]
            try:
                row["v6"] = lib.dry_run_check(row["fields"], row["fields"]["ws"], state)
            except Exception as e:
                row["v6"] = lib.check("V6", "dry run", "fail",
                                      "dry run error: %s: %s" % (type(e).__name__, e))

    workers = [threading.Thread(target=work, name="movie-ui-dry-run", daemon=True)
               for _ in range(min(seedfolder.DRY_RUN_WORKERS, len(rows)))]
    for t in workers:
        t.start()
    for t in workers:
        t.join()


def seed_rows(server, fields, clean):
    """SD14-SD18: steps 1-4 for every seed of a validated request, with no lock held. Returns
    (rows, shared). rows has one dict per request seed, in request order: {"name", "upload_id",
    "story_id" (provisional), "fields" (the seed's job fields), "v1", "v6", "status", "reason"};
    shared is the V2-V5 records of SD16 ([] when no seed passed V1)."""
    ws, state = fields["ws"], server.state
    seeds = clean["seeds"]
    ids = seedfolder.assign_story_ids([s["name"] for s in seeds], clean["prefix"],
                                      seed_taken(server, ws))                          # step 1
    rows = []
    for seed, story_id in zip(seeds, ids):                                             # step 2
        f = dict(fields, story_id=story_id, seed_upload=seed["upload_id"])
        if not (isinstance(seed["upload_id"], str) and seed["upload_id"]):
            errors = ["seed image upload missing"]
        else:
            errors = lib.validate_fields(f, ws, state)
        rows.append({"name": seed["name"], "upload_id": seed["upload_id"], "story_id": story_id,
                     "fields": f, "v1": lib.check("V1", "fields", "fail" if errors else "pass",
                                                  "\n".join(errors)),
                     "v6": None, "status": None, "reason": None})
    passed = [row for row in rows if row["v1"]["status"] == "pass"]
    shared = lib.shared_checks(passed[0]["fields"], ws) if passed else []               # step 3
    if passed and lib.checks_pass(shared):
        _dry_runs(server, passed)                                                       # step 4
    for row in rows:
        if row["v6"] is None:
            detail = "skipped: V1 failed" if row["v1"]["status"] == "fail" else "skipped: shared checks failed"
            row["v6"] = lib.check("V6", "dry run", "skip", detail)
        row["status"], row["reason"] = seedfolder.row_reason(row["v1"], row["v6"])
    return rows, shared


def _seed_response(server, rows, shared, run=None, job_ids=None):
    """SD21: the answer body. job_ids maps the index of each queued row to its job ID; queue.json
    is read once, after STORE_LOCK was released (SD20 step 4)."""
    job_ids = job_ids or {}
    queue = lib.read_queue(server.state) if job_ids else []
    seeds = []
    for i, row in enumerate(rows):
        seeds.append({"name": row["name"], "upload_id": row["upload_id"], "story_id": row["story_id"],
                      "status": row["status"], "reason": row["reason"], "checks": [row["v1"], row["v6"]],
                      "job": job_summary(server, job_ids[i], queue) if i in job_ids else None})
    return {"ok": any(row["status"] == "ok" for row in rows), "shared_checks": shared,
            "queued": len(job_ids), "refused": sum(1 for row in rows if row["status"] != "ok"),
            "run": run, "seeds": seeds}


def _h_seed_folder(self, groups, query, body):
    """POST /api/jobs/seed-folder (SD11-SD21): check every seed, then answer a preview (200) or
    queue one story or movie job per ok seed, in seed order (201; 409 when no seed is ok)."""
    server = self.server
    fields = _fields_body(body)
    clean, error = seedfolder.validate_request(body)
    if error is not None:
        raise ApiError(400, error)
    fields["seed_upload"] = fields["width"] = fields["height"] = None
    rows, shared = seed_rows(server, fields, clean)
    if clean["preview"]:
        return 200, _seed_response(server, rows, shared)
    ok = [i for i, row in enumerate(rows) if row["status"] == "ok"]
    if not ok:
        return 409, _seed_response(server, rows, shared)
    run = seedfolder.new_run_id()
    created = []
    with STORE_LOCK:
        final = seedfolder.assign_story_ids([rows[i]["name"] for i in ok], clean["prefix"],
                                            seed_taken(server, fields["ws"]))
        for i, story_id in zip(ok, final):
            f = dict(rows[i]["fields"], story_id=story_id,
                     seed_folder={"run": run, "name": rows[i]["name"]})
            created.append((i, story_id, _compose_job_locked(server, f, seams=clean["check_seams"])))
    job_ids = {}
    for i, story_id, job_id in created:
        rows[i]["story_id"] = story_id
        job_ids[i] = job_id
    return 201, _seed_response(server, rows, shared, run, job_ids)
```

**3.6.** The handler (SD11). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
MovieUIHandler.h_job_create = _h_job_create
```

with:

```python
MovieUIHandler.h_job_create = _h_job_create
MovieUIHandler.h_seed_folder = _h_seed_folder
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedfolder.py 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seams.py tests/test_movie_ui_batch.py 2>&1 | tail -1
```

Expected: `62 passed`, then the seams and batch files pass in full (they exercise `create_compose_job` with and without `check_seams`, and the batch submitter's call). Run the compile check with `FILES` = `movie_ui_server.py tests/test_movie_ui_seedfolder.py`; expected: `compiled 2` twice. Then run the gate block with `N=3`. Expected: `GATE PASS`, `lost 5 (listed 5, unexpected 0)` with the five `T3` lines of `$D/expected-failures.txt` as `LOST ... listed`, `new tests 62, not passing 0`, all the baseline failures still failing, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
git add movie_ui_server.py tests/test_movie_ui_seedfolder.py
git diff --cached --name-only    # expected: those 2 paths
git commit -m "feat(movie-ui): POST /api/jobs/seed-folder: one story or movie job per seed, with _compose_job_locked and the job_summary seed_folder tag (SD3, SD4, SD9, SD11-SD25; SDT12-SDT24)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `POST /api/characters/seed-folder` (SD39, SD41-SD46; SDT11, SDT28-SDT36, Review Focus 1)

This task implements:
- SD41: the route, directly after `POST /api/characters`, and `MovieUIHandler.h_character_seed_folder = _h_character_seed_folder` in the block at `:1332-1343`. `GET /api/characters/seed-folder` still reaches `h_character` (the router keeps looking after a method mismatch).
- SD43: `_phrase_errors(phrase)` and `_seed_number_errors(seed_n)`, the phrase block and seed-number check of `character_create_errors` moved out unchanged (each returns `[]` or the one message); `character_create_errors` calls them at the same positions.
- SD45: `_character_job_locked(server, kind, real, fields)` holds `create_character_job`'s body up to and including `lib.create_job(...)` and returns the job ID; `create_character_job` becomes `with STORE_LOCK: job_id = _character_job_locked(...)` followed by its unchanged `return`.
- SD39 `character_taken` (the spec's code, verbatim); SD44 steps 1-2 as `_character_rows` (the check's `name` is the seed's provisional character name; Plan ruling PR20); SD46 `_character_response`; SD42-SD44 `_h_character_seed_folder`. `_character_rows` and `_character_response` are plan names (Plan ruling PR10).

Tests: SDT11, SDT28-SDT36 and Review Focus 1, appended to `tests/test_movie_ui_seedfolder.py`. SDT34 is three tests (Plan ruling PR8).

**Files:**
- Modify (at a9d5aa1): `movie_ui_server.py`: `ROUTES` `:79`, `PHRASE_MAX`/`character_create_errors` `:1239-1242`, the phrase block `:1252-1257`, the seed-number check `:1274-1275`, `create_character_job` `:1284-1289`, the end of `_h_character_create` `:1303-1304` (the new section is inserted after it), `MovieUIHandler.h_character_create` `:1341`; `tests/test_movie_ui_seedfolder.py` (append after Review Focus 4).
- Read only: `movie_ui_server.py`: `ROUTES`'s `GET /api/characters/<name>` `:80`, the router `:390-396`, `_h_character` `:1205-1211`, `job_summary` (Task 3); `movie_ui_lib.py`: `character_argv` `:1167-1197`, `list_job_ids`, `job_state` `:855-860`.

**Interfaces:**
- Consumes: Task 1's `seedfolder.validate_character_request`, `assign_character_names`, `character_taken_names`, `new_run_id`, `RUN_ID_RE` (tests); Task 3's `job_summary` with `seed_folder`. Existing: `self.ws(value) -> realpath` (`resolve_ws`), `character_create_errors(body, state) -> [str]`, `lib.character_argv(kind, fields, ws_real, state) -> [str]`, `lib.create_job(...)`, `server.job(job_id) -> dict or None`, `lib.job_state(state, job_id, queue) -> str`.
- Produces, in `movie_ui_server`:
  - `_phrase_errors(phrase) -> [str]`, `_seed_number_errors(seed_n) -> [str]`;
  - `_character_job_locked(server, kind, real, fields) -> job_id` (the caller holds `STORE_LOCK`); `create_character_job(server, kind, real, fields) -> (201, {"job": summary})` (unchanged);
  - `character_taken(server, ws_real) -> set of str`;
  - `_character_rows(server, real, body, clean) -> [row]`; each row is `{"name", "upload_id", "character", "v1", "status", "reason"}`;
  - `_character_response(server, rows, run=None, job_ids=None) -> dict`;
  - `_h_character_seed_folder(self, groups, query, body) -> (status, body)` and `MovieUIHandler.h_character_seed_folder`.
- The SD46 body that Task 6 consumes: SD21's keys, with `"character"` for `"story_id"`, `checks` `[V1]` and `shared_checks` `[]`; 400 is `{"error": message}`.

- [ ] **Step 1: Write the failing tests.**

Edit `tests/test_movie_ui_seedfolder.py`: replace this text, which occurs exactly once:

```python
    status, _h, data = _post(s, _body(ws, seeds, False))
    assert status == 409, data
    assert _nothing_created(state)
```

with:

```python
    status, _h, data = _post(s, _body(ws, seeds, False))
    assert status == 409, data
    assert _nothing_created(state)


# --- The Characters HTTP tests: helpers (spec 6 rules) ---------------------------------------------

def _cbody(ws, seeds, preview, **overrides):
    """A Characters seed-folder request: no prefix, phrase "the stranger", seed 7."""
    body = {"ws": ws, "name": "", "phrase": "the stranger", "seed": 7, "seeds": seeds, "preview": preview}
    body.update(overrides)
    return body


def _cpost(s, body):
    return mt.api(s, "POST", "/api/characters/seed-folder", body=body)


def _character_job(state, ws, kind, name, job_state=None):
    """A job naming a character, made as SDT28 says: queued, or with job_state written and the job
    removed from the queue (as mt.make_job does)."""
    job_id = lib.new_job_id(state)
    lib.create_job(state, job_id, kind, ws, None, name, ["true"], {})
    if job_state is not None:
        lib.write_queue(state, [i for i in lib.read_queue(state) if i != job_id])
        lib.write_status(lib.job_dir(state, job_id), {"state": job_state})
    return job_id


# --- SDT11 (SD11): the Compose route and its token-----------------------------------------------------

def test_sdt11_the_route_and_its_token(env):
    s = env["srv"]
    routes = list(srv.ROUTES)
    i = routes.index(("POST", r"/api/jobs", "h_job_create", "/api/jobs"))
    assert routes[i + 1] == ("POST", r"/api/jobs/seed-folder", "h_seed_folder", "/api/jobs/seed-folder")
    assert len(srv.ROUTES) == 57
    assert srv.MovieUIHandler.h_seed_folder is srv._h_seed_folder
    for token in (None, "wrong-token"):
        assert mt.api(s, "POST", "/api/jobs/seed-folder", body={}, token=token)[::2] == (
            401, {"error": "missing or invalid token"})
    assert mt.api(s, "GET", "/api/jobs/seed-folder")[::2] == (405, {"error": "method not allowed"})


# --- SDT28 (SD39): the character taken set --------------------------------------------------------

def test_sdt28_the_character_taken_set(env, monkeypatch):
    s, ws, state = env["srv"], env["ws"], env["state"]
    assert seedfolder.character_taken_names(["Kyra", ".triggers"], ["Zed", None]) == {"kyra", ".triggers", "zed"}
    library = os.path.join(ws, "generated", "characters")
    os.makedirs(os.path.join(library, "kyra"))
    with open(os.path.join(library, "nova"), "w") as f:
        f.write("x")
    os.symlink(os.path.join(library, "missing"), os.path.join(library, "ghost"))
    _character_job(state, ws, "character-create", "zed")
    _character_job(state, ws, "character-train", "yon", "running")
    _character_job(state, ws, "character-create", "old", "done")
    _character_job(state, env["tmp"], "character-create", "far")
    assert srv.character_taken(s.server, ws) == {"kyra", "nova", "ghost", "zed", "yon"}
    other = os.path.join(env["tmp"], "lib")
    os.makedirs(os.path.join(other, "lena"))
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", other)
    assert srv.character_taken(s.server, ws) == {"lena", "zed", "yon"}


# --- SDT29 (SD41): the Characters route and its token -----------------------------------------------

def test_sdt29_the_characters_route_and_its_token(env):
    s, ws = env["srv"], env["ws"]
    routes = list(srv.ROUTES)
    i = routes.index(("POST", r"/api/characters", "h_character_create", "/api/characters"))
    assert routes[i + 1] == ("POST", r"/api/characters/seed-folder", "h_character_seed_folder",
                             "/api/characters/seed-folder")
    assert len(srv.ROUTES) == 57
    assert srv.MovieUIHandler.h_character_seed_folder is srv._h_character_seed_folder
    for token in (None, "wrong-token"):
        assert mt.api(s, "POST", "/api/characters/seed-folder", body={}, token=token)[::2] == (
            401, {"error": "missing or invalid token"})
    status, _h, data = mt.api(s, "GET", "/api/characters/seed-folder?ws=" + ws)
    assert (status, data["error"]) == (502, "character printed unparsable output")


# --- SDT30 (SD43): malformed Characters requests get 400 ------------------------------------------

def test_sdt30_malformed_character_requests_get_400(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["a.png"])
    good = _cbody(ws, seeds, True)
    no_ws = dict(good)
    del no_ws["ws"]
    cases = [
        (no_ws, "missing ws"),
        (dict(good, phrase=""), "phrase is required"),
        (dict(good, seed=-1), "seed must be an integer from 0 to 2147483647"),
        (dict(good, name="Temple"), CPREFIX_MSG),
        (dict(good, name="p" * 13), CPREFIX_MSG),
        (dict(good, seeds=[]), SEEDS_MSG),
        (dict(good, seeds=["a.png"]), "seed 1 must be an object"),
        (dict(good, seeds=[{"name": "x/a.png", "upload_id": seeds[0]["upload_id"]}]),
         "seed 1: name must be a string without '/'"),
        (dict(good, preview="yes"), PREVIEW_MSG),
        (dict(good, phrase="", seeds=[]), "phrase is required"),
    ]
    for body, message in cases:
        assert _cpost(s, body)[::2] == (400, {"error": message}), message
    assert _nothing_created(state)


# --- SDT31 (SD44, SD46): a Characters preview creates nothing ----------------------------------------

def test_sdt31_a_characters_preview_creates_nothing(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["Kyra.png", "Old Man #2.webp", "01_hero.png"])
    status, _h, data = _cpost(s, _cbody(ws, seeds, True))
    assert status == 200, data
    assert set(data) == {"ok", "shared_checks", "queued", "refused", "run", "seeds"}
    assert (data["ok"], data["queued"], data["run"], data["shared_checks"], data["refused"]) == (
        True, 0, None, [], 0)
    assert [r["character"] for r in data["seeds"]] == ["kyra", "old-man-2", "hero"]
    for row in data["seeds"]:
        assert set(row) == {"name", "upload_id", "character", "status", "reason", "checks", "job"}
        assert [c["id"] for c in row["checks"]] == ["V1"]
        assert (row["status"], row["job"]) == ("ok", None)
    assert _nothing_created(state)
    assert not os.path.exists(os.path.join(ws, "generated", "characters"))


# --- SDT32 (SD42, SD44, SD45): queue character-create jobs in seed order -----------------------------

def _queue_three_characters(env):
    s, ws = env["srv"], env["ws"]
    names = ["Kyra.png", "Old Man #2.webp", "01_hero.png"]
    seeds = _seeds(s, names)
    status, _h, data = _cpost(s, _cbody(ws, seeds, False, class_noun="woman", descriptor="x",
                                        trigger="kyrax", force=True))
    assert status == 201, data
    return names, seeds, data


def test_sdt32_queue_character_create_jobs_in_seed_order(env):
    ws, state = env["ws"], env["state"]
    _names, seeds, data = _queue_three_characters(env)
    assert data["queued"] == 3
    queue = lib.read_queue(state)
    assert len(queue) == 3 and queue == [r["job"]["id"] for r in data["seeds"]]
    for job_id, name, seed in zip(queue, ["kyra", "old-man-2", "hero"], seeds):
        job = _job(state, job_id)
        assert (job["kind"], job["story_id"], job["character"]) == ("character-create", None, name)
        fields = job["fields"]
        assert set(fields) == {"name", "phrase", "class_noun", "descriptor", "trigger", "seed", "seed_upload",
                               "force", "ws", "seed_folder"}
        assert (fields["class_noun"], fields["descriptor"], fields["trigger"], fields["force"]) == (
            None, None, None, False)
        argv = job["argv"]
        assert argv == lib.character_argv("character-create", fields, ws, state)
        assert argv[argv.index("--phrase") + 1] == "the stranger"
        assert argv[argv.index("--seed-image") + 1] == _upload_path(state, seed)
        assert argv[argv.index("--seed") + 1] == "7"
        for flag in ("--class", "--descriptor", "--trigger", "--force"):
            assert flag not in argv, flag


# --- SDT33 (SD44, SD46): refused Characters rows ------------------------------------------------------

def test_sdt33_refused_character_rows(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    unknown = "f" * 64 + ".png"
    bad = [{"name": "a.png", "upload_id": unknown}, {"name": "b.png", "upload_id": ""},
           {"name": "c.png", "upload_id": 7}]
    want = [("refused", "seed image upload %s not found" % unknown), ("refused", "seed image upload missing"),
            ("refused", "seed image upload missing")]
    status, _h, data = _cpost(s, _cbody(ws, bad, False))
    assert status == 409, data
    assert (data["run"], data["queued"], data["refused"]) == (None, 0, 3)
    assert [(r["status"], r["reason"]) for r in data["seeds"]] == want
    assert _nothing_created(state)
    good = _seeds(s, ["d.png"])
    status, _h, data = _cpost(s, _cbody(ws, bad + good, False))
    assert status == 201, data
    assert (data["queued"], data["refused"]) == (1, 3)
    assert [(r["status"], r["reason"]) for r in data["seeds"]] == want + [("ok", None)]
    assert lib.read_queue(state) == [data["seeds"][3]["job"]["id"]]


# --- SDT34 (SD39, SD44): final names avoid new characters and busy jobs --------------------------------

def test_sdt34a_a_character_made_between_preview_and_queue(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["kyra.png"])
    assert _cpost(s, _cbody(ws, seeds, True))[2]["seeds"][0]["character"] == "kyra"
    os.makedirs(os.path.join(ws, "generated", "characters", "kyra"))
    status, _h, data = _cpost(s, _cbody(ws, seeds, False))
    assert status == 201, data
    assert data["seeds"][0]["character"] == "kyra-2"
    assert _job(state, data["seeds"][0]["job"]["id"])["character"] == "kyra-2"


def test_sdt34b_a_queued_character_job_takes_its_name(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    _character_job(state, ws, "character-create", "nova")
    status, _h, data = _cpost(s, _cbody(ws, _seeds(s, ["nova.png"]), False))
    assert status == 201, data
    assert data["seeds"][0]["character"] == "nova-2"


def test_sdt34c_the_same_image_twice(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    seeds = _seeds(s, ["kyra.png", "kyra.png"], same=True)
    status, _h, data = _cpost(s, _cbody(ws, seeds, False))
    assert status == 201, data
    assert [r["character"] for r in data["seeds"]] == ["kyra", "kyra-2"]
    assert len(lib.read_queue(state)) == 2


# --- SDT35 (SD23, SD46): the tag on character jobs -----------------------------------------------------

def test_sdt35_the_seed_folder_tag_on_character_jobs(env):
    s, state = env["srv"], env["state"]
    names, _seeds_sent, data = _queue_three_characters(env)
    run = data["run"]
    assert seedfolder.RUN_ID_RE.fullmatch(run)
    for row, name in zip(data["seeds"], names):
        assert _job(state, row["job"]["id"])["fields"]["seed_folder"] == {"run": run, "name": name}
    queued = mt.api(s, "GET", "/api/jobs")[2]["queued"]
    assert [(j["seed_folder"], j["character"]) for j in queued] == [
        ({"run": run, "name": n}, c) for n, c in zip(names, ["kyra", "old-man-2", "hero"])]


# --- SDT36 (SD43, SD45, SD46): POST /api/characters is unchanged ----------------------------------------

def test_sdt36_post_api_characters_is_unchanged(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    body = {"ws": ws, "name": "kyra", "phrase": "", "seed": -1, "descriptor": "a tall man", "class_noun": "man"}
    status, _h, data = mt.api(s, "POST", "/api/characters", body=body)
    assert (status, data["error"], data["errors"]) == (
        400, "invalid fields", ["phrase is required", "seed must be an integer from 0 to 2147483647"])
    status, _h, data = mt.api(s, "POST", "/api/characters", body=dict(body, phrase="the stranger", seed=7))
    assert status == 201, data
    assert data["job"]["kind"] == "character-create"
    status, _h, data = _cpost(s, _cbody(ws, _seeds(s, ["nova.png"]), False))
    assert status == 201, data
    fields = _job(state, data["seeds"][0]["job"]["id"])["fields"]
    status, _h, data = mt.api(s, "POST", "/api/characters", body=dict(fields, force=True))
    assert status == 201, data
    forced = _job(state, data["job"]["id"])["fields"]
    assert "seed_folder" not in forced and forced["force"] is True


# --- Review Focus 1: phone and camera exports in Characters folder mode ---------------------------------

def test_sf_review_focus_1_timestamp_and_non_latin_names_as_characters(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    names = ["20241101_123456.jpg", "20241101_123457.jpg", "日本.png", "Café ☕ día.png"]
    status, _h, data = _cpost(s, _cbody(ws, _seeds(s, names), False))
    assert status == 201, data
    assert [r["character"] for r in data["seeds"]] == ["char", "char-2", "char-3", "cafe-dia"]
    for row, name in zip(data["seeds"], names):
        job = _job(state, row["job"]["id"])
        assert job["argv"][job["argv"].index("create") + 1] == row["character"]
        assert job["fields"]["seed_folder"]["name"] == name
    queued = mt.api(s, "GET", "/api/jobs")[2]["queued"]
    assert [j["seed_folder"]["name"] for j in queued] == names
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedfolder.py 2>&1 | tail -1
```

Expected: `13 failed, 62 passed`. `POST /api/characters/seed-folder` answers 405 (only `GET /api/characters/<name>` matches), SDT11 and SDT29 find 56 routes, SDT28 finds no `srv.character_taken`, and SDT36 passes its first two `POST /api/characters` checks but fails at the seed-folder request.

- [ ] **Step 3: Implement.**

**3.1.** The route (SD41). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    ("POST", r"/api/characters", "h_character_create", "/api/characters"),
```

with:

```python
    ("POST", r"/api/characters", "h_character_create", "/api/characters"),
    ("POST", r"/api/characters/seed-folder", "h_character_seed_folder", "/api/characters/seed-folder"),
```

**3.2.** `_phrase_errors` and `_seed_number_errors` (SD43). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
PHRASE_MAX = 200


def character_create_errors(body, state):
```

with:

```python
PHRASE_MAX = 200


def _phrase_errors(phrase):
    """MU65's phrase rule, moved out of character_create_errors unchanged (seed-folder SD43):
    [] or the one failing message."""
    if not (isinstance(phrase, str) and 1 <= len(phrase.strip()) and len(phrase) <= PHRASE_MAX
            and "\n" not in phrase and "\r" not in phrase):
        return ["phrase is required"]
    if not lib._argv_safe(phrase):
        return ["phrase contains invalid characters"]
    if phrase.strip().startswith("-"):
        return ["phrase must not start with '-'"]
    return []


def _seed_number_errors(seed_n):
    """MU65's seed-number rule, moved out of character_create_errors unchanged (seed-folder
    SD43): [] or the one failing message."""
    if seed_n is not None and not (isinstance(seed_n, int) and not isinstance(seed_n, bool) and 0 <= seed_n <= 2147483647):
        return ["seed must be an integer from 0 to 2147483647"]
    return []


def character_create_errors(body, state):
```

**3.3.** The phrase block calls `_phrase_errors` (SD43). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    if not (isinstance(phrase, str) and 1 <= len(phrase.strip()) and len(phrase) <= PHRASE_MAX
            and "\n" not in phrase and "\r" not in phrase):
        errors.append("phrase is required")
    elif not lib._argv_safe(phrase):
        errors.append("phrase contains invalid characters")
    elif phrase.strip().startswith("-"):
        errors.append("phrase must not start with '-'")
```

with:

```python
    errors += _phrase_errors(phrase)
```

**3.4.** The seed-number check calls `_seed_number_errors` (SD43). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    if seed_n is not None and not (isinstance(seed_n, int) and not isinstance(seed_n, bool) and 0 <= seed_n <= 2147483647):
        errors.append("seed must be an integer from 0 to 2147483647")
```

with:

```python
    errors += _seed_number_errors(seed_n)
```

**3.5.** `_character_job_locked` (SD45). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
def create_character_job(server, kind, real, fields):
    with STORE_LOCK:
        job_id = lib.new_job_id(server.state)
        argv = lib.character_argv(kind, fields, real, server.state)
        lib.create_job(server.state, job_id, kind, real, None, fields["name"], argv, fields)
    return 201, {"job": job_summary(server, job_id, lib.read_queue(server.state))}
```

with:

```python
def _character_job_locked(server, kind, real, fields):
    """Create the queued job of a character action and return its ID (seed-folder SD45). The
    caller holds STORE_LOCK."""
    job_id = lib.new_job_id(server.state)
    argv = lib.character_argv(kind, fields, real, server.state)
    lib.create_job(server.state, job_id, kind, real, None, fields["name"], argv, fields)
    return job_id


def create_character_job(server, kind, real, fields):
    with STORE_LOCK:
        job_id = _character_job_locked(server, kind, real, fields)
    return 201, {"job": job_summary(server, job_id, lib.read_queue(server.state))}
```

**3.6.** The Characters seed-folder section (SD39, SD42-SD46). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    fields["ws"] = real
    return create_character_job(self.server, "character-create", real, fields)
```

with:

```python
    fields["ws"] = real
    return create_character_job(self.server, "character-create", real, fields)


# ---------------------------------------------------------------------------
# Seed-folder Characters (docs/superpowers/specs/2026-11-01-seed-folder-compose-design.md, 3.5)
# ---------------------------------------------------------------------------

def character_taken(server, ws_real):
    """SD39: the names a seed's character must avoid."""
    library = os.environ.get("CHARACTER_LIBRARY_DIR") or os.path.join(ws_real, "generated", "characters")
    try:
        names = os.listdir(library)
    except OSError:
        names = []
    state, queue = server.state, lib.read_queue(server.state)
    busy = [job["character"] for job in (server.job(i) for i in lib.list_job_ids(state))
            if job is not None and job.get("workspace") == ws_real and isinstance(job.get("character"), str)
            and lib.job_state(state, job["id"], queue) in ("queued", "starting", "running")]
    return seedfolder.character_taken_names(names, busy)


def _character_rows(server, real, body, clean):
    """SD44 steps 1-2 for every seed of a validated request, with no lock held. One row per seed,
    in request order: {"name", "upload_id", "character" (provisional), "v1", "status", "reason"}."""
    seeds = clean["seeds"]
    names = seedfolder.assign_character_names([s["name"] for s in seeds], clean["prefix"],
                                              character_taken(server, real))           # step 1
    rows = []
    for seed, name in zip(seeds, names):                                               # step 2
        upload_id = seed["upload_id"]
        if not (isinstance(upload_id, str) and upload_id):
            errors = ["seed image upload missing"]
        else:
            errors = character_create_errors(
                {"name": name, "phrase": body.get("phrase"), "seed": body.get("seed"), "seed_upload": upload_id,
                 "class_noun": None, "descriptor": None, "trigger": None, "force": False}, server.state)
        rows.append({"name": seed["name"], "upload_id": upload_id, "character": name,
                     "v1": lib.check("V1", "fields", "fail" if errors else "pass", "\n".join(errors)),
                     "status": "refused" if errors else "ok", "reason": "; ".join(errors) if errors else None})
    return rows


def _character_response(server, rows, run=None, job_ids=None):
    """SD46: SD21's shape with "character" for "story_id", checks [V1] and shared_checks []."""
    job_ids = job_ids or {}
    queue = lib.read_queue(server.state) if job_ids else []
    seeds = []
    for i, row in enumerate(rows):
        seeds.append({"name": row["name"], "upload_id": row["upload_id"], "character": row["character"],
                      "status": row["status"], "reason": row["reason"], "checks": [row["v1"]],
                      "job": job_summary(server, job_ids[i], queue) if i in job_ids else None})
    return {"ok": any(row["status"] == "ok" for row in rows), "shared_checks": [],
            "queued": len(job_ids), "refused": sum(1 for row in rows if row["status"] != "ok"),
            "run": run, "seeds": seeds}


def _h_character_seed_folder(self, groups, query, body):
    """POST /api/characters/seed-folder (SD41-SD46): check every seed, then answer a preview (200)
    or queue one character-create job per ok seed, in seed order (201; 409 when no seed is ok)."""
    server = self.server
    real = self.ws(body.get("ws"))
    for errors in (_phrase_errors(body.get("phrase")), _seed_number_errors(body.get("seed"))):
        if errors:
            raise ApiError(400, errors[0])
    clean, error = seedfolder.validate_character_request(body)
    if error is not None:
        raise ApiError(400, error)
    rows = _character_rows(server, real, body, clean)
    if clean["preview"]:
        return 200, _character_response(server, rows)
    ok = [i for i, row in enumerate(rows) if row["status"] == "ok"]
    if not ok:
        return 409, _character_response(server, rows)
    run = seedfolder.new_run_id()
    created = []
    with STORE_LOCK:
        final = seedfolder.assign_character_names([rows[i]["name"] for i in ok], clean["prefix"],
                                                  character_taken(server, real))
        for i, name in zip(ok, final):
            fields = {"name": name, "phrase": body.get("phrase"), "class_noun": None, "descriptor": None,
                      "trigger": None, "seed": body.get("seed"), "seed_upload": rows[i]["upload_id"],
                      "force": False, "ws": real, "seed_folder": {"run": run, "name": rows[i]["name"]}}
            created.append((i, name, _character_job_locked(server, "character-create", real, fields)))
    job_ids = {}
    for i, name, job_id in created:
        rows[i]["character"] = name
        job_ids[i] = job_id
    return 201, _character_response(server, rows, run, job_ids)
```

**3.7.** The handler (SD41). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
MovieUIHandler.h_character_create = _h_character_create
```

with:

```python
MovieUIHandler.h_character_create = _h_character_create
MovieUIHandler.h_character_seed_folder = _h_character_seed_folder
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedfolder.py 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_http.py::test_mu64_mu65_character_endpoints tests/test_movie_ui_http.py::test_mu65_character_create_errors_flaglike_and_unsafe tests/test_movie_ui_http.py::test_fix13_character_empty_seed_upload_is_none 2>&1 | tail -1
```

Expected: `75 passed`, then `3 passed` (the existing Characters endpoint and error-order tests are unchanged). Run the compile check with `FILES` = `movie_ui_server.py tests/test_movie_ui_seedfolder.py`; expected: `compiled 2` twice. Then run the gate block with `N=4`. Expected: `GATE PASS`, `lost 5 (listed 5, unexpected 0)` (the same five `T3` lines), `new tests 75, not passing 0`, all the baseline failures still failing, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
git add movie_ui_server.py tests/test_movie_ui_seedfolder.py
git diff --cached --name-only    # expected: those 2 paths
git commit -m "feat(movie-ui): POST /api/characters/seed-folder: one character-create job per seed, with _character_job_locked, _phrase_errors and _seed_number_errors (SD39, SD41-SD46; SDT11, SDT28-SDT36)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The page, part 1: the shared folder code and Compose Seed folder (SD26-SD35, SD50; SDT25, Review Focus 5)

This task implements, in `index.html` (SD26) and `app.js`:
- SD27 `FOLDER_BOXES` (both boxes, verbatim, directly after `S`; `S` gains no folder fields) and `part`; the Compose wiring of the four listeners in `setupCompose`.
- The shared, box-parameterised functions, one copy each (SD50): `onFolderPick(box)` (SD27), `uploadFolder(box, seq)`, `renderFolderList(box)` and `uploadedSeeds(box)` (SD28; Plan rulings PR3, PR4), `folderBlock(box)` (SD29), `openFolderConfirm(box, base)`, `folderResult(box, row, seed)` and `folderError(res)` (SD31; Plan rulings PR11, PR12), `renderFolderTable(box)` (SD32), `queueFolder(box)` and `closeFolderConfirm(box)` (SD33).
- SD29 Compose folder mode (`folderMode`, `updateComposeButtons`, `composeFields`'s `byFolder`), SD30 the command preview (`sampleStoryId`, verbatim), SD31's Write story and Run all branches, SD34 `seedTag` and the Jobs cells.
- SD35: `onSeedFile`, `fillCompose`, the Size and Seed image options, the Batches page and `app.css` are unchanged. The lines `test_ct27`, `test_vl26` and `test_lu13` pin (including `check_seams: $("#c-mode").value === "chained" && $("#c-check-seams").checked` and `gate($("#c-write-story"), $("#c-write-story-reason"), []);`) are unchanged.
- The `characters` box is defined here but used only from Task 6 (its `mode()` reads `#ch-folder-mode`, which Task 6 adds; nothing calls it before then).

Tests: SDT25 and Review Focus 5, appended to `tests/test_movie_ui_seedfolder.py`.

**Files:**
- Modify (at a9d5aa1): `static/movie-ui/index.html`: the Story ID label `:47`, after `c-seed-status` `:83`, after `c-smoke-check` `:141`; `static/movie-ui/app.js`: `LEVEL_LABELS` `:10`, `S` `:14-15`, `composeFields` `:372-382`, `preview` `:414-415`, `updateComposeButtons` `:470-476`, the end of `onSeedFile` `:493-497` (the folder functions are inserted after it), `setupCompose` `:560` and `:581-584`, `jobLabel` `:1935-1937`, `pollJobsOnce` `:2060-2061`, `:2072-2074`, `:2082-2083`, `:2090`; `tests/test_movie_ui_seedfolder.py` (append after Review Focus 1).
- Read only: `app.js`: `el` `:21-33`, `api` `:76-102`, `gate` `:462-468`, `uploadFile` `:478-483`, `fillCompose` `:499-550`, `showTab` `:289-301`, `updateCharacterButtons` `:1508-1516`, `selectJob` `:2017`, `pollJobs` `:2029`; `index.html`: the Jobs tables `:342`, `:344`.

**Interfaces:**
- Consumes: Task 3's `POST /api/jobs/seed-folder` (the SD21 body; 400 `{"error"}`), the summaries' `seed_folder` (`{"run", "name"}` or null) in `GET /api/jobs`. Existing page functions: `uploadFile(file) -> Promise<upload_id>` (throws `Error` with the server's `error` or `upload failed: http <status>`), `composeFields(action) -> object`, `api(method, path, body) -> Promise<{status, data}>` (`data` is null for a non-JSON answer), `el`, `clear`, `show`, `gate`, `selectJob(id)`, `pollJobs() -> Promise`, `showTab(name)`, `preview()` (debounced), `updateCharacterButtons()`.
- Produces, in `app.js`: `SEEDS_MAX`, `SEED_TYPES`, `SEED_COLLATOR`; `FOLDER_BOXES.compose` and `FOLDER_BOXES.characters` (`{ids, endpoint, idKey, shared, mode(), select(), refresh(), folder, seq, body, rows, busy}`; `folder` is `{files: [{name, file, state, upload_id, reason}], uploading}` or null; `rows` is `[{name, id, status, result, job, sent}]` or null); `part(box, name) -> Element`; `folderMode() -> boolean`, `sampleStoryId(name, prefix) -> string`, `onFolderPick(box)`, `uploadFolder(box, seq) -> Promise`, `renderFolderList(box)`, `uploadedSeeds(box) -> [file]`, `folderBlock(box) -> string or null`, `folderResult(box, row, seed)`, `folderError(res) -> string`, `renderFolderTable(box)`, `openFolderConfirm(box, base) -> Promise`, `queueFolder(box) -> Promise`, `closeFolderConfirm(box)`, `seedTag(job) -> Element or null`. Task 6 uses `FOLDER_BOXES.characters`, `part`, `onFolderPick`, `renderFolderList`, `folderBlock`, `openFolderConfirm`, `queueFolder` and `closeFolderConfirm`.

- [ ] **Step 1: Write the failing tests.**

Edit `tests/test_movie_ui_seedfolder.py`: replace this text, which occurs exactly once:

```python
    status, _h, data = _post(s, _body(ws, seeds, False))
    assert status == 409, data
    assert _nothing_created(state)
```

with:

```python
    status, _h, data = _post(s, _body(ws, seeds, False))
    assert status == 409, data
    assert _nothing_created(state)


# --- SDT25 (SD26-SD35, SD50): the static page, Compose and the shared folder code ------------------

NEW_IDS = ("c-story-id-label", "c-res-folder", "c-folder-choose", "c-folder-file", "c-folder-status",
           "c-folder-list", "c-folder-confirm", "c-folder-shared", "c-folder-summary", "c-folder-table",
           "c-folder-queue", "c-folder-cancel")
JS_TEXTS = ('"/api/jobs/seed-folder"', 'new Intl.Collator("en", {numeric: true})',
            "function sampleStoryId(name, prefix)", '"Story ID prefix (optional)"',
            '"not available for a seed folder"', '"upload failed: "', '"seed folder "', '" · "', '"Queue "',
            "const FOLDER_BOXES = {", "function part(box, name)")
SHARED_FUNCTIONS = ("onFolderPick", "openFolderConfirm", "queueFolder", "closeFolderConfirm",
                    "renderFolderTable", "renderFolderList")


def _static_texts():
    static = os.path.join(WS, "static", "movie-ui")
    texts = {}
    for name in ("index.html", "app.js", "app.css"):
        with open(os.path.join(static, name), encoding="utf-8") as f:
            texts[name] = f.read()
    return static, texts


def test_sdt25_the_static_page():
    static, texts = _static_texts()
    html, js = texts["index.html"], texts["app.js"]
    for element in NEW_IDS:
        assert html.count('id="%s"' % element) == 1, element
    for element in ("c-story-id-label", "c-res-folder"):
        assert '"#%s' % element in js, element
    assert 'ids: "c-folder"' in js and 'ids: "ch-folder"' in js
    assert "webkitdirectory" in html
    assert "<th>File</th><th>Story ID</th><th>Result</th><th>Job</th>" in html
    for text in JS_TEXTS:
        assert text in js, text
    for name in SHARED_FUNCTIONS:
        assert js.count("function %s(box" % name) == 1, name
        assert js.count("function %s(" % name) == 1, name
    for name, text in texts.items():
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\balert\(", r"\bconfirm\(",
                        r"\bprompt\(", r"\beval\(", r"new Function"):
            assert not re.search(pattern, text), (name, pattern)
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")],
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr


# --- Review Focus 5: the page's sample story ID matches the server's rules ------------------------------

SAMPLE_CASES = [("beach.png", ""), ("Beach Day!.webp", "temple"), ("__01.png", ""), ("日本.png", ""),
                ("Beach Day.final.png", ""), ("Café.png", ""), ("a..b.png", ""), ("a -- b.png", ""),
                (".png", ""), ("a" * 100 + ".png", P40), ("a" * 77 + "-bc.png", ""), ("ﬁx.png", "Temple"),
                ("a\tb.png", ""), ("", ""), ("...", ""), ("-_-.png", "x"), ("x.tar.gz", ""),
                ("Straße ☕.jpg", ""), ("\U0001F600 smile.png", ""), ("Café ☕ día.png", "temple")]


def test_sf_review_focus_5_the_page_sample_id_matches_the_server(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    with open(os.path.join(WS, "static", "movie-ui", "app.js"), encoding="utf-8") as f:
        js = f.read()
    start = js.index("  function sampleStoryId(name, prefix) {")
    end = js.index("\n  }\n", start) + len("\n  }\n")
    script = js[start:end] + (
        "process.stdout.write(JSON.stringify(%s.map(function (c) { return sampleStoryId(c[0], c[1]); })));\n"
        % json.dumps(SAMPLE_CASES))
    path = os.path.join(str(tmp_path), "sample.js")
    with open(path, "w", encoding="utf-8") as f:
        f.write(script)
    proc = subprocess.run([node, path], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    want = [seedfolder.story_id_for(seedfolder.seed_stem(name), prefix, set()) for name, prefix in SAMPLE_CASES]
    assert json.loads(proc.stdout) == want
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedfolder.py::test_sdt25_the_static_page tests/test_movie_ui_seedfolder.py::test_sf_review_focus_5_the_page_sample_id_matches_the_server 2>&1 | tail -1
```

Expected: `2 failed` (`c-story-id-label` is not in the page; `function sampleStoryId` is not in `app.js`, so `js.index` raises `ValueError`).

- [ ] **Step 3: Implement.**

**3.1.** The Story ID label (SD26). Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
    <label data-field="story_id">Story ID <input id="c-story-id" type="text" size="30"></label>
```

with:

```html
    <label data-field="story_id"><span id="c-story-id-label">Story ID</span> <input id="c-story-id" type="text" size="30"></label>
```

**3.2.** The Seed folder choice (SD26). Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
      <span id="c-seed-status" class="muted"></span>
```

with:

```html
      <span id="c-seed-status" class="muted"></span>
      <label data-field="seed_upload"><input id="c-res-folder" type="radio" name="c-res" value="folder"> Seed folder
        <button id="c-folder-choose" type="button">Choose folder…</button>
        <input id="c-folder-file" type="file" webkitdirectory hidden></label>
      <span id="c-folder-status" class="muted"></span>
      <ul id="c-folder-list" class="muted" hidden></ul>
```

**3.3.** The confirm table (SD26). Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
  <div id="c-smoke-check" hidden></div>
```

with:

```html
  <div id="c-smoke-check" hidden></div>
  <div id="c-folder-confirm" hidden>
    <h3>Seed folder</h3>
    <ul id="c-folder-shared" class="checks"></ul>
    <p id="c-folder-summary" class="muted"></p>
    <table id="c-folder-table" class="list"><thead><tr><th>File</th><th>Story ID</th><th>Result</th><th>Job</th></tr></thead><tbody></tbody></table>
    <div class="row">
      <button id="c-folder-queue" type="button" disabled>Queue 0 jobs</button>
      <button id="c-folder-cancel" type="button">Cancel</button>
    </div>
  </div>
```

**3.4.** The constants (spec 1.1). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
  const LEVEL_LABELS = {render: "Render", stills: "New stills", replan: "Re-plan"};
```

with:

```js
  const LEVEL_LABELS = {render: "Render", stills: "New stills", replan: "Re-plan"};
  const SEEDS_MAX = 100;   // seed-folder spec 1.1: the most seeds in one run
  const SEED_TYPES = ["image/png", "image/jpeg", "image/webp"];
  const SEED_COLLATOR = new Intl.Collator("en", {numeric: true});
```

**3.5.** `FOLDER_BOXES` and `part` (SD27). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    logBuffer: "", logLines: [], bannerKind: null, stopped: false, recentSeq: 0, trace: null, traceAgent: null, agents: [], recent: [], timers: {}
  };
```

with:

```js
    logBuffer: "", logLines: [], bannerKind: null, stopped: false, recentSeq: 0, trace: null, traceAgent: null, agents: [], recent: [], timers: {}
  };
  // Seed-folder spec SD27: one state box per folder mode (Compose and Characters); part(box, name)
  // is the box's element <ids>-<name>.
  const FOLDER_BOXES = {
    compose: {ids: "c-folder", endpoint: "/api/jobs/seed-folder", idKey: "story_id", shared: true,
              mode: function () { return $("#c-res-folder").checked; },
              select: function () { $("#c-res-folder").checked = true; },
              refresh: function () { updateComposeButtons(); preview(); },
              folder: null, seq: 0, body: null, rows: null, busy: false},
    characters: {ids: "ch-folder", endpoint: "/api/characters/seed-folder", idKey: "character", shared: false,
                 mode: function () { return $("#ch-folder-mode").checked; },
                 select: function () { $("#ch-folder-mode").checked = true; },
                 refresh: function () { updateCharacterButtons(); },
                 folder: null, seq: 0, body: null, rows: null, busy: false}
  };
  function part(box, name) { return $("#" + box.ids + "-" + name); }
```

**3.6.** `composeFields` (SD29). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    const bySeed = $("#c-res-seed").checked;
    const supported = (S.options && S.options.supported) || {};
    const goal = textOrNull("#c-goal");
    return {
      ws: S.ws, action: action || "story",
      story_id: $("#c-story-id").value.trim(), narrative: $("#c-narrative").value,
      goal: supported.goal === false ? null : goal,
      panels: byLength ? null : numberOrNull("#c-panels"),
      length: byLength ? numberOrNull("#c-length") : null,
      fps: numberOrNull("#c-fps"), frames: numberOrNull("#c-frames"),
      width: bySeed ? null : numberOrNull("#c-width"), height: bySeed ? null : numberOrNull("#c-height"),
```

with:

```js
    const bySeed = $("#c-res-seed").checked;
    const byFolder = $("#c-res-folder").checked;
    const supported = (S.options && S.options.supported) || {};
    const goal = textOrNull("#c-goal");
    return {
      ws: S.ws, action: action || "story",
      story_id: $("#c-story-id").value.trim(), narrative: $("#c-narrative").value,
      goal: supported.goal === false ? null : goal,
      panels: byLength ? null : numberOrNull("#c-panels"),
      length: byLength ? numberOrNull("#c-length") : null,
      fps: numberOrNull("#c-fps"), frames: numberOrNull("#c-frames"),
      width: bySeed || byFolder ? null : numberOrNull("#c-width"),
      height: bySeed || byFolder ? null : numberOrNull("#c-height"),
```

**3.7.** The command preview (SD30). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    const fields = composeFields(S.composeAction);
    $("#c-command-for").textContent = "(" + S.composeAction + ")";
```

with:

```js
    const fields = composeFields(S.composeAction);
    $("#c-command-for").textContent = "(" + S.composeAction + ")";
    if (folderMode()) {
      const first = uploadedSeeds(FOLDER_BOXES.compose)[0];
      fields.seed_upload = first ? first.upload_id : null;
      fields.story_id = sampleStoryId(first ? first.name : "seed", fields.story_id);
      $("#c-command-for").textContent = first
        ? "(" + S.composeAction + ", first seed " + first.name + ", sample story ID)"
        : "(" + S.composeAction + ", no seed uploaded yet)";
    }
```

**3.8.** `updateComposeButtons` (SD29). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
  function updateComposeButtons() {
    const mode = $("#c-mode").value;
    gate($("#c-run-all"), $("#c-run-all-reason"), mode === "no_stills" ? ["render"] : ["render", "stills"]);
    gate($("#c-write-story"), $("#c-write-story-reason"), []);
    gate($("#c-smoke"), $("#c-smoke-reason"), ["render"]);
    show($("#c-check-seams-box"), mode === "chained");
  }
```

with:

```js
  function updateComposeButtons() {
    const mode = $("#c-mode").value;
    gate($("#c-run-all"), $("#c-run-all-reason"), mode === "no_stills" ? ["render"] : ["render", "stills"]);
    gate($("#c-write-story"), $("#c-write-story-reason"), []);
    gate($("#c-smoke"), $("#c-smoke-reason"), ["render"]);
    show($("#c-check-seams-box"), mode === "chained");
    // Seed-folder spec SD29: the folder mode of the Compose buttons.
    const box = FOLDER_BOXES.compose;
    const folder = folderMode();
    $("#c-story-id-label").textContent = folder ? "Story ID prefix (optional)" : "Story ID";
    $("#c-validate").disabled = folder;
    renderFolderList(box);
    if (!folder) { closeFolderConfirm(box); return; }
    $("#c-smoke").disabled = true;
    $("#c-smoke-reason").textContent = "not available for a seed folder";
    const block = folderBlock(box);
    if (!block) { return; }
    [["#c-run-all", "#c-run-all-reason"], ["#c-write-story", "#c-write-story-reason"]].forEach(function (pair) {
      $(pair[0]).disabled = true;
      const reason = $(pair[1]);
      reason.textContent = reason.textContent ? reason.textContent + "; " + block : block;
    });
  }
```

**3.9.** The shared folder functions (SD27, SD28, SD30-SD33, SD50). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    } catch (err) {
      $("#c-seed-status").textContent = String(err.message);
    }
    preview();
  }
```

with:

```js
    } catch (err) {
      $("#c-seed-status").textContent = String(err.message);
    }
    preview();
  }

  // --- seed folder (docs/superpowers/specs/2026-11-01-seed-folder-compose-design.md, Section 4) ---
  // One copy of each function serves both FOLDER_BOXES (SD27-SD33, SD50).

  function folderMode() { return FOLDER_BOXES.compose.mode(); }

  function sampleStoryId(name, prefix) {
    const dot = name.lastIndexOf(".");
    let stem = (dot > 0 ? name.slice(0, dot) : name).normalize("NFKD").replace(/[^\x00-\x7F]/g, "");
    stem = stem.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/\.{2,}/g, ".").replace(/-{2,}/g, "-");
    stem = stem.replace(/^[^A-Za-z0-9]+/, "").replace(/[-._]+$/, "") || "seed";
    const head = prefix ? prefix + "-" : "";
    return head + stem.slice(0, Math.max(1, 80 - head.length)).replace(/[-._]+$/, "");
  }

  function onFolderPick(box) {
    box.seq += 1;
    const input = part(box, "file");
    const picked = Array.from(input.files);
    input.value = "";
    const files = picked.filter(function (f) {
      return (f.webkitRelativePath.match(/\//g) || []).length === 1 && SEED_TYPES.indexOf(f.type) >= 0 &&
        !f.name.startsWith(".");
    }).sort(function (a, b) { return SEED_COLLATOR.compare(a.name, b.name); });
    if (files.length === 0) {
      part(box, "status").textContent = "no PNG, JPEG or WebP images directly in this folder";
      box.folder = null;
    } else if (files.length > SEEDS_MAX) {
      part(box, "status").textContent = "found " + files.length + " images; at most " + SEEDS_MAX +
        " per run — pick a smaller folder";
      box.folder = null;
    } else {
      box.folder = {files: files.map(function (f) {
        return {name: f.name, file: f, state: "waiting", upload_id: null, reason: null};
      }), uploading: true};
      box.select();
      closeFolderConfirm(box);
      uploadFolder(box, box.seq);
    }
    renderFolderList(box);
    box.refresh();
  }

  async function uploadFolder(box, seq) {
    const folder = box.folder;
    const n = folder.files.length;
    for (let i = 0; i < n; i += 1) {
      if (seq !== box.seq) { return; }
      const item = folder.files[i];
      part(box, "status").textContent = "uploading " + (i + 1) + " of " + n + "…";
      item.state = "uploading";
      renderFolderList(box);
      try {
        const uploadId = await uploadFile(item.file);
        if (seq !== box.seq) { return; }
        item.state = "uploaded";
        item.upload_id = uploadId;
      } catch (err) {
        if (seq !== box.seq) { return; }
        item.state = "failed";
        item.reason = String(err.message).replace(/^upload failed: /, "");
      }
      renderFolderList(box);
      box.refresh();
    }
    folder.uploading = false;
    const uploaded = uploadedSeeds(box).length;
    const failed = folder.files.filter(function (f) { return f.state === "failed"; }).length;
    part(box, "status").textContent = "uploaded " + uploaded + " of " + n + " images" +
      (failed > 0 ? " (" + failed + " failed)" : "");
    renderFolderList(box);
    box.refresh();
  }

  function renderFolderList(box) {
    const list = clear(part(box, "list"));
    const visible = box.mode() && Boolean(box.folder);
    show(list, visible);
    if (!visible) { return; }
    box.folder.files.forEach(function (f) {
      const text = f.state === "uploading" ? "uploading…" : f.state === "failed" ? "upload failed: " + f.reason : f.state;
      list.appendChild(el("li", {text: f.name + " — " + text}));
    });
  }

  function uploadedSeeds(box) {
    return box.folder ? box.folder.files.filter(function (f) { return f.state === "uploaded"; }) : [];
  }

  function folderBlock(box) {
    if (!box.folder) { return "pick a seed folder"; }
    if (box.folder.uploading) { return "uploading seeds…"; }
    if (!uploadedSeeds(box).length) { return "no seed uploaded"; }
    return null;
  }

  function folderResult(box, row, seed) {
    row.id = seed[box.idKey];
    row.status = seed.status;
    row.result = seed.status === "ok" ? "OK" : seed.reason;
  }

  function folderError(res) {
    return (res.data && res.data.error) || ("http " + res.status);
  }

  function renderFolderTable(box) {
    const body = clear(part(box, "table").querySelector("tbody"));
    (box.rows || []).forEach(function (row) {
      body.appendChild(el("tr", {}, [el("td", {text: row.name}), el("td", {text: row.id || "—"}),
        el("td", {text: row.result}), el("td", {text: row.job || ""})]));
    });
  }

  async function openFolderConfirm(box, base) {
    const seeds = uploadedSeeds(box).map(function (f) { return {name: f.name, upload_id: f.upload_id}; });
    let sent = 0;
    const rows = (box.folder ? box.folder.files : []).map(function (f) {
      if (f.state === "uploaded") {
        sent += 1;
        return {name: f.name, id: null, status: null, result: "checking…", job: null, sent: sent - 1};
      }
      return {name: f.name, id: null, status: null, result: "upload failed: " + f.reason, job: null, sent: -1};
    });
    const body = Object.assign(base, {seeds: seeds, preview: true});
    box.body = body;
    box.rows = rows;
    show(part(box, "confirm"), true);
    if (box.shared) { clear(part(box, "shared")); }
    part(box, "summary").textContent = "checking " + seeds.length + " seeds…";
    part(box, "queue").disabled = true;
    renderFolderTable(box);
    const res = await api("POST", box.endpoint, body);
    if (box.body !== body) { return; }
    if (res.status !== 200) {
      part(box, "summary").textContent = folderError(res);
      rows.forEach(function (row) { if (row.result === "checking…") { row.result = "—"; } });
      renderFolderTable(box);
      return;
    }
    rows.forEach(function (row) { if (row.sent >= 0) { folderResult(box, row, res.data.seeds[row.sent]); } });
    if (box.shared) {
      const shared = clear(part(box, "shared"));
      res.data.shared_checks.forEach(function (c) {
        shared.appendChild(el("li", {cls: "check-" + c.status, text: c.status + " " + c.id + " " + c.name + ": " + c.detail}));
      });
      if (!res.data.shared_checks.length) {
        shared.appendChild(el("li", {text: "shared checks not run: no seed passed its field checks"}));
      }
    }
    const k = rows.filter(function (row) { return row.status === "ok"; }).length;
    const sharedFailed = box.shared && res.data.shared_checks.some(function (c) { return c.status === "fail"; });
    part(box, "summary").textContent = sharedFailed
      ? "shared checks failed: nothing can be queued" : k + " of " + rows.length + " seeds can be queued";
    part(box, "queue").textContent = "Queue " + k + (k === 1 ? " job" : " jobs");
    part(box, "queue").disabled = k === 0;
    renderFolderTable(box);
  }

  async function queueFolder(box) {
    const body = box.body;
    if (!body || box.busy) { return; }
    const sent = box.rows.filter(function (row) { return row.sent >= 0 && row.status === "ok"; });
    const request = Object.assign({}, body, {seeds: sent.map(function (row) { return body.seeds[row.sent]; }),
                                             preview: false});
    box.busy = true;
    part(box, "queue").disabled = true;
    part(box, "cancel").disabled = true;
    part(box, "summary").textContent = "checking and queueing " + sent.length + " seeds…";
    try {
      const res = await api("POST", box.endpoint, request);
      if (res.status === 201 || res.status === 409) {
        sent.forEach(function (row, i) {
          const seed = res.data.seeds[i];
          folderResult(box, row, seed);
          row.job = seed.job ? seed.job.id : "";
        });
        box.body = null;
        renderFolderTable(box);
        if (res.status === 201) {
          const q = res.data.queued;
          part(box, "summary").textContent = "queued " + q + (q === 1 ? " job" : " jobs");
          const first = res.data.seeds.filter(function (seed) { return seed.job; })[0];
          selectJob(first.job.id);
          await pollJobs();
          showTab("jobs");
        } else {
          part(box, "summary").textContent = "nothing was queued";
        }
      } else {
        part(box, "summary").textContent = folderError(res);
        part(box, "queue").disabled = false;
      }
    } finally {
      box.busy = false;
      part(box, "cancel").disabled = false;
    }
  }

  function closeFolderConfirm(box) {
    if (box.busy) { return; }
    show(part(box, "confirm"), false);
    if (box.shared) { clear(part(box, "shared")); }
    part(box, "summary").textContent = "";
    clear(part(box, "table").querySelector("tbody"));
    box.body = null;
    box.rows = null;
  }
```

**3.10.** The Compose folder listeners (SD27). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    $("#c-seed-file").addEventListener("change", onSeedFile);
```

with:

```js
    $("#c-seed-file").addEventListener("change", onSeedFile);
    const composeBox = FOLDER_BOXES.compose;
    part(composeBox, "choose").addEventListener("click", function () { part(composeBox, "file").click(); });
    part(composeBox, "file").addEventListener("change", function () { onFolderPick(composeBox); });
    part(composeBox, "queue").addEventListener("click", function () { queueFolder(composeBox); });
    part(composeBox, "cancel").addEventListener("click", function () { closeFolderConfirm(composeBox); });
```

**3.11.** Write story and Run all in folder mode (SD31). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    $("#c-write-story").addEventListener("click", function () { S.composeAction = "story"; submit(composeFields("story")); });
    $("#c-run-all").addEventListener("click", function () {
      S.composeAction = "movie";
      submit(Object.assign(composeFields("movie"),
```

with:

```js
    $("#c-write-story").addEventListener("click", function () {
      S.composeAction = "story";
      if (folderMode()) {
        openFolderConfirm(FOLDER_BOXES.compose, Object.assign(composeFields("story"), {check_seams: false}));
        return;
      }
      submit(composeFields("story"));
    });
    $("#c-run-all").addEventListener("click", function () {
      S.composeAction = "movie";
      if (folderMode()) {
        openFolderConfirm(FOLDER_BOXES.compose, Object.assign(composeFields("movie"),
          {check_seams: $("#c-mode").value === "chained" && $("#c-check-seams").checked}));
        return;
      }
      submit(Object.assign(composeFields("movie"),
```

**3.12.** `seedTag` (SD34). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
  function jobLabel(job) {
    return job.story_id || job.character || (job.kind === "smoke" ? "smoke render" : "-");
  }
```

with:

```js
  function jobLabel(job) {
    return job.story_id || job.character || (job.kind === "smoke" ? "smoke render" : "-");
  }

  function seedTag(job) {
    const sf = job.seed_folder;
    return sf ? el("span", {cls: "badge", text: "seed folder " + sf.run + " · " + sf.name}) : null;
  }
```

**3.13.** The running job's tag (SD34). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
      running.textContent = jobs.running.id + " " + jobs.running.kind + " " + jobLabel(jobs.running) + " - " +
        jobs.running.state + " - " + jobs.running.command;
```

with:

```js
      running.textContent = jobs.running.id + " " + jobs.running.kind + " " + jobLabel(jobs.running) + " - " +
        jobs.running.state + " - " + jobs.running.command;
      const runningTag = seedTag(jobs.running);
      if (runningTag) { running.appendChild(document.createTextNode(" ")); running.appendChild(runningTag); }
```

**3.14.** The queue row's tag (SD34). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    jobs.queued.forEach(function (job) {
      queue.appendChild(el("tr", {data: {jobId: job.id}}, [el("td", {text: String(job.queue_position)}),
        el("td", {text: job.id}), el("td", {text: job.kind}), el("td", {text: jobLabel(job)}),
```

with:

```js
    jobs.queued.forEach(function (job) {
      const tag = seedTag(job);
      queue.appendChild(el("tr", {data: {jobId: job.id}}, [el("td", {text: String(job.queue_position)}),
        el("td", {text: job.id}), el("td", {text: job.kind}), el("td", {}, tag ? [jobLabel(job), " ", tag] : [jobLabel(job)]),
```

**3.15.** The history row's tag, part 1 (SD34). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    jobs.history.forEach(function (job) {
      const actions = el("td");
```

with:

```js
    jobs.history.forEach(function (job) {
      const tag = seedTag(job);
      const actions = el("td");
```

**3.16.** The history row's tag, part 2 (SD34). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
        el("td", {text: jobLabel(job)}), actions]);
```

with:

```js
        el("td", {}, tag ? [jobLabel(job), " ", tag] : [jobLabel(job)]), actions]);
```

- [ ] **Step 4: Run the new tests, the syntax check, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedfolder.py 2>&1 | tail -1
node --check static/movie-ui/app.js && echo "node ok"
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seams.py::test_ct27_the_static_page tests/test_movie_ui_batch.py::test_bt13_the_static_page tests/test_location_ui.py::test_lu13_the_static_page tests/test_vlm_lifecycle.py::test_vl26_page_gate_and_warn_style tests/test_soft_panel_count.py::test_spt27_the_regenerate_target_is_wired_in_the_static_ui 2>&1 | tail -1
```

Expected: `77 passed`, `node ok`, then `5 passed` (the other static-page tests are unchanged). Run the compile check with `FILES` = `tests/test_movie_ui_seedfolder.py`; expected: `compiled 1` twice. Then run the gate block with `N=5`. Expected: `GATE PASS`, `lost 5 (listed 5, unexpected 0)` (the same five `T3` lines), `new tests 77, not passing 0`, all the baseline failures still failing, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
git add static/movie-ui/index.html static/movie-ui/app.js tests/test_movie_ui_seedfolder.py
git diff --cached --name-only    # expected: those 3 paths
git commit -m "feat(movie-ui): the shared seed-folder page code (FOLDER_BOXES) and Compose Seed folder: pick, uploads, confirm table, queue, and the Jobs tag (SD26-SD35, SD50; SDT25)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The page, part 2: Characters Seed folder (SD47-SD50; SDT37)

This task implements, in `index.html` (SD47) and `app.js`:
- SD48: `updateCharacterButtons` keeps its statements, then sets the Name label, disables `#ch-class`, `#ch-descriptor`, `#ch-trigger` and `#ch-seed-file` in folder mode, calls `renderFolderList(box)`, closes the table outside folder mode, and adds `folderBlock(box)` to `#ch-create-status` while disabling `#ch-create`.
- SD48 wiring in `setupCharacters`: `#ch-folder-mode`'s `change` calls `updateCharacterButtons`, plus SD27's four listeners for `FOLDER_BOXES.characters`.
- SD49: `createCharacter(force)` begins with the spec's folder-mode line, verbatim; the rest, including the force path, is unchanged.
- SD50: the list, detail, Accept, Regenerate, Train, "Create anyway (--force)" and single-image Create are unchanged.

Tests: SDT37, appended to `tests/test_movie_ui_seedfolder.py`.

**Files:**
- Modify (at a9d5aa1): `static/movie-ui/index.html`: the Name label `:211`, after the Seed image label `:217`, after the `ch-create` row `:219`; `static/movie-ui/app.js`: the end of `updateCharacterButtons` `:1512-1516`, `createCharacter` `:1518-1519`, `setupCharacters` `:1548`; `tests/test_movie_ui_seedfolder.py` (append after Review Focus 5).
- Read only: `app.js`: `createCharacter` `:1518-1544`, `setupCharacters` `:1546-1570`, `numberOrNull` `:137-141`; Task 5's folder functions.

**Interfaces:**
- Consumes: Task 4's `POST /api/characters/seed-folder` (the SD46 body); Task 5's `FOLDER_BOXES.characters`, `part`, `onFolderPick`, `renderFolderList`, `folderBlock`, `openFolderConfirm`, `queueFolder`, `closeFolderConfirm`; existing `numberOrNull(selector)`.
- Produces: the Characters folder-mode HTML elements (`ch-name-label`, `ch-folder-mode`, `ch-folder-choose`, `ch-folder-file`, `ch-folder-status`, `ch-folder-list`, `ch-folder-confirm`, `ch-folder-summary`, `ch-folder-table`, `ch-folder-queue`, `ch-folder-cancel`; no `ch-folder-shared`), and the folder branches of `updateCharacterButtons` and `createCharacter`.

- [ ] **Step 1: Write the failing test.**

Edit `tests/test_movie_ui_seedfolder.py`: replace this text, which occurs exactly once:

```python
    want = [seedfolder.story_id_for(seedfolder.seed_stem(name), prefix, set()) for name, prefix in SAMPLE_CASES]
    assert json.loads(proc.stdout) == want
```

with:

```python
    want = [seedfolder.story_id_for(seedfolder.seed_stem(name), prefix, set()) for name, prefix in SAMPLE_CASES]
    assert json.loads(proc.stdout) == want


# --- SDT37 (SD47-SD50): the static page, Characters -----------------------------------------------------

CHARACTER_IDS = ("ch-name-label", "ch-folder-mode", "ch-folder-choose", "ch-folder-file", "ch-folder-status",
                 "ch-folder-list", "ch-folder-confirm", "ch-folder-summary", "ch-folder-table",
                 "ch-folder-queue", "ch-folder-cancel")


def test_sdt37_the_static_page_characters():
    _static, texts = _static_texts()
    html, js = texts["index.html"], texts["app.js"]
    for element in CHARACTER_IDS:
        assert html.count('id="%s"' % element) == 1, element
    for element in ("ch-folder-mode", "ch-name-label"):
        assert '"#%s' % element in js, element
    assert "ch-folder-shared" not in html + js
    assert "<th>File</th><th>Character</th><th>Result</th><th>Job</th>" in html
    for text in ('"/api/characters/seed-folder"', '"Name prefix (optional)"', "Seed folder (one character per image)"):
        assert text in html + js, text
```

- [ ] **Step 2: Run it and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedfolder.py::test_sdt37_the_static_page_characters 2>&1 | tail -1
```

Expected: `1 failed` (`ch-name-label` is not in the page).

- [ ] **Step 3: Implement.**

**3.1.** The Name label (SD47). Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
    <label>Name <input id="ch-name" type="text" size="24"></label>
```

with:

```html
    <label><span id="ch-name-label">Name</span> <input id="ch-name" type="text" size="24"></label>
```

**3.2.** The Seed folder checkbox (SD47). Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
    <label>Seed image <input id="ch-seed-file" type="file" accept="image/png,image/jpeg,image/webp"></label>
```

with:

```html
    <label>Seed image <input id="ch-seed-file" type="file" accept="image/png,image/jpeg,image/webp"></label>
    <label><input id="ch-folder-mode" type="checkbox"> Seed folder (one character per image)
      <button id="ch-folder-choose" type="button">Choose folder…</button>
      <input id="ch-folder-file" type="file" webkitdirectory hidden></label>
    <span id="ch-folder-status" class="muted"></span>
    <ul id="ch-folder-list" class="muted" hidden></ul>
```

**3.3.** The Characters confirm table (SD47). Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
  <div class="row"><button id="ch-create" type="button">Create</button> <span id="ch-create-status" class="muted"></span></div>
```

with:

```html
  <div class="row"><button id="ch-create" type="button">Create</button> <span id="ch-create-status" class="muted"></span></div>
  <div id="ch-folder-confirm" hidden>
    <h3>Seed folder</h3>
    <p id="ch-folder-summary" class="muted"></p>
    <table id="ch-folder-table" class="list"><thead><tr><th>File</th><th>Character</th><th>Result</th><th>Job</th></tr></thead><tbody></tbody></table>
    <div class="row">
      <button id="ch-folder-queue" type="button" disabled>Queue 0 jobs</button>
      <button id="ch-folder-cancel" type="button">Cancel</button>
    </div>
  </div>
```

**3.4.** `updateCharacterButtons` (SD48). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    if (status === "dataset") {
      $("#ch-train").disabled = true;
      $("#ch-train-reason").textContent = "fewer than 12 stills kept; regenerate the dataset";
    }
  }
```

with:

```js
    if (status === "dataset") {
      $("#ch-train").disabled = true;
      $("#ch-train-reason").textContent = "fewer than 12 stills kept; regenerate the dataset";
    }
    // Seed-folder spec SD48: the folder mode of the Characters form.
    const box = FOLDER_BOXES.characters;
    const folder = box.mode();
    $("#ch-name-label").textContent = folder ? "Name prefix (optional)" : "Name";
    ["#ch-class", "#ch-descriptor", "#ch-trigger", "#ch-seed-file"].forEach(function (id) { $(id).disabled = folder; });
    renderFolderList(box);
    if (!folder) { closeFolderConfirm(box); return; }
    const block = folderBlock(box);
    if (!block) { return; }
    $("#ch-create").disabled = true;
    const createStatus = $("#ch-create-status");
    createStatus.textContent = createStatus.textContent ? createStatus.textContent + "; " + block : block;
  }
```

**3.5.** `createCharacter` in folder mode (SD49). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
  async function createCharacter(force) {
    let body;
```

with:

```js
  async function createCharacter(force) {
    if (!force && FOLDER_BOXES.characters.mode()) { openFolderConfirm(FOLDER_BOXES.characters, {ws: S.ws, name: $("#ch-name").value.trim(), phrase: $("#ch-phrase").value.trim(), seed: numberOrNull("#ch-seed")}); return; }
    let body;
```

**3.6.** The Characters folder listeners (SD27, SD48). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    $("#ch-force").addEventListener("click", function () { createCharacter(true); });
```

with:

```js
    $("#ch-force").addEventListener("click", function () { createCharacter(true); });
    $("#ch-folder-mode").addEventListener("change", updateCharacterButtons);
    const charactersBox = FOLDER_BOXES.characters;
    part(charactersBox, "choose").addEventListener("click", function () { part(charactersBox, "file").click(); });
    part(charactersBox, "file").addEventListener("change", function () { onFolderPick(charactersBox); });
    part(charactersBox, "queue").addEventListener("click", function () { queueFolder(charactersBox); });
    part(charactersBox, "cancel").addEventListener("click", function () { closeFolderConfirm(charactersBox); });
```

- [ ] **Step 4: Run the new tests, the syntax check, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedfolder.py 2>&1 | tail -1
node --check static/movie-ui/app.js && echo "node ok"
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seams.py::test_ct27_the_static_page tests/test_movie_ui_batch.py::test_bt13_the_static_page tests/test_location_ui.py::test_lu13_the_static_page tests/test_vlm_lifecycle.py::test_vl26_page_gate_and_warn_style tests/test_soft_panel_count.py::test_spt27_the_regenerate_target_is_wired_in_the_static_ui 2>&1 | tail -1
```

Expected: `78 passed`, `node ok`, then `5 passed`. Run the compile check with `FILES` = `tests/test_movie_ui_seedfolder.py`; expected: `compiled 1` twice. Then run the gate block with `N=6`. Expected: `GATE PASS`, `lost 5 (listed 5, unexpected 0)`, `new tests 78, not passing 0`, all the baseline failures still failing, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
git add static/movie-ui/index.html static/movie-ui/app.js tests/test_movie_ui_seedfolder.py
git diff --cached --name-only    # expected: those 3 paths
git commit -m "feat(movie-ui): Characters Seed folder: one character per image through the shared folder code (SD47-SD50; SDT37)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The test-only re-baseline (spec 6.1)

**Files:**
- Modify (test-only; at a9d5aa1):
  - `tests/test_movie_ui_http.py`: `test_mut18` `:44`, `test_mut2` `:342-344`;
  - `tests/test_location_ui.py`: `test_lu1` `:66`;
  - `tests/test_movie_ui_builder.py`: `NEW_PY` `:216`, `test_mut25_source_scan_of_new_python_files` `:260`;
  - `tests/movie_ui_testutil.py`: `copy_ui` `:465`.

**Interfaces:**
- Consumes: the commits of Tasks 1-6.
- Produces: the one test-only re-baseline commit (spec 6.1, 8 step 4).

- [ ] **Step 1: Run the six re-baselined tests and expect the listed failures.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_movie_ui_http.py::test_mut18_every_api_route_needs_the_token \
  tests/test_location_ui.py::test_lu1_the_location_routes_need_the_token \
  tests/test_movie_ui_http.py::test_mut2_preview_argv_is_the_job_argv \
  tests/test_movie_ui_builder.py::test_mut25_source_scan_of_new_python_files \
  tests/test_movie_ui_builder.py::test_mut25_every_new_and_changed_file_compiles \
  tests/test_movie_ui_jobs.py::test_mut15_bin_movie_ui_lock_port_and_startup_lines 2>&1 | tail -1
```

Expected: `5 failed, 2 passed` (the five listed tests fail; both `test_mut25_every_new_and_changed_file_compiles` cases pass).

- [ ] **Step 2: The re-baseline edits.**

**2.1.** The `test_mut18` route count. Edit `tests/test_movie_ui_http.py`: replace this text, which occurs exactly once:

```python
    assert len(srv.ROUTES) == 55
```

with:

```python
    assert len(srv.ROUTES) == 57
```

**2.2.** The `test_mut2` key set. Edit `tests/test_movie_ui_http.py`: replace this text, which occurs exactly once:

```python
                                      "started", "ended", "exit_code", "error", "queue_position", "command",
                                      "progress"}
```

with:

```python
                                      "started", "ended", "exit_code", "error", "queue_position", "command",
                                      "progress", "seed_folder"}
```

**2.3.** The `test_lu1` route count. Edit `tests/test_location_ui.py`: replace this text, which occurs exactly once:

```python
    assert len(srv.ROUTES) == 55
```

with:

```python
    assert len(srv.ROUTES) == 57
```

**2.4.** `NEW_PY`. Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
          "movie_ui_batch.py", "tests/test_movie_ui_batch.py")
```

with:

```python
          "movie_ui_batch.py", "tests/test_movie_ui_batch.py", "movie_ui_seedfolder.py",
          "tests/test_movie_ui_seedfolder.py")
```

**2.5.** The `allowed` import set. Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
                   "subprocess", "sys", "threading", "time", "fleet_lib", "movie_ui_lib", "movie_ui_batch"}
```

with:

```python
                   "subprocess", "sys", "threading", "time", "fleet_lib", "movie_ui_lib", "movie_ui_batch",
                   "movie_ui_seedfolder"}
```

**2.6.** `copy_ui`. Edit `tests/movie_ui_testutil.py`: replace this text, which occurs exactly once:

```python
                "movie_ui_batch.py"):
```

with:

```python
                "movie_ui_batch.py", "movie_ui_seedfolder.py"):
```

- [ ] **Step 3: Run the checks.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
git diff --numstat -- tests/
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_movie_ui_http.py::test_mut18_every_api_route_needs_the_token \
  tests/test_location_ui.py::test_lu1_the_location_routes_need_the_token \
  tests/test_movie_ui_http.py::test_mut2_preview_argv_is_the_job_argv \
  tests/test_movie_ui_builder.py::test_mut25_source_scan_of_new_python_files \
  tests/test_movie_ui_builder.py::test_mut25_every_new_and_changed_file_compiles \
  tests/test_movie_ui_jobs.py::test_mut15_bin_movie_ui_lock_port_and_startup_lines 2>&1 | tail -1
```

Expected: four numstat lines, in `git`'s path order:
- `1	1	qwen-agent-workspace/tests/movie_ui_testutil.py`
- `1	1	qwen-agent-workspace/tests/test_location_ui.py`
- `4	2	qwen-agent-workspace/tests/test_movie_ui_builder.py`
- `2	2	qwen-agent-workspace/tests/test_movie_ui_http.py`

Then `7 passed`: `test_mut18`, `test_lu1`, `test_mut2`, `test_mut25_source_scan`, both `test_mut25_every_new_and_changed_file_compiles` cases (the 3.9 case now compiles `movie_ui_seedfolder.py` and its test file) and `test_mut15`. If a value differs, fix the Edit, not this command. Then run the gate block with `N=7`. Expected: `GATE PASS`, `lost 0`, `new tests 78, not passing 0`, all the baseline failures still failing, and `offline unchanged`.

- [ ] **Step 4: Commit (test-only; spec 6.1, 8 step 4).**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedf-wt/qwen-agent-workspace
git add tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_builder.py tests/movie_ui_testutil.py
git diff --cached --name-only    # expected: only those 4 paths
git commit -m "test: re-baseline mut18 and lu1 (57 routes), mut2 (the seed_folder summary key), mut25 (movie_ui_seedfolder compiled, scanned and allowed) and copy_ui for mut15 (seed-folder spec 6.1)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Verification (controller only; not an implementer task)

The controller runs these after Task 7, in spec 8 step 5's order: the pass bar items 1-3, the browser check (steps 1-12), the Opus design review, then the Compose live check, then the Characters live check if the user gives the go. Every rule of "Global Constraints" applies. A finding is fixed in a new commit on the owning task's files; then that task's Step 4 and V1 rerun.

- [ ] **V1: The pass bar, items 1-3 (spec 7), about 17 minutes.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/seedf-baseline
cd $S/seedf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedfolder.py 2>&1 | tail -1
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/final-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt; tail -1 $D/final-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/final-pytest.txt $D/expected-failures.txt 7
diff <(grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt | sort) <(grep -E '^(FAILED|ERROR)' $D/final-pytest.txt | sort) && echo "same failures, same messages"
grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $D/final-pytest.txt
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1
git diff --stat e94ebb0..HEAD -- bin story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py movie_ui_batch.py | tail -1
git diff --name-only e94ebb0..HEAD
git diff e94ebb0..HEAD -- movie_ui_seedfolder.py | grep -E '^\+(import|from) '
git diff e94ebb0..HEAD -- movie_ui_server.py | grep -E '^\+(import|from) '
git diff e94ebb0..HEAD -- tests/ | grep -E '^\+' | grep -nE "expanduser\(|urlopen|import requests|zshenv|fleet\.env|macstudio|127\.0\.0\.1:81" || echo "no real HOME, HTTP client, private host or model-server address in the new tests"
grep -n 'STATE_SUBDIRS = ' movie_ui_lib.py
```

Expected, in order:
- `78 passed` (item 1: every SDT test and the five Review Focus pins);
- the final summary is the baseline's with the pass count higher by exactly 78;
- `lost 0 (listed 0, unexpected 0); new tests 78, not passing 0` and `GATE PASS`;
- `same failures, same messages` (item 2: only the baseline failures, which include `test_d2_copied_literals_match_the_spike` and `test_rst62_import_sets`);
- `1` (`test_mut26` passes unedited);
- `OK 347/347` (item 3);
- no output from the pipeline `--stat` (no pipeline file and not `movie_ui_batch.py` changed);
- the changed paths are exactly the 2 docs (the spec and this plan) plus `movie_ui_lib.py`, `movie_ui_seedfolder.py`, `movie_ui_server.py`, `static/movie-ui/app.js`, `static/movie-ui/index.html`, `tests/movie_ui_testutil.py`, `tests/test_location_ui.py`, `tests/test_movie_ui_builder.py`, `tests/test_movie_ui_http.py` and `tests/test_movie_ui_seedfolder.py`, each with the `qwen-agent-workspace/` prefix (`app.css` is unchanged);
- exactly five import lines for the module: `+import re`, `+import secrets`, `+import time`, `+import unicodedata`, `+import movie_ui_lib as lib` (SD1);
- exactly one for the server: `+import movie_ui_seedfolder as seedfolder` (no third-party import);
- `no real HOME, HTTP client, private host or model-server address in the new tests`;
- `STATE_SUBDIRS = ("jobs", "uploads", "traces", "smoke", "batches")` (SD4: no new state subdirectory).

If a timing-sensitive test failed in one run only, rerun it alone and record both results. Any other difference: stop and report.

- [ ] **V2: The browser check (spec 6.2; before the merge; not pytest).**

A throwaway demo server under `$S/sfdemo/`, never committed. It never calls `start_threads`, so there is no dispatcher, no probe, and no job ever runs (the Characters jobs of steps 10-11 stay queued; `bin/character` is the stub). The stub workspace gets a copy of `static/movie-ui`, because `make_server`'s third argument is also the directory the page is served from (Plan ruling PR6).

Create `$S/sfdemo/make_folders.py` with the Write tool, exactly:

```python
"""Builds the browser-check folders of seed-folder spec 6.2 (never committed)."""
import os

S = "/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 24
seeds = os.path.join(S, "sfdemo", "seeds")
os.makedirs(os.path.join(seeds, "sub"), exist_ok=True)
for name, data in (("shot10.png", PNG + b"\x01"), ("shot2.png", PNG + b"\x02"), ("Beach Day!.webp", WEBP),
                   ("bad.jpg", PNG + b"\x03"), (".hidden.png", PNG + b"\x04"), ("notes.txt", b"notes\n"),
                   (os.path.join("sub", "inner.png"), PNG + b"\x05")):
    with open(os.path.join(seeds, name), "wb") as f:
        f.write(data)
many = os.path.join(S, "sfdemo", "seeds101")
os.makedirs(many, exist_ok=True)
for i in range(101):
    with open(os.path.join(many, "img%03d.png" % i), "wb") as f:
        f.write(PNG + i.to_bytes(2, "big"))
print("folders ready")
```

Create `$S/sfdemo/demo.py` with the Write tool, exactly:

```python
"""Throwaway demo server for the seed-folder browser check (spec 6.2; never committed)."""
import os
import secrets
import shutil
import sys

S = "/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad"
WS = S + "/seedf-wt/qwen-agent-workspace"
os.environ["HOME"] = S + "/sfdemo/home"
os.environ["MOVIE_UI_VLM_LIFECYCLE"] = "0"
os.environ["MOVIE_UI_VLM_TOOLS"] = S + "/sfdemo/no-tools"
os.environ["MOVIE_UI_VLM_PORT"] = "9"
os.environ.pop("CHARACTER_LIBRARY_DIR", None)
os.makedirs(os.environ["HOME"], exist_ok=True)
sys.path.insert(0, WS + "/tests")
import movie_ui_testutil as mt  # noqa: E402  (puts WS on sys.path)
import movie_ui_lib as lib  # noqa: E402
import movie_ui_server as srv  # noqa: E402

state = lib.state_dir()
lib.ensure_state(state)
ws = mt.make_stub_workspace(S + "/sfdemo")
if not os.path.isdir(os.path.join(ws, "static", "movie-ui")):
    shutil.copytree(os.path.join(WS, "static", "movie-ui"), os.path.join(ws, "static", "movie-ui"))
lib.shared_checks = lambda fields, ws_real, py=None: [lib.check("V2", "render", "pass", "stub")]
server = srv.make_server(0, state, ws, secrets.token_urlsafe(32))
assert server.port not in (8177, 8178, 8999), server.port
for key in ("render", "stills", "story_server"):
    server.capabilities[key] = {"ok": True, "reason": None, "checked": lib.utc_now()}
print("http://127.0.0.1:%d/?t=%s" % (server.port, server.token))
sys.stdout.flush()
server.serve_forever()
```

Run `python3 -B $S/sfdemo/make_folders.py` (expected: `folders ready`), then `python3 -B $S/sfdemo/demo.py` in the background, open the printed URL in a browser, and stop the process (Ctrl-C) when done. If the assert fires, start it again. Pass when all of these hold (spec 6.2, verbatim):
1. Picking `seeds101` shows `found 101 images; at most 100 per run — pick a smaller folder`.
2. Picking `seeds` lists exactly `bad.jpg`, `Beach Day!.webp`, `shot2.png`, `shot10.png`, in that order. `bad.jpg` is marked `upload failed: file content is not image/jpeg`, and the status ends `uploaded 3 of 4 images (1 failed)`.
3. The label reads `Story ID prefix (optional)`. Smoke render is disabled with `not available for a seed folder`. Validate is disabled.
4. With prefix `demo`, the command shows `--story-id demo-Beach-Day` and the `Beach Day!.webp` upload path.
5. Write story opens the table with the rows `bad.jpg | — | upload failed: file content is not image/jpeg`, `Beach Day!.webp | demo-Beach-Day | OK`, `shot2.png | demo-shot2 | OK` and `shot10.png | demo-shot10 | OK`. The shared check `pass V2 render: stub` is shown, and the button reads `Queue 3 jobs`.
6. Queue fills the Job column, switches to Jobs, and shows 3 queued story jobs in that order, each tagged `seed folder sf-… · <file name>`.
7. Cancel on a fresh table hides it and creates nothing.
8. Choosing Size again restores `Story ID` and the normal buttons.
9. On the Characters tab, picking `seeds` ticks `Seed folder (one character per image)` and gives the same list and status as step 2. The label reads `Name prefix (optional)`, and Class noun, Descriptor, Trigger and Seed image are disabled.
10. With prefix `demo` and phrase `the stranger`, Create opens the table with the rows `bad.jpg | — | upload failed: file content is not image/jpeg`, `Beach Day!.webp | demo-beach-day | OK`, `shot2.png | demo-shot2 | OK` and `shot10.png | demo-shot10 | OK`, no shared-check list, and `Queue 3 jobs`.
11. Queue switches to Jobs and shows 3 queued `character-create` jobs (`demo-beach-day`, `demo-shot2`, `demo-shot10`, in that order), each tagged `seed folder sf-… · <file name>`.
12. Unticking the box restores `Name`, re-enables the four inputs and hides the table. The Compose folder list from step 2 is still there (each box keeps its own state).

Also observe, and report but do not block on, Plan ruling PR5: with Compose's Seed folder selected, choosing a single seed image file switches the radio to Seed image but leaves the folder-mode label and buttons until the next Compose change.

- [ ] **V3: The design review (spec 8 step 5).** Ask an Opus `design-reviewer` to review `git diff a9d5aa1..HEAD -- qwen-agent-workspace` against the spec, this plan's rulings and the Review Focus. Fix every finding as above.

- [ ] **V4: The Compose live check (spec 6.3; controller-run only).**
  - Requires this Mac's movie-ui running from this branch and a running story server (the queued story jobs need the VLM when the real dispatcher starts them). Never on macstudio. Never touch `:8178`. No render: use Write story only. If the movie-ui or the story server is not running, starting it needs the user's go-ahead.
  - Pick a real folder of 3 PNG or JPEG images (each edge at least 64 px) through Compose → Seed folder, then use Write story.
  - Pass when exactly 3 story jobs are queued, in file-name order, with the IDs the confirm table predicted, each argv carrying its seed's `--seed-image`. (The predicted IDs equal the final ones when no story with those names appears between Write story and Queue and no earlier seed with the same stem is refused; Review Focus 2.)
  - Rendering happens only on the user's go.

- [ ] **V5: The Characters live check (spec 6.3; controller-run only, and only on the user's explicit go).**
  - It starts GPU work (the dataset edit). Without the user's go, record it as "not run (awaiting the user's go)" in the merge report; that does not block the merge (spec 7 item 5).
  - Use a real folder of 2 face images (each face at least 15% of the image height) through Characters → Seed folder → Create → Queue.
  - Pass when exactly 2 `character-create` jobs are queued, in file-name order, with the names the table predicted, each argv carrying its seed's `--seed-image` and the shared `--phrase`.

- [ ] **V6: Hand-off.** Report the branch `seed-folder` and its 7 new commits (6 task commits and the re-baseline), V1-V5's results and the PR5 observation. Push and the merge are a separate step that needs the user's approval.

---

## Coverage

### Spec coverage: requirement → task

| Requirement | Task (step) |
|---|---|
| SD1 module rules | 1 (`movie_ui_seedfolder.py`; SDT9 import check); V1 (the import lines) |
| SD2 `shared_checks` | 2 (3; SDT10) |
| SD3 `_compose_job_locked` | 3 (3.4; SDT18, SDT23, the seams and batch files in Step 4) |
| SD4 nothing new stored | 3, 4 (no state code; SDT13, SDT19, SDT31); V1 (`STATE_SUBDIRS`) |
| SD5 `seed_stem` | 1 (SDT1, SDT2, SDT7) |
| SD6 `valid_prefix` | 1 (SDT3, SDT7) |
| SD7 `first_free`, `story_id_for` | 1 (SDT1, SDT3, SDT4, SDT6, SDT7) |
| SD8 `assign_story_ids` | 1 (SDT1, SDT6, SDT7); 3 (SDT22) |
| SD9 taken set | 1 (`taken_names`; SDT4, SDT5); 3 (`seed_taken`; SDT20) |
| SD10 examples | 1 (SDT1) |
| SD11 Compose route | 3 (3.2, 3.6); 4 (SDT11) |
| SD12 body | 1 (`validate_request`; SDT8); 3 (`seed_upload`/`width`/`height` forced to null, `compose_fields`; SDT14) |
| SD13 400 table, `_seeds_and_preview` | 1 (rows 2-7; SDT8); 3 (row 1 via `_fields_body`; SDT12) |
| SD14 provisional IDs | 3 (`seed_rows` step 1; SDT13, SDT14, SDT20) |
| SD15 V1 per seed | 3 (`seed_rows` step 2; SDT15, SDT17) |
| SD16 shared checks once | 3 (`seed_rows` step 3; SDT16, SDT17) |
| SD17 V6, 4 workers, no lock | 3 (`_dry_runs`; SDT21) |
| SD18 status and reason | 1 (`row_reason`; SDT9); 3 (the skip records; SDT15, SDT16); Review Focus 4 |
| SD19 preview | 3 (SDT13) |
| SD20 queue | 3 (`_h_seed_folder`; SDT14-SDT20, SDT22); Review Focus 2, 3 |
| SD21 response | 3 (`_seed_response`; SDT13-SDT16) |
| SD22 run ID | 1 (`new_run_id`; SDT9); 3 (SDT19); 4 (SDT35) |
| SD23 tag | 1 (`seed_tag`; SDT9); 3 (`job_summary`; SDT19, SDT24); 4 (SDT35) |
| SD24 other routes unchanged | 3 (no code; SDT19, SDT24) |
| SD25 partial creation | 3 (no code; SDT23) |
| SD26 HTML | 5 (3.1-3.3; SDT25) |
| SD27 shared code, pick | 5 (3.5, 3.9 `onFolderPick`, 3.10); 6 (3.6); V2 items 1, 2, 9 |
| SD28 upload | 5 (3.9 `uploadFolder`, `renderFolderList`, `uploadedSeeds`); V2 items 2, 9 |
| SD29 Compose folder mode | 5 (3.6, 3.8, 3.9 `folderMode`, `folderBlock`); V2 items 3, 8 |
| SD30 command preview | 5 (3.7, 3.9 `sampleStoryId`; Review Focus 5); V2 item 4 |
| SD31 opening the table | 5 (3.9 `openFolderConfirm`, 3.11); V2 items 5, 10 |
| SD32 table | 5 (3.9 `renderFolderTable`); V2 items 5, 10 |
| SD33 Queue and Cancel | 5 (3.9 `queueFolder`, `closeFolderConfirm`, 3.10); V2 items 6, 7, 11, 12 |
| SD34 Jobs tag | 5 (3.12-3.16); V2 items 6, 11 |
| SD35 unchanged | 5 (no edit to `onSeedFile`, `fillCompose`, `app.css`; SDT25's pattern scan; the Step 4 static-page tests) |
| SD36 `character_stem` | 1 (SDT26, SDT27) |
| SD37 `valid_character_prefix` | 1 (SDT27); 4 (SDT30) |
| SD38 `character_name_for`, `assign_character_names` | 1 (SDT26, SDT27); 4 (SDT34c) |
| SD39 character taken set | 1 (`character_taken_names`); 4 (`character_taken`; SDT28, SDT34) |
| SD40 character examples | 1 (SDT26) |
| SD41 Characters route | 4 (3.1, 3.7; SDT29) |
| SD42 Characters body | 4 (`_h_character_seed_folder`; SDT32) |
| SD43 Characters 400s, `_phrase_errors`, `_seed_number_errors` | 1 (rows 4-8; `validate_character_request`); 4 (3.2-3.4; SDT30, SDT36) |
| SD44 Characters steps | 4 (`_character_rows`, the handler; SDT31-SDT34); Review Focus 1 |
| SD45 `_character_job_locked` | 4 (3.5; SDT32, SDT36) |
| SD46 Characters response and jobs | 4 (`_character_response`; SDT31, SDT33, SDT35, SDT36) |
| SD47 Characters HTML | 6 (3.1-3.3; SDT37) |
| SD48 Characters folder mode | 6 (3.4, 3.6); V2 items 9, 12 |
| SD49 Characters Create | 6 (3.5); V2 items 10, 11 |
| SD50 shared and unchanged | 5 (one copy of each function; SDT25); 6 (no other Characters edit; SDT37) |
| §5 error table | 1 (400 texts, reasons); 3, 4 (row texts, 409, 500); 5 (page texts) |
| §6.1 re-baseline | 7 (Step 2) |
| §6.2 browser check | V2 |
| §6.3 live checks | V4 (Compose), V5 (Characters) |
| §7 pass bar | V1 (items 1-3), V4 (item 4), V5 (item 5) |
| §8 rollout | Before Task 1 (snapshot, baseline); 1-6 (feature commits); 7 (test-only commit); V1-V5 |
| G1-G5 | G1 1; G2 2; G3 3, 4; G4 5, 6; G5 1-6 (and 7 for §6.1) |

### Test IDs and their owning task (each is owned by exactly one task)

| IDs | Task | Cases |
|---|---|---|
| SDT1-SDT9, SDT26, SDT27 | 1 | 43 (SDT1 17, SDT26 13, SDT8 2, SDT9 3, SDT27 2, SDT2-SDT7 1 each) |
| SDT10 | 2 | 1 |
| SDT12-SDT24, Review Focus 2-4 | 3 | 18 (SDT20 3, the other 12 SDT IDs 1 each, Review Focus 3) |
| SDT11, SDT28-SDT36, Review Focus 1 | 4 | 13 (SDT34 3, the other 9 SDT IDs 1 each, Review Focus 1) |
| SDT25, Review Focus 5 | 5 | 2 |
| SDT37 | 6 | 1 |
| the spec 6.1 re-baselines | 7 | (existing tests) |

Totals: 78 new cases in `tests/test_movie_ui_seedfolder.py`: 73 SDT cases and 5 Review Focus pins. Cumulative after each task: 43, 44, 62, 75, 77, 78.

### Self-review

- **Spec coverage.** Every requirement SD1-SD50 maps to a task in the table above, every test SDT1-SDT37 has real test code in its owning task, and §6.1, §6.2, §6.3, §7 and §8 each have a step.
- **Placeholders.** The only symbolic values are `$S`, `$D`, `WS` and `N` (the gate block), each defined in its block or in the house rules. No step says "add error handling", "TBD" or "similar to Task N". Every Edit names its old text, which occurs exactly once at its turn, with or without its last newline (checked by replay).
- **Type and name consistency.** These names appear with the same signature everywhere they are used:
  - `seedfolder.first_free(head, stem, taken, limit, trim)` (Task 1, through `story_id_for` and `character_name_for`);
  - `seedfolder._seeds_and_preview(body) -> (seeds, preview, error)`, `validate_request(body) -> (clean, error)` and `validate_character_request(body) -> (clean, error)` with the `clean` keys of Task 1's Interfaces (Tasks 1, 3, 4);
  - `seedfolder.assign_story_ids` / `assign_character_names(names, prefix, taken)` and `taken_names` / `character_taken_names(listing, busy)` (Tasks 1, 3, 4);
  - `lib.shared_checks(fields, ws_real, py=...)` (Task 2; Task 3 calls it with two arguments; the HTTP stub accepts `py=None`);
  - `srv.seed_rows(server, fields, clean) -> (rows, shared)` and `srv._character_rows(server, real, body, clean) -> rows`, with the row keys of Tasks 3 and 4, and `srv._seed_response` / `srv._character_response(server, rows, ..., run=None, job_ids=None)`;
  - `srv._compose_job_locked(server, fields, seams=False)` and `srv._character_job_locked(server, kind, real, fields)`, both returning a job ID with `STORE_LOCK` held by the caller;
  - the SD21/SD46 body keys and the summary's `seed_folder`, consumed through `box.idKey` (`"story_id"` or `"character"`) by `openFolderConfirm`, `queueFolder` and `folderResult`, and by `seedTag` (Tasks 5, 6);
  - the box functions take `box` first everywhere (`onFolderPick(box)`, `renderFolderList(box)`, `openFolderConfirm(box, base)`, `queueFolder(box)`, `closeFolderConfirm(box)`, `renderFolderTable(box)`), as SDT25 requires.
- **Spec strings.** Every message of SD13, SD18, SD27-SD34, SD43, SD47-SD49 and §5 is copied verbatim, including `—` (U+2014), `…` (U+2026) and `·` (U+00B7).
- **Review Focus.** Five inputs, each with a pinning test in its owning task (Tasks 4, 3, 3, 3 and 5).

## Plan rulings

**[defect]** rulings change behaviour from what the spec literally writes, or note a spec text that cannot work as written. **[reading]** rulings fill a detail the spec leaves open.

1. **PR1 [reading]: seven implementer tasks, one commit per task.** Spec 8 step 3's single feature commit becomes six task commits (Tasks 1-6), as in the prior plans. Spec 6.1 stays one test-only commit (Task 7), after every feature commit. The design review comes after the pass bar and the browser check, as spec 8 step 5 orders.
2. **PR2 [reading]: SD13 "the first failing rule" across items.** In `_seeds_and_preview`, rule 5 (an item that is not an object) is checked for every item before rule 6 (an item's name); within a rule, the lowest K is reported. So `[{"name": 5}, "x"]` gives `seed 2 must be an object` (SDT8 pins it). Both endpoints share it.
3. **PR3 [defect]: SD28 never refreshes the form after the last upload.** SD28 calls `box.refresh()` after each file, while `box.folder.uploading` is still true, and then sets `uploading = false` with no refresh. Run all and Write story (or Create) would stay blocked with `uploading seeds…`. `uploadFolder` calls `renderFolderList(box)` and `box.refresh()` once more after the final status.
4. **PR4 [reading]: `renderFolderList(box)` also runs right after a file's state becomes `uploading`,** so SD28's `uploading…` state text is ever shown. `uploadFolder` also checks `box.seq` at the top of each iteration.
5. **PR5 [defect, not changed]: picking a single seed image while in Compose folder mode leaves stale folder-mode controls.** The panel's `change` listener runs `updateComposeButtons()` before `onSeedFile`'s upload finishes; `onSeedFile` then checks the Seed image radio with no refresh. SD35 forbids editing `onSeedFile`, so the plan follows the spec. The label, Validate, the list and the Run all/Write story block stay in folder mode until the next Compose change; clicking Write story still submits one job, because the handlers test `folderMode()` at click time. Amendment (Q1): add `updateComposeButtons();` before `preview();` in `onSeedFile`. (Characters has no analogue: SD48 disables `#ch-seed-file` in folder mode.)
6. **PR6 [defect]: spec 6.2's demo serves no page.** `make_server(0, state, ws, token)` makes the stub workspace `ui_ws`, which is also where `_send_static` reads `static/movie-ui`, and the stub workspace has none. `demo.py` copies `static/movie-ui` into the stub workspace first, as `mt.copy_ui` does.
7. **PR7 [reading]: SDT7 and SDT27 draw 1 to 5 names per call,** so "the IDs (names) of one call are distinct" is exercised. SDT27's prefixes are a lower-case letter plus 1-11 of `[a-z0-9-]`, so every one passes `valid_character_prefix`.
8. **PR8 [reading]: SDT20 and SDT34 are three tests each (a, b, c), each on a fresh `env`.** (a)'s queued job would change (b)'s and (c)'s provisional IDs from the ones the spec expects.
9. **PR9 [reading]: the `env` fixture installs the `shared_checks` pass stub and removes `CHARACTER_LIBRARY_DIR`;** a test that needs another stub or a library directory sets it again with `monkeypatch`.
10. **PR10 [reading]: the server's internal names.** The Compose row dict `{"name", "upload_id", "story_id", "fields", "v1", "v6", "status", "reason"}`, `_seed_response(server, rows, shared, run=None, job_ids=None)`, the Characters row dict `{"name", "upload_id", "character", "v1", "status", "reason"}`, `_character_rows(server, real, body, clean)` and `_character_response(server, rows, run=None, job_ids=None)` are plan names. `_dry_runs(server, rows)` receives only the V1-passing rows. Under `STORE_LOCK` each handler records `(index, final ID or name, job ID)`, and the rows take their final values after the lock, as SD20 step 4 orders. The dry-run threads are daemon threads named `movie-ui-dry-run`, all joined before the answer.
11. **PR11 [reading]: `openFolderConfirm` treats any file that is not `uploaded` as a failed row.** Only `uploaded` and `failed` files can exist when the buttons are enabled (`folderBlock` covers uploading).
12. **PR12 [reading]: the page's error text is `(res.data && res.data.error) || ("http " + res.status)`** (`folderError`), because `api()` returns `data: null` for a non-JSON answer.
13. **PR13 [reading]: SDT10 is one test** (both `run_checks` cases and `shared_checks`), so it fails first on the missing `lib.shared_checks`.
14. **PR14 [reading]: the >100 message is built with `SEEDS_MAX`;** the text is exactly `found N images; at most 100 per run — pick a smaller folder`.
15. **PR15 [reading]: SDT12 covers all three `resolve_ws` messages** (`missing ws`, `ws must be an absolute path`, `not a harness workspace (no bin/ltx-movie): <path>`), a missing `preview` key, and checks that no dry run ran. SDT30 covers `missing ws` for the Characters endpoint.
16. **PR16 [reading]: the expected-failure list.** All five tests break at Task 3 (the first route, the summary key, the import and the copied module); Task 4's second route keeps `test_mut18` and `test_lu1` red. `NEW_PY`'s missing entries break nothing.
17. **PR17 [reading]: the Review Focus tests are named `test_sf_review_focus_N_...`,** unique in the suite.
18. **PR18 [reading]: `updateComposeButtons` and `updateCharacterButtons` call `renderFolderList(box)` before their folder-mode branch,** so the list hides outside folder mode (SD29, SD48).
19. **PR19 [reading]: SDT11 is owned by Task 4.** It asserts `len(srv.ROUTES) == 57`, which holds only once the Characters route exists. Task 3's compose route is exercised by SDT12-SDT24 meanwhile.
20. **PR20 [defect]: SD44 step 2's `"name": <its name>` is the seed's provisional character name, not its file name.** With the file name (`Kyra.png`), `character_create_errors` would refuse every row with `character name must match [a-z][a-z0-9-]{1,23}`, contradicting the spec's own statement that the check "can only report the upload". `_character_rows` passes the step 1 name.
21. **PR21 [reading]: SDT37's strings.** `"/api/characters/seed-folder"` and `"Name prefix (optional)"` are checked with their quotes (they are JavaScript strings); `Seed folder (one character per image)` is checked without quotes, because it is HTML text.
22. **PR22 [reading]: `folderResult(box, row, seed)`** sets `row.id = seed[box.idKey]`, `row.status` and `row.result` (SD31 step 6, SD33); SDT25's "defined exactly once as `function <name>(box`" also holds for it and for `uploadFolder(box, seq)`, `uploadedSeeds(box)` and `folderBlock(box)`.

## Questions for controller

1. **Q1 (PR5).** Accept the stale folder-mode controls after picking a single seed image in Compose folder mode (spec SD35 as written), or amend SD35 to add `updateComposeButtons();` before `preview();` in `onSeedFile`? The plan follows the spec; V2 reports what it observes.

## Spec defects found (for the spec author)

1. SD28 sets `box.folder.uploading = false` after the last `box.refresh()`, so Run all, Write story and Create stay blocked with `uploading seeds…` (PR3; the plan adds the refresh).
2. SD28 calls `renderFolderList(box)` only after each file, so the `uploading…` state text it defines is never shown (PR4).
3. SD35 keeps `onSeedFile` unchanged, which leaves Compose folder-mode controls stale after a single-seed pick in folder mode (PR5; not changed, Q1).
4. Spec 6.2's `srv.make_server(0, state, ws, <random token>)` passes the stub workspace as `ui_ws`, which has no `static/movie-ui`, so the page would answer 404 (PR6; the demo copies the static files).
5. SD13's "first failing rule" does not say whether rule 5 is checked across all items before rule 6 (PR2).
6. SD44 step 2's `b = {"name": <its name>, …}` reads as the file name, which `character_create_errors` would refuse; it must be the provisional character name (PR20).
7. SDT11 asserts 57 routes, so it cannot pass in a task that adds only the Compose route; the plan moves it to the Characters task (PR19).

The spec's other claims were checked against the code: the 55 routes; `job_summary`'s 14 keys; `STORE_LOCK` being non-reentrant; `job_index`'s busy map; the V1 messages; `GET /api/characters/seed-folder` reaching `h_character` (502 `character printed unparsable output` from the stub); `character_argv`'s `create … --seed-image … --seed N --no-review` with no `--descriptor` when a seed image is given; the existing Characters tests staying green; and the six spec 6.1 edits as the complete list of broken existing tests.

## Execution handoff

Plan complete and saved to `qwen-agent-workspace/docs/superpowers/plans/2026-11-01-seed-folder-compose.md`.

**How it was checked.**
- **Data files.** Every Create and Edit of Tasks 1-7 lives in one block file, and this plan's code blocks are rendered from those files.
- **Edits.** A script replayed the operations in order on a scratch copy of `a9d5aa1`'s `WS` (`git archive`, never the worktree or the main checkout), checking every old text exactly once, with and without its last newline. Each occurred exactly once at its turn.
- **Fail first, then pass.** After each task's Step 1 alone, and after the whole task, the task's command gave the Step 2 and Step 4 results quoted in each task: `1 error`/`43 passed`, `1 failed`/`44 passed`, `18 failed, 44 passed`/`62 passed`, `13 failed, 62 passed`/`75 passed`, `2 failed`/`2 passed` (`77 passed` for the file), `1 failed`/`78 passed`. Task 7's tests gave `4 failed, 2 passed` before and `6 passed` after (`test_mut15` was not run; see below).
- **HTTP tests without a socket.** The replay ran the Tasks 3 and 4 tests (and the existing movie-UI files) through a plan-only pytest plugin that drives the real `MovieUIHandler` over in-memory buffers instead of `mt.Running`'s 127.0.0.1 socket, so no server was started. The executor's run with the real in-test server is the authority. `test_sdt21` and Review Focus 3 passed three runs in a row.
- **The existing movie-UI tests.** `tests/test_movie_ui_http.py`, `test_location_ui.py`, `test_movie_ui_seams.py`, `test_movie_ui_builder.py`, `test_movie_ui_batch.py`, `test_movie_ui_checks.py` and `test_movie_ui_progress.py` were run through the same plugin on the unmodified copy and on the Task 6 copy. The only difference was the four listed tests (`test_mut18`, `test_lu1`, `test_mut2`, `test_mut25_source_scan`); the three existing Characters tests passed in both. `test_mut15`'s cause was confirmed by importing `movie_ui_server` from a copy made like `copy_ui`. The five static-page tests of Tasks 5 and 6 Step 4 passed.
- **Compile.** Every new and changed Python file compiled under Python 3.9.6 and 3.13, the module ran under 3.9.6, and `node --check static/movie-ui/app.js` passed after Tasks 5 and 6.
- **Not run.** The full suite (the baseline is Before Task 1's first job), `test_mut15`, the page's behaviour in a browser (V2), any real server, model or network, and the live checks.

Please review the plan. Which execution approach would you prefer?
- **Subagent-driven.** A fresh Sonnet `code-executor` implements each task in `$S/seedf-wt` on branch `seed-folder`, and a fresh Opus reviewer checks it before the next one starts.
- **Native.** One session implements every task, then one fresh Opus reviewer checks the whole branch.

I recommend subagent-driven. Tasks 3 and 4 consume Task 1's names, and Tasks 5 and 6 consume the two response bodies through one shared set of box functions, so a reviewer gate between them catches a drift early. Answer Q1 before Task 5 starts.
