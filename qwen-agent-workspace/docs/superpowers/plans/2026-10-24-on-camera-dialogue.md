# On-Camera Dialogue and the Timing-Only Critic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every story panel an optional `Dialogue: <referring phrase>: <spoken words>` field that the robust story engine writes and checks and that `bin/ltx-story-manifest` composes into the LTX motion prompt as quoted, beat-mapped speech; make the engine's only repairable faults spoken timing (T1) and the amount of action (T2/T3), with at most 2 critic rounds that never touch camera directions, descriptive text or dialogue; and attach chained-mode character LoRAs from `plan.json` at one strength per character for the whole story.

**Architecture:** `character_lib.py` gains the Dialogue grammar (`parse_dialogue`, `split_fragments`, `dialogue_word_cap`, `clean_line`, `speech_text`), the widened camera-sentence classifier, quote-aware and name-aware `cast_text`, and the casting helpers; the engine and the manifest share them so they cannot disagree. `story_engine.py` coerces speaking beats in `normalize_plan`, pastes the facing and camera sentences, assembles `Dialogue:`, adds T1/T2/T3/N18/N19, reclassifies every other rule as hard-structural or advisory, ranks by blocking count, guards every patch sentence by sentence, and stops after 2 rounds. `bin/ltx-story-manifest` parses `Dialogue:`, refuses an over-cap line, composes beats plus a fixed acoustic sentence (`--speech-delivery` switches to `plain` or `beats-no-acoustic`), and in `--chain` attaches characters from `plan.json`; `bin/ltx-movie`, `bin/judge-story`, `bin/judge-clips` and `bin/judge-stills` get the flag, the text and the label.

**Tech Stack:** Python 3.13 (`python3`, pytest 8.3.4) and Python 3.9.6 (`/usr/bin/python3`, compile check only); standard library only in every touched module (Pillow only where it already is, `bin/ltx-story-manifest`); the fake `bin/qwen-agent`, fake `bin/judge-story` and plan/panel/critic builders of `tests/story_engine_testutil.py`.

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-10-24-on-camera-dialogue-design.md`, rev 3, commit `fed1107` (user decisions D1-D8; Q1-Q5 resolved; Section 11 approved). Every Edit below is written against branch `qwen-agent-redteam` at `fed1107`, whose code tree is the code tree of `289254d` (the spec's line numbers cite `289254d`; `9f1d5c1` and `fed1107` add only the spec). The spec is binding; this plan changes no design decision. Where the plan had to read the spec, or the spec was silent or self-contradictory, the reading is listed in "Plan decisions" at the end; the controller's rulings on its two open points are recorded in "Spec amendments".

## Global Constraints

From the spec, verbatim (section in brackets):

- [0.1] "The implementer makes no design decisions."
- [0.1 D6] "Only these are hard (they block or trigger a rewrite): (a) timing: the spoken words do not fit the clip; (b) amount of action: too many or too few actions for the clip. Everything else is advisory: reported to the user and the logs, never rewritten or removed automatically. A structural rule stays hard only when the pipeline literally cannot proceed. The critic preserves camera directions, descriptive text and Dialogue word for word. There are at most 2 critic rounds."
- [0.3] "**Cut from this spec:** the movie-ui `speech_delivery` Compose field. A/B testing is done from the CLI only. No change is made to `movie_ui_lib.py`, `static/movie-ui/*`, the movie-ui help fixtures or `test_movie_ui_builder.py:118-131`."
- [0.3] "**Not changed:** the legacy templates and the legacy Phase 1 path, including `_phase1_shots_finish` and `SHOTS_REWRITE_TEMPLATE` (Q2 resolution: the legacy shots loop **stays strict**); `ltx2_mlx_video_skill.py`; `bin/ltx-mlx-render`; `bin/ltx-story-images`; `lora_catalog.py`; `bin/qwen-agent`; `fleet_lib.py`; `movie_ui_lib.py`."
- [0.4] Out of scope: "CFG, modality or audio-guidance settings"; "Voicing narration"; "Automatic panel restructuring"; "Writer-supplied beats, comma splitting, `/` or `|` separators"; "The legacy engine's checks and shots rewrite loop"; "Multi-speaker panels and off-screen speakers"; "The stale manifest T5 warning (R9)"; "Plan-based casting attachment in shots or no_stills mode."
- [DK2] "`/usr/bin/python3` (3.9) and `python3` both `py_compile` every changed file."
- [DK3] "Import sets are unchanged (`test_rst62`, `test_character_lib.py:540-550`, `test_s20`)."
- [DK5] "Legacy outputs stay byte-identical: the `--story-legacy` Phase 1 prompt and argv (`test_rst40`); the `--story-legacy` dry run golden `tests/fixtures/casting_baseline/ltx_movie_dry_run.txt` ...; the v2 manifest golden (`test_ltx_story_manifest_chain.py::test_v2_golden_byte_identical`); plain delivery for an alias panel whose spoken words contain no cast phrase (DLG8)."
- [9.1] "`tests/test_dialogue.py`: Stdlib plus pytest. Modules are loaded by path, as in `tests/test_story_engine.py`. It uses `tests/story_engine_testutil.py`. Every `_Run` gets `story_dir` under `tmp_path`."
- [0.3 G9] Existing tests change only by "the edits of Section 9.2" (and 11.8); [R8] "Do not weaken assertions beyond the stated reasons."
- [0.3 G10, 12] "`tests/test_movie_ui_builder.py::test_mut26` `BASELINE` re-baseline, in a **separate test-only follow-up commit** after G1-G9 and G11 land."

Repository rules (the controller's; every task's requirements include them):

- Standard library only in every Python file this plan touches; every new or changed file must run on Python 3.9.6 and 3.13: no `match`, no `X | Y` type expressions, no `zip(strict=)`, no parenthesised context managers, no walrus operator, no `str.removeprefix`.
- Tests never use the real `HOME`, never render, never contact a model server, a daemon or the Anthropic API (`tests/conftest.py` already strips `QWEN_LTX_AUTOTUNE`; `tests/test_dialogue.py` adds the same autouse `story_env` fixture as `tests/test_story_engine.py`).
- Run tests as `cd /Users/reubenpatterson/local_agent_harness/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/<file>`; every pytest run prints a `pytest_asyncio` deprecation warning first, which is expected.
- Never stage `../.DS_Store`, `../.claude/`, `.claude/`, `../agent/__pycache__/` or the repo-root `../bin/`. Stage only the paths a task names and check `git diff --cached --name-only` before every commit. Never use `git stash`, `git reset` or `git checkout` of a path.
- Every commit message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (the commit commands below pass it as a second `-m`).
- Known pre-existing failures at `fed1107`, to be ignored when they fail exactly as at the baseline: `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike`, `tests/test_judge_clips.py::test_goal_default_prompt_byte_identical`, `tests/test_story_engine.py::test_rst62_import_sets` (fails on `bin/ltx-mlx-render`'s `struct` import, before it reaches the files this plan touches), `tests/test_story_server.py::test_s14_source_guards`. Interaction: Task 17 re-baselines `test_judge_clips.py::test_goal_default_prompt_byte_identical` to the new judge-clips system prompt (spec 9.2), so it passes from Task 17 on: the list is these four for Tasks 1-16 and three (without the judge-clips test) from Task 17 on, which is what Task 24 Step 4 expects.
- `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` diffs the pipeline files against a pinned commit, so it fails from Task 1's commit until Task 24 re-baselines it in its own test-only commit (spec fix 9, G10). No task before 24 runs or edits it.

House rules:

- `WS` = `/Users/reubenpatterson/local_agent_harness/qwen-agent-workspace`. The git root is one level up, so `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix. Run every command from `WS`.
- Every code block is copied exactly, byte for byte. A **Create** writes a new file whose whole content is the block. An **Append** adds two empty lines after the file's current last line (which ends with one newline), then the block. An **Edit** replaces one block of old text, which must occur exactly once in the file at that moment, with the new text; if the old text does not occur exactly once, stop and report: do not adapt it.
- The compile check in each task is this command, with the task's files as arguments; expected output is two lines, `compiled N` for 3.9 and then for 3.13:

```bash
for py in /usr/bin/python3 python3; do $py -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' FILES; done
```

## Review Focus

These five inputs are implied by the spec, are the ones most likely to hit a real user first, and no DLG/CA test exercises them. Each is pinned by a test in its owning task.

1. **A writer reply whose `dialogue` carries its own label, the speaker's phrase and curly quotes** (`dialogue: the courier: “Keep moving.”`, `The Courier: "Keep moving."`). Expected: the stored part is `Keep moving.`, so story.md says `Dialogue: the courier: Keep moving.` and nothing is voiced twice. Test: `test_review_focus_1_writer_dialogue_with_label_prefix_and_quotes` (Task 9).
2. **A spoken line that names another cast member, in a cast run** (`Dialogue: the woman in grey: Tell the ronin I am here.` with `--cast` for both). Expected: the speaker's trigger is inserted outside the quotes, no trigger is inserted inside them, and the character named only inside the quotes gets no LoRA on that panel. Test: `test_review_focus_2_a_spoken_line_that_names_another_cast_member` (Task 5).
3. **A `Dialogue:` line in a story rendered with `--pace equal`** (every `--no-narration` and `--speech-only` run; such a story.md has no `Narration:` lines at all). Expected: the manifest composes the speech and records `speech_source: "dialogue"`; it never asks for a Narration. Test: `test_review_focus_3_dialogue_with_equal_pace_and_no_narration` (Task 5).
4. **A clip shorter than the default** (`--frames 97`, 4.04 s). Expected: the engine's T1 and the manifest's refusal use the same cap (9 words for one sentence), so a 10-word line that passes at 6 s is caught in Phase 1, not first at Phase 3. Test: `test_review_focus_4_a_short_clip_uses_the_same_cap_in_engine_and_manifest` (Task 11).
5. **Spoken words outside ASCII, ending in `?` and `!`** (`¿Dónde está el abad? ¡Aquí!`). Expected: two fragments split at the sentence ends, five words counted, the characters written back byte for byte, and no `.` appended after `!`. Test: `test_review_focus_5_non_ascii_spoken_words` (Task 1).

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `character_lib.py` | Modify (Tasks 1-4, 6, 20) | Dialogue constants and helpers (DG1-DG5); `_is_camera_sentence(sentence, phrases=())` (CM1); `insert_speech(..., phrases=())`; `motion_problems(motion, phrases=())`; `cast_text(..., skip_quoted=False, match_names=False)`; `member_referenced`, `prefix_character_triggers`, `story_strength`; `_STORY_FIELD_RE` with `Dialogue`; S3 accepts Dialogue. |
| `bin/ltx-story-manifest` | Modify (Tasks 4, 5, 21) | `Dialogue:` label and parsing; `_spoken`; the cap error; proportional pace with Dialogue; composition with `speech_text`; `speech_source`; `--speech-delivery`; `_casting_plan`, `_plan_cast_names` and the chained cast pass; help and docstring text. |
| `story_engine.py` | Modify (Tasks 7-15, 22) | `StoryContext.clip_seconds`, `engine_seconds`; speaker coercion and `speech_notes`; plan prompt; writer keys, panel keys and panel prompt; pasted facing/camera sentences, `Dialogue:` assembly, CM4 dedupe; T1/T2/T3/N18/N19 and the Dialogue N16/N17; the D6 classes; `final_outcome`, ranking, `critic_loop`, `merge_repair`, report-only judge gate; patch whitelist and guards; re-check; critic prompt. |
| `bin/ltx-movie` | Modify (Tasks 6, 7, 18, 19, 21) | `_validate_story_md` accepts Dialogue; `clip_seconds` in `_story_context`; `--speech-delivery` and its pass-through; docstring, help and dry-run text. |
| `bin/judge-story` | Modify (Task 16) | `DEFAULT_GOAL`; `PATCH_FIELDS` ends with `"dialogue"`. |
| `bin/judge-clips` | Modify (Task 17) | The Dialogue rule sentence; `format_panel_text` with `Dialogue:`. |
| `bin/judge-stills` | Modify (Task 4) | `PANEL_LABEL_RE` and the field dict gain `Dialogue` (still a verbatim copy). |
| `tests/test_dialogue.py` | Create (Task 1), Append (Tasks 2-23) | DLG1-DLG27, DLG29-DLG34, DLG-H, DLG-K1, CA1-CA9, DK2, DK3 and Review Focus 1-5. |
| `tests/test_story_engine.py` | Modify (Tasks 7-15, 19) | The Section 9.2 edits. |
| `tests/test_casting_pipeline.py`, `tests/test_shots_mode.py` | Modify (Task 21) | The 11.8 strength edits (`test_p20`, `test_p21`, `test_s62`). |
| `tests/test_judge_story.py`, `tests/test_judge_clips.py` | Modify (Tasks 16, 17) | The goal-prompt re-baselines. |
| `tests/test_movie_ui_builder.py` | Modify (Task 24 only) | `test_mut26` `BASELINE`. |

The task order follows the interfaces: the shared character_lib grammar first, then the parsers and the manifest that consume it, then the engine from the plan outward (context and coercion, prompts, writer keys, assembly, rules, controller, patches, reclassification, critic text), then the judges and `bin/ltx-movie`, then casting attachment, then the offline merge gate and the test-only re-baseline. The suite stays green after every task except `test_mut26`, as stated above.

---

## Before Task 1: baseline record (controller; no code, no commit)

DK1 compares against the pass count recorded here. Nothing is written into the repository.

- [ ] **Step 1: Confirm the starting point.**

```bash
cd /Users/reubenpatterson/local_agent_harness/qwen-agent-workspace
git rev-parse --short HEAD                       # expected: fed1107
git status --short                               # expected: only ?? ../.claude/, ?? ../agent/__pycache__/, ?? ../bin/, ?? .claude/ (and ?? ../.DS_Store if present)
ls tests/test_dialogue.py 2>&1 | grep -c "No such file"   # expected: 1
wc -l < story_engine.py                          # expected: 2595
wc -l < character_lib.py                         # expected: 1204
wc -l < bin/ltx-story-manifest                   # expected: 816
grep -c "CRITIC_MAX_ROUNDS = 3" story_engine.py  # expected: 1
```

If any expected value differs, stop and report: every Edit below was written against this tree.

- [ ] **Step 2: Record the pytest and script baselines (about 10 minutes).**

```bash
D=/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-24-dialogue
mkdir -p $D
git rev-parse HEAD > $D/base-commit.txt
python3 -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
python3 tests/test_ltx_movie_offline.py 2>&1 | tail -1 | tee $D/baseline-offline.txt
```

Expected: the `FAILED` lines are exactly the four known pre-existing failures of Global Constraints; the offline script prints `OK n/n`. Write any other difference into `$D/baseline-notes.txt`; Task 24 compares against what is recorded here.

---

### Task 1: character_lib Dialogue grammar, fragments, word cap and beat delivery

Implements DG1, DG2, DG3, DG4, DG5. Tests DLG1, DLG2, DLG3 and Review Focus 5.

**Files:**
- Modify: `character_lib.py` (a new block right before `def panel_strengths(`)
- Create: `tests/test_dialogue.py`

**Interfaces:**
- Consumes: `character_lib._SENTENCE_SPLIT_RE`, `_QUOTES`, `speaker_prefix(narration)`, `speech_sentence(phrase, speech)` (all existing).
- Produces (in `character_lib`): `DIALOGUE_MAX_WORDS = 14`, `DIALOGUE_MAX_FRAGMENTS = 3`, `DIALOGUE_WORDS_PER_SECOND = 2.4`, `DIALOGUE_BEAT_SECONDS = 0.4`, `SPEECH_DELIVERIES = ("beats", "plain", "beats-no-acoustic")`, `DEFAULT_SPEECH_DELIVERY = "beats"`, `SPEECH_BEATS`, `ACOUSTIC_SENTENCE`, `NO_KNOWN_PHRASES`; `dialogue_word_cap(seconds, fragments=1) -> int`; `split_fragments(line) -> [str]`; `clean_line(text) -> str` (DG3 step 4 only); `_speaker_regex(phrase) -> compiled regex` (`^\s*<phrase words>\s*:\s*`, case-insensitive); `parse_dialogue(value, phrases) -> (phrase or None, line, problem or None)`; `speech_text(phrase, line, delivery="beats") -> str`. In `tests/test_dialogue.py`: the module header (`WS`, `_load(name, rel)`, `character_lib`, `se`, `story_manifest`, `ltx_movie`, `PNG_1X1`, the autouse `story_env` fixture and the `ws` fixture) that every later task appends to.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_dlg1_parse_dialogue`, `test_dlg2_fragments_and_word_cap`, `test_dlg3_speech_text`, `test_review_focus_5_non_ascii_spoken_words`.

**1.1.** Create `tests/test_dialogue.py`:

```python
"""Tests for on-camera dialogue (docs/superpowers/specs/2026-10-24-on-camera-dialogue-design.md,
Sections 9.1 and 11.8: DLG1-DLG34, DLG-H, DLG-K1 and CA1-CA9): the Dialogue: field, beat-mapped
speech in the LTX motion prompt, the timing-only critic and chained casting attachment.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py
Stdlib plus pytest. Every model call goes to the fake bin/qwen-agent of a temp workspace
(story_engine_testutil.make_ws) or to a monkeypatched seam; no test renders or reaches a model
server, a daemon or the Anthropic API, and every test runs under the autouse story_env fixture
(a temporary HOME, character library and LoRA catalog).
"""

import base64
import copy
import importlib.machinery
import json
import os
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


character_lib = _load("character_lib_for_dialogue", "character_lib.py")
se = _load("story_engine_for_dialogue", "story_engine.py")
story_manifest = _load("ltx_story_manifest_for_dialogue", "bin/ltx-story-manifest")
ltx_movie = _load("ltx_movie_for_dialogue", "bin/ltx-movie")

# A valid 1x1 PNG: bin/ltx-story-manifest only checks that each panel still opens.
PNG_1X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
                           "60e6kgAAAABJRU5ErkJggg==")
AC = ("The audio is clear close-mic dialogue with a subtle natural room tone; the dialogue takes "
      "priority over the quiet ambience.")
SPLIT = (", and a line has at most 3 sentences; shorten the line, or split it across alternating "
         "close-up panels (the speaker, then the listener, then the speaker again)")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


# --- DLG1-DLG3, Review Focus 5: the Dialogue grammar (DG1-DG5) ------------------------------

PHRASES = ["the courier", "the old monk"]


def test_dlg1_parse_dialogue():
    parse = character_lib.parse_dialogue
    assert parse("the old monk: You came far.", PHRASES) == ("the old monk", "You came far.", None)
    assert parse("  The Old   Monk :  You came far ", PHRASES) == (
        "the old monk", "You came far.", None)
    assert parse("the old monk: You came far.", ["the old", "the old monk"])[0] == "the old monk"
    assert parse('the courier: "Keep moving."', PHRASES) == ("the courier", "Keep moving.", None)
    assert parse("the courier: “Keep moving.”", PHRASES) == (
        "the courier", "Keep moving.", None)
    assert parse('the courier: He said "go" twice', PHRASES) == (
        "the courier", "He said 'go' twice.", None)
    assert parse("the courier: Are you there?", PHRASES)[1] == "Are you there?"
    assert parse("the stranger: Halt.", PHRASES) == (
        None, "", "names 'the stranger', which is no character's referring phrase; use one of: "
                  "'the courier', 'the old monk'")
    assert parse("the stranger: Halt.", []) == (
        None, "", "names 'the stranger', which is no character's referring phrase; use one of: "
                  "none (no --cast, no ## Characters section and no plan.json cast)")
    assert parse("Keep moving.", PHRASES) == (
        None, "", "has no speaker; write it as <referring phrase>: <the spoken words>")
    assert parse('the courier:  ""', PHRASES) == (None, "", "has a speaker but no words")
    seven = "the tall old man in the hat"
    assert parse(seven + ": Sit down.", [seven]) == (seven, "Sit down.", None)
    assert parse("   ", PHRASES) == (None, "", None)
    assert parse("", PHRASES) == (None, "", None)


def test_dlg2_fragments_and_word_cap():
    lib = character_lib
    assert lib.split_fragments("You came far. Rest here before the abbot sees you.") == [
        "You came far.", "Rest here before the abbot sees you."]
    assert lib.split_fragments("  Stop!  Who goes there?  ") == ["Stop!", "Who goes there?"]
    assert lib.split_fragments("No sentence end") == ["No sentence end"]
    assert lib.split_fragments("") == []
    for frames, caps in ((145, [14, 13, 12]), (121, [12, 11, 10]), (97, [9, 8, 7]),
                         (241, [14, 14, 14])):
        assert [lib.dialogue_word_cap(frames / 24.0, n) for n in (1, 2, 3)] == caps, frames
    assert lib.dialogue_word_cap(6.0) == 14


def test_dlg3_speech_text():
    lib = character_lib
    assert (lib.DIALOGUE_MAX_WORDS, lib.DIALOGUE_MAX_FRAGMENTS, lib.DIALOGUE_WORDS_PER_SECOND,
            lib.DIALOGUE_BEAT_SECONDS) == (14, 3, 2.4, 0.4)
    assert lib.SPEECH_DELIVERIES == ("beats", "plain", "beats-no-acoustic")
    assert lib.DEFAULT_SPEECH_DELIVERY == "beats"
    assert lib.SPEECH_BEATS == ("After a breath", "After a short pause")
    assert lib.ACOUSTIC_SENTENCE == AC
    assert lib.speech_text("the courier", "I carry a letter for the abbot.", "beats") == (
        'The courier says, "I carry a letter for the abbot." ' + AC)
    assert lib.speech_text("the old monk", "You came far. Rest here before the abbot sees you.",
                           "beats") == ('The old monk says, "You came far." After a breath, '
                                        '"Rest here before the abbot sees you." ' + AC)
    three = "Come in. Sit by the fire. He will see you."
    assert lib.speech_text("the old monk", three, "beats") == (
        'The old monk says, "Come in." After a breath, "Sit by the fire." After a short pause, '
        '"He will see you." ' + AC)
    assert lib.speech_text("the old monk", three, "beats-no-acoustic") == (
        'The old monk says, "Come in." After a breath, "Sit by the fire." After a short pause, '
        '"He will see you."')
    for line in ("Keep moving.", three, "Go"):
        assert lib.speech_text("the courier", line, "plain") == lib.speech_sentence(
            "the courier", line)
    assert lib.speech_text("the courier", "One. Two. Three. Four. Five.", "beats") == (
        'The courier says, "One." After a breath, "Two." After a short pause, '
        '"Three. Four. Five." ' + AC)
    assert lib.speech_text("the courier", "Keep moving.") == lib.speech_text(
        "the courier", "Keep moving.", "beats")


def test_review_focus_5_non_ascii_spoken_words():
    lib = character_lib
    line = lib.parse_dialogue("the courier: ¿Dónde está el abad? ¡Aquí!", ["the courier"])[1]
    assert line == "¿Dónde está el abad? ¡Aquí!"
    assert lib.split_fragments(line) == ["¿Dónde está el abad?", "¡Aquí!"]
    assert len(line.split()) == 5
    assert lib.speech_text("the courier", line, "beats-no-acoustic") == (
        'The courier says, "¿Dónde está el abad?" After a breath, "¡Aquí!"')
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py 2>&1 | tail -3
```

Expected: `4 failed`, each with `AttributeError: module 'character_lib_for_dialogue' has no attribute ...` (`parse_dialogue`, `split_fragments`, `DIALOGUE_MAX_WORDS`).

- [ ] **Step 3: Implement.**

**3.1.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
def panel_strengths(names, members, character_strength, shots=False):
```

with:

```python
# On-camera dialogue (docs/superpowers/specs/2026-10-24-on-camera-dialogue-design.md Section 3):
# a panel's Dialogue: field is "<referring phrase>: <the spoken words>"; bin/ltx-story-manifest
# splits the words at sentence ends and writes them into the motion prompt with fixed beats and a
# fixed acoustic sentence, so LTX voices each fragment once.
DIALOGUE_MAX_WORDS = 14
DIALOGUE_MAX_FRAGMENTS = 3
DIALOGUE_WORDS_PER_SECOND = 2.4
DIALOGUE_BEAT_SECONDS = 0.4          # clip time each beat between fragments consumes
SPEECH_DELIVERIES = ("beats", "plain", "beats-no-acoustic")
DEFAULT_SPEECH_DELIVERY = "beats"
SPEECH_BEATS = ("After a breath", "After a short pause")   # before fragment 2, before fragment 3
ACOUSTIC_SENTENCE = ("The audio is clear close-mic dialogue with a subtle natural room tone; "
                     "the dialogue takes priority over the quiet ambience.")
NO_KNOWN_PHRASES = "none (no --cast, no ## Characters section and no plan.json cast)"


def dialogue_word_cap(seconds, fragments=1):
    """The most words a spoken line of `fragments` sentences may have in a clip of `seconds`
    (DG2): 2.4 words a second, less 0.4 s for each beat between fragments, never above 14."""
    return min(DIALOGUE_MAX_WORDS,
               int(DIALOGUE_WORDS_PER_SECOND * (seconds - DIALOGUE_BEAT_SECONDS * (fragments - 1))
                   + 1e-9))


def split_fragments(line):
    """The sentences of a spoken line, split at sentence ends (DG4)."""
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(line.strip()) if s.strip()]


def clean_line(text):
    """A spoken line with one surrounding pair of straight or curly double quotes removed, every
    other double quote turned into an apostrophe and whitespace collapsed (DG3 step 4)."""
    line = (text or "").strip()
    for left, right in (('"', '"'), ("“", "”")):
        if len(line) >= 2 and line.startswith(left) and line.endswith(right):
            line = line[1:-1].strip()
            break
    for quote in _QUOTES:
        line = line.replace(quote, "'")
    return " ".join(line.split())


def _speaker_regex(phrase):
    """The phrase, case-insensitive and whitespace-tolerant, then a colon, at the start of a
    text (DG3 step 2)."""
    return re.compile(r"^\s*" + r"\s+".join(re.escape(w) for w in phrase.split()) + r"\s*:\s*",
                      re.IGNORECASE)


def parse_dialogue(value, phrases):
    """(phrase, line, problem) for a Dialogue: value (DG3). phrase is the known phrase, as given,
    that the value starts with (most words first, then longest); line is the spoken words,
    cleaned, ending in . ! or ?. An empty value gives (None, "", None); a value that names no
    known phrase, or has no words, gives (None, "", problem)."""
    text = " ".join((value or "").split())
    if not text:
        return None, "", None
    for phrase in sorted((p for p in phrases if p.split()),
                         key=lambda p: (-len(p.split()), -len(p), p.lower())):
        match = _speaker_regex(phrase).match(text)
        if match:
            break
    else:
        found = speaker_prefix(text)
        if found:
            known = ", ".join(repr(p) for p in phrases) if phrases else NO_KNOWN_PHRASES
            return None, "", ("names %r, which is no character's referring phrase; use one of: %s"
                              % (found[0], known))
        return None, "", "has no speaker; write it as <referring phrase>: <the spoken words>"
    line = clean_line(text[match.end():])
    if not line:
        return None, "", "has a speaker but no words"
    if line[-1:] not in ".!?":
        line += "."
    return phrase, line, None


def speech_text(phrase, line, delivery=DEFAULT_SPEECH_DELIVERY):
    """The motion-prompt text for a spoken line (DG5). beats: '<Phrase> says, "<fragment 1>"',
    then ' <beat>, "<fragment n>"' for each later fragment (at most three; the rest join the
    third), then ACOUSTIC_SENTENCE; beats-no-acoustic leaves that sentence out; plain is
    speech_sentence's '<Phrase> says: "<line>"'."""
    fragments = split_fragments(line)
    if len(fragments) > DIALOGUE_MAX_FRAGMENTS:
        fragments = (fragments[:DIALOGUE_MAX_FRAGMENTS - 1]
                     + [" ".join(fragments[DIALOGUE_MAX_FRAGMENTS - 1:])])
    if delivery == "plain":
        return speech_sentence(phrase, line)
    text = phrase[:1].upper() + phrase[1:] + ' says, "' + fragments[0] + '"'
    for i in range(1, len(fragments)):
        text += " " + SPEECH_BEATS[i - 1] + ', "' + fragments[i] + '"'
    return text if delivery == "beats-no-acoustic" else text + " " + ACOUSTIC_SENTENCE


def panel_strengths(names, members, character_strength, shots=False):
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_character_lib.py tests/test_shots_mode.py 2>&1 | tail -1
```

Expected: `passed`, with no failure. Then the compile check with `FILES` = `character_lib.py tests/test_dialogue.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add character_lib.py tests/test_dialogue.py
git diff --cached --name-only    # expected: qwen-agent-workspace/character_lib.py, qwen-agent-workspace/tests/test_dialogue.py
git commit -m "feat(dialogue): character_lib Dialogue grammar, fragments, word cap and beat delivery (DG1-DG5, DLG1-DLG3)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: character_lib camera-sentence classifier and phrase-aware motion_problems

Implements CM1 (and the `motion_problems`/`shots_violations` parts of G1). Tests DLG5, DLG34.

**Files:**
- Modify: `character_lib.py`
- Modify: `tests/test_dialogue.py`

**Interfaces:**
- Consumes: `character_lib.SHOTS_PERSON_NOUNS`, `SHOTS_ANIMAL_NOUNS`, `_WORD_RE`, `_POSSESSIVE_RE`, `phrase_occurs`, `CharacterError`, `_CAMERA_SENTENCE_RE`, `_CAMERA_TERM_RE` (existing); `se.CAMERA_SENTENCES`.
- Produces (in `character_lib`): `_CAMERA_WIDE_TERM_RE`, `_PRONOUN_RE`, `_PERSON_WORDS`; `_refers_to_person(sentence, phrases) -> bool`; `_is_camera_sentence(sentence, phrases=()) -> bool`; `motion_problems(motion, phrases=()) -> [(rule, detail)]`; `shots_violations` now classifies Motion sentences with `humans + animals`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_dlg5_camera_sentence_classifier`, `test_dlg34_motion_problems_with_phrases`.

Append to `tests/test_dialogue.py`:

```python
# --- DLG5, DLG34: camera sentences (CM1) ----------------------------------------------------

def test_dlg5_camera_sentence_classifier():
    cam = character_lib._is_camera_sentence
    assert cam("Slowly the lens drifts across the empty quay.")
    assert cam("A close-up of the sealed letter.")
    assert not cam("He turns toward the camera.")
    assert not cam("The courier faces the camera.", ["the courier"])
    assert not cam("The waves pan out across the bay.")
    assert cam("A wide shot of the harbour.", ["the monk!"])          # a CharacterError is skipped
    for _key, sentence in se.CAMERA_SENTENCES:
        assert cam(sentence), sentence
        assert cam(sentence, PHRASES), sentence
    for tail in ("Static camera.", "Slow push-in.", "Handheld, slow pan left.", "He stays static."):
        assert cam(tail), tail
    for tail in ("He kneels.", "The robber takes the shot."):
        assert not cam(tail), tail


def test_dlg34_motion_problems_with_phrases():
    motion = "The courier raises the sealed letter. The courier faces the camera."
    two = ("S5 one action", "Motion: has 2 action sentences; it must have exactly one, optionally "
                            "followed by a camera sentence")
    assert character_lib.motion_problems(motion) == []
    assert character_lib.motion_problems(motion, ["the courier"]) == [two]
    text = '# S\n\n## Characters\n- "the courier": %s.\n' % seu.COURIER
    panel = {"number": 1, "title": "One", "image": "The courier waits.", "motion": motion,
             "narration": "It rained.", "prompt": "", "dialogue": ""}
    assert "panel 1: %s: %s" % two in character_lib.shots_violations(text, [panel], 1, [])
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k "dlg5 or dlg34" 2>&1 | tail -3
```

Expected: `2 failed`: `test_dlg5` with `TypeError: _is_camera_sentence() takes 1 positional argument but 2 were given`, `test_dlg34` with `TypeError: motion_problems() takes 1 positional argument but 2 were given`.

- [ ] **Step 3: Implement.**

**3.1.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
_CAMERA_TERM_RE = re.compile(r"\b(?:camera|shot|push-in|pull-back|pans?|tilts?|zooms?|dolly|"
                             r"tracking|static|locked-off|handheld)\b", re.IGNORECASE)
```

with:

```python
_CAMERA_TERM_RE = re.compile(r"\b(?:camera|shot|push-in|pull-back|pans?|tilts?|zooms?|dolly|"
                             r"tracking|static|locked-off|handheld)\b", re.IGNORECASE)
# Dialogue spec CM1: a longer sentence is a camera sentence too when it uses one of these terms
# and refers to no person (no cast phrase, no person or animal noun and no pronoun).
_CAMERA_WIDE_TERM_RE = re.compile(r"\b(?:cameras?|lens|dolly|dollies|push-in|pull-back|"
                                  r"extreme close-up|medium close-up|close-up|wide shot|medium shot|"
                                  r"tracking shot|handheld|locked-off|framing)\b", re.IGNORECASE)
_PRONOUN_RE = re.compile(r"\b(?:he|she|they|him|her|them|his|hers|their|theirs|himself|herself|"
                         r"themselves)\b", re.IGNORECASE)
_PERSON_WORDS = SHOTS_PERSON_NOUNS | SHOTS_ANIMAL_NOUNS
```

**3.2.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
def _is_camera_sentence(sentence):
    """A camera sentence (shots spec 4.3 S5; shots rules v2 spec 3.6): it starts with "camera"
    or "the camera", or it has at most _CAMERA_SHORT_MAX_WORDS words and contains a camera term
    ("Static camera.", "Slow push-in.")."""
    return bool(_CAMERA_SENTENCE_RE.match(sentence)
                or (len(sentence.split()) <= _CAMERA_SHORT_MAX_WORDS
                    and _CAMERA_TERM_RE.search(sentence)))
```

with:

```python
def _refers_to_person(sentence, phrases):
    """True when a sentence names one of phrases (a phrase that is not a valid referring phrase is
    skipped), a person or animal noun (possessive removed) or a pronoun (dialogue spec CM1)."""
    for phrase in phrases:
        try:
            if phrase_occurs(sentence, phrase):
                return True
        except CharacterError:
            continue
    if any(_POSSESSIVE_RE.sub("", word.lower()) in _PERSON_WORDS
           for word in _WORD_RE.findall(sentence)):
        return True
    return bool(_PRONOUN_RE.search(sentence))


def _is_camera_sentence(sentence, phrases=()):
    """A camera sentence (shots spec 4.3 S5; shots rules v2 spec 3.6; dialogue spec CM1): it
    starts with "camera" or "the camera"; or it has at most _CAMERA_SHORT_MAX_WORDS words and
    contains a camera term ("Static camera.", "Slow push-in."); or it contains a wide camera term
    ("A close-up of the sealed letter.") and refers to no person (_refers_to_person with
    phrases, so "The courier faces the camera." is an action when "the courier" is a phrase)."""
    return bool(_CAMERA_SENTENCE_RE.match(sentence)
                or (len(sentence.split()) <= _CAMERA_SHORT_MAX_WORDS
                    and _CAMERA_TERM_RE.search(sentence))
                or (_CAMERA_WIDE_TERM_RE.search(sentence)
                    and not _refers_to_person(sentence, phrases)))
```

**3.3.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
def motion_problems(motion):
    """[(rule, detail)] for one shots-mode Motion: text (spec 4.3 S5; S4 is advisory,
    motion_length_advisory). A camera sentence
    (_is_camera_sentence) is not an action sentence."""
    problems = []
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(motion.strip()) if s.strip()]
    actions = [s for s in sentences if not _is_camera_sentence(s)]
```

with:

```python
def motion_problems(motion, phrases=()):
    """[(rule, detail)] for one shots-mode Motion: text (spec 4.3 S5; S4 is advisory,
    motion_length_advisory). A camera sentence
    (_is_camera_sentence, with phrases) is not an action sentence."""
    problems = []
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(motion.strip()) if s.strip()]
    actions = [s for s in sentences if not _is_camera_sentence(s, phrases)]
```

**3.4.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
                    for rule, detail in motion_problems(p["motion"])]
```

with:

```python
                    for rule, detail in motion_problems(p["motion"], humans + animals)]
```

**3.5.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
                sentences = [s for s in sentences if not _is_camera_sentence(s)]
```

with:

```python
                sentences = [s for s in sentences if not _is_camera_sentence(s, humans + animals)]
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_character_lib.py tests/test_shots_mode.py 2>&1 | tail -1
python3 -m pytest -q -p no:cacheprovider tests/test_story_engine.py -k "rs4 or rst20 or rst21 or rst19" 2>&1 | tail -1
```

Expected: both `passed` with no failure (`test_s6`, `test_s7`, `test_s91`, `test_s97` and `test_rs4_constants` pass unchanged, spec 9.2 C). Compile check with `FILES` = `character_lib.py tests/test_dialogue.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add character_lib.py tests/test_dialogue.py
git diff --cached --name-only
git commit -m "feat(dialogue): camera sentences by wide term with no person; phrase-aware motion_problems (CM1, DLG5, DLG34)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: character_lib speech placement and quote-aware casting

Implements DG6 (`insert_speech` with `phrases`; `cast_text(skip_quoted)`). Tests DLG4, DLG6.

**Files:**
- Modify: `character_lib.py`
- Modify: `tests/test_dialogue.py`

**Interfaces:**
- Consumes: Task 2's `_is_camera_sentence(sentence, phrases=())`.
- Produces: `insert_speech(text, sentence, phrases=()) -> str` (inserts before the trailing run of camera sentences, never before sentence 1); `cast_text(text, members, insert=None, skip_quoted=False) -> (text, names)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_dlg4_insert_speech_placement`, `test_dlg6_cast_text_skip_quoted`.

Append to `tests/test_dialogue.py`:

```python
# --- DLG4, DLG6: placement and triggers (DG6) -----------------------------------------------

def _members(story_env, *names):
    """Resolved CastMembers for the test library characters kyra and ronin."""
    for name in names:
        {"kyra": seu.kyra, "ronin": seu.ronin}[name](story_env["lib"])
    return character_lib.resolve_cast([(None, name) for name in names])


def test_dlg4_insert_speech_placement():
    lib = character_lib
    said = 'The courier says, "Go."'
    motion = "The courier raises the letter. The courier faces the camera. The camera stays static."
    assert lib.insert_speech(motion, said, ["the courier"]) == (
        "The courier raises the letter. The courier faces the camera. " + said
        + " The camera stays static.")
    assert lib.insert_speech(motion, said) == (
        "The courier raises the letter. " + said + " The courier faces the camera. The camera "
        "stays static.")
    run = "The courier runs. The camera slowly pushes in. The camera holds."
    assert lib.insert_speech(run, said, ["the courier"]) == (
        "The courier runs. " + said + " The camera slowly pushes in. The camera holds.")
    assert lib.insert_speech("The camera stays static. The camera holds.", said) == (
        "The camera stays static. " + said + " The camera holds.")
    assert lib.insert_speech("The camera stays static.", said) == "The camera stays static. " + said
    he = 'He says: "Go."'
    assert lib.insert_speech("He runs. The camera tracks alongside the movement.", he) == (
        'He runs. He says: "Go." The camera tracks alongside the movement.')
    assert lib.insert_speech("He runs. He jumps.", he) == 'He runs. He jumps. He says: "Go."'


def test_dlg6_cast_text_skip_quoted(story_env):
    members = _members(story_env, "kyra", "ronin")
    text = 'The woman in grey says, "Tell the ronin the woman in grey is here."'
    assert character_lib.cast_text(text, members, skip_quoted=True) == (
        'The kyrawmn woman in grey says, "Tell the ronin the woman in grey is here."', ["kyra"])
    assert character_lib.cast_text(text, members) == (
        'The kyrawmn woman in grey says, "Tell the roninmn ronin the kyrawmn woman in grey is '
        'here."', ["kyra", "ronin"])
    assert character_lib.cast_text('"The ronin waits."', members, skip_quoted=True) == (
        '"The ronin waits."', [])
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k "dlg4 or dlg6" 2>&1 | tail -3
```

Expected: `2 failed`, each with `TypeError` (`insert_speech() takes 2 positional arguments but 3 were given`; `cast_text() got an unexpected keyword argument 'skip_quoted'`).

- [ ] **Step 3: Implement.**

**3.1.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
def insert_speech(text, sentence):
    """text with sentence added: before a trailing camera sentence (_is_camera_sentence) when
    there is one, else at the end, so the line belongs to the action, not to the camera."""
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]
    if len(sentences) > 1 and _is_camera_sentence(sentences[-1]):
        return " ".join(sentences[:-1] + [sentence, sentences[-1]])
    return (text.rstrip() + " " + sentence).strip()
```

with:

```python
def insert_speech(text, sentence, phrases=()):
    """text with sentence added before the run of trailing camera sentences
    (_is_camera_sentence with phrases, so a pasted "<Speaker> faces the camera." stays with the
    action), never before the first sentence; at the end when there is no such run (dialogue
    spec DG6)."""
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]
    trailing = 0
    while (trailing < len(sentences)
           and _is_camera_sentence(sentences[len(sentences) - 1 - trailing], phrases)):
        trailing += 1
    if len(sentences) > 1 and trailing >= 1:
        at = max(len(sentences) - trailing, 1)
        return " ".join(sentences[:at] + [sentence] + sentences[at:])
    return (text.rstrip() + " " + sentence).strip()
```

**3.2.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
def cast_text(text, members, insert=None):
    """(text with each cast phrase's trigger inserted, sorted names of the members found).
    Longest phrase first; a match overlapping an already-claimed span is ignored; an
    occurrence that already carries the trigger is counted but not re-inserted (spec 3.6).
    insert: if given, a set of names; every member still claims its spans, but only these
    members get a trigger and are reported."""
    found = []
    for member in sorted(members, key=lambda m: (-len(m.phrase), m.phrase.lower(), m.name)):
        for match in _phrase_regex(member.phrase, member.trigger).finditer(text):
            start, end = match.span()
            if any(start < e and s < end for s, e, _, _ in found):
                continue
```

with:

```python
def cast_text(text, members, insert=None, skip_quoted=False):
    """(text with each cast phrase's trigger inserted, sorted names of the members found).
    Longest phrase first; a match overlapping an already-claimed span is ignored; an
    occurrence that already carries the trigger is counted but not re-inserted (spec 3.6).
    insert: if given, a set of names; every member still claims its spans, but only these
    members get a trigger and are reported. skip_quoted: a match lying wholly inside a "..."
    span (a spoken line) is neither triggered nor reported (dialogue spec DG6)."""
    quoted = [m.span() for m in re.finditer(r'"[^"]*"', text)] if skip_quoted else []
    found = []
    for member in sorted(members, key=lambda m: (-len(m.phrase), m.phrase.lower(), m.name)):
        for match in _phrase_regex(member.phrase, member.trigger).finditer(text):
            start, end = match.span()
            if any(s <= start and end <= e for s, e in quoted):
                continue
            if any(start < e and s < end for s, e, _, _ in found):
                continue
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_character_lib.py tests/test_shots_mode.py tests/test_casting_pipeline.py 2>&1 | tail -1
```

Expected: `passed` with no failure (`test_spoken_narration_helpers` passes unchanged). Compile check with `FILES` = `character_lib.py tests/test_dialogue.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add character_lib.py tests/test_dialogue.py
git diff --cached --name-only
git commit -m "feat(dialogue): speech goes before the trailing camera run; cast_text can skip quoted spans (DG6, DLG4, DLG6)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The Dialogue: label in the three story parsers

Implements DG7 step 1, G7 and the `_STORY_FIELD_RE` part of G1 (spec 2.1). Tests DLG32.

**Files:**
- Modify: `bin/ltx-story-manifest`
- Modify: `character_lib.py`
- Modify: `bin/judge-stills`
- Modify: `tests/test_dialogue.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `bin/ltx-story-manifest._PANEL_LABEL_RE`, `character_lib._STORY_FIELD_RE` and `bin/judge-stills.PANEL_LABEL_RE` all equal `^(Image|Motion|Narration|Prompt|Style|Dialogue):\s*(.*)$`; every `_parse_prompts_md` panel dict gains `"dialogue"` (the joined `Dialogue:` text, `""` when absent), which every later task reads.

- [ ] **Step 1: Write the failing test.**

New test in this task: `test_dlg32_dialogue_label`.

Append to `tests/test_dialogue.py`:

```python
# --- DLG32: the Dialogue: label (DG7 step 1, G7) ---------------------------------------------

LABEL_PATTERN = r"^(Image|Motion|Narration|Prompt|Style|Dialogue):\s*(.*)$"
STORY_WITH_DIALOGUE = """# Gate

A courier reaches a temple gate.

## Panel 1 — Arrival
Image: The courier stands at the gate.
Motion: The courier raises the letter.
Dialogue: the courier: I carry a letter
for the abbot.
Narration: The bell had not yet rung.
"""
IMAGE_THEN_DIALOGUE = """# Gate

## Panel 1 — Arrival
Image: A temple gate at dusk.
Dialogue: the courier: I carry a letter.
Motion: The courier raises the letter.
"""


def _judge(name, rel):
    """A bin/judge-* script, loaded only by the tests that use it (they import anthropic and
    jsonschema, which collecting this module must not need)."""
    pytest.importorskip("anthropic")
    pytest.importorskip("jsonschema")
    return _load(name, rel)


def test_dlg32_dialogue_label(tmp_path):
    assert story_manifest._PANEL_LABEL_RE.pattern == LABEL_PATTERN
    assert character_lib._STORY_FIELD_RE.pattern == LABEL_PATTERN
    path = tmp_path / "story.md"
    path.write_text(STORY_WITH_DIALOGUE, encoding="utf-8")
    panel = story_manifest._parse_prompts_md(str(path))[1][0]
    assert (panel["image"], panel["motion"], panel["dialogue"], panel["narration"]) == (
        "The courier stands at the gate.", "The courier raises the letter.",
        "the courier: I carry a letter for the abbot.", "The bell had not yet rung.")
    plain = tmp_path / "plain.md"
    plain.write_text(STORY_WITH_DIALOGUE.replace(
        "Dialogue: the courier: I carry a letter\nfor the abbot.\n", ""), encoding="utf-8")
    assert story_manifest._parse_prompts_md(str(plain))[1][0]["dialogue"] == ""
    member = character_lib.CastMember("courier", "the courier", "courierx", "man", seu.COURIER,
                                      "/v.safetensors", None, None, None)
    assert character_lib.repair_cast_descriptions(IMAGE_THEN_DIALOGUE, [member]) == (
        IMAGE_THEN_DIALOGUE, [])
    judge_stills = _judge("judge_stills_for_dialogue", "bin/judge-stills")
    assert judge_stills.PANEL_LABEL_RE.pattern == LABEL_PATTERN
    parsed = judge_stills.parse_panels(STORY_WITH_DIALOGUE)[0]
    assert (parsed["image"], parsed["motion"], parsed["narration"]) == (
        "The courier stands at the gate.", "The courier raises the letter.",
        "The bell had not yet rung.")
```

- [ ] **Step 2: Run the test and confirm it fails.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k dlg32 2>&1 | tail -3
```

Expected: `1 failed`, an `AssertionError` on the first `pattern ==` line.

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
_PANEL_LABEL_RE = re.compile(r"^(Image|Motion|Narration|Prompt|Style):\s*(.*)$")
```

with:

```python
_PANEL_LABEL_RE = re.compile(r"^(Image|Motion|Narration|Prompt|Style|Dialogue):\s*(.*)$")
```

**3.2.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
    """Return (narrative, [{'title': str, 'text': str, 'image': str,
    'motion': str, 'narration': str, 'prompt': str, 'style': str}, ...]) parsed from a
    prompts.md file. Raises OSError if the file cannot be read.
```

with:

```python
    """Return (narrative, [{'title': str, 'text': str, 'image': str,
    'motion': str, 'narration': str, 'prompt': str, 'style': str, 'dialogue': str}, ...])
    parsed from a prompts.md file. Raises OSError if the file cannot be read.
```

**3.3.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
    image prompt. `style` is "" when the label never appears, so a story.md
    written before this field existed parses exactly as it did before.
    """
```

with:

```python
    image prompt. `style` is "" when the label never appears, so a story.md
    written before this field existed parses exactly as it did before.

    A `Dialogue:` label holds the panel's spoken line, "<referring phrase>: <the
    spoken words>" (docs/superpowers/specs/2026-10-24-on-camera-dialogue-design.md);
    `dialogue` is "" when the label never appears.
    """
```

**3.4.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
        fields = {"Image": [], "Motion": [], "Narration": [], "Prompt": [], "Style": []}
```

with:

```python
        fields = {"Image": [], "Motion": [], "Narration": [], "Prompt": [], "Style": [],
                  "Dialogue": []}
```

**3.5.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
        p["style"] = " ".join(fields["Style"])
```

with:

```python
        p["style"] = " ".join(fields["Style"])
        p["dialogue"] = " ".join(fields["Dialogue"])
```

**3.6.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
_STORY_FIELD_RE = re.compile(r"^(Image|Motion|Narration|Prompt|Style):\s*(.*)$")
```

with:

```python
_STORY_FIELD_RE = re.compile(r"^(Image|Motion|Narration|Prompt|Style|Dialogue):\s*(.*)$")
```

**3.7.** Edit `bin/judge-stills`: replace this text, which occurs exactly once:

```python
PANEL_LABEL_RE = re.compile(r"^(Image|Motion|Narration|Prompt|Style):\s*(.*)$")
```

with:

```python
PANEL_LABEL_RE = re.compile(r"^(Image|Motion|Narration|Prompt|Style|Dialogue):\s*(.*)$")
```

**3.8.** Edit `bin/judge-stills`: replace this text, which occurs exactly once:

```python
    Prompt: and Style: are recognized only to close the open field, then dropped
```

with:

```python
    Prompt:, Style: and Dialogue: are recognized only to close the open field, then dropped
```

**3.9.** Edit `bin/judge-stills`: replace this text, which occurs exactly once:

```python
        fields = {"Image": [], "Motion": [], "Narration": [], "Prompt": [], "Style": []}
```

with:

```python
        fields = {"Image": [], "Motion": [], "Narration": [], "Prompt": [], "Style": [],
                  "Dialogue": []}
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_judge_stills.py tests/test_shots_mode.py tests/test_casting_pipeline.py tests/test_casting_regression.py 2>&1 | tail -1
python3 tests/test_ltx_story_manifest_chain.py 2>&1 | tail -1
python3 tests/test_ltx_story_video.py 2>&1 | tail -1
```

Expected: the pytest line ends `passed` with no failure; the two scripts print `OK n/n` with the baseline counts. Compile check with `FILES` = `character_lib.py bin/ltx-story-manifest bin/judge-stills tests/test_dialogue.py`; expected `compiled 4` twice.

- [ ] **Step 5: Commit.**

```bash
git add bin/ltx-story-manifest character_lib.py bin/judge-stills tests/test_dialogue.py
git diff --cached --name-only
git commit -m "feat(dialogue): Dialogue: label in the manifest, character_lib and judge-stills parsers (DG7.1, DLG32)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: bin/ltx-story-manifest spoken lines: parsing, the cap, pace and beat composition

Implements DG7 steps 2-7, DG9, spec 2.5 and the manifest half of DG6 (`skip_quoted=True` in the cast pass). Tests DLG7, DLG8, DLG9, DLG10 and Review Focus 2 and 3.

**Files:**
- Modify: `bin/ltx-story-manifest`
- Modify: `tests/test_dialogue.py`

**Interfaces:**
- Consumes: Task 1's `parse_dialogue`, `split_fragments`, `dialogue_word_cap`, `DIALOGUE_MAX_FRAGMENTS`, `speech_text`; Task 3's `insert_speech(text, sentence, phrases)` and `cast_text(..., skip_quoted=True)`; Task 4's `p["dialogue"]`.
- Produces: the manifest flag `--speech-delivery {beats,plain,beats-no-acoustic}` (`args.speech_delivery`, default `"beats"`); `_spoken(args, prompt_texts, members) -> [(speaker or None, speech, source)] or None` (source `"dialogue"`, `"narration"` or `None`; `None` return after an `Error: panel %d: Dialogue: ...` line); manifest panels with a spoken line carry `"speaker"`, `"speech"`, `"speech_source"`. In `tests/test_dialogue.py`: `_manifest_ws(tmp_path, monkeypatch, story_id, text, plan=None, images=1) -> (story_md, [image paths], ws)`, `_manifest_argv(story_id, story_md, images, mode="chain", panels=2, frames=145, extra=()) -> argv`, `_read_manifest(ws, story_id) -> dict`, `CAST_PLAN`, `DG9_SETTING`, `CHAINED_DG9`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_dlg7_manifest_goldens`, `test_dlg8_narration_alias`, `test_dlg9_manifest_errors`, `test_dlg10_dialogue_wins_over_a_prefixed_narration`, `test_review_focus_2_a_spoken_line_that_names_another_cast_member`, `test_review_focus_3_dialogue_with_equal_pace_and_no_narration`.

Append to `tests/test_dialogue.py`:

```python
# --- DLG7-DLG10, Review Focus 2-3: bin/ltx-story-manifest speech (DG7, DG9) ---------------------

DG9_SETTING = ("The setting is a hilltop temple gate in modern Japan, worn stone steps underfoot, "
               "cedar trees behind, under low golden evening light.")
CAST_PLAN = {"schema": "ltx-movie.plan.v1", "cast": [
    {"id": "c1", "phrase": "the courier", "descriptor": seu.COURIER, "cast_name": None},
    {"id": "c2", "phrase": "the old monk", "descriptor": seu.MONK, "cast_name": None}],
    "beats": [{"cast": ["c1"]}, {"cast": ["c2"]}]}
CHAINED_DG9 = """# The Gate

A courier reaches a hilltop temple.

## Panel 1 — The Steps
Image: %s The courier climbs toward the gate.
Motion: The courier climbs the last worn step toward the gate. The camera stays static.
Narration: The bell had not yet rung.

## Panel 2 — At the Gate
Motion: The old monk lowers his broom and lifts his eyes. The old monk faces the camera. The camera stays static.
@@LINES@@
""" % DG9_SETTING
SHOTS_DG9 = """# The Letter

A courier brings a letter to a temple.

## Characters
- "the courier": %(courier)s.
- "the old monk": %(monk)s.

## Panel 1 — The Road
Image: %(setting)s The courier walks up the road. The shot is a wide shot.
Motion: The courier walks up the road toward the gate. The camera tracks alongside the movement.
Narration: The road was long.

## Panel 2 — The Stairs
Image: %(setting)s The courier climbs the stairs. The shot is a medium shot.
Motion: The courier climbs the worn stone stairs. The camera stays static.
Narration: The stairs were steep.

## Panel 3 — The Letter
Image: %(setting)s The courier is %(courier)s. The courier stands at the gate holding the sealed letter at chest height. The courier faces the camera. The shot is a medium close-up.
Motion: The courier raises the sealed letter toward the gate. The courier faces the camera. The camera stays static.
Dialogue: the courier: I carry a letter for the abbot.
Narration: The bell had not yet rung.
""" % {"courier": seu.COURIER, "monk": seu.MONK, "setting": DG9_SETTING}
NO_STILLS_DG9 = """# Shelter

A courier finds shelter.

## Panel 1 — Rain
Prompt: The courier runs through the rain toward the temple. The camera stays static.
Narration: The rain came suddenly.

## Panel 2 — Gate
Prompt: The courier reaches the temple gate and knocks twice. The camera stays static.
Narration: Someone was inside.

## Panel 3 — Door
Prompt: The old monk opens the heavy wooden door. The camera stays static.
Narration: The door creaked open.

## Panel 4 — Shelter
Prompt: The old monk sets down his broom as rain drips from the eaves. The old monk is %s. %s The shot is a close-up. The old monk faces the camera. The camera stays static.
Dialogue: the old monk: Come in. Sit by the fire. He will see you.
Narration: Inside, the fire was already lit.
""" % (seu.MONK, seu.TEMPLE)
OVER_CAP = "I carry a sealed letter from the harbour master for the abbot of this temple."


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


def test_dlg7_manifest_goldens(tmp_path, monkeypatch):
    chained = CHAINED_DG9.replace(
        "@@LINES@@", "Dialogue: the old monk: You came far. Rest here before the abbot sees you.")
    head = "The old monk lowers his broom and lifts his eyes. The old monk faces the camera. "
    expected = {
        "beats": head + 'The old monk says, "You came far." After a breath, "Rest here before the '
                        'abbot sees you." ' + AC + " The camera stays static.",
        "plain": head + 'The old monk says: "You came far. Rest here before the abbot sees you." '
                        "The camera stays static.",
        "beats-no-acoustic": head + 'The old monk says, "You came far." After a breath, "Rest here '
                                    'before the abbot sees you." The camera stays static.'}
    for delivery, motion in expected.items():
        story_md, images, ws = _manifest_ws(tmp_path, monkeypatch, "dlg7c", chained, plan=CAST_PLAN)
        extra = [] if delivery == "beats" else ["--speech-delivery", delivery]
        assert story_manifest.main(_manifest_argv("dlg7c", story_md, images, extra=extra)) == 0
        panels = _read_manifest(ws, "dlg7c")["panels"]
        assert panels[1]["motion_prompt"] == motion, delivery
        assert (panels[1]["speaker"], panels[1]["speech"], panels[1]["speech_source"],
                panels[1]["narration"], panels[1]["narration_words"]) == (
            "the old monk", "You came far. Rest here before the abbot sees you.", "dialogue", "",
            10)
        assert not {"speaker", "speech", "speech_source"} & set(panels[0])
    story_md, images, ws = _manifest_ws(tmp_path, monkeypatch, "dlg7s", SHOTS_DG9, images=3)
    assert story_manifest.main(_manifest_argv("dlg7s", story_md, images, mode="shots",
                                              panels=3)) == 0
    panel = _read_manifest(ws, "dlg7s")["panels"][2]
    assert panel["motion_prompt"] == (
        'The courier raises the sealed letter toward the gate. The courier faces the camera. The '
        'courier says, "I carry a letter for the abbot." ' + AC + " The camera stays static.")
    assert (panel["speech_source"], panel["narration"]) == ("dialogue", "The bell had not yet rung.")
    story_md, images, ws = _manifest_ws(tmp_path, monkeypatch, "dlg7n", NO_STILLS_DG9,
                                        plan=CAST_PLAN, images=0)
    assert story_manifest.main(_manifest_argv("dlg7n", story_md, images, mode="no_images",
                                              panels=4)) == 0
    panel = _read_manifest(ws, "dlg7n")["panels"][3]
    assert panel["motion_prompt"] == (
        "The old monk sets down his broom as rain drips from the eaves. The old monk is %s. %s The "
        'shot is a close-up. The old monk faces the camera. The old monk says, "Come in." After a '
        'breath, "Sit by the fire." After a short pause, "He will see you." %s The camera stays '
        "static." % (seu.MONK, seu.TEMPLE, AC))
    assert panel["speech"] == "Come in. Sit by the fire. He will see you."


def test_dlg8_narration_alias(tmp_path, monkeypatch):
    alias = CHAINED_DG9.replace(
        "Motion: The old monk lowers his broom and lifts his eyes. The old monk faces the camera. "
        "The camera stays static.\n@@LINES@@",
        "Motion: The courier runs. The camera tracks alongside the movement.\n"
        "Narration: the courier: Keep moving.")
    for delivery, motion in (
            ("beats", 'The courier runs. The courier says, "Keep moving." ' + AC
                      + " The camera tracks alongside the movement."),
            ("plain", 'The courier runs. The courier says: "Keep moving." The camera tracks '
                      "alongside the movement.")):
        story_md, images, ws = _manifest_ws(tmp_path, monkeypatch, "dlg8", alias, plan=CAST_PLAN)
        assert story_manifest.main(_manifest_argv(
            "dlg8", story_md, images, extra=["--speech-delivery", delivery])) == 0
        panel = _read_manifest(ws, "dlg8")["panels"][1]
        assert panel["motion_prompt"] == motion, delivery
        assert (panel["speaker"], panel["speech"], panel["speech_source"], panel["narration"],
                panel["narration_words"]) == ("the courier", "Keep moving.", "narration",
                                              "the courier: Keep moving.", 2)


def test_dlg9_manifest_errors(tmp_path, monkeypatch, capsys):
    tail = SPLIT
    cases = [
        ("Dialogue: the stranger: Halt.", 2, "",
         "Error: panel 2: Dialogue: names 'the stranger', which is no character's referring "
         "phrase; use one of: 'the courier', 'the old monk'\n"),
        ("Dialogue: the courier: " + OVER_CAP, 2, "",
         "Error: panel 2: Dialogue: is 15 words in 1 sentences; a 6.04-second clip fits at most "
         "14 words in 1 sentences" + tail + "\n"),
        ("Narration: the courier: " + OVER_CAP, 0,
         "WARNING: panel 2: the spoken Narration: is 15 words in 1 sentences; a 6.04-second clip "
         "fits at most 14 words in 1 sentences" + tail + "\n", ""),
        ("", 2, "",
         "Error: --pace proportional requires every panel to have a non-empty Narration or "
         "Dialogue field; panel 2 has neither\n"),
    ]
    for i, (lines, rc, out, err) in enumerate(cases):
        story_id = "dlg9-%d" % i
        story_md, images, ws = _manifest_ws(tmp_path, monkeypatch, story_id,
                                            CHAINED_DG9.replace("@@LINES@@", lines), plan=CAST_PLAN)
        capsys.readouterr()
        assert story_manifest.main(_manifest_argv(story_id, story_md, images)) == rc, lines
        captured = capsys.readouterr()
        assert out in captured.out, lines
        assert captured.err == err, lines
        assert os.path.exists(os.path.join(ws, "generated", "stories", story_id,
                                           "manifest.json")) == (rc == 0)


def test_dlg10_dialogue_wins_over_a_prefixed_narration(tmp_path, monkeypatch):
    both = CHAINED_DG9.replace(
        "Motion: The old monk lowers his broom and lifts his eyes. The old monk faces the camera. "
        "The camera stays static.\n@@LINES@@",
        "Motion: The courier waits at the gate. The camera stays static.\n"
        "Dialogue: the courier: Keep moving.\nNarration: the old monk: Wait.")
    story_md, images, ws = _manifest_ws(tmp_path, monkeypatch, "dlg10", both, plan=CAST_PLAN)
    assert story_manifest.main(_manifest_argv("dlg10", story_md, images)) == 0
    panel = _read_manifest(ws, "dlg10")["panels"][1]
    assert (panel["speaker"], panel["speech"], panel["speech_source"], panel["narration"]) == (
        "the courier", "Keep moving.", "dialogue", "the old monk: Wait.")
    assert panel["motion_prompt"] == ('The courier waits at the gate. The courier says, "Keep '
                                      'moving." ' + AC + " The camera stays static.")


def test_review_focus_2_a_spoken_line_that_names_another_cast_member(tmp_path, monkeypatch,
                                                                     story_env, capsys):
    _members(story_env, "kyra", "ronin")
    text = """# Quay

Two travellers on a quay.

## Panel 1 — One
Image: The woman in grey stands on the quay.
Motion: The woman in grey watches the ronin cross the quay. The camera stays static.
Narration: The tide was turning.

## Panel 2 — Two
Motion: The woman in grey lifts her chin. The woman in grey faces the camera. The camera stays static.
Dialogue: the woman in grey: Tell the ronin I am here.
"""
    story_md, images, ws = _manifest_ws(tmp_path, monkeypatch, "rf2", text)
    assert story_manifest.main(_manifest_argv("rf2", story_md, images, extra=[
        "--cast", "the woman in grey=kyra", "--cast", "the ronin=ronin"])) == 0
    panels = _read_manifest(ws, "rf2")["panels"]
    assert panels[1]["motion_prompt"] == (
        "The kyrawmn woman in grey lifts her chin. The kyrawmn woman in grey faces the camera. The "
        'kyrawmn woman in grey says, "Tell the ronin I am here." ' + AC + " The camera stays static.")
    assert [c["name"] for c in panels[1]["characters"]] == ["kyra"]
    assert [c["name"] for c in panels[0]["characters"]] == ["kyra", "ronin"]


def test_review_focus_3_dialogue_with_equal_pace_and_no_narration(tmp_path, monkeypatch):
    text = CHAINED_DG9.replace("Narration: The bell had not yet rung.\n", "").replace(
        "@@LINES@@", "Dialogue: the old monk: You came far.")
    story_md, images, ws = _manifest_ws(tmp_path, monkeypatch, "rf3", text, plan=CAST_PLAN)
    assert story_manifest.main(_manifest_argv("rf3", story_md, images,
                                              extra=["--pace", "equal"])) == 0
    panels = _read_manifest(ws, "rf3")["panels"]
    assert (panels[1]["speech_source"], panels[1]["narration"]) == ("dialogue", "")
    assert 'The old monk says, "You came far." ' + AC in panels[1]["motion_prompt"]
    assert panels[0]["narration"] == "" and "speaker" not in panels[0]
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k "dlg7 or dlg8 or dlg9 or dlg10 or review_focus_2 or review_focus_3" 2>&1 | tail -3
```

Expected: `6 failed`: the Dialogue tests fail because the manifest never reads `dialogue` (no `speaker` key, or the old pace error); `test_dlg8` fails on `--speech-delivery` (`SystemExit: 2`, unrecognized arguments).

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
only when --cast is given or a Narration: line has a colon.
```

with:

```python
only when --cast is given, a Narration: line has a colon or a panel has a Dialogue: line.
```

**3.2.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
                         help="per-panel catalog LoRAs (bin/ltx-movie's catalog_loras.json): each "
                              "panel gets a catalog_loras list and its triggers are prefixed to its "
                              "motion_prompt")
    return parser
```

with:

```python
                         help="per-panel catalog LoRAs (bin/ltx-movie's catalog_loras.json): each "
                              "panel gets a catalog_loras list and its triggers are prefixed to its "
                              "motion_prompt")
    parser.add_argument("--speech-delivery", dest="speech_delivery",
                         choices=["beats", "plain", "beats-no-acoustic"], default="beats",
                         help="how a Dialogue: line (or a spoken Narration: line) is written into "
                              "motion_prompt: beats (default) splits it at sentence ends with "
                              "short fixed beats and adds a fixed close-mic audio sentence; "
                              "beats-no-acoustic omits that sentence; plain is '<Speaker> says: "
                              "\"<line>\"'")
    return parser
```

**3.3.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
def _spoken_narration(args, prompt_texts, members):
    """[(speaker phrase or None, spoken text or the narration)] per prompts panel; character_lib
    is loaded only when some Narration: has a colon."""
    narrations = [pt["narration"] for pt in (prompt_texts or [])]
    if not any(":" in n for n in narrations):
        return [(None, n) for n in narrations]
    lib, phrases = _character_lib(), _known_phrases(args, members)
    return [lib.split_speaker(n, phrases) if ":" in n else (None, n) for n in narrations]
```

with:

```python
def _spoken(args, prompt_texts, members):
    """[(speaker phrase or None, spoken text or the narration, source)] per prompts panel (dialogue
    spec DG7 step 4), or None after an Error line for a Dialogue: that names no known phrase.
    source is "dialogue", "narration" (a Narration: line spoken by a known phrase, the
    back-compat alias) or None (voice-over); a panel with a Dialogue: keeps its Narration: as
    voice-over. character_lib is loaded only when some Dialogue: is non-empty or some
    Narration: has a colon."""
    panels = prompt_texts or []
    if not any(pt["dialogue"].strip() or ":" in pt["narration"] for pt in panels):
        return [(None, pt["narration"], None) for pt in panels]
    lib, phrases = _character_lib(), _known_phrases(args, members)
    spoken = []
    for i, pt in enumerate(panels, start=1):
        if pt["dialogue"].strip():
            phrase, line, problem = lib.parse_dialogue(pt["dialogue"], phrases)
            if problem:
                print("Error: panel %d: Dialogue: %s" % (i, problem), file=sys.stderr)
                return None
            spoken.append((phrase, line, "dialogue"))
        elif ":" in pt["narration"]:
            speaker, speech = lib.split_speaker(pt["narration"], phrases)
            spoken.append((speaker, speech, None if speaker is None else "narration"))
        else:
            spoken.append((None, pt["narration"], None))
    return spoken
```

**3.4.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
    spoken = _spoken_narration(args, prompt_texts, members)
```

with:

```python
    spoken = _spoken(args, prompt_texts, members)
    if spoken is None:
        return 2
```

**3.5.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
            for i in range(1, n_panels + 1):
                narration = prompt_texts[i - 1]["narration"]
                if not narration.strip():
                    print("Error: --pace proportional requires every panel to have a "
                          "non-empty Narration field; panel %d has none" % i, file=sys.stderr)
                    return 2
                if i <= len(spoken) and spoken[i - 1][0] is not None:
                    narration = spoken[i - 1][1]
                weights.append(max(len(narration.split()), 1))
```

with:

```python
            for i in range(1, n_panels + 1):
                narration = prompt_texts[i - 1]["narration"]
                speaker, speech, source = (spoken[i - 1] if i <= len(spoken)
                                           else (None, narration, None))
                if not narration.strip() and source != "dialogue":
                    print("Error: --pace proportional requires every panel to have a non-empty "
                          "Narration or Dialogue field; panel %d has neither" % i,
                          file=sys.stderr)
                    return 2
                weights.append(max(len((speech if speaker is not None else narration).split()),
                                   1))
```

**3.6.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
    panels = []
    for i in range(1, n_panels + 1):
        pt = prompt_texts[i - 1] if prompt_texts is not None else None
```

with:

```python
    # The word cap of each spoken line, against its own clip (dialogue spec DG7 step 6): a
    # Dialogue: line over it is refused; an old prefixed Narration: line only warns (D1).
    if any(speaker is not None for speaker, _speech, _source in spoken):
        dlib = _character_lib()
        for i, (speaker, speech, source) in enumerate(spoken[:n_panels], start=1):
            if speaker is None:
                continue
            seconds = frame_counts[i - 1] / float(args.fps)
            n = len(dlib.split_fragments(speech))
            cap = dlib.dialogue_word_cap(seconds, n)
            words = len(speech.split())
            if words > cap or n > dlib.DIALOGUE_MAX_FRAGMENTS:
                detail = ("%d words in %d sentences; a %.2f-second clip fits at most %d words in "
                          "%d sentences, and a line has at most 3 sentences; shorten the line, or "
                          "split it across alternating close-up panels (the speaker, then the "
                          "listener, then the speaker again)" % (words, n, seconds, cap, n))
                if source == "dialogue":
                    print("Error: panel %d: Dialogue: is %s" % (i, detail), file=sys.stderr)
                    return 2
                print("WARNING: panel %d: the spoken Narration: is %s" % (i, detail))

    panels = []
    for i in range(1, n_panels + 1):
        pt = prompt_texts[i - 1] if prompt_texts is not None else None
```

**3.7.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
        speaker, speech = spoken[i - 1] if i <= len(spoken) else (None, narration)
        if speaker is not None and motion_prompt is not None:
            lib_ = _character_lib()
            motion_prompt = lib_.insert_speech(motion_prompt, lib_.speech_sentence(speaker, speech))
```

with:

```python
        speaker, speech, source = spoken[i - 1] if i <= len(spoken) else (None, narration, None)
        if speaker is not None and motion_prompt is not None:
            lib_ = _character_lib()
            motion_prompt = lib_.insert_speech(
                motion_prompt, lib_.speech_text(speaker, speech, args.speech_delivery), [speaker])
```

**3.8.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
        if speaker is not None:
            panel["speaker"], panel["speech"] = speaker, speech
```

with:

```python
        if speaker is not None:
            panel["speaker"], panel["speech"], panel["speech_source"] = speaker, speech, source
```

**3.9.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
            p["motion_prompt"], names = lib.cast_text(p["motion_prompt"], members)
```

with:

```python
            p["motion_prompt"], names = lib.cast_text(p["motion_prompt"], members, skip_quoted=True)
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_casting_pipeline.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_lora_catalog.py 2>&1 | tail -1
python3 tests/test_ltx_story_manifest_chain.py 2>&1 | tail -1
python3 tests/test_ltx_story_video.py 2>&1 | tail -1
```

Expected: `passed` with no failure; both scripts print `OK n/n` with the baseline counts (C7a-c and `test_v2_golden_byte_identical` unchanged: no panel there speaks). Compile check with `FILES` = `bin/ltx-story-manifest tests/test_dialogue.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add bin/ltx-story-manifest tests/test_dialogue.py
git diff --cached --name-only
git commit -m "feat(dialogue): manifest composes Dialogue: as beats, refuses over-cap lines, --speech-delivery (DG7, DG9, DLG7-DLG10)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: A Dialogue: line satisfies the Narration requirement (S3 and _validate_story_md)

Implements the S3 part of G1 and the `_validate_story_md` part of G4 (6.3 rows "S3 fields ... Narration missing **and** no Dialogue" and V0). Tests DLG31.

**Files:**
- Modify: `character_lib.py`
- Modify: `bin/ltx-movie`
- Modify: `tests/test_dialogue.py`

**Interfaces:**
- Consumes: Task 4's `p["dialogue"]` (read with `p.get("dialogue", "")`, because callers may pass hand-built panel dicts).
- Produces: `shots_violations` and `_validate_story_md(story_md_path, expected_panels, no_stills=False, no_narration=False)` report a missing Narration only when the panel also has no Dialogue.

- [ ] **Step 1: Write the failing test.**

New test in this task: `test_dlg31_dialogue_satisfies_the_narration_requirement`.

Append to `tests/test_dialogue.py`:

```python
# --- DLG31: Dialogue in place of Narration (S3, V0) ------------------------------------------

def test_dlg31_dialogue_satisfies_the_narration_requirement(tmp_path):
    shots = ('# S\n\n## Characters\n- "the courier": %s.\n\n## Panel 1 — One\nImage: %s The courier '
             "stands at the gate.\nMotion: The courier raises the letter.\n@@LINE@@\n"
             % (seu.COURIER, DG9_SETTING))
    chained = ("# C\n\n## Panel 1 — One\nImage: A quay.\nMotion: The courier waits.\n@@LINE@@\n\n"
               "## Panel 2 — Two\nMotion: The courier runs.\nNarration: Rain fell.\n")
    no_stills = ("# N\n\n## Panel 1 — One\nPrompt: The courier waits on the quay.\n@@LINE@@\n")
    missing_s3 = "panel 1: S3 fields: missing/empty Narration: field"
    missing_v0 = "panel 1: missing/empty Narration: field"
    for line, ok in (("Dialogue: the courier: I carry a letter.", True), ("", False)):
        path = tmp_path / "shots.md"
        path.write_text(shots.replace("@@LINE@@", line), encoding="utf-8")
        panels = story_manifest._parse_prompts_md(str(path))[1]
        found = character_lib.shots_violations(path.read_text(encoding="utf-8"), panels, 1, [])
        assert (missing_s3 not in found) == ok, line
        for text, no_stills_flag, count in ((chained, False, 2), (no_stills, True, 1)):
            path = tmp_path / "story.md"
            path.write_text(text.replace("@@LINE@@", line), encoding="utf-8")
            assert (ltx_movie._validate_story_md(str(path), count, no_stills_flag) == []) == ok
            if not ok:
                assert missing_v0 in ltx_movie._validate_story_md(str(path), count, no_stills_flag)
```

- [ ] **Step 2: Run the test and confirm it fails.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k dlg31 2>&1 | tail -3
```

Expected: `1 failed`: the Dialogue case still reports `panel 1: S3 fields: missing/empty Narration: field`.

- [ ] **Step 3: Implement.**

**3.1.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
        for label, key in labels if narration else labels[:2]:
            if not p[key].strip():
                out.append("panel %d: S3 fields: missing/empty %s: field" % (num, label))
```

with:

```python
        for label, key in labels if narration else labels[:2]:
            if not p[key].strip() and not (key == "narration" and p.get("dialogue", "").strip()):
                out.append("panel %d: S3 fields: missing/empty %s: field" % (num, label))
```

**3.2.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
            for label, key in (("Prompt", "prompt"),) + (
                    () if no_narration else (("Narration", "narration"),)):
                if not p[key].strip():
                    violations.append("panel %d: missing/empty %s: field" % (num, label))
```

with:

```python
            for label, key in (("Prompt", "prompt"),) + (
                    () if no_narration else (("Narration", "narration"),)):
                if not p[key].strip() and not (key == "narration"
                                               and p.get("dialogue", "").strip()):
                    violations.append("panel %d: missing/empty %s: field" % (num, label))
```

**3.3.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
            for label, key in required[:-1] if no_narration else required:
                if not p[key].strip():
                    violations.append("panel %d: missing/empty %s: field" % (num, label))
```

with:

```python
            for label, key in required[:-1] if no_narration else required:
                if not p[key].strip() and not (key == "narration"
                                               and p.get("dialogue", "").strip()):
                    violations.append("panel %d: missing/empty %s: field" % (num, label))
```

**3.4.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    no_narration (--no-narration, --speech-only): Narration: is not required.
    """
```

with:

```python
    no_narration (--no-narration, --speech-only): Narration: is not required.
    A panel with a non-empty Dialogue: needs no Narration: (dialogue spec 6.3).
    """
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_shots_mode.py tests/test_story_engine.py tests/test_casting_regression.py 2>&1 | tail -1
python3 tests/test_ltx_movie_offline.py 2>&1 | tail -1
```

Expected: the pytest line shows no failure other than the known `test_rst62_import_sets`; the offline script prints `OK n/n` with the baseline `n`. Compile check with `FILES` = `character_lib.py bin/ltx-movie tests/test_dialogue.py`; expected `compiled 3` twice.

- [ ] **Step 5: Commit.**

```bash
git add character_lib.py bin/ltx-movie tests/test_dialogue.py
git diff --cached --name-only
git commit -m "feat(dialogue): a Dialogue: line satisfies S3 and the story.md Narration check (DLG31)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Engine clip length and speaking-beat coercion

Implements spec 2.2, 2.4, SP2, SP3 (the engine meaning of "declared cast member") and the `clip_seconds` part of G4. Tests DLG11, DLG33.

**Files:**
- Modify: `story_engine.py`
- Modify: `bin/ltx-movie`
- Modify: `tests/test_dialogue.py`
- Modify: `tests/test_story_engine.py` (`test_rst13_normalization`: spec 9.2 reason "`speaker`, `speech_notes`"; `test_rst39_outputs_and_layout`: its plan.json key list gains `speech_notes`, the same reason)

**Interfaces:**
- Consumes: `_clean_str`, `_q`, `normalize_plan`, `plan_checks`, `load_plan` (existing).
- Produces: `StoryContext` gains the last field `clip_seconds` (default `None`); `engine_seconds(ctx) -> float`; every normalized beat has `"speaker"` (a cast id or `""`, after coercion); every normalized plan has `"speech_notes"` (its last key, a list of `"beat %d: P14 speaking beat: ..."` strings); `coerce_speakers(ctx, plan) -> [note]` (mutates `plan["beats"]`); `plan_checks` appends `plan["speech_notes"]` to its advisory list; `load_plan` defaults a missing beat `speaker` to `""` and a missing `speech_notes` to `[]`; `bin/ltx-movie._story_context` passes `clip_seconds=args.frames / float(args.fps)`. In `tests/test_dialogue.py`: `_Done`, `_movie_args(*argv)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_dlg11_speaking_beat_coercion`, `test_dlg33_an_older_plan_json_loads`, `test_story_context_carries_the_clip_length`.

**1.1.** Append to `tests/test_dialogue.py`:

```python
# --- DLG11, DLG33: the plan's speaker and its coercion (2.2, 2.4, SP2) ------------------------

class _Done(object):
    returncode = 0


def _movie_args(*argv):
    """bin/ltx-movie args after the resolvers main() runs before Phase 1."""
    args = ltx_movie.build_parser().parse_args(list(argv))
    args.video_width, args.video_height = 704, 448
    for resolve in (ltx_movie._resolve_shots, ltx_movie._resolve_casting,
                    ltx_movie._resolve_global_loras, ltx_movie._resolve_story_engine):
        assert resolve(args) == 0
    return args


def test_dlg11_speaking_beat_coercion(ws):
    ctx = seu.make_ctx(se, ws, mode="shots", panels=3)
    raw = seu.plan_json("shots", 3)
    raw["beats"][1].update(speaker="c1", cast=["c1", "c2"])        # a wide shot, tracking
    raw["beats"][2].update(speaker="c1", shot="extreme close-up", camera="slow push-in")
    plan, shape = se.normalize_plan(ctx, raw)
    assert [b["speaker"] for b in plan["beats"]] == ["", "c1", "c1"]
    assert plan["beats"][1]["cast"] == ["c1"]
    assert (plan["beats"][1]["shot"], plan["beats"][1]["camera"]) == ("medium close-up", "static")
    assert (plan["beats"][2]["shot"], plan["beats"][2]["camera"]) == ("close-up", "slow push-in")
    assert plan["speech_notes"] == [
        "beat 2: P14 speaking beat: cast [c1, c2] changed to [c1] so the speaker is alone on screen",
        "beat 2: P14 speaking beat: shot 'wide shot' changed to 'medium close-up' so the speaker's "
        "face stays readable",
        "beat 2: P14 speaking beat: camera 'tracking' changed to 'static' so the speaker's face "
        "stays readable",
        "beat 3: P14 speaking beat: shot 'extreme close-up' changed to 'close-up' so the "
        "speaker's face stays readable"]
    assert se.plan_checks(ctx, plan, shape)[1][-4:] == plan["speech_notes"]
    chained = seu.make_ctx(se, ws)
    raw = seu.plan_json("chained", 3)
    raw["beats"][1]["speaker"] = "c9"
    plan, _shape = se.normalize_plan(chained, raw)
    assert plan["beats"][1]["speaker"] == "" and plan["speech_notes"] == [
        "beat 2: P14 speaking beat: speaker 'c9' is not a cast id, so nobody speaks in this beat"]
    raw["beats"][1]["speaker"] = "c1"
    plan, _shape = se.normalize_plan(chained._replace(narration=False), raw)
    assert plan["beats"][1]["speaker"] == "" and plan["speech_notes"] == [
        "beat 2: P14 speaking beat: speaker 'c1' dropped: this movie has no spoken lines"]
    raw = seu.plan_json("chained", 3)
    raw["beats"][2].update(speaker="c1", shot="wide shot", camera="tracking")
    plan, _shape = se.normalize_plan(chained, raw)
    assert [(b["shot"], b["camera"], b["speaker"]) for b in plan["beats"]] == [
        ("medium shot", "static", ""), ("wide shot", "tracking", ""), ("wide shot", "tracking", "c1")]
    assert plan["speech_notes"] == []
    runner = se._Run(chained, "")
    runner.make_state(0, plan, [se.empty_parts("chained", k, plan) for k in (1, 2, 3)])
    with open(os.path.join(chained.story_dir, "story_rounds", "round_0", "plan.json"),
              encoding="utf-8") as f:
        saved = json.load(f)
    assert [b["speaker"] for b in saved["beats"]] == ["", "", "c1"]
    assert saved["speech_notes"] == [] and list(saved)[-1] == "speech_notes"


def test_dlg33_an_older_plan_json_loads(ws):
    ctx = seu.make_ctx(se, ws)
    plan, _shape = se.normalize_plan(ctx, seu.plan_json("chained", 3))
    del plan["speech_notes"]
    for beat in plan["beats"]:
        del beat["speaker"]
    with open(os.path.join(ctx.story_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f)
    loaded = se.load_plan(ctx)
    assert [b["speaker"] for b in loaded["beats"]] == ["", "", ""]
    assert loaded["speech_notes"] == []


def test_story_context_carries_the_clip_length(tmp_path, monkeypatch):
    monkeypatch.setattr(ltx_movie, "WS", seu.make_ws(tmp_path))
    ctx = ltx_movie._story_context(_movie_args("n", "--story-id", "x", "--frames", "97"))
    assert (ctx.seconds, ctx.clip_seconds) == ("4", 97 / 24.0)
    assert se.engine_seconds(ctx) == 97 / 24.0
    assert se.engine_seconds(ctx._replace(clip_seconds=None)) == 4.0
    assert ltx_movie._story_context(_movie_args("n", "--story-id", "x")).clip_seconds == 145 / 24.0
```

**1.2.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    assert "surprise" not in plan
```

with:

```python
    assert "surprise" not in plan
    assert [b["speaker"] for b in plan["beats"]] == ["", "", ""] and plan["speech_notes"] == []
    assert list(plan)[-1] == "speech_notes" and list(plan["beats"][0])[-1] == "speaker"
```

**1.3.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    assert list(plan) == ["schema", "story_id", "mode", "panels", "seconds", "narrative", "goal",
                          "seed_image", "video_model", "auto_lora", "title", "logline", "cast",
                          "locations", "props", "beats", "loras"]
```

with:

```python
    assert list(plan) == ["schema", "story_id", "mode", "panels", "seconds", "narrative", "goal",
                          "seed_image", "video_model", "auto_lora", "title", "logline", "cast",
                          "locations", "props", "beats", "loras", "speech_notes"]
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k "dlg11 or dlg33 or clip_length" 2>&1 | tail -3
python3 -m pytest -q -p no:cacheprovider tests/test_story_engine.py -k "rst13 or rst39" 2>&1 | tail -3
```

Expected: `3 failed` (`KeyError: 'speaker'`, `KeyError: 'speech_notes'`, `AttributeError: 'StoryContext' object has no attribute 'clip_seconds'`), then `2 failed` (`KeyError: 'speaker'`; the plan key list).

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "auto_lora", "catalog", "pinned", "stills_pinned", "judge", "narration"], defaults=(True,))
# narration True: Narration: is voice-over or a character's spoken line. "speech"
# (bin/ltx-movie --speech-only): Narration: is optional and, when present, a character's spoken
# line. False (--no-narration): panels have no Narration: field and no narration check runs.
```

with:

```python
    "auto_lora", "catalog", "pinned", "stills_pinned", "judge", "narration", "clip_seconds"],
    defaults=(True, None))
# narration True: Narration: is voice-over or a character's spoken line. "speech"
# (bin/ltx-movie --speech-only): Narration: is optional and, when present, a character's spoken
# line. False (--no-narration): panels have no Narration: field and no narration check runs.
# clip_seconds: the exact clip length (frames / fps) the timing rules use; None means
# float(seconds) (docs/superpowers/specs/2026-10-24-on-camera-dialogue-design.md 2.4).


def engine_seconds(ctx):
    """The clip length in seconds that the timing rules use (dialogue spec 2.4)."""
    return ctx.clip_seconds if ctx.clip_seconds is not None else float(ctx.seconds)
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
            "location": _clean_str(item.get("location")),
            "cast": [_clean_str(c) if isinstance(c, str) else json.dumps(c) for c in beat_cast]})
```

with:

```python
            "location": _clean_str(item.get("location")),
            "cast": [_clean_str(c) if isinstance(c, str) else json.dumps(c) for c in beat_cast],
            "speaker": _clean_str(item.get("speaker"))})
```

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    picks["pinned"] = [dict(pin) for pin in ctx.pinned]
    plan["loras"] = picks
    return plan, shape
```

with:

```python
    picks["pinned"] = [dict(pin) for pin in ctx.pinned]
    plan["loras"] = picks
    plan["speech_notes"] = coerce_speakers(ctx, plan)
    return plan, shape


SPEAKING_SHOTS = ("medium close-up", "close-up")
SPEAKING_CAMERAS = ("static", "slow push-in")


def coerce_speakers(ctx, plan):
    """The P14 notes of the speaking-beat coercion (dialogue spec SP2), in beat order. Every beat
    gets a "speaker": a cast id or "". A speaker the movie cannot have (--no-narration) or that is
    not a plan cast id is dropped. A kept speaker is alone in the beat's cast, and when the beat
    frames its own shot (not a chained continuation, k >= 2) its shot becomes a medium close-up
    or close-up and its camera static or a slow push-in. No other beat is ever changed."""
    notes = []
    cast_ids = [c["id"] for c in plan["cast"]]
    for k, beat in enumerate(plan["beats"], start=1):
        raw = beat["speaker"]
        beat["speaker"] = ""
        if ctx.narration is False:
            if raw:
                notes.append("beat %d: P14 speaking beat: speaker %s dropped: this movie has no "
                             "spoken lines" % (k, _q(raw)))
            continue
        if not raw:
            continue
        if raw not in cast_ids:
            notes.append("beat %d: P14 speaking beat: speaker %s is not a cast id, so nobody speaks "
                         "in this beat" % (k, _q(raw)))
            continue
        beat["speaker"] = raw
        if beat["cast"] != [raw]:
            notes.append("beat %d: P14 speaking beat: cast [%s] changed to [%s] so the speaker is "
                         "alone on screen" % (k, ", ".join(beat["cast"]), raw))
            beat["cast"] = [raw]
        if ctx.mode != "chained" or k == 1:
            if beat["shot"] not in SPEAKING_SHOTS:
                shot = "close-up" if beat["shot"] == "extreme close-up" else "medium close-up"
                notes.append("beat %d: P14 speaking beat: shot %s changed to %s so the speaker's "
                             "face stays readable" % (k, _q(beat["shot"]), _q(shot)))
                beat["shot"] = shot
            if beat["camera"] not in SPEAKING_CAMERAS:
                notes.append("beat %d: P14 speaking beat: camera %s changed to 'static' so the "
                             "speaker's face stays readable" % (k, _q(beat["camera"])))
                beat["camera"] = "static"
    return notes
```

**3.4.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
            for hit in undeclared_references(lib, text, undeclared, exact_phrase=exact,
                                        masks=masks):
                hard.append(undeclared_message("plan: P13 undeclared character:", where, hit))
    return hard, advisory
```

with:

```python
            for hit in undeclared_references(lib, text, undeclared, exact_phrase=exact,
                                        masks=masks):
                hard.append(undeclared_message("plan: P13 undeclared character:", where, hit))
    advisory += plan["speech_notes"]
    return hard, advisory
```

**3.5.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
            or not all(k in plan for k in _PLAN_KEYS)):
        return None
    return plan
```

with:

```python
            or not all(k in plan for k in _PLAN_KEYS)):
        return None
    for beat in plan["beats"] if isinstance(plan["beats"], list) else []:
        if isinstance(beat, dict):
            beat.setdefault("speaker", "")
    plan.setdefault("speech_notes", [])
    return plan
```

**3.6.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
        stills_pinned=stills, judge=args.judge,
        narration=False if args.no_narration else "speech" if args.speech_only else True)
```

with:

```python
        stills_pinned=stills, judge=args.judge,
        narration=False if args.no_narration else "speech" if args.speech_only else True,
        clip_seconds=args.frames / float(args.fps))
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_story_engine.py tests/test_lora_catalog.py tests/test_iterate_story.py 2>&1 | tail -1
```

Expected: no failure other than the known `test_rst62_import_sets`. Compile check with `FILES` = `story_engine.py bin/ltx-movie tests/test_dialogue.py tests/test_story_engine.py`; expected `compiled 4` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py bin/ltx-movie tests/test_dialogue.py tests/test_story_engine.py
git diff --cached --name-only
git commit -m "feat(dialogue): plan speaker with speaking-beat coercion, speech_notes, clip_seconds (SP2, 2.4, DLG11, DLG33)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: The plan prompt asks for a speaker

Implements SP1 and spec 8.1 (and the plan half of CM5: "no dialogue" is dropped). Tests DLG12.

**Files:**
- Modify: `story_engine.py`
- Modify: `tests/test_dialogue.py`
- Modify: `tests/test_story_engine.py` (`test_rst8_plan_prompt_matrix`: spec 9.2 reason "8.1")

**Interfaces:**
- Consumes: `PLAN_PROMPT_TEMPLATE`, `build_plan_prompt` (existing).
- Produces: `SPEAKER_RULE`, `SILENT_SPEAKER_RULE`; the `@@SPEAKER_RULE@@` fragment token of `PLAN_PROMPT_TEMPLATE`.

- [ ] **Step 1: Write the failing tests.**

New test in this task: `test_dlg12_plan_prompt_speaker_rule`.

**1.1.** Append to `tests/test_dialogue.py`:

```python
# --- DLG12: the plan prompt (8.1) ------------------------------------------------------------

def test_dlg12_plan_prompt_speaker_rule(ws):
    spoken = (" speaker is the id of the one character who says something aloud on screen during "
              "the beat, or an empty string when nobody speaks; give a speaker only where a spoken "
              "line moves the story. A beat with a speaker shows only that character (its cast is "
              "just their id), in a medium close-up or close-up, facing the camera, with the camera "
              "static or a slow push-in.")
    silent = " speaker is always an empty string: nobody speaks in this movie."
    for mode in ("chained", "no_stills", "shots"):
        for narration, rule in ((True, spoken), ("speech", spoken), (False, silent)):
            prompt = se.build_plan_prompt(seu.make_ctx(se, ws, mode=mode, narration=narration),
                                          [], [])
            where = (mode, narration)
            assert ("at most %d.%s\n" % (se.MAX_CAST[mode], rule)) in prompt, where
            assert ("with the keys index, arc, action, shot, camera, location, cast and speaker."
                    in prompt), where
            assert "not a sequence of steps, with no on-screen text." in prompt, where
            assert "no dialogue" not in prompt and "@@" not in prompt, where
```

**1.2.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    assert "beats: a list of EXACTLY 14 objects" in prompt and "at most 2.\n" in prompt
```

with:

```python
    assert "beats: a list of EXACTLY 14 objects" in prompt
    assert "at most 2. speaker is the id of the one character who says something aloud" in prompt
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k dlg12 2>&1 | tail -3
python3 -m pytest -q -p no:cacheprovider tests/test_story_engine.py -k rst8 2>&1 | tail -3
```

Expected: `1 failed`, then `1 failed` (both on the missing speaker sentence).

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "arc, action, shot, camera, location and cast. index runs from 1 to @@PANELS@@. arc is one of "
```

with:

```python
    "arc, action, shot, camera, location, cast and speaker. index runs from 1 to @@PANELS@@. arc "
    "is one of "
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "of steps, with no dialogue and no on-screen text. shot is exactly one of: @@SHOT_LIST@@. "
```

with:

```python
    "of steps, with no on-screen text. shot is exactly one of: @@SHOT_LIST@@. "
```

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "@@MAX_CAST@@.\n"
    "loras: @@LORA_PARAGRAPH@@\n"
```

with:

```python
    "@@MAX_CAST@@.@@SPEAKER_RULE@@\n"
    "loras: @@LORA_PARAGRAPH@@\n"
```

**3.4.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
LORA_EMPTY_PARAGRAPH = ("an object with the keys global, per_beat and stills, each empty: global "
```

with:

```python
SPEAKER_RULE = (" speaker is the id of the one character who says something aloud on screen "
                "during the beat, or an empty string when nobody speaks; give a speaker only where "
                "a spoken line moves the story. A beat with a speaker shows only that character "
                "(its cast is just their id), in a medium close-up or close-up, facing the camera, "
                "with the camera static or a slow push-in.")
SILENT_SPEAKER_RULE = " speaker is always an empty string: nobody speaks in this movie."
LORA_EMPTY_PARAGRAPH = ("an object with the keys global, per_beat and stills, each empty: global "
```

**3.5.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        ("@@MODE_RULES@@", MODE_RULES[ctx.mode]),
    ]
    scalars = [("@@STORY_ID@@", ctx.story_id), ("@@PANELS@@", str(ctx.panels)),
               ("@@SECONDS@@", ctx.seconds), ("@@MAX_CAST@@", str(MAX_CAST[ctx.mode]))]
```

with:

```python
        ("@@MODE_RULES@@", MODE_RULES[ctx.mode]),
        ("@@SPEAKER_RULE@@", SILENT_SPEAKER_RULE if ctx.narration is False else SPEAKER_RULE),
    ]
    scalars = [("@@STORY_ID@@", ctx.story_id), ("@@PANELS@@", str(ctx.panels)),
               ("@@SECONDS@@", ctx.seconds), ("@@MAX_CAST@@", str(MAX_CAST[ctx.mode]))]
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_story_engine.py 2>&1 | tail -1
```

Expected: no failure other than the known `test_rst62_import_sets` (`test_rst47_robust_dry_run`, `test_rst57c` and `test_rst9` pass unchanged: the new text has no braces). Compile check with `FILES` = `story_engine.py tests/test_dialogue.py tests/test_story_engine.py`; expected `compiled 3` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_dialogue.py tests/test_story_engine.py
git diff --cached --name-only
git commit -m "feat(dialogue): the plan prompt asks for each beat's speaker (8.1, SP1, DLG12)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Writer keys, panel keys and the panel prompt

Implements SP5, CM3 and spec 8.2. Tests DLG13, DLG14 and Review Focus 1.

**Files:**
- Modify: `story_engine.py`
- Modify: `tests/test_dialogue.py`
- Modify: `tests/test_story_engine.py` (`test_rst16_panel_prompt`: spec 9.2 reason "fix-block text"; `test_rst17b_invalid_panel_retried_once_never_three_times`: the same fix-block text, spec 9.2 B; `test_rst20c_narration_modes`: spec 9.2 reason "speech-only has no narration key; `narration_speech` deleted; the voice-over N16 assertion moves to a re-check")

**Interfaces:**
- Consumes: Task 1's `dialogue_word_cap`, `clean_line`, `_speaker_regex`; Task 7's `engine_seconds` and beat `speaker`.
- Produces: `writer_keys(mode, k, narration=True, speaks=False) -> tuple`; `panel_speaks(ctx, plan, k) -> bool`; `speaker_phrase(plan, k) -> str or None`; `panel_keys(ctx, plan, k) -> tuple`; `_clean_dialogue(lib, text, phrase) -> str` (leading `<phrase>:` removed, then DG3 step 4); `KEY_LINE_TEMPLATES` with the 8.2 texts plus `"narration_with_dialogue"`, `"dialogue"`, `"no_stills_prompt_speaking"` and no `"narration_speech"`; `SPEAKING_ACTION_SENTENCE`, `SPEAKING_PROMPT_SENTENCE`, `SPEAKING_IMAGE_SENTENCE`, `SPEAKING_SENTENCES`, `FIX_INSTRUCTION`; `LABELS["dialogue"] == "Dialogue"`; `unparseable_panel_problem(mode, k, narration=True, speaks=False)`; parts.json and every writer-keyed call site use `panel_keys`. In `tests/test_dialogue.py`: `_speaking(k=2, speaker="c1")`, `_story(ws, mode, n=3, plan_mut=None, replies=None, ctx_kw=None) -> (ctx, plan, parts, text, path)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_dlg13_writer_keys_and_speaking_key_lines`, `test_dlg14_parse_panel_reply_on_a_speaking_panel`, `test_review_focus_1_writer_dialogue_with_label_prefix_and_quotes`.

**1.1.** Append to `tests/test_dialogue.py`:

```python
# --- DLG13, DLG14, Review Focus 1: writer keys and the panel prompt (SP5, 8.2) ----------------

def _speaking(k=2, speaker="c1"):
    """A plan mutation: speaker speaks in beat k."""
    def mutate(raw):
        raw["beats"][k - 1]["speaker"] = speaker
    return mutate


def _story(ws, mode, n=3, plan_mut=None, replies=None, ctx_kw=None):
    """(ctx, plan, parts, text, path) for seu.plan_json/panel_json; replies maps a panel number to
    a dict merged into that panel's writer reply before it is parsed (a speaking panel's reply
    needs a "dialogue")."""
    ctx = seu.make_ctx(se, ws, mode=mode, panels=n, **(ctx_kw or {}))
    raw = seu.plan_json(mode, n)
    if plan_mut:
        plan_mut(raw)
    plan, _shape = se.normalize_plan(ctx, raw)
    phrase = plan["cast"][0]["phrase"]
    parts = []
    for k in range(1, n + 1):
        reply = dict(seu.panel_json(mode, k, phrase), **(replies or {}).get(k, {}))
        parts.append(se.parse_panel_reply(ctx, plan, k, json.dumps(reply)))
    text = se.assemble(ctx, plan, parts)
    path = os.path.join(ctx.story_dir, "check.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return ctx, plan, parts, text, path


NO_STILLS_PROMPT = (
    "prompt: W1 to W2 words in the present tense: one flowing paragraph in strict chronological "
    "order that opens with the main action, carries enough separate beats to fill the full "
    "@@SECONDS@@ seconds, links them with temporal connectors (initially, as, then, while, a moment "
    "later), names the ambient and environmental sounds alongside the actions that make them, and "
    "states the camera viewpoint and the lighting and colour; you may also state a camera "
    "movement. Name each character only by their referring phrase. Do not describe any "
    "character's appearance or clothing, do not write a sentence about the place itself and do "
    "not name the shot type: the pipeline adds each character's description, the place's setting "
    "sentence, the shot type and, unless you state one, the camera movement itself. Describe only "
    "what is physically observable, with no mood words, no spoken words and no markdown.")
LINE = "Keep moving. The gate is close."


def test_dlg13_writer_keys_and_speaking_key_lines(ws):
    base = {("chained", 1): ["title", "image", "motion"], ("chained", 2): ["title", "motion"],
            ("no_stills", 1): ["title", "prompt"], ("no_stills", 2): ["title", "prompt"],
            ("shots", 1): ["title", "image", "motion"], ("shots", 2): ["title", "image", "motion"]}
    for (mode, k), keys in base.items():
        for narration in (True, "speech", False):
            for speaks in (False, True):
                expected = (keys + (["dialogue"] if speaks and narration is not False else [])
                            + (["narration"] if narration is True else []))
                assert list(se.writer_keys(mode, k, narration, speaks)) == expected, (
                    mode, k, narration, speaks)
    assert se.writer_keys("chained", 2) == ("title", "motion", "narration")
    for name, text in se.KEY_LINE_TEMPLATES.items():
        assert "Do not mention the camera" not in text and "camera or lens" not in text, name
    assert "narration_speech" not in se.KEY_LINE_TEMPLATES
    assert se.KEY_LINE_TEMPLATES["no_stills_prompt"] == NO_STILLS_PROMPT
    assert se.KEY_LINE_TEMPLATES["narration"] == (
        "narration: one sentence of 3 to 30 words of voice-over that nobody on screen says aloud. "
        "Never put a spoken line here.")
    assert se.KEY_LINE_TEMPLATES["narration_with_dialogue"] == (
        "narration: one sentence of 3 to 30 words of voice-over that nobody on screen says aloud, "
        "or an empty string: this panel's spoken line goes in dialogue, never here.")
    ctx, plan, parts, _t, _p = _story(ws, "chained", 3, plan_mut=_speaking(2),
                                      replies={2: {"dialogue": LINE}})
    prompt = se.build_panel_prompt(ctx, plan, parts, 2)
    assert ('\ndialogue: the exact words "the courier" says aloud in this panel: at most 14 words '
            "as one sentence, about one word fewer for each further sentence, and at most three "
            "sentences; no quotation marks, no speaker name and no description of how the words "
            "are said -- the pipeline adds who says them and how.\n") in prompt
    assert "\n" + se.KEY_LINE_TEMPLATES["narration_with_dialogue"] + "\n" in prompt
    assert ('already on screen. You may add one camera direction. In this panel "the courier" '
            "speaks the dialogue: keep their movement small -- a breath, a glance, a small hand "
            "gesture -- with the camera holding still, and do not write the spoken words or a "
            "speaking verb here; the pipeline adds them.\n") in prompt
    assert "@@" not in prompt
    quiet = se.build_panel_prompt(ctx, plan, parts, 3)
    assert "\ndialogue: " not in quiet
    assert "\n" + se.KEY_LINE_TEMPLATES["narration"] + "\n" in quiet
    ctx, plan, parts, _t, _p = _story(ws, "no_stills", 3, plan_mut=_speaking(2),
                                      replies={2: {"dialogue": LINE}})
    prompt = se.build_panel_prompt(ctx, plan, parts, 2)
    assert ('fills the full 6 seconds with small, continuous movements of "the courier" -- a '
            "breath, a glance, a small hand gesture -- names the ambient") in prompt
    assert ("no spoken words and no markdown. Do not write the spoken words or a speaking verb "
            "here; the pipeline adds them.\n") in prompt
    ctx, plan, parts, _t, _p = _story(ws, "shots", 3, plan_mut=_speaking(2),
                                      replies={2: {"dialogue": LINE}})
    prompt = se.build_panel_prompt(ctx, plan, parts, 2)
    assert ('Never name a person who is not in this shot. "the courier" is the only person in the '
            "frame, facing the camera.\n") in prompt
    assert ('without one, the pipeline adds the planned camera sentence. In this panel "the '
            'courier" speaks the dialogue:') in prompt
    ctx, plan, parts, _t, _p = _story(ws, "chained", 3, plan_mut=_speaking(2),
                                      replies={2: {"dialogue": LINE}},
                                      ctx_kw={"seconds": "4", "clip_seconds": 97 / 24.0})
    assert "at most 9 words as one sentence" in se.build_panel_prompt(ctx, plan, parts, 2)


def test_dlg14_parse_panel_reply_on_a_speaking_panel(ws):
    ctx = seu.make_ctx(se, ws)
    raw = seu.plan_json("chained", 3)
    raw["beats"][1]["speaker"] = "c1"
    plan, _shape = se.normalize_plan(ctx, raw)
    reply = dict(seu.panel_json("chained", 2), narration="",
                 dialogue='the courier: You came far. He said "wait".')
    parts = se.parse_panel_reply(ctx, plan, 2, json.dumps(reply))
    assert list(parts) == ["title", "motion", "dialogue", "narration"]
    assert (parts["dialogue"], parts["narration"]) == ("You came far. He said 'wait'.", "")
    assert se.parse_panel_reply(ctx, plan, 2, json.dumps(dict(reply, dialogue="  "))) is None
    no_line = dict(reply)
    del no_line["dialogue"]
    assert se.parse_panel_reply(ctx, plan, 2, json.dumps(no_line)) is None
    quiet = se.parse_panel_reply(ctx, plan, 3, json.dumps(dict(seu.panel_json("chained", 3),
                                                               dialogue="Ignored.")))
    assert list(quiet) == ["title", "motion", "narration"]
    assert se.parse_panel_reply(ctx, plan, 3, json.dumps(dict(seu.panel_json("chained", 3),
                                                              narration=""))) is None
    speech = ctx._replace(narration="speech")
    plan_speech, _shape = se.normalize_plan(speech, raw)
    assert list(se.parse_panel_reply(speech, plan_speech, 2, json.dumps(reply))) == [
        "title", "motion", "dialogue"]
    off = ctx._replace(narration=False)
    plan_off, _shape = se.normalize_plan(off, raw)
    assert list(se.parse_panel_reply(off, plan_off, 2, json.dumps(reply))) == ["title", "motion"]
    assert se.unparseable_panel_problem("chained", 2, True, True) == (
        "the reply is not one JSON object with the keys title, motion, dialogue, narration")


def test_review_focus_1_writer_dialogue_with_label_prefix_and_quotes(ws):
    ctx = seu.make_ctx(se, ws)
    raw = seu.plan_json("chained", 3)
    raw["beats"][1]["speaker"] = "c1"
    plan, _shape = se.normalize_plan(ctx, raw)
    for written in ("dialogue: the courier: “Keep moving.”", 'The Courier: "Keep moving."',
                    '"Keep moving."', "the courier:   Keep   moving."):
        reply = dict(seu.panel_json("chained", 2), dialogue=written)
        assert se.parse_panel_reply(ctx, plan, 2, json.dumps(reply))["dialogue"] == (
            "Keep moving."), written
```

**1.2.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    assert ("\n\nYour previous version of this panel was rejected. Problems:\n- panel 2: N3 "
            "appearance: x\n- panel 2: N12 one action: y\nPrevious version:\ntitle: "
```

with:

```python
    assert ("\n\nYour previous version of this panel was rejected. Problems:\n- panel 2: N3 "
            "appearance: x\n- panel 2: N12 one action: y\nFix only these problems. Keep every "
            "camera direction, every descriptive sentence and the dialogue word for word, and "
            "change only the sentence or sentences that cause them.\nPrevious version:\ntitle: "
```

**1.3.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    assert ("Your previous version of this panel was rejected. Problems:\n- the reply is not one "
            "JSON object with the keys title, motion, narration\nPrevious version:\ntitle: "
            "the courier swerves around a\nmotion: \nnarration: \n\n") in panel2[1]["argv"][-1]
```

with:

```python
    assert ("Your previous version of this panel was rejected. Problems:\n- the reply is not one "
            "JSON object with the keys title, motion, narration\nFix only these problems. Keep "
            "every camera direction, every descriptive sentence and the dialogue word for word, "
            "and change only the sentence or sentences that cause them.\nPrevious version:\ntitle: "
            "the courier swerves around a\nmotion: \nnarration: \n\n") in panel2[1]["argv"][-1]
```

**1.4.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
def test_rst20c_narration_modes(ws):
    # --speech-only: Narration: may be empty; a voice-over line is hard N16. --no-narration:
    # no Narration: field at all and no narration check.
    def narration(text):   # panel 2 says text; the other panels have no narration
        return lambda parts: [p.update(narration=text if k == 1 else "")
                              for k, p in enumerate(parts)]

    speech = {"narration": "speech"}
    for mode in ("chained", "no_stills", "shots"):
        assert _story_checks(ws, mode, part_mut=narration(""), ctx_kw=speech) == [], mode
        assert _story_checks(ws, mode, part_mut=narration("the courier: Keep moving, stay low."),
                             ctx_kw=speech, plan_mut=MEDIUM) == [], mode
    assert _story_checks(ws, "chained", part_mut=narration("Rain falls on the harbour town."),
                         ctx_kw=speech) == [
        "panel 2: N16 speaker: Narration: is voice-over, but this story is speech-only; start it "
        "with the referring phrase of the character in the shot who says it and a colon, or "
        "leave it empty"]
    ctx, plan, parts, text, _path = _story(ws, "chained", 3, part_mut=narration(""), ctx_kw=speech)
    assert "Narration:" not in text
    reply = dict(seu.panel_json("chained", 2, plan["cast"][0]["phrase"]), narration="")
    assert se.parse_panel_reply(ctx, plan, 2, json.dumps(reply))["narration"] == ""
    assert se.KEY_LINE_TEMPLATES["narration_speech"] in se.build_panel_prompt(ctx, plan, parts, 2)
    off = {"narration": False}
```

with:

```python
def test_rst20c_narration_modes(ws, monkeypatch, capsys):
    # --speech-only: there is no narration key (dialogue spec SP5); a hand-written voice-over
    # Narration: is N16 on re-check. --no-narration: no Narration: field at all and no
    # narration check.
    def narration(text):   # panel 2 says text; the other panels have no narration
        return lambda parts: [p.update(narration=text if k == 1 else "")
                              for k, p in enumerate(parts)]

    speech = {"narration": "speech"}
    for mode in ("chained", "no_stills", "shots"):
        assert _story_checks(ws, mode, part_mut=narration(""), ctx_kw=speech) == [], mode
        assert _story_checks(ws, mode, part_mut=narration("the courier: Keep moving, stay low."),
                             ctx_kw=speech, plan_mut=MEDIUM) == [], mode
    ctx, plan, parts, text, _path = _story(ws, "chained", 3, part_mut=narration(""), ctx_kw=speech)
    assert "Narration:" not in text
    reply = dict(seu.panel_json("chained", 2, plan["cast"][0]["phrase"]), narration="")
    assert "narration" not in se.parse_panel_reply(ctx, plan, 2, json.dumps(reply))
    assert "\nnarration: " not in se.build_panel_prompt(ctx, plan, parts, 2)
    saved, _text = _saved_story(ws, monkeypatch, ctx_kw=dict(speech, story_id="s20c"))
    motion = "Motion: " + seu.panel_json("chained", 2)["motion"] + "\n"
    _edit_story(saved, motion, motion + "Narration: Rain falls on the harbour town.\n")
    voice_over = ("panel 2: N16 speaker: Narration: is voice-over, but this story is speech-only; "
                  "start it with the referring phrase of the character in the shot who says it "
                  "and a colon, or leave it empty")
    assert se.recheck(saved, lambda path, panels, no_stills=False: ltx_movie._validate_story_md(
        path, panels, no_stills, no_narration=True)) == (2, [])
    assert "  - %s\n" % voice_over in capsys.readouterr().err
    off = {"narration": False}
```

**1.5.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once (the `--no-narration` tail of `test_rst20c_narration_modes`; `narration_speech` is deleted):

```python
        assert se.KEY_LINE_TEMPLATES["narration"] not in prompt
        assert se.KEY_LINE_TEMPLATES["narration_speech"] not in prompt
```

with:

```python
        assert se.KEY_LINE_TEMPLATES["narration"] not in prompt
        assert se.KEY_LINE_TEMPLATES["narration_with_dialogue"] not in prompt
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k "dlg13 or dlg14 or review_focus_1" 2>&1 | tail -3
python3 -m pytest -q -p no:cacheprovider tests/test_story_engine.py -k "rst16 or rst17b or rst20c" 2>&1 | tail -3
```

Expected: `3 failed` (`TypeError: writer_keys() takes from 2 to 3 positional arguments but 4 were given`; the speaking reply has no `dialogue` part), then `3 failed` (the fix-block text; `narration` is still a speech-only key).

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
_LABEL_RE = re.compile(r"^(?:title|image|motion|prompt|narration)\s*:\s*", re.IGNORECASE)
```

with:

```python
_LABEL_RE = re.compile(r"^(?:title|image|motion|prompt|narration|dialogue)\s*:\s*",
                       re.IGNORECASE)
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
LABELS = {"image": "Image", "motion": "Motion", "prompt": "Prompt", "narration": "Narration"}
```

with:

```python
LABELS = {"image": "Image", "motion": "Motion", "prompt": "Prompt", "narration": "Narration",
          "dialogue": "Dialogue"}
```

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "chained_motion1": (
        "motion: W1 to W2 words in one or two plain sentences: what the characters physically do "
        "during these @@SECONDS@@ seconds. Name each character only by their referring phrase, "
        "word for word. Describe ONE continuous physical motion, not a sequence of separate "
        "steps. Do not mention the camera: the pipeline adds the camera sentence."),
    "chained_motion": (
        "motion: W1 to W2 words in one or two plain sentences: what the characters physically do "
        "during these @@SECONDS@@ seconds, continuing from where the previous panel left them. "
        "Name each character only by their referring phrase, word for word. Describe ONE "
        "continuous physical motion, not a sequence of separate steps: @@SECONDS@@ seconds is "
        "enough for a single gesture, a few footsteps or the start of a movement. Do not describe "
        "appearance, clothing, setting, lighting, colour, style, camera or lens -- all of that is "
        "already on screen."),
    "no_stills_prompt": (
        "prompt: W1 to W2 words in the present tense: one flowing paragraph in strict "
        "chronological order that opens with the main action, carries enough separate beats to "
        "fill the full @@SECONDS@@ seconds, links them with temporal connectors (initially, as, "
        "then, while, a moment later), names the ambient and environmental sounds alongside the "
        "actions that make them, and states the camera viewpoint and the lighting and colour. "
        "Name each character only by their referring phrase. Do not describe any character's "
        "appearance or clothing, do not write a sentence about the place itself and do not name "
        "the shot type or the camera motion: the pipeline adds each character's description, the "
        "place's setting sentence, the shot type and the camera motion itself. Describe only what "
        "is physically observable, with no mood words, no spoken dialogue and no markdown."),
```

with:

```python
    "chained_motion1": (
        "motion: W1 to W2 words in one or two plain sentences: what the characters physically do "
        "during these @@SECONDS@@ seconds. Name each character only by their referring phrase, "
        "word for word. Describe ONE continuous physical motion, not a sequence of separate "
        "steps. You may add one camera direction; without one, the pipeline adds the planned "
        "camera sentence."),
    "chained_motion": (
        "motion: W1 to W2 words in one or two plain sentences: what the characters physically do "
        "during these @@SECONDS@@ seconds, continuing from where the previous panel left them. "
        "Name each character only by their referring phrase, word for word. Describe ONE "
        "continuous physical motion, not a sequence of separate steps: @@SECONDS@@ seconds is "
        "enough for a single gesture, a few footsteps or the start of a movement. Do not describe "
        "appearance, clothing, setting, lighting, colour or style -- all of that is already on "
        "screen. You may add one camera direction."),
    "no_stills_prompt": (
        "prompt: W1 to W2 words in the present tense: one flowing paragraph in strict "
        "chronological order that opens with the main action, carries enough separate beats to "
        "fill the full @@SECONDS@@ seconds, links them with temporal connectors (initially, as, "
        "then, while, a moment later), names the ambient and environmental sounds alongside the "
        "actions that make them, and states the camera viewpoint and the lighting and colour; you "
        "may also state a camera movement. Name each character only by their referring phrase. Do "
        "not describe any character's appearance or clothing, do not write a sentence about the "
        "place itself and do not name the shot type: the pipeline adds each character's "
        "description, the place's setting sentence, the shot type and, unless you state one, the "
        "camera movement itself. Describe only what is physically observable, with no mood words, "
        "no spoken words and no markdown."),
```

**3.4.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        "and the ONE physical action they perform during these @@SECONDS@@ seconds. Never chain "
        "actions with then, while, meanwhile, simultaneously, afterwards, followed by or a comma "
        "before and, and never use a semicolon. Do not mention the camera: the pipeline adds the "
        "camera sentence."),
    "narration_speech": ("narration: leave it empty unless a character in this shot says something "
                         "aloud; then one sentence of 3 to 30 words: that character's referring "
                         "phrase, word for word, and a colon, followed by their words with no "
                         "quotation marks. This movie has no voice-over, and every spoken line "
                         "belongs here, never in another field. A character who speaks needs a "
                         "medium shot or closer and no fixed smile or grin, so their lips can "
                         "move."),
    "narration": ("narration: one sentence of 3 to 30 words. It is voice-over unless a character "
                  "in this shot says it aloud: then begin with that character's referring phrase, "
                  "word for word, and a colon, followed by their words with no quotation marks. "
                  "Every spoken line belongs here, never in another field. A character who speaks "
                  "needs a medium shot or closer and no fixed smile or grin, so their lips can "
                  "move."),
}
```

with:

```python
        "and the ONE physical action they perform during these @@SECONDS@@ seconds. Never chain "
        "actions with then, while, meanwhile, simultaneously, afterwards, followed by or a comma "
        "before and, and never use a semicolon. You may follow it with one camera sentence; "
        "without one, the pipeline adds the planned camera sentence."),
    "narration": ("narration: one sentence of 3 to 30 words of voice-over that nobody on screen "
                  "says aloud. Never put a spoken line here."),
    "narration_with_dialogue": ("narration: one sentence of 3 to 30 words of voice-over that "
                                "nobody on screen says aloud, or an empty string: this panel's "
                                "spoken line goes in dialogue, never here."),
    "dialogue": ("dialogue: the exact words @@SPEAKER@@ says aloud in this panel: at most "
                 "@@DWORDS@@ words as one sentence, about one word fewer for each further "
                 "sentence, and at most three sentences; no quotation marks, no speaker name and "
                 "no description of how the words are said -- the pipeline adds who says them and "
                 "how."),
}
KEY_LINE_TEMPLATES["no_stills_prompt_speaking"] = KEY_LINE_TEMPLATES["no_stills_prompt"].replace(
    "carries enough separate beats to fill the full @@SECONDS@@ seconds, links them with temporal "
    "connectors (initially, as, then, while, a moment later), ",
    "fills the full @@SECONDS@@ seconds with small, continuous movements of @@SPEAKER@@ -- a "
    "breath, a glance, a small hand gesture -- ")
# Appended to a speaking panel's key lines (dialogue spec 8.2); @@SPEAKER@@ is the speaker's
# quoted referring phrase.
SPEAKING_ACTION_SENTENCE = (" In this panel @@SPEAKER@@ speaks the dialogue: keep their movement "
                            "small -- a breath, a glance, a small hand gesture -- with the camera "
                            "holding still, and do not write the spoken words or a speaking verb "
                            "here; the pipeline adds them.")
SPEAKING_PROMPT_SENTENCE = (" Do not write the spoken words or a speaking verb here; the pipeline "
                            "adds them.")
SPEAKING_IMAGE_SENTENCE = " @@SPEAKER@@ is the only person in the frame, facing the camera."
SPEAKING_SENTENCES = {"image": SPEAKING_IMAGE_SENTENCE, "motion": SPEAKING_ACTION_SENTENCE,
                      "prompt": SPEAKING_PROMPT_SENTENCE}
FIX_INSTRUCTION = ("\nFix only these problems. Keep every camera direction, every descriptive "
                   "sentence and the dialogue word for word, and change only the sentence or "
                   "sentences that cause them.")
```

**3.5.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def writer_keys(mode, k, narration=True):
    """The writer parts of panel k (Section 2.3), in order; no "narration" when narration is
    False."""
    if mode == "chained":
        keys = ("title", "image", "motion", "narration") if k == 1 else (
            "title", "motion", "narration")
    elif mode == "no_stills":
        keys = ("title", "prompt", "narration")
    else:
        keys = ("title", "image", "motion", "narration")
    return keys if narration else keys[:-1]
```

with:

```python
def writer_keys(mode, k, narration=True, speaks=False):
    """The writer parts of panel k (Section 2.3; dialogue spec SP5), in order: title, image
    (chained panel 1 and shots), motion or prompt, dialogue when the panel speaks and the movie
    has spoken lines, narration only when narration is True (--speech-only has none)."""
    if mode == "chained":
        keys = ["title", "image", "motion"] if k == 1 else ["title", "motion"]
    elif mode == "no_stills":
        keys = ["title", "prompt"]
    else:
        keys = ["title", "image", "motion"]
    if speaks and narration is not False:
        keys.append("dialogue")
    if narration is True:
        keys.append("narration")
    return tuple(keys)


def panel_speaks(ctx, plan, k):
    """True when beat k has a speaker and the movie has spoken lines (dialogue spec SP4)."""
    return bool(plan["beats"][k - 1]["speaker"]) and ctx.narration is not False


def speaker_phrase(plan, k):
    """The referring phrase of beat k's speaker, or None when nobody speaks."""
    speaker = plan["beats"][k - 1]["speaker"]
    for entry in plan["cast"]:
        if speaker and entry["id"] == speaker:
            return entry["phrase"]
    return None


def panel_keys(ctx, plan, k):
    """writer_keys for panel k of a plan (dialogue spec SP5)."""
    return writer_keys(ctx.mode, k, ctx.narration, speaks=bool(plan["beats"][k - 1]["speaker"]))
```

**3.6.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    obj = extract_json(answer)
    if obj is None:
        return None
    lib = _character_lib(ctx.ws)
    pasted = pasted_pieces(ctx, plan, k)
    parts = {}
    for key in writer_keys(ctx.mode, k, ctx.narration):
        if key == "title":
            continue
        value = clean_writer(lib, obj.get(key), pasted.get(key, ()))
        if not value and not (key == "narration" and ctx.narration == "speech"):
            return None
        parts[key] = value
```

with:

```python
    obj = extract_json(answer)
    if obj is None:
        return None
    lib = _character_lib(ctx.ws)
    pasted = pasted_pieces(ctx, plan, k)
    speaks = panel_speaks(ctx, plan, k)
    parts = {}
    for key in panel_keys(ctx, plan, k):
        if key == "title":
            continue
        value = clean_writer(lib, obj.get(key), pasted.get(key, ()))
        if key == "dialogue":
            value = _clean_dialogue(lib, value, speaker_phrase(plan, k))
        if not value and not (key == "narration" and speaks):
            return None
        parts[key] = value
```

**3.7.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def panel_fields(ctx, plan, parts, k):
```

with:

```python
def _clean_dialogue(lib, text, phrase):
    """A writer's or critic's spoken line: a leading "<phrase>:" removed (case-insensitive), then
    one surrounding pair of quotes off and every other double quote turned into an apostrophe
    (dialogue spec SP5, PG4; DG3 step 4)."""
    if phrase:
        text = lib._speaker_regex(phrase).sub("", text, count=1)
    return lib.clean_line(text)


def panel_fields(ctx, plan, parts, k):
```

**3.8.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        writers = {LABELS[key]: parts[k - 1].get(key, "") for key in writer_keys(ctx.mode, k, ctx.narration)
                   if key != "title"}
```

with:

```python
        writers = {LABELS[key]: parts[k - 1].get(key, "") for key in panel_keys(ctx, plan, k)
                   if key != "title"}
```

**3.9.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    seed = SEED_PANEL if ctx.mode == "chained" and k == 1 and ctx.seed_agent_image else ""
    key_lines = []
    for key in writer_keys(ctx.mode, k, ctx.narration):
        if key == "title" or key == "narration":
            line = KEY_LINE_TEMPLATES["narration_speech" if key == "narration"
                                      and ctx.narration == "speech" else key]
        elif ctx.mode == "chained":
            line = KEY_LINE_TEMPLATES["chained_image" if key == "image" else
                                      "chained_motion1" if k == 1 else "chained_motion"]
        else:
            line = KEY_LINE_TEMPLATES["%s_%s" % (ctx.mode, key)]
        if key in ("image", "motion", "prompt") and ctx.narration == "speech":
            line += SPEECH_FRAMING_SENTENCE
        if key in targets:
            line = line.replace("W1", str(targets[key][0]), 1).replace("W2", str(targets[key][1]), 1)
        key_lines.append(line)
    fix_block = ""
    if fix is not None:
        keys = writer_keys(ctx.mode, k, ctx.narration)
        current = parts[k - 1] if k <= len(parts) and parts[k - 1] else {}
        fix_block = ("Your previous version of this panel was rejected. Problems:\n"
                     + "\n".join("- " + m for m in fix[:MAX_LISTED])
                     + "\nPrevious version:\n"
```

with:

```python
    seed = SEED_PANEL if ctx.mode == "chained" and k == 1 and ctx.seed_agent_image else ""
    speaks = panel_speaks(ctx, plan, k)
    phrase = speaker_phrase(plan, k) if speaks else None
    words = str(_character_lib(ctx.ws).dialogue_word_cap(engine_seconds(ctx), 1)) if speaks else ""
    key_lines = []
    for key in panel_keys(ctx, plan, k):
        if key == "title":
            line = KEY_LINE_TEMPLATES["title"]
        elif key == "narration":
            line = KEY_LINE_TEMPLATES["narration_with_dialogue" if speaks else "narration"]
        elif key == "dialogue":
            line = KEY_LINE_TEMPLATES["dialogue"]
        elif ctx.mode == "chained":
            line = KEY_LINE_TEMPLATES["chained_image" if key == "image" else
                                      "chained_motion1" if k == 1 else "chained_motion"]
        elif key == "prompt" and speaks:
            line = KEY_LINE_TEMPLATES["no_stills_prompt_speaking"]
        else:
            line = KEY_LINE_TEMPLATES["%s_%s" % (ctx.mode, key)]
        if key in ("image", "motion", "prompt") and ctx.narration == "speech":
            line += SPEECH_FRAMING_SENTENCE
        if speaks:
            line += SPEAKING_SENTENCES.get(key, "")
        if key in targets:
            line = line.replace("W1", str(targets[key][0]), 1).replace("W2", str(targets[key][1]), 1)
        if speaks:
            line = line.replace("@@SPEAKER@@", '"%s"' % phrase).replace("@@DWORDS@@", words)
        key_lines.append(line)
    fix_block = ""
    if fix is not None:
        keys = panel_keys(ctx, plan, k)
        current = parts[k - 1] if k <= len(parts) and parts[k - 1] else {}
        fix_block = ("Your previous version of this panel was rejected. Problems:\n"
                     + "\n".join("- " + m for m in fix[:MAX_LISTED])
                     + FIX_INSTRUCTION
                     + "\nPrevious version:\n"
```

**3.10.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def unparseable_panel_problem(mode, k, narration=True):
    return ("the reply is not one JSON object with the keys %s"
            % ", ".join(writer_keys(mode, k, narration)))
```

with:

```python
def unparseable_panel_problem(mode, k, narration=True, speaks=False):
    return ("the reply is not one JSON object with the keys %s"
            % ", ".join(writer_keys(mode, k, narration, speaks)))
```

**3.11.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
            dict([("index", k)] + [(key, p.get(key, ""))
                                   for key in writer_keys(ctx.mode, k, ctx.narration)])
```

with:

```python
            dict([("index", k)] + [(key, p.get(key, "")) for key in panel_keys(ctx, plan, k)])
```

**3.12.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
                new = self.panel_call(plan, parts, k, 0,
                                      [unparseable_panel_problem(ctx.mode, k, ctx.narration)])
```

with:

```python
                new = self.panel_call(plan, parts, k, 0, [unparseable_panel_problem(
                    ctx.mode, k, ctx.narration, bool(plan["beats"][k - 1]["speaker"]))])
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_story_engine.py tests/test_lora_catalog.py 2>&1 | tail -1
```

Expected: no failure other than the known `test_rst62_import_sets`. Compile check with `FILES` = `story_engine.py tests/test_dialogue.py tests/test_story_engine.py`; expected `compiled 3` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_dialogue.py tests/test_story_engine.py
git diff --cached --name-only
git commit -m "feat(dialogue): dialogue writer key, panel keys, speaking key lines and camera-tolerant panel prompt (SP5, 8.2, DLG13, DLG14)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Assembly: the facing sentence, the Dialogue: field, the Narration rule and camera dedupe

Implements SP4, CM4, CM2, controller ruling Q1 (the pasted facing sentence is not an S5 action; Spec amendment 1), spec 2.1 (field order) and the "Dialogue label is excluded from N1-N10" bullet of 6.4. CM2 and the exclusion land here, with the first assembled `Dialogue:` field and the first pasted `<Speaker> faces the camera.`: without CM2 that pasted sentence would trip N3 (`camera` is an appearance word, and N3 is still hard until Task 14). Tests DLG15.

**Files:**
- Modify: `story_engine.py`
- Modify: `character_lib.py` (`shots_violations(..., ignore_facing=False)`, `FACING_SENTENCE`, `_drop_facing`)
- Modify: `tests/test_dialogue.py`
- Modify: `tests/test_story_engine.py` (`test_rst12_lexicons`: spec 9.2's exact new assertions; `test_rst20_panel_checks`: "the N3 'camera' case gives `[]`; N3 tail text")

**Interfaces:**
- Consumes: Task 2's `_is_camera_sentence(sentence, phrases)`; Task 1's `clean_line`; Task 9's `panel_speaks`, `speaker_phrase`, `LABELS`.
- Produces: `FACING_SENTENCE = "%s faces the camera."`, `SPEAKING_CAMERA = "The camera stays static."`, `CAMERA_MOTION_RE`; `_sentences(text) -> [str]`; `_facing(ctx, plan, k) -> [] or [sentence]`; `_moves_camera(ctx, plan, text) -> bool`; `pasted_pieces` always lists the facing sentence, `SPEAKING_CAMERA` (chained k>=2) and the planned camera sentence; `panel_fields` emits `("Dialogue", "<phrase>: <line>")` on a speaking panel (`"<phrase>:"` when its part is empty), drops the planned camera sentence on a non-speaking panel whose writer text moves the camera, and emits Narration only when `ctx.narration is True` and (the part is non-empty or the panel does not speak); `story_fields` emits `("Dialogue", text)` before Narration whenever the parsed panel has one; N4 and N10 skip the `Dialogue` label; `APPEARANCE_WORDS` has no camera words, `_CAMERA_TARGET_RE` is gone, and N3's tail ends `colour or style` (CM2). In `character_lib`: `FACING_SENTENCE = "%s faces the camera."` (the engine's `FACING_SENTENCE` is the same string), `_drop_facing(text, phrases) -> text`, and `shots_violations(text, panels, expected_panels, members, narration=True, ignore_facing=False)`: with `ignore_facing`, a Motion: sentence that is exactly `<Phrase> faces the camera.` for a cast or roster phrase is left out of S5's action count; every robust-engine caller (`panel_checks`, both `recheck` paths, `plan_free_report`) passes `ignore_facing=True`, while the legacy `bin/ltx-movie` shots path keeps the default, so it stays byte-identical.

- [ ] **Step 1: Write the failing test.**

New test in this task: `test_dlg15_assembly_goldens_and_dedupe`.

Append to `tests/test_dialogue.py`:

```python
# --- DLG15: assembly (SP4, CM4) --------------------------------------------------------------

SPEAKING_WRITERS = {
    "chained": [{"title": "Wet Road", "image": "The courier waits on the left",
                 "motion": "The courier pushes off", "narration": "The rain had not stopped"},
                {"title": "The Bend", "motion": "The courier leans into the bend.",
                 "dialogue": LINE, "narration": ""}],
    "no_stills": [{"title": "Wet Road", "prompt": "The courier pedals through the rain",
                   "narration": "The rain had not stopped"},
                  {"title": "The Bend", "prompt": "The courier leans into the bend.",
                   "dialogue": LINE, "narration": "Every street led down to the water."}],
    "shots": [{"title": "Wet Road", "image": "The courier waits on the left",
               "motion": "The courier pushes off", "narration": "The rain had not stopped"},
              {"title": "The Bend", "image": "The courier leans right.",
               "motion": "The courier leans into the bend.", "dialogue": LINE,
               "narration": "Every street led down to the water."}],
}
HEAD = ("# The Sealed Letter\n\nA courier carries a sealed letter through a rainy harbour town and "
        "delivers it at the temple gate.\n\n")
IDENTITY = "The courier is " + seu.COURIER + "."
PANEL1_IMAGE = ("Image: " + seu.HARBOUR + " " + IDENTITY
                + " The courier waits on the left. The shot is a medium shot.\n")
PANEL1_REST = "Motion: The courier pushes off. The camera stays static.\nNarration: The rain had not stopped.\n\n"
DIALOGUE_LINE = "Dialogue: the courier: Keep moving. The gate is close.\n"
GOLDEN_SPEAKING = {
    "chained": (HEAD + "## Panel 1 — Wet Road\n" + PANEL1_IMAGE + PANEL1_REST
                + "## Panel 2 — The Bend\nMotion: The courier leans into the bend. The courier "
                  "faces the camera. The camera stays static.\n" + DIALOGUE_LINE),
    "no_stills": (HEAD + "## Panel 1 — Wet Road\nPrompt: The courier pedals through the rain. "
                  + IDENTITY + " " + seu.HARBOUR + " The shot is a medium shot. The camera stays "
                  "static.\nNarration: The rain had not stopped.\n\n## Panel 2 — The Bend\nPrompt: "
                  "The courier leans into the bend. " + IDENTITY + " " + seu.HARBOUR + " The shot "
                  "is a medium close-up. The courier faces the camera. The camera stays static.\n"
                  + DIALOGUE_LINE + "Narration: Every street led down to the water.\n"),
    "shots": (HEAD + "## Characters\n- \"the courier\": " + seu.COURIER + ".\n- \"the old monk\": "
              + seu.MONK + ".\n\n## Panel 1 — Wet Road\n" + PANEL1_IMAGE + PANEL1_REST
              + "## Panel 2 — The Bend\nImage: " + seu.HARBOUR + " " + IDENTITY + " The courier "
                "leans right. The courier faces the camera. The shot is a medium close-up.\n"
                "Motion: The courier leans into the bend. The courier faces the camera. The camera "
                "stays static.\n" + DIALOGUE_LINE
              + "Narration: Every street led down to the water.\n"),
}


def test_dlg15_assembly_goldens_and_dedupe(ws, tmp_path):
    for mode, golden in GOLDEN_SPEAKING.items():
        ctx = seu.make_ctx(se, ws, mode=mode, panels=2)
        raw = seu.plan_json(mode, 2)
        raw["beats"][1]["speaker"] = "c1"
        plan, _shape = se.normalize_plan(ctx, raw)
        text = se.assemble(ctx, plan, SPEAKING_WRITERS[mode])
        assert text == golden, mode
        path = tmp_path / ("%s.md" % mode)
        path.write_text(text, encoding="utf-8")
        panel = story_manifest._parse_prompts_md(str(path))[1][1]
        assert panel["dialogue"] == "the courier: " + LINE
        assert character_lib.parse_dialogue(panel["dialogue"], PHRASES) == ("the courier", LINE,
                                                                            None)
        labels = [label for label, _text in se.story_fields(mode, 2, panel)]
        assert labels[-2:] == ["Dialogue", "Narration"], mode
        assert [label for label, _text in se.story_fields(mode, 2, panel, False)][-1] == "Dialogue"
    ctx = seu.make_ctx(se, ws, mode="shots", panels=2)
    plan, _shape = se.normalize_plan(ctx, seu.plan_json("shots", 2))
    parts = [dict(SPEAKING_WRITERS["shots"][0]),
             dict(SPEAKING_WRITERS["shots"][1], motion="The courier turns. The camera slowly pans "
                                                       "left.")]
    assert dict(se.panel_fields(ctx, plan, parts, 2))["Motion"] == (
        "The courier turns. The camera slowly pans left.")
    assert se.pasted_pieces(ctx, plan, 2)["motion"] == ["The camera tracks alongside the movement."]
    parts[1]["motion"] = "The courier turns. The camera viewpoint is front-facing."
    assert dict(se.panel_fields(ctx, plan, parts, 2))["Motion"] == (
        "The courier turns. The camera viewpoint is front-facing. The camera tracks alongside the "
        "movement.")
    raw = seu.plan_json("shots", 2)
    raw["beats"][1]["speaker"] = "c1"
    plan, _shape = se.normalize_plan(ctx, raw)
    parts[1]["motion"] = "The courier turns. The camera slowly pans left."
    assert dict(se.panel_fields(ctx, plan, parts, 2))["Motion"] == (
        "The courier turns. The camera slowly pans left. The courier faces the camera. The camera "
        "stays static.")
    assert se.pasted_pieces(ctx, plan, 2)["motion"] == ["The courier faces the camera.",
                                                        "The camera stays static."]
    lib = se._character_lib(WS)
    fields = [("Motion", "The courier waits."),
              ("Dialogue", "the courier: Tell the old monk <later>.")]
    assert se._field_checks(ctx, lib, plan, 2, "T", fields, {"Dialogue": "Tell the old monk "
                                                                         "<later>."},
                            ("N4", "N10"), []) == ([], [])
```

**1.2.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    assert {"grey", "kimono", "camera", "close-up", "palette"} <= se.APPEARANCE_WORDS
```

with:

```python
    assert {"grey", "kimono", "palette"} <= se.APPEARANCE_WORDS
    assert not ({"camera", "close-up"} & se.APPEARANCE_WORDS)
```

**1.3.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
         ["panel 2: N3 appearance: Motion: says 'grey'; panels after the first never re-describe "
          "appearance, clothing, setting, lighting, colour, style or camera"]),
```

with:

```python
         ["panel 2: N3 appearance: Motion: says 'grey'; panels after the first never re-describe "
          "appearance, clothing, setting, lighting, colour or style"]),
```

**1.4.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
                                                "camera slowly pans left past the boats.")},
         ["panel 2: N3 appearance: Motion: says 'camera'; panels after the first never re-describe "
          "appearance, clothing, setting, lighting, colour, style or camera"]),
```

with:

```python
                                                "camera slowly pans left past the boats.")},
         []),
```

**1.5.** Append to `tests/test_dialogue.py`:

```python
def test_shots_s5_ignores_the_pasted_facing_sentence(ws):
    # Controller ruling Q1 (Spec amendment 1): the pasted facing sentence is not an S5 action.
    s5 = ("panel 2: S5 one action: Motion: has 2 action sentences; it must have exactly one, "
          "optionally followed by a camera sentence")
    ctx, plan, parts, text, path = _story(ws, "shots", 3, plan_mut=_speaking(2),
                                          replies={2: {"dialogue": LINE}})
    hard, advisory = se.panel_checks(ctx, plan, parts, text, path)
    assert not [m for m in hard + advisory if " S5 " in m]
    panels = story_manifest._parse_prompts_md(path)[1]
    assert panels[1]["motion"].endswith(" The courier faces the camera. The camera stays static.")
    assert s5 in character_lib.shots_violations(text, panels, 3, [])
    assert s5 not in character_lib.shots_violations(text, panels, 3, [], ignore_facing=True)
    panels[1]["motion"] = panels[1]["motion"].replace(
        "The courier faces the camera.", "The courier faces the camera. The courier waves.")
    assert s5 in character_lib.shots_violations(text, panels, 3, [], ignore_facing=True)
    assert se.FACING_SENTENCE == character_lib.FACING_SENTENCE
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k dlg15 2>&1 | tail -3
python3 -m pytest -q -p no:cacheprovider tests/test_story_engine.py -k "rst12 or rst20_" 2>&1 | tail -3
```

Expected: `1 failed` (the chained golden lacks the facing sentence and the `Dialogue:` line), then `2 failed` (`test_rst12_lexicons`, `test_rst20_panel_checks`). `python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k s5_ignores` also gives `1 failed` (`AttributeError ... 'FACING_SENTENCE'`).

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace the whole of `pasted_pieces`, this text, which occurs exactly once:

```python
def pasted_pieces(ctx, plan, k):
    """{field: [pasted sentences in assembly order]} for panel k (RS14): the pieces of each
    assembled field that the writer does not write."""
    beat = plan["beats"][k - 1]
    by_cast = {c["id"]: c for c in plan["cast"]}
    by_location = {l["id"]: l for l in plan["locations"]}
    setting = by_location[beat["location"]]["setting"] if beat["location"] in by_location else ""
    identities = [identity(by_cast[c]) for c in beat["cast"] if c in by_cast]
    shot = shot_sentence(beat) if beat["shot"] in SHOT_TYPES else ""
    camera = dict(CAMERA_SENTENCES).get(beat["camera"], "")
    pieces = [setting] + identities + [shot]
    if ctx.mode == "chained":
        if k == 1:
            return {"image": pieces, "motion": [camera], "narration": []}
        return {"motion": [], "narration": []}
    if ctx.mode == "no_stills":
        return {"prompt": identities + [setting, shot, camera], "narration": []}
    return {"image": pieces, "motion": [camera], "narration": []}
```

with:

```python
FACING_SENTENCE = "%s faces the camera."
SPEAKING_CAMERA = "The camera stays static."
# CM4: on a non-speaking panel, a writer camera sentence that names one of these movements takes
# the place of the planned camera sentence in the assembled field.
CAMERA_MOTION_RE = re.compile(r"\b(?:static|still|holds?|locked-off|push(?:es)?\s+in|push-in|"
                              r"pull(?:s)?\s+back|pull-back|pans?|tilts?|tracks?|tracking|dolly|"
                              r"dollies|zooms?|orbits?|cranes?|handheld|follows?)\b", re.IGNORECASE)


def _sentences(text):
    """The non-empty sentences of a text, stripped."""
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]


def _facing(ctx, plan, k):
    """[the pasted "<Speaker> faces the camera." sentence] on a speaking panel, else [] (SP4)."""
    phrase = speaker_phrase(plan, k) if panel_speaks(ctx, plan, k) else None
    return [FACING_SENTENCE % (phrase[:1].upper() + phrase[1:])] if phrase else []


def _moves_camera(ctx, plan, text):
    """True when writer text holds a camera sentence (_is_camera_sentence with the plan's cast
    phrases) that names a camera movement (CAMERA_MOTION_RE) (CM4)."""
    if not CAMERA_MOTION_RE.search(text or ""):
        return False
    lib = _character_lib(ctx.ws)
    phrases = [c["phrase"] for c in plan["cast"] if c["phrase"]]
    return any(lib._is_camera_sentence(s, phrases) and CAMERA_MOTION_RE.search(s)
               for s in _sentences(text))


def pasted_pieces(ctx, plan, k):
    """{field: [pasted sentences in assembly order]} for panel k (RS14; dialogue spec SP4): the
    pieces of each assembled field that the writer does not write. A speaking panel adds the
    facing sentence (and, chained k >= 2, SPEAKING_CAMERA). The planned camera sentence is always
    listed, even when CM4 leaves it out of the assembled field."""
    beat = plan["beats"][k - 1]
    by_cast = {c["id"]: c for c in plan["cast"]}
    by_location = {l["id"]: l for l in plan["locations"]}
    setting = by_location[beat["location"]]["setting"] if beat["location"] in by_location else ""
    identities = [identity(by_cast[c]) for c in beat["cast"] if c in by_cast]
    shot = shot_sentence(beat) if beat["shot"] in SHOT_TYPES else ""
    camera = dict(CAMERA_SENTENCES).get(beat["camera"], "")
    facing = _facing(ctx, plan, k)
    pieces = [setting] + identities + facing + [shot]
    if ctx.mode == "chained":
        if k == 1:
            return {"image": pieces, "motion": facing + [camera], "narration": []}
        return {"motion": facing + ([SPEAKING_CAMERA] if facing else []), "narration": []}
    if ctx.mode == "no_stills":
        return {"prompt": identities + [setting, shot] + facing + [camera], "narration": []}
    return {"image": pieces, "motion": facing + [camera], "narration": []}
```

**3.2.** Edit `story_engine.py`: replace the whole of `panel_fields`, this text, which occurs exactly once:

```python
def panel_fields(ctx, plan, parts, k):
    """[(Label, assembled text)] of panel k in file order (RS14)."""
    p = parts[k - 1]
    pasted = pasted_pieces(ctx, plan, k)

    def join(pieces):
        return " ".join(_sentence(piece) for piece in pieces if piece and piece.strip())

    fields = []
    if (ctx.mode == "chained" and k == 1) or ctx.mode == "shots":
        image = pasted["image"]
        fields.append(("Image", join(image[:-1] + [p.get("image", "")] + image[-1:])))
    if ctx.mode == "no_stills":
        fields.append(("Prompt", join([p.get("prompt", "")] + pasted["prompt"])))
    else:
        fields.append(("Motion", join([p.get("motion", "")] + pasted["motion"])))
    if ctx.narration is True or (ctx.narration and p.get("narration", "").strip()):
        fields.append(("Narration", _sentence(p.get("narration", ""))))
    return fields
```

with:

```python
def panel_fields(ctx, plan, parts, k):
    """[(Label, assembled text)] of panel k in file order (RS14; dialogue spec SP4): Image: where
    the mode has one (setting, identities, writer image, facing, shot), Motion: or Prompt: (the
    writer text, then the pasted sentences; on a non-speaking panel the planned camera sentence
    is left out when the writer text moves the camera, CM4), Dialogue: on a speaking panel
    ("<phrase>: <line>"), then Narration: when narration is True and the part is non-empty or the
    panel does not speak."""
    p = parts[k - 1]
    pasted = pasted_pieces(ctx, plan, k)
    facing = _facing(ctx, plan, k)

    def join(pieces):
        return " ".join(_sentence(piece) for piece in pieces if piece and piece.strip())

    fields = []
    if (ctx.mode == "chained" and k == 1) or ctx.mode == "shots":
        image = pasted["image"]
        cut = len(image) - 1 - len(facing)
        fields.append(("Image", join(image[:cut] + [p.get("image", "")] + image[cut:])))
    key = "prompt" if ctx.mode == "no_stills" else "motion"
    pieces = pasted[key]
    if not facing and pieces and _moves_camera(ctx, plan, p.get(key, "")):
        pieces = pieces[:-1]
    fields.append((LABELS[key], join([p.get(key, "")] + pieces)))
    if facing:
        line = _sentence(_character_lib(ctx.ws).clean_line(p.get("dialogue", "")))
        fields.append(("Dialogue", (speaker_phrase(plan, k) + ": " + line).rstrip()))
    if ctx.narration is True and (p.get("narration", "").strip() or not facing):
        fields.append(("Narration", _sentence(p.get("narration", ""))))
    return fields
```

**3.3.** Edit `story_engine.py`: replace the whole of `story_fields`, this text, which occurs exactly once:

```python
def story_fields(mode, k, panel, narration=True):
    """[(Label, text)] of a parsed story.md panel, the fields RS3 assembles for mode/panel k
    (no Narration when narration is False)."""
    if mode == "no_stills":
        labels = ("Prompt", "Narration")
    elif mode == "chained" and k >= 2:
        labels = ("Motion", "Narration")
    else:
        labels = ("Image", "Motion", "Narration")
    labels = labels if narration else labels[:-1]
    return [(label, panel[label.lower()]) for label in labels]
```

with:

```python
def story_fields(mode, k, panel, narration=True):
    """[(Label, text)] of a parsed story.md panel: the fields RS3 assembles for mode/panel k, a
    Dialogue: whenever the panel has one (every mode, every narration value; dialogue spec SP4),
    and no Narration when narration is False."""
    if mode == "no_stills":
        labels = ["Prompt"]
    elif mode == "chained" and k >= 2:
        labels = ["Motion"]
    else:
        labels = ["Image", "Motion"]
    if panel.get("dialogue", "").strip():
        labels.append("Dialogue")
    if narration:
        labels.append("Narration")
    return [(label, panel[label.lower()]) for label in labels]
```

**3.4.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        if "N4" in ids and label != "Narration" and beat is not None:
```

with:

```python
        if "N4" in ids and label not in ("Narration", "Dialogue") and beat is not None:
```

**3.5.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        if "N10" in ids:
```

with:

```python
        if "N10" in ids and label != "Dialogue":
```

**3.6.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    lighting lit sunlight moonlight palette colour color cinematic photorealistic rendered style
    camera lens zoom zooms dolly framing close-up""".split())
```

with:

```python
    lighting lit sunlight moonlight palette colour color cinematic photorealistic rendered style
    """.split())
```

**3.7.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
# N3: "camera"/"lens" as the target of an action ("holds it up to the camera") is a direction,
# not a camera description, so it is blanked before the appearance search.
_CAMERA_TARGET_RE = re.compile(r"\b(?:to|toward|towards|into|at|from|past)\s+(?:the\s+)?(?:camera|lens)\b",
                               re.IGNORECASE)
```

with:

```python
# Camera language is never an N3 fault (dialogue spec CM2, D5).
```

**3.8.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
                blanked = lib._blank(text, lib._passage_spans(
                    text, list(phrases) + [p["name"] for p in plan["props"] if p["name"]]))
                blanked = _CAMERA_TARGET_RE.sub(lambda m: " " * len(m.group(0)), blanked)
```

with:

```python
                blanked = lib._blank(text, lib._passage_spans(
                    text, list(phrases) + [p["name"] for p in plan["props"] if p["name"]]))
```

**3.9.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
                        "says %s; panels after the first never re-describe appearance, clothing, "
                        "setting, lighting, colour, style or camera" % _q(word))
```

with:

```python
                        "says %s; panels after the first never re-describe appearance, clothing, "
                        "setting, lighting, colour or style" % _q(word))
```

**3.10.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
def motion_problems(motion, phrases=()):
```

with:

```python
# The sentence the robust engine pastes into a speaking panel's Motion: (dialogue spec SP4); with
# shots_violations(ignore_facing=True) it is not an S5 action sentence (controller ruling Q1).
FACING_SENTENCE = "%s faces the camera."


def _drop_facing(text, phrases):
    """text without the sentences that are exactly a pasted "<Phrase> faces the camera." for one
    of phrases (case-insensitive)."""
    facing = set((FACING_SENTENCE % (p[:1].upper() + p[1:])).lower() for p in phrases)
    return " ".join(s.strip() for s in _SENTENCE_SPLIT_RE.split(text.strip())
                    if s.strip() and s.strip().lower() not in facing)


def motion_problems(motion, phrases=()):
```

**3.11.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
def shots_violations(text, panels, expected_panels, members, narration=True):
```

with:

```python
def shots_violations(text, panels, expected_panels, members, narration=True, ignore_facing=False):
```

**3.12.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
    extras and animals. narration False (--no-narration) drops the Narration: requirement."""
```

with:

```python
    extras and animals. narration False (--no-narration) drops the Narration: requirement.
    ignore_facing (the robust story engine) leaves a Motion: sentence that is exactly a pasted
    "<Phrase> faces the camera." out of S5's action count."""
```

**3.13.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
                    for rule, detail in motion_problems(p["motion"], humans + animals)]
```

with:

```python
                    for rule, detail in motion_problems(
                        _drop_facing(p["motion"], humans + animals) if ignore_facing
                        else p["motion"], humans + animals)]
```

**3.14.** Edit `story_engine.py`: replace this text, which occurs exactly once (in `panel_checks`):

```python
        hard += lib.shots_violations(text, panels, ctx.panels, ctx.members, ctx.narration is True)
```

with:

```python
        hard += lib.shots_violations(text, panels, ctx.panels, ctx.members, ctx.narration is True,
                                     ignore_facing=True)
```

**3.15.** Edit `story_engine.py`: replace this text, which occurs exactly once (in `recheck`, with a plan):

```python
                hard += lib.shots_violations(text, parsed, ctx.panels, ctx.members,
                                            ctx.narration is True)
```

with:

```python
                hard += lib.shots_violations(text, parsed, ctx.panels, ctx.members,
                                            ctx.narration is True, ignore_facing=True)
```

**3.16.** Edit `story_engine.py`: replace this text, which occurs exactly once (in `recheck`, without a plan):

```python
        violations = lib.shots_violations(text, parsed, ctx.panels, ctx.members,
                                               ctx.narration is True)
```

with:

```python
        violations = lib.shots_violations(text, parsed, ctx.panels, ctx.members,
                                               ctx.narration is True, ignore_facing=True)
```

**3.17.** Edit `story_engine.py`: replace this text, which occurs exactly once (in `plan_free_report`):

```python
        hard += lib.shots_violations(text, parsed, panels, members)
```

with:

```python
        hard += lib.shots_violations(text, parsed, panels, members, ignore_facing=True)
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_story_engine.py tests/test_lora_catalog.py 2>&1 | tail -1
```

Expected: no failure other than the known `test_rst62_import_sets` (`test_rst18_assembly_goldens` passes unchanged: no fixture writer text moves the camera). Also run `python3 -m pytest -q -p no:cacheprovider tests/test_shots_mode.py tests/test_character_lib.py 2>&1 | tail -1` (no failure: the legacy shots checks use the default). Compile check with `FILES` = `story_engine.py character_lib.py tests/test_dialogue.py tests/test_story_engine.py`; expected `compiled 4` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py character_lib.py tests/test_dialogue.py tests/test_story_engine.py
git diff --cached --name-only
git commit -m "feat(dialogue): assemble Dialogue:, the pasted facing and camera sentences, camera dedupe; camera words leave N3; the facing sentence is no S5 action (SP4, CM4, CM2, Q1, DLG15)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Timing and action rules T1/T2/T3, N18, and the Dialogue variants of N16/N17

Implements spec 6.2, the N18/T rows of 6.3, the `_field_checks` and `GENERATION_CHECKS`/`RECHECK_IDS` bullets of 6.4 for T1/T2/T3/N18, and the N16/N17 rows of Section 7. Tests DLG16, DLG17 and Review Focus 4.

**Files:**
- Modify: `story_engine.py`
- Modify: `tests/test_dialogue.py`
- Modify: `tests/test_story_engine.py` (`test_rst20b_narration_speaker`: spec 9.2 reason "the 29-word alias adds an advisory T1")

**Interfaces:**
- Consumes: Task 1's `parse_dialogue`, `split_fragments`, `dialogue_word_cap`, `DIALOGUE_MAX_FRAGMENTS`; Task 2's `_is_camera_sentence`; Task 7's `engine_seconds`; Task 10's `_sentences`, `CAMERA_MOTION_RE`.
- Produces: `ACTION_SECONDS = 3.0`, `NO_STILLS_BEAT_SECONDS = 1.0`, `SEQUENCE_RE`, `NO_STILLS_CONNECTOR_RE`, `STILL_CAMERA_MOVES`, `SPLIT_INSTRUCTION`; `cast_phrases(ctx, plan) -> [str]`; `action_units(ctx, lib, text, phrases) -> (actions, units, max_actions)`; `over_cap(ctx, lib, line) -> detail str or None`; hard messages `"panel %d: T1 spoken timing: Dialogue: is ..."`, `"panel %d: T2 action amount: ..."`, `"panel %d: T3 action overload: ..."`, `"panel %d: N18 dialogue: Dialogue: ..."`; the advisory alias T1 `"panel %d: T1 spoken timing: Narration: speaks ..."`; `GENERATION_CHECKS` and `RECHECK_IDS` end with `"N18", "T1", "T2", "T3"`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_dlg16_t1_spoken_timing`, `test_dlg17_t2_t3_action_amount`, `test_n16_n17_n18_dialogue_messages`, `test_review_focus_4_a_short_clip_uses_the_same_cap_in_engine_and_manifest`.

**1.1.** Append to `tests/test_dialogue.py`:

```python
# --- DLG16, DLG17, Review Focus 4: T1, T2, T3, N18 and the Dialogue N16/N17 (6.2, 7) ------------

BUSY = "The courier stops at the crates, then turns, then pedals on toward the far end of the wet road."
OVERLOAD = ("The courier stops, then turns, then waves, then pedals on, then rides away along the "
            "wet road.")
SIXTEEN = "I carry a sealed letter from the old harbour master for the abbot of this temple."


def _checks(ws, mode, **kw):
    ctx, plan, parts, text, path = _story(ws, mode, 3, **kw)
    return se.panel_checks(ctx, plan, parts, text, path)


def _only(messages, rule):
    return [m for m in messages if " %s " % rule in m]


def test_dlg16_t1_spoken_timing(ws):
    def t1(line):
        hard, advisory = _checks(ws, "chained", plan_mut=_speaking(2), replies={2: {"dialogue": line}})
        assert not _only(advisory, "T1")
        return _only(hard, "T1")

    assert t1(SIXTEEN) == ["panel 2: T1 spoken timing: Dialogue: is 16 words in 1 sentences; a "
                           "6-second clip fits at most 14 words in 1 sentences" + SPLIT]
    assert t1("Come in now. Sit by the warm fire. He will see you soon.") == [
        "panel 2: T1 spoken timing: Dialogue: is 13 words in 3 sentences; a 6-second clip fits at "
        "most 12 words in 3 sentences" + SPLIT]
    assert t1("Stop. Wait. Look. Go.") == [
        "panel 2: T1 spoken timing: Dialogue: is 4 words in 4 sentences; a 6-second clip fits at "
        "most 11 words in 4 sentences" + SPLIT]
    assert t1(LINE) == []
    hard, advisory = _checks(ws, "chained", replies={2: {"narration": "the courier: " + SIXTEEN}})
    assert not _only(hard, "T1")
    assert _only(advisory, "T1") == [
        "panel 2: T1 spoken timing: Narration: speaks 16 words in 1 sentences; a 6-second clip "
        "fits at most 14 words in 1 sentences" + SPLIT]


def test_dlg17_t2_t3_action_amount(ws):
    def t(mode, key, text):
        hard, advisory = _checks(ws, mode, replies={2: {key: text}})
        assert not _only(advisory, "T2") and not _only(advisory, "T3")
        return _only(hard, "T2") + _only(hard, "T3")

    cut = ", so cut the extra actions and keep every other sentence word for word"
    assert t("chained", "motion", "The courier stops at the crates, then pedals on toward the far "
                                  "end of the wet road.") == []
    assert t("chained", "motion", BUSY) == [
        "panel 2: T2 action amount: Motion: holds 3 actions; a 6-second clip fits at most 2" + cut]
    assert t("chained", "motion", OVERLOAD) == [
        "panel 2: T3 action overload: Motion: holds 5 actions; a 6-second clip fits at most 2 and "
        "cannot render more than 4; give the extra actions their own panels"]
    assert t("shots", "motion", "The courier turns. The courier waves. The courier steps "
                                "forward.") == [
        "panel 2: T2 action amount: Motion: holds 3 actions; a 6-second clip fits at most 2" + cut]
    six = ("The courier pedals along the wet harbour road. Initially the tyres hiss. A moment later "
           "a gull cries. Moments later the rain thickens. Finally the bell rings. After that the "
           "lamps glow. Soon after the courier slows.")
    assert t("no_stills", "prompt", six) == [
        "panel 2: T2 action amount: Prompt: holds 7 actions; a 6-second clip fits at most 6" + cut]
    assert t("chained", "motion", "The camera slowly pans left. The camera holds.") == [
        "panel 2: T2 action amount: Motion: has no physical action; a 6-second clip needs one, so "
        "add one action sentence and keep every other sentence word for word"]
    for mode in ("chained", "no_stills", "shots"):
        ctx, plan, parts, text, path = _story(ws, mode, 6)
        hard, advisory = se.panel_checks(ctx, plan, parts, text, path)
        assert not [m for m in hard + advisory if " T1 " in m or " T2 " in m or " T3 " in m], mode
    assert se.GENERATION_CHECKS[16:20] == ("N18", "T1", "T2", "T3")
    assert se.RECHECK_IDS[14:18] == ("N18", "T1", "T2", "T3")


def test_n16_n17_n18_dialogue_messages(ws):
    ctx, plan, _parts, _text, _path = _story(ws, "chained", 3, plan_mut=_speaking(2),
                                             replies={2: {"dialogue": "Keep moving."}})
    lib = se._character_lib(WS)
    ids = ("N16", "N17", "N18", "T1")

    def checks(fields, writers=None, beat_cast=None):
        p = copy.deepcopy(plan)
        if beat_cast:
            p["beats"][1]["cast"] = beat_cast
        return se._field_checks(ctx, lib, p, 2, "T", fields, writers or {}, ids, [])

    waits = ("Motion", "The courier waits.")
    assert checks([waits, ("Dialogue", "the stranger: Halt.")]) == ([
        "panel 2: N18 dialogue: Dialogue: names 'the stranger', which is no character's referring "
        "phrase; use one of: 'the courier', 'the old monk'"], [])
    assert checks([waits, ("Dialogue", "the courier:")]) == ([
        "panel 2: N18 dialogue: Dialogue: has a speaker but no words"], [])
    assert checks([waits, ("Dialogue", "the old monk: Wait for me.")]) == ([], [
        "panel 2: N16 speaker: Dialogue: is spoken by 'the old monk', who is not in this shot; put "
        "'the old monk' in the shot or move the line to a panel that shows them"])
    assert checks([waits, ("Dialogue", "the courier: Keep moving.")], beat_cast=["c1", "c2"]) == (
        [], ["panel 2: N17 speaking shot: Dialogue: 'the courier' speaks in a shot that also shows "
             "'the old monk'; a speaking shot shows only the speaker"])
    pans = "The courier waits. The camera slowly pans left."
    assert checks([("Motion", pans), ("Dialogue", "the courier: Keep moving.")],
                  {"Motion": pans}) == ([], [
        "panel 2: N17 speaking shot: Motion: has the camera direction 'The camera slowly pans "
        "left.' while 'the courier' speaks; a speaking shot keeps the camera static"])
    pushes = "The courier waits. The camera slowly pushes in."
    assert checks([("Motion", pushes), ("Dialogue", "the courier: Keep moving.")],
                  {"Motion": pushes}) == ([], [])


def test_review_focus_4_a_short_clip_uses_the_same_cap_in_engine_and_manifest(ws, tmp_path,
                                                                              monkeypatch, capsys):
    ten = "I carry a letter for the abbot of this temple."
    short = {"seconds": "4", "clip_seconds": 97 / 24.0}
    hard, _advisory = _checks(ws, "chained", plan_mut=_speaking(2), replies={2: {"dialogue": ten}},
                              ctx_kw=short)
    assert _only(hard, "T1") == ["panel 2: T1 spoken timing: Dialogue: is 10 words in 1 "
                                 "sentences; a 4-second clip fits at most 9 words in 1 sentences"
                                 + SPLIT]
    hard, _advisory = _checks(ws, "chained", plan_mut=_speaking(2), replies={2: {"dialogue": ten}})
    assert _only(hard, "T1") == []
    story_md, images, mws = _manifest_ws(tmp_path, monkeypatch, "rf4", CHAINED_DG9.replace(
        "@@LINES@@", "Dialogue: the old monk: " + ten), plan=CAST_PLAN)
    capsys.readouterr()
    assert story_manifest.main(_manifest_argv("rf4", story_md, images, frames=97)) == 2
    assert capsys.readouterr().err == (
        "Error: panel 2: Dialogue: is 10 words in 1 sentences; a 4.04-second clip fits at most 9 "
        "words in 1 sentences" + SPLIT + "\n")
```

**1.2.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    # N14 counts the spoken words only: "the courier:" does not push 29 words over 30.
    words29 = " ".join(["go"] * 28) + " now."
    assert _story_checks(ws, "chained", part_mut=narration("the courier: " + words29)) == []
```

with:

```python
    # N14 counts the spoken words only: "the courier:" does not push 29 words over 30; the alias
    # line is over the 14-word cap, which is advisory for a Narration: line (dialogue spec 6.2).
    words29 = " ".join(["go"] * 28) + " now."
    assert _story_checks(ws, "chained", part_mut=narration("the courier: " + words29)) == [
        "panel 2: T1 spoken timing: Narration: speaks 29 words in 1 sentences; a 6-second clip "
        "fits at most 14 words in 1 sentences, and a line has at most 3 sentences; shorten the "
        "line, or split it across alternating close-up panels (the speaker, then the listener, "
        "then the speaker again)"]
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k "dlg16 or dlg17 or n16_n17 or review_focus_4" 2>&1 | tail -3
python3 -m pytest -q -p no:cacheprovider tests/test_story_engine.py -k rst20b 2>&1 | tail -3
```

Expected: `4 failed` (no T or N18 message is produced; `test_review_focus_4` fails on its first assertion), then `1 failed`.

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def _norm_text(text):
    return " ".join(text.lower().split()).rstrip(".")
```

with:

```python
# Dialogue spec 6.2: the timing and action rules.
ACTION_SECONDS = 3.0
NO_STILLS_BEAT_SECONDS = 1.0
SEQUENCE_RE = re.compile(r"\b(?:then|afterwards?|whereupon|followed\s+by|as\s+soon\s+as)\b",
                         re.IGNORECASE)
NO_STILLS_CONNECTOR_RE = re.compile(r"\b(?:initially|a\s+moment\s+later|moments\s+later|finally|"
                                    r"after\s+that|soon\s+after)\b", re.IGNORECASE)
# N17: the CAMERA_MOTION_RE words that keep a speaking shot still (a slow push-in is planned).
STILL_CAMERA_MOVES = ("static", "still", "hold", "holds", "locked-off", "push in", "pushes in",
                      "push-in")
SPLIT_INSTRUCTION = ("shorten the line, or split it across alternating close-up panels (the "
                     "speaker, then the listener, then the speaker again)")


def cast_phrases(ctx, plan):
    """The plan's cast phrases, or the cast members' phrases when there is no plan."""
    if plan:
        return [c["phrase"] for c in plan["cast"] if c.get("phrase")]
    return [m.phrase for m in ctx.members]


def action_units(ctx, lib, text, phrases):
    """(action sentences, action units, the most actions the clip fits) of a writer action text
    (dialogue spec 6.2): chained 1 + sequence markers + sentences beyond two; shots sentences +
    sequence markers; no_stills 1 + sequence markers + connectors. A camera sentence
    (_is_camera_sentence with phrases) is not an action sentence."""
    actions = len([s for s in _sentences(text) if not lib._is_camera_sentence(s, phrases)])
    seq = len(SEQUENCE_RE.findall(text))
    if ctx.mode == "chained":
        units = 1 + seq + max(0, actions - 2)
    elif ctx.mode == "shots":
        units = actions + seq
    else:
        units = 1 + seq + len(NO_STILLS_CONNECTOR_RE.findall(text))
    per = NO_STILLS_BEAT_SECONDS if ctx.mode == "no_stills" else ACTION_SECONDS
    return actions, units, max(1, int(engine_seconds(ctx) / per + 1e-9))


def over_cap(ctx, lib, line):
    """The T1 detail when a spoken line does not fit this clip (more words than its fragment-aware
    cap, or more than three sentences), else None (dialogue spec 6.2)."""
    n = len(lib.split_fragments(line))
    words = len(line.split())
    cap = lib.dialogue_word_cap(engine_seconds(ctx), n)
    if words <= cap and n <= lib.DIALOGUE_MAX_FRAGMENTS:
        return None
    return ("%d words in %d sentences; a %s-second clip fits at most %d words in %d sentences, and "
            "a line has at most 3 sentences; %s" % (words, n, ctx.seconds, cap, n,
                                                    SPLIT_INSTRUCTION))


def _norm_text(text):
    return " ".join(text.lower().split()).rstrip(".")
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    if "N12" in ids and ctx.mode == "chained":
        writer = writers.get("Motion", "")
```

with:

```python
    known = cast_phrases(ctx, plan)
    dialogue = dict(fields).get("Dialogue", "")
    if dialogue.strip():
        _phrase, line, problem = lib.parse_dialogue(dialogue, known)
        if problem:
            if "N18" in ids:
                hard.append("%s N18 dialogue: Dialogue: %s" % (prefix, problem))
        elif "T1" in ids:
            detail = over_cap(ctx, lib, line)
            if detail:
                hard.append("%s T1 spoken timing: Dialogue: is %s" % (prefix, detail))
    elif "T1" in ids:
        spoken = dict(fields).get("Narration", "")
        speaker, speech = lib.split_speaker(spoken, known) if ":" in spoken else (None, "")
        detail = over_cap(ctx, lib, speech) if speaker else None
        if detail:
            advisory.append("%s T1 spoken timing: Narration: speaks %s" % (prefix, detail))
    action_label = "Prompt" if ctx.mode == "no_stills" else "Motion"
    if ("T2" in ids or "T3" in ids) and action_label in dict(fields):
        actions, units, most = action_units(ctx, lib, writers.get(action_label, ""), known)
        if actions == 0:
            if "T2" in ids:
                hard.append("%s T2 action amount: %s: has no physical action; a %s-second clip "
                            "needs one, so add one action sentence and keep every other sentence "
                            "word for word" % (prefix, action_label, ctx.seconds))
        elif units > 2 * most:
            if "T3" in ids:
                hard.append("%s T3 action overload: %s: holds %d actions; a %s-second clip fits at "
                            "most %d and cannot render more than %d; give the extra actions their "
                            "own panels" % (prefix, action_label, units, ctx.seconds, most,
                                            2 * most))
        elif units > most:
            if "T2" in ids:
                hard.append("%s T2 action amount: %s: holds %d actions; a %s-second clip fits at "
                            "most %d, so cut the extra actions and keep every other sentence word "
                            "for word" % (prefix, action_label, units, ctx.seconds, most))
    if "N12" in ids and ctx.mode == "chained":
        writer = writers.get("Motion", "")
```

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    narration = dict(fields).get("Narration", "")
    if "N16" in ids and beat is not None:
        found = lib.speaker_prefix(narration)
        speech_only = ctx.narration == "speech"
        if speech_only and narration.strip() and (
                not found or lib.split_speaker(narration, [c["phrase"] for c in plan["cast"]])[0]
                is None):
            add(hard, "N16", "speaker", "Narration",
                "is voice-over, but this story is speech-only; start it with the referring "
                "phrase of the character in the shot who says it and a colon, or leave it empty")
        elif found:
            on_screen = [by_cast[c]["phrase"] for c in beat["cast"] if c in by_cast]
            known = [c["phrase"] for c in plan["cast"]]
            if lib.split_speaker(narration, on_screen)[0] is not None:
                pass
            elif lib.split_speaker(narration, known)[0] is not None:
                add(hard, "N16", "speaker", "Narration",
                    "is spoken by %s, who is not in this shot; only a character on screen can "
                    "speak, so make it voice-over (no prefix) or put %s in the shot"
                    % (_q(found[0]), _q(found[0])))
            else:
                add(advisory, "N16", "speaker", "Narration",
                    "starts with %s, which is no character's referring phrase, so it is read as "
                    "voice-over; start a spoken line with the speaker's referring phrase, or drop "
                    "the colon" % _q(found[0] + ":"))
    if "N17" in ids and beat is not None and narration.strip():
        on_screen = [by_cast[c]["phrase"] for c in beat["cast"] if c in by_cast]
        speaker = lib.split_speaker(narration, on_screen)[0]
        shot_applies = ctx.mode != "chained" or k == 1
        if speaker and shot_applies and beat["shot"] in WIDE_SHOTS:
            add(advisory, "N17", "speaking shot", "Narration",
                "%s speaks in a %s, too small to read the lips, so it plays as voice-over; use "
                "a medium shot or closer" % (_q(speaker), beat["shot"]))
        held = speaker and next((w for w in (_first(HELD_EXPRESSION_RE, writers.get(label, ""))
                                             for label in action_fields) if w), None)
        if held:
            add(advisory, "N17", "speaking shot", "Narration",
                "%s speaks, but the panel holds the expression %s, which freezes the mouth; "
                "describe the speaking instead" % (_q(speaker), _q(held)))
```

with:

```python
    narration = dict(fields).get("Narration", "")
    on_screen = ([by_cast[c]["phrase"] for c in beat["cast"] if c in by_cast]
                 if beat is not None else [])
    spoken_by = lib.parse_dialogue(dialogue, known)[0] if dialogue.strip() else None
    if "N16" in ids and beat is not None:
        found = lib.speaker_prefix(narration)
        speech_only = ctx.narration == "speech"
        if spoken_by is not None:
            if spoken_by.lower() not in [p.lower() for p in on_screen]:
                add(advisory, "N16", "speaker", "Dialogue",
                    "is spoken by %s, who is not in this shot; put %s in the shot or move the "
                    "line to a panel that shows them" % (_q(spoken_by), _q(spoken_by)))
        elif speech_only and narration.strip() and (
                not found or lib.split_speaker(narration, known)[0] is None):
            add(hard, "N16", "speaker", "Narration",
                "is voice-over, but this story is speech-only; start it with the referring "
                "phrase of the character in the shot who says it and a colon, or leave it empty")
        elif found:
            if lib.split_speaker(narration, on_screen)[0] is not None:
                pass
            elif lib.split_speaker(narration, known)[0] is not None:
                add(hard, "N16", "speaker", "Narration",
                    "is spoken by %s, who is not in this shot; only a character on screen can "
                    "speak, so make it voice-over (no prefix) or put %s in the shot"
                    % (_q(found[0]), _q(found[0])))
            else:
                add(advisory, "N16", "speaker", "Narration",
                    "starts with %s, which is no character's referring phrase, so it is read as "
                    "voice-over; start a spoken line with the speaker's referring phrase, or drop "
                    "the colon" % _q(found[0] + ":"))
    if "N17" in ids and beat is not None:
        if spoken_by is not None:
            speech_label = "Dialogue"
            speaker = (spoken_by if spoken_by.lower() in [p.lower() for p in on_screen] else None)
        else:
            speech_label = "Narration"
            speaker = lib.split_speaker(narration, on_screen)[0] if narration.strip() else None
        if speaker:
            shot_applies = ctx.mode != "chained" or k == 1
            if shot_applies and beat["shot"] in WIDE_SHOTS:
                add(advisory, "N17", "speaking shot", speech_label,
                    "%s speaks in a %s, too small to read the lips, so it plays as voice-over; "
                    "use a medium shot or closer" % (_q(speaker), beat["shot"]))
            held = next((w for w in (_first(HELD_EXPRESSION_RE, writers.get(field, ""))
                                     for field in action_fields) if w), None)
            if held:
                add(advisory, "N17", "speaking shot", speech_label,
                    "%s speaks, but the panel holds the expression %s, which freezes the mouth; "
                    "describe the speaking instead" % (_q(speaker), _q(held)))
            others = [p for p in on_screen if p.lower() != speaker.lower()]
            if speech_label == "Dialogue" and others:
                add(advisory, "N17", "speaking shot", "Dialogue",
                    "%s speaks in a shot that also shows %s; a speaking shot shows only the "
                    "speaker" % (_q(speaker), ", ".join(_q(p) for p in others)))
            for sentence in _sentences(writers.get(action_label, "")):
                move = CAMERA_MOTION_RE.search(sentence)
                if (move and lib._is_camera_sentence(sentence, known)
                        and " ".join(move.group(0).lower().split()) not in STILL_CAMERA_MOVES):
                    add(advisory, "N17", "speaking shot", action_label,
                        "has the camera direction %s while %s speaks; a speaking shot keeps the "
                        "camera static" % (_q(sentence), _q(speaker)))
                    break
```

**3.4.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
GENERATION_CHECKS = ("N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11", "N12",
                     "N14", "N15", "N16", "N17")
```

with:

```python
GENERATION_CHECKS = ("N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11", "N12",
                     "N14", "N15", "N16", "N17", "N18", "T1", "T2", "T3")
```

**3.5.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
RECHECK_IDS = ("N1", "N2", "N3", "N4", "N7", "N8", "N9", "N10", "N11", "N12", "N14", "N15",
               "N16", "N17")
```

with:

```python
RECHECK_IDS = ("N1", "N2", "N3", "N4", "N7", "N8", "N9", "N10", "N11", "N12", "N14", "N15",
               "N16", "N17", "N18", "T1", "T2", "T3")
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_story_engine.py tests/test_lora_catalog.py 2>&1 | tail -1
```

Expected: no failure other than the known `test_rst62_import_sets` (`test_rst20`, `test_rst20d` and every run test pass unchanged: no fixture panel, `SHOUT1` or `SHOUT2` holds more than two action units). Compile check with `FILES` = `story_engine.py tests/test_dialogue.py tests/test_story_engine.py`; expected `compiled 3` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_dialogue.py tests/test_story_engine.py
git diff --cached --name-only
git commit -m "feat(dialogue): T1 spoken timing, T2/T3 action amount, N18 dialogue form, Dialogue N16/N17 (6.2, 7, DLG16, DLG17)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: The round controller: blocking, two rounds, ranking, the code-only merge and a report-only judge

Implements spec 6.1, 6.5, 6.6 PG5 and PG6, 6.8 (engine part), 2.6 (`unresolved` in `story_checks.json`) and the ranking bullets of 6.4 ("Ranking (review fix 2)", `_new_rs37`, `REPAIR_IDS` replaces `WRITER_CHECK_IDS`). Tests DLG23, DLG24, DLG26.

**Files:**
- Modify: `story_engine.py`
- Modify: `tests/test_dialogue.py`
- Modify: `tests/test_story_engine.py`, limited to the spec 9.2 reasons: `test_rs4_constants` ("`CRITIC_MAX_ROUNDS` becomes 2"); `test_rst36_ranking`, `test_rst36b_a_state_that_introduces_n15_loses_a_tie` ("the new ranking key; `_new_rs37` reads advisories"); `test_rst26b_critic_retry_and_code_only_round`, `test_rst33_stop_passed`, `test_rst34_stop_plateau`, `test_rst35_stop_max_rounds`, `test_rst37_budgets_and_the_wall_clock`, `test_rst38_judge_gate`, `test_rst39_outputs_and_layout`, `test_rst43_exit_2_message`, `test_rst51_e2e_chained`, `test_rst52_e2e_no_stills_with_a_setting_patch`, `test_rst53_e2e_shots_with_two_characters`, `test_rst54_e2e_hard_fail_then_hand_edit_and_recheck`, `test_rst58_a_patch_that_names_an_undeclared_character_loses` ("`_shouting` ... is replaced by a T2 helper ... Exit-2 cases use a T1 helper ... A clean round 0 makes no critic call; max rounds is 2; `story_checks` gains `unresolved`; ... `::test_rst38` is report-only"). Every rewritten run test is written so that it also holds after Tasks 13 and 14 (its patches pass the PG3 guard, and it asserts nothing an N rule's class decides).

**Interfaces:**
- Consumes: Task 11's `cast_phrases`, `action_units`; Task 10's `_sentences`; Task 1's `split_fragments`, `dialogue_word_cap`, `DIALOGUE_MAX_FRAGMENTS`; `parse_violation`, `apply_patches(ctx, state, patches, regen=None, lora_allowed=None)` (unchanged in this task; Task 13 changes it).
- Produces: `CRITIC_MAX_ROUNDS = 2` (and no `MIN_OK_SCORE`); `NON_BLOCKING_IDS = ("T2", "T3")`; `REPAIR_IDS = ("N11", "T1", "T2", "T3")` (no `WRITER_CHECK_IDS`); `blocking(messages) -> [str]`; `unresolved(messages) -> [str]`; `n_blocking(state) -> int`; `guard_problem(ctx, plan, old, new) -> reason or None` (PG3); `line_problem(ctx, lib, line) -> reason or None` (the PG4 cap reason); `merge_repair(ctx, plan, k, old, new, ids) -> parts dict` (PG5); `_key(states, i) -> (blocking, hard, -low, -total)`; `best_round(states)` with the 6.4 key; `final_outcome(states) -> (best index, blocking list, unresolved list)`; `_checks_doc` writes `"unresolved": []` right after `"hard"`; `_Run.critic_round(k, judged)` (no `passed_only`); `_Run.critic_loop() -> stop reason`; `_Run.judge_gate()` never applies patches. In `tests/test_dialogue.py`: `_replies(mode, n, overrides=None, phrase="the courier")`, `_run(ws, tmp_path, monkeypatch, mode="chained", n=3, plan=None, panel=None, critic=(), **ctx_kw)`. In `tests/test_story_engine.py`: `BUSY`, `CALM`, `OVER_CAP`, `_busy(mode, k, text=BUSY)`, `_speaker_plan(mode, n, *ks)`, `_over_cap(mode, k)`, `_t1(k)`, `_t2(k)` replace `SHOUT1`, `SHOUT2` and `_shouting`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_dlg23_two_rounds_blocking_and_ranking`, `test_dlg24_code_only_round_merge`, `test_dlg26_judge_gate_is_report_only`.

**1.1.** Append to `tests/test_dialogue.py`:

```python
# --- DLG23, DLG24, DLG26: the round controller (6.1, 6.5, PG5, 6.8) --------------------------

def _replies(mode, n, overrides=None, phrase="the courier"):
    """The fake agent's panel script: one valid reply per panel; overrides maps a panel number to
    a list of dicts, each merged into that panel's seu.panel_json reply (one reply per call)."""
    script = {}
    for k in range(1, n + 1):
        changes = (overrides or {}).get(k, [{}])
        script[str(k)] = [seu.answer(dict(seu.panel_json(mode, k, phrase), **c)) for c in changes]
    return script


def _run(ws, tmp_path, monkeypatch, mode="chained", n=3, plan=None, panel=None, critic=(),
         **ctx_kw):
    log = seu.script_agent(monkeypatch, tmp_path,
                           plan=plan if plan is not None else [seu.answer(seu.plan_json(mode, n))],
                           panel=panel if panel is not None else _replies(mode, n),
                           critic=list(critic))
    ctx = seu.make_ctx(se, ws, mode=mode, panels=n, **ctx_kw)
    rc, advisories = se.run(ctx)
    return rc, advisories, ctx, seu.agent_log(log)


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _speaking_plan(mode, n, *ks):
    raw = seu.plan_json(mode, n)
    for k in ks:
        raw["beats"][k - 1]["speaker"] = "c1"
    return [seu.answer(raw)]


T2_MESSAGE = ("panel 2: T2 action amount: Motion: holds 3 actions; a 6-second clip fits at most 2, "
              "so cut the extra actions and keep every other sentence word for word")


def test_dlg23_two_rounds_blocking_and_ranking(ws, tmp_path, monkeypatch, capsys):
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, panel=_replies("chained", 3, {2: [
        {"motion": BUSY}]}), critic=[seu.answer(seu.critic_json((6, 6, 6), "revise")),
                                     seu.answer(seu.critic_json((7, 7, 7), "revise"))])
    assert rc == 0
    out = capsys.readouterr().out
    assert "stop: max_rounds; best round 2 (1 hard)\n" in out
    assert out.endswith("Warning: unresolved after 2 critic round(s): %s\n" % T2_MESSAGE)
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert checks["hard"] == [] and [v["message"] for v in checks["unresolved"]] == [T2_MESSAGE]
    run_doc = _read_json(os.path.join(ctx.story_dir, "story_rounds", "run.json"))
    assert run_doc["budgets"]["critic_rounds"] == 2
    assert [r["stage"] for r in log].count("critic") == 2
    t3 = ("panel 2: T3 action overload: Motion: holds 5 actions; a 6-second clip fits at most 2 "
          "and cannot render more than 4; give the extra actions their own panels")
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, story_id="t3", panel=_replies(
        "chained", 3, {2: [{"motion": OVERLOAD}, {"motion": OVERLOAD}]}),
        critic=[{"answer": "x"}] * 4)
    assert rc == 0
    assert ("Warning: unresolved after 1 critic round(s): %s\n" % t3) in capsys.readouterr().out
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, story_id="t1",
                            plan=_speaking_plan("chained", 3, 2), panel=_replies(
                                "chained", 3, {2: [{"dialogue": OVER_CAP}, {"dialogue": OVER_CAP}]}),
                            critic=[{"answer": "x"}] * 4)
    assert rc == 2
    err = capsys.readouterr().err
    assert err.startswith("Error: story.md has 1 hard violation(s) after the critic rounds")
    assert "split it across alternating close-up panels (the speaker, then the listener, then the " \
           "speaker again)" in err
    t1 = ("panel 2: T1 spoken timing: Dialogue: is 15 words in 1 sentences; a 6-second clip fits "
          "at most 14 words in 1 sentences" + SPLIT)
    a = {"hard": [t1], "advisory": [], "scores": None}
    t2s = [T2_MESSAGE.replace("panel 2:", "panel %d:" % k) for k in (1, 2, 3)]
    b = {"hard": t2s, "advisory": [], "scores": None}
    assert se.best_round([a, b]) == 1 and se.better([a, b], 1, 0)
    assert se.final_outcome([a, b]) == (1, [], t2s)
    assert se.final_outcome([a]) == (0, [t1], [])


def test_dlg24_code_only_round_merge(ws):
    ctx = seu.make_ctx(se, ws, mode="shots", panels=3)
    raw = seu.plan_json("shots", 3)
    raw["beats"][1]["speaker"] = "c1"
    plan, _shape = se.normalize_plan(ctx, raw)
    old = {"title": "Old", "image": "The courier stands at the gate.",
           "motion": "The courier turns, then waves.", "dialogue": OVER_CAP,
           "narration": "It rained."}
    new = {"title": "New", "image": "A different picture.", "motion": "The courier waves.",
           "dialogue": "I carry a letter.", "narration": "It poured."}
    assert se.merge_repair(ctx, plan, 2, old, new, {"T2"}) == dict(old, motion="The courier waves.")
    assert se.merge_repair(ctx, plan, 2, old, new, {"T1"}) == dict(old, dialogue="I carry a letter.")
    assert se.merge_repair(ctx, plan, 2, old, new, {"N11"}) == dict(old, narration="It poured.")
    assert se.merge_repair(ctx, plan, 2, old, dict(new, dialogue=OVER_CAP + " Again."),
                           {"T1"}) == old
    wide = dict(old, motion="The courier turns. The courier waves, then bows.")
    rewrite = dict(new, motion="The courier kneels. The courier bows. The courier rises.")
    assert se.merge_repair(ctx, plan, 2, wide, rewrite, {"T2"}) == wide
    assert se.merge_repair(ctx, plan, 2, old, new, {"N7"}) == old


def test_dlg26_judge_gate_is_report_only(tmp_path, monkeypatch, capsys):
    ws = seu.make_ws(tmp_path, fake_judge=True)
    reply = seu.critic_json((4, 8, 8), "revise", [
        {"target": "panel", "index": 2, "field": "motion", "reason": "r",
         "replacement": "The courier waves."}])
    monkeypatch.setenv("FAKE_JUDGE_REPLY", json.dumps(reply))
    monkeypatch.setenv("FAKE_JUDGE_LOG", os.path.join(str(tmp_path), "judge_log.jsonl"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-key")
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, judge=True)
    assert rc == 0
    rounds = os.path.join(ctx.story_dir, "story_rounds")
    saved = os.path.join(rounds, "round_0", "judgment.patches.json")
    assert _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["judge"] == {
        "status": "ok", "detail": "min score 4",
        "scores": {"continuity": 4, "story": 8, "renderability": 8}, "min_score": 4,
        "applied": False}
    assert sorted(os.listdir(rounds)) == ["round_0", "run.json"]
    with open(os.path.join(rounds, "round_0", "story.md"), encoding="utf-8") as f:
        round_0 = f.read()
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        assert f.read() == round_0
    assert ("Warning: judge-story minimum score 4 is below 7; its patches are saved in %s and were "
            "not applied (only spoken timing and the amount of action are repaired automatically)\n"
            % saved) in capsys.readouterr().out
    assert _read_json(saved)["patches"] == reply["patches"]
```
**1.2.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
            se.CRITIC_CALLS_PER_ROUND, se.MAX_PATCHES) == (2, 2, 3, 2, 8)
```

with:

```python
            se.CRITIC_CALLS_PER_ROUND, se.MAX_PATCHES) == (2, 2, 2, 2, 8)
```

**1.3.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
SHOUT2 = "The courier shouts across the quay and pedals on toward the far end of the wet road."
SHOUT1 = SHOUT2[:-1] + " past the moored boats."
```

with:

```python
BUSY = ("The courier stops at the crates, then turns, then pedals on toward the far end of the wet "
        "road.")
CALM = "The courier stops at the crates and pedals on toward the far end of the wet road."
OVER_CAP = "I carry a sealed letter from the harbour master for the abbot of this temple."
```

**1.4.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
def _shouting(mode, k, text):
    return seu.answer(dict(seu.panel_json(mode, k), motion=text))
```

with:

```python
def _busy(mode, k, text=BUSY):
    """A panel reply whose Motion: holds three action units: T2, hard but never blocking
    (dialogue spec 6.2, 9.2)."""
    return seu.answer(dict(seu.panel_json(mode, k), motion=text))


def _speaker_plan(mode, n, *ks):
    """A plan reply in which the courier (c1) speaks in each beat of ks."""
    raw = seu.plan_json(mode, n)
    for k in ks:
        raw["beats"][k - 1]["speaker"] = "c1"
    return seu.answer(raw)


def _over_cap(mode, k):
    """A speaking panel's reply whose spoken line is over the cap: T1, blocking."""
    return seu.answer(dict(seu.panel_json(mode, k), dialogue=OVER_CAP))


def _t1(k):
    return ("panel %d: T1 spoken timing: Dialogue: is 15 words in 1 sentences; a 6-second clip "
            "fits at most 14 words in 1 sentences, and a line has at most 3 sentences; shorten "
            "the line, or split it across alternating close-up panels (the speaker, then the "
            "listener, then the speaker again)" % k)


def _t2(k):
    return ("panel %d: T2 action amount: Motion: holds 3 actions; a 6-second clip fits at most 2, "
            "so cut the extra actions and keep every other sentence word for word" % k)
```

**1.5.** Edit `tests/test_story_engine.py`: replace the whole of `test_rst26b_critic_retry_and_code_only_round`, this text, which occurs exactly once:

```python
def test_rst26b_critic_retry_and_code_only_round(ws, tmp_path, monkeypatch, capsys):
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, panel=_panel_script(
        "chained", 3, p2=[_shouting("chained", 2, SHOUT2), seu.answer(seu.panel_json("chained", 2))]),
        critic=[{"answer": "garbage"}, {"answer": "{}"}, {"answer": "still garbage"},
                seu.answer(seu.critic_json())])
    assert rc == 0
    out = capsys.readouterr().out
    assert "critic round 1: no valid reply after 2 call(s); code-only round\n" in out
    assert "critic round 2 (local): continuity=8 story=8 renderability=8 verdict=ok; 0 patch(es): " \
           "0 applied, 0 rejected\nstop: passed; best round 1 (0 hard)\n" in out
    assert [(r["stage"], r["panel"]) for r in log] == [
        ("plan", None), ("panel", 1), ("panel", 2), ("panel", 3), ("critic", None),
        ("critic", None), ("panel", 2), ("critic", None), ("critic", None)]
    assert log[5]["argv"][-1].endswith(se.CRITIC_RETRY_SUFFIX)
    assert "panel 2: N7 dialogue and text: Motion: says 'shouts'" in log[6]["argv"][-1]
    critic1 = _read_json(os.path.join(_rounds(ctx, 1), "critic.json"))
    assert critic1 == {"route": "local", "calls": 2, "reply": None, "applied": [], "rejected": []}
```

with:

```python
def test_rst26b_critic_retry_and_code_only_round(ws, tmp_path, monkeypatch, capsys):
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, panel=_panel_script(
        "chained", 3, p2=[_busy("chained", 2), seu.answer(seu.panel_json("chained", 2))]),
        critic=[{"answer": "garbage"}, {"answer": "{}"}])
    assert rc == 0
    out = capsys.readouterr().out
    assert "critic round 1: no valid reply after 2 call(s); code-only round\n" in out
    assert "round 1: 0 hard, 0 advisory\nstop: passed; best round 1 (0 hard)\n" in out
    assert [(r["stage"], r["panel"]) for r in log] == [
        ("plan", None), ("panel", 1), ("panel", 2), ("panel", 3), ("critic", None),
        ("critic", None), ("panel", 2)]
    assert log[5]["argv"][-1].endswith(se.CRITIC_RETRY_SUFFIX)
    assert "- " + _t2(2) + "\n" in log[6]["argv"][-1]
    critic1 = _read_json(os.path.join(_rounds(ctx, 1), "critic.json"))
    assert critic1 == {"route": "local", "calls": 2, "reply": None, "applied": [], "rejected": []}
```

**1.6.** Edit `tests/test_story_engine.py`: replace the whole of `test_rst33_stop_passed`, this text, which occurs exactly once:

```python
def test_rst33_stop_passed(ws, tmp_path, monkeypatch, capsys):
    rc, advisories, ctx, log = _run(ws, tmp_path, monkeypatch,
                                    critic=[seu.answer(seu.critic_json((7, 7, 8)))])
    assert (rc, advisories) == (0, [])
    assert capsys.readouterr().out == (
        "plan: call 1 of 2\npanel 1/3: call 1\npanel 2/3: call 1\npanel 3/3: call 1\n"
        "round 0: 0 hard, 0 advisory\n"
        "critic round 1 (local): continuity=7 story=7 renderability=8 verdict=ok; 0 patch(es): "
        "0 applied, 0 rejected\nstop: passed; best round 0 (0 hard)\n")
    assert [r["stage"] for r in log].count("critic") == 1
    assert [r["env_preflight"] for r in log] == [None, "1", "1", "1", "1"]
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert (checks["stop_reason"], checks["best_round"], checks["round"]) == ("passed", 0, 0)
    assert checks["scores"] == {"continuity": 7, "story": 7, "renderability": 8}
```

with:

```python
def test_rst33_stop_passed(ws, tmp_path, monkeypatch, capsys):
    rc, advisories, ctx, log = _run(ws, tmp_path, monkeypatch)
    assert (rc, advisories) == (0, [])
    assert capsys.readouterr().out == (
        "plan: call 1 of 2\npanel 1/3: call 1\npanel 2/3: call 1\npanel 3/3: call 1\n"
        "round 0: 0 hard, 0 advisory\nstop: passed; best round 0 (0 hard)\n")
    assert [r["stage"] for r in log].count("critic") == 0
    assert [r["env_preflight"] for r in log] == [None, "1", "1", "1"]
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert (checks["stop_reason"], checks["best_round"], checks["round"]) == ("passed", 0, 0)
    assert checks["scores"] is None and checks["unresolved"] == []
```

**1.7.** Edit `tests/test_story_engine.py`: replace the whole of `test_rst34_stop_plateau`, this text, which occurs exactly once:

```python
def test_rst34_stop_plateau(ws, tmp_path, monkeypatch, capsys):
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, critic=[
        seu.answer(seu.critic_json((6, 6, 6), "revise", [_narration_patch(2, "The streets ran with water.")])),
        seu.answer(seu.critic_json((5, 5, 5), "revise", [_narration_patch(3, "Never applied.")]))])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.endswith("critic round 2 (local): continuity=5 story=5 renderability=5 "
                        "verdict=revise; 1 patch(es): 0 applied, 0 rejected\n"
                        "stop: plateau; best round 0 (0 hard)\n")
    assert _read_json(os.path.join(_rounds(ctx, 2), "critic.json"))["applied"] == []
    assert not os.path.exists(os.path.join(_rounds(ctx, 2), "plan.json"))
    with open(os.path.join(ctx.story_dir, "story.md")) as f:
        story = f.read()
    with open(os.path.join(_rounds(ctx, 0), "story.md")) as f:
        assert f.read() == story
```

with:

```python
def test_rst34_stop_plateau(ws, tmp_path, monkeypatch, capsys):
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, panel=_panel_script(
        "chained", 3, p2=[_busy("chained", 2)]), critic=[
        seu.answer(seu.critic_json((6, 6, 6), "revise")),
        seu.answer(seu.critic_json((5, 5, 5), "revise", [_motion_patch(2, CALM)]))])
    assert rc == 0
    out = capsys.readouterr().out
    assert ("critic round 2 (local): continuity=5 story=5 renderability=5 verdict=revise; 1 "
            "patch(es): 0 applied, 0 rejected\nstop: plateau; best round 0 (1 hard)\n") in out
    assert out.endswith("Warning: unresolved after 1 critic round(s): " + _t2(2) + "\n")
    assert _read_json(os.path.join(_rounds(ctx, 2), "critic.json"))["applied"] == []
    assert not os.path.exists(os.path.join(_rounds(ctx, 2), "plan.json"))
    with open(os.path.join(ctx.story_dir, "story.md")) as f:
        story = f.read()
    with open(os.path.join(_rounds(ctx, 0), "story.md")) as f:
        assert f.read() == story
```

**1.8.** Edit `tests/test_story_engine.py`: replace the whole of `test_rst35_stop_max_rounds`, this text, which occurs exactly once:

```python
def test_rst35_stop_max_rounds(ws, tmp_path, monkeypatch, capsys):
    clean = dict((k, seu.panel_json("chained", k)["motion"]) for k in (1, 2, 3))
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, panel=_panel_script(
        "chained", 3, p1=[_shouting("chained", 1, SHOUT1)], p2=[_shouting("chained", 2, SHOUT2)],
        p3=[_shouting("chained", 3, SHOUT2.replace("quay", "lane"))]),
        critic=[seu.answer(seu.critic_json((6, 6, 6), "revise", [_motion_patch(2, clean[2])])),
                seu.answer(seu.critic_json((6, 6, 6), "revise", [_motion_patch(3, clean[3])])),
                seu.answer(seu.critic_json((6, 6, 6), "revise", [_motion_patch(1, clean[1])]))])
    assert rc == 0
    out = capsys.readouterr().out
    hard_counts = [int(line.split()[2]) for line in out.splitlines() if line.startswith("round ")]
    assert hard_counts == [3, 2, 1, 0]
    assert out.endswith("stop: max_rounds; best round 3 (0 hard)\n")
    assert sorted(os.listdir(_rounds(ctx))) == ["round_0", "round_1", "round_2", "round_3",
                                                "run.json"]
```

with:

```python
def test_rst35_stop_max_rounds(ws, tmp_path, monkeypatch, capsys):
    clean = dict((k, seu.panel_json("chained", k)["motion"]) for k in (1, 2, 3))
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, panel=_panel_script(
        "chained", 3, p1=[_busy("chained", 1)], p2=[_busy("chained", 2)],
        p3=[_busy("chained", 3)]),
        critic=[seu.answer(seu.critic_json((6, 6, 6), "revise", [_motion_patch(2, clean[2])])),
                seu.answer(seu.critic_json((6, 6, 6), "revise", [_motion_patch(3, clean[3])]))])
    assert rc == 0
    out = capsys.readouterr().out
    hard_counts = [int(line.split()[2]) for line in out.splitlines() if line.startswith("round ")]
    assert hard_counts == [3, 2, 1]
    assert "stop: max_rounds; best round 2 (1 hard)\n" in out
    assert out.endswith("Warning: unresolved after 2 critic round(s): " + _t2(1) + "\n")
    assert sorted(os.listdir(_rounds(ctx))) == ["round_0", "round_1", "round_2", "run.json"]
```

**1.9.** Edit `tests/test_story_engine.py`: replace the whole of `test_rst36b_a_state_that_introduces_n15_loses_a_tie`, this text, which occurs exactly once:

```python
def test_rst36b_a_state_that_introduces_n15_loses_a_tie():
    n7 = "panel 2: N7 dialogue and text: Motion: says 'yells'"
    n15 = ("panel 2: N15 undeclared character: Motion: names library character ronin by its "
           "name 'ronin'; library characters appear only when declared with --character ronin")
    s0 = {"hard": [n7], "scores": {"continuity": 7, "story": 7, "renderability": 7}}
    s1 = {"hard": [n15], "scores": {"continuity": 9, "story": 9, "renderability": 9}}
    assert se.best_round([s0, s1]) == 0
    s1["hard"] = ["panel 3: N1 word count: Motion: is 4 words; it must be 15-35"]
    assert se.best_round([s0, s1]) == 1
    s0["hard"], s1["hard"] = [n15], [n15]
    assert se.best_round([s0, s1]) == 1
```

with:

```python
def test_rst36b_a_state_that_introduces_n15_loses_a_tie():
    n7 = "panel 2: N7 dialogue and text: Motion: says 'yells'"
    n15 = ("panel 2: N15 undeclared character: Motion: names library character ronin by its "
           "name 'ronin'; library characters appear only when declared with --character ronin")
    s0 = {"hard": [_t2(2)], "advisory": [n7],
          "scores": {"continuity": 7, "story": 7, "renderability": 7}}
    s1 = {"hard": [_t2(3)], "advisory": [n15],
          "scores": {"continuity": 9, "story": 9, "renderability": 9}}
    assert se.best_round([s0, s1]) == 0
    s1["advisory"] = ["panel 3: N1 word count: Motion: is 4 words; it must be 15-35"]
    assert se.best_round([s0, s1]) == 1
    s0["advisory"], s1["advisory"] = [n15], [n15]
    assert se.best_round([s0, s1]) == 1
```

**1.10.** Edit `tests/test_story_engine.py`: replace the whole of `test_rst37_budgets_and_the_wall_clock`, this text, which occurs exactly once:

```python
def test_rst37_budgets_and_the_wall_clock(ws, tmp_path, monkeypatch, capsys):
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, plan=[
        {"answer": "no"}, seu.answer(seu.plan_json("chained", 3))], panel=_panel_script(
        "chained", 3, p1=[{"answer": "no"}, seu.answer(seu.panel_json("chained", 1))],
        p2=[_shouting("chained", 2, SHOUT2), seu.answer(seu.panel_json("chained", 2))],
        p3=[_shouting("chained", 3, SHOUT2), _shouting("chained", 3, SHOUT2)]),
        critic=[{"answer": "x"}] * 6)
    assert rc == 2
    calls = _read_json(os.path.join(_rounds(ctx), "run.json"))["calls"]
    stages = [(c["stage"], c["panel"]) for c in calls]
    assert stages.count(("plan", None)) == 2
    assert all(stages.count(("panel", k)) <= 2 for k in (1, 2, 3))
    assert [c["round"] for c in calls if c["stage"] == "critic"] == [1, 1, 2, 2, 3, 3]
    assert "stop: plateau; best round 2 (1 hard)" in capsys.readouterr().out
    run_doc = _read_json(os.path.join(_rounds(ctx), "run.json"))
    assert run_doc["budgets"] == {"plan_calls": 2, "panel_calls": 2, "critic_rounds": 3,
                                  "critic_calls_per_round": 2, "max_patches": 8,
                                  "wall_clock_s": 2400}
    assert (run_doc["exit"], run_doc["stop_reason"], run_doc["best_round"]) == (2, "plateau", 2)

    clock = [0.0]
    monkeypatch.setattr(se, "_now", lambda: clock[0])
    real_agent = se.run_agent

    def slow_agent(*args, **kwargs):
        result = real_agent(*args, **kwargs)
        clock[0] = 10.0 ** 6
        return result

    monkeypatch.setattr(se, "run_agent", slow_agent)
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, story_id="s2")
    assert rc == 1 and [r["stage"] for r in log] == ["plan"]
    assert capsys.readouterr().err == (
        "Error: story generation exceeded the wall-clock cap of 2400s before every panel was "
        "written; partial work is kept in %s\n" % _rounds(ctx, 0))
    assert not os.path.exists(os.path.join(ctx.story_dir, "story.md"))

    clock[0] = 0.0
    monkeypatch.setattr(se, "run_agent", real_agent)
    real_critic = se.run_critic

    def slow_critic(*args, **kwargs):
        result = real_critic(*args, **kwargs)
        clock[0] = 10.0 ** 6
        return result

    monkeypatch.setattr(se, "run_critic", slow_critic)
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, story_id="s3", critic=[
        seu.answer(seu.critic_json((6, 6, 6), "revise", [_narration_patch(2, "It rained on.")]))])
    assert rc == 0
    assert capsys.readouterr().out.endswith("stop: time_cap; best round 1 (0 hard)\n")
    for name in ("plan.json", "story.md", "story_checks.json"):
        assert os.path.exists(os.path.join(ctx.story_dir, name))
```

with:

```python
def test_rst37_budgets_and_the_wall_clock(ws, tmp_path, monkeypatch, capsys):
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, plan=[
        {"answer": "no"}, _speaker_plan("chained", 3, 3)], panel=_panel_script(
        "chained", 3, p1=[{"answer": "no"}, seu.answer(seu.panel_json("chained", 1))],
        p2=[_busy("chained", 2), seu.answer(seu.panel_json("chained", 2))],
        p3=[_over_cap("chained", 3), _over_cap("chained", 3)]),
        critic=[{"answer": "x"}] * 4)
    assert rc == 2
    calls = _read_json(os.path.join(_rounds(ctx), "run.json"))["calls"]
    stages = [(c["stage"], c["panel"]) for c in calls]
    assert stages.count(("plan", None)) == 2
    assert all(stages.count(("panel", k)) <= 2 for k in (1, 2, 3))
    assert [c["round"] for c in calls if c["stage"] == "critic"] == [1, 1, 2, 2]
    assert "stop: max_rounds; best round 2 (1 hard)" in capsys.readouterr().out
    run_doc = _read_json(os.path.join(_rounds(ctx), "run.json"))
    assert run_doc["budgets"] == {"plan_calls": 2, "panel_calls": 2, "critic_rounds": 2,
                                  "critic_calls_per_round": 2, "max_patches": 8,
                                  "wall_clock_s": 2400}
    assert (run_doc["exit"], run_doc["stop_reason"], run_doc["best_round"]) == (2, "max_rounds", 2)

    clock = [0.0]
    monkeypatch.setattr(se, "_now", lambda: clock[0])
    real_agent = se.run_agent

    def slow_agent(*args, **kwargs):
        result = real_agent(*args, **kwargs)
        clock[0] = 10.0 ** 6
        return result

    monkeypatch.setattr(se, "run_agent", slow_agent)
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, story_id="s2")
    assert rc == 1 and [r["stage"] for r in log] == ["plan"]
    assert capsys.readouterr().err == (
        "Error: story generation exceeded the wall-clock cap of 2400s before every panel was "
        "written; partial work is kept in %s\n" % _rounds(ctx, 0))
    assert not os.path.exists(os.path.join(ctx.story_dir, "story.md"))

    clock[0] = 0.0
    monkeypatch.setattr(se, "run_agent", real_agent)
    real_critic = se.run_critic

    def slow_critic(*args, **kwargs):
        result = real_critic(*args, **kwargs)
        clock[0] = 10.0 ** 6
        return result

    monkeypatch.setattr(se, "run_critic", slow_critic)
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, story_id="s3", panel=_panel_script(
        "chained", 3, p2=[_busy("chained", 2)]), critic=[
        seu.answer(seu.critic_json((6, 6, 6), "revise"))])
    assert rc == 0
    assert "stop: time_cap; best round 1 (1 hard)\n" in capsys.readouterr().out
    for name in ("plan.json", "story.md", "story_checks.json"):
        assert os.path.exists(os.path.join(ctx.story_dir, name))
```

**1.11.** Edit `tests/test_story_engine.py`: replace the whole of `test_rst39_outputs_and_layout`, this text, which occurs exactly once:

```python
def test_rst39_outputs_and_layout(ws, tmp_path, monkeypatch):
    os.makedirs(os.path.join(ws, "generated", "stories", "s1", "story_rounds"))
    with open(os.path.join(ws, "generated", "stories", "s1", "story_rounds", "old.txt"), "w") as f:
        f.write("kept")
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, critic=[
        seu.answer(seu.critic_json((6, 6, 6), "revise", [_narration_patch(2, "It rained on.")])),
        seu.answer(seu.critic_json((8, 8, 8)))])
    assert rc == 0
    moved = [n for n in os.listdir(ctx.story_dir) if n.startswith("story_rounds-")]
    assert len(moved) == 1 and re.fullmatch(r"story_rounds-\d{8}T\d{6}Z-\d+", moved[0])
    with open(os.path.join(ctx.story_dir, moved[0], "old.txt")) as f:
        assert f.read() == "kept"
    plan = _read_json(os.path.join(ctx.story_dir, "plan.json"))
    assert list(plan) == ["schema", "story_id", "mode", "panels", "seconds", "narrative", "goal",
                          "seed_image", "video_model", "auto_lora", "title", "logline", "cast",
                          "locations", "props", "beats", "loras", "speech_notes"]
    assert plan["schema"] == "ltx-movie.plan.v1" and plan["panels"] == 3
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert list(checks) == ["schema", "story_id", "mode", "panels", "checked_at", "source",
                            "round", "hard", "advisory", "scores", "verdict", "stop_reason",
                            "rounds", "best_round", "judge"]
    assert checks["source"] == "robust" and checks["best_round"] == 1 and checks["judge"] is None
    assert checks["rounds"] == [
        {"round": 0, "hard": 0, "advisory": 0, "scores": {"continuity": 6, "story": 6,
                                                          "renderability": 6},
         "verdict": "revise"},
        {"round": 1, "hard": 0, "advisory": 0, "scores": {"continuity": 8, "story": 8,
                                                          "renderability": 8},
         "verdict": "ok"}]
    assert sorted(os.listdir(_rounds(ctx, 0))) == [
        "panel_01_prompt_1.txt", "panel_01_reply_1.txt", "panel_02_prompt_1.txt",
        "panel_02_reply_1.txt", "panel_03_prompt_1.txt", "panel_03_reply_1.txt", "parts.json",
        "plan.json", "plan_prompt.txt", "plan_reply_1.txt", "story.md", "story_checks.json"]
    assert sorted(os.listdir(_rounds(ctx, 1))) == [
        "critic.json", "critic_prompt_1.txt", "critic_reply_1.txt", "parts.json", "plan.json",
        "story.md", "story_checks.json"]
    assert sorted(os.listdir(_rounds(ctx, 2))) == ["critic.json", "critic_prompt_1.txt",
                                                   "critic_reply_1.txt"]
    round1 = _read_json(os.path.join(_rounds(ctx, 1), "story_checks.json"))
    assert (round1["round"], round1["stop_reason"], round1["best_round"], round1["rounds"]) == (
        1, None, None, [])
    run_doc = _read_json(os.path.join(_rounds(ctx), "run.json"))
    assert [c["stage"] for c in run_doc["calls"]] == ["plan", "panel", "panel", "panel",
                                                      "critic", "critic"]
    assert run_doc["calls"][4]["route"] == "local" and run_doc["exit"] == 0
    with open(os.path.join(ctx.story_dir, "story.md")) as f:
        assert "Narration: It rained on.\n" in f.read()
```

with:

```python
def test_rst39_outputs_and_layout(ws, tmp_path, monkeypatch):
    os.makedirs(os.path.join(ws, "generated", "stories", "s1", "story_rounds"))
    with open(os.path.join(ws, "generated", "stories", "s1", "story_rounds", "old.txt"), "w") as f:
        f.write("kept")
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, panel=_panel_script(
        "chained", 3, p2=[_busy("chained", 2)]), critic=[
        seu.answer(seu.critic_json((6, 6, 6), "revise", [_motion_patch(2, CALM)]))])
    assert rc == 0
    moved = [n for n in os.listdir(ctx.story_dir) if n.startswith("story_rounds-")]
    assert len(moved) == 1 and re.fullmatch(r"story_rounds-\d{8}T\d{6}Z-\d+", moved[0])
    with open(os.path.join(ctx.story_dir, moved[0], "old.txt")) as f:
        assert f.read() == "kept"
    plan = _read_json(os.path.join(ctx.story_dir, "plan.json"))
    assert list(plan) == ["schema", "story_id", "mode", "panels", "seconds", "narrative", "goal",
                          "seed_image", "video_model", "auto_lora", "title", "logline", "cast",
                          "locations", "props", "beats", "loras", "speech_notes"]
    assert plan["schema"] == "ltx-movie.plan.v1" and plan["panels"] == 3
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert list(checks) == ["schema", "story_id", "mode", "panels", "checked_at", "source",
                            "round", "hard", "unresolved", "advisory", "scores", "verdict",
                            "stop_reason", "rounds", "best_round", "judge"]
    assert checks["source"] == "robust" and checks["best_round"] == 1 and checks["judge"] is None
    assert checks["rounds"] == [
        {"round": 0, "hard": 1, "advisory": 1, "scores": {"continuity": 6, "story": 6,
                                                          "renderability": 6},
         "verdict": "revise"},
        {"round": 1, "hard": 0, "advisory": 0, "scores": None, "verdict": None}]
    assert sorted(os.listdir(_rounds(ctx, 0))) == [
        "panel_01_prompt_1.txt", "panel_01_reply_1.txt", "panel_02_prompt_1.txt",
        "panel_02_reply_1.txt", "panel_03_prompt_1.txt", "panel_03_reply_1.txt", "parts.json",
        "plan.json", "plan_prompt.txt", "plan_reply_1.txt", "story.md", "story_checks.json"]
    assert sorted(os.listdir(_rounds(ctx, 1))) == [
        "critic.json", "critic_prompt_1.txt", "critic_reply_1.txt", "parts.json", "plan.json",
        "story.md", "story_checks.json"]
    assert not os.path.exists(_rounds(ctx, 2))
    round1 = _read_json(os.path.join(_rounds(ctx, 1), "story_checks.json"))
    assert (round1["round"], round1["stop_reason"], round1["best_round"], round1["rounds"],
            round1["unresolved"]) == (1, None, None, [], [])
    run_doc = _read_json(os.path.join(_rounds(ctx), "run.json"))
    assert [c["stage"] for c in run_doc["calls"]] == ["plan", "panel", "panel", "panel", "critic"]
    assert run_doc["calls"][4]["route"] == "local" and run_doc["exit"] == 0
    with open(os.path.join(ctx.story_dir, "story.md")) as f:
        assert "Motion: " + CALM + "\n" in f.read()
```

**1.12.** Edit `tests/test_story_engine.py`: replace the whole of `test_rst43_exit_2_message`, this text, which occurs exactly once:

```python
def test_rst43_exit_2_message(ws, tmp_path, monkeypatch, capsys):
    shout3 = SHOUT2.replace("quay", "lane")
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, panel=_panel_script(
        "chained", 3, p2=[_shouting("chained", 2, SHOUT2), _shouting("chained", 2, SHOUT2)],
        p3=[_shouting("chained", 3, shout3), _shouting("chained", 3, shout3)]),
        critic=[{"answer": "x"}] * 4)
    assert rc == 2
    assert capsys.readouterr().err == (
        "Error: story.md has 2 hard violation(s) after the critic rounds (best round 1 of 1):\n"
        "  - panel 2: N7 dialogue and text: Motion: says 'shouts'\n"
        "  - panel 3: N7 dialogue and text: Motion: says 'shouts'\n"
        "story.md, plan.json and story_checks.json are saved in %s. Hand-edit story.md to fix "
        "the violations above and rerun: story.md already exists, so Phase 1 re-checks it "
        "instead of regenerating it (pass --force-story to regenerate).\n" % ctx.story_dir)
    for name in ("plan.json", "story.md", "story_checks.json"):
        assert os.path.exists(os.path.join(ctx.story_dir, name))
    assert [h["id"] for h in _read_json(os.path.join(ctx.story_dir,
                                                     "story_checks.json"))["hard"]] == ["N7", "N7"]
```

with:

```python
def test_rst43_exit_2_message(ws, tmp_path, monkeypatch, capsys):
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, plan=[_speaker_plan("chained", 3, 2, 3)],
                            panel=_panel_script("chained", 3,
                                                p2=[_over_cap("chained", 2), _over_cap("chained", 2)],
                                                p3=[_over_cap("chained", 3), _over_cap("chained", 3)]),
                            critic=[{"answer": "x"}] * 4)
    assert rc == 2
    assert capsys.readouterr().err == (
        "Error: story.md has 2 hard violation(s) after the critic rounds (best round 1 of 1):\n"
        "  - %s\n  - %s\n"
        "story.md, plan.json and story_checks.json are saved in %s. Hand-edit story.md to fix "
        "the violations above and rerun: story.md already exists, so Phase 1 re-checks it "
        "instead of regenerating it (pass --force-story to regenerate).\n"
        % (_t1(2), _t1(3), ctx.story_dir))
    for name in ("plan.json", "story.md", "story_checks.json"):
        assert os.path.exists(os.path.join(ctx.story_dir, name))
    assert [h["id"] for h in _read_json(os.path.join(ctx.story_dir,
                                                     "story_checks.json"))["hard"]] == ["T1", "T1"]
```

**1.13.** Edit `tests/test_story_engine.py`: replace the whole of `test_rst58_a_patch_that_names_an_undeclared_character_loses`, this text, which occurs exactly once:

```python
def test_rst58_a_patch_that_names_an_undeclared_character_loses(ws, tmp_path, monkeypatch,
                                                                 story_env):
    seu.ronin(story_env["lib"])
    patch = _motion_patch(2, "The courier waves to the ronin by the crates and pedals on along "
                             "the quay.")
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, critic=[
        seu.answer(seu.critic_json((8, 8, 8), "revise", [patch])),
        seu.answer(seu.critic_json((9, 9, 9)))])
    assert rc == 0
    assert _read_json(os.path.join(_rounds(ctx, 1), "critic.json"))["applied"] == [patch]
    round1 = _read_json(os.path.join(_rounds(ctx, 1), "story_checks.json"))
    assert "N15" in [h["id"] for h in round1["hard"]]
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert (checks["best_round"], checks["stop_reason"]) == (0, "plateau")
```

with:

```python
def test_rst58_a_patch_that_names_an_undeclared_character_loses(ws, tmp_path, monkeypatch,
                                                                 story_env):
    seu.ronin(story_env["lib"])
    patch = _motion_patch(2, "The courier waves to the ronin by the crates, then turns, then "
                             "pedals on along the quay.")
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, panel=_panel_script(
        "chained", 3, p2=[_busy("chained", 2)]), critic=[
        seu.answer(seu.critic_json((8, 8, 8), "revise", [patch])),
        seu.answer(seu.critic_json((9, 9, 9)))])
    assert rc == 0
    assert _read_json(os.path.join(_rounds(ctx, 1), "critic.json"))["applied"] == [patch]
    round1 = _read_json(os.path.join(_rounds(ctx, 1), "story_checks.json"))
    assert "N15" in [v["id"] for v in round1["hard"] + round1["advisory"]]
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert checks["best_round"] == 0
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        assert "ronin" not in f.read()
```

**1.14.** Edit `tests/test_story_engine.py`: replace the whole of `test_rst38_judge_gate`, this text, which occurs exactly once:

```python
def test_rst38_judge_gate(tmp_path, monkeypatch, capsys):
    ws = seu.make_ws(tmp_path, fake_judge=True)
    judge_log = _judge_env(monkeypatch, tmp_path, seu.critic_json((8, 9, 8)))
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, judge=True, goal="quiet suspense",
                            critic=[seu.answer(seu.critic_json((7, 7, 8)))])
    assert rc == 0
    judge = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["judge"]
    assert judge == {"status": "ok", "detail": "min score 8",
                     "scores": {"continuity": 8, "story": 9, "renderability": 8},
                     "min_score": 8, "applied": False}
    argv = seu.agent_log(judge_log)[0]["argv"]
    assert argv == ["--story-md", os.path.join(_rounds(ctx, 0), "story.md"), "--patches",
                    "--goal", "quiet suspense"]
    assert sorted(os.listdir(_rounds(ctx, 1))) == ["critic.json", "critic_prompt_1.txt",
                                                   "critic_reply_1.txt"]

    _judge_env(monkeypatch, tmp_path, seu.critic_json((5, 7, 7), "revise",
                                                      [_narration_patch(2, "The judge's line.")]))
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, judge=True, story_id="s2", critic=[
        seu.answer(seu.critic_json((7, 7, 8))), seu.answer(seu.critic_json((8, 8, 8)))])
    assert rc == 0
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert checks["judge"]["applied"] is True and checks["judge"]["min_score"] == 5
    assert checks["best_round"] == 1
    critic1 = _read_json(os.path.join(_rounds(ctx, 1), "critic.json"))
    assert critic1["route"] is None and critic1["reply"]["scores"]["continuity"] == 5
    assert os.path.exists(os.path.join(_rounds(ctx, 1), "judgment.patches.json"))
    assert os.path.exists(os.path.join(_rounds(ctx, 2), "critic.json"))
    with open(os.path.join(ctx.story_dir, "story.md")) as f:
        assert "Narration: The judge's line.\n" in f.read()

    _judge_env(monkeypatch, tmp_path, {"exit": 1})
    capsys.readouterr()
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, judge=True, story_id="s3",
                            critic=[seu.answer(seu.critic_json((7, 7, 8)))])
    assert rc == 0
    assert "Warning: judge-story failed (exit 1); keeping the critic's best round\n" in (
        capsys.readouterr().out)
    judge = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["judge"]
    assert (judge["status"], judge["detail"], judge["applied"]) == ("error", "exit 1", False)

    judge_log = _judge_env(monkeypatch, tmp_path, seu.critic_json())
    os.remove(judge_log) if os.path.exists(judge_log) else None
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, judge=True, story_id="s4", panel=_panel_script(
        "chained", 3, p2=[_shouting("chained", 2, SHOUT2), _shouting("chained", 2, SHOUT2)]),
        critic=[{"answer": "x"}] * 4)
    assert rc == 2 and not os.path.exists(judge_log)
    judge = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["judge"]
    assert judge == {"status": "skipped", "detail": "best round has hard violations",
                     "scores": None, "min_score": None, "applied": False}
```

with:

```python
def test_rst38_judge_gate(tmp_path, monkeypatch, capsys):
    ws = seu.make_ws(tmp_path, fake_judge=True)
    judge_log = _judge_env(monkeypatch, tmp_path, seu.critic_json((8, 9, 8)))
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, judge=True, goal="quiet suspense")
    assert rc == 0
    judge = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["judge"]
    assert judge == {"status": "ok", "detail": "min score 8",
                     "scores": {"continuity": 8, "story": 9, "renderability": 8},
                     "min_score": 8, "applied": False}
    argv = seu.agent_log(judge_log)[0]["argv"]
    assert argv == ["--story-md", os.path.join(_rounds(ctx, 0), "story.md"), "--patches",
                    "--goal", "quiet suspense"]
    assert not os.path.exists(_rounds(ctx, 1))
    assert [r["stage"] for r in log].count("critic") == 0

    patch = _narration_patch(2, "The judge's line.")
    _judge_env(monkeypatch, tmp_path, seu.critic_json((5, 7, 7), "revise", [patch]))
    capsys.readouterr()
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, judge=True, story_id="s2")
    assert rc == 0
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert checks["judge"] == {"status": "ok", "detail": "min score 5",
                               "scores": {"continuity": 5, "story": 7, "renderability": 7},
                               "min_score": 5, "applied": False}
    assert checks["best_round"] == 0 and len(checks["rounds"]) == 1
    saved = os.path.join(_rounds(ctx, 0), "judgment.patches.json")
    assert _read_json(saved)["patches"] == [patch]
    assert ("Warning: judge-story minimum score 5 is below 7; its patches are saved in %s and were "
            "not applied (only spoken timing and the amount of action are repaired "
            "automatically)\n" % saved) in capsys.readouterr().out
    assert not os.path.exists(_rounds(ctx, 1))
    with open(os.path.join(ctx.story_dir, "story.md")) as f:
        assert "The judge's line." not in f.read()

    _judge_env(monkeypatch, tmp_path, {"exit": 1})
    capsys.readouterr()
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, judge=True, story_id="s3")
    assert rc == 0
    assert "Warning: judge-story failed (exit 1); keeping the critic's best round\n" in (
        capsys.readouterr().out)
    judge = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["judge"]
    assert (judge["status"], judge["detail"], judge["applied"]) == ("error", "exit 1", False)

    judge_log = _judge_env(monkeypatch, tmp_path, seu.critic_json())
    os.remove(judge_log) if os.path.exists(judge_log) else None
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, judge=True, story_id="s4",
                            plan=[_speaker_plan("chained", 3, 2)], panel=_panel_script(
                                "chained", 3, p2=[_over_cap("chained", 2), _over_cap("chained", 2)]),
                            critic=[{"answer": "x"}] * 4)
    assert rc == 2 and not os.path.exists(judge_log)
    judge = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["judge"]
    assert judge == {"status": "skipped", "detail": "best round has hard violations",
                     "scores": None, "min_score": None, "applied": False}
```

**1.15.** Edit `tests/test_story_engine.py`: replace the whole of `test_rst51_e2e_chained`, this text, which occurs exactly once:

```python
def test_rst51_e2e_chained(movie, tmp_path, monkeypatch):
    rc, log = _main_run(tmp_path, monkeypatch,
                        [NARRATIVE, "--story-id", "e1", "--panels", "3", "--story-only",
                         "--no-review", "--force-story"],
                        plan=[seu.answer(seu.plan_json("chained", 3))],
                        panel=_panel_script("chained", 3), critic=[seu.answer(seu.critic_json())])
    assert rc == 0
    story_dir = os.path.join(movie, "generated", "stories", "e1")
    assert ltx_movie._validate_story_md(os.path.join(story_dir, "story.md"), 3) == []
    for name in ("plan.json", "story_checks.json"):
        assert os.path.exists(os.path.join(story_dir, name))
    with open(os.path.join(story_dir, "story_prompt.txt")) as f:
        assert f.read() == ltx_movie.build_story_prompt(NARRATIVE, "e1", 3, False, False,
                                                        seconds="6")
    assert [r["stage"] for r in log] == ["plan", "panel", "panel", "panel", "critic"]
    assert "--skill=analyst" in log[-1]["argv"]
    assert all("--max-rounds" in r["argv"] and r["argv"][r["argv"].index("--max-rounds") + 1] == "1"
               for r in log)
```

with:

```python
def test_rst51_e2e_chained(movie, tmp_path, monkeypatch):
    rc, log = _main_run(tmp_path, monkeypatch,
                        [NARRATIVE, "--story-id", "e1", "--panels", "3", "--story-only",
                         "--no-review", "--force-story"],
                        plan=[seu.answer(seu.plan_json("chained", 3))],
                        panel=_panel_script("chained", 3))
    assert rc == 0
    story_dir = os.path.join(movie, "generated", "stories", "e1")
    assert ltx_movie._validate_story_md(os.path.join(story_dir, "story.md"), 3) == []
    for name in ("plan.json", "story_checks.json"):
        assert os.path.exists(os.path.join(story_dir, name))
    with open(os.path.join(story_dir, "story_prompt.txt")) as f:
        assert f.read() == ltx_movie.build_story_prompt(NARRATIVE, "e1", 3, False, False,
                                                        seconds="6")
    assert [r["stage"] for r in log] == ["plan", "panel", "panel", "panel"]
    assert all("--max-rounds" in r["argv"] and r["argv"][r["argv"].index("--max-rounds") + 1] == "1"
               for r in log)
```

**1.16.** Edit `tests/test_story_engine.py`: replace the whole of `test_rst52_e2e_no_stills_with_a_setting_patch`, this text, which occurs exactly once:

```python
def test_rst52_e2e_no_stills_with_a_setting_patch(movie, tmp_path, monkeypatch):
    setting = ("The setting is a stormy fishing harbour in modern Japan, slick black cobblestones "
               "underfoot, cranes behind, under blue evening light.")
    patch = {"target": "plan", "index": 1, "field": "location.setting", "reason": "r",
             "replacement": setting}
    rc, log = _main_run(tmp_path, monkeypatch,
                        [NARRATIVE, "--story-id", "e2", "--panels", "2", "--no-stills",
                         "--story-only", "--no-review"],
                        plan=[seu.answer(seu.plan_json("no_stills", 2))],
                        panel=_panel_script("no_stills", 2),
                        critic=[seu.answer(seu.critic_json((6, 6, 6), "revise", [patch])),
                                seu.answer(seu.critic_json())])
    assert rc == 0
    story_md = os.path.join(movie, "generated", "stories", "e2", "story.md")
    panels = se._story_manifest(WS)._parse_prompts_md(story_md)[1]
    assert [150 <= len(p["prompt"].split()) <= 220 for p in panels] == [True, True]
    assert all(setting in p["prompt"] for p in panels)
    critic = _read_json(os.path.join(movie, "generated", "stories", "e2", "story_rounds",
                                     "round_1", "critic.json"))
    assert critic["applied"] == [patch]
```

with:

```python
def test_rst52_e2e_no_stills_with_a_setting_patch(movie, tmp_path, monkeypatch):
    # A clean round 0 makes no critic call, and a location.setting patch is never applied
    # (dialogue spec 6.5, 6.6): the run checks the no_stills assembly end to end instead.
    rc, log = _main_run(tmp_path, monkeypatch,
                        [NARRATIVE, "--story-id", "e2", "--panels", "2", "--no-stills",
                         "--story-only", "--no-review"],
                        plan=[seu.answer(seu.plan_json("no_stills", 2))],
                        panel=_panel_script("no_stills", 2))
    assert rc == 0
    story_md = os.path.join(movie, "generated", "stories", "e2", "story.md")
    panels = se._story_manifest(WS)._parse_prompts_md(story_md)[1]
    assert [150 <= len(p["prompt"].split()) <= 220 for p in panels] == [True, True]
    assert all(seu.HARBOUR in p["prompt"] for p in panels)
    assert [r["stage"] for r in log] == ["plan", "panel", "panel"]
```

**1.17.** Edit `tests/test_story_engine.py`: replace the whole of `test_rst54_e2e_hard_fail_then_hand_edit_and_recheck`, this text, which occurs exactly once:

```python
def test_rst54_e2e_hard_fail_then_hand_edit_and_recheck(movie, tmp_path, monkeypatch, capsys):
    argv = [NARRATIVE, "--story-id", "e4", "--panels", "3", "--story-only", "--no-review"]
    rc, log = _main_run(tmp_path, monkeypatch, argv,
                        plan=[seu.answer(seu.plan_json("chained", 3))],
                        panel=_panel_script("chained", 3, p2=[_shouting("chained", 2, SHOUT2),
                                                              _shouting("chained", 2, SHOUT2)]),
                        critic=[{"answer": "x"}] * 4)
    assert rc == 2
    assert "  - panel 2: N7 dialogue and text: Motion: says 'shouts'\n" in capsys.readouterr().err
    story_md = os.path.join(movie, "generated", "stories", "e4", "story.md")
    with open(story_md) as f:
        text = f.read()
    with open(story_md, "w") as f:
        f.write(text.replace("Motion: " + SHOUT2,
                             "Motion: " + seu.panel_json("chained", 2)["motion"] + "."))
    rc, again = _main_run(tmp_path, monkeypatch, argv)
    assert rc == 0 and again == []
    assert "re-checking it instead of regenerating it" in capsys.readouterr().out
    assert _read_json(os.path.join(movie, "generated", "stories", "e4",
                                   "story_checks.json"))["source"] == "recheck"
```

with:

```python
def test_rst54_e2e_hard_fail_then_hand_edit_and_recheck(movie, tmp_path, monkeypatch, capsys):
    argv = [NARRATIVE, "--story-id", "e4", "--panels", "3", "--story-only", "--no-review"]
    rc, log = _main_run(tmp_path, monkeypatch, argv,
                        plan=[_speaker_plan("chained", 3, 2)],
                        panel=_panel_script("chained", 3, p2=[_over_cap("chained", 2),
                                                              _over_cap("chained", 2)]),
                        critic=[{"answer": "x"}] * 4)
    assert rc == 2
    assert "  - " + _t1(2) + "\n" in capsys.readouterr().err
    story_md = os.path.join(movie, "generated", "stories", "e4", "story.md")
    with open(story_md) as f:
        text = f.read()
    with open(story_md, "w") as f:
        f.write(text.replace("Dialogue: the courier: " + OVER_CAP,
                             "Dialogue: the courier: I carry a letter for the abbot."))
    rc, again = _main_run(tmp_path, monkeypatch, argv)
    assert rc == 0 and again == []
    assert "re-checking it instead of regenerating it" in capsys.readouterr().out
    assert _read_json(os.path.join(movie, "generated", "stories", "e4",
                                   "story_checks.json"))["source"] == "recheck"
```

**1.18.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    def state(hard, scores=None):
        return {"hard": ["x"] * hard,
                "scores": dict(zip(se.SCORE_KEYS, scores)) if scores else None}
```

with:

```python
    def state(hard, scores=None):
        return {"hard": ["x"] * hard, "advisory": [],
                "scores": dict(zip(se.SCORE_KEYS, scores)) if scores else None}
```

**1.19.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
                        plan=[seu.answer(raw)], panel=panels,
                        critic=[{"answer": "garbage"}, seu.answer(seu.critic_json())])
```

with:

```python
                        plan=[seu.answer(raw)], panel=panels)
```

**1.20.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    assert [r["stage"] for r in log].count("critic") == 2
```

with:

```python
    assert [r["stage"] for r in log].count("critic") == 0
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k "dlg23 or dlg24 or dlg26" 2>&1 | tail -3
python3 -m pytest -q -p no:cacheprovider tests/test_story_engine.py 2>&1 | tail -3
```

Expected: `3 failed` (`AttributeError: module 'story_engine_for_dialogue' has no attribute 'final_outcome'` / `'merge_repair'`; the judge gate still adds a round). In `tests/test_story_engine.py` the failures include `test_rs4_constants`, `test_rst26b`, `test_rst33`, `test_rst34`, `test_rst35`, `test_rst36b`, `test_rst37`, `test_rst38`, `test_rst39`, `test_rst51`, `test_rst52` and `test_rst53` (a clean round 0 still calls the critic, T2 still blocks, three rounds), besides the known `test_rst62_import_sets`. `test_rst43` and `test_rst54` may already pass: they pin exit-2 output that Step 3 must keep.

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
CRITIC_MAX_ROUNDS = 3
CRITIC_CALLS_PER_ROUND = 2
MAX_PATCHES = 8
MIN_OK_SCORE = 7
JUDGE_MIN_SCORE = 7
```

with:

```python
CRITIC_MAX_ROUNDS = 2
CRITIC_CALLS_PER_ROUND = 2
MAX_PATCHES = 8
JUDGE_MIN_SCORE = 7
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
WRITER_CHECK_IDS = ("N1", "N2", "N3", "N4", "N7", "N8", "N9", "N10", "N11", "S4", "S5", "S7",
                    "S8", "S10", "S11")
```

with:

```python
# Dialogue spec 6.1: T2 and T3 trigger repair but never block; every other hard violation blocks.
NON_BLOCKING_IDS = ("T2", "T3")
# The hard ids a code-only round sends back to the panel writer (PG5).
REPAIR_IDS = ("N11", "T1", "T2", "T3")


def blocking(messages):
    """The hard violations among messages that block the story (dialogue spec 6.1)."""
    return [m for m in messages if parse_violation(m)["id"] not in NON_BLOCKING_IDS]


def unresolved(messages):
    """The hard violations among messages that never block: T2 and T3 (dialogue spec 6.1)."""
    return [m for m in messages if parse_violation(m)["id"] in NON_BLOCKING_IDS]


def n_blocking(state):
    return len(blocking(state["hard"]))


def guard_problem(ctx, plan, old, new):
    """Why replacing the writer action text old with new (already cleaned) is rejected, or None
    (dialogue spec PG3): only one contiguous run of at most max(1, units - max_actions) sentences
    of old may change, every other sentence is kept word for word, and a camera sentence of that
    run must survive into the new run."""
    lib = _character_lib(ctx.ws)
    phrases = cast_phrases(ctx, plan)
    a, b = _sentences(old), _sentences(new)
    p = 0
    while p < min(len(a), len(b)) and a[p] == b[p]:
        p += 1
    s = 0
    while s < min(len(a), len(b)) - p and a[len(a) - 1 - s] == b[len(b) - 1 - s]:
        s += 1
    old_span, new_span = a[p:len(a) - s], b[p:len(b) - s]
    _actions, units, most = action_units(ctx, lib, old, phrases)
    limit = max(1, units - most)
    if len(old_span) > limit:
        return ("the patch changes %d sentences; it may change at most %d contiguous sentence(s) "
                "and must keep every other sentence word for word" % (len(old_span), limit))
    for sentence in old_span:
        if lib._is_camera_sentence(sentence, phrases) and sentence not in new_span:
            return "the patch drops the camera direction %s" % _q(sentence)
    return None


def line_problem(ctx, lib, line):
    """The PG4 reason a new spoken line does not fit this clip, else None."""
    n = len(lib.split_fragments(line))
    words = len(line.split())
    cap = lib.dialogue_word_cap(engine_seconds(ctx), n)
    if words > cap or n > lib.DIALOGUE_MAX_FRAGMENTS:
        return ("the new line is %d words in %d sentences; at most %d words in %d sentences fit "
                "this clip" % (words, n, cap, n))
    return None


def merge_repair(ctx, plan, k, old, new, ids):
    """Panel k's writer parts after a code-only round (dialogue spec PG5): new's motion or prompt
    when ids has T2 or T3 and the PG3 guard accepts it, new's dialogue when ids has T1 and the
    line fits, new's narration when ids has N11; every other part keeps old's text."""
    merged = dict(old)
    action = "prompt" if ctx.mode == "no_stills" else "motion"
    if (ids & {"T2", "T3"} and new.get(action)
            and guard_problem(ctx, plan, old.get(action, ""), new[action]) is None):
        merged[action] = new[action]
    if ("T1" in ids and new.get("dialogue")
            and line_problem(ctx, _character_lib(ctx.ws), _sentence(new["dialogue"])) is None):
        merged["dialogue"] = new["dialogue"]
    if "N11" in ids and "narration" in new:
        merged["narration"] = new["narration"]
    return merged
```

**3.3.** Edit `story_engine.py`: replace the whole of `_key`, this text, which occurs exactly once:

```python
def _key(states, i):
    scores = _scores_of(states, i)
    low = min(scores.values()) if scores else 0
    total = sum(scores.values()) if scores else 0
    return (len(states[i]["hard"]), -low, -total)
```

with:

```python
def _key(states, i):
    scores = _scores_of(states, i)
    low = min(scores.values()) if scores else 0
    total = sum(scores.values()) if scores else 0
    return (n_blocking(states[i]), len(states[i]["hard"]), -low, -total)
```

**3.4.** Edit `story_engine.py`: replace `_new_rs37` and `best_round`, this text, which occurs exactly once:

```python
def _new_rs37(states, i):
    """1 when states[i] has a P13 or N15 hard violation that round 0 does not have (a patch or a
    regeneration introduced an undeclared library character), else 0."""
    base = set(states[0]["hard"])
    return int(any(parse_violation(m)["id"] in ("P13", "N15") and m not in base
                   for m in states[i]["hard"]))


def best_round(states):
    """The index of the state with the smallest (hard, new P13/N15, -min, -total, -round)
    (RS22; on an equal hard count a state that introduced an undeclared library character
    loses)."""
    return min(range(len(states)),
               key=lambda i: (len(states[i]["hard"]), _new_rs37(states, i))
               + _key(states, i)[1:] + (-i,))
```

with:

```python
def _new_rs37(states, i):
    """1 when states[i] has a P13 or N15 violation (hard or advisory) that round 0 does not have
    (a patch or a rewrite introduced an undeclared library character), else 0."""
    base = set(states[0]["hard"] + states[0]["advisory"])
    return int(any(parse_violation(m)["id"] in ("P13", "N15") and m not in base
                   for m in states[i]["hard"] + states[i]["advisory"]))


def best_round(states):
    """The index of the state with the smallest (blocking, hard, new P13/N15, -min, -total,
    -round) (RS22; dialogue spec 6.4: blocking first, so a T1 state never beats T2-only ones)."""
    return min(range(len(states)),
               key=lambda i: (n_blocking(states[i]), len(states[i]["hard"]), _new_rs37(states, i))
               + _key(states, i)[2:] + (-i,))


def final_outcome(states):
    """(best round, its blocking violations, its unresolved T2/T3 violations) (dialogue spec 6.5)."""
    best = best_round(states)
    return best, blocking(states[best]["hard"]), unresolved(states[best]["hard"])
```

**3.5.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
            "hard": [parse_violation(m) for m in state["hard"]],
            "advisory": [parse_violation(m) for m in state["advisory"]],
```

with:

```python
            "hard": [parse_violation(m) for m in state["hard"]], "unresolved": [],
            "advisory": [parse_violation(m) for m in state["advisory"]],
```

**3.6.** Edit `story_engine.py`: replace the whole of `_Run.critic_round`, this text, which occurs exactly once:

```python
    def critic_round(self, k, judged, passed_only=False):
        """One RS21 iteration on states[judged]. Returns a stop reason or None (a new state was
        appended)."""
        ctx = self.ctx
        prev = self.states[judged]
        rdir = os.path.join(self.rounds_dir, "round_%d" % k)
        base = build_critic_prompt(prev["plan"], prev["text"], (prev["hard"], prev["advisory"]),
                                   self.catalog_lines, narration=self.ctx.narration)
        prompt, reply, route, calls = base, None, None, 0
        for attempt in range(1, CRITIC_CALLS_PER_ROUND + 1):
            if self.expired():
                if calls == 0:
                    return "time_cap"
                break
            calls += 1
            self.round_dir(k)
            _write_text(os.path.join(rdir, "critic_prompt_%d.txt" % attempt), prompt)
            started = _now()
            self.agent_calls += 1
            status, answer, route = run_critic(ctx, prompt)
            self.record("critic", None, k, attempt, route, status, started)
            _write_text(os.path.join(rdir, "critic_reply_%d.txt" % attempt),
                        _reply_text(status, answer))
            reply = parse_critic(answer)
            if reply is not None:
                break
            prompt = base + CRITIC_RETRY_SUFFIX
        critic = {"route": route, "calls": calls, "reply": reply, "applied": [], "rejected": []}
        critic_path = os.path.join(rdir, "critic.json")
        if reply is not None:
            prev["scores"], prev["verdict"] = reply["scores"], reply["verdict"]
            scores = reply["scores"]

            def line(applied, rejected):
                print("critic round %d (%s): continuity=%d story=%d renderability=%d verdict=%s; "
                      "%d patch(es): %d applied, %d rejected"
                      % (k, route, scores["continuity"], scores["story"],
                         scores["renderability"], reply["verdict"], len(reply["patches"]),
                         applied, rejected))

            if (not prev["hard"] and reply["verdict"] == "ok"
                    and min(scores.values()) >= MIN_OK_SCORE):
                _write_json(critic_path, critic)
                line(0, 0)
                return "passed"
            if not passed_only and judged >= 1 and not better(self.states, judged, judged - 1):
                _write_json(critic_path, critic)
                line(0, 0)
                return "plateau"
            new, applied, rejected, _regen = apply_patches(
                ctx, {"plan": prev["plan"], "parts": prev["parts"]}, reply["patches"],
                regen=lambda kk, plan, parts: self.regenerate(prev, kk, plan, parts, k))
            critic["applied"], critic["rejected"] = applied, rejected
            _write_json(critic_path, critic)
            line(len(applied), len(rejected))
            self.make_state(k, new["plan"], new["parts"])
            return None
        print("critic round %d: no valid reply after %d call(s); code-only round" % (k, calls))
        _write_json(critic_path, critic)
        if (not passed_only and judged >= 1
                and len(prev["hard"]) >= len(self.states[judged - 1]["hard"])):
            return "plateau"
        parts = copy.deepcopy(prev["parts"])
        plan = copy.deepcopy(prev["plan"])
        for kk in range(1, ctx.panels + 1):
            mine = [m for m in prev["hard"] if parse_violation(m)["scope"] == "panel"
                    and parse_violation(m)["index"] == kk
                    and parse_violation(m)["id"] in WRITER_CHECK_IDS]
            if not mine or self.panel_calls[kk] >= PANEL_MAX_CALLS:
                continue
            if self.expired():
                self.time_up = True
                break
            new = self.panel_call(plan, parts, kk, k, mine)
            if new is not None:
                parts[kk - 1] = new
        self.make_state(k, plan, parts)
        return None
```

with:

```python
    def critic_round(self, k, judged):
        """One round on states[judged] (RS21; dialogue spec 6.5, PG5, PG6). Returns "plateau",
        "time_cap" or None (a new state was appended)."""
        ctx = self.ctx
        prev = self.states[judged]
        rdir = os.path.join(self.rounds_dir, "round_%d" % k)
        lora_allowed = bool(self.catalog_lines) and any(
            parse_violation(m)["id"] in ("L1", "L5", "L6", "L7") for m in prev["hard"])
        base = build_critic_prompt(prev["plan"], prev["text"], (prev["hard"], prev["advisory"]),
                                   self.catalog_lines if lora_allowed else None,
                                   narration=self.ctx.narration)
        prompt, reply, route, calls = base, None, None, 0
        for attempt in range(1, CRITIC_CALLS_PER_ROUND + 1):
            if self.expired():
                if calls == 0:
                    return "time_cap"
                break
            calls += 1
            self.round_dir(k)
            _write_text(os.path.join(rdir, "critic_prompt_%d.txt" % attempt), prompt)
            started = _now()
            self.agent_calls += 1
            status, answer, route = run_critic(ctx, prompt)
            self.record("critic", None, k, attempt, route, status, started)
            _write_text(os.path.join(rdir, "critic_reply_%d.txt" % attempt),
                        _reply_text(status, answer))
            reply = parse_critic(answer)
            if reply is not None:
                break
            prompt = base + CRITIC_RETRY_SUFFIX
        critic = {"route": route, "calls": calls, "reply": reply, "applied": [], "rejected": []}
        critic_path = os.path.join(rdir, "critic.json")
        if reply is not None:
            prev["scores"], prev["verdict"] = reply["scores"], reply["verdict"]
            scores = reply["scores"]

            def line(applied, rejected):
                print("critic round %d (%s): continuity=%d story=%d renderability=%d verdict=%s; "
                      "%d patch(es): %d applied, %d rejected"
                      % (k, route, scores["continuity"], scores["story"],
                         scores["renderability"], reply["verdict"], len(reply["patches"]),
                         applied, rejected))

            if judged >= 1 and not better(self.states, judged, judged - 1):
                _write_json(critic_path, critic)
                line(0, 0)
                return "plateau"
            new, applied, rejected, _regen = apply_patches(
                ctx, {"plan": prev["plan"], "parts": prev["parts"]}, reply["patches"],
                regen=lambda kk, plan, parts: self.regenerate(prev, kk, plan, parts, k),
                lora_allowed=lora_allowed)
            critic["applied"], critic["rejected"] = applied, rejected
            _write_json(critic_path, critic)
            line(len(applied), len(rejected))
            self.make_state(k, new["plan"], new["parts"])
            return None
        print("critic round %d: no valid reply after %d call(s); code-only round" % (k, calls))
        _write_json(critic_path, critic)
        if judged >= 1 and ((n_blocking(prev), len(prev["hard"]))
                            >= (n_blocking(self.states[judged - 1]),
                                len(self.states[judged - 1]["hard"]))):
            return "plateau"
        parts = copy.deepcopy(prev["parts"])
        plan = copy.deepcopy(prev["plan"])
        for kk in range(1, ctx.panels + 1):
            mine = [m for m in prev["hard"] if parse_violation(m)["scope"] == "panel"
                    and parse_violation(m)["index"] == kk]
            ids = set(parse_violation(m)["id"] for m in mine)
            if not ids & set(REPAIR_IDS) or self.panel_calls[kk] >= PANEL_MAX_CALLS:
                continue
            if self.expired():
                self.time_up = True
                break
            new = self.panel_call(plan, parts, kk, k, mine)
            if new is not None:
                parts[kk - 1] = merge_repair(ctx, plan, kk, parts[kk - 1], new, ids)
        self.make_state(k, plan, parts)
        return None
```

**3.7.** Edit `story_engine.py`: replace the whole of `_Run.judge_gate`, this text, which occurs exactly once:

```python
    def judge_gate(self):
        ctx = self.ctx
        best = self.states[best_round(self.states)]
        if best["hard"]:
            return {"status": "skipped", "detail": "best round has hard violations",
                    "scores": None, "min_score": None, "applied": False}
        if self.expired():
            return {"status": "skipped", "detail": "wall-clock cap reached", "scores": None,
                    "min_score": None, "applied": False}
        started = _now()
        status, detail, reply = run_judge(ctx, best["dir"])
        self.record("judge", None, best["round"], 1, None, status, started)
        if status != "ok":
            print("Warning: judge-story failed (%s); keeping the critic's best round" % detail)
            return {"status": "error", "detail": detail, "scores": None, "min_score": None,
                    "applied": False}
        low = min(reply["scores"].values())
        judge = {"status": "ok", "detail": "min score %d" % low, "scores": reply["scores"],
                 "min_score": low, "applied": False}
        if low >= JUDGE_MIN_SCORE:
            return judge
        j = len(self.states)
        rdir = self.round_dir(j)
        new, applied, rejected, _regen = apply_patches(
            ctx, {"plan": best["plan"], "parts": best["parts"]}, reply["patches"],
            regen=lambda kk, plan, parts: self.regenerate(best, kk, plan, parts, j),
            lora_allowed=False)
        _write_json(os.path.join(rdir, "judgment.patches.json"), reply)
        _write_json(os.path.join(rdir, "critic.json"), {
            "route": None, "calls": 0, "reply": reply, "applied": applied, "rejected": rejected})
        self.make_state(j, new["plan"], new["parts"])
        if not self.expired():
            self.critic_round(j + 1, j, passed_only=True)
        judge["applied"] = True
        return judge
```

with:

```python
    def judge_gate(self):
        """bin/judge-story --patches on the best round, as a final report only (dialogue spec 6.8):
        skipped when the best round has a blocking violation; its patches stay in the
        judgment.patches.json it writes into that round's directory and are never applied."""
        ctx = self.ctx
        best = self.states[best_round(self.states)]
        if blocking(best["hard"]):
            return {"status": "skipped", "detail": "best round has hard violations",
                    "scores": None, "min_score": None, "applied": False}
        if self.expired():
            return {"status": "skipped", "detail": "wall-clock cap reached", "scores": None,
                    "min_score": None, "applied": False}
        started = _now()
        status, detail, reply = run_judge(ctx, best["dir"])
        self.record("judge", None, best["round"], 1, None, status, started)
        if status != "ok":
            print("Warning: judge-story failed (%s); keeping the critic's best round" % detail)
            return {"status": "error", "detail": detail, "scores": None, "min_score": None,
                    "applied": False}
        low = min(reply["scores"].values())
        if low < JUDGE_MIN_SCORE:
            print("Warning: judge-story minimum score %d is below %d; its patches are saved in %s "
                  "and were not applied (only spoken timing and the amount of action are repaired "
                  "automatically)" % (low, JUDGE_MIN_SCORE,
                                      os.path.join(best["dir"], "judgment.patches.json")))
        return {"status": "ok", "detail": "min score %d" % low, "scores": reply["scores"],
                "min_score": low, "applied": False}
```

**3.8.** Edit `story_engine.py`: replace the end of `_Run.go`, from `self.make_state(0, plan, parts)` on, this text, which occurs exactly once:

```python
        self.make_state(0, plan, parts)
        stop = None
        for k in range(1, CRITIC_MAX_ROUNDS + 1):
            if self.expired():
                stop = "time_cap"
                break
            stop = self.critic_round(k, k - 1)
            if stop:
                break
            if self.time_up:
                stop = "time_cap"
                break
            if k == CRITIC_MAX_ROUNDS:
                stop = "max_rounds"
        judge = self.judge_gate() if ctx.judge else None
        best = best_round(self.states)
        state = self.states[best]
        print("stop: %s; best round %d (%d hard)" % (stop, best, len(state["hard"])))
        doc = _checks_doc(ctx, state)
        doc.update({"stop_reason": stop, "best_round": best, "judge": judge,
                    "rounds": [{"round": s["round"], "hard": len(s["hard"]),
                                "advisory": len(s["advisory"]), "scores": s["scores"],
                                "verdict": s["verdict"]} for s in self.states]})
        _write_json(os.path.join(ctx.story_dir, "plan.json"), state["plan"])
        _write_json(os.path.join(ctx.story_dir, "story_checks.json"), doc)
        _write_text(os.path.join(ctx.story_dir, "story.md"), state["text"])
        self.doc["stop_reason"], self.doc["best_round"] = stop, best
        self.advisories = state["advisory"]
        if not state["hard"]:
            return self.finish(0)
        print("Error: story.md has %d hard violation(s) after the critic rounds (best round %d of "
              "%d):" % (len(state["hard"]), best, len(self.states) - 1), file=sys.stderr)
        for message in state["hard"]:
            print("  - %s" % message, file=sys.stderr)
        print("story.md, plan.json and story_checks.json are saved in %s. Hand-edit story.md to "
              "fix the violations above and rerun: story.md already exists, so Phase 1 re-checks "
              "it instead of regenerating it (pass --force-story to regenerate)." % ctx.story_dir,
              file=sys.stderr)
        return self.finish(2)
```

with:

```python
        self.make_state(0, plan, parts)
        stop = self.critic_loop()
        judge = self.judge_gate() if ctx.judge else None
        best, blocking_list, unresolved_list = final_outcome(self.states)
        state = self.states[best]
        print("stop: %s; best round %d (%d hard)" % (stop, best, len(state["hard"])))
        doc = _checks_doc(ctx, state)
        doc.update({"hard": [parse_violation(m) for m in blocking_list],
                    "unresolved": [parse_violation(m) for m in unresolved_list],
                    "stop_reason": stop, "best_round": best, "judge": judge,
                    "rounds": [{"round": s["round"], "hard": len(s["hard"]),
                                "advisory": len(s["advisory"]), "scores": s["scores"],
                                "verdict": s["verdict"]} for s in self.states]})
        _write_json(os.path.join(ctx.story_dir, "plan.json"), state["plan"])
        _write_json(os.path.join(ctx.story_dir, "story_checks.json"), doc)
        _write_text(os.path.join(ctx.story_dir, "story.md"), state["text"])
        self.doc["stop_reason"], self.doc["best_round"] = stop, best
        self.advisories = state["advisory"]
        if not blocking_list:
            for message in unresolved_list:
                print("Warning: unresolved after %d critic round(s): %s"
                      % (len(self.states) - 1, message))
            return self.finish(0)
        print("Error: story.md has %d hard violation(s) after the critic rounds (best round %d of "
              "%d):" % (len(blocking_list), best, len(self.states) - 1), file=sys.stderr)
        for message in blocking_list:
            print("  - %s" % message, file=sys.stderr)
        if unresolved_list:
            print("Also unresolved (not blocking):", file=sys.stderr)
            for message in unresolved_list:
                print("  - %s" % message, file=sys.stderr)
        print("story.md, plan.json and story_checks.json are saved in %s. Hand-edit story.md to "
              "fix the violations above and rerun: story.md already exists, so Phase 1 re-checks "
              "it instead of regenerating it (pass --force-story to regenerate)." % ctx.story_dir,
              file=sys.stderr)
        return self.finish(2)
```

**3.9.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    # -- the whole run ---------------------------------------------------------------------

    def go(self):
```

with:

```python
    # -- the whole run ---------------------------------------------------------------------

    def critic_loop(self):
        """The critic rounds after round 0 (dialogue spec 6.5); returns the stop reason. A state
        with no hard violation stops at once, without a critic call; at most CRITIC_MAX_ROUNDS
        rounds run."""
        if not self.states[-1]["hard"]:
            return "passed"
        for k in range(1, CRITIC_MAX_ROUNDS + 1):
            if self.expired():
                return "time_cap"
            stop = self.critic_round(k, k - 1)
            if stop:
                return stop
            if not self.states[-1]["hard"]:
                return "passed"
            if self.time_up:
                return "time_cap"
        return "max_rounds"

    def go(self):
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_story_engine.py tests/test_lora_catalog.py tests/test_iterate_story.py 2>&1 | tail -1
grep -c "WRITER_CHECK_IDS\|MIN_OK_SCORE\|passed_only\|_shouting\|SHOUT" story_engine.py tests/test_story_engine.py
```

Expected: no failure other than the known `test_rst62_import_sets` (`test_rst10`, `test_rst11`, `test_rst17b`, `test_rst21`, `test_rst46`, `test_story_focus_1`-`3` and `test_story_focus_5` pass unchanged, spec 9.2 B); the `grep -c` prints `0` for both files. Compile check with `FILES` = `story_engine.py tests/test_dialogue.py tests/test_story_engine.py`; expected `compiled 3` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_dialogue.py tests/test_story_engine.py
git diff --cached --name-only
git commit -m "feat(dialogue): two critic rounds, blocking vs unresolved, blocking-first ranking, guarded code-only merge, report-only judge (6.1, 6.5, PG5, PG6, 6.8, DLG23, DLG24, DLG26)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: The patch whitelist and the sentence and line guards

Implements spec 6.6 PG1-PG4 (and deletes the regeneration path PG2 leaves without a caller). Tests DLG20, DLG22.

**Files:**
- Modify: `story_engine.py`
- Modify: `tests/test_dialogue.py`
- Modify: `tests/test_story_engine.py`, limited to the spec 9.2 reason "`apply_patches` returns a 3-tuple and has no `regen`; setting, shot, camera, image, narration and beat.action patches are rejected with the NOT_REPAIRED reason; `::test_rst29` becomes a beat.action rejection test": `test_rst27_whitelist_limit_and_duplicates`, `test_rst28_location_setting_patch`, `test_rst29_beat_action_regenerates_that_panel`, `test_rst30_shot_and_camera_reassemble_without_agent_calls`, `test_rst31_lora_patch`, `test_rst32_patches_never_change_counts_phrases_or_descriptors`, and `test_lct28_lora_limits_with_a_cast_character` (same file; only its unpacking of the 3-tuple changes).

**Interfaces:**
- Consumes: Task 12's `guard_problem(ctx, plan, old, new)`, `line_problem(ctx, lib, line)`; Task 9's `_clean_dialogue`, `speaker_phrase`; `clean_writer`, `pasted_pieces`, `lora_checks`, `_sentence`.
- Produces: `NOT_REPAIRED = "advisory"`, `NOT_REPAIRED_REASON`; `patch_ranges(ctx, plan, lora_allowed)` (PG1; `("panel", "dialogue")` added); `_patch_problem` returns `NOT_REPAIRED_REASON` for a NOT_REPAIRED field; `apply_patches(ctx, state, patches, lora_allowed=None, repairable=None) -> (new_state, applied, rejected)`; `repairable_ids(hard) -> {panel: set(ids)}`; `_Run.critic_round` passes `repairable=repairable_ids(prev["hard"])`; `_Run.regenerate` is deleted.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_dlg20_apply_patches_whitelist_and_guard`, `test_dlg22_the_critic_rewrites_one_sentence`.

**1.1.** Append to `tests/test_dialogue.py`:

```python
# --- DLG20, DLG22: the patch whitelist and guards (PG1-PG4) ----------------------------------

NOT_REPAIRED_REASON = ("not repaired automatically: only spoken timing and the amount of action "
                       "are patched")
THREE = ("The courier stops at the crates, then turns, then pedals on. The courier glances up at "
         "the rain. The camera slowly pans left.")
ONE_CHANGED = ("The courier stops at the crates and pedals on. The courier glances up at the rain. "
               "The camera slowly pans left.")
TWO_CHANGED = ("The courier stops at the crates and pedals on. The courier looks up at the grey "
               "sky. The camera slowly pans left.")


def _patch(target, index, field, replacement):
    return {"target": target, "index": index, "field": field, "reason": "r",
            "replacement": replacement}


def test_dlg20_apply_patches_whitelist_and_guard(ws):
    no_problem = ("panel %d has no hard timing or amount-of-action problem; advisory findings are "
                  "never patched")
    ctx, plan, parts, _t, _p = _story(ws, "chained", 3, plan_mut=_speaking(2),
                                      replies={2: {"motion": THREE, "dialogue": OVER_CAP}})
    state = {"plan": plan, "parts": parts}
    result = se.apply_patches(ctx, state, [
        _patch("plan", 2, field, "x") for field in ("beat.action", "beat.shot", "beat.camera",
                                                    "location.setting")]
        + [_patch("panel", 1, "image", "x"), _patch("panel", 2, "narration", "x")])
    assert len(result) == 3
    new, applied, rejected = result
    assert applied == [] and new == state
    assert [r["reason"] for r in rejected] == [NOT_REPAIRED_REASON] * 6
    _new, applied, rejected = se.apply_patches(ctx, state, [
        _patch("panel", 2, "motion", ONE_CHANGED), _patch("panel", 3, "dialogue", "Hello there.")],
        repairable={2: {"T1"}})
    assert applied == [] and [r["reason"] for r in rejected] == [no_problem % 2, no_problem % 3]
    new, applied, rejected = se.apply_patches(ctx, state, [
        _patch("panel", 2, "dialogue", 'the courier: "I carry a letter for the abbot"')],
        repairable={2: {"T1"}})
    assert len(applied) == 1 and new["parts"][1]["dialogue"] == "I carry a letter for the abbot."
    for replacement, reason in (
            (OVER_CAP, "the new line is 15 words in 1 sentences; at most 14 words in 1 sentences "
                       "fit this clip"),
            ('  ""  ', "empty after cleanup")):
        _new, applied, rejected = se.apply_patches(ctx, state, [
            _patch("panel", 2, "dialogue", replacement)])
        assert applied == [] and [r["reason"] for r in rejected] == [reason], replacement
    new, applied, rejected = se.apply_patches(ctx, state, [_patch("panel", 2, "motion",
                                                                  ONE_CHANGED)])
    assert len(applied) == 1 and new["parts"][1]["motion"] == ONE_CHANGED
    _new, applied, rejected = se.apply_patches(ctx, state, [_patch("panel", 2, "motion",
                                                                   TWO_CHANGED)])
    assert [r["reason"] for r in rejected] == [
        "the patch changes 2 sentences; it may change at most 1 contiguous sentence(s) and must "
        "keep every other sentence word for word"]
    panned = {"plan": plan, "parts": copy.deepcopy(parts)}
    panned["parts"][2]["motion"] = "The courier stops, then turns, then waves. The camera slowly pans left."
    _new, applied, rejected = se.apply_patches(ctx, panned, [
        _patch("panel", 3, "motion", "The courier stops, then turns, then waves. The courier rests.")])
    assert [r["reason"] for r in rejected] == [
        "the patch drops the camera direction 'The camera slowly pans left.'"]


def test_dlg22_the_critic_rewrites_one_sentence(ws, tmp_path, monkeypatch):
    good = _patch("panel", 2, "motion", ONE_CHANGED)
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, plan=_speaking_plan("chained", 3, 2),
                            panel=_replies("chained", 3, {2: [{"motion": THREE, "dialogue": LINE}]}),
                            critic=[seu.answer(seu.critic_json((6, 6, 6), "revise", [good]))])
    assert rc == 0
    rounds = os.path.join(ctx.story_dir, "story_rounds")
    with open(os.path.join(rounds, "round_0", "story.md"), encoding="utf-8") as f:
        before = f.read()
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        after = f.read()
    assert after == before.replace("Motion: " + THREE + " ", "Motion: " + ONE_CHANGED + " ")
    assert ("Motion: " + ONE_CHANGED + " The courier faces the camera. The camera stays static.\n"
            + "Dialogue: the courier: " + LINE + "\n") in after
    assert _read_json(os.path.join(rounds, "round_1", "critic.json"))["applied"] == [good]
    state0 = {"plan": _read_json(os.path.join(rounds, "round_0", "plan.json")),
              "parts": [dict((key, value) for key, value in p.items() if key != "index")
                        for p in _read_json(os.path.join(rounds, "round_0", "parts.json"))["panels"]]}
    _new, applied, rejected = se.apply_patches(ctx, state0, [dict(good, replacement=TWO_CHANGED)],
                                               repairable={2: {"T2"}})
    assert applied == [] and [r["reason"] for r in rejected] == [
        "the patch changes 2 sentences; it may change at most 1 contiguous sentence(s) and must "
        "keep every other sentence word for word"]
```

**1.2.** Edit `tests/test_story_engine.py`: replace the whole of `test_rst27_whitelist_limit_and_duplicates`, this text, which occurs exactly once:

```python
def test_rst27_whitelist_limit_and_duplicates(ws):
    ctx, state = _state(ws, "chained")
    good_action = "the courier coasts slowly down the empty harbour road"
    patches = [
        _patch("plan", 2, "beat.shot", "close-up"),
        _patch("plan", 2, "beat.camera", "static"),
        _patch("panel", 2, "image", "x"),
        _patch("panel", 1, "prompt", "x"),
        _patch("plan", 1, "lora", []),
        _patch("plan", 4, "beat.action", good_action),
        _patch("plan", True, "beat.action", good_action),
        _patch("panel", 0, "narration", "x"),
        _patch("story", 1, "narration", "x"),
        {"target": "panel", "index": 1, "field": "narration"},
        _patch("panel", 1, "narration", ["x"]),
        _patch("plan", 1, "lora", "x"),
    ]
    new, applied, rejected, regenerate = se.apply_patches(ctx, state, patches[:8])
    assert applied == [] and regenerate == []
    assert _reasons(rejected) == [
        "index 2 is out of range for beat.shot (allowed: 1 only)",
        "index 2 is out of range for beat.camera (allowed: 1 only)",
        "index 2 is out of range for image (allowed: 1 only)",
        "field not allowed in this mode",
        "field not allowed in this mode",
        "index 4 is out of range for beat.action (allowed: 1 to 3)",
        "index is not an integer",
        "index 0 is out of range for narration (allowed: 1 to 3)"]
    _new, _a, rejected, _r = se.apply_patches(ctx, state, patches[8:])
    assert _reasons(rejected) == [
        "unknown target or field",
        "not an object with the keys target, index, field, reason and replacement",
        "replacement must be a string", "field not allowed in this mode"]
    nine = [_patch("panel", (i % 3) + 1, "narration", "Line %d of the rain." % i) for i in range(9)]
    _new, applied, rejected, _r = se.apply_patches(ctx, state, nine)
    assert [p["index"] for p in applied] == [1, 2, 3]
    assert _reasons(rejected) == ["duplicate patch target"] * 5 + ["over the 8-patch limit"]
    assert rejected[-1]["patch"] is nine[8]
    shots_ctx, shots_state = _state(ws, "shots")
    _new, applied, rejected, _r = se.apply_patches(shots_ctx, shots_state, [
        _patch("plan", 3, "beat.shot", "close-up"), _patch("panel", 3, "image", "The courier "
                                                                                "waits."),
        _patch("panel", 2, "prompt", "x")])
    assert len(applied) == 2 and _reasons(rejected) == ["field not allowed in this mode"]
    no_stills_ctx, ns_state = _state(ws, "no_stills")
    _new, applied, rejected, _r = se.apply_patches(no_stills_ctx, ns_state, [
        _patch("panel", 2, "motion", "x"), _patch("panel", 2, "prompt", "The courier pedals.")])
    assert len(applied) == 1 and _reasons(rejected) == ["field not allowed in this mode"]
    assert state["parts"][0]["narration"] == "The rain had not stopped since dawn."
```

with:

```python
NOT_REPAIRED_REASON = ("not repaired automatically: only spoken timing and the amount of action "
                       "are patched")


def test_rst27_whitelist_limit_and_duplicates(ws):
    ctx, state = _state(ws, "chained")
    good_action = "the courier coasts slowly down the empty harbour road"
    patches = [
        _patch("plan", 2, "beat.shot", "close-up"),
        _patch("plan", 2, "beat.camera", "static"),
        _patch("panel", 2, "image", "x"),
        _patch("panel", 1, "prompt", "x"),
        _patch("plan", 1, "lora", []),
        _patch("plan", 4, "beat.action", good_action),
        _patch("plan", True, "beat.action", good_action),
        _patch("panel", 0, "narration", "x"),
        _patch("story", 1, "narration", "x"),
        {"target": "panel", "index": 1, "field": "narration"},
        _patch("panel", 1, "narration", ["x"]),
        _patch("plan", 1, "lora", "x"),
    ]
    new, applied, rejected = se.apply_patches(ctx, state, patches[:8])
    assert applied == []
    assert _reasons(rejected) == [
        NOT_REPAIRED_REASON, NOT_REPAIRED_REASON, NOT_REPAIRED_REASON,
        "field not allowed in this mode", "field not allowed in this mode",
        NOT_REPAIRED_REASON, NOT_REPAIRED_REASON, NOT_REPAIRED_REASON]
    _new, _a, rejected = se.apply_patches(ctx, state, patches[8:])
    assert _reasons(rejected) == [
        "unknown target or field",
        "not an object with the keys target, index, field, reason and replacement",
        NOT_REPAIRED_REASON, "field not allowed in this mode"]
    nine = [_patch("panel", (i % 3) + 1, "dialogue", "Line %d of the rain." % i) for i in range(9)]
    _new, applied, rejected = se.apply_patches(ctx, state, nine)
    assert [p["index"] for p in applied] == [1, 2, 3]
    assert _reasons(rejected) == ["duplicate patch target"] * 5 + ["over the 8-patch limit"]
    assert rejected[-1]["patch"] is nine[8]
    shots_ctx, shots_state = _state(ws, "shots")
    _new, applied, rejected = se.apply_patches(shots_ctx, shots_state, [
        _patch("plan", 3, "beat.shot", "close-up"), _patch("panel", 3, "image", "The courier "
                                                                                "waits."),
        _patch("panel", 2, "prompt", "x")])
    assert applied == [] and _reasons(rejected) == [
        NOT_REPAIRED_REASON, NOT_REPAIRED_REASON, "field not allowed in this mode"]
    no_stills_ctx, ns_state = _state(ws, "no_stills")
    rest = se._SENTENCE_SPLIT_RE.split(ns_state["parts"][1]["prompt"], 1)[1]
    _new, applied, rejected = se.apply_patches(no_stills_ctx, ns_state, [
        _patch("panel", 2, "motion", "x"),
        _patch("panel", 2, "prompt", "The courier coasts along the wet harbour road. " + rest)])
    assert len(applied) == 1 and _reasons(rejected) == ["field not allowed in this mode"]
    assert state["parts"][0]["narration"] == "The rain had not stopped since dawn."
```

**1.3.** Edit `tests/test_story_engine.py`: replace the whole of `test_rst28_location_setting_patch`, this text, which occurs exactly once:

```python
def test_rst28_location_setting_patch(ws):
    ctx, state = _state(ws, "shots")
    new_setting = ("The setting is a stormy fishing harbour in modern Japan, slick black "
                   "cobblestones underfoot, cranes behind, under blue evening light.")
    new, applied, rejected, _r = se.apply_patches(ctx, state, [
        _patch("plan", 1, "location.setting", new_setting[:-1]),
        _patch("plan", 2, "location.setting", "A short harbour")])
    assert len(applied) == 1
    assert _reasons(rejected) == ['the new setting does not start with "The setting is"']
    text = se.assemble(ctx, new["plan"], new["parts"])
    assert text.count(new_setting) == 3
    assert seu.HARBOUR not in text
    assert state["plan"]["locations"][0]["setting"] == seu.HARBOUR
```

with:

```python
def test_rst28_location_setting_patch(ws):
    ctx, state = _state(ws, "shots")
    new, applied, rejected = se.apply_patches(ctx, state, [
        _patch("plan", 1, "location.setting", seu.TEMPLE)])
    assert applied == [] and _reasons(rejected) == [NOT_REPAIRED_REASON]
    assert se.assemble(ctx, new["plan"], new["parts"]).count(seu.HARBOUR) == 3
    assert state["plan"]["locations"][0]["setting"] == seu.HARBOUR
```

**1.4.** Edit `tests/test_story_engine.py`: replace the whole of `test_rst29_beat_action_regenerates_that_panel`, this text, which occurs exactly once:

```python
def test_rst29_beat_action_regenerates_that_panel(ws):
    ctx, state = _state(ws, "shots")
    calls = []

    def regen(k, plan, parts):
        calls.append((k, plan["beats"][k - 1]["action"]))
        return "ok", dict(parts[k - 1], motion="The courier rests one hand on the railing.")

    action = "the courier stops beside the railing to catch his breath"
    new, applied, rejected, regenerate = se.apply_patches(ctx, state, [
        _patch("plan", 2, "beat.action", action),
        _patch("panel", 2, "motion", "The courier waves."),
        _patch("plan", 3, "beat.action", "too short")], regen=regen)
    assert calls == [(2, action)] and regenerate == [2]
    assert new["parts"][1]["motion"] == "The courier rests one hand on the railing."
    assert _reasons(rejected) == ["the new action is 2 words; it must be 6 to 40",
                                  "panel regenerated from a beat.action patch this round"]
    new, applied, rejected, regenerate = se.apply_patches(
        ctx, state, [_patch("plan", 2, "beat.action", action)],
        regen=lambda k, plan, parts: ("budget", None))
    assert new["plan"]["beats"][1]["action"] == action
    assert new["parts"][1] == state["parts"][1]
    assert _reasons(rejected) == ["panel 2 regeneration skipped: call budget exhausted"]
```

with:

```python
def test_rst29_beat_action_regenerates_that_panel(ws):
    # A beat.action patch is never applied and no panel is regenerated (dialogue spec PG1, PG2).
    ctx, state = _state(ws, "shots")
    action = "the courier stops beside the railing to catch his breath"
    new, applied, rejected = se.apply_patches(ctx, state, [_patch("plan", 2, "beat.action", action)])
    assert applied == [] and new == state
    assert _reasons(rejected) == [NOT_REPAIRED_REASON]
    assert "regen" not in inspect.signature(se.apply_patches).parameters
    assert not hasattr(se._Run, "regenerate")
```

**1.5.** Edit `tests/test_story_engine.py`: replace the whole of `test_rst30_shot_and_camera_reassemble_without_agent_calls`, this text, which occurs exactly once:

```python
def test_rst30_shot_and_camera_reassemble_without_agent_calls(ws, monkeypatch):
    ctx, state = _state(ws, "shots")
    monkeypatch.setattr(se, "run_agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    new, applied, rejected, regenerate = se.apply_patches(ctx, state, [
        _patch("plan", 2, "beat.shot", "Close-Up"), _patch("plan", 2, "beat.camera", "slow pan left"),
        _patch("plan", 3, "beat.shot", "aerial")])
    assert regenerate == [] and len(applied) == 2
    assert _reasons(rejected) == ["'aerial' is not one of: extreme wide shot, wide shot, medium "
                                  "shot, medium close-up, close-up, extreme close-up"]
    fields = dict(se.panel_fields(ctx, new["plan"], new["parts"], 2))
    assert fields["Image"].endswith(" The shot is a close-up.")
    assert fields["Motion"].endswith(" The camera slowly pans left.")
```

with:

```python
def test_rst30_shot_and_camera_reassemble_without_agent_calls(ws, monkeypatch):
    ctx, state = _state(ws, "shots")
    monkeypatch.setattr(se, "run_agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    new, applied, rejected = se.apply_patches(ctx, state, [
        _patch("plan", 2, "beat.shot", "Close-Up"), _patch("plan", 2, "beat.camera", "slow pan left")])
    assert applied == [] and _reasons(rejected) == [NOT_REPAIRED_REASON] * 2
    fields = dict(se.panel_fields(ctx, new["plan"], new["parts"], 2))
    assert fields["Image"].endswith(" The shot is a wide shot.")
    assert fields["Motion"].endswith(" The camera tracks alongside the movement.")
```

**1.6.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    new, applied, rejected, _r = se.apply_patches(ctx, state, [
        _patch("plan", 0, "lora", [{"id": "fast-motion", "strength": 0.7}]),
```

with:

```python
    new, applied, rejected = se.apply_patches(ctx, state, [
        _patch("plan", 0, "lora", [{"id": "fast-motion", "strength": 0.7}]),
```

**1.7.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    cleared, applied, _rj, _r = se.apply_patches(ctx, new, [_patch("plan", 0, "lora", [])])
```

with:

```python
    cleared, applied, _rj = se.apply_patches(ctx, new, [_patch("plan", 0, "lora", [])])
```

**1.8.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
        new, _a, _rj, _r = se.apply_patches(ctx, state, patches)
```

with:

```python
        new, _a, _rj = se.apply_patches(ctx, state, patches)
```

**1.9.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    _new, applied, rejected, _r = se.apply_patches(ctx, state, [
        _patch("plan", 2, "lora", [{"id": "fast-motion", "strength": 0.7},
```

with:

```python
    _new, applied, rejected = se.apply_patches(ctx, state, [
        _patch("plan", 2, "lora", [{"id": "fast-motion", "strength": 0.7},
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k "dlg20 or dlg22" 2>&1 | tail -3
python3 -m pytest -q -p no:cacheprovider tests/test_story_engine.py -k "rst27 or rst28 or rst29 or rst30 or rst31 or rst32 or lct28" 2>&1 | tail -3
```

Expected: `2 failed` (`ValueError: too many values to unpack (expected 3)`), then `7 failed` (the 3-tuple unpacking and the NOT_REPAIRED reasons).

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace the whole of `patch_ranges`, this text, which occurs exactly once:

```python
def patch_ranges(ctx, plan, lora_allowed):
    """{(target, field): (lo, hi) | None} -- None means "field not allowed in this mode"."""
    n, mode = ctx.panels, ctx.mode
    first_only = (1, 1) if mode == "chained" else (1, n)
    return {("plan", "beat.action"): (1, n),
            ("plan", "beat.shot"): first_only,
            ("plan", "beat.camera"): first_only,
            ("plan", "location.setting"): (1, len(plan["locations"])),
            ("plan", "lora"): (0, n) if lora_allowed else None,
            ("panel", "image"): first_only if mode != "no_stills" else None,
            ("panel", "motion"): (1, n) if mode != "no_stills" else None,
            ("panel", "prompt"): (1, n) if mode == "no_stills" else None,
            ("panel", "narration"): (1, n) if ctx.narration else None}
```

with:

```python
NOT_REPAIRED = "advisory"
NOT_REPAIRED_REASON = ("not repaired automatically: only spoken timing and the amount of action "
                       "are patched")


def patch_ranges(ctx, plan, lora_allowed):
    """{(target, field): (lo, hi) | None | NOT_REPAIRED} (dialogue spec PG1) -- None means "field
    not allowed in this mode"; NOT_REPAIRED marks a field that is never patched (it only ever
    holds advisory findings)."""
    n, mode = ctx.panels, ctx.mode
    return {("plan", "beat.action"): NOT_REPAIRED,
            ("plan", "beat.shot"): NOT_REPAIRED,
            ("plan", "beat.camera"): NOT_REPAIRED,
            ("plan", "location.setting"): NOT_REPAIRED,
            ("plan", "lora"): (0, n) if lora_allowed else None,
            ("panel", "image"): NOT_REPAIRED,
            ("panel", "motion"): (1, n) if mode != "no_stills" else None,
            ("panel", "prompt"): (1, n) if mode == "no_stills" else None,
            ("panel", "dialogue"): (1, n) if ctx.narration is not False else None,
            ("panel", "narration"): NOT_REPAIRED}
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    span = ranges[key]
    if span is None:
        return "field not allowed in this mode"
```

with:

```python
    span = ranges[key]
    if span == NOT_REPAIRED:
        return NOT_REPAIRED_REASON
    if span is None:
        return "field not allowed in this mode"
```

**3.3.** Edit `story_engine.py`: replace the whole of `apply_patches`, this text, which occurs exactly once:

```python
def apply_patches(ctx, state, patches, regen=None, lora_allowed=None):
    """(new_state, applied, rejected, regenerate) for a state {"plan", "parts"} and a patch
    list (RS20). Works on a deep copy. regen(k, plan, parts) -> ("ok", parts_k) | ("failed",
    None) | ("budget", None) | ("time", None) regenerates panel k after a beat.action patch;
    without regen the panel keeps its parts. rejected items are {"patch", "reason"}."""
    new = copy.deepcopy(state)
    plan, parts = new["plan"], new["parts"]
    lib = _character_lib(ctx.ws)
    if lora_allowed is None:
        lora_allowed = lora_patches_allowed(ctx)
    ranges = patch_ranges(ctx, plan, lora_allowed)
    applied, rejected, regenerate = [], [], []
    accepted, seen = [], set()
    patches = patches if isinstance(patches, list) else []
    for i, patch in enumerate(patches):
        if i >= MAX_PATCHES:
            rejected.append({"patch": patch, "reason": "over the 8-patch limit"})
            continue
        problem = _patch_problem(ranges, patch)
        if problem is None:
            key = (patch["target"], patch["index"], patch["field"])
            if key in seen:
                problem = "duplicate patch target"
            seen.add(key)
        if problem:
            rejected.append({"patch": patch, "reason": problem})
        else:
            accepted.append(patch)
    compatible_by_id = {e["id"]: e for e in compatible_entries(ctx)}
    catalog_by_id = {e["id"]: e for e in ctx.catalog.get("entries", [])}
    for patch in accepted:
        if patch["target"] != "plan":
            continue
        field, index = patch["field"], patch["index"]
        if field == "beat.action":
            action = clean_writer(lib, patch["replacement"])
            words = _words(action)
            if outside_range(words, 6, 40):
                rejected.append({"patch": patch, "reason": "the new action is %d words; it must "
                                                           "be 6 to 40" % words})
                continue
            plan["beats"][index - 1]["action"] = action
            regenerate.append(index)
        elif field in ("beat.shot", "beat.camera"):
            value = _collapse(patch["replacement"]).lower()
            allowed = shot_types(ctx.narration) if field == "beat.shot" else CAMERA_KEYS
            if value not in allowed:
                rejected.append({"patch": patch, "reason": "%s is not one of: %s"
                                 % (_q(value), ", ".join(allowed))})
                continue
            plan["beats"][index - 1][field.split(".")[1]] = value
        elif field == "location.setting":
            setting = _collapse(patch["replacement"])
            if setting and not setting.endswith((".", "!", "?")):
                setting += "."
            problems = _setting_problems(setting)
            if problems:
                rejected.append({"patch": patch, "reason": "the new setting " + problems[0]})
                continue
            plan["locations"][index - 1]["setting"] = setting
        else:
            before = lora_checks(ctx, plan, compatible_by_id, catalog_by_id)[0]
            saved = copy.deepcopy(plan["loras"])
            if index == 0:
                plan["loras"]["global"] = patch["replacement"]
            elif patch["replacement"]:
                plan["loras"]["per_beat"][str(index)] = patch["replacement"]
            else:
                plan["loras"]["per_beat"].pop(str(index), None)
            broken = [h for h in lora_checks(ctx, plan, compatible_by_id, catalog_by_id)[0]
                      if h not in before]
            if broken:
                plan["loras"] = saved
                rejected.append({"patch": patch, "reason": "would break " + broken[0]})
                continue
        applied.append(patch)
    regenerate = sorted(set(regenerate))
    for k in regenerate:
        if regen is None:
            continue
        outcome, new_parts = regen(k, plan, parts)
        if outcome == "ok":
            parts[k - 1] = new_parts
        elif outcome in ("budget", "time"):
            action_patch = [p for p in accepted if p["field"] == "beat.action"
                            and p["index"] == k][0]
            rejected.append({"patch": action_patch, "reason": "panel %d regeneration skipped: %s"
                             % (k, "call budget exhausted" if outcome == "budget"
                                else "wall-clock cap reached")})
    for patch in accepted:
        if patch["target"] != "panel":
            continue
        k, field = patch["index"], patch["field"]
        if k in regenerate:
            rejected.append({"patch": patch,
                             "reason": "panel regenerated from a beat.action patch this round"})
            continue
        text = clean_writer(lib, patch["replacement"],
                            pasted_pieces(ctx, plan, k).get(field, ()))
        if not text:
            rejected.append({"patch": patch, "reason": "empty after cleanup"})
            continue
        parts[k - 1][field] = text
        applied.append(patch)
    return new, applied, rejected, regenerate
```

with:

```python
def apply_patches(ctx, state, patches, lora_allowed=None, repairable=None):
    """(new_state, applied, rejected) for a state {"plan", "parts"} and a patch list (RS20;
    dialogue spec PG1-PG4). Works on a deep copy; rejected items are {"patch", "reason"}.
    repairable is {panel: set of hard ids} of the judged state, or None for no restriction: a
    motion or prompt patch needs a T2 or T3 on its panel, a dialogue patch a T1. A motion or
    prompt replacement must pass the PG3 sentence guard; a dialogue replacement must fit the
    clip (PG4)."""
    new = copy.deepcopy(state)
    plan, parts = new["plan"], new["parts"]
    lib = _character_lib(ctx.ws)
    if lora_allowed is None:
        lora_allowed = lora_patches_allowed(ctx)
    ranges = patch_ranges(ctx, plan, lora_allowed)
    applied, rejected = [], []
    accepted, seen = [], set()
    patches = patches if isinstance(patches, list) else []
    for i, patch in enumerate(patches):
        if i >= MAX_PATCHES:
            rejected.append({"patch": patch, "reason": "over the 8-patch limit"})
            continue
        problem = _patch_problem(ranges, patch)
        if problem is None:
            key = (patch["target"], patch["index"], patch["field"])
            if key in seen:
                problem = "duplicate patch target"
            seen.add(key)
        if problem:
            rejected.append({"patch": patch, "reason": problem})
        else:
            accepted.append(patch)
    compatible_by_id = {e["id"]: e for e in compatible_entries(ctx)}
    catalog_by_id = {e["id"]: e for e in ctx.catalog.get("entries", [])}
    for patch in accepted:
        if patch["target"] != "plan":
            continue
        index = patch["index"]
        before = lora_checks(ctx, plan, compatible_by_id, catalog_by_id)[0]
        saved = copy.deepcopy(plan["loras"])
        if index == 0:
            plan["loras"]["global"] = patch["replacement"]
        elif patch["replacement"]:
            plan["loras"]["per_beat"][str(index)] = patch["replacement"]
        else:
            plan["loras"]["per_beat"].pop(str(index), None)
        broken = [h for h in lora_checks(ctx, plan, compatible_by_id, catalog_by_id)[0]
                  if h not in before]
        if broken:
            plan["loras"] = saved
            rejected.append({"patch": patch, "reason": "would break " + broken[0]})
            continue
        applied.append(patch)
    for patch in accepted:
        if patch["target"] != "panel":
            continue
        k, field = patch["index"], patch["field"]
        need = {"T1"} if field == "dialogue" else {"T2", "T3"}
        if repairable is not None and not (repairable.get(k, set()) & need):
            rejected.append({"patch": patch, "reason": "panel %d has no hard timing or "
                                                       "amount-of-action problem; advisory "
                                                       "findings are never patched" % k})
            continue
        if field == "dialogue":
            text = _sentence(_clean_dialogue(lib, clean_writer(lib, patch["replacement"]),
                                             speaker_phrase(plan, k)))
            problem = line_problem(ctx, lib, text) if text else "empty after cleanup"
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
    return new, applied, rejected


def repairable_ids(hard):
    """{panel number: set of its hard violation ids} (dialogue spec PG2)."""
    out = {}
    for message in hard:
        violation = parse_violation(message)
        if violation["scope"] == "panel" and violation["index"]:
            out.setdefault(violation["index"], set()).add(violation["id"])
    return out
```

**3.4.** Edit `story_engine.py`: replace the method `_Run.regenerate` (with the blank line before it), this text, which occurs exactly once:

```python
        return parse_panel_reply(ctx, plan, k, answer)

    def regenerate(self, state, k, plan, parts, rnd):
        """("ok", parts_k) | ("failed", None) | ("budget", None) | ("time", None)."""
        if self.panel_calls[k] >= PANEL_MAX_CALLS:
            return "budget", None
        if self.expired():
            self.time_up = True
            return "time", None
        fix = [m for m in state["hard"] + state["advisory"]
               if parse_violation(m)["index"] == k
               and parse_violation(m)["scope"] in ("panel", "beat")]
        if not fix:
            fix = ["this panel's beat was revised; rewrite the panel for the new beat"]
        new = self.panel_call(plan, parts, k, rnd, fix)
        return ("ok", new) if new is not None else ("failed", None)
```

with:

```python
        return parse_panel_reply(ctx, plan, k, answer)
```

**3.5.** Edit `story_engine.py`: replace (this is the call Task 12 wrote in `_Run.critic_round`) this text, which occurs exactly once:

```python
            new, applied, rejected, _regen = apply_patches(
                ctx, {"plan": prev["plan"], "parts": prev["parts"]}, reply["patches"],
                regen=lambda kk, plan, parts: self.regenerate(prev, kk, plan, parts, k),
                lora_allowed=lora_allowed)
```

with:

```python
            new, applied, rejected = apply_patches(
                ctx, {"plan": prev["plan"], "parts": prev["parts"]}, reply["patches"],
                lora_allowed=lora_allowed, repairable=repairable_ids(prev["hard"]))
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_story_engine.py tests/test_lora_catalog.py 2>&1 | tail -1
grep -c "def regenerate\|regen=\|beat.action\": (1" story_engine.py
```

Expected: no failure other than the known `test_rst62_import_sets` (every run test Task 12 rewrote passes unchanged: its patches change one sentence of a T2 panel); the `grep -c` prints `0`. Compile check with `FILES` = `story_engine.py tests/test_dialogue.py tests/test_story_engine.py`; expected `compiled 3` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_dialogue.py tests/test_story_engine.py
git diff --cached --name-only
git commit -m "feat(dialogue): patch only spoken timing and the amount of action, guarded sentence by sentence (PG1-PG4, DLG20, DLG22)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Reclassification of every other check, and the re-check

Implements spec 6.3 and the remaining bullets of 6.4 (the N, P, L and S classes, `plan_copied_examples`, `plan_free_report`, `_undeclared_gate`) and 6.7. Tests DLG18, DLG21, DLG25.

**Files:**
- Modify: `story_engine.py`
- Modify: `tests/test_dialogue.py`
- Modify: `tests/test_story_engine.py`, limited to the spec 9.2 reasons: `test_rst15_lora_checks` ("hard→advisory moves; the L5 split"), `test_rst20_panel_checks` (its direct `_field_checks` call, whose N5/N6 now come back advisory; Task 10 made its N3 edits), `test_rst20c_narration_modes` (the voice-over N16 re-check is now advisory), `test_rst44_recheck_with_plan`, `test_rst44b_recheck_stale_plan_cast_does_not_mask`, `test_rst44d_recheck_no_plan_enforces_n15`, `test_rst44e_recheck_judges_writer_text_like_generation`, `test_rst45_recheck_without_plan`, `test_rst56b_n15_in_recheck_and_plan_free_report` ("N15/N7 are advisory; re-check exits 2 only when something is blocking; `plan_free_report` returns `(hard, advisory)`"), `test_rst55b_p13_forces_plan_call_2` ("P13 no longer forces plan call 2"). `test_rst14_plan_checks`, `test_rst55_p13_undeclared_character`, `test_rst56_n15_undeclared_character_in_panels`, `test_rst56b_n15_masks_declared_phrase` and `test_rst56c` are listed by spec 9.2 but pass unchanged: they compare `hard + advisory`, whose order the moves keep; DLG18 pins the classes themselves.

**Interfaces:**
- Consumes: Task 12's `blocking`, `unresolved`; `character_lib.shots_violations` (unchanged: still returns S1-S12 together).
- Produces: `SHOTS_HARD_RULES = ("S1", "S3")`; `split_shots(violations) -> (S1/S3 list, other S list)`; `_field_checks` reports N2-N10, N15 and both N16 branches as advisory, N11 only with no `Dialogue:`; `plan_checks` keeps P1, P2 and P3's normalize and duplicate messages hard and reports every other P message as advisory; `lora_checks` keeps L1, L6, L7 and the new `"plan: L5 strength: %s strength %s is outside (0, 2], which the renderer refuses"` hard and reports L2-L4 and the in-range L5 as advisory; `panel_checks` puts `plan_copied_examples` and the non-S1/S3 S rules into advisory; `plan_free_report(...) -> (hard, advisory)`; `_undeclared_gate` only prints `Warning:` lines; `recheck` writes `hard` = blocking and `unresolved`, exits 2 only when something blocks, and prints `Warning: unresolved: ...` otherwise; `apply_patches`' LoRA "would break" check compares hard and advisory LoRA findings.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_dlg18_reclassification`, `test_dlg21_an_advisory_only_round_0_passes_untouched`, `test_dlg25_recheck_blocks_only_on_blocking_violations`.

**1.1.** Append to `tests/test_dialogue.py`:

```python
# --- DLG18, DLG21, DLG25: the D6 classes and the re-check (6.3, 6.4, 6.7) -------------------

NARRATIVE = "A courier carries a sealed letter across a rainy harbour town."
STRIKE = "The courier strikes the old monk with a heavy staff."


def _ids(messages):
    return set(se.parse_violation(m if isinstance(m, str) else m["message"])["id"]
               for m in messages)


def _saved(ws, monkeypatch, mode="chained", n=3, story_id="s1", plan_mut=None, replies=None):
    """A story.md and plan.json saved in <story_dir> as a run would leave them."""
    monkeypatch.setattr(ltx_movie, "WS", ws)
    ctx, plan, _parts, text, _path = _story(ws, mode, n, plan_mut=plan_mut, replies=replies,
                                            ctx_kw={"story_id": story_id})
    with open(os.path.join(ctx.story_dir, "story.md"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(ctx.story_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f)
    return ctx, text


def _edit(ctx, old, new):
    path = os.path.join(ctx.story_dir, "story.md")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert text.count(old) == 1, old
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.replace(old, new))


def _two_people(raw):
    raw["beats"][1]["cast"] = ["c1", "c2"]


def test_dlg18_reclassification(ws, tmp_path, monkeypatch, capsys, story_env):
    def advisory_only(mode, rule, replies):
        hard, advisory = _checks(ws, mode, replies=replies)
        assert hard == [] and _only(advisory, rule), (rule, hard, advisory)

    advisory_only("chained", "N2", {2: {"motion": "The courier waves at the woman beside the "
                                                  "crates and keeps pedalling forward in the rain."}})
    advisory_only("chained", "N3", {2: {"motion": "The courier pulls the grey hood tighter and "
                                                  "pedals forward along the road past the boats."}})
    advisory_only("chained", "N4", {2: {"motion": "The courier pedals past the old monk beside the "
                                                  "crates and on toward the end of the quay."}})
    advisory_only("chained", "N5", {1: {"image": seu.panel_json("chained", 1)["image"][:300] + " "
                                                 + seu.TEMPLE}})
    advisory_only("no_stills", "N7", {2: {"prompt": seu.panel_json("no_stills", 2)["prompt"]
                                                    + " A fisherman shouts across the water."}})
    advisory_only("chained", "N7", {3: {"motion": 'The courier reads the "urgent" note and pedals '
                                                  "on toward the end of the quay."}})
    advisory_only("shots", "N7", {2: {"image": seu.panel_json("shots", 2)["image"]
                                               + " A caption fills the lower edge."}})
    advisory_only("chained", "N8", {2: {"motion": "The courier pedals toward a noise off-screen at "
                                                  "the far end of the long quay."}})
    advisory_only("chained", "N9", {2: {"motion": "The courier pedals hard and we cut to the far "
                                                  "end of the quay at once."}})
    advisory_only("chained", "N10", {1: {"narration": "<one sentence of voice-over narration>"}})
    replies = {2: {"motion": STRIKE}, 3: {"motion": "The courier steps forward then turns."}}
    ctx, plan, parts, text, path = _story(ws, "shots", 3, plan_mut=_two_people, replies=replies)
    parts[2]["narration"] = ""
    text = se.assemble(ctx, plan, parts)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    hard, advisory = se.panel_checks(ctx._replace(panels=4), plan, parts, text, path)
    assert _ids(hard) == {"S1", "S3", "N11"} and {"S5", "S8"} <= _ids(advisory)
    saved, _text = _saved(ws, monkeypatch, "shots", story_id="d18", plan_mut=_two_people,
                          replies=replies)
    _edit(saved, "Narration: " + seu.panel_json("shots", 3)["narration"] + "\n", "")
    assert se.recheck(saved, ltx_movie._validate_story_md)[0] == 2
    checks = _read_json(os.path.join(saved.story_dir, "story_checks.json"))
    assert {"S3", "N11"} <= _ids(checks["hard"]) and not {"S5", "S8"} & _ids(checks["hard"])
    assert {"S5", "S8"} <= _ids(checks["advisory"])
    story_md = os.path.join(saved.story_dir, "story.md")
    report = se.plan_free_report(story_md, "shots", 4, [], ltx_movie._validate_story_md, ws=ws)
    assert _ids(report[0]) == {"S1", "S3", "N11"} and {"S5", "S8"} <= _ids(report[1])
    os.remove(os.path.join(saved.story_dir, "plan.json"))
    capsys.readouterr()
    assert se.recheck(saved._replace(panels=4), ltx_movie._validate_story_md) == (2, [])
    err = capsys.readouterr().err
    assert "  - story: S1 panel count: expected exactly 4 panels, found 3\n" in err
    assert " S3 fields: " in err and " S5 " not in err and " S8 " not in err

    def plan_classes(mutate, mode="chained"):
        ctx = seu.make_ctx(se, ws, mode=mode, panels=3)
        raw = seu.plan_json(mode, 3)
        mutate(raw)
        plan, shape = se.normalize_plan(ctx, raw)
        return se.plan_checks(ctx, plan, shape)

    seu.ronin(story_env["lib"])
    for mutate, rule, mode in (
            (lambda raw: raw["locations"][0].update(setting="A rainy harbour town in modern Japan, "
                                                            "wet cobblestones underfoot, boats "
                                                            "behind, under grey light."), "P4",
             "chained"),
            (lambda raw: raw["beats"][1].update(arc="middle"), "P5", "chained"),
            (lambda raw: raw["beats"][2].update(shot="aerial shot"), "P7", "chained"),
            (lambda raw: raw["beats"][2].update(camera="zoom"), "P8", "chained"),
            (lambda raw: raw["cast"][1].update(phrase="the very old bald monk"), "P3", "chained"),
            (lambda raw: raw["cast"][1].update(descriptor="an old man"), "P3", "chained"),
            (lambda raw: raw["cast"][1].update(phrase="the ronin"), "P13", "chained"),
            (lambda raw: (raw["cast"].append({"id": "c3", "phrase": "the guard",
                                              "descriptor": seu.MONK}),
                          raw["beats"][1].update(cast=["c1", "c2", "c3"])), "P9", "shots")):
        hard, advisory = plan_classes(mutate, mode)
        assert hard == [] and _only(advisory, rule), (rule, hard, advisory)
    for phrase in ("The Courier", "the monk!"):
        hard, advisory = plan_classes(lambda raw: raw["cast"][1].update(phrase=phrase))
        assert _only(hard, "P3") and not _only(advisory, "P3"), phrase
    files = str(tmp_path / "files")
    entries = [seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style"),
               seu.catalog_entry(seu.lora_file(files, "big"), "big-style", kind="style"),
               seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion"),
               seu.catalog_entry(seu.lora_file(files, "rain"), "rain-physics", kind="physics")]
    lctx = seu.make_ctx(se, ws, catalog={"schema_version": 1, "entries": entries})

    def lora(loras, ctx=lctx):
        raw = seu.plan_json("chained", 3)
        raw["loras"] = dict({"global": [], "per_beat": {}, "stills": []}, **loras)
        plan, _shape = se.normalize_plan(ctx, raw)
        compatible = dict((e["id"], e) for e in se.compatible_entries(ctx))
        return se.lora_checks(ctx, plan, compatible, dict((e["id"], e) for e in entries))

    def pick(entry_id, strength=0.8):
        return {"id": entry_id, "strength": strength}

    assert lora({"global": [pick("fast-motion", 2.5)]}) == ([
        "plan: L5 strength: 'fast-motion' strength 2.5 is outside (0, 2], which the renderer "
        "refuses"], [])
    assert lora({"global": [pick("fast-motion", 1.4)]}) == ([], [
        "plan: L5 strength: 'fast-motion' strength 1.4 is outside its range 0.5 to 1.0"])
    for loras, rule, ctx in (
            ({"global": [pick("film-grain"), pick("big-style")]}, "L2", lctx),
            ({"per_beat": {"2": [pick("film-grain")]}}, "L2", lctx),
            ({"global": [pick("fast-motion")], "per_beat": {"2": [pick("rain-physics")]}}, "L3",
             lctx),
            ({"global": [pick("film-grain")], "per_beat": {"2": [pick("fast-motion")]}}, "L4",
             lctx._replace(pinned=[{"path": "/p/%d.safetensors" % i, "strength": 1.0,
                                    "catalog_id": None, "kind": None} for i in (1, 2, 3)]))):
        hard, advisory = lora(loras, ctx)
        assert hard == [] and _only(advisory, rule), (rule, hard, advisory)
    assert lora({"global": [pick("nope")]}) == (["plan: L1 catalog id: 'nope' is not in the "
                                                 "catalog"], [])
    rain = dict((e["id"], e["path"]) for e in entries)["rain-physics"]
    hard, _advisory = lora({"global": [pick("rain-physics")]}, lctx._replace(pinned=[
        {"path": rain, "strength": 1.0, "catalog_id": "rain-physics", "kind": "physics"}]))
    assert _only(hard, "L6")
    assert _only(lora({"stills": [pick("nope"), pick("nope-two")]})[0], "L7")


def test_dlg21_an_advisory_only_round_0_passes_untouched(tmp_path, monkeypatch, capsys):
    ws = seu.make_ws(tmp_path)
    monkeypatch.setattr(ltx_movie, "WS", ws)
    monkeypatch.setattr(ltx_movie, "_check_sudo_and_start_keepalive", lambda: None)
    camera = ("The courier pedals forward along the road as the camera slowly pans left past the "
              "boats.")
    quote = 'The courier reads the "urgent" note and pedals on toward the end of the quay.'
    cases = (("chained", [], {2: [{"motion": camera}], 3: [{"motion": quote}]},
              "panel 3: N7 dialogue and text: Motion: contains a double quote"),
             ("shots", ["--shots"], {2: [{"motion": STRIKE}]},
              "panel 2: S8 contact: Motion: 'strikes' acts on 'the old monk'; two people touching "
              "on screen"))
    for mode, flags, overrides, advisory in cases:
        raw = seu.plan_json(mode, 3)
        if mode == "shots":
            _two_people(raw)
        story_id = "d21-" + mode
        log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(raw)],
                               panel=_replies(mode, 3, overrides))
        rc = ltx_movie.main([NARRATIVE, "--story-id", story_id, "--panels", "3", "--story-only",
                             "--no-review"] + flags)
        out = capsys.readouterr().out
        assert rc == 0, mode
        assert [r["stage"] for r in seu.agent_log(log)] == ["plan", "panel", "panel", "panel"]
        story_dir = os.path.join(ws, "generated", "stories", story_id)
        with open(os.path.join(story_dir, "story.md"), "rb") as f:
            final = f.read()
        with open(os.path.join(story_dir, "story_rounds", "round_0", "story.md"), "rb") as f:
            assert f.read() == final, mode
        checks = _read_json(os.path.join(story_dir, "story_checks.json"))
        assert (checks["stop_reason"], checks["hard"], checks["unresolved"]) == ("passed", [], [])
        assert "Warning: " + advisory + "\n" in out, mode
        assert " N3 " not in out


def test_dlg25_recheck_blocks_only_on_blocking_violations(ws, monkeypatch, capsys, story_env):
    validate = ltx_movie._validate_story_md
    ctx, _text = _saved(ws, monkeypatch, story_id="r1", replies={2: {"motion": BUSY}})
    capsys.readouterr()
    assert se.recheck(ctx, validate)[0] == 0
    assert ("Warning: unresolved: " + T2_MESSAGE + "\n") in capsys.readouterr().out
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert checks["hard"] == [] and _ids(checks["unresolved"]) == {"T2"}
    ctx, _text = _saved(ws, monkeypatch, story_id="r2", plan_mut=_speaking(2),
                        replies={2: {"dialogue": OVER_CAP}})
    assert se.recheck(ctx, validate)[0] == 2
    assert " T1 spoken timing: Dialogue: is 15 words" in capsys.readouterr().err
    ctx, _text = _saved(ws, monkeypatch, story_id="r3", plan_mut=_speaking(2),
                        replies={2: {"dialogue": "Keep moving."}})
    _edit(ctx, "Dialogue: the courier: Keep moving.", "Dialogue: the stranger: Halt.")
    assert se.recheck(ctx, validate)[0] == 2
    assert ("  - panel 2: N18 dialogue: Dialogue: names 'the stranger', which is no character's "
            "referring phrase; use one of: 'the courier', 'the old monk'\n") in (
        capsys.readouterr().err)
    seu.ronin(story_env["lib"])
    ctx, _text = _saved(ws, monkeypatch, story_id="r4")
    os.remove(os.path.join(ctx.story_dir, "plan.json"))
    _edit(ctx, "Narration: The rain had not stopped since dawn.\n",
          "Narration: The ronin watched the rain.\n")
    assert se.recheck(ctx, validate) == (0, [])
    out, err = capsys.readouterr()
    assert err == ""
    assert "Warning: panel 1: N15 undeclared character: Narration: names library character ronin" in out
    ctx, _text = _saved(ws, monkeypatch, "shots", story_id="r5", plan_mut=_two_people,
                        replies={2: {"motion": STRIKE}})
    os.remove(os.path.join(ctx.story_dir, "plan.json"))
    rc, advisories = se.recheck(ctx, validate)
    assert rc == 0 and ("panel 2: S8 contact: Motion: 'strikes' acts on 'the old monk'; two "
                        "people touching on screen") in advisories
    assert se.recheck(ctx._replace(panels=4), validate) == (2, [])
    assert "  - story: S1 panel count: expected exactly 4 panels, found 3\n" in (
        capsys.readouterr().err)
```

**1.2.** Edit `tests/test_story_engine.py`: replace the whole of `test_rst15_lora_checks`, this text, which occurs exactly once:

```python
def test_rst15_lora_checks(ws, tmp_path, story_env):
    ctx = _lora_ctx(ws, tmp_path)
    paths = {e["id"]: e["path"] for e in ctx.catalog["entries"]}
    model = seu.VIDEO_MODEL

    def pick(entry_id, strength=0.8):
        return {"id": entry_id, "strength": strength}

    def lv(loras, **kw):
        return _lora_violations(kw.pop("ctx", ctx), loras, **kw)

    assert lv({"global": [pick("film-grain"), pick("fast-motion")],
               "per_beat": {"2": [pick("rain-physics")]}, "stills": [pick("ink-stills")]}) == (
        ["beat 2: L3 motion: 2 motion or physics LoRAs on this panel (fast-motion, "
         "rain-physics); at most 1"], [])
    assert lv({"global": [pick("film-grain")], "per_beat": {"2": [pick("rain-physics")]},
               "stills": [pick("ink-stills")]}) == ([], [])
    cases = [
        ({"global": [pick("nope")]}, ["plan: L1 catalog id: 'nope' is not in the catalog"]),
        ({"global": [pick("other-model")]},
         ["plan: L1 catalog id: 'other-model' does not support model %s" % model]),
        ({"global": [pick("ink-stills")]},
         ["plan: L1 catalog id: 'ink-stills' is a stills LoRA; global and per-beat picks must "
          "be video LoRAs"]),
        ({"stills": [pick("fast-motion")]},
         ["plan: L1 catalog id: 'fast-motion' is a video LoRA; a stills pick must be a stills "
          "LoRA"]),
        ({"per_beat": {"9": [pick("fast-motion")]}},
         ["plan: L1 catalog id: per_beat key '9' is not a beat number from 1 to 3"]),
        ({"per_beat": {"2": [{"id": "fast-motion", "strength": "high"}]}},
         ['beat 2: L1 catalog id: pick {"id": "fast-motion", "strength": "high"} is not an '
          'object with an id and a numeric strength']),
        ({"global": [pick("film-grain"), pick("big-style")]},
         ["plan: L2 style: 2 style LoRAs for every panel (film-grain, big-style); at most 1"]),
        ({"per_beat": {"2": [pick("film-grain")]}},
         ["beat 2: L2 style: style LoRA 'film-grain' can only be a global pick"]),
        ({"global": [pick("fast-motion", 1.4)]},
         ["plan: L5 strength: 'fast-motion' strength 1.4 is outside its range 0.5 to 1.0"]),
        ({"stills": [pick("ink-stills"), pick("ink-stills")]},
         ["plan: L7 stills: 2 stills LoRAs; at most 1"]),
    ]
    for loras, expected in cases:
        full = {"global": [], "per_beat": {}, "stills": []}
        full.update(loras)
        assert lv(full) == (expected, []), expected
    pins3 = _pins(("/p/1.safetensors", 1.0, None, None), ("/p/2.safetensors", 1.0, None, None),
                  ("/p/3.safetensors", 1.0, None, None))
    assert lv({"global": [pick("film-grain")], "per_beat": {"2": [pick("fast-motion")]}},
              ctx=ctx._replace(pinned=pins3)) == (
        ["beat 2: L4 LoRA count: 5 LoRAs on this panel (pinned LoRA, pinned LoRA, pinned LoRA, "
         "film-grain, fast-motion); at most 4"], [])
    members = _cast_members(story_env, "kyra", "ronin")
    cast_ctx = ctx._replace(pinned=pins3, members=members, mode="shots")
    fixed = [{"id": "c1", "phrase": "the woman in grey", "descriptor": seu.DESC_K},
             {"id": "c2", "phrase": "the ronin", "descriptor": seu.DESC_R}]
    assert lv({}, ctx=cast_ctx, cast=fixed, beat_cast=["c1", "c2"]) == (
        [], ["beat 1: L4 LoRA count: 5 LoRAs on this panel (pinned LoRA, pinned LoRA, pinned "
             "LoRA, character kyra, character ronin); at most 4"])
    dup_pin = _pins((paths["rain-physics"], 1.0, "rain-physics", "physics"))
    hard, _ = lv({"global": [pick("rain-physics")]}, ctx=ctx._replace(pinned=dup_pin))
    assert "beat 1: L6 duplicate: 'rain-physics' is applied twice on this panel" in hard
    assert sum("L6" in h for h in hard) == 1
    hard, _ = lv({"stills": [pick("ink-stills")]}, ctx=ctx._replace(mode="no_stills"))
    assert hard == ["plan: L1 catalog id: 'ink-stills' is not in the catalog",
                    "plan: L7 stills: this movie has no stills; stills must be empty"]
    assert lv({"stills": [pick("ink-stills")]},
              ctx=ctx._replace(stills_pinned=[os.path.realpath(paths["ink-stills"])])) == (
        ["plan: L7 stills: 'ink-stills' is also passed with --stills-lora"], [])
    style_pin = _pins((paths["big-style"], 1.9, "big-style", "style"))
    assert lv({"global": [pick("film-grain")]}, ctx=ctx._replace(pinned=style_pin)) == (
        ["plan: L2 style: 2 style LoRAs for every panel (big-style, film-grain); at most 1"], [])
    assert lv({}, ctx=ctx._replace(pinned=style_pin)) == ([], [])
    off = ctx._replace(auto_lora=False)
    assert lv({"global": [pick("nope")]}, ctx=off) == ([], [])
```

with:

```python
def test_rst15_lora_checks(ws, tmp_path, story_env):
    # L1, L6, L7 and an L5 strength outside (0, 2] are hard; L2-L4 and an L5 strength outside
    # the entry's range are advisory (dialogue spec 6.3, Q4).
    ctx = _lora_ctx(ws, tmp_path)
    paths = {e["id"]: e["path"] for e in ctx.catalog["entries"]}
    model = seu.VIDEO_MODEL

    def pick(entry_id, strength=0.8):
        return {"id": entry_id, "strength": strength}

    def lv(loras, **kw):
        return _lora_violations(kw.pop("ctx", ctx), loras, **kw)

    assert lv({"global": [pick("film-grain"), pick("fast-motion")],
               "per_beat": {"2": [pick("rain-physics")]}, "stills": [pick("ink-stills")]}) == (
        [], ["beat 2: L3 motion: 2 motion or physics LoRAs on this panel (fast-motion, "
             "rain-physics); at most 1"])
    assert lv({"global": [pick("film-grain")], "per_beat": {"2": [pick("rain-physics")]},
               "stills": [pick("ink-stills")]}) == ([], [])
    cases = [
        ({"global": [pick("nope")]}, ["plan: L1 catalog id: 'nope' is not in the catalog"], []),
        ({"global": [pick("other-model")]},
         ["plan: L1 catalog id: 'other-model' does not support model %s" % model], []),
        ({"global": [pick("ink-stills")]},
         ["plan: L1 catalog id: 'ink-stills' is a stills LoRA; global and per-beat picks must "
          "be video LoRAs"], []),
        ({"stills": [pick("fast-motion")]},
         ["plan: L1 catalog id: 'fast-motion' is a video LoRA; a stills pick must be a stills "
          "LoRA"], []),
        ({"per_beat": {"9": [pick("fast-motion")]}},
         ["plan: L1 catalog id: per_beat key '9' is not a beat number from 1 to 3"], []),
        ({"per_beat": {"2": [{"id": "fast-motion", "strength": "high"}]}},
         ['beat 2: L1 catalog id: pick {"id": "fast-motion", "strength": "high"} is not an '
          'object with an id and a numeric strength'], []),
        ({"global": [pick("film-grain"), pick("big-style")]}, [],
         ["plan: L2 style: 2 style LoRAs for every panel (film-grain, big-style); at most 1"]),
        ({"per_beat": {"2": [pick("film-grain")]}}, [],
         ["beat 2: L2 style: style LoRA 'film-grain' can only be a global pick"]),
        ({"global": [pick("fast-motion", 1.4)]}, [],
         ["plan: L5 strength: 'fast-motion' strength 1.4 is outside its range 0.5 to 1.0"]),
        ({"global": [pick("fast-motion", 2.5)]},
         ["plan: L5 strength: 'fast-motion' strength 2.5 is outside (0, 2], which the renderer "
          "refuses"], []),
        ({"stills": [pick("ink-stills"), pick("ink-stills")]},
         ["plan: L7 stills: 2 stills LoRAs; at most 1"], []),
    ]
    for loras, hard, advisory in cases:
        full = {"global": [], "per_beat": {}, "stills": []}
        full.update(loras)
        assert lv(full) == (hard, advisory), (hard, advisory)
    pins3 = _pins(("/p/1.safetensors", 1.0, None, None), ("/p/2.safetensors", 1.0, None, None),
                  ("/p/3.safetensors", 1.0, None, None))
    assert lv({"global": [pick("film-grain")], "per_beat": {"2": [pick("fast-motion")]}},
              ctx=ctx._replace(pinned=pins3)) == (
        [], ["beat 2: L4 LoRA count: 5 LoRAs on this panel (pinned LoRA, pinned LoRA, pinned LoRA, "
             "film-grain, fast-motion); at most 4"])
    members = _cast_members(story_env, "kyra", "ronin")
    cast_ctx = ctx._replace(pinned=pins3, members=members, mode="shots")
    fixed = [{"id": "c1", "phrase": "the woman in grey", "descriptor": seu.DESC_K},
             {"id": "c2", "phrase": "the ronin", "descriptor": seu.DESC_R}]
    assert lv({}, ctx=cast_ctx, cast=fixed, beat_cast=["c1", "c2"]) == (
        [], ["beat 1: L4 LoRA count: 5 LoRAs on this panel (pinned LoRA, pinned LoRA, pinned "
             "LoRA, character kyra, character ronin); at most 4"])
    dup_pin = _pins((paths["rain-physics"], 1.0, "rain-physics", "physics"))
    hard, _ = lv({"global": [pick("rain-physics")]}, ctx=ctx._replace(pinned=dup_pin))
    assert "beat 1: L6 duplicate: 'rain-physics' is applied twice on this panel" in hard
    assert sum("L6" in h for h in hard) == 1
    hard, _ = lv({"stills": [pick("ink-stills")]}, ctx=ctx._replace(mode="no_stills"))
    assert hard == ["plan: L1 catalog id: 'ink-stills' is not in the catalog",
                    "plan: L7 stills: this movie has no stills; stills must be empty"]
    assert lv({"stills": [pick("ink-stills")]},
              ctx=ctx._replace(stills_pinned=[os.path.realpath(paths["ink-stills"])])) == (
        ["plan: L7 stills: 'ink-stills' is also passed with --stills-lora"], [])
    style_pin = _pins((paths["big-style"], 1.9, "big-style", "style"))
    assert lv({"global": [pick("film-grain")]}, ctx=ctx._replace(pinned=style_pin)) == (
        [], ["plan: L2 style: 2 style LoRAs for every panel (big-style, film-grain); at most 1"])
    assert lv({}, ctx=ctx._replace(pinned=style_pin)) == ([], [])
    off = ctx._replace(auto_lora=False)
    assert lv({"global": [pick("nope")]}, ctx=off) == ([], [])
```

**1.3.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    assert se._field_checks(ctx, lib, plan, 1, "T", fields, {}, ("N5", "N6"), []) == (
        ["panel 1: N5 setting sentence: Image: lacks l1's setting sentence word for word",
         "panel 1: N6 description: Image: lacks c1's description word for word"], [])
```

with:

```python
    assert se._field_checks(ctx, lib, plan, 1, "T", fields, {}, ("N5", "N6"), []) == ([], [
        "panel 1: N5 setting sentence: Image: lacks l1's setting sentence word for word",
        "panel 1: N6 description: Image: lacks c1's description word for word"])
```

**1.4.** Edit `tests/test_story_engine.py`: replace (in `test_rst20c_narration_modes`) this text, which occurs exactly once:

```python
        path, panels, no_stills, no_narration=True)) == (2, [])
    assert "  - %s\n" % voice_over in capsys.readouterr().err
```

with:

```python
        path, panels, no_stills, no_narration=True)) == (0, [voice_over])
    assert capsys.readouterr().err == ""
```

**1.5.** Edit `tests/test_story_engine.py`: replace the whole of `test_rst44_recheck_with_plan`, this text, which occurs exactly once:

```python
def test_rst44_recheck_with_plan(ws, monkeypatch, tmp_path, capsys):
    log = seu.script_agent(monkeypatch, tmp_path)
    ctx, text = _saved_story(ws, monkeypatch)
    assert se.recheck(ctx, ltx_movie._validate_story_md) == (0, [])
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert (checks["source"], checks["round"], checks["stop_reason"], checks["rounds"],
            checks["hard"]) == ("recheck", None, None, [], [])
    motion = seu.panel_json("chained", 2)["motion"]
    _edit_story(ctx, "Motion: " + motion, "Motion: The courier yells " + motion[12:])
    story_md = os.path.join(ctx.story_dir, "story.md")
    assert se.recheck(ctx, ltx_movie._validate_story_md) == (2, [])
    assert capsys.readouterr().err == (
        "Error: story.md fails the story checks:\n"
        "  - panel 2: N7 dialogue and text: Motion: says 'yells'\n"
        "Hand-edit %s to fix the violations above and rerun, or pass --force-story to "
        "regenerate it.\n" % story_md)
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert checks["source"] == "recheck" and [h["id"] for h in checks["hard"]] == ["N7"]
    assert seu.agent_log(log) == []
    _edit_story(ctx, "Narration: Every street led down to the water.\n", "Narration:\n")
    se.recheck(ctx, ltx_movie._validate_story_md)
    hard = [h["message"] for h in _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["hard"]]
    assert hard == ["panel 2: missing/empty Narration: field",
                    "panel 2: N7 dialogue and text: Motion: says 'yells'",
                    "panel 2: N11 narration: Narration: is empty"]
```

with:

```python
def test_rst44_recheck_with_plan(ws, monkeypatch, tmp_path, capsys):
    log = seu.script_agent(monkeypatch, tmp_path)
    ctx, text = _saved_story(ws, monkeypatch)
    assert se.recheck(ctx, ltx_movie._validate_story_md) == (0, [])
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert (checks["source"], checks["round"], checks["stop_reason"], checks["rounds"],
            checks["hard"], checks["unresolved"]) == ("recheck", None, None, [], [], [])
    motion = seu.panel_json("chained", 2)["motion"]
    _edit_story(ctx, "Motion: " + motion, "Motion: The courier yells " + motion[12:])
    story_md = os.path.join(ctx.story_dir, "story.md")
    assert se.recheck(ctx, ltx_movie._validate_story_md) == (
        0, ["panel 2: N7 dialogue and text: Motion: says 'yells'"])
    assert capsys.readouterr().err == ""
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert checks["source"] == "recheck" and checks["hard"] == []
    assert [a["id"] for a in checks["advisory"]] == ["N7"]
    assert seu.agent_log(log) == []
    _edit_story(ctx, "Narration: Every street led down to the water.\n", "Narration:\n")
    assert se.recheck(ctx, ltx_movie._validate_story_md)[0] == 2
    assert capsys.readouterr().err == (
        "Error: story.md fails the story checks:\n"
        "  - panel 2: missing/empty Narration: field\n"
        "  - panel 2: N11 narration: Narration: is empty\n"
        "Hand-edit %s to fix the violations above and rerun, or pass --force-story to "
        "regenerate it.\n" % story_md)
    hard = [h["message"] for h in _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["hard"]]
    assert hard == ["panel 2: missing/empty Narration: field",
                    "panel 2: N11 narration: Narration: is empty"]
```

**1.6.** Edit `tests/test_story_engine.py`: replace (in `test_rst45_recheck_without_plan`) this text, which occurs exactly once:

```python
    assert se.recheck(shots, ltx_movie._validate_story_md) == (2, [])
    err = capsys.readouterr().err
    assert err.startswith("Error: story.md breaks the shot rules:\n")
    assert "  - panel 3: S5 one action: Motion: chains actions with 'then'\n" in err
    assert err.endswith("Hand-edit %s to fix the violations above and rerun, or pass "
                        "--force-story to have the story model write a new one.\n"
                        % os.path.join(shots.story_dir, "story.md"))
```

with:

```python
    rc, advisories = se.recheck(shots, ltx_movie._validate_story_md)
    assert rc == 0 and advisories[0] == "panel 3: S5 one action: Motion: chains actions with 'then'"
    assert "breaks the shot rules" not in capsys.readouterr().err
```

**1.7.** Edit `tests/test_story_engine.py`: replace (in `test_rst56b_n15_in_recheck_and_plan_free_report`) this text, which occurs exactly once:

```python
    assert se.recheck(ctx, ltx_movie._validate_story_md)[0] == 2
    message = ("panel 3: N15 undeclared character: Narration: names library character ronin by "
               "its name 'Ronin'; library characters appear only when declared with --character "
               "ronin")
    assert "  - %s\n" % message in capsys.readouterr().err
    story_md = os.path.join(ctx.story_dir, "story.md")
    assert se.plan_free_report(story_md, "shots", 3, [], ltx_movie._validate_story_md,
                               ws=ws) == [message]
    members = se._character_lib(WS).resolve_cast([(None, "ronin")])
    report = se.plan_free_report(story_md, "shots", 3, members, ltx_movie._validate_story_md, ws=ws)
    assert message not in report
    chained, _t = _saved_story(ws, monkeypatch, ctx_kw={"story_id": "s7"})
    path = os.path.join(chained.story_dir, "story.md")
    assert se.plan_free_report(path, "chained", 3, [], ltx_movie._validate_story_md, ws=ws) == []
    assert se.plan_free_report(path, "chained", 4, [], ltx_movie._validate_story_md, ws=ws) == [
        "expected exactly 4 panels, found 3"]
```

with:

```python
    rc, advisories = se.recheck(ctx, ltx_movie._validate_story_md)
    message = ("panel 3: N15 undeclared character: Narration: names library character ronin by "
               "its name 'Ronin'; library characters appear only when declared with --character "
               "ronin")
    assert rc == 0 and message in advisories
    assert message not in capsys.readouterr().err
    story_md = os.path.join(ctx.story_dir, "story.md")
    assert se.plan_free_report(story_md, "shots", 3, [], ltx_movie._validate_story_md,
                               ws=ws) == ([], [message])
    members = se._character_lib(WS).resolve_cast([(None, "ronin")])
    report = se.plan_free_report(story_md, "shots", 3, members, ltx_movie._validate_story_md, ws=ws)
    assert message not in report[0] + report[1]
    chained, _t = _saved_story(ws, monkeypatch, ctx_kw={"story_id": "s7"})
    path = os.path.join(chained.story_dir, "story.md")
    assert se.plan_free_report(path, "chained", 3, [], ltx_movie._validate_story_md,
                               ws=ws) == ([], [])
    assert se.plan_free_report(path, "chained", 4, [], ltx_movie._validate_story_md,
                               ws=ws) == (["expected exactly 4 panels, found 3"], [])
```

**1.8.** Edit `tests/test_story_engine.py`: replace (in `test_rst44b_recheck_stale_plan_cast_does_not_mask`) this text, which occurs exactly once:

```python
    assert se.recheck(ctx, ltx_movie._validate_story_md)[0] == 2
    assert " N15 " in capsys.readouterr().err
```

with:

```python
    rc, advisories = se.recheck(ctx, ltx_movie._validate_story_md)
    assert rc == 0 and [a for a in advisories if " N15 " in a]
    assert " N15 " not in capsys.readouterr().err
```

**1.9.** Edit `tests/test_story_engine.py`: replace (in `test_rst44d_recheck_no_plan_enforces_n15`) this text, which occurs exactly once:

```python
    assert se.recheck(ctx, ltx_movie._validate_story_md) == (2, [])
    err = capsys.readouterr().err
    assert " N15 " in err
    assert err.endswith("ltx-movie: story.md names library characters that were not declared "
                        "with --character; fix story.md and re-run\n")
```

with:

```python
    assert se.recheck(ctx, ltx_movie._validate_story_md) == (0, [])
    out, err = capsys.readouterr()
    assert err == ""
    assert ("Warning: panel 1: N15 undeclared character: Narration: names library character "
            "ronin") in out
```

**1.10.** Edit `tests/test_story_engine.py`: replace (in `test_rst44e_recheck_judges_writer_text_like_generation`) this text, which occurs exactly once:

```python
    assert se.recheck(ctx, ltx_movie._validate_story_md)[0] == 2
    assert "  - panel 2: N7 dialogue and text: Motion: says 'yells'\n" in capsys.readouterr().err
```

with:

```python
    rc, advisories = se.recheck(ctx, ltx_movie._validate_story_md)
    assert rc == 0 and "panel 2: N7 dialogue and text: Motion: says 'yells'" in advisories
```

**1.11.** Edit `tests/test_story_engine.py`: replace the whole of `test_rst55b_p13_forces_plan_call_2`, this text, which occurs exactly once:

```python
def test_rst55b_p13_forces_plan_call_2(ws, tmp_path, monkeypatch, story_env):
    seu.ronin(story_env["lib"])
    bad = seu.plan_json("chained", 3)
    bad["cast"][1]["phrase"] = "the ronin"
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, plan=[
        seu.answer(bad), seu.answer(seu.plan_json("chained", 3))],
        critic=[seu.answer(seu.critic_json())])
    assert rc == 0 and [r["stage"] for r in log][:2] == ["plan", "plan"]
    assert ("- plan: P13 undeclared character: c2's phrase names library character ronin by its "
            "referring phrase 'the ronin'") in log[1]["argv"][-1]
```

with:

```python
def test_rst55b_p13_forces_plan_call_2(ws, tmp_path, monkeypatch, story_env):
    # P13 is advisory (dialogue spec Q1): the plan is used as written, with the P13 advisory.
    seu.ronin(story_env["lib"])
    bad = seu.plan_json("chained", 3)
    bad["cast"][1]["phrase"] = "the ronin"
    rc, advisories, ctx, log = _run(ws, tmp_path, monkeypatch, plan=[seu.answer(bad)])
    assert rc == 0 and [r["stage"] for r in log][:2] == ["plan", "panel"]
    assert ("plan: P13 undeclared character: c2's phrase names library character ronin by its "
            "referring phrase 'the ronin'; " + _p13()) in advisories
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k "dlg18 or dlg21 or dlg25" 2>&1 | tail -3
python3 -m pytest -q -p no:cacheprovider tests/test_story_engine.py -k "rst15 or rst20 or rst44 or rst45 or rst55b or rst56b" 2>&1 | tail -3
```

Expected: `3 failed` (the N, S, P and L messages are still hard; the T2-only re-check exits 2), then failures in every test edited above.

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace the whole of `_field_checks`, this text, which occurs exactly once:

```python
def _field_checks(ctx, lib, plan, k, title, fields, writers, ids, undeclared):
    """(hard, advisory) of one panel: the RS15 checks named in ids, plus N15 when in ids.
    fields: [(Label, assembled text)]; writers: {Label: writer text}; plan may be None (then
    every check that needs the plan is skipped)."""
    hard, advisory = [], []
    beat = plan["beats"][k - 1] if plan and k <= len(plan["beats"]) else None
    phrases = _valid_phrases(lib, plan) if plan else {}
    by_cast = {c["id"]: c for c in plan["cast"]} if plan else {}
    by_location = {l["id"]: l for l in plan["locations"]} if plan else {}
    prefix = "panel %d:" % k

    def add(target, check, name, label, detail):
        target.append("%s %s %s: %s: %s" % (prefix, check, name, label, detail))

    action_fields = ("Image", "Motion", "Prompt")
    for label, text in fields:
        writer = writers.get(label, "")
        key = label.lower()
        if "N1" in ids and label != "Narration" and not (ctx.mode == "shots" and label == "Motion"):
            spec = field_range(ctx, k, key)
            if spec:
                lo, hi = spec[1]
                if outside_range(_words(text), lo, hi):
                    add(advisory, "N1", "word count", label,
                        "is %d words; aim for %d-%d" % (_words(text), lo, hi))
        if ctx.mode == "chained" and k >= 2 and label == "Motion" and plan:
            humans = [p for p in phrases if not lib.is_animal_phrase(p)]
            animals = [p for p in phrases if lib.is_animal_phrase(p)]
            if "N2" in ids:
                for sentence in lib._SENTENCE_SPLIT_RE.split(text.strip()):
                    refs = [r for r in lib._person_refs(sentence, humans, animals, [])
                            if r[2] in lib.SHOTS_PERSON_NOUNS]
                    if refs:
                        add(hard, "N2", "referring phrase", label,
                            "names %s outside every referring phrase; name each character by "
                            "their exact phrase" % _q(refs[0][2]))
                        break
            if "N3" in ids:
                blanked = lib._blank(text, lib._passage_spans(
                    text, list(phrases) + [p["name"] for p in plan["props"] if p["name"]]))
                word = _first(_APPEARANCE_RE, blanked)
                if word:
                    add(hard, "N3", "appearance", label,
                        "says %s; panels after the first never re-describe appearance, clothing, "
                        "setting, lighting, colour or style" % _q(word))
        if "N4" in ids and label not in ("Narration", "Dialogue") and beat is not None:
            for phrase in lib.find_phrases(writer, list(phrases)):
                if phrases[phrase] not in beat["cast"]:
                    add(hard, "N4", "stray cast", label,
                        "names %s, who is not in beat %d's cast" % (_q(phrase), k))
                    break
        pasted_field = ((ctx.mode == "chained" and k == 1 and label == "Image")
                        or (ctx.mode == "shots" and label == "Image")
                        or (ctx.mode == "no_stills" and label == "Prompt"))
        if pasted_field and beat is not None:
            norm = _norm_text(text)
            if "N5" in ids and beat["location"] in by_location:
                own = by_location[beat["location"]]
                if _norm_text(own["setting"]) not in norm:
                    add(hard, "N5", "setting sentence", label,
                        "lacks %s's setting sentence word for word" % own["id"])
                else:
                    for other in plan["locations"]:
                        if (other["id"] != own["id"] and other["setting"]
                                and _norm_text(other["setting"]) != _norm_text(own["setting"])
                                and _norm_text(other["setting"]) in norm):
                            add(hard, "N5", "setting sentence", label,
                                "contains %s's setting sentence; beat %d is at %s"
                                % (other["id"], k, own["id"]))
                            break
            if "N6" in ids:
                for cid in beat["cast"]:
                    entry = by_cast.get(cid)
                    if entry is None or (ctx.mode == "shots" and entry["cast_name"]):
                        continue
                    if _norm_text(entry["descriptor"]) not in norm:
                        add(hard, "N6", "description", label,
                            "lacks %s's description word for word" % cid)
                        break
        if label in action_fields:
            if "N7" in ids:
                if any(q in writer for q in ('"', "“", "”")):
                    add(hard, "N7", "dialogue and text", label, "contains a double quote")
                else:
                    word = _first(DIALOGUE_RE, writer) or _first(ONSCREEN_TEXT_RE, writer)
                    if word:
                        add(hard, "N7", "dialogue and text", label, "says %s" % _q(word))
            if "N8" in ids and ctx.mode != "shots":
                word = _first(lib._OFFSCREEN_RE, writer)
                if word:
                    add(hard, "N8", "off-screen", label,
                        "says %s; describe only what is in the frame" % _q(word))
            if "N9" in ids:
                word = _first(CUT_RE, writer)
                if word:
                    add(hard, "N9", "cut wording", label,
                        "says %s; one panel is one continuous shot" % _q(word))
        if "N10" in ids and label != "Dialogue":
            found = PLACEHOLDER_RE.search(writer)
            copied = found.group(0) if found else next(
                (ex for ex in COPIED_EXAMPLES if _norm_text(ex) in _norm_text(writer)), None)
            if copied:
                add(hard, "N10", "copied example", label, "contains template text %s" % _q(copied))
        if "N11" in ids and label == "Narration" and not text.strip() and ctx.narration is True:
            hard.append("%s N11 narration: Narration: is empty" % prefix)
    if "N15" in ids and undeclared:
        masks = _undeclared_masks(lib, ctx, plan, undeclared)
        for label, text in [("Title", title)] + list(fields):
            for hit in undeclared_references(lib, text, undeclared, masks=masks):
                hard.append(undeclared_message("%s N15 undeclared character:" % prefix,
                                               label + ":", hit))
    known = cast_phrases(ctx, plan)
    dialogue = dict(fields).get("Dialogue", "")
    if dialogue.strip():
        _phrase, line, problem = lib.parse_dialogue(dialogue, known)
        if problem:
            if "N18" in ids:
                hard.append("%s N18 dialogue: Dialogue: %s" % (prefix, problem))
        elif "T1" in ids:
            detail = over_cap(ctx, lib, line)
            if detail:
                hard.append("%s T1 spoken timing: Dialogue: is %s" % (prefix, detail))
    elif "T1" in ids:
        spoken = dict(fields).get("Narration", "")
        speaker, speech = lib.split_speaker(spoken, known) if ":" in spoken else (None, "")
        detail = over_cap(ctx, lib, speech) if speaker else None
        if detail:
            advisory.append("%s T1 spoken timing: Narration: speaks %s" % (prefix, detail))
    action_label = "Prompt" if ctx.mode == "no_stills" else "Motion"
    if ("T2" in ids or "T3" in ids) and action_label in dict(fields):
        actions, units, most = action_units(ctx, lib, writers.get(action_label, ""), known)
        if actions == 0:
            if "T2" in ids:
                hard.append("%s T2 action amount: %s: has no physical action; a %s-second clip "
                            "needs one, so add one action sentence and keep every other sentence "
                            "word for word" % (prefix, action_label, ctx.seconds))
        elif units > 2 * most:
            if "T3" in ids:
                hard.append("%s T3 action overload: %s: holds %d actions; a %s-second clip fits at "
                            "most %d and cannot render more than %d; give the extra actions their "
                            "own panels" % (prefix, action_label, units, ctx.seconds, most,
                                            2 * most))
        elif units > most:
            if "T2" in ids:
                hard.append("%s T2 action amount: %s: holds %d actions; a %s-second clip fits at "
                            "most %d, so cut the extra actions and keep every other sentence word "
                            "for word" % (prefix, action_label, units, ctx.seconds, most))
    if "N12" in ids and ctx.mode == "chained":
        writer = writers.get("Motion", "")
        chain = _first(lib._CHAIN_WORD_RE, writer)
        if chain is None and ";" in writer:
            chain = ";"
        if chain is None and lib._COMMA_AND_RE.search(writer):
            chain = ", and"
        if chain:
            add(advisory, "N12", "one action", "Motion", "chains actions with %s" % _q(chain))
    narration = dict(fields).get("Narration", "")
    on_screen = ([by_cast[c]["phrase"] for c in beat["cast"] if c in by_cast]
                 if beat is not None else [])
    spoken_by = lib.parse_dialogue(dialogue, known)[0] if dialogue.strip() else None
    if "N16" in ids and beat is not None:
        found = lib.speaker_prefix(narration)
        speech_only = ctx.narration == "speech"
        if spoken_by is not None:
            if spoken_by.lower() not in [p.lower() for p in on_screen]:
                add(advisory, "N16", "speaker", "Dialogue",
                    "is spoken by %s, who is not in this shot; put %s in the shot or move the "
                    "line to a panel that shows them" % (_q(spoken_by), _q(spoken_by)))
        elif speech_only and narration.strip() and (
                not found or lib.split_speaker(narration, known)[0] is None):
            add(hard, "N16", "speaker", "Narration",
                "is voice-over, but this story is speech-only; start it with the referring "
                "phrase of the character in the shot who says it and a colon, or leave it empty")
        elif found:
            if lib.split_speaker(narration, on_screen)[0] is not None:
                pass
            elif lib.split_speaker(narration, known)[0] is not None:
                add(hard, "N16", "speaker", "Narration",
                    "is spoken by %s, who is not in this shot; only a character on screen can "
                    "speak, so make it voice-over (no prefix) or put %s in the shot"
                    % (_q(found[0]), _q(found[0])))
            else:
                add(advisory, "N16", "speaker", "Narration",
                    "starts with %s, which is no character's referring phrase, so it is read as "
                    "voice-over; start a spoken line with the speaker's referring phrase, or drop "
                    "the colon" % _q(found[0] + ":"))
    if "N17" in ids and beat is not None:
        if spoken_by is not None:
            speech_label = "Dialogue"
            speaker = (spoken_by if spoken_by.lower() in [p.lower() for p in on_screen] else None)
        else:
            speech_label = "Narration"
            speaker = lib.split_speaker(narration, on_screen)[0] if narration.strip() else None
        if speaker:
            shot_applies = ctx.mode != "chained" or k == 1
            if shot_applies and beat["shot"] in WIDE_SHOTS:
                add(advisory, "N17", "speaking shot", speech_label,
                    "%s speaks in a %s, too small to read the lips, so it plays as voice-over; "
                    "use a medium shot or closer" % (_q(speaker), beat["shot"]))
            held = next((w for w in (_first(HELD_EXPRESSION_RE, writers.get(field, ""))
                                     for field in action_fields) if w), None)
            if held:
                add(advisory, "N17", "speaking shot", speech_label,
                    "%s speaks, but the panel holds the expression %s, which freezes the mouth; "
                    "describe the speaking instead" % (_q(speaker), _q(held)))
            others = [p for p in on_screen if p.lower() != speaker.lower()]
            if speech_label == "Dialogue" and others:
                add(advisory, "N17", "speaking shot", "Dialogue",
                    "%s speaks in a shot that also shows %s; a speaking shot shows only the "
                    "speaker" % (_q(speaker), ", ".join(_q(p) for p in others)))
            for sentence in _sentences(writers.get(action_label, "")):
                move = CAMERA_MOTION_RE.search(sentence)
                if (move and lib._is_camera_sentence(sentence, known)
                        and " ".join(move.group(0).lower().split()) not in STILL_CAMERA_MOVES):
                    add(advisory, "N17", "speaking shot", action_label,
                        "has the camera direction %s while %s speaks; a speaking shot keeps the "
                        "camera static" % (_q(sentence), _q(speaker)))
                    break
    if "N14" in ids:
        if plan:
            narration = lib.split_speaker(narration, [c["phrase"] for c in plan["cast"]])[1]
        if narration.strip():
            sentences = [s for s in lib._SENTENCE_SPLIT_RE.split(narration.strip()) if s.strip()]
            lo, hi = NARRATION_WORDS
            if len(sentences) != 1:
                add(advisory, "N14", "narration form", "Narration",
                    "is %d sentences; it should be one sentence of %d-%d words"
                    % (len(sentences), lo, hi))
            elif not lo <= _words(narration) <= hi:
                add(advisory, "N14", "narration form", "Narration",
                    "is %d words; it should be one sentence of %d-%d words"
                    % (_words(narration), lo, hi))
    return hard, advisory
```

with:

```python
def _field_checks(ctx, lib, plan, k, title, fields, writers, ids, undeclared):
    """(hard, advisory) of one panel: the RS15 checks named in ids, plus N15 when in ids. Hard:
    N11 (Narration: empty with no Dialogue:), N18, T1, T2, T3; every other N rule is advisory
    (dialogue spec 6.3, D6).
    fields: [(Label, assembled text)]; writers: {Label: writer text}; plan may be None (then
    every check that needs the plan is skipped)."""
    hard, advisory = [], []
    beat = plan["beats"][k - 1] if plan and k <= len(plan["beats"]) else None
    phrases = _valid_phrases(lib, plan) if plan else {}
    by_cast = {c["id"]: c for c in plan["cast"]} if plan else {}
    by_location = {l["id"]: l for l in plan["locations"]} if plan else {}
    prefix = "panel %d:" % k

    def add(target, check, name, label, detail):
        target.append("%s %s %s: %s: %s" % (prefix, check, name, label, detail))

    action_fields = ("Image", "Motion", "Prompt")
    for label, text in fields:
        writer = writers.get(label, "")
        key = label.lower()
        if "N1" in ids and label != "Narration" and not (ctx.mode == "shots" and label == "Motion"):
            spec = field_range(ctx, k, key)
            if spec:
                lo, hi = spec[1]
                if outside_range(_words(text), lo, hi):
                    add(advisory, "N1", "word count", label,
                        "is %d words; aim for %d-%d" % (_words(text), lo, hi))
        if ctx.mode == "chained" and k >= 2 and label == "Motion" and plan:
            humans = [p for p in phrases if not lib.is_animal_phrase(p)]
            animals = [p for p in phrases if lib.is_animal_phrase(p)]
            if "N2" in ids:
                for sentence in lib._SENTENCE_SPLIT_RE.split(text.strip()):
                    refs = [r for r in lib._person_refs(sentence, humans, animals, [])
                            if r[2] in lib.SHOTS_PERSON_NOUNS]
                    if refs:
                        add(advisory, "N2", "referring phrase", label,
                            "names %s outside every referring phrase; name each character by "
                            "their exact phrase" % _q(refs[0][2]))
                        break
            if "N3" in ids:
                blanked = lib._blank(text, lib._passage_spans(
                    text, list(phrases) + [p["name"] for p in plan["props"] if p["name"]]))
                word = _first(_APPEARANCE_RE, blanked)
                if word:
                    add(advisory, "N3", "appearance", label,
                        "says %s; panels after the first never re-describe appearance, clothing, "
                        "setting, lighting, colour or style" % _q(word))
        if "N4" in ids and label not in ("Narration", "Dialogue") and beat is not None:
            for phrase in lib.find_phrases(writer, list(phrases)):
                if phrases[phrase] not in beat["cast"]:
                    add(advisory, "N4", "stray cast", label,
                        "names %s, who is not in beat %d's cast" % (_q(phrase), k))
                    break
        pasted_field = ((ctx.mode == "chained" and k == 1 and label == "Image")
                        or (ctx.mode == "shots" and label == "Image")
                        or (ctx.mode == "no_stills" and label == "Prompt"))
        if pasted_field and beat is not None:
            norm = _norm_text(text)
            if "N5" in ids and beat["location"] in by_location:
                own = by_location[beat["location"]]
                if _norm_text(own["setting"]) not in norm:
                    add(advisory, "N5", "setting sentence", label,
                        "lacks %s's setting sentence word for word" % own["id"])
                else:
                    for other in plan["locations"]:
                        if (other["id"] != own["id"] and other["setting"]
                                and _norm_text(other["setting"]) != _norm_text(own["setting"])
                                and _norm_text(other["setting"]) in norm):
                            add(advisory, "N5", "setting sentence", label,
                                "contains %s's setting sentence; beat %d is at %s"
                                % (other["id"], k, own["id"]))
                            break
            if "N6" in ids:
                for cid in beat["cast"]:
                    entry = by_cast.get(cid)
                    if entry is None or (ctx.mode == "shots" and entry["cast_name"]):
                        continue
                    if _norm_text(entry["descriptor"]) not in norm:
                        add(advisory, "N6", "description", label,
                            "lacks %s's description word for word" % cid)
                        break
        if label in action_fields:
            if "N7" in ids:
                if any(q in writer for q in ('"', "“", "”")):
                    add(advisory, "N7", "dialogue and text", label, "contains a double quote")
                else:
                    word = _first(DIALOGUE_RE, writer) or _first(ONSCREEN_TEXT_RE, writer)
                    if word:
                        add(advisory, "N7", "dialogue and text", label, "says %s" % _q(word))
            if "N8" in ids and ctx.mode != "shots":
                word = _first(lib._OFFSCREEN_RE, writer)
                if word:
                    add(advisory, "N8", "off-screen", label,
                        "says %s; describe only what is in the frame" % _q(word))
            if "N9" in ids:
                word = _first(CUT_RE, writer)
                if word:
                    add(advisory, "N9", "cut wording", label,
                        "says %s; one panel is one continuous shot" % _q(word))
        if "N10" in ids and label != "Dialogue":
            found = PLACEHOLDER_RE.search(writer)
            copied = found.group(0) if found else next(
                (ex for ex in COPIED_EXAMPLES if _norm_text(ex) in _norm_text(writer)), None)
            if copied:
                add(advisory, "N10", "copied example", label, "contains template text %s" % _q(copied))
        if ("N11" in ids and label == "Narration" and not text.strip() and ctx.narration is True
                and not dict(fields).get("Dialogue", "").strip()):
            hard.append("%s N11 narration: Narration: is empty" % prefix)
    if "N15" in ids and undeclared:
        masks = _undeclared_masks(lib, ctx, plan, undeclared)
        for label, text in [("Title", title)] + list(fields):
            for hit in undeclared_references(lib, text, undeclared, masks=masks):
                advisory.append(undeclared_message("%s N15 undeclared character:" % prefix,
                                               label + ":", hit))
    known = cast_phrases(ctx, plan)
    dialogue = dict(fields).get("Dialogue", "")
    if dialogue.strip():
        _phrase, line, problem = lib.parse_dialogue(dialogue, known)
        if problem:
            if "N18" in ids:
                hard.append("%s N18 dialogue: Dialogue: %s" % (prefix, problem))
        elif "T1" in ids:
            detail = over_cap(ctx, lib, line)
            if detail:
                hard.append("%s T1 spoken timing: Dialogue: is %s" % (prefix, detail))
    elif "T1" in ids:
        spoken = dict(fields).get("Narration", "")
        speaker, speech = lib.split_speaker(spoken, known) if ":" in spoken else (None, "")
        detail = over_cap(ctx, lib, speech) if speaker else None
        if detail:
            advisory.append("%s T1 spoken timing: Narration: speaks %s" % (prefix, detail))
    action_label = "Prompt" if ctx.mode == "no_stills" else "Motion"
    if ("T2" in ids or "T3" in ids) and action_label in dict(fields):
        actions, units, most = action_units(ctx, lib, writers.get(action_label, ""), known)
        if actions == 0:
            if "T2" in ids:
                hard.append("%s T2 action amount: %s: has no physical action; a %s-second clip "
                            "needs one, so add one action sentence and keep every other sentence "
                            "word for word" % (prefix, action_label, ctx.seconds))
        elif units > 2 * most:
            if "T3" in ids:
                hard.append("%s T3 action overload: %s: holds %d actions; a %s-second clip fits at "
                            "most %d and cannot render more than %d; give the extra actions their "
                            "own panels" % (prefix, action_label, units, ctx.seconds, most,
                                            2 * most))
        elif units > most:
            if "T2" in ids:
                hard.append("%s T2 action amount: %s: holds %d actions; a %s-second clip fits at "
                            "most %d, so cut the extra actions and keep every other sentence word "
                            "for word" % (prefix, action_label, units, ctx.seconds, most))
    if "N12" in ids and ctx.mode == "chained":
        writer = writers.get("Motion", "")
        chain = _first(lib._CHAIN_WORD_RE, writer)
        if chain is None and ";" in writer:
            chain = ";"
        if chain is None and lib._COMMA_AND_RE.search(writer):
            chain = ", and"
        if chain:
            add(advisory, "N12", "one action", "Motion", "chains actions with %s" % _q(chain))
    narration = dict(fields).get("Narration", "")
    on_screen = ([by_cast[c]["phrase"] for c in beat["cast"] if c in by_cast]
                 if beat is not None else [])
    spoken_by = lib.parse_dialogue(dialogue, known)[0] if dialogue.strip() else None
    if "N16" in ids and beat is not None:
        found = lib.speaker_prefix(narration)
        speech_only = ctx.narration == "speech"
        if spoken_by is not None:
            if spoken_by.lower() not in [p.lower() for p in on_screen]:
                add(advisory, "N16", "speaker", "Dialogue",
                    "is spoken by %s, who is not in this shot; put %s in the shot or move the "
                    "line to a panel that shows them" % (_q(spoken_by), _q(spoken_by)))
        elif speech_only and narration.strip() and (
                not found or lib.split_speaker(narration, known)[0] is None):
            add(advisory, "N16", "speaker", "Narration",
                "is voice-over, but this story is speech-only; start it with the referring "
                "phrase of the character in the shot who says it and a colon, or leave it empty")
        elif found:
            if lib.split_speaker(narration, on_screen)[0] is not None:
                pass
            elif lib.split_speaker(narration, known)[0] is not None:
                add(advisory, "N16", "speaker", "Narration",
                    "is spoken by %s, who is not in this shot; only a character on screen can "
                    "speak, so make it voice-over (no prefix) or put %s in the shot"
                    % (_q(found[0]), _q(found[0])))
            else:
                add(advisory, "N16", "speaker", "Narration",
                    "starts with %s, which is no character's referring phrase, so it is read as "
                    "voice-over; start a spoken line with the speaker's referring phrase, or drop "
                    "the colon" % _q(found[0] + ":"))
    if "N17" in ids and beat is not None:
        if spoken_by is not None:
            speech_label = "Dialogue"
            speaker = (spoken_by if spoken_by.lower() in [p.lower() for p in on_screen] else None)
        else:
            speech_label = "Narration"
            speaker = lib.split_speaker(narration, on_screen)[0] if narration.strip() else None
        if speaker:
            shot_applies = ctx.mode != "chained" or k == 1
            if shot_applies and beat["shot"] in WIDE_SHOTS:
                add(advisory, "N17", "speaking shot", speech_label,
                    "%s speaks in a %s, too small to read the lips, so it plays as voice-over; "
                    "use a medium shot or closer" % (_q(speaker), beat["shot"]))
            held = next((w for w in (_first(HELD_EXPRESSION_RE, writers.get(field, ""))
                                     for field in action_fields) if w), None)
            if held:
                add(advisory, "N17", "speaking shot", speech_label,
                    "%s speaks, but the panel holds the expression %s, which freezes the mouth; "
                    "describe the speaking instead" % (_q(speaker), _q(held)))
            others = [p for p in on_screen if p.lower() != speaker.lower()]
            if speech_label == "Dialogue" and others:
                add(advisory, "N17", "speaking shot", "Dialogue",
                    "%s speaks in a shot that also shows %s; a speaking shot shows only the "
                    "speaker" % (_q(speaker), ", ".join(_q(p) for p in others)))
            for sentence in _sentences(writers.get(action_label, "")):
                move = CAMERA_MOTION_RE.search(sentence)
                if (move and lib._is_camera_sentence(sentence, known)
                        and " ".join(move.group(0).lower().split()) not in STILL_CAMERA_MOVES):
                    add(advisory, "N17", "speaking shot", action_label,
                        "has the camera direction %s while %s speaks; a speaking shot keeps the "
                        "camera static" % (_q(sentence), _q(speaker)))
                    break
    if "N14" in ids:
        if plan:
            narration = lib.split_speaker(narration, [c["phrase"] for c in plan["cast"]])[1]
        if narration.strip():
            sentences = [s for s in lib._SENTENCE_SPLIT_RE.split(narration.strip()) if s.strip()]
            lo, hi = NARRATION_WORDS
            if len(sentences) != 1:
                add(advisory, "N14", "narration form", "Narration",
                    "is %d sentences; it should be one sentence of %d-%d words"
                    % (len(sentences), lo, hi))
            elif not lo <= _words(narration) <= hi:
                add(advisory, "N14", "narration form", "Narration",
                    "is %d words; it should be one sentence of %d-%d words"
                    % (_words(narration), lo, hi))
    return hard, advisory
```

**3.2.** Edit `story_engine.py`: replace the whole of `plan_checks`, this text, which occurs exactly once:

```python
def plan_checks(ctx, plan, shape=()):
    """(hard, advisory) violation strings for a normalized plan (RS10). shape holds
    normalize_plan's container-shape P2 violations, reported first."""
    hard, advisory = list(shape), []
    n = ctx.panels
    beats = plan["beats"]
    if len(beats) != n:
        hard.append("plan: P1 beat count: expected exactly %d beats, found %d" % (n, len(beats)))
    for i, beat in enumerate(beats):
        if beat["index"] != i + 1:
            hard.append("plan: P1 beat count: beat %d has index %r; beats must be numbered 1 to %d "
                        "in order" % (i + 1, beat["index"], n))
    for key in ("title", "logline"):
        if not plan[key]:
            hard.append("plan: P2 structure: %s must be a non-empty string" % key)
    valid = {}
    for kind, fields in (("cast", ("phrase", "descriptor")), ("locations", ("setting",)),
                         ("props", ("name",))):
        seen = set()
        valid[kind] = {}
        for pos, entry in enumerate(plan[kind], start=1):
            label = entry["id"] if _ID_RES[kind].fullmatch(entry["id"]) else None
            if label is None:
                hard.append("plan: P2 structure: %s entry %d has id %s; ids are %s1, %s2 and so on"
                            % (kind, pos, _q(entry["id"]), kind[0], kind[0]))
            elif label in seen:
                hard.append("plan: P2 structure: %s id %s is used twice" % (kind, _q(label)))
                label = None
            missing = [f for f in fields if not entry[f]]
            for field in missing:
                hard.append("plan: P2 structure: %s entry %d has no %s" % (kind, pos, field))
            if label is not None:
                seen.add(label)
                if not missing:
                    valid[kind][label] = entry
    if not plan["locations"]:
        hard.append("plan: P2 structure: there must be at least one location")
    for k, beat in enumerate(beats, start=1):
        for field in ("arc", "action", "shot", "camera", "location"):
            if not beat[field]:
                hard.append("beat %d: P2 structure: %s is missing or empty" % (k, field))
        if beat["location"] and beat["location"] not in valid["locations"]:
            hard.append("beat %d: P2 structure: location %s is not defined"
                        % (k, _q(beat["location"])))
        for c in beat["cast"]:
            if c not in valid["cast"]:
                hard.append("beat %d: P2 structure: cast id %s is not defined" % (k, _q(c)))
        for c in sorted(set(c for c in beat["cast"] if beat["cast"].count(c) > 1)):
            hard.append("beat %d: P2 structure: cast id %s is listed twice" % (k, _q(c)))
    lib = _character_lib(ctx.ws)
    phrases = {}
    for cid, entry in valid["cast"].items():
        try:
            lib.normalize_phrase(entry["phrase"])
        except lib.CharacterError as e:
            hard.append("plan: P3 cast entry: %s's %s" % (cid, e))
            continue
        words = _words(entry["phrase"])
        if entry["cast_name"] is None and words > 4:
            hard.append("plan: P3 cast entry: %s's phrase %s has %d words; at most 4"
                        % (cid, _q(entry["phrase"]), words))
        other = phrases.get(entry["phrase"].lower())
        if other is not None:
            hard.append("plan: P3 cast entry: %s's phrase %s is also %s's"
                        % (cid, _q(entry["phrase"]), other))
        else:
            phrases[entry["phrase"].lower()] = cid
        try:
            lib.validate_descriptor(entry["descriptor"])
        except lib.CharacterError as e:
            hard.append("plan: P3 cast entry: %s's %s" % (cid, e))
    for lid, entry in valid["locations"].items():
        for problem in _setting_problems(entry["setting"]):
            hard.append("plan: P4 setting sentence: %s's setting %s" % (lid, problem))
        length = _setting_length(entry["setting"])
        if length:
            advisory.append("plan: P4 setting sentence: %s's setting %s" % (lid, length))
    arcs = [beat["arc"] if beat["arc"] in ARC_ROLES else None for beat in beats]
    for k, beat in enumerate(beats, start=1):
        if beat["arc"] and beat["arc"] not in ARC_ROLES:
            hard.append("beat %d: P5 arc: %s is not one of %s"
                        % (k, _q(beat["arc"]), ", ".join(ARC_ROLES)))
    required = (() if n == 1 else ("introduction", "resolution") if n == 2
                else ("introduction", "climax", "resolution"))
    for role in required:
        if role not in arcs:
            hard.append("plan: P5 arc: no beat has arc %s" % _q(role))
    for k in range(2, len(arcs) + 1):
        a, b = arcs[k - 2], arcs[k - 1]
        if a and b and ARC_ROLES.index(b) < ARC_ROLES.index(a):
            advisory.append("beat %d: P6 arc order: %s follows %s" % (k, _q(b), _q(a)))
    if n >= 2 and arcs:
        if arcs[0] and arcs[0] != "introduction":
            advisory.append("plan: P6 arc order: the first beat's arc is %s, not 'introduction'"
                            % _q(arcs[0]))
        if arcs[-1] and arcs[-1] != "resolution":
            advisory.append("plan: P6 arc order: the last beat's arc is %s, not 'resolution'"
                            % _q(arcs[-1]))
    for k, beat in enumerate(beats, start=1):
        if beat["shot"] and beat["shot"] not in SHOT_TYPES:
            hard.append("beat %d: P7 shot type: %s is not one of: %s"
                        % (k, _q(beat["shot"]), ", ".join(SHOT_TYPES)))
        elif (beat["shot"] and beat["shot"] not in shot_types(ctx.narration)
              and (ctx.mode != "chained" or k == 1)):
            hard.append("beat %d: P7 shot type: %s is too wide for on-screen speech; use one of: %s"
                        % (k, _q(beat["shot"]), ", ".join(shot_types(ctx.narration))))
        if beat["camera"] and beat["camera"] not in CAMERA_KEYS:
            hard.append("beat %d: P8 camera: %s is not one of: %s"
                        % (k, _q(beat["camera"]), ", ".join(CAMERA_KEYS)))
        if len(beat["cast"]) > MAX_CAST[ctx.mode]:
            hard.append("beat %d: P9 cast count: %d characters on screen; at most %d in this mode"
                        % (k, len(beat["cast"]), MAX_CAST[ctx.mode]))
        if k <= n:
            for field, pasted in pasted_pieces(ctx, plan, k).items():
                spec = field_range(ctx, k, field)
                pasted = [p for p in pasted if p]
                if spec is None or not pasted:
                    continue
                kind, (lo, hi) = spec
                used = _words(" ".join(pasted))
                if hi - used < MIN_WRITER_WORDS[kind]:
                    advisory.append("beat %d: P10 word budget: %s: the pasted sentences take %d of its "
                                "%d-%d words, leaving fewer than %d for the writer"
                                % (k, field.capitalize(), used, lo, hi, MIN_WRITER_WORDS[kind]))
    if ctx.mode == "chained":
        for k in range(2, len(beats) + 1):
            prev, cur = beats[k - 2]["location"], beats[k - 1]["location"]
            if (prev in valid["locations"] and cur in valid["locations"] and prev != cur):
                advisory.append("beat %d: P11 location change: moves from %s to %s with no cut; "
                                "the action must carry the characters there" % (k, prev, cur))
        opening = set(beats[0]["cast"]) if beats else set()
        for k in range(2, len(beats) + 1):
            for c in beats[k - 1]["cast"]:
                if c in valid["cast"] and c not in opening:
                    advisory.append("beat %d: P12 new character: %s is not in the opening frame; "
                                    "their look is left to the video model" % (k, c))
    undeclared = undeclared_characters(ctx)
    if undeclared:
        masks = _undeclared_masks(lib, ctx, plan, undeclared)
        texts = []
        for entry in plan["cast"]:
            if entry["cast_name"] is None:
                texts.append(("%s's phrase" % entry["id"], entry["phrase"], True))
                texts.append(("%s's descriptor" % entry["id"], entry["descriptor"], False))
        texts += [("the title", plan["title"], False), ("the logline", plan["logline"], False)]
        texts += [("%s's setting" % l["id"], l["setting"], False) for l in plan["locations"]]
        texts += [("%s's name" % p["id"], p["name"], False) for p in plan["props"]]
        texts += [("beat %d's action" % k, b["action"], False)
                  for k, b in enumerate(beats, start=1)]
        for where, text, exact in texts:
            for hit in undeclared_references(lib, text, undeclared, exact_phrase=exact,
                                        masks=masks):
                hard.append(undeclared_message("plan: P13 undeclared character:", where, hit))
    advisory += plan["speech_notes"]
    return hard, advisory
```

with:

```python
def plan_checks(ctx, plan, shape=()):
    """(hard, advisory) violation strings for a normalized plan (RS10). shape holds
    normalize_plan's container-shape P2 violations, reported first. Hard: P1, P2 and P3's
    normalize and duplicate-phrase messages; every other P message is advisory (dialogue spec
    6.3)."""
    hard, advisory = list(shape), []
    n = ctx.panels
    beats = plan["beats"]
    if len(beats) != n:
        hard.append("plan: P1 beat count: expected exactly %d beats, found %d" % (n, len(beats)))
    for i, beat in enumerate(beats):
        if beat["index"] != i + 1:
            hard.append("plan: P1 beat count: beat %d has index %r; beats must be numbered 1 to %d "
                        "in order" % (i + 1, beat["index"], n))
    for key in ("title", "logline"):
        if not plan[key]:
            hard.append("plan: P2 structure: %s must be a non-empty string" % key)
    valid = {}
    for kind, fields in (("cast", ("phrase", "descriptor")), ("locations", ("setting",)),
                         ("props", ("name",))):
        seen = set()
        valid[kind] = {}
        for pos, entry in enumerate(plan[kind], start=1):
            label = entry["id"] if _ID_RES[kind].fullmatch(entry["id"]) else None
            if label is None:
                hard.append("plan: P2 structure: %s entry %d has id %s; ids are %s1, %s2 and so on"
                            % (kind, pos, _q(entry["id"]), kind[0], kind[0]))
            elif label in seen:
                hard.append("plan: P2 structure: %s id %s is used twice" % (kind, _q(label)))
                label = None
            missing = [f for f in fields if not entry[f]]
            for field in missing:
                hard.append("plan: P2 structure: %s entry %d has no %s" % (kind, pos, field))
            if label is not None:
                seen.add(label)
                if not missing:
                    valid[kind][label] = entry
    if not plan["locations"]:
        hard.append("plan: P2 structure: there must be at least one location")
    for k, beat in enumerate(beats, start=1):
        for field in ("arc", "action", "shot", "camera", "location"):
            if not beat[field]:
                hard.append("beat %d: P2 structure: %s is missing or empty" % (k, field))
        if beat["location"] and beat["location"] not in valid["locations"]:
            hard.append("beat %d: P2 structure: location %s is not defined"
                        % (k, _q(beat["location"])))
        for c in beat["cast"]:
            if c not in valid["cast"]:
                hard.append("beat %d: P2 structure: cast id %s is not defined" % (k, _q(c)))
        for c in sorted(set(c for c in beat["cast"] if beat["cast"].count(c) > 1)):
            hard.append("beat %d: P2 structure: cast id %s is listed twice" % (k, _q(c)))
    lib = _character_lib(ctx.ws)
    phrases = {}
    for cid, entry in valid["cast"].items():
        try:
            lib.normalize_phrase(entry["phrase"])
        except lib.CharacterError as e:
            hard.append("plan: P3 cast entry: %s's %s" % (cid, e))
            continue
        words = _words(entry["phrase"])
        if entry["cast_name"] is None and words > 4:
            advisory.append("plan: P3 cast entry: %s's phrase %s has %d words; at most 4"
                        % (cid, _q(entry["phrase"]), words))
        other = phrases.get(entry["phrase"].lower())
        if other is not None:
            hard.append("plan: P3 cast entry: %s's phrase %s is also %s's"
                        % (cid, _q(entry["phrase"]), other))
        else:
            phrases[entry["phrase"].lower()] = cid
        try:
            lib.validate_descriptor(entry["descriptor"])
        except lib.CharacterError as e:
            advisory.append("plan: P3 cast entry: %s's %s" % (cid, e))
    for lid, entry in valid["locations"].items():
        for problem in _setting_problems(entry["setting"]):
            advisory.append("plan: P4 setting sentence: %s's setting %s" % (lid, problem))
        length = _setting_length(entry["setting"])
        if length:
            advisory.append("plan: P4 setting sentence: %s's setting %s" % (lid, length))
    arcs = [beat["arc"] if beat["arc"] in ARC_ROLES else None for beat in beats]
    for k, beat in enumerate(beats, start=1):
        if beat["arc"] and beat["arc"] not in ARC_ROLES:
            advisory.append("beat %d: P5 arc: %s is not one of %s"
                        % (k, _q(beat["arc"]), ", ".join(ARC_ROLES)))
    required = (() if n == 1 else ("introduction", "resolution") if n == 2
                else ("introduction", "climax", "resolution"))
    for role in required:
        if role not in arcs:
            advisory.append("plan: P5 arc: no beat has arc %s" % _q(role))
    for k in range(2, len(arcs) + 1):
        a, b = arcs[k - 2], arcs[k - 1]
        if a and b and ARC_ROLES.index(b) < ARC_ROLES.index(a):
            advisory.append("beat %d: P6 arc order: %s follows %s" % (k, _q(b), _q(a)))
    if n >= 2 and arcs:
        if arcs[0] and arcs[0] != "introduction":
            advisory.append("plan: P6 arc order: the first beat's arc is %s, not 'introduction'"
                            % _q(arcs[0]))
        if arcs[-1] and arcs[-1] != "resolution":
            advisory.append("plan: P6 arc order: the last beat's arc is %s, not 'resolution'"
                            % _q(arcs[-1]))
    for k, beat in enumerate(beats, start=1):
        if beat["shot"] and beat["shot"] not in SHOT_TYPES:
            advisory.append("beat %d: P7 shot type: %s is not one of: %s"
                        % (k, _q(beat["shot"]), ", ".join(SHOT_TYPES)))
        elif (beat["shot"] and beat["shot"] not in shot_types(ctx.narration)
              and (ctx.mode != "chained" or k == 1)):
            advisory.append("beat %d: P7 shot type: %s is too wide for on-screen speech; use one of: %s"
                        % (k, _q(beat["shot"]), ", ".join(shot_types(ctx.narration))))
        if beat["camera"] and beat["camera"] not in CAMERA_KEYS:
            advisory.append("beat %d: P8 camera: %s is not one of: %s"
                        % (k, _q(beat["camera"]), ", ".join(CAMERA_KEYS)))
        if len(beat["cast"]) > MAX_CAST[ctx.mode]:
            advisory.append("beat %d: P9 cast count: %d characters on screen; at most %d in this mode"
                        % (k, len(beat["cast"]), MAX_CAST[ctx.mode]))
        if k <= n:
            for field, pasted in pasted_pieces(ctx, plan, k).items():
                spec = field_range(ctx, k, field)
                pasted = [p for p in pasted if p]
                if spec is None or not pasted:
                    continue
                kind, (lo, hi) = spec
                used = _words(" ".join(pasted))
                if hi - used < MIN_WRITER_WORDS[kind]:
                    advisory.append("beat %d: P10 word budget: %s: the pasted sentences take %d of its "
                                "%d-%d words, leaving fewer than %d for the writer"
                                % (k, field.capitalize(), used, lo, hi, MIN_WRITER_WORDS[kind]))
    if ctx.mode == "chained":
        for k in range(2, len(beats) + 1):
            prev, cur = beats[k - 2]["location"], beats[k - 1]["location"]
            if (prev in valid["locations"] and cur in valid["locations"] and prev != cur):
                advisory.append("beat %d: P11 location change: moves from %s to %s with no cut; "
                                "the action must carry the characters there" % (k, prev, cur))
        opening = set(beats[0]["cast"]) if beats else set()
        for k in range(2, len(beats) + 1):
            for c in beats[k - 1]["cast"]:
                if c in valid["cast"] and c not in opening:
                    advisory.append("beat %d: P12 new character: %s is not in the opening frame; "
                                    "their look is left to the video model" % (k, c))
    undeclared = undeclared_characters(ctx)
    if undeclared:
        masks = _undeclared_masks(lib, ctx, plan, undeclared)
        texts = []
        for entry in plan["cast"]:
            if entry["cast_name"] is None:
                texts.append(("%s's phrase" % entry["id"], entry["phrase"], True))
                texts.append(("%s's descriptor" % entry["id"], entry["descriptor"], False))
        texts += [("the title", plan["title"], False), ("the logline", plan["logline"], False)]
        texts += [("%s's setting" % l["id"], l["setting"], False) for l in plan["locations"]]
        texts += [("%s's name" % p["id"], p["name"], False) for p in plan["props"]]
        texts += [("beat %d's action" % k, b["action"], False)
                  for k, b in enumerate(beats, start=1)]
        for where, text, exact in texts:
            for hit in undeclared_references(lib, text, undeclared, exact_phrase=exact,
                                        masks=masks):
                advisory.append(undeclared_message("plan: P13 undeclared character:", where, hit))
    advisory += plan["speech_notes"]
    return hard, advisory
```

**3.3.** Edit `story_engine.py`: replace the whole of `lora_checks`, this text, which occurs exactly once:

```python
def lora_checks(ctx, plan, compatible_by_id, catalog_by_id):
    """(hard, advisory) LoRA violations of a plan (RS11, LC12). Not run without auto LoRA."""
    hard, advisory = [], []
    if not ctx.auto_lora:
        return hard, advisory
    n = ctx.panels
    loras = plan["loras"]
    lora_catalog = _lora_catalog(ctx.ws)

    def check_pick(pick, scope, target):
        if not _is_pick(pick):
            hard.append("%s: L1 catalog id: pick %s is not an object with an id and a numeric "
                        "strength" % (scope, json.dumps(pick, ensure_ascii=False)))
            return None
        entry = catalog_by_id.get(pick["id"])
        if entry is None:
            hard.append("%s: L1 catalog id: %s is not in the catalog" % (scope, _q(pick["id"])))
            return None
        if target == "video" and entry["target"] != "video":
            hard.append("%s: L1 catalog id: %s is a stills LoRA; global and per-beat picks must "
                        "be video LoRAs" % (scope, _q(pick["id"])))
            return None
        if target == "stills" and entry["target"] != "stills":
            hard.append("%s: L1 catalog id: %s is a video LoRA; a stills pick must be a stills "
                        "LoRA" % (scope, _q(pick["id"])))
            return None
        model = ctx.video_model if target == "video" else lora_catalog.STILLS_BASE_MODEL
        if not lora_catalog.compatible(entry, model):
            hard.append("%s: L1 catalog id: %s does not support model %s"
                        % (scope, _q(pick["id"]), model))
            return None
        if pick["id"] not in compatible_by_id:
            hard.append("%s: L1 catalog id: %s is not in the catalog" % (scope, _q(pick["id"])))
            return None
        lo, hi = entry["strength_range"]
        if not lo <= pick["strength"] <= hi:
            hard.append("plan: L5 strength: %s strength %s is outside its range %s to %s"
                        % (_q(pick["id"]), repr(float(pick["strength"])), repr(float(lo)),
                           repr(float(hi))))
        return dict(entry, strength=pick["strength"])

    global_picks = [e for e in (check_pick(p, "plan", "video") for p in loras["global"]) if e]
    per_beat = {}
    for key, picks in loras["per_beat"].items():
        if key not in [str(k) for k in range(1, n + 1)]:
            hard.append("plan: L1 catalog id: per_beat key %s is not a beat number from 1 to %d"
                        % (_q(key), n))
            continue
        per_beat[int(key)] = [e for e in (check_pick(p, "beat %s" % key, "video")
                                          for p in picks) if e]
    stills = [e for e in (check_pick(p, "plan", "stills") for p in loras["stills"]) if e]
    pins = loras.get("pinned", [])

    def pin_label(pin):
        return pin["catalog_id"] or "pinned LoRA"

    styles = ([pin_label(p) for p in pins if p.get("kind") == "style"]
              + [e["id"] for e in global_picks if e["kind"] == "style"])
    if len(styles) > 1:
        hard.append("plan: L2 style: %d style LoRAs for every panel (%s); at most 1"
                    % (len(styles), ", ".join(styles)))
    for k in sorted(per_beat):
        for e in per_beat[k]:
            if e["kind"] == "style":
                hard.append("beat %d: L2 style: style LoRA %s can only be a global pick"
                            % (k, _q(e["id"])))
    by_cast = {c["id"]: c for c in plan["cast"]}
    reported_dupes = set()
    pin_paths = {os.path.realpath(p["path"]) for p in pins}
    for k in range(1, n + 1):
        beat = plan["beats"][k - 1] if k <= len(plan["beats"]) else {"cast": []}
        loras_k = ([(pin_label(p), p.get("kind"), p.get("catalog_id"), None) for p in pins]
                   + [(e["id"], e["kind"], e["id"], e["path"]) for e in global_picks]
                   + [(e["id"], e["kind"], e["id"], e["path"]) for e in per_beat.get(k, [])]
                   + [("character " + by_cast[c]["cast_name"], "character", None, None)
                      for c in beat["cast"] if c in by_cast and by_cast[c]["cast_name"]])
        motion = [label for label, kind, _i, _p in loras_k if kind in ("motion", "physics")]
        if len(motion) > 1:
            hard.append("beat %d: L3 motion: %d motion or physics LoRAs on this panel (%s); at "
                        "most 1" % (k, len(motion), ", ".join(motion)))
        if len(loras_k) > LORA_PANEL_LIMIT:
            message = ("beat %d: L4 LoRA count: %d LoRAs on this panel (%s); at most %d"
                       % (k, len(loras_k), ", ".join(l[0] for l in loras_k), LORA_PANEL_LIMIT))
            (hard if (global_picks or per_beat.get(k)) else advisory).append(message)
        ids = [i for _l, _k, i, _p in loras_k if i]
        for dup in sorted(set(i for i in ids if ids.count(i) > 1)):
            if dup not in reported_dupes:
                reported_dupes.add(dup)
                hard.append("beat %d: L6 duplicate: %s is applied twice on this panel"
                            % (k, _q(dup)))
        for label, _kind, catalog_id, path in loras_k:
            if (path and os.path.realpath(path) in pin_paths and catalog_id not in reported_dupes):
                reported_dupes.add(catalog_id)
                hard.append("beat %d: L6 duplicate: %s is applied twice on this panel"
                            % (k, _q(catalog_id)))
    if len(loras["stills"]) > 1:
        hard.append("plan: L7 stills: %d stills LoRAs; at most 1" % len(loras["stills"]))
    if ctx.mode == "no_stills" and loras["stills"]:
        hard.append("plan: L7 stills: this movie has no stills; stills must be empty")
    for e in stills:
        if os.path.realpath(e["path"]) in set(ctx.stills_pinned):
            hard.append("plan: L7 stills: %s is also passed with --stills-lora" % _q(e["id"]))
    return hard, advisory
```

with:

```python
def lora_checks(ctx, plan, compatible_by_id, catalog_by_id):
    """(hard, advisory) LoRA violations of a plan (RS11, LC12). Not run without auto LoRA. Hard:
    L1, L6, L7 and a strength outside (0, 2], which the renderer refuses; L2-L4 and a strength
    outside the entry's own range are advisory (dialogue spec 6.3, Q4)."""
    hard, advisory = [], []
    if not ctx.auto_lora:
        return hard, advisory
    n = ctx.panels
    loras = plan["loras"]
    lora_catalog = _lora_catalog(ctx.ws)

    def check_pick(pick, scope, target):
        if not _is_pick(pick):
            hard.append("%s: L1 catalog id: pick %s is not an object with an id and a numeric "
                        "strength" % (scope, json.dumps(pick, ensure_ascii=False)))
            return None
        entry = catalog_by_id.get(pick["id"])
        if entry is None:
            hard.append("%s: L1 catalog id: %s is not in the catalog" % (scope, _q(pick["id"])))
            return None
        if target == "video" and entry["target"] != "video":
            hard.append("%s: L1 catalog id: %s is a stills LoRA; global and per-beat picks must "
                        "be video LoRAs" % (scope, _q(pick["id"])))
            return None
        if target == "stills" and entry["target"] != "stills":
            hard.append("%s: L1 catalog id: %s is a video LoRA; a stills pick must be a stills "
                        "LoRA" % (scope, _q(pick["id"])))
            return None
        model = ctx.video_model if target == "video" else lora_catalog.STILLS_BASE_MODEL
        if not lora_catalog.compatible(entry, model):
            hard.append("%s: L1 catalog id: %s does not support model %s"
                        % (scope, _q(pick["id"]), model))
            return None
        if pick["id"] not in compatible_by_id:
            hard.append("%s: L1 catalog id: %s is not in the catalog" % (scope, _q(pick["id"])))
            return None
        lo, hi = entry["strength_range"]
        if not 0 < pick["strength"] <= 2:
            hard.append("plan: L5 strength: %s strength %s is outside (0, 2], which the renderer "
                        "refuses" % (_q(pick["id"]), repr(float(pick["strength"]))))
        elif not lo <= pick["strength"] <= hi:
            advisory.append("plan: L5 strength: %s strength %s is outside its range %s to %s"
                        % (_q(pick["id"]), repr(float(pick["strength"])), repr(float(lo)),
                           repr(float(hi))))
        return dict(entry, strength=pick["strength"])

    global_picks = [e for e in (check_pick(p, "plan", "video") for p in loras["global"]) if e]
    per_beat = {}
    for key, picks in loras["per_beat"].items():
        if key not in [str(k) for k in range(1, n + 1)]:
            hard.append("plan: L1 catalog id: per_beat key %s is not a beat number from 1 to %d"
                        % (_q(key), n))
            continue
        per_beat[int(key)] = [e for e in (check_pick(p, "beat %s" % key, "video")
                                          for p in picks) if e]
    stills = [e for e in (check_pick(p, "plan", "stills") for p in loras["stills"]) if e]
    pins = loras.get("pinned", [])

    def pin_label(pin):
        return pin["catalog_id"] or "pinned LoRA"

    styles = ([pin_label(p) for p in pins if p.get("kind") == "style"]
              + [e["id"] for e in global_picks if e["kind"] == "style"])
    if len(styles) > 1:
        advisory.append("plan: L2 style: %d style LoRAs for every panel (%s); at most 1"
                    % (len(styles), ", ".join(styles)))
    for k in sorted(per_beat):
        for e in per_beat[k]:
            if e["kind"] == "style":
                advisory.append("beat %d: L2 style: style LoRA %s can only be a global pick"
                            % (k, _q(e["id"])))
    by_cast = {c["id"]: c for c in plan["cast"]}
    reported_dupes = set()
    pin_paths = {os.path.realpath(p["path"]) for p in pins}
    for k in range(1, n + 1):
        beat = plan["beats"][k - 1] if k <= len(plan["beats"]) else {"cast": []}
        loras_k = ([(pin_label(p), p.get("kind"), p.get("catalog_id"), None) for p in pins]
                   + [(e["id"], e["kind"], e["id"], e["path"]) for e in global_picks]
                   + [(e["id"], e["kind"], e["id"], e["path"]) for e in per_beat.get(k, [])]
                   + [("character " + by_cast[c]["cast_name"], "character", None, None)
                      for c in beat["cast"] if c in by_cast and by_cast[c]["cast_name"]])
        motion = [label for label, kind, _i, _p in loras_k if kind in ("motion", "physics")]
        if len(motion) > 1:
            advisory.append("beat %d: L3 motion: %d motion or physics LoRAs on this panel (%s); at "
                        "most 1" % (k, len(motion), ", ".join(motion)))
        if len(loras_k) > LORA_PANEL_LIMIT:
            message = ("beat %d: L4 LoRA count: %d LoRAs on this panel (%s); at most %d"
                       % (k, len(loras_k), ", ".join(l[0] for l in loras_k), LORA_PANEL_LIMIT))
            advisory.append(message)
        ids = [i for _l, _k, i, _p in loras_k if i]
        for dup in sorted(set(i for i in ids if ids.count(i) > 1)):
            if dup not in reported_dupes:
                reported_dupes.add(dup)
                hard.append("beat %d: L6 duplicate: %s is applied twice on this panel"
                            % (k, _q(dup)))
        for label, _kind, catalog_id, path in loras_k:
            if (path and os.path.realpath(path) in pin_paths and catalog_id not in reported_dupes):
                reported_dupes.add(catalog_id)
                hard.append("beat %d: L6 duplicate: %s is applied twice on this panel"
                            % (k, _q(catalog_id)))
    if len(loras["stills"]) > 1:
        hard.append("plan: L7 stills: %d stills LoRAs; at most 1" % len(loras["stills"]))
    if ctx.mode == "no_stills" and loras["stills"]:
        hard.append("plan: L7 stills: this movie has no stills; stills must be empty")
    for e in stills:
        if os.path.realpath(e["path"]) in set(ctx.stills_pinned):
            hard.append("plan: L7 stills: %s is also passed with --stills-lora" % _q(e["id"]))
    return hard, advisory
```

**3.4.** Edit `story_engine.py`: replace (in `apply_patches`: a LoRA patch still may not add any LoRA finding, now that L2-L4 are advisory) this text, which occurs exactly once:

```python
        before = lora_checks(ctx, plan, compatible_by_id, catalog_by_id)[0]
```

with:

```python
        before = sum(lora_checks(ctx, plan, compatible_by_id, catalog_by_id), [])
```

**3.5.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        broken = [h for h in lora_checks(ctx, plan, compatible_by_id, catalog_by_id)[0]
                  if h not in before]
```

with:

```python
        broken = [h for h in sum(lora_checks(ctx, plan, compatible_by_id, catalog_by_id), [])
                  if h not in before]
```

**3.6.** Edit `story_engine.py`: replace the whole of `panel_checks`, this text, which occurs exactly once:

```python
def panel_checks(ctx, plan, parts, text, story_md_path):
    """(hard, advisory) of an assembled story (RS15): plan-scope N10, then per panel N2-N11 and
    N15 (hard), N16 (hard or advisory) and N1, N12-N14, N17 (advisory), then (shots)
    character_lib.shots_violations and shots_advisories. story_md_path holds text (written by
    the caller) and is parsed with bin/ltx-story-manifest's _parse_prompts_md."""
    lib = _character_lib(ctx.ws)
    undeclared = undeclared_characters(ctx)
    hard, advisory = plan_copied_examples(plan), []
    writers_by_panel = []
    for k in range(1, len(parts) + 1):
        fields = panel_fields(ctx, plan, parts, k)
        writers = {LABELS[key]: parts[k - 1].get(key, "") for key in panel_keys(ctx, plan, k)
                   if key != "title"}
        writers_by_panel.append(writers)
        h, a = _field_checks(ctx, lib, plan, k, parts[k - 1]["title"], fields, writers,
                             GENERATION_CHECKS, undeclared)
        hard += h
        advisory += a
    advisory = _order_by_panel(advisory + repeat_advisories(ctx, lib, plan, writers_by_panel))
    if ctx.mode == "shots":
        panels = _story_manifest(ctx.ws)._parse_prompts_md(story_md_path)[1]
        hard += lib.shots_violations(text, panels, ctx.panels, ctx.members, ctx.narration is True,
                                     ignore_facing=True)
        advisory += lib.shots_advisories(panels, ctx.members)
    return hard, advisory
```

with:

```python
def panel_checks(ctx, plan, parts, text, story_md_path):
    """(hard, advisory) of an assembled story (RS15; dialogue spec 6.3): per panel the
    _field_checks classes; plan-scope N10 is advisory; in shots mode S1 and S3 are hard and every
    other character_lib.shots_violations rule joins shots_advisories in advisory. story_md_path
    holds text (written by the caller) and is parsed with bin/ltx-story-manifest's
    _parse_prompts_md."""
    lib = _character_lib(ctx.ws)
    undeclared = undeclared_characters(ctx)
    hard, advisory = [], []
    writers_by_panel = []
    for k in range(1, len(parts) + 1):
        fields = panel_fields(ctx, plan, parts, k)
        writers = {LABELS[key]: parts[k - 1].get(key, "") for key in panel_keys(ctx, plan, k)
                   if key != "title"}
        writers_by_panel.append(writers)
        h, a = _field_checks(ctx, lib, plan, k, parts[k - 1]["title"], fields, writers,
                             GENERATION_CHECKS, undeclared)
        hard += h
        advisory += a
    advisory = plan_copied_examples(plan) + _order_by_panel(
        advisory + repeat_advisories(ctx, lib, plan, writers_by_panel))
    if ctx.mode == "shots":
        panels = _story_manifest(ctx.ws)._parse_prompts_md(story_md_path)[1]
        shots_hard, shots_other = split_shots(lib.shots_violations(
            text, panels, ctx.panels, ctx.members, ctx.narration is True, ignore_facing=True))
        hard += shots_hard
        advisory += shots_other + lib.shots_advisories(panels, ctx.members)
    return hard, advisory
```

**3.7.** Edit `story_engine.py`: replace `_order_by_panel`, adding the two names after it, this text, which occurs exactly once:

```python
def _order_by_panel(lines):
    """Panel advisories sorted by panel, then N12, N13, N14, N16, N17 (stable)."""
    order = {"N12": 0, "N13": 1, "N14": 2, "N16": 3, "N17": 4}
    return sorted(lines, key=lambda l: (int(l.split(":", 1)[0].split()[1]),
                                        order.get(l.split()[2], 3)))
```

with:

```python
def _order_by_panel(lines):
    """Panel advisories sorted by panel, then N12, N13, N14, N16, N17 (stable)."""
    order = {"N12": 0, "N13": 1, "N14": 2, "N16": 3, "N17": 4}
    return sorted(lines, key=lambda l: (int(l.split(":", 1)[0].split()[1]),
                                        order.get(l.split()[2], 3)))


SHOTS_HARD_RULES = ("S1", "S3")


def split_shots(violations):
    """(the S1/S3 violations, the other S rules) of a character_lib.shots_violations list: in the
    robust engine only S1 and S3 are hard (dialogue spec 6.3)."""
    return ([v for v in violations if parse_violation(v)["id"] in SHOTS_HARD_RULES],
            [v for v in violations if parse_violation(v)["id"] not in SHOTS_HARD_RULES])
```

**3.8.** Edit `story_engine.py`: replace the whole of `plan_free_report`, this text, which occurs exactly once:

```python
def plan_free_report(story_md, mode, panels, members, legacy_validate, ws=None):
    """The hard violations a re-check computes without a plan (RS28; the 7.2 yardstick for both
    engines). ws (default: this file's directory) locates the character library and the
    manifest parser. Prints nothing, writes nothing."""
    ws = ws or os.path.dirname(os.path.realpath(__file__))
    ctx = StoryContext(ws=ws, story_id="", story_dir=os.path.dirname(story_md), mode=mode,
                       panels=panels, seconds="6", narrative="", goal=None, members=members,
                       seed_image=None, seed_agent_image=None, story_model=None,
                       context_window=None, video_model="", auto_lora=False,
                       catalog={"schema_version": 1, "entries": []}, pinned=[], stills_pinned=[],
                       judge=False)
    lib = _character_lib(ws)
    hard = [] if mode == "shots" else list(legacy_validate(story_md, panels, mode == "no_stills"))
    text, parsed = _read_story(ctx, story_md)
    undeclared = undeclared_characters(ctx)
    for k, panel in enumerate(parsed, start=1):
        fields = story_fields(mode, k, panel)
        hard += _field_checks(ctx, lib, None, k, panel["title"], fields, dict(fields),
                              PLAN_FREE_IDS, undeclared)[0]
    if mode == "shots":
        hard += lib.shots_violations(text, parsed, panels, members, ignore_facing=True)
    return hard
```

with:

```python
def plan_free_report(story_md, mode, panels, members, legacy_validate, ws=None):
    """(hard, advisory) of a re-check without a plan (RS28; the 7.2 yardstick for both engines;
    dialogue spec 6.4): hard is legacy_validate (not shots), the hard part of _field_checks and
    S1/S3 (shots); advisory is the rest, N15 included. ws (default: this file's directory)
    locates the character library and the manifest parser. Prints nothing, writes nothing."""
    ws = ws or os.path.dirname(os.path.realpath(__file__))
    ctx = StoryContext(ws=ws, story_id="", story_dir=os.path.dirname(story_md), mode=mode,
                       panels=panels, seconds="6", narrative="", goal=None, members=members,
                       seed_image=None, seed_agent_image=None, story_model=None,
                       context_window=None, video_model="", auto_lora=False,
                       catalog={"schema_version": 1, "entries": []}, pinned=[], stills_pinned=[],
                       judge=False)
    lib = _character_lib(ws)
    hard = [] if mode == "shots" else list(legacy_validate(story_md, panels, mode == "no_stills"))
    advisory = []
    text, parsed = _read_story(ctx, story_md)
    undeclared = undeclared_characters(ctx)
    for k, panel in enumerate(parsed, start=1):
        fields = story_fields(mode, k, panel)
        h, a = _field_checks(ctx, lib, None, k, panel["title"], fields, dict(fields),
                             PLAN_FREE_IDS, undeclared)
        hard += h
        advisory += a
    if mode == "shots":
        shots_hard, shots_other = split_shots(lib.shots_violations(text, parsed, panels, members,
                                                                    ignore_facing=True))
        hard += shots_hard
        advisory += shots_other
    return hard, advisory
```

**3.9.** Edit `story_engine.py`: replace the whole of `_undeclared_gate`, this text, which occurs exactly once:

```python
def _undeclared_gate(ctx, story_md, legacy_validate, passed):
    """passed, unless story.md names a library character that was not declared (RS37)."""
    n15 = [v for v in plan_free_report(story_md, ctx.mode, ctx.panels, ctx.members,
                                       legacy_validate, ws=ctx.ws) if " N15 " in v]
    if not n15:
        return passed
    for v in n15:
        print("  - %s" % v, file=sys.stderr)
    print("ltx-movie: story.md names library characters that were not declared with --character; "
          "fix story.md and re-run", file=sys.stderr)
    return 2, []
```

with:

```python
def _undeclared_gate(ctx, story_md, legacy_validate, passed):
    """passed, after a Warning line for every N15 of plan_free_report (a library character
    story.md names but --character did not declare; advisory, RS37 and dialogue spec Q1)."""
    for v in plan_free_report(story_md, ctx.mode, ctx.panels, ctx.members, legacy_validate,
                              ws=ctx.ws)[1]:
        if " N15 " in v:
            print("Warning: %s" % v)
    return passed
```

**3.10.** Edit `story_engine.py`: replace the whole of `recheck`, this text, which occurs exactly once:

```python
def recheck(ctx, legacy_validate):
    """Re-check an existing story.md instead of regenerating it (RS28). Returns (exit code,
    advisories). legacy_validate is bin/ltx-movie's _validate_story_md."""
    story_md = os.path.join(ctx.story_dir, "story.md")
    for warning in catalog_warnings(ctx):
        print(warning)
    lib = _character_lib(ctx.ws)
    plan = load_plan(ctx)
    if plan is not None:
        try:
            hard = ([] if ctx.mode == "shots"
                    else list(legacy_validate(story_md, ctx.panels, ctx.mode == "no_stills")))
            advisory = []
            text, parsed = _read_story(ctx, story_md)
            undeclared = undeclared_characters(ctx)
            writers_by_panel = []
            for k, panel in enumerate(parsed, start=1):
                fields = story_fields(ctx.mode, k, panel, ctx.narration)
                writers = _recheck_writers(ctx, lib, plan, k, fields)
                writers_by_panel.append(writers)
                h, a = _field_checks(ctx, lib, plan, k, panel["title"], fields, writers,
                                     RECHECK_IDS, undeclared)
                hard += h
                advisory += a
            advisory = _order_by_panel(advisory + repeat_advisories(ctx, lib, plan, writers_by_panel))
            if ctx.mode == "shots":
                hard += lib.shots_violations(text, parsed, ctx.panels, ctx.members,
                                            ctx.narration is True, ignore_facing=True)
                advisory += lib.shots_advisories(parsed, ctx.members)
            if ctx.auto_lora:
                compatible = dict((e["id"], e) for e in compatible_entries(ctx))
                catalog = dict((e["id"], e) for e in ctx.catalog.get("entries", []))
                lh, la = lora_checks(ctx, plan, compatible, catalog)
                hard += lh
                advisory += la
            _write_json(os.path.join(ctx.story_dir, "story_checks.json"),
                        _checks_doc(ctx, {"hard": hard, "advisory": advisory}, source="recheck"))
            if hard:
                print("Error: story.md fails the story checks:", file=sys.stderr)
                for message in hard:
                    print("  - %s" % message, file=sys.stderr)
                print("Hand-edit %s to fix the violations above and rerun, or pass --force-story to "
                      "regenerate it." % story_md, file=sys.stderr)
                if any(parse_violation(m)["id"].startswith("L") for m in hard):
                    print("The L violations come from plan.json's catalog LoRA picks, not from "
                          "story.md: restore or re-add the LoRA files (bin/lora-catalog verify), "
                          "rerun with --no-auto-lora, or pass --force-story to regenerate.",
                          file=sys.stderr)
                return 2, advisory
            return 0, advisory
        except (KeyError, TypeError, AttributeError, ValueError, IndexError):
            print("note: %s is malformed; re-checking story.md without it"
                  % os.path.join(ctx.story_dir, "plan.json"))
    if ctx.mode != "shots":
        violations = legacy_validate(story_md, ctx.panels, ctx.mode == "no_stills")
        if violations:
            print("Error: story.md failed validation:", file=sys.stderr)
            for v in violations:
                print("  - %s" % v, file=sys.stderr)
            print("Hand-edit %s to fix the violations above and rerun; story.md already exists "
                  "so Phase 1 will be skipped next time (pass --force-story to regenerate it "
                  "instead)." % story_md, file=sys.stderr)
            return 1, []
        return _undeclared_gate(ctx, story_md, legacy_validate, (0, []))
    try:
        text, parsed = _read_story(ctx, story_md)
        violations = lib.shots_violations(text, parsed, ctx.panels, ctx.members,
                                               ctx.narration is True, ignore_facing=True)
        advisories = lib.shots_advisories(parsed, ctx.members)
    except OSError as e:
        violations, advisories = ["story: cannot read story.md: %s" % e], []
    if violations:
        print("Error: story.md breaks the shot rules:", file=sys.stderr)
        for v in violations:
            print("  - %s" % v, file=sys.stderr)
        print("Hand-edit %s to fix the violations above and rerun, or pass --force-story to "
              "have the story model write a new one." % story_md, file=sys.stderr)
        return 2, []
    return _undeclared_gate(ctx, story_md, legacy_validate, (0, advisories))
```

with:

```python
def recheck(ctx, legacy_validate):
    """Re-check an existing story.md instead of regenerating it (RS28; dialogue spec 6.7).
    Returns (exit code, advisories): 2 only when a blocking violation remains (unresolved T2/T3
    only warn). legacy_validate is bin/ltx-movie's _validate_story_md."""
    story_md = os.path.join(ctx.story_dir, "story.md")
    for warning in catalog_warnings(ctx):
        print(warning)
    lib = _character_lib(ctx.ws)
    plan = load_plan(ctx)
    if plan is not None:
        try:
            hard = ([] if ctx.mode == "shots"
                    else list(legacy_validate(story_md, ctx.panels, ctx.mode == "no_stills")))
            advisory = []
            text, parsed = _read_story(ctx, story_md)
            undeclared = undeclared_characters(ctx)
            writers_by_panel = []
            for k, panel in enumerate(parsed, start=1):
                fields = story_fields(ctx.mode, k, panel, ctx.narration)
                writers = _recheck_writers(ctx, lib, plan, k, fields)
                writers_by_panel.append(writers)
                h, a = _field_checks(ctx, lib, plan, k, panel["title"], fields, writers,
                                     RECHECK_IDS, undeclared)
                hard += h
                advisory += a
            advisory = _order_by_panel(advisory + repeat_advisories(ctx, lib, plan, writers_by_panel))
            if ctx.mode == "shots":
                shots_hard, shots_other = split_shots(lib.shots_violations(
                    text, parsed, ctx.panels, ctx.members, ctx.narration is True,
                    ignore_facing=True))
                hard += shots_hard
                advisory += shots_other + lib.shots_advisories(parsed, ctx.members)
            if ctx.auto_lora:
                compatible = dict((e["id"], e) for e in compatible_entries(ctx))
                catalog = dict((e["id"], e) for e in ctx.catalog.get("entries", []))
                lh, la = lora_checks(ctx, plan, compatible, catalog)
                hard += lh
                advisory += la
            blocking_list, unresolved_list = blocking(hard), unresolved(hard)
            doc = _checks_doc(ctx, {"hard": blocking_list, "advisory": advisory},
                              source="recheck")
            doc["unresolved"] = [parse_violation(m) for m in unresolved_list]
            _write_json(os.path.join(ctx.story_dir, "story_checks.json"), doc)
            if blocking_list:
                print("Error: story.md fails the story checks:", file=sys.stderr)
                for message in blocking_list:
                    print("  - %s" % message, file=sys.stderr)
                print("Hand-edit %s to fix the violations above and rerun, or pass --force-story to "
                      "regenerate it." % story_md, file=sys.stderr)
                if any(parse_violation(m)["id"].startswith("L") for m in blocking_list):
                    print("The L violations come from plan.json's catalog LoRA picks, not from "
                          "story.md: restore or re-add the LoRA files (bin/lora-catalog verify), "
                          "rerun with --no-auto-lora, or pass --force-story to regenerate.",
                          file=sys.stderr)
                return 2, advisory
            for message in unresolved_list:
                print("Warning: unresolved: %s" % message)
            return 0, advisory
        except (KeyError, TypeError, AttributeError, ValueError, IndexError):
            print("note: %s is malformed; re-checking story.md without it"
                  % os.path.join(ctx.story_dir, "plan.json"))
    if ctx.mode != "shots":
        violations = legacy_validate(story_md, ctx.panels, ctx.mode == "no_stills")
        if violations:
            print("Error: story.md failed validation:", file=sys.stderr)
            for v in violations:
                print("  - %s" % v, file=sys.stderr)
            print("Hand-edit %s to fix the violations above and rerun; story.md already exists "
                  "so Phase 1 will be skipped next time (pass --force-story to regenerate it "
                  "instead)." % story_md, file=sys.stderr)
            return 1, []
        return _undeclared_gate(ctx, story_md, legacy_validate, (0, []))
    try:
        text, parsed = _read_story(ctx, story_md)
        violations, others = split_shots(lib.shots_violations(text, parsed, ctx.panels,
                                                              ctx.members, ctx.narration is True,
                                                              ignore_facing=True))
        advisories = others + lib.shots_advisories(parsed, ctx.members)
    except OSError as e:
        violations, advisories = ["story: cannot read story.md: %s" % e], []
    if violations:
        print("Error: story.md breaks the shot rules:", file=sys.stderr)
        for v in violations:
            print("  - %s" % v, file=sys.stderr)
        print("Hand-edit %s to fix the violations above and rerun, or pass --force-story to "
              "have the story model write a new one." % story_md, file=sys.stderr)
        return 2, []
    return _undeclared_gate(ctx, story_md, legacy_validate, (0, advisories))
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_story_engine.py tests/test_lora_catalog.py tests/test_shots_mode.py tests/test_iterate_story.py 2>&1 | tail -1
```

Expected: no failure other than the known `test_rst62_import_sets` (`test_rst14`, `test_rst19`, `test_rst21`, `test_rst31`, `test_rst44c`, `test_rst44f`, `test_rst46`, `test_rst53`, `test_rst55`, `test_rst56`, `test_rst56c`, `test_lct28` and `test_fix1_picks_failing_lora_checks_exit_2` pass unchanged). Compile check with `FILES` = `story_engine.py tests/test_dialogue.py tests/test_story_engine.py`; expected `compiled 3` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_dialogue.py tests/test_story_engine.py
git diff --cached --name-only
git commit -m "feat(dialogue): every rule but timing, action and structure is advisory; re-check blocks only on blocking (6.3, 6.4, 6.7, DLG18, DLG21, DLG25)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: The critic prompt

Implements spec 8.3 and the critic half of CM5. Tests DLG19.

**Files:**
- Modify: `story_engine.py`
- Modify: `tests/test_dialogue.py`
- Modify: `tests/test_story_engine.py` (`test_rst20e_speech_only_framing`: spec 9.2 reason "`critic_field_lines` has no `beat.shot` line"; `test_rst22_critic_prompt`: "header text; no image line; ONLY1 count 0")

**Interfaces:**
- Consumes: Task 13's patch whitelist (the prompt lists exactly the fields `patch_ranges` lets a critic change).
- Produces: `critic_field_lines(mode, catalog_lines, narration=True) -> str` (the lora line when `catalog_lines`, then the motion or prompt line, then the dialogue line unless `narration is False`); the 8.3 header, renderability and patch paragraphs of `CRITIC_PROMPT_TEMPLATE`; no `ONLY1` and no `@@ONLY1@@`.

- [ ] **Step 1: Write the failing tests.**

New test in this task: `test_dlg19_critic_prompt`.

**1.1.** Append to `tests/test_dialogue.py`:

```python
# --- DLG19: the critic prompt (8.3) -----------------------------------------------------------

N12_MESSAGE = "panel 1: N12 one action: Motion: chains actions with 'then'"
MOTION_LINE = ('- target "panel", field "%s", index = the panel number, only for a panel with a '
               "[hard] T2 or T3 problem: replacement is the panel's whole new %s: writer text, "
               "identical to the current text except for the sentence or sentences that hold the "
               "extra or missing action.")
DIALOGUE_FIELD_LINE = ('- target "panel", field "dialogue", index = the panel number, only for a '
                       "panel with a [hard] T1 problem: replacement is the shortened spoken line, "
                       "without the speaker's phrase and without quotation marks, within the "
                       "limit the T1 problem states.")


def test_dlg19_critic_prompt(ws):
    header = ("\nProblems the pipeline's own checks found in this draft. Only the [hard] ones are "
              "fixed by patches; the [advisory] ones are reported to the user and must never be "
              "patched:\n- [hard] " + T2_MESSAGE + "\n- [advisory] " + N12_MESSAGE + "\n")
    render = ("- renderability: every panel shows physical action that a video model can render "
              "in 6 seconds -- neither more actions than fit nor none -- every spoken line fits "
              "its clip, and there is no on-screen text and nothing outside the frame. Camera "
              "directions and dialogue are part of a good panel, never a fault.\n")
    patches = ("Then propose at most 8 patches, most important first, only for the [hard] "
               "problems: a spoken line that does not fit its clip, or a panel with more or fewer "
               "actions than its clip can hold. Each patch is an object with exactly the keys "
               "target, index, field, reason and replacement. The allowed patches are:\n")
    preserve = ("\nPreserve every camera direction, every descriptive sentence and every dialogue "
                "line word for word: change only the sentence or sentences that cause the "
                "problem, and copy every other sentence of the field unchanged. A patch that "
                "changes anything else is rejected. A panel replacement holds only the text the "
                "writer writes: never include a character's description, a setting sentence or "
                "the shot type, because the pipeline adds those itself. The number of panels, the "
                "characters' referring phrases and their descriptions never change.\n")
    for mode in ("chained", "no_stills", "shots"):
        _ctx, plan, _parts, text, _p = _story(ws, mode, 3)
        prompt = se.build_critic_prompt(plan, text, ([T2_MESSAGE], [N12_MESSAGE]))
        for piece in (header, render, patches, preserve):
            assert piece in prompt, (mode, piece[:50])
        field, label = ("prompt", "Prompt") if mode == "no_stills" else ("motion", "Motion")
        lines = [MOTION_LINE % (field, label), DIALOGUE_FIELD_LINE]
        assert se.critic_field_lines(mode, None).split("\n") == lines, mode
        assert se.critic_field_lines(mode, None, False).split("\n") == lines[:1], mode
        assert ("are:\n" + "\n".join(lines) + "\nPreserve") in prompt, mode
        for absent in ("(only 1:", 'field "beat.action"', 'field "image"', 'field "narration"',
                       "@@"):
            assert absent not in prompt, (mode, absent)
    assert se.critic_field_lines("chained", ["- fast-motion: x"]).split("\n")[0].startswith(
        '- target "plan", field "lora", index 0 for the global picks')
    assert not hasattr(se, "ONLY1")
```

**1.2.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    assert "exactly one of: medium shot, medium close-up, close-up." in se.critic_field_lines(
        "shots", None, "speech")
```

with:

```python
    assert 'field "beat.shot"' not in se.critic_field_lines("shots", None, "speech")
```

**1.3.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
        assert "\nProblems the pipeline's own checks found in this draft (fix the hard ones first):"\
               "\n- none\n" in prompt
```

with:

```python
        assert ("\nProblems the pipeline's own checks found in this draft. Only the [hard] ones "
                "are fixed by patches; the [advisory] ones are reported to the user and must "
                "never be patched:\n- none\n") in prompt
```

**1.4.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
        assert has == {"image": mode != "no_stills", "motion": mode != "no_stills",
                       "prompt": mode == "no_stills"}, mode
        assert prompt.count("(only 1: later panels continue the same picture)") == (
            3 if mode == "chained" else 0)
```

with:

```python
        assert has == {"image": False, "motion": mode != "no_stills",
                       "prompt": mode == "no_stills"}, mode
        assert prompt.count("(only 1: later panels continue the same picture)") == 0
```

**1.5.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    block = capped.split("fix the hard ones first):\n", 1)[1].split("\n\nScore the draft", 1)[0]
```

with:

```python
    block = capped.split("must never be patched:\n", 1)[1].split("\n\nScore the draft", 1)[0]
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k dlg19 2>&1 | tail -3
python3 -m pytest -q -p no:cacheprovider tests/test_story_engine.py -k "rst20e or rst22" 2>&1 | tail -3
```

Expected: `1 failed` (the old header), then `2 failed`.

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "Problems the pipeline's own checks found in this draft (fix the hard ones first):\n"
```

with:

```python
    "Problems the pipeline's own checks found in this draft. Only the [hard] ones are fixed by "
    "patches; the [advisory] ones are reported to the user and must never be patched:\n"
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "- renderability: every panel shows one concrete physical action that a video model can "
    "render in @@SECONDS@@ seconds, with no dialogue, no on-screen text and nothing outside the "
    "frame.\n"
```

with:

```python
    "- renderability: every panel shows physical action that a video model can render in "
    "@@SECONDS@@ seconds -- neither more actions than fit nor none -- every spoken line fits its "
    "clip, and there is no on-screen text and nothing outside the frame. Camera directions and "
    "dialogue are part of a good panel, never a fault.\n"
```

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "Then propose at most 8 patches, most important first. Each patch is an object with exactly "
    "the keys target, index, field, reason and replacement. The allowed patches are:\n"
    "@@FIELD_LINES@@\n"
    "A panel replacement holds only the text the writer writes: never include a character's "
    "description, a setting sentence, the shot type or a camera sentence, because the pipeline "
    "adds those itself. The number of panels, the characters' referring phrases and their "
    "descriptions never change.\n"
```

with:

```python
    "Then propose at most 8 patches, most important first, only for the [hard] problems: a "
    "spoken line that does not fit its clip, or a panel with more or fewer actions than its clip "
    "can hold. Each patch is an object with exactly the keys target, index, field, reason and "
    "replacement. The allowed patches are:\n"
    "@@FIELD_LINES@@\n"
    "Preserve every camera direction, every descriptive sentence and every dialogue line word for "
    "word: change only the sentence or sentences that cause the problem, and copy every other "
    "sentence of the field unchanged. A patch that changes anything else is rejected. A panel "
    "replacement holds only the text the writer writes: never include a character's description, "
    "a setting sentence or the shot type, because the pipeline adds those itself. The number of "
    "panels, the characters' referring phrases and their descriptions never change.\n"
```

**3.4.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
                       "only.")
ONLY1 = " (only 1: later panels continue the same picture)"
```

with:

```python
                       "only.")
```

**3.5.** Edit `story_engine.py`: replace the whole of `critic_field_lines`, this text, which occurs exactly once:

```python
def critic_field_lines(mode, catalog_lines, narration=True):
    lines = [
        '- target "plan", field "beat.action", index = the beat number: replacement is the beat\'s '
        "new action, one sentence of 6 to 40 words; the pipeline rewrites that panel from it.",
        '- target "plan", field "beat.shot", index = the beat number@@ONLY1@@: replacement is '
        "exactly one of: " + ", ".join(shot_types(narration)) + ".",
        '- target "plan", field "beat.camera", index = the beat number@@ONLY1@@: replacement is '
        "exactly one of: " + ", ".join(CAMERA_KEYS) + ".",
        '- target "plan", field "location.setting", index = the place\'s position in the plan\'s '
        "locations list (1 is the first): replacement is its new setting sentence, 12 to 45 "
        'words starting "The setting is"; it replaces that sentence in every panel at that '
        "place."]
    if catalog_lines:
        lines.append('- target "plan", field "lora", index 0 for the global picks or a beat '
                     "number for that beat's own picks: replacement is the complete new list of "
                     "picks, each an object with the keys id and strength, from this catalog:"
                     + "\n" + "\n".join(catalog_lines))
    if mode in ("chained", "shots"):
        lines.append('- target "panel", field "image", index = the panel number@@ONLY1@@: '
                     "replacement is the new writer text of that panel's Image: field.")
        lines.append('- target "panel", field "motion", index = the panel number: replacement is '
                     "the new writer text of that panel's Motion: field.")
    else:
        lines.append('- target "panel", field "prompt", index = the panel number: replacement is '
                     "the new writer text of that panel's Prompt: field.")
    if narration:
        lines.append('- target "panel", field "narration", index = the panel number: replacement '
                     "is the panel's new narration sentence (prefixed with the speaker's referring "
                     "phrase and a colon when a character in the shot says it).")
    return "\n".join(lines)
```

with:

```python
def critic_field_lines(mode, catalog_lines, narration=True):
    """The allowed-patch lines of the critic prompt (dialogue spec 8.3): the lora line when
    catalog_lines is set, the Motion: (Prompt: in no_stills) line for a T2/T3 panel, and the
    dialogue line for a T1 panel unless the movie has no spoken lines."""
    lines = []
    if catalog_lines:
        lines.append('- target "plan", field "lora", index 0 for the global picks or a beat '
                     "number for that beat's own picks: replacement is the complete new list of "
                     "picks, each an object with the keys id and strength, from this catalog:"
                     + "\n" + "\n".join(catalog_lines))
    label = "Prompt" if mode == "no_stills" else "Motion"
    lines.append('- target "panel", field "%s", index = the panel number, only for a panel with a '
                 "[hard] T2 or T3 problem: replacement is the panel's whole new %s: writer text, "
                 "identical to the current text except for the sentence or sentences that hold "
                 "the extra or missing action." % (label.lower(), label))
    if narration is not False:
        lines.append('- target "panel", field "dialogue", index = the panel number, only for a '
                     "panel with a [hard] T1 problem: replacement is the shortened spoken line, "
                     "without the speaker's phrase and without quotation marks, within the limit "
                     "the T1 problem states.")
    return "\n".join(lines)
```

**3.6.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        ("@@FIELD_LINES@@", critic_field_lines(plan["mode"], catalog_lines, narration)),
        ("@@ONLY1@@", ONLY1 if plan["mode"] == "chained" else ""),
```

with:

```python
        ("@@FIELD_LINES@@", critic_field_lines(plan["mode"], catalog_lines, narration)),
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_story_engine.py 2>&1 | tail -1
grep -c "ONLY1" story_engine.py
```

Expected: no failure other than the known `test_rst62_import_sets` (`test_rst48_judge_story_patches` passes unchanged: it compares against `se.build_critic_prompt` itself); the `grep -c` prints `0`. Compile check with `FILES` = `story_engine.py tests/test_dialogue.py tests/test_story_engine.py`; expected `compiled 3` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_dialogue.py tests/test_story_engine.py
git diff --cached --name-only
git commit -m "feat(dialogue): critic prompt asks only for timing and action patches and to keep camera, description and dialogue (8.3, DLG19)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 16: bin/judge-story: the default goal and the dialogue patch field

Implements CM5 (the judge-story bullet), the `PATCH_FIELDS` bullet of 8.3, G5 and controller ruling Q2 (judge-story reports `unresolved` T2/T3 as advisory; Spec amendment 2). Tests DLG30 and `test_judge_story_reports_unresolved_as_advisory`.

**Files:**
- Modify: `bin/judge-story`
- Modify: `tests/test_dialogue.py`
- Modify: `tests/test_judge_story.py` (`test_goal_default_prompt_byte_identical`: spec 9.2 reason "new `DEFAULT_GOAL`; re-baseline the length (2223) and the SHA")

**Interfaces:**
- Consumes: nothing new.
- Produces: `bin/judge-story.DEFAULT_GOAL = "the most realistic action scenes possible, with any spoken lines delivered on camera by the character who says them"`; `PATCH_FIELDS` ends with `"dialogue"` (so `SUBMIT_REVIEW_SCHEMA` accepts dialogue patches); `_story_checks_messages(story_dir) -> (hard, advisory)` puts the `unresolved` messages first in advisory (never in hard; a file without `unresolved` reads as before). The default-goal `SYSTEM_PROMPT` is then 2264 characters with sha256 `63e5219eed17241bc56a72395afa8ece3a9edb920e373da9a25017dbc05761b1` (computed from the `fed1107` template with the new goal substituted).

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_dlg30_judge_story_goal_and_patch_fields`, `test_judge_story_reports_unresolved_as_advisory`.

**1.1.** Append to `tests/test_dialogue.py`:

```python
# --- DLG30: bin/judge-story (CM5, G5) --------------------------------------------------------

def test_dlg30_judge_story_goal_and_patch_fields():
    judge_story = _judge("judge_story_for_dialogue", "bin/judge-story")
    assert judge_story.DEFAULT_GOAL == ("the most realistic action scenes possible, with any "
                                        "spoken lines delivered on camera by the character who "
                                        "says them")
    assert judge_story.PATCH_FIELDS == ("beat.action", "beat.shot", "beat.camera",
                                        "location.setting", "lora", "motion", "image", "prompt",
                                        "narration", "dialogue")
    assert '"dialogue"' in json.dumps(judge_story.SUBMIT_REVIEW_SCHEMA)


def test_judge_story_reports_unresolved_as_advisory(tmp_path):
    # Controller ruling Q2 (Spec amendment 2): unresolved T2/T3 reach the judge as [advisory].
    judge_story = _judge("judge_story_for_dialogue", "bin/judge-story")
    checks = {"hard": [{"message": "panel 2: T1 spoken timing: x"}],
              "unresolved": [{"message": T2_MESSAGE}],
              "advisory": [{"message": N12_MESSAGE}]}
    (tmp_path / "story_checks.json").write_text(json.dumps(checks), encoding="utf-8")
    assert judge_story._story_checks_messages(str(tmp_path)) == (
        ["panel 2: T1 spoken timing: x"], [T2_MESSAGE, N12_MESSAGE])
    del checks["unresolved"]
    (tmp_path / "story_checks.json").write_text(json.dumps(checks), encoding="utf-8")
    assert judge_story._story_checks_messages(str(tmp_path)) == (
        ["panel 2: T1 spoken timing: x"], [N12_MESSAGE])
```

**1.2.** Edit `tests/test_judge_story.py`: replace this text, which occurs exactly once:

```python
# sha256 of the SYSTEM_PROMPT constant at commit 1d8580b, before --goal existed (2223 chars).
LEGACY_SYSTEM_PROMPT_SHA256 = "39be908ef72c563313398c1a0f1ff4a69bd948a0e5f90c030aaea879694cb97b"
```

with:

```python
# sha256 of the default-goal SYSTEM_PROMPT since the on-camera dialogue goal (dialogue spec
# CM5; 2264 chars). Before it: 39be908e... (2223 chars), the constant at commit 1d8580b.
LEGACY_SYSTEM_PROMPT_SHA256 = "63e5219eed17241bc56a72395afa8ece3a9edb920e373da9a25017dbc05761b1"
```

**1.3.** Edit `tests/test_judge_story.py`: replace this text, which occurs exactly once:

```python
    assert judge_story.DEFAULT_GOAL == ("the most realistic action scenes possible, with "
                                        "relatively little dialogue")
```

with:

```python
    assert judge_story.DEFAULT_GOAL == ("the most realistic action scenes possible, with any "
                                        "spoken lines delivered on camera by the character who "
                                        "says them")
```

**1.4.** Edit `tests/test_judge_story.py`: replace this text, which occurs exactly once:

```python
    assert len(rendered) == 2223
```

with:

```python
    assert len(rendered) == 2264
```

**1.5.** Edit `tests/test_judge_story.py`: replace this text, which occurs exactly once:

```python
    assert ("The target output goal is the most realistic action scenes possible, with "
            "relatively little dialogue.\n") in rendered
```

with:

```python
    assert ("The target output goal is the most realistic action scenes possible, with any "
            "spoken lines delivered on camera by the character who says them.\n") in rendered
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k "dlg30 or unresolved_as_advisory" 2>&1 | tail -3
python3 -m pytest -q -p no:cacheprovider tests/test_judge_story.py -k goal_default 2>&1 | tail -3
```

Expected: `2 failed` (the old goal; `unresolved` is not read), then `1 failed` (`test_goal_default_prompt_byte_identical`, on the old goal).

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/judge-story`: replace this text, which occurs exactly once:

```python
DEFAULT_GOAL = "the most realistic action scenes possible, with relatively little dialogue"
```

with:

```python
DEFAULT_GOAL = ("the most realistic action scenes possible, with any spoken lines delivered on "
                "camera by the character who says them")
```

**3.2.** Edit `bin/judge-story`: replace this text, which occurs exactly once:

```python
PATCH_FIELDS = ("beat.action", "beat.shot", "beat.camera", "location.setting", "lora", "motion",
                "image", "prompt", "narration")
```

with:

```python
PATCH_FIELDS = ("beat.action", "beat.shot", "beat.camera", "location.setting", "lora", "motion",
                "image", "prompt", "narration", "dialogue")
```

**3.3.** Edit `bin/judge-story`: replace this text, which occurs exactly once (in `_story_checks_messages`):

```python
        return ([v["message"] for v in checks["hard"]],
                [v["message"] for v in checks["advisory"]])
```

with:

```python
        # Unresolved T2/T3 (never blocking) are reported as advisory (dialogue spec 2.6, D6).
        return ([v["message"] for v in checks["hard"]],
                [v["message"] for v in checks.get("unresolved", [])]
                + [v["message"] for v in checks["advisory"]])
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_judge_story.py 2>&1 | tail -1
python3 -m pytest -q -p no:cacheprovider tests/test_story_engine.py -k "rst48 or rst2_" 2>&1 | tail -1
```

Expected: `passed`, no failure. Compile check with `FILES` = `bin/judge-story tests/test_dialogue.py tests/test_judge_story.py`; expected `compiled 3` twice.

- [ ] **Step 5: Commit.**

```bash
git add bin/judge-story tests/test_dialogue.py tests/test_judge_story.py
git diff --cached --name-only
git commit -m "feat(dialogue): judge-story goal wants on-camera speech; dialogue is a patch field; unresolved T2/T3 read as advisory (CM5, Q2, DLG30)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 17: bin/judge-clips: the Dialogue rule and the panel text

Implements CM5 (the judge-clips bullets) and G6. Tests DLG29.

**Files:**
- Modify: `bin/judge-clips`
- Modify: `tests/test_dialogue.py`
- Modify: `tests/test_judge_clips.py` (`test_goal_default_prompt_byte_identical`: spec 9.2 reason "re-baseline the length and the SHA")

Interaction with the known failures: `tests/test_judge_clips.py::test_goal_default_prompt_byte_identical` already fails at `fed1107` (its pins date from before the earlier Narration-speaker sentence: the prompt is 3266 characters, not 3166). This task's re-baseline pins the new prompt, so the test passes from here on and leaves the known-failure list; record that in Task 24's comparison.

**Interfaces:**
- Consumes: Task 5's manifest keys `speaker`, `speech`, `speech_source`.
- Produces: the system prompt sentence `A Dialogue: text is a line the named character speaks on camera in that panel's clip; Narration: text is voice-over.` (default-goal `SYSTEM_PROMPT`: 3200 characters, sha256 `bd5a50ea1f7a581bc53cb978c41e4600e10cb76a01fa17389b99889cbc1d1453`, computed from the `fed1107` template with this sentence in place of the old one); `format_panel_text(number, panel)` with a `Dialogue:` line.

- [ ] **Step 1: Write the failing tests.**

New test in this task: `test_dlg29_judge_clips_panel_text`.

**1.1.** Append to `tests/test_dialogue.py`:

```python
# --- DLG29: bin/judge-clips (CM5, G6) --------------------------------------------------------

def test_dlg29_judge_clips_panel_text():
    judge_clips = _judge("judge_clips_for_dialogue", "bin/judge-clips")
    base = {"index": 2, "title": "Gate", "motion_prompt": "The courier waits.", "image_path": None}
    head = "## Panel 2 — Gate\nMotion: The courier waits.\n"
    assert judge_clips.format_panel_text(2, dict(
        base, speaker="the courier", speech="Keep moving.", speech_source="dialogue",
        narration="The bell had not rung.")) == (
        head + "Dialogue: the courier: Keep moving.\nNarration: The bell had not rung.")
    alias = dict(base, speaker="the courier", speech="Keep moving.", speech_source="narration",
                 narration="the courier: Keep moving.")
    assert judge_clips.format_panel_text(2, alias) == head + "Dialogue: the courier: Keep moving."
    older = dict(alias)
    del older["speech_source"]
    assert judge_clips.format_panel_text(2, older) == head + "Dialogue: the courier: Keep moving."
    assert judge_clips.format_panel_text(2, dict(base, narration="Rain fell.")) == (
        head + "Narration: Rain fell.")
    assert ("A Dialogue: text is a line the named character speaks on camera in that panel's clip; "
            "Narration: text is voice-over.") in judge_clips.SYSTEM_PROMPT
    assert "starts with a character's referring phrase and a colon" not in judge_clips.SYSTEM_PROMPT
```

**1.2.** Edit `tests/test_judge_clips.py`: replace this text, which occurs exactly once:

```python
# sha256 of the SYSTEM_PROMPT constant at commit 1d8580b, before --goal existed (3166 chars).
LEGACY_SYSTEM_PROMPT_SHA256 = "ac604f73c470bae702f8380aab81418258ea9cc3e9db75f26a319f2342594c3d"
```

with:

```python
# sha256 of the default-goal SYSTEM_PROMPT since its Dialogue: rule (dialogue spec CM5; 3200
# chars). Before it: ac604f73... (3166 chars), the constant at commit 1d8580b.
LEGACY_SYSTEM_PROMPT_SHA256 = "bd5a50ea1f7a581bc53cb978c41e4600e10cb76a01fa17389b99889cbc1d1453"
```

**1.3.** Edit `tests/test_judge_clips.py`: replace this text, which occurs exactly once:

```python
    assert len(rendered) == 3166
```

with:

```python
    assert len(rendered) == 3200
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k dlg29 2>&1 | tail -3
python3 -m pytest -q -p no:cacheprovider tests/test_judge_clips.py -k "goal_default or t6_format" 2>&1 | tail -3
```

Expected: `1 failed`, then `1 failed, 1 passed` (`test_goal_default_prompt_byte_identical` fails on the length, as at the baseline; `test_t6_format_panel_text` passes and must keep passing).

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/judge-clips`: replace this text, which occurs exactly once:

```python
    "music, or sound effects. A Narration: text that starts with a character's referring "
    "phrase and a colon is a line that character speaks on camera in that panel's clip; any "
    "other Narration: text is voice-over.\n"
```

with:

```python
    "music, or sound effects. A Dialogue: text is a line the named character speaks on camera "
    "in that panel's clip; Narration: text is voice-over.\n"
```

**3.2.** Edit `bin/judge-clips`: replace the whole of `format_panel_text`, this text, which occurs exactly once:

```python
def format_panel_text(number, panel):
    """Header, then Opening still: (panel 1 only, when it has a still), Motion:, Narration:,
    each only when non-empty; no trailing newline (spec 3.7). Pure."""
    title = _text_field(panel, "title")
    lines = ["## Panel %d — %s" % (number, title) if title else "## Panel %d —" % number]
    if number == 1 and _text_field(panel, "image_path"):
        opening = _text_field(panel, "panel_text")
        if opening:
            lines.append("Opening still: %s" % opening)
    for label, key in (("Motion", "motion_prompt"), ("Narration", "narration")):
        value = _text_field(panel, key)
        if value:
            lines.append("%s: %s" % (label, value))
    return "\n".join(lines)
```

with:

```python
def format_panel_text(number, panel):
    """Header, then Opening still: (panel 1 only, when it has a still), Motion:, Dialogue: (the
    manifest's speaker and speech, when both are set), Narration:, each only when non-empty; a
    Narration: that is itself the spoken line (speech_source "narration", or an older manifest
    with a speaker and no speech_source) is left out. No trailing newline (spec 3.7; dialogue
    spec CM5). Pure."""
    title = _text_field(panel, "title")
    lines = ["## Panel %d — %s" % (number, title) if title else "## Panel %d —" % number]
    if number == 1 and _text_field(panel, "image_path"):
        opening = _text_field(panel, "panel_text")
        if opening:
            lines.append("Opening still: %s" % opening)
    motion = _text_field(panel, "motion_prompt")
    if motion:
        lines.append("Motion: %s" % motion)
    speaker, speech = _text_field(panel, "speaker"), _text_field(panel, "speech")
    if speaker and speech:
        lines.append("Dialogue: %s: %s" % (speaker, speech))
    narration = _text_field(panel, "narration")
    source = panel.get("speech_source", "narration" if panel.get("speaker") else None)
    if narration and source != "narration":
        lines.append("Narration: %s" % narration)
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_judge_clips.py 2>&1 | tail -1
```

Expected: `passed`, no failure (`test_goal_default_prompt_byte_identical` now passes). Compile check with `FILES` = `bin/judge-clips tests/test_dialogue.py tests/test_judge_clips.py`; expected `compiled 3` twice.

- [ ] **Step 5: Commit.**

```bash
git add bin/judge-clips tests/test_dialogue.py tests/test_judge_clips.py
git diff --cached --name-only
git commit -m "feat(dialogue): judge-clips reads Dialogue: as on-camera speech (CM5, DLG29)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 18: bin/ltx-movie --speech-delivery

Implements DG8. Tests DLG27.

**Files:**
- Modify: `bin/ltx-movie`
- Modify: `tests/test_dialogue.py`

**Interfaces:**
- Consumes: Task 5's manifest flag `--speech-delivery`.
- Produces: `bin/ltx-movie --speech-delivery {beats,plain,beats-no-acoustic}` (`args.speech_delivery`, default `"beats"`, right after `--speech-only`); Phase 3 and the dry-run manifest command add `--speech-delivery <value>` only when the value is not `beats`.

- [ ] **Step 1: Write the failing test.**

New test in this task: `test_dlg27_speech_delivery_reaches_the_manifest`.

**1.1.** Append to `tests/test_dialogue.py`:

```python
# --- DLG27: bin/ltx-movie --speech-delivery (DG8) --------------------------------------------

def test_dlg27_speech_delivery_reaches_the_manifest(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ltx_movie, "WS", seu.make_ws(tmp_path))
    assert ltx_movie.build_parser().parse_args(["n", "--story-id", "x"]).speech_delivery == "beats"
    calls = []
    monkeypatch.setattr(ltx_movie.subprocess, "run",
                        lambda cmd, **kw: calls.append(list(cmd)) or _Done())
    for delivery in ("beats", "plain", "beats-no-acoustic"):
        calls[:] = []
        argv = ["n", "--story-id", "sd1", "--panels", "3", "--no-review"]
        if delivery != "beats":
            argv += ["--speech-delivery", delivery]
        assert ltx_movie.phase3_manifest(_movie_args(*argv)) == 0
        manifest = calls[0]
        assert "ltx-story-manifest" in manifest[1]
        assert ("--speech-delivery" in manifest) == (delivery != "beats"), delivery
        if delivery != "beats":
            assert manifest[manifest.index("--speech-delivery") + 1] == delivery
    for flags, expected in (([], None), (["--speech-delivery", "plain"], "plain"),
                            (["--story-legacy", "--speech-delivery", "beats-no-acoustic"],
                             "beats-no-acoustic")):
        capsys.readouterr()
        assert ltx_movie.main(["n", "--story-id", "sd2", "--panels", "3", "--dry-run",
                               "--no-review"] + flags) == 0, flags
        line = [l for l in capsys.readouterr().out.splitlines()
                if l.startswith("Command: ") and "ltx-story-manifest" in l][0]
        if expected is None:
            assert "--speech-delivery" not in line
        else:
            assert line.endswith(" --force --speech-delivery " + expected), line
```

- [ ] **Step 2: Run the test and confirm it fails.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k dlg27 2>&1 | tail -3
```

Expected: `1 failed` (`AttributeError: 'Namespace' object has no attribute 'speech_delivery'`).

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    parser.add_argument("--speech-only", dest="speech_only", action="store_true", default=False,
                         help="Narration: is only ever a character's spoken line (\"the courier: "
                              "...\"), never voice-over, and may be empty; panels share the "
                              "length equally. Needs the default story engine.")
```

with:

```python
    parser.add_argument("--speech-only", dest="speech_only", action="store_true", default=False,
                         help="Narration: is only ever a character's spoken line (\"the courier: "
                              "...\"), never voice-over, and may be empty; panels share the "
                              "length equally. Needs the default story engine.")
    parser.add_argument("--speech-delivery", dest="speech_delivery",
                         choices=["beats", "plain", "beats-no-acoustic"], default="beats",
                         help="how spoken lines reach the video model (bin/ltx-story-manifest "
                              "--speech-delivery): beats (default), beats-no-acoustic, or plain, "
                              "the earlier '<Speaker> says: \"...\"' form, for A/B comparison")
```

**3.2.** Edit `bin/ltx-movie`: replace (in `phase3_manifest`) this text, which occurs exactly once:

```python
    if getattr(args, "no_narration", False) or getattr(args, "speech_only", False):
        cmd_manifest += ["--pace", "equal"]
```

with:

```python
    if getattr(args, "no_narration", False) or getattr(args, "speech_only", False):
        cmd_manifest += ["--pace", "equal"]
    if getattr(args, "speech_delivery", "beats") != "beats":
        cmd_manifest += ["--speech-delivery", args.speech_delivery]
```

**3.3.** Edit `bin/ltx-movie`: replace (in the dry run's Phase 3 block) this text, which occurs exactly once:

```python
    if getattr(args, "no_narration", False) or getattr(args, "speech_only", False):
        phase3_manifest_cmd += ["--pace", "equal"]
```

with:

```python
    if getattr(args, "no_narration", False) or getattr(args, "speech_only", False):
        phase3_manifest_cmd += ["--pace", "equal"]
    if getattr(args, "speech_delivery", "beats") != "beats":
        phase3_manifest_cmd += ["--speech-delivery", args.speech_delivery]
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_casting_regression.py tests/test_lora_catalog.py 2>&1 | tail -1
python3 -m pytest -q -p no:cacheprovider tests/test_story_engine.py -k "rst41 or rst47 or rst50" 2>&1 | tail -1
python3 tests/test_ltx_movie_offline.py 2>&1 | tail -1
```

Expected: no failure (the `--story-legacy` dry-run golden is unchanged: the default adds nothing); the offline script prints `OK n/n` with the baseline `n`. Compile check with `FILES` = `bin/ltx-movie tests/test_dialogue.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add bin/ltx-movie tests/test_dialogue.py
git diff --cached --name-only
git commit -m "feat(dialogue): ltx-movie --speech-delivery reaches the Phase 3 manifest (DG8, DLG27)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 19: bin/ltx-movie docstring, help and dry-run text

Implements spec 6.8 (the `--judge` help and the dry-run judge line), 6.9 and CM6 (the `--story-legacy` help sentence). Tests: the `test_rst47` edit and `test_ltx_movie_dialogue_help_and_docstring_text`.

**Files:**
- Modify: `bin/ltx-movie`
- Modify: `tests/test_dialogue.py`
- Modify: `tests/test_story_engine.py` (`test_rst47_robust_dry_run`: spec 9.2 reason "6.8 and 6.9 lines")

**Interfaces:**
- Consumes: nothing new.
- Produces: the exact 6.8/6.9/CM6 strings in `bin/ltx-movie`'s module docstring, `--judge` and `--story-legacy` help, and the robust dry run.

- [ ] **Step 1: Write the failing tests.**

New test in this task: `test_ltx_movie_dialogue_help_and_docstring_text`.

**1.1.** Append to `tests/test_dialogue.py`:

```python
# --- 6.8, 6.9, CM6: bin/ltx-movie text ---------------------------------------------------------

def test_ltx_movie_dialogue_help_and_docstring_text():
    actions = ltx_movie.build_parser()._option_string_actions
    assert actions["--judge"].help == (
        "after the local critic rounds, run bin/judge-story --patches (Claude; needs "
        "ANTHROPIC_API_KEY) as a final report: its scores go into story_checks.json and its "
        "patches are saved, never applied")
    assert actions["--story-legacy"].help.endswith(
        " It does not ask for Dialogue: lines; a prefixed Narration: line still renders as "
        "dialogue.")
    doc = " ".join(ltx_movie.__doc__.split())
    assert ("up to two local critic rounds that repair only spoken timing and the amount of action"
            in doc)
    assert "when blocking violations remain" in doc and "up to three local critic rounds" not in doc
```

**1.2.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
            "Story engine: a JSON plan, one call per panel, deterministic checks and up to 3 "
            "critic rounds (analyst via the local qwen-agentd, else a local one-shot); "
            "--story-legacy for the single-prompt path.",
```

with:

```python
            "Story engine: a JSON plan, one call per panel, deterministic checks and up to 2 "
            "critic rounds that repair only spoken timing and the amount of action (analyst via "
            "the local qwen-agentd, else a local one-shot); --story-legacy for the single-prompt "
            "path.",
```

**1.3.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
            assert block[4] == "Judge gate: bin/judge-story --patches after the critic rounds."
```

with:

```python
            assert block[4] == "Judge gate: bin/judge-story --patches after the critic rounds (report only)."
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k help_and_docstring 2>&1 | tail -3
python3 -m pytest -q -p no:cacheprovider tests/test_story_engine.py -k rst47 2>&1 | tail -3
```

Expected: `1 failed` twice.

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/ltx-movie`: replace (the module docstring) this text, which occurs exactly once:

```python
itself, runs deterministic checks and up to three local critic rounds (the fleet analyst skill),
and exits 2 with story.md, plan.json and story_checks.json saved when hard violations remain; a
rerun re-checks the existing story.md. --judge adds bin/judge-story --patches as a final gate;
```

with:

```python
itself, runs deterministic checks and up to two local critic rounds that repair only spoken
timing and the amount of action (the fleet analyst skill), and exits 2 with story.md, plan.json
and story_checks.json saved when blocking violations remain; a rerun re-checks the existing
story.md. --judge adds bin/judge-story --patches as a final gate;
```

**3.2.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
                         help="after the local critic rounds, run bin/judge-story --patches (Claude; "
                              "needs ANTHROPIC_API_KEY) as a final gate; a minimum score below 7 "
                              "applies its patches and runs one more critic round")
```

with:

```python
                         help="after the local critic rounds, run bin/judge-story --patches (Claude; "
                              "needs ANTHROPIC_API_KEY) as a final report: its scores go into "
                              "story_checks.json and its patches are saved, never applied")
```

**3.3.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
                              "writes story.md), exactly as before the robust story engine. See "
                              "docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md.")
```

with:

```python
                              "writes story.md), exactly as before the robust story engine. See "
                              "docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md. "
                              "It does not ask for Dialogue: lines; a prefixed Narration: line still "
                              "renders as dialogue.")
```

**3.4.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    print("Story engine: a JSON plan, one call per panel, deterministic checks and up to 3 critic "
          "rounds (analyst via the local qwen-agentd, else a local one-shot); --story-legacy for "
          "the single-prompt path.")
```

with:

```python
    print("Story engine: a JSON plan, one call per panel, deterministic checks and up to 2 critic "
          "rounds that repair only spoken timing and the amount of action (analyst via the local "
          "qwen-agentd, else a local one-shot); --story-legacy for the single-prompt path.")
```

**3.5.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
        print("Judge gate: bin/judge-story --patches after the critic rounds.")
```

with:

```python
        print("Judge gate: bin/judge-story --patches after the critic rounds (report only).")
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_story_engine.py tests/test_casting_regression.py tests/test_shots_mode.py 2>&1 | tail -1
python3 tests/test_ltx_movie_offline.py 2>&1 | tail -1
```

Expected: no failure other than the known `test_rst62_import_sets` (`test_rst40`, `test_rst41`, `test_s52` and the B1 golden are unchanged: the legacy Phase 1 prints none of these lines, and `--help` is not golden-pinned); `OK n/n` with the baseline `n`. Compile check with `FILES` = `bin/ltx-movie tests/test_dialogue.py tests/test_story_engine.py`; expected `compiled 3` twice.

- [ ] **Step 5: Commit.**

```bash
git add bin/ltx-movie tests/test_dialogue.py tests/test_story_engine.py
git diff --cached --name-only
git commit -m "docs(dialogue): ltx-movie help, docstring and dry run describe the two timing-only rounds and the report-only judge (6.8, 6.9, CM6)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 20: character_lib casting helpers: name and trigger matching, the trigger prefix, one strength

Implements spec 11.3 (the `cast_text` passes and `member_referenced`), the `prefix_character_triggers` rule of 11.4 and `story_strength` of 11.5. Tests CA2, CA7, CA9.

**Files:**
- Modify: `character_lib.py`
- Modify: `tests/test_dialogue.py`

**Interfaces:**
- Consumes: Task 3's `cast_text(text, members, insert=None, skip_quoted=False)`.
- Produces: `cast_text(text, members, insert=None, skip_quoted=False, match_names=False) -> (text, names)` (byte-identical to before with the defaults); `member_referenced(text, member) -> bool`; `story_strength(member, character_strength) -> float`; `prefix_character_triggers(prompt, triggers) -> str`. `panel_strengths`, `SINGLE_CHARACTER_STRENGTH` and `SHOTS_CHARACTER_STRENGTH` are unchanged.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_ca2_name_and_trigger_matching`, `test_ca7_cast_text_defaults_are_unchanged`, `test_ca9_member_referenced_and_prefix_character_triggers`.

**1.1.** Append to `tests/test_dialogue.py`:

```python
# --- CA2, CA7, CA9: casting helpers (11.3-11.5) ----------------------------------------------

def test_ca2_name_and_trigger_matching(story_env):
    members = _members(story_env, "kyra", "ronin")

    def cast(text):
        return character_lib.cast_text(text, members, skip_quoted=True, match_names=True)

    assert cast("Kyra turns.") == ("kyrawmn Kyra turns.", ["kyra"])
    assert cast("kyrawmn Kyra turns.") == ("kyrawmn Kyra turns.", ["kyra"])
    assert cast("A ronin waits.") == ("A ronin waits.", [])
    assert cast("the old ronin waits") == ("the old ronin waits", [])
    assert cast("kyrawmn") == ("kyrawmn", ["kyra"])
    assert cast('She says, "Kyra, wait."') == ('She says, "Kyra, wait."', [])
    assert cast("The ronin bows to Kyra.") == ("The roninmn ronin bows to kyrawmn Kyra.",
                                               ["kyra", "ronin"])
    assert character_lib.cast_text("Kyra turns.", members) == ("Kyra turns.", [])


def test_ca7_cast_text_defaults_are_unchanged(story_env):
    members = _members(story_env, "kyra", "ronin")
    for text, expected in (
            ("The woman in grey turns her head; the camera stays static.",
             ("The kyrawmn woman in grey turns her head; the camera stays static.", ["kyra"])),
            ("The ronin nods to the woman in grey.",
             ("The roninmn ronin nods to the kyrawmn woman in grey.", ["kyra", "ronin"])),
            ("Leaves drift across the empty trail.", ("Leaves drift across the empty trail.", []))):
        assert character_lib.cast_text(text, members) == expected, text
        assert character_lib.cast_text(text, members, skip_quoted=True,
                                       match_names=True) == expected, text
    assert character_lib.cast_text("The woman in grey and the ronin", members,
                                   insert={"kyra"}) == ("The kyrawmn woman in grey and the ronin",
                                                        ["kyra"])


def test_ca9_member_referenced_and_prefix_character_triggers(story_env):
    kyra = _members(story_env, "kyra")[0]
    for text, expected in (("The woman in grey turns.", True), ("Kyra turns.", True),
                           ("kyrawmn turns.", True), ("She turns her head.", False),
                           ('She says, "Kyra, wait."', False), ("a kyra doll", False)):
        assert character_lib.member_referenced(text, kyra) is expected, text
    prefix = character_lib.prefix_character_triggers
    assert prefix("She turns.", ["kyrawmn"]) == "kyrawmn. She turns."
    assert prefix("She turns.", ["kyrawmn", "KyraWmn", "roninmn"]) == "kyrawmn, roninmn. She turns."
    assert prefix("kyrawmn turns.", ["kyrawmn"]) == "kyrawmn turns."
    assert prefix("She turns.", []) == "She turns."
    assert prefix("the kyrawmn-like blur", ["kyrawmn"]) == "kyrawmn. the kyrawmn-like blur"
    assert character_lib.story_strength(kyra, 0.8) == 0.8
    assert character_lib.story_strength(kyra._replace(strength=0.5), 0.8) == 0.5
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k "ca2 or ca7 or ca9" 2>&1 | tail -3
```

Expected: `3 failed` (`TypeError: cast_text() got an unexpected keyword argument 'match_names'`; `AttributeError ... 'member_referenced'`).

- [ ] **Step 3: Implement.**

**3.1.** Edit `character_lib.py`: replace the whole of `cast_text` (as Task 3 left it), this text, which occurs exactly once:

```python
def cast_text(text, members, insert=None, skip_quoted=False):
    """(text with each cast phrase's trigger inserted, sorted names of the members found).
    Longest phrase first; a match overlapping an already-claimed span is ignored; an
    occurrence that already carries the trigger is counted but not re-inserted (spec 3.6).
    insert: if given, a set of names; every member still claims its spans, but only these
    members get a trigger and are reported. skip_quoted: a match lying wholly inside a "..."
    span (a spoken line) is neither triggered nor reported (dialogue spec DG6)."""
    quoted = [m.span() for m in re.finditer(r'"[^"]*"', text)] if skip_quoted else []
    found = []
    for member in sorted(members, key=lambda m: (-len(m.phrase), m.phrase.lower(), m.name)):
        for match in _phrase_regex(member.phrase, member.trigger).finditer(text):
            start, end = match.span()
            if any(s <= start and end <= e for s, e in quoted):
                continue
            if any(start < e and s < end for s, e, _, _ in found):
                continue
            found.append((start, end, member, match.group("trig") is not None))
    out = text
    for start, _end, member, already in sorted(found, key=lambda f: f[0], reverse=True):
        if already or (insert is not None and member.name not in insert):
            continue
        words = member.phrase.split()
        if len(words) > 1 and words[0].lower() in ARTICLES:
            cut = start + len(words[0])
            out = out[:cut] + " " + member.trigger + out[cut:]
        else:
            out = out[:start] + member.trigger + " " + out[start:]
    return out, sorted({member.name for _, _, member, _ in found
                        if insert is None or member.name in insert})
```

with:

```python
def cast_text(text, members, insert=None, skip_quoted=False, match_names=False):
    """(text with each cast member's trigger inserted, sorted names of the members found)
    (casting spec 3.6; dialogue spec DG6, 11.3). Spans are claimed in up to three passes, each
    taking members longest phrase first; a match overlapping an already-claimed span is ignored.
    Pass 1, the referring phrase: the trigger is inserted unless the occurrence already carries
    it. Pass 2 (match_names), the character's name with an initial capital and no article right
    before it: the trigger and a space go in front of it unless already there. Pass 3
    (match_names), the trigger itself: counted, nothing inserted. skip_quoted: a match lying
    wholly inside a "..." span (a spoken line) is neither triggered nor reported. insert: if
    given, a set of names; every member still claims its spans, but only these members get a
    trigger and are reported."""
    quoted = [m.span() for m in re.finditer(r'"[^"]*"', text)] if skip_quoted else []
    order = sorted(members, key=lambda m: (-len(m.phrase), m.phrase.lower(), m.name))
    found = []

    def claim(start, end, member, kind):
        if any(s <= start and end <= e for s, e in quoted):
            return
        if any(start < e and s < end for s, e, _, _ in found):
            return
        found.append((start, end, member, kind))

    for member in order:
        for match in _phrase_regex(member.phrase, member.trigger).finditer(text):
            claim(match.start(), match.end(), member,
                  "carried" if match.group("trig") is not None else "phrase")
    if match_names:
        for member in order:
            for match in re.finditer(r"(?<![\w-])" + re.escape(member.name) + r"(?![\w-])", text,
                                     re.IGNORECASE):
                before = re.search(r"([A-Za-z']+)\s+$", text[:match.start()])
                if (text[match.start()].isupper()
                        and not (before and before.group(1).lower() in ARTICLES)):
                    claim(match.start(), match.end(), member, "name")
        for member in order:
            for match in re.finditer(r"(?<![\w-])" + re.escape(member.trigger) + r"(?![\w-])",
                                     text, re.IGNORECASE):
                claim(match.start(), match.end(), member, "trigger")
    out = text
    for start, _end, member, kind in sorted(found, key=lambda f: f[0], reverse=True):
        if kind in ("carried", "trigger") or (insert is not None and member.name not in insert):
            continue
        if kind == "name":
            if not text[:start].lower().endswith(member.trigger.lower() + " "):
                out = out[:start] + member.trigger + " " + out[start:]
            continue
        words = member.phrase.split()
        if len(words) > 1 and words[0].lower() in ARTICLES:
            cut = start + len(words[0])
            out = out[:cut] + " " + member.trigger + out[cut:]
        else:
            out = out[:start] + member.trigger + " " + out[start:]
    return out, sorted({member.name for _, _, member, _ in found
                        if insert is None or member.name in insert})


def member_referenced(text, member):
    """True when text names a cast member by its referring phrase, its name (initial capital, no
    article right before it) or its trigger, outside "..." spans (dialogue spec 11.3)."""
    return bool(cast_text(text, [member], skip_quoted=True, match_names=True)[1])
```

**3.2.** Edit `character_lib.py`: replace `panel_strengths`, adding the two functions after it, this text, which occurs exactly once:

```python
def panel_strengths(names, members, character_strength, shots=False):
    """{name: strength} for one panel: 1.0 when exactly one cast character is named (continuous
    mode only); else -- and always in shots mode -- each character's own character.json strength
    if set, otherwise character_strength (casting spec 6; shots spec 6)."""
    by_name = {m.name: m for m in members}
    if len(names) == 1 and not shots:
        return {names[0]: SINGLE_CHARACTER_STRENGTH}
    return {n: (by_name[n].strength if by_name[n].strength is not None else character_strength)
            for n in names}
```

with:

```python
def panel_strengths(names, members, character_strength, shots=False):
    """{name: strength} for one panel: 1.0 when exactly one cast character is named (continuous
    mode only); else -- and always in shots mode -- each character's own character.json strength
    if set, otherwise character_strength (casting spec 6; shots spec 6)."""
    by_name = {m.name: m for m in members}
    if len(names) == 1 and not shots:
        return {names[0]: SINGLE_CHARACTER_STRENGTH}
    return {n: (by_name[n].strength if by_name[n].strength is not None else character_strength)
            for n in names}


def story_strength(member, character_strength):
    """A cast character's LoRA strength in every panel of a chained story (dialogue spec 11.5):
    its character.json strength when set, else character_strength."""
    return member.strength if member.strength is not None else character_strength


def prefix_character_triggers(prompt, triggers):
    """prompt with the missing character triggers in front as "t1, t2. " (dialogue spec 11.4):
    the triggers, in order, de-duplicated case-insensitively, that do not already occur as whole
    words. The rule of lora_catalog.prefix_triggers, duplicated so the chained cast pass does not
    load lora_catalog.py."""
    missing, seen = [], set()
    for trigger in triggers:
        if trigger.lower() in seen:
            continue
        seen.add(trigger.lower())
        if not re.search(r"(?<![\w-])" + re.escape(trigger) + r"(?![\w-])", prompt, re.IGNORECASE):
            missing.append(trigger)
    if not missing:
        return prompt
    return ", ".join(missing) + ". " + prompt
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_character_lib.py tests/test_shots_mode.py tests/test_casting_pipeline.py 2>&1 | tail -1
```

Expected: `passed`, no failure (`test_c36`, `test_c37`, `test_s2` and the `cast_text` tests of `tests/test_character_lib.py` pass unchanged). Compile check with `FILES` = `character_lib.py tests/test_dialogue.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add character_lib.py tests/test_dialogue.py
git diff --cached --name-only
git commit -m "feat(casting): cast_text matches names and triggers; member_referenced, story_strength, prefix_character_triggers (11.3-11.5, CA2, CA7, CA9)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 21: bin/ltx-story-manifest chained casting: plan attachment, the trigger prefix, one strength

Implements spec 11.2, 11.4 (the manifest's pass order and note), 11.5 (the `--chain` strength), 11.7 (the manifest and `bin/ltx-movie` rows) and 11.9. Tests CA1, CA3, CA4, CA5, CA8.

**Files:**
- Modify: `bin/ltx-story-manifest`
- Modify: `bin/ltx-movie` (docstring and `--character-strength` help only)
- Modify: `tests/test_dialogue.py`
- Modify: `tests/test_casting_pipeline.py` (`test_p20_cast_inserts_triggers_and_lists_characters`, `test_p21_character_strength_and_override`: the 11.8 strength edits)
- Modify: `tests/test_shots_mode.py` (`test_s62_shots_strength_overrides`, its chained case: the 11.8 strength edit)

**Interfaces:**
- Consumes: Task 20's `cast_text(..., skip_quoted=True, match_names=...)`, `story_strength`, `prefix_character_triggers`; `panel_strengths` (unchanged, still used by `--shots`).
- Produces (in `bin/ltx-story-manifest`): `_casting_plan(args, n_panels) -> [[plan cast entry]] per panel`; `_plan_cast_names(entries, members) -> set(names)`; in a `--chain` manifest every panel's `characters` is the union of the text pass and the plan pass, sorted by name, each at `story_strength`; a plan-attached character the Motion does not name has its trigger prefixed and the line `cast: panel %d: <names> attached from plan.json (Motion: does not name them); trigger prefixed`; a `--shots` manifest is unchanged except `skip_quoted`. In `tests/test_dialogue.py`: `CA_STORY`, `KYRA_ENTRY`, `RONIN_ENTRY`, `_ca_plan(*beat_casts)`, `_ca_manifest(tmp_path, monkeypatch, story_id, m1, m2, plan=None, cast=("kyra",), extra=()) -> (rc, panels)`, `_short(panel)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_ca1_plan_attaches_a_pronoun_only_panel`, `test_ca3_without_a_usable_plan_characters_attach_from_the_text`, `test_ca4_text_and_plan_names_are_united`, `test_ca5_one_strength_per_character_for_the_story`, `test_ca8_catalog_triggers_go_in_front_of_the_character_prefix`, `test_casting_help_and_docstring_text`.

**1.1.** Append to `tests/test_dialogue.py`:

```python
# --- CA1, CA3-CA5, CA8: chained casting attachment (11.2-11.5, 11.9) -------------------------

CA_STORY = """# Cast test

Kyra at the harbour.

## Panel 1 — One
Image: The woman in grey stands at the harbour wall.
Motion: @@M1@@
Narration: The tide was turning.

## Panel 2 — Two
Motion: @@M2@@
Narration: Nobody came.
"""
KYRA_ENTRY = {"id": "c1", "phrase": "the woman in grey", "descriptor": seu.DESC_K,
              "cast_name": "kyra"}
RONIN_ENTRY = {"id": "c2", "phrase": "the ronin", "descriptor": seu.DESC_R, "cast_name": "ronin"}
PRONOUN = "She turns her head toward the harbour."
WATCHES = "The woman in grey watches the boats."


def _ca_plan(*beat_casts):
    return {"schema": "ltx-movie.plan.v1", "cast": [KYRA_ENTRY, RONIN_ENTRY],
            "beats": [{"cast": list(c)} for c in beat_casts]}


def _ca_manifest(tmp_path, monkeypatch, story_id, m1, m2, plan=None, cast=("kyra",), extra=()):
    text = CA_STORY.replace("@@M1@@", m1).replace("@@M2@@", m2)
    story_md, images, mws = _manifest_ws(tmp_path, monkeypatch, story_id, text, plan=plan)
    flags = []
    for name in cast:
        flags += ["--cast", {"kyra": "the woman in grey=kyra", "ronin": "the ronin=ronin"}[name]]
    rc = story_manifest.main(_manifest_argv(story_id, story_md, images, extra=flags + list(extra)))
    return rc, (_read_manifest(mws, story_id)["panels"] if rc == 0 else None)


def _short(panel):
    return [(c["name"], c["strength"]) for c in panel["characters"]]


def test_ca1_plan_attaches_a_pronoun_only_panel(tmp_path, monkeypatch, capsys, story_env):
    _members(story_env, "kyra")
    rc, panels = _ca_manifest(tmp_path, monkeypatch, "ca1", WATCHES, PRONOUN,
                              plan=_ca_plan(["c1"], ["c1"]))
    assert rc == 0
    assert _short(panels[1]) == [("kyra", 0.8)]
    assert panels[1]["motion_prompt"] == "kyrawmn. " + PRONOUN
    assert panels[0]["motion_prompt"] == "The kyrawmn woman in grey watches the boats."
    assert ("cast: panel 2: kyra attached from plan.json (Motion: does not name them); trigger "
            "prefixed\n") in capsys.readouterr().out


def test_ca3_without_a_usable_plan_characters_attach_from_the_text(tmp_path, monkeypatch, capsys,
                                                                    story_env):
    _members(story_env, "kyra")
    rc, panels = _ca_manifest(tmp_path, monkeypatch, "ca3", WATCHES, PRONOUN)
    assert rc == 0 and panels[1]["characters"] == [] and panels[1]["motion_prompt"] == PRONOUN
    assert "plan.json" not in capsys.readouterr().out
    note = ("note: plan.json is not usable for casting (%s); characters attach from the Motion: "
            "text only\n")
    for i, (plan, reason) in enumerate((
            ("{not json", "it is unreadable or not a JSON object"),
            ("[]", "it is unreadable or not a JSON object"),
            ({"schema": "other"}, "its schema is not ltx-movie.plan.v1"),
            ({"schema": "ltx-movie.plan.v1", "cast": "c1", "beats": []},
             "its cast is not a list of objects"),
            (_ca_plan(["c1"]), "it has 1 beats for 2 panels"),
            ({"schema": "ltx-movie.plan.v1", "cast": [KYRA_ENTRY],
              "beats": [{"cast": ["c1"]}, {"cast": "c1"}]}, "beat 2 has no cast list"))):
        rc, panels = _ca_manifest(tmp_path, monkeypatch, "ca3-%d" % i, WATCHES, PRONOUN, plan=plan)
        assert rc == 0 and panels[1]["characters"] == [], reason
        assert panels[1]["motion_prompt"] == PRONOUN, reason
        assert (note % reason) in capsys.readouterr().out, reason


def test_ca4_text_and_plan_names_are_united(tmp_path, monkeypatch, story_env):
    _members(story_env, "kyra", "ronin")
    rc, panels = _ca_manifest(tmp_path, monkeypatch, "ca4", WATCHES, "The ronin bows low.",
                              plan=_ca_plan(["c1"], ["c1"]), cast=("kyra", "ronin"))
    assert rc == 0 and [c["name"] for c in panels[1]["characters"]] == ["kyra", "ronin"]
    assert panels[1]["motion_prompt"] == "kyrawmn. The roninmn ronin bows low."
    rc, panels = _ca_manifest(tmp_path, monkeypatch, "ca4b", WATCHES, "The woman in grey bows low.",
                              plan=_ca_plan([], []))
    assert rc == 0 and [c["name"] for c in panels[1]["characters"]] == ["kyra"]


def test_ca5_one_strength_per_character_for_the_story(tmp_path, monkeypatch, story_env):
    seu.kyra(story_env["lib"])
    seu.ronin(story_env["lib"], strength=0.5)
    both = ("kyra", "ronin")
    bows = "The ronin bows to the woman in grey."
    rc, panels = _ca_manifest(tmp_path, monkeypatch, "ca5", "The woman in grey waits.", bows,
                              cast=both)
    assert rc == 0
    assert [_short(p) for p in panels] == [[("kyra", 0.8)], [("kyra", 0.8), ("ronin", 0.5)]]
    rc, panels = _ca_manifest(tmp_path, monkeypatch, "ca5b", "The woman in grey waits.", bows,
                              cast=both, extra=["--character-strength", "1.0"])
    assert [_short(p) for p in panels] == [[("kyra", 1.0)], [("kyra", 1.0), ("ronin", 0.5)]]
    shots = ("# Shots cast\n\n## Panel 1 — One\nImage: The woman in grey stands alone.\nMotion: The "
             "woman in grey waits.\nNarration: It rained.\n\n## Panel 2 — Two\nImage: " + bows
             + "\nMotion: " + bows + "\nNarration: It poured.\n")
    story_md, images, mws = _manifest_ws(tmp_path, monkeypatch, "ca5s", shots, images=2)
    assert story_manifest.main(_manifest_argv("ca5s", story_md, images, mode="shots", extra=[
        "--cast", "the woman in grey=kyra", "--cast", "the ronin=ronin"])) == 0
    members = character_lib.resolve_cast([(None, "kyra"), (None, "ronin")])
    panels = _read_manifest(mws, "ca5s")["panels"]
    for p, names in zip(panels, (["kyra"], ["kyra", "ronin"])):
        expected = character_lib.panel_strengths(names, members, 0.8, shots=True)
        assert _short(p) == [(n, expected[n]) for n in names]


def test_ca8_catalog_triggers_go_in_front_of_the_character_prefix(tmp_path, monkeypatch,
                                                                  story_env):
    _members(story_env, "kyra")
    lora = tmp_path / "cat.safetensors"
    lora.write_bytes(b"x" * 16)
    entry = {"id": "cat-motion", "kind": "motion", "path": str(lora), "sha256": "0" * 64,
             "strength": 0.7, "triggers": ["cattrig"]}
    catalog = tmp_path / "catalog_loras.json"
    catalog.write_text(json.dumps({"schema": "ltx-movie.catalog-loras.v1", "story_id": "ca8",
                                   "panels": [[], [entry]]}), encoding="utf-8")
    rc, panels = _ca_manifest(tmp_path, monkeypatch, "ca8", WATCHES, PRONOUN,
                              plan=_ca_plan(["c1"], ["c1"]),
                              extra=["--catalog-loras", str(catalog)])
    assert rc == 0 and panels[1]["motion_prompt"] == "cattrig. kyrawmn. " + PRONOUN


def test_casting_help_and_docstring_text():
    actions = story_manifest.build_parser()._option_string_actions
    assert actions["--character-strength"].help == (
        "LoRA strength for each cast character without its own character.json strength (default "
        "0.8, provisional), the same in every panel")
    assert actions["--cast"].help.endswith(
        "; under --chain a panel also gets every character its plan.json beat lists")
    assert ltx_movie.build_parser()._option_string_actions["--character-strength"].help == (
        "LoRA strength for each cast character without its own character.json strength (default "
        "0.8, provisional): the same in every clip of the story, alone or with others; a panel "
        "still of exactly one character uses 1.0")
    doc = " ".join(story_manifest.__doc__.split())
    assert ("under --chain, strength is the character's own character.json strength or "
            "--character-strength (default 0.8) in every panel") in doc
    assert "strength is 1.0 when the panel names exactly one cast character" not in doc
    assert ("in the chained flow each character keeps one strength in every clip"
            in " ".join(ltx_movie.__doc__.split()))
```

**1.2.** Edit `tests/test_casting_pipeline.py`: replace (in `test_p20_cast_inserts_triggers_and_lists_characters`) this text, which occurs exactly once:

```python
        [("kyra", 1.0)], [("kyra", 0.8), ("ronin", 0.8)], []]
```

with:

```python
        [("kyra", 0.8)], [("kyra", 0.8), ("ronin", 0.8)], []]
```

**1.3.** Edit `tests/test_casting_pipeline.py`: replace (in `test_p20`) this text, which occurs exactly once:

```python
                    "video_lora": os.path.join(lib_dir, "kyra", "lora", "video.safetensors"),
                    "strength": 1.0}
```

with:

```python
                    "video_lora": os.path.join(lib_dir, "kyra", "lora", "video.safetensors"),
                    "strength": 0.8}
```

**1.4.** Edit `tests/test_casting_pipeline.py`: replace (in `test_p20`) this text, which occurs exactly once:

```python
    assert "cast: panel 1: kyra@1.0" in out.splitlines()
```

with:

```python
    assert "cast: panel 1: kyra@0.8" in out.splitlines()
```

**1.5.** Edit `tests/test_casting_pipeline.py`: replace (in `test_p21_character_strength_and_override`) this text, which occurs exactly once:

```python
    assert _short(panels[0]["characters"]) == [("kyra", 1.0)]
```

with:

```python
    assert _short(panels[0]["characters"]) == [("kyra", 0.6)]
```

**1.6.** Edit `tests/test_shots_mode.py`: replace (in `test_s62_shots_strength_overrides`) this text, which occurs exactly once:

```python
    assert _names_strengths(_shots_manifest(ws, "chain")["panels"][0]) == [("kyra", 1.0)]
```

with:

```python
    assert _names_strengths(_shots_manifest(ws, "chain")["panels"][0]) == [("kyra", 0.8)]
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k "ca1 or ca3 or ca4 or ca5 or ca8 or casting_help" 2>&1 | tail -3
python3 -m pytest -q -p no:cacheprovider tests/test_casting_pipeline.py tests/test_shots_mode.py -k "p20 or p21 or s62" 2>&1 | tail -3
```

Expected: `6 failed`, then `3 failed` (single characters still get 1.0; no plan attachment; the old help text).

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/ltx-story-manifest`: replace `_known_phrases`, adding `_casting_plan` and `_plan_cast_names` after it, this text, which occurs exactly once:

```python
def _known_phrases(args, members):
    """The referring phrases a Narration: speaker prefix may name: the --cast phrases, a shots
    story's "## Characters" phrases and the story's plan.json cast phrases."""
    lib = _character_lib()
    phrases = [m.phrase for m in members]
    try:
        with open(args.prompts_md, encoding="utf-8") as handle:
            phrases += [p for p, _ in lib.parse_character_roster(handle.read())[0]]
    except (OSError, TypeError):
        pass
    plan_path = os.path.join(WS, "generated", "stories", args.story_id, "plan.json")
    try:
        with open(plan_path, encoding="utf-8") as handle:
            cast = json.load(handle).get("cast") or []
        phrases += [c["phrase"] for c in cast if isinstance(c, dict) and isinstance(c.get("phrase"), str)]
    except (OSError, ValueError, AttributeError):
        pass
    return phrases
```

with:

```python
def _known_phrases(args, members):
    """The referring phrases a Narration: speaker prefix may name: the --cast phrases, a shots
    story's "## Characters" phrases and the story's plan.json cast phrases."""
    lib = _character_lib()
    phrases = [m.phrase for m in members]
    try:
        with open(args.prompts_md, encoding="utf-8") as handle:
            phrases += [p for p, _ in lib.parse_character_roster(handle.read())[0]]
    except (OSError, TypeError):
        pass
    plan_path = os.path.join(WS, "generated", "stories", args.story_id, "plan.json")
    try:
        with open(plan_path, encoding="utf-8") as handle:
            cast = json.load(handle).get("cast") or []
        phrases += [c["phrase"] for c in cast if isinstance(c, dict) and isinstance(c.get("phrase"), str)]
    except (OSError, ValueError, AttributeError):
        pass
    return phrases


def _casting_plan(args, n_panels):
    """[[plan cast entry, ...] for each panel] from the story's plan.json beats, for --chain casting
    (dialogue spec 11.2): empty lists when there is no plan.json, and also -- after one note line
    -- when it is not usable (not a JSON object; another schema; a cast that is not a list of
    objects; a beat count other than n_panels; a beat without a list of cast ids). An id the plan
    cast does not define is skipped."""
    path = os.path.join(WS, "generated", "stories", args.story_id, "plan.json")
    empty = [[] for _ in range(n_panels)]
    if not os.path.exists(path):
        return empty
    try:
        with open(path, encoding="utf-8") as handle:
            plan = json.load(handle)
    except (OSError, ValueError):
        plan = None
    reason = None
    if not isinstance(plan, dict):
        reason = "it is unreadable or not a JSON object"
    elif plan.get("schema") != "ltx-movie.plan.v1":
        reason = "its schema is not ltx-movie.plan.v1"
    elif (not isinstance(plan.get("cast"), list)
          or not all(isinstance(e, dict) for e in plan["cast"])):
        reason = "its cast is not a list of objects"
    else:
        beats = plan.get("beats") if isinstance(plan.get("beats"), list) else []
        if len(beats) != n_panels:
            reason = "it has %d beats for %d panels" % (len(beats), n_panels)
        else:
            for k, beat in enumerate(beats, start=1):
                if (not isinstance(beat, dict) or not isinstance(beat.get("cast"), list)
                        or not all(isinstance(c, str) for c in beat["cast"])):
                    reason = "beat %d has no cast list" % k
                    break
    if reason:
        print("note: plan.json is not usable for casting (%s); characters attach from the Motion: "
              "text only" % reason)
        return empty
    by_id = {}
    for entry in plan["cast"]:
        if isinstance(entry.get("id"), str):
            by_id.setdefault(entry["id"], entry)
    return [[by_id[c] for c in beat["cast"] if c in by_id] for beat in plan["beats"]]


def _plan_cast_names(entries, members):
    """The names of the cast members that plan cast entries attach (dialogue spec 11.2): the
    member an entry's cast_name names; for an entry whose cast_name is null, the member whose
    referring phrase equals its phrase (case-insensitively)."""
    names = set()
    for entry in entries:
        for m in members:
            if entry.get("cast_name") is not None:
                if entry.get("cast_name") == m.name:
                    names.add(m.name)
            elif str(entry.get("phrase", "")).lower() == m.phrase.lower():
                names.add(m.name)
    return names
```

**3.2.** Edit `bin/ltx-story-manifest`: replace (the start of the cast pass) this text, which occurs exactly once:

```python
    if members:
        by_name = {m.name: m for m in members}
        used = set()
        for p in panels:
            p["motion_prompt"], names = lib.cast_text(p["motion_prompt"], members, skip_quoted=True)
            if args.shots:
                names = sorted(set(names) | set(lib.cast_text(p["panel_text"], members)[1]))
            strengths = lib.panel_strengths(names, members, strength, shots=args.shots)
```

with:

```python
    if members:
        by_name = {m.name: m for m in members}
        plan_casts = _casting_plan(args, n_panels) if args.chain else None
        used = set()
        for i, p in enumerate(panels):
            p["motion_prompt"], names = lib.cast_text(p["motion_prompt"], members, skip_quoted=True,
                                                      match_names=args.chain)
            if args.shots:
                names = sorted(set(names) | set(lib.cast_text(p["panel_text"], members)[1]))
                strengths = lib.panel_strengths(names, members, strength, shots=True)
            else:
                from_plan = _plan_cast_names(plan_casts[i], members)
                prefixed = sorted(from_plan - set(names))
                if prefixed:
                    p["motion_prompt"] = lib.prefix_character_triggers(
                        p["motion_prompt"], [by_name[n].trigger for n in prefixed])
                    print("cast: panel %d: %s attached from plan.json (Motion: does not name "
                          "them); trigger prefixed" % (p["index"], ", ".join(prefixed)))
                names = sorted(set(names) | from_plan)
                strengths = dict((n, lib.story_strength(by_name[n], strength)) for n in names)
```

**3.3.** Edit `bin/ltx-story-manifest`: replace (the module docstring) this text, which occurs exactly once:

```python
name: strength is 1.0 when the panel names exactly one cast character, else the
character's own character.json strength or --character-strength (default 0.8).
```

with:

```python
name: under --chain, strength is the character's own character.json strength or
--character-strength (default 0.8) in every panel, and a panel also carries every
character plan.json puts in its beat (their trigger is prefixed when Motion: does not
name them); under --shots it is the character's own strength or --character-strength.
```

**3.4.** Edit `bin/ltx-story-manifest`: replace (the `--character-strength` help) this text, which occurs exactly once:

```python
                         help="LoRA strength for each cast character in a panel that names two "
                              "or more of them (default 0.8, provisional); one character uses "
                              "1.0, except with --shots, where every cast character uses this "
                              "strength")
```

with:

```python
                         help="LoRA strength for each cast character without its own "
                              "character.json strength (default 0.8, provisional), the same in "
                              "every panel")
```

**3.5.** Edit `bin/ltx-story-manifest`: replace (the end of the `--cast` help) this text, which occurs exactly once:

```python
                              "'characters' list carries its video LoRA and strength")
```

with:

```python
                              "'characters' list carries its video LoRA and strength; under "
                              "--chain a panel also gets every character its plan.json beat "
                              "lists")
```

**3.6.** Edit `bin/ltx-movie`: replace (the module docstring) this text, which occurs exactly once:

```python
with that character's LoRAs (1.0 for one character, --character-strength, default 0.8, for
two or more). Every casting problem exits 2 before any phase runs. character_lib.py is
```

with:

```python
with that character's LoRAs (in the chained flow each character keeps one strength in every
clip: its character.json strength, else --character-strength, default 0.8; a panel whose
Motion: only refers to a character by pronoun still gets its LoRA from plan.json). Every
casting problem exits 2 before any phase runs. character_lib.py is
```

**3.7.** Edit `bin/ltx-movie`: replace (the `--character-strength` help) this text, which occurs exactly once:

```python
                         help="LoRA strength for each cast character in a panel that names two "
                              "or more of them (default 0.8, provisional); a panel that names "
                              "one cast character uses 1.0, except with --shots, where every "
                              "cast character uses this strength")
```

with:

```python
                         help="LoRA strength for each cast character without its own "
                              "character.json strength (default 0.8, provisional): the same in "
                              "every clip of the story, alone or with others; a panel still of "
                              "exactly one character uses 1.0")
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_casting_pipeline.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_lora_catalog.py tests/test_ltx_story_images.py 2>&1 | tail -1
python3 tests/test_ltx_story_manifest_chain.py 2>&1 | tail -1
python3 tests/test_ltx_movie_offline.py 2>&1 | tail -1
```

Expected: `passed`, no failure (`test_p6`, `test_p9`, `test_p22`, `test_c36`, `test_c37`, `test_s2` and the B1-B3 regressions pass unchanged); both scripts print `OK n/n` with the baseline counts. Compile check with `FILES` = `bin/ltx-story-manifest bin/ltx-movie tests/test_dialogue.py tests/test_casting_pipeline.py tests/test_shots_mode.py`; expected `compiled 5` twice.

- [ ] **Step 5: Commit.**

```bash
git add bin/ltx-story-manifest bin/ltx-movie tests/test_dialogue.py tests/test_casting_pipeline.py tests/test_shots_mode.py
git diff --cached --name-only
git commit -m "feat(casting): chained panels attach plan.json characters with a trigger prefix, one strength per character (11.2-11.5, 11.9, CA1, CA3-CA5, CA8)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 22: N19, the chained cast-reference advisory

Implements spec 11.6 and the `story_engine.py` row of 11.7. Tests CA6.

**Files:**
- Modify: `story_engine.py`
- Modify: `tests/test_dialogue.py`

**Interfaces:**
- Consumes: Task 20's `member_referenced`; Task 2's `_PRONOUN_RE`.
- Produces: the advisory `panel %d: N19 cast reference: Motion: refers to '<phrase>' only by pronoun; ...` / `... never names '<phrase>'; ...` for each library character in a chained beat's plan cast whose assembled Motion: does not reference them; `"N19"` ends `GENERATION_CHECKS` and `RECHECK_IDS` (not `PLAN_FREE_IDS`, never hard, never in `REPAIR_IDS`).

- [ ] **Step 1: Write the failing test.**

New test in this task: `test_ca6_n19_cast_reference`.

**1.1.** Append to `tests/test_dialogue.py`:

```python
# --- CA6: N19 (11.6) ---------------------------------------------------------------------------

def test_ca6_n19_cast_reference(ws, story_env):
    members = _members(story_env, "kyra")

    def kyra_cast(raw):
        raw["cast"] = [{"id": "c1", "phrase": "the woman in grey", "descriptor": seu.DESC_K}]

    tail = "; the pipeline attaches kyra's LoRA from the plan and prefixes the trigger"
    for mode, key, text, expected in (
            ("chained", "motion", PRONOUN,
             ["panel 2: N19 cast reference: Motion: refers to 'the woman in grey' only by "
              "pronoun" + tail]),
            ("chained", "motion", "Rain falls on the quay.",
             ["panel 2: N19 cast reference: Motion: never names 'the woman in grey'" + tail]),
            ("chained", "motion", "The woman in grey turns her head.", []),
            ("chained", "motion", "Kyra turns her head toward the harbour.", []),
            ("chained", "motion", "kyrawmn turns her head toward the harbour.", []),
            ("shots", "motion", PRONOUN, []),
            ("no_stills", "prompt", PRONOUN + " " + seu.panel_json("no_stills", 2)["prompt"], [])):
        hard, advisory = _checks(ws, mode, plan_mut=kyra_cast, replies={2: {key: text}},
                                 ctx_kw={"members": members})
        assert _only(hard, "N19") == [] and _only(advisory, "N19") == expected, (mode, text)
    assert se.GENERATION_CHECKS[-1] == "N19" and se.RECHECK_IDS[-1] == "N19"
    assert "N19" not in se.PLAN_FREE_IDS and "N19" not in se.REPAIR_IDS
```

- [ ] **Step 2: Run the test and confirm it fails.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k ca6 2>&1 | tail -3
```

Expected: `1 failed` (no N19 message).

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace (in `_field_checks`) this text, which occurs exactly once:

```python
    if "N12" in ids and ctx.mode == "chained":
        writer = writers.get("Motion", "")
```

with:

```python
    if "N19" in ids and ctx.mode == "chained" and plan and beat is not None:
        motion = dict(fields).get("Motion", "")
        cast_members = dict((m.name, m) for m in ctx.members)
        for cid in beat["cast"]:
            entry = by_cast.get(cid)
            member = cast_members.get(entry.get("cast_name")) if entry else None
            if member is None or lib.member_referenced(motion, member):
                continue
            how = ("refers to %s only by pronoun" if lib._PRONOUN_RE.search(writers.get("Motion", ""))
                   else "never names %s")
            add(advisory, "N19", "cast reference", "Motion",
                (how % _q(member.phrase)) + "; the pipeline attaches %s's LoRA from the plan "
                "and prefixes the trigger" % member.name)
    if "N12" in ids and ctx.mode == "chained":
        writer = writers.get("Motion", "")
```

**3.2.** Edit `story_engine.py`: replace (the end of `GENERATION_CHECKS`) this text, which occurs exactly once:

```python
                     "N14", "N15", "N16", "N17", "N18", "T1", "T2", "T3")
```

with:

```python
                     "N14", "N15", "N16", "N17", "N18", "T1", "T2", "T3", "N19")
```

**3.3.** Edit `story_engine.py`: replace (the end of `RECHECK_IDS`) this text, which occurs exactly once:

```python
               "N16", "N17", "N18", "T1", "T2", "T3")
```

with:

```python
               "N16", "N17", "N18", "T1", "T2", "T3", "N19")
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py tests/test_story_engine.py tests/test_lora_catalog.py 2>&1 | tail -1
```

Expected: no failure other than the known `test_rst62_import_sets` (no fixture story casts a library character, so N19 adds nothing to any existing expectation). Compile check with `FILES` = `story_engine.py tests/test_dialogue.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_dialogue.py
git diff --cached --name-only
git commit -m "feat(casting): N19 advisory for a chained cast character the Motion does not name (11.6, CA6)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 23: The offline merge gate (DLG-H), the calibration replay (DLG-K1) and the DK2/DK3 guards

Implements DK2, DK3, DK4 (the gate: DLG21-DLG24 plus DLG-H), DK5 (its run), DK6 (the DLG-K1 fixture) and spec 10.1's replay procedure. Tests DLG-H, DLG-K1, `test_dk2_both_interpreters_compile_every_changed_file`, `test_dk3_import_sets_are_unchanged`.

**Files:**
- Modify: `tests/test_dialogue.py`

**Interfaces:**
- Consumes: Task 12's `_Run.critic_loop`, `final_outcome`; Task 10's `_sentences`; the `tests/test_dialogue.py` helpers `_run`, `_replies`, `_read_json`.
- Produces: the merge-gate command of Step 4; `tests/fixtures/dialogue_kpi/` is read when present (the corpus is recorded after the merge by the main thread or the user, spec 10.1; this task creates no fixture).

- [ ] **Step 1: Write the tests.**

New tests in this task: `test_dlg_h_offline_merge_gate` (6 parametrized cases), `test_dlg_k1_calibration_replay`, `test_dk2_both_interpreters_compile_every_changed_file`, `test_dk3_import_sets_are_unchanged`.

**1.1.** Append to `tests/test_dialogue.py`:

```python
# --- DLG-H, DLG-K1, DK2, DK3: the merge gate and the guards (DK2-DK6, 10.1) -------------------

DLG_H_TEXT = {
    "chained": ("motion", "The courier leans into the bend while rain streams off the yellow hood. "
                          "Water sprays from the front wheel across the cobblestones. The camera "
                          "slowly pans left."),
    "shots": ("motion", "The courier leans into the bend as rain streams off the yellow hood. The "
                        "camera slowly pans left."),
    "no_stills": ("prompt", seu.panel_json("no_stills", 2)["prompt"]
                  + " The camera slowly pans left as the yellow hood flaps in the wind."),
}


@pytest.mark.parametrize("speaking", [False, True], ids=["silent", "speaking"])
@pytest.mark.parametrize("mode", ["chained", "shots", "no_stills"])
def test_dlg_h_offline_merge_gate(mode, speaking, ws, tmp_path, monkeypatch):
    raw = seu.plan_json(mode, 3)
    if speaking:
        raw["beats"][1]["speaker"] = "c1"
    key, text = DLG_H_TEXT[mode]
    reply = {key: text}
    if speaking:
        reply["dialogue"] = LINE
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, mode=mode, plan=[seu.answer(raw)],
                            panel=_replies(mode, 3, {2: [reply]}))
    assert rc == 0
    rounds = os.path.join(ctx.story_dir, "story_rounds")
    assert _read_json(os.path.join(rounds, "round_0", "story_checks.json"))["hard"] == []
    assert _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["stop_reason"] == "passed"
    assert [r["stage"] for r in log].count("critic") == 0
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        story = f.read()
    for sentence in se._sentences(text):
        assert sentence in story, sentence
    if speaking:
        assert "Dialogue: the courier: " + LINE + "\n" in story


KPI_DIR = os.path.join(WS, "tests", "fixtures", "dialogue_kpi")


def test_dlg_k1_calibration_replay(tmp_path, monkeypatch, capsys):
    cases = (sorted(n for n in os.listdir(KPI_DIR) if os.path.isdir(os.path.join(KPI_DIR, n)))
             if os.path.isdir(KPI_DIR) else [])
    if not cases:
        pytest.skip("dialogue KPI corpus not recorded")

    def no_agent(*args, **kwargs):
        raise AssertionError("the DLG-K1 replay makes no panel or plan call")

    monkeypatch.setattr(se, "run_agent", no_agent)
    monkeypatch.setattr(se, "run_critic", lambda ctx, prompt: (
        "ok", json.dumps(seu.critic_json(verdict="revise")), "local"))
    passed = []
    for name in cases:
        case_dir = os.path.join(KPI_DIR, name)
        case = _read_json(os.path.join(case_dir, "case.json"))
        plan = _read_json(os.path.join(case_dir, "plan.json"))
        parts = [dict((key, value) for key, value in p.items() if key != "index")
                 for p in _read_json(os.path.join(case_dir, "parts.json"))["panels"]]
        ctx = seu.make_ctx(se, seu.make_ws(tmp_path / name), story_id="kpi-" + name,
                           mode=case["mode"], panels=case["panels"], seconds=case["seconds"],
                           clip_seconds=case["clip_seconds"], narration=case["narration"])
        runner = se._Run(ctx, "")
        runner.make_state(0, plan, parts)
        runner.critic_loop()
        if not se.final_outcome(runner.states)[1]:
            passed.append(name)
    with capsys.disabled():
        print("\nDLG-K1: %d of %d cases have 0 blocking violations" % (len(passed), len(cases)))
    if os.environ.get("DIALOGUE_KPI_ENFORCE") == "1":
        assert len(passed) >= 22, sorted(set(cases) - set(passed))


DK2_FILES = ("character_lib.py", "story_engine.py", "bin/ltx-story-manifest", "bin/ltx-movie",
             "bin/judge-story", "bin/judge-clips", "bin/judge-stills", "tests/test_dialogue.py",
             "tests/test_story_engine.py", "tests/test_casting_pipeline.py",
             "tests/test_shots_mode.py", "tests/test_judge_story.py", "tests/test_judge_clips.py",
             "tests/test_movie_ui_builder.py")
COMPILE_ONLY = ("import sys\n"
                "for path in sys.argv[1:]:\n"
                "    with open(path, encoding='utf-8') as f:\n"
                "        compile(f.read(), path, 'exec')\n"
                "print('compiled %d' % (len(sys.argv) - 1))\n")


def test_dk2_both_interpreters_compile_every_changed_file():
    paths = [os.path.join(WS, rel) for rel in DK2_FILES]
    for interpreter in ("/usr/bin/python3", sys.executable):
        proc = subprocess.run([interpreter, "-c", COMPILE_ONLY] + paths, capture_output=True,
                              text=True)
        assert (proc.returncode, proc.stdout) == (0, "compiled %d\n" % len(paths)), (
            interpreter, proc.stderr)


def _top_level_imports(rel):
    import ast
    with open(os.path.join(WS, rel), encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=rel)
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module)
    return names


def test_dk3_import_sets_are_unchanged():
    expected = {
        "character_lib.py": {"collections", "datetime", "json", "os", "re", "uuid"},
        "story_engine.py": {"collections", "copy", "datetime", "hashlib", "importlib.machinery",
                            "json", "os", "re", "shlex", "subprocess", "sys", "time", "uuid"},
        "bin/ltx-story-manifest": {"PIL", "argparse", "datetime", "glob", "importlib.machinery",
                                   "json", "os", "re", "sys"},
        "bin/ltx-movie": {"argparse", "glob", "importlib.machinery", "json", "os", "pipeline_log",
                          "shlex", "subprocess", "sys", "threading", "time"},
        "bin/judge-story": {"anthropic", "argparse", "datetime", "json", "jsonschema", "os", "sys"},
        "bin/judge-clips": {"anthropic", "argparse", "base64", "datetime", "fractions", "json",
                            "jsonschema", "os", "pipeline_log", "re", "shutil", "subprocess",
                            "sys", "tempfile"},
        "bin/judge-stills": {"anthropic", "argparse", "base64", "datetime", "json", "jsonschema",
                             "os", "pipeline_log", "re", "sys"},
    }
    for rel, names in expected.items():
        assert _top_level_imports(rel) == names, rel
```

- [ ] **Step 2: Run the new tests.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k "dlg_h or dlg_k1 or dk2 or dk3" -rs 2>&1 | tail -4
```

Expected: `8 passed, 1 skipped` and the skip reason `dialogue KPI corpus not recorded`. These tests pin behaviour Tasks 1-22 built, so they pass at once; a failure here is a stop-and-report (it means an earlier task's behaviour differs from the spec's D6 invariants).

- [ ] **Step 3: Run the DK4 merge gate and the DK5 legacy byte-identity tests.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k "dlg21 or dlg22 or dlg23 or dlg24 or dlg_h" 2>&1 | tail -1
python3 -m pytest -q -p no:cacheprovider tests/test_story_engine.py tests/test_shots_mode.py -k "rst40 or rst41 or s52" 2>&1 | tail -1
python3 -m pytest -q -p no:cacheprovider tests/test_casting_regression.py 2>&1 | tail -1
python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k dlg8 2>&1 | tail -1
python3 tests/test_ltx_story_manifest_chain.py 2>&1 | tail -1
```

Expected: `10 passed` (DLG21, DLG22, DLG23, DLG24 and the six DLG-H cases); then `3 passed`, `3 passed` and `1 passed`; `OK n/n` with the baseline count (`test_v2_golden_byte_identical` holds). Compile check with `FILES` = `tests/test_dialogue.py`; expected `compiled 1` twice.

- [ ] **Step 4: Commit.**

```bash
git add tests/test_dialogue.py
git diff --cached --name-only
git commit -m "test(dialogue): DLG-H offline merge gate, DLG-K1 calibration replay, DK2/DK3 guards (DK2-DK6)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 24: Design review, the test_mut26 re-baseline (test-only commit) and DK1

Implements G10, spec 12 steps 3-4 and DK1; hands DK6's recording and DK7 to the main thread. No production code changes in this task.

**Files:**
- Modify: `tests/test_movie_ui_builder.py` (`test_mut26_pipeline_files_are_unchanged`: spec 9.2 "set `BASELINE` to the feature commit's SHA and append ', then to <sha> (on-camera dialogue)' to the comment")

**Interfaces:**
- Consumes: every earlier task's commit.
- Produces: the final pass counts in `/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-24-dialogue/final-pytest.txt`.

- [ ] **Step 1: Design review (controller; spec 12 step 3).** Ask an Opus `design-reviewer` to review `git diff fed1107..HEAD -- qwen-agent-workspace` against the spec and this plan. Fix every finding in a new commit on the owning task's files before Step 2; re-run that task's Step 4.

- [ ] **Step 2: Re-baseline test_mut26 to the last pipeline commit.**

```bash
SHA=$(git log -1 --format=%H -- story_engine.py character_lib.py bin/ltx-movie bin/ltx-story-manifest bin/judge-story bin/judge-clips bin/judge-stills)
echo "$SHA"
python3 - "$SHA" <<'EOF'
import sys
sha = sys.argv[1]
path = "tests/test_movie_ui_builder.py"
with open(path, encoding="utf-8") as f:
    text = f.read()
old_comment = ("    # kept around the seed-aware field list). This invariant holds from the new "
               "baseline.\n")
new_comment = ("    # kept around the seed-aware field list), then to\n"
               "    # %s (on-camera dialogue). This invariant holds from the new baseline.\n" % sha)
old_base = '    BASELINE = "e2b4a27f71948d00ec57794a3c7f714380b9af66"\n'
assert text.count(old_comment) == 1 and text.count(old_base) == 1
text = text.replace(old_comment, new_comment).replace(old_base, '    BASELINE = "%s"\n' % sha)
with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("re-based to", sha)
EOF
python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py -k mut26 2>&1 | tail -1
```

Expected: the SHA is Task 22's commit (the last one that touched a pipeline file; Task 23 touched only `tests/test_dialogue.py`); `re-based to <that SHA>`; then `1 passed`.

- [ ] **Step 3: Commit (test-only; spec fix 9).**

```bash
git add tests/test_movie_ui_builder.py
git diff --cached --name-only    # expected: only qwen-agent-workspace/tests/test_movie_ui_builder.py
git commit -m "test: re-baseline test_mut26 to the on-camera dialogue pipeline commit" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4: DK1, the full suite against the baseline (about 10 minutes).**

```bash
D=/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-24-dialogue
python3 -m pytest tests/ -q -rA -p no:cacheprovider > $D/final-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt; tail -1 $D/final-pytest.txt
grep -E '^(FAILED|ERROR)' $D/final-pytest.txt
python3 tests/test_ltx_movie_offline.py 2>&1 | tail -1
diff <(grep -E '^PASSED' $D/baseline-pytest.txt | sort) <(grep -E '^PASSED' $D/final-pytest.txt | sort) | grep '^<' || echo "no lost pass"
```

Expected: the `FAILED` lines are exactly `test_character_dataset.py::test_d2_copied_literals_match_the_spike`, `test_story_engine.py::test_rst62_import_sets` and `test_story_server.py::test_s14_source_guards` (`test_judge_clips.py::test_goal_default_prompt_byte_identical` passes since Task 17); the passed count is the baseline's plus every new test (57 `tests/test_dialogue.py` functions, 62 collected with the six DLG-H cases, of which DLG-K1 is skipped) plus the judge-clips goal test; the offline script prints `OK n/n` with the baseline `n`; the last command prints `no lost pass` (a test renamed by this plan does not exist: none is renamed). Any other difference: stop and report.

- [ ] **Step 5: Hand-off of DK6 and DK7 (main thread or user; not an executor step).** After the merge, record the 24-case corpus (spec 10.1) under `tests/fixtures/dialogue_kpi/<case>/` with `case.json`, `plan.json` and `parts.json` copied from each run's `story_rounds/round_0/`, run `DIALOGUE_KPI_ENFORCE=1 python3 -m pytest -q -p no:cacheprovider tests/test_dialogue.py -k dlg_k1 -s` (DK6: at least 22 of 24, reported, not blocking), then run the 16 live runs of spec 10.2 (DK7: at least 14 of 16 exit 0 with no hand edit) and the delivery A/B of 10.3. A DK7 miss applies the spec's rollback rule (reopen `ACTION_SECONDS`, `NO_STILLS_BEAT_SECONDS`, the cap formula and the T2/T3 thresholds for a user decision); the feature is not "done" until DK7 passes.

---

## Coverage

### Spec section to task

| Spec | Task(s) |
|---|---|
| 0.3 G1 (`character_lib.py`) | 1, 2, 3, 4 (`_STORY_FIELD_RE`), 6 (S3), 20 |
| 0.3 G2 (`bin/ltx-story-manifest`) | 4, 5, 21 |
| 0.3 G3 (`story_engine.py`) | 7-15, 22 |
| 0.3 G4 (`bin/ltx-movie`) | 6, 7, 18, 19, 21 (docstring/help) |
| 0.3 G5, G6, G7 | 16, 17, 4 |
| 0.3 G8 (`tests/test_dialogue.py`) | 1-23 |
| 0.3 G9 (existing tests, 9.2 and 11.8) | 7-17, 19, 21 |
| 0.3 G10 (`test_mut26`) | 24 |
| 0.3 G11 (Section 11) | 20, 21, 22 |
| 2.1 field order | 4, 10 |
| 2.2 plan `speaker`, `speech_notes` | 7 |
| 2.3 writer parts | 9 |
| 2.4 `clip_seconds`, `engine_seconds` | 7 |
| 2.5 manifest keys | 5 |
| 2.6 `story_checks.json` | 12 (run), 14 (re-check) |
| DG1-DG5 | 1 |
| DG6 | 3 (character_lib), 5 (manifest `skip_quoted=True`) |
| DG7 | 4 (step 1), 5 (steps 2-7) |
| DG8 | 18 |
| DG9 | 5 (DLG7 goldens) |
| SP1 | 8 |
| SP2, SP3 | 7 (engine); SP3's manifest side is `_known_phrases`, unchanged, used by 5 |
| SP4 | 10 |
| SP5 | 9 |
| CM1 | 2 |
| CM2 | 10 |
| CM3 | 9 |
| CM4 | 10 |
| CM5 | 8 (plan), 15 (critic), 16 (judge-story), 17 (judge-clips), 4 (judge-stills) |
| CM6 | 19 |
| CM7 | 9 (the writer instruction); accepted risk R10 |
| 6.1 classes | 12 |
| 6.2 T1, T2, T3 | 11 |
| 6.3 audit | 14 (N, P, L, S classes), 11 (T1-T3, N18 rows), 7 (P14 row) |
| 6.4 code changes | 10 (Dialogue excluded from N4/N10; CM2's N3 change), 11 (T/N18 ids), 12 (ranking, `REPAIR_IDS`, `_new_rs37`), 14 (the rest) |
| 6.5 round controller | 12 |
| 6.6 PG1-PG4 | 13 |
| 6.6 PG5, PG6 | 12 |
| 6.7 re-check | 14 |
| 6.8 judge gate | 12 (engine), 19 (help, dry-run line) |
| 6.9 `bin/ltx-movie` text | 19 |
| 7 rule table | 7 (P14), 10 (N3 tail), 11 (T1-T3, N18, N16/N17 Dialogue), 14 (N11, L5, the advisory moves) |
| 8.1 | 8 |
| 8.2 | 9 |
| 8.3 | 15, 16 (`PATCH_FIELDS`) |
| 9.1, 9.2, 11.8 | the tasks named in the next table |
| 10.1 | 23 (replay test), 24 step 5 (recording) |
| 10.2, 10.3 | 24 step 5 (hand-off) |
| 11.1-11.5, 11.7, 11.9 | 20, 21 |
| 11.6 | 22 |
| 12 rollout | 24 (review, test-only re-baseline, DK1) |

### Test IDs and their owning task (each is owned by exactly one task)

| IDs | Task |
|---|---|
| DLG1, DLG2, DLG3 | 1 |
| DLG5, DLG34 | 2 |
| DLG4, DLG6 | 3 |
| DLG32 | 4 |
| DLG7, DLG8, DLG9, DLG10 | 5 |
| DLG31 | 6 |
| DLG11, DLG33 | 7 |
| DLG12 | 8 |
| DLG13, DLG14 | 9 |
| DLG15, Q1 amendment test | 10 |
| DLG16, DLG17 | 11 |
| DLG23, DLG24, DLG26 | 12 |
| DLG20, DLG22 | 13 |
| DLG18, DLG21, DLG25 | 14 |
| DLG19 | 15 |
| DLG30, Q2 amendment test | 16 |
| DLG29 | 17 |
| DLG27 | 18 |
| CA2, CA7, CA9 | 20 |
| CA1, CA3, CA4, CA5, CA8 | 21 |
| CA6 | 22 |
| DLG-H, DLG-K1, DK2, DK3, DK4, DK5, DK6 (fixture) | 23 |
| DK1, DK7 (hand-off) | 24 |
| Review Focus 1 / 2 / 3 / 4 / 5 | 9 / 5 / 5 / 11 / 1 |
| DLG28 | cut by the spec (movie-ui Compose field) |

Requirement IDs owned the same way: DG1-DG5 Task 1; DG6 Task 3; DG7 Task 5 (its step 1, the label, is Task 4's deliverable because Task 5 consumes it); DG8 Task 18; DG9 Task 5; SP1 Task 8; SP2, SP3 Task 7; SP4 Task 10; SP5 Task 9; CM1 Task 2; CM2 Task 10; CM3 Task 9; CM4 Task 10; CM5 Task 15 (its plan, judge-story, judge-clips and judge-stills pieces land in Tasks 8, 16, 17, 4); CM6 Task 19; CM7 Task 9.

## Plan decisions (where the spec is silent, split across sections, or self-contradictory)

1. **The DG9 over-cap line is 15 words, not 16.** `I carry a sealed letter from the harbour master for the abbot of this temple.` has 15 words; the spec calls it 16. Every message built from it (the T1 helper of 9.2, DLG9, DLG20, DLG25) uses the real count, `15 words`; DLG16's "16 words in 1 sentence" case uses its own 16-word line (`... from the old harbour master ...`). Both are over the 14-word cap, so the spec's intent holds.
2. **One cleanup order for a spoken line.** SP5 says writer dialogue gets `clean_writer`, then the DG3 step 4 quote replacement, then the leading `<phrase>:` strip; PG4 strips the phrase before the quote step. SP5's order turns `the courier: "Keep moving."` into `'Keep moving.'`; PG4's gives `Keep moving.`. The plan uses PG4's order in both places (`_clean_dialogue`), which gives the same result on every input SP5's order handles; Review Focus 1 pins it.
3. **`clean_writer` also drops a leading `dialogue:` label** (`_LABEL_RE`), extending RS13's "drop one leading field label" to the new key.
4. **A speaking panel always gets a `Dialogue:` field**, `"<phrase>:"` when its part is empty, so N18 ("has a speaker but no words") blocks a speaking panel whose writer failed; without it such a panel has neither Dialogue nor (per SP4) Narration and would pass.
5. **Message details the spec left to formatting:** the P14 shot note quotes both shots (`shot 'wide shot' changed to 'medium close-up'`), like the camera note; N17's "also shows %s" joins the other on-screen phrases with `", "`, each quoted; N17's camera-direction message quotes the sentence and applies to any on-screen speaker (Dialogue or the Narration alias); PG3's reasons count the old span and quote the dropped sentence. The N16/N17 Narration (alias) branches run only when the panel has no parseable `Dialogue:`.
6. **The judge gate's `judgment.patches.json`** "written into the best round's directory" (6.8) is the file `bin/judge-story --patches` already writes next to that round's story.md, which `run_judge` reads; the gate does not rewrite it with fewer keys.
7. **LoRA patches still may not add a LoRA finding.** `apply_patches`' "would break" guard compared hard LoRA findings; with L2-L4 advisory (Task 14) it compares hard plus advisory, so a critic still cannot stack a second motion LoRA (keeps `test_rst31` and `test_lct28`, which 9.2 does not list).
8. **`_casting_plan` has a fifth unusable-plan reason**, `its cast is not a list of objects`: 11.2 lists that condition for a usable plan but gives no reason string for it. Order: object, schema, cast, beat count, beat cast.
9. **`story_checks.json` puts `"unresolved"` right after `"hard"`.**
10. **`_Run.critic_loop()`** is the 6.5 loop factored out of `go()`, so DLG-K1 can "run the 6.5 loop" on a replayed round 0.
11. **Where the Dialogue exclusion from N4/N10 and CM2 land:** Task 10, with the first assembled `Dialogue:` field and the first pasted `<Speaker> faces the camera.` (otherwise that sentence trips N3, which stays hard until Task 14); the N16/N17 Dialogue variants are advisory from Task 11 on.
12. **A re-check that exits 2 lists only the blocking messages** and prints no `Warning: unresolved` lines (6.7 specifies the warnings only for the rc-0 case).
13. **`parse_dialogue` skips empty phrases** when matching (a plan cast entry with an empty phrase would otherwise "match" any value that starts with a colon).
14. **Existing-test edits outside the 9.2 list, each for a 9.2 reason:** `test_rst17b` (the fix-block text, as `test_rst16`), the `--no-narration` tail of `test_rst20c` (`narration_speech` is deleted), `test_lct28` (the 3-tuple). `test_rst14`, `test_rst55`, `test_rst56`, `test_rst56b_n15_masks_declared_phrase` and `test_rst56c` are listed by 9.2 but pass unchanged (they compare `hard + advisory`); DLG18 pins the classes. Test names are kept even where the behaviour now reads against them (`test_rst29`, `test_rst52`, `test_rst55b`), with a comment, so every RST id stays stable for DK1.
15. **One commit per task** instead of spec 12's two feature commits (the controller's task sizing). `test_mut26` is re-based to the last pipeline-touching commit (Task 22) in its own test-only commit after the spec 12.3 design review (Task 24).
16. **DK2 and DK3 have their own tests** in `tests/test_dialogue.py`: `test_rst61`'s file list does not include `character_lib.py`, `bin/judge-clips`, `bin/judge-stills` or the new test file, and `test_rst62` fails at baseline on `bin/ltx-mlx-render` before it reaches the files this plan changes.
17. **`--speech-delivery`'s choices are written out in both CLIs**: `character_lib` is loaded lazily, so `SPEECH_DELIVERIES` is not importable at parse time; DLG3 pins the constant to the same three values.
18. **`tests/test_dialogue.py` stays stdlib plus pytest (9.1)**: panel stills are a base64 1x1 PNG, not Pillow-made images.
19. **Left unchanged, spec silent:** `bin/ltx-story-manifest`'s module-docstring paragraph "Spoken narration" still describes `speech_sentence`; `plan_free_report` keeps `clip_seconds=None` (6.0 s), as it has no frame count.

## Spec amendments

Controller rulings on this plan's two questions; amend the spec to match.

1. **The pasted facing sentence is not an S5 action (Q1).** SP4/CM1: in the robust engine, `character_lib.shots_violations(..., ignore_facing=True)` leaves a Motion: sentence that is exactly `<Phrase> faces the camera.` (for a cast or roster phrase) out of S5's action-sentence count, as the pasted camera sentence already is; every robust caller (`panel_checks`, both `recheck` paths, `plan_free_report`) passes it, and the legacy `--story-legacy` shots loop keeps the default (strict, byte-identical, Q2 of the spec). DLG34 is unchanged (`motion_problems` still counts the facing sentence as an action when given the phrases). Task 10, test `test_shots_s5_ignores_the_pasted_facing_sentence`.
2. **judge-story reads `unresolved` (Q2).** G5/2.6: `bin/judge-story --patches` reads `story_checks.json`'s `unresolved` (T2/T3) and shows them to the judge as `[advisory]`, ahead of the other advisories; they never become `[hard]` and never block (D6). Task 16, test `test_judge_story_reports_unresolved_as_advisory`.

## Execution handoff

Plan complete and saved to `qwen-agent-workspace/docs/superpowers/plans/2026-10-24-on-camera-dialogue.md`. Every Create/Append/Edit block was replayed in order against a scratch copy of the `fed1107` tree (each old text occurred exactly once at its turn, and every changed file compiled under Python 3.9.6 and 3.13). Please review the plan. Which execution approach would you prefer?

- **Subagent-driven**: a fresh subagent implements each task and a fresh reviewer checks it before the next one starts, then a whole-branch review at the end.
- **Native**: one session implements every task, then one fresh reviewer checks the whole branch.

For this plan I recommend **subagent-driven**, because its 24 tasks hand exact interfaces forward (Tasks 12-14 rewrite run tests that must keep holding through the next two tasks) and a mistake that ships costs live GPU render time in the DK7 runs.
