# Shots Z-Image Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In Compose, one `Stills engine` select (`c-engine`) shows the image engine of every cell (mode x seed) and offers a choice only for shots mode with a seed: "Qwen edit of the seed" (today's path, the default) or "Z-Image", which bin/ltx-movie runs as `--shots --seed-image S --seed-edit-model as-is`: panel 1 is the letterboxed seed and every other panel is a Z-Image still from its own `Image:` text with the character, location, catalog and stills-row LoRAs, exactly as shots mode without a seed.

**Architecture:** No new CLI option: `--seed-edit-model as-is` with `--shots --seed-image` stops being refused (`_resolve_shots`) and selects the Z-Image engine through one predicate, `_shots_zimage_seed(args)`. With it true, `phase2_stills` skips the two Qwen paths and takes the existing shots branch (one `bin/ltx-story-images` run per stills-LoRA group, `--seed-image` included, so panel 1 is the seed); `_shots_missing_stills` always counts panel 1 and every still that `seed_edits.json`/`seed_context_edits.json` records as an `ok` Qwen edit with the same sha256; `_shots_zimage_prepare` moves those Qwen stills into `<story>/redo/<stamp>-<pid>/images/` and warns when plan.json was planned for Qwen; `_story_context` passes `seed_image=None` so the story keeps every cast identity sentence. On the page, `composeEngines(mode, seeded)` gives each cell's options, `S.composeEngine` holds the shots+seed choice, and `composeFields` sends `seed_edit_model: "as-is"`, `seed_edit_loras: null` for Z-Image; V1 rule 8 accepts as-is (and stills LoRAs with it) and refuses only a missing engine.

**Tech Stack:**
- Python 3.13 (`python3` = `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`, pytest 8.3.4); Python 3.9.6 (`/usr/bin/python3`) for the compile check only. node v26 (`/opt/homebrew/bin/node`) for `node --check` and the node-evaluated tests (they skip where node is missing).
- No new dependency. The new test files use the standard library, PIL and pytest, and reuse by import, unchanged: `tests/test_ltx_movie_shots_seed.py` (`sse`: `movie`, `clean_env`, `_phase_args`, `_parse`, `_seed1920`, `_dry`, `_write_story`, `ENGINE_RULE`, `STILLS_RULE`, `HELP`, `DOC_SENTENCE`), `tests/test_dialogue.py` (`dlg`: `ltx_movie`, `se`, `_movie_args`), `tests/story_engine_testutil.py` (`seu`: `set_story_env`, `make_ws`), `tests/test_movie_ui_shots_seed.py` (`uss`: `v1_env`, `_errors`, `UP`, `UNC`, `NEEDS_ENGINE`, `NO_STILLS_LORAS`), `tests/test_movie_ui_qwen_edit.py` (`env`, `_compose`, `_function`, `_job`, `_upload`), `tests/movie_ui_testutil.py` (`mt`: `WS`, `fields`, `api`, `PNG`).

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-11-11-shots-zimage-engine-design.md`, committed as `0f59f51` on branch `shots-zimage` (requirements ZE1-ZE14, edits E1-E16 and U1-U11, tests SZ1-SZ16, KPIs SZK1-SZK6, live checks L1-L6). Its line citations are at `e8d7f3a`; `0f59f51` adds only the spec, so they hold. Every Edit below is located by its old text, never by a line number. Where the spec cannot work as written against the code or the suite, an entry of "Spec conflicts" says which way this plan rules; "Plan rulings" fill details the spec leaves open.

## Spec conflicts

The spec is the authority. Each entry names the conflict, the ruling, and the cost if the ruling is wrong.

1. **SC1 [defect] The baseline directory `$S/sz-baseline` was not recorded at `e8d7f3a`.** Its `baseline-pytest.txt` has no line for `tests/test_audio_only_quoted.py` (added by `3d5e345`, part of `e8d7f3a`), and its `gate.py` names the lora-scope test files as `NEW_FILES`. Spec Plan "Before Task 1" item 2 says to record the baseline at `e8d7f3a`. **Ruling:** "Before Task 1" Step 3 re-records `$S/sz-baseline/baseline-pytest.txt` and `baseline-ok-lines.txt` at `0f59f51` (the code of `e8d7f3a`) and rewrites `gate.py` with this plan's two new test files. **Cost if wrong:** none; a stale baseline would make the gate report every audio-only-quoted test as "new".
2. **SC2 [dispatch] The gate counts 21 new tests, not SZK1's 16.** The planning dispatch requires one pinning test per Review Focus line; those five tests are new IDs. **Ruling:** SZK1 is read as `lost 0 (listed 0, unexpected 0); new tests 21, not passing 0` (SZ1-SZ16 plus Review Focus 1-5), `GATE PASS`. **Cost if wrong:** none in behaviour; five more tests.
3. **SC3 [defect] SZK2's `git diff --name-only e8d7f3a HEAD` can never be exactly D1-D7.** The spec (`0f59f51`) and this plan are committed on the branch after `e8d7f3a`. **Ruling:** V1 measures `git diff --name-only e8d7f3a HEAD -- . ':(exclude)docs'`, which must be exactly the 13 paths of D1-D7, and separately checks that `docs/` gains only the spec and this plan. **Cost if wrong:** none.
4. **SC4 [reading] Task 3's comment edit cannot be a whole-line Edit.** The `test_mut26` comment line (`tests/test_movie_ui_builder.py:291`) is one line of 1,827 characters. **Ruling:** that one Edit replaces the exact end of the line, `then to 3d5e345f788b262cc51c6d961f0c1d9737e163fc (audio-only-quoted).`, which occurs exactly once (the `BASELINE` line has the sha but not `(audio-only-quoted)`). Every other Edit in this plan replaces whole lines. **Cost if wrong:** none.
5. **SC5 [defect] The spec's Task 1 test command cannot print "0 failed".** Its `-k "sz or set or cxt or crt or s33 or sit or rst50"` selects `tests/test_story_engine.py::test_rst62_import_sets` (the substring `set` of `sets`), which fails at `e8d7f3a` and is one of the two baseline failures. **Ruling:** the command is run as the spec writes it, and Task 1 Step 6 expects exactly that one failure (`1 failed, 79 passed, 178 deselected` in the planning replay); every other failure is a stop. **Cost if wrong:** none; the gate (Step 7) checks the whole suite against the baseline anyway.

## Plan rulings

1. **R1 [reading] Blank lines.** E2's three functions sit directly before `_shots_missing_stills` with two blank lines between top-level functions, as the file does. U4's block follows `composeSeedDefault`'s closing `  }` after one blank line, and the existing blank line before `function composeFields` stays. None of this changes behaviour.
2. **R2 [reading] SZ5's "SZ5's final state" helper.** SZ6 and Review Focus tests need SZ5's end state; the new test file has `_qwen_state(tmp)`, which builds exactly that state (story.md, panels 1-3, SZ5's two records) and returns `{k: path}`. SZ5 itself builds the state step by step, as the spec writes it.
3. **R3 [reading] Asserts the spec implies but does not spell out.** SZ7 also checks the two new constants' texts and that a dry run without `--force-story` still warns; SZ10 also checks that `sse.HELP` (edited by E14) equals the new help texts; SZ13 also checks that the seed folder made no probe call (`movie_ui_server.py:959` skips the probe for `as-is`, as `_h_job_create` does at `:851`). Each is a property the spec states elsewhere (ZE7, E14, G17).
4. **R4 [reading] Test names.** `test_sz<N>_…` exactly as the spec names them; the Review Focus tests are `test_sz_review_focus_<N>_…`. `grep -rn "def test_sz" tests/` prints nothing at `0f59f51`.
5. **R5 [reading] The new movie-ui test file's docstring** says what it touches (the in-test server, node when installed) instead of the Task 1 file's "contacts a server", which would be false for SZ13.
6. **R6 [reading] The stale texts the spec keeps.** The `Shots mode` docstring paragraph (`bin/ltx-movie:98-102`, "Phase 2 instead edits the seed into every panel's still with the Qwen model of --seed-edit-model (required)") and the `--seed-image` help ("With --shots, Phase 2 instead edits the ORIGINAL into every panel's still") stay as they are: the spec changes only E10-E12, and SZ10 pins `--seed-image`'s help to `sse.HELP["--seed-image"]` and the docstring to `sse.DOC_SENTENCE`. With the Z-Image engine both are now true only for an ID. Recorded for the user; not changed here.
7. **R7 [reading] The flakes.** `tests/test_fleet_tracing.py::test_tr27_fanout_two_rounds_and_missing_reasons`, `::test_trt45_query_endpoints_refuse_browsers_and_bad_queries` and `::test_trt46_post_spans_validation_cap_and_store` are timing-sensitive and untouched by this branch. The gate lists them as allowed losses in every task and every gate block reruns them alone, where they must print `3 passed`.
8. **R8 [reading] The pinned-file check** in Task 3 writes the 23 `PIPELINE_FILES` paths out on each `git diff` line. zsh (this host's shell) does not word-split an unquoted `$P`, so `git diff -- $P` would compare one non-existent path and always look clean.

## Global Constraints

From the spec, verbatim (section in brackets):

- [Status] "The implementer makes no design decisions."
- [Where] "Every path is relative to `WS`; every line number cites `e8d7f3a`." "Nobody but the user accesses macstudio."
- [0.2] "`test_mut26` BASELINE over `PIPELINE_FILES` … `bin/ltx-movie` is the only pinned file that changes; Task 3 moves BASELINE".
- [0.2] "`NEW_PY` tail … not extended ([CR] CR15 precedent); new files still avoid `load_module(` and `urllib`".
- [0.2] "L17b, RST50 `"no_stills" not in phase2_stills` … the new code in `phase2_stills` has no `no_stills`". (L17b checks the whole text from `def phase2_stills(args):` to `def phase3_manifest`, so no new code in that range, E2's functions included, contains `no_stills`.)
- [0.2] "RST50 / L17d / L17f / L46e / L46f literal counts … no new `cmd += ["--seed-image", args.seed_image]`, `phase2_cmd += ["--seed-image", …]`, `_render_flags(args)` or `ltx-mlx-render` path; none of `story-images` counts change (that file is untouched)". (The counts stay: `_render_flags(args)` 4, `os.path.join(WS, "bin", "ltx-mlx-render")` 4, `'\n        cmd += ["--seed-image", args.seed_image]'` 1, `phase2_cmd += ["--seed-image", args.seed_image]` 1, `"--engine"` 0, `"--glob"` 0.)
- [0.2] "L7j (no top-level `import re`) … no new import". (`"\nimport re\n"` must not occur in `bin/ltx-movie`; no import of any kind is added to it.)
- [0.2] "plan prompt no-brace rule (RST8, RST47) … `story_engine.py` untouched".
- [0.2] "QET38/QET39 Compose pins … kept verbatim: `qwenPicker("c-sq", true)`, the `seedEdit` and `seed_edit_model: seedEdit ? …` lines of `composeFields`, `COMPOSE_PICKER.select(f.seed_edit_model || "as-is", …)`".
- [0.2] "deploy gate … records `bin/ltx-movie`'s own sha256; no change".
- [0.3] "Untouched: `story_engine.py`, `bin/ltx-story-images`, `bin/ltx-story-manifest`, `bin/ltx-mlx-render`, `qwen_edit.py`, `movie_ui_server.py`, `movie_ui_batch.py`, `scripts/deploy/*`."
- [0.4, out of scope] "F2 and F4 (Section 7, optional); a per-clip first-frame pipeline for text-to-video and any Z-Image option where a seed is edited outside shots mode (both closed by the user, Section 9); any change to the Qwen path's behaviour, records or texts other than the refusal texts of E3/U1; a new `FIELD_FLAGS` entry; cast refs on the Z-Image seed path; any model run, server or render in tests; any agent access to macstudio."
- [3, Task 1] "each Old occurs exactly once; stop if not".
- [3, Task 2] "Unchanged (ZE11): `build_argv`, `job_phases`, `FIELD_FLAGS`, `DEFAULT_FIELDS`, `movie_ui_server.py` (as-is skips the probe), `movie_ui_batch.py`, the `c-sq` markup and `qwenPicker`. All new page text goes in through markup or `textContent`."
- [0.5] "Every ZE requirement and SZ test is a must-have. There are no nice-to-haves."
- [Plan, Task 3] "a test-only commit; never amend" … "Merge with a merge commit (a squash would orphan BASELINE)."
- [Plan, V3] "push and merge only on the user's go."

Controller rules (every task's requirements include them):

- The repository is public: never commit a secret or token. Never read, cat, grep or source `~/.zshenv` or any `fleet.env`, and never print tokens or secrets. **Before any push** (V3, on the user's go) the controller runs the secret scan of "Verification" V1 over `git diff e8d7f3a..HEAD`; a hit stops the push.
- Never ssh, scp, rsync or HTTP to macstudio or any other host, and never read or suggest copying its files. Never contact :8177 or :8178 or any server other than an in-test `127.0.0.1` one.
- Never run a model, a render, a download, a real (non-dry-run) `bin/ltx-movie` outside the tests, a venv creation or a pip install. Never run tests against the real HOME.
- Never push. Push and the PR are a separate step that needs the user's go.

House rules (every task's requirements include them):

- **The checkout.** Never touch the main checkout `/Users/reubenpatterson/local_agent_harness`. Every command runs in the worktree `$S/sz-wt`, branch `shots-zimage`. Never git stash, reset, amend or check out other work.
- **Paths.** `S` = `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`; `WS` = `$S/sz-wt/qwen-agent-workspace`; `D` = `$S/sz-baseline` (scratch, never staged). The git root is `$S/sz-wt`, so `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix. Run every command from `WS`; shell variables do not persist between commands, so every block defines the variables it uses.
- **Python.** Every changed Python file must compile on Python 3.9.6 and 3.13: no `match` statement, no `X | Y` type expressions, no walrus operator, no `str.removeprefix`, no `zip(strict=)`, no parenthesised context managers. The code blocks below use none of them.
- **Editing.** Executors change tracked files only with the Edit tool, or the Write tool for a new file. Never use `rm`, `sed -i`, a redirect or a script to change a tracked file.
- **Code blocks are copied byte for byte.** An Edit's old text is whole lines (except SC4's one Edit) and occurs exactly once in the file at that moment. If it does not, stop and report; do not adapt it. The Edits of a step are applied in the order written.
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

The five inputs and failure modes most likely to reach a person using this first; the spec implies each, and no SZ row exercises it. Each is pinned by a test named `test_sz_review_focus_N_…` in the task that owns its code.

1. **Odd records and plans in a story directory switched to Z-Image** (a Qwen run that blocked or failed panels, a record of another schema, an unreadable or hand-edited `seed_edits.json`, `seed_context_edits.json` or `plan.json`): Phase 2's first step must not crash, must print nothing, and must move no still; only panel 1 is regenerated. Test: `test_sz_review_focus_1_odd_records_and_plans_move_nothing` (Task 1).
2. **Characters picked with the Z-Image engine** (L2: several stills-LoRA groups): only the group that holds panel 1 reruns, a complete group without panel 1 is skipped, and a recorded Qwen edit at panel 1 is moved aside before the seed is written over it. Test: `test_sz_review_focus_2_with_characters_only_panel_1s_group_reruns` (Task 1).
3. **`--redo N` on the Z-Image path** (the Shots tab's redo of a Z-Image movie): `_resolve_shots` accepts it, the phase tuple has `phase_redo_shots` before `phase2_stills` and no Phase 1c, and the missing panels are the redo panels plus panel 1. Test: `test_sz_review_focus_3_a_redo_on_the_zimage_path` (Task 1).
4. **A redo job queued from the page with the Z-Image engine** (L4's rerun): the job is created (201) with no Qwen probe, its argv has `--redo 2` and `--seed-edit-model as-is` and no `--seed-edit-lora`, and its phases have no `1c`. Test: `test_sz_review_focus_4_a_redo_job_on_the_zimage_engine` (Task 2).
5. **A stale engine choice when the cell changes** (Z-Image picked, then the mode switched to chained, the upload replaced by a folder, the seed radio left on with no upload, or no-stills chosen): the select shows exactly the cell's options and value, is disabled for a one-option cell, and shows the Z-Image note only for a seeded shots cell on Z-Image. Test: `test_sz_review_focus_5_the_engine_select_follows_the_cell` (Task 2; node).

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `bin/ltx-movie` (pinned) | Modify (Task 1) | E1 constants; E2 `_shots_zimage_seed`, `_shots_qwen_stills`, `_shots_zimage_prepare`; E3 `_resolve_shots`; E4 `phase2_stills` dispatch; E5 `_shots_missing_stills`; E6 `_phase2_shots`; E7 `_story_context`; E8, E9 the dry run; E10, E11 the helps; E12 the docstring. |
| `tests/test_ltx_movie_shots_zimage.py` | Create (Task 1) | SZ1-SZ10, Review Focus 1-3. |
| `tests/test_shots_mode.py`, `tests/test_ltx_movie_shots_seed.py`, `tests/test_ltx_movie_seed_context.py` | Modify (Task 1) | E13-E15: S33, SET1 (`MODEL_RULE`, the as-is case), `HELP`, CXT1. |
| `movie_ui_lib.py` | Modify (Task 2) | U1: V1 rule 8. |
| `static/movie-ui/index.html` | Modify (Task 2) | U2: the `c-engine` select and `c-engine-note`. |
| `static/movie-ui/app.js` | Modify (Task 2) | U3 `S.composeEngine`; U4 `composeEngines`, `composeEngineUpdate`; U5 `composeFields`; U6 `updateComposeButtons`; U7 the listener. |
| `tests/test_movie_ui_shots_zimage.py` | Create (Task 2) | SZ11-SZ16, Review Focus 4-5. |
| `tests/test_movie_ui_checks.py`, `tests/test_movie_ui_seedfolder.py`, `tests/test_movie_ui_shots_seed.py` | Modify (Task 2) | U8-U10: MUT4, SDT17, `NEEDS_MODEL`, SET16, SET20. |
| `tests/test_movie_ui_builder.py` | Modify (Task 3 only) | `test_mut26`'s `BASELINE` and comment. |

**Task split.** The spec's three tasks, unchanged. Task 1 makes the CLI path work (the page still sends only Qwen models, so nothing a user reaches changes yet); Task 2 exposes it in Compose; Task 3 is the test-only re-baseline after the only pinned-file commit (Task 1's).

---

## Between tasks: the existing suite

**Allowed lost passes** (`$D/expected-failures.txt`, written in "Before Task 1" Step 3). A line is `<first task> <last task> <test id> <note>`:

```text
# shots-zimage plan: baseline passes allowed to be lost. Columns: first task, last task, test id, note
1 2 tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged bin/ltx-movie changes in Task 1; Task 3 moves BASELINE
1 3 tests/test_fleet_tracing.py::test_tr27_fanout_two_rounds_and_missing_reasons flaky timing test; every gate block reruns it alone, where it must pass
1 3 tests/test_fleet_tracing.py::test_trt45_query_endpoints_refuse_browsers_and_bad_queries flaky timing test; every gate block reruns it alone, where it must pass
1 3 tests/test_fleet_tracing.py::test_trt46_post_spans_validation_cap_and_store flaky daemon start-up test; every gate block reruns it alone, where it must pass
```

**The gate** is `zsh $D/gate-run.sh N` (written in "Before Task 1" Step 3; a full run of about 20 minutes; it may run in the background). It prints, in order: the `disk ok` line, the run's summary line, the gate's `lost … new tests … baseline failures still failing …` line with any `LOST`/`NEW-TEST-FAIL` lines and `GATE PASS` or `GATE STOP`, the flake rerun's summary (expected `3 passed`), and `ATK2 OK lines unchanged` (the five `OK n/n` lines of `test_ltx_movie_offline.py`, `test_qwen_agent_image_oneshot.py`, `test_qwen_agent_danger_auto_approve.py`, `test_qwen_agent_context_budget.py`, `test_qwen_agent_session_memory.py` are the baseline's; SZK1's `test_ltx_movie_offline.py` line is the first of them).

**When the gate prints `GATE STOP`:** the executor stops and reports the UNEXPECTED or NEW-TEST-FAIL IDs with the output of `python3 -B -m pytest -q -p no:cacheprovider --tb=short <ids>`. A lost pass the list does not name is a defect in this task's code; the controller has an Opus reviewer rule on it and writes the exact fix. If an UNEXPECTED ID is `tests/test_fleet_tracing.py::test_trt41a_trace_cli_on_one_agent` or `tests/test_fleet_integration.py::test_t47_signatures_and_loopback_rules` (timing-sensitive, unrelated), rerun it alone; if it passes alone, the controller appends `<N> 3 <id> flaky` to the list and V1 rechecks it. A new test is never added to the list.

**Must stay green in every task** (none is in the list, so a failure stops the gate): `tests/test_ltx_movie_offline.py` (L7j, L17b, L17d, L17f, L29d, L46e, L46f), `tests/test_story_engine.py::test_rst50_source_literal_counts`, `tests/test_story_engine.py::test_rst8_plan_prompt_matrix`, `tests/test_qwen_edit.py` (QET11 `NEW_PY`), `tests/test_movie_ui_qwen_edit.py` (QET38, QET39), `tests/test_ltx_movie_shots_seed.py` (the Qwen path, SET1-SET15), `tests/test_ltx_movie_seed_context.py`, `tests/test_ltx_movie_seed_context_frame.py`, `tests/test_ltx_movie_cast_refs.py`, `tests/test_seeded_no_identity.py`, `tests/test_movie_ui_shots_seed.py` (SET17-SET21), `tests/test_deploy_pkg.py`, `tests/test_movie_ui_builder.py::test_mut25_*`.

---

## Before Task 1: the plan commit, the snapshot, the baseline (controller; no code)

- [ ] **Step 1: Commit this plan and confirm the tree.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/sz-wt/qwen-agent-workspace
git branch --show-current                                      # expected: shots-zimage
git status --short                                             # expected: ?? docs/superpowers/plans/2026-11-11-shots-zimage-engine.md (only)
git add docs/superpowers/plans/2026-11-11-shots-zimage-engine.md
git diff --cached --name-only                                  # expected: qwen-agent-workspace/docs/superpowers/plans/2026-11-11-shots-zimage-engine.md
git commit -m "docs: shots-zimage engine implementation plan" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git log -3 --format=%h' '%s                                    # expected: <plan sha> docs: shots-zimage engine implementation plan; 0f59f51 docs: shots-zimage engine design spec; e8d7f3a Merge pull request #20 ...
git diff --stat e8d7f3a HEAD -- . ':(exclude)docs' | tail -1   # expected: no output
wc -l bin/ltx-movie movie_ui_lib.py static/movie-ui/index.html static/movie-ui/app.js tests/test_shots_mode.py tests/test_ltx_movie_shots_seed.py tests/test_ltx_movie_seed_context.py tests/test_movie_ui_checks.py tests/test_movie_ui_seedfolder.py tests/test_movie_ui_shots_seed.py tests/test_movie_ui_builder.py | head -11
```

Expected `wc -l` counts (at `0f59f51`): `bin/ltx-movie` 4212, `movie_ui_lib.py` 2486, `static/movie-ui/index.html` 506, `static/movie-ui/app.js` 3413, `tests/test_shots_mode.py` 2543, `tests/test_ltx_movie_shots_seed.py` 730, `tests/test_ltx_movie_seed_context.py` 683, `tests/test_movie_ui_checks.py` 495, `tests/test_movie_ui_seedfolder.py` 1165, `tests/test_movie_ui_shots_seed.py` 236, `tests/test_movie_ui_builder.py` 302. If any value differs, stop and report: every Edit below was written against this tree.

- [ ] **Step 2: The compressed snapshot (house rule; spec Plan "Before Task 1" item 1) and the disk.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
tar czf $S/snapshot-pre-sz-e8d7f3a.tgz -C $S/sz-wt --exclude generated .
ls -l $S/snapshot-pre-sz-e8d7f3a.tgz
tar tzf $S/snapshot-pre-sz-e8d7f3a.tgz | grep -c 'qwen-agent-workspace/bin/ltx-movie$'   # expected: 1
tar tzf $S/snapshot-pre-sz-e8d7f3a.tgz | grep -c '/generated/'                           # expected: 0
df -g $S/sz-wt | tail -1 | awk '{print ($4 >= 20) ? "disk ok: " $4 " GiB free" : "DISK LOW: " $4 " GiB free"}'
```

Expected: the archive exists, `1`, `0`, and `disk ok` (at least 20 GiB; on `DISK LOW` stop and report, never delete anything).

- [ ] **Step 3: Write the gate files and record the baseline (SC1).** Write three scratch files with the Write tool (outside the repository, never staged):

1. `$D/expected-failures.txt`: exactly the `text` block of "Between tasks" above.
2. `$D/gate-run.sh`, exactly:

```bash
#!/bin/zsh
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/sz-baseline
N=$1
cd $S/sz-wt/qwen-agent-workspace
df -g . | tail -1 | awk '{print ($4 >= 5) ? "disk ok: " $4 " GiB free" : "DISK LOW: " $4 " GiB free"}'
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/task-$N-pytest.txt 2>&1; tail -1 $D/task-$N-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/task-$N-pytest.txt $D/expected-failures.txt $N
python3 -B -m pytest -q -p no:cacheprovider tests/test_fleet_tracing.py::test_tr27_fanout_two_rounds_and_missing_reasons tests/test_fleet_tracing.py::test_trt45_query_endpoints_refuse_browsers_and_bad_queries tests/test_fleet_tracing.py::test_trt46_post_spans_validation_cap_and_store 2>&1 | tail -1
for f in tests/test_ltx_movie_offline.py tests/test_qwen_agent_image_oneshot.py tests/test_qwen_agent_danger_auto_approve.py tests/test_qwen_agent_context_budget.py tests/test_qwen_agent_session_memory.py; do echo "$f $(python3 -B $f 2>&1 | tail -1)"; done > $D/task-$N-ok-lines.txt
diff $D/baseline-ok-lines.txt $D/task-$N-ok-lines.txt && echo "ATK2 OK lines unchanged"
```

3. `$D/gate.py`, exactly:

```python
"""The task gate of the shots-zimage plan: a full pytest -rA run against the baseline. A new test is any
test of tests/test_ltx_movie_shots_zimage.py or tests/test_movie_ui_shots_zimage.py, or any test ID the
baseline does not have."""
import re
import sys

base_file, run_file, expected_file, task = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
NEW_FILES = ("tests/test_ltx_movie_shots_zimage.py::", "tests/test_movie_ui_shots_zimage.py::")


def status(path):
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            found = re.match(r"^(PASSED|FAILED|ERROR|SKIPPED) (\S+)", line)
            if found:
                out[found.group(2)] = found.group(1)
    return out


base, now = status(base_file), status(run_file)
expected, flaky = [], []
with open(expected_file, encoding="utf-8") as f:
    for line in f:
        parts = line.split()
        if not parts or line.startswith("#"):
            continue
        if int(parts[0]) <= task <= int(parts[1]):
            expected.append(parts[2])
        if parts[3:4] == ["flaky"]:
            flaky.append(parts[2])


def listed(test):
    return any(test == e or test.startswith(e + "[") for e in expected)


lost = sorted(t for t, s in base.items() if s == "PASSED" and now.get(t) != "PASSED")
unexpected = [t for t in lost if not listed(t)]
mine = sorted(t for t in now if t.startswith(NEW_FILES) or t not in base)
broken = [t for t in mine if now[t] != "PASSED"]
old_failures = sorted(t for t, s in base.items() if s in ("FAILED", "ERROR") and t not in flaky)
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

Then record the baseline (about 20 minutes; it may run in the background):

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/sz-baseline
cd $S/sz-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1; tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
grep -c '^PASSED tests/test_audio_only_quoted.py::' $D/baseline-pytest.txt
grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $D/baseline-pytest.txt
for f in tests/test_ltx_movie_offline.py tests/test_qwen_agent_image_oneshot.py tests/test_qwen_agent_danger_auto_approve.py tests/test_qwen_agent_context_budget.py tests/test_qwen_agent_session_memory.py; do echo "$f $(python3 -B $f 2>&1 | tail -1)"; done > $D/baseline-ok-lines.txt; cat $D/baseline-ok-lines.txt
```

Expected: the summary `2 failed, 2756 passed, 2 skipped` (this planning session's clean clone at `0f59f51`); exactly the two `FAILED` lines `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets - AssertionError: b...`; no `ERROR` line; `6` (the audio-only-quoted tests are in this baseline, SC1); `1` (`test_mut26` passes at `0f59f51`); the five lines `tests/test_ltx_movie_offline.py OK 347/347`, `tests/test_qwen_agent_image_oneshot.py OK 25/25`, `tests/test_qwen_agent_danger_auto_approve.py OK 57/57`, `tests/test_qwen_agent_context_budget.py OK 68/68`, `tests/test_qwen_agent_session_memory.py OK 205/205`. If a `tests/test_fleet_tracing.py` flake of R7 is an extra `FAILED` line, rerun the three alone (the gate-run.sh line); `3 passed` means the baseline stands (the gate ignores them); anything else, or any other difference, stop and report. These files **are** the baseline.

---

### Task 1: The Z-Image seed path in `bin/ltx-movie` (pinned: `bin/ltx-movie`) (E1-E16; SZ1-SZ10, Review Focus 1-3)

This task implements, in `bin/ltx-movie` (ZE1-ZE10):
- E12: one sentence after "Absent, or as-is, the seed is used unchanged." in the docstring's "Seed edit" paragraph.
- E1: `SHOTS_ZIMAGE_MOVE_WHY`, `SHOTS_ZIMAGE_PLAN_WARNING` after `SHOTS_SEED_LORA_NOTE`.
- E10: the `--seed-edit-model` help. E11: the `--shots` help.
- E3: `_resolve_shots` accepts as-is (stills LoRAs too) and refuses only a missing `--seed-edit-model`, with a new text.
- E7: `_story_context` passes `seed_image=None` on the Z-Image path.
- E4: `phase2_stills` sends a Z-Image run to the shots branch.
- E2, E5: `_shots_zimage_seed`, `_shots_qwen_stills`, `_shots_zimage_prepare`; `_shots_missing_stills` counts panel 1 and recorded Qwen stills.
- E6: `_phase2_shots` calls `_shots_zimage_prepare` first.
- E8, E9: the dry run's Phase 0 sentence, its Phase 2 branch, and the dry-run moves.
- E13-E15 (test texts) and E16 (the new test file).

The page still sends only Qwen model IDs after this task, so no Compose path changes; the new path is reachable from the CLI.

**Files:**
- Modify: `bin/ltx-movie` (docstring `:116`; constants `:165-166`; `--seed-edit-model` help `:396-402`; `--shots` help `:490-493`; `_resolve_shots` `:1490-1501`; `_story_context` `:1936-1941`; `phase2_stills` `:2341-2342`; `_shots_missing_stills` `:2421-2427`; `_phase2_shots` `:2446-2447`; dry run `:3923-3925`, `:3963-3964`, `:3998-3999`; all located by text below).
- Modify: `tests/test_shots_mode.py` (S33 `:936-938`), `tests/test_ltx_movie_shots_seed.py` (`MODEL_RULE` `:226-227`, SET1 `:240`, `:247-248`, `HELP` `:300-310`), `tests/test_ltx_movie_seed_context.py` (CXT1 `:222-227`).
- Create: `tests/test_ltx_movie_shots_zimage.py`.

**Interfaces:**
- Consumes (existing, unchanged): `_story_paths(story_id) -> {"story_dir", "story_md", "images_dir", …}`, `_shots_seed_paths(story_dir)["record"]` (`seed_edits.json`), `_seed_context_paths(story_dir)["record"]` (`seed_context_edits.json`), `_shots_seed_entries(record_path, schema) -> {int n: entry dict}` (`{}` when missing, unreadable or another schema), `_sha256_file(path) -> hex str`, `SHOTS_SEED_EDITS_SCHEMA` (`"ltx-movie.seed-edits.v1"`), `SEED_CONTEXT_SCHEMA` (`"ltx-movie.seed-context-edits.v1"`), `_phase2_shots(args, cmd, exclude=())`, `_shots_stills_groups(story_md_path, members, locations=())`, `_print_shots_stills_plan(args, cmd, exclude=())`, `_stream_and_tee(cmd, log_path) -> int`, the module imports `json`, `os`, `sys`, `time`.
- Produces: `_shots_zimage_seed(args) -> bool` (True only for `--shots`, a `--seed-image` and `--seed-edit-model as-is`; reads attributes with `getattr` defaults); `_shots_qwen_stills(args) -> {int: str}` (panel number to `images/panel_NN.png`); `_shots_zimage_prepare(args, dry_run=False) -> None`; `SHOTS_ZIMAGE_MOVE_WHY`, `SHOTS_ZIMAGE_PLAN_WARNING` (one `%s`, the story.md path); the CLI contract Task 2 relies on: `bin/ltx-movie … --shots --seed-image S --seed-edit-model as-is` is accepted (with `--stills-lora` too), and `--shots --seed-image S` without `--seed-edit-model` is refused with E3's text.

- [ ] **Step 1: Write the failing tests.**

Create `tests/test_ltx_movie_shots_zimage.py` with the Write tool, exactly:

```python
"""Tests for the shots Z-Image engine (docs/superpowers/specs/2026-11-11-shots-zimage-engine-design.md, SZ1-SZ10): with
--shots, --seed-image and --seed-edit-model as-is, panel 1 is the seed and every other panel a Z-Image still.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_ltx_movie_shots_zimage.py

No test loads a model, renders or contacts a server. Stdlib, PIL and pytest.
"""

import argparse
import glob
import hashlib
import json
import os

import pytest
from PIL import Image

import story_engine_testutil as seu
import test_dialogue as dlg
import test_ltx_movie_shots_seed as sse
from test_ltx_movie_shots_seed import clean_env  # noqa: F401

movie = sse.movie
MOVE = "(a Qwen edit of the seed; the Z-Image engine renders this panel again)"
NO_MODEL = ("Error: --shots with --seed-image needs --seed-edit-model: a Qwen model ID makes every panel's still an "
            "edit of the seed; as-is keeps the seed as panel 1 and renders every other panel's still with Z-Image\n")
CONTEXT_AS_IS = ("Error: --seed-context needs --seed-edit-model ID, a Qwen registry edit model (as-is is refused): "
                 "every shots still is a Qwen edit of the seed\n")
PLAN_WARNING = ("Warning: %s was planned for the Qwen engine (plan.json records the seed image), so its Image: lines "
                "leave out the cast descriptions that Z-Image draws from; rerun with --force-story to plan the story "
                "for Z-Image")
HELP_EDIT = (
    "with --seed-image: edit the seed into panel 1 with a Qwen registry edit model (qwen21-q4, qwen21-q8, "
    "qwen21-bf16, qwen2511-q4, qwen2511-bf16), prompted by panel 1's Image: text after Phase 1 and screened with "
    "content safety; as-is, like leaving the flag out, uses the seed unchanged. With --shots it is required and "
    "chooses the stills engine: an ID makes every panel's still an edit of the seed, each prompted by its own Image: "
    "text; as-is keeps the seed as panel 1 and renders every other panel's still with Z-Image and its stills LoRAs, "
    "as --shots does without a seed. See docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md, "
    "2026-11-05-compose-shots-seed-edit-design.md and 2026-11-11-shots-zimage-engine-design.md.")
HELP_SHOTS = (
    "shots mode: every panel is its own shot with its own Image: still and is rendered from that still (no "
    "chaining; cuts between panels). Phase 1 uses the shots story template and enforces the shot rules (one "
    "action per Motion:, at most two cast characters per shot), Phase 2 renders a still for every panel, and "
    "every cast character LoRA defaults to 0.8. With --seed-image, --seed-edit-model (required) chooses the stills "
    "engine: an ID makes every panel's still a Qwen edit of the seed; as-is keeps the seed as panel 1 and renders "
    "every other panel's still with Z-Image. See docs/superpowers/specs/2026-10-06-shots-mode-design.md.")
DOC_SENTENCE = (
    "Absent, or as-is, the seed is used unchanged. With --shots (docs/superpowers/specs/2026-11-11-shots-zimage-"
    "engine-design.md) the flag is required: as-is keeps the seed as panel 1 and renders every other panel's still "
    "with Z-Image and its stills LoRAs, as --shots does without a seed.")
STILLS_GROUPS = ("Stills groups: computed from story.md after Phase 1 -- one run per distinct set of cast stills "
                 "LoRAs, each with --only <PANELS> (that group's panels):")
GROUP_CMD = ["py", "ltx-story-images", "--only", "1", "--seed-image", "/s.jpg"]


def _z(tmp, **kw):
    """tests/test_ltx_movie_shots_seed.py's phase args on the Z-Image engine: --seed-edit-model as-is, no seed edit."""
    return sse._phase_args(tmp, seed_edit=None, seed_edit_model="as-is", **kw)


def _stills(tmp, n=3):
    """<tmp>/stories/s1/images/panel_0k.png for k in 1..n, each 8x8 RGB of colour (10 * k, 0, 0); returns {k: path}."""
    images = os.path.join(tmp, "stories", "s1", "images")
    os.makedirs(images, exist_ok=True)
    paths = {}
    for k in range(1, n + 1):
        paths[k] = os.path.join(images, "panel_%02d.png" % k)
        Image.new("RGB", (8, 8), (10 * k, 0, 0)).save(paths[k])
    return paths


def _rec(tmp, name, schema, entries):
    """<tmp>/stories/s1/<name> as {"schema": schema, "panels": entries}; returns its path."""
    path = os.path.join(tmp, "stories", "s1", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"schema": schema, "panels": entries}, f)
    return path


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _qwen_state(tmp):
    """SZ5's final state: story.md, panels 1-3, seed_edits.json recording panel 2 (its sha) and panel 3 (another sha)
    as ok, and seed_context_edits.json recording panel 3 (its sha) as ok. Returns {k: path}."""
    sse._write_story(tmp)
    p = _stills(tmp)
    _rec(tmp, "seed_edits.json", "ltx-movie.seed-edits.v1",
         [{"n": 2, "status": "ok", "still_sha256": _sha(p[2])}, {"n": 3, "status": "ok", "still_sha256": "0" * 64}])
    _rec(tmp, "seed_context_edits.json", "ltx-movie.seed-context-edits.v1",
         [{"n": 3, "status": "ok", "still_sha256": _sha(p[3])}])
    return p


def _recorder(calls):
    """A _stream_and_tee stand-in: records each command and returns 0."""
    return lambda cmd, log_path: calls.append(list(cmd)) or 0


# --- SZ1 (ZE2): the option rules ----------------------------------------------------------------------------

def test_sz1_the_option_rules(clean_env, capsys):
    tmp = clean_env["tmp"]
    shots = ["--shots", "--seed-image", sse._seed1920(tmp)]
    as_is = ["--seed-edit-model", "as-is"]
    for extra, rc, err in (([], 2, NO_MODEL), (as_is, 0, ""),
                           (as_is + ["--stills-lora", "/x.safetensors"], 0, ""),
                           (as_is + ["--story-legacy"], 2, sse.ENGINE_RULE % "--story-legacy"),
                           (["--seed-edit-model", "qwen21-q4", "--stills-lora", "/x.safetensors"], 2,
                            sse.STILLS_RULE)):
        assert movie._resolve_shots(sse._parse(*(shots + extra))) == rc, extra
        assert capsys.readouterr().err == err, extra
    base = ["n", "--story-id", "s1", "--dry-run", "--no-review", "--no-auto-lora"] + shots + as_is
    for extra, err in ((["--seed-edit-lora", "uncensored=1.0"],
                        "Error: --seed-edit-lora cannot be combined with --seed-edit-model as-is\n"),
                       (["--cast-refs-model", "qwen21-q4"],
                        "Error: --cast-refs-model cannot be combined with --seed-image: with a seed image every shots "
                        "still is already a Qwen edit of the seed\n"),
                       (["--seed-context", "still"], CONTEXT_AS_IS)):
        assert movie.main(base + extra) == 2, extra
        assert capsys.readouterr().err == err, extra


# --- SZ2 (ZE1): the path predicate --------------------------------------------------------------------------

def test_sz2_the_path_predicate():
    def zimage(shots, image, model):
        return movie._shots_zimage_seed(argparse.Namespace(shots=shots, seed_image=image, seed_edit_model=model))

    assert zimage(True, "/s.png", "as-is") is True
    for case in ((True, "/s.png", "qwen21-q4"), (True, "/s.png", None), (True, None, "as-is"),
                 (False, "/s.png", "as-is")):
        assert zimage(*case) is False, case
    assert movie._shots_zimage_seed(argparse.Namespace(shots=True, seed_image="/s.png")) is False


# --- SZ3 (ZE5): the phase tuple has no Phase 1c --------------------------------------------------------------

def test_sz3_the_phase_tuple(clean_env):
    args = sse._parse("--shots", "--seed-image", sse._seed1920(clean_env["tmp"]), "--seed-edit-model", "as-is")
    assert movie._resolve_shots(args) == 0
    assert movie._resolve_seed_edit(args) == 0 and args.seed_edit is None
    args.seed_context = None
    args.story_server_stop_after_story = True
    assert [p.__name__ for p in movie._phase_sequence(args)] == [
        "phase0_seed", "phase1_story", "phase_release_story_server", "phase2_stills", "phase3_manifest",
        "phase4_render"]
    args.story_only = True
    assert [p.__name__ for p in movie._phase_sequence(args)] == ["phase0_seed", "phase1_story"]


# --- SZ4 (ZE4): Phase 2 runs the shots branch with the seed and the stills LoRAs ------------------------------

def test_sz4_phase_2_runs_the_shots_branch(clean_env, monkeypatch, capsys):
    calls = {"qwen": [], "shots": []}
    monkeypatch.setattr(movie, "_phase2_shots_seed", lambda args: calls["qwen"].append(args) or 0)
    monkeypatch.setattr(movie, "_phase2_seed_context", lambda args: calls["qwen"].append(args) or 0)
    monkeypatch.setattr(movie, "_phase2_shots", lambda args, cmd: calls["shots"].append(list(cmd)) or 0)
    args = _z(clean_env["tmp"], global_stills_loras=[("/x/still.safetensors", 0.8)])
    assert movie.phase2_stills(args) == 0
    assert calls["qwen"] == [] and len(calls["shots"]) == 1
    cmd = calls["shots"][0]
    assert cmd[cmd.index("--seed-image") + 1] == args.seed_image
    assert cmd[cmd.index("--lora") + 1] == "/x/still.safetensors:0.8"
    assert cmd[cmd.index("--only") + 1] == "1"
    assert cmd[cmd.index("--width") + 1] == "1408"
    assert capsys.readouterr().out == "=== Phase 2: stills ===\n"


# --- SZ5 (ZE6): the missing stills: panel 1 and every recorded Qwen still ----------------------------------

def test_sz5_missing_stills(clean_env):
    tmp = clean_env["tmp"]
    sse._write_story(tmp)
    p = _stills(tmp)
    _rec(tmp, "seed_edits.json", "ltx-movie.seed-edits.v1",
         [{"n": 2, "status": "ok", "still_sha256": _sha(p[2])}, {"n": 3, "status": "ok", "still_sha256": "0" * 64}])
    assert movie._shots_missing_stills(_z(tmp), [1, 2, 3]) == [1, 2]
    _rec(tmp, "seed_context_edits.json", "ltx-movie.seed-context-edits.v1",
         [{"n": 3, "status": "ok", "still_sha256": _sha(p[3])}])
    assert movie._shots_missing_stills(_z(tmp), [1, 2, 3]) == [1, 2, 3]
    assert movie._shots_missing_stills(sse._phase_args(tmp), [1, 2, 3]) == []
    assert movie._shots_missing_stills(sse._phase_args(tmp, seed_image=None, seed_edit=None), [1, 2, 3]) == []


# --- SZ6 (ZE6): the Qwen stills move aside, and panel 1's group runs ----------------------------------------

def test_sz6_qwen_stills_move_aside_and_the_group_runs(clean_env, monkeypatch, capsys):
    tmp = clean_env["tmp"]
    p = _qwen_state(tmp)
    old = dict((n, _sha(p[n])) for n in (2, 3))
    calls = []
    monkeypatch.setattr(movie, "_stream_and_tee", _recorder(calls))
    capsys.readouterr()
    assert movie._phase2_shots(_z(tmp), list(GROUP_CMD)) == 0
    assert len(calls) == 1
    assert calls[0][calls[0].index("--only") + 1] == "1,2,3" and calls[0][-1] == "--shots"
    assert os.path.exists(p[1]) and not os.path.exists(p[2]) and not os.path.exists(p[3])
    story_dir = os.path.join(tmp, "stories", "s1")
    moved = {}
    for n in (2, 3):
        found = glob.glob(os.path.join(story_dir, "redo", "*", "images", "panel_%02d.png" % n))
        assert len(found) == 1, n
        moved[n] = found[0]
        assert _sha(moved[n]) == old[n]
    out = capsys.readouterr().out.splitlines()
    assert [line for line in out if line.startswith("stills: moved ")] == [
        "stills: moved %s -> %s %s" % (p[n], moved[n], MOVE) for n in (2, 3)]
    for n in (2, 3):
        Image.new("RGB", (8, 8), (0, 10 * n, 0)).save(p[n])
    assert movie._phase2_shots(_z(tmp), list(GROUP_CMD)) == 0
    assert len(calls) == 2 and calls[1][calls[1].index("--only") + 1] == "1,2,3"
    assert not [line for line in capsys.readouterr().out.splitlines() if line.startswith("stills: moved ")]
    assert movie._phase2_shots(sse._phase_args(tmp, seed_image=None, seed_edit=None), list(GROUP_CMD)) == 0
    assert len(calls) == 2
    assert ("stills group 1/1 (no character LoRAs; panels 1,2,3): every still exists; skipped"
            in capsys.readouterr().out.splitlines())


# --- SZ7 (ZE7): the warning for a story planned for the Qwen engine -----------------------------------------

def test_sz7_the_plan_warning(clean_env, capsys):
    tmp = clean_env["tmp"]
    story_dir = sse._write_story(tmp)
    story_md = os.path.join(story_dir, "story.md")
    plan = os.path.join(story_dir, "plan.json")
    assert movie.SHOTS_ZIMAGE_PLAN_WARNING == PLAN_WARNING and movie.SHOTS_ZIMAGE_MOVE_WHY == MOVE
    with open(plan, "w", encoding="utf-8") as f:
        json.dump({"seed_image": "/s/seed.png"}, f)
    movie._shots_zimage_prepare(_z(tmp))
    assert capsys.readouterr().out == movie.SHOTS_ZIMAGE_PLAN_WARNING % story_md + "\n"
    movie._shots_zimage_prepare(_z(tmp), dry_run=True)
    assert capsys.readouterr().out == movie.SHOTS_ZIMAGE_PLAN_WARNING % story_md + "\n"
    movie._shots_zimage_prepare(_z(tmp, force_story=True), dry_run=True)
    assert capsys.readouterr().out == ""
    with open(plan, "w", encoding="utf-8") as f:
        json.dump({"seed_image": None}, f)
    movie._shots_zimage_prepare(_z(tmp))
    assert capsys.readouterr().out == ""
    os.remove(plan)
    movie._shots_zimage_prepare(_z(tmp))
    assert capsys.readouterr().out == ""


# --- SZ8 (ZE3): the Z-Image story keeps the cast identity sentences ------------------------------------------

def test_sz8_the_story_keeps_the_identity_sentences(tmp_path, monkeypatch):
    seu.set_story_env(monkeypatch, tmp_path)
    monkeypatch.setattr(dlg.ltx_movie, "WS", seu.make_ws(tmp_path))
    args = dlg._movie_args("n", "--story-id", "x", "--shots", "--seed-image", "/s/seed.png", "--seed-edit-model",
                           "as-is")
    args.seed_downscaled_path = "/s/agent.png"
    ctx = dlg.ltx_movie._story_context(args)
    assert ctx.seed_image is None and ctx.seed_agent_image == "/s/agent.png"
    assert not dlg.se.seed_omits_identities(ctx)
    args = dlg._movie_args("n", "--story-id", "x", "--shots", "--seed-image", "/s/seed.png", "--seed-edit-model",
                           "qwen21-q4")
    args.seed_downscaled_path = "/s/agent.png"
    ctx = dlg.ltx_movie._story_context(args)
    assert ctx.seed_image == "/s/seed.png" and ctx.seed_agent_image == "/s/agent.png"
    assert dlg.se.seed_omits_identities(ctx)


# --- SZ9 (ZE9): the dry run ---------------------------------------------------------------------------------

def test_sz9_the_dry_run(clean_env, capsys):
    tmp = clean_env["tmp"]
    seed = sse._seed1920(tmp)
    story_dir = os.path.join(tmp, "stories", "s1")
    shots = ("--shots", "--seed-image", seed, "--seed-edit-model", "as-is")
    out = sse._dry(capsys, *shots)
    lines = out.splitlines()
    zero = [line for line in lines if line.startswith("Would validate ")]
    assert len(zero) == 1 and zero[0].endswith(
        "(long edge 1024px) to %s. Phase 2 fits the ORIGINAL into panel_01.png at twice the video size and renders "
        "every other panel's still with Z-Image; nothing is cropped." % os.path.join(story_dir, "seed_downscaled.png"))
    assert "--- Phase 1c: seed edit ---" not in lines
    assert "Would edit the seed into every panel's still" not in out
    i = lines.index(STILLS_GROUPS)
    assert ("--seed-image " + seed) in lines[i + 1] and lines[i + 1].endswith("--shots")
    assert clean_env["fake"].calls == {"selection_problem": [], "wait_for_memory": [], "run_jobs": []}
    sse._write_story(tmp)
    p = _stills(tmp)
    _rec(tmp, "seed_edits.json", "ltx-movie.seed-edits.v1",
         [{"n": 2, "status": "ok", "still_sha256": _sha(p[2])}, {"n": 3, "status": "ok", "still_sha256": "0" * 64}])
    lines = sse._dry(capsys, *shots).splitlines()
    assert "Would move %s -> %s %s" % (
        p[2], os.path.join(story_dir, "redo", "<UTC stamp>-<pid>", "images", "panel_02.png"), MOVE) in lines
    assert not [line for line in lines if line.startswith("Would move ") and "panel_03.png" in line]
    assert "stills group 1/1 (no character LoRAs; panels 1,2,3)" in lines
    assert not [line for line in lines if "would be skipped" in line]
    assert os.path.exists(p[2]) and not os.path.exists(os.path.join(story_dir, "redo"))


# --- SZ10 (ZE10): the helps and the docstring ---------------------------------------------------------------

def test_sz10_help_and_docstring():
    actions = dict((a.option_strings[0], a) for a in movie.build_parser()._actions if a.option_strings)
    assert actions["--seed-edit-model"].help == HELP_EDIT
    assert actions["--shots"].help == HELP_SHOTS
    assert actions["--seed-image"].help == sse.HELP["--seed-image"]
    assert sse.HELP["--seed-edit-model"] == HELP_EDIT and sse.HELP["--shots"] == HELP_SHOTS
    doc = " ".join(movie.__doc__.split())
    assert DOC_SENTENCE in doc and sse.DOC_SENTENCE in doc


# --- Review Focus 1: odd records and plans never crash Phase 2's first step and move nothing ------------------

def test_sz_review_focus_1_odd_records_and_plans_move_nothing(clean_env, capsys):
    tmp = clean_env["tmp"]
    story_dir = sse._write_story(tmp)
    p = _stills(tmp)
    record = os.path.join(story_dir, "seed_edits.json")
    context = os.path.join(story_dir, "seed_context_edits.json")
    plan = os.path.join(story_dir, "plan.json")
    odd_entries = [{"n": 1, "status": "blocked", "still_sha256": _sha(p[1])},
                   {"n": 2, "status": "failed", "still_sha256": _sha(p[2])},
                   {"n": True, "status": "ok", "still_sha256": _sha(p[1])},
                   {"n": "3", "status": "ok", "still_sha256": _sha(p[3])},
                   {"n": 3, "status": "ok"},
                   {"n": 9, "status": "ok", "still_sha256": _sha(p[3])},
                   "panel 3"]
    records = ['{"schema": "ltx-movie.seed-edits.v1", "panels": [',
               json.dumps({"schema": "ltx-movie.cast-ref-edits.v1",
                           "panels": [{"n": 2, "status": "ok", "still_sha256": _sha(p[2])}]}),
               json.dumps({"schema": "ltx-movie.seed-edits.v1", "panels": odd_entries}),
               json.dumps({"schema": "ltx-movie.seed-edits.v1",
                           "panels": {"2": {"n": 2, "status": "ok", "still_sha256": _sha(p[2])}}}),
               None]
    plans = ["[1]", '"x"', json.dumps({"seed_image": ""}), json.dumps({"seed_image": 5}), "not json"]
    with open(context, "w", encoding="utf-8") as f:
        json.dump({"schema": "ltx-movie.seed-context-edits.v1", "panels": [
            {"n": 3, "status": "blocked", "still_sha256": _sha(p[3])}]}, f)
    capsys.readouterr()
    for text, plan_text in zip(records, plans):
        if text is None:
            os.remove(record)
        else:
            with open(record, "w", encoding="utf-8") as f:
                f.write(text)
        with open(plan, "w", encoding="utf-8") as f:
            f.write(plan_text)
        args = _z(tmp)
        assert movie._shots_qwen_stills(args) == {}, plan_text
        movie._shots_zimage_prepare(args)
        assert capsys.readouterr().out == "", plan_text
        movie._shots_zimage_prepare(args, dry_run=True)
        assert capsys.readouterr().out == "", plan_text
        assert movie._shots_missing_stills(args, [1, 2, 3]) == [1], plan_text
        assert all(os.path.exists(p[k]) for k in (1, 2, 3)), plan_text
        assert not os.path.exists(os.path.join(story_dir, "redo")), plan_text


# --- Review Focus 2: with characters, only the group holding panel 1 reruns ---------------------------------

def test_sz_review_focus_2_with_characters_only_panel_1s_group_reruns(clean_env, monkeypatch, capsys):
    tmp = clean_env["tmp"]
    story_dir = sse._write_story(tmp)
    p = _stills(tmp, n=4)
    _rec(tmp, "seed_edits.json", "ltx-movie.seed-edits.v1", [{"n": 1, "status": "ok", "still_sha256": _sha(p[1])}])
    monkeypatch.setattr(movie, "_shots_stills_groups",
                        lambda story_md, members, locations=(): [((), [2, 3]), (("kyra",), [1, 4])])
    calls = []
    monkeypatch.setattr(movie, "_stream_and_tee", _recorder(calls))
    capsys.readouterr()
    assert movie._phase2_shots(_z(tmp), list(GROUP_CMD)) == 0
    assert [c[c.index("--only") + 1] for c in calls] == ["1,4"]
    assert calls[0][calls[0].index("--seed-image") + 1] == "/s.jpg"
    moved = glob.glob(os.path.join(story_dir, "redo", "*", "images", "panel_01.png"))
    assert len(moved) == 1
    out = capsys.readouterr().out.splitlines()
    assert "stills: moved %s -> %s %s" % (p[1], moved[0], MOVE) in out
    assert "stills group 1/2 (no character LoRAs; panels 2,3): every still exists; skipped" in out
    assert [os.path.exists(p[k]) for k in (1, 2, 3, 4)] == [False, True, True, True]


# --- Review Focus 3: --redo on the Z-Image path ---------------------------------------------------------------

def test_sz_review_focus_3_a_redo_on_the_zimage_path(clean_env):
    tmp = clean_env["tmp"]
    sse._write_story(tmp)
    args = sse._parse("--shots", "--seed-image", sse._seed1920(tmp), "--seed-edit-model", "as-is", "--redo", "2")
    assert movie._resolve_shots(args) == 0 and args.redo_panels == [2]
    assert movie._resolve_seed_edit(args) == 0 and args.seed_edit is None
    args.seed_context = None
    assert [p.__name__ for p in movie._phase_sequence(args)] == [
        "phase0_seed", "phase1_story", "phase_release_story_server", "phase_redo_shots", "phase2_stills",
        "phase3_manifest", "phase4_render"]
    _stills(tmp)
    assert movie._shots_missing_stills(_z(tmp, redo_panels=[3]), [1, 2, 3]) == [1, 3]
    assert movie._shots_missing_stills(_z(tmp, redo_panels=[3]), [2, 3]) == [3]
    assert movie._shots_missing_stills(sse._phase_args(tmp, seed_image=None, seed_edit=None, redo_panels=[3]),
                                       [1, 2, 3]) == [3]
```

- [ ] **Step 2: Run the new tests; verify they fail.**

Run: `cd $S/sz-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_ltx_movie_shots_zimage.py 2>&1 | tail -1`
Expected: `13 failed` (every test: `_shots_zimage_seed` and the two constants do not exist yet, and `_resolve_shots` still refuses as-is).

- [ ] **Step 3: Edit the existing tests to the new texts (E13-E15).**

Edit `tests/test_shots_mode.py` (E13, S33): replace this text, which occurs exactly once:

```python
        (base + ["--shots", "--seed-image", str(seed)],
         "Error: --shots with --seed-image needs --seed-edit-model ID: every panel's still is a Qwen edit of "
         "the seed, so the seed cannot be used as-is"),
```

with:

```python
        (base + ["--shots", "--seed-image", str(seed)],
         "Error: --shots with --seed-image needs --seed-edit-model: a Qwen model ID makes every panel's still an "
         "edit of the seed; as-is keeps the seed as panel 1 and renders every other panel's still with Z-Image"),
```

Edit `tests/test_ltx_movie_shots_seed.py` (E13, `MODEL_RULE`): replace this text, which occurs exactly once:

```python
MODEL_RULE = ("Error: --shots with --seed-image needs --seed-edit-model ID: every panel's still is a Qwen edit of the "
              "seed, so the seed cannot be used as-is\n")
```

with:

```python
MODEL_RULE = ("Error: --shots with --seed-image needs --seed-edit-model: a Qwen model ID makes every panel's still "
              "an edit of the seed; as-is keeps the seed as panel 1 and renders every other panel's still with "
              "Z-Image\n")
```

Edit `tests/test_ltx_movie_shots_seed.py` (E13, SET1's as-is case is removed): replace this text, which occurs exactly once:

```python
    cases = [((), MODEL_RULE), (("--seed-edit-model", "as-is"), MODEL_RULE),
```

with:

```python
    cases = [((), MODEL_RULE),
```

Edit `tests/test_ltx_movie_shots_seed.py` (E13, SET1 accepts as-is): replace this text, which occurs exactly once:

```python
    args = _parse(*(shots + ["--seed-edit-model", "qwen21-q4"]))
    assert movie._resolve_shots(args) == 0 and args.redo_panels == []
```

with:

```python
    args = _parse(*(shots + ["--seed-edit-model", "qwen21-q4"]))
    assert movie._resolve_shots(args) == 0 and args.redo_panels == []
    assert movie._resolve_shots(_parse(*(shots + ["--seed-edit-model", "as-is"]))) == 0
```

Edit `tests/test_ltx_movie_shots_seed.py` (E14, `HELP["--seed-edit-model"]`): replace this text, which occurs exactly once:

```python
        "with content safety; as-is, like leaving the flag out, uses the seed unchanged. With --shots it is "
        "required and as-is is refused: every panel's still is an edit of the seed, each prompted by its own "
        "Image: text. See docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md and "
        "2026-11-05-compose-shots-seed-edit-design.md."),
```

with:

```python
        "with content safety; as-is, like leaving the flag out, uses the seed unchanged. With --shots it is "
        "required and chooses the stills engine: an ID makes every panel's still an edit of the seed, each prompted "
        "by its own Image: text; as-is keeps the seed as panel 1 and renders every other panel's still with Z-Image "
        "and its stills LoRAs, as --shots does without a seed. See "
        "docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md, 2026-11-05-compose-shots-seed-edit-design.md "
        "and 2026-11-11-shots-zimage-engine-design.md."),
```

Edit `tests/test_ltx_movie_shots_seed.py` (E14, `HELP["--shots"]`): replace this text, which occurs exactly once:

```python
        "every cast character LoRA defaults to 0.8. With --seed-image, every panel's still is instead a Qwen edit "
        "of the seed (--seed-edit-model ID, required). See docs/superpowers/specs/2026-10-06-shots-mode-design.md.")}
```

with:

```python
        "every cast character LoRA defaults to 0.8. With --seed-image, --seed-edit-model (required) chooses the "
        "stills engine: an ID makes every panel's still a Qwen edit of the seed; as-is keeps the seed as panel 1 and "
        "renders every other panel's still with Z-Image. See docs/superpowers/specs/2026-10-06-shots-mode-design.md.")}
```

Edit `tests/test_ltx_movie_seed_context.py` (E15, CXT1): replace this text, which occurs exactly once:

```python
            (["--shots", "--seed-image", seed],
             "Error: --shots with --seed-image needs --seed-edit-model ID: every panel's still is a Qwen edit of the "
             "seed, so the seed cannot be used as-is\n"),
            (["--shots", "--seed-image", seed, "--seed-edit-model", "as-is"],
             "Error: --shots with --seed-image needs --seed-edit-model ID: every panel's still is a Qwen edit of the "
             "seed, so the seed cannot be used as-is\n"),
```

with:

```python
            (["--shots", "--seed-image", seed],
             "Error: --shots with --seed-image needs --seed-edit-model: a Qwen model ID makes every panel's still an "
             "edit of the seed; as-is keeps the seed as panel 1 and renders every other panel's still with Z-Image\n"),
            (["--shots", "--seed-image", seed, "--seed-edit-model", "as-is"],
             "Error: --seed-context needs --seed-edit-model ID, a Qwen registry edit model (as-is is refused): every "
             "shots still is a Qwen edit of the seed\n"),
```

- [ ] **Step 4: Run the edited tests; verify they fail.**

Run: `cd $S/sz-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_shots_mode.py::test_s33_resolve_shots_errors tests/test_ltx_movie_shots_seed.py::test_set1_the_shots_seed_option_rules tests/test_ltx_movie_shots_seed.py::test_se4_se5_the_help_texts_and_the_docstring tests/test_ltx_movie_seed_context.py::test_cxt1_the_option_rules 2>&1 | tail -1`
Expected: `4 failed` (each now expects the new texts, which `bin/ltx-movie` does not print yet).

- [ ] **Step 5: Write the implementation in `bin/ltx-movie` (E1-E12).** Apply these Edits in order.

Edit `bin/ltx-movie` (E12, the docstring): replace this text, which occurs exactly once:

```python
passed to Phase 2 as its --seed-image. Absent, or as-is, the seed is used unchanged.
```

with:

```python
passed to Phase 2 as its --seed-image. Absent, or as-is, the seed is used unchanged. With --shots
(docs/superpowers/specs/2026-11-11-shots-zimage-engine-design.md) the flag is required: as-is keeps
the seed as panel 1 and renders every other panel's still with Z-Image and its stills LoRAs, as
--shots does without a seed.
```

Edit `bin/ltx-movie` (E1, the constants): replace this text, which occurs exactly once:

```python
SHOTS_SEED_LORA_NOTE = ("note: Z-Image stills LoRAs (character, location and catalog stills LoRAs) do not apply "
                        "to Qwen edits; every panel's still is edited without them")
```

with:

```python
SHOTS_SEED_LORA_NOTE = ("note: Z-Image stills LoRAs (character, location and catalog stills LoRAs) do not apply "
                        "to Qwen edits; every panel's still is edited without them")
# Shots Z-Image engine (docs/superpowers/specs/2026-11-11-shots-zimage-engine-design.md, ZE1): with --shots, --seed-image
# and --seed-edit-model as-is, panel 1 is the seed and every other panel is a Z-Image still, as shots mode without a seed.
SHOTS_ZIMAGE_MOVE_WHY = "(a Qwen edit of the seed; the Z-Image engine renders this panel again)"
SHOTS_ZIMAGE_PLAN_WARNING = ("Warning: %s was planned for the Qwen engine (plan.json records the seed image), so its "
                             "Image: lines leave out the cast descriptions that Z-Image draws from; rerun with "
                             "--force-story to plan the story for Z-Image")
```

Edit `bin/ltx-movie` (E10, the `--seed-edit-model` help): replace this text, which occurs exactly once:

```python
                              "flag out, uses the seed unchanged. With --shots it is required and as-is is refused: "
                              "every panel's still is an edit of the seed, each prompted by its own Image: text. See "
                              "docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md and "
                              "2026-11-05-compose-shots-seed-edit-design.md.")
```

with:

```python
                              "flag out, uses the seed unchanged. With --shots it is required and chooses the stills "
                              "engine: an ID makes every panel's still an edit of the seed, each prompted by its own "
                              "Image: text; as-is keeps the seed as panel 1 and renders every other panel's still "
                              "with Z-Image and its stills LoRAs, as --shots does without a seed. See "
                              "docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md, "
                              "2026-11-05-compose-shots-seed-edit-design.md and "
                              "2026-11-11-shots-zimage-engine-design.md.")
```

Edit `bin/ltx-movie` (E11, the `--shots` help): replace this text, which occurs exactly once:

```python
                              "cast character LoRA defaults to 0.8. With --seed-image, every "
                              "panel's still is instead a Qwen edit of the seed (--seed-edit-model "
                              "ID, required). See docs/superpowers/specs/"
```

with:

```python
                              "cast character LoRA defaults to 0.8. With --seed-image, "
                              "--seed-edit-model (required) chooses the stills engine: an ID makes "
                              "every panel's still a Qwen edit of the seed; as-is keeps the seed as "
                              "panel 1 and renders every other panel's still with Z-Image. See "
                              "docs/superpowers/specs/"
```

Edit `bin/ltx-movie` (E3, `_resolve_shots`): replace this text, which occurs exactly once:

```python
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
```

with:

```python
        # Shots seed edits SE2, amended by the shots Z-Image engine spec ZE2: an ID makes every panel's still a Qwen
        # edit of the seed; as-is keeps the seed as panel 1 and every other panel is a Z-Image still.
        if args.story_legacy or args.story_prompt_override is not None:
            print("Error: --shots with --seed-image needs the default story engine; it cannot be combined "
                  "with %s" % ("--story-legacy" if args.story_legacy else "--story-prompt-override"),
                  file=sys.stderr)
            return 2
        if args.seed_edit_model is None:
            print("Error: --shots with --seed-image needs --seed-edit-model: a Qwen model ID makes every panel's "
                  "still an edit of the seed; as-is keeps the seed as panel 1 and renders every other panel's still "
                  "with Z-Image", file=sys.stderr)
            return 2
        if args.seed_edit_model != "as-is" and getattr(args, "stills_lora_path_specs", None):
```

Edit `bin/ltx-movie` (E7, `_story_context`): replace this text, which occurs exactly once:

```python
        agent_image = getattr(args, "seed_downscaled_path", None)
    return engine.StoryContext(
        ws=WS, story_id=args.story_id, story_dir=paths["story_dir"], mode=_story_mode(args),
        panels=args.panels, seconds=_clip_seconds(args), narrative=args.narrative,
        goal=args.goal, members=list(getattr(args, "cast_members", None) or []),
        seed_image=os.path.abspath(args.seed_image) if seeded else None,
```

with:

```python
        agent_image = getattr(args, "seed_downscaled_path", None)
    # Shots Z-Image engine ZE3: Z-Image never sees the seed, so its Image: lines keep every cast description.
    return engine.StoryContext(
        ws=WS, story_id=args.story_id, story_dir=paths["story_dir"], mode=_story_mode(args),
        panels=args.panels, seconds=_clip_seconds(args), narrative=args.narrative,
        goal=args.goal, members=list(getattr(args, "cast_members", None) or []),
        seed_image=os.path.abspath(args.seed_image) if seeded and not _shots_zimage_seed(args) else None,
```

Edit `bin/ltx-movie` (E4, `phase2_stills`): replace this text, which occurs exactly once:

```python
    print("=== Phase 2: stills ===")
    if getattr(args, "shots", False) and getattr(args, "seed_image", None):
```

with:

```python
    print("=== Phase 2: stills ===")
    # Shots Z-Image engine ZE4: with --seed-edit-model as-is the shots branch below runs, panel 1 being the seed.
    if getattr(args, "shots", False) and getattr(args, "seed_image", None) and not _shots_zimage_seed(args):
```

Edit `bin/ltx-movie` (E2 and E5, the three new functions and `_shots_missing_stills`): replace this text, which occurs exactly once:

```python
def _shots_missing_stills(args, panels):
    """The panels of one group whose still must be generated: those being redone, and those
    with no images/panel_NN.png."""
    images_dir = _story_paths(args.story_id)["images_dir"]
    redo = set(getattr(args, "redo_panels", None) or [])
    return [i for i in panels if i in redo
            or not os.path.exists(os.path.join(images_dir, "panel_%02d.png" % i))]
```

with:

```python
def _shots_zimage_seed(args):
    """True on the shots Z-Image seed path (shots Z-Image engine spec ZE1): --shots, --seed-image and --seed-edit-model
    as-is. Panel 1 is then the seed and every other panel a Z-Image still, as in shots mode without a seed."""
    return bool(getattr(args, "shots", False) and getattr(args, "seed_image", None)
                and getattr(args, "seed_edit_model", None) == "as-is")


def _shots_qwen_stills(args):
    """{n: path} of every images/panel_NN.png that seed_edits.json or seed_context_edits.json records as an ok Qwen
    edit with the same sha256 (shots Z-Image engine spec ZE6). Reads; never writes."""
    paths = _story_paths(args.story_id)
    found = {}
    for record, schema in ((_shots_seed_paths(paths["story_dir"])["record"], SHOTS_SEED_EDITS_SCHEMA),
                           (_seed_context_paths(paths["story_dir"])["record"], SEED_CONTEXT_SCHEMA)):
        for n, entry in _shots_seed_entries(record, schema).items():
            still = os.path.join(paths["images_dir"], "panel_%02d.png" % n)
            if (entry.get("status") == "ok" and os.path.isfile(still)
                    and entry.get("still_sha256") == _sha256_file(still)):
                found[n] = still
    return found


def _shots_zimage_prepare(args, dry_run=False):
    """Phase 2's first step on the shots Z-Image seed path (shots Z-Image engine spec ZE6, ZE7): the warning when
    plan.json was planned for the Qwen engine, then every recorded Qwen still moved aside into
    <story>/redo/<stamp>-<pid>/images/. With dry_run it prints the moves and moves nothing."""
    paths = _story_paths(args.story_id)
    try:
        with open(os.path.join(paths["story_dir"], "plan.json"), encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, ValueError):
        plan = None
    if (isinstance(plan, dict) and isinstance(plan.get("seed_image"), str) and plan["seed_image"]
            and not (dry_run and getattr(args, "force_story", False))):
        print(SHOTS_ZIMAGE_PLAN_WARNING % paths["story_md"])
    stale = _shots_qwen_stills(args)
    archive = os.path.join(paths["story_dir"], "redo", "<UTC stamp>-<pid>" if dry_run else "%s-%d" % (
        time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid()), "images")
    for n in sorted(stale):
        moved = os.path.join(archive, os.path.basename(stale[n]))
        if dry_run:
            print("Would move %s -> %s %s" % (stale[n], moved, SHOTS_ZIMAGE_MOVE_WHY))
            continue
        os.makedirs(archive, exist_ok=True)
        os.replace(stale[n], moved)
        print("stills: moved %s -> %s %s" % (stale[n], moved, SHOTS_ZIMAGE_MOVE_WHY))


def _shots_missing_stills(args, panels):
    """The panels of one group whose still must be generated: those being redone, and those
    with no images/panel_NN.png. On the shots Z-Image seed path (shots Z-Image engine spec ZE6)
    also panel 1, which bin/ltx-story-images writes again from the seed, and every panel whose
    still is a recorded Qwen edit."""
    images_dir = _story_paths(args.story_id)["images_dir"]
    redo = set(getattr(args, "redo_panels", None) or [])
    zimage = _shots_zimage_seed(args)
    qwen = _shots_qwen_stills(args) if zimage else {}
    return [i for i in panels if i in redo or i in qwen or (zimage and i == 1)
            or not os.path.exists(os.path.join(images_dir, "panel_%02d.png" % i))]
```

Edit `bin/ltx-movie` (E6, `_phase2_shots`): replace this text, which occurs exactly once:

```python
    paths = _story_paths(args.story_id)
    groups = _exclude_groups(_shots_stills_groups(paths["story_md"], getattr(args, "cast_members", None) or [],
```

with:

```python
    paths = _story_paths(args.story_id)
    if _shots_zimage_seed(args):
        _shots_zimage_prepare(args)        # shots Z-Image engine ZE6: the plan warning; Qwen stills moved aside
    groups = _exclude_groups(_shots_stills_groups(paths["story_md"], getattr(args, "cast_members", None) or [],
```

Edit `bin/ltx-movie` (E8, the dry run's Phase 0 sentence): replace this text, which occurs exactly once:

```python
                 "Phase 2 edits the ORIGINAL into every panel's still with the Qwen edit model; nothing is cropped."
                 if getattr(args, "shots", False) else
                 "Phase 2 fits the ORIGINAL into panel_01.png at twice the video size; nothing is cropped."))
```

with:

```python
                 "Phase 2 fits the ORIGINAL into panel_01.png at twice the video size and renders every other "
                 "panel's still with Z-Image; nothing is cropped." if _shots_zimage_seed(args) else
                 "Phase 2 edits the ORIGINAL into every panel's still with the Qwen edit model; nothing is cropped."
                 if getattr(args, "shots", False) else
                 "Phase 2 fits the ORIGINAL into panel_01.png at twice the video size; nothing is cropped."))
```

Edit `bin/ltx-movie` (E9, the dry run's Qwen Phase 2 block): replace this text, which occurs exactly once:

```python
    if getattr(args, "shots", False) and getattr(args, "seed_image", None):
        print("--- Phase 2: stills ---")
```

with:

```python
    if getattr(args, "shots", False) and getattr(args, "seed_image", None) and not _shots_zimage_seed(args):
        print("--- Phase 2: stills ---")
```

Edit `bin/ltx-movie` (E9, the dry run's shots stills plan): replace this text, which occurs exactly once:

```python
        elif getattr(args, "shots", False):
            _print_shots_stills_plan(args, phase2_cmd)
```

with:

```python
        elif getattr(args, "shots", False):
            if _shots_zimage_seed(args):
                _shots_zimage_prepare(args, dry_run=True)   # shots Z-Image engine ZE9
            _print_shots_stills_plan(args, phase2_cmd)
```

- [ ] **Step 6: Run the tests (spec Plan, Task 1, item 2) and the compile check; verify they pass.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/sz-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_ltx_movie_shots_zimage.py 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider tests/test_ltx_movie_shots_zimage.py tests/test_ltx_movie_shots_seed.py tests/test_ltx_movie_seed_context.py tests/test_ltx_movie_seed_context_frame.py tests/test_ltx_movie_cast_refs.py tests/test_shots_mode.py tests/test_seeded_no_identity.py tests/test_story_engine.py -k "sz or set or cxt or crt or s33 or sit or rst50" 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider tests/test_ltx_movie_shots_seed.py tests/test_ltx_movie_seed_context.py tests/test_ltx_movie_seed_context_frame.py tests/test_ltx_movie_cast_refs.py tests/test_seeded_no_identity.py tests/test_movie_ui_builder.py 2>&1 | tail -1
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1
grep -c $'^import re$' bin/ltx-movie
git diff -- bin/ltx-movie | grep -E '^\+(import|from) ' || echo "no import added to bin/ltx-movie"
```

Expected, in order: `13 passed`; `1 failed, 79 passed, 178 deselected`, the one failure being `tests/test_story_engine.py::test_rst62_import_sets`, a baseline failure that the spec's `-k` expression also selects (SC5); `1 failed, 74 passed`, the failure being `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` (expected until Task 3); `OK 347/347` (the first line of `$S/sz-baseline/baseline-ok-lines.txt`); `0` (no top-level `import re`, L7j); `no import added to bin/ltx-movie`.

Run the compile check with `FILES` = `bin/ltx-movie tests/test_ltx_movie_shots_zimage.py tests/test_shots_mode.py tests/test_ltx_movie_shots_seed.py tests/test_ltx_movie_seed_context.py`. Expected: `compiled 5` twice.

- [ ] **Step 7: The gate.** Run `zsh $S/sz-baseline/gate-run.sh 1` (with `S` as above). Expected: `disk ok`; `GATE PASS`; `lost 1 (listed 1, unexpected 0); new tests 13, not passing 0; baseline failures still failing 2 of 2` (the listed loss is `test_mut26`; the 13 new tests are SZ1-SZ10 and Review Focus 1-3; an extra listed loss can only be an R7 flake, cleared by the next line); `3 passed`; `ATK2 OK lines unchanged`.

- [ ] **Step 8: Commit.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/sz-wt/qwen-agent-workspace
git add bin/ltx-movie tests/test_ltx_movie_shots_zimage.py tests/test_ltx_movie_shots_seed.py tests/test_ltx_movie_seed_context.py tests/test_shots_mode.py
git diff --cached --name-only    # expected: exactly those five paths, each with the qwen-agent-workspace/ prefix
git commit -m "bin/ltx-movie: --shots --seed-image --seed-edit-model as-is keeps the seed as panel 1 and renders every other still with Z-Image (shots-zimage ZE1-ZE10)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The Compose engine picker and V1 rule 8 (U1-U11; SZ11-SZ16, Review Focus 4-5)

This task implements, in the movie-ui (ZE11-ZE14):
- U1: V1 rule 8 in `movie_ui_lib.py`: a missing engine (`seed_edit_model` `None`) is refused with a new text; as-is passes, with stills LoRAs too.
- U2: the `Stills engine` select `c-engine` and its note `c-engine-note` after the Mode select in `static/movie-ui/index.html`.
- U3-U7 in `static/movie-ui/app.js`: `S.composeEngine` (`"qwen"` default, reset by `composeSeedDefault`, restored by `fillCompose`); `ZIMAGE_SEED_NOTE`, `composeEngines`, `composeEngineUpdate`; `composeFields` sends `seed_edit_model: "as-is"`, `seed_edit_loras: null` for a seeded shots movie on Z-Image; `updateComposeButtons` hides the `c-sq` box and its probe reason on Z-Image; the select's `change` listener.
- U8-U10 (test texts) and U11 (the new test file).

`build_argv`, `job_phases`, `FIELD_FLAGS`, `DEFAULT_FIELDS`, `movie_ui_server.py`, `movie_ui_batch.py`, the `c-sq` markup and `qwenPicker` are unchanged: as-is already reaches the argv as `--seed-edit-model as-is`, skips the 409 probe and gives no phase `1c`.

**Files:**
- Modify: `movie_ui_lib.py` (V1 rule 8 `:1565-1574`), `static/movie-ui/index.html` (after the Mode select `:101-105`), `static/movie-ui/app.js` (`S` `:25`; `composeSeedDefault` `:423-427`; `composeFields` `:436`, `:461-464`; `updateComposeButtons` `:546-563`; `fillCompose` `:844`; `setupCompose` `:886`); all located by text below.
- Modify: `tests/test_movie_ui_checks.py` (MUT4 `:76-78`), `tests/test_movie_ui_seedfolder.py` (SDT17 `:560-561`), `tests/test_movie_ui_shots_seed.py` (`NEEDS_MODEL` `:33-34`, SET16 `:65-66`, SET20 `:227`).
- Create: `tests/test_movie_ui_shots_zimage.py`.

**Interfaces:**
- Consumes (from Task 1, the CLI only): `bin/ltx-movie --shots --seed-image S --seed-edit-model as-is` is accepted (stills LoRAs too); with no `--seed-edit-model` it is refused. Existing, unchanged: `lib.validate_fields(fields, ws, state) -> [str]`, `lib.build_argv(fields, ws_real, state)`, `lib.job_phases(kind, fields)`, `qwen_edit_flags`; on the page `$`, `S`, `show`, `composeSeedEditActive()`, `COMPOSE_PICKER` (`select`, `selection`, `update`, `reason`, `state`), `preview()`, `updateComposeButtons()`.
- Produces: the V1 text `"a seed image in shots mode needs a stills engine: a Qwen edit model (every panel's still is an edit of the seed) or as-is (panel 1 is the seed and Z-Image renders every other panel)"`; on the page `S.composeEngine` (`"qwen"` or `"zimage"`), `ZIMAGE_SEED_NOTE` (string), `composeEngines(mode, seeded) -> [[value, label], …]` (values `none`, `zimage`, `seed`, `qwen`; default first), `composeEngineUpdate(mode) -> value` (fills `#c-engine`, sets its value and `disabled`, and `#c-engine-note`'s text), the elements `#c-engine` and `#c-engine-note`.

- [ ] **Step 1: Write the failing tests.**

Create `tests/test_movie_ui_shots_zimage.py` with the Write tool, exactly:

```python
"""Tests for the shots Z-Image engine, movie-ui side (docs/superpowers/specs/2026-11-11-shots-zimage-engine-design.md,
SZ11-SZ16): with --shots, --seed-image and --seed-edit-model as-is, panel 1 is the seed and every other panel a
Z-Image still.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_shots_zimage.py

No test loads a model, renders, dispatches a job or contacts a server other than the in-test 127.0.0.1 one; the
page tests evaluate app.js functions with node when it is installed. Stdlib and pytest.
"""

import json
import os
import re
import shutil
import subprocess

import pytest

import movie_ui_testutil as mt
import movie_ui_lib as lib
import test_movie_ui_shots_seed as uss
from test_movie_ui_shots_seed import v1_env  # noqa: F401
from test_movie_ui_qwen_edit import _compose, _function, _job, _upload, env  # noqa: F401

NEEDS_CHOICE = ("a seed image in shots mode needs a stills engine: a Qwen edit model (every panel's still is an edit "
                "of the seed) or as-is (panel 1 is the seed and Z-Image renders every other panel)")
SHOTS = dict(seed_upload=uss.UP, mode="shots")
STILLS = [{"id": None, "path": "/a.safetensors", "strength": 1, "kind": None}]
STATIC = os.path.join(mt.WS, "static", "movie-ui")
ENGINE_HTML = ('      <option value="no_stills" data-field="no_stills">no stills</option>\n    </select></label>\n'
               '    <label>Stills engine <select id="c-engine"></select></label> '
               '<span id="c-engine-note" class="muted"></span>\n')
BUTTONS_ENGINE = ('    show($("#c-check-seams-box"), mode === "chained");\n'
                  '    const engine = composeEngineUpdate(mode);\n'
                  '    COMPOSE_PICKER.update();\n')
BUTTONS_BOX = ('    const zimageSeed = shotsSeed && engine === "zimage";\n'
               '    show($("#c-sq-qwen-box"), seedEditOn && !zimageSeed);\n'
               '    const seedEditReason = seedEditOn && !zimageSeed ? COMPOSE_PICKER.reason() : "";\n')
FIELDS_AS_IS = ('    if (seedEdit && out.mode === "shots" && S.composeEngine === "zimage") {\n'
                '      out.seed_edit_model = "as-is";\n'
                '      out.seed_edit_loras = null;\n'
                '    }\n'
                '    return out;\n')
DEFAULT_RESET = '    S.composeEngine = "qwen";\n    S.seedOrigin = origin;\n'
FILL_LINE = ('    S.composeEngine = f.mode === "shots" && f.seed_upload && f.seed_edit_model === "as-is" ? "zimage" : '
             '"qwen";\n')
LISTEN_LINE = '    $("#c-engine").addEventListener("change", function () { S.composeEngine = $("#c-engine").value; });\n'
CHAINED = ('    if (mode === "chained") {\n'
           '      return [seeded ? ["seed", "The seed: panel 1 is the seed, as-is or a Qwen edit (below)"]\n')
VALUES = "].map(function (c) { return composeEngines(c[0], c[1]).map(function (o) { return o[0]; }); })));"
FAKE_DOM = (
    'function makeSelect() {\n'
    '  const s = {options: [], value: "", disabled: false};\n'
    '  Object.defineProperty(s, "textContent", {set: function () { s.options = []; }, get: function () { return ""; }});\n'
    '  s.appendChild = function (o) { s.options.push(o); };\n'
    '  return s;\n'
    '}\n'
    'const E = {"#c-res-seed": {checked: false}, "#c-res-folder": {checked: false}, "#c-engine": makeSelect(),\n'
    '  "#c-engine-note": {textContent: ""}};\n'
    'function $(selector) { return E[selector]; }\n'
    'const document = {createElement: function () { return {value: "", textContent: ""}; }};\n'
    'const S = {seedUpload: null, composeEngine: "qwen"};\n'
    'function run(mode, seedRadio, upload, folder, engine) {\n'
    '  E["#c-res-seed"].checked = seedRadio;\n'
    '  S.seedUpload = upload;\n'
    '  E["#c-res-folder"].checked = folder;\n'
    '  S.composeEngine = engine;\n'
    '  const value = composeEngineUpdate(mode);\n'
    '  const select = E["#c-engine"];\n'
    '  return [value, select.disabled, select.options.map(function (o) { return o.value; }),\n'
    '    E["#c-engine-note"].textContent === ZIMAGE_SEED_NOTE];\n'
    '}\n')


def _page():
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(STATIC, "app.js"), encoding="utf-8") as f:
        js = f.read()
    return html, js


def _node(script):
    """node -e script's stdout parsed as JSON (60 s); asserts a zero exit."""
    proc = subprocess.run([shutil.which("node"), "-e", script], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# --- SZ11 (ZE11): V1 rule 8 ---------------------------------------------------------------------------------

def test_sz11_v1_rule_8(v1_env):
    assert uss._errors(v1_env, seed_edit_model="as-is", **SHOTS) == []
    assert uss._errors(v1_env, seed_edit_model="as-is", stills_loras=STILLS, **SHOTS) == []
    assert uss._errors(v1_env, seed_edit_model=None, **SHOTS) == [NEEDS_CHOICE]
    assert uss._errors(v1_env, seed_edit_model="as-is", story_legacy=True, **SHOTS) == [uss.NEEDS_ENGINE]
    assert uss._errors(v1_env, seed_edit_model="qwen21-q4", stills_loras=STILLS, **SHOTS) == [uss.NO_STILLS_LORAS]
    assert uss._errors(v1_env, seed_edit_model="as-is", seed_edit_loras=uss.UNC, **SHOTS) == [
        "seed edit LoRAs need a seed edit model other than as-is"]


# --- SZ12 (ZE11): the argv and the phases are unchanged code -------------------------------------------------

def test_sz12_argv_and_phases(v1_env):
    state = v1_env["state"]
    f = mt.fields(mt.WS, action="movie", seed_edit_model="as-is", **SHOTS)
    argv = lib.build_argv(f, mt.WS, state)
    i = argv.index("--seed-image")
    assert argv[i:i + 4] == ["--seed-image", os.path.join(state, "uploads", uss.UP), "--seed-edit-model", "as-is"]
    assert "--seed-edit-lora" not in argv
    assert argv.count("--shots") == 1
    assert lib.job_phases("movie", f) == ["0", "1", "1b", "2", "3", "4"]


# --- SZ13 (ZE11): a job and a seed folder on the Z-Image engine ---------------------------------------------

def test_sz13_jobs_and_seed_folders(env):
    s, ws, state, probes = env["srv"], env["ws"], env["state"], env["probes"]
    up = _upload(s)
    status, _h, payload = mt.api(s, "POST", "/api/jobs",
                                 body=_compose(ws, up, story_id="shots-z", mode="shots", seed_edit_model="as-is"))
    assert status == 201, payload
    argv = _job(state, payload)["argv"]
    assert "--shots" in argv and argv[argv.index("--seed-edit-model") + 1] == "as-is"
    assert probes["calls"] == []
    seeds = [{"name": "alpha.png", "upload_id": _upload(s, mt.PNG + b"a")},
             {"name": "beta.png", "upload_id": _upload(s, mt.PNG + b"b")}]
    folder = dict(mt.fields(ws, story_id="", action="movie", mode="shots", seed_edit_model="as-is"), seeds=seeds,
                  preview=False)
    jobs = len(lib.list_job_ids(state))
    status, _h, payload = mt.api(s, "POST", "/api/jobs/seed-folder", body=folder)
    assert status == 201, payload
    assert [r["status"] for r in payload["seeds"]] == ["ok", "ok"] and payload["queued"] == 2
    assert len(lib.list_job_ids(state)) == jobs + 2
    for row in payload["seeds"]:
        argv = lib.read_job(lib.job_dir(state, row["job"]["id"]))["argv"]
        assert "--shots" in argv and argv[argv.index("--seed-edit-model") + 1] == "as-is"
    status, _h, payload = mt.api(s, "POST", "/api/jobs/seed-folder", body=dict(folder, seed_edit_model=None))
    assert status == 409, payload
    assert [(r["status"], r["reason"]) for r in payload["seeds"]] == [("refused", NEEDS_CHOICE)] * 2
    assert len(lib.list_job_ids(state)) == jobs + 2
    assert probes["calls"] == []


# --- SZ14 (ZE12-ZE14): the static page -------------------------------------------------------------------------

def test_sz14_the_page():
    html, js = _page()
    assert html.count(ENGINE_HTML) == 1
    for text in ("function composeEngines(mode, seeded) {", "function composeEngineUpdate(mode) {",
                 'seedOrigin: null, composeEngine: "qwen", '):
        assert js.count(text) == 1, text
    buttons = _function(js, "  function updateComposeButtons() {")
    assert BUTTONS_ENGINE in buttons and BUTTONS_BOX in buttons
    assert FIELDS_AS_IS in _function(js, "  function composeFields(action) {")
    assert DEFAULT_RESET in _function(js, "  function composeSeedDefault(origin) {")
    assert FILL_LINE in _function(js, "  function fillCompose(fields) {")
    assert LISTEN_LINE in _function(js, "  function setupCompose() {")
    for name, text in (("index.html", html), ("app.js", js)):
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\balert\(", r"\bconfirm\(", r"\bprompt\(",
                        r"\beval\(", r"new Function"):
            assert not re.search(pattern, text), (name, pattern)
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(STATIC, "app.js")], capture_output=True, text=True,
                              timeout=60)
        assert proc.returncode == 0, proc.stderr


# --- SZ15 (ZE12): the engines of each cell, evaluated ----------------------------------------------------------

def test_sz15_the_engine_cells():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    body = _function(_page()[1], "  function composeEngines(mode, seeded) {")
    script = body + ('console.log(JSON.stringify([["no_stills",false],["chained",false],["chained",true],'
                     '["shots",false],["shots",true]' + VALUES)
    assert _node(script) == [["none"], ["zimage"], ["seed"], ["zimage"], ["qwen", "zimage"]]


# --- SZ16 (ZE12, ZE13; Section 9 Q2): no Z-Image where a seed is edited outside shots mode --------------------

def test_sz16_no_zimage_where_a_seed_is_edited():
    js = _page()[1]
    body = _function(js, "  function composeEngines(mode, seeded) {")
    assert CHAINED in body
    assert body.count('"zimage"') == 3
    assert body.count('["zimage", "Z-Image: panel 1 is the seed') == 1
    assert body.index('return seeded ? [["qwen"') < body.index('["zimage", "Z-Image: panel 1 is the seed')
    assert 'out.mode === "shots" && S.composeEngine === "zimage"' in _function(js, "  function composeFields(action) {")
    assert ('f.mode === "shots" && f.seed_upload && f.seed_edit_model === "as-is"'
            in _function(js, "  function fillCompose(fields) {"))
    if shutil.which("node"):
        cells = _node(body + 'console.log(JSON.stringify([["chained",true],["no_stills",true],["shots",true]' + VALUES)
        assert cells == [["seed"], ["none"], ["qwen", "zimage"]]
        assert [c for c in cells if "zimage" in c and len(c) > 1] == [["qwen", "zimage"]]


# --- Review Focus 4: a redo job queued with the Z-Image engine ------------------------------------------------

def test_sz_review_focus_4_a_redo_job_on_the_zimage_engine(env):
    s, ws, state, probes = env["srv"], env["ws"], env["state"], env["probes"]
    up = _upload(s)
    sdir = os.path.join(ws, "generated", "stories", "shots-z-redo")
    os.makedirs(sdir)
    with open(os.path.join(sdir, "story.md"), "w", encoding="utf-8") as f:
        f.write("x")
    body = _compose(ws, up, story_id="shots-z-redo", action="redo", redo=[2], mode="shots", seed_edit_model="as-is")
    status, _h, payload = mt.api(s, "POST", "/api/jobs", body=body)
    assert status == 201, payload
    argv = _job(state, payload)["argv"]
    assert argv[argv.index("--redo") + 1] == "2" and argv[argv.index("--seed-edit-model") + 1] == "as-is"
    assert "--seed-edit-lora" not in argv and "--shots" in argv
    assert probes["calls"] == []
    assert lib.job_phases("movie", body) == ["0", "1", "1b", "redo", "2", "3", "4"]
    assert lib.job_phases("story", body) == ["0", "1"]


# --- Review Focus 5: the engine select follows the cell, whatever the remembered choice -----------------------

def test_sz_review_focus_5_the_engine_select_follows_the_cell():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    js = _page()[1]
    update = _function(js, "  function composeEngineUpdate(mode) {")
    start = js.index("  const ZIMAGE_SEED_NOTE = ")
    code = js[start:js.index(update) + len(update)]
    runs = [["shots", True, "u.png", False, "qwen"], ["shots", True, "u.png", False, "zimage"],
            ["chained", True, "u.png", False, "zimage"], ["shots", False, None, True, "zimage"],
            ["shots", True, None, False, "zimage"], ["no_stills", False, None, False, "zimage"],
            ["shots", True, "u.png", False, "zimage"]]
    script = FAKE_DOM + code + (
        "console.log(JSON.stringify(%s.map(function (r) { return run.apply(null, r); })));" % json.dumps(runs))
    assert _node(script) == [["qwen", False, ["qwen", "zimage"], False],
                             ["zimage", False, ["qwen", "zimage"], True],
                             ["seed", True, ["seed"], False],
                             ["zimage", False, ["qwen", "zimage"], True],
                             ["zimage", True, ["zimage"], False],
                             ["none", True, ["none"], False],
                             ["zimage", False, ["qwen", "zimage"], True]]
```

- [ ] **Step 2: Run the new tests; verify they fail.**

Run: `cd $S/sz-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_shots_zimage.py 2>&1 | tail -1`
Expected: `7 failed, 1 passed` (SZ12 pins argv and phases code that this plan does not change, so it passes already).

- [ ] **Step 3: Edit the existing tests to the new texts (U8-U10).**

Edit `tests/test_movie_ui_checks.py` (U8, MUT4): replace this text, which occurs exactly once:

```python
        ({"seed_upload": seed, "mode": "shots"},
         "a seed image in shots mode needs a Qwen edit model: every panel's still is an edit of the seed, so the "
         "seed cannot be used as-is"),
```

with:

```python
        ({"seed_upload": seed, "mode": "shots"},
         "a seed image in shots mode needs a stills engine: a Qwen edit model (every panel's still is an edit of the "
         "seed) or as-is (panel 1 is the seed and Z-Image renders every other panel)"),
```

Edit `tests/test_movie_ui_seedfolder.py` (U8, SDT17): replace this text, which occurs exactly once:

```python
            ("refused", "a seed image in shots mode needs a Qwen edit model: every panel's still is an edit of "
                        "the seed, so the seed cannot be used as-is")] * 2
```

with:

```python
            ("refused", "a seed image in shots mode needs a stills engine: a Qwen edit model (every panel's still "
                        "is an edit of the seed) or as-is (panel 1 is the seed and Z-Image renders every other "
                        "panel)")] * 2
```

Edit `tests/test_movie_ui_shots_seed.py` (U9, `NEEDS_MODEL`): replace this text, which occurs exactly once:

```python
NEEDS_MODEL = ("a seed image in shots mode needs a Qwen edit model: every panel's still is an edit of the seed, so "
               "the seed cannot be used as-is")
```

with:

```python
NEEDS_MODEL = ("a seed image in shots mode needs a stills engine: a Qwen edit model (every panel's still is an edit of "
               "the seed) or as-is (panel 1 is the seed and Z-Image renders every other panel)")
```

Edit `tests/test_movie_ui_shots_seed.py` (U9, SET16): replace this text, which occurs exactly once:

```python
    for model in (None, "as-is"):
        assert _errors(v1_env, seed_edit_model=model, **shots) == [NEEDS_MODEL], model
```

with:

```python
    for model in (None,):
        assert _errors(v1_env, seed_edit_model=model, **shots) == [NEEDS_MODEL], model
    assert _errors(v1_env, seed_edit_model="as-is", **shots) == []
```

Edit `tests/test_movie_ui_shots_seed.py` (U10, SET20): replace this text, which occurs exactly once:

```python
            'not offered.\n' + SE31 + '    show($("#c-sq-qwen-box"), seedEditOn);\n') in buttons
```

with:

```python
            'not offered.\n' + SE31 + '    const zimageSeed = shotsSeed && engine === "zimage";\n'
            '    show($("#c-sq-qwen-box"), seedEditOn && !zimageSeed);\n') in buttons
```

- [ ] **Step 4: Run the edited tests; verify they fail.**

Run: `cd $S/sz-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_checks.py tests/test_movie_ui_seedfolder.py::test_sdt17_shots_mode_refuses_every_seed tests/test_movie_ui_shots_seed.py 2>&1 | tail -1`
Expected: `5 failed, 17 passed` (the failures: MUT4, SDT17, SET16, SET18, SET20).

- [ ] **Step 5: Write the implementation (U1-U7).** Apply these Edits in order.

Edit `movie_ui_lib.py` (U1, the engine rule): replace this text, which occurs exactly once:

```python
        # Shots seed edits SE23: every panel's still is a Qwen edit of the seed.
        if fields.get("seed_edit_model") in (None, "as-is"):
            errors.append("a seed image in shots mode needs a Qwen edit model: every panel's still is an edit of "
                          "the seed, so the seed cannot be used as-is")
```

with:

```python
        # Shots seed edits SE23, amended by the shots Z-Image engine spec ZE11: as-is is the Z-Image engine.
        if fields.get("seed_edit_model") is None:
            errors.append("a seed image in shots mode needs a stills engine: a Qwen edit model (every panel's still "
                          "is an edit of the seed) or as-is (panel 1 is the seed and Z-Image renders every other "
                          "panel)")
```

Edit `movie_ui_lib.py` (U1, the stills-LoRA rule): replace this text, which occurs exactly once:

```python
        if isinstance(fields.get("stills_loras"), list) and fields["stills_loras"]:
            errors.append("stills LoRAs do not apply in shots mode with a seed image: every panel's still is a "
                          "Qwen edit of the seed")
```

with:

```python
        if (fields.get("seed_edit_model") != "as-is" and isinstance(fields.get("stills_loras"), list)
                and fields["stills_loras"]):
            errors.append("stills LoRAs do not apply in shots mode with a seed image: every panel's still is a "
                          "Qwen edit of the seed")
```

Edit `static/movie-ui/index.html` (U2): replace this text, which occurs exactly once:

```html
      <option value="no_stills" data-field="no_stills">no stills</option>
    </select></label>
```

with:

```html
      <option value="no_stills" data-field="no_stills">no stills</option>
    </select></label>
    <label>Stills engine <select id="c-engine"></select></label> <span id="c-engine-note" class="muted"></span>
```

Edit `static/movie-ui/app.js` (U3, the state): replace this text, which occurs exactly once:

```js
    characters: [], locations: [], location: null, locationPick: [], seedUpload: null, seedOrigin: null, composeAction: "story", story: null, character: null, action: null, selectedJob: null, logOffset: 0,
```

with:

```js
    characters: [], locations: [], location: null, locationPick: [], seedUpload: null, seedOrigin: null, composeEngine: "qwen", composeAction: "story", story: null, character: null, action: null, selectedJob: null, logOffset: 0,
```

Edit `static/movie-ui/app.js` (U3 and U4, `composeSeedDefault` and the two new functions): replace this text, which occurs exactly once:

```js
  function composeSeedDefault(origin) {
    S.seedOrigin = origin;
    if (origin === "seeds") { COMPOSE_PICKER.select("as-is", []); }
    else { COMPOSE_PICKER.select(null, null); }
  }
```

with:

```js
  function composeSeedDefault(origin) {
    S.composeEngine = "qwen";
    S.seedOrigin = origin;
    if (origin === "seeds") { COMPOSE_PICKER.select("as-is", []); }
    else { COMPOSE_PICKER.select(null, null); }
  }

  // Shots Z-Image engine spec ZE12: the stills engines of each Compose cell (mode x seed), the default first.
  const ZIMAGE_SEED_NOTE = "Panel 1 is the seed. Every other panel is a Z-Image still from its own Image: text, " +
    "with the stills LoRAs of the characters, the locations, the catalog pick and the stills LoRA rows.";
  function composeEngines(mode, seeded) {
    if (mode === "no_stills") { return [["none", "None: every clip is text-to-video"]]; }
    if (mode === "chained") {
      return [seeded ? ["seed", "The seed: panel 1 is the seed, as-is or a Qwen edit (below)"]
        : ["zimage", "Z-Image: panel 1's still from its Image: text"]];
    }
    return seeded ? [["qwen", "Qwen edit of the seed: every panel's still"],
      ["zimage", "Z-Image: panel 1 is the seed, every other panel from its Image: text"]]
      : [["zimage", "Z-Image: every panel's still from its Image: text"]];
  }

  function composeEngineUpdate(mode) {
    const seeded = ($("#c-res-seed").checked && Boolean(S.seedUpload)) || $("#c-res-folder").checked;
    const options = composeEngines(mode, seeded);
    const values = options.map(function (o) { return o[0]; });
    const select = $("#c-engine");
    if (Array.prototype.map.call(select.options, function (o) { return o.value; }).join(",") !== values.join(",")) {
      select.textContent = "";
      options.forEach(function (o) {
        const option = document.createElement("option");
        option.value = o[0];
        option.textContent = o[1];
        select.appendChild(option);
      });
    }
    const zimageSeed = mode === "shots" && seeded && S.composeEngine === "zimage";
    select.value = zimageSeed ? "zimage" : values[0];
    select.disabled = options.length === 1;
    $("#c-engine-note").textContent = zimageSeed ? ZIMAGE_SEED_NOTE : "";
    return select.value;
  }
```

Edit `static/movie-ui/app.js` (U5, `composeFields`'s object): replace this text, which occurs exactly once:

```js
    const seedEdit = composeSeedEditActive() ? COMPOSE_PICKER.selection() : null;
    return {
```

with:

```js
    const seedEdit = composeSeedEditActive() ? COMPOSE_PICKER.selection() : null;
    const out = {
```

Edit `static/movie-ui/app.js` (U5, `composeFields`'s end): replace this text, which occurs exactly once:

```js
      overwrite_movie: $("#c-overwrite").checked, redo: []
    };
  }
```

with:

```js
      overwrite_movie: $("#c-overwrite").checked, redo: []
    };
    // Shots Z-Image engine spec ZE13: a seeded shots movie's Z-Image engine is sent as the seed as-is.
    if (seedEdit && out.mode === "shots" && S.composeEngine === "zimage") {
      out.seed_edit_model = "as-is";
      out.seed_edit_loras = null;
    }
    return out;
  }
```

Edit `static/movie-ui/app.js` (U6, the engine select in `updateComposeButtons`): replace this text, which occurs exactly once:

```js
    show($("#c-check-seams-box"), mode === "chained");
    COMPOSE_PICKER.update();
```

with:

```js
    show($("#c-check-seams-box"), mode === "chained");
    const engine = composeEngineUpdate(mode);
    COMPOSE_PICKER.update();
```

Edit `static/movie-ui/app.js` (U6, the `c-sq` box and its reason): replace this text, which occurs exactly once:

```js
    show($("#c-sq-shots-note"), shotsSeed);
    show($("#c-sq-qwen-box"), seedEditOn);
    const seedEditReason = seedEditOn ? COMPOSE_PICKER.reason() : "";
```

with:

```js
    show($("#c-sq-shots-note"), shotsSeed);
    const zimageSeed = shotsSeed && engine === "zimage";
    show($("#c-sq-qwen-box"), seedEditOn && !zimageSeed);
    const seedEditReason = seedEditOn && !zimageSeed ? COMPOSE_PICKER.reason() : "";
```

Edit `static/movie-ui/app.js` (U3, `fillCompose`): replace this text, which occurs exactly once:

```js
    S.seedOrigin = "job";
```

with:

```js
    S.seedOrigin = "job";
    S.composeEngine = f.mode === "shots" && f.seed_upload && f.seed_edit_model === "as-is" ? "zimage" : "qwen";
```

Edit `static/movie-ui/app.js` (U7, the listener): replace this text, which occurs exactly once:

```js
    panel.addEventListener("change", function () { updateComposeButtons(); preview(); });
```

with:

```js
    panel.addEventListener("change", function () { updateComposeButtons(); preview(); });
    $("#c-engine").addEventListener("change", function () { S.composeEngine = $("#c-engine").value; });
```

(The `#c-engine` listener runs at the target, before the panel-wide `change` listener the event then bubbles to, which runs `updateComposeButtons(); preview();` with the new `S.composeEngine`.)

- [ ] **Step 6: Run the tests (spec Plan, Task 2, item 2), `node --check` and the compile check; verify they pass.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/sz-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider -rs tests/test_movie_ui_shots_zimage.py 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_shots_zimage.py tests/test_movie_ui_shots_seed.py tests/test_movie_ui_qwen_edit.py tests/test_movie_ui_checks.py tests/test_movie_ui_seedfolder.py tests/test_movie_ui_seams.py tests/test_movie_ui_batch.py 2>&1 | tail -1
node --check static/movie-ui/app.js && echo "app.js parses"
```

Expected, in order: `8 passed` (node is installed on this host; where it is not, SZ15 and Review Focus 5 skip and the line reads `6 passed, 2 skipped`, which is a stop-and-report here); `184 passed`; `app.js parses`.

Run the compile check with `FILES` = `movie_ui_lib.py tests/test_movie_ui_shots_zimage.py tests/test_movie_ui_checks.py tests/test_movie_ui_seedfolder.py tests/test_movie_ui_shots_seed.py`. Expected: `compiled 5` twice.

- [ ] **Step 7: The gate.** Run `zsh $S/sz-baseline/gate-run.sh 2`. Expected: `disk ok`; `GATE PASS`; `lost 1 (listed 1, unexpected 0); new tests 21, not passing 0; baseline failures still failing 2 of 2` (the listed loss is still `test_mut26`; the 21 new tests are Task 1's 13 plus SZ11-SZ16 and Review Focus 4-5); `3 passed`; `ATK2 OK lines unchanged`.

- [ ] **Step 8: Commit.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/sz-wt/qwen-agent-workspace
git add movie_ui_lib.py static/movie-ui/index.html static/movie-ui/app.js tests/test_movie_ui_shots_zimage.py tests/test_movie_ui_shots_seed.py tests/test_movie_ui_checks.py tests/test_movie_ui_seedfolder.py
git diff --cached --name-only    # expected: exactly those seven paths, each with the qwen-agent-workspace/ prefix
git commit -m "movie-ui: one Stills engine picker on every Compose cell; Z-Image for a seeded shots movie (shots-zimage ZE11-ZE14)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The `test_mut26` re-baseline, a test-only commit (spec Plan, Task 3; D7; SC4)

This task moves `test_mut26_pipeline_files_are_unchanged`'s `BASELINE` from `3d5e345f788b262cc51c6d961f0c1d9737e163fc` to Task 1's commit (the last commit touching a pinned file, `bin/ltx-movie`) and extends the comment's chain with `, then to <SHA> (shots-zimage).` Nothing else in the file changes, and the commit stages only that file. If a later review fix touches a pinned file, add a new test-only baseline commit the same way; never amend.

**Files:**
- Modify: `tests/test_movie_ui_builder.py` (`test_mut26`'s comment line `:291` and `BASELINE` `:293`; located by text below).

**Interfaces:**
- Consumes: Task 1's commit (`git log -1 --format=%H -- bin/ltx-movie`).
- Produces: nothing (test-only).

- [ ] **Step 1: Take the SHA and check the pinned files.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/sz-wt/qwen-agent-workspace
SHA=$(git log -1 --format=%H -- bin/ltx-movie); echo $SHA
git log -1 --format=%s $SHA                    # expected: bin/ltx-movie: --shots --seed-image --seed-edit-model as-is keeps ... (Task 1)
git diff --quiet $SHA HEAD -- bin/ltx-movie && echo "bin/ltx-movie unchanged since SHA"
git diff --quiet $SHA HEAD -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py && echo "pipeline files clean at SHA"
git diff --name-only e8d7f3a $SHA -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py
```

Expected: a 40-hex `SHA`; Task 1's subject; `bin/ltx-movie unchanged since SHA`; `pipeline files clean at SHA`; exactly one line, `qwen-agent-workspace/bin/ltx-movie`. Anything else: stop and report. (The 23 paths are `PIPELINE_FILES`, written out on both lines, R8.)

- [ ] **Step 2: Edit the comment (SC4: the end of the long line, not the whole line).** Type the 40 characters of `SHA` (Step 1) in place of the word `SHA`.

Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```text
then to 3d5e345f788b262cc51c6d961f0c1d9737e163fc (audio-only-quoted).
```

with:

```text
then to 3d5e345f788b262cc51c6d961f0c1d9737e163fc (audio-only-quoted), then to SHA (shots-zimage).
```

- [ ] **Step 3: Edit `BASELINE`.** Type `SHA` in place of the word `SHA`.

Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
    BASELINE = "3d5e345f788b262cc51c6d961f0c1d9737e163fc"
```

with:

```python
    BASELINE = "SHA"
```

- [ ] **Step 4: Verify.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/sz-wt/qwen-agent-workspace
SHA=$(git log -1 --format=%H -- bin/ltx-movie)
grep -c "    BASELINE = \"$SHA\"" tests/test_movie_ui_builder.py                                                                       # expected: 1
grep -c "then to 3d5e345f788b262cc51c6d961f0c1d9737e163fc (audio-only-quoted), then to $SHA (shots-zimage)\.$" tests/test_movie_ui_builder.py   # expected: 1
git diff --stat -- tests/test_movie_ui_builder.py | tail -1                                                                            # expected: 1 file changed, 2 insertions(+), 2 deletions(-)
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py -k mut26 2>&1 | tail -1                                      # expected: 1 passed, 11 deselected
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py 2>&1 | tail -1                                                 # expected: 12 passed
```

Expected: as the comments say (`1 passed, 11 deselected` and `12 passed` for the two pytest lines).

Then run `zsh $S/sz-baseline/gate-run.sh 3`. Expected: `disk ok`; `GATE PASS`; `lost 0 (listed 0, unexpected 0); new tests 21, not passing 0; baseline failures still failing 2 of 2` (SZK1 as SC2 reads it; a listed loss only if it is an R7 flake, cleared by the next line); `3 passed`; `ATK2 OK lines unchanged`; and `grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $S/sz-baseline/task-3-pytest.txt` prints `1`.

- [ ] **Step 5: Commit (test-only, one file).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/sz-wt/qwen-agent-workspace
git add tests/test_movie_ui_builder.py
git diff --cached --name-only    # expected: exactly qwen-agent-workspace/tests/test_movie_ui_builder.py
git commit -m "tests/test_movie_ui_builder.py: test_mut26 BASELINE moves to the shots-zimage commit" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Verification

The controller runs these after Task 3 (spec Plan "Verification"): the pass bar and the diff checks (V1, SZK1, SZK2), the Opus design review (V2); the live checks (V3, L1-L6) are the user's, on macstudio. Every rule of "Global Constraints" applies. A finding is fixed in a new commit on the owning task's files; if that commit touches `bin/ltx-movie`, a new Task 3-style test-only baseline commit follows; then V1 reruns.

- [ ] **V1: The pass bar and the diff (SZK1, SZK2; about 20 minutes).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/sz-baseline
cd $S/sz-wt/qwen-agent-workspace
df -g . | tail -1 | awk '{print ($4 >= 5) ? "disk ok: " $4 " GiB free" : "DISK LOW: " $4 " GiB free"}'
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/final-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt; tail -1 $D/final-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/final-pytest.txt $D/expected-failures.txt 3
python3 -B -m pytest -q -p no:cacheprovider tests/test_fleet_tracing.py::test_tr27_fanout_two_rounds_and_missing_reasons tests/test_fleet_tracing.py::test_trt45_query_endpoints_refuse_browsers_and_bad_queries tests/test_fleet_tracing.py::test_trt46_post_spans_validation_cap_and_store 2>&1 | tail -1
for f in tests/test_ltx_movie_offline.py tests/test_qwen_agent_image_oneshot.py tests/test_qwen_agent_danger_auto_approve.py tests/test_qwen_agent_context_budget.py tests/test_qwen_agent_session_memory.py; do echo "$f $(python3 -B $f 2>&1 | tail -1)"; done > $D/final-ok-lines.txt
diff $D/baseline-ok-lines.txt $D/final-ok-lines.txt && echo "ATK2 OK lines unchanged"
diff <(grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt | grep -v -e test_tr27_fanout -e test_trt45_query -e test_trt46_post | sort) <(grep -E '^(FAILED|ERROR)' $D/final-pytest.txt | grep -v -e test_tr27_fanout -e test_trt45_query -e test_trt46_post | sort) && echo "same failures, same messages"
git diff --name-only e8d7f3a HEAD -- . ':(exclude)docs' | sort
git diff --name-only e8d7f3a HEAD -- docs | sort
git diff --stat e8d7f3a HEAD -- story_engine.py bin/ltx-story-images bin/ltx-story-manifest bin/ltx-mlx-render qwen_edit.py movie_ui_server.py movie_ui_batch.py scripts/deploy tests/test_ltx_movie_offline.py tests/test_story_engine.py tests/test_qwen_edit.py | tail -1
git diff e8d7f3a HEAD -- bin/ltx-movie | grep -E '^\+(import|from) ' || echo "no import added to bin/ltx-movie"
git diff e8d7f3a HEAD -- bin/ltx-movie | grep -E '^\+' | grep -c 'no_stills'
git diff e8d7f3a HEAD -- tests/ | grep -E '^\+' | grep -nE "load_module\(|urllib|expanduser\(|zshenv|fleet\.env|macstudio|:8177|:8178" || echo "no forbidden pattern in the test diff"
git diff e8d7f3a HEAD | grep -E '^\+' | grep -nEi "(api[_-]?key|secret|token|passw(or)?d)[\"' ]*[:=][\"' ]*[A-Za-z0-9_\-]{12,}|hf_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY" || echo "secret scan: clean"
git ls-files -s bin/ltx-movie | cut -c1-6
git diff --numstat e8d7f3a HEAD -- bin/ltx-movie movie_ui_lib.py static/movie-ui/app.js static/movie-ui/index.html
```

Expected, in order:
- `disk ok`;
- the final summary is the baseline's with the pass count higher by exactly 21 (`2 failed, 2777 passed, 2 skipped` in the planning replay; a flake failing in either run shifts both counts by one, and the rerun line settles it);
- `lost 0 (listed 0, unexpected 0); new tests 21, not passing 0; baseline failures still failing 2 of 2` and `GATE PASS` (SZK1 as SC2 reads it; a listed loss of an R7 flake is allowed, and the next line must then be `3 passed`); `3 passed`;
- `ATK2 OK lines unchanged` (SZK1: `tests/test_ltx_movie_offline.py` prints the baseline's `OK n/n`); `same failures, same messages`;
- exactly these 13 lines (SZK2 as SC3 measures it): `qwen-agent-workspace/bin/ltx-movie`, `qwen-agent-workspace/movie_ui_lib.py`, `qwen-agent-workspace/static/movie-ui/app.js`, `qwen-agent-workspace/static/movie-ui/index.html`, `qwen-agent-workspace/tests/test_ltx_movie_seed_context.py`, `qwen-agent-workspace/tests/test_ltx_movie_shots_seed.py`, `qwen-agent-workspace/tests/test_ltx_movie_shots_zimage.py`, `qwen-agent-workspace/tests/test_movie_ui_builder.py`, `qwen-agent-workspace/tests/test_movie_ui_checks.py`, `qwen-agent-workspace/tests/test_movie_ui_seedfolder.py`, `qwen-agent-workspace/tests/test_movie_ui_shots_seed.py`, `qwen-agent-workspace/tests/test_movie_ui_shots_zimage.py`, `qwen-agent-workspace/tests/test_shots_mode.py`;
- exactly the spec and this plan: `qwen-agent-workspace/docs/superpowers/plans/2026-11-11-shots-zimage-engine.md`, `qwen-agent-workspace/docs/superpowers/specs/2026-11-11-shots-zimage-engine-design.md`;
- no output from the untouched-files `--stat` (spec 0.3);
- `no import added to bin/ltx-movie`; `0` (no `no_stills` in an added line of `bin/ltx-movie`); `no forbidden pattern in the test diff`; `secret scan: clean` (the controller rule; repeat it right before any push); `100755`; the four tab-separated lines `94 18 …/bin/ltx-movie`, `7 5 …/movie_ui_lib.py`, `50 4 …/static/movie-ui/app.js`, `1 0 …/static/movie-ui/index.html` (the code changes only where the plan says).

- [ ] **V2: The design review.** An Opus `design-reviewer` reviews `git diff 0f59f51..HEAD` against the spec, the load-bearing properties first: the Qwen path is byte-for-byte unchanged in behaviour for every ID (SZK6; SET1-SET15, CXT1, SZ5's and SZ6's Qwen controls); on the Z-Image path panel 1 is always written from the seed and no recorded Qwen still survives in `images/` (SZ5, SZ6, Review Focus 1-2); nothing is deleted, only moved into `redo/` (SZ6); the story keeps the identity sentences only on the Z-Image path (SZ8); a chained seed is never sent as Z-Image (SZ16, Review Focus 5); the E1-E12 and U1-U7 code typed exactly as the spec gives it; and the rulings SC1-SC5, R1-R8. A finding is fixed as described above.

- [ ] **V3: The live checks (spec Section 5), run by the user on macstudio; never by the agent.** The agent never connects to macstudio. The user checks out `shots-zimage` there first. Record each row as "not run (awaiting the user)" until the user pastes the figures back; then record each row's figures and pass or fail. Push and merge (a merge commit, never a squash) only on the user's go, after V1's secret scan.

| Row | Steps (user) | Record | Pass |
|---|---|---|---|
| L1 | Compose: upload a medium-shot photo of one person, mode shots, Stills engine `Z-Image`, panels 8, a narrative through at least three places, Run all | the preview command (`--seed-edit-model as-is`, no `--seed-edit-lora`); `images/panel_01.png` beside the seed; story.md `Image:` lines; per panel 2-8: same person as the seed? (yes/no) | SZK3, SZK4 |
| L2 | L1 with a trained library character picked and a seed showing that character | each `images/stills-group-KK.log` | SZK5; at least 6 of panels 2-8 show the character |
| L3 | L1's seed and narrative with the default engine (`Qwen edit of the seed`), a new story id | `seed_edits.json`, the `seed edits:` lines | SZK6 |
| L4 | rerun L3's story id with `Z-Image` | the `stills: moved … (a Qwen edit …)` lines and the plan.json warning; `images/` | every Qwen still moved aside (none left in `images/` from `seed_edits.json`); the warning printed once |
| L5 | the page, each cell C1-C11 of Section 1 | the engine select's options and enabled state per cell; the `c-sq` box under `Z-Image` vs `Qwen`; a Stills LoRA row accepted under `Z-Image`, refused (preview error) under `Qwen` | every cell as the table; Z-Image is selectable only in shots with a seed (upload or folder); no console error |
| L6 | chained mode with an uploaded seed, with and then without a picked character: open the Stills engine select, then Run all with the default Qwen model | the select's options; the preview command; `seed_edit.json` and Phase 1c in the log | the select shows only `The seed: …` (disabled) and no Z-Image; the command has `--seed-edit-model qwen21-q4`; Phase 1c runs as before |

---

## Self-review

### Spec coverage: requirements and edits → task

| Spec item | Task | Where (test) |
|---|---|---|
| ZE1 (E1, E2 predicate) | 1 | constants, `_shots_zimage_seed` (SZ2, SZ7) |
| ZE2 (E3) | 1 | `_resolve_shots` (SZ1, S33, SET1, CXT1) |
| ZE3 (E7) | 1 | `_story_context` (SZ8) |
| ZE4 (E4) | 1 | `phase2_stills` (SZ4) |
| ZE5, ZE8 (no edit) | 1 | `_phase_sequence`, `build_story_prompt`, Phases 3-4 unchanged (SZ3, Review Focus 3, SET2, SET3) |
| ZE6 (E2, E5, E6) | 1 | `_shots_qwen_stills`, `_shots_zimage_prepare`, `_shots_missing_stills`, `_phase2_shots` (SZ5, SZ6, Review Focus 1-3) |
| ZE7 (E2 warning) | 1 | `_shots_zimage_prepare` (SZ7, Review Focus 1) |
| ZE9 (E8, E9) | 1 | the dry run (SZ9) |
| ZE10 (E10-E12, E14) | 1 | helps, docstring (SZ10, SE4/SE5 test) |
| E13-E15 | 1 | Step 3 |
| E16 | 1 | Step 1 |
| ZE11 (U1) | 2 | V1 rule 8 (SZ11, SZ12, SZ13, MUT4, SDT17, SET16, SET18, Review Focus 4) |
| ZE12 (U2-U4) | 2 | `c-engine`, `S.composeEngine`, `composeEngines`, `composeEngineUpdate` (SZ14, SZ15, SZ16, Review Focus 5) |
| ZE13 (U5) | 2 | `composeFields` (SZ14, SZ16) |
| ZE14 (U6, U7) | 2 | `updateComposeButtons`, the listener (SZ14, SET20) |
| U8-U10 | 2 | Step 3 |
| U11 | 2 | Step 1 |
| D7, the BASELINE move | 3 | `test_mut26` (SC4, R8) |
| Plan "Before Task 1" | Before Task 1 | snapshot, baseline (SC1), gate files |
| SZK1, SZK2 | V1 | SC2, SC3 (and SC5 for Task 1's `-k` run) |
| SZK3-SZK6, L1-L6 | V3 | the user's |

### Spec tests → test

| ID | Test (file) | Task |
|---|---|---|
| SZ1 | `test_sz1_the_option_rules` (`tests/test_ltx_movie_shots_zimage.py`) | 1 |
| SZ2 | `test_sz2_the_path_predicate` | 1 |
| SZ3 | `test_sz3_the_phase_tuple` | 1 |
| SZ4 | `test_sz4_phase_2_runs_the_shots_branch` | 1 |
| SZ5 | `test_sz5_missing_stills` | 1 |
| SZ6 | `test_sz6_qwen_stills_move_aside_and_the_group_runs` | 1 |
| SZ7 | `test_sz7_the_plan_warning` | 1 |
| SZ8 | `test_sz8_the_story_keeps_the_identity_sentences` | 1 |
| SZ9 | `test_sz9_the_dry_run` | 1 |
| SZ10 | `test_sz10_help_and_docstring` | 1 |
| SZ11 | `test_sz11_v1_rule_8` (`tests/test_movie_ui_shots_zimage.py`) | 2 |
| SZ12 | `test_sz12_argv_and_phases` | 2 |
| SZ13 | `test_sz13_jobs_and_seed_folders` | 2 |
| SZ14 | `test_sz14_the_page` | 2 |
| SZ15 | `test_sz15_the_engine_cells` | 2 |
| SZ16 | `test_sz16_no_zimage_where_a_seed_is_edited` | 2 |
| Review Focus 1-3 | `test_sz_review_focus_1_…` … `_3_…` (`tests/test_ltx_movie_shots_zimage.py`) | 1 |
| Review Focus 4-5 | `test_sz_review_focus_4_…`, `_5_…` (`tests/test_movie_ui_shots_zimage.py`) | 2 |

### Type and name consistency check

- `_shots_zimage_seed(args)` returns a `bool` and reads `shots`, `seed_image`, `seed_edit_model` with `getattr` defaults; it is called by `_story_context`, `phase2_stills`, `_shots_missing_stills`, `_phase2_shots` and the dry run, and by SZ2 on `argparse.Namespace` objects with and without `seed_edit_model`. `sse._phase_args` namespaces have no `seed_edit_model` (so the Qwen controls are False); `_z` adds `seed_edit_model="as-is"` and `seed_edit=None`.
- `_shots_qwen_stills(args)` returns `{int: str}`; `_shots_missing_stills` tests membership (`i in qwen`), `_shots_zimage_prepare` iterates `sorted(stale)`. Records are read only through `_shots_seed_entries(path, schema)`, whose `{}` on a missing, unreadable or foreign record Review Focus 1 relies on.
- `_shots_zimage_prepare(args, dry_run=False)` returns `None` and prints: `SHOTS_ZIMAGE_PLAN_WARNING % paths["story_md"]`, `stills: moved <old> -> <new> SHOTS_ZIMAGE_MOVE_WHY`, or `Would move <old> -> <story>/redo/<UTC stamp>-<pid>/images/panel_NN.png SHOTS_ZIMAGE_MOVE_WHY`; the tests' `MOVE` and `PLAN_WARNING` are the constants' texts (SZ7 asserts the equality).
- The CLI refusal text is the same in E3, `NO_MODEL` (SZ1), S33 (without `\n`), `MODEL_RULE` and CXT1 (with `\n`). The V1 text is the same in U1, `NEEDS_CHOICE` (SZ11, SZ13), `NEEDS_MODEL` (SET16, SET18), MUT4 and SDT17.
- `S.composeEngine` holds `"qwen"` or `"zimage"`; it is written by the `S` initialiser, `composeSeedDefault`, `fillCompose` and the `#c-engine` listener, and read by `composeEngineUpdate` and `composeFields`, both only together with `mode === "shots"` and a seed. `composeEngineUpdate(mode)` returns the select's value, which `updateComposeButtons` keeps as `engine`.
- The fake DOM of Review Focus 5 provides exactly what `composeEngineUpdate` touches: `$("#c-res-seed").checked`, `$("#c-res-folder").checked`, `$("#c-engine")` (`options`, a `textContent` setter that clears them, `appendChild`, `value`, `disabled`), `$("#c-engine-note").textContent`, `document.createElement`, `S.seedUpload`, `S.composeEngine`.

## Execution handoff

Plan complete and saved to `qwen-agent-workspace/docs/superpowers/plans/2026-11-11-shots-zimage-engine.md`.

**How it was checked.**
- **Replay on a scratch clone, never on the worktree.** A script parsed every Create and Edit block of this plan, in order and step by step, and applied it to a `git clone` of the worktree at `0f59f51` under `$S/sz-replay` (scratch, outside `$S/sz-wt`, never pushed), checking that every old text occurs exactly once at its turn (37 Edits, 2 Creates); each task was committed locally in the clone, and Task 3 used the real SHA of the replayed Task 1 commit. The gate's `gate.py` and `expected-failures.txt` were extracted from this plan the same way. The worktree itself received only this plan file.
- **Executed in the replay.** Task 1: Step 2 `13 failed`; Step 4 `4 failed`; Step 6 `13 passed`, `1 failed, 79 passed, 178 deselected` (`test_rst62_import_sets`, SC5), `1 failed, 74 passed` (`test_mut26`), `OK 347/347`, `0`, `no import added to bin/ltx-movie`; `compiled 5` on Python 3.9.6 and 3.13. Task 2: Step 2 `7 failed, 1 passed`; Step 4 `5 failed, 17 passed`; Step 6 `8 passed`, `184 passed`, `app.js parses`; `compiled 5` twice. Task 3: Step 1 printed the SHA, Task 1's subject, both "unchanged/clean" lines and exactly `qwen-agent-workspace/bin/ltx-movie`; Step 4 printed `1`, `1`, `1 file changed, 2 insertions(+), 2 deletions(-)`, `1 passed, 11 deselected`, `12 passed`.
- **Mutation checks.** Each of these one-line reversions makes the new tests fail: recorded Qwen stills not counted as missing (1 failed), panel 1 not forced (4), `os.replace` turned into `os.remove` (2), E7 reverted (1), `_shots_zimage_prepare` not called (2), the `ok` status not checked (1), the page's Z-Image applied outside shots mode (1), `composeFields` sending as-is in any mode (2), V1 refusing as-is again (3).
- **The full gate, observed.** Baseline in a clean clone at `0f59f51`: `2 failed, 2756 passed, 2 skipped`, the two allowed failures, and the five `OK` lines above. After the replayed Task 3: `2 failed, 2777 passed, 2 skipped`; `lost 0 (listed 0, unexpected 0); new tests 21, not passing 0; baseline failures still failing 2 of 2`; `GATE PASS`; `ATK2 OK lines unchanged`; `same failures, same messages`; `test_mut26` PASSED. V1's diff checks on that replay: exactly the 13 paths, only the spec under `docs/` (the replay has no plan commit; the branch will also list this plan), no untouched-file output, `no import added to bin/ltx-movie`, `0`, `no forbidden pattern in the test diff`, `secret scan: clean`, `100755`, and the numstat `94 18`, `7 5`, `50 4`, `1 0`.
- **Not run.** Any model, render, download or network access; the gate-run.sh flake rerun line (the three R7 tests passed inside both full runs); the design review (V2); the live checks (V3) are the user's.

Please review the plan. Which execution approach would you prefer?
- **Subagent-driven.** A fresh Sonnet `code-executor` implements each task in `$S/sz-wt` on branch `shots-zimage`, and a fresh Opus reviewer checks it before the next one starts.
- **Native.** One session implements every task, then one fresh Opus reviewer checks the whole branch.

I recommend subagent-driven: Task 1 is a verbatim transcription into the one pinned file whose mistakes (a Qwen still kept, a still deleted instead of moved, the Qwen path changed) would cost a live run on macstudio to find, and a reviewer gate after it catches a slip before Task 2 exposes the path in Compose.
