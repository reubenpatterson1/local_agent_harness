# Batch Forks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bulk re-runs of stories to compare settings. The user ticks stories on the Stories tab, describes 1-6 variants (setting changes and prompt edits), and submits a batch. Each story × variant cell becomes a new fork story that copies only what its change level allows (Render, New stills or Re-plan). The fork runs as an ordinary movie job, queued Re-plan first, then New stills, then Render. A batch page plays a story's original and forks side by side.

**Architecture:**
- **`movie_ui_batch.py` (Task 1, new, pure).** The constants, the request check, the classification table, merge, prompt edits, the cell plan (`plan_cells`, with V1 and the fork-directory check passed in), fork IDs and numbers, the copy plan, the submit order, the totals, the eligibility texts and `fork_fallback`. It never writes.
- **`movie_ui_server.py` (Tasks 2-4).**
  - Task 2: `BATCH_LOCK`, the batch-record readers, the one-pass job index, `stored_fields`, `story_status`, `plan_batch`, and the `stories` and `preview` routes. `movie_ui_lib.STATE_SUBDIRS` gains `"batches"` here too.
  - Task 3: submit, the batch submitter thread (BF28's nine steps), `remove_fork`, `reconcile`, the batch view, and the list, create and detail routes.
  - Task 4: cancel, restart recovery, submit remaining, delete, and the job-cancel hook.
- **The page (Task 5).** The Stories checkbox column, the Batches tab with the editor and the batch page in `index.html` and `app.js`, and the level badge styles in `app.css`.
- **Task 6** is the whole-branch review, then the one test-only re-baseline commit of spec 7.1, then BK1-BK8 and the hand-off.
- **Tests:**
  - New files: `tests/test_movie_ui_batch.py` (BT1-BT13, BT31) and the helper `tests/batch_testutil.py`.
  - Appended to existing files: `tests/test_movie_ui_http.py` (BT14-BT27, BT29, BT32-BT35), `tests/test_movie_ui_jobs.py` (BT28) and `tests/test_vlm_lifecycle.py` (BT30).
  - Five Review Focus pins.
  - In all, 82 test cases: 77 BT cases and 5 Review Focus pins.

**Tech Stack:**
- Python 3.13 (`python3` = `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`, pytest 8.3.4). Python 3.9.6 (`/usr/bin/python3`) is used for the compile check only. Every new and changed Python file runs on both.
- `movie_ui_batch.py`, `movie_ui_lib.py` and `movie_ui_server.py` stay standard library only. The page is vanilla ES2017 with no modules.
- Test helpers: `tests/movie_ui_testutil.py` (`set_home`, `make_stub_workspace`, `Running`, `api`, `make_job`, `dispatch`, `fields`, `stub_config`, `stub_calls`, `status_of`, `wait_until`, `kill_everything`, `PNG`) and the new `tests/batch_testutil.py`. `node --check` checks `app.js` when `node` is installed (BT13; this Mac has `/opt/homebrew/bin/node`).

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-10-30-batch-forks-design.md`, committed at `d505e55` on `bulk-rerun`.
- Its code citations are at `574303a`. `d505e55` and its parent `709e8ae` add only the spec, so the code tree is `574303a`'s.
- The user approved the design section by section (spec Status) and resolved Q1-Q3 (spec 11). The spec is binding.
- This plan changes behaviour only where the spec's text and its own tests, or the repository's existing tests, cannot both hold. Each such case is a numbered ruling in "Plan rulings", marked **[defect]**. The other rulings fill a detail the spec leaves open and are marked **[reading]**.

## Global Constraints

From the spec, verbatim (section in brackets):

- [Status] "Every detail the notes leave open is decided here and marked **[spec choice]** with its reason. The implementer makes no design decisions."
- [0.2] "Untouched: every pipeline file, including `bin/ltx-movie`, `story_engine.py`, `bin/ltx-story-images`, `bin/ltx-story-manifest` and `bin/ltx-mlx-render`. `test_mut26` passes unedited."
- [0.3 Out of scope] "Batches across workspaces. Editing a submitted batch. Retrying refused cells automatically. Forking command-line stories. Diffing story.md between forks. Any VLM scheduling beyond the group order. Pipeline changes."
- [0.4] "Every BF requirement and every BT test is a must-have. There are no nice-to-haves."
- [BF1] "`movie_ui_batch.py` imports only `json`, `os`, `re`, `stat` and `movie_ui_lib`. It is Python 3.9-compatible and never writes. Its functions are pure, except `copy_plan`, which lists the original read-only."
- [BF2] "**Lock rule [spec choice]:** `BATCH_LOCK` and `STORE_LOCK` are never held together, and `BATCH_LOCK` is held only for a `batch.json` read-modify-write and for the planning step of submit (BF24, so two submits cannot draw the same number)."
- [BF3] "`<STATE>/batches/<batch-id>/batch.json` is written with `lib.write_json_atomic` (mode 0600), in directories made with `lib.make_dir` (mode 0700). `"batches"` is appended to `STATE_SUBDIRS`."
- [1.1] The constants: `BATCH_SCHEMA = "movie-ui.batch.v1"`, `FORK_SCHEMA = "movie-ui.fork.v1"`, `MAX_VARIANTS = 6`, `MAX_CELLS = 24`, `MAX_REPLACES = 10`, `LABEL_MAX = 24`, `PROMPT_MAX = lib.NARRATIVE_MAX`, `STORY_ID_MAX = 80`, `MIN_FREE_BYTES = 20 * 1024 ** 3`, `LEVELS = ("render", "stills", "replan")`, `LEVEL_LABELS = {"render": "Render", "stills": "New stills", "replan": "Re-plan"}`, `FIXED_KEYS = ("ws", "action", "story_id", "overwrite_movie", "redo")`, `GROUPS = (("panels", "length"), ("width", "height", "seed_upload"))`, `FORK_SUFFIX_RE = re.compile(r"-b([0-9]+)-v[0-9]+$")`; `app.js`: `BATCH_POLL_MS = 2000`.
- [5] "Rules: no inline handlers or styles, no `prompt(`/`alert(`/`confirm(`/`eval(` and no second `<script>` (`test_mut24`, `tests/test_movie_ui_http.py:1035-1040`). Confirmations go through `askConfirm`. The `Promise.all` line of `selectWorkspace` (`app.js:264`) is unchanged, because `test_lu13` pins it."
- [7 Rules] "Every test uses `mt.set_home`, `mt.make_stub_workspace` and the in-test `mt.Running` server on 127.0.0.1. Originals are made with `make_job(..., status={"state": "done", ...})` so that they have `last_fields`. `lib.run_checks` is monkeypatched to return pass or a given failure, except in BT26, where it is wrapped. Batch HTTP tests post, then wait with `mt.wait_until(..., 30)` until `GET /api/batches/<id>` reports status `submitted` (or the state under test). The submitter thread started by the route does the work; tests never call `_batch_submitter` directly. Nothing renders, no test contacts a real server, and none touches port 8178. `conftest.py` keeps the VLM lifecycle off."
- [7.1] The only edits to existing tests, in one test-only commit after the feature: `test_mut18` (`== 46` becomes `== 54`), `test_lu1` (the same), `test_lu13` (the `TABS` string gains `"batches", ` after `"stories", `), `test_movie_ui_builder.py` `NEW_PY` (gains `"movie_ui_batch.py"` and `"tests/test_movie_ui_batch.py"` at the end), `test_mut25_source_scan_of_new_python_files` (the `allowed` set gains `"movie_ui_batch"`), `tests/movie_ui_testutil.py::copy_ui` (the copied list gains `"movie_ui_batch.py"`).
- [8] The KPIs, verbatim:

| ID | Criterion | Verified by |
|---|---|---|
| BK1 | Every `DEFAULT_FIELDS` key is classified exactly as in §2.1 | BT1 |
| BK2 | An original story directory is byte-identical (sha256 of every file) before and after a batch whose forks ran on the stub | BT25 |
| BK3 | A Render fork's stub run sees the copied story and stills unchanged, and its argv differs from the original's only in the story ID and the changed flags | BT24 |
| BK4 | The queue order is Re-plan → New stills → Render, then by story and then by variant, after the existing queue | BT10, BT17 |
| BK5 | Refused, interrupted and cancelled-before-start cells leave no fork folder | BT18, BT23, BT27, BT28 |
| BK6 | `test_mut26_pipeline_files_are_unchanged` passes unedited | full run |
| BK7 | `python3 -m pytest tests/ -q -rA` from `WS` shows exactly the baseline failures recorded at `574303a` before any edit, and the pass count is the baseline plus every BT test. The only edits to existing tests are §7.1, in one test-only commit | full run before and after |
| BK8 | A fork with no job is eligible exactly when its `fork.json` and batch cell match (BF41c), and then uses the cell's submitted fields; `last_fields` always wins; a deleted batch or a mismatched record leaves it ineligible with the exact §6 texts | BT31, BT32, BT33, BT34, BT35 |

- [9 Rollout] "1. Snapshot `WS` (house rule): `tar czf <scratchpad>/snapshot-pre-batch-574303a.tgz`, excluding `generated/`. 2. At `574303a`, record the full-suite pass count and failure list. 3. Make the feature commit: G1-G4 plus the BT tests. 4. Make the test-only commit (§7.1). 5. Run BK1-BK8, then an Opus design review of the diff against this spec." Step 3's single feature commit is split into one commit per task (Plan ruling BR1). The design review comes before the test-only commit, as in the prior plans (Task 6).
- [8] "Live check after the merge (not a merge gate): 1 story × 2 Render variants on the user's machine, with both forks playing in the compare page and Play row starting them together. Never on macstudio."

Controller rules, verbatim. Every task's requirements include them:

- Tests never use the real HOME, never render, and never contact servers. An in-test 127.0.0.1 movie-UI server is allowed.
- Never touch port 8178.
- Never read ~/.zshenv or fleet.env.
- No access to the macstudio host.
- Pipeline files unchanged, so test_mut26 holds.
- Edit tool for tracked files.
- Never stage .DS_Store, .claude/, agent/__pycache__/, repo-root bin/, qwen-agent-workspace/bin/action-from-dir, pin-sh2.json, story_bible_pin-sh2.json or .superpowers/.
- Commit trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>".
- Never push.

House rules (from the prior plans; every task's requirements include them):

- **Where work happens.**
  - This Mac only. Use no ssh, scp, rsync, curl or HTTP to any other host, and never touch macstudio. Use no network.
  - The movie-UI tests start servers on `127.0.0.1` inside the test; nothing else listens.
  - Never start, stop or contact a model server (`:8177`, `:8178`). Never render, train, or load a model. The only jobs that run are the stub workspace's `bin/ltx-movie`.
  - Never cat, grep, read or source `~/.zshenv` or any `fleet.env`, and never print env values.
- **The checkout.** Never touch the main checkout `/Users/reubenpatterson/local_agent_harness`. Every command runs in the worktree `$S/bulk-wt`, on branch `bulk-rerun`. Never git stash, reset or check out other people's work.
- **Python.** Every new or changed file must run on Python 3.9.6 and 3.13. So use none of: the `match` statement, `X | Y` type expressions, the walrus operator, `str.removeprefix`, `zip(strict=)` and parenthesised context managers. The code blocks below use none of them.
- **Editing.**
  - Executors make every change to a tracked file with the Edit tool. Each new file is created with the Write tool in the step that names it, and edited with the Edit tool from then on.
  - Never use `rm`, `sed -i`, a redirect or a script to change a tracked file.
- **Git.**
  - Stage only the paths a task names, and check `git diff --cached --name-only` before every commit.
  - Every commit command passes the trailer as a second `-m`. No task pushes. Push is a separate step that needs the user's approval.
- **Paths.**
  - `S` = `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`.
  - `WS` = `$S/bulk-wt/qwen-agent-workspace`, and `D` = `$S/bulk-baseline`.
  - The git root is `$S/bulk-wt`, so `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix.
  - Run every command from `WS`. Shell variables do not persist between commands, so every block defines the variables it uses.
- **Code blocks** are copied byte for byte.
  - An Edit step's old text must occur exactly once in the file at that moment, with or without its last newline. If it does not, stop and report; do not adapt it.
  - Every Create and Edit below was replayed in order on a scratch copy of `574303a`'s `WS`. Each old text occurred exactly once at its turn (see "Execution handoff").
- **The compile check** (Step 4 of each code task) is this command, with the task's Python files as `FILES`. Expected: two lines, `compiled N` for 3.9 and then for 3.13.

```bash
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' FILES; done
```

## Review Focus

These five inputs and failure modes are the ones most likely to reach a user first, and no BT row exercises them. Each is pinned by a test in the task that owns its code. The tests are named `test_batch_review_focus_N_...`, because `tests/test_movie_ui_http.py` already has `test_review_focus_1` to `_5` (Plan ruling BR20).

1. **Accents and symbols in a label, a find/replace pair and an appended paragraph** (`café ☕`, `l’aube`, an em dash).
   - The text passes through the request check, `batch.json`, `fork.json`, the job's fields and its argv.
   - Expected: every copy holds the exact text, and the cell's diff shows the edited narrative.
   - Test: `test_batch_review_focus_1_non_ascii_labels_and_prompt_edits` (Task 3).
2. **An original whose saved settings no longer pass V1.** For example, its seed image upload was removed from `STATE/uploads`.
   - Expected: the preview shows the cell `invalid` with V1's own line (`seed image upload <id> not found`). The totals count it refused, the preview writes nothing, and `rows[0].fields` still shows the saved settings.
   - Test: `test_batch_review_focus_2_saved_settings_that_no_longer_pass_v1` (Task 2).
3. **Two submits of the same story at once** (a double click, or two tabs).
   - Without `BATCH_LOCK` both batches would draw number 1, and the second fork's `mkdir` would fail.
   - Expected: two batches numbered 1 and 2, with forks `ronin-rescue-b1-v1` and `ronin-rescue-b2-v1`, both queued.
   - Test: `test_batch_review_focus_3_two_batches_submitted_at_once` (Task 3).
4. **Another workspace** (the Workspace selector names another release).
   - Expected: `GET /api/batches?ws=` lists only that workspace's batches. Its numbering ignores the other workspace's records, so its first batch is number 1 with fork `-b1-v1`.
   - Test: `test_batch_review_focus_4_batches_are_per_workspace` (Task 3).
5. **An original whose `images/` and `clips/` are symlinks to a shared folder.**
   - Spec 2.6 skips symlinked files, but listing a symlinked directory would still copy regular files from outside the story.
   - Expected: `copy_plan` reads `images/` and `clips/` only when they are real directories, so the plan lists only the top-level files (Plan ruling BR12).
   - Test: `test_batch_review_focus_5_symlinked_images_and_clips_directories` (Task 1).

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `movie_ui_batch.py` | Create (Task 1) | The batch forks core: constants, `validate_request`, `FIELD_LEVELS`, `original_fields`, `edit_prompt`, `merge`, `argv_of`, `classify`, `fork_id`, `next_number`, `no_fields_reason`, `eligibility_reason`, `plan_cells`, `totals`, `submit_order`, `copy_plan`, `fork_fallback`. Never writes. |
| `movie_ui_lib.py` | Modify (Task 2) | `STATE_SUBDIRS` gains `"batches"`. |
| `movie_ui_server.py` | Modify (Tasks 2, 3, 4) | `import movie_ui_batch as batch` and `shutil`; `BATCH_LOCK`; `batch_queue`/`batch_thread`; 8 routes; the records, eligibility, planning and preview (T2); submit, the submitter, `remove_fork`, `reconcile`, the view (T3); cancel, `batch_recovery`, resume, delete, the job-cancel hook (T4). |
| `static/movie-ui/index.html`, `app.js`, `app.css` | Modify (Task 5) | The Stories checkbox column and `New batch (N)`, the Batches tab (list, editor, batch page), the prompt dialog, the level badges and chips. |
| `tests/test_movie_ui_batch.py` | Create (Task 1), extend (Task 5) | BT1-BT12, BT31, Review Focus 5 (T1); BT13 (T5). |
| `tests/batch_testutil.py` | Create (Task 2) | `original`, `variant`, `body`, `passing_checks`, `submit`, `wait_status`, `record`, `tree_digests`, `run_job`. |
| `tests/test_movie_ui_http.py` | Extend (Tasks 2, 3, 4), re-baseline (Task 6) | BT15, Review Focus 2 (T2); BT16-BT19, BT22-BT26, BT32-BT34, Review Focus 1, 3, 4 (T3); BT14, BT20, BT21, BT27, BT29, BT35 (T4); `test_mut18` (T6). |
| `tests/test_vlm_lifecycle.py` | Extend (Task 3) | BT30. |
| `tests/test_movie_ui_jobs.py` | Extend (Task 4) | BT28. |
| `tests/test_location_ui.py`, `tests/test_movie_ui_builder.py`, `tests/movie_ui_testutil.py` | Modify (Task 6 only) | The spec 7.1 re-baseline. |

**Task split.** The suggested split was seven tasks, with the routes in their own task. The routes are about one line each and wrap the server functions. Every spec test from BT14 on is an HTTP test of a route, so a routes-only task would leave Tasks 2-4 with no spec tests. So each server task ships its routes with its tests (Plan ruling BR1):
- Task 1 is the pure core.
- Task 2 is read-only (eligibility and the preview).
- Task 3 writes (submit and the submitter).
- Task 4 undoes (cancel, restart, delete).
- Task 5 is the page.
- Task 6 is the review, the test-only re-baseline and the KPIs.

A reviewer can reject any one of them on its own diff.

## Between tasks: the existing suite (approach B, and why)

**The choice.** Feature tasks do **not** edit the existing tests whose assertions the feature changes. These are the six edits of spec 7.1:
- `test_mut18` and `test_lu1` (the route count), `test_lu13` (the `TABS` string), `NEW_PY` and `test_mut25_source_scan_of_new_python_files` (the allowed imports);
- `copy_ui`, a helper that `test_mut15` uses.

They stay red from the task that first breaks them until Task 6's one test-only commit, as the spec (7.1, BK7) requires. Every other existing test must stay green in every task.

New tests are appended to existing test files (spec 7's table names the files). Each of those files gains one import line, `import batch_testutil as bt`. Those additions edit no existing test (Plan ruling BR19).

**Precision.** The list below was measured on the plan's replay. After Task 5, every movie-UI test file and every other test file that imports the movie-UI modules was run (see "Execution handoff"). Exactly these five existing tests failed:

| Code | Cause | First task |
|---|---|---|
| R54 | `test_mut18_every_api_route_needs_the_token` and `test_lu1_the_location_routes_need_the_token`: `ROUTES` has 48 entries after Task 2, 51 after Task 3 and 54 after Task 4, not 46 | 2 |
| IMP | `test_mut25_source_scan_of_new_python_files`: `movie_ui_server.py` imports `movie_ui_batch`, which the `allowed` set lacks | 2 |
| CPY | `test_mut15_bin_movie_ui_lock_port_and_startup_lines`: `copy_ui` does not copy `movie_ui_batch.py`, so the copied `bin/movie-ui` cannot import `movie_ui_server` and prints nothing | 2 |
| TABS | `test_lu13_the_static_page`: `TABS` gains `"batches"` | 5 |

The expected-failure list, written to `$D/expected-failures.txt` in "Before Task 1" Step 3. A line is `T<first task> <node id> <code>`.

```text
# batch forks plan: existing tests expected to fail from the given task until Task 6
T2 tests/test_movie_ui_http.py::test_mut18_every_api_route_needs_the_token R54
T2 tests/test_location_ui.py::test_lu1_the_location_routes_need_the_token R54
T2 tests/test_movie_ui_builder.py::test_mut25_source_scan_of_new_python_files IMP
T2 tests/test_movie_ui_jobs.py::test_mut15_bin_movie_ui_lock_port_and_startup_lines CPY
T5 tests/test_location_ui.py::test_lu13_the_static_page TABS
```

**Gate rule** (Step 4 of every code task):
1. Every new test passes. A new test is one in `tests/test_movie_ui_batch.py`, or any test ID the baseline does not have.
2. The baseline failures fail with the same messages.
3. Every lost baseline pass is listed for a task at or before this one in `$D/expected-failures.txt`.
4. `tests/test_ltx_movie_offline.py` prints the same last line as at the baseline.

**When the gate prints `GATE STOP`:**
- The executor stops and reports the UNEXPECTED or NEW-TEST-FAIL IDs, together with the output of `python3 -B -m pytest -q -p no:cacheprovider --tb=short <ids>`.
- The controller has an Opus reviewer rule on each ID. A lost pass that the list does not name is a defect in this task's code. The controller writes the exact fix, and the gate reruns.
- The list grows only for the timing-sensitive tests below.

**Timing-sensitive tests unrelated to this plan.** These are `tests/test_fleet_tracing.py::test_trt41a_trace_cli_on_one_agent` and `tests/test_fleet_integration.py::test_t47_signatures_and_loopback_rules`. The second failed in the location plan's final run but not in its baseline.
- If the gate lists one of them as UNEXPECTED, rerun it alone with `python3 -B -m pytest -q -p no:cacheprovider <node id>`.
- If it passes alone, the controller appends `T<N> <node id> flaky` to `$D/expected-failures.txt`, and Task 6 rechecks it.

**Must stay green in every task:** every `tests/test_movie_ui_*.py` test other than the three listed; every `tests/test_location_ui.py` test other than `test_lu1` and `test_lu13`; `tests/test_vlm_lifecycle.py`, `tests/test_location_lib.py`, `tests/test_model_download.py` and `tests/test_soft_panel_count.py`. None is in the list, so a failure there stops the gate.

---

## Before Task 1: the plan commit, the snapshot, the baseline (controller; no code)

- [ ] **Step 1: Confirm the plan commit and the tree.**

The controller commits this plan on `bulk-rerun` as `docs(plan): batch forks implementation plan`, directly on top of the spec commit `d505e55`.

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/bulk-wt/qwen-agent-workspace
git branch --show-current                                   # expected: bulk-rerun
git log -4 --format=%h' '%s                                 # expected: <plan sha> docs(plan): batch forks implementation plan, then d505e55, 709e8ae, 574303a
git diff --stat 574303a HEAD -- . ':(exclude)docs' | tail -1   # expected: no output
git status --short                                          # expected: no output
ls movie_ui_batch.py tests/test_movie_ui_batch.py tests/batch_testutil.py 2>&1 | grep -c "No such file"   # expected: 3
wc -l movie_ui_lib.py movie_ui_server.py static/movie-ui/index.html static/movie-ui/app.js static/movie-ui/app.css tests/movie_ui_testutil.py tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_builder.py tests/test_movie_ui_jobs.py tests/test_vlm_lifecycle.py | tail -12
grep -c "44beb3d67ad5af05093e29e1c6fc088330b41386" tests/test_movie_ui_builder.py   # expected: 2
```

Expected `wc -l` counts (at `574303a`): `movie_ui_lib.py` 2285, `movie_ui_server.py` 2087, `index.html` 346, `app.js` 1696, `app.css` 87, `movie_ui_testutil.py` 552, `test_movie_ui_http.py` 1149, `test_location_ui.py` 425, `test_movie_ui_builder.py` 295, `test_movie_ui_jobs.py` 438, `test_vlm_lifecycle.py` 1113. If any value differs, stop and report: every Edit below was written against this tree.

- [ ] **Step 2: Take the compressed snapshot (house rule; spec 9 step 1).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
tar czf $S/snapshot-pre-batch-574303a.tgz --exclude qwen-agent-workspace/generated -C $S/bulk-wt qwen-agent-workspace
tar tzf $S/snapshot-pre-batch-574303a.tgz | grep -c '^qwen-agent-workspace/movie_ui_server.py$'   # expected: 1
```

- [ ] **Step 3: Record a fresh baseline and write the gate files (about 17 minutes; spec 9 step 2).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/bulk-baseline
mkdir -p $D
cd $S/bulk-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
grep -c '^PASSED ' $D/baseline-pytest.txt
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1 | tee $D/baseline-offline.txt
```

Expected: the plan did not run the full suite at `574303a`.
- The location plan's last full run, at its final commit, gave `3 failed, 2111 passed, 2 skipped`. The three failures were `test_character_dataset.py::test_d2_copied_literals_match_the_spike`, `test_fleet_integration.py::test_t47_signatures_and_loopback_rules` and `test_story_engine.py::test_rst62_import_sets`.
- `574303a` adds three location fixes with their tests, so the counts here differ.
- Whatever this run records **is** the baseline (BK7). Report its summary line, its `FAILED`/`ERROR` lines, the pass count and the offline line. Every later "baseline" in this plan means these files.

Then write two scratch files with the Write tool. They are outside the repository and never staged.

1. `$D/expected-failures.txt`: exactly the `text` block of "Between tasks" above.
2. `$D/gate.py`.
   - The location plan's `$S/loc-baseline/gate.py` does not fit as it is. Its `NEW_FILES` names the location test files, and it checks only new files, but this plan appends tests to existing files.
   - So write this adapted copy. It names `tests/test_movie_ui_batch.py` and counts every test ID that the baseline lacks as new. The print labels say "new tests".
   - Everything else is `loc-baseline/gate.py` unchanged.

```python
"""The task gate of the batch forks plan: a full pytest -rA run against the baseline. Adapted from
the location library plan's gate: a new test is one of the new file or any test ID the baseline
does not have, since the batch tests are also appended to existing files."""
import re
import sys

base_file, run_file, expected_file, task = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
NEW_FILES = ("tests/test_movie_ui_batch.py::",)


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
D=$S/bulk-baseline
N=1
cd $S/bulk-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/task-$N-pytest.txt 2>&1; tail -1 $D/task-$N-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/task-$N-pytest.txt $D/expected-failures.txt $N
diff <(python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1) $D/baseline-offline.txt && echo "offline unchanged"
```

Expected: `GATE PASS`, `new tests <count>, not passing 0`, `baseline failures still failing B of B` (B = the baseline's failure count), and `offline unchanged`. Each task's Step 4 gives its count and its `LOST ... listed` lines. On `GATE STOP`, follow the gate rule ("Between tasks").

---

### Task 1: `movie_ui_batch.py`, the pure core (BF1, BF4-BF17, BF27, BF41c; BT1-BT12, BT31, Review Focus 5)

This task implements:
- Spec 1.1 constants and the spec 2.1 table `FIELD_LEVELS` (BF4, BK1).
- `validate_request` (spec 3.2 and every 400 line of spec 6, in table order; Plan rulings BR6, BR7).
- `original_fields` and `merge` with the four group couplings (BF5).
- `edit_prompt` (BF6). A non-string text raises `TypeError`, so BF12 refuses it (Plan ruling BR14).
- `argv_of` and `classify`: BF7's identical test, BF8's probe diff and resolved-panels entry, BF9's levels and BF10's warning (Plan ruling BR5).
- `fork_id` and `next_number` (BF13, BF14).
- `plan_cells`: spec 3.6 steps 1-7 with BF11, BF12, BF13's and BF15's refusals. V1 and the fork-directory check are passed in, so the module does no I/O itself (Plan rulings BR2, BR4, BR8).
- `no_fields_reason` and `eligibility_reason` (the texts of spec 3.4 and 3.6).
- `totals` (spec 3.3) and `submit_order` (BF27).
- `copy_plan` (BF16, BF17; Plan ruling BR12).
- `fork_fallback` (BF41c).

Tests: BT1-BT12, BT31 and Review Focus 5 in the new `tests/test_movie_ui_batch.py`. Its imports of `re`, `shutil` and `subprocess` are for BT13, which Task 5 appends.

**Files:**
- Create: `movie_ui_batch.py`, `tests/test_movie_ui_batch.py`.
- Read only: `movie_ui_lib.py`:
  - `JOB_ID_RE` `:35`, `STORY_ID_RE` `:37`;
  - `DEFAULT_FIELDS` `:892-905`, `compose_fields` `:927-936`, `goal_text` `:939-945`, `build_argv` `:966-1023`;
  - `_rule_locations` `:1048-1067`, `NARRATIVE_MAX` `:1240`, `valid_story_id` `:1269-1271`, `resolved_panels` `:1274-1281`.

**Interfaces:**
- Consumes (existing, `movie_ui_lib`): `compose_fields(body) -> dict`, `build_argv(fields, ws_real, state, py=sys.executable) -> [str]`, `resolved_panels(fields) -> int or None`, `valid_story_id(story_id) -> bool`, `DEFAULT_FIELDS`, `NARRATIVE_MAX`, `JOB_ID_RE`, `DEFAULT_MODEL`.
- Produces, in `movie_ui_batch` (later tasks use these names exactly):
  - the spec 1.1 constants; `FIELD_LEVELS` (25 keys); `COPY_FILES`, `STILL_RE`, `CLIP_RE`, `NO_FIELDS`, `IDENTICAL`;
  - `validate_request(body) -> (clean, errors)`. `clean` is `{"stories": [str], "variants": [{"label", "settings", "prompt": {"append", "replace", "per_story"}}]}`;
  - `original_fields(last_fields, story_id, ws_real) -> dict`;
  - `edit_prompt(narrative, prompt, story_id) -> (str, [str])`;
  - `merge(last_fields, variant, story_id, fork_id, ws_real) -> (orig, fork, warnings)`;
  - `argv_of(fields, story_id, ws_real, state) -> [str]`;
  - `classify(orig, fork, story_id, ws_real, state, has_story) -> (level, diff, warnings)`;
  - `fork_id(story_id, n, m) -> str`, `next_number(batch_records, story_names, ws_real) -> int`;
  - `no_fields_reason(story_id, code, batch_id) -> str`, `eligibility_reason(busy_job, code, batch_id) -> str or None`;
  - `plan_cells(stories, variants, number, ws_real, state, originals, validate, exists) -> [cell]`:
    - each cell is `{"story_id", "variant", "fork_id", "status": "ok"/"refused"/"invalid", "reason", "level", "diff", "warnings", "fields"}`;
    - `originals[story_id]` is `{"dir", "has_story", "busy_job", "fields", "code", "batch", "number"}`;
    - `validate(fields) -> [str]` and `exists(fork_id) -> bool` are passed in;
  - `totals(cells) -> {"jobs", "replan", "stills", "render", "refused", "text"}`;
  - `submit_order(cells, stories) -> [int]` (over cells whose status is `"pending"`);
  - `copy_plan(sdir, level) -> [(relpath, bytes)]`;
  - `fork_fallback(fork_rec, batch_rec, story_id, ws_real) -> (code, fields, batch_id, number)`.

- [ ] **Step 1: Write the failing tests.**

Create `tests/test_movie_ui_batch.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""Tests for movie_ui_batch, the pure core of batch forks (docs/superpowers/specs/2026-10-30-batch-
forks-design.md, Section 7: BT1-BT12 and BT31, with the plan's Review Focus pin 5).

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_batch.py
Stdlib plus pytest. No test reads the real HOME, renders or contacts a server: the functions here
are pure or list a temporary directory, and V1 and the fork-directory check are passed in as fakes.
"""

import os
import re
import shutil
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import movie_ui_batch as batch  # noqa: E402
import movie_ui_lib as lib  # noqa: E402

WSR = "/abs/ws"
STATE = "/abs/state"
BID = "20261030-120501-ab12"
NARRATIVE = "A ronin rescues a child from a burning village at dusk."
LORA = {"id": None, "path": "/loras/free.safetensors", "strength": 0.7, "kind": None}
SEED = "a" * 64 + ".png"
EXPECTED_LEVELS = {
    "model": "render", "gemma": "render", "video_loras": "render", "action_loras": "render",
    "frames": "render", "fps": "render", "no_low_ram": "render", "panel_timeout": "render",
    "width": "stills", "height": "stills", "stills_loras": "stills", "location_strength": "stills",
    "narrative": "replan", "goal": "replan", "panels": "replan", "length": "replan",
    "seed_upload": "replan", "mode": "replan", "characters": "replan", "locations": "replan",
    "narration": "replan", "story_legacy": "replan", "story_model": "replan", "judge": "replan",
    "auto_lora": "replan",
}


def saved(**overrides):
    """A saved job's fields (last_fields) of a movie of story ronin-rescue."""
    fields = lib.compose_fields({"ws": WSR, "action": "movie", "story_id": "ronin-rescue",
                                 "narrative": NARRATIVE})
    fields.update(overrides)
    return fields


def variant(settings=None, append="", replace=(), per_story=None, label="v1"):
    return {"label": label, "settings": dict(settings or {}),
            "prompt": {"append": append, "replace": [{"find": f, "with": w} for f, w in replace],
                       "per_story": dict(per_story or {})}}


def info(fields="saved", has_story=True, busy_job=None, code="job", batch_id=None, exists_dir=True):
    return {"dir": exists_dir, "has_story": has_story, "busy_job": busy_job,
            "fields": saved() if fields == "saved" else fields, "code": code, "batch": batch_id,
            "number": None}


def plan(stories, variants, originals=None, number=3, errors=(), existing=()):
    """plan_cells with V1 returning errors and the fork directories in existing."""
    originals = originals or dict((s, info()) for s in stories)
    return batch.plan_cells(stories, variants, number, WSR, STATE, originals,
                            lambda fields: list(errors), lambda fork: fork in existing)


def one(settings=None, base=None, **kw):
    """The single cell of a 1 x 1 plan of ronin-rescue."""
    originals = {"ronin-rescue": info(fields=saved(**(base or {})))}
    return plan(["ronin-rescue"], [variant(settings, **kw)], originals)[0]


# --- BT1 (BK1): the classification table (spec 2.1) -----------------------------------------

def test_bt1_every_default_field_is_classified():
    assert set(batch.FIELD_LEVELS) | set(batch.FIXED_KEYS) == set(lib.DEFAULT_FIELDS)
    assert not set(batch.FIELD_LEVELS) & set(batch.FIXED_KEYS)
    assert (len(batch.FIELD_LEVELS), len(batch.FIXED_KEYS), len(lib.DEFAULT_FIELDS)) == (25, 5, 30)
    assert batch.FIELD_LEVELS == EXPECTED_LEVELS
    assert batch.LEVELS == ("render", "stills", "replan")
    assert batch.LEVEL_LABELS == {"render": "Render", "stills": "New stills", "replan": "Re-plan"}


ONE_KEY = [
    ("model", {"model": "/models/other"}, {}),
    ("gemma", {"gemma": "/models/gemma-other"}, {}),
    ("video_loras", {"video_loras": [LORA]}, {}),
    ("action_loras", {"action_loras": [{"name": "roundhouse-kick", "strength": None}]}, {}),
    ("frames", {"frames": 97}, {}),
    ("fps", {"fps": 30}, {}),
    ("no_low_ram", {"no_low_ram": True}, {}),
    ("panel_timeout", {"panel_timeout": 3600}, {}),
    ("width", {"width": 768}, {"width": 1024, "height": 576}),
    ("height", {"height": 512}, {"width": 1024, "height": 576}),
    ("stills_loras", {"stills_loras": [LORA]}, {}),
    ("location_strength", {"location_strength": 0.5}, {"locations": ["harbour-street"]}),
    ("narrative", None, {}),
    ("goal", {"goal": "Keep it tense."}, {}),
    ("panels", {"panels": 12}, {}),
    ("length", {"length": 60}, {}),
    ("seed_upload", {"seed_upload": SEED}, {}),
    ("mode", {"mode": "shots"}, {}),
    ("characters", {"characters": ["kyra"]}, {}),
    ("locations", {"locations": ["harbour-street"]}, {}),
    ("narration", {"narration": "none"}, {}),
    ("story_model", {"story_model": "qwen38"}, {}),
    ("story_legacy", {"story_legacy": True}, {}),
    ("judge", {"judge": True}, {}),
    ("auto_lora", {"auto_lora": False}, {}),
]


@pytest.mark.parametrize("key,settings,base", ONE_KEY, ids=[case[0] for case in ONE_KEY])
def test_bt1_a_one_key_change_gives_its_level(key, settings, base):
    cell = one(settings, base) if settings is not None else one(base=base, append="Snow falls.")
    assert cell["status"] == "ok", cell["reason"]
    assert key in [d["key"] for d in cell["diff"]]
    assert cell["level"] == EXPECTED_LEVELS[key]


# --- BT2: merge (spec 2.2) ------------------------------------------------------------------

def test_bt2_merge_defaults_fixed_keys_and_couplings():
    old = {"narrative": "N", "narration": False, "action": "story", "story_id": "x", "ws": "/elsewhere",
           "overwrite_movie": True, "redo": [3]}
    orig, fork, warnings = batch.merge(old, variant(), "ronin-rescue", "ronin-rescue-b3-v1", WSR)
    expected = lib.compose_fields({"narrative": "N"})
    expected.update(ws=WSR, action="movie", story_id="ronin-rescue", narration="none",
                    overwrite_movie=False, redo=[])
    assert (orig, warnings) == (expected, [])
    assert fork == dict(expected, story_id="ronin-rescue-b3-v1")
    assert batch.original_fields(old, "ronin-rescue", WSR) == expected
    assert batch.merge({"narration": True, "narrative": "N"}, variant(), "s1", None, WSR)[1]["narration"] == "full"
    assert batch.merge({"narrative": "N"}, variant(), "s1", None, WSR)[1]["story_id"] == "s1"
    sized = saved(width=1024, height=576)
    fork = batch.merge(sized, variant({"panels": 12}), "ronin-rescue", None, WSR)[1]
    assert (fork["panels"], fork["length"]) == (12, None)
    fork = batch.merge(sized, variant({"length": 60}), "ronin-rescue", None, WSR)[1]
    assert (fork["panels"], fork["length"]) == (None, 60)
    seeded = saved(seed_upload=SEED)
    fork = batch.merge(seeded, variant({"width": 768, "height": 512}), "ronin-rescue", None, WSR)[1]
    assert (fork["width"], fork["height"], fork["seed_upload"]) == (768, 512, None)
    fork = batch.merge(seeded, variant({"height": 512}), "ronin-rescue", None, WSR)[1]
    assert (fork["width"], fork["height"], fork["seed_upload"]) == (None, 512, None)
    fork = batch.merge(sized, variant({"seed_upload": SEED}), "ronin-rescue", None, WSR)[1]
    assert (fork["width"], fork["height"], fork["seed_upload"]) == (None, None, SEED)
    fork = batch.merge(sized, variant({"seed_upload": None}), "ronin-rescue", None, WSR)[1]
    assert (fork["width"], fork["height"], fork["seed_upload"]) == (1024, 576, None)
    loras = variant({"video_loras": [dict(LORA)]})
    fork = batch.merge(saved(), loras, "ronin-rescue", None, WSR)[1]
    loras["settings"]["video_loras"][0]["strength"] = 2
    assert fork["video_loras"] == [LORA]


# --- BT3: prompt edits (spec 2.3) -----------------------------------------------------------

def test_bt3_prompt_edits():
    prompt = {"append": "", "replace": [{"find": "dusk", "with": "dawn"},
                                         {"find": "dawn gate", "with": "east gate"}], "per_story": {}}
    assert batch.edit_prompt("dusk at the dusk gate", prompt, "s1") == ("dawn at the east gate", [])
    per = {"append": "  Snow falls.  ", "replace": [{"find": "dusk", "with": "dawn"}],
           "per_story": {"s1": "Per story dusk, then dusk.  \n"}}
    assert batch.edit_prompt("The narrative at dusk.", per, "s1") == (
        "Per story dawn, then dawn.\n\nSnow falls.", [])
    assert batch.edit_prompt("The narrative at dusk.", per, "s2") == (
        "The narrative at dawn.\n\nSnow falls.", [])
    missing = {"append": "", "replace": [{"find": "fog", "with": "rain"}], "per_story": {}}
    assert batch.edit_prompt("Clear skies.", missing, "s1") == (
        "Clear skies.", ['find text not in this prompt: "fog"'])
    blank = {"append": " \n ", "replace": [], "per_story": {}}
    assert batch.edit_prompt("Clear skies.  ", blank, "s1") == ("Clear skies.  ", [])
    long = {"append": "y" * 20, "replace": [], "per_story": {}}
    text, warnings = batch.edit_prompt("x" * 19990, long, "s1")
    assert len(text) == 20012 and warnings == ["edited prompt is 20012 characters; the limit is 20000"]
    with pytest.raises(TypeError):
        batch.edit_prompt(None, blank, "s1")


# --- BT4, BT5: identical and duplicate variants, no-op keys (BF7, BF8, BF11) -----------------

def test_bt4_identical_and_duplicate_variants():
    assert one()["reason"] == batch.IDENTICAL
    assert one({"location_strength": 0.5})["reason"] == batch.IDENTICAL
    assert one({"goal": "Keep it tense."}, base={"goal": "Keep it tense"})["reason"] == batch.IDENTICAL
    assert one(per_story={"ronin-rescue": "  " + NARRATIVE + "  \n"})["reason"] == batch.IDENTICAL
    assert one(append="   ")["reason"] == batch.IDENTICAL
    for cell in (one(), one({"location_strength": 0.5})):
        assert (cell["status"], cell["level"], cell["diff"]) == ("refused", None, [])
    cells = plan(["s1", "s2"], [variant({"model": "/models/other"}, label="first"),
                                variant({"model": "/models/other"}, label="second"),
                                variant({"model": "/models/third"}, label="third")])
    assert [(c["status"], c["reason"]) for c in cells] == [
        ("ok", None), ("refused", "same settings and prompt as variant 1 (first) for this story"), ("ok", None),
        ("ok", None), ("refused", "same settings and prompt as variant 1 (first) for this story"), ("ok", None)]


def test_bt5_a_no_op_key_is_dropped_from_the_diff_and_the_level():
    cell = one({"model": "/models/other", "location_strength": 0.5})
    assert cell["status"] == "ok" and cell["level"] == "render"
    assert cell["diff"] == [{"key": "model", "from": lib.DEFAULT_MODEL, "to": "/models/other"}]
    cell = one({"model": "/models/other", "goal": "Keep it tense."}, base={"goal": "Keep it tense"})
    assert [d["key"] for d in cell["diff"]] == ["model"] and cell["level"] == "render"


# --- BT6: a length-sized story and shorter clips (BF8, BF10) ---------------------------------

def test_bt6_resolved_panels_and_shorter_clips():
    sized = {"panels": None, "length": 60}
    moved = one({"frames": 153}, base=sized)
    assert moved["level"] == "replan"
    assert moved["diff"] == [{"key": "frames", "from": 145, "to": 153},
                             {"key": "panels", "from": 10, "to": 9, "note": "resolved from length"}]
    assert moved["warnings"] == []
    kept = one({"fps": 25}, base=sized)
    assert kept["level"] == "render" and kept["diff"] == [{"key": "fps", "from": 24, "to": 25}]
    assert kept["warnings"] == ["shorter clips (5.80 s, was 6.04 s): the copied story.md is re-checked "
                                "and can fail its spoken-line timing"]
    panels = one({"frames": 97})
    assert panels["level"] == "render" and panels["warnings"] == [
        "shorter clips (4.04 s, was 6.04 s): the copied story.md is re-checked and can fail its "
        "spoken-line timing"]
    assert one({"frames": 153})["warnings"] == []


# --- BT7: fork IDs (spec 2.5) ---------------------------------------------------------------

def test_bt7_fork_ids_numbers_and_collisions():
    assert batch.fork_id("ronin-rescue", 3, 2) == "ronin-rescue-b3-v2"
    records = [{"workspace": WSR, "number": 4}, {"workspace": "/other", "number": 9},
               {"workspace": WSR, "number": True}, None]
    assert batch.next_number(records, ["plain"], WSR) == 5
    assert batch.next_number([], ["a-b7-v1", "b-b2-v3", "plain", "c-b12x-v1"], WSR) == 8
    assert batch.next_number([], [], WSR) == 1
    long = "a" * 70 + "-" + "b" * 7
    assert len(long) == 78 and batch.fork_id(long, 3, 1) == "a" * 70 + "-bbb-b3-v1"
    assert len(batch.fork_id(long, 3, 1)) == 80 and lib.valid_story_id(batch.fork_id(long, 3, 1))
    cut = "a" * 72 + "-._" + "ccc"
    assert len(cut) == 78 and batch.fork_id(cut, 3, 1) == "a" * 72 + "-b3-v1"
    assert lib.valid_story_id(batch.fork_id(cut, 3, 1))
    bad = plan(["s1"], [variant({"model": "/models/other"})], number=10 ** 80)[0]
    assert bad["reason"] == "the fork ID would not be a valid story ID: %s" % batch.fork_id("s1", 10 ** 80, 1)
    cells = plan(["Ronin", "ronin"], [variant({"model": "/models/other"})])
    assert [(c["fork_id"], c["status"], c["reason"]) for c in cells] == [
        ("Ronin-b3-v1", "ok", None),
        ("ronin-b3-v1", "refused", "fork ID ronin-b3-v1 is also the fork ID of story Ronin in this batch")]
    taken = plan(["ronin-rescue"], [variant({"model": "/models/other"})], existing=("ronin-rescue-b3-v1",))
    assert taken[0]["reason"] == "fork ID ronin-rescue-b3-v1 already exists; it is never overwritten"


# --- BT8: the copy plan (spec 2.6) ----------------------------------------------------------

NEVER = ("movie.mp4", ".movie.lock", "movie.log", "iterate-story.log", "runs/r1/story_summary.json",
         "redo/1/panel_01.mp4", "story_rounds/round_0/story.md", "story_rounds-old/round_0/story.md",
         "story.md.bak-20261030T120000Z", "plan.stale-1.json", "seed_downscaled.png", "fork.json",
         "clips/panel_01.chainseed.png", "notes.txt", "images/seed.png", "images/panel_1.png",
         "clips/panel_02.mp4", "clips/panel_03.mp4.provenance.json")
ALLOWED = ("story.md", "plan.json", "story_checks.json", "story_prompt.txt", "catalog_loras.json",
           "manifest.json", "images/panel_01.png", "images/panel_02.png", "images/images.json",
           "clips/panel_01.mp4", "clips/panel_01.mp4.provenance.json")


def _story_fixture(root):
    for rel in ALLOWED + NEVER:
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(rel.encode("utf-8"))
    os.symlink(os.path.join(root, "story.md"), os.path.join(root, "images", "panel_03.png"))
    return root


def test_bt8_the_copy_plan_of_every_level(tmp_path):
    sdir = _story_fixture(str(tmp_path / "story"))
    render = batch.copy_plan(sdir, "render")
    assert render == sorted((rel, len(rel.encode("utf-8"))) for rel in ALLOWED)
    assert [rel for rel, _n in render] == [
        "catalog_loras.json", "clips/panel_01.mp4", "clips/panel_01.mp4.provenance.json",
        "images/images.json", "images/panel_01.png", "images/panel_02.png", "manifest.json", "plan.json",
        "story.md", "story_checks.json", "story_prompt.txt"]
    assert [rel for rel, _n in batch.copy_plan(sdir, "stills")] == [
        "plan.json", "story.md", "story_checks.json", "story_prompt.txt"]
    assert batch.copy_plan(sdir, "replan") == []
    listed = set(rel for rel, _n in render)
    assert not listed & set(NEVER) and "images/panel_03.png" not in listed
    os.unlink(os.path.join(sdir, "story.md"))
    os.symlink(os.path.join(sdir, "plan.json"), os.path.join(sdir, "story.md"))
    assert "story.md" not in [rel for rel, _n in batch.copy_plan(sdir, "stills")]


def test_batch_review_focus_5_symlinked_images_and_clips_directories(tmp_path):
    """Review Focus 5: an original whose images/ and clips/ are symlinks to a shared folder."""
    shared = _story_fixture(str(tmp_path / "shared"))
    sdir = str(tmp_path / "story")
    os.makedirs(sdir)
    with open(os.path.join(sdir, "story.md"), "w", encoding="utf-8") as f:
        f.write("## Panel 1 -- Shot 1\n")
    os.symlink(os.path.join(shared, "images"), os.path.join(sdir, "images"))
    os.symlink(os.path.join(shared, "clips"), os.path.join(sdir, "clips"))
    assert batch.copy_plan(sdir, "render") == [("story.md", 21)]


# --- BT9: the 400 messages of spec 6, exact and in order -----------------------------------

def _errors(body):
    return batch.validate_request(body)[1]


def test_bt9_every_400_message_in_table_order():
    assert _errors({"stories": [], "variants": []}) == [
        "stories must be a list of 1 to 24 distinct story IDs", "variants must be a list of 1 to 6 variants"]
    for stories in (None, "s1", ["s1", "s1"], ["a..b"], ["-x"], [5], ["s%d" % i for i in range(25)]):
        assert _errors({"stories": stories, "variants": [variant()]}) == [
            "stories must be a list of 1 to 24 distinct story IDs"], stories
    for variants in (None, [variant()] * 7, ["v1"]):
        assert _errors({"stories": ["s1"], "variants": variants}) == [
            "variants must be a list of 1 to 6 variants"], variants
    assert _errors({"stories": ["s%d" % i for i in range(5)], "variants": [variant()] * 5}) == [
        "a batch has at most 24 cells; this one has 25 (5 stories x 5 variants)"]
    first = {"label": "", "settings": {"ws": "/x", "narrative": "n", "bogus": 1, "panels": 3, "length": 9,
                                       "width": 64},
             "prompt": {"append": 5, "replace": [{"find": "", "with": 7}, {"find": "ok", "with": "x" * 20001}],
                        "per_story": {"ronin-rescue": ""}}}
    second = {"label": "two\nlines", "settings": {"seed_upload": SEED, "width": 64, "height": 64},
              "prompt": {"replace": [{"find": "a", "with": "b"}] * 11, "per_story": {"other": "x"}}}
    assert _errors({"stories": ["ronin-rescue"], "variants": [first, second]}) == [
        "variant 1: label must be 1 to 24 characters with no line breaks",
        "variant 2: label must be 1 to 24 characters with no line breaks",
        "variant 1: setting ws cannot be changed in a variant",
        "variant 1: setting bogus cannot be changed in a variant",
        "variant 1: change the prompt with append, replace or per-story text",
        "variant 1: give panels or length, not both",
        "variant 1: give width and height together",
        "variant 2: give a seed image or a resolution, not both",
        "variant 1: append must be a string of at most 20000 characters",
        "variant 2: replace must be a list of at most 10 {find, with} pairs",
        "variant 1: replace pair 1: find must be 1 to 20000 characters",
        "variant 1: replace pair 1: with must be a string of at most 20000 characters",
        "variant 1: replace pair 2: with must be a string of at most 20000 characters",
        "variant 2: per_story must map story IDs of this batch to text",
        "variant 1: per-story prompt for ronin-rescue must be 1 to 20000 characters"]
    assert _errors({"stories": ["s1"], "variants": [{"label": "v1", "settings": [], "prompt": "x"}]}) == [
        "variant 1: settings must be an object", "variant 1: prompt must be an object"]
    assert _errors({"stories": ["s1"], "variants": [{"settings": {}}]}) == [
        "variant 1: label must be 1 to 24 characters with no line breaks"]
    for replace in ([{"find": "a"}], [{"find": "a", "with": "b", "x": 1}], ["a"], {"find": "a"}):
        assert _errors({"stories": ["s1"], "variants": [{"label": "v1", "prompt": {"replace": replace}}]}) == [
            "variant 1: replace must be a list of at most 10 {find, with} pairs"], replace
    assert _errors({"stories": ["s1"], "variants": [{"label": "v1", "prompt": {"per_story": {"s1": 5}}}]}) == [
        "variant 1: per_story must map story IDs of this batch to text"]
    assert _errors({"stories": ["s1"], "variants": [{"label": "v1", "settings": {"seed_upload": None,
                                                                                    "width": 64,
                                                                                    "height": 64}}]}) == []


def test_bt9_a_valid_request_is_cleaned():
    body = {"ws": "/ignored", "stories": ["s1", "s2"],
            "variants": [{"label": "v1", "settings": {"model": "/models/other"}},
                         {"label": "v2", "prompt": {"append": "Snow.", "replace": [{"find": "a", "with": "b"}],
                                                    "per_story": {"s2": "Text."}}}]}
    clean, errors = batch.validate_request(body)
    assert errors == []
    assert clean == {"stories": ["s1", "s2"], "variants": [
        {"label": "v1", "settings": {"model": "/models/other"},
         "prompt": {"append": "", "replace": [], "per_story": {}}},
        {"label": "v2", "settings": {},
         "prompt": {"append": "Snow.", "replace": [{"find": "a", "with": "b"}], "per_story": {"s2": "Text."}}}]}


# --- BT10 (BK4 unit), BT11: the submit order and the totals ---------------------------------

def test_bt10_the_submit_order():
    cells = [{"story_id": s, "variant": m, "status": "pending", "level": level}
             for s in ("s1", "s2") for m, level in ((1, "render"), (2, "replan"), (3, "stills"))]
    assert batch.submit_order(cells, ["s1", "s2"]) == [1, 4, 2, 5, 0, 3]
    cells[4]["status"] = "refused"
    assert batch.submit_order(cells, ["s1", "s2"]) == [1, 2, 5, 0, 3]


def test_bt11_the_totals_text():
    cells = [{"status": "ok", "level": level} for level in ("render", "replan", "stills", "render")]
    assert batch.totals(cells) == {"jobs": 4, "replan": 1, "stills": 1, "render": 2, "refused": 0,
                                   "text": "4 jobs: 1 re-plan, 1 new stills, 2 render-only"}
    cells += [{"status": "refused", "level": None}, {"status": "invalid", "level": None}]
    assert batch.totals(cells)["text"] == "4 jobs: 1 re-plan, 1 new stills, 2 render-only; 2 refused"
    assert batch.totals(cells)["refused"] == 2


# --- BT12: originals without story.md, a directory or saved settings (BF9, spec 3.6) --------

def test_bt12_an_original_without_story_md_is_replan():
    originals = {"ronin-rescue": info(has_story=False)}
    cell = plan(["ronin-rescue"], [variant({"model": "/models/other"})], originals)[0]
    assert (cell["status"], cell["level"]) == ("ok", "replan")
    assert cell["warnings"] == ["the original has no story.md; this fork writes a new story"]
    gone = plan(["ronin-rescue"], [variant({"model": "/models/other"})],
                {"ronin-rescue": info(exists_dir=False)})[0]
    assert gone["reason"] == "story ronin-rescue no longer exists in this workspace"
    busy = plan(["ronin-rescue"], [variant({"model": "/models/other"})],
                {"ronin-rescue": info(busy_job="20261030-120000-0a0a")})[0]
    assert busy["reason"] == "story ronin-rescue has a job queued or running (job 20261030-120000-0a0a)"
    for code, text in (("none", "story ronin-rescue has no saved Compose settings (it was started from "
                                "the command line)"),
                       ("gone", "story ronin-rescue has no saved Compose settings (its job and its batch "
                                "%s were deleted)" % BID),
                       ("mismatch", "story ronin-rescue has no saved Compose settings (its job was deleted "
                                    "and batch %s has no matching record of it)" % BID)):
        cell = plan(["ronin-rescue"], [variant({"model": "/models/other"})],
                    {"ronin-rescue": info(fields=None, code=code, batch_id=BID)})[0]
        assert (cell["status"], cell["reason"]) == ("refused", text)
    invalid = plan(["ronin-rescue"], [variant({"model": "/models/other"})], errors=["a", "b"])[0]
    assert (invalid["status"], invalid["reason"], invalid["level"]) == ("invalid", "a\nb", None)
    broken = plan(["ronin-rescue"], [variant({"model": "/models/other"})],
                  {"ronin-rescue": info(fields=saved(narrative=None))})[0]
    assert broken["reason"] == ("the saved settings of story ronin-rescue cannot be used: TypeError: the "
                                "saved narrative is not a string")
    assert batch.eligibility_reason(None, "job", None) is None
    assert batch.eligibility_reason(None, "ok", BID) is None


# --- BT31 (BK8 unit): the batch-record field fallback (BF41c) -------------------------------

def _pair():
    fields = saved(story_id="ronin-rescue-b1-v1", model="/models/other")
    fork_rec = {"schema": batch.FORK_SCHEMA, "fork_id": "ronin-rescue-b1-v1", "source_story": "ronin-rescue",
                "batch": BID, "variant": 1, "label": "v1", "level": "render", "diff": [],
                "created": "2026-10-30T12:05:09Z"}
    batch_rec = {"schema": batch.BATCH_SCHEMA, "id": BID, "number": 1, "workspace": WSR,
                 "cells": [{"story_id": "ronin-rescue", "variant": 1, "fork_id": "ronin-rescue-b1-v1",
                            "status": "queued", "job_id": "20261030-120509-0a0b", "fields": fields}]}
    return fork_rec, batch_rec


def test_bt31_a_matching_pair_gives_the_cell_fields():
    fork_rec, batch_rec = _pair()
    code, fields, batch_id, number = batch.fork_fallback(fork_rec, batch_rec, "ronin-rescue-b1-v1", WSR)
    assert (code, batch_id, number) == ("ok", BID, 1)
    assert fields == batch_rec["cells"][0]["fields"] and fields is not batch_rec["cells"][0]["fields"]


def test_bt31_none_and_gone():
    fork_rec, batch_rec = _pair()
    for bad in (None, [], dict(fork_rec, schema="x"), dict(fork_rec, fork_id="other"),
                dict(fork_rec, batch="../x"), dict(fork_rec, batch=5), dict(fork_rec, batch=None)):
        assert batch.fork_fallback(bad, batch_rec, "ronin-rescue-b1-v1", WSR) == ("none", None, None, None)
    assert batch.fork_fallback(fork_rec, None, "ronin-rescue-b1-v1", WSR) == ("gone", None, BID, None)


MISMATCH = [
    ("schema", lambda f, b: b.update(schema="x")),
    ("id", lambda f, b: b.update(id="20261030-120501-ffff")),
    ("workspace", lambda f, b: b.update(workspace="/other")),
    ("no-cell", lambda f, b: b.update(cells=[])),
    ("two-cells", lambda f, b: b["cells"].append(dict(b["cells"][0], fork_id="Ronin-Rescue-b1-v1"))),
    ("cell-case", lambda f, b: b["cells"][0].update(fork_id="Ronin-rescue-b1-v1")),
    ("source", lambda f, b: f.update(source_story="harbour-chase")),
    ("variant", lambda f, b: f.update(variant=2)),
    ("cancelled", lambda f, b: b["cells"][0].update(status="cancelled")),
    ("job", lambda f, b: b["cells"][0].update(job_id=None)),
    ("fields", lambda f, b: b["cells"][0].update(fields=None)),
    ("fields-id", lambda f, b: b["cells"][0]["fields"].update(story_id="ronin-rescue")),
]


@pytest.mark.parametrize("name,change", MISMATCH, ids=[case[0] for case in MISMATCH])
def test_bt31_mismatch(name, change):
    fork_rec, batch_rec = _pair()
    change(fork_rec, batch_rec)
    assert batch.fork_fallback(fork_rec, batch_rec, "ronin-rescue-b1-v1", WSR) == ("mismatch", None, BID, None)
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bulk-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_movie_ui_batch.py 2>&1 | tail -1
```

Expected: `1 error` (collection: `ModuleNotFoundError: No module named 'movie_ui_batch'`).

- [ ] **Step 3: Implement.**

Create `movie_ui_batch.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""movie_ui_batch -- batch forks: the pure core of a bulk re-run of stories to compare settings
(docs/superpowers/specs/2026-10-30-batch-forks-design.md, deliverable G1).

The constants (spec 1.1), the request check of the preview and submit bodies (3.2, 6), the field
classification table (2.1), merge (2.2), the prompt edits (2.3), the cell plan with its
classification and refusals (2.4, 3.6), fork IDs (2.5), the copy plan (2.6), the submit order
(4.2), the totals (3.3), the eligibility texts (3.4) and the batch-record field fallback check
(3.5).

Standard library plus movie_ui_lib only (BF1). Valid on Python 3.9 and 3.13. This module never
writes. Every function is pure except copy_plan, which lists a story directory read-only, and
plan_cells, which reads only through the validate and exists functions its caller passes in.
"""

import json
import os
import re
import stat

import movie_ui_lib as lib

BATCH_SCHEMA = "movie-ui.batch.v1"
FORK_SCHEMA = "movie-ui.fork.v1"
MAX_VARIANTS = 6
MAX_CELLS = 24
MAX_REPLACES = 10                      # [spec choice] bounds the request
LABEL_MAX = 24                         # [spec choice] fits a grid column header
PROMPT_MAX = lib.NARRATIVE_MAX         # 20000, the Compose narrative limit
STORY_ID_MAX = 80                      # STORY_ID_RE, movie_ui_lib.py:37
MIN_FREE_BYTES = 20 * 1024 ** 3        # 20 GiB left after the copy
LEVELS = ("render", "stills", "replan")            # rank order
LEVEL_LABELS = {"render": "Render", "stills": "New stills", "replan": "Re-plan"}
FIXED_KEYS = ("ws", "action", "story_id", "overwrite_movie", "redo")
GROUPS = (("panels", "length"), ("width", "height", "seed_upload"))
FORK_SUFFIX_RE = re.compile(r"-b([0-9]+)-v[0-9]+$")

# Spec 2.1 (BF4, BK1): the level of every editable DEFAULT_FIELDS key.
FIELD_LEVELS = {
    "model": "render", "gemma": "render", "video_loras": "render", "action_loras": "render",
    "frames": "render", "fps": "render", "no_low_ram": "render", "panel_timeout": "render",
    "width": "stills", "height": "stills", "stills_loras": "stills", "location_strength": "stills",
    "narrative": "replan", "goal": "replan", "panels": "replan", "length": "replan",
    "seed_upload": "replan", "mode": "replan", "characters": "replan", "locations": "replan",
    "narration": "replan", "story_model": "replan", "story_legacy": "replan", "judge": "replan",
    "auto_lora": "replan",
}

# Spec 2.6 (BF16): the allowlist of the files a fork copies, by level.
COPY_FILES = {
    "render": ("story.md", "plan.json", "story_checks.json", "story_prompt.txt", "catalog_loras.json",
               "manifest.json"),
    "stills": ("story.md", "plan.json", "story_checks.json", "story_prompt.txt"),
    "replan": (),
}
STILL_RE = re.compile(r"^panel_\d{2}\.png$")
CLIP_RE = re.compile(r"^panel_\d{2}\.mp4$")

# Spec 6: the rows of the 400 table, in table order (errors are sorted by row, stably).
_ROWS = ("stories", "variants", "cells", "label", "key", "narrative", "both", "pair", "seed", "append",
         "replace", "find", "with", "per_story", "per_story_text")

# Spec 3.6 step 2: a cell's refusal when its original has no saved Compose settings.
NO_FIELDS = {
    "none": "story %s has no saved Compose settings (it was started from the command line)",
    "gone": "story %s has no saved Compose settings (its job and its batch %s were deleted)",
    "mismatch": ("story %s has no saved Compose settings (its job was deleted and batch %s has no "
                 "matching record of it)"),
}
IDENTICAL = "same settings and prompt as the original; nothing to compare"

_ABSENT_A, _ABSENT_B = object(), object()   # two missing keys never compare equal (BF41c)


# ---------------------------------------------------------------------------
# The request (spec 3.2, 6)
# ---------------------------------------------------------------------------

def validate_request(body):
    """(clean, errors) for a preview or submit body (spec 3.2, 6). clean is {"stories",
    "variants"}, each variant as {"label", "settings", "prompt": {"append", "replace",
    "per_story"}}; errors lists the 400 lines in the table order of spec 6, variant K and pair J
    ascending within a row. The caller resolves "ws" with resolve_ws before this."""
    found = []
    stories = body.get("stories")
    stories_ok = (isinstance(stories, list) and 1 <= len(stories) <= MAX_CELLS
                  and all(lib.valid_story_id(s) for s in stories) and len(set(stories)) == len(stories))
    if not stories_ok:
        found.append(("stories", "stories must be a list of 1 to 24 distinct story IDs"))
    variants = body.get("variants")
    variants_ok = (isinstance(variants, list) and 1 <= len(variants) <= MAX_VARIANTS
                   and all(isinstance(v, dict) for v in variants))
    if not variants_ok:
        found.append(("variants", "variants must be a list of 1 to 6 variants"))
    if stories_ok and variants_ok and len(stories) * len(variants) > MAX_CELLS:
        found.append(("cells", "a batch has at most 24 cells; this one has %d (%d stories x %d variants)"
                      % (len(stories) * len(variants), len(stories), len(variants))))
    names = set(stories) if stories_ok else set()
    clean_variants = [_check_variant(k, v, names, found)
                      for k, v in enumerate(variants if variants_ok else [], 1)]
    errors = [text for _row, text in sorted(found, key=lambda item: _ROWS.index(item[0]))]
    return {"stories": list(stories) if stories_ok else [], "variants": clean_variants}, errors


def _check_variant(k, variant, names, found):
    """Append variant K's 400 lines to found as (row, text); return its clean form."""
    head = "variant %d: " % k
    label = variant.get("label")
    if not (isinstance(label, str) and 1 <= len(label) <= LABEL_MAX and "\n" not in label
            and "\r" not in label):
        found.append(("label", head + "label must be 1 to 24 characters with no line breaks"))
    settings = variant.get("settings", {})
    if not isinstance(settings, dict):
        found.append(("key", head + "settings must be an object"))
        settings = {}
    for key in settings:
        if key == "narrative":
            found.append(("narrative", head + "change the prompt with append, replace or per-story text"))
        elif key not in FIELD_LEVELS:
            found.append(("key", head + "setting %s cannot be changed in a variant" % key))
    if "panels" in settings and "length" in settings:
        found.append(("both", head + "give panels or length, not both"))
    if ("width" in settings) != ("height" in settings):
        found.append(("pair", head + "give width and height together"))
    if settings.get("seed_upload") is not None and ("width" in settings or "height" in settings):
        found.append(("seed", head + "give a seed image or a resolution, not both"))
    prompt = variant.get("prompt", {})
    if not isinstance(prompt, dict):
        found.append(("append", head + "prompt must be an object"))
        prompt = {}
    append = prompt.get("append", "")
    if not (isinstance(append, str) and len(append) <= PROMPT_MAX):
        found.append(("append", head + "append must be a string of at most 20000 characters"))
        append = ""
    replace = prompt.get("replace", [])
    pairs = []
    if not (isinstance(replace, list) and len(replace) <= MAX_REPLACES
            and all(isinstance(p, dict) and set(p) == {"find", "with"} for p in replace)):
        found.append(("replace", head + "replace must be a list of at most 10 {find, with} pairs"))
    else:
        for j, pair in enumerate(replace, 1):
            if not (isinstance(pair["find"], str) and 1 <= len(pair["find"]) <= PROMPT_MAX):
                found.append(("find", head + "replace pair %d: find must be 1 to 20000 characters" % j))
            if not (isinstance(pair["with"], str) and len(pair["with"]) <= PROMPT_MAX):
                found.append(("with", head + "replace pair %d: with must be a string of at most 20000 "
                                             "characters" % j))
            pairs.append({"find": pair["find"], "with": pair["with"]})
    per_story = prompt.get("per_story", {})
    texts = {}
    if not (isinstance(per_story, dict)
            and all(sid in names and isinstance(text, str) for sid, text in per_story.items())):
        found.append(("per_story", head + "per_story must map story IDs of this batch to text"))
    else:
        for sid, text in per_story.items():
            if not 1 <= len(text) <= PROMPT_MAX:
                found.append(("per_story_text", head + "per-story prompt for %s must be 1 to 20000 "
                                                       "characters" % sid))
            texts[sid] = text
    return {"label": label, "settings": json.loads(json.dumps(settings)),
            "prompt": {"append": append, "replace": pairs, "per_story": texts}}


# ---------------------------------------------------------------------------
# Merge, prompt edits and classification (spec 2.2-2.4)
# ---------------------------------------------------------------------------

def original_fields(last_fields, story_id, ws_real):
    """Merge step 1 (BF5): the original's fields with the fixed keys of a fork's run."""
    orig = lib.compose_fields(last_fields)
    orig.update(ws=ws_real, action="movie", story_id=story_id, overwrite_movie=False, redo=[])
    return orig


def edit_prompt(narrative, prompt, story_id):
    """(text, warnings): BF6's per-story text, then the find/replace pairs in order, then the
    appended paragraph, then the length warning. Raises TypeError when the text is not a string
    (a saved narrative of null), which BF12 turns into a refusal."""
    per_story = prompt.get("per_story") or {}
    text = per_story[story_id] if story_id in per_story else narrative
    if not isinstance(text, str):
        raise TypeError("the saved narrative is not a string")
    warnings = []
    for pair in prompt.get("replace") or []:
        if pair["find"] in text:
            text = text.replace(pair["find"], pair["with"])
        else:
            warnings.append('find text not in this prompt: "%s"' % pair["find"])
    append = (prompt.get("append") or "").strip()
    if append:
        text = text.rstrip() + "\n\n" + append
    if len(text) > PROMPT_MAX:
        warnings.append("edited prompt is %d characters; the limit is %d" % (len(text), PROMPT_MAX))
    return text, warnings


def merge(last_fields, variant, story_id, fork_id, ws_real):
    """(orig, fork, warnings) of spec 2.2 (BF5)."""
    orig = original_fields(last_fields, story_id, ws_real)
    fork = json.loads(json.dumps(orig))
    fork["story_id"] = fork_id or story_id
    for key, value in variant["settings"].items():
        fork[key] = json.loads(json.dumps(value))
        if key == "panels":
            fork["length"] = None
        elif key == "length":
            fork["panels"] = None
        elif key in ("width", "height"):
            fork["seed_upload"] = None
        elif key == "seed_upload" and value is not None:
            fork["width"] = fork["height"] = None
    fork["narrative"], warnings = edit_prompt(orig["narrative"], variant["prompt"], story_id)
    return orig, fork, warnings


def argv_of(fields, story_id, ws_real, state):
    """A(f) of spec 2.4: the bin/ltx-movie argv of fields with the original's story ID."""
    return lib.build_argv(dict(fields, story_id=story_id), ws_real, state)


def _group(key):
    for group in GROUPS:
        if key in group:
            return group
    return (key,)


def classify(orig, fork, story_id, ws_real, state, has_story):
    """(level, diff, warnings) of a fork whose argv differs from its original's (BF8-BF10)."""
    base = argv_of(orig, story_id, ws_real, state)
    diff = []
    for key in lib.DEFAULT_FIELDS:
        if key not in FIELD_LEVELS or fork[key] == orig[key]:
            continue
        probe = dict(orig)
        for k in _group(key):
            probe[k] = fork[k]
        if argv_of(probe, story_id, ws_real, state) != base:
            diff.append({"key": key, "from": orig[key], "to": fork[key]})
    if fork["length"] is not None and "panels" not in [d["key"] for d in diff]:
        before, after = lib.resolved_panels(orig), lib.resolved_panels(fork)
        if after != before:
            diff.append({"key": "panels", "from": before, "to": after, "note": "resolved from length"})
    level = LEVELS[max(LEVELS.index(FIELD_LEVELS[d["key"]]) for d in diff)]
    warnings = []
    if not has_story:
        level = "replan"
        warnings.append("the original has no story.md; this fork writes a new story")
    elif level in ("render", "stills"):
        clip, was = fork["frames"] / float(fork["fps"]), orig["frames"] / float(orig["fps"])
        if clip < was:
            warnings.append("shorter clips (%.2f s, was %.2f s): the copied story.md is re-checked and "
                            "can fail its spoken-line timing" % (clip, was))
    return level, diff, warnings


# ---------------------------------------------------------------------------
# Fork IDs (spec 2.5)
# ---------------------------------------------------------------------------

def fork_id(story_id, n, m):
    """BF13: <story_id>-b<n>-v<m>, the stem cut so the whole is at most 80 characters and never
    ends in "-", "." or "_"."""
    suffix = "-b%d-v%d" % (n, m)
    stem = story_id
    if len(story_id) + len(suffix) > STORY_ID_MAX:
        stem = story_id[:STORY_ID_MAX - len(suffix)].rstrip("-._")
    return stem + suffix


def next_number(batch_records, story_names, ws_real):
    """BF14: 1 plus the largest number of a batch record of ws_real and of a fork suffix among the
    workspace's story directory names (0 when there are none)."""
    top = 0
    for rec in batch_records:
        if not isinstance(rec, dict) or rec.get("workspace") != ws_real:
            continue
        number = rec.get("number")
        if isinstance(number, int) and not isinstance(number, bool):
            top = max(top, number)
    for name in story_names:
        found = FORK_SUFFIX_RE.search(name)
        if found:
            top = max(top, int(found.group(1)))
    return top + 1


# ---------------------------------------------------------------------------
# The cell plan (spec 3.6)
# ---------------------------------------------------------------------------

def no_fields_reason(story_id, code, batch_id):
    """The spec 3.6 step 2 refusal for BF41 code "none", "gone" or "mismatch"."""
    if code == "none":
        return NO_FIELDS["none"] % story_id
    return NO_FIELDS[code] % (story_id, batch_id)


def eligibility_reason(busy_job, code, batch_id):
    """Spec 3.4's reason of one Stories row (busy wins), or None when the story is eligible."""
    if busy_job is not None:
        return "Job %s is queued or running for this story" % busy_job
    if code == "none":
        return "Started from the command line: no saved Compose settings to fork"
    if code == "gone":
        return "Its job and its batch %s were deleted: no saved Compose settings to fork" % batch_id
    if code == "mismatch":
        return ("Its job was deleted and batch %s has no matching record of this fork: no saved "
                "Compose settings to fork" % batch_id)
    return None


def _unusable(story_id, error):
    return "the saved settings of story %s cannot be used: %s: %s" % (story_id, type(error).__name__, error)


def _early_refusal(story_id, info, fid, earlier, exists):
    """Steps 1-4 of spec 3.6, or None."""
    if not info["dir"]:
        return "story %s no longer exists in this workspace" % story_id
    if info["fields"] is None:
        return no_fields_reason(story_id, info["code"], info["batch"])
    if info["busy_job"] is not None:
        return "story %s has a job queued or running (job %s)" % (story_id, info["busy_job"])
    if not lib.valid_story_id(fid):
        return "the fork ID would not be a valid story ID: %s" % fid
    for other in earlier:
        if other["status"] == "ok" and other["fork_id"].lower() == fid.lower():
            return "fork ID %s is also the fork ID of story %s in this batch" % (fid, other["story_id"])
    if exists(fid):
        return "fork ID %s already exists; it is never overwritten" % fid
    return None


def _build(cell, info, variant, labels, ws_real, state, validate, earlier, argvs):
    """Steps 5-7 of spec 3.6 for a cell that passed steps 1-4."""
    story_id = cell["story_id"]
    try:
        orig, fork, warnings = merge(info["fields"], variant, story_id, cell["fork_id"], ws_real)
    except (KeyError, TypeError, ValueError) as e:
        cell["reason"] = _unusable(story_id, e)
        return
    cell["warnings"] = warnings
    errors = validate(fork)
    if errors:
        cell["status"], cell["reason"] = "invalid", "\n".join(errors)
        return
    try:
        argv = argv_of(fork, story_id, ws_real, state)
        if argv == argv_of(orig, story_id, ws_real, state):
            cell["reason"] = IDENTICAL
            return
        for other in earlier:
            if (other["story_id"] == story_id and other["status"] == "ok"
                    and argvs[(story_id, other["variant"])] == argv):
                cell["reason"] = "same settings and prompt as variant %d (%s) for this story" % (
                    other["variant"], labels[other["variant"] - 1])
                return
        level, diff, notes = classify(orig, fork, story_id, ws_real, state, info["has_story"])
    except (KeyError, TypeError, ValueError) as e:
        cell["reason"] = _unusable(story_id, e)
        return
    argvs[(story_id, cell["variant"])] = argv
    cell.update(status="ok", level=level, diff=diff, warnings=warnings + notes, fields=fork)


def plan_cells(stories, variants, number, ws_real, state, originals, validate, exists):
    """Spec 3.6 for every cell in grid order (story-major, then variant): a list of {"story_id",
    "variant", "fork_id", "status", "reason", "level", "diff", "warnings", "fields"} with status
    "ok", "refused" or "invalid" (V1 failed) and fields the fork's fields when "ok".

    originals maps each story ID to {"dir", "has_story", "busy_job", "fields", "code", "batch"}
    (fields None when the story has no saved Compose settings, with code "none", "gone" or
    "mismatch"); validate(fields) is V1 and exists(fork_id) says whether the fork's directory
    exists. BF11 and BF15 compare a cell only with earlier cells whose status is "ok"."""
    labels = [v["label"] for v in variants]
    cells, argvs = [], {}
    for story_id in stories:
        info = originals[story_id]
        for m, variant in enumerate(variants, 1):
            cell = {"story_id": story_id, "variant": m, "fork_id": fork_id(story_id, number, m),
                    "status": "refused", "reason": None, "level": None, "diff": [], "warnings": [],
                    "fields": None}
            earlier = list(cells)
            cells.append(cell)
            cell["reason"] = _early_refusal(story_id, info, cell["fork_id"], earlier, exists)
            if cell["reason"] is None:
                _build(cell, info, variant, labels, ws_real, state, validate, earlier, argvs)
    return cells


def totals(cells):
    """Spec 3.3's totals of a cell plan: "ok" cells are jobs; "refused" and "invalid" are refused."""
    ok = [c for c in cells if c["status"] == "ok"]
    counts = dict((level, sum(1 for c in ok if c["level"] == level)) for level in LEVELS)
    refused = sum(1 for c in cells if c["status"] in ("refused", "invalid"))
    text = "%d jobs: %d re-plan, %d new stills, %d render-only" % (
        len(ok), counts["replan"], counts["stills"], counts["render"])
    if refused:
        text += "; %d refused" % refused
    return {"jobs": len(ok), "replan": counts["replan"], "stills": counts["stills"],
            "render": counts["render"], "refused": refused, "text": text}


def submit_order(cells, stories):
    """BF27: the indices of the "pending" cells, Re-plan first, then New stills, then Render, and
    within a level by story order, then by variant."""
    pending = [i for i, c in enumerate(cells) if c["status"] == "pending"]
    return sorted(pending, key=lambda i: (-LEVELS.index(cells[i]["level"]),
                                          stories.index(cells[i]["story_id"]), cells[i]["variant"]))


# ---------------------------------------------------------------------------
# The copy plan (spec 2.6)
# ---------------------------------------------------------------------------

def _mode(path):
    try:
        return os.lstat(path).st_mode
    except OSError:
        return 0


def _names(directory):
    """The names in directory when it is a real directory (never through a symlink), else []."""
    if not stat.S_ISDIR(_mode(directory)):
        return []
    try:
        return os.listdir(directory)
    except OSError:
        return []


def copy_plan(sdir, level):
    """[(relpath, bytes)] sorted by relpath: the regular files a fork at level copies from sdir
    (BF16). Symlinks and anything off the allowlist are never listed; images/ and clips/ are read
    only when they are real directories; a clip is listed only together with its provenance."""
    rels = list(COPY_FILES.get(level, ()))
    if level == "render":
        images = os.path.join(sdir, "images")
        rels += [os.path.join("images", n) for n in _names(images)
                 if STILL_RE.fullmatch(n) or n == "images.json"]
        clips = os.path.join(sdir, "clips")
        for name in _names(clips):
            prov = name + ".provenance.json"
            if (CLIP_RE.fullmatch(name) and stat.S_ISREG(_mode(os.path.join(clips, name)))
                    and stat.S_ISREG(_mode(os.path.join(clips, prov)))):
                rels += [os.path.join("clips", name), os.path.join("clips", prov)]
    out = []
    for rel in rels:
        try:
            st = os.lstat(os.path.join(sdir, rel))
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode):
            out.append((rel, st.st_size))
    return sorted(out)


# ---------------------------------------------------------------------------
# The batch-record field fallback (spec 3.5, BF41c)
# ---------------------------------------------------------------------------

def fork_fallback(fork_rec, batch_rec, story_id, ws_real):
    """(code, fields, batch_id, number) of BF41c: "none", "gone", "mismatch" or "ok" (with a
    copy of the cell's submitted fields and the record's number)."""
    if not (isinstance(fork_rec, dict) and fork_rec.get("schema") == FORK_SCHEMA
            and fork_rec.get("fork_id") == story_id and isinstance(fork_rec.get("batch"), str)
            and lib.JOB_ID_RE.fullmatch(fork_rec["batch"])):
        return "none", None, None, None
    batch_id = fork_rec["batch"]
    if batch_rec is None:
        return "gone", None, batch_id, None
    mismatch = ("mismatch", None, batch_id, None)
    if not (isinstance(batch_rec, dict) and batch_rec.get("schema") == BATCH_SCHEMA
            and batch_rec.get("id") == batch_id and batch_rec.get("workspace") == ws_real
            and isinstance(batch_rec.get("cells"), list)):
        return mismatch
    found = [c for c in batch_rec["cells"] if isinstance(c, dict) and isinstance(c.get("fork_id"), str)
             and c["fork_id"].lower() == story_id.lower()]
    if len(found) != 1 or found[0]["fork_id"] != story_id:
        return mismatch
    cell = found[0]
    fields = cell.get("fields")
    if not (cell.get("story_id", _ABSENT_A) == fork_rec.get("source_story", _ABSENT_B)
            and cell.get("variant", _ABSENT_A) == fork_rec.get("variant", _ABSENT_B)
            and cell.get("status") == "queued" and isinstance(cell.get("job_id"), str)
            and isinstance(fields, dict) and fields.get("story_id") == story_id):
        return mismatch
    return "ok", json.loads(json.dumps(fields)), batch_id, batch_rec.get("number")
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bulk-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_movie_ui_batch.py 2>&1 | tail -1
```

Expected: `53 passed`. Run the compile check with `FILES` = `movie_ui_batch.py tests/test_movie_ui_batch.py`; expected: `compiled 2` twice. Then run the gate block with `N=1`. Expected: `GATE PASS`, `lost 0`, `new tests 53, not passing 0`, all the baseline failures still failing, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bulk-wt/qwen-agent-workspace
git add movie_ui_batch.py tests/test_movie_ui_batch.py
git diff --cached --name-only    # expected: those 2 paths
git commit -m "feat(movie-ui): movie_ui_batch, the pure core of batch forks: classification, merge, prompt edits, cell plan, fork IDs, copy plan, order, fallback (BF1, BF4-BF17, BF27, BF41c; BT1-BT12, BT31)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Eligibility, planning and the preview (BF2, BF3, BF22, BF23, BF41a/b/d/e; BT15, Review Focus 2)

This task implements:
- G3: `STATE_SUBDIRS` gains `"batches"` (BF3).
- BF2: `import movie_ui_batch as batch`, `BATCH_LOCK`, and the server's `batch_queue` and `batch_thread`.
- Spec 3.1 readers: `batch_path`, `read_batch`, `list_batch_ids`. Then `next_batch_number` (BF14 over this STATE).
- Spec 3.4:
  - `_story_listed` and `_story_names`, the directories `_h_stories` lists (Plan ruling BR11);
  - `job_index`, the one pass over the jobs, giving `last_fields` and the busy job;
  - `story_status`.
- BF41b: `stored_fields`. Its regular-file test is `isfile and not islink` (Plan ruling BR10).
- `originals_info` feeds `batch.plan_cells`. Spec 3.6 BF23: `plan_batch`.
- Spec 3.3:
  - `preview_cell` and `preview_row` (whose `fields` is merge step 1's `original_fields`; Plan ruling BR16);
  - `_batch_request` (400 for a bad `ws` first, then 400 `invalid batch`);
  - the routes `POST /api/batches/preview` and `GET /api/batches/stories`.
- Spec 7's helper module `tests/batch_testutil.py`, used by Tasks 2-4.

Tests: BT15 and Review Focus 2, appended to `tests/test_movie_ui_http.py`.

**Files:**
- Create: `tests/batch_testutil.py`.
- Modify:
  - `movie_ui_lib.py`: `STATE_SUBDIRS` `:32`;
  - `movie_ui_server.py`: the imports `:29-30`, `STORE_LOCK` `:33`, `MovieUIServer.__init__` `:190`, `ROUTES` `:103`, and the end of the Stories section `:1876-1879` (the new section is inserted after it);
  - `tests/test_movie_ui_http.py`: the imports `:18-20`, and the end of the file `:1147-1149` (append).
- Read only: `movie_ui_server.py`:
  - `resolve_ws` `:153-167`, `MovieUIServer.job` `:206-213`, `_h_stories` `:1682-1707`, `_inside` `:1643-1648`;
  - `newest_job` `:1159-1165`, `_preview` `:728-732`.

**Interfaces:**
- Consumes: Task 1's `batch.next_number`, `batch.fork_fallback`, `batch.eligibility_reason`, `batch.plan_cells`, `batch.original_fields`, `batch.validate_request`, `batch.totals`. Also `lib.validate_fields(fields, ws_real, state) -> [str]`, `lib.job_state(state, job_id, queue)`, `lib.list_job_ids(state)`, `lib.read_json(path, default=None)`.
- Produces, in `movie_ui_server`:
  - `BATCH_LOCK`; `server.batch_queue` (`[batch_id]`) and `server.batch_thread` (a Thread or None);
  - `batch_path(state, batch_id) -> str`, `read_batch(state, batch_id) -> dict or None`, `list_batch_ids(state) -> [str]`, `next_batch_number(server, ws_real) -> int`;
  - `_story_listed(ws_real, story_id) -> bool`, `_story_names(ws_real) -> [str]`;
  - `job_index(server, ws_real) -> ({story_id: fields}, {story_id: job_id})`;
  - `stored_fields(server, ws_real, story_id) -> (code, fields, batch_id, number)`;
  - `originals_info(server, ws_real, story_ids) -> {story_id: {"dir", "has_story", "busy_job", "fields", "code", "batch", "number"}}` (code `"job"` when `last_fields` exists);
  - `_fields_source(info) -> (source, fields_batch)`, `story_status(server, ws_real) -> [row]`;
  - `plan_batch(server, clean, number) -> (cells, originals)`; `clean` is `{"ws", "stories", "variants"}`;
  - `PREVIEW_CELL_KEYS`, `preview_cell(cell) -> dict`, `_movie_path(ws_real, story_id) -> str or None`, `preview_row(ws_real, story_id, info) -> dict`;
  - `_batch_request(body) -> clean`; the handlers `h_batch_preview` and `h_batch_stories`.
- Produces, in `tests/batch_testutil.py`:
  - `STORY_MD`, `OTHER_MODEL = "/models/other"`, `RENDER = {"model": OTHER_MODEL}`, `OTHER_GEMMA = "/models/gemma-other"`;
  - `original(state, ws, story_id, files=None, job_state="done", **overrides) -> (sdir, job_id)`;
  - `variant(label="v1", settings=None, append="", replace=(), per_story=None)`, `body(ws, stories, variants)`;
  - `passing_checks(monkeypatch, fail=None, gate=None) -> calls`;
  - `submit(s, ws, stories, variants) -> batch_id`, `wait_status(s, batch_id, statuses=("submitted",), timeout=30) -> payload`;
  - `record(state, batch_id)`, `tree_digests(root)`, `run_job(state, job_id, timeout=30)`.

- [ ] **Step 1: Write the failing tests.**

**1.1.** Create `tests/batch_testutil.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""Shared helpers for the batch-forks tests (docs/superpowers/specs/2026-10-30-batch-forks-design.md,
Section 7). Not a test module (pytest does not collect it).

Every helper writes under the stub workspace or the temporary STATE its caller passes in. Nothing
here reads the real HOME, renders, or contacts a server other than the in-test movie-ui server on
127.0.0.1 (movie_ui_testutil.Running); jobs run only the stub workspace's bin/ltx-movie.
"""

import hashlib
import os

import movie_ui_testutil as mt
import movie_ui_lib as lib

STORY_MD = ("## Panel 1 -- Shot 1\nImage: a quiet road.\nMotion: the camera drifts.\n\n"
            "## Panel 2 -- Shot 2\nImage: a dark gate.\nMotion: the camera pushes in.\n")
OTHER_MODEL = "/models/other"
RENDER = {"model": OTHER_MODEL}
OTHER_GEMMA = "/models/gemma-other"


def original(state, ws, story_id, files=None, job_state="done", **overrides):
    """An original story (spec 7 rules): <ws>/generated/stories/<story_id> holding story.md, or
    files ({relpath: bytes}), and a movie job of that story whose fields (movie_ui_testutil.fields
    with action movie and overrides) are its last_fields. job_state is "done" (the default),
    "queued" or "running". Returns (story directory, job ID)."""
    sdir = lib.story_dir(ws, story_id)
    os.makedirs(sdir, exist_ok=True)
    for rel, data in (files if files is not None else {"story.md": STORY_MD.encode("utf-8")}).items():
        path = os.path.join(sdir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    status = {"done": {"state": "done", "exit_code": 0, "ended": lib.utc_now()},
              "running": {"state": "running", "dispatched": lib.utc_now(), "runner_pid": 1, "pgid": None,
                          "started": lib.utc_now()},
              "queued": None}[job_state]
    fields = mt.fields(ws, action="movie", story_id=story_id, **overrides)
    return sdir, mt.make_job(state, ["true"], ws, story_id=story_id, fields=fields, status=status)


def variant(label="v1", settings=None, append="", replace=(), per_story=None):
    """One request variant (spec 3.2); replace is [(find, with)]."""
    return {"label": label, "settings": dict(settings or {}),
            "prompt": {"append": append, "replace": [{"find": f, "with": w} for f, w in replace],
                       "per_story": dict(per_story or {})}}


def body(ws, stories, variants):
    return {"ws": ws, "stories": list(stories), "variants": list(variants)}


def passing_checks(monkeypatch, fail=None, gate=None):
    """Replace lib.run_checks (spec 7 rules): V1 passes, except that a fork ID in fail ({fork_id:
    detail}) gets a failing V6 dry run; a fork ID in gate ({fork_id: threading.Event}) waits for
    its event (30 s at most) first. Returns the list of the fork IDs checked, in call order."""
    calls = []

    def fake(fields, ws_real, state, py=None):
        calls.append(fields["story_id"])
        event = (gate or {}).get(fields["story_id"])
        if event is not None:
            event.wait(30)
        if fields["story_id"] in (fail or {}):
            return [lib.check("V1", "fields", "pass"),
                    lib.check("V6", "dry run", "fail", fail[fields["story_id"]])]
        return [lib.check("V1", "fields", "pass")]
    monkeypatch.setattr(lib, "run_checks", fake)
    return calls


def submit(s, ws, stories, variants):
    """POST /api/batches; asserts 201 and returns the batch ID."""
    status, _h, payload = mt.api(s, "POST", "/api/batches", body=body(ws, stories, variants))
    assert status == 201, payload
    return payload["batch"]["id"]


def wait_status(s, batch_id, statuses=("submitted",), timeout=30):
    """Poll GET /api/batches/<id> until the batch status is one of statuses; returns the payload."""
    def ready():
        status, _h, payload = mt.api(s, "GET", "/api/batches/" + batch_id)
        return payload if status == 200 and payload["batch"]["status"] in statuses else None
    return mt.wait_until(ready, timeout, interval=0.1)


def record(state, batch_id):
    """The batch.json of batch_id as stored."""
    return lib.read_json(os.path.join(state, "batches", batch_id, "batch.json"))


def tree_digests(root):
    """{relpath: sha256 hex digest} of every file under root."""
    out = {}
    for base, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(base, name)
            with open(path, "rb") as f:
                out[os.path.relpath(path, root)] = hashlib.sha256(f.read()).hexdigest()
    return out


def run_job(state, job_id, timeout=30):
    """Dispatch one job as dispatch_tick does and wait until it is done (the stub ltx-movie runs)."""
    mt.dispatch(state, job_id)
    mt.wait_until(lambda: mt.status_of(state, job_id).get("state") == "done", timeout)
```

**1.2.** Edit `tests/test_movie_ui_http.py`: replace this text, which occurs exactly once:

```python
import movie_ui_testutil as mt
import movie_ui_lib as lib
import movie_ui_server as srv
```

with:

```python
import batch_testutil as bt
import movie_ui_testutil as mt
import movie_ui_lib as lib
import movie_ui_server as srv
```

**1.3.** Append the tests. Edit `tests/test_movie_ui_http.py`: replace this text, which occurs exactly once:

```python
    assert 'id="ch-regen-seed"' in html and 'max="2147483647"' in html
    assert html.index('id="ch-regen-seed"') < html.index('id="ch-regenerate"')
    assert "seed:" in js and "#ch-regen-seed" in js and "% 2147483648" in js
```

with:

```python
    assert 'id="ch-regen-seed"' in html and 'max="2147483647"' in html
    assert html.index('id="ch-regen-seed"') < html.index('id="ch-regenerate"')
    assert "seed:" in js and "#ch-regen-seed" in js and "% 2147483648" in js


# --- batch forks (docs/superpowers/specs/2026-10-30-batch-forks-design.md, Section 7) ----------

def test_bt15_batch_story_eligibility(env):
    s, state, ws = env["srv"], env["state"], env["ws"]
    os.makedirs(lib.story_dir(ws, "cli-story"))
    with open(os.path.join(lib.story_dir(ws, "cli-story"), "story.md"), "w", encoding="utf-8") as f:
        f.write(bt.STORY_MD)
    _sdir, queued = bt.original(state, ws, "queued-story", job_state="queued")
    _sdir, running = bt.original(state, ws, "running-story", job_state="running")
    bt.original(state, ws, "ui-story")
    status, _h, payload = mt.api(s, "GET", "/api/batches/stories?ws=" + ws)
    assert status == 200
    rows = dict((r["id"], r) for r in payload["stories"])
    assert sorted(rows) == ["cli-story", "queued-story", "running-story", "ui-story"]
    assert rows["cli-story"] == {"id": "cli-story", "eligible": False,
                                 "reason": "Started from the command line: no saved Compose settings to fork",
                                 "busy_job": None, "fields_source": None, "fields_batch": None}
    for story_id, job_id in (("queued-story", queued), ("running-story", running)):
        assert rows[story_id] == {"id": story_id, "eligible": False,
                                  "reason": "Job %s is queued or running for this story" % job_id,
                                  "busy_job": job_id, "fields_source": "job", "fields_batch": None}
    assert rows["ui-story"] == {"id": "ui-story", "eligible": True, "reason": None, "busy_job": None,
                                "fields_source": "job", "fields_batch": None}
    assert mt.api(s, "GET", "/api/batches/stories")[:3:2] == (400, {"error": "missing ws"})


def test_batch_review_focus_2_saved_settings_that_no_longer_pass_v1(env):
    """Review Focus 2: the original's saved seed image is gone from STATE/uploads."""
    s, state, ws = env["srv"], env["state"], env["ws"]
    gone = "0" * 64 + ".png"
    bt.original(state, ws, "seeded", seed_upload=gone)
    status, _h, payload = mt.api(s, "POST", "/api/batches/preview",
                                 body=bt.body(ws, ["seeded"], [bt.variant("v1", bt.RENDER)]))
    assert status == 200
    assert payload["cells"] == [{"story_id": "seeded", "variant": 1, "fork_id": "seeded-b1-v1",
                                 "status": "invalid", "reason": "seed image upload %s not found" % gone,
                                 "level": None, "diff": [], "warnings": []}]
    assert payload["totals"] == {"jobs": 0, "replan": 0, "stills": 0, "render": 0, "refused": 1,
                                 "text": "0 jobs: 0 re-plan, 0 new stills, 0 render-only; 1 refused"}
    assert payload["number"] == 1 and payload["rows"][0]["fields"]["seed_upload"] == gone
    assert (payload["rows"][0]["fields_source"], payload["rows"][0]["movie"]) == ("job", None)
    assert os.listdir(os.path.join(state, "batches")) == []
    assert not os.path.lexists(lib.story_dir(ws, "seeded-b1-v1"))
    status, _h, payload = mt.api(s, "POST", "/api/batches/preview", body={"ws": ws, "stories": [], "variants": []})
    assert (status, payload) == (400, {"error": "invalid batch", "errors": [
        "stories must be a list of 1 to 24 distinct story IDs", "variants must be a list of 1 to 6 variants"]})
    assert mt.api(s, "POST", "/api/batches/preview", body={"stories": ["seeded"]})[:3:2] == (
        400, {"error": "missing ws"})
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bulk-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_movie_ui_http.py::test_bt15_batch_story_eligibility \
  tests/test_movie_ui_http.py::test_batch_review_focus_2_saved_settings_that_no_longer_pass_v1 2>&1 | tail -1
```

Expected: `2 failed` (the routes answer 404).

- [ ] **Step 3: Implement.**

**3.1.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
STATE_SUBDIRS = ("jobs", "uploads", "traces", "smoke")
```

with:

```python
STATE_SUBDIRS = ("jobs", "uploads", "traces", "smoke", "batches")
```

**3.2.** Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
import fleet_lib
import movie_ui_lib as lib
```

with:

```python
import fleet_lib
import movie_ui_batch as batch
import movie_ui_lib as lib
```

**3.3.** Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
STORE_LOCK = threading.Lock()   # MU18: guards queue.json, server-side status writes, dispatch
```

with:

```python
STORE_LOCK = threading.Lock()   # MU18: guards queue.json, server-side status writes, dispatch
BATCH_LOCK = threading.Lock()   # batch forks BF2: batch.json read-modify-writes, submit planning;
                                # never held together with STORE_LOCK
```

**3.4.** Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
        self.job_cache = {}
```

with:

```python
        self.job_cache = {}
        self.batch_queue = []      # batch forks BF2: IDs of waiting batches, guarded by BATCH_LOCK
        self.batch_thread = None   # the batch-submitter thread while it runs (BF24, BF25)
```

**3.5.** Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    ("POST", r"/api/queue/move", "h_queue_move", "/api/queue/move"),
```

with:

```python
    ("POST", r"/api/queue/move", "h_queue_move", "/api/queue/move"),
    ("POST", r"/api/batches/preview", "h_batch_preview", "/api/batches/preview"),
    ("GET", r"/api/batches/stories", "h_batch_stories", "/api/batches/stories"),
```

**3.6.** Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
MovieUIHandler.h_stories = _h_stories
MovieUIHandler.h_story = _h_story
MovieUIHandler.h_story_save = _h_story_save
MovieUIHandler.h_files = _h_files
```

with:

```python
MovieUIHandler.h_stories = _h_stories
MovieUIHandler.h_story = _h_story
MovieUIHandler.h_story_save = _h_story_save
MovieUIHandler.h_files = _h_files


# ---------------------------------------------------------------------------
# Batch forks: records, eligibility, planning and the preview
# (docs/superpowers/specs/2026-10-30-batch-forks-design.md, Sections 3.1-3.6)
# ---------------------------------------------------------------------------

def batch_path(state, batch_id):
    return os.path.join(state, "batches", batch_id, "batch.json")


def read_batch(state, batch_id):
    """batch.json of one batch as a dict, or None (spec 3.1)."""
    rec = lib.read_json(batch_path(state, batch_id))
    return rec if isinstance(rec, dict) else None


def list_batch_ids(state):
    """Sorted IDs of every batches/<id> directory whose name matches JOB_ID_RE and that has a
    readable batch.json."""
    try:
        names = os.listdir(os.path.join(state, "batches"))
    except OSError:
        return []
    return sorted(n for n in names if lib.JOB_ID_RE.fullmatch(n) and read_batch(state, n) is not None)


def next_batch_number(server, ws_real):
    """BF14 over this STATE's batch records and the workspace's story directory names."""
    records = [read_batch(server.state, i) for i in list_batch_ids(server.state)]
    try:
        names = os.listdir(os.path.join(ws_real, "generated", "stories"))
    except OSError:
        names = []
    return batch.next_number(records, names, ws_real)


def _story_listed(ws_real, story_id):
    """True for a story directory _h_stories lists (spec 3.4: the same directories)."""
    root = os.path.join(ws_real, "generated", "stories")
    sdir = os.path.join(root, story_id)
    return (lib.valid_story_id(story_id) and story_id != lib.SMOKE_STORY_ID and os.path.isdir(sdir)
            and _inside(sdir, root))


def _story_names(ws_real):
    try:
        names = os.listdir(os.path.join(ws_real, "generated", "stories"))
    except OSError:
        names = []
    return sorted(n for n in names if _story_listed(ws_real, n))


def job_index(server, ws_real):
    """Spec 3.4's one pass over the jobs, newest first: ({story_id: last_fields}, {story_id:
    busy job ID}). last_fields is the dict fields of the newest story or movie job of ws_real;
    the busy job is the newest job of ws_real that is queued, starting or running."""
    state = server.state
    queue = lib.read_queue(state)
    last, busy = {}, {}
    for job_id in sorted(lib.list_job_ids(state), reverse=True):
        job = server.job(job_id)
        if job is None or job.get("workspace") != ws_real:
            continue
        story_id = job.get("story_id")
        if job.get("kind") in ("story", "movie") and isinstance(job.get("fields"), dict) \
                and story_id not in last:
            last[story_id] = job["fields"]
        if story_id not in busy and lib.job_state(state, job_id, queue) in ("queued", "starting", "running"):
            busy[story_id] = job_id
    return last, busy


def stored_fields(server, ws_real, story_id):
    """BF41b: (code, fields, batch_id, number) of a story with no last_fields, from its fork.json
    and that fork's batch record. A fork.json that is not a regular file is ignored (isfile
    and not islink is the lstat S_ISREG rule of copy_plan)."""
    path = os.path.join(lib.story_dir(ws_real, story_id), "fork.json")
    fork_rec = lib.read_json(path, None) if os.path.isfile(path) and not os.path.islink(path) else None
    batch_rec = None
    if isinstance(fork_rec, dict) and isinstance(fork_rec.get("batch"), str) \
            and lib.JOB_ID_RE.fullmatch(fork_rec["batch"]):
        record = batch_path(server.state, fork_rec["batch"])
        if os.path.isfile(record):
            batch_rec = lib.read_json(record, {})
    return batch.fork_fallback(fork_rec, batch_rec, story_id, ws_real)


def originals_info(server, ws_real, story_ids):
    """{story_id: {"dir", "has_story", "busy_job", "fields", "code", "batch", "number"}}: what
    batch.plan_cells needs of each original. code is "job" when last_fields exists, else the
    BF41 code; fields is last_fields, else the BF41 "ok" fields, else None."""
    last, busy = job_index(server, ws_real)
    out = {}
    for story_id in story_ids:
        sdir = lib.story_dir(ws_real, story_id)
        info = {"dir": _story_listed(ws_real, story_id),
                "has_story": os.path.isfile(os.path.join(sdir, "story.md")),
                "busy_job": busy.get(story_id), "fields": None, "code": "job", "batch": None, "number": None}
        if story_id in last:
            info["fields"] = last[story_id]
        else:
            code, fields, batch_id, number = stored_fields(server, ws_real, story_id)
            info.update(code=code, fields=fields, batch=batch_id, number=number)
        out[story_id] = info
    return out


def _fields_source(info):
    """("job" or "batch" or None, fields_batch) of spec 3.4."""
    source = {"job": "job", "ok": "batch"}.get(info["code"])
    return source, ({"id": info["batch"], "number": info["number"]} if source == "batch" else None)


def story_status(server, ws_real):
    """GET /api/batches/stories rows (spec 3.4) for the story directories _h_stories lists."""
    names = _story_names(ws_real)
    infos = originals_info(server, ws_real, names)
    rows = []
    for story_id in names:
        info = infos[story_id]
        reason = batch.eligibility_reason(info["busy_job"], info["code"], info["batch"])
        source, source_batch = _fields_source(info)
        rows.append({"id": story_id, "eligible": reason is None, "reason": reason,
                     "busy_job": info["busy_job"], "fields_source": source, "fields_batch": source_batch})
    return rows


def plan_batch(server, clean, number):
    """BF23: (cells, originals) of clean ({"ws", "stories", "variants"}) planned as batch number;
    the one planning function behind preview, submit and each cell's turn."""
    ws_real, state = clean["ws"], server.state
    originals = originals_info(server, ws_real, clean["stories"])
    cells = batch.plan_cells(clean["stories"], clean["variants"], number, ws_real, state, originals,
                             lambda fields: lib.validate_fields(fields, ws_real, state),
                             lambda fork: os.path.lexists(lib.story_dir(ws_real, fork)))
    return cells, originals


PREVIEW_CELL_KEYS = ("story_id", "variant", "fork_id", "status", "reason", "level", "diff", "warnings")


def preview_cell(cell):
    return dict((key, cell[key]) for key in PREVIEW_CELL_KEYS)


def _movie_path(ws_real, story_id):
    path = os.path.join(lib.story_dir(ws_real, story_id), "movie.mp4")
    return path if os.path.isfile(path) else None


def preview_row(ws_real, story_id, info):
    source, source_batch = _fields_source(info)
    fields = info["fields"]
    return {"story_id": story_id,
            "fields": batch.original_fields(fields, story_id, ws_real) if fields is not None else None,
            "fields_source": source, "fields_batch": source_batch, "movie": _movie_path(ws_real, story_id)}


def _batch_request(body):
    """The clean request of a preview or submit body; 400 for a bad ws, then 400 invalid batch."""
    real = resolve_ws(body.get("ws"))
    clean, errors = batch.validate_request(body)
    if errors:
        raise ApiError(400, "invalid batch", errors=errors)
    clean["ws"] = real
    return clean


def _h_batch_stories(self, groups, query, body):
    return 200, {"stories": story_status(self.server, self.ws(query.get("ws")))}


def _h_batch_preview(self, groups, query, body):
    server = self.server
    clean = _batch_request(body)
    number = next_batch_number(server, clean["ws"])
    cells, originals = plan_batch(server, clean, number)
    return 200, {"number": number,
                 "rows": [preview_row(clean["ws"], s, originals[s]) for s in clean["stories"]],
                 "cells": [preview_cell(c) for c in cells], "totals": batch.totals(cells)}


MovieUIHandler.h_batch_stories = _h_batch_stories
MovieUIHandler.h_batch_preview = _h_batch_preview
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bulk-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_movie_ui_http.py::test_bt15_batch_story_eligibility \
  tests/test_movie_ui_http.py::test_batch_review_focus_2_saved_settings_that_no_longer_pass_v1 2>&1 | tail -1
```

Expected: `2 passed`. Run the compile check with `FILES` = `movie_ui_lib.py movie_ui_server.py tests/batch_testutil.py tests/test_movie_ui_http.py`; expected: `compiled 4` twice. Then run the gate block with `N=2`. Expected:
- `GATE PASS`, `lost 4 (listed 4, unexpected 0); new tests 55, not passing 0`, and `offline unchanged`;
- the four `LOST ... listed` lines of the T2 entries: `test_lu1`, `test_mut25_source_scan`, `test_mut18_every_api_route` and `test_mut15`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bulk-wt/qwen-agent-workspace
git add movie_ui_lib.py movie_ui_server.py tests/batch_testutil.py tests/test_movie_ui_http.py
git diff --cached --name-only    # expected: those 4 paths
git commit -m "feat(movie-ui): batch forks eligibility, planning and the preview; STATE batches/ (BF2, BF3, BF22, BF23, BF41; BT15)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Submit, the batch submitter, reconcile and the batch view (BF16-BF20 execution, BF24-BF29, BF35; BT16-BT19, BT22-BT26, BT30, BT32-BT34, Review Focus 1, 3, 4)

This task implements:
- `write_batch` and `new_batch_id` (spec 3.1). `make_batch_record`: ok cells become pending and the rest refused, with `order` per BF27.
- `remove_fork` (BF19).
- BF24, `POST /api/batches`: `_batch_request`, then, under `BATCH_LOCK`, the ID, the number, `plan_batch`, the record, the queue and `_batch_kick`. It answers 409 `every cell was refused` with the cells, and writes no record.
- BF25: `_batch_submitter`.
- BF28 and BF26: `_submit_cell` and `_fork_cell`, the nine steps in order.
  - Step 1 checks pending before `cancel_requested` (Plan ruling BR9).
  - Step 2 is the recompute with `plan_batch`; step 3 the 20 GiB check.
  - Step 4 is `mkdir`, `fork.json` and `shutil.copy2`. A failed `fork.json` write is handled by Plan ruling BR13.
  - Step 5 is the busy re-check, and step 6 is `lib.run_checks` with no lock held.
  - Steps 7 and 9 are the cancel checks; step 8 is `create_compose_job`.
  - BF26's `internal error` refusal uses the stderr line of Plan ruling BR17.
- BF29: `reconcile`. BF35: `batch_view`.
- The routes `GET /api/batches` (this workspace only, newest first, with `done`) and `GET /api/batches/<id>`. Both reconcile.

Tests: BT16-BT19, BT22-BT26, BT32-BT34, and Review Focus 1, 3 and 4, appended to `tests/test_movie_ui_http.py`. BT30 is appended to `tests/test_vlm_lifecycle.py`.

**Files:**
- Modify:
  - `movie_ui_server.py`: the imports `:21-22`; `ROUTES` (the queue/move line from Task 2's edit, and Task 2's stories line); the end of Task 2's section (`MovieUIHandler.h_batch_stories`/`h_batch_preview`; the new section goes after it);
  - `tests/test_movie_ui_http.py`: the end of Task 2's tests (append);
  - `tests/test_vlm_lifecycle.py`: the imports `:27-28`, and the end of the file `:1109-1113` (append).
- Read only: `movie_ui_server.py` `create_compose_job` `:749-760`, `job_summary` `:707-719`; `movie_ui_lib.py` `create_job` `:174-186`, `cancel_job` `:813-826`, `run_checks` `:2065-2076`, `checks_pass` `:1253-1254`, `vlm_restore_wanted` `:461-472`.

**Interfaces:**
- Consumes: Task 1's `batch.copy_plan`, `batch.submit_order`, `batch.MIN_FREE_BYTES`, `batch.BATCH_SCHEMA`, `batch.FORK_SCHEMA`. Task 2's `BATCH_LOCK`, `read_batch`, `batch_path`, `list_batch_ids`, `next_batch_number`, `plan_batch`, `job_index`, `preview_cell`, `_movie_path`, `_batch_request`, `server.batch_queue` and `server.batch_thread`. The existing `create_compose_job(server, fields) -> job_id` (takes `STORE_LOCK`) and `job_summary(server, job_id, queue)`.
- Produces, in `movie_ui_server`:
  - `GIB`, `write_batch(state, rec)`, `new_batch_id(state) -> str`;
  - `make_batch_record(clean, batch_id, number, cells) -> dict`;
  - `remove_fork(fdir, batch_id) -> bool`;
  - `_batch_kick(server)` (the caller holds `BATCH_LOCK`), `_batch_submitter(server)`;
  - `_cell_update(server, batch_id, index, changes) -> rec or None`;
  - `_submit_cell(server, batch_id, index)`, `_fork_cell(server, batch_id, index, made)`;
  - `reconcile(server, batch_id) -> rec or None`, `batch_view(server, rec) -> dict`, `_known_batch(server, batch_id) -> rec` (404 `unknown batch <id>`);
  - the handlers `h_batches`, `h_batch_create`, `h_batch`.
- Produces, in `tests/test_movie_ui_http.py` (Task 4 uses them): `RICH_FILES`, `_fallback_fork(env, monkeypatch, delete_job=True) -> (batch_id, fork_id, job_id)`, `_stories(env) -> {id: row}`, `MISMATCH_REASON`.

- [ ] **Step 1: Write the failing tests.**

**1.1.** Append the HTTP tests. Edit `tests/test_movie_ui_http.py`: replace this text, which occurs exactly once:

```python
    assert mt.api(s, "POST", "/api/batches/preview", body={"stories": ["seeded"]})[:3:2] == (
        400, {"error": "missing ws"})
```

with:

```python
    assert mt.api(s, "POST", "/api/batches/preview", body={"stories": ["seeded"]})[:3:2] == (
        400, {"error": "missing ws"})


RICH_FILES = {"story.md": bt.STORY_MD.encode("utf-8"), "plan.json": b'{"schema": "ltx-movie.plan.v1"}',
              "story_checks.json": b'{"hard": [], "advisory": []}', "manifest.json": b'{"panels": []}',
              "images/panel_01.png": mt.PNG, "images/images.json": b"{}",
              "clips/panel_01.mp4": b"\x00\x00\x00\x18ftypmp42",
              "clips/panel_01.mp4.provenance.json": b'{"output_sha256": "x"}', "movie.mp4": b"movie"}


def test_bt16_preview_equals_submit(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "ronin-rescue")
    bt.original(state, ws, "harbour-chase")
    variants = [bt.variant("v1", bt.RENDER), bt.variant("v2", {"goal": "Keep it tense."}, replace=[("dusk", "dawn")]),
                bt.variant("v3", {})]
    req = bt.body(ws, ["ronin-rescue", "harbour-chase"], variants)
    preview = mt.api(s, "POST", "/api/batches/preview", body=req)[2]
    batch_id = bt.submit(s, ws, req["stories"], variants)
    bt.wait_status(s, batch_id)
    rec = bt.record(state, batch_id)
    keys = ("fork_id", "level", "diff", "warnings")
    assert [[c[k] for k in keys] for c in rec["cells"]] == [[c[k] for k in keys] for c in preview["cells"]]
    assert [c["status"] for c in rec["cells"]] == ["queued", "queued", "refused"] * 2
    assert preview["cells"][1]["warnings"] == ['find text not in this prompt: "dusk"']
    assert preview["totals"]["text"] == "4 jobs: 2 re-plan, 0 new stills, 2 render-only; 2 refused"
    assert rec["number"] == preview["number"] == 1 and rec["workspace"] == ws and rec["cancel_requested"] is False
    assert rec["schema"] == "movie-ui.batch.v1" and rec["stories"] == req["stories"]


def test_bt17_queue_order_after_the_existing_queue(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "s1")
    bt.original(state, ws, "s2")
    other = mt.make_job(state, ["true"], ws, story_id="unrelated")
    variants = [bt.variant("v1", bt.RENDER), bt.variant("v2", {"goal": "Keep it tense."}),
                bt.variant("v3", {"width": 768, "height": 512})]
    batch_id = bt.submit(s, ws, ["s1", "s2"], variants)
    bt.wait_status(s, batch_id)
    rec = bt.record(state, batch_id)
    assert [c["level"] for c in rec["cells"]] == ["render", "replan", "stills"] * 2
    assert rec["order"] == [1, 4, 2, 5, 0, 3]
    assert lib.read_queue(state) == [other] + [rec["cells"][i]["job_id"] for i in (1, 4, 2, 5, 0, 3)]


def test_bt18_a_cell_that_fails_v6_leaves_no_folder(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch, fail={"ronin-rescue-b1-v1": "Error: the dry run failed"})
    bt.original(state, ws, "ronin-rescue")
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER),
                                                   bt.variant("v2", {"gemma": bt.OTHER_GEMMA})])
    bt.wait_status(s, batch_id)
    cells = bt.record(state, batch_id)["cells"]
    assert (cells[0]["status"], cells[0]["reason"]) == ("refused", "V6 dry run: Error: the dry run failed")
    assert not os.path.lexists(lib.story_dir(ws, "ronin-rescue-b1-v1"))
    assert cells[1]["status"] == "queued" and os.path.isdir(lib.story_dir(ws, "ronin-rescue-b1-v2"))
    assert lib.read_queue(state) == [cells[1]["job_id"]]


def test_bt19_a_job_queued_between_preview_and_submit(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "ronin-rescue")
    bt.original(state, ws, "harbour-chase")
    req = bt.body(ws, ["ronin-rescue", "harbour-chase"], [bt.variant("v1", bt.RENDER)])
    assert [c["status"] for c in mt.api(s, "POST", "/api/batches/preview", body=req)[2]["cells"]] == ["ok", "ok"]
    late = mt.make_job(state, ["true"], ws, story_id="ronin-rescue",
                       fields=mt.fields(ws, action="movie", story_id="ronin-rescue"))
    batch_id = bt.submit(s, ws, req["stories"], req["variants"])
    bt.wait_status(s, batch_id)
    cells = bt.record(state, batch_id)["cells"]
    assert (cells[0]["status"], cells[0]["reason"]) == (
        "refused", "story ronin-rescue has a job queued or running (job %s)" % late)
    assert cells[1]["status"] == "queued" and not os.path.lexists(lib.story_dir(ws, "ronin-rescue-b1-v1"))


def test_bt22_every_cell_identical_is_409_and_writes_nothing(env):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.original(state, ws, "ronin-rescue")
    status, _h, payload = mt.api(s, "POST", "/api/batches", body=bt.body(
        ws, ["ronin-rescue"], [bt.variant("v1", {}), bt.variant("v2", {}, append="   ")]))
    assert status == 409 and payload["error"] == "every cell was refused"
    assert [c["reason"] for c in payload["cells"]] == [
        "same settings and prompt as the original; nothing to compare"] * 2
    assert os.listdir(os.path.join(state, "batches")) == []


def test_bt23_not_enough_free_space(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "ronin-rescue")

    class Usage(object):
        total, used, free = 100 * 1024 ** 3, 80 * 1024 ** 3, 20 * 1024 ** 3
    monkeypatch.setattr(srv.shutil, "disk_usage", lambda path: Usage())
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER)])
    bt.wait_status(s, batch_id)
    cell = bt.record(state, batch_id)["cells"][0]
    assert (cell["status"], cell["reason"]) == ("refused", "not enough free space: 20.0 GiB free, this fork "
                                                           "copies 0.0 GiB and at least 20 GiB must stay free")
    assert cell["copy_bytes"] == len(bt.STORY_MD) and not os.path.lexists(lib.story_dir(ws, cell["fork_id"]))


def test_bt24_a_render_fork_runs_on_the_copied_story(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    mt.stub_config(ws, {"ltx-movie run": {"stdout": "=== Phase 1: story ===\n"}})
    sdir, _job = bt.original(state, ws, "ronin-rescue", files=RICH_FILES)
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER)])
    cell = bt.wait_status(s, batch_id)["batch"]["cells"][0]
    fork = lib.story_dir(ws, cell["fork_id"])
    bt.run_job(state, cell["job_id"])
    copied = bt.tree_digests(fork)
    fork_json = lib.read_json(os.path.join(fork, "fork.json"))
    assert copied.pop("fork.json")
    original = bt.tree_digests(sdir)
    assert copied == dict((rel, original[rel]) for rel in original if rel != "movie.mp4")
    assert fork_json == {"schema": "movie-ui.fork.v1", "fork_id": cell["fork_id"], "source_story": "ronin-rescue",
                         "batch": batch_id, "variant": 1, "label": "v1", "level": "render",
                         "diff": [{"key": "model", "from": lib.DEFAULT_MODEL, "to": bt.OTHER_MODEL}],
                         "created": fork_json["created"]}
    runs = [c["argv"] for c in mt.stub_calls(ws) if c["tool"] == "ltx-movie" and c["sub"] == "run"]
    expected = lib.build_argv(mt.fields(ws, action="movie", story_id="ronin-rescue"), ws, state)[2:]
    expected[expected.index("--story-id") + 1] = cell["fork_id"]
    expected[expected.index("--model") + 1] = bt.OTHER_MODEL
    assert runs == [expected]


def test_bt25_the_original_is_byte_identical_after_its_forks_ran(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    sdir, _job = bt.original(state, ws, "ronin-rescue", files=RICH_FILES)
    before = bt.tree_digests(sdir)
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER),
                                                   bt.variant("v2", {"width": 768, "height": 512})])
    for cell in bt.wait_status(s, batch_id)["batch"]["cells"]:
        bt.run_job(state, cell["job_id"])
        assert os.path.isfile(os.path.join(lib.story_dir(ws, cell["fork_id"]), "movie.mp4"))
    assert bt.tree_digests(sdir) == before


def test_bt26_checks_run_with_no_lock_held(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    seen = []

    def grab(out):
        got = srv.STORE_LOCK.acquire(timeout=1)
        out.append(got)
        if got:
            srv.STORE_LOCK.release()

    def wrapped(fields, ws_real, state_dir, py=None):
        observed = {"store_locked": srv.STORE_LOCK.locked(), "batch_locked": srv.BATCH_LOCK.locked()}
        got = []
        other = threading.Thread(target=grab, args=(got,))
        other.start()
        other.join(5)
        observed["acquired"] = got == [True]
        seen.append(observed)
        return [lib.check("V1", "fields", "pass")]
    monkeypatch.setattr(lib, "run_checks", wrapped)
    bt.original(state, ws, "ronin-rescue")
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER)])
    bt.wait_status(s, batch_id)
    assert seen == [{"store_locked": False, "batch_locked": False, "acquired": True}]
    assert bt.record(state, batch_id)["cells"][0]["status"] == "queued"


def _fallback_fork(env, monkeypatch, delete_job=True):
    """BT32's state: a 1 x 1 Render batch whose fork job ran to done and (delete_job) was deleted.
    Returns (batch ID, fork ID, the fork's job ID)."""
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "ronin-rescue")
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER)])
    cell = bt.wait_status(s, batch_id)["batch"]["cells"][0]
    bt.run_job(state, cell["job_id"])
    if delete_job:
        assert mt.api(s, "DELETE", "/api/jobs/" + cell["job_id"])[:3:2] == (200, {"deleted": cell["job_id"]})
    return batch_id, cell["fork_id"], cell["job_id"]


def _stories(env):
    return dict((r["id"], r) for r in mt.api(env["srv"], "GET", "/api/batches/stories?ws=" + env["ws"])[2]["stories"])


def test_bt32_a_fork_whose_job_was_deleted_uses_its_batch_cell(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    batch_id, fork, _job = _fallback_fork(env, monkeypatch)
    assert _stories(env)[fork] == {"id": fork, "eligible": True, "reason": None, "busy_job": None,
                                   "fields_source": "batch", "fields_batch": {"id": batch_id, "number": 1}}
    gemma = [bt.variant("v1", {"gemma": bt.OTHER_GEMMA})]
    preview = mt.api(s, "POST", "/api/batches/preview", body=bt.body(ws, [fork], gemma))[2]
    row = preview["rows"][0]
    assert (row["fields_source"], row["fields_batch"]) == ("batch", {"id": batch_id, "number": 1})
    assert row["fields"]["model"] == bt.OTHER_MODEL and row["movie"] == os.path.join(lib.story_dir(ws, fork), "movie.mp4")
    view = mt.api(s, "GET", "/api/batches/" + batch_id)[2]["view"]
    assert view["cells"] == [{"state": "job deleted", "job": None, "dir": True,
                              "movie": os.path.join(lib.story_dir(ws, fork), "movie.mp4")}]
    second = bt.submit(s, ws, [fork], gemma)
    cell = bt.wait_status(s, second)["batch"]["cells"][0]
    assert (cell["status"], cell["fork_id"]) == ("queued", fork + "-b2-v1")
    fields = lib.read_job(lib.job_dir(state, cell["job_id"]))["fields"]
    assert (fields["model"], fields["gemma"], fields["story_id"]) == (bt.OTHER_MODEL, bt.OTHER_GEMMA, fork + "-b2-v1")


def test_bt33_last_fields_win_over_the_batch_cell(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    batch_id, fork, _job = _fallback_fork(env, monkeypatch, delete_job=False)
    rec = bt.record(state, batch_id)
    rec["cells"][0]["fields"]["model"] = "/models/rewritten"
    lib.write_json_atomic(os.path.join(state, "batches", batch_id, "batch.json"), rec)
    assert _stories(env)[fork] == {"id": fork, "eligible": True, "reason": None, "busy_job": None,
                                   "fields_source": "job", "fields_batch": None}
    preview = mt.api(s, "POST", "/api/batches/preview",
                     body=bt.body(ws, [fork], [bt.variant("v1", {"gemma": bt.OTHER_GEMMA})]))[2]
    assert preview["rows"][0]["fields"]["model"] == bt.OTHER_MODEL
    assert (preview["rows"][0]["fields_source"], preview["rows"][0]["fields_batch"]) == ("job", None)


MISMATCH_REASON = ("Its job was deleted and batch %s has no matching record of this fork: no saved Compose "
                   "settings to fork")


@pytest.mark.parametrize("case", ["no-fork-json", "cell-cancelled", "other-workspace", "variant-2"])
def test_bt34_a_missing_or_mismatched_record_leaves_the_fork_ineligible(env, monkeypatch, case):
    s, state, ws = env["srv"], env["state"], env["ws"]
    batch_id, fork, _job = _fallback_fork(env, monkeypatch)
    fork_json = os.path.join(lib.story_dir(ws, fork), "fork.json")
    if case == "no-fork-json":
        os.unlink(fork_json)
        reason = "Started from the command line: no saved Compose settings to fork"
        refusal = "story %s has no saved Compose settings (it was started from the command line)" % fork
    else:
        path = fork_json if case == "variant-2" else os.path.join(state, "batches", batch_id, "batch.json")
        data = lib.read_json(path)
        if case == "cell-cancelled":
            data["cells"][0]["status"] = "cancelled"
        elif case == "other-workspace":
            data["workspace"] = "/elsewhere/qwen-agent-workspace"
        else:
            data["variant"] = 2
        lib.write_json_atomic(path, data)
        reason = MISMATCH_REASON % batch_id
        refusal = ("story %s has no saved Compose settings (its job was deleted and batch %s has no matching "
                   "record of it)" % (fork, batch_id))
    assert _stories(env)[fork] == {"id": fork, "eligible": False, "reason": reason, "busy_job": None,
                                   "fields_source": None, "fields_batch": None}
    preview = mt.api(s, "POST", "/api/batches/preview",
                     body=bt.body(ws, [fork], [bt.variant("v1", {"gemma": bt.OTHER_GEMMA})]))[2]
    assert preview["rows"][0]["fields"] is None and preview["rows"][0]["fields_source"] is None
    assert (preview["cells"][0]["status"], preview["cells"][0]["reason"]) == ("refused", refusal)


def test_batch_review_focus_1_non_ascii_labels_and_prompt_edits(env, monkeypatch):
    """Review Focus 1: a label, find/replace text and an appended paragraph with accents and symbols."""
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    narrative = "A ronin rescues a child at dusk — before the café burns."
    bt.original(state, ws, "ronin-rescue", narrative=narrative)
    label = "café ☕"
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant(label, {}, append="Snow falls on the café.",
                                                              replace=[("dusk", "l’aube")])])
    cell = bt.wait_status(s, batch_id)["batch"]["cells"][0]
    edited = "A ronin rescues a child at l’aube — before the café burns.\n\nSnow falls on the café."
    job = lib.read_job(lib.job_dir(state, cell["job_id"]))
    assert job["fields"]["narrative"] == edited and job["argv"][2] == edited
    assert cell["diff"] == [{"key": "narrative", "from": narrative, "to": edited}] and cell["level"] == "replan"
    assert bt.record(state, batch_id)["variants"][0]["label"] == label
    assert lib.read_json(os.path.join(lib.story_dir(ws, cell["fork_id"]), "fork.json"))["label"] == label


def test_batch_review_focus_3_two_batches_submitted_at_once(env, monkeypatch):
    """Review Focus 3: a double click, or two tabs, submit a batch of the same story at once."""
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "ronin-rescue")
    results = []

    def post():
        results.append(mt.api(s, "POST", "/api/batches",
                              body=bt.body(ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER)])))
    threads = [threading.Thread(target=post) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert sorted(r[0] for r in results) == [201, 201]
    assert sorted(r[2]["batch"]["number"] for r in results) == [1, 2]
    forks = []
    for batch_id in set(r[2]["batch"]["id"] for r in results):
        cell = bt.wait_status(s, batch_id)["batch"]["cells"][0]
        assert cell["status"] == "queued"
        forks.append(cell["fork_id"])
    assert sorted(forks) == ["ronin-rescue-b1-v1", "ronin-rescue-b2-v1"] and len(lib.read_queue(state)) == 2


def test_batch_review_focus_4_batches_are_per_workspace(env, monkeypatch, tmp_path):
    """Review Focus 4: the Workspace selector names another workspace (another release)."""
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    other = mt.make_stub_workspace(tmp_path / "second")
    bt.original(state, ws, "ronin-rescue")
    bt.original(state, other, "ronin-rescue")
    first = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER)])
    created = bt.wait_status(s, first)["batch"]["created"]
    assert mt.api(s, "GET", "/api/batches?ws=" + other)[:3:2] == (200, {"batches": []})
    second = bt.submit(s, other, ["ronin-rescue"], [bt.variant("v1", bt.RENDER)])
    payload = bt.wait_status(s, second)
    assert payload["batch"]["number"] == 1 and payload["batch"]["cells"][0]["fork_id"] == "ronin-rescue-b1-v1"
    assert mt.api(s, "GET", "/api/batches?ws=" + ws)[2] == {"batches": [
        {"id": first, "number": 1, "created": created, "status": "submitted", "cells": 1, "done": 0}]}
    assert mt.api(s, "GET", "/api/batches")[:3:2] == (400, {"error": "missing ws"})
```

**1.2.** Edit `tests/test_vlm_lifecycle.py`: replace this text, which occurs exactly once:

```python
import movie_ui_testutil as mt
import movie_ui_lib as lib
```

with:

```python
import batch_testutil as bt
import movie_ui_testutil as mt
import movie_ui_lib as lib
```

**1.3.** Append BT30. Edit `tests/test_vlm_lifecycle.py`: replace this text, which occurs exactly once:

```python
        for pid in sleepers:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except OSError:
                pass
```

with:

```python
        for pid in sleepers:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except OSError:
                pass


# --- batch forks BT30 (docs/superpowers/specs/2026-10-30-batch-forks-design.md, Section 7) -----

def test_bt30_fork_jobs_record_their_vlm_policy(http_env, monkeypatch):
    s, ws, state = http_env["srv"], http_env["ws"], http_env["state"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "ronin-rescue")
    variants = [bt.variant("v1", bt.RENDER), bt.variant("v2", {"width": 768, "height": 512}),
                bt.variant("v3", {"goal": "Keep it tense."})]
    batch_id = bt.submit(s, ws, ["ronin-rescue"], variants)
    cells = bt.wait_status(s, batch_id)["batch"]["cells"]
    render, stills, replan = (c["job_id"] for c in cells)
    assert [lib.read_job(lib.job_dir(state, j))["vlm"] for j in (render, stills, replan)] == [
        "forbidden", "forbidden", "required"]
    assert lib.read_queue(state) == [replan, stills, render]
    assert lib.vlm_restore_wanted(state) == (True, "next job %s needs it" % replan)
    lib.write_status(lib.job_dir(state, replan), {"state": "done", "exit_code": 0, "ended": lib.utc_now()})
    lib.write_queue(state, [render])
    assert lib.vlm_restore_wanted(state) == (False, "next job %s runs without it" % render)
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bulk-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_movie_ui_http.py::test_bt16_preview_equals_submit \
  tests/test_movie_ui_http.py::test_bt17_queue_order_after_the_existing_queue \
  tests/test_movie_ui_http.py::test_bt18_a_cell_that_fails_v6_leaves_no_folder \
  tests/test_movie_ui_http.py::test_bt19_a_job_queued_between_preview_and_submit \
  tests/test_movie_ui_http.py::test_bt22_every_cell_identical_is_409_and_writes_nothing \
  tests/test_movie_ui_http.py::test_bt23_not_enough_free_space \
  tests/test_movie_ui_http.py::test_bt24_a_render_fork_runs_on_the_copied_story \
  tests/test_movie_ui_http.py::test_bt25_the_original_is_byte_identical_after_its_forks_ran \
  tests/test_movie_ui_http.py::test_bt26_checks_run_with_no_lock_held \
  tests/test_movie_ui_http.py::test_bt32_a_fork_whose_job_was_deleted_uses_its_batch_cell \
  tests/test_movie_ui_http.py::test_bt33_last_fields_win_over_the_batch_cell \
  tests/test_movie_ui_http.py::test_bt34_a_missing_or_mismatched_record_leaves_the_fork_ineligible \
  tests/test_movie_ui_http.py::test_batch_review_focus_1_non_ascii_labels_and_prompt_edits \
  tests/test_movie_ui_http.py::test_batch_review_focus_3_two_batches_submitted_at_once \
  tests/test_movie_ui_http.py::test_batch_review_focus_4_batches_are_per_workspace \
  tests/test_vlm_lifecycle.py::test_bt30_fork_jobs_record_their_vlm_policy 2>&1 | tail -1
```

Expected: `19 failed` (`POST /api/batches` and `GET /api/batches/<id>` answer 404: only Task 2's preview and stories routes exist).

- [ ] **Step 3: Implement.**

**3.1.** Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
import shlex
import signal
```

with:

```python
import shlex
import shutil
import signal
```

**3.2.** Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    ("POST", r"/api/queue/move", "h_queue_move", "/api/queue/move"),
```

with:

```python
    ("POST", r"/api/queue/move", "h_queue_move", "/api/queue/move"),
    ("GET", r"/api/batches", "h_batches", "/api/batches"),
    ("POST", r"/api/batches", "h_batch_create", "/api/batches"),
```

**3.3.** Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    ("GET", r"/api/batches/stories", "h_batch_stories", "/api/batches/stories"),
```

with:

```python
    ("GET", r"/api/batches/stories", "h_batch_stories", "/api/batches/stories"),
    ("GET", r"/api/batches/" + _ID, "h_batch", "/api/batches/" + _SAMPLE_ID),
```

**3.4.** Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
MovieUIHandler.h_batch_stories = _h_batch_stories
MovieUIHandler.h_batch_preview = _h_batch_preview
```

with:

```python
MovieUIHandler.h_batch_stories = _h_batch_stories
MovieUIHandler.h_batch_preview = _h_batch_preview


# ---------------------------------------------------------------------------
# Batch forks: submit, the batch submitter, reconcile and the batch page
# (docs/superpowers/specs/2026-10-30-batch-forks-design.md, Sections 3.1, 4.1-4.5)
# ---------------------------------------------------------------------------

GIB = float(1024 ** 3)


def write_batch(state, rec):
    lib.write_json_atomic(batch_path(state, rec["id"]), rec)


def new_batch_id(state):
    """A fresh batch ID in the job-ID format, drawn again while batches/<id> exists (spec 3.1)."""
    while True:
        batch_id = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(2)
        if not os.path.lexists(os.path.join(state, "batches", batch_id)):
            return batch_id


def make_batch_record(clean, batch_id, number, cells):
    """The batch.json of a submit (spec 3.1, BF24): "ok" cells are pending, the others refused,
    and order is the BF27 submit order."""
    now = lib.utc_now()
    rcells = [{"story_id": c["story_id"], "variant": c["variant"], "fork_id": c["fork_id"],
               "status": "pending" if c["status"] == "ok" else "refused", "reason": c["reason"],
               "level": c["level"], "diff": c["diff"], "warnings": c["warnings"], "fields": None,
               "job_id": None, "copy_bytes": 0, "updated": now} for c in cells]
    return {"schema": batch.BATCH_SCHEMA, "id": batch_id, "number": number, "workspace": clean["ws"],
            "created": now, "status": "waiting", "cancel_requested": False,
            "stories": list(clean["stories"]), "variants": clean["variants"],
            "order": batch.submit_order(rcells, clean["stories"]), "cells": rcells}


def remove_fork(fdir, batch_id):
    """BF19: shutil.rmtree(fdir) only when <fdir>/fork.json names batch_id and fdir's own name;
    otherwise leave it and say so on stderr. Returns True when removed."""
    rec = lib.read_json(os.path.join(fdir, "fork.json"), None)
    if isinstance(rec, dict) and rec.get("batch") == batch_id and rec.get("fork_id") == os.path.basename(fdir):
        shutil.rmtree(fdir)
        return True
    sys.stderr.write("movie-ui: batch %s: not removing %s (no matching fork.json)\n" % (batch_id, fdir))
    return False


def _batch_kick(server):
    """BF24 step 4: start the batch submitter unless it runs. The caller holds BATCH_LOCK."""
    if server.batch_thread is None or not server.batch_thread.is_alive():
        server.batch_thread = threading.Thread(target=_batch_submitter, args=(server,),
                                               name="batch-submitter", daemon=True)
        server.batch_thread.start()


def _batch_submitter(server):
    """BF25: submit the queued batches one at a time, each cell in the batch's order."""
    state = server.state
    while True:
        with BATCH_LOCK:
            if not server.batch_queue:
                server.batch_thread = None
                return
            batch_id = server.batch_queue.pop(0)
            rec = read_batch(state, batch_id)
            if rec is None or rec.get("status") != "waiting":
                continue
            rec["status"] = "submitting"
            write_batch(state, rec)
        for index in rec["order"]:
            _submit_cell(server, batch_id, index)
        with BATCH_LOCK:
            rec = read_batch(state, batch_id)
            if rec is not None:
                rec["status"] = "cancelled" if rec.get("cancel_requested") else "submitted"
                write_batch(state, rec)


def _cell_update(server, batch_id, index, changes):
    """Under BATCH_LOCK: apply changes to one cell of batch.json with a new "updated"; returns the
    record, or None when it is gone."""
    with BATCH_LOCK:
        rec = read_batch(server.state, batch_id)
        if rec is None:
            return None
        rec["cells"][index].update(changes, updated=lib.utc_now())
        write_batch(server.state, rec)
        return rec


def _submit_cell(server, batch_id, index):
    """BF28 step 1, then steps 2-9; an exception refuses the cell and removes its fork (BF26)."""
    with BATCH_LOCK:
        rec = read_batch(server.state, batch_id)
        if rec is None or rec["cells"][index].get("status") != "pending":
            return
        if rec.get("cancel_requested"):
            rec["cells"][index].update(status="cancelled", reason="batch cancelled", updated=lib.utc_now())
            write_batch(server.state, rec)
            return
        rec["cells"][index].update(status="forking", reason=None, updated=lib.utc_now())
        write_batch(server.state, rec)
    made = []
    try:
        _fork_cell(server, batch_id, index, made)
    except Exception as e:
        if made:
            remove_fork(made[0], batch_id)
        sys.stderr.write("movie-ui: batch %s: cell %d: internal error: %s: %s\n"
                         % (batch_id, index, type(e).__name__, e))
        _cell_update(server, batch_id, index,
                     {"status": "refused", "reason": "internal error: %s: %s" % (type(e).__name__, e)})


def _fork_cell(server, batch_id, index, made):
    """BF28 steps 2-9 for one forking cell. made holds the fork directory while an exception
    should remove it."""
    state = server.state
    rec = read_batch(state, batch_id)
    if rec is None:
        return
    ws_real = rec["workspace"]
    clean = {"ws": ws_real, "stories": rec["stories"], "variants": rec["variants"]}
    built = plan_batch(server, clean, rec["number"])[0][index]                       # 2
    if built["status"] != "ok":
        _cell_update(server, batch_id, index, {"status": "refused", "reason": built["reason"]})
        return
    story_id, fid, level = built["story_id"], built["fork_id"], built["level"]
    sdir, fdir = lib.story_dir(ws_real, story_id), lib.story_dir(ws_real, fid)
    plan = batch.copy_plan(sdir, level)                                               # 3
    copy_bytes = sum(n for _rel, n in plan)
    free = shutil.disk_usage(os.path.join(ws_real, "generated", "stories")).free
    if free - copy_bytes < batch.MIN_FREE_BYTES:
        _cell_update(server, batch_id, index, {"status": "refused", "copy_bytes": copy_bytes, "reason":
                     "not enough free space: %.1f GiB free, this fork copies %.1f GiB and at least 20 GiB "
                     "must stay free" % (free / GIB, copy_bytes / GIB)})
        return
    try:                                                                              # 4
        os.mkdir(fdir)
    except FileExistsError:
        _cell_update(server, batch_id, index, {"status": "refused", "copy_bytes": copy_bytes,
                                               "reason": "fork ID %s already exists; it is never overwritten" % fid})
        return
    made.append(fdir)
    fork_rec = {"schema": batch.FORK_SCHEMA, "fork_id": fid, "source_story": story_id, "batch": batch_id,
                "variant": built["variant"], "label": rec["variants"][built["variant"] - 1]["label"],
                "level": level, "diff": built["diff"], "created": lib.utc_now()}
    try:
        lib.write_json_atomic(os.path.join(fdir, "fork.json"), fork_rec)
        for rel, _n in plan:
            target = os.path.join(fdir, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(os.path.join(sdir, rel), target)
    except OSError as e:
        if os.path.lexists(os.path.join(fdir, "fork.json")):
            remove_fork(fdir, batch_id)
        else:
            os.rmdir(fdir)
        del made[:]
        _cell_update(server, batch_id, index, {"status": "refused", "copy_bytes": copy_bytes, "reason":
                     "copy failed: %s: %s" % (e.strerror or e, e.filename or fdir)})
        return
    busy = job_index(server, ws_real)[1].get(story_id)                                # 5
    if busy is not None:
        remove_fork(fdir, batch_id)
        del made[:]
        _cell_update(server, batch_id, index, {"status": "refused", "copy_bytes": copy_bytes, "reason":
                     "story %s got a job (%s) while it was being forked; fork it again later" % (story_id, busy)})
        return
    checks = lib.run_checks(built["fields"], ws_real, state)                          # 6, no lock held
    if not lib.checks_pass(checks):
        remove_fork(fdir, batch_id)
        del made[:]
        _cell_update(server, batch_id, index, {"status": "refused", "copy_bytes": copy_bytes, "reason": "\n".join(
            "%s %s: %s" % (c["id"], c["name"], c["detail"]) for c in checks if c["status"] == "fail")})
        return
    with BATCH_LOCK:                                                                  # 7
        rec = read_batch(state, batch_id)
        if rec is None or rec.get("cancel_requested"):
            remove_fork(fdir, batch_id)
            del made[:]
            if rec is not None:
                rec["cells"][index].update(status="cancelled", reason="batch cancelled", copy_bytes=copy_bytes,
                                           updated=lib.utc_now())
                write_batch(state, rec)
            return
    job_id = create_compose_job(server, built["fields"])                              # 8
    del made[:]
    with BATCH_LOCK:                                                                  # 9
        rec = read_batch(state, batch_id)
        if rec is not None:
            rec["cells"][index].update(status="queued", reason=None, job_id=job_id, fields=built["fields"],
                                       level=level, diff=built["diff"], warnings=built["warnings"],
                                       copy_bytes=copy_bytes, updated=lib.utc_now())
            write_batch(state, rec)
        late = rec is None or bool(rec.get("cancel_requested"))
    if late:
        with STORE_LOCK:
            result = lib.cancel_job(state, job_id)
        if rec is not None:
            reconcile(server, batch_id)
        elif result == "cancelled":
            remove_fork(fdir, batch_id)


def reconcile(server, batch_id):
    """BF29 under BATCH_LOCK: every queued cell whose job was cancelled before it started loses its
    fork directory and becomes cancelled. Returns the record, or None when it is gone."""
    state = server.state
    with BATCH_LOCK:
        rec = read_batch(state, batch_id)
        if rec is None:
            return None
        changed = False
        for cell in rec["cells"]:
            job_id = cell.get("job_id")
            if cell.get("status") != "queued" or not (isinstance(job_id, str) and lib.JOB_ID_RE.fullmatch(job_id)):
                continue
            status = lib.read_status(lib.job_dir(state, job_id)) or {}
            if status.get("state") == "cancelled" and status.get("started") is None:
                remove_fork(lib.story_dir(rec["workspace"], cell["fork_id"]), batch_id)
                cell.update(status="cancelled", reason="cancelled before it started", updated=lib.utc_now())
                changed = True
        if changed:
            write_batch(state, rec)
        return rec


def batch_view(server, rec):
    """The "view" of GET /api/batches/<id> (BF35): the originals' movies and, parallel to
    rec["cells"], each cell's display state, job summary, movie and whether its directory exists."""
    state, ws_real = server.state, rec["workspace"]
    queue = lib.read_queue(state)
    cells = []
    for cell in rec["cells"]:
        shown, job = cell["status"], None
        job_id = cell.get("job_id")
        if shown == "queued" and isinstance(job_id, str) and lib.JOB_ID_RE.fullmatch(job_id):
            if os.path.isdir(lib.job_dir(state, job_id)):
                job = job_summary(server, job_id, queue)
            shown = job["state"] if job is not None else "job deleted"
        cells.append({"state": shown, "job": job, "movie": _movie_path(ws_real, cell["fork_id"]),
                      "dir": os.path.isdir(lib.story_dir(ws_real, cell["fork_id"]))})
    return {"originals": dict((s, _movie_path(ws_real, s)) for s in rec["stories"]), "cells": cells}


def _known_batch(server, batch_id):
    """Reconcile batch_id (BF29) and return its record, or ApiError(404)."""
    rec = reconcile(server, batch_id)
    if rec is None:
        raise ApiError(404, "unknown batch %s" % batch_id)
    return rec


def _h_batches(self, groups, query, body):
    server = self.server
    real = self.ws(query.get("ws"))
    queue = lib.read_queue(server.state)
    out = []
    for batch_id in sorted(list_batch_ids(server.state), reverse=True):
        rec = read_batch(server.state, batch_id)
        if rec is None or rec.get("workspace") != real:
            continue
        rec = reconcile(server, batch_id) or rec
        done = sum(1 for c in rec["cells"] if isinstance(c.get("job_id"), str)
                   and lib.JOB_ID_RE.fullmatch(c["job_id"])
                   and lib.job_state(server.state, c["job_id"], queue) == "done")
        out.append({"id": rec["id"], "number": rec["number"], "created": rec["created"],
                    "status": rec["status"], "cells": len(rec["cells"]), "done": done})
    return 200, {"batches": out}


def _h_batch_create(self, groups, query, body):
    server = self.server
    state = server.state
    clean = _batch_request(body)
    with BATCH_LOCK:
        batch_id = new_batch_id(state)
        number = next_batch_number(server, clean["ws"])
        cells, _originals = plan_batch(server, clean, number)
        if not any(c["status"] == "ok" for c in cells):
            raise ApiError(409, "every cell was refused", cells=[preview_cell(c) for c in cells])
        rec = make_batch_record(clean, batch_id, number, cells)
        lib.make_dir(os.path.dirname(batch_path(state, batch_id)))
        write_batch(state, rec)
        server.batch_queue.append(batch_id)
        _batch_kick(server)
    pending = sum(1 for c in rec["cells"] if c["status"] == "pending")
    return 201, {"batch": {"id": batch_id, "number": number, "status": "waiting"}, "pending": pending,
                 "refused": len(rec["cells"]) - pending}


def _h_batch(self, groups, query, body):
    rec = _known_batch(self.server, groups[0])
    return 200, {"batch": rec, "view": batch_view(self.server, rec)}


MovieUIHandler.h_batches = _h_batches
MovieUIHandler.h_batch_create = _h_batch_create
MovieUIHandler.h_batch = _h_batch
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bulk-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_movie_ui_http.py::test_bt16_preview_equals_submit \
  tests/test_movie_ui_http.py::test_bt17_queue_order_after_the_existing_queue \
  tests/test_movie_ui_http.py::test_bt18_a_cell_that_fails_v6_leaves_no_folder \
  tests/test_movie_ui_http.py::test_bt19_a_job_queued_between_preview_and_submit \
  tests/test_movie_ui_http.py::test_bt22_every_cell_identical_is_409_and_writes_nothing \
  tests/test_movie_ui_http.py::test_bt23_not_enough_free_space \
  tests/test_movie_ui_http.py::test_bt24_a_render_fork_runs_on_the_copied_story \
  tests/test_movie_ui_http.py::test_bt25_the_original_is_byte_identical_after_its_forks_ran \
  tests/test_movie_ui_http.py::test_bt26_checks_run_with_no_lock_held \
  tests/test_movie_ui_http.py::test_bt32_a_fork_whose_job_was_deleted_uses_its_batch_cell \
  tests/test_movie_ui_http.py::test_bt33_last_fields_win_over_the_batch_cell \
  tests/test_movie_ui_http.py::test_bt34_a_missing_or_mismatched_record_leaves_the_fork_ineligible \
  tests/test_movie_ui_http.py::test_batch_review_focus_1_non_ascii_labels_and_prompt_edits \
  tests/test_movie_ui_http.py::test_batch_review_focus_3_two_batches_submitted_at_once \
  tests/test_movie_ui_http.py::test_batch_review_focus_4_batches_are_per_workspace \
  tests/test_vlm_lifecycle.py::test_bt30_fork_jobs_record_their_vlm_policy 2>&1 | tail -1
```

Expected: `19 passed` (about 40 s; BT24, BT25 and BT32-BT34 run the stub `ltx-movie` through the real runner). Run the compile check with `FILES` = `movie_ui_server.py tests/test_movie_ui_http.py tests/test_vlm_lifecycle.py`; expected: `compiled 3` twice. Then run the gate block with `N=3`. Expected: `GATE PASS`, `lost 4 (listed 4, unexpected 0); new tests 74, not passing 0`, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bulk-wt/qwen-agent-workspace
git add movie_ui_server.py tests/test_movie_ui_http.py tests/test_vlm_lifecycle.py
git diff --cached --name-only    # expected: those 3 paths
git commit -m "feat(movie-ui): batch submit, the batch submitter, fork copies, reconcile and the batch view (BF16-BF20, BF24-BF29, BF35; BT16-BT19, BT22-BT26, BT30, BT32-BT34)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Cancel, restart, submit remaining and delete (BF30-BF34; BT14, BT20, BT21, BT27-BT29, BT35)

This task implements:
- BF30: `_batch_job_cancelled`, called by `_h_job_cancel` once `cancel_job` gives `"cancelled"`, after `STORE_LOCK` is released.
- BF31: `POST /api/batches/<id>/cancel`.
  - It answers 409 `batch <id> has nothing to cancel` when no cell is pending or forking and no fork job is queued, starting or running.
  - Otherwise it does the four steps in order. It cancels the job of every queued cell (Plan ruling BR23).
- BF32: `batch_recovery(state)`, called in `main` right after `startup_recovery`. A recovered queued cell gets its job's fields (Plan ruling BR15).
- BF33: `POST /api/batches/<id>/resume`.
- BF34: `DELETE /api/batches/<id>`, which answers 409 while the batch is waiting or submitting and 500 on a failed `rmtree`.
- Every `<id>` handler first reconciles (BF29) through `_known_batch`.

Tests: BT14, BT20, BT21, BT27, BT29 and BT35, appended to `tests/test_movie_ui_http.py`; BT28, appended to `tests/test_movie_ui_jobs.py`.

**Files:**
- Modify:
  - `movie_ui_server.py`: `ROUTES` (Task 3's `GET /api/batches/<id>` line); `_h_job_cancel` `:855-858`; `main` `:682-684`; the end of Task 3's section (`MovieUIHandler.h_batches`/`h_batch_create`/`h_batch`; the new section goes after it);
  - `tests/test_movie_ui_http.py`: the end of Task 3's tests (append);
  - `tests/test_movie_ui_jobs.py`: the end of the file `:436-438` (append).
- Read only: `movie_ui_lib.py` `startup_recovery` `:788-802`, `run_job`'s cancelled-before-start path `:314-318`; `bin/movie-ui-job`.

**Interfaces:**
- Consumes: Task 3's `reconcile`, `remove_fork`, `_known_batch`, `_batch_kick`, `write_batch`, `make_batch_record`, `new_batch_id`; Task 2's `read_batch`, `list_batch_ids`, `batch_path`, `plan_batch`; Task 3's test helpers `_fallback_fork`, `_stories`.
- Produces, in `movie_ui_server`: `ACTIVE_JOB_STATES`, `_batch_job_cancelled(server, job_id)`, `batch_recovery(state)`, and the handlers `h_batch_cancel`, `h_batch_resume`, `h_batch_delete`. `main` calls `batch_recovery(state)`.

- [ ] **Step 1: Write the failing tests.**

**1.1.** Append the HTTP tests. Edit `tests/test_movie_ui_http.py`: replace this text, which occurs exactly once:

```python
    assert mt.api(s, "GET", "/api/batches")[:3:2] == (400, {"error": "missing ws"})
```

with:

```python
    assert mt.api(s, "GET", "/api/batches")[:3:2] == (400, {"error": "missing ws"})


BATCH_ROUTES = [("GET", "/api/batches"), ("POST", "/api/batches"), ("POST", "/api/batches/preview"),
                ("GET", "/api/batches/stories"), ("GET", "/api/batches/" + srv._SAMPLE_ID),
                ("DELETE", "/api/batches/" + srv._SAMPLE_ID), ("POST", "/api/batches/%s/cancel" % srv._SAMPLE_ID),
                ("POST", "/api/batches/%s/resume" % srv._SAMPLE_ID)]


def test_bt14_every_batch_route_needs_the_token(env):
    s = env["srv"]
    assert [(m, sample) for m, _r, _n, sample in srv.ROUTES if sample.startswith("/api/batches")] == BATCH_ROUTES
    for method, regex, name, sample in srv.ROUTES:
        if (method, sample) not in BATCH_ROUTES:
            continue
        assert re.fullmatch(regex, sample) and hasattr(srv.MovieUIHandler, name), name
        for token in (None, "wrong-token"):
            status, _h, payload = mt.api(s, method, sample, body={} if method == "POST" else None, token=token)
            assert (status, payload) == (401, {"error": "missing or invalid token"}), (method, sample, token)
    for method, sample in BATCH_ROUTES[4:]:
        assert mt.api(s, method, sample, body={} if method == "POST" else None)[:3:2] == (
            404, {"error": "unknown batch %s" % srv._SAMPLE_ID}), (method, sample)
    assert mt.api(s, "PUT", "/api/batches", body={})[:3:2] == (405, {"error": "method not allowed"})


def test_bt20_cancel_batch(env, monkeypatch):
    import fcntl
    s, state, ws = env["srv"], env["state"], env["ws"]
    gate = threading.Event()
    calls = bt.passing_checks(monkeypatch, gate={"ronin-rescue-b1-v3": gate})
    bt.original(state, ws, "ronin-rescue")
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v%d" % m, {"model": "/models/m%d" % m})
                                                   for m in range(1, 5)])
    mt.wait_until(lambda: "ronin-rescue-b1-v3" in calls, 30)
    cells = bt.record(state, batch_id)["cells"]
    assert [c["status"] for c in cells] == ["queued", "queued", "forking", "pending"]
    forks = [lib.story_dir(ws, c["fork_id"]) for c in cells]
    running, queued = cells[0]["job_id"], cells[1]["job_id"]
    jdir = lib.job_dir(state, running)
    lib.write_queue(state, [queued])
    lib.write_status(jdir, {"state": "running", "dispatched": lib.utc_now(), "runner_pid": os.getpid(),
                            "pgid": None, "started": lib.utc_now()})
    holder = os.open(os.path.join(jdir, "lock"), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(holder, fcntl.LOCK_EX)
    try:
        status, _h, payload = mt.api(s, "POST", "/api/batches/%s/cancel" % batch_id, body={})
        assert (status, payload) == (200, {"status": "cancelled", "cancelled": [queued], "cancelling": [running]})
        gate.set()
        mt.wait_until(lambda: s.server.batch_thread is None, 30)
    finally:
        os.close(holder)
    rec = bt.record(state, batch_id)
    assert [(c["status"], c["reason"]) for c in rec["cells"]] == [
        ("queued", None), ("cancelled", "cancelled before it started"), ("cancelled", "batch cancelled"),
        ("cancelled", "batch cancelled")]
    assert (rec["status"], rec["cancel_requested"]) == ("cancelled", True)
    assert os.path.isdir(forks[0]) and not any(os.path.lexists(f) for f in forks[1:])
    assert os.path.exists(os.path.join(jdir, "cancel")) and calls == [c["fork_id"] for c in cells[:3]]
    lib.write_status(jdir, {"state": "cancelled", "dispatched": lib.utc_now(), "runner_pid": os.getpid(),
                            "pgid": None, "started": lib.utc_now(), "exit_code": -15, "ended": lib.utc_now()})
    assert mt.api(s, "POST", "/api/batches/%s/cancel" % batch_id, body={})[:3:2] == (
        409, {"error": "batch %s has nothing to cancel" % batch_id})
    assert mt.api(s, "GET", "/api/batches/" + batch_id)[2]["view"]["cells"][0]["state"] == "cancelled"
    assert os.path.isdir(forks[0])


def test_bt21_delete_batch(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    gate = threading.Event()
    calls = bt.passing_checks(monkeypatch, gate={"ronin-rescue-b1-v1": gate})
    bt.original(state, ws, "ronin-rescue")
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER),
                                                   bt.variant("v2", {"gemma": bt.OTHER_GEMMA})])
    mt.wait_until(lambda: "ronin-rescue-b1-v1" in calls, 30)
    try:
        assert mt.api(s, "DELETE", "/api/batches/" + batch_id)[:3:2] == (
            409, {"error": "batch %s is still submitting; cancel it first" % batch_id})
    finally:
        gate.set()
    cells = bt.wait_status(s, batch_id)["batch"]["cells"]
    assert mt.api(s, "DELETE", "/api/batches/" + batch_id)[:3:2] == (200, {"deleted": batch_id})
    assert not os.path.exists(os.path.join(state, "batches", batch_id))
    assert mt.api(s, "GET", "/api/batches/" + batch_id)[:3:2] == (404, {"error": "unknown batch %s" % batch_id})
    for cell in cells:
        assert os.path.isfile(os.path.join(lib.story_dir(ws, cell["fork_id"]), "fork.json"))
        assert os.path.isfile(os.path.join(lib.job_dir(state, cell["job_id"]), "job.json"))


def test_bt27_cancelling_a_fork_job_removes_its_folder(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "ronin-rescue")
    batch_id = bt.submit(s, ws, ["ronin-rescue"], [bt.variant("v1", bt.RENDER),
                                                   bt.variant("v2", {"gemma": bt.OTHER_GEMMA})])
    cells = bt.wait_status(s, batch_id)["batch"]["cells"]
    forks = [lib.story_dir(ws, c["fork_id"]) for c in cells]
    queued, starting = cells[0]["job_id"], cells[1]["job_id"]
    assert mt.api(s, "POST", "/api/jobs/%s/cancel" % queued, body={})[:3:2] == (200, {"state": "cancelled"})
    cell = bt.record(state, batch_id)["cells"][0]
    assert (cell["status"], cell["reason"]) == ("cancelled", "cancelled before it started")
    assert not os.path.lexists(forks[0])
    jdir = lib.job_dir(state, starting)
    lib.write_queue(state, [])
    lib.write_status(jdir, {"state": "starting", "dispatched": lib.utc_now()})
    assert mt.api(s, "POST", "/api/jobs/%s/cancel" % starting, body={})[:3:2] == (202, {"state": "cancelling"})
    proc = subprocess.run([sys.executable, os.path.join(mt.WS, "bin", "movie-ui-job"), jdir],
                          capture_output=True, text=True, timeout=30)
    assert (proc.returncode, proc.stdout) == (0, "[movie-ui] cancelled before start\n")
    assert os.path.isdir(forks[1])
    payload = mt.api(s, "GET", "/api/batches/" + batch_id)[2]
    assert (payload["batch"]["cells"][1]["status"], payload["batch"]["cells"][1]["reason"]) == (
        "cancelled", "cancelled before it started")
    assert payload["view"]["cells"][1] == {"state": "cancelled", "job": None, "movie": None, "dir": False}
    assert not os.path.lexists(forks[1])


def test_bt29_resume_submits_the_interrupted_cells(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    bt.passing_checks(monkeypatch)
    bt.original(state, ws, "ronin-rescue")
    clean = {"ws": ws, "stories": ["ronin-rescue"],
             "variants": [bt.variant("v1", bt.RENDER), bt.variant("v2", {"gemma": bt.OTHER_GEMMA})]}
    batch_id = srv.new_batch_id(state)
    rec = srv.make_batch_record(clean, batch_id, 1, srv.plan_batch(s.server, clean, 1)[0])
    rec["status"] = "submitting"
    rec["cells"][0]["status"] = "forking"
    fork = lib.story_dir(ws, rec["cells"][0]["fork_id"])
    os.makedirs(fork)
    lib.write_json_atomic(os.path.join(fork, "fork.json"), {"schema": "movie-ui.fork.v1",
                                                            "fork_id": rec["cells"][0]["fork_id"],
                                                            "batch": batch_id})
    lib.make_dir(os.path.join(state, "batches", batch_id))
    srv.write_batch(state, rec)
    srv.batch_recovery(state)
    assert bt.record(state, batch_id)["status"] == "interrupted" and not os.path.lexists(fork)
    assert mt.api(s, "POST", "/api/batches/%s/resume" % batch_id, body={})[:3:2] == (
        200, {"status": "waiting", "pending": 2})
    cells = bt.wait_status(s, batch_id)["batch"]["cells"]
    assert [c["status"] for c in cells] == ["queued", "queued"]
    assert lib.read_json(os.path.join(fork, "fork.json"))["label"] == "v1"
    assert mt.api(s, "POST", "/api/batches/%s/resume" % batch_id, body={})[:3:2] == (
        409, {"error": "batch %s was not interrupted" % batch_id})


def test_bt35_a_deleted_batch_leaves_its_job_less_forks_ineligible(env, monkeypatch):
    s, state, ws = env["srv"], env["state"], env["ws"]
    batch_id, fork, _job = _fallback_fork(env, monkeypatch)
    assert mt.api(s, "DELETE", "/api/batches/" + batch_id)[:3:2] == (200, {"deleted": batch_id})
    assert _stories(env)[fork] == {
        "id": fork, "eligible": False, "busy_job": None, "fields_source": None, "fields_batch": None,
        "reason": "Its job and its batch %s were deleted: no saved Compose settings to fork" % batch_id}
    req = bt.body(ws, [fork], [bt.variant("v1", {"gemma": bt.OTHER_GEMMA})])
    cell = mt.api(s, "POST", "/api/batches/preview", body=req)[2]["cells"][0]
    assert (cell["status"], cell["reason"]) == ("refused", "story %s has no saved Compose settings (its job and "
                                                           "its batch %s were deleted)" % (fork, batch_id))
    status, _h, payload = mt.api(s, "POST", "/api/batches", body=req)
    assert status == 409 and payload["error"] == "every cell was refused"
```

**1.2.** Append BT28. Edit `tests/test_movie_ui_jobs.py`: replace this text, which occurs exactly once:

```python
    finally:
        # mt.kill_everything would os.killpg the oversized pgid and overflow
        lib.write_status(lib.job_dir(state, lost), {"state": "lost", "pgid": None})
```

with:

```python
    finally:
        # mt.kill_everything would os.killpg the oversized pgid and overflow
        lib.write_status(lib.job_dir(state, lost), {"state": "lost", "pgid": None})


# --- batch forks BT28 (docs/superpowers/specs/2026-10-30-batch-forks-design.md, Section 7) -----

def _bt28_fork(ws, fork_id, batch_id):
    sdir = lib.story_dir(ws, fork_id)
    os.makedirs(sdir)
    lib.write_json_atomic(os.path.join(sdir, "fork.json"), {"schema": "movie-ui.fork.v1", "fork_id": fork_id,
                                                            "source_story": "s1", "batch": batch_id})
    return sdir


def test_bt28_batch_recovery_after_a_restart(state, tmp_path, capsys):
    import movie_ui_server as srv
    ws = os.path.realpath(str(tmp_path))
    batch_id = "20261030-120501-ab12"
    lost, kept = _bt28_fork(ws, "s1-b1-v1", batch_id), _bt28_fork(ws, "s1-b1-v2", batch_id)
    fields = {"action": "movie", "mode": "chained", "story_id": "s1-b1-v2"}
    job_id = mt.make_job(state, ["true"], ws, story_id="s1-b1-v2", fields=fields)
    cells = [{"story_id": "s1", "variant": m, "fork_id": "s1-b1-v%d" % m, "status": status, "reason": None,
              "level": "render", "diff": [], "warnings": [], "fields": None, "job_id": None, "copy_bytes": 0,
              "updated": "2020-01-01T00:00:00Z"}
             for m, status in ((1, "forking"), (2, "forking"), (3, "pending"))]
    rec = {"schema": "movie-ui.batch.v1", "id": batch_id, "number": 1, "workspace": ws,
           "created": "2020-01-01T00:00:00Z", "status": "submitting", "cancel_requested": False,
           "stories": ["s1"], "variants": [{"label": "v%d" % m, "settings": {}, "prompt": {}} for m in (1, 2, 3)],
           "order": [0, 1, 2], "cells": cells}
    lib.make_dir(os.path.join(state, "batches", batch_id))
    lib.write_json_atomic(os.path.join(state, "batches", batch_id, "batch.json"), rec)
    srv.batch_recovery(state)
    assert capsys.readouterr().err == "movie-ui: batch %s: interrupted (2 cell(s) to submit again)\n" % batch_id
    rec = lib.read_json(os.path.join(state, "batches", batch_id, "batch.json"))
    assert rec["status"] == "interrupted"
    assert [(c["status"], c["reason"], c["job_id"]) for c in rec["cells"]] == [
        ("interrupted", "the server stopped while this fork was being made", None),
        ("queued", None, job_id),
        ("interrupted", "the server stopped before this fork was made", None)]
    assert rec["cells"][1]["fields"] == fields
    assert not os.path.lexists(lost) and os.path.isfile(os.path.join(kept, "fork.json"))
    srv.batch_recovery(state)
    assert capsys.readouterr() == ("", "")
```

- [ ] **Step 2: Run them and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bulk-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_movie_ui_http.py::test_bt14_every_batch_route_needs_the_token \
  tests/test_movie_ui_http.py::test_bt20_cancel_batch \
  tests/test_movie_ui_http.py::test_bt21_delete_batch \
  tests/test_movie_ui_http.py::test_bt27_cancelling_a_fork_job_removes_its_folder \
  tests/test_movie_ui_http.py::test_bt29_resume_submits_the_interrupted_cells \
  tests/test_movie_ui_http.py::test_bt35_a_deleted_batch_leaves_its_job_less_forks_ineligible \
  tests/test_movie_ui_jobs.py::test_bt28_batch_recovery_after_a_restart 2>&1 | tail -1
```

Expected: `7 failed`.

- [ ] **Step 3: Implement.**

**3.1.** Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    ("GET", r"/api/batches/" + _ID, "h_batch", "/api/batches/" + _SAMPLE_ID),
```

with:

```python
    ("GET", r"/api/batches/" + _ID, "h_batch", "/api/batches/" + _SAMPLE_ID),
    ("DELETE", r"/api/batches/" + _ID, "h_batch_delete", "/api/batches/" + _SAMPLE_ID),
    ("POST", r"/api/batches/" + _ID + r"/cancel", "h_batch_cancel", "/api/batches/" + _SAMPLE_ID + "/cancel"),
    ("POST", r"/api/batches/" + _ID + r"/resume", "h_batch_resume", "/api/batches/" + _SAMPLE_ID + "/resume"),
```

**3.2.** Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    with STORE_LOCK:
        result = lib.cancel_job(self.server.state, job_id)
    if result == "cancelled":
        return 200, {"state": "cancelled"}
```

with:

```python
    with STORE_LOCK:
        result = lib.cancel_job(self.server.state, job_id)
    if result == "cancelled":
        _batch_job_cancelled(self.server, job_id)
        return 200, {"state": "cancelled"}
```

**3.3.** Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    with STORE_LOCK:
        lib.startup_recovery(state)
    stop = start_threads(server)
```

with:

```python
    with STORE_LOCK:
        lib.startup_recovery(state)
    batch_recovery(state)
    stop = start_threads(server)
```

**3.4.** Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
MovieUIHandler.h_batches = _h_batches
MovieUIHandler.h_batch_create = _h_batch_create
MovieUIHandler.h_batch = _h_batch
```

with:

```python
MovieUIHandler.h_batches = _h_batches
MovieUIHandler.h_batch_create = _h_batch_create
MovieUIHandler.h_batch = _h_batch


# ---------------------------------------------------------------------------
# Batch forks: cancel, restart, submit remaining and delete
# (docs/superpowers/specs/2026-10-30-batch-forks-design.md, Section 4.4)
# ---------------------------------------------------------------------------

ACTIVE_JOB_STATES = ("queued", "starting", "running")


def _batch_job_cancelled(server, job_id):
    """BF30: reconcile the batch whose cells hold job_id, if there is one."""
    for batch_id in list_batch_ids(server.state):
        rec = read_batch(server.state, batch_id)
        if rec is not None and any(c.get("job_id") == job_id for c in rec.get("cells", [])):
            reconcile(server, batch_id)
            return


def batch_recovery(state):
    """BF32 at startup, before the server serves: every waiting or submitting batch becomes
    interrupted. A forking cell whose fork has a movie job created at or after the batch becomes
    queued with that job (and its fields); any other forking cell loses its fork and, like every
    pending cell, becomes interrupted. One stderr line per recovered batch; nothing otherwise."""
    for batch_id in list_batch_ids(state):
        rec = read_batch(state, batch_id)
        if rec is None or rec.get("status") not in ("waiting", "submitting"):
            continue
        jobs = {}
        for job_id in lib.list_job_ids(state):
            job = lib.read_job(lib.job_dir(state, job_id)) or {}
            if (job.get("kind") == "movie" and job.get("workspace") == rec["workspace"]
                    and isinstance(job.get("created"), str) and job["created"] >= rec["created"]):
                jobs[job.get("story_id")] = (job_id, job)
        now = lib.utc_now()
        for cell in rec["cells"]:
            if cell.get("status") == "forking" and cell["fork_id"] in jobs:
                job_id, job = jobs[cell["fork_id"]]
                cell.update(status="queued", reason=None, job_id=job_id, fields=job.get("fields"), updated=now)
            elif cell.get("status") == "forking":
                remove_fork(lib.story_dir(rec["workspace"], cell["fork_id"]), batch_id)
                cell.update(status="interrupted", reason="the server stopped while this fork was being made",
                            updated=now)
            elif cell.get("status") == "pending":
                cell.update(status="interrupted", reason="the server stopped before this fork was made", updated=now)
        rec["status"] = "interrupted"
        write_batch(state, rec)
        sys.stderr.write("movie-ui: batch %s: interrupted (%d cell(s) to submit again)\n"
                         % (batch_id, sum(1 for c in rec["cells"] if c.get("status") == "interrupted")))


def _h_batch_cancel(self, groups, query, body):
    """BF31: stop the batch's pending cells, cancel its forks' jobs, reconcile, mark it cancelled."""
    server, batch_id = self.server, groups[0]
    state = server.state
    _known_batch(server, batch_id)
    with BATCH_LOCK:
        rec = read_batch(state, batch_id)
        if rec is None:
            raise ApiError(404, "unknown batch %s" % batch_id)
        queue = lib.read_queue(state)
        jobs = [c["job_id"] for c in rec["cells"] if c.get("status") == "queued"
                and isinstance(c.get("job_id"), str) and lib.JOB_ID_RE.fullmatch(c["job_id"])]
        if not (any(c.get("status") in ("pending", "forking") for c in rec["cells"])
                or any(lib.job_state(state, j, queue) in ACTIVE_JOB_STATES for j in jobs)):
            raise ApiError(409, "batch %s has nothing to cancel" % batch_id)
        if batch_id in server.batch_queue:
            server.batch_queue.remove(batch_id)
        rec["cancel_requested"] = True
        for cell in rec["cells"]:
            if cell.get("status") == "pending":
                cell.update(status="cancelled", reason="batch cancelled", updated=lib.utc_now())
        write_batch(state, rec)
    cancelled, cancelling = [], []
    for job_id in jobs:
        with STORE_LOCK:
            result = lib.cancel_job(state, job_id)
        if result == "cancelled":
            cancelled.append(job_id)
        elif result == "cancelling":
            cancelling.append(job_id)
    reconcile(server, batch_id)
    with BATCH_LOCK:
        rec = read_batch(state, batch_id)
        if rec is not None:
            rec["status"] = "cancelled"
            write_batch(state, rec)
    return 200, {"status": "cancelled", "cancelled": cancelled, "cancelling": cancelling}


def _h_batch_resume(self, groups, query, body):
    """BF33: an interrupted batch's interrupted cells go back to pending and the batch is queued."""
    server, batch_id = self.server, groups[0]
    _known_batch(server, batch_id)
    with BATCH_LOCK:
        rec = read_batch(server.state, batch_id)
        if rec is None:
            raise ApiError(404, "unknown batch %s" % batch_id)
        if rec.get("status") != "interrupted":
            raise ApiError(409, "batch %s was not interrupted" % batch_id)
        for cell in rec["cells"]:
            if cell.get("status") == "interrupted":
                cell.update(status="pending", reason=None, updated=lib.utc_now())
        rec["status"] = "waiting"
        write_batch(server.state, rec)
        server.batch_queue.append(batch_id)
        _batch_kick(server)
    return 200, {"status": "waiting", "pending": sum(1 for c in rec["cells"] if c["status"] == "pending")}


def _h_batch_delete(self, groups, query, body):
    """BF34: remove the batch record (never its forks or their jobs) unless it is still submitting."""
    server, batch_id = self.server, groups[0]
    _known_batch(server, batch_id)
    with BATCH_LOCK:
        rec = read_batch(server.state, batch_id)
        if rec is None:
            raise ApiError(404, "unknown batch %s" % batch_id)
        if rec.get("status") in ("waiting", "submitting"):
            raise ApiError(409, "batch %s is still submitting; cancel it first" % batch_id)
        try:
            shutil.rmtree(os.path.dirname(batch_path(server.state, batch_id)))
        except OSError as e:
            raise ApiError(500, "cannot delete batch %s: %s" % (batch_id, e.strerror or e))
    return 200, {"deleted": batch_id}


MovieUIHandler.h_batch_cancel = _h_batch_cancel
MovieUIHandler.h_batch_resume = _h_batch_resume
MovieUIHandler.h_batch_delete = _h_batch_delete
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bulk-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_movie_ui_http.py::test_bt14_every_batch_route_needs_the_token \
  tests/test_movie_ui_http.py::test_bt20_cancel_batch \
  tests/test_movie_ui_http.py::test_bt21_delete_batch \
  tests/test_movie_ui_http.py::test_bt27_cancelling_a_fork_job_removes_its_folder \
  tests/test_movie_ui_http.py::test_bt29_resume_submits_the_interrupted_cells \
  tests/test_movie_ui_http.py::test_bt35_a_deleted_batch_leaves_its_job_less_forks_ineligible \
  tests/test_movie_ui_jobs.py::test_bt28_batch_recovery_after_a_restart 2>&1 | tail -1
```

Expected: `7 passed`. Run the compile check with `FILES` = `movie_ui_server.py tests/test_movie_ui_http.py tests/test_movie_ui_jobs.py`; expected: `compiled 3` twice. Then run the gate block with `N=4`. Expected: `GATE PASS`, `lost 4 (listed 4, unexpected 0); new tests 81, not passing 0`, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bulk-wt/qwen-agent-workspace
git add movie_ui_server.py tests/test_movie_ui_http.py tests/test_movie_ui_jobs.py
git diff --cached --name-only    # expected: those 3 paths
git commit -m "feat(movie-ui): cancel, restart recovery, submit remaining and delete for batches; the job-cancel hook (BF30-BF34; BT14, BT20, BT21, BT27-BT29, BT35)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The page: the Stories checkbox, the Batches tab, the editor, the batch page (BF36-BF40; BT13)

This task implements:
- BF36:
  - `#s-new-batch` and the `Pick` column;
  - `pickCell`, which disables an ineligible box with the server's reason as `title` and adds the `settings from batch b<N>` note;
  - `pickedStories` and `updateNewBatch`;
  - `loadStories`, which also reads `GET /api/batches/stories`.
- BF37: `#tab-batches` and `TABS`. `showTab("batches")` calls `loadBatches()`, and leaving the tab stops the batch poll. `showBatchBox` shows one box at a time.
- BF38, the editor:
  - variant cards: label, the grouped `Add setting…` menu, setting rows that copy the Compose controls (`cloneControl`, `settingControl`), and append and find → replace rows;
  - the preview table with badges, diff lines, warnings and `Edit prompt`;
  - the totals, Submit and Discard; the debounced, sequence-guarded preview; the prompt dialog.
  - `loraRow` and `collectLoras` gain an optional `container`.
- BF39, the batch page:
  - the title and the actions (Cancel and Delete confirm with the spec texts, and Submit remaining shows only for an interrupted batch);
  - the grid, built once per batch so the videos keep playing, with chips, badges, diffs, Open story, Log, Cancel and Play row;
  - polling every `BATCH_POLL_MS` while the page is shown; `stopPolling` also clears `"batch"`.
- BF40: the `.badge.level-*` colours (light, then dark inside the existing `@media` block), `.chip` and `#b-grid video`.
- The UI details the spec leaves open are Plan rulings BR18 and BR26.

Tests: BT13, appended to `tests/test_movie_ui_batch.py`.

**Files:**
- Modify:
  - `static/movie-ui/index.html`: the nav `:34`, the Stories panel `:142-143`, before the Characters panel `:168`, after `#confirm` `:342-344`;
  - `static/movie-ui/app.js`: `:8`, `stopPolling` `:68`, `TABS` `:285`, `showTab` `:292`, `loraRow` `:302` and `:343`, `collectLoras` `:347-349`, `loadStories` `:681-688`, `setupStories` `:757`, before the Characters section `:784`, `start` `:1676`;
  - `static/movie-ui/app.css`: `:5-7`, `:11-13`, `:86-87`;
  - `tests/test_movie_ui_batch.py`: the end of the file (append).
- Read only: `app.js` `askConfirm` `:103-123`, `debounce` `:125-131`, `uploadFile` `:472-477`, `openStory` `:696-732`, `selectJob` `:1336-1346`, `errorText` `:902-904`, `button` `:1313-1317`.

**Interfaces:**
- Consumes: the routes of Tasks 2-4 and their payloads (spec 3.3).
- Produces (page-internal):
  - `BATCH_POLL_MS`, `LEVEL_LABELS`, `BATCH_SETTINGS`, `BATCH_CONTROLS`;
  - `loraRow(target, item, container)`, `collectLoras(target, container)`;
  - `pickCell`, `pickedStories`, `updateNewBatch`, `showBatchBox`, `stopBatchPoll`, `loadBatches`;
  - `openBatchEditor(stories)`, `addVariantCard`, `settingControl(key, f)`, `batchBody`, `batchPreview`, `submitBatch`, `openPromptDialog`;
  - `openBatch(batchId)`, `pollBatch`, `renderBatchPage`, `playRow`, `setupBatches`.

- [ ] **Step 1: Write the failing test.**

Append BT13. Edit `tests/test_movie_ui_batch.py`: replace this text, which occurs exactly once:

```python
    assert batch.fork_fallback(fork_rec, batch_rec, "ronin-rescue-b1-v1", WSR) == ("mismatch", None, BID, None)
```

with:

```python
    assert batch.fork_fallback(fork_rec, batch_rec, "ronin-rescue-b1-v1", WSR) == ("mismatch", None, BID, None)


# --- BT13: the static page (spec 5) ---------------------------------------------------------

PAGE_IDS = ("s-new-batch", "tab-batches", "panel-batches", "b-list-box", "b-list", "b-editor", "b-page",
            "b-editor-stories", "b-add-variant", "b-variant-note", "b-variants", "b-preview", "b-totals",
            "b-submit", "b-discard", "b-editor-status", "b-prompt-dialog", "b-prompt-title", "b-prompt-text",
            "b-prompt-count", "b-prompt-save", "b-prompt-original", "b-prompt-close", "b-page-title", "b-back",
            "b-cancel", "b-resume", "b-delete", "b-page-status", "b-grid")


def test_bt13_the_static_page():
    static = os.path.join(WS, "static", "movie-ui")
    texts = {}
    for name in ("index.html", "app.js", "app.css"):
        with open(os.path.join(static, name), encoding="utf-8") as f:
            texts[name] = f.read()
    html, js, css = texts["index.html"], texts["app.js"], texts["app.css"]
    for element in PAGE_IDS:
        assert html.count('id="%s"' % element) == 1, element
    assert html.index('id="tab-stories"') < html.index('id="tab-batches"') < html.index('id="tab-characters"')
    assert "<thead><tr><th>Pick</th><th>Story</th><th>story.md</th>" in html
    assert ('const TABS = ["compose", "stories", "batches", "characters", "locations", "actions", "loras", '
            '"jobs", "traces"];') in js
    for text in ("New batch (", "Play row", "Submit remaining", "Use the original", "Add setting…",
                 "settings from batch b"):
        assert text in html + js, text
    for text in ("const BATCH_POLL_MS = 2000;", '["jobs", "log", "host", "batch"]', 'if (name === "batches") { loadBatches(); }',
                 "S.timers.batch = setInterval(pollBatch, BATCH_POLL_MS);", "function loraRow(target, item, container)",
                 "function collectLoras(target, container)",
                 "loadCatalog(), loadCharacters(), loadLocations(), loadActions(), loadStories(), loadModels()"):
        assert text in js, text
    for name, text in texts.items():
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\balert\(", r"\bconfirm\(", r"\bprompt\(",
                        r"\beval\(", r"new Function"):
            assert not re.search(pattern, text), (name, pattern)
    assert re.findall(r"<script[^>]*>", html) == ['<script src="/static/app.js" defer>']
    for rule in (".chip {", "#b-grid video { max-width: 320px; }"):
        assert css.count(rule) == 1, rule
    for level in ("render", "stills", "replan"):
        assert css.count(".level-%s {" % level) == 2, level
        dark = css.index("@media (prefers-color-scheme: dark)")
        assert css.index(".level-%s {" % level) < dark < css.rindex(".level-%s {" % level)
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")], capture_output=True, text=True,
                              timeout=60)
        assert proc.returncode == 0, proc.stderr
```

- [ ] **Step 2: Run it and expect a failure.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bulk-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_movie_ui_batch.py::test_bt13_the_static_page 2>&1 | tail -1
```

Expected: `1 failed` (`s-new-batch` is not in `index.html`).

- [ ] **Step 3: Implement.**

**3.1.** Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
  <button id="tab-stories" type="button" class="tab">Stories</button>
```

with:

```html
  <button id="tab-stories" type="button" class="tab">Stories</button>
  <button id="tab-batches" type="button" class="tab">Batches</button>
```

**3.2.** Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
<section id="panel-stories" class="panel" hidden>
  <table id="s-list" class="list"><thead><tr><th>Story</th><th>story.md</th><th>Checks</th><th>Stills</th><th>Clips</th><th>Movie</th><th>Modified</th></tr></thead><tbody></tbody></table>
```

with:

```html
<section id="panel-stories" class="panel" hidden>
  <div class="row"><button id="s-new-batch" type="button" hidden>New batch (0)</button></div>
  <table id="s-list" class="list"><thead><tr><th>Pick</th><th>Story</th><th>story.md</th><th>Checks</th><th>Stills</th><th>Clips</th><th>Movie</th><th>Modified</th></tr></thead><tbody></tbody></table>
```

**3.3.** Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
<section id="panel-characters" class="panel" hidden>
```

with:

```html
<section id="panel-batches" class="panel" hidden>
  <div id="b-list-box">
    <table id="b-list" class="list"><thead><tr><th>Batch</th><th>Created</th><th>Done</th><th>Status</th></tr></thead><tbody></tbody></table>
  </div>
  <div id="b-editor" hidden>
    <h2>New batch</h2>
    <p id="b-editor-stories" class="muted"></p>
    <div class="row"><button id="b-add-variant" type="button">Add variant</button> <span id="b-variant-note" class="muted"></span></div>
    <div id="b-variants"></div>
    <table id="b-preview" class="list"><thead></thead><tbody></tbody></table>
    <p id="b-totals"></p>
    <div class="row">
      <button id="b-submit" type="button" disabled>Submit batch</button>
      <button id="b-discard" type="button">Discard</button>
      <span id="b-editor-status" class="muted"></span>
    </div>
  </div>
  <div id="b-page" hidden>
    <h2 id="b-page-title"></h2>
    <div class="row">
      <button id="b-back" type="button">All batches</button>
      <button id="b-cancel" type="button">Cancel batch</button>
      <button id="b-resume" type="button" hidden>Submit remaining</button>
      <button id="b-delete" type="button">Delete batch</button>
      <span id="b-page-status" class="muted"></span>
    </div>
    <table id="b-grid" class="list"><thead></thead><tbody></tbody></table>
  </div>
</section>

<section id="panel-characters" class="panel" hidden>
```

**3.4.** Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
    <button id="confirm-no" type="button">No</button>
  </div>
</div>
```

with:

```html
    <button id="confirm-no" type="button">No</button>
  </div>
</div>

<div id="b-prompt-dialog" class="dialog" hidden>
  <div class="dialog-box">
    <h3 id="b-prompt-title"></h3>
    <textarea id="b-prompt-text" rows="12" cols="80"></textarea>
    <p id="b-prompt-count" class="muted"></p>
    <button id="b-prompt-save" type="button">Use this prompt</button>
    <button id="b-prompt-original" type="button">Use the original</button>
    <button id="b-prompt-close" type="button">Cancel</button>
  </div>
</div>
```

**3.5.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
  const STILLS_MODEL = "Tongyi-MAI/Z-Image-Turbo";
```

with:

```javascript
  const STILLS_MODEL = "Tongyi-MAI/Z-Image-Turbo";
  const BATCH_POLL_MS = 2000;   // batch forks spec 1.1: the jobs poll interval
  const LEVEL_LABELS = {render: "Render", stills: "New stills", replan: "Re-plan"};
```

**3.6.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
    ["jobs", "log", "host"].forEach(function (name) {
```

with:

```javascript
    ["jobs", "log", "host", "batch"].forEach(function (name) {
```

**3.7.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
  const TABS = ["compose", "stories", "characters", "locations", "actions", "loras", "jobs", "traces"];
```

with:

```javascript
  const TABS = ["compose", "stories", "batches", "characters", "locations", "actions", "loras", "jobs", "traces"];
```

**3.8.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
    if (name === "stories") { loadStories(); }
```

with:

```javascript
    if (name !== "batches") { stopBatchPoll(); }
    if (name === "stories") { loadStories(); }
    if (name === "batches") { loadBatches(); }
```

**3.9.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
  function loraRow(target, item) {
```

with:

```javascript
  function loraRow(target, item, container) {
```

**3.10.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
    $(target === "video" ? "#c-video-loras" : "#c-stills-loras").appendChild(row);
```

with:

```javascript
    (container || $(target === "video" ? "#c-video-loras" : "#c-stills-loras")).appendChild(row);
```

**3.11.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
  function collectLoras(target) {
    const entries = S.catalog[target];
    const rows = document.querySelectorAll((target === "video" ? "#c-video-loras" : "#c-stills-loras") + " .lora-row");
```

with:

```javascript
  function collectLoras(target, container) {
    const entries = S.catalog[target];
    const rows = container ? container.querySelectorAll(".lora-row")
      : document.querySelectorAll((target === "video" ? "#c-video-loras" : "#c-stills-loras") + " .lora-row");
```

**3.12.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
    const res = await api("GET", "/api/stories" + wsQuery());
    const body = clear($("#s-list tbody"));
    if (res.status !== 200) { return; }
    res.data.stories.forEach(function (st) {
      const checks = st.checks ? st.checks.hard + " hard, " + st.checks.advisory + " advisory" +
        (st.checks.verdict ? " (" + st.checks.verdict + ")" : "") : "-";
      const row = el("tr", {data: {storyId: st.id}, cls: "clickable"}, [
        el("td", {text: st.id}), el("td", {text: st.story_md ? "yes" : "no"}), el("td", {text: checks}),
```

with:

```javascript
    const res = await api("GET", "/api/stories" + wsQuery());
    const picks = await api("GET", "/api/batches/stories" + wsQuery());
    const body = clear($("#s-list tbody"));
    updateNewBatch();
    if (res.status !== 200) { return; }
    const eligibility = {};
    if (picks.status === 200) { picks.data.stories.forEach(function (p) { eligibility[p.id] = p; }); }
    res.data.stories.forEach(function (st) {
      const checks = st.checks ? st.checks.hard + " hard, " + st.checks.advisory + " advisory" +
        (st.checks.verdict ? " (" + st.checks.verdict + ")" : "") : "-";
      const row = el("tr", {data: {storyId: st.id}, cls: "clickable"}, [pickCell(st.id, eligibility[st.id]),
        el("td", {text: st.id}), el("td", {text: st.story_md ? "yes" : "no"}), el("td", {text: checks}),
```

**3.13.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
    $("#s-save").addEventListener("click", saveStory);
```

with:

```javascript
    $("#s-save").addEventListener("click", saveStory);
    $("#s-new-batch").addEventListener("click", function () { openBatchEditor(pickedStories()); });
```

**3.14.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
  // --- characters (MU82) ---------------------------------------------------------------
```

with:

```javascript
  // --- batches (batch forks spec Section 5, BF36-BF39) ---------------------------------

  // The editor's "Add setting…" menu, grouped by what a change costs (BF38): [key, label].
  const BATCH_SETTINGS = [
    ["Render", [["model", "Video model"], ["gemma", "Gemma"], ["video_loras", "Video LoRAs"],
                ["action_loras", "Actions"], ["frames", "Frames per panel"], ["fps", "FPS"],
                ["no_low_ram", "No low-RAM mode"], ["panel_timeout", "Panel timeout (s)"]]],
    ["New stills", [["resolution", "Resolution"], ["stills_loras", "Stills LoRAs"],
                    ["location_strength", "Location strength"]]],
    ["Re-plan", [["size", "Size"], ["goal", "Goal"], ["seed_upload", "Seed image"], ["mode", "Mode"],
                 ["story_model", "Story model"], ["auto_lora", "Auto-pick catalog LoRAs"], ["narration", "Narration"],
                 ["characters", "Cast"], ["locations", "Locations"], ["story_legacy", "Legacy story engine"],
                 ["judge", "Judge with Claude"]]]
  ];
  // The Compose control each single-control setting copies (BF38).
  const BATCH_CONTROLS = {
    gemma: "#c-gemma", goal: "#c-goal", story_model: "#c-story-model", frames: "#c-frames", fps: "#c-fps",
    panel_timeout: "#c-panel-timeout", location_strength: "#c-location-strength", no_low_ram: "#c-no-low-ram",
    auto_lora: "#c-auto-lora", story_legacy: "#c-story-legacy", judge: "#c-judge", mode: "#c-mode",
    narration: "#c-narration", characters: "#c-characters", locations: "#c-locations"
  };

  function cloneControl(selector) {
    const node = $(selector).cloneNode(true);
    node.removeAttribute("id");
    node.querySelectorAll("[id]").forEach(function (n) { n.removeAttribute("id"); });
    return node;
  }

  function nodeNumber(node) {
    const value = node.value.trim();
    return value === "" ? null : Number(value);
  }

  function nodeText(node) {
    const value = node.value.trim();
    return value === "" ? null : value;
  }

  function selectedValues(node) {
    return Array.prototype.map.call(node.selectedOptions, function (o) { return o.value; });
  }

  function selectValues(node, values) {
    Array.prototype.forEach.call(node.options, function (o) { o.selected = (values || []).indexOf(o.value) >= 0; });
  }

  function hasOption(node, value) {
    return Array.prototype.some.call(node.options, function (o) { return o.value === value; });
  }

  function batchFileUrl(ws, path) {
    return "/files?ws=" + enc(ws) + "&path=" + enc(path) + "&t=" + enc(S.token);
  }

  function levelBadge(level) { return el("span", {cls: "badge level-" + level, text: LEVEL_LABELS[level]}); }

  function batchNote(source) {
    return el("span", {cls: "s-pick-note muted", text: "settings from batch b" + source.number,
                       title: "This fork's job was deleted; its settings come from batch " + source.id});
  }

  function diffValue(key, value) {
    if (value === null || value === undefined) { return "default"; }
    if (key === "video_loras" || key === "stills_loras") {
      return value.map(function (i) { return (i.id || String(i.path).split("/").pop()) + " @ " + i.strength; }).join(", ") || "none";
    }
    if (key === "action_loras") {
      return value.map(function (a) { return a.name + (a.strength === null ? "" : " @ " + a.strength); }).join(", ") || "none";
    }
    if (Array.isArray(value)) { return value.join(", ") || "none"; }
    return String(value);
  }

  function diffLine(d) {
    if (d.key === "narrative") { return "narrative: prompt edited"; }
    return d.key + ": " + diffValue(d.key, d.from) + " → " + diffValue(d.key, d.to) + (d.note ? " (" + d.note + ")" : "");
  }

  // --- the Stories tab's checkboxes (BF36)

  function pickedStories() {
    return Array.prototype.filter.call(document.querySelectorAll("#s-list .s-pick"), function (b) { return b.checked; })
      .map(function (b) { return b.dataset.storyId; });
  }

  function updateNewBatch() {
    const n = pickedStories().length;
    $("#s-new-batch").textContent = "New batch (" + n + ")";
    show($("#s-new-batch"), n >= 1);
  }

  function pickCell(storyId, info) {
    const box = el("input", {type: "checkbox", cls: "s-pick", data: {storyId: storyId}});
    const cell = el("td", {}, [box]);
    if (!info || !info.eligible) {
      box.disabled = true;
      box.title = info ? info.reason : "batch eligibility is not known";
    }
    if (info && info.fields_source === "batch") {
      cell.appendChild(document.createTextNode(" "));
      cell.appendChild(batchNote(info.fields_batch));
    }
    box.addEventListener("click", function (event) { event.stopPropagation(); updateNewBatch(); });
    return cell;
  }

  // --- the Batches tab: one box at a time (BF37)

  function stopBatchPoll() {
    if (S.timers.batch) { clearInterval(S.timers.batch); S.timers.batch = null; }
  }

  function showBatchBox(name) {
    show($("#b-list-box"), name === "list");
    show($("#b-editor"), name === "editor");
    show($("#b-page"), name === "page");
    if (name !== "page") { stopBatchPoll(); }
  }

  async function loadBatches() {
    showBatchBox("list");
    if (!S.ws) { return; }
    const res = await api("GET", "/api/batches" + wsQuery());
    const body = clear($("#b-list tbody"));
    if (res.status !== 200) { return; }
    res.data.batches.forEach(function (b) {
      const row = el("tr", {data: {batchId: b.id}, cls: "clickable"}, [el("td", {text: b.id}),
        el("td", {text: new Date(b.created).toLocaleString()}), el("td", {text: b.done + "/" + b.cells}),
        el("td", {text: b.status})]);
      row.addEventListener("click", function () { openBatch(b.id); });
      body.appendChild(row);
    });
  }

  // --- the editor (BF38)

  function batchCards() { return Array.prototype.slice.call(document.querySelectorAll("#b-variants .b-variant")); }

  function batchStart() {
    const ed = S.bEditor;
    const row = ed && ed.rows.length ? ed.rows[0] : null;
    return Object.assign({}, S.options ? S.options.defaults : {}, row && row.fields ? row.fields : {});
  }

  function settingLabel(key) {
    let label = key;
    BATCH_SETTINGS.forEach(function (group) {
      group[1].forEach(function (item) { if (item[0] === key) { label = item[1]; } });
    });
    return label;
  }

  function settingsMenu() {
    const menu = el("select", {cls: "b-add-setting"}, [el("option", {value: "", text: "Add setting…"})]);
    BATCH_SETTINGS.forEach(function (group) {
      menu.appendChild(el("optgroup", {label: group[0]}, group[1].map(function (item) {
        return el("option", {value: item[0], text: item[1]});
      })));
    });
    return menu;
  }

  // One setting's control, started at the original's value f[key]; read() gives its settings.
  function settingControl(key, f) {
    let node;
    let read;
    if (key === "model") {
      node = cloneControl("#c-model");
      Array.prototype.slice.call(node.options).forEach(function (o) { if (o.value === "__download__") { o.remove(); } });
      if (f.model && !hasOption(node, f.model)) { node.appendChild(el("option", {value: f.model, text: f.model})); }
      node.value = f.model || "";
      read = function () { return {model: node.value || null}; };
    } else if (["gemma", "goal", "story_model"].indexOf(key) >= 0) {
      node = cloneControl(BATCH_CONTROLS[key]);
      node.value = f[key] === null || f[key] === undefined ? "" : String(f[key]);
      read = function () { const out = {}; out[key] = nodeText(node); return out; };
    } else if (["frames", "fps", "panel_timeout", "location_strength"].indexOf(key) >= 0) {
      node = cloneControl(BATCH_CONTROLS[key]);
      node.value = f[key] === null || f[key] === undefined ? "" : String(f[key]);
      read = function () { const out = {}; out[key] = nodeNumber(node); return out; };
    } else if (["no_low_ram", "auto_lora", "story_legacy", "judge"].indexOf(key) >= 0) {
      node = cloneControl(BATCH_CONTROLS[key]);
      node.checked = key === "auto_lora" ? f.auto_lora !== false : Boolean(f[key]);
      read = function () { const out = {}; out[key] = node.checked; return out; };
    } else if (key === "mode" || key === "narration") {
      node = cloneControl(BATCH_CONTROLS[key]);
      node.value = f[key] || (key === "mode" ? "chained" : "full");
      read = function () { const out = {}; out[key] = node.value; return out; };
    } else if (key === "characters" || key === "locations") {
      node = cloneControl(BATCH_CONTROLS[key]);
      selectValues(node, f[key]);
      read = function () { const out = {}; out[key] = selectedValues(node); return out; };
    } else if (key === "action_loras") {
      const pick = cloneControl("#c-actions");
      const strength = cloneControl("#c-action-strength");
      const items = f.action_loras || [];
      selectValues(pick, items.map(function (a) { return a.name; }));
      strength.value = items.length && items[0].strength !== null && items[0].strength !== undefined ? String(items[0].strength) : "";
      node = el("span", {}, [pick, " Strength ", strength]);
      read = function () {
        return {action_loras: selectedValues(pick).map(function (name) { return {name: name, strength: nodeNumber(strength)}; })};
      };
    } else if (key === "resolution") {
      const preset = cloneControl("#c-res-preset");
      const width = cloneControl("#c-width");
      const height = cloneControl("#c-height");
      const lock = function () {
        const custom = preset.value === "custom";
        width.readOnly = !custom;
        height.readOnly = !custom;
      };
      width.value = String(f.width || 1024);
      height.value = String(f.height || 576);
      preset.value = hasOption(preset, width.value + "x" + height.value) ? width.value + "x" + height.value : "custom";
      lock();
      preset.addEventListener("change", function () {
        if (preset.value !== "custom") {
          const wh = preset.value.split("x");
          width.value = wh[0];
          height.value = wh[1];
        }
        lock();
      });
      node = el("span", {}, [preset, width, " x ", height]);
      read = function () { return {width: nodeNumber(width), height: nodeNumber(height)}; };
    } else if (key === "size") {
      const kind = el("select", {cls: "b-size-kind"}, [el("option", {value: "panels", text: "Panels"}),
                                                        el("option", {value: "length", text: "Seconds"})]);
      const count = cloneControl("#c-panels");
      const bounds = function () {
        count.max = kind.value === "length" ? "3600" : "200";
        count.step = kind.value === "length" ? "0.5" : "1";
      };
      const byLength = (f.panels === null || f.panels === undefined) && f.length !== null && f.length !== undefined;
      kind.value = byLength ? "length" : "panels";
      count.value = String(byLength ? f.length : (f.panels === null || f.panels === undefined ? 15 : f.panels));
      bounds();
      kind.addEventListener("change", bounds);
      node = el("span", {}, [kind, count]);
      read = function () { const out = {}; out[kind.value] = nodeNumber(count); return out; };
    } else if (key === "seed_upload") {
      const file = cloneControl("#c-seed-file");
      let upload = f.seed_upload || null;
      const status = el("span", {cls: "muted", text: upload ? "upload " + upload.slice(0, 12) : "no seed image"});
      file.addEventListener("change", async function () {
        const chosen = file.files[0];
        if (!chosen) { return; }
        status.textContent = "uploading...";
        try {
          upload = await uploadFile(chosen);
          status.textContent = "uploaded " + upload.slice(0, 12);
        } catch (err) {
          status.textContent = String(err.message);
        }
        batchPreview();
      });
      node = el("span", {}, [file, status]);
      read = function () { return {seed_upload: upload}; };
    } else {
      const target = key === "video_loras" ? "video" : "stills";
      const box = el("div", {cls: "b-loras"});
      const add = el("button", {type: "button", text: "Add"});
      add.addEventListener("click", function () { loraRow(target, null, box); });
      (f[key] || []).forEach(function (item) { loraRow(target, item, box); });
      node = el("span", {}, [add, box]);
      read = function () { const out = {}; out[key] = collectLoras(target, box); return out; };
    }
    return {node: node, read: read};
  }

  function syncMenu(card) {
    const used = Array.prototype.map.call(card.querySelectorAll(".b-setting"), function (r) { return r.dataset.key; });
    Array.prototype.forEach.call(card.querySelector(".b-add-setting").options, function (o) {
      o.disabled = o.value !== "" && used.indexOf(o.value) >= 0;
    });
  }

  function addSettingRow(card, key) {
    const control = settingControl(key, batchStart());
    const remove = el("button", {type: "button", text: "Remove"});
    const row = el("div", {cls: "b-setting", data: {key: key}}, [el("span", {text: settingLabel(key)}), control.node, remove]);
    row.readSetting = control.read;
    remove.addEventListener("click", function () { row.remove(); syncMenu(card); });
    card.querySelector(".b-settings").appendChild(row);
    syncMenu(card);
  }

  function syncReplaces(card) {
    card.querySelector(".b-add-replace").disabled = card.querySelectorAll(".b-replace").length >= 10;
  }

  function addReplaceRow(card) {
    const box = card.querySelector(".b-replaces");
    if (box.querySelectorAll(".b-replace").length >= 10) { return; }
    const remove = el("button", {type: "button", text: "Remove"});
    const row = el("div", {cls: "b-replace"}, [el("input", {type: "text", cls: "b-find", size: "30", placeholder: "Find"}),
      el("input", {type: "text", cls: "b-with", size: "30", placeholder: "Replace with"}), remove]);
    remove.addEventListener("click", function () { row.remove(); syncReplaces(card); });
    box.appendChild(row);
    syncReplaces(card);
  }

  function syncCards() {
    const cards = batchCards();
    cards.forEach(function (card) { show(card.querySelector(".b-remove-variant"), cards.length > 1); });
    $("#b-add-variant").disabled = cards.length >= 6;
    $("#b-variant-note").textContent = cards.length >= 6 ? "at most 6 variants" : "";
  }

  function addVariantCard() {
    const used = batchCards().map(function (c) { return c.querySelector(".b-label").value; });
    if (used.length >= 6) { return; }
    let k = 1;
    while (used.indexOf("v" + k) >= 0) { k += 1; }
    const menu = settingsMenu();
    const addReplace = el("button", {type: "button", cls: "b-add-replace", text: "Add find → replace"});
    const remove = el("button", {type: "button", cls: "b-remove-variant", text: "Remove variant"});
    const label = el("input", {type: "text", cls: "b-label", maxlength: "24", size: "12", value: "v" + k});
    const card = el("div", {cls: "b-variant"}, [
      el("div", {cls: "row"}, [el("label", {}, ["Label ", label]), menu, remove]),
      el("div", {cls: "b-settings"}),
      el("textarea", {cls: "b-append", rows: "2", placeholder: "Append to every prompt"}),
      el("div", {cls: "b-replaces"}, [addReplace])]);
    card.perStory = {};
    menu.addEventListener("change", function () {
      if (menu.value) { addSettingRow(card, menu.value); }
      menu.value = "";
    });
    addReplace.addEventListener("click", function () { addReplaceRow(card); });
    remove.addEventListener("click", function () { card.remove(); syncCards(); });
    $("#b-variants").appendChild(card);
    syncCards();
  }

  // The request body of the preview and the submit (spec 3.2); a find/replace row with an empty Find is not sent.
  function batchBody() {
    const variants = batchCards().map(function (card) {
      const settings = {};
      card.querySelectorAll(".b-setting").forEach(function (row) { Object.assign(settings, row.readSetting()); });
      const replace = Array.prototype.filter.call(card.querySelectorAll(".b-replace"), function (row) {
        return row.querySelector(".b-find").value !== "";
      }).map(function (row) {
        return {"find": row.querySelector(".b-find").value, "with": row.querySelector(".b-with").value};
      });
      return {label: card.querySelector(".b-label").value, settings: settings,
              prompt: {append: card.querySelector(".b-append").value, replace: replace, per_story: Object.assign({}, card.perStory)}};
    });
    return {ws: S.ws, stories: S.bEditor.stories, variants: variants};
  }

  function previewCell(c) {
    const td = el("td", {}, [el("div", {text: c.fork_id})]);
    if (c.level) { td.appendChild(levelBadge(c.level)); }
    c.diff.forEach(function (d) { td.appendChild(el("div", {cls: "muted", text: diffLine(d)})); });
    const warnings = el("ul", {cls: "warnings"});
    c.warnings.forEach(function (w) { warnings.appendChild(el("li", {text: w})); });
    td.appendChild(warnings);
    if (c.status !== "ok") { td.appendChild(el("div", {cls: "bad", text: c.status + ": " + c.reason})); }
    const edit = button("Edit prompt", function () { openPromptDialog(c.story_id, c.variant - 1); });
    edit.className = "b-edit-prompt";
    td.appendChild(edit);
    return td;
  }

  function renderBatchPreview(data) {
    const labels = batchCards().map(function (c) { return c.querySelector(".b-label").value; });
    clear($("#b-preview thead")).appendChild(el("tr", {}, [el("th", {text: "Story"})].concat(
      labels.map(function (label) { return el("th", {text: label}); }))));
    const body = clear($("#b-preview tbody"));
    data.rows.forEach(function (row) {
      const first = el("td", {text: row.story_id});
      if (row.fields_source === "batch") {
        first.appendChild(document.createTextNode(" "));
        first.appendChild(batchNote(row.fields_batch));
      }
      body.appendChild(el("tr", {}, [first].concat(data.cells.filter(function (c) { return c.story_id === row.story_id; })
        .map(previewCell))));
    });
    $("#b-totals").textContent = data.totals.text;
    $("#b-submit").disabled = data.totals.jobs === 0;
  }

  const batchPreview = debounce(async function () {
    const ed = S.bEditor;
    if (!ed) { return; }
    S.batchSeq = (S.batchSeq || 0) + 1;
    const seq = S.batchSeq;
    const res = await api("POST", "/api/batches/preview", batchBody());
    if (seq !== S.batchSeq || ed !== S.bEditor) { return; }
    if (res.status !== 200) {
      $("#b-editor-status").textContent = errorText(res);
      $("#b-totals").textContent = "";
      $("#b-submit").disabled = true;
      return;
    }
    ed.rows = res.data.rows;
    $("#b-editor-status").textContent = "";
    renderBatchPreview(res.data);
  }, 300);

  function openBatchEditor(stories) {
    S.bEditor = {stories: stories.slice(), rows: []};
    showTab("batches");
    showBatchBox("editor");
    $("#b-editor-stories").textContent = "Stories: " + stories.join(", ");
    clear($("#b-variants"));
    clear($("#b-preview thead"));
    clear($("#b-preview tbody"));
    $("#b-totals").textContent = "";
    $("#b-editor-status").textContent = "";
    $("#b-submit").disabled = true;
    addVariantCard();
    batchPreview();
  }

  async function submitBatch() {
    if (!S.bEditor) { return; }
    $("#b-submit").disabled = true;
    $("#b-editor-status").textContent = "submitting...";
    const res = await api("POST", "/api/batches", batchBody());
    if (res.status === 201) {
      S.bEditor = null;
      openBatch(res.data.batch.id);
      return;
    }
    $("#b-editor-status").textContent = errorText(res);
    $("#b-submit").disabled = false;
  }

  function promptCount() { $("#b-prompt-count").textContent = $("#b-prompt-text").value.length + " / 20000 characters"; }

  function closePromptDialog() {
    S.batchPrompt = null;
    show($("#b-prompt-dialog"), false);
  }

  function openPromptDialog(storyId, index) {
    const card = batchCards()[index];
    if (!card || !S.bEditor) { return; }
    const row = S.bEditor.rows.find(function (r) { return r.story_id === storyId; });
    const original = row && row.fields ? row.fields.narrative : "";
    S.batchPrompt = {card: card, storyId: storyId};
    $("#b-prompt-title").textContent = "Prompt for " + storyId + " in " + card.querySelector(".b-label").value;
    $("#b-prompt-text").value = card.perStory[storyId] !== undefined ? card.perStory[storyId] : original;
    promptCount();
    show($("#b-prompt-dialog"), true);
    $("#b-prompt-text").focus();
  }

  // --- the batch page (BF39)

  async function useBatchWorkspace(ws) {
    if (S.ws === ws) { return; }
    const select = $("#ws-select");
    if (!hasOption(select, ws)) { select.appendChild(el("option", {value: ws, text: ws})); }
    select.value = ws;
    await selectWorkspace(ws);
  }

  function setVideo(td, ws, path, original) {
    const box = td.querySelector(".b-video");
    if (!path) {
      if (original && !box.firstChild) { box.appendChild(el("span", {cls: "muted", text: "no movie.mp4 yet"})); }
      return;
    }
    if (box.querySelector("video")) { return; }
    clear(box).appendChild(el("video", {src: batchFileUrl(ws, path), controls: "", preload: "metadata",
                                        cls: original ? "b-original-video" : "b-fork-video"}));
  }

  function playRow(tr) {
    const videos = Array.prototype.slice.call(tr.querySelectorAll("video"));
    videos.forEach(function (v) {
      v.pause();
      v.currentTime = 0;
      v.muted = !v.classList.contains("b-original-video");
    });
    videos.forEach(function (v) {
      const playing = v.play();
      if (playing && playing.catch) { playing.catch(function () {}); }
    });
  }

  function chipText(cell, view) {
    const p = view.job && view.job.progress;
    if ((view.state === "starting" || view.state === "running") && p && p.phase) {
      return "Phase " + p.phase + ": " + (p.phase_title || "") +
        (p.panels_total ? ", panels " + p.panels_done + "/" + p.panels_total : "");
    }
    if (view.state === "queued" && view.job) { return "queued (#" + view.job.queue_position + ")"; }
    if (cell.reason && ["refused", "cancelled", "interrupted"].indexOf(view.state) >= 0) { return view.state + ": " + cell.reason; }
    return view.state;
  }

  function buildBatchGrid(rec) {
    clear($("#b-grid thead")).appendChild(el("tr", {}, [el("th", {text: "Story"}), el("th", {text: "Original"})].concat(
      rec.variants.map(function (v) { return el("th", {text: v.label}); }))));
    const body = clear($("#b-grid tbody"));
    S.batchGrid = {id: rec.id, originals: {}, cells: []};
    rec.stories.forEach(function (storyId, s) {
      const original = el("td", {}, [el("div", {cls: "b-video"})]);
      const play = button("Play row", function () { playRow(tr); });
      play.className = "b-play-row";
      const tr = el("tr", {}, [el("td", {}, [el("div", {text: storyId}), play]), original]);
      S.batchGrid.originals[storyId] = original;
      rec.variants.forEach(function (_v, m) {
        const td = el("td", {}, [el("div", {cls: "b-video"}), el("div", {cls: "b-info"})]);
        S.batchGrid.cells[s * rec.variants.length + m] = td;
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
  }

  function fillBatchCell(td, rec, cell, view) {
    setVideo(td, rec.workspace, view.movie, false);
    const info = clear(td.querySelector(".b-info"));
    info.appendChild(el("span", {cls: "chip", text: chipText(cell, view)}));
    if (cell.level) {
      info.appendChild(document.createTextNode(" "));
      info.appendChild(levelBadge(cell.level));
    }
    cell.diff.forEach(function (d) { info.appendChild(el("div", {cls: "muted", text: diffLine(d)})); });
    const actions = el("div", {cls: "row"});
    if (view.dir) {
      const open = button("Open story", async function () {
        await useBatchWorkspace(rec.workspace);
        openStory(cell.fork_id);
      });
      open.className = "b-open";
      actions.appendChild(open);
    }
    if (view.job) {
      const log = button("Log", function () { selectJob(cell.job_id); showTab("jobs"); });
      log.className = "b-log";
      actions.appendChild(log);
    }
    if (view.job && ["queued", "starting", "running"].indexOf(view.state) >= 0) {
      const cancel = button("Cancel", async function () {
        if (await askConfirm("Cancel the job of fork " + cell.fork_id + "?")) {
          await api("POST", "/api/jobs/" + cell.job_id + "/cancel", {});
          pollBatch();
        }
      });
      cancel.className = "b-cancel-cell";
      actions.appendChild(cancel);
    }
    info.appendChild(actions);
  }

  function renderBatchPage(data) {
    const rec = data.batch;
    $("#b-page-title").textContent = "Batch " + rec.id + " (" + rec.status + ")";
    show($("#b-resume"), rec.status === "interrupted");
    if (!S.batchGrid || S.batchGrid.id !== rec.id) { buildBatchGrid(rec); }
    rec.stories.forEach(function (storyId) {
      setVideo(S.batchGrid.originals[storyId], rec.workspace, data.view.originals[storyId], true);
    });
    rec.cells.forEach(function (cell, i) { fillBatchCell(S.batchGrid.cells[i], rec, cell, data.view.cells[i]); });
  }

  async function pollBatch() {
    if (S.stopped || !S.batchId) { return; }
    const id = S.batchId;
    const res = await api("GET", "/api/batches/" + id);
    if (id !== S.batchId || $("#b-page").hidden) { return; }
    if (res.status !== 200) {
      $("#b-page-status").textContent = errorText(res);
      return;
    }
    renderBatchPage(res.data);
  }

  async function openBatch(batchId) {
    S.batchId = batchId;
    S.batchGrid = null;
    showTab("batches");
    showBatchBox("page");
    clear($("#b-grid thead"));
    clear($("#b-grid tbody"));
    $("#b-page-title").textContent = "Batch " + batchId;
    $("#b-page-status").textContent = "";
    S.timers.batch = setInterval(pollBatch, BATCH_POLL_MS);
    await pollBatch();
  }

  function setupBatches() {
    const editor = $("#b-editor");
    editor.addEventListener("input", function () { batchPreview(); });
    editor.addEventListener("change", function () { batchPreview(); });
    editor.addEventListener("click", function (event) {
      if (event.target.tagName === "BUTTON" && event.target.id !== "b-submit" && event.target.id !== "b-discard") { batchPreview(); }
    });
    $("#b-add-variant").addEventListener("click", addVariantCard);
    $("#b-submit").addEventListener("click", submitBatch);
    $("#b-discard").addEventListener("click", function () { S.bEditor = null; loadBatches(); });
    $("#b-back").addEventListener("click", function () { S.batchId = null; loadBatches(); });
    $("#b-cancel").addEventListener("click", async function () {
      const id = S.batchId;
      if (!id || !(await askConfirm("Cancel batch " + id + "? Queued forks are removed; running jobs stop and keep their partial output."))) { return; }
      const res = await api("POST", "/api/batches/" + id + "/cancel", {});
      $("#b-page-status").textContent = res.status === 200 ? "cancelled" : errorText(res);
      pollBatch();
    });
    $("#b-resume").addEventListener("click", async function () {
      const res = await api("POST", "/api/batches/" + S.batchId + "/resume", {});
      $("#b-page-status").textContent = res.status === 200 ? res.data.pending + " fork(s) to submit again" : errorText(res);
      pollBatch();
    });
    $("#b-delete").addEventListener("click", async function () {
      const id = S.batchId;
      if (!id || !(await askConfirm("Delete the record of batch " + id + "? The forks stay as ordinary stories."))) { return; }
      const res = await api("DELETE", "/api/batches/" + id);
      if (res.status === 200) {
        S.batchId = null;
        loadBatches();
      } else {
        $("#b-page-status").textContent = errorText(res);
      }
    });
    $("#b-prompt-text").addEventListener("input", promptCount);
    $("#b-prompt-save").addEventListener("click", function () {
      if (S.batchPrompt) { S.batchPrompt.card.perStory[S.batchPrompt.storyId] = $("#b-prompt-text").value; }
      closePromptDialog();
      batchPreview();
    });
    $("#b-prompt-original").addEventListener("click", function () {
      if (S.batchPrompt) { delete S.batchPrompt.card.perStory[S.batchPrompt.storyId]; }
      closePromptDialog();
      batchPreview();
    });
    $("#b-prompt-close").addEventListener("click", closePromptDialog);
  }

  // --- characters (MU82) ---------------------------------------------------------------
```

**3.15.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
    setupStories();
```

with:

```javascript
    setupStories();
    setupBatches();
```

**3.16.** Edit `static/movie-ui/app.css`: replace this text, which occurs exactly once:

```css
  --on-bad: #ffffff; --on-accent: #ffffff; --warn-bg: rgba(178, 106, 0, 0.12);
}
@media (prefers-color-scheme: dark) {
```

with:

```css
  --on-bad: #ffffff; --on-accent: #ffffff; --warn-bg: rgba(178, 106, 0, 0.12);
}
/* batch forks spec BF40: the fork level badges (two classes, so .badge's border does not win) */
.badge.level-render { border-color: #1f8a3b; }
.badge.level-stills { border-color: #b26a00; }
.badge.level-replan { border-color: #8a3fd1; }
@media (prefers-color-scheme: dark) {
```

**3.17.** Edit `static/movie-ui/app.css`: replace this text, which occurs exactly once:

```css
    --on-bad: #10131a; --on-accent: #10131a; --warn-bg: rgba(240, 166, 58, 0.18);
  }
}
```

with:

```css
    --on-bad: #10131a; --on-accent: #10131a; --warn-bg: rgba(240, 166, 58, 0.18);
  }
  .badge.level-render { border-color: #4cc26b; }
  .badge.level-stills { border-color: #f0a63a; }
  .badge.level-replan { border-color: #b98cff; }
}
```

**3.18.** Edit `static/movie-ui/app.css`: replace this text, which occurs exactly once:

```css
.preset-locked { opacity: .55; }
#c-res-preset { margin: 0 .25rem; }
```

with:

```css
.preset-locked { opacity: .55; }
#c-res-preset { margin: 0 .25rem; }

/* batch forks spec BF40: the batch page */
.chip { display: inline-block; padding: 1px 8px; border: 1px solid var(--line); border-radius: 10px; font-size: 12px; }
#b-grid video { max-width: 320px; }
```

- [ ] **Step 4: Run the new test, the syntax check, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bulk-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_movie_ui_batch.py::test_bt13_the_static_page 2>&1 | tail -1
```

Expected: `1 passed`. Then run `node --check static/movie-ui/app.js && echo "app.js ok"`; expected: `app.js ok`. Run the compile check with `FILES` = `tests/test_movie_ui_batch.py`; expected: `compiled 1` twice. Then run the gate block with `N=5`. Expected:
- `GATE PASS`, `lost 5 (listed 5, unexpected 0); new tests 82, not passing 0`, and `offline unchanged`;
- the new `LOST` line is `tests/test_location_ui.py::test_lu13_the_static_page listed`.

`test_mut24_page_headers_and_asset_rules` (the forbidden patterns and the one `<script>`) must still pass. It is in the must-stay-green set.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bulk-wt/qwen-agent-workspace
git add static/movie-ui/index.html static/movie-ui/app.js static/movie-ui/app.css tests/test_movie_ui_batch.py
git diff --cached --name-only    # expected: those 4 paths
git commit -m "feat(movie-ui): the batch page: Stories checkboxes, the Batches tab, the variant editor with live preview, the compare grid and Play row (BF36-BF40; BT13)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Whole-branch review, the test-only re-baseline (spec 7.1), BK1-BK8 and the hand-off

**Files:**
- Modify (test-only, Step 2):
  - `tests/test_movie_ui_http.py`: `test_mut18` `:43`;
  - `tests/test_location_ui.py`: `test_lu1` `:66`, `test_lu13` `:389`;
  - `tests/test_movie_ui_builder.py`: `NEW_PY` `:215`, `test_mut25_source_scan` `:259`;
  - `tests/movie_ui_testutil.py`: `copy_ui` `:464`.

**Interfaces:**
- Consumes: the commits of Tasks 1-5.
- Produces: the one test-only re-baseline commit (spec 7.1, 9 step 4), `$D/final-pytest.txt`, and the hand-off report.

- [ ] **Step 1: Design review (controller; spec 9 step 5).**
  - Ask an Opus `design-reviewer` to review `git diff 574303a..HEAD -- qwen-agent-workspace` against the spec, this plan's rulings and the Review Focus.
  - Fix every finding in a new commit on the owning task's files, then rerun that task's Step 4.
  - The re-baseline below comes after the review.

- [ ] **Step 2: The re-baseline edits (spec 7.1; test-only).**

**2.1.** The `test_mut18` route count. Edit `tests/test_movie_ui_http.py`: replace this text, which occurs exactly once:

```python
    assert len(srv.ROUTES) == 46
```

with:

```python
    assert len(srv.ROUTES) == 54
```

**2.2.** The `test_lu1` route count. Edit `tests/test_location_ui.py`: replace this text, which occurs exactly once:

```python
    assert len(srv.ROUTES) == 46
```

with:

```python
    assert len(srv.ROUTES) == 54
```

**2.3.** The `test_lu13` `TABS` string. Edit `tests/test_location_ui.py`: replace this text, which occurs exactly once:

```python
    assert ('const TABS = ["compose", "stories", "characters", "locations", "actions", "loras", '
```

with:

```python
    assert ('const TABS = ["compose", "stories", "batches", "characters", "locations", "actions", "loras", '
```

**2.4.** `NEW_PY`. Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
          "tests/test_movie_ui_progress.py", "tests/test_movie_ui_http.py", "tests/test_movie_ui_traces.py")
```

with:

```python
          "tests/test_movie_ui_progress.py", "tests/test_movie_ui_http.py", "tests/test_movie_ui_traces.py",
          "movie_ui_batch.py", "tests/test_movie_ui_batch.py")
```

**2.5.** The `allowed` import set. Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
                   "subprocess", "sys", "threading", "time", "fleet_lib", "movie_ui_lib"}
```

with:

```python
                   "subprocess", "sys", "threading", "time", "fleet_lib", "movie_ui_lib", "movie_ui_batch"}
```

**2.6.** `copy_ui`. Edit `tests/movie_ui_testutil.py`: replace this text, which occurs exactly once:

```python
    for rel in ("bin/movie-ui", "bin/movie-ui-job", "movie_ui_lib.py", "movie_ui_server.py", "fleet_lib.py"):
```

with:

```python
    for rel in ("bin/movie-ui", "bin/movie-ui-job", "movie_ui_lib.py", "movie_ui_server.py", "fleet_lib.py",
                "movie_ui_batch.py"):
```

**2.7.** Run this check:

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bulk-wt/qwen-agent-workspace
git diff --numstat -- tests/
```

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bulk-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_movie_ui_http.py::test_mut18_every_api_route_needs_the_token \
  tests/test_location_ui.py::test_lu1_the_location_routes_need_the_token \
  tests/test_location_ui.py::test_lu13_the_static_page \
  tests/test_movie_ui_builder.py::test_mut25_source_scan_of_new_python_files \
  tests/test_movie_ui_builder.py::test_mut25_every_new_and_changed_file_compiles \
  tests/test_movie_ui_jobs.py::test_mut15_bin_movie_ui_lock_port_and_startup_lines 2>&1 | tail -1
```

Expected: four numstat lines, in `git`'s path order:
- `2	1	qwen-agent-workspace/tests/movie_ui_testutil.py`
- `2	2	qwen-agent-workspace/tests/test_location_ui.py`
- `3	2	qwen-agent-workspace/tests/test_movie_ui_builder.py`
- `1	1	qwen-agent-workspace/tests/test_movie_ui_http.py`

Then `7 passed`: `test_mut18`, `test_lu1`, `test_lu13`, `test_mut25_source_scan`, both `test_mut25_every_new_and_changed_file_compiles` cases (the 3.9 case now compiles `movie_ui_batch.py` and its test file), and `test_mut15`. If a value differs, fix the Edit, not this command.

- [ ] **Step 3: Commit (test-only; spec 7.1, 9 step 4).**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bulk-wt/qwen-agent-workspace
git add tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_builder.py tests/movie_ui_testutil.py
git diff --cached --name-only    # expected: only those 4 paths
git commit -m "test: re-baseline mut18 and lu1 (54 routes), lu13 (the batches tab), mut25 (movie_ui_batch compiled, scanned and allowed) and copy_ui for mut15 (batch forks spec 7.1)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4: BK6, BK7: the full suite against the baseline (about 17 minutes).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/bulk-baseline
cd $S/bulk-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/final-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt; tail -1 $D/final-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/final-pytest.txt $D/expected-failures.txt 6
diff <(grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt | sort) <(grep -E '^(FAILED|ERROR)' $D/final-pytest.txt | sort) && echo "same failures, same messages"
diff <(grep -E '^PASSED' $D/baseline-pytest.txt | sort) <(grep -E '^PASSED' $D/final-pytest.txt | sort) | grep '^<' || echo "no lost pass"
grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $D/final-pytest.txt
diff <(python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1) $D/baseline-offline.txt && echo "offline unchanged"
```

Expected:
- the final summary is the baseline's with the pass count higher by exactly 82, the new cases (77 BT cases and 5 Review Focus pins; Plan ruling BR21);
- `lost 0 (listed 0, unexpected 0); new tests 82, not passing 0` and `GATE PASS`;
- `same failures, same messages` and `no lost pass` (BK7);
- `1` (BK6: `test_mut26` passes unedited);
- `offline unchanged`.

If a timing-sensitive test failed in one run only, rerun it alone and record both results. Any other difference: stop and report.

- [ ] **Step 5: BK1-BK5, BK8 and the isolation checks.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bulk-wt/qwen-agent-workspace
B=tests/test_movie_ui_batch.py
H=tests/test_movie_ui_http.py
python3 -B -m pytest -q -p no:cacheprovider $B::test_bt1_every_default_field_is_classified $B::test_bt1_a_one_key_change_gives_its_level 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider $H::test_bt25_the_original_is_byte_identical_after_its_forks_ran 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider $H::test_bt24_a_render_fork_runs_on_the_copied_story 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider $B::test_bt10_the_submit_order $H::test_bt17_queue_order_after_the_existing_queue 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider $H::test_bt18_a_cell_that_fails_v6_leaves_no_folder $H::test_bt23_not_enough_free_space $H::test_bt27_cancelling_a_fork_job_removes_its_folder tests/test_movie_ui_jobs.py::test_bt28_batch_recovery_after_a_restart 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider $B::test_bt31_a_matching_pair_gives_the_cell_fields $B::test_bt31_none_and_gone $B::test_bt31_mismatch $H::test_bt32_a_fork_whose_job_was_deleted_uses_its_batch_cell $H::test_bt33_last_fields_win_over_the_batch_cell $H::test_bt34_a_missing_or_mismatched_record_leaves_the_fork_ineligible $H::test_bt35_a_deleted_batch_leaves_its_job_less_forks_ineligible 2>&1 | tail -1
git diff --stat 574303a..HEAD -- bin story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py location_lib.py location_dataset.py | tail -1
git diff --name-only 574303a..HEAD
git diff 574303a..HEAD -- tests/ | grep -E '^\+' | grep -nE "8177|8178|expanduser\(|urlopen|import requests|zshenv|fleet\.env|macstudio" || echo "no model-server port, real HOME, HTTP client or private host in the new tests"
git diff 574303a..HEAD -- movie_ui_batch.py | grep -E '^\+(import|from) '
```

Expected, in order:
- BK1: `26 passed`;
- BK2: `1 passed`;
- BK3: `1 passed`;
- BK4: `2 passed`;
- BK5: `4 passed`;
- BK8: `21 passed` (BT31's 14 cases, BT32, BT33, BT34's 4 cases, BT35);
- no output from the pipeline `--stat` (no pipeline file changed);
- the changed paths are exactly the 2 docs (the spec and this plan) plus `movie_ui_batch.py`, `movie_ui_lib.py`, `movie_ui_server.py`, `static/movie-ui/app.css`, `static/movie-ui/app.js`, `static/movie-ui/index.html`, `tests/batch_testutil.py`, `tests/movie_ui_testutil.py`, `tests/test_location_ui.py`, `tests/test_movie_ui_batch.py`, `tests/test_movie_ui_builder.py`, `tests/test_movie_ui_http.py`, `tests/test_movie_ui_jobs.py` and `tests/test_vlm_lifecycle.py`, each with the `qwen-agent-workspace/` prefix;
- `no model-server port, real HOME, HTTP client or private host in the new tests`;
- exactly five import lines: `+import json`, `+import os`, `+import re`, `+import stat`, `+import movie_ui_lib as lib` (BF1).

- [ ] **Step 6: Hand-off (controller; not an executor step).**
  - Report the branch `bulk-rerun` and its 6 new commits (5 task commits and the re-baseline), with BK1-BK8.
  - Push and the merge are a separate step that needs the user's approval.

---

## Post-merge: live check (coordinator only; spec 8; not a task and not a merge gate)

The coordinator runs this after the merge, never an implementer:
- It renders two forks, which loads models. It needs the user's go-ahead.
- This Mac only, never macstudio. Never touch `:8178`. Never read `~/.zshenv` or `fleet.env`.

Steps:
- [ ] On the Stories tab, tick one story that has a movie, then New batch (1). Add two variants, each with one Render setting (for example two Video LoRA strengths), and Submit batch.
- [ ] When both forks are done, on the batch page, check that both forks play and that Play row starts the original and both forks together, with only the original's sound.

---

## Coverage

### Spec coverage: requirement → task

| Requirement | Task (step) |
|---|---|
| BF1 module rules | 1 (`movie_ui_batch.py`); 6 Step 5 (the import check) |
| BF2 import, `BATCH_LOCK`, `batch_queue`/`batch_thread`, lock rule | 2 (3.2-3.4); 3, 4 (every lock use) |
| BF3 `batches/`, 0600/0700 | 2 (3.1 `STATE_SUBDIRS`); 3 (`write_batch`, `lib.make_dir`) |
| BF4 classification table | 1 (`FIELD_LEVELS`) |
| BF5 merge | 1 (`original_fields`, `merge`) |
| BF6 prompt edits | 1 (`edit_prompt`) |
| BF7 identical | 1 (`plan_cells`/`_build`, `IDENTICAL`) |
| BF8 diff | 1 (`classify`) |
| BF9 level, no story.md | 1 (`classify`) |
| BF10 shorter clips warning | 1 (`classify`) |
| BF11 duplicate variant | 1 (`_build`) |
| BF12 unusable settings | 1 (`_build`, `_unusable`) |
| BF13 fork ID | 1 (`fork_id`, `_early_refusal`) |
| BF14 batch number | 1 (`next_number`); 2 (`next_batch_number`) |
| BF15 in-batch collision, existing directory | 1 (`_early_refusal`); 3 (`FileExistsError` at step 4) |
| BF16 copy plan | 1 (`copy_plan`) |
| BF17 never copied | 1 (`COPY_FILES` allowlist; BT8) |
| BF18 copy execution | 3 (`_fork_cell` step 4) |
| BF19 `fork.json`, `remove_fork` | 3 (`_fork_cell`, `remove_fork`) |
| BF20 `batch.json` | 3 (`make_batch_record`, `_cell_update`) |
| BF21 routes and responses | 2 (preview, stories); 3 (list, create, detail); 4 (delete, cancel, resume) |
| BF22 eligibility | 1 (`eligibility_reason`); 2 (`job_index`, `story_status`) |
| BF23 planning | 1 (`plan_cells`); 2 (`plan_batch`) |
| BF24 submit | 3 (`_h_batch_create`, `_batch_kick`) |
| BF25 submitter | 3 (`_batch_submitter`) |
| BF26 per-cell exception | 3 (`_submit_cell`) |
| BF27 queue order | 1 (`submit_order`); 3 (`make_batch_record`) |
| BF28 one cell | 3 (`_submit_cell`, `_fork_cell`) |
| BF29 reconcile | 3 (`reconcile`, `_known_batch`, `_h_batches`) |
| BF30 job-cancel hook | 4 (`_batch_job_cancelled`, `_h_job_cancel`) |
| BF31 cancel batch | 4 (`_h_batch_cancel`) |
| BF32 restart | 4 (`batch_recovery`, `main`) |
| BF33 submit remaining | 4 (`_h_batch_resume`) |
| BF34 delete batch | 4 (`_h_batch_delete`) |
| BF35 display state | 3 (`batch_view`) |
| BF36 Stories tab | 5 (3.2, 3.12, 3.13, `pickCell`) |
| BF37 Batches tab | 5 (3.1, 3.3, 3.7, 3.8, `showBatchBox`, `loadBatches`) |
| BF38 editor | 5 (3.3, 3.4, 3.9-3.11, the editor functions) |
| BF39 batch page | 5 (3.3, 3.6, the page functions) |
| BF40 CSS | 5 (3.16-3.18) |
| BF41a precedence | 2 (`originals_info`: `last_fields` first) |
| BF41b reading | 2 (`stored_fields`) |
| BF41c check | 1 (`fork_fallback`) |
| BF41d field source | 1 (`merge` takes the fallback fields like `last_fields`); 3 (step 9 stores `fields`) |
| BF41e where it applies | 2 (`story_status`, `plan_batch`, `preview_row`); 3 (the step 2 recompute) |
| BF41f deleted batch | 4 (`_h_batch_delete`; BT35) |
| §6 error table | 1 (the 400 lines); 2 (bad `ws`); 3 (409 every cell refused, 404 unknown batch, cell refusals); 4 (409/500 lines) |
| §7.1 re-baseline | 6 (Step 2) |
| §9 rollout | Before Task 1 (snapshot, baseline); 1-5 (feature commits); 6 (review, test-only commit, KPIs) |
| G1-G5 | G1 1; G2 2, 3, 4; G3 2; G4 5; G5 1-5 |

### Test IDs and their owning task (each is owned by exactly one task)

| IDs | Task | File | Cases |
|---|---|---|---|
| BT1-BT12, BT31, Review Focus 5 | 1 | `tests/test_movie_ui_batch.py` | 53 (BT1 26, BT9 2, BT31 14, others 1 each) |
| BT15, Review Focus 2 | 2 | `tests/test_movie_ui_http.py` | 2 |
| BT16-BT19, BT22-BT26, BT32-BT34, Review Focus 1, 3, 4 | 3 | `tests/test_movie_ui_http.py` | 18 (BT34 4) |
| BT30 | 3 | `tests/test_vlm_lifecycle.py` | 1 |
| BT14, BT20, BT21, BT27, BT29, BT35 | 4 | `tests/test_movie_ui_http.py` | 6 |
| BT28 | 4 | `tests/test_movie_ui_jobs.py` | 1 |
| BT13 | 5 | `tests/test_movie_ui_batch.py` | 1 |
| the spec 7.1 re-baselines | 6 | the four spec 7.1 files | (existing tests) |

Totals: 82 new cases, of which 77 are BT cases and 5 are Review Focus pins. Cumulative new cases after each task: 53, 55, 74, 81, 82.

### KPI → task

| KPI | Measured by |
|---|---|
| BK1 | Task 1 (BT1); Task 6 Step 5 |
| BK2 | Task 3 (BT25); Task 6 Step 5 |
| BK3 | Task 3 (BT24); Task 6 Step 5 |
| BK4 | Task 1 (BT10), Task 3 (BT17); Task 6 Step 5 |
| BK5 | Task 3 (BT18, BT23), Task 4 (BT27, BT28); Task 6 Step 5 |
| BK6 | every Step 4 gate (`test_mut26` is in the must-stay-green set); Task 6 Step 4 |
| BK7 | Before Task 1 Step 3 (baseline); every Step 4 gate; Task 6 Steps 3, 4 |
| BK8 | Task 1 (BT31), Task 3 (BT32-BT34), Task 4 (BT35); Task 6 Step 5 |

### Self-review

- **Spec coverage.** Every requirement BF1-BF41 maps to a task in the table above. Every test BT1-BT35 has real test code in its owning task, and every KPI BK1-BK8 has a measuring step. G1-G5 and §7.1 each have a step.
- **Placeholders.** The only symbolic values are `$S`, `$D`, `$B`, `$H` and `N` (the gate block), each defined in its block or in the house rules. No step says "add error handling", "TBD" or "similar to Task N". Every Edit names its old text, which occurs exactly once at its turn, with or without its last newline (checked by replay).
- **Type and name consistency.** The names below appear with the same signature in every task that uses them:
  - `plan_cells(stories, variants, number, ws_real, state, originals, validate, exists)` and its `originals` keys (`dir`, `has_story`, `busy_job`, `fields`, `code`, `batch`, `number`);
  - `plan_batch(server, clean, number) -> (cells, originals)`; `stored_fields`/`fork_fallback -> (code, fields, batch_id, number)`;
  - `make_batch_record(clean, batch_id, number, cells)`, `remove_fork(fdir, batch_id)`, `reconcile(server, batch_id)`, `batch_recovery(state)`;
  - `bt.variant(label, settings, append, replace, per_story)` (the unit tests' own `variant(settings, ..., label)` is local to `tests/test_movie_ui_batch.py`);
  - the cell keys of spec 3.1 and the preview keys of `PREVIEW_CELL_KEYS`.
- **Review Focus.** Five inputs, each with a pinning test in its owning task (Tasks 3, 2, 3, 3 and 1).

## Plan rulings (where the spec's text and its own tests, or the existing tests, cannot both hold, or the spec needs a reading)

**[defect]** rulings change behaviour from what the spec literally writes. The controller should confirm BR3 with the user before Task 1 starts. **[reading]** rulings fill a detail the spec leaves open.

1. **BR1 [reading]: six tasks and one commit per task.** The routes ship with the server code they wrap (see "Task split"), so the suggested seven tasks become six. Spec 9 step 3's single feature commit becomes five task commits, as in the prior plans. The design review comes before the test-only commit (Task 6).
2. **BR2 [reading]: `plan_cells` lives in `movie_ui_batch`.** V1 (`validate`) and the fork-directory test (`exists`) are passed in by the server's `plan_batch`, so the module still does no I/O itself (BF1). `plan_batch` remains "the single function behind preview, submit and each cell's turn" (BF23).
3. **BR3 [defect]: V1 runs before BF7, so a location strength without locations is `invalid`, not identical.**
   - Spec 3.6 orders V1 (step 6) before BF7 (step 7). The location library added V1 rule 12c (`movie_ui_lib.py:1061-1062`), which refuses `location strength needs at least one location`.
   - So BF7's example "a location strength with no locations" and BT5's "model + strength without locations → `render`" never reach BF7 or BF8 in a real preview: the cell is `invalid`.
   - The plan keeps the binding step order. BT4 and BT5 test BF7 and BF8 through `plan_cells` with a passing V1 fake, where the spec's examples hold exactly. BT22 (HTTP) uses an empty variant and a whitespace-only append.
   - Spec amendment (BF7): "such as `goal` ending in `.` or whitespace-only prompt edits (a location strength without locations is refused earlier by V1 rule 12c)".
4. **BR4 [reading]: BF11 and BF15 compare a cell only with earlier cells whose status is `ok`.** A refused cell makes no folder.
   - In BF28 step 2's recompute, the batch's own already-forked cells are refused as "already exists", so they no longer count.
   - So a cell's turn cannot detect that it became a duplicate of an earlier, already queued variant. Duplicates are refused at submit time.
5. **BR5 [reading]: the extra `panels … resolved from length` entry is the last entry of the diff,** after the key entries in `DEFAULT_FIELDS` order.
6. **BR6 [reading]: the order of the 400 lines.**
   - "In table order" is read row-major: all label lines, then all fixed-or-unknown key lines, and so on.
   - Within a row, variant K ascends, then pair J. Keys follow the variant's settings order.
7. **BR7 [reading]: request shapes spec 6 leaves open.**
   - A variant that is not an object gives the `variants must be a list of 1 to 6 variants` line.
   - `settings` that is not an object gives `variant K: settings must be an object` (in the fixed-or-unknown row). A `prompt` that is not an object gives `variant K: prompt must be an object` (in the append row).
   - A replace pair is an object with exactly the keys `find` and `with`. A missing label gives the label line.
   - Story IDs are distinct as exact strings; case-insensitive collisions are BF15's. `seed_upload: null` with a resolution is no error.
8. **BR8 [reading]: a cell's `warnings`.** The prompt-edit warnings stay on a cell refused by V1, BF7 or BF11; the over-length warning is why V1 refuses. A cell refused at steps 1-4 has none. `level` is set only on `ok` cells.
9. **BR9 [reading]: BF28 step 1 checks `pending` before `cancel_requested`.** A resumed batch's stored `order` still lists its queued cells, which must stay queued. For a pending cell the result is the spec's.
10. **BR10 [reading]: `stored_fields`'s `lstat` `S_ISREG` test is `os.path.isfile(p) and not os.path.islink(p)`.** It is equivalent, and spec 7.1 grows `test_mut25`'s allowed imports only by `movie_ui_batch`, not by `stat`.
11. **BR11 [reading]: eligibility and plan step 1 use `_h_stories`' directory rule, including `_inside`.** A story directory that is a symlink out of `generated/stories` is not listed and "no longer exists".
12. **BR12 [reading]: `copy_plan` reads `images/` and `clips/` only when they are real directories** (Review Focus 5). Spec 2.6's "never follow a link out of the story" covers linked directories too.
13. **BR13 [reading]: a failed `fork.json` write.** The new fork directory is empty, and `remove_fork` cannot match it without a `fork.json`. So `os.rmdir` removes it, and the cell is refused with `copy failed: …` (BK5).
14. **BR14 [reading]: `edit_prompt` raises `TypeError` for a text that is not a string** (a saved narrative of null). BF12 then gives `the saved settings of story <id> cannot be used: TypeError: the saved narrative is not a string`.
15. **BR15 [reading]: `batch_recovery` copies the job's `fields` into a cell it recovers as queued,** so the BF41 fallback works for that fork too.
16. **BR16 [reading]: preview `rows[].fields` is `original_fields`** (merge step 1: `compose_fields` plus the fixed keys).
17. **BR17 [reading]: BF26's stderr line** is `movie-ui: batch <id>: cell <index>: internal error: <Type>: <message>`.
18. **BR18 [reading]: UI details the spec leaves open.**
   - A diff line shows each LoRA as `id-or-file-name @ strength`, so a strength-only change is visible.
   - A cell's `Cancel` asks `Cancel the job of fork <id>?`, and Discard asks nothing.
   - The chip shows `<state>: <reason>` for refused, cancelled and interrupted cells.
   - A find/replace row with an empty Find is not sent.
   - A row whose eligibility could not be read is disabled with the title `batch eligibility is not known`.
   - The level badges use `.badge.level-*`, so `.badge`'s own border never wins. The light colours come before the `@media` block and the dark ones inside it.
   - The Submit button starts disabled.
19. **BR19 [reading]: test placement.**
   - The shared helpers are the new `tests/batch_testutil.py`.
   - Each existing test file named by spec 7 gains appended tests and at most one import line. These edit no existing test.
   - `tests/movie_ui_testutil.py` changes only in the spec 7.1 commit (`copy_ui`), so `test_mut15` is red from Task 2 to Task 6, as listed.
20. **BR20 [reading]: the Review Focus tests are named `test_batch_review_focus_N_...`,** because `tests/test_movie_ui_http.py` already has `test_review_focus_1` to `_5`.
21. **BR21 [reading]: BK7's count is the baseline plus the 82 new cases,** 77 BT cases and the 5 Review Focus pins that the plan format requires.
22. **BR22 [reading]: BT7's "a 78-character ID shortened to exactly 80 with `-._` stripped" is two IDs.** One cut ends on a letter and gives exactly 80 characters. The other ends in `-.`, which is stripped, giving 78 characters. Both are valid story IDs.
23. **BR23 [reading]: BF31 cancels the job of every queued cell.** `cancel_job` answers `None` for a finished job, so finished jobs appear in neither list.
24. **BR24 [reading]: test mechanics.**
   - BT20 holds the third cell in its checks, so the fourth is still pending when the cancel arrives. Before the second cancel, the test ends the "running" job (status `cancelled` with `started`), so that cancel answers 409.
   - BT21 holds the first cell in its checks, so the batch is submitting.
   - BT29 builds the interrupted state in-process: `plan_batch`, `make_batch_record`, a `forking` cell with its folder, then `batch_recovery`.
25. **BR25 [reading]: `$D/gate.py` is the location plan's gate with `NEW_FILES` replaced and new tests counted by "not in the baseline",** because the batch tests are also appended to existing files.
26. **BR26 [reading]: clicking the Batches tab shows the batch list.** An editor in progress stays in memory until Discard or the next `New batch`.

## Questions for controller

1. **Q1 (BR3).** Confirm that a variant with only a location strength, on a story without locations, is `invalid` (V1 rule 12c) and not "identical", and that BT4 and BT5 test BF7 and BF8 through `plan_cells` with a passing V1.
2. **Q2 (BR19).** Spec 7.1 puts `copy_ui` in the test-only commit, so `test_mut15` stays red in Tasks 2-5. The location plan moved its helper edits into the first task that needed them. Moving `copy_ui` into Task 2 instead would need a spec 7.1 amendment. The plan follows the spec.
3. **Q3 (BR4).** Confirm that a cell's turn does not re-detect a duplicate of an already queued variant (refused only at submit).

## Spec defects found (for the spec author)

1. BF7's example "a location strength with no locations", and BT5's "model + strength without locations → `render`", conflict with V1 rule 12c, which spec 3.6 runs first (BR3).
2. BT7's "shortened to exactly 80 with `-._` stripped" describes two different cuts (BR22).
3. Spec 6 gives no text for a variant, `settings` or `prompt` that is not an object, or for a replace pair with other keys (BR7).
4. BF28 step 1 checks `cancel_requested` first, which would cancel the queued cells of a resumed batch whose `order` still lists them (BR9).
5. BF41b's `os.lstat` `S_ISREG` needs `stat` in `movie_ui_server.py`, which `test_mut25`'s allowed set (re-baselined in 7.1 only for `movie_ui_batch`) forbids (BR10).
6. BF31 step 4 sets status `cancelled` while the submitter may still be finishing a forking cell. BF34 then allows deleting the record mid-submit. The plan's submitter tolerates a missing record at every step, but the spec should say so.
7. BK7's "the baseline plus every BT test" leaves out the Review Focus pins that the plan format requires (BR21).

Spec 7.1's list is complete. The replay found no other existing test that the feature breaks.

## Execution handoff

Plan complete and saved to `qwen-agent-workspace/docs/superpowers/plans/2026-10-30-batch-forks.md`.

**How it was checked.**
- **Data files.** Every Create and Edit of Tasks 1-6 lives in one data file, and this plan's code blocks are rendered from those files. A renderer refused to write the plan unless the plan's Create/Edit sequence equalled the replayed sequence.
- **Edits.** A script replayed the operations in order on a scratch copy of `574303a`'s `WS` (never the worktree or the main checkout), the way an executor applies them. It checked every old text exactly once, with and without its last newline, and created files with their exact bytes. Each old text occurred exactly once at its turn.
- **Fail first, then pass.** After each task's Step 1 alone, and after the whole task, the task's test command gave the Step 2 and Step 4 summaries quoted in each task: `1 error`/`53 passed`, `2 failed`/`2 passed`, `19 failed`/`19 passed`, `7 failed`/`7 passed` and `1 failed`/`1 passed`. Task 6's command gave `5 failed, 2 passed` before the re-baseline and `7 passed` after it.
- **The existing movie-UI tests.** These files were run after Task 2, after Task 5 and after Task 6: every `tests/test_movie_ui_*.py`, `tests/test_location_ui.py` and `tests/test_vlm_lifecycle.py`.
  - After Task 2: exactly the four T2 entries failed.
  - After Task 5: exactly the five listed tests failed (`5 failed, 245 passed, 1 skipped`).
  - After Task 6: `250 passed, 1 skipped`. The skip is `test_mut26`, because the scratch copy is not a git checkout; in the worktree it runs (Task 6 Step 4).
  - `tests/test_location_lib.py`, `tests/test_model_download.py`, `tests/test_soft_panel_count.py` and `tests/test_location_tool.py`, which import the movie-UI modules, passed after Task 5.
- **The gate script** was exercised on a cut-down baseline (those files at `574303a`) against the Task 5 run. With `N=5` it printed `lost 5 (listed 5, unexpected 0); new tests 82, not passing 0` and `GATE PASS`. With `N=4` it stopped on `test_lu13`, as it should.
- **Compile.** Every new and changed Python file compiled under Python 3.9.6 and 3.13, and `node --check static/movie-ui/app.js` passed.
- **Not run.** The full suite (the baseline is Before Task 1's first job), any server other than the in-test movie-UI servers, any model and the network. The page's behaviour in a browser is not tested beyond BT13's static checks and `node --check`; the post-merge live check covers it. Everything was written under `$S/bfplan/`.

Please review the plan. Which execution approach would you prefer?
- **Subagent-driven.** A fresh Sonnet `code-executor` implements each task in `$S/bulk-wt` on branch `bulk-rerun`, and a fresh Opus reviewer checks it before the next one starts. A whole-branch review follows at the end (Task 6 Step 1).
- **Native.** One session implements every task, then one fresh Opus reviewer checks the whole branch.

I recommend subagent-driven. Tasks 2-4 build on each other's server functions and record shapes (`plan_batch`, the cell keys, `reconcile`, `remove_fork`), and Task 5 consumes every payload. One ruling (BR3) changes spec behaviour and should be confirmed first. A mistake in Task 3's copy or cancel paths would delete or overwrite a user's story folder.
