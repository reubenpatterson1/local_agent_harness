# Seed Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A movie-ui **Seeds** tab that edits one source image into 1-4 seed candidates.
- The user picks a source (an upload, a candidate of an earlier run through **Edit again**, or a Characters still through **New seed from this**), types a prompt and picks **Z-Image (img2img)** (with a strength) or **Qwen-Image-Edit**. **Generate** queues one `seed-edit` GPU job.
- The job runs `bin/seed-edit`, which loads the model once and writes `cand_01.png`... into `generated/seeds/runs/<run>/` with a `run.json` record, screening every candidate with content safety. Qwen runs through diffusers bf16 when at least 64 GiB is available and the bf16 weights are cached, else through mflux q4 from a separate venv, else it refuses before loading.
- The tab shows each candidate beside the source; per candidate **Keep** copies it into a named seed folder `generated/seeds/<folder>/`, **Use in Compose** makes it the Compose seed image, **Edit again** makes it the new source. A runs list and a seed-folders list sit below.

**Architecture:**
- **`movie_ui_seedgen.py` (Task 1, new, pure).** The constants of spec 1.1; `validate_run_request` (the SG33 400 table), `valid_folder`, `new_run_id`, `keep_name`, `capability`, `availability_error`. It never writes and never starts a process.
- **`movie_ui_lib.py` (Task 2).** `seed-edit` joins the VLM-`forbidden` kinds; `seed_edit_argv`; `seed_edit_check` (runs `bin/seed-edit --probe`); the `seed-edit` branch of `ProgressParser` (`candidates` in the snapshot).
- **`bin/seed-edit` (Task 3, new).** The tool: argv rules, the canvas, `run.json` and its write order, the preflight (disk, busy GPU, backend, memory), the backend choice, the probe, the Z-Image backend in process, the diffusers bf16 child (`character_dataset.py qwenedit`, unchanged) and the mflux q4 child (screened in the parent).
- **`seed_edit_mflux_child.py` and `bin/seed-edit-setup` (Task 4, new).** The mflux q4 child (the spec's code) and the venv + download script, which only the controller runs, only on the user's go.
- **`movie_ui_server.py` (Task 5).** The `seed_edit` capability, six token-gated routes under `/api/seeds/`, `store_upload` (extracted from `_h_upload`), `SEEDS_LOCK`, and the `seed_run` key of the job summary.
- **The page (Task 6).** The Seeds tab and panel, its 21 functions, the Characters still button, the Jobs label, the progress text and the CSS.
- **Task 7** is the test-only re-baseline commit of spec 9.2 (plus one existing pin the spec missed, Plan ruling PR2) and SGT34.
- **Verification** (controller, not an implementer task): the pass bar (spec 10), the browser check (spec 9.3), the Opus design review and the live checks (spec 9.4), each live check only on the user's go.
- **Tests:** two new files. `tests/test_seed_edit_tool.py`: SGT1-SGT16 and Review Focus pins 3 and 4 (35 test cases). `tests/test_movie_ui_seedgen.py`: SGT17-SGT34 and Review Focus pins 1, 2 and 5 (57 test cases). 92 in all.

**Tech Stack:**
- Python 3.13 (`python3` = `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`, pytest 8.3.4, Pillow 12.3, psutil 6.1). Python 3.9.6 (`/usr/bin/python3`) is used for the compile check only. Every new and changed Python file compiles on both; `seed_edit_mflux_child.py` runs under the mflux venv's Python (3.13) and never in a test except through `main()` with mflux absent.
- `movie_ui_seedgen.py`, `movie_ui_lib.py` and `movie_ui_server.py` stay standard library only. `bin/seed-edit` and `bin/seed-edit-setup` import only the standard library and `movie_ui_lib` at the top. The page is vanilla ES2017 with no modules.
- Test helpers: `tests/movie_ui_testutil.py` (`set_home`, `make_stub_workspace`, `Running`, `api`, `make_job`, `make_hf_cache`, `kill_everything`, `PNG`, `JPEG`, `WEBP`). `node --check` checks `app.js` when `node` is installed (this Mac has `/opt/homebrew/bin/node`).

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-11-02-seed-generator-design.md`, committed at `2b19b59` on `seed-generator`.
- Its code citations are at `9eb363c`. `2b19b59` adds only the spec, so every line number below (cited "at 2b19b59") is also `9eb363c`'s.
- The user approved the design (spec Status). The spec is binding. Requirements SG1-SG69, tests SGT1-SGT34.
- This plan changes behaviour only where the spec cannot work as written. Each such case is a numbered ruling in "Plan rulings", marked **[defect]**. The other rulings fill a detail the spec leaves open and are marked **[reading]**.

## Global Constraints

From the spec, verbatim (section in brackets):

- [Status] "The implementer makes no design decisions."
- [0.2] "Untouched: every file in `PIPELINE_FILES` (including `character_dataset.py`, `z_image_skill.py`, `bin/character`), `content_safety.py`, `mps_guard.py`, `movie_ui_seedfolder.py`, `movie_ui_batch.py`, the existing `~/mflux` venv. `test_mut26` passes unedited."
- [0.3 Out of scope] "Deleting or renaming runs or seed folders; batch-editing a whole folder (notes). Multi-image Qwen edits, negative prompts, steps/guidance controls, LoRAs on the edit models. mflux q8, or any download outside `bin/seed-edit-setup`. Stopping the 8178 embed server or any server other than the story server the VLM lifecycle already stops. A seed-edit entry on the Batches page; a CLI flag on `bin/ltx-movie`. Running `bin/seed-edit-setup`, a real model or a real server in tests."
- [0.4] "Every SG requirement and SGT test is a must-have. There are no nice-to-haves."
- [SG1] "`movie_ui_seedgen.py` imports only `re`, `secrets`, `time` and `movie_ui_lib as lib`. It is Python 3.9-compatible, never writes, never starts a process; every function is pure except `new_run_id` (clock and random). The server imports it as `import movie_ui_seedgen as seedgen`."
- [SG2] "`bin/seed-edit`, `bin/seed-edit-setup` and `seed_edit_mflux_child.py` are Python 3.9-compatible source (they compile under `/usr/bin/python3`; the child runs under the venv's 3.13). `bin/seed-edit` puts its workspace (`WS = dirname(dirname(realpath(__file__)))`) first on `sys.path` and imports at module top only the standard library and `movie_ui_lib as lib`. PIL, psutil, torch, `z_image_skill`, `content_safety` and `character_dataset` are imported only inside the run functions named in §2."
- [SG3] "Besides the ordinary job record, nothing is added under STATE except uploads written by the Use route (SG52). The run directory and its `run.json` are the only record of a run."
- [1.1] The constants. `movie_ui_seedgen.py`: `PROMPT_MAX = 2000`, `CANDIDATES_MAX = 4`, `CANDIDATES_DEFAULT = 4`, `STRENGTH_MIN, STRENGTH_MAX, STRENGTH_DEFAULT = 0.10, 0.90, 0.45`, `SEED_MAX = 2147483647`, `MIN_FREE_GIB = 2.0`, `RUNS_MAX = 200`, `MODELS = {"zimage": "Z-Image", "qwen": "Qwen-Image-Edit"}`, `RUN_ID_RE = re.compile(r"^se-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")`, `FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")`, `STILL_RE = re.compile(r"^char_[0-9]{2}\.png$")`, `IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")`, `SOURCE_NAMES = ("source.png", "source.jpg", "source.webp")`. `bin/seed-edit`: `LONG_EDGE = 1024`, `MULTIPLE = 16`, `MIN_SIDE = 64`, `PROMPT_MAX = 2000`, `SEED_MAX = 2147483647`, `STRENGTH_DEFAULT = 0.45`, `MIN_FREE_GIB = 2.0`, `ZIMAGE_MIN_AVAIL_GIB = 20.0`, `BF16_MIN_AVAIL_GIB = 64.0`, `MFLUX_MIN_AVAIL_GIB = 32.0`, `AVAIL_WAIT_S = 600`, `CHILD_TIMEOUT_S = 3600`, `EDIT_MODEL`, `EDIT_LORA_REPO`, `EDIT_LORA_FILE`, `EDIT_STEPS = 8`, `EDIT_TRUE_CFG = 1.0`, `Q4_REPO = "mflux-community/qwen-image-edit-2511-mflux-q4"`, `Q4_NAME_PART = "qwen-image-edit-2511"`, `MFLUX_MIN_VERSION = (0, 22, 0)`, `MFLUX_GUIDANCE = 1.0`, `DEFAULT_MFLUX_PYTHON = "~/mflux-edit/.venv/bin/python"`, `SAFETY_SKILL = "seed_edit"`, `BACKEND_LABELS = {"zimage": "Z-Image", "diffusers-bf16": "diffusers bf16", "mflux-q4": "mflux q4"}`. `app.js`: `SEED_LONG_EDGE = 1024`, `SEED_MIN_SIDE = 64`, `SEED_PROMPT_MAX = 2000`, `SEED_POLL_MS = 2000`, `SEED_ACTIVE = ["queued", "starting", "running"]`, `SEED_MODEL_LABELS`, `SEED_BACKEND_LABELS`.
- [SG41] "`SEEDS_LOCK = threading.Lock()` next to `BATCH_LOCK` (guards Keep's name choice and write; never held together with `STORE_LOCK`)."
- [SG56] "Every DOM node is built with `el()`/`button()`; server text goes in through `textContent`/`text`; events use `addEventListener` only. No identifier or call spelled `prompt(` and no `on<x>=` assignment (the page bans `\bprompt\(` and `\son[a-z]+=`)." [0.1] The page bans `https?://`, `\son[a-z]+=`, `style=`, `\balert\(`, `\bconfirm\(`, `\bprompt\(`, `\beval\(` and `new Function` in `index.html`, `app.js` and `app.css`; `test_movie_ui_batch.py:500` pins the substring `["jobs", "log", "host", "batch"]`; three tests pin the `const TABS = [...]` line.
- [9 Rules] "Every test sets `HOME` to `tmp_path/home` (via `mt.set_home` or `monkeypatch.setenv`), removes `HF_HUB_CACHE`, `SEED_EDIT_*`, and sets `HF_HOME` and `Z_IMAGE_HF_HOME` under `tmp_path`." "Process boundaries are stubbed, never crossed for real." "No test uses the real HOME, loads a real model, runs `bin/seed-edit-setup`, or contacts a server other than the in-test `127.0.0.1` one. None touches port 8177 or 8178. No test dispatches a job (HTTP tests only queue)." "HTTP tests put an executable stub at `<ws>/bin/seed-edit` (written by a helper `stub_seed_edit(ws, models, exit=0, stderr="")`) that prints `json.dumps(models)` for `--probe`."
- [9.2] The edits to existing tests, in "one test-only commit, after the feature commit": `test_mut18` and `test_lu1` (`== 57` becomes `== 63`), `tests/test_movie_ui_seedfolder.py` `:921` and `:958` (both `== 57` become `== 63`), `test_mut2` (the key set gains `"seed_run"`), the three pinned `TABS` texts (gain `"seeds", ` after `"compose", `), `NEW_PY` (gains the six new Python files), `test_mut25_source_scan_of_new_python_files`'s `allowed` (gains `"movie_ui_seedgen"`), `copy_ui` (gains `"movie_ui_seedgen.py"`). "Because of `NEW_PY`, no new file may contain `urllib`, `load_module(`, a `match` statement, `X | None` text or `zip(strict=`, docstrings included." Plan ruling PR2 adds one edit the list misses.
- [10 Pass bar] "1. Every new test (SGT1-SGT34) passes. 2. `python3 -m pytest tests/ -q -rA` from `WS` has no failures beyond the 2 known ones: `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`. 3. `python3 tests/test_ltx_movie_offline.py` prints `OK 347/347`. 4. The browser check (§9.3) passes. 5. The live checks (§9.4) pass once the user gives the go; before that they are recorded as not run."
- [11 Rollout] "1. Snapshot `WS` (house rule): `tar czf $S/snapshot-pre-seedgen-9eb363c.tgz` excluding `generated/`. 2. At `9eb363c`, record the full-suite counts, the failure list and the offline line. 3. Feature commit: G1-G7 plus the two new test files. 4. Test-only commit: §9.2. 5. §10 items 1-3, the browser check, an Opus design review of the diff against this spec. 6. On the user's go: L1, then L2, then L3." Step 3's single feature commit is split into one commit per task (Plan ruling PR1). Steps 1 and 2 are already done (see "Before Task 1").

Controller rules (one line each; every task's requirements include them):

- Tests never use the real HOME, never load a model, never render, and never contact real servers (an in-test 127.0.0.1 server is OK).
- Never touch :8177 or :8178 (never start, stop or contact either).
- Never run `bin/seed-edit-setup`, a real `bin/seed-edit` run (only `--probe`, which loads nothing, runs in a test), a model, a download, a venv creation or a pip install. Only the controller does, only in Verification, only on the user's go.
- No new third-party imports in the server (`movie_ui_server.py` gains only `import movie_ui_seedgen as seedgen`).
- Commit trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>".
- Never stage .DS_Store, .claude/, agent/__pycache__/, repo-root bin/, qwen-agent-workspace/bin/action-from-dir, pin-sh2.json, story_bible_*.json, .superpowers/.
- Never read, cat, grep or source ~/.zshenv or any fleet.env, and never print tokens or secrets.
- Never ssh, scp, rsync or HTTP to macstudio, and never read or suggest copying its files.
- Pipeline files unchanged, so `test_mut26` holds.
- Never push. Push and merge are a separate step that needs the user's approval.

House rules (from the prior plans; every task's requirements include them):

- **Where work happens.** This Mac only, no network. The movie-UI tests start servers on `127.0.0.1` inside the test; nothing else listens. Never render, train, edit an image with a model, or load a model. No job ever runs in a task.
- **The checkout.** Never touch the main checkout `/Users/reubenpatterson/local_agent_harness`. Every command runs in the worktree `$S/seedgen-wt`, on branch `seed-generator`. Never git stash, reset or check out other people's work.
- **Python.** Every new or changed file must compile on Python 3.9.6 and 3.13. So use none of: the `match` statement, `X | Y` type expressions, the walrus operator, `str.removeprefix`, `zip(strict=)` and parenthesised context managers. The code blocks below use none of them.
- **Editing.** Executors make every change to a tracked file with the Edit tool. Each new file is created with the Write tool in the step that names it, and edited with the Edit tool from then on. The two new `bin/` files also get `chmod 755` right after their Write (Plan ruling PR21); that changes the mode, not the content. Never use `rm`, `sed -i`, a redirect or a script to change a tracked file.
- **Git.** Stage only the paths a task names, and check `git diff --cached --name-only` before every commit. Every commit command passes the trailer as a second `-m`.
- **Paths.**
  - `S` = `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`.
  - `WS` = `$S/seedgen-wt/qwen-agent-workspace`, and `D` = `$S/seedgen-baseline`.
  - The git root is `$S/seedgen-wt`, so `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix.
  - Run every command from `WS`. Shell variables do not persist between commands, so every block defines the variables it uses.
- **Code blocks** are copied byte for byte. An Edit step's old text must occur exactly once in the file at that moment, with or without its last newline. If it does not, stop and report; do not adapt it. Every Create and Edit below was replayed in order on a scratch copy of `2b19b59`'s `WS`, and each old text occurred exactly once at its turn (see "Execution handoff").
- **The compile check** (Step 4 of each code task) is this command, with the task's Python files as `FILES`. Expected: two lines, `compiled N` for 3.9 and then for 3.13.

```bash
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' FILES; done
```

## Review Focus

These five inputs and failure modes are the ones most likely to reach a user first, the spec implies them, and no SGT row exercises them. Each is pinned by a test in the task that owns its code. The tests are named `test_sg_review_focus_N_...` (Plan ruling PR24).

1. **A phone JPEG or a WebP file as the source.**
   - SGT23 queues only a PNG upload. A JPEG or WebP upload must keep its extension through the server's copy (`source.<ext>` from the upload ID), the job fields (`source_file`), the argv (`--source`), `run.json`'s `source` and the run view's `source` path (which `SOURCE_NAMES` gates; a wrong extension would hide the before image).
   - Expected: for `mt.JPEG` and `mt.WEBP` uploads, the run directory holds exactly `run.json` and `source.jpg` / `source.webp` (byte-equal to the upload), and every copy of the name agrees.
   - Test: `test_sg_review_focus_1_jpeg_and_webp_sources_keep_their_extension` (Task 5).
2. **Keep double-clicked, or clicked in two tabs at once.**
   - SG50/SG51 claim names under `SEEDS_LOCK` with `O_EXCL`. SGT28 keeps three times in sequence only.
   - Expected: four concurrent Keep requests of the same candidate into `heroes` all answer 201 with four distinct files `<run>-01.png`, `-01-2.png`, `-01-3.png`, `-01-4.png`, each byte-equal to the candidate.
   - Test: `test_sg_review_focus_2_keep_clicked_four_times_at_once` (Task 5).
3. **A prompt that looks like shell or argparse input.**
   - The prompt travels from the request through `lib.seed_edit_argv` into `bin/seed-edit`'s argparse. Quotes, newlines, `$(...)`, `--model qwen` inside the text, `a=b --c=d -e`, emoji and a 2000-character prompt must arrive unchanged (SG33 row 4 already refuses a leading `-`).
   - Expected: for each, `validate_run_request` accepts it, the argv carries it as one element, `tool.main(argv[2:])` exits 0, and `run.json`'s `prompt` and the Z-Image call's prompt equal it.
   - Test: `test_sg_review_focus_3_prompts_survive_the_argv_round_trip` (Task 3).
4. **A progress bar in a Qwen child's output.**
   - The parent finds candidates by matching whole lines (SG19, SG20). diffusers, transformers and mflux draw tqdm bars, which end in a carriage return and no newline when a bar is cleared, so a candidate line can follow `...\r` on the same physical line. SG21's `text=True` reads with universal newlines, which split at the `\r`; the pin keeps that property (a switch to binary mode or `newline=""` would make every candidate `failed`).
   - Expected: an mflux stub that prints `  0%|...\r100%|...\r` before each done line, and a bf16 stub that prints `Loading pipeline components...: 100%|...\r` before each candidate line, both end with every candidate `ok`, and the echoed log shows the bar and the done line on separate lines.
   - Test: `test_sg_review_focus_4_progress_bars_in_child_lines` (Task 3).
5. **The page's size line disagreeing with the tool.**
   - SG58's `seedCanvas` is a JavaScript copy of SG8's integer math; the page gates Generate on it (too small) and shows `<W0> × <H0> → <W> × <H>`. A drift would let the page queue a run the tool refuses, or show the wrong size.
   - Expected: for 26 sizes (SG8's nine, phone and HD sizes, 1-pixel and 8192-pixel edges), node's `seedCanvas(w, h)` equals the tool's `canvas(w, h)`, and for every size the tool refuses the page gets the same too-small numbers.
   - Test: `test_sg_review_focus_5_the_page_canvas_matches_the_tool` (Task 6; skipped when `node` is absent).

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `movie_ui_seedgen.py` | Create (Task 1) | The pure core: spec 1.1's constants, `FOLDER_MSG`, `validate_run_request`, `valid_folder`, `new_run_id`, `keep_name`, `capability`, `availability_error`. Never writes. |
| `movie_ui_lib.py` | Modify (Task 2) | `job_vlm`'s forbidden tuple gains `"seed-edit"`; `seed_edit_argv`; `_probe_model` and `seed_edit_check`; `SEED_CAND_RE` and the `seed-edit` branch of `ProgressParser`. |
| `bin/seed-edit` | Create (Task 3) | The tool: argv, canvas, run.json, preflight, backend choice, probe, the three backends, `run_child`. |
| `seed_edit_mflux_child.py` | Create (Task 4) | The mflux q4 child (spec SG25's body). |
| `bin/seed-edit-setup` | Create (Task 4) | The venv + download script (controller only, on the user's go). |
| `movie_ui_server.py` | Modify (Task 5) | The import, `SEEDS_LOCK`, `_RUN`/`_SAMPLE_RUN`, six routes, the `seed_edit` capability and its refresh, the `seed_run` summary key, `store_upload`, and the seed generator section (`seeds_root`, `runs_root`, `seed_free_gib`, `_seed_run`, `_candidates`, `_cand_file`, `_run_job`, `run_state`, `run_view`, `_seed_source`, six handlers, `_candidate_number`, `_ok_candidate`). |
| `static/movie-ui/index.html`, `app.js`, `app.css` | Modify (Task 6) | The Seeds tab, panel and functions; the Characters still button; `jobLabel`, `renderProgress`, `stopPolling`, `selectWorkspace`, `renderBadges`, `showTab`, `start`; the CSS. |
| `tests/test_seed_edit_tool.py` | Create (Task 3), extend (Task 4) | SGT1-SGT14, Review Focus 3 and 4 (T3); SGT15, SGT16 (T4). |
| `tests/test_movie_ui_seedgen.py` | Create (Task 1), extend (Tasks 2, 5, 6, 7) | SGT17 (T1); SGT18, SGT19 (T2); SGT20-SGT32, Review Focus 1 and 2 (T5); SGT33, Review Focus 5 (T6); SGT34 (T7). |
| `tests/test_movie_ui_http.py`, `test_location_ui.py`, `test_movie_ui_seedfolder.py`, `test_movie_ui_batch.py`, `test_movie_ui_seams.py`, `test_movie_ui_builder.py`, `tests/movie_ui_testutil.py` | Modify (Task 7 only) | The spec 9.2 re-baseline (plus PR2's `test_sdt19` edit). |

**Task split.** Each task is the smallest unit with its own test cycle and a reviewer gate:
- Task 1 is the pure core, which Tasks 5 and 3 (Review Focus 3) consume.
- Task 2 is the library side the server needs (policy, argv, probe, progress), testable without the server.
- Task 3 is the whole tool. Its backends share the run.json writer, the candidate lines and the failure path, so they ship together; the Qwen children are stubbed, so the child file itself is not needed yet.
- Task 4 is the two files no test executes for real (the mflux child and the setup script), each pinned by source checks.
- Task 5 is the server. The six routes, the capability and the summary key are tested only through the endpoints, and SGT20 asserts all 63 routes, so the server ships whole.
- Task 6 is the page.
- Task 7 is the spec 9.2 test-only commit and SGT34 (Plan ruling PR6).

The browser check, the pass bar, the design review and the live checks need a person, a browser, a running movie-ui or the user's go, so they are the controller's "Verification" section, not an implementer task. The spec requires no docs or README change.

## Between tasks: the existing suite

**The choice.** Feature tasks do **not** edit the existing tests whose assertions the feature changes (spec 9.2). Those tests stay red from the task that first breaks them until Task 7's one test-only commit. Every other existing test must stay green in every task.

**Precision.** The list below was measured on the plan's replay (see "Execution handoff"): fifteen existing test files (`tests/test_movie_ui_http.py`, `test_location_ui.py`, `test_movie_ui_seams.py`, `test_movie_ui_builder.py`, `test_movie_ui_batch.py`, `test_movie_ui_checks.py`, `test_movie_ui_progress.py`, `test_movie_ui_seedfolder.py`, `test_vlm_lifecycle.py`, `test_soft_panel_count.py`, `test_location_lib.py`, `test_model_download.py`, `test_movie_ui_actions.py`, `test_chained_end_frames.py`, `test_movie_ui_jobs.py`) were run on the unmodified copy and after Tasks 4, 5, 6 and 7. After Task 4 nothing changed; after Task 5 exactly the seven passes below marked T5 were lost; after Task 6 also the three marked T6; after Task 7 the results equalled the unmodified copy's. `test_mut15` was not run in the replay (it starts a `bin/movie-ui` process); its cause was confirmed by importing `movie_ui_server` from a copy made like `copy_ui` (`ModuleNotFoundError: No module named 'movie_ui_seedgen'`), and the same import succeeds once the copy also holds `movie_ui_seedgen.py`.

| Code | Cause | First task |
|---|---|---|
| R63 | `test_mut18_every_api_route_needs_the_token`, `test_lu1_the_location_routes_need_the_token`, `test_sdt11_the_route_and_its_token` and `test_sdt29_the_characters_route_and_its_token`: `ROUTES` has 63 entries, not 57 | 5 |
| KEYS | `test_mut2_preview_argv_is_the_job_argv` (the key set) and `test_sdt19_the_seed_folder_tag` (`len(j) == 15`): a job summary has 16 keys (`seed_run`) | 5 |
| IMP | `test_mut25_source_scan_of_new_python_files`: `movie_ui_server.py` imports `movie_ui_seedgen`, which the `allowed` set lacks | 5 |
| CPY | `test_mut15_bin_movie_ui_lock_port_and_startup_lines`: `copy_ui` does not copy `movie_ui_seedgen.py`, so the copied `bin/movie-ui` cannot import `movie_ui_server` and prints nothing | 5 |
| TABS | `test_lu13_the_static_page`, `test_bt13_the_static_page` and `test_ct27_the_static_page`: the pinned `const TABS = [...]` line gains `"seeds"` | 6 |

`NEW_PY`'s missing entries break nothing (they only widen the compile and scan); Task 7 adds them.

**Expected failures**, written to `$D/expected-failures.txt` in "Before Task 1" Step 3. A line is `T<first task> <test id> <reason>`:

```text
# seed generator plan: existing tests expected to fail from the given task until Task 7
T5 tests/test_movie_ui_http.py::test_mut18_every_api_route_needs_the_token R63
T5 tests/test_location_ui.py::test_lu1_the_location_routes_need_the_token R63
T5 tests/test_movie_ui_seedfolder.py::test_sdt11_the_route_and_its_token R63
T5 tests/test_movie_ui_seedfolder.py::test_sdt29_the_characters_route_and_its_token R63
T5 tests/test_movie_ui_http.py::test_mut2_preview_argv_is_the_job_argv KEYS
T5 tests/test_movie_ui_seedfolder.py::test_sdt19_the_seed_folder_tag KEYS
T5 tests/test_movie_ui_builder.py::test_mut25_source_scan_of_new_python_files IMP
T5 tests/test_movie_ui_jobs.py::test_mut15_bin_movie_ui_lock_port_and_startup_lines CPY
T6 tests/test_location_ui.py::test_lu13_the_static_page TABS
T6 tests/test_movie_ui_batch.py::test_bt13_the_static_page TABS
T6 tests/test_movie_ui_seams.py::test_ct27_the_static_page TABS
```

**Gate rule** (Step 4 of every code task):
1. Every new test passes. A new test is one in `tests/test_seed_edit_tool.py` or `tests/test_movie_ui_seedgen.py`, or any test ID the baseline does not have.
2. The baseline failures fail with the same messages.
3. Every lost baseline pass is listed for a task at or before this one in `$D/expected-failures.txt`.
4. `tests/test_ltx_movie_offline.py` prints the same last line as at the baseline.

**When the gate prints `GATE STOP`:**
- The executor stops and reports the UNEXPECTED or NEW-TEST-FAIL IDs, together with the output of `python3 -B -m pytest -q -p no:cacheprovider --tb=short <ids>`.
- The controller has an Opus reviewer rule on each ID. A lost pass that the list does not name is a defect in this task's code. The controller writes the exact fix, and the gate reruns.
- The list grows only for the timing-sensitive tests below.

**Timing-sensitive tests unrelated to this plan.** These are `tests/test_fleet_tracing.py::test_trt41a_trace_cli_on_one_agent` and `tests/test_fleet_integration.py::test_t47_signatures_and_loopback_rules`. If the gate lists one of them as UNEXPECTED, rerun it alone with `python3 -B -m pytest -q -p no:cacheprovider <node id>`. If it passes alone, the controller appends `T<N> <node id> flaky` to `$D/expected-failures.txt`, and Verification V1 rechecks it. `test_sgt10_the_mflux_child_fails_or_times_out` (a 1-second child timeout) and `test_sg_review_focus_2_keep_clicked_four_times_at_once` (four threads) passed three replay runs in a row; a new test is never added to the list.

**Must stay green in every task:** every `tests/test_movie_ui_*.py` test other than the ten listed; every `tests/test_location_ui.py` test other than `test_lu1` and `test_lu13`; `tests/test_vlm_lifecycle.py` (including `test_vl1_job_vlm` and `test_vl26_page_gate_and_warn_style`), `tests/test_soft_panel_count.py`, `tests/test_location_lib.py`, `tests/test_model_download.py` and `tests/test_character_dataset.py` (other than the baseline failure). In particular `test_mut24_page_headers_and_asset_rules`, `test_sdt25_the_static_page`, `test_sf_review_focus_5_the_page_sample_id_matches_the_server`, `test_sf_final_review_queue_and_confirm_guards`, `test_mut9_host_and_refresh` and `test_mut26_pipeline_files_are_unchanged`. None is in the list, so a failure there stops the gate.

---

## Before Task 1: the plan commit, the snapshot, the baseline (controller; no code)

The snapshot (spec 11 step 1) and the baseline (spec 11 step 2) are already done; Steps 2 and 3 only confirm them. Step 3 also writes the gate files.

- [ ] **Step 1: Confirm the plan commit and the tree.**

The plan is committed on `seed-generator` as `docs: seed generator implementation plan`, directly on top of the spec commit `2b19b59`.

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/seedgen-wt/qwen-agent-workspace
git branch --show-current                                   # expected: seed-generator
git log -3 --format=%h' '%s                                 # expected: <plan sha> docs: seed generator implementation plan, then 2b19b59, 9eb363c
git diff --stat 9eb363c HEAD -- . ':(exclude)docs' | tail -1   # expected: no output
git status --short                                          # expected: no output
ls movie_ui_seedgen.py bin/seed-edit bin/seed-edit-setup seed_edit_mflux_child.py tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py 2>&1 | grep -c "No such file"   # expected: 6
wc -l movie_ui_lib.py movie_ui_server.py static/movie-ui/index.html static/movie-ui/app.js static/movie-ui/app.css tests/movie_ui_testutil.py tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_builder.py tests/test_movie_ui_seedfolder.py tests/test_movie_ui_batch.py tests/test_movie_ui_seams.py | head -12
```

Expected `wc -l` counts (at `2b19b59`): `movie_ui_lib.py` 2339, `movie_ui_server.py` 3085, `index.html` 425, `app.js` 2684, `app.css` 100, `movie_ui_testutil.py` 553, `test_movie_ui_http.py` 1792, `test_location_ui.py` 425, `test_movie_ui_builder.py` 298, `test_movie_ui_seedfolder.py` 1164, `test_movie_ui_batch.py` 520, `test_movie_ui_seams.py` 432. If any value differs, stop and report: every Edit below was written against this tree.

- [ ] **Step 2: Confirm the compressed snapshot (house rule; spec 11 step 1; already taken).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
ls -l $S/snapshot-pre-seedgen-9eb363c.tgz
tar tzf $S/snapshot-pre-seedgen-9eb363c.tgz | grep -c 'movie_ui_server.py$'   # expected: 1
tar tzf $S/snapshot-pre-seedgen-9eb363c.tgz | grep -c '/generated/'           # expected: 0
```

If the file is missing, take it now: `tar czf $S/snapshot-pre-seedgen-9eb363c.tgz --exclude qwen-agent-workspace/generated -C $S/seedgen-wt qwen-agent-workspace`.

- [ ] **Step 3: Confirm the baseline (spec 11 step 2; already recorded) and write the gate files.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/seedgen-baseline
tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
grep -c '^PASSED ' $D/baseline-pytest.txt
cat $D/baseline-offline.txt
```

Expected: `2 failed, 2359 passed, 2 skipped, 7622 warnings in 1053.47s (0:17:33)`; the two `FAILED` lines `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets - AssertionError: b...`; `2359`; `OK 347/347`. These files **are** the baseline. Every later "baseline" in this plan means them.

Then write two scratch files with the Write tool. They are outside the repository and never staged.

1. `$D/expected-failures.txt`: exactly the `text` block of "Between tasks" above.
2. `$D/gate.py`: exactly this (the seed-folder plan's gate with `NEW_FILES` naming the two new test files). If the controller already has a gate script that reads `T<n> <test-id> <note>` lines, it may use that instead.

```python
"""The task gate of the seed generator plan: a full pytest -rA run against the baseline. A new
test is one of the two new files or any test ID the baseline does not have."""
import re
import sys

base_file, run_file, expected_file, task = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
NEW_FILES = ("tests/test_seed_edit_tool.py::", "tests/test_movie_ui_seedgen.py::")


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

**The gate block** (Step 4 of every code task; `N` is the task number). It is a full run of about 18 minutes, which may run in the background:

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/seedgen-baseline
N=1
cd $S/seedgen-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/task-$N-pytest.txt 2>&1; tail -1 $D/task-$N-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/task-$N-pytest.txt $D/expected-failures.txt $N
diff <(python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1) $D/baseline-offline.txt && echo "offline unchanged"
```

Expected: `GATE PASS`, `new tests <count>, not passing 0`, `baseline failures still failing 2 of 2`, and `offline unchanged`. Each task's Step 4 gives its count and its `LOST ... listed` lines. On `GATE STOP`, follow the gate rule ("Between tasks").

---

### Task 1: `movie_ui_seedgen.py`, the pure core (SG1, SG33-SG37; SGT17)

This task implements:
- Spec 1.1's `movie_ui_seedgen.py` constants, verbatim, plus `FOLDER_MSG` (SG34's text) and `SOURCE_MSG` (SG33 row 10's text).
- SG33 `validate_run_request(body)`: rows 1-14 in order, the first failure only; rows 10-14 live in the helper `_source(value)`. `clean` is SG33's shape.
- SG34 `valid_folder`, SG35 `new_run_id` and `keep_name`, SG36 `capability`, SG37 `availability_error`.

Tests: SGT17 in the new `tests/test_movie_ui_seedgen.py` (33 request cases plus four tests). Its imports of `hashlib`, `json`, `shutil`, `subprocess`, `sys`, `threading` and `time` are for Tasks 2, 5, 6 and 7, which append to the file.

**Files:**
- Create: `movie_ui_seedgen.py`, `tests/test_movie_ui_seedgen.py`.
- Read only (at 2b19b59): `movie_ui_lib.py`: `UPLOAD_ID_RE` `:36`, `CHARACTER_NAME_RE` `:38`, `_is_int` `:1307`, `_is_number` `:1311`, `_argv_safe` `:1371-1379`; `movie_ui_seedfolder.py` (the module style).

**Interfaces:**
- Consumes (existing, `movie_ui_lib`): `UPLOAD_ID_RE`, `CHARACTER_NAME_RE`, `_is_int(value) -> bool`, `_is_number(value) -> bool`, `_argv_safe(value) -> bool`.
- Produces, in `movie_ui_seedgen` (later tasks use these names exactly):
  - the constants of spec 1.1, `FOLDER_MSG`, `SOURCE_MSG`;
  - `validate_run_request(body) -> (clean, None)` or `(None, message)`; `clean` is `{"prompt": str (as sent), "model": "zimage" or "qwen", "strength": float or None, "candidates": int, "seed": int or None, "source": {"kind": "upload", "upload_id"} or {"kind": "run", "run", "n"} or {"kind": "character", "character", "still"}}`;
  - `valid_folder(name) -> bool`; `new_run_id() -> str` (matches `RUN_ID_RE`); `keep_name(run, n, k) -> str`;
  - `capability(models, detail, checked) -> {"ok", "reason", "checked", "models"}`; `availability_error(models, detail, model) -> str or None`.

- [ ] **Step 1: Write the failing tests.**

Create `tests/test_movie_ui_seedgen.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""Tests for the seed generator's movie-ui side (docs/superpowers/specs/2026-11-02-seed-generator-
design.md, Section 9: SGT17-SGT34, with the plan's Review Focus pins 1, 2 and 5): the pure module
movie_ui_seedgen, the movie_ui_lib hooks (job policy, argv, probe, progress), the six
/api/seeds/ routes, the seed_edit capability, the job summary key and the static page.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedgen.py

Rules (spec Section 9):
- The HTTP tests use the env fixture (like tests/test_movie_ui_seedfolder.py's): mt.set_home,
  mt.make_stub_workspace and the in-test mt.Running server on 127.0.0.1, with
  CHARACTER_LIBRARY_DIR removed unless a test sets it.
- Every test that touches the environment sets HOME under tmp_path, removes HF_HUB_CACHE and
  every SEED_EDIT_* variable, and sets HF_HOME and Z_IMAGE_HF_HOME under tmp_path.
- The workspace's bin/seed-edit is the stub written by stub_seed_edit(ws, models, ...); it prints
  json.dumps(models) for --probe. srv.seed_free_gib is replaced by a stub. Uploads go through
  POST /api/uploads with magic-number bytes (mt.PNG, mt.JPEG, mt.WEBP plus a suffix).
- No test uses the real HOME, loads a model, runs bin/seed-edit-setup, or contacts a server other
  than the in-test 127.0.0.1 one. None touches port 8177 or 8178. The VLM lifecycle is off
  (conftest.py). No test dispatches a job (the HTTP tests only queue).
Stdlib plus pytest.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

import pytest

import movie_ui_testutil as mt
import movie_ui_lib as lib
import movie_ui_seedgen as seedgen
import movie_ui_server as srv

WS = mt.WS
UP = "a" * 64 + ".png"
RUN = "se-20261102-141500-a1b2"


# --- SGT17 (SG33-SG37): the pure module -------------------------------------------------------------

def _req(**overrides):
    body = {"ws": "/abs/ws", "source": {"upload_id": UP}, "prompt": "make it night", "model": "zimage",
            "strength": 0.45, "candidates": 2, "seed": 7}
    body.update(overrides)
    return body


SOURCE_MSG = "source must be {upload_id}, {run, n} or {character, still}"
REQUEST_CASES = [
    (_req(prompt=5), "prompt is required"),
    (_req(prompt="   "), "prompt is required"),
    (_req(prompt="x" * 2001), "prompt is longer than 2000 characters"),
    (_req(prompt="a\x00b"), "prompt contains invalid characters"),
    (_req(prompt="a\ud800b"), "prompt contains invalid characters"),
    (_req(prompt="  -x"), "prompt must not start with '-'"),
    (_req(model="flux"), "model must be zimage or qwen"),
    (_req(model=None), "model must be zimage or qwen"),
    (_req(model="qwen", strength=0.5), "strength is only for zimage"),
    (_req(strength=0.05), "strength must be a number from 0.10 to 0.90"),
    (_req(strength=0.95), "strength must be a number from 0.10 to 0.90"),
    (_req(strength="0.5"), "strength must be a number from 0.10 to 0.90"),
    (_req(strength=True), "strength must be a number from 0.10 to 0.90"),
    (_req(candidates=0), "candidates must be an integer from 1 to 4"),
    (_req(candidates=5), "candidates must be an integer from 1 to 4"),
    (_req(candidates=2.0), "candidates must be an integer from 1 to 4"),
    (_req(candidates="2"), "candidates must be an integer from 1 to 4"),
    (_req(seed=-1), "seed must be an integer from 0 to 2147483647"),
    (_req(seed=2147483648), "seed must be an integer from 0 to 2147483647"),
    (_req(seed="7"), "seed must be an integer from 0 to 2147483647"),
    (_req(source="x"), SOURCE_MSG),
    (_req(source={}), SOURCE_MSG),
    (_req(source={"upload_id": 5}), SOURCE_MSG),
    (_req(source={"upload_id": UP, "run": RUN}), SOURCE_MSG),
    (_req(source={"run": RUN, "n": "1"}), SOURCE_MSG),
    (_req(source={"run": RUN, "n": True}), SOURCE_MSG),
    (_req(source={"character": "kyra"}), SOURCE_MSG),
    (_req(source={"upload_id": "x.png"}), "source upload x.png not found"),
    (_req(source={"run": "junk", "n": 1}), "unknown source run junk"),
    (_req(source={"run": RUN, "n": 5}), "source run %s has no ok candidate 5" % RUN),
    (_req(source={"run": RUN, "n": 0}), "source run %s has no ok candidate 0" % RUN),
    (_req(source={"character": "Kyra", "still": "char_01.png"}), "unknown character still Kyra/char_01.png"),
    (_req(source={"character": "kyra", "still": "char_1.png"}), "unknown character still kyra/char_1.png"),
]


@pytest.mark.parametrize("body,message", REQUEST_CASES, ids=["case%d" % (i + 1) for i in range(len(REQUEST_CASES))])
def test_sgt17_validate_run_request_refusals(body, message):
    assert seedgen.validate_run_request(body) == (None, message)


def test_sgt17_validate_run_request_order_and_defaults():
    assert seedgen.validate_run_request(_req(prompt="", model="flux")) == (None, "prompt is required")
    assert seedgen.validate_run_request(_req(model="flux", seed=-1)) == (None, "model must be zimage or qwen")
    assert seedgen.validate_run_request(_req(candidates=0, source="x")) == (
        None, "candidates must be an integer from 1 to 4")
    clean, error = seedgen.validate_run_request(_req(extra=1))
    assert error is None
    assert clean == {"prompt": "make it night", "model": "zimage", "strength": 0.45, "candidates": 2, "seed": 7,
                     "source": {"kind": "upload", "upload_id": UP}}
    bare = {"prompt": " a quiet street at dusk ", "model": "zimage", "source": {"run": RUN, "n": 3}}
    clean, error = seedgen.validate_run_request(bare)
    assert error is None
    assert clean == {"prompt": " a quiet street at dusk ", "model": "zimage", "strength": 0.45,
                     "candidates": 4, "seed": None, "source": {"kind": "run", "run": RUN, "n": 3}}
    assert isinstance(seedgen.validate_run_request(_req(strength=1 / 2))[0]["strength"], float)
    assert seedgen.validate_run_request(_req(strength=None, candidates=None, seed=None))[0]["strength"] == 0.45
    clean, error = seedgen.validate_run_request(_req(model="qwen", strength=None,
                                                     source={"character": "kyra", "still": "char_05.png"}))
    assert error is None and clean["strength"] is None
    assert clean["source"] == {"kind": "character", "character": "kyra", "still": "char_05.png"}
    assert seedgen.validate_run_request(_req(prompt="x" * 2000))[1] is None


def test_sgt17_folders_run_ids_and_keep_names():
    for name in ("heroes", "a.b-c_d", "A" * 64, "9lives"):
        assert seedgen.valid_folder(name) is True, name
    for name in ("", "runs", "Runs", "RUNS", "a..b", "-x", ".x", "A" * 65, "a/b", 5, None):
        assert seedgen.valid_folder(name) is False, name
    assert seedgen.FOLDER_MSG == ("folder must be 1 to 64 letters, digits, '.', '_' or '-', start with a letter "
                                  "or digit, contain no '..' and not be 'runs'")
    assert seedgen.RUN_ID_RE.fullmatch(seedgen.new_run_id())
    assert seedgen.keep_name(RUN, 2, 1) == RUN + "-02.png"
    assert seedgen.keep_name(RUN, 2, 3) == RUN + "-02-3.png"


def test_sgt17_capability_and_availability():
    ok_z = {"ok": True, "reason": None, "backend": "zimage"}
    no_z = {"ok": False, "reason": "torch not importable by /py", "backend": None}
    ok_q = {"ok": True, "reason": None, "backend": "mflux-q4"}
    no_q = {"ok": False, "reason": "diffusers bf16: x; mflux q4: y", "backend": None}
    both = {"zimage": ok_z, "qwen": ok_q}
    assert seedgen.capability(both, None, "T") == {"ok": True, "reason": None, "checked": "T", "models": both}
    partial = {"zimage": ok_z, "qwen": no_q}
    assert seedgen.capability(partial, None, "T") == {"ok": True, "reason": None, "checked": "T", "models": partial}
    none_ok = {"zimage": no_z, "qwen": no_q}
    assert seedgen.capability(none_ok, None, "T") == {
        "ok": False, "reason": "Z-Image: torch not importable by /py; Qwen-Image-Edit: diffusers bf16: x; mflux q4: y",
        "checked": "T", "models": none_ok}
    assert seedgen.capability(None, "bin/seed-edit --probe exited 1: boom", "T") == {
        "ok": False, "reason": "bin/seed-edit --probe exited 1: boom", "checked": "T", "models": None}
    assert seedgen.availability_error(both, None, "qwen") is None
    assert seedgen.availability_error(partial, None, "zimage") is None
    assert seedgen.availability_error(partial, None, "qwen") == (
        "Qwen-Image-Edit is unavailable: diffusers bf16: x; mflux q4: y")
    assert seedgen.availability_error(none_ok, None, "zimage") == "Z-Image is unavailable: torch not importable by /py"
    assert seedgen.availability_error(None, "boom", "zimage") == "cannot check the seed models: boom"


def test_sgt17_the_module_imports():
    with open(os.path.join(WS, "movie_ui_seedgen.py"), encoding="utf-8") as f:
        source = f.read()
    assert sorted(re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M)) == [
        "movie_ui_lib", "re", "secrets", "time"]
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedgen.py 2>&1 | tail -1
```

Expected: `1 error` (collection: `ModuleNotFoundError: No module named 'movie_ui_seedgen'`).

- [ ] **Step 3: Implement.**

Create `movie_ui_seedgen.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""movie_ui_seedgen -- the seed generator's pure core: the Seeds tab's request rules, the seed
folder rule, the run ID, Keep's file names and the seed_edit capability shape
(docs/superpowers/specs/2026-11-02-seed-generator-design.md, deliverable G4, Section 5.1).

Standard library plus movie_ui_lib only (SG1). Valid on Python 3.9 and 3.13. This module never
writes and never starts a process. Every function is pure except new_run_id, which reads the
clock and draws random digits.
"""

import re
import secrets
import time

import movie_ui_lib as lib

PROMPT_MAX = 2000
CANDIDATES_MAX = 4
CANDIDATES_DEFAULT = 4
STRENGTH_MIN, STRENGTH_MAX, STRENGTH_DEFAULT = 0.10, 0.90, 0.45
SEED_MAX = 2147483647
MIN_FREE_GIB = 2.0
RUNS_MAX = 200
MODELS = {"zimage": "Z-Image", "qwen": "Qwen-Image-Edit"}
RUN_ID_RE = re.compile(r"^se-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
STILL_RE = re.compile(r"^char_[0-9]{2}\.png$")          # movie_ui_server.STILL_FILE_RE
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
SOURCE_NAMES = ("source.png", "source.jpg", "source.webp")
FOLDER_MSG = ("folder must be 1 to 64 letters, digits, '.', '_' or '-', start with a letter or digit, "
              "contain no '..' and not be 'runs'")
SOURCE_MSG = "source must be {upload_id}, {run, n} or {character, still}"


def _absent(body, key):
    return body.get(key) is None


def _source(value):
    """SG33 rows 10-14: (clean source, None) or (None, error)."""
    keys = set(value) if isinstance(value, dict) else None
    if keys == {"upload_id"} and isinstance(value["upload_id"], str):
        upload_id = value["upload_id"]
        if not lib.UPLOAD_ID_RE.fullmatch(upload_id):
            return None, "source upload %s not found" % upload_id
        return {"kind": "upload", "upload_id": upload_id}, None
    if keys == {"run", "n"} and isinstance(value["run"], str) and lib._is_int(value["n"]):
        run, n = value["run"], value["n"]
        if not RUN_ID_RE.fullmatch(run):
            return None, "unknown source run %s" % run
        if not 1 <= n <= CANDIDATES_MAX:
            return None, "source run %s has no ok candidate %s" % (run, n)
        return {"kind": "run", "run": run, "n": n}, None
    if keys == {"character", "still"} and isinstance(value["character"], str) and isinstance(value["still"], str):
        character, still = value["character"], value["still"]
        if not (lib.CHARACTER_NAME_RE.fullmatch(character) and STILL_RE.fullmatch(still)):
            return None, "unknown character still %s/%s" % (character, still)
        return {"kind": "character", "character": character, "still": still}, None
    return None, SOURCE_MSG


def validate_run_request(body):
    """SG33: (clean, None) or (None, error) for a POST /api/seeds/runs body (a dict); the first
    failing rule only, in the spec's order. Extra keys are ignored."""
    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None, "prompt is required"
    if len(prompt) > PROMPT_MAX:
        return None, "prompt is longer than 2000 characters"
    if not lib._argv_safe(prompt):
        return None, "prompt contains invalid characters"
    if prompt.strip().startswith("-"):
        return None, "prompt must not start with '-'"
    model = body.get("model")
    if model not in MODELS:
        return None, "model must be zimage or qwen"
    strength = body.get("strength")
    if model == "qwen" and not _absent(body, "strength"):
        return None, "strength is only for zimage"
    if model == "zimage" and not _absent(body, "strength") and not (
            lib._is_number(strength) and STRENGTH_MIN <= strength <= STRENGTH_MAX):
        return None, "strength must be a number from 0.10 to 0.90"
    candidates = body.get("candidates")
    if not _absent(body, "candidates") and not (lib._is_int(candidates) and 1 <= candidates <= CANDIDATES_MAX):
        return None, "candidates must be an integer from 1 to 4"
    seed = body.get("seed")
    if not _absent(body, "seed") and not (lib._is_int(seed) and 0 <= seed <= SEED_MAX):
        return None, "seed must be an integer from 0 to 2147483647"
    source, error = _source(body.get("source"))
    if error is not None:
        return None, error
    if model == "zimage":
        strength = STRENGTH_DEFAULT if strength is None else float(strength)
    else:
        strength = None
    return {"prompt": prompt, "model": model, "strength": strength,
            "candidates": CANDIDATES_DEFAULT if candidates is None else candidates,
            "seed": seed, "source": source}, None


def valid_folder(name):
    """SG34: a seed folder name: FOLDER_RE, no "..", and not "runs" in any case."""
    return (isinstance(name, str) and FOLDER_RE.fullmatch(name) is not None and ".." not in name
            and name.lower() != "runs")


def new_run_id():
    """SG35: "se-" + UTC %Y%m%d-%H%M%S + "-" + 4 hex digits (matches RUN_ID_RE)."""
    return "se-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(2)


def keep_name(run, n, k):
    """SG35, SG51: the k-th candidate file name Keep tries for candidate n of run."""
    return "%s-%02d.png" % (run, n) if k == 1 else "%s-%02d-%d.png" % (run, n, k)


def capability(models, detail, checked):
    """SG36: the seed_edit capability from lib.seed_edit_check's (models, detail)."""
    if models is None:
        return {"ok": False, "reason": detail, "checked": checked, "models": None}
    ok = any(m["ok"] for m in models.values())
    reason = None if ok else "; ".join("%s: %s" % (MODELS[k], models[k]["reason"]) for k in ("zimage", "qwen"))
    return {"ok": ok, "reason": reason, "checked": checked, "models": models}


def availability_error(models, detail, model):
    """SG37: the 409 error for model, or None when it can run."""
    if models is None:
        return "cannot check the seed models: %s" % detail
    if not models[model]["ok"]:
        return "%s is unavailable: %s" % (MODELS[model], models[model]["reason"])
    return None
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedgen.py 2>&1 | tail -1
```

Expected: `37 passed` (SGT17's 33 request cases and four tests). Run the compile check with `FILES` = `movie_ui_seedgen.py tests/test_movie_ui_seedgen.py`; expected: `compiled 2` twice. Then run the gate block with `N=1`. Expected: `GATE PASS`, `lost 0`, `new tests 37, not passing 0`, `baseline failures still failing 2 of 2`, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
git add movie_ui_seedgen.py tests/test_movie_ui_seedgen.py
git diff --cached --name-only    # expected: those 2 paths
git commit -m "feat(movie-ui): movie_ui_seedgen, the seed generator's pure core: request rules, folder rule, run ID, keep names, capability shape (SG1, SG33-SG37; SGT17)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `movie_ui_lib.py`: job policy, argv, probe and progress (SG28-SG32; SGT18, SGT19)

This task implements, in `movie_ui_lib.py`:
- SG28: `job_vlm`'s forbidden tuple gains `"seed-edit"`.
- SG29: `seed_edit_argv(fields, ws_real, py=sys.executable)` directly below `character_argv`, the spec's code verbatim.
- SG30: `seed_edit_check(ws_real)` directly below `story_server_record`, with the helper `_probe_model(value)` above it (Plan ruling PR15: `reason` and `backend` must be present keys).
- SG31: `SEED_CAND_RE` directly after `STILL_NAME_RE`; `ProgressParser.__init__` gains `candidates` and `candidates_total`; `_line`'s `seed-edit` branch directly after the `last_line` update.
- SG32: `snapshot`'s `seed-edit` branch, directly before the generic branch.

Tests: SGT18 and SGT19, appended to `tests/test_movie_ui_seedgen.py`, with the helpers `OK_MODELS`, `stub_seed_edit(ws, models, exit=0, stderr="", sleep=0)` (Plan ruling PR16) and `clean_env(monkeypatch, tmp_path)`, which Task 5 reuses.

**Files:**
- Modify (at 2b19b59): `movie_ui_lib.py`: `job_vlm` `:434`, the end of `character_argv` `:1194-1196`, the end of `story_server_record` `:1633`, `STILL_NAME_RE` `:2154`, `ProgressParser.__init__` `:2193-2194`, `_line` `:2221-2223`, `snapshot` `:2274-2276`; `tests/test_movie_ui_seedgen.py` (append after SGT17).
- Read only: `movie_ui_lib.py`: `job_vlm` `:421-436`, `character_argv` `:1167-1196`, `run_light` `:1199-1226`, `tool_argv` `:1229-1231`, `last_line` `:1234-1237`, `LIGHT_TIMEOUT` `:957`, `ProgressParser` `:2182-2296`, `collapse` `:2157-2159`.

**Interfaces:**
- Consumes (existing): `run_light(argv, cwd, env=None, timeout=None) -> {"argv", "exit_code", "stdout", "stderr", "timed_out"}`, `tool_argv(ws_real, tool, *args)`, `last_line(text)`, `LIGHT_TIMEOUT` (read at call time), `_is_int`.
- Produces, in `movie_ui_lib`:
  - `job_vlm("seed-edit", ...) == "forbidden"`;
  - `seed_edit_argv(fields, ws_real, py=sys.executable) -> [str]` (fields: `run`, `source_file`, `prompt`, `model`, `strength`, `candidates`, `seed`);
  - `seed_edit_check(ws_real) -> (models, None)` or `(None, detail)`; `models` is `{"zimage": {"ok", "reason", "backend"}, "qwen": {...}}` with exactly those three keys per model;
  - `SEED_CAND_RE`; `ProgressParser.candidates` (`{"<i>": status}`) and `.candidates_total`; the `seed-edit` snapshot `{"kind", "elapsed_s", "last_line", "face_problem", "candidates": {"total", "done", "ok", "blocked", "failed", "current"}}`.
- Produces, in `tests/test_movie_ui_seedgen.py`: `OK_MODELS`, `stub_seed_edit`, `clean_env`.

- [ ] **Step 1: Write the failing tests.**

Edit `tests/test_movie_ui_seedgen.py`: replace this text, which occurs exactly once:

```python
    assert sorted(re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M)) == [
        "movie_ui_lib", "re", "secrets", "time"]
```

with:

```python
    assert sorted(re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M)) == [
        "movie_ui_lib", "re", "secrets", "time"]


# --- The probe stub and the environment (spec 9 rules) -----------------------------------------------

OK_MODELS = {"zimage": {"ok": True, "reason": None, "backend": "zimage"},
             "qwen": {"ok": True, "reason": None, "backend": "mflux-q4"}}


def stub_seed_edit(ws, models, exit=0, stderr="", sleep=0):
    """<ws>/bin/seed-edit as a stub: it sleeps `sleep` s, prints json.dumps(models) (models itself
    when it is a str) for --probe, writes stderr and exits with `exit`. Returns its path."""
    out = models if isinstance(models, str) else json.dumps(models)
    path = os.path.join(ws, "bin", "seed-edit")
    with open(path, "w", encoding="utf-8") as f:
        f.write("#!%s\nimport sys\nimport time\ntime.sleep(%r)\nif sys.argv[1:] == ['--probe']:\n"
                "    sys.stdout.write(%r + '\\n')\nsys.stderr.write(%r)\nsys.exit(%d)\n"
                % (sys.executable, sleep, out, stderr, exit))
    os.chmod(path, 0o755)
    return path


def clean_env(monkeypatch, tmp_path):
    """Spec 9: no HF_HUB_CACHE and no SEED_EDIT_* variable; HF_HOME and Z_IMAGE_HF_HOME under tmp_path."""
    for key in list(os.environ):
        if key.startswith("SEED_EDIT_"):
            monkeypatch.delenv(key)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", os.path.join(str(tmp_path), "hf"))
    monkeypatch.setenv("Z_IMAGE_HF_HOME", os.path.join(str(tmp_path), "zi"))


# --- SGT18 (SG28, SG29, SG31, SG32): job policy, argv and progress ------------------------------------

def test_sgt18_policy_argv_and_progress(monkeypatch, tmp_path):
    state = mt.set_home(monkeypatch, tmp_path)
    clean_env(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    assert lib.job_vlm("seed-edit", {}, ws, None) == "forbidden"
    run_dir = os.path.join(ws, "generated", "seeds", "runs", RUN)
    fields = {"ws": ws, "run": RUN, "source_file": "source.png", "prompt": "make it night", "model": "zimage",
              "strength": 0.3, "candidates": 3, "seed": 7, "source": {"kind": "upload", "upload_id": UP}}
    assert lib.seed_edit_argv(fields, ws) == [
        sys.executable, os.path.join(ws, "bin", "seed-edit"), "--source", os.path.join(run_dir, "source.png"),
        "--prompt", "make it night", "--model", "zimage", "--strength", "0.3", "--candidates", "3",
        "--seed", "7", "--run-dir", run_dir]
    qwen = dict(fields, model="qwen", strength=None, source_file="source.jpg")
    assert lib.seed_edit_argv(qwen, ws, py="/py") == [
        "/py", os.path.join(ws, "bin", "seed-edit"), "--source", os.path.join(run_dir, "source.jpg"),
        "--prompt", "make it night", "--model", "qwen", "--candidates", "3", "--seed", "7", "--run-dir", run_dir]
    job = {"id": "20261102-141500-a1b2", "workspace": ws, "story_id": None}
    parser = lib.ProgressParser("seed-edit", dict(fields, candidates=4))
    assert parser.snapshot(job, None, state) == {
        "kind": "seed-edit", "elapsed_s": None, "last_line": "", "face_problem": False,
        "candidates": {"total": 4, "done": 0, "ok": 0, "blocked": 0, "failed": 0, "current": 1}}
    lines = b"seed-edit: backend zimage (Z-Image img2img)\ncandidate 1/4 ok 1.0s\ncandidate 2/4 blocked 2.0s\n"
    parser.feed(lines)
    snap = parser.snapshot(job, None, state)
    assert snap["candidates"] == {"total": 4, "done": 2, "ok": 1, "blocked": 1, "failed": 0, "current": 3}
    assert snap["last_line"] == "candidate 2/4 blocked 2.0s"
    parser.feed(b"panel 3 ok: x\ncandidate 3/4 failed\ncandidate 4/4 failed\n")
    assert parser.snapshot(job, None, state)["candidates"] == {
        "total": 4, "done": 4, "ok": 1, "blocked": 1, "failed": 2, "current": None}
    assert parser.panels == {}
    bare = lib.ProgressParser("seed-edit", {"candidates": "4"})
    assert bare.snapshot(job, None, state)["candidates"] == {
        "total": None, "done": 0, "ok": 0, "blocked": 0, "failed": 0, "current": None}
    other = lib.ProgressParser("character-create", {"name": "kyra"})
    other.feed(lines)
    assert set(other.snapshot(job, None, state)) == {"kind", "elapsed_s", "last_line", "face_problem"}
    assert other.candidates == {}


# --- SGT19 (SG30): lib.seed_edit_check ---------------------------------------------------------------

def test_sgt19_seed_edit_check(monkeypatch, tmp_path):
    mt.set_home(monkeypatch, tmp_path)
    clean_env(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    stub_seed_edit(ws, OK_MODELS)
    assert lib.seed_edit_check(ws) == (OK_MODELS, None)
    extra = {"zimage": dict(OK_MODELS["zimage"], note=1), "qwen": OK_MODELS["qwen"], "other": 1}
    stub_seed_edit(ws, extra)
    assert lib.seed_edit_check(ws) == (OK_MODELS, None)
    stub_seed_edit(ws, OK_MODELS, exit=3, stderr="first\nnope\n")
    assert lib.seed_edit_check(ws) == (None, "bin/seed-edit --probe exited 3: nope")
    stub_seed_edit(ws, OK_MODELS, exit=3)
    assert lib.seed_edit_check(ws) == (None, "bin/seed-edit --probe exited 3: -")
    bad = [
        "not json",
        json.dumps({"zimage": dict(OK_MODELS["zimage"], ok="yes"), "qwen": OK_MODELS["qwen"]}),
        json.dumps({"zimage": OK_MODELS["zimage"]}),
        json.dumps([OK_MODELS]),
        json.dumps({"zimage": {"ok": True, "backend": "zimage"}, "qwen": OK_MODELS["qwen"]}),
        json.dumps({"zimage": dict(OK_MODELS["zimage"], reason=5), "qwen": OK_MODELS["qwen"]}),
        json.dumps({"zimage": OK_MODELS["zimage"], "qwen": dict(OK_MODELS["qwen"], backend=["x"])}),
    ]
    for printed in bad:
        stub_seed_edit(ws, printed)
        assert lib.seed_edit_check(ws) == (None, "bin/seed-edit --probe printed unparsable output"), printed
    monkeypatch.setattr(lib, "LIGHT_TIMEOUT", 1)
    stub_seed_edit(ws, OK_MODELS, sleep=2)
    assert lib.seed_edit_check(ws) == (None, "bin/seed-edit --probe timed out after 1 s")
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedgen.py 2>&1 | tail -1
```

Expected: `2 failed, 37 passed` (SGT18: `assert 'any' == 'forbidden'`; SGT19: `AttributeError: module 'movie_ui_lib' has no attribute 'seed_edit_check'`).

- [ ] **Step 3: Implement.**

**3.1.** The job policy (SG28). Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    if kind in ("smoke", "character-train", "action-train", "location-train"):
```

with:

```python
    if kind in ("smoke", "character-train", "action-train", "location-train", "seed-edit"):
```

**3.2.** The argv (SG29). Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    if fields.get("force"):
        argv.append("--force")
    return argv + ["--no-review"]
```

with:

```python
    if fields.get("force"):
        argv.append("--force")
    return argv + ["--no-review"]


def seed_edit_argv(fields, ws_real, py=sys.executable):
    """The bin/seed-edit argv of a seed-edit job (seed generator spec SG29)."""
    run_dir = os.path.join(ws_real, "generated", "seeds", "runs", fields["run"])
    argv = [py, os.path.join(ws_real, "bin", "seed-edit"),
            "--source", os.path.join(run_dir, fields["source_file"]),
            "--prompt", fields["prompt"], "--model", fields["model"]]
    if fields["model"] == "zimage":
        argv += ["--strength", repr(float(fields["strength"]))]
    return argv + ["--candidates", str(fields["candidates"]), "--seed", str(fields["seed"]),
                   "--run-dir", run_dir]
```

**3.3.** The probe (SG30). Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    return _from_pair("V2", "story server", _story_server_pair(kind, value))
```

with:

```python
    return _from_pair("V2", "story server", _story_server_pair(kind, value))


def _probe_model(value):
    """One model entry of bin/seed-edit --probe's output with exactly its three keys, or None."""
    if not (isinstance(value, dict) and isinstance(value.get("ok"), bool) and "reason" in value
            and "backend" in value):
        return None
    if not all(value[k] is None or isinstance(value[k], str) for k in ("reason", "backend")):
        return None
    return {"ok": value["ok"], "reason": value["reason"], "backend": value["backend"]}


def seed_edit_check(ws_real):
    """(models, None) from <ws>/bin/seed-edit --probe, or (None, detail) (seed generator SG30)."""
    run = run_light(tool_argv(ws_real, "seed-edit", "--probe"), ws_real)
    if run["timed_out"]:
        return None, "bin/seed-edit --probe timed out after %d s" % LIGHT_TIMEOUT
    code = run["exit_code"]
    if code != 0:
        return None, "bin/seed-edit --probe exited %s: %s" % (code or "none", last_line(run["stderr"]) or "-")
    try:
        data = json.loads(last_line(run["stdout"]))
    except (ValueError, RecursionError):
        data = None
    models = None
    if isinstance(data, dict):
        models = dict((key, _probe_model(data.get(key))) for key in ("zimage", "qwen"))
        if None in models.values():
            models = None
    if models is None:
        return None, "bin/seed-edit --probe printed unparsable output"
    return models, None
```

**3.4.** The candidate pattern (SG31). Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
STILL_NAME_RE = re.compile(r"^panel_\d{2}\.png$")
```

with:

```python
STILL_NAME_RE = re.compile(r"^panel_\d{2}\.png$")
SEED_CAND_RE = re.compile(r"^candidate (\d+)/(\d+) (ok|blocked|failed)(?: [0-9]+\.[0-9]s)?$")   # seed generator SG31
```

**3.5.** The parser's state (SG31). Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
        self.face_problem = False
        self.last_line = ""
```

with:

```python
        self.face_problem = False
        self.last_line = ""
        self.candidates = {}            # seed generator SG31: {"<i>": "ok" | "blocked" | "failed"}
        self.candidates_total = None
```

**3.6.** The parser's line rule (SG31). Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    def _line(self, line):
        if line.strip():
            self.last_line = line[:LINE_CLIP]
```

with:

```python
    def _line(self, line):
        if line.strip():
            self.last_line = line[:LINE_CLIP]
        if self.kind == "seed-edit":
            match = SEED_CAND_RE.match(line)
            if match:
                self.candidates_total = int(match.group(2))
                self.candidates[match.group(1)] = match.group(3)
            return
```

**3.7.** The snapshot (SG32). Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
        if self.kind not in ("story", "movie"):
            return {"kind": self.kind, "elapsed_s": elapsed, "last_line": self.current_last_line(),
                    "face_problem": self.face_problem}
```

with:

```python
        if self.kind == "seed-edit":
            total = self.candidates_total
            if total is None:
                total = self.fields.get("candidates") if _is_int(self.fields.get("candidates")) else None
            done = len(self.candidates)
            states = list(self.candidates.values())
            return {"kind": "seed-edit", "elapsed_s": elapsed, "last_line": self.current_last_line(),
                    "face_problem": False,
                    "candidates": {"total": total, "done": done, "ok": states.count("ok"),
                                   "blocked": states.count("blocked"), "failed": states.count("failed"),
                                   "current": done + 1 if total is not None and done < total else None}}
        if self.kind not in ("story", "movie"):
            return {"kind": self.kind, "elapsed_s": elapsed, "last_line": self.current_last_line(),
                    "face_problem": self.face_problem}
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedgen.py 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_progress.py tests/test_vlm_lifecycle.py tests/test_location_ui.py::test_lu9_job_vlm_policy 2>&1 | tail -1
```

Expected: `39 passed`, then `52 passed` (the existing progress and policy tests are unchanged). Run the compile check with `FILES` = `movie_ui_lib.py tests/test_movie_ui_seedgen.py`; expected: `compiled 2` twice. Then run the gate block with `N=2`. Expected: `GATE PASS`, `lost 0`, `new tests 39, not passing 0`, `baseline failures still failing 2 of 2`, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
git add movie_ui_lib.py tests/test_movie_ui_seedgen.py
git diff --cached --name-only    # expected: those 2 paths
git commit -m "feat(movie-ui): the seed-edit job kind in movie_ui_lib: VLM-forbidden policy, seed_edit_argv, seed_edit_check (bin/seed-edit --probe) and the candidates progress (SG28-SG32; SGT18, SGT19)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `bin/seed-edit`, the tool (SG2, SG4-SG23; SGT1-SGT14, Review Focus 3 and 4)

This task implements `bin/seed-edit` whole (spec Section 2):
- SG4 `parse` and `check_args` (the table's order; `Refusal` carries the text); SG5 exit codes; SG6 `main(argv=None)` and the `__main__` signal handlers; SG7 `say` and `error`.
- SG8 `canvas`; SG9 `read_source`; SG10 `prepare_source` (byte copy unless `samefile`, `work/source.png`). Plan ruling PR9 fixes when `source`, `size` and `source_size` are set; PR10 makes `--run-dir` absolute.
- SG11/SG12 `new_record`, `write_run`, `finish`, `fail_rest`, `refuse`, `cleanup`, `run` and `main`'s interrupt path.
- SG13 `preflight`, `wait_for_memory`, `disk_free_gib`, `avail_gib`, `total_gib`; SG14 `missing_modules`, `modules_problem`, `default_hub`, `zimage_problem`, `find_lightning`, `bf16_problem`, `mflux_version`, `mflux_problem`, `choose_qwen(paths=None)` (Plan rulings PR7, PR8, PR14); SG15 `probe`.
- SG16/SG17 the candidate lines and failure texts (Plan ruling PR12); SG18 `run_zimage`, `cpu_generator`; SG19 `run_bf16`; SG20 `run_mflux`; SG21 `run_child` and `CHILD` (Plan rulings PR11, PR13); `run_qwen_child`; SG22 one load per job; SG23 the docstring.

Tests: SGT1-SGT14 and Review Focus 3 and 4 in the new `tests/test_seed_edit_tool.py` (33 test cases). The child processes are stubs; `seed_edit_mflux_child.py` itself is Task 4's.

**Files:**
- Create: `bin/seed-edit` (then `chmod 755`), `tests/test_seed_edit_tool.py`.
- Read only (at 2b19b59): `movie_ui_lib.py`: `utc_now` `:49-51`, `write_json_atomic` `:102-104`, `read_json` `:107-113`, `STILLS_BASE_MODEL`/`ZIMAGE_TEXT_ENCODER` `:935-936`, `zimage_hub` `:1689-1691`, `repo_dir_name` `:1699-1700`, `zimage_hub_for` `:1703-1706`, `choose_snapshot` `:1709-1724`, `model_check` `:1798-1812`; `character_dataset.py`: the constants `:164-199`, `busy_process` `:535-556`, `child_qwenedit` `:1839-1883`; `z_image_skill.py`: `generate_variation` `:251-272`; `content_safety.py`: `ContentSafetyError` `:25-26`, `assert_image_safe` `:84-100`; `bin/character` `:135-152` (the signal pattern).

**Interfaces:**
- Consumes: Task 2's `lib.seed_edit_argv` (Review Focus 3) and Task 1's `seedgen.validate_run_request` (Review Focus 3); `lib.utc_now`, `lib.write_json_atomic`, `lib.read_json`, `lib.model_check(model_id, hub) -> (ok, detail)`, `lib.choose_snapshot(repo_dir) -> (path, reason)`, `lib.repo_dir_name`, `lib.zimage_hub()`, `lib.zimage_hub_for(repo)`, `lib.STILLS_BASE_MODEL`, `lib.ZIMAGE_TEXT_ENCODER`; at run time only: `character_dataset.busy_process()`, `z_image_skill.generate_variation(...)`, `content_safety.assert_image_safe(image, *, skill, prompt)`, `content_safety.ContentSafetyError`, `psutil`, `PIL`, `torch`.
- Produces, in `bin/seed-edit` (loaded by tests as module `seed_edit_tool`):
  - the constants of spec 1.1, `EXTS`, `BF16_LINE_RE`, `MFLUX_LINE_RE`, `CHILD`, `Refusal`;
  - `main(argv=None) -> int`; `probe() -> dict`; `canvas(w0, h0) -> (W, H)` or `Refusal`;
  - `choose_qwen(paths=None) -> (backend, why)` or `Refusal`; `mflux_problem() -> (problem, q4_dir, lora_file)`; `mflux_version(venv) -> (count, (parsed, text) or None)`; `find_lightning(hubs) -> path or None`; `zimage_problem()`, `bf16_problem()` (None or text);
  - the replaceable module functions `say`, `avail_gib`, `total_gib`, `missing_modules`, `cpu_generator`, `disk_free_gib`, and the module constants `AVAIL_WAIT_S`, `CHILD_TIMEOUT_S` (read at call time).
- The candidate lines the movie-ui parses (Task 2's `SEED_CAND_RE`): `candidate <i>/<N> ok <s.s>s`, `candidate <i>/<N> blocked <s.s>s`, `candidate <i>/<N> failed`.

- [ ] **Step 1: Write the failing tests.**

Create `tests/test_seed_edit_tool.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""Tests for bin/seed-edit, seed_edit_mflux_child.py and bin/seed-edit-setup (docs/superpowers/specs/
2026-11-02-seed-generator-design.md, Section 9: SGT1-SGT16, with the plan's Review Focus pins 3
and 4).

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py

Rules (spec Section 9):
- bin/seed-edit is loaded with importlib.machinery.SourceFileLoader("seed_edit_tool", path),
  importlib.util.spec_from_loader, importlib.util.module_from_spec and loader.exec_module (never
  the deprecated loader shortcut); seed_edit_mflux_child.py is a plain import.
- Every test sets HOME to tmp_path/home, removes HF_HUB_CACHE and every SEED_EDIT_* variable, and
  sets HF_HOME and Z_IMAGE_HF_HOME under tmp_path (the env fixture). HF caches are built with
  mt.make_hf_cache: one non-empty .safetensors file per repo, plus the Lightning file where needed.
- Process boundaries are stubbed, never crossed for real: the bf16 child through
  SEED_EDIT_QWENEDIT_SCRIPT (a Python stub run by sys.executable), the mflux child through
  SEED_EDIT_MFLUX_PYTHON (an executable stub whose shebang is sys.executable, beside a fake
  lib/python3.13/site-packages/mflux-<v>.dist-info/METADATA), and z_image_skill, content_safety
  and character_dataset through sys.modules fakes. Each stub records its argv, an env subset and
  its spec, and behaves per a config file its test writes. The fake assert_image_safe raises
  ContentSafetyError when the image's top-left pixel is pure red.
- tool.avail_gib, tool.total_gib, tool.missing_modules, tool.cpu_generator and tool.disk_free_gib
  are monkeypatched (cpu_generator returns the seed itself). Sources are real PNG, JPEG and GIF
  files drawn with PIL under tmp_path.
- No test uses the real HOME, loads a real model, runs bin/seed-edit-setup, or contacts a server.
  None touches port 8177 or 8178.
Stdlib, PIL and pytest.
"""

import glob
import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import types

import pytest
from PIL import Image

import movie_ui_testutil as mt
import movie_ui_lib as lib
import movie_ui_seedgen as seedgen

WS = mt.WS
TOOL_PATH = os.path.join(WS, "bin", "seed-edit")
PROMPT = "make it night"
RED = (255, 0, 0)
UP = "a" * 64 + ".png"
REV = "0123456789abcdef0123456789abcdef01234567"
R1, R2, R3, R4, R5 = ("se-20261102-141500-000%d" % i for i in range(1, 6))
RUN = "se-20261102-141500-a1b2"


def load_tool():
    loader = importlib.machinery.SourceFileLoader("seed_edit_tool", TOOL_PATH)
    spec = importlib.util.spec_from_loader("seed_edit_tool", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def png(path, size, color=(0, 128, 0)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def make_fakes(monkeypatch):
    """sys.modules fakes of content_safety, z_image_skill and character_dataset. calls["plan"] maps a
    seed (the fake generator) to "red" (blocked) or an exception the fake raises."""
    calls = {"safety": [], "zimage": [], "busy": None, "plan": {}}
    safety = types.ModuleType("content_safety")

    class ContentSafetyError(RuntimeError):
        pass

    def assert_image_safe(image, *, skill, prompt):
        calls["safety"].append({"skill": skill, "prompt": prompt, "size": image.size})
        if image.convert("RGB").getpixel((0, 0)) == RED:
            raise ContentSafetyError("CONTENT SAFETY BLOCK (fake)")

    safety.ContentSafetyError = ContentSafetyError
    safety.assert_image_safe = assert_image_safe
    zimage = types.ModuleType("z_image_skill")

    def generate_variation(seed_image, prompt, output_path=None, strength=0.45, generator=None, **kwargs):
        calls["zimage"].append({"size": seed_image.size, "mode": seed_image.mode, "prompt": prompt,
                                "strength": strength, "generator": generator, "output_path": output_path})
        action = calls["plan"].get(generator)
        if isinstance(action, BaseException):
            raise action
        image = Image.new("RGB", seed_image.size, RED if action == "red" else (0, 0, 200))
        assert_image_safe(image, skill="z_image_skill", prompt=prompt)
        return image

    zimage.generate_variation = generate_variation
    dataset = types.ModuleType("character_dataset")
    dataset.busy_process = lambda: calls["busy"]
    for name, module in (("content_safety", safety), ("z_image_skill", zimage), ("character_dataset", dataset)):
        monkeypatch.setitem(sys.modules, name, module)
    return calls


@pytest.fixture
def env(monkeypatch, tmp_path):
    tmp = str(tmp_path)
    home = os.path.join(tmp, "home")
    os.makedirs(home)
    monkeypatch.setenv("HOME", home)
    for key in list(os.environ):
        if key.startswith("SEED_EDIT_"):
            monkeypatch.delenv(key)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", os.path.join(tmp, "hf"))
    monkeypatch.setenv("Z_IMAGE_HF_HOME", os.path.join(tmp, "zi"))
    tool = load_tool()
    gens = []
    monkeypatch.setattr(tool, "avail_gib", lambda: 40.0)
    monkeypatch.setattr(tool, "total_gib", lambda: 48.0)
    monkeypatch.setattr(tool, "missing_modules", lambda names: [])
    monkeypatch.setattr(tool, "disk_free_gib", lambda path: 100.0)
    monkeypatch.setattr(tool, "cpu_generator", lambda seed: gens.append(seed) or seed)
    return {"tmp": tmp, "tool": tool, "gens": gens, "calls": make_fakes(monkeypatch), "mp": monkeypatch,
            "zhub": os.path.join(tmp, "zi", "hub"), "hfhub": os.path.join(tmp, "hf", "hub")}


def zimage_cache(env):
    for repo in (lib.STILLS_BASE_MODEL, lib.ZIMAGE_TEXT_ENCODER):
        mt.make_hf_cache(os.path.join(env["tmp"], "zi"), repo, {"x.safetensors": b"\x01" * 8})


def bf16_cache(env):
    root, tool = os.path.join(env["tmp"], "hf"), env["tool"]
    mt.make_hf_cache(root, tool.EDIT_MODEL, {"transformer/x.safetensors": b"\x01" * 8})
    mt.make_hf_cache(root, tool.EDIT_LORA_REPO, {tool.EDIT_LORA_FILE: b"\x01" * 8})


def mflux_weights(env, lora=True):
    """The q4 repo (and the Lightning repo) in the Z-Image hub; returns (q4 snapshot, Lightning path)."""
    root, tool = os.path.join(env["tmp"], "zi"), env["tool"]
    q4 = mt.make_hf_cache(root, tool.Q4_REPO, {"transformer/0.safetensors": b"\x01" * 8})
    path = None
    if lora:
        repo = mt.make_hf_cache(root, tool.EDIT_LORA_REPO, {tool.EDIT_LORA_FILE: b"\x01" * 8})
        path = os.path.join(repo, "snapshots", REV, tool.EDIT_LORA_FILE)
    return os.path.join(q4, "snapshots", REV), path


MFLUX_STUB = r'''#!__PYTHON__
"""Stub of the mflux child (tests only): records argv, env and spec, then obeys config.json."""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
with open(args[args.index("--spec") + 1], encoding="utf-8") as f:
    spec = json.load(f)
try:
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        config = json.load(f)
except OSError:
    config = {}
with open(os.path.join(HERE, "calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": sys.argv, "spec": spec,
                        "env": {k: os.environ.get(k) for k in ("HF_HUB_OFFLINE", "PYTHONUNBUFFERED")}}) + "\n")
time.sleep(config.get("sleep", 0))
from PIL import Image
for i, job in enumerate(spec["jobs"]):
    if config.get("fail_after") == i:
        print("boom", flush=True)
        sys.exit(1)
    color = (255, 0, 0) if job["n"] in config.get("red", []) else (0, 0, 200)
    Image.new("RGB", (spec["width"], spec["height"]), color).save(job["output_path"])
    print(config.get("prefix", "") + "seed-edit-child done %d 1.0" % job["n"], flush=True)
'''

QWENEDIT_STUB = r'''"""Stub of character_dataset.py qwenedit (tests only): records argv, env and spec, then obeys
config.json."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
with open(args[args.index("--spec") + 1], encoding="utf-8") as f:
    spec = json.load(f)
try:
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        config = json.load(f)
except OSError:
    config = {}
with open(os.path.join(HERE, "calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": [sys.executable] + sys.argv, "spec": spec,
                        "env": {k: os.environ.get(k) for k in ("PYTHONUNBUFFERED",)}}) + "\n")
from PIL import Image
for job in spec["jobs"]:
    name = os.path.basename(job["output_path"])
    status = "blocked" if int(name[5:7]) in config.get("blocked", []) else "ok"
    if status == "ok":
        Image.new("RGB", (job["width"], job["height"]), (0, 0, 200)).save(job["output_path"])
    print(config.get("prefix", "") + "%s %s 1.0s" % (name, status), flush=True)
sys.exit(config.get("exit", 0))
'''


def set_mflux_version(venv, text):
    """Replace the venv's mflux dist-info with one whose METADATA says Version: text (None: none)."""
    site = os.path.join(venv, "lib", "python3.13", "site-packages")
    for old in glob.glob(os.path.join(site, "mflux-*.dist-info")):
        os.remove(os.path.join(old, "METADATA"))
        os.rmdir(old)
    if text is not None:
        info = os.path.join(site, "mflux-%s.dist-info" % text)
        os.makedirs(info)
        with open(os.path.join(info, "METADATA"), "w", encoding="utf-8") as f:
            f.write("Metadata-Version: 2.1\nName: mflux\nVersion: %s\n" % text)


def mflux_venv(env, version="0.24.0"):
    """The stub venv python (SEED_EDIT_MFLUX_PYTHON) and its dist-info; returns (python, venv)."""
    venv = os.path.join(env["tmp"], "mflux-edit", ".venv")
    py = os.path.join(venv, "bin", "python")
    os.makedirs(os.path.dirname(py), exist_ok=True)
    with open(py, "w", encoding="utf-8") as f:
        f.write(MFLUX_STUB.replace("__PYTHON__", sys.executable))
    os.chmod(py, 0o755)
    set_mflux_version(venv, version)
    env["mp"].setenv("SEED_EDIT_MFLUX_PYTHON", py)
    return py, venv


def qwenedit_stub(env, config):
    path = os.path.join(env["tmp"], "qwenedit", "stub.py")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(QWENEDIT_STUB)
    stub_config(path, config)
    env["mp"].setenv("SEED_EDIT_QWENEDIT_SCRIPT", path)
    return path


def stub_config(stub, config):
    with open(os.path.join(os.path.dirname(stub), "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)


def stub_calls(stub):
    try:
        with open(os.path.join(os.path.dirname(stub), "calls.jsonl"), encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except OSError:
        return []


def run_tool(env, *extra, source=None, run=RUN, prompt=PROMPT, model="zimage"):
    """tool.main for one run directory <tmp>/runs/<run> (source: a 1536x1024 PNG by default);
    returns (exit code, run directory)."""
    if source is None:
        source = os.path.join(env["tmp"], "src.png")
        if not os.path.isfile(source):
            png(source, (1536, 1024))
    run_dir = os.path.join(env["tmp"], "runs", run)
    argv = ["--source", source, "--prompt", prompt, "--model", model, "--run-dir", run_dir] + list(extra)
    return env["tool"].main(argv), run_dir


def record_of(run_dir):
    return read_json(os.path.join(run_dir, "run.json"))


def statuses(run_dir):
    return [c["status"] for c in record_of(run_dir)["candidates"]]


def cand(run_dir, n):
    return os.path.join(run_dir, "cand_%02d.png" % n)


def plain(lines):
    """Candidate lines with the seconds replaced by S."""
    return [re.sub(r" [0-9]+\.[0-9]s$", " Ss", line) for line in lines]


# --- SGT1 (SG8): the canvas ----------------------------------------------------------------------------

CANVAS = [((1536, 1024), (1024, 672)), ((1024, 1024), (1024, 1024)), ((800, 600), (800, 592)),
          ((4000, 3000), (1024, 768)), ((3000, 4000), (768, 1024)), ((720, 1280), (576, 1024)),
          ((1023, 1023), (1008, 1008)), ((100, 70), (96, 64))]


def test_sgt1_the_canvas(env):
    tool = env["tool"]
    for (w0, h0), want in CANVAS:
        assert tool.canvas(w0, h0) == want, (w0, h0)
    with pytest.raises(tool.Refusal) as info:
        tool.canvas(100, 60)
    assert str(info.value) == "--source is too small: 100x60 gives a 96x48 canvas; each side must be at least 64 px"


# --- SGT2 (SG11, SG12, SG16, SG18): a Z-Image run ------------------------------------------------------

def test_sgt2_a_zimage_run(env, capsys):
    tool = env["tool"]
    zimage_cache(env)
    run_dir = os.path.join(env["tmp"], "runs", RUN)
    seen = []
    real_say = tool.say

    def spy(text):
        found = re.match(r"^candidate (\d+)/3 ", text)
        if found:
            n = int(found.group(1))
            seen.append((n, record_of(run_dir)["candidates"][n - 1]["status"], os.path.isfile(cand(run_dir, n))))
        real_say(text)

    env["mp"].setattr(tool, "say", spy)
    code, _run = run_tool(env, "--strength", "0.3", "--candidates", "3", "--seed", "100")
    assert code == 0
    assert env["gens"] == [101, 102, 103]
    assert [(c["size"], c["mode"], c["prompt"], c["strength"], c["output_path"]) for c in env["calls"]["zimage"]] == [
        ((1024, 672), "RGB", PROMPT, 0.3, None)] * 3
    assert env["calls"]["safety"] == [{"skill": "z_image_skill", "prompt": PROMPT, "size": (1024, 672)}] * 3
    for n in (1, 2, 3):
        with Image.open(cand(run_dir, n)) as img:
            assert img.size == (1024, 672)
    with open(os.path.join(env["tmp"], "src.png"), "rb") as f, open(os.path.join(run_dir, "source.png"), "rb") as g:
        assert f.read() == g.read()
    with Image.open(os.path.join(run_dir, "work", "source.png")) as img:
        assert img.size == (1536, 1024)
    record = record_of(run_dir)
    assert re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", record["created"])
    assert all(isinstance(c["seconds"], float) for c in record["candidates"])
    assert dict(record, created=None, candidates=[dict(c, seconds=None) for c in record["candidates"]]) == {
        "schema": "seed-edit.run.v1", "run": RUN, "created": None, "state": "done", "prompt": PROMPT,
        "model": "zimage", "backend": "zimage", "strength": 0.3, "seed": 100,
        "size": {"width": 1024, "height": 672}, "source_size": {"width": 1536, "height": 1024},
        "source": "source.png", "source_origin": None, "job": None, "error": None,
        "candidates": [{"n": n, "seed": 100 + n, "status": "ok", "seconds": None} for n in (1, 2, 3)]}
    out = capsys.readouterr().out.splitlines()
    assert out[:3] == ["seed-edit: run %s" % run_dir, "seed-edit: source 1536x1024 -> 1024x672",
                       "seed-edit: backend zimage (Z-Image img2img)"]
    assert plain(out[3:]) == ["candidate 1/3 ok Ss", "candidate 2/3 ok Ss", "candidate 3/3 ok Ss",
                              "seed-edit: done: 3 ok, 0 blocked, 0 failed"]
    assert seen == [(1, "ok", True), (2, "ok", True), (3, "ok", True)]


def test_sgt2_a_queued_record_keeps_created_origin_and_job(env):
    zimage_cache(env)
    run_dir = os.path.join(env["tmp"], "runs", RUN)
    os.makedirs(run_dir)
    origin = {"kind": "upload", "upload_id": UP}
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as f:
        json.dump({"created": "2026-11-02T14:15:00Z", "source_origin": origin, "job": "20261102-141500-a1b2",
                   "state": "queued", "prompt": "old"}, f)
    assert run_tool(env, "--candidates", "1", "--seed", "1")[0] == 0
    record = record_of(run_dir)
    assert (record["created"], record["source_origin"], record["job"]) == (
        "2026-11-02T14:15:00Z", origin, "20261102-141500-a1b2")
    assert (record["prompt"], record["state"]) == (PROMPT, "done")


# --- SGT3 (SG18): a blocked candidate ------------------------------------------------------------------

def test_sgt3_a_blocked_candidate(env, capsys):
    zimage_cache(env)
    env["calls"]["plan"][102] = "red"
    code, run_dir = run_tool(env, "--candidates", "3", "--seed", "100")
    assert code == 0
    assert [os.path.isfile(cand(run_dir, n)) for n in (1, 2, 3)] == [True, False, True]
    record = record_of(run_dir)
    assert statuses(run_dir) == ["ok", "blocked", "ok"]
    assert (record["state"], record["error"]) == ("done", None)
    assert isinstance(record["candidates"][1]["seconds"], float)
    out = capsys.readouterr().out.splitlines()
    assert plain(out[3:]) == ["candidate 1/3 ok Ss", "candidate 2/3 blocked Ss", "candidate 3/3 ok Ss",
                              "seed-edit: done: 2 ok, 1 blocked, 0 failed"]


# --- SGT4 (SG17, SG18): a Z-Image crash ----------------------------------------------------------------

def test_sgt4_a_zimage_crash(env, capsys):
    zimage_cache(env)
    env["calls"]["plan"][102] = RuntimeError("boom")
    run_dir = os.path.join(env["tmp"], "runs", RUN)
    for name in ("cand_09.part.png", "cand_09.pending.png"):
        png(os.path.join(run_dir, "work", name), (8, 8))
    code, _run = run_tool(env, "--candidates", "3", "--seed", "100")
    assert code == 1
    assert [os.path.isfile(cand(run_dir, n)) for n in (1, 2, 3)] == [True, False, False]
    record = record_of(run_dir)
    assert statuses(run_dir) == ["ok", "failed", "failed"]
    assert [c["seconds"] for c in record["candidates"][1:]] == [None, None]
    assert (record["state"], record["error"]) == ("failed", "Z-Image failed on candidate 2: RuntimeError: boom")
    out = capsys.readouterr().out.splitlines()
    assert plain(out[3:]) == ["candidate 1/3 ok Ss", "candidate 2/3 failed", "candidate 3/3 failed",
                              "seed-edit: done: 1 ok, 0 blocked, 2 failed"]
    assert glob.glob(os.path.join(run_dir, "work", "*.part.png")) == []
    assert glob.glob(os.path.join(run_dir, "work", "*.pending.png")) == []


# --- SGT5 (SG4): bad arguments -------------------------------------------------------------------------

BASE = ["--source", "SRC", "--prompt", PROMPT, "--model", "zimage", "--run-dir", "RUNDIR"]
ARG_CASES = [
    (["--probe", "--model", "qwen"], "--probe takes no other options"),
    (["--source", "SRC", "--prompt", PROMPT, "--model", "zimage"], "--source, --prompt, --model and --run-dir are required"),
    (BASE + ["--model", "flux"], "--model must be zimage or qwen"),
    (BASE + ["--prompt", "  "], "--prompt must not be empty"),
    (BASE + ["--prompt", "x" * 2001], "--prompt is longer than 2000 characters"),
    (BASE + ["--candidates", "0"], "--candidates must be an integer from 1 to 4"),
    (BASE + ["--candidates", "5"], "--candidates must be an integer from 1 to 4"),
    (BASE + ["--candidates", "x"], "--candidates must be an integer from 1 to 4"),
    (BASE + ["--candidates", "0", "--strength", "0.05"], "--candidates must be an integer from 1 to 4"),
    (BASE + ["--model", "qwen", "--strength", "0.3"], "--strength is only for --model zimage"),
    (BASE + ["--strength", "0.05"], "--strength must be a number from 0.10 to 0.90"),
    (BASE + ["--strength", "0.95"], "--strength must be a number from 0.10 to 0.90"),
    (BASE + ["--strength", "x"], "--strength must be a number from 0.10 to 0.90"),
    (BASE + ["--strength", "nan"], "--strength must be a number from 0.10 to 0.90"),
    (BASE + ["--seed", "-1"], "--seed must be an integer from 0 to 2147483647"),
    (BASE + ["--seed", "2147483648"], "--seed must be an integer from 0 to 2147483647"),
    (BASE + ["--seed", "1.5"], "--seed must be an integer from 0 to 2147483647"),
]


@pytest.mark.parametrize("argv,message", ARG_CASES, ids=["case%d" % (i + 1) for i in range(len(ARG_CASES))])
def test_sgt5_bad_arguments(env, capsys, argv, message):
    source = png(os.path.join(env["tmp"], "src.png"), (128, 128))
    run_dir = os.path.join(env["tmp"], "runs", RUN)
    argv = [source if a == "SRC" else run_dir if a == "RUNDIR" else a for a in argv]
    assert env["tool"].main(argv) == 2
    assert capsys.readouterr() == ("", "Error: %s\n" % message)
    assert not os.path.exists(run_dir)
    assert env["calls"]["zimage"] == []


# --- SGT6 (SG9, SG10, SG12): bad and odd sources -------------------------------------------------------

def test_sgt6_bad_and_odd_sources(env, capsys):
    zimage_cache(env)
    tmp = env["tmp"]
    gif = os.path.join(tmp, "anim.gif")
    Image.new("RGB", (200, 200)).save(gif)
    code, run_dir = run_tool(env, source=gif, run=R1)
    text = "--source must be a PNG, JPEG or WebP image (got GIF): %s" % gif
    assert code == 2 and capsys.readouterr().err == "Error: %s\n" % text
    record = record_of(run_dir)
    assert (record["state"], record["error"], record["backend"]) == ("failed", text, None)
    assert (record["size"], record["source_size"], record["source"]) == (None, None, None)
    assert statuses(run_dir) == ["failed"] * 4
    small = png(os.path.join(tmp, "small.png"), (100, 60))
    code, run_dir = run_tool(env, source=small, run=R2)
    text = "--source is too small: 100x60 gives a 96x48 canvas; each side must be at least 64 px"
    assert code == 2 and capsys.readouterr().err == "Error: %s\n" % text
    assert (record_of(run_dir)["error"], record_of(run_dir)["size"]) == (text, None)
    junk = os.path.join(tmp, "junk.png")
    with open(junk, "wb") as f:
        f.write(b"not an image")
    code, run_dir = run_tool(env, source=junk, run=R3)
    assert code == 2
    assert record_of(run_dir)["error"].startswith("cannot read --source %s: UnidentifiedImageError: " % junk)
    capsys.readouterr()
    outside = png(os.path.join(tmp, "elsewhere", "pic.png"), (300, 200), (10, 20, 30))
    code, run_dir = run_tool(env, "--candidates", "1", source=outside, run=R4)
    assert code == 0
    with open(outside, "rb") as f, open(os.path.join(run_dir, "source.png"), "rb") as g:
        assert f.read() == g.read()
    exif = Image.Exif()
    exif[0x0112] = 6
    jpeg = os.path.join(tmp, "phone.jpg")
    Image.new("RGB", (200, 100), (0, 200, 0)).save(jpeg, "JPEG", exif=exif.tobytes())
    code, run_dir = run_tool(env, "--candidates", "1", source=jpeg, run=R5)
    assert code == 0
    record = record_of(run_dir)
    assert (record["source"], record["source_size"], record["size"]) == (
        "source.jpg", {"width": 100, "height": 200}, {"width": 96, "height": 192})
    with Image.open(os.path.join(run_dir, "work", "source.png")) as img:
        assert img.size == (100, 200)
    with open(jpeg, "rb") as f, open(os.path.join(run_dir, "source.jpg"), "rb") as g:
        assert f.read() == g.read()
    assert env["calls"]["zimage"][-1]["size"] == (96, 192)


# --- SGT7 (SG13): preflight refusals -------------------------------------------------------------------

def _refused(run_dir, text, captured):
    record = record_of(run_dir)
    assert (record["state"], record["error"], record["backend"]) == ("failed", text, None)
    assert set(statuses(run_dir)) == {"failed"}
    assert captured.err.endswith("Error: %s\n" % text)


def test_sgt7_preflight_refusals(env, capsys):
    tool, mp, calls = env["tool"], env["mp"], env["calls"]
    zimage_cache(env)
    mp.setattr(tool, "disk_free_gib", lambda path: 1.5)
    code, run_dir = run_tool(env, run=R1)
    assert code == 2
    _refused(run_dir, "less than 2 GiB free on the disk holding %s (1.5 GiB free)" % run_dir, capsys.readouterr())
    mp.setattr(tool, "disk_free_gib", lambda path: 100.0)
    calls["busy"] = (4242, "bin/ltx-movie --story-id x")
    code, run_dir = run_tool(env, run=R2)
    assert code == 2
    _refused(run_dir, "another GPU process is running (pid 4242: bin/ltx-movie --story-id x); try again when "
                      "it ends", capsys.readouterr())
    calls["busy"] = None
    mp.setattr(tool, "missing_modules", lambda names: ["torch"])
    code, run_dir = run_tool(env, run=R3)
    assert code == 2
    _refused(run_dir, "Z-Image is unavailable: torch not importable by %s" % sys.executable, capsys.readouterr())
    mp.setattr(tool, "missing_modules", lambda names: [])
    mp.setattr(tool, "avail_gib", lambda: 10.0)
    mp.setattr(tool, "AVAIL_WAIT_S", 0)
    code, run_dir = run_tool(env, run=R4)
    assert code == 2
    captured = capsys.readouterr()
    assert "seed-edit: waiting up to 0 s for 20 GiB available (now 10.0 GiB)\n" in captured.out
    _refused(run_dir, "only 10.0 GiB available after waiting 0 s; Z-Image needs 20 GiB; free memory and retry",
             captured)
    py, _venv = mflux_venv(env)
    mflux_weights(env)
    code, run_dir = run_tool(env, run=R5, model="qwen")
    assert code == 2
    _refused(run_dir, "only 10.0 GiB available after waiting 0 s; mflux q4 needs 32 GiB; free memory and retry",
             capsys.readouterr())
    assert calls["zimage"] == [] and stub_calls(py) == []
    assert record_of(run_dir)["size"] == {"width": 1024, "height": 672}


# --- SGT8 (SG14): the run-time Qwen choice -------------------------------------------------------------

def _qwen_refusal(tool):
    with pytest.raises(tool.Refusal) as info:
        tool.choose_qwen()
    return str(info.value)


def test_sgt8_choose_qwen(env):
    tool, mp, tmp = env["tool"], env["mp"], env["tmp"]
    zhub, hfhub = env["zhub"], env["hfhub"]
    lora_file = tool.EDIT_LORA_FILE
    head = "Qwen-Image-Edit is unavailable: diffusers bf16: Qwen/Qwen-Image-Edit-2511 is not in %s; mflux q4: " % hfhub
    py = os.path.join(tmp, "mflux-edit", ".venv", "bin", "python")
    venv = os.path.dirname(os.path.dirname(py))
    mp.setenv("SEED_EDIT_MFLUX_PYTHON", py)
    assert _qwen_refusal(tool) == head + "no mflux venv at %s (run bin/seed-edit-setup)" % py
    mflux_venv(env, version=None)
    assert _qwen_refusal(tool) == head + "mflux is not installed in %s (run bin/seed-edit-setup)" % venv
    set_mflux_version(venv, "banana")
    assert _qwen_refusal(tool) == head + "cannot read the mflux version in %s" % venv
    set_mflux_version(venv, "0.21.0")
    assert _qwen_refusal(tool) == head + "mflux 0.21.0 in %s is older than 0.22.0 (run bin/seed-edit-setup)" % venv
    set_mflux_version(venv, "0.24.0")
    assert _qwen_refusal(tool) == head + (
        "mflux-community/qwen-image-edit-2511-mflux-q4 is not in %s or %s (run bin/seed-edit-setup)" % (zhub, hfhub))
    q4, _lora = mflux_weights(env, lora=False)
    assert _qwen_refusal(tool) == head + "Lightning LoRA %s is not in %s or %s (run bin/seed-edit-setup)" % (
        lora_file, zhub, hfhub)
    lora_repo = mt.make_hf_cache(os.path.join(tmp, "zi"), tool.EDIT_LORA_REPO, {lora_file: b"\x01" * 8})
    lora = os.path.join(lora_repo, "snapshots", REV, lora_file)
    paths = {}
    assert tool.choose_qwen(paths) == ("mflux-q4", "diffusers bf16: Qwen/Qwen-Image-Edit-2511 is not in %s" % hfhub)
    assert paths == {"q4_dir": q4, "lora_file": lora}
    assert tool.mflux_problem() == (None, q4, lora)
    mp.setenv("SEED_EDIT_LIGHTNING_FILE", "relative.safetensors")
    assert _qwen_refusal(tool) == head + "SEED_EDIT_LIGHTNING_FILE relative.safetensors is not a non-empty file"
    mp.delenv("SEED_EDIT_LIGHTNING_FILE")
    mp.setenv("SEED_EDIT_QWEN_Q4_DIR", "qwen-image-edit-2511-q4")
    assert _qwen_refusal(tool) == head + "SEED_EDIT_QWEN_Q4_DIR qwen-image-edit-2511-q4: not an absolute path"
    wrong = os.path.join(tmp, "models", "qwen-edit-q4")
    os.makedirs(wrong)
    mp.setenv("SEED_EDIT_QWEN_Q4_DIR", wrong)
    assert _qwen_refusal(tool) == head + (
        "SEED_EDIT_QWEN_Q4_DIR %s: the directory name must contain qwen-image-edit-2511" % wrong)
    right = os.path.join(tmp, "models", "QWEN-IMAGE-EDIT-2511-q4")
    os.makedirs(right)
    mp.setenv("SEED_EDIT_QWEN_Q4_DIR", right)
    assert _qwen_refusal(tool) == head + "SEED_EDIT_QWEN_Q4_DIR %s: no .safetensors file" % right
    with open(os.path.join(right, "model.safetensors"), "wb") as f:
        f.write(b"\x01" * 8)
    paths = {}
    assert tool.choose_qwen(paths)[0] == "mflux-q4" and paths == {"q4_dir": right, "lora_file": lora}
    mp.delenv("SEED_EDIT_QWEN_Q4_DIR")
    bf16_cache(env)
    mp.setattr(tool, "avail_gib", lambda: 70.0)
    assert tool.choose_qwen() == ("diffusers-bf16", "70.0 GiB available")
    mp.setattr(tool, "avail_gib", lambda: 40.0)
    assert tool.choose_qwen() == ("mflux-q4", "diffusers bf16: only 40.0 GiB available (needs 64)")


# --- SGT9 (SG20, SG21, SG22): the mflux child, screened in the parent ----------------------------------

def test_sgt9_the_mflux_child_screened_in_the_parent(env, capsys):
    py, _venv = mflux_venv(env)
    q4, lora = mflux_weights(env)
    stub_config(py, {"red": [2]})
    code, run_dir = run_tool(env, "--candidates", "3", "--seed", "100", model="qwen")
    assert code == 0
    work = os.path.join(run_dir, "work")
    calls = stub_calls(py)
    assert len(calls) == 1
    assert calls[0]["argv"] == [py, os.path.join(WS, "seed_edit_mflux_child.py"), "--spec",
                                os.path.join(work, "mflux_spec.json")]
    assert calls[0]["env"] == {"HF_HUB_OFFLINE": "1", "PYTHONUNBUFFERED": "1"}
    assert calls[0]["spec"] == {
        "model_path": q4, "lora_path": lora, "prompt": PROMPT, "source": os.path.join(work, "source.png"),
        "width": 1024, "height": 672, "steps": 8, "guidance": 1.0,
        "jobs": [{"n": n, "seed": 100 + n, "output_path": os.path.join(work, "cand_%02d.pending.png" % n)}
                 for n in (1, 2, 3)]}
    assert [os.path.isfile(cand(run_dir, n)) for n in (1, 2, 3)] == [True, False, True]
    assert not os.path.exists(os.path.join(work, "cand_02.pending.png"))
    record = record_of(run_dir)
    assert statuses(run_dir) == ["ok", "blocked", "ok"]
    assert [c["seconds"] for c in record["candidates"]] == [1.0, 1.0, 1.0]
    assert (record["backend"], record["state"], record["strength"]) == ("mflux-q4", "done", None)
    assert env["calls"]["safety"] == [{"skill": "seed_edit", "prompt": PROMPT, "size": (1024, 672)}] * 3
    out = capsys.readouterr().out.splitlines()
    assert "seed-edit: backend mflux-q4 (diffusers bf16: Qwen/Qwen-Image-Edit-2511 is not in %s)" % env["hfhub"] in out
    assert plain([line for line in out if line.startswith("candidate ")]) == [
        "candidate 1/3 ok Ss", "candidate 2/3 blocked Ss", "candidate 3/3 ok Ss"]


# --- SGT10 (SG17, SG20): the mflux child fails or times out --------------------------------------------

def test_sgt10_the_mflux_child_fails_or_times_out(env, capsys):
    tool = env["tool"]
    py, _venv = mflux_venv(env)
    mflux_weights(env)
    stub_config(py, {"fail_after": 1})
    code, run_dir = run_tool(env, "--candidates", "3", "--seed", "100", model="qwen", run=R1)
    assert code == 1
    record = record_of(run_dir)
    assert statuses(run_dir) == ["ok", "failed", "failed"]
    assert (record["state"], record["error"]) == ("failed", "mflux q4 child exited 1: boom")
    assert os.path.isfile(cand(run_dir, 1))
    out = capsys.readouterr().out.splitlines()
    assert "boom" in out and out[-3:] == ["candidate 2/3 failed", "candidate 3/3 failed",
                                         "seed-edit: done: 1 ok, 0 blocked, 2 failed"]
    env["mp"].setattr(tool, "CHILD_TIMEOUT_S", 1)
    stub_config(py, {"sleep": 30})
    started = time.monotonic()
    code, run_dir = run_tool(env, "--candidates", "3", "--seed", "100", model="qwen", run=R2)
    assert code == 1 and time.monotonic() - started < 20
    record = record_of(run_dir)
    assert statuses(run_dir) == ["failed"] * 3
    assert record["error"] == "mflux q4 child timed out after %d s" % tool.CHILD_TIMEOUT_S
    assert tool.CHILD is None


# --- SGT11 (SG19, SG22): the diffusers bf16 child ------------------------------------------------------

def test_sgt11_the_bf16_child(env, capsys):
    tool = env["tool"]
    bf16_cache(env)
    env["mp"].setattr(tool, "avail_gib", lambda: 70.0)
    stub = qwenedit_stub(env, {"blocked": [2]})
    code, run_dir = run_tool(env, "--candidates", "2", "--seed", "100", model="qwen")
    assert code == 0
    work = os.path.join(run_dir, "work")
    calls = stub_calls(stub)
    assert len(calls) == 1
    assert calls[0]["argv"] == [sys.executable, stub, "qwenedit", "--spec", os.path.join(work, "qwenedit_spec.json")]
    assert calls[0]["env"] == {"PYTHONUNBUFFERED": "1"}
    assert calls[0]["spec"] == {
        "image": os.path.join(work, "source.png"), "model": "Qwen/Qwen-Image-Edit-2511",
        "lora_repo": "lightx2v/Qwen-Image-Edit-2511-Lightning",
        "lora_file": "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors", "steps": 8, "true_cfg": 1.0,
        "skill": "seed_edit",
        "jobs": [{"prompt": PROMPT, "output_path": os.path.join(work, "cand_%02d.part.png" % n), "seed": 100 + n,
                  "width": 1024, "height": 672} for n in (1, 2)],
        "report_path": os.path.join(work, "qwenedit_report.json")}
    assert statuses(run_dir) == ["ok", "blocked"]
    assert [os.path.isfile(cand(run_dir, n)) for n in (1, 2)] == [True, False]
    assert record_of(run_dir)["backend"] == "diffusers-bf16"
    assert "seed-edit: backend diffusers-bf16 (70.0 GiB available)" in capsys.readouterr().out.splitlines()
    assert env["calls"]["safety"] == []


# --- SGT12 (SG6, SG12): an interrupt -------------------------------------------------------------------

def test_sgt12_an_interrupt(env, capsys):
    zimage_cache(env)
    env["calls"]["plan"][102] = KeyboardInterrupt()
    code, run_dir = run_tool(env, "--candidates", "3", "--seed", "100")
    assert code == 130
    record = record_of(run_dir)
    assert (record["state"], record["error"]) == ("cancelled", "interrupted")
    assert statuses(run_dir) == ["ok", "failed", "failed"]
    assert capsys.readouterr().err == "seed-edit: interrupted\n"


# --- SGT13 (SG15): the probe ---------------------------------------------------------------------------

HEAVY = {"torch", "PIL", "psutil", "diffusers", "transformers", "z_image_skill", "content_safety",
         "character_dataset"}


def test_sgt13_the_probe(env, capsys):
    tool, mp = env["tool"], env["mp"]
    zimage_cache(env)
    mflux_venv(env)
    mflux_weights(env)
    assert tool.probe() == {"zimage": {"ok": True, "reason": None, "backend": "zimage"},
                            "qwen": {"ok": True, "reason": None, "backend": "mflux-q4"}}
    assert tool.main(["--probe"]) == 0
    assert capsys.readouterr().out == json.dumps(tool.probe(), sort_keys=True) + "\n"
    bf16_cache(env)
    mp.setattr(tool, "total_gib", lambda: 128.0)
    assert tool.probe()["qwen"] == {"ok": True, "reason": None, "backend": "diffusers-bf16"}
    missing = os.path.join(env["tmp"], "none", "bin", "python")
    mp.setenv("SEED_EDIT_MFLUX_PYTHON", missing)
    mp.setattr(tool, "total_gib", lambda: 48.0)
    assert tool.probe()["qwen"] == {
        "ok": False, "backend": None,
        "reason": "diffusers bf16: needs a host with at least 64 GiB of memory (this host has 48.0 GiB); mflux q4: "
                  "no mflux venv at %s (run bin/seed-edit-setup)" % missing}
    mp.setattr(tool, "total_gib", lambda: None)
    assert tool.probe()["qwen"]["reason"].startswith("diffusers bf16: cannot read this host's memory size; ")
    proc = subprocess.run([sys.executable, "-X", "importtime", TOOL_PATH, "--probe"], capture_output=True,
                          text=True, timeout=60, cwd=env["tmp"])
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert len(lines) == 1 and set(json.loads(lines[0])) == {"zimage", "qwen"}
    imported = set(line.rsplit("|", 1)[1].strip().split(".")[0] for line in proc.stderr.splitlines()
                   if line.startswith("import time:") and line.count("|") == 2)
    assert "movie_ui_lib" in imported
    assert not imported & HEAVY, sorted(imported & HEAVY)


# --- SGT14 (spec 1.1): the mirrored constants ----------------------------------------------------------

def test_sgt14_the_mirrored_constants():
    import character_dataset
    tool = load_tool()
    for name in ("EDIT_MODEL", "EDIT_LORA_REPO", "EDIT_LORA_FILE", "EDIT_STEPS", "EDIT_TRUE_CFG", "AVAIL_WAIT_S"):
        assert getattr(tool, name) == getattr(character_dataset, name), name
    assert tool.BF16_MIN_AVAIL_GIB == character_dataset.EDIT_MIN_AVAIL_GIB
    assert tool.ZIMAGE_MIN_AVAIL_GIB == character_dataset.GENERATE_MIN_AVAIL_GIB
    assert tool.MIN_FREE_GIB == character_dataset.CREATE_MIN_FREE_GIB


# --- Review Focus 3: prompts that look like shell or argparse input --------------------------------------

ODD_PROMPTS = ['say "hi" and \'bye\'', "line one\nline two\n\ttabbed", "$(rm -rf ~) `id` ; | & > < *",
               "make it night --model qwen --strength 0.9", "a=b --c=d -e", "emoji \U0001F3AC and ünïcödé",
               "x" * 1999 + "!"]


def test_sg_review_focus_3_prompts_survive_the_argv_round_trip(env):
    tool = env["tool"]
    zimage_cache(env)
    ws = os.path.join(env["tmp"], "ws")
    for i, text in enumerate(ODD_PROMPTS):
        run = "se-20261102-141500-%04x" % i
        run_dir = os.path.join(ws, "generated", "seeds", "runs", run)
        png(os.path.join(run_dir, "source.png"), (128, 96))
        assert seedgen.validate_run_request({"prompt": text, "model": "zimage", "source": {"upload_id": UP}})[1] is None
        fields = {"ws": ws, "run": run, "source_file": "source.png", "prompt": text, "model": "zimage",
                  "strength": 0.45, "candidates": 1, "seed": 5, "source": None}
        argv = lib.seed_edit_argv(fields, ws)
        assert argv[argv.index("--prompt") + 1] == text
        assert tool.main(argv[2:]) == 0, text
        assert record_of(run_dir)["prompt"] == text
        assert env["calls"]["zimage"][-1]["prompt"] == text


# --- Review Focus 4: progress bars in the children's lines ---------------------------------------------

def test_sg_review_focus_4_progress_bars_in_child_lines(env, capsys):
    tool = env["tool"]
    py, _venv = mflux_venv(env)
    mflux_weights(env)
    bar = "  0%|          | 0/8 [00:00<?, ?it/s]\r100%|##########| 8/8 [00:01<00:00]\r"
    stub_config(py, {"prefix": bar})
    code, run_dir = run_tool(env, "--candidates", "2", "--seed", "1", model="qwen", run=R1)
    assert code == 0 and statuses(run_dir) == ["ok", "ok"]
    assert "100%|##########| 8/8 [00:01<00:00]\nseed-edit-child done 1 1.0\n" in capsys.readouterr().out
    bf16_cache(env)
    env["mp"].setattr(tool, "avail_gib", lambda: 70.0)
    qwenedit_stub(env, {"prefix": "Loading pipeline components...: 100%|##########| 5/5\r"})
    code, run_dir = run_tool(env, "--candidates", "2", "--seed", "1", model="qwen", run=R2)
    assert code == 0 and statuses(run_dir) == ["ok", "ok"]
    assert record_of(run_dir)["backend"] == "diffusers-bf16"
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py 2>&1 | tail -1
```

Expected: `1 failed, 32 errors` (every `env` test errors in the fixture with `FileNotFoundError` for `bin/seed-edit`; `test_sgt14_the_mirrored_constants` fails the same way).

- [ ] **Step 3: Implement.**

Create `bin/seed-edit` with exactly this content (the Write tool; the file ends with one newline):

```python
#!/usr/bin/env python3
"""seed-edit -- edit one source image into 1 to 4 seed candidates with Z-Image img2img or
Qwen-Image-Edit-2511 (docs/superpowers/specs/2026-11-02-seed-generator-design.md, Section 2).

  bin/seed-edit --source PATH --prompt TEXT --model zimage|qwen [--strength S] [--candidates N]
                [--seed N] --run-dir DIR
  bin/seed-edit --probe

The movie-ui runs it as a queued GPU job of kind seed-edit; it also runs by hand. Candidate i
(1-based) uses seed + i and lands in <run dir>/cand_NN.png. --strength (0.10 to 0.90, default
0.45) is for zimage only; --candidates defaults to 4; a missing --seed is drawn at random.
Qwen-Image-Edit runs through diffusers bf16 (the unchanged character_dataset.py qwenedit child)
when at least 64 GiB is available and the bf16 weights are cached, else through mflux q4
(seed_edit_mflux_child.py under the mflux venv, every image screened here), else it refuses
before loading. --probe prints one JSON line {"qwen": {...}, "zimage": {...}}, each value
{"backend", "ok", "reason"}, and loads nothing.

Exit codes: 0 every candidate ended ok or blocked; 1 the backend failed (finished candidates are
kept, the rest are failed); 2 refused before any model loaded; 130 interrupted (SIGINT, SIGTERM
or SIGHUP).

run.json (schema seed-edit.run.v1) write order: (1) the run directory and work/ are created;
(2) the source is read, copied and sized, and a refusal writes state failed with every candidate
failed; (3) state running, backend null, every candidate pending; (4) the preflight and the
backend choice, a refusal written as in (2); (5) the backend; (6) per candidate: the final
cand_NN.png (ok only), then run.json, then the candidate line; (7) state done or failed; (8) an
interrupt kills the child, marks the pending candidates failed and writes state cancelled.
created, source_origin and job are kept from an existing run.json; the tool owns every other key.

Environment: SEED_EDIT_MFLUX_PYTHON (default ~/mflux-edit/.venv/bin/python),
SEED_EDIT_QWEN_Q4_DIR (a local q4 model directory whose name contains qwen-image-edit-2511),
SEED_EDIT_LIGHTNING_FILE (a local Lightning LoRA file), SEED_EDIT_QWENEDIT_SCRIPT (default
<ws>/character_dataset.py), HF_HUB_CACHE and HF_HOME (the default hub), Z_IMAGE_HF_HOME (the
Z-Image hub, through movie_ui_lib.zimage_hub) and HOME.

Python 3.9 and 3.13. The top level imports only the standard library and movie_ui_lib; PIL,
psutil, torch, z_image_skill, content_safety and character_dataset are imported inside the
functions that use them.
"""

import argparse
import glob
import importlib.util
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import movie_ui_lib as lib  # noqa: E402

LONG_EDGE = 1024
MULTIPLE = 16
MIN_SIDE = 64
PROMPT_MAX = 2000
SEED_MAX = 2147483647
STRENGTH_DEFAULT = 0.45
MIN_FREE_GIB = 2.0               # character_dataset.CREATE_MIN_FREE_GIB
ZIMAGE_MIN_AVAIL_GIB = 20.0      # character_dataset.GENERATE_MIN_AVAIL_GIB
BF16_MIN_AVAIL_GIB = 64.0        # character_dataset.EDIT_MIN_AVAIL_GIB
MFLUX_MIN_AVAIL_GIB = 32.0
AVAIL_WAIT_S = 600               # character_dataset.AVAIL_WAIT_S
CHILD_TIMEOUT_S = 3600
EDIT_MODEL = "Qwen/Qwen-Image-Edit-2511"                                  # character_dataset.EDIT_MODEL
EDIT_LORA_REPO = "lightx2v/Qwen-Image-Edit-2511-Lightning"                # character_dataset.EDIT_LORA_REPO
EDIT_LORA_FILE = "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors"
EDIT_STEPS = 8
EDIT_TRUE_CFG = 1.0
Q4_REPO = "mflux-community/qwen-image-edit-2511-mflux-q4"
Q4_NAME_PART = "qwen-image-edit-2511"
MFLUX_MIN_VERSION = (0, 22, 0)
MFLUX_GUIDANCE = 1.0
DEFAULT_MFLUX_PYTHON = "~/mflux-edit/.venv/bin/python"   # expanded at use
SAFETY_SKILL = "seed_edit"
BACKEND_LABELS = {"zimage": "Z-Image", "diffusers-bf16": "diffusers bf16", "mflux-q4": "mflux q4"}

EXTS = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}
BF16_LINE_RE = re.compile(r"^cand_(\d{2})\.part\.png (ok|blocked) ([0-9]+\.[0-9])s$")
MFLUX_LINE_RE = re.compile(r"^seed-edit-child done (\d+) ([0-9]+\.[0-9])$")
CHILD = None    # the running Qwen child's Popen (SG21), or None


class Refusal(Exception):
    """A refusal before any model loads (exit 2); the message is the error text."""


def say(text):
    """Every stdout line of the tool goes through here (SG7)."""
    print(text, flush=True)


def error(text):
    sys.stderr.write("Error: %s\n" % text)
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# The command line (SG4)
# ---------------------------------------------------------------------------

def parse(argv):
    parser = argparse.ArgumentParser(prog="seed-edit", description="Edit one source image into 1 to 4 "
                                     "seed candidates (Z-Image img2img or Qwen-Image-Edit-2511).")
    for name in ("--source", "--prompt", "--model", "--strength", "--candidates", "--seed", "--run-dir"):
        parser.add_argument(name, type=str)
    parser.add_argument("--probe", action="store_true")
    return parser.parse_args(argv)


def check_args(args):
    """SG4: the cleaned options (None for --probe), or Refusal with the first failing rule's text."""
    given = (args.source, args.prompt, args.model, args.strength, args.candidates, args.seed, args.run_dir)
    if args.probe:
        if any(value is not None for value in given):
            raise Refusal("--probe takes no other options")
        return None
    if None in (args.source, args.prompt, args.model, args.run_dir):
        raise Refusal("--source, --prompt, --model and --run-dir are required")
    if args.model not in ("zimage", "qwen"):
        raise Refusal("--model must be zimage or qwen")
    if not args.prompt.strip():
        raise Refusal("--prompt must not be empty")
    if len(args.prompt) > PROMPT_MAX:
        raise Refusal("--prompt is longer than 2000 characters")
    if args.candidates is None:
        candidates = 4
    elif re.fullmatch(r"[0-9]+", args.candidates) and 1 <= int(args.candidates) <= 4:
        candidates = int(args.candidates)
    else:
        raise Refusal("--candidates must be an integer from 1 to 4")
    if args.model == "qwen":
        if args.strength is not None:
            raise Refusal("--strength is only for --model zimage")
        strength = None
    elif args.strength is None:
        strength = STRENGTH_DEFAULT
    else:
        try:
            strength = float(args.strength)
        except ValueError:
            strength = None
        if strength is None or not 0.10 <= strength <= 0.90:
            raise Refusal("--strength must be a number from 0.10 to 0.90")
    if args.seed is None:
        seed = secrets.randbelow(SEED_MAX + 1)
    elif re.fullmatch(r"[0-9]+", args.seed) and int(args.seed) <= SEED_MAX:
        seed = int(args.seed)
    else:
        raise Refusal("--seed must be an integer from 0 to 2147483647")
    return {"source": args.source, "prompt": args.prompt, "model": args.model, "strength": strength,
            "candidates": candidates, "seed": seed, "run_dir": os.path.abspath(args.run_dir)}


# ---------------------------------------------------------------------------
# The source and its size (SG8-SG10)
# ---------------------------------------------------------------------------

def canvas(w0, h0):
    """SG8: the (W, H) edit canvas of a w0 x h0 source, or Refusal when a side is under MIN_SIDE."""
    longest = max(w0, h0)
    if longest <= LONG_EDGE:
        w, h = w0, h0
    else:
        w, h = w0 * LONG_EDGE // longest, h0 * LONG_EDGE // longest
    width, height = w // MULTIPLE * MULTIPLE, h // MULTIPLE * MULTIPLE
    if width < MIN_SIDE or height < MIN_SIDE:
        raise Refusal("--source is too small: %dx%d gives a %dx%d canvas; each side must be at least 64 px"
                      % (w0, h0, width, height))
    return width, height


def read_source(path):
    """SG8, SG9: (PIL format, the EXIF-transposed RGB image) of path, or Refusal."""
    from PIL import Image, ImageOps
    try:
        with Image.open(path) as img:
            fmt = img.format
            if fmt not in EXTS:
                raise Refusal("--source must be a PNG, JPEG or WebP image (got %s): %s" % (fmt, path))
            image = ImageOps.exif_transpose(img).convert("RGB")
    except Refusal:
        raise
    except Exception as e:
        raise Refusal("cannot read --source %s: %s: %s" % (path, type(e).__name__, e))
    return fmt, image


def prepare_source(ctx):
    """SG8-SG10: read the source, copy its bytes to <run>/source.<ext>, size it and save the
    transposed RGB image as work/source.png."""
    rec, path = ctx["record"], ctx["opts"]["source"]
    fmt, image = read_source(path)
    dest = os.path.join(ctx["dir"], "source." + EXTS[fmt])
    if not (os.path.exists(dest) and os.path.samefile(path, dest)):
        shutil.copyfile(path, dest)
    rec["source"] = os.path.basename(dest)
    w0, h0 = image.size
    width, height = canvas(w0, h0)
    rec["size"] = {"width": width, "height": height}
    rec["source_size"] = {"width": w0, "height": h0}
    image.save(os.path.join(ctx["work"], "source.png"))
    ctx["width"], ctx["height"] = width, height
    say("seed-edit: source %dx%d -> %dx%d" % (w0, h0, width, height))


# ---------------------------------------------------------------------------
# Host checks, the backend checks and the probe (SG13-SG15)
# ---------------------------------------------------------------------------

def disk_free_gib(path):
    return shutil.disk_usage(path).free / 2 ** 30


def avail_gib():
    import psutil
    return psutil.virtual_memory().available / 2 ** 30


def total_gib():
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 2 ** 30
    except (ValueError, OSError):
        return None


def cpu_generator(seed):
    import torch
    return torch.Generator("cpu").manual_seed(seed)


def missing_modules(names):
    """The names importlib cannot find (find_spec None, ImportError or ValueError); imports nothing."""
    missing = []
    for name in names:
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            missing.append(name)
    return missing


def modules_problem(names):
    missing = missing_modules(names)
    return "%s not importable by %s" % (", ".join(missing), sys.executable) if missing else None


def default_hub():
    """$HF_HUB_CACHE, else <$HF_HOME or ~/.cache/huggingface>/hub (huggingface_hub's own rule)."""
    if os.environ.get("HF_HUB_CACHE"):
        return os.environ["HF_HUB_CACHE"]
    return os.path.join(os.environ.get("HF_HOME") or os.path.expanduser("~/.cache/huggingface"), "hub")


def mflux_python():
    return os.environ.get("SEED_EDIT_MFLUX_PYTHON") or os.path.expanduser(DEFAULT_MFLUX_PYTHON)


def zimage_problem():
    """None when Z-Image img2img can run in this python, else the first problem."""
    problem = modules_problem(["PIL", "psutil", "torch", "diffusers", "transformers"])
    if problem:
        return problem
    for repo in (lib.STILLS_BASE_MODEL, lib.ZIMAGE_TEXT_ENCODER):
        ok, detail = lib.model_check(repo, lib.zimage_hub_for(repo))
        if not ok:
            return detail
    return None


def find_lightning(hubs):
    """The snapshot path of the Lightning LoRA file in the first hub holding it (a non-empty regular
    file through its realpath), or None."""
    for hub in hubs:
        snapshot = lib.choose_snapshot(os.path.join(hub, lib.repo_dir_name(EDIT_LORA_REPO)))[0]
        if snapshot is None:
            continue
        path = os.path.join(snapshot, EDIT_LORA_FILE)
        real = os.path.realpath(path)
        if os.path.isfile(real) and os.path.getsize(real) > 0:
            return path
    return None


def bf16_problem():
    """None when the diffusers bf16 child's weights and modules are present, else the first problem."""
    problem = modules_problem(["PIL", "psutil", "torch", "diffusers", "transformers", "huggingface_hub"])
    if problem:
        return problem
    hub = default_hub()
    ok, detail = lib.model_check(EDIT_MODEL, hub)
    if not ok:
        return detail
    if find_lightning([hub]) is None:
        return "Lightning LoRA %s is not in %s" % (EDIT_LORA_FILE, hub)
    return None


def mflux_version(venv):
    """(number of mflux-*.dist-info/METADATA files in venv, (parsed, text) of the highest version that
    parses or None). Reads the files only; nothing is imported."""
    paths = sorted(glob.glob(os.path.join(venv, "lib", "python*", "site-packages", "mflux-*.dist-info",
                                          "METADATA")))
    best = None
    for path in paths:
        text = None
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("Version: "):
                        text = line[len("Version: "):].strip()
                        break
        except OSError:
            continue
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)", text or "")
        if match:
            parsed = tuple(int(g) for g in match.groups())
            if best is None or parsed > best[0]:
                best = (parsed, text)
    return len(paths), best


def mflux_problem():
    """(problem, q4_dir, lora_file): problem is None when the mflux q4 backend is ready, and the two
    paths are None when it is not."""
    py = mflux_python()
    if not os.access(py, os.X_OK):
        return "no mflux venv at %s (run bin/seed-edit-setup)" % py, None, None
    venv = os.path.dirname(os.path.dirname(py))
    count, best = mflux_version(venv)
    if count == 0:
        return "mflux is not installed in %s (run bin/seed-edit-setup)" % venv, None, None
    if best is None:
        return "cannot read the mflux version in %s" % venv, None, None
    if best[0] < MFLUX_MIN_VERSION:
        return "mflux %s in %s is older than 0.22.0 (run bin/seed-edit-setup)" % (best[1], venv), None, None
    zhub, dhub = lib.zimage_hub(), default_hub()
    q4_dir = os.environ.get("SEED_EDIT_QWEN_Q4_DIR")
    if q4_dir:
        if not os.path.isabs(q4_dir):
            return "SEED_EDIT_QWEN_Q4_DIR %s: not an absolute path" % q4_dir, None, None
        if Q4_NAME_PART not in os.path.basename(os.path.normpath(q4_dir)).lower():
            return ("SEED_EDIT_QWEN_Q4_DIR %s: the directory name must contain qwen-image-edit-2511" % q4_dir,
                    None, None)
        ok, detail = lib.model_check(q4_dir, None)
        if not ok:
            return "SEED_EDIT_QWEN_Q4_DIR %s: %s" % (q4_dir, detail), None, None
    else:
        hub = None
        for candidate in (zhub, dhub):
            if os.path.isdir(os.path.join(candidate, lib.repo_dir_name(Q4_REPO))):
                hub = candidate
                break
        if hub is None:
            return "%s is not in %s or %s (run bin/seed-edit-setup)" % (Q4_REPO, zhub, dhub), None, None
        ok, detail = lib.model_check(Q4_REPO, hub)
        if not ok:
            return "%s: %s" % (Q4_REPO, detail), None, None
        q4_dir = lib.choose_snapshot(os.path.join(hub, lib.repo_dir_name(Q4_REPO)))[0]
    lora_file = os.environ.get("SEED_EDIT_LIGHTNING_FILE")
    if lora_file:
        real = os.path.realpath(lora_file)
        if not (os.path.isabs(lora_file) and os.path.isfile(real) and os.path.getsize(real) > 0):
            return "SEED_EDIT_LIGHTNING_FILE %s is not a non-empty file" % lora_file, None, None
    else:
        lora_file = find_lightning([zhub, dhub])
        if lora_file is None:
            return ("Lightning LoRA %s is not in %s or %s (run bin/seed-edit-setup)" % (EDIT_LORA_FILE, zhub, dhub),
                    None, None)
    problem = modules_problem(["PIL", "psutil", "torch", "transformers"])
    if problem:
        return problem, None, None
    return None, q4_dir, lora_file


def choose_qwen(paths=None):
    """SG14's run-time choice: ("diffusers-bf16" or "mflux-q4", why), or Refusal. When paths is a dict,
    a mflux-q4 choice also stores its "q4_dir" and "lora_file" there."""
    b = bf16_problem()
    if b is None:
        a = avail_gib()
        if a >= BF16_MIN_AVAIL_GIB:
            return "diffusers-bf16", "%.1f GiB available" % a
        b = "only %.1f GiB available (needs 64)" % a
    m, q4_dir, lora_file = mflux_problem()
    if m is None:
        if paths is not None:
            paths["q4_dir"], paths["lora_file"] = q4_dir, lora_file
        return "mflux-q4", "diffusers bf16: %s" % b
    raise Refusal("Qwen-Image-Edit is unavailable: diffusers bf16: %s; mflux q4: %s" % (b, m))


def probe():
    """SG15: {"zimage": {...}, "qwen": {...}}, each {"ok", "reason", "backend"}; bf16 is judged by the
    host's total memory. Loads no model and starts no process."""
    p = zimage_problem()
    t = total_gib()
    if t is None:
        b = "cannot read this host's memory size"
    elif t < BF16_MIN_AVAIL_GIB:
        b = "needs a host with at least 64 GiB of memory (this host has %.1f GiB)" % t
    else:
        b = bf16_problem()
    m = mflux_problem()[0]
    ok = b is None or m is None
    backend = "diffusers-bf16" if b is None else ("mflux-q4" if m is None else None)
    return {"zimage": {"ok": p is None, "reason": p, "backend": "zimage" if p is None else None},
            "qwen": {"ok": ok, "reason": None if ok else "diffusers bf16: %s; mflux q4: %s" % (b, m),
                     "backend": backend}}


def wait_for_memory(floor, label):
    """SG13 step 4: wait up to AVAIL_WAIT_S for floor GiB available, else Refusal."""
    now = avail_gib()
    if now >= floor:
        return
    say("seed-edit: waiting up to %d s for %g GiB available (now %.1f GiB)" % (AVAIL_WAIT_S, floor, now))
    deadline = time.monotonic() + AVAIL_WAIT_S
    while True:
        now = avail_gib()
        if now >= floor:
            return
        if time.monotonic() >= deadline:
            raise Refusal("only %.1f GiB available after waiting %d s; %s needs %g GiB; free memory and retry"
                          % (now, AVAIL_WAIT_S, label, floor))
        time.sleep(5)


def preflight(ctx):
    """SG13: disk, busy GPU, the backend (SG14), the memory floor; (backend, why) or Refusal."""
    run_dir = ctx["dir"]
    free = disk_free_gib(run_dir)
    if free < MIN_FREE_GIB:
        raise Refusal("less than 2 GiB free on the disk holding %s (%.1f GiB free)" % (run_dir, free))
    import character_dataset
    busy = character_dataset.busy_process()
    if busy:
        raise Refusal("another GPU process is running (pid %s: %s); try again when it ends" % (busy[0], busy[1]))
    if ctx["opts"]["model"] == "zimage":
        problem = zimage_problem()
        if problem is not None:
            raise Refusal("Z-Image is unavailable: %s" % problem)
        backend, why = "zimage", "Z-Image img2img"
    else:
        paths = {}
        backend, why = choose_qwen(paths)
        ctx.update(paths)
    floor = {"zimage": ZIMAGE_MIN_AVAIL_GIB, "mflux-q4": MFLUX_MIN_AVAIL_GIB}.get(backend)
    if floor is not None:
        wait_for_memory(floor, BACKEND_LABELS[backend])
    return backend, why


# ---------------------------------------------------------------------------
# run.json and the candidates (SG11, SG12, SG16)
# ---------------------------------------------------------------------------

def new_record(run_dir, opts):
    old = lib.read_json(os.path.join(run_dir, "run.json"))
    if isinstance(old, dict):
        created, origin, job = old.get("created"), old.get("source_origin"), old.get("job")
    else:
        created, origin, job = lib.utc_now(), None, None
    return {"schema": "seed-edit.run.v1", "run": os.path.basename(run_dir), "created": created,
            "state": "running", "prompt": opts["prompt"], "model": opts["model"], "backend": None,
            "strength": opts["strength"], "seed": opts["seed"], "size": None, "source_size": None,
            "source": None, "source_origin": origin, "job": job, "error": None,
            "candidates": [{"n": i, "seed": opts["seed"] + i, "status": "pending", "seconds": None}
                           for i in range(1, opts["candidates"] + 1)]}


def write_run(ctx):
    lib.write_json_atomic(os.path.join(ctx["dir"], "run.json"), ctx["record"])


def final_path(ctx, n):
    return os.path.join(ctx["dir"], "cand_%02d.png" % n)


def part_path(ctx, n):
    return os.path.join(ctx["work"], "cand_%02d.part.png" % n)


def pending_path(ctx, n):
    return os.path.join(ctx["work"], "cand_%02d.pending.png" % n)


def pending_candidate(ctx, n):
    """Candidate n's entry while it is pending, else None."""
    cands = ctx["record"]["candidates"]
    if 1 <= n <= len(cands) and cands[n - 1]["status"] == "pending":
        return cands[n - 1]
    return None


def first_pending(ctx):
    """The first pending candidate's n, else the candidate count."""
    cands = ctx["record"]["candidates"]
    for cand in cands:
        if cand["status"] == "pending":
            return cand["n"]
    return len(cands)


def finish(ctx, n, status, seconds=None):
    """SG12 step 6, SG16: record candidate n's status in run.json, then print its line. An ok
    candidate's cand_NN.png is already in place."""
    cands = ctx["record"]["candidates"]
    cand = cands[n - 1]
    cand["status"] = status
    cand["seconds"] = None if seconds is None or status == "failed" else round(seconds, 1)
    write_run(ctx)
    if status == "failed":
        say("candidate %d/%d failed" % (n, len(cands)))
    else:
        say("candidate %d/%d %s %.1fs" % (n, len(cands), status, cand["seconds"]))


def fail_rest(ctx):
    """SG16: every candidate not yet finished gets its own failed line, in order."""
    for cand in ctx["record"]["candidates"]:
        if cand["status"] == "pending":
            finish(ctx, cand["n"], "failed")


def refuse(ctx, text):
    """SG12 steps 2 and 4: state failed, error, every candidate failed; exit 2."""
    rec = ctx["record"]
    for cand in rec["candidates"]:
        cand["status"], cand["seconds"] = "failed", None
    rec["state"], rec["error"] = "failed", text
    write_run(ctx)
    error(text)
    return 2


def cleanup(work):
    """SG12 step 7: delete leftover work/*.part.png and work/*.pending.png."""
    for pattern in ("*.part.png", "*.pending.png"):
        for path in glob.glob(os.path.join(work, pattern)):
            try:
                os.remove(path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# The backends (SG17-SG22)
# ---------------------------------------------------------------------------

def run_zimage(ctx):
    """SG18: Z-Image img2img in this process (the z_image_skill singleton loads once); returns None.
    A content-safety block is that candidate only; any other exception propagates to run()."""
    import z_image_skill
    import content_safety
    from PIL import Image
    opts = ctx["opts"]
    with Image.open(os.path.join(ctx["work"], "source.png")) as img:
        src = img.convert("RGB").resize((ctx["width"], ctx["height"]), Image.LANCZOS)
    for cand in ctx["record"]["candidates"]:
        n = cand["n"]
        started = time.monotonic()
        try:
            image = z_image_skill.generate_variation(src, opts["prompt"], output_path=None,
                                                     strength=opts["strength"], generator=cpu_generator(cand["seed"]))
        except content_safety.ContentSafetyError:
            finish(ctx, n, "blocked", time.monotonic() - started)
            continue
        seconds = time.monotonic() - started
        image.save(part_path(ctx, n))
        os.replace(part_path(ctx, n), final_path(ctx, n))
        finish(ctx, n, "ok", seconds)
    return None


def _kill_group(pid):
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except OSError:
        pass


def run_child(argv, env, on_line):
    """SG21: run a Qwen child in its own session with a CHILD_TIMEOUT_S timer that SIGKILLs its
    process group; echo each line to stdout and pass it to on_line without its newline. Text mode
    reads with universal newlines, so a progress bar's carriage return also ends a line and never
    hides a candidate line. Returns the exit code (-9 after the timeout). The child is killed if
    this function exits early (an exception in on_line, or an interrupt)."""
    global CHILD
    proc = subprocess.Popen(argv, cwd=WS, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                            bufsize=1, start_new_session=True)
    CHILD = proc
    timer = threading.Timer(CHILD_TIMEOUT_S, _kill_group, args=(proc.pid,))
    timer.daemon = True
    timer.start()
    try:
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            on_line(line.rstrip("\n"))
        return proc.wait()
    finally:
        timer.cancel()
        if proc.poll() is None:
            _kill_group(proc.pid)
            proc.wait()
        proc.stdout.close()
        CHILD = None


def run_qwen_child(ctx, label, argv, env, handle):
    """SG17, SG19-SG21: run a Qwen child, handing each line to handle; None, or the SG17 text."""
    last = [""]

    def on_line(line):
        if line.strip():
            last[0] = line.strip()
        handle(line)

    code = run_child(argv, env, on_line)
    if code == -9:
        return "%s child timed out after %d s" % (label, CHILD_TIMEOUT_S)
    if code != 0:
        return "%s child exited %d: %s" % (label, code, last[0] or "-")
    if any(cand["status"] == "pending" for cand in ctx["record"]["candidates"]):
        return "%s child exited 0 without finishing candidate %d" % (label, first_pending(ctx))
    return None


def run_bf16(ctx):
    """SG19: the unchanged character_dataset.py qwenedit child (it screens with skill seed_edit and
    never saves a blocked image); returns None or the SG17 text."""
    work, opts, rec = ctx["work"], ctx["opts"], ctx["record"]
    spec_path = os.path.join(work, "qwenedit_spec.json")
    lib.write_json_atomic(spec_path, {
        "image": os.path.join(work, "source.png"), "model": EDIT_MODEL, "lora_repo": EDIT_LORA_REPO,
        "lora_file": EDIT_LORA_FILE, "steps": EDIT_STEPS, "true_cfg": EDIT_TRUE_CFG, "skill": SAFETY_SKILL,
        "jobs": [{"prompt": opts["prompt"], "output_path": part_path(ctx, c["n"]), "seed": c["seed"],
                  "width": ctx["width"], "height": ctx["height"]} for c in rec["candidates"]],
        "report_path": os.path.join(work, "qwenedit_report.json")})
    script = os.environ.get("SEED_EDIT_QWENEDIT_SCRIPT") or os.path.join(WS, "character_dataset.py")

    def handle(line):
        match = BF16_LINE_RE.match(line)
        if not match or pending_candidate(ctx, int(match.group(1))) is None:
            return
        n = int(match.group(1))
        if match.group(2) == "ok":
            os.replace(part_path(ctx, n), final_path(ctx, n))
        finish(ctx, n, match.group(2), float(match.group(3)))

    return run_qwen_child(ctx, "diffusers bf16", [sys.executable, script, "qwenedit", "--spec", spec_path],
                          dict(os.environ, PYTHONUNBUFFERED="1"), handle)


def run_mflux(ctx):
    """SG20: seed_edit_mflux_child.py under the mflux venv; this process screens every pending image
    before it gets its final name. Returns None or the SG17 text."""
    import content_safety
    from PIL import Image
    work, opts, rec = ctx["work"], ctx["opts"], ctx["record"]
    spec_path = os.path.join(work, "mflux_spec.json")
    lib.write_json_atomic(spec_path, {
        "model_path": ctx["q4_dir"], "lora_path": ctx["lora_file"], "prompt": opts["prompt"],
        "source": os.path.join(work, "source.png"), "width": ctx["width"], "height": ctx["height"],
        "steps": EDIT_STEPS, "guidance": MFLUX_GUIDANCE,
        "jobs": [{"n": c["n"], "seed": c["seed"], "output_path": pending_path(ctx, c["n"])}
                 for c in rec["candidates"]]})

    def handle(line):
        match = MFLUX_LINE_RE.match(line)
        if not match or pending_candidate(ctx, int(match.group(1))) is None:
            return
        n, seconds = int(match.group(1)), float(match.group(2))
        with Image.open(pending_path(ctx, n)) as img:
            rgb = img.convert("RGB")
        try:
            content_safety.assert_image_safe(rgb, skill=SAFETY_SKILL, prompt=opts["prompt"])
        except content_safety.ContentSafetyError:
            os.remove(pending_path(ctx, n))
            finish(ctx, n, "blocked", seconds)
            return
        os.replace(pending_path(ctx, n), final_path(ctx, n))
        finish(ctx, n, "ok", seconds)

    argv = [mflux_python(), os.path.join(WS, "seed_edit_mflux_child.py"), "--spec", spec_path]
    return run_qwen_child(ctx, "mflux q4", argv, dict(os.environ, PYTHONUNBUFFERED="1", HF_HUB_OFFLINE="1"),
                          handle)


# ---------------------------------------------------------------------------
# main (SG5-SG7, SG12)
# ---------------------------------------------------------------------------

def run(ctx):
    """SG12 steps 2-7 for one run; returns the exit code."""
    rec = ctx["record"]
    try:
        prepare_source(ctx)
    except Refusal as e:
        return refuse(ctx, str(e))
    rec["state"] = "running"
    write_run(ctx)
    try:
        backend, why = preflight(ctx)
    except Refusal as e:
        return refuse(ctx, str(e))
    rec["backend"] = backend
    write_run(ctx)
    say("seed-edit: backend %s (%s)" % (backend, why))
    runner = {"zimage": run_zimage, "diffusers-bf16": run_bf16, "mflux-q4": run_mflux}[backend]
    try:
        failure = runner(ctx)
    except Exception as e:
        failure = "%s failed on candidate %d: %s: %s" % (BACKEND_LABELS[backend], first_pending(ctx),
                                                         type(e).__name__, e)
    fail_rest(ctx)
    statuses = [cand["status"] for cand in rec["candidates"]]
    rec["state"] = "failed" if "failed" in statuses else "done"
    rec["error"] = failure
    write_run(ctx)
    say("seed-edit: done: %d ok, %d blocked, %d failed" % (statuses.count("ok"), statuses.count("blocked"),
                                                          statuses.count("failed")))
    return 0 if failure is None and "failed" not in statuses else 1


def main(argv=None):
    """bin/seed-edit (SG4-SG23). Returns the exit code; installs no signal handler."""
    args = parse(argv)
    try:
        opts = check_args(args)
    except Refusal as e:
        error(str(e))
        return 2
    if opts is None:
        say(json.dumps(probe(), sort_keys=True))
        return 0
    run_dir = opts["run_dir"]
    os.makedirs(run_dir, exist_ok=True)
    os.makedirs(os.path.join(run_dir, "work"), exist_ok=True)
    ctx = {"dir": run_dir, "work": os.path.join(run_dir, "work"), "opts": opts,
           "record": new_record(run_dir, opts)}
    say("seed-edit: run %s" % run_dir)
    try:
        return run(ctx)
    except KeyboardInterrupt:
        child = CHILD
        if child is not None:
            _kill_group(child.pid)
        for cand in ctx["record"]["candidates"]:
            if cand["status"] == "pending":
                cand["status"] = "failed"
        ctx["record"]["state"], ctx["record"]["error"] = "cancelled", "interrupted"
        write_run(ctx)
        sys.stderr.write("seed-edit: interrupted\n")
        return 130
    finally:
        cleanup(ctx["work"])


def _interrupt(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    # A movie-ui Cancel (SIGTERM), a closed terminal (SIGHUP) and Ctrl-C take the same path (SG6).
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _interrupt)
    sys.exit(main())
```

Then make it executable, like the other `bin/` tools:

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
chmod 755 bin/seed-edit && ls -l bin/seed-edit | cut -c1-10    # expected: -rwxr-xr-x
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py 2>&1 | tail -1
```

Expected: `33 passed` (SGT1, SGT3, SGT4, SGT6-SGT14 one each, SGT2 two, SGT5's 17 cases, Review Focus 3 and 4). Run the compile check with `FILES` = `bin/seed-edit tests/test_seed_edit_tool.py`; expected: `compiled 2` twice. Then run the gate block with `N=3`. Expected: `GATE PASS`, `lost 0`, `new tests 72, not passing 0`, `baseline failures still failing 2 of 2`, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
git add bin/seed-edit tests/test_seed_edit_tool.py
git diff --cached --name-only    # expected: those 2 paths
git ls-files -s bin/seed-edit | cut -c1-6    # expected: 100755
git commit -m "feat: bin/seed-edit, one source image into 1-4 seed candidates: argv, canvas, run.json write order, preflight, Qwen backend choice by memory, probe, Z-Image in process, diffusers bf16 and mflux q4 children with parent-side screening (SG2, SG4-SG23; SGT1-SGT14)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `seed_edit_mflux_child.py` and `bin/seed-edit-setup` (SG24-SG27, SG66-SG69; SGT15, SGT16)

This task implements:
- SG24-SG27: `seed_edit_mflux_child.py`, the spec's body verbatim (SG25), with a module docstring and SG24's top-level imports.
- SG66-SG69: `bin/seed-edit-setup`: steps 1-9 of SG67, its own identical copies of `mflux_version` and `find_lightning` (SGT16 pins the code equal to `bin/seed-edit`'s), the `DOWNLOAD` program, and the exit codes. No test runs it; only the controller does, in Verification L1, on the user's go.

Tests: SGT15 and SGT16, appended to `tests/test_seed_edit_tool.py`. SGT15 calls the child's `main` only with `importlib.metadata.version` patched to an old or missing mflux, so it returns before reading the spec or importing mlx.

**Files:**
- Create: `seed_edit_mflux_child.py`, `bin/seed-edit-setup` (then `chmod 755`).
- Modify: `tests/test_seed_edit_tool.py` (append after Review Focus 4).
- Read only: `bin/seed-edit` (Task 3: `mflux_version`, `find_lightning`, the repo constants).

**Interfaces:**
- Consumes: Task 3's `bin/seed-edit` (`mflux_version`, `find_lightning`, `Q4_REPO`, `EDIT_LORA_REPO`, `EDIT_LORA_FILE`; setup step 9 runs `bin/seed-edit --probe`); `lib.zimage_hub`, `lib.model_check`, `lib.choose_snapshot`, `lib.repo_dir_name`, `lib.last_line`.
- Produces: `seed_edit_mflux_child.main(argv=None) -> int`, `parse_version(text)`, `exit_with_parent(poll_s=2.0)`, `MIN_VERSION`; `bin/seed-edit-setup`'s `main(argv=None) -> int` (exit 0, 1 or 2) and its constants `VENV`, `MFLUX_SPEC`, `MFLUX_VERSION`, `SETUP_MIN_FREE_GIB`, `DEFAULT_BASE_PYTHON`, `Q4_REPO`, `EDIT_LORA_REPO`, `EDIT_LORA_FILE`, `DOWNLOAD`.
- The child's line the tool parses (Task 3's `MFLUX_LINE_RE`): `seed-edit-child done <n> <s.s>`.

- [ ] **Step 1: Write the failing tests.**

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
    code, run_dir = run_tool(env, "--candidates", "2", "--seed", "1", model="qwen", run=R2)
    assert code == 0 and statuses(run_dir) == ["ok", "ok"]
    assert record_of(run_dir)["backend"] == "diffusers-bf16"
```

with:

```python
    code, run_dir = run_tool(env, "--candidates", "2", "--seed", "1", model="qwen", run=R2)
    assert code == 0 and statuses(run_dir) == ["ok", "ok"]
    assert record_of(run_dir)["backend"] == "diffusers-bf16"


# --- SGT15 (SG24, SG25, SG27): the mflux child ---------------------------------------------------------

def test_sgt15_the_mflux_child(monkeypatch, tmp_path, capsys):
    import seed_edit_mflux_child as child
    with open(os.path.join(WS, "seed_edit_mflux_child.py"), encoding="utf-8") as f:
        source = f.read()
    assert re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M) == [
        "argparse", "importlib.metadata", "json", "os", "re", "sys", "threading", "time"]
    for text, want in (("0.24.0", (0, 24, 0)), ("0.22.0", (0, 22, 0)), ("0.21.9", (0, 21, 9)), ("x", None),
                       (None, None)):
        assert child.parse_version(text) == want, text
    assert child.parse_version("0.21.9") < child.MIN_VERSION <= child.parse_version("0.22.0")
    monkeypatch.setattr(child, "exit_with_parent", lambda poll_s=2.0: None)
    monkeypatch.setattr(child.importlib.metadata, "version", lambda name: "0.21.0")
    missing = os.path.join(str(tmp_path), "missing-spec.json")
    assert child.main(["--spec", missing]) == 2
    assert capsys.readouterr().out == ("seed-edit-child: mflux 0.21.0 is missing or older than 0.22.0; refusing "
                                       "(it would run Qwen-Image-Edit-2509)\n")

    def not_installed(name):
        raise child.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(child.importlib.metadata, "version", not_installed)
    assert child.main(["--spec", missing]) == 2
    assert capsys.readouterr().out.startswith("seed-edit-child: mflux None is missing or older than 0.22.0")
    for text in ('guidance=spec["guidance"]', "bake_lora=False", 'negative_prompt=" "',
                 "ModelConfig.qwen_image_edit_2511()", "quantize=None", "lora_scales=[1.0]"):
        assert text in source, text


# --- SGT16 (SG66-SG69): bin/seed-edit-setup is read, never run ------------------------------------------

def _code_of(source, name):
    """The text of function name in source, without its docstring."""
    start = source.index("\ndef %s(" % name)
    text = source[start:source.index("\n\n\n", start)]
    doc = text.index('"""')
    return text[:doc] + text[text.index('"""', doc + 3) + 3:]


def test_sgt16_the_setup_script_is_read_never_run():
    with open(os.path.join(WS, "bin", "seed-edit-setup"), encoding="utf-8") as f:
        source = f.read()
    with open(TOOL_PATH, encoding="utf-8") as f:
        tool_source = f.read()
    assert source.startswith("#!/usr/bin/env python3\n")
    for text in ('"mflux==0.24.0"', "SETUP_MIN_FREE_GIB = 31.0", "HF_XET_CHUNK_CACHE_SIZE_BYTES", "cache_dir=hub",
                 'VENV = "~/mflux-edit/.venv"',
                 'DEFAULT_BASE_PYTHON = "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13"'):
        assert text in source, text
    assert "HF_TOKEN" not in source
    tool = load_tool()
    for name in ("Q4_REPO", "EDIT_LORA_REPO", "EDIT_LORA_FILE"):
        assert '%s = "%s"' % (name, getattr(tool, name)) in source, name
    for name in ("mflux_version", "find_lightning"):
        assert _code_of(source, name) == _code_of(tool_source, name), name
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py 2>&1 | tail -1
```

Expected: `2 failed, 33 passed` (SGT15: `ModuleNotFoundError: No module named 'seed_edit_mflux_child'`; SGT16: `FileNotFoundError` for `bin/seed-edit-setup`).

- [ ] **Step 3: Implement.**

**3.1.** Create `seed_edit_mflux_child.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""seed_edit_mflux_child.py -- bin/seed-edit's mflux q4 child: load Qwen-Image-Edit-2511 once from a
local q4 directory with the Lightning LoRA as a local file, then edit the source into every job of
a spec file (docs/superpowers/specs/2026-11-02-seed-generator-design.md, Section 3).

  ~/mflux-edit/.venv/bin/python seed_edit_mflux_child.py --spec SPEC

Runs under the mflux venv's Python (mflux pinned to 0.24.0). It never screens: bin/seed-edit
screens each pending image before giving it its final name. After saving each job's image it
prints "seed-edit-child done <n> <seconds>". guidance is the spec's (always 1.0) and the LoRA is
never baked into the quantized weights.

Exit codes: 0 every job saved; 2 mflux missing or older than 0.22.0 (refused before the spec is
read; an older mflux would run Qwen-Image-Edit-2509); 3 the parent died; anything else is a crash.
Top-level imports are standard library only; mlx and mflux are imported inside main after the
version gate.
"""

import argparse
import importlib.metadata
import json
import os
import re
import sys
import threading
import time

MIN_VERSION = (0, 22, 0)


def parse_version(text):
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(g) for g in m.groups()) if m else None


def exit_with_parent(poll_s=2.0):
    parent = os.getppid()

    def _watch():
        while True:
            time.sleep(poll_s)
            if os.getppid() != parent:
                os._exit(3)

    threading.Thread(target=_watch, daemon=True).start()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="seed_edit_mflux_child.py")
    parser.add_argument("--spec", required=True)
    args = parser.parse_args(argv)
    exit_with_parent()
    try:
        version = importlib.metadata.version("mflux")
    except importlib.metadata.PackageNotFoundError:
        version = None
    parsed = parse_version(version)
    if parsed is None or parsed < MIN_VERSION:
        print("seed-edit-child: mflux %s is missing or older than 0.22.0; refusing (it would run "
              "Qwen-Image-Edit-2509)" % version, flush=True)
        return 2
    with open(args.spec, encoding="utf-8") as f:
        spec = json.load(f)
    import mlx.core as mx
    from mflux.models.common.config.model_config import ModelConfig
    from mflux.models.qwen.variants.edit.qwen_image_edit import QwenImageEdit
    config = ModelConfig.qwen_image_edit_2511()
    print("seed-edit-child: mflux %s, model %s, transformer overrides %s"
          % (version, config.model_name, config.transformer_overrides), flush=True)
    model = QwenImageEdit(model_path=spec["model_path"], quantize=None, model_config=config,
                          lora_paths=[spec["lora_path"]], lora_scales=[1.0], bake_lora=False)
    peak = getattr(mx, "get_peak_memory", None) or mx.metal.get_peak_memory
    for job in spec["jobs"]:
        started = time.monotonic()
        result = model.generate_image(seed=job["seed"], prompt=spec["prompt"],
                                      image_paths=[spec["source"]],
                                      num_inference_steps=spec["steps"], guidance=spec["guidance"],
                                      negative_prompt=" ", width=spec["width"], height=spec["height"])
        result.image.save(job["output_path"])
        seconds = time.monotonic() - started
        print("seed-edit-child: mlx peak memory %.2f GiB" % (peak() / 2 ** 30), flush=True)
        print("seed-edit-child done %d %.1f" % (job["n"], seconds), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**3.2.** Create `bin/seed-edit-setup` with exactly this content (the Write tool; the file ends with one newline):

```python
#!/usr/bin/env python3
"""seed-edit-setup -- create the mflux venv and download the Qwen-Image-Edit-2511 q4 weights and the
Lightning LoRA that bin/seed-edit's mflux q4 backend needs
(docs/superpowers/specs/2026-11-02-seed-generator-design.md, Section 7).

  bin/seed-edit-setup

Run only by the controller on the user's go; never by a test. Steps: refuse when
SEED_EDIT_MFLUX_PYTHON is set; read what is present (the venv ~/mflux-edit/.venv with mflux
0.24.0, the q4 repo and the Lightning file in the Z-Image hub); with all three present, print the
sizes and exit; else check 31 GiB of free space and a base Python of 3.11 or newer
(SEED_EDIT_SETUP_PYTHON, default the 3.13 framework Python), create the venv, pip install
mflux==0.24.0, download the q4 repo snapshot and the single Lightning file (both public; no token)
into the Z-Image hub ($Z_IMAGE_HF_HOME/hub or ~/hf_home/hub, never $HF_HOME), then print the sizes
and bin/seed-edit --probe's Qwen-Image-Edit verdict. Re-running after success only prints;
re-running after a partial download resumes it.

Exit codes: 0 done or nothing to do; 1 a step failed; 2 a precondition failed.
Standard library plus movie_ui_lib. Python 3.9 and 3.13.
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import movie_ui_lib as lib  # noqa: E402

VENV = "~/mflux-edit/.venv"
MFLUX_SPEC = "mflux==0.24.0"
MFLUX_VERSION = "0.24.0"
SETUP_MIN_FREE_GIB = 31.0
DEFAULT_BASE_PYTHON = "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13"
Q4_REPO = "mflux-community/qwen-image-edit-2511-mflux-q4"
EDIT_LORA_REPO = "lightx2v/Qwen-Image-Edit-2511-Lightning"
EDIT_LORA_FILE = "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors"
DOWNLOAD = ("import sys\n"
            "from huggingface_hub import hf_hub_download, snapshot_download\n"
            "hub, repo, lora_repo, lora_file = sys.argv[1:5]\n"
            "print(snapshot_download(repo_id=repo, cache_dir=hub), flush=True)\n"
            "print(hf_hub_download(repo_id=lora_repo, filename=lora_file, cache_dir=hub), flush=True)\n")


def say(text):
    print("seed-edit-setup: " + text, flush=True)


def fail(code, text):
    sys.stderr.write("Error: %s\n" % text)
    return code


def mflux_version(venv):
    """bin/seed-edit's mflux_version, copied with identical behaviour: (number of
    mflux-*.dist-info/METADATA files in venv, (parsed, text) of the highest version that parses or
    None)."""
    paths = sorted(glob.glob(os.path.join(venv, "lib", "python*", "site-packages", "mflux-*.dist-info",
                                          "METADATA")))
    best = None
    for path in paths:
        text = None
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("Version: "):
                        text = line[len("Version: "):].strip()
                        break
        except OSError:
            continue
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)", text or "")
        if match:
            parsed = tuple(int(g) for g in match.groups())
            if best is None or parsed > best[0]:
                best = (parsed, text)
    return len(paths), best


def find_lightning(hubs):
    """bin/seed-edit's find_lightning, copied with identical behaviour."""
    for hub in hubs:
        snapshot = lib.choose_snapshot(os.path.join(hub, lib.repo_dir_name(EDIT_LORA_REPO)))[0]
        if snapshot is None:
            continue
        path = os.path.join(snapshot, EDIT_LORA_FILE)
        real = os.path.realpath(path)
        if os.path.isfile(real) and os.path.getsize(real) > 0:
            return path
    return None


def existing_ancestor(path):
    path = os.path.abspath(path)
    while not os.path.exists(path) and os.path.dirname(path) != path:
        path = os.path.dirname(path)
    return path


def free_gib(path):
    return shutil.disk_usage(path).free / 2 ** 30


def tree_gib(path):
    """The sum of the lstat sizes under path (symlinks not followed), in GiB."""
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for name in dirnames + filenames:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                pass
    return total / 2 ** 30


def snapshot_gib(snapshot):
    """The sum of the realpath sizes of the snapshot's files, each realpath once, in GiB."""
    seen, total = set(), 0
    for dirpath, _dirnames, filenames in os.walk(snapshot):
        for name in filenames:
            real = os.path.realpath(os.path.join(dirpath, name))
            if real not in seen and os.path.isfile(real):
                seen.add(real)
                total += os.path.getsize(real)
    return total / 2 ** 30


def venv_ready(py, venv):
    best = mflux_version(venv)[1]
    return os.access(py, os.X_OK) and best is not None and best[1] == MFLUX_VERSION


def report(venv, hub):
    """Step 9: the sizes, then bin/seed-edit --probe's Qwen-Image-Edit verdict (informational)."""
    say("venv %s: %.2f GiB" % (venv, tree_gib(venv) if os.path.isdir(venv) else 0.0))
    snapshot = lib.choose_snapshot(os.path.join(hub, lib.repo_dir_name(Q4_REPO)))[0]
    if snapshot is not None and os.path.isdir(snapshot):
        say("q4 %s: %.2f GiB" % (snapshot, snapshot_gib(snapshot)))
    else:
        say("q4 %s is not in %s" % (Q4_REPO, hub))
    lora = find_lightning([hub])
    if lora is not None:
        say("Lightning %s: %.2f GiB" % (lora, os.path.getsize(os.path.realpath(lora)) / 2 ** 30))
    else:
        say("Lightning %s is not in %s" % (EDIT_LORA_FILE, hub))
    ancestor = existing_ancestor(hub)
    say("free on %s: %.1f GiB" % (ancestor, free_gib(ancestor)))
    proc = subprocess.run([sys.executable, os.path.join(WS, "bin", "seed-edit"), "--probe"],
                          capture_output=True, text=True)
    try:
        qwen = json.loads(lib.last_line(proc.stdout))["qwen"]
        verdict = ("ok (%s)" % qwen["backend"]) if qwen["ok"] else ("unavailable: %s" % qwen["reason"])
    except (ValueError, KeyError, TypeError):
        verdict = "unavailable: bin/seed-edit --probe printed unparsable output"
    say("probe: Qwen-Image-Edit " + verdict)


def main(argv=None):
    """bin/seed-edit-setup (SG66-SG69). Returns the exit code."""
    argparse.ArgumentParser(prog="seed-edit-setup", description="Create ~/mflux-edit/.venv (mflux 0.24.0) "
                            "and download the q4 Qwen-Image-Edit-2511 weights and the Lightning LoRA "
                            "into the Z-Image hub.").parse_args(argv)
    if os.environ.get("SEED_EDIT_MFLUX_PYTHON"):
        return fail(2, "SEED_EDIT_MFLUX_PYTHON is set; unset it to set up the default venv at ~/mflux-edit/.venv")
    venv = os.path.expanduser(VENV)
    py = os.path.join(venv, "bin", "python")
    hub = lib.zimage_hub()
    venv_ok = venv_ready(py, venv)
    q4_ok = lib.model_check(Q4_REPO, hub)[0]
    lora_ok = find_lightning([hub]) is not None
    if venv_ok and q4_ok and lora_ok:
        say("nothing to do")
        report(venv, hub)
        return 0
    frees = [(free_gib(p), p) for p in (existing_ancestor(hub), existing_ancestor(os.path.dirname(venv)))]
    free, where = min(frees)
    if free < SETUP_MIN_FREE_GIB:
        return fail(2, "only %.1f GiB free on %s; seed-edit-setup needs at least %g GiB (q4 weights ~29 GB, "
                       "Lightning LoRA ~0.85 GB, mflux venv)" % (free, where, SETUP_MIN_FREE_GIB))
    base = os.environ.get("SEED_EDIT_SETUP_PYTHON") or DEFAULT_BASE_PYTHON
    if not os.access(base, os.X_OK):
        return fail(2, "base python %s is not executable (set SEED_EDIT_SETUP_PYTHON)" % base)
    proc = subprocess.run([base, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                          capture_output=True, text=True)
    version = proc.stdout.strip()
    match = re.fullmatch(r"(\d+)\.(\d+)", version)
    if proc.returncode != 0 or not match or (int(match.group(1)), int(match.group(2))) < (3, 11):
        return fail(2, "base python %s is Python %s; mflux 0.24.0 needs 3.11 or newer" % (base, version or "?"))
    if not os.path.exists(py):
        code = subprocess.call([base, "-m", "venv", venv])
        if code != 0:
            return fail(1, "python -m venv exited %d" % code)
    if not venv_ready(py, venv):
        code = subprocess.call([py, "-m", "pip", "install", MFLUX_SPEC])
        if code != 0:
            return fail(1, "pip install mflux==0.24.0 exited %d" % code)
    if not (q4_ok and lora_ok):
        env = dict(os.environ, HF_HOME=os.path.dirname(hub), HF_HUB_OFFLINE="0", HF_XET_CHUNK_CACHE_SIZE_BYTES="0")
        code = subprocess.call([py, "-c", DOWNLOAD, hub, Q4_REPO, EDIT_LORA_REPO, EDIT_LORA_FILE], env=env)
        if code != 0:
            return fail(1, "the download exited %d" % code)
    report(venv, hub)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Then make it executable (never run it):

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
chmod 755 bin/seed-edit-setup && ls -l bin/seed-edit-setup | cut -c1-10    # expected: -rwxr-xr-x
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py 2>&1 | tail -1
```

Expected: `35 passed`. Run the compile check with `FILES` = `seed_edit_mflux_child.py bin/seed-edit-setup tests/test_seed_edit_tool.py`; expected: `compiled 3` twice. Then run the gate block with `N=4`. Expected: `GATE PASS`, `lost 0`, `new tests 74, not passing 0`, `baseline failures still failing 2 of 2`, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
git add seed_edit_mflux_child.py bin/seed-edit-setup tests/test_seed_edit_tool.py
git diff --cached --name-only    # expected: those 3 paths
git ls-files -s bin/seed-edit-setup | cut -c1-6    # expected: 100755
git commit -m "feat: seed_edit_mflux_child.py (mflux >= 0.22 gate, Qwen-Image-Edit-2511 q4 with the Lightning LoRA, guidance 1.0) and bin/seed-edit-setup (the ~/mflux-edit venv and the q4 + Lightning downloads, run only on the user's go) (SG24-SG27, SG66-SG69; SGT15, SGT16)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The server: the capability, six routes, Keep, Use and the summary key (SG3, SG38-SG53; SGT20-SGT32, Review Focus 1 and 2)

This task implements, in `movie_ui_server.py`:
- G6's import, `import movie_ui_seedgen as seedgen`, after `import movie_ui_seedfolder as seedfolder`.
- SG41 `SEEDS_LOCK` after `BATCH_LOCK`; SG40 `_RUN` after `_ID` and `_SAMPLE_RUN` after `_SAMPLE_ID`, and the six routes directly after `POST /api/uploads` (63 routes).
- SG38: the fourth capability in `MovieUIServer.__init__`, and `refresh_capabilities` calling `lib.seed_edit_check(self.probe_ws)` after the three probes and storing `seedgen.capability(...)` inside the same `cap_lock` block (Plan ruling PR4 names the pair `seed_models, seed_detail`). `capability_snapshot` is unchanged.
- SG46: `job_summary`'s 16th key `seed_run`.
- SG53: `store_upload(state, data, ext)` directly above `_h_upload`, which keeps its type and magic checks and returns `201, store_upload(self.server.state, body, ext)`.
- A new section after the characters attach block (`MovieUIHandler.h_character_train = ...`): SG41 `seeds_root`, `runs_root`, `seed_free_gib`; SG42 `_seed_run`, `_candidates`, `_cand_file`; `_run_job` (plan name: the record's job ID when its directory exists); SG43 `run_state`, `run_view`; SG44 `_seed_source` (step 2) and `_h_seed_run_create` (Plan ruling PR3: a sent seed of 0 is kept); SG47 `_h_seed_runs`; SG48 `_h_seed_run`; SG50/SG51 `_candidate_number`, `_ok_candidate`, `_h_seed_keep`; SG52 `_h_seed_use`; SG49 `_h_seed_folders`; and the `MovieUIHandler.h_seed_* = _h_seed_*` block.
- SG3 and SG45 need no code of their own: nothing but uploads is written under STATE, and every 400/409 is raised before step 6 creates the run directory. SGT21, SGT22 and SGT29 pin them.

Tests: SGT20-SGT32 and Review Focus 1 and 2, appended to `tests/test_movie_ui_seedgen.py`, with the spec 9 `env` fixture (which also writes the `bin/seed-edit` stub with both models ok and replaces `srv.seed_free_gib` by a 100 GiB stub; Plan ruling PR23) and the helpers `_upload`, `_body`, `_create`, `make_run`, `set_status`, `seed_job`.

**Files:**
- Modify (at 2b19b59): `movie_ui_server.py`: the import `:33`, `BATCH_LOCK` `:37-38`, the ID patterns `:60-65`, `ROUTES` `:98`, `MovieUIServer.__init__` `:202-203`, `refresh_capabilities` `:210-218`, `job_summary` `:739`, `_h_upload` `:1118-1128`, the characters attach block's last line `:1585`; `tests/test_movie_ui_seedgen.py` (append after SGT19).
- Read only: `movie_ui_server.py`: `ApiError` `:134-139`, `resolve_ws` `:169-183`, `_handle`'s route loop `:393-399`, `job_summary` `:726-739`, `_character_job_locked` `:1431-1437`, `character_taken` `:1465-1476` (the `CHARACTER_LIBRARY_DIR` rule), `_inside` `:1922-1927`, `_json_in` `:1938-1946`, `_isfile_in` `:1949-1950`, `_h_files` `:2105-2175`; `movie_ui_lib.py`: `JOB_ID_RE` `:35`, `job_dir` `:120-121`, `read_queue` `:144-147`, `new_job_id` `:165-171`, `create_job` `:174-190`, `job_state` `:855-860`, `cancel_job` `:863-876`.

**Interfaces:**
- Consumes: Task 1's `seedgen.validate_run_request`, `valid_folder`, `FOLDER_MSG`, `new_run_id`, `keep_name`, `capability`, `availability_error`, `RUN_ID_RE`, `SOURCE_NAMES`, `IMAGE_EXTS`, `CANDIDATES_MAX`, `MIN_FREE_GIB`, `SEED_MAX`, `RUNS_MAX`; Task 2's `lib.seed_edit_check(ws_real)` and `lib.seed_edit_argv(fields, ws_real)`; existing `lib.create_job`, `lib.new_job_id`, `lib.write_json_atomic`, `lib.write_bytes_atomic`, `lib.job_state`, `lib.read_queue`, `lib.utc_now`, `job_summary`, `_inside`, `_json_in`, `_isfile_in`, `STORE_LOCK`.
- Produces, in `movie_ui_server` (Task 6's page consumes the bodies):
  - `ROUTES` (63), `SEEDS_LOCK`, `store_upload(state, data, ext) -> {"upload_id", "path", "bytes"}`, `seeds_root(ws_real)`, `runs_root(ws_real)`, `seed_free_gib(path)`, `run_state(server, record, queue)`, `run_view(server, ws_real, run, run_dir, record, queue)`;
  - `POST /api/seeds/runs` → 201 `{"run": view}`; 400/409 `{"error"}`; the view's keys: `run`, `dir`, `created`, `state`, `prompt`, `model`, `backend`, `strength`, `seed`, `size`, `source_size`, `source_origin`, `error`, `source`, `candidates` (`[{"n", "seed", "status", "seconds", "path"}]`), `job` (a job summary or null);
  - `GET /api/seeds/runs?ws=` → `{"runs": [{"run", "created", "state", "prompt", "model", "backend", "count", "ok", "thumbs"}]}`; `GET /api/seeds/runs/<run>?ws=` → the view; `POST .../keep` `{ws, n, folder}` → 201 `{"folder", "file", "path"}`; `POST .../use` `{ws, n}` → 201 `{"upload_id", "path", "bytes"}`; `GET /api/seeds/folders?ws=` → `{"root", "folders": [{"folder", "count", "path"}]}`;
  - the capability `seed_edit` `{"ok", "reason", "checked", "models"}` in `GET /api/host`; the summary key `seed_run`.

- [ ] **Step 1: Write the failing tests.**

Edit `tests/test_movie_ui_seedgen.py`: replace this text, which occurs exactly once:

```python
    monkeypatch.setattr(lib, "LIGHT_TIMEOUT", 1)
    stub_seed_edit(ws, OK_MODELS, sleep=2)
    assert lib.seed_edit_check(ws) == (None, "bin/seed-edit --probe timed out after 1 s")
```

with:

```python
    monkeypatch.setattr(lib, "LIGHT_TIMEOUT", 1)
    stub_seed_edit(ws, OK_MODELS, sleep=2)
    assert lib.seed_edit_check(ws) == (None, "bin/seed-edit --probe timed out after 1 s")


# --- The HTTP tests: fixture and helpers (spec 9 rules) -----------------------------------------------

TIME_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
VIEW_KEYS = {"run", "dir", "created", "state", "prompt", "model", "backend", "strength", "seed", "size",
             "source_size", "source_origin", "error", "source", "candidates", "job"}
RA, RB = "se-20261101-100000-000a", "se-20261101-100000-000b"


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "0")
    monkeypatch.delenv("CHARACTER_LIBRARY_DIR", raising=False)
    state = mt.set_home(monkeypatch, tmp_path)
    clean_env(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    stub_seed_edit(ws, OK_MODELS)
    monkeypatch.setattr(srv, "seed_free_gib", lambda path: 100.0)
    running = mt.Running(state)
    yield {"state": state, "ws": ws, "tmp": str(tmp_path), "srv": running, "mp": monkeypatch}
    running.close()
    mt.kill_everything(state)


def _upload(s, data=mt.PNG, ctype="image/png"):
    status, _h, payload = mt.api(s, "POST", "/api/uploads", raw=data, headers={"Content-Type": ctype})
    assert status == 201, payload
    return payload["upload_id"]


def _body(ws, source, **overrides):
    body = {"ws": ws, "source": source, "prompt": "make it night", "model": "zimage", "strength": 0.45,
            "candidates": 2, "seed": 7}
    body.update(overrides)
    return body


def _create(s, body):
    return mt.api(s, "POST", "/api/seeds/runs", body=body)


def _runs_root(ws):
    return os.path.join(ws, "generated", "seeds", "runs")


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _record(run_dir):
    return json.loads(_read(os.path.join(run_dir, "run.json")).decode("utf-8"))


def _nothing_created(env):
    return (not os.path.exists(os.path.join(env["ws"], "generated", "seeds")) and lib.read_queue(env["state"]) == []
            and os.listdir(os.path.join(env["state"], "jobs")) == [])


def make_run(ws, run, cands, state="done", job=None, prompt="make it night", files=None):
    """A hand-made run under <ws>/generated/seeds/runs: source.png, run.json with one candidate per
    status in cands, and cand_NN.png (mt.PNG + bytes([n])) for every ok candidate, or for the n in
    files when files is given. Returns the run directory."""
    run_dir = os.path.join(_runs_root(ws), run)
    os.makedirs(run_dir)
    with open(os.path.join(run_dir, "source.png"), "wb") as f:
        f.write(mt.PNG + b"source")
    record = {"schema": "seed-edit.run.v1", "run": run, "created": "2026-11-02T14:15:00Z", "state": state,
              "prompt": prompt, "model": "zimage", "backend": "zimage", "strength": 0.45, "seed": 7,
              "size": {"width": 1024, "height": 672}, "source_size": {"width": 1536, "height": 1024},
              "source": "source.png", "source_origin": None, "job": job, "error": None,
              "candidates": [{"n": i + 1, "seed": 8 + i, "status": st,
                              "seconds": 1.0 if st in ("ok", "blocked") else None} for i, st in enumerate(cands)]}
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as f:
        json.dump(record, f)
    for i, st in enumerate(cands):
        if (files is None and st == "ok") or (files is not None and i + 1 in files):
            with open(os.path.join(run_dir, "cand_%02d.png" % (i + 1)), "wb") as f:
                f.write(mt.PNG + bytes([i + 1]))
    return run_dir


def set_status(run_dir, n, status):
    record = _record(run_dir)
    record["candidates"][n - 1]["status"] = status
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as f:
        json.dump(record, f)


def seed_job(state, ws, run):
    """A queued seed-edit job naming run (as the server would create it)."""
    job_id = lib.new_job_id(state)
    lib.create_job(state, job_id, "seed-edit", ws, None, None, ["true"], {"run": run, "candidates": 1})
    return job_id


# --- SGT20 (SG40): the routes ------------------------------------------------------------------------

SEED_ROUTES = [
    ("POST", r"/api/seeds/runs", "h_seed_run_create", "/api/seeds/runs"),
    ("GET", r"/api/seeds/runs", "h_seed_runs", "/api/seeds/runs"),
    ("GET", r"/api/seeds/runs/(se-[0-9]{8}-[0-9]{6}-[0-9a-f]{4})", "h_seed_run", "/api/seeds/runs/" + RUN),
    ("POST", r"/api/seeds/runs/(se-[0-9]{8}-[0-9]{6}-[0-9a-f]{4})/keep", "h_seed_keep",
     "/api/seeds/runs/" + RUN + "/keep"),
    ("POST", r"/api/seeds/runs/(se-[0-9]{8}-[0-9]{6}-[0-9a-f]{4})/use", "h_seed_use", "/api/seeds/runs/" + RUN + "/use"),
    ("GET", r"/api/seeds/folders", "h_seed_folders", "/api/seeds/folders"),
]


def test_sgt20_the_routes(env):
    s = env["srv"]
    routes = list(srv.ROUTES)
    i = routes.index(("POST", r"/api/uploads", "h_upload", "/api/uploads"))
    assert routes[i + 1:i + 7] == SEED_ROUTES
    assert len(srv.ROUTES) == 63
    for method, regex, name, sample in SEED_ROUTES:
        assert re.fullmatch(regex, sample), sample
        assert getattr(srv.MovieUIHandler, name) is getattr(srv, "_" + name), name
        for token in (None, "wrong-token"):
            assert mt.api(s, method, sample, body={} if method == "POST" else None, token=token)[::2] == (
                401, {"error": "missing or invalid token"}), (sample, token)
    assert mt.api(s, "DELETE", "/api/seeds/runs")[::2] == (405, {"error": "method not allowed"})
    assert mt.api(s, "GET", "/api/seeds/runs/se-junk?ws=" + env["ws"])[::2] == (404, {"error": "not found"})


# --- SGT21 (SG33, SG44, SG45): every 400, and nothing created ------------------------------------------

def test_sgt21_bad_requests_get_400_and_create_nothing(env):
    s, ws, tmp = env["srv"], env["ws"], env["tmp"]
    up = _upload(s)
    good = _body(ws, {"upload_id": up})
    no_ws = dict(good)
    del no_ws["ws"]
    cases = [(no_ws, "missing ws"), (dict(good, ws="relative/ws"), "ws must be an absolute path"),
             (dict(good, ws=tmp), "not a harness workspace (no bin/ltx-movie): %s" % tmp)]
    cases += [(dict(body, ws=ws), message) for body, message in REQUEST_CASES if "\ud800" not in str(body["prompt"])]
    cases += [(_body(ws, {"upload_id": UP}), "source upload %s not found" % UP),
              (_body(ws, {"run": RUN, "n": 1}), "unknown source run %s" % RUN),
              (_body(ws, {"character": "kyra", "still": "char_01.png"}), "unknown character still kyra/char_01.png")]
    for body, message in cases:
        assert _create(s, body)[::2] == (400, {"error": message}), message
    assert _nothing_created(env)


# --- SGT22 (SG37, SG44, SG45): every 409, and nothing created ------------------------------------------

def test_sgt22_conflicts_get_409_and_create_nothing(env):
    s, ws = env["srv"], env["ws"]
    up = _upload(s)
    reason = "diffusers bf16: needs a host with at least 64 GiB of memory (this host has 48.0 GiB); mflux q4: x"
    stub_seed_edit(ws, dict(OK_MODELS, qwen={"ok": False, "reason": reason, "backend": None}))
    assert _create(s, _body(ws, {"upload_id": up}, model="qwen", strength=None))[::2] == (
        409, {"error": "Qwen-Image-Edit is unavailable: " + reason})
    stub_seed_edit(ws, dict(OK_MODELS, zimage={"ok": False, "reason": "torch not importable by /py", "backend": None}))
    assert _create(s, _body(ws, {"upload_id": up}))[::2] == (
        409, {"error": "Z-Image is unavailable: torch not importable by /py"})
    stub_seed_edit(ws, OK_MODELS, exit=1, stderr="Traceback\nboom\n")
    assert _create(s, _body(ws, {"upload_id": up}))[::2] == (
        409, {"error": "cannot check the seed models: bin/seed-edit --probe exited 1: boom"})
    stub_seed_edit(ws, OK_MODELS)
    asked = []
    env["mp"].setattr(srv, "seed_free_gib", lambda path: asked.append(path) or 1.0)
    generated = os.path.join(ws, "generated")
    assert _create(s, _body(ws, {"upload_id": up}))[::2] == (
        409, {"error": "less than 2 GiB free on the disk holding %s (1.0 GiB free)" % generated})
    assert asked == [generated]
    assert _nothing_created(env)


# --- SGT23 (SG44, SG46, SG53): queue a run from an upload ----------------------------------------------

def test_sgt23_queue_a_run_from_an_upload(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    up = _upload(s, mt.PNG + b"src")
    status, _h, data = _create(s, _body(ws, {"upload_id": up}))
    assert status == 201, data
    view = data["run"]
    run = view["run"]
    assert seedgen.RUN_ID_RE.fullmatch(run)
    run_dir = os.path.join(_runs_root(ws), run)
    assert _read(os.path.join(run_dir, "source.png")) == mt.PNG + b"src"
    record = _record(run_dir)
    job_id = record["job"]
    assert lib.JOB_ID_RE.fullmatch(job_id) and TIME_RE.fullmatch(record["created"])
    assert dict(record, created=None) == {
        "schema": "seed-edit.run.v1", "run": run, "created": None, "state": "queued", "prompt": "make it night",
        "model": "zimage", "backend": None, "strength": 0.45, "seed": 7, "size": None, "source_size": None,
        "source": "source.png", "source_origin": {"kind": "upload", "upload_id": up}, "job": job_id, "error": None,
        "candidates": [{"n": 1, "seed": 8, "status": "pending", "seconds": None},
                       {"n": 2, "seed": 9, "status": "pending", "seconds": None}]}
    job = lib.read_job(lib.job_dir(state, job_id))
    assert (job["kind"], job["story_id"], job["character"], job["vlm"]) == ("seed-edit", None, None, "forbidden")
    assert job["fields"] == {"ws": ws, "run": run, "source_file": "source.png", "prompt": "make it night",
                             "model": "zimage", "strength": 0.45, "candidates": 2, "seed": 7,
                             "source": {"kind": "upload", "upload_id": up}}
    assert job["argv"] == lib.seed_edit_argv(job["fields"], ws)
    assert lib.read_queue(state) == [job_id]
    assert set(view) == VIEW_KEYS
    assert (view["state"], view["dir"], view["source"]) == ("queued", run_dir, os.path.join(run_dir, "source.png"))
    assert view["candidates"] == [{"n": 1, "seed": 8, "status": "pending", "seconds": None, "path": None},
                                  {"n": 2, "seed": 9, "status": "pending", "seconds": None, "path": None}]
    assert (view["job"]["id"], view["job"]["seed_run"], view["job"]["queue_position"]) == (job_id, run, 1)
    status, _h, data = _create(s, _body(ws, {"upload_id": up}, seed=None, candidates=None, strength=None))
    assert status == 201, data
    seed = data["run"]["seed"]
    assert 0 <= seed <= 2147483647 and data["run"]["strength"] == 0.45
    assert [c["seed"] for c in data["run"]["candidates"]] == [seed + 1, seed + 2, seed + 3, seed + 4]
    status, _h, data = _create(s, _body(ws, {"upload_id": up}, seed=0, model="qwen", strength=None, candidates=1))
    assert status == 201, data
    assert (data["run"]["seed"], data["run"]["strength"]) == (0, None)
    argv = lib.read_job(lib.job_dir(state, data["run"]["job"]["id"]))["argv"]
    assert "--strength" not in argv and argv[argv.index("--seed") + 1] == "0"


# --- SGT24 (SG44): a candidate of a finished run as the source -----------------------------------------

def test_sgt24_a_candidate_as_the_source(env):
    s, ws = env["srv"], env["ws"]
    run_dir = make_run(ws, RA, ["ok", "ok"])
    status, _h, data = _create(s, _body(ws, {"run": RA, "n": 2}))
    assert status == 201, data
    assert _read(os.path.join(data["run"]["dir"], "source.png")) == _read(os.path.join(run_dir, "cand_02.png"))
    assert data["run"]["source_origin"] == {"kind": "run", "run": RA, "n": 2}
    set_status(run_dir, 2, "blocked")
    no_ok = (400, {"error": "source run %s has no ok candidate 2" % RA})
    assert _create(s, _body(ws, {"run": RA, "n": 2}))[::2] == no_ok
    set_status(run_dir, 2, "ok")
    os.remove(os.path.join(run_dir, "cand_02.png"))
    assert _create(s, _body(ws, {"run": RA, "n": 2}))[::2] == no_ok
    assert _create(s, _body(ws, {"run": RA, "n": 3}))[::2] == (400, {"error": "source run %s has no ok candidate 3" % RA})
    assert _create(s, _body(ws, {"run": RB, "n": 1}))[::2] == (400, {"error": "unknown source run %s" % RB})
    assert len(os.listdir(_runs_root(ws))) == 2


# --- SGT25 (SG44): a character still as the source -----------------------------------------------------

def test_sgt25_a_character_still_as_the_source(env):
    s, ws, tmp, mp = env["srv"], env["ws"], env["tmp"], env["mp"]
    library = os.path.join(tmp, "lib")
    stills = os.path.join(library, "kyra", "dataset", "stills")
    os.makedirs(stills)
    with open(os.path.join(stills, "char_05.png"), "wb") as f:
        f.write(mt.PNG + b"kyra5")
    with open(os.path.join(tmp, "outside.png"), "wb") as f:
        f.write(mt.PNG + b"outside")
    os.symlink(os.path.join(tmp, "outside.png"), os.path.join(stills, "char_06.png"))
    mp.setenv("CHARACTER_LIBRARY_DIR", library)
    status, _h, data = _create(s, _body(ws, {"character": "kyra", "still": "char_05.png"}))
    assert status == 201, data
    assert _read(data["run"]["source"]) == mt.PNG + b"kyra5"
    assert data["run"]["source_origin"] == {"kind": "character", "character": "kyra", "still": "char_05.png"}
    for still in ("char_07.png", "char_06.png", "char_5.png"):
        assert _create(s, _body(ws, {"character": "kyra", "still": still}))[::2] == (
            400, {"error": "unknown character still kyra/%s" % still})
    mp.delenv("CHARACTER_LIBRARY_DIR")
    assert _create(s, _body(ws, {"character": "kyra", "still": "char_05.png"}))[::2] == (
        400, {"error": "unknown character still kyra/char_05.png"})
    own = os.path.join(ws, "generated", "characters", "kyra", "dataset", "stills")
    os.makedirs(own)
    with open(os.path.join(own, "char_05.png"), "wb") as f:
        f.write(mt.PNG + b"own5")
    status, _h, data = _create(s, _body(ws, {"character": "kyra", "still": "char_05.png"}))
    assert status == 201 and _read(data["run"]["source"]) == mt.PNG + b"own5"


# --- SGT26 (SG43, SG47): the runs list ------------------------------------------------------------------

def test_sgt26_the_runs_list(env):
    s, ws, state, tmp = env["srv"], env["ws"], env["state"], env["tmp"]
    assert mt.api(s, "GET", "/api/seeds/runs?ws=" + ws)[::2] == (200, {"runs": []})
    r1, r2, r3 = ("se-20261101-100000-000%d" % i for i in (1, 2, 3))
    d1 = make_run(ws, r1, ["ok", "blocked", "ok"], files=[1])
    make_run(ws, r2, ["pending", "pending"], state="queued", job=seed_job(state, ws, r2), prompt="second")
    make_run(ws, r3, ["pending"], state="running", job="20261101-000000-dead", prompt="third")
    os.makedirs(os.path.join(_runs_root(ws), "junk"))
    os.makedirs(os.path.join(_runs_root(ws), "se-20261101-100000-0004"))
    outside = make_run(os.path.join(tmp, "elsewhere"), "se-20261101-100000-0005", ["ok"])
    os.symlink(outside, os.path.join(_runs_root(ws), "se-20261101-100000-0005"))
    status, _h, data = mt.api(s, "GET", "/api/seeds/runs?ws=" + ws)
    assert status == 200
    runs = data["runs"]
    assert [r["run"] for r in runs] == [r3, r2, r1]
    assert all(set(r) == {"run", "created", "state", "prompt", "model", "backend", "count", "ok", "thumbs"}
               for r in runs)
    assert [(r["state"], r["prompt"], r["count"], r["ok"], r["thumbs"]) for r in runs[:2]] == [
        ("unknown", "third", 1, 0, []), ("queued", "second", 2, 0, [])]
    assert runs[2] == {"run": r1, "created": "2026-11-02T14:15:00Z", "state": "done", "prompt": "make it night",
                       "model": "zimage", "backend": "zimage", "count": 3, "ok": 2,
                       "thumbs": [os.path.join(d1, "cand_01.png")]}
    for i in range(201):
        make_run(ws, "se-20261103-%06d-0000" % i, [])
    runs = mt.api(s, "GET", "/api/seeds/runs?ws=" + ws)[2]["runs"]
    assert len(runs) == 200
    assert (runs[0]["run"], runs[-1]["run"]) == ("se-20261103-000200-0000", "se-20261103-000001-0000")


# --- SGT27 (SG42, SG43, SG48): one run's view ----------------------------------------------------------

def test_sgt27_the_run_view(env):
    s, ws, state, tmp = env["srv"], env["ws"], env["state"], env["tmp"]
    run_dir = make_run(ws, RA, ["ok", "blocked", "ok", "failed"], files=[1])
    status, _h, view = mt.api(s, "GET", "/api/seeds/runs/%s?ws=%s" % (RA, ws))
    assert status == 200 and set(view) == VIEW_KEYS
    assert view == {
        "run": RA, "dir": run_dir, "created": "2026-11-02T14:15:00Z", "state": "done", "prompt": "make it night",
        "model": "zimage", "backend": "zimage", "strength": 0.45, "seed": 7, "size": {"width": 1024, "height": 672},
        "source_size": {"width": 1536, "height": 1024}, "source_origin": None, "error": None,
        "source": os.path.join(run_dir, "source.png"),
        "candidates": [{"n": 1, "seed": 8, "status": "ok", "seconds": 1.0, "path": os.path.join(run_dir, "cand_01.png")},
                       {"n": 2, "seed": 9, "status": "blocked", "seconds": 1.0, "path": None},
                       {"n": 3, "seed": 10, "status": "ok", "seconds": 1.0, "path": None},
                       {"n": 4, "seed": 11, "status": "failed", "seconds": None, "path": None}],
        "job": None}
    job_id = seed_job(state, ws, RB)
    make_run(ws, RB, ["pending"], state="queued", job=job_id)
    view = mt.api(s, "GET", "/api/seeds/runs/%s?ws=%s" % (RB, ws))[2]
    assert (view["state"], view["job"]["state"], view["job"]["seed_run"]) == ("queued", "queued", RB)
    assert lib.cancel_job(state, job_id) == "cancelled"
    view = mt.api(s, "GET", "/api/seeds/runs/%s?ws=%s" % (RB, ws))[2]
    assert (view["state"], view["job"]["id"], view["job"]["state"]) == ("cancelled", job_id, "cancelled")
    missing = "se-20261101-999999-ffff"
    assert mt.api(s, "GET", "/api/seeds/runs/%s?ws=%s" % (missing, ws))[::2] == (
        404, {"error": "unknown seed run %s" % missing})
    outside = make_run(os.path.join(tmp, "elsewhere"), missing, ["ok"])
    os.symlink(outside, os.path.join(_runs_root(ws), missing))
    assert mt.api(s, "GET", "/api/seeds/runs/%s?ws=%s" % (missing, ws))[::2] == (
        404, {"error": "unknown seed run %s" % missing})


# --- SGT28 (SG50, SG51): Keep ----------------------------------------------------------------------------

def test_sgt28_keep(env):
    s, ws, tmp = env["srv"], env["ws"], env["tmp"]
    run_dir = make_run(ws, RA, ["ok", "blocked"])
    path = "/api/seeds/runs/%s/keep" % RA
    seeds = os.path.join(ws, "generated", "seeds")
    heroes = os.path.join(seeds, "heroes")
    for name in (RA + "-01.png", RA + "-01-2.png", RA + "-01-3.png"):
        assert mt.api(s, "POST", path, body={"ws": ws, "n": 1, "folder": "heroes"})[::2] == (
            201, {"folder": "heroes", "file": name, "path": os.path.join(heroes, name)})
        assert _read(os.path.join(heroes, name)) == _read(os.path.join(run_dir, "cand_01.png"))
    assert mt.api(s, "POST", path, body={"ws": ws, "n": 2, "folder": "heroes"})[::2] == (
        409, {"error": "candidate 2 of %s is blocked; only an ok candidate can be kept" % RA})
    for folder in ("", "runs", "Runs", "a..b", "-x", ".x", "A" * 65, "a/b", 5, None):
        assert mt.api(s, "POST", path, body={"ws": ws, "n": 1, "folder": folder})[::2] == (
            400, {"error": seedgen.FOLDER_MSG}), folder
    outside = os.path.join(tmp, "outside-folder")
    os.makedirs(outside)
    os.symlink(outside, os.path.join(seeds, "out"))
    assert mt.api(s, "POST", path, body={"ws": ws, "n": 1, "folder": "out"})[::2] == (
        409, {"error": "folder out resolves outside %s" % seeds})
    assert os.listdir(outside) == []
    for n in (0, 3, "1", None, True):
        assert mt.api(s, "POST", path, body={"ws": ws, "n": n, "folder": "heroes"})[::2] == (
            400, {"error": "n must be a candidate number from 1 to 2"}), n
    os.remove(os.path.join(run_dir, "cand_01.png"))
    assert mt.api(s, "POST", path, body={"ws": ws, "n": 1, "folder": "heroes"})[::2] == (
        409, {"error": "candidate 1 of %s has no image file" % RA})
    assert mt.api(s, "POST", "/api/seeds/runs/%s/keep" % RB, body={"ws": ws, "n": 1, "folder": "heroes"})[::2] == (
        404, {"error": "unknown seed run %s" % RB})
    assert sorted(os.listdir(heroes)) == [RA + "-01-2.png", RA + "-01-3.png", RA + "-01.png"]


# --- SGT29 (SG52, SG53): Use in Compose ----------------------------------------------------------------

def test_sgt29_use_registers_the_candidate_as_an_upload(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    run_dir = make_run(ws, RA, ["ok", "blocked"])
    data = _read(os.path.join(run_dir, "cand_01.png"))
    upload_id = hashlib.sha256(data).hexdigest() + ".png"
    want = {"upload_id": upload_id, "path": os.path.join(state, "uploads", upload_id), "bytes": len(data)}
    path = "/api/seeds/runs/%s/use" % RA
    assert mt.api(s, "POST", path, body={"ws": ws, "n": 1})[::2] == (201, want)
    assert _read(want["path"]) == data
    assert mt.api(s, "POST", "/api/uploads", raw=data, headers={"Content-Type": "image/png"})[::2] == (201, want)
    assert mt.api(s, "POST", path, body={"ws": ws, "n": 2})[::2] == (
        409, {"error": "candidate 2 of %s is blocked; only an ok candidate can be used" % RA})
    assert mt.api(s, "POST", path, body={"ws": ws, "n": 3})[::2] == (
        400, {"error": "n must be a candidate number from 1 to 2"})
    assert mt.api(s, "POST", "/api/uploads", raw=b"GIF89a", headers={"Content-Type": "image/png"})[::2] == (
        400, {"error": "file content is not image/png"})
    status, _h, out = mt.api(s, "POST", "/api/uploads", raw=mt.WEBP, headers={"Content-Type": "image/webp"})
    assert (status, out["upload_id"], out["bytes"]) == (201, hashlib.sha256(mt.WEBP).hexdigest() + ".webp", len(mt.WEBP))


# --- SGT30 (SG49): the seed folders ----------------------------------------------------------------------

def test_sgt30_the_seed_folders(env):
    s, ws, tmp = env["srv"], env["ws"], env["tmp"]
    seeds = os.path.join(ws, "generated", "seeds")
    assert mt.api(s, "GET", "/api/seeds/folders?ws=" + ws)[::2] == (200, {"root": seeds, "folders": []})
    heroes = os.path.join(seeds, "heroes")
    os.makedirs(os.path.join(heroes, "sub.png"))
    for name in ("a.png", "b.PNG", "c.jpg", "notes.txt"):
        with open(os.path.join(heroes, name), "wb") as f:
            f.write(mt.PNG)
    for name in ("runs", "Zeta", "alpha", "a..b"):
        os.makedirs(os.path.join(seeds, name), exist_ok=True)
    with open(os.path.join(seeds, "loose.png"), "wb") as f:
        f.write(mt.PNG)
    os.makedirs(os.path.join(tmp, "outside-folder"))
    os.symlink(os.path.join(tmp, "outside-folder"), os.path.join(seeds, "linked"))
    assert mt.api(s, "GET", "/api/seeds/folders?ws=" + ws)[::2] == (200, {"root": seeds, "folders": [
        {"folder": "alpha", "count": 0, "path": os.path.join(seeds, "alpha")},
        {"folder": "heroes", "count": 3, "path": heroes},
        {"folder": "Zeta", "count": 0, "path": os.path.join(seeds, "Zeta")}]})


# --- SGT31 (SG36, SG38): the seed_edit capability --------------------------------------------------------

def test_sgt31_the_seed_edit_capability(env):
    s, ws, tmp = env["srv"], env["ws"], env["tmp"]
    server = s.server
    assert mt.api(s, "GET", "/api/host")[2]["capabilities"]["seed_edit"] == {
        "ok": None, "reason": "probing", "checked": None, "models": None}
    server.probe_ws = ws
    good_py = os.path.join(tmp, "good-python")
    with open(good_py, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(good_py, 0o755)
    server.stills_py = good_py
    env["mp"].setenv("LTX2_MLX_BIN", os.path.join(tmp, "missing-ltx"))
    caps = mt.api(s, "GET", "/api/host?refresh=1")[2]["capabilities"]
    checked = caps["seed_edit"]["checked"]
    assert TIME_RE.fullmatch(checked)
    assert caps["seed_edit"] == {"ok": True, "reason": None, "checked": checked, "models": OK_MODELS}
    assert all(set(caps[key]) == {"ok", "reason", "checked"} for key in ("render", "stills", "story_server"))
    none_ok = {"zimage": {"ok": False, "reason": "z", "backend": None},
               "qwen": {"ok": False, "reason": "q", "backend": None}}
    stub_seed_edit(ws, none_ok)
    caps = mt.api(s, "GET", "/api/host?refresh=1")[2]["capabilities"]
    assert dict(caps["seed_edit"], checked=None) == {"ok": False, "reason": "Z-Image: z; Qwen-Image-Edit: q",
                                                     "checked": None, "models": none_ok}
    stub_seed_edit(ws, OK_MODELS, exit=1, stderr="boom\n")
    caps = mt.api(s, "GET", "/api/host?refresh=1")[2]["capabilities"]
    assert dict(caps["seed_edit"], checked=None) == {"ok": False, "reason": "bin/seed-edit --probe exited 1: boom",
                                                     "checked": None, "models": None}


# --- SGT32 (SG46): the job summary key -------------------------------------------------------------------

def test_sgt32_the_job_summary_key(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    status, _h, data = _create(s, _body(ws, {"upload_id": _upload(s)}))
    assert status == 201, data
    mt.make_job(state, ["true"], ws)
    queued = mt.api(s, "GET", "/api/jobs")[2]["queued"]
    assert [(j["kind"], j["seed_run"]) for j in queued] == [("seed-edit", data["run"]["run"]), ("movie", None)]


# --- Review Focus 1: phone JPEGs and WebP files keep their extension end to end ----------------------------

def test_sg_review_focus_1_jpeg_and_webp_sources_keep_their_extension(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    for data, ctype, ext in ((mt.JPEG + b"phone", "image/jpeg", "jpg"), (mt.WEBP + b"web", "image/webp", "webp")):
        status, _h, out = _create(s, _body(ws, {"upload_id": _upload(s, data, ctype)}))
        assert status == 201, out
        view = out["run"]
        name = "source." + ext
        assert view["source"] == os.path.join(view["dir"], name)
        assert _read(view["source"]) == data
        assert _record(view["dir"])["source"] == name
        assert sorted(os.listdir(view["dir"])) == ["run.json", name]
        job = lib.read_job(lib.job_dir(state, view["job"]["id"]))
        assert job["fields"]["source_file"] == name
        assert job["argv"][job["argv"].index("--source") + 1] == view["source"]


# --- Review Focus 2: Keep clicked four times at once -------------------------------------------------------

def test_sg_review_focus_2_keep_clicked_four_times_at_once(env):
    s, ws = env["srv"], env["ws"]
    run_dir = make_run(ws, RA, ["ok"])
    results = []

    def keep():
        results.append(mt.api(s, "POST", "/api/seeds/runs/%s/keep" % RA, body={"ws": ws, "n": 1, "folder": "heroes"}))

    threads = [threading.Thread(target=keep) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert sorted(r[0] for r in results) == [201] * 4
    names = sorted(r[2]["file"] for r in results)
    assert names == sorted([RA + "-01.png"] + [RA + "-01-%d.png" % k for k in (2, 3, 4)])
    for r in results:
        assert _read(r[2]["path"]) == _read(os.path.join(run_dir, "cand_01.png"))
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedgen.py 2>&1 | tail -1
```

Expected: `39 passed, 15 errors` (every new test errors in the `env` fixture: `AttributeError: <module 'movie_ui_server' ...> has no attribute 'seed_free_gib'`; Plan ruling PR25).

- [ ] **Step 3: Implement.**

**3.1.** The import. Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
import movie_ui_seedfolder as seedfolder
```

with:

```python
import movie_ui_seedfolder as seedfolder
import movie_ui_seedgen as seedgen
```

**3.2.** The Keep lock (SG41). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
BATCH_LOCK = threading.Lock()   # batch forks BF2: batch.json read-modify-writes, submit planning;
                                # never held together with STORE_LOCK
```

with:

```python
BATCH_LOCK = threading.Lock()   # batch forks BF2: batch.json read-modify-writes, submit planning;
                                # never held together with STORE_LOCK
SEEDS_LOCK = threading.Lock()   # seed generator SG41: Keep's name choice and write; never held
                                # together with STORE_LOCK
```

**3.3.** The run ID pattern and sample (SG40). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
_ID = r"([0-9]{8}-[0-9]{6}-[0-9a-f]{4})"
_STORY = r"([A-Za-z0-9][A-Za-z0-9._-]{0,79})"
_NAME = r"([a-z][a-z0-9-]{1,23})"
_ACTION = r"([a-z][a-z0-9-]{1,31})"
_TRACE = r"([0-9a-f]{32})"
_SAMPLE_ID = "20261019-142233-a1b2"
```

with:

```python
_ID = r"([0-9]{8}-[0-9]{6}-[0-9a-f]{4})"
_RUN = r"(se-[0-9]{8}-[0-9]{6}-[0-9a-f]{4})"   # seed generator SG40
_STORY = r"([A-Za-z0-9][A-Za-z0-9._-]{0,79})"
_NAME = r"([a-z][a-z0-9-]{1,23})"
_ACTION = r"([a-z][a-z0-9-]{1,31})"
_TRACE = r"([0-9a-f]{32})"
_SAMPLE_ID = "20261019-142233-a1b2"
_SAMPLE_RUN = "se-20261102-141500-a1b2"
```

**3.4.** The routes (SG40). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    ("POST", r"/api/uploads", "h_upload", "/api/uploads"),
```

with:

```python
    ("POST", r"/api/uploads", "h_upload", "/api/uploads"),
    ("POST", r"/api/seeds/runs", "h_seed_run_create", "/api/seeds/runs"),
    ("GET", r"/api/seeds/runs", "h_seed_runs", "/api/seeds/runs"),
    ("GET", r"/api/seeds/runs/" + _RUN, "h_seed_run", "/api/seeds/runs/" + _SAMPLE_RUN),
    ("POST", r"/api/seeds/runs/" + _RUN + r"/keep", "h_seed_keep", "/api/seeds/runs/" + _SAMPLE_RUN + "/keep"),
    ("POST", r"/api/seeds/runs/" + _RUN + r"/use", "h_seed_use", "/api/seeds/runs/" + _SAMPLE_RUN + "/use"),
    ("GET", r"/api/seeds/folders", "h_seed_folders", "/api/seeds/folders"),
```

**3.5.** The fresh capability (SG38). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
        self.capabilities = dict((k, {"ok": None, "reason": "probing", "checked": None})
                                 for k in ("render", "stills", "story_server"))
```

with:

```python
        self.capabilities = dict((k, {"ok": None, "reason": "probing", "checked": None})
                                 for k in ("render", "stills", "story_server"))
        self.capabilities["seed_edit"] = {"ok": None, "reason": "probing", "checked": None, "models": None}
```

**3.6.** The capability refresh (SG38). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    def refresh_capabilities(self):
        """Re-run MU60's three probes against probe_ws and store the results."""
        results = {"render": lib.render_check(), "stills": lib.stills_check(self.probe_ws, self.stills_py),
                   "story_server": lib.story_server_check(self.probe_ws)}
        checked = lib.utc_now()
        with self.cap_lock:
            for key, (ok, detail) in results.items():
                reason = detail if (key == "story_server" or not ok) else None
                self.capabilities[key] = {"ok": ok, "reason": reason, "checked": checked}
```

with:

```python
    def refresh_capabilities(self):
        """Re-run MU60's three probes and the seed_edit probe (seed generator SG38) against probe_ws
        and store the results."""
        results = {"render": lib.render_check(), "stills": lib.stills_check(self.probe_ws, self.stills_py),
                   "story_server": lib.story_server_check(self.probe_ws)}
        seed_models, seed_detail = lib.seed_edit_check(self.probe_ws)
        checked = lib.utc_now()
        with self.cap_lock:
            for key, (ok, detail) in results.items():
                reason = detail if (key == "story_server" or not ok) else None
                self.capabilities[key] = {"ok": ok, "reason": reason, "checked": checked}
            self.capabilities["seed_edit"] = seedgen.capability(seed_models, seed_detail, checked)
```

**3.7.** The summary key (SG46). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
            "seed_folder": seedfolder.seed_tag(job.get("fields"))}
```

with:

```python
            "seed_folder": seedfolder.seed_tag(job.get("fields")),
            "seed_run": (job.get("fields") or {}).get("run") if job["kind"] == "seed-edit" else None}
```

**3.8.** `store_upload` (SG53). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
def _h_upload(self, groups, query, body):
    media = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    ext, magic = UPLOAD_TYPES[media]
    ok = (body[:4] == b"RIFF" and body[8:12] == b"WEBP") if magic is None else body.startswith(magic)
    if not ok:
        raise ApiError(400, "file content is not %s" % media)
    upload_id = "%s.%s" % (hashlib.sha256(body).hexdigest(), ext)
    path = os.path.join(self.server.state, "uploads", upload_id)
    if not os.path.isfile(path):
        lib.write_bytes_atomic(path, body)
    return 201, {"upload_id": upload_id, "path": path, "bytes": len(body)}
```

with:

```python
def store_upload(state, data, ext):
    """<state>/uploads/<sha256 hex>.<ext>, written once; returns {"upload_id", "path", "bytes"} (MU53,
    seed generator SG53)."""
    upload_id = "%s.%s" % (hashlib.sha256(data).hexdigest(), ext)
    path = os.path.join(state, "uploads", upload_id)
    if not os.path.isfile(path):
        lib.write_bytes_atomic(path, data)
    return {"upload_id": upload_id, "path": path, "bytes": len(data)}


def _h_upload(self, groups, query, body):
    media = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    ext, magic = UPLOAD_TYPES[media]
    ok = (body[:4] == b"RIFF" and body[8:12] == b"WEBP") if magic is None else body.startswith(magic)
    if not ok:
        raise ApiError(400, "file content is not %s" % media)
    return 201, store_upload(self.server.state, body, ext)
```

**3.9.** The seed generator section (SG41-SG52). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
MovieUIHandler.h_character_train = _h_character_train
```

with:

```python
MovieUIHandler.h_character_train = _h_character_train


# ---------------------------------------------------------------------------
# The seed generator (docs/superpowers/specs/2026-11-02-seed-generator-design.md, Section 5)
# ---------------------------------------------------------------------------

def seeds_root(ws_real):
    return os.path.join(ws_real, "generated", "seeds")


def runs_root(ws_real):
    return os.path.join(seeds_root(ws_real), "runs")


def seed_free_gib(path):
    return shutil.disk_usage(path).free / 2 ** 30


def _seed_run(ws_real, run):
    """SG42: (run_dir, record) of a run whose directory lies inside runs_root and whose run.json is
    a JSON object, else ApiError(404)."""
    root = runs_root(ws_real)
    run_dir = os.path.join(root, run)
    record = None
    if _inside(run_dir, root) and os.path.isdir(run_dir):
        record = _json_in(run_dir, os.path.join(run_dir, "run.json"))
    if not isinstance(record, dict):
        raise ApiError(404, "unknown seed run %s" % run)
    return run_dir, record


def _candidates(record):
    """SG42: the candidate entries of a record with an int n from 1 to 4, in order."""
    cands = record.get("candidates")
    if not isinstance(cands, list):
        return []
    return [c for c in cands if isinstance(c, dict) and lib._is_int(c.get("n"))
            and 1 <= c["n"] <= seedgen.CANDIDATES_MAX]


def _cand_file(run_dir, entry):
    """SG42: <run_dir>/cand_NN.png of an ok entry when that file exists inside run_dir, else None."""
    path = os.path.join(run_dir, "cand_%02d.png" % entry["n"])
    return path if entry.get("status") == "ok" and _isfile_in(run_dir, path) else None


def _run_job(server, record):
    """The record's job ID when it names an existing job directory, else None."""
    job_id = record.get("job")
    if isinstance(job_id, str) and lib.JOB_ID_RE.fullmatch(job_id) and os.path.isdir(lib.job_dir(server.state, job_id)):
        return job_id
    return None


def run_state(server, record, queue):
    """SG43: the tool's final state, else the job's state, else "unknown"."""
    if record.get("state") in ("done", "failed", "cancelled"):
        return record["state"]
    job_id = _run_job(server, record)
    return lib.job_state(server.state, job_id, queue) if job_id is not None else "unknown"


def run_view(server, ws_real, run, run_dir, record, queue):
    """SG43: the run as the page shows it."""
    source = record.get("source")
    source_path = os.path.join(run_dir, source) if source in seedgen.SOURCE_NAMES else None
    if source_path is not None and not _isfile_in(run_dir, source_path):
        source_path = None
    job_id = _run_job(server, record)
    view = {"run": run, "dir": run_dir, "created": record.get("created"), "state": run_state(server, record, queue)}
    for key in ("prompt", "model", "backend", "strength", "seed", "size", "source_size", "source_origin", "error"):
        view[key] = record.get(key)
    view["source"] = source_path
    view["candidates"] = [{"n": c["n"], "seed": c.get("seed"), "status": c.get("status"),
                           "seconds": c.get("seconds"), "path": _cand_file(run_dir, c)} for c in _candidates(record)]
    view["job"] = job_summary(server, job_id, queue) if job_id is not None else None
    return view


def _seed_source(server, real, source):
    """SG44 step 2: (source file, extension) of a validated source, else ApiError(400)."""
    if source["kind"] == "upload":
        path = os.path.join(server.state, "uploads", source["upload_id"])
        if not os.path.isfile(path):
            raise ApiError(400, "source upload %s not found" % source["upload_id"])
        return path, source["upload_id"].rsplit(".", 1)[1]
    if source["kind"] == "run":
        try:
            run_dir, record = _seed_run(real, source["run"])
        except ApiError:
            raise ApiError(400, "unknown source run %s" % source["run"])
        entries = [c for c in _candidates(record) if c["n"] == source["n"]]
        path = _cand_file(run_dir, entries[0]) if entries else None
        if path is None:
            raise ApiError(400, "source run %s has no ok candidate %s" % (source["run"], source["n"]))
        return path, "png"
    library = os.environ.get("CHARACTER_LIBRARY_DIR") or os.path.join(real, "generated", "characters")
    path = os.path.join(library, source["character"], "dataset", "stills", source["still"])
    if not _isfile_in(library, path):
        raise ApiError(400, "unknown character still %s/%s" % (source["character"], source["still"]))
    return path, "png"


def _h_seed_run_create(self, groups, query, body):
    """SG44: validate, check the source, the models and the disk, then create the run directory and
    queue its seed-edit job."""
    server = self.server
    real = self.ws(body.get("ws"))
    clean, error = seedgen.validate_run_request(body)
    if error is not None:
        raise ApiError(400, error)
    source, ext = _seed_source(server, real, clean["source"])
    models, detail = lib.seed_edit_check(real)
    error = seedgen.availability_error(models, detail, clean["model"])
    if error is not None:
        raise ApiError(409, error)
    generated = os.path.join(real, "generated")
    where = generated if os.path.isdir(generated) else real
    free = seed_free_gib(where)
    if free < seedgen.MIN_FREE_GIB:
        raise ApiError(409, "less than 2 GiB free on the disk holding %s (%.1f GiB free)" % (where, free))
    seed = clean["seed"] if clean["seed"] is not None else secrets.randbelow(seedgen.SEED_MAX + 1)
    root = runs_root(real)
    os.makedirs(root, exist_ok=True)
    while True:
        run = seedgen.new_run_id()
        try:
            os.mkdir(os.path.join(root, run))
            break
        except FileExistsError:
            continue
    run_dir = os.path.join(root, run)
    source_file = "source." + ext
    shutil.copyfile(source, os.path.join(run_dir, source_file))
    origin = clean["source"]
    with STORE_LOCK:
        job_id = lib.new_job_id(server.state)
        record = {"schema": "seed-edit.run.v1", "run": run, "created": lib.utc_now(), "state": "queued",
                  "prompt": clean["prompt"], "model": clean["model"], "backend": None,
                  "strength": clean["strength"], "seed": seed, "size": None, "source_size": None,
                  "source": source_file, "source_origin": origin, "job": job_id, "error": None,
                  "candidates": [{"n": i, "seed": seed + i, "status": "pending", "seconds": None}
                                 for i in range(1, clean["candidates"] + 1)]}
        lib.write_json_atomic(os.path.join(run_dir, "run.json"), record)
        fields = {"ws": real, "run": run, "source_file": source_file, "prompt": clean["prompt"],
                  "model": clean["model"], "strength": clean["strength"], "candidates": clean["candidates"],
                  "seed": seed, "source": origin}
        lib.create_job(server.state, job_id, "seed-edit", real, None, None, lib.seed_edit_argv(fields, real), fields)
    return 201, {"run": run_view(server, real, run, run_dir, record, lib.read_queue(server.state))}


def _h_seed_runs(self, groups, query, body):
    """SG47: the newest RUNS_MAX readable runs."""
    real = self.ws(query.get("ws"))
    try:
        names = sorted((n for n in os.listdir(runs_root(real)) if seedgen.RUN_ID_RE.fullmatch(n)), reverse=True)
    except OSError:
        names = []
    queue = lib.read_queue(self.server.state)
    runs = []
    for name in names:
        if len(runs) >= seedgen.RUNS_MAX:
            break
        try:
            run_dir, record = _seed_run(real, name)
        except ApiError:
            continue
        cands = [(c, _cand_file(run_dir, c)) for c in _candidates(record)]
        runs.append({"run": name, "created": record.get("created"), "state": run_state(self.server, record, queue),
                     "prompt": record.get("prompt"), "model": record.get("model"), "backend": record.get("backend"),
                     "count": len(cands), "ok": sum(1 for c, _path in cands if c.get("status") == "ok"),
                     "thumbs": [path for _c, path in cands if path is not None]})
    return 200, {"runs": runs}


def _h_seed_run(self, groups, query, body):
    """SG48: one run's view."""
    real = self.ws(query.get("ws"))
    run_dir, record = _seed_run(real, groups[0])
    return 200, run_view(self.server, real, groups[0], run_dir, record, lib.read_queue(self.server.state))


def _candidate_number(entries, n):
    """SG50, SG52: ApiError(400) unless n is a candidate number of entries."""
    if not (lib._is_int(n) and 1 <= n <= len(entries)):
        raise ApiError(400, "n must be a candidate number from 1 to %d" % len(entries))


def _ok_candidate(run_dir, entries, run, n, verb):
    """SG50, SG52: the image file of candidate n when it is ok, else ApiError(409)."""
    entry = None
    for c in entries:
        if c["n"] == n:
            entry = c
            break
    status = entry.get("status") if entry is not None else "missing"
    if status != "ok":
        raise ApiError(409, "candidate %s of %s is %s; only an ok candidate can be %s" % (n, run, status, verb))
    path = _cand_file(run_dir, entry)
    if path is None:
        raise ApiError(409, "candidate %s of %s has no image file" % (n, run))
    return path


def _h_seed_keep(self, groups, query, body):
    """SG50, SG51: copy an ok candidate into a seed folder under the first free name."""
    real, run = self.ws(body.get("ws")), groups[0]
    run_dir, record = _seed_run(real, run)
    entries = _candidates(record)
    n, folder = body.get("n"), body.get("folder")
    _candidate_number(entries, n)
    if not seedgen.valid_folder(folder):
        raise ApiError(400, seedgen.FOLDER_MSG)
    with open(_ok_candidate(run_dir, entries, run, n, "kept"), "rb") as f:
        data = f.read()
    root = seeds_root(real)
    folder_dir = os.path.join(root, folder)
    with SEEDS_LOCK:
        os.makedirs(folder_dir, exist_ok=True)
        if not _inside(folder_dir, root):
            raise ApiError(409, "folder %s resolves outside %s" % (folder, root))
        k = 1
        while True:
            dest = os.path.join(folder_dir, seedgen.keep_name(run, n, k))
            try:
                fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
                break
            except FileExistsError:
                k += 1
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        except BaseException:
            try:
                os.unlink(dest)
            except OSError:
                pass
            raise
    return 201, {"folder": folder, "file": os.path.basename(dest), "path": dest}


def _h_seed_use(self, groups, query, body):
    """SG52: register an ok candidate as an upload, exactly as POST /api/uploads would."""
    real, run = self.ws(body.get("ws")), groups[0]
    run_dir, record = _seed_run(real, run)
    entries = _candidates(record)
    _candidate_number(entries, body.get("n"))
    with open(_ok_candidate(run_dir, entries, run, body["n"], "used"), "rb") as f:
        data = f.read()
    return 201, store_upload(self.server.state, data, "png")


def _h_seed_folders(self, groups, query, body):
    """SG49: the seed folders with their image counts."""
    real = self.ws(query.get("ws"))
    root = seeds_root(real)
    try:
        names = os.listdir(root)
    except OSError:
        names = []
    folders = []
    for name in sorted(names, key=lambda n: n.lower()):
        path = os.path.join(root, name)
        if not (seedgen.valid_folder(name) and os.path.isdir(path) and _inside(path, root)):
            continue
        try:
            count = sum(1 for n in os.listdir(path) if os.path.splitext(n)[1].lower() in seedgen.IMAGE_EXTS
                        and os.path.isfile(os.path.join(path, n)))
        except OSError:
            count = 0
        folders.append({"folder": name, "count": count, "path": path})
    return 200, {"root": root, "folders": folders}


MovieUIHandler.h_seed_run_create = _h_seed_run_create
MovieUIHandler.h_seed_runs = _h_seed_runs
MovieUIHandler.h_seed_run = _h_seed_run
MovieUIHandler.h_seed_keep = _h_seed_keep
MovieUIHandler.h_seed_use = _h_seed_use
MovieUIHandler.h_seed_folders = _h_seed_folders
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedgen.py 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_seedfolder.py 2>&1 | tail -1
```

Expected: `54 passed`, then `6 failed, 174 passed` (the six are this task's `R63` and `KEYS` lines: `test_mut18`, `test_lu1`, `test_sdt11`, `test_sdt29`, `test_mut2`, `test_sdt19`). Run the compile check with `FILES` = `movie_ui_server.py tests/test_movie_ui_seedgen.py`; expected: `compiled 2` twice. Then run the gate block with `N=5`. Expected: `GATE PASS`, `lost 8 (listed 8, unexpected 0)` (the eight `T5` lines), `new tests 89, not passing 0`, `baseline failures still failing 2 of 2`, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
git add movie_ui_server.py tests/test_movie_ui_seedgen.py
git diff --cached --name-only    # expected: those 2 paths
git commit -m "feat(movie-ui): the seed generator routes: POST/GET /api/seeds/runs, the run view, Keep (O_EXCL under SEEDS_LOCK), Use (store_upload, the same content-hash ID), the seed folders, the seed_edit capability and the seed_run job key (SG3, SG38-SG53; SGT20-SGT32)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The page: the Seeds tab, the Characters button and the Jobs text (SG54-SG65; SGT33, Review Focus 5)

This task implements, in `index.html`, `app.js` and `app.css`:
- SG54: the `tab-seeds` button directly after `tab-compose`; the `TABS` line; `showTab`'s two lines directly after its `stopBatchPoll` line.
- SG55: the panel directly after `panel-compose`'s `</section>`, the spec's HTML (dedented two spaces).
- Spec 1.1's seven `SEED_*` constants directly after `SEED_COLLATOR`; SG56's `S.seeds` directly after `part`.
- SG57-SG63: the 21 functions, each defined once, in a new section directly before `// --- characters (MU82)`. Plan rulings PR5 (Generate's button refresh after `busy`), PR18 (one `"unavailable — "` literal) and PR19 (the page details) apply.
- SG59: `renderBadges` calls `updateSeedButtons()` after `updateLocationButtons()`; SG64: `openCharacter`'s stills line, `jobLabel`, `renderProgress`'s generic branch, `stopPolling`'s added line, `selectWorkspace`'s `resetSeeds();`, `start`'s `setupSeeds();`.
- SG65: the six CSS rules, appended.

Tests: SGT33 and Review Focus 5, appended to `tests/test_movie_ui_seedgen.py`.

**Files:**
- Modify (at 2b19b59): `static/movie-ui/index.html`: the nav `:33`, the end of `panel-compose` `:154-157`; `static/movie-ui/app.js`: `SEED_COLLATOR` `:13`, `part` `:33`, `stopPolling` `:88-90`, `renderBadges` `:232-235`, `selectWorkspace` `:284-285`, `TABS` `:307`, `showTab` `:314`, the characters header `:1743`, `openCharacter`'s stills line `:1778`, `jobLabel` `:2233`, `renderProgress` `:2273-2276`, `start` `:2661-2662`; `static/movie-ui/app.css`: the last line `:100`; `tests/test_movie_ui_seedgen.py` (append after Review Focus 2).
- Read only: `app.js`: `el` `:39-51`, `clear` `:53`, `show` `:55`, `enc` `:57`, `fileUrl` `:75-77`, `api` `:94-121`, `wsQuery` `:153`, `capability` `:210-213`, `uploadFile` `:524-529`, `updateComposeButtons` `:500-522`, `preview` `:433`, `button` `:2296-2300`, `pollJobs` `:2331-2343`.

**Interfaces:**
- Consumes: Task 5's routes and bodies (the run view, the runs list, Keep, Use, the folders list, the `seed_edit` capability, the summary's `seed_run`), Task 2's `progress.candidates`; existing `el`, `button`, `clear`, `show`, `enc`, `fileUrl`, `api`, `wsQuery`, `capability`, `uploadFile`, `showTab`, `updateComposeButtons`, `preview`, `pollJobs`, `S.host.state_dir`, `S.seedUpload`.
- Produces: the HTML IDs of SG55 and `tab-seeds`; `S.seeds`; the 21 SG57 functions; `S.timers.seeds`.

- [ ] **Step 1: Write the failing tests.**

Edit `tests/test_movie_ui_seedgen.py`: replace this text, which occurs exactly once:

```python
    for r in results:
        assert _read(r[2]["path"]) == _read(os.path.join(run_dir, "cand_01.png"))
```

with:

```python
    for r in results:
        assert _read(r[2]["path"]) == _read(os.path.join(run_dir, "cand_01.png"))


# --- SGT33 (SG54-SG65): the static page ----------------------------------------------------------------

PAGE_IDS = ("tab-seeds", "panel-seeds", "se-file", "se-source-status", "se-source-img", "se-source-size", "se-prompt",
            "se-prompt-count", "se-model", "se-model-note", "se-strength-box", "se-strength", "se-candidates",
            "se-seed", "se-generate", "se-generate-reason", "se-run-title", "se-run-status", "se-folder-options",
            "se-grid", "se-runs", "se-folders")
JS_TEXTS = ('"/api/seeds/runs"', '"/api/seeds/folders"', '"/keep"', '"/use"', '"New seed from this"',
            '"Use in Compose"', '"Edit again"', '"Copy path"', '"blocked by content safety"', '"unavailable — "',
            '"selected — press Cmd+C"', '"seed run "', "navigator.clipboard", "S.timers.seeds",
            'const TABS = ["compose", "seeds", "stories", "batches", "characters", "locations", "actions", "loras", '
            '"jobs", "traces"];',
            '["jobs", "log", "host", "batch"]',
            "await Promise.all([loadCatalog(), loadCharacters(), loadLocations(), loadActions(), loadStories(), "
            "loadModels()]);",
            "    resetSeeds();\n    await loadOptions();\n", "    setupCompose();\n    setupSeeds();\n",
            "    updateLocationButtons();\n    updateSeedButtons();\n  }\n",
            '    if (name !== "seeds") { stopSeedPoll(); }\n    if (name === "seeds") { loadSeeds(); }\n',
            "    });\n    if (S.timers.seeds) { clearInterval(S.timers.seeds); S.timers.seeds = null; }\n"
            "    if (S.timers.traces) {",
            'return job.story_id || job.character || (job.seed_run ? "seed run " + job.seed_run : "") || '
            '(job.kind === "smoke" ? "smoke render" : "-");',
            'gallery.appendChild(el("figure", {cls: "se-still"}, [el("img", {src: fileUrl(p), alt: p}), '
            'button("New seed from this", function () { seedFromStill(name, p); })]));')
SEED_FUNCTIONS = ("seedCanvas", "setSeedSource", "onSeedSourceFile", "updateSeedButtons", "seedBody", "generateSeeds",
                  "openSeedRun", "pollSeedRun", "renderSeedRun", "seedRow", "keepSeed", "useSeed", "editSeedAgain",
                  "loadSeeds", "loadSeedRuns", "loadSeedFolders", "copySeedPath", "seedFromStill", "stopSeedPoll",
                  "resetSeeds", "setupSeeds")
CSS_RULES = (".se-grid { display: flex; flex-direction: column; gap: 12px; }",
             ".se-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: flex-start; }",
             ".se-img, .se-thumb { width: 320px; height: auto; border: 1px solid var(--line); }",
             ".se-actions { display: flex; flex-direction: column; gap: 4px; }",
             ".se-mini { width: 64px; height: auto; margin-right: 4px; }",
             ".gallery figure { margin: 0; display: flex; flex-direction: column; gap: 4px; }")


def _static_texts():
    static = os.path.join(WS, "static", "movie-ui")
    texts = {}
    for name in ("index.html", "app.js", "app.css"):
        with open(os.path.join(static, name), encoding="utf-8") as f:
            texts[name] = f.read()
    return static, texts


def test_sgt33_the_static_page():
    static, texts = _static_texts()
    html, js, css = texts["index.html"], texts["app.js"], texts["app.css"]
    for element in PAGE_IDS:
        assert html.count('id="%s"' % element) == 1, element
    assert html.index('id="tab-compose"') < html.index('id="tab-seeds"') < html.index('id="tab-stories"')
    assert html.index('id="panel-compose"') < html.index('id="panel-seeds"') < html.index('id="panel-stories"')
    assert '<img id="se-source-img" class="se-thumb" alt="source image" hidden>' in html
    assert '<option value="4" selected>4</option>' in html and 'placeholder="blank = random"' in html
    for text in JS_TEXTS:
        assert text in js, text
    for name in SEED_FUNCTIONS:
        assert js.count("function %s(" % name) == 1, name
    for rule in CSS_RULES:
        assert rule in css, rule
    for name, text in texts.items():
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\balert\(", r"\bconfirm\(", r"\bprompt\(",
                        r"\beval\(", r"new Function"):
            assert not re.search(pattern, text), (name, pattern)
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")], capture_output=True, text=True,
                              timeout=60)
        assert proc.returncode == 0, proc.stderr


# --- Review Focus 5: the page's canvas size matches the tool's ----------------------------------------------

CANVAS_CASES = [(1536, 1024), (1024, 1024), (800, 600), (4000, 3000), (3000, 4000), (720, 1280), (1023, 1023),
                (100, 70), (100, 60), (64, 64), (63, 100), (1025, 1), (2000, 1999), (1, 5000), (4032, 3024),
                (3024, 4032), (1080, 1920), (1920, 1080), (5000, 5000), (17, 17), (1040, 1040), (1041, 300),
                (8192, 64), (64, 8192), (1366, 768), (2048, 1365)]


def test_sg_review_focus_5_the_page_canvas_matches_the_tool(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader("seed_edit_tool", os.path.join(WS, "bin", "seed-edit"))
    spec = importlib.util.spec_from_loader("seed_edit_tool", loader)
    tool = importlib.util.module_from_spec(spec)
    loader.exec_module(tool)
    with open(os.path.join(WS, "static", "movie-ui", "app.js"), encoding="utf-8") as f:
        js = f.read()
    start = js.index("  function seedCanvas(w, h) {")
    end = js.index("\n  }\n", start) + len("\n  }\n")
    script = js[start:end] + "const SEED_LONG_EDGE = 1024;\nprocess.stdout.write(JSON.stringify(%s.map(function (c) { " \
        "return seedCanvas(c[0], c[1]); })));\n" % json.dumps(CANVAS_CASES)
    path = os.path.join(str(tmp_path), "canvas.js")
    with open(path, "w", encoding="utf-8") as f:
        f.write(script)
    proc = subprocess.run([node, path], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    for (w0, h0), got in zip(CANVAS_CASES, json.loads(proc.stdout)):
        try:
            want = dict(zip(("width", "height"), tool.canvas(w0, h0)))
        except tool.Refusal as e:
            found = re.search(r"gives a ([0-9]+)x([0-9]+) canvas", str(e))
            want = {"width": int(found.group(1)), "height": int(found.group(2))}
            assert min(got["width"], got["height"]) < 64, (w0, h0, got)
        assert got == want, (w0, h0)
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedgen.py 2>&1 | tail -1
```

Expected: `2 failed, 54 passed` (SGT33: `AssertionError: tab-seeds`; Review Focus 5: `ValueError: substring not found`).

- [ ] **Step 3: Implement.**

**3.1.** The tab (SG54). Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
  <button id="tab-compose" type="button" class="tab active">Compose</button>
```

with:

```html
  <button id="tab-compose" type="button" class="tab active">Compose</button>
  <button id="tab-seeds" type="button" class="tab">Seeds</button>
```

**3.2.** The panel (SG55). Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
      <button id="c-folder-cancel" type="button">Cancel</button>
    </div>
  </div>
</section>
```

with:

```html
      <button id="c-folder-cancel" type="button">Cancel</button>
    </div>
  </div>
</section>

<section id="panel-seeds" class="panel" hidden>
  <h3>Source</h3>
  <div class="row">
    <label>Upload <input id="se-file" type="file" accept="image/png,image/jpeg,image/webp"></label>
    <span id="se-source-status" class="muted"></span>
  </div>
  <div class="row">
    <img id="se-source-img" class="se-thumb" alt="source image" hidden>
    <span id="se-source-size" class="muted"></span>
  </div>
  <div class="grid">
    <label class="wide">Prompt <textarea id="se-prompt" rows="3" maxlength="2000"></textarea></label>
    <span id="se-prompt-count" class="muted">0 / 2000 characters</span>
    <label>Model <select id="se-model">
        <option value="zimage">Z-Image (img2img)</option>
        <option value="qwen">Qwen-Image-Edit</option>
      </select></label>
    <span id="se-model-note" class="muted"></span>
    <label id="se-strength-box">Strength <input id="se-strength" type="number" min="0.10" max="0.90" step="0.05" value="0.45">
      <span class="muted">lower keeps more of the source</span></label>
    <label>Candidates <select id="se-candidates"><option value="1">1</option><option value="2">2</option><option value="3">3</option><option value="4" selected>4</option></select></label>
    <label>Seed <input id="se-seed" type="number" min="0" max="2147483647" step="1" placeholder="blank = random"></label>
  </div>
  <div class="row"><button id="se-generate" type="button">Generate</button> <span id="se-generate-reason" class="muted"></span></div>
  <h3 id="se-run-title"></h3>
  <p id="se-run-status" class="muted"></p>
  <datalist id="se-folder-options"></datalist>
  <div id="se-grid" class="se-grid"></div>
  <h3>Runs</h3>
  <table id="se-runs" class="list"><thead><tr><th>Run</th><th>Prompt</th><th>Model</th><th>State</th><th>Candidates</th></tr></thead><tbody></tbody></table>
  <h3>Seed folders</h3>
  <p class="muted">Kept seeds land in these folders; pick one in Compose → Seed folder.</p>
  <table id="se-folders" class="list"><thead><tr><th>Folder</th><th>Images</th><th>Path</th><th></th></tr></thead><tbody></tbody></table>
</section>
```

**3.3.** The constants (spec 1.1). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
  const SEED_COLLATOR = new Intl.Collator("en", {numeric: true});
```

with:

```javascript
  const SEED_COLLATOR = new Intl.Collator("en", {numeric: true});
  // Seed generator spec 1.1: the Seeds tab.
  const SEED_LONG_EDGE = 1024;
  const SEED_MIN_SIDE = 64;
  const SEED_PROMPT_MAX = 2000;
  const SEED_POLL_MS = 2000;
  const SEED_ACTIVE = ["queued", "starting", "running"];
  const SEED_MODEL_LABELS = {zimage: "Z-Image", qwen: "Qwen-Image-Edit"};
  const SEED_BACKEND_LABELS = {"zimage": "Z-Image img2img", "mflux-q4": "mflux q4", "diffusers-bf16": "diffusers bf16"};
```

**3.4.** The state (SG56). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
  function part(box, name) { return $("#" + box.ids + "-" + name); }
```

with:

```javascript
  function part(box, name) { return $("#" + box.ids + "-" + name); }
  // Seed generator spec SG56: the Seeds tab's state.
  S.seeds = {source: null, natural: null, run: null, view: null, rows: {}, busy: false};
```

**3.5.** `stopPolling` (SG64). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
    ["jobs", "log", "host", "batch"].forEach(function (name) {
      if (S.timers[name]) { clearInterval(S.timers[name]); S.timers[name] = null; }
    });
```

with:

```javascript
    ["jobs", "log", "host", "batch"].forEach(function (name) {
      if (S.timers[name]) { clearInterval(S.timers[name]); S.timers[name] = null; }
    });
    if (S.timers.seeds) { clearInterval(S.timers.seeds); S.timers.seeds = null; }
```

**3.6.** `renderBadges` (SG59). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
    updateComposeButtons();
    updateCharacterButtons();
    updateLocationButtons();
  }
```

with:

```javascript
    updateComposeButtons();
    updateCharacterButtons();
    updateLocationButtons();
    updateSeedButtons();
  }
```

**3.7.** `selectWorkspace` (SG64). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
    closeFolderConfirm(FOLDER_BOXES.characters);
    await loadOptions();
```

with:

```javascript
    closeFolderConfirm(FOLDER_BOXES.characters);
    resetSeeds();
    await loadOptions();
```

**3.8.** `TABS` (SG54). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
  const TABS = ["compose", "stories", "batches", "characters", "locations", "actions", "loras", "jobs", "traces"];
```

with:

```javascript
  const TABS = ["compose", "seeds", "stories", "batches", "characters", "locations", "actions", "loras", "jobs", "traces"];
```

**3.9.** `showTab` (SG54). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
    if (name !== "batches") { stopBatchPoll(); }
```

with:

```javascript
    if (name !== "batches") { stopBatchPoll(); }
    if (name !== "seeds") { stopSeedPoll(); }
    if (name === "seeds") { loadSeeds(); }
```

**3.10.** The Characters still button (SG64). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
      res.data.dataset.stills.forEach(function (p) { gallery.appendChild(el("img", {src: fileUrl(p), alt: p})); });
```

with:

```javascript
      res.data.dataset.stills.forEach(function (p) { gallery.appendChild(el("figure", {cls: "se-still"}, [el("img", {src: fileUrl(p), alt: p}), button("New seed from this", function () { seedFromStill(name, p); })])); });
```

**3.11.** `jobLabel` (SG64). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
    return job.story_id || job.character || (job.kind === "smoke" ? "smoke render" : "-");
```

with:

```javascript
    return job.story_id || job.character || (job.seed_run ? "seed run " + job.seed_run : "") || (job.kind === "smoke" ? "smoke render" : "-");
```

**3.12.** `renderProgress` (SG64). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
    } else {
      box.appendChild(el("div", {text: job.kind + (p.elapsed_s !== null ? " - " + p.elapsed_s + " s" : "") +
        (p.face_problem ? " - the seed face was refused" : "")}));
    }
```

with:

```javascript
    } else {
      const c = p.candidates;
      let counted = "";
      if (c && c.current) { counted = " - candidate " + c.current + " of " + c.total; }
      else if (c) { counted = " - " + c.done + " of " + c.total + " candidates"; }
      box.appendChild(el("div", {text: job.kind + (p.elapsed_s !== null ? " - " + p.elapsed_s + " s" : "") +
        (p.face_problem ? " - the seed face was refused" : "") + counted}));
    }
```

**3.13.** `start` (SG64). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
    setupCompose();
    setupSmoke();
```

with:

```javascript
    setupCompose();
    setupSeeds();
    setupSmoke();
```

**3.14.** The Seeds functions (SG57-SG63). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
  // --- characters (MU82) ---------------------------------------------------------------
```

with:

```javascript
  // --- seeds (docs/superpowers/specs/2026-11-02-seed-generator-design.md, Section 6) ---------

  function seedCanvas(w, h) {
    const longest = Math.max(w, h);
    let a = w;
    let b = h;
    if (longest > SEED_LONG_EDGE) {
      a = Math.floor(w * SEED_LONG_EDGE / longest);
      b = Math.floor(h * SEED_LONG_EDGE / longest);
    }
    return {width: Math.floor(a / 16) * 16, height: Math.floor(b / 16) * 16};
  }

  function setSeedSource(source, statusText) {
    S.seeds.source = source;
    S.seeds.natural = null;
    $("#se-source-status").textContent = statusText;
    $("#se-source-size").textContent = "";
    const img = $("#se-source-img");
    img.src = fileUrl(source.path);
    show(img, true);
    updateSeedButtons();
  }

  async function onSeedSourceFile() {
    const file = $("#se-file").files[0];
    if (!file) { return; }
    $("#se-source-status").textContent = "uploading…";
    try {
      const id = await uploadFile(file);
      setSeedSource({kind: "upload", upload_id: id, path: S.host.state_dir + "/uploads/" + id}, "uploaded " + id.slice(0, 12));
    } catch (err) {
      $("#se-source-status").textContent = err.message;
    }
  }

  function updateSeedButtons() {
    const cap = capability("seed_edit");
    const models = cap.models || null;
    const select = $("#se-model");
    Array.prototype.forEach.call(select.options, function (o) {
      o.disabled = Boolean(models && models[o.value] && models[o.value].ok === false);
    });
    const chosen = select.options[select.selectedIndex];
    if (chosen && chosen.disabled) {
      const other = Array.prototype.filter.call(select.options, function (o) { return !o.disabled; })[0];
      if (other) { select.value = other.value; }
    }
    const model = select.value;
    let note = "";
    if (cap.ok === null) {
      note = "checking models…";
    } else if (!models && cap.ok === false) {
      note = "cannot check the seed models: " + cap.reason;
    } else if (models) {
      const parts = [];
      const off = "unavailable — ";
      if (!models.zimage.ok) { parts.push("Z-Image: " + off + models.zimage.reason); }
      if (models.qwen.ok) { parts.push("Qwen-Image-Edit backend: " + SEED_BACKEND_LABELS[models.qwen.backend]); }
      else { parts.push("Qwen-Image-Edit: " + off + models.qwen.reason); }
      note = parts.join("; ");
    }
    $("#se-model-note").textContent = note;
    show($("#se-strength-box"), model === "zimage");
    $("#se-prompt-count").textContent = $("#se-prompt").value.length + " / " + SEED_PROMPT_MAX + " characters";
    const natural = S.seeds.natural;
    const canvas = natural ? seedCanvas(natural.width, natural.height) : null;
    const entry = models && models[model];
    const strength = Number($("#se-strength").value);
    const seedText = $("#se-seed").value.trim();
    const seed = Number(seedText);
    let reason = "";
    if (S.seeds.busy) { reason = "queueing…"; }
    else if (!S.seeds.source) { reason = "choose a source image"; }
    else if (!natural) { reason = "loading the source image…"; }
    else if (canvas.width < SEED_MIN_SIDE || canvas.height < SEED_MIN_SIDE) {
      reason = "the source is too small: each side must be at least 64 px after scaling";
    }
    else if (!$("#se-prompt").value.trim()) { reason = "enter a prompt"; }
    else if (!(entry && entry.ok === true)) {
      reason = SEED_MODEL_LABELS[model] + " unavailable: " + ((entry && entry.reason) || cap.reason || "probing");
    }
    else if (model === "zimage" && !(Number.isFinite(strength) && strength >= 0.10 && strength <= 0.90)) {
      reason = "strength must be from 0.10 to 0.90";
    }
    else if (seedText !== "" && !(Number.isInteger(seed) && seed >= 0 && seed <= 2147483647)) {
      reason = "seed must be an integer from 0 to 2147483647";
    }
    $("#se-generate").disabled = reason !== "";
    $("#se-generate-reason").textContent = reason;
  }

  function seedBody() {
    const src = S.seeds.source;
    let source;
    if (src.kind === "upload") { source = {upload_id: src.upload_id}; }
    else if (src.kind === "run") { source = {run: src.run, n: src.n}; }
    else { source = {character: src.character, still: src.still}; }
    const model = $("#se-model").value;
    const seedText = $("#se-seed").value.trim();
    return {ws: S.ws, source: source, prompt: $("#se-prompt").value, model: model,
            strength: model === "zimage" ? Number($("#se-strength").value) : null,
            candidates: Number($("#se-candidates").value), seed: seedText === "" ? null : Number(seedText)};
  }

  async function generateSeeds() {
    S.seeds.busy = true;
    updateSeedButtons();
    let failure = null;
    try {
      const res = await api("POST", "/api/seeds/runs", seedBody());
      if (res.status === 201) {
        openSeedRun(res.data.run.run);
        pollJobs();
      } else {
        failure = (res.data && res.data.error) || ("http " + res.status);
      }
    } finally {
      S.seeds.busy = false;
      updateSeedButtons();
      if (failure !== null) { $("#se-generate-reason").textContent = failure; }
    }
  }

  async function openSeedRun(run) {
    stopSeedPoll();
    S.seeds.run = run;
    S.seeds.view = null;
    S.seeds.rows = {};
    clear($("#se-grid"));
    const res = await api("GET", "/api/seeds/runs/" + enc(run) + wsQuery());
    if (S.seeds.run !== run) { return; }
    if (res.status !== 200) {
      $("#se-run-title").textContent = run;
      $("#se-run-status").textContent = (res.data && res.data.error) || ("http " + res.status);
      return;
    }
    renderSeedRun(res.data);
    if (SEED_ACTIVE.indexOf(res.data.state) >= 0) { S.timers.seeds = setInterval(pollSeedRun, SEED_POLL_MS); }
  }

  async function pollSeedRun() {
    const run = S.seeds.run;
    if (!run) { stopSeedPoll(); return; }
    const res = await api("GET", "/api/seeds/runs/" + enc(run) + wsQuery());
    if (res.status !== 200 || S.seeds.run !== run) { return; }
    renderSeedRun(res.data);
    if (SEED_ACTIVE.indexOf(res.data.state) < 0) {
      stopSeedPoll();
      loadSeedRuns();
    }
  }

  function renderSeedRun(view) {
    if (!view || view.run !== S.seeds.run) { return; }
    S.seeds.view = view;
    $("#se-run-title").textContent = view.run + " · " + (SEED_MODEL_LABELS[view.model] || view.model) +
      (view.backend ? " (" + SEED_BACKEND_LABELS[view.backend] + ")" : "");
    const job = view.job;
    const progress = job && job.progress && job.progress.candidates;
    const counts = {ok: 0, blocked: 0, failed: 0};
    view.candidates.forEach(function (c) { if (counts[c.status] !== undefined) { counts[c.status] += 1; } });
    let status;
    if (view.state === "queued") { status = "queued (position " + (job && job.queue_position) + ")"; }
    else if (view.state === "starting") { status = "starting…"; }
    else if (view.state === "running") {
      status = progress && progress.current ? "candidate " + progress.current + " of " + progress.total + "…" : "running…";
    }
    else if (view.state === "done") {
      status = "done: " + counts.ok + " ok, " + counts.blocked + " blocked, " + counts.failed + " failed";
    }
    else if (view.state === "failed") { status = "failed: " + (view.error || (job && job.error) || "see the job log"); }
    else if (view.state === "cancelled") { status = "cancelled"; }
    else if (view.state === "lost") { status = "lost: the job's runner disappeared"; }
    else { status = "unknown: the job record is gone"; }
    $("#se-run-status").textContent = status;
    view.candidates.forEach(function (cand) { seedRow(view, cand); });
  }

  function seedRow(view, cand) {
    const progress = view.job && view.job.progress && view.job.progress.candidates;
    const current = progress ? progress.current : null;
    const key = cand.status + "|" + (cand.path || "") + "|" + (cand.status === "pending" && cand.n === current ? "now" : "");
    let row = S.seeds.rows[cand.n];
    if (!row) {
      const source = el("img", {cls: "se-img", alt: "source image"});
      if (view.source) { source.src = fileUrl(view.source); }
      const node = el("div", {cls: "se-row"}, [el("div", {cls: "se-label", text: "Candidate " + cand.n + " · seed " + cand.seed}), source]);
      $("#se-grid").appendChild(node);
      row = S.seeds.rows[cand.n] = {status: null, node: node, parts: []};
    }
    if (row.status === key) { return; }
    row.status = key;
    row.parts.forEach(function (piece) { piece.remove(); });
    let cell;
    if (cand.status === "ok" && cand.path) { cell = el("img", {cls: "se-img", src: fileUrl(cand.path), alt: "candidate " + cand.n}); }
    else if (cand.status === "ok") { cell = el("span", {cls: "muted", text: "the image file is missing"}); }
    else if (cand.status === "pending") { cell = el("span", {cls: "muted", text: cand.n === current ? "generating…" : "waiting…"}); }
    else if (cand.status === "blocked") { cell = el("span", {cls: "muted", text: "blocked by content safety"}); }
    else { cell = el("span", {cls: "muted", text: "failed"}); }
    row.parts = [cell];
    if (cand.status === "ok" && cand.path) {
      const run = view.run;
      const input = el("input", {cls: "se-keep-folder", type: "text", list: "se-folder-options", placeholder: "folder name", size: "20"});
      const status = el("span", {cls: "se-cand-status muted"});
      row.parts.push(el("div", {cls: "se-actions"}, [input,
        button("Keep", function () { keepSeed(run, cand.n, input, status); }),
        button("Use in Compose", function () { useSeed(run, cand.n, status); }),
        button("Edit again", function () { editSeedAgain(cand); }),
        status]));
    }
    row.parts.forEach(function (piece) { row.node.appendChild(piece); });
  }

  async function keepSeed(run, n, input, status) {
    const res = await api("POST", "/api/seeds/runs/" + enc(run) + "/keep", {ws: S.ws, n: n, folder: input.value.trim()});
    if (res.status === 201) {
      status.textContent = "kept as " + res.data.path;
      loadSeedFolders();
    } else {
      status.textContent = (res.data && res.data.error) || ("http " + res.status);
    }
  }

  async function useSeed(run, n, status) {
    const res = await api("POST", "/api/seeds/runs/" + enc(run) + "/use", {ws: S.ws, n: n});
    if (res.status !== 201) {
      status.textContent = (res.data && res.data.error) || ("http " + res.status);
      return;
    }
    const uploadId = res.data.upload_id;
    S.seedUpload = uploadId;
    $("#c-res-seed").checked = true;
    $("#c-seed-status").textContent = "seed from " + run + " candidate " + n + " (" + uploadId.slice(0, 12) + ")";
    showTab("compose");
    updateComposeButtons();
    preview();
  }

  function editSeedAgain(cand) {
    const run = S.seeds.view.run;
    setSeedSource({kind: "run", run: run, n: cand.n, path: cand.path}, "candidate " + cand.n + " of " + run);
  }

  async function loadSeeds() {
    await loadSeedRuns();
    await loadSeedFolders();
    updateSeedButtons();
    if (S.seeds.run) { openSeedRun(S.seeds.run); }
  }

  async function loadSeedRuns() {
    if (!S.ws) { return; }
    const res = await api("GET", "/api/seeds/runs" + wsQuery());
    const body = clear($("#se-runs tbody"));
    if (res.status !== 200) { return; }
    res.data.runs.forEach(function (r) {
      const text = typeof r.prompt === "string" ? (r.prompt.length > 80 ? r.prompt.slice(0, 80) + "…" : r.prompt) : "";
      const thumbs = el("td");
      r.thumbs.forEach(function (p) { thumbs.appendChild(el("img", {cls: "se-mini", src: fileUrl(p), alt: ""})); });
      const row = el("tr", {cls: "clickable"}, [el("td", {text: r.run}), el("td", {text: text}),
        el("td", {text: SEED_MODEL_LABELS[r.model] || String(r.model)}), el("td", {text: r.state}), thumbs]);
      row.addEventListener("click", function () { openSeedRun(r.run); });
      body.appendChild(row);
    });
  }

  async function loadSeedFolders() {
    if (!S.ws) { return; }
    const res = await api("GET", "/api/seeds/folders" + wsQuery());
    const options = clear($("#se-folder-options"));
    const body = clear($("#se-folders tbody"));
    if (res.status !== 200) { return; }
    res.data.folders.forEach(function (f) {
      options.appendChild(el("option", {value: f.folder}));
      const input = el("input", {cls: "se-path", type: "text", readonly: "readonly", size: "60", value: f.path});
      const status = el("span", {cls: "muted"});
      body.appendChild(el("tr", {}, [el("td", {text: f.folder}), el("td", {text: String(f.count)}), el("td", {}, [input]),
        el("td", {}, [button("Copy path", function () { copySeedPath(input, status); }), status])]));
    });
  }

  function copySeedPath(input, status) {
    function selectIt() {
      input.focus();
      input.select();
      status.textContent = "selected — press Cmd+C";
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(input.value).then(function () { status.textContent = "copied"; }, selectIt);
    } else {
      selectIt();
    }
  }

  function seedFromStill(name, p) {
    const still = p.split("/").pop();
    setSeedSource({kind: "character", character: name, still: still, path: p}, "still " + still + " of " + name);
    showTab("seeds");
  }

  function stopSeedPoll() {
    if (S.timers.seeds) { clearInterval(S.timers.seeds); S.timers.seeds = null; }
  }

  function resetSeeds() {
    stopSeedPoll();
    S.seeds.source = null;
    S.seeds.natural = null;
    S.seeds.run = null;
    S.seeds.view = null;
    S.seeds.rows = {};
    $("#se-source-status").textContent = "";
    $("#se-source-size").textContent = "";
    const img = $("#se-source-img");
    img.removeAttribute("src");
    show(img, false);
    $("#se-run-title").textContent = "";
    $("#se-run-status").textContent = "";
    clear($("#se-grid"));
    clear($("#se-runs tbody"));
    clear($("#se-folders tbody"));
    clear($("#se-folder-options"));
    updateSeedButtons();
  }

  function setupSeeds() {
    $("#se-file").addEventListener("change", onSeedSourceFile);
    $("#se-generate").addEventListener("click", generateSeeds);
    $("#se-source-img").addEventListener("load", function () {
      const img = $("#se-source-img");
      if (!S.seeds.source) { return; }
      S.seeds.natural = {width: img.naturalWidth, height: img.naturalHeight};
      const canvas = seedCanvas(img.naturalWidth, img.naturalHeight);
      $("#se-source-size").textContent = img.naturalWidth + " × " + img.naturalHeight + " → " + canvas.width + " × " + canvas.height;
      updateSeedButtons();
    });
    ["input", "change"].forEach(function (type) { $("#panel-seeds").addEventListener(type, updateSeedButtons); });
  }

  // --- characters (MU82) ---------------------------------------------------------------
```

**3.15.** The CSS (SG65). Edit `static/movie-ui/app.css`: replace this text, which occurs exactly once:

```css
.seam-missed td { background: var(--warn-bg); }
```

with:

```css
.seam-missed td { background: var(--warn-bg); }
/* seed generator spec SG65: the Seeds tab and the Characters stills */
.se-grid { display: flex; flex-direction: column; gap: 12px; }
.se-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: flex-start; }
.se-img, .se-thumb { width: 320px; height: auto; border: 1px solid var(--line); }
.se-actions { display: flex; flex-direction: column; gap: 4px; }
.se-mini { width: 64px; height: auto; margin-right: 4px; }
.gallery figure { margin: 0; display: flex; flex-direction: column; gap: 4px; }
```

- [ ] **Step 4: Run the new tests, the syntax check, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedgen.py 2>&1 | tail -1
node --check static/movie-ui/app.js && echo "node ok"
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seams.py::test_ct27_the_static_page tests/test_movie_ui_batch.py::test_bt13_the_static_page tests/test_location_ui.py::test_lu13_the_static_page tests/test_vlm_lifecycle.py::test_vl26_page_gate_and_warn_style tests/test_soft_panel_count.py::test_spt27_the_regenerate_target_is_wired_in_the_static_ui tests/test_movie_ui_seedfolder.py::test_sdt25_the_static_page tests/test_movie_ui_seedfolder.py::test_sdt37_the_static_page_characters tests/test_movie_ui_seedfolder.py::test_sf_final_review_queue_and_confirm_guards tests/test_movie_ui_http.py::test_mut24_page_headers_and_asset_rules 2>&1 | tail -1
```

Expected: `56 passed`, `node ok`, then `3 failed, 6 passed` (the three `TABS` lines fail; the other static-page tests are unchanged). Run the compile check with `FILES` = `tests/test_movie_ui_seedgen.py`; expected: `compiled 1` twice. Then run the gate block with `N=6`. Expected: `GATE PASS`, `lost 11 (listed 11, unexpected 0)` (every line of the list), `new tests 91, not passing 0`, `baseline failures still failing 2 of 2`, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
git add static/movie-ui/index.html static/movie-ui/app.js static/movie-ui/app.css tests/test_movie_ui_seedgen.py
git diff --cached --name-only    # expected: those 4 paths
git commit -m "feat(movie-ui): the Seeds tab: source, prompt, model gating, before/after grid with Keep, Use in Compose and Edit again, runs and seed-folder lists; New seed from this on Characters stills; the seed run label and candidate progress on Jobs (SG54-SG65; SGT33)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The test-only re-baseline (spec 9.2, Plan ruling PR2) and SGT34 (Plan ruling PR6)

**Files:**
- Modify (test-only; at 2b19b59):
  - `tests/test_movie_ui_http.py`: `test_mut18` `:44`, `test_mut2` `:343-344`;
  - `tests/test_location_ui.py`: `test_lu1` `:66`, `test_lu13` `:389-390`;
  - `tests/test_movie_ui_seedfolder.py`: `test_sdt19` `:612` (Plan ruling PR2), `test_sdt11` `:920-921`, `test_sdt29` `:957-958`;
  - `tests/test_movie_ui_batch.py`: `test_bt13` `:495-496`;
  - `tests/test_movie_ui_seams.py`: `JS_SNIPPETS` (used by `test_ct27`) `:351-352`;
  - `tests/test_movie_ui_builder.py`: `NEW_PY` `:216-217`, `test_mut25_source_scan_of_new_python_files` `:261-262`;
  - `tests/movie_ui_testutil.py`: `copy_ui` `:465`;
  - `tests/test_movie_ui_seedgen.py` (append SGT34 after Review Focus 5).

**Interfaces:**
- Consumes: the commits of Tasks 1-6.
- Produces: the one test-only re-baseline commit (spec 9.2, 11 step 4).

- [ ] **Step 1: Write SGT34.**

Edit `tests/test_movie_ui_seedgen.py`: replace this text, which occurs exactly once:

```python
        assert got == want, (w0, h0)
```

with:

```python
        assert got == want, (w0, h0)


# --- SGT34 (SG2, SG24): the new Python files are compiled and scanned; the tool's top-level imports ---------

def test_sgt34_the_new_python_files_and_the_tool_imports():
    with open(os.path.join(WS, "tests", "test_movie_ui_builder.py"), encoding="utf-8") as f:
        builder = f.read()
    start = builder.index("NEW_PY = (")
    new_py = builder[start:builder.index(")", start)]
    for rel in ("movie_ui_seedgen.py", "bin/seed-edit", "bin/seed-edit-setup", "seed_edit_mflux_child.py",
                "tests/test_seed_edit_tool.py", "tests/test_movie_ui_seedgen.py"):
        assert '"%s"' % rel in new_py, rel
    with open(os.path.join(WS, "bin", "seed-edit"), encoding="utf-8") as f:
        source = f.read()
    assert re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M) == [
        "argparse", "glob", "importlib.util", "json", "os", "re", "secrets", "shutil", "signal", "subprocess", "sys",
        "threading", "time", "movie_ui_lib"]
```

- [ ] **Step 2: Run the re-baselined tests and SGT34, and expect the listed failures.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_movie_ui_http.py::test_mut18_every_api_route_needs_the_token \
  tests/test_location_ui.py::test_lu1_the_location_routes_need_the_token \
  tests/test_movie_ui_seedfolder.py::test_sdt11_the_route_and_its_token \
  tests/test_movie_ui_seedfolder.py::test_sdt29_the_characters_route_and_its_token \
  tests/test_movie_ui_http.py::test_mut2_preview_argv_is_the_job_argv \
  tests/test_movie_ui_seedfolder.py::test_sdt19_the_seed_folder_tag \
  tests/test_movie_ui_builder.py::test_mut25_source_scan_of_new_python_files \
  tests/test_movie_ui_builder.py::test_mut25_every_new_and_changed_file_compiles \
  tests/test_movie_ui_jobs.py::test_mut15_bin_movie_ui_lock_port_and_startup_lines \
  tests/test_location_ui.py::test_lu13_the_static_page \
  tests/test_movie_ui_batch.py::test_bt13_the_static_page \
  tests/test_movie_ui_seams.py::test_ct27_the_static_page \
  tests/test_movie_ui_seedgen.py::test_sgt34_the_new_python_files_and_the_tool_imports 2>&1 | tail -1
```

Expected: `12 failed, 2 passed` (the eleven listed tests and SGT34 fail; both `test_mut25_every_new_and_changed_file_compiles` cases pass).

- [ ] **Step 3: The re-baseline edits.**

**3.1.** The `test_mut18` route count. Edit `tests/test_movie_ui_http.py`: replace this text, which occurs exactly once:

```python
    assert len(srv.ROUTES) == 57
```

with:

```python
    assert len(srv.ROUTES) == 63
```

**3.2.** The `test_mut2` key set. Edit `tests/test_movie_ui_http.py`: replace this text, which occurs exactly once:

```python
                                      "started", "ended", "exit_code", "error", "queue_position", "command",
                                      "progress", "seed_folder"}
```

with:

```python
                                      "started", "ended", "exit_code", "error", "queue_position", "command",
                                      "progress", "seed_folder", "seed_run"}
```

**3.3.** The `test_lu1` route count. Edit `tests/test_location_ui.py`: replace this text, which occurs exactly once:

```python
    assert len(srv.ROUTES) == 57
```

with:

```python
    assert len(srv.ROUTES) == 63
```

**3.4.** The `test_sdt11` route count. Edit `tests/test_movie_ui_seedfolder.py`: replace this text, which occurs exactly once:

```python
    assert routes[i + 1] == ("POST", r"/api/jobs/seed-folder", "h_seed_folder", "/api/jobs/seed-folder")
    assert len(srv.ROUTES) == 57
```

with:

```python
    assert routes[i + 1] == ("POST", r"/api/jobs/seed-folder", "h_seed_folder", "/api/jobs/seed-folder")
    assert len(srv.ROUTES) == 63
```

**3.5.** The `test_sdt29` route count. Edit `tests/test_movie_ui_seedfolder.py`: replace this text, which occurs exactly once:

```python
                             "/api/characters/seed-folder")
    assert len(srv.ROUTES) == 57
```

with:

```python
                             "/api/characters/seed-folder")
    assert len(srv.ROUTES) == 63
```

**3.6.** The `test_sdt19` summary key count (Plan ruling PR2). Edit `tests/test_movie_ui_seedfolder.py`: replace this text, which occurs exactly once:

```python
    assert all(len(j) == 15 for j in queued)
```

with:

```python
    assert all(len(j) == 16 for j in queued)
```

**3.7.** The `test_lu13` TABS text. Edit `tests/test_location_ui.py`: replace this text, which occurs exactly once:

```python
    assert ('const TABS = ["compose", "stories", "batches", "characters", "locations", "actions", "loras", '
            '"jobs", "traces"];') in js
```

with:

```python
    assert ('const TABS = ["compose", "seeds", "stories", "batches", "characters", "locations", "actions", "loras", '
            '"jobs", "traces"];') in js
```

**3.8.** The `test_bt13` TABS text. Edit `tests/test_movie_ui_batch.py`: replace this text, which occurs exactly once:

```python
    assert ('const TABS = ["compose", "stories", "batches", "characters", "locations", "actions", "loras", '
            '"jobs", "traces"];') in js
```

with:

```python
    assert ('const TABS = ["compose", "seeds", "stories", "batches", "characters", "locations", "actions", "loras", '
            '"jobs", "traces"];') in js
```

**3.9.** The `test_ct27` TABS snippet. Edit `tests/test_movie_ui_seams.py`: replace this text, which occurs exactly once:

```python
    'const TABS = ["compose", "stories", "batches", "characters", "locations", "actions", "loras", '
    '"jobs", "traces"];',
```

with:

```python
    'const TABS = ["compose", "seeds", "stories", "batches", "characters", "locations", "actions", "loras", '
    '"jobs", "traces"];',
```

**3.10.** `NEW_PY`. Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
          "movie_ui_batch.py", "tests/test_movie_ui_batch.py", "movie_ui_seedfolder.py",
          "tests/test_movie_ui_seedfolder.py")
```

with:

```python
          "movie_ui_batch.py", "tests/test_movie_ui_batch.py", "movie_ui_seedfolder.py",
          "tests/test_movie_ui_seedfolder.py", "movie_ui_seedgen.py", "bin/seed-edit", "bin/seed-edit-setup",
          "seed_edit_mflux_child.py", "tests/test_seed_edit_tool.py", "tests/test_movie_ui_seedgen.py")
```

**3.11.** The `allowed` import set. Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
                   "subprocess", "sys", "threading", "time", "fleet_lib", "movie_ui_lib", "movie_ui_batch",
                   "movie_ui_seedfolder"}
```

with:

```python
                   "subprocess", "sys", "threading", "time", "fleet_lib", "movie_ui_lib", "movie_ui_batch",
                   "movie_ui_seedfolder", "movie_ui_seedgen"}
```

**3.12.** `copy_ui`. Edit `tests/movie_ui_testutil.py`: replace this text, which occurs exactly once:

```python
                "movie_ui_batch.py", "movie_ui_seedfolder.py"):
```

with:

```python
                "movie_ui_batch.py", "movie_ui_seedfolder.py", "movie_ui_seedgen.py"):
```

- [ ] **Step 4: Run the checks and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
git diff --numstat -- tests/
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_movie_ui_http.py::test_mut18_every_api_route_needs_the_token \
  tests/test_location_ui.py::test_lu1_the_location_routes_need_the_token \
  tests/test_movie_ui_seedfolder.py::test_sdt11_the_route_and_its_token \
  tests/test_movie_ui_seedfolder.py::test_sdt29_the_characters_route_and_its_token \
  tests/test_movie_ui_http.py::test_mut2_preview_argv_is_the_job_argv \
  tests/test_movie_ui_seedfolder.py::test_sdt19_the_seed_folder_tag \
  tests/test_movie_ui_builder.py::test_mut25_source_scan_of_new_python_files \
  tests/test_movie_ui_builder.py::test_mut25_every_new_and_changed_file_compiles \
  tests/test_movie_ui_jobs.py::test_mut15_bin_movie_ui_lock_port_and_startup_lines \
  tests/test_location_ui.py::test_lu13_the_static_page \
  tests/test_movie_ui_batch.py::test_bt13_the_static_page \
  tests/test_movie_ui_seams.py::test_ct27_the_static_page \
  tests/test_movie_ui_seedgen.py::test_sgt34_the_new_python_files_and_the_tool_imports 2>&1 | tail -1
```

Expected: eight numstat lines, in `git`'s path order:
- `1	1	qwen-agent-workspace/tests/movie_ui_testutil.py`
- `2	2	qwen-agent-workspace/tests/test_location_ui.py`
- `1	1	qwen-agent-workspace/tests/test_movie_ui_batch.py`
- `3	2	qwen-agent-workspace/tests/test_movie_ui_builder.py`
- `2	2	qwen-agent-workspace/tests/test_movie_ui_http.py`
- `1	1	qwen-agent-workspace/tests/test_movie_ui_seams.py`
- `3	3	qwen-agent-workspace/tests/test_movie_ui_seedfolder.py`
- `17	0	qwen-agent-workspace/tests/test_movie_ui_seedgen.py`

Then `14 passed` (the twelve listed tests, both compile cases included, and SGT34; the 3.9 compile case now compiles the six new Python files and `test_mut25`'s scan covers them). If a value differs, fix the Edit, not this command. Then run the gate block with `N=7`. Expected: `GATE PASS`, `lost 0`, `new tests 92, not passing 0`, `baseline failures still failing 2 of 2`, and `offline unchanged`.

- [ ] **Step 5: Commit (test-only; spec 9.2, 11 step 4).**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedgen-wt/qwen-agent-workspace
git add tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_seedfolder.py tests/test_movie_ui_batch.py tests/test_movie_ui_seams.py tests/test_movie_ui_builder.py tests/movie_ui_testutil.py tests/test_movie_ui_seedgen.py
git diff --cached --name-only    # expected: only those 8 paths
git commit -m "test: re-baseline mut18, lu1, sdt11, sdt29 (63 routes), mut2 and sdt19 (the seed_run summary key), the three TABS pins, mut25 (the new seed generator files compiled, scanned and movie_ui_seedgen allowed) and copy_ui for mut15; add SGT34 (seed generator spec 9.2)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Verification (controller only; not an implementer task)

The controller runs these after Task 7, in spec 11 step 5's order: the pass bar items 1-3, the browser check (items 1-10), the Opus design review; then, each only on the user's explicit go, the live checks of spec 9.4. Every rule of "Global Constraints" applies. A finding is fixed in a new commit on the owning task's files; then that task's Step 4 and V1 rerun.

- [ ] **V1: The pass bar, items 1-3 (spec 10), about 18 minutes.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/seedgen-baseline
cd $S/seedgen-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py 2>&1 | tail -1
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/final-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt; tail -1 $D/final-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/final-pytest.txt $D/expected-failures.txt 7
diff <(grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt | sort) <(grep -E '^(FAILED|ERROR)' $D/final-pytest.txt | sort) && echo "same failures, same messages"
grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $D/final-pytest.txt
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1
git diff --stat 9eb363c..HEAD -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py content_safety.py mps_guard.py movie_ui_seedfolder.py movie_ui_batch.py | tail -1
git diff --name-only 9eb363c..HEAD
git diff 9eb363c..HEAD -- movie_ui_seedgen.py | grep -E '^\+(import|from) '
git diff 9eb363c..HEAD -- movie_ui_server.py | grep -E '^\+(import|from) '
git diff 9eb363c..HEAD -- tests/ | grep -E '^\+' | grep -nE "expanduser\(|urlopen|import requests|zshenv|fleet\.env|macstudio|127\.0\.0\.1:81" || echo "no real HOME, HTTP client, private host or model-server address in the new tests"
grep -n 'STATE_SUBDIRS = ' movie_ui_lib.py
git ls-files -s bin/seed-edit bin/seed-edit-setup | cut -c1-6
```

Expected, in order:
- `92 passed` (item 1: SGT1-SGT34 and the five Review Focus pins);
- the final summary is the baseline's with the pass count higher by exactly 92 (`2 failed, 2451 passed, 2 skipped`);
- `lost 0 (listed 0, unexpected 0); new tests 92, not passing 0` and `GATE PASS`;
- `same failures, same messages` (item 2: only `test_d2_copied_literals_match_the_spike` and `test_rst62_import_sets`);
- `1` (`test_mut26` passes unedited);
- `OK 347/347` (item 3);
- no output from the `--stat` (no pipeline file, `content_safety.py`, `mps_guard.py`, `movie_ui_seedfolder.py` or `movie_ui_batch.py` changed; spec 0.2);
- the changed paths are exactly the 2 docs (the spec and this plan) plus `bin/seed-edit`, `bin/seed-edit-setup`, `movie_ui_lib.py`, `movie_ui_seedgen.py`, `movie_ui_server.py`, `seed_edit_mflux_child.py`, `static/movie-ui/app.css`, `static/movie-ui/app.js`, `static/movie-ui/index.html`, `tests/movie_ui_testutil.py`, `tests/test_location_ui.py`, `tests/test_movie_ui_batch.py`, `tests/test_movie_ui_builder.py`, `tests/test_movie_ui_http.py`, `tests/test_movie_ui_seams.py`, `tests/test_movie_ui_seedfolder.py`, `tests/test_movie_ui_seedgen.py` and `tests/test_seed_edit_tool.py`, each with the `qwen-agent-workspace/` prefix (20 paths);
- exactly four import lines for the module: `+import re`, `+import secrets`, `+import time`, `+import movie_ui_lib as lib` (SG1);
- exactly one for the server: `+import movie_ui_seedgen as seedgen` (no third-party import);
- `no real HOME, HTTP client, private host or model-server address in the new tests`;
- `STATE_SUBDIRS = ("jobs", "uploads", "traces", "smoke", "batches")` (SG3: no new state subdirectory);
- `100755` twice.

If a timing-sensitive test failed in one run only, rerun it alone and record both results. Any other difference: stop and report.

- [ ] **V2: The browser check (spec 9.3; before the merge; not pytest).**

A throwaway demo server under `$S/sgdemo/`, never committed. It never calls `start_threads`, so there is no dispatcher, no probe thread, and no job ever runs (the run queued in item 3 stays queued). The stub workspace gets a fresh copy of `static/movie-ui` on every start, because `make_server`'s third argument is also the directory the page is served from. The page URL, which carries this run's throwaway token, is written to `$S/sgdemo/url.txt` (mode 0600) and never printed (Plan ruling PR22). The stub `bin/seed-edit` prints `$S/sgdemo/models.json` for `--probe`, so item 10 changes the probe's answer by rewriting that file. `server.stills_py` is a stub, so Re-check imports no torch.

Create `$S/sgdemo/demo.py` with the Write tool, exactly:

```python
"""Throwaway demo server for the seed generator browser check (spec 9.3; never committed).

Run: python3 -B $S/sgdemo/demo.py (Ctrl-C stops it). It never calls start_threads, so no job ever
runs. The page URL, with this run's throwaway token, goes to $S/sgdemo/url.txt (mode 0600) and is
never printed. The static files are copied fresh from the worktree on every start.
"""
import json
import os
import secrets
import shutil
import sys

S = "/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad"
WS = S + "/seedgen-wt/qwen-agent-workspace"
DEMO = S + "/sgdemo"
RUN = "se-20261102-120000-0001"
os.environ["HOME"] = DEMO + "/home"
os.environ["MOVIE_UI_VLM_LIFECYCLE"] = "0"
os.environ["MOVIE_UI_VLM_TOOLS"] = DEMO + "/no-tools"
os.environ["MOVIE_UI_VLM_PORT"] = "9"
for key in list(os.environ):
    if key.startswith("SEED_EDIT_"):
        del os.environ[key]
os.makedirs(os.environ["HOME"], exist_ok=True)
sys.path.insert(0, WS + "/tests")
import movie_ui_testutil as mt  # noqa: E402  (puts WS on sys.path)
import movie_ui_lib as lib  # noqa: E402
import movie_ui_seedgen as seedgen  # noqa: E402
import movie_ui_server as srv  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402


def picture(path, size, back, front):
    """A real image: a background with a centred rectangle (PNG or JPEG by the extension)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = Image.new("RGB", size, back)
    w, h = size
    ImageDraw.Draw(img).rectangle([w // 4, h // 4, w * 3 // 4, h * 3 // 4], fill=front)
    img.save(path)


state = lib.state_dir()
lib.ensure_state(state)
ws = mt.make_stub_workspace(DEMO)
static = os.path.join(ws, "static", "movie-ui")
shutil.rmtree(static, ignore_errors=True)
shutil.copytree(os.path.join(WS, "static", "movie-ui"), static)
os.environ["CHARACTER_LIBRARY_DIR"] = os.path.join(ws, "generated", "characters")

models_path = os.path.join(DEMO, "models.json")
if not os.path.isfile(models_path):
    with open(models_path, "w", encoding="utf-8") as f:
        json.dump({"zimage": {"ok": True, "reason": None, "backend": "zimage"},
                   "qwen": {"ok": True, "reason": None, "backend": "mflux-q4"}}, f)
stub = os.path.join(ws, "bin", "seed-edit")
with open(stub, "w", encoding="utf-8") as f:
    f.write("#!%s\nimport sys\nif sys.argv[1:] == ['--probe']:\n"
            "    sys.stdout.write(open(%r, encoding='utf-8').read().strip() + '\\n')\n" % (sys.executable, models_path))
os.chmod(stub, 0o755)

kyra = os.path.join(ws, "generated", "characters", "kyra", "dataset")
picture(os.path.join(kyra, "contact_sheet.jpg"), (600, 400), (40, 40, 40), (200, 200, 200))
for i, color in ((1, (180, 60, 60)), (2, (60, 60, 180))):
    picture(os.path.join(kyra, "stills", "char_%02d.png" % i), (512, 768), color, (240, 220, 200))
show = json.dumps({"name": "kyra", "status": "trained", "seed": 7,
                   "dataset": {"contact_sheet": os.path.join(kyra, "contact_sheet.jpg")},
                   "loras": {"video": None, "stills": None}}, indent=2)
mt.stub_config(ws, {
    "character list": {"stdout": "NAME             TRIGGER          STATUS    VIDEO STILLS PHRASE\n"
                                 "kyra             kyrax            trained   yes   yes    the stranger\n"},
    "character show kyra": {"stdout": show + "\n"}})

run_dir = os.path.join(ws, "generated", "seeds", "runs", RUN)
if not os.path.isdir(run_dir):
    picture(os.path.join(run_dir, "source.png"), (1024, 672), (30, 90, 160), (250, 250, 250))
    picture(os.path.join(run_dir, "cand_01.png"), (1024, 672), (20, 30, 60), (250, 160, 40))
    picture(os.path.join(run_dir, "cand_03.png"), (1024, 672), (60, 20, 60), (120, 250, 120))
    lib.write_json_atomic(os.path.join(run_dir, "run.json"), {
        "schema": "seed-edit.run.v1", "run": RUN, "created": "2026-11-02T12:00:00Z", "state": "done",
        "prompt": "the same street at night, wet cobblestones", "model": "zimage", "backend": "zimage",
        "strength": 0.45, "seed": 41, "size": {"width": 1024, "height": 672},
        "source_size": {"width": 1024, "height": 672}, "source": "source.png", "source_origin": None,
        "job": None, "error": None,
        "candidates": [{"n": 1, "seed": 42, "status": "ok", "seconds": 61.2},
                       {"n": 2, "seed": 43, "status": "blocked", "seconds": 9.8},
                       {"n": 3, "seed": 44, "status": "ok", "seconds": 9.7}]})
picture(os.path.join(DEMO, "upload-1536x1024.png"), (1536, 1024), (90, 140, 90), (250, 250, 120))

stills_ok = os.path.join(DEMO, "stills-ok")
with open(stills_ok, "w", encoding="utf-8") as f:
    f.write("#!/bin/sh\nexit 0\n")
os.chmod(stills_ok, 0o755)
server = srv.make_server(0, state, ws, secrets.token_urlsafe(32))
assert server.port not in (8177, 8178, 8999), server.port
server.probe_ws = ws
server.stills_py = stills_ok
checked = lib.utc_now()
for key in ("render", "stills", "story_server"):
    server.capabilities[key] = {"ok": True, "reason": None, "checked": checked}
models, detail = lib.seed_edit_check(ws)
server.capabilities["seed_edit"] = seedgen.capability(models, detail, checked)
url_path = os.path.join(DEMO, "url.txt")
fd = os.open(url_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    f.write("http://127.0.0.1:%d/?t=%s\n" % (server.port, server.token))
print("demo serving on 127.0.0.1:%d; open the URL in %s" % (server.port, url_path))
sys.stdout.flush()
server.serve_forever()
```

Create `$S/sgdemo/qwen_off.py` with the Write tool, exactly:

```python
"""Browser check step 10: the demo stub's next --probe reports Qwen-Image-Edit unavailable."""
import json

PATH = "/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sgdemo/models.json"
with open(PATH, "w", encoding="utf-8") as f:
    json.dump({"zimage": {"ok": True, "reason": None, "backend": "zimage"},
               "qwen": {"ok": False, "backend": None,
                        "reason": "diffusers bf16: needs a host with at least 64 GiB of memory (this host has "
                                  "48.0 GiB); mflux q4: no mflux venv at /demo/python (run bin/seed-edit-setup)"}}, f)
print("qwen is now unavailable in the demo stub; press Re-check")
```

Run `python3 -B $S/sgdemo/demo.py` in the background (it prints `demo serving on 127.0.0.1:<port>; open the URL in .../url.txt`), open the URL with `open "$(cat $S/sgdemo/url.txt)"` (nothing is echoed), and stop the process (Ctrl-C or kill its PID) when done. If the port assert fires, start it again. The upload for item 2 is `$S/sgdemo/upload-1536x1024.png`. For item 10, run `python3 -B $S/sgdemo/qwen_off.py` (expected: `qwen is now unavailable in the demo stub; press Re-check`) and press Re-check. To repeat the check from scratch, stop the demo and move `$S/sgdemo` aside first (the kept files and the queued run persist across restarts). Pass when all of these hold (spec 9.3, verbatim):
1. The Seeds tab sits right after Compose; the note reads `Qwen-Image-Edit backend: mflux q4`.
2. Uploading a 1536×1024 PNG shows the thumbnail and `1536 × 1024 → 1024 × 672`; Generate stays disabled with `enter a prompt` until a prompt is typed; Strength (0.45) shows for Z-Image and hides for Qwen.
3. Generate (Z-Image, 2 candidates, seed 7) opens the run: title `se-… · Z-Image`, status `queued (position 1)`, two rows of source + `waiting…`; Jobs shows a queued `seed-edit` job labelled `seed run se-…`.
4. The runs list shows the new run first, then the demo run with two thumbnails.
5. Opening the demo run shows three rows, source and candidate at the same width; row 2 reads `blocked by content safety` with no buttons.
6. Keep row 1 into `heroes` → `kept as …/generated/seeds/heroes/se-20261102-120000-0001-01.png`; again → `…-01-2.png`; the folders table lists `heroes  2  <absolute path>`; Copy path either says `copied` (paste matches) or selects the path text.
7. Use in Compose on row 3 → Compose tab, Seed image radio checked, status `seed from se-20261102-120000-0001 candidate 3 (…)`, and the command preview carries `--seed-image <STATE>/uploads/<sha256>.png`.
8. Edit again on row 1 → Seeds source becomes that candidate (`candidate 1 of se-20261102-120000-0001`), the prompt text is unchanged.
9. Characters → `kyra` shows `New seed from this` under each still; clicking one opens Seeds with `still char_01.png of kyra` and its thumbnail.
10. After the stub's qwen entry is changed to unavailable and Re-check is pressed, the Qwen option is disabled and the note reads `Qwen-Image-Edit: unavailable — <reason>`.

Also observe, and report but do not block on: a Generate with Qwen-Image-Edit after `qwen_off.py` but before Re-check gets the server's 409; `#se-generate-reason` shows `Qwen-Image-Edit is unavailable: ...` and Generate is enabled again (Plan ruling PR5).

- [ ] **V3: The design review (spec 11 step 5).** Ask an Opus `design-reviewer` to review `git diff 2b19b59..HEAD -- qwen-agent-workspace` against the spec, this plan's rulings and the Review Focus. Fix every finding as above.

- [ ] **V4: Live check L1, setup (spec 9.4; controller-run only, and only on the user's explicit go).**
  - Never on macstudio. Never touch :8178. It creates `~/mflux-edit/.venv`, pip-installs `mflux==0.24.0` and downloads about 30 GB into the Z-Image hub; it uses no token.
  - Run `python3 bin/seed-edit-setup` from `WS`. Record its four size lines and its probe line.
  - Pass: exit 0 and `seed-edit-setup: probe: Qwen-Image-Edit ok (mflux-q4)`. If it refuses for free space (SG67 step 4: `only <x.x> GiB free on <path>; seed-edit-setup needs at least 31 GiB ...`), report the figure and stop (spec R2).
  - Without the go, record "not run (awaiting the user's go)".

- [ ] **V5: Live check L2, Z-Image (spec 9.4; controller-run only, and only on the user's explicit go).**
  - Requires this Mac's movie-ui running from this branch; starting it needs the user's go. The job's VLM preflight stops the story server and its postflight restores it, as for every forbidden kind ([VL]); the controller itself never starts, stops or contacts :8177 or :8178. Never on macstudio.
  - From the Seeds tab: one real seed image, a short edit prompt, Z-Image, 2 candidates.
  - Pass: the job ends `done` with 2 candidates `ok` (a `blocked` is recorded, not a failure); its log shows `vlm: stopped for this job` before the tool and the postflight line after. Record each candidate's seconds (candidate 1 includes the load, SG18).
  - Without the go, record "not run (awaiting the user's go)". L2 does not depend on L1.

- [ ] **V6: Live check L3, Qwen mflux q4 (spec 9.4; after L1; controller-run only, and only on the user's explicit go).**
  - Same conditions as V5. Right before Generate, record `python3 -c "import psutil; print('%.1f' % (psutil.virtual_memory().available / 2 ** 30))"`.
  - Same flow with Qwen-Image-Edit, 2 candidates.
  - Pass: the job ends `done`; the log shows `seed-edit: backend mflux-q4 (...)` and the child line `seed-edit-child: mflux 0.24.0, model Qwen/Qwen-Image-Edit-2511, transformer overrides ...` with `zero_cond_t` true in the overrides.
  - Record: the highest `seed-edit-child: mlx peak memory` line, the available memory before Generate, the seconds per candidate, and the candidate variety: `python3 -c "import sys; from PIL import Image, ImageChops, ImageStat; a, b = (Image.open(p).convert('RGB') for p in sys.argv[1:3]); print('%.2f' % (sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3))" <run dir>/cand_01.png <run dir>/cand_02.png` (the mean absolute per-pixel difference), plus a one-line visual note.
  - Without the go, record "not run (awaiting the user's go)".

- [ ] **V7: Hand-off.** Report the branch `seed-generator` and its 7 new commits (6 feature commits and the re-baseline) on top of the plan commit, V1-V6's results (live checks not run are recorded as such) and the V2 observation. Push and the merge are a separate step that needs the user's approval.

---

## Coverage

### Spec coverage: requirement → task

| Requirement | Task (step) |
|---|---|
| SG1 module rules | 1 (`movie_ui_seedgen.py`; SGT17 import check); V1 (the import lines) |
| SG2 3.9 source, the tool's top-level imports | 3 (SGT13's importtime check), 4, 7 (SGT34); the compile checks; V1 |
| SG3 nothing new under STATE | 5 (no state code; SGT29 writes only an upload); V1 (`STATE_SUBDIRS`) |
| SG4 argv rules | 3 (`check_args`; SGT5) |
| SG5 exit codes | 3 (SGT2, SGT4, SGT5, SGT6, SGT12) |
| SG6 `main` and the signals | 3 (`main`, `__main__`; SGT12) |
| SG7 output lines | 3 (`say`, `error`; SGT2) |
| SG8 canvas | 3 (`canvas`; SGT1); 6 (`seedCanvas`; Review Focus 5) |
| SG9 source refusals | 3 (`read_source`; SGT6) |
| SG10 byte copy, `work/source.png` | 3 (`prepare_source`; SGT6, Review Focus 3's samefile path) |
| SG11 run.json | 3 (`new_record`; SGT2) |
| SG12 write order | 3 (`run`, `finish`, `refuse`, `cleanup`, `main`; SGT2, SGT4, SGT6, SGT7, SGT12) |
| SG13 preflight | 3 (`preflight`, `wait_for_memory`; SGT7) |
| SG14 checks and the Qwen choice | 3 (`missing_modules` ... `choose_qwen`; SGT8, SGT13) |
| SG15 probe | 3 (`probe`; SGT13) |
| SG16 candidate lines | 3 (`finish`, `fail_rest`; SGT2-SGT4, SGT10) |
| SG17 failure texts | 3 (`run`, `run_qwen_child`; SGT4, SGT10) |
| SG18 Z-Image | 3 (`run_zimage`; SGT2-SGT4, SGT12) |
| SG19 diffusers bf16 | 3 (`run_bf16`; SGT11, Review Focus 4) |
| SG20 mflux q4 | 3 (`run_mflux`; SGT9, Review Focus 4) |
| SG21 `run_child` | 3 (SGT9, SGT10, Review Focus 4) |
| SG22 one load per job | 3 (one child start: SGT9, SGT11; Z-Image's singleton) |
| SG23 environment, docstring | 3 (the docstring; the variables in SGT8, SGT9, SGT11) |
| SG24-SG27 the mflux child | 4 (SGT15) |
| SG28 `job_vlm` | 2 (SGT18); 5 (SGT23 `vlm` forbidden) |
| SG29 `seed_edit_argv` | 2 (SGT18); 5 (SGT23); 3 (Review Focus 3) |
| SG30 `seed_edit_check` | 2 (SGT19); 5 (SGT22, SGT31) |
| SG31, SG32 progress | 2 (SGT18); 6 (`renderSeedRun`, `renderProgress`) |
| SG33 request rules | 1 (SGT17); 5 (SGT21) |
| SG34 folder rule | 1 (SGT17); 5 (SGT28, SGT30) |
| SG35 run ID, keep names | 1 (SGT17); 5 (SGT23, SGT28) |
| SG36 capability shape | 1 (SGT17); 5 (SGT31) |
| SG37 availability errors | 1 (SGT17); 5 (SGT22) |
| SG38 the capability | 5 (3.5, 3.6; SGT31) |
| SG39 cadence | 5 (no periodic probe; one probe per create: SGT22) |
| SG40 routes | 5 (3.3, 3.4, 3.9; SGT20) |
| SG41 `SEEDS_LOCK`, roots, `seed_free_gib` | 5 (3.2, 3.9; SGT22, SGT28, Review Focus 2) |
| SG42 run lookup | 5 (`_seed_run`, `_candidates`, `_cand_file`; SGT27, SGT28) |
| SG43 run state and view | 5 (`run_state`, `run_view`; SGT23, SGT26, SGT27) |
| SG44 create | 5 (`_seed_source`, `_h_seed_run_create`; SGT21-SGT25, Review Focus 1) |
| SG45 400/409 create nothing | 5 (SGT21, SGT22) |
| SG46 `seed_run` | 5 (3.7; SGT23, SGT32) |
| SG47 runs list | 5 (`_h_seed_runs`; SGT26) |
| SG48 run view route | 5 (`_h_seed_run`; SGT27) |
| SG49 folders | 5 (`_h_seed_folders`; SGT30) |
| SG50, SG51 Keep | 5 (`_h_seed_keep`; SGT28, Review Focus 2) |
| SG52 Use | 5 (`_h_seed_use`; SGT29) |
| SG53 `store_upload` | 5 (3.8; SGT29) |
| SG54 tab | 6 (3.1, 3.8, 3.9; SGT33); V2 item 1 |
| SG55 panel | 6 (3.2; SGT33) |
| SG56 state, DOM rules | 6 (3.4; SGT33's pattern scan) |
| SG57 functions | 6 (3.14; SGT33) |
| SG58 source | 6 (`setSeedSource`, `onSeedSourceFile`, the load listener); V2 items 2, 8, 9 |
| SG59 gating | 6 (`updateSeedButtons`, 3.6); V2 items 1, 2, 10 |
| SG60 Generate | 6 (`seedBody`, `generateSeeds`); V2 item 3 |
| SG61 run grid | 6 (`openSeedRun`, `pollSeedRun`, `renderSeedRun`, `seedRow`); V2 items 3, 5 |
| SG62 actions | 6 (`keepSeed`, `useSeed`, `editSeedAgain`); V2 items 6-8 |
| SG63 lists | 6 (`loadSeeds`, `loadSeedRuns`, `loadSeedFolders`, `copySeedPath`); V2 items 4, 6 |
| SG64 Characters, Jobs, polling, workspace | 6 (3.5, 3.7, 3.10-3.13; SGT33); V2 items 3, 9 |
| SG65 CSS | 6 (3.15; SGT33) |
| SG66-SG69 setup | 4 (SGT16); V4 |
| §8 error table | 3 (tool texts), 5 (route texts), 6 (page texts) |
| §9.2 re-baseline | 7 (Step 3; plus PR2's edit) |
| §9.3 browser check | V2 |
| §9.4 live checks | V4 (L1), V5 (L2), V6 (L3) |
| §10 pass bar | V1 (items 1-3), V2 (item 4), V4-V6 (item 5) |
| §11 rollout | Before Task 1 (snapshot, baseline); 1-6 (feature commits); 7 (test-only commit); V1-V6 |
| G1-G8 | G1 3; G2 4; G3 4; G4 1; G5 2; G6 5; G7 6; G8 1-7 |

### Test IDs and their owning task (each is owned by exactly one task)

| IDs | Task | Cases |
|---|---|---|
| SGT17 | 1 | 37 (33 request cases, four tests) |
| SGT18, SGT19 | 2 | 2 |
| SGT1-SGT14, Review Focus 3, 4 | 3 | 33 (SGT5 17, SGT2 2, the other 12 SGT IDs 1 each, Review Focus 3 and 4) |
| SGT15, SGT16 | 4 | 2 |
| SGT20-SGT32, Review Focus 1, 2 | 5 | 15 |
| SGT33, Review Focus 5 | 6 | 2 |
| SGT34 | 7 | 1 |
| the spec 9.2 re-baselines (and PR2's) | 7 | (existing tests) |

Totals: 92 new cases: 35 in `tests/test_seed_edit_tool.py` and 57 in `tests/test_movie_ui_seedgen.py` (87 SGT cases and 5 Review Focus pins). Cumulative after each task: 37, 39, 72, 74, 89, 91, 92.

### Self-review

- **Spec coverage.** Every requirement SG1-SG69 maps to a task in the table above, every test SGT1-SGT34 has real test code in its owning task, and §8, §9.2, §9.3, §9.4, §10 and §11 each have a step.
- **Placeholders.** The only symbolic values are `$S`, `$D`, `WS` and `N` (the gate block), each defined in its block or in the house rules. No step says "add error handling", "TBD" or "similar to Task N". Every Edit names its old text, which occurs exactly once at its turn, with or without its last newline (checked by replay).
- **Type and name consistency.** These names appear with the same signature everywhere they are used:
  - `seedgen.validate_run_request(body) -> (clean, error)` with Task 1's `clean` keys (Tasks 1, 3, 5);
  - `lib.seed_edit_argv(fields, ws_real, py=...)` with the nine field keys of SG44 (Tasks 2, 3, 5); `lib.seed_edit_check(ws_real) -> (models, detail)` (Tasks 2, 5);
  - the tool's `canvas`, `choose_qwen(paths=None)`, `mflux_problem() -> (problem, q4_dir, lora_file)`, `mflux_version(venv) -> (count, best)`, `find_lightning(hubs)`, `probe()` (Tasks 3, 4, 6);
  - the candidate lines (`candidate <i>/<N> ok <s.s>s` ...) between the tool (Task 3), `SEED_CAND_RE` (Task 2) and the page's `progress.candidates` (Task 6); the child lines `cand_NN.part.png <status> <s.s>s` and `seed-edit-child done <n> <s.s>` (Tasks 3, 4);
  - the run view keys of SG43 (Tasks 5, 6), the runs-list item keys of SG47 and the folders body of SG49 (Tasks 5, 6), `store_upload`'s record (Task 5, consumed by `useSeed` in Task 6).
- **Spec strings.** Every message of SG4, SG9, SG13, SG14, SG17, SG30, SG33, SG34, SG37, SG42-SG52, SG59, SG61-SG64 and SG67 is copied verbatim, including `—` (U+2014), `…` (U+2026), `·` (U+00B7), `×` (U+00D7) and `→` (U+2192). The plan adds only the texts its rulings name (PR7, PR12, PR19).
- **Review Focus.** Five inputs, each with a pinning test in its owning task (Tasks 5, 5, 3, 3 and 6).

## Plan rulings

**[defect]** rulings change behaviour from what the spec literally writes, or note a spec text that cannot work as written. **[reading]** rulings fill a detail the spec leaves open.

1. **PR1 [reading]: seven implementer tasks, one commit per task.** Spec 11 step 3's single feature commit becomes six task commits (Tasks 1-6), as in the prior plans. Spec 9.2 stays one test-only commit (Task 7), after every feature commit. The design review comes after the pass bar and the browser check, as spec 11 step 5 orders.
2. **PR2 [defect]: spec 9.2 misses `test_sdt19_the_seed_folder_tag`.** `tests/test_movie_ui_seedfolder.py:612` asserts `all(len(j) == 15 for j in queued)`; SG46's 16th key breaks it (measured on the replay). Spec 9.2's closing claim lists the pins it checked, and this count pin is not among them. Task 7 changes it to `== 16`, and the expected-failure list names it from Task 5.
3. **PR3 [defect]: SG44 step 5 `clean["seed"] or secrets.randbelow(...)` would replace a requested seed of 0 by a random seed.** 0 is a valid seed (SG33 row 9, SG4). `_h_seed_run_create` uses `clean["seed"] if clean["seed"] is not None else secrets.randbelow(seedgen.SEED_MAX + 1)`. SGT23 pins seed 0.
4. **PR4 [defect]: SG38's `models, detail = lib.seed_edit_check(...)` collides with `refresh_capabilities`' loop variable `detail`** (`for key, (ok, detail) in results.items()`), which would hand the last probe's detail to `seedgen.capability`. The pair is named `seed_models, seed_detail`.
5. **PR5 [defect]: SG60 never refreshes the buttons after `busy` returns to false.** As written, Generate stays disabled (showing the error, or nothing after a 201) until the next input event. `generateSeeds`'s `finally` sets `busy = false`, calls `updateSeedButtons()`, and then writes the error text (when there is one) into `#se-generate-reason`, so the error stays visible with Generate enabled.
6. **PR6 [reading]: SGT34 is written in Task 7.** It asserts `NEW_PY` membership, which only the spec 9.2 commit creates, and the gate never lets a new test fail. Task 7 adds SGT34 in its Step 1, so the commit stays test-only.
7. **PR7 [defect]: SG14 step 3 gives no text for a relative `SEED_EDIT_QWEN_Q4_DIR`,** and `lib.model_check(path, None)` raises `TypeError` for one (it joins `None` with the ID). The tool refuses it with `SEED_EDIT_QWEN_Q4_DIR <path>: not an absolute path` (the `<path>: <detail>` form of the same step). SGT8 pins it.
8. **PR8 [reading]: `choose_qwen(paths=None)`.** SG14 returns `(backend, why)` only, but the mflux backend needs the q4 directory and the Lightning file. When `paths` is a dict, a mflux-q4 choice also stores `q4_dir` and `lora_file` there; `preflight` passes one. No second scan, and `choose_qwen()` still returns SG14's pair.
9. **PR9 [reading]: when SG12 sets `source`, `size` and `source_size`.** The order inside SG12 step 2 is: read (SG9's format check), copy (SG10), canvas (SG8), save `work/source.png`. `source` is `"source.<ext>"` once the copy exists, else null; `size` and `source_size` are set together after the canvas passes, so both stay null on any SG8-SG10 refusal (spec SG11).
10. **PR10 [reading]: `--run-dir` is made absolute** (`os.path.abspath`) before it is created, printed and recorded; `run` is its basename.
11. **PR11 [reading]: `run_child` passes `encoding="utf-8", errors="replace"` with `text=True`,** so a child's stray byte cannot raise `UnicodeDecodeError` in the parent. Text mode keeps universal newlines, which split a progress bar's carriage returns into separate lines (Review Focus 4).
12. **PR12 [reading]: one failure path for backend exceptions.** `run_zimage` handles only `ContentSafetyError`; any other exception from a backend (a Z-Image crash, or a parent-side error while a child runs: moving a file, screening) reaches `run()`, which writes `<label> failed on candidate <i>: <ExcType>: <message>` with `<label>` from `BACKEND_LABELS` and `<i>` the first unfinished candidate, then fails the rest. For Z-Image this is exactly SG17's text. `run_child` kills the child's group whenever it exits early.
13. **PR13 [reading]: SG21's `-9` means the timeout text,** as the spec writes; a child SIGKILLed by anything else also reads `... child timed out after 3600 s`.
14. **PR14 [reading]: `mflux_version(venv)` returns `(count, best)`,** so the tool tells `mflux is not installed in <venv>` (no METADATA) from `cannot read the mflux version in <venv>` (none parses). `bin/seed-edit-setup` carries an identical copy (SG67 step 2); SGT16 pins the two functions' code equal.
15. **PR15 [reading]: SG30's shape check requires the keys `reason` and `backend` to be present** in each model entry (a missing key is unparsable output).
16. **PR16 [reading]: `stub_seed_edit(ws, models, exit=0, stderr="", sleep=0)`.** `sleep` serves SGT19's timeout case; a `str` `models` is printed as is (SGT19's `not json`).
17. **PR17 [reading]: the test docstrings paraphrase "never `load_module(`"** ("never the deprecated loader shortcut"), because spec 9.2 itself forbids that text in any `NEW_PY` file and `test_mut25` scans docstrings.
18. **PR18 [reading]: SGT33's `"unavailable — "` is a JavaScript string literal,** so `updateSeedButtons` builds both SG59 notes from `const off = "unavailable — ";`. The texts shown are SG59's.
19. **PR19 [reading]: the page's details.** The source image's `load` listener is registered once in `setupSeeds` and reads the current state; `setSeedSource` also clears `#se-source-size` until the new image loads. `openSeedRun` stops a running poll first, ignores a stale answer, and on a non-200 shows the run ID as the title and the error (`data.error` or `http <status>`) as the status. `seedRow`'s change key is the status, the path, and whether a pending candidate is the current one (so `generating…` replaces `waiting…`; a pending row has no folder input to lose). An `ok` candidate without a file shows `the image file is missing`. `keepSeed` and `useSeed` fall back to `http <status>` when the answer has no JSON. `loadSeeds` runs its two loads in sequence. `seedCanvas`'s `L` is named `longest`.
20. **PR20 [reading]: placements the spec leaves open.** The seven `SEED_*` constants directly after `SEED_COLLATOR`; the Seeds section directly before `// --- characters (MU82)`; the server section directly after the characters attach block; `_RUN` after `_ID` and `_SAMPLE_RUN` after `_SAMPLE_ID`; `SEED_CAND_RE` after `STILL_NAME_RE`; `showTab`'s two lines together after `stopBatchPoll`.
21. **PR21 [reading]: `chmod 755` for `bin/seed-edit` and `bin/seed-edit-setup`,** like every other `bin/` tool (git records `100755`). The movie-ui runs the tool through `sys.executable`, so only a hand run needs the mode.
22. **PR22 [reading]: the demo writes its URL (with its throwaway token) to a 0600 file instead of printing it** (controller rule: never print tokens), uses a stub `stills_py` so Re-check imports no torch, and reads the probe answer from `models.json` so item 10 needs no restart.
23. **PR23 [reading]: the HTTP `env` fixture also writes the `bin/seed-edit` stub (both models ok) and replaces `srv.seed_free_gib` by a 100 GiB stub;** a test that needs another answer rewrites the stub or patches again.
24. **PR24 [reading]: the Review Focus tests are named `test_sg_review_focus_N_...`,** unique in the suite.
25. **PR25 [reading]: Task 5's Step 2 shows 15 errors, not failures:** the `env` fixture's `monkeypatch.setattr(srv, "seed_free_gib", ...)` raises before the server code exists.
26. **PR26 [reading]: SGT8 covers more than its row lists:** `mflux is not installed`, `cannot read the mflux version`, a relative `SEED_EDIT_LIGHTNING_FILE`, a relative q4 directory (PR7) and a q4 directory without a `.safetensors` file.
27. **PR27 [reading]: in the bf16 and mflux line handlers, a line naming a candidate that is out of range or no longer pending is ignored.**
28. **PR28 [reading]: Keep reads the candidate's bytes before taking `SEEDS_LOCK`;** the lock covers `makedirs`, the inside check, the `O_EXCL` name claim and the write (SG50).
29. **PR29 [reading]: the live checks keep the spec's labels:** L1 setup, L2 Z-Image, L3 Qwen (Q1).
30. **PR30 [reading]: SGT30 creates a `runs` folder but not also `Runs`:** on this Mac's case-insensitive APFS volumes the two names are one directory. `Runs` is refused by `valid_folder` in SGT17 and over HTTP in SGT28.

## Questions for controller

1. **Q1 (live check labels).** The dispatch named the live checks "L1 Z-Image / L2 setup / L3 Qwen"; spec 9.4 and 11 step 6 name them L1 setup, L2 Z-Image, L3 Qwen (L3 after L1). The plan keeps the spec's labels and notes that L2 does not depend on L1, so it can run first on the user's go. Confirm, or say which order to record.
2. **Q2 (PR2).** Task 7 edits one existing test that spec 9.2 does not list (`test_sdt19_the_seed_folder_tag`, `== 15` to `== 16`). It is required for the pass bar. Accept the plan's edit, or amend the spec's 9.2 table first.

## Spec defects found (for the spec author)

1. Spec 9.2 misses `tests/test_movie_ui_seedfolder.py:612` (`len(j) == 15`), which SG46 breaks (PR2). The 0.1/9.2 claim "no other existing test pins ..." did not check summary key counts.
2. SG44 step 5's `clean["seed"] or secrets.randbelow(2147483648)` replaces a requested seed of 0 (PR3).
3. SG38's `models, detail` is shadowed by `refresh_capabilities`' loop variable `detail` (PR4).
4. SG60 sets `busy = false` with no button refresh, so Generate stays disabled after every request until the next input (PR5).
5. SG14 step 3 has no text for a relative `SEED_EDIT_QWEN_Q4_DIR`, and `lib.model_check(path, None)` raises `TypeError` for one (PR7).
6. SGT34 asserts `NEW_PY` membership, which only the test-only commit creates, so it cannot pass in a feature task (PR6).
7. Section 9's "never `load_module(`" in the test docstring rules conflicts with 9.2's own ban on that text in `NEW_PY` files (PR17).
8. SGT33 lists `"unavailable — "` with quotes, while SG59's texts embed it after a label; the page needs a separate literal (PR18).
9. Spec 9.3's demo sets the capabilities but not `server.stills_py`, so its Re-check (item 10) would run the stills probe, which imports torch and diffusers in a child (PR22).
10. Not changed, for the record: with `$CHARACTER_LIBRARY_DIR` outside `<ws>/generated`, `/files` refuses the still's path (403), so after New seed from this the thumbnail never loads and Generate stays at `loading the source image…`, although the server would accept the source. The Characters gallery already shows broken images in that setup. A fix would serve the library through `/files` or let the page skip the size gate; both are spec changes.

The spec's other claims were checked against the code: the 57 routes and `POST /api/uploads` at `:98`; `job_summary`'s 15 keys; `refresh_capabilities` and the capability shape; `_h_upload`'s body; `_inside`, `_json_in`, `_isfile_in`; `character_dataset.py`'s constants, `busy_process`, `child_qwenedit`'s per-job line and `main`; `z_image_skill.generate_variation`'s screening; `ProgressParser`'s structure; the three `TABS` pins and the `["jobs", "log", "host", "batch"]` pin; `test_mut25`'s scan and allow-list; `copy_ui`'s list; `make_hf_cache`'s layout; and every spec 9.2 edit's old text, each of which occurs exactly once in its file.

## Execution handoff

Plan complete and saved to `qwen-agent-workspace/docs/superpowers/plans/2026-11-02-seed-generator.md`.

**How it was checked.**
- **Data files.** Every Create and Edit of Tasks 1-7 lives in one block file, and this plan's code blocks are rendered from those files.
- **Edits.** A script replayed the operations in order on a scratch copy of `2b19b59`'s `WS` (`git archive`, never the worktree or the main checkout), checking every old text exactly once, with and without its last newline. Each occurred exactly once at its turn. Created `bin/` files got mode 755.
- **Fail first, then pass.** After each task's Step 1 alone, and after the whole task, the task's command gave the Step 2 and Step 4 results quoted in each task: `1 error`/`37 passed`, `2 failed, 37 passed`/`39 passed`, `1 failed, 32 errors`/`33 passed`, `2 failed, 33 passed`/`35 passed`, `39 passed, 15 errors`/`54 passed`, `2 failed, 54 passed`/`56 passed`, `1 failed, 56 passed`/`57 passed`. Task 7's re-baselined tests and SGT34 gave `11 failed, 2 passed` before and `13 passed` after (`test_mut15` not run; see below). Both new files gave `92 passed` three runs in a row.
- **HTTP tests without a socket.** The replay ran the Task 5 and 6 tests (and the existing movie-UI files) through a plan-only pytest plugin that drives the real `MovieUIHandler` over in-memory buffers instead of `mt.Running`'s 127.0.0.1 socket, so no server was started. The executor's run with the real in-test server is the authority.
- **The existing movie-UI tests.** Fifteen existing test files ("Between tasks") were run through the same plugin on the unmodified copy and after Tasks 4, 5, 6 and 7. The only differences were the expected-failure list's T5 and T6 lines (minus `test_mut15`), and after Task 7 none. Three `test_movie_ui_http.py` tests that open raw sockets failed identically on both copies under the plugin; they pass in the real baseline. `test_mut15`'s cause was confirmed by importing `movie_ui_server` from a copy made like `copy_ui`, with and without `movie_ui_seedgen.py`.
- **Compile.** Every new and changed Python file compiled under Python 3.9.6 and 3.13, `movie_ui_seedgen` ran under 3.9.6, and `node --check static/movie-ui/app.js` passed after Task 6.
- **The demo.** `demo.py`'s setup, with the server replaced by the plugin, served the page with the Seeds tab and answered the browser check's server side: the demo run's view and thumbnails, `kyra`'s two stills, a queued run from the 1536×1024 upload (position 1, `seed_run` set), two Keeps (`-01.png`, `-01-2.png`), the folders list, Use and the Compose preview's `--seed-image`, and `qwen_off.py` followed by a refresh.
- **Not run.** The full suite (the baseline is Before Task 1's files), `test_mut15`, the page's behaviour in a browser (V2), any real server, model, download or network, `bin/seed-edit-setup`, and the live checks.

Please review the plan. Which execution approach would you prefer?
- **Subagent-driven.** A fresh Sonnet `code-executor` implements each task in `$S/seedgen-wt` on branch `seed-generator`, and a fresh Opus reviewer checks it before the next one starts.
- **Native.** One session implements every task, then one fresh Opus reviewer checks the whole branch.

I recommend subagent-driven. Task 3 consumes Tasks 1 and 2 (Review Focus 3), Task 5 consumes Tasks 1 and 2, and Task 6 consumes Task 5's bodies and Task 3's canvas rule, so a reviewer gate between them catches a drift early. Answer Q1 before Verification and Q2 before Task 7.
