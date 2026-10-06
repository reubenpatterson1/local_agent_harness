# bin/judge-clips Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `bin/judge-clips`, a hand-run, observe-only tool for loop Phase 4. It finds a story's rendered `clips/panel_NN.mp4` files and pairs each with the `manifest.json` panel whose `index` equals its number. It samples 4 frames per clip with ffmpeg and sends every frame, with each panel's Opening still:/Motion:/Narration: text, to Claude in one request. It writes the returned scores and a panel-specific critique to `clips_judgment.json`:
- per clip: `motion_fidelity`, `physical_realism`, `temporal_stability`;
- per movie: `narrative_clarity`, plus `seam_continuity` only when 2 or more clips are judged.

**Architecture:** One standalone executable Python script, `bin/judge-clips`, modeled on the shipped `bin/judge-stills`:
- no file extension; `main(argv=None) -> int`;
- no imports from other `bin/*` files;
- `__main__` wired through `pipeline_log.run_logged("judge-clips", ...)`.

`main` runs these steps in order:
1. Filesystem and manifest preconditions (exit 2).
2. The ffmpeg/ffprobe PATH check (exit 2).
3. The env-key gate (exit 1).
4. For each clip, one `ffprobe` call and one `ffmpeg` extraction into a `tempfile.TemporaryDirectory`.
5. At most two non-streaming `messages.create` calls, carrying interleaved panel-text, frame-label, and base64 JPEG blocks. There is one retry, and only when no tool call comes back.
6. jsonschema validation, plus the panel-set and two-way `seam_continuity` checks.
7. The output file and the stdout table.

**Tech Stack:** Python 3.13.0 (`/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`), `anthropic` 0.116.0, `jsonschema` 4.23.0, `httpx` 0.28.1 (tests only, to build an `APIConnectionError`), `pytest` 8.3.4, and ffmpeg/ffprobe 9.0.1 at `/opt/homebrew/bin`. The encoders used are `libx264` (test fixtures) and `mjpeg` (frames).
**Spec:** docs/superpowers/specs/2026-10-04-judge-clips-design.md (committed a4dadc2). The user ruled on spec Section 8, and these rulings are not to be reopened:
- G1: keep the 25-clip cap and the E5 wording as written.
- G2: accept schema-2 manifests as written.
- G3: accepted as a known limitation.

**How this plan was validated:** On 2026-10-04, every code block below was assembled task by task in a scratch copy outside the repo (`/tmp/jcplan`, with `pipeline_log.py` copied in). Each block was run there and spliced into this document byte-for-byte. Every "Expected:" count, failure message, mutation catch, and smoke-test result in this plan was observed in that copy, not predicted. The live gates L1/L2 were rehearsed offline: real test_story1 and final_e2e_verify clips, with a fake client, through `pipeline_log.run_logged`.

## Global Constraints

**Workspace and scope**
- Workspace root `WS` = `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/`. Run every command in this plan from `WS`. The git repo root is one level up, so `git diff --name-only` prints paths with the `qwen-agent-workspace/` prefix.
- Exactly two files are created: `bin/judge-clips` (`chmod +x`) and `tests/test_judge_clips.py`. No other file is created or modified (spec 0.3). Specifically untouched: `bin/judge-stills`, `pipeline_log.py`, `tests/test_pipeline_log.py`, `bin/ltx-movie`, and the deploy package (`scripts/deploy/build_pkg.py`, `tests/test_deploy_pkg.py`). The tool is not added to the deploy package, so the dual-interpreter gate does not apply (spec 0.4, 7.5).

**Script conventions (spec 1.1)**
- Shebang `#!/usr/bin/env python3`, module docstring first, no extension, executable bit set.
- Imports in this order: `argparse`, `base64`, `datetime`, `fractions`, `json`, `os`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`; a blank line; then `anthropic` and `jsonschema`. Use `import fractions` and `fractions.Fraction`, never `from fractions import Fraction`.
- Then exactly `WS = ...`, `sys.path.insert(0, WS)`, `import pipeline_log  # noqa: E402`.
- `def main(argv=None):` returns an `int`. The file ends with spec 1.1's `_pipeline_log_story_dir` plus `sys.exit(pipeline_log.run_logged("judge-clips", ...))`.

**Verbatim rule**
- Every Python block in these spec sections appears in `bin/judge-clips` verbatim, paragraph by paragraph: 1.1, 1.4, 2.1, 2.2, 3.1, 3.2, 3.4-3.9, 4.1, 4.3-4.6, 5.2, 5.3. This plan keeps `main`'s comments exactly as the spec wrote them, even though spec 1.4 allows rewording.
- The spec 7.1 helper blocks appear verbatim in the test file.
- Each task runs a "spec transcription check" that extracts those blocks from the spec file itself, so a paraphrase cannot pass. A negative control was run: changing "you receive no audio" to "you get no audio" made the check exit 1.

**Constants**
- `MODEL = "claude-opus-5-5"`; `EFFORT = "high"`; `MAX_TOKENS = 21333`; `TOOL_NAME = "submit_judgment"`.
- `FRAMES_PER_CLIP = 4`; `MAX_CLIPS = 25`; `MEDIA_TYPE = "image/jpeg"`.
- `CLIP_NAME_RE = re.compile(r"panel_(\d{2,})\.mp4")`, used with `fullmatch` over `os.listdir`, never `glob`.
- `CLIP_SCORE_KEYS = ("motion_fidelity", "physical_realism", "temporal_stability")`; `MOVIE_SCORE_KEYS = ("seam_continuity", "narrative_clarity")`; `CLIP_TABLE_FORMAT = "  %-5s  %-16s  %-16s  %s"`.

**Judging request**
- `thinking={"type": "adaptive"}`, `output_config={"effort": "high"}`, `tool_choice={"type": "auto"}`, exactly one tool, `system=SYSTEM_PROMPT`.
- Never `budget_tokens`. No `temperature`/`top_k`/`top_p`, no streaming, no `timeout=`. The SDK's default `max_retries` (2) is left unchanged (spec G5).

**API key**
- Read only via `os.environ.get("ANTHROPIC_API_KEY")`. `None` and `""` both count as unset.
- Checked after every exit-2 check, and before any ffprobe/ffmpeg run and before `anthropic.Anthropic()`. That constructor is called with no arguments.
- The key is never assigned, printed, logged, or written.

**Subprocesses**
- Every `subprocess.run` passes `capture_output=True, encoding="utf-8", errors="replace"`.
- No timeout.
- `ffprobe`/`ffmpeg` are invoked by bare name, resolved through `PATH`.

**API calls and validation**
- At most two API calls per run. The single retry happens only when no `submit_judgment` tool_use block comes back. It re-sends the same `user_content` list (every frame) and passes `r1.content` back unmodified. A validation failure is never retried.
- `validate_judgment_input(tool_input, panels)` takes the list of judged clip numbers. Its checks run in this order: schema, duplicates, missing, extra, seam required (2 or more clips), seam rejected (fewer than 2). Every failure is a `jsonschema.ValidationError`.

**Exit codes and messages (spec 6)**
- Exit codes: 0 success; 1 for E14-E18; 2 for E1-E13. Every message goes to stderr and starts with `Error: `.
- `Error: clips directory not found: <clips_dir>` (E2)
- `Error: no panel_NN.mp4 clips found in <clips_dir>` (E3)
- `Error: more than one clip for panel <N> in <clips_dir>: <name>, <name>` (E4)
- `Error: <count> clips found in <clips_dir>; judge-clips sends 4 frames per clip in one request and judges at most 25 clips (100 images, the Anthropic API's per-request image limit for 200k-context models).` (E5)
- `Error: manifest.json not found: <manifest_path>` (E6)
- `Error: manifest.json is not valid JSON: <manifest_path>: <exception text>` (E7)
- `Error: manifest.json has no panels list: <manifest_path>` (E8)
- `Error: manifest.json panel entry <position> has no integer index: <manifest_path>` (E9)
- `Error: manifest.json lists panel index <N> more than once: <manifest_path>` (E10)
- `Error: clips with no matching panel in manifest.json: <name>, <name>; the clips in <clips_dir> may be stale relative to manifest.json.` (E11)
- `Error: manifest.json panels with no rendered clip in <clips_dir>: <N>, <N>; judge-clips judges only complete renders.` (E12)
- `Error: <tool> not found on PATH; judge-clips needs ffmpeg and ffprobe to extract frames.` (E13)
- `Error: ANTHROPIC_API_KEY is not set; export it in your environment to run judge-clips.` (E14)
- `Error: frame extraction failed: <detail>` (E15)
- `Error: Anthropic API call failed: <type(e).__name__>: <str(e)>` (E16)
- `Error: Claude did not call submit_judgment after one retry; raw responses written to <raw_path>` (E17)
- `Error: submit_judgment input failed schema validation: <ValidationError.message>` (E18)
- Exceptions outside the spec 6 table are not caught and propagate as tracebacks. Examples: an `OSError` opening the manifest for a reason other than absence, and an `OSError` writing an output file.

**Outputs (spec 2.4, 5)**
- `clips_judgment.json` is written with `json.dump(obj, f, indent=2, ensure_ascii=False)` plus a trailing `"\n"`.
  - Key order: `story_id, model, effort, timestamp, frames_per_clip, usage, clips, movie, critique`.
  - `clips` is sorted by panel. Each entry's key order is `panel, frames, motion_fidelity, physical_realism, temporal_stability`, and every number goes through `int(...)`.
  - `movie.seam_continuity` is JSON `null` exactly when 1 clip was judged.
  - `usage.thinking_tokens` is JSON `null` when no response reports it.
- `clips_judgment.raw.json` is written on E17/E18 only.
- Both files are overwritten without a prompt and nothing is ever deleted. Nothing is written into `clips/`; frames exist only in the `judge-clips-*` temporary directory, which is removed on success and on failure.
- Stdout is used on success only, exactly as spec 5.3 formalizes.

**Tests**
- pytest with plain `assert` statements, never a `check()` helper. Exactly **55** test functions, one per spec test ID:
  - T1a T1b T2 T3 T4a T4b T5 T6 T7 T8a T8b T8c T9a T9b T9c T10a T10b T10c T10d
  - T11a T11b T11c T11d T11e T11f T12 T13
  - T14a T14b T14c T14d T14e T14f T14g T14h T14i T14j T14k T14l T14m T14n T14o
  - T15 T16 T17 T18 T19 T20 T21a T21b T21c T22 T23 T24 T25
- Multi-case IDs loop inside one function. Extra coverage goes in as extra assertions inside those 55 functions, never as new functions.
- No network: an autouse fixture makes constructing the real client fail the test.
- Real ffmpeg/ffprobe, no `pytest.skip` or `importorskip` anywhere.
- Every `main()` fixture lives under `tmp_path`, with `judge_clips.WS` monkeypatched to it.

**Test-run output**
- Pytest prints one `DeprecationWarning` for `SourceFileLoader.load_module()`, so every passing run of `tests/test_judge_clips.py` ends `N passed, 1 warning`.
- On startup it also prints a `pytest_asyncio` `PytestDeprecationWarning` about `asyncio_default_fixture_loop_scope`.
- Neither is a failure.

**Regression baselines** (measured 2026-10-04 at a4dadc2, before any change)

| Command | Last line |
|---|---|
| `python3 -m pytest tests/test_judge_stills.py -q --color=no` | `32 passed, 1 warning` |
| `python3 -m pytest tests/test_judge_story.py -q --color=no` | `19 passed, 1 warning` |
| `python3 -m pytest tests/test_iterate_story.py -q --color=no` | `17 passed, 1 warning` |
| `python3 -m pytest tests/test_pipeline_log.py -q --color=no` | `17 passed, 4 warnings` |

**Mutation runners**
- Each mutated run is `python3 -m pytest -q --color=no -p no:cacheprovider tests/test_judge_clips.py::<name>`, and the verdict comes from the return code alone:
  - 1 = CAUGHT;
  - 0 = survived;
  - anything else (2 collection error, 4 usage error, 5 no tests collected) means a broken mutation or a mistyped test name, and it fails the script.
- Before mutating, every runner asserts each named test passes on the unmutated file (control) and asserts each anchor's exact occurrence count. It restores the file in `finally`.
- Each pytest run gets a fresh `PYTHONPYCACHEPREFIX` and a fresh `TMPDIR` under a `jc-mut-*` directory, which is removed after the run. Do not remove either:
  - a same-size mutation written in the same second as an earlier compile can otherwise load a stale `.pyc` and falsely survive;
  - the `mkdtemp` mutation would otherwise leave `judge-clips-*` directories in the real `$TMPDIR`, which live gate L1 checks.
- Never decide a pass or fail from `$?` after a pipe to `tail`, because that is `tail`'s status.

**Commits**
- The working tree has unrelated modified and untracked files. Stage only by explicit path. Before each commit, confirm that `git diff --cached --name-only` lists only that task's two files.
- Commit messages start with `judge-clips: ` and end with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Do not push. Pushing is gated by a design review.

## Decisions this plan makes where the spec is silent or inexact

These were decided while writing the plan and verified in the scratch copy. Do not re-decide them.

1. **Clip/panel pairing (spec 3.3) lands in Task 5, not Task 2.** E11/E12 have no function of their own. They are lines in `main` (spec 1.4), and their tests (T14k, T14l, T14o) are `main()` tests that need the T14 harness. Task 2 delivers what pairing consumes: `find_clips` and `load_manifest_panels`, pinned by T3 and T5.
2. **Spec 7.4 row "`-fps_mode passthrough` removed -> T10a, T10b, T10c" is wrong about T10b.** Without passthrough, ffmpeg duplicates frames only to fill timestamp gaps. T10b's clip3 selects the consecutive indices 0, 1, 2, and clip1 selects index 0, so there are no gaps: 3 and 1 files are written (observed), and T10b passes. The catchers used are T10a (31 files observed), T10c (argv), and T17 (`main` hits the file-count ClipError).
3. **Spec 7.4 row "`MAX_CLIPS` changed to 26, or `>` changed to `>=` -> T14d, T14e" is two mutations.** Each change is caught by exactly one of the two tests: 26 is caught by T14d; `>=` is caught by T14e. Final acceptance therefore runs 45 mutations for the spec's 44 rows.
4. **"Dedup removed" is defined as `unique = sorted(set(indices))` -> `unique = sorted(indices)`.** That builds the select string and the expected file count from the repeated list, which is the only form under which the spec's named catcher T10b (3 files for 4 expected) holds. A select-line-only edit is caught by T10c alone. T17 also catches the defined form.
5. **Extra assertions inside spec IDs.** These pin spec 1.1 "every subprocess call captures its output" and spec 3.8's label wording:
   - T9c and T10c also assert the recorded `subprocess.run` kwargs equal `{"capture_output": True, "encoding": "utf-8", "errors": "replace"}`.
   - T8a also asserts the literal first label.
   - T25 also asserts `seam_continuity is None`.
   - T12 (c) uses entries for panels 1, 2, 3, so the extra-panel check is reached.
6. **`_create_message` and `_write_raw` are spec 4.1's and 5.2's code blocks exactly, with no docstrings.** Spec 1.3 says "identical to judge-stills", whose versions carry a docstring and one comment. Behavior is identical, and the transcription check enforces the blocks. `find_tool_use` is copied from `bin/judge-stills`, docstring included (the spec shows no block for it).
7. **Test-helper names and details the spec leaves open:**
   - `_dummy(n)`, `_run_precondition(...)` (the T14 harness), `_fake_run(...)` (the subprocess recorder), `CAPTURE_KWARGS`, `_clip_input(...)`, `TWO_CLIP_STDOUT`, `_REAL_TEMPORARY_DIRECTORY`.
   - `_no_tempdir` raises `AssertionError("temporary directory created")`.
   - `_make_story`'s int clip specs are copied with `shutil.copyfile`.
8. **Module docstring and code comments** are fixed text given below, written within spec 1.1's required content. **Placement:** `CLIP_TABLE_FORMAT` sits with `format_clip_row` (the spec 5.3 block, kept intact), and there are two blank lines between `SUBMIT_JUDGMENT_SCHEMA` and `SYSTEM_PROMPT`.

## Review Focus

1. **The sampled frames must be the right frames.** These are the failure modes:
   - an index past the end of the clip is silently skipped;
   - a repeated `select` term yields one file, not two;
   - dropping `-fps_mode passthrough` makes ffmpeg write 191 files for a real clip;
   - floor instead of round, or `n` instead of `n - 1`, shifts the indices;
   - taking the frame count from the container header (`nb_frames`) instead of the decoder (`-count_frames nb_read_frames`).

   Each must be caught before a wrong frame reaches the judge. Tests: T4a, T4b, T9a-T9c, and T10a-T10d (Task 3), which use a luma-encoded frame-number oracle on real ffmpeg output; T17 (Task 6), which decodes every sent image back to its frame number and checks the 24-fps `t=` labels against the manifest's deliberately wrong 30 fps.
2. **Clip/manifest mismatch must be refused before any subprocess or API work.** Cases: a partial render (`mlxdemo`, `mystorytest2`), a stale extra clip, `panel_01.mp4` plus `panel_001.mp4`, more than 25 clips, and a malformed manifest (bad JSON, non-UTF-8, no panels list, a missing/str/bool index, a duplicate index). Each must exit 2 with its exact message, write nothing, and never construct a client. Order matters: E11 before E12, and ffmpeg checked before ffprobe. Tests: T3, T5 (Task 2); T14a-T14o (Task 5); live gate L3 / smoke S1 (Final acceptance).
3. **The single-clip case (`final_e2e_verify`, and any 1-panel story).** `seam_continuity` must come out as JSON `null` and `n/a (only 1 clip)`: never fabricated, never a `KeyError`, never `"%d" % None`. Validation is two-way: a 2-clip judgment without seam fails E18, and a 1-clip judgment with seam fails E18. Tests: T13 (Task 1); T8b (Task 4); T18, T21c (Task 6); live gate L2.
4. **Claude answers in prose, or returns a malformed or partial judgment.** Requirements:
   - exactly one retry, re-sending all 19 blocks and `r1.content` with its thinking signature;
   - a double failure writes a raw dump and exits 1;
   - schema, duplicate, missing, and extra panel failures exit 1 with no retry;
   - float scores are written as integers, and `clips` is sorted by panel.

   Tests: T11a-T11f, T12, T13 (Task 1); T17, T21a-T21c, T25 (Task 6); T19, T20 (Task 7).
5. **Environment failures, temp-dir hygiene, and key leakage.** Cases: an unset/empty key, missing ffmpeg/ffprobe, a garbage clip, and an API error on either call. Each must exit with one `Error:` line and no traceback. The temp directory must be gone afterwards, `clips/` must be untouched, no client may be constructed when the key is missing, and the key must never appear in any output. Tests: T14n, T15 (Task 5); T16, T17 (Task 6); T22, T23 (Task 7).

These are not covered by any test (spec 9), and only live runs can reveal them:
- a manifest `num_frames` that disagrees with the decoded count;
- VFR or cover-art streams;
- request size at the 25-clip cap;
- same-numbered stale clips;
- whether the real model omits `seam_continuity` for 1 clip (L2).

## Task map

| Task | Adds | New tests | Cumulative | bin/judge-clips lines | test file lines |
|---|---|---|---|---|---|
| 1 | Skeleton, constants, schema, `_panel_list`, `validate_judgment_input` | T11a-T11f, T12, T13 (8) | 8 | 137 | 177 |
| 2 | `ManifestError`, `find_clips`, `load_manifest_panels` | T3, T5 (2) | 10 | 178 | 220 |
| 3 | `ClipError`, `_stderr_tail`, `probe_clip`, `frame_indices`, `extract_frames` | T4a, T4b, T9a-T9c, T10a-T10d (9) | 19 | 251 | 411 |
| 4 | Prompt texts, `_text_field`, `format_panel_text`, `format_frame_label`, `build_user_content` | T6, T7, T8a-T8c (5) | 24 | 382 | 497 |
| 5 | `build_parser`, `resolve_paths`, interim `main` (steps 1-12), pipeline_log wiring | T1a, T1b, T2, T14a-T14o, T15, T24 (20) | 44 | 468 | 798 |
| 6 | Frame extraction in `main`, judging call, validation path, output, stdout | T16, T17, T18, T21a-T21c, T25 (7) | 51 | 602 | 1080 |
| 7 | Retry, double failure, API errors | T19, T20, T22, T23 (4) | 55 | 622 | 1195 |

Each test lands in the task that introduces the code it exercises, so each new test is red before that task's implementation step and green after it. That was observed for all 55 in the scratch copy.

---

### Task 1: Script skeleton, constants, submit_judgment schema, and validate_judgment_input

**Files:**
- Create: `bin/judge-clips` (137 lines at the end of this task), then `chmod +x`.
- Test: create `tests/test_judge_clips.py` (177 lines at the end of this task).

**Interfaces:**
- Consumes: `pipeline_log.py` (exists at `WS`, unchanged; imported only).
- Produces, in `bin/judge-clips`:
  - module globals `WS`, `MODEL`, `EFFORT`, `MAX_TOKENS`, `TOOL_NAME`, `FRAMES_PER_CLIP`, `MAX_CLIPS`, `MEDIA_TYPE`, `CLIP_NAME_RE`, `CLIP_SCORE_KEYS`, `MOVIE_SCORE_KEYS`, and `SUBMIT_JUDGMENT_SCHEMA` (dict);
  - `_panel_list(panels) -> str`;
  - `validate_judgment_input(tool_input, panels) -> None`, which raises `jsonschema.ValidationError`.
  - Two lines serve as edit anchors for Task 4: `TOOL_NAME = "submit_judgment"` (Task 4 inserts `TOOL_DESCRIPTION` after it) and `def _panel_list(panels):` (Task 4 inserts the prompt texts before it).
- Produces, in `tests/test_judge_clips.py`:
  - every import used by later tasks;
  - module globals `WS`, `_SCRIPT_PATH`, `judge_clips`, `SENTINEL_KEY`, `STORY_ID`, `VALID_INPUT`, `ONE_CLIP_INPUT`;
  - the autouse fixture `_no_real_client`.

  Every later task appends to this file and relies on these names.

- [ ] **Step 1: Write the failing test**

Create `tests/test_judge_clips.py` with exactly this content. The imports `base64`, `fractions`, `json`, `re`, `shutil`, `subprocess`, `tempfile`, `types`, `uuid`, `anthropic`, and `httpx` are used by tests that Tasks 2-7 append. They are included now so later tasks only append.

```python
"""Tests for bin/judge-clips.

Spec: docs/superpowers/specs/2026-10-04-judge-clips-design.md (Section 7).
Run from the workspace root: python3 -m pytest tests/test_judge_clips.py -v

Plain pytest asserts only -- no check() helper, which reports false greens under
pytest. No test makes a network call: the autouse fixture below makes constructing
the real anthropic.Anthropic client fail the test, and every test that reaches the
API installs a recording fake first. Real ffmpeg and ffprobe run on small synthetic
clips (no skips: a missing ffmpeg, ffprobe, or libx264 errors the tests loudly).
Story fixtures live under tmp_path with judge_clips.WS patched to it; nothing is
written to the real generated/ tree. Exactly one test function per spec test ID
(55 total); multi-case IDs loop inside their function.
"""

import base64
import copy
import fractions
import importlib.machinery
import json
import os
import re
import shutil
import subprocess
import tempfile
import types
import uuid

import anthropic
import httpx
import jsonschema
import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
_SCRIPT_PATH = os.path.join(WS, "bin", "judge-clips")
judge_clips = importlib.machinery.SourceFileLoader("judge_clips", _SCRIPT_PATH).load_module()

SENTINEL_KEY = "sk-test-SENTINEL-do-not-leak"
STORY_ID = "clips-test"

# Deliberately in reverse panel order, with distinct values per score, and a non-ASCII
# dash (checks ensure_ascii=False in the written JSON) (spec 7.1).
VALID_INPUT = {
    "clips": [
        {"panel": 2, "motion_fidelity": 4, "physical_realism": 3, "temporal_stability": 5},
        {"panel": 1, "motion_fidelity": 7, "physical_realism": 6, "temporal_stability": 8}],
    "movie": {"seam_continuity": 9, "narrative_clarity": 2},
    "critique": "Panel 1 holds the dawn light; Panel 2's horse melts by frame 3 — fix it.",
}
ONE_CLIP_INPUT = {
    "clips": [{"panel": 1, "motion_fidelity": 7, "physical_realism": 6, "temporal_stability": 8}],
    "movie": {"narrative_clarity": 2},
    "critique": VALID_INPUT["critique"],
}


@pytest.fixture(autouse=True)
def _no_real_client(monkeypatch):
    """SC8 guard for every test: constructing the real client fails the test, and the
    key starts unset. Tests that reach the API install a recording fake over this."""
    def _forbidden(*args, **kwargs):
        raise AssertionError("test constructed a real anthropic.Anthropic client")
    monkeypatch.setattr(judge_clips.anthropic, "Anthropic", _forbidden)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


# --- T11-T13: submit_judgment validation (spec 4.3, 4.4) -----------------------------

def test_t11a_missing_top_level_key_rejected():
    for key in ("clips", "movie", "critique"):
        payload = copy.deepcopy(VALID_INPUT)
        del payload[key]
        with pytest.raises(jsonschema.ValidationError):
            judge_clips.validate_judgment_input(payload, [1, 2])


def test_t11b_missing_clip_entry_key_rejected():
    for key in ("panel", "motion_fidelity", "physical_realism", "temporal_stability"):
        payload = copy.deepcopy(VALID_INPUT)
        del payload["clips"][1][key]           # clips[1] is the panel-1 entry
        with pytest.raises(jsonschema.ValidationError):
            judge_clips.validate_judgment_input(payload, [1, 2])


def test_t11c_out_of_range_or_non_integer_score_rejected():
    # 0 and 11 are the range cases; "7", 7.5 and True pin "non-integer score"
    # (jsonschema does not count booleans as integers).
    for bad in (0, 11, "7", 7.5, True):
        for key in ("motion_fidelity", "physical_realism", "temporal_stability"):
            payload = copy.deepcopy(VALID_INPUT)
            payload["clips"][1][key] = bad
            with pytest.raises(jsonschema.ValidationError):
                judge_clips.validate_judgment_input(payload, [1, 2])
        for key in ("seam_continuity", "narrative_clarity"):
            payload = copy.deepcopy(VALID_INPUT)
            payload["movie"][key] = bad
            with pytest.raises(jsonschema.ValidationError):
                judge_clips.validate_judgment_input(payload, [1, 2])


def test_t11d_non_integer_panel_rejected():
    for bad in ("1", True, 1.5, None):
        payload = copy.deepcopy(VALID_INPUT)
        payload["clips"][1]["panel"] = bad
        with pytest.raises(jsonschema.ValidationError):
            judge_clips.validate_judgment_input(payload, [1, 2])


def test_t11e_valid_payloads_accepted():
    for value in (1, 10):
        payload = copy.deepcopy(VALID_INPUT)
        for entry in payload["clips"]:
            for key in ("motion_fidelity", "physical_realism", "temporal_stability"):
                entry[key] = value
        payload["movie"] = {"seam_continuity": value, "narrative_clarity": value}
        assert judge_clips.validate_judgment_input(payload, [1, 2]) is None
    # No additionalProperties constraint: extra keys are tolerated (spec 4.3).
    payload = copy.deepcopy(VALID_INPUT)
    payload["extra"] = "ignored"
    payload["clips"][0]["extra_score"] = 99
    payload["movie"]["extra_movie_score"] = 99
    assert judge_clips.validate_judgment_input(payload, [1, 2]) is None
    # jsonschema accepts 7.0 as an integer; 1.0/2.0 equal 1/2 in the panel-set checks.
    payload = copy.deepcopy(VALID_INPUT)
    payload["clips"][0]["panel"] = 2.0
    payload["clips"][1]["panel"] = 1.0
    for entry in payload["clips"]:
        for key in ("motion_fidelity", "physical_realism", "temporal_stability"):
            entry[key] = 7.0
    payload["movie"] = {"seam_continuity": 7.0, "narrative_clarity": 7.0}
    assert judge_clips.validate_judgment_input(payload, [1, 2]) is None


def test_t11f_missing_narrative_clarity_rejected():
    payload = copy.deepcopy(VALID_INPUT)
    del payload["movie"]["narrative_clarity"]
    with pytest.raises(jsonschema.ValidationError):
        judge_clips.validate_judgment_input(payload, [1, 2])
    payload = copy.deepcopy(ONE_CLIP_INPUT)
    del payload["movie"]["narrative_clarity"]
    with pytest.raises(jsonschema.ValidationError):
        judge_clips.validate_judgment_input(payload, [1])


def test_t12_panel_set_rules():
    panel_1 = VALID_INPUT["clips"][1]
    panel_3 = dict(panel_1, panel=3)
    cases = [
        # (a) two entries for panel 1, none for 2: the duplicate check precedes the
        # missing check.
        ([panel_1, panel_1], "clips lists these panels more than once: 1"),
        ([panel_1], "clips is missing these judged panels: 2"),                    # (b)
        ([panel_1, VALID_INPUT["clips"][0], panel_3],
         "clips includes panels that were not judged: 3"),                        # (c)
        ([panel_1, panel_1, panel_3], "clips lists these panels more than once: 1"),  # (d)
    ]
    for clips, message in cases:
        payload = copy.deepcopy(VALID_INPUT)
        payload["clips"] = copy.deepcopy(clips)
        with pytest.raises(jsonschema.ValidationError) as exc:
            judge_clips.validate_judgment_input(payload, [1, 2])
        assert exc.value.message == message


def test_t13_seam_two_way_rule():
    payload = copy.deepcopy(VALID_INPUT)
    del payload["movie"]["seam_continuity"]
    with pytest.raises(jsonschema.ValidationError) as exc:
        judge_clips.validate_judgment_input(payload, [1, 2])
    assert exc.value.message == "seam_continuity is required when judging 2 or more clips"
    payload = copy.deepcopy(ONE_CLIP_INPUT)
    payload["movie"]["seam_continuity"] = 5
    with pytest.raises(jsonschema.ValidationError) as exc:
        judge_clips.validate_judgment_input(payload, [1])
    assert exc.value.message == "seam_continuity must be omitted when judging fewer than 2 clips"
    assert judge_clips.validate_judgment_input(copy.deepcopy(ONE_CLIP_INPUT), [1]) is None
    assert judge_clips.validate_judgment_input(copy.deepcopy(VALID_INPUT), [1, 2]) is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_clips.py -v --color=no; echo "rc=$?"
```
Expected: the collection error `ERROR tests/test_judge_clips.py - FileNotFoundError: [Errno 2] No such file or directory: '/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/bin/judge-clips'`, then `Interrupted: 1 error during collection`, then `rc=2`.

- [ ] **Step 3: Write minimal implementation**

Create `bin/judge-clips` with exactly this content, then make it executable. The docstring and comments are this plan's fixed text. `SUBMIT_JUDGMENT_SCHEMA` is spec 4.3 verbatim, and `validate_judgment_input` is spec 4.4 verbatim.

```python
#!/usr/bin/env python3
"""judge-clips -- judge a story's rendered panel clips with Claude against the manifest text.

Loop Phase 4 of the story-pipeline self-improvement loop
(docs/superpowers/specs/2026-10-04-judge-clips-design.md). Observational only:
it finds every clips/panel_NN.mp4 rendered under generated/stories/<id>/, pairs
each clip with the manifest.json panel whose index equals its number, samples 4
frames from each clip with ffmpeg (the first frame, two evenly spaced middle
frames, and the last frame), and sends every frame, with each panel's Motion:
and Narration: text (and panel 1's Opening still: text), to Claude in one
request (adaptive thinking, high effort). Claude calls the submit_judgment tool
with 1-10 scores per clip for motion_fidelity, physical_realism, and
temporal_stability; 1-10 movie scores for narrative_clarity and, when 2 or more
clips are judged, seam_continuity; and a critique naming specific panels. The
tool writes clips_judgment.json to the story directory and prints the scores and
critique. It never regenerates anything. Audio is not judged: the API takes no
audio input.

Usage:
  bin/judge-clips --story-id <id>    # generated/stories/<id>/clips/ + manifest.json

Requires ANTHROPIC_API_KEY in the environment, and ffmpeg and ffprobe on PATH.
Exit codes: 0 success, 1 runtime or API failure, 2 argument or precondition
failure. If Claude never calls submit_judgment (after one retry) or its input
fails validation, the raw API responses are written to clips_judgment.raw.json
and no scores are reported.
"""

import argparse
import base64
import datetime
import fractions
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import anthropic
import jsonschema

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
import pipeline_log  # noqa: E402

MODEL = "claude-opus-5-5"
EFFORT = "high"
# Same value and rationale as bin/judge-stills: the SDK's largest non-streaming
# max_tokens without an explicit timeout= (spec 1.3).
MAX_TOKENS = 21333
TOOL_NAME = "submit_judgment"

# Frames sampled from every clip (spec 3.5), and the most clips one run judges:
# 25 clips x 4 frames = 100 images (spec 0.2, G1).
FRAMES_PER_CLIP = 4
MAX_CLIPS = 25

# ffmpeg writes every sampled frame as a JPEG (spec 3.6).
MEDIA_TYPE = "image/jpeg"

# Clip filenames: two or more digits, as bin/ltx-mlx-render's "panel_%02d.mp4" % i
# writes them. Matched with fullmatch over os.listdir, never glob (spec 3.1).
CLIP_NAME_RE = re.compile(r"panel_(\d{2,})\.mp4")

# Output order of the scores in clips_judgment.json and on stdout (spec 5.1, 5.3).
CLIP_SCORE_KEYS = ("motion_fidelity", "physical_realism", "temporal_stability")
MOVIE_SCORE_KEYS = ("seam_continuity", "narrative_clarity")

# seam_continuity is deliberately NOT in movie.required: it is required when 2 or more
# clips are judged and must be absent for 1, which this schema does not express, so
# validate_judgment_input enforces both directions (spec 4.3, 4.4).
SUBMIT_JUDGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "description": "Exactly one entry per clip judged.",
            "items": {
                "type": "object",
                "properties": {
                    "panel": {"type": "integer",
                              "description": "The clip's panel number as an integer, e.g. 3."},
                    "motion_fidelity": {"type": "integer", "minimum": 1, "maximum": 10},
                    "physical_realism": {"type": "integer", "minimum": 1, "maximum": 10},
                    "temporal_stability": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["panel", "motion_fidelity", "physical_realism",
                             "temporal_stability"],
            },
        },
        "movie": {
            "type": "object",
            "properties": {
                "seam_continuity": {"type": "integer", "minimum": 1, "maximum": 10},
                "narrative_clarity": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["narrative_clarity"],
        },
        "critique": {
            "type": "string",
            "description": "Free-text critique. Name specific panels by number (e.g. 'Panel 3').",
        },
    },
    "required": ["clips", "movie", "critique"],
}


def _panel_list(panels):
    """Panel numbers joined as "1, 2, 4" for messages (spec 1.3)."""
    return ", ".join(str(p) for p in panels)


def validate_judgment_input(tool_input, panels):
    """Raise jsonschema.ValidationError unless tool_input is a complete judgment of exactly
    the judged panels (spec 4.4). panels is the list of judged clip numbers."""
    jsonschema.validate(instance=tool_input, schema=SUBMIT_JUDGMENT_SCHEMA)
    submitted = [entry["panel"] for entry in tool_input["clips"]]
    duplicates = sorted({p for p in submitted if submitted.count(p) > 1})
    if duplicates:
        raise jsonschema.ValidationError(
            "clips lists these panels more than once: %s" % _panel_list(duplicates))
    missing = sorted(set(panels) - set(submitted))
    if missing:
        raise jsonschema.ValidationError(
            "clips is missing these judged panels: %s" % _panel_list(missing))
    extra = sorted(set(submitted) - set(panels))
    if extra:
        raise jsonschema.ValidationError(
            "clips includes panels that were not judged: %s" % _panel_list(extra))
    if len(panels) >= 2 and "seam_continuity" not in tool_input["movie"]:
        raise jsonschema.ValidationError(
            "seam_continuity is required when judging 2 or more clips")
    if len(panels) < 2 and "seam_continuity" in tool_input["movie"]:
        raise jsonschema.ValidationError(
            "seam_continuity must be omitted when judging fewer than 2 clips")
```

```bash
chmod +x /Users/reubenpatterson/local_model_harness/qwen-agent-workspace/bin/judge-clips
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_clips.py -q --color=no; echo "rc=$?"; test -x bin/judge-clips && echo "executable OK"
```
Expected: `8 passed, 1 warning`, `rc=0`, `executable OK`.

Spec transcription check. It confirms the blocks below appear verbatim, extracting them from the spec file itself:
- in `bin/judge-clips`: the spec 1.1 `WS` block, the spec 4.3 schema, and spec 4.4's `validate_judgment_input`;
- in the test file: spec 7.1's loader block and `VALID_INPUT`.
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import re, textwrap
SPEC = "docs/superpowers/specs/2026-10-04-judge-clips-design.md"
CHECKS = [("bin/judge-clips", ["1.1#0", "4.3", "4.4"]),
          ("tests/test_judge_clips.py", ["7.1#0", "7.1#4"])]
lines = open(SPEC, encoding="utf-8").read().split("\n")
def blocks(section):
    start = next(i for i, l in enumerate(lines) if l.startswith("### " + section + " "))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(("### ", "## "))), len(lines))
    found, i = [], start
    while i < end:
        if lines[i].strip() == "```python":
            j = next(k for k in range(i + 1, end) if lines[k].strip() == "```")
            found.append(textwrap.dedent("\n".join(lines[i + 1:j])))
            i = j
        i += 1
    return found
for target, wants in CHECKS:
    src = open(target, encoding="utf-8").read()
    checked = 0
    for want in wants:
        section, _, index = want.partition("#")
        chosen = blocks(section)
        assert chosen, "no python block under spec " + section
        if index:
            chosen = [chosen[int(index)]]
        for block in chosen:
            for paragraph in re.split(r"\n[ \t]*\n", block):
                if paragraph.strip():
                    assert paragraph.strip() in src, "spec %s paragraph not verbatim in %s:\n%s" % (want, target, paragraph)
                    checked += 1
    print("PASS %s: %d spec paragraphs verbatim (%s)" % (target, checked, ", ".join(wants)))
EOF
```
Expected: `PASS bin/judge-clips: 3 spec paragraphs verbatim (1.1#0, 4.3, 4.4)` and `PASS tests/test_judge_clips.py: 2 spec paragraphs verbatim (7.1#0, 7.1#4)`.

Mutation checks at the unit level, for these spec 7.4 rows: duplicate-panel, missing-panel, and extra-panel validation removed; seam `>= 2` and `< 2` checks removed; `seam_continuity` added to `movie.required`. Task 6 re-runs four of them end to end. The script restores the file itself:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, shutil, subprocess, tempfile
PATH = "bin/judge-clips"
T = "tests/test_judge_clips.py::"
# (label, [(old, new, expected count of old)], [tests that must fail])
MUTATIONS = [
    ("duplicate-panel validation removed",
     [("    if duplicates:\n", "    if False:\n", 1)],
     ["test_t12_panel_set_rules"]),
    ("missing-panel validation removed",
     [("    missing = sorted(set(panels) - set(submitted))\n    if missing:\n",
       "    missing = sorted(set(panels) - set(submitted))\n    if False:\n", 1)],
     ["test_t12_panel_set_rules"]),
    ("extra-panel validation removed",
     [("    extra = sorted(set(submitted) - set(panels))\n    if extra:\n",
       "    extra = sorted(set(submitted) - set(panels))\n    if False:\n", 1)],
     ["test_t12_panel_set_rules"]),
    ("seam >= 2 check removed",
     [('    if len(panels) >= 2 and "seam_continuity" not in tool_input["movie"]:\n', "    if False:\n", 1)],
     ["test_t13_seam_two_way_rule"]),
    ("seam < 2 check removed",
     [('    if len(panels) < 2 and "seam_continuity" in tool_input["movie"]:\n', "    if False:\n", 1)],
     ["test_t13_seam_two_way_rule"]),
    ("seam_continuity added to movie.required",
     [('"required": ["narrative_clarity"],', '"required": ["seam_continuity", "narrative_clarity"],', 1)],
     ["test_t13_seam_two_way_rule"]),
]
def run(name):
    # Fresh bytecode cache and TMPDIR per run: a same-size mutation written in the same
    # second as an earlier compile would otherwise load the stale .pyc and falsely
    # "survive", and the mkdtemp mutation must not leave judge-clips-* dirs behind.
    base = tempfile.mkdtemp(prefix="jc-mut-")
    try:
        os.mkdir(os.path.join(base, "tmp"))
        env = dict(os.environ, PYTHONPYCACHEPREFIX=os.path.join(base, "pyc"),
                   TMPDIR=os.path.join(base, "tmp"))
        return subprocess.run(["python3", "-m", "pytest", "-q", "--color=no",
                               "-p", "no:cacheprovider", T + name],
                              capture_output=True, text=True, env=env).returncode
    finally:
        shutil.rmtree(base, ignore_errors=True)
src = open(PATH, encoding="utf-8").read()
caught = 0
for label, edits, tests in MUTATIONS:
    mutated = src
    for old, new, count in edits:
        assert mutated.count(old) == count, "%s: anchor count %d != %d" % (label, mutated.count(old), count)
        mutated = mutated.replace(old, new)
    for name in tests:
        assert run(name) == 0, "control: %s must pass unmutated" % name
    try:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(mutated)
        for name in tests:
            rc = run(name)
            print("[%s] %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation not caught"
            caught += 1
    finally:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(src)
assert open(PATH, encoding="utf-8").read() == src
print("%d mutations, %d CAUGHT; restored bin/judge-clips" % (len(MUTATIONS), caught))
EOF
```
Expected: six `CAUGHT` lines, then `6 mutations, 6 CAUGHT; restored bin/judge-clips`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
git diff --cached --name-only            # expect: no output
git add -- bin/judge-clips tests/test_judge_clips.py
git diff --cached --name-only            # expect exactly the two paths below
# qwen-agent-workspace/bin/judge-clips
# qwen-agent-workspace/tests/test_judge_clips.py
git commit -F - <<'EOF'
judge-clips: add script skeleton and submit_judgment validation

New standalone bin/judge-clips (spec 2026-10-04-judge-clips-design.md,
loop Phase 4): imports and pipeline_log path setup per spec 1.1, module
constants, the submit_judgment JSON Schema from spec 4.3 (seam_continuity
defined but not schema-required), and validate_judgment_input(tool_input,
panels): schema, then duplicate/missing/extra panel checks, then the
two-way seam_continuity rule (spec 4.4). Tests T11a-T11f, T12, T13; an
autouse fixture makes constructing a real Anthropic client fail any test.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 2: Clip discovery and manifest loading

**Files:**
- Modify: `bin/judge-clips`. Append `ManifestError`, `find_clips`, and `load_manifest_panels` at the end of the file (178 lines at the end of this task).
- Test: append to `tests/test_judge_clips.py`. This adds the spec 7.1 `PANEL_1`, `PANEL_2`, and `_manifest` fixtures and tests T3 and T5 (220 lines at the end of this task).

**Interfaces:**
- Consumes: `CLIP_NAME_RE` (Task 1).
- Produces:
  - `class ManifestError(Exception)`; its `str()` is the E7-E10 message without `Error: `;
  - `find_clips(clips_dir) -> list[tuple[int, str]]`: numeric sort, with path as the tie-break;
  - `load_manifest_panels(manifest_path) -> dict[int, dict]`: keyed by each panel's `index`, not its list position.
- Test fixtures produced: `PANEL_1`, `PANEL_2`, `_manifest(panels) -> dict` (`fps` 30, deliberately not the clips' 24). Tasks 4-7 use them, and Task 5's `_make_story` default argument evaluates `_manifest([PANEL_1, PANEL_2])` at definition time.
- Clip/panel pairing (E11/E12) is not in this task; see Decision 1. It lands in Task 5's `main`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_judge_clips.py`. The block starts with two empty lines. Note that spec 7.1's fixture block has one blank line between `PANEL_2` and `def _manifest`; keep it as written, because the transcription check compares paragraphs.

```python


# --- shared manifest panel fixtures (spec 7.1) -----------------------------------------

PANEL_1 = {"index": 1, "image_path": "/abs/story/images/panel_01.png", "title": "The Beach at Dawn",
           "panel_text": "A wide shot of a woman in a yellow sundress at the water's edge — dawn.",
           "narration": "She came to the shore for solitude.", "num_frames": 25,
           "motion_prompt": "She takes a slow step into the surf.", "conditioning": "still"}
PANEL_2 = {"index": 2, "image_path": None, "title": "The Horse Appears",
           "panel_text": "A chestnut horse trots out of the mist.",
           "narration": "A wild horse appeared.", "num_frames": 3,
           "motion_prompt": "A chestnut horse trots out of the mist.", "conditioning": "chain"}

def _manifest(panels):
    # fps 30 deliberately differs from the clips' real 24 fps, so a label computed from
    # the manifest fps instead of ffprobe's avg_frame_rate is caught (T17).
    return {"schema_version": 3, "story_id": STORY_ID, "fps": 30, "panels": panels}


# --- T3, T5: clip discovery and manifest loading (spec 3.1-3.3) -----------------------

def test_t3_find_clips_numeric_sort_and_filter(tmp_path):
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    for name in ("panel_03.mp4", "panel_01.mp4", "panel_100.mp4", "panel_99.mp4",
                 "panel_02.mp4", "panel_1.mp4", "panel_01.mp4.provenance.json",
                 "panel_02.chainseed.png", "panel_01.mov", "Panel_04.mp4", "panel_05.mp4.bak"):
        (clips_dir / name).write_bytes(b"x")
    d = str(clips_dir)
    assert judge_clips.find_clips(d) == [
        (1, os.path.join(d, "panel_01.mp4")),
        (2, os.path.join(d, "panel_02.mp4")),
        (3, os.path.join(d, "panel_03.mp4")),
        (99, os.path.join(d, "panel_99.mp4")),
        (100, os.path.join(d, "panel_100.mp4")),
    ]


def test_t5_load_manifest_pairs_by_index(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema_version": 3, "panels": [PANEL_2, PANEL_1]}),
                    encoding="utf-8")
    assert judge_clips.load_manifest_panels(str(path)) == {1: PANEL_1, 2: PANEL_2}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_clips.py -q --color=no; echo "rc=$?"
```
Expected: `2 failed, 8 passed, 1 warning`, `rc=1`. The failures:
- `test_t3_find_clips_numeric_sort_and_filter`: `AttributeError: module 'judge_clips' has no attribute 'find_clips'`.
- `test_t5_load_manifest_pairs_by_index`: `AttributeError: module 'judge_clips' has no attribute 'load_manifest_panels'`.

- [ ] **Step 3: Write minimal implementation**

Append this at the end of `bin/judge-clips`, after `validate_judgment_input`'s body. The block starts with two empty lines, so there are exactly two blank lines before `class ManifestError`. `find_clips` is spec 3.1 verbatim, and `load_manifest_panels` is spec 3.2 verbatim.

```python


class ManifestError(Exception):
    """manifest.json cannot be used; str() is the E7-E10 message without "Error: "
    (spec 3.2, 6)."""


def find_clips(clips_dir):
    """[(panel_number, path)] for every panel_NN.mp4 in clips_dir, sorted numerically (path
    breaks ties). os.listdir + fullmatch, not glob (spec 3.1)."""
    found = []
    for name in os.listdir(clips_dir):
        m = CLIP_NAME_RE.fullmatch(name)
        if m:
            found.append((int(m.group(1)), os.path.join(clips_dir, name)))
    found.sort(key=lambda item: (item[0], item[1]))
    return found


def load_manifest_panels(manifest_path):
    """{index: panel dict} from manifest.json. Raises ManifestError for E7-E10 (spec 3.2)."""
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except ValueError as e:
        # json.JSONDecodeError and UnicodeDecodeError are both ValueError subclasses.
        raise ManifestError("manifest.json is not valid JSON: %s: %s" % (manifest_path, e))
    panels = manifest.get("panels") if isinstance(manifest, dict) else None
    if not isinstance(panels, list) or not panels:
        raise ManifestError("manifest.json has no panels list: %s" % manifest_path)
    by_index = {}
    for position, panel in enumerate(panels, 1):
        index = panel.get("index") if isinstance(panel, dict) else None
        if not isinstance(index, int) or isinstance(index, bool):
            raise ManifestError("manifest.json panel entry %d has no integer index: %s"
                                % (position, manifest_path))
        if index in by_index:
            raise ManifestError("manifest.json lists panel index %d more than once: %s"
                                % (index, manifest_path))
        by_index[index] = panel
    return by_index
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_clips.py -q --color=no; echo "rc=$?"
```
Expected: `10 passed, 1 warning`, `rc=0`.

Spec transcription check:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import re, textwrap
SPEC = "docs/superpowers/specs/2026-10-04-judge-clips-design.md"
CHECKS = [("bin/judge-clips", ["3.1", "3.2"]),
          ("tests/test_judge_clips.py", ["7.1#3"])]
lines = open(SPEC, encoding="utf-8").read().split("\n")
def blocks(section):
    start = next(i for i, l in enumerate(lines) if l.startswith("### " + section + " "))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(("### ", "## "))), len(lines))
    found, i = [], start
    while i < end:
        if lines[i].strip() == "```python":
            j = next(k for k in range(i + 1, end) if lines[k].strip() == "```")
            found.append(textwrap.dedent("\n".join(lines[i + 1:j])))
            i = j
        i += 1
    return found
for target, wants in CHECKS:
    src = open(target, encoding="utf-8").read()
    checked = 0
    for want in wants:
        section, _, index = want.partition("#")
        chosen = blocks(section)
        assert chosen, "no python block under spec " + section
        if index:
            chosen = [chosen[int(index)]]
        for block in chosen:
            for paragraph in re.split(r"\n[ \t]*\n", block):
                if paragraph.strip():
                    assert paragraph.strip() in src, "spec %s paragraph not verbatim in %s:\n%s" % (want, target, paragraph)
                    checked += 1
    print("PASS %s: %d spec paragraphs verbatim (%s)" % (target, checked, ", ".join(wants)))
EOF
```
Expected: `PASS bin/judge-clips: 2 spec paragraphs verbatim (3.1, 3.2)` and `PASS tests/test_judge_clips.py: 2 spec paragraphs verbatim (7.1#3)`.

Mutation checks for these spec 7.4 rows: `find_clips` sorts by filename string; `CLIP_NAME_RE` changed to `panel_(\d+)\.mp4`; `load_manifest_panels` pairs by list position. The script restores the file itself:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, shutil, subprocess, tempfile
PATH = "bin/judge-clips"
T = "tests/test_judge_clips.py::"
# (label, [(old, new, expected count of old)], [tests that must fail])
MUTATIONS = [
    ("find_clips sorts by filename string",
     [("    found.sort(key=lambda item: (item[0], item[1]))\n", "    found.sort(key=lambda item: item[1])\n", 1)],
     ["test_t3_find_clips_numeric_sort_and_filter"]),
    ("CLIP_NAME_RE accepts one digit",
     [(r're.compile(r"panel_(\d{2,})\.mp4")', r're.compile(r"panel_(\d+)\.mp4")', 1)],
     ["test_t3_find_clips_numeric_sort_and_filter"]),
    ("load_manifest_panels pairs by list position",
     [("        by_index[index] = panel\n", "        by_index[position] = panel\n", 1)],
     ["test_t5_load_manifest_pairs_by_index"]),
]
def run(name):
    # Fresh bytecode cache and TMPDIR per run: a same-size mutation written in the same
    # second as an earlier compile would otherwise load the stale .pyc and falsely
    # "survive", and the mkdtemp mutation must not leave judge-clips-* dirs behind.
    base = tempfile.mkdtemp(prefix="jc-mut-")
    try:
        os.mkdir(os.path.join(base, "tmp"))
        env = dict(os.environ, PYTHONPYCACHEPREFIX=os.path.join(base, "pyc"),
                   TMPDIR=os.path.join(base, "tmp"))
        return subprocess.run(["python3", "-m", "pytest", "-q", "--color=no",
                               "-p", "no:cacheprovider", T + name],
                              capture_output=True, text=True, env=env).returncode
    finally:
        shutil.rmtree(base, ignore_errors=True)
src = open(PATH, encoding="utf-8").read()
caught = 0
for label, edits, tests in MUTATIONS:
    mutated = src
    for old, new, count in edits:
        assert mutated.count(old) == count, "%s: anchor count %d != %d" % (label, mutated.count(old), count)
        mutated = mutated.replace(old, new)
    for name in tests:
        assert run(name) == 0, "control: %s must pass unmutated" % name
    try:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(mutated)
        for name in tests:
            rc = run(name)
            print("[%s] %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation not caught"
            caught += 1
    finally:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(src)
assert open(PATH, encoding="utf-8").read() == src
print("%d mutations, %d CAUGHT; restored bin/judge-clips" % (len(MUTATIONS), caught))
EOF
```
Expected: three `CAUGHT` lines, then `3 mutations, 3 CAUGHT; restored bin/judge-clips`.

Real-data read-only check: `find_clips` and `load_manifest_panels` see the expected panels on the live-gate stories.
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import importlib.machinery
jc = importlib.machinery.SourceFileLoader("judge_clips", "bin/judge-clips").load_module()
for story, clips, panels in (("test_story1", [1, 2, 3, 4, 5], [1, 2, 3, 4, 5]),
                             ("final_e2e_verify", [1], [1]),
                             ("mlxdemo", [1, 3], [1, 2, 3]),
                             ("mystorytest2", [5], [1, 2, 3, 4, 5])):
    base = "generated/stories/%s/" % story
    assert [n for n, _ in jc.find_clips(base + "clips")] == clips, story
    assert sorted(jc.load_manifest_panels(base + "manifest.json")) == panels, story
print("PASS real clips and manifests")
EOF
```
Expected: `PASS real clips and manifests`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
git diff --cached --name-only            # expect: no output
git add -- bin/judge-clips tests/test_judge_clips.py
git diff --cached --name-only            # expect exactly the two paths below
# qwen-agent-workspace/bin/judge-clips
# qwen-agent-workspace/tests/test_judge_clips.py
git commit -F - <<'EOF'
judge-clips: add clip discovery and manifest loading

find_clips() lists clips/ with os.listdir + CLIP_NAME_RE.fullmatch (not
glob) and sorts numerically (spec 3.1); load_manifest_panels() returns
{index: panel} and raises ManifestError for invalid JSON, a missing or
empty panels list, a non-int (or bool) index, or a duplicate index
(spec 3.2). Tests T3, T5 (pairing by index, not list position).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 3: Clip probing, frame indices, and frame extraction (real ffmpeg)

**Files:**
- Modify: `bin/judge-clips`. Append `ClipError`, `_stderr_tail`, `probe_clip`, `frame_indices`, and `extract_frames` at the end of the file (251 lines at the end of this task).
- Test: append to `tests/test_judge_clips.py`. This adds `GARBAGE_CLIP`, the spec 7.1 `_make_clip` generator and `_frame_number` oracle, the session fixture `synthetic_clips`, the subprocess recorder `_fake_run`, `CAPTURE_KWARGS`, and tests T4a, T4b, T9a, T9b, T9c, T10a, T10b, T10c, T10d (411 lines at the end of this task).

**Interfaces:**
- Consumes: `FRAMES_PER_CLIP` (Task 1).
- Produces:
  - `class ClipError(Exception)`, whose `str()` is the E15 detail;
  - `_stderr_tail(stderr) -> str`;
  - `probe_clip(path) -> (int, fractions.Fraction)`;
  - `frame_indices(n) -> list[int]`, always of length 4;
  - `extract_frames(path, indices, out_dir) -> list[bytes]`, in `indices` order.
- Test helpers produced:
  - `GARBAGE_CLIP`;
  - `_make_clip(path, frames)`, where frame N has luma 16 + 8N;
  - `_frame_number(jpeg_bytes, tmp_path) -> int`;
  - `synthetic_clips` (session-scoped `{25: path, 3: path, 1: path}`);
  - `_fake_run(monkeypatch, returncode, stdout="", stderr="") -> list[(argv, kwargs)]`;
  - `CAPTURE_KWARGS`.

  Tasks 5-7 use `synthetic_clips`, `GARBAGE_CLIP`, and `_frame_number`.

Grounding verified 2026-10-04 with ffmpeg 9.0.1:
- `_make_clip` yields `nb_read_frames` 25, 3, and 1 at `avg_frame_rate` `24/1`.
- The oracle maps the 4 extracted frames of the 25-frame clip to gray values 0/75/149/224, which are frames 0/8/16/24.
- An audio-only mp4 and a `-frames:v 0` mp4 both give `"streams": []` with exit 0.
- Garbage input makes ffprobe exit 1 and ffmpeg exit 183.
- Without `-fps_mode passthrough`, the 25-frame clip writes 31 JPEGs, while clip3 `[0,1,2]` still writes 3 and clip1 still writes 1 (Decision 2).
- A repeated select term writes one file.
- Selecting 0,1,2,5 from clip3 writes 3 files with exit 0.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_judge_clips.py` (the block starts with two empty lines):

```python


# --- synthetic clips and the frame-number oracle (spec 7.1) ---------------------------

GARBAGE_CLIP = b"not a real clip"


def _make_clip(path, frames):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y",
                    "-f", "lavfi", "-i",
                    "color=c=black:s=64x48:r=24,format=yuv420p,geq=lum='16+N*8':cb=128:cr=128",
                    "-f", "lavfi", "-t", "2", "-i", "anullsrc=r=48000:cl=mono",
                    "-map", "0:v", "-map", "1:a", "-frames:v", str(frames),
                    "-c:v", "libx264", "-preset", "ultrafast", "-qp", "0", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(path)], check=True)


def _frame_number(jpeg_bytes, tmp_path):
    path = tmp_path / ("oracle_%s.jpg" % uuid.uuid4().hex)
    path.write_bytes(jpeg_bytes)
    out = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
                          "-vf", "scale=1:1:flags=area", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    return round(out[0] * 219 / 255 / 8)


@pytest.fixture(scope="session")
def synthetic_clips(tmp_path_factory):
    """{25: path, 3: path, 1: path}: real h264+aac clips whose frame N has uniform luma
    16 + 8N, generated once per session (spec 7.1)."""
    directory = tmp_path_factory.mktemp("synthetic")
    paths = {}
    for frames in (25, 3, 1):
        path = directory / ("clip%d.mp4" % frames)
        _make_clip(path, frames)
        paths[frames] = str(path)
    return paths


def _fake_run(monkeypatch, returncode, stdout="", stderr=""):
    """Replace judge_clips.subprocess.run with a recorder that returns one canned
    CompletedProcess. Returns the list of (argv, kwargs) calls."""
    calls = []

    def _run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)
    monkeypatch.setattr(judge_clips.subprocess, "run", _run)
    return calls


CAPTURE_KWARGS = {"capture_output": True, "encoding": "utf-8", "errors": "replace"}


# --- T4, T9, T10: frame indices, probing, extraction (spec 3.4-3.6) -------------------

def test_t4a_frame_indices_table():
    table = {241: [0, 80, 160, 240], 145: [0, 48, 96, 144], 25: [0, 8, 16, 24],
             9: [0, 3, 5, 8], 5: [0, 1, 3, 4], 4: [0, 1, 2, 3], 3: [0, 1, 1, 2],
             2: [0, 0, 1, 1], 1: [0, 0, 0, 0]}
    for n, expected in table.items():
        assert judge_clips.frame_indices(n) == expected, n


def test_t4b_frame_indices_properties():
    for n in range(1, 2001):
        idx = judge_clips.frame_indices(n)
        assert len(idx) == 4, n
        assert idx[0] == 0, n
        assert idx[3] == n - 1, n
        assert idx == sorted(idx), n
        for k in range(4):
            assert abs(idx[k] - k * (n - 1) / 3) <= 0.5, (n, k)


def test_t9a_probe_synthetic_clips(synthetic_clips):
    for frames in (25, 3, 1):
        assert judge_clips.probe_clip(synthetic_clips[frames]) == (frames, fractions.Fraction(24))


def test_t9b_probe_real_failures(tmp_path):
    garbage = tmp_path / "garbage.mp4"
    garbage.write_bytes(GARBAGE_CLIP)
    with pytest.raises(judge_clips.ClipError) as exc:
        judge_clips.probe_clip(str(garbage))
    assert str(exc.value).startswith("ffprobe failed on %s (exit 1): " % garbage)

    audio_only = tmp_path / "audio_only.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-t", "1",
                    "-i", "anullsrc=r=48000:cl=mono", "-c:a", "aac", str(audio_only)], check=True)
    zero_frames = tmp_path / "zero_frames.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "color=c=black:s=64x48:r=24", "-frames:v", "0", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(zero_frames)], check=True)
    for path in (audio_only, zero_frames):
        with pytest.raises(judge_clips.ClipError) as exc:
            judge_clips.probe_clip(str(path))
        assert str(exc.value) == "%s has no video stream" % path


def test_t9c_probe_canned_output(monkeypatch):
    clip = "/x/panel_01.mp4"
    calls = _fake_run(monkeypatch, 0,
                      stdout='{"streams": [{"avg_frame_rate": "24/1", "nb_read_frames": "145"}]}')
    assert judge_clips.probe_clip(clip) == (145, fractions.Fraction(24))
    assert calls == [(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                       "-show_entries", "stream=nb_read_frames,avg_frame_rate", "-of", "json",
                       "/x/panel_01.mp4"], CAPTURE_KWARGS)]
    cases = [
        (0, '{"streams": [{"avg_frame_rate": "24/1", "nb_read_frames": "0"}]}', "",
         "/x/panel_01.mp4 has no decodable video frames"),                          # (b)
        (0, '{"streams": [{"avg_frame_rate": "24/1"}]}', "",
         "/x/panel_01.mp4 has no decodable video frames"),                          # (c)
        (0, '{"streams": [{"avg_frame_rate": "0/0", "nb_read_frames": "145"}]}', "",
         "/x/panel_01.mp4 has no usable frame rate (avg_frame_rate='0/0')"),        # (d)
        (0, "not json", "", "ffprobe returned unreadable output for /x/panel_01.mp4"),  # (e)
        (1, "", "line one\nlast line\n\n",
         "ffprobe failed on /x/panel_01.mp4 (exit 1): last line"),                  # (f)
        (1, "", "", "ffprobe failed on /x/panel_01.mp4 (exit 1): (no error output)"),  # (g)
    ]
    for returncode, stdout, stderr, message in cases:
        _fake_run(monkeypatch, returncode, stdout=stdout, stderr=stderr)
        with pytest.raises(judge_clips.ClipError) as exc:
            judge_clips.probe_clip(clip)
        assert str(exc.value) == message


def test_t10a_extract_four_distinct_frames(tmp_path, synthetic_clips):
    out = tmp_path / "out"
    out.mkdir()
    images = judge_clips.extract_frames(synthetic_clips[25], [0, 8, 16, 24], str(out))
    assert len(images) == 4
    assert all(image.startswith(b"\xff\xd8") for image in images)
    assert [_frame_number(image, tmp_path) for image in images] == [0, 8, 16, 24]
    size = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
                           "-of", "csv=p=0", str(out / "frame_1.jpg")],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert size == "64,48"
    assert sorted(os.listdir(out)) == ["frame_1.jpg", "frame_2.jpg", "frame_3.jpg", "frame_4.jpg"]


def test_t10b_extract_repeated_indices(tmp_path, synthetic_clips):
    out = tmp_path / "out"
    out.mkdir()
    images = judge_clips.extract_frames(synthetic_clips[3], [0, 1, 1, 2], str(out))
    assert len(images) == 4
    assert images[1] == images[2]
    assert [_frame_number(image, tmp_path) for image in images] == [0, 1, 1, 2]
    assert len(os.listdir(out)) == 3

    out2 = tmp_path / "out2"
    out2.mkdir()
    images = judge_clips.extract_frames(synthetic_clips[1], [0, 0, 0, 0], str(out2))
    assert len(images) == 4
    assert images[0] == images[1] == images[2] == images[3]
    assert [_frame_number(image, tmp_path) for image in images] == [0, 0, 0, 0]
    assert len(os.listdir(out2)) == 1


def test_t10c_extract_canned_output(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    calls = _fake_run(monkeypatch, 0)
    with pytest.raises(judge_clips.ClipError) as exc:
        judge_clips.extract_frames("/x/panel_02.mp4", [0, 1, 1, 2], str(out))
    assert calls == [(["ffmpeg", "-nostdin", "-v", "error", "-i", "/x/panel_02.mp4",
                       "-map", "0:v:0", "-vf", "select=eq(n\\,0)+eq(n\\,1)+eq(n\\,2)",
                       "-fps_mode", "passthrough", "-q:v", "2", "-f", "image2",
                       os.path.join(str(out), "frame_%d.jpg")], CAPTURE_KWARGS)]
    assert str(exc.value) == "ffmpeg wrote 0 frames from /x/panel_02.mp4; expected 3"

    _fake_run(monkeypatch, 1, stderr="bad\nworse\n")
    with pytest.raises(judge_clips.ClipError) as exc:
        judge_clips.extract_frames("/x/panel_02.mp4", [0, 1, 1, 2], str(out))
    assert str(exc.value) == "ffmpeg failed on /x/panel_02.mp4 (exit 1): worse"


def test_t10d_extract_real_failures(tmp_path, synthetic_clips):
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(judge_clips.ClipError) as exc:
        judge_clips.extract_frames(synthetic_clips[3], [0, 1, 2, 5], str(out))
    assert str(exc.value) == "ffmpeg wrote 3 frames from %s; expected 4" % synthetic_clips[3]

    garbage = tmp_path / "garbage.mp4"
    garbage.write_bytes(GARBAGE_CLIP)
    out3 = tmp_path / "out3"
    out3.mkdir()
    with pytest.raises(judge_clips.ClipError) as exc:
        judge_clips.extract_frames(str(garbage), [0], str(out3))
    assert str(exc.value).startswith("ffmpeg failed on %s (exit " % garbage)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_clips.py -q --color=no; echo "rc=$?"
```
Expected: `9 failed, 10 passed, 1 warning`, `rc=1`. The failures:

| Test | Error |
|---|---|
| T4a, T4b | `AttributeError: module 'judge_clips' has no attribute 'frame_indices'` |
| T9a, T9c | `... no attribute 'probe_clip'` |
| T10a, T10b | `... no attribute 'extract_frames'` |
| T9b, T10c, T10d | `... no attribute 'ClipError'` |

If any test instead errors with `CalledProcessError` from `_make_clip`, ffmpeg, ffprobe, or libx264 is missing. Stop and report; do not add a skip.

- [ ] **Step 3: Write minimal implementation**

Append this at the end of `bin/judge-clips`, after `load_manifest_panels`'s body. The block starts with two empty lines. `_stderr_tail` and `probe_clip` are spec 3.4 verbatim, `frame_indices` is spec 3.5 verbatim, and `extract_frames` is spec 3.6 verbatim. In particular:
- the Python literal `"eq(n\\,%d)"` (which ffmpeg receives as `eq(n\,0)`);
- `"-fps_mode", "passthrough"`;
- the literal `frame_%d.jpg` passed to ffmpeg;
- the file-count check.

```python


class ClipError(Exception):
    """A clip cannot be probed or its frames cannot be extracted; str() is the E15 detail
    (spec 3.4, 3.6)."""


def _stderr_tail(stderr):
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return lines[-1] if lines else "(no error output)"


def probe_clip(path):
    """(frame_count, fps) of the clip's first video stream. frame_count is the number of
    frames the decoder actually produces (-count_frames nb_read_frames), never the
    container header's nb_frames; fps is avg_frame_rate as a Fraction (spec 3.4)."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames,avg_frame_rate", "-of", "json", path],
        capture_output=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise ClipError("ffprobe failed on %s (exit %d): %s"
                        % (path, proc.returncode, _stderr_tail(proc.stderr)))
    try:
        streams = json.loads(proc.stdout).get("streams")
    except ValueError:
        raise ClipError("ffprobe returned unreadable output for %s" % path)
    if not streams:
        raise ClipError("%s has no video stream" % path)
    count = streams[0].get("nb_read_frames", "")
    if not count.isdigit() or int(count) == 0:
        raise ClipError("%s has no decodable video frames" % path)
    rate = streams[0].get("avg_frame_rate", "")
    try:
        fps = fractions.Fraction(rate)
    except (ValueError, ZeroDivisionError):
        fps = fractions.Fraction(0)
    if fps <= 0:
        raise ClipError("%s has no usable frame rate (avg_frame_rate=%r)" % (path, rate))
    return int(count), fps


def frame_indices(n):
    """The FRAMES_PER_CLIP frame indices sampled from a clip of n >= 1 frames:
    round(k * (n - 1) / 3) for k = 0..3 -- first frame, two evenly spaced middle frames,
    last frame. Repeats are kept when n < 4 (spec 3.5). Pure."""
    return [round(k * (n - 1) / (FRAMES_PER_CLIP - 1)) for k in range(FRAMES_PER_CLIP)]


def extract_frames(path, indices, out_dir):
    """JPEG bytes for each entry of indices, in the same order. Each distinct index is
    extracted once (a repeated select term yields one frame, not two) and its bytes are
    reused for repeats. out_dir must be an existing empty directory (spec 3.6)."""
    unique = sorted(set(indices))
    select = "select=" + "+".join("eq(n\\,%d)" % i for i in unique)
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-map", "0:v:0",
         "-vf", select, "-fps_mode", "passthrough", "-q:v", "2",
         "-f", "image2", os.path.join(out_dir, "frame_%d.jpg")],
        capture_output=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise ClipError("ffmpeg failed on %s (exit %d): %s"
                        % (path, proc.returncode, _stderr_tail(proc.stderr)))
    expected = ["frame_%d.jpg" % j for j in range(1, len(unique) + 1)]
    written = os.listdir(out_dir)
    if sorted(written) != sorted(expected):
        raise ClipError("ffmpeg wrote %d frames from %s; expected %d"
                        % (len(written), path, len(unique)))
    by_index = {}
    for j, index in enumerate(unique, 1):
        with open(os.path.join(out_dir, "frame_%d.jpg" % j), "rb") as f:
            by_index[index] = f.read()
    return [by_index[i] for i in indices]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_clips.py -q --color=no; echo "rc=$?"
```
Expected: `19 passed, 1 warning`, `rc=0`.

Spec transcription check:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import re, textwrap
SPEC = "docs/superpowers/specs/2026-10-04-judge-clips-design.md"
CHECKS = [("bin/judge-clips", ["3.4", "3.5", "3.6"]),
          ("tests/test_judge_clips.py", ["7.1#1", "7.1#2"])]
lines = open(SPEC, encoding="utf-8").read().split("\n")
def blocks(section):
    start = next(i for i, l in enumerate(lines) if l.startswith("### " + section + " "))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(("### ", "## "))), len(lines))
    found, i = [], start
    while i < end:
        if lines[i].strip() == "```python":
            j = next(k for k in range(i + 1, end) if lines[k].strip() == "```")
            found.append(textwrap.dedent("\n".join(lines[i + 1:j])))
            i = j
        i += 1
    return found
for target, wants in CHECKS:
    src = open(target, encoding="utf-8").read()
    checked = 0
    for want in wants:
        section, _, index = want.partition("#")
        chosen = blocks(section)
        assert chosen, "no python block under spec " + section
        if index:
            chosen = [chosen[int(index)]]
        for block in chosen:
            for paragraph in re.split(r"\n[ \t]*\n", block):
                if paragraph.strip():
                    assert paragraph.strip() in src, "spec %s paragraph not verbatim in %s:\n%s" % (want, target, paragraph)
                    checked += 1
    print("PASS %s: %d spec paragraphs verbatim (%s)" % (target, checked, ", ".join(wants)))
EOF
```
Expected: `PASS bin/judge-clips: 4 spec paragraphs verbatim (3.4, 3.5, 3.6)` and `PASS tests/test_judge_clips.py: 2 spec paragraphs verbatim (7.1#1, 7.1#2)`.

Mutation checks for these spec 7.4 rows: `frame_indices` uses `int()`; `frame_indices` uses `n`; ffprobe uses `nb_frames` without `-count_frames`; `-fps_mode passthrough` removed; dedup removed (Decision 4); file-count check removed. The passthrough row is checked against T10a and T10c only (Decision 2), and Task 6 adds T17 for it. The script restores the file itself:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, shutil, subprocess, tempfile
PATH = "bin/judge-clips"
T = "tests/test_judge_clips.py::"
# (label, [(old, new, expected count of old)], [tests that must fail])
MUTATIONS = [
    ("frame_indices floors with int() instead of round()",
     [("    return [round(k * (n - 1)", "    return [int(k * (n - 1)", 1)],
     ["test_t4a_frame_indices_table", "test_t4b_frame_indices_properties"]),
    ("frame_indices uses n instead of n - 1",
     [("k * (n - 1) / (FRAMES_PER_CLIP - 1)", "k * n / (FRAMES_PER_CLIP - 1)", 1)],
     ["test_t4a_frame_indices_table", "test_t4b_frame_indices_properties"]),
    ("ffprobe uses stream=nb_frames without -count_frames",
     [('"v:0", "-count_frames",\n         "-show_entries", "stream=nb_read_frames,avg_frame_rate"',
       '"v:0",\n         "-show_entries", "stream=nb_frames,avg_frame_rate"', 1)],
     ["test_t9a_probe_synthetic_clips", "test_t9c_probe_canned_output"]),
    ("-fps_mode passthrough removed",
     [('"-fps_mode", "passthrough", ', "", 1)],
     ["test_t10a_extract_four_distinct_frames", "test_t10c_extract_canned_output"]),
    ("dedup removed (select built from indices, not unique)",
     [("    unique = sorted(set(indices))\n", "    unique = sorted(indices)\n", 1)],
     ["test_t10b_extract_repeated_indices", "test_t10c_extract_canned_output"]),
    ("file-count check removed",
     [("    if sorted(written) != sorted(expected):\n", "    if False:\n", 1)],
     ["test_t10c_extract_canned_output", "test_t10d_extract_real_failures"]),
]
def run(name):
    # Fresh bytecode cache and TMPDIR per run: a same-size mutation written in the same
    # second as an earlier compile would otherwise load the stale .pyc and falsely
    # "survive", and the mkdtemp mutation must not leave judge-clips-* dirs behind.
    base = tempfile.mkdtemp(prefix="jc-mut-")
    try:
        os.mkdir(os.path.join(base, "tmp"))
        env = dict(os.environ, PYTHONPYCACHEPREFIX=os.path.join(base, "pyc"),
                   TMPDIR=os.path.join(base, "tmp"))
        return subprocess.run(["python3", "-m", "pytest", "-q", "--color=no",
                               "-p", "no:cacheprovider", T + name],
                              capture_output=True, text=True, env=env).returncode
    finally:
        shutil.rmtree(base, ignore_errors=True)
src = open(PATH, encoding="utf-8").read()
caught = 0
for label, edits, tests in MUTATIONS:
    mutated = src
    for old, new, count in edits:
        assert mutated.count(old) == count, "%s: anchor count %d != %d" % (label, mutated.count(old), count)
        mutated = mutated.replace(old, new)
    for name in tests:
        assert run(name) == 0, "control: %s must pass unmutated" % name
    try:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(mutated)
        for name in tests:
            rc = run(name)
            print("[%s] %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation not caught"
            caught += 1
    finally:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(src)
assert open(PATH, encoding="utf-8").read() == src
print("%d mutations, %d CAUGHT; restored bin/judge-clips" % (len(MUTATIONS), caught))
EOF
```
Expected: twelve `CAUGHT` lines (two tests per mutation), then `6 mutations, 12 CAUGHT; restored bin/judge-clips`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
git diff --cached --name-only            # expect: no output
git add -- bin/judge-clips tests/test_judge_clips.py
git diff --cached --name-only            # expect exactly the two paths below
# qwen-agent-workspace/bin/judge-clips
# qwen-agent-workspace/tests/test_judge_clips.py
git commit -F - <<'EOF'
judge-clips: add clip probing, frame indices, and frame extraction

probe_clip() reads the decoded frame count (-count_frames
nb_read_frames) and avg_frame_rate with ffprobe (spec 3.4);
frame_indices() samples round(k*(n-1)/3), k=0..3 (spec 3.5);
extract_frames() runs one ffmpeg select per clip with -fps_mode
passthrough, extracts each distinct index once, and checks the written
file count (spec 3.6). Every failure is a ClipError. Tests T4a, T4b,
T9a-T9c, T10a-T10d run real ffmpeg on synthetic luma-encoded clips.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 4: Prompt texts, panel text, frame labels, and user-message content

**Files:**
- Modify: `bin/judge-clips`, in three edits:
  - Insert `TOOL_DESCRIPTION` directly after `TOOL_NAME`.
  - Insert `SYSTEM_PROMPT`, `FINAL_USER_TEXT_SINGLE`, `FINAL_USER_TEXT_MULTI_TEMPLATE`, and `RETRY_USER_MESSAGE` immediately before `def _panel_list(panels):`.
  - Append `_text_field`, `format_panel_text`, `format_frame_label`, and `build_user_content` at the end of the file.

  The file is 382 lines at the end of this task.
- Test: append to `tests/test_judge_clips.py`. This adds the `_clip_input` helper and tests T6, T7, T8a, T8b, T8c (497 lines at the end of this task).

**Interfaces:**
- Consumes: `FRAMES_PER_CLIP` and `MEDIA_TYPE` (Task 1). Test fixtures `PANEL_1` and `PANEL_2` (Task 2).
- Produces:
  - `TOOL_DESCRIPTION`, `SYSTEM_PROMPT`, `FINAL_USER_TEXT_SINGLE`, `RETRY_USER_MESSAGE` (all `str`), and `FINAL_USER_TEXT_MULTI_TEMPLATE` (`str` with one `%d`);
  - `_text_field(panel, key) -> str`;
  - `format_panel_text(number, panel) -> str`;
  - `format_frame_label(panel, position, t) -> str`;
  - `build_user_content(clips) -> list[dict]`, always `9 * len(clips) + 1` blocks.
- Who uses them later: Task 6 sends `SYSTEM_PROMPT` and `TOOL_DESCRIPTION` and calls the three formatters and `build_user_content` from `main`; Task 7 sends `RETRY_USER_MESSAGE`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_judge_clips.py` (the block starts with two empty lines):

```python


# --- T6-T8: panel text, frame labels, user content, system prompt (spec 3.7-3.9, 4.5) -

def _clip_input(panel, text, prefix):
    """A build_user_content input entry: frames at t = 0.0, 0.5, 1.0, 1.5 whose data are
    "<prefix>0" .. "<prefix>3" (spec 7.2 T8a)."""
    return {"panel": panel, "text": text,
            "frames": [{"t": t, "data": "%s%d" % (prefix, k)}
                       for k, t in enumerate((0.0, 0.5, 1.0, 1.5))]}


def test_t6_format_panel_text():
    expected_a = ("## Panel 1 — The Beach at Dawn\n"
                  "Opening still: A wide shot of a woman in a yellow sundress at the water's "
                  "edge — dawn.\n"
                  "Motion: She takes a slow step into the surf.\n"
                  "Narration: She came to the shore for solitude.")
    expected_b = ("## Panel 2 — The Horse Appears\n"
                  "Motion: A chestnut horse trots out of the mist.\n"
                  "Narration: A wild horse appeared.")
    without_opening = ("## Panel 1 — The Beach at Dawn\n"
                       "Motion: She takes a slow step into the surf.\n"
                       "Narration: She came to the shore for solitude.")
    assert judge_clips.format_panel_text(1, PANEL_1) == expected_a                     # (a)
    assert judge_clips.format_panel_text(2, PANEL_2) == expected_b                     # (b)
    assert judge_clips.format_panel_text(1, dict(PANEL_1, image_path=None)) == without_opening  # (c)
    assert judge_clips.format_panel_text(1, dict(PANEL_1, panel_text="   ")) == without_opening  # (d)
    assert judge_clips.format_panel_text(
        3, {"index": 3, "title": "", "motion_prompt": None}) == "## Panel 3 —"           # (e)
    assert judge_clips.format_panel_text(
        4, {"index": 4, "title": "  Padded  ", "motion_prompt": "  Runs.  ",
            "narration": 7}) == "## Panel 4 — Padded\nMotion: Runs."                    # (f)
    # (g) a still path on a panel other than 1 never adds an Opening still: line
    assert judge_clips.format_panel_text(
        2, dict(PANEL_2, image_path="/abs/story/images/panel_02.png")) == expected_b


def test_t7_format_frame_label():
    assert judge_clips.format_frame_label(3, 2, 2.0) == "Panel 3, frame 2 of 4 (t=2.00s)"
    assert judge_clips.format_frame_label(1, 4, 6.0) == "Panel 1, frame 4 of 4 (t=6.00s)"
    assert judge_clips.format_frame_label(2, 1, 1 / 3) == "Panel 2, frame 1 of 4 (t=0.33s)"


def test_t8a_build_user_content_two_clips():
    content = judge_clips.build_user_content([_clip_input(1, "T1", "A"), _clip_input(2, "T2", "B")])
    expected = []
    for panel, text, prefix in ((1, "T1", "A"), (2, "T2", "B")):
        expected.append({"type": "text", "text": text})
        for k, t in enumerate((0.0, 0.5, 1.0, 1.5)):
            expected.append({"type": "text",
                             "text": judge_clips.format_frame_label(panel, k + 1, t)})
            expected.append({"type": "image",
                             "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": "%s%d" % (prefix, k)}})
    expected.append({"type": "text", "text": judge_clips.FINAL_USER_TEXT_MULTI_TEMPLATE % 2})
    assert len(content) == 19
    assert content == expected
    assert content[1]["text"] == "Panel 1, frame 1 of 4 (t=0.00s)"
    assert judge_clips.FINAL_USER_TEXT_MULTI_TEMPLATE % 2 == (
        "You are judging all 2 clips above, 4 sampled frames from each, against their panel "
        "text. Submit one clips entry per panel with motion_fidelity, physical_realism, and "
        "temporal_stability, score both seam_continuity and narrative_clarity for the movie, "
        "and call submit_judgment.")


def test_t8b_build_user_content_one_clip():
    content = judge_clips.build_user_content([_clip_input(1, "T1", "A")])
    assert len(content) == 10
    assert content[-1] == {"type": "text", "text": judge_clips.FINAL_USER_TEXT_SINGLE}
    assert judge_clips.FINAL_USER_TEXT_SINGLE == (
        "You are judging 1 clip above, shown as 4 sampled frames, against its panel text. "
        "There is only one clip, so there is no join between clips to judge: omit "
        "seam_continuity from your movie object entirely. Score motion_fidelity, "
        "physical_realism, and temporal_stability for the clip, score narrative_clarity for "
        "the movie, and call submit_judgment.")


def test_t8c_system_prompt_content():
    for phrase in ("the most realistic action scenes possible", "you receive no audio",
                   "Do not judge audio", "motion_fidelity:", "physical_realism:",
                   "temporal_stability:", "seam_continuity:", "narrative_clarity:",
                   "do not include seam_continuity", "you must include seam_continuity",
                   "exactly once"):
        assert phrase in judge_clips.SYSTEM_PROMPT, phrase
    assert not judge_clips.SYSTEM_PROMPT.endswith("\n")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_clips.py -q --color=no; echo "rc=$?"
```
Expected: `5 failed, 19 passed, 1 warning`, `rc=1`. Each failure is an `AttributeError: module 'judge_clips' has no attribute ...`:

| Test | Missing attribute |
|---|---|
| T6 | `'format_panel_text'` |
| T7 | `'format_frame_label'` |
| T8a, T8b | `'build_user_content'` |
| T8c | `'SYSTEM_PROMPT'` |

- [ ] **Step 3: Write minimal implementation**

Edit 1 uses the Edit tool on `bin/judge-clips` (spec 4.1's `TOOL_DESCRIPTION`).

old_string:
```python
TOOL_NAME = "submit_judgment"
```
new_string:
```python
TOOL_NAME = "submit_judgment"
TOOL_DESCRIPTION = ("Submit your judgment of the clips: for every clip, its panel number and "
                    "1-10 scores for motion_fidelity, physical_realism, and "
                    "temporal_stability; for the movie, a 1-10 narrative_clarity score "
                    "always, plus seam_continuity when you are judging 2 or more clips; and a "
                    "critique naming specific panels by number. You must call this exactly "
                    "once.")
```

Edit 2 uses the Edit tool on `bin/judge-clips`. It adds spec 4.5's `SYSTEM_PROMPT`, spec 3.9's two final texts, and spec 4.6's `RETRY_USER_MESSAGE`, all verbatim:
- In `SYSTEM_PROMPT`, each paragraph break is `"\n"` followed by `"\n"`, and each line before a bullet ends in `"\n"`.
- The two `\"` escapes are part of the text: `\"## Panel N\"` and `\"Panel 3\"`.
- There is no trailing newline after `failure.`.

old_string:
```python
def _panel_list(panels):
```
new_string:
```python
SYSTEM_PROMPT = (
    "You are an expert film director and visual-effects supervisor judging the video clips "
    "generated for a story by an AI image-and-video generation pipeline. The target output "
    "goal is the most realistic action scenes possible.\n"
    "\n"
    "The story is told in panels. A video model rendered each panel as one short clip from "
    "that panel's Motion: text, and the clips are joined in panel order into one movie. Clip "
    "1 starts from an opening still image described by Panel 1's Opening still: text. Each "
    "later clip starts from the last frame of the previous clip, so the movie is meant to "
    "play as one continuous take.\n"
    "\n"
    "You cannot watch the video. You will receive the panels in panel order. For each panel "
    "you get its \"## Panel N\" header and whichever of its Opening still:, Motion:, and "
    "Narration: text it has, followed by 4 frames sampled from its clip: the first frame, "
    "two evenly spaced middle frames, and the last frame. Each frame is preceded by a label "
    "giving its panel, its position (frame 1 of 4 to frame 4 of 4), and its time in seconds "
    "from the start of that clip. A clip shorter than 4 frames repeats some frames. The "
    "final message tells you exactly how many clips you are judging. Judge motion by "
    "comparing a clip's frames with each other and with its Motion: text; you cannot see "
    "what happens between the sampled frames, so do not reward or penalize anything the "
    "frames cannot show.\n"
    "\n"
    "The movie also has a soundtrack and spoken narration, but you receive no audio. Do not "
    "judge audio, voice, music, or sound effects. The Narration: text is what is spoken "
    "over that panel's clip.\n"
    "\n"
    "Score each clip on these dimensions, each an integer from 1 (worst) to 10 (best):\n"
    "- motion_fidelity: whether the clip actually performs the action its Motion: text "
    "describes.\n"
    "- physical_realism: whether the action, anatomy, and physics are plausible: people, "
    "animals, objects, water, and cloth move and interact the way they would in real "
    "footage.\n"
    "- temporal_stability: whether people, animals, objects, and the setting keep their "
    "identity, shape, and appearance across the clip's frames, with no morphing, melting, "
    "or identity drift.\n"
    "\n"
    "Score the movie as a whole on these dimensions, on the same 1-10 scale:\n"
    "- seam_continuity: whether each clip's first frame continues from the previous clip's "
    "last frame, so the joins between clips read as one continuous take, with no jump in "
    "character appearance, position, setting, lighting, or camera.\n"
    "- narrative_clarity: whether a viewer could follow the story from the visuals together "
    "with the Narration: text.\n"
    "\n"
    "Put exactly one entry in clips for every panel you receive, with its panel number as "
    "an integer. If you are judging fewer than 2 clips, do not include seam_continuity in "
    "your movie object at all: with a single clip there is no join to judge. If you are "
    "judging 2 or more clips, you must include seam_continuity, scored normally.\n"
    "\n"
    "Then write a critique that names specific panels by number (for example, \"Panel 3\") "
    "when identifying strengths and problems.\n"
    "\n"
    "You must deliver your judgment by calling the submit_judgment tool exactly once. Do not "
    "put the judgment in a plain text reply; a response without a submit_judgment call is a "
    "failure."
)

# Final text block of the user message; it states the clip count so the judge knows
# whether seam_continuity applies (spec 3.9).
FINAL_USER_TEXT_SINGLE = ("You are judging 1 clip above, shown as 4 sampled frames, against "
                          "its panel text. There is only one clip, so there is no join "
                          "between clips to judge: omit seam_continuity from your movie "
                          "object entirely. Score motion_fidelity, physical_realism, and "
                          "temporal_stability for the clip, score narrative_clarity for the "
                          "movie, and call submit_judgment.")
FINAL_USER_TEXT_MULTI_TEMPLATE = ("You are judging all %d clips above, 4 sampled frames from "
                                  "each, against their panel text. Submit one clips entry per "
                                  "panel with motion_fidelity, physical_realism, and "
                                  "temporal_stability, score both seam_continuity and "
                                  "narrative_clarity for the movie, and call submit_judgment.")

RETRY_USER_MESSAGE = ("You did not call the submit_judgment tool. Call submit_judgment now "
                      "with your clip scores, movie scores, and critique. Do not reply with "
                      "plain text.")


def _panel_list(panels):
```

Edit 3 appends this at the end of `bin/judge-clips`, after `extract_frames`'s body (the block starts with two empty lines). These are spec 3.7, 3.8, and 3.9 verbatim. The header dash is U+2014 EM DASH, in both header formats.

```python


def _text_field(panel, key):
    """panel[key] stripped when it is a string; "" when missing, null, or not a string."""
    value = panel.get(key)
    return value.strip() if isinstance(value, str) else ""


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


def format_frame_label(panel, position, t):
    """Text block placed immediately before each frame image (spec 3.8). Pure."""
    return "Panel %d, frame %d of %d (t=%.2fs)" % (panel, position, FRAMES_PER_CLIP, t)


def build_user_content(clips):
    """The single user turn's content blocks (spec 3.9). clips is a list, in panel order, of
    {"panel": int, "text": str, "frames": [{"t": float, "data": base64 str}] * 4}. Per clip:
    its text block, then a label text block and an image block for each frame; then one
    final text block. Always 9 * len(clips) + 1 blocks. Pure."""
    content = []
    for clip in clips:
        content.append({"type": "text", "text": clip["text"]})
        for position, frame in enumerate(clip["frames"], 1):
            content.append({"type": "text",
                            "text": format_frame_label(clip["panel"], position, frame["t"])})
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": MEDIA_TYPE,
                                       "data": frame["data"]}})
    count = len(clips)
    if count >= 2:
        final_text = FINAL_USER_TEXT_MULTI_TEMPLATE % count
    else:
        final_text = FINAL_USER_TEXT_SINGLE
    content.append({"type": "text", "text": final_text})
    return content
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_clips.py -q --color=no; echo "rc=$?"
```
Expected: `24 passed, 1 warning`, `rc=0`.

Spec transcription check. It covers every prompt text, pulled from the spec file itself:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import re, textwrap
SPEC = "docs/superpowers/specs/2026-10-04-judge-clips-design.md"
CHECKS = [("bin/judge-clips", ["3.7", "3.8", "3.9", "4.1#1", "4.5", "4.6"])]
lines = open(SPEC, encoding="utf-8").read().split("\n")
def blocks(section):
    start = next(i for i, l in enumerate(lines) if l.startswith("### " + section + " "))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(("### ", "## "))), len(lines))
    found, i = [], start
    while i < end:
        if lines[i].strip() == "```python":
            j = next(k for k in range(i + 1, end) if lines[k].strip() == "```")
            found.append(textwrap.dedent("\n".join(lines[i + 1:j])))
            i = j
        i += 1
    return found
for target, wants in CHECKS:
    src = open(target, encoding="utf-8").read()
    checked = 0
    for want in wants:
        section, _, index = want.partition("#")
        chosen = blocks(section)
        assert chosen, "no python block under spec " + section
        if index:
            chosen = [chosen[int(index)]]
        for block in chosen:
            for paragraph in re.split(r"\n[ \t]*\n", block):
                if paragraph.strip():
                    assert paragraph.strip() in src, "spec %s paragraph not verbatim in %s:\n%s" % (want, target, paragraph)
                    checked += 1
    print("PASS %s: %d spec paragraphs verbatim (%s)" % (target, checked, ", ".join(wants)))
EOF
```
Expected: `PASS bin/judge-clips: 8 spec paragraphs verbatim (3.7, 3.8, 3.9, 4.1#1, 4.5, 4.6)`.

Mutation checks at the unit level, for these spec 7.4 rows: `MEDIA_TYPE` `"image/png"`; label block after its image block; `number == 1` condition removed; opening-still line without the `image_path` condition; final text always MULTI; final text always SINGLE; audio sentence removed from `SYSTEM_PROMPT`. Task 6 re-runs four of them end to end. The script restores the file itself:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, shutil, subprocess, tempfile
PATH = "bin/judge-clips"
T = "tests/test_judge_clips.py::"
LABEL_THEN_IMAGE = '''            content.append({"type": "text",
                            "text": format_frame_label(clip["panel"], position, frame["t"])})
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": MEDIA_TYPE,
                                       "data": frame["data"]}})
'''
IMAGE_THEN_LABEL = '''            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": MEDIA_TYPE,
                                       "data": frame["data"]}})
            content.append({"type": "text",
                            "text": format_frame_label(clip["panel"], position, frame["t"])})
'''
AUDIO = '''    "The movie also has a soundtrack and spoken narration, but you receive no audio. Do not "
    "judge audio, voice, music, or sound effects. The Narration: text is what is spoken "
    "over that panel's clip.\\n"
    "\\n"
'''
# (label, [(old, new, expected count of old)], [tests that must fail])
MUTATIONS = [
    ("MEDIA_TYPE changed to image/png",
     [('MEDIA_TYPE = "image/jpeg"', 'MEDIA_TYPE = "image/png"', 1)],
     ["test_t8a_build_user_content_two_clips"]),
    ("label block emitted after its image block",
     [(LABEL_THEN_IMAGE, IMAGE_THEN_LABEL, 1)],
     ["test_t8a_build_user_content_two_clips"]),
    ("number == 1 condition removed from the opening-still branch",
     [('    if number == 1 and _text_field(panel, "image_path"):\n', '    if _text_field(panel, "image_path"):\n', 1)],
     ["test_t6_format_panel_text"]),
    ("opening-still line emitted without the image_path condition",
     [('    if number == 1 and _text_field(panel, "image_path"):\n', "    if number == 1:\n", 1)],
     ["test_t6_format_panel_text"]),
    ("final text always MULTI",
     [("    if count >= 2:\n", "    if True:\n", 1)],
     ["test_t8b_build_user_content_one_clip"]),
    ("final text always SINGLE",
     [("    if count >= 2:\n", "    if False:\n", 1)],
     ["test_t8a_build_user_content_two_clips"]),
    ("audio sentence removed from SYSTEM_PROMPT",
     [(AUDIO, "", 1)],
     ["test_t8c_system_prompt_content"]),
]
def run(name):
    # Fresh bytecode cache and TMPDIR per run: a same-size mutation written in the same
    # second as an earlier compile would otherwise load the stale .pyc and falsely
    # "survive", and the mkdtemp mutation must not leave judge-clips-* dirs behind.
    base = tempfile.mkdtemp(prefix="jc-mut-")
    try:
        os.mkdir(os.path.join(base, "tmp"))
        env = dict(os.environ, PYTHONPYCACHEPREFIX=os.path.join(base, "pyc"),
                   TMPDIR=os.path.join(base, "tmp"))
        return subprocess.run(["python3", "-m", "pytest", "-q", "--color=no",
                               "-p", "no:cacheprovider", T + name],
                              capture_output=True, text=True, env=env).returncode
    finally:
        shutil.rmtree(base, ignore_errors=True)
src = open(PATH, encoding="utf-8").read()
caught = 0
for label, edits, tests in MUTATIONS:
    mutated = src
    for old, new, count in edits:
        assert mutated.count(old) == count, "%s: anchor count %d != %d" % (label, mutated.count(old), count)
        mutated = mutated.replace(old, new)
    for name in tests:
        assert run(name) == 0, "control: %s must pass unmutated" % name
    try:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(mutated)
        for name in tests:
            rc = run(name)
            print("[%s] %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation not caught"
            caught += 1
    finally:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(src)
assert open(PATH, encoding="utf-8").read() == src
print("%d mutations, %d CAUGHT; restored bin/judge-clips" % (len(MUTATIONS), caught))
EOF
```
Expected: seven `CAUGHT` lines, then `7 mutations, 7 CAUGHT; restored bin/judge-clips`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
git diff --cached --name-only            # expect: no output
git add -- bin/judge-clips tests/test_judge_clips.py
git diff --cached --name-only            # expect exactly the two paths below
# qwen-agent-workspace/bin/judge-clips
# qwen-agent-workspace/tests/test_judge_clips.py
git commit -F - <<'EOF'
judge-clips: add prompt texts, panel text, frame labels, user content

SYSTEM_PROMPT, TOOL_DESCRIPTION, FINAL_USER_TEXT_SINGLE,
FINAL_USER_TEXT_MULTI_TEMPLATE and RETRY_USER_MESSAGE transcribed
verbatim from spec 3.9/4.1/4.5/4.6 (checked mechanically against the
spec text). format_panel_text() sends Opening still: only for panel 1
with a still, then Motion:/Narration: (spec 3.7); format_frame_label()
labels each frame with its position and time (spec 3.8);
build_user_content() emits per clip a text block then 4 (label, image)
pairs, then a count-stating final text (spec 3.9). Tests T6, T7,
T8a-T8c.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 5: CLI, path resolution, preconditions, clip/panel pairing, PATH check, key gate, and pipeline_log wiring

**Files:**
- Modify: `bin/judge-clips`. Append `build_parser`, `resolve_paths`, an interim `main`, `_pipeline_log_story_dir`, and the `__main__` guard at the end of the file (468 lines at the end of this task).
  - The interim `main` implements spec 1.2 steps 1-12, which is spec 1.4 verbatim through the key check.
  - It then raises `NotImplementedError("frame extraction and the judging call are added by plan Task 6")`.
- Test: append to `tests/test_judge_clips.py`. This adds tests T1a, T1b, T2, T14a-T14o, T15, and T24 (798 lines at the end of this task). It also adds these helpers:
  - `_dummy`, `_make_story`, `_listing`;
  - `_FakeAnthropic` and `_install_fake`, copied from `tests/test_judge_stills.py` and retargeted to `judge_clips`;
  - `_no_subprocess`, `_no_tempdir`, `_run_precondition`.

**Interfaces:**
- Consumes:
  - From `bin/judge-clips`: `WS`, `MAX_CLIPS`, `_panel_list` (Task 1); `find_clips`, `load_manifest_panels`, `ManifestError` (Task 2).
  - Test fixtures `PANEL_1`, `PANEL_2`, `_manifest` (Task 2) and `synthetic_clips` (Task 3).
- Produces in `bin/judge-clips`:
  - `build_parser() -> argparse.ArgumentParser`;
  - `resolve_paths(story_id) -> (story_dir, clips_dir, manifest_path)`;
  - `main(argv=None) -> int`;
  - `_pipeline_log_story_dir(argv) -> str | None`;
  - the `__main__` block.
- No test reaches the interim `NotImplementedError` line: every Task 5 test returns at step 1, 3-11, or 12. Task 6 consumes `main`'s locals `args`, `story_dir`, `clips_dir`, `manifest_path`, `clips`, `numbers`, and `panels_by_index`.
- Test helpers produced:
  - `_dummy(n)`;
  - `_make_story(tmp_path, monkeypatch, manifest=_manifest([PANEL_1, PANEL_2]), clips={1: 25, 2: 3}, story_id=STORY_ID, with_clips_dir=True, synthetic=None) -> pathlib.Path`, which also patches `judge_clips.WS`;
  - `_listing(directory)`;
  - `_FakeAnthropic` (with `.constructions`, `.calls`, and `.messages.create(**kwargs)`) and `_install_fake(monkeypatch, scripted)`;
  - `_no_subprocess(monkeypatch)`, `_no_tempdir(monkeypatch)`;
  - `_run_precondition(monkeypatch, capsys, story_dir, story_id=STORY_ID) -> str` (stderr).

  Tasks 6-7 use `_make_story`, `_listing`, and `_install_fake`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_judge_clips.py` (the block starts with two empty lines):

```python


# --- shared fixtures for main() tests -------------------------------------------------

def _dummy(n):
    """Placeholder clip bytes for precondition tests: nothing decodes a clip before E14."""
    return b"dummy clip %d" % n


def _make_story(tmp_path, monkeypatch, manifest=_manifest([PANEL_1, PANEL_2]), clips={1: 25, 2: 3},
                story_id=STORY_ID, with_clips_dir=True, synthetic=None):
    """Build tmp_path/generated/stories/<story_id>/ and point judge_clips.WS at tmp_path
    (spec 7.1). manifest: a dict or list is written with json.dumps, a str as-is, bytes
    with write_bytes; None writes no manifest.json. Unless with_clips_dir is False,
    clips/ is created, and each (number, spec) in clips becomes clips/panel_%02d.mp4 (a
    str number is used verbatim as the filename): an int spec copies synthetic[spec], a
    bytes spec is written as-is. Returns the story directory as a pathlib.Path."""
    monkeypatch.setattr(judge_clips, "WS", str(tmp_path))
    story_dir = tmp_path / "generated" / "stories" / story_id
    story_dir.mkdir(parents=True)
    manifest_path = story_dir / "manifest.json"
    if isinstance(manifest, (dict, list)):
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif isinstance(manifest, str):
        manifest_path.write_text(manifest, encoding="utf-8")
    elif isinstance(manifest, bytes):
        manifest_path.write_bytes(manifest)
    if with_clips_dir:
        clips_dir = story_dir / "clips"
        clips_dir.mkdir()
        for number, spec in clips.items():
            name = number if isinstance(number, str) else "panel_%02d.mp4" % number
            if isinstance(spec, int):
                shutil.copyfile(synthetic[spec], str(clips_dir / name))
            else:
                (clips_dir / name).write_bytes(spec)
    return story_dir


def _listing(directory):
    """Every path under directory, relative and sorted, to prove nothing was written."""
    return sorted(os.path.relpath(os.path.join(root, name), directory)
                  for root, dirs, files in os.walk(directory) for name in dirs + files)


class _FakeAnthropic:
    """Stands in for anthropic.Anthropic. Calling it records the construction and returns
    itself as the client; .messages.create(**kwargs) records kwargs and returns (or
    raises, for exception instances) the scripted items in order."""

    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.constructions = []
        self.calls = []
        self.messages = types.SimpleNamespace(create=self._create)

    def __call__(self, *args, **kwargs):
        self.constructions.append((args, kwargs))
        return self

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.scripted.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _install_fake(monkeypatch, scripted):
    fake = _FakeAnthropic(scripted)
    monkeypatch.setattr(judge_clips.anthropic, "Anthropic", fake)
    return fake


def _no_subprocess(monkeypatch):
    def _forbidden(*args, **kwargs):
        raise AssertionError("subprocess ran")
    monkeypatch.setattr(judge_clips.subprocess, "run", _forbidden)


def _no_tempdir(monkeypatch):
    def _forbidden(*args, **kwargs):
        raise AssertionError("temporary directory created")
    monkeypatch.setattr(judge_clips.tempfile, "TemporaryDirectory", _forbidden)


def _run_precondition(monkeypatch, capsys, story_dir, story_id=STORY_ID):
    """The spec 7.2 T14 harness. No subprocess or temporary directory may be created, a
    recording fake client is installed, and the key IS set, so a check that wrongly ran
    after the key gate would still trip a guard. Asserts exit 2, empty stdout, no client
    constructed, and (when story_dir is given) nothing written. Returns stderr."""
    _no_subprocess(monkeypatch)
    _no_tempdir(monkeypatch)
    fake = _install_fake(monkeypatch, [])
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    before = _listing(story_dir) if story_dir is not None else None
    assert judge_clips.main(["--story-id", story_id]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert fake.constructions == []
    if story_dir is not None:
        assert _listing(story_dir) == before
    return err


# --- T1, T2, T14, T15, T24: arguments, paths, preconditions, key gate, wiring ----------

def test_t1a_no_args_exit_2():
    with pytest.raises(SystemExit) as exc:
        judge_clips.main([])
    assert exc.value.code == 2


def test_t1b_unknown_flag_exit_2():
    with pytest.raises(SystemExit) as exc:
        judge_clips.main(["--story-md", "x"])
    assert exc.value.code == 2


def test_t2_resolve_paths(monkeypatch, tmp_path):
    assert judge_clips.WS == WS
    base = os.path.join(WS, "generated", "stories", "abc")
    assert judge_clips.resolve_paths("abc") == (
        base, os.path.join(base, "clips"), os.path.join(base, "manifest.json"))
    # WS is read at call time, not import time (spec 2.2).
    monkeypatch.setattr(judge_clips, "WS", str(tmp_path))
    assert judge_clips.resolve_paths("abc")[0] == os.path.join(
        str(tmp_path), "generated", "stories", "abc")


def test_t14a_missing_clips_dir(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, clips={}, with_clips_dir=False)
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == "Error: clips directory not found: %s\n" % (story_dir / "clips")


def test_t14b_no_matching_clips(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, clips={
        "panel_1.mp4": _dummy(1), "panel_01.mp4.provenance.json": b"{}",
        "panel_02.chainseed.png": b"png"})
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == "Error: no panel_NN.mp4 clips found in %s\n" % (story_dir / "clips")


def test_t14c_duplicate_clip_number(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, manifest=_manifest([PANEL_1]),
                            clips={1: _dummy(1), "panel_001.mp4": _dummy(1)})
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == ("Error: more than one clip for panel 1 in %s: panel_001.mp4, panel_01.mp4\n"
                   % (story_dir / "clips"))


def test_t14d_more_than_25_clips(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, manifest=None,
                            clips={n: _dummy(n) for n in range(1, 27)})
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == ("Error: 26 clips found in %s; judge-clips sends 4 frames per clip in one "
                   "request and judges at most 25 clips (100 images, the Anthropic API's "
                   "per-request image limit for 200k-context models).\n" % (story_dir / "clips"))


def test_t14e_exactly_25_clips_passes_cap(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, manifest=None,
                            clips={n: _dummy(n) for n in range(1, 26)})
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == "Error: manifest.json not found: %s\n" % (story_dir / "manifest.json")


def test_t14f_missing_manifest(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, manifest=None, clips={1: _dummy(1)})
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == "Error: manifest.json not found: %s\n" % (story_dir / "manifest.json")


def test_t14g_manifest_not_valid_json(tmp_path, monkeypatch, capsys):
    for i, manifest in enumerate(("{not json", b"\xff\xfe{}")):
        story_id = "bad-json-%d" % i
        story_dir = _make_story(tmp_path, monkeypatch, manifest=manifest,
                                clips={1: _dummy(1)}, story_id=story_id)
        err = _run_precondition(monkeypatch, capsys, story_dir, story_id=story_id)
        assert err.startswith("Error: manifest.json is not valid JSON: %s: "
                              % (story_dir / "manifest.json"))
        assert err.endswith("\n") and err.count("\n") == 1


def test_t14h_manifest_without_panels_list(tmp_path, monkeypatch, capsys):
    for i, manifest in enumerate(([], {}, {"panels": {}}, {"panels": []})):
        story_id = "no-panels-%d" % i
        story_dir = _make_story(tmp_path, monkeypatch, manifest=manifest,
                                clips={1: _dummy(1)}, story_id=story_id)
        err = _run_precondition(monkeypatch, capsys, story_dir, story_id=story_id)
        assert err == ("Error: manifest.json has no panels list: %s\n"
                       % (story_dir / "manifest.json"))


def test_t14i_panel_entry_without_integer_index(tmp_path, monkeypatch, capsys):
    cases = [({"panels": [{"title": "x"}]}, 1),
             ({"panels": [{"index": 1}, {"index": "2"}]}, 2),
             ({"panels": [{"index": True}]}, 1),
             ({"panels": ["panel"]}, 1)]
    for i, (manifest, position) in enumerate(cases):
        story_id = "bad-index-%d" % i
        story_dir = _make_story(tmp_path, monkeypatch, manifest=manifest,
                                clips={1: _dummy(1)}, story_id=story_id)
        err = _run_precondition(monkeypatch, capsys, story_dir, story_id=story_id)
        assert err == ("Error: manifest.json panel entry %d has no integer index: %s\n"
                       % (position, story_dir / "manifest.json"))


def test_t14j_duplicate_manifest_index(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch,
                            manifest={"panels": [{"index": 1}, {"index": 1}]},
                            clips={1: _dummy(1)})
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == ("Error: manifest.json lists panel index 1 more than once: %s\n"
                   % (story_dir / "manifest.json"))


def test_t14k_extra_clip(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch,
                            clips={1: _dummy(1), 2: _dummy(2), 3: _dummy(3)})
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == ("Error: clips with no matching panel in manifest.json: panel_03.mp4; the "
                   "clips in %s may be stale relative to manifest.json.\n" % (story_dir / "clips"))


def test_t14l_partial_render(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch,
                            manifest=_manifest([{"index": i} for i in (1, 2, 3, 4)]),
                            clips={1: _dummy(1), 3: _dummy(3)})
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == ("Error: manifest.json panels with no rendered clip in %s: 2, 4; "
                   "judge-clips judges only complete renders.\n" % (story_dir / "clips"))


def test_t14m_nonexistent_story(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(judge_clips, "WS", str(tmp_path))
    story_id = "judge-clips-test-nonexistent-%s" % uuid.uuid4().hex
    err = _run_precondition(monkeypatch, capsys, None, story_id=story_id)
    assert err.startswith("Error: clips directory not found:")
    assert not (tmp_path / "generated").exists()


def test_t14n_ffmpeg_or_ffprobe_missing(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, clips={1: _dummy(1), 2: _dummy(2)})
    monkeypatch.setattr(judge_clips.shutil, "which",
                        lambda t: None if t == "ffprobe" else "/bin/" + t)
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == ("Error: ffprobe not found on PATH; judge-clips needs ffmpeg and ffprobe "
                   "to extract frames.\n")
    # Both missing: ffmpeg is reported, which pins the check order.
    monkeypatch.setattr(judge_clips.shutil, "which", lambda t: None)
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == ("Error: ffmpeg not found on PATH; judge-clips needs ffmpeg and ffprobe "
                   "to extract frames.\n")


def test_t14o_extra_clip_reported_before_missing(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, clips={1: _dummy(1), 3: _dummy(3)})
    err = _run_precondition(monkeypatch, capsys, story_dir)
    assert err == ("Error: clips with no matching panel in manifest.json: panel_03.mp4; the "
                   "clips in %s may be stale relative to manifest.json.\n" % (story_dir / "clips"))


def test_t15_key_unset_runs_nothing(tmp_path, monkeypatch, capsys, synthetic_clips):
    story_dir = _make_story(tmp_path, monkeypatch, synthetic=synthetic_clips)
    before = _listing(story_dir)
    _no_subprocess(monkeypatch)
    _no_tempdir(monkeypatch)
    fake = _install_fake(monkeypatch, [])
    expected_err = ("Error: ANTHROPIC_API_KEY is not set; export it in your environment to "
                    "run judge-clips.\n")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert judge_clips.main(["--story-id", STORY_ID]) == 1
    out, err = capsys.readouterr()
    assert err == expected_err
    assert out == ""
    assert fake.constructions == []
    assert fake.calls == []
    # An empty value counts as unset (spec 4.2).
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert judge_clips.main(["--story-id", STORY_ID]) == 1
    out, err = capsys.readouterr()
    assert err == expected_err
    assert out == ""
    assert fake.constructions == []
    assert fake.calls == []
    assert _listing(story_dir) == before


def test_t24_pipeline_log_wiring():
    with open(_SCRIPT_PATH, encoding="utf-8") as f:
        text = f.read()
    assert ('pipeline_log.run_logged("judge-clips", _pipeline_log_story_dir(sys.argv[1:]), '
            'main, sys.argv)') in text
    assert "sys.path.insert(0, WS)" in text
    assert "import pipeline_log" in text
    assert "    sys.exit(main())" not in text
    assert (judge_clips._pipeline_log_story_dir(["--story-id", "abc"])
            == os.path.join(WS, "generated", "stories", "abc"))
    assert judge_clips._pipeline_log_story_dir([]) is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_clips.py -q --color=no; echo "rc=$?"
```
Expected: `20 failed, 24 passed, 1 warning`, `rc=1`. The failures:
- T1a, T1b, T14a-T14o, and T15 fail with `AttributeError: module 'judge_clips' has no attribute 'main'`.
- T2 fails with `... no attribute 'resolve_paths'`.
- T24 fails with `assert 'pipeline_log.run_logged("judge-clips", _pipeline_log_story_dir(sys.argv[1:]), main, sys.argv)' in '#!/usr/bin/env python3...`.

- [ ] **Step 3: Write minimal implementation**

Append this at the end of `bin/judge-clips`, after `build_user_content`'s body. The block starts with two empty lines. Its parts:
- `build_parser` is spec 2.1 verbatim, and `resolve_paths` is spec 2.2 verbatim.
- `main` is spec 1.4 verbatim from `def main(argv=None):` through the key check's `return 1`, then one blank line, then the interim `raise`.
- The last two definitions are spec 1.1's ending, verbatim. The `__main__` line is a single 107-character line; do not wrap it.

```python


def build_parser():
    parser = argparse.ArgumentParser(
        prog="judge-clips",
        description="Judge a story's rendered panel clips with Claude against the manifest text.")
    parser.add_argument("--story-id", dest="story_id", metavar="ID", required=True,
                        help="judge generated/stories/ID/clips/panel_NN.mp4 against "
                             "generated/stories/ID/manifest.json")
    return parser


def resolve_paths(story_id):
    story_dir = os.path.join(WS, "generated", "stories", story_id)
    clips_dir = os.path.join(story_dir, "clips")
    manifest_path = os.path.join(story_dir, "manifest.json")
    return story_dir, clips_dir, manifest_path


def main(argv=None):
    args = build_parser().parse_args(argv)
    story_dir, clips_dir, manifest_path = resolve_paths(args.story_id)

    # Cheap filesystem and manifest checks first; all exit 2 (spec 1.2, 2.3).
    if not os.path.isdir(clips_dir):
        print("Error: clips directory not found: %s" % clips_dir, file=sys.stderr)
        return 2
    clips = find_clips(clips_dir)
    if not clips:
        print("Error: no panel_NN.mp4 clips found in %s" % clips_dir, file=sys.stderr)
        return 2
    numbers = [number for number, _ in clips]
    for number in sorted(set(numbers)):
        if numbers.count(number) > 1:
            names = [os.path.basename(path) for n, path in clips if n == number]
            print("Error: more than one clip for panel %d in %s: %s"
                  % (number, clips_dir, ", ".join(names)), file=sys.stderr)
            return 2
    if len(clips) > MAX_CLIPS:
        print("Error: %d clips found in %s; judge-clips sends 4 frames per clip in one request "
              "and judges at most 25 clips (100 images, the Anthropic API's per-request image "
              "limit for 200k-context models)." % (len(clips), clips_dir), file=sys.stderr)
        return 2
    if not os.path.isfile(manifest_path):
        print("Error: manifest.json not found: %s" % manifest_path, file=sys.stderr)
        return 2
    try:
        panels_by_index = load_manifest_panels(manifest_path)
    except ManifestError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    extra = [os.path.basename(path) for number, path in clips if number not in panels_by_index]
    if extra:
        print("Error: clips with no matching panel in manifest.json: %s; the clips in %s may "
              "be stale relative to manifest.json." % (", ".join(extra), clips_dir),
              file=sys.stderr)
        return 2
    missing = sorted(set(panels_by_index) - set(numbers))
    if missing:
        print("Error: manifest.json panels with no rendered clip in %s: %s; judge-clips "
              "judges only complete renders." % (clips_dir, _panel_list(missing)),
              file=sys.stderr)
        return 2
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            print("Error: %s not found on PATH; judge-clips needs ffmpeg and ffprobe to "
                  "extract frames." % tool, file=sys.stderr)
            return 2

    # Checked before any subprocess runs and before the client exists; the key is never
    # read into a variable (spec 4.2).
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set; export it in your environment to run "
              "judge-clips.", file=sys.stderr)
        return 1

    raise NotImplementedError("frame extraction and the judging call are added by plan Task 6")


def _pipeline_log_story_dir(argv):
    story_id = pipeline_log.argv_value(argv, "--story-id")
    return os.path.join(WS, "generated", "stories", story_id) if story_id else None


if __name__ == "__main__":
    sys.exit(pipeline_log.run_logged("judge-clips", _pipeline_log_story_dir(sys.argv[1:]), main, sys.argv))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_clips.py -q --color=no; echo "rc=$?"
```
Expected: `44 passed, 1 warning`, `rc=0`.

Spec transcription check:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import re, textwrap
SPEC = "docs/superpowers/specs/2026-10-04-judge-clips-design.md"
CHECKS = [("bin/judge-clips", ["1.1", "2.1", "2.2"])]
lines = open(SPEC, encoding="utf-8").read().split("\n")
def blocks(section):
    start = next(i for i, l in enumerate(lines) if l.startswith("### " + section + " "))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(("### ", "## "))), len(lines))
    found, i = [], start
    while i < end:
        if lines[i].strip() == "```python":
            j = next(k for k in range(i + 1, end) if lines[k].strip() == "```")
            found.append(textwrap.dedent("\n".join(lines[i + 1:j])))
            i = j
        i += 1
    return found
for target, wants in CHECKS:
    src = open(target, encoding="utf-8").read()
    checked = 0
    for want in wants:
        section, _, index = want.partition("#")
        chosen = blocks(section)
        assert chosen, "no python block under spec " + section
        if index:
            chosen = [chosen[int(index)]]
        for block in chosen:
            for paragraph in re.split(r"\n[ \t]*\n", block):
                if paragraph.strip():
                    assert paragraph.strip() in src, "spec %s paragraph not verbatim in %s:\n%s" % (want, target, paragraph)
                    checked += 1
    print("PASS %s: %d spec paragraphs verbatim (%s)" % (target, checked, ", ".join(wants)))
EOF
```
Expected: `PASS bin/judge-clips: 5 spec paragraphs verbatim (1.1, 2.1, 2.2)`.

Real-shebang smoke test. It proves the `#!/usr/bin/env python3` interpreter imports `anthropic`, `jsonschema`, and `pipeline_log`. It writes nothing: the story directory does not exist, so `pipeline_log` skips the log.
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && bin/judge-clips --help >/dev/null; echo "help rc=$?"; bin/judge-clips --story-id judge-clips-smoke-nonexistent; echo "missing rc=$?"; bin/judge-clips; echo "noargs rc=$?"
```
Expected output, in order:
1. `help rc=0`.
2. `Error: clips directory not found: /Users/reubenpatterson/local_model_harness/qwen-agent-workspace/generated/stories/judge-clips-smoke-nonexistent/clips` and `missing rc=2`.
3. `usage: judge-clips [-h] --story-id ID`, then `judge-clips: error: the following arguments are required: --story-id`, then `noargs rc=2`.

Mutation checks for these spec 7.4 rows:
- PATH check removed; PATH order swapped;
- duplicate-clip check removed; `MAX_CLIPS` 26; `>` to `>=` (Decision 3);
- `isinstance(index, bool)` exclusion removed;
- E11 removed; E12 removed; E11/E12 order swapped;
- `__main__` reverted to `sys.exit(main())`.

The key-order rows need the extraction block and the client, so they run in Task 6. In this interim `main`, a mutation that lets a T14 case pass its check reaches either the `NotImplementedError` or a guard, so the test fails. The script restores the file itself:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, shutil, subprocess, tempfile
PATH = "bin/judge-clips"
T = "tests/test_judge_clips.py::"
E11 = '''    extra = [os.path.basename(path) for number, path in clips if number not in panels_by_index]
    if extra:
        print("Error: clips with no matching panel in manifest.json: %s; the clips in %s may "
              "be stale relative to manifest.json." % (", ".join(extra), clips_dir),
              file=sys.stderr)
        return 2
'''
E12 = '''    missing = sorted(set(panels_by_index) - set(numbers))
    if missing:
        print("Error: manifest.json panels with no rendered clip in %s: %s; judge-clips "
              "judges only complete renders." % (clips_dir, _panel_list(missing)),
              file=sys.stderr)
        return 2
'''
# (label, [(old, new, expected count of old)], [tests that must fail])
MUTATIONS = [
    ("PATH check (E13) removed",
     [("        if shutil.which(tool) is None:\n", "        if False:\n", 1)],
     ["test_t14n_ffmpeg_or_ffprobe_missing"]),
    ("PATH check order swapped (ffprobe first)",
     [('    for tool in ("ffmpeg", "ffprobe"):\n', '    for tool in ("ffprobe", "ffmpeg"):\n', 1)],
     ["test_t14n_ffmpeg_or_ffprobe_missing"]),
    ("duplicate-clip check (E4) removed",
     [("        if numbers.count(number) > 1:\n", "        if False:\n", 1)],
     ["test_t14c_duplicate_clip_number"]),
    ("MAX_CLIPS changed to 26",
     [("MAX_CLIPS = 25\n", "MAX_CLIPS = 26\n", 1)],
     ["test_t14d_more_than_25_clips"]),
    ("clip cap compared with >= instead of >",
     [("    if len(clips) > MAX_CLIPS:\n", "    if len(clips) >= MAX_CLIPS:\n", 1)],
     ["test_t14e_exactly_25_clips_passes_cap"]),
    ("isinstance(index, bool) exclusion removed",
     [("        if not isinstance(index, int) or isinstance(index, bool):\n", "        if not isinstance(index, int):\n", 1)],
     ["test_t14i_panel_entry_without_integer_index"]),
    ("extra-clip check (E11) removed",
     [('    if extra:\n        print("Error: clips with no matching panel', '    if False:\n        print("Error: clips with no matching panel', 1)],
     ["test_t14k_extra_clip"]),
    ("missing-clip check (E12) removed",
     [('    if missing:\n        print("Error: manifest.json panels with no rendered clip', '    if False:\n        print("Error: manifest.json panels with no rendered clip', 1)],
     ["test_t14l_partial_render"]),
    ("E11 and E12 order swapped",
     [(E11 + E12, E12 + E11, 1)],
     ["test_t14o_extra_clip_reported_before_missing"]),
    ("__main__ reverted to sys.exit(main())",
     [('    sys.exit(pipeline_log.run_logged("judge-clips", _pipeline_log_story_dir(sys.argv[1:]), main, sys.argv))\n',
       "    sys.exit(main())\n", 1)],
     ["test_t24_pipeline_log_wiring"]),
]
def run(name):
    # Fresh bytecode cache and TMPDIR per run: a same-size mutation written in the same
    # second as an earlier compile would otherwise load the stale .pyc and falsely
    # "survive", and the mkdtemp mutation must not leave judge-clips-* dirs behind.
    base = tempfile.mkdtemp(prefix="jc-mut-")
    try:
        os.mkdir(os.path.join(base, "tmp"))
        env = dict(os.environ, PYTHONPYCACHEPREFIX=os.path.join(base, "pyc"),
                   TMPDIR=os.path.join(base, "tmp"))
        return subprocess.run(["python3", "-m", "pytest", "-q", "--color=no",
                               "-p", "no:cacheprovider", T + name],
                              capture_output=True, text=True, env=env).returncode
    finally:
        shutil.rmtree(base, ignore_errors=True)
src = open(PATH, encoding="utf-8").read()
caught = 0
for label, edits, tests in MUTATIONS:
    mutated = src
    for old, new, count in edits:
        assert mutated.count(old) == count, "%s: anchor count %d != %d" % (label, mutated.count(old), count)
        mutated = mutated.replace(old, new)
    for name in tests:
        assert run(name) == 0, "control: %s must pass unmutated" % name
    try:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(mutated)
        for name in tests:
            rc = run(name)
            print("[%s] %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation not caught"
            caught += 1
    finally:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(src)
assert open(PATH, encoding="utf-8").read() == src
print("%d mutations, %d CAUGHT; restored bin/judge-clips" % (len(MUTATIONS), caught))
EOF
```
Expected: ten `CAUGHT` lines, then `10 mutations, 10 CAUGHT; restored bin/judge-clips`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
git diff --cached --name-only            # expect: no output
git add -- bin/judge-clips tests/test_judge_clips.py
git diff --cached --name-only            # expect exactly the two paths below
# qwen-agent-workspace/bin/judge-clips
# qwen-agent-workspace/tests/test_judge_clips.py
git commit -F - <<'EOF'
judge-clips: add CLI, preconditions, clip/panel pairing, and key gate

--story-id (required, the only flag) and resolve_paths() per spec
2.1/2.2. main() runs spec 1.2 steps 1-12: exit 2 for a missing clips/
dir, no panel_NN.mp4, a duplicate clip number, more than 25 clips, a
missing or malformed manifest, a stale extra clip (E11, checked before
E12), a partial render (E12), or ffmpeg/ffprobe not on PATH; then exit 1
for an unset or empty ANTHROPIC_API_KEY before any subprocess or client.
__main__ goes through pipeline_log.run_logged("judge-clips", ...).
Frame extraction and the judging call land next. Tests T1a, T1b, T2,
T14a-T14o, T15, T24.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 6: Frame extraction in main, judging call, validation-failure path, output file, and stdout

**Files:**
- Modify: `bin/judge-clips`, in two edits (602 lines at the end of this task):
  - Insert `find_tool_use`, `CLIP_TABLE_FORMAT`, `format_clip_row`, `format_movie_line`, `_create_message`, and `_write_raw` immediately before `def main(argv=None):`.
  - Replace `main`'s interim `raise NotImplementedError(...)` line with spec 1.4's remainder: the extraction block through `return 0`. For now it has a single API call in place of the retry block.
- Test: append to `tests/test_judge_clips.py`. This adds tests T16, T17, T18, T21a, T21b, T21c, and T25 (1080 lines at the end of this task). It also adds these helpers:
  - `THINKING_BLOCK`, `_usage`, `_message`, `_tool_response`, `_text_response`, copied from `tests/test_judge_stills.py`;
  - `_REAL_TEMPORARY_DIRECTORY`, `_record_tempdirs`, `TWO_CLIP_STDOUT`.

**Interfaces:**
- Consumes:
  - From `bin/judge-clips`: every Task 1-4 symbol; `main`'s locals from Task 5; `probe_clip`, `frame_indices`, `extract_frames`, `ClipError` (Task 3); `format_panel_text`, `build_user_content`, `SYSTEM_PROMPT`, `TOOL_DESCRIPTION` (Task 4).
  - Test helpers `_make_story`, `_listing`, `_install_fake` (Task 5), and `synthetic_clips`, `_frame_number`, `GARBAGE_CLIP` (Task 3).
- Produces:
  - `find_tool_use(response)`;
  - `CLIP_TABLE_FORMAT`;
  - `format_clip_row(entry) -> str`;
  - `format_movie_line(name, value) -> str`;
  - `_create_message(client, messages)`;
  - `_write_raw(story_dir, responses) -> str` (the path of `clips_judgment.raw.json`).
- `main` now runs spec 1.2 steps 13-19 with one API call. A response with no tool call is not handled yet: `block.input` raises `AttributeError` until Task 7 adds the retry.
- Test helpers produced: `THINKING_BLOCK`, `_usage`, `_message`, `_tool_response`, `_text_response`, `_record_tempdirs(monkeypatch) -> list[str]`. Task 7 uses them.

T21a-T21c and T25 sit in this task, not Task 7, because the code they exercise lands here: the `validate_judgment_input(block.input, numbers)` call, the E18 path, and the `int()` output coercion. In Task 7 they would pass before any Task 7 code was written, so they could never go red.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_judge_clips.py` (the block starts with two empty lines):

```python


# --- SDK response builders: real anthropic.types.Message objects (spec 7.1) ----------

THINKING_BLOCK = {"type": "thinking", "thinking": "Comparing the clips to the panel text.",
                  "signature": "sig-abc123"}


def _usage(input_tokens, output_tokens, thinking_tokens):
    """thinking_tokens=None omits output_tokens_details, as when the API does not report it."""
    usage = {"input_tokens": input_tokens, "output_tokens": output_tokens}
    if thinking_tokens is not None:
        usage["output_tokens_details"] = {"thinking_tokens": thinking_tokens}
    return usage


def _message(content, usage, stop_reason):
    return anthropic.types.Message.model_validate({
        "id": "msg_test_%s" % uuid.uuid4().hex, "type": "message", "role": "assistant",
        "model": "claude-opus-5-5", "stop_reason": stop_reason, "stop_sequence": None,
        "content": content, "usage": usage})


def _tool_response(tool_input, usage):
    return _message([THINKING_BLOCK, {"type": "tool_use", "id": "toolu_test",
                                      "name": "submit_judgment", "input": tool_input}],
                    usage, "tool_use")


def _text_response(text, usage):
    return _message([THINKING_BLOCK, {"type": "text", "text": text}], usage, "end_turn")


_REAL_TEMPORARY_DIRECTORY = tempfile.TemporaryDirectory


def _record_tempdirs(monkeypatch):
    """Wrap the real tempfile.TemporaryDirectory (captured at import, before any patch)
    so each directory judge-clips creates is recorded. Returns the list of names."""
    created = []

    def _recording(*args, **kwargs):
        tmp = _REAL_TEMPORARY_DIRECTORY(*args, **kwargs)
        created.append(tmp.name)
        return tmp
    monkeypatch.setattr(judge_clips.tempfile, "TemporaryDirectory", _recording)
    return created


TWO_CLIP_STDOUT = ("Clip scores:\n"
                   "  panel  motion_fidelity   physical_realism  temporal_stability\n"
                   "  1      7                 6                 8\n"
                   "  2      4                 3                 5\n"
                   "\n"
                   "Movie scores:\n"
                   "  seam_continuity       9\n"
                   "  narrative_clarity     2\n"
                   "\n"
                   "--- Critique ---\n")


# --- T16-T18, T21, T25: extraction in main, judging call, outputs (spec 1.4, 4-6) ----

def test_t16_extraction_failure(tmp_path, monkeypatch, capsys, synthetic_clips):
    story_dir = _make_story(tmp_path, monkeypatch, clips={1: 25, 2: GARBAGE_CLIP},
                            synthetic=synthetic_clips)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    fake = _install_fake(monkeypatch, [])
    created = _record_tempdirs(monkeypatch)
    before = _listing(story_dir)

    assert judge_clips.main(["--story-id", STORY_ID]) == 1

    out, err = capsys.readouterr()
    assert err.startswith("Error: frame extraction failed: ffprobe failed on %s (exit 1): "
                          % (story_dir / "clips" / "panel_02.mp4"))
    assert out == ""
    assert fake.constructions == []
    assert len(created) == 1
    assert not os.path.exists(created[0])
    assert _listing(story_dir) == before


def test_t17_successful_run_two_clips(tmp_path, monkeypatch, capsys, synthetic_clips):
    story_dir = _make_story(tmp_path, monkeypatch, synthetic=synthetic_clips)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    created = _record_tempdirs(monkeypatch)
    clips_before = _listing(story_dir / "clips")
    fake = _install_fake(monkeypatch, [
        _tool_response(copy.deepcopy(VALID_INPUT), _usage(1200, 3400, 2100))])

    assert judge_clips.main(["--story-id", STORY_ID]) == 0

    with open(story_dir / "clips_judgment.json", encoding="utf-8") as f:
        raw_text = f.read()
    judgment = json.loads(raw_text)
    assert list(judgment) == ["story_id", "model", "effort", "timestamp", "frames_per_clip",
                              "usage", "clips", "movie", "critique"]
    assert judgment["story_id"] == STORY_ID
    assert judgment["model"] == "claude-opus-5-5"
    assert judgment["effort"] == "high"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", judgment["timestamp"])
    assert judgment["frames_per_clip"] == 4
    assert judgment["usage"] == {"input_tokens": 1200, "output_tokens": 3400,
                                 "thinking_tokens": 2100}
    assert judgment["clips"] == [
        {"panel": 1, "frames": [0, 8, 16, 24], "motion_fidelity": 7, "physical_realism": 6,
         "temporal_stability": 8},
        {"panel": 2, "frames": [0, 1, 1, 2], "motion_fidelity": 4, "physical_realism": 3,
         "temporal_stability": 5}]
    for entry in judgment["clips"]:
        assert list(entry) == ["panel", "frames", "motion_fidelity", "physical_realism",
                               "temporal_stability"]
    assert judgment["movie"] == {"seam_continuity": 9, "narrative_clarity": 2}
    assert list(judgment["movie"]) == ["seam_continuity", "narrative_clarity"]
    assert judgment["critique"] == VALID_INPUT["critique"]
    assert "—" in raw_text                 # ensure_ascii=False
    assert raw_text.endswith("}\n")        # trailing newline after json.dump
    for name in ("clips_judgment.raw.json", "judgment.json", "stills_judgment.json"):
        assert not (story_dir / name).exists(), name

    out, err = capsys.readouterr()
    assert out == TWO_CLIP_STDOUT + VALID_INPUT["critique"] + "\n"
    assert err == ""

    assert fake.constructions == [((), {})]               # Anthropic() with no arguments
    assert len(fake.calls) == 1
    kwargs = fake.calls[0]
    assert sorted(kwargs) == ["max_tokens", "messages", "model", "output_config", "system",
                              "thinking", "tool_choice", "tools"]
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["max_tokens"] == 21333
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"] == {"effort": "high"}
    assert kwargs["tool_choice"] == {"type": "auto"}
    assert kwargs["system"] == judge_clips.SYSTEM_PROMPT
    assert [tool["name"] for tool in kwargs["tools"]] == ["submit_judgment"]
    assert kwargs["tools"][0]["input_schema"] == judge_clips.SUBMIT_JUDGMENT_SCHEMA
    assert kwargs["tools"][0]["description"] == judge_clips.TOOL_DESCRIPTION
    messages = kwargs["messages"]
    assert len(messages) == 1 and messages[0]["role"] == "user"
    content = messages[0]["content"]
    assert [block["type"] for block in content] == (
        ["text"] + ["text", "image"] * 4 + ["text"] + ["text", "image"] * 4 + ["text"])
    assert content[0]["text"] == judge_clips.format_panel_text(1, PANEL_1)
    assert content[9]["text"] == judge_clips.format_panel_text(2, PANEL_2)
    # 24-fps values; the manifest's fps of 30 would give 0.27, 0.53, 0.80 and 0.03, 0.03, 0.07.
    assert [content[i]["text"] for i in (1, 3, 5, 7)] == [
        "Panel 1, frame 1 of 4 (t=0.00s)", "Panel 1, frame 2 of 4 (t=0.33s)",
        "Panel 1, frame 3 of 4 (t=0.67s)", "Panel 1, frame 4 of 4 (t=1.00s)"]
    assert [content[i]["text"] for i in (10, 12, 14, 16)] == [
        "Panel 2, frame 1 of 4 (t=0.00s)", "Panel 2, frame 2 of 4 (t=0.04s)",
        "Panel 2, frame 3 of 4 (t=0.04s)", "Panel 2, frame 4 of 4 (t=0.08s)"]
    for i in (2, 4, 6, 8, 11, 13, 15, 17):
        assert content[i]["source"]["type"] == "base64"
        assert content[i]["source"]["media_type"] == "image/jpeg"
    assert [_frame_number(base64.b64decode(content[i]["source"]["data"]), tmp_path)
            for i in (2, 4, 6, 8)] == [0, 8, 16, 24]
    assert [_frame_number(base64.b64decode(content[i]["source"]["data"]), tmp_path)
            for i in (11, 13, 15, 17)] == [0, 1, 1, 2]
    assert content[18]["text"] == judge_clips.FINAL_USER_TEXT_MULTI_TEMPLATE % 2

    assert len(created) == 1
    assert os.path.basename(created[0]).startswith("judge-clips-")
    assert not os.path.exists(created[0])
    assert not os.path.realpath(created[0]).startswith(os.path.realpath(str(story_dir)))
    assert _listing(story_dir / "clips") == clips_before


def test_t18_successful_run_one_clip(tmp_path, monkeypatch, capsys, synthetic_clips):
    story_dir = _make_story(tmp_path, monkeypatch, manifest=_manifest([PANEL_1]),
                            clips={1: 1}, synthetic=synthetic_clips)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    fake = _install_fake(monkeypatch, [
        _tool_response(copy.deepcopy(ONE_CLIP_INPUT), _usage(900, 2500, 1500))])

    assert judge_clips.main(["--story-id", STORY_ID]) == 0

    with open(story_dir / "clips_judgment.json", encoding="utf-8") as f:
        raw_text = f.read()
    judgment = json.loads(raw_text)
    assert judgment["clips"] == [{"panel": 1, "frames": [0, 0, 0, 0], "motion_fidelity": 7,
                                  "physical_realism": 6, "temporal_stability": 8}]
    assert judgment["movie"] == {"seam_continuity": None, "narrative_clarity": 2}
    assert '"seam_continuity": null' in raw_text
    out, err = capsys.readouterr()
    assert out == ("Clip scores:\n"
                   "  panel  motion_fidelity   physical_realism  temporal_stability\n"
                   "  1      7                 6                 8\n"
                   "\n"
                   "Movie scores:\n"
                   "  seam_continuity       n/a (only 1 clip)\n"
                   "  narrative_clarity     2\n"
                   "\n"
                   "--- Critique ---\n" + ONE_CLIP_INPUT["critique"] + "\n")
    assert err == ""
    assert len(fake.calls) == 1                       # a valid tool_use: no retry
    content = fake.calls[0]["messages"][0]["content"]
    assert len(content) == 10
    assert len({content[i]["source"]["data"] for i in (2, 4, 6, 8)}) == 1
    assert [content[i]["text"] for i in (1, 3, 5, 7)] == [
        "Panel 1, frame %d of 4 (t=0.00s)" % k for k in (1, 2, 3, 4)]
    assert content[9]["text"] == judge_clips.FINAL_USER_TEXT_SINGLE


def test_t21a_schema_invalid_tool_input(tmp_path, monkeypatch, capsys, synthetic_clips):
    story_dir = _make_story(tmp_path, monkeypatch, synthetic=synthetic_clips)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    bad = copy.deepcopy(VALID_INPUT)
    bad["clips"][0]["temporal_stability"] = 11            # clips[0] is panel 2
    fake = _install_fake(monkeypatch, [_tool_response(bad, _usage(10, 20, 5))])

    assert judge_clips.main(["--story-id", STORY_ID]) == 1

    assert len(fake.calls) == 1            # no retry on a validation failure
    with open(story_dir / "clips_judgment.raw.json", encoding="utf-8") as f:
        raw = json.load(f)
    assert len(raw["responses"]) == 1
    assert not (story_dir / "clips_judgment.json").exists()
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("Error: submit_judgment input failed schema validation: ")


def test_t21b_missing_judged_panel(tmp_path, monkeypatch, capsys, synthetic_clips):
    story_dir = _make_story(tmp_path, monkeypatch, synthetic=synthetic_clips)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    partial = copy.deepcopy(VALID_INPUT)
    partial["clips"] = [partial["clips"][1]]               # panel 1 only
    fake = _install_fake(monkeypatch, [_tool_response(partial, _usage(10, 20, 5))])

    assert judge_clips.main(["--story-id", STORY_ID]) == 1

    assert len(fake.calls) == 1
    with open(story_dir / "clips_judgment.raw.json", encoding="utf-8") as f:
        assert len(json.load(f)["responses"]) == 1
    assert not (story_dir / "clips_judgment.json").exists()
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ("Error: submit_judgment input failed schema validation: clips is missing "
                   "these judged panels: 2\n")


def test_t21c_two_clips_missing_seam(tmp_path, monkeypatch, capsys, synthetic_clips):
    story_dir = _make_story(tmp_path, monkeypatch, synthetic=synthetic_clips)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    no_seam = copy.deepcopy(VALID_INPUT)
    del no_seam["movie"]["seam_continuity"]
    fake = _install_fake(monkeypatch, [_tool_response(no_seam, _usage(10, 20, 5))])

    assert judge_clips.main(["--story-id", STORY_ID]) == 1

    assert len(fake.calls) == 1
    with open(story_dir / "clips_judgment.raw.json", encoding="utf-8") as f:
        assert len(json.load(f)["responses"]) == 1
    assert not (story_dir / "clips_judgment.json").exists()
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ("Error: submit_judgment input failed schema validation: seam_continuity "
                   "is required when judging 2 or more clips\n")


def test_t25_float_scores_written_as_integers(tmp_path, monkeypatch, capsys, synthetic_clips):
    story_dir = _make_story(tmp_path, monkeypatch, manifest=_manifest([PANEL_1]),
                            clips={1: 1}, synthetic=synthetic_clips)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    _install_fake(monkeypatch, [_tool_response(
        {"clips": [{"panel": 1.0, "motion_fidelity": 7.0, "physical_realism": 6.0,
                    "temporal_stability": 8.0}],
         "movie": {"narrative_clarity": 2.0}, "critique": "c"}, _usage(10, 20, 5))])

    assert judge_clips.main(["--story-id", STORY_ID]) == 0

    with open(story_dir / "clips_judgment.json", encoding="utf-8") as f:
        raw_text = f.read()
    judgment = json.loads(raw_text)
    for entry in judgment["clips"]:
        for key in ("panel", "motion_fidelity", "physical_realism", "temporal_stability"):
            assert type(entry[key]) is int, key
    assert type(judgment["movie"]["narrative_clarity"]) is int
    assert judgment["movie"]["seam_continuity"] is None
    assert '"panel": 1,' in raw_text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_clips.py -q --color=no; echo "rc=$?"
```
Expected: `7 failed, 44 passed, 1 warning`, `rc=1`. T16, T17, T18, T21a, T21b, T21c, and T25 each fail with `NotImplementedError: frame extraction and the judging call are added by plan Task 6`.

- [ ] **Step 3: Write minimal implementation**

Edit 1 uses the Edit tool on `bin/judge-clips`. The parts:
- `find_tool_use` is copied from `bin/judge-stills`, docstring included.
- The `CLIP_TABLE_FORMAT` / `format_clip_row` / `format_movie_line` block is spec 5.3 verbatim.
- `_create_message` is spec 4.1 verbatim, with no docstring (Decision 6).
- `_write_raw` is spec 5.2 verbatim.

old_string:
```python
def main(argv=None):
```
new_string:
```python
def find_tool_use(response):
    """First content block that is a submit_judgment tool call, else None."""
    for block in response.content:
        if block.type == "tool_use" and block.name == TOOL_NAME:
            return block
    return None


CLIP_TABLE_FORMAT = "  %-5s  %-16s  %-16s  %s"


def format_clip_row(entry):
    return CLIP_TABLE_FORMAT % (entry["panel"], entry["motion_fidelity"],
                                entry["physical_realism"], entry["temporal_stability"])


def format_movie_line(name, value):
    """None is reached only for seam_continuity when exactly 1 clip was judged."""
    if value is None:
        return "  %-20s  n/a (only 1 clip)" % name
    return "  %-20s  %d" % (name, value)


def _create_message(client, messages):
    return client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": EFFORT},
        system=SYSTEM_PROMPT,
        tools=[{
            "name": TOOL_NAME,
            "description": TOOL_DESCRIPTION,
            "input_schema": SUBMIT_JUDGMENT_SCHEMA,
        }],
        tool_choice={"type": "auto"},
        messages=messages,
    )


def _write_raw(story_dir, responses):
    path = os.path.join(story_dir, "clips_judgment.raw.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"responses": [r.model_dump(mode="json") for r in responses]}, f,
                  indent=2, ensure_ascii=False)
    return path


def main(argv=None):
```

Edit 2 uses the Edit tool on `bin/judge-clips`. new_string is spec 1.4 verbatim from `clip_inputs = []` to `return 0`, with one exception: where spec 1.4 has the `responses = []` / `try:` retry block, this task has the two-line single call. Task 7 swaps that in.

old_string:
```python
    raise NotImplementedError("frame extraction and the judging call are added by plan Task 6")
```
new_string:
```python
    clip_inputs = []
    frames_by_panel = {}
    try:
        with tempfile.TemporaryDirectory(prefix="judge-clips-") as tmp_dir:
            for number, path in clips:
                frame_count, fps = probe_clip(path)
                indices = frame_indices(frame_count)
                out_dir = os.path.join(tmp_dir, "panel_%02d" % number)
                os.mkdir(out_dir)
                images = extract_frames(path, indices, out_dir)
                frames_by_panel[number] = indices
                clip_inputs.append({
                    "panel": number,
                    "text": format_panel_text(number, panels_by_index[number]),
                    "frames": [{"t": float(index / fps),
                                "data": base64.standard_b64encode(data).decode("ascii")}
                               for index, data in zip(indices, images)],
                })
    except ClipError as e:
        print("Error: frame extraction failed: %s" % e, file=sys.stderr)
        return 1
    user_content = build_user_content(clip_inputs)
    client = anthropic.Anthropic()

    responses = [_create_message(client, [{"role": "user", "content": user_content}])]
    block = find_tool_use(responses[0])
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        validate_judgment_input(block.input, numbers)
    except jsonschema.ValidationError as e:
        _write_raw(story_dir, responses)
        print("Error: submit_judgment input failed schema validation: %s" % e.message,
              file=sys.stderr)
        return 1

    tool_input = block.input
    movie = tool_input["movie"]
    thinking_counts = [r.usage.output_tokens_details.thinking_tokens for r in responses
                       if r.usage.output_tokens_details is not None
                       and r.usage.output_tokens_details.thinking_tokens is not None]
    judgment = {
        "story_id": args.story_id,
        "model": MODEL,
        "effort": EFFORT,
        "timestamp": timestamp,
        "frames_per_clip": FRAMES_PER_CLIP,
        "usage": {
            "input_tokens": sum(r.usage.input_tokens for r in responses),
            "output_tokens": sum(r.usage.output_tokens for r in responses),
            "thinking_tokens": sum(thinking_counts) if thinking_counts else None,
        },
        # int(): jsonschema accepts 7.0 as an integer; the file always holds JSON integers
        # (spec 5.1). Sorted by panel regardless of the order the judge listed them.
        "clips": [
            {"panel": int(entry["panel"]),
             "frames": frames_by_panel[int(entry["panel"])],
             "motion_fidelity": int(entry["motion_fidelity"]),
             "physical_realism": int(entry["physical_realism"]),
             "temporal_stability": int(entry["temporal_stability"])}
            for entry in sorted(tool_input["clips"], key=lambda entry: entry["panel"])
        ],
        "movie": {
            # Absent (-> JSON null) only in the 1-clip case; validation rejects every other
            # absence and every 1-clip presence (spec 4.4).
            "seam_continuity": (int(movie["seam_continuity"]) if "seam_continuity" in movie
                                else None),
            "narrative_clarity": int(movie["narrative_clarity"]),
        },
        "critique": tool_input["critique"],
    }
    with open(os.path.join(story_dir, "clips_judgment.json"), "w", encoding="utf-8") as f:
        json.dump(judgment, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print("Clip scores:")
    print(CLIP_TABLE_FORMAT % (("panel",) + CLIP_SCORE_KEYS))
    for entry in judgment["clips"]:
        print(format_clip_row(entry))
    print()
    print("Movie scores:")
    for name in MOVIE_SCORE_KEYS:
        print(format_movie_line(name, judgment["movie"][name]))
    print()
    print("--- Critique ---")
    print(judgment["critique"])
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_clips.py -q --color=no; echo "rc=$?"
```
Expected: `51 passed, 1 warning`, `rc=0`.

Spec transcription check:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import re, textwrap
SPEC = "docs/superpowers/specs/2026-10-04-judge-clips-design.md"
CHECKS = [("bin/judge-clips", ["4.1#0", "5.2", "5.3"])]
lines = open(SPEC, encoding="utf-8").read().split("\n")
def blocks(section):
    start = next(i for i, l in enumerate(lines) if l.startswith("### " + section + " "))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(("### ", "## "))), len(lines))
    found, i = [], start
    while i < end:
        if lines[i].strip() == "```python":
            j = next(k for k in range(i + 1, end) if lines[k].strip() == "```")
            found.append(textwrap.dedent("\n".join(lines[i + 1:j])))
            i = j
        i += 1
    return found
for target, wants in CHECKS:
    src = open(target, encoding="utf-8").read()
    checked = 0
    for want in wants:
        section, _, index = want.partition("#")
        chosen = blocks(section)
        assert chosen, "no python block under spec " + section
        if index:
            chosen = [chosen[int(index)]]
        for block in chosen:
            for paragraph in re.split(r"\n[ \t]*\n", block):
                if paragraph.strip():
                    assert paragraph.strip() in src, "spec %s paragraph not verbatim in %s:\n%s" % (want, target, paragraph)
                    checked += 1
    print("PASS %s: %d spec paragraphs verbatim (%s)" % (target, checked, ", ".join(wants)))
EOF
```
Expected: `PASS bin/judge-clips: 5 spec paragraphs verbatim (4.1#0, 5.2, 5.3)`. Spec 1.4 as a whole is checked after Task 7, once the retry block is in.

Mutation checks. These cover the rows owned by this task:
- key check moved after the extraction block / after `anthropic.Anthropic()`;
- fps from the manifest;
- output `clips` not sorted;
- `int()` coercion removed;
- seam read with no presence check;
- `format_movie_line` without its `None` branch;
- `TemporaryDirectory` replaced by `mkdtemp`;
- frames written into `clips/`;
- output named `stills_judgment.json`.

They also re-run these Task 1, 3, and 4 rows end to end through T17, T18, T21b, and T21c: passthrough, dedup, `MEDIA_TYPE`, label order, always MULTI, always SINGLE, `seam_continuity` in `movie.required`, missing-panel validation, and seam `>= 2`. The script restores the file itself:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, shutil, subprocess, tempfile
PATH = "bin/judge-clips"
T = "tests/test_judge_clips.py::"
KEY = '''    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set; export it in your environment to run "
              "judge-clips.", file=sys.stderr)
        return 1
'''
USER_CONTENT = "    user_content = build_user_content(clip_inputs)\n"
CLIENT = "    client = anthropic.Anthropic()\n"
LABEL_THEN_IMAGE = '''            content.append({"type": "text",
                            "text": format_frame_label(clip["panel"], position, frame["t"])})
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": MEDIA_TYPE,
                                       "data": frame["data"]}})
'''
IMAGE_THEN_LABEL = '''            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": MEDIA_TYPE,
                                       "data": frame["data"]}})
            content.append({"type": "text",
                            "text": format_frame_label(clip["panel"], position, frame["t"])})
'''
SEAM_READ = '''            "seam_continuity": (int(movie["seam_continuity"]) if "seam_continuity" in movie
                                else None),
'''
NONE_BRANCH = '''    if value is None:
        return "  %-20s  n/a (only 1 clip)" % name
'''
# (label, [(old, new, expected count of old)], [tests that must fail])
MUTATIONS = [
    ("key check moved after the extraction block",
     [(KEY, "", 1), (USER_CONTENT, KEY + USER_CONTENT, 1)],
     ["test_t15_key_unset_runs_nothing"]),
    ("key check moved after anthropic.Anthropic()",
     [(KEY, "", 1), (CLIENT, CLIENT + KEY, 1)],
     ["test_t15_key_unset_runs_nothing"]),
    ("fps taken from the manifest's fps instead of ffprobe",
     [("                frame_count, fps = probe_clip(path)\n",
       '                frame_count, fps = probe_clip(path)[0], json.load(open(manifest_path, encoding="utf-8"))["fps"]\n', 1)],
     ["test_t17_successful_run_two_clips"]),
    ("-fps_mode passthrough removed",
     [('"-fps_mode", "passthrough", ', "", 1)],
     ["test_t17_successful_run_two_clips"]),
    ("dedup removed (select built from indices, not unique)",
     [("    unique = sorted(set(indices))\n", "    unique = sorted(indices)\n", 1)],
     ["test_t17_successful_run_two_clips"]),
    ("MEDIA_TYPE changed to image/png",
     [('MEDIA_TYPE = "image/jpeg"', 'MEDIA_TYPE = "image/png"', 1)],
     ["test_t17_successful_run_two_clips"]),
    ("label block emitted after its image block",
     [(LABEL_THEN_IMAGE, IMAGE_THEN_LABEL, 1)],
     ["test_t17_successful_run_two_clips"]),
    ("final text always MULTI",
     [("    if count >= 2:\n", "    if True:\n", 1)],
     ["test_t18_successful_run_one_clip"]),
    ("final text always SINGLE",
     [("    if count >= 2:\n", "    if False:\n", 1)],
     ["test_t17_successful_run_two_clips"]),
    ("seam_continuity added to movie.required",
     [('"required": ["narrative_clarity"],', '"required": ["seam_continuity", "narrative_clarity"],', 1)],
     ["test_t18_successful_run_one_clip"]),
    ("missing-panel validation removed",
     [("    missing = sorted(set(panels) - set(submitted))\n    if missing:\n",
       "    missing = sorted(set(panels) - set(submitted))\n    if False:\n", 1)],
     ["test_t21b_missing_judged_panel"]),
    ("seam >= 2 check removed",
     [('    if len(panels) >= 2 and "seam_continuity" not in tool_input["movie"]:\n', "    if False:\n", 1)],
     ["test_t21c_two_clips_missing_seam"]),
    ("output clips not sorted by panel",
     [('            for entry in sorted(tool_input["clips"], key=lambda entry: entry["panel"])\n',
       '            for entry in tool_input["clips"]\n', 1)],
     ["test_t17_successful_run_two_clips"]),
    ("int() coercion removed from the output",
     [('int(entry["', '(entry["', 5), ('int(movie["', '(movie["', 2)],
     ["test_t25_float_scores_written_as_integers"]),
    ("seam_continuity read with no presence check",
     [(SEAM_READ, '            "seam_continuity": int(movie["seam_continuity"]),\n', 1)],
     ["test_t18_successful_run_one_clip"]),
    ("format_movie_line has no None branch",
     [(NONE_BRANCH, "", 1)],
     ["test_t18_successful_run_one_clip"]),
    ("TemporaryDirectory replaced by mkdtemp without cleanup",
     [('        with tempfile.TemporaryDirectory(prefix="judge-clips-") as tmp_dir:\n',
       '        for tmp_dir in [tempfile.mkdtemp(prefix="judge-clips-")]:\n', 1)],
     ["test_t16_extraction_failure", "test_t17_successful_run_two_clips"]),
    ("frames written into clips/ instead of the temp dir",
     [('                out_dir = os.path.join(tmp_dir, "panel_%02d" % number)\n',
       '                out_dir = os.path.join(clips_dir, "panel_%02d" % number)\n', 1)],
     ["test_t17_successful_run_two_clips"]),
    ("output file named stills_judgment.json",
     [('os.path.join(story_dir, "clips_judgment.json")', 'os.path.join(story_dir, "stills_judgment.json")', 1)],
     ["test_t17_successful_run_two_clips"]),
]
def run(name):
    # Fresh bytecode cache and TMPDIR per run: a same-size mutation written in the same
    # second as an earlier compile would otherwise load the stale .pyc and falsely
    # "survive", and the mkdtemp mutation must not leave judge-clips-* dirs behind.
    base = tempfile.mkdtemp(prefix="jc-mut-")
    try:
        os.mkdir(os.path.join(base, "tmp"))
        env = dict(os.environ, PYTHONPYCACHEPREFIX=os.path.join(base, "pyc"),
                   TMPDIR=os.path.join(base, "tmp"))
        return subprocess.run(["python3", "-m", "pytest", "-q", "--color=no",
                               "-p", "no:cacheprovider", T + name],
                              capture_output=True, text=True, env=env).returncode
    finally:
        shutil.rmtree(base, ignore_errors=True)
src = open(PATH, encoding="utf-8").read()
caught = 0
for label, edits, tests in MUTATIONS:
    mutated = src
    for old, new, count in edits:
        assert mutated.count(old) == count, "%s: anchor count %d != %d" % (label, mutated.count(old), count)
        mutated = mutated.replace(old, new)
    for name in tests:
        assert run(name) == 0, "control: %s must pass unmutated" % name
    try:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(mutated)
        for name in tests:
            rc = run(name)
            print("[%s] %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation not caught"
            caught += 1
    finally:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(src)
assert open(PATH, encoding="utf-8").read() == src
print("%d mutations, %d CAUGHT; restored bin/judge-clips" % (len(MUTATIONS), caught))
EOF
```
Expected: twenty `CAUGHT` lines (the `mkdtemp` row is checked against both T16 and T17), then `19 mutations, 20 CAUGHT; restored bin/judge-clips`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
git diff --cached --name-only            # expect: no output
git add -- bin/judge-clips tests/test_judge_clips.py
git diff --cached --name-only            # expect exactly the two paths below
# qwen-agent-workspace/bin/judge-clips
# qwen-agent-workspace/tests/test_judge_clips.py
git commit -F - <<'EOF'
judge-clips: add frame extraction, judging call, clips_judgment.json

main() probes and extracts 4 frames per clip inside one
judge-clips-* TemporaryDirectory (ClipError -> E15, exit 1, temp dir
removed), builds the interleaved user content with t= labels from each
clip's own avg_frame_rate, and sends spec 4.1's fixed request. The tool
input is validated with validate_judgment_input(block.input, numbers);
a failure dumps clips_judgment.raw.json and exits 1 with no retry.
Success writes clips_judgment.json (nine keys, clips sorted by panel,
every score int(), seam_continuity null for 1 clip) and prints the
spec 5.3 tables and critique. Tests T16, T17, T18, T21a-T21c, T25.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 7: One retry, double failure, API errors, and the key-leak guard

**Files:**
- Modify: `bin/judge-clips`. Replace the two lines in `main` that make the single call with spec 1.4's try/retry/except block and double-failure branch (622 lines at the end of this task).
- Test: append to `tests/test_judge_clips.py`. This adds tests T19, T20, T22, T23 (1195 lines at the end of this task).

**Interfaces:**
- Consumes:
  - From `bin/judge-clips`: `find_tool_use`, `_create_message`, `_write_raw` (Task 6); `RETRY_USER_MESSAGE` (Task 4); `main`'s locals `client`, `user_content`, `story_dir`.
  - Test helpers `_make_story`, `_listing`, `_install_fake`, `_tool_response`, `_text_response`, `_usage`, `VALID_INPUT`, `SENTINEL_KEY`, `STORY_ID`, `synthetic_clips`.
- Produces: the final `main`, which is spec 1.4 verbatim. There are no new symbols.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_judge_clips.py` (the block starts with two empty lines):

```python


# --- T19, T20, T22, T23: retry, double failure, API errors, key leakage (spec 4.6, 6) -

def test_t19_retry_after_missing_tool_call(tmp_path, monkeypatch, synthetic_clips):
    story_dir = _make_story(tmp_path, monkeypatch, synthetic=synthetic_clips)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    # r1 reports no thinking_tokens; r2 does: the sum covers only the responses that
    # report it (spec 5.1).
    r1 = _text_response("Here is my judgment in prose.", _usage(100, 200, None))
    r2 = _tool_response(copy.deepcopy(VALID_INPUT), _usage(1000, 3000, 2500))
    fake = _install_fake(monkeypatch, [r1, r2])

    assert judge_clips.main(["--story-id", STORY_ID]) == 0

    assert len(fake.calls) == 2
    first, second = fake.calls
    assert len(first["messages"]) == 1     # the retry builds a new list, not an append
    retry_messages = second["messages"]
    assert len(retry_messages) == 3
    assert [m["role"] for m in retry_messages] == ["user", "assistant", "user"]
    assert retry_messages[0] == first["messages"][0]      # every frame re-sent
    assert len(retry_messages[0]["content"]) == 19
    assert retry_messages[1]["content"] == r1.content
    assert retry_messages[1]["content"][0].type == "thinking"
    assert retry_messages[1]["content"][0].signature == "sig-abc123"
    assert retry_messages[2]["content"] == judge_clips.RETRY_USER_MESSAGE
    assert ({k: v for k, v in second.items() if k != "messages"}
            == {k: v for k, v in first.items() if k != "messages"})
    with open(story_dir / "clips_judgment.json", encoding="utf-8") as f:
        judgment = json.load(f)
    assert judgment["usage"] == {"input_tokens": 1100, "output_tokens": 3200,
                                 "thinking_tokens": 2500}
    assert not (story_dir / "clips_judgment.raw.json").exists()


def test_t20_double_failure_writes_raw_and_no_judgment(tmp_path, monkeypatch, capsys,
                                                       synthetic_clips):
    story_dir = _make_story(tmp_path, monkeypatch, synthetic=synthetic_clips)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    r1 = _text_response("Prose judgment, attempt one.", _usage(100, 200, 50))
    r2 = _text_response("Prose judgment, attempt two.", _usage(110, 210, 60))
    fake = _install_fake(monkeypatch, [r1, r2])

    assert judge_clips.main(["--story-id", STORY_ID]) == 1

    assert len(fake.calls) == 2
    raw_path = story_dir / "clips_judgment.raw.json"
    with open(raw_path, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["responses"] == [r1.model_dump(mode="json"), r2.model_dump(mode="json")]
    assert not (story_dir / "clips_judgment.json").exists()
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ("Error: Claude did not call submit_judgment after one retry; raw "
                   "responses written to %s\n" % raw_path)


def test_t22_api_error(tmp_path, monkeypatch, capsys, synthetic_clips):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)

    def connection_error():
        return anthropic.APIConnectionError(
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))

    # (a) The first call raises.
    first_dir = _make_story(tmp_path, monkeypatch, story_id="api-first", synthetic=synthetic_clips)
    before = _listing(first_dir)
    fake = _install_fake(monkeypatch, [connection_error()])
    assert judge_clips.main(["--story-id", "api-first"]) == 1
    assert len(fake.calls) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("Error: Anthropic API call failed: APIConnectionError: ")
    assert _listing(first_dir) == before

    # (b) r1 has no tool call and the retry raises: E16, and r1 is not dumped.
    retry_dir = _make_story(tmp_path, monkeypatch, story_id="api-retry", synthetic=synthetic_clips)
    before = _listing(retry_dir)
    fake = _install_fake(monkeypatch, [
        _text_response("Prose only.", _usage(100, 200, 50)), connection_error()])
    assert judge_clips.main(["--story-id", "api-retry"]) == 1
    assert len(fake.calls) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("Error: Anthropic API call failed: APIConnectionError: ")
    assert _listing(retry_dir) == before


def test_t23_api_key_never_leaks(tmp_path, monkeypatch, capsys, synthetic_clips):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)

    # T17 scenario (success). These responses omit output_tokens_details, so this run
    # also pins usage.thinking_tokens == null rather than a fabricated 0 (spec 5.1).
    ok_dir = _make_story(tmp_path, monkeypatch, story_id="leak-ok", synthetic=synthetic_clips)
    _install_fake(monkeypatch, [
        _tool_response(copy.deepcopy(VALID_INPUT), _usage(1200, 3400, None))])
    assert judge_clips.main(["--story-id", "leak-ok"]) == 0
    ok_out, ok_err = capsys.readouterr()

    # T20 scenario (double failure).
    fail_dir = _make_story(tmp_path, monkeypatch, story_id="leak-fail", synthetic=synthetic_clips)
    _install_fake(monkeypatch, [_text_response("Prose one.", _usage(1, 2, None)),
                                _text_response("Prose two.", _usage(3, 4, None))])
    assert judge_clips.main(["--story-id", "leak-fail"]) == 1
    fail_out, fail_err = capsys.readouterr()

    written = [ok_dir / "clips_judgment.json", fail_dir / "clips_judgment.raw.json"]
    for path in written:
        assert path.is_file(), path
    with open(ok_dir / "clips_judgment.json", encoding="utf-8") as f:
        assert json.load(f)["usage"]["thinking_tokens"] is None
    for text in [ok_out, ok_err, fail_out, fail_err] + [p.read_text(encoding="utf-8")
                                                         for p in written]:
        assert SENTINEL_KEY not in text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_clips.py -q --color=no; echo "rc=$?"
```
Expected: `4 failed, 51 passed, 1 warning`, `rc=1`. The failures:
- T19, T20, and T23 fail with `AttributeError: 'NoneType' object has no attribute 'input'`.
- T22 fails with an uncaught `anthropic.APIConnectionError: Connection error.` (raised by the fake client, not the network).

- [ ] **Step 3: Write minimal implementation**

Use the Edit tool on `bin/judge-clips`. new_string is spec 1.4's retry block verbatim, including its comment.

old_string:
```python
    responses = [_create_message(client, [{"role": "user", "content": user_content}])]
    block = find_tool_use(responses[0])
```
new_string:
```python
    responses = []
    try:
        responses.append(_create_message(client, [{"role": "user", "content": user_content}]))
        block = find_tool_use(responses[0])
        if block is None:
            # One retry in the same conversation, re-sending every frame. r1.content goes
            # back exactly as received (thinking blocks and signatures) (spec 4.6).
            responses.append(_create_message(client, [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": responses[0].content},
                {"role": "user", "content": RETRY_USER_MESSAGE},
            ]))
            block = find_tool_use(responses[1])
    except anthropic.APIError as e:
        print("Error: Anthropic API call failed: %s: %s" % (type(e).__name__, e),
              file=sys.stderr)
        return 1
    if block is None:
        raw_path = _write_raw(story_dir, responses)
        print("Error: Claude did not call submit_judgment after one retry; raw responses "
              "written to %s" % raw_path, file=sys.stderr)
        return 1
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_clips.py -q --color=no; echo "rc=$?"
```
Expected: `55 passed, 1 warning`, `rc=0`.

Spec transcription check. `main` is now spec 1.4 verbatim, every paragraph, comments included:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import re, textwrap
SPEC = "docs/superpowers/specs/2026-10-04-judge-clips-design.md"
CHECKS = [("bin/judge-clips", ["1.4"])]
lines = open(SPEC, encoding="utf-8").read().split("\n")
def blocks(section):
    start = next(i for i, l in enumerate(lines) if l.startswith("### " + section + " "))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(("### ", "## "))), len(lines))
    found, i = [], start
    while i < end:
        if lines[i].strip() == "```python":
            j = next(k for k in range(i + 1, end) if lines[k].strip() == "```")
            found.append(textwrap.dedent("\n".join(lines[i + 1:j])))
            i = j
        i += 1
    return found
for target, wants in CHECKS:
    src = open(target, encoding="utf-8").read()
    checked = 0
    for want in wants:
        section, _, index = want.partition("#")
        chosen = blocks(section)
        assert chosen, "no python block under spec " + section
        if index:
            chosen = [chosen[int(index)]]
        for block in chosen:
            for paragraph in re.split(r"\n[ \t]*\n", block):
                if paragraph.strip():
                    assert paragraph.strip() in src, "spec %s paragraph not verbatim in %s:\n%s" % (want, target, paragraph)
                    checked += 1
    print("PASS %s: %d spec paragraphs verbatim (%s)" % (target, checked, ", ".join(wants)))
EOF
```
Expected: `PASS bin/judge-clips: 8 spec paragraphs verbatim (1.4)`.

Mutation checks for these spec 7.4 rows: retry removed; retry without re-sending `user_content`; raw dump skipped on double failure. The script restores the file itself:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, shutil, subprocess, tempfile
PATH = "bin/judge-clips"
T = "tests/test_judge_clips.py::"
RETRY_BLOCK = '''        if block is None:
            # One retry in the same conversation, re-sending every frame. r1.content goes
            # back exactly as received (thinking blocks and signatures) (spec 4.6).
            responses.append(_create_message(client, [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": responses[0].content},
                {"role": "user", "content": RETRY_USER_MESSAGE},
            ]))
            block = find_tool_use(responses[1])
'''
# (label, [(old, new, expected count of old)], [tests that must fail])
MUTATIONS = [
    ("retry removed",
     [(RETRY_BLOCK, "", 1)],
     ["test_t19_retry_after_missing_tool_call"]),
    ("retry does not re-send user_content",
     [('                {"role": "user", "content": user_content},\n', "", 1)],
     ["test_t19_retry_after_missing_tool_call"]),
    ("raw dump skipped on double failure",
     [("        raw_path = _write_raw(story_dir, responses)\n",
       '        raw_path = os.path.join(story_dir, "clips_judgment.raw.json")\n', 1)],
     ["test_t20_double_failure_writes_raw_and_no_judgment"]),
]
def run(name):
    # Fresh bytecode cache and TMPDIR per run: a same-size mutation written in the same
    # second as an earlier compile would otherwise load the stale .pyc and falsely
    # "survive", and the mkdtemp mutation must not leave judge-clips-* dirs behind.
    base = tempfile.mkdtemp(prefix="jc-mut-")
    try:
        os.mkdir(os.path.join(base, "tmp"))
        env = dict(os.environ, PYTHONPYCACHEPREFIX=os.path.join(base, "pyc"),
                   TMPDIR=os.path.join(base, "tmp"))
        return subprocess.run(["python3", "-m", "pytest", "-q", "--color=no",
                               "-p", "no:cacheprovider", T + name],
                              capture_output=True, text=True, env=env).returncode
    finally:
        shutil.rmtree(base, ignore_errors=True)
src = open(PATH, encoding="utf-8").read()
caught = 0
for label, edits, tests in MUTATIONS:
    mutated = src
    for old, new, count in edits:
        assert mutated.count(old) == count, "%s: anchor count %d != %d" % (label, mutated.count(old), count)
        mutated = mutated.replace(old, new)
    for name in tests:
        assert run(name) == 0, "control: %s must pass unmutated" % name
    try:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(mutated)
        for name in tests:
            rc = run(name)
            print("[%s] %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation not caught"
            caught += 1
    finally:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(src)
assert open(PATH, encoding="utf-8").read() == src
print("%d mutations, %d CAUGHT; restored bin/judge-clips" % (len(MUTATIONS), caught))
EOF
```
Expected: three `CAUGHT` lines, then `3 mutations, 3 CAUGHT; restored bin/judge-clips`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
git diff --cached --name-only            # expect: no output
git add -- bin/judge-clips tests/test_judge_clips.py
git diff --cached --name-only            # expect exactly the two paths below
# qwen-agent-workspace/bin/judge-clips
# qwen-agent-workspace/tests/test_judge_clips.py
git commit -F - <<'EOF'
judge-clips: add the single retry, double-failure dump, and API errors

When no submit_judgment block comes back, retry once in the same
conversation, re-sending every frame and r1.content unmodified (thinking
signatures included). A second miss writes clips_judgment.raw.json and
exits 1. Any anthropic.APIError on either call exits 1 with one line and
writes nothing. Tests T19, T20, T22, T23 (key never leaks;
thinking_tokens null when unreported).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## Final acceptance (main thread, after Task 7; spec Section 7.6)

The orchestrating session runs these checks, not the task implementer, because implementer-reported counts are not accepted (spec A1). They write nothing anywhere except where noted:
- A2 rewrites `bin/judge-clips` temporarily and restores it.
- L1 and L2 write `clips_judgment.json` and append to `iterate-story.log` in two real story directories. Both are under `generated/`, which is gitignored.

### A1: suite count and test-ID coverage

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_clips.py -v --color=no; echo "rc=$?"; /usr/bin/grep -c '^def test_' tests/test_judge_clips.py
```
Pass: `55 passed, 1 warning`, then `rc=0`, then `55`.

Each spec test ID maps to exactly one test function:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import re
spec = open("docs/superpowers/specs/2026-10-04-judge-clips-design.md", encoding="utf-8").read().split("\n")
start = next(i for i, l in enumerate(spec) if l.startswith("### 7.2 "))
end = next(i for i, l in enumerate(spec) if l.startswith("### 7.4 "))
ids = [m.group(1).lower() for l in spec[start:end] for m in [re.match(r"^\| (T\d+[a-z]?) \|", l)] if m]
assert len(ids) == len(set(ids)), "duplicate spec IDs"
names = re.findall(r"^def test_(t\d+[a-z]?)_", open("tests/test_judge_clips.py", encoding="utf-8").read(), re.M)
assert len(names) == len(set(names)), "two functions for one ID"
missing, extra = sorted(set(ids) - set(names)), sorted(set(names) - set(ids))
assert not missing and not extra, (missing, extra)
print("PASS %d spec test IDs, %d test functions, one-to-one" % (len(ids), len(names)))
EOF
```
Pass: `PASS 55 spec test IDs, 55 test functions, one-to-one`.

### T: full spec transcription check

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import re, textwrap
SPEC = "docs/superpowers/specs/2026-10-04-judge-clips-design.md"
CHECKS = [("bin/judge-clips", ["1.1", "1.4", "2.1", "2.2", "3.1", "3.2", "3.4", "3.5", "3.6", "3.7", "3.8", "3.9", "4.1", "4.3", "4.4", "4.5", "4.6", "5.2", "5.3"]),
          ("tests/test_judge_clips.py", ["7.1"])]
lines = open(SPEC, encoding="utf-8").read().split("\n")
def blocks(section):
    start = next(i for i, l in enumerate(lines) if l.startswith("### " + section + " "))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(("### ", "## "))), len(lines))
    found, i = [], start
    while i < end:
        if lines[i].strip() == "```python":
            j = next(k for k in range(i + 1, end) if lines[k].strip() == "```")
            found.append(textwrap.dedent("\n".join(lines[i + 1:j])))
            i = j
        i += 1
    return found
for target, wants in CHECKS:
    src = open(target, encoding="utf-8").read()
    checked = 0
    for want in wants:
        section, _, index = want.partition("#")
        chosen = blocks(section)
        assert chosen, "no python block under spec " + section
        if index:
            chosen = [chosen[int(index)]]
        for block in chosen:
            for paragraph in re.split(r"\n[ \t]*\n", block):
                if paragraph.strip():
                    assert paragraph.strip() in src, "spec %s paragraph not verbatim in %s:\n%s" % (want, target, paragraph)
                    checked += 1
    print("PASS %s: %d spec paragraphs verbatim (%s)" % (target, checked, ", ".join(wants)))
EOF
```
Pass:
- `PASS bin/judge-clips: 34 spec paragraphs verbatim (1.1, 1.4, 2.1, 2.2, 3.1, 3.2, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 4.1, 4.3, 4.4, 4.5, 4.6, 5.2, 5.3)`
- `PASS tests/test_judge_clips.py: 6 spec paragraphs verbatim (7.1)`

### A2: all spec 7.4 mutations on the final file (self-restoring)

The run covers 44 spec rows as 45 mutations (Decision 3). Where more than one test catches a mutation, every catcher is listed, and each one must fail. Two rows differ from spec 7.4's text: passthrough uses T10a, T10c, and T17 (Decision 2), and dedup adds T17 (Decision 4). It runs 122 pytest subprocesses (61 controls, 61 mutated runs) and takes roughly 10-15 minutes; running it in the background is fine, but do not edit `bin/judge-clips` while it runs.

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, shutil, subprocess, tempfile
PATH = "bin/judge-clips"
T = "tests/test_judge_clips.py::"
KEY = '''    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set; export it in your environment to run "
              "judge-clips.", file=sys.stderr)
        return 1
'''
USER_CONTENT = "    user_content = build_user_content(clip_inputs)\n"
CLIENT = "    client = anthropic.Anthropic()\n"
E11 = '''    extra = [os.path.basename(path) for number, path in clips if number not in panels_by_index]
    if extra:
        print("Error: clips with no matching panel in manifest.json: %s; the clips in %s may "
              "be stale relative to manifest.json." % (", ".join(extra), clips_dir),
              file=sys.stderr)
        return 2
'''
E12 = '''    missing = sorted(set(panels_by_index) - set(numbers))
    if missing:
        print("Error: manifest.json panels with no rendered clip in %s: %s; judge-clips "
              "judges only complete renders." % (clips_dir, _panel_list(missing)),
              file=sys.stderr)
        return 2
'''
LABEL_THEN_IMAGE = '''            content.append({"type": "text",
                            "text": format_frame_label(clip["panel"], position, frame["t"])})
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": MEDIA_TYPE,
                                       "data": frame["data"]}})
'''
IMAGE_THEN_LABEL = '''            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": MEDIA_TYPE,
                                       "data": frame["data"]}})
            content.append({"type": "text",
                            "text": format_frame_label(clip["panel"], position, frame["t"])})
'''
AUDIO = '''    "The movie also has a soundtrack and spoken narration, but you receive no audio. Do not "
    "judge audio, voice, music, or sound effects. The Narration: text is what is spoken "
    "over that panel's clip.\\n"
    "\\n"
'''
SEAM_READ = '''            "seam_continuity": (int(movie["seam_continuity"]) if "seam_continuity" in movie
                                else None),
'''
NONE_BRANCH = '''    if value is None:
        return "  %-20s  n/a (only 1 clip)" % name
'''
RETRY_BLOCK = '''        if block is None:
            # One retry in the same conversation, re-sending every frame. r1.content goes
            # back exactly as received (thinking blocks and signatures) (spec 4.6).
            responses.append(_create_message(client, [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": responses[0].content},
                {"role": "user", "content": RETRY_USER_MESSAGE},
            ]))
            block = find_tool_use(responses[1])
'''
# (label, [(old, new, expected count of old)], [tests that must fail])
MUTATIONS = [
    ("key check moved after the extraction block",
     [(KEY, "", 1), (USER_CONTENT, KEY + USER_CONTENT, 1)],
     ["test_t15_key_unset_runs_nothing"]),
    ("key check moved after anthropic.Anthropic()",
     [(KEY, "", 1), (CLIENT, CLIENT + KEY, 1)],
     ["test_t15_key_unset_runs_nothing"]),
    ("PATH check (E13) removed",
     [("        if shutil.which(tool) is None:\n", "        if False:\n", 1)],
     ["test_t14n_ffmpeg_or_ffprobe_missing"]),
    ("PATH check order swapped (ffprobe first)",
     [('    for tool in ("ffmpeg", "ffprobe"):\n', '    for tool in ("ffprobe", "ffmpeg"):\n', 1)],
     ["test_t14n_ffmpeg_or_ffprobe_missing"]),
    ("find_clips sorts by filename string",
     [("    found.sort(key=lambda item: (item[0], item[1]))\n", "    found.sort(key=lambda item: item[1])\n", 1)],
     ["test_t3_find_clips_numeric_sort_and_filter"]),
    ("CLIP_NAME_RE accepts one digit",
     [(r're.compile(r"panel_(\d{2,})\.mp4")', r're.compile(r"panel_(\d+)\.mp4")', 1)],
     ["test_t3_find_clips_numeric_sort_and_filter"]),
    ("duplicate-clip check (E4) removed",
     [("        if numbers.count(number) > 1:\n", "        if False:\n", 1)],
     ["test_t14c_duplicate_clip_number"]),
    ("MAX_CLIPS changed to 26",
     [("MAX_CLIPS = 25\n", "MAX_CLIPS = 26\n", 1)],
     ["test_t14d_more_than_25_clips"]),
    ("clip cap compared with >= instead of >",
     [("    if len(clips) > MAX_CLIPS:\n", "    if len(clips) >= MAX_CLIPS:\n", 1)],
     ["test_t14e_exactly_25_clips_passes_cap"]),
    ("load_manifest_panels pairs by list position",
     [("        by_index[index] = panel\n", "        by_index[position] = panel\n", 1)],
     ["test_t5_load_manifest_pairs_by_index"]),
    ("isinstance(index, bool) exclusion removed",
     [("        if not isinstance(index, int) or isinstance(index, bool):\n", "        if not isinstance(index, int):\n", 1)],
     ["test_t14i_panel_entry_without_integer_index"]),
    ("extra-clip check (E11) removed",
     [('    if extra:\n        print("Error: clips with no matching panel', '    if False:\n        print("Error: clips with no matching panel', 1)],
     ["test_t14k_extra_clip"]),
    ("missing-clip check (E12) removed",
     [('    if missing:\n        print("Error: manifest.json panels with no rendered clip', '    if False:\n        print("Error: manifest.json panels with no rendered clip', 1)],
     ["test_t14l_partial_render"]),
    ("E11 and E12 order swapped",
     [(E11 + E12, E12 + E11, 1)],
     ["test_t14o_extra_clip_reported_before_missing"]),
    ("frame_indices floors with int() instead of round()",
     [("    return [round(k * (n - 1)", "    return [int(k * (n - 1)", 1)],
     ["test_t4a_frame_indices_table", "test_t4b_frame_indices_properties"]),
    ("frame_indices uses n instead of n - 1",
     [("k * (n - 1) / (FRAMES_PER_CLIP - 1)", "k * n / (FRAMES_PER_CLIP - 1)", 1)],
     ["test_t4a_frame_indices_table", "test_t4b_frame_indices_properties"]),
    ("ffprobe uses stream=nb_frames without -count_frames",
     [('"v:0", "-count_frames",\n         "-show_entries", "stream=nb_read_frames,avg_frame_rate"',
       '"v:0",\n         "-show_entries", "stream=nb_frames,avg_frame_rate"', 1)],
     ["test_t9a_probe_synthetic_clips", "test_t9c_probe_canned_output"]),
    ("-fps_mode passthrough removed",
     [('"-fps_mode", "passthrough", ', "", 1)],
     ["test_t10a_extract_four_distinct_frames", "test_t10c_extract_canned_output",
      "test_t17_successful_run_two_clips"]),
    ("dedup removed (select built from indices, not unique)",
     [("    unique = sorted(set(indices))\n", "    unique = sorted(indices)\n", 1)],
     ["test_t10b_extract_repeated_indices", "test_t10c_extract_canned_output",
      "test_t17_successful_run_two_clips"]),
    ("file-count check removed",
     [("    if sorted(written) != sorted(expected):\n", "    if False:\n", 1)],
     ["test_t10c_extract_canned_output", "test_t10d_extract_real_failures"]),
    ("fps taken from the manifest's fps instead of ffprobe",
     [("                frame_count, fps = probe_clip(path)\n",
       '                frame_count, fps = probe_clip(path)[0], json.load(open(manifest_path, encoding="utf-8"))["fps"]\n', 1)],
     ["test_t17_successful_run_two_clips"]),
    ("MEDIA_TYPE changed to image/png",
     [('MEDIA_TYPE = "image/jpeg"', 'MEDIA_TYPE = "image/png"', 1)],
     ["test_t8a_build_user_content_two_clips", "test_t17_successful_run_two_clips"]),
    ("label block emitted after its image block",
     [(LABEL_THEN_IMAGE, IMAGE_THEN_LABEL, 1)],
     ["test_t8a_build_user_content_two_clips", "test_t17_successful_run_two_clips"]),
    ("number == 1 condition removed from the opening-still branch",
     [('    if number == 1 and _text_field(panel, "image_path"):\n', '    if _text_field(panel, "image_path"):\n', 1)],
     ["test_t6_format_panel_text"]),
    ("opening-still line emitted without the image_path condition",
     [('    if number == 1 and _text_field(panel, "image_path"):\n', "    if number == 1:\n", 1)],
     ["test_t6_format_panel_text"]),
    ("final text always MULTI",
     [("    if count >= 2:\n", "    if True:\n", 1)],
     ["test_t8b_build_user_content_one_clip", "test_t18_successful_run_one_clip"]),
    ("final text always SINGLE",
     [("    if count >= 2:\n", "    if False:\n", 1)],
     ["test_t8a_build_user_content_two_clips", "test_t17_successful_run_two_clips"]),
    ("audio sentence removed from SYSTEM_PROMPT",
     [(AUDIO, "", 1)],
     ["test_t8c_system_prompt_content"]),
    ("duplicate-panel validation removed",
     [("    if duplicates:\n", "    if False:\n", 1)],
     ["test_t12_panel_set_rules"]),
    ("missing-panel validation removed",
     [("    missing = sorted(set(panels) - set(submitted))\n    if missing:\n",
       "    missing = sorted(set(panels) - set(submitted))\n    if False:\n", 1)],
     ["test_t12_panel_set_rules", "test_t21b_missing_judged_panel"]),
    ("extra-panel validation removed",
     [("    extra = sorted(set(submitted) - set(panels))\n    if extra:\n",
       "    extra = sorted(set(submitted) - set(panels))\n    if False:\n", 1)],
     ["test_t12_panel_set_rules"]),
    ("seam >= 2 check removed",
     [('    if len(panels) >= 2 and "seam_continuity" not in tool_input["movie"]:\n', "    if False:\n", 1)],
     ["test_t13_seam_two_way_rule", "test_t21c_two_clips_missing_seam"]),
    ("seam < 2 check removed",
     [('    if len(panels) < 2 and "seam_continuity" in tool_input["movie"]:\n', "    if False:\n", 1)],
     ["test_t13_seam_two_way_rule"]),
    ("seam_continuity added to movie.required",
     [('"required": ["narrative_clarity"],', '"required": ["seam_continuity", "narrative_clarity"],', 1)],
     ["test_t13_seam_two_way_rule", "test_t18_successful_run_one_clip"]),
    ("output clips not sorted by panel",
     [('            for entry in sorted(tool_input["clips"], key=lambda entry: entry["panel"])\n',
       '            for entry in tool_input["clips"]\n', 1)],
     ["test_t17_successful_run_two_clips"]),
    ("int() coercion removed from the output",
     [('int(entry["', '(entry["', 5), ('int(movie["', '(movie["', 2)],
     ["test_t25_float_scores_written_as_integers"]),
    ("seam_continuity read with no presence check",
     [(SEAM_READ, '            "seam_continuity": int(movie["seam_continuity"]),\n', 1)],
     ["test_t18_successful_run_one_clip"]),
    ("format_movie_line has no None branch",
     [(NONE_BRANCH, "", 1)],
     ["test_t18_successful_run_one_clip"]),
    ("TemporaryDirectory replaced by mkdtemp without cleanup",
     [('        with tempfile.TemporaryDirectory(prefix="judge-clips-") as tmp_dir:\n',
       '        for tmp_dir in [tempfile.mkdtemp(prefix="judge-clips-")]:\n', 1)],
     ["test_t16_extraction_failure", "test_t17_successful_run_two_clips"]),
    ("frames written into clips/ instead of the temp dir",
     [('                out_dir = os.path.join(tmp_dir, "panel_%02d" % number)\n',
       '                out_dir = os.path.join(clips_dir, "panel_%02d" % number)\n', 1)],
     ["test_t17_successful_run_two_clips"]),
    ("retry removed",
     [(RETRY_BLOCK, "", 1)],
     ["test_t19_retry_after_missing_tool_call"]),
    ("retry does not re-send user_content",
     [('                {"role": "user", "content": user_content},\n', "", 1)],
     ["test_t19_retry_after_missing_tool_call"]),
    ("raw dump skipped on double failure",
     [("        raw_path = _write_raw(story_dir, responses)\n",
       '        raw_path = os.path.join(story_dir, "clips_judgment.raw.json")\n', 1)],
     ["test_t20_double_failure_writes_raw_and_no_judgment"]),
    ("output file named stills_judgment.json",
     [('os.path.join(story_dir, "clips_judgment.json")', 'os.path.join(story_dir, "stills_judgment.json")', 1)],
     ["test_t17_successful_run_two_clips"]),
    ("__main__ reverted to sys.exit(main())",
     [('    sys.exit(pipeline_log.run_logged("judge-clips", _pipeline_log_story_dir(sys.argv[1:]), main, sys.argv))\n',
       "    sys.exit(main())\n", 1)],
     ["test_t24_pipeline_log_wiring"]),
]
def run(name):
    # Fresh bytecode cache and TMPDIR per run: a same-size mutation written in the same
    # second as an earlier compile would otherwise load the stale .pyc and falsely
    # "survive", and the mkdtemp mutation must not leave judge-clips-* dirs behind.
    base = tempfile.mkdtemp(prefix="jc-mut-")
    try:
        os.mkdir(os.path.join(base, "tmp"))
        env = dict(os.environ, PYTHONPYCACHEPREFIX=os.path.join(base, "pyc"),
                   TMPDIR=os.path.join(base, "tmp"))
        return subprocess.run(["python3", "-m", "pytest", "-q", "--color=no",
                               "-p", "no:cacheprovider", T + name],
                              capture_output=True, text=True, env=env).returncode
    finally:
        shutil.rmtree(base, ignore_errors=True)
src = open(PATH, encoding="utf-8").read()
caught = 0
for label, edits, tests in MUTATIONS:
    mutated = src
    for old, new, count in edits:
        assert mutated.count(old) == count, "%s: anchor count %d != %d" % (label, mutated.count(old), count)
        mutated = mutated.replace(old, new)
    for name in tests:
        assert run(name) == 0, "control: %s must pass unmutated" % name
    try:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(mutated)
        for name in tests:
            rc = run(name)
            print("[%s] %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation not caught"
            caught += 1
    finally:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(src)
assert open(PATH, encoding="utf-8").read() == src
print("%d mutations, %d CAUGHT; restored bin/judge-clips" % (len(MUTATIONS), caught))
EOF
```
Pass: 61 `CAUGHT` lines, then `45 mutations, 61 CAUGHT; restored bin/judge-clips`. Any `NOT CAUGHT`, control failure, or anchor-count assertion is a failure. Afterwards, `git diff --stat HEAD -- bin/judge-clips` must print nothing.

### R1: regression suites

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && for t in test_judge_stills test_judge_story test_iterate_story test_pipeline_log; do python3 -m pytest tests/$t.py -q --color=no > /tmp/jc_r1_$t.txt 2>&1; echo "$t rc=$? :: $(tail -1 /tmp/jc_r1_$t.txt)"; done
```
Pass: the counts below, each with `rc=0`. They match the pre-Task-1 baselines.
- `test_judge_stills rc=0 :: 32 passed, 1 warning ...`
- `test_judge_story rc=0 :: 19 passed, 1 warning ...`
- `test_iterate_story rc=0 :: 17 passed, 1 warning ...`
- `test_pipeline_log rc=0 :: 17 passed, 4 warnings ...`

### Scope check

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && git diff --name-only a4dadc2..HEAD; git log --format='%s' a4dadc2..HEAD
```
Pass:
- The diff prints exactly `qwen-agent-workspace/bin/judge-clips` and `qwen-agent-workspace/tests/test_judge_clips.py`.
- The log prints the seven task subjects, every one starting `judge-clips: `.

If other commits were interleaved, report them; do not rewrite history. Also run `git diff --stat` for tracked files. It must show only the six files that were already modified before Task 1: `../.gitignore`, `.gitignore`, `bin/ltx-story-video`, `bin/qwen-agent`, `ltx_ceiling.json`, `ltx_video_skill.py`.

### S1: real-data precondition smoke and spec live gate L3 (no key, no network, writes nothing)

`STORY_PIPELINE_LOGGED=1` keeps the real stories' `iterate-story.log` untouched.
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && for s in mlxdemo mystorytest2 test_story1 final_e2e_verify frogjump; do STORY_PIPELINE_LOGGED=1 env -u ANTHROPIC_API_KEY bin/judge-clips --story-id "$s"; echo "$s rc=$?"; done
```
Pass, all five observed in the scratch copy:
- `mlxdemo` (spec L3) prints `Error: manifest.json panels with no rendered clip in /Users/reubenpatterson/local_model_harness/qwen-agent-workspace/generated/stories/mlxdemo/clips: 2; judge-clips judges only complete renders.` and `rc=2`.
- `mystorytest2` (spec L3) prints `Error: manifest.json panels with no rendered clip in /Users/reubenpatterson/local_model_harness/qwen-agent-workspace/generated/stories/mystorytest2/clips: 1, 2, 3, 4; judge-clips judges only complete renders.` and `rc=2`.
- `test_story1`, `final_e2e_verify`, and `frogjump` each print `Error: ANTHROPIC_API_KEY is not set; export it in your environment to run judge-clips.` and `rc=1`. This proves E2-E13 all pass on real data.
- No `clips_judgment*` file appears in any of the five story directories.

### S2: real-clip extraction smoke (no key, no network, reads only)

This runs real ffprobe and ffmpeg on the real clips, using the tool's own functions in a throwaway temp directory, and builds the user content without calling the API.
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import base64, importlib.machinery, os, subprocess, tempfile
jc = importlib.machinery.SourceFileLoader("judge_clips", "bin/judge-clips").load_module()
for story, n_clips, frames, size in (("test_story1", 5, [0, 48, 96, 144], "704,448"),
                                     ("final_e2e_verify", 1, [0, 3, 5, 8], None)):
    story_dir, clips_dir, manifest_path = jc.resolve_paths(story)
    clips = jc.find_clips(clips_dir)
    panels = jc.load_manifest_panels(manifest_path)
    assert [n for n, _ in clips] == sorted(panels) and len(clips) == n_clips, (story, clips)
    clip_inputs, total_b64 = [], 0
    with tempfile.TemporaryDirectory(prefix="judge-clips-smoke-") as tmp:
        for number, path in clips:
            count, fps = jc.probe_clip(path)
            indices = jc.frame_indices(count)
            assert indices == frames, (story, number, indices)
            out = os.path.join(tmp, "panel_%02d" % number)
            os.mkdir(out)
            images = jc.extract_frames(path, indices, out)
            assert len(images) == 4 and all(i.startswith(b"\xff\xd8") for i in images)
            if size:
                got = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
                                      "-of", "csv=p=0", os.path.join(out, "frame_1.jpg")],
                                     capture_output=True, text=True, check=True).stdout.strip()
                assert got == size, got
            data = [base64.standard_b64encode(i).decode("ascii") for i in images]
            total_b64 += sum(len(d) for d in data)
            clip_inputs.append({"panel": number, "text": jc.format_panel_text(number, panels[number]),
                                "frames": [{"t": float(i / fps), "data": d} for i, d in zip(indices, data)]})
    content = jc.build_user_content(clip_inputs)
    assert len(content) == 9 * n_clips + 1
    print("PASS %s: %d clips, frames %s, %d blocks, %.2f MB base64" % (story, n_clips, frames, len(content), total_b64 / 1e6))
EOF
```
Pass, as observed: `PASS test_story1: 5 clips, frames [0, 48, 96, 144], 46 blocks, 0.75 MB base64` and `PASS final_e2e_verify: 1 clips, frames [0, 3, 5, 8], 10 blocks, 0.26 MB base64`. The MB figures may differ slightly if the clips were re-rendered; the frames and block counts may not.

### L1 (live, needs a real key; the main thread or the user runs it): spec live gate L1

One Opus call (20 frames, about 9k image tokens). `ANTHROPIC_API_KEY` must be exported. `STORY_PIPELINE_LOGGED` is unset explicitly so the run is logged. The before/after listings live in a `mktemp -d` directory created inside this one command, so nothing depends on an earlier session. `ls -lA` (not `-la`) leaves out `..`, whose mtime legitimately changes when `clips_judgment.json` is written.
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && B=$(mktemp -d) && ls -lA generated/stories/test_story1/clips > "$B/ls_before" && shasum generated/stories/test_story1/clips/* > "$B/sha_before" && env -u STORY_PIPELINE_LOGGED bin/judge-clips --story-id test_story1 > "$B/stdout"; echo "rc=$?"; ls -lA generated/stories/test_story1/clips > "$B/ls_after"; shasum generated/stories/test_story1/clips/* > "$B/sha_after"; diff "$B/ls_before" "$B/ls_after" && diff "$B/sha_before" "$B/sha_after" && echo "clips/ unchanged"; cat "$B/stdout"; python3 - "$B" <<'EOF'
import glob, importlib.machinery, json, os, re, sys, tempfile
B = sys.argv[1]
jc = importlib.machinery.SourceFileLoader("judge_clips", "bin/judge-clips").load_module()
story = "generated/stories/test_story1"
with open(os.path.join(story, "clips_judgment.json"), encoding="utf-8") as f:
    d = json.load(f)
assert list(d) == ["story_id", "model", "effort", "timestamp", "frames_per_clip", "usage",
                   "clips", "movie", "critique"], list(d)
assert [c["panel"] for c in d["clips"]] == [1, 2, 3, 4, 5], d["clips"]
assert all(c["frames"] == [0, 48, 96, 144] for c in d["clips"]), d["clips"]
assert type(d["movie"]["seam_continuity"]) is int, d["movie"]
assert re.search(r"Panel \d", d["critique"]), "critique names no panel by number"
expected = ("Clip scores:\n" + jc.CLIP_TABLE_FORMAT % (("panel",) + jc.CLIP_SCORE_KEYS) + "\n"
            + "".join(jc.format_clip_row(e) + "\n" for e in d["clips"])
            + "\nMovie scores:\n"
            + "".join(jc.format_movie_line(k, d["movie"][k]) + "\n" for k in jc.MOVIE_SCORE_KEYS)
            + "\n--- Critique ---\n" + d["critique"] + "\n")
with open(os.path.join(B, "stdout"), encoding="utf-8") as f:
    assert f.read() == expected, "stdout differs from spec 5.3"
with open(os.path.join(story, "iterate-story.log"), encoding="utf-8") as f:
    log = f.read()
last = log[log.rindex("=== stage: "):]
assert last.startswith("=== stage: judge-clips === ") and "\nexit: 0\n" in last, last[:300]
leftovers = glob.glob(os.path.join(tempfile.gettempdir(), "judge-clips-*"))
assert leftovers == [], leftovers
print("PASS L1: usage %s; movie %s" % (d["usage"], d["movie"]))
EOF
```
Pass:
- `rc=0` and `clips/ unchanged`.
- The stdout table is printed, then `PASS L1: ...`.

The checker asserts these spec L1 items:
- the 9 keys;
- 5 entries, each with frames `[0, 48, 96, 144]`;
- an integer `seam_continuity`;
- the critique names a panel by number;
- stdout equals the spec 5.3 formal definition;
- a `=== stage: judge-clips ===` record with `exit: 0`;
- no `judge-clips-*` directory left in `$TMPDIR` (checked with Python `glob`, because a zsh glob that matches nothing aborts the shell).

How to handle a failure:
- An E16 (API error) or E17/E18 is a real finding. Report it to the user with the stderr line and, for E17/E18, `generated/stories/test_story1/clips_judgment.raw.json`. Do not patch around it.
- E18 for a string or label panel is spec Review Focus 4.
- A request-size error is spec Review Focus 3.

### L2 (live, needs a real key): spec live gate L2, the 1-clip case

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && B=$(mktemp -d) && env -u STORY_PIPELINE_LOGGED bin/judge-clips --story-id final_e2e_verify > "$B/stdout"; echo "rc=$?"; cat "$B/stdout"; python3 - "$B" <<'EOF'
import json, os, sys
B = sys.argv[1]
story = "generated/stories/final_e2e_verify"
with open(os.path.join(story, "clips_judgment.json"), encoding="utf-8") as f:
    d = json.load(f)
assert [c["frames"] for c in d["clips"]] == [[0, 3, 5, 8]], d["clips"]
assert d["movie"]["seam_continuity"] is None, d["movie"]
with open(os.path.join(B, "stdout"), encoding="utf-8") as f:
    assert "\n  seam_continuity       n/a (only 1 clip)\n" in f.read()
with open(os.path.join(story, "iterate-story.log"), encoding="utf-8") as f:
    log = f.read()
last = log[log.rindex("=== stage: "):]
assert last.startswith("=== stage: judge-clips === ") and "\nexit: 0\n" in last, last[:300]
print("PASS L2: clips %s; movie %s" % (d["clips"], d["movie"]))
EOF
```
Pass: `rc=0`, a stdout line `  seam_continuity       n/a (only 1 clip)`, then `PASS L2: ...`.

If the run instead exits 1 with `Error: submit_judgment input failed schema validation: seam_continuity must be omitted when judging fewer than 2 clips`, the real model scored seam despite the instruction. That is E18 by design: a real finding to report to the user (spec L2, Review Focus 4), not a test bug. Do not loosen validation.

## Provenance of this document

This plan was assembled from code pieces that were run and tested in the scratch copy. It was then checked in two ways:
- An executor simulation parsed this text, applied every Step 1 and Step 3 block in order, and reproduced all seven tested file states byte-for-byte.
- Every embedded check and mutation script was extracted from this text and run against the matching staged copy. All passed, and every file was restored.

This repo copy is the authoritative plan.
