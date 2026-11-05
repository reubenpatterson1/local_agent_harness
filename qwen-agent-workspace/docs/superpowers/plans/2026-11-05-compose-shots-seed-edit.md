# Compose Shots Seed Edit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In Compose shots mode with a seed image (CLI: `bin/ltx-movie --shots --seed-image P --seed-edit-model ID`), every panel's still is a screened Qwen edit of the ORIGINAL seed, prompted by that panel's own `Image:` text, made for all panels in one `qwen_edit.run_jobs` child, recorded per panel in `seed_edits.json` and reused on a rerun; shots without a seed and every chained path stay byte-identical.

**Architecture:** Phase 2 of `bin/ltx-movie` gains a shots seed branch (`_phase2_shots_seed`) that plans read-only (prompts, keys, reuse), moves stale stills aside, clears the todo panels' record entries, runs one Qwen batch and fits each result into `images/panel_NN.png`; `bin/ltx-story-images` is never called in that mode. `_resolve_shots` stops refusing `--shots --seed-image` (it requires a named model instead), Phase 1c and the seed story preface are switched off in shots mode, and the dry run prints the new Phase 2 block. The movie-ui relaxes V1 rule 8 into three shots-seed rules, probes the selection for `redo` jobs too, drops phase `1c` from shots jobs, copies `seed_edits.json` into render-level forks, and keeps the Compose picker active in shots mode with "Seed as-is" disabled.

**Tech Stack:**
- Python 3.13 (`python3` = `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`, pytest 8.3.4, Pillow); Python 3.9.6 (`/usr/bin/python3`) for the compile check only. The page is vanilla ES2017; `node` (`/opt/homebrew/bin/node`) runs `--check` in the page test when present.
- No new dependency anywhere. Test helpers reused by import, unchanged: `tests/movie_ui_testutil.py`; `tests/test_seed_edit_tool.py` (`QWENEDIT_STUB`, `png`, `qwenedit_stub`, `stub_config`, `stub_calls`); `tests/test_qwen_edit.py` (`env`, `_mflux_ready`, `_bf16_cache`); `tests/test_movie_ui_qwen_edit.py` (`env`, `_clean_env`, `_compose`, `_job`, `_probe`, `_upload`, `_function`).

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-11-05-compose-shots-seed-edit-design.md`, committed at `7a79ea9` on branch `shots-seed-edit` (requirements SE1-SE34, tests SET1-SET21, KPIs SEK1-SEK10, live checks L1-L5). The spec's line citations are at `bdeb3ae`; `7a79ea9` adds only the spec, so they hold. Every Edit below is located by its old text, never by a line number. Where the spec cannot work as written against the existing suite, a numbered ruling marked **[defect]** says what this plan does instead; **[reading]** fills a detail the spec leaves open; **[dispatch]** follows an explicit instruction of the planning dispatch.

## Global Constraints

From the spec, verbatim (section in brackets):

- [Status] "The implementer makes no design decisions."
- [0.1 item 1] "Shots mode WITH a seed image: every panel's still is a Qwen edit of the ORIGINAL seed image (never of another panel's still, never of a previous clip's frame), each driven by that panel's own `Image:` text."
- [0.1 item 2] "Shots mode WITHOUT a seed image is unchanged (Z-Image-Turbo per stills-LoRA group, `bin/ltx-story-images`)."
- [0.1 item 3] "Chained mode (with or without a seed, with or without `--seed-edit-model`) is unchanged, including Phase 1c and `seed_edit.json`."
- [0.1 item 4] "All N edits of one Phase 2 run go through `qwen_edit.run_jobs` as ONE batch in ONE child load."
- [0.1 item 5] "Content safety screens every output; any blocked or failed panel fails the job. No silent fallback to the unedited seed or to Z-Image."
- [0.1 item 6] "Z-Image stays for every image made from text; nothing here adds a Qwen text-to-image path."
- [0.3] "there is no top-level `import hashlib` ... This spec follows the code (local import)." (`tests/test_dialogue.py::test_dk3_import_sets_are_unchanged` pins the import set.)
- [0.4] "Untouched (verified callers suffice): `bin/ltx-story-images`, `story_engine.py`, `qwen_edit.py`, `seed_edit_mflux_child.py`, `movie_ui_seedgen.py`, `content_safety.py`, `ltx_image_fit.py`, `bin/ltx-story-manifest`, `bin/ltx-mlx-render`, `scripts/deploy/build_pkg.py`, `static/movie-ui/app.css`, every other `PIPELINE_FILES` member."
- [1 item 3] "`--shots --seed-image` requires `--seed-edit-model ID` (absent or `as-is` refused, SE2)."
- [1 item 3] "Timeout: `qwen_edit.child_timeout(n)` for the n panels being edited: 3600 s for 1-6 panels, 7200 s for 12, 9000 s for 15, 14400 s for 24."
- [SE9] "The file the user passed is never modified. `images/images.json` is not written".
- [SE11] "Exactly `SHOTS_SEED_EDIT_PREFIX + _compose_prompt(Image:, Style:)`; no trigger word of any kind is inserted".
- [SE13] "Every panel's seed is `--image-seed` (default 0)".
- [SE28] "`FIELD_FLAGS` is unchanged (31 entries)".
- [SE32] "All new page text goes in through markup or `textContent`; the page bans (`https?://`, `\son[a-z]+=`, `style=`, `alert(`, `confirm(`, `prompt(`, `eval(`, `new Function`) still hold."
- [6.1] "no real model, no real HOME, no server other than the in-test `127.0.0.1` one, no port 8177/8178, no render, no download. Every test sets `HOME`, `HF_HOME`, `Z_IMAGE_HF_HOME` under `tmp_path` and removes `HF_HUB_CACHE` and every `SEED_EDIT_*` variable."
- [6.1] "Both new files load `bin/ltx-movie` with `SourceFileLoader` + `spec_from_loader` + `module_from_spec` + `exec_module` (never `load_module(`), no `urllib`, and are listed in `NEW_PY` (SE33)."
- [6.3] "No other existing test changes; a test that fails for any other reason is a defect in the implementation, not in the test." (Plan ruling R3 adds QET11's tail list, which SE33 forces.)
- [SEK1] "`python3 -m pytest tests/ -q -rA` from `WS` has no failure beyond those recorded at `bdeb3ae` in step 9.1.3 (expected: `test_d2_copied_literals_match_the_spike`, `test_rst62_import_sets`".
- [SEK2] "`python3 tests/test_ltx_movie_offline.py` prints the same `OK n/n` line as at `bdeb3ae` (expected `OK 347/347`); no check is added to or removed from that file".
- [SEK10] "At least 20 GiB free on the disk holding `WS` before the gate runs".
- [9.3] `bin/ltx-movie` is the only pinned file that changes; `test_mut26`'s `BASELINE` moves in one separate test-only commit after every pinned-file commit (plan ruling R2 sets the comment suffix to `, then to <sha> (shots-seed-edit)`).
- [8] "Live checks on macstudio (run by the user; the agent has no access)".

Controller rules (every task's requirements include them):

- The repository is public: never commit a secret or token. Never read, cat, grep or source `~/.zshenv` or any `fleet.env`, and never print tokens or secrets.
- Never ssh, scp, rsync or HTTP to macstudio or any other host, and never read or suggest copying its files. Never contact :8177 or :8178 or any server other than an in-test `127.0.0.1` one.
- Never download model weights; never run `bin/seed-edit-setup`, a model, a render, a real (non-dry-run) `bin/ltx-movie`, a venv creation or a pip install. Never run tests against the real HOME.
- Never push. Push and the PR are a separate step that needs the user's go.

House rules (every task's requirements include them):

- **The checkout.** Never touch the main checkout `/Users/reubenpatterson/local_agent_harness`. Every command runs in the worktree `$S/ss-wt`, branch `shots-seed-edit`. Never git stash, reset, amend or check out other work.
- **Paths.** `S` = `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`; `WS` = `$S/ss-wt/qwen-agent-workspace`; `D` = `$S/sse-baseline` (scratch, never staged). The git root is `$S/ss-wt`, so `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix. Run every command from `WS`; shell variables do not persist between commands, so every block defines the variables it uses.
- **Python.** Every changed file must compile on Python 3.9.6 and 3.13: no `match` statement, no `X | Y` type expressions, no walrus operator, no `str.removeprefix`, no `zip(strict=)`, no parenthesised context managers. `test_mut25` also scans every `NEW_PY` file for `urllib`, `load_module(`, `shell=True` and `X | None` text, docstrings included. The code blocks below use none of them.
- **Editing.** Executors change tracked files only with the Edit tool, or the Write tool for a new file. Never use `rm`, `sed -i`, a redirect or a script to change a tracked file.
- **Code blocks are copied byte for byte.** An Edit's old text is whole lines and occurs exactly once in the file at that moment, with or without its last newline. If it does not, stop and report; do not adapt it. Every Edit and Write below was replayed in order against `7a79ea9`'s files (see "Execution handoff").
- **Git.** Stage only the paths a task names, and check `git diff --cached --name-only` before every commit. Every commit passes the trailer as a second `-m`: `-m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`. Never stage `.DS_Store`, `.claude/`, `__pycache__/`, repo-root `bin/`, `qwen-agent-workspace/bin/action-from-dir`, `pin-sh2.json`, `story_bible_*.json` or `.superpowers/`.
- **The compile check** (in each task's verify step) is this command, with the task's Python files as `FILES`. Expected: two lines, `compiled N` for 3.9 and then for 3.13.

```bash
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' FILES; done
```

## Review Focus

These five inputs and failure modes are the ones most likely to reach a user first; the spec implies them and no SET row exercises them. Each is pinned by a test in the task that owns its code, named `test_sse_review_focus_N_...` (unique in the suite).

1. **The story the default engine actually writes in shots mode.** The robust engine's `assemble` (`story_engine.py:3270-3281`) writes a `## Characters` section, no `Style:` line at all in shots mode, and a `Dialogue:` field on speaking panels; the spec's fixture has a `Style:` on panel 1 and no dialogue. SE11's prompt must then be exactly `SHOTS_SEED_EDIT_PREFIX + <Image: text>` (no trailing space, no dialogue or narration). Expected: `_shots_seed_prompts` returns `(n, PREFIX + IMAGES[n-1])` for every panel and the batch's jobs carry those prompts. Test: `test_sse_review_focus_1_the_robust_engine_shots_story` (Task 1).
2. **`--redo` of a shots seed story.** The spec claims `--redo` works unchanged (Phase Redo moves the redo panels' stills aside before Phase 2), but SET9 only calls `_phase2_shots_seed` with `redo_panels` set. Expected: after `phase_redo_shots` then `phase2_stills`, only the redo panel is edited, its old still sits under `redo/<stamp>-<pid>/images/` (moved by Phase Redo, so Phase 2 prints no `seed edits: moved` line), the other panels' entries are byte-identical and the redo panel's entry is a fresh `ok`. Test: `test_sse_review_focus_2_a_redo_re_edits_only_its_panels` (Task 1).
3. **The legacy diffusers model `qwen2511-bf16`** (kept selectable for A/B). Its route is a different child (`character_dataset.py qwenedit`, screened in the child, stage files matched by basename); SET15 covers only the mflux route. Expected: one child whose spec has `image` = `<story>/seed-original.png`, skill `ltx_movie_shots_seed_edit`, one job per panel with its own prompt and no per-job `image` (every job shares the source), stills for the unblocked panels, and the blocked panel recorded `blocked`. Test: `test_sse_review_focus_3_the_legacy_diffusers_model` (Task 1; plan ruling R6).
4. **A block and a failure in the same batch** (an earlier panel blocked, then the child times out). SE17 prints both texts but no test combines them. Expected: stderr is the failure line (`kept: 1; edited on the next run: 2,3`) followed by the blocked line for panel 2; entries `ok`/`blocked`/`failed`; the rerun edits exactly 2 and 3. Test: `test_sse_review_focus_4_a_block_and_a_failure_in_one_batch` (Task 1).
5. **A render-level batch fork of a shots seed story.** SE27 says a render fork "reuses every still", but SET19 only checks the copy listing. Expected: copying `copy_plan(<story>, "render")` into a fork directory the way `movie_ui_server` does (`shutil.copy2`) and running the fork's Phase 2 with the same selection edits nothing (the entries' relative paths and the key hold in the fork), and no `seed-original.png` needs copying. Test: `test_sse_review_focus_5_a_render_fork_reuses_every_still` (Task 3).

## Plan rulings

1. **R1 [reading] Task order and commits.** Spec 9.2's "feature commit, then tests commit" becomes one commit per task with that task's tests (PR #10 precedent, its ruling R5); the `test_mut26` re-baseline stays its own final test-only commit (spec 9.2 item 3, 9.3). The Phase 2 batch (Task 1) lands before the CLI rule that admits `--shots --seed-image` (Task 2), so no commit has a CLI that reaches the old Z-Image Phase 2 with a seed (the four wrong behaviours of spec 0.2). `test_mut26` is an expected failure from Task 1 (the first `bin/ltx-movie` edit) through Task 4.
2. **R2 [dispatch] The `test_mut26` comment suffix is `, then to <SHA> (shots-seed-edit).`** Spec 9.3 item 2 writes `(shots seed edits)`; the planning dispatch requires `(shots-seed-edit)`, which also matches the chain's branch-name precedent (`(qwen-edit-models)`).
3. **R3 [defect] QET11's tail list grows with `NEW_PY`.** `tests/test_qwen_edit.py::test_qet11_imports_and_the_new_files` asserts `NEW_PY`'s entries after `tests/test_movie_ui_seedgen.py` exactly; SE33 appends two entries, so QET11 fails unless its list grows too. Spec 6.3 does not list it. Tasks 1 and 3 extend it with the entry they add to `NEW_PY`.
4. **R4 [reading] `NEW_PY` grows as each new file appears** (`test_mut25` compiles every listed file, so a name cannot precede its file): Task 1 adds `tests/test_ltx_movie_shots_seed.py`, Task 3 `tests/test_movie_ui_shots_seed.py`. The final tuple is SE33's.
5. **R5 [reading] Fixture names.** Spec 6.1's rules for `tests/test_ltx_movie_shots_seed.py` are the fixture `clean_env` (HOME/HF_HOME/Z_IMAGE_HF_HOME under `tmp_path`, no `HF_HUB_CACHE`/`SEED_EDIT_*`, `_story_dir` and `_qwen_edit` patched; PR #10's `qe_fake` pattern). `tests/test_movie_ui_shots_seed.py` imports `tests/test_movie_ui_qwen_edit.py`'s server fixture `env`, so its copy of `tests/test_movie_ui_checks.py`'s V1 fixture is named `v1_env`. SET15 and Review Focus 3 use `tests/test_qwen_edit.py`'s `env` by import, as spec SET15 says.
6. **R6 [defect, test-only] Review Focus 3 uses a one-substitution copy of `QWENEDIT_STUB`.** The stub derives the job number with `int(name[5:7])`, which raises `ValueError` on `panel_02.pending.png` (`name[5:7]` is `_0`), so the stub child would crash on every shots seed job. The test writes `QWENEDIT_STUB.replace("int(name[5:7])", "int(name[6:8])")` over the stub file; `tests/test_seed_edit_tool.py` is not changed. The real `character_dataset.child_qwenedit` prints `os.path.basename(job["output_path"])`, which `QWENEDIT_LINE_RE` (`^(\S+) ...`) matches for any name.
7. **R7 [reading] SE6's comment placement.** "directly above the existing comment" is read literally: the new comment line goes inside the `if` body, directly above `# The postface goes AFTER the rendered template on purpose.`, at its indentation (8 spaces). Behaviour is the same either way.
8. **R8 [reading] SE4 and SE5 get a test.** No SET row covers the three help texts or the docstring sentence; Task 2 adds `test_se4_se5_the_help_texts_and_the_docstring`, which compares each parser `help` to SE4's text exactly and finds SE5's sentence at the end of the "Shots mode" paragraph.
9. **R9 [reading] Pins of unchanged behaviour pass before their task's code.** SET14 (chained and plain shots dry runs) and SET21 (no new field flag) pin behaviour this plan must not change; each task's "run to verify they fail" step names them as the tests that already pass.
10. **R10 [reading] SET13's reuse record is built by the code under test.** The dry run's selection is `qwen21-q4` with no LoRA (`cli_selection` with no `--seed-edit-lora` gives `[]`), the geometry 576x320 from the 1920x1080 seed (as `test_ltx_movie_offline` L27b2 records), and image seed 0; SET13 writes the record with `_phase2_shots_seed` and exactly those values, then edits panel 2's `Image:` line, so `Panels to edit: 2; reused: 1,3` is the real comparison. SET13 runs the default (robust) engine: `--story-legacy` is now refused in shots seed mode, so PR #10's QET31 pattern (`--story-legacy`) cannot be reused.
11. **R11 [reading] Test fixture text.** SHOTS_STORY's title, summary, character line, three `Image:` texts and `Style:` text are this plan's (spec 6.1 fixes only their shape). `IMAGES[n-1]` follow the shots template (setting sentence, the character's full description, pose, shot type).
12. **R12 [reading] Task 2 inserts its tests at section anchors** (`# --- SET4 ...` and `# --- SET15 ...`), so the file reads in SET order; Task 4 appends SET20 after Review Focus 5 and adds its three imports.
13. **R13 [reading] The docstring sentence (SE5) is wrapped to the paragraph's width** without changing a word; the test compares whitespace-joined text.
14. **R14 [defect] Task 5's pinned-file check writes the 23 `PIPELINE_FILES` paths out on each `git diff` line.** PR #10's Task 8 held them in `P="..."` and ran `git diff -- $P`; under zsh (this host's shell) an unquoted `$P` is one word, so that check compared a single non-existent path, always printed `pipeline files clean at SHA` and listed nothing. Observed in this planning session's replay; the inline form prints the expected `qwen-agent-workspace/bin/ltx-movie`.

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `bin/ltx-movie` (pinned) | Modify (Tasks 1, 2) | Task 1: SE1 constants, SE8 dispatch, SE9-SE15 functions (the shots seed Phase 2). Task 2: SE2 rules, SE4 help, SE5 docstring, SE6 prompt, SE7 phase tuple, SE19-SE20 dry run. |
| `movie_ui_lib.py` | Modify (Task 3) | SE23 V1 rule 8, SE26 `job_phases`. |
| `movie_ui_server.py` | Modify (Task 3) | SE25: the 409 probe for `redo` too. |
| `movie_ui_batch.py` | Modify (Task 3) | SE27: `COPY_FILES["render"]` gains `seed_edits.json`. |
| `static/movie-ui/index.html` | Modify (Task 4) | SE29: the picker label span, the shots note. |
| `static/movie-ui/app.js` | Modify (Task 4) | SE30 `composeSeedEditActive`, SE31 `updateComposeButtons`. |
| `tests/test_ltx_movie_shots_seed.py` | Create (Task 1), Modify (Task 2) | SET4-SET12, SET15, Review Focus 1-4 (Task 1); SET1-SET3, SE4/SE5, SET13, SET14 (Task 2). |
| `tests/test_movie_ui_shots_seed.py` | Create (Task 3), Modify (Task 4) | SET16-SET19, SET21, Review Focus 5 (Task 3); SET20 (Task 4). |
| `tests/test_movie_ui_builder.py` | Modify (Tasks 1, 3, 5) | `NEW_PY` (Tasks 1, 3; SE33), `test_mut26` (Task 5 only). |
| `tests/test_qwen_edit.py` | Modify (Tasks 1, 3) | QET11's tail list (R3). |
| `tests/test_shots_mode.py` | Modify (Task 2) | S33's expected text (spec 6.3). |
| `tests/test_movie_ui_checks.py`, `tests/test_movie_ui_seedfolder.py` | Modify (Task 3) | MUT4's and SDT17's expected text (spec 6.3). |

**Task split.** Each task is the smallest unit with its own test cycle and a reviewer gate, and each leaves the suite green except the expected `test_mut26` failure:
- Task 1 adds the shots seed Phase 2 (reachable only by calling it: the CLI still refuses the combination), so a reviewer checks the batch, the record and the reuse rule against SE9-SE18 alone.
- Task 2 opens the CLI (rules, prompt, phase tuple, dry run, help) on top of it.
- Task 3 is the movie-ui server side (V1, phases, the 409, the batch copy), testable over HTTP without the page; Task 4 is the page; Task 5 the baseline.

The browser check, the pass bar, the design review and the live checks need a browser, a person or the user's go, so they are the controller's "Verification" section. The spec calls for no README or doc change beyond `bin/ltx-movie`'s docstring and help (SE4, SE5, Task 2), so there is no docs task.

---

## Between tasks: the existing suite

**Expected lost passes**, written to `$D/expected-failures.txt` in "Before Task 1" Step 3. A line is `T<first task> <test id> <note>`; the list covers Tasks 1-4 and is empty from Task 5 on (Task 5 checks that `test_mut26` passes again):

```text
# shots seed edit plan: baseline passes expected to fail from the given task until Task 5
T1 tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged bin/ltx-movie changes from Task 1; Task 5 moves BASELINE
```

**The gate** is `$D/gate.py`, written in "Before Task 1" Step 3. Every task's verify step runs this block with its `N` (a full run of about 20 minutes; it may run in the background):

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/sse-baseline
N=1
cd $S/ss-wt/qwen-agent-workspace
df -g . | tail -1 | awk '{print ($4 >= 20) ? "disk ok: " $4 " GiB free" : "DISK LOW: " $4 " GiB free"}'
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/task-$N-pytest.txt 2>&1; tail -1 $D/task-$N-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/task-$N-pytest.txt $D/expected-failures.txt $N
diff <(python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1) $D/baseline-offline.txt && echo "offline unchanged"
```

Expected: `disk ok` (SEK10: at least 20 GiB; on `DISK LOW` stop and report, never delete anything), `GATE PASS`, `not passing 0`, `baseline failures still failing 2 of 2`, `offline unchanged` (`OK 347/347`), and the `lost` line each task's verify step states.

**When the gate prints `GATE STOP`:** the executor stops and reports the UNEXPECTED or NEW-TEST-FAIL IDs with the output of `python3 -B -m pytest -q -p no:cacheprovider --tb=short <ids>`. A lost pass the list does not name is a defect in this task's code; the controller has an Opus reviewer rule on it and writes the exact fix. If an UNEXPECTED ID is `tests/test_fleet_tracing.py::test_trt41a_trace_cli_on_one_agent` or `tests/test_fleet_integration.py::test_t47_signatures_and_loopback_rules` (timing-sensitive, unrelated), rerun it alone; if it passes alone, the controller appends `T<N> <id> flaky` to the list and V1 rechecks it. A new test is never added to the list.

**Must stay green in every task** (none is in the list, so a failure stops the gate): `tests/test_dialogue.py::test_dk3_import_sets_are_unchanged` (no top-level import added to `bin/ltx-movie`), `tests/test_ltx_movie_offline.py`'s 347 checks (L17b: no `no_stills` text between `def phase2_stills(args):` and `def phase3_manifest`; L17d/L17f: the `_render_flags(args)` and `ltx-mlx-render` join counts; L25/L34: the chained seed prompt), `tests/test_movie_ui_builder.py::test_mut25_*`, `tests/test_ltx_movie_seed_edit.py` (QET26-QET32, chained Phase 1c), `tests/test_movie_ui_qwen_edit.py` (QET33-QET39), `tests/test_shots_mode.py` (every S-test but the S33 text edit), `tests/test_movie_ui_batch.py::test_bt8_the_copy_plan_of_every_level`, `tests/test_ltx_story_images.py` (I13, I21: `bin/ltx-story-images` untouched).

---

## Before Task 1: the plan commit, the snapshot, the baseline (controller; no code)

- [ ] **Step 1: Confirm the plan commit and the tree.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/ss-wt/qwen-agent-workspace
git branch --show-current                                      # expected: shots-seed-edit
git log -3 --format=%h' '%s                                    # expected: <plan sha> docs(plan): ...; 7a79ea9 spec: Compose shots mode with a seed image, ...; bdeb3ae Merge pull request #10 ...
git diff --stat bdeb3ae HEAD -- . ':(exclude)docs' | tail -1   # expected: no output
git status --short                                             # expected: no output
wc -l bin/ltx-movie movie_ui_lib.py movie_ui_server.py movie_ui_batch.py static/movie-ui/index.html static/movie-ui/app.js tests/test_movie_ui_builder.py tests/test_qwen_edit.py tests/test_shots_mode.py tests/test_movie_ui_checks.py tests/test_movie_ui_seedfolder.py | head -11
```

Expected `wc -l` counts (at `7a79ea9`): `bin/ltx-movie` 2976, `movie_ui_lib.py` 2477, `movie_ui_server.py` 3524, `movie_ui_batch.py` 492, `index.html` 504, `app.js` 3370, `tests/test_movie_ui_builder.py` 301, `tests/test_qwen_edit.py` 404, `tests/test_shots_mode.py` 2543, `tests/test_movie_ui_checks.py` 493, `tests/test_movie_ui_seedfolder.py` 1164. If any value differs, stop and report: every Edit below was written against this tree. (The plan commit itself is the controller's: `git add qwen-agent-workspace/docs/superpowers/plans/2026-11-05-compose-shots-seed-edit.md` only, message `docs(plan): Compose shots seed edit implementation plan`, with the Sonnet trailer.)

- [ ] **Step 2: Confirm the compressed snapshot (house rule; spec 9.1 step 1).** The planning session took it before writing this plan.

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
ls -l $S/snapshot-pre-sse-bdeb3ae.tgz
tar tzf $S/snapshot-pre-sse-bdeb3ae.tgz | grep -c 'qwen-agent-workspace/bin/ltx-movie$'   # expected: 1
tar tzf $S/snapshot-pre-sse-bdeb3ae.tgz | grep -c '/generated/'                           # expected: 0
```

If the file is missing, take it now: `tar czf $S/snapshot-pre-sse-bdeb3ae.tgz --exclude qwen-agent-workspace/generated -C $S/ss-wt qwen-agent-workspace`.

- [ ] **Step 3: Record the baseline (spec 9.1 steps 2-3) and write the gate files.** The full run takes about 20 minutes and may run in the background.

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/sse-baseline
mkdir -p $D
cd $S/ss-wt/qwen-agent-workspace
df -g . | tail -1
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1; tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
grep -c '^PASSED ' $D/baseline-pytest.txt
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1 > $D/baseline-offline.txt; cat $D/baseline-offline.txt
grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $D/baseline-pytest.txt
```

Expected: at least 20 GiB available in the `df -g` line; a summary of the shape `2 failed, <P0> passed, 2 skipped, ...` (at `7a79ea9` in a clean clone: `2 failed, 2615 passed, 2 skipped`); exactly the two `FAILED` lines `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets - AssertionError: b...`; no `ERROR` line; `OK 347/347`; `1` (`test_mut26` passes at `7a79ea9`). Record the `PASSED` count as `P0`. If the failures differ, stop and report. These files **are** the baseline.

Then write two scratch files with the Write tool (outside the repository, never staged):

1. `$D/expected-failures.txt`: exactly the `text` block of "Between tasks" above.
2. `$D/gate.py`, exactly:

```python
"""The task gate of the shots seed edit plan: a full pytest -rA run against the baseline. A new test is one of
the two new files or any test ID the baseline does not have."""
import re
import sys

base_file, run_file, expected_file, task = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
NEW_FILES = ("tests/test_ltx_movie_shots_seed.py::", "tests/test_movie_ui_shots_seed.py::")


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
        if parts and not line.startswith("#") and int(parts[0][1:]) <= task < 5:
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

(The `task < 5` clause makes every listed loss unexpected from Task 5 on, which is how Task 5's gate proves `test_mut26` passes again.)

---

### Task 1: The shots seed Phase 2 batch, its record and its reuse rule (pinned: `bin/ltx-movie`) (SE1, SE8-SE18; SET4-SET12, SET15, Review Focus 1-4)

This task implements, in `bin/ltx-movie`:
- SE1: the four constants after `SEED_EDIT_SCHEMA`.
- SE8: the shots seed dispatch at the top of `phase2_stills`.
- SE9-SE15: `_shots_seed_paths`, `_sha256_file`, `_shots_seed_prompts`, `_shots_seed_entries`, `_write_shots_seed_record`, `_shots_seed_plan`, `_shots_seed_lora_note`, `_phase2_shots_seed`, typed exactly as the spec gives them, after `phase_seed_edit` and before `_redo_moves` (SE16-SE18 are their behaviour).
- Tests: the new `tests/test_ltx_movie_shots_seed.py` (SET4-SET12, SET15, Review Focus 1-4); `NEW_PY` gains it (R4) and QET11's tail list grows (R3).

The CLI still refuses `--shots --seed-image` after this task (`_resolve_shots` is Task 2's), so the new branch is reachable only by calling `phase2_stills` or `_phase2_shots_seed` with shots seed args; no shipped command path changes behaviour.

**Files:**
- Modify: `bin/ltx-movie` (constants after `SEED_EDIT_SCHEMA = ...` `:137`; `phase2_stills` header `:2085-2087`; the end of `phase_seed_edit` `:2328-2330`).
- Create: `tests/test_ltx_movie_shots_seed.py`.
- Modify: `tests/test_movie_ui_builder.py` (`NEW_PY` `:213-217`), `tests/test_qwen_edit.py` (QET11's tail list `:402-404`).

**Interfaces:**
- Consumes (existing, unchanged): `_qwen_edit()` → `qwen_edit` with `label(model_id) -> str`, `multiple(model_id) -> int`, `memory_floor(model_id) -> float`, `settings(model_id, loras) -> {"qwen_model", "loras", "steps", "scheduler"}`, `generator_text(model_id, loras) -> str`, `wait_for_memory(floor, label, tag="seed-edit")`, `run_jobs(model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None, noun="job") -> (results, failure)` (`on_result(result)` fires once per `ok` or `blocked` job, for `ok` after the screened file is at `output_path`; a `failed` job gets no call), `Unavailable`; `_story_paths(story_id)` (`story_dir`, `story_md`, `images_dir`); `_load_story_panels(story_md)`; `_image_fit()` (`load_oriented_rgb(path)`, `fit_letterbox(img, w, h)`); `_seed_edit_size(args, multiple) -> (W, H)`; `_still_size(args) -> (2W, 2H)`; `_write_seed_edit_record(path, record)` (atomic); `_catalog_plan(args)`; `_panel_list(panels) -> "1,2,3"`; `bin/ltx-story-images`' `_style_text(panels)` and `_compose_prompt(image_text, style_text)`; `args.seed_edit` = `{"qwen_model": ID, "loras": [{"id", "scale"}]}` (set by `_resolve_seed_edit`).
- Produces (Tasks 2-3 and the tests use these names exactly): constants `SHOTS_SEED_EDIT_SKILL = "ltx_movie_shots_seed_edit"`, `SHOTS_SEED_EDITS_SCHEMA = "ltx-movie.seed-edits.v1"`, `SHOTS_SEED_EDIT_PREFIX`, `SHOTS_SEED_LORA_NOTE`; `_shots_seed_paths(story_dir) -> {"original", "record", "work"}`; `_sha256_file(path) -> str`; `_shots_seed_prompts(story_md) -> [(n, prompt)]`; `_shots_seed_entries(record_path) -> {n: entry}`; `_write_shots_seed_record(path, entries, total)`; `_shots_seed_plan(args, qe) -> (error or None, {"prompts", "size", "still", "keys", "entries", "reuse", "todo"} or None)`; `_shots_seed_lora_note(args) -> bool`; `_phase2_shots_seed(args) -> 0 | 1`; the story files `seed-original.png`, `seed_edits.json`, `seed_edits/`.

- [ ] **Step 1: Write the failing tests.**

Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
          "tests/test_movie_ui_qwen_edit.py")
```

with:

```python
          "tests/test_movie_ui_qwen_edit.py", "tests/test_ltx_movie_shots_seed.py")
```

Edit `tests/test_qwen_edit.py`: replace this text, which occurs exactly once:

```python
        "qwen_edit.py", "tests/test_qwen_edit.py", "tests/test_ltx_movie_seed_edit.py",
        "tests/test_movie_ui_qwen_edit.py"]
```

with:

```python
        "qwen_edit.py", "tests/test_qwen_edit.py", "tests/test_ltx_movie_seed_edit.py",
        "tests/test_movie_ui_qwen_edit.py", "tests/test_ltx_movie_shots_seed.py"]
```

Write `tests/test_ltx_movie_shots_seed.py` with exactly this content (the Write tool):

```python
"""Tests for bin/ltx-movie's shots mode with a seed image (docs/superpowers/specs/2026-11-05-compose-shots-seed-
edit-design.md, Sections 3 and 6.2: SET1-SET15, with the plan's Review Focus pins 1-4): every panel's still is a
Qwen edit of the original seed, made in one batch, screened, fitted, recorded in seed_edits.json and reused on a
rerun; the option rules, the story prompt, the phase tuples and the dry run.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_ltx_movie_shots_seed.py

Rules (spec 6.1): bin/ltx-movie is loaded with SourceFileLoader, spec_from_loader, module_from_spec and
exec_module as ltx_movie_sse. The clean_env fixture sets HOME, HF_HOME and Z_IMAGE_HF_HOME under tmp_path,
removes HF_HUB_CACHE and every SEED_EDIT_* variable, and patches _story_dir to <tmp>/stories/<id> and _qwen_edit
to the multi-job fake _FakeShotsQwenEdit (the real qwen_edit's pure parts, and recorders for selection_problem,
wait_for_memory and run_jobs). SET15 and Review Focus 3 use the real qwen_edit instead, with test_qwen_edit's
env fixture and the stub children of tests/test_seed_edit_tool.py. No test loads a model, renders, contacts a
server or touches port 8177 or 8178. Stdlib, PIL and pytest.
"""

import argparse
import glob
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import re
import types

import pytest
from PIL import Image

import movie_ui_testutil as mt
import qwen_edit
import test_seed_edit_tool as st
from test_qwen_edit import _bf16_cache, _mflux_ready, env  # noqa: F401

WS = mt.WS
UNC = [{"id": "uncensored", "scale": 1.0}]
PREFIX = ("Edit this photo into a new shot of the same film. Every person from the photo who appears in the new "
          "shot keeps exactly the same face, hair, skin tone, build and clothing. Change their pose and action, "
          "the place, the background, the lighting, the framing and the camera angle to match the new shot, and "
          "leave out anyone the new shot does not describe. The new shot: ")
LORA_NOTE = ("note: Z-Image stills LoRAs (character, location and catalog stills LoRAs) do not apply to Qwen "
             "edits; every panel's still is edited without them")
SETTING = "The setting is a rain-soaked stone harbour at night, wet cobbles underfoot, under amber lamplight."
WOMAN = "The woman in a red coat is a tall woman in her thirties with short black hair and a red wool coat."
IMAGES = [SETTING + " " + WOMAN + " She stands at the end of the quay facing right; medium shot, eye level.",
          SETTING + " " + WOMAN + " She runs along the quay toward the camera; wide shot, low angle.",
          SETTING + " " + WOMAN + " She looks out to sea; close-up, eye level."]
STYLE = "Muted teal and amber colour with soft film grain."
ENTRY_KEYS = ["n", "status", "created", "label", "source", "source_sha256", "original", "prompt", "seed", "width",
              "height", "still_width", "still_height", "qwen_model", "loras", "steps", "scheduler", "output",
              "still", "still_sha256", "seconds", "error"]


def _story_md(images=IMAGES, style=STYLE, dialogue=False):
    """A shots story.md: a title, a summary, a Characters section and one panel per images item (no Image: line
    for None); panel 1 has a Style: line unless style is None; dialogue adds a Dialogue: line to every panel."""
    lines = ["# The harbour", "", "A woman waits on a harbour quay for a boat that never comes.", "",
             "## Characters",
             '- "the woman in a red coat": a tall woman in her thirties with short black hair and a red wool coat.',
             ""]
    for n, image in enumerate(images, start=1):
        lines.append("## Panel %d — Shot %d" % (n, n))
        if image is not None:
            lines.append("Image: %s" % image)
        if n == 1 and style is not None:
            lines.append("Style: %s" % style)
        lines.append("Motion: The woman in a red coat turns her head. The camera stays static.")
        if dialogue:
            lines.append("Dialogue: the woman in a red coat: Where are you?")
        lines.append("Narration: She waits.")
        lines.append("")
    return "\n".join(lines)


SHOTS_STORY = _story_md()


def _load_movie():
    path = os.path.join(WS, "bin", "ltx-movie")
    loader = importlib.machinery.SourceFileLoader("ltx_movie_sse", path)
    spec = importlib.util.spec_from_loader("ltx_movie_sse", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


movie = _load_movie()


class _FakeShotsQwenEdit(object):
    """Spec 6.1's multi-job fake qwen_edit: the real pure parts, and recorders for selection_problem,
    wait_for_memory (raises wait_error when set) and run_jobs. run_jobs handles the jobs in order by
    outcomes.get(n, "ok"): "ok" writes a (width, height) PNG of colour (0, 0, 40 * n) at output_path and reports
    12.5 s, "blocked" reports a block and writes nothing, "stop" stops (this job and every later one are failed);
    after the on_result of job interrupt_after it raises KeyboardInterrupt. It returns (results in job order,
    failure)."""
    MODEL_IDS = qwen_edit.MODEL_IDS
    SelectionError = qwen_edit.SelectionError
    Unavailable = qwen_edit.Unavailable

    def __init__(self):
        self.calls = {"selection_problem": [], "wait_for_memory": [], "run_jobs": []}
        self.reset()
        for name in ("cli_selection", "settings", "label", "multiple", "memory_floor", "generator_text"):
            setattr(self, name, getattr(qwen_edit, name))

    def reset(self):
        self.outcomes, self.failure, self.interrupt_after, self.wait_error = {}, None, None, None

    def selection_problem(self, model_id, loras):
        self.calls["selection_problem"].append((model_id, loras))
        return None

    def wait_for_memory(self, floor, label, tag="seed-edit"):
        self.calls["wait_for_memory"].append((floor, label, tag))
        if self.wait_error is not None:
            raise self.wait_error

    def run_jobs(self, model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None,
                 noun="job"):
        self.calls["run_jobs"].append({"model_id": model_id, "loras": loras, "jobs": [dict(j) for j in jobs],
                                       "size": (width, height), "skill": skill, "work_dir": work_dir, "noun": noun})
        results, stopped = [], False
        for job in jobs:
            n = job["n"]
            outcome = "stop" if stopped else self.outcomes.get(n, "ok")
            if outcome == "stop":
                stopped = True
                results.append({"n": n, "output_path": job["output_path"], "status": "failed", "seconds": None})
                continue
            if outcome == "ok":
                Image.new("RGB", (width, height), (0, 0, 40 * n)).save(job["output_path"])
            result = {"n": n, "output_path": job["output_path"], "status": outcome, "seconds": 12.5}
            on_result(dict(result))
            results.append(result)
            if self.interrupt_after == n:
                raise KeyboardInterrupt()
        return results, self.failure


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """Spec 6.1: HOME, HF_HOME and Z_IMAGE_HF_HOME under tmp_path, no HF_HUB_CACHE and no SEED_EDIT_* variable;
    _story_dir is <tmp>/stories/<id> and _qwen_edit the multi-job fake. Returns {"tmp", "fake"}."""
    tmp = str(tmp_path)
    monkeypatch.setenv("HOME", os.path.join(tmp, "home"))
    for key in list(os.environ):
        if key.startswith("SEED_EDIT_"):
            monkeypatch.delenv(key)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", os.path.join(tmp, "hf"))
    monkeypatch.setenv("Z_IMAGE_HF_HOME", os.path.join(tmp, "zi"))
    fake = _FakeShotsQwenEdit()
    monkeypatch.setattr(movie, "_qwen_edit", lambda: fake)
    monkeypatch.setattr(movie, "_story_dir", lambda story_id: os.path.join(tmp, "stories", story_id))
    return {"tmp": tmp, "fake": fake}


def _seed_jpeg(path, color=(0, 200, 0)):
    """QET28's seed: a 200x100 JPEG whose EXIF orientation 6 makes it 100x200 when oriented."""
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (200, 100), color).save(path, "JPEG", exif=exif.tobytes())
    return path


def _write_story(tmp, story_id="s1", text=None):
    """<tmp>/stories/<story_id>/story.md with text (SHOTS_STORY by default); returns the story directory."""
    story_dir = os.path.join(tmp, "stories", story_id)
    os.makedirs(story_dir, exist_ok=True)
    with open(os.path.join(story_dir, "story.md"), "w", encoding="utf-8") as f:
        f.write(SHOTS_STORY if text is None else text)
    return story_dir


def _phase_args(tmp, **overrides):
    """Spec 6.1's phase args: a shots seed run of story s1 at 704x448, image seed 3, qwen21-q4 + uncensored @ 1,
    the seed <tmp>/seed.jpg (written on first use)."""
    seed = os.path.join(tmp, "seed.jpg")
    if not os.path.isfile(seed):
        _seed_jpeg(seed)
    values = dict(story_id="s1", seed_image=seed, video_width=704, video_height=448, image_seed=3,
                  seed_edit={"qwen_model": "qwen21-q4", "loras": UNC}, shots=True, redo_panels=[],
                  cast_members=[], location_pins=[], story_engine="robust", no_auto_lora=True, panels=3,
                  force_story=False, global_stills_loras=[], stills_lora_path=None)
    values.update(overrides)
    return argparse.Namespace(**values)


def _record(story_dir):
    with open(os.path.join(story_dir, "seed_edits.json"), encoding="utf-8") as f:
        return json.load(f)


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _jobs(fake):
    """The panel numbers of every run_jobs call, one list per call."""
    return [[job["n"] for job in call["jobs"]] for call in fake.calls["run_jobs"]]


def _prompt(n, images=IMAGES):
    return PREFIX + images[n - 1] + " " + STYLE


def _still(story_dir, n):
    return os.path.join(story_dir, "images", "panel_%02d.png" % n)


def _blocked_text(story_dir, panels):
    return ("Error: the content screen blocked the Qwen edit of the seed (Qwen-Image-2.1 q4) for panels %s of story "
            "s1; the movie stops here rather than use an unscreened, unedited or text-rendered still. Change those "
            "panels' Image: lines in %s, then rerun: every other panel's recorded still is reused\n"
            % (panels, os.path.join(story_dir, "story.md")))


# --- SET4 (SE8, SEK3): Phase 2 dispatches a shots seed run, and only it -------------------------------------

def test_set4_phase_2_dispatches_shots_seed_runs(clean_env, monkeypatch, capsys):
    calls = {"seed": [], "shots": [], "run": []}
    monkeypatch.setattr(movie, "_phase2_shots_seed", lambda args: calls["seed"].append(args) or 0)
    monkeypatch.setattr(movie, "_phase2_shots", lambda args, cmd: calls["shots"].append(list(cmd)) or 0)
    monkeypatch.setattr(movie.subprocess, "run",
                        lambda *a, **k: calls["run"].append(a) or types.SimpleNamespace(returncode=0))
    monkeypatch.setattr(movie, "_stream_and_tee", lambda cmd, log_path: calls["run"].append(cmd) or 0)
    args = _phase_args(clean_env["tmp"])
    assert movie.phase2_stills(args) == 0
    assert calls == {"seed": [args], "shots": [], "run": []}
    assert capsys.readouterr().out == "=== Phase 2: stills ===\n"
    plain = _phase_args(clean_env["tmp"], seed_image=None, seed_edit=None)
    assert movie.phase2_stills(plain) == 0
    assert len(calls["seed"]) == 1 and calls["run"] == [] and len(calls["shots"]) == 1
    assert "--seed-image" not in calls["shots"][0]


# --- SET5 (SE9-SE13, SE15, SE18, SEK4): every panel is a Qwen edit of the seed, in one batch ---------------

def test_set5_every_panel_is_a_qwen_edit_of_the_seed(clean_env, capsys):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    story_dir = _write_story(tmp)
    args = _phase_args(tmp)
    assert movie.SHOTS_SEED_EDIT_PREFIX == PREFIX and movie.SHOTS_SEED_LORA_NOTE == LORA_NOTE
    assert (movie.SHOTS_SEED_EDIT_SKILL, movie.SHOTS_SEED_EDITS_SCHEMA) == (
        "ltx_movie_shots_seed_edit", "ltx-movie.seed-edits.v1")
    assert movie._phase2_shots_seed(args) == 0
    work = os.path.join(story_dir, "seed_edits")
    original = os.path.join(story_dir, "seed-original.png")
    (call,) = fake.calls["run_jobs"]
    assert call == {"model_id": "qwen21-q4", "loras": UNC, "size": (704, 448), "skill": "ltx_movie_shots_seed_edit",
                    "work_dir": work, "noun": "panel",
                    "jobs": [{"n": n, "seed": 3, "prompt": _prompt(n), "source": original,
                              "stage_path": os.path.join(work, "panel_%02d.pending.png" % n),
                              "output_path": os.path.join(work, "panel_%02d.png" % n)} for n in (1, 2, 3)]}
    assert fake.calls["wait_for_memory"] == [(20.0, "Qwen-Image-2.1 q4", "ltx-movie")]
    assert fake.calls["selection_problem"] == []
    with Image.open(original) as img:
        assert (img.format, img.size) == ("PNG", (100, 200))
    record = _record(story_dir)
    assert list(record) == ["schema", "updated", "panels"] and record["schema"] == "ltx-movie.seed-edits.v1"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", record["updated"])
    settings = qwen_edit.settings("qwen21-q4", UNC)
    assert len(record["panels"]) == 3
    for n, entry in enumerate(record["panels"], start=1):
        with Image.open(_still(story_dir, n)) as img:
            assert (img.format, img.size) == ("PNG", (1408, 896))
        assert list(entry) == ENTRY_KEYS
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", entry["created"])
        assert dict(entry, created=None) == {
            "n": n, "status": "ok", "created": None, "label": "Qwen-Image-2.1 q4",
            "source": os.path.abspath(args.seed_image), "source_sha256": _sha(args.seed_image),
            "original": "seed-original.png", "prompt": _prompt(n), "seed": 3, "width": 704, "height": 448,
            "still_width": 1408, "still_height": 896, "qwen_model": settings["qwen_model"],
            "loras": settings["loras"], "steps": 40, "scheduler": "linear",
            "output": "seed_edits/panel_%02d.png" % n, "still": "images/panel_%02d.png" % n,
            "still_sha256": _sha(_still(story_dir, n)), "seconds": 12.5, "error": None}
        assert os.path.isfile(os.path.join(work, "panel_%02d.png" % n))
    assert glob.glob(os.path.join(story_dir, "images", "*.tmp")) == []
    assert not os.path.exists(os.path.join(story_dir, "seed_edit.json"))
    assert not os.path.exists(os.path.join(story_dir, "images", "images.json"))
    assert not os.path.exists(os.path.join(story_dir, "redo"))
    assert capsys.readouterr().out.splitlines() == [
        "seed edits: %s; 704x448, fitted into 1408x896 stills; seed 3; panels 1,2,3 of 3, each prompted by its own "
        "Image: text" % qwen_edit.generator_text("qwen21-q4", UNC)] + [
        "panel %d -> %s (Qwen edit of the seed, 12.5s)" % (n, _still(story_dir, n)) for n in (1, 2, 3)] + [
        "seed edits: 3 panel stills written"]


# --- SET6 (SE17, SEK5): a blocked panel fails the phase, with no still and no fallback ----------------------

def test_set6_a_blocked_panel_fails_the_phase(clean_env, capsys):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    story_dir = _write_story(tmp)
    fake.outcomes = {2: "blocked"}
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 1
    captured = capsys.readouterr()
    assert captured.err == _blocked_text(story_dir, "2")
    assert "panel 2 BLOCKED: the content screen blocked the Qwen edit of the seed" in captured.out.splitlines()
    entries = _record(story_dir)["panels"]
    assert [e["status"] for e in entries] == ["ok", "blocked", "ok"]
    assert [entries[1][k] for k in ("output", "still", "still_sha256", "seconds", "error")] == [
        None, None, None, 12.5, None]
    assert [os.path.exists(_still(story_dir, n)) for n in (1, 2, 3)] == [True, False, True]


# --- SET7 (SE16, SE17, SEK6): a failed batch keeps its finished panels, and the rerun edits the rest -------

def test_set7_a_failed_batch_keeps_the_finished_panels(clean_env, capsys):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    story_dir = _write_story(tmp)
    fake.outcomes, fake.failure = {2: "stop"}, "Qwen-Image-2.1 q4 child exited 1: boom"
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 1
    assert capsys.readouterr().err == ("Error: the seed edits failed: Qwen-Image-2.1 q4 child exited 1: boom (kept: "
                                       "1; edited on the next run: 2,3)\n")
    assert [(e["n"], e["status"], e["error"], e["seconds"]) for e in _record(story_dir)["panels"]] == [
        (1, "ok", None, 12.5), (2, "failed", "Qwen-Image-2.1 q4 child exited 1: boom", None),
        (3, "failed", "Qwen-Image-2.1 q4 child exited 1: boom", None)]
    fake.reset()
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    assert _jobs(fake) == [[1, 2, 3], [2, 3]]
    assert ("seed edits: reusing the stills of panels 1 (recorded edits of the same seed image, prompt, seed and "
            "settings)") in capsys.readouterr().out.splitlines()
    assert [e["status"] for e in _record(story_dir)["panels"]] == ["ok"] * 3


# --- SET8 (SE16, SEK6): an interrupted batch leaves ok entries only for the stills it finished -------------

def test_set8_an_interrupted_batch_records_only_finished_stills(clean_env, capsys):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    story_dir = _write_story(tmp)
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    first = _record(story_dir)["panels"]
    old_03 = _sha(_still(story_dir, 3))
    changed = [IMAGES[0], IMAGES[1] + " Rain falls harder.", IMAGES[2] + " Rain falls harder."]
    _write_story(tmp, text=_story_md(changed))
    fake.interrupt_after = 2
    with pytest.raises(KeyboardInterrupt):
        movie._phase2_shots_seed(_phase_args(tmp))
    entries = _record(story_dir)["panels"]
    assert [(e["n"], e["status"]) for e in entries] == [(1, "ok"), (2, "ok")]
    assert entries[0] == first[0] and entries[1]["prompt"] == _prompt(2, changed)
    moved = glob.glob(os.path.join(story_dir, "redo", "*", "images", "panel_03.png"))
    assert len(moved) == 1 and _sha(moved[0]) == old_03
    assert not os.path.exists(_still(story_dir, 3))
    fake.reset()
    capsys.readouterr()
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    assert _jobs(fake) == [[1, 2, 3], [2, 3], [3]]


# --- SET9 (SE13, SEK4): a rerun edits exactly the panels whose key changed ----------------------------------

def test_set9_a_rerun_edits_exactly_the_changed_panels(clean_env, capsys):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    story_dir = _write_story(tmp)
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    capsys.readouterr()
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    assert len(fake.calls["run_jobs"]) == 1 and len(fake.calls["wait_for_memory"]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "seed edits: reusing the stills of panels 1,2,3 (recorded edits of the same seed image, prompt, seed and "
        "settings)",
        "seed edits: every panel's still is a recorded edit of the same seed image, prompt, seed and settings; "
        "nothing to edit"]

    def edits_after(story_id, **overrides):
        """The panels a rerun of a fresh all-ok copy of the story edits after overrides."""
        _write_story(tmp, story_id)
        assert movie._phase2_shots_seed(_phase_args(tmp, story_id=story_id)) == 0
        before = len(fake.calls["run_jobs"])
        assert movie._phase2_shots_seed(_phase_args(tmp, story_id=story_id, **overrides)) == 0
        return [job["n"] for call in fake.calls["run_jobs"][before:] for job in call["jobs"]]

    other = _seed_jpeg(os.path.join(tmp, "seed-red.jpg"), color=(200, 0, 0))
    assert edits_after("s-seed", seed_image=other) == [1, 2, 3]
    assert edits_after("s-image-seed", image_seed=4) == [1, 2, 3]
    assert edits_after("s-q8", seed_edit={"qwen_model": "qwen21-q8", "loras": UNC}) == [1, 2, 3]
    assert edits_after("s-scale", seed_edit={"qwen_model": "qwen21-q4",
                                             "loras": [{"id": "uncensored", "scale": 0.5}]}) == [1, 2, 3]
    capsys.readouterr()
    old_02 = _sha(_still(story_dir, 2))
    _write_story(tmp, text=_story_md([IMAGES[0], IMAGES[1] + " Gulls circle overhead.", IMAGES[2]]))
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    assert _jobs(fake)[-1] == [2]
    (moved,) = glob.glob(os.path.join(story_dir, "redo", "*", "images", "panel_02.png"))
    assert re.fullmatch(r"\d{8}T\d{6}Z-%d" % os.getpid(), os.path.basename(os.path.dirname(os.path.dirname(moved))))
    assert _sha(moved) == old_02
    assert ("seed edits: moved %s -> %s (not a recorded edit of this seed image, prompt, seed and settings)"
            % (_still(story_dir, 2), moved)) in capsys.readouterr().out.splitlines()
    Image.new("RGB", (1408, 896), (9, 9, 9)).save(_still(story_dir, 3))
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    assert _jobs(fake)[-1] == [3]
    assert movie._phase2_shots_seed(_phase_args(tmp, redo_panels=[1])) == 0
    assert _jobs(fake)[-1] == [1]


# --- SET10 (SE17): the memory wait or the install check fails every panel, before any child --------------

def test_set10_an_unavailable_selection_fails_every_panel(clean_env, capsys):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    story_dir = _write_story(tmp)
    text = "only 10.0 GiB available after waiting 0 s; Qwen-Image-2.1 q4 needs 20 GiB; free memory and retry"
    fake.wait_error = qwen_edit.Unavailable(text)
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 1
    assert capsys.readouterr().err == ("Error: the seed edits failed: %s (kept: none; edited on the next run: "
                                       "1,2,3)\n" % text)
    assert [(e["status"], e["error"], e["seconds"], e["output"]) for e in _record(story_dir)["panels"]] == [
        ("failed", text, None, None)] * 3
    assert fake.calls["run_jobs"] == []


# --- SET11 (SE14): one note when a Z-Image stills LoRA would have applied -----------------------------------

def test_set11_the_stills_lora_note(clean_env, capsys):
    tmp = clean_env["tmp"]
    _write_story(tmp)
    member = types.SimpleNamespace(stills_lora="/x.safetensors")
    assert movie._phase2_shots_seed(_phase_args(tmp, cast_members=[member])) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == LORA_NOTE and out.count(LORA_NOTE) == 1
    _write_story(tmp, "s2")
    assert movie._phase2_shots_seed(_phase_args(tmp, story_id="s2")) == 0
    assert LORA_NOTE not in capsys.readouterr().out


# --- SET12 (SE13): a panel without Image: text, or a story without panels, stops before any write ---------

def test_set12_a_panel_without_an_image_line(clean_env, capsys):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    story_dir = _write_story(tmp, text=_story_md([IMAGES[0], None, IMAGES[2]]))
    story_md = os.path.join(story_dir, "story.md")
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 1
    assert capsys.readouterr().err == ("Error: panel 2 of %s has no Image: description to edit the seed with\n"
                                       % story_md)
    assert not os.path.exists(os.path.join(story_dir, "seed-original.png"))
    assert not os.path.exists(os.path.join(story_dir, "seed_edits.json"))
    assert fake.calls["run_jobs"] == [] and fake.calls["wait_for_memory"] == []
    _write_story(tmp, text="# Empty\n\nNo panels.\n")
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 1
    assert capsys.readouterr().err == "Error: %s has no panels to edit the seed into\n" % story_md
    assert not os.path.exists(os.path.join(story_dir, "seed_edits.json"))


# --- SET15 (SE15, SEK4, SEK5): the real runner, one mflux child, every output screened ---------------------

def test_set15_the_real_runner_screens_every_panel(env):
    py, _snapshot, _lora = _mflux_ready(env)
    st.stub_config(py, {"red": [2]})
    tmp, mp = env["tmp"], env["mp"]
    mp.setattr(movie, "_qwen_edit", lambda: qwen_edit)
    mp.setattr(movie, "_story_dir", lambda story_id: os.path.join(tmp, "stories", story_id))
    story_dir = _write_story(tmp)
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 1
    (call,) = st.stub_calls(py)
    original = os.path.join(story_dir, "seed-original.png")
    assert [(j["n"], j["prompt"], j["source"]) for j in call["spec"]["jobs"]] == [
        (n, _prompt(n), original) for n in (1, 2, 3)]
    assert env["calls"]["safety"] == [{"skill": "ltx_movie_shots_seed_edit", "prompt": _prompt(n), "size": (704, 448)}
                                      for n in (1, 2, 3)]
    for n in (1, 3):
        with Image.open(_still(story_dir, n)) as img:
            assert img.size == (1408, 896)
    assert not os.path.exists(_still(story_dir, 2))
    assert [e["status"] for e in _record(story_dir)["panels"]] == ["ok", "blocked", "ok"]


# --- Review Focus 1: the story the default engine writes in shots mode (no Style:, Dialogue: lines) -------

def test_sse_review_focus_1_the_robust_engine_shots_story(clean_env):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    story_dir = _write_story(tmp, text=_story_md(style=None, dialogue=True))
    assert movie._shots_seed_prompts(os.path.join(story_dir, "story.md")) == [
        (n, PREFIX + IMAGES[n - 1]) for n in (1, 2, 3)]
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    assert [job["prompt"] for job in fake.calls["run_jobs"][0]["jobs"]] == [PREFIX + image for image in IMAGES]


# --- Review Focus 2: --redo of a shots seed story re-edits only its panels ----------------------------------

def test_sse_review_focus_2_a_redo_re_edits_only_its_panels(clean_env, capsys):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    story_dir = _write_story(tmp)
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    first = _record(story_dir)["panels"]
    old_02 = _sha(_still(story_dir, 2))
    args = _phase_args(tmp, redo_panels=[2])
    assert movie.phase_redo_shots(args) == 0
    capsys.readouterr()
    assert movie.phase2_stills(args) == 0
    out = capsys.readouterr().out.splitlines()
    assert _jobs(fake) == [[1, 2, 3], [2]]
    assert out[:2] == ["=== Phase 2: stills ===",
                       "seed edits: reusing the stills of panels 1,3 (recorded edits of the same seed image, prompt, "
                       "seed and settings)"]
    assert [line for line in out if line.startswith("seed edits: moved ")] == []
    (moved,) = glob.glob(os.path.join(story_dir, "redo", "*", "images", "panel_02.png"))
    assert _sha(moved) == old_02
    entries = _record(story_dir)["panels"]
    assert (entries[0], entries[2]) == (first[0], first[2])
    assert entries[1]["status"] == "ok" and entries[1]["still_sha256"] == _sha(_still(story_dir, 2))


# --- Review Focus 3: the legacy diffusers model (qwen2511-bf16) edits every panel in its own child ---------

PANEL_QWENEDIT_STUB = st.QWENEDIT_STUB.replace("int(name[5:7])", "int(name[6:8])")   # panel_NN.pending.png


def test_sse_review_focus_3_the_legacy_diffusers_model(env):
    assert PANEL_QWENEDIT_STUB != st.QWENEDIT_STUB
    tmp, mp = env["tmp"], env["mp"]
    _bf16_cache(env)
    stub = st.qwenedit_stub(env, {"blocked": [2]})
    with open(stub, "w", encoding="utf-8") as f:
        f.write(PANEL_QWENEDIT_STUB)
    mp.setattr(qwen_edit, "avail_gib", lambda: 80.0)
    mp.setattr(movie, "_qwen_edit", lambda: qwen_edit)
    mp.setattr(movie, "_story_dir", lambda story_id: os.path.join(tmp, "stories", story_id))
    story_dir = _write_story(tmp)
    assert movie._phase2_shots_seed(_phase_args(tmp, seed_edit={"qwen_model": "qwen2511-bf16", "loras": []})) == 1
    (call,) = st.stub_calls(stub)
    work = os.path.join(story_dir, "seed_edits")
    spec = call["spec"]
    assert (spec["image"], spec["skill"]) == (os.path.join(story_dir, "seed-original.png"), "ltx_movie_shots_seed_edit")
    assert spec["jobs"] == [{"prompt": _prompt(n), "output_path": os.path.join(work, "panel_%02d.pending.png" % n),
                             "seed": 3, "width": 704, "height": 448} for n in (1, 2, 3)]
    assert [e["status"] for e in _record(story_dir)["panels"]] == ["ok", "blocked", "ok"]
    assert [os.path.isfile(_still(story_dir, n)) for n in (1, 2, 3)] == [True, False, True]
    assert env["calls"]["safety"] == []


# --- Review Focus 4: a block and a failure in the same batch ------------------------------------------------

def test_sse_review_focus_4_a_block_and_a_failure_in_one_batch(clean_env, capsys):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    story_dir = _write_story(tmp)
    fake.outcomes, fake.failure = {2: "blocked", 3: "stop"}, "Qwen-Image-2.1 q4 child timed out after 3600 s"
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 1
    assert capsys.readouterr().err == (
        "Error: the seed edits failed: Qwen-Image-2.1 q4 child timed out after 3600 s (kept: 1; edited on the next "
        "run: 2,3)\n" + _blocked_text(story_dir, "2"))
    assert [(e["status"], e["error"]) for e in _record(story_dir)["panels"]] == [
        ("ok", None), ("blocked", None), ("failed", "Qwen-Image-2.1 q4 child timed out after 3600 s")]
    fake.reset()
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    assert _jobs(fake) == [[1, 2, 3], [2, 3]] and len(fake.calls["wait_for_memory"]) == 2
```

- [ ] **Step 2: Run the new tests to verify they fail.**

Run: `cd $S/ss-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_ltx_movie_shots_seed.py tests/test_qwen_edit.py::test_qet11_imports_and_the_new_files 2>&1 | tail -3`
Expected: `14 failed, 1 passed`: every test of `tests/test_ltx_movie_shots_seed.py` fails with an `AttributeError` (SET4: `<module 'ltx_movie_sse' from '.../bin/ltx-movie'> has no attribute '_phase2_shots_seed'`, raised by `monkeypatch.setattr`; SET5: `module 'ltx_movie_sse' has no attribute 'SHOTS_SEED_EDIT_PREFIX'`; Review Focus 1: `... has no attribute '_shots_seed_prompts'`; the other 11: `module 'ltx_movie_sse' has no attribute '_phase2_shots_seed'`); QET11 passes.

- [ ] **Step 3: Write the implementation.**

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
SEED_EDIT_SKILL = "ltx_movie_seed_edit"
SEED_EDIT_SCHEMA = "ltx-movie.seed-edit.v1"
```

with:

```python
SEED_EDIT_SKILL = "ltx_movie_seed_edit"
SEED_EDIT_SCHEMA = "ltx-movie.seed-edit.v1"
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

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
def phase2_stills(args):
    paths = _story_paths(args.story_id)
    print("=== Phase 2: stills ===")
```

with:

```python
def phase2_stills(args):
    paths = _story_paths(args.story_id)
    print("=== Phase 2: stills ===")
    if getattr(args, "shots", False) and getattr(args, "seed_image", None):
        return _phase2_shots_seed(args)       # shots seed edits SE8: every still is a Qwen edit of the seed
```

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    args.seed_edited_path = files["edited"]
    print("seed edit: %s (%.1f s)" % (files["edited"], result["seconds"]))
    return 0
```

with:

```python
    args.seed_edited_path = files["edited"]
    print("seed edit: %s (%.1f s)" % (files["edited"], result["seconds"]))
    return 0


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

- [ ] **Step 4: Run the tests and the compile check; verify they pass.**

Run: `cd $S/ss-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_ltx_movie_shots_seed.py tests/test_qwen_edit.py tests/test_ltx_movie_seed_edit.py tests/test_shots_mode.py tests/test_dialogue.py::test_dk3_import_sets_are_unchanged tests/test_movie_ui_builder.py 2>&1 | tail -1 && python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1`
Expected: only `test_mut26_pipeline_files_are_unchanged` fails (expected), every other test passes (in the planning replay: `1 failed, 127 passed`); `OK 347/347`.

Run the compile check with `FILES` = `bin/ltx-movie tests/test_ltx_movie_shots_seed.py tests/test_qwen_edit.py tests/test_movie_ui_builder.py`. Expected: `compiled 4` twice.

- [ ] **Step 5: The gate.** Run the gate block with `N=1`. Expected: `GATE PASS`, `lost 1 (listed 1, unexpected 0); new tests 14, not passing 0; baseline failures still failing 2 of 2` (the one listed loss is the expected failure `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged`, from this task until Task 5; the 14 new tests are SET4-SET12, SET15 and Review Focus 1-4), `disk ok`, `offline unchanged`.

- [ ] **Step 6: Commit.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/ss-wt/qwen-agent-workspace
git add bin/ltx-movie tests/test_ltx_movie_shots_seed.py tests/test_qwen_edit.py tests/test_movie_ui_builder.py
git diff --cached --name-only    # expected: exactly those four paths
git commit -m "ltx-movie: Phase 2 of shots mode with a seed image edits the seed into every panel in one screened Qwen batch, recorded in seed_edits.json (shots seed edits SE1, SE8-SE18, SET4-SET12, SET15)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The CLI: `--shots --seed-image` rules, the story prompt, the phase tuple, the dry run and the help (pinned: `bin/ltx-movie`) (SE2-SE7, SE19-SE22; SET1-SET3, SET13, SET14)

This task implements, in `bin/ltx-movie`:
- SE2: `_resolve_shots` allows `--shots --seed-image` with `--seed-edit-model ID` and refuses the legacy engine, a missing or `as-is` model, and `--stills-lora` (SE3: `_resolve_seed_edit` unchanged).
- SE4: the three help texts; SE5: the docstring sentence (R13).
- SE6: `build_story_prompt`'s seed preface is off in shots mode (R7); SE7: `_phase_sequence` inserts no Phase 1c in shots mode.
- SE19: `_print_shots_seed_plan` and the Phase 2 dry-run branch; SE20: the Phase 0 dry-run text and the Phase 1c block condition.
- SE21, SE22 need no code (Phases 3-4, `build_pkg.py` unchanged).
- Tests: SET1-SET3, SE4/SE5 (R8), SET13, SET14 in `tests/test_ltx_movie_shots_seed.py` (R12); S33's text in `tests/test_shots_mode.py` (spec 6.3).

**Files:**
- Modify: `bin/ltx-movie` (line numbers at `7a79ea9`, before Task 1's edits: docstring `:97-98`; parser `:312-313`, `:318-319`, `:408-409`; `build_story_prompt` `:247-248`; `_resolve_shots` `:1251-1255`; after `_print_shots_stills_plan` `:2643-2646`; `_print_dry_run_plan` Phase 0 `:2702-2707`, Phase 1c `:2731-2732`, Phase 2 `:2745-2746`; `_phase_sequence` `:2840`).
- Modify: `tests/test_ltx_movie_shots_seed.py`, `tests/test_shots_mode.py` (S33 `:937-938`).

**Interfaces:**
- Consumes (Task 1): `_shots_seed_paths`, `_shots_seed_plan(args, qe)`, `SHOTS_SEED_EDIT_SKILL`, `_phase2_shots_seed` (SET13 builds its record with it); existing `_qwen_edit()`, `_seed_edit_size`, `_still_size`, `_story_paths`, `_panel_list`, `SEED_MIN_EDGE`, `SEED_DOWNSCALE_MAX_EDGE`.
- Produces: `_print_shots_seed_plan(args) -> None`; the CLI contract `--shots --seed-image P --seed-edit-model ID [--seed-edit-lora ID=S ...]` (exit 2 with the three SE2 texts otherwise); shots seed phase tuples `(phase0_seed, phase1_story, [phase_release_story_server,] [phase_redo_shots,] phase2_stills, phase3_manifest, phase4_render)` (Task 3's `job_phases` mirrors them).

- [ ] **Step 1: Write the failing tests and the spec 6.3 edit.**

Edit `tests/test_shots_mode.py`: replace this text, which occurs exactly once:

```python
         "Error: --shots is not supported with --seed-image: the seed image can be only panel 1's "
         "still, and the seed-image story preface describes the chained flow"),
```

with:

```python
         "Error: --shots with --seed-image needs --seed-edit-model ID: every panel's still is a Qwen edit of "
         "the seed, so the seed cannot be used as-is"),
```

Edit `tests/test_ltx_movie_shots_seed.py`: replace this text, which occurs exactly once:

```python
# --- SET4 (SE8, SEK3): Phase 2 dispatches a shots seed run, and only it -------------------------------------
```

with:

```python
# --- SET1 (SE2): the option rules of --shots with --seed-image -----------------------------------------------

def _parse(*extra):
    return movie.build_parser().parse_args(["a narrative", "--story-id", "s1"] + list(extra))


MODEL_RULE = ("Error: --shots with --seed-image needs --seed-edit-model ID: every panel's still is a Qwen edit of the "
              "seed, so the seed cannot be used as-is\n")
ENGINE_RULE = ("Error: --shots with --seed-image needs the default story engine; it cannot be combined with %s\n")
STILLS_RULE = ("Error: --stills-lora cannot be combined with --shots and --seed-image: every panel's still is a Qwen "
               "edit of the seed, and Z-Image stills LoRAs do not apply to it\n")


def test_set1_the_shots_seed_option_rules(clean_env, capsys):
    tmp = clean_env["tmp"]
    seed = st.png(os.path.join(tmp, "seed.png"), (64, 64))
    override = os.path.join(tmp, "prompt.txt")
    with open(override, "w", encoding="utf-8") as f:
        f.write("x")
    shots = ["--shots", "--seed-image", seed]
    cases = [((), MODEL_RULE), (("--seed-edit-model", "as-is"), MODEL_RULE),
             (("--seed-edit-model", "qwen21-q4", "--story-legacy"), ENGINE_RULE % "--story-legacy"),
             (("--seed-edit-model", "qwen21-q4", "--story-prompt-override", override),
              ENGINE_RULE % "--story-prompt-override"),
             (("--seed-edit-model", "qwen21-q4", "--stills-lora", os.path.join(tmp, "x.safetensors")), STILLS_RULE)]
    for extra, text in cases:
        args = _parse(*(shots + list(extra)))
        assert movie._resolve_shots(args) == 2, extra
        assert capsys.readouterr().err == text, extra
    args = _parse(*(shots + ["--seed-edit-model", "qwen21-q4"]))
    assert movie._resolve_shots(args) == 0 and args.redo_panels == []
    _write_story(tmp)
    args = _parse(*(shots + ["--seed-edit-model", "qwen21-q4", "--redo", "2"]))
    assert movie._resolve_shots(args) == 0 and args.redo_panels == [2]
    assert capsys.readouterr().err == ""


# --- SET2 (SE6): the shots story prompt has no seed preface ------------------------------------------------

def test_set2_the_shots_story_prompt_has_no_seed_preface():
    seeded = movie.build_story_prompt("N", "sid", 3, False, True, seconds="6", shots=True)
    assert seeded == movie.build_story_prompt("N", "sid", 3, seconds="6", shots=True)
    assert movie.SEED_IMAGE_PREFACE not in seeded and movie.SEED_IMAGE_POSTFACE not in seeded
    chained = movie.build_story_prompt("N", "sid", 3, False, True, seconds="6")
    assert chained.startswith(movie.SEED_IMAGE_PREFACE) and chained.endswith(movie.SEED_IMAGE_POSTFACE)


# --- SET3 (SE7, SEK3): a shots seed run has the ordinary shots phase tuple, with no Phase 1c ------------------

class _SeqArgs(object):
    """_phase_sequence's inputs for a shots seed run with a seed edit; keyword arguments override."""

    def __init__(self, **kwargs):
        self.no_stills, self.story_server_stop_after_story, self.seed_image = False, False, "x.png"
        self.story_only, self.shots, self.redo_panels = False, True, []
        self.seed_edit = {"qwen_model": "qwen21-q4", "loras": UNC}
        self.min_avail_gib, self.avail_timeout = 25.0, 1800
        for key, value in kwargs.items():
            setattr(self, key, value)


def _names(args):
    return tuple(p.__name__ for p in movie._phase_sequence(args))


def test_set3_shots_seed_runs_have_no_phase_1c():
    assert _names(_SeqArgs(story_server_stop_after_story=True)) == (
        "phase0_seed", "phase1_story", "phase_release_story_server", "phase2_stills", "phase3_manifest",
        "phase4_render")
    assert _names(_SeqArgs(story_server_stop_after_story=True, redo_panels=[2])) == (
        "phase0_seed", "phase1_story", "phase_release_story_server", "phase_redo_shots", "phase2_stills",
        "phase3_manifest", "phase4_render")
    assert _names(_SeqArgs(story_only=True)) == ("phase0_seed", "phase1_story")
    assert _names(_SeqArgs(story_server_stop_after_story=True, shots=False)) == (
        "phase0_seed", "phase1_story", "phase_release_story_server", "phase_seed_edit", "phase2_stills",
        "phase3_manifest", "phase4_render")


# --- SE4, SE5 (plan ruling R8): the three help texts and the docstring sentence ------------------------------

HELP = {
    "--seed-image": (
        "image that becomes the movie's literal first frame: Phase 0 derives the video width/height from its aspect "
        "ratio (1:3 to 3:1) and attaches a scaled copy to the Phase 1 story prompt; Phase 2 fits the ORIGINAL "
        "(scaled, never cropped) into panel_01.png at twice the video size, same as z_image, so ltx-2-mlx's own "
        "downscale keeps more real detail. With --shots, Phase 2 instead edits the ORIGINAL into every panel's "
        "still (see --seed-edit-model). Incompatible with --no-stills and with --video-width/--video-height."),
    "--seed-edit-model": (
        "with --seed-image: edit the seed into panel 1 with a Qwen registry edit model (qwen21-q4, qwen21-q8, "
        "qwen21-bf16, qwen2511-q4, qwen2511-bf16), prompted by panel 1's Image: text after Phase 1 and screened "
        "with content safety; as-is, like leaving the flag out, uses the seed unchanged. With --shots it is "
        "required and as-is is refused: every panel's still is an edit of the seed, each prompted by its own "
        "Image: text. See docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md and "
        "2026-11-05-compose-shots-seed-edit-design.md."),
    "--shots": (
        "shots mode: every panel is its own shot with its own Image: still and is rendered from that still (no "
        "chaining; cuts between panels). Phase 1 uses the shots story template and enforces the shot rules (one "
        "action per Motion:, at most two cast characters per shot), Phase 2 renders a still for every panel, and "
        "every cast character LoRA defaults to 0.8. With --seed-image, every panel's still is instead a Qwen edit "
        "of the seed (--seed-edit-model ID, required). See docs/superpowers/specs/2026-10-06-shots-mode-design.md.")}
DOC_SENTENCE = (
    "so that only they re-render. With --seed-image (docs/superpowers/specs/2026-11-05-compose-shots-seed-edit-"
    "design.md), Phase 2 instead edits the seed into every panel's still with the Qwen model of --seed-edit-model "
    "(required), in one child, each panel prompted by its own Image: text, screened, recorded in seed_edits.json "
    "and reused on a rerun when nothing changed. Story engine")


def test_se4_se5_the_help_texts_and_the_docstring():
    actions = dict((a.option_strings[0], a) for a in movie.build_parser()._actions if a.option_strings)
    for flag, text in HELP.items():
        assert actions[flag].help == text, flag
    assert DOC_SENTENCE in " ".join(movie.__doc__.split())


# --- SET4 (SE8, SEK3): Phase 2 dispatches a shots seed run, and only it -------------------------------------
```

Edit `tests/test_ltx_movie_shots_seed.py`: replace this text, which occurs exactly once:

```python
# --- SET15 (SE15, SEK4, SEK5): the real runner, one mflux child, every output screened ---------------------
```

with:

```python
# --- SET13 (SE19, SE20): the shots seed dry run ------------------------------------------------------------

def _dry(capsys, *extra):
    argv = ["a narrative", "--story-id", "s1", "--dry-run", "--no-review", "--no-auto-lora"] + list(extra)
    rc = movie.main(argv)
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    return captured.out


def _seed1920(tmp):
    """A 1920x1080 PNG seed (QET31's): the dry run derives the video geometry 576x320 from it."""
    path = os.path.join(tmp, "seed1920.png")
    if not os.path.isfile(path):
        Image.new("RGB", (1920, 1080), (40, 50, 60)).save(path)
    return path


SHOTS_DRY = ("Would edit the seed into every panel's still with %s at 576x320, seed 0, in one Qwen child: each panel "
             "is prompted by the shots seed-edit instruction and its own Image: text (and the Style: text) from "
             "story.md, screened with content safety (skill ltx_movie_shots_seed_edit), fitted (never cropped) into "
             "%s at 1152x640 and recorded in %s. Z-Image and stills LoRAs are not used. A blocked or failed panel "
             "stops the run after the batch; a rerun reuses every recorded edit.")


def test_set13_the_shots_seed_dry_run(clean_env, capsys):
    tmp, fake = clean_env["tmp"], clean_env["fake"]
    seed = _seed1920(tmp)
    story_dir = os.path.join(tmp, "stories", "s1")
    shots = ("--shots", "--seed-image", seed, "--seed-edit-model", "qwen21-q4")
    out = _dry(capsys, *shots)
    lines = out.splitlines()
    zero = [line for line in lines if line.startswith("Would validate ")]
    assert len(zero) == 1 and zero[0].endswith(
        "(long edge 1024px) to %s. Phase 2 edits the ORIGINAL into every panel's still with the Qwen edit model; "
        "nothing is cropped." % os.path.join(story_dir, "seed_downscaled.png"))
    assert "--- Phase 1c: seed edit ---" not in lines and "ltx-story-images" not in out
    i = lines.index("--- Phase 2: stills ---")
    assert lines[i:i + 5] == [
        "--- Phase 2: stills ---",
        SHOTS_DRY % (qwen_edit.generator_text("qwen21-q4", []), os.path.join(story_dir, "images", "panel_NN.png"),
                     os.path.join(story_dir, "seed_edits.json")),
        "Panels: decided at Phase 2, from story.md after Phase 1", "", "--- Phase 3: manifest + dry-run ---"]
    assert fake.calls == {"selection_problem": [], "wait_for_memory": [], "run_jobs": []}
    _write_story(tmp)
    assert movie._phase2_shots_seed(_phase_args(tmp, seed_image=seed, video_width=576, video_height=320,
                                                image_seed=0, seed_edit={"qwen_model": "qwen21-q4", "loras": []})) == 0
    _write_story(tmp, text=_story_md([IMAGES[0], IMAGES[1] + " Gulls circle overhead.", IMAGES[2]]))
    capsys.readouterr()
    assert "Panels to edit: 2; reused: 1,3" in _dry(capsys, *shots).splitlines()
    assert len(fake.calls["run_jobs"]) == 1 and fake.calls["selection_problem"] == []
    assert not os.path.exists(os.path.join(story_dir, "redo"))


# --- SET14 (SEK3): the chained and the plain shots dry runs are unchanged ------------------------------------

def test_set14_chained_and_plain_shots_dry_runs_are_unchanged(clean_env, capsys):
    seed = _seed1920(clean_env["tmp"])
    fits = "Phase 2 fits the ORIGINAL into panel_01.png at twice the video size; nothing is cropped."
    plain = _dry(capsys, "--seed-image", seed)
    assert fits in plain and "--- Phase 1c: seed edit ---" not in plain.splitlines()
    edited = _dry(capsys, "--seed-image", seed, "--seed-edit-model", "qwen21-q4")
    assert fits in edited and "--- Phase 1c: seed edit ---" in edited.splitlines()
    shots = _dry(capsys, "--shots")
    assert ("Stills groups: computed from story.md after Phase 1 -- one run per distinct set of cast stills LoRAs, "
            "each with --only <PANELS> (that group's panels):") in shots.splitlines()
    assert "Would edit the seed into every panel's still" not in shots


# --- SET15 (SE15, SEK4, SEK5): the real runner, one mflux child, every output screened ---------------------
```

- [ ] **Step 2: Run the new tests to verify they fail.**

Run: `cd $S/ss-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_ltx_movie_shots_seed.py tests/test_shots_mode.py::test_s33_resolve_shots_errors 2>&1 | tail -8`
Expected: `6 failed, 15 passed`. SET1 fails (stderr is `Error: --shots is not supported with --seed-image: ...`), SET2 fails (the shots prompt starts with `SEED_IMAGE_PREFACE`), SET3 fails (`phase_seed_edit` is in the shots tuple), SE4/SE5 fails (the old `--seed-image` help), SET13 fails (`main` returns 2 with the old refusal), S33 fails (the old text); SET14 passes (R9: it pins unchanged dry runs); Task 1's 14 tests pass.

- [ ] **Step 3: Write the implementation.**

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```text
paired. --redo N[,M] moves those panels' stills and clips, and movie.mp4, into
<story>/redo/<stamp>-<pid>/ so that only they re-render.
```

with:

```text
paired. --redo N[,M] moves those panels' stills and clips, and movie.mp4, into
<story>/redo/<stamp>-<pid>/ so that only they re-render. With --seed-image
(docs/superpowers/specs/2026-11-05-compose-shots-seed-edit-design.md), Phase 2 instead edits
the seed into every panel's still with the Qwen model of --seed-edit-model (required), in one
child, each panel prompted by its own Image: text, screened, recorded in seed_edits.json and
reused on a rerun when nothing changed.
```

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
                              "ltx-2-mlx's own downscale keeps more real detail. Incompatible "
                              "with --no-stills and with --video-width/--video-height.")
```

with:

```python
                              "ltx-2-mlx's own downscale keeps more real detail. With --shots, "
                              "Phase 2 instead edits the ORIGINAL into every panel's still (see "
                              "--seed-edit-model). Incompatible with --no-stills and with "
                              "--video-width/--video-height.")
```

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
                              "flag out, uses the seed unchanged. See docs/superpowers/specs/"
                              "2026-11-03-qwen-edit-models-design.md.")
```

with:

```python
                              "flag out, uses the seed unchanged. With --shots it is required and as-is is refused: "
                              "every panel's still is an edit of the seed, each prompted by its own Image: text. See "
                              "docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md and "
                              "2026-11-05-compose-shots-seed-edit-design.md.")
```

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
                              "cast character LoRA defaults to 0.8. See docs/superpowers/specs/"
                              "2026-10-06-shots-mode-design.md.")
```

with:

```python
                              "cast character LoRA defaults to 0.8. With --seed-image, every "
                              "panel's still is instead a Qwen edit of the seed (--seed-edit-model "
                              "ID, required). See docs/superpowers/specs/"
                              "2026-10-06-shots-mode-design.md.")
```

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    if seed_image and not no_stills:
        # The postface goes AFTER the rendered template on purpose. The template's
```

with:

```python
    if seed_image and not no_stills and not shots:
        # Shots seed edits SE6: the seed preface describes the chained flow; shots stories keep the shots template.
        # The postface goes AFTER the rendered template on purpose. The template's
```

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    if getattr(args, "seed_image", None):
        print("Error: --shots is not supported with --seed-image: the seed image can be only "
              "panel 1's still, and the seed-image story preface describes the chained flow",
              file=sys.stderr)
        return 2
```

with:

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

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
        skip = "" if _shots_missing_stills(args, panels) else " -- would be skipped: every still exists"
        print("stills group %d/%d (%s; panels %s)%s"
              % (k, len(groups), ", ".join(names) or "no character LoRAs", _panel_list(panels), skip))
        print("Command: %s" % shlex.join(group_cmd))
```

with:

```python
        skip = "" if _shots_missing_stills(args, panels) else " -- would be skipped: every still exists"
        print("stills group %d/%d (%s; panels %s)%s"
              % (k, len(groups), ", ".join(names) or "no character LoRAs", _panel_list(panels), skip))
        print("Command: %s" % shlex.join(group_cmd))


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

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
        print("Would validate %s (readable image, every edge >= %dpx, aspect 1:3 to 3:1), "
              "derive the video geometry from it, and write a scaled story-model copy "
              "(long edge %dpx) to %s. Phase 2 fits the ORIGINAL into panel_01.png at "
              "twice the video size; nothing is cropped."
              % (args.seed_image, SEED_MIN_EDGE, SEED_DOWNSCALE_MAX_EDGE,
                 paths["seed_downscaled"]))
```

with:

```python
        print("Would validate %s (readable image, every edge >= %dpx, aspect 1:3 to 3:1), "
              "derive the video geometry from it, and write a scaled story-model copy "
              "(long edge %dpx) to %s. %s"
              % (args.seed_image, SEED_MIN_EDGE, SEED_DOWNSCALE_MAX_EDGE, paths["seed_downscaled"],
                 "Phase 2 edits the ORIGINAL into every panel's still with the Qwen edit model; nothing is cropped."
                 if getattr(args, "shots", False) else
                 "Phase 2 fits the ORIGINAL into panel_01.png at twice the video size; nothing is cropped."))
```

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    if getattr(args, "seed_edit", None):
        qe = _qwen_edit()
```

with:

```python
    if getattr(args, "seed_edit", None) and not getattr(args, "shots", False):
        qe = _qwen_edit()
```

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    if args.no_stills:
        print("--- Phase 2: stills --- SKIPPED (--no-stills: no anchor stills are generated)")
```

with:

```python
    if getattr(args, "shots", False) and getattr(args, "seed_image", None):
        print("--- Phase 2: stills ---")
        _print_shots_seed_plan(args)
        print()
    elif args.no_stills:
        print("--- Phase 2: stills --- SKIPPED (--no-stills: no anchor stills are generated)")
```

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    if getattr(args, "seed_edit", None) and phase2_stills in phases:
```

with:

```python
    if (getattr(args, "seed_edit", None) and phase2_stills in phases and not getattr(args, "shots", False)):
```

- [ ] **Step 4: Run the tests and the compile check; verify they pass.**

Run: `cd $S/ss-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_ltx_movie_shots_seed.py tests/test_ltx_movie_seed_edit.py tests/test_shots_mode.py tests/test_dialogue.py tests/test_movie_ui_builder.py 2>&1 | tail -1 && python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1`
Expected: only `test_mut26_pipeline_files_are_unchanged` fails (expected), every other test passes (in the planning replay: `1 failed, 190 passed, 1 skipped`); `OK 347/347`.

Run the compile check with `FILES` = `bin/ltx-movie tests/test_ltx_movie_shots_seed.py tests/test_shots_mode.py`. Expected: `compiled 3` twice.

- [ ] **Step 5: The gate.** Run the gate block with `N=2`. Expected: `GATE PASS`, `lost 1 (listed 1, unexpected 0); new tests 20, not passing 0; baseline failures still failing 2 of 2` (the listed loss is `test_mut26`; Task 1's 14 plus SET1, SET2, SET3, SE4/SE5, SET13, SET14), `disk ok`, `offline unchanged`.

- [ ] **Step 6: Commit.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/ss-wt/qwen-agent-workspace
git add bin/ltx-movie tests/test_ltx_movie_shots_seed.py tests/test_shots_mode.py
git diff --cached --name-only    # expected: exactly those three paths
git commit -m "ltx-movie: --shots with --seed-image needs --seed-edit-model ID; no seed preface and no Phase 1c in shots mode; the shots seed dry run and help (shots seed edits SE2-SE7, SE19-SE20, SET1-SET3, SET13, SET14)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: movie-ui: V1 rule 8, the phases, the 409 for redo jobs, the render-fork copy (SE23-SE28, SE33, SE34; SET16-SET19, SET21, Review Focus 5)

This task implements:
- SE23: `validate_fields`' rule 8 shots branch (the seed-folder rows get it through V1); SE26: `job_phases` drops `1c` in shots mode.
- SE25: `_h_job_create` probes the selection for action `redo` as well as `movie`.
- SE27: `COPY_FILES["render"]` gains `seed_edits.json`.
- SE24, SE28, SE34 need no code (argv, flags, VLM policy, `stills_needed`, `_fields_body` unchanged); SET17 and SET21 pin them.
- Tests: the new `tests/test_movie_ui_shots_seed.py` (SET16-SET19, SET21, Review Focus 5); the spec 6.3 edits of MUT4 and SDT17; `NEW_PY` and QET11 gain the file (R3, R4).

**Files:**
- Modify: `movie_ui_lib.py` (rule 8 `:1564-1565`; `job_phases` `:2295-2296`), `movie_ui_server.py` (`_h_job_create` `:849`), `movie_ui_batch.py` (`COPY_FILES` `:51-52`).
- Create: `tests/test_movie_ui_shots_seed.py`.
- Modify: `tests/test_movie_ui_checks.py` (MUT4 `:76`), `tests/test_movie_ui_seedfolder.py` (SDT17 `:560`), `tests/test_movie_ui_builder.py` (`NEW_PY`), `tests/test_qwen_edit.py` (QET11).

**Interfaces:**
- Consumes: `lib.validate_fields(fields, ws_real, state) -> [str]`, `lib.build_argv`, `lib.job_phases(kind, fields) -> [str]`, `batch.copy_plan(sdir, level) -> [(rel, bytes)]`, the server routes `POST /api/jobs` and `POST /api/jobs/seed-folder`; Task 1's `_phase2_shots_seed` and the test helpers `_FakeShotsQwenEdit`, `_write_story`, `_phase_args`, `movie` (imported from `tests/test_ltx_movie_shots_seed.py` as `sse`).
- Produces: the three V1 texts (`a seed image in shots mode needs a Qwen edit model: ...`, `... needs the default story engine; ...`, `stills LoRAs do not apply in shots mode with a seed image: ...`); shots seed phases `["0", "1", "1b", "2", "3", "4"]` / `["0", "1", "1b", "redo", "2", "3", "4"]`; a 409 `<label> is unavailable: <reason>` for `redo` jobs; `COPY_FILES["render"]` with `seed_edits.json`; the fixture `v1_env` and the constant `UP` (Task 4's SET20 uses `v1_env`).

- [ ] **Step 1: Write the failing tests and the spec 6.3 edits.**

Edit `tests/test_movie_ui_checks.py`: replace this text, which occurs exactly once:

```python
        ({"seed_upload": seed, "mode": "shots"}, "a seed image cannot be used with shots mode"),
```

with:

```python
        ({"seed_upload": seed, "mode": "shots"},
         "a seed image in shots mode needs a Qwen edit model: every panel's still is an edit of the seed, so the "
         "seed cannot be used as-is"),
```

Edit `tests/test_movie_ui_seedfolder.py`: replace this text, which occurs exactly once:

```python
            ("refused", "a seed image cannot be used with shots mode")] * 2
```

with:

```python
            ("refused", "a seed image in shots mode needs a Qwen edit model: every panel's still is an edit of "
                        "the seed, so the seed cannot be used as-is")] * 2
```

Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
          "tests/test_movie_ui_qwen_edit.py", "tests/test_ltx_movie_shots_seed.py")
```

with:

```python
          "tests/test_movie_ui_qwen_edit.py", "tests/test_ltx_movie_shots_seed.py",
          "tests/test_movie_ui_shots_seed.py")
```

Edit `tests/test_qwen_edit.py`: replace this text, which occurs exactly once:

```python
        "tests/test_movie_ui_qwen_edit.py", "tests/test_ltx_movie_shots_seed.py"]
```

with:

```python
        "tests/test_movie_ui_qwen_edit.py", "tests/test_ltx_movie_shots_seed.py",
        "tests/test_movie_ui_shots_seed.py"]
```

Write `tests/test_movie_ui_shots_seed.py` with exactly this content (the Write tool):

```python
"""Tests for the movie-ui side of shots mode with a seed image (docs/superpowers/specs/2026-11-05-compose-shots-
seed-edit-design.md, Section 4, test table 6.2: SET16-SET21, with the plan's Review Focus pin 5): V1 rule 8, the
argv and the phases, the 409 rule for movie and redo jobs and seed folders, the render-level batch copy, the
field flags and the static page.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_shots_seed.py

Rules (spec 6.1): the V1 tests use v1_env, a copy of tests/test_movie_ui_checks.py's env (a temporary HOME and a
stub workspace); the HTTP tests use tests/test_movie_ui_qwen_edit.py's server env fixture by import (the in-test
server and stub workspace, lib.seed_edit_check a recorder answering in _probe's shape, lib.shared_checks a pass
stub). Every test sets HOME, HF_HOME and Z_IMAGE_HF_HOME under tmp_path and removes HF_HUB_CACHE and every
SEED_EDIT_* variable. Review Focus 5 runs bin/ltx-movie's Phase 2 with tests/test_ltx_movie_shots_seed.py's
multi-job fake. No test uses the real HOME, renders, dispatches a job or contacts a server other than the in-test
127.0.0.1 one; none touches port 8177 or 8178. Stdlib, PIL and pytest.
"""

import os
import shutil

import pytest

import movie_ui_testutil as mt
import movie_ui_batch as batch
import movie_ui_lib as lib
import test_ltx_movie_shots_seed as sse
from test_movie_ui_qwen_edit import _clean_env, _compose, _job, _probe, _upload, env  # noqa: F401

WS = mt.WS
UP = "a" * 64 + ".png"
UNC = [{"id": "uncensored", "scale": 1.0}]
NEEDS_MODEL = ("a seed image in shots mode needs a Qwen edit model: every panel's still is an edit of the seed, so "
               "the seed cannot be used as-is")
NEEDS_ENGINE = "a seed image in shots mode needs the default story engine; it cannot be combined with --story-legacy"
NO_STILLS_LORAS = ("stills LoRAs do not apply in shots mode with a seed image: every panel's still is a Qwen edit "
                   "of the seed")
FLAGS = {"--story-id", "--panels", "--length", "--fps", "--frames", "--video-width", "--video-height",
         "--seed-image", "--model", "--gemma", "--story-model", "--goal", "--shots", "--no-stills", "--lora",
         "--stills-lora", "--character", "--location", "--location-strength", "--action", "--no-auto-lora",
         "--no-narration", "--speech-only", "--story-legacy", "--judge", "--no-low-ram", "--panel-timeout",
         "--force", "--force-story", "--redo", "--story-only", "--no-review", "--seed-edit-model",
         "--seed-edit-lora"}


@pytest.fixture
def v1_env(monkeypatch, tmp_path):
    """tests/test_movie_ui_checks.py's env with spec 6.1's variables, and the seed upload UP in the uploads."""
    state = mt.set_home(monkeypatch, tmp_path)
    _clean_env(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    with open(os.path.join(state, "uploads", UP), "wb") as f:
        f.write(mt.PNG)
    return {"state": state, "ws": ws, "tmp": str(tmp_path)}


def _errors(v1_env, **overrides):
    return lib.validate_fields(mt.fields(v1_env["ws"], **overrides), v1_env["ws"], v1_env["state"])


# --- SET16 (SE23): V1 rule 8 in shots mode with a seed image ---------------------------------------------------

def test_set16_v1_rule_8_in_shots_mode(v1_env):
    shots = dict(seed_upload=UP, mode="shots")
    for model in (None, "as-is"):
        assert _errors(v1_env, seed_edit_model=model, **shots) == [NEEDS_MODEL], model
    assert _errors(v1_env, seed_edit_model="qwen21-q4", **shots) == []
    assert _errors(v1_env, seed_edit_model="qwen21-q4", seed_edit_loras=UNC, **shots) == []
    assert _errors(v1_env, seed_edit_model="qwen21-q4", story_legacy=True, **shots) == [NEEDS_ENGINE]
    stills = [{"id": None, "path": "/a.safetensors", "strength": 1, "kind": None}]
    assert _errors(v1_env, seed_edit_model="qwen21-q4", stills_loras=stills, **shots) == [NO_STILLS_LORAS]
    assert _errors(v1_env, seed_upload=UP, mode="chained") == []
    assert _errors(v1_env, mode="shots", stills_loras=stills) == []


# --- SET17 (SE24, SE26): the argv is unchanged, and shots seed jobs have no phase 1c -------------------------

def test_set17_argv_and_phases(v1_env):
    state = v1_env["state"]
    f = mt.fields(WS, seed_upload=UP, action="movie", mode="shots", seed_edit_model="qwen21-q4",
                  seed_edit_loras=[{"id": "uncensored", "scale": 1}])
    argv = lib.build_argv(f, WS, state)
    i = argv.index("--seed-image")
    assert argv[i - 4:i + 6] == ["--fps", "24", "--frames", "145", "--seed-image", os.path.join(state, "uploads", UP),
                                 "--seed-edit-model", "qwen21-q4", "--seed-edit-lora", "uncensored=1.0"]
    assert argv.count("--shots") == 1
    assert lib.job_phases("movie", f) == ["0", "1", "1b", "2", "3", "4"]
    assert lib.job_phases("movie", dict(f, action="redo", redo=[2])) == ["0", "1", "1b", "redo", "2", "3", "4"]
    assert lib.job_phases("movie", dict(f, mode="chained")) == ["0", "1", "1b", "1c", "2", "3", "4"]
    assert lib.job_phases("story", f) == ["0", "1"]


# --- SET18 (SE25): the 409 rule for movie and redo jobs, and seed folders in shots mode ----------------------

def test_set18_the_409_rule_for_movie_and_redo_jobs_and_seed_folders(env):
    s, ws, state, probes = env["srv"], env["ws"], env["state"], env["probes"]
    up = _upload(s)
    q8 = ("mflux-community/qwen-image-2-1-mflux-q8@f5c8cc79a674 is not in /z or /h "
          "(run bin/seed-edit-setup --model qwen21-q8)")
    probes["answer"] = (_probe(models={"qwen21-q8": {"ok": False, "reason": q8}}), None)
    shots = dict(mode="shots", seed_edit_model="qwen21-q8")
    sdir = os.path.join(ws, "generated", "stories", "shots-redo")
    os.makedirs(sdir)
    with open(os.path.join(sdir, "story.md"), "w", encoding="utf-8") as f:
        f.write("x")
    movie_body = _compose(ws, up, story_id="shots-seed", **shots)
    redo_body = _compose(ws, up, story_id="shots-redo", action="redo", redo=[2], **shots)
    for body in (movie_body, redo_body):
        status, _h, payload = mt.api(s, "POST", "/api/jobs", body=body)
        assert (status, payload.get("error")) == (409, "Qwen-Image-2.1 q8 is unavailable: " + q8), body["action"]
    assert lib.list_job_ids(state) == [] and probes["calls"] == [ws, ws]
    probes["answer"] = (_probe(), None)
    for body in (movie_body, redo_body):
        status, _h, payload = mt.api(s, "POST", "/api/jobs", body=body)
        assert status == 201, payload
        argv = _job(state, payload)["argv"]
        assert "--shots" in argv and argv[argv.index("--seed-edit-model") + 1] == "qwen21-q8", body["action"]
    assert "--redo" in argv and len(probes["calls"]) == 4
    seeds = [{"name": "alpha.png", "upload_id": _upload(s, mt.PNG + b"a")},
             {"name": "beta.png", "upload_id": _upload(s, mt.PNG + b"b")}]
    folder = dict(mt.fields(ws, story_id="", action="movie", mode="shots", seed_edit_model="qwen21-q4"), seeds=seeds,
                  preview=False)
    jobs = len(lib.list_job_ids(state))
    status, _h, payload = mt.api(s, "POST", "/api/jobs/seed-folder", body=folder)
    assert status == 201, payload
    assert [r["status"] for r in payload["seeds"]] == ["ok", "ok"] and payload["queued"] == 2
    assert len(lib.list_job_ids(state)) == jobs + 2
    for row in payload["seeds"]:
        argv = lib.read_job(lib.job_dir(state, row["job"]["id"]))["argv"]
        assert "--shots" in argv and argv[argv.index("--seed-edit-model") + 1] == "qwen21-q4"
    status, _h, payload = mt.api(s, "POST", "/api/jobs/seed-folder", body=dict(folder, seed_edit_model=None))
    assert status == 409, payload
    assert [(r["status"], r["reason"]) for r in payload["seeds"]] == [("refused", NEEDS_MODEL)] * 2
    assert len(lib.list_job_ids(state)) == jobs + 2


# --- SET19 (SE27): a render-level fork copies seed_edits.json ------------------------------------------------

def test_set19_a_render_fork_copies_seed_edits_json(v1_env):
    sdir = os.path.join(v1_env["tmp"], "story")
    os.makedirs(os.path.join(sdir, "images"))
    for rel in ("story.md", "seed_edits.json", "seed_edit.json", "seed-original.png", "images/panel_01.png"):
        with open(os.path.join(sdir, rel), "w", encoding="utf-8") as f:
            f.write("x")
    assert [rel for rel, _n in batch.copy_plan(sdir, "render")] == ["images/panel_01.png", "seed_edits.json",
                                                                    "story.md"]
    for level in ("stills", "replan"):
        assert "seed_edits.json" not in [rel for rel, _n in batch.copy_plan(sdir, level)], level
    assert batch.COPY_FILES["render"] == ("story.md", "plan.json", "story_checks.json", "story_prompt.txt",
                                          "catalog_loras.json", "manifest.json", "seed_edits.json")


# --- SET21 (SE28): no new field flag ---------------------------------------------------------------------------

def test_set21_no_new_field_flag(v1_env):
    assert len(lib.FIELD_FLAGS) == 31
    assert lib.FIELD_FLAGS[-1] == ("seed_edit", ("--seed-edit-model", "--seed-edit-lora"))
    assert set(flag for _key, flags in lib.FIELD_FLAGS for flag in flags) == FLAGS


# --- Review Focus 5: a render-level batch fork of a shots seed story reuses every still ---------------------

def test_sse_review_focus_5_a_render_fork_reuses_every_still(monkeypatch, tmp_path, capsys):
    tmp = str(tmp_path)
    monkeypatch.setenv("HOME", os.path.join(tmp, "home"))
    _clean_env(monkeypatch, tmp_path)
    fake = sse._FakeShotsQwenEdit()
    monkeypatch.setattr(sse.movie, "_qwen_edit", lambda: fake)
    monkeypatch.setattr(sse.movie, "_story_dir", lambda story_id: os.path.join(tmp, "stories", story_id))
    sdir = sse._write_story(tmp)
    assert sse.movie._phase2_shots_seed(sse._phase_args(tmp)) == 0
    fork = os.path.join(tmp, "stories", "s1-b1-v1")
    for rel, _n in batch.copy_plan(sdir, "render"):
        os.makedirs(os.path.dirname(os.path.join(fork, rel)), exist_ok=True)
        shutil.copy2(os.path.join(sdir, rel), os.path.join(fork, rel))
    capsys.readouterr()
    assert sse.movie._phase2_shots_seed(sse._phase_args(tmp, story_id="s1-b1-v1")) == 0
    assert len(fake.calls["run_jobs"]) == 1
    assert capsys.readouterr().out.splitlines()[-1] == (
        "seed edits: every panel's still is a recorded edit of the same seed image, prompt, seed and settings; "
        "nothing to edit")
    assert not os.path.exists(os.path.join(fork, "seed-original.png"))
```

- [ ] **Step 2: Run the new tests to verify they fail.**

Run: `cd $S/ss-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_shots_seed.py tests/test_movie_ui_checks.py::test_mut4_every_v1_error_alone tests/test_movie_ui_seedfolder.py::test_sdt17_shots_mode_refuses_every_seed tests/test_qwen_edit.py::test_qet11_imports_and_the_new_files 2>&1 | tail -10`
Expected: `7 failed, 2 passed`. SET16 fails (`['a seed image cannot be used with shots mode']`), SET17 fails (`job_phases` gives `["0", "1", "1b", "1c", "2", "3", "4"]` for shots), SET18 fails (the first shots seed movie job answers 409 `validation failed`; with SE23 alone the `redo` job would answer 201, so the test also pins SE25), SET19 fails (`seed_edits.json` is not in the render copy plan), Review Focus 5 fails (the fork re-edits every panel: two `run_jobs` calls), MUT4 and SDT17 fail (the old text); SET21 passes (R9); QET11 passes.

- [ ] **Step 3: Write the implementation.**

Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    elif seed is not None and mode == "shots":
        errors.append("a seed image cannot be used with shots mode")
```

with:

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

Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    edit = (["1c"] if kind == "movie" and fields.get("seed_upload")
            and fields.get("seed_edit_model") not in (None, "as-is") else [])
```

with:

```python
    edit = (["1c"] if kind == "movie" and fields.get("seed_upload") and fields.get("mode") != "shots"
            and fields.get("seed_edit_model") not in (None, "as-is") else [])
```

Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    if (fields["action"] == "movie" and fields["seed_upload"]
```

with:

```python
    if (fields["action"] in ("movie", "redo") and fields["seed_upload"]
```

Edit `movie_ui_batch.py`: replace this text, which occurs exactly once:

```python
    "render": ("story.md", "plan.json", "story_checks.json", "story_prompt.txt", "catalog_loras.json",
               "manifest.json"),
```

with:

```python
    "render": ("story.md", "plan.json", "story_checks.json", "story_prompt.txt", "catalog_loras.json",
               "manifest.json", "seed_edits.json"),
```

- [ ] **Step 4: Run the tests and the compile check; verify they pass.**

Run: `cd $S/ss-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_shots_seed.py tests/test_movie_ui_checks.py tests/test_movie_ui_seedfolder.py tests/test_movie_ui_qwen_edit.py tests/test_movie_ui_batch.py tests/test_movie_ui_progress.py tests/test_qwen_edit.py tests/test_movie_ui_builder.py 2>&1 | tail -1`
Expected: only `test_mut26_pipeline_files_are_unchanged` fails (expected), every other test passes (in the planning replay: `1 failed, 193 passed`).

Run the compile check with `FILES` = `movie_ui_lib.py movie_ui_server.py movie_ui_batch.py tests/test_movie_ui_shots_seed.py tests/test_movie_ui_checks.py tests/test_movie_ui_seedfolder.py tests/test_movie_ui_builder.py tests/test_qwen_edit.py`. Expected: `compiled 8` twice.

- [ ] **Step 5: The gate.** Run the gate block with `N=3`. Expected: `GATE PASS`, `lost 1 (listed 1, unexpected 0); new tests 26, not passing 0; baseline failures still failing 2 of 2` (the listed loss is `test_mut26`; the 6 new tests are SET16-SET19, SET21 and Review Focus 5), `disk ok`, `offline unchanged`.

- [ ] **Step 6: Commit.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/ss-wt/qwen-agent-workspace
git add movie_ui_lib.py movie_ui_server.py movie_ui_batch.py tests/test_movie_ui_shots_seed.py tests/test_movie_ui_checks.py tests/test_movie_ui_seedfolder.py tests/test_movie_ui_builder.py tests/test_qwen_edit.py
git diff --cached --name-only    # expected: exactly those eight paths
git commit -m "movie-ui: a seed image in shots mode needs a Qwen edit model; no phase 1c in shots jobs; redo jobs probe the selection; render forks copy seed_edits.json (shots seed edits SE23-SE28, SET16-SET19, SET21)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The page: the Compose picker in shots mode, "Seed as-is" disabled there (SE29-SE32; SET20)

This task implements:
- SE29: `index.html`'s picker label span `c-sq-label` and the hidden shots note `c-sq-shots-note`.
- SE30: `composeSeedEditActive` is true in chained and shots mode.
- SE31: `updateComposeButtons` resets an as-is choice to the registry default in shots mode, disables and relabels the as-is option there, sets the label and shows the note.
- SE32: the page bans hold (SET20 checks them).
- Tests: SET20 appended to `tests/test_movie_ui_shots_seed.py`, with the three imports it needs (R12).

**Files:**
- Modify: `static/movie-ui/index.html` (`:92`, after `:95`), `static/movie-ui/app.js` (`composeSeedEditActive` `:413-417`; `updateComposeButtons` `:546-547`).
- Modify: `tests/test_movie_ui_shots_seed.py`.

**Interfaces:**
- Consumes (existing, unchanged): `COMPOSE_PICKER` (`qwenPicker("c-sq", true)`: `.state` (`{model, loras}` or `null`), `.select(model, loras)`, `.update()`, `.selection()`, `.reason()`; its `render` writes option 0 as `as-is` with text `Seed as-is (no edit)` on every `update`), `show(node, on)`, `$()`, `S.options.supported.seed_edit`, `S.seedUpload`; `composeFields` sends `COMPOSE_PICKER.selection()` whenever `composeSeedEditActive()` is true. Task 3's `v1_env`; `tests/test_movie_ui_qwen_edit.py`'s `_function(js, head)`.
- Produces: the DOM ids `c-sq-label`, `c-sq-shots-note`; the page behaviour of spec Section 7 items 1-4 (checked in V2).

- [ ] **Step 1: Write the failing test.**

Edit `tests/test_movie_ui_shots_seed.py`: replace this text, which occurs exactly once:

```python
import os
import shutil

import pytest
```

with:

```python
import os
import re
import shutil
import subprocess

import pytest
```

Edit `tests/test_movie_ui_shots_seed.py`: replace this text, which occurs exactly once:

```python
from test_movie_ui_qwen_edit import _clean_env, _compose, _job, _probe, _upload, env  # noqa: F401
```

with:

```python
from test_movie_ui_qwen_edit import _clean_env, _compose, _function, _job, _probe, _upload, env  # noqa: F401
```

Edit `tests/test_movie_ui_shots_seed.py`: replace this text, which occurs exactly once:

```python
    assert not os.path.exists(os.path.join(fork, "seed-original.png"))
```

with:

```python
    assert not os.path.exists(os.path.join(fork, "seed-original.png"))


# --- SET20 (SE29-SE32): the static page ------------------------------------------------------------------------

LABEL = '<label><span id="c-sq-label">Panel 1 from the seed</span> <select id="c-sq-qwen-model"></select></label>'
SHOTS_NOTE = ("<p id=\"c-sq-shots-note\" class=\"muted\" hidden>Every panel's still is a Qwen edit of the seed, "
              "prompted by that panel's own Image: text. Z-Image is not used: stills LoRAs, and the stills LoRAs of "
              "characters and locations, do not apply (characters and locations still shape the story and the "
              "video).</p>")
ACTIVE = ('    return supported.seed_edit !== false && (mode === "chained" || mode === "shots")\n'
          '      && (($("#c-res-seed").checked && Boolean(S.seedUpload)) || $("#c-res-folder").checked);\n')
SE31 = ('    const shotsSeed = seedEditOn && mode === "shots";\n'
        '    if (shotsSeed && COMPOSE_PICKER.state && COMPOSE_PICKER.state.model === "as-is") {\n'
        '      COMPOSE_PICKER.select(null, null);\n'
        '      COMPOSE_PICKER.update();\n'
        '    }\n'
        '    const asIsOption = $("#c-sq-qwen-model").options[0];\n'
        '    if (asIsOption && asIsOption.value === "as-is") {\n'
        '      asIsOption.disabled = shotsSeed;\n'
        '      asIsOption.textContent = shotsSeed ? "Seed as-is (no edit) — chained mode only" '
        ': "Seed as-is (no edit)";\n'
        '    }\n'
        '    $("#c-sq-label").textContent = mode === "shots" ? "Every panel from the seed" : "Panel 1 from the seed";\n'
        '    show($("#c-sq-shots-note"), shotsSeed);\n')


def test_set20_the_page(v1_env):
    static = os.path.join(WS, "static", "movie-ui")
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(static, "app.js"), encoding="utf-8") as f:
        js = f.read()
    assert html.count("          " + LABEL + "\n") == 1
    assert html.count('          <p id="c-sq-qwen-note" class="muted"></p>\n          ' + SHOTS_NOTE + "\n") == 1
    for ident in ('id="c-sq-label"', 'id="c-sq-shots-note"'):
        assert html.count(ident) == 1, ident
    box = html.index('<div id="c-sq-qwen-box" hidden>')
    assert box < html.index(LABEL) < html.index(SHOTS_NOTE) < html.index('id="c-sq-reason"') < html.index(
        "</fieldset>", box)
    active = _function(js, "  function composeSeedEditActive() {")
    assert '    const mode = $("#c-mode").value;\n' + ACTIVE in active
    buttons = _function(js, "  function updateComposeButtons() {")
    assert ('    COMPOSE_PICKER.update();\n    const seedEditOn = composeSeedEditActive();\n'
            '    // Shots seed edits spec SE31: in shots mode every panel is an edit of the seed, so "Seed as-is" is '
            'not offered.\n' + SE31 + '    show($("#c-sq-qwen-box"), seedEditOn);\n') in buttons
    for name, text in (("index.html", html), ("app.js", js)):
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\balert\(", r"\bconfirm\(", r"\bprompt\(",
                        r"\beval\(", r"new Function"):
            assert not re.search(pattern, text), (name, pattern)
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")], capture_output=True, text=True,
                              timeout=60)
        assert proc.returncode == 0, proc.stderr
```

- [ ] **Step 2: Run the new test to verify it fails.**

Run: `cd $S/ss-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_shots_seed.py 2>&1 | tail -3`
Expected: `1 failed, 6 passed`: SET20 fails (`assert 0 == 1` on the `LABEL` count); the other 6 tests pass.

- [ ] **Step 3: Write the implementation.** Every Edit below, in order (index.html first, then app.js).

Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
          <label>Panel 1 from the seed <select id="c-sq-qwen-model"></select></label>
```

with:

```html
          <label><span id="c-sq-label">Panel 1 from the seed</span> <select id="c-sq-qwen-model"></select></label>
```

Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
          <p id="c-sq-qwen-note" class="muted"></p>
```

with:

```html
          <p id="c-sq-qwen-note" class="muted"></p>
          <p id="c-sq-shots-note" class="muted" hidden>Every panel's still is a Qwen edit of the seed, prompted by that panel's own Image: text. Z-Image is not used: stills LoRAs, and the stills LoRAs of characters and locations, do not apply (characters and locations still shape the story and the video).</p>
```

Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
  function composeSeedEditActive() {
    const supported = (S.options && S.options.supported) || {};
    return supported.seed_edit !== false && $("#c-mode").value === "chained"
      && (($("#c-res-seed").checked && Boolean(S.seedUpload)) || $("#c-res-folder").checked);
  }
```

with:

```js
  function composeSeedEditActive() {
    const supported = (S.options && S.options.supported) || {};
    const mode = $("#c-mode").value;
    return supported.seed_edit !== false && (mode === "chained" || mode === "shots")
      && (($("#c-res-seed").checked && Boolean(S.seedUpload)) || $("#c-res-folder").checked);
  }
```

Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    const seedEditOn = composeSeedEditActive();
    show($("#c-sq-qwen-box"), seedEditOn);
```

with:

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

- [ ] **Step 4: Run the tests; verify they pass.**

Run: `cd $S/ss-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_shots_seed.py tests/test_movie_ui_qwen_edit.py tests/test_movie_ui_seedgen.py tests/test_movie_ui_seams.py 2>&1 | tail -1 && node --check static/movie-ui/app.js && echo "node ok"`
Expected: every test passes (in the planning replay: `127 passed`); `node ok`.

- [ ] **Step 5: The gate.** Run the gate block with `N=4`. Expected: `GATE PASS`, `lost 1 (listed 1, unexpected 0); new tests 27, not passing 0; baseline failures still failing 2 of 2` (the listed loss is `test_mut26`; the new test is SET20), `disk ok`, `offline unchanged`.

- [ ] **Step 6: Commit.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/ss-wt/qwen-agent-workspace
git add static/movie-ui/index.html static/movie-ui/app.js tests/test_movie_ui_shots_seed.py
git diff --cached --name-only    # expected: exactly those three paths
git commit -m "movie-ui page: the Compose edit model picker works in shots mode with a seed, every panel from the seed, Seed as-is chained only (shots seed edits SE29-SE32, SET20)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The `test_mut26` re-baseline, a test-only commit (spec 9.3, D8; ruling R2)

This task moves `test_mut26_pipeline_files_are_unchanged`'s `BASELINE` to the last implementation commit (Task 4's; no pinned file changed after Task 2, so it is also a commit after every pinned-file change) and extends the comment's chain with `, then to <SHA> (shots-seed-edit).` Nothing else in the file changes, and the commit stages only that file (spec 9.3 items 2-3). If a later review fix touches a pinned file, add a new test-only baseline commit the same way; never amend.

**Files:**
- Modify: `tests/test_movie_ui_builder.py` (`test_mut26`'s comment line `:290` and `BASELINE` `:292`; `NEW_PY` grew by one line in Task 3, so they are at `:291` and `:293` by then; located by text below).

**Interfaces:** none (test-only).

- [ ] **Step 1: Take the SHA and check the pinned files (spec 9.3 item 1).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/ss-wt/qwen-agent-workspace
SHA=$(git rev-parse HEAD); echo $SHA
git log -1 --format=%s                         # expected: movie-ui page: the Compose edit model picker works in shots mode ... (Task 4)
git diff --quiet $SHA -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py && echo "pipeline files clean at SHA"
git diff --name-only bdeb3ae $SHA -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py
```

Expected: a 40-hex `SHA`; `pipeline files clean at SHA`; exactly `qwen-agent-workspace/bin/ltx-movie`. Anything else: stop and report. (The 23 paths are `PIPELINE_FILES`, written out on both lines rather than held in a shell variable: zsh, this host's shell, does not word-split an unquoted `$P`, so `git diff -- $P` would compare one non-existent path and always look clean.)

- [ ] **Step 2: Edit the comment.** Type the 40 characters of `SHA` (Step 1) in place of the word `SHA`.

Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```text
    # 6a0b3035bdf3f6eb20833372436fd5e64af1f67b (panel-1 pacing instruction reworded), then to e25f58f5103ae1f703ab135a00a5d51b664b8124 (VLM lifecycle + panel-1 pacing), then to 75d914b9d128434b9fa0ac25cf0482e6f9b5ca7a (character_dataset.py: regenerate with a new seed), then to 5903089fe272c03933d31ca4af105c4aec42b823 (the seed is persisted under the library lock after the preflights), then to ac23105738adee0b26ea9d391681f3abbaa26ab0 (narrative dialogue fidelity), then to cf0a0e684ea4f9ca09f7e7d45dc0e33544242971 (writer pacing), then to 05ba1792b7e1620f96b1e50ba5a83f6349620529 (pinned cast presence), then to f7a38afc6d6ae9622b63dbf4ce939e362a05a7ad (speaker attribution), then to 42f33640cd008021a32dc0f8f948d0e8da04de2b (shot prompt format), then to ff757afbc0a801f2029628871c684ce4d98b4811 (soft panel count), then to 44beb3d67ad5af05093e29e1c6fc088330b41386 (location library), then to 38005c3bfee25daf73da231692609fc0b8d25892 (chained end frames), then to c12d5f4395062ad432153443d62e9b1f8c464a50 (qwen-edit-models), then to d2cf22881a733bb49b97c4388b22466b589ec1f0 (qwen-edit-models: Phase 1c clears the old record before an edit).
```

with:

```text
    # 6a0b3035bdf3f6eb20833372436fd5e64af1f67b (panel-1 pacing instruction reworded), then to e25f58f5103ae1f703ab135a00a5d51b664b8124 (VLM lifecycle + panel-1 pacing), then to 75d914b9d128434b9fa0ac25cf0482e6f9b5ca7a (character_dataset.py: regenerate with a new seed), then to 5903089fe272c03933d31ca4af105c4aec42b823 (the seed is persisted under the library lock after the preflights), then to ac23105738adee0b26ea9d391681f3abbaa26ab0 (narrative dialogue fidelity), then to cf0a0e684ea4f9ca09f7e7d45dc0e33544242971 (writer pacing), then to 05ba1792b7e1620f96b1e50ba5a83f6349620529 (pinned cast presence), then to f7a38afc6d6ae9622b63dbf4ce939e362a05a7ad (speaker attribution), then to 42f33640cd008021a32dc0f8f948d0e8da04de2b (shot prompt format), then to ff757afbc0a801f2029628871c684ce4d98b4811 (soft panel count), then to 44beb3d67ad5af05093e29e1c6fc088330b41386 (location library), then to 38005c3bfee25daf73da231692609fc0b8d25892 (chained end frames), then to c12d5f4395062ad432153443d62e9b1f8c464a50 (qwen-edit-models), then to d2cf22881a733bb49b97c4388b22466b589ec1f0 (qwen-edit-models: Phase 1c clears the old record before an edit), then to SHA (shots-seed-edit).
```

- [ ] **Step 3: Edit `BASELINE`.** Type `SHA` in place of the word `SHA`.

Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
    BASELINE = "d2cf22881a733bb49b97c4388b22466b589ec1f0"
```

with:

```python
    BASELINE = "SHA"
```

- [ ] **Step 4: Verify.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/ss-wt/qwen-agent-workspace
SHA=$(git rev-parse HEAD)
grep -c "    BASELINE = \"$SHA\"" tests/test_movie_ui_builder.py                                                              # expected: 1
grep -c "(qwen-edit-models: Phase 1c clears the old record before an edit), then to $SHA (shots-seed-edit)\.$" tests/test_movie_ui_builder.py   # expected: 1
git diff --stat -- tests/test_movie_ui_builder.py | tail -1                                                                   # expected: 1 file changed, 2 insertions(+), 2 deletions(-)
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py 2>&1 | tail -1                                      # expected: N passed, no failure
```

Then run the gate block with `N=5`. Expected: `GATE PASS`, `lost 0 (listed 0, unexpected 0); new tests 27, not passing 0; baseline failures still failing 2 of 2`, `disk ok`, `offline unchanged`; and `grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $D/task-5-pytest.txt` prints `1`.

- [ ] **Step 5: Commit (test-only, one file).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/ss-wt/qwen-agent-workspace
git add tests/test_movie_ui_builder.py
git diff --cached --name-only    # expected: exactly qwen-agent-workspace/tests/test_movie_ui_builder.py
git commit -m "tests/test_movie_ui_builder.py: test_mut26 BASELINE moves to the last shots-seed-edit implementation commit (spec 9.3)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Verification (controller only; not an implementer task)

The controller runs these after Task 5, in spec 9.1's order: the pass bar (V1), the browser check (V2), the Opus design review (V3); the live checks (V4) are the user's, on macstudio. Every rule of "Global Constraints" applies. A finding is fixed in a new commit on the owning task's files; if that commit touches `bin/ltx-movie`, a new Task 5-style test-only baseline commit follows; then V1 reruns.

- [ ] **V1: The pass bar, spec 9.1 items 2-4 (about 20 minutes).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/sse-baseline
cd $S/ss-wt/qwen-agent-workspace
df -g . | tail -1
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/final-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt; tail -1 $D/final-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/final-pytest.txt $D/expected-failures.txt 5
diff <(grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt | sort) <(grep -E '^(FAILED|ERROR)' $D/final-pytest.txt | sort) && echo "same failures, same messages"
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1
git diff --stat bdeb3ae..HEAD -- bin/ltx-story-images story_engine.py qwen_edit.py seed_edit_mflux_child.py movie_ui_seedgen.py content_safety.py ltx_image_fit.py bin/ltx-story-manifest bin/ltx-mlx-render scripts/deploy/build_pkg.py static/movie-ui/app.css | tail -1
git diff --name-only bdeb3ae..HEAD | wc -l
git diff bdeb3ae..HEAD -- bin/ltx-movie | grep -E '^\+(import|from) ' || echo "no top-level import added to bin/ltx-movie"
git diff bdeb3ae..HEAD -- tests/ | grep -E '^\+' | grep -nE "expanduser\(|urlopen|import requests|zshenv|fleet\.env|macstudio|127\.0\.0\.1:81|HF_TOKEN\"\]" || echo "no real HOME, HTTP client, private host, model-server address or real token in the new tests"
git ls-files -s bin/ltx-movie | cut -c1-6
```

Expected, in order:
- at least 20 GiB available (SEK10);
- the final summary is the baseline's with the pass count higher by exactly 27 (`2 failed, <P0 + 27> passed, 2 skipped`);
- `lost 0 (listed 0, unexpected 0); new tests 27, not passing 0; baseline failures still failing 2 of 2` and `GATE PASS`;
- `same failures, same messages` (SEK1); `OK 347/347` (SEK2);
- no output from the untouched-files `--stat` (spec 0.4);
- `15` (the spec, the plan, and the 13 files of the File Structure table);
- `no top-level import added to bin/ltx-movie`; the "no real HOME ..." line; `100755`.

- [ ] **V2: The browser check (spec Section 7), on a throwaway demo; never committed.** Copy PR #10's demo server: `mkdir -p $S/ssedemo` and copy `$S/qemdemo/demo.py` to `$S/ssedemo/demo.py` (the Write tool, after a Read), changing exactly two lines: `WS = S + "/qem-wt/qwen-agent-workspace"` becomes `WS = S + "/ss-wt/qwen-agent-workspace"` and `DEMO = S + "/qemdemo"` becomes `DEMO = S + "/ssedemo"`. Its stub probe answers `qwen21-q4`, `qwen2511-q4` and `uncensored` ok and `qwen21-q8` not installed, and its stub `bin/ltx-movie --help` prints the current help fixture (both seed-edit flags), as spec Section 7 asks. Run `python3 -B $S/ssedemo/demo.py` in the background, open the URL in `$S/ssedemo/url.txt` (never print it), and check spec Section 7 items 1-5: (1) Compose, upload a seed, mode Shots: the picker shows, its label reads `Every panel from the seed`, the selection is `Qwen-Image-2.1 q4` + Uncensored at 1, the shots note is visible, and the preview command has `--seed-edit-model qwen21-q4 --seed-edit-lora uncensored=1.0` and `--shots`; (2) Seeds → Use → Compose, mode Shots: the as-is option reads `Seed as-is (no edit) — chained mode only`, is disabled, the selection is `Qwen-Image-2.1 q4` + Uncensored; mode Chained: the label is `Panel 1 from the seed`, as-is is enabled, the note is hidden; (3) Shots without a seed (Size): no picker, no seed-edit flag in the command; (4) Shots + seed + a stills LoRA row: the preview errors list `stills LoRAs do not apply in shots mode with a seed image: every panel's still is a Qwen edit of the seed`; (5) the browser console shows no error. Stop the demo with `kill $(cat $S/ssedemo/pid)`. A failure is a Task 4 defect.

- [ ] **V3: The design review.** An Opus `design-reviewer` reviews `git diff 7a79ea9..HEAD` against the spec, the load-bearing properties first: every output screened and no fallback (SEK5; SET6, SET15, Review Focus 3), one child per Phase 2 run with exactly the todo panels (SEK4; SET5, SET9), no `ok` entry for an unwritten still after a failure or interrupt (SEK6; SET7, SET8, Review Focus 4), chained and plain shots byte-identical (SEK3; SET3, SET14, QET26-QET32, `OK 347/347`), the SE9-SE15 code typed exactly as the spec gives it, and the plan rulings R1-R14. A finding is fixed as described above.

- [ ] **V4: The live checks (spec Section 8), run by the user on macstudio; never by the agent.** The agent never connects to macstudio. Record each row as "not run (awaiting the user)" until the user pastes the figures back; then record each row's figures and pass or fail. Push and merge only on the user's go (spec 9.1 item 6). Preparation (user): check out `shots-seed-edit` on macstudio; `bin/seed-edit-setup --model qwen21-q4 --lora uncensored` (and `--model qwen2511-q4` for L4).

| Row | Steps (user) | Record | Pass |
|---|---|---|---|
| L1 | movie-ui Compose: upload a medium-shot photo of one person, mode Shots, panels 12, default picker (`qwen21-q4` + uncensored), a narrative that moves through at least three places, Run all | `seed_edits.json` (status and seconds per panel), Phase 2 wall clock from the job log, `seed-original.png` beside `images/panel_01..12.png`; per panel two yes/no judgements: same person as the seed? visibly a different shot from the seed? | SEK7 (≥ 10/12 same person), SEK8 (≥ 8/12 different shot), SEK9 (no timeout) |
| L2 | rerun L1's story with Overwrite ticked after cancelling the job in the movie-ui during Phase 2 once at least three stills exist (stills counter) | `seed_edits.json` right after the cancel; the rerun's `seed edits: reusing the stills of panels …` line and its plan line | finished panels reused (not re-edited); no unfinished panel had an ok entry after the cancel; the rerun's plan line lists exactly the rest |
| L3 | the Section 7 steps 1-4 on the real page | screenshots or notes | every step as described |
| L4 (optional) | L1's narrative and seed with `qwen2511-q4` (8 steps) | the same records | seconds per panel and the two judgements, for comparison with L1 |
| L5 | chained regression: [QE] L3(a) (chained, uploaded seed, default model) | `seed_edit.json`, Phase 1c in the log | Phase 1c runs and panel 1 is the edit, as before |

Open questions 1-7 of spec Section 13 are decided by the user from that record, after L1 (and L4).

---

## Self-review

### Spec coverage: requirements → task

| Requirement | Task | Where |
|---|---|---|
| SE1 | 1 | the four constants after `SEED_EDIT_SCHEMA` (SET5, SET11 pin the texts) |
| SE2 | 2 | `_resolve_shots` (SET1, S33) |
| SE3 | 2 (no code) | `_resolve_seed_edit` unchanged; SET1 and SET13 run through it |
| SE4, SE5 | 2 | three help strings, the docstring sentence (R8, R13: `test_se4_se5_the_help_texts_and_the_docstring`) |
| SE6 | 2 | `build_story_prompt` (R7; SET2) |
| SE7 | 2 | `_phase_sequence` (SET3) |
| SE8 | 1 | `phase2_stills` dispatch (SET4) |
| SE9-SE15 | 1 | the eight functions after `phase_seed_edit` (SET5-SET12, SET15, Review Focus 1-4) |
| SE16-SE18 | 1 | their behaviour (SET7, SET8, SET10, SET6, SET5) |
| SE19, SE20 | 2 | `_print_shots_seed_plan`, the Phase 0 text, the Phase 1c and Phase 2 dry-run blocks (SET13, SET14) |
| SE21, SE22 | — (no code) | Phases 3-4 and `build_pkg.py` unchanged (V1's untouched-files check; V3) |
| SE23 | 3 | V1 rule 8 (SET16, SET18 folder rows, MUT4, SDT17) |
| SE24 | 3 (no code) | `build_argv` unchanged (SET17) |
| SE25 | 3 | `_h_job_create` (SET18) |
| SE26 | 3 | `job_phases` (SET17) |
| SE27 | 3 | `COPY_FILES["render"]` (SET19, Review Focus 5) |
| SE28 | 3 (no code) | `FIELD_FLAGS` unchanged (SET21) |
| SE29-SE32 | 4 | `index.html`, `app.js` (SET20; V2) |
| SE33 | 1, 3 | `NEW_PY` (R4) and QET11 (R3) |
| SE34 | 3 (no code) | VLM policy, `stills_needed`, seams job, `_fields_body` unchanged (V3) |
| Section 6.3 edits | 2 (S33), 3 (MUT4, SDT17, `NEW_PY`) | spec 6.3 table; plus QET11 (R3) |
| 9.3, D8 | 5 | `test_mut26` (R2) |
| Section 7, 8, 9.1 | Verification | V1-V4 |

### Spec tests → test

| ID | Test (file) | Task |
|---|---|---|
| SET1 | `test_set1_the_shots_seed_option_rules` (`tests/test_ltx_movie_shots_seed.py`) | 2 |
| SET2 | `test_set2_the_shots_story_prompt_has_no_seed_preface` | 2 |
| SET3 | `test_set3_shots_seed_runs_have_no_phase_1c` | 2 |
| SET4 | `test_set4_phase_2_dispatches_shots_seed_runs` | 1 |
| SET5 | `test_set5_every_panel_is_a_qwen_edit_of_the_seed` | 1 |
| SET6 | `test_set6_a_blocked_panel_fails_the_phase` | 1 |
| SET7 | `test_set7_a_failed_batch_keeps_the_finished_panels` | 1 |
| SET8 | `test_set8_an_interrupted_batch_records_only_finished_stills` | 1 |
| SET9 | `test_set9_a_rerun_edits_exactly_the_changed_panels` | 1 |
| SET10 | `test_set10_an_unavailable_selection_fails_every_panel` | 1 |
| SET11 | `test_set11_the_stills_lora_note` | 1 |
| SET12 | `test_set12_a_panel_without_an_image_line` | 1 |
| SET13 | `test_set13_the_shots_seed_dry_run` | 2 |
| SET14 | `test_set14_chained_and_plain_shots_dry_runs_are_unchanged` | 2 |
| SET15 | `test_set15_the_real_runner_screens_every_panel` | 1 |
| SET16 | `test_set16_v1_rule_8_in_shots_mode` (`tests/test_movie_ui_shots_seed.py`) | 3 |
| SET17 | `test_set17_argv_and_phases` | 3 |
| SET18 | `test_set18_the_409_rule_for_movie_and_redo_jobs_and_seed_folders` | 3 |
| SET19 | `test_set19_a_render_fork_copies_seed_edits_json` | 3 |
| SET20 | `test_set20_the_page` | 4 |
| SET21 | `test_set21_no_new_field_flag` | 3 |
| SE4/SE5 (R8) | `test_se4_se5_the_help_texts_and_the_docstring` | 2 |
| Review Focus 1-4 | `test_sse_review_focus_1_...` ... `_4_...` (`tests/test_ltx_movie_shots_seed.py`) | 1 |
| Review Focus 5 | `test_sse_review_focus_5_a_render_fork_reuses_every_still` (`tests/test_movie_ui_shots_seed.py`) | 3 |

### KPIs → where verified

| KPI | Verified by |
|---|---|
| SEK1, SEK2 | every task's gate; V1 |
| SEK3 | SET3, SET4 (no-seed half), SET14, the unchanged QET26-QET32 and S-tests in every gate |
| SEK4 | SET5, SET9, SET15 |
| SEK5 | SET6, SET15, Review Focus 3 and 4 |
| SEK6 | SET7, SET8, Review Focus 4 |
| SEK7-SEK9 | V4 (L1), the user's |
| SEK10 | every gate's `disk ok` line; V1 |

### Type and name consistency check

- `args.seed_edit` is `{"qwen_model": ID, "loras": [{"id", "scale"}]}` everywhere: set by the unchanged `_resolve_seed_edit`, read by `_shots_seed_plan`, `_phase2_shots_seed` and `_print_shots_seed_plan`, and built that way by `_phase_args`, `_SeqArgs` and SET13.
- `run_jobs` jobs are `{"n", "seed", "prompt", "source", "stage_path", "output_path"}` (Task 1's code; the fake records and SET5 compares exactly that shape); results are `{"n", "output_path", "status", "seconds"}` with `status` in `ok`/`blocked`/`failed`, which `_phase2_shots_seed`'s `status` map, the fake and the real `run_jobs` all use; `on_result` receives one such dict.
- `_shots_seed_plan` returns `(error, plan)` with `plan["prompts"]` a list of `(n, prompt)` tuples, `plan["keys"]`/`plan["entries"]` dicts keyed by int `n`, `plan["reuse"]`/`plan["todo"]` sorted int lists; `_print_shots_seed_plan` and `_phase2_shots_seed` read exactly those keys. `_shots_seed_entries` drops non-int and bool `n`, so JSON's ints key the dict consistently with `_shots_seed_prompts`' `enumerate(..., start=1)`.
- Record entries have SE12's 22 keys in order (`ENTRY_KEYS` in the tests); `seed_edits.json` is `{"schema", "updated", "panels"}`; `still_sha256` is `_sha256_file` of the fitted still, which the reuse check recomputes with the same function.
- The skill text `ltx_movie_shots_seed_edit` is one constant (`SHOTS_SEED_EDIT_SKILL`) used by `run_jobs` and the dry run; the tests compare the literal.
- The three V1 texts in `movie_ui_lib.py` (Task 3) equal `NEEDS_MODEL`, `NEEDS_ENGINE`, `NO_STILLS_LORAS` in the tests and the MUT4/SDT17 edits; the CLI texts (Task 2) equal `MODEL_RULE`, `ENGINE_RULE`, `STILLS_RULE` and the S33 edit.
- `job_phases`' shots result `["0", "1", "1b", "2", "3", "4"]` mirrors `_phase_sequence`'s shots seed tuple (Phase 0, Phase 1, Phase 1b, Phase 2, Phase 3, Phase 4; `redo` before `2`).
- The page ids `c-sq-label` and `c-sq-shots-note` appear once each in `index.html` and are read only in `updateComposeButtons`.

## Spec gaps found (for the spec author)

1. **[R3] SE33 breaks QET11.** `tests/test_qwen_edit.py::test_qet11_imports_and_the_new_files` pins `NEW_PY`'s tail; spec 6.3 says no other existing test changes. The plan grows QET11's list with `NEW_PY`.
2. **[R6] `tests/test_seed_edit_tool.py`'s `QWENEDIT_STUB` cannot serve shots seed jobs** (`int(name[5:7])` on `panel_NN.pending.png` raises). Only Review Focus 3 needs it; the test substitutes one expression in its own copy.
3. **The spec's story fixture is not what the default engine writes in shots mode.** `story_engine.assemble` writes no `Style:` line and may write `Dialogue:` fields; Review Focus 1 pins the prompt for that input (`PREFIX + Image:` text, nothing else).
4. **SE4 and SE5 have no SET row.** The plan adds one test (R8).
5. **[R2] Spec 9.3's comment suffix `(shots seed edits)` conflicts with the planning dispatch's `(shots-seed-edit)`;** the plan follows the dispatch.
6. **SET13 cannot reuse QET31's `--story-legacy` dry run,** since SE2 refuses the legacy engine in shots seed mode; it runs the default engine's dry run (as `test_ltx_movie_offline` L27 and L43 do), which stays offline (R10).
7. **`_shots_seed_plan` hashes the seed and every recorded still on every Phase 2 run and dry run** (`_sha256_file` per panel). For 24 panels of 2W × 2H PNGs this is a few hundred MB read at most; not a correctness issue, noted for L1's Phase 2 wall clock.
8. **A blocked panel with a pinned seed reproduces its block on an unchanged rerun** (spec 12 item 7); the blocked text tells the user to change the `Image:` line, and `--redo` of that panel alone also reproduces it. Not changed (Open question 2).
9. **(PR #10's plan, not this spec) Its Task 8 pinned-file guard was vacuous under zsh** (ruling R14): `git diff --quiet $SHA -- $P` with an unquoted `$P` never compares the pinned files. This plan writes the paths out.

## Execution handoff

Plan complete and saved to `qwen-agent-workspace/docs/superpowers/plans/2026-11-05-compose-shots-seed-edit.md`.

**How it was checked.**
- **Replay on scratch clones, never on the worktree.** A script parsed every Edit and Write block of this plan, in order, and applied it to `git clone`s of the worktree at `7a79ea9` under `$S/sse-replay*` (scratch, outside `$S/ss-wt`, never pushed), checking that every old text occurs exactly once at its turn; each task was committed locally in the clone, and Task 5 used the real SHA of the replayed Task 4 commit. The worktree itself received only this plan file.
- **Spec code byte for byte.** Each of the spec's eleven code blocks (SE1, SE2, SE8, SE9-SE15, SE19 x2, SE20, SE23, SE26, SE30, SE31) occurs exactly once in this plan, checked programmatically against the spec at `7a79ea9`.
- **Executed in the replay.** Every task's Step 2 command gave the stated failures (`14 failed, 1 passed`; `6 failed, 15 passed`; `7 failed, 2 passed`; `1 failed, 6 passed`) and every Step 4 command passed with only `test_mut26` failing in Tasks 1-4 (`OK 347/347` after Tasks 1 and 2); the compile check gave `compiled N` on Python 3.9.6 and 3.13; `node --check` passed on the replayed `app.js`. A mutation check (SE25 reverted with SE23 in place) makes SET18 fail, so SET18 pins SE25. Task 5's Step 1 block, run as written, printed `pipeline files clean at SHA` and exactly `qwen-agent-workspace/bin/ltx-movie`; Step 4's greps printed `1`, `1` and `1 file changed, 2 insertions(+), 2 deletions(-)`.
- **The full gate, observed.** Baseline in a clean clone at `7a79ea9`: `2 failed, 2615 passed, 2 skipped` (the two allowed failures), `OK 347/347`. After the replayed Task 5: `2 failed, 2642 passed, 2 skipped`; `lost 0 (listed 0, unexpected 0); new tests 27, not passing 0; baseline failures still failing 2 of 2`; `GATE PASS`; `same failures, same messages`; `offline unchanged`; `test_mut26` PASSED. After the replayed Task 1 (a separate clone at that commit): `3 failed, 2628 passed, 2 skipped`; `lost 1 (listed 1, unexpected 0); new tests 14, not passing 0; baseline failures still failing 2 of 2` (the listed loss is `test_mut26`); `GATE PASS`; `offline unchanged`.
- **Not run.** The browser check (V2), any model, download, venv or network access; the live checks (V4) are the user's, on macstudio. The Task 2-4 full-suite gate lines are computed from the test lists (their targeted Step 2 and Step 4 runs were observed).

Please review the plan. Which execution approach would you prefer?
- **Subagent-driven.** A fresh Sonnet `code-executor` implements each task in `$S/ss-wt` on branch `shots-seed-edit`, and a fresh Opus reviewer checks it before the next one starts.
- **Native.** One session implements every task, then one fresh Opus reviewer checks the whole branch.

I recommend subagent-driven: Task 1 is a large verbatim transcription into a pinned file whose correctness (screening, the record, the reuse key) is load-bearing, Tasks 2-4 consume its names, and a reviewer gate after each task catches a transcription slip before the next task builds on it.
