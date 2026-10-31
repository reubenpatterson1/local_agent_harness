# Chained End Frames Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In chained mode the planner writes an end frame for every beat, each writer is told the frame its panel opens on and the frame it must land its camera clause on, five camera moves join the fixed list, a "standing still" end clause no longer trips the mixed-camera check, only spoken lines keep double quotes, and `bin/seam-report` (with the movie UI's Check seams) scores each panel's last frame against its planned end frame after the render.

**Architecture:**
- **`story_engine.py` (Tasks 1-4).**
  - Task 1: the camera keys and sentences (CE1), the M1 end-clause rule (CE2) and the quote rule (CE10).
  - Task 2: the planner side. `normalize_plan` keeps `end_frame` (CE3), the plan prompt gains `END_FRAME_RULE` and `PLAN_REFERENCE` (CE4, CE5), P22/P23/P24 (CE6), and the plan retry and drop (CE7).
  - Task 3: N23, the landing check, with its one round-0 re-ask, its advisory, and the check ids (CE9, CE12).
  - Task 4: the writer prompt's opens-on and ends-on lines (CE8), and the new `FORMAT_REFERENCE` with its N22 constants (CE11).
- **`bin/seam-report` (Task 5, new, stdlib only).** It reads `plan.json` and `clips/`, asks the story server's VLM over loopback HTTP, and writes `seam_report.json` and `seam_report.md` (CE13).
- **The movie UI (Task 6).**
  - `movie_ui_lib`: the `seams` job kind, `seams_argv` and `plan_has_end_frames`.
  - `movie_ui_server`: the 55th route `POST /api/stories/<id>/seams`, `check_seams` on `POST /api/jobs`, and the `end_frames`/`seams` keys of `GET /api/stories/<id>`.
  - The page: the Check seams button and the Seams box on the Stories tab, and the Compose checkbox (CE14, CE15).
- **Task 7** is the whole-branch review, then the ONE test-only re-baseline commit (spec Section 7, CR1-CR7), then CK1-CK7 and the hand-off.
- **Tests:**
  - New files: `tests/test_chained_end_frames.py` (CT1-CT16, CT29; Tasks 1-5), `tests/test_seam_report.py` (CT17-CT22, CT30; Task 5) and `tests/test_movie_ui_seams.py` (CT23-CT28; Task 6).
  - Five Review Focus pins.
  - In all, 71 test cases: 66 CT cases and 5 Review Focus pins.

**Tech Stack:**
- Python 3.13 (`python3` = `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`, pytest 8.3.4). Python 3.9.6 (`/usr/bin/python3`) is used for the compile check only. Every new and changed Python file runs on both.
- Everything is standard library only. The page is vanilla ES2017 with no modules, checked with `node --check` when `node` is installed (`/opt/homebrew/bin/node` on this Mac).
- Test helpers:
  - `tests/story_engine_testutil.py`: `make_ws`, `script_agent`, `agent_log`, `answer`, `make_ctx`, `plan_json`, `panel_json`, `set_story_env`, `make_character`;
  - `tests/movie_ui_testutil.py`: `set_home`, `make_stub_workspace`, `Running`, `api`, `make_job`, `dispatch`, `fields`, `stub_config`, `status_of`, `read_log`, `wait_until`, `kill_everything`.

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-10-30-chained-end-frames-design.md`, committed at `133edae` on `chain-endframes`.
- `133edae` is the spec rebased onto `d30c40f`, the merge of batch forks. The spec's code citations are at `574303a`.
  - `story_engine.py`, `character_lib.py` and every `bin/` file are unchanged between `574303a` and `d30c40f`, so the spec's `story_engine.py` line numbers hold.
  - The movie-UI files moved. This plan cites them at `133edae`. The route count is 54 there, so this plan's count is 55. `TABS` already holds `"batches"` and is unchanged.
- The user approved the design section by section (spec Status and 0.0). The spec is binding.
- This plan changes behaviour only where the spec's text and its own tests, or the repository's existing tests, cannot both hold. Each such case is a numbered ruling in "Plan rulings", marked **[defect]**. The other rulings fill a detail the spec leaves open and are marked **[reading]**.

## Global Constraints

From the spec, verbatim (section in brackets):

- [Status] "Every design choice is made here. Each choice the approved notes left open is marked **[spec choice]** with a one-line reason, and Section 11 lists them all. The implementer makes no design decisions."
- [0.3 Not changed] "`character_lib.py`, `bin/ltx-story-manifest`, `bin/ltx-mlx-render`, `bin/judge-clips`, `bin/ltx-movie`, `bin/story-server`, the `story.md` labels, `PLAN_MAX_CALLS`, `PANEL_MAX_CALLS`, `REPAIR_IDS`, `FORMAT_IDS`, `merge_repair`, `apply_patches`, `trim_format`, `DEFAULT_FIELDS`, `build_argv`, the `story_checks.json` shape, shots and no_stills planning (apart from the shared camera list, D2)."
- [0.4] "Automatic re-render of missed panels." and "Batch-fork jobs ([BF]) queue no seams job (they are not created through `POST /api/jobs`)." are out of scope.
- [0.5] "CE1-CE15 and CT1-CT30 are must-haves. Nothing else is built: no CLI flag on `bin/ltx-movie`, no threshold flag on `bin/seam-report`, no re-render."
- [D1] "Every reader uses `beat.get("end_frame", "")`."
- [D3] P22 and P24 "are computed in `plan_round` only and join `problems`, exactly as `line_assignment_problems` does (`:1442-1449`). They are **not** in `plan_checks`, so a state never holds them."
- [D7] "N23 is not in `FORMAT_IDS` or `REPAIR_IDS`, so patches, `merge_repair` and `trim_format` behave exactly as before."
- [D10] "an old story re-checks with the same rc, hard list and advisories, and composes the same manifest."
- [CE13] "`bin/seam-report`, mode 0755, `#!/usr/bin/env python3`, stdlib only, compiles under `/usr/bin/python3` (3.9)." "It writes nothing except the two report files."
- [CE15] "The [MUI] page rules still hold: no inline handlers or styles, no `prompt(`/`alert(`/`confirm(`/`eval(`, one `<script>`, and the `TABS` line is unchanged."
- [6 Conventions] "Each module docstring states that no test renders, reads the real HOME, or contacts a model server, a daemon, ffmpeg or the Anthropic API. The only server is the in-test 127.0.0.1 movie-UI server. The VLM, the LLM and ffmpeg are stubbed by monkeypatching `vlm_models`, `vlm_complete`, `last_frame_png` and `shutil.which`."
- [7 Rule] "After G1-G5, every existing test that changes outcome must be explained by a code below. Its assertions are updated to the new behaviour in the single test-only commit, whose body has one paragraph per changed file naming the tests and codes." "A failure that no code explains is an implementation defect: fix the code, not the test." "No test is deleted, and no assertion is weakened beyond the new behaviour. Recorded fixture artifacts under `tests/fixtures/writer_pacing/` are not edited."
- [7] The codes, verbatim:

| Code | Cause |
|---|---|
| CR1 | Camera keys (CE1): 14 sentences, the plan camera list without plain `tracking`, the longer P8 key list, `CAMERA_SPEAKING_SENTENCE`, `SPEAKING_CAMERAS`, `CAMERA_MOVE_WORDS`, `CAMERA_WRITER_FORMS` |
| CR2 | `FORMAT_REFERENCE`, its segments and terms (CE11): hash, length, `REF_PARTS`, six-gram count, the shot-1 camera key |
| CR3 | Chained plan prompt (CE4): `END_FRAME_RULE`, `end_frame` in the beat keys, `PLAN_REFERENCE` (which has braces) |
| CR4 | `N23` in `GENERATION_CHECKS` and `RECHECK_IDS` (CE12) |
| CR5 | P22 re-ask (CE7): a chained E2E whose scripted plan has no end frames makes a second plan call, which the fake agent answers with no envelope when its queue is empty; it also prints `plan: call 2 of 2` and the drop warning and writes `plan_reply_2.txt` |
| CR6 | `test_mut26` `BASELINE`: `story_engine.py` changes. The comment gains `, then to <feature sha> (chained end frames).` |
| CR7 | Route count: the merged base's count + 1 |

- [8] The KPIs, verbatim:

| # | KPI | Target | Verified by |
|---|---|---|---|
| CK1 | Newly planned chained beats with a valid end frame (stubbed planner that returns them on call 1 or 2) | 100% of beats in every saved plan with end frames; exhaustion leaves none, prints the warning, and rc is 0 | CT5, CT8, CT16 |
| CK2 | Chained panels whose camera clause covers the end frame (stubbed writer that lands) | 100%, zero N23 messages; a non-landing writer gets exactly one re-ask and then an advisory | CT10, CT11 |
| CK3 | Old stories | re-check with the same rc, hard and advisory lists, and the same manifest bytes | CT15, the CR "must pass unchanged" set |
| CK4 | The "standing still" end frame | survives the repair; "stays still and pushes in" is still N20 | CT12 |
| CK5 | Non-speech double quotes in any assembled prompt across the fixtures | 0 | CT13 |
| CK6 | seam-report verdicts and error cases | every row of CT17-CT22 | CT17-CT22 |
| CK7 | Full suite | same pre-existing failures (same tests, same messages); only the Section 7 re-baselines change, in ONE test-only commit | full run |

- [10 Rollout] "2. **Snapshot** (house rule) ... Record the full-suite pass count and pre-existing failures on the rebased base. 3. **Plan, then implement via SDD**, with no separate plan review. Commit 1 (feature): G1-G5. Commit 2 (tests only): G6, including `test_mut26` `BASELINE` = commit 1's sha. Run CK7 and the `/usr/bin/python3` compile checks. 4. **Opus review** of the diff against this spec; fix; re-run CK7." Commit 1 is split into one commit per task (Plan ruling R1). The review comes before the test-only commit, as in the prior plans (Task 7).
- [10 step 7] The live A/B is post-merge, on this Mac only, "not a merge gate; never two renders at once, never the story server during a render, never port 8178".

Controller rules, verbatim. Every task's requirements include them:

- Tests never use the real HOME, never render, and never contact servers (except an in-test 127.0.0.1 movie-UI server and in-test stubs).
- `bin/seam-report` tests use a stubbed VLM: a monkeypatched HTTP call or an in-test 127.0.0.1 stub, never the real story server.
- Never touch port 8178.
- Never read ~/.zshenv or fleet.env.
- No access to the macstudio host.
- Edit tool for tracked files.
- Never stage .DS_Store, .claude/, agent/__pycache__/, repo-root bin/, qwen-agent-workspace/bin/action-from-dir, pin-sh2.json, story_bible_pin-sh2.json or .superpowers/.
- Commit trailer "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>".
- Never push.

House rules (from the prior plans; every task's requirements include them):

- **Where work happens.**
  - This Mac only. Use no ssh, scp, rsync, curl or HTTP to any other host, and never touch macstudio. Use no network.
  - The movie-UI tests start servers on `127.0.0.1` inside the test; nothing else listens.
  - Never start, stop or contact a model server (`:8177`, `:8178`). Never render, train, or load a model. The only jobs that run are the stub workspace's tools and the copied `bin/seam-report` of CT28, which stops before any server contact.
  - Never cat, grep, read or source `~/.zshenv` or any `fleet.env`, and never print env values. Never read the real `~/.local/share`.
- **The checkout.** Never touch the main checkout `/Users/reubenpatterson/local_agent_harness`. Every command runs in the worktree `$S/chain-wt`, on branch `chain-endframes`. Never git stash, reset or check out other people's work.
- **Python.** Every new or changed file must run on Python 3.9.6 and 3.13. So use none of: the `match` statement, `X | Y` type expressions, the walrus operator, `str.removeprefix`, `zip(strict=)` and parenthesised context managers. The code blocks below use none of them.
- **Editing.**
  - Executors make every change to a tracked file with the Edit tool. Each new file is created with the Write tool in the step that names it, and edited with the Edit tool from then on.
  - Never use `rm`, `sed -i`, a redirect or a script to change a tracked file. The one `chmod` (Task 5) is on a new, untracked file.
- **Git.**
  - Stage only the paths a task names, and check `git diff --cached --name-only` before every commit.
  - Every commit command passes the trailer as its last `-m`. No task pushes. Push is a separate step that needs the user's approval.
- **Paths.**
  - `S` = `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`.
  - `WS` = `$S/chain-wt/qwen-agent-workspace`, and `D` = `$S/chain-baseline`.
  - The git root is `$S/chain-wt`, so `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix.
  - Run every command from `WS`. Shell variables do not persist between commands, so every block defines the variables it uses.
- **Code blocks** are copied byte for byte.
  - An Edit step's old text must occur exactly once in the file at that moment, with or without its last newline. If it does not, stop and report; do not adapt it.
  - Every Create, Edit and chmod below was replayed in order on a scratch copy of `133edae`'s `WS`. Each old text occurred exactly once at its turn (see "Execution handoff").
  - Some old and new texts hold non-ASCII characters: `—` (U+2014), `–` (U+2013), curly quotes `“ ” ’` and `é`. Copy them as they are.
  - Every old and new text ends at the end of a line. Task 7's fixture hunks hold single lines of about 2,300 characters (a plan prompt's beats line); copy each whole.
  - The `tests/test_seam_report.py` block is fenced with four backticks, because its text holds three (a fenced model reply in CT21). Copy the text between the fences.
- **The compile check** (Step 4 of each code task) is this command, with the task's Python files as `FILES`. Expected: two lines, `compiled N` for 3.9 and then for 3.13.

```bash
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' FILES; done
```

## Review Focus

These five inputs and failure modes are the ones most likely to reach a user first, and no CT row exercises them. Each is pinned by a test in the task that owns its code. The tests are named `test_review_focus_N_...` in this plan's new files.

1. **A report whose end frame or reason holds a `|`, a line break or non-ASCII text** (`café`, an em dash, `l’aube`).
   - The VLM's reason and missing phrases come back as free text, and a planner's end frame is free text too.
   - Expected: every table cell of `seam_report.md` has its `|` escaped and its whitespace collapsed, so the table keeps its columns; `seam_report.json` holds the exact UTF-8 text (no `\u` escapes); stdout shows the text unescaped.
   - Test: `test_review_focus_1_pipes_line_breaks_and_accents_in_the_report` (Task 5).
2. **A zero-byte `panel_02.chainseed.png`** (a render interrupted while it wrote the seed) that is newer than its clip.
   - Expected: a seed counts only when it is a non-empty file, so panel 1 is read from `clips/panel_01.mp4`, and the empty file is never sent to the VLM.
   - Test: `test_review_focus_2_an_empty_chainseed_never_stands_in_for_its_clip` (Task 5).
3. **A camera clause that differs from its end frame only in case and apostrophes** ("THE COURIER’S bicycle ... Harbour Wall ... left!" against "The courier's bicycle ... harbour wall ... left.").
   - The local model writes curly apostrophes and capitals freely.
   - Expected: N23 compares `line_words`, which lower-cases and straightens apostrophes, so the clause lands and no re-ask is spent.
   - Test: `test_review_focus_3_curly_apostrophes_and_capitals_still_land` (Task 3).
4. **A `seam_report.json` that is cut short** (a disk-full write, or an edit by hand).
   - Expected: `GET /api/stories/<id>` answers `seams: null`, so the Stories tab says "No seam report yet: press Check seams.", and Check seams still queues a new job (201).
   - Test: `test_review_focus_4_a_malformed_seam_report_reads_as_none` (Task 6).
5. **A Run all that fails validation with Check seams ticked.**
   - Expected: the 409 creates no job at all. No seams job is queued for a movie that does not exist.
   - Test: `test_review_focus_5_a_refused_run_all_queues_no_seams_job` (Task 6).

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `story_engine.py` | Modify (Tasks 1-4) | T1: `CAMERA_SENTENCES` (14), `PLAN_CAMERA_KEYS`, `CAMERA_SPEAKING_SENTENCE`, `SPEAKING_CAMERAS`, `CAMERA_MOVE_WORDS`, 5 `CAMERA_WRITER_FORMS`, `END_CLAUSE_RE`, `camera_head`, `end_clause`, `_DOUBLE_QUOTES`, `reserve_quotes`. T2: `END_FRAME_RULE`, the plan prompt, `normalize_plan`'s `end_frame`, `_named_ids`, `PLAN_REFERENCE_*`, `plan_reference`, P22/P23/P24, `drop_end_frames`, the retry and drop. T3: `END_FRAME_STOP_WORDS`, `end_frame_words`, `end_frame_detail`, `end_frame_landing_problems`, N23 in `_field_checks` and round 0, `GENERATION_CHECKS`, `RECHECK_IDS`. T4: `OPENS_ON_LINE`, `ENDS_ON_LINE`, `ENDS_ON_STATIC_LINE`, `build_panel_prompt`'s lines, `FORMAT_REFERENCE`, `REFERENCE_TERMS`, `REFERENCE_COPY_SEGMENTS`, `reference_copies`. |
| `bin/seam-report` | Create (Task 5), mode 0755 | The seam report (CE13). |
| `movie_ui_lib.py` | Modify (Task 6) | `job_vlm("seams")`, `seams_argv`, `plan_has_end_frames`. |
| `movie_ui_server.py` | Modify (Task 6) | The seams route, `_create_seams_job`, `create_compose_job(seams=)`, `_h_job_create`'s `check_seams`, `_h_story_seams`, `_h_story`'s two keys. |
| `static/movie-ui/index.html`, `app.js`, `app.css` | Modify (Task 6) | The Compose checkbox, the Check seams button, the Seams box, `showSeams`, `.seam-missed`. |
| `tests/test_chained_end_frames.py` | Create (Task 1), extend (Tasks 2-5) | CT1 (five parts), CT2-CT16, CT29, Review Focus 3. |
| `tests/test_seam_report.py` | Create (Task 5) | CT17-CT22, CT30, Review Focus 1, 2. |
| `tests/test_movie_ui_seams.py` | Create (Task 6) | CT23-CT28, Review Focus 4, 5. |
| `tests/test_story_engine.py`, `test_shot_format.py`, `test_dialogue.py`, `test_narrative_fidelity.py`, `test_pinned_cast.py`, `test_soft_panel_count.py`, `test_speaker_attribution.py`, `test_movie_ui_http.py`, `test_location_ui.py`, `test_movie_ui_builder.py`; `tests/fixtures/location/plan_prompt_{chained,chained_cast,shots}.txt`, `tests/fixtures/pinned_cast/uncast_{chained_lines,chained_seed,shots_lines}.txt` | Modify (Task 7 only) | The spec Section 7 re-baseline: 52 test edits and 10 fixture edits in one test-only commit. |

**Task split.** The spec's rollout makes one feature commit. This plan makes one commit per task (Plan ruling R1), so a reviewer can reject any one on its own diff:
- Task 1 is the camera list, the M1 rule and the quote rule.
- Task 2 is the planner.
- Task 3 is N23.
- Task 4 is the writer prompt and the format reference.
- Task 5 is `bin/seam-report`.
- Task 6 is the movie UI.
- Task 7 is the review, the test-only re-baseline and the KPIs.

**Order.** The quote rule (CE10) is in Task 1, because P23 (Task 2) reads `_DOUBLE_QUOTES` at call time. N23 (Task 3) comes before the new format reference (Task 4), because CT14 checks the reference's Motions with `end_frame_detail` (Plan ruling R2).

## Between tasks: the existing suite (approach B, and why)

**The choice.** Feature tasks do **not** edit existing tests. The spec (Section 7 and CK7) asks for ONE test-only commit after the feature. So the existing tests the feature changes stay red from the task that first breaks them until Task 7. Every other existing test must stay green in every task.

**Precision.** The list below was measured on the plan's replay, not read off the spec.
- After each of Tasks 1-4, the replay ran the 29 test files that load `story_engine.py`, `bin/ltx-movie` or `character_lib.py`; after Task 6, the 18 movie-UI and pipeline test files; after Task 7, all of them (see "Execution handoff").
- The spec's Section 7 list was written by reading. The measured list differs from it in both directions (Plan ruling R12):
  - Four tests the spec lists do not change at all, so they get no edit: `test_rst10_plan_retry_and_fatal_plan`, `test_rst37_budgets_and_the_wall_clock`, `test_nf28*` and `test_nf29*`.
  - Eight tests the spec does not name fail for a listed code. They are `test_rst26b` and `test_rst33` (CR5); `test_rst47`, `test_dlg12`, `test_nf12`, `test_spt4` and `test_sat9` (CR3); and `test_nf14` (CR5).
- `test_mut26` skips on the scratch copy, which is not a git checkout. In the worktree it fails from Task 1, when `story_engine.py` first changes.

| Code | First task | Tests |
|---|---|---|
| CR1 (and CR3 for the two prompt fixtures) | 1 | `test_rs4`, `test_rst14`, `test_pacing_camera_sentences_classify_as_before`, `test_sft1a`, `test_sft1b`, `test_sft2`, `test_nf16`, `test_pt2`, `test_ls1` |
| CR6 | 1 | `test_mut26` |
| CR3, CR5 | 2 | 18 tests (the T2 lines below) |
| CR4 | 3 | `test_sft1c` |
| CR2 | 4 | `test_sft12`, `test_sft13`, `test_sft21`, the shot-format `test_review_focus_3` |
| CR7 | 6 | `test_mut18`, `test_lu1` |

The expected-failure list, written to `$D/expected-failures.txt` in "Before Task 1" Step 3. A line is `T<first task> <node id> <codes>`.

```text
# chained end frames plan: existing tests expected to fail from the given task until Task 7
T1 tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged CR6
T1 tests/test_story_engine.py::test_rs4_constants CR1
T1 tests/test_story_engine.py::test_rst14_plan_checks CR1
T1 tests/test_story_engine.py::test_pacing_camera_sentences_classify_as_before CR1
T1 tests/test_shot_format.py::test_sft1a_planner_constants CR1,CR4
T1 tests/test_shot_format.py::test_sft1b_writer_constants CR1,CR2
T1 tests/test_shot_format.py::test_sft2_the_plan_prompt CR1
T1 tests/test_narrative_fidelity.py::test_nf16_the_speaking_coercion_table CR1
T1 tests/test_pinned_cast.py::test_pt2_fixed_cast_block_and_uncast_byte_identity CR1,CR3
T1 tests/test_location_story.py::test_ls1_without_locations_plan_prompts_and_plans_are_byte_identical CR1,CR3
T2 tests/test_story_engine.py::test_rst8_plan_prompt_matrix CR3
T2 tests/test_story_engine.py::test_rst57_reserved_sentence_in_the_plan_prompt CR3
T2 tests/test_story_engine.py::test_rst47_robust_dry_run CR3
T2 tests/test_story_engine.py::test_rst26b_critic_retry_and_code_only_round CR5
T2 tests/test_story_engine.py::test_rst33_stop_passed CR5
T2 tests/test_story_engine.py::test_rst39_outputs_and_layout CR5
T2 tests/test_story_engine.py::test_rst51_e2e_chained CR5
T2 tests/test_story_engine.py::test_rst55b_p13_forces_plan_call_2 CR5
T2 tests/test_dialogue.py::test_dlg12_plan_prompt_speaker_rule CR3
T2 tests/test_dialogue.py::test_dlg21_an_advisory_only_round_0_passes_untouched CR5
T2 tests/test_narrative_fidelity.py::test_nf12_the_plan_prompt CR3
T2 tests/test_narrative_fidelity.py::test_nf14_the_plan_retry_gate CR5
T2 tests/test_narrative_fidelity.py::test_nf32_no_narration_keeps_the_movie_silent CR5
T2 tests/test_narrative_fidelity.py::test_nf33_default_narration_with_the_fixed_plan CR5
T2 tests/test_pinned_cast.py::test_pt16_two_pinned_chained_every_line_spoken_by_c1 CR5
T2 tests/test_soft_panel_count.py::test_spt4_the_plan_prompt CR3
T2 tests/test_soft_panel_count.py::test_spt8_e2e_one_beat_added CR5
T2 tests/test_speaker_attribution.py::test_sat9_plan_prompt CR3
T3 tests/test_shot_format.py::test_sft1c_check_constants CR2,CR4
T4 tests/test_shot_format.py::test_sft12_reference_copies CR2,CR3
T4 tests/test_shot_format.py::test_sft13_the_composition_and_the_reference CR2
T4 tests/test_shot_format.py::test_sft21_the_reference_adds_exactly_its_own_length CR2
T4 tests/test_shot_format.py::test_review_focus_3_an_end_frame_in_the_references_words_falls_back CR2
T6 tests/test_movie_ui_http.py::test_mut18_every_api_route_needs_the_token CR7
T6 tests/test_location_ui.py::test_lu1_the_location_routes_need_the_token CR7
```

**Gate rule** (Step 4 of every code task):
1. Every new test passes. A new test is one in the three new files, or any test ID the baseline does not have.
2. The baseline failures fail with the same messages.
3. Every lost baseline pass is listed for a task at or before this one in `$D/expected-failures.txt`.
4. `tests/test_ltx_movie_offline.py` prints the same last line as at the baseline.

**When the gate prints `GATE STOP`:**
- The executor stops and reports the UNEXPECTED or NEW-TEST-FAIL IDs, together with the output of `python3 -B -m pytest -q -p no:cacheprovider --tb=short <ids>`.
- The controller has an Opus reviewer rule on each ID.
  - A lost pass that a CR code of this or an earlier task explains is appended as `T<N> <id> <codes> +gate`, and Task 7 needs a re-baseline edit for it.
  - Otherwise it is a defect in this task's code: the controller writes the exact fix, and the gate reruns.
- The list grows only in these two ways.

**Timing-sensitive tests unrelated to this plan.** These are `tests/test_fleet_tracing.py::test_trt41a_trace_cli_on_one_agent` and `tests/test_fleet_integration.py::test_t47_signatures_and_loopback_rules`.
- If the gate lists one of them as UNEXPECTED, rerun it alone with `python3 -B -m pytest -q -p no:cacheprovider <node id>`.
- If it passes alone, the controller appends `T<N> <node id> flaky` to `$D/expected-failures.txt`, and Task 7 rechecks it.

**Must stay green in every task** (spec Section 7, "Must pass unchanged"):
- `tests/test_ltx_story_manifest_chain.py` (including `test_v2_golden_byte_identical`), `tests/test_judge_clips.py`, `tests/test_character_lib.py`, `tests/test_ltx_mlx_render.py`;
- `tests/test_vlm_lifecycle.py::test_vl1_job_vlm`, `tests/test_location_ui.py::test_lu9_job_vlm_policy`, `tests/test_location_ui.py::test_lu13_the_static_page`;
- `tests/test_dialogue.py::test_dlg15_assembly_goldens_and_dedupe`, `tests/test_story_engine.py::test_rst16_panel_prompt`, `tests/test_story_engine.py::test_rst18_assembly_goldens`;
- every recheck test, `tests/test_writer_pacing.py`, `tests/test_movie_ui_batch.py` (BT1: no `DEFAULT_FIELDS` key is added) and `python3 tests/test_ltx_movie_offline.py`.

None of them is in the list, so a failure there stops the gate.

---

## Before Task 1: the plan commit, the snapshot, the baseline (controller; no code)

- [ ] **Step 1: Commit this plan and confirm the tree.**

The controller commits this plan on `chain-endframes` as `docs(plan): chained end frames implementation plan`, directly on top of the spec commit `133edae`.

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/chain-wt/qwen-agent-workspace
git branch --show-current                                   # expected: chain-endframes
git log -3 --format=%h' '%s                                 # expected: <plan sha> docs(plan): ..., then 133edae docs(spec): ..., then d30c40f Merge pull request #3 ...
git diff --stat d30c40f HEAD -- . ':(exclude)docs' | tail -1   # expected: no output
git status --short                                          # expected: no output
ls bin/seam-report tests/test_chained_end_frames.py tests/test_seam_report.py tests/test_movie_ui_seams.py 2>&1 | grep -c "No such file"   # expected: 4
grep -c "44beb3d67ad5af05093e29e1c6fc088330b41386" tests/test_movie_ui_builder.py   # expected: 2
git diff --quiet 44beb3d67ad5af05093e29e1c6fc088330b41386 HEAD -- story_engine.py character_lib.py bin/ltx-movie bin/ltx-story-manifest && echo "pipeline files at the mut26 baseline"
wc -l story_engine.py movie_ui_lib.py movie_ui_server.py static/movie-ui/index.html static/movie-ui/app.js static/movie-ui/app.css tests/test_story_engine.py tests/test_shot_format.py tests/test_dialogue.py tests/test_narrative_fidelity.py tests/test_pinned_cast.py tests/test_soft_panel_count.py tests/test_speaker_attribution.py tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_builder.py | tail -17
```

Expected:
- `pipeline files at the mut26 baseline` (batch forks left `test_mut26`'s `BASELINE` at `44beb3d`, so CR6 re-baselines from there);
- the `wc -l` counts (at `133edae`): `story_engine.py` 5046, `movie_ui_lib.py` 2285, `movie_ui_server.py` 2798, `index.html` 389, `app.js` 2345, `app.css` 98, `test_story_engine.py` 3005, `test_shot_format.py` 1532, `test_dialogue.py` 2112, `test_narrative_fidelity.py` 1443, `test_pinned_cast.py` 742, `test_soft_panel_count.py` 1474, `test_speaker_attribution.py` 892, `test_movie_ui_http.py` 1792, `test_location_ui.py` 425, `test_movie_ui_builder.py` 296.

If any value differs, stop and report: every Edit below was written against this tree.

- [ ] **Step 2: Take the compressed snapshot (house rule; spec 10 step 2).**

The spec's command archives the main checkout. The house rule forbids touching it, and the worktree's `WS` is the same tree, so the snapshot is taken from the worktree (Plan ruling R16).

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
tar czf $S/snapshot-pre-chained-end-frames.tgz --exclude qwen-agent-workspace/generated -C $S/chain-wt qwen-agent-workspace
tar tzf $S/snapshot-pre-chained-end-frames.tgz | grep -c '^qwen-agent-workspace/story_engine.py$'   # expected: 1
```

- [ ] **Step 3: Record a fresh baseline and write the gate files (about 18 minutes; spec 10 step 2).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/chain-baseline
mkdir -p $D
cd $S/chain-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
grep -c '^PASSED ' $D/baseline-pytest.txt
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1 | tee $D/baseline-offline.txt
```

Expected: the plan did not run the full suite at `133edae`.
- Batch forks' final full run, at `9c877fb` (the same code tree as `d30c40f` and `133edae`), gave `2 failed, 2206 passed, 2 skipped`. Its two failures were `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`, and its offline line was `OK 347/347`.
- Whatever this run records **is** the baseline (CK7). Report its summary line, its `FAILED`/`ERROR` lines, the pass count and the offline line. Every later "baseline" in this plan means these files.

Then write two scratch files with the Write tool. They are outside the repository and never staged.

1. `$D/expected-failures.txt`: exactly the `text` block of "Between tasks" above.
2. `$D/gate.py`. It is `$S/bulk-baseline/gate.py` (batch forks' gate) with its docstring and `NEW_FILES` changed to name this plan's three new test files; the rest is unchanged:

```python
"""The task gate of the chained end frames plan: a full pytest -rA run against the baseline. Adapted
from the batch forks plan's gate: a new test is one of the three new test files or any test ID the
baseline does not have."""
import re
import sys

base_file, run_file, expected_file, task = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
NEW_FILES = ("tests/test_chained_end_frames.py::", "tests/test_seam_report.py::",
             "tests/test_movie_ui_seams.py::")


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

**The gate block** (Step 4 of every code task; `N` is the task number). It is a full run of about 18 minutes, which may run in the background:

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/chain-baseline
N=1
cd $S/chain-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/task-$N-pytest.txt 2>&1; tail -1 $D/task-$N-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/task-$N-pytest.txt $D/expected-failures.txt $N
diff <(python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1) $D/baseline-offline.txt && echo "offline unchanged"
```

Expected: `GATE PASS`, `new tests <count>, not passing 0`, `baseline failures still failing B of B` (B = the baseline's failure count), and `offline unchanged`. Each task's Step 4 gives its count and its `LOST ... listed` total. On `GATE STOP`, follow the gate rule ("Between tasks").

---
### Task 1: Camera keys, the M1 end-clause rule and the quote rule (CE1, CE2, CE10; CT1 part, CT12, CT13, CT29)

This task implements:
- CE1: the 14 `CAMERA_SENTENCES`, `PLAN_CAMERA_KEYS` (every key but plain `tracking`) in the plan prompt's camera list, `CAMERA_SPEAKING_SENTENCE`, `SPEAKING_CAMERAS` (the two tracking keys join), `CAMERA_MOVE_WORDS` and the five new `CAMERA_WRITER_FORMS` entries.
- CE2: `END_CLAUSE_RE`, `camera_head`, `end_clause`, and `_mixed_camera`/`_names_camera` reading only the head.
- CE10: `_DOUBLE_QUOTES`, `reserve_quotes`, and `panel_fields` writing the writer's action text with apostrophes.

Tests: CT1 (Task 1 part), CT12, CT13 and CT29 in the new `tests/test_chained_end_frames.py`. The file's imports of `copy`, `hashlib`, `shutil` and `subprocess`, and its helpers `ref_ctx`, `ef_plan`, `END_FRAME` and `REF_NARRATIVE`, are for the parts Tasks 2-5 append.

**Files:**
- Create: `tests/test_chained_end_frames.py`.
- Modify: `story_engine.py`:
  - `CAMERA_SENTENCES`/`CAMERA_KEYS` `:44-57`, `CAMERA_SPEAKING_SENTENCE` `:410-412`, the `@@CAMERA_LIST@@` fragment `:1130`, `SPEAKING_CAMERAS` `:1345`;
  - `CAMERA_MOVE_WORDS` `:1695-1706`, `_camera_words` `:1716-1718` (the new code follows it), `_mixed_camera`/`_names_camera` `:1735-1743`;
  - `CAMERA_WRITER_FORMS` `:2751-2752` and `:2761-2762` (insertions), `panel_fields` `:2915-2938`.
- Read only: `character_lib.py` `_is_camera_sentence` `:1028`; `bin/ltx-story-manifest` (CT13's manifest run).

**Interfaces:**
- Consumes (existing): `CAMERA_MOTION_RE`, `STATIC_CAMERA_WORDS`, `_camera_words(sentence)`, `camera_problem(lib, text, phrases, key)`, `repair_action_text(ctx, plan, k, text) -> (text, notes)`, `panel_fields(ctx, plan, parts, k) -> [(Label, text)]`, `assemble(ctx, plan, parts) -> str`, `panel_checks(ctx, plan, parts, text, path) -> (hard, advisory)`, `REPAIR_NOTE`.
- Produces (later tasks use these names exactly):
  - `PLAN_CAMERA_KEYS` (tuple of 13 keys);
  - `END_CLAUSE_RE`, `camera_head(sentence) -> str`, `end_clause(sentence) -> str` (`""` when there is no clause);
  - `_DOUBLE_QUOTES = ('"', "“", "”")`, `reserve_quotes(text) -> str`.
  - In the test file: `REAL_HOME`, `REF_NARRATIVE`, `END_FRAME` (a `%d` template, 20 words), `ref_ctx(ws, **kw)`, `ef_plan(n, mode="chained") -> raw plan dict`, `_normalized(ctx, raw) -> plan`, `_read_json(path)`, the fixtures `story_env` and `ws`, and the module objects `se`, `lib`, `story_manifest`, `ltx_movie`.

- [ ] **Step 1: Write the failing tests.**

Create `tests/test_chained_end_frames.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""Tests for chained end frames (docs/superpowers/specs/2026-10-30-chained-end-frames-design.md,
Section 6: CT1-CT16 and CT29, with the plan's Review Focus pin 3): five camera moves join the
fixed list, words after "as the move completes" or "holding" no longer make a camera sentence
mixed (M1), double quotes in a writer's action text become apostrophes, the chained planner
writes an end frame for every beat (P22, P23, P24 and the plan reference), writer k is told the
frame it opens on and the frame it ends on, and its camera clause must land on the planned end
frame (N23).

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_chained_end_frames.py
Stdlib plus pytest. No test renders, reads the real HOME, or contacts a model server, a daemon,
ffmpeg or the Anthropic API: every model call goes to the fake bin/qwen-agent of a temp workspace
(story_engine_testutil.make_ws and script_agent), every ctx lives under tmp_path, and every test
runs under the autouse story_env fixture (a temporary HOME, character library and LoRA catalog).
"""

import base64
import copy
import glob
import hashlib
import importlib.machinery
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


lib = _load("character_lib_for_chained_end_frames", "character_lib.py")
se = _load("story_engine_for_chained_end_frames", "story_engine.py")
story_manifest = _load("ltx_story_manifest_for_chained_end_frames",
                       os.path.join("bin", "ltx-story-manifest"))
ltx_movie = _load("ltx_movie_for_chained_end_frames", os.path.join("bin", "ltx-movie"))

# Captured at import, before any fixture sets HOME (CT29).
REAL_HOME = os.path.expanduser("~")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


# --- Test data (spec Section 6) ----------------------------------------------------------------

REF_NARRATIVE = ('At dawn the old fishmonger drags her empty herring crates to the shutter of the '
                 'market hall. At the zinc counter she says, "Forty years of mornings." After a '
                 'breath she says, "Not one more." She rests her head on her folded hands.')
END_FRAME = ("The courier stands at frame centre on the wet quay, facing the camera, seen from the "
             "waist up, beat %d.")
QUOTE_TEXT = 'The courier reads the "urgent" note and the “closed” sign.'
# A valid 1x1 PNG: bin/ltx-story-manifest only checks that each panel still opens.
PNG_1X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
                           "60e6kgAAAABJRU5ErkJggg==")


def ref_ctx(ws, **kw):
    """The reference movie's ctx: chained, 3 panels of 145 frames, --speech-only, REF_NARRATIVE,
    no auto LoRA; keyword arguments replace fields."""
    fields = dict(mode="chained", panels=3, narration="speech", clip_seconds=145 / 24.0,
                  narrative=REF_NARRATIVE, auto_lora=False)
    fields.update(kw)
    return seu.make_ctx(se, ws, **fields)


def ef_plan(n, mode="chained"):
    """EF_PLAN(n): seu.plan_json(mode, n) with beat k's end_frame END_FRAME % k (20 words)."""
    raw = seu.plan_json(mode, n)
    for k, beat in enumerate(raw["beats"], start=1):
        beat["end_frame"] = END_FRAME % k
    return raw


def _normalized(ctx, raw):
    plan, shape = se.normalize_plan(ctx, raw)
    assert shape == []
    return plan


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _ronin_plan(ws, camera, **ctx_kw):
    """(ctx, plan) of a 1-beat chained plan whose cast c1 is "the ronin" and whose camera is
    camera."""
    ctx = seu.make_ctx(se, ws, panels=1, **ctx_kw)
    raw = seu.plan_json("chained", 1, cast=[{"id": "c1", "phrase": "the ronin",
                                             "descriptor": seu.DESC_R}])
    raw["beats"][0]["camera"] = camera
    return ctx, _normalized(ctx, raw)


# --- CT29: no server and no real HOME (spec Section 6 conventions) -----------------------------

def test_ct29_no_server_and_no_real_home(story_env, tmp_path):
    assert os.path.expanduser("~") == story_env["home"]
    assert os.path.expanduser("~") != REAL_HOME
    assert story_env["home"].startswith(str(tmp_path))
    assert os.environ["QWEN_AGENT_DAEMON_URL"].startswith("http://127.0.0.1:")
    assert "ANTHROPIC_API_KEY" not in os.environ


# --- CT1 (Task 1 part): the camera constants (CE1, CE2) ----------------------------------------

CAMERA_SENTENCES = (
    ("slow push-in", "The camera pushes in."),
    ("slow pull-back", "The camera pulls back."),
    ("tracking", "The camera tracks alongside the movement."),
    ("slow tracking left", "The camera tracks left alongside the movement."),
    ("slow tracking right", "The camera tracks right alongside the movement."),
    ("handheld", "The camera is handheld, with slight natural movement."),
    ("slow pan left", "The camera pans left."),
    ("slow pan right", "The camera pans right."),
    ("slow tilt up", "The camera tilts up."),
    ("slow tilt down", "The camera tilts down."),
    ("slow crane up", "The camera cranes up."),
    ("slow crane down", "The camera cranes down."),
    ("slow orbit", "The camera arcs around the subject in a partial orbit."),
    ("static", "The camera stays static."),
)
PLAN_CAMERA_KEYS = ("slow push-in", "slow pull-back", "slow tracking left", "slow tracking right",
                    "handheld", "slow pan left", "slow pan right", "slow tilt up",
                    "slow tilt down", "slow crane up", "slow crane down", "slow orbit", "static")
CAMERA_SPEAKING_SENTENCE = (" On a beat with a speaker, prefer slow push-in, slow pull-back, "
                            "slow tracking left, slow tracking right or handheld, and never use a "
                            "pan, a tilt, a crane or an orbit, which sweep the speaker's face out "
                            "of the frame.")
SPEAKING_CAMERAS = ("slow push-in", "slow pull-back", "tracking", "slow tracking left",
                    "slow tracking right", "handheld", "static")
TRACK_WORDS = ("track", "tracks", "tracking", "follow", "follows", "dolly", "dollies")
CAMERA_MOVE_WORDS = {
    "slow push-in": ("push in", "pushes in", "push-in", "dolly", "dollies", "zoom", "zooms"),
    "slow pull-back": ("pull back", "pulls back", "pull-back", "dolly", "dollies", "zoom",
                       "zooms"),
    "tracking": TRACK_WORDS,
    "slow tracking left": TRACK_WORDS,
    "slow tracking right": TRACK_WORDS,
    "handheld": ("handheld",),
    "slow pan left": ("pan", "pans"),
    "slow pan right": ("pan", "pans"),
    "slow tilt up": ("tilt", "tilts"),
    "slow tilt down": ("tilt", "tilts"),
    "slow crane up": ("crane", "cranes"),
    "slow crane down": ("crane", "cranes"),
    "slow orbit": ("orbit", "orbits"),
    "static": ("static", "still", "hold", "holds", "locked-off"),
}
NEW_WRITER_FORMS = {
    "slow tracking left": ("tracks left", "'The camera tracks left alongside <whom it follows> — "
                                         "as the move completes, <where the frame ends>.'"),
    "slow tracking right": ("tracks right", "'The camera tracks right alongside <whom it follows> "
                                            "— as the move completes, <where the frame ends>.'"),
    "slow crane up": ("cranes up", "'The camera cranes up — as the move completes, <what the "
                                   "frame ends on>.'"),
    "slow crane down": ("cranes down", "'The camera cranes down — as the move completes, <what "
                                       "the frame ends on>.'"),
    "slow orbit": ("arcs around the subject in a partial orbit", "'The camera arcs around <whom it "
                   "circles> in a partial orbit — as the move completes, <where the frame "
                   "ends>.'"),
}


def _form_sentence(form):
    """A CAMERA_WRITER_FORMS form as a sentence: its quotes off and every <...> part made "x"."""
    return re.sub(r"<[^<>]*>", "x", form.strip("'"))


def test_ct1a_the_camera_constants():
    assert se.CAMERA_SENTENCES == CAMERA_SENTENCES
    assert se.CAMERA_KEYS == tuple(key for key, _sentence in CAMERA_SENTENCES)
    assert se.PLAN_CAMERA_KEYS == PLAN_CAMERA_KEYS
    assert se.CAMERA_SPEAKING_SENTENCE == CAMERA_SPEAKING_SENTENCE
    assert se.SPEAKING_CAMERAS == SPEAKING_CAMERAS
    assert se.CAMERA_MOVE_WORDS == CAMERA_MOVE_WORDS
    for key, value in NEW_WRITER_FORMS.items():
        assert se.CAMERA_WRITER_FORMS[key] == value, key
    assert set(se.CAMERA_WRITER_FORMS) == set(se.CAMERA_KEYS) == set(se.CAMERA_MOVE_WORDS)
    for key, sentence in se.CAMERA_SENTENCES:
        for text in (sentence, _form_sentence(se.CAMERA_WRITER_FORMS[key][1])):
            assert lib._is_camera_sentence(text, ["the courier"]), (key, text)
            assert se._names_camera(text, key), (key, text)
            assert not se._mixed_camera(text), (key, text)
    for text in ([sentence for _key, sentence in CAMERA_SENTENCES] + [CAMERA_SPEAKING_SENTENCE]
                 + [move + " " + form for move, form in NEW_WRITER_FORMS.values()]):
        assert "slowly" not in text.lower(), text


# --- CT12: M1, the end clause is not camera language (CE2, CK4) --------------------------------

def test_ct12_a_standing_still_end_frame_survives_the_repair(ws):
    ctx, plan = _ronin_plan(ws, "slow push-in")
    phrases = se.cast_phrases(ctx, plan)
    text = ("The ronin runs to the wall. The camera pushes in — as the move completes, the ronin "
            "stands still at the right edge.")
    assert se.repair_action_text(ctx, plan, 1, text) == (text, [])
    assert se.camera_problem(lib, text, phrases, "slow push-in") is None
    sentence = "The camera pushes in — as the move completes, the ronin stands still at the right edge."
    assert se.camera_head(sentence) == "The camera pushes in — "
    assert se.end_clause(sentence) == "the ronin stands still at the right edge"
    assert (se.camera_head("The camera pushes in."), se.end_clause("The camera pushes in.")) == (
        "The camera pushes in.", "")
    assert not se._mixed_camera(sentence) and se._names_camera(sentence, "slow push-in")


def test_ct12_stays_still_and_pushes_in_is_still_mixed(ws):
    ctx, plan = _ronin_plan(ws, "slow push-in")
    phrases = se.cast_phrases(ctx, plan)
    mixed = "The ronin runs to the wall. The camera stays still and pushes in."
    detail = se.camera_problem(lib, mixed, phrases, "slow push-in")
    assert "has the camera both stay still and move" in detail
    assert se.repair_action_text(ctx, plan, 1, mixed) == (
        "The ronin runs to the wall.",
        [se.REPAIR_NOTE % (1, "N20", "camera direction", "Motion",
                           "'The camera stays still and pushes in.'")])


def test_ct12_static_holding_and_the_head_rule(ws):
    ctx, plan = _ronin_plan(ws, "static")
    phrases = se.cast_phrases(ctx, plan)
    held = ("The ronin runs to the wall. The camera stays static, holding the ronin as he stands "
            "still at the right edge.")
    assert se.camera_problem(lib, held, phrases, "static") is None
    assert se.repair_action_text(ctx, plan, 1, held) == (held, [])
    pushed = ("The ronin runs to the wall. The camera pushes in — as the move completes, she holds "
              "still at the right edge.")
    assert "does not move the camera the planned way" in se.camera_problem(lib, pushed, phrases,
                                                                           "static")


# --- CT13: quotes reserved for spoken lines (CE10, CK5) ----------------------------------------

def _quote_parts(mode, n=2):
    """seu.panel_json parts for n panels, the action text of every panel QUOTE_TEXT plus the usual
    words, and panel 2 saying "Go now." when it speaks."""
    key = "prompt" if mode == "no_stills" else "motion"
    parts = []
    for k in range(1, n + 1):
        part = seu.panel_json(mode, k)
        part[key] = QUOTE_TEXT + " " + part[key]
        parts.append(part)
    parts[1]["dialogue"] = "Go now."
    return parts


def _speaking(ctx, n=2):
    raw = seu.plan_json(ctx.mode, n)
    raw["beats"][1]["speaker"] = "c1"
    return _normalized(ctx, raw)


def test_ct13_writer_double_quotes_become_apostrophes(ws, tmp_path):
    for mode in ("chained", "shots", "no_stills"):
        ctx = seu.make_ctx(se, ws, mode=mode, panels=2, story_id="q-" + mode.replace("_", "-"))
        plan = _speaking(ctx)
        parts = _quote_parts(mode)
        label = "Prompt" if mode == "no_stills" else "Motion"
        for k in (1, 2):
            fields = dict(se.panel_fields(ctx, plan, parts, k))
            assert "'urgent'" in fields[label] and "'closed'" in fields[label], (mode, k)
            assert not any(q in fields[label] for q in ('"', "“", "”")), (mode, k)
        assert dict(se.panel_fields(ctx, plan, parts, 2))["Dialogue"] == "the courier: Go now."
        assert se.reserve_quotes(QUOTE_TEXT) == "The courier reads the 'urgent' note and the 'closed' sign."
    ctx = seu.make_ctx(se, ws, mode="chained", panels=2, story_id="q-checks")
    plan = _speaking(ctx)
    parts = _quote_parts("chained")
    text = se.assemble(ctx, plan, parts)
    path = os.path.join(str(tmp_path), "q-checks.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    _hard, advisory = se.panel_checks(ctx, plan, parts, text, path)
    assert "panel 1: N7 dialogue and text: Motion: contains a double quote" in advisory


def test_ct13_the_manifest_keeps_only_the_spoken_line_quoted(ws, tmp_path, monkeypatch):
    ctx = seu.make_ctx(se, ws, mode="chained", panels=2, story_id="q-story")
    plan = _speaking(ctx)
    text = se.assemble(ctx, plan, _quote_parts("chained"))
    mws = tmp_path / "mws"
    mws.mkdir()
    for name in ("character_lib.py", "lora_catalog.py"):
        os.symlink(os.path.join(WS, name), str(mws / name))
    monkeypatch.setattr(story_manifest, "WS", str(mws))
    story_dir = mws / "generated" / "stories" / "q-story"
    story_dir.mkdir(parents=True)
    (story_dir / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    story_md = tmp_path / "q-story.md"
    story_md.write_text(text, encoding="utf-8")
    image = tmp_path / "q-story_01.png"
    image.write_bytes(PNG_1X1)
    argv = ["--story-id", "q-story", "--prompts-md", str(story_md), "--chain", "--image",
            str(image), "--fps", "24", "--target-seconds", repr(145 * 2 / 24.0), "--min-frames",
            "145", "--max-frames", "145", "--force"]
    assert story_manifest.main(argv) == 0
    prompts = [p["motion_prompt"] for p in _read_json(str(story_dir / "manifest.json"))["panels"]]
    assert [p.count('"') for p in prompts] == [0, 2]
    assert 'The courier says, "Go now."' in prompts[1]
    assert not any(q in p for p in prompts for q in ("“", "”"))


def test_ct13_the_fixture_parts_assemble_with_no_double_quote(ws):
    found = []
    for path in sorted(glob.glob(os.path.join(WS, "tests", "fixtures", "**", "parts.json"),
                                 recursive=True)):
        sibling = os.path.join(os.path.dirname(path), "plan.json")
        if not os.path.isfile(sibling):
            continue
        plan = _read_json(sibling)
        if plan.get("mode") not in ("chained", "shots"):
            continue
        found.append(os.path.basename(os.path.dirname(path)))
        parts = [dict((key, value) for key, value in p.items() if key != "index")
                 for p in _read_json(path)["panels"]]
        ctx = seu.make_ctx(se, ws, mode=plan["mode"], panels=len(plan["beats"]),
                           narration="speech", narrative=plan["narrative"], goal=plan["goal"],
                           story_id=found[-1])
        motions = [line for line in se.assemble(ctx, plan, parts).split("\n")
                   if line.startswith("Motion: ")]
        assert motions and not any(q in m for m in motions for q in ('"', "“", "”")), found[-1]
    assert found == ["hockey-1x241-f", "hockey-2x145-f"]
```

- [ ] **Step 2: Run the tests to verify they fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_chained_end_frames.py 2>&1 | tail -1
```

Expected: `5 failed, 3 passed`. The three that pass already pin behaviour this task keeps: `test_ct29_no_server_and_no_real_home`, `test_ct12_stays_still_and_pushes_in_is_still_mixed` (M1 must not unmix it) and `test_ct13_the_fixture_parts_assemble_with_no_double_quote` (no recorded writer text has a double quote today).

- [ ] **Step 3: Write the implementation.**

**3.1.** The camera sentences and keys (CE1). Edit `story_engine.py`: replace this text, which occurs exactly once:

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
```

with:

```python
# Shot prompt format spec SF1, D1; chained end frames spec CE1, D2: moves first, static last; the
# pasted sentence is the fallback when the writer writes no camera sentence (SF6).
CAMERA_SENTENCES = (
    ("slow push-in", "The camera pushes in."),
    ("slow pull-back", "The camera pulls back."),
    ("tracking", "The camera tracks alongside the movement."),
    ("slow tracking left", "The camera tracks left alongside the movement."),
    ("slow tracking right", "The camera tracks right alongside the movement."),
    ("handheld", "The camera is handheld, with slight natural movement."),
    ("slow pan left", "The camera pans left."),
    ("slow pan right", "The camera pans right."),
    ("slow tilt up", "The camera tilts up."),
    ("slow tilt down", "The camera tilts down."),
    ("slow crane up", "The camera cranes up."),
    ("slow crane down", "The camera cranes down."),
    ("slow orbit", "The camera arcs around the subject in a partial orbit."),
    ("static", "The camera stays static."),
)
CAMERA_KEYS = tuple(key for key, _ in CAMERA_SENTENCES)
# Chained end frames spec CE1, D2: the plan prompt offers every key but plain "tracking", so a
# new plan names the tracking direction; "tracking" stays valid for P8 and old plans.
PLAN_CAMERA_KEYS = tuple(key for key in CAMERA_KEYS if key != "tracking")
```

**3.2.** The speaking-camera sentence (CE1). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
CAMERA_SPEAKING_SENTENCE = (" On a beat with a speaker, prefer slow push-in, slow pull-back, "
                            "tracking or handheld, and never use a pan or a tilt, which sweeps "
                            "the speaker's face out of the frame.")
```

with:

```python
CAMERA_SPEAKING_SENTENCE = (" On a beat with a speaker, prefer slow push-in, slow pull-back, "
                            "slow tracking left, slow tracking right or handheld, and never use a "
                            "pan, a tilt, a crane or an orbit, which sweep the speaker's face out "
                            "of the frame.")
```

**3.3.** The plan prompt's camera list (CE1). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        ("@@CAMERA_LIST@@", ", ".join(CAMERA_KEYS)),
```

with:

```python
        ("@@CAMERA_LIST@@", ", ".join(PLAN_CAMERA_KEYS)),
```

**3.4.** The speaking cameras (CE1). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
SPEAKING_CAMERAS = ("slow push-in", "slow pull-back", "tracking", "handheld", "static")
```

with:

```python
SPEAKING_CAMERAS = ("slow push-in", "slow pull-back", "tracking", "slow tracking left",
                    "slow tracking right", "handheld", "static")
```

**3.5.** The move words (CE1). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
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
```

with:

```python
CAMERA_MOVE_WORDS = {
    "slow push-in": ("push in", "pushes in", "push-in", "dolly", "dollies", "zoom", "zooms"),
    "slow pull-back": ("pull back", "pulls back", "pull-back", "dolly", "dollies", "zoom",
                       "zooms"),
    "tracking": ("track", "tracks", "tracking", "follow", "follows", "dolly", "dollies"),
    "slow tracking left": ("track", "tracks", "tracking", "follow", "follows", "dolly",
                           "dollies"),
    "slow tracking right": ("track", "tracks", "tracking", "follow", "follows", "dolly",
                            "dollies"),
    "handheld": ("handheld",),
    "slow pan left": ("pan", "pans"),
    "slow pan right": ("pan", "pans"),
    "slow tilt up": ("tilt", "tilts"),
    "slow tilt down": ("tilt", "tilts"),
    "slow crane up": ("crane", "cranes"),
    "slow crane down": ("crane", "cranes"),
    "slow orbit": ("orbit", "orbits"),
    "static": ("static", "still", "hold", "holds", "locked-off"),
}
```

**3.6.** The end clause (CE2). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def _camera_words(sentence):
    """The CAMERA_MOTION_RE words of a sentence, lower case, whitespace collapsed, in order."""
    return [" ".join(m.group(0).lower().split()) for m in CAMERA_MOTION_RE.finditer(sentence)]
```

with:

```python
def _camera_words(sentence):
    """The CAMERA_MOTION_RE words of a sentence, lower case, whitespace collapsed, in order."""
    return [" ".join(m.group(0).lower().split()) for m in CAMERA_MOTION_RE.finditer(sentence)]


# Chained end frames spec CE2, D6 (M1): the words after "as the move completes" or "holding"
# describe the subject at the end frame, not the camera.
END_CLAUSE_RE = re.compile(r"\bas\s+the\s+move\s+completes\b|\bholding\b", re.IGNORECASE)


def camera_head(sentence):
    """The part of a camera sentence before its first END_CLAUSE_RE match, or the whole sentence
    when it has none (CE2)."""
    match = END_CLAUSE_RE.search(sentence)
    return sentence[:match.start()] if match else sentence


def end_clause(sentence):
    """The words of a camera sentence after its first END_CLAUSE_RE match, stripped of the
    characters " ,;:—–-.!?" at both ends, or "" when it has none (CE2, CE9)."""
    match = END_CLAUSE_RE.search(sentence)
    return sentence[match.end():].strip(" ,;:—–-.!?") if match else ""
```

**3.7.** `_mixed_camera` and `_names_camera` read the head (CE2). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def _mixed_camera(sentence):
    """True when a camera sentence both keeps the camera still and moves it."""
    words = _camera_words(sentence)
    return (any(w in STATIC_CAMERA_WORDS for w in words)
            and any(w not in CAMERA_MOVE_WORDS["static"] for w in words))


def _names_camera(sentence, key):
    return any(w in CAMERA_MOVE_WORDS[key] for w in _camera_words(sentence))
```

with:

```python
def _mixed_camera(sentence):
    """True when a camera sentence both keeps the camera still and moves it. Only the words before
    the end clause count (CE2, M1)."""
    words = _camera_words(camera_head(sentence))
    return (any(w in STATIC_CAMERA_WORDS for w in words)
            and any(w not in CAMERA_MOVE_WORDS["static"] for w in words))


def _names_camera(sentence, key):
    return any(w in CAMERA_MOVE_WORDS[key] for w in _camera_words(camera_head(sentence)))
```

**3.8.** The two tracking writer forms (CE1). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "tracking": ("tracks the movement", "'The camera tracks <whom it follows> — as the move "
                                        "completes, <where the frame ends>.'"),
```

with:

```python
    "tracking": ("tracks the movement", "'The camera tracks <whom it follows> — as the move "
                                        "completes, <where the frame ends>.'"),
    "slow tracking left": ("tracks left", "'The camera tracks left alongside <whom it follows> — "
                                         "as the move completes, <where the frame ends>.'"),
    "slow tracking right": ("tracks right", "'The camera tracks right alongside <whom it "
                                            "follows> — as the move completes, <where the frame "
                                            "ends>.'"),
```

**3.9.** The crane and orbit writer forms (CE1). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "slow tilt down": ("tilts down", "'The camera tilts down — as the move completes, <what the "
                                     "frame ends on>.'"),
```

with:

```python
    "slow tilt down": ("tilts down", "'The camera tilts down — as the move completes, <what the "
                                     "frame ends on>.'"),
    "slow crane up": ("cranes up", "'The camera cranes up — as the move completes, <what the "
                                   "frame ends on>.'"),
    "slow crane down": ("cranes down", "'The camera cranes down — as the move completes, <what "
                                       "the frame ends on>.'"),
    "slow orbit": ("arcs around the subject in a partial orbit", "'The camera arcs around <whom "
                   "it circles> in a partial orbit — as the move completes, <where the frame "
                   "ends>.'"),
```

**3.10.** `reserve_quotes` (CE10). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def panel_fields(ctx, plan, parts, k):
```

with:

```python
# Chained end frames spec CE10, D8: double quotes in a final video prompt are kept for the
# spoken line, so the writer's action text is written with apostrophes.
_DOUBLE_QUOTES = ('"', "“", "”")


def reserve_quotes(text):
    """text with every straight or curly double quote turned into an apostrophe (CE10)."""
    for quote in _DOUBLE_QUOTES:
        text = text.replace(quote, "'")
    return text


def panel_fields(ctx, plan, parts, k):
```

**3.11.** `panel_fields`'s docstring (CE10). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    writer text moves the camera, CM4; shot prompt format spec SF6), Dialogue: on a speaking panel
    ("<phrase>: <line>"), then Narration: when narration is True and the part is non-empty or the
    panel does not speak."""
```

with:

```python
    writer text moves the camera, CM4; shot prompt format spec SF6), Dialogue: on a speaking panel
    ("<phrase>: <line>"), then Narration: when narration is True and the part is non-empty or the
    panel does not speak; the writer's action text has its double quotes turned into apostrophes
    (chained end frames spec CE10)."""
```

**3.12.** `panel_fields` writes the action text with apostrophes (CE10). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    fields.append((LABELS[key], join([p.get(key, "")] + pieces)))
```

with:

```python
    fields.append((LABELS[key], join([reserve_quotes(p.get(key, ""))] + pieces)))
```

- [ ] **Step 4: Run the tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_chained_end_frames.py 2>&1 | tail -1
```

Expected: `8 passed`.

The compile check with `FILES` = `story_engine.py tests/test_chained_end_frames.py`. Expected: `compiled 2` twice.

The gate block with `N=1`. Expected: `GATE PASS`, `lost 10 (listed 10, unexpected 0); new tests 8, not passing 0`, and `offline unchanged`. The 10 are the T1 lines of the list, `test_mut26` included.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
git add story_engine.py tests/test_chained_end_frames.py
git diff --cached --name-only    # expected: only those 2 paths
git commit -m "feat(story-engine): five camera moves, the M1 end-clause rule and double quotes kept for spoken lines (chained end frames CE1, CE2, CE10; CT12, CT13)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 2: The planner: end frames in the plan, the plan reference, P22, P23, P24, the retry and the drop (CE3-CE7; CT1 part, CT2-CT8, CT16)

This task implements:
- CE3: `normalize_plan` keeps a chained beat's non-empty `end_frame`; the key is absent otherwise.
- CE4: the template gains `@@END_FRAME_RULE@@` and `@@PLAN_REFERENCE@@`; `END_FRAME_RULE`; `build_plan_prompt`'s `beat_keys` and the two fragments.
- CE5: `PLAN_REFERENCE_INTRO`, `PLAN_REFERENCE_LINES_CLAUSE`, `PLAN_REFERENCE_PLAN`, `_plan_reference_json`, `plan_reference`, `PLAN_REFERENCE_KEY_WORDS`, `PLAN_REFERENCE_SEGMENTS` and `PLAN_REFERENCE_SIX_GRAMS`, placed after `reference_copies`.
- CE6: `_named_ids` after `_mentions_at`; after `line_assignment_problems`, `END_FRAME_WORDS`, the P22/P24 messages, `END_FRAMES_DROPPED`, `plan_end_frame_problems`, `end_frame_advisories`, `plan_copy_problems` and `drop_end_frames`; P23 in `plan_checks`.
- CE7: `plan_round`'s `problems`, `go`'s fatal list (a P24 copy outside the end frames) and the drop after the last plan call.

The spec's code blocks are copied as they are. `end_frame_advisories` reads `_DOUBLE_QUOTES` (Task 1) and `cast_phrases`, `_first`, `_APPEARANCE_RE` and `DIALOGUE_RE` at call time. `plan_copy_problems` reads `REFERENCE_TERMS` at call time, so Task 4's `"half-open shutter"` reaches it.

Tests: CT1 (Task 2 part), CT2-CT8 and CT16, appended to `tests/test_chained_end_frames.py`. Its E2E helper `_e2e` also serves Task 3.

**Files:**
- Modify: `tests/test_chained_end_frames.py` (append).
- Modify: `story_engine.py`:
  - `PLAN_PROMPT_TEMPLATE` `:354-357`, the Task 1 `CAMERA_SPEAKING_SENTENCE` (the new rule follows it);
  - `build_plan_prompt` `:1115-1117` and `:1137-1142`, `_mentions_at` `:666-668`, `normalize_plan` `:1315`, `line_assignment_problems` `:1449`;
  - `plan_checks` `:2268`, `reference_copies` `:2587-2588`, `plan_round` `:4485`, `go` `:4685-4691` and `:4700`.

**Interfaces:**
- Consumes: Task 1's `CAMERA_MOVE_WORDS`, `_camera_words`, `_DOUBLE_QUOTES`; existing `line_words`, `_mentions`, `_q`, `speaker_phrase_of`, `CAMERA_CLAUSE_RE`, `_first`, `_APPEARANCE_RE`, `DIALOGUE_RE`, `cast_phrases`, `_six_grams`, `REFERENCE_TERMS`, `_clean_str`, `_words`, `json`, `copy`.
- Produces (later tasks use these names exactly):
  - `END_FRAME_RULE`; `plan_reference(lines) -> str`; `PLAN_REFERENCE_PLAN` (dict); `PLAN_REFERENCE_SIX_GRAMS` (68 runs);
  - `_named_ids(words, mentions) -> [cast id]`;
  - `END_FRAME_WORDS = (8, 30)`, `P22_MISSING`, `P22_LENGTH`, `P24_MESSAGE`, `END_FRAMES_DROPPED`;
  - `plan_end_frame_problems(ctx, plan) -> [str]`, `end_frame_advisories(ctx, lib, plan) -> [str]`, `plan_copy_problems(ctx, plan, end_frames=True) -> [str]`, `drop_end_frames(plan)`.
  - In the test file: `_e2e(ws, tmp_path, monkeypatch, plans, n=3, panel=None, **ctx_kw) -> (rc, agent log, saved plan.json or None, ctx)`, `_panel_replies(mode, n)`, `HERRING_ACTION`, `ZINC_FRAME`.

- [ ] **Step 1: Write the failing tests.**

Append to the test file. Edit `tests/test_chained_end_frames.py`: replace this text, which occurs exactly once:

```python
        assert motions and not any(q in m for m in motions for q in ('"', "“", "”")), found[-1]
    assert found == ["hockey-1x241-f", "hockey-2x145-f"]
```

with:

```python
        assert motions and not any(q in m for m in motions for q in ('"', "“", "”")), found[-1]
    assert found == ["hockey-1x241-f", "hockey-2x145-f"]


# --- CT1 (Task 2 part): the planner constants (CE4-CE7) ----------------------------------------

END_FRAME_RULE = (" end_frame is one sentence of 8 to 30 words, in the present tense, of the "
                  "frame the beat ends on: who or what is in frame, where each one is (left, "
                  "centre or right; foreground or background), which way they face and how tight "
                  "the shot is. It never names a camera move, the lighting, a colour or a style, "
                  "has no spoken words and no double quotes, and names only characters in the "
                  "beat's cast. Beat k's end frame is exactly where beat k+1 begins; write beat "
                  "k+1's action so it starts from that composition. The last beat's end frame "
                  "closes the story.")
PLAN_REFERENCE_INTRO = ("FORMAT REFERENCE ONLY — never reuse its people, places, objects or "
                        "words. This is the complete plan of a three-beat movie made as one "
                        "continuous take, a different story from this one.%s It shows the format "
                        "of every plan: each beat's end_frame says exactly where the beat ends, "
                        "the next beat's action starts from that end frame, and the last end "
                        "frame closes the story.\n")
PLAN_REFERENCE_LINES_CLAUSE = (' Its narrative quoted two spoken lines: 1 "Forty years of '
                               'mornings." and 2 "Not one more."')
PLAN_REFERENCE_KEY_WORDS = frozenset(("fishmonger", "fishmongers", "herring", "herrings",
                                      "crates", "zinc", "shutter", "cloth"))
P22_MISSING = ("beat %d: P22 end frame: end_frame is missing or empty; write one sentence of 8 "
               "to 30 words of the frame this beat ends on: who or what is in frame, where (left, "
               "centre or right; foreground or background), which way they face and how tight "
               "the shot is")
P22_LENGTH = "beat %d: P22 end frame: end_frame is %d words; write one sentence of 8 to 30 words"
P24_MESSAGE = ("plan: P24 reference copy: %s copies the plan reference (%s); write only this "
               "movie's own people, places, objects and words")
END_FRAMES_DROPPED = ("Warning: end frames dropped after %d attempts; this story has no seam "
                      "report")


def test_ct1b_the_planner_constants():
    assert se.END_FRAME_RULE == END_FRAME_RULE
    assert se.PLAN_REFERENCE_INTRO == PLAN_REFERENCE_INTRO
    assert se.PLAN_REFERENCE_LINES_CLAUSE == PLAN_REFERENCE_LINES_CLAUSE
    assert se.PLAN_REFERENCE_KEY_WORDS == PLAN_REFERENCE_KEY_WORDS
    assert se.END_FRAME_WORDS == (8, 30)
    assert se.P22_MISSING == P22_MISSING
    assert se.P22_LENGTH == P22_LENGTH
    assert se.P24_MESSAGE == P24_MESSAGE
    assert se.END_FRAMES_DROPPED == END_FRAMES_DROPPED
    for text in (END_FRAME_RULE, PLAN_REFERENCE_INTRO, PLAN_REFERENCE_LINES_CLAUSE, P22_MISSING,
                 P22_LENGTH, P24_MESSAGE, END_FRAMES_DROPPED, se.plan_reference(True),
                 se.plan_reference(False)):
        assert "slowly" not in text.lower(), text


# --- CT2: the plan reference (CE5) ---------------------------------------------------------------

def _sha(text):
    return (hashlib.sha256(text.encode("utf-8")).hexdigest(), len(text), len(text.split()))


def test_ct2_the_plan_reference_is_pinned():
    assert _sha(se._plan_reference_json(se.PLAN_REFERENCE_PLAN)) == (
        "e3329d43c6049b5d7e727531d37cd14b0a19fda8d3055f79c9298e5280123a53", 2103, 322)
    assert _sha(se.plan_reference(True)) == (
        "f01c845181417fa7a3d77f112786e52efb05c029716c141e3999c6f2c1a87fb3", 2562, 403)
    assert _sha(se.plan_reference(False)) == (
        "571591dffb3a354b21569a171420b6e762268787854d9b1c22dbd496482c1eff", 2429, 380)
    assert len(se.PLAN_REFERENCE_SIX_GRAMS) == 68
    assert json.loads(se.plan_reference(True).split("\n", 1)[1]) == se.PLAN_REFERENCE_PLAN
    no_lines = copy.deepcopy(se.PLAN_REFERENCE_PLAN)
    for beat in no_lines["beats"]:
        del beat["lines"]
    assert json.loads(se.plan_reference(False).split("\n", 1)[1]) == no_lines
    assert se.plan_reference(True).startswith(PLAN_REFERENCE_INTRO % PLAN_REFERENCE_LINES_CLAUSE)
    assert se.plan_reference(False).startswith(PLAN_REFERENCE_INTRO % "")
    for text in (se.plan_reference(True), se.plan_reference(False)):
        assert "@@" not in text and text.endswith("}\n\n")


def test_ct2_the_reference_plan_passes_the_plan_checks(ws):
    for narration in ("speech", True):
        ctx = ref_ctx(ws, narration=narration)
        plan = _normalized(ctx, copy.deepcopy(se.PLAN_REFERENCE_PLAN))
        hard, advisory = se.plan_checks(ctx, plan)
        assert hard == [], narration
        assert [m for m in advisory if re.search(r": P(?:8|22|23|24) ", m)] == [], narration
        assert se.plan_end_frame_problems(ctx, plan) == []
        assert se.line_assignment_problems(plan) == []
        assert [b["end_frame"] for b in plan["beats"]] == [
            b["end_frame"] for b in se.PLAN_REFERENCE_PLAN["beats"]]
    ctx = ref_ctx(ws, narrative="A courier delivers a letter.")
    plan = _normalized(ctx, copy.deepcopy(se.PLAN_REFERENCE_PLAN))
    problems = se.plan_copy_problems(ctx, plan)
    assert problems
    assert all(m.startswith("plan: P24 reference copy: ") for m in problems)
    assert problems[0].startswith("plan: P24 reference copy: the logline copies the plan reference (")


# --- CT3: the plan prompt (CE4) -------------------------------------------------------------------

LINES_NARRATIVE = ('At dusk Kyra climbs the stone steps of a mountain temple, and the ronin walks '
                   'one step behind her. Near the top Kyra turns and says, "We reach the gate '
                   'before dark." They pass under the gate together, and Kyra says, "Stay close '
                   'to me."')
CAMERA_LIST = ("camera is exactly one of: slow push-in, slow pull-back, slow tracking left, slow "
               "tracking right, handheld, slow pan left, slow pan right, slow tilt up, slow tilt "
               "down, slow crane up, slow crane down, slow orbit, static.")
LINES_RULE_END = "never add a beat only to separate lines that fit together."


def _plan_prompt(ws, **kw):
    """The plan prompt of make_ctx(**kw), with no catalog and no pins."""
    return se.build_plan_prompt(seu.make_ctx(se, ws, **kw), [], [])


def test_ct3_the_chained_plan_prompt(ws):
    lined = _plan_prompt(ws, narrative=LINES_NARRATIVE, narration="speech")
    assert ("with the keys index, arc, action, shot, camera, location, cast, speaker, lines and "
            "end_frame.") in lined
    assert LINES_RULE_END + se.END_FRAME_RULE + "\n" in lined
    assert CAMERA_LIST in lined
    assert lined.endswith(se.plan_reference(True) + se.NO_TOOL_SENTENCE)
    plain = _plan_prompt(ws)
    assert "with the keys index, arc, action, shot, camera, location, cast, speaker and end_frame." in plain
    assert se.END_FRAME_RULE + "\nloras: " in plain
    assert plain.endswith(se.MODE_RULES["chained"] + se.plan_reference(False) + se.NO_TOOL_SENTENCE)
    silent = _plan_prompt(ws, narration=False)
    assert se.END_FRAME_RULE in silent
    assert "FORMAT REFERENCE ONLY" not in silent
    assert silent.endswith(se.MODE_RULES["chained"] + se.NO_TOOL_SENTENCE)
    for prompt, lines in ((lined, True), (plain, False), (silent, None)):
        assert "@@" not in prompt
        rest = prompt.replace(se.plan_reference(lines), "") if lines is not None else prompt
        assert "{" not in rest and "}" not in rest


def test_ct3_shots_and_no_stills_plan_prompts(ws):
    for mode in ("shots", "no_stills"):
        for kw in ({}, {"narrative": LINES_NARRATIVE, "narration": "speech"}, {"narration": False}):
            prompt = _plan_prompt(ws, mode=mode, **kw)
            assert "end_frame" not in prompt, (mode, kw)
            assert "FORMAT REFERENCE ONLY" not in prompt, (mode, kw)
            assert CAMERA_LIST in prompt, (mode, kw)
            assert "@@" not in prompt and "{" not in prompt and "}" not in prompt, (mode, kw)


# --- CT4: normalize_plan keeps the end frame (CE3) ------------------------------------------------

def test_ct4_normalize_plan_keeps_a_chained_end_frame(ws):
    ctx = seu.make_ctx(se, ws)
    keys = list(_normalized(ctx, seu.plan_json("chained", 3)))
    raw = seu.plan_json("chained", 3)
    raw["beats"][0]["end_frame"] = "  The courier  stands at frame centre,\n facing left.  "
    plan = _normalized(ctx, raw)
    assert plan["beats"][0]["end_frame"] == "The courier stands at frame centre, facing left."
    assert list(plan) == keys
    assert "end_frame" not in plan["beats"][1]
    for value in ("", "   ", None, 7, ["The courier stands."], {"text": "x"}):
        raw = seu.plan_json("chained", 3)
        raw["beats"][0]["end_frame"] = value
        assert "end_frame" not in _normalized(ctx, raw)["beats"][0], value
    for mode in ("shots", "no_stills"):
        other = seu.make_ctx(se, ws, mode=mode, story_id="n-" + mode.replace("_", "-"))
        plan = _normalized(other, ef_plan(3, mode))
        assert not any("end_frame" in b for b in plan["beats"]), mode
        assert list(plan) == list(_normalized(other, seu.plan_json(mode, 3))), mode


# --- CT5: P22 (CE6) ---------------------------------------------------------------------------------

def _words_frame(n):
    return " ".join(["The courier stands"] + ["still"] * (n - 3)) + "."


def test_ct5_p22_end_frame_presence_and_length(ws):
    ctx = seu.make_ctx(se, ws)
    assert se.plan_end_frame_problems(ctx, _normalized(ctx, ef_plan(3))) == []
    raw = ef_plan(3)
    del raw["beats"][1]["end_frame"]
    assert se.plan_end_frame_problems(ctx, _normalized(ctx, raw)) == [P22_MISSING % 2]
    for k, words, expected in ((1, 7, [P22_LENGTH % (1, 7)]), (3, 31, [P22_LENGTH % (3, 31)]),
                               (2, 8, []), (2, 30, [])):
        raw = ef_plan(3)
        raw["beats"][k - 1]["end_frame"] = _words_frame(words)
        assert se.plan_end_frame_problems(ctx, _normalized(ctx, raw)) == expected, words
    shots = seu.make_ctx(se, ws, mode="shots", story_id="p22-shots")
    assert se.plan_end_frame_problems(shots, _normalized(shots, seu.plan_json("shots", 3))) == []
    assert se.plan_end_frame_problems(ctx, _normalized(ctx, seu.plan_json("chained", 2))) == [
        P22_MISSING % 1, P22_MISSING % 2]


# --- CT6: P23 (CE6) ---------------------------------------------------------------------------------

P23 = "beat 1: P23 end frame content: "


def _p23(ws, text, cast=("c1",)):
    ctx = seu.make_ctx(se, ws, panels=1)
    raw = seu.plan_json("chained", 1)
    raw["beats"][0]["cast"] = list(cast)
    raw["beats"][0]["end_frame"] = text
    plan = _normalized(ctx, raw)
    found = se.end_frame_advisories(ctx, lib, plan)
    assert [m for m in se.plan_checks(ctx, plan)[1] if " P23 " in m] == found
    return found


def test_ct6_p23_end_frame_content_rows(ws):
    assert _p23(ws, "The courier stands beside the old monk at frame centre, facing the camera.") == [
        P23 + "names 'the old monk', who is not in beat 1's cast"]
    assert _p23(ws, "The camera pushes in on the courier at frame centre facing left.") == [
        P23 + "says 'camera pushes'; an end frame describes the frame, never a camera move"]
    assert _p23(ws, "The courier pans the quay from the right edge, facing left.") == [
        P23 + "says 'pans'; an end frame describes the frame, never a camera move"]
    assert _p23(ws, "The courier stands at frame centre, lit by a lamp, facing left.") == [
        P23 + "says 'lit'; an end frame never describes appearance, clothing, setting, lighting, "
        "colour or style"]
    assert _p23(ws, "The courier says goodbye at frame centre, facing left.") == [
        P23 + "says 'says'; an end frame has no spoken words"]
    assert _p23(ws, 'The courier stands under the "closed" sign at frame centre, facing left.') == [
        P23 + "contains a double quote; double quotes are kept for spoken lines"]
    assert _p23(ws, "The courier stands still at frame centre, facing left, holding the sealed "
                    "letter, seen from the waist up.") == []
    assert _p23(ws, "The old monk follows the courier along the quay, both facing left at frame "
                    "centre.", cast=("c1", "c2")) == []
    ctx = ref_ctx(ws)
    assert se.end_frame_advisories(ctx, lib, _normalized(ctx, copy.deepcopy(se.PLAN_REFERENCE_PLAN))) == []
    shots = seu.make_ctx(se, ws, mode="shots", story_id="p23-shots")
    assert se.end_frame_advisories(shots, lib, _normalized(shots, seu.plan_json("shots", 1))) == []


# --- CT7: P24 (CE6) ---------------------------------------------------------------------------------

HERRING_ACTION = "The courier drags a tall stack of empty herring crates past the boats."
ZINC_FRAME = "The courier leans on the zinc counter, facing the camera, seen from the waist up."
FISHER = "a weathered man with a grey beard and short white hair wearing an oilskin coat that smells of herring"


def _p24_plan(ctx, action=None, frame=None):
    raw = ef_plan(3)
    if action is not None:
        raw["beats"][0]["action"] = action
    if frame is not None:
        raw["beats"][1]["end_frame"] = frame
    return _normalized(ctx, raw)


def test_ct7_p24_reference_copy_rows(ws, story_env):
    ctx = seu.make_ctx(se, ws)
    assert se.plan_copy_problems(ctx, _p24_plan(ctx)) == []
    assert se.plan_copy_problems(ctx, _p24_plan(ctx, action=HERRING_ACTION)) == [
        P24_MESSAGE % ("beat 1's action", "'herring', 'a tall stack of empty herring', 'tall stack "
                       "of empty herring crates'")]
    assert se.plan_copy_problems(ctx, _p24_plan(ctx, frame=ZINC_FRAME)) == [
        P24_MESSAGE % ("beat 2's end frame", "'zinc'")]
    assert se.plan_copy_problems(ctx, _p24_plan(ctx, frame=ZINC_FRAME), end_frames=False) == []
    zinc = seu.make_ctx(se, ws, narrative="A courier leans on a zinc counter in the rain.",
                        story_id="p24-zinc")
    assert se.plan_copy_problems(zinc, _p24_plan(zinc, frame=ZINC_FRAME)) == []
    basket = "The courier carries a herring basket past the boats."
    assert se.plan_copy_problems(ctx, _p24_plan(ctx, action=basket)) == [
        P24_MESSAGE % ("beat 1's action", "'herring'")]
    seu.make_character(story_env["lib"], "fisher", "fishermn", "the old fisherman", "man", FISHER)
    pinned = seu.make_ctx(se, ws, members=lib.resolve_cast([(None, "fisher")]), story_id="p24-pin")
    assert se.plan_copy_problems(pinned, _p24_plan(pinned, action=basket)) == []
    assert se.plan_copy_problems(ctx, _p24_plan(
        ctx, action="The courier turns back into the hall and walks to the gate.")) == []
    for other in (seu.make_ctx(se, ws, mode="shots", story_id="p24-shots"),
                  seu.make_ctx(se, ws, narration=False, story_id="p24-silent")):
        assert se.plan_copy_problems(other, _p24_plan(other, action=HERRING_ACTION)) == []


# --- CT8: the plan retry, end to end (CE7, CK1) -----------------------------------------------------

def _panel_replies(mode, n):
    return dict((str(k), [seu.answer(seu.panel_json(mode, k))]) for k in range(1, n + 1))


def _e2e(ws, tmp_path, monkeypatch, plans, n=3, panel=None, **ctx_kw):
    """(rc, agent log, saved plan.json or None, ctx) of se.run with the scripted plan replies
    plans and panel replies panel (default: one seu.panel_json reply per panel)."""
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(p) for p in plans],
                           panel=_panel_replies("chained", n) if panel is None else panel)
    ctx = seu.make_ctx(se, ws, panels=ctx_kw.pop("panels", n), **ctx_kw)
    rc, _advisories = se.run(ctx)
    path = os.path.join(ctx.story_dir, "plan.json")
    return rc, seu.agent_log(log), (_read_json(path) if os.path.exists(path) else None), ctx


def _assert_p22_clean(plan):
    """CK1: a saved plan either has every beat's end frame, each passing P22, or none."""
    frames = [b.get("end_frame") for b in plan["beats"]]
    if any(frames):
        assert all(se.END_FRAME_WORDS[0] <= len(f.split()) <= se.END_FRAME_WORDS[1]
                   for f in frames), frames


def test_ct8_a_plan_without_end_frames_is_asked_again(ws, tmp_path, monkeypatch, capsys):
    rc, log, plan, _ctx = _e2e(ws, tmp_path, monkeypatch, [seu.plan_json("chained", 3), ef_plan(3)])
    out = capsys.readouterr().out
    assert rc == 0
    assert [c["stage"] for c in log][:3] == ["plan", "plan", "panel"]
    assert ("YOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- " + P22_MISSING % 1 + "\n") in log[1]["argv"][-1]
    assert [b["end_frame"] for b in plan["beats"]] == [END_FRAME % k for k in (1, 2, 3)]
    assert "end frames dropped" not in out
    _assert_p22_clean(plan)


def test_ct8_two_plans_without_end_frames_drop_them(ws, tmp_path, monkeypatch, capsys):
    rc, log, plan, ctx = _e2e(ws, tmp_path, monkeypatch, [seu.plan_json("chained", 3)] * 2)
    out = capsys.readouterr().out
    assert rc == 0
    assert [c["stage"] for c in log][:3] == ["plan", "plan", "panel"]
    assert END_FRAMES_DROPPED % 2 + "\n" in out
    assert not any("end_frame" in b for b in plan["beats"])
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert not [m for m in checks["advisory"] if " P22 " in m["message"]]
    _assert_p22_clean(plan)


def test_ct8_a_copied_action_after_the_last_call_is_fatal(ws, tmp_path, monkeypatch, capsys):
    raw = ef_plan(3)
    raw["beats"][0]["action"] = HERRING_ACTION
    rc, log, plan, _ctx = _e2e(ws, tmp_path, monkeypatch, [raw, raw])
    err = capsys.readouterr().err
    assert rc == 1
    assert [c["stage"] for c in log] == ["plan", "plan"]
    assert "  - plan: P24 reference copy: beat 1's action copies the plan reference (" in err
    assert plan is None


def test_ct8_a_copied_end_frame_after_the_last_call_is_dropped(ws, tmp_path, monkeypatch, capsys):
    raw = ef_plan(3)
    raw["beats"][1]["end_frame"] = ZINC_FRAME
    rc, log, plan, _ctx = _e2e(ws, tmp_path, monkeypatch, [raw, raw])
    out = capsys.readouterr().out
    assert rc == 0
    assert END_FRAMES_DROPPED % 2 + "\n" in out
    assert not any("end_frame" in b for b in plan["beats"])
    _assert_p22_clean(plan)


def test_ct8_a_plan_with_end_frames_makes_one_call(ws, tmp_path, monkeypatch, capsys):
    rc, log, plan, _ctx = _e2e(ws, tmp_path, monkeypatch, [ef_plan(3)])
    out = capsys.readouterr().out
    assert rc == 0
    assert [c["stage"] for c in log].count("plan") == 1
    assert "end frames dropped" not in out
    assert [b["end_frame"] for b in plan["beats"]] == [END_FRAME % k for k in (1, 2, 3)]
    _assert_p22_clean(plan)


# --- CT16: the soft panel count (CE7; [SPC]) -------------------------------------------------------

def test_ct16_an_added_beat_needs_its_own_end_frame(ws, tmp_path, monkeypatch, capsys):
    four = ef_plan(4)
    del four["beats"][3]["end_frame"]
    rc, log, plan, _ctx = _e2e(ws, tmp_path, monkeypatch, [four, ef_plan(4)], n=4, panels=3)
    assert rc == 0
    assert [c["stage"] for c in log][:2] == ["plan", "plan"]
    assert "YOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- " + P22_MISSING % 4 + "\n" in log[1]["argv"][-1]
    assert len(plan["beats"]) == 4 and all(b.get("end_frame") for b in plan["beats"])
    rc, log, plan, _ctx = _e2e(ws, tmp_path, monkeypatch, [ef_plan(4)], n=4, panels=3,
                               story_id="s2")
    assert rc == 0
    assert [c["stage"] for c in log].count("plan") == 1
    assert len(plan["beats"]) == 4
    _assert_p22_clean(plan)
```

- [ ] **Step 2: Run the tests to verify they fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_chained_end_frames.py 2>&1 | tail -1
```

Expected: `14 failed, 9 passed`. Of the 15 new tests only `test_ct3_shots_and_no_stills_plan_prompts` passes: shots and no_stills prompts must not change here, and Task 1 already gave them the new camera list.

- [ ] **Step 3: Write the implementation.**

**3.1.** The template (CE4). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "@@MAX_CAST@@.@@SPEAKER_RULE@@@@LINES_RULE@@\n"
    "loras: @@LORA_PARAGRAPH@@\n"
    "\n"
    "@@MODE_RULES@@" + NO_TOOL_SENTENCE)
```

with:

```python
    "@@MAX_CAST@@.@@SPEAKER_RULE@@@@LINES_RULE@@@@END_FRAME_RULE@@\n"
    "loras: @@LORA_PARAGRAPH@@\n"
    "\n"
    "@@MODE_RULES@@@@PLAN_REFERENCE@@" + NO_TOOL_SENTENCE)
```

**3.2.** `END_FRAME_RULE` (CE4). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
CAMERA_SPEAKING_SENTENCE = (" On a beat with a speaker, prefer slow push-in, slow pull-back, "
                            "slow tracking left, slow tracking right or handheld, and never use a "
                            "pan, a tilt, a crane or an orbit, which sweep the speaker's face out "
                            "of the frame.")
```

with:

```python
CAMERA_SPEAKING_SENTENCE = (" On a beat with a speaker, prefer slow push-in, slow pull-back, "
                            "slow tracking left, slow tracking right or handheld, and never use a "
                            "pan, a tilt, a crane or an orbit, which sweep the speaker's face out "
                            "of the frame.")
# Chained end frames spec CE4, D1: the planner's end frame of every chained beat.
END_FRAME_RULE = (" end_frame is one sentence of 8 to 30 words, in the present tense, of the "
                  "frame the beat ends on: who or what is in frame, where each one is (left, "
                  "centre or right; foreground or background), which way they face and how tight "
                  "the shot is. It never names a camera move, the lighting, a colour or a style, "
                  "has no spoken words and no double quotes, and names only characters in the "
                  "beat's cast. Beat k's end frame is exactly where beat k+1 begins; write beat "
                  "k+1's action so it starts from that composition. The last beat's end frame "
                  "closes the story.")
```

**3.3.** `beat_keys` (CE4). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
                else SEED_PARAGRAPH)
    fragments = [
        ("@@GOAL_PARAGRAPH@@", _goal_paragraph(ctx.goal)),
```

with:

```python
                else SEED_PARAGRAPH)
    beat_keys = "cast, speaker and lines" if lines else "cast and speaker"
    if ctx.mode == "chained":
        beat_keys = "cast, speaker, lines and end_frame" if lines else "cast, speaker and end_frame"
    fragments = [
        ("@@GOAL_PARAGRAPH@@", _goal_paragraph(ctx.goal)),
```

**3.4.** The beat keys and the two new fragments (CE4). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        ("@@BEAT_KEYS@@", "cast, speaker and lines" if lines else "cast and speaker"),
        ("@@LINES_RULE@@", (LINES_RULE + (LINES_PINNED_SENTENCE
                                          if ctx.members and ctx.mode != "chained" else "")
                         + said)
         if lines else ""),
    ]
```

with:

```python
        ("@@BEAT_KEYS@@", beat_keys),
        ("@@LINES_RULE@@", (LINES_RULE + (LINES_PINNED_SENTENCE
                                          if ctx.members and ctx.mode != "chained" else "")
                         + said)
         if lines else ""),
        ("@@END_FRAME_RULE@@", END_FRAME_RULE if ctx.mode == "chained" else ""),
        ("@@PLAN_REFERENCE@@", plan_reference(bool(lines))
         if ctx.mode == "chained" and ctx.narration is not False else ""),
    ]
```

**3.5.** `_named_ids` (CE6). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        if span == tokens:
            hits[cid] = max(hits.get(cid, 0), n)
    return hits
```

with:

```python
        if span == tokens:
            hits[cid] = max(hits.get(cid, 0), n)
    return hits


def _named_ids(words, mentions):
    """The cast ids, in mention order without repeats, whose mention ([(cast id, words)], as
    _mentions) occurs as consecutive words of words (chained end frames spec CE6, CE9)."""
    out = []
    for cid, tokens in mentions:
        n = len(tokens)
        if cid not in out and any(words[i:i + n] == tokens for i in range(len(words) - n + 1)):
            out.append(cid)
    return out
```

**3.6.** `normalize_plan` keeps the end frame (CE3). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
            "lines": _clean_lines(item.get("lines"))})
```

with:

```python
            "lines": _clean_lines(item.get("lines"))})
        # Chained end frames spec CE3, D1: a chained beat keeps its end frame; the key is present
        # only when the planner wrote one.
        end_frame = _clean_str(item.get("end_frame")) if ctx.mode == "chained" else ""
        if end_frame:
            beats[-1]["end_frame"] = end_frame
```

**3.7.** P22, P23 and P24, and `drop_end_frames` (CE6). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
            for n, line in enumerate(plan.get("spoken_lines", []), start=1) if n not in held]
```

with:

```python
            for n, line in enumerate(plan.get("spoken_lines", []), start=1) if n not in held]


# Chained end frames spec CE6, D3, D4: the end frame checks. P22 and P24 make the plan call
# retry and never enter a state; P23 is a plan_checks advisory.
END_FRAME_WORDS = (8, 30)
P22_MISSING = ("beat %d: P22 end frame: end_frame is missing or empty; write one sentence of 8 "
               "to 30 words of the frame this beat ends on: who or what is in frame, where (left, "
               "centre or right; foreground or background), which way they face and how tight "
               "the shot is")
P22_LENGTH = "beat %d: P22 end frame: end_frame is %d words; write one sentence of 8 to 30 words"
P24_MESSAGE = ("plan: P24 reference copy: %s copies the plan reference (%s); write only this "
               "movie's own people, places, objects and words")
END_FRAMES_DROPPED = ("Warning: end frames dropped after %d attempts; this story has no seam "
                      "report")


def plan_end_frame_problems(ctx, plan):
    """The P22 messages of a chained plan, in beat order (CE6): a beat with no end frame, or one
    whose word count (_words) is outside END_FRAME_WORDS. [] in shots and no_stills."""
    if ctx.mode != "chained":
        return []
    out = []
    for k, beat in enumerate(plan["beats"], start=1):
        text = beat.get("end_frame", "")
        if not text:
            out.append(P22_MISSING % k)
        elif not END_FRAME_WORDS[0] <= _words(text) <= END_FRAME_WORDS[1]:
            out.append(P22_LENGTH % (k, _words(text)))
    return out


def end_frame_advisories(ctx, lib, plan):
    """The P23 advisories of a chained plan's end frames, in beat order, at most one of each kind
    per beat (CE6, D4): a cast entry outside the beat's cast; a camera word (a CAMERA_CLAUSE_RE
    match, else a CAMERA_MOTION_RE word other than the static words and follow/follows); an N3
    word (_APPEARANCE_RE with the cast phrases and prop names blanked); a speaking verb
    (DIALOGUE_RE); a straight or curly double quote."""
    if ctx.mode != "chained":
        return []
    still = CAMERA_MOVE_WORDS["static"] + ("follow", "follows")
    mentions = _mentions(plan["cast"])
    names = cast_phrases(ctx, plan) + [p["name"] for p in plan["props"] if p.get("name")]
    out = []
    for k, beat in enumerate(plan["beats"], start=1):
        text = beat.get("end_frame", "")
        if not text:
            continue
        prefix = "beat %d: P23 end frame content:" % k
        stray = [c for c in _named_ids(line_words(text), mentions) if c not in beat["cast"]]
        if stray:
            out.append("%s names %s, who is not in beat %d's cast"
                       % (prefix, _q(speaker_phrase_of(plan, stray[0])), k))
        clause = CAMERA_CLAUSE_RE.search(text)
        word = (" ".join(clause.group(0).lower().split()) if clause else
                next((w for w in _camera_words(text) if w not in still), None))
        if word:
            out.append("%s says %s; an end frame describes the frame, never a camera move"
                       % (prefix, _q(word)))
        word = _first(_APPEARANCE_RE, lib._blank(text, lib._passage_spans(text, names)))
        if word:
            out.append("%s says %s; an end frame never describes appearance, clothing, setting, "
                       "lighting, colour or style" % (prefix, _q(word)))
        word = _first(DIALOGUE_RE, text)
        if word:
            out.append("%s says %s; an end frame has no spoken words" % (prefix, _q(word)))
        if any(q in text for q in _DOUBLE_QUOTES):
            out.append("%s contains a double quote; double quotes are kept for spoken lines"
                       % prefix)
    return out


def plan_copy_problems(ctx, plan, end_frames=True):
    """The P24 messages of a chained plan shown PLAN_REFERENCE (CE6): every model-written field
    (title, logline, a non-library cast entry's phrase and descriptor, a non-library location's
    setting, prop names, beat actions and, with end_frames, beat end frames) that contains a
    REFERENCE_TERMS term or a PLAN_REFERENCE_SIX_GRAMS run, leaving out any the narrative, the
    goal, a library character's phrase or descriptor or a library location's description already
    has. [] unless ctx.mode is chained and ctx.narration is not False."""
    if ctx.mode != "chained" or ctx.narration is False:
        return []
    own = ([ctx.narrative or "", ctx.goal or ""] + [m.phrase for m in ctx.members]
           + [m.descriptor for m in ctx.members] + [pin.description for pin in ctx.locations])
    own_words = [line_words(t) for t in own]
    own_line = " " + " | ".join(" ".join(w) for w in own_words) + " "
    own_grams = set(g for w in own_words for g in _six_grams(w))
    texts = [("the title", plan["title"]), ("the logline", plan["logline"])]
    for c in plan["cast"]:
        if not c.get("cast_name"):
            texts += [("%s's phrase" % c["id"], c["phrase"]),
                      ("%s's descriptor" % c["id"], c["descriptor"])]
    texts += [("%s's setting" % l["id"], l["setting"]) for l in plan["locations"]
              if not l.get("location_name")]
    texts += [("%s's name" % p["id"], p["name"]) for p in plan["props"]]
    texts += [("beat %d's action" % k, b["action"]) for k, b in enumerate(plan["beats"], start=1)]
    if end_frames:
        texts += [("beat %d's end frame" % k, b.get("end_frame", ""))
                  for k, b in enumerate(plan["beats"], start=1)]
    out = []
    for where, text in texts:
        words = line_words(text or "")
        line = " " + " ".join(words) + " "
        hits = [t for t in REFERENCE_TERMS
                if (" %s " % " ".join(line_words(t))) in line
                and (" %s " % " ".join(line_words(t))) not in own_line]
        hits += [" ".join(g) for g in sorted((_six_grams(words) & PLAN_REFERENCE_SIX_GRAMS)
                                             - own_grams)]
        if hits:
            out.append(P24_MESSAGE % (where, ", ".join(_q(h) for h in hits[:3])))
    return out


def drop_end_frames(plan):
    """Remove every beat's end frame, in place (CE7)."""
    for beat in plan["beats"]:
        beat.pop("end_frame", None)
```

**3.8.** P23 in `plan_checks` (CE6). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    # Pinned cast presence spec PC1, D1: every library character is in some beat's cast.
```

with:

```python
    # Chained end frames spec CE6, D4: P23, the end frame content (advisory).
    advisory += end_frame_advisories(ctx, lib, plan)
    # Pinned cast presence spec PC1, D1: every library character is in some beat's cast.
```

**3.9.** The plan reference (CE5). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    return hits + [" ".join(g) for g in sorted((_six_grams(words) & REFERENCE_SIX_GRAMS)
                                               - own_grams)]
```

with:

```python
    return hits + [" ".join(g) for g in sorted((_six_grams(words) & REFERENCE_SIX_GRAMS)
                                               - own_grams)]


# Chained end frames spec CE5, D9: a complete three-beat planner reply of the FORMAT_REFERENCE
# movie, shown to the chained planner for its format only.
PLAN_REFERENCE_INTRO = ("FORMAT REFERENCE ONLY — never reuse its people, places, objects or "
                        "words. This is the complete plan of a three-beat movie made as one "
                        "continuous take, a different story from this one.%s It shows the format "
                        "of every plan: each beat's end_frame says exactly where the beat ends, "
                        "the next beat's action starts from that end frame, and the last end "
                        "frame closes the story.\n")
PLAN_REFERENCE_LINES_CLAUSE = (' Its narrative quoted two spoken lines: 1 "Forty years of '
                               'mornings." and 2 "Not one more."')
PLAN_REFERENCE_PLAN = {
    "title": "The Last Morning at the Market",
    "logline": ("At dawn an old fishmonger closes her market hall for the last time and says "
                "goodbye to forty years of work."),
    "cast": [{"id": "c1", "phrase": "the old fishmonger",
              "descriptor": ("an old woman with a stooped build, weathered pale skin and short "
                             "grey hair under a knitted cap, wearing a rubber apron over a thick "
                             "wool jumper and tall rubber boots")}],
    "locations": [{"id": "l1", "setting": (
        "The setting is a covered fish market hall in a northern harbour town at dawn, wet "
        "concrete underfoot, rows of bare zinc counters behind, under grey first light from the "
        "harbour doors.")}],
    "props": [{"id": "p1", "name": "the herring crates"}, {"id": "p2", "name": "the folded cloth"}],
    "beats": [
        {"index": 1, "arc": "introduction",
         "action": ("The old fishmonger drags a tall stack of empty herring crates across the wet "
                    "market hall to the half-open shutter."),
         "shot": "medium shot", "camera": "slow tracking right", "location": "l1", "cast": ["c1"],
         "speaker": "", "lines": [],
         "end_frame": ("The old fishmonger stands beside the half-open shutter at frame centre, "
                       "facing left toward the hall, seen from the knees up, the empty crates at "
                       "her feet.")},
        {"index": 2, "arc": "climax",
         "action": ("From the shutter, the old fishmonger turns back into the hall and walks to "
                    "the zinc counter, laying her folded cloth on it."),
         "shot": "medium shot", "camera": "slow push-in", "location": "l1", "cast": ["c1"],
         "speaker": "c1", "lines": [1, 2],
         "end_frame": ("The old fishmonger stands behind the zinc counter at frame centre, "
                       "facing forward, her face filling the frame from chin to brow.")},
        {"index": 3, "arc": "resolution",
         "action": ("The old fishmonger lowers her forehead onto her folded hands on the cold "
                    "zinc counter and closes her eyes."),
         "shot": "close-up", "camera": "static", "location": "l1", "cast": ["c1"],
         "speaker": "", "lines": [],
         "end_frame": ("The old fishmonger rests her forehead on her folded hands at frame "
                       "centre, eyes closed, her head and hands filling the frame in a "
                       "close-up.")},
    ],
    "loras": {"global": [], "per_beat": {}, "stills": []},
}


def _plan_reference_json(plan):
    """The reference plan as JSON (CE5): title and logline on the first line, then one line each
    for cast, locations and props, one line per beat, and loras; json.dumps defaults with
    ensure_ascii=False, keys in dict order."""
    def dump(value):
        return json.dumps(value, ensure_ascii=False)
    lines = ['{"title": %s, "logline": %s,' % (dump(plan["title"]), dump(plan["logline"]))]
    lines += [' "%s": %s,' % (key, dump(plan[key])) for key in ("cast", "locations", "props")]
    lines.append(' "beats": [')
    last = len(plan["beats"]) - 1
    lines += ["  " + dump(beat) + ("," if i < last else "],") for i, beat in enumerate(plan["beats"])]
    lines.append(' "loras": %s}' % dump(plan["loras"]))
    return "\n".join(lines)


def plan_reference(lines):
    """The @@PLAN_REFERENCE@@ text (CE5): with lines, the plan as written; without, every beat's
    "lines" key and the spoken-lines sentence are left out, matching a prompt with no lines key."""
    plan = copy.deepcopy(PLAN_REFERENCE_PLAN)
    if not lines:
        for beat in plan["beats"]:
            del beat["lines"]
    return ((PLAN_REFERENCE_INTRO % (PLAN_REFERENCE_LINES_CLAUSE if lines else ""))
            + _plan_reference_json(plan) + "\n\n")


# Chained end frames spec CE6, D9: P24 counts a six-word run only when it holds one of these.
PLAN_REFERENCE_KEY_WORDS = frozenset(("fishmonger", "fishmongers", "herring", "herrings",
                                      "crates", "zinc", "shutter", "cloth"))
PLAN_REFERENCE_SEGMENTS = tuple(
    [PLAN_REFERENCE_PLAN["title"], PLAN_REFERENCE_PLAN["logline"]]
    + [c["descriptor"] for c in PLAN_REFERENCE_PLAN["cast"]]
    + [l["setting"] for l in PLAN_REFERENCE_PLAN["locations"]]
    + [p["name"] for p in PLAN_REFERENCE_PLAN["props"]]
    + [b["action"] for b in PLAN_REFERENCE_PLAN["beats"]]
    + [b["end_frame"] for b in PLAN_REFERENCE_PLAN["beats"]])
PLAN_REFERENCE_SIX_GRAMS = frozenset(g for s in PLAN_REFERENCE_SEGMENTS
                                     for g in _six_grams(line_words(s))
                                     if set(g) & PLAN_REFERENCE_KEY_WORDS)
```

**3.10.** P22 and P24 re-ask (CE7). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
                problems = hard + line_assignment_problems(plan)
```

with:

```python
                problems = (hard + plan_end_frame_problems(ctx, plan)
                            + plan_copy_problems(ctx, plan) + line_assignment_problems(plan))
```

**3.11.** A P24 copy outside the end frames is fatal after the last call (CE7). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        # Pinned cast presence spec PC2, speaker attribution spec SA3: a plan that drops a library
        # character or gives a spoken line to the wrong speaker, or sets no beat at a library
        # location (location library spec L3.5), is not usable.
        fatal = ([h for h in found[2]
                  if parse_violation(h)["id"] in ("P1", "P2", "P16", "P17", "P21")]
                 if found else ["the reply is not one JSON object"])
        if fatal:
```

with:

```python
        # Pinned cast presence spec PC2, speaker attribution spec SA3: a plan that drops a library
        # character or gives a spoken line to the wrong speaker, or sets no beat at a library
        # location (location library spec L3.5), is not usable; chained end frames spec CE7: a P24
        # copy outside the end frames too.
        fatal = ([h for h in found[2]
                  if parse_violation(h)["id"] in ("P1", "P2", "P16", "P17", "P21")]
                 + plan_copy_problems(ctx, found[0], end_frames=False)
                 if found else ["the reply is not one JSON object"])
        if fatal:
```

**3.12.** Failing end frames are dropped (CE7). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        plan, self.shape, _hard = found
```

with:

```python
        plan, self.shape, _hard = found
        # Chained end frames spec CE7, D3: end frames that still fail after the last plan call
        # are dropped; the story never fails because of them.
        if plan_end_frame_problems(ctx, plan) or plan_copy_problems(ctx, plan):
            drop_end_frames(plan)
            print(END_FRAMES_DROPPED % len([c for c in self.doc["calls"] if c["stage"] == "plan"]))
```

- [ ] **Step 4: Run the tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_chained_end_frames.py 2>&1 | tail -1
```

Expected: `23 passed`.

Then this check of the pinned values (CE5, CE6):

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
python3 -B -c '
import hashlib, importlib.machinery
se = importlib.machinery.SourceFileLoader("se_check", "story_engine.py").load_module()
for text in (se._plan_reference_json(se.PLAN_REFERENCE_PLAN), se.plan_reference(True), se.plan_reference(False)):
    print(hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], len(text), len(text.split()))
print(len(se.PLAN_REFERENCE_SIX_GRAMS))'
```

Expected, exactly: `e3329d43c604 2103 322`, `f01c84518141 2562 403`, `571591dffb3a 2429 380`, `68`.

The compile check with `FILES` = `story_engine.py tests/test_chained_end_frames.py`. Expected: `compiled 2` twice.

The gate block with `N=2`. Expected: `GATE PASS`, `lost 28 (listed 28, unexpected 0); new tests 23, not passing 0`, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
git add story_engine.py tests/test_chained_end_frames.py
git diff --cached --name-only    # expected: only those 2 paths
git commit -m "feat(story-engine): chained plans give every beat an end frame: the plan reference, P22, P23, P24, the re-ask and the drop (chained end frames CE3-CE7; CT2-CT8, CT16)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 3: N23, the camera clause lands on the planned end frame (CE9, CE12; CT1 part, CT10, CT11, CT15, Review Focus 3)

This task implements:
- CE9: `END_FRAME_STOP_WORDS`, `end_frame_words`, `end_frame_detail` and `end_frame_landing_problems`, placed after `trim_format`.
  - The N23 advisory in `_field_checks`, after N22, in every state and on recheck, with the docstring's added sentence.
  - The round-0 re-ask in `go`, which joins `format_problems` in the existing single re-ask.
- CE12: `"N23"` in `GENERATION_CHECKS` and `RECHECK_IDS`, before `"Q1"`, so the existing slices keep their values.

Tests: CT1 (Task 3 part), CT10, CT11, CT15 and Review Focus 3, appended to `tests/test_chained_end_frames.py`. `REF_MOTIONS` (the three Motion fields of the spec's CE11 parts table) also serves Task 4.

**Files:**
- Modify: `tests/test_chained_end_frames.py` (append).
- Modify: `story_engine.py`: `trim_format`'s end `:3564-3566`, `_field_checks`' docstring `:3040` and its N22 block's end `:3340-3341`, `GENERATION_CHECKS` `:3485-3487`, round 0 `:4728-4737`, `RECHECK_IDS` `:4819-4820`.

**Interfaces:**
- Consumes: Task 1's `end_clause`; Task 2's `_named_ids`; existing `_sentences`, `_mentions`, `line_words`, `_q`, `speaker_phrase_of`, `panel_fields`, `_character_lib`, `cast_phrases`, `format_problems`, `trim_format`, `PANEL_MAX_CALLS`.
- Produces (Task 4 and the tests use these names exactly):
  - `END_FRAME_STOP_WORDS` (frozenset), `end_frame_words(text, mention_words) -> set`;
  - `end_frame_detail(lib, plan, k, text, phrases) -> str or None`;
  - `end_frame_landing_problems(ctx, plan, part, k) -> [str]`.
  - In the test file: `REF_MOTIONS` (3 strings), `E2`, `E2_QUOTED`.

- [ ] **Step 1: Write the failing tests.**

Append to the test file. Edit `tests/test_chained_end_frames.py`: replace this text, which occurs exactly once:

```python
    assert len(plan["beats"]) == 4
    _assert_p22_clean(plan)
```

with:

```python
    assert len(plan["beats"]) == 4
    _assert_p22_clean(plan)


# --- CT1 (Task 3 part): the N23 constants and check ids (CE9, CE12) ------------------------------

END_FRAME_STOP_WORDS = frozenset("""
    a an the and or but nor of to in on at by for from with without into onto off over under up
    down out about across along around through toward towards behind beside between near past
    against as is are be being it its he she they him her them his hers their theirs this that
    these those there here who whom which what while where when one each both all every
    some""".split())
GENERATION_CHECKS = ("N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11", "N12",
                     "N14", "N15", "N16", "N17", "N18", "T1", "T2", "T3", "N20", "N21", "N22",
                     "N23", "Q1", "N19")
RECHECK_IDS = ("N1", "N2", "N3", "N4", "N7", "N8", "N9", "N10", "N11", "N12", "N14", "N15", "N16",
               "N17", "N18", "T1", "T2", "T3", "N23", "Q1", "N19")


def test_ct1c_the_n23_constants_and_check_ids():
    assert se.END_FRAME_STOP_WORDS == END_FRAME_STOP_WORDS
    assert se.GENERATION_CHECKS == GENERATION_CHECKS
    assert se.GENERATION_CHECKS[16:20] == ("N18", "T1", "T2", "T3")
    assert se.GENERATION_CHECKS[-2:] == ("Q1", "N19") and se.GENERATION_CHECKS[-1] == "N19"
    assert se.RECHECK_IDS == RECHECK_IDS
    assert se.RECHECK_IDS[14:18] == ("N18", "T1", "T2", "T3")
    assert se.RECHECK_IDS[-2:] == ("Q1", "N19")
    assert se.FORMAT_IDS == ("N7", "N20", "N21", "N22")
    assert se.PLAN_FREE_IDS == ("N1", "N7", "N8", "N9", "N10", "N11", "N15")


# --- CT10: N23 detection (CE9, CK2) ---------------------------------------------------------------

E2 = END_FRAME % 2
E2_QUOTED = "'" + E2 + "'"
REF_MOTIONS = (
    "The old fishmonger drags a tall stack of empty herring crates across the wet concrete of the "
    "market hall toward the half-open shutter at real-time speed, her heavy steps splashing "
    "through shallow puddles that hold the first glow from the harbour doors. The camera tracks "
    "right alongside her — as the move completes, the old fishmonger stands beside the half-open "
    "shutter at frame centre, facing left toward the hall, seen from the knees up, the empty "
    "crates at her feet.",
    "The old fishmonger turns back from the shutter and walks to the zinc counter at real-time "
    "speed, laying her folded cloth beside the empty ice trays and lifting her face to the "
    "camera. The old fishmonger presses both palms flat on the folded cloth, her shoulders "
    "sinking. The camera pushes in — as the move completes, the old fishmonger stands behind the "
    "zinc counter at frame centre, facing forward, her face filling the frame from chin to brow. "
    "The old fishmonger faces the camera.",
    "The old fishmonger lowers her forehead onto her folded hands on the cold zinc counter at "
    "real-time speed, her breath fogging the metal as a thin trickle of meltwater runs past her "
    "knuckles and drips to the wet floor. The camera stays static, holding the old fishmonger as "
    "she rests her forehead on her folded hands at frame centre, eyes closed, her head and hands "
    "filling the frame.",
)


def _detail(ws, camera, plan=None):
    ctx = seu.make_ctx(se, ws)
    plan = plan or _normalized(ctx, ef_plan(3))
    return se.end_frame_detail(lib, plan, 2, "The courier runs. " + camera, ["the courier"])


def test_ct10_n23_detection_rows(ws):
    assert _detail(ws, "The camera tracks the movement.") == (
        "has no camera sentence whose words after 'as the move completes,' (or after 'holding' "
        "for a static camera) describe the planned end frame " + E2_QUOTED)
    assert _detail(ws, "The camera tracks him — as the move completes, he stands at frame centre "
                       "on the wet quay.") == (
        "the camera sentence ends 'he stands at frame centre on the wet quay', which does not "
        "name 'the courier', whom the planned end frame " + E2_QUOTED + " names")
    assert _detail(ws, "The camera tracks him — as the move completes, the courier waits by a "
                       "lamp.") == (
        "the camera sentence ends 'the courier waits by a lamp', which shares 0 of the 11 content "
        "words of the planned end frame " + E2_QUOTED + "; it needs at least 6")
    assert _detail(ws, "The camera tracks him — as the move completes, the courier stands at frame "
                       "centre on the wet quay, facing left.") is None
    assert _detail(ws, "The camera tracks him — as the move completes, the courier stands at frame "
                       "centre on the wet quay.") == (
        "the camera sentence ends 'the courier stands at frame centre on the wet quay', which "
        "shares 5 of the 11 content words of the planned end frame " + E2_QUOTED + "; it needs "
        "at least 6")
    assert _detail(ws, "The camera stays static, holding the courier at frame centre on the wet "
                       "quay, facing the camera.") is None
    ctx = seu.make_ctx(se, ws)
    raw = ef_plan(3)
    del raw["beats"][1]["end_frame"]
    assert _detail(ws, "The camera tracks the movement.", plan=_normalized(ctx, raw)) is None
    mentions = se._mentions(_normalized(ctx, ef_plan(3))["cast"])
    assert sorted(se.end_frame_words(E2, set(w for _c, ws_ in mentions for w in ws_))) == [
        "2", "beat", "camera", "centre", "facing", "frame", "quay", "seen", "stands", "waist", "wet"]
    for k, motion in enumerate(REF_MOTIONS, start=1):
        assert se.end_frame_detail(lib, se.PLAN_REFERENCE_PLAN, k, motion,
                                   ["the old fishmonger"]) is None, k


def test_review_focus_3_curly_apostrophes_and_capitals_still_land(ws):
    ctx = seu.make_ctx(se, ws, panels=1)
    raw = seu.plan_json("chained", 1)
    raw["beats"][0]["end_frame"] = ("The courier's bicycle leans against the harbour wall at frame "
                                    "centre, the courier beside it facing left.")
    plan = _normalized(ctx, raw)
    text = ("The courier runs. The camera tracks him — as the move completes, THE COURIER’S "
            "bicycle leans against the Harbour Wall at frame centre, the courier beside it facing "
            "left!")
    assert se.end_frame_detail(lib, plan, 1, text, ["the courier"]) is None
    assert se.end_clause("The camera tracks him — as the move completes, THE COURIER’S bicycle "
                         "leans.") == "THE COURIER’S bicycle leans"


# --- CT11: N23 in round 0, end to end (CE9, CK2) -------------------------------------------------

def _clause(end_frame):
    """end_frame with a lower-case first letter and no full stop."""
    return end_frame[:1].lower() + end_frame[1:].rstrip(".")


def _miss(k):
    return seu.panel_json("chained", k)


def _land(k):
    """Panel k of EF_PLAN(2) (1 static, 2 tracking) with a camera sentence that lands."""
    part = seu.panel_json("chained", k)
    if k == 1:
        part["motion"] += " The camera stays static, holding " + _clause(END_FRAME % 1) + "."
    else:
        part["motion"] += (" The camera tracks the courier — as the move completes, "
                           + _clause(END_FRAME % 2) + ".")
    return part


def _ct11(ws, tmp_path, monkeypatch, panel1, panel2, story_id="s1"):
    panel = {"1": [p if "answer" in p else seu.answer(p) for p in panel1],
             "2": [seu.answer(p) for p in panel2]}
    rc, log, plan, ctx = _e2e(ws, tmp_path, monkeypatch, [ef_plan(2)], n=2, panel=panel,
                              story_id=story_id)
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    return rc, log, ctx, checks


def _n23(messages):
    return [m for m in messages if " N23 " in m]


def test_ct11_one_re_ask_then_the_landing_reply(ws, tmp_path, monkeypatch):
    rc, log, ctx, checks = _ct11(ws, tmp_path, monkeypatch, [_miss(1), _land(1)], [_land(2)])
    assert rc == 0
    assert [c["stage"] for c in log] == ["plan", "panel", "panel", "panel"]
    with open(os.path.join(ctx.story_dir, "story_rounds", "round_0", "panel_01_prompt_2.txt"),
              encoding="utf-8") as f:
        assert "- panel 1: N23 end frame landing: Motion: " in f.read()
    assert _n23([m["message"] for m in checks["hard"] + checks["advisory"]]) == []


def test_ct11_a_writer_that_misses_twice_is_kept_with_an_advisory(ws, tmp_path, monkeypatch):
    rc, log, ctx, checks = _ct11(ws, tmp_path, monkeypatch, [_miss(1), _miss(1)], [_land(2)])
    assert rc == 0
    assert [c["stage"] for c in log] == ["plan", "panel", "panel", "panel"]
    advisory = [m["message"] for m in checks["advisory"]]
    assert len(_n23(advisory)) == 1
    assert _n23(advisory)[0].startswith("panel 1: N23 end frame landing: Motion: has no camera "
                                        "sentence whose words after 'as the move completes,'")
    assert _n23([m["message"] for m in checks["hard"]]) == []
    hard = checks["hard"]
    rc2, advisories = se.recheck(ctx, ltx_movie._validate_story_md)
    assert rc2 == 0
    assert _n23(advisories) == _n23(advisory)
    assert _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["hard"] == hard


def test_ct11_no_re_ask_without_a_call_left(ws, tmp_path, monkeypatch):
    rc, log, ctx, checks = _ct11(ws, tmp_path, monkeypatch, [{"answer": "not json"}, _miss(1)],
                                 [_land(2)])
    assert rc == 0
    assert [(c["stage"], c["panel"]) for c in log] == [
        ("plan", None), ("panel", 1), ("panel", 1), ("panel", 2)]
    assert len(_n23([m["message"] for m in checks["advisory"]])) == 1


def test_ct11_writers_that_land_get_no_n23(ws, tmp_path, monkeypatch):
    rc, log, ctx, checks = _ct11(ws, tmp_path, monkeypatch, [_land(1)], [_land(2)])
    assert rc == 0
    assert [c["stage"] for c in log] == ["plan", "panel", "panel"]
    assert _n23([m["message"] for m in checks["hard"] + checks["advisory"]]) == []
    assert not any("N23" in " ".join(c["argv"]) for c in log)


# --- CT15: old stories re-check exactly as before (D10, CK3) --------------------------------------

def _forbid_end_frame_steps(monkeypatch):
    def forbidden(*_args, **_kw):
        raise AssertionError("an old story ran an end-frame step")
    for name in ("end_frame_words", "plan_end_frame_problems", "plan_copy_problems",
                 "end_frame_advisories"):
        monkeypatch.setattr(se, name, forbidden)


def _recheck_twice(ctx, monkeypatch):
    """(rc, hard, advisory) of se.recheck with RECHECK_IDS, then without N23."""
    out = []
    for ids in (se.RECHECK_IDS, tuple(i for i in se.RECHECK_IDS if i != "N23")):
        monkeypatch.setattr(se, "RECHECK_IDS", ids)
        rc, advisory = se.recheck(ctx, ltx_movie._validate_story_md)
        hard = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["hard"]
        out.append((rc, hard, advisory))
    return out


def test_ct15_old_stories_recheck_as_before(ws, monkeypatch):
    fixture = os.path.join(WS, "tests", "fixtures", "writer_pacing", "hockey-2x145-f")
    plan = _read_json(os.path.join(fixture, "plan.json"))
    hockey = seu.make_ctx(se, ws, story_id="hockey-2x145-f", panels=2, seconds="6",
                          clip_seconds=145 / 24.0, narration="speech", narrative=plan["narrative"],
                          goal=plan["goal"])
    for name in ("plan.json", "story.md"):
        shutil.copy(os.path.join(fixture, name), os.path.join(hockey.story_dir, name))
    courier = seu.make_ctx(se, ws, story_id="old-courier")
    old_plan = _normalized(courier, seu.plan_json("chained", 3))
    parts = [seu.panel_json("chained", k) for k in (1, 2, 3)]
    with open(os.path.join(courier.story_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(old_plan, f)
    with open(os.path.join(courier.story_dir, "story.md"), "w", encoding="utf-8") as f:
        f.write(se.assemble(courier, old_plan, parts))
    _forbid_end_frame_steps(monkeypatch)
    for ctx in (hockey, courier):
        with open(os.path.join(ctx.story_dir, "story.md"), "rb") as f:
            before = f.read()
        with_n23, without = _recheck_twice(ctx, monkeypatch)
        assert with_n23 == without, ctx.story_id
        assert with_n23[0] == 0, ctx.story_id
        with open(os.path.join(ctx.story_dir, "story.md"), "rb") as f:
            assert f.read() == before, ctx.story_id
```

- [ ] **Step 2: Run the tests to verify they fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_chained_end_frames.py 2>&1 | tail -1
```

Expected: `7 failed, 26 passed`. Of the 8 new tests only `test_ct11_writers_that_land_get_no_n23` passes: no N23 message exists yet, and this task must keep landing writers free of one (CK2).

- [ ] **Step 3: Write the implementation.**

**3.1.** The N23 functions (CE9). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    if notes:
        new["repairs"] = notes
    return new
```

with:

```python
    if notes:
        new["repairs"] = notes
    return new


# Chained end frames spec CE9, D7: N23, the camera sentence lands on the planned end frame.
END_FRAME_STOP_WORDS = frozenset("""
    a an the and or but nor of to in on at by for from with without into onto off over under up
    down out about across along around through toward towards behind beside between near past
    against as is are be being it its he she they him her them his hers their theirs this that
    these those there here who whom which what while where when one each both all every
    some""".split())


def end_frame_words(text, mention_words):
    """The content words of text (N23): its line_words that are neither END_FRAME_STOP_WORDS nor
    in mention_words (every word of every cast mention), as a set."""
    return set(w for w in line_words(text) if w not in END_FRAME_STOP_WORDS
               and w not in mention_words)


def end_frame_detail(lib, plan, k, text, phrases):
    """The N23 detail of panel k's assembled Motion text, or None (CE9). None when beat k has no
    end frame. The clause is end_clause of the first camera sentence (lib._is_camera_sentence with
    phrases) that has one. It fails when there is no such clause; when it does not name every cast
    entry the end frame names (_named_ids over _mentions); or when it shares fewer than
    (n + 1) // 2 of the end frame's n content words (end_frame_words)."""
    end_frame = plan["beats"][k - 1].get("end_frame", "")
    if not end_frame:
        return None
    clause = next((end_clause(s) for s in _sentences(text)
                   if lib._is_camera_sentence(s, phrases) and end_clause(s)), "")
    if not clause:
        return ("has no camera sentence whose words after 'as the move completes,' (or after "
                "'holding' for a static camera) describe the planned end frame %s"
                % _q(end_frame))
    mentions = _mentions(plan["cast"])
    named = _named_ids(line_words(clause), mentions)
    missing = [c for c in _named_ids(line_words(end_frame), mentions) if c not in named]
    if missing:
        return ("the camera sentence ends %s, which does not name %s, whom the planned end frame "
                "%s names" % (_q(clause), " and ".join(_q(speaker_phrase_of(plan, c))
                                                      for c in missing), _q(end_frame)))
    mention_words = set(w for _cid, words in mentions for w in words)
    want = end_frame_words(end_frame, mention_words)
    shared = len(want & end_frame_words(clause, mention_words))
    need = (len(want) + 1) // 2
    if shared < need:
        return ("the camera sentence ends %s, which shares %d of the %d content words of the "
                "planned end frame %s; it needs at least %d"
                % (_q(clause), shared, len(want), _q(end_frame), need))
    return None


def end_frame_landing_problems(ctx, plan, part, k):
    """[the hard N23 message] of panel k with writer parts part, or [] (CE9; round 0 only)."""
    if ctx.mode != "chained" or not plan["beats"][k - 1].get("end_frame"):
        return []
    parts = [{}] * (k - 1) + [part]
    motion = dict(panel_fields(ctx, plan, parts, k)).get("Motion", "")
    detail = end_frame_detail(_character_lib(ctx.ws), plan, k, motion, cast_phrases(ctx, plan))
    return ["panel %d: N23 end frame landing: Motion: %s" % (k, detail)] if detail else []
```

**3.2.** `_field_checks`' docstring (CE9). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    every check that needs the plan is skipped)."""
```

with:

```python
    every check that needs the plan is skipped). N23 is always advisory here (chained end frames
    spec CE9)."""
```

**3.3.** The N23 advisory (CE9). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
                                "words" % (prefix, label, ", ".join(_q(h) for h in hits[:3])))
    return hard, advisory
```

with:

```python
                                "words" % (prefix, label, ", ".join(_q(h) for h in hits[:3])))
        if "N23" in ids and ctx.mode == "chained":
            detail = end_frame_detail(lib, plan, k, dict(fields)[action_label], known)
            if detail:
                advisory.append("%s N23 end frame landing: %s: %s"
                                % (prefix, action_label, detail))
    return hard, advisory
```

**3.4.** `GENERATION_CHECKS` (CE12). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
GENERATION_CHECKS = ("N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11", "N12",
                     "N14", "N15", "N16", "N17", "N18", "T1", "T2", "T3", "N20", "N21", "N22",
                     "Q1", "N19")
```

with:

```python
GENERATION_CHECKS = ("N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11", "N12",
                     "N14", "N15", "N16", "N17", "N18", "T1", "T2", "T3", "N20", "N21", "N22",
                     "N23", "Q1", "N19")
```

**3.5.** N23 joins the round-0 re-ask (CE9). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
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
```

with:

```python
                # Shot prompt format spec SF13, D8: one re-ask for a writer-format problem while
                # the panel has a call left, then the deterministic trim; chained end frames spec
                # CE9: N23 joins the same single re-ask.
                problems = (format_problems(ctx, plan, new, k)
                            + end_frame_landing_problems(ctx, plan, new, k))
                if (problems and self.panel_calls[k] < PANEL_MAX_CALLS
                        and not self.expired()):
                    again = self.panel_call(plan, parts, k, 0, problems)
                    if (again is not None
                            and len(format_problems(ctx, plan, again, k)
                                    + end_frame_landing_problems(ctx, plan, again, k))
                            <= len(problems)):
                        parts[k - 1] = again
                parts[k - 1] = trim_format(ctx, plan, k, parts[k - 1])
```

**3.6.** `RECHECK_IDS` (CE12). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
RECHECK_IDS = ("N1", "N2", "N3", "N4", "N7", "N8", "N9", "N10", "N11", "N12", "N14", "N15",
               "N16", "N17", "N18", "T1", "T2", "T3", "Q1", "N19")
```

with:

```python
RECHECK_IDS = ("N1", "N2", "N3", "N4", "N7", "N8", "N9", "N10", "N11", "N12", "N14", "N15",
               "N16", "N17", "N18", "T1", "T2", "T3", "N23", "Q1", "N19")
```

- [ ] **Step 4: Run the tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_chained_end_frames.py 2>&1 | tail -1
```

Expected: `33 passed`.

The compile check with `FILES` = `story_engine.py tests/test_chained_end_frames.py`. Expected: `compiled 2` twice.

The gate block with `N=3`. Expected: `GATE PASS`, `lost 29 (listed 29, unexpected 0); new tests 33, not passing 0`, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
git add story_engine.py tests/test_chained_end_frames.py
git diff --cached --name-only    # expected: only those 2 paths
git commit -m "feat(story-engine): N23, the camera clause lands on the planned end frame: one round-0 re-ask, then an advisory (chained end frames CE9, CE12; CT10, CT11, CT15)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 4: What writer k is told, and the format reference (CE8, CE11; CT1 part, CT9, CT14)

This task implements:
- CE8: `OPENS_ON_LINE`, `ENDS_ON_LINE` and `ENDS_ON_STATIC_LINE`, after `SPEAKING_STAY_SENTENCE`.
  - `build_panel_prompt` adds them to the `@@PREVIOUS@@` fragment of a chained panel. Panel k opens on beat k-1's end frame, and ends on its own end frame; a static panel names "holding".
- CE11:
  - `FORMAT_REFERENCE` becomes the finished shots of `PLAN_REFERENCE`'s beats, with opens-on and ends-on labels (3538 characters, 618 words, sha256 `990aeb28…`).
  - `REFERENCE_TERMS` gains `"half-open shutter"` and `REFERENCE_COPY_SEGMENTS` is replaced (80 six-word runs).
  - `reference_copies` exempts the plan's end frames.

Tests: CT1 (Task 4 part), CT9 and CT14, appended to `tests/test_chained_end_frames.py`. CT14's corpus guard removes a verbatim plan reference first, because Task 7 re-baselines six plan-prompt fixtures that quote it (Plan ruling R13).

**Files:**
- Modify: `tests/test_chained_end_frames.py` (append).
- Modify: `story_engine.py`: `FORMAT_REFERENCE` and its comment `:2503-2535`, `REFERENCE_TERMS`/`REFERENCE_COPY_SEGMENTS` `:2536-2558`, `reference_copies` `:2568-2578`, `SPEAKING_STAY_SENTENCE` `:2774-2775`, `build_panel_prompt` `:3661-3664`.

**Interfaces:**
- Consumes: Task 2's `PLAN_REFERENCE_PLAN` and `PLAN_REFERENCE_SIX_GRAMS`; Task 3's `end_frame_detail`; existing `_sentence`, `panel_camera`, `panel_fields`, `cap_static_cameras`, `build_panel_prompt`.
- Produces: `OPENS_ON_LINE`, `ENDS_ON_LINE`, `ENDS_ON_STATIC_LINE`, the new `FORMAT_REFERENCE`, `REFERENCE_TERMS`, `REFERENCE_COPY_SEGMENTS` and `REFERENCE_SIX_GRAMS`.

- [ ] **Step 1: Write the failing tests.**

Append to the test file. Edit `tests/test_chained_end_frames.py`: replace this text, which occurs exactly once:

```python
        with open(os.path.join(ctx.story_dir, "story.md"), "rb") as f:
            assert f.read() == before, ctx.story_id
```

with:

```python
        with open(os.path.join(ctx.story_dir, "story.md"), "rb") as f:
            assert f.read() == before, ctx.story_id


# --- CT1 (Task 4 part): the writer constants (CE8, CE11) -----------------------------------------

OPENS_ON_LINE = ("This panel opens on: %s Start the action from exactly this composition; do "
                 "not describe it.\n")
ENDS_ON_LINE = ("This panel ends on: %s The clause after 'as the move completes,' in your camera "
                "sentence must describe this end frame.\n")
ENDS_ON_STATIC_LINE = ("This panel ends on: %s The words after 'holding' in your camera "
                       "sentence must describe this end frame.\n")
REFERENCE_COPY_SEGMENTS = (
    "The old fishmonger drags a tall stack of empty herring crates across the wet concrete of "
    "the market hall toward the half-open shutter",
    "her heavy steps splashing through shallow puddles that hold the first glow from the "
    "harbour doors",
    "The old fishmonger turns back from the shutter and walks to the zinc counter",
    "laying her folded cloth beside the empty ice trays",
    "The old fishmonger presses both palms flat on the folded cloth, her shoulders sinking",
    "The old fishmonger lowers her forehead onto her folded hands on the cold zinc counter",
    "her breath fogging the metal as a thin trickle of meltwater runs past her knuckles and "
    "drips to the wet floor",
    "Forty years of mornings. Not one more.",
)


def test_ct1d_the_writer_constants():
    assert se.OPENS_ON_LINE == OPENS_ON_LINE
    assert se.ENDS_ON_LINE == ENDS_ON_LINE
    assert se.ENDS_ON_STATIC_LINE == ENDS_ON_STATIC_LINE
    assert se.REFERENCE_TERMS[-1] == "half-open shutter"
    assert se.REFERENCE_TERMS[:-1] == ("fishmonger", "fishmongers", "herring", "herrings", "zinc",
                                       "ice trays", "market hall", "fish market", "harbour doors",
                                       "meltwater", "forty years of mornings")
    assert se.REFERENCE_COPY_SEGMENTS == REFERENCE_COPY_SEGMENTS
    for text in (OPENS_ON_LINE, ENDS_ON_LINE, ENDS_ON_STATIC_LINE, se.FORMAT_REFERENCE):
        assert "slowly" not in text.lower(), text[:40]


# --- CT9: what writer k is told (CE8) --------------------------------------------------------------

def _writer_prompts(ws, raw):
    """The three panel prompts of a chained 3-panel plan (after the P18 cap) and its plan."""
    ctx = seu.make_ctx(se, ws)
    plan = _normalized(ctx, raw)
    se.cap_static_cameras(ctx, plan)
    parts = [seu.panel_json("chained", k) for k in (1, 2, 3)]
    return [se.build_panel_prompt(ctx, plan, parts, k) for k in (1, 2, 3)], plan, ctx, parts


def test_ct9_the_writer_is_told_where_it_opens_and_ends(ws):
    prompts, plan, ctx, parts = _writer_prompts(ws, ef_plan(3))
    assert [b["camera"] for b in plan["beats"]] == ["slow push-in", "tracking", "static"]
    ef1, ef2, ef3 = (END_FRAME % k for k in (1, 2, 3))
    assert ENDS_ON_LINE % ef1 in prompts[0]
    assert "This panel opens on:" not in prompts[0]
    motion1 = dict(se.panel_fields(ctx, plan, parts, 1))["Motion"]
    assert ("The previous panel's Motion: " + motion1 + "\n" + OPENS_ON_LINE % ef1
            + ENDS_ON_LINE % ef2 + "\n" + se.FORMAT_REFERENCE) in prompts[1]
    assert OPENS_ON_LINE % ef2 + ENDS_ON_STATIC_LINE % ef3 in prompts[2]
    assert ENDS_ON_LINE % ef3 not in prompts[2]
    for prompt in prompts:
        assert "@@" not in prompt and prompt.count(se.FORMAT_REFERENCE) == 1
    plain, _plan, _ctx, _parts = _writer_prompts(ws, seu.plan_json("chained", 3))
    for prompt in plain:
        assert "This panel opens on:" not in prompt and "This panel ends on:" not in prompt
        assert "@@" not in prompt and prompt.count(se.FORMAT_REFERENCE) == 1
    raw = ef_plan(3)
    raw["beats"][1]["end_frame"] = "  The courier waits at frame centre, facing left, seen from the waist up  "
    prompts, _plan, _ctx, _parts = _writer_prompts(ws, raw)
    assert (OPENS_ON_LINE % "The courier waits at frame centre, facing left, seen from the waist up."
            in prompts[2])


# --- CT14: the format reference (CE11) -------------------------------------------------------------

REF_PHRASE = "the old fishmonger"
REF_SHOTS = ("The shot is a medium shot.", "The shot is a medium shot.", "The shot is a close-up.")
REF_SPEAKERS = (None, "the old fishmonger", None)
REF_LINES = ("", "Forty years of mornings. Not one more.", "")


def ref_shots():
    """The three "Shot N" texts of se.FORMAT_REFERENCE: each line's text after its "): "."""
    return [line.split("): ", 1)[1] for line in se.FORMAT_REFERENCE.split("\n")
            if line.startswith("Shot ")]


def test_ct14_the_format_reference_is_pinned(ws):
    reference = se.FORMAT_REFERENCE
    assert hashlib.sha256(reference.encode("utf-8")).hexdigest() == (
        "990aeb28a929b910786b30cef2288cb16ed9910b88a3d7011778d31f4ca96efe")
    assert (len(reference), len(reference.split())) == (3538, 618)
    assert "@@" not in reference and "{" not in reference
    shots = ref_shots()
    assert len(shots) == 3
    for k, shot in enumerate(shots, start=1):
        assert lib.panel_prompt(REF_MOTIONS[k - 1], REF_SHOTS[k - 1], REF_SPEAKERS[k - 1],
                                REF_LINES[k - 1], "beats", [REF_PHRASE]) == shot, k
    for k, key in enumerate(("slow tracking right", "slow push-in", "static"), start=1):
        assert se.camera_problem(lib, REF_MOTIONS[k - 1], [REF_PHRASE], key) is None, key
        assert se.end_frame_detail(lib, se.PLAN_REFERENCE_PLAN, k, REF_MOTIONS[k - 1],
                                   [REF_PHRASE]) is None, k
    labels = [line.split("): ", 1)[0] for line in reference.split("\n") if line.startswith("Shot ")]
    frames = [b["end_frame"].rstrip(".") for b in se.PLAN_REFERENCE_PLAN["beats"]]
    assert "ends on: " + frames[0] in labels[0] and "opens on" not in labels[0]
    for k in (2, 3):
        assert "opens on: " + frames[k - 2] + "; ends on: " + frames[k - 1] in labels[k - 1], k
    for segment in se.REFERENCE_COPY_SEGMENTS[:-1]:
        assert segment in reference, segment
    assert len(se.REFERENCE_SIX_GRAMS) == 80
    assert reference.count(lib.ACOUSTIC_SENTENCE) == 1
    assert reference.count(lib.AMBIENCE_SENTENCE) == 2


def test_ct14_no_fixture_copies_either_reference():
    """The corpus guard. The plan prompt fixtures re-baselined in the test-only commit (CR3)
    quote PLAN_REFERENCE whole; that quote is removed first (Plan ruling CR-A)."""
    fixtures = os.path.join(WS, "tests", "fixtures")
    grams = se.REFERENCE_SIX_GRAMS | se.PLAN_REFERENCE_SIX_GRAMS
    seen = 0
    for root, _dirs, names in os.walk(fixtures):
        for name in names:
            with open(os.path.join(root, name), encoding="utf-8") as f:
                text = f.read()
            for reference in (se.plan_reference(True), se.plan_reference(False)):
                text = text.replace(reference, "")
            words = se.line_words(text)
            seen += 1
            line = " " + " ".join(words) + " "
            assert not (se._six_grams(words) & grams), name
            assert [t for t in se.REFERENCE_TERMS
                    if " %s " % " ".join(se.line_words(t)) in line] == [], name
    assert seen >= 40
```

- [ ] **Step 2: Run the tests to verify they fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_chained_end_frames.py 2>&1 | tail -1
```

Expected: `3 failed, 37 passed`. Of the 4 new tests only `test_ct14_no_fixture_copies_either_reference` passes: no fixture copies either reference today, and none may after this task.

- [ ] **Step 3: Write the implementation.**

**3.1.** The format reference (CE11). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
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
```

with:

```python
# Shot prompt format spec SF8, D9: three finished shots of an unrelated movie, shown to the
# chained and shots writer for their order only. Each "Shot N" text is exactly
# character_lib.panel_prompt of its parts (SFT13); chained end frames spec CE11: the finished
# shots of PLAN_REFERENCE's beats, with opens-on and ends-on labels.
FORMAT_REFERENCE = (
    "FORMAT REFERENCE ONLY — never reuse its people, places, objects or words. These are the "
    "finished video prompts of three shots from a different movie. They show the order of "
    "every finished shot: the shot type; the action; when someone speaks, the spoken line and "
    "then one short reaction by the speaker; the one camera sentence, which says where the "
    "move ends; and the audio last. The pipeline wrote the sentences that start \"The shot "
    "is\", the sentence \"The old fishmonger faces the camera.\", the spoken line and the "
    "audio sentence; the writer wrote every other sentence. Each label names the frame its "
    "shot opens on and the frame it ends on: the action starts from the opening frame without "
    "describing it, and the words after 'as the move completes,' or 'holding' in the camera "
    "sentence describe the end frame. Double quotes appear only around the spoken line.\n"
    "Shot 1 (silent; the camera tracks right; ends on: The old fishmonger stands beside the "
    "half-open shutter at frame centre, facing left toward the hall, seen from the knees up, "
    "the empty crates at her feet): The shot is a medium shot. The old fishmonger drags a tall "
    "stack of empty herring crates across the wet concrete of the market hall toward the "
    "half-open shutter at real-time speed, her heavy steps splashing through shallow puddles "
    "that hold the first glow from the harbour doors. The camera tracks right alongside her — "
    "as the move completes, the old fishmonger stands beside the half-open shutter at frame "
    "centre, facing left toward the hall, seen from the knees up, the empty crates at her "
    "feet. The audio is the natural ambient sound of the place, with no music.\n"
    "Shot 2 (speaking; the camera pushes in; opens on: The old fishmonger stands beside the "
    "half-open shutter at frame centre, facing left toward the hall, seen from the knees up, "
    "the empty crates at her feet; ends on: The old fishmonger stands behind the zinc counter "
    "at frame centre, facing forward, her face filling the frame from chin to brow): The shot "
    "is a medium shot. The old fishmonger turns back from the shutter and walks to the zinc "
    "counter at real-time speed, laying her folded cloth beside the empty ice trays and "
    "lifting her face to the camera. The old fishmonger faces the camera. The old fishmonger "
    "says, \"Forty years of mornings.\" After a breath, \"Not one more.\" The old fishmonger "
    "presses both palms flat on the folded cloth, her shoulders sinking. The camera pushes in "
    "— as the move completes, the old fishmonger stands behind the zinc counter at frame "
    "centre, facing forward, her face filling the frame from chin to brow. The audio is clear "
    "close-mic dialogue with a subtle natural room tone; the dialogue takes priority over the "
    "quiet ambience, and there is no music.\n"
    "Shot 3 (silent; the movie's one deliberate static hold; opens on: The old fishmonger "
    "stands behind the zinc counter at frame centre, facing forward, her face filling the "
    "frame from chin to brow; ends on: The old fishmonger rests her forehead on her folded "
    "hands at frame centre, eyes closed, her head and hands filling the frame in a close-up): "
    "The shot is a close-up. The old fishmonger lowers her forehead onto her folded hands on "
    "the cold zinc counter at real-time speed, her breath fogging the metal as a thin trickle "
    "of meltwater runs past her knuckles and drips to the wet floor. The camera stays static, "
    "holding the old fishmonger as she rests her forehead on her folded hands at frame centre, "
    "eyes closed, her head and hands filling the frame. The audio is the natural ambient sound "
    "of the place, with no music.\n"
    "\n")
```

**3.2.** The N22 terms and segments (CE11). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
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
```

with:

```python
# Shot prompt format spec SF12, D11: the reference's own names, props and wording.
REFERENCE_TERMS = ("fishmonger", "fishmongers", "herring", "herrings", "zinc", "ice trays",
                   "market hall", "fish market", "harbour doors", "meltwater",
                   "forty years of mornings", "half-open shutter")
REFERENCE_COPY_SEGMENTS = (
    "The old fishmonger drags a tall stack of empty herring crates across the wet concrete of "
    "the market hall toward the half-open shutter",
    "her heavy steps splashing through shallow puddles that hold the first glow from the "
    "harbour doors",
    "The old fishmonger turns back from the shutter and walks to the zinc counter",
    "laying her folded cloth beside the empty ice trays",
    "The old fishmonger presses both palms flat on the folded cloth, her shoulders sinking",
    "The old fishmonger lowers her forehead onto her folded hands on the cold zinc counter",
    "her breath fogging the metal as a thin trickle of meltwater runs past her knuckles and "
    "drips to the wet floor",
    "Forty years of mornings. Not one more.",
)
```

**3.3.** `reference_copies` exempts the end frames (CE11). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
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
```

with:

```python
def reference_copies(narrative, plan, text, goal=None):
    """The REFERENCE_TERMS terms and the six-word REFERENCE_COPY_SEGMENTS runs that text copies
    from FORMAT_REFERENCE, in that order (SF12), leaving out any that the narrative, the goal or
    the plan (cast phrases and descriptors, settings, prop names, beat actions and end frames;
    chained end frames spec CE11) already has."""
    own = [narrative or "", goal or ""]
    if plan:
        own += ([c.get("phrase") or "" for c in plan["cast"]]
                + [c.get("descriptor") or "" for c in plan["cast"]]
                + [l.get("setting") or "" for l in plan["locations"]]
                + [p.get("name") or "" for p in plan["props"]]
                + [b.get("action") or "" for b in plan["beats"]]
                + [b.get("end_frame") or "" for b in plan["beats"]])
```

**3.4.** The opens-on and ends-on lines (CE8). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
SPEAKING_STAY_SENTENCE = (" In this whole panel @@SPEAKER@@ never leaves, turns away or moves "
                          "out of the frame, even when the beat says so.")
```

with:

```python
SPEAKING_STAY_SENTENCE = (" In this whole panel @@SPEAKER@@ never leaves, turns away or moves "
                          "out of the frame, even when the beat says so.")
# Chained end frames spec CE8, D5: writer k starts from end frame k-1 and lands on end frame k.
OPENS_ON_LINE = ("This panel opens on: %s Start the action from exactly this composition; do "
                 "not describe it.\n")
ENDS_ON_LINE = ("This panel ends on: %s The clause after 'as the move completes,' in your camera "
                "sentence must describe this end frame.\n")
ENDS_ON_STATIC_LINE = ("This panel ends on: %s The words after 'holding' in your camera "
                       "sentence must describe this end frame.\n")
```

**3.5.** Writer k is told where it opens and ends (CE8). Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    previous = ""
    if ctx.mode == "chained" and k >= 2:
        previous = ("The previous panel's Motion: "
                    + dict(panel_fields(ctx, plan, parts, k - 1))["Motion"] + "\n")
```

with:

```python
    previous = ""
    if ctx.mode == "chained" and k >= 2:
        previous = ("The previous panel's Motion: "
                    + dict(panel_fields(ctx, plan, parts, k - 1))["Motion"] + "\n")
    if ctx.mode == "chained":
        opens = plan["beats"][k - 2].get("end_frame", "") if k >= 2 else ""
        ends = beat.get("end_frame", "")
        if opens:
            previous += OPENS_ON_LINE % _sentence(opens)
        if ends:
            previous += ((ENDS_ON_STATIC_LINE if panel_camera(ctx, plan, k) == "static"
                          else ENDS_ON_LINE) % _sentence(ends))
```

- [ ] **Step 4: Run the tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_chained_end_frames.py 2>&1 | tail -1
```

Expected: `40 passed`.

The compile check with `FILES` = `story_engine.py tests/test_chained_end_frames.py`. Expected: `compiled 2` twice.

The gate block with `N=4`. Expected: `GATE PASS`, `lost 33 (listed 33, unexpected 0); new tests 40, not passing 0`, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
git add story_engine.py tests/test_chained_end_frames.py
git diff --cached --name-only    # expected: only those 2 paths
git commit -m "feat(story-engine): writers are told where each panel opens and ends; the format reference becomes the reference plan's finished shots (chained end frames CE8, CE11; CT9, CT14)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 5: `bin/seam-report` (CE13; CT1 part, CT17-CT22, CT30, Review Focus 1, 2)

This task implements spec Section 3 in one new executable, `bin/seam-report`:
- the CLI and its exit codes;
- the order of work (steps 1-10), where the first exit wins;
- frame sources: a chainseed only when it is non-empty and not older than its clip;
- `last_frame_png`, with bin/judge-clips' ffprobe and ffmpeg argv;
- the loopback probe and calls, the retry rule and the verdicts;
- the two report files, written to `<path>.tmp` and then `os.replace`, and the stdout lines.

Where the spec leaves a detail open, Plan ruling R8 records the choice: the `SeamError` detail texts, the `source` of an unreadable clip, and the one temporary directory per run.

Tests: CT17-CT22, CT30 and Review Focus 1 and 2 in the new `tests/test_seam_report.py`, and the CT1 compile part appended to `tests/test_chained_end_frames.py`.
- The module is loaded by path as `seam_report_for_tests`.
- An autouse fixture sets HOME and the temporary directory under `tmp_path`, and replaces `http.client.HTTPConnection` with one that fails the test.
- Every story lives in a temporary workspace that `seam.WS` points at.

**Files:**
- Create: `bin/seam-report` (mode 0755), `tests/test_seam_report.py`.
- Modify: `tests/test_chained_end_frames.py` (append).
- Read only: `bin/judge-clips` `probe_clip` `:291-318`, `extract_frames` `:328-351` (the argv this copies); `story_engine.py` `extract_json` `:272`; `bin/story-server` `:42` (`STORY_SERVER_PORT`).

**Interfaces:**
- Consumes: `story_engine.extract_json(text) -> dict or None`, loaded lazily from `WS/story_engine.py`.
- Produces (spec Section 3's module functions; Task 6 runs the script):
  - `main(argv=None) -> int`, `build_parser()`, `frame_sources(plan, clips_dir) -> [(k, end_frame, source, path)]`;
  - `last_frame_png(clip, out_png)`, `vlm_models(port) -> (model, None) or (None, what)`;
  - `vlm_complete(port, model, prompt, png) -> str or None`, which raises `TransportError(what)`;
  - `seam_prompt(plan, k) -> str`, `parse_reply(content) -> dict or None`, `render_md(doc) -> str`, `_utc() -> str`;
  - `SeamError`, `TransportError`, and the Section 3 constants.

- [ ] **Step 1: Write the failing tests.**

**1.1.** Create `tests/test_seam_report.py` with exactly this content (the Write tool; the file ends with one newline):

````python
"""Tests for bin/seam-report (docs/superpowers/specs/2026-10-30-chained-end-frames-design.md,
Sections 3 and 6: CT17-CT22 and CT30, with the plan's Review Focus pins 1 and 2).

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_seam_report.py
Stdlib plus pytest. No test renders, reads the real HOME, or contacts a model server, a daemon,
ffmpeg or the Anthropic API: the VLM (vlm_models, vlm_complete), ffmpeg (last_frame_png and
shutil.which) and http.client.HTTPConnection are monkeypatched, HOME and the temporary directory
are under tmp_path, and every story lives in a temporary workspace.
"""

import ast
import http.client
import importlib.machinery
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SEAM = os.path.join(WS, "bin", "seam-report")
seam = importlib.machinery.SourceFileLoader("seam_report_for_tests", SEAM).load_module()

COURIER = ("a young man with short brown hair and a lean build wearing a yellow rain jacket and "
           "grey trousers")
E1 = "The courier stands at frame centre on the wet quay, facing the camera, seen from the waist up."
E2 = "The courier stands at the left edge beside the boats, facing right, seen from the knees up."
E3 = "The courier holds out the sealed letter at frame centre, facing the camera, in a close-up."
SEED2 = b"\x89PNG\r\n\x1a\nseed-of-panel-2"
SEED3 = b"\x89PNG\r\n\x1a\nseed-of-panel-3"
LAST_PNG = b"\x89PNG\r\n\x1a\nlast-frame-of-a-clip"
MP4 = b"\x00\x00\x00\x18ftypmp42"
CREATED = "2026-10-31T12:00:00Z"
DOWN = ("Error: the story server is not answering at 127.0.0.1:8177 (%s); nothing was changed. "
        "Start it with bin/story-server mlx-vision and rerun bin/seam-report %s.\n")
STOPPED = ("Error: the story server stopped answering at 127.0.0.1:8177 (%s) while checking "
           "panel %d; nothing was written. Start it with bin/story-server mlx-vision and rerun "
           "bin/seam-report %s.\n")


@pytest.fixture(autouse=True)
def isolation(monkeypatch, tmp_path):
    """A temporary HOME and temporary directory, no STORY_SERVER_PORT, and no real network."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("STORY_SERVER_PORT", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    temp = tmp_path / "tmp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))

    def no_network(*_args, **_kw):
        raise AssertionError("a test opened an HTTP connection")
    monkeypatch.setattr(http.client, "HTTPConnection", no_network)
    return {"home": str(home), "temp": str(temp)}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """<tmp>/ws with generated/stories/ and story_engine.py symlinked; seam.WS points at it."""
    root = tmp_path / "ws"
    (root / "generated" / "stories").mkdir(parents=True)
    os.symlink(os.path.join(WS, "story_engine.py"), str(root / "story_engine.py"))
    monkeypatch.setattr(seam, "WS", str(root))
    monkeypatch.setattr(seam, "_utc", lambda: CREATED)
    return str(root)


def _plan(frames=(E1, E2, E3), mode="chained", casts=None):
    """A plan.json document whose beat k has end_frame frames[k - 1] (none when None)."""
    beats = []
    for k, frame in enumerate(frames, start=1):
        beat = {"index": k, "arc": "rising", "action": "the courier rides on", "shot": "medium shot",
                "camera": "slow push-in", "location": "l1",
                "cast": list((casts or {}).get(k, ["c1"])), "speaker": "", "lines": []}
        if frame is not None:
            beat["end_frame"] = frame
        beats.append(beat)
    return {"schema": "ltx-movie.plan.v1", "story_id": "sr1", "mode": mode, "panels": len(beats),
            "cast": [{"id": "c1", "phrase": "the courier", "descriptor": COURIER, "cast_name": None},
                     {"id": "c2", "phrase": "the old monk", "descriptor": "an old man in a robe",
                      "cast_name": None}],
            "beats": beats}


def _story(ws, plan, story_id="sr1", files=()):
    """generated/stories/<story_id>/ with plan (a dict, or raw text; None: no plan.json) and
    files [(relpath, bytes, mtime)]; returns the story directory."""
    sdir = os.path.join(ws, "generated", "stories", story_id)
    os.makedirs(os.path.join(sdir, "clips"), exist_ok=True)
    if plan is not None:
        with open(os.path.join(sdir, "plan.json"), "w", encoding="utf-8") as f:
            f.write(plan if isinstance(plan, str) else json.dumps(plan))
    for rel, data, mtime in files:
        path = os.path.join(sdir, rel)
        with open(path, "wb") as f:
            f.write(data)
        os.utime(path, (mtime, mtime))
    return sdir


def _reports(sdir):
    return sorted(n for n in os.listdir(sdir) if n.startswith("seam_report"))


class FakeVLM(object):
    """vlm_models and vlm_complete stand-ins: replies are returned (an Exception is raised) in
    order; calls records (port, model, prompt, png)."""

    def __init__(self, replies, model="test-vlm"):
        self.replies = list(replies)
        self.model = model
        self.calls = []
        self.ports = []

    def models(self, port):
        self.ports.append(port)
        return self.model, None

    def complete(self, port, model, prompt, png):
        self.calls.append((port, model, prompt, png))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _vlm(monkeypatch, replies, model="test-vlm"):
    fake = FakeVLM(replies, model)
    monkeypatch.setattr(seam, "vlm_models", fake.models)
    monkeypatch.setattr(seam, "vlm_complete", fake.complete)
    return fake


def _ffmpeg(monkeypatch, fail=None):
    """shutil.which finds ffmpeg and ffprobe; last_frame_png writes LAST_PNG, or raises
    SeamError(fail). Returns the clip names it was called with."""
    monkeypatch.setattr(seam.shutil, "which", lambda name: "/opt/fake/bin/" + name)
    calls = []

    def fake(clip, out_png):
        calls.append(os.path.basename(clip))
        if fail is not None:
            raise seam.SeamError(fail)
        with open(out_png, "wb") as f:
            f.write(LAST_PNG)
    monkeypatch.setattr(seam, "last_frame_png", fake)
    return calls


def _reply(score, reason, missing=()):
    return json.dumps({"score": score, "reason": reason, "missing": list(missing)})


def _run(argv, capsys):
    rc = seam.main(argv)
    out, err = capsys.readouterr()
    return rc, out, err


# --- CT17: nothing to check (CE13 steps 3-5) -------------------------------------------------------

def test_ct17_nothing_to_check(ws, monkeypatch, capsys):
    def never(*_args):
        raise AssertionError("the story server was contacted")
    monkeypatch.setattr(seam, "vlm_models", never)
    sdir = _story(ws, _plan(mode="shots"), "shots-story")
    assert _run(["shots-story"], capsys) == (0, "seam-report: nothing to check: shots-story is a "
                                             "shots story; seams are checked only in chained "
                                             "stories\n", "")
    assert _reports(sdir) == []
    sdir = _story(ws, _plan(frames=(None, None)), "no-frames")
    assert _run(["no-frames"], capsys) == (
        0, "seam-report: nothing to check: this plan has no end frames; no seam report\n", "")
    assert _reports(sdir) == []
    sdir = _story(ws, _plan(frames=("   ", None)), "blank-frames")
    assert _run(["blank-frames"], capsys)[1] == (
        "seam-report: nothing to check: this plan has no end frames; no seam report\n")
    sdir = _story(ws, _plan(), "no-clips")
    assert _run(["no-clips"], capsys) == (
        0, "seam-report: no clips to check in %s\n" % os.path.join(sdir, "clips"), "")
    assert _reports(sdir) == []


def test_ct17_the_script_as_a_subprocess(tmp_path):
    root = tmp_path / "sub"
    (root / "bin").mkdir(parents=True)
    shutil.copy(SEAM, str(root / "bin" / "seam-report"))
    os.symlink(os.path.join(WS, "story_engine.py"), str(root / "story_engine.py"))
    sdir = _story(str(root), _plan(), "sub-story")
    env = dict(os.environ, HOME=str(tmp_path / "home"))
    proc = subprocess.run([sys.executable, str(root / "bin" / "seam-report"), "sub-story"],
                          capture_output=True, text=True, env=env, timeout=60)
    clips = os.path.join(os.path.realpath(str(root)), "generated", "stories", "sub-story", "clips")
    assert (proc.returncode, proc.stdout, proc.stderr) == (
        0, "seam-report: no clips to check in %s\n" % clips, "")
    assert _reports(sdir) == []


# --- CT18: preconditions (CE13 CLI and steps 1, 2, 6) ---------------------------------------------

def test_ct18_preconditions(ws, monkeypatch, capsys):
    stories = os.path.join(ws, "generated", "stories")
    for bad in ("bad/../id", "a..b", ".hidden", "x" * 81):
        assert _run([bad], capsys) == (2, "", "Error: invalid story id: %s\n" % bad), bad
    assert _run(["nope"], capsys) == (2, "", "Error: no story nope in %s\n" % stories)
    for story_id, plan in (("missing", None), ("not-json", "{not json"),
                           ("wrong-schema", dict(_plan(), schema="ltx-movie.plan.v0")),
                           ("no-mode", dict(_plan(), mode=None)),
                           ("no-beats", dict(_plan(), beats={})), ("a-list", "[]")):
        sdir = _story(ws, plan, story_id)
        path = os.path.join(sdir, "plan.json")
        assert _run([story_id], capsys) == (
            2, "", "Error: %s is not a plan.json written by bin/ltx-movie's default story "
                   "engine\n" % path), story_id
        assert _reports(sdir) == []
    sdir = _story(ws, _plan(), "no-ffmpeg", files=[("clips/panel_01.mp4", MP4, 1000)])
    monkeypatch.setattr(seam.shutil, "which", lambda name: None if name == "ffprobe" else "/x")
    assert _run(["no-ffmpeg"], capsys) == (
        2, "", "Error: ffmpeg and ffprobe must be on PATH to read the clips in %s\n"
        % os.path.join(sdir, "clips"))
    assert _reports(sdir) == []
    for argv in ([], ["a", "b"], ["sr1", "--port", "x"]):
        with pytest.raises(SystemExit) as exit_info:
            seam.main(argv)
        assert exit_info.value.code == 2, argv
    capsys.readouterr()
    assert seam.build_parser().parse_args(["sr1"]).port == 8177
    monkeypatch.setenv("STORY_SERVER_PORT", "9123")
    assert seam.build_parser().parse_args(["sr1"]).port == 9123
    assert seam.build_parser().parse_args(["sr1", "--port", "8188"]).port == 8188


# --- CT19: the story server is down (CE13 steps 7, 8) --------------------------------------------

def test_ct19_server_down_at_the_probe(ws, monkeypatch, capsys, isolation):
    sdir = _story(ws, _plan(), files=[("clips/panel_02.chainseed.png", SEED2, 2000)])
    with open(os.path.join(sdir, "seam_report.json"), "wb") as f:
        f.write(b"an older report\n")
    monkeypatch.setattr(seam, "vlm_models", lambda port: (None, "ConnectionRefusedError"))
    assert _run(["sr1"], capsys) == (2, "", DOWN % ("ConnectionRefusedError", "sr1"))
    with open(os.path.join(sdir, "seam_report.json"), "rb") as f:
        assert f.read() == b"an older report\n"
    assert _reports(sdir) == ["seam_report.json"]
    assert os.listdir(isolation["temp"]) == []


def test_ct19_server_stops_while_checking(ws, monkeypatch, capsys, isolation):
    sdir = _story(ws, _plan(), files=[("clips/panel_02.chainseed.png", SEED2, 2000),
                                      ("clips/panel_03.chainseed.png", SEED3, 2000)])
    _ffmpeg(monkeypatch)
    fake = _vlm(monkeypatch, [_reply(8, "Fine."), seam.TransportError("HTTP 503")])
    assert _run(["sr1"], capsys) == (2, "", STOPPED % ("HTTP 503", 2, "sr1"))
    assert len(fake.calls) == 2
    assert _reports(sdir) == []
    assert os.listdir(isolation["temp"]) == []


# --- CT20: verdicts and the report (CE13 steps 5, 8-10; CK6) ---------------------------------------

def _three_panel_story(ws):
    return _story(ws, _plan(), files=[("clips/panel_01.mp4", MP4, 1000),
                                      ("clips/panel_02.mp4", MP4, 1000),
                                      ("clips/panel_03.mp4", MP4, 1000),
                                      ("clips/panel_02.chainseed.png", SEED2, 2000),
                                      ("clips/panel_03.chainseed.png", SEED3, 2000)])


EXPECTED_MD = """# Seam report: sr1

Created 2026-10-31T12:00:00Z with test-vlm. A score below 6 is missed.

| Panel | Score | Verdict | Reason | Missing |
|---|---|---|---|---|
| 1 | 8 | ok | The courier stands at frame centre. | - |
| 2 | 5 | missed | The courier faces left, not right. | facing right; seen from the knees up |
| 3 | 6 | ok | Close to the plan. | the sealed letter |

Mean score 6.33 over 3 scored panel(s); 1 missed, 0 without a clip, 0 unparseable.

## Planned end frames

- panel 1: %s
- panel 2: %s
- panel 3: %s
""" % (E1, E2, E3)


def test_ct20_verdicts_sources_and_the_report(ws, monkeypatch, capsys):
    sdir = _three_panel_story(ws)
    clips = _ffmpeg(monkeypatch)
    fake = _vlm(monkeypatch, [
        _reply(8, "The courier stands at frame centre."),
        _reply(5, "The courier  faces left,\nnot right.", [" facing right ", "seen from the knees up", "  "]),
        _reply(6, "Close to the plan.", ["the sealed letter"])])
    rc, out, err = _run(["sr1"], capsys)
    json_path, md_path = (os.path.join(sdir, "seam_report.json"),
                          os.path.join(sdir, "seam_report.md"))
    assert (rc, err) == (0, "")
    assert out == (
        "panel 1: ok (8/10): The courier stands at frame centre.\n"
        "panel 2: missed (5/10): The courier faces left, not right.; missing: facing right; seen "
        "from the knees up\n"
        "panel 3: ok (6/10): Close to the plan.\n"
        "seam-report: wrote %s and %s: 1 of 3 panel(s) missed, mean score 6.33\n"
        % (json_path, md_path))
    assert clips == ["panel_03.mp4"]
    assert [c[3] for c in fake.calls] == [SEED2, SEED3, LAST_PNG]
    assert [(c[0], c[1]) for c in fake.calls] == [(8177, "test-vlm")] * 3
    assert fake.ports == [8177]
    with open(json_path, encoding="utf-8") as f:
        text = f.read()
    assert text == json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n"
    assert json.loads(text) == {
        "schema": "ltx-movie.seam-report.v1", "story_id": "sr1", "created": CREATED,
        "model": "test-vlm", "threshold": 6,
        "panels": [
            {"panel": 1, "end_frame": E1, "source": "chainseed",
             "frame": "clips/panel_02.chainseed.png", "score": 8, "verdict": "ok",
             "reason": "The courier stands at frame centre.", "missing": [], "attempts": 1},
            {"panel": 2, "end_frame": E2, "source": "chainseed",
             "frame": "clips/panel_03.chainseed.png", "score": 5, "verdict": "missed",
             "reason": "The courier faces left, not right.",
             "missing": ["facing right", "seen from the knees up"], "attempts": 1},
            {"panel": 3, "end_frame": E3, "source": "clip", "frame": "clips/panel_03.mp4",
             "score": 6, "verdict": "ok", "reason": "Close to the plan.",
             "missing": ["the sealed letter"], "attempts": 1}],
        "summary": {"panels": 3, "scored": 3, "ok": 2, "missed": 1, "no_clip": 0,
                    "unparseable": 0, "mean_score": 6.33}}
    with open(md_path, encoding="utf-8") as f:
        assert f.read() == EXPECTED_MD
    assert _reports(sdir) == ["seam_report.json", "seam_report.md"]


def test_ct20_stale_seeds_missing_clips_and_unreadable_clips(ws, monkeypatch, capsys):
    stale = _story(ws, _plan(frames=(E1, E2)), "stale", files=[
        ("clips/panel_01.mp4", MP4, 1000), ("clips/panel_02.chainseed.png", SEED2, 500),
        ("clips/panel_02.mp4", MP4, 1000)])
    assert [(k, s, os.path.basename(p)) for k, _e, s, p in
            seam.frame_sources(_plan(frames=(E1, E2)), os.path.join(stale, "clips"))] == [
        (1, "clip", "panel_01.mp4"), (2, "clip", "panel_02.mp4")]
    seeded = _story(ws, _plan(frames=(E1, E2)), "seeded", files=[
        ("clips/panel_02.chainseed.png", SEED2, 500), ("clips/panel_02.mp4", MP4, 1000)])
    assert [(k, s) for k, _e, s, _p in
            seam.frame_sources(_plan(frames=(E1, E2)), os.path.join(seeded, "clips"))] == [
        (1, "chainseed"), (2, "clip")]
    gap = _story(ws, _plan(frames=(E1, None, E3)), "gap", files=[("clips/panel_03.mp4", MP4, 1000)])
    _ffmpeg(monkeypatch)
    _vlm(monkeypatch, [_reply(7, "Good.")])
    rc, out, _err = _run(["gap"], capsys)
    doc = json.load(open(os.path.join(gap, "seam_report.json"), encoding="utf-8"))
    assert rc == 0
    assert [(p["panel"], p["source"], p["frame"], p["score"], p["verdict"], p["reason"],
             p["attempts"]) for p in doc["panels"]] == [
        (1, None, None, None, "no clip", "clips/panel_01.mp4 does not exist", 0),
        (3, "clip", "clips/panel_03.mp4", 7, "ok", "Good.", 1)]
    assert doc["summary"] == {"panels": 2, "scored": 1, "ok": 1, "missed": 0, "no_clip": 1,
                              "unparseable": 0, "mean_score": 7.0}
    assert out.startswith("panel 1: no clip: clips/panel_01.mp4 does not exist\n"
                          "panel 3: ok (7/10): Good.\n")
    broken = _story(ws, _plan(frames=(E1,)), "broken", files=[("clips/panel_01.mp4", MP4, 1000)])
    _ffmpeg(monkeypatch, fail="x")
    fake = _vlm(monkeypatch, [])
    rc, out, _err = _run(["broken"], capsys)
    doc = json.load(open(os.path.join(broken, "seam_report.json"), encoding="utf-8"))
    assert rc == 0 and fake.calls == []
    assert doc["panels"][0]["verdict"] == "no clip" and doc["panels"][0]["attempts"] == 0
    assert doc["panels"][0]["reason"] == "cannot read the last frame of clips/panel_01.mp4: x"
    assert doc["summary"]["mean_score"] is None
    assert out.endswith(": 0 of 1 panel(s) missed, mean score n/a\n")
    with open(os.path.join(broken, "seam_report.md"), encoding="utf-8") as f:
        md = f.read()
    assert "| 1 | - | no clip | cannot read the last frame of clips/panel_01.mp4: x | - |\n" in md
    assert "Mean score n/a over 0 scored panel(s); 0 missed, 1 without a clip, 0 unparseable." in md


def test_ct20_a_report_file_that_cannot_be_written(ws, monkeypatch, capsys):
    sdir = _story(ws, _plan(frames=(E1, E2)), files=[("clips/panel_02.chainseed.png", SEED2, 2000)])
    os.makedirs(os.path.join(sdir, "seam_report.json.tmp"))
    _vlm(monkeypatch, [_reply(9, "Fine.")])
    rc, out, err = _run(["sr1"], capsys)
    assert rc == 1 and out == ""
    assert err.startswith("Error: cannot write %s: " % os.path.join(sdir, "seam_report.json"))


# --- CT21: unparseable replies (CE13 step 8) ------------------------------------------------------

def _one_panel(ws, monkeypatch, replies, capsys):
    sdir = _story(ws, _plan(frames=(E1, E2)), files=[("clips/panel_02.chainseed.png", SEED2, 2000)])
    fake = _vlm(monkeypatch, replies)
    rc, _out, _err = _run(["sr1"], capsys)
    assert rc == 0
    with open(os.path.join(sdir, "seam_report.json"), encoding="utf-8") as f:
        panel = json.load(f)["panels"][0]
    shutil.rmtree(sdir)
    return panel, fake


def test_ct21_unparseable_replies_are_retried(ws, monkeypatch, capsys):
    panel, fake = _one_panel(ws, monkeypatch, ["garbage"] * 3, capsys)
    assert (panel["verdict"], panel["attempts"], panel["score"], panel["reason"],
            panel["missing"]) == ("unparseable", 3, None,
                                  "the model gave no valid reply in 3 attempts", [])
    assert len(fake.calls) == 3
    panel, _fake = _one_panel(ws, monkeypatch, ["garbage", _reply(7, "ok")], capsys)
    assert (panel["verdict"], panel["attempts"], panel["score"]) == ("ok", 2, 7)
    panel, _fake = _one_panel(ws, monkeypatch, [None, _reply(11, "x"), _reply(4, "Off.")], capsys)
    assert (panel["verdict"], panel["attempts"], panel["score"]) == ("missed", 3, 4)
    for content in (_reply(11, "x"), _reply(0, "x"), _reply(True, "x"), _reply(7.0, "x"),
                    _reply(7, " \n "), json.dumps({"score": 7, "reason": "x", "missing": "y"}),
                    json.dumps({"score": 7, "reason": "x", "missing": [1]}),
                    json.dumps({"score": 7, "missing": []}), "[1, 2]", "garbage"):
        assert seam.parse_reply(content) is None, content
    assert seam.parse_reply('<think>{"score": 1}</think>{"score": 7, "reason": "ok", '
                            '"missing": []}') == {"score": 7, "reason": "ok", "missing": []}
    assert seam.parse_reply('```json\n{"score": 3, "reason": " far \\n off ", '
                            '"missing": [" the quay ", ""]}\n```') == {
        "score": 3, "reason": "far off", "missing": ["the quay"]}


# --- CT22: the prompt and the request (CE13) -------------------------------------------------------

class FakeConnection(object):
    """http.client.HTTPConnection stand-in: records the request and answers status / body, or
    raises error from request()."""
    made = []
    status, body, error = 200, b"{}", None

    def __init__(self, host, port, timeout=None):
        self.record = {"host": host, "port": port, "timeout": timeout}
        FakeConnection.made.append(self.record)

    def request(self, method, path, body=None, headers=None):
        self.record.update(method=method, path=path, body=body, headers=headers)
        if FakeConnection.error is not None:
            raise FakeConnection.error

    def getresponse(self):
        record = self.record

        class Response(object):
            status = FakeConnection.status

            def read(self, n=None):
                record["read"] = n
                return FakeConnection.body
        return Response()

    def close(self):
        self.record["closed"] = True


def _connection(monkeypatch, status=200, body=b"{}", error=None):
    FakeConnection.made = []
    FakeConnection.status, FakeConnection.body, FakeConnection.error = status, body, error
    monkeypatch.setattr(http.client, "HTTPConnection", FakeConnection)
    return FakeConnection.made


def test_ct22_the_prompt(ws):
    plan = _plan(casts={2: ["c1", "c2"], 3: []})
    assert seam.seam_prompt(plan, 2) == (
        "This image is the last frame of panel 2 of a movie. The story plan says the panel ends "
        "on this frame:\n" + E2 + "\nCharacters in this panel: \"the courier\" is " + COURIER
        + "; \"the old monk\" is an old man in a robe.\nScore how well the image matches the "
        "planned end frame, from 1 (nothing matches) to 10 (everything matches). Judge only who "
        "or what is in frame, where each one is (left, centre or right; foreground or "
        "background), which way they face and how tight the shot is; ignore image quality, "
        "lighting, colour and style.\nReply with one JSON object only, with exactly these keys: "
        "score (an integer from 1 to 10), reason (one sentence of at most 25 words) and missing "
        "(a list of the short phrases of the planned end frame that the image does not show, or "
        "an empty list).")
    empty = seam.seam_prompt(plan, 3)
    assert "Characters in this panel" not in empty
    assert ("ends on this frame:\n" + E3 + "\n\nScore how well") in empty
    assert seam.seam_prompt(plan, 1).count("Characters in this panel: \"the courier\" is ") == 1


def test_ct22_the_requests(monkeypatch):
    made = _connection(monkeypatch, body=json.dumps(
        {"choices": [{"message": {"role": "assistant", "content": "a reply"}}]}).encode("utf-8"))
    assert seam.vlm_complete(8177, "test-vlm", "the prompt", b"PNGBYTES") == "a reply"
    record = made[0]
    assert (record["host"], record["port"], record["timeout"]) == ("127.0.0.1", 8177, 300)
    assert (record["method"], record["path"], record["read"], record["closed"]) == (
        "POST", "/v1/chat/completions", 1048576, True)
    body = json.loads(record["body"].decode("utf-8"))
    assert sorted(body) == ["max_tokens", "messages", "model", "temperature"]
    assert (body["model"], body["max_tokens"], body["temperature"]) == ("test-vlm", 400, 0)
    assert body["messages"][0]["role"] == "user"
    text, image = body["messages"][0]["content"]
    assert text == {"type": "text", "text": "the prompt"}
    assert image["type"] == "image_url"
    assert image["image_url"]["url"] == "data:image/png;base64,UE5HQllURVM="
    for reply in (b"not json", json.dumps({"choices": []}).encode("utf-8"),
                  json.dumps({"choices": [{"message": {"content": None}}]}).encode("utf-8")):
        _connection(monkeypatch, body=reply)
        assert seam.vlm_complete(8177, "m", "p", b"x") is None, reply
    _connection(monkeypatch, status=503)
    with pytest.raises(seam.TransportError) as error:
        seam.vlm_complete(8177, "m", "p", b"x")
    assert str(error.value) == "HTTP 503"
    _connection(monkeypatch, error=ConnectionRefusedError(61, "refused"))
    with pytest.raises(seam.TransportError) as error:
        seam.vlm_complete(8177, "m", "p", b"x")
    assert str(error.value) == "ConnectionRefusedError"
    made = _connection(monkeypatch, body=b'{"object": "list", "data": [{"id": "mlx-vlm"}]}')
    assert seam.vlm_models(9001) == ("mlx-vlm", None)
    assert (made[0]["method"], made[0]["path"], made[0]["port"], made[0]["timeout"]) == (
        "GET", "/v1/models", 9001, 10)
    for status, body, what in ((500, b"{}", "HTTP 500"), (200, b"<html>", "invalid JSON"),
                               (200, b'{"data": []}', "no model listed"),
                               (200, b'{"data": [{"id": 5}]}', "no model listed"),
                               (200, b"[1]", "no model listed")):
        _connection(monkeypatch, status=status, body=body)
        assert seam.vlm_models(8177) == (None, what), body
    _connection(monkeypatch, error=http.client.RemoteDisconnected("gone"))
    assert seam.vlm_models(8177) == (None, "RemoteDisconnected")


# --- CT30: the script itself (CE13) ---------------------------------------------------------------

def test_ct30_executable_shebang_and_stdlib_imports():
    assert os.access(SEAM, os.X_OK)
    with open(SEAM, encoding="utf-8") as f:
        source = f.read()
    assert source.startswith("#!/usr/bin/env python3\n")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert imported == {"argparse", "base64", "http.client", "importlib.machinery", "json", "os",
                        "re", "shutil", "subprocess", "sys", "tempfile", "time"}
    assert seam.VERDICTS == ("ok", "missed", "no clip", "unparseable")
    assert (seam.SCHEMA, seam.MISS_BELOW, seam.ATTEMPTS, seam.MAX_TOKENS, seam.TEMPERATURE,
            seam.CALL_TIMEOUT_S, seam.MODELS_TIMEOUT_S, seam.MAX_BODY) == (
        "ltx-movie.seam-report.v1", 6, 3, 400, 0, 300, 10, 1048576)


# --- Review Focus 1, 2 -----------------------------------------------------------------------------

def test_review_focus_1_pipes_line_breaks_and_accents_in_the_report(ws, monkeypatch, capsys):
    frame = "The café owner | the courier stand at frame centre — facing left, seen from the waist up."
    sdir = _story(ws, _plan(frames=(frame, E2)), files=[("clips/panel_02.chainseed.png", SEED2, 2000)])
    _vlm(monkeypatch, [_reply(4, "Left | right\nswapped — café", ["the | sign", "l’aube"])])
    rc, out, _err = _run(["sr1"], capsys)
    assert rc == 0
    with open(os.path.join(sdir, "seam_report.md"), encoding="utf-8") as f:
        md = f.read()
    assert ("| 1 | 4 | missed | Left \\| right swapped — café | the \\| sign; l’aube |\n") in md
    assert "- panel 1: " + frame + "\n" in md
    with open(os.path.join(sdir, "seam_report.json"), encoding="utf-8") as f:
        raw = f.read()
    assert "café" in raw and "l’aube" in raw and "\\u" not in raw
    assert json.loads(raw)["panels"][0]["end_frame"] == frame
    assert "panel 1: missed (4/10): Left | right swapped — café; missing: the | sign; l’aube\n" in out


def test_review_focus_2_an_empty_chainseed_never_stands_in_for_its_clip(ws, monkeypatch, capsys):
    sdir = _story(ws, _plan(frames=(E1, E2)), files=[
        ("clips/panel_01.mp4", MP4, 1000), ("clips/panel_02.chainseed.png", b"", 2000),
        ("clips/panel_02.mp4", MP4, 1000)])
    assert [(k, s) for k, _e, s, _p in
            seam.frame_sources(_plan(frames=(E1, E2)), os.path.join(sdir, "clips"))] == [
        (1, "clip"), (2, "clip")]
    clips = _ffmpeg(monkeypatch)
    fake = _vlm(monkeypatch, [_reply(9, "Fine."), _reply(9, "Fine.")])
    assert _run(["sr1"], capsys)[0] == 0
    assert clips == ["panel_01.mp4", "panel_02.mp4"]
    assert [c[3] for c in fake.calls] == [LAST_PNG, LAST_PNG]
````

**1.2.** Append the CT1 compile part. Edit `tests/test_chained_end_frames.py`: replace this text, which occurs exactly once:

```python
                    if " %s " % " ".join(se.line_words(t)) in line] == [], name
    assert seen >= 40
```

with:

```python
                    if " %s " % " ".join(se.line_words(t)) in line] == [], name
    assert seen >= 40


# --- CT1 (Task 5 part): the new and changed Python files compile under both Pythons ------------

def test_ct1e_the_changed_files_compile_under_both_pythons():
    script = ("import sys\n"
              "for path in sys.argv[1:]:\n"
              "    with open(path, encoding='utf-8') as f:\n"
              "        compile(f.read(), path, 'exec')\n"
              "print('compiled %d' % (len(sys.argv) - 1))\n")
    files = [os.path.join(WS, name) for name in
             ("story_engine.py", os.path.join("bin", "seam-report"), "movie_ui_lib.py",
              "movie_ui_server.py")]
    pythons = [sys.executable] + (["/usr/bin/python3"] if os.path.exists("/usr/bin/python3")
                                  else [])
    for python in pythons:
        proc = subprocess.run([python, "-B", "-c", script] + files, capture_output=True,
                              text=True)
        assert (proc.returncode, proc.stdout) == (0, "compiled 4\n"), (python, proc.stderr)
```

- [ ] **Step 2: Run the tests to verify they fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_seam_report.py \
  tests/test_chained_end_frames.py::test_ct1e_the_changed_files_compile_under_both_pythons 2>&1 | tail -1
```

Expected: `1 error` (collecting `tests/test_seam_report.py` fails, because `bin/seam-report` does not exist yet; pytest stops before it runs any test).

- [ ] **Step 3: Write the implementation.**

**3.1.** Create `bin/seam-report` with exactly this content (the Write tool; the file ends with one newline):

```python
#!/usr/bin/env python3
"""seam-report -- score each chained panel's last frame against its planned end frame
(docs/superpowers/specs/2026-10-30-chained-end-frames-design.md, Section 3, CE13).

    bin/seam-report STORY_ID [--port N]

Reads generated/stories/<STORY_ID>/plan.json and its clips/, asks the story server's VLM
(loopback HTTP to 127.0.0.1:<port>, /v1/models and /v1/chat/completions) to score the last frame
of every panel whose beat has an end frame, and writes seam_report.json and seam_report.md next
to plan.json. A panel's frame is clips/panel_<k+1>.chainseed.png (the exact last frame of clip k)
when it is not older than its clip, else the last frame of clips/panel_<k>.mp4. It never
re-renders, never starts a server and writes nothing but the two report files.

Exit 0: report written, nothing to check, or no clips to check. 1: a report file cannot be
written. 2: a usage error, an invalid story id, no story, an invalid plan, ffmpeg or ffprobe
missing, or the story server not answering. Standard library only; Python 3.9 and 3.13.
"""

import argparse
import base64
import http.client
import importlib.machinery
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

SCHEMA = "ltx-movie.seam-report.v1"
MISS_BELOW = 6          # a score below 6 is "missed" (notes, Section 3)
ATTEMPTS = 3            # VLM calls per panel before "unparseable"
MAX_TOKENS = 400
TEMPERATURE = 0
CALL_TIMEOUT_S = 300
MODELS_TIMEOUT_S = 10
MAX_BODY = 1048576
VERDICTS = ("ok", "missed", "no clip", "unparseable")

PLAN_SCHEMA = "ltx-movie.plan.v1"
STORY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
THINK_RE = re.compile(r"(?s)<think>.*?</think>")
FFMPEG_TIMEOUT_S = 120
UNPARSEABLE_REASON = "the model gave no valid reply in %d attempts" % ATTEMPTS
SEAM_PROMPT = (
    "This image is the last frame of panel @@K@@ of a movie. The story plan says the panel ends "
    "on this frame:\n@@END_FRAME@@\n@@CHARACTERS@@\n"
    "Score how well the image matches the planned end frame, from 1 (nothing matches) to 10 "
    "(everything matches). Judge only who or what is in frame, where each one is (left, centre "
    "or right; foreground or background), which way they face and how tight the shot is; ignore "
    "image quality, lighting, colour and style.\n"
    "Reply with one JSON object only, with exactly these keys: score (an integer from 1 to 10), "
    "reason (one sentence of at most 25 words) and missing (a list of the short phrases of the "
    "planned end frame that the image does not show, or an empty list).")
DOWN = ("the story server is not answering at 127.0.0.1:%d (%s); nothing was changed. Start it "
        "with bin/story-server mlx-vision and rerun bin/seam-report %s.")
STOPPED = ("the story server stopped answering at 127.0.0.1:%d (%s) while checking panel %d; "
           "nothing was written. Start it with bin/story-server mlx-vision and rerun "
           "bin/seam-report %s.")


class SeamError(Exception):
    """A clip whose last frame cannot be read; the message is the detail."""


class TransportError(Exception):
    """The story server stopped answering; the message is what went wrong."""


_ENGINE = []


def _engine():
    """story_engine.py of WS, loaded by path on first use (only for extract_json)."""
    if not _ENGINE:
        _ENGINE.append(importlib.machinery.SourceFileLoader(
            "story_engine_for_seam_report", os.path.join(WS, "story_engine.py")).load_module())
    return _ENGINE[0]


def _utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def build_parser():
    parser = argparse.ArgumentParser(
        prog="seam-report",
        description="Score each chained panel's last frame against its planned end frame.")
    parser.add_argument("story_id", metavar="STORY_ID")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("STORY_SERVER_PORT") or 8177),
                        help="the story server's port (default: $STORY_SERVER_PORT or 8177)")
    return parser


def _error(message):
    print("Error: %s" % message, file=sys.stderr)
    return 2


def _end_frame(beat):
    """beat's end_frame when it is a string with a non-space character, else ""."""
    value = beat.get("end_frame") if isinstance(beat, dict) else None
    return value if isinstance(value, str) and value.strip() else ""


def _nonempty(path):
    return os.path.isfile(path) and os.path.getsize(path) > 0


def _read_plan(path):
    """The plan.json at path when it is a dict with the plan schema, a string mode and a list of
    beats, else None."""
    try:
        with open(path, encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, ValueError):
        return None
    if (isinstance(plan, dict) and plan.get("schema") == PLAN_SCHEMA
            and isinstance(plan.get("mode"), str) and isinstance(plan.get("beats"), list)):
        return plan
    return None


def frame_sources(plan, clips_dir):
    """[(k, end frame, source, path)] for every beat k (1-based) with an end frame, in order.
    source is "chainseed" (path: clips/panel_<k+1>.chainseed.png, used when it is a non-empty
    file and the clip is missing or not newer), "clip" (path: clips/panel_<k>.mp4, a non-empty
    file) or None (path None). The last panel always comes from its clip."""
    beats = plan["beats"]
    out = []
    for k, beat in enumerate(beats, start=1):
        end_frame = _end_frame(beat)
        if not end_frame:
            continue
        clip = os.path.join(clips_dir, "panel_%02d.mp4" % k)
        seed = os.path.join(clips_dir, "panel_%02d.chainseed.png" % (k + 1))
        if (k < len(beats) and _nonempty(seed)
                and (not os.path.exists(clip) or os.path.getmtime(seed) >= os.path.getmtime(clip))):
            out.append((k, end_frame, "chainseed", seed))
        elif _nonempty(clip):
            out.append((k, end_frame, "clip", clip))
        else:
            out.append((k, end_frame, None, None))
    return out


def _run(argv):
    """The stdout of argv (capture_output, timeout FFMPEG_TIMEOUT_S); SeamError when it cannot
    run or exits non-zero."""
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=FFMPEG_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise SeamError("%s did not run (%s)" % (argv[0], e.__class__.__name__))
    if proc.returncode != 0:
        lines = [line.strip() for line in proc.stderr.decode("utf-8", "replace").splitlines()
                 if line.strip()]
        raise SeamError("%s exited %d: %s" % (argv[0], proc.returncode,
                                              lines[-1] if lines else "(no error output)"))
    return proc.stdout.decode("utf-8", "replace")


def last_frame_png(clip, out_png):
    """Write the last decoded frame of clip to out_png (bin/judge-clips' ffprobe and ffmpeg
    argv); raises SeamError(detail) when it cannot."""
    probe = _run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                  "-show_entries", "stream=nb_read_frames", "-of", "json", clip])
    try:
        n = int(json.loads(probe)["streams"][0]["nb_read_frames"])
    except (ValueError, KeyError, IndexError, TypeError):
        raise SeamError("ffprobe gave no frame count")
    if n < 1:
        raise SeamError("the clip has no frames")
    _run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", clip, "-vf",
          "select=eq(n\\,%d)" % (n - 1), "-fps_mode", "passthrough", "-frames:v", "1", out_png])
    if not _nonempty(out_png):
        raise SeamError("ffmpeg wrote no frame")


def _request(port, method, path, body, timeout):
    """(status, at most MAX_BODY bytes of the reply) of one loopback request; raises OSError or
    http.client.HTTPException."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        headers = {"Content-Type": "application/json"} if body is not None else {}
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read(MAX_BODY)
    finally:
        conn.close()


def vlm_models(port):
    """(model, None) from GET /v1/models: the string id of the first listed model; or (None,
    what): "HTTP <n>", "invalid JSON", "no model listed" or the exception class name."""
    try:
        status, raw = _request(port, "GET", "/v1/models", None, MODELS_TIMEOUT_S)
    except (OSError, http.client.HTTPException) as e:
        return None, e.__class__.__name__
    if status != 200:
        return None, "HTTP %d" % status
    try:
        doc = json.loads(raw.decode("utf-8"))
    except ValueError:
        return None, "invalid JSON"
    data = doc.get("data") if isinstance(doc, dict) else None
    if not (isinstance(data, list) and data and isinstance(data[0], dict)
            and isinstance(data[0].get("id"), str)):
        return None, "no model listed"
    return data[0]["id"], None


def vlm_complete(port, model, prompt, png):
    """The content string of one POST /v1/chat/completions with prompt and the PNG bytes png, or
    None when the 200 reply is not JSON or has no string content; raises TransportError(what) on
    a transport failure or a non-200 status."""
    body = json.dumps({
        "model": model, "max_tokens": MAX_TOKENS, "temperature": TEMPERATURE,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {
                "url": "data:image/png;base64," + base64.b64encode(png).decode("ascii")}}]}]})
    try:
        status, raw = _request(port, "POST", "/v1/chat/completions", body.encode("utf-8"),
                               CALL_TIMEOUT_S)
    except (OSError, http.client.HTTPException) as e:
        raise TransportError(e.__class__.__name__)
    if status != 200:
        raise TransportError("HTTP %d" % status)
    try:
        content = json.loads(raw.decode("utf-8"))["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    return content if isinstance(content, str) else None


def seam_prompt(plan, k):
    """The VLM prompt of panel k: SEAM_PROMPT with @@K@@, @@END_FRAME@@ and @@CHARACTERS@@
    replaced in that order; @@CHARACTERS@@ names each plan cast entry of the beat's cast, in cast
    order, with its descriptor, or is "" when there is none."""
    beat = plan["beats"][k - 1]
    ids = beat.get("cast") if isinstance(beat.get("cast"), list) else []
    people = ['"%s" is %s' % (c.get("phrase"), c.get("descriptor"))
              for c in plan.get("cast") or [] if isinstance(c, dict) and c.get("id") in ids]
    characters = "Characters in this panel: " + "; ".join(people) + "." if people else ""
    return (SEAM_PROMPT.replace("@@K@@", str(k)).replace("@@END_FRAME@@", _end_frame(beat))
            .replace("@@CHARACTERS@@", characters))


def parse_reply(content):
    """{"score", "reason", "missing"} of a VLM reply, or None: <think> blocks removed, then
    story_engine.extract_json; score an int (not a bool) from 1 to 10, reason a string that is
    not empty once its whitespace is collapsed, missing a list of strings (kept stripped and
    non-empty)."""
    raw = _engine().extract_json(THINK_RE.sub("", content))
    if raw is None:
        return None
    score, reason, missing = raw.get("score"), raw.get("reason"), raw.get("missing")
    if not (isinstance(score, int) and not isinstance(score, bool) and 1 <= score <= 10):
        return None
    reason = " ".join(reason.split()) if isinstance(reason, str) else ""
    if not reason or not (isinstance(missing, list) and all(isinstance(m, str) for m in missing)):
        return None
    return {"score": score, "reason": reason,
            "missing": [m.strip() for m in missing if m.strip()]}


def _check_panel(port, model, plan, k, end_frame, source, path, tmp):
    """The report entry of panel k; raises TransportError from vlm_complete."""
    panel = {"panel": k, "end_frame": end_frame, "source": source,
             "frame": None if path is None else "clips/" + os.path.basename(path),
             "score": None, "verdict": "no clip", "reason": "", "missing": [], "attempts": 0}
    if source is None:
        panel["reason"] = "clips/panel_%02d.mp4 does not exist" % k
        return panel
    if source == "clip":
        out_png = os.path.join(tmp, "panel_%02d.png" % k)
        try:
            last_frame_png(path, out_png)
        except SeamError as e:
            panel["reason"] = "cannot read the last frame of clips/panel_%02d.mp4: %s" % (k, e)
            return panel
        path = out_png
    with open(path, "rb") as f:
        png = f.read()
    prompt = seam_prompt(plan, k)
    for attempt in range(1, ATTEMPTS + 1):
        content = vlm_complete(port, model, prompt, png)
        reply = parse_reply(content) if content is not None else None
        if reply is not None:
            panel.update(score=reply["score"], reason=reply["reason"], missing=reply["missing"],
                         attempts=attempt,
                         verdict="ok" if reply["score"] >= MISS_BELOW else "missed")
            return panel
    panel.update(verdict="unparseable", reason=UNPARSEABLE_REASON, attempts=ATTEMPTS)
    return panel


def _summary(panels):
    scored = [p["score"] for p in panels if p["score"] is not None]
    return {"panels": len(panels), "scored": len(scored),
            "ok": len([p for p in panels if p["verdict"] == "ok"]),
            "missed": len([p for p in panels if p["verdict"] == "missed"]),
            "no_clip": len([p for p in panels if p["verdict"] == "no clip"]),
            "unparseable": len([p for p in panels if p["verdict"] == "unparseable"]),
            "mean_score": round(sum(scored) / float(len(scored)), 2) if scored else None}


def _mean(summary):
    return "n/a" if summary["mean_score"] is None else str(summary["mean_score"])


def _cell(text):
    """A table cell: every | escaped as \\| and its whitespace collapsed."""
    return " ".join(str(text).replace("|", "\\|").split())


def render_md(doc):
    """The seam_report.md text of a seam_report.json document."""
    summary = doc["summary"]
    lines = ["# Seam report: %s" % doc["story_id"], "",
             "Created %s with %s. A score below %d is missed." % (doc["created"], doc["model"],
                                                                 doc["threshold"]), "",
             "| Panel | Score | Verdict | Reason | Missing |", "|---|---|---|---|---|"]
    for p in doc["panels"]:
        lines.append("| %d | %s | %s | %s | %s |" % (
            p["panel"], "-" if p["score"] is None else p["score"], _cell(p["verdict"]),
            _cell(p["reason"]), _cell("; ".join(p["missing"])) if p["missing"] else "-"))
    lines += ["", "Mean score %s over %d scored panel(s); %d missed, %d without a clip, %d "
              "unparseable." % (_mean(summary), summary["scored"], summary["missed"],
                                summary["no_clip"], summary["unparseable"]),
              "", "## Planned end frames", ""]
    lines += ["- panel %d: %s" % (p["panel"], p["end_frame"]) for p in doc["panels"]]
    return "\n".join(lines) + "\n"


def _panel_line(p):
    if p["verdict"] in ("ok", "missed"):
        line = "panel %d: %s (%d/10): %s" % (p["panel"], p["verdict"], p["score"], p["reason"])
        if p["verdict"] == "missed" and p["missing"]:
            line += "; missing: " + "; ".join(p["missing"])
        return line
    return "panel %d: %s: %s" % (p["panel"], p["verdict"], p["reason"])


def _write(path, text):
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(temporary, path)


def main(argv=None):
    args = build_parser().parse_args(argv)
    story_id, port = args.story_id, args.port
    if not STORY_ID_RE.match(story_id) or ".." in story_id:
        return _error("invalid story id: %s" % story_id)
    stories = os.path.join(WS, "generated", "stories")
    story_dir = os.path.join(stories, story_id)
    clips_dir = os.path.join(story_dir, "clips")
    if not os.path.isdir(story_dir):
        return _error("no story %s in %s" % (story_id, stories))
    plan_path = os.path.join(story_dir, "plan.json")
    plan = _read_plan(plan_path)
    if plan is None:
        return _error("%s is not a plan.json written by bin/ltx-movie's default story engine"
                      % plan_path)
    if plan["mode"] != "chained":
        print("seam-report: nothing to check: %s is a %s story; seams are checked only in "
              "chained stories" % (story_id, plan["mode"]))
        return 0
    sources = frame_sources(plan, clips_dir)
    if not sources:
        print("seam-report: nothing to check: this plan has no end frames; no seam report")
        return 0
    if not [s for s in sources if s[2] is not None]:
        print("seam-report: no clips to check in %s" % clips_dir)
        return 0
    if ([s for s in sources if s[2] == "clip"]
            and not (shutil.which("ffmpeg") and shutil.which("ffprobe"))):
        return _error("ffmpeg and ffprobe must be on PATH to read the clips in %s" % clips_dir)
    model, what = vlm_models(port)
    if model is None:
        return _error(DOWN % (port, what, story_id))
    panels = []
    tmp = tempfile.mkdtemp(prefix="seam-report-")
    try:
        for k, end_frame, source, path in sources:
            try:
                panels.append(_check_panel(port, model, plan, k, end_frame, source, path, tmp))
            except TransportError as e:
                return _error(STOPPED % (port, e, k, story_id))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    doc = {"schema": SCHEMA, "story_id": story_id, "created": _utc(), "model": model,
           "threshold": MISS_BELOW, "panels": panels, "summary": _summary(panels)}
    json_path = os.path.join(story_dir, "seam_report.json")
    md_path = os.path.join(story_dir, "seam_report.md")
    for path, text in ((json_path, json.dumps(doc, indent=2, ensure_ascii=False) + "\n"),
                       (md_path, render_md(doc))):
        try:
            _write(path, text)
        except OSError as e:
            print("Error: cannot write %s: %s" % (path, e), file=sys.stderr)
            return 1
    for p in panels:
        print(_panel_line(p))
    summary = doc["summary"]
    print("seam-report: wrote %s and %s: %d of %d panel(s) missed, mean score %s"
          % (json_path, md_path, summary["missed"], summary["panels"], _mean(summary)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**3.2.** Make `bin/seam-report` executable (it is a new, untracked file, so this is not an edit):

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
chmod 0755 bin/seam-report
ls -l bin/seam-report | cut -c1-10    # expected: -rwxr-xr-x
```

- [ ] **Step 4: Run the tests, the compile check and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_seam_report.py \
  tests/test_chained_end_frames.py::test_ct1e_the_changed_files_compile_under_both_pythons 2>&1 | tail -1
```

Expected: `15 passed` (14 in `tests/test_seam_report.py` and the CT1 compile test).

The compile check with `FILES` = `bin/seam-report tests/test_seam_report.py tests/test_chained_end_frames.py`. Expected: `compiled 3` twice.

The gate block with `N=5`. Expected: `GATE PASS`, `lost 33 (listed 33, unexpected 0); new tests 55, not passing 0`, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
git add bin/seam-report tests/test_seam_report.py tests/test_chained_end_frames.py
git diff --cached --name-only    # expected: only those 3 paths
git ls-files -s bin/seam-report | cut -c1-6    # expected: 100755
git commit -m "feat(bin): bin/seam-report scores each chained panel's last frame against its planned end frame (chained end frames CE13; CT17-CT22, CT30)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 6: The movie UI: the seams job, Check seams and the Stories tab report (CE14, CE15; CT23-CT28, Review Focus 4, 5)

This task implements:
- CE14 in `movie_ui_lib.py`: `job_vlm`'s first tuple gains `"seams"` (so a seams job is `required`), and `seams_argv` and `plan_has_end_frames` follow `effective_vlm`.
- CE14 in `movie_ui_server.py`:
  - the route `POST /api/stories/<id>/seams` right after the `story.md` PUT route (54 + 1 = 55 routes) and its registration next to `h_story_save`;
  - `_create_seams_job` before `create_compose_job`, which gains `seams=False` and queues the seams job right behind a chained movie under the same `STORE_LOCK` hold;
  - `_h_job_create` passing `check_seams` (only the JSON value `true` counts);
  - `_h_story_seams` after `_h_story_save` (404, 409 without end frames, 409 while one is queued or running, else 201);
  - `_h_story`'s `end_frames` and `seams` keys, appended last.
- CE15: the three `index.html` snippets, `app.js`'s `updateComposeButtons` line, the Run all handler, `showSeams` before `openStory`, its call at the end of `openStory` and the Check seams handler in `setupStories`, and the `.seam-missed` rule at the end of `app.css`.
  - The JS blocks are indented to where they sit in `app.js` (Plan ruling R6).

`DEFAULT_FIELDS`, `build_argv`, the batch submitter's call of `create_compose_job` and the `TABS` line are unchanged.

Tests: CT23-CT28 and Review Focus 4 and 5 in the new `tests/test_movie_ui_seams.py`.
- Every server is `mt.Running` on 127.0.0.1 under `mt.set_home`, in a stub workspace.
- `conftest.py` keeps the VLM lifecycle off and the VLM port at 9. CT23-CT25 unset the port to check the `8177` default.
- CT28 dispatches a failing stub movie and then a copy of the real `bin/seam-report`, which stops at "no clips to check" before any server contact.

**Files:**
- Create: `tests/test_movie_ui_seams.py`.
- Modify:
  - `movie_ui_lib.py`: `job_vlm` `:424-425`, `effective_vlm` `:439-445`;
  - `movie_ui_server.py`: `ROUTES` `:118`, `create_compose_job`/`_h_job_create` `:764-784`, `_h_story` `:1773`, `_h_story_save`'s end `:1809-1810`, `MovieUIHandler.h_story_save` `:1894`;
  - `static/movie-ui/index.html` `:136`, `:157`, `:162`;
  - `static/movie-ui/app.js` `:474-475`, `:581`, `:706`, `:741-742`, `:792-795`;
  - `static/movie-ui/app.css` `:98`.

**Interfaces:**
- Consumes: Task 5's `bin/seam-report` (its argv `STORY_ID --port N`); existing `lib.new_job_id`, `lib.create_job`, `lib.vlm_port`, `lib.job_state`, `lib.ACTIVE_STATES`, `lib.list_job_ids`, `lib.read_queue`, `_story_dir`, `_json_in`, `job_summary`, `ApiError`, `STORE_LOCK`, `COMPOSE_KINDS`; `app.js`'s `$`, `el`, `clear`, `show`, `enc`, `api`, `submit`, `composeFields`, `pollJobs`, `S`.
- Produces:
  - `lib.seams_argv(ws_real, story_id, py=sys.executable) -> [str]` and `lib.plan_has_end_frames(plan) -> bool`;
  - `srv._create_seams_job(state, real, story_id) -> job id` (the caller holds `STORE_LOCK`), `srv.create_compose_job(server, fields, seams=False)` and `srv._h_story_seams`;
  - the job kind `"seams"`, and the `GET /api/stories/<id>` keys `end_frames` and `seams`.

- [ ] **Step 1: Write the failing tests.**

Create `tests/test_movie_ui_seams.py` with exactly this content (the Write tool; the file ends with one newline):

```python
"""Tests for the movie-UI seams check (docs/superpowers/specs/2026-10-30-chained-end-frames-
design.md, Sections 4 and 6: CT23-CT28, with the plan's Review Focus pins 4 and 5): the seams job
kind, POST /api/stories/<id>/seams, Compose's check_seams option, the Stories tab's report and
the static page.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_seams.py
Stdlib plus pytest. No test renders, reads the real HOME, or contacts a model server, a daemon,
ffmpeg or the Anthropic API: the only server is the in-test movie-UI server on 127.0.0.1 under a
temporary HOME (movie_ui_testutil), every workspace is the stub workspace, the VLM lifecycle is
off (MOVIE_UI_VLM_LIFECYCLE=0, conftest.py), and the one seams job that runs (CT28) stops at "no
clips to check" before it would contact any server.
"""

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

import movie_ui_testutil as mt
import movie_ui_lib as lib
import movie_ui_server as srv

WS = mt.WS
END_FRAME = "The courier stands at frame centre on the wet quay, facing the camera, seen from the waist up."
REPORT = {"schema": "ltx-movie.seam-report.v1", "story_id": "ronin-rescue",
          "created": "2026-10-31T12:00:00Z", "model": "test-vlm", "threshold": 6,
          "panels": [{"panel": 1, "end_frame": END_FRAME, "source": "chainseed",
                      "frame": "clips/panel_02.chainseed.png", "score": 4, "verdict": "missed",
                      "reason": "The courier faces left.", "missing": ["facing the camera"],
                      "attempts": 1}],
          "summary": {"panels": 1, "scored": 1, "ok": 0, "missed": 1, "no_clip": 0,
                      "unparseable": 0, "mean_score": 4.0}}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "0")
    state = mt.set_home(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    running = mt.Running(state)
    yield {"state": state, "ws": ws, "tmp": str(tmp_path), "srv": running}
    running.close()
    mt.kill_everything(state)


def _plan(mode="chained", end_frames=True):
    beats = [{"index": k, "arc": "rising", "action": "the courier rides on", "cast": ["c1"]}
             for k in (1, 2)]
    if end_frames:
        beats[1]["end_frame"] = END_FRAME
    return {"schema": "ltx-movie.plan.v1", "mode": mode, "beats": beats,
            "cast": [{"id": "c1", "phrase": "the courier", "descriptor": "a young man"}]}


def _story(ws, story_id="ronin-rescue", plan=None, report=None):
    """generated/stories/<story_id>/ with plan.json (a dict, raw text, or none) and
    seam_report.json (a dict, raw text, or none); returns its directory."""
    sdir = os.path.join(ws, "generated", "stories", story_id)
    os.makedirs(sdir, exist_ok=True)
    for name, value in (("plan.json", plan), ("seam_report.json", report)):
        if value is not None:
            with open(os.path.join(sdir, name), "w", encoding="utf-8") as f:
                f.write(value if isinstance(value, str) else json.dumps(value))
    return sdir


def _passing_checks(monkeypatch):
    monkeypatch.setattr(lib, "run_checks",
                        lambda fields, ws_real, state, py=None: [lib.check("V1", "fields", "pass")])


def _jobs_of(state, kind):
    return [i for i in lib.list_job_ids(state) if lib.read_job(lib.job_dir(state, i))["kind"] == kind]


# --- CT23: the seams job kind, its argv and the plan test (CE14) ----------------------------------

def test_ct23_the_seams_job_policy_argv_and_plan_test(monkeypatch, tmp_path):
    monkeypatch.delenv("MOVIE_UI_VLM_PORT", raising=False)
    ws = str(tmp_path)
    assert lib.job_vlm("seams", {}, ws, "s1") == "required"
    assert lib.seams_argv(ws, "s1") == [sys.executable, ws + "/bin/seam-report", "s1", "--port",
                                        "8177"]
    assert lib.seams_argv(ws, "s1", py="/usr/bin/python3")[0] == "/usr/bin/python3"
    monkeypatch.setenv("MOVIE_UI_VLM_PORT", "9001")
    assert lib.seams_argv(ws, "s1")[-2:] == ["--port", "9001"]
    assert lib.plan_has_end_frames(_plan()) is True
    for plan in (None, {}, [], _plan(mode="shots"), _plan(end_frames=False),
                 {"mode": "chained", "beats": [{"end_frame": "   "}, {"end_frame": ""}]},
                 {"mode": "chained", "beats": [{"end_frame": 5}, "x", None]},
                 {"mode": "chained", "beats": "x"}, {"mode": "chained", "beats": []}):
        assert lib.plan_has_end_frames(plan) is False, plan


# --- CT24: POST /api/stories/<id>/seams (CE14) ----------------------------------------------------

def test_ct24_the_check_seams_route(env, monkeypatch):
    monkeypatch.delenv("MOVIE_UI_VLM_PORT", raising=False)
    s, ws, state = env["srv"], env["ws"], env["state"]
    _story(ws, plan=_plan())
    path = "/api/stories/ronin-rescue/seams"
    status, _h, created = mt.api(s, "POST", path, body={"ws": ws})
    assert status == 201, created
    job = created["job"]
    assert (job["kind"], job["state"], job["story_id"], job["workspace"]) == (
        "seams", "queued", "ronin-rescue", ws)
    assert job["command"].endswith("seam-report ronin-rescue --port 8177")
    record = lib.read_job(lib.job_dir(state, job["id"]))
    assert record["vlm"] == "required"
    assert record["argv"] == lib.seams_argv(ws, "ronin-rescue")
    assert record["fields"] == {"ws": ws, "story_id": "ronin-rescue"}
    assert lib.read_queue(state)[-1] == job["id"]
    assert mt.api(s, "POST", path, body={"ws": ws})[::2] == (
        409, {"error": "a seams check of ronin-rescue is already queued as job %s" % job["id"]})
    lib.write_queue(state, [i for i in lib.read_queue(state) if i != job["id"]])
    lib.write_status(lib.job_dir(state, job["id"]), {"state": "done", "exit_code": 0})
    assert mt.api(s, "POST", path, body={"ws": ws})[0] == 201
    stories = os.path.join(ws, "generated", "stories")
    assert mt.api(s, "POST", "/api/stories/nope/seams", body={"ws": ws})[::2] == (
        404, {"error": "no story nope in %s" % stories})
    _story(ws, "old-story", plan=_plan(end_frames=False))
    assert mt.api(s, "POST", "/api/stories/old-story/seams", body={"ws": ws})[::2] == (
        409, {"error": "story old-story has no end frames to check"})
    _story(ws, "shots-story", plan=_plan(mode="shots"))
    assert mt.api(s, "POST", "/api/stories/shots-story/seams", body={"ws": ws})[0] == 409
    _story(ws, "no-plan")
    assert mt.api(s, "POST", "/api/stories/no-plan/seams", body={"ws": ws})[0] == 409
    for token in (None, "wrong-token"):
        assert mt.api(s, "POST", path, body={"ws": ws}, token=token)[::2] == (
            401, {"error": "missing or invalid token"})
    assert ("POST", r"/api/stories/" + srv._STORY + r"/seams", "h_story_seams",
            "/api/stories/ronin-rescue/seams") in srv.ROUTES
    assert len(_jobs_of(state, "seams")) == 2


# --- CT25: Compose's check_seams option (CE14, D12) ------------------------------------------------

def test_ct25_run_all_queues_the_seams_job_right_behind_the_movie(env, monkeypatch):
    monkeypatch.delenv("MOVIE_UI_VLM_PORT", raising=False)
    s, ws, state = env["srv"], env["ws"], env["state"]
    _passing_checks(monkeypatch)
    movie = mt.fields(ws, action="movie", mode="chained")
    status, _h, created = mt.api(s, "POST", "/api/jobs", body=dict(movie, check_seams=True))
    assert status == 201, created
    assert created["job"]["kind"] == "movie"
    seams = _jobs_of(state, "seams")
    assert len(seams) == 1
    assert lib.read_queue(state)[-2:] == [created["job"]["id"], seams[0]]
    record = lib.read_job(lib.job_dir(state, seams[0]))
    assert record["argv"] == [sys.executable, ws + "/bin/seam-report", "ronin-rescue", "--port",
                              "8177"]
    assert (record["story_id"], record["workspace"], record["vlm"]) == ("ronin-rescue", ws,
                                                                        "required")
    assert "check_seams" not in lib.read_job(lib.job_dir(state, created["job"]["id"]))["fields"]
    for body in (movie, dict(movie, check_seams=False), dict(movie, check_seams="true"),
                 dict(movie, check_seams=1),
                 dict(mt.fields(ws, action="movie", mode="shots"), check_seams=True),
                 dict(mt.fields(ws, action="story", mode="chained"), check_seams=True)):
        assert mt.api(s, "POST", "/api/jobs", body=body)[0] == 201, body
    assert len(_jobs_of(state, "seams")) == 1


# --- CT26: the Stories tab's data (CE14) ----------------------------------------------------------

def test_ct26_get_story_has_end_frames_and_the_report(env):
    s, ws = env["srv"], env["ws"]
    _story(ws, plan=_plan(), report=REPORT)
    data = mt.api(s, "GET", "/api/stories/ronin-rescue?ws=" + ws)[2]
    assert (data["end_frames"], data["seams"], data["plan_mode"]) == (True, REPORT, "chained")
    _story(ws, "old-story", plan=_plan(end_frames=False))
    data = mt.api(s, "GET", "/api/stories/old-story?ws=" + ws)[2]
    assert (data["end_frames"], data["seams"]) == (False, None)
    _story(ws, "bare")
    data = mt.api(s, "GET", "/api/stories/bare?ws=" + ws)[2]
    assert (data["end_frames"], data["seams"], data["plan_mode"]) == (False, None, None)


# --- CT27: the static page (CE15) -------------------------------------------------------------------

HTML_SNIPPETS = (
    '    <button id="c-run-all" type="button">Run all</button> <span id="c-run-all-reason" '
    'class="muted"></span>\n    <label id="c-check-seams-box"><input id="c-check-seams" '
    'type="checkbox" checked> Check seams after render</label>\n',
    '      <button id="s-regenerate" type="button">Regenerate story</button>\n'
    '      <button id="s-seams" type="button" hidden>Check seams</button>\n',
    '    <div id="s-checks"></div>\n'
    '    <div id="s-seams-box" hidden>\n'
    '      <h3>Seams</h3>\n'
    '      <p id="s-seams-summary" class="muted"></p>\n'
    '      <table id="s-seams-table" class="list"><thead><tr><th>Panel</th><th>Score</th>'
    '<th>Verdict</th><th>Reason</th></tr></thead><tbody></tbody></table>\n'
    '    </div>\n',
)
JS_SNIPPETS = (
    '"/seams"',
    'check_seams: $("#c-mode").value === "chained" && $("#c-check-seams").checked',
    '"seam-missed"', '"This plan has no end frames; no seam report."',
    '"No seam report yet: press Check seams."', "showSeams(res.data);",
    '"seams check queued as job "', 'show($("#c-check-seams-box"), mode === "chained");',
    'const TABS = ["compose", "stories", "batches", "characters", "locations", "actions", "loras", '
    '"jobs", "traces"];',
)


def test_ct27_the_static_page():
    static = os.path.join(WS, "static", "movie-ui")
    texts = {}
    for name in ("index.html", "app.js", "app.css"):
        with open(os.path.join(static, name), encoding="utf-8") as f:
            texts[name] = f.read()
    for snippet in HTML_SNIPPETS:
        assert texts["index.html"].count(snippet) == 1, snippet[:60]
    for snippet in JS_SNIPPETS:
        assert snippet in texts["app.js"], snippet
    assert texts["app.js"].count("function showSeams(data)") == 1
    assert texts["app.js"].index("function showSeams(data)") < texts["app.js"].index(
        "async function openStory(storyId)")
    assert ".seam-missed td { background: var(--warn-bg); }\n" in texts["app.css"]
    for name, text in texts.items():
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\balert\(", r"\bconfirm\(",
                        r"\bprompt\(", r"\beval\(", r"new Function"):
            assert not re.search(pattern, text), (name, pattern)
    assert re.findall(r"<script[^>]*>", texts["index.html"]) == ['<script src="/static/app.js" defer>']
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")],
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr


# --- CT28: a failed movie, then its seams job (CE14, D11) ----------------------------------------

def _wait_finished(state, job_id):
    return mt.wait_until(lambda: mt.status_of(state, job_id).get("state")
                         in ("done", "failed", "cancelled"), 30)


def test_ct28_the_seams_job_of_a_failed_movie_ends_done(env):
    ws, state = env["ws"], env["state"]
    shutil.copy(os.path.join(WS, "bin", "seam-report"), os.path.join(ws, "bin", "seam-report"))
    sdir = _story(ws, plan=_plan())
    mt.stub_config(ws, {"ltx-movie run": {"exit": 1, "stderr": "render failed\n"}})
    movie = mt.make_job(state, [os.path.join(ws, "bin", "ltx-movie"), "a narrative", "--story-id",
                                "ronin-rescue"], ws, story_id="ronin-rescue")
    with srv.STORE_LOCK:
        seams = srv._create_seams_job(state, ws, "ronin-rescue")
    assert lib.read_queue(state) == [movie, seams]
    mt.dispatch(state, movie)
    _wait_finished(state, movie)
    assert mt.status_of(state, movie)["state"] == "failed"
    assert not os.path.exists(os.path.join(sdir, "clips"))
    mt.dispatch(state, seams)
    _wait_finished(state, seams)
    assert (mt.status_of(state, seams)["state"], mt.status_of(state, seams)["exit_code"]) == (
        "done", 0)
    lines = mt.read_log(state, seams).splitlines()
    child = [line for line in lines if not line.startswith("[movie-ui] ")]
    assert child[-1] == "seam-report: no clips to check in %s" % os.path.join(sdir, "clips")
    assert lines[-1] == "[movie-ui] exit 0 (done)"
    assert sorted(os.listdir(sdir)) == ["plan.json"]


# --- Review Focus 4, 5 -----------------------------------------------------------------------------

def test_review_focus_4_a_malformed_seam_report_reads_as_none(env):
    s, ws = env["srv"], env["ws"]
    _story(ws, plan=_plan(), report='{"schema": "ltx-movie.seam-report.v1", "panels": [')
    data = mt.api(s, "GET", "/api/stories/ronin-rescue?ws=" + ws)[2]
    assert (data["end_frames"], data["seams"]) == (True, None)
    assert mt.api(s, "POST", "/api/stories/ronin-rescue/seams", body={"ws": ws})[0] == 201


def test_review_focus_5_a_refused_run_all_queues_no_seams_job(env, monkeypatch):
    s, ws, state = env["srv"], env["ws"], env["state"]
    monkeypatch.setattr(lib, "run_checks", lambda fields, ws_real, state, py=None: [
        lib.check("V1", "fields", "fail", "panels must be an integer from 1 to 200")])
    status, _h, refused = mt.api(s, "POST", "/api/jobs", body=dict(
        mt.fields(ws, action="movie", mode="chained"), check_seams=True))
    assert (status, refused["error"]) == (409, "validation failed")
    assert lib.read_queue(state) == [] and lib.list_job_ids(state) == []
```

- [ ] **Step 2: Run the tests to verify they fail.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_movie_ui_seams.py 2>&1 | tail -1
```

Expected: `7 failed, 1 passed`. The one that passes is `test_review_focus_5_a_refused_run_all_queues_no_seams_job`: a refused Run all queues nothing today, and must still queue nothing.

- [ ] **Step 3: Write the implementation.**

**3.1.** The `seams` job needs the VLM (CE14). Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    if kind in ("story", "character-create", "character-regenerate", "location-create",
                "location-regenerate"):
```

with:

```python
    if kind in ("story", "character-create", "character-regenerate", "location-create",
                "location-regenerate", "seams"):
```

**3.2.** `seams_argv` and `plan_has_end_frames` (CE14). Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
def effective_vlm(job):
    """The policy at dispatch (VP2): a movie job is recomputed (a story job queued ahead of it
    can create story.md); any other job uses its recorded vlm, and no or an unknown key is "any"."""
    if job.get("kind") == "movie":
        return job_vlm("movie", job.get("fields"), job.get("workspace"), job.get("story_id"))
    vlm = job.get("vlm")
    return vlm if vlm in VLM_POLICIES else "any"
```

with:

```python
def effective_vlm(job):
    """The policy at dispatch (VP2): a movie job is recomputed (a story job queued ahead of it
    can create story.md); any other job uses its recorded vlm, and no or an unknown key is "any"."""
    if job.get("kind") == "movie":
        return job_vlm("movie", job.get("fields"), job.get("workspace"), job.get("story_id"))
    vlm = job.get("vlm")
    return vlm if vlm in VLM_POLICIES else "any"


# Chained end frames spec CE14: the seams job and the plans that have something to check.
def seams_argv(ws_real, story_id, py=sys.executable):
    """The bin/seam-report argv of a seams job, on the port the VLM preflight checks."""
    return [py, os.path.join(ws_real, "bin", "seam-report"), story_id, "--port", str(vlm_port())]


def plan_has_end_frames(plan):
    """True when plan (a parsed plan.json, or None) is chained and a beat has a non-empty string
    end_frame. Pure."""
    beats = plan.get("beats") if isinstance(plan, dict) else None
    return (isinstance(plan, dict) and plan.get("mode") == "chained" and isinstance(beats, list)
            and any(isinstance(b, dict) and isinstance(b.get("end_frame"), str)
                    and b["end_frame"].strip() for b in beats))
```

**3.3.** The route (CE14). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    ("PUT", r"/api/stories/" + _STORY + r"/story\.md", "h_story_save", "/api/stories/ronin-rescue/story.md"),
```

with:

```python
    ("PUT", r"/api/stories/" + _STORY + r"/story\.md", "h_story_save", "/api/stories/ronin-rescue/story.md"),
    ("POST", r"/api/stories/" + _STORY + r"/seams", "h_story_seams", "/api/stories/ronin-rescue/seams"),
```

**3.4.** The seams job behind a chained Run all (CE14). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
def create_compose_job(server, fields):
    """Create the queued job of a validated compose submission; returns its ID."""
    state, real = server.state, fields["ws"]
    with STORE_LOCK:
        job_id = lib.new_job_id(state)
        if fields["action"] == "smoke":
            lib.write_smoke_manifest(state, job_id)
            argv = lib.build_smoke_argv(fields, real, state, job_id)
            return lib.create_job(state, job_id, "smoke", real, None, None, argv, fields)["id"]
        argv = lib.build_argv(fields, real, state)
        return lib.create_job(state, job_id, COMPOSE_KINDS[fields["action"]], real, fields["story_id"], None,
                              argv, fields)["id"]


def _h_job_create(self, groups, query, body):
    fields = _fields_body(body)
    checks = lib.run_checks(fields, fields["ws"], self.server.state)
    if not lib.checks_pass(checks):
        raise ApiError(409, "validation failed", checks=checks)
    job_id = create_compose_job(self.server, fields)
    return 201, {"job": job_summary(self.server, job_id, lib.read_queue(self.server.state)), "checks": checks}
```

with:

```python
# Chained end frames spec CE14, D12: the seams job of a story; the caller holds STORE_LOCK.
def _create_seams_job(state, real, story_id):
    """Create and queue the seams job of story_id; returns its ID (CE14)."""
    job_id = lib.new_job_id(state)
    lib.create_job(state, job_id, "seams", real, story_id, None, lib.seams_argv(real, story_id),
                   {"ws": real, "story_id": story_id})
    return job_id


def create_compose_job(server, fields, seams=False):
    """Create the queued job of a validated compose submission; returns its ID. With seams, a
    chained movie's seams job is queued right behind it under the same STORE_LOCK hold (chained
    end frames spec CE14, D12)."""
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
            _create_seams_job(state, real, fields["story_id"])
        return job_id


def _h_job_create(self, groups, query, body):
    fields = _fields_body(body)
    checks = lib.run_checks(fields, fields["ws"], self.server.state)
    if not lib.checks_pass(checks):
        raise ApiError(409, "validation failed", checks=checks)
    job_id = create_compose_job(self.server, fields,
                                seams=isinstance(body, dict) and body.get("check_seams") is True)
    return 201, {"job": job_summary(self.server, job_id, lib.read_queue(self.server.state)), "checks": checks}
```

**3.5.** `GET /api/stories/<id>` gains `end_frames` and `seams` (CE14). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
                 "last_fields": job["fields"] if job is not None else None}
```

with:

```python
                 "last_fields": job["fields"] if job is not None else None,
                 "end_frames": lib.plan_has_end_frames(plan),
                 "seams": _json_in(sdir, os.path.join(sdir, "seam_report.json"))}
```

**3.6.** `POST /api/stories/<id>/seams` (CE14). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
        lib.write_bytes_atomic(path, data)
    return 200, {"sha256": hashlib.sha256(data).hexdigest(), "backup": backup}
```

with:

```python
        lib.write_bytes_atomic(path, data)
    return 200, {"sha256": hashlib.sha256(data).hexdigest(), "backup": backup}


def _h_story_seams(self, groups, query, body):
    """POST /api/stories/<id>/seams: queue a seams check (bin/seam-report) of a story whose plan
    has end frames (chained end frames spec CE14, D12); a second one is refused while one is
    queued or running."""
    real, story_id, sdir = _story_dir(self, groups, body.get("ws"))
    if not lib.plan_has_end_frames(_json_in(sdir, os.path.join(sdir, "plan.json"))):
        raise ApiError(409, "story %s has no end frames to check" % story_id)
    state = self.server.state
    with STORE_LOCK:
        queue = lib.read_queue(state)
        for job_id in lib.list_job_ids(state):
            job = self.server.job(job_id)
            if (job is not None and job["kind"] == "seams" and job["workspace"] == real
                    and job["story_id"] == story_id
                    and lib.job_state(state, job_id, queue) in ("queued",) + lib.ACTIVE_STATES):
                raise ApiError(409, "a seams check of %s is already queued as job %s"
                               % (story_id, job_id))
        job_id = _create_seams_job(state, real, story_id)
    return 201, {"job": job_summary(self.server, job_id, lib.read_queue(state))}
```

**3.7.** Its handler registration (CE14). Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
MovieUIHandler.h_story_save = _h_story_save
```

with:

```python
MovieUIHandler.h_story_save = _h_story_save
MovieUIHandler.h_story_seams = _h_story_seams
```

**3.8.** The Compose checkbox (CE15). Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
    <button id="c-run-all" type="button">Run all</button> <span id="c-run-all-reason" class="muted"></span>
```

with:

```html
    <button id="c-run-all" type="button">Run all</button> <span id="c-run-all-reason" class="muted"></span>
    <label id="c-check-seams-box"><input id="c-check-seams" type="checkbox" checked> Check seams after render</label>
```

**3.9.** The Check seams button (CE15). Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
      <button id="s-regenerate" type="button">Regenerate story</button>
```

with:

```html
      <button id="s-regenerate" type="button">Regenerate story</button>
      <button id="s-seams" type="button" hidden>Check seams</button>
```

**3.10.** The Seams box (CE15). Edit `static/movie-ui/index.html`: replace this text, which occurs exactly once:

```html
    <div id="s-checks"></div>
```

with:

```html
    <div id="s-checks"></div>
    <div id="s-seams-box" hidden>
      <h3>Seams</h3>
      <p id="s-seams-summary" class="muted"></p>
      <table id="s-seams-table" class="list"><thead><tr><th>Panel</th><th>Score</th><th>Verdict</th><th>Reason</th></tr></thead><tbody></tbody></table>
    </div>
```

**3.11.** The checkbox shows only for chained movies (CE15). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
    gate($("#c-smoke"), $("#c-smoke-reason"), ["render"]);
  }
```

with:

```javascript
    gate($("#c-smoke"), $("#c-smoke-reason"), ["render"]);
    show($("#c-check-seams-box"), mode === "chained");
  }
```

**3.12.** Run all sends `check_seams` (CE15). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
    $("#c-run-all").addEventListener("click", function () { S.composeAction = "movie"; submit(composeFields("movie")); });
```

with:

```javascript
    $("#c-run-all").addEventListener("click", function () {
      S.composeAction = "movie";
      submit(Object.assign(composeFields("movie"),
                           {check_seams: $("#c-mode").value === "chained" && $("#c-check-seams").checked}));
    });
```

**3.13.** `showSeams` (CE15). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
  async function openStory(storyId) {
```

with:

```javascript
  function showSeams(data) {
    const chained = data.plan_mode === "chained";
    show($("#s-seams"), Boolean(data.end_frames));
    show($("#s-seams-box"), chained);
    const body = clear($("#s-seams-table tbody"));
    const report = data.end_frames ? data.seams : null;
    show($("#s-seams-table"), Boolean(report));
    if (!chained) { return; }
    if (!data.end_frames) { $("#s-seams-summary").textContent = "This plan has no end frames; no seam report."; return; }
    if (!report) { $("#s-seams-summary").textContent = "No seam report yet: press Check seams."; return; }
    const s = report.summary || {};
    $("#s-seams-summary").textContent = "Mean score " + (s.mean_score === null || s.mean_score === undefined ? "n/a" : s.mean_score)
      + " over " + s.scored + " scored panel(s); " + s.missed + " missed (a score below " + report.threshold + ").";
    (report.panels || []).forEach(function (p) {
      body.appendChild(el("tr", {cls: p.verdict === "missed" ? "seam-missed" : ""}, [
        el("td", {text: String(p.panel)}), el("td", {text: p.score === null ? "-" : String(p.score)}),
        el("td", {text: p.verdict}), el("td", {text: p.reason})]));
    });
  }

  async function openStory(storyId) {
```

**3.14.** `openStory` shows the seams (CE15). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
    $("#s-action-status").textContent = res.data.last_fields ? "" : "no earlier job for this story: Render opens Compose with only its ID";
  }
```

with:

```javascript
    $("#s-action-status").textContent = res.data.last_fields ? "" : "no earlier job for this story: Render opens Compose with only its ID";
    showSeams(res.data);
  }
```

**3.15.** The Check seams handler (CE15). Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
    });
  }

  // --- batches (batch forks spec Section 5, BF36-BF39) ---------------------------------
```

with:

```javascript
    });
    $("#s-seams").addEventListener("click", async function () {
      const res = await api("POST", "/api/stories/" + enc(S.story.id) + "/seams", {ws: S.ws});
      $("#s-action-status").textContent = res.status === 201 ? "seams check queued as job " + res.data.job.id
        : ((res.data && res.data.error) || ("http " + res.status));
      if (res.status === 201) { pollJobs(); }
    });
  }

  // --- batches (batch forks spec Section 5, BF36-BF39) ---------------------------------
```

**3.16.** The missed-row style (CE15). Edit `static/movie-ui/app.css`: replace this text, which occurs exactly once:

```css
#b-grid video { max-width: 320px; }
```

with:

```css
#b-grid video { max-width: 320px; }
/* chained end frames spec CE15: a panel whose seam was missed */
.seam-missed td { background: var(--warn-bg); }
```

- [ ] **Step 4: Run the tests, the compile check, `node --check` and the gate.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_movie_ui_seams.py 2>&1 | tail -1
```

Expected: `8 passed`.

The compile check with `FILES` = `movie_ui_lib.py movie_ui_server.py tests/test_movie_ui_seams.py`. Expected: `compiled 3` twice. Then:

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
node --check static/movie-ui/app.js && echo "app.js parses"
```

Expected: `app.js parses`.

The gate block with `N=6`. Expected: `GATE PASS`, `lost 35 (listed 35, unexpected 0); new tests 67, not passing 0`, and `offline unchanged`.

- [ ] **Step 5: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
git add movie_ui_lib.py movie_ui_server.py static/movie-ui/index.html static/movie-ui/app.js static/movie-ui/app.css tests/test_movie_ui_seams.py
git diff --cached --name-only    # expected: only those 6 paths
git commit -m "feat(movie-ui): Check seams: the seams job, Compose's check_seams option and the Stories tab report (chained end frames CE14, CE15; CT23-CT28)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 7: Whole-branch review, the ONE test-only re-baseline (spec Section 7, CR1-CR7), CK1-CK7 and the hand-off

**Files:**
- Modify (test-only, Step 3), 16 files:
  - `tests/test_story_engine.py`, `tests/test_shot_format.py`, `tests/test_dialogue.py`, `tests/test_narrative_fidelity.py`, `tests/test_pinned_cast.py`, `tests/test_soft_panel_count.py`, `tests/test_speaker_attribution.py`;
  - `tests/test_movie_ui_http.py` (`test_mut18`), `tests/test_location_ui.py` (`test_lu1`), `tests/test_movie_ui_builder.py` (`test_mut26`);
  - `tests/fixtures/location/plan_prompt_chained.txt`, `plan_prompt_chained_cast.txt`, `plan_prompt_shots.txt` (for `test_ls1`, whose own file is unchanged);
  - `tests/fixtures/pinned_cast/uncast_chained_lines.txt`, `uncast_chained_seed.txt`, `uncast_shots_lines.txt` (for `test_pt2`).
- Not edited: anything under `tests/fixtures/writer_pacing/` (spec Section 7 rule).

**Interfaces:**
- Consumes: the commits of Tasks 1-6.
- Produces: the one test-only re-baseline commit (spec 10 step 3, commit 2), `$D/final-pytest.txt`, and the hand-off report.

- [ ] **Step 1: Design review (controller; spec 10 step 4).**
  - Ask an Opus `design-reviewer` to review `git diff d30c40f..HEAD -- qwen-agent-workspace` against the spec, this plan's rulings and the Review Focus.
  - Fix every finding in a new commit on the owning task's files, then rerun that task's Step 4.
  - If a fix changes a value that Step 3 re-baselines, the controller writes the changed Edit before Step 3 runs.
  - The re-baseline below comes after the review.

- [ ] **Step 2: Find the last pipeline commit (CR6).**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
git log -1 --format='%H %s' -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py
```

Expected: one line. It is a 40-character SHA, then the subject of Task 4's commit, or of a Step 1 fix commit if that commit touched `story_engine.py`. `bin/seam-report` is not a `PIPELINE_FILES` entry (Plan ruling R17). In Step 3, **SHA** means exactly those 40 characters, typed in place of the word `SHA` in edits 3.51 and 3.52.

- [ ] **Step 3: The re-baseline edits (spec Section 7; test-only).**

Every edit below updates an assertion to the new behaviour that its code names. None deletes a test or weakens an assertion beyond the new behaviour. The fixture edits make each prompt fixture equal the new `build_plan_prompt` output: the camera list, `CAMERA_SPEAKING_SENTENCE`, and for the chained ones the beat keys, `END_FRAME_RULE` and the plan reference (spec Section 7, `test_pt2` and `test_ls1`). Within a fixture, the hunks run from the end of the file to its start.

**`tests/test_story_engine.py`**

**3.1.** `test_rs4_constants`: the 14 keys (CR1). Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
        "slow push-in", "slow pull-back", "tracking", "handheld", "slow pan left",
        "slow pan right", "slow tilt up", "slow tilt down", "static"]
```

with:

```python
        "slow push-in", "slow pull-back", "tracking", "slow tracking left", "slow tracking right",
        "handheld", "slow pan left", "slow pan right", "slow tilt up", "slow tilt down",
        "slow crane up", "slow crane down", "slow orbit", "static"]
```

**3.2.** `test_rst8_plan_prompt_matrix`: braces outside the plan reference (CR3). Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
                    assert "{" not in prompt and "}" not in prompt, where
```

with:

```python
                    rest = prompt.replace(se.plan_reference(True), "").replace(
                        se.plan_reference(False), "")
                    assert "{" not in rest and "}" not in rest, where
```

**3.3.** `test_rst14_plan_checks`: the P8 key list (CR1). Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
        (beat(3, camera="zoom"), ["beat 3: P8 camera: 'zoom' is not one of: slow push-in, "
                                  "slow pull-back, tracking, handheld, slow pan left, slow pan "
                                  "right, slow tilt up, slow tilt down, static"]),
```

with:

```python
        (beat(3, camera="zoom"), ["beat 3: P8 camera: 'zoom' is not one of: slow push-in, "
                                  "slow pull-back, tracking, slow tracking left, slow tracking "
                                  "right, handheld, slow pan left, slow pan right, slow tilt up, "
                                  "slow tilt down, slow crane up, slow crane down, slow orbit, "
                                  "static"]),
```

**3.4.** `test_rst57_reserved_sentence_in_the_plan_prompt`: braces outside the plan reference (CR3). Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    assert "accessories." + sentence in prompt
    assert "{" not in prompt and "}" not in prompt
```

with:

```python
    assert "accessories." + sentence in prompt
    rest = prompt.replace(se.plan_reference(False), "")
    assert "{" not in rest and "}" not in rest
```

**3.5.** `test_rst26b_critic_retry_and_code_only_round`: the second plan call (CR5). Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    assert [(r["stage"], r["panel"]) for r in log] == [
        ("plan", None), ("panel", 1), ("panel", 2), ("panel", 3), ("critic", None),
        ("critic", None), ("panel", 2)]
    assert log[5]["argv"][-1].endswith(se.CRITIC_RETRY_SUFFIX)
    assert "- " + _t2(2) + "\n" in log[6]["argv"][-1]
```

with:

```python
    assert [(r["stage"], r["panel"]) for r in log] == [
        ("plan", None), ("plan", None), ("panel", 1), ("panel", 2), ("panel", 3),
        ("critic", None), ("critic", None), ("panel", 2)]
    assert log[6]["argv"][-1].endswith(se.CRITIC_RETRY_SUFFIX)
    assert "- " + _t2(2) + "\n" in log[7]["argv"][-1]
```

**3.6.** `test_rst33_stop_passed`: stdout and the preflight flags of the second plan call (CR5). Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
        "plan: call 1 of 2\npanel 1/3: call 1\npanel 2/3: call 1\npanel 3/3: call 1\n"
        "round 0: 0 hard, 4 advisory\nstop: passed; best round 0 (0 hard)\n")
    assert [r["stage"] for r in log].count("critic") == 0
    assert [r["env_preflight"] for r in log] == [None, "1", "1", "1"]
```

with:

```python
        "plan: call 1 of 2\nplan: call 2 of 2\nWarning: end frames dropped after 2 attempts; "
        "this story has no seam report\npanel 1/3: call 1\npanel 2/3: call 1\npanel 3/3: call 1\n"
        "round 0: 0 hard, 4 advisory\nstop: passed; best round 0 (0 hard)\n")
    assert [r["stage"] for r in log].count("critic") == 0
    assert [r["env_preflight"] for r in log] == [None, "1", "1", "1", "1"]
```

**3.7.** `test_rst39_outputs_and_layout`: `plan_reply_2.txt` (CR5). Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
        "plan.json", "plan_prompt.txt", "plan_reply_1.txt", "story.md", "story_checks.json"]
```

with:

```python
        "plan.json", "plan_prompt.txt", "plan_reply_1.txt", "plan_reply_2.txt", "story.md",
        "story_checks.json"]
```

**3.8.** `test_rst39_outputs_and_layout`: the `run.json` calls (CR5). Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    assert [c["stage"] for c in run_doc["calls"]] == ["plan", "panel", "panel", "panel", "critic"]
    assert run_doc["calls"][4]["route"] == "local" and run_doc["exit"] == 0
```

with:

```python
    assert [c["stage"] for c in run_doc["calls"]] == ["plan", "plan", "panel", "panel", "panel",
                                                      "critic"]
    assert run_doc["calls"][5]["route"] == "local" and run_doc["exit"] == 0
```

**3.9.** `test_rst47_robust_dry_run`: the plan reference's lines in the dry run (CR3). Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
        assert not [line for line in proc.stdout.splitlines() if "{" in line or "}" in line]
        phase1 = "\n".join(block)
```

with:

```python
        reference = set(se.plan_reference(True).splitlines()
                        + se.plan_reference(False).splitlines())
        assert not [line for line in proc.stdout.splitlines()
                    if ("{" in line or "}" in line) and line not in reference]
        phase1 = "\n".join(line for line in block if line not in reference)
```

**3.10.** `test_rst51_e2e_chained`: the stages (CR5). Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    assert [r["stage"] for r in log] == ["plan", "panel", "panel", "panel"]
    assert all("--max-rounds" in r["argv"] and r["argv"][r["argv"].index("--max-rounds") + 1] == "1"
```

with:

```python
    assert [r["stage"] for r in log] == ["plan", "plan", "panel", "panel", "panel"]
    assert all("--max-rounds" in r["argv"] and r["argv"][r["argv"].index("--max-rounds") + 1] == "1"
```

**3.11.** `test_rst55b_p13_forces_plan_call_2`: the stages (CR5). Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    assert rc == 0 and [r["stage"] for r in log][:2] == ["plan", "panel"]
```

with:

```python
    assert rc == 0 and [r["stage"] for r in log][:3] == ["plan", "plan", "panel"]
```

**3.12.** `test_pacing_camera_sentences_classify_as_before`: 14 sentences (CR1). Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    assert len(sentences) == 9
```

with:

```python
    assert len(sentences) == 14
```

**3.13.** `test_pacing_camera_sentences_classify_as_before`: the new keys' "old" sentences are their new ones (CR1). Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
           "handheld": sentences["handheld"]}
```

with:

```python
           "handheld": sentences["handheld"],
           "slow tracking left": sentences["slow tracking left"],
           "slow tracking right": sentences["slow tracking right"],
           "slow crane up": sentences["slow crane up"],
           "slow crane down": sentences["slow crane down"], "slow orbit": sentences["slow orbit"]}
```


**`tests/test_shot_format.py`**

**3.14.** `test_sft1a_planner_constants`: `CAMERA_SENTENCES` (CR1). Edit `tests/test_shot_format.py`: replace this text, which occurs exactly once:

```python
    ("tracking", "The camera tracks alongside the movement."),
    ("handheld", "The camera is handheld, with slight natural movement."),
    ("slow pan left", "The camera pans left."),
    ("slow pan right", "The camera pans right."),
    ("slow tilt up", "The camera tilts up."),
    ("slow tilt down", "The camera tilts down."),
    ("static", "The camera stays static."),
```

with:

```python
    ("tracking", "The camera tracks alongside the movement."),
    ("slow tracking left", "The camera tracks left alongside the movement."),
    ("slow tracking right", "The camera tracks right alongside the movement."),
    ("handheld", "The camera is handheld, with slight natural movement."),
    ("slow pan left", "The camera pans left."),
    ("slow pan right", "The camera pans right."),
    ("slow tilt up", "The camera tilts up."),
    ("slow tilt down", "The camera tilts down."),
    ("slow crane up", "The camera cranes up."),
    ("slow crane down", "The camera cranes down."),
    ("slow orbit", "The camera arcs around the subject in a partial orbit."),
    ("static", "The camera stays static."),
```

**3.15.** `test_sft1a_planner_constants`: `CAMERA_SPEAKING_SENTENCE` (CR1). Edit `tests/test_shot_format.py`: replace this text, which occurs exactly once:

```python
CAMERA_SPEAKING_SENTENCE = (" On a beat with a speaker, prefer slow push-in, slow pull-back, "
                            "tracking or handheld, and never use a pan or a tilt, which sweeps "
                            "the speaker's face out of the frame.")
```

with:

```python
CAMERA_SPEAKING_SENTENCE = (" On a beat with a speaker, prefer slow push-in, slow pull-back, "
                            "slow tracking left, slow tracking right or handheld, and never use a "
                            "pan, a tilt, a crane or an orbit, which sweep the speaker's face out "
                            "of the frame.")
```

**3.16.** `test_sft1a_planner_constants`: `SPEAKING_CAMERAS` (CR1). Edit `tests/test_shot_format.py`: replace this text, which occurs exactly once:

```python
SPEAKING_CAMERAS = ("slow push-in", "slow pull-back", "tracking", "handheld", "static")
```

with:

```python
SPEAKING_CAMERAS = ("slow push-in", "slow pull-back", "tracking", "slow tracking left",
                    "slow tracking right", "handheld", "static")
```

**3.17.** `test_sft1a_planner_constants`: `RECHECK_IDS_3970E96` becomes `RECHECK_IDS_CE` (CR4). Edit `tests/test_shot_format.py`: replace this text, which occurs exactly once:

```python
RECHECK_IDS_3970E96 = ("N1", "N2", "N3", "N4", "N7", "N8", "N9", "N10", "N11", "N12", "N14", "N15",
                       "N16", "N17", "N18", "T1", "T2", "T3", "Q1", "N19")
```

with:

```python
RECHECK_IDS_CE = ("N1", "N2", "N3", "N4", "N7", "N8", "N9", "N10", "N11", "N12", "N14", "N15",
                  "N16", "N17", "N18", "T1", "T2", "T3", "N23", "Q1", "N19")
```

**3.18.** `test_sft1a_planner_constants`: its use (CR4). Edit `tests/test_shot_format.py`: replace this text, which occurs exactly once:

```python
    assert se.RECHECK_IDS == RECHECK_IDS_3970E96
```

with:

```python
    assert se.RECHECK_IDS == RECHECK_IDS_CE
```

**3.19.** `test_sft2_the_plan_prompt`: `CAMERA_LIST` (CR1). Edit `tests/test_shot_format.py`: replace this text, which occurs exactly once:

```python
CAMERA_LIST = ("camera is exactly one of: slow push-in, slow pull-back, tracking, handheld, slow "
               "pan left, slow pan right, slow tilt up, slow tilt down, static.")
```

with:

```python
CAMERA_LIST = ("camera is exactly one of: slow push-in, slow pull-back, slow tracking left, slow "
               "tracking right, handheld, slow pan left, slow pan right, slow tilt up, slow tilt "
               "down, slow crane up, slow crane down, slow orbit, static.")
```

**3.20.** `test_sft1b_writer_constants`: the two tracking forms (CR1). Edit `tests/test_shot_format.py`: replace this text, which occurs exactly once:

```python
    "tracking": ("tracks the movement", "'The camera tracks <whom it follows> — as the move "
                                        "completes, <where the frame ends>.'"),
    "handheld": ("moves handheld", "'The camera follows with handheld movement — as the move "
```

with:

```python
    "tracking": ("tracks the movement", "'The camera tracks <whom it follows> — as the move "
                                        "completes, <where the frame ends>.'"),
    "slow tracking left": ("tracks left", "'The camera tracks left alongside <whom it follows> — "
                                         "as the move completes, <where the frame ends>.'"),
    "slow tracking right": ("tracks right", "'The camera tracks right alongside <whom it "
                                            "follows> — as the move completes, <where the frame "
                                            "ends>.'"),
    "handheld": ("moves handheld", "'The camera follows with handheld movement — as the move "
```

**3.21.** `test_sft1b_writer_constants`: the crane and orbit forms (CR1). Edit `tests/test_shot_format.py`: replace this text, which occurs exactly once:

```python
    "slow tilt down": ("tilts down", "'The camera tilts down — as the move completes, <what the "
                                     "frame ends on>.'"),
    "static": ("stays static", "'The camera stays static, holding <what stays in the frame>.'"),
```

with:

```python
    "slow tilt down": ("tilts down", "'The camera tilts down — as the move completes, <what the "
                                     "frame ends on>.'"),
    "slow crane up": ("cranes up", "'The camera cranes up — as the move completes, <what the "
                                   "frame ends on>.'"),
    "slow crane down": ("cranes down", "'The camera cranes down — as the move completes, <what "
                                       "the frame ends on>.'"),
    "slow orbit": ("arcs around the subject in a partial orbit", "'The camera arcs around <whom "
                   "it circles> in a partial orbit — as the move completes, <where the frame "
                   "ends>.'"),
    "static": ("stays static", "'The camera stays static, holding <what stays in the frame>.'"),
```

**3.22.** `test_sft1b_writer_constants`: the reference hash (CR2). Edit `tests/test_shot_format.py`: replace this text, which occurs exactly once:

```python
FORMAT_REFERENCE_SHA256 = "d2fe46c687bdaf8ebc75235bdf530d5d751aa1fa62f9bf393bf9855bef7681dd"
```

with:

```python
FORMAT_REFERENCE_SHA256 = "990aeb28a929b910786b30cef2288cb16ed9910b88a3d7011778d31f4ca96efe"
```

**3.23.** `test_sft1b_writer_constants`: the reference length (CR2). Edit `tests/test_shot_format.py`: replace this text, which occurs exactly once:

```python
    assert (len(reference), len(reference.split())) == (2406, 421)
```

with:

```python
    assert (len(reference), len(reference.split())) == (3538, 618)
```

**3.24.** `test_sft21_the_reference_adds_exactly_its_own_length` (CR2). Edit `tests/test_shot_format.py`: replace this text, which occurs exactly once:

```python
    assert len(full) - len(bare) == len(reference) == 2406
```

with:

```python
    assert len(full) - len(bare) == len(reference) == 3538
```

**3.25.** `test_sft1c_check_constants`: `REFERENCE_TERMS` and `REFERENCE_COPY_SEGMENTS` (CR2). Edit `tests/test_shot_format.py`: replace this text, which occurs exactly once:

```python
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
```

with:

```python
REFERENCE_TERMS = ("fishmonger", "fishmongers", "herring", "herrings", "zinc", "ice trays",
                   "market hall", "fish market", "harbour doors", "meltwater",
                   "forty years of mornings", "half-open shutter")
REFERENCE_COPY_SEGMENTS = (
    "The old fishmonger drags a tall stack of empty herring crates across the wet concrete of "
    "the market hall toward the half-open shutter",
    "her heavy steps splashing through shallow puddles that hold the first glow from the "
    "harbour doors",
    "The old fishmonger turns back from the shutter and walks to the zinc counter",
    "laying her folded cloth beside the empty ice trays",
    "The old fishmonger presses both palms flat on the folded cloth, her shoulders sinking",
    "The old fishmonger lowers her forehead onto her folded hands on the cold zinc counter",
    "her breath fogging the metal as a thin trickle of meltwater runs past her knuckles and "
    "drips to the wet floor",
    "Forty years of mornings. Not one more.",
)
```

**3.26.** `test_sft1c_check_constants`: `GENERATION_CHECKS` (CR4). Edit `tests/test_shot_format.py`: replace this text, which occurs exactly once:

```python
                     "N14", "N15", "N16", "N17", "N18", "T1", "T2", "T3", "N20", "N21", "N22",
                     "Q1", "N19")


def test_sft1c_check_constants():
```

with:

```python
                     "N14", "N15", "N16", "N17", "N18", "T1", "T2", "T3", "N20", "N21", "N22",
                     "N23", "Q1", "N19")


def test_sft1c_check_constants():
```

**3.27.** `test_sft1c_check_constants`: 80 six-word runs (CR2). Edit `tests/test_shot_format.py`: replace this text, which occurs exactly once:

```python
    assert len(se.REFERENCE_SIX_GRAMS) == 138
```

with:

```python
    assert len(se.REFERENCE_SIX_GRAMS) == 80
```

**3.28.** `test_sft12_reference_copies`: the ice-trays row becomes a CE11 segment row (CR2). Edit `tests/test_shot_format.py`: replace this text, which occurs exactly once:

```python
    hits = se.reference_copies(narrative, raw,
                               "The courier looks up from the empty ice trays to the camera")
    assert hits[0] == "ice trays"
    assert "looks up from the empty ice" in hits
```

with:

```python
    hits = se.reference_copies(narrative, raw,
                               "The courier lays the folded cloth beside the empty ice trays")
    assert hits[0] == "ice trays"
    assert "folded cloth beside the empty ice" in hits
```

**3.29.** `test_sft12_reference_copies`: the N22 message of segment 4 (CR2). Edit `tests/test_shot_format.py`: replace this text, which occurs exactly once:

```python
        "panel 1: N22 reference copy: Motion: copies the format reference ('fishmonger', 'cloth "
        "drop onto the counter her', 'drop onto the counter her shoulders'); describe only this "
        "movie's own people, places, objects and words"]
```

with:

```python
        "panel 1: N22 reference copy: Motion: copies the format reference ('fishmonger', 'both "
        "palms flat on the folded', 'fishmonger presses both palms flat on'); describe only this "
        "movie's own people, places, objects and words"]
```

**3.30.** `test_sft12_reference_copies`: the corpus guard removes the plan reference that the re-baselined prompt fixtures quote (CR3; Plan ruling R13). Edit `tests/test_shot_format.py`: replace this text, which occurs exactly once:

```python
            with open(os.path.join(root, name), encoding="utf-8") as f:
                words = se.line_words(f.read())
```

with:

```python
            with open(os.path.join(root, name), encoding="utf-8") as f:
                text = f.read()
            # Chained end frames spec CR3: the plan prompt fixtures quote the plan reference whole.
            for reference in (se.plan_reference(True), se.plan_reference(False)):
                text = text.replace(reference, "")
            words = se.line_words(text)
```

**3.31.** `test_review_focus_3_an_end_frame_in_the_references_words_falls_back`: a clause in a CE11 segment's words (CR2). Edit `tests/test_shot_format.py`: replace this text, which occurs exactly once:

```python
    camera = ("The camera pushes in — as the move completes, her face fills the frame from chin "
              "to brow.")
```

with:

```python
    camera = ("The camera pushes in — as the move completes, she lays her folded cloth beside "
              "the empty ice trays.")
```

**3.32.** `REF_PARTS` becomes the CE11 parts table (CR2). Edit `tests/test_shot_format.py`: replace this text, which occurs exactly once:

```python
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
```

with:

```python
REF_PARTS = (
    {"shot": "The shot is a medium shot.",
     "motion": ("The old fishmonger drags a tall stack of empty herring crates across the wet "
                "concrete of the market hall toward the half-open shutter at real-time speed, her "
                "heavy steps splashing through shallow puddles that hold the first glow from the "
                "harbour doors. The camera tracks right alongside her — as the move completes, "
                "the old fishmonger stands beside the half-open shutter at frame centre, facing "
                "left toward the hall, seen from the knees up, the empty crates at her feet."),
     "speaker": None, "line": ""},
    {"shot": "The shot is a medium shot.",
     "motion": ("The old fishmonger turns back from the shutter and walks to the zinc counter at "
                "real-time speed, laying her folded cloth beside the empty ice trays and lifting "
                "her face to the camera. The old fishmonger presses both palms flat on the folded "
                "cloth, her shoulders sinking. The camera pushes in — as the move completes, the "
                "old fishmonger stands behind the zinc counter at frame centre, facing forward, "
                "her face filling the frame from chin to brow. The old fishmonger faces the "
                "camera."),
     "speaker": "the old fishmonger", "line": "Forty years of mornings. Not one more."},
    {"shot": "The shot is a close-up.",
     "motion": ("The old fishmonger lowers her forehead onto her folded hands on the cold zinc "
                "counter at real-time speed, her breath fogging the metal as a thin trickle of "
                "meltwater runs past her knuckles and drips to the wet floor. The camera stays "
                "static, holding the old fishmonger as she rests her forehead on her folded hands "
                "at frame centre, eyes closed, her head and hands filling the frame."),
     "speaker": None, "line": ""},
)
```

**3.33.** `test_sft13_the_composition_and_the_reference`: the shot-1 key and the reaction (CR2). Edit `tests/test_shot_format.py`: replace this text, which occurs exactly once:

```python
    for part, key in zip(REF_PARTS, ("tracking", "slow push-in", "static")):
        assert se.camera_problem(lib, part["motion"], [REF_PHRASE], key) is None, key
    post = se.post_line_sentences(lib, REF_PARTS[1]["motion"], [REF_PHRASE])
    assert post == ["The old fishmonger lets the folded cloth drop onto the counter, her "
                    "shoulders sinking."]
```

with:

```python
    for part, key in zip(REF_PARTS, ("slow tracking right", "slow push-in", "static")):
        assert se.camera_problem(lib, part["motion"], [REF_PHRASE], key) is None, key
    post = se.post_line_sentences(lib, REF_PARTS[1]["motion"], [REF_PHRASE])
    assert post == ["The old fishmonger presses both palms flat on the folded cloth, her "
                    "shoulders sinking."]
```


**`tests/test_dialogue.py`**

**3.34.** `test_dlg12_plan_prompt_speaker_rule`: `END_FRAME_RULE` and `end_frame` in chained prompts (CR3). Edit `tests/test_dialogue.py`: replace this text, which occurs exactly once:

```python
            assert ("at most %d.%s\n" % (se.MAX_CAST[mode], rule)) in prompt, where
            assert ("with the keys index, arc, action, shot, camera, location, cast and speaker."
                    in prompt), where
```

with:

```python
            end = se.END_FRAME_RULE if mode == "chained" else ""
            keys = "cast, speaker and end_frame" if mode == "chained" else "cast and speaker"
            assert ("at most %d.%s%s\n" % (se.MAX_CAST[mode], rule, end)) in prompt, where
            assert ("with the keys index, arc, action, shot, camera, location, %s." % keys
                    in prompt), where
```

**3.35.** `test_dlg21_an_advisory_only_round_0_passes_untouched`: the chained case's second plan call (CR5). Edit `tests/test_dialogue.py`: replace this text, which occurs exactly once:

```python
        assert [r["stage"] for r in seu.agent_log(log)] == ["plan", "panel", "panel", "panel"]
        story_dir = os.path.join(ws, "generated", "stories", story_id)
```

with:

```python
        assert [r["stage"] for r in seu.agent_log(log)] == (
            ["plan"] * (2 if mode == "chained" else 1) + ["panel", "panel", "panel"]), mode
        story_dir = os.path.join(ws, "generated", "stories", story_id)
```


**`tests/test_narrative_fidelity.py`**

**3.36.** `test_nf16_the_speaking_coercion_table`: the two tracking keys are kept (CR1). Edit `tests/test_narrative_fidelity.py`: replace this text, which occurs exactly once:

```python
    kept = ("slow push-in", "slow pull-back", "tracking", "handheld", "static")
```

with:

```python
    kept = ("slow push-in", "slow pull-back", "tracking", "slow tracking left",
            "slow tracking right", "handheld", "static")
```

**3.37.** `test_nf14_the_plan_retry_gate`: a plan without end frames is asked again (CR5). Edit `tests/test_narrative_fidelity.py`: replace this text, which occurs exactly once:

```python
    assert len(seu.agent_log(log)) == 1 and [b["lines"] for b in found[0]["beats"]] == [[1], [2]]
```

with:

```python
    assert len(seu.agent_log(log)) == 2 and [b["lines"] for b in found[0]["beats"]] == [[1], [2]]
```

**3.38.** `test_nf12_the_plan_prompt`: the hockey prompt (CR3). Edit `tests/test_narrative_fidelity.py`: replace this text, which occurs exactly once:

```python
    assert "location, cast, speaker and lines. index runs from 1 to the number of beats." in prompt
    assert ("at most 4." + SPEAKER_RULE + LINES_RULE.replace("@@LINE_WORDS@@", "13")
            .replace("@@MIN_BEATS@@", "2") + "\n") in prompt
```

with:

```python
    assert ("location, cast, speaker, lines and end_frame. index runs from 1 to the number of "
            "beats.") in prompt
    assert ("at most 4." + SPEAKER_RULE + LINES_RULE.replace("@@LINE_WORDS@@", "13")
            .replace("@@MIN_BEATS@@", "2") + se.END_FRAME_RULE + "\n") in prompt
```

**3.39.** `test_nf12_the_plan_prompt`: the quiet prompt (CR3). Edit `tests/test_narrative_fidelity.py`: replace this text, which occurs exactly once:

```python
    assert "location, cast and speaker. index runs" in quiet
    assert ("at most 4." + SPEAKER_RULE + "\n") in quiet
```

with:

```python
    assert "location, cast, speaker and end_frame. index runs" in quiet
    assert ("at most 4." + SPEAKER_RULE + se.END_FRAME_RULE + "\n") in quiet
```

**3.40.** `test_nf12_the_plan_prompt`: the silent prompt (CR3). Edit `tests/test_narrative_fidelity.py`: replace this text, which occurs exactly once:

```python
    assert "location, cast and speaker. index runs" in silent
    assert ("at most 4." + se.SILENT_SPEAKER_RULE + "\n") in silent
```

with:

```python
    assert "location, cast, speaker and end_frame. index runs" in silent
    assert ("at most 4." + se.SILENT_SPEAKER_RULE + se.END_FRAME_RULE + "\n") in silent
```

**3.41.** `test_nf32_no_narration_keeps_the_movie_silent`: the stages (CR5). Edit `tests/test_narrative_fidelity.py`: replace this text, which occurs exactly once:

```python
    assert rc == 0 and _stages(log) == ["plan", "panel", "panel", "panel"]
```

with:

```python
    assert rc == 0 and _stages(log) == ["plan", "plan", "panel", "panel", "panel"]
```

**3.42.** `test_nf33_default_narration_with_the_fixed_plan`: two plan calls (CR5). Edit `tests/test_narrative_fidelity.py`: replace this text, which occurs exactly once:

```python
    assert _stages(log).count("plan") == 1
    assert _story_json(ctx, "story_rounds", "round_0", "plan.json")["speech_notes"] == [
        P18_2X145, P19_NOTE % (4, 3)]
```

with:

```python
    assert _stages(log).count("plan") == 2
    assert _story_json(ctx, "story_rounds", "round_0", "plan.json")["speech_notes"] == [
        P18_2X145, P19_NOTE % (4, 3)]
```

**3.43.** `test_nf33_default_narration_with_the_fixed_plan`: the stages (CR5). Edit `tests/test_narrative_fidelity.py`: replace this text, which occurs exactly once:

```python
    assert _stages(log) == ["plan", "panel", "panel", "panel"]
    assert "Warning: unresolved" not in capsys.readouterr().out
```

with:

```python
    assert _stages(log) == ["plan", "plan", "panel", "panel", "panel"]
    assert "Warning: unresolved" not in capsys.readouterr().out
```


**`tests/test_pinned_cast.py`**

**3.44.** `test_pt16_two_pinned_chained_every_line_spoken_by_c1`: the stages (CR5). Edit `tests/test_pinned_cast.py`: replace this text, which occurs exactly once:

```python
    rc, ctx, log = _pt16_run(ws, tmp_path, monkeypatch, story_env)
    assert rc == 0
    assert [r["stage"] for r in log] == ["plan", "panel", "panel", "panel"]
```

with:

```python
    rc, ctx, log = _pt16_run(ws, tmp_path, monkeypatch, story_env)
    assert rc == 0
    assert [r["stage"] for r in log] == ["plan", "plan", "panel", "panel", "panel"]
```


**`tests/test_soft_panel_count.py`**

**3.45.** `test_spt4_the_plan_prompt`: `SPC4_EXAMPLE`'s beat keys (CR3). Edit `tests/test_soft_panel_count.py`: replace this text, which occurs exactly once:

```python
    "beats: a list of 3 to 5 objects, one per panel in order, with the keys index, arc, action, "
    "shot, camera, location, cast and speaker. index runs from 1 to the number of beats. This "
```

with:

```python
    "beats: a list of 3 to 5 objects, one per panel in order, with the keys index, arc, action, "
    "shot, camera, location, cast, speaker and end_frame. index runs from 1 to the number of "
    "beats. This "
```

**3.46.** `test_spt8_e2e_one_beat_added`: the stages (CR5). Edit `tests/test_soft_panel_count.py`: replace this text, which occurs exactly once:

```python
    assert [r["stage"] for r in log][:5] == ["plan", "panel", "panel", "panel", "panel"]
```

with:

```python
    assert [r["stage"] for r in log][:6] == ["plan", "plan", "panel", "panel", "panel", "panel"]
```


**`tests/test_speaker_attribution.py`**

**3.47.** `test_sat9_plan_prompt`: `END_FRAME_RULE` after the speakers sentence (CR3). Edit `tests/test_speaker_attribution.py`: replace this text, which occurs exactly once:

```python
    prompt, rule = _plan_prompt(ws, mode="chained", members=members, narrative=LINES_NARRATIVE)
    assert rule + both + "\nloras: " in prompt
```

with:

```python
    prompt, rule = _plan_prompt(ws, mode="chained", members=members, narrative=LINES_NARRATIVE)
    assert rule + both + se.END_FRAME_RULE + "\nloras: " in prompt
```

**3.48.** `test_sat9_plan_prompt`: `END_FRAME_RULE` after the lines rule (CR3). Edit `tests/test_speaker_attribution.py`: replace this text, which occurs exactly once:

```python
    prompt, rule = _plan_prompt(ws, mode="chained", members=members, narrative=PRONOUN_NARRATIVE)
    assert rule + "\nloras: " in prompt
```

with:

```python
    prompt, rule = _plan_prompt(ws, mode="chained", members=members, narrative=PRONOUN_NARRATIVE)
    assert rule + se.END_FRAME_RULE + "\nloras: " in prompt
```


**`tests/test_movie_ui_http.py`**

**3.49.** `test_mut18_every_api_route_needs_the_token`: 55 routes (CR7). Edit `tests/test_movie_ui_http.py`: replace this text, which occurs exactly once:

```python
    assert len(srv.ROUTES) == 54
```

with:

```python
    assert len(srv.ROUTES) == 55
```


**`tests/test_location_ui.py`**

**3.50.** `test_lu1_the_location_routes_need_the_token`: 55 routes (CR7). Edit `tests/test_location_ui.py`: replace this text, which occurs exactly once:

```python
    assert len(srv.ROUTES) == 54
```

with:

```python
    assert len(srv.ROUTES) == 55
```


**`tests/test_movie_ui_builder.py`**

**3.51.** `test_mut26_pipeline_files_are_unchanged`: the comment (CR6). Type the 40 characters of **SHA** (Step 2) in place of the word `SHA`. Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
then to 44beb3d67ad5af05093e29e1c6fc088330b41386 (location library).
```

with:

```python
then to 44beb3d67ad5af05093e29e1c6fc088330b41386 (location library), then to SHA (chained end frames).
```

**3.52.** `test_mut26_pipeline_files_are_unchanged`: `BASELINE` (CR6). Type **SHA** in place of the word `SHA`. Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
    BASELINE = "44beb3d67ad5af05093e29e1c6fc088330b41386"
```

with:

```python
    BASELINE = "SHA"
```


**`tests/fixtures/location/plan_prompt_chained.txt`**

**3.53.** The fixture's plan reference (CR3). Edit `tests/fixtures/location/plan_prompt_chained.txt`: replace this text, which occurs exactly once:

```text
Rules for this movie: keep consecutive beats at the same location unless the action itself moves the characters there, and put every character who can be seen in the opening frame in beat 1's cast.

```

with:

```text
Rules for this movie: keep consecutive beats at the same location unless the action itself moves the characters there, and put every character who can be seen in the opening frame in beat 1's cast.

FORMAT REFERENCE ONLY — never reuse its people, places, objects or words. This is the complete plan of a three-beat movie made as one continuous take, a different story from this one. It shows the format of every plan: each beat's end_frame says exactly where the beat ends, the next beat's action starts from that end frame, and the last end frame closes the story.
{"title": "The Last Morning at the Market", "logline": "At dawn an old fishmonger closes her market hall for the last time and says goodbye to forty years of work.",
 "cast": [{"id": "c1", "phrase": "the old fishmonger", "descriptor": "an old woman with a stooped build, weathered pale skin and short grey hair under a knitted cap, wearing a rubber apron over a thick wool jumper and tall rubber boots"}],
 "locations": [{"id": "l1", "setting": "The setting is a covered fish market hall in a northern harbour town at dawn, wet concrete underfoot, rows of bare zinc counters behind, under grey first light from the harbour doors."}],
 "props": [{"id": "p1", "name": "the herring crates"}, {"id": "p2", "name": "the folded cloth"}],
 "beats": [
  {"index": 1, "arc": "introduction", "action": "The old fishmonger drags a tall stack of empty herring crates across the wet market hall to the half-open shutter.", "shot": "medium shot", "camera": "slow tracking right", "location": "l1", "cast": ["c1"], "speaker": "", "end_frame": "The old fishmonger stands beside the half-open shutter at frame centre, facing left toward the hall, seen from the knees up, the empty crates at her feet."},
  {"index": 2, "arc": "climax", "action": "From the shutter, the old fishmonger turns back into the hall and walks to the zinc counter, laying her folded cloth on it.", "shot": "medium shot", "camera": "slow push-in", "location": "l1", "cast": ["c1"], "speaker": "c1", "end_frame": "The old fishmonger stands behind the zinc counter at frame centre, facing forward, her face filling the frame from chin to brow."},
  {"index": 3, "arc": "resolution", "action": "The old fishmonger lowers her forehead onto her folded hands on the cold zinc counter and closes her eyes.", "shot": "close-up", "camera": "static", "location": "l1", "cast": ["c1"], "speaker": "", "end_frame": "The old fishmonger rests her forehead on her folded hands at frame centre, eyes closed, her head and hands filling the frame in a close-up."}],
 "loras": {"global": [], "per_beat": {}, "stills": []}}

```

**3.54.** The fixture's beats line: the beat keys, the camera list, `CAMERA_SPEAKING_SENTENCE` and `END_FRAME_RULE` (CR1, CR3). Edit `tests/fixtures/location/plan_prompt_chained.txt`: replace this text, which occurs exactly once:

```text
beats: a list of 3 to 5 objects, one per panel in order, with the keys index, arc, action, shot, camera, location, cast and speaker. index runs from 1 to the number of beats. This movie's target length is 3 beats, and like a word range it is soft: use 3 beats when the narrative fits them, and add a beat, up to 5 beats in all, only for something the narrative needs that no other beat can hold. arc is one of introduction, rising, climax, falling, resolution, in story order; the first beat is introduction, the last is resolution, and at least one beat is climax. action is one sentence of 6 to 40 words saying what the characters physically do during these 6 seconds: one continuous physical action that a camera can film, not a sequence of steps, with no on-screen text. shot is exactly one of: extreme wide shot, wide shot, medium shot, medium close-up, close-up, extreme close-up. camera is exactly one of: slow push-in, slow pull-back, tracking, handheld, slow pan left, slow pan right, slow tilt up, slow tilt down, static. Give every beat one camera move from this list, and use static only for a deliberate hold: at most one beat in three may be static, so at most 1 in this movie. On a beat with a speaker, prefer slow push-in, slow pull-back, tracking or handheld, and never use a pan or a tilt, which sweeps the speaker's face out of the frame. location is the id of the place where the beat happens. cast is the list of ids of the characters on screen in the beat, at most 4. speaker is the id of the one character who says something aloud on screen during the beat, or an empty string when nobody speaks; give a speaker only where a spoken line moves the story. A beat with a speaker shows only that character (its cast is just their id), facing the camera, in a medium shot, medium close-up or close-up; the speaker may move during the beat, as long as their face stays in frame and lit while they speak. Write a speaking beat's action as what the speaker physically does, never as speaking, and end it with the speaker still in frame: nobody else acts after the line, and when the narrative has the speaker leave, or another character act, after a line, give that a later beat with no speaker, adding that beat when the beat count allows it, and leave it out only when it does not.
```

with:

```text
beats: a list of 3 to 5 objects, one per panel in order, with the keys index, arc, action, shot, camera, location, cast, speaker and end_frame. index runs from 1 to the number of beats. This movie's target length is 3 beats, and like a word range it is soft: use 3 beats when the narrative fits them, and add a beat, up to 5 beats in all, only for something the narrative needs that no other beat can hold. arc is one of introduction, rising, climax, falling, resolution, in story order; the first beat is introduction, the last is resolution, and at least one beat is climax. action is one sentence of 6 to 40 words saying what the characters physically do during these 6 seconds: one continuous physical action that a camera can film, not a sequence of steps, with no on-screen text. shot is exactly one of: extreme wide shot, wide shot, medium shot, medium close-up, close-up, extreme close-up. camera is exactly one of: slow push-in, slow pull-back, slow tracking left, slow tracking right, handheld, slow pan left, slow pan right, slow tilt up, slow tilt down, slow crane up, slow crane down, slow orbit, static. Give every beat one camera move from this list, and use static only for a deliberate hold: at most one beat in three may be static, so at most 1 in this movie. On a beat with a speaker, prefer slow push-in, slow pull-back, slow tracking left, slow tracking right or handheld, and never use a pan, a tilt, a crane or an orbit, which sweep the speaker's face out of the frame. location is the id of the place where the beat happens. cast is the list of ids of the characters on screen in the beat, at most 4. speaker is the id of the one character who says something aloud on screen during the beat, or an empty string when nobody speaks; give a speaker only where a spoken line moves the story. A beat with a speaker shows only that character (its cast is just their id), facing the camera, in a medium shot, medium close-up or close-up; the speaker may move during the beat, as long as their face stays in frame and lit while they speak. Write a speaking beat's action as what the speaker physically does, never as speaking, and end it with the speaker still in frame: nobody else acts after the line, and when the narrative has the speaker leave, or another character act, after a line, give that a later beat with no speaker, adding that beat when the beat count allows it, and leave it out only when it does not. end_frame is one sentence of 8 to 30 words, in the present tense, of the frame the beat ends on: who or what is in frame, where each one is (left, centre or right; foreground or background), which way they face and how tight the shot is. It never names a camera move, the lighting, a colour or a style, has no spoken words and no double quotes, and names only characters in the beat's cast. Beat k's end frame is exactly where beat k+1 begins; write beat k+1's action so it starts from that composition. The last beat's end frame closes the story.
```


**`tests/fixtures/location/plan_prompt_chained_cast.txt`**

**3.55.** The fixture's plan reference (CR3). Edit `tests/fixtures/location/plan_prompt_chained_cast.txt`: replace this text, which occurs exactly once:

```text
Rules for this movie: keep consecutive beats at the same location unless the action itself moves the characters there, and put every character who can be seen in the opening frame in beat 1's cast.

```

with:

```text
Rules for this movie: keep consecutive beats at the same location unless the action itself moves the characters there, and put every character who can be seen in the opening frame in beat 1's cast.

FORMAT REFERENCE ONLY — never reuse its people, places, objects or words. This is the complete plan of a three-beat movie made as one continuous take, a different story from this one. It shows the format of every plan: each beat's end_frame says exactly where the beat ends, the next beat's action starts from that end frame, and the last end frame closes the story.
{"title": "The Last Morning at the Market", "logline": "At dawn an old fishmonger closes her market hall for the last time and says goodbye to forty years of work.",
 "cast": [{"id": "c1", "phrase": "the old fishmonger", "descriptor": "an old woman with a stooped build, weathered pale skin and short grey hair under a knitted cap, wearing a rubber apron over a thick wool jumper and tall rubber boots"}],
 "locations": [{"id": "l1", "setting": "The setting is a covered fish market hall in a northern harbour town at dawn, wet concrete underfoot, rows of bare zinc counters behind, under grey first light from the harbour doors."}],
 "props": [{"id": "p1", "name": "the herring crates"}, {"id": "p2", "name": "the folded cloth"}],
 "beats": [
  {"index": 1, "arc": "introduction", "action": "The old fishmonger drags a tall stack of empty herring crates across the wet market hall to the half-open shutter.", "shot": "medium shot", "camera": "slow tracking right", "location": "l1", "cast": ["c1"], "speaker": "", "end_frame": "The old fishmonger stands beside the half-open shutter at frame centre, facing left toward the hall, seen from the knees up, the empty crates at her feet."},
  {"index": 2, "arc": "climax", "action": "From the shutter, the old fishmonger turns back into the hall and walks to the zinc counter, laying her folded cloth on it.", "shot": "medium shot", "camera": "slow push-in", "location": "l1", "cast": ["c1"], "speaker": "c1", "end_frame": "The old fishmonger stands behind the zinc counter at frame centre, facing forward, her face filling the frame from chin to brow."},
  {"index": 3, "arc": "resolution", "action": "The old fishmonger lowers her forehead onto her folded hands on the cold zinc counter and closes her eyes.", "shot": "close-up", "camera": "static", "location": "l1", "cast": ["c1"], "speaker": "", "end_frame": "The old fishmonger rests her forehead on her folded hands at frame centre, eyes closed, her head and hands filling the frame in a close-up."}],
 "loras": {"global": [], "per_beat": {}, "stills": []}}

```

**3.56.** The fixture's beats line: the beat keys, the camera list, `CAMERA_SPEAKING_SENTENCE` and `END_FRAME_RULE` (CR1, CR3). Edit `tests/fixtures/location/plan_prompt_chained_cast.txt`: replace this text, which occurs exactly once:

```text
beats: a list of 3 to 5 objects, one per panel in order, with the keys index, arc, action, shot, camera, location, cast and speaker. index runs from 1 to the number of beats. This movie's target length is 3 beats, and like a word range it is soft: use 3 beats when the narrative fits them, and add a beat, up to 5 beats in all, only for something the narrative needs that no other beat can hold. arc is one of introduction, rising, climax, falling, resolution, in story order; the first beat is introduction, the last is resolution, and at least one beat is climax. action is one sentence of 6 to 40 words saying what the characters physically do during these 6 seconds: one continuous physical action that a camera can film, not a sequence of steps, with no on-screen text. shot is exactly one of: extreme wide shot, wide shot, medium shot, medium close-up, close-up, extreme close-up. camera is exactly one of: slow push-in, slow pull-back, tracking, handheld, slow pan left, slow pan right, slow tilt up, slow tilt down, static. Give every beat one camera move from this list, and use static only for a deliberate hold: at most one beat in three may be static, so at most 1 in this movie. On a beat with a speaker, prefer slow push-in, slow pull-back, tracking or handheld, and never use a pan or a tilt, which sweeps the speaker's face out of the frame. location is the id of the place where the beat happens. cast is the list of ids of the characters on screen in the beat, at most 4. speaker is the id of the one character who says something aloud on screen during the beat, or an empty string when nobody speaks; give a speaker only where a spoken line moves the story. A beat with a speaker shows that character facing the camera, in a medium shot, medium close-up or close-up; its cast is the speaker's id plus the id of every already-cast character who is still in frame and stays silent, and no character of your own. The speaker may move during the beat, as long as their face stays in frame and lit while they speak. Write a speaking beat's action as what the speaker physically does, never as speaking, and end it with the speaker still in frame: nobody else acts after the line, and when the narrative has the speaker leave, or another character act, after a line, give that a later beat with no speaker, adding that beat when the beat count allows it, and leave it out only when it does not.
```

with:

```text
beats: a list of 3 to 5 objects, one per panel in order, with the keys index, arc, action, shot, camera, location, cast, speaker and end_frame. index runs from 1 to the number of beats. This movie's target length is 3 beats, and like a word range it is soft: use 3 beats when the narrative fits them, and add a beat, up to 5 beats in all, only for something the narrative needs that no other beat can hold. arc is one of introduction, rising, climax, falling, resolution, in story order; the first beat is introduction, the last is resolution, and at least one beat is climax. action is one sentence of 6 to 40 words saying what the characters physically do during these 6 seconds: one continuous physical action that a camera can film, not a sequence of steps, with no on-screen text. shot is exactly one of: extreme wide shot, wide shot, medium shot, medium close-up, close-up, extreme close-up. camera is exactly one of: slow push-in, slow pull-back, slow tracking left, slow tracking right, handheld, slow pan left, slow pan right, slow tilt up, slow tilt down, slow crane up, slow crane down, slow orbit, static. Give every beat one camera move from this list, and use static only for a deliberate hold: at most one beat in three may be static, so at most 1 in this movie. On a beat with a speaker, prefer slow push-in, slow pull-back, slow tracking left, slow tracking right or handheld, and never use a pan, a tilt, a crane or an orbit, which sweep the speaker's face out of the frame. location is the id of the place where the beat happens. cast is the list of ids of the characters on screen in the beat, at most 4. speaker is the id of the one character who says something aloud on screen during the beat, or an empty string when nobody speaks; give a speaker only where a spoken line moves the story. A beat with a speaker shows that character facing the camera, in a medium shot, medium close-up or close-up; its cast is the speaker's id plus the id of every already-cast character who is still in frame and stays silent, and no character of your own. The speaker may move during the beat, as long as their face stays in frame and lit while they speak. Write a speaking beat's action as what the speaker physically does, never as speaking, and end it with the speaker still in frame: nobody else acts after the line, and when the narrative has the speaker leave, or another character act, after a line, give that a later beat with no speaker, adding that beat when the beat count allows it, and leave it out only when it does not. end_frame is one sentence of 8 to 30 words, in the present tense, of the frame the beat ends on: who or what is in frame, where each one is (left, centre or right; foreground or background), which way they face and how tight the shot is. It never names a camera move, the lighting, a colour or a style, has no spoken words and no double quotes, and names only characters in the beat's cast. Beat k's end frame is exactly where beat k+1 begins; write beat k+1's action so it starts from that composition. The last beat's end frame closes the story.
```


**`tests/fixtures/location/plan_prompt_shots.txt`**

**3.57.** The fixture's beats line: the camera list and `CAMERA_SPEAKING_SENTENCE` (CR1). Edit `tests/fixtures/location/plan_prompt_shots.txt`: replace this text, which occurs exactly once:

```text
beats: a list of 4 to 6 objects, one per panel in order, with the keys index, arc, action, shot, camera, location, cast and speaker. index runs from 1 to the number of beats. This movie's target length is 4 beats, and like a word range it is soft: use 4 beats when the narrative fits them, and add a beat, up to 6 beats in all, only for something the narrative needs that no other beat can hold. arc is one of introduction, rising, climax, falling, resolution, in story order; the first beat is introduction, the last is resolution, and at least one beat is climax. action is one sentence of 6 to 40 words saying what the characters physically do during these 6 seconds: one continuous physical action that a camera can film, not a sequence of steps, with no on-screen text. shot is exactly one of: extreme wide shot, wide shot, medium shot, medium close-up, close-up, extreme close-up. camera is exactly one of: slow push-in, slow pull-back, tracking, handheld, slow pan left, slow pan right, slow tilt up, slow tilt down, static. Give every beat one camera move from this list, and use static only for a deliberate hold: at most one beat in three may be static, so at most 2 in this movie. On a beat with a speaker, prefer slow push-in, slow pull-back, tracking or handheld, and never use a pan or a tilt, which sweeps the speaker's face out of the frame. location is the id of the place where the beat happens. cast is the list of ids of the characters on screen in the beat, at most 2. speaker is the id of the one character who says something aloud on screen during the beat, or an empty string when nobody speaks; give a speaker only where a spoken line moves the story. A beat with a speaker shows only that character (its cast is just their id), facing the camera, in a medium shot, medium close-up or close-up; the speaker may move during the beat, as long as their face stays in frame and lit while they speak. Write a speaking beat's action as what the speaker physically does, never as speaking, and end it with the speaker still in frame: nobody else acts after the line, and when the narrative has the speaker leave, or another character act, after a line, give that a later beat with no speaker, adding that beat when the beat count allows it, and leave it out only when it does not.
```

with:

```text
beats: a list of 4 to 6 objects, one per panel in order, with the keys index, arc, action, shot, camera, location, cast and speaker. index runs from 1 to the number of beats. This movie's target length is 4 beats, and like a word range it is soft: use 4 beats when the narrative fits them, and add a beat, up to 6 beats in all, only for something the narrative needs that no other beat can hold. arc is one of introduction, rising, climax, falling, resolution, in story order; the first beat is introduction, the last is resolution, and at least one beat is climax. action is one sentence of 6 to 40 words saying what the characters physically do during these 6 seconds: one continuous physical action that a camera can film, not a sequence of steps, with no on-screen text. shot is exactly one of: extreme wide shot, wide shot, medium shot, medium close-up, close-up, extreme close-up. camera is exactly one of: slow push-in, slow pull-back, slow tracking left, slow tracking right, handheld, slow pan left, slow pan right, slow tilt up, slow tilt down, slow crane up, slow crane down, slow orbit, static. Give every beat one camera move from this list, and use static only for a deliberate hold: at most one beat in three may be static, so at most 2 in this movie. On a beat with a speaker, prefer slow push-in, slow pull-back, slow tracking left, slow tracking right or handheld, and never use a pan, a tilt, a crane or an orbit, which sweep the speaker's face out of the frame. location is the id of the place where the beat happens. cast is the list of ids of the characters on screen in the beat, at most 2. speaker is the id of the one character who says something aloud on screen during the beat, or an empty string when nobody speaks; give a speaker only where a spoken line moves the story. A beat with a speaker shows only that character (its cast is just their id), facing the camera, in a medium shot, medium close-up or close-up; the speaker may move during the beat, as long as their face stays in frame and lit while they speak. Write a speaking beat's action as what the speaker physically does, never as speaking, and end it with the speaker still in frame: nobody else acts after the line, and when the narrative has the speaker leave, or another character act, after a line, give that a later beat with no speaker, adding that beat when the beat count allows it, and leave it out only when it does not.
```


**`tests/fixtures/pinned_cast/uncast_chained_lines.txt`**

**3.58.** The fixture's plan reference (CR3). Edit `tests/fixtures/pinned_cast/uncast_chained_lines.txt`: replace this text, which occurs exactly once:

```text
Rules for this movie: keep consecutive beats at the same location unless the action itself moves the characters there, and put every character who can be seen in the opening frame in beat 1's cast.

```

with:

```text
Rules for this movie: keep consecutive beats at the same location unless the action itself moves the characters there, and put every character who can be seen in the opening frame in beat 1's cast.

FORMAT REFERENCE ONLY — never reuse its people, places, objects or words. This is the complete plan of a three-beat movie made as one continuous take, a different story from this one. Its narrative quoted two spoken lines: 1 "Forty years of mornings." and 2 "Not one more." It shows the format of every plan: each beat's end_frame says exactly where the beat ends, the next beat's action starts from that end frame, and the last end frame closes the story.
{"title": "The Last Morning at the Market", "logline": "At dawn an old fishmonger closes her market hall for the last time and says goodbye to forty years of work.",
 "cast": [{"id": "c1", "phrase": "the old fishmonger", "descriptor": "an old woman with a stooped build, weathered pale skin and short grey hair under a knitted cap, wearing a rubber apron over a thick wool jumper and tall rubber boots"}],
 "locations": [{"id": "l1", "setting": "The setting is a covered fish market hall in a northern harbour town at dawn, wet concrete underfoot, rows of bare zinc counters behind, under grey first light from the harbour doors."}],
 "props": [{"id": "p1", "name": "the herring crates"}, {"id": "p2", "name": "the folded cloth"}],
 "beats": [
  {"index": 1, "arc": "introduction", "action": "The old fishmonger drags a tall stack of empty herring crates across the wet market hall to the half-open shutter.", "shot": "medium shot", "camera": "slow tracking right", "location": "l1", "cast": ["c1"], "speaker": "", "lines": [], "end_frame": "The old fishmonger stands beside the half-open shutter at frame centre, facing left toward the hall, seen from the knees up, the empty crates at her feet."},
  {"index": 2, "arc": "climax", "action": "From the shutter, the old fishmonger turns back into the hall and walks to the zinc counter, laying her folded cloth on it.", "shot": "medium shot", "camera": "slow push-in", "location": "l1", "cast": ["c1"], "speaker": "c1", "lines": [1, 2], "end_frame": "The old fishmonger stands behind the zinc counter at frame centre, facing forward, her face filling the frame from chin to brow."},
  {"index": 3, "arc": "resolution", "action": "The old fishmonger lowers her forehead onto her folded hands on the cold zinc counter and closes her eyes.", "shot": "close-up", "camera": "static", "location": "l1", "cast": ["c1"], "speaker": "", "lines": [], "end_frame": "The old fishmonger rests her forehead on her folded hands at frame centre, eyes closed, her head and hands filling the frame in a close-up."}],
 "loras": {"global": [], "per_beat": {}, "stills": []}}

```

**3.59.** The fixture's beats line: the beat keys, the camera list, `CAMERA_SPEAKING_SENTENCE` and `END_FRAME_RULE` (CR1, CR3). Edit `tests/fixtures/pinned_cast/uncast_chained_lines.txt`: replace this text, which occurs exactly once:

```text
beats: a list of 3 to 5 objects, one per panel in order, with the keys index, arc, action, shot, camera, location, cast, speaker and lines. index runs from 1 to the number of beats. This movie's target length is 3 beats, and like a word range it is soft: use 3 beats when the narrative fits them, and add a beat, up to 5 beats in all, only for something the narrative needs that no other beat can hold. A spoken line that cannot share a beat with the line beside it gets a beat of its own. arc is one of introduction, rising, climax, falling, resolution, in story order; the first beat is introduction, the last is resolution, and at least one beat is climax. action is one sentence of 6 to 40 words saying what the characters physically do during these 6 seconds: one continuous physical action that a camera can film, not a sequence of steps, with no on-screen text. shot is exactly one of: medium shot, medium close-up, close-up (characters speak on screen in this movie, so only these framings keep the speaker's lips readable). camera is exactly one of: slow push-in, slow pull-back, tracking, handheld, slow pan left, slow pan right, slow tilt up, slow tilt down, static. Give every beat one camera move from this list, and use static only for a deliberate hold: at most one beat in three may be static, so at most 1 in this movie. On a beat with a speaker, prefer slow push-in, slow pull-back, tracking or handheld, and never use a pan or a tilt, which sweeps the speaker's face out of the frame. location is the id of the place where the beat happens. cast is the list of ids of the characters on screen in the beat, at most 4. speaker is the id of the one character who says something aloud on screen during the beat, or an empty string when nobody speaks; give a speaker only where a spoken line moves the story. A beat with a speaker shows only that character (its cast is just their id), facing the camera, in a medium shot, medium close-up or close-up; the speaker may move during the beat, as long as their face stays in frame and lit while they speak. Write a speaking beat's action as what the speaker physically does, never as speaking, and end it with the speaker still in frame: nobody else acts after the line, and when the narrative has the speaker leave, or another character act, after a line, give that a later beat with no speaker, adding that beat when the beat count allows it, and leave it out only when it does not. lines is the list of the numbers of the spoken lines above that the speaker says aloud during the beat, in order, or an empty list. Every spoken line belongs to exactly one beat, in the narrative's order: give each line to the beat whose action surrounds it in the narrative, and give a speaker to every beat with lines and to no other beat. A beat may hold two or more consecutive lines only when one character says them all and together they are at most 13 words. Give each line its own beat whenever there are at least as many target beats (3) as lines; never add a beat only to separate lines that fit together.
```

with:

```text
beats: a list of 3 to 5 objects, one per panel in order, with the keys index, arc, action, shot, camera, location, cast, speaker, lines and end_frame. index runs from 1 to the number of beats. This movie's target length is 3 beats, and like a word range it is soft: use 3 beats when the narrative fits them, and add a beat, up to 5 beats in all, only for something the narrative needs that no other beat can hold. A spoken line that cannot share a beat with the line beside it gets a beat of its own. arc is one of introduction, rising, climax, falling, resolution, in story order; the first beat is introduction, the last is resolution, and at least one beat is climax. action is one sentence of 6 to 40 words saying what the characters physically do during these 6 seconds: one continuous physical action that a camera can film, not a sequence of steps, with no on-screen text. shot is exactly one of: medium shot, medium close-up, close-up (characters speak on screen in this movie, so only these framings keep the speaker's lips readable). camera is exactly one of: slow push-in, slow pull-back, slow tracking left, slow tracking right, handheld, slow pan left, slow pan right, slow tilt up, slow tilt down, slow crane up, slow crane down, slow orbit, static. Give every beat one camera move from this list, and use static only for a deliberate hold: at most one beat in three may be static, so at most 1 in this movie. On a beat with a speaker, prefer slow push-in, slow pull-back, slow tracking left, slow tracking right or handheld, and never use a pan, a tilt, a crane or an orbit, which sweep the speaker's face out of the frame. location is the id of the place where the beat happens. cast is the list of ids of the characters on screen in the beat, at most 4. speaker is the id of the one character who says something aloud on screen during the beat, or an empty string when nobody speaks; give a speaker only where a spoken line moves the story. A beat with a speaker shows only that character (its cast is just their id), facing the camera, in a medium shot, medium close-up or close-up; the speaker may move during the beat, as long as their face stays in frame and lit while they speak. Write a speaking beat's action as what the speaker physically does, never as speaking, and end it with the speaker still in frame: nobody else acts after the line, and when the narrative has the speaker leave, or another character act, after a line, give that a later beat with no speaker, adding that beat when the beat count allows it, and leave it out only when it does not. lines is the list of the numbers of the spoken lines above that the speaker says aloud during the beat, in order, or an empty list. Every spoken line belongs to exactly one beat, in the narrative's order: give each line to the beat whose action surrounds it in the narrative, and give a speaker to every beat with lines and to no other beat. A beat may hold two or more consecutive lines only when one character says them all and together they are at most 13 words. Give each line its own beat whenever there are at least as many target beats (3) as lines; never add a beat only to separate lines that fit together. end_frame is one sentence of 8 to 30 words, in the present tense, of the frame the beat ends on: who or what is in frame, where each one is (left, centre or right; foreground or background), which way they face and how tight the shot is. It never names a camera move, the lighting, a colour or a style, has no spoken words and no double quotes, and names only characters in the beat's cast. Beat k's end frame is exactly where beat k+1 begins; write beat k+1's action so it starts from that composition. The last beat's end frame closes the story.
```


**`tests/fixtures/pinned_cast/uncast_chained_seed.txt`**

**3.60.** The fixture's plan reference (CR3). Edit `tests/fixtures/pinned_cast/uncast_chained_seed.txt`: replace this text, which occurs exactly once:

```text
Rules for this movie: keep consecutive beats at the same location unless the action itself moves the characters there, and put every character who can be seen in the opening frame in beat 1's cast.

```

with:

```text
Rules for this movie: keep consecutive beats at the same location unless the action itself moves the characters there, and put every character who can be seen in the opening frame in beat 1's cast.

FORMAT REFERENCE ONLY — never reuse its people, places, objects or words. This is the complete plan of a three-beat movie made as one continuous take, a different story from this one. It shows the format of every plan: each beat's end_frame says exactly where the beat ends, the next beat's action starts from that end frame, and the last end frame closes the story.
{"title": "The Last Morning at the Market", "logline": "At dawn an old fishmonger closes her market hall for the last time and says goodbye to forty years of work.",
 "cast": [{"id": "c1", "phrase": "the old fishmonger", "descriptor": "an old woman with a stooped build, weathered pale skin and short grey hair under a knitted cap, wearing a rubber apron over a thick wool jumper and tall rubber boots"}],
 "locations": [{"id": "l1", "setting": "The setting is a covered fish market hall in a northern harbour town at dawn, wet concrete underfoot, rows of bare zinc counters behind, under grey first light from the harbour doors."}],
 "props": [{"id": "p1", "name": "the herring crates"}, {"id": "p2", "name": "the folded cloth"}],
 "beats": [
  {"index": 1, "arc": "introduction", "action": "The old fishmonger drags a tall stack of empty herring crates across the wet market hall to the half-open shutter.", "shot": "medium shot", "camera": "slow tracking right", "location": "l1", "cast": ["c1"], "speaker": "", "end_frame": "The old fishmonger stands beside the half-open shutter at frame centre, facing left toward the hall, seen from the knees up, the empty crates at her feet."},
  {"index": 2, "arc": "climax", "action": "From the shutter, the old fishmonger turns back into the hall and walks to the zinc counter, laying her folded cloth on it.", "shot": "medium shot", "camera": "slow push-in", "location": "l1", "cast": ["c1"], "speaker": "c1", "end_frame": "The old fishmonger stands behind the zinc counter at frame centre, facing forward, her face filling the frame from chin to brow."},
  {"index": 3, "arc": "resolution", "action": "The old fishmonger lowers her forehead onto her folded hands on the cold zinc counter and closes her eyes.", "shot": "close-up", "camera": "static", "location": "l1", "cast": ["c1"], "speaker": "", "end_frame": "The old fishmonger rests her forehead on her folded hands at frame centre, eyes closed, her head and hands filling the frame in a close-up."}],
 "loras": {"global": [], "per_beat": {}, "stills": []}}

```

**3.61.** The fixture's beats line: the beat keys, the camera list, `CAMERA_SPEAKING_SENTENCE` and `END_FRAME_RULE` (CR1, CR3). Edit `tests/fixtures/pinned_cast/uncast_chained_seed.txt`: replace this text, which occurs exactly once:

```text
beats: a list of 3 to 5 objects, one per panel in order, with the keys index, arc, action, shot, camera, location, cast and speaker. index runs from 1 to the number of beats. This movie's target length is 3 beats, and like a word range it is soft: use 3 beats when the narrative fits them, and add a beat, up to 5 beats in all, only for something the narrative needs that no other beat can hold. arc is one of introduction, rising, climax, falling, resolution, in story order; the first beat is introduction, the last is resolution, and at least one beat is climax. action is one sentence of 6 to 40 words saying what the characters physically do during these 6 seconds: one continuous physical action that a camera can film, not a sequence of steps, with no on-screen text. shot is exactly one of: extreme wide shot, wide shot, medium shot, medium close-up, close-up, extreme close-up. camera is exactly one of: slow push-in, slow pull-back, tracking, handheld, slow pan left, slow pan right, slow tilt up, slow tilt down, static. Give every beat one camera move from this list, and use static only for a deliberate hold: at most one beat in three may be static, so at most 1 in this movie. On a beat with a speaker, prefer slow push-in, slow pull-back, tracking or handheld, and never use a pan or a tilt, which sweeps the speaker's face out of the frame. location is the id of the place where the beat happens. cast is the list of ids of the characters on screen in the beat, at most 4. speaker is the id of the one character who says something aloud on screen during the beat, or an empty string when nobody speaks; give a speaker only where a spoken line moves the story. A beat with a speaker shows only that character (its cast is just their id), facing the camera, in a medium shot, medium close-up or close-up; the speaker may move during the beat, as long as their face stays in frame and lit while they speak. Write a speaking beat's action as what the speaker physically does, never as speaking, and end it with the speaker still in frame: nobody else acts after the line, and when the narrative has the speaker leave, or another character act, after a line, give that a later beat with no speaker, adding that beat when the beat count allows it, and leave it out only when it does not.
```

with:

```text
beats: a list of 3 to 5 objects, one per panel in order, with the keys index, arc, action, shot, camera, location, cast, speaker and end_frame. index runs from 1 to the number of beats. This movie's target length is 3 beats, and like a word range it is soft: use 3 beats when the narrative fits them, and add a beat, up to 5 beats in all, only for something the narrative needs that no other beat can hold. arc is one of introduction, rising, climax, falling, resolution, in story order; the first beat is introduction, the last is resolution, and at least one beat is climax. action is one sentence of 6 to 40 words saying what the characters physically do during these 6 seconds: one continuous physical action that a camera can film, not a sequence of steps, with no on-screen text. shot is exactly one of: extreme wide shot, wide shot, medium shot, medium close-up, close-up, extreme close-up. camera is exactly one of: slow push-in, slow pull-back, slow tracking left, slow tracking right, handheld, slow pan left, slow pan right, slow tilt up, slow tilt down, slow crane up, slow crane down, slow orbit, static. Give every beat one camera move from this list, and use static only for a deliberate hold: at most one beat in three may be static, so at most 1 in this movie. On a beat with a speaker, prefer slow push-in, slow pull-back, slow tracking left, slow tracking right or handheld, and never use a pan, a tilt, a crane or an orbit, which sweep the speaker's face out of the frame. location is the id of the place where the beat happens. cast is the list of ids of the characters on screen in the beat, at most 4. speaker is the id of the one character who says something aloud on screen during the beat, or an empty string when nobody speaks; give a speaker only where a spoken line moves the story. A beat with a speaker shows only that character (its cast is just their id), facing the camera, in a medium shot, medium close-up or close-up; the speaker may move during the beat, as long as their face stays in frame and lit while they speak. Write a speaking beat's action as what the speaker physically does, never as speaking, and end it with the speaker still in frame: nobody else acts after the line, and when the narrative has the speaker leave, or another character act, after a line, give that a later beat with no speaker, adding that beat when the beat count allows it, and leave it out only when it does not. end_frame is one sentence of 8 to 30 words, in the present tense, of the frame the beat ends on: who or what is in frame, where each one is (left, centre or right; foreground or background), which way they face and how tight the shot is. It never names a camera move, the lighting, a colour or a style, has no spoken words and no double quotes, and names only characters in the beat's cast. Beat k's end frame is exactly where beat k+1 begins; write beat k+1's action so it starts from that composition. The last beat's end frame closes the story.
```


**`tests/fixtures/pinned_cast/uncast_shots_lines.txt`**

**3.62.** The fixture's beats line: the camera list and `CAMERA_SPEAKING_SENTENCE` (CR1). Edit `tests/fixtures/pinned_cast/uncast_shots_lines.txt`: replace this text, which occurs exactly once:

```text
beats: a list of 4 to 6 objects, one per panel in order, with the keys index, arc, action, shot, camera, location, cast, speaker and lines. index runs from 1 to the number of beats. This movie's target length is 4 beats, and like a word range it is soft: use 4 beats when the narrative fits them, and add a beat, up to 6 beats in all, only for something the narrative needs that no other beat can hold. A spoken line that cannot share a beat with the line beside it gets a beat of its own. arc is one of introduction, rising, climax, falling, resolution, in story order; the first beat is introduction, the last is resolution, and at least one beat is climax. action is one sentence of 6 to 40 words saying what the characters physically do during these 6 seconds: one continuous physical action that a camera can film, not a sequence of steps, with no on-screen text. shot is exactly one of: medium shot, medium close-up, close-up (characters speak on screen in this movie, so only these framings keep the speaker's lips readable). camera is exactly one of: slow push-in, slow pull-back, tracking, handheld, slow pan left, slow pan right, slow tilt up, slow tilt down, static. Give every beat one camera move from this list, and use static only for a deliberate hold: at most one beat in three may be static, so at most 2 in this movie. On a beat with a speaker, prefer slow push-in, slow pull-back, tracking or handheld, and never use a pan or a tilt, which sweeps the speaker's face out of the frame. location is the id of the place where the beat happens. cast is the list of ids of the characters on screen in the beat, at most 2. speaker is the id of the one character who says something aloud on screen during the beat, or an empty string when nobody speaks; give a speaker only where a spoken line moves the story. A beat with a speaker shows only that character (its cast is just their id), facing the camera, in a medium shot, medium close-up or close-up; the speaker may move during the beat, as long as their face stays in frame and lit while they speak. Write a speaking beat's action as what the speaker physically does, never as speaking, and end it with the speaker still in frame: nobody else acts after the line, and when the narrative has the speaker leave, or another character act, after a line, give that a later beat with no speaker, adding that beat when the beat count allows it, and leave it out only when it does not. lines is the list of the numbers of the spoken lines above that the speaker says aloud during the beat, in order, or an empty list. Every spoken line belongs to exactly one beat, in the narrative's order: give each line to the beat whose action surrounds it in the narrative, and give a speaker to every beat with lines and to no other beat. A beat may hold two or more consecutive lines only when one character says them all and together they are at most 13 words. Give each line its own beat whenever there are at least as many target beats (4) as lines; never add a beat only to separate lines that fit together.
```

with:

```text
beats: a list of 4 to 6 objects, one per panel in order, with the keys index, arc, action, shot, camera, location, cast, speaker and lines. index runs from 1 to the number of beats. This movie's target length is 4 beats, and like a word range it is soft: use 4 beats when the narrative fits them, and add a beat, up to 6 beats in all, only for something the narrative needs that no other beat can hold. A spoken line that cannot share a beat with the line beside it gets a beat of its own. arc is one of introduction, rising, climax, falling, resolution, in story order; the first beat is introduction, the last is resolution, and at least one beat is climax. action is one sentence of 6 to 40 words saying what the characters physically do during these 6 seconds: one continuous physical action that a camera can film, not a sequence of steps, with no on-screen text. shot is exactly one of: medium shot, medium close-up, close-up (characters speak on screen in this movie, so only these framings keep the speaker's lips readable). camera is exactly one of: slow push-in, slow pull-back, slow tracking left, slow tracking right, handheld, slow pan left, slow pan right, slow tilt up, slow tilt down, slow crane up, slow crane down, slow orbit, static. Give every beat one camera move from this list, and use static only for a deliberate hold: at most one beat in three may be static, so at most 2 in this movie. On a beat with a speaker, prefer slow push-in, slow pull-back, slow tracking left, slow tracking right or handheld, and never use a pan, a tilt, a crane or an orbit, which sweep the speaker's face out of the frame. location is the id of the place where the beat happens. cast is the list of ids of the characters on screen in the beat, at most 2. speaker is the id of the one character who says something aloud on screen during the beat, or an empty string when nobody speaks; give a speaker only where a spoken line moves the story. A beat with a speaker shows only that character (its cast is just their id), facing the camera, in a medium shot, medium close-up or close-up; the speaker may move during the beat, as long as their face stays in frame and lit while they speak. Write a speaking beat's action as what the speaker physically does, never as speaking, and end it with the speaker still in frame: nobody else acts after the line, and when the narrative has the speaker leave, or another character act, after a line, give that a later beat with no speaker, adding that beat when the beat count allows it, and leave it out only when it does not. lines is the list of the numbers of the spoken lines above that the speaker says aloud during the beat, in order, or an empty list. Every spoken line belongs to exactly one beat, in the narrative's order: give each line to the beat whose action surrounds it in the narrative, and give a speaker to every beat with lines and to no other beat. A beat may hold two or more consecutive lines only when one character says them all and together they are at most 13 words. Give each line its own beat whenever there are at least as many target beats (4) as lines; never add a beat only to separate lines that fit together.
```

- [ ] **Step 4: Check the re-baseline.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
SHA=$(git log -1 --format=%H -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py)
grep -c "(location library), then to $SHA (chained end frames)." tests/test_movie_ui_builder.py
grep -c "    BASELINE = \"$SHA\"" tests/test_movie_ui_builder.py
git diff --numstat -- tests/
git status --short -- tests/fixtures/writer_pacing | wc -l
```

Expected, in order:
- `1` and `1`;
- these 16 numstat lines, in `git`'s path order:
  - `12	1	qwen-agent-workspace/tests/fixtures/location/plan_prompt_chained.txt`
  - `12	1	qwen-agent-workspace/tests/fixtures/location/plan_prompt_chained_cast.txt`
  - `1	1	qwen-agent-workspace/tests/fixtures/location/plan_prompt_shots.txt`
  - `12	1	qwen-agent-workspace/tests/fixtures/pinned_cast/uncast_chained_lines.txt`
  - `12	1	qwen-agent-workspace/tests/fixtures/pinned_cast/uncast_chained_seed.txt`
  - `1	1	qwen-agent-workspace/tests/fixtures/pinned_cast/uncast_shots_lines.txt`
  - `6	3	qwen-agent-workspace/tests/test_dialogue.py`
  - `1	1	qwen-agent-workspace/tests/test_location_ui.py`
  - `2	2	qwen-agent-workspace/tests/test_movie_ui_builder.py`
  - `1	1	qwen-agent-workspace/tests/test_movie_ui_http.py`
  - `13	11	qwen-agent-workspace/tests/test_narrative_fidelity.py`
  - `1	1	qwen-agent-workspace/tests/test_pinned_cast.py`
  - `68	50	qwen-agent-workspace/tests/test_shot_format.py`
  - `3	2	qwen-agent-workspace/tests/test_soft_panel_count.py`
  - `2	2	qwen-agent-workspace/tests/test_speaker_attribution.py`
  - `37	21	qwen-agent-workspace/tests/test_story_engine.py`
- `0` (no recorded writer_pacing artifact changed).

Then the re-baselined tests:

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_story_engine.py::test_pacing_camera_sentences_classify_as_before \
  tests/test_story_engine.py::test_rs4_constants \
  tests/test_story_engine.py::test_rst14_plan_checks \
  tests/test_story_engine.py::test_rst26b_critic_retry_and_code_only_round \
  tests/test_story_engine.py::test_rst33_stop_passed \
  tests/test_story_engine.py::test_rst39_outputs_and_layout \
  tests/test_story_engine.py::test_rst47_robust_dry_run \
  tests/test_story_engine.py::test_rst51_e2e_chained \
  tests/test_story_engine.py::test_rst55b_p13_forces_plan_call_2 \
  tests/test_story_engine.py::test_rst57_reserved_sentence_in_the_plan_prompt \
  tests/test_story_engine.py::test_rst8_plan_prompt_matrix \
  tests/test_shot_format.py::test_review_focus_3_an_end_frame_in_the_references_words_falls_back \
  tests/test_shot_format.py::test_sft12_reference_copies \
  tests/test_shot_format.py::test_sft13_the_composition_and_the_reference \
  tests/test_shot_format.py::test_sft1a_planner_constants \
  tests/test_shot_format.py::test_sft1b_writer_constants \
  tests/test_shot_format.py::test_sft1c_check_constants \
  tests/test_shot_format.py::test_sft21_the_reference_adds_exactly_its_own_length \
  tests/test_shot_format.py::test_sft2_the_plan_prompt \
  tests/test_dialogue.py::test_dlg12_plan_prompt_speaker_rule \
  tests/test_dialogue.py::test_dlg21_an_advisory_only_round_0_passes_untouched \
  tests/test_narrative_fidelity.py::test_nf12_the_plan_prompt \
  tests/test_narrative_fidelity.py::test_nf14_the_plan_retry_gate \
  tests/test_narrative_fidelity.py::test_nf16_the_speaking_coercion_table \
  tests/test_narrative_fidelity.py::test_nf32_no_narration_keeps_the_movie_silent \
  tests/test_narrative_fidelity.py::test_nf33_default_narration_with_the_fixed_plan \
  tests/test_pinned_cast.py::test_pt16_two_pinned_chained_every_line_spoken_by_c1 \
  tests/test_pinned_cast.py::test_pt2_fixed_cast_block_and_uncast_byte_identity \
  tests/test_location_story.py::test_ls1_without_locations_plan_prompts_and_plans_are_byte_identical \
  tests/test_soft_panel_count.py::test_spt4_the_plan_prompt \
  tests/test_soft_panel_count.py::test_spt8_e2e_one_beat_added \
  tests/test_speaker_attribution.py::test_sat9_plan_prompt \
  tests/test_movie_ui_http.py::test_mut18_every_api_route_needs_the_token \
  tests/test_location_ui.py::test_lu1_the_location_routes_need_the_token \
  tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged 2>&1 | tail -1
```

Expected: `35 passed` (before Step 3 the same command gives `35 failed`). If a value differs, fix the Edit, not this command.

- [ ] **Step 5: Commit (the ONE test-only commit; spec 10 step 3, commit 2).**

The body has one paragraph per changed file, naming its tests and codes (spec Section 7 rule).

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
git add tests/test_story_engine.py tests/test_shot_format.py tests/test_dialogue.py tests/test_narrative_fidelity.py tests/test_pinned_cast.py tests/test_soft_panel_count.py tests/test_speaker_attribution.py tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_builder.py tests/fixtures/location/plan_prompt_chained.txt tests/fixtures/location/plan_prompt_chained_cast.txt tests/fixtures/location/plan_prompt_shots.txt tests/fixtures/pinned_cast/uncast_chained_lines.txt tests/fixtures/pinned_cast/uncast_chained_seed.txt tests/fixtures/pinned_cast/uncast_shots_lines.txt
git diff --cached --name-only    # expected: only those 16 paths
git commit -m "test: re-baseline the existing tests to chained end frames (spec Section 7, CR1-CR7)" \
  -m "tests/test_story_engine.py: test_rs4_constants, test_rst14_plan_checks and test_pacing_camera_sentences_classify_as_before (CR1: the 14 camera keys and sentences); test_rst8_plan_prompt_matrix, test_rst57_reserved_sentence_in_the_plan_prompt and test_rst47_robust_dry_run (CR3: the plan reference holds braces); test_rst26b_critic_retry_and_code_only_round, test_rst33_stop_passed, test_rst39_outputs_and_layout, test_rst51_e2e_chained and test_rst55b_p13_forces_plan_call_2 (CR5: the second plan call, its stdout and plan_reply_2.txt)." \
  -m "tests/test_shot_format.py: test_sft1a_planner_constants (CR1, CR4: RECHECK_IDS_3970E96 renamed RECHECK_IDS_CE), test_sft1b_writer_constants (CR1, CR2), test_sft2_the_plan_prompt (CR1), test_sft1c_check_constants (CR2, CR4), test_sft12_reference_copies (CR2: a CE11 segment row and the N22 message; CR3: the corpus guard removes the plan reference that the re-baselined prompt fixtures quote), test_sft13_the_composition_and_the_reference and REF_PARTS (CR2), test_sft21_the_reference_adds_exactly_its_own_length (CR2) and test_review_focus_3_an_end_frame_in_the_references_words_falls_back (CR2)." \
  -m "tests/test_dialogue.py: test_dlg12_plan_prompt_speaker_rule (CR3) and test_dlg21_an_advisory_only_round_0_passes_untouched, chained case (CR5)." \
  -m "tests/test_narrative_fidelity.py: test_nf16_the_speaking_coercion_table (CR1), test_nf12_the_plan_prompt (CR3), and test_nf14_the_plan_retry_gate, test_nf32_no_narration_keeps_the_movie_silent and test_nf33_default_narration_with_the_fixed_plan (CR5)." \
  -m "tests/test_pinned_cast.py: test_pt16_two_pinned_chained_every_line_spoken_by_c1 (CR5)." \
  -m "tests/test_soft_panel_count.py: test_spt4_the_plan_prompt (CR3) and test_spt8_e2e_one_beat_added (CR5)." \
  -m "tests/test_speaker_attribution.py: test_sat9_plan_prompt (CR3)." \
  -m "tests/test_movie_ui_http.py: test_mut18_every_api_route_needs_the_token (CR7: 55 routes)." \
  -m "tests/test_location_ui.py: test_lu1_the_location_routes_need_the_token (CR7: 55 routes)." \
  -m "tests/test_movie_ui_builder.py: test_mut26_pipeline_files_are_unchanged (CR6: BASELINE is the last pipeline commit of this branch)." \
  -m "tests/fixtures/location/plan_prompt_chained.txt: test_ls1_without_locations_plan_prompts_and_plans_are_byte_identical (CR1, CR3)." \
  -m "tests/fixtures/location/plan_prompt_chained_cast.txt: test_ls1_without_locations_plan_prompts_and_plans_are_byte_identical (CR1, CR3)." \
  -m "tests/fixtures/location/plan_prompt_shots.txt: test_ls1_without_locations_plan_prompts_and_plans_are_byte_identical (CR1)." \
  -m "tests/fixtures/pinned_cast/uncast_chained_lines.txt: test_pt2_fixed_cast_block_and_uncast_byte_identity (CR1, CR3)." \
  -m "tests/fixtures/pinned_cast/uncast_chained_seed.txt: test_pt2_fixed_cast_block_and_uncast_byte_identity (CR1, CR3)." \
  -m "tests/fixtures/pinned_cast/uncast_shots_lines.txt: test_pt2_fixed_cast_block_and_uncast_byte_identity (CR1)." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: CK7: the full suite against the baseline (about 18 minutes).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/chain-baseline
cd $S/chain-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/final-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt; tail -1 $D/final-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/final-pytest.txt $D/expected-failures.txt 7
diff <(grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt | sort) <(grep -E '^(FAILED|ERROR)' $D/final-pytest.txt | sort) && echo "same failures, same messages"
diff <(grep -E '^PASSED' $D/baseline-pytest.txt | sort) <(grep -E '^PASSED' $D/final-pytest.txt | sort) | grep '^<' || echo "no lost pass"
grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $D/final-pytest.txt
diff <(python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1) $D/baseline-offline.txt && echo "offline unchanged"
```

Expected:
- the final summary is the baseline's with the pass count higher by exactly 71, the new cases (66 CT cases and 5 Review Focus pins; Plan ruling R20);
- `lost 0 (listed 0, unexpected 0); new tests 71, not passing 0` and `GATE PASS`;
- `same failures, same messages` and `no lost pass` (CK7);
- `1` (`test_mut26` passes at its new `BASELINE`);
- `offline unchanged`.

If a timing-sensitive test failed in one run only, rerun it alone and record both results. Any other difference: stop and report.

- [ ] **Step 7: CK1-CK6 and the isolation checks.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/chain-wt/qwen-agent-workspace
F=tests/test_chained_end_frames.py
python3 -B -m pytest -q -p no:cacheprovider $F::test_ct5_p22_end_frame_presence_and_length $F::test_ct8_a_plan_without_end_frames_is_asked_again $F::test_ct8_two_plans_without_end_frames_drop_them $F::test_ct8_a_copied_action_after_the_last_call_is_fatal $F::test_ct8_a_copied_end_frame_after_the_last_call_is_dropped $F::test_ct8_a_plan_with_end_frames_makes_one_call $F::test_ct8_a_fatal_call_2_falls_back_to_a_usable_call_1 $F::test_ct8_a_timeout_before_call_2_keeps_a_usable_call_1 $F::test_ct16_an_added_beat_needs_its_own_end_frame 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider $F::test_ct10_n23_detection_rows $F::test_ct11_one_re_ask_then_the_landing_reply $F::test_ct11_a_writer_that_misses_twice_is_kept_with_an_advisory $F::test_ct11_no_re_ask_without_a_call_left $F::test_ct11_writers_that_land_get_no_n23 $F::test_ct11_a_re_ask_that_adds_a_hard_problem_keeps_reply_1 $F::test_ct11_a_re_ask_with_an_equal_count_is_accepted $F::test_ct11_a_re_ask_with_more_format_and_n23_problems_is_rejected 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider $F::test_ct15_old_stories_recheck_as_before tests/test_ltx_story_manifest_chain.py tests/test_judge_clips.py tests/test_character_lib.py tests/test_ltx_mlx_render.py tests/test_vlm_lifecycle.py::test_vl1_job_vlm tests/test_location_ui.py::test_lu9_job_vlm_policy tests/test_location_ui.py::test_lu13_the_static_page tests/test_dialogue.py::test_dlg15_assembly_goldens_and_dedupe tests/test_story_engine.py::test_rst16_panel_prompt tests/test_story_engine.py::test_rst18_assembly_goldens tests/test_writer_pacing.py 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider $F::test_ct12_a_standing_still_end_frame_survives_the_repair $F::test_ct12_stays_still_and_pushes_in_is_still_mixed $F::test_ct12_static_holding_and_the_head_rule 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider $F::test_ct13_writer_double_quotes_become_apostrophes $F::test_ct13_the_manifest_keeps_only_the_spoken_line_quoted $F::test_ct13_the_fixture_parts_assemble_with_no_double_quote 2>&1 | tail -1
python3 -B -m pytest -q -p no:cacheprovider tests/test_seam_report.py 2>&1 | tail -1
git diff --stat d30c40f..HEAD -- character_lib.py bin/ltx-story-manifest bin/ltx-mlx-render bin/judge-clips bin/ltx-movie bin/story-server | tail -1
git diff d30c40f..HEAD -- movie_ui_lib.py movie_ui_batch.py | grep -c "DEFAULT_FIELDS"
git diff --name-only d30c40f..HEAD
git diff d30c40f..HEAD -- tests/test_chained_end_frames.py tests/test_seam_report.py tests/test_movie_ui_seams.py | grep -E '^\+' | grep -nE "8178|urlopen|import requests|zshenv|fleet\.env|macstudio|\.local/share" || echo "no 8178, real HTTP client, private host or real HOME path in the new tests"
git diff d30c40f..HEAD -- bin/seam-report | grep -E '^\+(import|from) '
```

Expected, in order:
- CK1: `9 passed`;
- CK2: `8 passed`;
- CK3: `202 passed` (CT15 and the spec's "must pass unchanged" set; the offline script was checked in Step 6);
- CK4: `3 passed`;
- CK5: `3 passed`;
- CK6: `18 passed`;
- no output from the `--stat` (spec 0.3: those files are not changed);
- `0` (no `DEFAULT_FIELDS` change; [BF] BT1 holds);
- the changed paths are exactly the 2 docs (the spec and this plan) plus `bin/seam-report`, `movie_ui_lib.py`, `movie_ui_server.py`, `static/movie-ui/app.css`, `static/movie-ui/app.js`, `static/movie-ui/index.html`, `story_engine.py`, the six fixtures of Task 7, `tests/test_chained_end_frames.py`, `tests/test_dialogue.py`, `tests/test_location_ui.py`, `tests/test_movie_ui_builder.py`, `tests/test_movie_ui_http.py`, `tests/test_movie_ui_seams.py`, `tests/test_narrative_fidelity.py`, `tests/test_pinned_cast.py`, `tests/test_seam_report.py`, `tests/test_shot_format.py`, `tests/test_soft_panel_count.py`, `tests/test_speaker_attribution.py` and `tests/test_story_engine.py`, each with the `qwen-agent-workspace/` prefix (28 paths);
- `no 8178, real HTTP client, private host or real HOME path in the new tests`. The new tests name `8177` only as the default port value they assert and in `8177 + 1`, the pinned `EMBED_PORT`, so the literal never appears; every HTTP connection in them is a monkeypatched fake;
- exactly twelve import lines: `+import argparse`, `+import base64`, `+import http.client`, `+import importlib.machinery`, `+import json`, `+import os`, `+import re`, `+import shutil`, `+import subprocess`, `+import sys`, `+import tempfile`, `+import time` (CE13, CT30).

- [ ] **Step 8: Hand-off (controller; not an executor step).**
  - Report the branch `chain-endframes` and its 11 new commits (6 task commits, the Task 2, Task 3, Task 5 and Task 6 fix commits and the re-baseline), with CK1-CK7.
  - Before any push, run the spec's secret scan (spec 10 step 5) and review every hit by hand.
  - Push, the merge and the live A/B are separate steps that need the user's approval.

---

## Post-merge: the live A/B (coordinator only; spec 10 step 7; not a task and not a merge gate)

The coordinator runs this after the merge, never an implementer:
- It renders six movies and loads the story server, so it needs the user's go-ahead.
- This Mac only, never macstudio. Never touch `:8178`. Never read `~/.zshenv` or `fleet.env`. Never two renders at once, and never the story server during a render.

Steps (spec 10 step 7, unchanged):
- [ ] Arm B: `bin/ltx-movie … --story-id ce1-<name> --force-story --no-review` for `ch3-a`, `ch3-b` and `hk2`.
- [ ] Arm A: copy each `ce1-<name>` to `ce0-<name>` without `clips/`, `movie.mp4` and `manifest.json`; strip the camera clauses with `$R/strip_clauses.py`; render with `--no-review`.
- [ ] Start `bin/story-server mlx-vision`, run `bin/seam-report` on all six stories, then stop it.
- [ ] Report the mean score B vs A, the missed counts, plan calls, P22 drops and N23 advisories, and `$R/ab.html`. The expectation (not a gate) is mean B > mean A.

---

## Coverage

### Spec coverage: requirement → task

| Requirement | Task (step) |
|---|---|
| CE1 camera keys, sentences, `PLAN_CAMERA_KEYS`, speaking sentence and cameras, move words, writer forms | 1 (3.1-3.5, 3.8, 3.9) |
| CE2 `END_CLAUSE_RE`, `camera_head`, `end_clause`, head-only `_mixed_camera`/`_names_camera` | 1 (3.6, 3.7) |
| CE3 `normalize_plan` keeps `end_frame` | 2 (3.6) |
| CE4 template, `END_FRAME_RULE`, `beat_keys`, the two fragments | 2 (3.1-3.4) |
| CE5 the plan reference and its pins | 2 (3.9; Step 4 pin check) |
| CE6 `_named_ids`, P22, P23 (in `plan_checks`), P24, `drop_end_frames` | 2 (3.5, 3.7, 3.8) |
| CE7 `plan_round` problems, fatal P24, the drop and its warning | 2 (3.10-3.12) |
| CE8 opens-on and ends-on lines | 4 (3.4, 3.5) |
| CE9 N23 functions, advisory, round-0 re-ask | 3 (3.1-3.3, 3.5) |
| CE10 `reserve_quotes` in `panel_fields` | 1 (3.10-3.12) |
| CE11 `FORMAT_REFERENCE`, terms, segments, `reference_copies` | 4 (3.1-3.3) |
| CE12 `GENERATION_CHECKS`, `RECHECK_IDS` | 3 (3.4, 3.6) |
| CE13 `bin/seam-report` | 5 (3.1, 3.2) |
| CE14 `job_vlm`, `seams_argv`, `plan_has_end_frames`, the route, `_create_seams_job`, `create_compose_job(seams=)`, `_h_job_create`, `_h_story_seams`, `_h_story` keys | 6 (3.1-3.7) |
| CE15 `index.html`, `app.js`, `app.css` | 6 (3.8-3.16) |
| D1-D12 | D1, D2, D6, D8 1; D3, D4, D9 (plan side) 2; D5, D9 (writer side) 4; D7, D10 3; D11 5; D12 6 |
| Section 5 messages | 2 (P22, P23, P24, drop), 3 (N23), 5 (seam-report), 6 (HTTP and page texts); each pinned by its CT |
| Section 7 re-baseline (CR1-CR7) | 7 (Steps 2-5) |
| Section 10 rollout | Before Task 1 (snapshot, baseline); 1-6 (feature commits); 7 (review, test-only commit, CK7); Post-merge (A/B) |
| G1-G6 | G1 1-4; G2 5; G3, G4 6; G5 1-6; G6 7 |

### Test IDs and their owning task (each is owned by exactly one task)

| IDs | Task | File | Cases |
|---|---|---|---|
| CT1 (camera part), CT12, CT13, CT29 | 1 | `tests/test_chained_end_frames.py` | 8 (CT12 3, CT13 3) |
| CT1 (planner part), CT2-CT8, CT16 | 2 | `tests/test_chained_end_frames.py` | 17 (CT2 2, CT3 2, CT8 7) |
| CT1 (N23 part), CT10, CT11, CT15, Review Focus 3 | 3 | `tests/test_chained_end_frames.py` | 11 (CT11 7) |
| CT1 (writer part), CT9, CT14 | 4 | `tests/test_chained_end_frames.py` | 4 (CT14 2) |
| CT1 (compile part) | 5 | `tests/test_chained_end_frames.py` | 1 |
| CT17-CT22, CT30, Review Focus 1, 2 | 5 | `tests/test_seam_report.py` | 18 (CT17 2, CT18 2, CT19 3, CT20 5, CT22 2) |
| CT23-CT28, Review Focus 4, 5 | 6 | `tests/test_movie_ui_seams.py` | 12 (CT25 5) |
| the Section 7 re-baselines | 7 | the 16 files of Task 7 | (existing tests) |

Totals: 71 new cases, of which 66 are CT cases and 5 are Review Focus pins. Cumulative new cases after each task: 8, 25, 36, 40, 59, 71.

### KPI → task

| KPI | Measured by |
|---|---|
| CK1 | Task 2 (CT5, CT8, CT16; `_assert_p22_clean` checks every beat of every saved plan); Task 7 Step 7 |
| CK2 | Task 3 (CT10, CT11); Task 7 Step 7 |
| CK3 | Task 3 (CT15); every Step 4 gate (the must-stay-green set and the offline line); Task 7 Steps 6, 7 |
| CK4 | Task 1 (CT12); Task 7 Step 7 |
| CK5 | Task 1 (CT13); Task 7 Step 7 |
| CK6 | Task 5 (CT17-CT22); Task 7 Step 7 |
| CK7 | Before Task 1 Step 3 (baseline); every Step 4 gate; Task 7 Steps 5, 6 |

### Self-review

- **Spec coverage.** Every requirement CE1-CE15 maps to a task in the table above. Every test CT1-CT30 has real test code in its owning task, and every KPI CK1-CK7 has a measuring step. G1-G6 and Section 7 each have a step.
- **Placeholders.** The only symbolic values are `$S`, `$D`, `$F`, `N` (the gate block) and **SHA** (Task 7 Step 2), each defined where it is used. No step says "add error handling", "TBD" or "similar to Task N". Every Edit names its old text, which occurs exactly once at its turn, with or without its last newline (checked by replay).
- **Type and name consistency.** These names appear with the same signature in every task that uses them:
  - `camera_head(sentence)`, `end_clause(sentence)`, `reserve_quotes(text)`, `_named_ids(words, mentions)`;
  - `plan_end_frame_problems(ctx, plan)`, `end_frame_advisories(ctx, lib, plan)`, `plan_copy_problems(ctx, plan, end_frames=True)`, `drop_end_frames(plan)`, `plan_reference(lines)`;
  - `end_frame_detail(lib, plan, k, text, phrases)`, `end_frame_landing_problems(ctx, plan, part, k)`;
  - `seams_argv(ws_real, story_id, py=sys.executable)`, `plan_has_end_frames(plan)`, `_create_seams_job(state, real, story_id)`, `create_compose_job(server, fields, seams=False)`;
  - the test helpers `ef_plan(n, mode)`, `ref_ctx(ws, **kw)`, `_e2e(ws, tmp_path, monkeypatch, plans, n=3, panel=None, **ctx_kw)` and `REF_MOTIONS`.
- **Review Focus.** Five inputs, each with a pinning test in its owning task (Tasks 5, 5, 3, 6 and 6).

## Plan rulings (where the spec's text and its own tests, or the existing tests, cannot both hold, or the spec needs a reading)

**[defect]** rulings change behaviour or a test from what the spec literally writes. The controller should confirm R13 before Task 4 starts. **[reading]** rulings fill a detail the spec leaves open.

1. **R1 [reading]: seven tasks and one commit per task.** Spec 10 step 3's single feature commit becomes six task commits, as in the prior plans, followed by the ONE test-only commit. The design review comes before the test-only commit (Task 7 Step 1).
2. **R2 [reading]: the task order.**
   - CE10 (`_DOUBLE_QUOTES`, `reserve_quotes`) is in Task 1, because P23 (Task 2) reads `_DOUBLE_QUOTES` at call time.
   - CE9/CE12 (Task 3) come before CE8/CE11 (Task 4), because CT14 checks the new reference's Motions with `end_frame_detail`.
3. **R3 [defect]: CT13's fixture scan covers two parts.json files, not "the four hockey fixtures".**
   - Only `tests/fixtures/writer_pacing/hockey-1x241-f` and `hockey-2x145-f` have a sibling `plan.json`.
   - The two `tests/fixtures/narrative_fidelity/hockey-*` dirs hold a `parts.json` but no `plan.json`, so the spec's own rule ("with a sibling chained or shots plan.json") selects two.
   - The test asserts exactly those two names.
4. **R4 [defect]: `ref_ctx(ws, **kw)` lets `kw` replace its defaults.** The spec writes `make_ctx(..., narrative=REF_NARRATIVE, ..., **kw)`, which raises `TypeError` for CT2's own call `ref_ctx(ws, narrative="A courier delivers a letter.")`. So the helper builds a dict of defaults and updates it with `kw`.
5. **R5 [defect]: CT28's "its log's last line".** The runner writes `[movie-ui] exit 0 (done)` to `log.txt` after the child exits (`movie_ui_lib.run_job`). So CT28 asserts that the last line the seams job printed is `seam-report: no clips to check in <clips>`, and that the log's last line is `[movie-ui] exit 0 (done)`.
6. **R6 [reading]: CE15's JS blocks are indented to where they sit.** The spec's blocks are list-indented. In `app.js` the Run all handler and the Check seams handler sit 4 spaces in (inside `setupCompose`/`setupStories`), and `showSeams` sits at the 2-space function level. The text is otherwise the spec's.
7. **R7 [reading]: movie-UI placements the spec leaves open.**
   - `"seams"` is the last item of `job_vlm`'s first tuple.
   - `_create_seams_job` sits right before `create_compose_job`, `_h_story_seams` right after `_h_story_save`, and its registration right after `h_story_save`'s.
   - `_h_story`'s `end_frames` and `seams` are its last two keys.
   - The `.seam-missed` rule is appended at the end of `app.css`, with a one-line comment.
8. **R8 [reading]: `bin/seam-report` details the spec leaves open.**
   - The `SeamError` details are `<tool> exited N: <its last stderr line>`, `<tool> did not run (<exception class>)`, `ffprobe gave no frame count`, `the clip has no frames` and `ffmpeg wrote no frame`.
   - A panel whose clip cannot be read keeps `source: "clip"` and its `frame` path, with verdict `no clip`.
   - One temporary directory is made per run, after the probe, and removed in a `finally`.
   - The `--port` default is read when the parser is built.
   - The `ok` stdout line never lists `missing`, and the "Planned end frames" lines are not table cells, so they are not escaped.
   - A `plan.json` that cannot be read or decoded is "not a plan.json".
9. **R9 [reading]: CT1's compile check uses `compile()` in a subprocess per Python** (as SFT1 does), so no `.pyc` is written into `WS`. `py_compile` would write `bin/__pycache__/`.
10. **R10 [reading]: CT11's E2E shapes.** `EF_PLAN(2)` keeps static (panel 1) and tracking (panel 2) after P18 (`max_static(2) == 1`). A landing reply appends that camera's `CAMERA_WRITER_FORMS` shape, with the end frame lower-cased and without its full stop.
11. **R11 [reading]: CT15 re-checks two old stories.** These are the copied `hockey-2x145-f` fixture and a synthetic chained 3-panel courier story. "The same hard list" is `story_checks.json`'s `hard`, because `recheck` returns only the advisories.
12. **R12 [reading]: the expected-failure list is measured, not read.**
    - Four tests that spec Section 7 names do not change, so they get no edit: `test_rst10_plan_retry_and_fatal_plan`, `test_rst37_budgets_and_the_wall_clock`, `test_nf28*` and `test_nf29*`.
    - Eight tests it does not name fail for a listed code:
      - `test_rst26b` and `test_rst33` (CR5: the second plan call);
      - `test_rst47` (CR3: the plan reference's braces in the dry run);
      - `test_dlg12`, `test_nf12`, `test_spt4` and `test_sat9` (CR3: `END_FRAME_RULE` follows the speaker or lines rule on the beats line, and the beat keys gain `end_frame`);
      - `test_nf14` (CR5).
    - Every failure has a code, so none is an implementation defect.
13. **R13 [defect]: the corpus guards strip the verbatim plan reference.**
    - Spec CR3 re-baselines six plan-prompt fixtures. Their chained prompts now quote `PLAN_REFERENCE` whole.
    - CT14's corpus guard and the existing SFT12 corpus loop ("no ... run ... in any file under `tests/fixtures/`") would then fail on the reference's own words.
    - Both guards remove `plan_reference(True)` and `plan_reference(False)` from each file's text before scanning. They still fail on any copy outside the quoted reference.
14. **R14 [reading]: SFT12's ice-trays row and the shot-format Review Focus 3 use CE11 segment words** (CR2).
    - The old texts ("looks up from the empty ice trays", "her face fills the frame from chin to brow") are no longer segments: D9 drops end-frame clauses from N22.
    - The new texts ("lays the folded cloth beside the empty ice trays") keep each test's point.
15. **R15 [reading]: the fixtures are re-baselined as 10 whole-line Edit hunks.** The house rule forbids rewriting a tracked file by script. Each chained fixture gets two hunks (its beats line, which holds the beat keys, the camera list, `CAMERA_SPEAKING_SENTENCE` and `END_FRAME_RULE`; and the plan reference after the chained mode rules), and each shots fixture one (its beats line). Every old text ends with a newline, so it works with or without it. Applied in order, the hunks give exactly the new `build_plan_prompt` output (checked by replay).
16. **R16 [reading]: the snapshot is taken from the worktree**, named as the spec names it (`$S/snapshot-pre-chained-end-frames.tgz`). The spec's command archives the main checkout, which the house rules forbid touching; the tree is the same.
17. **R17 [reading]: `test_mut26`'s `BASELINE` is the last commit that touched a `PIPELINE_FILES` entry**, which is Task 4's (`story_engine.py`), unless a review fix touches it. `bin/seam-report` is not in `PIPELINE_FILES`.
18. **R18 [reading]: CT13's manifest story uses the default narration (True).** Panel 2 speaks and panel 1 narrates. With `narration="speech"` panel 1 would have neither Narration nor Dialogue, and `bin/ltx-story-manifest`'s proportional pace refuses that.
19. **R19 [reading]: some tests pin more than the spec's minimum rows.** For example:
    - CT18 checks four bad IDs and the `--port` default;
    - CT22 checks `vlm_models`' five failure answers;
    - CT24 checks that a finished seams job no longer blocks a new one, and that shots and plan-less stories are refused;
    - CT25 checks that `check_seams: 1` is not `true`.
    None weakens a spec assertion.
20. **R20 [reading]: CK7's count is the baseline plus the 71 new cases,** 66 CT cases and the 5 Review Focus pins that the plan format requires.
21. **R21 [reading]: `END_FRAMES_DROPPED`'s N counts every plan call made,** including a call 2 that got no envelope, as the spec's `len([c for c in self.doc["calls"] if c["stage"] == "plan"])` does.
22. **R22 [reading]: two values are wrapped at 100 columns.** `SPEAKING_CAMERAS` and the `_mixed_camera` docstring's added sentence keep the spec's exact values.

## Questions for controller

1. **Q1 (R13).** Should the two corpus guards (CT14 and SFT12) skip the plan reference that the re-baselined prompt fixtures quote verbatim? Recommended: yes. Without it, CR3's fixture re-baseline and the corpus guards cannot both hold. Any other copy still fails.
2. **Q2 (R5).** Should CT28 assert the seams job's own last line, followed by the runner's `[movie-ui] exit 0 (done)`? Recommended: yes. The runner always appends that line.
3. **Q3 (R3).** Should CT13's fixture scan cover the two `parts.json` files that have a sibling `plan.json`? Recommended: yes. Giving the narrative_fidelity fixtures a `plan.json` would add fixture files the spec never mentions.
4. **Q4 (R12).** Should the test-only commit re-baseline the measured list, including the eight tests the spec did not name, each with its CR code? Recommended: yes. Spec Section 7 says the implementer confirms each by running the suite, and each failure has a code.

## Spec defects found (for the spec author)

1. CT13's "the four hockey fixtures": only two `parts.json` files have a sibling `plan.json` (R3).
2. CT14's corpus guard (and the existing SFT12 loop) contradicts CR3's fixture re-baseline, which puts `PLAN_REFERENCE` into six fixtures (R13).
3. CT28's "its log's last line" ignores the runner's exit line (R5).
4. `ref_ctx(ws, **kw)`, as written, raises `TypeError` for CT2's own call (R4).
5. The Section 7 list names four tests that do not change and misses eight that do (R12).
6. CE15's JS snippets are list-indented, not file-indented (R6). CT1's "py_compile" would write `.pyc` files into `WS` (R9).
7. CT13's "speech story" cannot be a `--speech-only` (narration `"speech"`) story with a silent panel 1, because the manifest's proportional pace needs Narration or Dialogue on every panel (R18).

## Execution handoff

Plan complete and saved to `qwen-agent-workspace/docs/superpowers/plans/2026-10-30-chained-end-frames.md`.

**How it was checked.**
- **Data files.** Every Create, Edit and chmod of Tasks 1-7 lives in one data file, and this plan's code blocks are rendered from those files. The renderer refused to write the plan unless the plan's Create/Edit/chmod sequence equalled the replayed sequence.
- **Edits.** A script replayed the operations in order on a scratch copy of `133edae`'s `WS`, under `$S/cfplan/` (never the worktree or the main checkout), the way an executor applies them. It checked every old text exactly once, with and without its last newline, and created files with their exact bytes. Each old text occurred exactly once at its turn.
- **The spec's pins.** On the replay, `_plan_reference_json`, `plan_reference(True)` and `plan_reference(False)` gave the spec's sha256, character and word counts, with 68 six-word runs. `FORMAT_REFERENCE` gave `990aeb28…`, `(3538, 618)` and 80 runs.
- **Fail first, then pass.** After each task's Step 1 alone, and after the whole task, the task's test command gave the Step 2 and Step 4 summaries quoted in each task: `5 failed, 3 passed`/`8 passed`, `14 failed, 9 passed`/`23 passed`, `7 failed, 24 passed`/`31 passed`, `3 failed, 32 passed`/`35 passed`, `1 error`/`15 passed` and `7 failed, 1 passed`/`8 passed`. Each new test that passes before its task is named in that task's Step 2.
- **The existing suite.**
  - After each of Tasks 1-4, the 29 test files that load `story_engine.py`, `bin/ltx-movie` or `character_lib.py` were run. After Task 6, the 18 movie-UI and pipeline files were run.
  - The failures were exactly the expected-failure lines of that task and the earlier ones, plus the baseline's `test_rst62_import_sets`. No failure appeared in one task that the list gives to a later task, and none disappeared before Task 7.
  - Task 7's command gave `34 failed, 1 skipped` before the re-baseline and `34 passed, 1 skipped` after it; the skip is `test_mut26`, because the scratch copy is not a git checkout.
  - After Task 7, those 47 files plus `tests/test_ltx_movie_offline.py`, `tests/test_chained_end_frames.py` and `tests/test_seam_report.py` gave `1 failed, 1669 passed, 7 skipped`, and `tests/test_movie_ui_seams.py` gave `8 passed`. The failure is the baseline's `test_rst62_import_sets`, the skips are git-checkout and missing-corpus skips, and `python3 tests/test_ltx_movie_offline.py` printed `OK 347/347`, the baseline's line.
- **The git-dependent tests.** A scratch `git clone --shared` of the worktree under `$S/cfplan/` got Tasks 1-6 as commits, then Task 7 with the real SHA from Task 7 Step 2's command (Task 4's commit).
  - `test_mut26` failed before Task 7. After Task 7, all 35 re-baselined tests passed, `test_mut26` included.
  - The five tests that skip outside git (`test_ls14`, `test_lp14`, `test_lp19`, `test_lc1`, `test_lc3`) passed.
  - Task 7 Step 4's numstat and Step 7's `git diff` checks gave the quoted values: 27 changed paths there, 28 with this plan.
- **The gate script** was exercised on a cut-down baseline (batch forks' final run, limited to the files above). It listed `test_mut26` as `listed` and every other loss as an artifact of the cut-down run, as expected.
- **Compile.** Every new and changed Python file compiled under Python 3.9.6 and 3.13, and `node --check static/movie-ui/app.js` passed.
- **Not run.** The full suite (the baseline is Before Task 1's first job), any server other than the in-test movie-UI servers, any model, ffmpeg and the network. The page's behaviour in a browser is not tested beyond CT27's static checks and `node --check`; the post-merge A/B covers it.

Please review the plan. Does it capture what you want? The user pre-authorized implementation without a separate plan review, so the controller may start once it has ruled on Q1-Q4.
- **Subagent-driven** (recommended). A fresh Sonnet `code-executor` implements each task in `$S/chain-wt` on branch `chain-endframes`, and a fresh Opus reviewer checks it before the next one starts. A whole-branch review follows at the end (Task 7 Step 1).
- **Native.** One session implements every task, then one fresh Opus reviewer checks the whole branch.

I recommend subagent-driven. Tasks 2-4 build on each other's names (`_named_ids`, `end_clause`, `end_frame_detail`, `PLAN_REFERENCE_PLAN`), and Task 7 re-baselines 34 tests whose expected values depend on all of them. A mistake in Task 2's retry or drop would add a plan call to every chained story.
