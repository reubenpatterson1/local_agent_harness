# Speaker Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A quoted line keeps the speaker the narrative names. A new extractor, `line_speakers`, reads the narrative and returns, for each spoken line, the cast id it names as the speaker, or `None`. It is deterministic and conservative: a pronoun, an ambiguous name or a conflict gives `None`. A Phase 1 plan that gives an attributed line to another speaker is rejected by a new hard plan check, P17 "line speaker". The existing plan call retries it once, and the run exits 1 when the retry also fails. `assign_missing_lines` and the critic's Q1 dialogue patch never give an attributed line to another speaker. When the movie has library characters, the planner is told which lines are theirs. These stay exactly as they are: lines with a pronoun attribution, uncast plan prompts, the re-check of old stories, and every other check.

**Architecture:** All production code is in `story_engine.py`, stdlib only.
- **SA1, the extractor.** A block after `spoken_lines` adds the constants `ATTRIBUTION_VERBS`, `CALL_OUT_VERBS`, `GAP_BLOCK_WORDS` and `OBJECT_WORDS`, the private helpers `_attribution_verb_at`, `_mentions`, `_mentions_at`, `_speaker_before` and `_speaker_after`, and the public `line_speakers(narrative, cast)`.
- **SA6, the planner sentence.** `LINE_SPEAKERS_SENTENCE` is filled in `build_plan_prompt` and appended to the `@@LINES_RULE@@` fragment, only when a library member has an attributed line.
- **SA2, the check.** `plan_checks` gains P17 after P16.
- **SA3, the fatal exit.** `_Run.go` adds `"P17"` to its fatal ids. This reuses the existing `plan_round` retry feedback and the existing fatal-plan error.
- **SA4 and SA5, the pipeline guards.** `assign_missing_lines` skips a beat whose speaker is not the line's attributed one, and `q1_dialogue_patch` rejects a patch that would give the line to another speaker.

`character_lib.py`, `bin/*`, `movie_ui_lib.py` and `static/*` are not touched.

**Tech Stack:**
- Python 3.13 (`python3` = `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`, pytest 8.3.4), and Python 3.9.6 (`/usr/bin/python3`) for the compile check only.
- The standard library only.
- `tests/story_engine_testutil.py` (`set_story_env`, `make_ws`, `make_ctx`, `plan_json`, `panel_json`, `answer`, `script_agent`, `agent_log`, `kyra`, `ronin`, `MONK`) and the fake `bin/qwen-agent` it installs.

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-10-28-speaker-attribution-design.md` (Section 8.3 "Open: None").
- It is committed at `76bff8a` on branch `sa-impl` of the git worktree `sa-wt`.
- Its line numbers cite `e254e65`. `76bff8a`'s code tree is `e254e65`'s: the only difference is the spec file. Every Edit below finds its text by content.
- The spec is binding, and this plan changes no design decision.
- The user approved the spec as written. That includes its three trade-offs:
  - R1: pin-sh2-shaped runs may now exit 1.
  - R3: uncast runs whose narrative names an invented speaker by the planner's phrase can now retry or exit 1.
  - R2: the "The monk hands Kyra rice and says" false positive.
- Where the plan had to read the spec, the reading is listed in "Plan decisions".

## Global Constraints

From the spec, verbatim (section in brackets):

- [Status] "Every design choice is made here. Each choice the brief left open is marked **[spec choice]**, and Section 7 lists them all. The implementer makes no design decisions."
- [0.4 Not changed] "`character_lib.py`, `bin/*`, `movie_ui_lib.py` and `static/*`."
- [0.4 Not changed] "`classify_quotes`, `spoken_lines`, `spoken_lines_block`, `coerce_speakers`, `speaking_coercion`, `line_assignment_problems`, `recheck`, the critic prompt, `PLAN_MAX_CALLS`, `plan.json` schema and every other check id."
- [0.4 Not changed] "`LINES_RULE`, `LINES_PINNED_SENTENCE` and `SPEAKER_RULE` keep their exact text."
- [0.4 Not changed] "No existing test is edited." The one exception is the G4 re-baseline of `test_mut26`, in its own test-only commit (Task 4).
- [0.4 G3] The fixture is "A byte-exact copy of `generated/stories/pin-sh2/story_rounds/round_0/plan_reply_1.txt`: 1897 bytes, sha256 `4bd4d603998cca92c44c4d59295fb33318df3c486cf85b3c860d020b62da1374`. Copy it **before** any live rerun overwrites `pin-sh2`".
- [0.4 G4] "`BASELINE` re-baseline in a **separate test-only follow-up commit**, as in [PCP] G5. The comment gains `, then to <sha> (speaker attribution).`"
- [0.5] Out of scope:
  - "**Pronoun attribution** ("she says"). It is never resolved (D1)."
  - "Attribution by a name the narrative gives an *invented* character that the planner does not reuse as the phrase".
  - "Rewording `LINES_RULE` to resolve C1."
  - "Re-checking old stories for attribution (D6)."
  - "Giving the attribution to the critic prompt, or to `bin/judge-story`."
  - "Lip-sync attribution in render."
- [0.7] "SA1-SA6 and SAT1-SAT10 are must-haves. Nothing else is built: no CLI flag, no new advisory, no critic-prompt change and no deterministic plan repair."
- [0.6 SK2] "`/usr/bin/python3` (3.9) and `python3` (3.13) both `py_compile` `story_engine.py`." This plan checks it with `compile()`; see the house rules.
- [0.6 SK3] "`story_engine.py` gains no import."
- [0.6 SK8] "Otherwise it is byte-identical to `e254e65`; the uncast fixtures of [PCP] PT2 still match."
- [0.6 SK9] "`recheck` of a story whose `plan.json` misattributes a line gives rc 0, calls neither `plan_checks` nor `line_speakers`, and writes no P17."
- [4.1] "the module docstring states that no test renders, reads the real HOME, or contacts a model server, a daemon or the Anthropic API."
- [6] PR note: "Phase 1 now refuses a plan that gives a quoted line to a different character than the narrative names (P17; retried once, then exit 1). The pipeline's own line placement and the critic's line patches respect the same attribution. Pronoun attributions ("she says") are not enforced. Existing stories re-check exactly as before; regenerate one with `--force-story` (movie-ui: Regenerate)."

Repository rules. These are hard rules from the controller, and every task's requirements include them:

- **This Mac only.**
  - Never access the macstudio host or any remote host: no ssh, scp, rsync, curl or HTTP. Use no network.
  - Never contact a local server or port (`:8177`, `:8178`).
  - Never render, and never load a model.
  - Never read `~/.zshenv` or `fleet.env`.
- **Never touch the main checkout `/Users/reubenpatterson/local_agent_harness`.** Every command runs in the worktree `sa-wt`.
  - The one exception is Task 1 Step 1.1. It reads one file from the main checkout with `cp`: `qwen-agent-workspace/generated/stories/pin-sh2/story_rounds/round_0/plan_reply_1.txt`.
  - Nothing in the main checkout is written, moved or deleted.
  - Offline pytest in the worktree is allowed.
- **Python.** Use the standard library only in every Python file this plan touches. Every new or changed file must run on Python 3.9.6 and 3.13, so use none of these: the `match` statement, `X | Y` type expressions, the walrus operator, `str.removeprefix`, `zip(strict=)` or parenthesised context managers.
- **Tests.** They never render, never contact a model server, a daemon or the Anthropic API, and never use the real `HOME`. `tests/test_speaker_attribution.py` uses the autouse `story_env` fixture (`seu.set_story_env`: a temporary HOME, character library and LoRA catalog), and it builds every ctx and workspace under `tmp_path`.
- **Running tests.** Run them as `cd $WS && python3 -m pytest -q -p no:cacheprovider tests/<file>`. Every pytest run first prints a `pytest_asyncio` deprecation warning, which is expected.
- **Editing.** Executors make every file change with the Edit tool (an Edit step) or the Write tool (a Create step). The only exception is the `cp` of Task 1 Step 1.1. Never use `rm`, `sed -i`, a redirect or a script to change a tracked file.
- **Git.**
  - Never stage `../.DS_Store`, `../.claude/`, `.claude/`, `../agent/__pycache__/`, the repo-root `../bin/` or `bin/action-from-dir`.
  - Stage only the paths a task names, and check `git diff --cached --name-only` before every commit.
  - Never use `git stash`, `git reset` or `git checkout` of a path.
- **Commit messages.** Every commit message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. The commit commands below pass it as a second `-m`.
- **Known pre-existing failures.** They are ignored when they fail exactly as at the baseline.
  - The controller's baseline is the full run at `e254e65`'s code tree, recorded at `$S/pc-baseline/final-pytest.txt`. It gave `2 failed, 1864 passed, 2 skipped`, and `tests/test_ltx_movie_offline.py` printed `OK 347/347`.
  - The two failures are `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike`, and `tests/test_story_engine.py::test_rst62_import_sets`, which fails on `bin/ltx-mlx-render`.
  - The regression gate expects exactly those two failures and `1864 + 15` passed. No other test may fail.
- **`test_mut26`.** `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` diffs `PIPELINE_FILES`, which includes `story_engine.py`, in the working tree against a pinned commit (`05ba1792b7e1620f96b1e50ba5a83f6349620529`).
  - It therefore fails from Task 1's first `story_engine.py` edit until Task 4 re-baselines it, in its own test-only commit.
  - No task before Task 4 runs or edits it. Each task's Step 4 run names its files and does not include `tests/test_movie_ui_builder.py`.

House rules:

- **Paths.**
  - `S` = `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`.
  - `WS` = `$S/sa-wt/qwen-agent-workspace`.
  - The git root is `$S/sa-wt`, one level up, so `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix.
  - Run every command from `WS`. Every bash block below assumes `cd $WS`.
  - Shell variables do not persist between commands, so every block that uses `$S`, `$WS`, `$D` or `$SHA` defines it first, or names the house-rule value.
- **Code blocks** are copied exactly, byte for byte.
  - A **Create** step uses the Write tool to write a new file whose whole content is the block, followed by one newline.
  - An **Edit** step uses the Edit tool to replace one block of old text with the new text. The old text must occur exactly once in the file at that moment. If it does not, stop and report, and do not adapt it.
  - Every Append is written as an Edit. Its old text is the file's current last lines, and its new text is those lines, two empty lines, then the new code.
  - A **Run this command** step runs its `bash` block from `WS`.
- **The compile check** in each task is this command, with the task's files as `FILES`. It uses `compile()` on the source text, not `py_compile`, which errors on macOS when pointed at `/dev/null`. The expected output is two lines, `compiled N` for 3.9 and then for 3.13:

```bash
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' FILES; done
```

## Review Focus

These five inputs follow from the spec and are the ones most likely to reach a real run first. No SAT test exercises them. Each is pinned by a test in its owning task.

1. **A plan that both drops a library character and misattributes the lines.** Shots, 2 panels: both beats cast the ronin, and beat 1 has him say lines 1 and 2. This is the pin-sh2 shape with Kyra dropped.
   - Expected: after two such replies the run exits 1. The fatal stderr lists P16 for c1 first, then the P17 messages for beat 1 line 1 and beat 1 line 2, in `plan_checks` order. There is no panel call, and no `story.md` or `plan.json`.
   - Test: `test_review_focus_1_an_exhausted_plan_lists_p16_then_every_p17` (Task 2).
2. **A speaker written as a name, not an id.** The speakers are `"Kyra"` and `"RONIN"`; models do this when the narrative uses names.
   - Expected: P17 runs on the coerced plan. `"RONIN"` resolves to c2 by library name ([PCP] A1), so P17 reports c2 for Kyra's line 2. With beat 3 cast `["c1"]` and speaker `"The Woman in Grey"`, the hard list is empty.
   - Test: `test_review_focus_2_a_speaker_written_as_a_name_is_checked_after_coercion` (Task 2).
3. **A quoted sign before the spoken lines, plus curly quotes.** The narrative is `A sign reads "Closed". Kyra says, “Go.” The ronin says, "Fine."`.
   - Expected: `spoken_lines` is `["Go.", "Fine."]` and `line_speakers` is `["c1", "c2"]`, so the numbers line up even though a quote is skipped. The prompt carries `line 1 to c1 and line 2 to c2`. A plan with c1 saying line 2 gets exactly one P17, for `"Fine."` to c2.
   - Test: `test_review_focus_3_a_quote_that_is_not_spoken_keeps_the_line_numbers` (Task 2).
4. **An invented speaker in a run with library characters.** The narrative is `Kyra says, "Go." The old monk says, "Enter."`, and the planner adds c3 "the old monk".
   - Expected: the prompt sentence lists only `line 1 to c1`, because an invented id does not exist before the reply. P17 still enforces c3 for line 2 from the plan's cast, and a plan with c3 saying it is clean.
   - Test: `test_review_focus_4_an_invented_speaker_in_a_pinned_run` (Task 2).
5. **The pin-sh2 shape with line 2 left out by both plan replies.** Shots, 2 panels: beat 1 `[c1]` says line 1, and beat 2 `[c2]` is silent. Models omit a line as often as they misplace it.
   - Expected: `assign_missing_lines` skips the ronin's beat and gives line 2 to beat 1. The run exits 0 with `Dialogue: the woman in grey: We reach the gate before dark. Stay close to me.` and `hard []`.
   - At `e254e65` the ronin got the line. Before Task 3 the run ends with exit 2, on a story-end P17.
   - Test: `test_review_focus_5_the_pin_sh2_shape_with_line_2_left_out` (Task 3).

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `story_engine.py` | Modify (Tasks 1-3) | Task 1: the SA1 block (constants, helpers and `line_speakers`); `LINE_SPEAKERS_SENTENCE` and its use in `build_plan_prompt` (SA6). Task 2: P17 in `plan_checks` and its docstring (SA2); `"P17"` in `_Run.go`'s fatal ids (SA3). Task 3: the `assign_missing_lines` guard and docstring (SA4); the `q1_dialogue_patch` guard and docstring (SA5). |
| `tests/fixtures/speaker_attribution/pin_sh2_plan_reply_1.txt` | Create by `cp` (Task 1) | The byte-exact pin-sh2 plan reply (G3). |
| `tests/test_speaker_attribution.py` | Create (Task 1), Edit to append (Tasks 2, 3) | SAT1-SAT10 and Review Focus 1-5. |
| `docs/superpowers/specs/2026-10-27-pinned-cast-presence-design.md` | Modify (Task 3) | The amendment line of spec 6 step 8, as bullet A5. |
| `tests/test_movie_ui_builder.py` | Modify (Task 4 only) | `test_mut26` `BASELINE` and its comment (G4). |

The tasks split the work like this:
- Task 1 is the extractor and the planner contract: everything that reads the attribution, and everything the plan model reads.
- Task 2 is the rule: the P17 check, its retry and its exit.
- Task 3 is the pipeline guards.
- Task 4 is the review, the test-only re-baseline and the final measurements.

A reviewer can accept or reject each task on its own diff. The suite stays green after every task except `test_mut26`, as stated above.

---

## Before Task 1: confirm the tree, take the snapshot, record the baseline (controller; no code, no commit)

SK1 compares against the pass count recorded here. Nothing is written into the repository.

- [ ] **Step 1: Confirm the starting point.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
WS=$S/sa-wt/qwen-agent-workspace
cd $WS
git branch --show-current                        # expected: sa-impl
git log -1 --format=%s                           # expected: docs(plan): speaker attribution implementation plan
git rev-parse HEAD~1                             # expected: 76bff8a74db3dfaf5ebeb058d4f297faf3781bed (the spec commit)
git diff --stat e254e65 HEAD -- . ':(exclude)docs' | tail -1   # expected: no output (HEAD's code tree is e254e65's)
git status --short                               # expected: no output, or only ?? ../agent/__pycache__/ (written by any earlier test run; never staged)
ls tests/test_speaker_attribution.py tests/fixtures/speaker_attribution 2>&1 | grep -c "No such file"   # expected: 2
wc -l < story_engine.py                          # expected: 3796
grep -c "P17" story_engine.py                    # expected: 0
grep -c "line_speakers" story_engine.py          # expected: 0
grep -c "05ba1792b7e1620f96b1e50ba5a83f6349620529" tests/test_movie_ui_builder.py   # expected: 2
ls generated 2>&1 | grep -c "No such file"       # expected: 1 (the worktree has no generated/ tree)
```

If any expected value differs, stop and report: every Edit below was written against this tree.

- [ ] **Step 2: Take the compressed snapshot (house rule; spec 6 step 1).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
tar czf $S/snapshot-pre-speaker-attribution-e254e65.tgz --exclude qwen-agent-workspace/generated -C $S/sa-wt qwen-agent-workspace
tar tzf $S/snapshot-pre-speaker-attribution-e254e65.tgz | grep -c '^qwen-agent-workspace/story_engine.py$'   # expected: 1
```

- [ ] **Step 3: Record the pytest and script baselines (spec 6 step 2; about 1 minute).**

The controller recorded the full-suite baseline at `e254e65`'s code tree in `$S/pc-baseline/final-pytest.txt`. Copy it, and do not re-run the 15-minute suite:

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/sa-baseline
mkdir -p $D
cp $S/pc-baseline/final-pytest.txt $D/baseline-pytest.txt
tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
python3 tests/test_ltx_movie_offline.py 2>&1 | tail -1 | tee $D/baseline-offline.txt
git -C $S/sa-wt rev-parse HEAD > $D/base-commit.txt
```

Expected output:
- the summary `2 failed, 1864 passed, 2 skipped, 3370 warnings in 868.18s (0:14:28)`;
- exactly two `FAILED` lines, `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets - AssertionError: b...`;
- `OK 347/347` from the offline script.

If `$S/pc-baseline/final-pytest.txt` is missing, or its last line is not that summary, record the baseline in the worktree now and use that file instead: `python3 -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1` (about 15 minutes).

`tests/test_fleet_tracing.py::test_trt41a_trace_cli_on_one_agent` is timing-sensitive and unrelated to this plan. If it ever fails, rerun it alone (`python3 -m pytest -q -p no:cacheprovider tests/test_fleet_tracing.py -k trt41a`) and record both results. Write any other difference into `$D/baseline-notes.txt`; Task 4 compares against what is recorded here.

---

### Task 1: The extractor and the planner sentence (SA1, SA6), and the pin-sh2 fixture (G3)

This task implements:
- G3, the fixture, copied before any `story_engine.py` edit and before any live rerun;
- SA1, the extractor block;
- SA6, `LINE_SPEAKERS_SENTENCE`, the `said` block and the `@@LINES_RULE@@` fragment.

Tests: SAT1, SAT2 and SAT9. The task creates `tests/test_speaker_attribution.py` with the whole spec 4.1 header and helpers, which Tasks 2 and 3 append to. This is the first pipeline commit, so `test_mut26` fails from here until Task 4.

**Files:**
- Create (by `cp`): `tests/fixtures/speaker_attribution/pin_sh2_plan_reply_1.txt`
- Create: `tests/test_speaker_attribution.py`
- Modify: `story_engine.py`. The edits go after `LINES_PINNED_SENTENCE` (`:380-382`), after `spoken_lines` (`:531-534`), before `seed = ""` in `build_plan_prompt` (`:785`), and in the `@@LINES_RULE@@` fragment (`:803-805`).

**Interfaces:**
- Consumes (existing):
  - from `story_engine`: `classify_quotes(narrative) -> [(inner, spoken)]`, `spoken_lines(narrative) -> [str]`, `line_words(text) -> [str]`, `QUOTE_RE`, `_CLAUSE_BREAK_RE`, `_QUOTE_EDGE_CHARS`, `SPEECH_VERBS`, `LINES_RULE`, `LINES_PINNED_SENTENCE`, `build_plan_prompt(ctx, compatible, pins) -> str`, `engine_seconds(ctx)`, and `StoryContext` (`members`, `mode`, `narration`, `narrative`);
  - from `character_lib`: `resolve_cast(entries) -> [CastMember]` (`.name`, `.phrase`) and `dialogue_word_cap(seconds, fragments=1)`;
  - from `story_engine_testutil`: `set_story_env`, `make_ws`, `make_ctx(se, ws, **overrides)`, `plan_json(mode, n, cast=None, **overrides)`, `panel_json`, `answer`, `script_agent`, `agent_log`, `kyra(lib)`, `ronin(lib)`.
- Produces:
  - In `story_engine`: the frozensets `ATTRIBUTION_VERBS`, `CALL_OUT_VERBS`, `GAP_BLOCK_WORDS` and `OBJECT_WORDS`; the helpers `_attribution_verb_at(words, p) -> int`, `_mentions(cast) -> [(id, words)]`, `_mentions_at(words, mentions, end=None, start=None) -> {id: width}`, `_speaker_before(words, mentions) -> id or None` and `_speaker_after(words, mentions) -> id or None`; the public `line_speakers(narrative, cast) -> [id or None]`, with one entry per `spoken_lines(narrative)` line; and the string `LINE_SPEAKERS_SENTENCE`, a `%` format of one `str`. `build_plan_prompt` appends the filled sentence to the `@@LINES_RULE@@` fragment only when the narrative has lines, the movie has members, and at least one line is attributed to a member.
  - In `tests/test_speaker_attribution.py`:
    - the module header (`WS`, `FIX`, `FIX_SHA256`, `seu`, `lib`, `se`, with `copy`, `hashlib`, `json` and `re` imported) and the fixtures `story_env` (autouse) and `ws`;
    - copied verbatim from `tests/test_pinned_cast.py`: `KYRA`, `RONIN`, `CAST2`, `LINES_NARRATIVE`, `_members`, `_raw`, `_read_json`, `_fatal_err` and `_pt16_run`;
    - the spec's extra helpers `CAST3`, `PRONOUN_NARRATIVE`, `MONK_NARRATIVE`, `P17(k, n, line, want, want_phrase, got, got_phrase) -> str`, `SENTENCE(items) -> str` and `_shots2(ws, story_env, **kw) -> ctx`;
    - `_fix_text() -> str`.

- [ ] **Step 1: Copy the fixture and write the failing tests.**

New tests in this task: `test_sat1_constants`, `test_sat2_extraction_table`, `test_sat9_plan_prompt`.

**1.1.** Run this command (from WS). It is spec 6 step 2's fixture copy. It reads the main checkout and writes only into the worktree:

```bash
mkdir -p tests/fixtures/speaker_attribution
cp /Users/reubenpatterson/local_agent_harness/qwen-agent-workspace/generated/stories/pin-sh2/story_rounds/round_0/plan_reply_1.txt tests/fixtures/speaker_attribution/pin_sh2_plan_reply_1.txt
shasum -a 256 tests/fixtures/speaker_attribution/pin_sh2_plan_reply_1.txt
wc -c < tests/fixtures/speaker_attribution/pin_sh2_plan_reply_1.txt
git diff --quiet -- story_engine.py && echo "story_engine.py unedited"
```

Expected output, exactly (the `wc` count may be printed with leading spaces):

```text
4bd4d603998cca92c44c4d59295fb33318df3c486cf85b3c860d020b62da1374  tests/fixtures/speaker_attribution/pin_sh2_plan_reply_1.txt
1897
story_engine.py unedited
```

If the hash differs, a live rerun has replaced `pin-sh2` in the main checkout since the spec was written. In that case, run this command instead. It copies the spec author's archived copy of the same file, whose hash matched when this plan was written, over the destination:

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cp $S/p17/ws/tests/fixtures/speaker_attribution/pin_sh2_plan_reply.txt tests/fixtures/speaker_attribution/pin_sh2_plan_reply_1.txt
shasum -a 256 tests/fixtures/speaker_attribution/pin_sh2_plan_reply_1.txt
```

If that hash also differs, stop and report.

**1.2.** Create `tests/test_speaker_attribution.py`:

```python
"""Tests for speaker attribution (docs/superpowers/specs/2026-10-28-speaker-attribution-
design.md, Section 4.1: SAT1-SAT10, and the plan's Review Focus 1-5): a quoted line keeps the
speaker the narrative names. line_speakers extracts the attribution, P17 "line speaker" is a hard
plan check (retried by the plan call, fatal when the retries run out), assign_missing_lines and
q1_dialogue_patch never give an attributed line to another speaker, and the plan prompt tells
the planner which lines belong to already-cast characters.

Run from the workspace root:
python3 -m pytest -q -p no:cacheprovider tests/test_speaker_attribution.py
Stdlib plus pytest. No test renders, reads the real HOME, or contacts a model server, a daemon or
the Anthropic API: every model call goes to the fake bin/qwen-agent of a temp workspace
(story_engine_testutil.make_ws), every ctx lives under tmp_path, and every test runs under the
autouse story_env fixture (a temporary HOME, character library and LoRA catalog). The fixture
tests/fixtures/speaker_attribution/pin_sh2_plan_reply_1.txt is a byte-exact copy of the plan
reply of the live pin-sh2 run at e254e65 (spec G3).
"""

import copy
import hashlib
import importlib.machinery
import json
import os
import re
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
FIX = os.path.join(WS, "tests", "fixtures", "speaker_attribution", "pin_sh2_plan_reply_1.txt")
FIX_SHA256 = "4bd4d603998cca92c44c4d59295fb33318df3c486cf85b3c860d020b62da1374"
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


lib = _load("character_lib_for_attribution", "character_lib.py")
se = _load("story_engine_for_attribution", "story_engine.py")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


# --- Copied verbatim from tests/test_pinned_cast.py (spec 4.1) ---------------------------------

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


def _fatal_err(message_lines, ctx):
    return ("Error: the story model did not return a usable plan after 2 call(s)\n"
            + "".join("  - %s\n" % m for m in message_lines)
            + "Raw replies are kept in %s. Rerun the same command to try again.\n"
            % os.path.join(ctx.story_dir, "story_rounds", "round_0"))


def _pt16_run(ws, tmp_path, monkeypatch, story_env):
    """(rc, ctx, agent log) of PT16's engine run: chained, kyra and ronin pinned, --speech-only,
    LINES_NARRATIVE, every beat cast ["c1", "c2"], beats 2 and 3 spoken by c1."""
    members = _members(story_env)
    ctx = seu.make_ctx(se, ws, story_id="pc5", members=members, narration="speech",
                       narrative=LINES_NARRATIVE)
    raw = _raw("chained", 3, [["c1", "c2"]] * 3)
    raw["beats"][1].update(speaker="c1", lines=[1])
    raw["beats"][2].update(speaker="c1", lines=[2])
    panel = {
        "1": [seu.answer({"title": "The Temple Steps",
                          "image": seu.panel_json("chained", 1, KYRA)["image"],
                          "motion": "The woman in grey climbs the stone steps as the ronin "
                                    "follows one step behind her."})],
        "2": [seu.answer({"title": "Near The Top",
                          "motion": "The woman in grey turns and steps toward the camera, the "
                                    "ronin a pace behind her.",
                          "dialogue": "We reach the gate before dark."})],
        "3": [seu.answer({"title": "Through The Gate",
                          "motion": "The woman in grey walks under the gate toward the camera, "
                                    "the ronin beside her.",
                          "dialogue": "Stay close to me."})]}
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(raw)], panel=panel)
    rc, _advisories = se.run(ctx)
    return rc, ctx, seu.agent_log(log)


# --- Extra helpers (spec 4.1) ----------------------------------------------------------------

CAST3 = [{"id": "c1", "phrase": KYRA, "cast_name": "kyra"},
         {"id": "c2", "phrase": RONIN, "cast_name": "ronin"},
         {"id": "c3", "phrase": "the old monk", "cast_name": None}]
PRONOUN_NARRATIVE = (LINES_NARRATIVE.replace("Near the top Kyra turns", "Near the top she turns")
                     .replace("and Kyra says", "and she says"))
MONK_NARRATIVE = 'The courier reaches the temple gate, and the old monk says, "Enter."'


def P17(k, n, line, want, want_phrase, got, got_phrase):
    """The SA2 message for beat k and spoken line n."""
    return ("beat %d: P17 line speaker: the narrative gives spoken line %d \"%s\" to %s '%s', but "
            "this beat's speaker is %s '%s'; put line %d in the lines of a beat whose speaker is "
            "%s (consecutive lines may share a beat), and never give it to another character"
            % (k, n, line, want, want_phrase, got, got_phrase, n, want))


def SENTENCE(items):
    """LINE_SPEAKERS_SENTENCE filled with the joined items text."""
    return se.LINE_SPEAKERS_SENTENCE % items


def _shots2(ws, story_env, **kw):
    """The pin-sh2 ctx: shots, 2 panels, kyra and ronin pinned, --speech-only, LINES_NARRATIVE."""
    return seu.make_ctx(se, ws, mode="shots", panels=2, members=_members(story_env),
                        narration="speech", narrative=LINES_NARRATIVE, **kw)


def _fix_text():
    with open(FIX, encoding="utf-8") as f:
        return f.read()


# --- SAT1: the constants (SA1, SA6) ------------------------------------------------------------

ATTRIBUTION_VERBS = frozenset("""
    says said asks asked replies replied answers answered shouts shouted yells yelled
    screams screamed cries cried whispers whispered murmurs murmured mutters muttered
    exclaims exclaimed announces announced declares declared tells told""".split())
CALL_OUT_VERBS = frozenset(("calls", "called"))
GAP_BLOCK_WORDS = frozenset("""
    the a an this that these those his her its their my our your he she they it him them we
    you i who whom which whose someone somebody everyone everybody nobody one as while when
    whenever before after until because since if though although whereas""".split())
OBJECT_WORDS = frozenset("""
    to at toward towards beside behind with of for from near by past around under over like
    than without into onto upon about besides""".split())
LINE_SPEAKERS_SENTENCE = (" The narrative gives these lines to already-cast characters: %s. The "
                          "beat that holds one of these lines has that character as its speaker, "
                          "and no other character says it.")


def test_sat1_constants():
    assert se.ATTRIBUTION_VERBS == ATTRIBUTION_VERBS
    assert se.CALL_OUT_VERBS == CALL_OUT_VERBS
    assert se.GAP_BLOCK_WORDS == GAP_BLOCK_WORDS
    assert se.OBJECT_WORDS == OBJECT_WORDS
    assert se.LINE_SPEAKERS_SENTENCE == LINE_SPEAKERS_SENTENCE
    assert se.LINE_SPEAKERS_SENTENCE.count("%s") == 1
    assert re.findall(r"@@[A-Z_]+@@", se.LINE_SPEAKERS_SENTENCE) == []
    assert se.ATTRIBUTION_VERBS <= se.SPEECH_VERBS


# --- SAT2: the extraction table (SA1, SK4) -----------------------------------------------------

SAT2_ROWS = [
    (LINES_NARRATIVE, CAST3, ["c1", "c1"]),
    (PRONOUN_NARRATIVE, CAST3, [None, None]),
    ('Kyra says, "Go."', CAST3, ["c1"]),
    ('"Go," says the ronin.', CAST3, ["c2"]),
    ('“Go,” says the ronin.', CAST3, ["c2"]),
    ('"Go," the ronin says.', CAST3, ["c2"]),
    ('"Go," Kyra said quietly.', CAST3, ["c1"]),
    ('"Go!" yells Kyra.', CAST3, ["c1"]),
    ('"Go!" Kyra yells.', CAST3, [None]),
    ('She says, "Go."', CAST3, [None]),
    ('Kyra turns to the ronin, and she says, "Go."', CAST3, [None]),
    ('The ronin nods as Kyra says, "Go."', CAST3, ["c1"]),
    ('Kyra nods as the ronin says, "Go."', CAST3, ["c2"]),
    ('The ronin watches Kyra and says, "Go."', CAST3, [None]),
    ('Kyra asks the ronin, "Ready?"', CAST3, ["c1"]),
    ('The ronin and Kyra said, "Go."', CAST3, [None]),
    ('The monk beside Kyra says, "Go."', CAST3, [None]),
    ("Kyra's brother says, \"Go.\"", CAST3, [None]),
    ('The old monk says, "Go."', CAST3, ["c3"]),
    ('The monk says, "Go."', CAST3, [None]),
    ('"Go," says Kyra, "now."', CAST3, ["c1", "c1"]),
    ('Kyra says, "Go." The ronin says, "Fine."', CAST3, ["c1", "c2"]),
    ('Kyra says, "Go," and the ronin replies, "Fine."', CAST3, ["c1", "c2"]),
    ('Kyra calls out, "Wait!"', CAST3, ["c1"]),
    ('Kyra quietly says, "Wait."', CAST3, ["c1"]),
    ('Kyra smiles and then says, "Wait."', CAST3, ["c1"]),
    ('Kyra waits and Jiro says, "Wait."', CAST3, [None]),
    ('Kyra whispers to the ronin, "Wait."', CAST3, ["c1"]),
    ('The crowd shouts, "Kyra!"', CAST3, []),
    ('A sign reads "Closed".', CAST3, []),
    ('"Go," Kyra says to the ronin, who answers, "Fine."', CAST3, ["c1", None]),
    ('Kyra says, "Go," the ronin says.', CAST3, [None]),
    ('They pass under the gate together and Kyra says, "Stay close to me."', CAST3, [None]),
    ('The woman in grey says, "Go."', CAST3, ["c1"]),
    ('Ronin says, "Go."', CAST3, ["c2"]),
    ('"Go," Kyra says, "now."', CAST3, ["c1", "c1"]),
    ('The ronin hands Kyra rice and says, "Eat."', CAST3, [None]),
    ('Then says Kyra: "Go."', CAST3, ["c1"]),
    ('Kyra says, "Go."', [], [None]),
]


def test_sat2_extraction_table():
    assert len(SAT2_ROWS) == 39
    for text, cast, want in SAT2_ROWS:
        assert se.line_speakers(text, cast) == want, text
        assert len(want) == len(se.spoken_lines(text)), text


# --- SAT9: the plan prompt (SA6, SK8) ----------------------------------------------------------

def _plan_prompt(ws, **kw):
    """(plan prompt, filled LINES_RULE) of make_ctx(**kw), with no catalog and no pins."""
    ctx = seu.make_ctx(se, ws, **kw)
    cap = str(lib.dialogue_word_cap(se.engine_seconds(ctx), 2))
    return se.build_plan_prompt(ctx, [], []), se.LINES_RULE.replace("@@LINE_WORDS@@", cap)


def test_sat9_plan_prompt(ws, story_env):
    members = _members(story_env)
    both = SENTENCE("line 1 to c1 and line 2 to c1")
    prompt, rule = _plan_prompt(ws, mode="shots", members=members, narrative=LINES_NARRATIVE)
    assert rule + se.LINES_PINNED_SENTENCE + both + "\nloras: " in prompt
    prompt, rule = _plan_prompt(ws, mode="chained", members=members, narrative=LINES_NARRATIVE)
    assert rule + both + "\nloras: " in prompt
    prompt, rule = _plan_prompt(ws, mode="shots", members=members, narrative=PRONOUN_NARRATIVE)
    assert rule + se.LINES_PINNED_SENTENCE + "\nloras: " in prompt
    assert "The narrative gives these lines" not in prompt
    prompt, rule = _plan_prompt(ws, mode="chained", members=members, narrative=PRONOUN_NARRATIVE)
    assert rule + "\nloras: " in prompt
    assert "The narrative gives these lines" not in prompt
    prompt, _rule = _plan_prompt(ws, mode="chained", members=members, narrative=(
        'Kyra climbs the steps, and the ronin follows. She says, "Wait." The ronin says, "Go."'))
    assert SENTENCE("line 2 to c2") in prompt
    prompt, _rule = _plan_prompt(ws, mode="chained", members=members, narrative=(
        'Kyra says, "Go." The ronin says, "Why?" Kyra says, "Now."'))
    assert SENTENCE("line 1 to c1, line 2 to c2 and line 3 to c1") in prompt
    for narrative in (LINES_NARRATIVE, MONK_NARRATIVE):
        prompt, _rule = _plan_prompt(ws, mode="chained", narrative=narrative)
        assert "The narrative gives these lines" not in prompt, narrative
    prompt, _rule = _plan_prompt(ws, mode="chained", members=members, narration=False,
                                 narrative=LINES_NARRATIVE)
    assert "The narrative gives these lines" not in prompt
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_speaker_attribution.py 2>&1 | grep -E '^FAILED|passed|failed'
```

Expected: `3 failed`.
- SAT1 fails with `AttributeError: module 'story_engine_for_attribution' has no attribute 'ATTRIBUTION_VERBS'`.
- SAT2 fails with `... has no attribute 'line_speakers'`.
- SAT9 fails with `... has no attribute 'LINE_SPEAKERS_SENTENCE'`.

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py` (SA1, the extractor): replace this text, which occurs exactly once:

```python
    return [spoken_display(inner) for inner, spoken in classify_quotes(narrative)
            if spoken and line_words(inner)]


def required_lines(ctx):
```

with:

```python
    return [spoken_display(inner) for inner, spoken in classify_quotes(narrative)
            if spoken and line_words(inner)]


# Speaker attribution spec SA1, D1, D2: who the narrative says speaks each spoken line.
ATTRIBUTION_VERBS = frozenset("""
    says said asks asked replies replied answers answered shouts shouted yells yelled
    screams screamed cries cried whispers whispered murmurs murmured mutters muttered
    exclaims exclaimed announces announced declares declared tells told""".split())
CALL_OUT_VERBS = frozenset(("calls", "called"))     # an attribution verb only before "out"
GAP_BLOCK_WORDS = frozenset("""
    the a an this that these those his her its their my our your he she they it him them we
    you i who whom which whose someone somebody everyone everybody nobody one as while when
    whenever before after until because since if though although whereas""".split())
OBJECT_WORDS = frozenset("""
    to at toward towards beside behind with of for from near by past around under over like
    than without into onto upon about besides""".split())


def _attribution_verb_at(words, p):
    """The number of words of the attribution verb at words[p] (1, or 2 for "calls out"), or 0."""
    if p >= len(words):
        return 0
    if words[p] in ATTRIBUTION_VERBS:
        return 1
    return 2 if words[p] in CALL_OUT_VERBS and words[p + 1:p + 2] == ["out"] else 0


def _mentions(cast):
    """[(cast id, words)]: every entry's phrase, and a library character's name (SA1, D2)."""
    out = []
    for entry in cast:
        for name in (entry.get("phrase"), entry.get("cast_name")):
            words = line_words(name) if isinstance(name, str) else []
            if words and entry["id"]:
                out.append((entry["id"], words))
    return out


def _mentions_at(words, mentions, end=None, start=None):
    """{cast id: words in its longest mention} for the mentions that end just before index end,
    or begin at index start, of words."""
    hits = {}
    for cid, tokens in mentions:
        n = len(tokens)
        if end is not None:
            span = words[end - n:end] if n <= end else None
        else:
            span = words[start:start + n]
        if span == tokens:
            hits[cid] = max(hits.get(cid, 0), n)
    return hits


def _speaker_before(words, mentions):
    """The cast id the clause before a quote names as its speaker, or None (SA1 forms B1, B2)."""
    verbs = [p for p in range(len(words)) if _attribution_verb_at(words, p)]
    if verbs:
        v = verbs[-1]
        tokens = set(w for _cid, t in mentions for w in t)
        for e in range(v, max(1, v - 3) - 1, -1):
            gap = words[e:v]
            joined = len(gap) in (2, 3) and gap[-1] in ("and", "then") and not any(
                w in GAP_BLOCK_WORDS or w in tokens or w in SPEECH_VERBS for w in gap)
            if gap and not joined and not (len(gap) == 1 and gap[0].endswith("ly")):
                continue
            hits = _mentions_at(words, mentions, end=e)
            if not hits:
                continue
            if len(hits) > 1:
                return None
            cid, width = next(iter(hits.items()))
            start = e - width
            before = words[start - 1] if start else None
            if before in OBJECT_WORDS or (before in ("and", "or", "nor") and start > 1):
                return None
            if joined and any(c != cid for c, t in mentions
                              for q in range(len(t), start + 1) if words[q - len(t):q] == t):
                return None
            return cid
    lead = 1 if words[:1] in (["and"], ["then"]) else 0
    width = _attribution_verb_at(words, lead)
    if width:
        hits = _mentions_at(words, mentions, start=lead + width)
        if len(hits) == 1 and lead + width + next(iter(hits.values())) == len(words):
            return next(iter(hits))
    return None


def _speaker_after(words, mentions):
    """The cast id the clause after a quote names as its speaker, or None (SA1 forms A1, A2)."""
    width = _attribution_verb_at(words, 0)
    if width:
        hits = _mentions_at(words, mentions, start=width)
        return next(iter(hits)) if len(hits) == 1 else None
    hits = _mentions_at(words, mentions, start=0)
    if len(hits) != 1:
        return None
    cid, n = next(iter(hits.items()))
    rest = words[n:]
    if _attribution_verb_at(rest, 0) or (rest[:1] and rest[0].endswith("ly")
                                         and _attribution_verb_at(rest, 1)):
        return cid
    return None


def line_speakers(narrative, cast):
    """One entry per line of spoken_lines(narrative), in order (speaker attribution spec SA1):
    the id of the cast entry (plan cast entries, or {"id", "phrase", "cast_name"} dicts) that the
    narrative names as the line's speaker, or None when it names none, or not unambiguously."""
    mentions = _mentions(cast)
    text = narrative.replace("“", '"').replace("”", '"')
    matches = list(QUOTE_RE.finditer(text))
    out = []
    for i, (match, (inner, spoken)) in enumerate(zip(matches, classify_quotes(narrative))):
        if not (spoken and line_words(inner)):
            continue
        if not mentions:
            out.append(None)
            continue
        prev_end = matches[i - 1].end() if i > 0 else 0
        next_start = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        lead = text[prev_end:match.start()].rstrip(_QUOTE_EDGE_CHARS)
        before = _speaker_before(line_words(_CLAUSE_BREAK_RE.split(lead)[-1]), mentions)
        after_text = text[match.end():next_start]
        after = None
        if (not match.group(1).rstrip().endswith((".", "!", "?", "…"))
                or re.match(r"\s*[a-z]", after_text)):
            after = _speaker_after(line_words(_CLAUSE_BREAK_RE.split(
                after_text.lstrip(_QUOTE_EDGE_CHARS))[0]), mentions)
        out.append(None if before and after and before != after else before or after)
    return out


def required_lines(ctx):
```

**3.2.** Edit `story_engine.py` (SA6, the constant): replace this text, which occurs exactly once:

```python
                         "speaker, even when two consecutive lines must then share a beat.")
LORA_EMPTY_PARAGRAPH = ("an object with the keys global, per_beat and stills, each empty: global "
```

with:

```python
                         "speaker, even when two consecutive lines must then share a beat.")
# Speaker attribution spec SA6, D5: the lines the narrative gives to already-cast characters.
LINE_SPEAKERS_SENTENCE = (" The narrative gives these lines to already-cast characters: %s. The "
                          "beat that holds one of these lines has that character as its speaker, "
                          "and no other character says it.")
LORA_EMPTY_PARAGRAPH = ("an object with the keys global, per_beat and stills, each empty: global "
```

**3.3.** Edit `story_engine.py` (SA6, the sentence): replace this text, which occurs exactly once:

```python
        lora += "\n".join(catalog_line(e) for e in compatible) + _pins_block(pins)
    seed = ""
```

with:

```python
        lora += "\n".join(catalog_line(e) for e in compatible) + _pins_block(pins)
    said = ""
    if lines and ctx.members:
        fixed = [{"id": "c%d" % i, "phrase": m.phrase, "cast_name": m.name}
                 for i, m in enumerate(ctx.members, start=1)]
        items = ["line %d to %s" % (n, cid) for n, cid
                 in enumerate(line_speakers(ctx.narrative, fixed), start=1) if cid]
        if items:
            said = LINE_SPEAKERS_SENTENCE % (items[0] if len(items) == 1 else
                                             ", ".join(items[:-1]) + " and " + items[-1])
    seed = ""
```

**3.4.** Edit `story_engine.py` (SA6, the fragment): replace this text, which occurs exactly once:

```python
        ("@@LINES_RULE@@", (LINES_RULE + (LINES_PINNED_SENTENCE
                                          if ctx.members and ctx.mode != "chained" else ""))
         if lines else ""),
```

with:

```python
        ("@@LINES_RULE@@", (LINES_RULE + (LINES_PINNED_SENTENCE
                                          if ctx.members and ctx.mode != "chained" else "")
                         + said)
         if lines else ""),
```

Nothing else in `build_plan_prompt` changes.

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_speaker_attribution.py tests/test_story_engine.py tests/test_dialogue.py tests/test_narrative_fidelity.py tests/test_writer_pacing.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_casting_pipeline.py tests/test_iterate_story.py tests/test_pinned_cast.py tests/test_judge_story.py tests/test_ltx_story_manifest_chain.py tests/test_character_lib.py 2>&1 | grep -E '^FAILED|passed|failed'
```

Expected output:
- one `FAILED` line, `tests/test_story_engine.py::test_rst62_import_sets` (the known failure);
- then `1 failed, 499 passed, 1 skipped`. That is the same files' `496 passed` at `e254e65`, plus 3.

These tests pass unedited in this run: `test_pinned_cast.py::test_pt2_fixed_cast_block_and_uncast_byte_identity` (SK8: the uncast fixtures are byte-identical), `test_pinned_cast.py::test_pt5_lines_sentence_variants` (its containment checks still hold with the sentence appended after `LINES_PINNED_SENTENCE`; spec 4.2) and `test_story_engine.py::test_rst8_plan_prompt_matrix`.

Then run the compile check with `FILES` = `story_engine.py tests/test_speaker_attribution.py`. Expected: `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_speaker_attribution.py tests/fixtures/speaker_attribution/pin_sh2_plan_reply_1.txt
git diff --cached --name-only    # expected: exactly these 3 paths, each with the qwen-agent-workspace/ prefix: story_engine.py, tests/fixtures/speaker_attribution/pin_sh2_plan_reply_1.txt, tests/test_speaker_attribution.py
git commit -m "feat(story): line_speakers reads who the narrative says speaks each line, and the planner is told (SA1, SA6, SAT1, SAT2, SAT9)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: P17 line speaker, retried by the plan call and fatal when the retries run out (SA2, SA3)

This task implements:
- SA2, the P17 block and the `plan_checks` docstring;
- SA3, `"P17"` in the fatal ids of `_Run.go`, with its two-line comment.

Tests: SAT3, SAT4, SAT5, SAT6, SAT10 and Review Focus 1-4.

**Files:**
- Modify: `story_engine.py`. The edits go in the `plan_checks` docstring (`:1365-1368`), before `undeclared = undeclared_characters(ctx)` (`:1514`), and in the fatal filter (`:3497-3498`).
- Modify: `tests/test_speaker_attribution.py` (append).

**Interfaces:**
- Consumes:
  - from Task 1: the test header and helpers, `line_speakers` and `LINE_SPEAKERS_SENTENCE`;
  - from `story_engine`: `normalize_plan(ctx, raw) -> (plan, shape)` (which runs `coerce_speakers`), `plan_checks(ctx, plan, shape=()) -> (hard, advisory)`, `parse_violation(text) -> dict`, `extract_json(text) -> dict or None`, `speaker_phrase_of(plan, cid)`, `_q`, `run(ctx) -> (rc, advisories)` and `recheck(ctx, legacy_validate) -> (rc, advisories)`;
  - from `story_engine_testutil`: `seu.MONK`.
- Produces:
  - `plan_checks` hard gains one `beat k: P17 line speaker: ...` message per (beat, line) whose attributed id differs from the beat's speaker. The messages come in beat order, then line order, after P16 and before the undeclared-character messages.
  - `_Run.go` treats P17 as fatal: exit 1, with the existing three-part stderr.
  - In the test module: `_p17(ctx, raw) -> [str]`, `_lines(raw, lines) -> raw`, `_bad(mode)`, `_corrected(mode)` and `SHOTS2_PANELS`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_sat3_p17_matrix`, `test_sat4_pin_sh2_fixture`, `test_sat5_e2e_exhausted`, `test_sat6_e2e_retry`, `test_sat10_back_compat_recheck`, `test_review_focus_1_an_exhausted_plan_lists_p16_then_every_p17`, `test_review_focus_2_a_speaker_written_as_a_name_is_checked_after_coercion`, `test_review_focus_3_a_quote_that_is_not_spoken_keeps_the_line_numbers`, `test_review_focus_4_an_invented_speaker_in_a_pinned_run`.

**1.1.** Edit `tests/test_speaker_attribution.py` (append): replace this text, the file's last lines, which occurs exactly once:

```python
    prompt, _rule = _plan_prompt(ws, mode="chained", members=members, narration=False,
                                 narrative=LINES_NARRATIVE)
    assert "The narrative gives these lines" not in prompt
```

with:

```python
    prompt, _rule = _plan_prompt(ws, mode="chained", members=members, narration=False,
                                 narrative=LINES_NARRATIVE)
    assert "The narrative gives these lines" not in prompt


# --- SAT3, SAT4: P17 line speaker (SA2, SK5) ---------------------------------------------------

def _p17(ctx, raw):
    """The P17 messages of plan_checks' hard list for the normalised raw reply."""
    plan, shape = se.normalize_plan(ctx, raw)
    return [m for m in se.plan_checks(ctx, plan, shape)[0] if " P17 " in m]


def _lines(raw, lines):
    """raw with beat k's lines set to lines[k - 1]; returns raw."""
    for beat, numbers in zip(raw["beats"], lines):
        beat["lines"] = list(numbers)
    return raw


def _bad(mode):
    """SAT3's plan that gives line 2 (Kyra's) to the ronin in beat 3."""
    if mode == "chained":
        raw = _raw("chained", 3, [["c1", "c2"]] * 3)
        raw["beats"][1].update(speaker="c1", lines=[1])
        raw["beats"][2].update(speaker="c2", lines=[2])
        return raw
    return _lines(_raw(mode, 3, [["c1"], ["c1"], ["c2"]], ["c1", "", "c2"]), [[1], [], [2]])


def _corrected(mode):
    """SAT3's corrected plan: both lines spoken by c1, the ronin on screen."""
    if mode == "chained":
        raw = _bad("chained")
        raw["beats"][2]["speaker"] = "c1"
        return raw
    return _lines(_raw(mode, 3, [["c1"], ["c2"], ["c1"]], ["c1", "", "c1"]), [[1], [], [2]])


def test_sat3_p17_matrix(ws, story_env):
    members = _members(story_env)
    want = [P17(3, 2, "Stay close to me.", "c1", KYRA, "c2", RONIN)]
    for mode in ("chained", "shots", "no_stills"):
        for narration in (True, "speech"):
            where = (mode, narration)
            ctx = seu.make_ctx(se, ws, mode=mode, panels=3, members=members, narration=narration,
                               narrative=LINES_NARRATIVE)
            found = _p17(ctx, _bad(mode))
            assert found == want, where
            v = se.parse_violation(found[0])
            assert (v["id"], v["name"], v["scope"], v["index"]) == (
                "P17", "line speaker", "beat", 3), where
            assert _p17(ctx, _corrected(mode)) == [], where
            pronoun = seu.make_ctx(se, ws, mode=mode, panels=3, members=members,
                                   narration=narration, narrative=PRONOUN_NARRATIVE)
            assert _p17(pronoun, _bad(mode)) == [], where
            uncast = seu.make_ctx(se, ws, mode=mode, panels=3, narration=narration,
                                  narrative=MONK_NARRATIVE)
            raw = _lines(seu.plan_json(mode, 3), [[1], [], []])
            raw["beats"][0]["speaker"] = "c1"
            assert _p17(uncast, raw) == [
                P17(1, 1, "Enter.", "c2", "the old monk", "c1", "the courier")], where
            raw["beats"][0].update(cast=["c2"], speaker="c2")
            assert _p17(uncast, raw) == [], where
        silent = seu.make_ctx(se, ws, mode=mode, panels=3, members=members, narration=False,
                              narrative=LINES_NARRATIVE)
        assert _p17(silent, _bad(mode)) == [], mode


def test_sat4_pin_sh2_fixture(ws, story_env):
    with open(FIX, "rb") as f:
        assert hashlib.sha256(f.read()).hexdigest() == FIX_SHA256
    ctx = _shots2(ws, story_env)
    plan, shape = se.normalize_plan(ctx, se.extract_json(_fix_text()))
    assert se.plan_checks(ctx, plan, shape)[0] == [
        P17(2, 2, "Stay close to me.", "c1", KYRA, "c2", RONIN)]


# --- SAT5, SAT6, SAT10: the plan retry, the fatal exit and the re-check (SA3, SK6, SK9) -------

SHOTS2_PANELS = {"1": [seu.answer(seu.panel_json("shots", 1, KYRA))],
                 "2": [seu.answer(seu.panel_json("shots", 2, RONIN))]}


def test_sat5_e2e_exhausted(ws, tmp_path, monkeypatch, capsys, story_env):
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(_fix_text())] * 2)
    ctx = _shots2(ws, story_env, story_id="sa1")
    capsys.readouterr()
    rc, _advisories = se.run(ctx)
    assert rc == 1
    assert [r["stage"] for r in seu.agent_log(log)] == ["plan", "plan"]
    assert capsys.readouterr().err == _fatal_err(
        [P17(2, 2, "Stay close to me.", "c1", KYRA, "c2", RONIN)], ctx)
    for name in ("story.md", "plan.json"):
        assert not os.path.exists(os.path.join(ctx.story_dir, name)), name


def test_sat6_e2e_retry(ws, tmp_path, monkeypatch, story_env):
    bad = json.loads(_fix_text())
    good = copy.deepcopy(bad)
    good["beats"][0]["lines"] = [1, 2]
    good["beats"][1].update(speaker="", lines=[])
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(bad), seu.answer(good)],
                           panel=SHOTS2_PANELS)
    ctx = _shots2(ws, story_env, story_id="sa2")
    rc, _advisories = se.run(ctx)
    log = seu.agent_log(log)
    assert rc == 0
    assert [r["stage"] for r in log] == ["plan", "plan", "panel", "panel"]
    assert ("YOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- "
            + P17(2, 2, "Stay close to me.", "c1", KYRA, "c2", RONIN) + "\n") in log[1]["argv"][-1]
    plan = _read_json(ctx.story_dir, "plan.json")
    assert [(b["cast"], b["speaker"], b["lines"]) for b in plan["beats"]] == [
        (["c1"], "c1", [1, 2]), (["c2"], "", [])]
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        dialogue = [line for line in f.read().splitlines() if line.startswith("Dialogue: ")]
    assert dialogue == [
        "Dialogue: the woman in grey: We reach the gate before dark. Stay close to me."]
    assert _read_json(ctx.story_dir, "story_checks.json")["hard"] == []
    with open(os.path.join(ctx.story_dir, "story_rounds", "round_0", "plan_prompt.txt"),
              encoding="utf-8") as f:
        assert (se.LINES_PINNED_SENTENCE + SENTENCE("line 1 to c1 and line 2 to c1")
                + "\nloras: ") in f.read()


def test_sat10_back_compat_recheck(ws, tmp_path, monkeypatch, story_env):
    rc, ctx, _log = _pt16_run(ws, tmp_path, monkeypatch, story_env)
    assert rc == 0
    plan = _read_json(ctx.story_dir, "plan.json")
    plan["beats"][2]["speaker"] = "c2"
    with open(os.path.join(ctx.story_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)

    def refuse(*args, **kwargs):
        raise AssertionError("recheck must not call plan_checks or line_speakers")

    monkeypatch.setattr(se, "plan_checks", refuse)
    monkeypatch.setattr(se, "line_speakers", refuse)
    rc, _advisories = se.recheck(ctx, lambda path, panels, no_stills=False: [])
    assert rc == 0
    checks = _read_json(ctx.story_dir, "story_checks.json")
    assert checks["hard"] == []
    assert [e["message"] for e in checks["hard"] + checks["advisory"]
            if " P17 " in e["message"]] == []


# --- Review Focus 1-4: the inputs most likely to reach a real run first (SA2, SA3) ------------

def test_review_focus_1_an_exhausted_plan_lists_p16_then_every_p17(ws, tmp_path, monkeypatch,
                                                                    capsys, story_env):
    raw = _lines(_raw("shots", 2, [["c2"], ["c2"]], ["c2", ""]), [[1, 2], []])
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(raw)] * 2)
    ctx = _shots2(ws, story_env, story_id="sa3")
    capsys.readouterr()
    rc, _advisories = se.run(ctx)
    assert rc == 1
    assert [r["stage"] for r in seu.agent_log(log)] == ["plan", "plan"]
    p16 = ("plan: P16 cast presence: c1 'the woman in grey' (library character kyra) is in no "
           "beat's cast; every already-cast character must be on screen, so put c1 in the cast "
           "of at least one beat; a beat with a speaker shows only the speaker, so that beat has "
           "no speaker or c1 is its speaker")
    assert capsys.readouterr().err == _fatal_err(
        [p16, P17(1, 1, "We reach the gate before dark.", "c1", KYRA, "c2", RONIN),
         P17(1, 2, "Stay close to me.", "c1", KYRA, "c2", RONIN)], ctx)
    for name in ("story.md", "plan.json"):
        assert not os.path.exists(os.path.join(ctx.story_dir, name)), name


def test_review_focus_2_a_speaker_written_as_a_name_is_checked_after_coercion(ws, story_env):
    ctx = seu.make_ctx(se, ws, mode="shots", panels=3, members=_members(story_env),
                       narration="speech", narrative=LINES_NARRATIVE)
    raw = _lines(_raw("shots", 3, [["c1"], ["c2"], ["c2"]], ["Kyra", "", "RONIN"]),
                 [[1], [], [2]])
    assert _p17(ctx, raw) == [P17(3, 2, "Stay close to me.", "c1", KYRA, "c2", RONIN)]
    raw["beats"][2].update(cast=["c1"], speaker="The Woman in Grey")
    plan, shape = se.normalize_plan(ctx, raw)
    assert [(b["speaker"], b["lines"]) for b in plan["beats"]] == [
        ("c1", [1]), ("", []), ("c1", [2])]
    assert se.plan_checks(ctx, plan, shape)[0] == []


def test_review_focus_3_a_quote_that_is_not_spoken_keeps_the_line_numbers(ws, story_env):
    members = _members(story_env)
    narrative = 'A sign reads "Closed". Kyra says, “Go.” The ronin says, "Fine."'
    assert se.spoken_lines(narrative) == ["Go.", "Fine."]
    assert se.line_speakers(narrative, CAST3) == ["c1", "c2"]
    ctx = seu.make_ctx(se, ws, mode="chained", panels=3, members=members, narrative=narrative)
    assert SENTENCE("line 1 to c1 and line 2 to c2") in se.build_plan_prompt(ctx, [], [])
    raw = _raw("chained", 3, [["c1", "c2"]] * 3)
    raw["beats"][1].update(speaker="c1", lines=[1])
    raw["beats"][2].update(speaker="c1", lines=[2])
    assert _p17(ctx, raw) == [P17(3, 2, "Fine.", "c2", RONIN, "c1", KYRA)]
    raw["beats"][2]["speaker"] = "c2"
    assert _p17(ctx, raw) == []


def test_review_focus_4_an_invented_speaker_in_a_pinned_run(ws, story_env):
    members = _members(story_env)
    narrative = 'Kyra says, "Go." The old monk says, "Enter."'
    ctx = seu.make_ctx(se, ws, mode="chained", panels=3, members=members, narrative=narrative)
    prompt = se.build_plan_prompt(ctx, [], [])
    assert SENTENCE("line 1 to c1") in prompt and "line 2 to" not in prompt
    raw = _raw("chained", 3, [["c1", "c2"], ["c1", "c3"], ["c1", "c2"]])
    raw["cast"].append({"id": "c3", "phrase": "the old monk", "descriptor": seu.MONK})
    raw["beats"][0].update(speaker="c1", lines=[1])
    raw["beats"][1].update(speaker="c1", lines=[2])
    assert _p17(ctx, raw) == [P17(2, 2, "Enter.", "c3", "the old monk", "c1", KYRA)]
    raw["beats"][1].update(cast=["c3"], speaker="c3")
    assert _p17(ctx, raw) == []
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_speaker_attribution.py 2>&1 | grep -E '^FAILED|passed|failed'
```

Expected: `8 failed, 4 passed`. There is no P17 message yet, so:
- SAT3 fails with `AssertionError: ('chained', True)` (`[] == ['beat 3: P17...']`).
- SAT4, Review Focus 2, 3 and 4 fail with an `AssertionError` (`[] == ['beat ...: P17...']`). Review Focus 3 passes its extraction and prompt asserts first.
- SAT5 fails on the stage list (`['plan', 'panel', 'panel'] == ['plan', 'plan']`), and SAT6 does too (`['plan', 'panel', 'panel'] == ['plan', 'plan', 'panel', 'panel']`). In both, the first reply is accepted.
- Review Focus 1 fails on the stderr. The run already exits 1 on P16, but the two P17 lines are missing.

SAT10 passes already: it pins the unchanged `recheck`. Task 1's three tests pass.

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py` (SA2, the docstring): replace this text, which occurs exactly once:

```python
    normalize_plan's container-shape P2 violations, reported first. Hard: P1, P2, P3's normalize
    and duplicate-phrase messages, and P16 (a library character in no beat's cast; pinned cast
    presence spec PC1); every other P message is advisory (dialogue spec 6.3)."""
```

with:

```python
    normalize_plan's container-shape P2 violations, reported first. Hard: P1, P2, P3's normalize
    and duplicate-phrase messages, P16 (a library character in no beat's cast; pinned cast
    presence spec PC1) and P17 (a spoken line given to a speaker other than the one the narrative
    names; speaker attribution spec SA2); every other P message is advisory (dialogue spec
    6.3)."""
```

**3.2.** Edit `story_engine.py` (SA2, the check): replace this text, which occurs exactly once:

```python
            hard.append(message)
    undeclared = undeclared_characters(ctx)
```

with:

```python
            hard.append(message)
    # Speaker attribution spec SA2, D3: a spoken line keeps the speaker the narrative names.
    if plan["spoken_lines"]:
        said_by = line_speakers(ctx.narrative, plan["cast"])
        for k, beat in enumerate(beats, start=1):
            for n in beat["lines"]:
                want = said_by[n - 1]
                if want and beat["speaker"] != want:
                    hard.append(
                        "beat %d: P17 line speaker: the narrative gives spoken line %d \"%s\" to "
                        "%s %s, but this beat's speaker is %s %s; put line %d in the lines of a "
                        "beat whose speaker is %s (consecutive lines may share a beat), and never "
                        "give it to another character"
                        % (k, n, plan["spoken_lines"][n - 1], want,
                           _q(speaker_phrase_of(plan, want)), beat["speaker"],
                           _q(speaker_phrase_of(plan, beat["speaker"])), n, want))
    undeclared = undeclared_characters(ctx)
```

**3.3.** Edit `story_engine.py` (SA3): replace this text, which occurs exactly once:

```python
        # Pinned cast presence spec PC2: a plan that drops a library character is not usable.
        fatal = ([h for h in found[2] if parse_violation(h)["id"] in ("P1", "P2", "P16")]
```

with:

```python
        # Pinned cast presence spec PC2, speaker attribution spec SA3: a plan that drops a library
        # character or gives a spoken line to the wrong speaker is not usable.
        fatal = ([h for h in found[2] if parse_violation(h)["id"] in ("P1", "P2", "P16", "P17")]
```

Nothing else in `plan_checks` or `go()` changes.

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_speaker_attribution.py tests/test_story_engine.py tests/test_dialogue.py tests/test_narrative_fidelity.py tests/test_writer_pacing.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_casting_pipeline.py tests/test_iterate_story.py tests/test_pinned_cast.py tests/test_judge_story.py tests/test_ltx_story_manifest_chain.py tests/test_character_lib.py 2>&1 | grep -E '^FAILED|passed|failed'
```

Expected output:
- one `FAILED` line, `tests/test_story_engine.py::test_rst62_import_sets` (the known failure);
- then `1 failed, 508 passed, 1 skipped`, which is Task 1's count plus 9.

These pass unchanged: `test_rst10` and `test_rst11` (the existing fatal-plan stderr), `test_pinned_cast.py`'s PT14, PT15, PT16, PT18 and Review Focus 1, and every NF test that runs `plan_checks` (whose narratives attribute nothing to a cast phrase).

Then run the compile check with `FILES` = `story_engine.py tests/test_speaker_attribution.py`. Expected: `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_speaker_attribution.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_speaker_attribution.py
git commit -m "feat(story): a plan that gives a quoted line to the wrong speaker is retried, then fatal (P17 line speaker; SA2, SA3, SAT3-SAT6, SAT10)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The pipeline never misattributes: assign_missing_lines and the Q1 dialogue patch (SA4, SA5), and the [PCP] amendment line

This task implements:
- SA4, the `said_by` line, the skip and the docstring sentence;
- SA5, the guard and the docstring sentence;
- spec 6 step 8, the amendment line in [PCP].

Tests: SAT7, SAT8 and Review Focus 5.

**Files:**
- Modify: `story_engine.py`. The edits go in the `assign_missing_lines` docstring (`:1097-1104`), after `cast_ids = ...` (`:1109`), after the eligibility `continue` (`:1122-1124`), in the `q1_dialogue_patch` docstring (`:2888-2895`), and after the "never changes who speaks" return (`:2917-2919`).
- Modify: `docs/superpowers/specs/2026-10-27-pinned-cast-presence-design.md` (after Amendment bullet A4, the file's last line).
- Modify: `tests/test_speaker_attribution.py` (append).

**Interfaces:**
- Consumes:
  - from Tasks 1 and 2: the test header and helpers, `_lines`, `SHOTS2_PANELS`, `line_speakers` and P17;
  - from `story_engine`: `assign_missing_lines(ctx, plan) -> [note]`, `q1_dialogue_patch(ctx, lib, plan, parts, k, replacement) -> (matched, problem)`, `empty_parts(mode, k, plan, ctx=None)` and `run(ctx)`.
- Produces:
  - `assign_missing_lines` keeps its signature. It never gives a line whose `line_speakers` entry is an id to a beat whose speaker, or whose sole cast member when it has no speaker, is another id.
  - `q1_dialogue_patch` keeps its signature. It returns `(True, "the narrative gives spoken line %d to %s, so a spoken-line patch never gives it to %s")` for such a patch, and changes nothing.
  - In the test module: `ASSIGNED` and `_sat7_plan(ws, story_env, narrative) -> (ctx, plan)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_sat7_assign_missing_lines`, `test_sat8_q1_dialogue_patch`, `test_review_focus_5_the_pin_sh2_shape_with_line_2_left_out`.

**1.1.** Edit `tests/test_speaker_attribution.py` (append): replace this text, the file's last lines, which occurs exactly once:

```python
    raw["beats"][1].update(cast=["c3"], speaker="c3")
    assert _p17(ctx, raw) == []
```

with:

```python
    raw["beats"][1].update(cast=["c3"], speaker="c3")
    assert _p17(ctx, raw) == []


# --- SAT7, SAT8, Review Focus 5: the pipeline never misattributes (SA4, SA5, SK7) -------------

ASSIGNED = ("beat %d: P14 speaking beat: line 2 given to this beat by the pipeline, because the "
            "plan gave it to no beat")


def _sat7_plan(ws, story_env, narrative):
    """(ctx, plan) of SAT7: shots, 3 panels, kyra and ronin pinned, --speech-only, beats cast
    [c1], [c2], [c1], beat 1 spoken by c1 with line 1, line 2 in no beat; normalised only."""
    ctx = seu.make_ctx(se, ws, mode="shots", panels=3, members=_members(story_env),
                       narration="speech", narrative=narrative)
    raw = _lines(_raw("shots", 3, [["c1"], ["c2"], ["c1"]], ["c1", "", ""]), [[1], [], []])
    return ctx, se.normalize_plan(ctx, raw)[0]


def test_sat7_assign_missing_lines(ws, story_env):
    ctx, plan = _sat7_plan(ws, story_env, LINES_NARRATIVE)
    assert se.assign_missing_lines(ctx, plan) == [ASSIGNED % 3]
    assert [(b["speaker"], b["lines"]) for b in plan["beats"]] == [
        ("c1", [1]), ("", []), ("c1", [2])]
    assert [m for m in se.plan_checks(ctx, plan)[0] if " P17 " in m] == []
    ctx, plan = _sat7_plan(ws, story_env, PRONOUN_NARRATIVE)
    notes = se.assign_missing_lines(ctx, plan)
    assert [(b["speaker"], b["lines"]) for b in plan["beats"]] == [
        ("c1", [1]), ("c2", [2]), ("", [])]
    assert notes[0] == ASSIGNED % 2


def test_sat8_q1_dialogue_patch(ws, story_env):
    ctx, plan = _sat7_plan(ws, story_env, LINES_NARRATIVE)
    fresh = copy.deepcopy(plan)
    parts = [se.empty_parts("shots", k, plan, ctx) for k in (1, 2, 3)]
    assert se.q1_dialogue_patch(ctx, lib, plan, parts, 2, "the ronin: Stay close to me.") == (
        True, "the narrative gives spoken line 2 to 'the woman in grey', so a spoken-line patch "
              "never gives it to 'the ronin'")
    assert (plan["beats"][1]["speaker"], plan["beats"][1]["lines"]) == ("", [])
    parts = [se.empty_parts("shots", k, fresh, ctx) for k in (1, 2, 3)]
    assert se.q1_dialogue_patch(ctx, lib, fresh, parts, 3,
                                "the woman in grey: Stay close to me.") == (True, None)
    ctx, plan = _sat7_plan(ws, story_env, PRONOUN_NARRATIVE)
    parts = [se.empty_parts("shots", k, plan, ctx) for k in (1, 2, 3)]
    assert se.q1_dialogue_patch(ctx, lib, plan, parts, 2, "the ronin: Stay close to me.") == (
        True, None)


def test_review_focus_5_the_pin_sh2_shape_with_line_2_left_out(ws, tmp_path, monkeypatch,
                                                               story_env):
    raw = _lines(_raw("shots", 2, [["c1"], ["c2"]], ["c1", ""]), [[1], []])
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(raw)] * 2,
                           panel=SHOTS2_PANELS)
    ctx = _shots2(ws, story_env, story_id="sa4")
    rc, _advisories = se.run(ctx)
    assert rc == 0
    assert [r["stage"] for r in seu.agent_log(log)] == ["plan", "plan", "panel", "panel"]
    plan = _read_json(ctx.story_dir, "plan.json")
    assert [(b["cast"], b["speaker"], b["lines"]) for b in plan["beats"]] == [
        (["c1"], "c1", [1, 2]), (["c2"], "", [])]
    assert ASSIGNED % 1 in plan["speech_notes"]
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        dialogue = [line for line in f.read().splitlines() if line.startswith("Dialogue: ")]
    assert dialogue == [
        "Dialogue: the woman in grey: We reach the gate before dark. Stay close to me."]
    assert _read_json(ctx.story_dir, "story_checks.json")["hard"] == []
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_speaker_attribution.py 2>&1 | grep -E '^FAILED|passed|failed'
```

Expected: `3 failed, 12 passed`.
- SAT7 fails on the notes. Line 2 goes to beat 2, so the notes are `beat 2: P14 speaking beat: line 2 given to this beat ...` plus a shot note.
- SAT8 fails with `(True, None) == (True, "the narrative gives spoken line 2 ...")`.
- Review Focus 5 fails with `assert 2 == 0`. Line 2 goes to the ronin's beat, and the story-end check then reports P17 (exit 2).

Tasks 1 and 2's twelve tests pass.

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py` (SA4, the docstring): replace this text, which occurs exactly once:

```python
    spoken line), so the result does not depend on the order lines are tried."""
```

with:

```python
    spoken line), so the result does not depend on the order lines are tried. A line the
    narrative gives to a named speaker (speaker attribution spec SA4) goes only to a beat whose
    speaker, or sole cast member, is that speaker."""
```

**3.2.** Edit `story_engine.py` (SA4, the attribution): replace this text, which occurs exactly once:

```python
    cast_ids = [c["id"] for c in plan["cast"]]
    holder = dict((n, k) for k, beat in enumerate(beats, start=1) for n in beat["lines"])
```

with:

```python
    cast_ids = [c["id"] for c in plan["cast"]]
    said_by = line_speakers(ctx.narrative, plan["cast"])
    holder = dict((n, k) for k, beat in enumerate(beats, start=1) for n in beat["lines"])
```

**3.3.** Edit `story_engine.py` (SA4, the skip): replace this text, which occurs exactly once:

```python
                        or (len(beat["cast"]) == 1 and beat["cast"][0] in cast_ids)):
                    continue
                lines = sorted(beat["lines"] + [n])
```

with:

```python
                        or (len(beat["cast"]) == 1 and beat["cast"][0] in cast_ids)):
                    continue
                if said_by[n - 1] and (beat["speaker"] or beat["cast"][0]) != said_by[n - 1]:
                    continue
                lines = sorted(beat["lines"] + [n])
```

**3.4.** Edit `story_engine.py` (SA5, the docstring): replace this text, which occurs exactly once:

```python
    panel's spoken lines, adds only adjacent ones, and never rewrites other Dialogue words."""
```

with:

```python
    panel's spoken lines, adds only adjacent ones, and never rewrites other Dialogue words. A
    patch that gives a line to a speaker other than the one the narrative names is rejected
    (speaker attribution spec SA5)."""
```

**3.5.** Edit `story_engine.py` (SA5, the guard): replace this text, which occurs exactly once:

```python
        return True, ("panel %d's speaker is %s; a spoken-line patch never changes who speaks"
                      % (k, _q(beat["speaker"])))
```

with:

```python
        return True, ("panel %d's speaker is %s; a spoken-line patch never changes who speaks"
                      % (k, _q(beat["speaker"])))
    said_by = line_speakers(ctx.narrative, plan["cast"])
    for n in range(i, j + 1):
        if said_by[n - 1] and said_by[n - 1] != sid:
            return True, ("the narrative gives spoken line %d to %s, so a spoken-line patch never "
                          "gives it to %s" % (n, _q(speaker_phrase_of(plan, said_by[n - 1])),
                                              _q(speaker_phrase_of(plan, sid))))
```

**3.6.** Edit `docs/superpowers/specs/2026-10-27-pinned-cast-presence-design.md` (spec 6 step 8, the [PCP] amendment line): replace this text, which occurs exactly once:

```text
- **A4 (known limit).** Under `--speech-only` the chained beat-1 widening to "medium shot" applies only to shots wider than the ones offered, so a chained beat-1 close-up with a silent co-star stays a close-up (PT10 pins this). PK10 records the beat-1 shot of the chained runs.
```

with:

```text
- **A4 (known limit).** Under `--speech-only` the chained beat-1 widening to "medium shot" applies only to shots wider than the ones offered, so a chained beat-1 close-up with a silent co-star stays a close-up (PT10 pins this). PK10 records the beat-1 shot of the chained runs.
- **A5 (2026-10-28, speaker attribution spec SA4).** A2 closed by speaker attribution spec SA4 for lines the narrative attributes; unattributed lines unchanged.
```

Nothing else in `assign_missing_lines`, `q1_dialogue_patch` or the [PCP] spec changes.

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_speaker_attribution.py tests/test_story_engine.py tests/test_dialogue.py tests/test_narrative_fidelity.py tests/test_writer_pacing.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_casting_pipeline.py tests/test_iterate_story.py tests/test_pinned_cast.py tests/test_judge_story.py tests/test_ltx_story_manifest_chain.py tests/test_character_lib.py 2>&1 | grep -E '^FAILED|passed|failed'
```

Expected output:
- one `FAILED` line, `tests/test_story_engine.py::test_rst62_import_sets` (the known failure);
- then `1 failed, 511 passed, 1 skipped`, which is Task 2's count plus 3.

These pass unedited: `test_narrative_fidelity.py::test_nf37_assign_missing_lines`, `test_nf24_the_q1_dialogue_patch` and every other NF test of `assign_missing_lines`, Q1 and `apply_patches` (spec 4.2). So do `test_pinned_cast.py`'s PT16 and `test_final_i1`.

Then run the compile check with `FILES` = `story_engine.py tests/test_speaker_attribution.py`. Expected: `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_speaker_attribution.py docs/superpowers/specs/2026-10-27-pinned-cast-presence-design.md
git diff --cached --name-only    # expected: qwen-agent-workspace/docs/superpowers/specs/2026-10-27-pinned-cast-presence-design.md, qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_speaker_attribution.py
git commit -m "feat(story): the pipeline's line placement and the critic's line patches keep the narrative's speaker (SA4, SA5, SAT7, SAT8)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Design review, the test_mut26 re-baseline (test-only commit), SK1-SK9 and the SK10 hand-off

This task implements spec 6 steps 4-6 (G4). It measures SK1, SK2 and SK3, the unchanged files and the verbatim spec blocks. It hands SK10 (the live runs, spec 5 and 6 step 7) and the PR note to the controller; see "Post-implementation: live checks". No production code changes in this task.

**Files:**
- Modify: `tests/test_movie_ui_builder.py` (`test_mut26_pipeline_files_are_unchanged` `:283-285`). The change is spec G4: "`BASELINE` re-baseline ... The comment gains `, then to <sha> (speaker attribution).`"

**Interfaces:**
- Consumes: the commits of Tasks 1-3.
- Produces: the final pass counts in `$S/sa-baseline/final-pytest.txt`.

- [ ] **Step 1: Design review (controller; spec 6 step 5).** Ask an Opus `design-reviewer` to review `git diff 76bff8a..HEAD -- qwen-agent-workspace` against the spec and this plan. Fix every finding in a new commit on the owning task's files before Step 2, then re-run that task's Step 4.

- [ ] **Step 2: Find the last pipeline commit.**

Run this command:

```bash
git log -1 --format='%H %s' -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py
```

Expected: one line. It is a 40-character SHA, then the subject of Task 3's commit, `feat(story): the pipeline's line placement and the critic's line patches keep the narrative's speaker (SA4, SA5, SAT7, SAT8)`. It is the Step 1 fix commit instead if that commit touched a `PIPELINE_FILES` entry. In Steps 3 and 4, **SHA** means exactly those 40 characters, typed in place of the word `SHA`. That is the only text in this plan that comes from a command's output.

- [ ] **Step 3: Re-baseline test_mut26 to that commit (spec G4).**

**3.1.** Edit `tests/test_movie_ui_builder.py` (the comment): replace this text, which occurs exactly once:

```python
then to 05ba1792b7e1620f96b1e50ba5a83f6349620529 (pinned cast presence).
```

with this text, where `SHA` is the Step 2 value:

```python
then to 05ba1792b7e1620f96b1e50ba5a83f6349620529 (pinned cast presence), then to SHA (speaker attribution).
```

**3.2.** Edit `tests/test_movie_ui_builder.py` (the baseline): replace this text, which occurs exactly once:

```python
    BASELINE = "05ba1792b7e1620f96b1e50ba5a83f6349620529"
```

with this text, where `SHA` is the Step 2 value:

```python
    BASELINE = "SHA"
```

**3.3.** Run this command:

```bash
SHA=$(git log -1 --format=%H -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py)
grep -c "$SHA" tests/test_movie_ui_builder.py
grep -c "05ba1792b7e1620f96b1e50ba5a83f6349620529" tests/test_movie_ui_builder.py
grep -c "(pinned cast presence), then to $SHA (speaker attribution)." tests/test_movie_ui_builder.py
grep -c "    BASELINE = \"$SHA\"" tests/test_movie_ui_builder.py
git diff --numstat -- tests/test_movie_ui_builder.py
python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py -k mut26 2>&1 | tail -1
```

Expected output, in order:
- `2`, `1` (the kept "pinned cast presence" item), `1` and `1`;
- `2	2	qwen-agent-workspace/tests/test_movie_ui_builder.py`;
- `1 passed, 11 deselected` in the summary line.

If any value differs, fix the Edit, not this command.

- [ ] **Step 4: Commit (test-only; spec 0.4 G4).**

```bash
git add tests/test_movie_ui_builder.py
git diff --cached --name-only    # expected: only qwen-agent-workspace/tests/test_movie_ui_builder.py
git commit -m "test(movie-ui): re-baseline mut26 to the speaker attribution pipeline commit" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: SK1, the full suite against the baseline (about 15 minutes).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/sa-baseline
python3 -m pytest tests/ -q -rA -p no:cacheprovider > $D/final-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt; tail -1 $D/final-pytest.txt
diff <(grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt | sed 's/ - .*//' | sort) <(grep -E '^(FAILED|ERROR)' $D/final-pytest.txt | sed 's/ - .*//' | sort) && echo "same failures"
diff <(grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt | sort) <(grep -E '^(FAILED|ERROR)' $D/final-pytest.txt | sort) && echo "same failure messages"
python3 tests/test_ltx_movie_offline.py 2>&1 | tail -1; cat $D/baseline-offline.txt
diff <(grep -E '^PASSED' $D/baseline-pytest.txt | sort) <(grep -E '^PASSED' $D/final-pytest.txt | sort) | grep '^<' || echo "no lost pass"
grep -c '^PASSED tests/test_speaker_attribution.py::' $D/final-pytest.txt
```

Expected:
- The final summary is `2 failed, 1879 passed, 2 skipped`: the baseline's `2 failed, 1864 passed, 2 skipped` plus the 15 new tests.
- `same failures` and `same failure messages` print, for exactly `test_d2_copied_literals_match_the_spike` and `test_rst62_import_sets`, unchanged in number and message (SK1).
- The passed count is the baseline's plus 15, the functions of `tests/test_speaker_attribution.py` (SAT1-SAT10 and Review Focus 1-5). Add 1 if `test_trt41a` failed in the baseline run only; if it fails here instead, rerun it alone.
- The skipped count is unchanged.
- The offline script prints `OK 347/347`, the same as `baseline-offline.txt`.
- The diff prints `no lost pass`, and the last command prints `15`.

Any other difference: stop and report.

- [ ] **Step 6: SK2, SK3, the unchanged files and the verbatim spec text.**

```bash
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' story_engine.py tests/test_speaker_attribution.py tests/test_movie_ui_builder.py; done
git diff e254e65 -- story_engine.py | grep -E '^[+-]\s*(import|from) ' || echo "no import change"
git diff --name-only e254e65 -- character_lib.py bin movie_ui_lib.py static | wc -l
git diff --name-only e254e65 -- . ':(exclude)docs' | sed 's#^qwen-agent-workspace/##' | grep -v -E '^(story_engine\.py|tests/test_speaker_attribution\.py|tests/test_movie_ui_builder\.py|tests/fixtures/speaker_attribution/pin_sh2_plan_reply_1\.txt)$' || echo "only the planned files"
git diff --numstat e254e65 -- docs/superpowers/specs/2026-10-27-pinned-cast-presence-design.md
git diff e254e65 -- story_engine.py tests/test_speaker_attribution.py | grep '^+' | grep -v '^+++' | awk 'length > 101' | wc -l
python3 - <<'EOF'
import re
spec = open("docs/superpowers/specs/2026-10-28-speaker-attribution-design.md", encoding="utf-8").read()
code = open("story_engine.py", encoding="utf-8").read()
blocks = re.findall(r"```python\n(.*?)```", spec, re.S)[:8]
print("%d of %d spec code blocks verbatim" % (sum(b in code for b in blocks), len(blocks)))
EOF
python3 -m pytest -q -p no:cacheprovider tests/test_pinned_cast.py tests/test_story_engine.py tests/test_narrative_fidelity.py -k "pt2 or pt5 or rst8 or rst10 or rst11 or rst61 or nf24 or nf37" 2>&1 | tail -1
```

Expected, in order:
- `compiled 3` twice (SK2);
- `no import change` (SK3);
- `0`, which `wc` may print with leading spaces (spec 0.4 "Not changed");
- `only the planned files`;
- `1	0	qwen-agent-workspace/docs/superpowers/specs/2026-10-27-pinned-cast-presence-design.md` (the one added A5 line);
- `0`, again possibly with leading spaces (no added line is longer than 100 columns);
- `8 of 8 spec code blocks verbatim` (SA1-SA6);
- then `9 passed, 162 deselected` in the summary line, with no failure (SK8: PT2, PT5, `test_rst8`; the fatal stderr: `test_rst10`, `test_rst11`; SK2: `test_rst61`; NF24, NF37).

- [ ] **Step 7: Hand-off (controller; not an executor step).** Run the live checks of "Post-implementation: live checks" below after the merge, and put the spec 6 PR note in the PR description.

---

## Post-implementation: live checks (controller; spec 5, SK10; this Mac only, story-only; not a task and not a merge gate)

These runs are for the controller or the user after the merge, never for an executor.
- They start the local story server, which loads a model and listens on `:8177`. That is outside every executor's rules, so it needs the user's own go-ahead.
- They run on this Mac only, never on macstudio or any other host.
- They are story-only: nothing renders.

Run them exactly as spec Section 5 writes them; the summary below is not a substitute for the spec text.

- **Setup.**
  - `R=$S/attrib` (new, empty), and `W` is the merged workspace on this Mac.
  - **First, archive the current artifacts:** `mkdir -p $R/pre && cp -Rp $W/generated/stories/pin-* $R/pre/`. The old `pin-sh2` is the only record of the defect and the source of G3.
  - Start the story server exactly as `start_llm` in `$S/pinned/run.sh` (vllm-metal `qwen38-6bit`, port 8177). Stop it with `bin/story-server stop` after the last run.
  - `N` is `LINES_NARRATIVE`.
- **Runs** (from `$W`, one after the other): the five `$S/pinned/run.sh` commands, `pin-ch3-a`, `pin-ch3-b`, `pin-sh4-a`, `pin-sh4-b` and `pin-sh2`, with their story ids and flags. Then one extra `pin-sh2-b`: the `pin-sh2` command with only the story id changed. Each log goes to `$R/run-<id>.log`.
- **Measure.**
  - Run `W=$W python3 -I $S/pinned/measure.py pin-ch3-a pin-ch3-b pin-sh4-a pin-sh4-b pin-sh2 pin-sh2-b > $R/measure.txt`.
  - Save spec 5's attribution script as `$R/measure_sa.py`, and run it with the same ids into `$R/measure_sa.txt`.
- **Pass criteria (spec 5 a-d):**
  - (a) Every run that exits 0 has `got == want` in `measure_sa.txt`, and every `speakers` entry in `measure.txt` is `the woman in grey`.
  - (b) The `pin-ch3` and `pin-sh4` runs exit 0 with `hard []`, and both members have non-empty `beats` and `panels`.
  - (c) `pin-sh2` exits 0, with both lines in one beat spoken by `c1` and the ronin in a beat with no speaker.
  - (d) Any exit-1 run prints the existing fatal stderr, listing only P16 or P17 problems.
  - If `pin-sh2` or `pin-sh2-b` exits 1, criterion c is a KPI miss to report to the user, not a contract failure (R1, approved). A run that exits 1 leaves the previous story's files in place, so its `measure.txt` lines are stale and are ignored.
- **Recorded, not gating:**
  - each run's plan-call count, `plan_reply_1.txt` and the retry prompt of any retried run;
  - whether the `pin-ch3`/`pin-sh4` prompts carry `line 1 to c1 and line 2 to c1`;
  - the diff of new against old `pin-sh2` `plan_prompt.txt`, which must be exactly the inserted `LINE_SPEAKERS_SENTENCE`.
- Put the exit codes, `measure.txt` and `measure_sa.txt` in the report, with the spec 6 PR note.

---

## Coverage

### Spec section to task

| Spec | Task(s) |
|---|---|
| 0.4 G1 (`story_engine.py`) | 1 (SA1, SA6), 2 (SA2, SA3), 3 (SA4, SA5) |
| 0.4 G2 (`tests/test_speaker_attribution.py`) | 1, 2, 3 |
| 0.4 G3 (the fixture) | 1 step 1.1 |
| 0.4 G4 (`test_mut26`) | 4 steps 2-4 |
| 0.4 Not changed | 4 step 6 (the `git diff` checks and the verbatim-block check); SAT1 (the constants); `test_pinned_cast.py` PT1 (the kept `LINES_RULE`, `LINES_PINNED_SENTENCE` and `SPEAKER_RULE` text) in every Step 4 run |
| 0.5 Out of scope | nothing is built for it; SAT2's pronoun rows and SAT3's pronoun plans pin the no-constraint behaviour |
| 0.6 SK1 | Before Task 1 (baseline), 4 step 5 |
| 0.6 SK2, SK3 | every task's compile check; `test_rst61` in each Step 4; 4 step 6 |
| 0.6 SK4 | 1 (SAT2) |
| 0.6 SK5 | 2 (SAT3, SAT4) |
| 0.6 SK6 | 2 (SAT5, SAT6) |
| 0.6 SK7 | 3 (SAT7, SAT8) |
| 0.6 SK8 | 1 (SAT9; PT2 and `test_rst8` unedited in Step 4) |
| 0.6 SK9 | 2 (SAT10) |
| 0.6 SK10 | Post-implementation: live checks |
| D1, D2 | 1 (SA1; SAT2) |
| D3 | 2 (SA2, SA3) |
| D4 | 3 (SA4, SA5; Review Focus 5 shows that P17 never fires on an accepted plan) |
| D5 | 1 (SA6; SAT9) |
| D6 | 2 (SAT10); `recheck` unchanged |
| D7 | 1-3 (the names); SAT3 (`parse_violation` of P17) |
| SA1 | 1 step 3.1 |
| SA2 | 2 steps 3.1, 3.2 |
| SA3 | 2 step 3.3 |
| SA4 | 3 steps 3.1-3.3 |
| SA5 | 3 steps 3.4, 3.5 |
| SA6 | 1 steps 3.2-3.4 |
| 3 interactions | plan retry and fatal exit: 2 (SAT5, SAT6, Review Focus 1); P16 together with P17: 2 (Review Focus 1); `assign_missing_lines`: 3 (SAT7, Review Focus 5); critic and `apply_patches`: 3 (SAT8); `make_state`: 2 (SAT6), 3 (Review Focus 5); `recheck`: 2 (SAT10); uncast runs: 1 (SAT9), 2 (SAT3); pinned runs with no member-attributed line: 1 (SAT9), 2 (SAT3); `--no-narration`: 1 (SAT9), 2 (SAT3); `--story-legacy`, `bin/*`, movie-ui: unchanged files (4 step 6) and the Step 4 suites |
| 4.1 | 1-3 (see the next table) |
| 4.2 | every task's Step 4 run; 4 steps 5, 6 |
| 5 | Post-implementation: live checks |
| 6 rollout | Before Task 1 (steps 1, 2: snapshot, baseline); 1 step 1.1 (step 2: fixture first); 1-3 (step 3: feature commits; step 8: the [PCP] line in Task 3); every Step 4 and 4 steps 5, 6 (step 4); 4 step 1 (step 5); 4 steps 2-5 (step 6); live checks (step 7) |

### Test IDs and their owning task (each is owned by exactly one task)

| IDs | Task |
|---|---|
| SAT1, SAT2, SAT9 | 1 |
| SAT3, SAT4, SAT5, SAT6, SAT10, Review Focus 1, 2, 3, 4 | 2 |
| SAT7, SAT8, Review Focus 5 | 3 |
| MUT26 re-baseline; SK1, SK2, SK3 and the unchanged files measured; SK10 hand-off | 4 |

### Self-review

- **Spec coverage.** Every requirement (SA1-SA6) and every SAT test (SAT1-SAT10) maps to exactly one task in the tables above. G1-G4 and the SK criteria each have a step. The spec's live checks (Section 5) are the post-implementation section, not a task.
- **Placeholder scan.** No step says "TBD", "similar to Task N" or "add appropriate handling". Every test and implementation block is the full code.
  - The only symbolic values are `$S`, `$WS`, `$D` and `$SHA`, each defined in its block or in the house rules.
  - The word `SHA` in Task 4 Step 3, which is the value Step 2 prints.
  - Every expected count is a number measured on the replay (see "Execution handoff").
- **Type consistency.**
  - `line_speakers(narrative, cast)` takes plan cast entries in SA2, SA4 and SA5, and `{"id", "phrase", "cast_name"}` dicts in SA6 and SAT2. Its result always has `len(spoken_lines(narrative))` entries, which SAT2 asserts for every row.
  - `_raw(mode, n, casts, speakers=None)` builds a reply from `CAST2` in every task.
  - `P17(k, n, line, want, want_phrase, got, got_phrase)` matches SA2's format, including the `_q` quotes.
  - `_lines(raw, lines)` returns its argument.
  - `_shots2(ws, story_env, **kw)` calls `_members`, so each test that uses it creates the test library's kyra and ronin.

## Plan decisions (where the spec is silent, conflicts with the task split, or needs a reading)

1. **Three feature commits instead of spec 6 step 3's single feature commit.** This is the task split, so a reviewer can accept the extractor with the planner text, the rule, and the guards separately. `test_mut26` is re-based to the last commit that touches a `PIPELINE_FILES` entry (Task 3's, or the Step 1 review fix), in its own test-only commit, after the design review (Task 4). This follows how `e254e65` re-based it to `05ba179`.
2. **SA6 is in Task 1, with SA1.** `LINE_SPEAKERS_SENTENCE` is the only consumer of `line_speakers` that needs no other new code, and SAT1 checks it together with the SA1 constants. So SAT1 is one test function in one task, and Task 2's SAT6 can assert the prompt sentence.
3. **The [PCP] amendment line (spec 6 step 8) is a new bullet A5**, appended after A4. It carries the spec's sentence word for word, and it goes into Task 3's commit, the one that implements SA4 and so closes A2. The bullet label `**A5 (2026-10-28, speaker attribution spec SA4).**` follows A1-A4's `**A<n> (...).**` form. The file is not a `PIPELINE_FILES` entry.
4. **All shared test helpers are in Task 1's header**: the spec 4.1 "Copied verbatim" list and its "Extra helpers" list, in one place.
   - `_read_json`, `_fatal_err` and `_pt16_run` are first used in Task 2. They are copied byte for byte from `tests/test_pinned_cast.py` (`:305-307`, `:310-314`, `:631-656`), including `_pt16_run`'s story id `pc5`.
   - The private helpers the spec leaves open are named `FIX_SHA256`, `_fix_text`, `_plan_prompt`, `_p17`, `_lines`, `_bad`, `_corrected`, `SHOTS2_PANELS`, `ASSIGNED` and `_sat7_plan`.
5. **Test readings.**
   - SAT3's uncast case runs inside the narration loop (`True` and `"speech"`). Like the bad plans, it compares the P17 messages only: "gives exactly" is read with SAT3's own `[m for m in ... if " P17 " in m]` filter.
   - SAT4 compares the whole hard list, as the spec writes it.
   - SAT9 uses `StoryContext`'s default narration (`True`) except for the `narration=False` row. `LINES_RULE` is filled the same way for either value.
   - SAT2 also asserts that the table has exactly 39 rows (SK4's count).
   - SAT6 and Review Focus 5 share `SHOTS2_PANELS`, the spec's panel replies. `script_agent` only serialises it, so sharing it is safe.
   - The story ids the spec leaves open are `sa3` (Review Focus 1) and `sa4` (Review Focus 5).
   - SAT10's replacement raises `AssertionError("recheck must not call plan_checks or line_speakers")` for both monkeypatched names.
6. **The fixture is copied with a plain `cp`**, which reads the main checkout and writes only into the worktree. There is a stated fallback to the spec author's archived copy (`$S/p17/ws/tests/fixtures/speaker_attribution/pin_sh2_plan_reply.txt`), whose sha256 matched G3 when this plan was written.
7. **The `test_mut26` re-baseline uses two Edit-tool steps** (the controller's "Edit tool, no rm" rule), not a rewrite script. The SHA from Step 2 is the only runtime value in the plan, and Step 3.3 checks it four ways.
8. **The Step 4 file list** is spec 0.3's measurement list without `tests/test_movie_ui_builder.py`, whose `test_mut26` fails until Task 4. It adds `tests/test_speaker_attribution.py`.
9. **`WS` is the worktree** (`$S/sa-wt/qwen-agent-workspace`), not the main checkout the spec names, per the controller's rule. Only the post-implementation live checks name the merged workspace, and the controller runs those.
10. **Two comment lines and two docstrings are wrapped at 100 columns**, with the spec's words unchanged: the SA2 `plan_checks` docstring, and the SA4 and SA5 docstring sentences. The spec gives their words but not their line breaks.

## Questions for controller

None. The spec has no open question (8.3). The user approved its three decisions to confirm (8.2: C1-C3) and its trade-offs (R1, R2, R3) as written.

## Spec defects found (for the spec author; none blocks this plan)

1. **Spec 0.3 says `$S/p17/ws` is "the scratch implementation of Section 2 exactly as written".** Its `story_engine.py` (`$S/p17/sa.diff`) differs from Section 2 in comments and docstrings only.
   - Three comments read differently: the `LINE_SPEAKERS_SENTENCE` comment says `SA6:`, not `SA6, D5:`; `_speaker_before`'s docstring says `forms B1-B3`, not `B1, B2`; and the P17 comment says `SA2:`, not `SA2, D3:`.
   - It also lacks the SA2, SA4 and SA5 docstring changes and the SA3 two-line comment.
   - Behaviour is identical. This plan follows Section 2, and Task 4 step 6 checks all 8 spec code blocks verbatim.
2. **SAT3's uncast case names no narration value**, and "gives exactly" can be read as either the whole hard list or the P17 messages (Plan decision 5). Both readings pass on the replayed tree; the plan uses the P17-filter reading, for symmetry with the bad plans.
3. **The G4 text "The comment gains `, then to <sha> (speaker attribution).`"** is applied, as [PCP] G5 was, by turning the comment's final `(pinned cast presence).` into `(pinned cast presence), then to <sha> (speaker attribution).` (Task 4 step 3.1).

## Execution handoff

Plan complete and saved to `qwen-agent-workspace/docs/superpowers/plans/2026-10-28-speaker-attribution.md`.

**How it was replayed.** A script read this file and ran every block of "Before Task 1" and Tasks 1-4 in order: every Run this command, Create, Edit and commit block, plus each Step 4's compile check. It ran on `$S/sa-rp1`, a `git clone --no-local` of `sa-wt` at `76bff8a` with this plan committed on top, so it had the real history for `test_mut26`.
- The only paths it changed were the replay's own: the clone, the baseline directory and the snapshot.
- The fixture was copied from the main checkout with the Step 1.1 `cp` (read only). Its sha256 was `4bd4d603998cca92c44c4d59295fb33318df3c486cf85b3c860d020b62da1374`, 1897 bytes. The fallback block was not needed.

**What it showed.**
- Each Edit's old text occurred exactly once at its turn.
- The Step 2 runs failed exactly as their Expected lines state: `3 failed`; `8 failed, 4 passed`; `3 failed, 12 passed`.
- The Step 4 runs each gave `1 failed` (`test_rst62_import_sets`), with `499`, `508` and `511 passed, 1 skipped`. The same files gave `496 passed` on the unchanged tree.
- Every changed file compiled under Python 3.9.6 and 3.13.
- Task 4 Step 2 found Task 3's commit. The Step 3 Edits and checks printed `2`, `1`, `1`, `1`, the `2	2` numstat and `1 passed, 11 deselected`.
- The full suite after the re-baseline gave `2 failed, 1879 passed, 2 skipped` (`same failures`, `same failure messages`, `no lost pass`, `15`), and the offline script printed `OK 347/347`.
- Step 6 printed `compiled 3` twice, `no import change`, `0`, `only the planned files`, the A5 numstat, `0`, `8 of 8 spec code blocks verbatim` and `9 passed, 162 deselected`.
- The replayed `story_engine.py` is byte-identical to a separate draft tree built from the same blocks. Behaviourally, it equals the spec author's scratch implementation (Spec defect 1).

Please review the plan. Which execution approach would you prefer?

- **Subagent-driven**: a fresh subagent implements each task and a fresh reviewer checks it before the next one starts, then a whole-branch review at the end.
- **Native**: one session implements every task, then one fresh reviewer checks the whole branch.

For this plan I recommend **subagent-driven**. Its three feature tasks have separate review questions: the extractor's conservatism and the planner text, the fatal-exit policy, and the pipeline guards. Each one has its own failing-test cycle.
