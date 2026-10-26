# Narrative Dialogue Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every spoken line the narrative quotes required on-camera dialogue: extract it deterministically, have the plan (or, for what it leaves out, the pipeline) assign it to a beat, paste it verbatim into that panel's `Dialogue:`, block on a new hard rule Q1 when a line is missing or out of order, let the critic repair Q1 with a dialogue patch, and refuse an infeasible line set before any model call. Speaking shots may also be medium shots that track, push in or pull back, the manifest speaks the line after the first action sentence of a chained or shots Motion, and crowds are setting, not cast.

**Architecture:** `story_engine.py` gains the quote extractor (`classify_quotes`, `spoken_lines`, `required_lines`), the pre-flight (`spoken_lines_problem`), plan `"spoken_lines"`/`"cast_notes"` and beat `"lines"`, the rewritten `coerce_speakers` around an extracted `speaking_coercion` (the widened F2 table), `drop_groups`, the plan-retry gate and the pipeline assignment `assign_missing_lines`, the writer's pasted `assigned_dialogue`, the Q1 check in `panel_checks` and `recheck`, the critic prompt's spoken-lines block and the Q1 dialogue patch in `apply_patches`. `character_lib.py` gains `is_facing_sentence` and `insert_speech(..., first_action=False)`; `bin/ltx-story-manifest`'s one speech call passes `first_action` under `--chain` and `--shots`. Engine assembly order is unchanged; only the chained `k >= 2` speaking camera sentence follows the beat.

**Tech Stack:** Python 3.13 (`python3`, pytest 8.3.4) and Python 3.9.6 (`/usr/bin/python3`, compile check only); standard library only in every touched module; the fake `bin/qwen-agent` and the plan/panel/critic builders of `tests/story_engine_testutil.py`; the manifest helpers of `tests/test_dialogue.py`; verbatim copies of the two recorded 2026-10-26 hockey runs as fixtures.

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-10-26-narrative-dialogue-fidelity-design.md`, revision 2 (fixes F1-F3 and the controller ruling SP-P; Section 11.3 "Open: None"). Every Edit below is written against commit `7aac623` (branch `regen-seed` tip: `qwen-agent-redteam` `44f3c4d` plus the regenerate-seed change, which touches only `bin/character`, `character_dataset.py`, `movie_ui_*.py`, `static/movie-ui` and tests). The spec's line numbers cite `44f3c4d`; `story_engine.py`, `character_lib.py`, `bin/ltx-story-manifest`, `tests/test_dialogue.py`, `tests/test_story_engine.py` and `tests/story_engine_testutil.py` are byte-identical at both commits, so every cited line holds. The `Files:` line numbers below cite `7aac623`; every Edit finds its text by content. The spec is binding; this plan changes no design decision. Where the plan had to read the spec, or the spec conflicts with a pinned test, the reading is listed in "Plan decisions"; the controller's three rulings are recorded there and in "Spec amendments".

## Global Constraints

From the spec, verbatim (section in brackets):

- [Status] "This spec makes every design choice ... The implementer makes no design decisions."
- [0.3] "**Not changed:** `bin/ltx-movie`, `bin/judge-story` (`PATCH_FIELDS` already has `"dialogue"`), `bin/judge-clips`, `bin/judge-stills`. `bin/ltx-story-manifest`, apart from G2b. The `--story-legacy` templates and path. `movie_ui_lib.py` and `static/*`. `ltx2_mlx_video_skill.py`."
- [0.4] Out of scope: "**Pacing.**"; "Branding legibility ..., spray realism and stray props."; "Lip-sync quality measurement."; "**Who says a line.** Q1 checks that the words are spoken, not that the narrative's speaker says them."; "screenplay form (`NAME: "line"` with no speech verb), single-quoted speech, `„…“` and `«…»` quotes, and nested quotes"; "Automatic splitting of an over-long quoted line."; "The legacy engine and the plan-free yardstick (`PLAN_FREE_IDS`): no Q1 there."; "Multi-speaker panels and off-screen speakers".
- [0.6] "F1, F2 and F3 (Sections 3-5) and the tests (Section 8) are must-haves. Nothing else is built. In particular, there is no dry-run line, no movie-ui field and no new CLI flag."
- [0.5 NK2] "`/usr/bin/python3` (3.9) and `python3` (3.13) both `py_compile` `story_engine.py`, `character_lib.py` and `bin/ltx-story-manifest`."
- [0.5 NK3] "Import sets are unchanged: no new import in any changed file."
- [0.5 NK6] "Every test outside Section 8.3 A passes unedited."
- [0.5 NK7] "Legacy output stays byte-identical." (`test_rst40`, `test_rst41`, `test_s52`, `test_casting_regression.py`)
- [8.1] "No test renders, contacts a server or reads the real HOME."
- [0.3 G6] "`tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` | `BASELINE` re-baseline in a **separate test-only follow-up commit**".

Repository rules (the controller's; every task's requirements include them):

- Standard library only in every Python file this plan touches; every new or changed file must run on Python 3.9.6 and 3.13: no `match` statement, no `X | Y` type expressions, no walrus operator, no `str.removeprefix`, no `zip(strict=)`, no parenthesised context managers.
- Tests never render, never contact a model server, a daemon or the Anthropic API, and never use the real `HOME` (`tests/test_narrative_fidelity.py` uses the autouse `story_env` fixture, as `tests/test_dialogue.py` does).
- Run tests as `cd /Users/reubenpatterson/local_agent_harness/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/<file>`; every pytest run prints a `pytest_asyncio` deprecation warning first, which is expected.
- Never stage `../.DS_Store`, `../.claude/`, `.claude/`, `../agent/__pycache__/` or the repo-root `../bin/`. Stage only the paths a task names and check `git diff --cached --name-only` before every commit. Never use `git stash`, `git reset` or `git checkout` of a path.
- Every commit message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (the commit commands below pass it as a second `-m`).
- Known pre-existing failures at `7aac623`, to be ignored when they fail exactly as at the baseline: `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets` (it fails on `bin/ltx-mlx-render`'s `struct` import, before it reaches the files this plan changes).
- `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` diffs `PIPELINE_FILES` against a pinned commit. `story_engine.py`, `character_lib.py` and `bin/ltx-story-manifest` are all in `PIPELINE_FILES` (checked at `7aac623`, `tests/test_movie_ui_builder.py:216-221`), so `test_mut26` fails from Task 1's commit until Task 13 re-baselines it in its own test-only commit. No task before 13 runs or edits it.
- The legacy `--story-legacy` outputs stay byte-identical: no task touches the legacy templates or path (`test_rst40`, `test_rst41`, `test_s52` and `tests/test_casting_regression.py` pass unchanged after every task).

House rules:

- `WS` = `/Users/reubenpatterson/local_agent_harness/qwen-agent-workspace`. The git root is one level up, so `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix. Run every command from `WS`.
- Every code block is copied exactly, byte for byte. A **Create** writes a new file whose whole content is the block. An **Append** adds two empty lines after the file's current last line (which ends with one newline), then the block. An **Edit** replaces one block of old text, which must occur exactly once in the file at that moment, with the new text; if the old text does not occur exactly once, stop and report: do not adapt it. A **Run this command** step runs its `bash` block from `WS`.
- The compile check in each task is this command, with the task's files as arguments; expected output is two lines, `compiled N` for 3.9 and then for 3.13:

```bash
for py in /usr/bin/python3 python3; do $py -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' FILES; done
```

## Review Focus

These five inputs are implied by the spec, are the ones most likely to hit a real user first, and no NF test exercises them. Each is pinned by a test in its owning task.

1. **A narrative typed with smart quotes and a curly apostrophe** (`says “It’s just a short climb.”`, what macOS text fields produce). Expected: the required line keeps the author's `’` in the plan prompt's block and in `Dialogue:`, Q1 passes, and a hand-typed `Dialogue:` with a straight apostrophe and no full stop also passes. Test: `test_review_focus_1_smart_quotes_in_the_narrative` (Task 9).
2. **A re-check of a story written before this change** (bin/ltx-movie re-checks an existing story.md on every rerun; its plan.json still casts the crowd and has no `lines`, `spoken_lines` or `cast_notes`). Expected: once its `Dialogue:` fields hold every quoted line (the QL14 hand edit) the re-check exits 0 with no Q1; without the edit it exits 2 and names the missing line. Test: `test_review_focus_2_recheck_of_a_story_written_before_this_change` (Task 9).
3. **A planner that makes the crowd the speaker of the beat holding a line** (the recorded 2x145 plan put "the cheering crowd" in beat 2). Expected: P15 drops the crowd, the line stays on that beat, its one remaining character becomes the speaker, and one note says so (`beat 2: P15 group cast: the cheering crowd is part of the setting, not a speaker; the beat's line goes to the FuboTV player`, Spec amendment 1). Test: `test_review_focus_3_the_planner_gives_a_line_to_the_crowd` (Task 6).
4. **A critic that re-types the missing line** (other case, curly quotes, no full stop: `The FuboTV Player: “it’s just fubotv”`). Expected: the Q1 patch applies, the stored `Dialogue:` text is the narrative's own spelling (`It's just FuboTV.`), and Q1 clears. Test: `test_review_focus_4_a_retyped_q1_patch_stores_the_narrative_words` (Task 12).
5. **A `--shots` movie whose narrative quotes lines** (each shot is its own still and S1/S3 are hard there). Expected: the plan's lines reach each speaking shot's `Dialogue:`, the shot rules do not trip on the pasted facing sentence or the `Dialogue:` line, and the run exits 0 with no Q1. Test: `test_review_focus_5_a_shots_movie_with_quoted_lines` (Task 10).

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `character_lib.py` | Modify (Task 1) | `is_facing_sentence(sentence, phrases)`; `insert_speech(text, sentence, phrases=(), first_action=False)` (SP-P1). |
| `bin/ltx-story-manifest` | Modify (Task 1) | The one `insert_speech` call passes `first_action=bool(args.chain or args.shots)` (SP-P2). |
| `story_engine.py` | Modify (Tasks 2-12) | QL1-QL4 constants and the extractor (2); the pre-flight (3); SM1-SM3, SM5 and `speaking_coercion` (4); GC2-GC4, P15, Q2, Q3 (5); beat `lines`, `spoken_lines`, the `coerce_speakers` rewrite, the retry gate, the `load_plan` defaults (6); the plan prompt (7); the panel prompt text and `assigned_dialogue` (8); Q1 (9); `assign_missing_lines` (10); the critic prompt (11); the Q1 patch (12). |
| `tests/fixtures/narrative_fidelity/` | Create (Task 2) | `narrative.txt`; `hockey-2x145/` and `hockey-1x241/`: the recorded replies and `parts.json`, `case.json`, `plan_reply_fixed.json` (spec 8.2). |
| `tests/test_narrative_fidelity.py` | Create (Task 1), Append (Tasks 2-12) | NF1-NF37 (without NF18) and Review Focus 1-5. |
| `tests/test_dialogue.py` | Modify (Tasks 4, 7, 8) | The spec 8.3 A edits of DLG11, DLG12, DLG13, DLG15, `test_shots_s5...`, `test_n16_n17_n18...`, DLG22. |
| `tests/test_story_engine.py` | Modify (Tasks 5, 6) | The spec 8.3 A edits of `test_rst13_normalization` and `test_rst39_outputs_and_layout`. |
| `tests/test_movie_ui_builder.py` | Modify (Task 13 only) | `test_mut26` `BASELINE`. |

The task order follows the interfaces: the manifest's speech placement first (independent of the engine), then the engine from the narrative outward (the extractor, the pre-flight, the speaking-shot table, groups, beat lines and the retry gate, the plan prompt, the writer, Q1, the pipeline assignment, the critic prompt, the critic patch), then the review and the test-only re-baseline. The suite stays green after every task except `test_mut26`, as stated above.

---

## Before Task 1: baseline record (controller; no code, no commit)

NK1 compares against the pass count recorded here. Nothing is written into the repository.

- [ ] **Step 1: Confirm the starting point.**

```bash
cd /Users/reubenpatterson/local_agent_harness/qwen-agent-workspace
git diff --stat 7aac623 HEAD -- . ':(exclude)docs' | tail -1   # expected: no output (HEAD's code tree is 7aac623's)
git status --short                               # expected: only ?? ../.claude/, ?? ../agent/__pycache__/, ?? ../bin/, ?? .claude/, ?? bin/action-from-dir (untracked at planning time) and ?? ../.DS_Store if present, plus this plan if it is not committed yet
ls tests/test_narrative_fidelity.py tests/fixtures/narrative_fidelity 2>&1 | grep -c "No such file"   # expected: 2
wc -l < story_engine.py                          # expected: 2997
wc -l < character_lib.py                         # expected: 1409
wc -l < bin/ltx-story-manifest                   # expected: 946
ls /Users/reubenpatterson/local_agent_harness/qwen-agent-workspace/generated/stories/hockey-2x145/story_rounds/round_0/plan_reply_1.txt /Users/reubenpatterson/local_agent_harness/qwen-agent-workspace/generated/stories/hockey-1x241/story_rounds/round_0/plan_reply_1.txt   # expected: both paths listed (Task 2 copies from them)
```

If any expected value differs, stop and report: every Edit below was written against this tree.

- [ ] **Step 2: Record the pytest and script baselines (about 12 minutes).**

```bash
D=/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-26-narrative-fidelity
mkdir -p $D
git rev-parse HEAD > $D/base-commit.txt
python3 -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
python3 tests/test_ltx_movie_offline.py 2>&1 | tail -1 | tee $D/baseline-offline.txt
```

Expected: the `FAILED` lines are exactly the two known pre-existing failures of Global Constraints; the offline script prints `OK n/n` (`OK 347/347` on the replay tree). Write any other difference into `$D/baseline-notes.txt`; Task 13 compares against what is recorded here.

---

### Task 1: Speech placement: the spoken line goes after the first action sentence (SP-P)

Implements SP-P1 (`character_lib.is_facing_sentence`, `insert_speech(..., first_action=False)`) and SP-P2 (the one manifest call). Tests NF34, NF35. Creates `tests/test_narrative_fidelity.py`, which every later task appends to. This is the first pipeline commit: `test_mut26` fails from here until Task 13.

**Files:**
- Modify: `character_lib.py` (`insert_speech` `:718-733`; a new function after `FACING_SENTENCE` `:1095`)
- Modify: `bin/ltx-story-manifest` (the `insert_speech` call `:830-831`)
- Create: `tests/test_narrative_fidelity.py`

**Interfaces:**
- Consumes: `character_lib._SENTENCE_SPLIT_RE`, `_is_camera_sentence(sentence, phrases=())`, `FACING_SENTENCE`, `speech_text(phrase, line, delivery)`, `ACOUSTIC_SENTENCE` (all existing); from `tests/test_dialogue.py` (imported as `dlg`): `_manifest_ws(tmp_path, monkeypatch, story_id, text, plan=None, images=1) -> (story_md, images, ws)`, `_manifest_argv(story_id, story_md, images, mode="chain", panels=2, frames=145, extra=())`, `_read_manifest(ws, story_id)`, `dlg.story_manifest` (the manifest module those helpers patch), `dlg.AC`.
- Produces: `character_lib.is_facing_sentence(sentence, phrases) -> bool`; `character_lib.insert_speech(text, sentence, phrases=(), first_action=False) -> str`. In `tests/test_narrative_fidelity.py`: the module header (`WS`, `FIXTURES`, `_load`, `character_lib`, `se`, `dlg`, the autouse `story_env` fixture, the `ws` fixture) and the constants `PLAYER = "the FuboTV player"`, `STOP_MOTION`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_nf34_insert_speech_after_the_first_action`, `test_nf35_manifest_places_the_line_after_the_first_action`.

**1.1.** Create `tests/test_narrative_fidelity.py`:

```python
"""Tests for narrative dialogue fidelity (docs/superpowers/specs/2026-10-26-narrative-dialogue-
fidelity-design.md, Section 8.1: NF1-NF37, without NF18, and the plan's Review Focus 1-5): the
narrative's quoted lines are required on-camera dialogue (Q1), speaking shots may move, the spoken
line is placed after the first action sentence, and crowds are setting, not cast.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py
Stdlib plus pytest. Every model call goes to the fake bin/qwen-agent of a temp workspace
(story_engine_testutil.make_ws); no test renders or reaches a model server, a daemon or the
Anthropic API, and every test runs under the autouse story_env fixture (a temporary HOME,
character library and LoRA catalog). The hockey fixtures under tests/fixtures/narrative_fidelity/
are verbatim copies of the two recorded 2026-10-26 runs, plus two hand-written plan replies.
"""

import copy
import importlib.machinery
import json
import os
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
FIXTURES = os.path.join(WS, "tests", "fixtures", "narrative_fidelity")
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402
import test_dialogue as dlg  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


character_lib = _load("character_lib_for_fidelity", "character_lib.py")
se = _load("story_engine_for_fidelity", "story_engine.py")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


# --- NF34, NF35: speech placement (SP-P) ------------------------------------------------------

PLAYER = "the FuboTV player"
STOP_MOTION = ("The FuboTV player skates forward, then halts in a sharp hockey stop that sprays ice "
               "mist into the air. He skates away from the camera. The FuboTV player faces the "
               "camera. The camera stays static.")
STOP_HEAD = ("The FuboTV player skates forward, then halts in a sharp hockey stop that sprays ice "
             "mist into the air. The FuboTV player faces the camera.")
STOP_TAIL = "He skates away from the camera. The camera stays static."


def test_nf34_insert_speech_after_the_first_action():
    lib = character_lib
    assert lib.insert_speech(STOP_MOTION, "S", [PLAYER], first_action=True) == (
        STOP_HEAD + " S " + STOP_TAIL)
    courier = ["the courier"]
    assert lib.insert_speech("The courier faces the camera. The courier runs. The courier waves. "
                             "The camera stays static.", "S", courier, first_action=True) == (
        "The courier runs. The courier faces the camera. S The courier waves. The camera stays "
        "static.")
    assert lib.insert_speech("The courier runs. The courier waves.", "S", courier,
                             first_action=True) == "The courier runs. S The courier waves."
    one = "The courier raises the letter. The courier faces the camera. The camera stays static."
    assert lib.insert_speech(one, "S", courier, first_action=True) == lib.insert_speech(
        one, "S", courier)
    said = 'The courier says, "Go."'
    assert lib.insert_speech(one, said, courier, first_action=False) == (
        "The courier raises the letter. The courier faces the camera. " + said
        + " The camera stays static.")
    assert lib.insert_speech(one, said, first_action=False) == (
        "The courier raises the letter. " + said + " The courier faces the camera. The camera "
        "stays static.")
    run = "The courier runs. The camera slowly pushes in. The camera holds."
    assert lib.insert_speech(run, said, courier, first_action=False) == (
        "The courier runs. " + said + " The camera slowly pushes in. The camera holds.")
    assert lib.insert_speech("The camera stays static. The camera holds.", said,
                             first_action=False) == (
        "The camera stays static. " + said + " The camera holds.")
    assert lib.insert_speech("The camera stays static.", said, first_action=False) == (
        "The camera stays static. " + said)
    he = 'He says: "Go."'
    assert lib.insert_speech("He runs. The camera tracks alongside the movement.", he,
                             first_action=False) == (
        'He runs. He says: "Go." The camera tracks alongside the movement.')
    assert lib.insert_speech("He runs. He jumps.", he, first_action=False) == (
        'He runs. He jumps. He says: "Go."')
    assert lib.is_facing_sentence("  the courier FACES the camera. ", courier)
    assert lib.is_facing_sentence("The FuboTV player faces the camera.", [PLAYER])
    assert not lib.is_facing_sentence("The courier faces the gate.", courier)
    assert not lib.is_facing_sentence("The courier faces the camera.", [])


HOCKEY_SETTING = ("The setting is a modern indoor ice hockey arena at night, a smooth white ice "
                  "rink floor, under bright overhead floodlights.")
PLAYER_DESC = ("a man in his late twenties with an athletic build wearing a reddish-orange and "
               "white hockey jersey")
HOCKEY_MANIFEST_PLAN = {"schema": "ltx-movie.plan.v1", "cast": [
    {"id": "c1", "phrase": PLAYER, "descriptor": PLAYER_DESC, "cast_name": None}],
    "beats": [{"cast": ["c1"]}, {"cast": ["c1"]}]}
CHAINED_STOP = """# The Stop

A hockey player stops short.

## Panel 1 — Skating In
Image: %s The FuboTV player glides forward on the ice.
Motion: The FuboTV player glides forward toward the camera. The camera stays static.
Narration: The crowd roars.

## Panel 2 — The Stop
Motion: %s
Dialogue: the FuboTV player: It's just FuboTV.
""" % (HOCKEY_SETTING, STOP_MOTION)
SHOTS_STOP = """# The Stop

A hockey player stops short.

## Characters
- "the FuboTV player": %s.

## Panel 1 — Skating In
Image: %s The FuboTV player glides forward on the ice. The shot is a medium shot.
Motion: The FuboTV player glides forward toward the camera. The camera stays static.
Narration: The crowd roars.

## Panel 2 — The Stop
Image: %s The FuboTV player halts on the ice. The FuboTV player faces the camera. The shot is a medium close-up.
Motion: %s
Dialogue: the FuboTV player: It's just FuboTV.
Narration: The crowd goes quiet.
""" % (PLAYER_DESC, HOCKEY_SETTING, HOCKEY_SETTING, STOP_MOTION)
NO_STILLS_STOP = """# The Stop

A hockey player stops short.

## Panel 1 — Skating In
Prompt: The FuboTV player glides forward toward the camera. The camera stays static.
Narration: The crowd roars.

## Panel 2 — The Stop
Prompt: The FuboTV player skates forward. He skates away from the camera. The FuboTV player faces the camera. The camera stays static.
Dialogue: the FuboTV player: It's just FuboTV.
"""


def test_nf35_manifest_places_the_line_after_the_first_action(tmp_path, monkeypatch):
    beats = STOP_HEAD + ' The FuboTV player says, "It\'s just FuboTV." ' + dlg.AC + " " + STOP_TAIL
    plain = STOP_HEAD + ' The FuboTV player says: "It\'s just FuboTV." ' + STOP_TAIL
    for delivery, motion in (("beats", beats), ("plain", plain)):
        story_md, images, mws = dlg._manifest_ws(tmp_path, monkeypatch, "nf35c", CHAINED_STOP,
                                                 plan=HOCKEY_MANIFEST_PLAN)
        extra = [] if delivery == "beats" else ["--speech-delivery", delivery]
        assert dlg.story_manifest.main(dlg._manifest_argv("nf35c", story_md, images,
                                                          extra=extra)) == 0
        panel = dlg._read_manifest(mws, "nf35c")["panels"][1]
        assert panel["motion_prompt"] == motion, delivery
        assert (panel["speaker"], panel["speech"]) == (PLAYER, "It's just FuboTV.")
    story_md, images, mws = dlg._manifest_ws(tmp_path, monkeypatch, "nf35s", SHOTS_STOP, images=2)
    assert dlg.story_manifest.main(dlg._manifest_argv("nf35s", story_md, images,
                                                      mode="shots")) == 0
    assert dlg._read_manifest(mws, "nf35s")["panels"][1]["motion_prompt"] == beats
    story_md, images, mws = dlg._manifest_ws(tmp_path, monkeypatch, "nf35n", NO_STILLS_STOP,
                                             plan=HOCKEY_MANIFEST_PLAN, images=0)
    assert dlg.story_manifest.main(dlg._manifest_argv("nf35n", story_md, images,
                                                      mode="no_images")) == 0
    assert dlg._read_manifest(mws, "nf35n")["panels"][1]["motion_prompt"] == (
        "The FuboTV player skates forward. He skates away from the camera. The FuboTV player "
        'faces the camera. The FuboTV player says, "It\'s just FuboTV." ' + dlg.AC
        + " The camera stays static.")
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py 2>&1 | tail -3
```

Expected: `2 failed`. NF34 fails with `TypeError: insert_speech() got an unexpected keyword argument 'first_action'`. NF35 fails on its first `motion_prompt` assertion, because today the line lands after "He skates away from the camera.".

- [ ] **Step 3: Implement.**

**3.1.** Edit `character_lib.py`: replace this text, which occurs exactly once:

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
```

with:

```python
def insert_speech(text, sentence, phrases=(), first_action=False):
    """text with sentence added before the run of trailing camera sentences
    (_is_camera_sentence with phrases, so a pasted "<Speaker> faces the camera." stays with the
    action), never before the first sentence; at the end when there is no such run (dialogue
    spec DG6). With first_action (bin/ltx-story-manifest --chain and --shots) and two or more
    action sentences before that run (neither a camera sentence nor a pasted facing sentence),
    sentence goes right after the first action sentence instead, any pasted facing sentence
    moves to just before it, and the trailing camera run stays last (narrative dialogue fidelity
    spec SP-P1)."""
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]
    trailing = 0
    while (trailing < len(sentences)
           and _is_camera_sentence(sentences[len(sentences) - 1 - trailing], phrases)):
        trailing += 1
    if first_action:
        body = sentences[:len(sentences) - trailing]
        actions = [i for i, s in enumerate(body)
                   if not _is_camera_sentence(s, phrases) and not is_facing_sentence(s, phrases)]
        if len(actions) >= 2:
            facing = [s for s in body if is_facing_sentence(s, phrases)]
            rest = [s for s in body if not is_facing_sentence(s, phrases)]
            at = len([s for s in body[:actions[0] + 1] if not is_facing_sentence(s, phrases)])
            return " ".join(rest[:at] + facing + [sentence] + rest[at:]
                            + sentences[len(sentences) - trailing:])
    if len(sentences) > 1 and trailing >= 1:
```

**3.2.** Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
FACING_SENTENCE = "%s faces the camera."


def _drop_facing(text, phrases):
```

with:

```python
FACING_SENTENCE = "%s faces the camera."


def is_facing_sentence(sentence, phrases):
    """True when sentence is exactly a pasted "<Phrase> faces the camera." for one of phrases
    (case-insensitive; narrative dialogue fidelity spec SP-P1)."""
    return sentence.strip().lower() in {(FACING_SENTENCE % (p[:1].upper() + p[1:])).lower()
                                        for p in phrases}


def _drop_facing(text, phrases):
```

**3.3.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
            motion_prompt = lib_.insert_speech(
                motion_prompt, lib_.speech_text(speaker, speech, args.speech_delivery), [speaker])
```

with:

```python
            motion_prompt = lib_.insert_speech(
                motion_prompt, lib_.speech_text(speaker, speech, args.speech_delivery), [speaker],
                first_action=bool(args.chain or args.shots))
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py tests/test_dialogue.py tests/test_character_lib.py tests/test_ltx_story_manifest_chain.py tests/test_casting_regression.py 2>&1 | tail -1
```

Expected: `passed` and `1 skipped` (DLG-K1), with no failure. DLG4, DLG7-DLG10, `test_review_focus_2`, `test_review_focus_3`, `test_spoken_narration_helpers` and `test_v2_golden_byte_identical` pass unchanged (spec 8.3 C). Then the compile check with `FILES` = `character_lib.py bin/ltx-story-manifest tests/test_narrative_fidelity.py`; expected `compiled 3` twice.

- [ ] **Step 5: Commit.**

```bash
git add character_lib.py bin/ltx-story-manifest tests/test_narrative_fidelity.py
git diff --cached --name-only    # expected: qwen-agent-workspace/bin/ltx-story-manifest, qwen-agent-workspace/character_lib.py, qwen-agent-workspace/tests/test_narrative_fidelity.py
git commit -m "feat(dialogue): speak the line after the first action sentence in chained and shots motion (SP-P, NF34, NF35)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The fixtures and the spoken lines of a narrative (QL1-QL4)

Implements G4 (spec 8.2: the recorded copies and the four hand-written files), QL1 (with the GC1 constants, which QL2 step 5(b) uses), QL2, QL3 and QL4. Tests NF1, NF2, NF3, NF4.

**Files:**
- Create: `tests/fixtures/narrative_fidelity/narrative.txt`, `tests/fixtures/narrative_fidelity/hockey-2x145/{plan_reply_1.txt, panel_01_reply_1.txt, panel_02_reply_1.txt, parts.json, case.json, plan_reply_fixed.json}`, `tests/fixtures/narrative_fidelity/hockey-1x241/{plan_reply_1.txt, panel_01_reply_1.txt, parts.json, case.json, plan_reply_fixed.json}`
- Modify: `story_engine.py` (a new block after `_goal_paragraph` `:373-374`)
- Modify: `tests/test_narrative_fidelity.py` (append)

**Interfaces:**
- Consumes: `story_engine.StoryContext.narration` (`True`, `"speech"` or `False`).
- Produces (in `story_engine`): the constants `QUOTE_RE`, `_LINE_WORD_RE`, `_CLAUSE_BREAK_RE`, `_QUOTE_EDGE_CHARS`, `BEFORE_WINDOW_WORDS = 6`, `AFTER_WINDOW_WORDS = 4`, `SPEECH_VERBS`, `CALL_VERBS`, `CLAUSE_STOP_WORDS`, `NOT_SPEAKER_WORDS`, `GROUP_NOUNS`, `GROUP_DESCRIPTOR_RE`, `SPOKEN_LINES_HEADER`; `line_words(text) -> [str]`; `classify_quotes(narrative) -> [(inner, spoken)]`; `spoken_display(inner) -> str`; `spoken_lines(narrative) -> [str]`; `required_lines(ctx) -> [str]`. In `tests/test_narrative_fidelity.py`: `_hockey(case) -> dict` (the `case.json`), `HOCKEY` (the narrative, stripped), `LINE1`, `LINE2`, `_hockey_ctx(ws, case, **kw) -> StoryContext`.

- [ ] **Step 1: Copy the fixtures and write the failing tests.**

New tests in this task: `test_nf1_the_hockey_narrative`, `test_nf2_which_quotes_are_spoken`, `test_nf3_line_words`, `test_nf4_required_lines`.

**1.1.** Run this command (from WS):

```bash
D=tests/fixtures/narrative_fidelity
R=/Users/reubenpatterson/local_agent_harness/qwen-agent-workspace/generated/stories
mkdir -p $D/hockey-2x145 $D/hockey-1x241
for f in plan_reply_1.txt panel_01_reply_1.txt panel_02_reply_1.txt parts.json; do
    cp "$R/hockey-2x145/story_rounds/round_0/$f" "$D/hockey-2x145/$f"
done
for f in plan_reply_1.txt panel_01_reply_1.txt parts.json; do
    cp "$R/hockey-1x241/story_rounds/round_0/$f" "$D/hockey-1x241/$f"
done
(cd $D && shasum -a 256 hockey-2x145/plan_reply_1.txt hockey-2x145/panel_01_reply_1.txt hockey-2x145/panel_02_reply_1.txt hockey-2x145/parts.json hockey-1x241/plan_reply_1.txt hockey-1x241/panel_01_reply_1.txt hockey-1x241/parts.json)
```

Expected output, exactly (the recorded files are byte-for-byte copies; any other hash: stop and report):

```text
e663a8484efa81f795cbb9894ef536aab650e8073e3897229914fcddf52024e8  hockey-2x145/plan_reply_1.txt
e2aaed0d257415032df00ea799a52387ec755fbbdfccc2359a02bafb662acd83  hockey-2x145/panel_01_reply_1.txt
a69ba349e80cea7cd4a131ee7f6c0d9eb198cdd8342b7c09d0ea08a9b4ad195e  hockey-2x145/panel_02_reply_1.txt
88f39df435b3f2e51234e1a4a787ab3c3aa87bae5ad976dcd95e10802f375c70  hockey-2x145/parts.json
d4b1ad9603065e0ed8376e2b8825acd35fc617f86fab193f1fa426cc30baf584  hockey-1x241/plan_reply_1.txt
1458a77b92f76b02147e6b7b77f4d1ff05b7ab4ffbd5ca840e65ee13b73346df  hockey-1x241/panel_01_reply_1.txt
9884b867ddb65fea1095195d4f1b60436847dc2f46d66253b68525307a539ebf  hockey-1x241/parts.json
```

**1.2.** Create `tests/fixtures/narrative_fidelity/narrative.txt` (one line, then a newline; byte-identical to `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/hockey/narrative.txt`, see Plan decision 1):

```text
A hockey player in a reddish-orange and white uniform with "FuboTV" in a big logo on the front stands in a hockey rink with "FuboTV" on the sides of the rink and on digital banners on the bleachers, with cheering crowds in the stands. He skates forward towards the camera and says "Getting the best deal on hockey isn't a hat trick..." then stops short, kicking up ice mist into the air, then says "It's just FuboTV." then skates away.
```

**1.3.** Create `tests/fixtures/narrative_fidelity/hockey-2x145/case.json`:

```json
{"story_id": "hockey-2x145", "panels": 2, "seconds": "6", "frames": 145, "goal": "a polished, realistic FuboTV hockey promo: on-camera lines delivered by the player, a hockey stop with ice spray, legible FuboTV branding"}
```

**1.4.** Create `tests/fixtures/narrative_fidelity/hockey-1x241/case.json`:

```json
{"story_id": "hockey-1x241", "panels": 1, "seconds": "10", "frames": 241, "goal": "a polished, realistic FuboTV hockey promo: on-camera lines delivered by the player, a hockey stop with ice spray, legible FuboTV branding"}
```

**1.5.** Create `tests/fixtures/narrative_fidelity/hockey-2x145/plan_reply_fixed.json` (the JSON of `plan_reply_1.txt` with `beats[0]["lines"] = [1]`, `beats[1]["speaker"] = "c1"` and `beats[1]["lines"] = [2]`; the crowd `c2` is kept on purpose):

```json
{
  "title": "FuboTV: It's Just FuboTV",
  "logline": "A FuboTV hockey player skates toward the camera, delivers a deal line, and finishes with a hard stop that sprays ice before skating away.",
  "cast": [
    {
      "id": "c1",
      "phrase": "the FuboTV player",
      "descriptor": "a man in his late twenties, athletic build, light skin, short dark hair, wearing a reddish-orange and white hockey jersey with a large FuboTV logo on the chest, white pants, black skates, and a white helmet with a clear visor"
    },
    {
      "id": "c2",
      "phrase": "the cheering crowd",
      "descriptor": "a dense group of spectators in their twenties and thirties, mixed skin tones, casual winter clothing, seated in the bleachers behind the rink boards, some with raised arms and open mouths, cheering"
    }
  ],
  "locations": [
    {
      "id": "l1",
      "setting": "The setting is a modern indoor ice hockey arena at night, a smooth white ice rink floor, bright overhead floodlights with FuboTV boards and banners around the perimeter."
    }
  ],
  "props": [
    {
      "id": "p1",
      "name": "hockey stick"
    },
    {
      "id": "p2",
      "name": "FuboTV rink boards"
    },
    {
      "id": "p3",
      "name": "digital bleacher banners"
    }
  ],
  "beats": [
    {
      "index": 1,
      "arc": "introduction",
      "action": "The FuboTV player skates forward toward the camera, gliding steadily across the ice while speaking directly to the lens.",
      "shot": "medium close-up",
      "camera": "static",
      "location": "l1",
      "cast": [
        "c1"
      ],
      "speaker": "c1",
      "lines": [
        1
      ]
    },
    {
      "index": 2,
      "arc": "resolution",
      "action": "The FuboTV player skates forward, halts in a sharp hockey stop that sprays ice mist, then skates away from the camera.",
      "shot": "medium shot",
      "camera": "static",
      "location": "l1",
      "cast": [
        "c1",
        "c2"
      ],
      "speaker": "c1",
      "lines": [
        2
      ]
    }
  ],
  "loras": {
    "global": [],
    "per_beat": {},
    "stills": []
  }
}
```

**1.6.** Create `tests/fixtures/narrative_fidelity/hockey-1x241/plan_reply_fixed.json` (the JSON of `plan_reply_1.txt` with `beats[0]["speaker"] = "c1"` and `beats[0]["lines"] = [1, 2]`):

```json
{
  "title": "FuboTV: It's Just FuboTV",
  "logline": "A FuboTV hockey player skates toward the camera, delivers a deal line, and finishes with a hard stop that sprays ice before skating away.",
  "cast": [
    {
      "id": "c1",
      "phrase": "the FuboTV player",
      "descriptor": "a man in his late twenties, athletic build, light skin, short brown hair, wearing a reddish-orange and white hockey jersey with a large FuboTV logo on the chest, white pants, black skates, and a white helmet with a clear visor"
    }
  ],
  "locations": [
    {
      "id": "l1",
      "setting": "The setting is a modern indoor hockey arena, with a white ice rink, reddish-orange boards, and bright overhead lights reflecting off the glossy surface."
    }
  ],
  "props": [
    {
      "id": "p1",
      "name": "FuboTV jersey"
    },
    {
      "id": "p2",
      "name": "hockey skates"
    },
    {
      "id": "p3",
      "name": "ice mist"
    }
  ],
  "beats": [
    {
      "index": 1,
      "arc": "climax",
      "action": "The FuboTV player skates forward toward the camera, stops abruptly in a hockey stop that sprays ice mist into the air, then skates away from the camera.",
      "shot": "medium shot",
      "camera": "tracking",
      "location": "l1",
      "cast": [
        "c1"
      ],
      "speaker": "c1",
      "lines": [
        1,
        2
      ]
    }
  ],
  "loras": {
    "global": [],
    "per_beat": {},
    "stills": []
  }
}
```

**1.7.** Run this command (from WS):

```bash
shasum -a 256 tests/fixtures/narrative_fidelity/narrative.txt
```

Expected: `7801957a0e5a4a741039e9954a507e6b2d21af384f2044bd42d5b6f3459427ca  tests/fixtures/narrative_fidelity/narrative.txt` (the recorded narrative's hash). Any other hash: stop and report.

**1.8.** Append to `tests/test_narrative_fidelity.py`:

```python
# --- NF1-NF4: the spoken lines of a narrative (QL1-QL4) -----------------------------------------

def _hockey(case):
    """The case.json of a recorded hockey run (spec 8.2)."""
    with open(os.path.join(FIXTURES, case, "case.json"), encoding="utf-8") as f:
        return json.load(f)


with open(os.path.join(FIXTURES, "narrative.txt"), encoding="utf-8") as _f:
    HOCKEY = _f.read().strip()
LINE1 = "Getting the best deal on hockey isn't a hat trick..."
LINE2 = "It's just FuboTV."


def _hockey_ctx(ws, case, **kw):
    """The StoryContext of a recorded hockey run (spec 8.1): chained, --speech-only, the case's
    panels, seconds, clip length and goal; keyword arguments replace fields."""
    c = _hockey(case)
    fields = dict(story_id=c["story_id"], mode="chained", panels=c["panels"],
                  seconds=c["seconds"], clip_seconds=c["frames"] / 24.0, narration="speech",
                  narrative=HOCKEY, goal=c["goal"])
    fields.update(kw)
    return seu.make_ctx(se, ws, **fields)


def test_nf1_the_hockey_narrative():
    assert se.classify_quotes(HOCKEY) == [("FuboTV", False), ("FuboTV", False), (LINE1, True),
                                          (LINE2, True)]
    assert se.spoken_lines(HOCKEY) == [LINE1, LINE2]
    assert se.line_words(LINE1) == ["getting", "the", "best", "deal", "on", "hockey", "isn't", "a",
                                    "hat", "trick"]


NF2_CASES = (
    ("She whispers, “Keep moving.”", ["Keep moving."]),
    ('"Run!" he shouts.', ["Run!"]),
    ('"Wait," she says, "I\'m coming."', ["Wait.", "I'm coming."]),
    ('He says to the old monk, "Rest here."', ["Rest here."]),
    ('"Hi," the old monk says.', ["Hi."]),
    ('A sign that says "OPEN" hangs on the door.', []),
    ('The scoreboard says "GOAL".', []),
    ('The shop called "Joe\'s" is closed.', []),
    ('He called out "Over here!"', ["Over here!"]),
    ('The monk says nothing, pointing at the "EXIT" sign.', []),
    ('He nods. "Go!" flashes on the screen.', []),
    ('He says "Keep moving.', []),
    ('He says "".', []),
    ('He says "...".', []),
    ('He says "Wait…"', ["Wait..."]),
    ('He says "Keep moving" and leaves.', ["Keep moving."]),
    ('A sign says "OPEN" and he says "Come in."', ["Come in."]),
    ('He looks at the "FuboTV" logo and says "Wow."', ["Wow."]),
    ('He wears a "Fubo" cap and says nothing.', []),
    ('He says nothing and points at the "EXIT" sign.', []),
    ('He calls his dog "Rex"', []),
    ('The crowd chants "Go Fubo!" as he says hello.', []),
    ('The crowd yells "Goal!"', []),
)


def test_nf2_which_quotes_are_spoken():
    for narrative, expected in NF2_CASES:
        assert se.spoken_lines(narrative) == expected, narrative
    assert se.spoken_lines(HOCKEY) == [LINE1, LINE2]


def test_nf3_line_words():
    for text in ("It's just FuboTV.", "IT’S JUST FUBOTV", "it‘s just fubotv...", "It's  just FuboTV…",
                 "it's, just; FuboTV!"):
        assert se.line_words(text) == ["it's", "just", "fubotv"], text
    assert se.line_words("Café au lait, s’il vous plaît.") == [
        "café", "au", "lait", "s'il", "vous", "plaît"]
    assert se.line_words("a well-known stop") == ["a", "well", "known", "stop"]
    assert se.line_words("...") == []


def test_nf4_required_lines(ws):
    for narration in (True, "speech"):
        assert se.required_lines(_hockey_ctx(ws, "hockey-2x145", narration=narration)) == [
            LINE1, LINE2], narration
    assert se.required_lines(_hockey_ctx(ws, "hockey-2x145", narration=False)) == []
    assert se.required_lines(seu.make_ctx(se, ws)) == []
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py 2>&1 | tail -3
```

Expected: `4 failed, 2 passed`, each failure an `AttributeError: module 'story_engine_for_fidelity' has no attribute ...` (`classify_quotes`, `spoken_lines`, `line_words`, `required_lines`).

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def _goal_paragraph(goal):
    return "" if goal is None else "The target output goal is " + goal + ".\n\n"
```

with:

```python
def _goal_paragraph(goal):
    return "" if goal is None else "The target output goal is " + goal + ".\n\n"


# Narrative dialogue fidelity (docs/superpowers/specs/2026-10-26-narrative-dialogue-fidelity-
# design.md QL1, GC1): the narrative's quoted spoken lines are required on-camera dialogue (Q1),
# and a group of people is setting, never cast.
QUOTE_RE = re.compile(r'"([^"]*)"')
_LINE_WORD_RE = re.compile(r"[^\W_]+(?:'[^\W_]+)*")
_CLAUSE_BREAK_RE = re.compile(r"[.!?;,]")
_QUOTE_EDGE_CHARS = " \t\n,:;—–-"
BEFORE_WINDOW_WORDS = 6
AFTER_WINDOW_WORDS = 4
SPEECH_VERBS = frozenset("""
    say says said saying ask asks asked asking reply replies replied replying
    answer answers answered answering shout shouts shouted shouting yell yells yelled yelling
    scream screams screamed screaming cry cries cried crying
    whisper whispers whispered whispering murmur murmurs murmured murmuring
    mutter mutters muttered muttering exclaim exclaims exclaimed exclaiming
    announce announces announced announcing declare declares declared declaring
    tell tells told telling speak speaks spoke speaking""".split())
CALL_VERBS = frozenset(("call", "calls", "called", "calling"))     # speech only before "out"
CLAUSE_STOP_WORDS = frozenset("and then as but while before after until so or when".split())
NOT_SPEAKER_WORDS = frozenset("""
    that which it sign signs banner banners logo logos screen screens scoreboard jumbotron
    board boards billboard poster posters label caption display shirt jersey note card""".split())
GROUP_NOUNS = frozenset("""
    crowd crowds audience audiences fans spectators onlookers bystanders passers-by passersby
    pedestrians commuters supporters cheerleaders throng throngs mob mobs masses public
    congregation team teams squad squads band bands people extras""".split())
GROUP_DESCRIPTOR_RE = re.compile(
    r"^an?\s+(?:[A-Za-z-]+\s+){0,2}(?:group|crowd|throng|mob|mass|sea|line|row|pack|band|team|"
    r"squad|horde|swarm|flock|herd)\s+of\b", re.IGNORECASE)
SPOKEN_LINES_HEADER = ("Spoken lines (the narrative quotes these words; the movie must speak "
                       "every one of them on camera, word for word, in this order):")


def line_words(text):
    """The words of a text for spoken-line matching (QL2): lower case, curly apostrophes made
    straight, an apostrophe inside a word kept, every other non-letter, non-digit character a
    word break (so case, punctuation and an ellipsis never matter)."""
    return _LINE_WORD_RE.findall(text.replace("’", "'").replace("‘", "'").lower())


def _speech_verb_at(words, p):
    """True when words[p] is a speech verb (a call verb only right before "out") whose word
    before it is not that, which, it, a text surface or a group noun (QL2 step 5)."""
    word = words[p]
    verb = word in SPEECH_VERBS or (word in CALL_VERBS and p + 1 < len(words)
                                    and words[p + 1] == "out")
    return verb and (words[p - 1] if p > 0 else "") not in NOT_SPEAKER_WORDS | GROUP_NOUNS


def classify_quotes(narrative):
    """[(inner, spoken)] for every double-quoted span of the narrative, in order (QL2): curly
    double quotes count as straight ones and pair left to right (an unmatched last quote is
    ignored); inner is the quoted text with its whitespace collapsed; spoken is True when a
    speech verb lies in the clause before the quote (at most 6 words back, after the last
    conjunction) or in the clause after it (at most 4 words on, before the first conjunction)."""
    text = narrative.replace("“", '"').replace("”", '"')
    matches = list(QUOTE_RE.finditer(text))
    out = []
    for i, match in enumerate(matches):
        prev_end = matches[i - 1].end() if i > 0 else 0
        next_start = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        before = line_words(_CLAUSE_BREAK_RE.split(
            text[prev_end:match.start()].rstrip(_QUOTE_EDGE_CHARS))[-1])
        stops = [j for j, w in enumerate(before) if w in CLAUSE_STOP_WORDS]
        if stops:
            before = before[stops[-1] + 1:]
        after = line_words(_CLAUSE_BREAK_RE.split(
            text[match.end():next_start].lstrip(_QUOTE_EDGE_CHARS))[0])
        stops = [j for j, w in enumerate(after) if w in CLAUSE_STOP_WORDS]
        if stops:
            after = after[:stops[0]]
        spoken = (any(_speech_verb_at(before, p)
                      for p in range(max(0, len(before) - BEFORE_WINDOW_WORDS), len(before)))
                  or any(_speech_verb_at(after, p)
                         for p in range(min(AFTER_WINDOW_WORDS, len(after)))))
        out.append((" ".join(match.group(1).split()), spoken))
    return out


def spoken_display(inner):
    """The display text of a quoted spoken line (QL3): one surrounding pair of straight or curly
    double quotes removed, every other double quote an apostrophe, whitespace collapsed (the
    three steps of character_lib.clean_line), "…" written as "...", trailing commas, semicolons,
    colons and dashes removed, and a full stop added unless it ends in . ! or ?. The author's
    ellipsis is kept."""
    line = inner.strip()
    for left, right in (('"', '"'), ("“", "”")):
        if len(line) >= 2 and line.startswith(left) and line.endswith(right):
            line = line[1:-1].strip()
            break
    for quote in ('"', "“", "”"):
        line = line.replace(quote, "'")
    line = " ".join(line.split()).replace("…", "...").rstrip(" ,;:—–-")
    if not line.endswith((".", "!", "?")):
        line += "."
    return line


def spoken_lines(narrative):
    """The display text of every spoken quote of the narrative that has a word, in order (QL3)."""
    return [spoken_display(inner) for inner, spoken in classify_quotes(narrative)
            if spoken and line_words(inner)]


def required_lines(ctx):
    """The spoken lines the movie must speak on camera (QL4): none with --no-narration."""
    return [] if ctx.narration is False else spoken_lines(ctx.narrative)
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py tests/test_story_engine.py 2>&1 | tail -1
```

Expected: `1 failed` (`test_rst62_import_sets`, the known pre-existing failure) and the rest `passed`. Then the compile check with `FILES` = `story_engine.py tests/test_narrative_fidelity.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_narrative_fidelity.py tests/fixtures/narrative_fidelity
git diff --cached --name-only    # expected: the 12 files under qwen-agent-workspace/tests/fixtures/narrative_fidelity/, qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_narrative_fidelity.py
git commit -m "feat(story): extract the narrative's quoted spoken lines; hockey fixtures (QL1-QL4, NF1-NF4)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The pre-flight: an infeasible line set exits 2 before any model call (QL5)

Implements QL5 (`panels_needed`, `spoken_lines_problem`, `_n_sentences`, the `go()` hook). Tests NF5, NF6, NF31.

**Files:**
- Modify: `story_engine.py` (after `required_lines`, Task 2's block; `_Run.go()` `:2700-2702`)
- Modify: `tests/test_narrative_fidelity.py` (append)

**Interfaces:**
- Consumes: `required_lines(ctx)` (Task 2); `engine_seconds(ctx)`, `_character_lib(ws)`, `_Run.finish(code)` (existing); `character_lib.split_fragments`, `dialogue_word_cap(seconds, fragments)`, `DIALOGUE_MAX_WORDS = 14`, `DIALOGUE_MAX_FRAGMENTS = 3` (existing).
- Produces (in `story_engine`): `_n_sentences(n) -> str`; `_lines_fit(lib, seconds, group) -> bool`; `panels_needed(lib, seconds, lines) -> int`; `spoken_lines_problem(ctx) -> str or None`. In the tests: `COURIER_LINES` (the NF13 3-line narrative), `SIX_WORD_LINES` (the NF5 3-line narrative), `OVER_CAP`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_nf5_spoken_lines_problem`, `test_nf6_panels_needed`, `test_nf31_an_infeasible_line_set_exits_2_before_any_call`.

**1.1.** Append to `tests/test_narrative_fidelity.py`:

```python
# --- NF5, NF6, NF31: the pre-flight (QL5) ----------------------------------------------------------

COURIER_LINES = ('The courier says "Keep moving." Then he says "The gate is close." At the gate he '
                 'whispers "We made it."')
SIX_WORD_LINES = ('The courier says "Keep moving along the wet road." Then he says "The temple gate '
                  'is close now." At the gate he whispers "We made it here at last."')
OVER_CAP = "I carry a sealed letter from the harbour master for the abbot of this temple."
PANELS_PROBLEM = ("the narrative quotes 3 spoken lines, which need at least 2 panels of 6 seconds "
                  "(one panel speaks at most 14 words), but this movie has 1; use --panels 2 or "
                  "more, or longer clips (a larger --frames)")


def test_nf5_spoken_lines_problem(ws):
    def problem(narrative, **kw):
        return se.spoken_lines_problem(seu.make_ctx(se, ws, narrative=narrative, **kw))

    assert problem('The courier says "%s"' % OVER_CAP) == (
        "the narrative's spoken line 1 (\"%s\") is 15 words in 1 sentence; no clip fits it, because "
        "a spoken line has at most 14 words in at most 3 sentences; split it into shorter quoted "
        "lines in the narrative" % OVER_CAP)
    assert problem('The courier says "Stop. Wait. Look. Go."') == (
        "the narrative's spoken line 1 (\"Stop. Wait. Look. Go.\") is 4 words in 4 sentences; no "
        "clip fits it, because a spoken line has at most 14 words in at most 3 sentences; split it "
        "into shorter quoted lines in the narrative")
    ten = "I carry a letter for the abbot of this temple."
    assert problem('The courier says "%s"' % ten, seconds="4", clip_seconds=97 / 24.0) == (
        "the narrative's spoken line 1 (\"%s\") is 10 words in 1 sentence; a 4-second clip fits at "
        "most 9 words in 1 sentence; use longer clips (a larger --frames) or split it into shorter "
        "quoted lines in the narrative" % ten)
    assert problem('The courier says "%s"' % ten) is None
    assert problem(SIX_WORD_LINES, panels=1) == PANELS_PROBLEM
    assert problem(SIX_WORD_LINES, panels=2) is None
    assert problem(SIX_WORD_LINES, panels=1, narration=False) is None
    assert problem(seu.make_ctx(se, ws).narrative, panels=1) is None
    for case, panels in (("hockey-2x145", 2), ("hockey-2x145", 1), ("hockey-1x241", 1)):
        assert se.spoken_lines_problem(_hockey_ctx(ws, case, panels=panels)) is None, (case, panels)
    assert (se._n_sentences(1), se._n_sentences(2)) == ("1 sentence", "2 sentences")


def test_nf6_panels_needed():
    lib = character_lib
    six = 145 / 24.0
    assert se.panels_needed(lib, six, [LINE1, LINE2]) == 1
    assert se.panels_needed(lib, six, se.spoken_lines(SIX_WORD_LINES)) == 2
    four = ["Keep moving now, friend.", "The gate is close.", "We made it here.",
            "Please open the door."]
    assert se.panels_needed(lib, six, four) == 2
    assert se.panels_needed(lib, six, []) == 0
    assert se.panels_needed(lib, six, [OVER_CAP]) == 1


def test_nf31_an_infeasible_line_set_exits_2_before_any_call(ws, tmp_path, monkeypatch, capsys):
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(seu.plan_json("chained", 1))])
    ctx = seu.make_ctx(se, ws, panels=1, narrative=SIX_WORD_LINES)
    capsys.readouterr()
    rc, _advisories = se.run(ctx)
    assert rc == 2
    assert capsys.readouterr().err == "Error: " + PANELS_PROBLEM + "\n"
    assert seu.agent_log(log) == []
    with open(os.path.join(ctx.story_dir, "story_rounds", "run.json"), encoding="utf-8") as f:
        assert json.load(f)["exit"] == 2
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py 2>&1 | tail -3
```

Expected: `3 failed, 6 passed`. NF5 and NF6 fail with `AttributeError` (`spoken_lines_problem`, `panels_needed`); NF31 fails on `assert rc == 2`, because the run calls the fake agent's plan stage.

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def required_lines(ctx):
    """The spoken lines the movie must speak on camera (QL4): none with --no-narration."""
    return [] if ctx.narration is False else spoken_lines(ctx.narrative)
```

with:

```python
def required_lines(ctx):
    """The spoken lines the movie must speak on camera (QL4): none with --no-narration."""
    return [] if ctx.narration is False else spoken_lines(ctx.narrative)


def _n_sentences(n):
    """The text "1 sentence" or "<n> sentences" (QL5's new messages only)."""
    return "1 sentence" if n == 1 else "%d sentences" % n


def _lines_fit(lib, seconds, group):
    """True when the consecutive spoken lines of group, joined, fit one clip of seconds (QL5)."""
    text = " ".join(group)
    n = len(lib.split_fragments(text))
    return (n <= lib.DIALOGUE_MAX_FRAGMENTS
            and len(text.split()) <= lib.dialogue_word_cap(seconds, n))


def panels_needed(lib, seconds, lines):
    """The fewest panels that speak lines in order, packing consecutive lines greedily (QL5)."""
    needed, i = 0, 0
    while i < len(lines):
        j = i
        while j + 1 < len(lines) and _lines_fit(lib, seconds, lines[i:j + 2]):
            j += 1
        needed += 1
        i = j + 1
    return needed


def spoken_lines_problem(ctx):
    """Why the narrative's spoken lines cannot be spoken in this movie, or None (QL5): a line no
    clip fits, a line this clip length does not fit, or more lines than the panels can hold."""
    lines = required_lines(ctx)
    if not lines:
        return None
    lib = _character_lib(ctx.ws)
    secs = engine_seconds(ctx)
    for i, line in enumerate(lines, start=1):
        n = len(lib.split_fragments(line))
        words = len(line.split())
        if n > lib.DIALOGUE_MAX_FRAGMENTS or words > lib.DIALOGUE_MAX_WORDS:
            return ("the narrative's spoken line %d (\"%s\") is %d words in %s; no clip fits it, "
                    "because a spoken line has at most %d words in at most %d sentences; split it "
                    "into shorter quoted lines in the narrative"
                    % (i, line, words, _n_sentences(n), lib.DIALOGUE_MAX_WORDS,
                       lib.DIALOGUE_MAX_FRAGMENTS))
        cap = lib.dialogue_word_cap(secs, n)
        if words > cap:
            return ("the narrative's spoken line %d (\"%s\") is %d words in %s; a %s-second clip "
                    "fits at most %d words in %s; use longer clips (a larger --frames) or split it "
                    "into shorter quoted lines in the narrative"
                    % (i, line, words, _n_sentences(n), ctx.seconds, cap, _n_sentences(n)))
    needed = panels_needed(lib, secs, lines)
    if needed > ctx.panels:
        return ("the narrative quotes %d spoken lines, which need at least %d panels of %s seconds "
                "(one panel speaks at most %d words), but this movie has %d; use --panels %d or "
                "more, or longer clips (a larger --frames)"
                % (len(lines), needed, ctx.seconds, lib.dialogue_word_cap(secs, 1), ctx.panels,
                   needed))
    return None
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        for warning in catalog_warnings(ctx):
            print(warning)
        found, why = self.plan_round()
```

with:

```python
        for warning in catalog_warnings(ctx):
            print(warning)
        problem = spoken_lines_problem(ctx)
        if problem:
            print("Error: %s" % problem, file=sys.stderr)
            return self.finish(2)
        found, why = self.plan_round()
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py tests/test_story_engine.py tests/test_dialogue.py 2>&1 | tail -1
```

Expected: `1 failed` (`test_rst62_import_sets`), `1 skipped` and the rest `passed`. Then the compile check with `FILES` = `story_engine.py tests/test_narrative_fidelity.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_narrative_fidelity.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_narrative_fidelity.py
git commit -m "feat(story): refuse an infeasible spoken-line set before any model call (QL5, NF5, NF6, NF31)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Speaking shots may move: the coercion table, the chained camera sentence and N17 (SM1-SM3, SM5)

Implements SM1, SM2 (with `speaking_coercion` extracted from SP2 step 4, QL7), SM3 and SM5. Tests NF16, NF17, NF19; the spec 8.3 A edits of `test_dlg11_speaking_beat_coercion`, `test_dlg15_assembly_goldens_and_dedupe`, `test_shots_s5_ignores_the_pasted_facing_sentence`, `test_n16_n17_n18_dialogue_messages` and `test_dlg22_the_critic_rewrites_one_sentence`. The writer-text half of F2 (SM4) is Task 8.

**Files:**
- Modify: `story_engine.py` (`SPEAKING_SHOTS`/`SPEAKING_CAMERAS` and `coerce_speakers` `:710-755`; `pasted_pieces` `:822-824`, `:837`; `STILL_CAMERA_MOVES` `:1477-1479`; the N17 camera-direction message `:1774-1775`)
- Modify: `tests/test_dialogue.py` (`:589-599`, `:852-865`, `:903-907`, `:925`, `:1033-1034`, `:1260-1261`)
- Modify: `tests/test_narrative_fidelity.py` (append)

**Interfaces:**
- Consumes: `CAMERA_SENTENCES`, `_q`, `_facing(ctx, plan, k)` (existing).
- Produces (in `story_engine`): `SPEAKING_SHOTS = ("medium shot", "medium close-up", "close-up")`; `SPEAKING_CAMERAS = ("static", "slow push-in", "slow pull-back", "tracking")`; `speaking_camera(beat) -> str`; `speaking_coercion(ctx, plan, k) -> [note]` (beat k's speaker is already set; Tasks 6, 10 and 12 call it); `STILL_CAMERA_MOVES` (widened). `coerce_speakers(ctx, plan)` keeps its signature (Task 6 rewrites its body).

- [ ] **Step 1: Write the failing tests and the spec 8.3 A edits.**

New tests in this task: `test_nf16_the_speaking_coercion_table`, `test_nf17_pasted_pieces_of_a_speaking_panel`, `test_nf19_n17_accepts_a_moving_speaking_camera`.

**1.1.** Edit `tests/test_dialogue.py`: replace this text, which occurs exactly once:

```python
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
```

with:

```python
    assert (plan["beats"][1]["shot"], plan["beats"][1]["camera"]) == ("medium close-up", "tracking")
    assert (plan["beats"][2]["shot"], plan["beats"][2]["camera"]) == ("close-up", "slow push-in")
    assert plan["speech_notes"] == [
        "beat 2: P14 speaking beat: cast [c1, c2] changed to [c1] so the speaker is alone on screen",
        "beat 2: P14 speaking beat: shot 'wide shot' changed to 'medium close-up' so the speaker's "
        "face stays readable",
        "beat 3: P14 speaking beat: shot 'extreme close-up' changed to 'close-up' so the "
        "speaker's face stays readable"]
    assert se.plan_checks(ctx, plan, shape)[1][-3:] == plan["speech_notes"]
```

**1.2.** Edit `tests/test_dialogue.py`: replace this text, which occurs exactly once:

```python
                + "## Panel 2 — The Bend\nMotion: The courier leans into the bend. The courier "
                  "faces the camera. The camera stays static.\n" + DIALOGUE_LINE),
```

with:

```python
                + "## Panel 2 — The Bend\nMotion: The courier leans into the bend. The courier "
                  "faces the camera. The camera tracks alongside the movement.\n" + DIALOGUE_LINE),
```

**1.3.** Edit `tests/test_dialogue.py`: replace this text, which occurs exactly once:

```python
                  "is a medium close-up. The courier faces the camera. The camera stays static.\n"
                  + DIALOGUE_LINE + "Narration: Every street led down to the water.\n"),
```

with:

```python
                  "is a medium close-up. The courier faces the camera. The camera tracks "
                  "alongside the movement.\n"
                  + DIALOGUE_LINE + "Narration: Every street led down to the water.\n"),
```

**1.4.** Edit `tests/test_dialogue.py`: replace this text, which occurs exactly once:

```python
                "Motion: The courier leans into the bend. The courier faces the camera. The camera "
                "stays static.\n" + DIALOGUE_LINE
```

with:

```python
                "Motion: The courier leans into the bend. The courier faces the camera. The camera "
                "tracks alongside the movement.\n" + DIALOGUE_LINE
```

**1.5.** Edit `tests/test_dialogue.py`: replace this text, which occurs exactly once:

```python
    assert dict(se.panel_fields(ctx, plan, parts, 2))["Motion"] == (
        "The courier turns. The camera slowly pans left. The courier faces the camera. The camera "
        "stays static.")
    assert se.pasted_pieces(ctx, plan, 2)["motion"] == ["The courier faces the camera.",
                                                        "The camera stays static."]
```

with:

```python
    assert dict(se.panel_fields(ctx, plan, parts, 2))["Motion"] == (
        "The courier turns. The camera slowly pans left. The courier faces the camera. The camera "
        "tracks alongside the movement.")
    assert se.pasted_pieces(ctx, plan, 2)["motion"] == ["The courier faces the camera.",
                                                        "The camera tracks alongside the movement."]
```

**1.6.** Edit `tests/test_dialogue.py`: replace this text, which occurs exactly once:

```python
    assert panels[1]["motion"].endswith(" The courier faces the camera. The camera stays static.")
```

with:

```python
    assert panels[1]["motion"].endswith(" The courier faces the camera. The camera tracks "
                                        "alongside the movement.")
```

**1.7.** Edit `tests/test_dialogue.py`: replace this text, which occurs exactly once:

```python
        "panel 2: N17 speaking shot: Motion: has the camera direction 'The camera slowly pans "
        "left.' while 'the courier' speaks; a speaking shot keeps the camera static"])
```

with:

```python
        "panel 2: N17 speaking shot: Motion: has the camera direction 'The camera slowly pans "
        "left.' while 'the courier' speaks; while someone speaks the camera stays static, pushes "
        "in, pulls back or tracks them, so their face stays readable"])
```

**1.8.** Edit `tests/test_dialogue.py`: replace this text, which occurs exactly once:

```python
    assert ("Motion: " + ONE_CHANGED + " The courier faces the camera. The camera stays static.\n"
            + "Dialogue: the courier: " + LINE + "\n") in after
```

with:

```python
    assert ("Motion: " + ONE_CHANGED + " The courier faces the camera. The camera tracks "
            "alongside the movement.\n" + "Dialogue: the courier: " + LINE + "\n") in after
```

**1.9.** Append to `tests/test_narrative_fidelity.py`:

```python
# --- NF16, NF17, NF19: speaking shots may move (SM1-SM3, SM5) ------------------------------------

FACING = "The courier faces the camera."


def _speaking_beat(ctx, mode, n, k, **beat):
    """The normalized seu.plan_json plan whose beat k is spoken by c1 (beat: field overrides)."""
    raw = seu.plan_json(mode, n)
    raw["beats"][k - 1].update(speaker="c1", **beat)
    return se.normalize_plan(ctx, raw)[0]


def test_nf16_the_speaking_coercion_table(ws):
    ctx = seu.make_ctx(se, ws, mode="shots", panels=3)
    shots = {"extreme wide shot": "medium close-up", "wide shot": "medium close-up",
             "medium shot": "medium shot", "medium close-up": "medium close-up",
             "close-up": "close-up", "extreme close-up": "close-up", "": "medium close-up"}
    kept = ("static", "slow push-in", "slow pull-back", "tracking")
    assert sorted(shots) == sorted(se.SHOT_TYPES + ("",))
    for shot in se.SHOT_TYPES + ("",):
        for camera in se.CAMERA_KEYS + ("",):
            plan = _speaking_beat(ctx, "shots", 3, 2, shot=shot, camera=camera)
            want = (shots[shot], camera if camera in kept else "static")
            assert (plan["beats"][1]["shot"], plan["beats"][1]["camera"]) == want, (shot, camera)
            notes = []
            if want[0] != shot:
                notes.append("beat 2: P14 speaking beat: shot %s changed to %s so the speaker's "
                             "face stays readable" % (se._q(shot), se._q(want[0])))
            if want[1] != camera:
                notes.append("beat 2: P14 speaking beat: camera %s changed to 'static' so the "
                             "speaker's face stays readable" % se._q(camera))
            assert plan["speech_notes"] == notes, (shot, camera)
    plan = _speaking_beat(seu.make_ctx(se, ws), "chained", 3, 3, shot="extreme wide shot",
                          camera="slow pan left")
    assert (plan["beats"][2]["shot"], plan["beats"][2]["camera"]) == (
        "extreme wide shot", "slow pan left")
    assert plan["speech_notes"] == []
    assert se.speaking_camera({"camera": "tracking"}) == "tracking"
    assert se.speaking_camera({"camera": "slow tilt up"}) == "static"


def test_nf17_pasted_pieces_of_a_speaking_panel(ws):
    def pieces(mode, camera, field):
        ctx = seu.make_ctx(se, ws, mode=mode, panels=3)
        return se.pasted_pieces(ctx, _speaking_beat(ctx, mode, 3, 2, camera=camera), 2)[field]

    assert pieces("chained", "tracking", "motion") == [
        FACING, "The camera tracks alongside the movement."]
    assert pieces("chained", "slow pan left", "motion") == [FACING, "The camera stays static."]
    assert pieces("shots", "slow pull-back", "image")[-2] == FACING
    assert pieces("shots", "slow pull-back", "motion") == [FACING, "The camera pulls back."]
    assert pieces("no_stills", "static", "prompt")[-2:] == [FACING, "The camera stays static."]
    assert se.SPEAKING_CAMERA == dict(se.CAMERA_SENTENCES)["static"]
    assert not hasattr(se, "MOVING_FACING_SENTENCE")
    assert not hasattr(character_lib, "MOVING_FACING_SENTENCE")


def test_nf19_n17_accepts_a_moving_speaking_camera(ws):
    ctx = seu.make_ctx(se, ws)
    plan = _speaking_beat(ctx, "chained", 3, 2)
    lib = se._character_lib(WS)

    def n17(motion):
        fields = [("Motion", motion), ("Dialogue", "the courier: Keep moving.")]
        return se._field_checks(ctx, lib, plan, 2, "T", fields, {"Motion": motion}, ("N17",), [])

    assert n17("The courier waits. The camera slowly pans left.") == ([], [
        "panel 2: N17 speaking shot: Motion: has the camera direction 'The camera slowly pans "
        "left.' while 'the courier' speaks; while someone speaks the camera stays static, pushes "
        "in, pulls back or tracks them, so their face stays readable"])
    for camera in ("The camera tracks the courier.", "The camera pulls back.",
                   "The camera follows the courier.", "The camera slowly pushes in."):
        assert n17("The courier waits. " + camera) == ([], []), camera
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py tests/test_dialogue.py 2>&1 | tail -10
```

Expected: `8 failed`: NF16, NF17, NF19 (the coercion still drops tracking, `speaking_camera` does not exist, the old N17 text), and the five edited `test_dialogue.py` tests (`test_dlg11_speaking_beat_coercion`, `test_dlg15_assembly_goldens_and_dedupe`, `test_shots_s5_ignores_the_pasted_facing_sentence`, `test_n16_n17_n18_dialogue_messages`, `test_dlg22_the_critic_rewrites_one_sentence`).

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
SPEAKING_SHOTS = ("medium close-up", "close-up")
SPEAKING_CAMERAS = ("static", "slow push-in")


def coerce_speakers(ctx, plan):
    """The P14 notes of the speaking-beat coercion (dialogue spec SP2), in beat order. Every beat
    gets a "speaker": a cast id or "". A speaker the movie cannot have (--no-narration) or that is
    not a plan cast id is dropped. A kept speaker is alone in the beat's cast, and when the beat
    frames its own shot (not a chained continuation, k >= 2) its shot becomes a medium close-up
    or close-up and its camera static or a slow push-in. No other beat is ever changed."""
```

with:

```python
# Narrative dialogue fidelity spec SM1: a speaking beat may be a medium shot, and its camera may
# stay static, push in, pull back or track the speaker.
SPEAKING_SHOTS = ("medium shot", "medium close-up", "close-up")
SPEAKING_CAMERAS = ("static", "slow push-in", "slow pull-back", "tracking")


def speaking_camera(beat):
    """The beat's camera when a speaking shot may keep it, else "static" (SM1)."""
    return beat["camera"] if beat["camera"] in SPEAKING_CAMERAS else "static"


def coerce_speakers(ctx, plan):
    """The P14 notes of the speaking-beat coercion (dialogue spec SP2), in beat order. Every beat
    gets a "speaker": a cast id or "". A speaker the movie cannot have (--no-narration) or that is
    not a plan cast id is dropped. A kept speaker gets speaking_coercion. No other beat is ever
    changed."""
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
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

with:

```python
        beat["speaker"] = raw
        notes += speaking_coercion(ctx, plan, k)
    return notes


def speaking_coercion(ctx, plan, k):
    """The P14 notes of SP2 step 4 for beat k, whose speaker is already set (narrative dialogue
    fidelity spec QL7, SM2): the speaker is alone in the beat's cast, and when the beat frames
    its own shot (not a chained continuation, k >= 2) a shot wider than a medium shot becomes a
    medium close-up (an extreme close-up a close-up), and a camera that does not stay static,
    push in, pull back or track becomes static. Tracking is never coerced away."""
    notes = []
    beat = plan["beats"][k - 1]
    speaker = beat["speaker"]
    if beat["cast"] != [speaker]:
        notes.append("beat %d: P14 speaking beat: cast [%s] changed to [%s] so the speaker is "
                     "alone on screen" % (k, ", ".join(beat["cast"]), speaker))
        beat["cast"] = [speaker]
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

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    pieces of each assembled field that the writer does not write. A speaking panel adds the
    facing sentence (and, chained k >= 2, SPEAKING_CAMERA). The planned camera sentence is always
    listed, even when CM4 leaves it out of the assembled field."""
```

with:

```python
    pieces of each assembled field that the writer does not write. A speaking panel adds the
    facing sentence (and, chained k >= 2, the camera sentence of speaking_camera: the planned
    camera, or "The camera stays static." for a pan or tilt; narrative dialogue fidelity spec
    SM3). The planned camera sentence is always listed, even when CM4 leaves it out of the
    assembled field."""
```

**3.4.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        return {"motion": facing + ([SPEAKING_CAMERA] if facing else []), "narration": []}
```

with:

```python
        return {"motion": facing + ([dict(CAMERA_SENTENCES)[speaking_camera(beat)]]
                                    if facing else []), "narration": []}
```

**3.5.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
# N17: the CAMERA_MOTION_RE words that keep a speaking shot still (a slow push-in is planned).
STILL_CAMERA_MOVES = ("static", "still", "hold", "holds", "locked-off", "push in", "pushes in",
                      "push-in")
```

with:

```python
# N17: the CAMERA_MOTION_RE words a speaking shot may use: it stays still, pushes in, pulls back
# or tracks the speaker (narrative dialogue fidelity spec SM1, SM5).
STILL_CAMERA_MOVES = ("static", "still", "hold", "holds", "locked-off", "push in", "pushes in",
                      "push-in", "pull back", "pulls back", "pull-back", "track", "tracks",
                      "tracking", "follow", "follows")
```

**3.6.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
                        "has the camera direction %s while %s speaks; a speaking shot keeps the "
                        "camera static" % (_q(sentence), _q(speaker)))
```

with:

```python
                        "has the camera direction %s while %s speaks; while someone speaks the "
                        "camera stays static, pushes in, pulls back or tracks them, so their face "
                        "stays readable" % (_q(sentence), _q(speaker)))
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py tests/test_dialogue.py tests/test_story_engine.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_judge_story.py 2>&1 | tail -1
```

Expected: `1 failed` (`test_rst62_import_sets`), `1 skipped` and the rest `passed`. `test_pacing_camera_sentences_classify_as_before` and `test_pacing_panel1_prompt_and_no_slowly` pass unchanged (spec 8.3 B). Then the compile check with `FILES` = `story_engine.py tests/test_dialogue.py tests/test_narrative_fidelity.py`; expected `compiled 3` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_dialogue.py tests/test_narrative_fidelity.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_dialogue.py, qwen-agent-workspace/tests/test_narrative_fidelity.py
git commit -m "feat(story): speaking shots may be medium shots and may track, push in or pull back (SM1-SM3, SM5, NF16, NF17, NF19)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Crowds are setting, not cast; the plan advisories P15, Q2 and Q3 (GC2-GC4, QL12)

Implements GC2, GC3, GC4 and QL12 (`cast_notes`, Q2, Q3 in `plan_checks`). Tests NF22, NF23, NF27, NF36; the `"cast_notes"` half of the spec 8.3 A edit of `test_rst39_outputs_and_layout` (Task 6 adds `"spoken_lines"`).

**Files:**
- Modify: `story_engine.py` (`normalize_plan` `:706-707`; new functions after `speaking_coercion` (Task 4); `plan_checks` `:1024-1026`)
- Modify: `tests/test_story_engine.py` (`test_rst39_outputs_and_layout` `:1758-1760`)
- Modify: `tests/test_narrative_fidelity.py` (append)

**Interfaces:**
- Consumes: `GROUP_NOUNS`, `GROUP_DESCRIPTOR_RE`, `spoken_lines(narrative)` (Task 2); `_q` (existing).
- Produces (in `story_engine`): `is_group_entry(entry) -> bool`; `drop_groups(plan) -> [note]` (removes group entries from `plan["cast"]` and their ids from every beat's `cast`, in place); `plan["cast_notes"]` (a list of P15 strings, after `"loras"`, before `"speech_notes"`). `plan_checks` reads `plan.get("cast_notes", [])`. In the tests: `_reply(case, name="plan_reply_1.txt") -> dict`, `P15_2X145`.

- [ ] **Step 1: Write the failing tests and the spec 8.3 A edit.**

New tests in this task: `test_nf22_is_group_entry`, `test_nf23_normalization_drops_the_crowd`, `test_nf27_q2_no_narration_drops_the_spoken_lines`, `test_nf36_q3_an_odd_quote_count`.

**1.1.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    assert list(plan) == ["schema", "story_id", "mode", "panels", "seconds", "narrative", "goal",
                          "seed_image", "video_model", "auto_lora", "title", "logline", "cast",
                          "locations", "props", "beats", "loras", "speech_notes"]
```

with:

```python
    assert list(plan) == ["schema", "story_id", "mode", "panels", "seconds", "narrative", "goal",
                          "seed_image", "video_model", "auto_lora", "title", "logline", "cast",
                          "locations", "props", "beats", "loras", "cast_notes", "speech_notes"]
```

**1.2.** Append to `tests/test_narrative_fidelity.py`:

```python
# --- NF22, NF23, NF27, NF36: groups are setting; the plan advisories P15, Q2, Q3 (GC, QL12) -------

P15_2X145 = ("plan: P15 group cast: c2 'the cheering crowd' is a group of people, not a "
             "character, so it is removed from the cast and from beat 2; describe it in the "
             "setting sentence instead")


def _reply(case, name="plan_reply_1.txt"):
    """The parsed JSON of a fixture plan reply."""
    with open(os.path.join(FIXTURES, case, name), encoding="utf-8") as f:
        return se.extract_json(f.read())


def _entry(phrase, descriptor="a man in a red jersey with short dark hair", cast_name=None):
    return {"id": "c2", "phrase": phrase, "descriptor": descriptor, "cast_name": cast_name}


def test_nf22_is_group_entry():
    for phrase in ("the cheering crowd", "the fans'", "the hockey team", "the people",
                   "the spectators", "the fans’"):
        assert se.is_group_entry(_entry(phrase)), phrase
    for phrase in ("the team captain", "the crowd's leader", "the crowd’s leader", PLAYER):
        assert not se.is_group_entry(_entry(phrase)), phrase
    assert se.is_group_entry(_entry("the onlookers", "a dense group of spectators in the stands"))
    assert se.is_group_entry(_entry("the hecklers", "a dense group of hecklers in the stands"))
    assert se.is_group_entry(_entry("the hecklers", "A row of hecklers in winter coats"))
    assert not se.is_group_entry(_entry("the hiker", "a man with a group of friends"))
    assert not se.is_group_entry(_entry("the crowd", cast_name="crowd"))


def test_nf23_normalization_drops_the_crowd(ws):
    ctx = _hockey_ctx(ws, "hockey-2x145")
    plan, shape = se.normalize_plan(ctx, _reply("hockey-2x145"))
    assert shape == []
    assert [c["id"] for c in plan["cast"]] == ["c1"]
    assert plan["cast_notes"] == [P15_2X145]
    assert plan["beats"][1]["cast"] == ["c1"]
    advisory = se.plan_checks(ctx, plan, shape)[1]
    assert P15_2X145 in advisory and not [m for m in advisory if " P12 " in m]
    raw = _reply("hockey-2x145")
    raw["beats"][1]["speaker"] = "c9"
    plan, shape = se.normalize_plan(ctx, raw)
    not_cast = "beat 2: P14 speaking beat: speaker 'c9' is not a cast id, so nobody speaks in this beat"
    assert plan["speech_notes"] == [not_cast]
    assert se.plan_checks(ctx, plan, shape)[1][-2:] == [P15_2X145, not_cast]
    assert list(plan)[-2:] == ["cast_notes", "speech_notes"]
    many = {"cast": [_entry(PLAYER, cast_name=None), _entry("the fans", "a sea of fans")],
            "beats": [{"cast": ["c1", "c2"]}, {"cast": ["c2", "c2"]}, {"cast": ["c1"]}]}
    many["cast"][0]["id"] = "c1"
    assert se.drop_groups(many) == [
        "plan: P15 group cast: c2 'the fans' is a group of people, not a character, so it is "
        "removed from the cast and from beats 1, 2; describe it in the setting sentence instead"]
    assert [b["cast"] for b in many["beats"]] == [["c1"], [], ["c1"]]
    alone = {"cast": [_entry("the audience")], "beats": [{"cast": []}]}
    assert se.drop_groups(alone) == [
        "plan: P15 group cast: c2 'the audience' is a group of people, not a character, so it is "
        "removed from the cast; describe it in the setting sentence instead"]
    assert alone["cast"] == []


Q2_HOCKEY = ("plan: Q2 spoken lines: the narrative quotes 2 spoken line(s), but --no-narration "
             "makes this movie silent, so none of them is spoken")


def test_nf27_q2_no_narration_drops_the_spoken_lines(ws):
    for narration, expected in ((False, [Q2_HOCKEY]), ("speech", []), (True, [])):
        ctx = _hockey_ctx(ws, "hockey-2x145", narration=narration)
        plan, shape = se.normalize_plan(ctx, seu.plan_json("chained", 2))
        hard, advisory = se.plan_checks(ctx, plan, shape)
        assert [m for m in advisory if " Q2 " in m] == expected, narration
        assert not [m for m in hard if " Q2 " in m]


def test_nf36_q3_an_odd_quote_count(ws):
    q3 = ("plan: Q3 quotes: the narrative has an odd number of double quotes (1), so its last "
          "quote is unmatched and ignored; close every quoted line")
    for narration in (True, "speech", False):
        ctx = seu.make_ctx(se, ws, narrative='He says "Go.', narration=narration)
        plan, shape = se.normalize_plan(ctx, seu.plan_json("chained", 3))
        assert [m for m in se.plan_checks(ctx, plan, shape)[1] if " Q3 " in m] == [q3], narration
        ctx = _hockey_ctx(ws, "hockey-2x145", narration=narration)
        plan, shape = se.normalize_plan(ctx, seu.plan_json("chained", 2))
        assert not [m for m in se.plan_checks(ctx, plan, shape)[1] if " Q3 " in m], narration
    ctx = seu.make_ctx(se, ws, narrative="He says “Go.” Then “Stop.")
    plan, shape = se.normalize_plan(ctx, seu.plan_json("chained", 3))
    assert [m for m in se.plan_checks(ctx, plan, shape)[1] if " Q3 " in m] == [
        q3.replace("(1)", "(3)")]
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py tests/test_story_engine.py -k "nf22 or nf23 or nf27 or nf36 or rst39" 2>&1 | tail -7
```

Expected: `5 failed`: NF22 and NF23 (`AttributeError`: `is_group_entry`, and normalization keeps `c2`), NF27 and NF36 (no Q2 or Q3 advisory) and `test_rst39_outputs_and_layout` (no `cast_notes` key).

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    plan["speech_notes"] = coerce_speakers(ctx, plan)
    return plan, shape
```

with:

```python
    plan["cast_notes"] = drop_groups(plan)
    plan["speech_notes"] = coerce_speakers(ctx, plan)
    return plan, shape
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
            beat["camera"] = "static"
    return notes


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")   # character_lib._SENTENCE_SPLIT_RE
```

with:

```python
            beat["camera"] = "static"
    return notes


def is_group_entry(entry):
    """True when a plan cast entry is a group of people, not a character (narrative dialogue
    fidelity spec GC2): it is not a library character, and the head word of its phrase (the last
    word, lowercased, without a trailing 's or ') is a GROUP_NOUNS word, or its descriptor
    starts like "a group of" (GROUP_DESCRIPTOR_RE)."""
    if entry.get("cast_name") is not None:
        return False
    words = (entry.get("phrase") or "").split()
    head = words[-1].lower() if words else ""
    for tail in ("'s", "’s", "'", "’"):
        if head.endswith(tail):
            head = head[:-len(tail)]
            break
    return head in GROUP_NOUNS or bool(GROUP_DESCRIPTOR_RE.match(entry.get("descriptor") or ""))


def drop_groups(plan):
    """The P15 notes of GC3, in cast order: every group entry is removed from plan["cast"], and
    each removed id that no kept entry also uses is removed from every beat's cast (order kept)."""
    groups = [entry for entry in plan["cast"] if is_group_entry(entry)]
    if not groups:
        return []
    plan["cast"] = [entry for entry in plan["cast"] if not is_group_entry(entry)]
    gone = set(entry["id"] for entry in groups) - set(entry["id"] for entry in plan["cast"])
    listed = {}
    for k, beat in enumerate(plan["beats"], start=1):
        for cid in beat["cast"]:
            if cid in gone and k not in listed.setdefault(cid, []):
                listed[cid].append(k)
        beat["cast"] = [cid for cid in beat["cast"] if cid not in gone]
    notes = []
    for entry in groups:
        beats = listed.get(entry["id"], [])
        where = ("" if not beats else " and from beat%s %s"
                 % ("s" if len(beats) > 1 else "", ", ".join(str(k) for k in beats)))
        notes.append("plan: P15 group cast: %s %s is a group of people, not a character, so it is "
                     "removed from the cast%s; describe it in the setting sentence instead"
                     % (entry["id"], _q(entry["phrase"]), where))
    return notes


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")   # character_lib._SENTENCE_SPLIT_RE
```

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
                advisory.append(undeclared_message("plan: P13 undeclared character:", where, hit))
    advisory += plan["speech_notes"]
    return hard, advisory
```

with:

```python
                advisory.append(undeclared_message("plan: P13 undeclared character:", where, hit))
    advisory += plan.get("cast_notes", [])
    if ctx.narration is False:
        silent = spoken_lines(ctx.narrative)
        if silent:
            advisory.append("plan: Q2 spoken lines: the narrative quotes %d spoken line(s), but "
                            "--no-narration makes this movie silent, so none of them is spoken"
                            % len(silent))
    quotes = ctx.narrative.replace("“", '"').replace("”", '"').count('"')
    if quotes % 2:
        advisory.append("plan: Q3 quotes: the narrative has an odd number of double quotes (%d), "
                        "so its last quote is unmatched and ignored; close every quoted line"
                        % quotes)
    advisory += plan["speech_notes"]
    return hard, advisory
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py tests/test_dialogue.py tests/test_story_engine.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_judge_story.py 2>&1 | tail -1
```

Expected: `1 failed` (`test_rst62_import_sets`), `1 skipped` and the rest `passed`. Then the compile check with `FILES` = `story_engine.py tests/test_story_engine.py tests/test_narrative_fidelity.py`; expected `compiled 3` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_story_engine.py tests/test_narrative_fidelity.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_narrative_fidelity.py, qwen-agent-workspace/tests/test_story_engine.py
git commit -m "feat(story): a crowd is setting, not cast (P15); Q2 and Q3 advisories (GC2-GC4, QL12, NF22, NF23, NF27, NF36)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Lines in the plan: normalization, coercion, the retry gate and the plan.json defaults (QL7, QL8, 2.1)

Implements QL7 (`_clean_lines`, beat `"lines"`, `plan["spoken_lines"]`, the `coerce_speakers` rewrite, `_nums`), QL8 (`line_assignment_problems` and the `plan_round` gate) and the 2.1 `load_plan` defaults. Tests NF13, NF14, NF26 and Review Focus 3; the spec 8.3 A edits of `test_rst13_normalization` and the `"spoken_lines"` half of `test_rst39_outputs_and_layout`.

**Files:**
- Modify: `story_engine.py` (`_empty_loras` `:610-611`; the beats of `normalize_plan` `:691`; the end of `normalize_plan` (Task 5); `coerce_speakers` (Task 4); `_q` `:763-764`; `plan_round` `:2508-2509`; `load_plan` `:2829-2831`)
- Modify: `tests/test_story_engine.py` (`test_rst13_normalization` `:307`; `test_rst39_outputs_and_layout` (Task 5))
- Modify: `tests/test_narrative_fidelity.py` (append)

**Interfaces:**
- Consumes: `required_lines(ctx)` (Task 2); `speaking_coercion(ctx, plan, k)` (Task 4); `drop_groups(plan)` (Task 5); `line_problem(ctx, lib, line)`, `_character_lib(ws)` (existing).
- Produces (in `story_engine`): every normalized beat has `"lines"` (a list of 1-based spoken-line numbers, ascending, after `"speaker"`); `plan["spoken_lines"]` (after `"loras"`, before `"cast_notes"`); `_clean_lines(value) -> [int]`; `_nums(numbers) -> str` (`"1, 2"`); `speaker_phrase_of(plan, cid) -> str`; `coerce_speakers(ctx, plan, groups=())` (groups: the entries `drop_groups` removed; the P15 group-speaker note of Spec amendment 1); `line_assignment_problems(plan) -> [str]` (the plan-scope Q1 retry messages); `load_plan` defaults `lines`, `spoken_lines` and `cast_notes`. In the tests: `_lines_plan(ws, narrative, beats, n=3, **ctx_kw) -> (ctx, plan)`, `_fixture_text(case, name) -> str`.

- [ ] **Step 1: Write the failing tests and the spec 8.3 A edits.**

New tests in this task: `test_nf13_coerce_speakers_with_lines`, `test_nf14_the_plan_retry_gate`, `test_nf26_an_older_plan_json_loads`, `test_review_focus_3_the_planner_gives_a_line_to_the_crowd`.

**1.1.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
    assert list(plan)[-1] == "speech_notes" and list(plan["beats"][0])[-1] == "speaker"
```

with:

```python
    assert list(plan)[-1] == "speech_notes" and list(plan["beats"][0])[-1] == "lines"
```

**1.2.** Edit `tests/test_story_engine.py`: replace this text, which occurs exactly once:

```python
                          "locations", "props", "beats", "loras", "cast_notes", "speech_notes"]
```

with:

```python
                          "locations", "props", "beats", "loras", "spoken_lines", "cast_notes",
                          "speech_notes"]
```

**1.3.** Append to `tests/test_narrative_fidelity.py`:

```python
# --- NF13, NF14, NF26, Review Focus 3: lines in the plan (QL7, QL8, 2.1) ---------------------------

def _lines_plan(ws, narrative, beats, n=3, **ctx_kw):
    """(ctx, normalized plan) of seu.plan_json("chained", n) under narrative; beats maps a beat
    number to the fields that replace that beat's."""
    ctx = seu.make_ctx(se, ws, panels=n, narrative=narrative, **ctx_kw)
    raw = seu.plan_json("chained", n)
    for k, fields in beats.items():
        raw["beats"][k - 1].update(fields)
    return ctx, se.normalize_plan(ctx, raw)[0]


def _fixture_text(case, name):
    with open(os.path.join(FIXTURES, case, name), encoding="utf-8") as f:
        return f.read()


COURIER_SPOKEN = ["Keep moving.", "The gate is close.", "We made it."]


def test_nf13_coerce_speakers_with_lines(ws):
    every = dict((k, {"speaker": "c1", "lines": [k]}) for k in (1, 2, 3))
    _ctx, plan = _lines_plan(ws, COURIER_LINES, every)
    assert plan["spoken_lines"] == COURIER_SPOKEN
    assert [(b["speaker"], b["lines"]) for b in plan["beats"]] == [("c1", [1]), ("c1", [2]),
                                                                    ("c1", [3])]
    assert plan["speech_notes"] == [] and se.line_assignment_problems(plan) == []
    _ctx, plan = _lines_plan(ws, COURIER_LINES, {1: {"speaker": "c1", "lines": [2, 1]},
                                                 2: {"speaker": "c1", "lines": [2]},
                                                 3: {"speaker": "c1", "lines": [4]}})
    assert [(b["speaker"], b["lines"]) for b in plan["beats"]] == [("c1", [1, 2]), ("c1", []),
                                                                    ("c1", [])]
    assert plan["speech_notes"] == [
        "beat 2: P14 speaking beat: line 2 dropped: an earlier beat already speaks line 2 or a "
        "later one",
        "beat 3: P14 speaking beat: line 4 dropped: the narrative has no spoken line 4"]
    assert se.line_assignment_problems(plan) == [
        'plan: Q1 spoken line: spoken line 3 "We made it." is in no beat\'s lines; put 3 in the '
        "lines of the beat whose action surrounds it in the narrative, and give that beat a "
        "speaker"]
    _ctx, plan = _lines_plan(ws, COURIER_LINES, {1: {"lines": [1]}})
    assert (plan["beats"][0]["speaker"], plan["beats"][0]["lines"]) == ("c1", [1])
    assert plan["speech_notes"] == [
        "beat 1: P14 speaking beat: speaker set to 'c1', the only character in the beat, to say "
        "line(s) 1"]
    _ctx, plan = _lines_plan(ws, COURIER_LINES, {1: {"cast": ["c1", "c2"], "lines": [1, 2]}})
    assert (plan["beats"][0]["speaker"], plan["beats"][0]["lines"]) == ("", [])
    assert plan["speech_notes"] == [
        "beat 1: P14 speaking beat: line(s) 1, 2 dropped: the beat has no speaker"]
    seven = ('The courier says "Keep moving along the wet harbour road." Then he says "The temple '
             'gate is close to us."')
    _ctx, plan = _lines_plan(ws, seven, {1: {"speaker": "c1", "lines": [1, 2]}})
    assert plan["beats"][0]["lines"] == [1]
    assert plan["speech_notes"] == [
        "beat 1: P14 speaking beat: line 2 dropped: together with the beat's other lines it does "
        "not fit a 6-second clip"]
    _ctx, plan = _lines_plan(ws, seu.make_ctx(se, ws).narrative, every)
    assert [(b["speaker"], b["lines"]) for b in plan["beats"]] == [("c1", [])] * 3
    assert plan["speech_notes"] == [] and plan["spoken_lines"] == []
    _ctx, plan = _lines_plan(ws, COURIER_LINES, every, narration=False)
    assert [(b["speaker"], b["lines"]) for b in plan["beats"]] == [("", [])] * 3
    assert plan["spoken_lines"] == []
    assert se._clean_lines("1") == [] and se._clean_lines(["2", True, 1.0, 3]) == [2, 3]
    assert se._clean_lines(None) == [] and se._clean_lines([" 4 ", "x", -1, "²"]) == [4, -1]
    assert se._nums([1, 2, 3]) == "1, 2, 3"


def test_nf14_the_plan_retry_gate(ws, tmp_path, monkeypatch):
    recorded = seu.answer(_fixture_text("hockey-2x145", "plan_reply_1.txt"))
    fixed = seu.answer(_fixture_text("hockey-2x145", "plan_reply_fixed.json"))
    ctx = _hockey_ctx(ws, "hockey-2x145")
    log = seu.script_agent(monkeypatch, tmp_path, plan=[recorded, fixed])
    found, why = se._Run(ctx, "").plan_round()
    calls = seu.agent_log(log)
    assert why is None and [c["stage"] for c in calls] == ["plan", "plan"]
    retry = calls[1]["argv"][calls[1]["argv"].index("--user-prompt") + 1]
    assert ('- plan: Q1 spoken line: spoken line 1 "%s" is in no beat\'s lines; put 1 in the '
            "lines of the beat whose action surrounds it in the narrative, and give that beat a "
            "speaker\n" % LINE1) in retry
    assert '- plan: Q1 spoken line: spoken line 2 "%s"' % LINE2 in retry
    assert [b["lines"] for b in found[0]["beats"]] == [[1], [2]] and found[2] == []
    log = seu.script_agent(monkeypatch, tmp_path, plan=[fixed])
    found, why = se._Run(ctx, "").plan_round()
    assert len(seu.agent_log(log)) == 1 and [b["lines"] for b in found[0]["beats"]] == [[1], [2]]


def test_nf26_an_older_plan_json_loads(ws):
    ctx = _hockey_ctx(ws, "hockey-2x145")
    plan, _shape = se.normalize_plan(ctx, _reply("hockey-2x145", "plan_reply_fixed.json"))
    del plan["spoken_lines"], plan["cast_notes"]
    for beat in plan["beats"]:
        del beat["lines"]
    with open(os.path.join(ctx.story_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f)
    loaded = se.load_plan(ctx)
    assert [b["lines"] for b in loaded["beats"]] == [[], []]
    assert (loaded["spoken_lines"], loaded["cast_notes"]) == ([], [])


def test_review_focus_3_the_planner_gives_a_line_to_the_crowd(ws):
    # The planner makes the crowd (a group, dropped by P15) the speaker of the beat that holds
    # line 2. Expected: the line stays on that beat, spoken by its one remaining character, and
    # one P15 note says so (controller ruling, plan Spec amendment 1); with no individual left,
    # the note says the beat has no speaker.
    raw = _reply("hockey-2x145", "plan_reply_fixed.json")
    raw["beats"][1]["speaker"] = "c2"
    plan, _shape = se.normalize_plan(_hockey_ctx(ws, "hockey-2x145"), raw)
    assert plan["cast_notes"] == [P15_2X145]
    beat = plan["beats"][1]
    assert (beat["speaker"], beat["lines"], beat["cast"]) == ("c1", [2], ["c1"])
    assert plan["speech_notes"] == [
        "beat 2: P15 group cast: the cheering crowd is part of the setting, not a speaker; the "
        "beat's line goes to the FuboTV player"]
    assert se.line_assignment_problems(plan) == []
    no_speaker = ("beat 2: P15 group cast: the cheering crowd is part of the setting, not a "
                  "speaker; the beat has no speaker")
    for speaker in ("c2", "The Cheering Crowd"):
        raw = _reply("hockey-2x145")
        raw["beats"][1]["speaker"] = speaker
        plan, _shape = se.normalize_plan(_hockey_ctx(ws, "hockey-2x145"), raw)
        assert (plan["beats"][1]["speaker"], plan["speech_notes"]) == ("", [no_speaker]), speaker
    raw = seu.plan_json("chained", 3)
    raw["cast"].append({"id": "c3", "phrase": "the harbour crowd",
                        "descriptor": "a crowd of fishermen in yellow oilskins"})
    raw["beats"][0].update(cast=["c1", "c2", "c3"], speaker="c3", lines=[1])
    plan, _shape = se.normalize_plan(seu.make_ctx(se, ws, narrative=COURIER_LINES), raw)
    assert (plan["beats"][0]["speaker"], plan["beats"][0]["lines"]) == ("", [])
    assert plan["speech_notes"] == [
        "beat 1: P15 group cast: the harbour crowd is part of the setting, not a speaker; the beat "
        "has no speaker",
        "beat 1: P14 speaking beat: line(s) 1 dropped: the beat has no speaker"]
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py tests/test_story_engine.py -k "nf13 or nf14 or nf26 or review_focus_3 or rst13 or rst39" 2>&1 | tail -8
```

Expected: `6 failed`: NF13 (`KeyError: 'spoken_lines'`), NF14 (one plan call, no retry), NF26 (`KeyError: 'spoken_lines'` on the `del`), Review Focus 3 (`KeyError: 'lines'`), `test_rst13_normalization` and `test_rst39_outputs_and_layout` (the key orders).

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def _empty_loras():
    return {"global": [], "per_beat": {}, "stills": []}
```

with:

```python
def _empty_loras():
    return {"global": [], "per_beat": {}, "stills": []}


def _clean_lines(value):
    """A beat reply's "lines" (narrative dialogue fidelity spec QL7): its integers (not bools) and
    digit strings, as ints, in order; [] when it is not a list. Anything else is dropped,
    including a digit string int() cannot read (such as "²")."""
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, int) and not isinstance(item, bool):
            out.append(item)
        elif isinstance(item, str) and item.strip().isdigit():
            try:
                out.append(int(item))
            except ValueError:
                continue
    return out
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
            "speaker": _clean_str(item.get("speaker"))})
```

with:

```python
            "speaker": _clean_str(item.get("speaker")),
            "lines": _clean_lines(item.get("lines"))})
```

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    plan["cast_notes"] = drop_groups(plan)
    plan["speech_notes"] = coerce_speakers(ctx, plan)
```

with:

```python
    plan["spoken_lines"] = required_lines(ctx)
    groups = [entry for entry in plan["cast"] if is_group_entry(entry)]
    plan["cast_notes"] = drop_groups(plan)
    plan["speech_notes"] = coerce_speakers(ctx, plan, groups)
```

**3.4.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def coerce_speakers(ctx, plan):
    """The P14 notes of the speaking-beat coercion (dialogue spec SP2), in beat order. Every beat
    gets a "speaker": a cast id or "". A speaker the movie cannot have (--no-narration) or that is
    not a plan cast id is dropped. A kept speaker gets speaking_coercion. No other beat is ever
    changed."""
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
        for entry in plan["cast"]:
            if (raw not in cast_ids and entry.get("phrase")
                    and raw.strip().lower() == entry["phrase"].strip().lower()):
                raw = entry["id"]
        if raw not in cast_ids:
            notes.append("beat %d: P14 speaking beat: speaker %s is not a cast id, so nobody speaks "
                         "in this beat" % (k, _q(raw)))
            continue
        beat["speaker"] = raw
        notes += speaking_coercion(ctx, plan, k)
    return notes
```

with:

```python
def coerce_speakers(ctx, plan, groups=()):
    """The P14 notes of the speaking-beat coercion (dialogue spec SP2; narrative dialogue fidelity
    spec QL7), in beat order. Every beat gets a "speaker" (a cast id or "") and "lines" (the
    numbers of the narrative's spoken lines the beat says, ascending). A speaker the movie cannot
    have (--no-narration) or that is not a plan cast id is dropped. A line number is dropped when
    the narrative has no such line, when an earlier beat already says it or a later one, when the
    beat has no speaker and no sole cast member to become the speaker, or (the last line first)
    while the beat's lines together do not fit the clip. A beat that keeps a speaker gets
    speaking_coercion. No other beat is ever changed. groups are the cast entries drop_groups
    removed: a speaker that names one (by id or phrase) gets the P15 note of the controller
    ruling (plan Spec amendment 1) in place of the "not a cast id" and "speaker set to" notes."""
    notes = []
    cast_ids = [c["id"] for c in plan["cast"]]
    spoken = plan["spoken_lines"]
    lib = _character_lib(ctx.ws) if spoken else None
    last = 0
    for k, beat in enumerate(plan["beats"], start=1):
        raw, raw_lines = beat["speaker"], beat["lines"]
        beat["speaker"], beat["lines"] = "", []
        if ctx.narration is False:
            if raw:
                notes.append("beat %d: P14 speaking beat: speaker %s dropped: this movie has no "
                             "spoken lines" % (k, _q(raw)))
            continue
        sid, group, at = "", None, len(notes)
        if raw:
            for entry in plan["cast"]:
                if (raw not in cast_ids and entry.get("phrase")
                        and raw.strip().lower() == entry["phrase"].strip().lower()):
                    raw = entry["id"]
            if raw in cast_ids:
                sid = raw
            else:
                group = next((entry["phrase"] for entry in groups
                              if raw == entry["id"] or raw.strip().lower()
                              == (entry.get("phrase") or "").strip().lower()), None)
                if group is None:
                    notes.append("beat %d: P14 speaking beat: speaker %s is not a cast id, so "
                                 "nobody speaks in this beat" % (k, _q(raw)))
        if spoken:
            lines = []
            for n in sorted(set(raw_lines)):
                if not 1 <= n <= len(spoken):
                    notes.append("beat %d: P14 speaking beat: line %d dropped: the narrative has "
                                 "no spoken line %d" % (k, n, n))
                elif n <= last:
                    notes.append("beat %d: P14 speaking beat: line %d dropped: an earlier beat "
                                 "already speaks line %d or a later one" % (k, n, last))
                else:
                    lines.append(n)
            if lines and not sid:
                if len(beat["cast"]) == 1 and beat["cast"][0] in cast_ids:
                    sid = beat["cast"][0]
                    if group is None:
                        notes.append("beat %d: P14 speaking beat: speaker set to %s, the only "
                                     "character in the beat, to say line(s) %s"
                                     % (k, _q(sid), _nums(lines)))
                else:
                    notes.append("beat %d: P14 speaking beat: line(s) %s dropped: the beat has no "
                                 "speaker" % (k, _nums(lines)))
                    lines = []
            while lines and line_problem(ctx, lib, " ".join(spoken[n - 1] for n in lines)):
                n = lines.pop()
                notes.append("beat %d: P14 speaking beat: line %d dropped: together with the "
                             "beat's other lines it does not fit a %s-second clip"
                             % (k, n, ctx.seconds))
            beat["lines"] = lines
            if lines:
                last = lines[-1]
        if group is not None:
            notes.insert(at, "beat %d: P15 group cast: %s is part of the setting, not a speaker; %s"
                         % (k, group, "the beat's line goes to %s" % speaker_phrase_of(plan, sid)
                            if sid else "the beat has no speaker"))
        if not sid:
            continue
        beat["speaker"] = sid
        notes += speaking_coercion(ctx, plan, k)
    return notes


def line_assignment_problems(plan):
    """The plan-scope Q1 messages (QL8): one for each of the narrative's spoken lines that no
    beat's lines hold. They make the plan call retry; they never enter a state."""
    held = set(n for beat in plan["beats"] for n in beat.get("lines", []))
    return ["plan: Q1 spoken line: spoken line %d \"%s\" is in no beat's lines; put %d in the "
            "lines of the beat whose action surrounds it in the narrative, and give that beat a "
            "speaker" % (n, line, n)
            for n, line in enumerate(plan.get("spoken_lines", []), start=1) if n not in held]
```

**3.5.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def _q(text):
    return "'%s'" % text
```

with:

```python
def _q(text):
    return "'%s'" % text


def _nums(numbers):
    """Spoken-line numbers as "1, 2" (QL7)."""
    return ", ".join(str(n) for n in numbers)


def speaker_phrase_of(plan, cid):
    """The referring phrase of plan cast id cid (plan Spec amendment 1)."""
    return next(c["phrase"] for c in plan["cast"] if c["id"] == cid)
```

**3.6.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
                found = (plan, shape, hard)
                problems = hard
```

with:

```python
                found = (plan, shape, hard)
                problems = hard + line_assignment_problems(plan)
```

**3.7.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        if isinstance(beat, dict):
            beat.setdefault("speaker", "")
    plan.setdefault("speech_notes", [])
```

with:

```python
        if isinstance(beat, dict):
            beat.setdefault("speaker", "")
            beat.setdefault("lines", [])
    plan.setdefault("spoken_lines", [])
    plan.setdefault("cast_notes", [])
    plan.setdefault("speech_notes", [])
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py tests/test_dialogue.py tests/test_story_engine.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_judge_story.py 2>&1 | tail -1
```

Expected: `1 failed` (`test_rst62_import_sets`), `1 skipped` and the rest `passed`; `test_dlg11`, `test_dlg33`, `test_ff5_speaker_given_as_phrase` and the `_speaker_plan`/`_over_cap` users of `tests/test_story_engine.py` pass (spec 8.3 B). Then the compile check with `FILES` = `story_engine.py tests/test_story_engine.py tests/test_narrative_fidelity.py`; expected `compiled 3` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_story_engine.py tests/test_narrative_fidelity.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_narrative_fidelity.py, qwen-agent-workspace/tests/test_story_engine.py
git commit -m "feat(story): beats carry the narrative's spoken-line numbers; an unassigned line retries the plan (QL7, QL8, NF13, NF14, NF26)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The plan prompt: the spoken-lines block, the `lines` key, `LINES_RULE`, crowds as setting (QL6, 7.1)

Implements QL6 and Section 7.1 (a)-(f) (`spoken_lines_block`, the template, `SPEAKER_RULE`, `LINES_RULE`, `build_plan_prompt`). Tests NF12; the spec 8.3 A edit of `test_dlg12_plan_prompt_speaker_rule`.

**Files:**
- Modify: `story_engine.py` (`PLAN_PROMPT_TEMPLATE` `:289-311`; `SPEAKER_RULE` `:344-349`; after `required_lines` (Task 2); `build_plan_prompt` `:522-523`, `:556-560`)
- Modify: `tests/test_dialogue.py` (`test_dlg12_plan_prompt_speaker_rule` `:650-654`)
- Modify: `tests/test_narrative_fidelity.py` (append)

**Interfaces:**
- Consumes: `SPOKEN_LINES_HEADER`, `required_lines(ctx)` (Task 2); `_fill`, `engine_seconds`, `_character_lib` (existing); `character_lib.dialogue_word_cap(seconds, fragments)`.
- Produces (in `story_engine`): `spoken_lines_block(lines) -> str` (`""` for no lines; Task 11's critic prompt uses it); `SPEAKER_RULE` (7.1 d); `LINES_RULE` (7.1 e, with the scalar token `@@LINE_WORDS@@`); the template tokens `@@BEAT_KEYS@@` and `@@LINES_RULE@@`.

- [ ] **Step 1: Write the failing tests and the spec 8.3 A edit.**

New test in this task: `test_nf12_the_plan_prompt`.

**1.1.** Edit `tests/test_dialogue.py`: replace this text, which occurs exactly once:

```python
    spoken = (" speaker is the id of the one character who says something aloud on screen during "
              "the beat, or an empty string when nobody speaks; give a speaker only where a spoken "
              "line moves the story. A beat with a speaker shows only that character (its cast is "
              "just their id), in a medium close-up or close-up, facing the camera, with the camera "
              "static or a slow push-in.")
```

with:

```python
    spoken = (" speaker is the id of the one character who says something aloud on screen during "
              "the beat, or an empty string when nobody speaks; give a speaker only where a spoken "
              "line moves the story. A beat with a speaker shows only that character (its cast is "
              "just their id), facing the camera, in a medium shot, medium close-up or close-up; "
              "the speaker may move during the beat, and the camera may stay static, push in, pull "
              "back or track them, as long as their face stays in frame and lit while they speak.")
```

**1.2.** Append to `tests/test_narrative_fidelity.py`:

```python
# --- NF12: the plan prompt (QL6, 7.1) -------------------------------------------------------------

CAST_LINE = ("cast: a list with one object per individual character who acts or speaks on screen, "
             "with the keys id, phrase and descriptor; a group of people (a crowd, an audience, "
             "fans, spectators, a team) is never a cast entry, and belongs in the setting sentence "
             "of its place. id is c1, c2, c3 and so on, in order. phrase is the character's "
             "referring phrase:")
SETTING_LINE = ("names the period, the place, the ground, the light and any crowd or other group "
                "of people in the background.\n")
SPEAKER_RULE = (" speaker is the id of the one character who says something aloud on screen "
                "during the beat, or an empty string when nobody speaks; give a speaker only where "
                "a spoken line moves the story. A beat with a speaker shows only that character "
                "(its cast is just their id), facing the camera, in a medium shot, medium close-up "
                "or close-up; the speaker may move during the beat, and the camera may stay static, "
                "push in, pull back or track them, as long as their face stays in frame and lit "
                "while they speak.")
LINES_RULE = (" lines is the list of the numbers of the spoken lines above that the speaker says "
              "aloud during the beat, in order, or an empty list. Every spoken line belongs to "
              "exactly one beat, in the narrative's order: give each line to the beat whose action "
              "surrounds it in the narrative, and give a speaker to every beat with lines and to no "
              "other beat. A beat may hold two or more consecutive lines only when together they "
              "are at most @@LINE_WORDS@@ words. Give each line its own beat whenever there are at "
              "least as many beats as lines.")
SPOKEN_BLOCK = ("\n\nSpoken lines (the narrative quotes these words; the movie must speak every one "
                "of them on camera, word for word, in this order):\n1. \"%s\"\n2. \"%s\""
                % (LINE1, LINE2))


def test_nf12_the_plan_prompt(ws):
    assert (se.SPEAKER_RULE, se.LINES_RULE) == (SPEAKER_RULE, LINES_RULE)
    assert se.spoken_lines_block([LINE1, LINE2]) == SPOKEN_BLOCK
    assert se.spoken_lines_block([]) == ""
    prompt = se.build_plan_prompt(_hockey_ctx(ws, "hockey-2x145"), [], [])
    assert ("Narrative to adapt:\n" + HOCKEY + SPOKEN_BLOCK + "\n\nThe target output goal is "
            ) in prompt
    assert "location, cast, speaker and lines. index runs from 1 to 2." in prompt
    assert ("at most 4." + SPEAKER_RULE + LINES_RULE.replace("@@LINE_WORDS@@", "13") + "\n"
            ) in prompt
    assert CAST_LINE in prompt and SETTING_LINE in prompt and "@@" not in prompt
    one = se.build_plan_prompt(_hockey_ctx(ws, "hockey-1x241"), [], [])
    assert "together they are at most 14 words." in one and "@@" not in one
    quiet = se.build_plan_prompt(seu.make_ctx(se, ws), [], [])
    assert "Spoken lines (" not in quiet and "lines is the list" not in quiet
    assert "location, cast and speaker. index runs" in quiet
    assert ("at most 4." + SPEAKER_RULE + "\n") in quiet
    assert CAST_LINE in quiet and SETTING_LINE in quiet and "@@" not in quiet
    silent = se.build_plan_prompt(_hockey_ctx(ws, "hockey-2x145", narration=False), [], [])
    assert "Spoken lines (" not in silent and "lines is the list" not in silent
    assert "location, cast and speaker. index runs" in silent
    assert ("at most 4." + se.SILENT_SPEAKER_RULE + "\n") in silent
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py tests/test_dialogue.py -k "nf12 or dlg12" 2>&1 | tail -4
```

Expected: `2 failed`: NF12 (`AttributeError: ... no attribute 'LINES_RULE'`) and `test_dlg12_plan_prompt_speaker_rule` (the old `SPEAKER_RULE`).

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "cast: a list with one object per character who is ever on screen, with the keys id, phrase "
    "and descriptor. id is c1, c2, c3 and so on, in order. phrase is the character's referring "
```

with:

```python
    "cast: a list with one object per individual character who acts or speaks on screen, with "
    "the keys id, phrase and descriptor; a group of people (a crowd, an audience, fans, "
    "spectators, a team) is never a cast entry, and belongs in the setting sentence of its "
    "place. id is c1, c2, c3 and so on, in order. phrase is the character's referring "
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "the period, the place, the ground and the light.\n"
```

with:

```python
    "the period, the place, the ground, the light and any crowd or other group of people in the "
    "background.\n"
```

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "arc, action, shot, camera, location, cast and speaker. index runs from 1 to @@PANELS@@. arc "
```

with:

```python
    "arc, action, shot, camera, location, @@BEAT_KEYS@@. index runs from 1 to @@PANELS@@. arc "
```

**3.4.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    "@@MAX_CAST@@.@@SPEAKER_RULE@@\n"
```

with:

```python
    "@@MAX_CAST@@.@@SPEAKER_RULE@@@@LINES_RULE@@\n"
```

**3.5.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
SPEAKER_RULE = (" speaker is the id of the one character who says something aloud on screen "
                "during the beat, or an empty string when nobody speaks; give a speaker only where "
                "a spoken line moves the story. A beat with a speaker shows only that character "
                "(its cast is just their id), in a medium close-up or close-up, facing the camera, "
                "with the camera static or a slow push-in.")
SILENT_SPEAKER_RULE = " speaker is always an empty string: nobody speaks in this movie."
```

with:

```python
SPEAKER_RULE = (" speaker is the id of the one character who says something aloud on screen "
                "during the beat, or an empty string when nobody speaks; give a speaker only where "
                "a spoken line moves the story. A beat with a speaker shows only that character "
                "(its cast is just their id), facing the camera, in a medium shot, medium close-up "
                "or close-up; the speaker may move during the beat, and the camera may stay static, "
                "push in, pull back or track them, as long as their face stays in frame and lit "
                "while they speak.")
SILENT_SPEAKER_RULE = " speaker is always an empty string: nobody speaks in this movie."
# Narrative dialogue fidelity spec 7.1 (e): only when the narrative quotes spoken lines.
LINES_RULE = (" lines is the list of the numbers of the spoken lines above that the speaker says "
              "aloud during the beat, in order, or an empty list. Every spoken line belongs to "
              "exactly one beat, in the narrative's order: give each line to the beat whose action "
              "surrounds it in the narrative, and give a speaker to every beat with lines and to no "
              "other beat. A beat may hold two or more consecutive lines only when together they "
              "are at most @@LINE_WORDS@@ words. Give each line its own beat whenever there are at "
              "least as many beats as lines.")
```

**3.6.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def required_lines(ctx):
    """The spoken lines the movie must speak on camera (QL4): none with --no-narration."""
    return [] if ctx.narration is False else spoken_lines(ctx.narrative)
```

with:

```python
def required_lines(ctx):
    """The spoken lines the movie must speak on camera (QL4): none with --no-narration."""
    return [] if ctx.narration is False else spoken_lines(ctx.narrative)


def spoken_lines_block(lines):
    """The numbered spoken-lines block appended to the narrative in the plan and critic prompts
    (QL6, QL11), or "" when there are no lines."""
    if not lines:
        return ""
    return "\n\n" + SPOKEN_LINES_HEADER + "".join('\n%d. "%s"' % (i, line)
                                                 for i, line in enumerate(lines, start=1))
```

**3.7.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    """The exact plan prompt of RS7."""
    undeclared = undeclared_characters(ctx)
```

with:

```python
    """The exact plan prompt of RS7 (narrative dialogue fidelity spec QL6: the spoken-lines block
    after the narrative, the lines key and LINES_RULE when the narrative quotes spoken lines)."""
    lines = required_lines(ctx)
    undeclared = undeclared_characters(ctx)
```

**3.8.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        ("@@SPEAKER_RULE@@", SILENT_SPEAKER_RULE if ctx.narration is False else SPEAKER_RULE),
    ]
    scalars = [("@@STORY_ID@@", ctx.story_id), ("@@PANELS@@", str(ctx.panels)),
               ("@@SECONDS@@", ctx.seconds), ("@@MAX_CAST@@", str(MAX_CAST[ctx.mode]))]
    return _fill(PLAN_PROMPT_TEMPLATE, fragments, scalars, ctx.narrative)
```

with:

```python
        ("@@SPEAKER_RULE@@", SILENT_SPEAKER_RULE if ctx.narration is False else SPEAKER_RULE),
        ("@@BEAT_KEYS@@", "cast, speaker and lines" if lines else "cast and speaker"),
        ("@@LINES_RULE@@", LINES_RULE if lines else ""),
    ]
    # character_lib is loaded only for a narrative with spoken lines, so an uncast dry run still
    # never loads it (test_rst47, test_s53).
    line_cap = (str(_character_lib(ctx.ws).dialogue_word_cap(engine_seconds(ctx), 2))
                if lines else "")
    scalars = [("@@STORY_ID@@", ctx.story_id), ("@@PANELS@@", str(ctx.panels)),
               ("@@SECONDS@@", ctx.seconds), ("@@MAX_CAST@@", str(MAX_CAST[ctx.mode])),
               ("@@LINE_WORDS@@", line_cap)]
    return _fill(PLAN_PROMPT_TEMPLATE, fragments, scalars,
                 ctx.narrative + spoken_lines_block(lines))
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py tests/test_dialogue.py tests/test_story_engine.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_judge_story.py 2>&1 | tail -1
```

Expected: `1 failed` (`test_rst62_import_sets`), `1 skipped` and the rest `passed`. `test_rst40` (the legacy prompt) passes unchanged (spec 8.3 C), and so do `test_rst47_robust_dry_run` and `test_s53_uncast_shots_dry_run_never_loads_character_lib`, because a quote-free narrative never loads `character_lib` (Plan decision 3). Then the compile check with `FILES` = `story_engine.py tests/test_dialogue.py tests/test_narrative_fidelity.py`; expected `compiled 3` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_dialogue.py tests/test_narrative_fidelity.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_dialogue.py, qwen-agent-workspace/tests/test_narrative_fidelity.py
git commit -m "feat(story): the plan prompt lists the narrative's spoken lines and asks for each beat's lines (QL6, 7.1, NF12)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: The panel writer: the narrative's words are pasted, and the speaker may move (QL9, SM4, 7.2)

Implements QL9 (`assigned_dialogue`, the `dialogue_fixed` key line, `parse_panel_reply`, `empty_parts`, `panel_fields`) and SM4/7.2 (`SPEECH_FRAMING_SENTENCE`, `SPEAKING_ACTION_SENTENCE`, `SPEAKING_IMAGE_SENTENCE`, the `no_stills_prompt_speaking` text). Tests NF15, NF20; the spec 8.3 A edit of `test_dlg13_writer_keys_and_speaking_key_lines`.

**Files:**
- Modify: `story_engine.py` (`SPEECH_FRAMING_SENTENCE` `:36-38`; `KEY_LINE_TEMPLATES` `:1286-1299`; before `panel_keys` `:1338`; `empty_parts` `:1385-1387`; `parse_panel_reply` `:1404-1405`; `panel_fields` `:1449`; `build_panel_prompt` `:1907-1930`)
- Modify: `tests/test_dialogue.py` (`test_dlg13_writer_keys_and_speaking_key_lines` `:742-745`, `:753-754`, `:760-761`)
- Modify: `tests/test_narrative_fidelity.py` (append)

**Interfaces:**
- Consumes: the plan's `spoken_lines` and beat `lines` (Task 6); `speaker_phrase`, `panel_speaks`, `panel_keys`, `_clean_dialogue`, `_sentence` (existing).
- Produces (in `story_engine`): `assigned_dialogue(plan, k) -> str` (the beat's spoken lines joined with spaces, `""` when it has none; Tasks 9, 10 and 12 use it); `KEY_LINE_TEMPLATES["dialogue_fixed"]` (tokens `@@LINE@@`, `@@SPEAKER@@`).

- [ ] **Step 1: Write the failing tests and the spec 8.3 A edit.**

New tests in this task: `test_nf15_the_writer_gets_the_narrative_words`, `test_nf20_the_panel_prompt_constants`.

**1.1.** Edit `tests/test_dialogue.py`: replace this text, which occurs exactly once:

```python
    assert ('already on screen. You may add one camera direction. In this panel "the courier" '
            "speaks the dialogue: keep their movement small -- a breath, a glance, a small hand "
            "gesture -- with the camera holding still, and do not write the spoken words or a "
            "speaking verb here; the pipeline adds them.\n") in prompt
```

with:

```python
    assert ('already on screen. You may add one camera direction. In this panel "the courier" '
            "speaks the dialogue: they may move as the beat says, but write the motion so that "
            "their face is toward the camera, in frame and lit while they speak -- a speaker who "
            "approaches the camera speaks once close -- and do not write the spoken words or a "
            "speaking verb here; the pipeline adds them.\n") in prompt
```

**1.2.** Edit `tests/test_dialogue.py`: replace this text, which occurs exactly once:

```python
    assert ('fills the full 6 seconds with small, continuous movements of "the courier" -- a '
            "breath, a glance, a small hand gesture -- names the ambient") in prompt
```

with:

```python
    assert ('fills the full 6 seconds with the one continuous movement of "the courier" that the '
            "beat describes, keeping their face toward the camera while they speak, names the "
            "ambient") in prompt
```

**1.3.** Edit `tests/test_dialogue.py`: replace this text, which occurs exactly once:

```python
    assert ('Never name a person who is not in this shot. "the courier" is the only person in the '
            "frame, facing the camera.\n") in prompt
```

with:

```python
    assert ('Never name a person who is not in this shot. "the courier" is the only person in the '
            "foreground, facing the camera; any crowd stays in the background.\n") in prompt
```

**1.4.** Append to `tests/test_narrative_fidelity.py`:

```python
# --- NF15, NF20: the panel writer (QL9, SM4, 7.2) ---------------------------------------------------

DIALOGUE_FIXED = ("dialogue: exactly @@LINE@@ -- the narrative's own words, which @@SPEAKER@@ says "
                  "aloud in this panel; copy them unchanged, because the pipeline uses the "
                  "narrative's words whatever this field holds.")
SPEAKING_ACTION = (" In this panel @@SPEAKER@@ speaks the dialogue: they may move as the beat "
                   "says, but write the motion so that their face is toward the camera, in frame "
                   "and lit while they speak -- a speaker who approaches the camera speaks once "
                   "close -- and do not write the spoken words or a speaking verb here; the "
                   "pipeline adds them.")
SPEAKING_IMAGE = (" @@SPEAKER@@ is the only person in the foreground, facing the camera; any crowd "
                  "stays in the background.")
SPEECH_FRAMING = (" Characters speak on screen in this movie: keep each character within medium "
                  "to close-up range of the camera while they speak, and never have a character "
                  "shrink into the distance or leave the frame before their line ends.")


def _panel_reply(case, k):
    """The parsed JSON of a recorded panel reply."""
    return se.extract_json(_fixture_text(case, "panel_%02d_reply_1.txt" % k))


def test_nf15_the_writer_gets_the_narrative_words(ws):
    ctx = _hockey_ctx(ws, "hockey-2x145")
    plan, _shape = se.normalize_plan(ctx, _reply("hockey-2x145", "plan_reply_fixed.json"))
    assert (se.assigned_dialogue(plan, 1), se.assigned_dialogue(plan, 2)) == (LINE1, LINE2)
    parts = [se.empty_parts(ctx.mode, k, plan, ctx) for k in (1, 2)]
    assert [p["dialogue"] for p in parts] == [LINE1, LINE2]
    assert "dialogue" not in se.empty_parts(ctx.mode, 2, plan)
    prompt = se.build_panel_prompt(ctx, plan, parts, 2)
    assert ('\ndialogue: exactly "It\'s just FuboTV." -- the narrative\'s own words, which "the '
            'FuboTV player" says aloud in this panel; copy them unchanged, because the pipeline '
            "uses the narrative's words whatever this field holds.\n") in prompt
    assert "@@" not in prompt and "\ndialogue: the exact words" not in prompt
    assert '\ndialogue: exactly "%s" -- ' % LINE1 in se.build_panel_prompt(ctx, plan, parts, 1)
    reply = _panel_reply("hockey-2x145", 2)
    for written in (dict(reply, dialogue="Something else."), reply):
        assert se.parse_panel_reply(ctx, plan, 2, json.dumps(written))["dialogue"] == LINE2
    parts[1] = dict(se.parse_panel_reply(ctx, plan, 2, json.dumps(reply)), dialogue="Other words.")
    assert dict(se.panel_fields(ctx, plan, parts, 2))["Dialogue"] == PLAYER + ": " + LINE2
    recorded, _shape = se.normalize_plan(ctx, _reply("hockey-2x145"))
    assert se.assigned_dialogue(recorded, 1) == ""
    assert ('\ndialogue: the exact words "the FuboTV player" says aloud in this panel: at most 14 '
            "words") in se.build_panel_prompt(ctx, recorded, parts, 1)
    written = se.parse_panel_reply(ctx, recorded, 1, json.dumps(_panel_reply("hockey-2x145", 1)))
    assert written["dialogue"] == "Getting the best deal on hockey isn't a hat trick."


def test_nf20_the_panel_prompt_constants():
    assert se.KEY_LINE_TEMPLATES["dialogue_fixed"] == DIALOGUE_FIXED
    assert se.SPEAKING_ACTION_SENTENCE == SPEAKING_ACTION
    assert se.SPEAKING_IMAGE_SENTENCE == SPEAKING_IMAGE
    assert se.SPEECH_FRAMING_SENTENCE == SPEECH_FRAMING
    base = se.KEY_LINE_TEMPLATES["no_stills_prompt"]
    assert se.KEY_LINE_TEMPLATES["no_stills_prompt_speaking"] == base.replace(
        "carries enough separate beats to fill the full @@SECONDS@@ seconds, links them with "
        "temporal connectors (initially, as, then, while, a moment later), ",
        "fills the full @@SECONDS@@ seconds with the one continuous movement of @@SPEAKER@@ that "
        "the beat describes, keeping their face toward the camera while they speak, ")
    assert se.KEY_LINE_TEMPLATES["no_stills_prompt_speaking"] != base
    assert se.SPEAKING_SENTENCES == {"image": SPEAKING_IMAGE, "motion": SPEAKING_ACTION,
                                     "prompt": se.SPEAKING_PROMPT_SENTENCE}
    for text in (DIALOGUE_FIXED, SPEAKING_ACTION, SPEAKING_IMAGE, SPEECH_FRAMING,
                 se.KEY_LINE_TEMPLATES["no_stills_prompt_speaking"]):
        assert "slowly" not in text.lower()
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py tests/test_dialogue.py -k "nf15 or nf20 or dlg13" 2>&1 | tail -5
```

Expected: `3 failed`: NF15 (`AttributeError: ... no attribute 'assigned_dialogue'`), NF20 (`KeyError: 'dialogue_fixed'`) and `test_dlg13_writer_keys_and_speaking_key_lines` (the old speaking sentences).

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
SPEECH_FRAMING_SENTENCE = (" Characters speak on screen in this movie: keep each character within "
                          "medium to close-up range of the camera, and never have them shrink "
                          "into the distance or leave the frame.")
```

with:

```python
SPEECH_FRAMING_SENTENCE = (" Characters speak on screen in this movie: keep each character within "
                           "medium to close-up range of the camera while they speak, and never "
                           "have a character shrink into the distance or leave the frame before "
                           "their line ends.")
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
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
```

with:

```python
# Narrative dialogue fidelity spec QL9, 7.2: the dialogue key line of a beat that says the
# narrative's spoken lines (@@LINE@@ is those lines, quoted; the pipeline pastes them itself).
KEY_LINE_TEMPLATES["dialogue_fixed"] = (
    "dialogue: exactly @@LINE@@ -- the narrative's own words, which @@SPEAKER@@ says aloud in "
    "this panel; copy them unchanged, because the pipeline uses the narrative's words whatever "
    "this field holds.")
KEY_LINE_TEMPLATES["no_stills_prompt_speaking"] = KEY_LINE_TEMPLATES["no_stills_prompt"].replace(
    "carries enough separate beats to fill the full @@SECONDS@@ seconds, links them with temporal "
    "connectors (initially, as, then, while, a moment later), ",
    "fills the full @@SECONDS@@ seconds with the one continuous movement of @@SPEAKER@@ that the "
    "beat describes, keeping their face toward the camera while they speak, ")
# Appended to a speaking panel's key lines (dialogue spec 8.2; narrative dialogue fidelity spec
# 7.2); @@SPEAKER@@ is the speaker's quoted referring phrase.
SPEAKING_ACTION_SENTENCE = (" In this panel @@SPEAKER@@ speaks the dialogue: they may move as the "
                            "beat says, but write the motion so that their face is toward the "
                            "camera, in frame and lit while they speak -- a speaker who approaches "
                            "the camera speaks once close -- and do not write the spoken words or "
                            "a speaking verb here; the pipeline adds them.")
SPEAKING_PROMPT_SENTENCE = (" Do not write the spoken words or a speaking verb here; the pipeline "
                            "adds them.")
SPEAKING_IMAGE_SENTENCE = (" @@SPEAKER@@ is the only person in the foreground, facing the camera; "
                           "any crowd stays in the background.")
```

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def panel_keys(ctx, plan, k):
```

with:

```python
def assigned_dialogue(plan, k):
    """The narrative's spoken lines that beat k says, joined by spaces, or "" (narrative dialogue
    fidelity spec QL9): the pasted Dialogue text of a beat with lines, whatever the writer
    replied. A plan without spoken_lines or lines (an older plan.json) gives ""."""
    spoken = plan.get("spoken_lines", [])
    return " ".join(spoken[n - 1] for n in plan["beats"][k - 1].get("lines", [])
                    if 1 <= n <= len(spoken))


def panel_keys(ctx, plan, k):
```

**3.4.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    parts = {key: "" for key in keys}
    parts["title"] = title_fallback(plan["beats"][k - 1]["action"]) or "Panel %d" % k
    return parts
```

with:

```python
    parts = {key: "" for key in keys}
    parts["title"] = title_fallback(plan["beats"][k - 1]["action"]) or "Panel %d" % k
    if ctx is not None and assigned_dialogue(plan, k):
        parts["dialogue"] = assigned_dialogue(plan, k)
    return parts
```

**3.5.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        if key == "dialogue":
            value = _clean_dialogue(lib, value, speaker_phrase(plan, k))
```

with:

```python
        if key == "dialogue":
            value = assigned_dialogue(plan, k) or _clean_dialogue(lib, value,
                                                                  speaker_phrase(plan, k))
```

**3.6.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        line = _sentence(_character_lib(ctx.ws).clean_line(p.get("dialogue", "")))
```

with:

```python
        line = _sentence(assigned_dialogue(plan, k)
                         or _character_lib(ctx.ws).clean_line(p.get("dialogue", "")))
```

**3.7.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    words = str(_character_lib(ctx.ws).dialogue_word_cap(engine_seconds(ctx), 1)) if speaks else ""
    key_lines = []
```

with:

```python
    words = str(_character_lib(ctx.ws).dialogue_word_cap(engine_seconds(ctx), 1)) if speaks else ""
    assigned = assigned_dialogue(plan, k)
    key_lines = []
```

**3.8.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        elif key == "dialogue":
            line = KEY_LINE_TEMPLATES["dialogue"]
```

with:

```python
        elif key == "dialogue":
            line = KEY_LINE_TEMPLATES["dialogue_fixed" if assigned else "dialogue"]
```

**3.9.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
            line = line.replace("@@SPEAKER@@", '"%s"' % phrase).replace("@@DWORDS@@", words)
```

with:

```python
            line = (line.replace("@@SPEAKER@@", '"%s"' % phrase).replace("@@DWORDS@@", words)
                    .replace("@@LINE@@", '"%s"' % assigned))
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py tests/test_dialogue.py tests/test_story_engine.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_judge_story.py 2>&1 | tail -1
```

Expected: `1 failed` (`test_rst62_import_sets`), `1 skipped` and the rest `passed`; `test_dlg14`, `test_review_focus_1`, `test_empty_parts_uses_panel_keys_with_ctx` and `test_pacing_panel1_prompt_and_no_slowly` pass unchanged (spec 8.3 B). Then the compile check with `FILES` = `story_engine.py tests/test_dialogue.py tests/test_narrative_fidelity.py`; expected `compiled 3` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_dialogue.py tests/test_narrative_fidelity.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_dialogue.py, qwen-agent-workspace/tests/test_narrative_fidelity.py
git commit -m "feat(story): paste the narrative's spoken lines into the speaking panel; the speaker may move (QL9, SM4, NF15, NF20)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Q1: every quoted line is in some panel's `Dialogue:`, word for word and in order (QL10, QL14)

Implements QL10 (`Q1_MISSING`, `Q1_ORDER`, `_find_run`, `spoken_line_problems`, `GENERATION_CHECKS`/`RECHECK_IDS`, the `panel_checks` and `recheck` wiring) and QL14. Tests NF7, NF8, NF9, NF10, NF11 and Review Focus 1, 2.

**Files:**
- Modify: `story_engine.py` (`GENERATION_CHECKS` `:1831-1832`; `panel_checks` `:1843-1856`; `RECHECK_IDS` `:2811-2812`; `recheck` `:2933-2935`)
- Modify: `tests/test_narrative_fidelity.py` (append)

**Interfaces:**
- Consumes: `required_lines(ctx)`, `line_words(text)` (Task 2); `assigned_dialogue(plan, k)` (Task 8); `drop_groups` notes (Task 5); `cast_phrases(ctx, plan)`, `panel_fields`, `_Run.make_state(rnd, plan, parts)`, `blocking(messages)`, `recheck(ctx, legacy_validate)` (existing); `character_lib.parse_dialogue(value, phrases) -> (phrase or None, line, problem)`.
- Produces (in `story_engine`): `Q1_MISSING`, `Q1_ORDER` (each `% (line number, line text)`); `_find_run(words, run, start) -> int or None`; `spoken_line_problems(ctx, lib, phrases, dialogues) -> [str]` (hard, blocking `story:` Q1 messages, in line order; Task 12 relies on `repairable_ids` seeing them as story scope); `"Q1"` in `GENERATION_CHECKS` and `RECHECK_IDS`, just before their last id `"N19"` (Plan decision 2). In the tests: `T2_2X145`, `_replay(ws, case, reply_file, assign=False, **ctx_kw) -> (state, plan, notes)`, `_say(line) -> "the FuboTV player: <line>"`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_nf7_spoken_line_problems`, `test_nf8_replay_the_recorded_2x145_plan`, `test_nf9_replay_the_recorded_1x241_plan`, `test_nf10_replay_the_fixed_plans`, `test_nf11_recheck_with_a_plan`, `test_review_focus_1_smart_quotes_in_the_narrative`, `test_review_focus_2_recheck_of_a_story_written_before_this_change`.

**1.1.** Append to `tests/test_narrative_fidelity.py`:

```python
# --- NF7-NF11, Review Focus 1, 2: Q1 (QL10, QL14) ----------------------------------------------------

T2_2X145 = ("panel 2: T2 action amount: Motion: holds 3 actions; a 6-second clip fits at most 2, "
            "so cut the extra actions and keep every other sentence word for word")
Q1_MISSING = ("story: Q1 spoken line: the narrative's spoken line %d \"%s\" is in no panel's "
              "Dialogue:; give it word for word to the panel that shows it being said (Dialogue: "
              "<speaker's referring phrase>: <the line>)")
Q1_ORDER = ("story: Q1 spoken line: the narrative's spoken line %d \"%s\" is spoken out of the "
            "narrative's order; the Dialogue: fields must say the spoken lines in the order the "
            "narrative gives them")
PANEL2_FIXED = ("Motion: The FuboTV player skates forward, then halts in a sharp hockey stop that "
                "sprays ice mist into the air. He holds the pose, then skates away from the camera. "
                "The FuboTV player faces the camera. The camera stays static.\n"
                "Dialogue: the FuboTV player: It's just FuboTV.\n")


def _say(line):
    return PLAYER + ": " + line


def _replay(ws, case, reply_file, assign=False, **ctx_kw):
    """(state, plan, notes) of a recorded run's round 0 replayed through the current checks (spec
    8.1): the plan reply normalized; with assign, assign_missing_lines (QL8b), its notes added to
    speech_notes as _Run.go() adds them; the recorded parts.json panels; every beat with lines
    given its assigned dialogue; then _Run.make_state."""
    ctx = _hockey_ctx(ws, case, **ctx_kw)
    plan, shape = se.normalize_plan(ctx, _reply(case, reply_file))
    notes = se.assign_missing_lines(ctx, plan) if assign else []
    plan["speech_notes"] += notes
    parts = [dict((key, value) for key, value in panel.items() if key != "index")
             for panel in json.loads(_fixture_text(case, "parts.json"))["panels"]]
    for k, beat in enumerate(plan["beats"], start=1):
        if beat["lines"]:
            parts[k - 1]["dialogue"] = se.assigned_dialogue(plan, k)
    runner = se._Run(ctx, "")
    runner.shape = shape
    return runner.make_state(0, plan, parts), plan, notes


def test_nf7_spoken_line_problems(ws):
    assert (se.Q1_MISSING, se.Q1_ORDER) == (Q1_MISSING, Q1_ORDER)
    ctx = _hockey_ctx(ws, "hockey-2x145")

    def q1(*dialogues):
        return se.spoken_line_problems(ctx, character_lib, [PLAYER], list(dialogues))

    assert q1(_say(LINE1), _say(LINE2)) == []
    assert q1(_say(LINE1 + " " + LINE2), "") == []
    assert q1(_say(LINE1), "") == [Q1_MISSING % (2, LINE2)]
    assert q1(_say(LINE2), _say(LINE1)) == [Q1_ORDER % (2, LINE2)]
    assert q1(_say("Getting the best deal on hockey"), _say("isn't a hat trick... " + LINE2)) == [
        Q1_MISSING % (1, LINE1)]
    assert q1(_say("Hey there. " + LINE1 + " Right?"), _say("Yes. " + LINE2 + " Go.")) == []
    assert q1(_say("GETTING the best deal on hockey, isn’t a hat trick"), _say("it's JUST fubotv!")
              ) == []
    assert q1("the stranger: " + LINE1 + " " + LINE2, "") == [Q1_MISSING % (1, LINE1),
                                                              Q1_MISSING % (2, LINE2)]
    assert q1("", "") == [Q1_MISSING % (1, LINE1), Q1_MISSING % (2, LINE2)]
    assert q1() == [Q1_MISSING % (1, LINE1), Q1_MISSING % (2, LINE2)]
    twice = seu.make_ctx(se, ws, narrative='The courier says "Go." Then he says "Go."')
    for dialogues, expected in ((["the courier: Go."], [Q1_ORDER % (2, "Go.")]),
                                (["the courier: Go. Go."], []),
                                (["the courier: Go.", "the courier: Go."], [])):
        assert se.spoken_line_problems(twice, character_lib, ["the courier"], dialogues) == (
            expected), dialogues
    silent = _hockey_ctx(ws, "hockey-2x145", narration=False)
    assert se.spoken_line_problems(silent, character_lib, [PLAYER], []) == []
    assert se._find_run(["a", "b", "a", "b"], ["a", "b"], 1) == 2
    assert se._find_run(["a", "b"], ["b", "a"], 0) is None
    assert se.GENERATION_CHECKS[-2:] == ("Q1", "N19") and se.RECHECK_IDS[-2:] == ("Q1", "N19")
    assert "Q1" not in se.PLAN_FREE_IDS and "Q1" not in se.NON_BLOCKING_IDS
    assert "Q1" not in se.REPAIR_IDS


def test_nf8_replay_the_recorded_2x145_plan(ws):
    state, plan, _notes = _replay(ws, "hockey-2x145", "plan_reply_1.txt")
    q1 = Q1_MISSING % (2, LINE2)
    assert state["hard"] == [T2_2X145, q1]
    assert se.blocking(state["hard"]) == [q1]
    assert se.parse_violation(q1) == {"id": "Q1", "name": "spoken line", "scope": "story",
                                      "index": None, "message": q1}
    assert P15_2X145 in state["advisory"]
    assert not [m for m in state["advisory"] if " P12 " in m]
    assert plan["beats"][1]["cast"] == ["c1"]


def test_nf9_replay_the_recorded_1x241_plan(ws):
    state, _plan, _notes = _replay(ws, "hockey-1x241", "plan_reply_1.txt")
    assert state["hard"] == [Q1_MISSING % (1, LINE1), Q1_MISSING % (2, LINE2)]
    assert se.blocking(state["hard"]) == state["hard"]


def test_nf10_replay_the_fixed_plans(ws):
    state, _plan, _notes = _replay(ws, "hockey-2x145", "plan_reply_fixed.json")
    assert state["hard"] == [T2_2X145] and se.blocking(state["hard"]) == []
    assert "Dialogue: the FuboTV player: " + LINE1 + "\n" in state["text"]
    assert state["text"].endswith(PANEL2_FIXED)
    state, plan, _notes = _replay(ws, "hockey-1x241", "plan_reply_fixed.json")
    assert state["hard"] == [] and plan["speech_notes"] == []
    assert (plan["beats"][0]["shot"], plan["beats"][0]["camera"]) == ("medium shot", "tracking")
    assert ("Motion: The FuboTV player skates forward toward the camera, then stops abruptly in a "
            "hockey stop, spraying ice mist into the air. He then skates away from the camera. The "
            "FuboTV player faces the camera. The camera tracks alongside the movement.\n"
            "Dialogue: the FuboTV player: " + LINE1 + " " + LINE2 + "\n") in state["text"]
    image = [l for l in state["text"].split("\n") if l.startswith("Image: ")]
    assert len(image) == 1
    assert image[0].endswith(" The FuboTV player faces the camera. The shot is a medium shot.")


def _recheck(ctx, capsys, text, check_ctx=None):
    """(rc, captured) of se.recheck on text written as the story's story.md."""
    with open(os.path.join(ctx.story_dir, "story.md"), "w", encoding="utf-8") as f:
        f.write(text)
    capsys.readouterr()
    rc, _advisories = se.recheck(check_ctx or ctx, lambda path, panels, no_stills=False: [])
    return rc, capsys.readouterr()


def test_nf11_recheck_with_a_plan(ws, capsys):
    state, plan, _notes = _replay(ws, "hockey-2x145", "plan_reply_fixed.json")
    ctx = _hockey_ctx(ws, "hockey-2x145")
    se._write_json(os.path.join(ctx.story_dir, "plan.json"), plan)
    rc, out = _recheck(ctx, capsys, state["text"])
    assert rc == 0 and " Q1 " not in out.out + out.err
    cut = state["text"].replace("Dialogue: the FuboTV player: It's just FuboTV.\n", "")
    assert cut != state["text"]
    rc, out = _recheck(ctx, capsys, cut)
    assert rc == 2 and ("  - " + Q1_MISSING % (2, LINE2) + "\n") in out.err
    rc, out = _recheck(ctx, capsys, cut, ctx._replace(narration=False))
    assert " Q1 " not in out.out + out.err


def test_review_focus_1_smart_quotes_in_the_narrative(ws):
    # A narrative typed with smart quotes and a curly apostrophe (macOS text fields). Expected: the
    # required line keeps the author's apostrophe in the plan prompt and in Dialogue:, Q1 passes,
    # and a hand-typed Dialogue: with a straight apostrophe and no full stop also passes.
    narrative = "The courier reaches the gate and says “It’s just a short climb.”"
    line = "It’s just a short climb."
    assert se.spoken_lines(narrative) == [line]
    ctx = seu.make_ctx(se, ws, panels=1, narrative=narrative)
    assert '\n1. "%s"\n' % line in se.build_plan_prompt(ctx, [], [])
    raw = seu.plan_json("chained", 1)
    raw["beats"][0].update(speaker="c1", lines=[1])
    plan, _shape = se.normalize_plan(ctx, raw)
    parts = [se.parse_panel_reply(ctx, plan, 1, json.dumps(seu.panel_json("chained", 1)))]
    text = se.assemble(ctx, plan, parts)
    assert "\nDialogue: the courier: %s\n" % line in text
    path = os.path.join(ctx.story_dir, "check.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    hard, _advisory = se.panel_checks(ctx, plan, parts, text, path)
    assert not [m for m in hard if " Q1 " in m]
    assert se.spoken_line_problems(ctx, character_lib, ["the courier"],
                                   ["the courier: it's just a short climb"]) == []


def test_review_focus_2_recheck_of_a_story_written_before_this_change(ws, capsys):
    # bin/ltx-movie re-checks an existing story.md on every rerun. A story written before this
    # change has a plan.json with the crowd still cast and no lines, spoken_lines or cast_notes.
    # Expected: once its Dialogue: fields hold every quoted line (the QL14 hand edit), the re-check
    # passes with no Q1; without the edit it exits 2 and names the missing line.
    state, plan, _notes = _replay(ws, "hockey-2x145", "plan_reply_1.txt")
    old = copy.deepcopy(plan)
    del old["spoken_lines"], old["cast_notes"]
    old["cast"].append(dict(_reply("hockey-2x145")["cast"][1], cast_name=None))
    old["beats"][1]["cast"] = ["c1", "c2"]
    for beat in old["beats"]:
        del beat["lines"]
    ctx = _hockey_ctx(ws, "hockey-2x145")
    se._write_json(os.path.join(ctx.story_dir, "plan.json"), old)
    rc, out = _recheck(ctx, capsys, state["text"] + "Dialogue: the FuboTV player: It's just "
                                                    "FuboTV.\n")
    assert rc == 0 and " Q1 " not in out.out + out.err
    rc, out = _recheck(ctx, capsys, state["text"])
    assert rc == 2
    assert out.err.startswith("Error: story.md fails the story checks:\n  - "
                              + Q1_MISSING % (2, LINE2) + "\n")
    assert "pass --force-story to regenerate it" in out.err
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py -k "nf7 or nf8 or nf9 or nf10 or nf11 or review_focus_1 or review_focus_2" 2>&1 | tail -9
```

Expected: `6 failed, 1 passed`. NF7 fails with `AttributeError: ... no attribute 'Q1_MISSING'`, Review Focus 1 with `AttributeError: ... no attribute 'spoken_line_problems'`; NF8 and NF9 fail because `state["hard"]` has no Q1, NF11 and Review Focus 2 because the re-check of the cut story.md exits 0. NF10 passes already: it pins the two fixed replays, which have no Q1 to report, and it keeps holding from Step 3 on.

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
GENERATION_CHECKS = ("N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11", "N12",
                     "N14", "N15", "N16", "N17", "N18", "T1", "T2", "T3", "N19")
```

with:

```python
# Narrative dialogue fidelity spec QL10: a quoted spoken line of the narrative is missing from
# every panel's Dialogue:, or is spoken out of order. Hard and blocking; story scope.
Q1_MISSING = ("story: Q1 spoken line: the narrative's spoken line %d \"%s\" is in no panel's "
              "Dialogue:; give it word for word to the panel that shows it being said (Dialogue: "
              "<speaker's referring phrase>: <the line>)")
Q1_ORDER = ("story: Q1 spoken line: the narrative's spoken line %d \"%s\" is spoken out of the "
            "narrative's order; the Dialogue: fields must say the spoken lines in the order the "
            "narrative gives them")


def _find_run(words, run, start):
    """The first j >= start with words[j:j + len(run)] == run, else None."""
    for j in range(start, len(words) - len(run) + 1):
        if words[j:j + len(run)] == run:
            return j
    return None


def spoken_line_problems(ctx, lib, phrases, dialogues):
    """The Q1 violations of a story (QL10), in line order. dialogues is one Dialogue: value per
    panel, in order ("" for none); a value that names no known phrase counts as empty. Each
    required line must lie, word for word (line_words: case and punctuation ignored), inside one
    panel's line, later than the line before it; a line found only earlier is out of order."""
    required = required_lines(ctx)
    if not required:
        return []
    found = []
    for value in dialogues:
        phrase, line = (lib.parse_dialogue(value, phrases)[:2] if value.strip()
                        else (None, ""))
        found.append(line_words(line) if phrase else [])
    kpos, jpos, out = 0, 0, []
    for i, text in enumerate(required, start=1):
        run = line_words(text)
        hit = None
        for p in range(kpos, len(found)):
            j = _find_run(found[p], run, jpos if p == kpos else 0)
            if j is not None:
                hit = (p, j)
                break
        if hit:
            kpos, jpos = hit[0], hit[1] + len(run)
            continue
        anywhere = any(_find_run(words, run, 0) is not None for words in found)
        out.append((Q1_ORDER if anywhere else Q1_MISSING) % (i, text))
    return out


GENERATION_CHECKS = ("N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11", "N12",
                     "N14", "N15", "N16", "N17", "N18", "T1", "T2", "T3", "Q1", "N19")
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    hard, advisory = [], []
    writers_by_panel = []
    for k in range(1, len(parts) + 1):
        fields = panel_fields(ctx, plan, parts, k)
```

with:

```python
    hard, advisory = [], []
    writers_by_panel = []
    dialogues = []
    for k in range(1, len(parts) + 1):
        fields = panel_fields(ctx, plan, parts, k)
        dialogues.append(dict(fields).get("Dialogue", ""))
```

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    advisory = plan_copied_examples(plan) + _order_by_panel(
        advisory + repeat_advisories(ctx, lib, plan, writers_by_panel))
    if ctx.mode == "shots":
```

with:

```python
    advisory = plan_copied_examples(plan) + _order_by_panel(
        advisory + repeat_advisories(ctx, lib, plan, writers_by_panel))
    if "Q1" in GENERATION_CHECKS:
        hard += spoken_line_problems(ctx, lib, cast_phrases(ctx, plan), dialogues)
    if ctx.mode == "shots":
```

**3.4.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
RECHECK_IDS = ("N1", "N2", "N3", "N4", "N7", "N8", "N9", "N10", "N11", "N12", "N14", "N15",
               "N16", "N17", "N18", "T1", "T2", "T3", "N19")
```

with:

```python
RECHECK_IDS = ("N1", "N2", "N3", "N4", "N7", "N8", "N9", "N10", "N11", "N12", "N14", "N15",
               "N16", "N17", "N18", "T1", "T2", "T3", "Q1", "N19")
```

**3.5.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
                hard += h
                advisory += a
            advisory = _order_by_panel(advisory + repeat_advisories(ctx, lib, plan, writers_by_panel))
```

with:

```python
                hard += h
                advisory += a
            hard += spoken_line_problems(ctx, lib, cast_phrases(ctx, plan),
                                         [p.get("dialogue", "") for p in parsed])
            advisory = _order_by_panel(advisory + repeat_advisories(ctx, lib, plan, writers_by_panel))
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py tests/test_dialogue.py tests/test_story_engine.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_judge_story.py 2>&1 | tail -1
```

Expected: `1 failed` (`test_rst62_import_sets`), `1 skipped` and the rest `passed`; `test_dlg17` (its `GENERATION_CHECKS[16:20]` and `RECHECK_IDS[14:18]` slices), `test_dlg21`, `test_dlg23`, `test_dlg25` and `test_dlg_h_offline_merge_gate` pass unchanged (their narratives quote nothing). Then the compile check with `FILES` = `story_engine.py tests/test_narrative_fidelity.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_narrative_fidelity.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_narrative_fidelity.py
git commit -m "feat(story): Q1, a quoted spoken line missing from every Dialogue: blocks the story (QL10, QL14, NF7-NF11)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: The pipeline gives each line the plan left out to the first eligible beat; the engine runs (QL8b)

Implements QL8b (`assign_missing_lines` and its `go()` hook) and NK5. Tests NF9b, NF28, NF29, NF30, NF32, NF33, NF37 and Review Focus 5.

**Files:**
- Modify: `story_engine.py` (after `line_assignment_problems` (Task 6); `_Run.go()` `:2716-2717`)
- Modify: `tests/test_narrative_fidelity.py` (append)

**Interfaces:**
- Consumes: `line_problem(ctx, lib, line)`, `_character_lib(ws)`, `se.run(ctx) -> (rc, advisories)` (existing); `speaking_coercion(ctx, plan, k)` (Task 4); the plan's `spoken_lines` and beat `lines` (Task 6); `line_assignment_problems` (Task 6); Q1 (Task 9); `_replay(..., assign=True)` (Task 9's helper).
- Produces (in `story_engine`): `assign_missing_lines(ctx, plan) -> [note]` (fills, in place, each line no beat holds into the first eligible beat; sets that beat's speaker to its sole cast member when it has none). In the tests: `_engine(monkeypatch, tmp_path, ctx, plan, panel, critic=()) -> (rc, log)`, `_story_json(ctx, *parts)`, `GIVEN`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_nf9b_replay_with_the_pipeline_assignment`, `test_nf37_assign_missing_lines`, `test_nf28_engine_the_2x145_failure`, `test_nf29_engine_the_1x241_failure`, `test_nf30_q1_blocks_when_no_beat_is_eligible`, `test_nf32_no_narration_keeps_the_movie_silent`, `test_nf33_default_narration_with_the_fixed_plan`, `test_review_focus_5_a_shots_movie_with_quoted_lines`.

**1.1.** Append to `tests/test_narrative_fidelity.py`:

```python
# --- NF9b, NF28-NF30, NF32, NF33, NF37, Review Focus 5: the pipeline assignment (QL8b) -------------

GIVEN = ("beat %d: P14 speaking beat: line %d given to this beat by the pipeline, because the plan "
         "gave it to no beat")


def _engine(monkeypatch, tmp_path, ctx, plan, panel, critic=()):
    """(rc, agent log) of se.run(ctx) with the fake agent's scripted replies."""
    log = seu.script_agent(monkeypatch, tmp_path, plan=plan, panel=panel, critic=list(critic))
    rc, _advisories = se.run(ctx)
    return rc, seu.agent_log(log)


def _story_json(ctx, *parts):
    with open(os.path.join(ctx.story_dir, *parts), encoding="utf-8") as f:
        return json.load(f)


def _story_text(ctx, *parts):
    with open(os.path.join(ctx.story_dir, *parts), encoding="utf-8") as f:
        return f.read()


def _stages(log):
    return [call["stage"] for call in log]


def test_nf9b_replay_with_the_pipeline_assignment(ws):
    state, plan, notes = _replay(ws, "hockey-2x145", "plan_reply_1.txt", assign=True)
    assert [b["lines"] for b in plan["beats"]] == [[1], [2]]
    assert plan["beats"][1]["speaker"] == "c1"
    assert notes == [GIVEN % (1, 1), GIVEN % (2, 2)]
    assert state["hard"] == [T2_2X145]
    state, plan, notes = _replay(ws, "hockey-1x241", "plan_reply_1.txt", assign=True)
    beat = plan["beats"][0]
    assert (beat["lines"], beat["speaker"], beat["shot"], beat["camera"]) == (
        [1, 2], "c1", "medium shot", "tracking")
    assert notes == [GIVEN % (1, 1), GIVEN % (1, 2)]
    assert state["hard"] == []


def test_nf37_assign_missing_lines(ws):
    def assigned(beats, n=3, narrative=COURIER_LINES):
        ctx, plan = _lines_plan(ws, narrative, beats, n=n)
        notes = se.assign_missing_lines(ctx, plan)
        return plan, notes

    plan, notes = assigned({})
    assert [b["lines"] for b in plan["beats"]] == [[1], [2], [3]]
    assert notes == [GIVEN % (1, 1), GIVEN % (2, 2), GIVEN % (3, 3)]
    assert [b["speaker"] for b in plan["beats"]] == ["c1", "c1", "c1"]
    assert (plan["beats"][0]["shot"], plan["beats"][0]["camera"]) == ("medium shot", "static")
    plan, notes = assigned({2: {"cast": ["c1", "c2"]}})
    assert [b["lines"] for b in plan["beats"]] == [[1], [], [2, 3]]
    assert notes == [GIVEN % (1, 1), GIVEN % (3, 2), GIVEN % (3, 3)]
    plan, notes = assigned({1: {"speaker": "c1", "lines": [1]}, 2: {"speaker": "c1", "lines": [3]}})
    assert [b["lines"] for b in plan["beats"]] == [[1], [2, 3], []]
    assert notes == [GIVEN % (2, 2)]
    seven = ('The courier says "Keep moving along the wet harbour road." Then he says "The temple '
             'gate is close to us."')
    plan, notes = assigned({}, n=1, narrative=seven)
    assert [b["lines"] for b in plan["beats"]] == [[1]] and notes == [GIVEN % (1, 1)]
    assert se.line_assignment_problems(plan) == [
        'plan: Q1 spoken line: spoken line 2 "The temple gate is close to us." is in no beat\'s '
        "lines; put 2 in the lines of the beat whose action surrounds it in the narrative, and "
        "give that beat a speaker"]
    plan, notes = assigned({}, narrative=seu.make_ctx(se, ws).narrative)
    assert notes == [] and [b["lines"] for b in plan["beats"]] == [[], [], []]


NF28_PATCH = {"target": "panel", "index": 2, "field": "motion", "reason": "r",
              "replacement": "The FuboTV player skates forward, then halts in a sharp hockey stop "
                             "that sprays ice mist into the air. He skates away from the camera."}


def _recorded(case, name):
    return seu.answer(_fixture_text(case, name))


def test_nf28_engine_the_2x145_failure(ws, tmp_path, monkeypatch):
    ctx = _hockey_ctx(ws, "hockey-2x145")
    plan = _recorded("hockey-2x145", "plan_reply_1.txt")
    rc, log = _engine(monkeypatch, tmp_path, ctx, [plan, plan],
                      {"1": [_recorded("hockey-2x145", "panel_01_reply_1.txt")],
                       "2": [_recorded("hockey-2x145", "panel_02_reply_1.txt")]},
                      [seu.answer(seu.critic_json((7, 6, 6), "revise", [NF28_PATCH]))])
    assert rc == 0
    assert _stages(log) == ["plan", "plan", "panel", "panel", "critic"]
    round0 = _story_json(ctx, "story_rounds", "round_0", "plan.json")
    assert [b["lines"] for b in round0["beats"]] == [[1], [2]]
    assert (round0["beats"][1]["speaker"], round0["beats"][1]["cast"]) == ("c1", ["c1"])
    assert round0["speech_notes"] == [GIVEN % (1, 1), GIVEN % (2, 2)]
    checks0 = _story_json(ctx, "story_rounds", "round_0", "story_checks.json")
    assert [v["id"] for v in checks0["hard"]] == ["T2"]
    assert '\ndialogue: exactly "%s" -- ' % LINE1 in _story_text(
        ctx, "story_rounds", "round_0", "panel_01_prompt_1.txt")
    assert _story_json(ctx, "story_rounds", "round_1", "critic.json")["applied"] == [NF28_PATCH]
    assert _story_json(ctx, "story_checks.json")["stop_reason"] == "passed"
    story = _story_text(ctx, "story.md")
    assert "Dialogue: the FuboTV player: " + LINE1 + "\n" in story
    assert story.endswith(
        "## Panel 2 — The FuboTV Hockey Stop\nMotion: The FuboTV player skates forward, then halts "
        "in a sharp hockey stop that sprays ice mist into the air. He skates away from the camera. "
        "The FuboTV player faces the camera. The camera stays static.\n"
        "Dialogue: the FuboTV player: It's just FuboTV.\n")


def test_nf29_engine_the_1x241_failure(ws, tmp_path, monkeypatch):
    ctx = _hockey_ctx(ws, "hockey-1x241")
    plan = _recorded("hockey-1x241", "plan_reply_1.txt")
    rc, log = _engine(monkeypatch, tmp_path, ctx, [plan, plan],
                      {"1": [_recorded("hockey-1x241", "panel_01_reply_1.txt")]})
    assert rc == 0
    assert _stages(log) == ["plan", "plan", "panel"]
    assert _story_json(ctx, "story_rounds", "round_0", "story_checks.json")["hard"] == []
    assert _story_json(ctx, "story_checks.json")["stop_reason"] == "passed"
    assert _story_json(ctx, "plan.json")["speech_notes"] == [GIVEN % (1, 1), GIVEN % (1, 2)]
    story = _story_text(ctx, "story.md")
    assert ("Motion: The FuboTV player skates forward toward the camera, then stops abruptly in a "
            "hockey stop, spraying ice mist into the air. He then skates away from the camera. The "
            "FuboTV player faces the camera. The camera tracks alongside the movement.\n"
            "Dialogue: the FuboTV player: " + LINE1 + " " + LINE2 + "\n") in story


def test_nf30_q1_blocks_when_no_beat_is_eligible(ws, tmp_path, monkeypatch, capsys):
    raw = seu.plan_json("chained", 3)
    for beat in raw["beats"]:
        beat["cast"] = ["c1", "c2"]
    ctx = seu.make_ctx(se, ws, narrative=COURIER_LINES)
    capsys.readouterr()
    rc, log = _engine(monkeypatch, tmp_path, ctx, [seu.answer(raw), seu.answer(raw)],
                      dict((str(k), [seu.answer(seu.panel_json("chained", k))]) for k in (1, 2, 3)),
                      [{"answer": "x"}] * 4)
    assert rc == 2
    assert _story_json(ctx, "story_rounds", "round_0", "plan.json")["speech_notes"] == []
    err = capsys.readouterr().err
    for i, line in enumerate(COURIER_SPOKEN, start=1):
        assert ("  - " + Q1_MISSING % (i, line) + "\n") in err
    assert [v["id"] for v in _story_json(ctx, "story_checks.json")["hard"]] == ["Q1", "Q1", "Q1"]
    assert _stages(log).count("critic") == 4 and _stages(log).count("plan") == 2
    assert "\nDialogue:" not in _story_text(ctx, "story.md")


def test_nf32_no_narration_keeps_the_movie_silent(ws, tmp_path, monkeypatch):
    ctx = seu.make_ctx(se, ws, narration=False, narrative=HOCKEY)
    rc, log = _engine(monkeypatch, tmp_path, ctx, [seu.answer(seu.plan_json("chained", 3))],
                      dict((str(k), [seu.answer(seu.panel_json("chained", k))]) for k in (1, 2, 3)))
    assert rc == 0 and _stages(log) == ["plan", "panel", "panel", "panel"]
    checks0 = _story_json(ctx, "story_rounds", "round_0", "story_checks.json")
    assert not [v for v in checks0["hard"] + checks0["advisory"] if v["id"] == "Q1"]
    assert Q2_HOCKEY in [v["message"] for v in checks0["advisory"]]
    assert "Spoken lines (" not in _story_text(ctx, "story_rounds", "round_0", "plan_prompt.txt")


def test_nf33_default_narration_with_the_fixed_plan(ws, tmp_path, monkeypatch, capsys):
    ctx = _hockey_ctx(ws, "hockey-2x145", narration=True)
    p2 = _recorded("hockey-2x145", "panel_02_reply_1.txt")
    capsys.readouterr()
    rc, log = _engine(monkeypatch, tmp_path, ctx, [_recorded("hockey-2x145", "plan_reply_fixed.json")],
                      {"1": [_recorded("hockey-2x145", "panel_01_reply_1.txt")], "2": [p2, p2]},
                      [{"answer": "x"}] * 4)
    assert rc == 0
    assert _stages(log).count("plan") == 1
    assert _story_json(ctx, "story_rounds", "round_0", "plan.json")["speech_notes"] == []
    checks0 = _story_json(ctx, "story_rounds", "round_0", "story_checks.json")
    assert [v["id"] for v in checks0["hard"]] == ["T2"]
    assert ("Warning: unresolved after 2 critic round(s): " + T2_2X145 + "\n"
            ) in capsys.readouterr().out
    story = _story_text(ctx, "story.md")
    assert "Dialogue: the FuboTV player: " + LINE1 + "\n" in story
    assert "Dialogue: the FuboTV player: " + LINE2 + "\n" in story


def test_review_focus_5_a_shots_movie_with_quoted_lines(ws, tmp_path, monkeypatch):
    # --shots with a quoted narrative: every shot is its own still and the shot rules S1/S3 are
    # hard. Expected: the plan's lines reach each speaking shot's Dialogue:, the shot rules do not
    # trip on the pasted facing sentence or the Dialogue: line, and the run passes with no Q1.
    narrative = 'The courier says "Keep moving." At the gate he whispers "We made it."'
    raw = seu.plan_json("shots", 2)
    raw["beats"][0].update(speaker="c1", lines=[1])
    raw["beats"][1].update(speaker="c1", lines=[2])
    ctx = seu.make_ctx(se, ws, mode="shots", panels=2, narrative=narrative)
    rc, log = _engine(monkeypatch, tmp_path, ctx, [seu.answer(raw)],
                      dict((str(k), [seu.answer(seu.panel_json("shots", k))]) for k in (1, 2)))
    assert rc == 0 and _stages(log) == ["plan", "panel", "panel"]
    assert _story_json(ctx, "story_rounds", "round_0", "story_checks.json")["hard"] == []
    story = _story_text(ctx, "story.md")
    assert "\nDialogue: the courier: Keep moving.\n" in story
    assert "\nDialogue: the courier: We made it.\n" in story
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py -k "nf9b or nf37 or nf28 or nf29 or nf30 or nf32 or nf33 or review_focus_5" 2>&1 | tail -9
```

Expected: `4 failed, 4 passed`. NF9b and NF37 fail with `AttributeError: ... no attribute 'assign_missing_lines'`; NF28 and NF29 fail on `assert rc == 0`, because the plan left both lines unassigned and the run blocks on Q1. NF30, NF32, NF33 and Review Focus 5 pass already: they pin runs in which no beat is eligible, the movie is silent, or the plan assigns every line, so the assignment must leave them exactly as they are.

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
            for n, line in enumerate(plan.get("spoken_lines", []), start=1) if n not in held]
```

with:

```python
            for n, line in enumerate(plan.get("spoken_lines", []), start=1) if n not in held]


def assign_missing_lines(ctx, plan):
    """The P14 notes of QL8b: each of the narrative's spoken lines that no beat holds goes to the
    first eligible beat after the beat holding the nearest earlier line (then to that beat
    itself), never later than the beat holding the next assigned line. A beat is eligible when
    it has a speaker or exactly one cast member (who becomes the speaker, with
    speaking_coercion) and its lines with the new one still fit the clip. A line with no
    eligible beat stays unassigned, for Q1 and the critic. Lines the plan placed never move."""
    spoken, beats, notes = plan["spoken_lines"], plan["beats"], []
    if not spoken:
        return notes
    lib = _character_lib(ctx.ws)
    cast_ids = [c["id"] for c in plan["cast"]]
    holder = dict((n, k) for k, beat in enumerate(beats, start=1) for n in beat["lines"])
    for n in range(1, len(spoken) + 1):
        if n in holder:
            continue
        earlier = [holder[m] for m in range(1, n) if m in holder]
        prev_k = earlier[-1] if earlier else 0
        later = [holder[m] for m in range(n + 1, len(spoken) + 1) if m in holder]
        next_k = later[0] if later else len(beats)
        for k in list(range(prev_k + 1, next_k + 1)) + ([prev_k] if prev_k else []):
            beat = beats[k - 1]
            if not (beat["speaker"] or (len(beat["cast"]) == 1 and beat["cast"][0] in cast_ids)):
                continue
            lines = sorted(beat["lines"] + [n])
            if line_problem(ctx, lib, " ".join(spoken[m - 1] for m in lines)):
                continue
            notes.append("beat %d: P14 speaking beat: line %d given to this beat by the pipeline, "
                         "because the plan gave it to no beat" % (k, n))
            if not beat["speaker"]:
                beat["speaker"] = beat["cast"][0]
                notes += speaking_coercion(ctx, plan, k)
            beat["lines"] = lines
            holder[n] = k
            break
    return notes
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        plan, self.shape, _hard = found
        parts = [empty_parts(ctx.mode, k, plan, ctx) for k in range(1, ctx.panels + 1)]
```

with:

```python
        plan, self.shape, _hard = found
        plan["speech_notes"] += assign_missing_lines(ctx, plan)
        parts = [empty_parts(ctx.mode, k, plan, ctx) for k in range(1, ctx.panels + 1)]
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py tests/test_dialogue.py tests/test_story_engine.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_judge_story.py 2>&1 | tail -1
```

Expected: `1 failed` (`test_rst62_import_sets`), `1 skipped` and the rest `passed`. Then the compile check with `FILES` = `story_engine.py tests/test_narrative_fidelity.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_narrative_fidelity.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_narrative_fidelity.py
git commit -m "feat(story): the pipeline gives each unassigned spoken line to the first eligible beat (QL8b, NF9b, NF28-NF30, NF32, NF33, NF37)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: The critic prompt: the spoken-lines block and the Q1 patch line (QL11, 7.3)

Implements QL11 and 7.3 (`CRITIC_Q1_FIELD_LINE`, `critic_field_lines(..., spoken=False)`, `build_critic_prompt`). Tests NF25.

**Files:**
- Modify: `story_engine.py` (`CRITIC_RETRY_SUFFIX` `:2019-2021`; `critic_field_lines` `:2031-2051`; `build_critic_prompt` `:2068`, `:2077`)
- Modify: `tests/test_narrative_fidelity.py` (append)

**Interfaces:**
- Consumes: `spoken_lines_block(lines)` (Task 7); the plan's `spoken_lines` (Task 6); `_replay` (Task 9); `dlg.DIALOGUE_FIELD_LINE` (`tests/test_dialogue.py`).
- Produces (in `story_engine`): `CRITIC_Q1_FIELD_LINE`; `critic_field_lines(mode, catalog_lines, narration=True, spoken=False) -> str`. `build_critic_prompt(plan, story_md_text, violations, catalog_lines=None, for_judge=False, narration=True)` keeps its signature (`bin/judge-story` calls it with a raw plan.json, which may lack `spoken_lines`).

- [ ] **Step 1: Write the failing test.**

New test in this task: `test_nf25_the_critic_prompt`.

**1.1.** Append to `tests/test_narrative_fidelity.py`:

```python
# --- NF25: the critic prompt (QL11, 7.3) --------------------------------------------------------------

CRITIC_Q1_FIELD_LINE = (
    '- target "panel", field "dialogue", index = the number of the panel that shows the line '
    "being said, only when a [hard] Q1 problem names a spoken line: replacement is the "
    "speaker's referring phrase, a colon and then that spoken line, or several consecutive "
    "spoken lines, copied word for word from the Spoken lines list in their order; the pipeline "
    "makes that character the panel's speaker. This is the only patch that adds spoken words.")


def test_nf25_the_critic_prompt(ws):
    assert se.CRITIC_Q1_FIELD_LINE == CRITIC_Q1_FIELD_LINE
    state, plan, _notes = _replay(ws, "hockey-2x145", "plan_reply_1.txt")
    prompt = se.build_critic_prompt(plan, state["text"], (state["hard"], state["advisory"]),
                                    narration="speech")
    assert ("Narrative to adapt:\n" + HOCKEY + SPOKEN_BLOCK + "\n\nThe target output goal is "
            ) in prompt
    assert ("\n" + dlg.DIALOGUE_FIELD_LINE + "\n" + CRITIC_Q1_FIELD_LINE + "\nPreserve every "
            ) in prompt
    assert "\n- [hard] " + Q1_MISSING % (2, LINE2) + "\n" in prompt
    assert "@@" not in prompt
    for mode in ("chained", "no_stills", "shots"):
        lines = se.critic_field_lines(mode, None)
        assert lines == se.critic_field_lines(mode, None, True, False), mode
        assert CRITIC_Q1_FIELD_LINE not in lines and lines.endswith(dlg.DIALOGUE_FIELD_LINE), mode
        assert se.critic_field_lines(mode, None, "speech", True) == (
            lines + "\n" + CRITIC_Q1_FIELD_LINE), mode
        assert se.critic_field_lines(mode, None, False, True) == se.critic_field_lines(
            mode, None, False), mode
    ctx = _hockey_ctx(ws, "hockey-2x145", narration=False)
    silent, _shape = se.normalize_plan(ctx, _reply("hockey-2x145"))
    prompt = se.build_critic_prompt(silent, state["text"], ([], []), narration=False)
    assert "Spoken lines (" not in prompt and CRITIC_Q1_FIELD_LINE not in prompt
    older = dict(plan)
    del older["spoken_lines"]
    prompt = se.build_critic_prompt(older, state["text"], ([], []))
    assert "Spoken lines (" not in prompt and CRITIC_Q1_FIELD_LINE not in prompt
```

- [ ] **Step 2: Run the test and confirm it fails.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py -k nf25 2>&1 | tail -3
```

Expected: `1 failed`, with `AttributeError: module 'story_engine_for_fidelity' has no attribute 'CRITIC_Q1_FIELD_LINE'`.

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
CRITIC_RETRY_SUFFIX = ("\n\nYour previous reply was not one JSON object with the keys scores, "
                       "verdict and patches in the required form. Reply with that JSON object "
                       "only.")
```

with:

```python
CRITIC_RETRY_SUFFIX = ("\n\nYour previous reply was not one JSON object with the keys scores, "
                       "verdict and patches in the required form. Reply with that JSON object "
                       "only.")
# Narrative dialogue fidelity spec 7.3: the critic's one way to add a missing quoted line (QL13).
CRITIC_Q1_FIELD_LINE = (
    '- target "panel", field "dialogue", index = the number of the panel that shows the line '
    "being said, only when a [hard] Q1 problem names a spoken line: replacement is the "
    "speaker's referring phrase, a colon and then that spoken line, or several consecutive "
    "spoken lines, copied word for word from the Spoken lines list in their order; the pipeline "
    "makes that character the panel's speaker. This is the only patch that adds spoken words.")
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def critic_field_lines(mode, catalog_lines, narration=True):
    """The allowed-patch lines of the critic prompt (dialogue spec 8.3): the lora line when
    catalog_lines is set, the Motion: (Prompt: in no_stills) line for a T2/T3 panel, and the
    dialogue line for a T1 panel unless the movie has no spoken lines."""
```

with:

```python
def critic_field_lines(mode, catalog_lines, narration=True, spoken=False):
    """The allowed-patch lines of the critic prompt (dialogue spec 8.3): the lora line when
    catalog_lines is set, the Motion: (Prompt: in no_stills) line for a T2/T3 panel, and the
    dialogue line for a T1 panel unless the movie has no spoken lines; then, when the narrative
    quotes spoken lines (spoken), the Q1 dialogue line (narrative dialogue fidelity spec QL11)."""
```

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
                     "without the speaker's phrase and without quotation marks, within the limit "
                     "the T1 problem states.")
    return "\n".join(lines)
```

with:

```python
                     "without the speaker's phrase and without quotation marks, within the limit "
                     "the T1 problem states.")
        if spoken:
            lines.append(CRITIC_Q1_FIELD_LINE)
    return "\n".join(lines)
```

**3.4.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
        ("@@FIELD_LINES@@", critic_field_lines(plan["mode"], catalog_lines, narration)),
```

with:

```python
        ("@@FIELD_LINES@@", critic_field_lines(plan["mode"], catalog_lines, narration,
                                               spoken=bool(plan.get("spoken_lines")))),
```

**3.5.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    return text.replace("@@NARRATIVE@@", plan["narrative"])
```

with:

```python
    return text.replace("@@NARRATIVE@@",
                        plan["narrative"] + spoken_lines_block(plan.get("spoken_lines", [])))
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py tests/test_dialogue.py tests/test_story_engine.py tests/test_judge_story.py 2>&1 | tail -1
```

Expected: `1 failed` (`test_rst62_import_sets`), `1 skipped` and the rest `passed`; `test_dlg19_critic_prompt` and the `tests/test_judge_story.py` tests that call `build_critic_prompt` pass unchanged (spec 8.3 B). Then the compile check with `FILES` = `story_engine.py tests/test_narrative_fidelity.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_narrative_fidelity.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_narrative_fidelity.py
git commit -m "feat(story): the critic sees the spoken lines and the Q1 dialogue patch (QL11, NF25)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: The critic's Q1 dialogue patch (QL13)

Implements QL13 (`repairable_ids` story scope, `Q1_ONLY_REASON`, `spoken_run`, `contained_lines`, `q1_dialogue_patch`, the `apply_patches` panel loop and the never-rewritten guard). Tests NF21, NF24 and Review Focus 4.

**Files:**
- Modify: `story_engine.py` (before `apply_patches` and its docstring `:2187-2193`; its panel loop `:2238-2248`; `repairable_ids` `:2265-2272`)
- Modify: `tests/test_narrative_fidelity.py` (append)

**Interfaces:**
- Consumes: `line_words`, `spoken_lines` (Task 2); `speaking_coercion` (Task 4); `_nums` (Task 6); `_find_run`, `Q1_MISSING` (Task 9); `clean_writer`, `cast_phrases`, `panel_fields`, `line_problem`, `_q`, `parse_violation` (existing); `character_lib.parse_dialogue`, `clean_line`, `speaker_prefix`.
- Produces (in `story_engine`): `repairable_ids(hard)` also maps the key `"story"` to the set of story-scope hard ids; `Q1_ONLY_REASON` (`% panel`); `spoken_run(text, spoken) -> (i, j) or None`; `contained_lines(text, spoken) -> [int]`; `q1_dialogue_patch(ctx, lib, plan, parts, k, replacement) -> (matched, problem)` (on success it sets the beat's speaker and lines and `parts[k - 1]["dialogue"]` in place); `apply_patches(ctx, state, patches, lora_allowed=None, repairable=None)` keeps its signature.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_nf21_repairable_ids_story_scope`, `test_nf24_the_q1_dialogue_patch`, `test_review_focus_4_a_retyped_q1_patch_stores_the_narrative_words`.

**1.1.** Append to `tests/test_narrative_fidelity.py`:

```python
# --- NF21, NF24, Review Focus 4: the critic's Q1 dialogue patch (QL13) -----------------------------

Q1_ONLY = ("panel %d has no hard timing problem, and under a Q1 problem a dialogue replacement must "
           "be the speaker's referring phrase, a colon and one or more consecutive spoken lines of "
           "the narrative, word for word")
STORY_Q1 = {"story": {"Q1"}}


def _dialogue_patch(index, replacement):
    return {"target": "panel", "index": index, "field": "dialogue", "reason": "r",
            "replacement": replacement}


def _apply(ctx, plan, parts, replacements, repairable=None):
    """apply_patches with one dialogue patch per (panel, replacement); repairable defaults to a
    story Q1."""
    state = {"plan": plan, "parts": parts}
    patches = [_dialogue_patch(k, text) for k, text in replacements]
    return se.apply_patches(ctx, state, patches, lora_allowed=False,
                            repairable=STORY_Q1 if repairable is None else repairable)


def _reasons(rejected):
    return [r["reason"] for r in rejected]


def _seu3(ws, beats=None, writer_dialogue=None):
    """(ctx, plan, parts) of the NF24 "seu3" case: seu.plan_json("chained", 3) under the NF13
    narrative, beat 2 cast c1 and c2, beat 3 spoken by c1; beats adds field overrides; the parts
    are the raw seu.panel_json replies, panel 1 with writer_dialogue when given."""
    fields = {2: {"cast": ["c1", "c2"]}, 3: {"speaker": "c1"}}
    for k, extra in (beats or {}).items():
        fields[k] = dict(fields.get(k, {}), **extra)
    ctx, plan = _lines_plan(ws, COURIER_LINES, fields)
    parts = [dict(seu.panel_json("chained", k)) for k in (1, 2, 3)]
    if writer_dialogue is not None:
        parts[0]["dialogue"] = writer_dialogue
    return ctx, plan, parts


def _rec(ws, case, reply="plan_reply_1.txt", **ctx_kw):
    """(ctx, plan, parts) of a replayed recorded round 0 (no pipeline assignment)."""
    state, plan, _notes = _replay(ws, case, reply, **ctx_kw)
    return _hockey_ctx(ws, case, **ctx_kw), plan, state["parts"]


def test_nf21_repairable_ids_story_scope():
    assert se.repairable_ids(["story: Q1 spoken line: x", T2_2X145]) == {2: {"T2"},
                                                                         "story": {"Q1"}}
    assert se.repairable_ids([T2_2X145]) == {2: {"T2"}}


def test_nf24_the_q1_dialogue_patch(ws):
    assert se.Q1_ONLY_REASON == Q1_ONLY
    ctx, plan, parts = _rec(ws, "hockey-2x145")
    new, applied, rejected = _apply(ctx, plan, parts, [(2, _say(LINE2))])
    assert len(applied) == 1 and rejected == []
    assert (new["plan"]["beats"][1]["speaker"], new["plan"]["beats"][1]["lines"]) == ("c1", [2])
    assert new["parts"][1]["dialogue"] == LINE2
    assert plan["beats"][1]["lines"] == [] and "dialogue" not in parts[1]
    one_ctx, one_plan, one_parts = _rec(ws, "hockey-1x241")
    new, applied, rejected = _apply(one_ctx, one_plan, one_parts, [(1, LINE1 + " " + LINE2)])
    assert len(applied) == 1 and new["plan"]["beats"][0]["lines"] == [1, 2]
    assert new["plan"]["beats"][0]["speaker"] == "c1"
    s_ctx, s_plan, s_parts = _seu3(ws)
    _new, applied, rejected = _apply(s_ctx, s_plan, s_parts, [(2, "Keep moving.")])
    assert _reasons(rejected) == [
        "name the speaker: start the replacement with their referring phrase and a colon"]
    _new, applied, rejected = _apply(ctx, plan, parts, [(2, "It is just Fubo.")])
    assert _reasons(rejected) == [Q1_ONLY % 2]
    f_ctx, f_plan, f_parts = _rec(ws, "hockey-2x145", "plan_reply_fixed.json")
    _new, applied, rejected = _apply(f_ctx, f_plan, f_parts, [(1, _say(LINE1 + " " + LINE2))])
    assert _reasons(rejected) == ["spoken line 2 is already given to beat 2"]
    new, applied, rejected = _apply(ctx, plan, parts, [(1, _say(LINE2))])
    assert len(applied) == 1 and new["plan"]["beats"][0]["lines"] == [1, 2]
    assert new["parts"][0]["dialogue"] == LINE1 + " " + LINE2
    g_ctx, g_plan, g_parts = _rec(ws, "hockey-1x241", seconds="4", clip_seconds=97 / 24.0)
    _new, applied, rejected = _apply(g_ctx, g_plan, g_parts, [(1, LINE1 + " " + LINE2)])
    assert _reasons(rejected) == [
        "the new line is 13 words in 2 sentences; at most 8 words in 2 sentences fit this clip"]
    _new, applied, rejected = _apply(s_ctx, s_plan, s_parts, [(3, "the old monk: The gate is close.")])
    assert _reasons(rejected) == [
        "panel 3's speaker is 'c1'; a spoken-line patch never changes who speaks"]
    _new, applied, rejected = _apply(ctx, plan, parts, [(2, "the hockey player: " + LINE2)])
    assert _reasons(rejected) == [
        "the replacement names 'the hockey player', which is no character's referring phrase; use "
        "one of: 'the FuboTV player'"]
    _new, applied, rejected = _apply(ctx, plan, parts, [(2, _say(LINE2))], repairable={2: {"T2"}})
    assert _reasons(rejected) == [
        "panel 2 has no hard timing or amount-of-action problem; advisory findings are never "
        "patched"]
    _new, applied, rejected = _apply(f_ctx, f_plan, f_parts, [(2, "Short.")],
                                     repairable={2: {"T1"}})
    assert _reasons(rejected) == [
        "panel 2 says the narrative's spoken line(s) 2, which are never rewritten"]
    first, applied, rejected = _apply(s_ctx, s_plan, s_parts, [(1, "the courier: Keep moving.")])
    assert len(applied) == 1 and first["plan"]["beats"][0]["lines"] == [1]
    assert first["plan"]["beats"][0]["speaker"] == "c1"
    second, applied, rejected = _apply(s_ctx, first["plan"], first["parts"],
                                       [(1, "the courier: The gate is close.")])
    assert len(applied) == 1 and second["plan"]["beats"][0]["lines"] == [1, 2]
    assert second["parts"][0]["dialogue"] == "Keep moving. The gate is close."
    _new, applied, rejected = _apply(s_ctx, first["plan"], first["parts"],
                                     [(1, "the courier: We made it.")])
    assert _reasons(rejected) == [
        "the replacement must keep panel 1's spoken lines and add only an adjacent line"]
    n_ctx, n_plan, n_parts = _seu3(ws, {1: {"speaker": "c1"}}, "Hello there. Keep moving.")
    _new, applied, rejected = _apply(n_ctx, n_plan, n_parts, [(1, "the courier: The gate is close.")])
    assert _reasons(rejected) == [
        "panel 1's Dialogue: has words that are not the narrative's spoken lines, and existing "
        "Dialogue words are never rewritten"]
    assert (se.spoken_run(LINE1 + " " + LINE2, [LINE1, LINE2]),
            se.spoken_run("it's just fubotv", [LINE1, LINE2]),
            se.spoken_run("hat trick", [LINE1, LINE2]), se.spoken_run("...", [LINE1])) == (
        (1, 2), (2, 2), None, None)
    assert se.contained_lines("Yes. " + LINE2, [LINE1, LINE2]) == [2]


def test_review_focus_4_a_retyped_q1_patch_stores_the_narrative_words(ws):
    # A local critic re-types the missing line: other case, curly quotes, no full stop. Expected:
    # the patch applies, the stored Dialogue: text is the narrative's own spelling, and Q1 clears.
    ctx, plan, parts = _rec(ws, "hockey-2x145")
    new, applied, rejected = _apply(ctx, plan, parts, [(2, "The FuboTV Player: “it’s just fubotv”")])
    assert len(applied) == 1 and rejected == []
    assert new["parts"][1]["dialogue"] == LINE2
    state = se._Run(ctx, "").make_state(1, new["plan"], new["parts"])
    assert state["hard"] == [T2_2X145]
    assert state["text"].endswith("Dialogue: the FuboTV player: It's just FuboTV.\n")
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py -k "nf21 or nf24 or review_focus_4" 2>&1 | tail -5
```

Expected: `3 failed`: NF21 (no `"story"` key), NF24 (`AttributeError: ... no attribute 'Q1_ONLY_REASON'`) and Review Focus 4 (the patch is rejected: panel 2 has no T1 or N18).

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def apply_patches(ctx, state, patches, lora_allowed=None, repairable=None):
    """(new_state, applied, rejected) for a state {"plan", "parts"} and a patch list (RS20;
    dialogue spec PG1-PG4). Works on a deep copy; rejected items are {"patch", "reason"}.
    repairable is {panel: set of hard ids} of the judged state, or None for no restriction: a
    motion or prompt patch needs a T2 or T3 on its panel, a dialogue patch a T1. A motion or
    prompt replacement must pass the PG3 sentence guard; a dialogue replacement must fit the
    clip (PG4)."""
```

with:

```python
Q1_ONLY_REASON = ("panel %d has no hard timing problem, and under a Q1 problem a dialogue "
                  "replacement must be the speaker's referring phrase, a colon and one or more "
                  "consecutive spoken lines of the narrative, word for word")


def spoken_run(text, spoken):
    """(i, j) when the words of text (line_words) are exactly the words of spoken lines i to j,
    in order, for the smallest such i; else None (narrative dialogue fidelity spec QL13)."""
    words = line_words(text)
    if not words:
        return None
    for i in range(1, len(spoken) + 1):
        run = []
        for j in range(i, len(spoken) + 1):
            run += line_words(spoken[j - 1])
            if run == words:
                return i, j
            if len(run) >= len(words):
                break
    return None


def contained_lines(text, spoken):
    """The numbers of the spoken lines whose words lie, in order, inside text (QL13)."""
    words = line_words(text)
    return [n for n, line in enumerate(spoken, start=1)
            if _find_run(words, line_words(line), 0) is not None]


def q1_dialogue_patch(ctx, lib, plan, parts, k, replacement):
    """(matched, problem) for a critic dialogue patch on panel k under a Q1 problem (QL13).
    matched is False when the replacement is not one or more consecutive spoken lines of the
    narrative (then the caller's ordinary dialogue rules apply); otherwise problem is None (the
    patch is applied in place: the beat gets its speaker when it has none, with
    speaking_coercion, and the lines, and parts[k - 1]["dialogue"] the narrative's canonical
    words) or the reason it is rejected. The speaker comes from the replacement's referring
    phrase, else the beat's speaker, else the beat's sole cast member; the patch keeps the
    panel's spoken lines, adds only adjacent ones, and never rewrites other Dialogue words."""
    spoken = plan["spoken_lines"]
    phrases = cast_phrases(ctx, plan)
    text = clean_writer(lib, replacement)
    phrase, line, _problem = lib.parse_dialogue(text, phrases)
    if phrase:
        sid0 = next((c["id"] for c in plan["cast"]
                     if (c.get("phrase") or "").lower() == phrase.lower()), "")
        run = spoken_run(line, spoken)
    else:
        sid0 = ""
        run = spoken_run(lib.clean_line(text), spoken)
        found = lib.speaker_prefix(text) if run is None else None
        if found and spoken_run(found[1], spoken) is not None:
            return True, "the replacement " + lib.parse_dialogue(text, phrases)[2]
    if run is None:
        return False, None
    i, j = run
    beat = plan["beats"][k - 1]
    sid = sid0 or beat["speaker"] or (beat["cast"][0] if len(beat["cast"]) == 1 else "")
    if not sid:
        return True, "name the speaker: start the replacement with their referring phrase and a colon"
    if beat["speaker"] and sid != beat["speaker"]:
        return True, ("panel %d's speaker is %s; a spoken-line patch never changes who speaks"
                      % (k, _q(beat["speaker"])))
    current = lib.parse_dialogue(dict(panel_fields(ctx, plan, parts, k)).get("Dialogue", ""),
                                 phrases)[1]
    have = contained_lines(current, spoken)
    want = set(beat["lines"]) | set(have) | set(range(i, j + 1))
    if max(want) - min(want) + 1 != len(want):
        return True, ("the replacement must keep panel %d's spoken lines and add only an "
                      "adjacent line" % k)
    i, j = min(want), max(want)
    words = line_words(current)
    if words and (not have or words != [w for n in range(min(have), max(have) + 1)
                                        for w in line_words(spoken[n - 1])]):
        return True, ("panel %d's Dialogue: has words that are not the narrative's spoken lines, "
                      "and existing Dialogue words are never rewritten" % k)
    for other_k, other in enumerate(plan["beats"], start=1):
        overlap = set(other["lines"]) & set(range(i, j + 1))
        if other_k != k and overlap:
            return True, "spoken line %d is already given to beat %d" % (min(overlap), other_k)
    canonical = " ".join(spoken[i - 1:j])
    problem = line_problem(ctx, lib, canonical)
    if problem:
        return True, problem
    if beat["speaker"] == "":
        beat["speaker"] = sid
        plan["speech_notes"] += speaking_coercion(ctx, plan, k)
    beat["lines"] = list(range(i, j + 1))
    parts[k - 1]["dialogue"] = canonical
    return True, None


def apply_patches(ctx, state, patches, lora_allowed=None, repairable=None):
    """(new_state, applied, rejected) for a state {"plan", "parts"} and a patch list (RS20;
    dialogue spec PG1-PG4). Works on a deep copy; rejected items are {"patch", "reason"}.
    repairable is {panel: set of hard ids, "story": set of story-scope hard ids} of the judged
    state, or None for no restriction: a motion or prompt patch needs a T2 or T3 on its panel, a
    dialogue patch a T1 or N18. A motion or prompt replacement must pass the PG3 sentence guard;
    a dialogue replacement must fit the clip (PG4). Under a story Q1 (narrative dialogue fidelity
    spec QL13), a dialogue replacement that is consecutive spoken lines of the narrative goes
    through q1_dialogue_patch instead; a panel's spoken lines are never rewritten."""
```

**3.2.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
    for patch in accepted:
        if patch["target"] != "panel":
            continue
        k, field = patch["index"], patch["field"]
        need = {"T1", "N18"} if field == "dialogue" else {"T2", "T3"}
        if repairable is not None and not (repairable.get(k, set()) & need):
            rejected.append({"patch": patch, "reason": "panel %d has no hard timing or "
                                                       "amount-of-action problem; advisory "
                                                       "findings are never patched" % k})
            continue
        if field == "dialogue":
```

with:

```python
    q1 = bool(plan.get("spoken_lines")) and (repairable is None
                                             or "Q1" in repairable.get("story", set()))
    for patch in accepted:
        if patch["target"] != "panel":
            continue
        k, field = patch["index"], patch["field"]
        if field == "dialogue" and q1:
            matched, problem = q1_dialogue_patch(ctx, lib, plan, parts, k, patch["replacement"])
            if matched:
                if problem:
                    rejected.append({"patch": patch, "reason": problem})
                else:
                    applied.append(patch)
                continue
        need = {"T1", "N18"} if field == "dialogue" else {"T2", "T3"}
        if repairable is not None and not (repairable.get(k, set()) & need):
            reason = (Q1_ONLY_REASON % k if field == "dialogue" and q1 else
                      "panel %d has no hard timing or amount-of-action problem; advisory findings "
                      "are never patched" % k)
            rejected.append({"patch": patch, "reason": reason})
            continue
        if field == "dialogue" and plan["beats"][k - 1].get("lines"):
            rejected.append({"patch": patch, "reason": "panel %d says the narrative's spoken "
                                                       "line(s) %s, which are never rewritten"
                                                       % (k, _nums(plan["beats"][k - 1]["lines"]))})
            continue
        if field == "dialogue":
```

**3.3.** Edit `story_engine.py`: replace this text, which occurs exactly once:

```python
def repairable_ids(hard):
    """{panel number: set of its hard violation ids} (dialogue spec PG2)."""
    out = {}
    for message in hard:
        violation = parse_violation(message)
        if violation["scope"] == "panel" and violation["index"]:
            out.setdefault(violation["index"], set()).add(violation["id"])
    return out
```

with:

```python
def repairable_ids(hard):
    """{panel number: set of its hard violation ids} (dialogue spec PG2), plus "story": the set of
    story-scope hard ids, such as Q1 (narrative dialogue fidelity spec QL13), when there is one."""
    out = {}
    for message in hard:
        violation = parse_violation(message)
        if violation["scope"] == "panel" and violation["index"]:
            out.setdefault(violation["index"], set()).add(violation["id"])
        elif violation["scope"] == "story":
            out.setdefault("story", set()).add(violation["id"])
    return out
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_narrative_fidelity.py tests/test_dialogue.py tests/test_story_engine.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_judge_story.py 2>&1 | tail -1
```

Expected: `1 failed` (`test_rst62_import_sets`), `1 skipped` and the rest `passed`; `test_dlg20`, `test_dlg22`, `test_ff3` and `test_ff4` pass unchanged (spec 8.3 B). Then the compile check with `FILES` = `story_engine.py tests/test_narrative_fidelity.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_narrative_fidelity.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_narrative_fidelity.py
git commit -m "feat(story): the critic repairs Q1 with a dialogue patch that makes the panel's character speak the line (QL13, NF21, NF24)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Design review, the test_mut26 re-baseline (test-only commit), NK1-NK3 and NK7

Implements spec 9 steps 2-4 (G6) and measures NK1, NK2, NK3, NK6 and NK7. It hands NK8 (the live reruns, spec 9 step 5) and the PR note to the main thread. No production code changes in this task.

**Files:**
- Modify: `tests/test_movie_ui_builder.py` (`test_mut26_pipeline_files_are_unchanged` `:283-285`: spec 8.3 A "`BASELINE` = the feature commit's SHA, with `", then to <sha> (narrative dialogue fidelity)"` appended to the comment")

**Interfaces:**
- Consumes: every earlier task's commit.
- Produces: the final pass counts in `/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-26-narrative-fidelity/final-pytest.txt`.

- [ ] **Step 1: Design review (controller; spec 9 step 3).** Ask an Opus `design-reviewer` to review `git diff 7aac623..HEAD -- qwen-agent-workspace` against the spec and this plan. Fix every finding in a new commit on the owning task's files before Step 2, then re-run that task's Step 4.

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
old_comment = ("(the seed is persisted under the library lock after the preflights).\n"
               "    # This invariant holds from the new baseline.\n")
new_comment = ("(the seed is persisted under the library lock after the preflights), then to "
               "%s (narrative dialogue fidelity).\n"
               "    # This invariant holds from the new baseline.\n" % sha)
old_base = '    BASELINE = "5903089fe272c03933d31ca4af105c4aec42b823"\n'
assert text.count(old_comment) == 1 and text.count(old_base) == 1
text = text.replace(old_comment, new_comment).replace(old_base, '    BASELINE = "%s"\n' % sha)
with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("re-based to", sha)
EOF
python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py -k mut26 2>&1 | tail -1
```

Expected: the SHA is Task 12's commit, the last one that touched a `PIPELINE_FILES` entry (`story_engine.py`), or the Step 1 fix commit if that touched one; then `re-based to <that SHA>`; then `1 passed, 11 deselected`.

- [ ] **Step 3: Commit (test-only; spec 0.3 G6).**

```bash
git add tests/test_movie_ui_builder.py
git diff --cached --name-only    # expected: only qwen-agent-workspace/tests/test_movie_ui_builder.py
git commit -m "test(movie-ui): re-baseline mut26 to the narrative dialogue fidelity pipeline commit" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4: NK1, the full suite against the baseline (about 12 minutes).**

```bash
D=/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-26-narrative-fidelity
python3 -m pytest tests/ -q -rA -p no:cacheprovider > $D/final-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt; tail -1 $D/final-pytest.txt
grep -E '^(FAILED|ERROR)' $D/final-pytest.txt
python3 tests/test_ltx_movie_offline.py 2>&1 | tail -1
diff <(grep -E '^PASSED' $D/baseline-pytest.txt | sort) <(grep -E '^PASSED' $D/final-pytest.txt | sort) | grep '^<' || echo "no lost pass"
```

Expected: the `FAILED` lines are exactly `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`. The passed count is the baseline's plus 42 (the functions of `tests/test_narrative_fidelity.py`: NF1-NF17, NF9b, NF19-NF37 and Review Focus 1-5); the skipped count is unchanged. The offline script prints `OK n/n` with the baseline `n`. The last command prints `no lost pass` (no test is renamed). Any other difference: stop and report.

- [ ] **Step 5: NK2, NK3, NK6, NK7.**

```bash
for py in /usr/bin/python3 python3; do $py -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' story_engine.py character_lib.py bin/ltx-story-manifest tests/test_narrative_fidelity.py tests/test_dialogue.py tests/test_story_engine.py tests/test_movie_ui_builder.py; done
git diff 7aac623 -- story_engine.py character_lib.py bin/ltx-story-manifest | grep -E '^\+\s*(import|from) ' || echo "no new import"
git diff --name-only 7aac623 -- bin/ltx-movie bin/judge-story bin/judge-clips bin/judge-stills movie_ui_lib.py static ltx2_mlx_video_skill.py | wc -l
python3 -m pytest -q -p no:cacheprovider tests/test_story_engine.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_dialogue.py -k "rst40 or rst41 or rst61 or s52 or s20 or casting or dk2 or dk3" 2>&1 | tail -1
```

Expected: `compiled 7` twice; `no new import`; `0` (spec 0.3 "Not changed"); then `passed` with no failure (NK7: `test_rst40`, `test_rst41`, `test_s52`, `tests/test_casting_regression.py`; NK2/NK3: `test_rst61`, `test_s20`, DK2, DK3).

- [ ] **Step 6: Hand-off of NK8 and the PR note (main thread or user; not an executor step).** After the merge:
  - Rerun both hockey commands of spec 0.1 with `--story-id hockey-2x145-f` and `--story-id hockey-1x241-f`. Phase 1 exits 0, and `story.md` holds both lines verbatim in `Dialogue:` fields in narrative order. Whisper on the clips hears both lines; in 2x145 panel 2 the line comes before the skate-away (SP-P). Record the exit codes, the `Dialogue:` lines and the whisper transcripts in the PR.
  - The PR description carries the spec 9 note, in substance: "An existing story whose narrative quotes spoken lines, written before this change, now exits 2 on re-check (Q1) when a quoted line is missing from its `Dialogue:` fields. `bin/ltx-movie` re-checks an existing story.md unless `--force-story` is given. Either rerun with `--force-story` to regenerate it, or hand-add the `Dialogue:` lines the error names."

---

## Coverage

### Spec section to task

| Spec | Task(s) |
|---|---|
| 0.3 G1 (`story_engine.py`) | 2-12 |
| 0.3 G2 (`character_lib.py`), G2b (`bin/ltx-story-manifest`) | 1 |
| 0.3 G3 (`tests/test_narrative_fidelity.py`) | 1-12 |
| 0.3 G4 (fixtures, 8.2) | 2 |
| 0.3 G5 (existing tests, 8.3 A) | 4, 5, 6, 7, 8 |
| 0.3 G6 (`test_mut26`) | 13 |
| 0.5 NK1 | Before Task 1 (baseline), 13 step 4 |
| 0.5 NK2, NK3 | every task's compile check; 13 step 5 |
| 0.5 NK4 | 9 (NF8, NF9, NF10), 10 (NF9b) |
| 0.5 NK5 | 3 (NF31), 10 (NF28-NF30), 12 (NF24) |
| 0.5 NK6 | 7 (NF12), 13 step 4 |
| 0.5 NK7 | every task's step 4; 13 step 5 |
| 0.5 NK8 | 13 step 6 (hand-off) |
| 2.1 plan.json keys, beat `lines`, `load_plan` | 5 (`cast_notes`), 6 (`spoken_lines`, `lines`, the defaults) |
| 2.2 writer parts, story.md, `story_checks.json` | 8 (the pasted dialogue), 9 (Q1's `parse_violation` shape) |
| QL1 (and GC1's constants) | 2 |
| QL2, QL3, QL4 | 2 |
| QL5 | 3 |
| QL6 | 7 |
| QL7 | 4 (`speaking_coercion`), 6 (the rest) |
| QL8 | 6 |
| QL8b | 10 |
| QL9 | 8 |
| QL10 | 9 |
| QL11 | 11 |
| QL12 | 5 |
| QL13 | 12 |
| QL14 | 9 |
| QL15 interactions | 2 (`required_lines`), 5 (Q2), 7 (the prompt rows), 9 (Q1), 10 (NF32, NF33) |
| SM1, SM2, SM3, SM5 | 4 |
| SM4 | 7 (`SPEAKER_RULE`), 8 (the writer sentences) |
| SP-P1, SP-P2 | 1 |
| SP-P3 (engine assembly unchanged) | 4 (only the chained `k >= 2` camera sentence changes) |
| GC2, GC3, GC4 | 5 |
| 6 rule table | 3 (pre-flight), 4 (N17, the P14 camera note), 5 (P15, Q2, Q3), 6 (P14 line notes, Q1 plan form), 9 (Q1), 10 (P14 "given" note), 12 (patch reasons) |
| 7.1 | 7 |
| 7.2 | 8 |
| 7.3 | 11 |
| 8.1 | 1-12 (see the next table) |
| 8.2 | 2 |
| 8.3 A | 4, 5, 6, 7, 8, 13 |
| 8.3 B, C | the step 4 runs of the owning tasks; 13 steps 4-5 |
| 9 rollout | Before Task 1; 13 (review, test-only re-baseline, NK1, NK8 and the PR note) |

### Test IDs and their owning task (each is owned by exactly one task)

| IDs | Task |
|---|---|
| NF34, NF35 | 1 |
| NF1, NF2, NF3, NF4 | 2 |
| NF5, NF6, NF31 | 3 |
| NF16, NF17, NF19; the 8.3 A edits of DLG11, DLG15, `test_shots_s5_...`, `test_n16_n17_n18_...`, DLG22 | 4 |
| NF22, NF23, NF27, NF36; the `cast_notes` half of the RST39 edit | 5 |
| NF13, NF14, NF26, Review Focus 3; the RST13 edit and the `spoken_lines` half of the RST39 edit | 6 |
| NF12; the DLG12 edit | 7 |
| NF15, NF20; the DLG13 edit | 8 |
| NF7, NF8, NF9, NF10, NF11, Review Focus 1, Review Focus 2 | 9 |
| NF9b, NF28, NF29, NF30, NF32, NF33, NF37, Review Focus 5 | 10 |
| NF25 | 11 |
| NF21, NF24, Review Focus 4 | 12 |
| MUT26 re-baseline; NK1, NK2, NK3, NK6, NK7 measured; NK8 hand-off | 13 |
| NF18 | withdrawn by the spec (revision 2, with R5) |

## Plan decisions (where the spec is silent, conflicts with a pinned test, or needs a reading)

1. **`narrative.txt` is written from the plan, not copied** (Task 2 step 1.2). Its source, `/private/tmp/claude-502/.../scratchpad/hockey/narrative.txt`, lives in a session scratch directory that may be gone when the plan runs. The block is byte-identical to that file, and step 1.7 checks its sha256 (`7801957a...27ca`, recorded from the source). The seven recorded run files are copied with `cp` from `generated/stories/`, which is in the repository checkout, and checked by sha256 too.
2. **Controller ruling: `"Q1"` sits just before `"N19"` in `GENERATION_CHECKS` and `RECHECK_IDS`, not at the end** (Task 9; `test_ca6`'s pin stands). QL10 says "appended", but `test_dialogue.py::test_ca6_n19_cast_reference` asserts `GENERATION_CHECKS[-1] == "N19" and RECHECK_IDS[-1] == "N19"`, and NK6 says every test outside 8.3 A passes unedited. Replayed, appending fails `test_ca6`. The tuples are membership sets (`if "Q1" in ...`), so the position changes no behaviour; `test_dlg17`'s `[16:20]` slices are unchanged either way. Ruled: insert before `"N19"`; Spec amendment 2.
3. **Controller ruling: `build_plan_prompt` loads `character_lib` lazily, only when the narrative quotes spoken lines** (Task 7; `test_rst47` and `test_s53` stay green). QL6 computes `lib.dialogue_word_cap(...)` unconditionally, but `test_rst47_robust_dry_run` and `test_shots_mode.py::test_s53_uncast_shots_dry_run_never_loads_character_lib` pin that an uncast robust dry run never loads `character_lib`. Replayed, the unconditional load fails both. With no lines `@@LINE_WORDS@@` becomes `""`, and the token never appears then, because `@@LINES_RULE@@` is `""` too. Ruled: lazy load; Spec amendment 3.
4. **`_clean_lines` drops a digit string that `int()` cannot read** (Task 6). QL7 keeps every `str` whose `.strip().isdigit()` "converted with `int`", but `"²".isdigit()` is True and `int("²")` raises `ValueError`, which would kill the run with a traceback on a malformed plan reply. Such an item is dropped, like every other unusable item; every input the spec's rule handles gives the same result.
5. **`drop_groups` names, in its P15 note, the beats the id was removed from** (Task 5). GC3 says `where` is `""` "when no beat listed the id". When a kept entry shares the removed id (a duplicate id, already a hard P2), that id is not removed from any beat, so the note names no beat. A beat that lists the id twice is named once.
6. **QL13 step 6 with no contained line:** when the panel's current `Dialogue:` has words but holds no spoken line at all, `min`/`max` of `contained_lines` are undefined; the patch is rejected with the step-6 "never rewritten" reason, because those words are not the narrative's spoken lines (Task 12).
7. **`q1_dialogue_patch` looks up `sid0` with `(c.get("phrase") or "")`**, so a cast entry without a phrase cannot raise.
8. **Test-helper readings.** `_replay(..., assign=True)` adds the QL8b notes to `speech_notes`, as `_Run.go()` does (NF9b asserts the returned notes). NF16 covers an empty shot as well as an empty camera ("plus `""`"). NF19 also checks that a push-in raises no N17. NF24's "seu3" parts are the raw `seu.panel_json` replies. NF35's chained, shots and no_stills story.md texts are written for the test (the spec names the Motion and the expected composition only). The new test file imports `tests/test_dialogue.py` as `dlg` for its manifest helpers and `AC`/`DIALOGUE_FIELD_LINE`; importing a module does not register its autouse fixture, so the file defines its own `story_env`.
9. **Five tests pass before their own task's Step 3** and say so in Step 2: NF10 (Task 9), NF30, NF32, NF33 and Review Focus 5 (Task 10). Each pins a run that the new code must leave exactly as it is (no Q1 to report, no eligible beat, a silent movie, a plan that assigns every line).
10. **The plan.json keys arrive in two tasks**: `cast_notes` in Task 5 and `spoken_lines` in Task 6, so `test_rst39`'s key list is edited in both (each half for its own 8.3 A reason). `plan_checks` reads `plan.get("cast_notes", [])`; the three `load_plan` defaults all land in Task 6 with NF26.
11. **The Q1 call in `panel_checks` sits after the advisory reorder and before the shots block**, which keeps the QL10 order (per-panel hard, then Q1, then S1/S3).
12. **One commit per task** instead of spec 9's single feature commit (the controller's task sizing). `test_mut26` is re-based, in its own test-only commit, to the last commit that touches a `PIPELINE_FILES` entry (Task 12's, or the Step 1 review fix), after the spec 9 step 3 design review (Task 13).
13. **`speaking_coercion` is extracted in Task 4** with the F2 table; Task 6 rewrites the rest of `coerce_speakers` around it.
14. **Controller ruling: the group-speaker note** (Task 6; Spec amendment 1). `normalize_plan` collects the group entries before `drop_groups` removes them and passes them to `coerce_speakers(ctx, plan, groups)`. A raw speaker that is a removed group's id, or its phrase (case-insensitive), gets one note, at the place the "not a cast id" note would have had: `beat %d: P15 group cast: %s is part of the setting, not a speaker; the beat's line goes to %s` when the beat then gets a speaker (its sole remaining cast member, because it has lines), or `...; the beat has no speaker` otherwise. That note replaces both the "not a cast id" note and the "speaker set to" note for that beat. The phrases are written unquoted, as the ruling's format gives them. The QL7 "line(s) %s dropped: the beat has no speaker" note still follows when the beat had lines and no individual remains (it reports the dropped lines, which the P15 note does not). With `--no-narration` the existing "dropped: this movie has no spoken lines" note is unchanged. The NF23 sub-case "a group id given as a speaker gives the existing 'not a cast id' note" is replaced by the same order check with an unknown id (`c9`); Review Focus 3 pins the ruled notes.

## Questions for controller

None. The three questions of the first draft were ruled by the controller (Plan decisions 2, 3 and 14; Spec amendments 1-3).

## Spec amendments

Controller rulings on this plan's questions; amend the spec to match.

1. **The group-speaker note (QL7, GC3, NF23).** GC3's sentence "It runs before `coerce_speakers`, so a group id given as a speaker is reported by the existing note "speaker %s is not a cast id, so nobody speaks in this beat"" is replaced by: when a group cast member was the beat's speaker, the note reads exactly `"beat %d: P15 group cast: %s is part of the setting, not a speaker; the beat's line goes to %s"` (the group phrase, then the new speaker's phrase), and when no individual remains it reads `"beat %d: P15 group cast: %s is part of the setting, not a speaker; the beat has no speaker"`. It takes the place of the "not a cast id" note and, for that beat, of the "speaker set to" note (QL7's pseudo-code: `coerce_speakers(ctx, plan, groups)`, with `groups` the entries `drop_groups` removed). NF23's clause "a group id given as a speaker gives the existing "not a cast id" note" is withdrawn; the plan's Review Focus 3 test pins the new notes.
2. **Q1's position (QL10).** "`"Q1"` is appended to `GENERATION_CHECKS` and `RECHECK_IDS`" reads "`"Q1"` is inserted just before `"N19"` in `GENERATION_CHECKS` and `RECHECK_IDS`" (`test_ca6` pins `"N19"` last).
3. **The plan prompt's `character_lib` load (QL6).** "**Scalar.** `("@@LINE_WORDS@@", str(lib.dialogue_word_cap(engine_seconds(ctx), 2)))`, where `lib = _character_lib(ctx.ws)`" gains: "`lib` is loaded only when `lines` is non-empty; otherwise the scalar is `""`" (an uncast dry run never loads `character_lib`: `test_rst47`, `test_s53`).

## Execution handoff

Plan complete and saved to `qwen-agent-workspace/docs/superpowers/plans/2026-10-26-narrative-dialogue-fidelity.md`. Every Create/Append/Edit/Run block was replayed in order on a scratch worktree of `7aac623`. Each old text occurred exactly once at its turn, and each task's Step 2 run failed (or passed, where Step 2 says so) as its Expected line states. Each task's Step 4 run passed, apart from the known `test_rst62_import_sets`. Every changed file compiled under Python 3.9.6 and 3.13. After Task 12, `tests/test_narrative_fidelity.py` (42 passed), `test_dialogue.py`, `test_story_engine.py`, `test_shots_mode.py`, `test_casting_regression.py`, `test_judge_story.py`, `test_character_lib.py`, `test_ltx_story_manifest_chain.py`, `test_casting_pipeline.py`, `test_lora_catalog.py`, `test_iterate_story.py`, `test_ltx_movie_iterate_flags.py`, `test_ltx_story_images.py`, `test_ltx_story_video.py`, `test_action_compose.py` and `test_movie_ui_builder.py -k "not mut26"` passed, and `tests/test_ltx_movie_offline.py` printed `OK 347/347`. Task 13's re-baseline script was dry-run on a dummy SHA. The full suite was not run; it is Task 13 Step 4. Please review the plan. Which execution approach would you prefer?

- **Subagent-driven**: a fresh subagent implements each task and a fresh reviewer checks it before the next one starts, then a whole-branch review at the end.
- **Native**: one session implements every task, then one fresh reviewer checks the whole branch.

For this plan I recommend **subagent-driven**. Its 13 tasks hand exact interfaces forward: `speaking_coercion` (Task 4) is called from Tasks 6, 10 and 12, and the `lines`/`spoken_lines` shape of Task 6 feeds every later task. A mistake that ships costs live GPU render time in the NK8 reruns.
