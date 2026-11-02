# Seed Models Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Seeds tab's Qwen-Image choice becomes an explicit selection from a fixed registry: Qwen-Image-2.1 q4 (the default, with the abenzerps uncensored LoRA at 1.0), q8 and bf16 through mflux, Qwen-Image-Edit-2511 q4 (Lightning built in) through mflux, and 2511 bf16 through the unchanged diffusers child. The user picks the model and 0-2 family-legal LoRAs (with a strength each) on the page; `bin/seed-edit` runs exactly that selection, screening every candidate with content safety; `bin/seed-edit-setup --model ID --lora ID` installs pinned revisions.

**Architecture:**
- **`movie_ui_seedgen.py` (Tasks 1, 2).** The registry (`QWEN_MODELS`, `QWEN_LORAS`, spec SQ3's literals) and its pure rules: lookups, `qwen_settings`, `record_settings`, `canvas_multiple`, `registry_view`, the request rows 9a-9i, the capability (now carrying the registry) and the 409 text per selected model and LoRA. `bin/seed-edit`, `bin/seed-edit-setup` and the server import it; the page gets it through the capability.
- **`movie_ui_lib.py` and `movie_ui_server.py` (Task 2).** `seed_edit_argv` adds `--qwen-model` and one `--lora ID=SCALE` per LoRA; `seed_edit_check` parses the probe's new per-model/per-LoRA shape; the server's create route, run view and runs list carry the selection.
- **`bin/seed-edit` (Task 3).** `--qwen-model`/`--lora`, the 32-multiple canvas for 2.1, lookups at pinned revisions only (`pinned_snapshot`, `pinned_file`, `weights_problem`), the probe's new shape, the explicit preflight (model, LoRAs, memory floor per model) and the family-aware mflux child spec. The auto-by-memory choice and the two override variables are removed.
- **`seed_edit_mflux_child.py` (Task 4).** Family dispatch (`QwenImage21Edit` or `QwenImageEdit`), LoRA lists, the 2.1 scheduler, the 0.24.0 gate, RGB save.
- **`bin/seed-edit-setup` (Task 5).** `--model`/`--lora`, the per-selection free-space floor with resume, pinned snapshot and single-file downloads (a LoRA repo is never snapshotted), licence lines, the per-ID probe report.
- **The page (Task 6).** The Qwen model select, LoRA rows (rebuilt only when the family or availability changes), the read-only steps text, the unavailable list, the gating, the body, the run title and the Runs Model cell.
- **Tests.** Every task edits only `tests/test_seed_edit_tool.py` and `tests/test_movie_ui_seedgen.py`, folding in the re-baselines its change needs, so every task leaves the suite green except the two known failures. New: SQT1-SQT22 and the five Review Focus pins. Removed: SGT8 (Task 3) and SGT16 (Task 5, replaced by SQT18).

**Tech Stack:**
- Python 3.13 (`python3` = `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`, pytest 8.3.4, Pillow, psutil); Python 3.9.6 (`/usr/bin/python3`) for the compile check only. The page is vanilla ES2017; `node` (`/opt/homebrew/bin/node`) runs `--check` and two extracted-function checks in tests.
- mflux is pinned `==0.24.0` in `~/mflux-edit/.venv` (never touched by this plan). No new dependency anywhere.
- Test helpers: `tests/movie_ui_testutil.py` (`set_home`, `make_stub_workspace`, `Running`, `api`, `make_hf_cache`, `kill_everything`, `PNG`, `JPEG`, `WEBP`), unchanged.

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-11-02-seed-models-design.md`, committed at `3ac29b9` on `seed-models` (requirements SQ1-SQ56, tests SQT1-SQT22). It amends `qwen-agent-workspace/docs/superpowers/specs/2026-11-02-seed-generator-design.md` ([SG], including §14a); every SG requirement stays in force except where the seed-models spec's Section 12 supersedes or amends it.
- The spec's line citations are at `aee9461`; `3ac29b9` adds only the spec, so they are also `3ac29b9`'s.
- The spec is binding. This plan changes behaviour only where the spec cannot work as written; each such case is a numbered ruling in "Plan rulings" marked **[defect]**. Rulings marked **[reading]** fill a detail the spec leaves open.

## Global Constraints

From the spec, verbatim (section in brackets):

- [Status] "The implementer makes no design decisions."
- [0.3] "No new file. Untouched: `character_dataset.py` and every other `PIPELINE_FILES` member (`test_mut26` passes unedited), `content_safety.py`, `mps_guard.py`, `z_image_skill.py`, `movie_ui_seedfolder.py`, `movie_ui_batch.py`, `tests/movie_ui_testutil.py`, `tests/test_movie_ui_builder.py`."
- [0.4] "Free-form repo IDs, local model directories or LoRA files chosen by the user (the `SEED_EDIT_QWEN_Q4_DIR` and `SEED_EDIT_LIGHTNING_FILE` overrides are removed, SQ19). diffusers `QwenImage21Pipeline`; the Qwen-Image-2.1-Turbo checkpoint; the lightx2v 2.1 Lightning LoRA (`lora.down`/`lora.up` keys mflux does not map); Viggle's 9-step mode; any q3/q5/q6 repo. User-editable steps, guidance or scheduler (steps are derived and shown read-only); negative prompts; multi-reference edits; LoRAs on the 2511 family. `bin/seed-edit-setup` installing `qwen2511-bf16` (SQ43). Running setup, a real model or a real server in tests; any agent access to the macstudio host."
- [0.5] "Every SQ requirement and SQT test is a must-have. There are no nice-to-haves."
- [SQ1] "`bin/seed-edit` and `bin/seed-edit-setup` import it at module top as `import movie_ui_seedgen as seedgen` (directly after `import movie_ui_lib as lib`). `movie_ui_seedgen.py`'s own imports stay exactly `re`, `secrets`, `time`, `movie_ui_lib` (SG1 unchanged). The registry dicts are never mutated at run time."
- [SQ2] "`seed_edit_mflux_child.py` does not import the registry ... it carries its own `FAMILIES` table, which SQT9 pins equal to the registry's `mflux_class`/`mflux_config` per family."
- [SQ3] The registry constants are "typed exactly" (the code block of SQ3); `MODELS = {"zimage": "Z-Image", "qwen": "Qwen-Image"}`.
- [SQ24] "For every registry model, with or without LoRAs, every candidate passes `content_safety.assert_image_safe` before it gets its final name ... No registry field, request field, environment variable or LoRA turns it off. `/files` keeps refusing `work/` (SG §14a item 5)."
- [SQ25] "every `lora_paths` element is a local file path inside a pinned snapshot, never a repo ID; `model_path` is a local directory; `bake_lora` is always False; `HF_HUB_OFFLINE=1` stays."
- [SQ26] "The only environment variables `bin/seed-edit` reads: `SEED_EDIT_MFLUX_PYTHON`, `SEED_EDIT_QWENEDIT_SCRIPT`, `HF_HUB_CACHE`, `HF_HOME`, `Z_IMAGE_HF_HOME`, `HOME`."
- [SQ28] The child's top-level imports stay exactly SG24's list; `MIN_VERSION = (0, 24, 0)`; mflux stays pinned `==0.24.0` (SQ42 `MFLUX_SPEC = "mflux==0.24.0"`).
- [SQ43] "A LoRA repo is never a snapshot item; `snapshot_download` is never called with a LoRA repo (abenzerps 97.96 GiB, Viggle 97.67 GiB)."
- [SQ45] "No token is read or sent (`HF_TOKEN` appears nowhere in the file)."
- [SQ56] "Every node is built with `el()`/`button()`, server text goes in through `textContent`; the page bans (`https?://`, `\son[a-z]+=`, `style=`, `\bprompt\(`, ...) and the pinned lines of SGT33 still hold."
- [9.1] "Every test sets `HOME` under `tmp_path`, removes `HF_HUB_CACHE` and every `SEED_EDIT_*` variable, sets `HF_HOME` and `Z_IMAGE_HF_HOME` under `tmp_path`; no test loads a real model, uses the real HOME, or contacts a server other than the in-test `127.0.0.1` one; none touches port 8177 or 8178; no test dispatches a job." "`bin/seed-edit-setup` is loaded in-process with `SourceFileLoader("seed_edit_setup", path)` ... and its `main` **is** called, but only with `setup.subprocess.call` (a recorder returning 0), `setup.subprocess.run` (a recorder ...), `setup.free_gib` and `setup.venv_ready` replaced, `SEED_EDIT_SETUP_PYTHON` pointing at an executable stub file under `tmp_path`, and the hub under `tmp_path` through `Z_IMAGE_HF_HOME`." "The child's behaviour is tested in-process with fake `mlx`, `mlx.core` and `mflux…` modules in `sys.modules` (SQT8); no test imports the real mflux or mlx."
- [9.4] "Content safety on every candidate of every registry model (SQT6), "a LoRA repo is never snapshotted" (SQT11), exact child class/config/kwargs per family (SQT5, SQT8, SQT9), the 32-multiple canvas for 2.1 (SQT1, SQT22), and "nothing created on 400/409" (SQT19) are load-bearing; a change that weakens one of them fails review."
- [11] "`python3 -m pytest tests/ -q -rA` from `WS` has no failures beyond the 2 known ones"; "`python3 tests/test_ltx_movie_offline.py` prints `OK 347/347`"; "push and the PR only on the user's go".

Project constraints (from the dispatch; every task's requirements include them):

- Tests: pytest from `qwen-agent-workspace`; never use the real HOME, never load a real model, never render, never contact servers (an in-test 127.0.0.1 server is OK); backends stubbed at the process boundary or with fake modules.
- Full-suite gate: the baseline is 2 known failures (`test_d2_copied_literals_match_the_spike`, `test_rst62_import_sets`) and offline `OK 347/347`; every task leaves the suite otherwise green (the only lost baseline passes are the two tests this plan deletes, SGT8 and SGT16, listed in the expected-failures file).
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never stage `.DS_Store`, `.claude/`, `__pycache__/`, repo-root `bin/`, `qwen-agent-workspace/bin/action-from-dir`, `pin-sh2.json`, `story_bible_*.json`, `.superpowers/`.
- No pipeline file outside the seed generator's files changes unless the spec says so.
- `content_safety.assert_image_safe` runs on every candidate for every model.

Controller rules (every task's requirements include them):

- Never read, cat, grep or source `~/.zshenv` or any `fleet.env`, and never print tokens or secrets.
- Never ssh, scp, rsync or HTTP to macstudio, and never read or suggest copying its files. The live checks (spec 10) are run by the user there.
- Never download model weights; never run `bin/seed-edit-setup`, a real `bin/seed-edit` run, a model, a venv creation or a pip install. Never touch :8177 or :8178.
- Never push. Push and the PR are a separate step that needs the user's go (and the PR opens after PR #6 merges, spec 11).

House rules (every task's requirements include them):

- **The checkout.** Never touch the main checkout `/Users/reubenpatterson/local_agent_harness`. Every command runs in the worktree `$S/seedmodels-wt`, branch `seed-models`. Never git stash, reset or check out other work.
- **Paths.** `S` = `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`; `WS` = `$S/seedmodels-wt/qwen-agent-workspace`; `D` = `$S/seedmodels-baseline`. The git root is `$S/seedmodels-wt`, so `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix. Run every command from `WS`; shell variables do not persist between commands, so every block defines the variables it uses.
- **Python.** Every changed file must compile on Python 3.9.6 and 3.13: no `match` statement, no `X | Y` type expressions, no walrus operator, no `str.removeprefix`, no `zip(strict=)`, no parenthesised context managers. `test_mut25` also scans these files for `urllib`, `load_module(`, `shell=True` and `X | None` text, docstrings included. The code blocks below use none of them.
- **Editing.** Executors make every change to a tracked file with the Edit tool, except the two whole-file replacements (Task 4's `seed_edit_mflux_child.py`, Task 5's `bin/seed-edit-setup`), which use the Write tool after a Read (the file keeps its mode; `bin/seed-edit-setup` stays `100755`). Never use `rm`, `sed -i`, a redirect or a script to change a tracked file.
- **Code blocks** are copied byte for byte. An Edit's old text is whole lines and occurs exactly once in the file at that moment, with or without its last newline. If it does not, stop and report; do not adapt it. Every Edit and Write below was replayed in order on a scratch copy of `3ac29b9` (see "Execution handoff").
- **Git.** Stage only the paths a task names, and check `git diff --cached --name-only` before every commit. Every commit command passes the trailer as a second `-m`.
- **The compile check** (Step 4 of each task) is this command, with the task's Python files as `FILES`. Expected: two lines, `compiled N` for 3.9 and then for 3.13.

```bash
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' FILES; done
```

## Review Focus

These five inputs and failure modes are the ones most likely to reach a user first; the spec implies them and no SQT row exercises them. Each is pinned by a test in the task that owns its code, named `test_sq_review_focus_N_...` (unique in the suite; the seed generator's are `test_sg_review_focus_N_...`).

1. **A phone-sized source that is not a multiple of 32, run on Qwen-Image-2.1.** mflux 0.24.0 refuses a 2.1 canvas side that is not a multiple of 32 (spec 0.2, 14 item 1). SQT1 tests `canvas()` alone and SQT5 uses a 1536x1024 source, whose canvas (1024x672) is the same for 16 and 32, so nothing proves `prepare_source` passes the family's multiple. Expected: an 800x600 source gives the child spec, `run.json`'s `size` and the candidate file 800x576 on `qwen21-q4` and 800x592 on `qwen2511-q4` (and Z-Image stays 800x592). Test: `test_sq_review_focus_1_the_qwen21_canvas_reaches_the_child` (Task 3).
2. **An old page tab (or a script) posts a Qwen run without `qwen_model` or `loras`.** A movie-ui tab opened before the upgrade keeps the old `app.js` and sends `{model: "qwen"}` only. SQT15 checks the defaults in the pure function and SQT19 posts explicit fields. Expected over HTTP: with the uncensored LoRA not installed, 409 `LoRA Uncensored (abenzerps) is unavailable: ...(run bin/seed-edit-setup --lora uncensored)` and nothing created; with everything installed, 201, job fields `qwen21-q4` + `[{"id": "uncensored", "scale": 1.0}]`, argv `--qwen-model qwen21-q4 --lora uncensored=1.0`, view steps 40 / scheduler `linear`. Test: `test_sq_review_focus_2_a_qwen_request_without_the_new_fields` (Task 2).
3. **A Qwen job queued before the upgrade runs after it.** Its fields have no `qwen_model`, so its argv has no `--qwen-model` (SQ12's legacy default). Expected: `lib.seed_edit_argv` gives SG29's argv; `bin/seed-edit` runs `qwen2511-q4` with no LoRA (family `qwen2511`, the pinned snapshot, the pinned Lightning file, 8 steps); the queued `run.json` keeps `created` and `job` and gains the four SQ19 keys. Test: `test_sq_review_focus_3_a_job_queued_before_the_registry` (Task 3).
4. **A host that holds a 2511 q4 snapshot downloaded at an older `main`** (spec 14 item 7, SQ47; macstudio may be one). Expected: the tool reports `mflux-community/qwen-image-edit-2511-mflux-q4@3c74aab7dd79 is not in ... (run bin/seed-edit-setup --model qwen2511-q4)`; `bin/seed-edit-setup --model qwen2511-q4` treats the snapshot and the Lightning file as needed, counts the old repo directory as present (so a free-space figure just under the full size still passes), prints both Apache-2.0 licence lines and downloads exactly the pinned snapshot and the pinned Lightning file; the old snapshot stays. Test: `test_sq_review_focus_4_an_old_main_2511_snapshot` (Task 5).
5. **The selection survives the request -> argv -> tool round trip.** The server writes `run.json` from the request and the tool rewrites it from its argv; any drift (scale formatting, LoRA order, a prompt that looks like options) would make the queued and the running record disagree or run a different selection. Expected: for scales 2, 1e-06 and 0.30000000000000004, LoRAs given in reverse registry order, every model, defaults, and a prompt containing `--qwen-model qwen21-bf16 --lora viggle-turbo=2 --model zimage`, the tool's cleaned `qwen_model`/`loras` and `qwen_settings` equal the server's, and the prompt arrives unchanged. Test: `test_sq_review_focus_5_the_selection_round_trip` (Task 3).

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `movie_ui_seedgen.py` | Modify (Tasks 1, 2) | SG's pure core plus the Qwen registry: SQ3's constants, `qwen_model`, `qwen_lora`, `registry_order`, `default_loras`, `qwen_settings`, `record_settings`, `canvas_multiple`, `registry_view`, `_qwen_fields` (rows 9a-9i), `capability` (with `registry`), `availability_error(models, detail, clean)`. |
| `movie_ui_lib.py` | Modify (Task 2) | `seed_edit_argv` (qwen selection args), `_probe_qwen`, `seed_edit_check(ws_real, model_ids, lora_ids)`. |
| `movie_ui_server.py` | Modify (Task 2) | The initial `seed_edit` capability with `registry`, `refresh_capabilities`' IDs, `_h_seed_run_create`'s check/record/fields, `run_view`'s and `_h_seed_runs`' selection keys. |
| `bin/seed-edit` | Modify (Task 3) | Options, `check_loras`, `canvas(w0, h0, multiple)`, the pinned lookups, `qwen_hubs`, `mflux_env_problem`, `lora_problem`, `qwen_model_problem`, `memory_problem`, the probe, the explicit preflight, `new_record`'s keys, the mflux spec, labels. |
| `seed_edit_mflux_child.py` | Replace (Task 4) | SQ28's body: `FAMILIES`, the two gates, per-family kwargs, RGB save. |
| `bin/seed-edit-setup` | Replace (Task 5) | SQ41-SQ47: options, `selection`, `items_of`, `item_ok`, `download_item`, the floor, `DOWNLOAD`, licences, `report`; byte copies of five tool functions. |
| `static/movie-ui/index.html`, `app.js`, `app.css` | Modify (Task 6) | The Qwen box, its eight functions, gating, body, titles, Runs cell, CSS. |
| `tests/test_movie_ui_seedgen.py` | Modify (Tasks 1, 2, 3, 5, 6) | SQT15-SQT22, Review Focus 2, and the re-baselined SGT17, SGT19, SGT22, SGT23, SGT26, SGT27, SGT31, SGT33, SGT34, SG Review Focus 5. |
| `tests/test_seed_edit_tool.py` | Modify (Tasks 1, 3, 4, 5) | SQT1-SQT14, Review Focus 1, 3, 4, 5, the helpers `pinned_cache`/`install_model`/`install_lora`/`load_setup`/`setup_env`, and the re-baselined SGT2, SGT7, SGT9, SGT10, SGT11, SGT13, SGT14, SGT15, SG Review Focus 4 and `test_sg_final_setup_resume_counts_what_is_present`; SGT8 and SGT16 deleted. |

**Task split.** Each task is the smallest unit with its own test cycle and a reviewer gate, and each leaves the full suite green:
- Task 1 is the pure registry and the request rows: nothing consumes the new keys yet, so the server keeps working.
- Task 2 is the movie-ui side. The 409 rule needs the probe's new shape, which needs the new parser, which the server calls with new arguments; they ship together. The HTTP tests use a stub `bin/seed-edit`, so the real tool is not needed yet.
- Task 3 is the whole tool: options, canvas, lookups, probe, preflight and spec share `ctx` and the record, so they ship together; the children are stubbed.
- Task 4 is the child (in-process fakes); Task 5 is the setup script (in-process recorders; SQT18 needs Task 3's functions to compare against).
- Task 6 is the page (needs the capability's `registry` from Task 2 and the canvas rule from Task 3).

The browser check, the pass bar, the design review and the live checks need a person, a browser, a running movie-ui or the user's go, so they are the controller's "Verification" section, not an implementer task. The spec requires no docs or README change.

## Between tasks: the existing suite

**The choice.** Each task edits the existing tests its change breaks in the same task (the dispatch: "fold test re-baselines into the task whose change breaks them"), so there is no test-only commit and no test stays red between tasks.

**Expected lost passes.** Only the two deleted tests, written to `$D/expected-failures.txt` in "Before Task 1" Step 3:

```text
# seed models plan: baseline passes that the given task removes on purpose
T3 tests/test_seed_edit_tool.py::test_sgt8_choose_qwen removed (choose_qwen is gone; SQT3 and SQT7 replace it)
T5 tests/test_seed_edit_tool.py::test_sgt16_the_setup_script_is_read_never_run removed (SQT18 replaces it)
```

**The gate** is `$D/gate.py` (already in place: the seed generator plan's gate; its `NEW_FILES` are the two seed test files, so every test in them must pass). Step 4 of every task runs this block with its `N` (a full run of about 18 minutes; it may run in the background):

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/seedmodels-baseline
N=1
cd $S/seedmodels-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/task-$N-pytest.txt 2>&1; tail -1 $D/task-$N-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/task-$N-pytest.txt $D/expected-failures.txt $N
diff <(python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1) $D/baseline-offline.txt && echo "offline unchanged"
```

Expected: `GATE PASS`, `not passing 0`, `baseline failures still failing 2 of 2`, `offline unchanged`, and the task's `lost` line as its Step 4 states.

**When the gate prints `GATE STOP`:** the executor stops and reports the UNEXPECTED or NEW-TEST-FAIL IDs with the output of `python3 -B -m pytest -q -p no:cacheprovider --tb=short <ids>`. A lost pass the list does not name is a defect in this task's code; the controller has an Opus reviewer rule on it and writes the exact fix. If an UNEXPECTED ID is `tests/test_fleet_tracing.py::test_trt41a_trace_cli_on_one_agent` or `tests/test_fleet_integration.py::test_t47_signatures_and_loopback_rules` (timing-sensitive, unrelated), rerun it alone; if it passes alone, the controller appends `T<N> <id> flaky` to the list and V1 rechecks it.

**Must stay green in every task** (none is in the list, so a failure stops the gate): every other test in the two seed files; `tests/test_movie_ui_builder.py` (`test_mut25_*`, `test_mut26_pipeline_files_are_unchanged`); `tests/test_movie_ui_http.py`, `test_movie_ui_jobs.py`, `test_movie_ui_seedfolder.py`, `test_movie_ui_batch.py`, `test_movie_ui_seams.py`, `test_location_ui.py` (the three `TABS` pins and `["jobs", "log", "host", "batch"]`), `tests/test_vlm_lifecycle.py`, `tests/test_character_dataset.py` (other than the baseline failure).

---

## Before Task 1: the plan commit, the snapshot, the baseline (controller; no code)

The snapshot (spec 11 step 1) and the baseline (spec 11 step 2) are already taken; these steps confirm them and write the expected-failures file.

- [ ] **Step 1: Confirm the plan commit and the tree.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/seedmodels-wt/qwen-agent-workspace
git branch --show-current                                   # expected: seed-models
git log -3 --format=%h' '%s                                 # expected: <plan sha> docs: seed models implementation plan, then 3ac29b9, aee9461
git diff --stat aee9461 HEAD -- . ':(exclude)docs' | tail -1   # expected: no output
git status --short                                          # expected: no output
wc -l movie_ui_seedgen.py movie_ui_lib.py movie_ui_server.py bin/seed-edit bin/seed-edit-setup seed_edit_mflux_child.py static/movie-ui/index.html static/movie-ui/app.js static/movie-ui/app.css tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py | head -11
```

Expected `wc -l` counts (at `3ac29b9`): `movie_ui_seedgen.py` 131, `movie_ui_lib.py` 2403, `movie_ui_server.py` 3411, `bin/seed-edit` 787, `bin/seed-edit-setup` 228, `seed_edit_mflux_child.py` 86, `index.html` 461, `app.js` 3073, `app.css` 107, `test_seed_edit_tool.py` 905, `test_movie_ui_seedgen.py` 918. If any value differs, stop and report: every Edit below was written against this tree.

- [ ] **Step 2: Confirm the compressed snapshot (house rule; spec 11 step 1; already taken).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
ls -l $S/snapshot-pre-seedmodels-aee9461.tgz
tar tzf $S/snapshot-pre-seedmodels-aee9461.tgz | grep -c 'movie_ui_server.py$'   # expected: 1
tar tzf $S/snapshot-pre-seedmodels-aee9461.tgz | grep -c '/generated/'           # expected: 0
```

If the file is missing, take it now: `tar czf $S/snapshot-pre-seedmodels-aee9461.tgz --exclude qwen-agent-workspace/generated -C $S/seedmodels-wt qwen-agent-workspace`.

- [ ] **Step 3: Confirm the baseline (spec 11 step 2; already recorded) and write the expected-failures file.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/seedmodels-baseline
tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
grep -c '^PASSED ' $D/baseline-pytest.txt
grep -cE '^PASSED tests/test_(seed_edit_tool|movie_ui_seedgen)\.py::' $D/baseline-pytest.txt
cat $D/baseline-offline.txt
grep -n 'NEW_FILES = ' $D/gate.py
```

Expected: `2 failed, 2455 passed, 2 skipped, 7622 warnings in 1062.62s (0:17:42)`; the two `FAILED` lines `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets - AssertionError: b...`; `2455`; `96`; `OK 347/347`; `7:NEW_FILES = ("tests/test_seed_edit_tool.py::", "tests/test_movie_ui_seedgen.py::")`. These files **are** the baseline.

Then write `$D/expected-failures.txt` with the Write tool: exactly the `text` block of "Between tasks" above (it is outside the repository and never staged).

---

### Task 1: The Qwen registry and the request rows (SQ1, SQ3-SQ10, SQ30; SQT10, SQT15, SQT16)

This task implements:
- SQ3's registry constants after `SOURCE_MSG`, typed exactly (`MODELS` is Task 2's change).
- SQ5-SQ10: `qwen_model`, `qwen_lora`, `registry_order`, `default_loras`, `qwen_settings`, `record_settings`, `canvas_multiple`, `registry_view` (pure).
- SQ30's rows 9a-9i in `_qwen_fields(body, model)` (PR3), called between SG33's seed row and its source rows; `clean` gains `qwen_model` and `loras`.
- Tests: SQT10 (registry pins, in `tests/test_seed_edit_tool.py`), SQT15 (26 request cases and the defaults/placement test), SQT16's settings, legacy-run, canvas-multiple and registry-view tests; SGT17's two exact `clean` dicts gain `qwen_model`/`loras` (the only existing test the new keys break).

**Files:**
- Modify: `movie_ui_seedgen.py` (docstring `:1-8`; constants after `:31`; `_qwen_fields` before `validate_run_request` `:61`; its call and `clean` `:88-97`; the eight registry functions before `capability` `:116`)
- Modify: `tests/test_movie_ui_seedgen.py` (docstring; SGT17 `:104-110`; SQT15/SQT16 after `test_sgt17_the_module_imports` `:155-159`)
- Modify: `tests/test_seed_edit_tool.py` (docstring; SQT10 before Review Focus 3 `:762`)

**Interfaces:**
- Consumes:
  - `movie_ui_lib._is_number(value) -> bool` (existing).
- Produces:
  - `movie_ui_seedgen` constants: `QWEN_FAMILIES`, `QWEN21_PATTERNS`, `QWEN21_REQUIRED`, `QWEN_RESEARCH`, `LIGHTNING`, `QWEN21_CLASS`, `QWEN2511_CLASS`, `QWEN_MODELS` (tuple of 5 dicts), `QWEN_LORAS` (tuple of 2 dicts), `QWEN_MODEL_IDS`, `QWEN_LORA_IDS`, `DEFAULT_QWEN_MODEL = "qwen21-q4"`, `LEGACY_QWEN_MODEL = "qwen2511-q4"`, `SCALE_MAX = 2.0`, `LORAS_MSG`.
  - `qwen_model(model_id) -> dict or None`; `qwen_lora(lora_id) -> dict or None`; `registry_order(loras) -> list` (sorted copy of `[{"id", "scale"}]`); `default_loras(model_id) -> [{"id", "scale"}]`.
  - `qwen_settings(model_id or None, loras) -> {"qwen_model": {"id", "repo"} or None, "loras": [{"id", "repo", "file", "scale": float}], "steps": int or None, "scheduler": str or None}`; `record_settings(record) -> the same four keys`; `canvas_multiple(model, model_id) -> 16 or 32`; `registry_view() -> {"default_model", "families", "models", "loras"}`.
  - `validate_run_request(body)`'s `clean` gains `"qwen_model"` (`None` for zimage, else a registry ID) and `"loras"` (`[]` for zimage, else `[{"id", "scale": float}]` in registry order).
  - Test helpers in `tests/test_movie_ui_seedgen.py`: `_qreq(**overrides)`, `QWEN_REQUEST_CASES` (list of `(body, message)`), `REPOS`, `UNC`, `VIG`, `_settings(model_id, loras, steps, scheduler)`.

- [ ] **Step 1: Write the failing tests.** Make these edits in order (Edit tool; each old text occurs exactly once at its turn).

**Edit 1.1** `tests/test_movie_ui_seedgen.py`: replace

```python
movie_ui_seedgen, the movie_ui_lib hooks (job policy, argv, probe, progress), the six
/api/seeds/ routes, the seed_edit capability, the job summary key and the static page.

```

with

```python
movie_ui_seedgen, the movie_ui_lib hooks (job policy, argv, probe, progress), the six
/api/seeds/ routes, the seed_edit capability, the job summary key and the static page. Also the
seed models registry (docs/superpowers/specs/2026-11-02-seed-models-design.md, Section 9.2:
SQT15-SQT22, with that plan's Review Focus pin 2).

```

**Edit 1.2** `tests/test_movie_ui_seedgen.py`: replace

```python
    assert clean == {"prompt": "make it night", "model": "zimage", "strength": 0.45, "candidates": 2, "seed": 7,
                     "source": {"kind": "upload", "upload_id": UP}}
    bare = {"prompt": " a quiet street at dusk ", "model": "zimage", "source": {"run": RUN, "n": 3}}
    clean, error = seedgen.validate_run_request(bare)
    assert error is None
    assert clean == {"prompt": " a quiet street at dusk ", "model": "zimage", "strength": 0.45,
                     "candidates": 4, "seed": None, "source": {"kind": "run", "run": RUN, "n": 3}}
    assert isinstance(seedgen.validate_run_request(_req(strength=1 / 2))[0]["strength"], float)
```

with

```python
    assert clean == {"prompt": "make it night", "model": "zimage", "strength": 0.45, "candidates": 2, "seed": 7,
                     "qwen_model": None, "loras": [], "source": {"kind": "upload", "upload_id": UP}}
    bare = {"prompt": " a quiet street at dusk ", "model": "zimage", "source": {"run": RUN, "n": 3}}
    clean, error = seedgen.validate_run_request(bare)
    assert error is None
    assert clean == {"prompt": " a quiet street at dusk ", "model": "zimage", "strength": 0.45,
                     "candidates": 4, "seed": None, "qwen_model": None, "loras": [],
                     "source": {"kind": "run", "run": RUN, "n": 3}}
    assert isinstance(seedgen.validate_run_request(_req(strength=1 / 2))[0]["strength"], float)
```

**Edit 1.3** `tests/test_movie_ui_seedgen.py`: replace

```python
        "movie_ui_lib", "re", "secrets", "time"]

```

with

```python
        "movie_ui_lib", "re", "secrets", "time"]


# --- SQT15 (seed models SQ30): the Qwen model and LoRA request rows ---------------------------------

def _qreq(**overrides):
    body = _req(model="qwen", strength=None)
    body.update(overrides)
    return body


UNC1 = {"id": "uncensored", "scale": 1}
SCALE_MSG = "LoRA uncensored scale must be a number above 0 and at most 2"
QWEN_REQUEST_CASES = [
    (_req(qwen_model="qwen21-q4"), "qwen_model is only for qwen"),
    (_req(qwen_model=""), "qwen_model is only for qwen"),
    (_req(qwen_model="x", loras="y"), "qwen_model is only for qwen"),
    (_req(loras=[]), "loras is only for qwen"),
    (_qreq(qwen_model="flux"), "unknown qwen_model flux"),
    (_qreq(qwen_model=5), "unknown qwen_model 5"),
    (_qreq(qwen_model="flux", loras="x"), "unknown qwen_model flux"),
    (_qreq(loras="x"), "loras must be a list of {id, scale}"),
    (_qreq(loras={"id": "uncensored", "scale": 1}), "loras must be a list of {id, scale}"),
    (_qreq(loras=[{}]), "loras must be a list of {id, scale}"),
    (_qreq(loras=[{"id": "uncensored"}]), "loras must be a list of {id, scale}"),
    (_qreq(loras=[{"id": "uncensored", "scale": 1, "x": 1}]), "loras must be a list of {id, scale}"),
    (_qreq(loras=["uncensored"]), "loras must be a list of {id, scale}"),
    (_qreq(loras=[{"id": 5, "scale": 1}]), "unknown LoRA 5"),
    (_qreq(loras=[{"id": "nope", "scale": 1}]), "unknown LoRA nope"),
    (_qreq(loras=[UNC1, {"id": "uncensored", "scale": 0.5}]), "LoRA uncensored is listed twice"),
    (_qreq(qwen_model="qwen2511-q4", loras=[UNC1]),
     "LoRA uncensored is for Qwen-Image-2.1, not Qwen-Image-Edit-2511 q4 (Lightning)"),
    (_qreq(qwen_model="qwen2511-bf16", loras=[{"id": "viggle-turbo", "scale": 1}]),
     "LoRA viggle-turbo is for Qwen-Image-2.1, not Qwen-Image-Edit-2511 bf16 (Lightning, diffusers)"),
    (_qreq(loras=[{"id": "uncensored", "scale": 0}]), SCALE_MSG),
    (_qreq(loras=[{"id": "uncensored", "scale": -1}]), SCALE_MSG),
    (_qreq(loras=[{"id": "uncensored", "scale": 2.01}]), SCALE_MSG),
    (_qreq(loras=[{"id": "uncensored", "scale": True}]), SCALE_MSG),
    (_qreq(loras=[{"id": "uncensored", "scale": "1"}]), SCALE_MSG),
    (_qreq(loras=[{"id": "uncensored", "scale": None}]), SCALE_MSG),
    (_qreq(loras=[{"id": "uncensored", "scale": 5}, {}]), SCALE_MSG),
    (_qreq(loras=[{"id": "nope", "scale": 1}, {}]), "unknown LoRA nope"),
]


@pytest.mark.parametrize("body,message", QWEN_REQUEST_CASES,
                         ids=["case%d" % (i + 1) for i in range(len(QWEN_REQUEST_CASES))])
def test_sqt15_the_qwen_request_rows(body, message):
    assert seedgen.validate_run_request(body) == (None, message)


def test_sqt15_qwen_defaults_order_and_placement():
    clean, error = seedgen.validate_run_request(_qreq())
    assert error is None
    assert (clean["qwen_model"], clean["loras"]) == ("qwen21-q4", [{"id": "uncensored", "scale": 1.0}])
    assert seedgen.validate_run_request(_qreq(qwen_model=None, loras=None))[0]["loras"] == [
        {"id": "uncensored", "scale": 1.0}]
    assert seedgen.validate_run_request(_qreq(qwen_model="qwen2511-q4"))[0]["loras"] == []
    assert seedgen.validate_run_request(_qreq(qwen_model="qwen2511-bf16"))[0]["loras"] == []
    assert seedgen.validate_run_request(_qreq(loras=[]))[0]["loras"] == []
    clean = seedgen.validate_run_request(_qreq(qwen_model="qwen21-q8", loras=[
        {"id": "viggle-turbo", "scale": 2}, {"id": "uncensored", "scale": 0.5}]))[0]
    assert (clean["qwen_model"], clean["loras"]) == (
        "qwen21-q8", [{"id": "uncensored", "scale": 0.5}, {"id": "viggle-turbo", "scale": 2.0}])
    assert all(isinstance(item["scale"], float) for item in clean["loras"])
    clean = seedgen.validate_run_request(_req(qwen_model=None, loras=None))[0]
    assert (clean["qwen_model"], clean["loras"]) == (None, [])
    assert seedgen.validate_run_request(_req(seed=-1, qwen_model="x")) == (
        None, "seed must be an integer from 0 to 2147483647")
    assert seedgen.validate_run_request(_req(qwen_model="x", source="x")) == (None, "qwen_model is only for qwen")
    assert seedgen.validate_run_request(_qreq(strength=0.5, qwen_model="flux")) == (
        None, "strength is only for zimage")
    for body, message in REQUEST_CASES:
        assert seedgen.validate_run_request(body) == (None, message)


# --- SQT16 (seed models SQ7-SQ10): settings, legacy runs, the canvas multiple, the registry view -------

REPOS = {"qwen21-q4": "mflux-community/qwen-image-2-1-mflux-q4", "qwen21-q8": "mflux-community/qwen-image-2-1-mflux-q8",
         "qwen21-bf16": "Qwen/Qwen-Image-2.1", "qwen2511-q4": "mflux-community/qwen-image-edit-2511-mflux-q4",
         "qwen2511-bf16": "Qwen/Qwen-Image-Edit-2511"}
UNC = {"id": "uncensored", "repo": "abenzerps/Qwen-Image-2.1-Uncensored-Quantized",
       "file": "qwen-image-2.1-uncensored-lora.safetensors"}
VIG = {"id": "viggle-turbo", "repo": "Viggle/Qwen-Image-2.1-viggle-turbo",
       "file": "Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors"}


def _settings(model_id, loras, steps, scheduler):
    return {"qwen_model": {"id": model_id, "repo": REPOS[model_id]}, "loras": loras, "steps": steps,
            "scheduler": scheduler}


def test_sqt16_qwen_settings():
    assert seedgen.qwen_settings(None, []) == {"qwen_model": None, "loras": [], "steps": None, "scheduler": None}
    for model_id in ("qwen21-q4", "qwen21-q8", "qwen21-bf16"):
        assert seedgen.qwen_settings(model_id, []) == _settings(model_id, [], 40, "linear")
        assert seedgen.qwen_settings(model_id, [{"id": "uncensored", "scale": 1}]) == _settings(
            model_id, [dict(UNC, scale=1.0)], 40, "linear")
        assert seedgen.qwen_settings(model_id, [{"id": "viggle-turbo", "scale": 0.5}]) == _settings(
            model_id, [dict(VIG, scale=0.5)], 6, "viggle_turbo")
        assert seedgen.qwen_settings(model_id, [{"id": "viggle-turbo", "scale": 1.0}, {"id": "uncensored", "scale": 0.5}]) \
            == _settings(model_id, [dict(UNC, scale=0.5), dict(VIG, scale=1.0)], 6, "viggle_turbo")
    for model_id in ("qwen2511-q4", "qwen2511-bf16"):
        assert seedgen.qwen_settings(model_id, []) == _settings(model_id, [], 8, None)
    scale = seedgen.qwen_settings("qwen21-q4", [{"id": "uncensored", "scale": 1}])["loras"][0]["scale"]
    assert isinstance(scale, float)


def test_sqt16_record_settings_and_the_canvas_multiple():
    new = dict(_settings("qwen21-q8", [dict(UNC, scale=0.5)], 40, "linear"), model="qwen", backend="mflux")
    assert seedgen.record_settings(new) == _settings("qwen21-q8", [dict(UNC, scale=0.5)], 40, "linear")
    odd = {"model": "qwen", "qwen_model": {"id": "qwen21-q4", "repo": REPOS["qwen21-q4"]}, "loras": "x"}
    assert seedgen.record_settings(odd) == {"qwen_model": odd["qwen_model"], "loras": [], "steps": None,
                                            "scheduler": None}
    for backend in ("mflux-q4", None):
        assert seedgen.record_settings({"model": "qwen", "backend": backend}) == _settings("qwen2511-q4", [], 8, None)
    assert seedgen.record_settings({"model": "qwen", "backend": "diffusers-bf16"}) == _settings(
        "qwen2511-bf16", [], 8, None)
    zimage = {"qwen_model": None, "loras": [], "steps": None, "scheduler": None}
    assert seedgen.record_settings({"model": "zimage", "backend": "zimage"}) == zimage
    assert seedgen.record_settings({}) == zimage
    assert [seedgen.canvas_multiple("qwen", m) for m in seedgen.QWEN_MODEL_IDS] == [32, 32, 32, 16, 16]
    assert seedgen.canvas_multiple("zimage", None) == 16


def test_sqt16_the_registry_view():
    research = "Qwen Research License (non-commercial)"

    def model(model_id, label, family, backend, steps, scheduler, multiple, memory, license, setup):
        return {"id": model_id, "label": label, "family": family, "backend": backend, "steps": steps,
                "scheduler": scheduler, "multiple": multiple, "memory_gib": memory, "license": license,
                "setup": "bin/seed-edit-setup --model %s" % model_id if setup else None}

    assert seedgen.registry_view() == {
        "default_model": "qwen21-q4",
        "families": {"qwen21": "Qwen-Image-2.1", "qwen2511": "Qwen-Image-Edit-2511"},
        "models": [model("qwen21-q4", "Qwen-Image-2.1 q4", "qwen21", "mflux", 40, "linear", 32, 20.0, research, True),
                   model("qwen21-q8", "Qwen-Image-2.1 q8", "qwen21", "mflux", 40, "linear", 32, 32.0, research, True),
                   model("qwen21-bf16", "Qwen-Image-2.1 bf16", "qwen21", "mflux", 40, "linear", 32, 56.0, research,
                         True),
                   model("qwen2511-q4", "Qwen-Image-Edit-2511 q4 (Lightning)", "qwen2511", "mflux", 8, None, 16,
                         32.0, "Apache-2.0", True),
                   model("qwen2511-bf16", "Qwen-Image-Edit-2511 bf16 (Lightning, diffusers)", "qwen2511",
                         "diffusers", 8, None, 16, 64.0, "Apache-2.0", False)],
        "loras": [{"id": "uncensored", "label": "Uncensored (abenzerps)", "family": "qwen21", "default_on": True,
                   "default_scale": 1.0, "steps": None, "scheduler": None, "license": research,
                   "setup": "bin/seed-edit-setup --lora uncensored"},
                  {"id": "viggle-turbo", "label": "Viggle turbo 6-step", "family": "qwen21", "default_on": False,
                   "default_scale": 1.0, "steps": 6, "scheduler": "viggle_turbo", "license": research,
                   "setup": "bin/seed-edit-setup --lora viggle-turbo"}]}
    json.dumps(seedgen.registry_view())
    view = seedgen.registry_view()
    view["families"]["qwen21"] = "changed"
    assert seedgen.QWEN_FAMILIES["qwen21"] == "Qwen-Image-2.1"

```

**Edit 1.4** `tests/test_seed_edit_tool.py`: replace

```python
2026-11-02-seed-generator-design.md, Section 9: SGT1-SGT16, with the plan's Review Focus pins 3
and 4).

```

with

```python
2026-11-02-seed-generator-design.md, Section 9: SGT1-SGT16, with the plan's Review Focus pins 3
and 4), and the seed models registry in them (docs/superpowers/specs/2026-11-02-seed-models-
design.md, Section 9.2: SQT1-SQT14, with that plan's Review Focus pins 1, 3, 4 and 5).

```

**Edit 1.5** `tests/test_seed_edit_tool.py`: replace

```python

# --- Review Focus 3: prompts that look like shell or argparse input --------------------------------------
```

with

```python

# --- SQT10 (seed models SQ3, SQ4, SQ6): the registry pins -------------------------------------------------

RESEARCH = "Qwen Research License (non-commercial)"
LIGHTNING_PIN = {"repo": "lightx2v/Qwen-Image-Edit-2511-Lightning", "revision": "107d238d68b8387e32843d0b4a2e24ceb0d3ad86",
                 "file": "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors", "bytes": 849608296,
                 "scale": 1.0}
MFLUX_PATTERNS = ["model_index.json", "scheduler/*.json", "processor/**", "vae/*.json", "vae/*.safetensors",
                  "transformer/*.json", "transformer/*.safetensors", "text_encoder/*.json", "text_encoder/*.safetensors"]
C21 = "mflux.models.qwen21.variants.edit.qwen_image_21_edit.QwenImage21Edit"
C2511 = "mflux.models.qwen.variants.edit.qwen_image_edit.QwenImageEdit"
REGISTRY = [
    {"id": "qwen21-q4", "label": "Qwen-Image-2.1 q4", "family": "qwen21", "backend": "mflux",
     "repo": "mflux-community/qwen-image-2-1-mflux-q4", "revision": "b6c0fc76350650482d13aea89b316c28cd487f7f",
     "allow_patterns": None, "bytes": 10638928735, "quant": "q4", "mflux_class": C21, "mflux_config": "qwen_image_21",
     "steps": 40, "guidance": 1.0, "scheduler": "linear", "multiple": 32, "builtin_lora": None, "memory_gib": 20.0,
     "license": RESEARCH, "setup": True},
    {"id": "qwen21-q8", "label": "Qwen-Image-2.1 q8", "family": "qwen21", "backend": "mflux",
     "repo": "mflux-community/qwen-image-2-1-mflux-q8", "revision": "f5c8cc79a6741026a6057546012fba3b0a4b5b25",
     "allow_patterns": None, "bytes": 18460986297, "quant": "q8", "mflux_class": C21, "mflux_config": "qwen_image_21",
     "steps": 40, "guidance": 1.0, "scheduler": "linear", "multiple": 32, "builtin_lora": None, "memory_gib": 32.0,
     "license": RESEARCH, "setup": True},
    {"id": "qwen21-bf16", "label": "Qwen-Image-2.1 bf16", "family": "qwen21", "backend": "mflux",
     "repo": "Qwen/Qwen-Image-2.1", "revision": "d26bb61231c349cf6b7896fa83353113880e1ba3",
     "allow_patterns": MFLUX_PATTERNS, "bytes": 33131601593, "quant": "bf16", "mflux_class": C21,
     "mflux_config": "qwen_image_21", "steps": 40, "guidance": 1.0, "scheduler": "linear", "multiple": 32,
     "builtin_lora": None, "memory_gib": 56.0, "license": RESEARCH, "setup": True},
    {"id": "qwen2511-q4", "label": "Qwen-Image-Edit-2511 q4 (Lightning)", "family": "qwen2511", "backend": "mflux",
     "repo": "mflux-community/qwen-image-edit-2511-mflux-q4", "revision": "3c74aab7dd79e6a8148c329cbca78c00c049ec3b",
     "allow_patterns": None, "bytes": 28958989673, "quant": "q4", "mflux_class": C2511,
     "mflux_config": "qwen_image_edit_2511", "steps": 8, "guidance": 1.0, "scheduler": None, "multiple": 16,
     "builtin_lora": LIGHTNING_PIN, "memory_gib": 32.0, "license": "Apache-2.0", "setup": True},
    {"id": "qwen2511-bf16", "label": "Qwen-Image-Edit-2511 bf16 (Lightning, diffusers)", "family": "qwen2511",
     "backend": "diffusers", "repo": "Qwen/Qwen-Image-Edit-2511", "revision": None, "allow_patterns": None,
     "bytes": None, "quant": "bf16", "mflux_class": None, "mflux_config": None, "steps": 8, "guidance": 1.0,
     "scheduler": None, "multiple": 16, "builtin_lora": dict(LIGHTNING_PIN, revision=None), "memory_gib": 64.0,
     "license": "Apache-2.0", "setup": False},
]
LORA_REGISTRY = [
    {"id": "uncensored", "label": "Uncensored (abenzerps)", "family": "qwen21",
     "repo": "abenzerps/Qwen-Image-2.1-Uncensored-Quantized", "revision": "7959e658915f52274897fb573ffeda49de8dc16b",
     "file": "qwen-image-2.1-uncensored-lora.safetensors", "bytes": 33586704, "default_on": True,
     "default_scale": 1.0, "steps": None, "scheduler": None, "license": RESEARCH},
    {"id": "viggle-turbo", "label": "Viggle turbo 6-step", "family": "qwen21",
     "repo": "Viggle/Qwen-Image-2.1-viggle-turbo", "revision": "009a44a895ef85f7e643c80fdca9543795248867",
     "file": "Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors", "bytes": 679604800,
     "default_on": False, "default_scale": 1.0, "steps": 6, "scheduler": "viggle_turbo", "license": RESEARCH},
]


def test_sqt10_the_registry_pins():
    import character_dataset
    tool = load_tool()
    assert seedgen.QWEN_MODEL_IDS == ("qwen21-q4", "qwen21-q8", "qwen21-bf16", "qwen2511-q4", "qwen2511-bf16")
    assert seedgen.QWEN_LORA_IDS == ("uncensored", "viggle-turbo")
    assert [dict(m) for m in seedgen.QWEN_MODELS] == REGISTRY
    assert [dict(lora) for lora in seedgen.QWEN_LORAS] == LORA_REGISTRY
    assert (seedgen.DEFAULT_QWEN_MODEL, seedgen.LEGACY_QWEN_MODEL, seedgen.SCALE_MAX) == ("qwen21-q4", "qwen2511-q4", 2.0)
    assert seedgen.QWEN_FAMILIES == {"qwen21": "Qwen-Image-2.1", "qwen2511": "Qwen-Image-Edit-2511"}
    assert seedgen.QWEN21_PATTERNS == MFLUX_PATTERNS
    assert seedgen.QWEN21_REQUIRED == ("vae/config.json", "transformer/config.json", "text_encoder/config.json")
    for entry in seedgen.QWEN_MODELS + seedgen.QWEN_LORAS:
        assert entry["revision"] is None or re.fullmatch(r"[0-9a-f]{40}", entry["revision"]), entry["id"]
    assert all("allow_patterns" not in lora for lora in seedgen.QWEN_LORAS)
    for model_id in ("qwen2511-q4", "qwen2511-bf16"):
        entry = seedgen.qwen_model(model_id)
        assert entry["steps"] == tool.EDIT_STEPS
        assert (entry["builtin_lora"]["repo"], entry["builtin_lora"]["file"]) == (tool.EDIT_LORA_REPO, tool.EDIT_LORA_FILE)
    assert seedgen.qwen_model("qwen2511-bf16")["repo"] == tool.EDIT_MODEL
    assert seedgen.qwen_model("qwen2511-bf16")["memory_gib"] == character_dataset.EDIT_MIN_AVAIL_GIB
    assert [seedgen.default_loras(m) for m in seedgen.QWEN_MODEL_IDS] == [[{"id": "uncensored", "scale": 1.0}]] * 3 + [[]] * 2
    assert (seedgen.qwen_model("nope"), seedgen.qwen_lora("nope")) == (None, None)
    assert seedgen.registry_order([{"id": "viggle-turbo", "scale": 1}, {"id": "uncensored", "scale": 2}]) == [
        {"id": "uncensored", "scale": 2}, {"id": "viggle-turbo", "scale": 1}]


# --- Review Focus 3: prompts that look like shell or argparse input --------------------------------------
```

- [ ] **Step 2: Run the two seed test files; the new and re-baselined tests fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedmodels-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py 2>&1 | tail -1
```

Expected: `32 failed, 95 passed`. The failing tests are exactly: `test_sqt10_the_registry_pins`, `test_sgt17_validate_run_request_order_and_defaults`, `test_sqt15_the_qwen_request_rows` (26 cases), `test_sqt15_qwen_defaults_order_and_placement`, `test_sqt16_qwen_settings`, `test_sqt16_record_settings_and_the_canvas_multiple`, `test_sqt16_the_registry_view`.

- [ ] **Step 3: Implement.** Make these edits in order.

**Edit 1.6** `movie_ui_seedgen.py`: replace

```python
folder rule, the run ID, Keep's file names and the seed_edit capability shape
(docs/superpowers/specs/2026-11-02-seed-generator-design.md, deliverable G4, Section 5.1).

```

with

```python
folder rule, the run ID, Keep's file names and the seed_edit capability shape
(docs/superpowers/specs/2026-11-02-seed-generator-design.md, deliverable G4, Section 5.1), and the
fixed Qwen model and LoRA registry with its selection rules
(docs/superpowers/specs/2026-11-02-seed-models-design.md, Sections 2 and 5.1). bin/seed-edit and
bin/seed-edit-setup import the registry from here; the page gets it through the capability.

```

**Edit 1.7** `movie_ui_seedgen.py`: replace

```python
SOURCE_MSG = "source must be {upload_id}, {run, n} or {character, still}"

```

with

```python
SOURCE_MSG = "source must be {upload_id}, {run, n} or {character, still}"
QWEN_FAMILIES = {"qwen21": "Qwen-Image-2.1", "qwen2511": "Qwen-Image-Edit-2511"}
QWEN21_PATTERNS = ["model_index.json", "scheduler/*.json", "processor/**", "vae/*.json", "vae/*.safetensors",
                   "transformer/*.json", "transformer/*.safetensors", "text_encoder/*.json",
                   "text_encoder/*.safetensors"]          # mflux 0.24.0 QwenImage21WeightDefinition patterns
QWEN21_REQUIRED = ("vae/config.json", "transformer/config.json", "text_encoder/config.json")
QWEN_RESEARCH = "Qwen Research License (non-commercial)"
LIGHTNING = {"repo": "lightx2v/Qwen-Image-Edit-2511-Lightning",
             "revision": "107d238d68b8387e32843d0b4a2e24ceb0d3ad86",
             "file": "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors",
             "bytes": 849608296, "scale": 1.0}
QWEN21_CLASS = "mflux.models.qwen21.variants.edit.qwen_image_21_edit.QwenImage21Edit"
QWEN2511_CLASS = "mflux.models.qwen.variants.edit.qwen_image_edit.QwenImageEdit"
QWEN_MODELS = (
    {"id": "qwen21-q4", "label": "Qwen-Image-2.1 q4", "family": "qwen21", "backend": "mflux",
     "repo": "mflux-community/qwen-image-2-1-mflux-q4", "revision": "b6c0fc76350650482d13aea89b316c28cd487f7f",
     "allow_patterns": None, "bytes": 10638928735, "quant": "q4",
     "mflux_class": QWEN21_CLASS, "mflux_config": "qwen_image_21",
     "steps": 40, "guidance": 1.0, "scheduler": "linear", "multiple": 32, "builtin_lora": None,
     "memory_gib": 20.0, "license": QWEN_RESEARCH, "setup": True},
    {"id": "qwen21-q8", "label": "Qwen-Image-2.1 q8", "family": "qwen21", "backend": "mflux",
     "repo": "mflux-community/qwen-image-2-1-mflux-q8", "revision": "f5c8cc79a6741026a6057546012fba3b0a4b5b25",
     "allow_patterns": None, "bytes": 18460986297, "quant": "q8",
     "mflux_class": QWEN21_CLASS, "mflux_config": "qwen_image_21",
     "steps": 40, "guidance": 1.0, "scheduler": "linear", "multiple": 32, "builtin_lora": None,
     "memory_gib": 32.0, "license": QWEN_RESEARCH, "setup": True},
    {"id": "qwen21-bf16", "label": "Qwen-Image-2.1 bf16", "family": "qwen21", "backend": "mflux",
     "repo": "Qwen/Qwen-Image-2.1", "revision": "d26bb61231c349cf6b7896fa83353113880e1ba3",
     "allow_patterns": QWEN21_PATTERNS, "bytes": 33131601593, "quant": "bf16",
     "mflux_class": QWEN21_CLASS, "mflux_config": "qwen_image_21",
     "steps": 40, "guidance": 1.0, "scheduler": "linear", "multiple": 32, "builtin_lora": None,
     "memory_gib": 56.0, "license": QWEN_RESEARCH, "setup": True},
    {"id": "qwen2511-q4", "label": "Qwen-Image-Edit-2511 q4 (Lightning)", "family": "qwen2511", "backend": "mflux",
     "repo": "mflux-community/qwen-image-edit-2511-mflux-q4", "revision": "3c74aab7dd79e6a8148c329cbca78c00c049ec3b",
     "allow_patterns": None, "bytes": 28958989673, "quant": "q4",
     "mflux_class": QWEN2511_CLASS, "mflux_config": "qwen_image_edit_2511",
     "steps": 8, "guidance": 1.0, "scheduler": None, "multiple": 16, "builtin_lora": LIGHTNING,
     "memory_gib": 32.0, "license": "Apache-2.0", "setup": True},
    {"id": "qwen2511-bf16", "label": "Qwen-Image-Edit-2511 bf16 (Lightning, diffusers)", "family": "qwen2511",
     "backend": "diffusers", "repo": "Qwen/Qwen-Image-Edit-2511", "revision": None,
     "allow_patterns": None, "bytes": None, "quant": "bf16", "mflux_class": None, "mflux_config": None,
     "steps": 8, "guidance": 1.0, "scheduler": None, "multiple": 16, "builtin_lora": dict(LIGHTNING, revision=None),
     "memory_gib": 64.0, "license": "Apache-2.0", "setup": False},
)
QWEN_LORAS = (
    {"id": "uncensored", "label": "Uncensored (abenzerps)", "family": "qwen21",
     "repo": "abenzerps/Qwen-Image-2.1-Uncensored-Quantized", "revision": "7959e658915f52274897fb573ffeda49de8dc16b",
     "file": "qwen-image-2.1-uncensored-lora.safetensors", "bytes": 33586704,
     "default_on": True, "default_scale": 1.0, "steps": None, "scheduler": None, "license": QWEN_RESEARCH},
    {"id": "viggle-turbo", "label": "Viggle turbo 6-step", "family": "qwen21",
     "repo": "Viggle/Qwen-Image-2.1-viggle-turbo", "revision": "009a44a895ef85f7e643c80fdca9543795248867",
     "file": "Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors", "bytes": 679604800,
     "default_on": False, "default_scale": 1.0, "steps": 6, "scheduler": "viggle_turbo", "license": QWEN_RESEARCH},
)
QWEN_MODEL_IDS = tuple(m["id"] for m in QWEN_MODELS)
QWEN_LORA_IDS = tuple(l["id"] for l in QWEN_LORAS)
DEFAULT_QWEN_MODEL = "qwen21-q4"
LEGACY_QWEN_MODEL = "qwen2511-q4"
SCALE_MAX = 2.0
LORAS_MSG = "loras must be a list of {id, scale}"

```

**Edit 1.8** `movie_ui_seedgen.py`: replace

```python

def validate_run_request(body):
```

with

```python

def _qwen_fields(body, model):
    """Seed models SQ30 rows 9a-9i: (qwen_model, loras, None) cleaned, or (None, None, error)."""
    model_id, loras = body.get("qwen_model"), body.get("loras")
    if model == "zimage":
        if model_id is not None:
            return None, None, "qwen_model is only for qwen"
        if loras is not None:
            return None, None, "loras is only for qwen"
        return None, [], None
    if model_id is not None and not (isinstance(model_id, str) and model_id in QWEN_MODEL_IDS):
        return None, None, "unknown qwen_model %s" % (model_id,)
    if model_id is None:
        model_id = DEFAULT_QWEN_MODEL
    if loras is None:
        return model_id, default_loras(model_id), None
    if not isinstance(loras, list):
        return None, None, LORAS_MSG
    entry, seen, clean = qwen_model(model_id), set(), []
    for item in loras:
        if not (isinstance(item, dict) and set(item) == {"id", "scale"}):
            return None, None, LORAS_MSG
        lora_id, scale = item["id"], item["scale"]
        if not (isinstance(lora_id, str) and lora_id in QWEN_LORA_IDS):
            return None, None, "unknown LoRA %s" % (lora_id,)
        if lora_id in seen:
            return None, None, "LoRA %s is listed twice" % lora_id
        seen.add(lora_id)
        lora = qwen_lora(lora_id)
        if lora["family"] != entry["family"]:
            return None, None, "LoRA %s is for %s, not %s" % (lora_id, QWEN_FAMILIES[lora["family"]], entry["label"])
        if not (lib._is_number(scale) and 0 < scale <= SCALE_MAX):
            return None, None, "LoRA %s scale must be a number above 0 and at most 2" % lora_id
        clean.append({"id": lora_id, "scale": float(scale)})
    return model_id, registry_order(clean), None


def validate_run_request(body):
```

**Edit 1.9** `movie_ui_seedgen.py`: replace

```python
        return None, "seed must be an integer from 0 to 2147483647"
    source, error = _source(body.get("source"))
```

with

```python
        return None, "seed must be an integer from 0 to 2147483647"
    qwen_model_id, loras, error = _qwen_fields(body, model)
    if error is not None:
        return None, error
    source, error = _source(body.get("source"))
```

**Edit 1.10** `movie_ui_seedgen.py`: replace

```python
            "candidates": CANDIDATES_DEFAULT if candidates is None else candidates,
            "seed": seed, "source": source}, None

```

with

```python
            "candidates": CANDIDATES_DEFAULT if candidates is None else candidates,
            "seed": seed, "qwen_model": qwen_model_id, "loras": loras, "source": source}, None

```

**Edit 1.11** `movie_ui_seedgen.py`: replace

```python

def capability(models, detail, checked):
```

with

```python

def qwen_model(model_id):
    """Seed models SQ5: the QWEN_MODELS entry whose id is model_id, else None."""
    for entry in QWEN_MODELS:
        if entry["id"] == model_id:
            return entry
    return None


def qwen_lora(lora_id):
    """Seed models SQ5: the QWEN_LORAS entry whose id is lora_id, else None."""
    for entry in QWEN_LORAS:
        if entry["id"] == lora_id:
            return entry
    return None


def registry_order(loras):
    """Seed models SQ5: a [{"id", "scale"}] list sorted by each id's place in QWEN_LORA_IDS."""
    return sorted(loras, key=lambda item: QWEN_LORA_IDS.index(item["id"]))


def default_loras(model_id):
    """Seed models SQ6: the default-on LoRAs of model_id's family, [{"id", "scale"}]."""
    family = qwen_model(model_id)["family"]
    return [{"id": lora["id"], "scale": lora["default_scale"]} for lora in QWEN_LORAS
            if lora["default_on"] and lora["family"] == family]


def qwen_settings(model_id, loras):
    """Seed models SQ7: {"qwen_model", "loras", "steps", "scheduler"} of a selection (model_id None
    for Z-Image). A LoRA with its own steps (the first in registry order) sets steps and scheduler."""
    if model_id is None:
        return {"qwen_model": None, "loras": [], "steps": None, "scheduler": None}
    entry = qwen_model(model_id)
    steps, scheduler, turbo, out = entry["steps"], entry["scheduler"], None, []
    for item in registry_order(loras):
        lora = qwen_lora(item["id"])
        out.append({"id": lora["id"], "repo": lora["repo"], "file": lora["file"], "scale": float(item["scale"])})
        if turbo is None and lora["steps"] is not None:
            turbo = lora
    if turbo is not None:
        steps, scheduler = turbo["steps"], turbo["scheduler"]
    return {"qwen_model": {"id": entry["id"], "repo": entry["repo"]}, "loras": out, "steps": steps,
            "scheduler": scheduler}


def record_settings(record):
    """Seed models SQ8: the four qwen_settings keys of a run.json dict; a Qwen run made before the
    registry reads as qwen2511-bf16 when its backend was diffusers-bf16, else as qwen2511-q4."""
    if isinstance(record.get("qwen_model"), dict):
        loras = record.get("loras")
        return {"qwen_model": record["qwen_model"], "loras": loras if isinstance(loras, list) else [],
                "steps": record.get("steps"), "scheduler": record.get("scheduler")}
    if record.get("model") == "qwen":
        return qwen_settings("qwen2511-bf16" if record.get("backend") == "diffusers-bf16" else LEGACY_QWEN_MODEL, [])
    return qwen_settings(None, [])


def canvas_multiple(model, model_id):
    """Seed models SQ9: the edit canvas multiple: the registry model's for qwen, else 16."""
    return qwen_model(model_id)["multiple"] if model == "qwen" else 16


def registry_view():
    """Seed models SQ10: the page's copy of the registry (the seed_edit capability's "registry")."""
    models = [{"id": m["id"], "label": m["label"], "family": m["family"], "backend": m["backend"],
               "steps": m["steps"], "scheduler": m["scheduler"], "multiple": m["multiple"],
               "memory_gib": m["memory_gib"], "license": m["license"],
               "setup": "bin/seed-edit-setup --model %s" % m["id"] if m["setup"] else None} for m in QWEN_MODELS]
    loras = [{"id": lora["id"], "label": lora["label"], "family": lora["family"], "default_on": lora["default_on"],
              "default_scale": lora["default_scale"], "steps": lora["steps"], "scheduler": lora["scheduler"],
              "license": lora["license"], "setup": "bin/seed-edit-setup --lora %s" % lora["id"]} for lora in QWEN_LORAS]
    return {"default_model": DEFAULT_QWEN_MODEL, "families": dict(QWEN_FAMILIES), "models": models, "loras": loras}


def capability(models, detail, checked):
```

- [ ] **Step 4: Run the tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedmodels-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py 2>&1 | tail -1
```

Expected: `127 passed`. Run the compile check with `FILES` = `movie_ui_seedgen.py tests/test_movie_ui_seedgen.py tests/test_seed_edit_tool.py`; expected `compiled 3` twice. Then run the gate block ("Between tasks") with `N=1`. Expected: `GATE PASS`, `lost 0`, `new tests 127, not passing 0`, `baseline failures still failing 2 of 2`, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedmodels-wt/qwen-agent-workspace
git add movie_ui_seedgen.py tests/test_movie_ui_seedgen.py tests/test_seed_edit_tool.py
git diff --cached --name-only    # expected: exactly these 3 paths, with the qwen-agent-workspace/ prefix
git commit -m "feat(seed-models): the Qwen model and LoRA registry and its request rows in movie_ui_seedgen (SQ1, SQ3-SQ10, SQ30; SQT10, SQT15, SQT16)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The movie-ui side: probe shape, argv, capability, 409 texts, record, view and list (SQ31-SQ40; SQT16-SQT17, SQT19-SQT21, Review Focus 2)

This task implements:
- SQ3's `MODELS` label `Qwen-Image`; SQ32 `capability` with `registry` in both branches; SQ31 `availability_error(models, detail, clean)`.
- SQ34 `seed_edit_argv`'s `--qwen-model` and `--lora ID=SCALE` (`%r` of the float); SQ35 `_probe_qwen` (PR5) and `seed_edit_check(ws_real, model_ids, lora_ids)`.
- SQ33 the server's initial capability with `registry` and `refresh_capabilities`' IDs; SQ36 the create route's check, record (`**seedgen.qwen_settings(...)` after `seed`) and job fields; SQ37 `run_view` (PR14); SQ38 `_h_seed_runs`.
- Tests: SQT16's availability test, SQT17, SQT19, SQT20, SQT21, Review Focus 2; the helper `qwen_probe(models=None, loras=None)` builds probe answers in SQ18's shape and `OK_MODELS` becomes one; SGT17, SGT19, SGT22, SGT23, SGT26, SGT27 and SGT31 re-baselined (spec 9.3, PR2 (d), (e)).

**Files:**
- Modify: `movie_ui_seedgen.py` (`MODELS` `:23`; `capability` and `availability_error`, the module's last two functions)
- Modify: `movie_ui_lib.py` (`seed_edit_argv` `:1199-1208`; `_probe_qwen` after `_probe_model` `:1648-1655`; `seed_edit_check` `:1658-1677`)
- Modify: `movie_ui_server.py` (initial capability `:215`; `refresh_capabilities` `:227`; `run_view` `:1700`; `_h_seed_run_create` `:1742-1776`; `_h_seed_runs` `:1797-1800`)
- Modify: `tests/test_movie_ui_seedgen.py`

**Interfaces:**
- Consumes:
  - Task 1: `seedgen.qwen_model`, `seedgen.qwen_lora`, `seedgen.registry_view()`, `seedgen.qwen_settings`, `seedgen.record_settings`, `QWEN_MODEL_IDS`, `QWEN_LORA_IDS`, `clean["qwen_model"]`, `clean["loras"]`, the test helper `QWEN_REQUEST_CASES`.
- Produces:
  - `seedgen.capability(models, detail, checked) -> {"ok", "reason", "checked", "models", "registry"}`; `seedgen.availability_error(models, detail, clean) -> str or None`.
  - `lib.seed_edit_argv(fields, ws_real, py=sys.executable)` (a qwen job's fields carry `qwen_model` and `loras`); `lib.seed_edit_check(ws_real, model_ids, lora_ids) -> (models, None) or (None, detail)` with `models = {"zimage": {"ok", "reason", "backend"}, "qwen": {"ok", "reason", "models": {id: {"ok", "reason"}}, "loras": {id: {"ok", "reason"}}}}`.
  - The `seed_edit` capability always has `registry` (the page's Task 6 reads it); a run view has `qwen_model`, `loras`, `steps`, `scheduler`; a runs-list item has `qwen_model`, `loras`.
  - Test helpers in `tests/test_movie_ui_seedgen.py`: `qwen_probe(models=None, loras=None)`, `ALL_MODELS_OFF`, `ZCLEAN`, `OK_MODELS` (SQ18 shape), `IDS`, `LIDS`, `NO_QWEN`.

- [ ] **Step 1: Write the failing tests.** Make these edits in order (Edit tool; each old text occurs exactly once at its turn).

**Edit 2.1** `tests/test_movie_ui_seedgen.py`: replace

```python

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

```

with

```python

def qwen_probe(models=None, loras=None):
    """A probe qwen entry in seed models SQ18's shape: every model and LoRA ok except the IDs that
    models and loras map to their reasons; ok and reason follow SQ18's aggregate rule."""
    models, loras = models or {}, loras or {}
    per_model = dict((i, {"ok": i not in models, "reason": models.get(i)}) for i in seedgen.QWEN_MODEL_IDS)
    per_lora = dict((i, {"ok": i not in loras, "reason": loras.get(i)}) for i in seedgen.QWEN_LORA_IDS)
    ok = any(e["ok"] for e in per_model.values())
    reason = None if ok else "; ".join("%s: %s" % (i, per_model[i]["reason"]) for i in seedgen.QWEN_MODEL_IDS)
    return {"ok": ok, "reason": reason, "models": per_model, "loras": per_lora}


ALL_MODELS_OFF = dict((i, "%s is missing" % i) for i in seedgen.QWEN_MODEL_IDS)
ZCLEAN = {"model": "zimage", "qwen_model": None, "loras": []}


def test_sgt17_capability_and_availability():
    ok_z = {"ok": True, "reason": None, "backend": "zimage"}
    no_z = {"ok": False, "reason": "torch not importable by /py", "backend": None}
    ok_q = qwen_probe()
    no_q = qwen_probe(models=ALL_MODELS_OFF)
    registry = seedgen.registry_view()
    both = {"zimage": ok_z, "qwen": ok_q}
    assert seedgen.capability(both, None, "T") == {"ok": True, "reason": None, "checked": "T", "models": both,
                                                   "registry": registry}
    partial = {"zimage": ok_z, "qwen": no_q}
    assert seedgen.capability(partial, None, "T") == {"ok": True, "reason": None, "checked": "T", "models": partial,
                                                      "registry": registry}
    none_ok = {"zimage": no_z, "qwen": no_q}
    assert seedgen.capability(none_ok, None, "T") == {
        "ok": False, "reason": "Z-Image: torch not importable by /py; Qwen-Image: " + no_q["reason"],
        "checked": "T", "models": none_ok, "registry": registry}
    assert seedgen.capability(None, "bin/seed-edit --probe exited 1: boom", "T") == {
        "ok": False, "reason": "bin/seed-edit --probe exited 1: boom", "checked": "T", "models": None,
        "registry": registry}
    assert seedgen.MODELS == {"zimage": "Z-Image", "qwen": "Qwen-Image"}
    assert seedgen.availability_error(partial, None, ZCLEAN) is None
    assert seedgen.availability_error(none_ok, None, ZCLEAN) == "Z-Image is unavailable: torch not importable by /py"
    assert seedgen.availability_error(None, "boom", ZCLEAN) == "cannot check the seed models: boom"


# --- SQT16 (seed models SQ31): the 409 texts for a Qwen selection ------------------------------------

def test_sqt16_availability_of_a_qwen_selection():
    ok_z = {"ok": True, "reason": None, "backend": "zimage"}

    def clean(model_id, *lora_ids):
        return {"model": "qwen", "qwen_model": model_id, "loras": [{"id": i, "scale": 1.0} for i in lora_ids]}

    every = {"zimage": ok_z, "qwen": qwen_probe()}
    assert seedgen.availability_error(every, None, clean("qwen21-q4", "uncensored", "viggle-turbo")) is None
    q8_off = {"zimage": ok_z, "qwen": qwen_probe(models={"qwen21-q8": "not installed (run x)"})}
    assert seedgen.availability_error(q8_off, None, clean("qwen21-q8")) == (
        "Qwen-Image-2.1 q8 is unavailable: not installed (run x)")
    assert seedgen.availability_error(q8_off, None, clean("qwen21-q4", "uncensored")) is None
    loras_off = {"zimage": ok_z, "qwen": qwen_probe(loras={"uncensored": "u missing", "viggle-turbo": "v missing"})}
    assert seedgen.availability_error(loras_off, None, clean("qwen21-q4", "uncensored", "viggle-turbo")) == (
        "LoRA Uncensored (abenzerps) is unavailable: u missing")
    assert seedgen.availability_error(loras_off, None, clean("qwen21-q4", "viggle-turbo")) == (
        "LoRA Viggle turbo 6-step is unavailable: v missing")
    assert seedgen.availability_error(loras_off, None, clean("qwen21-q4")) is None
    both_off = {"zimage": ok_z, "qwen": qwen_probe(models={"qwen21-bf16": "needs 56 GiB"}, loras={"uncensored": "u"})}
    assert seedgen.availability_error(both_off, None, clean("qwen21-bf16", "uncensored")) == (
        "Qwen-Image-2.1 bf16 is unavailable: needs 56 GiB")
    aggregate_off = {"zimage": ok_z, "qwen": dict(qwen_probe(), ok=False, reason="x")}
    assert seedgen.availability_error(aggregate_off, None, clean("qwen2511-q4")) is None
    zimage_off = {"zimage": dict(ok_z, ok=False, reason="z"), "qwen": qwen_probe()}
    assert seedgen.availability_error(zimage_off, None, clean("qwen2511-bf16")) is None
    assert seedgen.availability_error(None, "boom", clean("qwen21-q4")) == "cannot check the seed models: boom"

```

**Edit 2.2** `tests/test_movie_ui_seedgen.py`: replace

```python

OK_MODELS = {"zimage": {"ok": True, "reason": None, "backend": "zimage"},
             "qwen": {"ok": True, "reason": None, "backend": "mflux-q4"}}

```

with

```python

OK_MODELS = {"zimage": {"ok": True, "reason": None, "backend": "zimage"}, "qwen": qwen_probe()}
IDS, LIDS = seedgen.QWEN_MODEL_IDS, seedgen.QWEN_LORA_IDS

```

**Edit 2.3** `tests/test_movie_ui_seedgen.py`: replace

```python
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
```

with

```python
    stub_seed_edit(ws, OK_MODELS)
    assert lib.seed_edit_check(ws, IDS, LIDS) == (OK_MODELS, None)
    extra = {"zimage": dict(OK_MODELS["zimage"], note=1), "qwen": OK_MODELS["qwen"], "other": 1}
    stub_seed_edit(ws, extra)
    assert lib.seed_edit_check(ws, IDS, LIDS) == (OK_MODELS, None)
    stub_seed_edit(ws, OK_MODELS, exit=3, stderr="first\nnope\n")
    assert lib.seed_edit_check(ws, IDS, LIDS) == (None, "bin/seed-edit --probe exited 3: nope")
    stub_seed_edit(ws, OK_MODELS, exit=3)
    assert lib.seed_edit_check(ws, IDS, LIDS) == (None, "bin/seed-edit --probe exited 3: -")
    bad = [
```

**Edit 2.4** `tests/test_movie_ui_seedgen.py`: replace

```python
        json.dumps({"zimage": dict(OK_MODELS["zimage"], reason=5), "qwen": OK_MODELS["qwen"]}),
        json.dumps({"zimage": OK_MODELS["zimage"], "qwen": dict(OK_MODELS["qwen"], backend=["x"])}),
    ]
    for printed in bad:
        stub_seed_edit(ws, printed)
        assert lib.seed_edit_check(ws) == (None, "bin/seed-edit --probe printed unparsable output"), printed
    monkeypatch.setattr(lib, "LIGHT_TIMEOUT", 1)
    stub_seed_edit(ws, OK_MODELS, sleep=2)
    assert lib.seed_edit_check(ws) == (None, "bin/seed-edit --probe timed out after 1 s")


# --- The HTTP tests: fixture and helpers (spec 9 rules) -----------------------------------------------

TIME_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
VIEW_KEYS = {"run", "dir", "created", "state", "prompt", "model", "backend", "strength", "seed", "size",
             "source_size", "source_origin", "error", "source", "candidates", "job"}
RA, RB = "se-20261101-100000-000a", "se-20261101-100000-000b"
```

with

```python
        json.dumps({"zimage": dict(OK_MODELS["zimage"], reason=5), "qwen": OK_MODELS["qwen"]}),
        json.dumps({"zimage": OK_MODELS["zimage"], "qwen": dict(OK_MODELS["qwen"], reason=["x"])}),
    ]
    for printed in bad:
        stub_seed_edit(ws, printed)
        assert lib.seed_edit_check(ws, IDS, LIDS) == (None, "bin/seed-edit --probe printed unparsable output"), printed
    monkeypatch.setattr(lib, "LIGHT_TIMEOUT", 1)
    stub_seed_edit(ws, OK_MODELS, sleep=2)
    assert lib.seed_edit_check(ws, IDS, LIDS) == (None, "bin/seed-edit --probe timed out after 1 s")


# --- SQT17 (seed models SQ34, SQ35): the qwen argv and the probe's new shape ----------------------------

def test_sqt17_qwen_argv_and_probe_shape(monkeypatch, tmp_path):
    mt.set_home(monkeypatch, tmp_path)
    clean_env(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    run_dir = os.path.join(ws, "generated", "seeds", "runs", RUN)
    fields = {"ws": ws, "run": RUN, "source_file": "source.png", "prompt": "make it night", "model": "qwen",
              "strength": None, "qwen_model": "qwen21-q4",
              "loras": [{"id": "uncensored", "scale": 1.0}, {"id": "viggle-turbo", "scale": 0.5}],
              "candidates": 4, "seed": 7, "source": {"kind": "upload", "upload_id": UP}}
    assert lib.seed_edit_argv(fields, ws, py="/py") == [
        "/py", os.path.join(ws, "bin", "seed-edit"), "--source", os.path.join(run_dir, "source.png"),
        "--prompt", "make it night", "--model", "qwen", "--qwen-model", "qwen21-q4", "--lora", "uncensored=1.0",
        "--lora", "viggle-turbo=0.5", "--candidates", "4", "--seed", "7", "--run-dir", run_dir]
    plain = dict(fields, qwen_model="qwen2511-q4", loras=[])
    assert lib.seed_edit_argv(plain, ws, py="/py")[6:11] == ["--model", "qwen", "--qwen-model", "qwen2511-q4",
                                                             "--candidates"]
    legacy = dict(fields)
    del legacy["qwen_model"], legacy["loras"]
    assert lib.seed_edit_argv(legacy, ws, py="/py") == [
        "/py", os.path.join(ws, "bin", "seed-edit"), "--source", os.path.join(run_dir, "source.png"),
        "--prompt", "make it night", "--model", "qwen", "--candidates", "4", "--seed", "7", "--run-dir", run_dir]
    zimage = dict(fields, model="zimage", strength=0.3, qwen_model=None, loras=[])
    assert "--qwen-model" not in lib.seed_edit_argv(zimage, ws) and "--lora" not in lib.seed_edit_argv(zimage, ws)
    qwen = qwen_probe(models={"qwen21-q8": "q8 missing"}, loras={"viggle-turbo": "v missing"})
    noisy = dict(qwen, backend="mflux", models=dict((i, dict(e, extra=1)) for i, e in qwen["models"].items()))
    stub_seed_edit(ws, {"zimage": OK_MODELS["zimage"], "qwen": noisy})
    assert lib.seed_edit_check(ws, IDS, LIDS) == ({"zimage": OK_MODELS["zimage"], "qwen": qwen}, None)
    models = dict(qwen["models"])
    del models["qwen21-q8"]
    loras = dict(qwen["loras"], extra={"ok": True, "reason": None})
    no_loras = dict(qwen)
    del no_loras["loras"]
    bad_ok = dict(qwen, models=dict(qwen["models"], **{"qwen21-q4": {"ok": "yes", "reason": None}}))
    bad_reason = dict(qwen, loras=dict(qwen["loras"], uncensored={"ok": False, "reason": 5}))
    no_reason = dict(qwen, models=dict(qwen["models"], **{"qwen21-q4": {"ok": True}}))
    for printed in (dict(qwen, models=models), dict(qwen, loras=loras), bad_ok, no_loras, bad_reason, no_reason,
                    dict(qwen, models=[]), dict(qwen, ok=None)):
        stub_seed_edit(ws, {"zimage": OK_MODELS["zimage"], "qwen": printed})
        assert lib.seed_edit_check(ws, IDS, LIDS) == (None, "bin/seed-edit --probe printed unparsable output"), printed


# --- The HTTP tests: fixture and helpers (spec 9 rules) -----------------------------------------------

TIME_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
VIEW_KEYS = {"run", "dir", "created", "state", "prompt", "model", "backend", "strength", "seed", "size",
             "source_size", "source_origin", "error", "source", "candidates", "job",
             "qwen_model", "loras", "steps", "scheduler"}
NO_QWEN = {"qwen_model": None, "loras": [], "steps": None, "scheduler": None}
RA, RB = "se-20261101-100000-000a", "se-20261101-100000-000b"
```

**Edit 2.5** `tests/test_movie_ui_seedgen.py`: replace

```python
    up = _upload(s)
    reason = "diffusers bf16: needs a host with at least 64 GiB of memory (this host has 48.0 GiB); mflux q4: x"
    stub_seed_edit(ws, dict(OK_MODELS, qwen={"ok": False, "reason": reason, "backend": None}))
    assert _create(s, _body(ws, {"upload_id": up}, model="qwen", strength=None))[::2] == (
        409, {"error": "Qwen-Image-Edit is unavailable: " + reason})
    stub_seed_edit(ws, dict(OK_MODELS, zimage={"ok": False, "reason": "torch not importable by /py", "backend": None}))
```

with

```python
    up = _upload(s)
    reason = "needs a host with at least 20 GiB of memory (this host has 16.0 GiB)"
    stub_seed_edit(ws, dict(OK_MODELS, qwen=qwen_probe(models={"qwen21-q4": reason})))
    assert _create(s, _body(ws, {"upload_id": up}, model="qwen", strength=None))[::2] == (
        409, {"error": "Qwen-Image-2.1 q4 is unavailable: " + reason})
    stub_seed_edit(ws, dict(OK_MODELS, zimage={"ok": False, "reason": "torch not importable by /py", "backend": None}))
```

**Edit 2.6** `tests/test_movie_ui_seedgen.py`: replace

```python
        "candidates": [{"n": 1, "seed": 8, "status": "pending", "seconds": None},
                       {"n": 2, "seed": 9, "status": "pending", "seconds": None}]}
    job = lib.read_job(lib.job_dir(state, job_id))
    assert (job["kind"], job["story_id"], job["character"], job["vlm"]) == ("seed-edit", None, None, "forbidden")
    assert job["fields"] == {"ws": ws, "run": run, "source_file": "source.png", "prompt": "make it night",
                             "model": "zimage", "strength": 0.45, "candidates": 2, "seed": 7,
                             "source": {"kind": "upload", "upload_id": up}}
    assert job["argv"] == lib.seed_edit_argv(job["fields"], ws)
```

with

```python
        "candidates": [{"n": 1, "seed": 8, "status": "pending", "seconds": None},
                       {"n": 2, "seed": 9, "status": "pending", "seconds": None}], **NO_QWEN}
    job = lib.read_job(lib.job_dir(state, job_id))
    assert (job["kind"], job["story_id"], job["character"], job["vlm"]) == ("seed-edit", None, None, "forbidden")
    assert job["fields"] == {"ws": ws, "run": run, "source_file": "source.png", "prompt": "make it night",
                             "model": "zimage", "strength": 0.45, "qwen_model": None, "loras": [], "candidates": 2,
                             "seed": 7, "source": {"kind": "upload", "upload_id": up}}
    assert job["argv"] == lib.seed_edit_argv(job["fields"], ws)
```

**Edit 2.7** `tests/test_movie_ui_seedgen.py`: replace

```python
    assert [r["run"] for r in runs] == [r3, r2, r1]
    assert all(set(r) == {"run", "created", "state", "prompt", "model", "backend", "count", "ok", "thumbs"}
               for r in runs)
    assert [(r["state"], r["prompt"], r["count"], r["ok"], r["thumbs"]) for r in runs[:2]] == [
        ("unknown", "third", 1, 0, []), ("queued", "second", 2, 0, [])]
    assert runs[2] == {"run": r1, "created": "2026-11-02T14:15:00Z", "state": "done", "prompt": "make it night",
                       "model": "zimage", "backend": "zimage", "count": 3, "ok": 2,
                       "thumbs": [os.path.join(d1, "cand_01.png")]}
```

with

```python
    assert [r["run"] for r in runs] == [r3, r2, r1]
    assert all(set(r) == {"run", "created", "state", "prompt", "model", "backend", "qwen_model", "loras", "count",
                          "ok", "thumbs"} for r in runs)
    assert [(r["state"], r["prompt"], r["count"], r["ok"], r["thumbs"]) for r in runs[:2]] == [
        ("unknown", "third", 1, 0, []), ("queued", "second", 2, 0, [])]
    assert runs[2] == {"run": r1, "created": "2026-11-02T14:15:00Z", "state": "done", "prompt": "make it night",
                       "model": "zimage", "backend": "zimage", "qwen_model": None, "loras": [], "count": 3, "ok": 2,
                       "thumbs": [os.path.join(d1, "cand_01.png")]}
```

**Edit 2.8** `tests/test_movie_ui_seedgen.py`: replace

```python
                       {"n": 4, "seed": 11, "status": "failed", "seconds": None, "path": None}],
        "job": None}
    job_id = seed_job(state, ws, RB)
```

with

```python
                       {"n": 4, "seed": 11, "status": "failed", "seconds": None, "path": None}],
        "job": None, **NO_QWEN}
    job_id = seed_job(state, ws, RB)
```

**Edit 2.9** `tests/test_movie_ui_seedgen.py`: replace

```python
    server = s.server
    assert mt.api(s, "GET", "/api/host")[2]["capabilities"]["seed_edit"] == {
        "ok": None, "reason": "probing", "checked": None, "models": None}
    server.probe_ws = ws
```

with

```python
    server = s.server
    registry = seedgen.registry_view()
    assert mt.api(s, "GET", "/api/host")[2]["capabilities"]["seed_edit"] == {
        "ok": None, "reason": "probing", "checked": None, "models": None, "registry": registry}
    server.probe_ws = ws
```

**Edit 2.10** `tests/test_movie_ui_seedgen.py`: replace

```python
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

```

with

```python
    assert TIME_RE.fullmatch(checked)
    assert caps["seed_edit"] == {"ok": True, "reason": None, "checked": checked, "models": OK_MODELS,
                                 "registry": registry}
    assert all(set(caps[key]) == {"ok", "reason", "checked"} for key in ("render", "stills", "story_server"))
    none_ok = {"zimage": {"ok": False, "reason": "z", "backend": None},
               "qwen": dict(qwen_probe(models=ALL_MODELS_OFF), reason="q")}
    stub_seed_edit(ws, none_ok)
    caps = mt.api(s, "GET", "/api/host?refresh=1")[2]["capabilities"]
    assert dict(caps["seed_edit"], checked=None) == {"ok": False, "reason": "Z-Image: z; Qwen-Image: q",
                                                     "checked": None, "models": none_ok, "registry": registry}
    stub_seed_edit(ws, OK_MODELS, exit=1, stderr="boom\n")
    caps = mt.api(s, "GET", "/api/host?refresh=1")[2]["capabilities"]
    assert dict(caps["seed_edit"], checked=None) == {"ok": False, "reason": "bin/seed-edit --probe exited 1: boom",
                                                     "checked": None, "models": None, "registry": registry}

```

**Edit 2.11** `tests/test_movie_ui_seedgen.py`: replace

```python
    assert [(j["kind"], j["seed_run"]) for j in queued] == [("seed-edit", data["run"]["run"]), ("movie", None)]

```

with

```python
    assert [(j["kind"], j["seed_run"]) for j in queued] == [("seed-edit", data["run"]["run"]), ("movie", None)]


# --- SQT19 (seed models SQ36, SQ39): a Qwen run over HTTP; every new 400 and 409 creates nothing ------------

def test_sqt19_a_qwen_run_and_its_refusals(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    up = _upload(s)
    body = _body(ws, {"upload_id": up}, model="qwen", strength=None, qwen_model="qwen21-q4",
                 loras=[{"id": "uncensored", "scale": 0.5}])
    for case, message in QWEN_REQUEST_CASES:
        assert _create(s, dict(case, ws=ws, source={"upload_id": up}))[::2] == (400, {"error": message}), message
    q8 = ("mflux-community/qwen-image-2-1-mflux-q8@f5c8cc79a674 is not in /z or /h "
          "(run bin/seed-edit-setup --model qwen21-q8)")
    stub_seed_edit(ws, dict(OK_MODELS, qwen=qwen_probe(models={"qwen21-q8": q8})))
    assert _create(s, dict(body, qwen_model="qwen21-q8"))[::2] == (
        409, {"error": "Qwen-Image-2.1 q8 is unavailable: " + q8})
    vig = ("Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors is not in /z or /h "
           "(run bin/seed-edit-setup --lora viggle-turbo)")
    stub_seed_edit(ws, dict(OK_MODELS, qwen=qwen_probe(loras={"viggle-turbo": vig})))
    assert _create(s, dict(body, loras=[{"id": "viggle-turbo", "scale": 1}]))[::2] == (
        409, {"error": "LoRA Viggle turbo 6-step is unavailable: " + vig})
    assert _nothing_created(env)
    status, _h, data = _create(s, body)
    assert status == 201, data
    record = _record(data["run"]["dir"])
    assert {k: record[k] for k in NO_QWEN} == {
        "qwen_model": {"id": "qwen21-q4", "repo": "mflux-community/qwen-image-2-1-mflux-q4"},
        "loras": [{"id": "uncensored", "repo": "abenzerps/Qwen-Image-2.1-Uncensored-Quantized",
                   "file": "qwen-image-2.1-uncensored-lora.safetensors", "scale": 0.5}],
        "steps": 40, "scheduler": "linear"}
    assert {k: data["run"][k] for k in NO_QWEN} == {k: record[k] for k in NO_QWEN}
    job = lib.read_job(lib.job_dir(state, data["run"]["job"]["id"]))
    assert (job["fields"]["qwen_model"], job["fields"]["loras"]) == ("qwen21-q4", [{"id": "uncensored", "scale": 0.5}])
    argv = job["argv"]
    assert argv == lib.seed_edit_argv(job["fields"], ws)
    i = argv.index("--qwen-model")
    assert argv[i:i + 4] == ["--qwen-model", "qwen21-q4", "--lora", "uncensored=0.5"]


# --- SQT20 (seed models SQ37, SQ38): the run view and the runs list carry the selection ---------------------

def test_sqt20_the_view_and_the_list_carry_the_selection(env):
    s, ws = env["srv"], env["ws"]
    legacy = make_run(ws, RA, ["ok"])
    record = dict(_record(legacy), model="qwen", backend="mflux-q4", strength=None)
    with open(os.path.join(legacy, "run.json"), "w", encoding="utf-8") as f:
        json.dump(record, f)
    view = mt.api(s, "GET", "/api/seeds/runs/%s?ws=%s" % (RA, ws))[2]
    assert set(view) == VIEW_KEYS
    assert {k: view[k] for k in NO_QWEN} == {
        "qwen_model": {"id": "qwen2511-q4", "repo": "mflux-community/qwen-image-edit-2511-mflux-q4"}, "loras": [],
        "steps": 8, "scheduler": None}
    newer = make_run(ws, RB, ["ok"])
    settings = seedgen.qwen_settings("qwen21-q4", [{"id": "viggle-turbo", "scale": 1.0}])
    record = dict(_record(newer), model="qwen", backend="mflux", strength=None, **settings)
    with open(os.path.join(newer, "run.json"), "w", encoding="utf-8") as f:
        json.dump(record, f)
    view = mt.api(s, "GET", "/api/seeds/runs/%s?ws=%s" % (RB, ws))[2]
    assert {k: view[k] for k in NO_QWEN} == settings and settings["steps"] == 6
    runs = mt.api(s, "GET", "/api/seeds/runs?ws=" + ws)[2]["runs"]
    assert [(r["run"], r["qwen_model"], r["loras"]) for r in runs] == [
        (RB, settings["qwen_model"], settings["loras"]),
        (RA, {"id": "qwen2511-q4", "repo": "mflux-community/qwen-image-edit-2511-mflux-q4"}, [])]
    assert all("steps" not in r for r in runs)


# --- SQT21 (seed models SQ33): the capability carries the registry from the start ----------------------------

def test_sqt21_the_capability_carries_the_registry(env):
    s, ws = env["srv"], env["ws"]
    server = s.server
    assert server.capabilities["seed_edit"] == {"ok": None, "reason": "probing", "checked": None, "models": None,
                                                "registry": seedgen.registry_view()}
    server.probe_ws = ws
    env["mp"].setenv("LTX2_MLX_BIN", os.path.join(env["tmp"], "missing-ltx"))
    seed_edit = mt.api(s, "GET", "/api/host?refresh=1")[2]["capabilities"]["seed_edit"]
    assert (seed_edit["models"], seed_edit["registry"]) == (OK_MODELS, seedgen.registry_view())


# --- Review Focus 2: an old page tab (or a script) posts a Qwen run without qwen_model or loras ---------------

def test_sq_review_focus_2_a_qwen_request_without_the_new_fields(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    up = _upload(s)
    old_page = _body(ws, {"upload_id": up}, model="qwen", strength=None)
    unc = "qwen-image-2.1-uncensored-lora.safetensors is not in /z or /h (run bin/seed-edit-setup --lora uncensored)"
    stub_seed_edit(ws, dict(OK_MODELS, qwen=qwen_probe(loras={"uncensored": unc})))
    assert _create(s, old_page)[::2] == (409, {"error": "LoRA Uncensored (abenzerps) is unavailable: " + unc})
    assert _nothing_created(env)
    stub_seed_edit(ws, OK_MODELS)
    status, _h, data = _create(s, old_page)
    assert status == 201, data
    job = lib.read_job(lib.job_dir(state, data["run"]["job"]["id"]))
    assert (job["fields"]["qwen_model"], job["fields"]["loras"]) == ("qwen21-q4", [{"id": "uncensored", "scale": 1.0}])
    assert job["argv"][job["argv"].index("--qwen-model"):][:4] == ["--qwen-model", "qwen21-q4", "--lora", "uncensored=1.0"]
    assert (data["run"]["steps"], data["run"]["scheduler"]) == (40, "linear")

```

- [ ] **Step 2: Run the two seed test files; the new and re-baselined tests fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedmodels-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py 2>&1 | tail -1
```

Expected: `17 failed, 116 passed`. The failing tests are exactly: `test_sgt17_capability_and_availability`, `test_sqt16_availability_of_a_qwen_selection`, `test_sgt19_seed_edit_check`, `test_sqt17_qwen_argv_and_probe_shape`, `test_sgt22_conflicts_get_409_and_create_nothing`, `test_sgt23_queue_a_run_from_an_upload`, `test_sgt24_a_candidate_as_the_source`, `test_sgt25_a_character_still_as_the_source`, `test_sgt26_the_runs_list`, `test_sgt27_the_run_view`, `test_sgt31_the_seed_edit_capability`, `test_sgt32_the_job_summary_key`, `test_sqt19_a_qwen_run_and_its_refusals`, `test_sqt20_the_view_and_the_list_carry_the_selection`, `test_sqt21_the_capability_carries_the_registry`, `test_sq_review_focus_2_a_qwen_request_without_the_new_fields`, `test_sg_review_focus_1_jpeg_and_webp_sources_keep_their_extension`.

- [ ] **Step 3: Implement.** Make these edits in order.

**Edit 2.12** `movie_ui_lib.py`: replace

```python
def seed_edit_argv(fields, ws_real, py=sys.executable):
    """The bin/seed-edit argv of a seed-edit job (seed generator spec SG29)."""
    run_dir = os.path.join(ws_real, "generated", "seeds", "runs", fields["run"])
    argv = [py, os.path.join(ws_real, "bin", "seed-edit"),
            "--source", os.path.join(run_dir, fields["source_file"]),
            "--prompt", fields["prompt"], "--model", fields["model"]]
    if fields["model"] == "zimage":
```

with

```python
def seed_edit_argv(fields, ws_real, py=sys.executable):
    """The bin/seed-edit argv of a seed-edit job (seed generator spec SG29; seed models SQ34: a qwen
    job's --qwen-model and one --lora ID=SCALE per LoRA, in the fields' (registry) order). Fields
    without qwen_model (a job queued before the registry) give SG29's argv."""
    run_dir = os.path.join(ws_real, "generated", "seeds", "runs", fields["run"])
    argv = [py, os.path.join(ws_real, "bin", "seed-edit"),
            "--source", os.path.join(run_dir, fields["source_file"]),
            "--prompt", fields["prompt"], "--model", fields["model"]]
    if fields["model"] == "qwen" and fields.get("qwen_model") is not None:
        argv += ["--qwen-model", fields["qwen_model"]]
        for lora in fields["loras"]:
            argv += ["--lora", "%s=%r" % (lora["id"], float(lora["scale"]))]
    if fields["model"] == "zimage":
```

**Edit 2.13** `movie_ui_lib.py`: replace

```python

def seed_edit_check(ws_real):
    """(models, None) from <ws>/bin/seed-edit --probe, or (None, detail) (seed generator SG30)."""
    run = run_light(tool_argv(ws_real, "seed-edit", "--probe"), ws_real)
```

with

```python

def _probe_qwen(value, model_ids, lora_ids):
    """The qwen entry of bin/seed-edit --probe's output (seed models SQ35): {"ok", "reason", "models",
    "loras"} with exactly those keys, models and loras keyed by exactly model_ids and lora_ids and each
    entry {"ok", "reason"}; extra keys are dropped. None when the shape is wrong."""
    def entry(item):
        if not (isinstance(item, dict) and isinstance(item.get("ok"), bool) and "reason" in item
                and (item["reason"] is None or isinstance(item["reason"], str))):
            return None
        return {"ok": item["ok"], "reason": item["reason"]}

    top = entry(value)
    if top is None:
        return None
    for key, ids in (("models", model_ids), ("loras", lora_ids)):
        found = value.get(key)
        if not (isinstance(found, dict) and set(found) == set(ids)):
            return None
        parsed = dict((i, entry(found[i])) for i in ids)
        if None in parsed.values():
            return None
        top[key] = parsed
    return top


def seed_edit_check(ws_real, model_ids, lora_ids):
    """(models, None) from <ws>/bin/seed-edit --probe, or (None, detail) (seed generator SG30; seed
    models SQ35: the qwen entry carries one {"ok", "reason"} per registry model and LoRA)."""
    run = run_light(tool_argv(ws_real, "seed-edit", "--probe"), ws_real)
```

**Edit 2.14** `movie_ui_lib.py`: replace

```python
    if isinstance(data, dict):
        models = dict((key, _probe_model(data.get(key))) for key in ("zimage", "qwen"))
        if None in models.values():
```

with

```python
    if isinstance(data, dict):
        models = {"zimage": _probe_model(data.get("zimage")),
                  "qwen": _probe_qwen(data.get("qwen"), model_ids, lora_ids)}
        if None in models.values():
```

**Edit 2.15** `movie_ui_seedgen.py`: replace

```python
RUNS_MAX = 200
MODELS = {"zimage": "Z-Image", "qwen": "Qwen-Image-Edit"}
RUN_ID_RE = re.compile(r"^se-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
```

with

```python
RUNS_MAX = 200
MODELS = {"zimage": "Z-Image", "qwen": "Qwen-Image"}
RUN_ID_RE = re.compile(r"^se-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
```

**Edit 2.16** `movie_ui_seedgen.py`: replace

```python
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

with

```python
def capability(models, detail, checked):
    """SG36, seed models SQ32: the seed_edit capability from lib.seed_edit_check's (models, detail),
    with the registry view."""
    if models is None:
        return {"ok": False, "reason": detail, "checked": checked, "models": None, "registry": registry_view()}
    ok = any(m["ok"] for m in models.values())
    reason = None if ok else "; ".join("%s: %s" % (MODELS[k], models[k]["reason"]) for k in ("zimage", "qwen"))
    return {"ok": ok, "reason": reason, "checked": checked, "models": models, "registry": registry_view()}


def availability_error(models, detail, clean):
    """SG37, seed models SQ31: the 409 error for a cleaned request, or None when it can run. For qwen
    the selected model's own probe entry decides, then each selected LoRA's in registry order."""
    if models is None:
        return "cannot check the seed models: %s" % detail
    if clean["model"] == "zimage":
        if not models["zimage"]["ok"]:
            return "%s is unavailable: %s" % (MODELS["zimage"], models["zimage"]["reason"])
        return None
    entry = qwen_model(clean["qwen_model"])
    found = models["qwen"]["models"][entry["id"]]
    if not found["ok"]:
        return "%s is unavailable: %s" % (entry["label"], found["reason"])
    for item in clean["loras"]:
        lora = qwen_lora(item["id"])
        found = models["qwen"]["loras"][lora["id"]]
        if not found["ok"]:
            return "LoRA %s is unavailable: %s" % (lora["label"], found["reason"])
    return None
```

**Edit 2.17** `movie_ui_server.py`: replace

```python
                                 for k in ("render", "stills", "story_server"))
        self.capabilities["seed_edit"] = {"ok": None, "reason": "probing", "checked": None, "models": None}
        self.parser_lock = threading.Lock()
```

with

```python
                                 for k in ("render", "stills", "story_server"))
        self.capabilities["seed_edit"] = {"ok": None, "reason": "probing", "checked": None, "models": None,
                                          "registry": seedgen.registry_view()}
        self.parser_lock = threading.Lock()
```

**Edit 2.18** `movie_ui_server.py`: replace

```python
                   "story_server": lib.story_server_check(self.probe_ws)}
        seed_models, seed_detail = lib.seed_edit_check(self.probe_ws)
        checked = lib.utc_now()
```

with

```python
                   "story_server": lib.story_server_check(self.probe_ws)}
        seed_models, seed_detail = lib.seed_edit_check(self.probe_ws, seedgen.QWEN_MODEL_IDS, seedgen.QWEN_LORA_IDS)
        checked = lib.utc_now()
```

**Edit 2.19** `movie_ui_server.py`: replace

```python
    view = {"run": run, "dir": run_dir, "created": record.get("created"), "state": run_state(server, record, queue)}
    for key in ("prompt", "model", "backend", "strength", "seed", "size", "source_size", "source_origin", "error"):
        view[key] = record.get(key)
```

with

```python
    view = {"run": run, "dir": run_dir, "created": record.get("created"), "state": run_state(server, record, queue)}
    for key in ("prompt", "model", "backend"):
        view[key] = record.get(key)
    view.update(seedgen.record_settings(record))
    for key in ("strength", "seed", "size", "source_size", "source_origin", "error"):
        view[key] = record.get(key)
```

**Edit 2.20** `movie_ui_server.py`: replace

```python
    source, ext = _seed_source(server, real, clean["source"])
    models, detail = lib.seed_edit_check(real)
    error = seedgen.availability_error(models, detail, clean["model"])
    if error is not None:
```

with

```python
    source, ext = _seed_source(server, real, clean["source"])
    models, detail = lib.seed_edit_check(real, seedgen.QWEN_MODEL_IDS, seedgen.QWEN_LORA_IDS)
    error = seedgen.availability_error(models, detail, clean)
    if error is not None:
```

**Edit 2.21** `movie_ui_server.py`: replace

```python
                  "prompt": clean["prompt"], "model": clean["model"], "backend": None,
                  "strength": clean["strength"], "seed": seed, "size": None, "source_size": None,
                  "source": source_file, "source_origin": origin, "job": job_id, "error": None,
                  "candidates": [{"n": i, "seed": seed + i, "status": "pending", "seconds": None}
                                 for i in range(1, clean["candidates"] + 1)]}
        lib.write_json_atomic(os.path.join(run_dir, "run.json"), record)
        fields = {"ws": real, "run": run, "source_file": source_file, "prompt": clean["prompt"],
                  "model": clean["model"], "strength": clean["strength"], "candidates": clean["candidates"],
                  "seed": seed, "source": origin}
```

with

```python
                  "prompt": clean["prompt"], "model": clean["model"], "backend": None,
                  "strength": clean["strength"], "seed": seed,
                  **seedgen.qwen_settings(clean["qwen_model"], clean["loras"]), "size": None, "source_size": None,
                  "source": source_file, "source_origin": origin, "job": job_id, "error": None,
                  "candidates": [{"n": i, "seed": seed + i, "status": "pending", "seconds": None}
                                 for i in range(1, clean["candidates"] + 1)]}
        lib.write_json_atomic(os.path.join(run_dir, "run.json"), record)
        fields = {"ws": real, "run": run, "source_file": source_file, "prompt": clean["prompt"],
                  "model": clean["model"], "strength": clean["strength"], "qwen_model": clean["qwen_model"],
                  "loras": clean["loras"], "candidates": clean["candidates"],
                  "seed": seed, "source": origin}
```

**Edit 2.22** `movie_ui_server.py`: replace

```python
        cands = [(c, _cand_file(run_dir, c)) for c in _candidates(record)]
        runs.append({"run": name, "created": record.get("created"), "state": run_state(self.server, record, queue),
                     "prompt": record.get("prompt"), "model": record.get("model"), "backend": record.get("backend"),
                     "count": len(cands), "ok": sum(1 for c, _path in cands if c.get("status") == "ok"),
                     "thumbs": [path for _c, path in cands if path is not None]})
```

with

```python
        cands = [(c, _cand_file(run_dir, c)) for c in _candidates(record)]
        settings = seedgen.record_settings(record)
        runs.append({"run": name, "created": record.get("created"), "state": run_state(self.server, record, queue),
                     "prompt": record.get("prompt"), "model": record.get("model"), "backend": record.get("backend"),
                     "qwen_model": settings["qwen_model"], "loras": settings["loras"], "count": len(cands), "ok": sum(1 for c, _path in cands if c.get("status") == "ok"),
                     "thumbs": [path for _c, path in cands if path is not None]})
```

- [ ] **Step 4: Run the tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedmodels-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py 2>&1 | tail -1
```

Expected: `133 passed`. Run the compile check with `FILES` = `movie_ui_seedgen.py movie_ui_lib.py movie_ui_server.py tests/test_movie_ui_seedgen.py`; expected `compiled 4` twice. Then run the gate block ("Between tasks") with `N=2`. Expected: `GATE PASS`, `lost 0`, `new tests 133, not passing 0`, `baseline failures still failing 2 of 2`, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedmodels-wt/qwen-agent-workspace
git add movie_ui_seedgen.py movie_ui_lib.py movie_ui_server.py tests/test_movie_ui_seedgen.py
git diff --cached --name-only    # expected: exactly these 4 paths, with the qwen-agent-workspace/ prefix
git commit -m "feat(seed-models): the movie-ui side of the registry: probe shape, argv, capability registry, per-model and per-LoRA 409s, run record, view and list (SQ31-SQ40; SQT16-SQT17, SQT19-SQT21)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `bin/seed-edit`: the selection, the 2.1 canvas, pinned lookups, the probe, the preflight and the child spec (SQ12-SQ27; SQT1-SQT7, Review Focus 1, 3, 5)

This task implements:
- SQ12 `--qwen-model`/`--lora` and rows 9-16 (`check_loras`, PR4); SQ13 labels; SQ14 `canvas(w0, h0, multiple=MULTIPLE)` called with `seedgen.canvas_multiple(...)`.
- SQ15's three functions typed exactly; SQ16 `qwen_hubs`, `mflux_env_problem` (0.24.0 gate), `lora_problem`, `qwen_model_problem`, `memory_problem`; SQ17's removals (`choose_qwen`, `mflux_problem`, the two override variables, four constants); `MFLUX_MIN_VERSION = (0, 24, 0)`; `BACKEND_LABELS`.
- SQ18 the probe's new shape; SQ19 `new_record`'s four keys; SQ20 the backend line; SQ21 the preflight (PR7); SQ22 the runner map; SQ23 the mflux spec (PR6); SQ26/SQ27 the docstring and the import.
- Tests: SQT1-SQT7, Review Focus 1, 3 and 5; helpers `pinned_cache`, `QWEN21_FILES`, `install_model`, `install_lora`, and `mflux_weights(env)` rebuilt on pinned caches; SGT2, SGT7, SGT9, SGT10, SGT11, SGT13, SGT14, SG Review Focus 4, SGT16 (interim, PR2 (c)) and SGT34 re-baselined; SGT8 deleted.

**Files:**
- Modify: `bin/seed-edit` (docstring `:1-39`; import `:58`; constants `:68-83`; `parse` `:109-115`; `check_args` `:118-159`; `canvas` `:166-177`; `prepare_source` `:206`; `mflux_problem`/`choose_qwen`/`probe` `:332-418` replaced; `preflight` `:438-460`; `new_record` `:474-475`; `run_bf16` `:670`; `run_mflux` `:674-706`; `run` `:729-734`)
- Modify: `tests/test_seed_edit_tool.py`, `tests/test_movie_ui_seedgen.py` (SGT34 only)

**Interfaces:**
- Consumes:
  - Task 1: `seedgen.QWEN_MODELS`, `QWEN_LORAS`, `QWEN_MODEL_IDS`, `QWEN_LORA_IDS`, `QWEN_FAMILIES`, `QWEN21_REQUIRED`, `LEGACY_QWEN_MODEL`, `SCALE_MAX`, `qwen_model`, `qwen_lora`, `registry_order`, `qwen_settings`, `canvas_multiple`.
  - Task 2: `lib.seed_edit_argv` (Review Focus 3 and 5 only).
  - Existing: `lib.intact_scan(snapshot, repo_dir) -> (problems, notes)`, `lib.repo_dir_name`, `lib.zimage_hub`, `bf16_problem`, `modules_problem`, `wait_for_memory`, `run_qwen_child`.
- Produces:
  - `bin/seed-edit` functions (Task 5 copies the first five byte for byte): `mflux_version(venv)` and `default_hub()` (unchanged), `pinned_snapshot(repo, revision, hubs) -> (snapshot, repo_dir) or (None, None)`, `pinned_file(repo, revision, name, hubs) -> path or None`, `weights_problem(entry, hubs) -> (problem, model dir, built-in LoRA path)`.
  - `qwen_hubs() -> [zimage hub, default hub]`; `mflux_env_problem() -> str or None`; `lora_problem(lora, hubs) -> (problem, path)`; `qwen_model_problem(entry) -> (problem, paths)`; `memory_problem(entry) -> str or None`; `probe()` in SQ18's shape; `MFLUX_MIN_VERSION = (0, 24, 0)` (Task 4's SQT9 compares the child's).
  - The child spec (Task 4's input): `{"family", "model_path", "lora_paths", "lora_scales", "prompt", "source", "width", "height", "steps", "guidance", "scheduler", "jobs": [{"n", "seed", "output_path"}]}`.
  - Test helpers in `tests/test_seed_edit_tool.py`: `pinned_cache(root, repo, revision, files) -> snapshot`, `QWEN21_FILES`, `install_model(env, model_id, root="zi", files=None) -> (snapshot, Lightning path or None)`, `install_lora(env, lora_id, root="zi") -> path`, `mflux_weights(env) -> (snapshot, Lightning path)`.

- [ ] **Step 1: Write the failing tests.** Make these edits in order (Edit tool; each old text occurs exactly once at its turn).

**Edit 3.1** `tests/test_movie_ui_seedgen.py`: replace

```python
        "argparse", "glob", "importlib.util", "json", "os", "re", "secrets", "shutil", "signal", "subprocess", "sys",
        "threading", "time", "movie_ui_lib"]

```

with

```python
        "argparse", "glob", "importlib.util", "json", "os", "re", "secrets", "shutil", "signal", "subprocess", "sys",
        "threading", "time", "movie_ui_lib", "movie_ui_seedgen"]

```

**Edit 3.2** `tests/test_seed_edit_tool.py`: replace

```python

def mflux_weights(env, lora=True):
    """The q4 repo (and the Lightning repo) in the Z-Image hub; returns (q4 snapshot, Lightning path)."""
    root, tool = os.path.join(env["tmp"], "zi"), env["tool"]
    q4 = mt.make_hf_cache(root, tool.Q4_REPO, {"transformer/0.safetensors": b"\x01" * 8})
    path = None
    if lora:
        repo = mt.make_hf_cache(root, tool.EDIT_LORA_REPO, {tool.EDIT_LORA_FILE: b"\x01" * 8})
        path = os.path.join(repo, "snapshots", REV, tool.EDIT_LORA_FILE)
    return os.path.join(q4, "snapshots", REV), path

```

with

```python

def pinned_cache(root, repo, revision, files):
    """Seed models spec 9.1: mt.make_hf_cache without refs/main, its snapshot renamed to revision (the
    blob links are relative, so they keep working); returns the snapshot path."""
    repo_dir = mt.make_hf_cache(root, repo, files, refs=False)
    snapshot = os.path.join(repo_dir, "snapshots", revision)
    os.rename(os.path.join(repo_dir, "snapshots", REV), snapshot)
    return snapshot


QWEN21_FILES = {"vae/config.json": b"{}", "transformer/config.json": b"{}", "text_encoder/config.json": b"{}",
                "processor/tokenizer.json": b"{}", "transformer/0.safetensors": b"\x01" * 8}


def install_model(env, model_id, root="zi", files=None):
    """Registry model model_id's pinned snapshot under <tmp>/<root>/hub (zi: the Z-Image hub, hf: the
    default hub), plus its pinned built-in Lightning file; returns (snapshot, Lightning path or None)."""
    entry = seedgen.qwen_model(model_id)
    base = os.path.join(env["tmp"], root)
    if files is None:
        files = QWEN21_FILES if entry["family"] == "qwen21" else {"transformer/0.safetensors": b"\x01" * 8}
    snapshot = pinned_cache(base, entry["repo"], entry["revision"], files)
    lora = entry["builtin_lora"]
    if lora is None:
        return snapshot, None
    lightning = pinned_cache(base, lora["repo"], lora["revision"], {lora["file"]: b"\x01" * 8})
    return snapshot, os.path.join(lightning, lora["file"])


def install_lora(env, lora_id, root="zi"):
    """Registry LoRA lora_id's pinned file under <tmp>/<root>/hub; returns its snapshot path."""
    lora = seedgen.qwen_lora(lora_id)
    snapshot = pinned_cache(os.path.join(env["tmp"], root), lora["repo"], lora["revision"],
                            {lora["file"]: b"\x01" * 8})
    return os.path.join(snapshot, lora["file"])


def mflux_weights(env):
    """The pinned qwen2511-q4 snapshot and its pinned Lightning file in the Z-Image hub; returns
    (snapshot, Lightning path)."""
    return install_model(env, "qwen2511-q4")

```

**Edit 3.3** `tests/test_seed_edit_tool.py`: replace

```python
        "model": "zimage", "backend": "zimage", "strength": 0.3, "seed": 100,
        "size": {"width": 1024, "height": 672}, "source_size": {"width": 1536, "height": 1024},
```

with

```python
        "model": "zimage", "backend": "zimage", "strength": 0.3, "seed": 100,
        "qwen_model": None, "loras": [], "steps": None, "scheduler": None,
        "size": {"width": 1024, "height": 672}, "source_size": {"width": 1536, "height": 1024},
```

**Edit 3.4** `tests/test_seed_edit_tool.py`: replace

```python
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
```

with

```python
    mflux_weights(env)
    code, run_dir = run_tool(env, "--qwen-model", "qwen2511-q4", run=R5, model="qwen")
    assert code == 2
    _refused(run_dir, "only 10.0 GiB available after waiting 0 s; Qwen-Image-Edit-2511 q4 (Lightning) needs 32 GiB; "
                      "free memory and retry", capsys.readouterr())
    assert calls["zimage"] == [] and stub_calls(py) == []
    assert record_of(run_dir)["size"] == {"width": 1024, "height": 672}


# --- SQT1 (seed models SQ14): the canvas floors to 32 for Qwen-Image-2.1 ---------------------------------

CANVAS_32 = [((1536, 1024), (1024, 672)), ((1024, 1024), (1024, 1024)), ((800, 600), (800, 576)),
             ((4000, 3000), (1024, 768)), ((3000, 4000), (768, 1024)), ((720, 1280), (576, 1024)),
             ((1023, 1023), (992, 992)), ((100, 70), (96, 64)), ((90, 90), (64, 64))]


def test_sqt1_the_canvas_for_qwen21(env):
    tool = env["tool"]
    for (w0, h0), want in CANVAS_32:
        assert tool.canvas(w0, h0, 32) == want, (w0, h0)
    with pytest.raises(tool.Refusal) as info:
        tool.canvas(100, 60, 32)
    assert str(info.value) == "--source is too small: 100x60 gives a 96x32 canvas; each side must be at least 64 px"
    for (w0, h0), want in CANVAS:
        assert tool.canvas(w0, h0) == tool.canvas(w0, h0, 16) == want, (w0, h0)


# --- SQT2 (seed models SQ12): --qwen-model and --lora ------------------------------------------------------

QBASE = ["--source", "SRC", "--prompt", PROMPT, "--model", "qwen", "--run-dir", "RUNDIR"]
Q21 = QBASE + ["--qwen-model", "qwen21-q4"]
SCALE_TEXT = "--lora uncensored scale must be a number above 0 and at most 2"
QARG_CASES = [
    (["--probe", "--lora", "uncensored=1"], "--probe takes no other options"),
    (["--probe", "--qwen-model", "qwen21-q4"], "--probe takes no other options"),
    (BASE + ["--qwen-model", "qwen21-q4"], "--qwen-model is only for --model qwen"),
    (BASE + ["--qwen-model", "x", "--lora", "y"], "--qwen-model is only for --model qwen"),
    (BASE + ["--lora", "uncensored=1"], "--lora is only for --model qwen"),
    (QBASE + ["--qwen-model", "flux"],
     "--qwen-model must be one of qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-q4, qwen2511-bf16"),
    (QBASE + ["--candidates", "0", "--qwen-model", "flux"], "--candidates must be an integer from 1 to 4"),
    (QBASE + ["--qwen-model", "flux", "--seed", "-1"],
     "--qwen-model must be one of qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-q4, qwen2511-bf16"),
    (Q21 + ["--lora", "uncensored"], "--lora must be ID=SCALE (got uncensored)"),
    (Q21 + ["--lora", "=1"], "--lora must be ID=SCALE (got =1)"),
    (Q21 + ["--lora", "Uncensored=1"], "--lora must be ID=SCALE (got Uncensored=1)"),
    (Q21 + ["--lora", "nope=1"], "--lora: unknown LoRA nope; known: uncensored, viggle-turbo"),
    (Q21 + ["--lora", "nope=1", "--lora", "x"], "--lora: unknown LoRA nope; known: uncensored, viggle-turbo"),
    (Q21 + ["--lora", "uncensored=1", "--lora", "uncensored=0.5"], "--lora uncensored is given twice"),
    (QBASE + ["--qwen-model", "qwen2511-q4", "--lora", "uncensored=1"],
     "--lora uncensored is for Qwen-Image-2.1, not Qwen-Image-Edit-2511 q4 (Lightning)"),
    (QBASE + ["--lora", "uncensored=1"],
     "--lora uncensored is for Qwen-Image-2.1, not Qwen-Image-Edit-2511 q4 (Lightning)"),
    (Q21 + ["--lora", "uncensored=0"], SCALE_TEXT),
    (Q21 + ["--lora", "uncensored=-1"], SCALE_TEXT),
    (Q21 + ["--lora", "uncensored=2.5"], SCALE_TEXT),
    (Q21 + ["--lora", "uncensored=x"], SCALE_TEXT),
    (Q21 + ["--lora", "uncensored=nan"], SCALE_TEXT),
    (Q21 + ["--lora", "uncensored=inf"], SCALE_TEXT),
    (Q21 + ["--lora", "uncensored=1", "--seed", "-1"], "--seed must be an integer from 0 to 2147483647"),
]


@pytest.mark.parametrize("argv,message", QARG_CASES, ids=["case%d" % (i + 1) for i in range(len(QARG_CASES))])
def test_sqt2_bad_qwen_arguments(env, capsys, argv, message):
    source = png(os.path.join(env["tmp"], "src.png"), (128, 128))
    run_dir = os.path.join(env["tmp"], "runs", RUN)
    argv = [source if a == "SRC" else run_dir if a == "RUNDIR" else a for a in argv]
    assert env["tool"].main(argv) == 2
    assert capsys.readouterr() == ("", "Error: %s\n" % message)
    assert not os.path.exists(run_dir)


def test_sqt2_the_cleaned_qwen_options(env):
    tool = env["tool"]

    def opts(*extra, model="qwen"):
        return tool.check_args(tool.parse(["--source", "s", "--prompt", PROMPT, "--model", model, "--run-dir", "r",
                                           "--seed", "1"] + list(extra)))

    got = opts()
    assert (got["qwen_model"], got["loras"]) == ("qwen2511-q4", [])
    got = opts("--qwen-model", "qwen21-q4", "--lora", "viggle-turbo=0.5", "--lora", "uncensored=1")
    assert (got["qwen_model"], got["loras"]) == ("qwen21-q4", [{"id": "uncensored", "scale": 1.0},
                                                              {"id": "viggle-turbo", "scale": 0.5}])
    assert opts("--qwen-model", "qwen21-q8", "--lora", "uncensored=2")["loras"] == [{"id": "uncensored", "scale": 2.0}]
    assert opts("--qwen-model", "qwen21-q4")["loras"] == []
    got = opts(model="zimage")
    assert (got["qwen_model"], got["loras"]) == (None, [])


# --- SQT3 (seed models SQ15-SQ17): the pinned registry lookups --------------------------------------------

def test_sqt3_the_pinned_lookups(env):
    tool, mp, zhub, hfhub = env["tool"], env["mp"], env["zhub"], env["hfhub"]
    hubs, where = [zhub, hfhub], "%s or %s" % (zhub, hfhub)
    q8 = seedgen.qwen_model("qwen21-q8")
    absent = ("mflux-community/qwen-image-2-1-mflux-q8@f5c8cc79a674 is not in %s "
              "(run bin/seed-edit-setup --model qwen21-q8)" % where)
    assert tool.weights_problem(q8, hubs) == (absent, None, None)
    mt.make_hf_cache(os.path.join(env["tmp"], "hf"), q8["repo"], QWEN21_FILES)
    assert tool.weights_problem(q8, hubs) == (absent, None, None)
    q8_snapshot, _none = install_model(env, "qwen21-q8")
    assert tool.weights_problem(q8, hubs) == (None, q8_snapshot, None)
    q4 = seedgen.qwen_model("qwen21-q4")
    snapshot, _none = install_model(env, "qwen21-q4")
    with open(os.path.join(os.path.dirname(os.path.dirname(snapshot)), "blobs", "partial0.incomplete"), "wb") as f:
        f.write(b"x")
    assert tool.weights_problem(q4, hubs) == (
        "mflux-community/qwen-image-2-1-mflux-q4: download incomplete: 1 partial blob(s) "
        "(run bin/seed-edit-setup --model qwen21-q4)", None, None)
    bf16 = seedgen.qwen_model("qwen21-bf16")
    files = dict(QWEN21_FILES)
    del files["vae/config.json"], files["processor/tokenizer.json"]
    install_model(env, "qwen21-bf16", files=files)
    assert tool.weights_problem(bf16, hubs) == (
        "Qwen/Qwen-Image-2.1: missing vae/config.json; missing processor/ (run bin/seed-edit-setup --model qwen21-bf16)",
        None, None)
    e2511 = seedgen.qwen_model("qwen2511-q4")
    only = pinned_cache(os.path.join(env["tmp"], "hf"), e2511["repo"], e2511["revision"],
                        {"transformer/0.safetensors": b"\x01" * 8})
    mt.make_hf_cache(os.path.join(env["tmp"], "zi"), tool.EDIT_LORA_REPO, {tool.EDIT_LORA_FILE: b"\x01" * 8})
    assert tool.weights_problem(e2511, hubs) == (
        "Lightning LoRA Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors is not in %s "
        "(run bin/seed-edit-setup --model qwen2511-q4)" % where, None, None)
    lightning = os.path.join(pinned_cache(os.path.join(env["tmp"], "hf"), tool.EDIT_LORA_REPO,
                                          e2511["builtin_lora"]["revision"], {tool.EDIT_LORA_FILE: b"\x01" * 8}),
                             tool.EDIT_LORA_FILE)
    assert tool.weights_problem(e2511, hubs) == (None, only, lightning)
    unc = seedgen.qwen_lora("uncensored")
    missing = ("qwen-image-2.1-uncensored-lora.safetensors is not in %s (run bin/seed-edit-setup --lora uncensored)"
               % where)
    assert tool.lora_problem(unc, hubs) == (missing, None)
    pinned_cache(os.path.join(env["tmp"], "zi"), unc["repo"], unc["revision"], {unc["file"]: b""})
    assert tool.lora_problem(unc, hubs) == (missing, None)
    found = install_lora(env, "uncensored", root="hf")
    assert tool.lora_problem(unc, hubs) == (None, found)
    py = os.path.join(env["tmp"], "mflux-edit", ".venv", "bin", "python")
    venv = os.path.dirname(os.path.dirname(py))
    mp.setenv("SEED_EDIT_MFLUX_PYTHON", py)
    assert tool.mflux_env_problem() == "no mflux venv at %s (run bin/seed-edit-setup)" % py
    mflux_venv(env, version=None)
    assert tool.mflux_env_problem() == "mflux is not installed in %s (run bin/seed-edit-setup)" % venv
    set_mflux_version(venv, "banana")
    assert tool.mflux_env_problem() == "cannot read the mflux version in %s" % venv
    set_mflux_version(venv, "0.23.9")
    assert tool.mflux_env_problem() == "mflux 0.23.9 in %s is older than 0.24.0 (run bin/seed-edit-setup)" % venv
    for version in ("0.24.0", "0.25.1"):
        set_mflux_version(venv, version)
        assert tool.mflux_env_problem() is None
    assert tool.qwen_model_problem(q8) == (None, {"model_path": q8_snapshot, "builtin_lora": None})
    mp.setattr(tool, "missing_modules", lambda names: ["torch"])
    assert tool.qwen_model_problem(q8) == ("torch not importable by %s" % sys.executable, {})
    assert tool.qwen_hubs() == [zhub, hfhub]
    assert tool.MFLUX_MIN_VERSION == (0, 24, 0)
    with open(TOOL_PATH, encoding="utf-8") as f:
        source = f.read()
    for gone in ("SEED_EDIT_QWEN_Q4_DIR", "SEED_EDIT_LIGHTNING_FILE", "def choose_qwen(", "def mflux_problem(",
                 "BF16_MIN_AVAIL_GIB", "MFLUX_MIN_AVAIL_GIB", "Q4_REPO", "Q4_NAME_PART"):
        assert gone not in source, gone
    assert set(re.findall(r"os\.environ(?:\.get\(|\[)\"([A-Z0-9_]+)\"", source)) == {
        "SEED_EDIT_MFLUX_PYTHON", "SEED_EDIT_QWENEDIT_SCRIPT", "HF_HUB_CACHE", "HF_HOME"}


# --- SQT4 (seed models SQ18): the probe's new shape ---------------------------------------------------------

def test_sqt4_the_probe(env, capsys):
    tool, mp, zhub, hfhub = env["tool"], env["mp"], env["zhub"], env["hfhub"]
    where = "%s or %s" % (zhub, hfhub)
    zimage_cache(env)
    mflux_venv(env)

    def absent(model_id, revision):
        return "%s@%s is not in %s (run bin/seed-edit-setup --model %s)" % (
            seedgen.qwen_model(model_id)["repo"], revision, where, model_id)

    mem = "needs a host with at least %d GiB of memory (this host has 48.0 GiB)"
    nothing = {"qwen21-q4": absent("qwen21-q4", "b6c0fc763506"), "qwen21-q8": absent("qwen21-q8", "f5c8cc79a674"),
               "qwen21-bf16": mem % 56, "qwen2511-q4": absent("qwen2511-q4", "3c74aab7dd79"),
               "qwen2511-bf16": mem % 64}
    viggle = ("Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors is not in %s "
              "(run bin/seed-edit-setup --lora viggle-turbo)" % where)
    uncensored = ("qwen-image-2.1-uncensored-lora.safetensors is not in %s (run bin/seed-edit-setup --lora uncensored)"
                  % where)
    got = tool.probe()["qwen"]
    assert got == {"ok": False, "reason": "; ".join("%s: %s" % (i, nothing[i]) for i in seedgen.QWEN_MODEL_IDS),
                   "models": dict((i, {"ok": False, "reason": nothing[i]}) for i in seedgen.QWEN_MODEL_IDS),
                   "loras": {"uncensored": {"ok": False, "reason": uncensored},
                             "viggle-turbo": {"ok": False, "reason": viggle}}}
    install_model(env, "qwen21-q4")
    install_lora(env, "uncensored")
    models = dict((i, {"ok": False, "reason": nothing[i]}) for i in seedgen.QWEN_MODEL_IDS)
    models["qwen21-q4"] = {"ok": True, "reason": None}
    assert tool.probe() == {"zimage": {"ok": True, "reason": None, "backend": "zimage"},
                            "qwen": {"ok": True, "reason": None, "models": models,
                                     "loras": {"uncensored": {"ok": True, "reason": None},
                                               "viggle-turbo": {"ok": False, "reason": viggle}}}}
    assert tool.main(["--probe"]) == 0
    assert capsys.readouterr().out == json.dumps(tool.probe(), sort_keys=True) + "\n"
    install_model(env, "qwen21-bf16")
    mp.setattr(tool, "total_gib", lambda: 128.0)
    got = tool.probe()["qwen"]
    assert got["models"]["qwen21-bf16"] == {"ok": True, "reason": None}
    assert "backend" not in got and set(got) == {"ok", "reason", "models", "loras"}
    mp.setattr(tool, "total_gib", lambda: None)
    assert set(e["reason"] for e in tool.probe()["qwen"]["models"].values()) == {"cannot read this host's memory size"}


# --- SQT5 (seed models SQ7, SQ19-SQ23): every mflux selection's child spec, record and backend line ---------

SQT5_CASES = [
    ("qwen21-q4", ["uncensored=1.0"], ["uncensored"], [1.0], 40, "linear",
     "Qwen-Image-2.1 q4; LoRAs uncensored@1; 40 steps; scheduler linear"),
    ("qwen21-q4", ["viggle-turbo=1.0", "uncensored=0.5"], ["uncensored", "viggle-turbo"], [0.5, 1.0], 6,
     "viggle_turbo", "Qwen-Image-2.1 q4; LoRAs uncensored@0.5, viggle-turbo@1; 6 steps; scheduler viggle_turbo"),
    ("qwen21-q8", [], [], [], 40, "linear", "Qwen-Image-2.1 q8; LoRAs none; 40 steps; scheduler linear"),
    ("qwen21-bf16", ["uncensored=1.0"], ["uncensored"], [1.0], 40, "linear",
     "Qwen-Image-2.1 bf16; LoRAs uncensored@1; 40 steps; scheduler linear"),
    ("qwen2511-q4", [], ["lightning"], [1.0], 8, None,
     "Qwen-Image-Edit-2511 q4 (Lightning); LoRAs none; 8 steps; scheduler default"),
]


@pytest.mark.parametrize("model_id,loras,paths,scales,steps,scheduler,why", SQT5_CASES,
                         ids=["case%d" % (i + 1) for i in range(len(SQT5_CASES))])
def test_sqt5_the_mflux_selection(env, capsys, model_id, loras, paths, scales, steps, scheduler, why):
    tool = env["tool"]
    env["mp"].setattr(tool, "avail_gib", lambda: 128.0)
    py, _venv = mflux_venv(env)
    snapshot, lightning = install_model(env, model_id)
    found = {"lightning": lightning}
    for lora_id in ("uncensored", "viggle-turbo"):
        found[lora_id] = install_lora(env, lora_id)
    extra = ["--qwen-model", model_id, "--candidates", "2", "--seed", "100"]
    for value in loras:
        extra += ["--lora", value]
    code, run_dir = run_tool(env, *extra, model="qwen")
    assert code == 0
    work = os.path.join(run_dir, "work")
    calls = stub_calls(py)
    assert len(calls) == 1
    assert calls[0]["argv"] == [py, os.path.join(WS, "seed_edit_mflux_child.py"), "--spec",
                                os.path.join(work, "mflux_spec.json")]
    assert calls[0]["env"]["HF_HUB_OFFLINE"] == "1"
    entry = seedgen.qwen_model(model_id)
    assert calls[0]["spec"] == {
        "family": entry["family"], "model_path": snapshot, "lora_paths": [found[p] for p in paths],
        "lora_scales": scales, "prompt": PROMPT, "source": os.path.join(work, "source.png"), "width": 1024,
        "height": 672, "steps": steps, "guidance": 1.0, "scheduler": scheduler,
        "jobs": [{"n": n, "seed": 100 + n, "output_path": os.path.join(work, "cand_%02d.pending.png" % n)}
                 for n in (1, 2)]}
    assert all(p.startswith(env["zhub"]) and os.path.realpath(p) != p for p in calls[0]["spec"]["lora_paths"])
    record = record_of(run_dir)
    chosen = [{"id": v.split("=")[0], "scale": float(v.split("=")[1])} for v in loras]
    assert (record["backend"], record["state"]) == ("mflux", "done")
    assert {k: record[k] for k in ("qwen_model", "loras", "steps", "scheduler")} == seedgen.qwen_settings(
        model_id, chosen)
    assert (record["steps"], record["scheduler"]) == (steps, scheduler)
    assert "seed-edit: backend mflux (%s)" % why in capsys.readouterr().out.splitlines()


# --- SQT6 (seed models SQ24): content safety screens every candidate of every registry model --------------

def test_sqt6_content_safety_on_every_candidate_of_every_model(env, capsys):
    tool, calls = env["tool"], env["calls"]
    env["mp"].setattr(tool, "avail_gib", lambda: 70.0)
    py, _venv = mflux_venv(env)
    for model_id in ("qwen21-q4", "qwen21-q8", "qwen21-bf16", "qwen2511-q4"):
        install_model(env, model_id)
    for lora_id in ("uncensored", "viggle-turbo"):
        install_lora(env, lora_id)
    stub_config(py, {"red": [2]})
    cases = [("qwen2511-q4", [])]
    for model_id in ("qwen21-q4", "qwen21-q8", "qwen21-bf16"):
        cases += [(model_id, []), (model_id, ["uncensored=1"]), (model_id, ["viggle-turbo=1"]),
                  (model_id, ["uncensored=0.5", "viggle-turbo=1"])]
    for i, (model_id, loras) in enumerate(cases):
        calls["safety"] = []
        extra = ["--qwen-model", model_id, "--candidates", "3", "--seed", "100"]
        for value in loras:
            extra += ["--lora", value]
        code, run_dir = run_tool(env, *extra, model="qwen", run="se-20261102-141500-%04x" % i)
        assert code == 0, (model_id, loras)
        assert calls["safety"] == [{"skill": "seed_edit", "prompt": PROMPT, "size": (1024, 672)}] * 3, (model_id, loras)
        assert statuses(run_dir) == ["ok", "blocked", "ok"], (model_id, loras)
        assert [os.path.isfile(cand(run_dir, n)) for n in (1, 2, 3)] == [True, False, True], (model_id, loras)
        assert not os.path.exists(os.path.join(run_dir, "work", "cand_02.pending.png"))
    assert len(stub_calls(py)) == len(cases)
    bf16_cache(env)
    stub = qwenedit_stub(env, {"blocked": [2]})
    calls["safety"] = []
    code, run_dir = run_tool(env, "--qwen-model", "qwen2511-bf16", "--candidates", "3", "--seed", "100", model="qwen",
                             run="se-20261102-141500-ffff")
    assert code == 0
    work = os.path.join(run_dir, "work")
    spec = stub_calls(stub)[0]["spec"]
    assert spec == {
        "image": os.path.join(work, "source.png"), "model": "Qwen/Qwen-Image-Edit-2511",
        "lora_repo": "lightx2v/Qwen-Image-Edit-2511-Lightning",
        "lora_file": "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors", "steps": 8, "true_cfg": 1.0,
        "skill": "seed_edit",
        "jobs": [{"prompt": PROMPT, "output_path": os.path.join(work, "cand_%02d.part.png" % n), "seed": 100 + n,
                  "width": 1024, "height": 672} for n in (1, 2, 3)],
        "report_path": os.path.join(work, "qwenedit_report.json")}
    assert statuses(run_dir) == ["ok", "blocked", "ok"]
    assert [os.path.isfile(cand(run_dir, n)) for n in (1, 2, 3)] == [True, False, True]
    assert calls["safety"] == []


# --- SQT7 (seed models SQ13, SQ21): run-time refusals and the child failure text ----------------------------

def test_sqt7_run_time_refusals(env, capsys):
    tool, mp, zhub, hfhub = env["tool"], env["mp"], env["zhub"], env["hfhub"]
    where = "%s or %s" % (zhub, hfhub)
    py, venv = mflux_venv(env)
    install_model(env, "qwen21-q4")
    install_lora(env, "uncensored")
    cases = [
        (["--qwen-model", "qwen21-q8"], "Qwen-Image-2.1 q8 is unavailable: mflux-community/qwen-image-2-1-mflux-q8"
         "@f5c8cc79a674 is not in %s (run bin/seed-edit-setup --model qwen21-q8)" % where),
        (["--qwen-model", "qwen21-q4", "--lora", "uncensored=1", "--lora", "viggle-turbo=1"],
         "LoRA Viggle turbo 6-step is unavailable: Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors "
         "is not in %s (run bin/seed-edit-setup --lora viggle-turbo)" % where),
    ]
    for i, (extra, text) in enumerate(cases):
        code, run_dir = run_tool(env, *extra, model="qwen", run=(R1, R2)[i])
        assert code == 2
        _refused(run_dir, text, capsys.readouterr())
    mp.setattr(tool, "avail_gib", lambda: 10.0)
    mp.setattr(tool, "AVAIL_WAIT_S", 0)
    code, run_dir = run_tool(env, "--qwen-model", "qwen21-q4", model="qwen", run=R3)
    assert code == 2
    _refused(run_dir, "only 10.0 GiB available after waiting 0 s; Qwen-Image-2.1 q4 needs 20 GiB; free memory and retry",
             capsys.readouterr())
    bf16_cache(env)
    stub = qwenedit_stub(env, {})
    mp.setattr(tool, "avail_gib", lambda: 40.0)
    code, run_dir = run_tool(env, "--qwen-model", "qwen2511-bf16", model="qwen", run=R4)
    assert code == 2
    _refused(run_dir, "only 40.0 GiB available after waiting 0 s; Qwen-Image-Edit-2511 bf16 (Lightning, diffusers) "
                      "needs 64 GiB; free memory and retry", capsys.readouterr())
    set_mflux_version(venv, "0.23.0")
    code, run_dir = run_tool(env, "--qwen-model", "qwen21-q4", model="qwen", run=R5)
    assert code == 2
    _refused(run_dir, "Qwen-Image-2.1 q4 is unavailable: mflux 0.23.0 in %s is older than 0.24.0 "
                      "(run bin/seed-edit-setup)" % venv, capsys.readouterr())
    assert stub_calls(py) == [] and stub_calls(stub) == []
    set_mflux_version(venv, "0.24.0")
    stub_config(py, {"fail_after": 1})
    code, run_dir = run_tool(env, "--qwen-model", "qwen21-q4", "--lora", "uncensored=1", "--candidates", "3",
                             model="qwen", run="se-20261102-141500-0006")
    assert code == 1
    assert record_of(run_dir)["error"] == "Qwen-Image-2.1 q4 child exited 1: boom"
    assert statuses(run_dir) == ["ok", "failed", "failed"]


# --- SGT9 (SG20, SG21, SG22): the mflux child, screened in the parent ----------------------------------
# --- SGT9 (SG20, SG21, SG22): the mflux child, screened in the parent ----------------------------------

def test_sgt9_the_mflux_child_screened_in_the_parent(env, capsys):
    py, _venv = mflux_venv(env)
    q4, lora = mflux_weights(env)
    stub_config(py, {"red": [2]})
    code, run_dir = run_tool(env, "--qwen-model", "qwen2511-q4", "--candidates", "3", "--seed", "100", model="qwen")
    assert code == 0
```

**Edit 3.5** `tests/test_seed_edit_tool.py`: replace

```python
    assert calls[0]["spec"] == {
        "model_path": q4, "lora_path": lora, "prompt": PROMPT, "source": os.path.join(work, "source.png"),
        "width": 1024, "height": 672, "steps": 8, "guidance": 1.0,
        "jobs": [{"n": n, "seed": 100 + n, "output_path": os.path.join(work, "cand_%02d.pending.png" % n)}
```

with

```python
    assert calls[0]["spec"] == {
        "family": "qwen2511", "model_path": q4, "lora_paths": [lora], "lora_scales": [1.0], "prompt": PROMPT,
        "source": os.path.join(work, "source.png"), "width": 1024, "height": 672, "steps": 8, "guidance": 1.0,
        "scheduler": None,
        "jobs": [{"n": n, "seed": 100 + n, "output_path": os.path.join(work, "cand_%02d.pending.png" % n)}
```

**Edit 3.6** `tests/test_seed_edit_tool.py`: replace

```python
    assert [c["seconds"] for c in record["candidates"]] == [1.0, 1.0, 1.0]
    assert (record["backend"], record["state"], record["strength"]) == ("mflux-q4", "done", None)
    assert env["calls"]["safety"] == [{"skill": "seed_edit", "prompt": PROMPT, "size": (1024, 672)}] * 3
    out = capsys.readouterr().out.splitlines()
    assert "seed-edit: backend mflux-q4 (diffusers bf16: Qwen/Qwen-Image-Edit-2511 is not in %s)" % env["hfhub"] in out
    assert plain([line for line in out if line.startswith("candidate ")]) == [
```

with

```python
    assert [c["seconds"] for c in record["candidates"]] == [1.0, 1.0, 1.0]
    assert (record["backend"], record["state"], record["strength"]) == ("mflux", "done", None)
    assert env["calls"]["safety"] == [{"skill": "seed_edit", "prompt": PROMPT, "size": (1024, 672)}] * 3
    out = capsys.readouterr().out.splitlines()
    assert "seed-edit: backend mflux (Qwen-Image-Edit-2511 q4 (Lightning); LoRAs none; 8 steps; scheduler default)" in out
    assert plain([line for line in out if line.startswith("candidate ")]) == [
```

**Edit 3.7** `tests/test_seed_edit_tool.py`: replace

```python
    stub_config(py, {"fail_after": 1})
    code, run_dir = run_tool(env, "--candidates", "3", "--seed", "100", model="qwen", run=R1)
    assert code == 1
    record = record_of(run_dir)
    assert statuses(run_dir) == ["ok", "failed", "failed"]
    assert (record["state"], record["error"]) == ("failed", "mflux q4 child exited 1: boom")
    assert os.path.isfile(cand(run_dir, 1))
```

with

```python
    stub_config(py, {"fail_after": 1})
    q4 = ["--qwen-model", "qwen2511-q4", "--candidates", "3", "--seed", "100"]
    code, run_dir = run_tool(env, *q4, model="qwen", run=R1)
    assert code == 1
    record = record_of(run_dir)
    assert statuses(run_dir) == ["ok", "failed", "failed"]
    assert (record["state"], record["error"]) == ("failed", "Qwen-Image-Edit-2511 q4 (Lightning) child exited 1: boom")
    assert os.path.isfile(cand(run_dir, 1))
```

**Edit 3.8** `tests/test_seed_edit_tool.py`: replace

```python
    started = time.monotonic()
    code, run_dir = run_tool(env, "--candidates", "3", "--seed", "100", model="qwen", run=R2)
    assert code == 1 and time.monotonic() - started < 20
    record = record_of(run_dir)
    assert statuses(run_dir) == ["failed"] * 3
    assert record["error"] == "mflux q4 child timed out after %d s" % tool.CHILD_TIMEOUT_S
    assert tool.CHILD is None
    env["mp"].setattr(tool, "CHILD_TIMEOUT_S", 3600)
    stub_config(py, {"kill_after": 1})
    code, run_dir = run_tool(env, "--candidates", "3", "--seed", "100", model="qwen", run=R3)
    assert code == 1
    record = record_of(run_dir)
    assert statuses(run_dir) == ["ok", "failed", "failed"]
    assert (record["state"], record["error"]) == ("failed", "mflux q4 child exited -9: killed")
    assert tool.CHILD is None
```

with

```python
    started = time.monotonic()
    code, run_dir = run_tool(env, *q4, model="qwen", run=R2)
    assert code == 1 and time.monotonic() - started < 20
    record = record_of(run_dir)
    assert statuses(run_dir) == ["failed"] * 3
    assert record["error"] == "Qwen-Image-Edit-2511 q4 (Lightning) child timed out after %d s" % tool.CHILD_TIMEOUT_S
    assert tool.CHILD is None
    env["mp"].setattr(tool, "CHILD_TIMEOUT_S", 3600)
    stub_config(py, {"kill_after": 1})
    code, run_dir = run_tool(env, *q4, model="qwen", run=R3)
    assert code == 1
    record = record_of(run_dir)
    assert statuses(run_dir) == ["ok", "failed", "failed"]
    assert (record["state"], record["error"]) == ("failed", "Qwen-Image-Edit-2511 q4 (Lightning) child exited -9: killed")
    assert tool.CHILD is None
```

**Edit 3.9** `tests/test_seed_edit_tool.py`: replace

```python
    stub = qwenedit_stub(env, {"blocked": [2]})
    code, run_dir = run_tool(env, "--candidates", "2", "--seed", "100", model="qwen")
    assert code == 0
```

with

```python
    stub = qwenedit_stub(env, {"blocked": [2]})
    code, run_dir = run_tool(env, "--qwen-model", "qwen2511-bf16", "--candidates", "2", "--seed", "100", model="qwen")
    assert code == 0
```

**Edit 3.10** `tests/test_seed_edit_tool.py`: replace

```python
    assert [os.path.isfile(cand(run_dir, n)) for n in (1, 2)] == [True, False]
    assert record_of(run_dir)["backend"] == "diffusers-bf16"
    assert "seed-edit: backend diffusers-bf16 (70.0 GiB available)" in capsys.readouterr().out.splitlines()
    assert env["calls"]["safety"] == []
```

with

```python
    assert [os.path.isfile(cand(run_dir, n)) for n in (1, 2)] == [True, False]
    assert record_of(run_dir)["backend"] == "diffusers"
    assert ("seed-edit: backend diffusers (Qwen-Image-Edit-2511 bf16 (Lightning, diffusers); LoRAs none; 8 steps; "
            "scheduler default)") in capsys.readouterr().out.splitlines()
    assert env["calls"]["safety"] == []
```

**Edit 3.11** `tests/test_seed_edit_tool.py`: replace

```python
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
```

with

```python
    mflux_weights(env)
    got = tool.probe()
    assert got["zimage"] == {"ok": True, "reason": None, "backend": "zimage"}
    assert (got["qwen"]["ok"], got["qwen"]["reason"], got["qwen"]["models"]["qwen2511-q4"]) == (
        True, None, {"ok": True, "reason": None})
    assert "backend" not in got["qwen"]
    assert tool.main(["--probe"]) == 0
    assert capsys.readouterr().out == json.dumps(tool.probe(), sort_keys=True) + "\n"
    bf16_cache(env)
    mp.setattr(tool, "total_gib", lambda: 128.0)
    assert tool.probe()["qwen"]["models"]["qwen2511-bf16"] == {"ok": True, "reason": None}
    missing = os.path.join(env["tmp"], "none", "bin", "python")
    mp.setenv("SEED_EDIT_MFLUX_PYTHON", missing)
    assert tool.probe()["qwen"]["models"]["qwen2511-q4"] == {
        "ok": False, "reason": "no mflux venv at %s (run bin/seed-edit-setup)" % missing}
    proc = subprocess.run([sys.executable, "-X", "importtime", TOOL_PATH, "--probe"], capture_output=True,
```

**Edit 3.12** `tests/test_seed_edit_tool.py`: replace

```python
        assert getattr(tool, name) == getattr(character_dataset, name), name
    assert tool.BF16_MIN_AVAIL_GIB == character_dataset.EDIT_MIN_AVAIL_GIB
    assert tool.ZIMAGE_MIN_AVAIL_GIB == character_dataset.GENERATE_MIN_AVAIL_GIB
```

with

```python
        assert getattr(tool, name) == getattr(character_dataset, name), name
    assert seedgen.qwen_model("qwen2511-bf16")["memory_gib"] == character_dataset.EDIT_MIN_AVAIL_GIB
    assert tool.ZIMAGE_MIN_AVAIL_GIB == character_dataset.GENERATE_MIN_AVAIL_GIB
```

**Edit 3.13** `tests/test_seed_edit_tool.py`: replace

```python
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

with

```python
    stub_config(py, {"prefix": bar})
    code, run_dir = run_tool(env, "--qwen-model", "qwen2511-q4", "--candidates", "2", "--seed", "1", model="qwen", run=R1)
    assert code == 0 and statuses(run_dir) == ["ok", "ok"]
    assert "100%|##########| 8/8 [00:01<00:00]\nseed-edit-child done 1 1.0\n" in capsys.readouterr().out
    bf16_cache(env)
    env["mp"].setattr(tool, "avail_gib", lambda: 70.0)
    qwenedit_stub(env, {"prefix": "Loading pipeline components...: 100%|##########| 5/5\r"})
    code, run_dir = run_tool(env, "--qwen-model", "qwen2511-bf16", "--candidates", "2", "--seed", "1", model="qwen",
                             run=R2)
    assert code == 0 and statuses(run_dir) == ["ok", "ok"]
    assert record_of(run_dir)["backend"] == "diffusers"


# --- Review Focus 1: a 2.1 run gets a canvas of multiples of 32 from a source that is not one -------------

def test_sq_review_focus_1_the_qwen21_canvas_reaches_the_child(env):
    tool = env["tool"]
    py, _venv = mflux_venv(env)
    install_model(env, "qwen21-q4")
    install_model(env, "qwen2511-q4")
    zimage_cache(env)
    source = png(os.path.join(env["tmp"], "phone.png"), (800, 600))
    want = {"qwen21-q4": (800, 576), "qwen2511-q4": (800, 592)}
    for i, model_id in enumerate(("qwen21-q4", "qwen2511-q4")):
        code, run_dir = run_tool(env, "--qwen-model", model_id, "--candidates", "1", model="qwen", source=source,
                                 run=(R1, R2)[i])
        assert code == 0, model_id
        spec = stub_calls(py)[-1]["spec"]
        assert (spec["width"], spec["height"]) == want[model_id]
        assert record_of(run_dir)["size"] == {"width": want[model_id][0], "height": want[model_id][1]}
        with Image.open(cand(run_dir, 1)) as img:
            assert img.size == want[model_id]
    code, run_dir = run_tool(env, "--candidates", "1", source=source, run=R3)
    assert code == 0 and record_of(run_dir)["size"] == {"width": 800, "height": 592}


# --- Review Focus 3: a Qwen job queued before the registry still runs -------------------------------------------

def test_sq_review_focus_3_a_job_queued_before_the_registry(env):
    tool = env["tool"]
    py, _venv = mflux_venv(env)
    snapshot, lightning = mflux_weights(env)
    ws = os.path.join(env["tmp"], "ws")
    run_dir = os.path.join(ws, "generated", "seeds", "runs", RUN)
    png(os.path.join(run_dir, "source.png"), (300, 200))
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": "seed-edit.run.v1", "run": RUN, "created": "2026-11-02T14:15:00Z", "state": "queued",
                   "prompt": PROMPT, "model": "qwen", "backend": None, "job": "20261102-141500-a1b2"}, f)
    fields = {"ws": ws, "run": RUN, "source_file": "source.png", "prompt": PROMPT, "model": "qwen", "strength": None,
              "candidates": 1, "seed": 5, "source": None}
    argv = lib.seed_edit_argv(fields, ws)
    assert "--qwen-model" not in argv
    assert tool.main(argv[2:]) == 0
    record = record_of(run_dir)
    assert (record["state"], record["backend"], record["job"]) == ("done", "mflux", "20261102-141500-a1b2")
    assert {k: record[k] for k in ("qwen_model", "loras", "steps", "scheduler")} == seedgen.qwen_settings(
        "qwen2511-q4", [])
    spec = stub_calls(py)[0]["spec"]
    assert (spec["family"], spec["model_path"], spec["lora_paths"], spec["steps"]) == (
        "qwen2511", snapshot, [lightning], 8)


# --- Review Focus 5: the selection survives the request -> argv -> tool round trip ------------------------------

ROUND_TRIPS = [("qwen21-q4", [{"id": "viggle-turbo", "scale": 2}, {"id": "uncensored", "scale": 1e-06}]),
               ("qwen21-q8", [{"id": "uncensored", "scale": 0.1 + 0.2}]), ("qwen21-bf16", []), ("qwen2511-q4", []),
               ("qwen2511-bf16", []), ("qwen21-q4", None), (None, None)]


def test_sq_review_focus_5_the_selection_round_trip(env):
    tool = env["tool"]
    ws = os.path.join(env["tmp"], "ws")
    prompt = "make it night --qwen-model qwen21-bf16 --lora viggle-turbo=2 --model zimage"
    for model_id, loras in ROUND_TRIPS:
        body = {"prompt": prompt, "model": "qwen", "source": {"upload_id": UP}, "qwen_model": model_id, "loras": loras}
        clean, error = seedgen.validate_run_request(body)
        assert error is None, (model_id, loras)
        fields = {"ws": ws, "run": RUN, "source_file": "source.png", "prompt": prompt, "model": "qwen",
                  "strength": None, "qwen_model": clean["qwen_model"], "loras": clean["loras"], "candidates": 2,
                  "seed": 9, "source": clean["source"]}
        opts = tool.check_args(tool.parse(lib.seed_edit_argv(fields, ws)[2:]))
        assert opts["prompt"] == prompt
        assert (opts["qwen_model"], opts["loras"]) == (clean["qwen_model"], clean["loras"]), (model_id, loras)
        assert seedgen.qwen_settings(opts["qwen_model"], opts["loras"]) == seedgen.qwen_settings(
            clean["qwen_model"], clean["loras"])

```

**Edit 3.14** `tests/test_seed_edit_tool.py`: replace

```python
    tool = load_tool()
    for name in ("Q4_REPO", "EDIT_LORA_REPO", "EDIT_LORA_FILE"):
        assert '%s = "%s"' % (name, getattr(tool, name)) in source, name
    for name in ("mflux_version", "find_lightning"):
```

with

```python
    tool = load_tool()
    for name, value in (("Q4_REPO", seedgen.qwen_model("qwen2511-q4")["repo"]), ("EDIT_LORA_REPO", tool.EDIT_LORA_REPO),
                        ("EDIT_LORA_FILE", tool.EDIT_LORA_FILE)):
        assert '%s = "%s"' % (name, value) in source, name
    for name in ("mflux_version", "find_lightning"):
```

- [ ] **Step 2: Run the two seed test files; the new and re-baselined tests fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedmodels-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py 2>&1 | tail -1
```

Expected: `45 failed, 124 passed`. The failing tests are exactly: `test_sgt2_a_zimage_run`, `test_sgt7_preflight_refusals`, `test_sqt1_the_canvas_for_qwen21`, `test_sqt2_bad_qwen_arguments` (23 cases), `test_sqt2_the_cleaned_qwen_options`, `test_sqt3_the_pinned_lookups`, `test_sqt4_the_probe`, `test_sqt5_the_mflux_selection` (5 cases), `test_sqt6_content_safety_on_every_candidate_of_every_model`, `test_sqt7_run_time_refusals`, `test_sgt9_the_mflux_child_screened_in_the_parent`, `test_sgt10_the_mflux_child_fails_or_times_out`, `test_sgt11_the_bf16_child`, `test_sgt13_the_probe`, `test_sg_review_focus_4_progress_bars_in_child_lines`, `test_sq_review_focus_1_the_qwen21_canvas_reaches_the_child`, `test_sq_review_focus_3_a_job_queued_before_the_registry`, `test_sq_review_focus_5_the_selection_round_trip`, `test_sgt34_the_new_python_files_and_the_tool_imports`.

- [ ] **Step 3: Implement.** Make these edits in order.

**Edit 3.15** `bin/seed-edit`: replace

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

```

with

```python
#!/usr/bin/env python3
"""seed-edit -- edit one source image into 1 to 4 seed candidates with Z-Image img2img or a Qwen
registry model (docs/superpowers/specs/2026-11-02-seed-generator-design.md, Section 2, amended by
docs/superpowers/specs/2026-11-02-seed-models-design.md, Section 3).

  bin/seed-edit --source PATH --prompt TEXT --model zimage|qwen [--qwen-model ID] [--lora ID=SCALE ...]
                [--strength S] [--candidates N] [--seed N] --run-dir DIR
  bin/seed-edit --probe

The movie-ui runs it as a queued GPU job of kind seed-edit; it also runs by hand. Candidate i
(1-based) uses seed + i and lands in <run dir>/cand_NN.png. --strength (0.10 to 0.90, default
0.45) is for zimage only; --candidates defaults to 4; a missing --seed is drawn at random.
--qwen-model is one of movie_ui_seedgen's registry IDs: qwen21-q4, qwen21-q8, qwen21-bf16
(Qwen-Image-2.1 through mflux), qwen2511-q4 (Qwen-Image-Edit-2511 q4 through mflux, Lightning
built in) or qwen2511-bf16 (the unchanged character_dataset.py qwenedit child); without it
--model qwen runs qwen2511-q4, as a job queued before the registry did. Each --lora ID=SCALE
(uncensored, viggle-turbo; 0 < SCALE <= 2) must be of the model's family; viggle-turbo sets 6
steps and scheduler viggle_turbo. Every candidate of every model is screened with content
safety before it gets its final name. --probe prints one JSON line {"qwen": {"ok", "reason",
"models": {ID: {"ok", "reason"}}, "loras": {ID: {"ok", "reason"}}}, "zimage": {"backend", "ok",
"reason"}} and loads nothing.

```

**Edit 3.16** `bin/seed-edit`: replace

```python
Environment: SEED_EDIT_MFLUX_PYTHON (default ~/mflux-edit/.venv/bin/python),
SEED_EDIT_QWEN_Q4_DIR (a local q4 model directory whose name contains qwen-image-edit-2511),
SEED_EDIT_LIGHTNING_FILE (a local Lightning LoRA file), SEED_EDIT_QWENEDIT_SCRIPT (default
<ws>/character_dataset.py), HF_HUB_CACHE and HF_HOME (the default hub), Z_IMAGE_HF_HOME (the
Z-Image hub, through movie_ui_lib.zimage_hub) and HOME.

Python 3.9 and 3.13. The top level imports only the standard library and movie_ui_lib; PIL,
psutil, torch, z_image_skill, content_safety and character_dataset are imported inside the
functions that use them.
"""
```

with

```python
Environment: SEED_EDIT_MFLUX_PYTHON (default ~/mflux-edit/.venv/bin/python),
SEED_EDIT_QWENEDIT_SCRIPT (default <ws>/character_dataset.py), HF_HUB_CACHE and HF_HOME (the
default hub), Z_IMAGE_HF_HOME (the Z-Image hub, through movie_ui_lib.zimage_hub) and HOME. The
mflux weights and LoRAs are looked up only at their pinned revisions, in the Z-Image hub and then
the default hub.

Python 3.9 and 3.13. The top level imports only the standard library, movie_ui_lib and
movie_ui_seedgen; PIL, psutil, torch, z_image_skill, content_safety and character_dataset are
imported inside the functions that use them.
"""
```

**Edit 3.17** `bin/seed-edit`: replace

```python
import movie_ui_lib as lib  # noqa: E402

```

with

```python
import movie_ui_lib as lib  # noqa: E402
import movie_ui_seedgen as seedgen  # noqa: E402

```

**Edit 3.18** `bin/seed-edit`: replace

```python
ZIMAGE_MIN_AVAIL_GIB = 20.0      # character_dataset.GENERATE_MIN_AVAIL_GIB
BF16_MIN_AVAIL_GIB = 64.0        # character_dataset.EDIT_MIN_AVAIL_GIB
MFLUX_MIN_AVAIL_GIB = 32.0
AVAIL_WAIT_S = 600               # character_dataset.AVAIL_WAIT_S
```

with

```python
ZIMAGE_MIN_AVAIL_GIB = 20.0      # character_dataset.GENERATE_MIN_AVAIL_GIB
AVAIL_WAIT_S = 600               # character_dataset.AVAIL_WAIT_S
```

**Edit 3.19** `bin/seed-edit`: replace

```python
EDIT_TRUE_CFG = 1.0
Q4_REPO = "mflux-community/qwen-image-edit-2511-mflux-q4"
Q4_NAME_PART = "qwen-image-edit-2511"
MFLUX_MIN_VERSION = (0, 22, 0)
MFLUX_GUIDANCE = 1.0
DEFAULT_MFLUX_PYTHON = "~/mflux-edit/.venv/bin/python"   # expanded at use
SAFETY_SKILL = "seed_edit"
BACKEND_LABELS = {"zimage": "Z-Image", "diffusers-bf16": "diffusers bf16", "mflux-q4": "mflux q4"}

```

with

```python
EDIT_TRUE_CFG = 1.0
MFLUX_MIN_VERSION = (0, 24, 0)
MFLUX_GUIDANCE = 1.0
DEFAULT_MFLUX_PYTHON = "~/mflux-edit/.venv/bin/python"   # expanded at use
SAFETY_SKILL = "seed_edit"
BACKEND_LABELS = {"zimage": "Z-Image", "mflux": "mflux", "diffusers": "diffusers"}

```

**Edit 3.20** `bin/seed-edit`: replace

```python
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
```

with

```python
    parser = argparse.ArgumentParser(prog="seed-edit", description="Edit one source image into 1 to 4 "
                                     "seed candidates (Z-Image img2img or a Qwen registry model).")
    for name in ("--source", "--prompt", "--model", "--strength", "--candidates", "--seed", "--run-dir"):
        parser.add_argument(name, type=str)
    parser.add_argument("--qwen-model", type=str)
    parser.add_argument("--lora", type=str, action="append")
    parser.add_argument("--probe", action="store_true")
    return parser.parse_args(argv)


def check_loras(values, entry):
    """Seed models SQ12 rows 12-16 for each --lora value in the order given: the cleaned
    [{"id", "scale"}] in registry order, or Refusal."""
    loras = []
    for value in values:
        match = re.match(r"^([a-z0-9-]+)=(.*)$", value)
        if not match:
            raise Refusal("--lora must be ID=SCALE (got %s)" % value)
        lora_id, text = match.group(1), match.group(2)
        if lora_id not in seedgen.QWEN_LORA_IDS:
            raise Refusal("--lora: unknown LoRA %s; known: %s" % (lora_id, ", ".join(seedgen.QWEN_LORA_IDS)))
        if any(item["id"] == lora_id for item in loras):
            raise Refusal("--lora %s is given twice" % lora_id)
        lora = seedgen.qwen_lora(lora_id)
        if lora["family"] != entry["family"]:
            raise Refusal("--lora %s is for %s, not %s" % (lora_id, seedgen.QWEN_FAMILIES[lora["family"]],
                                                           entry["label"]))
        try:
            scale = float(text)
        except ValueError:
            scale = None
        if scale is None or not 0 < scale <= seedgen.SCALE_MAX:
            raise Refusal("--lora %s scale must be a number above 0 and at most 2" % lora_id)
        loras.append({"id": lora_id, "scale": scale})
    return seedgen.registry_order(loras)


def check_args(args):
    """SG4 and seed models SQ12: the cleaned options (None for --probe), or Refusal with the first
    failing rule's text."""
    given = (args.source, args.prompt, args.model, args.strength, args.candidates, args.seed, args.run_dir,
             args.qwen_model, args.lora)
    if args.probe:
```

**Edit 3.21** `bin/seed-edit`: replace

```python
            raise Refusal("--strength must be a number from 0.10 to 0.90")
    if args.seed is None:
```

with

```python
            raise Refusal("--strength must be a number from 0.10 to 0.90")
    if args.model == "zimage":
        if args.qwen_model is not None:
            raise Refusal("--qwen-model is only for --model qwen")
        if args.lora is not None:
            raise Refusal("--lora is only for --model qwen")
        qwen_model, loras = None, []
    else:
        qwen_model = seedgen.LEGACY_QWEN_MODEL if args.qwen_model is None else args.qwen_model
        if qwen_model not in seedgen.QWEN_MODEL_IDS:
            raise Refusal("--qwen-model must be one of %s" % ", ".join(seedgen.QWEN_MODEL_IDS))
        loras = check_loras(args.lora or [], seedgen.qwen_model(qwen_model))
    if args.seed is None:
```

**Edit 3.22** `bin/seed-edit`: replace

```python
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
```

with

```python
    return {"source": args.source, "prompt": args.prompt, "model": args.model, "strength": strength,
            "candidates": candidates, "seed": seed, "run_dir": os.path.abspath(args.run_dir),
            "qwen_model": qwen_model, "loras": loras}


# ---------------------------------------------------------------------------
# The source and its size (SG8-SG10)
# ---------------------------------------------------------------------------

def canvas(w0, h0, multiple=MULTIPLE):
    """SG8, seed models SQ14: the (W, H) edit canvas of a w0 x h0 source, each side floored to a
    multiple of multiple, or Refusal when a side is under MIN_SIDE."""
    longest = max(w0, h0)
    if longest <= LONG_EDGE:
        w, h = w0, h0
    else:
        w, h = w0 * LONG_EDGE // longest, h0 * LONG_EDGE // longest
    width, height = w // multiple * multiple, h // multiple * multiple
    if width < MIN_SIDE or height < MIN_SIDE:
```

**Edit 3.23** `bin/seed-edit`: replace

```python
    w0, h0 = image.size
    width, height = canvas(w0, h0)
    rec["size"] = {"width": width, "height": height}
```

with

```python
    w0, h0 = image.size
    width, height = canvas(w0, h0, seedgen.canvas_multiple(ctx["opts"]["model"], ctx["opts"]["qwen_model"]))
    rec["size"] = {"width": width, "height": height}
```

**Edit 3.24** `bin/seed-edit`: replace

```python

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

```

with

```python

def pinned_snapshot(repo, revision, hubs):
    """(snapshot, repo_dir) of the first hub holding <repo dir>/snapshots/<revision> as a directory,
    else (None, None)."""
    for hub in hubs:
        repo_dir = os.path.join(hub, lib.repo_dir_name(repo))
        snapshot = os.path.join(repo_dir, "snapshots", revision)
        if os.path.isdir(snapshot):
            return snapshot, repo_dir
    return None, None


def pinned_file(repo, revision, name, hubs):
    """<hub>/<repo dir>/snapshots/<revision>/<name> in the first hub where its realpath is a non-empty
    regular file (the snapshot path is returned, not the realpath), else None."""
    for hub in hubs:
        path = os.path.join(hub, lib.repo_dir_name(repo), "snapshots", revision, name)
        real = os.path.realpath(path)
        if os.path.isfile(real) and os.path.getsize(real) > 0:
            return path
    return None


def weights_problem(entry, hubs):
    """(problem, model dir, built-in LoRA path) of an mflux registry model in hubs. problem is None
    when the pinned snapshot is intact (for qwen21 also with its component configs and processor/)
    and the built-in LoRA, if any, is present."""
    where = " or ".join(hubs)
    setup = "(run bin/seed-edit-setup --model %s)" % entry["id"]
    snapshot, repo_dir = pinned_snapshot(entry["repo"], entry["revision"], hubs)
    if snapshot is None:
        return "%s@%s is not in %s %s" % (entry["repo"], entry["revision"][:12], where, setup), None, None
    problems = list(lib.intact_scan(snapshot, repo_dir)[0])
    if entry["family"] == "qwen21":
        problems += ["missing %s" % rel for rel in seedgen.QWEN21_REQUIRED
                     if not os.path.isfile(os.path.join(snapshot, rel))]
        if not os.path.isdir(os.path.join(snapshot, "processor")):
            problems.append("missing processor/")
    if problems:
        return "%s: %s %s" % (entry["repo"], "; ".join(problems), setup), None, None
    lora = entry["builtin_lora"]
    lora_path = None
    if lora is not None:
        lora_path = pinned_file(lora["repo"], lora["revision"], lora["file"], hubs)
        if lora_path is None:
            return "Lightning LoRA %s is not in %s %s" % (lora["file"], where, setup), None, None
    return None, snapshot, lora_path


def qwen_hubs():
    """Seed models SQ16: the hubs searched for the mflux weights and LoRAs, in order."""
    return [lib.zimage_hub(), default_hub()]


def mflux_env_problem():
    """Seed models SQ16: None when the mflux venv holds mflux 0.24.0 or newer, else the first problem."""
    py = mflux_python()
    if not os.access(py, os.X_OK):
        return "no mflux venv at %s (run bin/seed-edit-setup)" % py
    venv = os.path.dirname(os.path.dirname(py))
    count, best = mflux_version(venv)
    if count == 0:
        return "mflux is not installed in %s (run bin/seed-edit-setup)" % venv
    if best is None:
        return "cannot read the mflux version in %s" % venv
    if best[0] < MFLUX_MIN_VERSION:
        return "mflux %s in %s is older than 0.24.0 (run bin/seed-edit-setup)" % (best[1], venv)
    return None


def lora_problem(lora, hubs):
    """Seed models SQ16: (None, snapshot path) of a registry LoRA's pinned file, else (problem, None)."""
    path = pinned_file(lora["repo"], lora["revision"], lora["file"], hubs)
    if path is None:
        return ("%s is not in %s (run bin/seed-edit-setup --lora %s)" % (lora["file"], " or ".join(hubs), lora["id"]),
                None)
    return None, path


def qwen_model_problem(entry):
    """Seed models SQ16: (problem, paths) of a registry model; paths is {"model_path", "builtin_lora"}
    for a ready mflux entry, else {}."""
    if entry["backend"] == "diffusers":
        return bf16_problem(), {}
    problem = mflux_env_problem()
    if problem is not None:
        return problem, {}
    problem, model_path, builtin_lora = weights_problem(entry, qwen_hubs())
    if problem is not None:
        return problem, {}
    problem = modules_problem(["PIL", "psutil", "torch", "transformers"])
    if problem is not None:
        return problem, {}
    return None, {"model_path": model_path, "builtin_lora": builtin_lora}


def memory_problem(entry):
    """Seed models SQ16: None when this host's total memory reaches the entry's floor, else why not."""
    t = total_gib()
    if t is None:
        return "cannot read this host's memory size"
    if t < entry["memory_gib"]:
        return "needs a host with at least %g GiB of memory (this host has %.1f GiB)" % (entry["memory_gib"], t)
    return None


def probe():
    """SG15, seed models SQ18: {"zimage": {"ok", "reason", "backend"}, "qwen": {"ok", "reason",
    "models", "loras"}}; each registry model is judged by the host's total memory first, then by
    what is installed. Loads no model and starts no process."""
    p = zimage_problem()
    hubs = qwen_hubs()
    models = {}
    for entry in seedgen.QWEN_MODELS:
        reason = memory_problem(entry) or qwen_model_problem(entry)[0]
        models[entry["id"]] = {"ok": reason is None, "reason": reason}
    loras = {}
    for lora in seedgen.QWEN_LORAS:
        reason = lora_problem(lora, hubs)[0]
        loras[lora["id"]] = {"ok": reason is None, "reason": reason}
    ok = any(m["ok"] for m in models.values())
    reason = None if ok else "; ".join("%s: %s" % (i, models[i]["reason"]) for i in seedgen.QWEN_MODEL_IDS)
    return {"zimage": {"ok": p is None, "reason": p, "backend": "zimage" if p is None else None},
            "qwen": {"ok": ok, "reason": reason, "models": models, "loras": loras}}

```

**Edit 3.25** `bin/seed-edit`: replace

```python
def preflight(ctx):
    """SG13: disk, busy GPU, the backend (SG14), the memory floor; (backend, why) or Refusal."""
    run_dir = ctx["dir"]
```

with

```python
def preflight(ctx):
    """SG13 and seed models SQ21: disk, busy GPU, the selected model and LoRAs, the memory floor;
    (backend, why) or Refusal. Sets ctx["label"], and for qwen ctx["entry"], ctx["paths"] and
    ctx["lora_paths"] (registry order)."""
    run_dir = ctx["dir"]
```

**Edit 3.26** `bin/seed-edit`: replace

```python
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

```

with

```python
        raise Refusal("another GPU process is running (pid %s: %s); try again when it ends" % (busy[0], busy[1]))
    opts = ctx["opts"]
    if opts["model"] == "zimage":
        problem = zimage_problem()
        if problem is not None:
            raise Refusal("Z-Image is unavailable: %s" % problem)
        ctx["label"] = BACKEND_LABELS["zimage"]
        wait_for_memory(ZIMAGE_MIN_AVAIL_GIB, ctx["label"])
        return "zimage", "Z-Image img2img"
    entry = seedgen.qwen_model(opts["qwen_model"])
    ctx["entry"], ctx["label"] = entry, entry["label"]
    problem, paths = qwen_model_problem(entry)
    if problem is not None:
        raise Refusal("%s is unavailable: %s" % (entry["label"], problem))
    lora_paths = []
    for item in opts["loras"]:
        lora = seedgen.qwen_lora(item["id"])
        problem, path = lora_problem(lora, qwen_hubs())
        if problem is not None:
            raise Refusal("LoRA %s is unavailable: %s" % (lora["label"], problem))
        lora_paths.append(path)
    wait_for_memory(entry["memory_gib"], entry["label"])
    ctx["paths"], ctx["lora_paths"] = paths, lora_paths
    settings = seedgen.qwen_settings(entry["id"], opts["loras"])
    listed = ", ".join("%s@%g" % (item["id"], item["scale"]) for item in settings["loras"]) or "none"
    return entry["backend"], "%s; LoRAs %s; %d steps; scheduler %s" % (
        entry["label"], listed, settings["steps"], settings["scheduler"] or "default")

```

**Edit 3.27** `bin/seed-edit`: replace

```python
            "state": "running", "prompt": opts["prompt"], "model": opts["model"], "backend": None,
            "strength": opts["strength"], "seed": opts["seed"], "size": None, "source_size": None,
            "source": None, "source_origin": origin, "job": job, "error": None,
```

with

```python
            "state": "running", "prompt": opts["prompt"], "model": opts["model"], "backend": None,
            "strength": opts["strength"], "seed": opts["seed"],
            **seedgen.qwen_settings(opts["qwen_model"], opts["loras"]), "size": None, "source_size": None,
            "source": None, "source_origin": origin, "job": job, "error": None,
```

**Edit 3.28** `bin/seed-edit`: replace

```python

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
```

with

```python

    return run_qwen_child(ctx, ctx["label"], [sys.executable, script, "qwenedit", "--spec", spec_path],
                          dict(os.environ, PYTHONUNBUFFERED="1"), handle)


def run_mflux(ctx):
    """SG20, seed models SQ23: seed_edit_mflux_child.py under the mflux venv with the registry
    family, the pinned local paths (the built-in Lightning LoRA, then the selected LoRAs in registry
    order) and the run's steps and scheduler; this process screens every pending image before it
    gets its final name. Returns None or the SG17 text."""
    import content_safety
    from PIL import Image
    work, opts, rec, entry = ctx["work"], ctx["opts"], ctx["record"], ctx["entry"]
    builtin = entry["builtin_lora"]
    lora_paths = ([ctx["paths"]["builtin_lora"]] if builtin is not None else []) + ctx["lora_paths"]
    lora_scales = ([builtin["scale"]] if builtin is not None else []) + [item["scale"] for item in opts["loras"]]
    spec_path = os.path.join(work, "mflux_spec.json")
    lib.write_json_atomic(spec_path, {
        "family": entry["family"], "model_path": ctx["paths"]["model_path"], "lora_paths": lora_paths,
        "lora_scales": lora_scales, "prompt": opts["prompt"], "source": os.path.join(work, "source.png"),
        "width": ctx["width"], "height": ctx["height"], "steps": rec["steps"], "guidance": MFLUX_GUIDANCE,
        "scheduler": rec["scheduler"],
        "jobs": [{"n": c["n"], "seed": c["seed"], "output_path": pending_path(ctx, c["n"])}
```

**Edit 3.29** `bin/seed-edit`: replace

```python
    argv = [mflux_python(), os.path.join(WS, "seed_edit_mflux_child.py"), "--spec", spec_path]
    return run_qwen_child(ctx, "mflux q4", argv, dict(os.environ, PYTHONUNBUFFERED="1", HF_HUB_OFFLINE="1"),
                          handle)
```

with

```python
    argv = [mflux_python(), os.path.join(WS, "seed_edit_mflux_child.py"), "--spec", spec_path]
    return run_qwen_child(ctx, ctx["label"], argv, dict(os.environ, PYTHONUNBUFFERED="1", HF_HUB_OFFLINE="1"),
                          handle)
```

**Edit 3.30** `bin/seed-edit`: replace

```python
    say("seed-edit: backend %s (%s)" % (backend, why))
    runner = {"zimage": run_zimage, "diffusers-bf16": run_bf16, "mflux-q4": run_mflux}[backend]
    try:
        failure = runner(ctx)
    except Exception as e:
        failure = "%s failed on candidate %d: %s: %s" % (BACKEND_LABELS[backend], first_pending(ctx),
                                                         type(e).__name__, e)
    fail_rest(ctx)
```

with

```python
    say("seed-edit: backend %s (%s)" % (backend, why))
    runner = {"zimage": run_zimage, "diffusers": run_bf16, "mflux": run_mflux}[backend]
    try:
        failure = runner(ctx)
    except Exception as e:
        failure = "%s failed on candidate %d: %s: %s" % (ctx["label"], first_pending(ctx), type(e).__name__, e)
    fail_rest(ctx)
```

- [ ] **Step 4: Run the tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedmodels-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py 2>&1 | tail -1
```

Expected: `169 passed`. Run the compile check with `FILES` = `bin/seed-edit tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py`; expected `compiled 3` twice. Then run the gate block ("Between tasks") with `N=3`. Expected: `GATE PASS`, `lost 1 (listed 1, unexpected 0)` with `LOST tests/test_seed_edit_tool.py::test_sgt8_choose_qwen listed`, `new tests 169, not passing 0`, `baseline failures still failing 2 of 2`, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedmodels-wt/qwen-agent-workspace
git add bin/seed-edit tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py
git diff --cached --name-only    # expected: exactly these 3 paths, with the qwen-agent-workspace/ prefix
git commit -m "feat(seed-edit): explicit Qwen model and LoRA selection, the 2.1 canvas, pinned lookups, the per-model probe and preflight, the family-aware child spec (SQ12-SQ27; SQT1-SQT7)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `seed_edit_mflux_child.py`: family dispatch, LoRA lists, the scheduler, the 0.24.0 gate, RGB save (SQ2, SQ28, SQ29; SQT8, SQT9)

This task implements:
- SQ28's body as written (whole file replaced; `parse_version` and `exit_with_parent` unchanged), SQ29's exit codes and the rewritten docstring.
- Tests: SQT8 (in-process with fake `mlx`, `mlx.core`, `ModelConfig` and the two classes; the real mflux and mlx are never imported) and SQT9; SGT15 re-baselined (PR2).

**Files:**
- Replace: `seed_edit_mflux_child.py` (Write)
- Modify: `tests/test_seed_edit_tool.py` (SGT15; SQT8, SQT9 after it)

**Interfaces:**
- Consumes:
  - Task 3's child spec shape and `tool.MFLUX_MIN_VERSION`; Task 1's `QWEN_MODELS[...]["mflux_class"]`/`["mflux_config"]`, `QWEN_FAMILIES`.
- Produces:
  - `seed_edit_mflux_child.FAMILIES = {family: (module, class name, ModelConfig method)}`, `MIN_VERSION = (0, 24, 0)`, `main(argv=None) -> 0, 2 (or 3 from the watcher)`.

- [ ] **Step 1: Write the failing tests.** Make these edits in order (Edit tool; each old text occurs exactly once at its turn).

**Edit 4.1** `tests/test_seed_edit_tool.py`: replace

```python
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
```

with

```python
        assert child.parse_version(text) == want, text
    assert child.parse_version("0.23.9") < child.MIN_VERSION <= child.parse_version("0.24.0")
    monkeypatch.setattr(child, "exit_with_parent", lambda poll_s=2.0: None)
    monkeypatch.setattr(child.importlib.metadata, "version", lambda name: "0.23.0")
    missing = os.path.join(str(tmp_path), "missing-spec.json")
    assert child.main(["--spec", missing]) == 2
    assert capsys.readouterr().out == ("seed-edit-child: mflux 0.23.0 is missing or older than 0.24.0; refusing "
                                       "(run bin/seed-edit-setup)\n")

    def not_installed(name):
        raise child.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(child.importlib.metadata, "version", not_installed)
    assert child.main(["--spec", missing]) == 2
    assert capsys.readouterr().out.startswith("seed-edit-child: mflux None is missing or older than 0.24.0")
    for text in ("bake_lora=False", "quantize=None", '.convert("RGB").save('):
        assert text in source, text


# --- SQT8 (seed models SQ28, SQ29): the child in-process with fake mlx and mflux modules --------------------

def child_fakes(monkeypatch):
    """sys.modules fakes of mlx, mlx.core, ModelConfig's module and the two FAMILIES classes; returns the
    record {"init": [(class name, kwargs)], "generate": [(class name, kwargs)]}."""
    record = {"init": [], "generate": []}
    core = types.ModuleType("mlx.core")
    core.get_peak_memory = lambda: 2 ** 30
    mlx = types.ModuleType("mlx")
    mlx.core = core
    config_module = types.ModuleType("mflux.models.common.config.model_config")

    class ModelConfig(object):
        def __init__(self, name):
            self.model_name = name

        @staticmethod
        def qwen_image_21():
            return ModelConfig("Qwen/Qwen-Image-2.1")

        @staticmethod
        def qwen_image_edit_2511():
            return ModelConfig("Qwen/Qwen-Image-Edit-2511")

    config_module.ModelConfig = ModelConfig

    def fake_class(name):
        class Fake(object):
            def __init__(self, **kwargs):
                record["init"].append((name, kwargs))

            def generate_image(self, **kwargs):
                record["generate"].append((name, kwargs))
                return types.SimpleNamespace(image=Image.new("RGBA", (kwargs["width"], kwargs["height"]),
                                                             (0, 0, 200, 128)))
        return Fake

    modules = {"mlx": mlx, "mlx.core": core, "mflux.models.common.config.model_config": config_module}
    for family, (module_name, class_name, _config) in (
            ("qwen21", ("mflux.models.qwen21.variants.edit.qwen_image_21_edit", "QwenImage21Edit", None)),
            ("qwen2511", ("mflux.models.qwen.variants.edit.qwen_image_edit", "QwenImageEdit", None))):
        module = types.ModuleType(module_name)
        setattr(module, class_name, fake_class(class_name))
        modules[module_name] = module
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    return record


def child_spec(tmp_path, family, lora_paths, lora_scales, scheduler):
    tmp = str(tmp_path)
    spec = {"family": family, "model_path": os.path.join(tmp, "model"), "lora_paths": lora_paths,
            "lora_scales": lora_scales, "prompt": PROMPT, "source": os.path.join(tmp, "source.png"), "width": 64,
            "height": 96, "steps": 40, "guidance": 1.0, "scheduler": scheduler,
            "jobs": [{"n": 1, "seed": 11, "output_path": os.path.join(tmp, "cand_01.pending.png")}]}
    path = os.path.join(tmp, "spec-%s-%d.json" % (family, len(lora_paths)))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(spec, f)
    return path, spec


def test_sqt8_the_child_per_family(monkeypatch, tmp_path, capsys):
    import seed_edit_mflux_child as child
    monkeypatch.setattr(child, "exit_with_parent", lambda poll_s=2.0: None)
    monkeypatch.setattr(child.importlib.metadata, "version", lambda name: "0.24.0")
    record = child_fakes(monkeypatch)
    lora = os.path.join(str(tmp_path), "uncensored.safetensors")
    path, spec = child_spec(tmp_path, "qwen21", [lora], [1.0], "linear")
    assert child.main(["--spec", path]) == 0
    (name, init), = record["init"]
    assert name == "QwenImage21Edit"
    assert set(init) == {"model_path", "quantize", "model_config", "lora_paths", "lora_scales", "bake_lora"}
    assert (init["model_path"], init["quantize"], init["model_config"].model_name, init["lora_paths"],
            init["lora_scales"], init["bake_lora"]) == (spec["model_path"], None, "Qwen/Qwen-Image-2.1", [lora], [1.0],
                                                        False)
    (name, kwargs), = record["generate"]
    assert kwargs == {"seed": 11, "prompt": PROMPT, "image_paths": [spec["source"]], "num_inference_steps": 40,
                      "guidance": 1.0, "width": 64, "height": 96, "scheduler": "linear"}
    with Image.open(spec["jobs"][0]["output_path"]) as img:
        assert (img.mode, img.size) == ("RGB", (64, 96))
    out = capsys.readouterr().out.splitlines()
    assert out[0] == ('seed-edit-child: mflux 0.24.0, family qwen21, model Qwen/Qwen-Image-2.1, transformer overrides '
                      'None, scheduler linear, LoRAs [["uncensored.safetensors", 1.0]]')
    assert re.fullmatch(r"seed-edit-child done 1 [0-9]+\.[0-9]", out[-1])
    record["init"], record["generate"] = [], []
    path, spec = child_spec(tmp_path, "qwen21", [], [], "viggle_turbo")
    assert child.main(["--spec", path]) == 0
    assert (record["init"][0][1]["lora_paths"], record["init"][0][1]["lora_scales"]) == (None, None)
    assert record["generate"][0][1]["scheduler"] == "viggle_turbo"
    record["init"], record["generate"] = [], []
    lightning = os.path.join(str(tmp_path), "lightning.safetensors")
    path, spec = child_spec(tmp_path, "qwen2511", [lightning], [1.0], None)
    assert child.main(["--spec", path]) == 0
    (name, init), = record["init"]
    assert (name, init["model_config"].model_name, init["lora_paths"]) == (
        "QwenImageEdit", "Qwen/Qwen-Image-Edit-2511", [lightning])
    kwargs = record["generate"][0][1]
    assert kwargs["negative_prompt"] == " " and "scheduler" not in kwargs
    capsys.readouterr()
    record["init"], record["generate"] = [], []
    path, spec = child_spec(tmp_path, "x", [], [], None)
    assert child.main(["--spec", path]) == 2
    assert capsys.readouterr().out == "seed-edit-child: unknown model family 'x'; refusing\n"
    assert record == {"init": [], "generate": []}
    monkeypatch.setattr(child.importlib.metadata, "version", lambda name: "0.23.0")
    assert child.main(["--spec", os.path.join(str(tmp_path), "missing.json")]) == 2
    assert capsys.readouterr().out == ("seed-edit-child: mflux 0.23.0 is missing or older than 0.24.0; refusing "
                                       "(run bin/seed-edit-setup)\n")


# --- SQT9 (seed models SQ2, SQ28): the child's FAMILIES table mirrors the registry ----------------------------

def test_sqt9_the_child_mirrors_the_registry():
    import seed_edit_mflux_child as child
    tool = load_tool()
    for entry in seedgen.QWEN_MODELS:
        if entry["backend"] != "mflux":
            continue
        module_name, class_name = entry["mflux_class"].rsplit(".", 1)
        assert child.FAMILIES[entry["family"]] == (module_name, class_name, entry["mflux_config"]), entry["id"]
    assert set(child.FAMILIES) == set(seedgen.QWEN_FAMILIES)
    assert child.MIN_VERSION == tool.MFLUX_MIN_VERSION == (0, 24, 0)
    with open(os.path.join(WS, "seed_edit_mflux_child.py"), encoding="utf-8") as f:
        source = f.read()
    assert re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M) == [
        "argparse", "importlib.metadata", "json", "os", "re", "sys", "threading", "time"]
    for text in ("bake_lora=False", "quantize=None", '.convert("RGB").save('):
        assert text in source, text
```

- [ ] **Step 2: Run the two seed test files; the new and re-baselined tests fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedmodels-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py 2>&1 | tail -1
```

Expected: `3 failed, 168 passed`. The failing tests are exactly: `test_sgt15_the_mflux_child`, `test_sqt8_the_child_per_family`, `test_sqt9_the_child_mirrors_the_registry`.

- [ ] **Step 3: Implement.** Make these edits in order.

**Write** `seed_edit_mflux_child.py` (the whole file: Read it first, then Write exactly this; the file keeps its mode):

```python
"""seed_edit_mflux_child.py -- bin/seed-edit's mflux child: load one Qwen registry model of family
qwen21 (Qwen-Image-2.1, QwenImage21Edit) or qwen2511 (Qwen-Image-Edit-2511, QwenImageEdit) once from
a local pinned snapshot with its LoRAs as local files, then edit the source into every job of a
spec file (docs/superpowers/specs/2026-11-02-seed-generator-design.md, Section 3, amended by
docs/superpowers/specs/2026-11-02-seed-models-design.md, Section 4).

  ~/mflux-edit/.venv/bin/python seed_edit_mflux_child.py --spec SPEC

The spec carries family, model_path, lora_paths and lora_scales (equal-length lists, possibly
empty), prompt, source, width, height, steps, guidance (always 1.0), scheduler (qwen21 only) and
jobs. Runs under the mflux venv's Python (mflux pinned to 0.24.0). It never screens: bin/seed-edit
screens each pending image before giving it its final name. After saving each job's image as RGB
it prints "seed-edit-child done <n> <seconds>". LoRAs are never baked into the quantized weights.

Exit codes: 0 every job saved; 2 mflux missing or older than 0.24.0 (refused before the spec is
read) or an unknown family (refused before mlx or mflux is imported); 3 the parent died; anything
else is a crash. Top-level imports are standard library only; mlx and mflux are imported inside
main after both gates.
"""

import argparse
import importlib.metadata
import json
import os
import re
import sys
import threading
import time

MIN_VERSION = (0, 24, 0)
FAMILIES = {
    "qwen21": ("mflux.models.qwen21.variants.edit.qwen_image_21_edit", "QwenImage21Edit", "qwen_image_21"),
    "qwen2511": ("mflux.models.qwen.variants.edit.qwen_image_edit", "QwenImageEdit", "qwen_image_edit_2511"),
}


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
        print("seed-edit-child: mflux %s is missing or older than 0.24.0; refusing (run bin/seed-edit-setup)"
              % version, flush=True)
        return 2
    with open(args.spec, encoding="utf-8") as f:
        spec = json.load(f)
    family = spec.get("family")
    if family not in FAMILIES:
        print("seed-edit-child: unknown model family %r; refusing" % (family,), flush=True)
        return 2
    import mlx.core as mx
    from mflux.models.common.config.model_config import ModelConfig
    module_name, class_name, config_name = FAMILIES[family]
    model_class = getattr(importlib.import_module(module_name), class_name)
    config = getattr(ModelConfig, config_name)()
    loras = [[os.path.basename(p), s] for p, s in zip(spec["lora_paths"], spec["lora_scales"])]
    print("seed-edit-child: mflux %s, family %s, model %s, transformer overrides %s, scheduler %s, LoRAs %s"
          % (version, family, config.model_name, getattr(config, "transformer_overrides", None),
             spec["scheduler"], json.dumps(loras)), flush=True)
    model = model_class(model_path=spec["model_path"], quantize=None, model_config=config,
                        lora_paths=spec["lora_paths"] or None, lora_scales=spec["lora_scales"] or None,
                        bake_lora=False)
    peak = getattr(mx, "get_peak_memory", None) or mx.metal.get_peak_memory
    for job in spec["jobs"]:
        started = time.monotonic()
        kwargs = {"seed": job["seed"], "prompt": spec["prompt"], "image_paths": [spec["source"]],
                  "num_inference_steps": spec["steps"], "guidance": spec["guidance"],
                  "width": spec["width"], "height": spec["height"]}
        if family == "qwen21":
            kwargs["scheduler"] = spec["scheduler"]
        else:
            kwargs["negative_prompt"] = " "
        result = model.generate_image(**kwargs)
        result.image.convert("RGB").save(job["output_path"])
        seconds = time.monotonic() - started
        print("seed-edit-child: mlx peak memory %.2f GiB" % (peak() / 2 ** 30), flush=True)
        print("seed-edit-child done %d %.1f" % (job["n"], seconds), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedmodels-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py 2>&1 | tail -1
```

Expected: `171 passed`. Run the compile check with `FILES` = `seed_edit_mflux_child.py tests/test_seed_edit_tool.py`; expected `compiled 2` twice. Then run the gate block ("Between tasks") with `N=4`. Expected: `GATE PASS`, `lost 1 (listed 1, unexpected 0)` (SGT8, from Task 3), `new tests 171, not passing 0`, `baseline failures still failing 2 of 2`, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedmodels-wt/qwen-agent-workspace
git add seed_edit_mflux_child.py tests/test_seed_edit_tool.py
git diff --cached --name-only    # expected: exactly these 2 paths, with the qwen-agent-workspace/ prefix
git commit -m "feat(seed-edit): the mflux child dispatches by family (Qwen-Image-2.1 or 2511), takes LoRA lists and the 2.1 scheduler, gates on mflux 0.24.0 and saves RGB (SQ28, SQ29; SQT8, SQT9)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: `bin/seed-edit-setup`: selections, the per-selection floor, pinned downloads, licences, the probe report (SQ41-SQ47; SQT11-SQT14, SQT18, Review Focus 4)

This task implements:
- SQ41 options and refusals (PR8); SQ42 the byte copies of `mflux_version`, `default_hub`, `pinned_snapshot`, `pinned_file`, `weights_problem` and the constants; SQ43 items (PR9); SQ44 steps 1-9 with the floor (PR10), `DOWNLOAD` exactly, licence lines and the report; SQ45-SQ46.
- Whole file replaced (it keeps mode `100755`).
- Tests: SQT11-SQT14 and Review Focus 4 through `main` with spec 9.1's recorders (`setup_env` fixture, PR18), SQT18 in `tests/test_movie_ui_seedgen.py` (PR16); `test_sg_final_setup_resume_counts_what_is_present` rewritten (PR17); SGT16 deleted.

**Files:**
- Replace: `bin/seed-edit-setup` (Write)
- Modify: `tests/test_seed_edit_tool.py` (SGT16 and the old resume test replaced by the setup section)
- Modify: `tests/test_movie_ui_seedgen.py` (SQT18 before `test_sg_task6_review_page_guards`)

**Interfaces:**
- Consumes:
  - Task 3: the five functions' exact code in `bin/seed-edit`, `tool.qwen_hubs`, `tool.weights_problem` (Review Focus 4); Task 1: `QWEN_MODELS`, `QWEN_LORAS`, `LIGHTNING`, `DEFAULT_QWEN_MODEL`, `qwen_model`, `qwen_lora`, `QWEN21_PATTERNS`; Task 3's test helpers `pinned_cache`, `QWEN21_FILES`, `install_lora`.
- Produces:
  - `bin/seed-edit-setup`: `VENV_GIB = 3.0`, `HEADROOM_GIB = 1.0`, `DOWNLOAD`, `unique(values)`, `selection(args) -> ((models, loras), None) or (None, text)`, `items_of(models, loras)`, `item_ok(item, hub)`, `download_item(item)`, `report(venv, hub, models, loras, items)`, `main(argv=None)`.
  - Test helpers in `tests/test_seed_edit_tool.py`: `load_setup()`, the `setup_env` fixture (`setup`, `rec` with `call`/`run`/`free`/`ready`, `base`, `venv`, `py`, `hub`), `mark_ready(e)`, `downloads(rec)`, `Q4_ITEM`, `UNC_ITEM`, `VIG_ITEM`, `LIGHTNING_ITEM`.

- [ ] **Step 1: Write the failing tests.** Make these edits in order (Edit tool; each old text occurs exactly once at its turn).

**Edit 5.1** `tests/test_movie_ui_seedgen.py`: replace

```python

def test_sg_task6_review_page_guards():
```

with

```python

# --- SQT18 (seed models SQ42): bin/seed-edit-setup carries the tool's lookups byte for byte -------------------------

def _code_of(source, name):
    """The text of function name in source, without its docstring (as tests/test_seed_edit_tool.py's)."""
    start = source.index("\ndef %s(" % name)
    text = source[start:source.index("\n\n\n", start)]
    doc = text.index('"""')
    return text[:doc] + text[text.index('"""', doc + 3) + 3:]


def test_sqt18_the_setup_script_carries_the_tool_lookups():
    with open(os.path.join(WS, "bin", "seed-edit-setup"), encoding="utf-8") as f:
        setup = f.read()
    with open(os.path.join(WS, "bin", "seed-edit"), encoding="utf-8") as f:
        tool = f.read()
    for name in ("mflux_version", "default_hub", "pinned_snapshot", "pinned_file", "weights_problem"):
        assert _code_of(setup, name) == _code_of(tool, name), name
    assert setup.startswith("#!/usr/bin/env python3\n")
    for text in ('"mflux==0.24.0"', "VENV_GIB = 3.0", "HEADROOM_GIB = 1.0", "cache_dir=hub", 'revision=item["revision"]',
                 "HF_XET_CHUNK_CACHE_SIZE_BYTES", 'HF_HUB_ENABLE_HF_TRANSFER="0"', 'VENV = "~/mflux-edit/.venv"',
                 'DEFAULT_BASE_PYTHON = "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13"'):
        assert text in setup, text
    for text in ("HF_TOKEN", "SETUP_MIN_FREE_GIB", "find_lightning", "Q4_REPO", "EDIT_LORA_REPO"):
        assert text not in setup, text
    assert re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", setup, re.M) == [
        "argparse", "glob", "json", "os", "re", "shutil", "subprocess", "sys", "movie_ui_lib", "movie_ui_seedgen"]


def test_sg_task6_review_page_guards():
```

**Edit 5.2** `tests/test_seed_edit_tool.py`: replace

```python

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
    for name, value in (("Q4_REPO", seedgen.qwen_model("qwen2511-q4")["repo"]), ("EDIT_LORA_REPO", tool.EDIT_LORA_REPO),
                        ("EDIT_LORA_FILE", tool.EDIT_LORA_FILE)):
        assert '%s = "%s"' % (name, value) in source, name
    for name in ("mflux_version", "find_lightning"):
        assert _code_of(source, name) == _code_of(tool_source, name), name


def test_sg_final_setup_resume_counts_what_is_present(env):
    """Final review F1: a resumed download is not refused for space it already used. bin/seed-edit-setup is
    loaded as a module (its main is never called; its top level only imports and assigns)."""
    path = os.path.join(WS, "bin", "seed-edit-setup")
    loader = importlib.machinery.SourceFileLoader("seed_edit_setup", path)
    spec = importlib.util.spec_from_loader("seed_edit_setup", loader)
    setup = importlib.util.module_from_spec(spec)
    loader.exec_module(setup)
    hub, venv = os.path.join(env["tmp"], "hub"), os.path.join(env["tmp"], "venv")
    assert setup.present_gib(hub, venv) == 0.0
    blobs = os.path.join(hub, lib.repo_dir_name(setup.Q4_REPO), "blobs")
    snap = os.path.join(hub, lib.repo_dir_name(setup.Q4_REPO), "snapshots", "abc")
    os.makedirs(blobs)
    os.makedirs(snap)
    with open(os.path.join(blobs, "abc.incomplete"), "wb") as f:
        f.truncate(3 * 2 ** 20)
    os.symlink(os.path.join(blobs, "abc.incomplete"), os.path.join(snap, "model.safetensors"))
    os.makedirs(os.path.join(venv, "bin"))
    with open(os.path.join(venv, "bin", "python"), "wb") as f:
        f.truncate(2 ** 20)
    got = setup.present_gib(hub, venv)
    assert 4 / 1024 <= got < 4 / 1024 + 0.001, got
    with open(path, encoding="utf-8") as f:
        source = f.read()
    assert 'HF_HUB_ENABLE_HF_TRANSFER="0"' in source and "already present" in source

```

with

```python

# --- bin/seed-edit-setup in-process (seed models spec 9.1) --------------------------------------------------

def load_setup():
    path = os.path.join(WS, "bin", "seed-edit-setup")
    loader = importlib.machinery.SourceFileLoader("seed_edit_setup", path)
    spec = importlib.util.spec_from_loader("seed_edit_setup", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def setup_env(env):
    """bin/seed-edit-setup loaded in-process with spec 9.1's replacements: subprocess.call and .run record
    their argv (and env) and return 0, free_gib returns rec["free"] (100 GiB), venv_ready returns
    rec["ready"] (False), and SEED_EDIT_SETUP_PYTHON is an executable stub under tmp. Nothing is started,
    downloaded or installed."""
    setup = load_setup()
    mp, tmp = env["mp"], env["tmp"]
    base = os.path.join(tmp, "base-python")
    with open(base, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(base, 0o755)
    mp.setenv("SEED_EDIT_SETUP_PYTHON", base)
    rec = {"call": [], "run": [], "free": 100.0, "ready": False}

    def call(argv, env=None):
        rec["call"].append({"argv": list(argv), "env": env})
        return 0

    def run(argv, **kwargs):
        rec["run"].append(list(argv))
        if argv[0] == base:
            return types.SimpleNamespace(returncode=0, stdout="3.13\n", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    mp.setattr(setup.subprocess, "call", call)
    mp.setattr(setup.subprocess, "run", run)
    mp.setattr(setup, "free_gib", lambda path: rec["free"])
    mp.setattr(setup, "venv_ready", lambda py, venv: rec["ready"])
    venv = os.path.join(tmp, "home", "mflux-edit", ".venv")
    return dict(env, setup=setup, rec=rec, base=base, venv=venv, py=os.path.join(venv, "bin", "python"),
                hub=env["zhub"])


def mark_ready(e):
    """venv_ready answers True, and the venv python exists (as it does whenever the venv is ready)."""
    e["rec"]["ready"] = True
    os.makedirs(os.path.dirname(e["py"]), exist_ok=True)
    with open(e["py"], "w", encoding="utf-8") as f:
        f.write("")


def downloads(rec):
    """The item lists of the recorded DOWNLOAD calls."""
    return [json.loads(c["argv"][4]) for c in rec["call"] if c["argv"][1] == "-c"]


Q4_ITEM = {"kind": "snapshot", "repo": "mflux-community/qwen-image-2-1-mflux-q4",
           "revision": "b6c0fc76350650482d13aea89b316c28cd487f7f", "allow_patterns": None}
UNC_ITEM = {"kind": "file", "repo": "abenzerps/Qwen-Image-2.1-Uncensored-Quantized",
            "revision": "7959e658915f52274897fb573ffeda49de8dc16b", "file": "qwen-image-2.1-uncensored-lora.safetensors"}
VIG_ITEM = {"kind": "file", "repo": "Viggle/Qwen-Image-2.1-viggle-turbo",
            "revision": "009a44a895ef85f7e643c80fdca9543795248867",
            "file": "Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors"}
LIGHTNING_ITEM = {"kind": "file", "repo": "lightx2v/Qwen-Image-Edit-2511-Lightning",
                  "revision": "107d238d68b8387e32843d0b4a2e24ceb0d3ad86",
                  "file": "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors"}
RESEARCH_LINE = "seed-edit-setup: license: %s: Qwen Research License (non-commercial)"


# --- SQT11 (seed models SQ41-SQ44): the items of a selection ---------------------------------------------------

def test_sqt11_the_setup_items(setup_env, capsys):
    e = setup_env
    setup, rec = e["setup"], e["rec"]
    assert setup.main([]) == 0
    download = rec["call"][2]
    assert [c["argv"] for c in rec["call"]] == [
        [e["base"], "-m", "venv", e["venv"]], [e["py"], "-m", "pip", "install", "mflux==0.24.0"],
        [e["py"], "-c", setup.DOWNLOAD, e["hub"], download["argv"][4]]]
    assert downloads(rec) == [[Q4_ITEM, UNC_ITEM]]
    assert {k: download["env"][k] for k in ("HF_HOME", "HF_HUB_OFFLINE", "HF_XET_CHUNK_CACHE_SIZE_BYTES",
                                            "HF_HUB_ENABLE_HF_TRANSFER")} == {
        "HF_HOME": os.path.dirname(e["hub"]), "HF_HUB_OFFLINE": "0", "HF_XET_CHUNK_CACHE_SIZE_BYTES": "0",
        "HF_HUB_ENABLE_HF_TRANSFER": "0"}
    assert [e["base"], "-c", "import sys; print('%d.%d' % sys.version_info[:2])"] in rec["run"]
    assert [sys.executable, os.path.join(WS, "bin", "seed-edit"), "--probe"] in rec["run"]
    out = capsys.readouterr().out.splitlines()
    assert RESEARCH_LINE % "qwen21-q4" in out and RESEARCH_LINE % "uncensored" in out
    assert out[-1] == "seed-edit-setup: probe: unavailable: bin/seed-edit --probe printed unparsable output"
    cases = [(["--model", "qwen21-bf16", "--lora", "viggle-turbo", "--lora", "uncensored"],
              [{"kind": "snapshot", "repo": "Qwen/Qwen-Image-2.1", "revision": "d26bb61231c349cf6b7896fa83353113880e1ba3",
                "allow_patterns": seedgen.QWEN21_PATTERNS}, VIG_ITEM, UNC_ITEM]),
             (["--model", "qwen2511-q4"],
              [{"kind": "snapshot", "repo": "mflux-community/qwen-image-edit-2511-mflux-q4",
                "revision": "3c74aab7dd79e6a8148c329cbca78c00c049ec3b", "allow_patterns": None}, LIGHTNING_ITEM]),
             (["--lora", "viggle-turbo"], [VIG_ITEM]),
             (["--model", "qwen21-q4", "--model", "qwen21-q4", "--lora", "uncensored", "--lora", "uncensored"],
              [Q4_ITEM, UNC_ITEM])]
    mark_ready(e)
    for argv, want in cases:
        rec["call"] = []
        assert setup.main(argv) == 0, argv
        assert downloads(rec) == [want], argv
        assert [c["argv"][1] for c in rec["call"]] == ["-c"], argv
    lora_repos = set(lora["repo"] for lora in seedgen.QWEN_LORAS) | {"lightx2v/Qwen-Image-Edit-2511-Lightning"}
    for model_id in ("qwen21-q4", "qwen21-q8", "qwen21-bf16", "qwen2511-q4"):
        for loras in ([], ["uncensored"], ["viggle-turbo"], ["uncensored", "viggle-turbo"]):
            rec["call"] = []
            argv = ["--model", model_id]
            for lora_id in loras:
                argv += ["--lora", lora_id]
            assert setup.main(argv) == 0, argv
            items = downloads(rec)[0]
            assert [i["repo"] for i in items if i["kind"] == "snapshot"] == [seedgen.qwen_model(model_id)["repo"]]
            assert not [i for i in items if i["kind"] == "snapshot" and i["repo"] in lora_repos], argv
            assert [i["file"] for i in items if i["kind"] == "file" and i["repo"] != LIGHTNING_ITEM["repo"]] == [
                seedgen.qwen_lora(lora_id)["file"] for lora_id in loras]


# --- SQT12 (seed models SQ44 step 4): the per-selection free-space floor ---------------------------------------

def test_sqt12_the_free_space_floor(setup_env, capsys):
    e = setup_env
    setup, rec = e["setup"], e["rec"]
    def where():
        return min(setup.existing_ancestor(e["hub"]), setup.existing_ancestor(os.path.dirname(e["venv"])))

    rec["free"] = 5.0
    assert setup.main([]) == 2
    assert capsys.readouterr().err == (
        "Error: only 5.0 GiB free on %s; seed-edit-setup needs at least 13.9 GiB more (13.9 GiB in all, 0.0 GiB "
        "already present; qwen21-q4 ~9.91 GiB, uncensored ~0.03 GiB, mflux venv ~3 GiB, 1 GiB headroom)\n" % where())
    assert rec["call"] == [] and rec["run"] == []
    total = (10638928735 + 33586704) / 2 ** 30 + 3.0 + 1.0
    rec["free"] = total - 2 / 1024
    assert setup.main([]) == 2
    capsys.readouterr()
    blobs = os.path.join(e["hub"], lib.repo_dir_name("mflux-community/qwen-image-2-1-mflux-q4"), "blobs")
    os.makedirs(blobs)
    with open(os.path.join(blobs, "abc.incomplete"), "wb") as f:
        f.truncate(3 * 2 ** 20)
    assert setup.main([]) == 0
    assert downloads(rec) == [[Q4_ITEM, UNC_ITEM]]
    capsys.readouterr()
    rec["call"], rec["run"], rec["free"] = [], [], 5.0
    mark_ready(e)
    assert setup.main([]) == 2
    assert capsys.readouterr().err == (
        "Error: only 5.0 GiB free on %s; seed-edit-setup needs at least 10.9 GiB more (10.9 GiB in all, 0.0 GiB "
        "already present; qwen21-q4 ~9.91 GiB, uncensored ~0.03 GiB, 1 GiB headroom)\n" % where())
    os.remove(os.path.join(blobs, "abc.incomplete"))
    pinned_cache(os.path.join(e["tmp"], "zi"), Q4_ITEM["repo"], Q4_ITEM["revision"], QWEN21_FILES)
    install_lora(e, "uncensored")
    assert setup.main([]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "seed-edit-setup: nothing to do" and rec["call"] == []
    assert out[2].startswith("seed-edit-setup: model qwen21-q4 %s: " % os.path.join(
        e["hub"], lib.repo_dir_name(Q4_ITEM["repo"]), "snapshots", Q4_ITEM["revision"]))


def test_sg_final_setup_resume_counts_what_is_present(setup_env, capsys):
    """Final review F1, re-based on seed models SQ44 step 4: a resumed download is not refused for space it
    already used: a 3 MiB partial blob in the q4 repo and a 1 MiB venv python count as present."""
    e = setup_env
    setup, rec = e["setup"], e["rec"]
    blobs = os.path.join(e["hub"], lib.repo_dir_name("mflux-community/qwen-image-2-1-mflux-q4"), "blobs")
    os.makedirs(blobs)
    with open(os.path.join(blobs, "abc.incomplete"), "wb") as f:
        f.truncate(3 * 2 ** 20)
    os.makedirs(os.path.dirname(e["py"]))
    with open(e["py"], "wb") as f:
        f.truncate(2 ** 20)
    total = (10638928735 + 33586704) / 2 ** 30 + 3.0 + 1.0
    rec["free"] = total - 3.5 / 1024
    assert setup.main([]) == 0
    assert [c["argv"][1] for c in rec["call"]] == ["-m", "-c"]
    capsys.readouterr()
    rec["free"] = total - 4.5 / 1024
    assert setup.main([]) == 2
    assert re.fullmatch(r"Error: only [0-9.]+ GiB free on .+; seed-edit-setup needs at least 13\.9 GiB more \(13\.9 GiB "
                        r"in all, 0\.0 GiB already present; qwen21-q4 ~9\.91 GiB, uncensored ~0\.03 GiB, mflux venv "
                        r"~3 GiB, 1 GiB headroom\)\n", capsys.readouterr().err)
    with open(os.path.join(WS, "bin", "seed-edit-setup"), encoding="utf-8") as f:
        source = f.read()
    assert 'HF_HUB_ENABLE_HF_TRANSFER="0"' in source and "already present" in source


# --- SQT13 (seed models SQ41): the refusals before anything else ------------------------------------------------

def test_sqt13_the_setup_refusals(setup_env, capsys):
    e = setup_env
    setup, rec = e["setup"], e["rec"]
    known = "qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-q4, qwen2511-bf16"
    bf16 = ("qwen2511-bf16 is not installed by seed-edit-setup: it runs the diffusers weights of "
            "Qwen/Qwen-Image-Edit-2511 and lightx2v/Qwen-Image-Edit-2511-Lightning from the default Hugging Face "
            "cache (%s)" % e["hfhub"])
    cases = [(["--model", "flux"], "unknown --model flux; known: %s" % known),
             (["--model", "qwen2511-bf16"], bf16),
             (["--model", "qwen2511-bf16", "--model", "flux"], "unknown --model flux; known: %s" % known),
             (["--lora", "nope"], "unknown --lora nope; known: uncensored, viggle-turbo"),
             (["--lora", "nope", "--model", "qwen2511-bf16"], bf16)]
    for argv, text in cases:
        assert setup.main(argv) == 2, argv
        assert capsys.readouterr().err == "Error: %s\n" % text, argv
    e["mp"].setenv("SEED_EDIT_MFLUX_PYTHON", "/x/python")
    assert setup.main([]) == 2
    assert capsys.readouterr().err == ("Error: SEED_EDIT_MFLUX_PYTHON is set; unset it to set up the default venv at "
                                       "~/mflux-edit/.venv\n")
    assert setup.main(["--model", "flux"]) == 2
    assert capsys.readouterr().err.startswith("Error: unknown --model flux")
    assert rec["call"] == [] and rec["run"] == []


# --- SQT14 (seed models SQ44 step 8): the DOWNLOAD script ----------------------------------------------------------

def test_sqt14_the_download_script(monkeypatch, tmp_path):
    setup = load_setup()
    calls = []
    fake = types.ModuleType("huggingface_hub")

    def snapshot_download(**kwargs):
        calls.append(("snapshot_download", kwargs))
        return "/snapshot"

    def hf_hub_download(**kwargs):
        calls.append(("hf_hub_download", kwargs))
        return "/file"

    fake.snapshot_download, fake.hf_hub_download = snapshot_download, hf_hub_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake)
    hub = os.path.join(str(tmp_path), "hub")
    items = [dict(Q4_ITEM, allow_patterns=["a/*.json"]), UNC_ITEM]
    monkeypatch.setattr(sys, "argv", ["-c", hub, json.dumps(items)])
    exec(compile(setup.DOWNLOAD, "DOWNLOAD", "exec"), {})
    assert calls == [
        ("snapshot_download", {"repo_id": Q4_ITEM["repo"], "revision": Q4_ITEM["revision"], "allow_patterns": ["a/*.json"],
                               "cache_dir": hub}),
        ("hf_hub_download", {"repo_id": UNC_ITEM["repo"], "filename": UNC_ITEM["file"], "revision": UNC_ITEM["revision"],
                             "cache_dir": hub})]


# --- Review Focus 4: a host holding a 2511 q4 snapshot from an older main ----------------------------------------

def test_sq_review_focus_4_an_old_main_2511_snapshot(setup_env, capsys):
    e = setup_env
    setup, rec, tool = e["setup"], e["rec"], e["tool"]
    entry = seedgen.qwen_model("qwen2511-q4")
    old = mt.make_hf_cache(os.path.join(e["tmp"], "zi"), entry["repo"], {"transformer/0.safetensors": b"\x01" * (4 * 2 ** 20)})
    mt.make_hf_cache(os.path.join(e["tmp"], "zi"), tool.EDIT_LORA_REPO, {tool.EDIT_LORA_FILE: b"\x01" * 8})
    assert tool.weights_problem(entry, tool.qwen_hubs())[0] == (
        "mflux-community/qwen-image-edit-2511-mflux-q4@3c74aab7dd79 is not in %s or %s "
        "(run bin/seed-edit-setup --model qwen2511-q4)" % (e["zhub"], e["hfhub"]))
    mark_ready(e)
    total = (entry["bytes"] + entry["builtin_lora"]["bytes"]) / 2 ** 30 + 1.0
    rec["free"] = total - 2 / 1024
    assert setup.main(["--model", "qwen2511-q4"]) == 0
    assert downloads(rec) == [[{"kind": "snapshot", "repo": entry["repo"], "revision": entry["revision"],
                                "allow_patterns": None}, LIGHTNING_ITEM]]
    out = capsys.readouterr().out.splitlines()
    assert "seed-edit-setup: license: qwen2511-q4: Apache-2.0" in out
    assert "seed-edit-setup: license: lightning: Apache-2.0" in out
    assert os.path.isdir(os.path.join(old, "snapshots", REV))

```

- [ ] **Step 2: Run the two seed test files; the new and re-baselined tests fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedmodels-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py 2>&1 | tail -1
```

Expected: `7 failed, 169 passed`. The failing tests are exactly: `test_sqt11_the_setup_items`, `test_sqt12_the_free_space_floor`, `test_sg_final_setup_resume_counts_what_is_present`, `test_sqt13_the_setup_refusals`, `test_sqt14_the_download_script`, `test_sq_review_focus_4_an_old_main_2511_snapshot`, `test_sqt18_the_setup_script_carries_the_tool_lookups`.

- [ ] **Step 3: Implement.** Make these edits in order.

**Write** `bin/seed-edit-setup` (the whole file: Read it first, then Write exactly this; the file keeps its mode):

```python
#!/usr/bin/env python3
"""seed-edit-setup -- create the mflux venv and download the pinned weights of the selected Qwen
registry models and LoRAs that bin/seed-edit's mflux backend needs
(docs/superpowers/specs/2026-11-02-seed-models-design.md, Section 6; replaces seed generator SG66-SG69).

  bin/seed-edit-setup [--model ID ...] [--lora ID ...]

Run by the user (or the controller on the user's go); tests call main only with every process,
download and disk check replaced. With no option the selection is --model qwen21-q4 --lora
uncensored; otherwise it is exactly the options given (repeats dropped; --lora alone installs the
venv and those LoRAs only). --model takes qwen21-q4, qwen21-q8, qwen21-bf16 or qwen2511-q4;
qwen2511-bf16 is refused (it runs the diffusers weights of the default Hugging Face cache).

Items: each model is one snapshot of its repo at the registry's pinned revision (qwen21-bf16 only
the nine mflux file patterns of Qwen/Qwen-Image-2.1); qwen2511-q4 also gets its Lightning LoRA as
one file; each LoRA is one file of its repo at its pinned revision. A LoRA repo is never
snapshotted (the abenzerps and Viggle repos are about 98 GiB each). Everything goes into the
Z-Image hub ($Z_IMAGE_HF_HOME/hub or ~/hf_home/hub, never $HF_HOME).

Steps: refuse unknown IDs, qwen2511-bf16 and a set SEED_EDIT_MFLUX_PYTHON; read what is present
(the venv ~/mflux-edit/.venv with mflux 0.24.0; each item intact at its pinned revision); with
everything present print the report and exit; else check the free space: the needed items' bytes,
plus 3 GiB for the venv when it is not ready, plus 1 GiB headroom, less what an earlier partial run
left in their repo directories (and in the venv), so a re-run resumes; check a base Python of 3.11
or newer (SEED_EDIT_SETUP_PYTHON, default the 3.13 framework Python); create the venv; pip install
mflux==0.24.0; print each needed item's licence (the Qwen Research License items are
non-commercial); download the needed items (all public; no token); print the sizes and
bin/seed-edit --probe's verdict for each selected model and LoRA.

Exit codes: 0 done or nothing to do; 1 a step failed; 2 a precondition failed.
Standard library plus movie_ui_lib and movie_ui_seedgen. Python 3.9 and 3.13.
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
import movie_ui_seedgen as seedgen  # noqa: E402

VENV = "~/mflux-edit/.venv"
MFLUX_SPEC = "mflux==0.24.0"
MFLUX_VERSION = "0.24.0"
DEFAULT_BASE_PYTHON = "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13"
VENV_GIB = 3.0
HEADROOM_GIB = 1.0
DOWNLOAD = ("import json\n"
            "import sys\n"
            "from huggingface_hub import hf_hub_download, snapshot_download\n"
            "hub, items = sys.argv[1], json.loads(sys.argv[2])\n"
            "for item in items:\n"
            '    if item["kind"] == "snapshot":\n'
            '        print(snapshot_download(repo_id=item["repo"], revision=item["revision"],\n'
            '                                allow_patterns=item["allow_patterns"], cache_dir=hub), flush=True)\n'
            "    else:\n"
            '        print(hf_hub_download(repo_id=item["repo"], filename=item["file"], revision=item["revision"],\n'
            "                              cache_dir=hub), flush=True)\n")


def say(text):
    print("seed-edit-setup: " + text, flush=True)


def fail(code, text):
    sys.stderr.write("Error: %s\n" % text)
    return code


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


def default_hub():
    """$HF_HUB_CACHE, else <$HF_HOME or ~/.cache/huggingface>/hub (huggingface_hub's own rule)."""
    if os.environ.get("HF_HUB_CACHE"):
        return os.environ["HF_HUB_CACHE"]
    return os.path.join(os.environ.get("HF_HOME") or os.path.expanduser("~/.cache/huggingface"), "hub")


def pinned_snapshot(repo, revision, hubs):
    """(snapshot, repo_dir) of the first hub holding <repo dir>/snapshots/<revision> as a directory,
    else (None, None)."""
    for hub in hubs:
        repo_dir = os.path.join(hub, lib.repo_dir_name(repo))
        snapshot = os.path.join(repo_dir, "snapshots", revision)
        if os.path.isdir(snapshot):
            return snapshot, repo_dir
    return None, None


def pinned_file(repo, revision, name, hubs):
    """<hub>/<repo dir>/snapshots/<revision>/<name> in the first hub where its realpath is a non-empty
    regular file (the snapshot path is returned, not the realpath), else None."""
    for hub in hubs:
        path = os.path.join(hub, lib.repo_dir_name(repo), "snapshots", revision, name)
        real = os.path.realpath(path)
        if os.path.isfile(real) and os.path.getsize(real) > 0:
            return path
    return None


def weights_problem(entry, hubs):
    """(problem, model dir, built-in LoRA path) of an mflux registry model in hubs. problem is None
    when the pinned snapshot is intact (for qwen21 also with its component configs and processor/)
    and the built-in LoRA, if any, is present."""
    where = " or ".join(hubs)
    setup = "(run bin/seed-edit-setup --model %s)" % entry["id"]
    snapshot, repo_dir = pinned_snapshot(entry["repo"], entry["revision"], hubs)
    if snapshot is None:
        return "%s@%s is not in %s %s" % (entry["repo"], entry["revision"][:12], where, setup), None, None
    problems = list(lib.intact_scan(snapshot, repo_dir)[0])
    if entry["family"] == "qwen21":
        problems += ["missing %s" % rel for rel in seedgen.QWEN21_REQUIRED
                     if not os.path.isfile(os.path.join(snapshot, rel))]
        if not os.path.isdir(os.path.join(snapshot, "processor")):
            problems.append("missing processor/")
    if problems:
        return "%s: %s %s" % (entry["repo"], "; ".join(problems), setup), None, None
    lora = entry["builtin_lora"]
    lora_path = None
    if lora is not None:
        lora_path = pinned_file(lora["repo"], lora["revision"], lora["file"], hubs)
        if lora_path is None:
            return "Lightning LoRA %s is not in %s %s" % (lora["file"], where, setup), None, None
    return None, snapshot, lora_path


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


def unique(values):
    """values (None for none) without repeats, first order kept."""
    out = []
    for value in values or []:
        if value not in out:
            out.append(value)
    return out


def selection(args):
    """SQ41: ((model IDs, LoRA IDs), None), or (None, the refusal text). No option at all selects
    qwen21-q4 and uncensored."""
    if args.model is None and args.lora is None:
        return ([seedgen.DEFAULT_QWEN_MODEL], ["uncensored"]), None
    models, loras = unique(args.model), unique(args.lora)
    for model_id in models:
        if model_id not in seedgen.QWEN_MODEL_IDS:
            return None, "unknown --model %s; known: %s" % (model_id, ", ".join(seedgen.QWEN_MODEL_IDS))
    for model_id in models:
        entry = seedgen.qwen_model(model_id)
        if not entry["setup"]:
            return None, ("%s is not installed by seed-edit-setup: it runs the diffusers weights of %s and %s from "
                          "the default Hugging Face cache (%s)" % (model_id, entry["repo"], entry["builtin_lora"]["repo"],
                                                                    default_hub()))
    for lora_id in loras:
        if lora_id not in seedgen.QWEN_LORA_IDS:
            return None, "unknown --lora %s; known: %s" % (lora_id, ", ".join(seedgen.QWEN_LORA_IDS))
    return (models, loras), None


def items_of(models, loras):
    """SQ43: the selection's items in order: per model a snapshot item (and qwen2511-q4's Lightning
    file item), then per LoRA a file item. Each carries its licence for the step 8 lines."""
    items = []
    for model_id in models:
        entry = seedgen.qwen_model(model_id)
        items.append({"kind": "snapshot", "name": model_id, "repo": entry["repo"], "revision": entry["revision"],
                      "allow_patterns": entry["allow_patterns"], "bytes": entry["bytes"], "license": entry["license"]})
        lightning = entry["builtin_lora"]
        if lightning is not None:
            items.append({"kind": "file", "name": "lightning", "repo": lightning["repo"],
                          "revision": lightning["revision"], "file": lightning["file"], "bytes": lightning["bytes"],
                          "license": "Apache-2.0"})
    for lora_id in loras:
        lora = seedgen.qwen_lora(lora_id)
        items.append({"kind": "file", "name": lora_id, "repo": lora["repo"], "revision": lora["revision"],
                      "file": lora["file"], "bytes": lora["bytes"], "license": lora["license"]})
    return items


def item_ok(item, hub):
    """SQ43: a snapshot item is ok when its pinned snapshot is intact (weights_problem without the
    built-in LoRA, which is its own item); a file item when its pinned file is present."""
    if item["kind"] == "snapshot":
        entry = seedgen.qwen_model(item["name"])
        return weights_problem(dict(entry, builtin_lora=None), [hub])[0] is None
    return pinned_file(item["repo"], item["revision"], item["file"], [hub]) is not None


def download_item(item):
    """The DOWNLOAD script's view of an item."""
    if item["kind"] == "snapshot":
        return {"kind": "snapshot", "repo": item["repo"], "revision": item["revision"],
                "allow_patterns": item["allow_patterns"]}
    return {"kind": "file", "repo": item["repo"], "revision": item["revision"], "file": item["file"]}


def report(venv, hub, models, loras, items):
    """SQ44 step 9: the sizes, then bin/seed-edit --probe's verdict per selected model and LoRA
    (informational)."""
    say("venv %s: %.2f GiB" % (venv, tree_gib(venv) if os.path.isdir(venv) else 0.0))
    for model_id in models:
        problem, snapshot, _lora = weights_problem(dict(seedgen.qwen_model(model_id), builtin_lora=None), [hub])
        if problem is None:
            say("model %s %s: %.2f GiB" % (model_id, snapshot, snapshot_gib(snapshot)))
        else:
            say("model %s: %s" % (model_id, problem))
    for item in items:
        if item["kind"] != "file":
            continue
        path = pinned_file(item["repo"], item["revision"], item["file"], [hub])
        if path is not None:
            say("LoRA %s %s: %.2f GiB" % (item["name"], path, os.path.getsize(os.path.realpath(path)) / 2 ** 30))
        else:
            say("LoRA %s (%s) is not in %s" % (item["name"], item["file"], hub))
    ancestor = existing_ancestor(hub)
    say("free on %s: %.1f GiB" % (ancestor, free_gib(ancestor)))
    proc = subprocess.run([sys.executable, os.path.join(WS, "bin", "seed-edit"), "--probe"],
                          capture_output=True, text=True)
    try:
        qwen = json.loads(lib.last_line(proc.stdout))["qwen"]
        verdicts = [(i, qwen["models"][i]) for i in models] + [(i, qwen["loras"][i]) for i in loras]
        lines = [("probe: %s ok" % i) if v["ok"] else ("probe: %s unavailable: %s" % (i, v["reason"]))
                 for i, v in verdicts]
    except (ValueError, KeyError, TypeError):
        lines = ["probe: unavailable: bin/seed-edit --probe printed unparsable output"]
    for line in lines:
        say(line)


def main(argv=None):
    """bin/seed-edit-setup (seed models SQ41-SQ47). Returns the exit code."""
    parser = argparse.ArgumentParser(prog="seed-edit-setup", description="Create ~/mflux-edit/.venv (mflux "
                                     "0.24.0) and download the pinned weights of the selected Qwen models and "
                                     "LoRAs into the Z-Image hub (default: --model qwen21-q4 --lora uncensored).")
    parser.add_argument("--model", type=str, action="append")
    parser.add_argument("--lora", type=str, action="append")
    args = parser.parse_args(argv)
    chosen, error = selection(args)
    if error is not None:
        return fail(2, error)
    if os.environ.get("SEED_EDIT_MFLUX_PYTHON"):
        return fail(2, "SEED_EDIT_MFLUX_PYTHON is set; unset it to set up the default venv at ~/mflux-edit/.venv")
    models, loras = chosen
    venv = os.path.expanduser(VENV)
    py = os.path.join(venv, "bin", "python")
    hub = lib.zimage_hub()
    items = items_of(models, loras)
    venv_ok = venv_ready(py, venv)
    needed = [item for item in items if not item_ok(item, hub)]
    if venv_ok and not needed:
        say("nothing to do")
        report(venv, hub, models, loras, items)
        return 0
    total = sum(item["bytes"] for item in needed) / 2 ** 30 + (0.0 if venv_ok else VENV_GIB) + HEADROOM_GIB
    repo_dirs = []
    for item in needed:
        repo_dir = os.path.join(hub, lib.repo_dir_name(item["repo"]))
        if repo_dir not in repo_dirs and os.path.isdir(repo_dir):
            repo_dirs.append(repo_dir)
    present = sum(tree_gib(repo_dir) for repo_dir in repo_dirs)
    if not venv_ok and os.path.isdir(venv):
        present += tree_gib(venv)
    need = max(total - present, 0.0)
    free, where = min((free_gib(p), p) for p in (existing_ancestor(hub), existing_ancestor(os.path.dirname(venv))))
    if free < need:
        parts = ["%s ~%.2f GiB" % (item["name"], item["bytes"] / 2 ** 30) for item in needed]
        if not venv_ok:
            parts.append("mflux venv ~%g GiB" % VENV_GIB)
        parts.append("%g GiB headroom" % HEADROOM_GIB)
        return fail(2, "only %.1f GiB free on %s; seed-edit-setup needs at least %.1f GiB more (%.1f GiB in all, "
                       "%.1f GiB already present; %s)" % (free, where, need, total, present, ", ".join(parts)))
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
    if needed:
        for item in needed:
            say("license: %s: %s" % (item["name"], item["license"]))
        env = dict(os.environ, HF_HOME=os.path.dirname(hub), HF_HUB_OFFLINE="0", HF_XET_CHUNK_CACHE_SIZE_BYTES="0",
                   HF_HUB_ENABLE_HF_TRANSFER="0")
        code = subprocess.call([py, "-c", DOWNLOAD, hub, json.dumps([download_item(item) for item in needed])],
                               env=env)
        if code != 0:
            return fail(1, "the download exited %d" % code)
    report(venv, hub, models, loras, items)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedmodels-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py 2>&1 | tail -1
```

Expected: `176 passed`. Run the compile check with `FILES` = `bin/seed-edit-setup tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py`; expected `compiled 3` twice. Then run the gate block ("Between tasks") with `N=5`. Expected: `GATE PASS`, `lost 2 (listed 2, unexpected 0)` with `LOST ...test_sgt16_the_setup_script_is_read_never_run listed` and `LOST ...test_sgt8_choose_qwen listed`, `new tests 176, not passing 0`, `baseline failures still failing 2 of 2`, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedmodels-wt/qwen-agent-workspace
git add bin/seed-edit-setup tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py
git diff --cached --name-only    # expected: exactly these 3 paths, with the qwen-agent-workspace/ prefix
git commit -m "feat(seed-edit-setup): --model/--lora selections, the per-selection free-space floor with resume, pinned snapshot and single-file downloads, licence lines, the per-ID probe report (SQ41-SQ47; SQT11-SQT14, SQT18)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The page: the Qwen model box, LoRA rows, steps text, gating, body, titles and the Runs cell (SQ48-SQ56; SQT22)

This task implements:
- SQ48 the HTML box and the option text, the two CSS rules; SQ49 the constants and `S.seeds.qwen`/`qwenKey`; SQ50's eight functions and `seedCanvas(w, h, multiple)`; SQ51 `renderSeedQwen` (PR11, PR12); SQ52 `readSeedQwen`; SQ53 the gating and the size line; SQ54 the body; SQ55 `seedModelText` (PR13), the run title and the Runs cell.
- `resetSeeds` and `editSeedAgain` are untouched (SQ49: they never touch the selection).
- Tests: SQT22 (static checks plus a node run of the extracted `seedModelText` against `registry_view()`); SGT33's `PAGE_IDS` and `SEED_FUNCTIONS`; SG Review Focus 5 over multiples 16 and 32.

**Files:**
- Modify: `static/movie-ui/index.html` (`:173-177`)
- Modify: `static/movie-ui/app.css` (append)
- Modify: `static/movie-ui/app.js` (constants `:20-21`; `S.seeds` `:43`; `seedCanvas` `:1761-1770` and the new functions after it; `updateSeedButtons` `:1795-1846`; `seedBody` `:1859-1861`; run title `:1923-1924`; Runs cell `:2038`; load handler `:2111-2114`)
- Modify: `tests/test_movie_ui_seedgen.py`

**Interfaces:**
- Consumes:
  - Task 2: the `seed_edit` capability's `registry` (`registry_view()`'s shape) and `models.qwen.models`/`models.qwen.loras`; the run view's and list items' `qwen_model`, `loras`, `steps`. Task 3: `tool.canvas(w, h, multiple)` (SG Review Focus 5). Existing page helpers `$`, `el`, `clear`, `show`, `capability`.
- Produces:
  - `app.js`: `seedRegistry()`, `seedQwenEntry(id)`, `seedLoraEntry(id)`, `seedMultiple()`, `readSeedQwen()`, `renderSeedQwen()`, `seedLoraBody()`, `seedModelText(view)`, `seedCanvas(w, h, multiple)`; the request body's `qwen_model` and `loras`.

- [ ] **Step 1: Write the failing tests.** Make these edits in order (Edit tool; each old text occurs exactly once at its turn).

**Edit 6.1** `tests/test_movie_ui_seedgen.py`: replace

```python
            "se-seed", "se-generate", "se-generate-reason", "se-run-title", "se-run-status", "se-folder-options",
            "se-grid", "se-runs", "se-folders")
JS_TEXTS = ('"/api/seeds/runs"', '"/api/seeds/folders"', '"/keep"', '"/use"', '"New seed from this"',
```

with

```python
            "se-seed", "se-generate", "se-generate-reason", "se-run-title", "se-run-status", "se-folder-options",
            "se-grid", "se-runs", "se-folders", "se-qwen-box", "se-qwen-model", "se-steps", "se-loras", "se-qwen-note")
JS_TEXTS = ('"/api/seeds/runs"', '"/api/seeds/folders"', '"/keep"', '"/use"', '"New seed from this"',
```

**Edit 6.2** `tests/test_movie_ui_seedgen.py`: replace

```python
                  "loadSeeds", "loadSeedRuns", "loadSeedFolders", "copySeedPath", "seedFromStill", "stopSeedPoll",
                  "resetSeeds", "setupSeeds")
CSS_RULES = (".se-grid { display: flex; flex-direction: column; gap: 12px; }",
```

with

```python
                  "loadSeeds", "loadSeedRuns", "loadSeedFolders", "copySeedPath", "seedFromStill", "stopSeedPoll",
                  "resetSeeds", "setupSeeds", "seedRegistry", "seedQwenEntry", "seedLoraEntry", "seedMultiple",
                  "renderSeedQwen", "readSeedQwen", "seedLoraBody", "seedModelText")
CSS_RULES = (".se-grid { display: flex; flex-direction: column; gap: 12px; }",
```

**Edit 6.3** `tests/test_movie_ui_seedgen.py`: replace

```python

# --- Review Focus 5: the page's canvas size matches the tool's ----------------------------------------------
```

with

```python

# --- SQT22 (seed models SQ48-SQ56): the Qwen model box on the static page -------------------------------------

QWEN_BOX = ('      <div id="se-qwen-box" class="wide" hidden>\n'
            '        <label>Qwen model <select id="se-qwen-model"></select></label>\n'
            '        <span id="se-steps" class="muted"></span>\n'
            '        <div id="se-loras" class="se-loras"></div>\n'
            '        <p id="se-qwen-note" class="muted"></p>\n'
            '      </div>\n')
QWEN_JS_TEXTS = ('"Lightning 8-step LoRA built in (not selectable)"', '" steps (turbo)"', '"Unavailable here: "',
                 '"se-lora-scale-"', '"se-lora-note-"', '" — unavailable"', '"checking models…"', '" (Lightning)"',
                 "qwen_model: model === \"qwen\" ? S.seeds.qwen.model : null",
                 "loras: model === \"qwen\" ? seedLoraBody() : null",
                 '  const SEED_MODEL_LABELS = {zimage: "Z-Image", qwen: "Qwen-Image"};',
                 '  const SEED_BACKEND_LABELS = {"zimage": "Z-Image img2img", "mflux": "mflux", "diffusers": "diffusers", '
                 '"mflux-q4": "mflux q4", "diffusers-bf16": "diffusers bf16"};',
                 'S.seeds = {source: null, natural: null, run: null, view: null, rows: {}, busy: false, qwen: null, '
                 'qwenKey: ""};',
                 "  function seedCanvas(w, h, multiple) {",
                 "seedCanvas(natural.width, natural.height, seedMultiple())",
                 '" strength must be above 0 and at most 2"',
                 '    else if (qwenReason) { reason = qwenReason; }\n',
                 '        el("td", {text: seedModelText(r)}), el("td", {text: r.state}), thumbs]);')


def test_sqt22_the_qwen_box_on_the_page():
    static, texts = _static_texts()
    html, js, css = texts["index.html"], texts["app.js"], texts["app.css"]
    assert '<span id="se-model-note" class="muted"></span>\n' + QWEN_BOX in html
    assert '<option value="qwen">Qwen-Image (edit)</option>' in html and "Qwen-Image-Edit<" not in html
    for rule in (".se-loras { display: flex; flex-direction: column; gap: 4px; }",
                 ".se-lora { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }"):
        assert rule in css, rule
    for text in QWEN_JS_TEXTS:
        assert text in js, text
    for gone in ("Qwen-Image-Edit backend", "seedCanvas(img.naturalWidth", "SEED_BACKEND_LABELS[models.qwen.backend]"):
        assert gone not in js, gone
    node = shutil.which("node")
    if not node:
        return
    start = js.index("  function seedRegistry() {")
    helpers = js[start:js.index("  function seedMultiple() {", start)]
    start = js.index("  function seedModelText(view) {")
    helpers += js[start:js.index("\n  }\n", start) + len("\n  }\n")]
    views = [{"model": "zimage"},
             {"model": "qwen", "qwen_model": {"id": "qwen21-q4"}, "loras": [{"id": "uncensored", "scale": 1.0}]},
             {"model": "qwen", "qwen_model": {"id": "qwen21-q8"},
              "loras": [{"id": "uncensored", "scale": 0.5}, {"id": "viggle-turbo", "scale": 1}]},
             {"model": "qwen", "qwen_model": {"id": "qwen2511-q4"}, "loras": []},
             {"model": "qwen", "qwen_model": {"id": "qwen9"}, "loras": []},
             {"model": "qwen", "qwen_model": None}, {"model": "flux"}]
    script = ('const SEED_MODEL_LABELS = {zimage: "Z-Image", qwen: "Qwen-Image"};\n'
              "function capability(name) { return {registry: %s}; }\n%s"
              "process.stdout.write(JSON.stringify(%s.map(seedModelText)));\n"
              % (json.dumps(seedgen.registry_view()), helpers, json.dumps(views)))
    proc = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == ["Z-Image", "Qwen-Image-2.1 q4 + uncensored 1",
                                       "Qwen-Image-2.1 q8 + uncensored 0.5, viggle-turbo 1",
                                       "Qwen-Image-Edit-2511 q4 (Lightning)", "qwen9", "Qwen-Image", "flux"]


# --- Review Focus 5: the page's canvas size matches the tool's ----------------------------------------------
```

**Edit 6.4** `tests/test_movie_ui_seedgen.py`: replace

```python
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

with

```python
        js = f.read()
    start = js.index("  function seedCanvas(w, h, multiple) {")
    end = js.index("\n  }\n", start) + len("\n  }\n")
    cases = [[w, h, m] for (w, h) in CANVAS_CASES for m in (16, 32)]
    script = js[start:end] + "const SEED_LONG_EDGE = 1024;\nprocess.stdout.write(JSON.stringify(%s.map(function (c) { " \
        "return seedCanvas(c[0], c[1], c[2]); })));\n" % json.dumps(cases)
    path = os.path.join(str(tmp_path), "canvas.js")
    with open(path, "w", encoding="utf-8") as f:
        f.write(script)
    proc = subprocess.run([node, path], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    for (w0, h0, m), got in zip(cases, json.loads(proc.stdout)):
        try:
            want = dict(zip(("width", "height"), tool.canvas(w0, h0, m)))
        except tool.Refusal as e:
            found = re.search(r"gives a ([0-9]+)x([0-9]+) canvas", str(e))
            want = {"width": int(found.group(1)), "height": int(found.group(2))}
            assert min(got["width"], got["height"]) < 64, (w0, h0, m, got)
        assert got == want, (w0, h0, m)

```

- [ ] **Step 2: Run the two seed test files; the new and re-baselined tests fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedmodels-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py 2>&1 | tail -1
```

Expected: `3 failed, 174 passed`. The failing tests are exactly: `test_sgt33_the_static_page`, `test_sqt22_the_qwen_box_on_the_page`, `test_sg_review_focus_5_the_page_canvas_matches_the_tool`.

- [ ] **Step 3: Implement.** Make these edits in order.

**Edit 6.5** `static/movie-ui/app.css`: replace

```css
.gallery figure { margin: 0; display: flex; flex-direction: column; gap: 4px; }
```

with

```css
.gallery figure { margin: 0; display: flex; flex-direction: column; gap: 4px; }
/* seed models spec SQ48: the Qwen model box and its LoRA rows */
.se-loras { display: flex; flex-direction: column; gap: 4px; }
.se-lora { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
```

**Edit 6.6** `static/movie-ui/app.js`: replace

```javascript
  const SEED_ACTIVE = ["queued", "starting", "running"];
  const SEED_MODEL_LABELS = {zimage: "Z-Image", qwen: "Qwen-Image-Edit"};
  const SEED_BACKEND_LABELS = {"zimage": "Z-Image img2img", "mflux-q4": "mflux q4", "diffusers-bf16": "diffusers bf16"};
  const S = {
```

with

```javascript
  const SEED_ACTIVE = ["queued", "starting", "running"];
  const SEED_MODEL_LABELS = {zimage: "Z-Image", qwen: "Qwen-Image"};
  const SEED_BACKEND_LABELS = {"zimage": "Z-Image img2img", "mflux": "mflux", "diffusers": "diffusers", "mflux-q4": "mflux q4", "diffusers-bf16": "diffusers bf16"};
  const S = {
```

**Edit 6.7** `static/movie-ui/app.js`: replace

```javascript
  // Seed generator spec SG56: the Seeds tab's state.
  S.seeds = {source: null, natural: null, run: null, view: null, rows: {}, busy: false};

```

with

```javascript
  // Seed generator spec SG56: the Seeds tab's state.
  S.seeds = {source: null, natural: null, run: null, view: null, rows: {}, busy: false, qwen: null, qwenKey: ""};

```

**Edit 6.8** `static/movie-ui/app.js`: replace

```javascript

  function seedCanvas(w, h) {
    const longest = Math.max(w, h);
```

with

```javascript

  function seedCanvas(w, h, multiple) {
    const longest = Math.max(w, h);
```

**Edit 6.9** `static/movie-ui/app.js`: replace

```javascript
    }
    return {width: Math.floor(a / 16) * 16, height: Math.floor(b / 16) * 16};
  }
```

with

```javascript
    }
    return {width: Math.floor(a / multiple) * multiple, height: Math.floor(b / multiple) * multiple};
  }

  // Seed models spec SQ50-SQ55: the Qwen model registry (from the seed_edit capability) on the page.
  function seedRegistry() { return capability("seed_edit").registry || null; }

  function seedQwenEntry(id) {
    const registry = seedRegistry();
    return (registry && registry.models.filter(function (m) { return m.id === id; })[0]) || null;
  }

  function seedLoraEntry(id) {
    const registry = seedRegistry();
    return (registry && registry.loras.filter(function (l) { return l.id === id; })[0]) || null;
  }

  function seedMultiple() {
    const entry = seedQwenEntry(S.seeds.qwen ? S.seeds.qwen.model : null);
    return $("#se-model").value === "qwen" && entry ? entry.multiple : 16;
  }

  function readSeedQwen() {
    const state = S.seeds.qwen;
    if (!state) { return; }
    const select = $("#se-qwen-model");
    if (select.value) { state.model = select.value; }
    Array.prototype.forEach.call(document.querySelectorAll("#se-loras .se-lora"), function (row) {
      const id = row.dataset.lora;
      const box = $("#se-lora-" + id);
      if (!box.disabled) { state.loras[id].checked = box.checked; }
      state.loras[id].scale = $("#se-lora-scale-" + id).value;
    });
  }

  function renderSeedQwen() {
    const registry = seedRegistry();
    const select = $("#se-qwen-model");
    if (!registry) {
      clear(select);
      $("#se-steps").textContent = "checking models…";
      return;
    }
    const models = capability("seed_edit").models;
    const state = S.seeds.qwen;
    function probe(id) { return models && models.qwen.models[id]; }
    function loraProbe(id) { return models && models.qwen.loras[id]; }
    function enabled(id) { return !(probe(id) && probe(id).ok === false); }
    if (select.options.length !== registry.models.length) {
      clear(select);
      registry.models.forEach(function (m) { select.appendChild(el("option", {value: m.id})); });
    }
    registry.models.forEach(function (m, i) {
      const option = select.options[i];
      option.textContent = m.label + (enabled(m.id) ? "" : " — unavailable");
      option.disabled = !enabled(m.id);
    });
    let chosen = state.model;
    if (!enabled(chosen)) {
      const first = registry.models.filter(function (m) { return enabled(m.id); })[0];
      if (enabled(registry.default_model)) { chosen = registry.default_model; }
      else if (first) { chosen = first.id; }
    }
    state.model = chosen;
    select.value = chosen;
    const entry = seedQwenEntry(chosen);
    const loras = registry.loras.filter(function (l) { return l.family === entry.family; });
    function loraOk(id) { return loraProbe(id) ? loraProbe(id).ok === true : false; }
    const key = entry.family + "|" + JSON.stringify(loras.map(function (l) { return [l.id, loraOk(l.id)]; }));
    if (key !== S.seeds.qwenKey) {
      S.seeds.qwenKey = key;
      const box = clear($("#se-loras"));
      if (entry.family === "qwen2511") {
        box.appendChild(el("span", {cls: "muted", text: "Lightning 8-step LoRA built in (not selectable)"}));
      }
      else {
        loras.forEach(function (l) {
          const ok = loraOk(l.id);
          const saved = state.loras[l.id];
          const checkbox = el("input", {type: "checkbox", id: "se-lora-" + l.id});
          checkbox.checked = saved.checked && ok;
          checkbox.disabled = !ok;
          const scale = el("input", {type: "number", id: "se-lora-scale-" + l.id, min: "0", max: "2", step: "0.05", value: saved.scale});
          scale.disabled = !ok;
          const found = loraProbe(l.id);
          const text = ok ? l.license + (l.steps ? "; " + l.steps + " steps, scheduler " + l.scheduler : "")
            : "unavailable — " + (found ? found.reason : "probing");
          const note = el("span", {cls: "muted", id: "se-lora-note-" + l.id, text: text});
          box.appendChild(el("div", {cls: "se-lora", data: {lora: l.id}}, [el("label", {}, [checkbox, " " + l.label]),
            el("label", {}, ["strength ", scale]), note]));
        });
      }
    }
    const turbo = loras.filter(function (l) {
      const box = $("#se-lora-" + l.id);
      return l.steps && box && !box.disabled && box.checked;
    })[0];
    $("#se-steps").textContent = turbo ? turbo.steps + " steps (turbo)"
      : entry.steps + " steps" + (entry.family === "qwen2511" ? " (Lightning)" : "");
    const parts = registry.models.filter(function (m) { return !enabled(m.id); }).map(function (m) {
      return m.label + " — " + probe(m.id).reason;
    });
    $("#se-qwen-note").textContent = parts.length ? "Unavailable here: " + parts.join("; ") : "";
  }

  function seedLoraBody() {
    const out = [];
    Array.prototype.forEach.call(document.querySelectorAll("#se-loras .se-lora"), function (row) {
      const id = row.dataset.lora;
      const box = $("#se-lora-" + id);
      if (!box.disabled && box.checked) { out.push({id: id, scale: Number($("#se-lora-scale-" + id).value)}); }
    });
    return out;
  }

  function seedModelText(view) {
    if (view.model !== "qwen") { return SEED_MODEL_LABELS[view.model] || String(view.model); }
    let text = SEED_MODEL_LABELS.qwen;
    if (view.qwen_model) {
      const entry = seedQwenEntry(view.qwen_model.id);
      text = entry ? entry.label : String(view.qwen_model.id);
    }
    const loras = view.loras || [];
    if (loras.length) { text += " + " + loras.map(function (l) { return l.id + " " + l.scale; }).join(", "); }
    return text;
  }
```

**Edit 6.10** `static/movie-ui/app.js`: replace

```javascript
    const models = cap.models || null;
    const select = $("#se-model");
```

with

```javascript
    const models = cap.models || null;
    const registry = seedRegistry();
    if (!S.seeds.qwen && registry) {
      const loras = {};
      registry.loras.forEach(function (l) { loras[l.id] = {checked: l.default_on, scale: String(l.default_scale)}; });
      S.seeds.qwen = {model: registry.default_model, loras: loras};
    }
    readSeedQwen();
    renderSeedQwen();
    const select = $("#se-model");
```

**Edit 6.11** `static/movie-ui/app.js`: replace

```javascript
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
```

with

```javascript
      if (!models.zimage.ok) { parts.push("Z-Image: " + off + models.zimage.reason); }
      if (!models.qwen.ok) { parts.push("Qwen-Image: " + off + models.qwen.reason); }
      note = parts.join("; ");
    }
    $("#se-model-note").textContent = note;
    show($("#se-strength-box"), model === "zimage");
    show($("#se-qwen-box"), model === "qwen");
    $("#se-prompt-count").textContent = $("#se-prompt").value.length + " / " + SEED_PROMPT_MAX + " characters";
    const natural = S.seeds.natural;
    const canvas = natural ? seedCanvas(natural.width, natural.height, seedMultiple()) : null;
    if (natural) {
      $("#se-source-size").textContent = natural.width + " × " + natural.height + " → " + canvas.width + " × " + canvas.height;
    }
    const entry = models && models[model];
    let qwenReason = "";
    if (model === "qwen" && models && S.seeds.qwen) {
      const chosen = seedQwenEntry(S.seeds.qwen.model);
      const found = models.qwen.models[S.seeds.qwen.model];
      if (!(found && found.ok === true)) {
        qwenReason = (chosen ? chosen.label : S.seeds.qwen.model) + " unavailable: " + ((found && found.reason) || "probing");
      }
      else {
        Array.prototype.forEach.call(document.querySelectorAll("#se-loras .se-lora"), function (row) {
          const id = row.dataset.lora;
          const box = $("#se-lora-" + id);
          const s = Number($("#se-lora-scale-" + id).value);
          if (!qwenReason && !box.disabled && box.checked && !(Number.isFinite(s) && s > 0 && s <= 2)) {
            qwenReason = "LoRA " + seedLoraEntry(id).label + " strength must be above 0 and at most 2";
          }
        });
      }
    }
    const strength = Number($("#se-strength").value);
```

**Edit 6.12** `static/movie-ui/app.js`: replace

```javascript
    }
    else if (model === "zimage" && !(Number.isFinite(strength) && strength >= 0.10 && strength <= 0.90)) {
```

with

```javascript
    }
    else if (qwenReason) { reason = qwenReason; }
    else if (model === "zimage" && !(Number.isFinite(strength) && strength >= 0.10 && strength <= 0.90)) {
```

**Edit 6.13** `static/movie-ui/app.js`: replace

```javascript
            strength: model === "zimage" ? Number($("#se-strength").value) : null,
            candidates: Number($("#se-candidates").value), seed: seedText === "" ? null : Number(seedText)};
  }
```

with

```javascript
            strength: model === "zimage" ? Number($("#se-strength").value) : null,
            candidates: Number($("#se-candidates").value), seed: seedText === "" ? null : Number(seedText),
            qwen_model: model === "qwen" ? S.seeds.qwen.model : null, loras: model === "qwen" ? seedLoraBody() : null};
  }
```

**Edit 6.14** `static/movie-ui/app.js`: replace

```javascript
    S.seeds.view = view;
    $("#se-run-title").textContent = view.run + " · " + (SEED_MODEL_LABELS[view.model] || view.model) +
      (view.backend ? " (" + SEED_BACKEND_LABELS[view.backend] + ")" : "");
    const job = view.job;
```

with

```javascript
    S.seeds.view = view;
    $("#se-run-title").textContent = view.run + " · " + seedModelText(view) + (view.steps ? " · " + view.steps + " steps" : "") +
      (view.backend ? " (" + (SEED_BACKEND_LABELS[view.backend] || view.backend) + ")" : "");
    const job = view.job;
```

**Edit 6.15** `static/movie-ui/app.js`: replace

```javascript
      const row = el("tr", {cls: "clickable"}, [el("td", {text: r.run}), el("td", {text: text}),
        el("td", {text: SEED_MODEL_LABELS[r.model] || String(r.model)}), el("td", {text: r.state}), thumbs]);
      row.addEventListener("click", function () { openSeedRun(r.run); });
```

with

```javascript
      const row = el("tr", {cls: "clickable"}, [el("td", {text: r.run}), el("td", {text: text}),
        el("td", {text: seedModelText(r)}), el("td", {text: r.state}), thumbs]);
      row.addEventListener("click", function () { openSeedRun(r.run); });
```

**Edit 6.16** `static/movie-ui/app.js`: replace

```javascript
      S.seeds.natural = {width: img.naturalWidth, height: img.naturalHeight};
      const canvas = seedCanvas(img.naturalWidth, img.naturalHeight);
      $("#se-source-size").textContent = img.naturalWidth + " × " + img.naturalHeight + " → " + canvas.width + " × " + canvas.height;
      updateSeedButtons();
```

with

```javascript
      S.seeds.natural = {width: img.naturalWidth, height: img.naturalHeight};
      updateSeedButtons();
```

**Edit 6.17** `static/movie-ui/index.html`: replace

```html
        <option value="zimage">Z-Image (img2img)</option>
        <option value="qwen">Qwen-Image-Edit</option>
      </select></label>
    <span id="se-model-note" class="muted"></span>
    <label id="se-strength-box">Strength <input id="se-strength" type="number" min="0.10" max="0.90" step="0.05" value="0.45">
```

with

```html
        <option value="zimage">Z-Image (img2img)</option>
        <option value="qwen">Qwen-Image (edit)</option>
      </select></label>
    <span id="se-model-note" class="muted"></span>
      <div id="se-qwen-box" class="wide" hidden>
        <label>Qwen model <select id="se-qwen-model"></select></label>
        <span id="se-steps" class="muted"></span>
        <div id="se-loras" class="se-loras"></div>
        <p id="se-qwen-note" class="muted"></p>
      </div>
    <label id="se-strength-box">Strength <input id="se-strength" type="number" min="0.10" max="0.90" step="0.05" value="0.45">
```

- [ ] **Step 4: Run the tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedmodels-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py 2>&1 | tail -1
```

Expected: `177 passed`. Run the compile check with `FILES` = `tests/test_movie_ui_seedgen.py`; expected `compiled 1` twice. Then run the gate block ("Between tasks") with `N=6`. Expected: `GATE PASS`, `lost 2 (listed 2, unexpected 0)` (SGT8 and SGT16), `new tests 177, not passing 0`, `baseline failures still failing 2 of 2`, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/seedmodels-wt/qwen-agent-workspace
git add static/movie-ui/index.html static/movie-ui/app.js static/movie-ui/app.css tests/test_movie_ui_seedgen.py
git diff --cached --name-only    # expected: exactly these 4 paths, with the qwen-agent-workspace/ prefix
git commit -m "feat(movie-ui): the Seeds tab's Qwen model select, LoRA rows with strengths, read-only steps, per-model gating and the selection in run titles and the Runs list (SQ48-SQ56; SQT22)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---


## Verification (controller only; not an implementer task)

The controller runs these after Task 6, in spec 11's order: the pass bar (V1), the browser check (V2), the Opus design review (V3); the live checks (V4) are the user's, on macstudio. Every rule of "Global Constraints" applies. A finding is fixed in a new commit on the owning task's files; then that task's Step 4 and V1 rerun.

- [ ] **V1: The pass bar, spec 11 items 1-3 (about 18 minutes).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/seedmodels-baseline
cd $S/seedmodels-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py 2>&1 | tail -1
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/final-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt; tail -1 $D/final-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/final-pytest.txt $D/expected-failures.txt 6
diff <(grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt | sort) <(grep -E '^(FAILED|ERROR)' $D/final-pytest.txt | sort) && echo "same failures, same messages"
grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $D/final-pytest.txt
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1
git diff --stat 3ac29b9..HEAD -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py content_safety.py mps_guard.py movie_ui_seedfolder.py movie_ui_batch.py tests/movie_ui_testutil.py tests/test_movie_ui_builder.py | tail -1
git diff --name-only 3ac29b9..HEAD
git diff 3ac29b9..HEAD -- movie_ui_seedgen.py | grep -E '^\+(import|from) ' || echo "movie_ui_seedgen imports unchanged"
git diff 3ac29b9..HEAD -- tests/ | grep -E '^\+' | grep -nE "expanduser\(|urlopen|import requests|zshenv|fleet\.env|macstudio|127\.0\.0\.1:81|HF_TOKEN" || echo "no real HOME, HTTP client, private host, model-server address or token in the new tests"
git ls-files -s bin/seed-edit bin/seed-edit-setup | cut -c1-6
```

Expected, in order:
- `177 passed` (both seed test files);
- the final summary is the baseline's with the pass count higher by exactly 81 (`2 failed, 2536 passed, 2 skipped`), and the same 2 failed, 2 skipped;
- `lost 2 (listed 2, unexpected 0); new tests 177, not passing 0; baseline failures still failing 2 of 2` and `GATE PASS`;
- `same failures, same messages`; `1` (`test_mut26` passed); `OK 347/347`;
- no output from the untouched-files `--stat` (spec 0.3);
- exactly these 11 paths (no new file, spec 0.3): `qwen-agent-workspace/bin/seed-edit`, `qwen-agent-workspace/bin/seed-edit-setup`, `qwen-agent-workspace/movie_ui_lib.py`, `qwen-agent-workspace/movie_ui_seedgen.py`, `qwen-agent-workspace/movie_ui_server.py`, `qwen-agent-workspace/seed_edit_mflux_child.py`, `qwen-agent-workspace/static/movie-ui/app.css`, `qwen-agent-workspace/static/movie-ui/app.js`, `qwen-agent-workspace/static/movie-ui/index.html`, `qwen-agent-workspace/tests/test_movie_ui_seedgen.py`, `qwen-agent-workspace/tests/test_seed_edit_tool.py`;
- `movie_ui_seedgen imports unchanged`; the "no real HOME ..." line; `100755` twice.

- [ ] **V2: The browser check (spec 9.5), on a throwaway demo; never committed.**

Write `$S/smdemo/demo.py` with the Write tool (a scratch file outside the repository), exactly:

```python
"""Throwaway demo server for the seed models browser check (spec 9.5; never committed).

Run: python3 -B $S/smdemo/demo.py (kill $(cat $S/smdemo/pid) stops it). It never calls start_threads,
so no job ever runs. The page URL, with this run's throwaway token, goes to $S/smdemo/url.txt
(mode 0600) and is never printed. The static files are copied fresh from the worktree on every
start. The stub probe answers in spec SQ18's shape: qwen21-q4, qwen2511-q4 and uncensored ok;
qwen21-q8 and viggle-turbo not installed; qwen21-bf16 and qwen2511-bf16 below their memory floors.
"""
import json
import os
import secrets
import shutil
import sys

S = "/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad"
WS = S + "/seedmodels-wt/qwen-agent-workspace"
DEMO = S + "/smdemo"
OLD_RUN = "se-20261102-120000-0001"
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
    """A real image: a background with a centred rectangle."""
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

hubs = "<zhub> or <dhub>"
models = {
    "qwen21-q4": {"ok": True, "reason": None},
    "qwen21-q8": {"ok": False, "reason": "mflux-community/qwen-image-2-1-mflux-q8@f5c8cc79a674 is not in %s "
                                         "(run bin/seed-edit-setup --model qwen21-q8)" % hubs},
    "qwen21-bf16": {"ok": False, "reason": "needs a host with at least 56 GiB of memory (this host has 48.0 GiB)"},
    "qwen2511-q4": {"ok": True, "reason": None},
    "qwen2511-bf16": {"ok": False, "reason": "needs a host with at least 64 GiB of memory (this host has 48.0 GiB)"}}
loras = {"uncensored": {"ok": True, "reason": None},
         "viggle-turbo": {"ok": False, "reason": "Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors is "
                                                 "not in %s (run bin/seed-edit-setup --lora viggle-turbo)" % hubs}}
probe = {"zimage": {"ok": True, "reason": None, "backend": "zimage"},
         "qwen": {"ok": True, "reason": None, "models": models, "loras": loras}}
models_path = os.path.join(DEMO, "models.json")
with open(models_path, "w", encoding="utf-8") as f:
    json.dump(probe, f)
stub = os.path.join(ws, "bin", "seed-edit")
with open(stub, "w", encoding="utf-8") as f:
    f.write("#!%s\nimport sys\nif sys.argv[1:] == ['--probe']:\n"
            "    sys.stdout.write(open(%r, encoding='utf-8').read().strip() + '\\n')\n" % (sys.executable, models_path))
os.chmod(stub, 0o755)

run_dir = os.path.join(ws, "generated", "seeds", "runs", OLD_RUN)
if not os.path.isdir(run_dir):
    picture(os.path.join(run_dir, "source.png"), (1024, 672), (30, 90, 160), (250, 250, 250))
    picture(os.path.join(run_dir, "cand_01.png"), (1024, 672), (20, 30, 60), (250, 160, 40))
    lib.write_json_atomic(os.path.join(run_dir, "run.json"), {
        "schema": "seed-edit.run.v1", "run": OLD_RUN, "created": "2026-11-02T12:00:00Z", "state": "done",
        "prompt": "the same street at night, wet cobblestones", "model": "qwen", "backend": "mflux-q4",
        "strength": None, "seed": 41, "size": {"width": 1024, "height": 672},
        "source_size": {"width": 1024, "height": 672}, "source": "source.png", "source_origin": None,
        "job": None, "error": None,
        "candidates": [{"n": 1, "seed": 42, "status": "ok", "seconds": 61.2},
                       {"n": 2, "seed": 43, "status": "blocked", "seconds": 9.8}]})
picture(os.path.join(DEMO, "upload-800x600.png"), (800, 600), (90, 140, 90), (250, 250, 120))

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
found, detail = lib.seed_edit_check(ws, seedgen.QWEN_MODEL_IDS, seedgen.QWEN_LORA_IDS)
assert found is not None, detail
server.capabilities["seed_edit"] = seedgen.capability(found, detail, checked)
url_path = os.path.join(DEMO, "url.txt")
fd = os.open(url_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    f.write("http://127.0.0.1:%d/?t=%s\n" % (server.port, server.token))
with open(os.path.join(DEMO, "pid"), "w", encoding="utf-8") as f:
    f.write("%d\n" % os.getpid())
print("demo serving on 127.0.0.1:%d; open the URL in %s" % (server.port, url_path))
sys.stdout.flush()
server.serve_forever()
```

Run it in the background: `python3 -B $S/smdemo/demo.py`. It prints only the port and the path of `url.txt`; open the URL from that file in a browser (the token stays in the file, never in a terminal or a message). Check spec 9.5's six items, using `$S/smdemo/upload-800x600.png` for item 2 and the demo's `se-20261102-120000-0001` (the pre-registry Qwen run) for item 6. Item 4 queues a job: read its argv with `python3 -B -c 'import json,sys; print(json.load(open(sys.argv[1]))["argv"])' $S/smdemo/home/.local/share/qwen-agent/movie-ui/jobs/<job id>/job.json` (the demo never dispatches it). Stop the demo with `kill $(cat $S/smdemo/pid)`. Record pass or the exact difference per item. The demo was run once on the plan's scratch tree: the capability carried the registry with `qwen21-q4` and `qwen2511-q4` ok, the old run opened as `qwen2511-q4` with 8 steps and backend `mflux-q4`, the runs list carried its `qwen_model`, and the page held `se-qwen-box`.

- [ ] **V3: The design review.** An Opus `design-reviewer` reviews `git diff 3ac29b9..HEAD` against the spec (the load-bearing properties of spec 9.4 first). A finding is fixed as described above.

- [ ] **V4: The live checks (spec 10), run by the user on macstudio.** The agent never connects to macstudio. Record M0 and rows A1-A9 as "not run (awaiting the user)" until the user pastes the figures back; then record each row's end state, config line, peak memory, seconds per candidate, blocked count and visual note, and pass or fail per spec 10's pass rule. Open questions 1-3 of the spec are decided by the user from that record.

## Coverage

### Spec coverage: requirement -> task

| Requirement | Task (where) |
|---|---|
| SQ1 registry in `movie_ui_seedgen`, imports | 1 (constants), 3 (tool import; SGT34), 5 (setup import; SQT18); `test_sgt17_the_module_imports` unchanged; V1 |
| SQ2 child `FAMILIES` | 4 (SQT9) |
| SQ3 constants | 1 (SQT10), 2 (`MODELS`; SGT17) |
| SQ4 field meanings | 1 (SQT10: revisions, `allow_patterns`, `setup`), 3 (SQT3 lookups by revision), 5 (SQT11 setup flag) |
| SQ5 lookups, `registry_order` | 1 (SQT10, SQT16) |
| SQ6 `default_loras` | 1 (SQT10, SQT15) |
| SQ7 `qwen_settings` | 1 (SQT16), 3 (SQT5), Review Focus 5 |
| SQ8 `record_settings` | 1 (SQT16), 2 (SQT20) |
| SQ9 `canvas_multiple` | 1 (SQT16), 3 (Review Focus 1) |
| SQ10 `registry_view` | 1 (SQT16), 2 (SQT21), 6 (SQT22 node check) |
| SQ11 licences | 1 (SQT10 `license`), 5 (SQT11, Review Focus 4 licence lines), 6 (LoRA note text) |
| SQ12 options and rows | 3 (SQT2) |
| SQ13 labels | 3 (SQT7, SGT10, SGT11) |
| SQ14 canvas multiple | 3 (SQT1, Review Focus 1), 6 (SG Review Focus 5 for 16 and 32) |
| SQ15 pinned lookups | 3 (SQT3), 5 (SQT18 copies) |
| SQ16 tool functions | 3 (SQT3, SQT4, SQT7) |
| SQ17 removals | 3 (SQT3 source check, SGT14) |
| SQ18 probe | 3 (SQT4, SGT13) |
| SQ19 run.json keys | 3 (SQT5, SGT2, Review Focus 3), 2 (SQT19 queued record) |
| SQ20 backend line | 3 (SQT5, SGT9, SGT11) |
| SQ21 preflight | 3 (SQT7) |
| SQ22 dispatch | 3 (SQT5, SQT6, SGT11) |
| SQ23 mflux spec | 3 (SQT5, SGT9) |
| SQ24 content safety on every candidate | 3 (SQT6) |
| SQ25 local paths, `bake_lora`, offline | 3 (SQT5 paths under the hub, never realpaths; `HF_HUB_OFFLINE`), 4 (SQT8 `bake_lora=False`) |
| SQ26 environment, docstring | 3 (SQT3 environment-variable source check; docstring rewritten) |
| SQ27 tool imports | 3 (SGT34) |
| SQ28 child body | 4 (SQT8, SQT9, SGT15) |
| SQ29 child exit codes | 4 (SQT8: 0, 2 for the version and for an unknown family) |
| SQ30 request rows | 1 (SQT15), 2 (SQT19 over HTTP) |
| SQ31 `availability_error` | 2 (SGT17, SQT16 availability, SQT19, Review Focus 2) |
| SQ32 `capability` with `registry` | 2 (SGT17, SGT31) |
| SQ33 initial capability, refresh IDs | 2 (SQT21, SGT31) |
| SQ34 `seed_edit_argv` | 2 (SQT17), 3 (Review Focus 3, 5) |
| SQ35 `seed_edit_check` | 2 (SQT17, SGT19) |
| SQ36 create record and fields | 2 (SQT19, SGT23) |
| SQ37 run view keys | 2 (SQT20, SGT27) |
| SQ38 runs list keys | 2 (SQT20, SGT26) |
| SQ39 nothing created on 400/409 | 2 (SQT19, SGT21, SGT22, Review Focus 2) |
| SQ40 routes, `/files` unchanged | 2 (SGT20, `test_sg_final_files_refuses_a_runs_work_directory` unchanged) |
| SQ41 setup options and refusals | 5 (SQT13, SQT11 repeats) |
| SQ42 setup copies and constants | 5 (SQT18) |
| SQ43 items | 5 (SQT11) |
| SQ44 steps, floor, download, report | 5 (SQT11, SQT12, SQT14, `test_sg_final_setup_resume_counts_what_is_present`, Review Focus 4) |
| SQ45 exit codes, idempotence, no token | 5 (SQT12 nothing to do, SQT13, SQT18 `HF_TOKEN`) |
| SQ46 setup docstring | 5 (the Write) |
| SQ47 existing installs | 5 (Review Focus 4) |
| SQ48 HTML and CSS | 6 (SQT22, SGT33) |
| SQ49 constants and state | 6 (SQT22) |
| SQ50 functions | 6 (SGT33 `SEED_FUNCTIONS`, SQT22) |
| SQ51 `renderSeedQwen` | 6 (SQT22 texts; V2 items 1, 2) |
| SQ52 `readSeedQwen` | 6 (V2 items 3, 5) |
| SQ53 gating, size line | 6 (SQT22 texts; V2 items 1-3) |
| SQ54 body | 6 (SQT22 texts; V2 item 4) |
| SQ55 run title, Runs cell | 6 (SQT22 node check of `seedModelText`; V2 items 4, 6) |
| SQ56 page rules | 6 (SGT33 bans and pins) |

### Tests: spec ID -> test

| Spec test | Test (task) |
|---|---|
| SQT1 | `test_sqt1_the_canvas_for_qwen21` (3) |
| SQT2 | `test_sqt2_bad_qwen_arguments` (23 cases), `test_sqt2_the_cleaned_qwen_options` (3) |
| SQT3 | `test_sqt3_the_pinned_lookups` (3) |
| SQT4 | `test_sqt4_the_probe` (3) |
| SQT5 | `test_sqt5_the_mflux_selection` (5 cases) (3) |
| SQT6 | `test_sqt6_content_safety_on_every_candidate_of_every_model` (3) |
| SQT7 | `test_sqt7_run_time_refusals` (3) |
| SQT8 | `test_sqt8_the_child_per_family` (4) |
| SQT9 | `test_sqt9_the_child_mirrors_the_registry` (4) |
| SQT10 | `test_sqt10_the_registry_pins` (1) |
| SQT11 | `test_sqt11_the_setup_items` (5) |
| SQT12 | `test_sqt12_the_free_space_floor` (5) |
| SQT13 | `test_sqt13_the_setup_refusals` (5) |
| SQT14 | `test_sqt14_the_download_script` (5) |
| SQT15 | `test_sqt15_the_qwen_request_rows` (26 cases), `test_sqt15_qwen_defaults_order_and_placement` (1) |
| SQT16 | `test_sqt16_qwen_settings`, `test_sqt16_record_settings_and_the_canvas_multiple`, `test_sqt16_the_registry_view` (1); `test_sqt16_availability_of_a_qwen_selection` (2) |
| SQT17 | `test_sqt17_qwen_argv_and_probe_shape` (2) |
| SQT18 | `test_sqt18_the_setup_script_carries_the_tool_lookups` (5) |
| SQT19 | `test_sqt19_a_qwen_run_and_its_refusals` (2) |
| SQT20 | `test_sqt20_the_view_and_the_list_carry_the_selection` (2) |
| SQT21 | `test_sqt21_the_capability_carries_the_registry` (2) |
| SQT22 | `test_sqt22_the_qwen_box_on_the_page` (6) |

### Spec 9.3's edits to existing tests -> task

| Test | Task | Edit |
|---|---|---|
| SGT5 | none | unchanged: its one qwen row (`--strength` with qwen) fails at SG4 row 6, before every new row, so no row needs `--qwen-model` (spec 9.3 "where they need to") |
| SGT7 | 3 | `--qwen-model qwen2511-q4`, `Qwen-Image-Edit-2511 q4 (Lightning) needs 32 GiB` |
| SGT8 | 3 | deleted (with its helper `_qwen_refusal`) |
| SGT9, SGT10, SG Review Focus 4 | 3 | `mflux_weights` now builds pinned caches; `--qwen-model qwen2511-q4` (and `qwen2511-bf16` for Review Focus 4's second half); SQT5's qwen2511 spec dict; SQ13/SQ20 texts |
| SGT11 | 3 | `--qwen-model qwen2511-bf16`, backend `diffusers`, SQ20's line |
| SGT13 | 3 | the probe in SQ18's shape (rewritten; the importtime subprocess check unchanged) |
| SGT14 | 3 | `BF16_MIN_AVAIL_GIB` line replaced by the registry `memory_gib` check |
| SGT15 | 4 | the 0.24.0 refusal with `0.23.0`, the version pins 0.23.9/0.24.0, SQT9's source pins |
| SGT16 | 3, 5 | Task 3 reads `Q4_REPO`'s value from the registry (the tool constant is gone); Task 5 deletes it (SQT18) |
| `test_sg_final_setup_resume_counts_what_is_present` | 5 | rewritten through `main` (3 MiB partial blob + 1 MiB venv python) |
| SGT17 | 1, 2 | Task 1: the two clean dicts gain `qwen_model`/`loras`; Task 2: `Qwen-Image` label, `registry`, `availability_error(..., clean)` |
| SGT19, SGT22, SGT23, SGT26, SGT27, SGT31, SGT32 | 2 | `OK_MODELS` in SQ18's shape (SGT32 needs nothing more); the rest as spec 9.3 says |
| SGT33 | 6 | `PAGE_IDS` + 5, `SEED_FUNCTIONS` + 8 (no `JS_TEXTS` string depends on `SEED_MODEL_LABELS`) |
| SGT34 | 3 | the import list gains `"movie_ui_seedgen"` |
| SG Review Focus 5 | 6 | `seedCanvas(w, h, multiple)`, every case for 16 and 32 |
| SGT2 | 3 | plan ruling PR2: the record gains the four SQ19 keys |

## Plan rulings

**[defect]** rulings change behaviour from what the spec literally writes, or note a spec text that cannot work as written. **[reading]** rulings fill a detail the spec leaves open.

1. **PR1 [reading]: six tasks, one commit each, re-baselines folded in.** Spec 11's "feature commit Q1-Q7" and "test commit Q8" become six task commits, each with its own tests and the existing-test edits its change needs (the dispatch's rule). The deleted SGT8 and SGT16 are the only lost baseline passes.
2. **PR2 [defect]: spec 9.3 misses six existing-test edits.** (a) SGT2 compares the whole Z-Image `run.json`, which SQ19 extends by four keys. (b) SGT13 checks the old probe semantics (backend choice by memory), not only its shape; it is rewritten to the SQ18 shape. (c) SGT16 reads `tool.Q4_REPO`, which Task 3 removes, so Task 3 compares with the registry's repo until Task 5 deletes SGT16. (d) SGT19's bad case `qwen ... backend=["x"]` is no longer bad (the qwen entry has no `backend`, and extra keys are dropped); it becomes `reason=["x"]`. (e) SGT31's `none_ok` qwen entry must carry `models`/`loras` to parse. (f) SG Review Focus 4's bf16 half relied on the auto choice; it passes `--qwen-model qwen2511-bf16` and expects backend `diffusers`. SGT15's pins `0.21.9 < MIN_VERSION <= 0.22.0` also move to `0.23.9`/`0.24.0`.
3. **PR3 [reading]: helper `_qwen_fields(body, model)`** in `movie_ui_seedgen.py` holds rows 9a-9i (like SG's `_source`), returning `(qwen_model, loras, None)` or `(None, None, error)`.
4. **PR4 [reading]: helper `check_loras(values, entry)`** in `bin/seed-edit` holds SQ12 rows 12-16; row 12's regex is applied as written (`re.match(r"^([a-z0-9-]+)=(.*)$", value)`).
5. **PR5 [reading]: `_probe_qwen` requires the key `reason` in every entry** (as SG's PR15 does for `_probe_model`), with a local `entry()` helper.
6. **PR6 [reading]: one formula for the child's LoRA lists.** `lora_paths` = the built-in Lightning path (when the entry has one) followed by the selected LoRAs' paths; `lora_scales` likewise. It gives SQ23's two cases exactly; `steps`/`scheduler` are read from the record (already SQ7's values).
7. **PR7 [reading]: `preflight` sets `ctx["label"]` for Z-Image too** (`BACKEND_LABELS["zimage"]`), so `run()`'s exception text has one source (SQ13).
8. **PR8 [reading]: setup refusals are checked rule by rule:** every `--model` value for "unknown", then for `qwen2511-bf16`, then every `--lora` value, then `SEED_EDIT_MFLUX_PYTHON` (SQ41's "in this order"). SQT13 pins `--model qwen2511-bf16 --model flux` -> the unknown text.
9. **PR9 [reading]: setup item dicts carry `license`** (printed in step 8); the download payload is SQ44's key list only. LoRA file items keep the options' order (SQT11 "in that order").
10. **PR10 [reading]: the floor's `<parts>` are joined from a list,** so a run that needs only the venv has no leading comma; for SQ44's examples the text is identical.
11. **PR11 [reading]: a LoRA row while its probe entry is missing (probing) reads `unavailable — probing`.**
12. **PR12 [reading]: `#se-qwen-model`'s options are built once** (when their count differs from the registry's) and their text and `disabled` updated in place on every render.
13. **PR13 [reading]: `seedModelText` of a model other than `zimage`/`qwen`** keeps the old Runs-cell rule (`SEED_MODEL_LABELS[model] || String(model)`).
14. **PR14 [reading]: `run_view` places the four keys after `backend`** by splitting its key loop; `_h_seed_runs` adds only `qwen_model` and `loras` (SQ38).
15. **PR15 [reading]: `registry_view()["families"]` is a copy** of `QWEN_FAMILIES`, so no caller can mutate the registry (SQ1); SQT16 pins it.
16. **PR16 [reading]: SQT18 lives in `tests/test_movie_ui_seedgen.py`** (the spec's table) with its own copy of SGT16's `_code_of`.
17. **PR17 [reading]: SQT12's partial-blob clause tests the decision, not the text.** `%.1f` hides 3 MiB, so the test shows that a free figure 2 MiB under the total is refused without the partial blob and passes with it. `test_sg_final_setup_resume_counts_what_is_present` keeps the 3 MiB + 1 MiB case.
18. **PR18 [reading]: in the setup tests a ready venv also has its python file,** because `venv_ready` true implies it exists; otherwise SG67 step 6 would create the venv.
19. **PR19 [reading]: the demo for V2** is a new scratch `$S/smdemo/demo.py` (the seed generator's `$S/sgdemo/demo.py` with SQ18's probe and the two runs spec 9.5 names).
20. **PR20 [reading]: docstrings.** The four changed code files' and the two test files' docstrings name the seed-models spec; `bin/seed-edit`'s follows SQ26, the child's SQ29, setup's SQ46.

## Spec ambiguities resolved (for the spec author)

1. Spec 9.3 omits SGT2, SGT13's semantic rewrite, SGT16's interim `Q4_REPO` read, SGT19's `backend` bad case, SGT31's `none_ok` shape and SG Review Focus 4's bf16 half (PR2).
2. SQ41's refusal order for a mix of bad values is read rule by rule (PR8).
3. SQ44's `<parts>` with no needed item but a missing venv would start with a comma as written; the plan joins a list (PR10).
4. SQ51's LoRA note while probing has no reason; the plan shows `probing` (PR11).
5. SQ12's regex is applied with `re.match` as written; a trailing newline in a `--lora` value therefore passes row 12 and fails or passes row 16 by `float()` (PR4).

## Execution handoff

Plan complete and saved to `qwen-agent-workspace/docs/superpowers/plans/2026-11-02-seed-models.md`.

**How it was checked.**
- **Written and run first.** Every task's tests and code were written on a scratch copy of `3ac29b9`'s tree (`git archive`, outside the repository; never the worktree or the main checkout) and committed there per task (tests, then code). This plan's Edit and Write blocks are derived mechanically from those commits; each Edit's old text is the smallest whole-line context that is unique at its turn.
- **Replay.** A script parsed this file's blocks and applied them in order to a fresh copy of `3ac29b9`'s tree, checking every old text exactly once with and without its last newline. The result equalled the scratch tree byte for byte, and `bin/seed-edit` and `bin/seed-edit-setup` kept mode 755.
- **Fail first, then pass** (the two seed test files after Step 1 and after Step 3): Task 1 `32 failed, 95 passed` then `127 passed`; Task 2 `17 failed, 116 passed` then `133 passed`; Task 3 `45 failed, 124 passed` then `169 passed`; Task 4 `3 failed, 168 passed` then `171 passed`; Task 5 `7 failed, 169 passed` then `176 passed`; Task 6 `3 failed, 174 passed` then `177 passed`. The failing-test lists in each Step 2 are the replay's.
- **Compile.** After every task, the task's Python files compiled under Python 3.9.6 and 3.13; `node --check static/movie-ui/app.js` passed after Task 6.
- **The page.** The new `app.js` functions were also run in node against a minimal fake DOM: the selection fallback (an unavailable default moves to the first available model), the `40 steps` / `8 steps (Lightning)` / `6 steps (turbo)` texts, the strength gate (`LoRA Uncensored (abenzerps) strength must be above 0 and at most 2` at 3), the size line (`800 × 600 → 800 × 576` on 2.1, `→ 800 × 592` on 2511), the disabled Viggle row with its setup reason, the unavailable list, and the LoRA body; each matched spec 9.5 items 1-3.
- **Full suite.** On the final scratch tree (with the repository's other top-level directories alongside): `2 failed, 2530 passed, 8 skipped`; failures exactly `test_d2_copied_literals_match_the_spike, test_rst62_import_sets`; `tests/test_ltx_movie_offline.py` printed `OK 347/347`. Besides the two deleted tests, the only baseline passes not passing there were the 6 that need the real checkout's history and skip in a scratch tree (`test_lp14_the_render_unit_order`, `test_lp19_provenance_changes_only_for_the_location_panel`, `test_ls14_story_engine_gains_no_import`, `test_lc1_scale_shift_tables_match`, `test_lc3_the_1724_pair_lora_is_not_fail`, `test_mut26_pipeline_files_are_unchanged`); they run in the executor's gate, so the worktree's expected summary is `2 failed, 2536 passed, 2 skipped`.
- **Demo.** V2's `demo.py`, pointed at the scratch tree, served the page; over HTTP on 127.0.0.1 its capability carried the registry with `qwen21-q4` and `qwen2511-q4` ok, the pre-registry run opened as `qwen2511-q4` with 8 steps, the runs list carried its `qwen_model`, and the page held `se-qwen-box`.
- **Not run.** The executor's gate in the real worktree, a real browser (V2), any real model, download, venv, `bin/seed-edit-setup` run or network access, and the live checks (V4, the user's, on macstudio).

Please review the plan. Which execution approach would you prefer?
- **Subagent-driven.** A fresh Sonnet `code-executor` implements each task in `$S/seedmodels-wt` on branch `seed-models`, and a fresh Opus reviewer checks it before the next one starts.
- **Native.** One session implements every task, then one fresh Opus reviewer checks the whole branch.

I recommend subagent-driven: Tasks 2, 3, 5 and 6 each consume the previous tasks' names (the registry, the probe shape, the tool's copied functions, the capability's `registry`), and a shipped drift in the content-safety or "never snapshot a LoRA repo" properties would be costly, so a reviewer gate after each task is worth its cost.
