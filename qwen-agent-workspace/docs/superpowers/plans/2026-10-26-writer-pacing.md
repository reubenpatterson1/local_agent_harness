# Writer Pacing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tell the chained panel writer exactly where the pipeline speaks the line (one sentence before the dialogue and, only when the beat continues, one after it), ask every chained Motion for fast, concrete motion at real-time speed with named, big and bright effects, and give the critic's chained Motion patch line the same speech-point rule. Placement code, checks, the plan prompt and the shots and no_stills prompts stay as they are.

**Architecture:** Prompt text only, all in `story_engine.py`. A new `PACING_SENTENCE` replaces the [PACE1] sentence in `KEY_LINE_TEMPLATES["chained_motion1"]` and is added to `["chained_motion"]` (WP1). A new `SPEAKING_CHAINED_MOTION_SENTENCE` (WP2) is appended by `build_panel_prompt` to the motion key line of a chained speaking panel in place of `SPEAKING_ACTION_SENTENCE`, which shots keeps (WP3). A new `CRITIC_SPEAKING_MOTION_CLAUSE` ends the chained Motion patch line of `critic_field_lines(..., speaking=False)` when the plan has a speaking beat (WP4), and `build_critic_prompt` passes `speaking` (WP5), so `bin/judge-story --patches` inherits it with no edit. `character_lib.insert_speech` is not touched: the contract states what it already does.

**Tech Stack:** Python 3.13 (`python3` = `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`, pytest 8.3.4) and Python 3.9.6 (`/usr/bin/python3`, compile check only); standard library only; `tests/story_engine_testutil.py` (`make_ws`, `make_ctx`, `set_story_env`) and the `_story`/`_speaking` helpers, `LINE`, `MOTION_LINE` and `DIALOGUE_FIELD_LINE` of `tests/test_dialogue.py`; verbatim copies of the two recorded 2026-10-26 NK8 hockey runs as fixtures.

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-10-26-writer-pacing-design.md` (Section 8.3 "Open: None"). Every Edit below is written against commit `88213da` (branch `qwen-agent-redteam`), whose code tree is the one the spec cites; the `Files:` line numbers cite `88213da`, and every Edit finds its text by content. The spec is binding; this plan changes no design decision. The controller has ruled on the spec's three "decisions to confirm" (8.2), and they stand as written: **C1** "one sentence on each side of the speech point" (D1) stands; **C2** dropping the [PACE1] ban on speed adverbs (D5) stands; **C3** chained-only pacing (D5) stands. Where the plan had to read the spec, the reading is listed in "Plan decisions".

## Global Constraints

From the spec, verbatim (section in brackets):

- [Status] "Every design choice is made here; each one the brief left open is marked **[spec choice]**, and Section 7 lists them all. The implementer makes no design decisions."
- [0.3] "**Not changed:** `character_lib.py`: `insert_speech`, `is_facing_sentence`, `_is_camera_sentence`, `speech_text` and every regex. **The placement code stays as it is; the writer is told how it works.**"
- [0.3] "`bin/ltx-story-manifest`, `bin/ltx-movie`, `bin/judge-story`, `bin/judge-clips`, `bin/judge-stills`. `bin/judge-story --patches` gets WP4 through `build_critic_prompt`, with no edit to its file."
- [0.3] "The plan prompt: `PLAN_PROMPT_TEMPLATE`, `SPEAKER_RULE`, `LINES_RULE`, `SILENT_SPEAKER_RULE`."
- [0.3] "`SPEAKING_ACTION_SENTENCE` keeps its exact text and is still used for shots Motion (D2). `SPEAKING_SENTENCES`, `SPEAKING_PROMPT_SENTENCE`, `SPEAKING_IMAGE_SENTENCE`, `SPEECH_FRAMING_SENTENCE`, `dialogue_fixed` and `no_stills_prompt_speaking` are also unchanged."
- [0.3] "`shots_motion`, `shots_image`, `chained_image`, `no_stills_prompt` and every other key line except the two chained Motion lines."
- [0.3] "`CAMERA_SENTENCES`, `SPEAKING_CAMERA`, `pasted_pieces`, `panel_fields`, `WORD_RANGES` and `MIN_WRITER_WORDS`."
- [0.3] "Every check: N1-N19, T1-T3, Q1, P*, S*. `GENERATION_CHECKS`, `RECHECK_IDS`, `NON_BLOCKING_IDS` and `REPAIR_IDS` are unchanged, and no check id is added."
- [0.3] "`apply_patches`, PG1-PG5, `repairable_ids` and `CRITIC_PROMPT_TEMPLATE`."
- [0.3] "The `--story-legacy` templates and path; `movie_ui_lib.py` and `static/*`; `ltx2_mlx_video_skill.py`."
- [0.4] Out of scope: "**`--auto-duration`**"; "**The camera-sentence clash**"; "**Clause splitting** of a writer sentence at ", then", and any new deterministic check of the speech point (D3)."; "**Several insertion points for a multi-line beat.**"; "**Pacing text for shots and no_stills** (D5)."; "Pasting a real-time sentence or phrase by code (D5)."; "Changing the word bands of [PACE1]."; "Measuring optical flow, lip-sync or audio quality as a gate."; "Branding legibility and stray props."
- [0.6] "WP1-WP5 and the tests (Section 4) are must-haves. Nothing else is built: no new check, no new CLI flag, no paste, and no change to placement or to the plan prompt."
- [0.5 WK2] "`/usr/bin/python3` (3.9) and `python3` (3.13) both `py_compile` `story_engine.py`." (checked here with `compile()`, see the house rules)
- [0.5 WK3] "Import sets are unchanged: `story_engine.py` gains no import."
- [0.5 WK4] "Shots and no_stills prompts are byte-identical to today."
- [0.5 WK6] "Legacy output stays byte-identical." (`test_rst40`, `test_rst41`, `test_s52`, `test_casting_regression.py`)
- [4.1] "No test renders, reads the real HOME, or contacts a model server, daemon or the Anthropic API."
- [0.3 G5] "`tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` | `BASELINE` re-baseline in a **separate test-only follow-up commit**".
- [6] PR note: "Writer prompts only. Existing stories re-check and re-render exactly as before; a story regenerated with `--force-story` gets the new chained Motion instructions."

Repository rules (the controller's; every task's requirements include them):

- Standard library only in every Python file this plan touches; every new or changed file must run on Python 3.9.6 and 3.13: no `match` statement, no `X | Y` type expressions, no walrus operator, no `str.removeprefix`, no `zip(strict=)`, no parenthesised context managers.
- Tests never render, never contact a model server, a daemon or the Anthropic API, and never use the real `HOME` (`tests/test_writer_pacing.py` uses the autouse `story_env` fixture, as `tests/test_narrative_fidelity.py` does, and builds every ctx under `tmp_path`).
- Run tests as `cd /Users/reubenpatterson/local_agent_harness/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/<file>`; every pytest run prints a `pytest_asyncio` deprecation warning first, which is expected.
- Never stage `../.DS_Store`, `../.claude/`, `.claude/`, `../agent/__pycache__/`, the repo-root `../bin/` or `bin/action-from-dir`. Stage only the paths a task names and check `git diff --cached --name-only` before every commit. Never use `git stash`, `git reset` or `git checkout` of a path.
- Every commit message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (the commit commands below pass it as a second `-m`).
- Known pre-existing failures at `88213da`, to be ignored when they fail exactly as at the baseline: `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets` (it fails on `bin/ltx-mlx-render`'s `struct` import, before it reaches `story_engine.py`).
- `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` diffs `PIPELINE_FILES` (which holds `story_engine.py`, `tests/test_movie_ui_builder.py:216-221`) in the working tree against a pinned commit (`ac23105`), so `test_mut26` fails from Task 1's first `story_engine.py` edit until Task 3 re-baselines it in its own test-only commit. No task before 3 runs or edits it.
- The legacy `--story-legacy` outputs stay byte-identical: no task touches the legacy templates or path (`test_rst40`, `test_rst41`, `test_s52` and `tests/test_casting_regression.py` pass unchanged after every task).

House rules:

- `WS` = `/Users/reubenpatterson/local_agent_harness/qwen-agent-workspace`. The git root is one level up, so `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix. Run every command from `WS`.
- Every code block is copied exactly, byte for byte. A **Create** writes a new file whose whole content is the block, followed by one newline. An **Append** adds two empty lines after the file's current last line (which ends with one newline), then the block, then one newline. An **Edit** replaces one block of old text, which must occur exactly once in the file at that moment, with the new text; if the old text does not occur exactly once, stop and report: do not adapt it. A **Run this command** step runs its `bash` block from `WS`.
- The compile check in each task is this command, with the task's files as `FILES`. It uses `compile()` on the source text, not `py_compile` (which errors on macOS when pointed at `/dev/null`). Expected output is two lines, `compiled N` for 3.9 and then for 3.13:

```bash
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' FILES; done
```

## Review Focus

These five inputs are implied by the spec, are the ones most likely to hit a real user first, and no WT test exercises them. Each is pinned by a test in its owning task.

1. **A writer re-ask on a speaking chained panel** (the code-only round re-asks the writer with a fix block, for example after N12 "chains actions with 'then'"; spec 3 "Code-only round"). Expected: the re-ask prompt's motion key line is the same as the first ask's, the pacing sentence and the speech-point contract each appear exactly once, the old "speaks once close" text is absent, and the fix block still lists the problem and the previous Motion. Test: `test_review_focus_1_a_writer_re_ask_keeps_one_contract` (Task 1).
2. **One 10-second panel whose beat speaks both lines** (the recorded `hockey-1x241-f` movie; spec R5). Expected: the panel-1 motion key line is `chained_motion1` at 5 to 23 words and 10 seconds, then the speech framing sentence, then the contract naming `"FuboTV hockey player"`; the dialogue key line pastes both lines as one, in order. Test: `test_review_focus_2_one_ten_second_panel_speaks_both_lines` (Task 1).
3. **A `--no-narration` chained movie whose planner still names a speaker** (spec 3 `--no-narration` row). Expected: every panel prompt carries the pacing sentence once and no speaking sentence or dialogue key; the critic prompt has no speech-point clause, also for a recorded plan.json whose beats name a speaker. Test: `test_review_focus_3_a_silent_chained_movie_gets_pacing_and_no_speech_point` (Task 2).
4. **A critic round that may also repick LoRAs** (auto-LoRA with catalog lines: the lora patch line comes first). Expected: the lora line and its catalog lines are unchanged and first, the clause ends the Motion line (not the lora line), and the dialogue line follows. Test: `test_review_focus_4_the_lora_catalog_line_stays_first` (Task 2).
5. **`bin/judge-story --patches` on a story whose plan.json predates on-camera dialogue** (judge-story passes plan.json to `build_critic_prompt` as read, so its beats have no `speaker` key and it has no `spoken_lines`). Expected: the prompt builds without raising and its Motion line has no clause; the same plan with one beat given a speaker gets the clause. Test: `test_review_focus_5_an_older_plan_json_through_judge_story` (Task 2).

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `story_engine.py` | Modify (Tasks 1, 2) | `PACING_SENTENCE` and the two chained Motion key lines (WP1); `SPEAKING_CHAINED_MOTION_SENTENCE` and the extended comment on `SPEAKING_ACTION_SENTENCE` (WP2); the chained motion branch in `build_panel_prompt` (WP3) (Task 1). `CRITIC_SPEAKING_MOTION_CLAUSE`, `critic_field_lines(..., speaking=False)` (WP4) and the `speaking=` argument in `build_critic_prompt` (WP5) (Task 2). |
| `tests/fixtures/writer_pacing/` | Create (Task 1) | `hockey-2x145-f/` and `hockey-1x241-f/`: verbatim `plan.json`, `parts.json`, `story.md`, `story_checks.json`, `manifest.json`, plus a hand-written `case.json` each (spec 4.2). |
| `tests/test_writer_pacing.py` | Create (Task 1), Append (Task 2) | WT1-WT9 and Review Focus 1-5. |
| `tests/test_story_engine.py` | Modify (Task 1) | The spec 4.3 A edit of `test_pacing_panel1_prompt_and_no_slowly`. |
| `tests/test_dialogue.py` | Modify (Task 1) | The spec 4.3 A edit of `test_dlg13_writer_keys_and_speaking_key_lines`. |
| `tests/test_movie_ui_builder.py` | Modify (Task 3 only) | `test_mut26` `BASELINE` and its comment (spec 4.3 A, G5). |

Task 1 is the writer contract (everything the panel writer sees); Task 2 is the critic's patch line, which a reviewer can accept or reject on its own; Task 3 is the review, the test-only re-baseline and the final measurements. The suite stays green after every task except `test_mut26`, as stated above.

---

## Before Task 1: baseline record and snapshot (controller; no code, no commit)

WK1 compares against the pass count recorded here. Nothing is written into the repository.

- [ ] **Step 1: Confirm the starting point.**

```bash
cd /Users/reubenpatterson/local_agent_harness/qwen-agent-workspace
git diff --stat 88213da HEAD -- . ':(exclude)docs' | tail -1   # expected: no output (HEAD's code tree is 88213da's)
git status --short                               # expected: only ?? ../.claude/, ?? ../agent/__pycache__/, ?? ../bin/, ?? .claude/, ?? bin/action-from-dir and ?? ../.DS_Store if present, plus the spec and this plan if they are not committed yet
ls tests/test_writer_pacing.py tests/fixtures/writer_pacing 2>&1 | grep -c "No such file"   # expected: 2
wc -l < story_engine.py                          # expected: 3669
grep -c "The motion plays at natural, real-time speed: use plain action" story_engine.py   # expected: 1
ls generated/stories/hockey-2x145-f/story_rounds/round_0/parts.json generated/stories/hockey-1x241-f/story_rounds/round_0/parts.json   # expected: both paths listed (Task 1 copies from them)
```

If any expected value differs, stop and report: every Edit below was written against this tree.

- [ ] **Step 2: Take the compressed snapshot (house rule; spec 6 step 1).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
mkdir -p $S
tar czf $S/snapshot-pre-writer-pacing-88213da.tgz --exclude qwen-agent-workspace/generated -C /Users/reubenpatterson/local_agent_harness qwen-agent-workspace
tar tzf $S/snapshot-pre-writer-pacing-88213da.tgz | grep -c '^qwen-agent-workspace/generated/'   # expected: 0
tar tzf $S/snapshot-pre-writer-pacing-88213da.tgz | grep -c '^qwen-agent-workspace/story_engine.py$'   # expected: 1
```

- [ ] **Step 3: Record the pytest and script baselines (about 12 minutes).**

```bash
D=/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-26-writer-pacing
mkdir -p $D
git rev-parse HEAD > $D/base-commit.txt
python3 -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
python3 tests/test_ltx_movie_offline.py 2>&1 | tail -1 | tee $D/baseline-offline.txt
```

Expected: the `FAILED` lines are exactly the two known pre-existing failures of Global Constraints; the offline script prints `OK n/n` (`OK 347/347` on the replay tree). `tests/test_fleet_tracing.py::test_trt41a_trace_cli_on_one_agent` is timing-sensitive and unrelated to this plan (it failed once in the replay baseline and passed in the replay's final run): if it fails here, rerun it alone (`python3 -m pytest -q -p no:cacheprovider tests/test_fleet_tracing.py -k trt41a`) and record both results. Write any other difference into `$D/baseline-notes.txt`; Task 3 compares against what is recorded here.

---

### Task 1: The chained writer contract: the pacing sentence, the speech point and the fixtures (WP1, WP2, WP3)

Implements G3 (spec 4.2: the ten recorded copies and the two hand-written `case.json`), WP1, WP2 and WP3, and the spec 4.3 A edits of `test_pacing_panel1_prompt_and_no_slowly` and DLG13. Tests WT1-WT6, WT8, WT9, Review Focus 1 and 2. Creates `tests/test_writer_pacing.py`, which Task 2 appends to. This is the first pipeline commit: `test_mut26` fails from here until Task 3.

**Files:**
- Create: `tests/fixtures/writer_pacing/hockey-2x145-f/{plan.json, parts.json, story.md, story_checks.json, manifest.json, case.json}`, `tests/fixtures/writer_pacing/hockey-1x241-f/{plan.json, parts.json, story.md, story_checks.json, manifest.json, case.json}`
- Create: `tests/test_writer_pacing.py`
- Modify: `story_engine.py` (before `KEY_LINE_TEMPLATES` `:1679`; `chained_motion1` and `chained_motion` `:1688-1703`; the comment and `SPEAKING_ACTION_SENTENCE` `:1752-1759`; `build_panel_prompt` `:2457-2458`)
- Modify: `tests/test_story_engine.py` (`test_pacing_panel1_prompt_and_no_slowly` `:2923-2924`)
- Modify: `tests/test_dialogue.py` (`test_dlg13_writer_keys_and_speaking_key_lines` `:741-745`)

**Interfaces:**
- Consumes (existing): `story_engine.KEY_LINE_TEMPLATES`, `SPEECH_FRAMING_SENTENCE`, `SPEAKING_ACTION_SENTENCE`, `SPEAKING_SENTENCES`, `SPEAKING_IMAGE_SENTENCE`, `SPEAKING_PROMPT_SENTENCE`, `build_panel_prompt(ctx, plan, parts, k, fix=None, no_stills_rules="")`, `panel_fields(ctx, plan, parts, k)`, `assemble(ctx, plan, parts)`, `panel_checks(ctx, plan, parts, text, story_md_path) -> (hard, advisory)`, `recheck(ctx, legacy_validate) -> (rc, advisories)`; `character_lib.insert_speech(text, sentence, phrases=(), first_action=False)`, `speech_text(phrase, line, delivery)`, `parse_dialogue(value, phrases) -> (phrase, line, rest)`; `story_engine_testutil.set_story_env`, `make_ws`, `make_ctx(se, ws, **overrides)`; from `tests/test_dialogue.py` (imported as `dlg`): `_story(ws, mode, n=3, plan_mut=None, replies=None, ctx_kw=None) -> (ctx, plan, parts, text, path)`, `_speaking(k=2, speaker="c1")`, `LINE`; `tests/fixtures/narrative_fidelity/narrative.txt`.
- Produces: in `story_engine`, the strings `PACING_SENTENCE` and `SPEAKING_CHAINED_MOTION_SENTENCE`; `build_panel_prompt` appends `SPEAKING_CHAINED_MOTION_SENTENCE` (not `SPEAKING_SENTENCES["motion"]`) to the motion key line of a chained speaking panel. In `tests/test_writer_pacing.py`: the module header (`WS`, `FIX`, `seu`, `dlg`, `lib`, `se`, the autouse `story_env` fixture, the `ws` fixture, `copy`, `re` and `shutil` imported), `_case(name)`, `_read(name, filename) -> str`, `_json(name, filename)`, `HOCKEY`, `_ctx(ws, name, **kw)`, `_recorded(name) -> (plan, parts)`, `_motion_key_line(prompt)`, and the constants `PHRASE`, `LINE1`, `LINE2`, `GOOD2`, `SAY2`, `FACING_CAMERA`, `NAMES`.

- [ ] **Step 1: Copy the fixtures, write the failing tests and the spec 4.3 A edits.**

New tests in this task: `test_wt1_the_constants`, `test_wt2_pacing_reaches_chained_prompts_only`, `test_wt3_the_hockey_speaking_prompts`, `test_review_focus_1_a_writer_re_ask_keeps_one_contract`, `test_review_focus_2_one_ten_second_panel_speaks_both_lines`, `test_wt4_shots_and_no_stills_speaking_prompts_are_unchanged`, `test_wt5_the_contract_matches_the_placement`, `test_wt6_the_contract_motion_passes_the_checks`, `test_wt8_old_stories_compose_unchanged`, `test_wt9_old_stories_check_unchanged`.

**1.1.** Run this command (from WS):

```bash
D=tests/fixtures/writer_pacing
R=/Users/reubenpatterson/local_agent_harness/qwen-agent-workspace/generated/stories
for s in hockey-2x145-f hockey-1x241-f; do
    mkdir -p $D/$s
    for f in plan.json story.md story_checks.json manifest.json; do cp "$R/$s/$f" "$D/$s/$f"; done
    cp "$R/$s/story_rounds/round_0/parts.json" "$D/$s/parts.json"
done
(cd $D && shasum -a 256 hockey-2x145-f/plan.json hockey-2x145-f/parts.json hockey-2x145-f/story.md hockey-2x145-f/story_checks.json hockey-2x145-f/manifest.json hockey-1x241-f/plan.json hockey-1x241-f/parts.json hockey-1x241-f/story.md hockey-1x241-f/story_checks.json hockey-1x241-f/manifest.json)
```

Expected output, exactly (the recorded files are byte-for-byte copies; any other hash: stop and report):

```text
05babd6cddc11299a6dc958d456c6cbe653fc9ce983946e8ec9d418f7b6d038f  hockey-2x145-f/plan.json
40d54b1e6bec6ca7fd3eded12ee9f493853250422eafd34444f6d3a94dcd3e00  hockey-2x145-f/parts.json
896a62f6d82e64885f86c00ca64d21cb7da92799121a08ac1a7120e1a8313e98  hockey-2x145-f/story.md
2513317ef6a351f0d52d28f00e524e5acc3cf8c33f2fa7882336456f5cc00192  hockey-2x145-f/story_checks.json
335811ef9a60d1d31d61b6f0e900c8ae268638f5a2c431e65e81205d92339e41  hockey-2x145-f/manifest.json
d5592faa169b4e162b5381a90b92920ece4d3ceeee10d2b6276e7c6b7934ff9c  hockey-1x241-f/plan.json
065dda461f58dfb52ff39e230a9508ec8323dc0824585396a84ba48f36e6f290  hockey-1x241-f/parts.json
34554b6a03aa89a8d4044b400274a4589de9a403fa7592461707efc61ae7c349  hockey-1x241-f/story.md
179b0a7a8132c5066adb663ce3ca8269d77ca4fe138ce8097b403d6d83e6eefa  hockey-1x241-f/story_checks.json
486fdfc140ddfd3cf348d9de797df53a24db54b6ce68b2a4e4e5a7bf79f0243b  hockey-1x241-f/manifest.json
```

`story_checks.json` is the top-level file of each story (spec 4.2), not `story_rounds/round_0/story_checks.json`, which differs.

**1.2.** Create `tests/fixtures/writer_pacing/hockey-2x145-f/case.json` (one line, then a newline):

```json
{"story_id": "hockey-2x145-f", "panels": 2, "seconds": "6", "frames": 145, "goal": "a polished, realistic FuboTV hockey promo: on-camera lines delivered by the player, a hockey stop with ice spray, legible FuboTV branding"}
```

**1.3.** Create `tests/fixtures/writer_pacing/hockey-1x241-f/case.json` (one line, then a newline):

```json
{"story_id": "hockey-1x241-f", "panels": 1, "seconds": "10", "frames": 241, "goal": "a polished, realistic FuboTV hockey promo: on-camera lines delivered by the player, a hockey stop with ice spray, legible FuboTV branding"}
```

**1.4.** Run this command (from WS):

```bash
shasum -a 256 tests/fixtures/writer_pacing/hockey-2x145-f/case.json tests/fixtures/writer_pacing/hockey-1x241-f/case.json tests/fixtures/narrative_fidelity/narrative.txt
```

Expected output, exactly:

```text
2d62c7ba3616c715cf7a86bf73a3a872765bb79b0a68e896a98fe38c8b2051c1  tests/fixtures/writer_pacing/hockey-2x145-f/case.json
7e5c4d747842131cfa497ba1469f1b40aaff5449c031500b8ca76bc30f8f2453  tests/fixtures/writer_pacing/hockey-1x241-f/case.json
7801957a0e5a4a741039e9954a507e6b2d21af384f2044bd42d5b6f3459427ca  tests/fixtures/narrative_fidelity/narrative.txt
```

(The narrative is reused from `tests/fixtures/narrative_fidelity/`, spec 4.2; it is not copied again.)

**1.5.** Create `tests/test_writer_pacing.py`:

```python
"""Tests for writer pacing (docs/superpowers/specs/2026-10-26-writer-pacing-design.md, Section 4.1:
WT1-WT9, and the plan's Review Focus 1-5): the chained writer is told where the pipeline speaks
the line (one sentence on each side of the speech point), every chained Motion key line asks for
fast, concrete motion at real-time speed with named effects, and the critic's chained Motion
patch keeps the speech point.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_writer_pacing.py
Stdlib plus pytest. No test renders, reads the real HOME, or contacts a model server, a daemon or
the Anthropic API: every ctx lives under tmp_path (story_engine_testutil.make_ws) and every test
runs under the autouse story_env fixture (a temporary HOME, character library and LoRA catalog).
The hockey fixtures under tests/fixtures/writer_pacing/ are verbatim copies of the two recorded
2026-10-26 NK8 runs (hockey-2x145-f, hockey-1x241-f), plus one hand-written case.json each.
"""

import copy
import importlib.machinery
import json
import os
import re
import shutil
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
FIX = os.path.join(WS, "tests", "fixtures", "writer_pacing")
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402
import test_dialogue as dlg  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


lib = _load("character_lib_for_pacing", "character_lib.py")
se = _load("story_engine_for_pacing", "story_engine.py")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


def _case(name):
    """The hand-written case.json of a recorded hockey run (spec 4.2)."""
    with open(os.path.join(FIX, name, "case.json"), encoding="utf-8") as f:
        return json.load(f)


def _read(name, filename):
    with open(os.path.join(FIX, name, filename), encoding="utf-8") as f:
        return f.read()


def _json(name, filename):
    with open(os.path.join(FIX, name, filename), encoding="utf-8") as f:
        return json.load(f)


with open(os.path.join(WS, "tests", "fixtures", "narrative_fidelity", "narrative.txt"),
          encoding="utf-8") as _f:
    HOCKEY = _f.read().strip()


def _ctx(ws, name, **kw):
    """The StoryContext of a recorded hockey run: chained, --speech-only, the case's panels,
    seconds, clip length and goal; keyword arguments replace fields."""
    c = _case(name)
    fields = dict(story_id=c["story_id"], mode="chained", panels=c["panels"],
                  seconds=c["seconds"], clip_seconds=c["frames"] / 24.0, narration="speech",
                  narrative=HOCKEY, goal=c["goal"])
    fields.update(kw)
    return seu.make_ctx(se, ws, **fields)


def _recorded(name):
    """(plan, parts) of a recorded run: plan.json as written, and parts.json's panels without
    their "index" key."""
    plan = _json(name, "plan.json")
    parts = [{k: v for k, v in p.items() if k != "index"}
             for p in _json(name, "parts.json")["panels"]]
    return plan, parts


def _motion_key_line(prompt):
    """The first line of a panel prompt that starts with "motion: " (the motion key line)."""
    return [line for line in prompt.split("\n") if line.startswith("motion: ")][0]


PHRASE = "FuboTV hockey player"
LINE1 = "Getting the best deal on hockey isn't a hat trick..."
LINE2 = "It's just FuboTV."
GOOD2 = ("The FuboTV hockey player snaps into a hard hockey stop that throws a big, bright spray "
         "of ice into the air. He pushes off and skates away from the camera at real-time speed.")
SAY2 = lib.speech_text(PHRASE, LINE2, "beats")
FACING_CAMERA = " FuboTV hockey player faces the camera. The camera stays static."
NAMES = ("hockey-2x145-f", "hockey-1x241-f")

# --- WT1: the constants (WP1, WP2) ----------------------------------------------------------------

PACING = (" The motion plays at real-time speed: use fast, concrete action verbs, with no words "
          "that slow it down, and end the main action with the words 'at real-time speed'. When "
          "an action throws something up, such as ice, snow, water, dust or sparks, name it in "
          "the same sentence as a big, bright spray, splash or cloud, and never say how long it "
          "lasts, how small it is or when it settles.")
SPEAKING_CHAINED = (
    " In this panel @@SPEAKER@@ speaks the dialogue, and the pipeline inserts it right after the "
    "first sentence about what @@SPEAKER@@ does. Write that first sentence as everything they do "
    "before the dialogue, ending with them near the camera, face toward it (if the dialogue "
    "comes before they do anything, it is how they turn toward the camera); only when the beat "
    "has them act after the dialogue, write what they do then as a second sentence. Never put "
    "an action from before the dialogue and one from after it in the same sentence, and do not "
    "write the spoken words or a speaking verb; the pipeline adds them.")
CHAINED_MOTION1 = (
    "motion: W1 to W2 words in one or two plain sentences: what the characters physically do "
    "during these @@SECONDS@@ seconds. Name each character only by their referring phrase, word "
    "for word. Describe ONE continuous physical motion, not a sequence of separate steps: "
    "@@SECONDS@@ seconds is enough for a single gesture, a few footsteps or the start of a "
    "movement. The motion plays at real-time speed: use fast, concrete action verbs, with no "
    "words that slow it down, and end the main action with the words 'at real-time speed'. When "
    "an action throws something up, such as ice, snow, water, dust or sparks, name it in the "
    "same sentence as a big, bright spray, splash or cloud, and never say how long it lasts, how "
    "small it is or when it settles. You may add one camera direction; without one, the "
    "pipeline adds the planned camera sentence.")
CHAINED_MOTION = (
    "motion: W1 to W2 words in one or two plain sentences: what the characters physically do "
    "during these @@SECONDS@@ seconds, continuing from where the previous panel left them. Name "
    "each character only by their referring phrase, word for word. Describe ONE continuous "
    "physical motion, not a sequence of separate steps: @@SECONDS@@ seconds is enough for a "
    "single gesture, a few footsteps or the start of a movement. The motion plays at real-time "
    "speed: use fast, concrete action verbs, with no words that slow it down, and end the main "
    "action with the words 'at real-time speed'. When an action throws something up, such as "
    "ice, snow, water, dust or sparks, name it in the same sentence as a big, bright spray, "
    "splash or cloud, and never say how long it lasts, how small it is or when it settles. Do "
    "not describe appearance, clothing, setting, lighting, colour or style -- all of that is "
    "already on screen. You may add one camera direction.")
SPEAKING_ACTION = (" In this panel @@SPEAKER@@ speaks the dialogue: they may move as the beat "
                   "says, but write the motion so that their face is toward the camera, in frame "
                   "and lit while they speak -- a speaker who approaches the camera speaks once "
                   "close -- and do not write the spoken words or a speaking verb here; the "
                   "pipeline adds them.")


def test_wt1_the_constants():
    assert se.PACING_SENTENCE == PACING
    assert se.SPEAKING_CHAINED_MOTION_SENTENCE == SPEAKING_CHAINED
    assert se.KEY_LINE_TEMPLATES["chained_motion1"] == CHAINED_MOTION1
    assert se.KEY_LINE_TEMPLATES["chained_motion"] == CHAINED_MOTION
    assert se.SPEAKING_ACTION_SENTENCE == SPEAKING_ACTION
    assert se.SPEAKING_SENTENCES == {"image": se.SPEAKING_IMAGE_SENTENCE,
                                     "motion": se.SPEAKING_ACTION_SENTENCE,
                                     "prompt": se.SPEAKING_PROMPT_SENTENCE}
    for text in (PACING, SPEAKING_CHAINED, CHAINED_MOTION1, CHAINED_MOTION):
        assert "slowly" not in text.lower() and "no adverbs" not in text, text[:40]
        assert set(re.findall(r"@@[A-Z_]+@@", text)) <= {"@@SECONDS@@", "@@SPEAKER@@"}, text[:40]
    assert "speaks once close" not in SPEAKING_CHAINED


# --- WT2: pacing reaches chained prompts only (WP1, D5) ------------------------------------------

OLD_PACING = "use plain action verbs with no adverbs of speed or manner"


def test_wt2_pacing_reaches_chained_prompts_only(ws):
    ctx, plan, parts, _t, _p = dlg._story(ws, "chained", 3)
    for k in (1, 2, 3):
        prompt = se.build_panel_prompt(ctx, plan, parts, k)
        assert prompt.count(se.PACING_SENTENCE) == 1, k
        assert OLD_PACING not in prompt, k
    for mode, ks in (("shots", (1, 2)), ("no_stills", (1,))):
        ctx, plan, parts, _t, _p = dlg._story(ws, mode, 3)
        for k in ks:
            prompt = se.build_panel_prompt(ctx, plan, parts, k)
            assert se.PACING_SENTENCE not in prompt and "at real-time speed" not in prompt, (
                mode, k)


# --- WT3, Review Focus 1, 2: the hockey speaking prompts (WP1-WP3) -----------------------------

def _expected_line(template, w2, seconds):
    return (se.KEY_LINE_TEMPLATES[template].replace("W1", "5", 1).replace("W2", w2, 1)
            .replace("@@SECONDS@@", seconds) + se.SPEECH_FRAMING_SENTENCE
            + se.SPEAKING_CHAINED_MOTION_SENTENCE.replace("@@SPEAKER@@", '"%s"' % PHRASE))


def test_wt3_the_hockey_speaking_prompts(ws):
    ctx = _ctx(ws, "hockey-2x145-f")
    plan, parts = _recorded("hockey-2x145-f")
    for k, template, w2 in ((1, "chained_motion1", "23"), (2, "chained_motion", "25")):
        prompt = se.build_panel_prompt(ctx, plan, parts, k)
        assert _motion_key_line(prompt) == _expected_line(template, w2, "6"), k
        assert "before the dialogue" in prompt and "speaks once close" not in prompt, k
    assert 'dialogue: exactly "It\'s just FuboTV." -- ' in se.build_panel_prompt(
        ctx, plan, parts, 2)


def test_review_focus_1_a_writer_re_ask_keeps_one_contract(ws):
    ctx = _ctx(ws, "hockey-2x145-f")
    plan, parts = _recorded("hockey-2x145-f")
    fix = ["panel 2: N12 one action: Motion: chains actions with 'then'"]
    prompt = se.build_panel_prompt(ctx, plan, parts, 2, fix=fix)
    assert "\n" + _expected_line("chained_motion", "25", "6") + "\n" in prompt
    assert prompt.count(se.PACING_SENTENCE) == 1
    assert prompt.count(se.SPEAKING_CHAINED_MOTION_SENTENCE.replace(
        "@@SPEAKER@@", '"%s"' % PHRASE)) == 1
    assert "speaks once close" not in prompt and "@@" not in prompt
    assert "\n- " + fix[0] + "\n" in prompt
    assert "\nPrevious version:\n" in prompt and "\nmotion: " + parts[1]["motion"] + "\n" in prompt


def test_review_focus_2_one_ten_second_panel_speaks_both_lines(ws):
    ctx = _ctx(ws, "hockey-1x241-f")
    plan, parts = _recorded("hockey-1x241-f")
    prompt = se.build_panel_prompt(ctx, plan, parts, 1)
    assert _motion_key_line(prompt) == _expected_line("chained_motion1", "23", "10")
    assert '\ndialogue: exactly "%s %s" -- ' % (LINE1, LINE2) in prompt
    assert "@@" not in prompt and "speaks once close" not in prompt


# --- WT4: shots and no_stills speaking prompts are unchanged (D2) --------------------------------

def test_wt4_shots_and_no_stills_speaking_prompts_are_unchanged(ws):
    ctx, plan, parts, _t, _p = dlg._story(ws, "shots", 3, plan_mut=dlg._speaking(2),
                                          replies={2: {"dialogue": dlg.LINE}})
    prompt = se.build_panel_prompt(ctx, plan, parts, 2)
    assert ("without one, the pipeline adds the planned camera sentence."
            + se.SPEAKING_ACTION_SENTENCE.replace("@@SPEAKER@@", '"the courier"') + "\n") in prompt
    assert "before the dialogue" not in prompt
    ctx, plan, parts, _t, _p = dlg._story(ws, "no_stills", 3, plan_mut=dlg._speaking(2),
                                          replies={2: {"dialogue": dlg.LINE}})
    prompt = se.build_panel_prompt(ctx, plan, parts, 2)
    assert "here; the pipeline adds them.\n" in prompt
    assert "before the dialogue" not in prompt


# --- WT5, WT6: a Motion written to the contract (D1) ---------------------------------------------

def _good(ws):
    """(ctx, plan, parts) of the 2x145-f run with panel 2's Motion written to the contract."""
    ctx = _ctx(ws, "hockey-2x145-f")
    plan, parts = _recorded("hockey-2x145-f")
    parts[1]["motion"] = GOOD2
    return ctx, plan, parts


def _compose(writer, say=SAY2):
    return lib.insert_speech(writer + FACING_CAMERA, say, [PHRASE], first_action=True)


def test_wt5_the_contract_matches_the_placement(ws):
    ctx, plan, parts = _good(ws)
    motion = dict(se.panel_fields(ctx, plan, parts, 2))["Motion"]
    assert motion == GOOD2 + FACING_CAMERA
    out = lib.insert_speech(motion, SAY2, [PHRASE], first_action=True)
    assert out == ("The FuboTV hockey player snaps into a hard hockey stop that throws a big, "
                   "bright spray of ice into the air. FuboTV hockey player faces the camera. "
                   + SAY2 + " He pushes off and skates away from the camera at real-time speed. "
                   "The camera stays static.")
    assert out.index(SAY2) < out.index("skates away")
    camera_first = ("The camera holds on him. The FuboTV hockey player snaps into a hard hockey "
                    "stop. He skates away at real-time speed.")
    out = _compose(camera_first)
    assert out == ("The camera holds on him. The FuboTV hockey player snaps into a hard hockey "
                   "stop. FuboTV hockey player faces the camera. " + SAY2 + " He skates away at "
                   "real-time speed. The camera stays static.")
    assert out.index(SAY2) < out.index("skates away")
    camera_last = ("The FuboTV hockey player snaps into a hard hockey stop. He skates away at "
                   "real-time speed. The camera holds on him as he recedes.")
    out = _compose(camera_last)
    assert out == ("The FuboTV hockey player snaps into a hard hockey stop. FuboTV hockey player "
                   "faces the camera. " + SAY2 + " He skates away at real-time speed. The camera "
                   "holds on him as he recedes. The camera stays static.")
    assert out.index(SAY2) < out.index("skates away")
    one = "The FuboTV hockey player skates toward the camera at real-time speed."
    assert _compose(one) == (one + " FuboTV hockey player faces the camera. " + SAY2
                             + " The camera stays static.")
    plain = lib.speech_text(PHRASE, LINE2, "plain")
    out = _compose(GOOD2, plain)
    assert out == ("The FuboTV hockey player snaps into a hard hockey stop that throws a big, "
                   "bright spray of ice into the air. FuboTV hockey player faces the camera. "
                   + plain + " He pushes off and skates away from the camera at real-time speed. "
                   "The camera stays static.")
    assert out.index(plain) < out.index("skates away")


def test_wt6_the_contract_motion_passes_the_checks(ws, tmp_path):
    ctx, plan, parts = _good(ws)
    text = se.assemble(ctx, plan, parts)
    path = os.path.join(str(tmp_path), "story.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    assert se.panel_checks(ctx, plan, parts, text, path) == (
        [], ["panel 1: N7 dialogue and text: Motion: says 'speaks'"])


# --- WT8, WT9: old stories compose and check unchanged (WK6) -------------------------------------

def _story_fields(text):
    """[(motion, dialogue)] of each "## Panel" section of a story.md."""
    fields = []
    for section in text.split("\n## Panel ")[1:]:
        lines = section.split("\n")
        motion = [line[len("Motion: "):] for line in lines if line.startswith("Motion: ")][0]
        dialogue = [line[len("Dialogue: "):] for line in lines if line.startswith("Dialogue: ")][0]
        fields.append((motion, dialogue))
    return fields


def test_wt8_old_stories_compose_unchanged():
    for name in NAMES:
        panels = _json(name, "manifest.json")["panels"]
        fields = _story_fields(_read(name, "story.md"))
        assert len(fields) == len(panels) == _case(name)["panels"], name
        for k, (motion, dialogue) in enumerate(fields, start=1):
            phrase, line, _rest = lib.parse_dialogue(dialogue, [PHRASE])
            assert lib.insert_speech(motion, lib.speech_text(phrase, line, "beats"), [phrase],
                                     first_action=True) == panels[k - 1]["motion_prompt"], (name, k)


RECORDED_ADVISORY = {
    "hockey-2x145-f": ["panel 1: N7 dialogue and text: Motion: says 'speaks'",
                       "panel 2: N12 one action: Motion: chains actions with 'then'",
                       "panel 2: N1 word count: Motion: is 46 words; aim for 15-35"],
    "hockey-1x241-f": ["panel 1: N12 one action: Motion: chains actions with 'then'"],
}


def test_wt9_old_stories_check_unchanged(ws, tmp_path):
    for name in NAMES:
        ctx = _ctx(ws, name)
        plan, parts = _recorded(name)
        text = se.assemble(ctx, plan, parts)
        assert text == _read(name, "story.md"), name
        path = os.path.join(str(tmp_path), name + ".md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        rec = _json(name, "story_checks.json")
        expected = ([m["message"] for m in rec["hard"]], [m["message"] for m in rec["advisory"]])
        assert expected == ([], RECORDED_ADVISORY[name]), name
        assert se.panel_checks(ctx, plan, parts, text, path) == expected, name
        for filename in ("plan.json", "story.md"):
            shutil.copy(os.path.join(FIX, name, filename), os.path.join(ctx.story_dir, filename))
        rc, _adv = se.recheck(ctx, lambda path, panels, no_stills=False: [])
        assert rc == 0, name
```

**1.6.** Edit `tests/test_story_engine.py` (spec 4.3 A, WP1): replace this text, which occurs exactly once:

```python
    assert "The motion plays at natural, real-time speed: use plain action verbs with no " \
        "adverbs of speed or manner." in prompt
```

with:

```python
    assert "The motion plays at real-time speed: use fast, concrete action verbs, with no " \
        "words that slow it down, and end the main action with the words 'at real-time " \
        "speed'." in prompt
```

**1.7.** Edit `tests/test_dialogue.py` (spec 4.3 A, WP2, WP3): replace this text, which occurs exactly once:

```python
    assert ('already on screen. You may add one camera direction. In this panel "the courier" '
            "speaks the dialogue: they may move as the beat says, but write the motion so that "
            "their face is toward the camera, in frame and lit while they speak -- a speaker who "
            "approaches the camera speaks once close -- and do not write the spoken words or a "
            "speaking verb here; the pipeline adds them.\n") in prompt
```

with:

```python
    assert ('already on screen. You may add one camera direction.'
            + se.SPEAKING_CHAINED_MOTION_SENTENCE.replace("@@SPEAKER@@", '"the courier"')
            + "\n") in prompt
```

DLG13's shots assertion (`'without one, the pipeline adds the planned camera sentence. In this panel "the courier" speaks the dialogue:'`) is not edited and must pass.

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_writer_pacing.py tests/test_story_engine.py::test_pacing_panel1_prompt_and_no_slowly tests/test_dialogue.py::test_dlg13_writer_keys_and_speaking_key_lines 2>&1 | grep -E '^FAILED|passed|failed'
```

Expected: `7 failed, 5 passed`. WT1 and WT2 fail with `AttributeError: module 'story_engine_for_pacing' has no attribute 'PACING_SENTENCE'`; WT3, Review Focus 1 and Review Focus 2 with `... has no attribute 'SPEAKING_CHAINED_MOTION_SENTENCE'`; `test_pacing_panel1_prompt_and_no_slowly` with an `AssertionError` on the new pacing sentence; DLG13 with `AttributeError: module 'story_engine_for_dialogue' has no attribute 'SPEAKING_CHAINED_MOTION_SENTENCE'`. WT4, WT5, WT6, WT8 and WT9 pass already: they pin behaviour this task must leave exactly as it is (shots and no_stills prompts, the unchanged placement, the checks, and the recorded stories).

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py` (WP1, the constant): replace this text, which occurs exactly once:

```python
              "motion from that exact pose.\n\n")
KEY_LINE_TEMPLATES = {
```

with:

```python
              "motion from that exact pose.\n\n")
# Writer pacing spec WP1, D5: fast, concrete motion at real-time speed, with named effects.
PACING_SENTENCE = (" The motion plays at real-time speed: use fast, concrete action verbs, with no "
                   "words that slow it down, and end the main action with the words 'at real-time "
                   "speed'. When an action throws something up, such as ice, snow, water, dust or "
                   "sparks, name it in the same sentence as a big, bright spray, splash or cloud, "
                   "and never say how long it lasts, how small it is or when it settles.")
KEY_LINE_TEMPLATES = {
```

**3.2.** Edit `story_engine.py` (WP1, the two chained Motion key lines): replace this text, which occurs exactly once:

```python
    "chained_motion1": (
        "motion: W1 to W2 words in one or two plain sentences: what the characters physically do "
        "during these @@SECONDS@@ seconds. Name each character only by their referring phrase, "
        "word for word. Describe ONE continuous physical motion, not a sequence of separate "
        "steps: @@SECONDS@@ seconds is enough for a single gesture, a few footsteps or the "
        "start of a movement. The motion plays at natural, real-time speed: use plain action "
        "verbs with no adverbs of speed or manner. You may add one camera direction; without "
        "one, the pipeline adds the planned camera sentence."),
    "chained_motion": (
        "motion: W1 to W2 words in one or two plain sentences: what the characters physically do "
        "during these @@SECONDS@@ seconds, continuing from where the previous panel left them. "
        "Name each character only by their referring phrase, word for word. Describe ONE "
        "continuous physical motion, not a sequence of separate steps: @@SECONDS@@ seconds is "
        "enough for a single gesture, a few footsteps or the start of a movement. Do not describe "
        "appearance, clothing, setting, lighting, colour or style -- all of that is already on "
        "screen. You may add one camera direction."),
```

with:

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

**3.3.** Edit `story_engine.py` (WP2; the comment gains the spec's sentence, and the WP2 comment is wrapped at 100 columns, Plan decision 3): replace this text, which occurs exactly once:

```python
# Appended to a speaking panel's key lines (dialogue spec 8.2; narrative dialogue fidelity spec
# 7.2); @@SPEAKER@@ is the speaker's quoted referring phrase.
SPEAKING_ACTION_SENTENCE = (" In this panel @@SPEAKER@@ speaks the dialogue: they may move as the "
                            "beat says, but write the motion so that their face is toward the "
                            "camera, in frame and lit while they speak -- a speaker who approaches "
                            "the camera speaks once close -- and do not write the spoken words or "
                            "a speaking verb here; the pipeline adds them.")
SPEAKING_PROMPT_SENTENCE = (
```

with:

```python
# Appended to a speaking panel's key lines (dialogue spec 8.2; narrative dialogue fidelity spec
# 7.2); @@SPEAKER@@ is the speaker's quoted referring phrase. Chained Motion uses
# SPEAKING_CHAINED_MOTION_SENTENCE instead (writer pacing spec WP2); shots Motion keeps this one
# (one action sentence, so the line follows it).
SPEAKING_ACTION_SENTENCE = (" In this panel @@SPEAKER@@ speaks the dialogue: they may move as the "
                            "beat says, but write the motion so that their face is toward the "
                            "camera, in frame and lit while they speak -- a speaker who approaches "
                            "the camera speaks once close -- and do not write the spoken words or "
                            "a speaking verb here; the pipeline adds them.")
# Writer pacing spec WP2, D1, D2: a chained speaking panel's motion is one sentence before the
# dialogue (which character_lib.insert_speech places after it) and, when the beat goes on, one
# after it.
SPEAKING_CHAINED_MOTION_SENTENCE = (
    " In this panel @@SPEAKER@@ speaks the dialogue, and the pipeline inserts it right after the "
    "first sentence about what @@SPEAKER@@ does. Write that first sentence as everything they do "
    "before the dialogue, ending with them near the camera, face toward it (if the dialogue "
    "comes before they do anything, it is how they turn toward the camera); only when the beat "
    "has them act after the dialogue, write what they do then as a second sentence. Never put "
    "an action from before the dialogue and one from after it in the same sentence, and do not "
    "write the spoken words or a speaking verb; the pipeline adds them.")
SPEAKING_PROMPT_SENTENCE = (
```

**3.4.** Edit `story_engine.py` (WP3, `build_panel_prompt`): replace this text, which occurs exactly once:

```python
        if speaks:
            line += SPEAKING_SENTENCES.get(key, "")
```

with:

```python
        if speaks:
            line += (SPEAKING_CHAINED_MOTION_SENTENCE if ctx.mode == "chained" and key == "motion"
                     else SPEAKING_SENTENCES.get(key, ""))
```

Nothing else in `build_panel_prompt` changes: the existing `.replace("@@SPEAKER@@", ...)` replaces both `@@SPEAKER@@` tokens of WP2.

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_writer_pacing.py tests/test_dialogue.py tests/test_story_engine.py tests/test_narrative_fidelity.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_character_lib.py tests/test_ltx_story_manifest_chain.py 2>&1 | grep -E '^FAILED|passed|failed'
grep -c "natural, real-time" story_engine.py
```

Expected: one `FAILED` line, `tests/test_story_engine.py::test_rst62_import_sets` (the known failure), then `1 failed, 364 passed, 1 skipped` (DLG-K1 is the skip); then `0` (spec WP1: the [PACE1] sentence appears nowhere in `story_engine.py`). Spec 4.3 B and C pass unchanged in this run: `test_rst16_panel_prompt`, `test_rst22_critic_prompt`, `test_rs4_constants`, `test_pacing_camera_sentences_classify_as_before`, DLG4, DLG7-DLG10, DLG15, DLG19, DLG20, DLG22, DLG24, NF15, NF20, NF25, NF28-NF35, `test_review_focus_2`, `test_review_focus_3`, `test_rst40`, `test_rst41`, `test_rst61`, `test_s52`, every `test_shots_mode.py` test, `test_casting_regression.py`, `test_character_lib.py` and `test_v2_golden_byte_identical`. Then the compile check with `FILES` = `story_engine.py tests/test_writer_pacing.py tests/test_story_engine.py tests/test_dialogue.py`; expected `compiled 4` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_writer_pacing.py tests/fixtures/writer_pacing tests/test_story_engine.py tests/test_dialogue.py
git diff --cached --name-only    # expected: exactly these 16 paths, each with the qwen-agent-workspace/ prefix: story_engine.py, tests/test_dialogue.py, tests/test_story_engine.py, tests/test_writer_pacing.py and tests/fixtures/writer_pacing/{hockey-1x241-f,hockey-2x145-f}/{case.json,manifest.json,parts.json,plan.json,story.md,story_checks.json}
git commit -m "feat(story): tell the chained writer where the line is spoken, and ask for fast motion at real-time speed with named effects (WP1-WP3, WT1-WT6, WT8, WT9)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The critic's chained Motion patch keeps the speech point (WP4, WP5)

Implements WP4 (`CRITIC_SPEAKING_MOTION_CLAUSE`, `critic_field_lines(..., speaking=False)`) and WP5 (`build_critic_prompt` passes `speaking`). Tests WT7 (with WT1's third literal, Plan decision 1), Review Focus 3, 4 and 5. `bin/judge-story --patches` inherits the clause through `build_critic_prompt`; its file is not edited.

**Files:**
- Modify: `story_engine.py` (after `CRITIC_Q1_FIELD_LINE` `:2555-2561`; `critic_field_lines` `:2571-2594`; the field-lines call in `build_critic_prompt` `:2611-2612`)
- Modify: `tests/test_writer_pacing.py` (append)

**Interfaces:**
- Consumes: from Task 1, `story_engine.PACING_SENTENCE` and, in `tests/test_writer_pacing.py`, `_json`, `_read`, `copy`, `re`, `se`, `dlg`; existing `story_engine.build_critic_prompt(plan, story_md_text, violations, catalog_lines=None, for_judge=False, narration=True)`; from `tests/test_dialogue.py`: `MOTION_LINE` (a `%`-format string taking the field and the label), `DIALOGUE_FIELD_LINE`, `_story`, `_speaking`.
- Produces: `story_engine.CRITIC_SPEAKING_MOTION_CLAUSE` (str); `story_engine.critic_field_lines(mode, catalog_lines, narration=True, spoken=False, speaking=False) -> str`. In `tests/test_writer_pacing.py`: the constants `MOTION`, `CRITIC_CLAUSE`, `CATALOG`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_wt7_the_critic_clause`, `test_review_focus_3_a_silent_chained_movie_gets_pacing_and_no_speech_point`, `test_review_focus_4_the_lora_catalog_line_stays_first`, `test_review_focus_5_an_older_plan_json_through_judge_story`.

**1.1.** Append to `tests/test_writer_pacing.py`:

```python
# --- WT7, Review Focus 3, 4, 5: the critic's chained Motion patch line (WP4, WP5, D6) -----------

MOTION = dlg.MOTION_LINE % ("motion", "Motion")
CRITIC_CLAUSE = (
    " On a panel with a Dialogue: line, the pipeline inserts the spoken words right after the "
    "first sentence about what the speaker does, so keep everything the speaker does before "
    "the line in that first sentence and everything they do after it in a later sentence.")
CATALOG = ["- fast-motion: x"]


def test_wt7_the_critic_clause(ws):
    assert se.CRITIC_SPEAKING_MOTION_CLAUSE == CRITIC_CLAUSE
    assert "slowly" not in CRITIC_CLAUSE.lower() and "no adverbs" not in CRITIC_CLAUSE
    assert re.findall(r"@@[A-Z_]+@@", CRITIC_CLAUSE) == []
    assert se.critic_field_lines("chained", None, "speech", True, speaking=True).split("\n")[0] == (
        MOTION + CRITIC_CLAUSE)
    for mode in ("shots", "no_stills"):
        assert se.critic_field_lines(mode, None, "speech", True, speaking=True) == (
            se.critic_field_lines(mode, None, "speech", True)), mode
    assert se.critic_field_lines("chained", None, False, False, speaking=True) == (
        se.critic_field_lines("chained", None, False))
    for mode in ("chained", "shots", "no_stills"):
        assert se.critic_field_lines(mode, None) == se.critic_field_lines(
            mode, None, True, False, False), mode
    plan = _json("hockey-2x145-f", "plan.json")
    text = _read("hockey-2x145-f", "story.md")
    for for_judge in (False, True):
        prompt = se.build_critic_prompt(plan, text, ([], []), narration="speech",
                                        for_judge=for_judge)
        assert "\n" + MOTION + CRITIC_CLAUSE + "\n" in prompt, for_judge
    _c, quiet, _parts, quiet_text, _p = dlg._story(ws, "chained", 3)
    for narration in (True, "speech"):
        assert CRITIC_CLAUSE not in se.build_critic_prompt(quiet, quiet_text, ([], []),
                                                           narration=narration), narration


def test_review_focus_3_a_silent_chained_movie_gets_pacing_and_no_speech_point(ws):
    ctx, plan, parts, text, _p = dlg._story(ws, "chained", 3, plan_mut=dlg._speaking(2),
                                            ctx_kw={"narration": False})
    assert [b["speaker"] for b in plan["beats"]] == ["", "", ""]
    for k in (1, 2, 3):
        prompt = se.build_panel_prompt(ctx, plan, parts, k)
        assert prompt.count(se.PACING_SENTENCE) == 1, k
        assert "speaks the dialogue" not in prompt and "\ndialogue: " not in prompt, k
    assert "are:\n" + MOTION + "\nPreserve" in se.build_critic_prompt(plan, text, ([], []),
                                                                      narration=False)
    hockey = _json("hockey-2x145-f", "plan.json")
    prompt = se.build_critic_prompt(hockey, _read("hockey-2x145-f", "story.md"), ([], []),
                                    narration=False)
    assert "are:\n" + MOTION + "\nPreserve" in prompt and CRITIC_CLAUSE not in prompt


def test_review_focus_4_the_lora_catalog_line_stays_first(ws):
    lines = se.critic_field_lines("chained", CATALOG, "speech", True, speaking=True)
    before = se.critic_field_lines("chained", CATALOG, "speech", True)
    assert lines == before.replace("\n" + MOTION + "\n", "\n" + MOTION + CRITIC_CLAUSE + "\n")
    assert lines.count(CRITIC_CLAUSE) == 1
    assert lines.startswith('- target "plan", field "lora", index 0 for the global picks')
    prompt = se.build_critic_prompt(_json("hockey-2x145-f", "plan.json"),
                                    _read("hockey-2x145-f", "story.md"), ([], []), CATALOG,
                                    narration="speech")
    assert ("\n- fast-motion: x\n" + MOTION + CRITIC_CLAUSE + "\n" + dlg.DIALOGUE_FIELD_LINE
            + "\n") in prompt


def test_review_focus_5_an_older_plan_json_through_judge_story():
    text = _read("hockey-2x145-f", "story.md")
    older = _json("hockey-2x145-f", "plan.json")
    del older["spoken_lines"]
    for beat in older["beats"]:
        del beat["speaker"]
        del beat["lines"]
    prompt = se.build_critic_prompt(older, text, ([], []), for_judge=True)
    assert "are:\n" + MOTION + "\n" + dlg.DIALOGUE_FIELD_LINE + "\nPreserve" in prompt
    assert CRITIC_CLAUSE not in prompt
    mixed = copy.deepcopy(older)
    mixed["beats"][1]["speaker"] = "c1"
    assert ("are:\n" + MOTION + CRITIC_CLAUSE + "\n" + dlg.DIALOGUE_FIELD_LINE + "\nPreserve") in (
        se.build_critic_prompt(mixed, text, ([], []), for_judge=True))
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_writer_pacing.py 2>&1 | grep -E '^FAILED|passed|failed'
```

Expected: `3 failed, 11 passed`. WT7 fails with `AttributeError: module 'story_engine_for_pacing' has no attribute 'CRITIC_SPEAKING_MOTION_CLAUSE'`; Review Focus 4 with `TypeError: critic_field_lines() got an unexpected keyword argument 'speaking'`; Review Focus 5 with an `AssertionError` on the plan whose beat 2 has a speaker (the plan without speakers already passes its first half). Review Focus 3 passes already: it pins what Task 1 gave a silent movie and what the `narration is not False` guard must keep (no clause when nobody may speak).

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py` (WP4, the constant): replace this text, which occurs exactly once:

```python
    "makes that character the panel's speaker. This is the only patch that adds spoken words.")
```

with:

```python
    "makes that character the panel's speaker. This is the only patch that adds spoken words.")
# Writer pacing spec WP4, D6: a chained Motion patch on a speaking panel keeps the speech point.
CRITIC_SPEAKING_MOTION_CLAUSE = (
    " On a panel with a Dialogue: line, the pipeline inserts the spoken words right after the "
    "first sentence about what the speaker does, so keep everything the speaker does before "
    "the line in that first sentence and everything they do after it in a later sentence.")
```

**3.2.** Edit `story_engine.py` (WP4, the signature and the docstring): replace this text, which occurs exactly once:

```python
def critic_field_lines(mode, catalog_lines, narration=True, spoken=False):
    """The allowed-patch lines of the critic prompt (dialogue spec 8.3): the lora line when
    catalog_lines is set, the Motion: (Prompt: in no_stills) line for a T2/T3 panel, and the
    dialogue line for a T1 panel unless the movie has no spoken lines; then, when the narrative
    quotes spoken lines (spoken), the Q1 dialogue line (narrative dialogue fidelity spec QL11)."""
```

with:

```python
def critic_field_lines(mode, catalog_lines, narration=True, spoken=False, speaking=False):
    """The allowed-patch lines of the critic prompt (dialogue spec 8.3): the lora line when
    catalog_lines is set, the Motion: (Prompt: in no_stills) line for a T2/T3 panel, and the
    dialogue line for a T1 panel unless the movie has no spoken lines; then, when the narrative
    quotes spoken lines (spoken), the Q1 dialogue line (narrative dialogue fidelity spec QL11).
    With speaking (the plan has a speaking beat) in chained mode, the Motion line ends with
    CRITIC_SPEAKING_MOTION_CLAUSE (writer pacing spec WP4)."""
```

**3.3.** Edit `story_engine.py` (WP4, the Motion/Prompt line): replace this text, which occurs exactly once:

```python
    label = "Prompt" if mode == "no_stills" else "Motion"
    lines.append('- target "panel", field "%s", index = the panel number, only for a panel with a '
                 "[hard] T2 or T3 problem: replacement is the panel's whole new %s: writer text, "
                 "identical to the current text except for the sentence or sentences that hold "
                 "the extra or missing action." % (label.lower(), label))
```

with:

```python
    label = "Prompt" if mode == "no_stills" else "Motion"
    motion = ('- target "panel", field "%s", index = the panel number, only for a panel with a '
              "[hard] T2 or T3 problem: replacement is the panel's whole new %s: writer text, "
              "identical to the current text except for the sentence or sentences that hold "
              "the extra or missing action." % (label.lower(), label))
    if speaking and mode == "chained" and narration is not False:
        motion += CRITIC_SPEAKING_MOTION_CLAUSE
    lines.append(motion)
```

The lora, dialogue and Q1 lines and their order are unchanged.

**3.4.** Edit `story_engine.py` (WP5, `build_critic_prompt`): replace this text, which occurs exactly once:

```python
        ("@@FIELD_LINES@@", critic_field_lines(plan["mode"], catalog_lines, narration,
                                               spoken=bool(plan.get("spoken_lines")))),
```

with:

```python
        ("@@FIELD_LINES@@", critic_field_lines(plan["mode"], catalog_lines, narration,
                                               spoken=bool(plan.get("spoken_lines")),
                                               speaking=any(b.get("speaker")
                                                            for b in plan["beats"]))),
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_writer_pacing.py tests/test_dialogue.py tests/test_story_engine.py tests/test_narrative_fidelity.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_judge_story.py tests/test_iterate_story.py 2>&1 | grep -E '^FAILED|passed|failed'
```

Expected: one `FAILED` line, `tests/test_story_engine.py::test_rst62_import_sets` (the known failure), then `1 failed, 353 passed, 1 skipped`. `test_rst22_critic_prompt`, `test_rst48_judge_story_patches`, `test_rst48b_judge_story_patches_rejects_a_malformed_plan`, DLG19, DLG22 and NF25 pass unchanged (spec 4.3 B: DLG19 calls `critic_field_lines(mode, None)`, so `speaking` is False, and its story has no speaker; NF25 names only the dialogue and Q1 lines). Then the compile check with `FILES` = `story_engine.py tests/test_writer_pacing.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_writer_pacing.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_writer_pacing.py
git commit -m "feat(story): the critic's chained Motion patch keeps the speech point on a speaking plan (WP4, WP5, WT7)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Design review, the test_mut26 re-baseline (test-only commit), WK1-WK6 and the WK7 hand-off

Implements spec 6 steps 3-5 (G5) and measures WK1, WK2, WK3 and WK6. It hands WK7 (the live runs, spec 5 and 6 step 6) and the PR note to the main thread. No production code changes in this task.

**Files:**
- Modify: `tests/test_movie_ui_builder.py` (`test_mut26_pipeline_files_are_unchanged` `:283-285`: spec 4.3 A "`BASELINE` becomes the feature commit's SHA, and the comment line ending `(narrative dialogue fidelity).` becomes `... (narrative dialogue fidelity), then to <sha> (writer pacing).`")

**Interfaces:**
- Consumes: the commits of Tasks 1 and 2.
- Produces: the final pass counts in `/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-26-writer-pacing/final-pytest.txt`.

- [ ] **Step 1: Design review (controller; spec 6 step 4).** Ask an Opus `design-reviewer` to review `git diff 88213da..HEAD -- qwen-agent-workspace` against the spec and this plan. Fix every finding in a new commit on the owning task's files before Step 2, then re-run that task's Step 4.

- [ ] **Step 2: Re-baseline test_mut26 to the last pipeline commit.**

```bash
SHA=$(git log -1 --format=%H -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py)
echo "$SHA"
python3 - "$SHA" <<'EOF'
import sys
sha = sys.argv[1]
path = "tests/test_movie_ui_builder.py"
with open(path, encoding="utf-8") as f:
    text = f.read()
old_comment = ("(narrative dialogue fidelity).\n"
               "    # This invariant holds from the new baseline.\n")
new_comment = ("(narrative dialogue fidelity), then to %s (writer pacing).\n"
               "    # This invariant holds from the new baseline.\n" % sha)
old_base = '    BASELINE = "ac23105738adee0b26ea9d391681f3abbaa26ab0"\n'
assert text.count(old_comment) == 1 and text.count(old_base) == 1
text = text.replace(old_comment, new_comment).replace(old_base, '    BASELINE = "%s"\n' % sha)
with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("re-based to", sha)
EOF
python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py -k mut26 2>&1 | tail -1
```

Expected: the SHA is Task 2's commit, the last one that touched a `PIPELINE_FILES` entry (`story_engine.py`), or the Step 1 fix commit if that touched one; then `re-based to <that SHA>`; then `1 passed, 11 deselected`.

- [ ] **Step 3: Commit (test-only; spec 0.3 G5).**

```bash
git add tests/test_movie_ui_builder.py
git diff --cached --name-only    # expected: only qwen-agent-workspace/tests/test_movie_ui_builder.py
git commit -m "test(movie-ui): re-baseline mut26 to the writer pacing pipeline commit" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4: WK1, the full suite against the baseline (about 12 minutes).**

```bash
D=/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-26-writer-pacing
python3 -m pytest tests/ -q -rA -p no:cacheprovider > $D/final-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt; tail -1 $D/final-pytest.txt
grep -E '^(FAILED|ERROR)' $D/final-pytest.txt
python3 tests/test_ltx_movie_offline.py 2>&1 | tail -1
diff <(grep -E '^PASSED' $D/baseline-pytest.txt | sort) <(grep -E '^PASSED' $D/final-pytest.txt | sort) | grep '^<' || echo "no lost pass"
```

Expected: the `FAILED` lines are exactly `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`. The passed count is the baseline's plus 14 (the functions of `tests/test_writer_pacing.py`: WT1-WT9 and Review Focus 1-5), plus 1 if `test_trt41a` failed in the baseline run only (see Before Task 1, Step 3; if it fails here instead, rerun it alone); the skipped count is unchanged. The offline script prints `OK n/n` with the baseline `n`. The last command prints `no lost pass` (no test is renamed). Any other difference: stop and report.

- [ ] **Step 5: WK2, WK3, the unchanged files and WK6.**

```bash
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' story_engine.py tests/test_writer_pacing.py tests/test_dialogue.py tests/test_story_engine.py tests/test_movie_ui_builder.py; done
git diff 88213da -- story_engine.py | grep -E '^\+\s*(import|from) ' || echo "no new import"
git diff --name-only 88213da -- character_lib.py bin/ltx-story-manifest bin/ltx-movie bin/judge-story bin/judge-clips bin/judge-stills movie_ui_lib.py static ltx2_mlx_video_skill.py | wc -l
git diff --name-only 88213da -- . ':(exclude)docs' | sed 's#^qwen-agent-workspace/##' | grep -v -E '^(story_engine\.py|tests/test_writer_pacing\.py|tests/test_story_engine\.py|tests/test_dialogue\.py|tests/test_movie_ui_builder\.py|tests/fixtures/writer_pacing/hockey-(2x145|1x241)-f/(case|manifest|parts|plan|story_checks)\.json|tests/fixtures/writer_pacing/hockey-(2x145|1x241)-f/story\.md)$' || echo "only the planned files"
python3 -m pytest -q -p no:cacheprovider tests/test_story_engine.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_dialogue.py -k "rst40 or rst41 or rst61 or s52 or s20 or casting or dk2 or dk3" 2>&1 | tail -1
```

Expected: `compiled 5` twice (WK2); `no new import` (WK3); `0` (spec 0.3 "Not changed"); `only the planned files`; then `passed` with no failure (WK6: `test_rst40`, `test_rst41`, `test_s52`, `tests/test_casting_regression.py`; WK2/WK3: `test_rst61`, `test_s20`, DK2, DK3).

- [ ] **Step 6: Hand-off of WK7 and the PR note (main thread or user; not an executor step).** After the merge:
  - Run spec Section 5 exactly: with `S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`, `R=$S/hockey/pacing` (new, empty) and the `qwen38-6bit` vllm-metal server on port 8177 started as `start_llm` in `$S/hockey/rerun/run.sh`, run both `bin/ltx-movie` commands of spec 5 with `--story-id hockey-2x145-p` and `--story-id hockey-1x241-p`, `bin/story-server stop` after each; then the three whisper transcripts and the contact sheets of spec 5.
  - Check pass criteria (a)-(f) of spec 5: both runs exit 0 with Phase 1 complete and no `Error:` line; no `Q1` in either `hard` list and the `Dialogue:` lines verbatim; the 2x145 panel-2 writer Motion has two or more action sentences and, in `manifest.json` `panels[1].motion_prompt`, `'says, "It\'s just FuboTV."'` comes before the skate-away sentence; whisper hears `norm(LINE1)` and `norm(LINE2)` (in order for 1x241); no tile before line 2 starts shows the player receding; a clearly visible ice spray in `sheet_2x145_p2.jpg` and `sheet_1x241.jpg`.
  - Record the exit codes, the `Dialogue:` lines, the panel-2 Motion and `motion_prompt`, the whisper JSONs and the four sheets in the PR or report, plus the not-gating items (whether each Motion says "at real-time speed" and names the spray in its stop sentence, the judge scores, any extra words whisper hears). If (c) fails because the writer bundled the actions again, record it and open the D3 (b) follow-up; if (e) fails while (c) holds, open a separate LTX timing investigation.
  - The PR description carries the spec 6 note, in substance: "Writer prompts only. Existing stories re-check and re-render exactly as before; a story regenerated with `--force-story` gets the new chained Motion instructions."

---

## Coverage

### Spec section to task

| Spec | Task(s) |
|---|---|
| 0.3 G1 (`story_engine.py`) | 1 (WP1-WP3), 2 (WP4, WP5) |
| 0.3 G2 (`tests/test_writer_pacing.py`) | 1, 2 |
| 0.3 G3 (fixtures, 4.2) | 1 |
| 0.3 G4 (existing tests, 4.3 A) | 1 (pacing test, DLG13) |
| 0.3 G5 (`test_mut26`) | 3 |
| 0.3 Not changed | 3 step 5 (the `git diff` checks); every task's Edits touch only the listed text |
| 0.5 WK1 | Before Task 1 (baseline), 3 step 4 |
| 0.5 WK2, WK3 | every task's compile check; 3 step 5 |
| 0.5 WK4 | 1 (WT1-WT4), 2 (WT7 for the critic side) |
| 0.5 WK5 | 1 (WT5, WT6) |
| 0.5 WK6 | 1 (WT8, WT9, and the step 4 legacy tests); 3 step 5 |
| 0.5 WK7 | 3 step 6 (hand-off) |
| D1, D2 | 1 (WP2, WP3) |
| D3, D4 | nothing is built (spec choice); WT5 pins the unchanged placement |
| D5 | 1 (WP1) |
| D6 | 2 (WP4, WP5) |
| WP1 | 1 step 3.1, 3.2 |
| WP2 | 1 step 3.3 |
| WP3 | 1 step 3.4 |
| WP4 | 2 steps 3.1-3.3 |
| WP5 | 2 step 3.4 |
| 3 interactions | 1 (writer rows; Review Focus 1 for the code-only round), 2 (critic, judge-story and `--no-narration` rows; Review Focus 3, 5) |
| 4.1 | 1, 2 (see the next table) |
| 4.2 | 1 steps 1.1-1.4 |
| 4.3 A | 1 steps 1.6, 1.7; 3 step 2 |
| 4.3 B, C | the step 4 runs of Tasks 1 and 2; 3 steps 4-5 |
| 5 | 3 step 6 (hand-off) |
| 6 rollout | Before Task 1 (snapshot, baseline); 1, 2 (feature commits); 3 (review, test-only re-baseline, WK1, WK7 and the PR note) |

### Test IDs and their owning task (each is owned by exactly one task)

| IDs | Task |
|---|---|
| WT1 (without the WP4 literal), WT2, WT3, WT4, WT5, WT6, WT8, WT9, Review Focus 1, Review Focus 2; the 4.3 A edits of `test_pacing_panel1_prompt_and_no_slowly` and DLG13 | 1 |
| WT7 (with WT1's WP4 literal), Review Focus 3, Review Focus 4, Review Focus 5 | 2 |
| MUT26 re-baseline; WK1, WK2, WK3, WK6 measured; WK7 hand-off | 3 |

## Plan decisions (where the spec is silent, conflicts with the task split, or needs a reading)

1. **WT1's `CRITIC_SPEAKING_MOTION_CLAUSE` assertion lives in WT7** (Task 2). WT1 checks all three new literals, but the WP4 constant only exists after Task 2; with WT1 in Task 1, Task 1's Step 4 could not pass. WT1 checks `PACING_SENTENCE`, `SPEAKING_CHAINED_MOTION_SENTENCE` and both key lines (and their no-"slowly", no-"no adverbs" and `@@`-token rules); WT7 checks the clause literal with the same three rules. Every assertion of WT1 is made once.
2. **Two feature commits instead of spec 6's single feature commit** (the task split: a reviewer can accept the writer contract and reject the critic clause). `test_mut26` is re-based, in its own test-only commit, to the last commit that touches a `PIPELINE_FILES` entry (Task 2's, or the Step 1 review fix), after the spec 6 step 4 design review (Task 3).
3. **The WP2 comment is wrapped into three comment lines at 100 columns**, with the spec's words unchanged, and the sentence added to the comment above `SPEAKING_ACTION_SENTENCE` wraps that comment onto two more lines. The spec gives each as one line; the file wraps every comment at 100 columns.
4. **The [PACE1] removal is checked by `grep -c "natural, real-time" story_engine.py` = `0`** (Task 1 step 4), in addition to WT1/WT2's "use plain action verbs with no adverbs of speed or manner" absence, because spec WP1 says the sentence "no longer appears anywhere in `story_engine.py`".
5. **The compile checks use `compile()` on `/usr/bin/python3` and `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`** (controller's rule), in addition to `test_rst61` (WK2's named verifier), because `py_compile` to `/dev/null` errors on macOS.
6. **Test-helper readings.** `_motion_key_line` takes the first prompt line starting with `"motion: "`; in a fix prompt (Review Focus 1) the previous-version block also has a `motion: ` line, so that test matches the key line as `"\n" + line + "\n"` instead. WT2 and WT4 call this module's `se.build_panel_prompt` on the ctx and plan that `dlg._story` built with `test_dialogue`'s own copy of `story_engine` (both copies load the same file). WT7's "the prompt does not contain the clause" for `dlg._story(ws, "chained", 3)` is checked with `narration` True and `"speech"`. WT9 also asserts that the recorded messages are the spec's stated lists (`([], [N7, N12, N1])` and `([], [N12])`), as `RECORDED_ADVISORY`.
7. **Five tests pass before their own task's Step 3** and say so in Step 2: WT4, WT5, WT6, WT8 and WT9 (Task 1), and Review Focus 3 (Task 2). Each pins behaviour the new code must leave exactly as it is.
8. **The `tests/test_writer_pacing.py` header imports `copy`, which only Task 2 uses** (Review Focus 5), so that Task 2 appends without editing the import block.

## Questions for controller

None. The spec's three decisions to confirm (8.2: C1, C2, C3) were ruled by the controller and stand as written.

## Spec defects found (for the spec author; none blocks this plan)

1. **WT1 mixes Task 1 and Task 2 constants** (Plan decision 1). Harmless with spec 6's single feature commit; with any split, the WP4 literal belongs to WT7.
2. **WP5's rationale is inaccurate.** It says `plan["beats"]` always exists "because every caller passes a normalized plan or a plan.json that `bin/judge-story` validated by schema". `bin/judge-story main_patches` checks only `plan.get("schema") == "ltx-movie.plan.v1"` (`bin/judge-story:360`), not a schema. The behaviour is still safe: a plan.json without `beats` raises `KeyError` earlier, in `build_critic_prompt`'s `plan_json` line, and a beat that is not an object raises `AttributeError` at `b.get`; `main_patches` catches both (`:372`) and exits 2 with its "not a plan.json" error, as `test_rst48b` pins today.
3. **WP2's comment is one line of about 200 characters** (Plan decision 3); cosmetic.

## Execution handoff

Plan complete and saved to `qwen-agent-workspace/docs/superpowers/plans/2026-10-26-writer-pacing.md`. Every Create/Append/Edit/Run block was replayed in order on a scratch `git archive` export of `88213da`. Each old text occurred exactly once at its turn, and each task's Step 2 run failed (and passed) exactly as its Expected line states. Each task's Step 4 run gave the stated counts, with `test_rst62_import_sets` the only failure. Every changed file compiled under Python 3.9.6 and 3.13. The full suite on a whole-repository export (1823 passed at `88213da`; 1838 after Task 2) lost no pass: it gained the 14 new tests, and the flaky, unrelated `test_trt41a_trace_cli_on_one_agent` failed in the baseline run only. The only failures after Task 2 were `test_d2` and `test_rst62`, and `tests/test_ltx_movie_offline.py` printed `OK 347/347` on both trees. Task 1's and Task 2's Step 4 baselines were also run read-only in the real working tree (354 and 339 passed at `88213da`), matching the export. Task 3's re-baseline script was dry-run on a dummy SHA. Please review the plan. Which execution approach would you prefer?

- **Subagent-driven**: a fresh subagent implements each task and a fresh reviewer checks it before the next one starts, then a whole-branch review at the end.
- **Native**: one session implements every task, then one fresh reviewer checks the whole branch.

For this plan I recommend **native**. It has three small tasks in one file, the only interface handed forward is `PACING_SENTENCE` and the test module header, and every block was replayed. A shipped mistake is caught by the WT tests long before the WK7 GPU runs.
