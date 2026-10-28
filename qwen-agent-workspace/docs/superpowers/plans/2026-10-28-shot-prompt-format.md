# Shot Prompt Format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A video prompt carries one planned camera move that the writer writes as a single end-framed camera sentence. Static is capped at one beat in three. A speaking panel is composed in a fixed order: shot, action, line, one reaction, camera, then the audio sentence last. Nobody leaves the frame or acts after the line, and speaking verbs are cut. The writer sees a format-only reference that a hard check keeps them from copying. The user is told when the narrative's exit after its last line cannot be filmed.

**Architecture:**
- **Engine (`story_engine.py`, stdlib only, no new import).**
  - Planner contract: SF1-SF5, the camera list and rule, the speaker rules, the speaking coercion and the P18 static cap.
  - Writer contract: SF6-SF8, `panel_camera`, the CM4 fix, the word ranges, the key lines and `FORMAT_REFERENCE`. Plan ruling PR1 adds `cleanup_pieces`.
  - Writer-format checks N7 (hard in generation), N20, N21 and N22, with deterministic parse-time repairs: SF9-SF12, SF13a, SF13c, SF14.
  - Repair plumbing: SF13b and SF13d-h, the round-0 re-ask, the trim, the critic and patch paths.
  - P19: amendment SF-A1, with coordinator ruling CR1.
- **`character_lib.py`:** the S4/S5 parameters (SF15c) and the fixed-order composer `panel_prompt` (SF15a-b).
- **`bin/ltx-story-manifest`:** composes speech movies with `panel_prompt` (SF16).
- **Tests:** one new file, `tests/test_shot_format.py`. A separate test-only task re-baselines the existing tests (G5), then `test_mut26` gets its own commit (G6).

**Tech Stack:**
- Python 3.13 (`python3` = `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`, pytest 8.3.4). Python 3.9.6 (`/usr/bin/python3`) is used for the compile check only. Standard library only.
- `tests/story_engine_testutil.py` (`set_story_env`, `make_ws`, `make_ctx`, `plan_json`, `panel_json`, `answer`, `script_agent`, `agent_log`, `kyra`, `ronin`, `COURIER`, `MONK`, `HARBOUR`) and the fake `bin/qwen-agent` it installs.

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-10-28-shot-prompt-format-design.md`, committed at `6f16063`. It includes Amendment SF-A1, and the user approved C1-C6 (spec 8.2).
- Its line numbers cite `3970e96`. The code tree of `6f16063` is `3970e96`'s; the only difference is the spec file. Every Edit below finds its text by content.
- The spec is binding. This plan changes no design decision except where the spec's code and its tests cannot both hold. Each such place is a numbered ruling in "Plan rulings". Coordinator ruling **CR1** (2026-10-28) replaces the P19 hint text (see Global Constraints).

## Global Constraints

From the spec, verbatim (section in brackets):

- [Status] "Every design choice is made here. Each choice the brief left open is marked **[spec choice]**, and Section 7 lists them all. The implementer makes no design decisions."
- [0.4 Not changed] "`movie_ui_lib.py`, `static/*`, `bin/ltx-movie` (including its legacy prompt at `:202`), `bin/judge-story` and `bin/ltx-mlx-render`."
- [0.4 Not changed] "`LINES_RULE`, `LINES_PINNED_SENTENCE`, `LINE_SPEAKERS_SENTENCE`, P16 and P17."
- [0.4 Not changed] "`speech_text`, `insert_speech`, `speech_sentence`, `SPEECH_BEATS`, `_is_camera_sentence`, `CAMERA_MOTION_RE`, `COPIED_EXAMPLES`, `RECHECK_IDS`, `PLAN_FREE_IDS`, `NON_BLOCKING_IDS`, `PLAN_MAX_CALLS`, `PANEL_MAX_CALLS`, `PANEL_MAX_TOKENS`, the `plan.json` schema and the `story_checks.json` shape."
- [0.4 G5] "Existing tests and fixtures | The re-baselines of Section 4.2, in a **separate test-only commit** whose body explains every changed file (Section 4.2 rule)".
- [0.4 G6] "`BASELINE` re-baseline in its own follow-up commit, as in [SA] G4. The comment gains `, then to <sha> (shot prompt format).`"
- [0.6 SK2] "`/usr/bin/python3` (3.9) and `python3` (3.13) both `py_compile` `story_engine.py`, `character_lib.py` and `bin/ltx-story-manifest`." (This plan checks it with `compile()`; see Plan ruling PR5.)
- [0.6 SK3] "None of the three files gains an import."
- [0.7] "SF1-SF16 and SFT1-SFT22 are must-haves. Nothing else is built: no CLI flag, no voice descriptors, no line splitting, no `no_stills` reordering."
- [4.1] "the module docstring states that no test renders, reads the real HOME, or contacts a model server, a daemon or the Anthropic API."
- [4.2 Rule] "A failure that no code explains is an implementation defect: fix the code, not the test." "No test is deleted. No assertion is weakened beyond the new behaviour."
- [4.2] "`tests/fixtures/writer_pacing/hockey-2x145-f/*`: the fixture files are **not** edited (they are recorded artifacts)."
- [6] PR note (required, in substance): "Phase 1 now plans one camera move per panel (static at most one panel in three) and tells the writer that move; the writer writes the one camera sentence with its end frame, and the pipeline's sentence is only a fallback. A speaking panel's final prompt is shot type, action, the line, one reaction, camera, then the audio sentence last; nobody leaves or acts after the line, speaking verbs are cut, and writers see a format-only reference that a hard check keeps them from copying. Old stories re-check exactly as before; regenerate one with `--force-story` (movie-ui: Regenerate)."
- [CR1, coordinator, 2026-10-28] The P19 hint reads "...; rerun with --force-story --panels %d to keep it". Without `--force-story`, rerunning with a new `--panels` re-checks the existing story and exits 1 with "expected exactly n panels". The coordinator amends the spec to match; everything else in SF-A1 stands. `P19_NOTE` below carries this text.

Controller rules, verbatim. Every task's requirements include them:

- tests never use the real HOME, never render, never contact servers
- never touch port 8178
- never read, cat, grep or source ~/.zshenv or fleet.env
- never stage .DS_Store, .claude/, agent/__pycache__/, repo-root bin/, qwen-agent-workspace/bin/action-from-dir
- no git stash/reset/checkout of others' work
- commit trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
- Python run with -B

House rules (from the prior plans; every task's requirements include them):

- **Where work happens.**
  - This Mac only. No ssh, scp, rsync, curl or HTTP, and never touch macstudio. Use no network.
  - Never start, stop or contact a model server (`:8177`, `:8178`). Never render, and never load a model.
- **The main checkout.** Never touch the main checkout `/Users/reubenpatterson/local_agent_harness`.
  - Every command runs in the worktree `$S/sf-wt`.
  - The only exceptions are the controller steps of "Before Task 1": the plan commit and `git worktree add`.
- **Python.**
  - Use the standard library only, in every Python file this plan touches.
  - Every new or changed file must run on Python 3.9.6 and 3.13. So use none of: the `match` statement, `X | Y` type expressions, the walrus operator, `str.removeprefix`, `zip(strict=)` and parenthesised context managers.
- **Editing.**
  - Executors make every file change with the Edit tool (an Edit step) or the Write tool (a Create step).
  - Never use `rm`, `sed -i`, a redirect or a script to change a tracked file. Task 7's fixture regeneration is the one exception: it runs exactly the command that the Task 7 re-baseline spec gives.
- **Git.**
  - Stage only the paths a task names, and check `git diff --cached --name-only` before every commit.
  - Every commit command passes the trailer as a second `-m`, or as the last line of a `-F` message file.
  - Push is a separate step that needs the user's approval. No task pushes.
- **Paths.**
  - `S` = `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`.
  - `WS` = `$S/sf-wt/qwen-agent-workspace`, and `D` = `$S/sf-baseline`.
  - The git root is `$S/sf-wt`, so `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix.
  - Run every command from `WS`. Shell variables do not persist between commands, so every block defines the variables it uses.
- **Code blocks** are copied byte for byte.
  - An Edit step's old text must occur exactly once in the file at that moment. If it does not, stop and report; do not adapt it.
  - Every Edit and Create below was replayed in order on a scratch export of `6f16063`. Each old text occurred exactly once at its turn (see "Execution handoff").
- **The compile check** (Step 4 of each code task) is this command, with the task's files as `FILES`. Expected: two lines, `compiled N` for 3.9 and then for 3.13.

```bash
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' FILES; done
```

## Review Focus

The spec implies these five inputs, and no SFT row exercises them. They are the ones most likely to reach a real run first. Each is pinned by a test in its owning task.

1. **A writer camera sentence that begins with the planned sentence's words.** This is exactly the form the writer is told to use ("The camera pushes in — as the move completes, ..."), on the critic's patch path.
   - Expected: the patch is applied word for word, and the field holds that one camera sentence and no fallback.
   - At the spec's code, `clean_writer` blanked "The camera pushes in" out of it; see Plan ruling PR1.
   - Test: `test_review_focus_1_a_critic_patch_keeps_an_end_framed_camera_sentence_whole` (Task 4). The parse path is SFT6 (Task 2).
2. **The round-0 re-ask comes back unparseable.** Local models do this.
   - Expected: the first reply is kept, then trimmed. The run exits 0 with exactly 4 calls, and the exit is removed with a "the pipeline removed" advisory.
   - Test: `test_review_focus_2_an_unparseable_re_ask_keeps_the_first_reply_and_trims` (Task 4).
3. **The writer's end frame reuses the reference's own words** ("her face fills the frame from chin to brow"). This is the likeliest N22 in practice, since the reference shows that very shot.
   - Expected: a hard N22 on that sentence. The trim drops the camera sentence, so the planned fallback "The camera pushes in." closes the field.
   - Test: `test_review_focus_3_an_end_frame_in_the_references_words_falls_back` (Task 4).
4. **A reaction that names the speaker by library name, or names a crowd or co-star as an object** ("Kyra nods.", "... waves to the crowd.", "She glances at the ronin.").
   - Expected: no N21. Only another character as a clause subject counts.
   - Test: `test_review_focus_4_the_speakers_own_name_and_an_object_are_not_other_actors` (Task 3).
5. **An adverb on the planned move** ("The camera slowly pushes in on her.", "The camera gently pans left toward the harbour.").
   - Expected: one valid camera direction. There is no N20 and no repair.
   - Test: `test_review_focus_5_an_adverb_on_the_planned_move_is_one_valid_direction` (Task 3).

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `story_engine.py` | Modify (Tasks 1-5) | Planner camera contract and P18 (T1); writer camera contract, word ranges, the format reference and `cleanup_pieces` (T2); the N7/N20/N21/N22 checks and parse-time repairs, the S4/S5 generation parameters (T3); the round-0 re-ask, trim, critic and patch paths (T4); P19 (T5). |
| `character_lib.py` | Modify (Tasks 3, 6) | `motion_problems`/`shots_violations`/`motion_length_advisory`/`shots_advisories` parameters (T3); `ACOUSTIC_SENTENCE`, `AMBIENCE_SENTENCE`, `framing_sentence`, `compose_motion`, `panel_prompt` (T6). |
| `bin/ltx-story-manifest` | Modify (Task 6) | Speech movies in `--chain`/`--shots` compose with `panel_prompt`; the `--speech-delivery` help. |
| `tests/test_shot_format.py` | Create (Task 1), append (Tasks 2-6) | SFT1-SFT25 and Review Focus 1-5: 37 test functions. |
| Existing tests and fixtures of spec 4.2 | Modify (Task 7 only) | The G5 re-baseline, one test-only commit. |
| `tests/test_movie_ui_builder.py` | Modify (Task 8 only) | `test_mut26` `BASELINE` and comment (G6). |

**Task split.** Tasks 1-6 each add one layer that a reviewer can accept or reject on its own diff:
- Task 1 is what the planner reads and the cap after it.
- Task 2 is what the writer reads and what is pasted.
- Task 3 is how a writer reply is judged and repaired at parse time.
- Task 4 is what happens when it is still wrong.
- Task 5 is P19.
- Task 6 is the final prompt composition.

Task 7 is the test-only re-baseline, and Task 8 is the whole-branch review, `test_mut26` and the gates.

## Between tasks: the existing suite (approach B, and why)

**The choice.** Feature tasks do **not** edit existing tests. Instead this plan states which existing tests are expected to fail after each task, and they are all fixed in Task 7, one test-only commit.

**Why not approach A** (each feature task updates the tests it breaks):
- The spec mandates the opposite. 0.4 G5, 4.2 and 6 call for one separate test-only commit whose body explains every changed file.
- One golden is broken by several tasks. For example, the shots goldens change through R5 (T1), R7/R8 (T2), R12/R15 (T3) and R13 (T6). Approach A would rewrite the same literal up to four times and scatter its explanation across four commits.
- A single re-baseline after all behaviour lands gives one diff per golden, explained once.

**The cost** is that the existing suite is knowingly red in the listed places between Task 1 and Task 7. The gate below keeps that from hiding a real regression.

**Precision.** The list below is the spec's 4.2 inventory, mapped to the task whose R code first breaks each test, plus the tests this plan's own reading added (marked +).
- It was derived by reading and grep at `6f16063`, not by running the suite, which this plan's author was not permitted to do.
- After each task, the gate compares a full run with the `3970e96` baseline.
- **Every test that passed at the baseline and does not pass now must be on the list for this task or an earlier one.** Otherwise the executor stops; see the gate rule.
- A listed test that still passes is fine; it may break in a later task.

**Gate rule** (Step 4 of every code task):
1. Every `tests/test_shot_format.py` test passes.
2. The two baseline failures fail with the same messages.
3. Every lost baseline pass is listed for a task at or before this one in `$D/expected-failures.txt`.
4. `tests/test_ltx_movie_offline.py` prints `OK 347/347`.

**When the gate prints `GATE STOP`:**
- The executor stops and reports the UNEXPECTED ids together with `python3 -B -m pytest -q -p no:cacheprovider --tb=short <ids>` output.
- The controller has an Opus reviewer rule on each id.
  - If an R code of this or an earlier task explains its diff, the controller appends a line `T<N> <id> <codes> +gate` to `$D/expected-failures.txt`. That is the only way the list grows.
  - Otherwise it is a defect, and the controller writes the exact fix for the executor.
- The gate then reruns.

**The R codes** are spec 4.2's R1-R17, plus R18:

| Code | Cause | First task |
|---|---|---|
| R1-R5 | camera order/handheld, plan camera rule, speaker rules, speaking push-in, P18 cap | 1 |
| R6, R7, R8, R9, R10 | CM4 fix, chained k>=2 fallback, word ranges, key lines, format reference | 2 |
| R18 (+) | Plan ruling PR1: a writer action field keeps a CAMERA_SENTENCES sentence it wrote verbatim (no longer blanked by the cleanup), so CM4 drops the pasted copy and the sentence stays where the writer put it | 2 |
| R12, R15, R16 (detection and parse repairs); R8 (shots S4 in generation, SF14) | N7 hard and the cuts; S5 speaking allowance; N20/N21/N22 | 3 |
| R11, R14, R16 (re-ask and trim) | REPAIR_IDS; critic lines; round-0 re-ask | 4 |
| R17 | P19 | 5 |
| R13 | manifest composition and audio sentences | 6 |
| G6 | `test_mut26` (any edit to a `PIPELINE_FILES` entry) | 1 (fixed in Task 8) |

The expected-failure list, written to `$D/expected-failures.txt` in "Before Task 1" Step 4. A line is `T<first task> <node id> <codes>`. A parametrised test matches by its id prefix.

```text
# shot prompt format plan: existing tests expected to fail from the given task until Task 7 (Task 8 for mut26)
T1 tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged G6
T1 tests/test_story_engine.py::test_rs4_constants R1,R8
T1 tests/test_story_engine.py::test_rst8_plan_prompt_matrix R2,R3
T1 tests/test_story_engine.py::test_rst9_narrative_is_inserted_verbatim R2,R3
T1 tests/test_story_engine.py::test_rst57_reserved_sentence_in_the_plan_prompt R2,R3
T1 tests/test_story_engine.py::test_rst20e_speech_only_framing R2,R3
T1 tests/test_story_engine.py::test_rst14_plan_checks R1
T1 tests/test_story_engine.py::test_rst39_outputs_and_layout R5,R7,R8,R12
T1 tests/test_story_engine.py::test_rst48_judge_story_patches R5,R7,R8,R12
T1 tests/test_story_engine.py::test_pacing_camera_sentences_classify_as_before R1
T1 tests/test_dialogue.py::test_dlg5_camera_sentence_classifier R1
T1 tests/test_dialogue.py::test_dlg12_plan_prompt_speaker_rule R2,R3
T1 tests/test_narrative_fidelity.py::test_nf16_the_speaking_coercion_table R4
T1 tests/test_narrative_fidelity.py::test_nf17_pasted_pieces_of_a_speaking_panel R4,R6
T1 tests/test_narrative_fidelity.py::test_nf12_the_plan_prompt R2,R3
T1 tests/test_pinned_cast.py::test_pt1_plan_constants R3
T1 tests/test_pinned_cast.py::test_pt2_fixed_cast_block_and_uncast_byte_identity R1,R2,R3
T1 tests/test_pinned_cast.py::test_pt4_speaker_rule_variants R3
T1 tests/test_pinned_cast.py::test_pt5_lines_sentence_variants R2
T1 tests/test_pinned_cast.py::test_pt18_seed_and_two_pinned_retried R2
T1 tests/test_speaker_attribution.py::test_sat9_plan_prompt R2,R3
T1 tests/test_speaker_attribution.py::test_sat6_e2e_retry R2,R3
T1 tests/test_speaker_attribution.py::test_review_focus_3_a_quote_that_is_not_spoken_keeps_the_line_numbers R2,R3
T1 tests/test_speaker_attribution.py::test_review_focus_4_an_invented_speaker_in_a_pinned_run R2,R3
T2 tests/test_story_engine.py::test_rst16_panel_prompt R8,R9,R10
T2 tests/test_story_engine.py::test_rst20c_narration_modes R8,R9,R10
T2 tests/test_story_engine.py::test_rst18_assembly_goldens R7
T2 tests/test_story_engine.py::test_rst17_cleanup_and_title_fallback R7,R18
T2 tests/test_story_engine.py::test_rst20_panel_checks R8
T2 tests/test_story_engine.py::test_pacing_panel1_prompt_and_no_slowly R8
T2 tests/test_story_engine.py::test_rst44_recheck_with_plan R8 +
T2 tests/test_dialogue.py::test_dlg13_writer_keys_and_speaking_key_lines R9
T2 tests/test_dialogue.py::test_n16_n17_n18_dialogue_messages R6,R7
T2 tests/test_dialogue.py::test_dlg15_assembly_goldens_and_dedupe R6,R7,R18 +
T2 tests/test_narrative_fidelity.py::test_nf19_n17_accepts_a_moving_speaking_camera R6
T2 tests/test_narrative_fidelity.py::test_nf20_the_panel_prompt_constants R9
T2 tests/test_narrative_fidelity.py::test_nf28_engine_the_2x145_failure R6,R7,R16
T2 tests/test_writer_pacing.py::test_wt1_the_constants R9,R14
T2 tests/test_writer_pacing.py::test_wt3_the_hockey_speaking_prompts R8,R9
T2 tests/test_writer_pacing.py::test_wt4_shots_and_no_stills_speaking_prompts_are_unchanged R9
T2 tests/test_writer_pacing.py::test_review_focus_1_a_writer_re_ask_keeps_one_contract R9
T2 tests/test_writer_pacing.py::test_wt9_old_stories_check_unchanged R8 +
T2 tests/test_pinned_cast.py::test_pt11_writer_prompt R8,R9,R10
T3 tests/test_dialogue.py::test_dlg21_an_advisory_only_round_0_passes_untouched R12
T3 tests/test_writer_pacing.py::test_wt6_the_contract_motion_passes_the_checks R12,R16
T4 tests/test_dialogue.py::test_dlg19_critic_prompt R14
T4 tests/test_writer_pacing.py::test_wt7_the_critic_clause R14 +
T4 tests/test_speaker_attribution.py::test_q1_a2_constants R11
T6 tests/test_dialogue.py::test_dlg3_speech_text R13
T6 tests/test_dialogue.py::test_dlg7_manifest_goldens R13
T6 tests/test_dialogue.py::test_dlg8_narration_alias R13
T6 tests/test_dialogue.py::test_dlg10_dialogue_wins_over_a_prefixed_narration R13
T6 tests/test_dialogue.py::test_review_focus_2_a_spoken_line_that_names_another_cast_member R13
T6 tests/test_dialogue.py::test_review_focus_3_dialogue_with_equal_pace_and_no_narration R13
T6 tests/test_dialogue.py::test_dlg29_judge_clips_panel_text R13
T6 tests/test_narrative_fidelity.py::test_nf35_manifest_places_the_line_after_the_first_action R13
T6 tests/test_writer_pacing.py::test_wt5_the_contract_matches_the_placement R13
T6 tests/test_writer_pacing.py::test_wt8_old_stories_compose_unchanged R13
T6 tests/test_pinned_cast.py::test_pt13_speech_stays_with_the_speaker R13
```

Spec 4.2 also names failures that depend on how a test is written. The gate rule decides them, and the rule above handles each:
- the `tests/test_shots_mode.py` robust-engine goldens (R5-R8, R15);
- `tests/test_casting_pipeline.py` (R13 only if spoken; R6, R7);
- the `test_speaker_attribution.py` prompt tests (whole bytes only).

**Must stay green in every task** (spec 4.3):
- `tests/test_ltx_story_manifest_chain.py`, `tests/test_ltx_mlx_render.py`, `tests/test_ltx_story_video.py`, `tests/test_judge_clips.py`, `tests/test_lora_catalog.py`, `tests/test_character_lib.py`, `tests/test_iterate_story.py`, `tests/test_judge_story.py`, `tests/test_casting_regression.py` and `tests/test_ltx_movie_offline.py`;
- `test_dlg4_insert_speech_placement` and `test_nf34_insert_speech_after_the_first_action`.

None of them is in the list, so a failure there stops the gate.

---

## Before Task 1: the plan commit, the worktree, the snapshot, the baseline (controller; no code)

- [ ] **Step 1: Commit this plan on `qwen-agent-redteam` (after the user approves the plan).**

This follows how `44776c8 docs(plan): speaker attribution implementation plan` was committed. Committing on the branch before the worktree is cut keeps the main checkout's copy of this file from blocking the later fast-forward.

```bash
cd /Users/reubenpatterson/local_agent_harness
git branch --show-current          # expected: qwen-agent-redteam
git log -1 --format=%h             # expected: 6f16063
git add qwen-agent-workspace/docs/superpowers/plans/2026-10-28-shot-prompt-format.md
git diff --cached --name-only      # expected: only qwen-agent-workspace/docs/superpowers/plans/2026-10-28-shot-prompt-format.md
git commit -m "docs(plan): shot prompt format implementation plan" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 2: Create the worktree and confirm the tree.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
git -C /Users/reubenpatterson/local_agent_harness worktree add -b sf-impl $S/sf-wt qwen-agent-redteam
WS=$S/sf-wt/qwen-agent-workspace
cd $WS
git branch --show-current                                   # expected: sf-impl
git log -1 --format=%s                                      # expected: docs(plan): shot prompt format implementation plan
git rev-parse HEAD~1                                        # expected: 6f16063... (the spec commit)
git diff --stat 3970e96 HEAD -- . ':(exclude)docs' | tail -1   # expected: no output
git status --short                                          # expected: no output
ls tests/test_shot_format.py 2>&1 | grep -c "No such file"  # expected: 1
wc -l < story_engine.py                                     # expected: 4058
grep -c "P18\|N20\|FORMAT_REFERENCE" story_engine.py        # expected: 0
grep -c "f7a38afc6d6ae9622b63dbf4ce939e362a05a7ad" tests/test_movie_ui_builder.py   # expected: 2
```

If any value differs, stop and report: every Edit below was written against this tree.

- [ ] **Step 3: Take the compressed snapshot (house rule; spec 6 step 1).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
tar czf $S/snapshot-pre-shot-format-3970e96.tgz --exclude qwen-agent-workspace/generated -C $S/sf-wt qwen-agent-workspace
tar tzf $S/snapshot-pre-shot-format-3970e96.tgz | grep -c '^qwen-agent-workspace/story_engine.py$'   # expected: 1
```

- [ ] **Step 4: Record the baseline and write the gate files (about 1 minute).**

The full-suite baseline at `3970e96`'s code tree is `$S/sa-baseline/final-pytest.txt`, which is the final run of the speaker-attribution work. Copy it; do not re-run the 15-minute suite.

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/sf-baseline
mkdir -p $D
cp $S/sa-baseline/final-pytest.txt $D/baseline-pytest.txt
tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
grep -c '^PASSED ' $D/baseline-pytest.txt
cd $S/sf-wt/qwen-agent-workspace && python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1 | tee $D/baseline-offline.txt
```

Expected:
- `2 failed, 1890 passed, 2 skipped, 3757 warnings in 885.36s (0:14:45)`;
- exactly two `FAILED` lines: `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets - AssertionError: b...`;
- `1890`;
- `OK 347/347`.

If the copied file's last line differs, record the baseline in the worktree instead, with `python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1` (about 15 minutes).

Then write two scratch files with the Write tool. They are outside the repository and never staged.

1. `$D/expected-failures.txt`: exactly the `text` block of "Between tasks" above.
2. `$D/gate.py`:

```python
"""The task gate of the shot prompt format plan: a full pytest -rA run against the baseline."""
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
mine = sorted(t for t in now if t.startswith("tests/test_shot_format.py::"))
broken = [t for t in mine if now[t] != "PASSED"]
old_failures = sorted(t for t, s in base.items() if s != "PASSED")
still = [t for t in old_failures if now.get(t) != "PASSED"]
print("lost %d (listed %d, unexpected %d); test_shot_format %d, not passing %d; baseline "
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

---

### Task 1: The planner camera contract and the P18 static cap (SF1-SF5)

This task implements:
- SF1, the camera keys and `max_static`;
- SF2, `CAMERA_RULE` and `CAMERA_SPEAKING_SENTENCE` in the plan prompt;
- SF3, `SPEAKING_BEAT_SENTENCE` and the two speaker rules;
- SF4, `SPEAKING_CAMERAS`, `speaking_camera`, the P14 coercion to `slow push-in`, and `handheld` in `STILL_CAMERA_MOVES`;
- SF5, `P18_NOTE` and `cap_static_cameras` with its `_Run.go` call.

Tests: SFT1 (planner part: `test_sft1a_planner_constants`, and the two-interpreter compile check), SFT2, SFT3 (coercion part), SFT4 and SFT22. The task creates `tests/test_shot_format.py` with the whole spec 4.1 header and helpers, and later tasks append to it. This is the first pipeline commit, so `test_mut26` fails from here until Task 8.

**Files:**
- Create: `tests/test_shot_format.py`
- Modify: `story_engine.py`. The edits go to `CAMERA_SENTENCES` (`:44-55`), the template camera clause (`:313`), the speaker rules (`:352-369`), the `build_plan_prompt` fragments and scalars (`:961`, `:978`), `SPEAKING_CAMERAS`/`speaking_camera` (`:1152-1160`), `speaking_coercion` (`:1320-1357`), `STILL_CAMERA_MOVES` (`:2238`) and `_Run.go` (`:3772`).

**Interfaces:**
- Consumes (existing):
  - from `story_engine`: `normalize_plan(ctx, raw) -> (plan, shape)`, `build_plan_prompt(ctx, compatible, pins) -> str`, `parse_violation(text) -> dict`, `_q`, `run(ctx) -> (rc, advisories)`;
  - from `story_engine_testutil`: `set_story_env`, `make_ws`, `make_ctx(se, ws, **overrides)`, `plan_json`, `panel_json`, `answer`, `script_agent`, `agent_log`, `kyra`, `ronin`.
- Produces:
  - In `story_engine`:
    - the constants `CAMERA_SENTENCES` (9 pairs, moves first, `handheld` added, `static` last), `CAMERA_RULE` (holds `@@MAX_STATIC@@`), `CAMERA_SPEAKING_SENTENCE`, `SPEAKING_BEAT_SENTENCE`, `SPEAKING_CAMERAS` and `P18_NOTE` (a `%` format of `(int k, int cap, int panels)`);
    - `max_static(panels: int) -> int`;
    - `cap_static_cameras(ctx, plan) -> [str]`, which changes `plan["beats"]` in place;
    - `speaking_camera(beat) -> str`, now giving `"slow push-in"` for a camera outside `SPEAKING_CAMERAS`.
  - In `tests/test_shot_format.py`:
    - the module header (`WS`, `seu`, `lib`, `se`, `story_manifest`, `ltx_movie`; imports `base64`, `copy`, `hashlib`, `json`, `os`, `re`, `subprocess`, `sys`, `pytest`) and the fixtures `story_env` (autouse) and `ws`;
    - copied verbatim from `tests/test_speaker_attribution.py`: `KYRA`, `RONIN`, `CAST2`, `LINES_NARRATIVE`, `_members`, `_raw` and `_read_json(story_dir, name)`;
    - copied verbatim from `tests/test_dialogue.py`: `PNG_1X1`, `CAST_PLAN`, `_manifest_ws`, `_manifest_argv` and `_read_manifest`;
    - the spec 4.1 extras `REF_PHRASE`, `REF_PARTS` and `ref_shots()`;
    - this plan's `HOCKEY_NARRATIVE`, `HOCKEY_FIX`, `_hockey(ws, **kw) -> (ctx, plan, parts)` and `_plan_prompt(ws, **kw) -> str`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_sft1a_planner_constants`, `test_sft1_the_pipeline_files_compile_under_both_pythons`, `test_sft2_the_plan_prompt`, `test_sft3a_a_speaking_pan_or_tilt_becomes_a_slow_push_in`, `test_sft4_the_static_cap`, `test_sft4_e2e_the_cap_runs_once_after_the_plan` and `test_sft22_no_server_and_no_real_home`.

Create `tests/test_shot_format.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""Tests for the shot prompt format (docs/superpowers/specs/2026-10-28-shot-prompt-format-
design.md, Section 4.1: SFT1-SFT25, and the plan's Review Focus 1-5): the planner gets one camera
move per beat with static capped at one beat in three (P18), the writer writes the panel's one
camera sentence (N20), a speaking panel ends with the speaker in frame and nobody else acting
(N21), speaking verbs are cut (N7), writers see a format reference they must not copy (N22), the
manifest composes a speech movie's prompts in a fixed order with the audio sentence last, and the
user is told when the narrative's exit after its last line is left out (P19).

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_shot_format.py
Stdlib plus pytest. No test renders, reads the real HOME, or contacts a model server, a daemon or
the Anthropic API: every model call goes to the fake bin/qwen-agent of a temp workspace
(story_engine_testutil.make_ws), every ctx lives under tmp_path, and every test runs under the
autouse story_env fixture (a temporary HOME, character library and LoRA catalog).
"""

import base64
import copy
import hashlib
import importlib.machinery
import json
import os
import re
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


lib = _load("character_lib_for_shot_format", "character_lib.py")
se = _load("story_engine_for_shot_format", "story_engine.py")
story_manifest = _load("ltx_story_manifest_for_shot_format",
                       os.path.join("bin", "ltx-story-manifest"))
ltx_movie = _load("ltx_movie_for_shot_format", os.path.join("bin", "ltx-movie"))


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


# --- Copied verbatim from tests/test_speaker_attribution.py (spec 4.1) -------------------------

KYRA = "the woman in grey"
RONIN = "the ronin"
CAST2 = [{"id": "c1", "phrase": "x", "descriptor": "a woman"},
         {"id": "c2", "phrase": "y", "descriptor": "a man"}]
LINES_NARRATIVE = ('At dusk Kyra climbs the stone steps of a mountain temple, and the ronin walks '
                   'one step behind her. Near the top Kyra turns and says, "We reach the gate '
                   'before dark." They pass under the gate together, and Kyra says, "Stay close '
                   'to me."')


def _members(story_env):
    """kyra (c1, "the woman in grey") and ronin (c2, "the ronin") from the test library."""
    seu.kyra(story_env["lib"])
    seu.ronin(story_env["lib"])
    return lib.resolve_cast([(None, "kyra"), (None, "ronin")])


def _raw(mode, n, casts, speakers=None):
    """A plan reply for n beats with CAST2 (normalisation replaces both entries with the
    members): beat k gets cast casts[k - 1] and, when speakers is given, speaker
    speakers[k - 1]."""
    raw = seu.plan_json(mode, n, cast=copy.deepcopy(CAST2))
    for k, beat in enumerate(raw["beats"], start=1):
        beat["cast"] = list(casts[k - 1])
        if speakers is not None:
            beat["speaker"] = speakers[k - 1]
    return raw


def _read_json(story_dir, name):
    with open(os.path.join(story_dir, name), encoding="utf-8") as f:
        return json.load(f)


# --- Copied verbatim from tests/test_dialogue.py (spec 4.1: the manifest tests) ----------------

# A valid 1x1 PNG: bin/ltx-story-manifest only checks that each panel still opens.
PNG_1X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
                           "60e6kgAAAABJRU5ErkJggg==")
CAST_PLAN = {"schema": "ltx-movie.plan.v1", "cast": [
    {"id": "c1", "phrase": "the courier", "descriptor": seu.COURIER, "cast_name": None},
    {"id": "c2", "phrase": "the old monk", "descriptor": seu.MONK, "cast_name": None}],
    "beats": [{"cast": ["c1"]}, {"cast": ["c2"]}]}


def _manifest_ws(tmp_path, monkeypatch, story_id, text, plan=None, images=1):
    """A workspace for bin/ltx-story-manifest (its module WS patched), with character_lib.py and
    lora_catalog.py symlinked in, the story.md, `images` panel stills, and plan (a dict, or the
    raw file text) as generated/stories/<story_id>/plan.json when given."""
    ws = tmp_path / "mws"
    if not ws.exists():
        ws.mkdir()
        for name in ("character_lib.py", "lora_catalog.py"):
            os.symlink(os.path.join(WS, name), str(ws / name))
    monkeypatch.setattr(story_manifest, "WS", str(ws))
    story_md = tmp_path / ("%s.md" % story_id)
    story_md.write_text(text, encoding="utf-8")
    paths = []
    for k in range(1, images + 1):
        path = tmp_path / ("%s_%02d.png" % (story_id, k))
        path.write_bytes(PNG_1X1)
        paths.append(str(path))
    if plan is not None:
        story_dir = ws / "generated" / "stories" / story_id
        story_dir.mkdir(parents=True, exist_ok=True)
        (story_dir / "plan.json").write_text(plan if isinstance(plan, str) else json.dumps(plan),
                                             encoding="utf-8")
    return str(story_md), paths, str(ws)


def _manifest_argv(story_id, story_md, images, mode="chain", panels=2, frames=145, extra=()):
    argv = ["--story-id", story_id, "--prompts-md", story_md]
    if mode == "chain":
        argv += ["--chain", "--image", images[0]]
    elif mode == "shots":
        argv += ["--shots"]
        for image in images:
            argv += ["--image", image]
    else:
        argv += ["--no-images"]
    return argv + ["--fps", "24", "--target-seconds", repr(frames * panels / 24.0),
                   "--min-frames", str(frames), "--max-frames", str(frames), "--force"] + list(extra)


def _read_manifest(ws, story_id):
    with open(os.path.join(ws, "generated", "stories", story_id, "manifest.json"),
              encoding="utf-8") as f:
        return json.load(f)


# --- Extra helpers (spec 4.1) ----------------------------------------------------------------

REF_PHRASE = "the old fishmonger"
REF_PARTS = (
    {"shot": "The shot is a wide shot.",
     "motion": ("The old fishmonger drags a tall stack of empty herring crates across the wet "
                "concrete of the market hall toward the half-open shutter at real-time speed, her "
                "heavy steps splashing through shallow puddles that hold the first glow from the "
                "harbour doors. The camera tracks alongside her from the left — as the move "
                "completes, she reaches the shutter at frame centre, the long rows of bare zinc "
                "counters stretching away behind her."),
     "speaker": None, "line": ""},
    {"shot": "The shot is a medium shot.",
     "motion": ("The old fishmonger looks up from the empty ice trays to the camera, drying her "
                "knuckles on a folded cloth at the zinc counter at real-time speed. The old "
                "fishmonger lets the folded cloth drop onto the counter, her shoulders sinking. "
                "The camera pushes in — as the move completes, her face fills the frame from "
                "chin to brow, the bare counters soft behind her. The old fishmonger faces the "
                "camera."),
     "speaker": "the old fishmonger", "line": "Forty years of mornings. Not one more."},
    {"shot": "The shot is a close-up.",
     "motion": ("The old fishmonger presses her forehead against the cold ribs of the half-closed "
                "steel shutter at real-time speed, both palms flat on the metal, her breath "
                "fogging the ribbed steel as a thin trickle of meltwater runs past her knuckles "
                "and drips onto the wet concrete at her feet. The camera stays static, holding her "
                "face, her knuckles and the ribbed steel tight in the frame as her eyelids drop "
                "shut and the shutter stops trembling."),
     "speaker": None, "line": ""},
)
# The narrative of the recorded hockey runs ($S/hockey/narrative.txt, written out; it equals the
# narrative of tests/fixtures/writer_pacing/hockey-2x145-f/plan.json).
HOCKEY_NARRATIVE = (
    'A hockey player in a reddish-orange and white uniform with "FuboTV" in a big logo on the '
    'front stands in a hockey rink with "FuboTV" on the sides of the rink and on digital banners '
    'on the bleachers, with cheering crowds in the stands. He skates forward towards the camera '
    'and says "Getting the best deal on hockey isn\'t a hat trick..." then stops short, kicking '
    'up ice mist into the air, then says "It\'s just FuboTV." then skates away.')
HOCKEY_FIX = os.path.join(WS, "tests", "fixtures", "writer_pacing", "hockey-2x145-f")


def ref_shots():
    """The three "Shot N" texts of se.FORMAT_REFERENCE: each line's text after its "): "."""
    return [line.split("): ", 1)[1] for line in se.FORMAT_REFERENCE.split("\n")
            if line.startswith("Shot ")]


def _hockey(ws, **kw):
    """(ctx, plan, parts) of the recorded hockey-2x145-f run: chained, 2 panels of 145 frames,
    --speech-only, its plan.json and its parts.json panels without their "index" key."""
    plan = _read_json(HOCKEY_FIX, "plan.json")
    parts = [dict((key, value) for key, value in p.items() if key != "index")
             for p in _read_json(HOCKEY_FIX, "parts.json")["panels"]]
    fields = dict(mode="chained", panels=2, narration="speech", clip_seconds=145 / 24.0,
                  narrative=plan["narrative"], goal=plan["goal"])
    fields.update(kw)
    return seu.make_ctx(se, ws, **fields), plan, parts


def _plan_prompt(ws, **kw):
    """The plan prompt of make_ctx(**kw), with no catalog and no pins."""
    return se.build_plan_prompt(seu.make_ctx(se, ws, **kw), [], [])


# --- SFT1 (Task 1 part): the planner constants (SF1-SF5) --------------------------------------

CAMERA_SENTENCES = (
    ("slow push-in", "The camera pushes in."),
    ("slow pull-back", "The camera pulls back."),
    ("tracking", "The camera tracks alongside the movement."),
    ("handheld", "The camera is handheld, with slight natural movement."),
    ("slow pan left", "The camera pans left."),
    ("slow pan right", "The camera pans right."),
    ("slow tilt up", "The camera tilts up."),
    ("slow tilt down", "The camera tilts down."),
    ("static", "The camera stays static."),
)
CAMERA_RULE = (" Give every beat one camera move from this list, and use static only for a "
               "deliberate hold: at most one beat in three may be static, so at most "
               "@@MAX_STATIC@@ in this movie.")
CAMERA_SPEAKING_SENTENCE = (" On a beat with a speaker, prefer slow push-in, slow pull-back, "
                            "tracking or handheld, and never use a pan or a tilt, which sweeps "
                            "the speaker's face out of the frame.")
SPEAKING_BEAT_SENTENCE = (" Write a speaking beat's action as what the speaker physically does, "
                          "never as speaking, and end it with the speaker still in frame: nobody "
                          "else acts after the line, and when the narrative has the speaker "
                          "leave, or another character act, after a line, give that a later beat "
                          "with no speaker, or leave it out when no later beat is left.")
SPEAKER_RULE = (" speaker is the id of the one character who says something aloud on screen "
                "during the beat, or an empty string when nobody speaks; give a speaker only where "
                "a spoken line moves the story. A beat with a speaker shows only that character "
                "(its cast is just their id), facing the camera, in a medium shot, medium close-up "
                "or close-up; the speaker may move during the beat, as long as their face stays in "
                "frame and lit while they speak." + SPEAKING_BEAT_SENTENCE)
SPEAKER_RULE_KEEP_CAST = (
    " speaker is the id of the one character who says something aloud on screen during the "
    "beat, or an empty string when nobody speaks; give a speaker only where a spoken line moves "
    "the story. A beat with a speaker shows that character facing the camera, in a medium shot, "
    "medium close-up or close-up; its cast is the speaker's id plus the id of every already-cast "
    "character who is still in frame and stays silent, and no character of your own. The speaker "
    "may move during the beat, as long as their face stays in frame and lit while they speak."
    + SPEAKING_BEAT_SENTENCE)
P18_NOTE = ("beat %d: P18 static camera: camera 'static' changed to 'slow push-in': at most %d "
            "of the %d beats may be static, and the latest static beats are kept as the "
            "deliberate holds")
SPEAKING_CAMERAS = ("slow push-in", "slow pull-back", "tracking", "handheld", "static")
STILL_CAMERA_MOVES = ("static", "still", "hold", "holds", "locked-off", "push in", "pushes in",
                      "push-in", "pull back", "pulls back", "pull-back", "track", "tracks",
                      "tracking", "follow", "follows", "handheld")
RECHECK_IDS_3970E96 = ("N1", "N2", "N3", "N4", "N7", "N8", "N9", "N10", "N11", "N12", "N14", "N15",
                       "N16", "N17", "N18", "T1", "T2", "T3", "Q1", "N19")
PLAN_FREE_IDS_3970E96 = ("N1", "N7", "N8", "N9", "N10", "N11", "N15")


def test_sft1a_planner_constants():
    assert se.CAMERA_SENTENCES == CAMERA_SENTENCES
    assert se.CAMERA_KEYS == tuple(key for key, _sentence in CAMERA_SENTENCES)
    assert [se.max_static(n) for n in range(1, 8)] == [1, 1, 1, 2, 2, 2, 3]
    assert se.CAMERA_RULE == CAMERA_RULE
    assert se.CAMERA_SPEAKING_SENTENCE == CAMERA_SPEAKING_SENTENCE
    assert se.SPEAKING_BEAT_SENTENCE == SPEAKING_BEAT_SENTENCE
    assert se.SPEAKER_RULE == SPEAKER_RULE
    assert se.SPEAKER_RULE_KEEP_CAST == SPEAKER_RULE_KEEP_CAST
    assert se.SPEAKING_CAMERAS == SPEAKING_CAMERAS
    assert se.STILL_CAMERA_MOVES == STILL_CAMERA_MOVES
    assert se.STILL_CAMERA_MOVES[-1] == "handheld"
    assert se.P18_NOTE == P18_NOTE
    assert se.RECHECK_IDS == RECHECK_IDS_3970E96
    assert se.PLAN_FREE_IDS == PLAN_FREE_IDS_3970E96
    for text in ([sentence for _key, sentence in se.CAMERA_SENTENCES]
                 + [se.CAMERA_RULE, se.CAMERA_SPEAKING_SENTENCE, se.SPEAKING_BEAT_SENTENCE,
                    se.SPEAKER_RULE, se.SPEAKER_RULE_KEEP_CAST, se.P18_NOTE]):
        assert "slowly" not in text.lower(), text


def test_sft1_the_pipeline_files_compile_under_both_pythons():
    script = ("import sys\n"
              "for path in sys.argv[1:]:\n"
              "    with open(path, encoding='utf-8') as f:\n"
              "        compile(f.read(), path, 'exec')\n"
              "print('compiled %d' % (len(sys.argv) - 1))\n")
    files = [os.path.join(WS, name) for name in
             ("story_engine.py", "character_lib.py", os.path.join("bin", "ltx-story-manifest"))]
    pythons = [sys.executable] + (["/usr/bin/python3"] if os.path.exists("/usr/bin/python3")
                                  else [])
    for python in pythons:
        proc = subprocess.run([python, "-c", script] + files, capture_output=True, text=True)
        assert (proc.returncode, proc.stdout) == (0, "compiled 3\n"), (python, proc.stderr)


# --- SFT2: the plan prompt camera rule (SF2, SK4) ------------------------------------------------

CAMERA_LIST = ("camera is exactly one of: slow push-in, slow pull-back, tracking, handheld, slow "
               "pan left, slow pan right, slow tilt up, slow tilt down, static.")


def test_sft2_the_plan_prompt(ws, story_env):
    for panels, most in zip(range(1, 8), (1, 1, 1, 2, 2, 2, 3)):
        rule = se.CAMERA_RULE.replace("@@MAX_STATIC@@", str(most))
        prompt = _plan_prompt(ws, mode="shots", panels=panels, narration="speech")
        assert (CAMERA_LIST + rule + se.CAMERA_SPEAKING_SENTENCE + " location is") in prompt, panels
        silent = _plan_prompt(ws, mode="shots", panels=panels, narration=False)
        assert (CAMERA_LIST + rule + " location is") in silent, panels
        assert se.CAMERA_SPEAKING_SENTENCE not in silent, panels
    members = _members(story_env)
    for mode in ("chained", "shots", "no_stills"):
        for narration in (True, "speech", False):
            for cast in ([], members):
                where = (mode, narration, bool(cast))
                prompt = _plan_prompt(ws, mode=mode, narration=narration, members=cast)
                assert "the camera may stay static" not in prompt, where
                assert "@@" not in prompt, where
    assert se.SPEAKER_RULE_KEEP_CAST in _plan_prompt(ws, mode="chained", members=members)
    assert se.SPEAKER_RULE in _plan_prompt(ws, mode="shots", members=members)


# --- SFT3 (Task 1 part): the P14 speaking coercion (SF4, SK4) -----------------------------------

def test_sft3a_a_speaking_pan_or_tilt_becomes_a_slow_push_in(ws, story_env):
    ctx = seu.make_ctx(se, ws, mode="shots", panels=1, members=_members(story_env),
                       narration="speech")
    for camera in ("slow pan left", "slow pan right", "slow tilt up", "slow tilt down", "",
                   "handheld", "static", "tracking", "slow pull-back", "slow push-in"):
        raw = _raw("shots", 1, [["c1"]], ["c1"])
        raw["beats"][0]["camera"] = camera
        plan, _shape = se.normalize_plan(ctx, raw)
        notes = [n for n in plan["speech_notes"] if " camera " in n]
        if camera in se.SPEAKING_CAMERAS:
            assert (plan["beats"][0]["camera"], notes) == (camera, []), camera
        else:
            assert plan["beats"][0]["camera"] == "slow push-in", camera
            assert notes == ["beat 1: P14 speaking beat: camera %s changed to 'slow push-in' so "
                             "the speaker's face stays readable" % se._q(camera)], camera


# --- SFT4: P18, the static cap (SF5, SK4) ------------------------------------------------------

def test_sft4_the_static_cap(ws):
    names = {"s": "static", "t": "tracking", "p": "slow push-in"}
    for before, after in (("sss", "pps"), ("stss", "ptss"), ("ssssss", "ppppss"),
                          ("sstssss", "pptpsss")):
        n = len(before)
        ctx = seu.make_ctx(se, ws, mode="shots", panels=n)
        plan = {"beats": [{"camera": names[c]} for c in before]}
        notes = se.cap_static_cameras(ctx, plan)
        assert [beat["camera"] for beat in plan["beats"]] == [names[c] for c in after], before
        changed = [k for k, (a, b) in enumerate(zip(before, after), start=1) if a != b]
        assert notes == [se.P18_NOTE % (k, se.max_static(n), n) for k in changed], before
        violation = se.parse_violation(notes[0])
        assert (violation["id"], violation["name"], violation["scope"], violation["index"]) == (
            "P18", "static camera", "beat", changed[0]), before
    ctx = seu.make_ctx(se, ws, mode="shots", panels=2)
    plan = {"beats": [{"camera": "static"}, {"camera": "tracking"}]}
    assert se.cap_static_cameras(ctx, plan) == []
    assert [beat["camera"] for beat in plan["beats"]] == ["static", "tracking"]


def test_sft4_e2e_the_cap_runs_once_after_the_plan(ws, tmp_path, monkeypatch):
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(seu.plan_json("shots", 3))],
                           panel=dict((str(k), [seu.answer(seu.panel_json("shots", k))])
                                      for k in (1, 2, 3)))
    ctx = seu.make_ctx(se, ws, mode="shots", panels=3, story_id="sf4")
    rc, advisories = se.run(ctx)
    note = se.P18_NOTE % (1, 1, 3)
    assert rc == 0
    assert [r["stage"] for r in seu.agent_log(log)] == ["plan", "panel", "panel", "panel"]
    plan = _read_json(ctx.story_dir, "plan.json")
    assert [beat["camera"] for beat in plan["beats"]] == ["slow push-in", "tracking", "static"]
    assert plan["speech_notes"] == [note]
    checks = _read_json(ctx.story_dir, "story_checks.json")
    assert note in [a["message"] for a in checks["advisory"]]
    assert note in advisories
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        motions = [line for line in f.read().splitlines() if line.startswith("Motion: ")]
    assert motions[0].endswith(". The camera pushes in.")


# --- SFT22: no server and no real HOME (spec 4.1 conventions) -----------------------------------

def test_sft22_no_server_and_no_real_home(story_env, tmp_path):
    assert os.path.expanduser("~") == story_env["home"]
    assert story_env["home"].startswith(str(tmp_path))
    assert os.environ["QWEN_AGENT_DAEMON_URL"].startswith("http://127.0.0.1:")
    assert "ANTHROPIC_API_KEY" not in os.environ
```

- [ ] **Step 2: Run the tests to verify that they fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_shot_format.py 2>&1 | tail -1
```

Expected: `5 failed, 2 passed`. The compile check and SFT22 already pass. SFT1a fails on the `CAMERA_SENTENCES` order, SFT2 on the missing `CAMERA_RULE`, SFT3a on the coercion to `static`, and SFT4 on the missing `cap_static_cameras`/`P18_NOTE`.

- [ ] **Step 3: Implement SF1-SF5.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
CAMERA_SENTENCES = (
    ("static", "The camera stays static."),
    ("slow push-in", "The camera pushes in."),
    ("slow pull-back", "The camera pulls back."),
    ("slow pan left", "The camera pans left."),
    ("slow pan right", "The camera pans right."),
    ("slow tilt up", "The camera tilts up."),
    ("slow tilt down", "The camera tilts down."),
    ("tracking", "The camera tracks alongside the movement."),
)
CAMERA_KEYS = tuple(key for key, _ in CAMERA_SENTENCES)
ARC_ROLES = ("introduction", "rising", "climax", "falling", "resolution")
```

with:

```python
# Shot prompt format spec SF1, D1: moves first, static last; the pasted sentence is the fallback
# when the writer writes no camera sentence (SF6).
CAMERA_SENTENCES = (
    ("slow push-in", "The camera pushes in."),
    ("slow pull-back", "The camera pulls back."),
    ("tracking", "The camera tracks alongside the movement."),
    ("handheld", "The camera is handheld, with slight natural movement."),
    ("slow pan left", "The camera pans left."),
    ("slow pan right", "The camera pans right."),
    ("slow tilt up", "The camera tilts up."),
    ("slow tilt down", "The camera tilts down."),
    ("static", "The camera stays static."),
)
CAMERA_KEYS = tuple(key for key, _ in CAMERA_SENTENCES)


def max_static(panels):
    """The most beats a movie of `panels` beats may give the static camera: one in three, rounded
    up (shot prompt format spec SF2, D3)."""
    return (panels + 2) // 3


ARC_ROLES = ("introduction", "rising", "climax", "falling", "resolution")
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "camera is exactly one of: @@CAMERA_LIST@@. location is the id of the place where the beat "
```

with:

```python
    "camera is exactly one of: @@CAMERA_LIST@@.@@CAMERA_RULE@@ location is the id of the place where the beat "
```

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
SPEAKER_RULE = (" speaker is the id of the one character who says something aloud on screen "
                "during the beat, or an empty string when nobody speaks; give a speaker only where "
                "a spoken line moves the story. A beat with a speaker shows only that character "
                "(its cast is just their id), facing the camera, in a medium shot, medium close-up "
                "or close-up; the speaker may move during the beat, and the camera may stay static, "
                "push in, pull back or track them, as long as their face stays in frame and lit "
                "while they speak.")
SILENT_SPEAKER_RULE = " speaker is always an empty string: nobody speaks in this movie."
# Pinned cast presence spec PC5, D3: in chained mode a declared character still in frame stays
# in a speaking beat, silent.
SPEAKER_RULE_KEEP_CAST = (
    " speaker is the id of the one character who says something aloud on screen during the "
    "beat, or an empty string when nobody speaks; give a speaker only where a spoken line moves "
    "the story. A beat with a speaker shows that character facing the camera, in a medium shot, "
    "medium close-up or close-up; its cast is the speaker's id plus the id of every already-cast "
    "character who is still in frame and stays silent, and no character of your own. The speaker "
    "may move during the beat, and the camera may stay static, push in, pull back or track them, "
    "as long as their face stays in frame and lit while they speak.")
```

with:

```python
# Shot prompt format spec SF3, D7: a speaking beat's action is physical, and it ends with the
# speaker in frame and nobody else acting.
SPEAKING_BEAT_SENTENCE = (" Write a speaking beat's action as what the speaker physically does, "
                          "never as speaking, and end it with the speaker still in frame: nobody "
                          "else acts after the line, and when the narrative has the speaker "
                          "leave, or another character act, after a line, give that a later beat "
                          "with no speaker, or leave it out when no later beat is left.")
SPEAKER_RULE = (" speaker is the id of the one character who says something aloud on screen "
                "during the beat, or an empty string when nobody speaks; give a speaker only where "
                "a spoken line moves the story. A beat with a speaker shows only that character "
                "(its cast is just their id), facing the camera, in a medium shot, medium close-up "
                "or close-up; the speaker may move during the beat, as long as their face stays in "
                "frame and lit while they speak." + SPEAKING_BEAT_SENTENCE)
SILENT_SPEAKER_RULE = " speaker is always an empty string: nobody speaks in this movie."
# Shot prompt format spec SF2, D1: one move per beat, static only as a capped deliberate hold.
CAMERA_RULE = (" Give every beat one camera move from this list, and use static only for a "
               "deliberate hold: at most one beat in three may be static, so at most "
               "@@MAX_STATIC@@ in this movie.")
CAMERA_SPEAKING_SENTENCE = (" On a beat with a speaker, prefer slow push-in, slow pull-back, "
                            "tracking or handheld, and never use a pan or a tilt, which sweeps "
                            "the speaker's face out of the frame.")
# Pinned cast presence spec PC5, D3: in chained mode a declared character still in frame stays
# in a speaking beat, silent.
SPEAKER_RULE_KEEP_CAST = (
    " speaker is the id of the one character who says something aloud on screen during the "
    "beat, or an empty string when nobody speaks; give a speaker only where a spoken line moves "
    "the story. A beat with a speaker shows that character facing the camera, in a medium shot, "
    "medium close-up or close-up; its cast is the speaker's id plus the id of every already-cast "
    "character who is still in frame and stays silent, and no character of your own. The speaker "
    "may move during the beat, as long as their face stays in frame and lit while they speak."
    + SPEAKING_BEAT_SENTENCE)
```

**3.4.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        ("@@CAMERA_LIST@@", ", ".join(CAMERA_KEYS)),
```

with:

```python
        ("@@CAMERA_LIST@@", ", ".join(CAMERA_KEYS)),
        ("@@CAMERA_RULE@@", CAMERA_RULE + ("" if ctx.narration is False
                                           else CAMERA_SPEAKING_SENTENCE)),
```

**3.5.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
               ("@@LINE_WORDS@@", line_cap)]
```

with:

```python
               ("@@LINE_WORDS@@", line_cap), ("@@MAX_STATIC@@", str(max_static(ctx.panels)))]
```

**3.6.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
# Narrative dialogue fidelity spec SM1: a speaking beat may be a medium shot, and its camera may
# stay static, push in, pull back or track the speaker.
SPEAKING_SHOTS = ("medium shot", "medium close-up", "close-up")
SPEAKING_CAMERAS = ("static", "slow push-in", "slow pull-back", "tracking")


def speaking_camera(beat):
    """The beat's camera when a speaking shot may keep it, else "static" (SM1)."""
    return beat["camera"] if beat["camera"] in SPEAKING_CAMERAS else "static"
```

with:

```python
# Narrative dialogue fidelity spec SM1; shot prompt format spec SF4, D2: a speaking beat may be
# a medium shot, and its camera pushes in, pulls back, tracks, is handheld or stays static.
SPEAKING_SHOTS = ("medium shot", "medium close-up", "close-up")
SPEAKING_CAMERAS = ("slow push-in", "slow pull-back", "tracking", "handheld", "static")


def speaking_camera(beat):
    """The beat's camera when a speaking shot may keep it, else "slow push-in" (SM1; shot prompt
    format spec SF4)."""
    return beat["camera"] if beat["camera"] in SPEAKING_CAMERAS else "slow push-in"
```

**3.7.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    shot when silent library characters share the beat, and a camera that does not stay static,
    push in, pull back or track becomes static. Tracking is never coerced away."""
```

with:

```python
    shot when silent library characters share the beat, and a camera that does not push in,
    pull back, track, move handheld or stay static becomes a slow push-in (shot prompt format
    spec SF4). Tracking is never coerced away."""
```

**3.8.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        if beat["camera"] not in SPEAKING_CAMERAS:
            notes.append("beat %d: P14 speaking beat: camera %s changed to 'static' so the "
                         "speaker's face stays readable" % (k, _q(beat["camera"])))
            beat["camera"] = "static"
    return notes


def is_group_entry(entry):
```

with:

```python
        if beat["camera"] not in SPEAKING_CAMERAS:
            notes.append("beat %d: P14 speaking beat: camera %s changed to 'slow push-in' so "
                         "the speaker's face stays readable" % (k, _q(beat["camera"])))
            beat["camera"] = "slow push-in"
    return notes


# Shot prompt format spec SF5, D3: at most max_static(panels) static beats; the earliest excess
# ones become a slow push-in, and the latest static beats stay as the deliberate holds.
P18_NOTE = ("beat %d: P18 static camera: camera 'static' changed to 'slow push-in': at most %d "
            "of the %d beats may be static, and the latest static beats are kept as the "
            "deliberate holds")


def cap_static_cameras(ctx, plan):
    """The P18 notes of the static cap (shot prompt format spec SF5), in beat order; changes
    plan["beats"] in place."""
    cap = max_static(ctx.panels)
    static = [k for k, beat in enumerate(plan["beats"], start=1) if beat["camera"] == "static"]
    notes = []
    for k in static[:max(0, len(static) - cap)]:
        plan["beats"][k - 1]["camera"] = "slow push-in"
        notes.append(P18_NOTE % (k, cap, ctx.panels))
    return notes


def is_group_entry(entry):
```

**3.9.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
                      "tracking", "follow", "follows")
```

with:

```python
                      "tracking", "follow", "follows", "handheld")
```

**3.10.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        plan["speech_notes"] += assign_missing_lines(ctx, plan)
```

with:

```python
        plan["speech_notes"] += assign_missing_lines(ctx, plan)
        plan["speech_notes"] += cap_static_cameras(ctx, plan)
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/sf-baseline
cd $S/sf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_shot_format.py 2>&1 | tail -1
```

Expected: `7 passed`. Then run the compile check (Global Constraints) with `FILES` = `story_engine.py tests/test_shot_format.py`. Expected: `compiled 2` twice. Then the gate, a full run of about 15 minutes, which may run in the background:

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/sf-baseline
cd $S/sf-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/task-1-pytest.txt 2>&1; tail -1 $D/task-1-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/task-1-pytest.txt $D/expected-failures.txt 1
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1
```

Expected:
- `GATE PASS`;
- `test_shot_format 7, not passing 0` and `baseline failures still failing 2 of 2`;
- `OK 347/347`.

On `GATE STOP`, follow the gate rule ("Between tasks").

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_shot_format.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_shot_format.py
git commit -m "feat(story): one camera move per beat, static capped at one beat in three, a speaking pan becomes a push-in (SF1-SF5, P18; SFT1a, SFT2-SFT4, SFT22)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The writer camera contract, the word ranges and the format reference (SF6-SF8, Plan ruling PR1)

This task implements:
- SF6, `panel_camera`, the pasted camera on every panel (chained k >= 2 included) and the CM4 fix in `panel_fields`;
- SF7, `WORD_RANGES`, the three replaced key lines and the `no_stills_prompt` clause, the new writer constants, `SPEAKING_CHAINED_MOTION_SENTENCE` and the `build_panel_prompt` key-line additions;
- SF8, `FORMAT_REFERENCE` and its insertion;
- Plan ruling PR1, `cleanup_pieces` in `parse_panel_reply`. Without it, the cleanup blanks the planned sentence's words out of the writer's own camera sentence (SK5).

Tests: SFT1 (writer part), SFT3 (paste part), SFT5, SFT6 and SFT21.

**Files:**
- Modify: `story_engine.py`. The edits go to `WORD_RANGES` (`:56-58`), before and in `pasted_pieces` (`:1478-1501`), after `pasted_pieces` (`:1504-1507`), after `COPIED_EXAMPLES` (`:1893`), the template line `:1917`, the key lines (`:1944-1958`, `:1964-1965`, `:1979-1984`), `SPEAKING_CHAINED_MOTION_SENTENCE` (`:2016-2030`), after `SPEAKING_SENTENCES` (`:2044-2045`), `parse_panel_reply` (`:2158`), `panel_fields` (`:2183-2184`, `:2201`) and `build_panel_prompt` (`:2794`, `:2819-2820`, `:2825-2826`, `:2846`).
- Modify: `tests/test_shot_format.py` (append).

**Interfaces:**
- Consumes: Task 1's `CAMERA_SENTENCES`, `speaking_camera`, `SPEAKING_CAMERAS` and the test helpers; the existing `panel_speaks(ctx, plan, k)`, `engine_seconds(ctx)`, `ACTION_SECONDS`, `empty_parts`, `parse_panel_reply(ctx, plan, k, answer)`, `panel_fields(ctx, plan, parts, k) -> [(Label, text)]` and `build_panel_prompt(ctx, plan, parts, k, fix=None)`.
- Produces:
  - In `story_engine`:
    - the functions `panel_camera(ctx, plan, k) -> str` (a camera key, or the beat's raw camera) and `cleanup_pieces(pasted: dict, key: str) -> [str]`;
    - the constants `CAMERA_WRITER_SENTENCE` (tokens `@@CAMERA_MOVE@@`, `@@CAMERA_FORM@@`), `CAMERA_WRITER_FORMS` (`{key: (move, form)}` for every `CAMERA_KEYS` key), `SPEAKING_REACTION_SENTENCE`, `SPEAKING_NO_REACTION_SENTENCE`, `SPEAKING_STAY_SENTENCE` (token `@@SPEAKER@@`) and `FORMAT_REFERENCE` (2406 characters, no `@@`).
  - In the test module: `_sft5(ws, mode="shots", narration="speech", cameras=(...), speaker_beat=2, **ctx_kw) -> (ctx, plan, parts)`, `_key_line(prompt, key) -> str`, `_writer_sentence(camera) -> str`, `SFT6_ACTION` and `SFT6_CAMERA`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_sft1b_writer_constants`, `test_sft3b_a_chained_speaking_pan_pastes_a_push_in`, `test_sft5_the_writer_prompt`, `test_sft6_the_pasted_camera_is_only_a_fallback` and `test_sft21_the_reference_adds_exactly_its_own_length`.

Edit `tests/test_shot_format.py` (append): replace this text, the file's last lines, which occurs exactly once:

```python
    assert story_env["home"].startswith(str(tmp_path))
    assert os.environ["QWEN_AGENT_DAEMON_URL"].startswith("http://127.0.0.1:")
    assert "ANTHROPIC_API_KEY" not in os.environ
```

with:

```python
    assert story_env["home"].startswith(str(tmp_path))
    assert os.environ["QWEN_AGENT_DAEMON_URL"].startswith("http://127.0.0.1:")
    assert "ANTHROPIC_API_KEY" not in os.environ


# --- SFT1 (Task 2 part): the writer constants (SF6-SF8) ----------------------------------------

WORD_RANGES = {"chained": {"image1": (120, 170), "motion1": (55, 105), "motion": (55, 105)},
               "no_stills": {"prompt": (150, 220)},
               "shots": {"image": (80, 170), "motion": (55, 105)}}
PACING_SENTENCE = se.PACING_SENTENCE
KEY_LINES = {
    "chained_motion1": (
        "motion: W1 to W2 words: one or two plain sentences of what the characters physically do "
        "during these @@SECONDS@@ seconds, then the camera sentence. Name each character only by "
        "their referring phrase, word for word. Describe ONE continuous physical motion, not a "
        "sequence of separate steps: @@SECONDS@@ seconds is enough for a single gesture, a few "
        "footsteps or the start of a movement." + PACING_SENTENCE),
    "chained_motion": (
        "motion: W1 to W2 words: one or two plain sentences of what the characters physically do "
        "during these @@SECONDS@@ seconds, continuing from where the previous panel left them, "
        "then the camera sentence. Name each character only by their referring phrase, word for "
        "word. Describe ONE continuous physical motion, not a sequence of separate steps: "
        "@@SECONDS@@ seconds is enough for a single gesture, a few footsteps or the start of a "
        "movement." + PACING_SENTENCE + " Do not describe appearance, clothing, setting, "
        "lighting, colour or style -- all of that is already on screen."),
    "shots_motion": (
        "motion: W1 to W2 words: ONE sentence naming ONE character by their referring phrase and "
        "the ONE physical action they perform during these @@SECONDS@@ seconds, told in concrete "
        "detail (where in the frame they start, how they move and where they end), then the "
        "camera sentence. Never chain actions with then, while, meanwhile, simultaneously, "
        "afterwards, followed by or a comma before and, and never use a semicolon."),
}
CAMERA_WRITER_SENTENCE = (" End this field with exactly one camera sentence, for this panel's "
                          "planned camera, in which the camera @@CAMERA_MOVE@@: begin it with "
                          "'The camera' and write it like @@CAMERA_FORM@@, with your own words in "
                          "place of the part in angle brackets. Write no other camera direction "
                          "anywhere in this field.")
CAMERA_WRITER_FORMS = {
    "slow push-in": ("pushes in", "'The camera pushes in — as the move completes, <what then "
                                  "fills the frame>.'"),
    "slow pull-back": ("pulls back", "'The camera pulls back — as the move completes, <what the "
                                     "wider frame then shows>.'"),
    "tracking": ("tracks the movement", "'The camera tracks <whom it follows> — as the move "
                                        "completes, <where the frame ends>.'"),
    "handheld": ("moves handheld", "'The camera follows with handheld movement — as the move "
                                   "completes, <where the frame ends>.'"),
    "slow pan left": ("pans left", "'The camera pans left — as the move completes, <what the "
                                   "frame ends on>.'"),
    "slow pan right": ("pans right", "'The camera pans right — as the move completes, <what the "
                                     "frame ends on>.'"),
    "slow tilt up": ("tilts up", "'The camera tilts up — as the move completes, <what the frame "
                                 "ends on>.'"),
    "slow tilt down": ("tilts down", "'The camera tilts down — as the move completes, <what the "
                                     "frame ends on>.'"),
    "static": ("stays static", "'The camera stays static, holding <what stays in the frame>.'"),
}
# Shot prompt format spec SF7, D7: a shots speaking panel's reaction after the line, and the
# speaker staying in frame (every mode).
SPEAKING_REACTION_SENTENCE = (" The pipeline puts the spoken line right after your first "
                              "sentence. Between that sentence and the camera sentence you may "
                              "write one short sentence, beginning with @@SPEAKER@@, of how they "
                              "react once the line is said, such as a nod, a breath or a glance "
                              "down; nobody else acts in it.")
SPEAKING_NO_REACTION_SENTENCE = (" The pipeline puts the spoken line right after your first "
                                 "sentence, so write no other action sentence.")
SPEAKING_STAY_SENTENCE = (" In this whole panel @@SPEAKER@@ never leaves, turns away or moves "
                          "out of the frame, even when the beat says so.")
SPEAKING_CHAINED_MOTION_SENTENCE = (
    " In this panel @@SPEAKER@@ speaks the dialogue, and the pipeline inserts it right after the "
    "first sentence about what @@SPEAKER@@ does. Write that first sentence as everything "
    "@@SPEAKER@@ does before the dialogue, ending with them near the camera, face toward it (if "
    "the dialogue comes before they do anything, it is how they turn or step toward the camera; "
    "never write only that they face it); after it you may write one short second sentence of "
    "how @@SPEAKER@@ reacts once the line is said, such as a nod, a breath or a glance down, in "
    "which nobody else acts. Begin each of these sentences with @@SPEAKER@@, word for word, and "
    "write nothing about anyone else before the first one. Never put an action from before the "
    "dialogue and one from after it in the same sentence, and do not write the spoken words or a "
    "speaking verb; the pipeline adds them.")
FORMAT_REFERENCE_SHA256 = "d2fe46c687bdaf8ebc75235bdf530d5d751aa1fa62f9bf393bf9855bef7681dd"


def test_sft1b_writer_constants():
    assert se.WORD_RANGES == WORD_RANGES
    for key, line in KEY_LINES.items():
        assert se.KEY_LINE_TEMPLATES[key] == line, key
    for key in ("no_stills_prompt", "no_stills_prompt_speaking"):
        line = se.KEY_LINE_TEMPLATES[key]
        assert "you may also state a camera movement" not in line, key
        assert ("and states the camera viewpoint and the lighting and colour. Name each character "
                "only by their referring phrase.") in line, key
    assert se.CAMERA_WRITER_SENTENCE == CAMERA_WRITER_SENTENCE
    assert se.CAMERA_WRITER_FORMS == CAMERA_WRITER_FORMS
    assert set(se.CAMERA_WRITER_FORMS) == set(se.CAMERA_KEYS)
    assert se.SPEAKING_REACTION_SENTENCE == SPEAKING_REACTION_SENTENCE
    assert se.SPEAKING_NO_REACTION_SENTENCE == SPEAKING_NO_REACTION_SENTENCE
    assert se.SPEAKING_STAY_SENTENCE == SPEAKING_STAY_SENTENCE
    assert se.SPEAKING_CHAINED_MOTION_SENTENCE == SPEAKING_CHAINED_MOTION_SENTENCE
    reference = se.FORMAT_REFERENCE
    assert hashlib.sha256(reference.encode("utf-8")).hexdigest() == FORMAT_REFERENCE_SHA256
    assert (len(reference), len(reference.split())) == (2406, 421)
    assert "@@" not in reference
    for text in ([reference, se.CAMERA_WRITER_SENTENCE, se.SPEAKING_REACTION_SENTENCE,
                  se.SPEAKING_NO_REACTION_SENTENCE, se.SPEAKING_STAY_SENTENCE,
                  se.SPEAKING_CHAINED_MOTION_SENTENCE]
                 + [se.KEY_LINE_TEMPLATES[key] for key in KEY_LINES]
                 + [form for _move, form in se.CAMERA_WRITER_FORMS.values()]):
        assert "slowly" not in text.lower(), text


# --- SFT3 (Task 2 part): the chained paste-time speaking camera (SF4, SF6) --------------------

def test_sft3b_a_chained_speaking_pan_pastes_a_push_in(ws, story_env):
    ctx = seu.make_ctx(se, ws, mode="chained", panels=2, members=_members(story_env),
                       narration="speech")
    raw = _raw("chained", 2, [["c1"], ["c1"]], ["", "c1"])
    raw["beats"][1]["camera"] = "slow pan right"
    plan, _shape = se.normalize_plan(ctx, raw)
    assert plan["beats"][1]["camera"] == "slow pan right"
    assert se.panel_camera(ctx, plan, 2) == "slow push-in"
    assert se.panel_camera(ctx, plan, 1) == plan["beats"][0]["camera"]
    assert se.pasted_pieces(ctx, plan, 2)["motion"] == ["The woman in grey faces the camera.",
                                                        "The camera pushes in."]


# --- SFT5: the writer prompt (SF7, SF8, SK9) ---------------------------------------------------

def _sft5(ws, mode="shots", narration="speech", cameras=("tracking", "slow push-in", "static"),
          speaker_beat=2, **ctx_kw):
    """(ctx, plan, parts) of a 3-panel movie: beat k's camera cameras[k - 1], the courier (c1)
    speaking in beat speaker_beat (none when 0), empty writer parts."""
    ctx = seu.make_ctx(se, ws, mode=mode, panels=3, narration=narration, **ctx_kw)
    raw = seu.plan_json(mode, 3)
    for beat, camera in zip(raw["beats"], cameras):
        beat["camera"] = camera
    if speaker_beat:
        raw["beats"][speaker_beat - 1]["speaker"] = "c1"
    plan, _shape = se.normalize_plan(ctx, raw)
    return ctx, plan, [se.empty_parts(mode, k, plan, ctx) for k in (1, 2, 3)]


def _key_line(prompt, key):
    return [line for line in prompt.split("\n") if line.startswith(key + ": ")][0]


def _writer_sentence(camera):
    move, form = se.CAMERA_WRITER_FORMS[camera]
    return (se.CAMERA_WRITER_SENTENCE.replace("@@CAMERA_MOVE@@", move)
            .replace("@@CAMERA_FORM@@", form))


def test_sft5_the_writer_prompt(ws):
    ctx, plan, parts = _sft5(ws)
    first = se.build_panel_prompt(ctx, plan, parts, 1)
    assert _key_line(first, "motion").endswith(_writer_sentence("tracking"))
    second = se.build_panel_prompt(ctx, plan, parts, 2)
    speaking = (se.SPEAKING_ACTION_SENTENCE + se.SPEAKING_REACTION_SENTENCE
                + se.SPEAKING_STAY_SENTENCE).replace("@@SPEAKER@@", '"the courier"')
    assert speaking + _writer_sentence("slow push-in") in _key_line(second, "motion")
    for prompt in (first, second):
        assert prompt.count(se.FORMAT_REFERENCE) == 1
        assert (se.FORMAT_REFERENCE + "Write this panel as one JSON object") in prompt
        assert "@@" not in prompt
    ctx, plan, parts = _sft5(ws, clip_seconds=5.04)
    short = _key_line(se.build_panel_prompt(ctx, plan, parts, 2), "motion")
    no_reaction = (se.SPEAKING_ACTION_SENTENCE + se.SPEAKING_NO_REACTION_SENTENCE
                   + se.SPEAKING_STAY_SENTENCE).replace("@@SPEAKER@@", '"the courier"')
    assert no_reaction + _writer_sentence("slow push-in") in short
    assert "of how they react once the line is said" not in short
    ctx, plan, parts = _sft5(ws, mode="chained", cameras=("tracking", "static", "static"),
                             speaker_beat=0)
    for k in (1, 2):
        prompt = se.build_panel_prompt(ctx, plan, parts, k)
        assert prompt.count(se.FORMAT_REFERENCE) == 1, k
        assert "@@" not in prompt, k
    assert "in which the camera stays static" in _key_line(
        se.build_panel_prompt(ctx, plan, parts, 2), "motion")
    for mode, narration in (("no_stills", "speech"), ("no_stills", True), ("chained", False),
                            ("shots", False), ("no_stills", False)):
        ctx, plan, parts = _sft5(ws, mode=mode, narration=narration)
        for k in (1, 2, 3):
            prompt = se.build_panel_prompt(ctx, plan, parts, k)
            assert "FORMAT REFERENCE ONLY" not in prompt, (mode, narration, k)
            assert "@@" not in prompt, (mode, narration, k)
    ctx, plan, parts = _sft5(ws, cameras=("", "slow push-in", "static"))
    assert "End this field with exactly one camera sentence" not in _key_line(
        se.build_panel_prompt(ctx, plan, parts, 1), "motion")


# --- SFT6: the pasted camera is only a fallback (SF6, plan ruling PR1, SK5) ----------------------

SFT6_ACTION = "The courier steps onto the wet quay at real-time speed."
SFT6_CAMERA = "The camera pushes in — as the move completes, her face fills the frame."


def test_sft6_the_pasted_camera_is_only_a_fallback(ws):
    for mode in ("chained", "shots", "no_stills"):
        label = "Prompt" if mode == "no_stills" else "Motion"
        for speaks in (False, True):
            ctx = seu.make_ctx(se, ws, mode=mode, panels=2, narration="speech")
            raw = seu.plan_json(mode, 2)
            for beat in raw["beats"]:
                beat["camera"] = "slow push-in"
                beat["speaker"] = "c1" if speaks else ""
            plan, _shape = se.normalize_plan(ctx, raw)
            for k in (1, 2):
                where = (mode, speaks, k)
                assert se.panel_camera(ctx, plan, k) == "slow push-in", where
                reply = seu.panel_json(mode, k)
                if speaks:
                    reply["dialogue"] = "Go now."
                for writer in (SFT6_ACTION, SFT6_ACTION + " " + SFT6_CAMERA):
                    reply[label.lower()] = writer
                    parts = [se.empty_parts(mode, j, plan, ctx) for j in (1, 2)]
                    parts[k - 1] = se.parse_panel_reply(ctx, plan, k, json.dumps(reply))
                    field = dict(se.panel_fields(ctx, plan, parts, k))[label]
                    assert field.count("The camera") == 1, where
                    if writer == SFT6_ACTION:
                        assert field.endswith(" The camera pushes in."), where
                    else:
                        assert SFT6_CAMERA in field, where
                        assert "The camera pushes in." not in field, where


# --- SFT21: the prompt budget (SF8) ------------------------------------------------------------

def test_sft21_the_reference_adds_exactly_its_own_length(ws, monkeypatch):
    ctx, plan, parts = _sft5(ws)
    reference = se.FORMAT_REFERENCE
    full = se.build_panel_prompt(ctx, plan, parts, 2)
    monkeypatch.setattr(se, "FORMAT_REFERENCE", "")
    bare = se.build_panel_prompt(ctx, plan, parts, 2)
    assert len(full) - len(bare) == len(reference) == 2406
    assert len(full) < 9000
```

- [ ] **Step 2: Run the tests to verify that they fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_shot_format.py 2>&1 | tail -1
```

Expected: `5 failed, 7 passed`. The five new tests fail: on `WORD_RANGES`, the missing `panel_camera`, `CAMERA_WRITER_FORMS` and `FORMAT_REFERENCE`.

- [ ] **Step 3: Implement SF6-SF8 and PR1.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
WORD_RANGES = {"chained": {"image1": (120, 170), "motion1": (15, 35), "motion": (15, 35)},
               "no_stills": {"prompt": (150, 220)},
               "shots": {"image": (80, 170), "motion": (10, 25)}}
```

with:

```python
WORD_RANGES = {"chained": {"image1": (120, 170), "motion1": (55, 105), "motion": (55, 105)},
               "no_stills": {"prompt": (150, 220)},
               "shots": {"image": (80, 170), "motion": (55, 105)}}
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
               for s in _sentences(text))


def pasted_pieces(ctx, plan, k):
    """{field: [pasted sentences in assembly order]} for panel k (RS14; dialogue spec SP4): the
    pieces of each assembled field that the writer does not write. A speaking panel adds the
    facing sentence (and, chained k >= 2, the camera sentence of speaking_camera: the planned
    camera, or "The camera stays static." for a pan or tilt; narrative dialogue fidelity spec
    SM3). The planned camera sentence is always listed, even when CM4 leaves it out of the
    assembled field."""
```

with:

```python
               for s in _sentences(text))


def panel_camera(ctx, plan, k):
    """The camera key panel k uses (shot prompt format spec SF6): speaking_camera(beat) on a
    chained k >= 2 speaking panel, else the beat's planned camera."""
    beat = plan["beats"][k - 1]
    if ctx.mode == "chained" and k >= 2 and panel_speaks(ctx, plan, k):
        return speaking_camera(beat)
    return beat["camera"]


def pasted_pieces(ctx, plan, k):
    """{field: [pasted sentences in assembly order]} for panel k (RS14; dialogue spec SP4): the
    pieces of each assembled field that the writer does not write. A speaking panel adds the
    facing sentence; every panel, chained k >= 2 included, lists its panel_camera sentence
    (shot prompt format spec SF6). The planned camera sentence is always listed, even when
    CM4 leaves it out of the assembled field."""
```

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    camera = dict(CAMERA_SENTENCES).get(beat["camera"], "")
```

with:

```python
    camera = dict(CAMERA_SENTENCES).get(panel_camera(ctx, plan, k), "")
```

**3.4.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        return {"motion": facing + ([dict(CAMERA_SENTENCES)[speaking_camera(beat)]]
                                    if facing else []), "narration": []}
```

with:

```python
        return {"motion": facing + [camera], "narration": []}
```

**3.5.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "chained_motion1": (
        "motion: W1 to W2 words in one or two plain sentences: what the characters physically do "
        "during these @@SECONDS@@ seconds. Name each character only by their referring phrase, "
        "word for word. Describe ONE continuous physical motion, not a sequence of separate "
        "steps: @@SECONDS@@ seconds is enough for a single gesture, a few footsteps or the "
        "start of a movement." + PACING_SENTENCE + " You may add one camera direction; without "
        "one, the pipeline adds the planned camera sentence."),
    "chained_motion": (
        "motion: W1 to W2 words in one or two plain sentences: what the characters physically do "
        "during these @@SECONDS@@ seconds, continuing from where the previous panel left them. "
        "Name each character only by their referring phrase, word for word. Describe ONE "
        "continuous physical motion, not a sequence of separate steps: @@SECONDS@@ seconds is "
        "enough for a single gesture, a few footsteps or the start of a movement."
        + PACING_SENTENCE + " Do not describe appearance, clothing, setting, lighting, colour or "
        "style -- all of that is already on screen. You may add one camera direction."),
```

with:

```python
    "chained_motion1": (
        "motion: W1 to W2 words: one or two plain sentences of what the characters physically do "
        "during these @@SECONDS@@ seconds, then the camera sentence. Name each character only by "
        "their referring phrase, word for word. Describe ONE continuous physical motion, not a "
        "sequence of separate steps: @@SECONDS@@ seconds is enough for a single gesture, a few "
        "footsteps or the start of a movement." + PACING_SENTENCE),
    "chained_motion": (
        "motion: W1 to W2 words: one or two plain sentences of what the characters physically do "
        "during these @@SECONDS@@ seconds, continuing from where the previous panel left them, "
        "then the camera sentence. Name each character only by their referring phrase, word for "
        "word. Describe ONE continuous physical motion, not a sequence of separate steps: "
        "@@SECONDS@@ seconds is enough for a single gesture, a few footsteps or the start of a "
        "movement." + PACING_SENTENCE + " Do not describe appearance, clothing, setting, "
        "lighting, colour or style -- all of that is already on screen."),
```

**3.6.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        "actions that make them, and states the camera viewpoint and the lighting and colour; you "
        "may also state a camera movement. Name each character only by their referring phrase. Do "
```

with:

```python
        "actions that make them, and states the camera viewpoint and the lighting and colour. "
        "Name each character only by their referring phrase. Do "
```

**3.7.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "shots_motion": (
        "motion: ONE sentence of W1 to W2 words naming ONE character by their referring phrase "
        "and the ONE physical action they perform during these @@SECONDS@@ seconds. Never chain "
        "actions with then, while, meanwhile, simultaneously, afterwards, followed by or a comma "
        "before and, and never use a semicolon. You may follow it with one camera sentence; "
        "without one, the pipeline adds the planned camera sentence."),
```

with:

```python
    "shots_motion": (
        "motion: W1 to W2 words: ONE sentence naming ONE character by their referring phrase and "
        "the ONE physical action they perform during these @@SECONDS@@ seconds, told in concrete "
        "detail (where in the frame they start, how they move and where they end), then the "
        "camera sentence. Never chain actions with then, while, meanwhile, simultaneously, "
        "afterwards, followed by or a comma before and, and never use a semicolon."),
```

**3.8.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
# Writer pacing spec WP2, D1, D2: a chained speaking panel's motion is one sentence before the
# dialogue (which character_lib.insert_speech places after it) and, when the beat goes on, one
# after it.
SPEAKING_CHAINED_MOTION_SENTENCE = (
    " In this panel @@SPEAKER@@ speaks the dialogue, and the pipeline inserts it right after the "
    "first sentence about what @@SPEAKER@@ does. Write that first sentence as everything "
    "@@SPEAKER@@ does before the dialogue, ending with them near the camera, face toward it (if "
    "the dialogue comes before they do anything, it is how they turn or step toward the camera; "
    "never write only that they face it); only when the beat has them act after the dialogue, "
    "write what they do then as a second "
    "sentence. Begin each of these sentences with @@SPEAKER@@, word for word, and write nothing "
    "about anyone else before the first one. The action before the dialogue and the action "
    "after it are the two parts of this one motion: never put an action from before the "
    "dialogue and one from after it in the same sentence, and do not write the spoken words or "
    "a speaking verb; the pipeline adds them.")
```

with:

```python
# Writer pacing spec WP2, D1, D2: a chained speaking panel's motion is one sentence before the
# dialogue (which character_lib.insert_speech places after it) and, when the beat goes on, one
# after it; shot prompt format spec SF7.
SPEAKING_CHAINED_MOTION_SENTENCE = (
    " In this panel @@SPEAKER@@ speaks the dialogue, and the pipeline inserts it right after the "
    "first sentence about what @@SPEAKER@@ does. Write that first sentence as everything "
    "@@SPEAKER@@ does before the dialogue, ending with them near the camera, face toward it (if "
    "the dialogue comes before they do anything, it is how they turn or step toward the camera; "
    "never write only that they face it); after it you may write one short second sentence of "
    "how @@SPEAKER@@ reacts once the line is said, such as a nod, a breath or a glance down, in "
    "which nobody else acts. Begin each of these sentences with @@SPEAKER@@, word for word, and "
    "write nothing about anyone else before the first one. Never put an action from before the "
    "dialogue and one from after it in the same sentence, and do not write the spoken words or a "
    "speaking verb; the pipeline adds them.")
```

**3.9.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
SPEAKING_SENTENCES = {"image": SPEAKING_IMAGE_SENTENCE, "motion": SPEAKING_ACTION_SENTENCE,
                      "prompt": SPEAKING_PROMPT_SENTENCE}
```

with:

```python
SPEAKING_SENTENCES = {"image": SPEAKING_IMAGE_SENTENCE, "motion": SPEAKING_ACTION_SENTENCE,
                      "prompt": SPEAKING_PROMPT_SENTENCE}
# Shot prompt format spec SF7, D4: the writer writes the panel's one camera sentence, with the
# end frame; CAMERA_WRITER_FORMS maps a camera key to (the move, as said of the camera; the form).
CAMERA_WRITER_SENTENCE = (" End this field with exactly one camera sentence, for this panel's "
                          "planned camera, in which the camera @@CAMERA_MOVE@@: begin it with "
                          "'The camera' and write it like @@CAMERA_FORM@@, with your own words in "
                          "place of the part in angle brackets. Write no other camera direction "
                          "anywhere in this field.")
CAMERA_WRITER_FORMS = {
    "slow push-in": ("pushes in", "'The camera pushes in — as the move completes, <what then "
                                  "fills the frame>.'"),
    "slow pull-back": ("pulls back", "'The camera pulls back — as the move completes, <what the "
                                     "wider frame then shows>.'"),
    "tracking": ("tracks the movement", "'The camera tracks <whom it follows> — as the move "
                                        "completes, <where the frame ends>.'"),
    "handheld": ("moves handheld", "'The camera follows with handheld movement — as the move "
                                   "completes, <where the frame ends>.'"),
    "slow pan left": ("pans left", "'The camera pans left — as the move completes, <what the "
                                   "frame ends on>.'"),
    "slow pan right": ("pans right", "'The camera pans right — as the move completes, <what the "
                                     "frame ends on>.'"),
    "slow tilt up": ("tilts up", "'The camera tilts up — as the move completes, <what the frame "
                                 "ends on>.'"),
    "slow tilt down": ("tilts down", "'The camera tilts down — as the move completes, <what the "
                                     "frame ends on>.'"),
    "static": ("stays static", "'The camera stays static, holding <what stays in the frame>.'"),
}
# Shot prompt format spec SF7, D7: a shots speaking panel's reaction after the line, and the
# speaker staying in frame (every mode).
SPEAKING_REACTION_SENTENCE = (" The pipeline puts the spoken line right after your first "
                              "sentence. Between that sentence and the camera sentence you may "
                              "write one short sentence, beginning with @@SPEAKER@@, of how they "
                              "react once the line is said, such as a nod, a breath or a glance "
                              "down; nobody else acts in it.")
SPEAKING_NO_REACTION_SENTENCE = (" The pipeline puts the spoken line right after your first "
                                 "sentence, so write no other action sentence.")
SPEAKING_STAY_SENTENCE = (" In this whole panel @@SPEAKER@@ never leaves, turns away or moves "
                          "out of the frame, even when the beat says so.")
```

**3.10.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    assigned = assigned_dialogue(plan, k)
```

with:

```python
    assigned = assigned_dialogue(plan, k)
    camera_key = panel_camera(ctx, plan, k)
    fits_two = max(1, int(engine_seconds(ctx) / ACTION_SECONDS + 1e-9)) >= 2
```

**3.11.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
                line += SPEAKING_SENTENCES.get(key, "")
        if key in targets:
```

with:

```python
                line += SPEAKING_SENTENCES.get(key, "")
        if speaks and key in ("motion", "prompt"):
            if ctx.mode == "shots":
                line += SPEAKING_REACTION_SENTENCE if fits_two else SPEAKING_NO_REACTION_SENTENCE
            line += SPEAKING_STAY_SENTENCE
        if key in ("motion", "prompt") and camera_key in CAMERA_WRITER_FORMS:
            line += CAMERA_WRITER_SENTENCE
        if key in targets:
```

**3.12.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
                    .replace("@@SILENT@@", _and_list(silent) if silent else ""))
        key_lines.append(line)
```

with:

```python
                    .replace("@@SILENT@@", _and_list(silent) if silent else ""))
        if camera_key in CAMERA_WRITER_FORMS:
            move, form = CAMERA_WRITER_FORMS[camera_key]
            line = line.replace("@@CAMERA_MOVE@@", move).replace("@@CAMERA_FORM@@", form)
        key_lines.append(line)
```

**3.13.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
)
_LABEL_RE = re.compile(r"^(?:title|image|motion|prompt|narration|dialogue)\s*:\s*",
```

with:

```python
)
# Shot prompt format spec SF8, D9: three finished shots of an unrelated movie, shown to the
# chained and shots writer for their order only. Each "Shot N" text is exactly
# character_lib.panel_prompt of its parts (SFT13).
FORMAT_REFERENCE = (
    "FORMAT REFERENCE ONLY — never reuse its people, places, objects or words. These are the "
    "finished video prompts of three shots from a different movie. They show the order of every "
    "finished shot: the shot type; the action; when someone speaks, the spoken line and then one "
    "short reaction by the speaker; the one camera sentence, which says where the move ends; and "
    "the audio last. The pipeline wrote the sentences that start \"The shot is\", the sentence "
    "\"The old fishmonger faces the camera.\", the spoken line and the audio sentence; the "
    "writer wrote every other sentence.\n"
    "Shot 1 (silent; the camera tracks): The shot is a wide shot. The old fishmonger drags a "
    "tall stack of empty herring crates across the wet concrete of the market hall toward the "
    "half-open shutter at real-time speed, her heavy steps splashing through shallow puddles "
    "that hold the first glow from the harbour doors. The camera tracks alongside her from the "
    "left — as the move completes, she reaches the shutter at frame centre, the long rows of "
    "bare zinc counters stretching away behind her. The audio is the natural ambient sound of "
    "the place, with no music.\n"
    "Shot 2 (speaking; the camera pushes in): The shot is a medium shot. The old fishmonger "
    "looks up from the empty ice trays to the camera, drying her knuckles on a folded cloth at "
    "the zinc counter at real-time speed. The old fishmonger faces the camera. The old "
    "fishmonger says, \"Forty years of mornings.\" After a breath, \"Not one more.\" The old "
    "fishmonger lets the folded cloth drop onto the counter, her shoulders sinking. The camera "
    "pushes in — as the move completes, her face fills the frame from chin to brow, the bare "
    "counters soft behind her. The audio is clear close-mic dialogue with a subtle natural room "
    "tone; the dialogue takes priority over the quiet ambience, and there is no music.\n"
    "Shot 3 (silent; the movie's one deliberate static hold): The shot is a close-up. The old "
    "fishmonger presses her forehead against the cold ribs of the half-closed steel shutter at "
    "real-time speed, both palms flat on the metal, her breath fogging the ribbed steel as a "
    "thin trickle of meltwater runs past her knuckles and drips onto the wet concrete at her "
    "feet. The camera stays static, holding her face, her knuckles and the ribbed steel tight in "
    "the frame as her eyelids drop shut and the shutter stops trembling. The audio is the "
    "natural ambient sound of the place, with no music.\n\n")
_LABEL_RE = re.compile(r"^(?:title|image|motion|prompt|narration|dialogue)\s*:\s*",
```

**3.14.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "@@SEED_PANEL@@Write this panel as one JSON object with exactly these keys:\n"
```

with:

```python
    "@@FORMAT_REFERENCE@@@@SEED_PANEL@@Write this panel as one JSON object with exactly these keys:\n"
```

**3.15.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        ("@@SEED_PANEL@@", seed),
```

with:

```python
        ("@@FORMAT_REFERENCE@@", FORMAT_REFERENCE
         if ctx.mode in ("chained", "shots") and ctx.narration is not False else ""),
        ("@@SEED_PANEL@@", seed),
```

**3.16.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    return {"image": pieces, "motion": facing + [camera], "narration": []}


def identity(cast_entry):
```

with:

```python
    return {"image": pieces, "motion": facing + [camera], "narration": []}


# Plan ruling PR1 (shot prompt format spec SF6, D4): a writer's camera sentence begins with the
# planned sentence's words ("The camera pushes in — as the move completes, ..."), so the cleanup
# of an action field never blanks a CAMERA_SENTENCES sentence; CM4 (panel_fields) then leaves
# the pasted copy out.
def cleanup_pieces(pasted, key):
    """The pasted sentences clean_writer blanks from the writer's key text: pasted[key], without
    the CAMERA_SENTENCES sentences when key is motion or prompt."""
    cameras = set(sentence for _key, sentence in CAMERA_SENTENCES)
    return [p for p in pasted.get(key, ())
            if key not in ("motion", "prompt") or p not in cameras]


def identity(cast_entry):
```

**3.17.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        value = clean_writer(lib, obj.get(key), pasted.get(key, ()))
```

with:

```python
        value = clean_writer(lib, obj.get(key), cleanup_pieces(pasted, key))
```

**3.18.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    writer text, then the pasted sentences; on a non-speaking panel the planned camera sentence
    is left out when the writer text moves the camera, CM4), Dialogue: on a speaking panel
```

with:

```python
    writer text, then the pasted sentences; the planned camera sentence is left out when the
    writer text moves the camera, CM4; shot prompt format spec SF6), Dialogue: on a speaking panel
```

**3.19.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    if not facing and pieces and _moves_camera(ctx, plan, p.get(key, "")):
```

with:

```python
    if pieces and _moves_camera(ctx, plan, p.get(key, "")):
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_shot_format.py 2>&1 | tail -1
```

Expected: `12 passed`. Run the compile check with `FILES` = `story_engine.py tests/test_shot_format.py`; expected: `compiled 2` twice. Then run the gate block of Task 1 Step 4 with `task-2-pytest.txt` and task number `2`. Expected: `GATE PASS`, `test_shot_format 12, not passing 0`, `baseline failures still failing 2 of 2` and `OK 347/347`.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_shot_format.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_shot_format.py
git commit -m "feat(story): the writer writes the panel's one camera sentence and sees a format reference; the pasted camera is a fallback (SF6-SF8, PR1; SFT1b, SFT3b, SFT5, SFT6, SFT21)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The writer-format checks and their parse-time repairs (SF9-SF12, SF13a, SF13c, SF14, SF15c)

This task implements:
- SF9, the N20 detectors and `_cut_clause`;
- SF10, `EXIT_RE`, `post_line_sentences` and `_other_actor`;
- SF11, `_apply_drops`, `repair_action_text`, the `generating` parameter and the N7 block;
- SF12, `REFERENCE_TERMS`, `REFERENCE_COPY_SEGMENTS`, `REFERENCE_SIX_GRAMS` and `reference_copies`;
- the SF9-SF12 block of `_field_checks`;
- SF13a, the repair in `parse_panel_reply`;
- SF13c, the `repairs` advisories in `panel_checks`;
- SF14, `GENERATION_CHECKS` and the S4/S5 generation arguments;
- SF15c, the `character_lib` parameters they use.

Tests: SFT1 (check part), SFT7, SFT8, SFT9, SFT10, SFT12, SFT15, SFT17, SFT18, and Review Focus 4 and 5.

**Files:**
- Modify: `story_engine.py`. The edits go after `_moves_camera` (`:1477-1478`), after `FORMAT_REFERENCE` (Task 2), in `parse_panel_reply` (`:2168`), in `_field_checks` (`:2299-2302`, `:2381-2387`, `:2553-2557`), to `GENERATION_CHECKS` (`:2698-2699`) and in `panel_checks` (`:2719-2721`, `:2735-2738`).
- Modify: `character_lib.py`: `motion_problems` (`:1127-1136`), `shots_violations` (`:1148`, `:1186-1188`), `motion_length_advisory` (`:1252-1256`) and `shots_advisories` (`:1263-1270`).
- Modify: `tests/test_shot_format.py` (append).

**Interfaces:**
- Consumes:
  - Task 2's `panel_camera`, `CAMERA_WRITER_FORMS` (read at call time) and `FORMAT_REFERENCE`;
  - the existing `_sentences`, `CAMERA_MOTION_RE`, `DIALOGUE_RE`, `_first`, `cast_phrases`, `speaker_phrase`, `_mentions`, `_mentions_at`, `line_words`, `GROUP_NOUNS`, `CLAUSE_STOP_WORDS`, `_CLAUSE_BREAK_RE`, `lib._is_camera_sentence` and `lib.is_facing_sentence`.
- Produces:
  - In `story_engine`:
    - the constants `STATIC_CAMERA_WORDS`, `CAMERA_MOVE_WORDS` (`{key: (words)}`), `CAMERA_CLAUSE_RE`, `_CUT_RE`, `REPAIR_NOTE` (a `%` format of `(k, id, name, Label, quoted text)`), `EXIT_RE`, `REFERENCE_TERMS`, `REFERENCE_COPY_SEGMENTS` and `REFERENCE_SIX_GRAMS` (a frozenset of 138 six-word tuples; Plan ruling PR3);
    - the check helpers `camera_directions(lib, text, phrases) -> [(index, "sentence"|"clause")]`, `camera_problem(lib, text, phrases, key) -> str or None`, `_camera_words`, `_mixed_camera`, `_names_camera(sentence, key) -> bool` and `_cut_clause(sentence, at) -> (head, tail) or None`;
    - the N21 helpers `post_line_sentences(lib, text, phrases) -> [str]` and `_other_actor(sentence, others, own) -> str or None`;
    - the repair functions `_apply_drops(lib, sentences, drop, phrases)`, `repair_action_text(ctx, plan, k, text) -> (text, notes)`, `_six_grams(words) -> set` and `reference_copies(narrative, plan, text, goal=None) -> [str]`;
    - `_field_checks(..., generating=False)`;
    - `parse_panel_reply` adds `"repairs"` only when non-empty.
  - In `character_lib`: `motion_problems(motion, phrases=(), max_actions=1)`, `shots_violations(..., speaking_actions=1)`, `motion_length_advisory(motion, lo=..., hi=...)` and `shots_advisories(panels, members, motion_words=None)`.
  - In the test module: `REPAIR_NOTE`, `GENERATION_CHECKS`, `SFT7_ROWS`, `HOCKEY_E2`, `N21_EXIT(label, sentence, words, speaker)`, `N21_ACTOR(label, sentence, actor, speaker)`, `_n21_plan(ws, story_env, mode, speaker="c1")` and `_n21(ctx, plan, writer) -> (hard, advisory)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_sft1c_check_constants`, `test_sft7_n20_detection`, `test_review_focus_5_an_adverb_on_the_planned_move_is_one_valid_direction`, `test_sft8_the_parse_time_repairs`, `test_sft9_n7_severity`, `test_sft10_n21_detection`, `test_review_focus_4_the_speakers_own_name_and_an_object_are_not_other_actors`, `test_sft12_reference_copies`, `test_sft15_the_s4_and_s5_parameters`, `test_sft17_an_old_story_rechecks_as_before` and `test_sft18_exit_verbs`.

Edit `tests/test_shot_format.py` (append): replace this text, the file's last lines, which occurs exactly once:

```python
    bare = se.build_panel_prompt(ctx, plan, parts, 2)
    assert len(full) - len(bare) == len(reference) == 2406
    assert len(full) < 9000
```

with:

```python
    bare = se.build_panel_prompt(ctx, plan, parts, 2)
    assert len(full) - len(bare) == len(reference) == 2406
    assert len(full) < 9000


# --- SFT1 (Task 3 part): the check constants (SF9-SF12, SF14) ----------------------------------

REFERENCE_TERMS = ("fishmonger", "fishmongers", "herring", "herrings", "zinc", "ice trays",
                   "market hall", "fish market", "harbour doors", "meltwater",
                   "forty years of mornings")
REFERENCE_COPY_SEGMENTS = (
    "The old fishmonger drags a tall stack of empty herring crates across the wet concrete of "
    "the market hall toward the half-open shutter",
    "her heavy steps splashing through shallow puddles that hold the first glow from the "
    "harbour doors",
    "she reaches the shutter at frame centre, the long rows of bare zinc counters stretching "
    "away behind her",
    "The old fishmonger looks up from the empty ice trays to the camera, drying her knuckles on "
    "a folded cloth at the zinc counter",
    "The old fishmonger lets the folded cloth drop onto the counter, her shoulders sinking",
    "her face fills the frame from chin to brow, the bare counters soft behind her",
    "The old fishmonger presses her forehead against the cold ribs of the half-closed steel "
    "shutter",
    "both palms flat on the metal, her breath fogging the ribbed steel as a thin trickle of "
    "meltwater runs past her knuckles and drips onto the wet concrete at her feet",
    "holding her face, her knuckles and the ribbed steel tight in the frame as her eyelids drop "
    "shut and the shutter stops trembling",
    "Forty years of mornings. Not one more.",
)
REPAIR_NOTE = "panel %d: %s %s: %s: the pipeline removed %s"
GENERATION_CHECKS = ("N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11", "N12",
                     "N14", "N15", "N16", "N17", "N18", "T1", "T2", "T3", "N20", "N21", "N22",
                     "Q1", "N19")


def test_sft1c_check_constants():
    assert se.REFERENCE_TERMS == REFERENCE_TERMS
    assert se.REFERENCE_COPY_SEGMENTS == REFERENCE_COPY_SEGMENTS
    assert se.REPAIR_NOTE == REPAIR_NOTE
    assert se.GENERATION_CHECKS == GENERATION_CHECKS
    assert se.GENERATION_CHECKS[16:20] == ("N18", "T1", "T2", "T3")
    assert se.GENERATION_CHECKS[-2:] == ("Q1", "N19")
    assert se.GENERATION_CHECKS[-1] == "N19"
    assert len(se.REFERENCE_SIX_GRAMS) == 138
    assert set(se.CAMERA_WRITER_FORMS) == set(se.CAMERA_KEYS) == set(se.CAMERA_MOVE_WORDS)
    for key, sentence in se.CAMERA_SENTENCES:
        form = re.sub(r"<[^<>]*>", "x", se.CAMERA_WRITER_FORMS[key][1].strip("'"))
        for text in (sentence, form):
            assert se._names_camera(text, key), (key, text)
            assert not se._mixed_camera(text), (key, text)
            assert se.camera_problem(lib, text, [], key) is None, (key, text)


# --- SFT7, Review Focus 5: N20 detection (SF9, SK5) --------------------------------------------

SFT7_ROWS = (
    ("The courier runs. The camera pushes in.", "slow push-in", None),
    ("The courier runs. The camera holds on him as he recedes. The camera stays static.", "static",
     "has 2 camera directions"),
    ("The courier runs while the camera tracks him. The camera pushes in.", "slow push-in",
     "has 2 camera directions"),
    ("The courier runs while the camera tracks him.", "",
     "puts the camera direction inside the action sentence"),
    ("The camera pushes in and stays static.", "slow push-in",
     "the camera sentence 'The camera pushes in and stays static.' has the camera both stay still "
     "and move"),
    ("The camera pans left.", "slow push-in",
     "the camera sentence 'The camera pans left.' does not move the camera the planned way"),
    ("The camera follows with handheld movement.", "handheld", None),
    ("The camera follows her.", "tracking", None),
    ("The camera holds steady on her.", "static", None),
    ("The courier faces the camera.", "static", None),
    ("The shot is a medium shot. The courier runs. The camera tracks alongside the movement.",
     "tracking", None),
)
HOCKEY_E2 = ("The FuboTV hockey player carves a sharp stop, spraying ice mist into the air, his "
             "face toward the lens, then pushes off and skates away from the camera. The camera "
             "holds on him as he recedes. The camera stays static.")


def test_sft7_n20_detection(ws):
    for text, key, start in SFT7_ROWS:
        detail = se.camera_problem(lib, text, ["the courier"], key)
        if start is None:
            assert detail is None, text
        else:
            assert detail is not None and detail.startswith(start), (text, detail)
    ctx, plan, parts = _hockey(ws, story_id="sf7")
    parts[1]["motion"] = HOCKEY_E2
    text = se.assemble(ctx, plan, parts)
    path = os.path.join(ctx.story_dir, "check.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    hard, _advisory = se.panel_checks(ctx, plan, parts, text, path)
    assert ("panel 2: N20 camera direction: Motion: has 2 camera directions ('The camera holds on "
            "him as he recedes.'; 'The camera stays static.'); a panel has exactly one camera "
            "sentence; write one camera sentence in which the camera stays static") in hard


def test_review_focus_5_an_adverb_on_the_planned_move_is_one_valid_direction(ws):
    for camera, text in (("slow push-in", "The courier runs. The camera slowly pushes in on her."),
                         ("slow pan left",
                          "The courier runs. The camera gently pans left toward the harbour.")):
        ctx = seu.make_ctx(se, ws, mode="shots", panels=1)
        raw = seu.plan_json("shots", 1)
        raw["beats"][0]["camera"] = camera
        plan, _shape = se.normalize_plan(ctx, raw)
        assert se.camera_problem(lib, text, ["the courier"], camera) is None, text
        assert se.repair_action_text(ctx, plan, 1, text) == (text, []), text


# --- SFT8: the N20 and N7 repairs at parse time (SF11, SF13a, SK5, SK8) --------------------------

def test_sft8_the_parse_time_repairs(ws):
    ctx = seu.make_ctx(se, ws, mode="shots", panels=1)
    raw = seu.plan_json("shots", 1)
    raw["beats"][0]["camera"] = "slow push-in"
    plan, _shape = se.normalize_plan(ctx, raw)

    def note(check, name, removed):
        return se.REPAIR_NOTE % (1, check, name, "Motion", se._q(removed))

    rows = (
        ("The courier runs. The camera pans left.",
         ("The courier runs.", [note("N20", "camera direction", "The camera pans left.")])),
        ("The courier runs while the camera tracks him.",
         ("The courier runs.", [note("N20", "camera direction", "while the camera tracks him.")])),
        ("The courier runs. The camera pushes in. The camera holds.",
         ("The courier runs. The camera pushes in.",
          [note("N20", "camera direction", "The camera holds.")])),
        ("The courier turns toward the camera and speaks.",
         ("The courier turns toward the camera.",
          [note("N7", "dialogue and text", "and speaks.")])),
        ("The courier speaks softly. The courier waves.",
         ("The courier waves.", [note("N7", "dialogue and text", "The courier speaks softly.")])),
        ("The courier speaks.", ("The courier speaks.", [])),
        ("The camera pans left.", ("The camera pans left.", [])),
    )
    for text, want in rows:
        assert se.repair_action_text(ctx, plan, 1, text) == want, text
    reply = dict(seu.panel_json("shots", 1), motion="The courier runs. The camera pans left.")
    part = se.parse_panel_reply(ctx, plan, 1, json.dumps(reply))
    assert part["motion"] == "The courier runs."
    assert part["repairs"] == [note("N20", "camera direction", "The camera pans left.")]
    plain = se.parse_panel_reply(ctx, plan, 1, json.dumps(seu.panel_json("shots", 1)))
    assert "repairs" not in plain
    text = se.assemble(ctx, plan, [part])
    path = os.path.join(ctx.story_dir, "check.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    hard, advisory = se.panel_checks(ctx, plan, [part], text, path)
    assert note("N20", "camera direction", "The camera pans left.") in advisory
    assert [m for m in hard if " N20 " in m] == []


# --- SFT9: N7 is hard while generating, on the Motion or Prompt only (SF11, SK8) ----------------

def test_sft9_n7_severity(ws):
    ctx = seu.make_ctx(se, ws, mode="shots", panels=1)
    plan, _shape = se.normalize_plan(ctx, seu.plan_json("shots", 1))

    def n7(label, text, generating):
        hard, advisory = se._field_checks(ctx, lib, plan, 1, "T", [(label, text)], {label: text},
                                          se.GENERATION_CHECKS, (), generating=generating)
        return [m for m in hard if " N7 " in m], [m for m in advisory if " N7 " in m]

    assert n7("Motion", "The courier speaks.", True) == (
        ["panel 1: N7 dialogue and text: Motion: says 'speaks'; the pipeline adds the spoken line "
         "itself, so write only what the speaker physically does, with no speaking verb"], [])
    assert n7("Motion", "The courier speaks.", False) == (
        [], ["panel 1: N7 dialogue and text: Motion: says 'speaks'"])
    assert n7("Image", "The courier speaks.", True) == (
        [], ["panel 1: N7 dialogue and text: Image: says 'speaks'"])
    quoted = 'The courier holds up a sign reading "Closed".'
    for generating in (True, False):
        assert n7("Motion", quoted, generating) == (
            [], ["panel 1: N7 dialogue and text: Motion: contains a double quote"]), generating


# --- SFT10, Review Focus 4: N21 detection (SF10, SK7) ------------------------------------------

def N21_EXIT(label, sentence, words, speaker):
    return ("panel 1: N21 after the line: %s: '%s' has a character leave the frame or turn away "
            "('%s'); '%s' speaks in this panel, so end it with '%s' still in frame, face toward "
            "the camera" % (label, sentence, words, speaker, speaker))


def N21_ACTOR(label, sentence, actor, speaker):
    return ("panel 1: N21 after the line: %s: '%s' has '%s' act after the spoken line; after the "
            "line only '%s' reacts, and nobody else acts" % (label, sentence, actor, speaker))


def _n21_plan(ws, story_env, mode, speaker="c1"):
    """A 1-panel movie with kyra (c1) and ronin (c2); beat 1 cast both, speaker `speaker`."""
    ctx = seu.make_ctx(se, ws, mode=mode, panels=1, members=_members(story_env),
                       narration="speech")
    plan, _shape = se.normalize_plan(ctx, _raw(mode, 1, [["c1", "c2"]], [speaker]))
    return ctx, plan


def _n21(ctx, plan, writer):
    """(hard N21 messages, advisory N21 messages) of panel 1 with writer action text writer."""
    label = "Prompt" if ctx.mode == "no_stills" else "Motion"
    hard, advisory = se._field_checks(ctx, lib, plan, 1, "T", [(label, writer)], {label: writer},
                                      se.GENERATION_CHECKS, (), generating=True)
    return [m for m in hard if " N21 " in m], [m for m in advisory if " N21 " in m]


def test_sft10_n21_detection(ws, story_env):
    for mode in ("shots", "chained", "no_stills"):
        ctx, plan = _n21_plan(ws, story_env, mode)
        label = "Prompt" if mode == "no_stills" else "Motion"
        exits = (
            ("The woman in grey turns to the camera. The woman in grey skates away.",
             "The woman in grey skates away.", "skates away"),
            ("The woman in grey turns to the camera, then walks off.",
             "The woman in grey turns to the camera, then walks off.", "walks off"),
            ("The woman in grey turns. The camera holds on her as she recedes.",
             "The camera holds on her as she recedes.", "recedes"),
        )
        for writer, sentence, words in exits:
            assert _n21(ctx, plan, writer) == ([N21_EXIT(label, sentence, words, KYRA)], []), (
                mode, writer)
        actors = (
            ("The woman in grey turns. The ronin bows.", "The ronin bows.", "the ronin"),
            ("The woman in grey turns. The woman in grey nods as the ronin bows.",
             "The woman in grey nods as the ronin bows.", "the ronin"),
            ("The woman in grey turns. The crowd cheers.", "The crowd cheers.", "the crowd"),
        )
        for writer, sentence, actor in actors:
            want = [] if mode == "no_stills" else [N21_ACTOR(label, sentence, actor, KYRA)]
            assert _n21(ctx, plan, writer) == (want, []), (mode, writer)
        for writer in ("The woman in grey turns. The woman in grey glances back at the ronin.",
                       "The woman in grey turns. Her shoulders drop."):
            assert _n21(ctx, plan, writer) == ([], []), (mode, writer)
        three = "The woman in grey turns. The woman in grey nods. The woman in grey breathes."
        want = [] if mode == "no_stills" else [
            "panel 1: N21 after the line: %s: has 2 sentences after the first one, which the "
            "spoken line follows; after the line write at most one short sentence of how '%s' "
            "reacts" % (label, KYRA)]
        assert _n21(ctx, plan, three) == ([], want), mode
        ctx, silent = _n21_plan(ws, story_env, mode, speaker="")
        assert _n21(ctx, silent, exits[0][0]) == ([], []), mode
    ctx = seu.make_ctx(se, ws, mode="shots", panels=1, narration="speech")
    raw = seu.plan_json("shots", 1)
    raw["beats"][0]["speaker"] = "c1"
    plan, _shape = se.normalize_plan(ctx, raw)
    assert _n21(ctx, plan, "The courier turns. The old monk bows.") == (
        [N21_ACTOR("Motion", "The old monk bows.", "the old monk", "the courier")], [])


def test_review_focus_4_the_speakers_own_name_and_an_object_are_not_other_actors(ws, story_env):
    for mode in ("chained", "shots"):
        ctx, plan = _n21_plan(ws, story_env, mode)
        for writer in ("The woman in grey turns. Kyra nods.",
                       "The woman in grey turns. The woman in grey waves to the crowd.",
                       "The woman in grey turns. She glances at the ronin."):
            assert _n21(ctx, plan, writer) == ([], []), (mode, writer)


# --- SFT12: N22, the reference copy (SF12, SK9) ------------------------------------------------

def test_sft12_reference_copies(ws):
    narrative = seu.make_ctx(se, ws).narrative
    raw = seu.plan_json("shots", 1)
    assert se.reference_copies(narrative, raw, "The courier walks past the zinc counter.") == [
        "zinc"]
    hits = se.reference_copies(narrative, raw,
                               "The courier looks up from the empty ice trays to the camera")
    assert hits[0] == "ice trays"
    assert "looks up from the empty ice" in hits
    assert se.reference_copies(narrative, raw, "The courier runs at real-time speed.") == []
    market = "The courier locks the fish market."
    assert se.reference_copies(narrative, raw, market) == ["fish market"]
    assert se.reference_copies("A courier closes a fish market at dawn.", raw, market) == []
    ctx = seu.make_ctx(se, ws, mode="shots", panels=1)
    plan, _shape = se.normalize_plan(ctx, raw)
    part = se.parse_panel_reply(ctx, plan, 1, json.dumps(
        dict(seu.panel_json("shots", 1), motion=se.REFERENCE_COPY_SEGMENTS[4] + ".")))
    text = se.assemble(ctx, plan, [part])
    path = os.path.join(ctx.story_dir, "check.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    hard, _advisory = se.panel_checks(ctx, plan, [part], text, path)
    assert [m for m in hard if " N22 " in m] == [
        "panel 1: N22 reference copy: Motion: copies the format reference ('fishmonger', 'cloth "
        "drop onto the counter her', 'drop onto the counter her shoulders'); describe only this "
        "movie's own people, places, objects and words"]
    fixtures = os.path.join(WS, "tests", "fixtures")
    seen = 0
    for root, _dirs, names in os.walk(fixtures):
        for name in names:
            with open(os.path.join(root, name), encoding="utf-8") as f:
                words = se.line_words(f.read())
            seen += 1
            line = " " + " ".join(words) + " "
            assert not (se._six_grams(words) & se.REFERENCE_SIX_GRAMS), name
            assert [t for t in se.REFERENCE_TERMS
                    if " %s " % " ".join(se.line_words(t)) in line] == [], name
    assert seen >= 40
    for segment in se.REFERENCE_COPY_SEGMENTS[:-1]:
        assert segment in se.FORMAT_REFERENCE, segment
    assert ('"Forty years of mornings." After a breath, "Not one more."' in se.FORMAT_REFERENCE)
    assert se.line_words(se.REFERENCE_COPY_SEGMENTS[-1]) == se.line_words(
        "Forty years of mornings. Not one more.")


# --- SFT15: the S4/S5 parameters of generation (SF14, SF15c) -----------------------------------

def test_sft15_the_s4_and_s5_parameters(ws):
    two = "The courier lifts the letter at real-time speed. The courier nods. The camera pushes in."
    three = ("The courier lifts the letter. The courier nods. The courier sighs. The camera pushes "
             "in.")
    assert lib.motion_problems(two, ["the courier"], max_actions=2) == []
    assert lib.motion_problems(three, ["the courier"], max_actions=2) == [
        ("S5 one action", "Motion: has 3 action sentences; a speaking shot has one, or one and "
                          "the speaker's reaction, optionally followed by a camera sentence")]
    assert lib.motion_problems(two, ["the courier"]) == [
        ("S5 one action", "Motion: has 2 action sentences; it must have exactly one, optionally "
                          "followed by a camera sentence")]
    ctx = seu.make_ctx(se, ws, mode="shots", panels=1, narration="speech")
    raw = seu.plan_json("shots", 1)
    raw["beats"][0].update(speaker="c1", camera="slow push-in")
    plan, _shape = se.normalize_plan(ctx, raw)
    part = {"title": "The Letter", "image": seu.panel_json("shots", 1)["image"], "motion": two,
            "dialogue": "Go now."}
    text = se.assemble(ctx, plan, [part])
    path = os.path.join(ctx.story_dir, "check.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    _hard, advisory = se.panel_checks(ctx, plan, [part], text, path)
    assert [m for m in advisory if " S5 one action" in m] == []
    panels = se._story_manifest(ctx.ws)._parse_prompts_md(path)[1]
    assert [v for v in lib.shots_violations(text, panels, 1, [], True, ignore_facing=True)
            if " S5 one action" in v] == [
        "panel 1: S5 one action: Motion: has 2 action sentences; it must have exactly one, "
        "optionally followed by a camera sentence"]
    motion = " ".join(["word"] * 19) + " end."
    assert lib.shots_advisories([{"number": 1, "motion": motion, "image": ""}], [],
                                motion_words=(55, 105)) == [
        "panel 1: S4 motion length: Motion: is 20 words; aim for 55-105"]
    assert lib.shots_advisories([{"number": 1, "motion": motion, "image": ""}], []) == []


# --- SFT17: old stories re-check exactly as before (D12, SK10) ---------------------------------

def test_sft17_an_old_story_rechecks_as_before(ws, monkeypatch):
    monkeypatch.setattr(ltx_movie, "WS", ws)
    ctx, _plan, _parts = _hockey(ws, story_id="sf17")
    for name in ("plan.json", "story.md"):
        with open(os.path.join(HOCKEY_FIX, name), encoding="utf-8") as f:
            text = f.read()
        with open(os.path.join(ctx.story_dir, name), "w", encoding="utf-8") as f:
            f.write(text)
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        story = f.read()
    assert "as he speaks." in story and HOCKEY_E2 in story

    def refuse(*args, **kwargs):
        raise AssertionError("recheck must not repair, compare with the reference or cap cameras")

    for name in ("repair_action_text", "reference_copies", "cap_static_cameras"):
        monkeypatch.setattr(se, name, refuse)
    rc, advisories = se.recheck(ctx, ltx_movie._validate_story_md)
    assert rc == 0
    assert "panel 1: N7 dialogue and text: Motion: says 'speaks'" in advisories
    assert [a for a in advisories if " N20 " in a or " N21 " in a or " N22 " in a] == []
    checks = _read_json(ctx.story_dir, "story_checks.json")
    assert checks["hard"] == [] and checks["source"] == "recheck"


# --- SFT18: the exit verbs (SF10) --------------------------------------------------------------

def test_sft18_exit_verbs():
    for words in ("skates away", "walks off", "turns away", "steps off", "pulls away",
                  "leaves the frame", "exits", "disappears into", "out of frame", "out of the shot",
                  "into the distance", "recedes", "turns her back"):
        assert se.EXIT_RE.search("She %s now." % words), words
    for words in ("pushes off from the kerb", "turns off the light", "the leaves fall",
                  "the exit sign", "steps back", "turns toward the camera", "runs down the steel"):
        assert se.EXIT_RE.search("She %s now." % words) is None, words
```

- [ ] **Step 2: Run the tests to verify that they fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_shot_format.py 2>&1 | tail -1
```

Expected: `11 failed, 12 passed`. Every new test fails on a missing name or keyword: `REFERENCE_TERMS`, `camera_problem`, `repair_action_text`, `generating`, `reference_copies`, `max_actions` and `EXIT_RE`. SFT17's `monkeypatch.setattr` raises on the missing attributes.

- [ ] **Step 3: Implement SF9-SF12, SF13a, SF13c, SF14 and SF15c.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    return any(lib._is_camera_sentence(s, phrases) and CAMERA_MOTION_RE.search(s)
               for s in _sentences(text))


def panel_camera(ctx, plan, k):
```

with:

```python
    return any(lib._is_camera_sentence(s, phrases) and CAMERA_MOTION_RE.search(s)
               for s in _sentences(text))


# Shot prompt format spec SF9, D5: a panel has exactly one camera direction, a camera sentence
# that names its camera.
STATIC_CAMERA_WORDS = ("static", "still", "locked-off")
CAMERA_MOVE_WORDS = {
    "slow push-in": ("push in", "pushes in", "push-in", "dolly", "dollies", "zoom", "zooms"),
    "slow pull-back": ("pull back", "pulls back", "pull-back", "dolly", "dollies", "zoom",
                       "zooms"),
    "tracking": ("track", "tracks", "tracking", "follow", "follows", "dolly", "dollies"),
    "handheld": ("handheld",),
    "slow pan left": ("pan", "pans"),
    "slow pan right": ("pan", "pans"),
    "slow tilt up": ("tilt", "tilts"),
    "slow tilt down": ("tilt", "tilts"),
    "static": ("static", "still", "hold", "holds", "locked-off"),
}
CAMERA_CLAUSE_RE = re.compile(
    r"\bcamera\s+(?:[a-z]+ly\s+)?(?:stays|remains|is|holds?|moves?|push(?:es)?|pulls?|pans?|"
    r"tilts?|tracks?|follows?|zooms?|dollies|orbits?|cranes?|circles?|swings?|glides?|drifts?|"
    r"sweeps?|rises?|lowers?)\b", re.IGNORECASE)
_CUT_RE = re.compile(r"\s*[,;:—–]\s*(?:(?:and|then|while|as|before|after|until|so)\s+)?|\s+-\s+"
                     r"|\s+(?:and|then|while|as|before|after|until|so)\s+", re.IGNORECASE)
REPAIR_NOTE = "panel %d: %s %s: %s: the pipeline removed %s"


def _camera_words(sentence):
    """The CAMERA_MOTION_RE words of a sentence, lower case, whitespace collapsed, in order."""
    return [" ".join(m.group(0).lower().split()) for m in CAMERA_MOTION_RE.finditer(sentence)]


def camera_directions(lib, text, phrases):
    """[(index, kind)] of the camera directions among _sentences(text) (SF9): "sentence" for a
    camera sentence (lib._is_camera_sentence with phrases) that has a CAMERA_MOTION_RE word,
    "clause" for any other sentence with a CAMERA_CLAUSE_RE match."""
    out = []
    for i, sentence in enumerate(_sentences(text)):
        if lib._is_camera_sentence(sentence, phrases):
            if _camera_words(sentence):
                out.append((i, "sentence"))
        elif CAMERA_CLAUSE_RE.search(sentence):
            out.append((i, "clause"))
    return out


def _mixed_camera(sentence):
    """True when a camera sentence both keeps the camera still and moves it."""
    words = _camera_words(sentence)
    return (any(w in STATIC_CAMERA_WORDS for w in words)
            and any(w not in CAMERA_MOVE_WORDS["static"] for w in words))


def _names_camera(sentence, key):
    return any(w in CAMERA_MOVE_WORDS[key] for w in _camera_words(sentence))


def camera_problem(lib, text, phrases, key):
    """The N20 detail of an assembled action field, or None (SF9). key is the panel's camera
    (panel_camera); a key not in CAMERA_MOVE_WORDS (None, "") skips the planned-move test."""
    sentences = _sentences(text)
    found = camera_directions(lib, text, phrases)
    hint = ("; write one camera sentence in which the camera %s" % CAMERA_WRITER_FORMS[key][0]
            if key in CAMERA_WRITER_FORMS else "")
    if len(found) > 1:
        return ("has %d camera directions (%s); a panel has exactly one camera sentence%s"
                % (len(found), "; ".join(_q(sentences[i]) for i, _kind in found), hint))
    if not found:
        return None
    i, kind = found[0]
    if kind == "clause":
        return ("puts the camera direction inside the action sentence %s; write it as its own "
                "sentence that begins with 'The camera'%s" % (_q(sentences[i]), hint))
    if _mixed_camera(sentences[i]):
        return "the camera sentence %s has the camera both stay still and move%s" % (
            _q(sentences[i]), hint)
    if key in CAMERA_MOVE_WORDS and not _names_camera(sentences[i], key):
        return "the camera sentence %s does not move the camera the planned way%s" % (
            _q(sentences[i]), hint)
    return None


def _cut_clause(sentence, at):
    """(head, tail) of a sentence cut at the last clause boundary (_CUT_RE) that ends at or
    before index at: head is the text before the boundary with a full stop, tail the text from
    the boundary on without its leading punctuation; None when no boundary ends at or before at,
    or when head would have fewer than 3 words."""
    start = None
    for match in _CUT_RE.finditer(sentence, 0, at + 1):
        if match.end() <= at:
            start = match.start()
    if start is None:
        return None
    head = sentence[:start].rstrip(" ,;:—–-")
    if len(head.split()) < 3:
        return None
    return head + ".", sentence[start:].strip(" ,;:—–-")


# Shot prompt format spec SF10, D7: a speaker never leaves, and nobody else acts after the line.
EXIT_RE = re.compile(
    r"\b(?:(?:walk|walks|walking|skate|skates|skating|run|runs|running|ride|rides|riding|drive|"
    r"drives|driving|glide|glides|gliding|stride|strides|striding|head|heads|heading|hurry|"
    r"hurries|hurrying|wander|wanders|wandering|march|marches|marching|drift|drifts|drifting|"
    r"fly|flies|flying|swim|swims|swimming|limp|limps|limping|move|moves|moving|step|steps|"
    r"stepping|back|backs|backing)\s+(?:away|off)|(?:turn|turns|turning|pull|pulls|pulling)\s+"
    r"away|leav(?:e|es|ing)\s+(?:the\s+)?(?:frame|shot|scene|room|rink|ice)|exit(?:s|ing)|"
    r"depart(?:s|ing)|disappear(?:s|ing)?\s+(?:from|into|behind|through)|retreat(?:s|ing)|"
    r"reced(?:es|ing)|out\s+of\s+(?:the\s+)?(?:frame|shot|view|sight)|into\s+the\s+distance|"
    r"turn(?:s|ing)?\s+(?:her|his|their)\s+back)\b", re.IGNORECASE)


def post_line_sentences(lib, text, phrases):
    """The action sentences of a speaking panel's writer action text that compose_motion puts
    after the spoken line (SF10): every action sentence (not a camera sentence, not a pasted
    facing sentence) after the first."""
    return [s for s in _sentences(text) if not lib._is_camera_sentence(s, phrases)
            and not lib.is_facing_sentence(s, phrases)][1:]


def _other_actor(sentence, others, own):
    """The words of the first other-character clause subject of a sentence, or None (SF10): a
    mention in others ([(cast id, words)], as _mentions), or a GROUP_NOUNS word with at most one
    article, that starts a _CLAUSE_BREAK_RE piece or follows a CLAUSE_STOP_WORDS word, and is
    not where a mention in own (the speaker's) starts."""
    for piece in _CLAUSE_BREAK_RE.split(sentence):
        words = line_words(piece)
        for p in range(len(words)):
            if (p and words[p - 1] not in CLAUSE_STOP_WORDS) or _mentions_at(words, own, start=p):
                continue
            hits = _mentions_at(words, others, start=p)
            if hits:
                return " ".join(words[p:p + max(hits.values())])
            q = p + 1 if words[p] in ("the", "a", "an") else p
            if q < len(words) and words[q] in GROUP_NOUNS:
                return " ".join(words[p:q + 1])
    return None


def _apply_drops(lib, sentences, drop, phrases):
    """(kept sentences, dropped sentences): the indices in drop are removed when at least one
    action sentence (not a camera sentence, not a facing sentence) remains; otherwise only the
    camera sentences among them are removed (SF11)."""
    def action(s):
        return not lib._is_camera_sentence(s, phrases) and not lib.is_facing_sentence(s, phrases)
    drop = set(drop)
    if not any(action(s) for i, s in enumerate(sentences) if i not in drop):
        drop = set(i for i in drop if not action(sentences[i]))
    return ([s for i, s in enumerate(sentences) if i not in drop],
            [s for i, s in enumerate(sentences) if i in drop])


def repair_action_text(ctx, plan, k, text):
    """(text, notes): panel k's writer Motion or Prompt after the SF11 speaking-verb cut and the
    SF9 camera repair, with one REPAIR_NOTE advisory per removed piece. When the result would be
    empty the text is returned unchanged with no notes."""
    lib = _character_lib(ctx.ws)
    phrases = cast_phrases(ctx, plan)
    label = "Prompt" if ctx.mode == "no_stills" else "Motion"
    sentences, notes, drop = [], [], []
    for sentence in _sentences(text):
        found = DIALOGUE_RE.search(sentence)
        cut = _cut_clause(sentence, found.start()) if found else None
        if cut:
            sentences.append(cut[0])
            notes.append(REPAIR_NOTE % (k, "N7", "dialogue and text", label, _q(cut[1])))
        else:
            if found:
                drop.append(len(sentences))
            sentences.append(sentence)
    sentences, dropped = _apply_drops(lib, sentences, drop, phrases)
    notes += [REPAIR_NOTE % (k, "N7", "dialogue and text", label, _q(s)) for s in dropped]
    key = panel_camera(ctx, plan, k)
    found = camera_directions(lib, " ".join(sentences), phrases)
    valid = [i for i, kind in found if kind == "sentence" and not _mixed_camera(sentences[i])
             and (key not in CAMERA_MOVE_WORDS or _names_camera(sentences[i], key))]
    if found and not (len(found) == 1 and valid):
        keep, kinds, out = (valid[0] if valid else None), dict(found), []
        for i, sentence in enumerate(sentences):
            kind = kinds.get(i)
            if kind is None or i == keep:
                out.append(sentence)
            elif kind == "sentence":
                notes.append(REPAIR_NOTE % (k, "N20", "camera direction", label, _q(sentence)))
            else:
                start = CAMERA_CLAUSE_RE.search(sentence).start()
                if sentence[:start].lower().endswith("the "):
                    start -= 4
                cut = _cut_clause(sentence, start)
                out.append(cut[0] if cut else sentence)
                if cut:
                    notes.append(REPAIR_NOTE % (k, "N20", "camera direction", label, _q(cut[1])))
        sentences = out
    repaired = " ".join(sentences)
    return (repaired, notes) if repaired else (text, [])


def panel_camera(ctx, plan, k):
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "natural ambient sound of the place, with no music.\n\n")
_LABEL_RE = re.compile(r"^(?:title|image|motion|prompt|narration|dialogue)\s*:\s*",
```

with:

```python
    "natural ambient sound of the place, with no music.\n\n")
# Shot prompt format spec SF12, D11: the reference's own names, props and wording.
REFERENCE_TERMS = ("fishmonger", "fishmongers", "herring", "herrings", "zinc", "ice trays",
                   "market hall", "fish market", "harbour doors", "meltwater",
                   "forty years of mornings")
REFERENCE_COPY_SEGMENTS = (
    "The old fishmonger drags a tall stack of empty herring crates across the wet concrete of "
    "the market hall toward the half-open shutter",
    "her heavy steps splashing through shallow puddles that hold the first glow from the "
    "harbour doors",
    "she reaches the shutter at frame centre, the long rows of bare zinc counters stretching "
    "away behind her",
    "The old fishmonger looks up from the empty ice trays to the camera, drying her knuckles on "
    "a folded cloth at the zinc counter",
    "The old fishmonger lets the folded cloth drop onto the counter, her shoulders sinking",
    "her face fills the frame from chin to brow, the bare counters soft behind her",
    "The old fishmonger presses her forehead against the cold ribs of the half-closed steel "
    "shutter",
    "both palms flat on the metal, her breath fogging the ribbed steel as a thin trickle of "
    "meltwater runs past her knuckles and drips onto the wet concrete at her feet",
    "holding her face, her knuckles and the ribbed steel tight in the frame as her eyelids drop "
    "shut and the shutter stops trembling",
    "Forty years of mornings. Not one more.",
)


def _six_grams(words):
    return set(tuple(words[i:i + 6]) for i in range(len(words) - 5))


REFERENCE_SIX_GRAMS = frozenset(g for s in REFERENCE_COPY_SEGMENTS for g in _six_grams(line_words(s)))


def reference_copies(narrative, plan, text, goal=None):
    """The REFERENCE_TERMS terms and the six-word REFERENCE_COPY_SEGMENTS runs that text copies
    from FORMAT_REFERENCE, in that order (SF12), leaving out any that the narrative, the goal or
    the plan (cast phrases and descriptors, settings, prop names, beat actions) already has."""
    own = [narrative or "", goal or ""]
    if plan:
        own += ([c.get("phrase") or "" for c in plan["cast"]]
                + [c.get("descriptor") or "" for c in plan["cast"]]
                + [l.get("setting") or "" for l in plan["locations"]]
                + [p.get("name") or "" for p in plan["props"]]
                + [b.get("action") or "" for b in plan["beats"]])
    own_words = [line_words(t) for t in own]
    own_line = " " + " | ".join(" ".join(w) for w in own_words) + " "
    own_grams = set(g for w in own_words for g in _six_grams(w))
    words = line_words(text or "")
    line = " " + " ".join(words) + " "
    hits = [t for t in REFERENCE_TERMS
            if (" %s " % " ".join(line_words(t))) in line
            and (" %s " % " ".join(line_words(t))) not in own_line]
    return hits + [" ".join(g) for g in sorted((_six_grams(words) & REFERENCE_SIX_GRAMS)
                                               - own_grams)]
_LABEL_RE = re.compile(r"^(?:title|image|motion|prompt|narration|dialogue)\s*:\s*",
```

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def _field_checks(ctx, lib, plan, k, title, fields, writers, ids, undeclared):
    """(hard, advisory) of one panel: the RS15 checks named in ids, plus N15 when in ids. Hard:
    N11 (Narration: empty with no Dialogue:), N18, T1, T2, T3; every other N rule is advisory
    (dialogue spec 6.3, D6).
```

with:

```python
def _field_checks(ctx, lib, plan, k, title, fields, writers, ids, undeclared, generating=False):
    """(hard, advisory) of one panel: the RS15 checks named in ids, plus N15 when in ids. Hard:
    N11 (Narration: empty with no Dialogue:), N18, T1, T2, T3, and with generating (shot prompt
    format spec SF11-SF12) N7 on the Motion or Prompt, N20, N21 (exits and other actors) and
    N22; every other N rule is advisory (dialogue spec 6.3, D6).
```

**3.4.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
            if "N7" in ids:
                if any(q in writer for q in ('"', "“", "”")):
                    add(advisory, "N7", "dialogue and text", label, "contains a double quote")
                else:
                    word = _first(DIALOGUE_RE, writer) or _first(ONSCREEN_TEXT_RE, writer)
                    if word:
                        add(advisory, "N7", "dialogue and text", label, "says %s" % _q(word))
```

with:

```python
            if "N7" in ids:
                speech = _first(DIALOGUE_RE, writer)
                if (generating and speech
                        and label == ("Prompt" if ctx.mode == "no_stills" else "Motion")):
                    add(hard, "N7", "dialogue and text", label,
                        "says %s; the pipeline adds the spoken line itself, so write only what "
                        "the speaker physically does, with no speaking verb" % _q(speech))
                elif any(q in writer for q in ('"', "“", "”")):
                    add(advisory, "N7", "dialogue and text", label, "contains a double quote")
                else:
                    word = speech or _first(ONSCREEN_TEXT_RE, writer)
                    if word:
                        add(advisory, "N7", "dialogue and text", label, "says %s" % _q(word))
```

**3.5.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
                    % (_words(narration), lo, hi))
    return hard, advisory


def _repeat_words(lib, text, phrase_words):
```

with:

```python
                    % (_words(narration), lo, hi))
    # Shot prompt format spec SF9-SF12: the writer-format checks (generation only, D12).
    if plan and beat is not None and action_label in dict(fields):
        if "N20" in ids:
            detail = camera_problem(lib, dict(fields)[action_label], known,
                                    panel_camera(ctx, plan, k))
            if detail:
                hard.append("%s N20 camera direction: %s: %s" % (prefix, action_label, detail))
        if "N21" in ids and panel_speaks(ctx, plan, k):
            writer = writers.get(action_label, "")
            speaker = speaker_phrase(plan, k)
            for sentence in _sentences(writer):
                found = EXIT_RE.search(sentence)
                if found:
                    hard.append("%s N21 after the line: %s: %s has a character leave the frame or "
                                "turn away (%s); %s speaks in this panel, so end it with %s still "
                                "in frame, face toward the camera"
                                % (prefix, action_label, _q(sentence),
                                   _q(" ".join(found.group(0).lower().split())), _q(speaker),
                                   _q(speaker)))
                    break
            if ctx.mode != "no_stills":
                post = post_line_sentences(lib, writer, known)
                mentions = _mentions(plan["cast"])
                others = [m for m in mentions if m[0] != beat["speaker"]]
                own = [m for m in mentions if m[0] == beat["speaker"]]
                for sentence in post:
                    actor = _other_actor(sentence, others, own)
                    if actor:
                        hard.append("%s N21 after the line: %s: %s has %s act after the spoken "
                                    "line; after the line only %s reacts, and nobody else acts"
                                    % (prefix, action_label, _q(sentence), _q(actor),
                                       _q(speaker)))
                        break
                if len(post) > 1:
                    advisory.append("%s N21 after the line: %s: has %d sentences after the first "
                                    "one, which the spoken line follows; after the line write at "
                                    "most one short sentence of how %s reacts"
                                    % (prefix, action_label, len(post), _q(speaker)))
        if "N22" in ids:
            for label, text in writers.items():
                hits = reference_copies(ctx.narrative, plan, text, ctx.goal)
                if hits:
                    hard.append("%s N22 reference copy: %s: copies the format reference (%s); "
                                "describe only this movie's own people, places, objects and "
                                "words" % (prefix, label, ", ".join(_q(h) for h in hits[:3])))
    return hard, advisory


def _repeat_words(lib, text, phrase_words):
```

**3.6.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
GENERATION_CHECKS = ("N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11", "N12",
                     "N14", "N15", "N16", "N17", "N18", "T1", "T2", "T3", "Q1", "N19")
```

with:

```python
GENERATION_CHECKS = ("N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11", "N12",
                     "N14", "N15", "N16", "N17", "N18", "T1", "T2", "T3", "N20", "N21", "N22",
                     "Q1", "N19")
```

**3.7.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        h, a = _field_checks(ctx, lib, plan, k, parts[k - 1]["title"], fields, writers,
                             GENERATION_CHECKS, undeclared)
        hard += h
```

with:

```python
        h, a = _field_checks(ctx, lib, plan, k, parts[k - 1]["title"], fields, writers,
                             GENERATION_CHECKS, undeclared, generating=True)
        a = a + parts[k - 1].get("repairs", [])
        hard += h
```

**3.8.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        shots_hard, shots_other = split_shots(lib.shots_violations(
            text, panels, ctx.panels, ctx.members, ctx.narration is True, ignore_facing=True))
        hard += shots_hard
        advisory += shots_other + lib.shots_advisories(panels, ctx.members)
```

with:

```python
        shots_hard, shots_other = split_shots(lib.shots_violations(
            text, panels, ctx.panels, ctx.members, ctx.narration is True, ignore_facing=True,
            speaking_actions=2))
        hard += shots_hard
        advisory += shots_other + lib.shots_advisories(
            panels, ctx.members, motion_words=WORD_RANGES["shots"]["motion"])
```

**3.9.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    return dict({"title": title}, **parts)
```

with:

```python
    action = "prompt" if ctx.mode == "no_stills" else "motion"
    parts[action], repairs = repair_action_text(ctx, plan, k, parts[action])
    out = dict({"title": title}, **parts)
    if repairs:
        out["repairs"] = repairs
    return out
```

**3.10.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
def motion_problems(motion, phrases=()):
    """[(rule, detail)] for one shots-mode Motion: text (spec 4.3 S5; S4 is advisory,
    motion_length_advisory). A camera sentence
    (_is_camera_sentence, with phrases) is not an action sentence."""
    problems = []
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(motion.strip()) if s.strip()]
    actions = [s for s in sentences if not _is_camera_sentence(s, phrases)]
    if len(actions) != 1:
        problems.append(("S5 one action", "Motion: has %d action sentences; it must have exactly "
                         "one, optionally followed by a camera sentence" % len(actions)))
```

with:

```python
def motion_problems(motion, phrases=(), max_actions=1):
    """[(rule, detail)] for one shots-mode Motion: text (spec 4.3 S5; S4 is advisory,
    motion_length_advisory). A camera sentence
    (_is_camera_sentence, with phrases) is not an action sentence."""
    problems = []
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(motion.strip()) if s.strip()]
    actions = [s for s in sentences if not _is_camera_sentence(s, phrases)]
    if not 1 <= len(actions) <= max_actions:
        if max_actions == 1:
            problems.append(("S5 one action", "Motion: has %d action sentences; it must have "
                             "exactly one, optionally followed by a camera sentence"
                             % len(actions)))
        else:
            problems.append(("S5 one action", "Motion: has %d action sentences; a speaking shot "
                             "has one, or one and the speaker's reaction, optionally followed by "
                             "a camera sentence" % len(actions)))
```

**3.11.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
def shots_violations(text, panels, expected_panels, members, narration=True, ignore_facing=False):
```

with:

```python
def shots_violations(text, panels, expected_panels, members, narration=True, ignore_facing=False,
                     speaking_actions=1):
```

**3.12.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
                    for rule, detail in motion_problems(
                        _drop_facing(p["motion"], humans + animals) if ignore_facing
                        else p["motion"], humans + animals)]
```

with:

```python
                    for rule, detail in motion_problems(
                        _drop_facing(p["motion"], humans + animals) if ignore_facing
                        else p["motion"], humans + animals,
                        max_actions=speaking_actions if p.get("dialogue", "").strip() else 1)]
```

**3.13.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
def motion_length_advisory(motion):
    """The S4 detail when a shots-mode Motion: is more than SHOTS_MOTION_WORD_TOLERANCE outside
    its word range, else None (word counts are advisory)."""
    words = len(motion.split())
    lo, hi = SHOTS_MOTION_MIN_WORDS, SHOTS_MOTION_MAX_WORDS
```

with:

```python
def motion_length_advisory(motion, lo=SHOTS_MOTION_MIN_WORDS, hi=SHOTS_MOTION_MAX_WORDS):
    """The S4 detail when a shots-mode Motion: is more than SHOTS_MOTION_WORD_TOLERANCE outside
    its word range, else None (word counts are advisory)."""
    words = len(motion.split())
```

**3.14.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
def shots_advisories(panels, members):
    """Non-fatal shots-mode warnings (shots spec 4.4; its W1 is the fatal S9 since shots rules v2),
    per panel in order: S4 when Motion: is well outside its word range, then W2 when the shot
    names a cast character but its Image: states no shot type, or a wide one (W2 only with
    members)."""
    out = []
    for p in panels:
        length = motion_length_advisory(p["motion"]) if p["motion"].strip() else None
```

with:

```python
def shots_advisories(panels, members, motion_words=None):
    """Non-fatal shots-mode warnings (shots spec 4.4; its W1 is the fatal S9 since shots rules v2),
    per panel in order: S4 when Motion: is well outside its word range, then W2 when the shot
    names a cast character but its Image: states no shot type, or a wide one (W2 only with
    members)."""
    out = []
    for p in panels:
        length = ((motion_length_advisory(p["motion"], *motion_words) if motion_words
                   else motion_length_advisory(p["motion"])) if p["motion"].strip() else None)
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_shot_format.py 2>&1 | tail -1
```

Expected: `23 passed`. Run the compile check with `FILES` = `story_engine.py character_lib.py tests/test_shot_format.py`; expected: `compiled 3` twice. Then run the gate block of Task 1 Step 4 with `task-3-pytest.txt` and task number `3`. Expected: `GATE PASS`, `test_shot_format 23, not passing 0`, `baseline failures still failing 2 of 2` and `OK 347/347`.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py character_lib.py tests/test_shot_format.py
git diff --cached --name-only    # expected: qwen-agent-workspace/character_lib.py, qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_shot_format.py
git commit -m "feat(story): hard writer-format checks N7, N20, N21 and N22, with parse-time cuts and camera repair (SF9-SF12, SF13a, SF13c, SF14, SF15c; SFT1c, SFT7-SFT10, SFT12, SFT15, SFT17, SFT18)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The repair plumbing: re-ask, trim, critic and patches (SF13b, SF13d-h)

This task implements:
- SF13b, `FORMAT_IDS`, `format_problems` and `trim_format`;
- SF13d, the round-0 re-ask and trim in `_Run.go`;
- SF13e, `REPAIR_IDS`;
- SF13f, `merge_repair`;
- SF13g, the `apply_patches` need set and its non-dialogue branch. Plan ruling PR1 applies here too: `cleanup_pieces` replaces the `pasted_pieces(...).get(field, ())` argument of its `clean_writer` call.
- SF13h, the critic field lines and `CRITIC_SPEAKING_MOTION_CLAUSE`.

Tests: SFT1 (repair part), SFT11, SFT16, SFT19, SFT20, and Review Focus 1, 2 and 3.

**Files:**
- Modify: `story_engine.py`. The edits go before `panel_checks` (after Task 3's `GENERATION_CHECKS`), in `critic_field_lines` (`:2953-2956`, `:2961-2964`), to `CRITIC_SPEAKING_MOTION_CLAUSE` (`:2925-2929`), in `apply_patches` (`:3280`, `:3296-3305`), to `REPAIR_IDS` (`:3329-3331`), in `merge_repair` (`:3386-3398`) and in `_Run.go` (`:3784-3786`).
- Modify: `tests/test_shot_format.py` (append).

**Interfaces:**
- Consumes: Task 3's `_field_checks(..., generating=True)`, `repair_action_text`, `reference_copies`, `EXIT_RE`, `_cut_clause`, `_other_actor`, `_apply_drops` and `REPAIR_NOTE`; Task 2's `cleanup_pieces`; the existing `_Run.panel_call(plan, parts, k, rnd, fix)`, `panel_keys`, `LABELS`, `guard_problem`, `line_problem` and `parse_violation`.
- Produces:
  - In `story_engine`:
    - `FORMAT_IDS = ("N7", "N20", "N21", "N22")`;
    - `format_problems(ctx, plan, part, k) -> [str]` (hard messages);
    - `trim_format(ctx, plan, k, part) -> part`, which returns a new dict whenever it trims and adds `"repairs"`;
    - `REPAIR_IDS` with the four new ids;
    - `merge_repair` and `apply_patches` accept the new ids.
  - In the test module: `FORMAT_IDS`, `REPAIR_IDS`, `CRITIC_SPEAKING_MOTION_CLAUSE`, `MOTION_LINE`, `DIALOGUE_LINE`, `SFT11_EXIT`, `SFT11_CLEAN`, `_sft11_reply(motion)`, `_sft11_run(ws, tmp_path, monkeypatch, story_env, story_id, panel_1) -> (rc, ctx, log)`, `_motion_lines(ctx)`, `_messages(ctx, key)`, `_patch(...)`, `_speaking_state(ws, motion) -> (ctx, state)` and `SFT16_EXIT`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_sft1d_repair_constants`, `test_sft11_the_round_0_re_ask_then_the_trim`, `test_review_focus_2_an_unparseable_re_ask_keeps_the_first_reply_and_trims`, `test_sft16_the_critic_lines_the_patches_and_merge_repair`, `test_review_focus_1_a_critic_patch_keeps_an_end_framed_camera_sentence_whole`, `test_sft19_the_trim_keeps_the_only_action`, `test_sft20_the_chained_hockey_shape` and `test_review_focus_3_an_end_frame_in_the_references_words_falls_back`.

Edit `tests/test_shot_format.py` (append): replace this text, the file's last lines, which occurs exactly once:

```python
    for words in ("pushes off from the kerb", "turns off the light", "the leaves fall",
                  "the exit sign", "steps back", "turns toward the camera", "runs down the steel"):
        assert se.EXIT_RE.search("She %s now." % words) is None, words
```

with:

```python
    for words in ("pushes off from the kerb", "turns off the light", "the leaves fall",
                  "the exit sign", "steps back", "turns toward the camera", "runs down the steel"):
        assert se.EXIT_RE.search("She %s now." % words) is None, words


# --- SFT1 (Task 4 part): the repair constants (SF13) -------------------------------------------

FORMAT_IDS = ("N7", "N20", "N21", "N22")
REPAIR_IDS = ("N7", "N11", "N18", "N20", "N21", "N22", "T1", "T2", "T3")
CRITIC_SPEAKING_MOTION_CLAUSE = (
    " On a panel with a Dialogue: line, the pipeline inserts the spoken words right after the "
    "first sentence about what the speaker does, so keep everything the speaker does before "
    "the line in that first sentence and at most one short sentence of the speaker's reaction "
    "after it, in which nobody else acts and the speaker never leaves the frame. Begin each of "
    "those sentences with the speaker's referring phrase.")
MOTION_LINE = ('- target "panel", field "%s", index = the panel number, only for a panel with '
               "a [hard] T2, T3, N7, N20, N21 or N22 problem: replacement is the panel's whole new "
               "%s: writer text, identical to the current text except for the sentence or "
               "sentences that cause the problem.")
DIALOGUE_LINE = ('- target "panel", field "dialogue", index = the panel number, only for a panel '
                 "with a [hard] T1, N18 or N22 problem: replacement is the new spoken line, "
                 "without the speaker's phrase and without quotation marks, within the limit a T1 "
                 "problem states.")


def test_sft1d_repair_constants():
    assert se.FORMAT_IDS == FORMAT_IDS
    assert se.REPAIR_IDS == REPAIR_IDS
    assert se.CRITIC_SPEAKING_MOTION_CLAUSE == CRITIC_SPEAKING_MOTION_CLAUSE
    assert "slowly" not in se.CRITIC_SPEAKING_MOTION_CLAUSE.lower()


# --- SFT11, Review Focus 2: the round-0 re-ask, then the trim (SF13d, SK7) ----------------------

SFT11_EXIT = "The woman in grey turns to the camera. The woman in grey walks away."
SFT11_CLEAN = "The woman in grey turns to the camera at real-time speed."


def _sft11_reply(motion):
    return seu.answer({"title": "At The Gate", "image": seu.panel_json("shots", 1, KYRA)["image"],
                       "motion": motion, "dialogue": "We go now."})


def _sft11_run(ws, tmp_path, monkeypatch, story_env, story_id, panel_1):
    """(rc, ctx, agent log) of a shots run: 2 panels, kyra and ronin pinned, --speech-only; beat
    1 casts kyra, who speaks; beat 2 casts the ronin, silent; panel 1 gets the replies panel_1."""
    raw = _raw("shots", 2, [["c1"], ["c2"]], ["c1", ""])
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(raw)],
                           panel={"1": panel_1,
                                  "2": [seu.answer(seu.panel_json("shots", 2, RONIN))]})
    ctx = seu.make_ctx(se, ws, mode="shots", panels=2, members=_members(story_env),
                       narration="speech", story_id=story_id)
    rc, _advisories = se.run(ctx)
    return rc, ctx, seu.agent_log(log)


def _motion_lines(ctx):
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        return [line for line in f.read().splitlines() if line.startswith("Motion: ")]


def _messages(ctx, key):
    return [entry["message"] for entry in _read_json(ctx.story_dir, "story_checks.json")[key]]


def test_sft11_the_round_0_re_ask_then_the_trim(ws, tmp_path, monkeypatch, story_env):
    removed = se.REPAIR_NOTE % (1, "N21", "after the line", "Motion",
                                "'The woman in grey walks away.'")
    rc, ctx, log = _sft11_run(ws, tmp_path, monkeypatch, story_env, "sf11a",
                              [_sft11_reply(SFT11_EXIT), _sft11_reply(SFT11_CLEAN)])
    assert rc == 0
    assert [r["stage"] for r in log] == ["plan", "panel", "panel", "panel"]
    with open(os.path.join(ctx.story_dir, "story_rounds", "round_0", "panel_01_prompt_2.txt"),
              encoding="utf-8") as f:
        assert ("Your previous version of this panel was rejected. Problems:\n- panel 1: N21 after "
                "the line: Motion: ") in f.read()
    assert _motion_lines(ctx)[0].startswith("Motion: " + SFT11_CLEAN)
    assert [m for m in _messages(ctx, "advisory") if "the pipeline removed" in m] == []
    rc, ctx, log = _sft11_run(ws, tmp_path, monkeypatch, story_env, "sf11b",
                              [_sft11_reply(SFT11_EXIT), _sft11_reply(SFT11_EXIT)])
    assert rc == 0
    assert [r["stage"] for r in log] == ["plan", "panel", "panel", "panel"]
    assert "walks away" not in _motion_lines(ctx)[0]
    assert _motion_lines(ctx)[0].startswith("Motion: The woman in grey turns to the camera. ")
    assert removed in _messages(ctx, "advisory")
    rc, ctx, log = _sft11_run(ws, tmp_path, monkeypatch, story_env, "sf11c",
                              [_sft11_reply("The woman in grey skates away.")] * 2)
    assert rc == 2
    assert [r["stage"] for r in log][:4] == ["plan", "panel", "panel", "panel"]
    assert _messages(ctx, "hard") == [N21_EXIT("Motion", "The woman in grey skates away.",
                                               "skates away", KYRA)]


def test_review_focus_2_an_unparseable_re_ask_keeps_the_first_reply_and_trims(
        ws, tmp_path, monkeypatch, story_env):
    rc, ctx, log = _sft11_run(ws, tmp_path, monkeypatch, story_env, "sfrf2",
                              [_sft11_reply(SFT11_EXIT), {"answer": "not json"}])
    assert rc == 0
    assert [r["stage"] for r in log] == ["plan", "panel", "panel", "panel"]
    assert _motion_lines(ctx)[0] == ("Motion: The woman in grey turns to the camera. The woman in "
                                     "grey faces the camera. The camera stays static.")
    assert se.REPAIR_NOTE % (1, "N21", "after the line", "Motion",
                             "'The woman in grey walks away.'") in _messages(ctx, "advisory")


# --- SFT16, Review Focus 1: the critic, the patches and merge_repair (SF13e-h) -----------------

def _patch(target, index, field, replacement, reason="because"):
    return {"target": target, "index": index, "field": field, "reason": reason,
            "replacement": replacement}


def _speaking_state(ws, motion):
    """(ctx, state) of a 1-panel shots movie, --speech-only: the courier speaks, the camera is
    a slow push-in, and the writer's Motion is motion."""
    ctx = seu.make_ctx(se, ws, mode="shots", panels=1, narration="speech")
    raw = seu.plan_json("shots", 1)
    raw["beats"][0].update(speaker="c1", camera="slow push-in")
    plan, _shape = se.normalize_plan(ctx, raw)
    part = {"title": "The Gate", "image": seu.panel_json("shots", 1)["image"], "motion": motion,
            "dialogue": "Go now."}
    return ctx, {"plan": plan, "parts": [part]}


SFT16_EXIT = "The courier turns to the camera. The courier walks away."


def test_sft16_the_critic_lines_the_patches_and_merge_repair(ws):
    for mode, label in (("chained", "Motion"), ("shots", "Motion"), ("no_stills", "Prompt")):
        assert se.critic_field_lines(mode, None) == (
            MOTION_LINE % (label.lower(), label) + "\n" + DIALOGUE_LINE), mode
    ctx, state = _speaking_state(ws, SFT16_EXIT)
    new, applied, rejected = se.apply_patches(
        ctx, state, [_patch("panel", 1, "motion", "The courier turns to the camera.")],
        repairable={1: {"N21"}})
    assert (len(applied), rejected) == (1, [])
    assert new["parts"][0]["motion"] == "The courier turns to the camera."
    new, applied, rejected = se.apply_patches(
        ctx, state, [_patch("panel", 1, "motion", SFT16_EXIT)], repairable={1: {"N21"}})
    assert applied == []
    assert [r["reason"] for r in rejected] == [
        "the patch does not fix the panel's N7, N20, N21 or N22 problem"]
    new, applied, rejected = se.apply_patches(
        ctx, state, [_patch("panel", 1, "motion",
                            "The courier sits. The courier waits. The courier nods.")],
        repairable={1: {"T2"}})
    assert [r["reason"] for r in rejected] == [
        "the patch changes 2 sentences; it may change at most 1 contiguous sentence(s) and must "
        "keep every other sentence word for word"]
    old = dict(state["parts"][0], image="The courier stands by the zinc counter.")
    fixed = dict(state["parts"][0], image="The courier stands by the wooden gate.")
    assert se.merge_repair(ctx, state["plan"], 1, old, fixed, {"N22"})["image"] == (
        "The courier stands by the wooden gate.")
    assert se.merge_repair(ctx, state["plan"], 1, old, fixed, {"T2"})["image"] == (
        "The courier stands by the zinc counter.")


def test_review_focus_1_a_critic_patch_keeps_an_end_framed_camera_sentence_whole(ws):
    ctx, state = _speaking_state(ws, SFT16_EXIT)
    replacement = ("The courier turns to the camera. The camera pushes in — as the move "
                   "completes, his face fills the frame.")
    new, applied, rejected = se.apply_patches(
        ctx, state, [_patch("panel", 1, "motion", replacement)], repairable={1: {"N21"}})
    assert (len(applied), rejected) == (1, [])
    assert new["parts"][0]["motion"] == replacement
    field = dict(se.panel_fields(ctx, new["plan"], new["parts"], 1))["Motion"]
    assert field == ("The courier turns to the camera. The camera pushes in — as the move "
                     "completes, his face fills the frame. The courier faces the camera.")


# --- SFT19, SFT20, Review Focus 3: the trim (SF13b) --------------------------------------------

def test_sft19_the_trim_keeps_the_only_action(ws):
    ctx, plan, parts = _hockey(ws, story_id="sf19")
    part = dict(parts[1], motion="The FuboTV hockey player skates away.")
    assert se.trim_format(ctx, plan, 2, part) == part
    assert se.format_problems(ctx, plan, part, 2) != []


def test_sft20_the_chained_hockey_shape(ws):
    ctx, plan, parts = _hockey(ws, story_id="sf20")
    first, cut = ("The FuboTV hockey player carves a sharp stop, spraying ice mist into the air, "
                  "his face toward the lens, then pushes off and skates away from the camera.",
                  "The FuboTV hockey player carves a sharp stop, spraying ice mist into the air, "
                  "his face toward the lens, then pushes off.")
    assert se.panel_camera(ctx, plan, 2) == "static"
    assert se.format_problems(ctx, plan, parts[1], 2) == [
        "panel 2: N21 after the line: Motion: '%s' has a character leave the frame or turn away "
        "('skates away'); 'FuboTV hockey player' speaks in this panel, so end it with 'FuboTV "
        "hockey player' still in frame, face toward the camera" % first]
    trimmed = se.trim_format(ctx, plan, 2, parts[1])
    assert trimmed["motion"] == cut
    assert trimmed["repairs"] == [
        se.REPAIR_NOTE % (2, "N21", "after the line", "Motion",
                          "'and skates away from the camera.'"),
        se.REPAIR_NOTE % (2, "N21", "after the line", "Motion",
                          "'The camera holds on him as he recedes.'")]
    assert se.format_problems(ctx, plan, trimmed, 2) == []
    assert se.repair_action_text(ctx, plan, 2, parts[1]["motion"]) == (parts[1]["motion"], [])
    assert se.repair_action_text(ctx, plan, 1, parts[0]["motion"]) == (
        "The FuboTV hockey player skates forward toward the camera, his face toward the lens, in "
        "frame and lit.", [se.REPAIR_NOTE % (1, "N7", "dialogue and text", "Motion",
                                             "'as he speaks.'")])


def test_review_focus_3_an_end_frame_in_the_references_words_falls_back(ws):
    camera = ("The camera pushes in — as the move completes, her face fills the frame from chin "
              "to brow.")
    ctx, state = _speaking_state(ws, "The courier turns to the camera at real-time speed. "
                                 + camera)
    plan, part = state["plan"], state["parts"][0]
    problems = se.format_problems(ctx, plan, part, 1)
    assert [m for m in problems if " N22 " in m] == problems
    assert len(problems) == 1
    assert problems[0].startswith("panel 1: N22 reference copy: Motion: copies the format "
                                  "reference ('")
    trimmed = se.trim_format(ctx, plan, 1, part)
    assert trimmed["motion"] == "The courier turns to the camera at real-time speed."
    assert trimmed["repairs"] == [se.REPAIR_NOTE % (1, "N22", "reference copy", "Motion",
                                                    se._q(camera))]
    assert dict(se.panel_fields(ctx, plan, [trimmed], 1))["Motion"] == (
        "The courier turns to the camera at real-time speed. The courier faces the camera. The "
        "camera pushes in.")
```

- [ ] **Step 2: Run the tests to verify that they fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_shot_format.py 2>&1 | tail -1
```

Expected: `8 failed, 23 passed`. They fail on:
- the missing `FORMAT_IDS`, `format_problems` and `trim_format`;
- SFT11 and Review Focus 2 exiting 2 with no re-ask;
- the old critic field lines;
- the N21 patch being rejected by the old need set (Review Focus 1).

- [ ] **Step 3: Implement SF13b and SF13d-h.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
GENERATION_CHECKS = ("N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11", "N12",
                     "N14", "N15", "N16", "N17", "N18", "T1", "T2", "T3", "N20", "N21", "N22",
                     "Q1", "N19")


def panel_checks(ctx, plan, parts, text, story_md_path):
```

with:

```python
GENERATION_CHECKS = ("N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11", "N12",
                     "N14", "N15", "N16", "N17", "N18", "T1", "T2", "T3", "N20", "N21", "N22",
                     "Q1", "N19")


# Shot prompt format spec SF13, D8: the writer-format ids.
FORMAT_IDS = ("N7", "N20", "N21", "N22")


def format_problems(ctx, plan, part, k):
    """The hard N7, N20, N21 and N22 messages of panel k with writer parts part (SF13)."""
    parts = [{}] * (k - 1) + [part]
    writers = {LABELS[key]: part.get(key, "") for key in panel_keys(ctx, plan, k)
               if key != "title"}
    return _field_checks(ctx, _character_lib(ctx.ws), plan, k, part.get("title", ""),
                         panel_fields(ctx, plan, parts, k), writers, FORMAT_IDS, (),
                         generating=True)[0]


def trim_format(ctx, plan, k, part):
    """part after the SF13 trim, which runs only for an N21 or N22 that format_problems still
    finds: on the action field an exit is cut at the clause boundary before it (a camera
    sentence with an exit is dropped), a post-line sentence with another actor is dropped, and a
    sentence that copies the reference is dropped (_apply_drops keeps one action sentence); on
    the image and narration fields a copying sentence is dropped while one sentence remains.
    Each removal adds a REPAIR_NOTE to part["repairs"]."""
    ids = set(parse_violation(m)["id"] for m in format_problems(ctx, plan, part, k))
    if not ids & {"N21", "N22"}:
        return part
    lib = _character_lib(ctx.ws)
    phrases = cast_phrases(ctx, plan)
    new = dict(part)
    notes = list(part.get("repairs", []))
    action = "prompt" if ctx.mode == "no_stills" else "motion"
    label = LABELS[action]
    sentences = _sentences(new.get(action, ""))
    why = {}
    if "N21" in ids:
        beat = plan["beats"][k - 1]
        mentions = _mentions(plan["cast"])
        others = [m for m in mentions if m[0] != beat["speaker"]]
        own = [m for m in mentions if m[0] == beat["speaker"]]
        for i, sentence in enumerate(sentences):
            found = EXIT_RE.search(sentence)
            if not found:
                continue
            cut = (None if lib._is_camera_sentence(sentence, phrases)
                   else _cut_clause(sentence, found.start()))
            if cut:
                sentences[i] = cut[0]
                notes.append(REPAIR_NOTE % (k, "N21", "after the line", label, _q(cut[1])))
            else:
                why[i] = "N21"
        if ctx.mode != "no_stills":
            actions = [i for i, s in enumerate(sentences) if not lib._is_camera_sentence(s, phrases)
                       and not lib.is_facing_sentence(s, phrases)]
            for i in actions[1:]:
                if _other_actor(sentences[i], others, own):
                    why.setdefault(i, "N21")
    if "N22" in ids:
        for i, sentence in enumerate(sentences):
            if reference_copies(ctx.narrative, plan, sentence, ctx.goal):
                why.setdefault(i, "N22")
    kept, dropped = _apply_drops(lib, sentences, sorted(why), phrases)
    for i, sentence in enumerate(sentences):
        if sentence in dropped and i in why:
            name = "after the line" if why[i] == "N21" else "reference copy"
            notes.append(REPAIR_NOTE % (k, why[i], name, label, _q(sentence)))
    if kept:
        new[action] = " ".join(kept)
    if "N22" in ids:
        for key in ("image", "narration"):
            if new.get(key):
                field = _sentences(new[key])
                bad = [s for s in field if reference_copies(ctx.narrative, plan, s, ctx.goal)]
                if bad and len(bad) < len(field):
                    new[key] = " ".join(s for s in field if s not in bad)
                    notes += [REPAIR_NOTE % (k, "N22", "reference copy", LABELS[key], _q(s))
                              for s in bad]
    if notes:
        new["repairs"] = notes
    return new


def panel_checks(ctx, plan, parts, text, story_md_path):
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    motion = ('- target "panel", field "%s", index = the panel number, only for a panel with a '
              "[hard] T2 or T3 problem: replacement is the panel's whole new %s: writer text, "
              "identical to the current text except for the sentence or sentences that hold "
              "the extra or missing action." % (label.lower(), label))
```

with:

```python
    motion = ('- target "panel", field "%s", index = the panel number, only for a panel with a '
              "[hard] T2, T3, N7, N20, N21 or N22 problem: replacement is the panel's whole new "
              "%s: writer text, identical to the current text except for the sentence or "
              "sentences that cause the problem." % (label.lower(), label))
```

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        lines.append('- target "panel", field "dialogue", index = the panel number, only for a '
                     "panel with a [hard] T1 or N18 problem: replacement is the shortened spoken line, "
                     "without the speaker's phrase and without quotation marks, within the limit "
                     "the T1 problem states.")
```

with:

```python
        lines.append('- target "panel", field "dialogue", index = the panel number, only for a '
                     "panel with a [hard] T1, N18 or N22 problem: replacement is the new spoken "
                     "line, without the speaker's phrase and without quotation marks, within "
                     "the limit a T1 problem states.")
```

**3.4.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
CRITIC_SPEAKING_MOTION_CLAUSE = (
    " On a panel with a Dialogue: line, the pipeline inserts the spoken words right after the "
    "first sentence about what the speaker does, so keep everything the speaker does before "
    "the line in that first sentence and everything they do after it in a later sentence. Begin "
    "each of those sentences with the speaker's referring phrase.")
```

with:

```python
CRITIC_SPEAKING_MOTION_CLAUSE = (
    " On a panel with a Dialogue: line, the pipeline inserts the spoken words right after the "
    "first sentence about what the speaker does, so keep everything the speaker does before "
    "the line in that first sentence and at most one short sentence of the speaker's reaction "
    "after it, in which nobody else acts and the speaker never leaves the frame. Begin each of "
    "those sentences with the speaker's referring phrase.")
```

**3.5.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        need = {"T1", "N18"} if field == "dialogue" else {"T2", "T3"}
```

with:

```python
        need = ({"T1", "N18", "N22"} if field == "dialogue"
                else {"T2", "T3", "N7", "N20", "N21", "N22"})
```

**3.6.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        else:
            text = clean_writer(lib, patch["replacement"],
                                pasted_pieces(ctx, plan, k).get(field, ()))
            problem = (guard_problem(ctx, plan, parts[k - 1].get(field, ""), text) if text
                       else "empty after cleanup")
        if problem:
            rejected.append({"patch": patch, "reason": problem})
            continue
        parts[k - 1][field] = text
        applied.append(patch)
```

with:

```python
        else:
            text = clean_writer(lib, patch["replacement"],
                                cleanup_pieces(pasted_pieces(ctx, plan, k), field))
            notes = []
            if text and field in ("motion", "prompt"):
                text, notes = repair_action_text(ctx, plan, k, text)
            if not text:
                problem = "empty after cleanup"
            elif repairable is not None and repairable.get(k, set()) & set(FORMAT_IDS):
                problem = (None if len(format_problems(ctx, plan, dict(parts[k - 1], **{field: text}),
                                                       k))
                           < len(format_problems(ctx, plan, parts[k - 1], k))
                           else "the patch does not fix the panel's N7, N20, N21 or N22 problem")
            else:
                problem = guard_problem(ctx, plan, parts[k - 1].get(field, ""), text)
        if problem:
            rejected.append({"patch": patch, "reason": problem})
            continue
        parts[k - 1][field] = text
        if field in ("motion", "prompt"):
            parts[k - 1].pop("repairs", None)
            if notes:
                parts[k - 1]["repairs"] = notes
        applied.append(patch)
```

**3.7.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
# The hard ids a code-only round sends back to the panel writer (PG5; speaker attribution spec
# Q1-A2 adds N18, so a free line that says another speaker's line is rewritten).
REPAIR_IDS = ("N11", "N18", "T1", "T2", "T3")
```

with:

```python
# The hard ids a code-only round sends back to the panel writer (PG5; speaker attribution spec
# Q1-A2 adds N18, so a free line that says another speaker's line is rewritten; shot prompt
# format spec SF13 adds N7, N20, N21 and N22).
REPAIR_IDS = ("N7", "N11", "N18", "N20", "N21", "N22", "T1", "T2", "T3")
```

**3.8.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    """Panel k's writer parts after a code-only round (dialogue spec PG5): new's motion or prompt
    when ids has T2 or T3 and the PG3 guard accepts it, new's dialogue when ids has T1 or N18
    (speaker attribution spec Q1-A2) and the line fits, new's narration when ids has N11; every
    other part keeps old's text."""
    merged = dict(old)
    action = "prompt" if ctx.mode == "no_stills" else "motion"
    if (ids & {"T2", "T3"} and new.get(action)
            and guard_problem(ctx, plan, old.get(action, ""), new[action]) is None):
        merged[action] = new[action]
    if (ids & {"T1", "N18"} and new.get("dialogue")
            and line_problem(ctx, _character_lib(ctx.ws), _sentence(new["dialogue"])) is None):
        merged["dialogue"] = new["dialogue"]
    if "N11" in ids and "narration" in new:
```

with:

```python
    """Panel k's writer parts after a code-only round (dialogue spec PG5): new's motion or prompt
    when ids has T2 or T3 and the PG3 guard accepts it, new's dialogue when ids has T1 or N18
    (speaker attribution spec Q1-A2) and the line fits, new's narration when ids has N11; every
    other part keeps old's text. With N7, N20, N21 or N22 (shot prompt format spec SF13) it takes
    new's action text when that has fewer writer-format problems, and for N22 new's image or
    narration when only old's copies the reference."""
    merged = dict(old)
    action = "prompt" if ctx.mode == "no_stills" else "motion"
    if (ids & {"T2", "T3"} and new.get(action)
            and guard_problem(ctx, plan, old.get(action, ""), new[action]) is None):
        merged[action] = new[action]
    if (ids & {"T1", "N18", "N22"} and new.get("dialogue")
            and line_problem(ctx, _character_lib(ctx.ws), _sentence(new["dialogue"])) is None):
        merged["dialogue"] = new["dialogue"]
    if (ids & set(FORMAT_IDS) and new.get(action)
            and len(format_problems(ctx, plan, new, k))
            < len(format_problems(ctx, plan, old, k))):
        merged[action] = new[action]
        merged.pop("repairs", None)
        if new.get("repairs"):
            merged["repairs"] = new["repairs"]
    if "N22" in ids:
        for key in ("image", "narration"):
            if (new.get(key) and old.get(key)
                    and reference_copies(ctx.narrative, plan, old[key], ctx.goal)
                    and not reference_copies(ctx.narrative, plan, new[key], ctx.goal)):
                merged[key] = new[key]
    if "N11" in ids and "narration" in new:
```

**3.9.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
            if new is not None:
                parts[k - 1] = new
                valid += 1
```

with:

```python
            if new is not None:
                parts[k - 1] = new
                # Shot prompt format spec SF13, D8: one re-ask for a writer-format problem while
                # the panel has a call left, then the deterministic trim.
                problems = format_problems(ctx, plan, new, k)
                if (problems and self.panel_calls[k] < PANEL_MAX_CALLS
                        and not self.expired()):
                    again = self.panel_call(plan, parts, k, 0, problems)
                    if (again is not None
                            and len(format_problems(ctx, plan, again, k)) <= len(problems)):
                        parts[k - 1] = again
                parts[k - 1] = trim_format(ctx, plan, k, parts[k - 1])
                valid += 1
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_shot_format.py 2>&1 | tail -1
```

Expected: `31 passed`. Run the compile check with `FILES` = `story_engine.py tests/test_shot_format.py`; expected: `compiled 2` twice. Then run the gate block of Task 1 Step 4 with `task-4-pytest.txt` and task number `4`. Expected: `GATE PASS`, `test_shot_format 31, not passing 0`, `baseline failures still failing 2 of 2` and `OK 347/347`.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_shot_format.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_shot_format.py
git commit -m "feat(story): a writer-format problem is re-asked once in round 0, then trimmed; the critic and code-only rounds can repair it (SF13b, SF13d-h; SFT1d, SFT11, SFT16, SFT19, SFT20)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: P19, the exit after the last line that cannot be filmed (amendment SF-A1, coordinator ruling CR1)

This task implements SF-A1's `P19_NOTE`, `narrative_exit_after_last_line` and `exit_left_out_notes`, and their `_Run.go` call after `cap_static_cameras`. The note carries the CR1 text: "...; rerun with --force-story --panels %d to keep it".

Tests: SFT23, SFT24, SFT25.

**Files:**
- Modify: `story_engine.py`. The edits go between `EXIT_RE` and `post_line_sentences` (Task 3), and in `_Run.go` after the Task 1 `cap_static_cameras` line.
- Modify: `tests/test_shot_format.py` (append).

**Interfaces:**
- Consumes: Task 3's `EXIT_RE`; the existing `QUOTE_RE`, `classify_quotes`, `line_words`, `_q`; Task 1's `_Run.go` line `plan["speech_notes"] += cap_static_cameras(ctx, plan)`.
- Produces:
  - `P19_NOTE`, a `%` format of `(quoted exit words, panels + 1)`;
  - `narrative_exit_after_last_line(narrative) -> str or None`;
  - `exit_left_out_notes(ctx, plan) -> [str]`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_sft23_the_narratives_exit_after_its_last_line`, `test_sft24_when_p19_fires` and `test_sft25_p19_end_to_end`.

Edit `tests/test_shot_format.py` (append): replace this text, the file's last lines, which occurs exactly once:

```python
    assert dict(se.panel_fields(ctx, plan, [trimmed], 1))["Motion"] == (
        "The courier turns to the camera at real-time speed. The courier faces the camera. The "
        "camera pushes in.")
```

with:

```python
    assert dict(se.panel_fields(ctx, plan, [trimmed], 1))["Motion"] == (
        "The courier turns to the camera at real-time speed. The courier faces the camera. The "
        "camera pushes in.")


# --- SFT23, SFT24, SFT25: P19, the exit after the last line (amendment SF-A1) --------------------

P19_NOTE = ("plan: P19 exit left out: the narrative's exit after its last spoken line (%s) was "
            "left out, because that line is in the last beat and a speaking beat never shows its "
            "speaker leave; rerun with --force-story --panels %d to keep it")


def test_sft23_the_narratives_exit_after_its_last_line():
    assert HOCKEY_NARRATIVE == _read_json(HOCKEY_FIX, "plan.json")["narrative"]
    rows = (
        (HOCKEY_NARRATIVE, "skates away"),
        (LINES_NARRATIVE, None),
        ('Kyra says, "Go." She walks off.', "walks off"),
        ('Kyra walks off. Kyra says, "Go."', None),
        ('Kyra says, "Go," and the ronin leaves the frame.', "leaves the frame"),
        ('Kyra says, "Go." Later the crowd says, "Yes." Kyra turns away.', "turns away"),
        ('A sign reads "Closed". Kyra walks away.', None),
        ('Kyra says, "Go." She pushes off from the kerb.', None),
        ('Kyra says, “Go.” She skates away.', "skates away"),
    )
    for narrative, want in rows:
        assert se.narrative_exit_after_last_line(narrative) == want, narrative


def _p19_plan(ws, mode, lines, narrative=HOCKEY_NARRATIVE, narration="speech"):
    """(ctx, normalised plan) of len(lines) beats: beat k says lines[k - 1], spoken by the courier
    (c1) when it has lines."""
    ctx = seu.make_ctx(se, ws, mode=mode, panels=len(lines), narrative=narrative,
                       narration=narration)
    raw = seu.plan_json(mode, len(lines))
    for beat, numbers in zip(raw["beats"], lines):
        beat.update(lines=list(numbers), speaker="c1" if numbers else "")
    plan, _shape = se.normalize_plan(ctx, raw)
    return ctx, plan


def test_sft24_when_p19_fires(ws):
    rows = (
        ("chained", [[1], [2]], {}, [P19_NOTE % ("'skates away'", 3)]),
        ("chained", [[1, 2]], {}, [P19_NOTE % ("'skates away'", 2)]),
        ("shots", [[1], [2], []], {}, []),
        ("shots", [[1], [], [2]], {}, [P19_NOTE % ("'skates away'", 4)]),
        ("chained", [[1], [2]], {"narration": False}, []),
        ("chained", [[1], []], {}, []),
        ("chained", [[1], [2]], {"narrative": LINES_NARRATIVE}, []),
        ("shots", [[1], [], [2]], {"narrative": LINES_NARRATIVE}, []),
    )
    for mode, lines, kw, want in rows:
        ctx, plan = _p19_plan(ws, mode, lines, **kw)
        assert se.exit_left_out_notes(ctx, plan) == want, (mode, lines, kw)
    assert se.P19_NOTE == P19_NOTE
    violation = se.parse_violation(P19_NOTE % ("'x'", 3))
    assert (violation["id"], violation["name"], violation["scope"], violation["index"]) == (
        "P19", "exit left out", "plan", None)


def _sft25_run(ws, tmp_path, monkeypatch, story_id, narrative):
    """(rc, advisories, ctx) of a chained 2-panel --speech-only run of narrative: beat k says
    spoken line k, spoken by the courier."""
    raw = seu.plan_json("chained", 2)
    raw["beats"][0].update(speaker="c1", lines=[1])
    raw["beats"][1].update(speaker="c1", lines=[2])
    panel = {"1": [seu.answer({"title": "Skate In", "image": seu.panel_json("chained", 1)["image"],
                               "motion": "The courier glides toward the camera at real-time "
                                         "speed, his face to the lens.",
                               "dialogue": "x"})],
             "2": [seu.answer({"title": "The Stop",
                               "motion": "The courier carves a hard stop at real-time speed, a "
                                         "big bright spray of ice in the air.",
                               "dialogue": "x"})]}
    seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(raw)], panel=panel)
    ctx = seu.make_ctx(se, ws, mode="chained", panels=2, narration="speech", narrative=narrative,
                       story_id=story_id)
    rc, advisories = se.run(ctx)
    return rc, advisories, ctx


def test_sft25_p19_end_to_end(ws, tmp_path, monkeypatch, capsys):
    note = P19_NOTE % ("'skates away'", 3)
    rc, advisories, ctx = _sft25_run(ws, tmp_path, monkeypatch, "sf25", HOCKEY_NARRATIVE)
    assert rc == 0
    assert [a for a in advisories if " P19 " in a] == [note]
    assert note.endswith("; rerun with --force-story --panels 3 to keep it")
    assert [m for m in _messages(ctx, "advisory") if " P19 " in m] == [note]
    assert note in _read_json(ctx.story_dir, "plan.json")["speech_notes"]
    capsys.readouterr()
    rc, advisories = se.recheck(ctx, lambda path, panels, no_stills=False: [])
    captured = capsys.readouterr()
    assert rc == 0
    assert [a for a in advisories if "P19" in a] == []
    assert "P19" not in captured.out + captured.err
    rc, advisories, ctx = _sft25_run(ws, tmp_path, monkeypatch, "sf25b", LINES_NARRATIVE)
    assert rc == 0
    assert [a for a in advisories if "P19" in a] == []
    assert [m for m in _messages(ctx, "advisory") if "P19" in m] == []
```

- [ ] **Step 2: Run the tests to verify that they fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_shot_format.py 2>&1 | tail -1
```

Expected: `3 failed, 31 passed`. They fail on the missing `narrative_exit_after_last_line`, `exit_left_out_notes` and the P19 advisory.

- [ ] **Step 3: Implement SF-A1 with CR1.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    r"turn(?:s|ing)?\s+(?:her|his|their)\s+back)\b", re.IGNORECASE)


def post_line_sentences(lib, text, phrases):
```

with:

```python
    r"turn(?:s|ing)?\s+(?:her|his|their)\s+back)\b", re.IGNORECASE)


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


def post_line_sentences(lib, text, phrases):
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        plan["speech_notes"] += cap_static_cameras(ctx, plan)
```

with:

```python
        plan["speech_notes"] += cap_static_cameras(ctx, plan)
        plan["speech_notes"] += exit_left_out_notes(ctx, plan)
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_shot_format.py 2>&1 | tail -1
```

Expected: `34 passed`. Run the compile check with `FILES` = `story_engine.py tests/test_shot_format.py`; expected: `compiled 2` twice. Then run the gate block of Task 1 Step 4 with `task-5-pytest.txt` and task number `5`.
- Expected: `GATE PASS`, `test_shot_format 34, not passing 0`, `baseline failures still failing 2 of 2` and `OK 347/347`.
- A hockey-narrative E2E whose last line lands in its last beat may now gain one P19 advisory. That is R17, and such a test was already listed or rules through the gate.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_shot_format.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_shot_format.py
git commit -m "feat(story): tell the user when the narrative's exit after its last line is left out, and how to keep it (P19; SF-A1, CR1; SFT23-SFT25)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The fixed-order composition of a speech movie's prompts (SF15a-b, SF16)

This task implements:
- SF15a, the new `ACOUSTIC_SENTENCE` text;
- SF15b, `AMBIENCE_SENTENCE`, `SHOT_SENTENCE_RE`, `framing_sentence`, `compose_motion` and `panel_prompt` in `character_lib.py`;
- SF16, the manifest's `speech_movie`/`order_phrases`, the speech insertion and the `--speech-delivery` help.

Tests: SFT1 (audio part), SFT13, SFT14.

**Files:**
- Modify: `character_lib.py`: `ACOUSTIC_SENTENCE` (`:759-760`), and after `speech_text` (`:841-844`).
- Modify: `bin/ltx-story-manifest`: the help (`:183-187`), after `_spoken` (`:696-698`) and the speech insertion (`:828-832`).
- Modify: `tests/test_shot_format.py` (append).

**Interfaces:**
- Consumes:
  - in `character_lib`: `speech_text(phrase, line, delivery)`, `speech_sentence`, `_SENTENCE_SPLIT_RE`, `is_facing_sentence(sentence, phrases)`, `_is_camera_sentence(sentence, phrases)` and `DEFAULT_SPEECH_DELIVERY`;
  - in the manifest: `_known_phrases(args, members)`, `_character_lib()` and `spoken`.
- Produces, in `character_lib`:
  - `ACOUSTIC_SENTENCE` (new text) and `AMBIENCE_SENTENCE`;
  - `framing_sentence(image) -> str`;
  - `compose_motion(text, speech="", phrases=(), audio="", framing="") -> str`;
  - `panel_prompt(motion, framing="", speaker=None, line="", delivery=DEFAULT_SPEECH_DELIVERY, phrases=()) -> str`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_sft1e_audio_constants`, `test_sft13_the_composition_and_the_reference` and `test_sft14_the_manifest_composes_the_fixed_order`.

Edit `tests/test_shot_format.py` (append): replace this text, the file's last lines, which occurs exactly once:

```python
    assert rc == 0
    assert [a for a in advisories if "P19" in a] == []
    assert [m for m in _messages(ctx, "advisory") if "P19" in m] == []
```

with:

```python
    assert rc == 0
    assert [a for a in advisories if "P19" in a] == []
    assert [m for m in _messages(ctx, "advisory") if "P19" in m] == []


# --- SFT1 (Task 6 part): the audio sentences (SF15a, SF15b) -------------------------------------

ACOUSTIC_SENTENCE = ("The audio is clear close-mic dialogue with a subtle natural room tone; "
                     "the dialogue takes priority over the quiet ambience, and there is no music.")
AMBIENCE_SENTENCE = "The audio is the natural ambient sound of the place, with no music."


def test_sft1e_audio_constants():
    assert lib.ACOUSTIC_SENTENCE == ACOUSTIC_SENTENCE
    assert lib.AMBIENCE_SENTENCE == AMBIENCE_SENTENCE
    assert se.FORMAT_REFERENCE.count(ACOUSTIC_SENTENCE) == 1
    assert se.FORMAT_REFERENCE.count(AMBIENCE_SENTENCE) == 2


# --- SFT13: the composition and the reference's self-consistency (SF15, SF8, SK6) ---------------

def test_sft13_the_composition_and_the_reference(ws):
    shots = ref_shots()
    assert len(shots) == 3
    for part, shot in zip(REF_PARTS, shots):
        assert lib.panel_prompt(part["motion"], part["shot"], part["speaker"], part["line"],
                                "beats", [REF_PHRASE]) == shot
    for part, key in zip(REF_PARTS, ("tracking", "slow push-in", "static")):
        assert se.camera_problem(lib, part["motion"], [REF_PHRASE], key) is None, key
    post = se.post_line_sentences(lib, REF_PARTS[1]["motion"], [REF_PHRASE])
    assert post == ["The old fishmonger lets the folded cloth drop onto the counter, her "
                    "shoulders sinking."]
    assert se._other_actor(post[0], [], se._mentions([{"id": "c1", "phrase": REF_PHRASE}])) is None
    assert lib.compose_motion("The camera tracks alongside the movement. A runs.", "S", ["x"]) == (
        "A runs. S The camera tracks alongside the movement.")
    assert lib.compose_motion("A. X faces the camera. B. The camera tracks alongside the movement.",
                              "S", ["x"]) == (
        "A. X faces the camera. S B. The camera tracks alongside the movement.")
    assert lib.compose_motion("X faces the camera. The camera tracks alongside the movement.", "S",
                              ["x"], "AUDIO.", "The shot is a close-up.") == (
        "The shot is a close-up. X faces the camera. S The camera tracks alongside the movement. "
        "AUDIO.")
    assert lib.compose_motion("The shot is a close-up. A runs.", "", ["x"], "",
                              "The shot is a close-up.") == "The shot is a close-up. A runs."
    assert lib.framing_sentence("The courier waits. The shot is a wide shot. The shot is a "
                                "close-up.") == "The shot is a close-up."
    assert lib.framing_sentence("The courier waits.") == ""
    assert lib.panel_prompt("A runs.", "", "x", "Go.", "plain") == 'A runs. X says: "Go."'
    assert lib.panel_prompt("A runs.", "", "x", "Go.", "beats-no-acoustic") == (
        'A runs. X says, "Go."')
    assert lib.panel_prompt("A runs.", "", None, "", "beats") == "A runs. " + AMBIENCE_SENTENCE
    assert lib.panel_prompt("A runs.", "", None, "", "plain") == "A runs."


# --- SFT14: the manifest composes a speech movie in the fixed order (SF16, SK6) ----------------

SFT14_SETTING = seu.HARBOUR


def _sft14_story(panel_1_speech):
    """A 2-panel shots story.md: panel 1 a medium shot with panel_1_speech (a Dialogue: or
    Narration: line), panel 2 a silent wide shot with a Narration: line."""
    return ("# The Letter\n\nA courier brings a letter.\n\n## Characters\n"
            "- \"the courier\": %s.\n\n"
            "## Panel 1 — The Gate\n"
            "Image: %s The courier stands at the gate. The courier faces the camera. The shot is a "
            "medium shot.\n"
            "Motion: The courier lifts the sealed letter at real-time speed. The courier faces the "
            "camera. The camera pushes in.\n"
            "%s\n\n"
            "## Panel 2 — The Road\n"
            "Image: %s The courier walks down the road. The shot is a wide shot.\n"
            "Motion: The courier walks down the road at real-time speed. The camera tracks "
            "alongside the movement.\n"
            "Narration: The road was long.\n") % (seu.COURIER, SFT14_SETTING, panel_1_speech,
                                                   SFT14_SETTING)


SFT14_CHAIN = """# The Gate

A courier reaches a hilltop temple.

## Panel 1 — The Steps
Image: %s The courier climbs toward the gate. The shot is a wide shot.
Motion: The courier climbs the last worn step at real-time speed. The camera tracks alongside the movement.
Narration: The bell had not yet rung.

## Panel 2 — At the Gate
Motion: The old monk lifts his eyes at real-time speed. The old monk faces the camera. The camera pushes in.
Dialogue: the old monk: You came far.
""" % SFT14_SETTING


def _sft14_prompts(tmp_path, monkeypatch, story_id, text, mode, extra=(), plan=None):
    story_md, images, ws = _manifest_ws(tmp_path, monkeypatch, story_id, text, plan=plan,
                                        images=1 if mode == "chain" else 2)
    if mode == "v2":
        argv = ["--story-id", story_id, "--prompts-md", story_md, "--image", images[0],
                "--image", images[1], "--fps", "24", "--target-seconds", repr(145 * 2 / 24.0),
                "--min-frames", "145", "--max-frames", "145", "--force"] + list(extra)
    else:
        argv = _manifest_argv(story_id, story_md, images, mode=mode, extra=extra)
    assert story_manifest.main(argv) == 0
    return [p["motion_prompt"] for p in _read_manifest(ws, story_id)["panels"]]


def test_sft14_the_manifest_composes_the_fixed_order(tmp_path, monkeypatch):
    speaking = _sft14_story("Dialogue: the courier: Go now.")
    assert _sft14_prompts(tmp_path, monkeypatch, "sf14a", speaking, "shots") == [
        "The shot is a medium shot. The courier lifts the sealed letter at real-time speed. The "
        "courier faces the camera. The courier says, \"Go now.\" The camera pushes in. "
        + ACOUSTIC_SENTENCE,
        "The shot is a wide shot. The courier walks down the road at real-time speed. The camera "
        "tracks alongside the movement. " + AMBIENCE_SENTENCE]
    assert _sft14_prompts(tmp_path, monkeypatch, "sf14b", SFT14_CHAIN, "chain",
                          plan=CAST_PLAN) == [
        "The shot is a wide shot. The courier climbs the last worn step at real-time speed. The "
        "camera tracks alongside the movement. " + AMBIENCE_SENTENCE,
        "The old monk lifts his eyes at real-time speed. The old monk faces the camera. The old "
        "monk says, \"You came far.\" The camera pushes in. " + ACOUSTIC_SENTENCE]
    silent = _sft14_story("Narration: The gate was shut.")
    assert _sft14_prompts(tmp_path, monkeypatch, "sf14c", silent, "shots") == [
        "The courier lifts the sealed letter at real-time speed. The courier faces the camera. The "
        "camera pushes in.",
        "The courier walks down the road at real-time speed. The camera tracks alongside the "
        "movement."]
    assert _sft14_prompts(tmp_path, monkeypatch, "sf14d", speaking, "v2") == [
        "The courier lifts the sealed letter at real-time speed. The courier faces the camera. The "
        "courier says, \"Go now.\" The camera pushes in. " + ACOUSTIC_SENTENCE,
        "The courier walks down the road at real-time speed. The camera tracks alongside the "
        "movement."]
    assert _sft14_prompts(tmp_path, monkeypatch, "sf14e", speaking, "shots",
                          extra=["--speech-delivery", "plain"]) == [
        "The shot is a medium shot. The courier lifts the sealed letter at real-time speed. The "
        "courier faces the camera. The courier says: \"Go now.\" The camera pushes in.",
        "The shot is a wide shot. The courier walks down the road at real-time speed. The camera "
        "tracks alongside the movement."]
```

- [ ] **Step 2: Run the tests to verify that they fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_shot_format.py 2>&1 | tail -1
```

Expected: `3 failed, 34 passed`. They fail on the missing `AMBIENCE_SENTENCE` and `panel_prompt`, and on the old manifest order.

- [ ] **Step 3: Implement SF15a-b and SF16.**

**3.1.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
ACOUSTIC_SENTENCE = ("The audio is clear close-mic dialogue with a subtle natural room tone; "
                     "the dialogue takes priority over the quiet ambience.")
```

with:

```python
ACOUSTIC_SENTENCE = ("The audio is clear close-mic dialogue with a subtle natural room tone; "
                     "the dialogue takes priority over the quiet ambience, and there is no music.")
```

**3.2.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
    return text if delivery == "beats-no-acoustic" else text + " " + ACOUSTIC_SENTENCE


def panel_strengths(names, members, character_strength, shots=False):
```

with:

```python
    return text if delivery == "beats-no-acoustic" else text + " " + ACOUSTIC_SENTENCE


# Shot prompt format spec SF15, D6: a speech movie's chained or shots video prompt, in the fixed
# order framing, first action, facing, line, other actions, camera, audio.
AMBIENCE_SENTENCE = "The audio is the natural ambient sound of the place, with no music."
SHOT_SENTENCE_RE = re.compile(r"The shot is an? (?:extreme wide shot|wide shot|medium shot|"
                              r"medium close-up|close-up|extreme close-up)\.")


def framing_sentence(image):
    """The last robust-engine shot sentence ("The shot is a medium shot.") in an Image: text, or
    "" (SF15)."""
    found = SHOT_SENTENCE_RE.findall(image or "")
    return found[-1] if found else ""


def compose_motion(text, speech="", phrases=(), audio="", framing=""):
    """text's sentences in the SF15 order: framing (unless text already has that shot
    sentence), text's shot sentences, its first action sentence, its pasted facing sentences
    (is_facing_sentence with phrases), speech, its other action sentences, its camera sentences
    (_is_camera_sentence with phrases), audio. Empty pieces are left out."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split((text or "").strip()) if s.strip()]
    shot = [s for s in sentences if SHOT_SENTENCE_RE.fullmatch(s)]
    facing = [s for s in sentences if s not in shot and is_facing_sentence(s, phrases)]
    camera = [s for s in sentences if s not in shot and s not in facing
              and _is_camera_sentence(s, phrases)]
    actions = [s for s in sentences if s not in shot and s not in facing and s not in camera]
    lead = [framing] if framing and framing not in shot else []
    return " ".join(lead + shot + actions[:1] + facing + ([speech] if speech else [])
                    + actions[1:] + camera + ([audio] if audio else []))


def panel_prompt(motion, framing="", speaker=None, line="", delivery=DEFAULT_SPEECH_DELIVERY,
                 phrases=()):
    """The final video prompt of one chained or shots panel of a speech movie (SF15): on a
    speaking panel (speaker set) compose_motion with speech_text's words (no acoustic sentence)
    and [speaker] as the phrases; with beats delivery the last sentence is ACOUSTIC_SENTENCE on
    a speaking panel and AMBIENCE_SENTENCE on a silent one; plain and beats-no-acoustic add no
    audio sentence."""
    speaks = speaker is not None
    said = (speech_text(speaker, line, "beats-no-acoustic" if delivery == "beats" else delivery)
            if speaks else "")
    audio = "" if delivery != "beats" else ACOUSTIC_SENTENCE if speaks else AMBIENCE_SENTENCE
    return compose_motion(motion, said, [speaker] if speaks else phrases, audio, framing)


def panel_strengths(names, members, character_strength, shots=False):
```

**3.3.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
                         help="how a Dialogue: line (or a spoken Narration: line) is written into "
                              "motion_prompt: beats (default) splits it at sentence ends with "
                              "short fixed beats and adds a fixed close-mic audio sentence; "
                              "beats-no-acoustic omits that sentence; plain is '<Speaker> says: "
                              "\"<line>\"'")
```

with:

```python
                         help="how a Dialogue: line (or a spoken Narration: line) is written into "
                              "motion_prompt: beats (default) splits it at sentence ends with "
                              "short fixed beats and ends the prompt with a fixed audio "
                              "sentence; beats-no-acoustic omits that sentence; plain is "
                              "'<Speaker> says: \"<line>\"'")
```

**3.4.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
    spoken = _spoken(args, prompt_texts, members)
    if spoken is None:
        return 2
```

with:

```python
    spoken = _spoken(args, prompt_texts, members)
    if spoken is None:
        return 2

    # Shot prompt format spec SF16, D6: a speech movie's chained or shots prompts use the fixed
    # order; a movie with no spoken panel composes exactly as before.
    speech_movie = any(s[0] is not None for s in spoken)
    order_phrases = (_known_phrases(args, members)
                     if speech_movie and (args.chain or args.shots) else [])
```

**3.5.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
        if speaker is not None and motion_prompt is not None:
            lib_ = _character_lib()
            motion_prompt = lib_.insert_speech(
                motion_prompt, lib_.speech_text(speaker, speech, args.speech_delivery), [speaker],
                first_action=bool(args.chain or args.shots))
```

with:

```python
        if motion_prompt is not None and speech_movie and (args.chain or args.shots):
            lib_ = _character_lib()
            framing = lib_.framing_sentence(pt["image"]) if (args.shots or i == 1) else ""
            motion_prompt = lib_.panel_prompt(motion_prompt, framing, speaker, speech,
                                              args.speech_delivery, order_phrases)
        elif speaker is not None and motion_prompt is not None:
            lib_ = _character_lib()
            beats = args.speech_delivery == "beats"
            motion_prompt = lib_.insert_speech(
                motion_prompt, lib_.speech_text(speaker, speech, "beats-no-acoustic" if beats
                                                else args.speech_delivery), [speaker],
                first_action=bool(args.chain or args.shots))
            if beats:
                motion_prompt += " " + lib_.ACOUSTIC_SENTENCE
```

- [ ] **Step 4: Run the new tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_shot_format.py 2>&1 | tail -1
```

Expected: `37 passed`. Run the compile check with `FILES` = `story_engine.py character_lib.py bin/ltx-story-manifest tests/test_shot_format.py`; expected: `compiled 4` twice. Then run the gate block of Task 1 Step 4 with `task-6-pytest.txt` and task number `6`. Expected: `GATE PASS`, `test_shot_format 37, not passing 0`, `baseline failures still failing 2 of 2` and `OK 347/347`.
- `tests/test_ltx_story_manifest_chain.py` must pass in full, `test_v2_golden_byte_identical` included (spec 4.3). No listed line covers it, so a failure there stops the gate.

- [ ] **Step 5: Commit.**

```bash
git add character_lib.py bin/ltx-story-manifest tests/test_shot_format.py
git diff --cached --name-only    # expected: qwen-agent-workspace/bin/ltx-story-manifest, qwen-agent-workspace/character_lib.py, qwen-agent-workspace/tests/test_shot_format.py
git commit -m "feat(manifest): a speech movie's prompt is shot, action, line, reaction, camera, then the audio sentence last (SF15, SF16; SFT1e, SFT13, SFT14)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Re-baseline the existing tests (G5; test-only commit; spec 4.2)

This task changes no pipeline file. It turns every listed failure green by updating its assertions or fixture to the new behaviour. The work is split so that the executor makes no decision:
- The measurement and the edits are executor steps.
- The classification, the exact edit text and the per-file explanations come from an Opus pass that the controller runs. "Opus thinks, Sonnet types."

**Files:**
- Modify: only the existing test files and fixtures that the Step 2 re-baseline spec names. The candidates are spec 4.2's files: `tests/test_story_engine.py`, `tests/test_dialogue.py`, `tests/test_narrative_fidelity.py`, `tests/test_writer_pacing.py`, `tests/test_pinned_cast.py`, `tests/fixtures/pinned_cast/uncast_*.txt`, `tests/test_speaker_attribution.py`, `tests/test_shots_mode.py`, `tests/test_casting_pipeline.py` and `tests/fixtures/casting_baseline/*`.
- Never: `tests/fixtures/writer_pacing/**` (spec 4.2), `tests/test_shot_format.py` and `tests/test_movie_ui_builder.py` (Task 8), and any pipeline file.

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
D=$S/sf-baseline
cd $S/sf-wt/qwen-agent-workspace
python3 -B $D/gate.py $D/baseline-pytest.txt $D/task-6-pytest.txt $D/expected-failures.txt 6 | grep '^LOST' | awk '{print $2}' | grep -v test_mut26 > $D/rebaseline-ids.txt
wc -l < $D/rebaseline-ids.txt
python3 -B -m pytest -q -p no:cacheprovider --tb=long -vv $(cat $D/rebaseline-ids.txt) > $D/rebaseline-diffs.txt 2>&1; tail -1 $D/rebaseline-diffs.txt
```

Expected: the count of lost tests other than `test_mut26`, and a summary line `N failed`, where N is that count. Report N to the controller.

- [ ] **Step 2: The re-baseline spec (controller; an Opus `spec-author` or `investigator`; not an executor step).**

Give it four inputs: spec 4.2 (its rule and R1-R17), this plan's R18 and Plan rulings, `$D/rebaseline-ids.txt` and `$D/rebaseline-diffs.txt`. It writes `$D/rebaseline-spec.md`, which holds:
- **(a) A code for every test.** Each test gets the R code(s) that explain every line of its diff.
  - A diff line that no code explains is a defect. It is fixed in the pipeline code by a fix commit on the owning task's files, and the task gate is re-run, before any test edit.
- **(b) The exact edits, per file.** For each file, the exact Edit steps (old text, new text) that update each changed assertion or golden literal to the value the diff shows.
  - No test is deleted, and no assertion is weakened beyond the new behaviour.
  - A whole-prompt byte fixture (`tests/fixtures/pinned_cast/uncast_*.txt`) is regenerated by one exact command that writes the new `build_plan_prompt` output. Its diff against the old file must be exactly the camera list order, the `CAMERA_RULE`/`CAMERA_SPEAKING_SENTENCE` insertion and the speaker-rule text (spec 4.2).
- **(c) The commit message body.** One paragraph per changed file. Each paragraph names the tests, the codes, and, in one sentence per golden, what changed (spec 4.2 rule; for example "panel 2 Motion: 'The camera stays static.' fallback dropped because the writer's 'The camera tracks him.' is valid (R6)"). The message ends with the trailer line.

- [ ] **Step 3: Apply the re-baseline spec exactly (executor).**

Make every Edit of `$D/rebaseline-spec.md` (b) in order, and run its fixture command, if any. Write its message (c) to `$D/rebaseline-commit-msg.txt` with the Write tool. If an old text does not occur exactly once, stop and report.

- [ ] **Step 4: Verify (executor).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/sf-baseline
cd $S/sf-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider $(cat $D/rebaseline-ids.txt) 2>&1 | tail -1
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/task-7-pytest.txt 2>&1; tail -1 $D/task-7-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/task-7-pytest.txt $D/expected-failures.txt 7 | grep -E '^(LOST|GATE)'
git diff --name-only | grep -v -E '^qwen-agent-workspace/tests/' || echo "tests only"
git diff --name-only | grep -E 'writer_pacing/|test_shot_format|test_movie_ui_builder' || echo "no forbidden file"
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1
```

Expected:
- `N passed`;
- the full-suite summary `3 failed, 1926 passed, 2 skipped`: the two baseline failures plus `test_mut26`, and 1890 - 1 + 37 passed;
- exactly one `LOST` line, `test_mut26 ... listed`, then `GATE PASS`;
- `tests only`, `no forbidden file` and `OK 347/347`.

- [ ] **Step 5: Review (controller; Opus `design-reviewer`).**

The reviewer checks every paragraph of `$D/rebaseline-commit-msg.txt` against `git diff`. Each changed line must trace to its stated code, and no assertion may be weakened. Fix every finding through Steps 2-4 before Step 6.

- [ ] **Step 6: Commit (test-only; spec 0.4 G5).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/sf-wt/qwen-agent-workspace
git add $(git diff --name-only --relative)
git diff --cached --name-only    # expected: only qwen-agent-workspace/tests/... paths, as listed in the re-baseline spec
tail -1 $S/sf-baseline/rebaseline-commit-msg.txt    # expected: Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
git commit -F $S/sf-baseline/rebaseline-commit-msg.txt
```

The subject line of the message is `test: re-baseline the existing tests to the shot prompt format (spec 4.2)`.

---

### Task 8: Whole-branch review, the test_mut26 re-baseline (G6), SK1-SK3 and the hand-off

**Files:**
- Modify: `tests/test_movie_ui_builder.py`: the `test_mut26` comment and `BASELINE` (`:283-285`).

**Interfaces:**
- Consumes: the commits of Tasks 1-7.
- Produces: `$D/final-pytest.txt`, and the G6 commit.

- [ ] **Step 1: Design review (controller; spec 6 step 3).**
  - Ask an Opus `design-reviewer` to review `git diff 6f16063..HEAD -- qwen-agent-workspace` against the spec, this plan's rulings and the Review Focus.
  - Fix every finding in a new commit on the owning task's files. Then re-run that task's Step 4 and Task 7 Step 4. If a fix changes a re-baselined value, apply a follow-up test-only commit through Task 7 Steps 2-6.

- [ ] **Step 2: Find the last pipeline commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sf-wt/qwen-agent-workspace
git log -1 --format='%H %s' -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py
```

Expected: one line. It is a 40-character SHA, then the subject of Task 6's commit, or of the Step 1 fix commit if that commit touched a `PIPELINE_FILES` entry. In Step 3, **SHA** means exactly those 40 characters, typed in place of the word `SHA`.

- [ ] **Step 3: Re-baseline test_mut26 (spec G6).**

**3.1.** Edit `tests/test_movie_ui_builder.py` (the comment): replace this text, which occurs exactly once:

```python
then to f7a38afc6d6ae9622b63dbf4ce939e362a05a7ad (speaker attribution).
```

with:

```python
then to f7a38afc6d6ae9622b63dbf4ce939e362a05a7ad (speaker attribution), then to SHA (shot prompt format).
```

**3.2.** Edit `tests/test_movie_ui_builder.py` (the baseline): replace this text, which occurs exactly once:

```python
    BASELINE = "f7a38afc6d6ae9622b63dbf4ce939e362a05a7ad"
```

with:

```python
    BASELINE = "SHA"
```

**3.3.** Run this command:

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sf-wt/qwen-agent-workspace
SHA=$(git log -1 --format=%H -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py)
grep -c "$SHA" tests/test_movie_ui_builder.py
grep -c "(speaker attribution), then to $SHA (shot prompt format)." tests/test_movie_ui_builder.py
grep -c "    BASELINE = \"$SHA\"" tests/test_movie_ui_builder.py
git diff --numstat -- tests/test_movie_ui_builder.py
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py -k mut26 2>&1 | tail -1
```

Expected, in order: `2`, `1`, `1`, then `2	2	qwen-agent-workspace/tests/test_movie_ui_builder.py`, then `1 passed, 11 deselected`. If any value differs, fix the Edit, not this command.

- [ ] **Step 4: Commit (test-only; spec 0.4 G6).**

```bash
git add tests/test_movie_ui_builder.py
git diff --cached --name-only    # expected: only qwen-agent-workspace/tests/test_movie_ui_builder.py
git commit -m "test(movie-ui): re-baseline mut26 to the shot prompt format pipeline commit" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: SK1, the full suite against the baseline (about 15 minutes).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/sf-baseline
cd $S/sf-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/final-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt; tail -1 $D/final-pytest.txt
diff <(grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt | sort) <(grep -E '^(FAILED|ERROR)' $D/final-pytest.txt | sort) && echo "same failures, same messages"
diff <(grep -E '^PASSED' $D/baseline-pytest.txt | sort) <(grep -E '^PASSED' $D/final-pytest.txt | sort) | grep '^<' || echo "no lost pass"
grep -c '^PASSED tests/test_shot_format.py::' $D/final-pytest.txt
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1
```

Expected:
- the final summary `2 failed, 1927 passed, 2 skipped`: the baseline's `2 failed, 1890 passed, 2 skipped` plus the 37 new tests;
- `same failures, same messages` (SK1), `no lost pass`, `37` and `OK 347/347`.

If `test_trt41a` failed in one run only, rerun it alone and record both results. Any other difference: stop and report.

- [ ] **Step 6: SK2, SK3, the unchanged files and the verbatim spec text.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/sf-wt/qwen-agent-workspace
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' story_engine.py character_lib.py bin/ltx-story-manifest tests/test_shot_format.py tests/test_movie_ui_builder.py; done
git diff 6f16063 -- story_engine.py character_lib.py bin/ltx-story-manifest | grep -E '^[+-]\s*(import|from) ' || echo "no import change"
git diff --name-only 6f16063 -- movie_ui_lib.py static bin/ltx-movie bin/judge-story bin/ltx-mlx-render tests/fixtures/writer_pacing | wc -l
python3 -B - <<'EOF'
import re
spec = open("docs/superpowers/specs/2026-10-28-shot-prompt-format-design.md", encoding="utf-8").read()
blocks = re.findall(r"```python\n(.*?)```", spec, re.S)
code = "".join(open(p, encoding="utf-8").read()
               for p in ("story_engine.py", "character_lib.py", "bin/ltx-story-manifest"))
verbatim = [0, 1, 2, 4, 5, 6, 7, 8, 9, 11, 12, 16, 18, 19, 21, 22, 23, 24, 25, 26, 27, 28, 29, 32,
            33, 34, 35, 36]
print("%d of %d spec code blocks verbatim" % (sum(blocks[i] in code for i in verbatim), len(verbatim)))
EOF
```

Expected, in order:
- `compiled 5` twice (SK2);
- `no import change` (SK3);
- `0` (spec 0.4 "Not changed", and the hockey fixtures);
- `28 of 28 spec code blocks verbatim`.

The spec blocks not checked verbatim are each explained in Plan rulings PR1, PR8 and CR1, or are list-nested fragments placed at their code indent: 3, 10, 13, 14, 15, 17, 20, 30, 31, 37 and 38.

- [ ] **Step 7: Hand-off (controller; not an executor step).**
  - Report the branch `sf-impl` and its commits.
  - Push and the merge into `qwen-agent-redteam` are a separate step that needs the user's approval.
  - Put the spec 6 PR note in the PR description.
  - The live checks below run after the merge.

---

## Post-merge: live acceptance and render A/B (coordinator only; spec 5; not a task and not a merge gate)

The coordinator runs these after the merge, never an implementer:
- They start the local story server, which loads a model on `:8177`, and they render. Both need the user's go-ahead.
- This Mac only, never macstudio. Never touch `:8178`. Never read `~/.zshenv` or `fleet.env`.
- Run them exactly as spec Section 5 writes them; this checklist is not a substitute.

- [ ] **Preconditions.** No render is running: `$S/accent2/.render.lock` is absent, and `pgrep -f ltx-mlx-render` prints nothing.
- [ ] **Setup.**
  - `R=$S/shotfmt-live` (new, empty).
  - Archive first: `mkdir -p $R/pre && cp -Rp $W/generated/stories/pin-* $W/generated/stories/hockey-* $R/pre/`.
  - Start the story server as the `vllm serve` line of `$S/attrib/run.sh`, and stop it with `bin/story-server stop` after the last run.
- [ ] **The before runs** (`sf0-*`) run with the workspace at `3970e96`, before the fast-forward. These are the nine configurations of spec 5.1, `ch3-a` through `hk3s`, story-only.
- [ ] **The before renders** (spec 5.4) of the pairs `sh2`, `ch3-a`, `hk2` and `hk1`: one at a time, and never with the story server up.
- [ ] **Fast-forward** the workspace to the reviewed commits (after the user approves the push and merge).
- [ ] **The after runs** (`sf1-*`), then `$R/measure_sf.py` exactly as spec 5.2, into `measure_before.txt` and `measure_after.txt`.
- [ ] **KPIs (spec 5.3) on `measure_after.txt`:**
  - K1: static ratio <= 0.35, and every run <= `ceil(panels/3)`.
  - K2-K5: 0 panels.
  - K6: `lines ok` True.
  - K7: exit 0 for all 9.
  - K8, with the CR1 wording:
    - `sf1-hk2` shows exactly one P19 ending `rerun with --force-story --panels 3 to keep it`, and `sf1-hk1` one ending `rerun with --force-story --panels 2 to keep it`.
    - Each also appears as a `Warning: plan: P19 ...` line in its run log.
    - `sf1-hk3s` shows P19 (`--panels 4`) exactly when its plan puts line 2 in beat 3.
    - No `sf1` pin run shows P19.
- [ ] **The after renders, and `$R/ab.html`** (spec 5.4). The user watches and listens. The outcome is recorded; it does not gate.
- [ ] **Report:** K1-K8 with both measure files, the recorded rows, the exit codes, the A/B page path and the PR note.

---

## Coverage

### Spec section to task

| Spec | Task(s) |
|---|---|
| 0.4 G1 (`story_engine.py`) | 1 (SF1-SF5), 2 (SF6-SF8), 3 (SF9-SF12, SF13a, SF13c, SF14), 4 (SF13b, SF13d-h), 5 (SF-A1) |
| 0.4 G2 (`character_lib.py`, SF15) | 3 (SF15c), 6 (SF15a-b) |
| 0.4 G3 (`bin/ltx-story-manifest`, SF16) | 6 |
| 0.4 G4 (`tests/test_shot_format.py`) | 1-6 (see the next table) |
| 0.4 G5 (re-baseline, test-only) | 7 |
| 0.4 G6 (`test_mut26`) | 8 steps 2-4 |
| 0.4 Not changed | 8 step 6 (`git diff` checks); SFT1a (`RECHECK_IDS`, `PLAN_FREE_IDS`); the gate's must-stay-green files in every task |
| 0.5 Out of scope | nothing built; SFT14 (c) pins byte-identity without a spoken panel |
| 0.6 SK1 | Before Task 1 step 4 (baseline), every Step 4 gate, 8 step 5 |
| 0.6 SK2, SK3 | `test_sft1_the_pipeline_files_compile_under_both_pythons`; every compile check; 8 step 6 |
| 0.6 SK4 | 1 (SFT2-SFT4) |
| 0.6 SK5 | 2 (SFT6), 3 (SFT7, SFT8), 4 (Review Focus 1) |
| 0.6 SK6 | 6 (SFT13, SFT14) |
| 0.6 SK7 | 3 (SFT10), 4 (SFT11, SFT19, SFT20) |
| 0.6 SK8 | 3 (SFT8, SFT9, SFT17) |
| 0.6 SK9 | 2 (SFT5), 3 (SFT12), 4 (Review Focus 3) |
| 0.6 SK10 | 3 (SFT17) |
| 0.6 SK11 | Post-merge checklist |
| D1-D3 | 1 |
| D4 | 2; D4's "only a fallback" also needs PR1 (2, 4) |
| D5 | 3 (detection, repair); 4 (re-ask) |
| D6 | 6 |
| D7 | 3 (detection); 4 (re-ask, trim) |
| D8 | 3 (parse time); 4 (round 0, critic) |
| D9 | 2 |
| D10 | 3 |
| D11 | 3 (check); 4 (trim, critic, merge) |
| D12 | 3 (SFT17; `RECHECK_IDS` unchanged) |
| D13 | 2 |
| SF1-SF5 | 1 steps 3.1-3.10 |
| SF6 | 2 steps 3.2-3.4, 3.18, 3.19 |
| SF7 | 2 steps 3.1, 3.5-3.12 |
| SF8 | 2 steps 3.13-3.15 |
| SF9, SF10, SF11 | 3 steps 3.1, 3.3-3.5 |
| SF12 | 3 steps 3.2, 3.5 |
| SF13a, SF13c | 3 steps 3.7, 3.9 |
| SF13b, SF13d-h | 4 steps 3.1-3.9 |
| SF14 | 3 steps 3.6-3.8 |
| SF15a-b | 6 steps 3.1-3.2 |
| SF15c | 3 steps 3.10-3.14 |
| SF16 | 6 steps 3.3-3.5 |
| SF-A1 | 5 steps 3.1-3.2 |
| 3 Interactions | plan retry unchanged (gate: `test_rst10`, SA tests); after the plan: 1 (SFT4 E2E), 5 (SFT25); round 0: 4 (SFT11, Review Focus 2); critic and code-only: 4 (SFT16, Review Focus 1); blocking: 4 (SFT11 c); recheck: 3 (SFT17), 5 (SFT25); manifest: 6 (SFT14); `--no-narration`: 1 (SFT2), 2 (SFT5); movie-ui/judge-story: the gate's must-stay-green files |
| 4.1 | 1-6 |
| 4.2 | the gate (1-6), 7 |
| 4.3 | the gate's must-stay-green files (1-7) |
| 5 | Post-merge checklist |
| 6 rollout | Before Task 1 (snapshot, worktree); 1-6 (feature commits); 7 (G5); 8 (review, G6, SK1-SK3) |

### Test IDs and their owning task (each is owned by exactly one task)

| IDs | Task |
|---|---|
| SFT1 (planner part, compile check), SFT2, SFT3 (coercion), SFT4 (unit, E2E), SFT22 | 1 |
| SFT1 (writer part), SFT3 (chained paste), SFT5, SFT6, SFT21 | 2 |
| SFT1 (check part), SFT7, SFT8, SFT9, SFT10, SFT12, SFT15, SFT17, SFT18, Review Focus 4, 5 | 3 |
| SFT1 (repair part), SFT11, SFT16, SFT19, SFT20, Review Focus 1, 2, 3 | 4 |
| SFT23, SFT24, SFT25 | 5 |
| SFT1 (audio part), SFT13, SFT14 | 6 |
| the G5 re-baseline | 7 |
| MUT26 (G6); SK1-SK3 measured; SK11 hand-off | 8 |

### Self-review

- **Spec coverage.** Every requirement (SF1-SF16, SF-A1) and every test (SFT1-SFT25) maps to a task in the tables above. G1-G6 and SK1-SK11 each have a step.
- **Placeholders.**
  - The only symbolic values are `$S`, `$WS` and `$D`, each defined in its block or in the house rules.
  - The word `SHA` in Task 8 Step 3 is the value Step 2 prints.
  - The contents of Task 7's `$D/rebaseline-spec.md` are produced by an Opus pass from measured diffs. This plan's author was not permitted to run the suite (see "Between tasks"). That one hand-off is deliberate, and it is the reason Task 7 has a classification step.
- **Type consistency.**
  - `panel_camera(ctx, plan, k)` is used by SF6 (`pasted_pieces`), SF7 (`build_panel_prompt`), SF9 (`_field_checks`), SF11 (`repair_action_text`) and the tests.
  - `REPAIR_NOTE` is the same `(k, id, name, Label, quoted)` format in SF11, SF13b and every test helper.
  - `format_problems(ctx, plan, part, k)` and `trim_format(ctx, plan, k, part)` take their arguments in the spec's (different) orders, and every call below uses those orders.
  - `cleanup_pieces(pasted, key)` takes the dict of `pasted_pieces` in both of its callers.
- **Review Focus.** Five inputs, each with a test in its owning task (Tasks 3 and 4).

## Plan rulings (where the spec's code and its own tests cannot both hold, or the spec needs a reading)

The **[defect]** rulings change behaviour from what the spec literally writes. The controller should confirm them with the user before Task 2 (PR1) and Task 4 (PR2).

1. **PR1 [defect]: the cleanup must not blank the planned camera sentence from the writer's own camera sentence.**
   - `parse_panel_reply` (`:2158`) and `apply_patches` (`:3297-3298`) pass the field's pasted sentences to `clean_writer`. Those include the planned `CAMERA_SENTENCES` sentence, and `character_lib._passage_spans` matches a passage without its full stop.
   - So the form the writer is told to use, "The camera pushes in — as the move completes, her face fills the frame.", is cut to "— as the move completes, her face fills the frame.". CM4 then sees no camera and appends the fallback.
   - The same happens for every key whose form begins with its fallback's words: push-in, pull-back, the pans and tilts, and static ("The camera stays static, holding ..."). The probe output is in "Execution handoff". It breaks SK5, D4 and SFT6 as written.
   - **Ruling:** a new helper, `cleanup_pieces(pasted, key)`, leaves the `CAMERA_SENTENCES` sentences out of the action field's cleanup list. It is used at both call sites (Task 2 step 3.16-3.17, Task 4 step 3.6). A writer who writes the fallback verbatim keeps it, and CM4 drops the pasted copy, so the field still has one camera sentence; its position is where the writer put it (R18).
   - `_recheck_writers` is left unchanged (D12; see Questions, Q1).
2. **PR2 [defect]: SFT20 contradicts SF9, SF10 and SF13b.**
   - `_cut_clause` cuts at the *last* boundary before the exit. In "... toward the lens, then pushes off and skates away from the camera." that boundary is " and ", so the trim leaves "..., then pushes off.", not "... toward the lens.".
   - "The camera holds on him as he recedes." names the planned static move ("holds" is in `CAMERA_MOVE_WORDS["static"]`), so `repair_action_text` removes nothing from panel 2. The N21 trim drops that sentence instead (its "recedes" is an exit, D7).
   - **Ruling:** Section 2 is normative, so SFT20 asserts what the code does: the cut text, the two N21 notes, an empty `format_problems` afterwards, and `repair_action_text` returning the text unchanged. Separately, it asserts the panel-1 "as he speaks." cut.
   - The outcome the spec wanted (the exit and the receding camera both gone) holds. Only "then pushes off." survives (Q2).
3. **PR3: `REFERENCE_SIX_GRAMS` has 138 members, not 129.** The ten segments give 19+11+13+19+9+10+11+26+18+2 = 138, all distinct. SFT1c asserts 138. SFT12's corpus guard still holds with 138: none occurs in the 44 files under `tests/fixtures/`.
4. **PR4: the spoken-line segment is not a substring of `FORMAT_REFERENCE`** (the reference has `"Forty years of mornings." After a breath, "Not one more."`). SFT12 asserts that the nine prose segments are substrings, and that the spoken segment's `line_words` equal the reference line's.
5. **PR5: SFT1's "`/usr/bin/python3 -m py_compile`"** writes `.pyc` files into the tree. The test instead runs `compile()` in a subprocess of each interpreter: the same syntax check, with no file written. When `/usr/bin/python3` is absent, only `sys.executable` is checked (the spec's "else skip").
6. **PR6: SFT1 and SFT3 are split by task** (SFT1a-e and the compile check; SFT3a, SFT3b), so that each task's constants are asserted by that task's tests.
7. **PR7: SFT17's story** is the recorded `hockey-2x145-f` story, copied into the temp story dir. The fixture files are not edited. Its panel 2 is E2's text, and its panel 1 has the speaking verb "as he speaks". SFT7's full-message row uses E2's two camera sentences in the writer's Motion (the facing sentence is pasted).
8. **PR8: lines over 100 columns.**
   - Three spec lines are wrapped with their words unchanged: the `@@CAMERA_RULE@@` fragment, the `SPEAKING_CAMERAS` comment and the `speaking_camera` docstring.
   - Spec blocks 24 and 30 each have one 101-102-column line. Block 24's `REFERENCE_SIX_GRAMS` line is kept verbatim; block 30's line is reached by PR1's change anyway.
9. **PR9: SF7's "Keep the source line breaks as they are" for `no_stills_prompt`.** The two literals keep their lines: the first ends "lighting and colour. " and the second starts "Name each character".
10. **PR10: placements.**
    - In file order: `_moves_camera`, SF9, SF10's `EXIT_RE`, SF-A1, `post_line_sentences`, `_other_actor`, SF11, `panel_camera`, `pasted_pieces`, `cleanup_pieces`.
    - `max_static` is placed right after `CAMERA_KEYS`.
    - SF12's block goes after `FORMAT_REFERENCE`.
    - SF13b goes after `GENERATION_CHECKS`.
11. **PR11: six feature commits** instead of spec 6's single feature commit, one per task. G5 and G6 stay separate test-only commits (Tasks 7, 8), as in the prior plans.
12. **PR12: approach B for the existing suite**, as justified in "Between tasks". R18 is added for PR1.
13. **PR13: test readings.**
    - **E2E replies.** SFT11 uses `SFT11_EXIT` and `SFT11_CLEAN` in a kyra/ronin shots run with free dialogue "We go now.". SFT25 uses two courier replies.
    - **Story ids:** `sf4`, `sf7`, `sf11a`-`sf11c`, `sfrf2`, `sf17`, `sf19`, `sf20`, `sf25`, `sf25b`, `sf14a`-`sf14e`.
    - **The fourth module.** SFT17 needs `ltx_movie._validate_story_md`, so `bin/ltx-movie` is loaded as `ltx_movie_for_shot_format`.
    - **SFT14 (d)'s argv** is written out, because `_manifest_argv` has no v2 `--image` mode.
    - **SFT12's "a 6-gram present"** is the concrete `"looks up from the empty ice"`.
    - **The header imports** (`base64`, `hashlib`, `re`) are used from Tasks 1, 2 and 3 on.
14. **CR1 (coordinator ruling, 2026-10-28):** `P19_NOTE` ends "rerun with --force-story --panels %d to keep it". Spec block 38 is applied with that one change (Task 5 step 3.1), and SFT25 and K8 use it.

## Questions for controller

1. **Q1 (PR1's re-check side).**
   - `_recheck_writers` still blanks the pasted fallback's words from a re-checked story. D12 forbids changing it, and re-check output for old stories must not change.
   - So re-checking a *new* shots story with an end-framed camera sentence can count the "— as the move completes, ..." remnant as an action sentence. That gives a non-blocking T2 warning on re-check, though never in generation.
   - Should a follow-on change pass `cleanup_pieces` there too? It would change no old story's hard list. This plan leaves it as the spec says.
2. **Q2 (PR2).** Should `_cut_clause` cut at the first boundary after the last sequence word ("then")? Then "then pushes off and skates away" goes as a whole. That is a design change for the spec author; this plan follows Section 2.
3. **Q3.** PR1 and PR2 are behaviour rulings on spec defects. Confirm them, or have the spec amended, before Task 2 and Task 4 start.

## Spec defects found (for the spec author)

1. PR1: the cleanup blanks the writer's form camera sentence (blocking for SK5 as written).
2. PR2: SFT20's expected trim text and its N20 assertion do not follow from SF9, SF10 and SF13b.
3. PR3: 129 six-grams should be 138.
4. PR4: "Every segment is a substring of `FORMAT_REFERENCE`" is false for the spoken-line segment.
5. SF7 says "Replace these four `KEY_LINE_TEMPLATES` entries" but shows three. The fourth is the `no_stills_prompt` substring edit, and SFT1 says "the three replaced entries".
6. SF16 (c) cites the help at `:184-187`. The `help=` string starts on `:183`.

## Execution handoff

Plan complete and saved to `qwen-agent-workspace/docs/superpowers/plans/2026-10-28-shot-prompt-format.md`.

**How it was checked.** Every Create and Edit block of Tasks 1-6 lives in one data file, and this plan's blocks are rendered from it. A script replayed them in order the way an executor applies them, on a scratch `git archive` export of `6f16063`: one trailing newline stripped, and an exactly-once check.
- **Edits.** Each old text occurred exactly once at its turn, and the replayed tree is byte-identical to the build tree.
- **Compile and imports.** Every changed file compiled under Python 3.9.6 and 3.13 after every task. The test module imported cleanly after every task, with 7, 12, 23, 31, 34 and 37 test functions.
- **Spec text.** The 28 spec blocks of Task 8 Step 6 occur verbatim. `FORMAT_REFERENCE`'s sha256 is the spec's `d2fe46c6...`, at 421 words and 2406 characters.
- **Probes.** The expected values were probed against the replayed code (plain Python, not pytest) with the fake agent and a temporary HOME: no server, no render.
  - Every SFT row was probed, plus Review Focus 1-5, the SFT4/SFT11/SFT25 runs, the SFT17 re-check, the SFT14 manifest runs and the corpus guard.
  - All matched the assertions written above, after PR1-PR4 and CR1.
  - The PR1 defect showed in the same probe: without `cleanup_pieces`, the writer's camera sentence was cut to "— as the move completes, her face fills the frame.".
- **Not run, as instructed.** Neither the existing suite nor the new test file was run. The existing-test failure list therefore comes from reading, and the per-task gate measures it.
- **Scratch.** Everything was written under `$S/sfplan/`, except for one slip. The spec author's `$S/shotfmt/hits.py` was edited by mistake and restored at once: same content, new mtime.

Please review the plan. Execution method: subagent-driven, as you specified. Sonnet `code-executor` implementers run Tasks 1-8 in `$S/sf-wt` on branch `sf-impl`, and a fresh Opus reviewer checks each task, then the whole branch. Does the plan capture what you want?
