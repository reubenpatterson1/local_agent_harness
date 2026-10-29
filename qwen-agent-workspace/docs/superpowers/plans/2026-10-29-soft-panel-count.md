# Soft Panel Count Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `--panels N` becomes a target. The story planner uses N to N+2 beats as the narrative needs, never fewer than the spoken lines need with one speaker per panel. After the plan, every use of the count follows the plan's beat count: panel loops, budgets, stills, manifest, render, `--redo`, `story_prompt.txt`, the movie UI and the re-check. The user is told why the count differs from the target (P20, and a `note:` on every `bin/ltx-movie` run).

**Architecture:**
- **Engine (`story_engine.py`, stdlib only, no new import).**
  - Range and plan prompt (Task 1): SPC1-SPC5 and SPC12 (b). `StoryContext` gains `panels_target` and, by Plan ruling SPR2, `length`. Adds `panel_range`, the speaker runs, the range count text, the arc rule for a range and the pre-flight beyond N+2.
  - P19 (Task 2): SPC12 (a), with the coordinator additions. SPR1: only the speaker's own exit counts. SPR2: the hint names `--length` when `--length` sized the movie.
  - The run (Task 3): SPC6-SPC9 and SPC11. Covers P1's range, `plan.json`/`story_checks.json`/run.json `panels_target`, the ctx swap after the plan, the budgets and P20. SPR3 keeps `lora_checks` right for a saved plan with no beats.
  - Reuse and re-check (Task 4): SPC10. SPR4 makes the re-check ignore a stale plan.
- **`bin/ltx-movie` (Task 5):** SPC13. Adds the resolver before Phase 1, the adoption, the `story_prompt.txt` rewrite and the note after Phase 1, and the dry-run `Panel count:` line, placed after the prompt (SPR5). `_story_context` passes `panels_target` and `length`.
- **movie UI and `bin/iterate-story` (Task 6):** SPC14-SPC16.
- **Tests:** one new file, `tests/test_soft_panel_count.py`, with 43 test functions. A separate test-only task re-baselines the existing tests (G6). Then `test_mut26` gets its own commit (G7).

**Tech Stack:**
- Python 3.13 (`python3` = `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`, pytest 8.3.4). Python 3.9.6 (`/usr/bin/python3`) is used for the compile check only. Standard library only.
- `tests/story_engine_testutil.py` (`set_story_env`, `make_ws`, `make_ctx`, `plan_json`, `panel_json`, `answer`, `script_agent`, `agent_log`, `kyra`, `ronin`, `catalog_entry`, `make_catalog`, `lora_file`) and the fake `bin/qwen-agent` it installs.
- `tests/movie_ui_testutil.py` (`set_home`, `make_stub_workspace`, `Running`, `api`, `fields`, `kill_everything`), for SPT26 only.
- JavaScript in `static/movie-ui/app.js` is checked with `node --check` when `node` is installed.

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-10-29-soft-panel-count-design.md`, committed at `182f361`, an ancestor of HEAD `9952d81`. The user approved the design (spec 0.0), and C16 is user-approved.
- The spec cites line numbers at `6f16063`, before the shot prompt format ([SF]) landed. This plan is written against `9952d81`, where [SF] is merged (`a33efcb`, `42f3364`, `9952d81`). Every Edit below finds its text by content. The drift is recorded in Plan ruling PR11.
- The spec is binding. This plan changes design only in two cases, each a numbered ruling in "Plan rulings": where the spec's code and its own tests cannot both hold, and the two coordinator-approved additions SPR1 and SPR2, parked from the [SF] work. Each ruling that changes spec text carries its amendment text.

## Global Constraints

From the spec, verbatim (section in brackets):

- [Status] "Every design choice is made here. Each choice the brief left open is marked **[spec choice]**, and Section 8.2 lists them for confirmation. The implementer makes no design decisions."
- [0.4 Not changed] "**Files:** `character_lib.py`, `bin/ltx-story-manifest`, `bin/ltx-story-images`, `bin/ltx-mlx-render`, `movie_ui_server.py`, `bin/judge-story`, `bin/judge-clips`, `bin/judge-stills`, and the legacy engine path of `bin/ltx-movie`."
- [0.4 Not changed] "**Schemas and budgets:** `PLAN_SCHEMA`, `CHECKS_SCHEMA` and `RUN_SCHEMA` (the strings stay `v1`; only fields are added), `PLAN_MAX_CALLS` and `PANEL_MAX_CALLS`."
- [0.4 Not changed] "**Prompt texts:** `LINE_SPEAKERS_SENTENCE`, `MODE_PARAGRAPHS`, `MODE_RULES` and the writer prompt templates."
- [0.4 Not changed] "**Critic:** its patch targets. The critic never adds or removes beats."
- [0.4 G6] "Existing tests and fixtures | The re-baselines of Section 4.2, in a separate test-only commit whose body explains each changed file ([SF] Section 4.2 rule)".
- [0.4 G7] "`tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` | `BASELINE` re-baselined in its own follow-up commit; the comment gains `, then to <sha> (soft panel count).`"
- [0.5] "**The extra is fixed.** `PANELS_EXTRA` is a constant (2). There is no CLI flag and no movie-UI field for it." "**The legacy engine keeps an exact count.** `--story-legacy` and `--story-prompt-override` are unchanged."
- [0.6 SPK2] "`/usr/bin/python3` (3.9) and `python3` both `py_compile` `story_engine.py`, `bin/ltx-movie`, `bin/iterate-story` and `movie_ui_lib.py`. None gains an import." (This plan checks it with `compile()`; see Plan ruling PR5.)
- [0.7] "**Must-haves:** SPC1-SPC16 and SPT1-SPT27." "**Explicitly not built:** a flag for the extra; a plan retry for a dropped exit; a pipeline-written exit beat; a planner-written reason field."
- [4.1] "**Module docstring.** It states that no test renders, reads the real HOME, or contacts a model server, a daemon or the Anthropic API."
- [4.2 Rule] "Every outcome change must be explained by a code below and updated in G6. The G6 commit body has one paragraph per file." "An unexplained failure is a defect in the code, not the test." "No test is deleted, and no assertion is weakened beyond the new behaviour."
- [6] PR note (required, in substance): "`--panels` is now a target. The story planner may use up to 2 more panels when the narrative needs them, and never fewer. Examples: an exit after the last line, a spoken line that cannot share a panel, or a change of speaker. The warning `plan: P20 panel count: ...` says when and why, and every later run of the story prints `note: story.md has N panels for a target of T (because ...)`. Stills, the manifest, the render, `--redo`, `story_prompt.txt` and the movie UI follow the story's real panel count. Existing stories re-check as before. `--story-legacy` keeps an exact count."
- [Coordinator additions, 2026-10-29] (a) P19 considers only an exit whose subject is the last line's speaker (Plan ruling SPR1). (b) With `--length`, the count hints never suggest `--panels` (Plan ruling SPR2).

Controller rules, verbatim. Every task's requirements include them:

- tests never use the real HOME, never render, never contact servers
- never touch port 8178
- never read, cat, grep or source ~/.zshenv or fleet.env
- never stage .DS_Store, .claude/, agent/__pycache__/, repo-root bin/, qwen-agent-workspace/bin/action-from-dir
- no git stash/reset/checkout of others' work
- commit trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
- Python run with -B
- executors make every tracked-file change with the Edit tool

House rules (from the prior plans; every task's requirements include them):

- **Where work happens.**
  - This Mac only. No ssh, scp, rsync, curl or HTTP to any other host, and never touch macstudio. Use no network. SPT26 starts a movie-ui server on `127.0.0.1` inside the test; nothing else listens.
  - Never start, stop or contact a model server (`:8177`, `:8178`). Never render, and never load a model.
- **The main checkout.** Never touch the main checkout `/Users/reubenpatterson/local_agent_harness`.
  - Every command runs in the worktree `$S/sp-wt`.
  - The only exceptions are the controller steps of "Before Task 1": the plan commit and `git worktree add`.
- **Python.**
  - Use the standard library only, in every Python file this plan touches.
  - Every new or changed file must run on Python 3.9.6 and 3.13. So use none of: the `match` statement, `X | Y` type expressions, the walrus operator, `str.removeprefix`, `zip(strict=)` and parenthesised context managers.
- **Editing.**
  - Executors make every change to a tracked file with the Edit tool. The one new file, `tests/test_soft_panel_count.py`, is created with the Write tool in Task 1 and edited with the Edit tool from then on.
  - Never use `rm`, `sed -i`, a redirect or a script to change a tracked file. Task 7 has no exception: its fixture updates are Edit steps too (Plan ruling PR10).
- **Git.**
  - Stage only the paths a task names, and check `git diff --cached --name-only` before every commit.
  - Every commit command passes the trailer as a second `-m`, or as the last line of a `-F` message file.
  - Push is a separate step that needs the user's approval. No task pushes.
- **Paths.**
  - `S` = `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`.
  - `WS` = `$S/sp-wt/qwen-agent-workspace`, and `D` = `$S/sp-baseline`.
  - The git root is `$S/sp-wt`, so `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix.
  - Run every command from `WS`. Shell variables do not persist between commands, so every block defines the variables it uses.
- **Code blocks** are copied byte for byte.
  - An Edit step's old text must occur exactly once in the file at that moment. If it does not, stop and report; do not adapt it.
  - Every Edit and Create below was replayed in order on a scratch `git archive 9952d81` export. Each old text occurred exactly once at its turn (see "Execution handoff").
- **The compile check** (Step 4 of each code task) is this command, with the task's Python files as `FILES`. Expected: two lines, `compiled N` for 3.9 and then for 3.13.

```bash
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' FILES; done
```

## Review Focus

The spec implies these five inputs, and no SPT row exercises them. They are the ones most likely to reach a real run first. Each is pinned by a test in its owning task.

1. **A narrative whose lines need one panel more than the target.** For example, three six-word lines at `--panels 1` need 2 panels. Before this plan, the pre-flight refused it with exit 2.
   - Expected: no exit 2. A 1-beat plan is rejected with `expected 2 to 3 beats, found 1`. The retry's 2-beat plan is accepted, and P20 names the lines reason.
   - Test: `test_review_focus_1_lines_that_need_one_more_panel_are_planned_not_refused` (Task 3).
2. **A stale `plan.json` beside a `story.md` with another panel count.** This happens when a later `--story-legacy` run, or a hand edit, changed `story.md` but left `plan.json`.
   - Expected: the re-check of `story.md` at `--panels 3` passes plan-free, as it does at `9952d81`.
   - The spec's SPC10 would adopt the plan's 4 and fail the 3-panel story. See Plan ruling SPR4.
   - Test: `test_review_focus_2_a_stale_plan_is_not_adopted_by_recheck` (Task 4).
3. **A `--no-stills` movie that gets an added panel.** Only chained (SPT8) and shots (SPT19, SPT24) are exercised.
   - Expected: 4 panel calls, a 4-panel `story.md`, and one P20.
   - Test: `test_review_focus_3_a_no_stills_movie_gets_its_added_panel` (Task 3).
4. **The dry run of an existing story with more panels than the target.**
   - Expected: Phase 3's `--target-seconds` is for the story's count, not the target's. Otherwise the printed manifest command is the one that would exit 2 (SPT18).
   - Test: the last block of `test_spt17_the_dry_run` (Task 5).
5. **The added panel's writer reply is unparseable once.** The re-ask budget is keyed by panel number, and panel 4 did not exist before the ctx swap.
   - Expected: panel 4 is asked twice, and the run exits 0.
   - Test: `test_review_focus_5_an_added_panel_can_be_re_asked` (Task 3).

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `story_engine.py` | Modify (Tasks 1-4) | Range helpers, the `StoryContext` fields, the plan prompt, the arc rule and the pre-flight (T1); P19's subject rule and hints (T2); P1's range, the doc fields, the ctx swap, the budgets and P20 (T3); plan reuse and the re-check (T4). |
| `bin/ltx-movie` | Modify (Task 5) | `--panels` help; `PANEL_COUNT_*`/`DRY_PANELS_*`; `_plan_panels`, `_resolve_story_panels`, `_write_story_prompt`; `_story_context` fields; `_phase1_robust` adoption; the dry-run `Panel count:` line; `main` calls the resolver. |
| `movie_ui_lib.py` | Modify (Task 6) | `PANELS_EXTRA`, `STORY_PANEL_RE`, `plan_panels`, `effective_panels`; rule 16 and the Phase 2 stills count. |
| `static/movie-ui/app.js`, `static/movie-ui/index.html` | Modify (Task 6) | The `storyFields` fallback, the Size note, and the "Panels (target)" input of Regenerate. |
| `bin/iterate-story` | Modify (Task 6) | `build_engine_cmd` regenerates with `panels_target`. |
| `tests/test_soft_panel_count.py` | Create (Task 1), append (Tasks 2-6) | SPT1-SPT27, SPR1-SPR3, Review Focus 1-5: 43 test functions. |
| Existing tests and fixtures of spec 4.2 | Modify (Task 7 only) | The G6 re-baseline, one test-only commit. |
| `tests/test_movie_ui_builder.py` | Modify (Task 8 only) | `test_mut26` `BASELINE` and comment (G7). |

**Task split.** Tasks 1-6 each add one layer that a reviewer can accept or reject on its own diff:
- Task 1 is what the planner reads, and the pre-flight in front of it.
- Task 2 is the P19 notice.
- Task 3 is the run that accepts a bigger plan and lives with it.
- Task 4 is the reuse of a saved bigger plan.
- Task 5 is `bin/ltx-movie`.
- Task 6 is the movie UI and `bin/iterate-story`.

Task 7 is the test-only re-baseline, and Task 8 is the whole-branch review, `test_mut26` and the gates.

## Between tasks: the existing suite (approach B, and why)

**The choice.** Feature tasks do **not** edit existing tests. Instead this plan states which existing tests are expected to fail after each task, and they are all fixed in Task 7, one test-only commit.

**Why not approach A** (each feature task updates the tests it breaks):
- The spec mandates the opposite. 0.4 G6 and 4.2 call for one separate test-only commit whose body explains every changed file.
- Several goldens are broken by more than one task. For example, `tests/test_shot_format.py` changes through RB7 (T1, T2) and RB10 (T2), and the `uncast_*.txt` fixtures through RB1, RB7 and RB9 (all T1). Approach A would scatter one golden's explanation across commits.

**The cost** is that the existing suite is knowingly red in the listed places between Task 1 and Task 7. The gate below keeps that from hiding a real regression.

**Precision.** The list below is the spec's 4.2 inventory, mapped to the task whose RB code first breaks each test, plus the tests this plan's own reading added (marked +).
- It was derived by reading and grep at `9952d81`, not by running the suite, which this plan's author was not permitted to do.
- After each task, the gate compares a full run with the baseline that the controller records at `9952d81` (Before Task 1, Step 4).
- **Every test that passed at the baseline and does not pass now must be on the list for this task or an earlier one.** Otherwise the executor stops; see the gate rule.
- A listed test that still passes is fine; it may break in a later task.

**Gate rule** (Step 4 of every code task):
1. Every `tests/test_soft_panel_count.py` test passes.
2. The two baseline failures fail with the same messages.
3. Every lost baseline pass is listed for a task at or before this one in `$D/expected-failures.txt`.
4. `tests/test_ltx_movie_offline.py` prints `OK 347/347`.

**When the gate prints `GATE STOP`:**
- The executor stops and reports the UNEXPECTED ids together with `python3 -B -m pytest -q -p no:cacheprovider --tb=short <ids>` output.
- The controller has an Opus reviewer rule on each id.
  - If an RB code of this or an earlier task explains its diff, the controller appends a line `T<N> <id> <codes> +gate` to `$D/expected-failures.txt`. That is the only way the list grows.
  - Otherwise it is a defect, and the controller writes the exact fix for the executor.
- The gate then reruns.

**The RB codes** are spec 4.2's RB1-RB9, plus RB10 for Plan ruling SPR1:

| Code | Cause | First task |
|---|---|---|
| RB1 | Plan prompt count text (SPC4): `EXACTLY N` becomes `N to N+2`, `index runs from 1 to the number of beats.`, and the `PANEL_COUNT_RULE` insertion | 1 |
| RB2 | Arc rule for targets 1 and 2 (SPC5) | 1 |
| RB6 | Pre-flight: no error at N+1 or N+2; new message text, including `--force-story` (SPC3) | 1 |
| RB7 | [SF] constants (SPC12): `SPEAKING_BEAT_SENTENCE`, `SPEAKER_RULE` and `SPEAKER_RULE_KEEP_CAST` (T1); `P19_NOTE`'s second argument (T2) | 1, 2 |
| RB9 | `LINES_RULE` and `LINES_PINNED_SENTENCE` text (SPC2), including `@@MIN_BEATS@@` in `LINES_RULE` | 1 |
| RB10 (+) | Plan ruling SPR1: an exit whose subject is not the last line's speaker no longer counts for P19 (`'Kyra says, "Go," and the ronin leaves the frame.'` gives `None`) | 2 |
| RB3 | P1 messages (SPC7) | 3 |
| RB4 | `plan.json` key order: `panels_target` after `panels` (SPC6) | 3 |
| RB5 | `story_checks.json` key order (SPC8) | 3 |
| RB8 | `--panels` help (SPC13 h); expected to break nothing (the offline L1 substring still holds) | 5 |
| G7 | `test_mut26` (any edit to a `PIPELINE_FILES` entry) | 1 (fixed in Task 8) |

The expected-failure list, written to `$D/expected-failures.txt` in "Before Task 1" Step 4. A line is `T<first task> <node id> <codes>`. A parametrised test matches by its id prefix.

```text
# soft panel count plan: existing tests expected to fail from the given task until Task 7 (Task 8 for mut26)
T1 tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged G7
T1 tests/test_story_engine.py::test_rst8_plan_prompt_matrix RB1,RB2
T1 tests/test_story_engine.py::test_rst9_narrative_is_inserted_verbatim RB1
T1 tests/test_story_engine.py::test_story_focus_2_a_one_panel_story RB2 +
T1 tests/test_narrative_fidelity.py::test_nf5_spoken_lines_problem RB6
T1 tests/test_narrative_fidelity.py::test_nf31_an_infeasible_line_set_exits_2_before_any_call RB6
T1 tests/test_narrative_fidelity.py::test_nf12_the_plan_prompt RB1,RB7,RB9
T1 tests/test_pinned_cast.py::test_pt1_plan_constants RB7,RB9
T1 tests/test_pinned_cast.py::test_pt2_fixed_cast_block_and_uncast_byte_identity RB1,RB7,RB9
T1 tests/test_pinned_cast.py::test_pt5_lines_sentence_variants RB9
T1 tests/test_dialogue.py::test_dlg12_plan_prompt_speaker_rule RB7
T1 tests/test_speaker_attribution.py::test_sat9_plan_prompt RB9
T1 tests/test_shot_format.py::test_sft1a_planner_constants RB7
T2 tests/test_shot_format.py::test_sft23_the_narratives_exit_after_its_last_line RB10 +
T2 tests/test_shot_format.py::test_sft24_when_p19_fires RB7
T2 tests/test_shot_format.py::test_sft25_p19_end_to_end RB7
T2 tests/test_narrative_fidelity.py::test_nf28_engine_the_2x145_failure RB7 +
T2 tests/test_narrative_fidelity.py::test_nf29_engine_the_1x241_failure RB7 +
T2 tests/test_narrative_fidelity.py::test_nf33_default_narration_with_the_fixed_plan RB7 +
T3 tests/test_story_engine.py::test_rst14_plan_checks RB3
T3 tests/test_story_engine.py::test_rst11_short_plan_is_fatal RB3
T3 tests/test_pinned_cast.py::test_review_focus_1_an_exhausted_plan_lists_every_fatal_problem RB3
T3 tests/test_story_engine.py::test_rst13_normalization RB4
T3 tests/test_story_engine.py::test_rst39_outputs_and_layout RB4,RB5
```

The spec's 4.2 also names failures that depend on how a test is written: `tests/test_speaker_attribution.py` prompt tests (whole bytes only) and the `tests/test_ltx_movie_offline.py` L1 help (byte-exact only). The gate rule decides them.

**Must stay green in every task** (spec 4.2 "Must not change" and 4.3):
- the files `tests/test_ltx_story_manifest_chain.py`, `tests/test_ltx_mlx_render.py`, `tests/test_ltx_story_images.py`, `tests/test_character_lib.py`, `tests/test_casting_regression.py`, `tests/test_judge_story.py`, `tests/test_judge_clips.py`, `tests/test_lora_catalog.py`, `tests/test_iterate_story.py`, `tests/test_movie_ui_checks.py` and `tests/test_ltx_movie_offline.py`;
- the tests `test_mut16_stills_count_during_phase_2`, `test_rst47_robust_dry_run` (kept green by Plan ruling SPR5), `test_rst46_review_gate` and `test_rst50b_robust_review_reads_utf8`.

None of them is in the list, so a failure there stops the gate.

---

## Before Task 1: the plan commit, the worktree, the snapshot, the baseline (controller; no code)

- [ ] **Step 1: Commit this plan on `qwen-agent-redteam` (after the user approves the plan).**

This follows how `ed9dfad docs(plan): shot prompt format implementation plan` was committed. Committing on the branch before the worktree is cut keeps the main checkout's copy of this file from blocking the later fast-forward.

```bash
cd /Users/reubenpatterson/local_agent_harness
git branch --show-current          # expected: qwen-agent-redteam
git log -1 --format=%h             # expected: 9952d81
git add qwen-agent-workspace/docs/superpowers/plans/2026-10-29-soft-panel-count.md
git diff --cached --name-only      # expected: only qwen-agent-workspace/docs/superpowers/plans/2026-10-29-soft-panel-count.md
git commit -m "docs(plan): soft panel count implementation plan" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 2: Create the worktree and confirm the tree.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
git -C /Users/reubenpatterson/local_agent_harness worktree add -b sp-impl $S/sp-wt qwen-agent-redteam
WS=$S/sp-wt/qwen-agent-workspace
cd $WS
git branch --show-current                                   # expected: sp-impl
git log -1 --format=%s                                      # expected: docs(plan): soft panel count implementation plan
git rev-parse HEAD~1                                        # expected: 9952d81ace0a733ac706b9ed4bc99c59a44319be
git diff --stat 9952d81 HEAD -- . ':(exclude)docs' | tail -1   # expected: no output
git status --short                                          # expected: no output
ls tests/test_soft_panel_count.py 2>&1 | grep -c "No such file"   # expected: 1
wc -l < story_engine.py                                     # expected: 4692
wc -l < bin/ltx-movie                                       # expected: 2540
grep -c "panels_target\|PANELS_EXTRA" story_engine.py bin/ltx-movie movie_ui_lib.py   # expected: three lines ending :0
grep -c "42f33640cd008021a32dc0f8f948d0e8da04de2b" tests/test_movie_ui_builder.py   # expected: 2
```

If any value differs, stop and report: every Edit below was written against this tree.

- [ ] **Step 3: Take the compressed snapshot (house rule; spec 6 step 1).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
tar czf $S/snapshot-pre-soft-panels-9952d81.tgz --exclude qwen-agent-workspace/generated -C $S/sp-wt qwen-agent-workspace
tar tzf $S/snapshot-pre-soft-panels-9952d81.tgz | grep -c '^qwen-agent-workspace/story_engine.py$'   # expected: 1
```

- [ ] **Step 4: Record a fresh baseline at `9952d81` and write the gate files (about 15 minutes).**

The controller records a fresh full-suite baseline in the worktree, whose code tree is `9952d81`'s. It does not copy an older run.

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/sp-baseline
mkdir -p $D
cd $S/sp-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
grep -c '^PASSED ' $D/baseline-pytest.txt
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1 | tee $D/baseline-offline.txt
```

Expected:
- a summary of `2 failed, 1931 passed, 2 skipped` (the warning count and time vary);
- exactly two `FAILED` lines: `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets - AssertionError: b...`;
- `1931`;
- `OK 347/347`.

If the numbers differ, the recorded file is still the baseline. Report the difference, and use the recorded pass count wherever this plan says 1931.

Then write two scratch files with the Write tool. They are outside the repository and never staged.

1. `$D/expected-failures.txt`: exactly the `text` block of "Between tasks" above.
2. `$D/gate.py`:

```python
"""The task gate of the soft panel count plan: a full pytest -rA run against the baseline."""
import re
import sys

base_file, run_file, expected_file, task = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])


def status(path):
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            match = re.match(r"^(PASSED|FAILED|ERROR) (\S+)", line)
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
mine = sorted(t for t in now if t.startswith("tests/test_soft_panel_count.py::"))
broken = [t for t in mine if now[t] != "PASSED"]
old_failures = sorted(t for t, s in base.items() if s != "PASSED")
still = [t for t in old_failures if now.get(t) != "PASSED"]
print("lost %d (listed %d, unexpected %d); test_soft_panel_count %d, not passing %d; baseline "
      "failures still failing %d of %d" % (len(lost), len(lost) - len(unexpected),
                                          len(unexpected), len(mine), len(broken), len(still),
                                          len(old_failures)))
for t in lost:
    print("LOST", t, "listed" if listed(t) else "UNEXPECTED")
for t in broken:
    print("NEW-FILE-FAIL", t)
print("GATE", "PASS" if not unexpected and not broken else "STOP")
```

`tests/test_fleet_tracing.py::test_trt41a_trace_cli_on_one_agent` is timing-sensitive and unrelated to this plan. If the gate lists it as UNEXPECTED, rerun it alone (`python3 -B -m pytest -q -p no:cacheprovider tests/test_fleet_tracing.py -k trt41a`). If it passes alone, the controller appends `T<N> tests/test_fleet_tracing.py::test_trt41a_trace_cli_on_one_agent flaky +gate`, and Task 8 rechecks it.

**The gate block** (Step 4 of every code task; `N` is the task number). It is a full run of about 15 minutes, which may run in the background:

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/sp-baseline
N=1
cd $S/sp-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/task-$N-pytest.txt 2>&1; tail -1 $D/task-$N-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/task-$N-pytest.txt $D/expected-failures.txt $N
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1
```

Expected: `GATE PASS`, `test_soft_panel_count <count>, not passing 0`, `baseline failures still failing 2 of 2`, and `OK 347/347`. Each task's Step 4 gives its count. On `GATE STOP`, follow the gate rule ("Between tasks").

---

### Task 1: The range and the plan prompt (SPC1-SPC5, SPC12 b; Plan ruling SPR2's pre-flight)

This task implements:
- SPC1: `StoryContext.panels_target`, plus SPR2's `length`; `PANELS_EXTRA`, `target_panels`, `most_panels`, `speaker_runs`, `lines_needed`, `declared_speakers` and `panel_range`. It also adds SPR2's `length_for`.
- SPC2: the reworded `LINES_RULE` and `LINES_PINNED_SENTENCE`, and the constants `PANEL_COUNT_RULE`, `PANEL_COUNT_MIN_CLAUSE`, `PANEL_COUNT_LINES_SENTENCE` and `ARC_COUNT_CLAUSES`.
- SPC3: the pre-flight stops only beyond N+2. Plan ruling SPR2 adds `LINES_LENGTH_PROBLEM` for a movie that `--length` sized.
- SPC4: the template's count text and `build_plan_prompt`'s fragments and scalars.
- SPC5: `_plan_arc_rule`.
- SPC12 (b): `SPEAKING_BEAT_SENTENCE`.

Tests: SPT1 (engine part: `test_spt1a_engine_constants`, and the compile check), SPT2, SPT3, SPT4, SPT5, SPT22, SPT23 and SPR2's `test_spr2a_...`. The task creates `tests/test_soft_panel_count.py` with the whole spec 4.1 header and helpers, and later tasks append to it. This is the first pipeline commit, so `test_mut26` fails from here until Task 8.

**Files:**
- Create: `tests/test_soft_panel_count.py`
- Modify: `story_engine.py`. The edits go to `StoryContext` and its comment (`:93-102`), after `engine_seconds` (`:105-107`), `LINES_RULE` through `LINE_SPEAKERS_SENTENCE` (`:394-410`), the template beat clause (`:317-319`), `SPEAKING_BEAT_SENTENCE` (`:365-369`), after `panels_needed` (`:743-752`), `spoken_lines_problem` (`:755-785`), after `_arc_rule` (`:812-818`), and `build_plan_prompt` (`:941-1003`).

**Interfaces:**
- Consumes (existing):
  - from `story_engine`: `required_lines(ctx)`, `spoken_lines(narrative)`, `line_speakers(narrative, cast)`, `panels_needed(lib, seconds, lines)`, `engine_seconds(ctx)`, `_character_lib(ws)`, `_arc_rule(n)`, `max_static(panels)`, `build_plan_prompt(ctx, compatible, pins)`, `run(ctx)`, and `CAMERA_RULE` and `SPEAKER_RULE*` from [SF];
  - from `story_engine_testutil`: `set_story_env`, `make_ws`, `make_ctx(se, ws, **overrides)`, `plan_json`, `panel_json`, `answer`, `script_agent`, `agent_log`, `kyra`, `ronin`.
- Produces:
  - In `story_engine`:
    - `StoryContext` fields `panels_target` and `length`, both defaulting to `None`;
    - `PANELS_EXTRA = 2`;
    - `target_panels(ctx) -> int`, `most_panels(ctx) -> int` and `length_for(ctx, panels: int) -> str` (seconds to one decimal);
    - `speaker_runs(lines: [str], speakers: [str or None]) -> [[str]]`;
    - `lines_needed(lib, seconds, lines, speakers) -> int`;
    - `declared_speakers(ctx) -> [str or None]`;
    - `panel_range(ctx) -> (lo, hi)`;
    - `_plan_arc_rule(lo, hi) -> str`;
    - the constants `PANEL_COUNT_RULE` (a `%` format of `(int target, str min_clause, int lo, int hi)`), `PANEL_COUNT_MIN_CLAUSE` (`% lo`), `PANEL_COUNT_LINES_SENTENCE`, `ARC_COUNT_CLAUSES` (dict 1-3) and `LINES_LENGTH_PROBLEM` (a `%` format of 10 values, see SPR2).
  - In `tests/test_soft_panel_count.py`:
    - the module header (`WS`, `seu`, `lib` = `character_lib`, `se`, `ltx_movie`, `iterate_story`, `manifest`, `mui` = `movie_ui_lib`; imports `base64`, `copy`, `json`, `os`, `shlex`, `subprocess`, `sys`, `pytest`) and the fixtures `story_env` (autouse), `ws` and `movie`;
    - the helpers `HOCKEY`, `EIGHT`, `TURNS`, `SIX_WORD_LINES`, `LINES_NARRATIVE`, `NARRATIVE`, `panel_script(mode, n, ...)`, `save_story(ws, tmp_path, monkeypatch, story_id, mode, target, beats) -> ctx`, `_members(story_env, names)`, `_read_json(story_dir, name)` and `_plan_prompt(ws, **kw)`;
    - the literals `LINES_RULE`, `LINES_PINNED_SENTENCE`, `PANEL_COUNT_RULE`, `PANEL_COUNT_MIN_CLAUSE`, `PANEL_COUNT_LINES_SENTENCE`, `ARC_COUNT_CLAUSES`, `SPEAKING_BEAT_SENTENCE`, `LINES_LENGTH_PROBLEM`, `SPC3_EXAMPLE`, `FIVE_TURNS` and `SPC4_EXAMPLE`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_spt1a_engine_constants`, `test_spt1_the_pipeline_files_compile_under_both_pythons`, `test_spt22_no_server_and_no_real_home`, `test_spt2_target_most_and_the_range`, `test_spt23_speaker_runs_and_lines_needed`, `test_spt3_the_pre_flight`, `test_spr2a_the_pre_flight_names_length_when_length_sized_the_movie`, `test_spt4_the_plan_prompt` and `test_spt5_the_arc_rule`.

Create `tests/test_soft_panel_count.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""Tests for the soft panel count (docs/superpowers/specs/2026-10-29-soft-panel-count-design.md,
Section 4.1: SPT1-SPT27, with the plan's rulings SPR1-SPR5 and its Review Focus 1-5): --panels
is a target, the story planner may use up to PANELS_EXTRA more beats, everything after the plan
uses the plan's beat count, the user is told why (P20), the P19 hint says how to keep a dropped
exit, and the movie UI and bin/iterate-story follow the story's real count.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_soft_panel_count.py
Stdlib plus pytest. No test renders, reads the real HOME, or contacts a model server, a daemon or
the Anthropic API: every model call goes to the fake bin/qwen-agent of a temp workspace
(story_engine_testutil.make_ws), every ctx lives under tmp_path, and every test runs under the
autouse story_env fixture (a temporary HOME, character library and LoRA catalog). The one HTTP
check (SPT26) talks to a movie-ui server that the test itself starts on 127.0.0.1.
"""

import base64
import copy
import importlib.machinery
import json
import os
import shlex
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


lib = _load("character_lib_for_soft_count", "character_lib.py")
se = _load("story_engine_for_soft_count", "story_engine.py")
ltx_movie = _load("ltx_movie_for_soft_count", os.path.join("bin", "ltx-movie"))
iterate_story = _load("iterate_story_for_soft_count", os.path.join("bin", "iterate-story"))
manifest = _load("ltx_story_manifest_for_soft_count", os.path.join("bin", "ltx-story-manifest"))
mui = _load("movie_ui_lib_for_soft_count", "movie_ui_lib.py")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


@pytest.fixture
def movie(tmp_path, monkeypatch):
    """A temp workspace with the fake agent; ltx_movie.WS points at it; no sudo check
    (copied from tests/test_story_engine.py)."""
    ws = seu.make_ws(tmp_path)
    monkeypatch.setattr(ltx_movie, "WS", ws)
    monkeypatch.setattr(ltx_movie, "_check_sudo_and_start_keepalive", lambda: None)
    return ws


# --- Helpers (spec 4.1) ----------------------------------------------------------------------

with open(os.path.join(WS, "tests", "fixtures", "narrative_fidelity", "narrative.txt"),
          encoding="utf-8") as _f:
    HOCKEY = _f.read().strip()
EIGHT = ('The courier says "Keep moving along the wet harbour road now." Then he says "The temple '
         'gate is close to us now." He says "Can you see the lanterns by the gate?" At the gate he '
         'says "We made it here before the rain came."')
TURNS = ('Kyra says, "Go now." The ronin says, "Wait here." Kyra says, "Come on." The ronin says, '
         '"Not yet."')
# Written out from tests/test_narrative_fidelity.py.
SIX_WORD_LINES = ('The courier says "Keep moving along the wet road." Then he says "The temple gate '
                  'is close now." At the gate he whispers "We made it here at last."')
LINES_NARRATIVE = ('At dusk Kyra climbs the stone steps of a mountain temple, and the ronin walks '
                   'one step behind her. Near the top Kyra turns and says, "We reach the gate '
                   'before dark." They pass under the gate together, and Kyra says, "Stay close '
                   'to me."')
NARRATIVE = "A courier carries a sealed letter across a rainy harbour town."


def panel_script(mode, n, phrase="the courier", **overrides):
    """{"<k>": [one valid reply]} for every panel; overrides p<k>=[items] replace panel k's
    (copied from tests/test_story_engine.py::_panel_script)."""
    script = dict((str(k), [seu.answer(seu.panel_json(mode, k, phrase))]) for k in range(1, n + 1))
    for key, items in overrides.items():
        script[key[1:]] = items
    return script


def save_story(ws, tmp_path, monkeypatch, story_id, mode, target, beats):
    """A story generated by se.run for --panels target from a plan of `beats` beats; returns
    the ctx (spec 4.1)."""
    seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(seu.plan_json(mode, beats))],
                     panel=panel_script(mode, beats))
    ctx = seu.make_ctx(se, ws, story_id=story_id, mode=mode, panels=target)
    rc, _advisories = se.run(ctx)
    assert rc == 0
    return ctx


def _members(story_env, names=("kyra", "ronin")):
    """The library members for names, kyra (c1, "the woman in grey") and ronin (c2, "the
    ronin")."""
    for name in names:
        getattr(seu, name)(story_env["lib"])
    return lib.resolve_cast([(None, name) for name in names])


def _read_json(story_dir, name):
    with open(os.path.join(story_dir, name), encoding="utf-8") as f:
        return json.load(f)


def _plan_prompt(ws, **kw):
    """The plan prompt of make_ctx(**kw), with no catalog and no pins."""
    return se.build_plan_prompt(seu.make_ctx(se, ws, **kw), [], [])


# --- SPT1 (Task 1 part): the engine constants (SPC1-SPC5, SPC12 b; plan ruling SPR2) ----------

LINES_RULE = (" lines is the list of the numbers of the spoken lines above that the speaker says "
              "aloud during the beat, in order, or an empty list. Every spoken line belongs to "
              "exactly one beat, in the narrative's order: give each line to the beat whose action "
              "surrounds it in the narrative, and give a speaker to every beat with lines and to no "
              "other beat. A beat may hold two or more consecutive lines only when one character "
              "says them all and together they are at most @@LINE_WORDS@@ words. Give each line its "
              "own beat whenever there are at least as many target beats (@@MIN_BEATS@@) as lines; "
              "never add a beat only to separate lines that fit together.")
LINES_PINNED_SENTENCE = (" A beat with a speaker shows only the speaker, so every already-cast "
                         "character who says none of the lines still needs a beat with no "
                         "speaker: add a beat for it when the beat count allows it, else let two "
                         "consecutive lines share one.")
PANEL_COUNT_RULE = (" This movie's target length is %d beats%s, and like a word range it is "
                    "soft: use %d beats when the narrative fits them, and add a beat, up to %d "
                    "beats in all, only for something the narrative needs that no other beat can "
                    "hold.")
PANEL_COUNT_MIN_CLAUSE = ", but its spoken lines need at least %d"
PANEL_COUNT_LINES_SENTENCE = (" A spoken line that cannot share a beat with the line beside it "
                              "gets a beat of its own.")
ARC_COUNT_CLAUSES = {
    1: "with 1 beat, use climax",
    2: "with 2 beats, the first beat is introduction and the last is resolution",
    3: ("with 3 or more beats, the first beat is introduction, the last is resolution, and at "
        "least one beat is climax"),
}
SPEAKING_BEAT_SENTENCE = (" Write a speaking beat's action as what the speaker physically does, "
                          "never as speaking, and end it with the speaker still in frame: nobody "
                          "else acts after the line, and when the narrative has the speaker "
                          "leave, or another character act, after a line, give that a later beat "
                          "with no speaker, adding that beat when the beat count allows it, and "
                          "leave it out only when it does not.")
LINES_LENGTH_PROBLEM = (
    "the narrative quotes %d spoken lines, which need at least %d panels of %s seconds (one panel "
    "has one speaker and speaks at most %d words), but this movie has at most %d (--length %s "
    "sets a target of %d, plus up to %d more); rerun with --force-story --length %s or more (a "
    "target of %d panels), or with longer clips (a larger --frames)")
SPC3_EXAMPLE = ("the narrative quotes 4 spoken lines, which need at least 4 panels of 6 seconds (one "
                "panel has one speaker and speaks at most 14 words), but this movie has at most 3 "
                "(--panels 1 plus up to 2 more); rerun with --force-story --panels 2 or more, or "
                "with longer clips (a larger --frames)")


def test_spt1a_engine_constants():
    assert se.PANELS_EXTRA == 2
    assert se.LINES_RULE == LINES_RULE
    assert se.LINES_PINNED_SENTENCE == LINES_PINNED_SENTENCE
    assert se.PANEL_COUNT_RULE == PANEL_COUNT_RULE
    assert se.PANEL_COUNT_MIN_CLAUSE == PANEL_COUNT_MIN_CLAUSE
    assert se.PANEL_COUNT_LINES_SENTENCE == PANEL_COUNT_LINES_SENTENCE
    assert se.ARC_COUNT_CLAUSES == ARC_COUNT_CLAUSES
    assert se.SPEAKING_BEAT_SENTENCE == SPEAKING_BEAT_SENTENCE
    assert se.SPEAKER_RULE.endswith(SPEAKING_BEAT_SENTENCE)
    assert se.SPEAKER_RULE_KEEP_CAST.endswith(SPEAKING_BEAT_SENTENCE)
    assert se.LINES_LENGTH_PROBLEM == LINES_LENGTH_PROBLEM
    assert se.StoryContext._fields[-2:] == ("panels_target", "length")
    assert se.StoryContext._field_defaults == {"narration": True, "clip_seconds": None,
                                               "panels_target": None, "length": None}
    assert "@@PANELS@@" not in se.PLAN_PROMPT_TEMPLATE


def test_spt1_the_pipeline_files_compile_under_both_pythons():
    script = ("import sys\n"
              "for path in sys.argv[1:]:\n"
              "    with open(path, encoding='utf-8') as f:\n"
              "        compile(f.read(), path, 'exec')\n"
              "print('compiled %d' % (len(sys.argv) - 1))\n")
    files = [os.path.join(WS, name) for name in
             ("story_engine.py", os.path.join("bin", "ltx-movie"),
              os.path.join("bin", "iterate-story"), "movie_ui_lib.py")]
    pythons = [sys.executable] + (["/usr/bin/python3"] if os.path.exists("/usr/bin/python3")
                                  else [])
    for python in pythons:
        proc = subprocess.run([python, "-c", script] + files, capture_output=True, text=True)
        assert (proc.returncode, proc.stdout) == (0, "compiled 4\n"), (python, proc.stderr)


def test_spt22_no_server_and_no_real_home(story_env, tmp_path):
    assert os.path.expanduser("~") == story_env["home"]
    assert story_env["home"].startswith(str(tmp_path))
    assert os.environ["QWEN_AGENT_DAEMON_URL"].startswith("http://127.0.0.1:")
    assert "ANTHROPIC_API_KEY" not in os.environ


# --- SPT2, SPT23: the range and the speaker runs (SPC1, D2) -----------------------------------

def test_spt2_target_most_and_the_range(ws, story_env):
    def ctx(**kw):
        return seu.make_ctx(se, ws, **kw)

    assert len(se.spoken_lines(EIGHT)) == 4
    assert se.panels_needed(lib, 6.0, se.spoken_lines(EIGHT)) == 4
    members = _members(story_env)
    assert se.declared_speakers(ctx(narrative=TURNS, members=members)) == ["c1", "c2", "c1", "c2"]
    rows = (
        ({}, (3, 5)),
        ({"panels": 1}, (1, 3)),
        ({"panels": 1, "narrative": SIX_WORD_LINES}, (2, 3)),
        ({"panels": 2, "narrative": EIGHT}, (4, 4)),
        ({"panels": 2, "narrative": EIGHT, "narration": False}, (2, 4)),
        ({"panels": 5, "panels_target": 3}, (3, 5)),
        ({"panels": 1, "narrative": TURNS}, (2, 3)),
        ({"panels": 2, "narrative": TURNS, "members": members}, (4, 4)),
    )
    for kw, want in rows:
        assert se.panel_range(ctx(**kw)) == want, kw
    both = ctx(panels=5, panels_target=3)
    assert (se.target_panels(both), se.most_panels(both)) == (3, 5)
    plain = ctx(panels=4)
    assert (se.target_panels(plain), se.most_panels(plain)) == (4, 6)


def test_spt23_speaker_runs_and_lines_needed():
    lines = ["a", "b", "c", "d"]
    rows = (
        ([None] * 4, [["a", "b", "c", "d"]]),
        (["c1", "c2", "c1", "c2"], [["a"], ["b"], ["c"], ["d"]]),
        (["c1", None, "c1", "c2"], [["a", "b", "c"], ["d"]]),
        ([None, "c2", None, "c1"], [["a", "b", "c"], ["d"]]),
        (["c1", "c1", "c2", "c2"], [["a", "b"], ["c", "d"]]),
    )
    for speakers, want in rows:
        assert se.speaker_runs(lines, speakers) == want, speakers
    turns = se.spoken_lines(TURNS)
    assert se.lines_needed(lib, 6.0, turns, ["c1", "c2", "c1", "c2"]) == 4
    assert se.lines_needed(lib, 6.0, turns, [None] * 4) == 2
    assert se.panels_needed(lib, 6.0, turns) == 2


# --- SPT3: the spoken-lines pre-flight (SPC3; plan ruling SPR2) -------------------------------

def test_spt3_the_pre_flight(ws, tmp_path, monkeypatch, capsys, story_env):
    def problem(**kw):
        return se.spoken_lines_problem(seu.make_ctx(se, ws, **kw))

    assert problem(narrative=EIGHT, panels=1) == SPC3_EXAMPLE
    assert problem(narrative=EIGHT, panels=2) is None
    assert problem(narrative=SIX_WORD_LINES, panels=1) is None
    members = _members(story_env)
    assert problem(narrative=TURNS, members=members, panels=1) == SPC3_EXAMPLE
    assert problem(narrative=TURNS, panels=1) is None
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(seu.plan_json("chained", 1))])
    ctx = seu.make_ctx(se, ws, narrative=EIGHT, panels=1, story_id="spt3")
    capsys.readouterr()
    rc, _advisories = se.run(ctx)
    assert rc == 2
    assert capsys.readouterr().err == "Error: " + SPC3_EXAMPLE + "\n"
    assert seu.agent_log(log) == []
    assert _read_json(os.path.join(ctx.story_dir, "story_rounds"), "run.json")["exit"] == 2


FIVE_TURNS = TURNS + ' Kyra says, "Now."'


def test_spr2a_the_pre_flight_names_length_when_length_sized_the_movie(ws, story_env):
    members = _members(story_env)
    clip = 145 / 24.0
    base = dict(narrative=FIVE_TURNS, members=members, panels=2, clip_seconds=clip)
    cap = lib.dialogue_word_cap(clip, 1)
    assert se.spoken_lines_problem(seu.make_ctx(se, ws, **base)) == (
        "the narrative quotes 5 spoken lines, which need at least 5 panels of 6 seconds (one panel "
        "has one speaker and speaks at most %d words), but this movie has at most 4 (--panels 2 "
        "plus up to 2 more); rerun with --force-story --panels 3 or more, or with longer clips (a "
        "larger --frames)" % cap)
    found = se.spoken_lines_problem(seu.make_ctx(se, ws, length=12.0, **base))
    assert found == LINES_LENGTH_PROBLEM % (5, 5, "6", cap, 4, "12.0", 2, 2, "18.1", 3)
    assert "--panels" not in found
    assert se.length_for(seu.make_ctx(se, ws, **base), 3) == "18.1"
    assert round(18.1 / clip) == 3


# --- SPT4: the plan prompt (SPC2, SPC4, D9) ---------------------------------------------------

SPC4_EXAMPLE = (
    "beats: a list of 3 to 5 objects, one per panel in order, with the keys index, arc, action, "
    "shot, camera, location, cast and speaker. index runs from 1 to the number of beats. This "
    "movie's target length is 3 beats, and like a word range it is soft: use 3 beats when the "
    "narrative fits them, and add a beat, up to 5 beats in all, only for something the narrative "
    "needs that no other beat can hold. arc is one of introduction, rising, climax, falling, "
    "resolution, in story order; the first beat is introduction, the last is resolution, and at "
    "least one beat is climax.")


def test_spt4_the_plan_prompt(ws, story_env):
    prompts = []

    def prompt(**kw):
        prompts.append(_plan_prompt(ws, **kw))
        return prompts[-1]

    assert SPC4_EXAMPLE in prompt(panels=3)
    text = prompt(narrative=EIGHT, panels=2)
    assert "beats: a list of EXACTLY 4 objects" in text
    assert "index runs from 1 to the number of beats. arc is one of" in text
    assert "target length" not in text
    ctx = seu.make_ctx(se, ws, mode="chained", panels=2, narration="speech", narrative=HOCKEY)
    line_cap = str(lib.dialogue_word_cap(se.engine_seconds(ctx), 2))
    text = prompt(mode="chained", panels=2, narration="speech", narrative=HOCKEY)
    assert (PANEL_COUNT_RULE % (2, "", 2, 4) + PANEL_COUNT_LINES_SENTENCE + " arc is one of") in text
    assert LINES_RULE.replace("@@LINE_WORDS@@", line_cap).replace("@@MIN_BEATS@@", "2") in text
    text = prompt(mode="chained", panels=2, narration=False, narrative=HOCKEY)
    assert (PANEL_COUNT_RULE % (2, "", 2, 4) + " arc is one of") in text
    text = prompt(panels=1, narrative=SIX_WORD_LINES)
    assert PANEL_COUNT_RULE % (1, PANEL_COUNT_MIN_CLAUSE % 2, 2, 3) in text
    assert "at least as many target beats (2) as lines" in text
    assert LINES_PINNED_SENTENCE in prompt(mode="shots", narrative=LINES_NARRATIVE,
                                           members=_members(story_env, ("kyra",)))
    assert se.CAMERA_RULE.replace("@@MAX_STATIC@@", "1") in prompt(mode="shots", panels=3)
    text = prompt(narrative=TURNS, members=_members(story_env), panels=2)
    assert "line 1 to c1, line 2 to c2, line 3 to c1 and line 4 to c2" in text
    for text in prompts:
        assert "@@" not in text and "EXACTLY 3 objects" not in text


# --- SPT5: the arc rule for a range (SPC5) ----------------------------------------------------

def test_spt5_the_arc_rule():
    assert se._plan_arc_rule(1, 3) == (
        "with 1 beat, use climax; with 2 beats, the first beat is introduction and the last is "
        "resolution; with 3 or more beats, the first beat is introduction, the last is "
        "resolution, and at least one beat is climax.")
    assert se._plan_arc_rule(2, 4) == (
        "with 2 beats, the first beat is introduction and the last is resolution; with 3 or more "
        "beats, the first beat is introduction, the last is resolution, and at least one beat is "
        "climax.")
    assert se._plan_arc_rule(3, 5) == ("the first beat is introduction, the last is resolution, "
                                       "and at least one beat is climax.")
    assert se._plan_arc_rule(4, 4) == se._arc_rule(4)
    assert se._plan_arc_rule(2, 2) == ARC_COUNT_CLAUSES[2] + "."
```

- [ ] **Step 2: Run the tests to verify that they fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sp-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_soft_panel_count.py 2>&1 | tail -1
```

Expected: the summary starts `7 failed, 2 passed`. The compile check and SPT22 pass already; the other seven fail on the missing `PANELS_EXTRA`, `panel_range`, `speaker_runs` and `_plan_arc_rule`, and on the old prompt text.

- [ ] **Step 3: Implement SPC1-SPC5, SPC12 (b) and SPR2's pre-flight.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "auto_lora", "catalog", "pinned", "stills_pinned", "judge", "narration", "clip_seconds"],
    defaults=(True, None))
```

with:

```python
    "auto_lora", "catalog", "pinned", "stills_pinned", "judge", "narration", "clip_seconds",
    "panels_target", "length"],
    defaults=(True, None, None, None))
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
# clip_seconds: the exact clip length (frames / fps) the timing rules use; None means
# float(seconds) (docs/superpowers/specs/2026-10-24-on-camera-dialogue-design.md 2.4).
```

with:

```python
# clip_seconds: the exact clip length (frames / fps) the timing rules use; None means
# float(seconds) (docs/superpowers/specs/2026-10-24-on-camera-dialogue-design.md 2.4).
# Soft panel count spec SPC1, D1: panels is the movie's panel count -- the --panels target until
# the plan is accepted, the plan's beat count after; panels_target is --panels (None: panels).
# Plan ruling SPR2: length is bin/ltx-movie's --length in seconds when --length sized the movie
# (None otherwise); the panel-count hints then name --length, never --panels.
```

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def engine_seconds(ctx):
    """The clip length in seconds that the timing rules use (dialogue spec 2.4)."""
    return ctx.clip_seconds if ctx.clip_seconds is not None else float(ctx.seconds)
```

with:

```python
def engine_seconds(ctx):
    """The clip length in seconds that the timing rules use (dialogue spec 2.4)."""
    return ctx.clip_seconds if ctx.clip_seconds is not None else float(ctx.seconds)


# Soft panel count spec SPC1, D2: the planner may add up to PANELS_EXTRA beats to the target.
PANELS_EXTRA = 2


def target_panels(ctx):
    """The --panels target (soft panel count spec SPC1)."""
    return ctx.panels if ctx.panels_target is None else ctx.panels_target


def most_panels(ctx):
    """The most beats a plan may have: the target plus PANELS_EXTRA (SPC1)."""
    return target_panels(ctx) + PANELS_EXTRA


def length_for(ctx, panels):
    """The --length, in seconds to one decimal, that bin/ltx-movie resolves to a target of
    `panels` clips of this movie's clip length (plan ruling SPR2)."""
    return "%.1f" % (panels * engine_seconds(ctx))
```

**3.4.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
# Narrative dialogue fidelity spec 7.1 (e): only when the narrative quotes spoken lines.
LINES_RULE = (" lines is the list of the numbers of the spoken lines above that the speaker says "
              "aloud during the beat, in order, or an empty list. Every spoken line belongs to "
              "exactly one beat, in the narrative's order: give each line to the beat whose action "
              "surrounds it in the narrative, and give a speaker to every beat with lines and to no "
              "other beat. A beat may hold two or more consecutive lines only when together they "
              "are at most @@LINE_WORDS@@ words. Give each line its own beat whenever there are at "
              "least as many beats as lines.")
# Pinned cast presence spec PC6, D3: where a speaking beat shows only the speaker, a declared
# character with no line needs a beat without a speaker.
LINES_PINNED_SENTENCE = (" A beat with a speaker shows only the speaker, so every already-cast "
                         "character who says none of the lines still needs a beat with no "
                         "speaker, even when two consecutive lines must then share a beat.")
# Speaker attribution spec SA6, D5: the lines the narrative gives to already-cast characters.
LINE_SPEAKERS_SENTENCE = (" The narrative gives these lines to already-cast characters: %s. The "
                          "beat that holds one of these lines has that character as its speaker, "
                          "and no other character says it.")
```

with:

```python
# Narrative dialogue fidelity spec 7.1 (e): only when the narrative quotes spoken lines; soft
# panel count spec SPC2.
LINES_RULE = (" lines is the list of the numbers of the spoken lines above that the speaker says "
              "aloud during the beat, in order, or an empty list. Every spoken line belongs to "
              "exactly one beat, in the narrative's order: give each line to the beat whose action "
              "surrounds it in the narrative, and give a speaker to every beat with lines and to no "
              "other beat. A beat may hold two or more consecutive lines only when one character "
              "says them all and together they are at most @@LINE_WORDS@@ words. Give each line its "
              "own beat whenever there are at least as many target beats (@@MIN_BEATS@@) as lines; "
              "never add a beat only to separate lines that fit together.")
# Pinned cast presence spec PC6, D3: where a speaking beat shows only the speaker, a declared
# character with no line needs a beat without a speaker; soft panel count spec SPC2.
LINES_PINNED_SENTENCE = (" A beat with a speaker shows only the speaker, so every already-cast "
                         "character who says none of the lines still needs a beat with no "
                         "speaker: add a beat for it when the beat count allows it, else let two "
                         "consecutive lines share one.")
# Speaker attribution spec SA6, D5: the lines the narrative gives to already-cast characters.
LINE_SPEAKERS_SENTENCE = (" The narrative gives these lines to already-cast characters: %s. The "
                          "beat that holds one of these lines has that character as its speaker, "
                          "and no other character says it.")
# Soft panel count spec SPC2, D3: the beat count is a target the planner may exceed by up to
# PANELS_EXTRA, like a word range.
PANEL_COUNT_RULE = (" This movie's target length is %d beats%s, and like a word range it is "
                    "soft: use %d beats when the narrative fits them, and add a beat, up to %d "
                    "beats in all, only for something the narrative needs that no other beat can "
                    "hold.")
PANEL_COUNT_MIN_CLAUSE = ", but its spoken lines need at least %d"
PANEL_COUNT_LINES_SENTENCE = (" A spoken line that cannot share a beat with the line beside it "
                              "gets a beat of its own.")
# Soft panel count spec SPC5: the arc rule for each beat count the range allows.
ARC_COUNT_CLAUSES = {
    1: "with 1 beat, use climax",
    2: "with 2 beats, the first beat is introduction and the last is resolution",
    3: ("with 3 or more beats, the first beat is introduction, the last is resolution, and at "
        "least one beat is climax"),
}
```

**3.5.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "beats: a list of EXACTLY @@PANELS@@ objects, one per panel in order, with the keys index, "
    "arc, action, shot, camera, location, @@BEAT_KEYS@@. index runs from 1 to @@PANELS@@. arc "
    "is one of "
```

with:

```python
    "beats: a list of @@BEAT_COUNT@@ objects, one per panel in order, with the keys index, "
    "arc, action, shot, camera, location, @@BEAT_KEYS@@. index runs from 1 to the number of "
    "beats.@@PANEL_COUNT_RULE@@ arc is one of "
```

**3.6.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
                          "leave, or another character act, after a line, give that a later beat "
                          "with no speaker, or leave it out when no later beat is left.")
```

with:

```python
                          "leave, or another character act, after a line, give that a later beat "
                          "with no speaker, adding that beat when the beat count allows it, and "
                          "leave it out only when it does not.")
```

**3.7.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        needed += 1
        i = j + 1
    return needed
```

with:

```python
        needed += 1
        i = j + 1
    return needed


def speaker_runs(lines, speakers):
    """The spoken lines split into the runs one beat could hold by speaker (soft panel count spec
    SPC1, D2): a line starts a new run when its speaker is known and differs from a known speaker
    earlier in the current run; a line with no known speaker (None) joins the current run."""
    runs, current, who = [], [], None
    for line, cid in zip(lines, speakers):
        if current and cid is not None and who is not None and cid != who:
            runs.append(current)
            current, who = [], None
        current.append(line)
        if cid is not None:
            who = cid
    if current:
        runs.append(current)
    return runs


def lines_needed(lib, seconds, lines, speakers):
    """The fewest panels that speak lines in order with one speaker each (SPC1): panels_needed
    summed over speaker_runs."""
    return sum(panels_needed(lib, seconds, run) for run in speaker_runs(lines, speakers))


def declared_speakers(ctx):
    """line_speakers of the narrative against the declared members, as c1, c2, ... in
    --character order (the mapping build_plan_prompt gives the planner); one None per line when
    nothing is declared (SPC1)."""
    fixed = [{"id": "c%d" % i, "phrase": m.phrase, "cast_name": m.name}
             for i, m in enumerate(ctx.members, start=1)]
    return line_speakers(ctx.narrative, fixed)


# Plan ruling SPR2: the pre-flight's count hint when --length sized the movie.
LINES_LENGTH_PROBLEM = (
    "the narrative quotes %d spoken lines, which need at least %d panels of %s seconds (one panel "
    "has one speaker and speaks at most %d words), but this movie has at most %d (--length %s "
    "sets a target of %d, plus up to %d more); rerun with --force-story --length %s or more (a "
    "target of %d panels), or with longer clips (a larger --frames)")
```

**3.8.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def spoken_lines_problem(ctx):
    """Why the narrative's spoken lines cannot be spoken in this movie, or None (QL5): a line no
    clip fits, a line this clip length does not fit, or more lines than the panels can hold."""
```

with:

```python
def spoken_lines_problem(ctx):
    """Why the narrative's spoken lines cannot be spoken in this movie, or None (QL5): a line no
    clip fits, a line this clip length does not fit, or more lines than the target plus
    PANELS_EXTRA panels can hold, one speaker per panel (soft panel count spec SPC3)."""
```

**3.9.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    needed = panels_needed(lib, secs, lines)
    if needed > ctx.panels:
        return ("the narrative quotes %d spoken lines, which need at least %d panels of %s seconds "
                "(one panel speaks at most %d words), but this movie has %d; use --panels %d or "
                "more, or longer clips (a larger --frames)"
                % (len(lines), needed, ctx.seconds, lib.dialogue_word_cap(secs, 1), ctx.panels,
                   needed))
    return None
```

with:

```python
    needed = lines_needed(lib, secs, lines, declared_speakers(ctx))
    most = most_panels(ctx)
    if needed > most and ctx.length is not None:
        return (LINES_LENGTH_PROBLEM
                % (len(lines), needed, ctx.seconds, lib.dialogue_word_cap(secs, 1), most,
                   "%.1f" % ctx.length, target_panels(ctx), PANELS_EXTRA,
                   length_for(ctx, needed - PANELS_EXTRA), needed - PANELS_EXTRA))
    if needed > most:
        return ("the narrative quotes %d spoken lines, which need at least %d panels of %s seconds "
                "(one panel has one speaker and speaks at most %d words), but this movie has at "
                "most %d (--panels %d plus up to %d more); rerun with --force-story --panels %d "
                "or more, or with longer clips (a larger --frames)"
                % (len(lines), needed, ctx.seconds, lib.dialogue_word_cap(secs, 1), most,
                   target_panels(ctx), PANELS_EXTRA, needed - PANELS_EXTRA))
    return None


def panel_range(ctx):
    """(fewest, most) beats a plan may have (soft panel count spec SPC1, D2): the target, or the
    panels the narrative's spoken lines need with one speaker each when that is more; and the
    target plus PANELS_EXTRA. character_lib is loaded only when the narrative quotes spoken
    lines."""
    lines = required_lines(ctx)
    needed = (lines_needed(_character_lib(ctx.ws), engine_seconds(ctx), lines,
                           declared_speakers(ctx)) if lines else 0)
    return max(target_panels(ctx), needed), most_panels(ctx)
```

**3.10.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    return "use climax."
```

with:

```python
    return "use climax."


def _plan_arc_rule(lo, hi):
    """The plan prompt's arc rule for a movie of lo to hi beats (soft panel count spec SPC5):
    _arc_rule(lo) from 3 beats up, else one ARC_COUNT_CLAUSES clause per count from lo up to 3."""
    if lo >= 3:
        return _arc_rule(lo)
    return "; ".join(ARC_COUNT_CLAUSES[k] for k in range(lo, min(hi, 3) + 1)) + "."
```

**3.11.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    """The exact plan prompt of RS7 (narrative dialogue fidelity spec QL6: the spoken-lines block
    after the narrative, the lines key and LINES_RULE when the narrative quotes spoken lines)."""
    lines = required_lines(ctx)
```

with:

```python
    """The exact plan prompt of RS7 (narrative dialogue fidelity spec QL6: the spoken-lines block
    after the narrative, the lines key and LINES_RULE when the narrative quotes spoken lines).
    Soft panel count spec SPC4: the beat count is lo to hi of panel_range; @@MIN_BEATS@@ is lo."""
    lines = required_lines(ctx)
    lo, hi = panel_range(ctx)
    target = target_panels(ctx)
```

**3.12.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    if lines and ctx.members:
        fixed = [{"id": "c%d" % i, "phrase": m.phrase, "cast_name": m.name}
                 for i, m in enumerate(ctx.members, start=1)]
        items = ["line %d to %s" % (n, cid) for n, cid
                 in enumerate(line_speakers(ctx.narrative, fixed), start=1) if cid]
```

with:

```python
    if lines and ctx.members:
        items = ["line %d to %s" % (n, cid) for n, cid
                 in enumerate(declared_speakers(ctx), start=1) if cid]
```

**3.13.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        ("@@ARC_RULE@@", _arc_rule(ctx.panels)),
```

with:

```python
        ("@@ARC_RULE@@", _plan_arc_rule(lo, hi)),
        ("@@BEAT_COUNT@@", "EXACTLY %d" % lo if lo == hi else "%d to %d" % (lo, hi)),
        ("@@PANEL_COUNT_RULE@@", "" if lo >= hi else (
            PANEL_COUNT_RULE % (target, PANEL_COUNT_MIN_CLAUSE % lo if lo > target else "", lo,
                                hi)
            + (PANEL_COUNT_LINES_SENTENCE if lines else ""))),
```

**3.14.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    scalars = [("@@STORY_ID@@", ctx.story_id), ("@@PANELS@@", str(ctx.panels)),
               ("@@SECONDS@@", ctx.seconds), ("@@MAX_CAST@@", str(MAX_CAST[ctx.mode])),
               ("@@LINE_WORDS@@", line_cap), ("@@MAX_STATIC@@", str(max_static(ctx.panels)))]
```

with:

```python
    scalars = [("@@STORY_ID@@", ctx.story_id), ("@@MIN_BEATS@@", str(lo)),
               ("@@SECONDS@@", ctx.seconds), ("@@MAX_CAST@@", str(MAX_CAST[ctx.mode])),
               ("@@LINE_WORDS@@", line_cap), ("@@MAX_STATIC@@", str(max_static(target)))]
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sp-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_soft_panel_count.py 2>&1 | tail -1
```

Expected: `9 passed`. Run the compile check with `FILES` = `story_engine.py tests/test_soft_panel_count.py`; expected: `compiled 2` twice. Then run the gate block with `N=1`.
- Expected: `GATE PASS`, `test_soft_panel_count 9, not passing 0`, `baseline failures still failing 2 of 2` and `OK 347/347`.
- The T1 lines of the expected-failure list may show as LOST; each is `listed`.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_soft_panel_count.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_soft_panel_count.py
git commit -m "feat(story): --panels is a target: the plan prompt asks for N to N+2 beats, lines need one speaker per panel, and the pre-flight stops only beyond N+2 (SPC1-SPC5, SPC12b; SPR2; SPT1a, SPT2-SPT5, SPT22, SPT23)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: P19 says whether the movie had room, and only the speaker's own exit counts (SPC12 a; Plan rulings SPR1, SPR2)

This task implements:
- SPC12 (a): `P19_NOTE` with a `%s` hint, `P19_ROOM_HINT` and `P19_CAP_HINT`. `exit_left_out_notes` picks the hint from `len(plan["beats"])` and `most_panels(ctx)`.
- Plan ruling SPR1 (coordinator addition a): `narrative_exit_after_last_line(narrative, cast=())` returns only an exit whose subject is the last line's speaker. It adds the helpers `EXIT_SUBJECT_PRONOUNS`, `_plain_words`, `_clause_tail` and `_bare`.
- Plan ruling SPR2 (coordinator addition b): `P19_ROOM_HINT_LENGTH` and `P19_CAP_HINT_LENGTH`, used when `ctx.length` is not `None`.

Tests: SPT1 (P19 part: `test_spt1b_p19_constants`), SPT13, `test_spr2b_...`, `test_spr1a_...` and `test_spr1b_...`.

**Files:**
- Modify: `story_engine.py`, the SF-A1 block from `P19_NOTE` to the end of `exit_left_out_notes` (`:1638-1670`).
- Modify: `tests/test_soft_panel_count.py` (append).

**Interfaces:**
- Consumes: Task 1's `most_panels`, `target_panels` and `length_for`; the existing `EXIT_RE`, `QUOTE_RE`, `classify_quotes`, `line_words`, `line_speakers`, `_mentions`, `_speech_verb_at`, `_LINE_WORD_RE`, `_CLAUSE_BREAK_RE`, `_QUOTE_EDGE_CHARS`, `CLAUSE_STOP_WORDS` and `_q`; the `_Run.go` call `exit_left_out_notes(ctx, plan)` (unchanged).
- Produces:
  - `P19_NOTE`, a `%` format of `(quoted exit words, hint)`;
  - `P19_ROOM_HINT` (`% (most, n + 1)`), `P19_CAP_HINT` (`% (most, target, n + 1)`), `P19_ROOM_HINT_LENGTH` (`% (most, seconds_str, n + 1)`) and `P19_CAP_HINT_LENGTH` (`% (most, target, seconds_str, n + 1)`);
  - `narrative_exit_after_last_line(narrative, cast=()) -> str or None`. Task 3's `panel_count_notes` calls it with `plan["cast"]`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_spt1b_p19_constants`, `test_spt13_the_p19_hints`, `test_spr2b_the_p19_hint_names_length_when_length_sized_the_movie`, `test_spr1a_the_exit_subject_rule` and `test_spr1b_p19_ignores_an_exit_by_anyone_else`.

Edit `tests/test_soft_panel_count.py` (append): replace this text, the file's last lines, which occurs exactly once:

```python
                                       "and at least one beat is climax.")
    assert se._plan_arc_rule(4, 4) == se._arc_rule(4)
    assert se._plan_arc_rule(2, 2) == ARC_COUNT_CLAUSES[2] + "."
```

with:

```python
                                       "and at least one beat is climax.")
    assert se._plan_arc_rule(4, 4) == se._arc_rule(4)
    assert se._plan_arc_rule(2, 2) == ARC_COUNT_CLAUSES[2] + "."


# --- SPT1 (Task 2 part), SPT13: the P19 hints (SPC12 a; plan ruling SPR2) ---------------------

P19_NOTE = ("plan: P19 exit left out: the narrative's exit after its last spoken line (%s) was "
            "left out, because that line is in the last beat and a speaking beat never shows its "
            "speaker leave; %s")
P19_ROOM_HINT = ("the planner could have added a beat for it (this movie may have up to %d), so "
                 "rerun with --force-story, or rerun with --force-story --panels %d to keep it")
P19_CAP_HINT = ("this movie already has the %d panels a target of %d allows, so rerun with "
                "--force-story --panels %d to keep it")
P19_ROOM_HINT_LENGTH = ("the planner could have added a beat for it (this movie may have up to "
                        "%d), so rerun with --force-story, or rerun with --force-story --length "
                        "%s (a target of %d panels) to keep it")
P19_CAP_HINT_LENGTH = ("this movie already has the %d panels a target of %d allows, so rerun "
                       "with --force-story --length %s (a target of %d panels) to keep it")


def test_spt1b_p19_constants():
    assert se.P19_NOTE == P19_NOTE
    assert se.P19_ROOM_HINT == P19_ROOM_HINT
    assert se.P19_CAP_HINT == P19_CAP_HINT
    assert se.P19_ROOM_HINT_LENGTH == P19_ROOM_HINT_LENGTH
    assert se.P19_CAP_HINT_LENGTH == P19_CAP_HINT_LENGTH
    assert se.EXIT_SUBJECT_PRONOUNS == (["he"], ["she"], ["they"])
    for hint in (P19_ROOM_HINT, P19_CAP_HINT):
        assert "--force-story --panels %d" in hint
    for hint in (P19_ROOM_HINT_LENGTH, P19_CAP_HINT_LENGTH):
        assert "--force-story --length %s" in hint and "--panels" not in hint
    assert "--panels" not in P19_NOTE


def _p19_plan(ws, mode, target, lines, narrative=HOCKEY, **kw):
    """(ctx, normalised plan) for --panels target and len(lines) beats: beat k says lines[k - 1],
    spoken by the courier (c1) when it has lines."""
    ctx = seu.make_ctx(se, ws, mode=mode, panels=target, narrative=narrative,
                       narration=kw.pop("narration", "speech"), **kw)
    raw = seu.plan_json(mode, len(lines))
    for beat, numbers in zip(raw["beats"], lines):
        beat.update(lines=list(numbers), speaker="c1" if numbers else "")
    plan, _shape = se.normalize_plan(ctx, raw)
    return ctx, plan


def test_spt13_the_p19_hints(ws):
    skate = "'skates away'"
    rows = (
        ("chained", 2, [[1], [2]], [P19_NOTE % (skate, P19_ROOM_HINT % (4, 3))]),
        ("chained", 1, [[1], [], [2]], [P19_NOTE % (skate, P19_CAP_HINT % (3, 1, 4))]),
        ("chained", 2, [[1], [2], []], []),
    )
    for mode, target, lines, want in rows:
        ctx, plan = _p19_plan(ws, mode, target, lines)
        assert se.exit_left_out_notes(ctx, plan) == want, (target, lines)
    # Every shot prompt format SFT24 row, its expected note rewritten to the SPC12 hint.
    sft24 = (
        ("chained", [[1], [2]], {}, [P19_NOTE % (skate, P19_ROOM_HINT % (4, 3))]),
        ("chained", [[1, 2]], {}, [P19_NOTE % (skate, P19_ROOM_HINT % (3, 2))]),
        ("shots", [[1], [2], []], {}, []),
        ("shots", [[1], [], [2]], {}, [P19_NOTE % (skate, P19_ROOM_HINT % (5, 4))]),
        ("chained", [[1], [2]], {"narration": False}, []),
        ("chained", [[1], []], {}, []),
        ("chained", [[1], [2]], {"narrative": LINES_NARRATIVE}, []),
        ("shots", [[1], [], [2]], {"narrative": LINES_NARRATIVE}, []),
    )
    for mode, lines, kw, want in sft24:
        ctx, plan = _p19_plan(ws, mode, len(lines), lines, **kw)
        assert se.exit_left_out_notes(ctx, plan) == want, (mode, lines, kw)
    violation = se.parse_violation(P19_NOTE % ("'x'", "y"))
    assert (violation["id"], violation["name"], violation["scope"], violation["index"]) == (
        "P19", "exit left out", "plan", None)


def test_spr2b_the_p19_hint_names_length_when_length_sized_the_movie(ws):
    clip = 145 / 24.0
    ctx, plan = _p19_plan(ws, "chained", 2, [[1], [2]], length=12.0, clip_seconds=clip)
    assert se.exit_left_out_notes(ctx, plan) == [
        P19_NOTE % ("'skates away'", P19_ROOM_HINT_LENGTH % (4, "18.1", 3))]
    ctx, plan = _p19_plan(ws, "chained", 2, [[1], [], [], [2]], length=12.0, clip_seconds=clip)
    notes = se.exit_left_out_notes(ctx, plan)
    assert notes == [P19_NOTE % ("'skates away'", P19_CAP_HINT_LENGTH % (4, 2, "30.2", 5))]
    assert "--panels" not in notes[0]
    assert (round(18.1 / clip), round(30.2 / clip)) == (3, 5)


# --- Plan ruling SPR1: the exit counts only when its subject is the last line's speaker -------

KYRA_RONIN_CAST = [
    {"id": "c1", "phrase": "the woman in grey", "descriptor": "a woman", "cast_name": "Kyra"},
    {"id": "c2", "phrase": "the ronin", "descriptor": "a man", "cast_name": "ronin"}]


def test_spr1a_the_exit_subject_rule():
    rows = (
        (HOCKEY, (), "skates away"),
        (LINES_NARRATIVE, (), None),
        ('Kyra says, "Go." She walks off.', (), "walks off"),
        ('Kyra walks off. Kyra says, "Go."', (), None),
        ('Kyra says, "Go," and the ronin leaves the frame.', (), None),
        ('Kyra says, "Go." Later the crowd says, "Yes." Kyra turns away.', (), "turns away"),
        ('A sign reads "Closed". Kyra walks away.', (), None),
        ('Kyra says, "Go." She pushes off from the kerb.', (), None),
        ('Kyra says, “Go.” She skates away.', (), "skates away"),
        ('The skater says "Go." The crowd drifts away.', (), None),
        ('The skater says "Go." The puck moves off the ice.', (), None),
        ('The skater says "Go." The crowd drifts away, and she skates off.', (), "skates off"),
        ('The skater says "Go." Then the skater slowly skates away.', (), "skates away"),
        ('Holly says "Go." Then Molly walks off.', (), None),
        ('Holly says "Go." Then Holly walks off.', (), "walks off"),
        ('Kyra says, "Go," and walks off.', (), "walks off"),
        ('"Go," Kyra says, and she slowly walks off.', (), "walks off"),
        ('Kyra says, "Go." Her ronin walks off.', (), None),
        ('Near the top Kyra turns and says, "Go." Kyra walks off.', (), None),
        ('Near the top Kyra turns and says, "Go." Kyra walks off.', KYRA_RONIN_CAST, "walks off"),
        ('Kyra says, "Go." The woman in grey walks off.', KYRA_RONIN_CAST, "walks off"),
        ('Kyra says, "Go." The ronin walks off.', KYRA_RONIN_CAST, None),
    )
    for narrative, cast, want in rows:
        assert se.narrative_exit_after_last_line(narrative, cast) == want, (narrative, cast)
    assert se.narrative_exit_after_last_line(HOCKEY) == "skates away"


def test_spr1b_p19_ignores_an_exit_by_anyone_else(ws):
    for narrative, want in (
            ('The skater says "Go." The puck moves off the ice.', []),
            ('The skater says "Go." The crowd drifts away.', []),
            ('The skater says "Go." The crowd drifts away, and she skates off.',
             [P19_NOTE % ("'skates off'", P19_ROOM_HINT % (3, 2))])):
        ctx, plan = _p19_plan(ws, "chained", 1, [[1]], narrative=narrative)
        assert se.exit_left_out_notes(ctx, plan) == want, narrative
```

- [ ] **Step 2: Run the tests to verify that they fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sp-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_soft_panel_count.py 2>&1 | tail -1
```

Expected: the summary starts `5 failed, 9 passed`. The five fail on the missing hint constants and on the old `P19_NOTE` and exit rule.

- [ ] **Step 3: Implement SPC12 (a) with SPR1 and SPR2.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
# Shot prompt format spec amendment SF-A1: the narrative's exit after its last spoken line is
# left out when that line is in the last beat.
P19_NOTE = ("plan: P19 exit left out: the narrative's exit after its last spoken line (%s) was "
            "left out, because that line is in the last beat and a speaking beat never shows its "
            "speaker leave; rerun with --force-story --panels %d to keep it")


def narrative_exit_after_last_line(narrative):
    """The EXIT_RE words (lower case, whitespace collapsed) of the first exit in the narrative
    text after the closing quote of its last spoken line, or None (SF-A1). The quotes are paired
    as in line_speakers: curly quotes count as straight ones, and classify_quotes decides which
    quote is spoken."""
    text = narrative.replace("“", '"').replace("”", '"')
    spoken = [match for match, (inner, said) in zip(QUOTE_RE.finditer(text),
                                                    classify_quotes(narrative))
              if said and line_words(inner)]
    if not spoken:
        return None
    found = EXIT_RE.search(text[spoken[-1].end():])
    return " ".join(found.group(0).lower().split()) if found else None


def exit_left_out_notes(ctx, plan):
    """[P19_NOTE] when the narrative has an exit after its last spoken line and the beat that
    says that line is the last beat, else [] (SF-A1)."""
    lines = plan.get("spoken_lines") or []
    if ctx.narration is False or not lines:
        return []
    found = narrative_exit_after_last_line(ctx.narrative)
    last = plan["beats"][-1] if plan["beats"] else None
    if found is None or last is None or len(lines) not in last.get("lines", []):
        return []
    return [P19_NOTE % (_q(found), ctx.panels + 1)]
```

with:

```python
# Shot prompt format spec amendment SF-A1: the narrative's exit after its last spoken line is
# left out when that line is in the last beat; soft panel count spec SPC12.
P19_NOTE = ("plan: P19 exit left out: the narrative's exit after its last spoken line (%s) was "
            "left out, because that line is in the last beat and a speaking beat never shows its "
            "speaker leave; %s")
P19_ROOM_HINT = ("the planner could have added a beat for it (this movie may have up to %d), so "
                 "rerun with --force-story, or rerun with --force-story --panels %d to keep it")
P19_CAP_HINT = ("this movie already has the %d panels a target of %d allows, so rerun with "
                "--force-story --panels %d to keep it")
# Plan ruling SPR2: the same hints when --length sized the movie; the panel count is information.
P19_ROOM_HINT_LENGTH = ("the planner could have added a beat for it (this movie may have up to "
                        "%d), so rerun with --force-story, or rerun with --force-story --length "
                        "%s (a target of %d panels) to keep it")
P19_CAP_HINT_LENGTH = ("this movie already has the %d panels a target of %d allows, so rerun "
                       "with --force-story --length %s (a target of %d panels) to keep it")
# Plan ruling SPR1: an exit after the last spoken line counts only when its subject is that
# line's speaker.
EXIT_SUBJECT_PRONOUNS = (["he"], ["she"], ["they"])


def _plain_words(text):
    """line_words of text without its adverbs: the words that end in "ly" and begin with a
    lower-case letter (plan ruling SPR1)."""
    return [w.lower() for w in _LINE_WORD_RE.findall(text.replace("’", "'").replace("‘", "'"))
            if not (w.endswith("ly") and w[:1].islower())]


def _clause_tail(text):
    """The _plain_words of text's last _CLAUSE_BREAK_RE piece after that piece's last
    CLAUSE_STOP_WORDS word (plan ruling SPR1)."""
    words = _plain_words(_CLAUSE_BREAK_RE.split(text)[-1])
    stops = [j for j, w in enumerate(words) if w in CLAUSE_STOP_WORDS]
    return words[stops[-1] + 1:] if stops else words


def _bare(words):
    """words without one leading "the", "a" or "an" (plan ruling SPR1)."""
    return words[1:] if words[:1] in (["the"], ["a"], ["an"]) else words


def narrative_exit_after_last_line(narrative, cast=()):
    """The EXIT_RE words (lower case, whitespace collapsed) of the first exit in the narrative
    text after the closing quote of its last spoken line whose subject is that line's speaker,
    or None (SF-A1; plan ruling SPR1). The quotes are paired as in line_speakers: curly quotes
    count as straight ones, and classify_quotes decides which quote is spoken. An exit's subject
    is the _clause_tail of the text from that closing quote to the exit. It is the speaker's when
    it is empty (the line's own sentence goes on), is he, she or they, or equals, without a
    leading article, a name of the speaker: the words before the speech verb in the _clause_tail
    of the text that leads up to the line, or a phrase or library name of the entry of cast (plan
    cast entries) that line_speakers gives the line."""
    text = narrative.replace("“", '"').replace("”", '"')
    matches = list(QUOTE_RE.finditer(text))
    spoken = [i for i, (match, (inner, said)) in enumerate(zip(matches,
                                                               classify_quotes(narrative)))
              if said and line_words(inner)]
    if not spoken:
        return None
    i = spoken[-1]
    lead = _clause_tail(text[matches[i - 1].end() if i else 0:matches[i].start()]
                        .rstrip(_QUOTE_EDGE_CHARS))
    verbs = [p for p in range(len(lead)) if _speech_verb_at(lead, p)]
    names = [_bare(lead[:verbs[0]])] if verbs and _bare(lead[:verbs[0]]) else []
    who = line_speakers(narrative, list(cast))[-1] if cast else None
    names += [_bare(words) for cid, words in _mentions(list(cast)) if who and cid == who]
    tail = text[matches[i].end():]
    for found in EXIT_RE.finditer(tail):
        subject = _clause_tail(tail[:found.start()])
        if not subject or subject in EXIT_SUBJECT_PRONOUNS or _bare(subject) in names:
            return " ".join(found.group(0).lower().split())
    return None


def exit_left_out_notes(ctx, plan):
    """[P19_NOTE] when the narrative has an exit after its last spoken line and the beat that
    says that line is the last beat, else [] (SF-A1); the hint says whether the movie had room
    for one more beat, and always names --force-story (soft panel count spec SPC12), and it names
    --length instead of --panels when --length sized the movie (plan ruling SPR2)."""
    lines = plan.get("spoken_lines") or []
    if ctx.narration is False or not lines:
        return []
    found = narrative_exit_after_last_line(ctx.narrative, plan["cast"])
    last = plan["beats"][-1] if plan["beats"] else None
    if found is None or last is None or len(lines) not in last.get("lines", []):
        return []
    n, most = len(plan["beats"]), most_panels(ctx)
    hint = (P19_ROOM_HINT % (most, n + 1) if n < most
            else P19_CAP_HINT % (most, target_panels(ctx), n + 1))
    if ctx.length is not None:
        hint = (P19_ROOM_HINT_LENGTH % (most, length_for(ctx, n + 1), n + 1) if n < most
                else P19_CAP_HINT_LENGTH % (most, target_panels(ctx), length_for(ctx, n + 1),
                                            n + 1))
    return [P19_NOTE % (_q(found), hint)]
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sp-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_soft_panel_count.py 2>&1 | tail -1
```

Expected: `14 passed`. Run the compile check with `FILES` = `story_engine.py tests/test_soft_panel_count.py`; expected: `compiled 2` twice. Then run the gate block with `N=2`. Expected: `GATE PASS`, `test_soft_panel_count 14, not passing 0`, `baseline failures still failing 2 of 2` and `OK 347/347`.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_soft_panel_count.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_soft_panel_count.py
git commit -m "feat(story): the P19 hint says whether the movie had room for the exit and how to keep it, and only the speaker's own exit counts (SPC12a; SPR1, SPR2; SPT1b, SPT13)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The run lives with the plan's beat count, and P20 says why (SPC6-SPC9, SPC11; Plan ruling SPR3)

This task implements:
- SPC6: `normalize_plan` writes `panels_target`, and sets `panels` to the beat count.
- SPC7: P1 accepts `lo..hi`, and `n = len(beats)` in `plan_checks`. In `lora_checks`, Plan ruling SPR3 makes `n = plan["panels"]`.
- SPC8: `_checks_doc` adds `panels_target`.
- SPC9: in `_Run.__init__`, the cap uses `most_panels` and the doc carries `panels_target`. `plan_round` budgets use `most_panels`. In `go`, the ctx is swapped after the plan, the cap and `panel_calls` are reset, run.json is updated, and P20 is called and printed.
- SPC11: `P20_*` and `panel_count_notes`. By SPR1 it passes `plan["cast"]` to the exit rule.

Tests: SPT1 (P20 part: `test_spt1c_p20_constants`), SPT6, SPT7, SPT8, SPT9, SPT10, SPT11, SPT12, SPT19 and SPT24, plus `test_spr3_...` and Review Focus 1, 3 and 5.

**Files:**
- Modify: `story_engine.py`. The edits go to `normalize_plan` (`:1105-1175`), `plan_checks` (`:1830-1845`), `lora_checks` (`:2036-2045`), `_checks_doc` (`:4070-4077`), `_Run.__init__` (`:4083-4108`), `plan_round` (`:4157-4158`) and `go` (`:4383-4386`). `P20_*` and `panel_count_notes` go after Task 2's `exit_left_out_notes`.
- Modify: `tests/test_soft_panel_count.py` (append).

**Interfaces:**
- Consumes: Task 1's `panel_range`, `target_panels`, `most_panels`, `speaker_runs` and `lines_needed`; Task 2's `narrative_exit_after_last_line(narrative, cast)`; the existing `wall_clock_cap`, `plan_max_tokens`, `plan_timeout`, `assign_missing_lines`, `cap_static_cameras` and `exit_left_out_notes`.
- Produces:
  - `plan["panels"] == len(plan["beats"])` and `plan["panels_target"]`, in `plan.json`, `story_checks.json` (`panels_target`) and run.json (`panels_target`);
  - in `_Run.go`, after the plan, `self.ctx.panels == len(plan["beats"])` and `self.ctx.panels_target == N`;
  - `P20_NOTE` (`% (n, n - target, target, reasons)`), `P20_LINES_REASON` (`% (lines, panels, seconds)`), `P20_SPEAKER_REASON` (`% (runs, panels)`), `P20_EXIT_REASON` (`% quoted words`) and `P20_OTHER_REASON`;
  - `panel_count_notes(ctx, plan) -> [str]`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_spt1c_p20_constants`, `test_spt6_p1_and_the_beat_range_checks`, `test_spr3_lora_checks_use_the_plans_panel_count`, `test_spt7_normalize_plan`, `test_spt8_e2e_one_beat_added`, `test_spt9_e2e_the_target_met`, `test_spt10_e2e_out_of_range`, `test_spt11_e2e_the_hockey_exit`, `test_spt12_the_p20_reasons`, `test_spt19_the_static_cap_uses_the_effective_count`, `test_spt24_e2e_the_range_with_speakers`, `test_review_focus_1_lines_that_need_one_more_panel_are_planned_not_refused`, `test_review_focus_3_a_no_stills_movie_gets_its_added_panel` and `test_review_focus_5_an_added_panel_can_be_re_asked`.

Edit `tests/test_soft_panel_count.py` (append): replace this text, the file's last lines, which occurs exactly once:

```python
             [P19_NOTE % ("'skates off'", P19_ROOM_HINT % (3, 2))])):
        ctx, plan = _p19_plan(ws, "chained", 1, [[1]], narrative=narrative)
        assert se.exit_left_out_notes(ctx, plan) == want, narrative
```

with:

```python
             [P19_NOTE % ("'skates off'", P19_ROOM_HINT % (3, 2))])):
        ctx, plan = _p19_plan(ws, "chained", 1, [[1]], narrative=narrative)
        assert se.exit_left_out_notes(ctx, plan) == want, narrative


# --- SPT1 (Task 3 part): the P20 constants (SPC11) --------------------------------------------

P20_NOTE = ("plan: P20 panel count: this movie has %d panels, %d more than its target of %d, "
            "because %s")
P20_LINES_REASON = "the narrative's %d spoken lines need at least %d panels of %s seconds"
P20_SPEAKER_REASON = ("the narrative's spoken lines come in %d runs by different speakers, which "
                      "need at least %d panels with one speaker each")
P20_EXIT_REASON = "the narrative's exit after its last spoken line (%s) has a later beat"
P20_OTHER_REASON = "the story planner needed them for the narrative's action"
CAST2 = [{"id": "c1", "phrase": "x", "descriptor": "a woman"},
         {"id": "c2", "phrase": "y", "descriptor": "a man"}]


def test_spt1c_p20_constants():
    assert se.P20_NOTE == P20_NOTE
    assert se.P20_LINES_REASON == P20_LINES_REASON
    assert se.P20_SPEAKER_REASON == P20_SPEAKER_REASON
    assert se.P20_EXIT_REASON == P20_EXIT_REASON
    assert se.P20_OTHER_REASON == P20_OTHER_REASON
    for text in (P20_NOTE, P20_LINES_REASON, P20_SPEAKER_REASON, P20_EXIT_REASON,
                 P20_OTHER_REASON):
        assert "--panels" not in text and "--length" not in text


def _normalized(ctx, raw):
    plan, _shape = se.normalize_plan(ctx, raw)
    return plan


def _p1(hard):
    return [m for m in hard if " P1 " in m]


# --- SPT6, SPT7: P1, the beat-range checks and normalize_plan (SPC6, SPC7; plan ruling SPR3) ---

def test_spt6_p1_and_the_beat_range_checks(ws, tmp_path):
    ctx = seu.make_ctx(se, ws, panels=3)
    for n in (3, 4, 5):
        hard, advisory = se.plan_checks(ctx, _normalized(ctx, seu.plan_json("chained", n)))
        assert [m for m in hard + advisory if " P1 " in m or " P5 " in m or " P6 " in m] == [], n
    for n in (2, 6):
        hard = se.plan_checks(ctx, _normalized(ctx, seu.plan_json("chained", n)))[0]
        assert "plan: P1 beat count: expected 3 to 5 beats, found %d" % n in hard, n
    eight = seu.make_ctx(se, ws, panels=2, narrative=EIGHT)
    hard = se.plan_checks(eight, _normalized(eight, seu.plan_json("chained", 3)))[0]
    assert "plan: P1 beat count: expected exactly 4 beats, found 3" in hard
    raw = seu.plan_json("chained", 4)
    raw["beats"][3]["index"] = 7
    hard = se.plan_checks(ctx, _normalized(ctx, raw))[0]
    assert _p1(hard) == [
        "plan: P1 beat count: beat 4 has index 7; beats must be numbered 1 to 4 in order"]
    files = str(tmp_path / "files")
    entry = seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion")
    lctx = seu.make_ctx(se, ws, panels=3, catalog={"schema_version": 1, "entries": [entry]})
    compatible = dict((e["id"], e) for e in se.compatible_entries(lctx))
    for key, want in (("5", []), ("6", ["plan: L1 catalog id: per_beat key '6' is not a beat "
                                        "number from 1 to 5"])):
        raw = seu.plan_json("chained", 5)
        raw["loras"] = {"global": [], "per_beat": {key: [{"id": "fast-motion", "strength": 0.7}]},
                        "stills": []}
        hard = se.lora_checks(lctx, _normalized(lctx, raw), compatible, {"fast-motion": entry})[0]
        assert [m for m in hard if " L1 " in m] == want, key


def test_spr3_lora_checks_use_the_plans_panel_count(ws, tmp_path):
    files = str(tmp_path / "files")
    entry = seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion")
    ctx = seu.make_ctx(se, ws, panels=3, catalog={"schema_version": 1, "entries": [entry]})
    compatible = dict((e["id"], e) for e in se.compatible_entries(ctx))
    saved = {"schema": "ltx-movie.plan.v1", "mode": "chained", "panels": 3, "title": "T",
             "logline": "x", "cast": [], "locations": [], "props": [], "beats": [],
             "loras": {"global": [], "per_beat": {"2": [{"id": "fast-motion", "strength": 0.7}]},
                       "stills": []}}
    assert se.lora_checks(ctx, saved, compatible, {"fast-motion": entry})[0] == []


def test_spt7_normalize_plan(ws):
    ctx = seu.make_ctx(se, ws, panels=3)
    plan = _normalized(ctx, seu.plan_json("chained", 4))
    assert (plan["panels"], plan["panels_target"]) == (4, 3)
    assert list(plan)[:6] == ["schema", "story_id", "mode", "panels", "panels_target", "seconds"]
    swapped = seu.make_ctx(se, ws, panels=4, panels_target=3)
    assert _normalized(swapped, seu.plan_json("chained", 4))["panels_target"] == 3


# --- SPT8-SPT10: the run with one beat added, the target met, and out of range (SPC9) --------

def _messages(story_dir, key="advisory"):
    return [entry["message"] for entry in _read_json(story_dir, "story_checks.json")[key]]


def _run_story(ws, tmp_path, monkeypatch, plan, panel, critic=(), **ctx_kw):
    """(rc, advisories, ctx, agent log) of one se.run with the fake agent scripted."""
    log = seu.script_agent(monkeypatch, tmp_path, plan=plan, panel=panel, critic=list(critic))
    ctx = seu.make_ctx(se, ws, **ctx_kw)
    rc, advisories = se.run(ctx)
    return rc, advisories, ctx, seu.agent_log(log)


def test_spt8_e2e_one_beat_added(ws, tmp_path, monkeypatch, capsys):
    capsys.readouterr()
    rc, advisories, ctx, log = _run_story(
        ws, tmp_path, monkeypatch, [seu.answer(seu.plan_json("chained", 4))],
        panel_script("chained", 4), story_id="spt8", panels=3)
    out = capsys.readouterr().out
    note = P20_NOTE % (4, 1, 3, P20_OTHER_REASON)
    assert rc == 0
    assert [r["stage"] for r in log][:5] == ["plan", "panel", "panel", "panel", "panel"]
    with open(os.path.join(ctx.story_dir, "story_rounds", "round_0", "panel_04_prompt_1.txt"),
              encoding="utf-8") as f:
        assert "You are writing panel 4 of 4 " in f.read()
    assert len(manifest._parse_prompts_md(os.path.join(ctx.story_dir, "story.md"))[1]) == 4
    plan = _read_json(ctx.story_dir, "plan.json")
    assert (plan["panels"], plan["panels_target"]) == (4, 3)
    assert note in plan["speech_notes"]
    checks = _read_json(ctx.story_dir, "story_checks.json")
    assert (checks["panels"], checks["panels_target"]) == (4, 3)
    assert _messages(ctx.story_dir).count(note) == 1
    run = _read_json(os.path.join(ctx.story_dir, "story_rounds"), "run.json")
    assert (run["panels"], run["panels_target"]) == (4, 3)
    assert run["budgets"]["wall_clock_s"] == se.wall_clock_cap(4)
    assert advisories.count(note) == 1
    assert ("\n" + note + "\n") in out
    assert out.index("\n" + note + "\n") < out.index("panel 1/4: call 1")


def test_spt9_e2e_the_target_met(ws, tmp_path, monkeypatch, capsys):
    capsys.readouterr()
    rc, advisories, ctx, _log = _run_story(
        ws, tmp_path, monkeypatch, [seu.answer(seu.plan_json("chained", 3))],
        panel_script("chained", 3), story_id="spt9", panels=3)
    out = capsys.readouterr().out
    assert rc == 0
    plan = _read_json(ctx.story_dir, "plan.json")
    checks = _read_json(ctx.story_dir, "story_checks.json")
    run = _read_json(os.path.join(ctx.story_dir, "story_rounds"), "run.json")
    for doc in (plan, checks, run):
        assert (doc["panels"], doc["panels_target"]) == (3, 3)
    assert " P20 " not in out
    assert [a for a in advisories if " P20 " in a] == []
    assert [m for m in plan["speech_notes"] if " P20 " in m] == []


def test_spt10_e2e_out_of_range(ws, tmp_path, monkeypatch, capsys):
    six = seu.answer(seu.plan_json("chained", 6))
    capsys.readouterr()
    rc, _advisories, _ctx, log = _run_story(ws, tmp_path, monkeypatch, [six, six], {},
                                            story_id="spt10", panels=3)
    assert rc == 1
    line = "  - plan: P1 beat count: expected 3 to 5 beats, found 6"
    assert capsys.readouterr().err.splitlines()[1] == line
    assert line.strip()[2:] in log[1]["argv"][-1]


# --- SPT11: the hockey exit gets its beat, or P19 says how to keep it ------------------------

def _hockey_panel(k, motion):
    reply = {"title": "Rink Part %d" % k, "motion": motion}
    if k == 1:
        reply["image"] = seu.panel_json("chained", 1)["image"]
    return seu.answer(reply)


def test_spt11_e2e_the_hockey_exit(ws, tmp_path, monkeypatch):
    raw = seu.plan_json("chained", 3)
    raw["beats"][0].update(speaker="c1", lines=[1])
    raw["beats"][1].update(speaker="c1", lines=[2])
    raw["beats"][2].update(speaker="", lines=[],
                           action="the hockey player skates away across the ice toward the far "
                                  "boards")
    panel = {"1": [_hockey_panel(1, "The courier glides toward the camera at real-time speed, "
                                    "his face to the lens.")],
             "2": [_hockey_panel(2, "The courier carves a hard stop at real-time speed, a big "
                                    "bright spray of ice in the air.")],
             "3": [_hockey_panel(3, "The courier skates away across the ice toward the far "
                                    "boards at real-time speed.")]}
    rc, advisories, ctx, _log = _run_story(ws, tmp_path, monkeypatch, [seu.answer(raw)], panel,
                                           story_id="spt11a", panels=2, narration="speech",
                                           narrative=HOCKEY)
    assert rc == 0
    assert [a for a in advisories if " P20 " in a] == [
        P20_NOTE % (3, 1, 2, P20_EXIT_REASON % "'skates away'")]
    assert [a for a in advisories if " P19 " in a] == []
    raw = seu.plan_json("chained", 2)
    raw["beats"][0].update(speaker="c1", lines=[1])
    raw["beats"][1].update(speaker="c1", lines=[2])
    rc, advisories, ctx, _log = _run_story(
        ws, tmp_path, monkeypatch, [seu.answer(raw)], {"1": panel["1"], "2": panel["2"]},
        story_id="spt11b", panels=2, narration="speech", narrative=HOCKEY)
    assert rc == 0
    assert [a for a in advisories if " P20 " in a] == []
    assert [a for a in advisories if " P19 " in a] == [
        P19_NOTE % ("'skates away'", P19_ROOM_HINT % (4, 3))]


# --- SPT12: the P20 reasons (SPC11; plan ruling SPR1) -----------------------------------------

def _lines_plan(ctx, lines, speakers=None, cast=None):
    """normalize_plan of a plan of len(lines) beats: beat k says lines[k - 1], spoken by
    speakers[k - 1] (default c1 when it has lines), cast [its speaker] when cast is given."""
    raw = seu.plan_json(ctx.mode, len(lines), cast=cast)
    for k, (beat, numbers) in enumerate(zip(raw["beats"], lines)):
        who = speakers[k] if speakers else ("c1" if numbers else "")
        beat.update(lines=list(numbers), speaker=who)
        if cast is not None and who:
            beat["cast"] = [who]
    return _normalized(ctx, raw)


def test_spt12_the_p20_reasons(ws, story_env):
    words = P20_LINES_REASON % (4, 4, "6")
    ctx = seu.make_ctx(se, ws, panels=3, narrative=EIGHT)
    assert se.panel_count_notes(ctx, _lines_plan(ctx, [[1], [2], [3], [4]])) == [
        P20_NOTE % (4, 1, 3, words)]
    ctx = seu.make_ctx(se, ws, panels=1, narrative=HOCKEY, narration="speech",
                       clip_seconds=145 / 24.0)
    assert se.panels_needed(lib, se.engine_seconds(ctx), se.spoken_lines(HOCKEY)) == 1
    assert se.panel_count_notes(ctx, _lines_plan(ctx, [[1, 2], [], []])) == [
        P20_NOTE % (3, 2, 1, P20_EXIT_REASON % "'skates away'")]
    ctx = seu.make_ctx(se, ws, panels=3, narrative=EIGHT + " He walks off.")
    assert se.panel_count_notes(ctx, _lines_plan(ctx, [[1], [2], [3], [4], []])) == [
        P20_NOTE % (5, 2, 3, words + " and " + P20_EXIT_REASON % "'walks off'")]
    ctx = seu.make_ctx(se, ws, panels=2, narrative=TURNS, members=_members(story_env))
    plan = _lines_plan(ctx, [[1], [2], [3], [4]], ["c1", "c2", "c1", "c2"],
                       cast=copy.deepcopy(CAST2))
    assert se.panel_count_notes(ctx, plan) == [P20_NOTE % (4, 2, 2, P20_SPEAKER_REASON % (4, 4))]
    ctx = seu.make_ctx(se, ws, panels=3)
    assert se.panel_count_notes(ctx, _normalized(ctx, seu.plan_json("chained", 3))) == []
    violation = se.parse_violation(P20_NOTE % (4, 1, 3, "x"))
    assert (violation["id"], violation["name"], violation["scope"], violation["index"]) == (
        "P20", "panel count", "plan", None)
    ctx = seu.make_ctx(se, ws, panels=1, narration="speech",
                       narrative='The skater says "Go." The crowd drifts away.')
    assert se.panel_count_notes(ctx, _lines_plan(ctx, [[1], []])) == [
        P20_NOTE % (2, 1, 1, P20_OTHER_REASON)]


# --- SPT19: the static cap after the ctx swap (D9) --------------------------------------------

def test_spt19_the_static_cap_uses_the_effective_count(ws, tmp_path, monkeypatch):
    raw = seu.plan_json("shots", 4)
    for beat in raw["beats"]:
        beat["camera"] = "static"
    rc, _advisories, ctx, _log = _run_story(ws, tmp_path, monkeypatch, [seu.answer(raw)],
                                            panel_script("shots", 4), story_id="spt19",
                                            mode="shots", panels=3)
    assert rc == 0
    plan = _read_json(ctx.story_dir, "plan.json")
    assert [b["camera"] for b in plan["beats"]] == ["slow push-in", "slow push-in", "static",
                                                    "static"]
    assert se.P18_NOTE % (1, 2, 4) in plan["speech_notes"]
    assert se.P18_NOTE % (2, 2, 4) in plan["speech_notes"]
    with open(os.path.join(ctx.story_dir, "story_rounds", "round_0", "plan_prompt.txt"),
              encoding="utf-8") as f:
        assert "so at most 1 in this movie" in f.read()


# --- SPT24: the range with speakers, end to end (SPC1, SPC7) ----------------------------------

def test_spt24_e2e_the_range_with_speakers(ws, tmp_path, monkeypatch, capsys, story_env):
    members = _members(story_env)

    def raw(n):
        plan = seu.plan_json("shots", n, cast=copy.deepcopy(CAST2))
        for k, beat in enumerate(plan["beats"]):
            who = ("c1", "c2")[k % 2]
            beat.update(cast=[who], speaker=who, lines=[k + 1])
        return plan

    phrases = ("the woman in grey", "the ronin")
    capsys.readouterr()
    rc, _a, _ctx, _log = _run_story(ws, tmp_path, monkeypatch, [seu.answer(raw(3))] * 2, {},
                                    story_id="spt24a", mode="shots", panels=2, members=members,
                                    narrative=TURNS)
    assert rc == 1
    assert "  - plan: P1 beat count: expected exactly 4 beats, found 3" in (
        capsys.readouterr().err.splitlines())
    panel = dict((str(k), [seu.answer(seu.panel_json("shots", k, phrases[(k - 1) % 2]))])
                 for k in range(1, 5))
    rc, advisories, _ctx, _log = _run_story(ws, tmp_path, monkeypatch, [seu.answer(raw(4))],
                                            panel, story_id="spt24b", mode="shots", panels=2,
                                            members=members, narrative=TURNS)
    assert rc == 0
    assert [a for a in advisories if " P20 " in a] == [
        P20_NOTE % (4, 2, 2, P20_SPEAKER_REASON % (4, 4))]


# --- Review Focus 1, 3, 5: lines that need one more panel, no_stills, an added panel re-asked -

def test_review_focus_1_lines_that_need_one_more_panel_are_planned_not_refused(
        ws, tmp_path, monkeypatch, capsys):
    one = seu.plan_json("chained", 1)
    one["beats"][0].update(speaker="c1", lines=[1, 2, 3])
    two = seu.plan_json("chained", 2)
    two["beats"][0].update(speaker="c1", lines=[1, 2])
    two["beats"][1].update(speaker="c1", lines=[3])
    capsys.readouterr()
    rc, advisories, ctx, log = _run_story(ws, tmp_path, monkeypatch,
                                          [seu.answer(one), seu.answer(two)],
                                          panel_script("chained", 2), story_id="rf1", panels=1,
                                          narrative=SIX_WORD_LINES)
    assert rc == 0
    assert [r["stage"] for r in log][:4] == ["plan", "plan", "panel", "panel"]
    assert "- plan: P1 beat count: expected 2 to 3 beats, found 1\n" in log[1]["argv"][-1]
    assert [a for a in advisories if " P20 " in a] == [
        P20_NOTE % (2, 1, 1, P20_LINES_REASON % (3, 2, "6"))]
    assert _read_json(ctx.story_dir, "plan.json")["panels"] == 2


def test_review_focus_3_a_no_stills_movie_gets_its_added_panel(ws, tmp_path, monkeypatch):
    rc, advisories, ctx, log = _run_story(
        ws, tmp_path, monkeypatch, [seu.answer(seu.plan_json("no_stills", 4))],
        panel_script("no_stills", 4), story_id="rf3", mode="no_stills", panels=3)
    assert rc == 0
    assert [r["panel"] for r in log if r["stage"] == "panel"][:4] == [1, 2, 3, 4]
    assert len(manifest._parse_prompts_md(os.path.join(ctx.story_dir, "story.md"))[1]) == 4
    assert [a for a in advisories if " P20 " in a] == [P20_NOTE % (4, 1, 3, P20_OTHER_REASON)]


def test_review_focus_5_an_added_panel_can_be_re_asked(ws, tmp_path, monkeypatch):
    panel = panel_script("chained", 4, p4=[{"answer": "not json"},
                                           seu.answer(seu.panel_json("chained", 4))])
    rc, _advisories, ctx, log = _run_story(ws, tmp_path, monkeypatch,
                                           [seu.answer(seu.plan_json("chained", 4))], panel,
                                           story_id="rf5", panels=3)
    assert rc == 0
    assert len([r for r in log if r["stage"] == "panel" and r["panel"] == 4]) == 2
    run = _read_json(os.path.join(ctx.story_dir, "story_rounds"), "run.json")
    assert len([c for c in run["calls"] if c["stage"] == "panel" and c["panel"] == 4]) == 2
```

- [ ] **Step 2: Run the tests to verify that they fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sp-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_soft_panel_count.py 2>&1 | tail -1
```

Expected: the summary starts `13 failed, 15 passed`. `test_spr3_...` passes already: it guards the old `n = ctx.panels` behaviour, which SPR3 keeps for a saved plan. The other 13 fail because P1 still rejects a bigger plan, and on the missing `panels_target` and `P20_*`.

- [ ] **Step 3: Implement SPC6-SPC9 and SPC11 with SPR3.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    list). Wrong-typed string fields become "" and are reported by plan_checks."""
    shape = []
    plan = {"schema": PLAN_SCHEMA, "story_id": ctx.story_id, "mode": ctx.mode,
            "panels": ctx.panels, "seconds": ctx.seconds, "narrative": ctx.narrative,
```

with:

```python
    list). Wrong-typed string fields become "" and are reported by plan_checks. plan["panels"] is
    the beat count and plan["panels_target"] the --panels target (soft panel count spec SPC6)."""
    shape = []
    plan = {"schema": PLAN_SCHEMA, "story_id": ctx.story_id, "mode": ctx.mode,
            "panels": ctx.panels, "panels_target": target_panels(ctx), "seconds": ctx.seconds,
            "narrative": ctx.narrative,
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    plan["beats"] = beats
    loras = raw.get("loras")
```

with:

```python
    plan["beats"] = beats
    plan["panels"] = len(beats)
    loras = raw.get("loras")
```

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    names; speaker attribution spec SA2); every other P message is advisory (dialogue spec
    6.3)."""
    hard, advisory = list(shape), []
    n = ctx.panels
    beats = plan["beats"]
    if len(beats) != n:
        hard.append("plan: P1 beat count: expected exactly %d beats, found %d" % (n, len(beats)))
    for i, beat in enumerate(beats):
```

with:

```python
    names; speaker attribution spec SA2); every other P message is advisory (dialogue spec
    6.3). P1 accepts lo to hi beats of panel_range (soft panel count spec SPC7)."""
    hard, advisory = list(shape), []
    beats = plan["beats"]
    n = len(beats)
    lo, hi = panel_range(ctx)
    if not lo <= n <= hi:
        hard.append("plan: P1 beat count: expected exactly %d beats, found %d" % (lo, n)
                    if lo == hi else
                    "plan: P1 beat count: expected %d to %d beats, found %d" % (lo, hi, n))
    for i, beat in enumerate(beats):
```

**3.4.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    if not ctx.auto_lora:
        return hard, advisory
    n = ctx.panels
    loras = plan["loras"]
```

with:

```python
    if not ctx.auto_lora:
        return hard, advisory
    # Soft panel count spec SPC7, plan ruling SPR3: the plan's own panel count, which is its beat
    # count (normalize_plan) and is also right for a saved plan.json without beats.
    n = plan["panels"]
    loras = plan["loras"]
```

**3.5.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    return {"schema": CHECKS_SCHEMA, "story_id": ctx.story_id, "mode": ctx.mode,
            "panels": ctx.panels, "checked_at": _utc(), "source": source,
```

with:

```python
    return {"schema": CHECKS_SCHEMA, "story_id": ctx.story_id, "mode": ctx.mode,
            "panels": ctx.panels, "panels_target": target_panels(ctx), "checked_at": _utc(),
            "source": source,
```

**3.6.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        self.cap = wall_clock_cap(ctx.panels)
        self.rounds_dir = os.path.join(ctx.story_dir, "story_rounds")
```

with:

```python
        self.cap = wall_clock_cap(most_panels(ctx))
        self.rounds_dir = os.path.join(ctx.story_dir, "story_rounds")
```

**3.7.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        self.doc = {"schema": RUN_SCHEMA, "story_id": ctx.story_id, "mode": ctx.mode,
                    "panels": ctx.panels, "started_at": _utc(), "finished_at": None,
```

with:

```python
        self.doc = {"schema": RUN_SCHEMA, "story_id": ctx.story_id, "mode": ctx.mode,
                    "panels": ctx.panels, "panels_target": target_panels(ctx),
                    "started_at": _utc(), "finished_at": None,
```

**3.8.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
            status, answer = self.agent(text, plan_max_tokens(ctx.panels),
                                        plan_timeout(ctx.panels), image=ctx.seed_agent_image)
```

with:

```python
            status, answer = self.agent(text, plan_max_tokens(most_panels(ctx)),
                                        plan_timeout(most_panels(ctx)), image=ctx.seed_agent_image)
```

**3.9.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        plan, self.shape, _hard = found
        plan["speech_notes"] += assign_missing_lines(ctx, plan)
        plan["speech_notes"] += cap_static_cameras(ctx, plan)
        plan["speech_notes"] += exit_left_out_notes(ctx, plan)
```

with:

```python
        plan, self.shape, _hard = found
        # Soft panel count spec SPC9, D1: from here on the movie has the plan's beat count.
        ctx = self.ctx = ctx._replace(panels=len(plan["beats"]), panels_target=target_panels(ctx))
        self.cap = wall_clock_cap(ctx.panels)
        self.doc["panels"] = ctx.panels
        self.doc["budgets"]["wall_clock_s"] = self.cap
        self.panel_calls = dict((k, 0) for k in range(1, ctx.panels + 1))
        self.write_run()
        plan["speech_notes"] += assign_missing_lines(ctx, plan)
        plan["speech_notes"] += cap_static_cameras(ctx, plan)
        plan["speech_notes"] += exit_left_out_notes(ctx, plan)
        count_notes = panel_count_notes(ctx, plan)
        plan["speech_notes"] += count_notes
        for note in count_notes:
            print(note)
```

**3.10.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    return [P19_NOTE % (_q(found), hint)]
```

with:

```python
    return [P19_NOTE % (_q(found), hint)]


# Soft panel count spec SPC11, D4: tell the user when the movie has more panels than its target,
# and why.
P20_NOTE = ("plan: P20 panel count: this movie has %d panels, %d more than its target of %d, "
            "because %s")
P20_LINES_REASON = "the narrative's %d spoken lines need at least %d panels of %s seconds"
P20_SPEAKER_REASON = ("the narrative's spoken lines come in %d runs by different speakers, which "
                      "need at least %d panels with one speaker each")
P20_EXIT_REASON = "the narrative's exit after its last spoken line (%s) has a later beat"
P20_OTHER_REASON = "the story planner needed them for the narrative's action"


def panel_count_notes(ctx, plan):
    """[P20_NOTE] when the plan has more beats than the target, else [] (SPC11). Reasons, in order
    and joined with " and ": the lines need more panels than the target by words; the lines need
    more panels than that because of speaker changes (speakers from plan["cast"]); the narrative's
    exit after its last spoken line (plan ruling SPR1: its speaker's) follows the beat that says
    that line. With none, P20_OTHER_REASON."""
    n, target = len(plan["beats"]), target_panels(ctx)
    if n <= target:
        return []
    reasons = []
    lines = plan.get("spoken_lines") or []
    if lines:
        lib, secs = _character_lib(ctx.ws), engine_seconds(ctx)
        by_words = panels_needed(lib, secs, lines)
        if by_words > target:
            reasons.append(P20_LINES_REASON % (len(lines), by_words, ctx.seconds))
        speakers = line_speakers(ctx.narrative, plan["cast"])
        by_speaker = lines_needed(lib, secs, lines, speakers)
        if by_speaker > max(target, by_words):
            reasons.append(P20_SPEAKER_REASON % (len(speaker_runs(lines, speakers)), by_speaker))
        found = narrative_exit_after_last_line(ctx.narrative, plan["cast"])
        said = [k for k, beat in enumerate(plan["beats"], start=1)
                if len(lines) in beat.get("lines", [])]
        if found is not None and said and said[0] < n:
            reasons.append(P20_EXIT_REASON % _q(found))
    if not reasons:
        reasons.append(P20_OTHER_REASON)
    return [P20_NOTE % (n, n - target, target, " and ".join(reasons))]
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sp-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_soft_panel_count.py 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider tests/test_lora_catalog.py 2>&1 | tail -1
```

Expected: `28 passed`, then `tests/test_lora_catalog.py` with no failure (SPR3). Run the compile check with `FILES` = `story_engine.py tests/test_soft_panel_count.py`; expected: `compiled 2` twice. Then run the gate block with `N=3`. Expected: `GATE PASS`, `test_soft_panel_count 28, not passing 0`, `baseline failures still failing 2 of 2` and `OK 347/347`.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_soft_panel_count.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_soft_panel_count.py
git commit -m "feat(story): after the plan the movie has the plan's beat count, and P20 says why it differs from the target (SPC6-SPC9, SPC11; SPR3; SPT1c, SPT6-SPT12, SPT19, SPT24)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: A saved plan in the target's range is reused and re-checked at its own count (SPC10; Plan ruling SPR4)

This task implements:
- SPC10: `_count_in_range`, the `load_plan` range condition and docstring, and the `recheck` ctx adoption.
- Plan ruling SPR4: `recheck` drops a stale plan whose count `story.md` does not have, before the adoption.

Tests: SPT14 and Review Focus 2.

**Files:**
- Modify: `story_engine.py`, `load_plan` (`:4497-4516`) and `recheck` (`:4603-4613`).
- Modify: `tests/test_soft_panel_count.py` (append).

**Interfaces:**
- Consumes: Task 1's `PANELS_EXTRA` and `target_panels`; the existing `_story_manifest(ws)._parse_prompts_md(path)`.
- Produces: `_count_in_range(panels, target) -> bool`. `load_plan(ctx)` accepts `panels` in `[target, target + 2]`. Inside `recheck`, `ctx.panels` is `plan["panels"]` and `ctx.panels_target` is `plan.json`'s `panels_target`, or the current target. Task 5's `_phase1_robust` relies on this.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_spt14_load_plan_and_recheck` and `test_review_focus_2_a_stale_plan_is_not_adopted_by_recheck`.

Edit `tests/test_soft_panel_count.py` (append): replace this text, the file's last lines, which occurs exactly once:

```python
    assert len([r for r in log if r["stage"] == "panel" and r["panel"] == 4]) == 2
    run = _read_json(os.path.join(ctx.story_dir, "story_rounds"), "run.json")
    assert len([c for c in run["calls"] if c["stage"] == "panel" and c["panel"] == 4]) == 2
```

with:

```python
    assert len([r for r in log if r["stage"] == "panel" and r["panel"] == 4]) == 2
    run = _read_json(os.path.join(ctx.story_dir, "story_rounds"), "run.json")
    assert len([c for c in run["calls"] if c["stage"] == "panel" and c["panel"] == 4]) == 2


# --- SPT14: plan reuse and recheck (SPC10) ----------------------------------------------------

def _write_json(story_dir, name, doc):
    with open(os.path.join(story_dir, name), "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)


def test_spt14_load_plan_and_recheck(ws, tmp_path, monkeypatch):
    saved = save_story(ws, tmp_path, monkeypatch, "s1", "chained", 3, 4)
    for panels, loads in ((2, True), (3, True), (4, True), (1, False), (5, False)):
        found = se.load_plan(seu.make_ctx(se, ws, story_id="s1", panels=panels))
        assert (found is not None) == loads, panels
    plan = _read_json(saved.story_dir, "plan.json")
    assert (plan["panels"], plan["panels_target"]) == (4, 3)
    _write_json(saved.story_dir, "plan.json", dict(plan, panels=True))
    assert se.load_plan(seu.make_ctx(se, ws, story_id="s1", panels=3)) is None
    _write_json(saved.story_dir, "plan.json", plan)
    old = save_story(ws, tmp_path, monkeypatch, "s0", "chained", 3, 3)
    doc = _read_json(old.story_dir, "plan.json")
    del doc["panels_target"]
    _write_json(old.story_dir, "plan.json", doc)
    assert se.load_plan(seu.make_ctx(se, ws, story_id="s0", panels=3)) is not None
    seen = []

    def spy(path, panels, no_stills=False):
        seen.append(panels)
        return []

    rc, _advisories = se.recheck(seu.make_ctx(se, ws, story_id="s1", panels=2), spy)
    assert rc == 0
    assert seen == [4]
    checks = _read_json(saved.story_dir, "story_checks.json")
    assert (checks["panels"], checks["panels_target"], checks["source"]) == (4, 3, "recheck")
    del seen[:]
    rc, _advisories = se.recheck(seu.make_ctx(se, ws, story_id="s1", panels=1), spy)
    assert seen and set(seen) == {1}


# --- Review Focus 2, plan ruling SPR4: a stale plan.json beside a story.md of another count ---

def test_review_focus_2_a_stale_plan_is_not_adopted_by_recheck(ws, tmp_path, monkeypatch):
    stale = save_story(ws, tmp_path, monkeypatch, "rf2", "chained", 3, 4)
    other = save_story(ws, tmp_path, monkeypatch, "rf2b", "chained", 3, 3)
    with open(os.path.join(other.story_dir, "story.md"), encoding="utf-8") as f:
        text = f.read()
    with open(os.path.join(stale.story_dir, "story.md"), "w", encoding="utf-8") as f:
        f.write(text)
    seen = []

    def validate(path, panels, no_stills=False):
        seen.append(panels)
        return ltx_movie._validate_story_md(path, panels, no_stills)

    ctx = seu.make_ctx(se, ws, story_id="rf2", panels=3)
    assert se.load_plan(ctx) is not None
    rc, _advisories = se.recheck(ctx, validate)
    assert rc == 0
    assert seen and set(seen) == {3}
```

- [ ] **Step 2: Run the tests to verify that they fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sp-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_soft_panel_count.py 2>&1 | tail -1
```

Expected: the summary starts `2 failed, 28 passed`. Both fail on `load_plan`'s exact-count condition.

- [ ] **Step 3: Implement SPC10 with SPR4.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def load_plan(ctx):
    """<story_dir>/plan.json when it is a valid plan for ctx's mode and panel count, else None."""
```

with:

```python
def _count_in_range(panels, target):
    """True when panels is an int (not a bool) from target to target + PANELS_EXTRA (SPC10)."""
    return (isinstance(panels, int) and not isinstance(panels, bool)
            and target <= panels <= target + PANELS_EXTRA)


def load_plan(ctx):
    """<story_dir>/plan.json when it is a valid plan for ctx's mode whose panels lie in the
    target's range (soft panel count spec SPC10), else None."""
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
            or plan.get("mode") != ctx.mode or plan.get("panels") != ctx.panels
```

with:

```python
            or plan.get("mode") != ctx.mode
            or not _count_in_range(plan.get("panels"), target_panels(ctx))
```

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    lib = _character_lib(ctx.ws)
    plan = load_plan(ctx)
    if plan is not None:
        try:
```

with:

```python
    lib = _character_lib(ctx.ws)
    plan = load_plan(ctx)
    if (plan is not None and plan["panels"] != ctx.panels
            and len(_story_manifest(ctx.ws)._parse_prompts_md(story_md)[1]) != plan["panels"]):
        # Plan ruling SPR4: a plan whose panel count story.md does not have is stale (a later
        # --story-legacy run, or a hand edit); re-check story.md without it, as before SPC10.
        plan = None
    if plan is not None:
        # Soft panel count spec SPC10: re-check against the plan's panel count; the saved target
        # comes from plan.json (an older plan has none: the current target).
        saved = plan.get("panels_target")
        ctx = ctx._replace(panels=plan["panels"], panels_target=(
            saved if isinstance(saved, int) and not isinstance(saved, bool)
            else target_panels(ctx)))
    if plan is not None:
        try:
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sp-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_soft_panel_count.py 2>&1 | tail -1
```

Expected: `30 passed`. Run the compile check with `FILES` = `story_engine.py tests/test_soft_panel_count.py`; expected: `compiled 2` twice. Then run the gate block with `N=4`. Expected: `GATE PASS`, `test_soft_panel_count 30, not passing 0`, `baseline failures still failing 2 of 2` and `OK 347/347`.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_soft_panel_count.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_soft_panel_count.py
git commit -m "feat(story): reuse a saved plan whose panel count is in the target's range and re-check at its count; a stale plan is ignored (SPC10; SPR4; SPT14)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: `bin/ltx-movie` adopts the story's count and says why on every run (SPC13; Plan rulings SPR2, SPR5)

This task implements:
- SPC13 (a), (b): `PANEL_COUNT_NOTE`, `PANEL_COUNT_PHASES`, `PANEL_COUNT_NO_REASON`, `DRY_PANELS_RANGE`, `DRY_PANELS_STORY`, `DRY_PANELS_STOP`, `_plan_panels`, `_resolve_story_panels` and `_write_story_prompt`.
- SPC13 (c): `main` calls the resolver before `_resolve_shots`.
- SPC13 (d): `_story_context` passes `panels_target` and, by Plan ruling SPR2, `length`.
- SPC13 (e): the dry run's plan budgets use `most_panels`, and it prints a `Panel count:` line. By Plan ruling SPR5, that line comes after the rendered prompt.
- SPC13 (f), (g): `_phase1_robust` writes the prompt through `_write_story_prompt`, records `generated`, adopts the count, rewrites `story_prompt.txt` after a generate run that changed the count, and prints the note.
- SPC13 (h): the `--panels` help.

Tests: SPT1 (`bin/ltx-movie` part: `test_spt1d_ltx_movie_constants`), SPT15, SPT16 with SPT25, SPT17 (with Review Focus 4), SPT18 and `test_spr2c_...`.

**Files:**
- Modify: `bin/ltx-movie`. The edits go to the `--panels` help (`:307-309`), before `_story_context` (`:1420`), the end of `_story_context` (`:1450`), `_phase1_robust` (`:1611-1635`), `_print_robust_phase1` (`:2225-2232`) and `main` (`:2473`).
- Modify: `tests/test_soft_panel_count.py` (append).

**Interfaces:**
- Consumes: the engine's `PANELS_EXTRA`, `most_panels`, `panel_range`, `target_panels`, `spoken_lines_problem` (Task 1) and `recheck`'s adoption (Task 4); the existing `_story_paths`, `_story_mode`, `_story_engine`, `_load_story_panels`, `build_story_prompt`, `_clip_seconds` and `_validate_story_md`.
- Produces: `_plan_panels(args) -> (int, str) or None`, `_resolve_story_panels(args)` (sets `args.panels_target`, may set `args.panels`) and `_write_story_prompt(args, story_dir)`. After the resolver or Phase 1, `args.panels` is the story's count. `_story_context(args).length == args.length`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_spt1d_ltx_movie_constants`, `test_spt15_the_resolver`, `test_spt16_spt25_adoption_and_story_prompt`, `test_spt16c_catalog_loras_follow_the_adopted_count`, `test_spt16d_shots_stills_follow_the_adopted_count`, `test_spr2c_length_reaches_the_story_context_and_the_hint`, `test_spt17_the_dry_run` and `test_spt18_the_manifest_needs_the_adopted_count`.

Edit `tests/test_soft_panel_count.py` (append): replace this text, the file's last lines, which occurs exactly once:

```python
    rc, _advisories = se.recheck(ctx, validate)
    assert rc == 0
    assert seen and set(seen) == {3}
```

with:

```python
    rc, _advisories = se.recheck(ctx, validate)
    assert rc == 0
    assert seen and set(seen) == {3}


# --- SPT1 (Task 5 part): the bin/ltx-movie constants (SPC13 a) --------------------------------

PANEL_COUNT_NOTE = "note: story.md has %d panels for a target of %d (%s)"
PANEL_COUNT_PHASES = "; Phases 2-4 use all %d"
PANEL_COUNT_NO_REASON = "plan.json records no reason"
DRY_PANELS_RANGE = ("Panel count: a target of %d; the plan may have %d to %d beats, and Phases 2-4 "
                    "use the plan's count.")
DRY_PANELS_STORY = ("Panel count: plan.json and story.md have %d panels for a target of %d; Phases "
                    "2-4 would use all %d.")
DRY_PANELS_STOP = "Panel count: Phase 1 would stop: %s"
PANELS_HELP = ("number of chained clips; panel 1 also gets the movie's one still image; mutually "
               "exclusive with --length. With the default story engine it is a target: the plan "
               "may add up to 2 panels to fit the narrative, and Phases 2-4 use the plan's count.")


def test_spt1d_ltx_movie_constants():
    assert ltx_movie.PANEL_COUNT_NOTE == PANEL_COUNT_NOTE
    assert ltx_movie.PANEL_COUNT_PHASES == PANEL_COUNT_PHASES
    assert ltx_movie.PANEL_COUNT_NO_REASON == PANEL_COUNT_NO_REASON
    assert ltx_movie.DRY_PANELS_RANGE == DRY_PANELS_RANGE
    assert ltx_movie.DRY_PANELS_STORY == DRY_PANELS_STORY
    assert ltx_movie.DRY_PANELS_STOP == DRY_PANELS_STOP
    helptext = " ".join(ltx_movie.build_parser().format_help().split())
    assert PANELS_HELP in helptext


def _args(*argv):
    """bin/ltx-movie's args for argv after main's resolvers, story panels first (as
    tests/test_lora_catalog.py::_movie_args, plus _resolve_story_panels)."""
    args = ltx_movie.build_parser().parse_args(list(argv))
    args.video_width, args.video_height = 704, 448
    ltx_movie._resolve_story_panels(args)
    for resolve in (ltx_movie._resolve_shots, ltx_movie._resolve_casting,
                    ltx_movie._resolve_global_loras, ltx_movie._resolve_story_engine):
        assert resolve(args) == 0
    return args


THREE_PANELS = ("# T\n\n## Panel 1 — A\nImage: The courier waits.\nMotion: x\nNarration: y\n\n"
                "## Panel 2 — B\nMotion: x\nNarration: y\n\n## Panel 3 — C\nMotion: x\n"
                "Narration: y\n")


# --- SPT15: the bin/ltx-movie resolver (SPC13 b, c; D6) ---------------------------------------

def test_spt15_the_resolver(movie, tmp_path, monkeypatch, capsys):
    saved = save_story(movie, tmp_path, monkeypatch, "m1", "chained", 3, 4)

    def resolved(panels, *flags):
        args = ltx_movie.build_parser().parse_args(
            [NARRATIVE, "--story-id", "m1", "--panels", str(panels)] + list(flags))
        ltx_movie._resolve_story_panels(args)
        return args.panels, args.panels_target

    rows = ((3, (), (4, 3)), (2, (), (4, 2)), (4, (), (4, 4)), (1, (), (1, 1)),
            (3, ("--force-story",), (3, 3)), (3, ("--story-legacy",), (3, 3)),
            (3, ("--shots",), (3, 3)))
    for panels, flags, want in rows:
        assert resolved(panels, *flags) == want, (panels, flags)
    story_md = os.path.join(saved.story_dir, "story.md")
    with open(story_md, encoding="utf-8") as f:
        text = f.read()
    with open(story_md, "w", encoding="utf-8") as f:
        f.write(THREE_PANELS)
    assert resolved(3) == (3, 3)
    os.remove(story_md)
    assert resolved(3) == (3, 3)
    with open(story_md, "w", encoding="utf-8") as f:
        f.write(text)
    save_story(movie, tmp_path, monkeypatch, "m1s", "shots", 3, 4)
    args = ltx_movie.build_parser().parse_args(
        [NARRATIVE, "--story-id", "m1s", "--panels", "3", "--shots", "--redo", "4"])
    ltx_movie._resolve_story_panels(args)
    assert ltx_movie._resolve_shots(args) == 0
    assert args.redo_panels == [4]
    args = ltx_movie.build_parser().parse_args(
        [NARRATIVE, "--story-id", "m1s", "--panels", "3", "--shots", "--redo", "5"])
    ltx_movie._resolve_story_panels(args)
    capsys.readouterr()
    assert ltx_movie._resolve_shots(args) == 2
    assert capsys.readouterr().err == "Error: --redo panel 5 is out of range (1..4)\n"


# --- SPT16, SPT25: adoption after Phase 1, the downstream uses, story_prompt.txt (SPC13 f, g) --

def _story_prompt(story_id, panels, args):
    return ltx_movie.build_story_prompt(NARRATIVE, story_id, panels, False, False,
                                        seconds=ltx_movie._clip_seconds(args), cast_block=None,
                                        shots=False)


def test_spt16_spt25_adoption_and_story_prompt(movie, tmp_path, monkeypatch, capsys):
    note = P20_NOTE % (4, 1, 3, P20_OTHER_REASON)
    seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(seu.plan_json("chained", 4))],
                     panel=panel_script("chained", 4))
    capsys.readouterr()
    assert ltx_movie.main([NARRATIVE, "--story-id", "m2", "--panels", "3", "--story-only",
                           "--no-review"]) == 0
    out = capsys.readouterr().out
    told = PANEL_COUNT_NOTE % (4, 3, "because " + P20_OTHER_REASON)
    assert ("Warning: " + note + "\n") in out
    assert (told + "\n") in out
    assert out.index("Warning: " + note) < out.index(told)
    story_dir = os.path.join(movie, "generated", "stories", "m2")
    prompt_path = os.path.join(story_dir, "story_prompt.txt")
    with open(prompt_path, encoding="utf-8") as f:
        prompt = f.read()
    assert "EXACTLY 4 panel sections" in prompt
    args = _args(NARRATIVE, "--story-id", "m2", "--panels", "3", "--no-review")
    assert prompt == _story_prompt("m2", 4, args)
    assert (args.panels, args.panels_target) == (4, 3)
    args.panels = 3
    os.utime(prompt_path, (1000000000, 1000000000))
    capsys.readouterr()
    assert ltx_movie._phase1_robust(args) == 0
    out = capsys.readouterr().out
    assert (told + PANEL_COUNT_PHASES % 4 + "\n") in out
    assert args.panels == 4
    assert ltx_movie._target_seconds(args) == 4 * 145 / 24.0
    assert os.path.getmtime(prompt_path) == 1000000000
    args = _args(NARRATIVE, "--story-id", "m2", "--panels", "4", "--no-review")
    capsys.readouterr()
    assert ltx_movie._phase1_robust(args) == 0
    assert "note: story.md has " not in capsys.readouterr().out
    seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(seu.plan_json("chained", 3))],
                     panel=panel_script("chained", 3))
    capsys.readouterr()
    assert ltx_movie.main([NARRATIVE, "--story-id", "m3", "--panels", "3", "--story-only",
                           "--no-review"]) == 0
    assert "note: story.md has " not in capsys.readouterr().out
    with open(os.path.join(movie, "generated", "stories", "m3", "story_prompt.txt"),
              encoding="utf-8") as f:
        assert "EXACTLY 3 panel sections" in f.read()


def test_spt16c_catalog_loras_follow_the_adopted_count(movie, tmp_path, story_env):
    files = str(tmp_path / "files")
    fast = seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion", triggers=["fastmo"])
    seu.make_catalog(story_env["catalog"], [fast])
    story_dir = os.path.join(movie, "generated", "stories", "c4")
    os.makedirs(story_dir)
    _write_json(story_dir, "plan.json", {
        "schema": "ltx-movie.plan.v1", "mode": "chained", "panels": 4, "panels_target": 3,
        "title": "T", "logline": "x", "cast": [], "locations": [], "props": [], "beats": [],
        "loras": {"global": [], "per_beat": {"4": [{"id": "fast-motion", "strength": 0.7}]},
                  "stills": []}})
    with open(os.path.join(story_dir, "story.md"), "w", encoding="utf-8") as f:
        f.write(THREE_PANELS + "\n## Panel 4 — D\nMotion: x\nNarration: y\n")
    args = _args(NARRATIVE, "--story-id", "c4", "--panels", "3")
    assert args.panels == 4
    error, lists = ltx_movie._catalog_panel_loras(args)
    assert error is None and len(lists) == 4
    assert [p["id"] for p in lists[3]] == ["fast-motion"]
    assert lists[3][0]["path"] == fast["path"] and lists[:3] == [[], [], []]


def test_spt16d_shots_stills_follow_the_adopted_count(movie, tmp_path, monkeypatch):
    save_story(movie, tmp_path, monkeypatch, "m2s", "shots", 3, 4)
    args = _args(NARRATIVE, "--story-id", "m2s", "--panels", "3", "--shots")
    assert args.panels == 4
    assert len(ltx_movie._shots_image_flags(args)) == 8


# --- Plan ruling SPR2: --length reaches the engine ----------------------------------------------

TEN = (EIGHT + ' He says "The lanterns are burning low along the old wall." He says "We should '
       'rest here until the cold morning comes."')


def test_spr2c_length_reaches_the_story_context_and_the_hint(movie, tmp_path, monkeypatch,
                                                             capsys):
    args = ltx_movie.build_parser().parse_args([NARRATIVE, "--story-id", "l1", "--length", "30"])
    ltx_movie._resolve_length(args, [NARRATIVE, "--story-id", "l1", "--length", "30"])
    ltx_movie._resolve_story_panels(args)
    ctx = ltx_movie._story_context(args)
    assert (ctx.panels, ctx.panels_target, ctx.length) == (5, 5, 30.0)
    args = _args(NARRATIVE, "--story-id", "l2", "--panels", "3")
    assert ltx_movie._story_context(args).length is None
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(seu.plan_json("chained", 2))])
    capsys.readouterr()
    assert ltx_movie.main([TEN, "--story-id", "l3", "--length", "12", "--story-only",
                           "--no-review"]) == 2
    err = capsys.readouterr().err
    cap = lib.dialogue_word_cap(145 / 24.0, 1)
    assert ("Error: " + LINES_LENGTH_PROBLEM % (6, 6, "6", cap, 4, "12.0", 2, 2, "24.2", 4)
            + "\n") in err
    assert "--panels" not in err
    assert seu.agent_log(log) == []


# --- SPT17, Review Focus 4: the dry run (SPC13 e; plan ruling SPR5) ---------------------------

def _dry(argv, capsys):
    capsys.readouterr()
    assert ltx_movie.main(argv + ["--dry-run", "--no-review"]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    start = lines.index("--- Phase 1: story ---")
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("--- Phase "))
    return out, lines[start:end]


def test_spt17_the_dry_run(movie, tmp_path, monkeypatch, capsys):
    out, block = _dry([NARRATIVE, "--story-id", "d1", "--panels", "20"], capsys)
    assert DRY_PANELS_RANGE % (20, 20, 22) in block
    assert "Command (subprocess timeout 880s): " in out
    argv = shlex.split(out.split("Command (subprocess timeout 880s): ", 1)[1]
                       .split("\n\nRendered plan prompt:\n", 1)[0])
    assert argv[argv.index("--max-tokens") + 1] == "5500"
    assert argv[-1].startswith('You are planning a short narrated movie (story-id "d1")')
    assert block[block.index("Rendered plan prompt:") + 1].startswith("You are planning")
    _out, block = _dry([EIGHT, "--story-id", "d2", "--panels", "1"], capsys)
    assert [line for line in block if line.startswith(
        "Panel count: Phase 1 would stop: the narrative quotes 4 spoken lines")]
    save_story(movie, tmp_path, monkeypatch, "m1", "chained", 3, 4)
    out, block = _dry([NARRATIVE, "--story-id", "m1", "--panels", "3"], capsys)
    assert DRY_PANELS_STORY % (4, 3, 4) in block
    assert ("--target-seconds " + str(4 * 145 / 24.0)) in out
    assert ("--target-seconds " + str(3 * 145 / 24.0)) not in out


# --- SPT18: why the count must be adopted before Phase 3 --------------------------------------

# A valid 1x1 PNG (copied from tests/test_dialogue.py): the manifest only checks that it opens.
PNG_1X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
                           "60e6kgAAAABJRU5ErkJggg==")


def test_spt18_the_manifest_needs_the_adopted_count(movie, tmp_path, monkeypatch, capsys):
    saved = save_story(movie, tmp_path, monkeypatch, "m5", "chained", 3, 4)
    monkeypatch.setattr(manifest, "WS", movie)
    image = str(tmp_path / "seed.png")
    with open(image, "wb") as f:
        f.write(PNG_1X1)
    base = ["--chain", "--prompts-md", os.path.join(saved.story_dir, "story.md"), "--image",
            image, "--fps", "24", "--min-frames", "145", "--max-frames", "145", "--pace", "equal",
            "--force", "--story-id", "x"]
    assert manifest.main(base + ["--target-seconds", repr(4 * 145 / 24.0)]) == 0
    written = _read_json(os.path.join(movie, "generated", "stories", "x"), "manifest.json")
    assert len(written["panels"]) == 4
    capsys.readouterr()
    assert manifest.main(base + ["--target-seconds", repr(3 * 145 / 24.0)]) == 2
    assert "not achievable" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify that they fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sp-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_soft_panel_count.py 2>&1 | tail -1
```

Expected: the summary starts `7 failed, 31 passed`. SPT18 passes already: it pins the manifest's existing behaviour. The seven fail on the missing constants and `_resolve_story_panels`.

- [ ] **Step 3: Implement SPC13 with SPR2 and SPR5.**

**3.1.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    parser.add_argument("--panels", type=int, default=15,
                         help="number of chained clips; panel 1 also gets the movie's "
                              "one still image; mutually exclusive with --length")
```

with:

```python
    parser.add_argument("--panels", type=int, default=15,
                         help="number of chained clips; panel 1 also gets the movie's "
                              "one still image; mutually exclusive with --length. With the "
                              "default story engine it is a target: the plan may add up to 2 "
                              "panels to fit the narrative, and Phases 2-4 use the plan's count.")
```

**3.2.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
def _story_context(args, dry_run=False):
    """The story_engine.StoryContext of this run (robust story spec 2.1)."""
```

with:

```python
# Soft panel count spec SPC13, D7: the user is told when the story has more panels than its target,
# and why, on every run.
PANEL_COUNT_NOTE = "note: story.md has %d panels for a target of %d (%s)"
PANEL_COUNT_PHASES = "; Phases 2-4 use all %d"
PANEL_COUNT_NO_REASON = "plan.json records no reason"
DRY_PANELS_RANGE = ("Panel count: a target of %d; the plan may have %d to %d beats, and Phases 2-4 "
                    "use the plan's count.")
DRY_PANELS_STORY = ("Panel count: plan.json and story.md have %d panels for a target of %d; Phases "
                    "2-4 would use all %d.")
DRY_PANELS_STOP = "Panel count: Phase 1 would stop: %s"


def _plan_panels(args):
    """(panels, reason) of plan.json when it is the plan of this story.md (soft panel count spec
    SPC13, D6): a JSON object with schema ltx-movie.plan.v1, this run's mode, an int panels from
    the target (args.panels_target, else args.panels) to the target plus
    story_engine.PANELS_EXTRA, and story.md parsing to exactly that many panels; else None.
    reason is "because <the text after 'because '>" of the first speech_notes entry that starts
    "plan: P20 panel count: ", else PANEL_COUNT_NO_REASON."""
    target = getattr(args, "panels_target", None) or args.panels
    paths = _story_paths(args.story_id)
    try:
        with open(os.path.join(paths["story_dir"], "plan.json"), encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, ValueError):
        return None
    panels = plan.get("panels") if isinstance(plan, dict) else None
    if (not isinstance(plan, dict) or plan.get("schema") != "ltx-movie.plan.v1"
            or plan.get("mode") != _story_mode(args) or not isinstance(panels, int)
            or isinstance(panels, bool)
            or not target <= panels <= target + _story_engine().PANELS_EXTRA
            or len(_load_story_panels(paths["story_md"])) != panels):
        return None
    notes = plan.get("speech_notes") if isinstance(plan.get("speech_notes"), list) else []
    saved = [m for m in notes if isinstance(m, str) and m.startswith("plan: P20 panel count: ")
             and ", because " in m]
    reason = ("because " + saved[0].split(", because ", 1)[1]) if saved else PANEL_COUNT_NO_REASON
    return panels, reason


def _resolve_story_panels(args):
    """Soft panel count spec SPC13, D7: args.panels_target is --panels; with the default story
    engine, no --force-story and an existing story.md whose plan.json is its plan for this run,
    args.panels becomes the plan's panel count. Prints nothing; never fails."""
    args.panels_target = args.panels
    if (args.story_legacy or args.story_prompt_override is not None or args.force_story
            or not os.path.isfile(_story_paths(args.story_id)["story_md"])):
        return
    found = _plan_panels(args)
    if found is not None:
        args.panels = found[0]


def _write_story_prompt(args, story_dir):
    """<story_dir>/story_prompt.txt: build_story_prompt for args.panels (soft panel count spec
    SPC13, D12)."""
    prompt = build_story_prompt(args.narrative, args.story_id, args.panels, args.no_stills,
                                bool(getattr(args, "seed_image", None)),
                                seconds=_clip_seconds(args),
                                cast_block=getattr(args, "cast_block", None),
                                shots=getattr(args, "shots", False))
    with open(os.path.join(story_dir, "story_prompt.txt"), "w", encoding="utf-8") as f:
        f.write(prompt)


def _story_context(args, dry_run=False):
    """The story_engine.StoryContext of this run (robust story spec 2.1)."""
```

**3.3.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
        clip_seconds=args.frames / float(args.fps))
```

with:

```python
        clip_seconds=args.frames / float(args.fps),
        panels_target=getattr(args, "panels_target", None), length=getattr(args, "length", None))
```

**3.4.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    if os.path.exists(story_md) and not args.force_story:
        print("note: %s already exists; re-checking it instead of regenerating it (pass "
              "--force-story to regenerate)" % story_md)
        rc, advisories = engine.recheck(
            ctx, lambda path, panels, no_stills=False: _validate_story_md(
                path, panels, no_stills, no_narration=args.no_narration or args.speech_only))
    else:
        print("=== Phase 1: story ===")
        prompt = build_story_prompt(args.narrative, args.story_id, args.panels, args.no_stills,
                                     bool(getattr(args, "seed_image", None)),
                                     seconds=_clip_seconds(args),
                                     cast_block=getattr(args, "cast_block", None),
                                     shots=getattr(args, "shots", False))
        with open(os.path.join(paths["story_dir"], "story_prompt.txt"), "w",
                  encoding="utf-8") as f:
            f.write(prompt)
        rc, advisories = engine.run(ctx, no_stills_rules=_no_stills_rules())
```

with:

```python
    if os.path.exists(story_md) and not args.force_story:
        generated = False
        print("note: %s already exists; re-checking it instead of regenerating it (pass "
              "--force-story to regenerate)" % story_md)
        rc, advisories = engine.recheck(
            ctx, lambda path, panels, no_stills=False: _validate_story_md(
                path, panels, no_stills, no_narration=args.no_narration or args.speech_only))
    else:
        generated = True
        print("=== Phase 1: story ===")
        _write_story_prompt(args, paths["story_dir"])
        rc, advisories = engine.run(ctx, no_stills_rules=_no_stills_rules())
```

**3.5.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    for advisory in advisories:
        print("Warning: %s" % advisory)
    members = getattr(args, "cast_members", None) or []
```

with:

```python
    for advisory in advisories:
        print("Warning: %s" % advisory)
    target = getattr(args, "panels_target", None) or args.panels
    found = _plan_panels(args)
    if found is not None:
        args.panels = found[0]
        if args.panels != target:
            if generated:
                _write_story_prompt(args, paths["story_dir"])
            print(PANEL_COUNT_NOTE % (args.panels, target, found[1])
                  + ("" if args.story_only else PANEL_COUNT_PHASES % args.panels))
    members = getattr(args, "cast_members", None) or []
```

**3.6.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    argv = engine.agent_cmd(ctx, prompt, max_tokens=engine.plan_max_tokens(args.panels),
                            image=ctx.seed_agent_image)
    print("Command (subprocess timeout %ds): %s"
          % (engine.plan_timeout(args.panels), shlex.join(argv)))
    print()
    print("Rendered plan prompt:")
    print(prompt)
    print()
```

with:

```python
    argv = engine.agent_cmd(ctx, prompt, max_tokens=engine.plan_max_tokens(engine.most_panels(ctx)),
                            image=ctx.seed_agent_image)
    print("Command (subprocess timeout %ds): %s"
          % (engine.plan_timeout(engine.most_panels(ctx)), shlex.join(argv)))
    print()
    print("Rendered plan prompt:")
    print(prompt)
    print()
    # Soft panel count spec SPC13 (e); plan ruling SPR5: after the rendered prompt, so the
    # command line is still followed by a blank line and "Rendered plan prompt:".
    problem = engine.spoken_lines_problem(ctx)
    lo, hi = engine.panel_range(ctx)
    target = engine.target_panels(ctx)
    if problem:
        print(DRY_PANELS_STOP % problem)
    elif ctx.panels != target:
        print(DRY_PANELS_STORY % (ctx.panels, target, ctx.panels))
    else:
        print(DRY_PANELS_RANGE % (target, lo, hi))
    print()
```

**3.7.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    rc = _resolve_shots(args)
    if rc:
        return rc
    rc = _resolve_casting(args)
```

with:

```python
    _resolve_story_panels(args)
    rc = _resolve_shots(args)
    if rc:
        return rc
    rc = _resolve_casting(args)
```

- [ ] **Step 4: Run the new tests, the dry-run and review guards, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sp-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_soft_panel_count.py 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider tests/test_story_engine.py -k "rst46 or rst47 or rst50" 2>&1 | tail -1
```

Expected: `38 passed`, then the four selected `test_story_engine.py` tests passed with none failed. They are `test_rst46_review_gate`, `test_rst47_robust_dry_run`, `test_rst50_source_literal_counts` and `test_rst50b_robust_review_reads_utf8`. Run the compile check with `FILES` = `bin/ltx-movie tests/test_soft_panel_count.py`; expected: `compiled 2` twice. Then run the gate block with `N=5`. Expected: `GATE PASS`, `test_soft_panel_count 38, not passing 0`, `baseline failures still failing 2 of 2` and `OK 347/347`.

- [ ] **Step 5: Commit.**

```bash
git add bin/ltx-movie tests/test_soft_panel_count.py
git diff --cached --name-only    # expected: qwen-agent-workspace/bin/ltx-movie, qwen-agent-workspace/tests/test_soft_panel_count.py
git commit -m "feat(ltx-movie): adopt the story's panel count before and after Phase 1 and say why on every run (SPC13; SPR2, SPR5; SPT1d, SPT15-SPT18, SPT25)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The movie UI and `bin/iterate-story` follow the story's count (SPC14-SPC16)

This task implements:
- SPC14 (a): `PANELS_EXTRA`, `STORY_PANEL_RE`, `plan_panels` and `effective_panels` in `movie_ui_lib.py`, used by rule 16 and the Phase 2 stills count.
- SPC14 (b): the `storyFields` fallback.
- SPC14 (c): the Size note.
- SPC15: `build_engine_cmd` regenerates with `panels_target`.
- SPC16: the "Panels (target)" input, its prefill, and the Regenerate handler.

Tests: SPT1 (UI part: `test_spt1e_movie_ui_constants`), SPT20, SPT21, SPT26 and SPT27.

**Files:**
- Modify: `movie_ui_lib.py`: after `resolved_panels` (`:1214-1221`), rule 16 (`:1385`) and `snapshot` (`:2132`).
- Modify: `static/movie-ui/app.js`: `openStory` (`:716`), `storyFields` (`:737`) and the Regenerate handler (`:748-753`).
- Modify: `static/movie-ui/index.html`: the Size fieldset (`:52-53`) and the Stories row (`:150`).
- Modify: `bin/iterate-story`: `build_engine_cmd` (`:265`).
- Modify: `tests/test_soft_panel_count.py` (append).

**Interfaces:**
- Consumes: the existing `read_json`, `_is_int`, `resolved_panels`, `story_dir`, `validate_fields`, `build_argv`, `compose_fields` and `ProgressParser` (movie UI); `numberOrNull`, `askConfirm`, `submit` and `storyFields` (`app.js`); and `movie_ui_testutil`.
- Produces: `movie_ui_lib.PANELS_EXTRA`, `STORY_PANEL_RE`, `plan_panels(sdir, mode) -> int or None` and `effective_panels(fields, sdir) -> int or None`; the element ids `c-size-note` and `s-regen-panels`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_spt1e_movie_ui_constants`, `test_spt20_the_movie_ui_uses_the_storys_count`, `test_spt21_iterate_story_regenerates_with_the_target`, `test_spt26_the_regenerate_argv` and `test_spt27_the_regenerate_target_is_wired_in_the_static_ui`.

Edit `tests/test_soft_panel_count.py` (append): replace this text, the file's last lines, which occurs exactly once:

```python
    capsys.readouterr()
    assert manifest.main(base + ["--target-seconds", repr(3 * 145 / 24.0)]) == 2
    assert "not achievable" in capsys.readouterr().err
```

with:

```python
    capsys.readouterr()
    assert manifest.main(base + ["--target-seconds", repr(3 * 145 / 24.0)]) == 2
    assert "not achievable" in capsys.readouterr().err


# --- SPT1 (Task 6 part), SPT20: the movie UI (SPC14) ------------------------------------------

import movie_ui_testutil as mt  # noqa: E402


def test_spt1e_movie_ui_constants():
    assert mui.PANELS_EXTRA == se.PANELS_EXTRA
    assert mui.STORY_PANEL_RE.pattern == manifest._PANEL_HEADER_RE.pattern


def _plan_doc(story_dir):
    return _read_json(story_dir, "plan.json")


def test_spt20_the_movie_ui_uses_the_storys_count(ws, tmp_path, monkeypatch):
    saved = save_story(ws, tmp_path, monkeypatch, "s1", "chained", 3, 4)
    sdir = saved.story_dir
    assert mui.plan_panels(sdir, "chained") == 4
    assert mui.plan_panels(sdir, "shots") is None
    plan = _plan_doc(sdir)
    for bad in ({"schema": "x"}, {"panels": 0}, {"panels": "4"}, {"panels": True}):
        _write_json(sdir, "plan.json", dict(plan, **bad))
        assert mui.plan_panels(sdir, "chained") is None, bad
    os.remove(os.path.join(sdir, "plan.json"))
    assert mui.plan_panels(sdir, "chained") is None
    _write_json(sdir, "plan.json", plan)
    story_md = os.path.join(sdir, "story.md")
    with open(story_md, encoding="utf-8") as f:
        text = f.read()
    with open(story_md, "w", encoding="utf-8") as f:
        f.write(THREE_PANELS)
    assert mui.plan_panels(sdir, "chained") is None
    with open(story_md, "w", encoding="utf-8") as f:
        f.write(text)
    rows = (({"panels": 3, "mode": "chained"}, sdir, 4), ({"panels": 2, "mode": "chained"}, sdir, 4),
            ({"panels": 1, "mode": "chained"}, sdir, 1), ({"panels": 3, "mode": "shots"}, sdir, 3),
            ({"panels": 3, "mode": "chained"}, None, 3))
    for fields, where, want in rows:
        assert mui.effective_panels(fields, where) == want, (fields, where)
    six = save_story(ws, tmp_path, monkeypatch, "s6", "chained", 5, 6)
    by_length = {"length": 30, "frames": 145, "fps": 24, "mode": "chained"}
    assert mui.resolved_panels(by_length) == 5
    assert mui.effective_panels(by_length, six.story_dir) == 6
    shots = save_story(ws, tmp_path, monkeypatch, "sh4", "shots", 3, 4)
    state = str(tmp_path / "state")
    os.makedirs(state)
    for redo, want in (([4], []), ([5], ["redo panel 5 is out of range (1..4)"])):
        fields = mui.compose_fields({"story_id": "sh4", "narrative": "x"})
        fields.update(action="redo", mode="shots", panels=3, redo=redo)
        errors = mui.validate_fields(fields, ws, state)
        assert [e for e in errors if e.startswith("redo panel")] == want, redo
    fields = {"mode": "shots", "panels": 3, "action": "movie", "seed_upload": None}
    parser = mui.ProgressParser("movie", fields)
    parser.feed(b"=== Phase 1: story ===\n=== Phase 2: stills ===\n")
    job = {"id": "20261029-120000-a1b2", "kind": "movie", "workspace": ws, "story_id": "sh4",
           "fields": fields}
    assert parser.snapshot(job, None, state)["stills"]["expected"] == 4
    assert shots.story_dir == os.path.join(ws, "generated", "stories", "sh4")
    static = os.path.join(WS, "static", "movie-ui")
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(static, "app.js"), encoding="utf-8") as f:
        js = f.read()
    assert 'id="c-size-note"' in html and "Panels is a target" in html
    assert "st.checks.panels_target || st.checks.panels" in js


# --- SPT21: bin/iterate-story regenerates with the target (SPC15) -----------------------------

def test_spt21_iterate_story_regenerates_with_the_target():
    plan = {"narrative": NARRATIVE, "mode": "chained", "panels": 4, "panels_target": 3,
            "cast": [], "loras": {"pinned": []}}
    cmd = iterate_story.build_engine_cmd("s", plan)
    assert cmd[cmd.index("--panels") + 1] == "3"
    del plan["panels_target"]
    cmd = iterate_story.build_engine_cmd("s", plan)
    assert cmd[cmd.index("--panels") + 1] == "4"


# --- SPT26, SPT27: a panel target for "Regenerate story" (SPC16) ------------------------------

PY = "/py"
LTX = "/w/bin/ltx-movie"


def _f(**overrides):
    fields = mui.compose_fields({"story_id": "ronin", "narrative": "  A ronin walks.  "})
    fields.update(overrides)
    return fields


@pytest.fixture
def ui_env(monkeypatch, tmp_path):
    """tests/test_movie_ui_http.py's env fixture: a movie-ui server on 127.0.0.1 under a
    temporary HOME, with a stub workspace."""
    state = mt.set_home(monkeypatch, tmp_path)
    ui_ws = mt.make_stub_workspace(tmp_path)
    running = mt.Running(state)
    yield {"state": state, "ws": ui_ws, "tmp": str(tmp_path), "srv": running}
    running.close()
    mt.kill_everything(state)


def test_spt26_the_regenerate_argv(ui_env):
    base = [PY, LTX, "A ronin walks.", "--story-id", "ronin"]
    defaults = ["--fps", "24", "--frames", "145", "--model", mui.DEFAULT_MODEL, "--gemma",
                mui.DEFAULT_GEMMA]
    want = base + ["--panels", "4"] + defaults + ["--force-story", "--story-only", "--no-review"]
    assert mui.build_argv(_f(action="regenerate", panels=4, length=None), "/w", "/s",
                          py=PY) == want
    fields = _f(panels=None, length=30)
    fields.update(action="regenerate", panels=4, length=None)
    argv = mui.build_argv(fields, "/w", "/s", py=PY)
    assert argv == want and "--length" not in argv
    checked = dict(fields, ws=ui_env["ws"])
    errors = mui.validate_fields(checked, ui_env["ws"], ui_env["state"])
    assert [e for e in errors if "panels" in e] == []
    errors = mui.validate_fields(dict(checked, panels=0), ui_env["ws"], ui_env["state"])
    assert "panels must be an integer from 1 to 200" in errors
    errors = mui.validate_fields(dict(checked, length=30), ui_env["ws"], ui_env["state"])
    assert "give exactly one of panels or length" in errors
    body = mt.fields(ui_env["ws"], action="regenerate", panels=4)
    status, _headers, preview = mt.api(ui_env["srv"], "POST", "/api/preview", body=body)
    assert status == 200 and preview["errors"] == []
    argv = preview["argv"]
    assert argv[argv.index("--panels") + 1] == "4" and "--force-story" in argv


def test_spt27_the_regenerate_target_is_wired_in_the_static_ui():
    static = os.path.join(WS, "static", "movie-ui")
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(static, "app.js"), encoding="utf-8") as f:
        js = f.read()
    assert 'id="s-regen-panels"' in html and 'min="1"' in html and "Panels (target)" in html
    assert html.index('id="s-regen-panels"') < html.index('id="s-regenerate"')
    for text in ("#s-regen-panels", "with a target of ", "{panels: target, length: null}",
                 "res.data.last_fields.panels"):
        assert text in js, text
```

- [ ] **Step 2: Run the tests to verify that they fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sp-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_soft_panel_count.py 2>&1 | tail -1
```

Expected: the summary starts `4 failed, 39 passed`. SPT26 passes already, because SPC16 (d) needs no server change. The four fail on the missing `PANELS_EXTRA`, `plan_panels` and static ids, and on `build_engine_cmd`'s `--panels`.

- [ ] **Step 3: Implement SPC14-SPC16.**

**3.1.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    if _is_number(length) and _is_int(frames) and _is_int(fps) and frames > 0 and fps > 0:
        return int(round(length / (frames / float(fps))))
    return None
```

with:

```python
    if _is_number(length) and _is_int(frames) and _is_int(fps) and frames > 0 and fps > 0:
        return int(round(length / (frames / float(fps))))
    return None


# Soft panel count spec SPC14, D11: story_engine.PANELS_EXTRA and bin/ltx-story-manifest's
# _PANEL_HEADER_RE (this module never loads a pipeline module, so both are repeated here and
# pinned equal by a test).
PANELS_EXTRA = 2
STORY_PANEL_RE = re.compile(r"^##\s*Panel\s*(\d+)\s*[—–-]\s*(.*)$", re.MULTILINE)


def plan_panels(sdir, mode):
    """<sdir>/plan.json's "panels" when the file is a JSON object with schema ltx-movie.plan.v1,
    "mode" equal to mode, an int "panels" of at least 1, and <sdir>/story.md has exactly that
    many STORY_PANEL_RE headers; else None (SPC14)."""
    plan = read_json(os.path.join(sdir, "plan.json"))
    if not (isinstance(plan, dict) and plan.get("schema") == "ltx-movie.plan.v1"
            and plan.get("mode") == mode and _is_int(plan.get("panels")) and plan["panels"] >= 1):
        return None
    try:
        with open(os.path.join(sdir, "story.md"), "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    return plan["panels"] if len(STORY_PANEL_RE.findall(text)) == plan["panels"] else None


def effective_panels(fields, sdir):
    """The story's panel count for fields (SPC14): plan_panels(sdir, fields["mode"]) when it lies
    in [resolved_panels(fields), resolved_panels(fields) + PANELS_EXTRA], else
    resolved_panels(fields). sdir None means no story directory."""
    target = resolved_panels(fields)
    planned = plan_panels(sdir, fields.get("mode")) if sdir is not None else None
    if target is not None and planned is not None and target <= planned <= target + PANELS_EXTRA:
        return planned
    return target
```

**3.2.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
            total = resolved_panels(fields)
            if total is not None:
```

with:

```python
            total = effective_panels(fields, sdir)
            if total is not None:
```

**3.3.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
            expected = resolved_panels(self.fields) if self.fields.get("mode") == "shots" else 1
```

with:

```python
            expected = (effective_panels(self.fields, story_dir(job["workspace"], job["story_id"]))
                        if self.fields.get("mode") == "shots" else 1)
```

**3.4.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    const panels = st.checks && st.checks.panels ? st.checks.panels : (S.options ? S.options.defaults.panels : 15);
```

with:

```js
    const saved = st.checks ? (st.checks.panels_target || st.checks.panels) : null;
    const panels = saved ? saved : (S.options ? S.options.defaults.panels : 15);
```

**3.5.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    show($("#s-redo-box"), Boolean(shots));
```

with:

```js
    show($("#s-redo-box"), Boolean(shots));
    const regen = $("#s-regen-panels");
    const lastPanels = res.data.last_fields ? res.data.last_fields.panels : null;
    regen.value = lastPanels !== null && lastPanels !== undefined ? String(lastPanels) : "";
    regen.placeholder = res.data.checks && res.data.checks.panels ? String(res.data.checks.panels) : "";
```

**3.6.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```js
    $("#s-regenerate").addEventListener("click", async function () {
      if (!S.story.last_fields) { $("#s-action-status").textContent = "compose this story once before regenerating it"; return; }
      if (!(await askConfirm("Regenerate story.md of " + S.story.id + "? The current one is replaced."))) { return; }
      const res = await submit(storyFields("regenerate"));
      $("#s-action-status").textContent = res.status === 201 ? "queued" : "refused; see Compose checks";
    });
```

with:

```js
    $("#s-regenerate").addEventListener("click", async function () {
      if (!S.story.last_fields) { $("#s-action-status").textContent = "compose this story once before regenerating it"; return; }
      const target = numberOrNull("#s-regen-panels");
      const question = target === null
        ? "Regenerate story.md of " + S.story.id + "? The current one is replaced."
        : "Regenerate story.md of " + S.story.id + " with a target of " + target + " panels? The current one is replaced.";
      if (!(await askConfirm(question))) { return; }
      const fields = storyFields("regenerate");
      const res = await submit(target === null ? fields : Object.assign(fields, {panels: target, length: null}));
      $("#s-action-status").textContent = res.status === 201 ? "queued" : "refused; see Compose checks";
    });
```

**3.7.** Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
        <input id="c-length" type="number" min="1" max="3600" step="0.5" value="60"></label>
```

with:

```html
        <input id="c-length" type="number" min="1" max="3600" step="0.5" value="60"></label>
      <span id="c-size-note" class="muted">Panels is a target: the default story engine may add up to 2 panels to fit the narrative.</span>
```

**3.8.** Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
      <button id="s-regenerate" type="button">Regenerate story</button>
```

with:

```html
      <label>Panels (target) <input id="s-regen-panels" type="number" min="1" max="200" step="1" size="4"></label>
      <button id="s-regenerate" type="button">Regenerate story</button>
```

**3.9.** Edit `bin/iterate-story`: replace this text, which occurs exactly once:

```python
           "--story-id", story_id, "--panels", str(plan["panels"])]
```

with:

```python
           "--story-id", story_id, "--panels", str(plan.get("panels_target", plan["panels"]))]
```

- [ ] **Step 4: Run the new tests, the UI suites, the compile and JavaScript checks, and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sp-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_soft_panel_count.py 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_progress.py tests/test_movie_ui_checks.py tests/test_iterate_story.py 2>&1 | tail -1
if command -v node >/dev/null; then node --check static/movie-ui/app.js && echo "app.js ok"; else echo "node not installed"; fi
```

Expected: `43 passed`; then those three suites with no failure; then `app.js ok` (or `node not installed`). Run the compile check with `FILES` = `movie_ui_lib.py bin/iterate-story tests/test_soft_panel_count.py`; expected: `compiled 3` twice. Then run the gate block with `N=6`. Expected: `GATE PASS`, `test_soft_panel_count 43, not passing 0`, `baseline failures still failing 2 of 2` and `OK 347/347`.

- [ ] **Step 5: Commit.**

```bash
git add movie_ui_lib.py static/movie-ui/app.js static/movie-ui/index.html bin/iterate-story tests/test_soft_panel_count.py
git diff --cached --name-only    # expected: the five paths above, each with the qwen-agent-workspace/ prefix
git commit -m "feat(movie-ui): stills, redo and Regenerate follow the story's panel count, and iterate-story keeps the target (SPC14-SPC16; SPT1e, SPT20, SPT21, SPT26, SPT27)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Re-baseline the existing tests (G6; test-only commit; spec 4.2)

This task changes no pipeline file. It turns every listed failure green by updating its assertions or fixture to the new behaviour. The work is split so that the executor makes no decision:
- The measurement and the edits are executor steps.
- The classification, the exact edit text and the per-file explanations come from an Opus pass that the controller runs. "Opus thinks, Sonnet types."

**Files:**
- Modify: only the existing test files and fixtures that the Step 2 re-baseline spec names. The candidates are spec 4.2's files plus this plan's additions:
  - `tests/test_story_engine.py`, `tests/test_narrative_fidelity.py`, `tests/test_pinned_cast.py`, `tests/test_dialogue.py`, `tests/test_speaker_attribution.py` and `tests/test_shot_format.py`;
  - `tests/fixtures/pinned_cast/uncast_chained_lines.txt`, `uncast_chained_seed.txt` and `uncast_shots_lines.txt`.
- Never: `tests/fixtures/writer_pacing/**` and `tests/fixtures/narrative_fidelity/**` (recorded artifacts); `tests/test_soft_panel_count.py`; `tests/test_movie_ui_builder.py` (Task 8); and any pipeline file.

**Interfaces:**
- Consumes: the commits of Tasks 1-6, `$D/expected-failures.txt` and `$D/task-6-pytest.txt`.
- Produces:
  - `$D/rebaseline-diffs.txt`;
  - `$D/rebaseline-spec.md`, from the Opus pass;
  - `$D/rebaseline-commit-msg.txt`;
  - one test-only commit.

- [ ] **Step 1: Collect every lost test with its full diff (executor).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/sp-baseline
cd $S/sp-wt/qwen-agent-workspace
python3 -B $D/gate.py $D/baseline-pytest.txt $D/task-6-pytest.txt $D/expected-failures.txt 6 | grep '^LOST' | awk '{print $2}' | grep -v test_mut26 > $D/rebaseline-ids.txt
wc -l < $D/rebaseline-ids.txt
python3 -B -m pytest -q -p no:cacheprovider --tb=long -vv $(cat $D/rebaseline-ids.txt) > $D/rebaseline-diffs.txt 2>&1; tail -1 $D/rebaseline-diffs.txt
```

Expected: the count of lost tests other than `test_mut26` (23 if the list was exact), and a summary line `N failed`, where N is that count. Report N to the controller.

- [ ] **Step 2: The re-baseline spec (controller; an Opus `spec-author` or `investigator`; not an executor step).**

Give it these inputs:
- spec 4.2, with its rule and RB1-RB9;
- this plan's RB10 and Plan rulings;
- `$D/rebaseline-ids.txt` and `$D/rebaseline-diffs.txt`.

It writes `$D/rebaseline-spec.md`, which holds:
- **(a) A code for every test.** Each test gets the RB code(s) that explain every line of its diff.
  - A diff line that no code explains is a defect. It is fixed in the pipeline code by a fix commit on the owning task's files, and the task gate is re-run, before any test edit.
- **(b) The exact edits, per file.** For each file, the exact Edit steps (old text, new text) that update each changed assertion or golden literal to the value the diff shows.
  - No test is deleted, and no assertion is weakened beyond the new behaviour.
  - The three `tests/fixtures/pinned_cast/uncast_*.txt` plan-prompt fixtures are updated by Edit steps too (Plan ruling PR10).
    - Their diff against `9952d81` must be exactly: the count text, the `PANEL_COUNT_RULE` sentence, the `LINES_RULE`/`LINES_PINNED_SENTENCE` text where present, and the `SPEAKING_BEAT_SENTENCE` tail (RB1, RB7, RB9).
    - The arc rule does not change: the fixtures are 3-panel and 4-panel prompts.
  - The re-baseline spec also gives one read-only check command. It compares each edited fixture with `build_plan_prompt`'s output for its `FIXTURE_CASES` entry, under a temporary HOME, character library and LoRA catalog. Expected output: three `same <name>` lines.
  - Two tests keep their intent, not just their literals:
    - `test_nf31_an_infeasible_line_set_exits_2_before_any_call` moves to a narrative whose lines need more than N+2 panels, so it still exits 2 before any call (RB6). An EIGHT-style four-line narrative at `--panels 1` does this; the SPC3 text is the example in spec SPC3.
    - `test_sft23_the_narratives_exit_after_its_last_line` keeps every row. Only the `'... and the ronin leaves the frame.'` row's expected value becomes `None` (RB10).
- **(c) The commit message body.** One paragraph per changed file. Each paragraph names the tests, the codes, and, in one sentence per golden, what changed (spec 4.2 rule). The message ends with the trailer line.

- [ ] **Step 3: Apply the re-baseline spec exactly (executor).**

Make every Edit of `$D/rebaseline-spec.md` (b) in order. Write its message (c) to `$D/rebaseline-commit-msg.txt` with the Write tool. If an old text does not occur exactly once, stop and report. Run the fixture check command and confirm its expected output.

- [ ] **Step 4: Verify (executor).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/sp-baseline
cd $S/sp-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider $(cat $D/rebaseline-ids.txt) 2>&1 | tail -1
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/task-7-pytest.txt 2>&1; tail -1 $D/task-7-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/task-7-pytest.txt $D/expected-failures.txt 7 | grep -E '^(LOST|GATE)'
git diff --name-only | grep -v -E '^qwen-agent-workspace/tests/' || echo "tests only"
git diff --name-only | grep -E 'writer_pacing/|narrative_fidelity/|test_soft_panel_count|test_movie_ui_builder' || echo "no forbidden file"
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1
```

Expected:
- `N passed`;
- the full-suite summary `3 failed, 1973 passed, 2 skipped`: the two baseline failures plus `test_mut26`, and 1931 - 1 + 43 passed;
- exactly one `LOST` line, `test_mut26 ... listed`, then `GATE PASS`;
- `tests only`, `no forbidden file` and `OK 347/347`.

- [ ] **Step 5: Review (controller; Opus `design-reviewer`).**

The reviewer checks every paragraph of `$D/rebaseline-commit-msg.txt` against `git diff`. Each changed line must trace to its stated code, and no assertion may be weakened. Fix every finding through Steps 2-4 before Step 6.

- [ ] **Step 6: Commit (test-only; spec 0.4 G6).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/sp-wt/qwen-agent-workspace
git add $(git diff --name-only --relative)
git diff --cached --name-only    # expected: only qwen-agent-workspace/tests/... paths, as listed in the re-baseline spec
tail -1 $S/sp-baseline/rebaseline-commit-msg.txt    # expected: Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
git commit -F $S/sp-baseline/rebaseline-commit-msg.txt
```

The subject line of the message is `test: re-baseline the existing tests to the soft panel count (spec 4.2)`.

---

### Task 8: Whole-branch review, the test_mut26 re-baseline (G7), SPK1-SPK2 and the hand-off

**Files:**
- Modify: `tests/test_movie_ui_builder.py`: the `test_mut26` comment and `BASELINE` (`:283-285`).

**Interfaces:**
- Consumes: the commits of Tasks 1-7.
- Produces: `$D/final-pytest.txt`, and the G7 commit.

- [ ] **Step 1: Design review (controller; spec 6 step 3).**
  - Ask an Opus `design-reviewer` to review `git diff 9952d81..HEAD -- qwen-agent-workspace` against the spec, this plan's rulings and the Review Focus.
  - Fix every finding in a new commit on the owning task's files. Then re-run that task's Step 4 and Task 7 Step 4. If a fix changes a re-baselined value, apply a follow-up test-only commit through Task 7 Steps 2-6.

- [ ] **Step 2: Find the last pipeline commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sp-wt/qwen-agent-workspace
git log -1 --format='%H %s' -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py
```

Expected: one line. It is a 40-character SHA, then the subject of Task 6's commit, which touches `bin/iterate-story`, or of the Step 1 fix commit if that commit touched a `PIPELINE_FILES` entry. In Step 3, **SHA** means exactly those 40 characters, typed in place of the word `SHA`.

- [ ] **Step 3: Re-baseline test_mut26 (spec G7).**

**3.1.** Edit `tests/test_movie_ui_builder.py` (the comment): replace this text, which occurs exactly once:

```python
then to 42f33640cd008021a32dc0f8f948d0e8da04de2b (shot prompt format).
```

with:

```python
then to 42f33640cd008021a32dc0f8f948d0e8da04de2b (shot prompt format), then to SHA (soft panel count).
```

**3.2.** Edit `tests/test_movie_ui_builder.py` (the baseline): replace this text, which occurs exactly once:

```python
    BASELINE = "42f33640cd008021a32dc0f8f948d0e8da04de2b"
```

with:

```python
    BASELINE = "SHA"
```

**3.3.** Run this command:

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sp-wt/qwen-agent-workspace
SHA=$(git log -1 --format=%H -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py)
grep -c "$SHA" tests/test_movie_ui_builder.py
grep -c "(shot prompt format), then to $SHA (soft panel count)." tests/test_movie_ui_builder.py
grep -c "    BASELINE = \"$SHA\"" tests/test_movie_ui_builder.py
git diff --numstat -- tests/test_movie_ui_builder.py
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py -k mut26 2>&1 | tail -1
```

Expected, in order: `2`, `1`, `1`, then `2	2	qwen-agent-workspace/tests/test_movie_ui_builder.py`, then `1 passed, 11 deselected`. If any value differs, fix the Edit, not this command.

- [ ] **Step 4: Commit (test-only; spec 0.4 G7).**

```bash
git add tests/test_movie_ui_builder.py
git diff --cached --name-only    # expected: only qwen-agent-workspace/tests/test_movie_ui_builder.py
git commit -m "test(movie-ui): re-baseline mut26 to the soft panel count pipeline commit" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: SPK1, the full suite against the baseline (about 15 minutes).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/sp-baseline
cd $S/sp-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/final-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt; tail -1 $D/final-pytest.txt
diff <(grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt | sort) <(grep -E '^(FAILED|ERROR)' $D/final-pytest.txt | sort) && echo "same failures, same messages"
diff <(grep -E '^PASSED' $D/baseline-pytest.txt | sort) <(grep -E '^PASSED' $D/final-pytest.txt | sort) | grep '^<' || echo "no lost pass"
grep -c '^PASSED tests/test_soft_panel_count.py::' $D/final-pytest.txt
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1
```

Expected:
- the final summary `2 failed, 1974 passed, 2 skipped`: the baseline's `2 failed, 1931 passed, 2 skipped` plus the 43 new tests;
- `same failures, same messages` (SPK1), `no lost pass`, `43` and `OK 347/347`.

If `test_trt41a` failed in one run only, rerun it alone and record both results. Any other difference: stop and report.

- [ ] **Step 6: SPK2, the unchanged files and the verbatim spec text.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sp-wt/qwen-agent-workspace
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' story_engine.py bin/ltx-movie bin/iterate-story movie_ui_lib.py tests/test_soft_panel_count.py tests/test_movie_ui_builder.py; done
git diff 9952d81 -- story_engine.py bin/ltx-movie bin/iterate-story movie_ui_lib.py | grep -E '^[+-]\s*(import|from) ' || echo "no import change"
git diff --name-only 9952d81 -- character_lib.py bin/ltx-story-manifest bin/ltx-story-images bin/ltx-mlx-render movie_ui_server.py bin/judge-story bin/judge-clips bin/judge-stills tests/fixtures/writer_pacing tests/fixtures/narrative_fidelity | wc -l
python3 -B - <<'EOF'
import re
spec = open("docs/superpowers/specs/2026-10-29-soft-panel-count-design.md", encoding="utf-8").read()
blocks = re.findall(r"```(?:python|js|html)\n(.*?)```", spec, re.S)
code = "".join(open(p, encoding="utf-8").read() for p in (
    "story_engine.py", "bin/ltx-movie", "movie_ui_lib.py", "bin/iterate-story",
    "static/movie-ui/app.js", "static/movie-ui/index.html"))
verbatim = [1, 2, 3, 4, 5, 6, 7, 11, 12, 13, 15, 17, 19, 20, 21, 22, 23, 24, 26, 27, 28, 29, 30,
            31]
nested = [9, 10, 14]
dedent = lambda b: "\n".join(l[2:] if l.startswith("  ") else l for l in b.split("\n"))
print("%d of %d spec code blocks verbatim; %d of %d at their list indent" % (
    sum(blocks[i] in code for i in verbatim), len(verbatim),
    sum(dedent(blocks[i]) in code for i in nested), len(nested)))
EOF
```

Expected, in order:
- `compiled 6` twice (SPK2);
- `no import change` (SPK2);
- `0` (spec 0.4 "Not changed", and the recorded fixtures);
- `24 of 24 spec code blocks verbatim; 3 of 3 at their list indent`.

The spec blocks not checked are each explained:
- 0 (`StoryContext`, SPR2's `length`), 8 (SPC3, SPR2's `--length` branch), 16 (SPC11, SPR1's `plan["cast"]`) and 18 (SPC12, SPR2's `--length` hints);
- 25, the `app.js` line before the change;
- 32, the Section 5 measure script, which is not code in the repo.

- [ ] **Step 7: Hand-off (controller; not an executor step).**
  - Report the branch `sp-impl` and its commits.
  - Push and the merge into `qwen-agent-redteam` are a separate step that needs the user's approval.
  - Put the spec 6 PR note in the PR description.
  - The live checks below run after the merge.

---

## Post-merge: live acceptance (coordinator only; spec 5; not a task and not a merge gate)

The coordinator runs these after the merge, never an implementer:
- They start the local story server, which loads a model on `:8177`, and they render once. Both need the user's go-ahead.
- This Mac only, never macstudio. Never touch `:8178`. Never read `~/.zshenv` or `fleet.env`.
- Run them as spec Section 5 writes them, with the one amendment below. This checklist is not a substitute.

- [ ] **Preconditions.** Both specs are merged into WS, and no render is running: `pgrep -f ltx-mlx-render` prints nothing.
- [ ] **Setup** (spec 5.1). `R=$S/softcount-live` (new, empty). `NH`, `NP` and `G` come from the repo, as spec 5.1 says. Start the story server exactly as [SF] Section 5.1 does, and stop it with `bin/story-server stop` after the last story run and before the render.
- [ ] **The nine story runs** of the spec 5.1 table: `spc-hk2-a`, `spc-hk2-b`, `spc-hk1-a`, `spc-hk1-b`, `spc-hk3s`, `spc-ch3`, `spc-sh4`, `spc-sh2` and `spc-sil3`. Each logs to `$R/run-<id>.log`, and the coordinator echoes `<id> exit $?`.
- [ ] **One render**, `spc-hk2-a`, after `bin/story-server stop`, exactly as spec 5.1 writes it. It has no `--story-only` and no `--force-story`.
- [ ] **Measure** (spec 5.2), saved as `$R/measure_spc.py`, with Plan ruling SPR1's amendment. The line `found = se.narrative_exit_after_last_line(plan["narrative"]) if lines else None` reads `found = se.narrative_exit_after_last_line(plan["narrative"], plan["cast"]) if lines else None`. Then the render record into `$R/render.txt`.
- [ ] **KPIs** (spec 5.3) L1-L7 on `measure.txt` and `render.txt`:
  - L1: all 9 runs exit 0, in range, with `panels_target` and `checks` right.
  - L2: `exit_beat True` in at least 3 of the 4 hockey runs, and `P19 0` wherever `exit_beat True`.
  - L3: P20 and the note appear exactly when the count differs, and the render log has the one note with the same reason and `; Phases 2-4 use all <n>`.
  - L4: at most 1 inflation among `spc-ch3`, `spc-sh4` and `spc-sil3`, and none at `target + 2`.
  - L5: `lines_ok`.
  - L6: static cap.
  - L7: the render's panel count and duration.
- [ ] **Recorded, not gating** (SPR2; no server needed): `bin/ltx-movie "$NH" --length 12 --frames 145 --story-id spc-len-dry --speech-only --dry-run --no-review | grep '^Panel count:'`. Expected (probed on the replayed tree): `Panel count: a target of 2; the plan may have 2 to 4 beats, and Phases 2-4 use the plan's count.` The dry run never contacts the story server. Record the line.
- [ ] **Report:** L1-L7 with `measure.txt` and `render.txt`, the recorded rows (spec 5.3), the exit codes and the PR note.

---

## Coverage

### Spec section to task

| Spec | Task(s) |
|---|---|
| 0.4 G1 (`story_engine.py`, SPC1-SPC12) | 1 (SPC1-SPC5, SPC12 b), 2 (SPC12 a), 3 (SPC6-SPC9, SPC11), 4 (SPC10) |
| 0.4 G2 (`bin/ltx-movie`, SPC13) | 5 |
| 0.4 G3 (movie UI, SPC14, SPC16) | 6 |
| 0.4 G4 (`bin/iterate-story`, SPC15) | 6 |
| 0.4 G5 (`tests/test_soft_panel_count.py`) | 1-6 (see the next table) |
| 0.4 G6 (re-baseline, test-only) | 7 |
| 0.4 G7 (`test_mut26`) | 8 steps 2-4 |
| 0.4 Not changed | 8 step 6 (`git diff` checks); the gate's must-stay-green files in every task |
| 0.5 Out of scope | nothing built; the legacy path: SPT15 (`--story-legacy` row) |
| 0.6 SPK1 | Before Task 1 step 4 (baseline), every Step 4 gate, 8 step 5 |
| 0.6 SPK2 | `test_spt1_the_pipeline_files_compile_under_both_pythons`; every compile check; 8 step 6 |
| 0.6 SPK3 | 1 (SPT2, SPT4), 3 (SPT6, SPT10, SPT24) |
| 0.6 SPK4 | 3 (SPT8), 5 (SPT15, SPT16, SPT25) |
| 0.6 SPK5 | 3 (SPT8, SPT9, SPT11), 5 (SPT16) |
| 0.6 SPK6 | 1 (SPT3, SPT4) |
| 0.6 SPK7 | 4 (SPT14), 5 (SPT15), 6 (SPT20) |
| 0.6 SPK8 | 1 (SPT4 g), 2 (SPT13), 3 (SPT19) |
| 0.6 SPK9 | 6 (SPT20) |
| 0.6 SPK10 | Post-merge checklist |
| 0.6 SPK11 | 6 (SPT26, SPT27) |
| D1 | 1 (fields), 3 (the swap) |
| D2 | 1 |
| D3 | 1 |
| D4 | 3 |
| D5 | 2 |
| D6 | 4, 5, 6 |
| D7 | 5 |
| D8 | 3 (engine), 5 (dry run) |
| D9 | 1 (prompt), 3 (P18) |
| D10 | 3 (SPT8 chained, SPT19 shots, Review Focus 3 `no_stills`) |
| D11 | 6 |
| D12 | 5 |
| SPC1-SPC5 | 1 steps 3.1-3.14 |
| SPC6, SPC7 | 3 steps 3.1-3.4 |
| SPC8 | 3 step 3.5 |
| SPC9 | 3 steps 3.6-3.9 |
| SPC10 | 4 steps 3.1-3.3 |
| SPC11 | 3 step 3.10 |
| SPC12 (a) | 2 step 3.1 |
| SPC12 (b) | 1 step 3.6 |
| SPC12 (c) | spec text only (coordinator; Plan ruling PR13) |
| SPC13 | 5 steps 3.1-3.7 |
| SPC14 (a) | 6 steps 3.1-3.3 |
| SPC14 (b), (c) | 6 steps 3.4, 3.7 |
| SPC15 | 6 step 3.9 |
| SPC16 | 6 steps 3.5, 3.6, 3.8 |
| 3 Interactions | pre-flight: 1 (SPT3); plan prompt: 1 (SPT4); plan retry: 3 (SPT10, Review Focus 1); after the plan: 3 (SPT8, SPT11, SPT19); round 0, critic, code-only: 3 (SPT8, Review Focus 5); chained, shots, `no_stills`: 3; `--no-narration`: 1 (SPT2, SPT4 d); recheck and reuse: 4 (SPT14, Review Focus 2); re-check and render runs: 5 (SPT16 b); `--force-story`: 5 (SPT15); `--redo`: 5 (SPT15); manifest: 5 (SPT18); movie UI: 6; iterate-story: 6; legacy: 5 (SPT15) |
| 4.1 | 1-6 |
| 4.2 | the gate (1-6), 7 |
| 4.3 | the gate's must-stay-green files (1-7) |
| 5 | Post-merge checklist |
| 6 rollout | Before Task 1 (snapshot, worktree, baseline); 1-6 (feature commits); 7 (G6); 8 (review, G7, SPK1, SPK2) |
| Coordinator additions (a), (b) | 2 (SPR1, SPR2 hints), 1 (SPR2 pre-flight), 3 (SPR1 in P20), 5 (SPR2 plumbing) |

### Test IDs and their owning task (each is owned by exactly one task)

| IDs | Task |
|---|---|
| SPT1 (engine constants, compile check), SPT2, SPT3, SPT4, SPT5, SPT22, SPT23, SPR2 (pre-flight) | 1 |
| SPT1 (P19 constants), SPT13, SPR1 (a, b), SPR2 (P19 hint) | 2 |
| SPT1 (P20 constants), SPT6, SPT7, SPT8, SPT9, SPT10, SPT11, SPT12, SPT19, SPT24, SPR3, Review Focus 1, 3, 5 | 3 |
| SPT14, Review Focus 2 | 4 |
| SPT1 (`bin/ltx-movie` constants, `--panels` help), SPT15, SPT16, SPT17 (with Review Focus 4), SPT18, SPT25, SPR2 (plumbing, end to end) | 5 |
| SPT1 (movie UI constants), SPT20, SPT21, SPT26, SPT27 | 6 |
| the G6 re-baseline | 7 |
| MUT26 (G7); SPK1, SPK2 measured; SPK10 hand-off | 8 |

### Self-review

- **Spec coverage.** Every requirement (SPC1-SPC16) and every test (SPT1-SPT27) maps to a task in the tables above. G1-G7 and SPK1-SPK11 each have a step. The coordinator additions (a) and (b) are rulings SPR1 and SPR2, with tests in Tasks 1, 2 and 5.
- **Placeholders.**
  - The only symbolic values are `$S`, `$WS`, `$D` and `N` (the gate block), each defined in its block or in the house rules.
  - The word `SHA` in Task 8 Step 3 is the value Step 2 prints.
  - The contents of Task 7's `$D/rebaseline-spec.md` are produced by an Opus pass from measured diffs. This plan's author was not permitted to run the suite (see "Between tasks"). That one hand-off is deliberate, and it is the reason Task 7 has a classification step.
- **Type consistency.**
  - `panel_range(ctx)` returns `(lo, hi)` in SPC4, SPC7, the dry run (SPC13 e) and the tests.
  - `target_panels(ctx)` and `most_panels(ctx)` are used by name in Tasks 1-5.
  - `narrative_exit_after_last_line(narrative, cast=())` is called with `plan["cast"]` in both engine callers (Tasks 2, 3) and in the amended measure script.
  - The P19 hint formats are `(most, n+1)`, `(most, target, n+1)`, `(most, seconds, n+1)` and `(most, target, seconds, n+1)` in the code and every test.
  - `save_story(ws, tmp_path, monkeypatch, story_id, mode, target, beats)` has the same order in every test.
  - `effective_panels(fields, sdir)` and `plan_panels(sdir, mode)` keep the spec's argument orders.
- **Review Focus.** Five inputs, each with a test in its owning task (Tasks 3, 4 and 5).

## Plan rulings (where the spec's code and its own tests cannot both hold, the spec needs a reading, or the coordinator added a requirement)

The **[coordinator]** rulings come from the two parked additions. The **[defect]** rulings change behaviour from what the spec literally writes. The controller should confirm SPR3-SPR5 with the user before Tasks 3-5.

1. **SPR1 [coordinator (a)]: P19 counts only an exit whose subject is the last line's speaker.**
   - **The rule.** `narrative_exit_after_last_line(narrative, cast=())` looks at every `EXIT_RE` match in the text after the closing quote of the last spoken line, in order. It returns the first match whose subject is the speaker's.
   - **The subject.** It is `_clause_tail` of the text from that closing quote to the match:
     - the last `_CLAUSE_BREAK_RE` piece (`[.!?;,]`);
     - then the words after that piece's last `CLAUSE_STOP_WORDS` word ("and", "then", "as", "but", "while", "before", "after", "until", "so", "or", "when");
     - without adverbs, meaning any word that ends in "ly" and begins with a lower-case letter, so "Holly" is kept.
   - **It is the speaker's when** one of these holds:
     - (i) it is empty: the line's own sentence goes on ("... says "It's just FuboTV." then skates away");
     - (ii) it is exactly "he", "she" or "they";
     - (iii) without a leading "the"/"a"/"an", it equals a name of the speaker. A name is either:
       - the words before the speech verb in the `_clause_tail` of the text that leads up to the line ('Kyra says, "Go."' gives `kyra`);
       - or, with `cast`, a phrase or library name of the cast entry that `line_speakers(narrative, cast)` gives the last line.
   - **Callers.** Both engine callers pass `plan["cast"]`: `exit_left_out_notes` (P19) and `panel_count_notes` (P20's exit reason). So the two never disagree about the exit.
   - **Tested** by `test_spr1a_the_exit_subject_rule` (22 rows), `test_spr1b_p19_ignores_an_exit_by_anyone_else` and SPT11/SPT12/SPT13. "the crowd drifts away" and "the puck moves off the ice" never fire. "The crowd drifts away, and she skates off." fires on "skates off".
   - **Known limit (accepted).** A named subject that is neither the narrative's attribution words nor an attributed cast name does not count. For example, "The skater says "Go." The hockey player skates away." gives `None`. P19 then stays silent. That is a missed notice, never a false one.
   - **Re-baseline.** RB10: one SFT23 row (`'... and the ronin leaves the frame.'`) becomes `None`.
   - **Spec amendment text** (for SF-A1, SPC11 and SPC12):
     > "An exit after the last spoken line counts for P19 and for P20's exit reason only when its subject is that line's speaker: the clause has no subject of its own, its subject is he, she or they, or its subject (without a leading article) names the speaker by the words of the line's attribution clause or by a phrase or library name of the plan cast entry the narrative gives the line. `narrative_exit_after_last_line(narrative, cast=())` implements this; both callers pass `plan["cast"]`. Section 5.2's measure script passes `plan["cast"]` too."
2. **SPR2 [coordinator (b)]: with `--length`, no count hint suggests `--panels`.**
   - **The plumbing.** `StoryContext` gains a last field, `length` (default `None`): `bin/ltx-movie`'s `--length` in seconds, set by `_story_context` (`length=getattr(args, "length", None)`). `length_for(ctx, panels)` is `"%.1f" % (panels * engine_seconds(ctx))`. That is the `--length` that `_resolve_length` (`round(length / (frames / fps))`) resolves back to `panels`.
   - **Why one decimal is exact.** The rounding error is at most 0.05 s, and a clip is at least 9/24 s at 24 fps. So the ratio is off by less than 0.14 and rounds to `panels`. It stays exact up to `fps` 60 (error below 0.34). Tests pin `round(18.1 / (145/24)) == 3` and `round(30.2 / (145/24)) == 5`.
   - **The hints.** When `ctx.length is not None`:
     - P19 uses `P19_ROOM_HINT_LENGTH` / `P19_CAP_HINT_LENGTH`. They name `--force-story --length <seconds>` and give the panel count only as information ("(a target of N panels)").
     - The SPC3 pre-flight uses `LINES_LENGTH_PROBLEM`. This extends (b) from P19/P20 to the one other count hint; see Question Q1.
   - **P20.** It needs no change. `P20_NOTE` and its reasons name no flag: "this movie has 4 panels, 1 more than its target of 3, because ..." is information.
   - **What stays verbatim.** The spec's `--panels` texts and code paths are kept verbatim; the `--length` branch is added in front of them.
   - **Spec amendment text** (new D13, and SPC1, SPC3, SPC12, SPC13 d):
     > "D13. When `--length` sized the movie, no count hint names `--panels` (the two flags are mutually exclusive). `StoryContext` gains `length` (None unless `--length` was given); `length_for(ctx, n)` is the `--length` that resolves to n panels, to one decimal. The pre-flight beyond N+2 says `rerun with --force-story --length <s> or more (a target of <n> panels)`, and P19 says `rerun with --force-story --length <s> (a target of <n> panels) to keep it`. P20 names no flag and is unchanged."
3. **SPR3 [defect]: `lora_checks` uses `n = plan["panels"]`, not `len(plan["beats"])`.**
   - Spec 4.3 requires `tests/test_lora_catalog.py` to pass unchanged. Its `_catalog_story` writes a saved plan with `"panels": 3`, `"beats": []` and a `per_beat` key `"2"`, which `bin/ltx-movie`'s `_catalog_checks_error` checks.
   - With SPC7's `len(plan["beats"])`, every `per_beat` key is "not a beat number from 1 to 0". Every catalog test then gets the LC13 error, and so does SPT16 (c) as the spec writes it.
   - `plan["panels"]` is the beat count for every plan `normalize_plan` builds (SPC6). It is the saved count for every `plan.json` that `load_plan` or `_catalog_plan` accepts. So SPC7's intent, accepting a key up to the plan's own count during `plan_round`, holds.
   - Tested by `test_spr3_lora_checks_use_the_plans_panel_count`, SPT6's L1 rows and SPT16 (c).
   - **Spec amendment:** SPC7's last paragraph reads "`n = ctx.panels` becomes `n = plan["panels"]`".
4. **SPR4 [defect]: `recheck` ignores a stale plan whose count `story.md` does not have.**
   - With SPC10 alone, take a 4-panel `plan.json` left beside a 3-panel `story.md`, which D6 names as the stale case: after a later `--story-legacy` run or a hand edit. `recheck` at `--panels 3` then adopts 4, and `legacy_validate` fails the story ("expected exactly 4 panels, found 3").
   - At `9952d81`, `load_plan` refused that plan, and the plan-free re-check passed. `bin/ltx-movie`'s resolver does check the `story.md` count (D6), but `recheck` re-reads `plan.json` itself.
   - **Ruling:** before SPC10's adoption block, when `plan["panels"] != ctx.panels` and `story.md` parses to a different count, `plan = None`.
   - Unchanged by this ruling:
     - a plan with `plan["panels"] == ctx.panels` keeps today's behaviour;
     - `recheck` still never calls `plan_checks` or `line_speakers` (`test_sat10`).
   - Tested by Review Focus 2.
   - **Spec amendment:** SPC10 gains "a plan whose `panels` differ from `ctx.panels` is used only when `story.md` has that many panels".
5. **SPR5 [defect]: the dry run's `Panel count:` line follows the rendered prompt, not the command line.**
   - SPC13 (e) puts it before the blank line after `Command (...)`. `test_rst47` takes everything between `Command (subprocess timeout 600s): ` and `\n\nRendered plan prompt:\n` and passes it to `shlex.split`. That would include "... use the plan's count.", whose apostrophe raises `ValueError: No closing quotation`.
   - **Ruling:** the block goes after the `print()` that ends the rendered prompt, followed by its own `print()`. It stays inside the Phase 1 block, which ends at the next `--- Phase ` line, so SPT17 holds and `test_rst47` is unchanged.
   - **Spec amendment:** SPC13 (e) "Immediately after the `print()` that follows `print(prompt)`, add: ... then `print()`".
6. **PR1: two SPT values corrected.** `TURNS` has four sentences, and `character_lib.DIALOGUE_MAX_FRAGMENTS` is 3, so the four lines need 2 panels even with one speaker.
   - SPT2's row "`TURNS` uncast, `panels=1` → `(1, 3)`" is `(2, 3)`.
   - SPT23's "with all `None` → 1" is `2`.
   - SPT3's "the same ctx uncast → `None`" holds (2 <= 3).
7. **PR2: SPT17 and SPT18 run in-process.**
   - A `bin/ltx-movie` subprocess resolves `WS` from its own real path, so it can never see the temp `movie` workspace's story (SPT17's third case). SPT17 calls `ltx_movie.main([... "--dry-run", "--no-review"])` with `capsys`.
   - A `bin/ltx-story-manifest` subprocess would write `generated/stories/x/manifest.json` into the real workspace. SPT18 calls `manifest.main(argv)` with `manifest.WS` patched to the temp workspace, as `tests/test_shot_format.py`'s SFT14 does.
8. **PR3: SPT26's HTTP check and SPT27 live in the new file.** G5 lists SPT1-SPT27 in `tests/test_soft_panel_count.py`. The `ui_env` fixture is `tests/test_movie_ui_http.py`'s `env`, copied.
9. **PR4: SPT14's "spy saw 1".** The plan-free path calls `legacy_validate` twice: the re-check, then `_undeclared_gate`'s `plan_free_report`. The test asserts `set(seen) == {1}`; with a plan it asserts `seen == [4]`.
10. **PR5: SPT1 is split by task (1a-1e), and the compile check runs `compile()` in a subprocess of each interpreter.** That is the same syntax check as `py_compile`, with no `.pyc` written. When `/usr/bin/python3` is absent, only `sys.executable` is checked (the spec's "else skip").
11. **PR6: comment placement.** "; soft panel count spec SPC2" is inserted before each comment's final full stop, and the line is wrapped at 100 columns.
12. **PR7: `@@MIN_BEATS@@` takes the scalar slot of the removed `@@PANELS@@`.** The order of scalars does not matter.
13. **PR8: eight commits.** That is six feature commits, one per task, instead of spec 6's single feature commit, plus G6 and G7 as separate test-only commits (Tasks 7, 8), as in the prior plans.
14. **PR9: approach B for the existing suite**, as justified in "Between tasks". RB10 is added for SPR1.
15. **PR10: the Task 7 fixture updates are Edit steps.** The controller rule "executors make every tracked-file change with the Edit tool" allows no regeneration command. A read-only check compares each fixture with `build_plan_prompt`.
16. **PR11: line-cite drift (`6f16063` → `9952d81`).** [SF] moved `story_engine.py`; every Edit finds its anchor by content, and the old texts are `9952d81`'s. The main moves (spec cite → `9952d81`):
    - `StoryContext` `:82-86` → `:93-97`, and its comment `:87-91` → `:98-102`;
    - `engine_seconds` `:94-96` → `:105-107`;
    - template `:306-307` → `:317-319`;
    - `LINES_RULE` `:371-377` → `:394-401`, and `LINES_PINNED_SENTENCE` `:380-382` → `:402-406`;
    - `panels_needed` `:719-728` → `:743-752`, and `spoken_lines_problem` `:731-761` → `:755-785`;
    - `_arc_rule` `:788-794` → `:812-818`;
    - `build_plan_prompt` `:917-979` → `:941-1003`, with `@@ARC_RULE@@` at `:982` and the scalars at `:1002-1004`;
    - `normalize_plan` `:1079-1146` → `:1105-1175`;
    - `plan_checks` `n` `:1542` → `:1838`, and P5/P6/P10 → `:1916`/`:1925`/`:1946`;
    - `lora_checks` `n` `:1747` → `:2043`;
    - `_checks_doc` `:3458` → `:4070`;
    - `_Run.__init__` `:3471` → `:4083`, and `plan_round` `:3545` → `:4157`;
    - `go`'s accepted plan `:3771` → `:4383`;
    - `load_plan` `:3873` → `:4497`, and `recheck` `:3969` → `:4603`;
    - the [SF] names are at `:60` (`max_static`), `:365` (`SPEAKING_BEAT_SENTENCE`), `:376` (`CAMERA_RULE`), `:1387`/`:1392` (P18), `:1625` (`EXIT_RE`) and `:1638-1670` (SF-A1).
    - `bin/ltx-movie`, `movie_ui_lib.py`, `static/*` and `bin/iterate-story` are unchanged since `6f16063`, so their cites hold.
    - SF-A1's P19 hint at `9952d81` already carries CR1's `--force-story` (spec 0.5's "[SF] amendment").
17. **PR12: the 4.2 inventory, re-read at `9952d81`.**
    - Added:
      - `test_story_focus_2_a_one_panel_story` (RB2, "use climax.");
      - `test_nf28`, `test_nf29` and `test_nf33` (RB7: [SF]'s re-baseline pinned `P19_NOTE` there);
      - `test_sft23` (RB10);
      - `test_sat9_plan_prompt` (RB9: `se.LINES_RULE.replace("@@LINE_WORDS@@", ...)` leaves `@@MIN_BEATS@@`).
    - Moved:
      - `test_rst8` `:269/:271` → `:272/:274`;
      - `test_rst11` `:1567-1568` → `:1611-1612`;
      - `test_rst39` `:1759/:1765` → `:1806/:1812`;
      - `test_pinned_cast.py` `:384` → `:391` (`test_review_focus_1_an_exhausted_plan_lists_every_fatal_problem`);
      - `test_narrative_fidelity.py` `:678` → `:682`.
    - `test_dlg12` is RB7 only.
18. **PR13: SPC12 (c)** amends [SF] Section 0.5's text. It needs no code, and the coordinator patches the [SF] spec.
19. **PR14: test readings.**
    - `save_story` takes `(ws, tmp_path, monkeypatch, ...)`, because `seu.script_agent` needs them.
    - SPT16 is split into `test_spt16_spt25_...` (a, b, e and SPT25), `test_spt16c_...` and `test_spt16d_...`.
    - SPT16 (c)'s `plan.json` has `"beats": []`, as `_catalog_story`'s does; SPR3 keeps it valid.
    - SPT11's panel replies are courier replies, as [SF]'s SFT25 uses.
    - Story ids: `s0`, `s1`, `s6`, `sh4`, `spt3`, `spt8`-`spt11b`, `spt19`, `spt24a`, `spt24b`, `rf1`-`rf5`, `rf2b`, `m1`, `m1s`, `m2`, `m2s`, `m3`, `m5`, `c4`, `d1`, `d2`, `l1`-`l3`.

## Questions for controller

1. **Q1 (SPR2's reach).** The coordinator named P19/P20. This plan also gives the SPC3 pre-flight a `--length` wording, because it is the only other count hint and has the same mutual-exclusion problem. Keep it, or drop it? To drop it, remove:
   - `LINES_LENGTH_PROBLEM` and its branch (Task 1 steps 3.7, 3.9);
   - `test_spr2a_...`;
   - the `main()` half of `test_spr2c_...`.
2. **Q2 (SPR1's known limit).** A named subject that is neither the attribution words nor an attributed cast name does not count. For example, uncast "The skater says ... The hockey player skates away." This errs toward silence. Accept?
3. **Q3.** SPR3, SPR4 and SPR5 are behaviour rulings on spec defects. Confirm them, or have the spec amended, before Tasks 3, 4 and 5 start.
4. **Q4 (SPT26's HTTP half).** This plan reads "tests never contact servers" as model servers, daemons and other hosts. The spec's SPT26 requires an HTTP check. It talks to a movie-ui server that the test starts on `127.0.0.1`, exactly as the existing `tests/test_movie_ui_http.py` does. If the rule is meant strictly, drop the last four statements of `test_spt26_the_regenerate_argv` (from `body = mt.fields(...)`) and the `ui_env` server. The `validate_fields` part can use `mt.set_home` and `mt.make_stub_workspace` without `mt.Running`.

## Spec defects found (for the spec author)

1. SPR3: SPC7's `lora_checks` `n = len(plan["beats"])` breaks `tests/test_lora_catalog.py`, which spec 4.3 requires unchanged, and SPT16 (c).
2. SPR4: SPC10 adopts a stale in-range plan in `recheck`, a regression from `9952d81` for D6's own stale case.
3. SPR5: SPC13 (e)'s placement breaks `test_rst47`; the spec claims it is unaffected.
4. PR1: SPT2's `TURNS` uncast row and SPT23's all-`None` value assume fewer than four sentences fit one clip.
5. PR2: SPT17's third case and SPT18 cannot run as subprocesses: the WS resolution, and a write into the real tree.
6. PR12: spec 4.2 omits `test_story_focus_2_a_one_panel_story`, `test_sat9_plan_prompt` and the three `test_nf2x/nf33` P19 pins, and its line cites predate [SF].

## Execution handoff

Plan complete and saved to `qwen-agent-workspace/docs/superpowers/plans/2026-10-29-soft-panel-count.md`.

**How it was checked.** Every Create and Edit block of Tasks 1-6 lives in one data file, and this plan's blocks are rendered from it. A script replayed them in order on a scratch `git archive 9952d81` export, the way an executor applies them: one trailing newline stripped, and an exactly-once check.
- **Edits.** Each old text occurred exactly once at its turn.
- **Compile.** `story_engine.py`, `bin/ltx-movie`, `bin/iterate-story` and `movie_ui_lib.py` compiled under Python 3.9.6 and 3.13 after Task 6. `node --check` passed on `app.js`.
- **Probes.** A plain-Python runner, not pytest, called every test function of the new file against the replayed tree. It used stand-in `monkeypatch`, `tmp_path` and `capsys`, the `story_env` HOME, the fake agent, and a movie-ui server on `127.0.0.1` for SPT26. There was no model server and no render.
  - After each task, all of that task's tests passed: 9, 14, 28, 30, 38 and 43.
  - Against the previous task's code, the counts that fail first are the Step 2 counts above: 7, 5, 13, 2, 7 and 4.
  - Each defect showed in its own probe:
    - without SPR4, Review Focus 2's re-check exits non-zero;
    - with the spec's placement, `shlex.split` raises `No closing quotation` (SPR5);
    - `TURNS` gives `(2, 3)` (PR1).
- **Spec text.** The 24 spec blocks of Task 8 Step 6 occur verbatim in the replayed tree, and the 3 list-nested blocks occur at their code indent.
- **Not run, as instructed.** Neither the existing suite nor pytest was run. The existing-test failure list therefore comes from reading and grep at `9952d81`, and the per-task gate measures it.
- **Scratch.** Everything was written under `$S/spplan/`.

Please review the plan. Which execution approach would you prefer?
- **Subagent-driven.** A fresh Sonnet `code-executor` implements each task in `$S/sp-wt` on branch `sp-impl`, and a fresh Opus reviewer checks it before the next one starts. A whole-branch review follows at the end.
- **Native.** One session implements every task, then one fresh Opus reviewer checks the whole branch.

I recommend subagent-driven. Tasks 2-6 each consume names and data shapes from the tasks before them (`panel_range`, the ctx swap, `panels_target`, `_plan_panels`). Three tasks carry defect rulings that a per-task reviewer should confirm. A shipped mistake would silently render the wrong number of clips. Does the plan capture what you want, and which approach should we use?
