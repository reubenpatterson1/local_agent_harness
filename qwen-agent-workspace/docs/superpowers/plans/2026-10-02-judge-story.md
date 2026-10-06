# bin/judge-story Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `bin/judge-story`, a hand-run, observe-only tool that sends an existing `story.md` plus the prompt that produced it to Claude (extended thinking), gets back four 1-10 scores, a panel-specific critique, and a revised story prompt through the `submit_judgment` tool, and writes `judgment.json` and `story_prompt.revised.txt` next to the story. Also make `bin/ltx-movie` Phase 1 persist that prompt as `story_prompt.txt`.
**Architecture:** One standalone executable Python script, `bin/judge-story`, following the existing `bin/*` convention: no extension, `main(argv=None) -> int`, no imports from other `bin/*` files, no shared module. It runs file preconditions, then an env-key gate, then at most two non-streaming `messages.create` calls (one retry, only when no tool call comes back), then jsonschema validation, then output writes. A separate 3-line insert in `bin/ltx-movie`'s `phase1_story()` writes the exact prompt string that judge-story needs as input.
**Tech Stack:** Python 3.13.0 (`/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`), `anthropic` 0.116.0 (Messages API, extended thinking, tool use), `jsonschema` 4.23.0, `httpx` 0.28.1 (tests only, to build an `APIConnectionError`), `pytest` 8.3.4.
**Spec:** docs/superpowers/specs/2026-10-02-judge-story-design.md

## Global Constraints

- Workspace root `WS` = `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/`. Run every command in this plan from `WS` unless a step says otherwise. The git repo root is one level up (`/Users/reubenpatterson/local_model_harness`), so `git diff --name-only` prints paths with the `qwen-agent-workspace/` prefix.
- Exactly three files change: `bin/judge-story` (create, `chmod +x`), `tests/test_judge_story.py` (create), and `bin/ltx-movie` (insert the 3 lines of spec Section 2.2 in `phase1_story()`, nothing else). No other file is created or modified. No `requirements*.txt` or `pyproject.toml` exists, and none is added (spec G5).
- `bin/judge-story` stays out of the deploy package (`scripts/deploy/`, `tests/test_deploy_pkg.py`) for Phase 1 (spec G5 recommendation).
- Script conventions: shebang `#!/usr/bin/env python3`, module docstring at the top, no file extension, executable bit set, `def main(argv=None):` returning an `int`, ending with `if __name__ == "__main__":` / `    sys.exit(main())`.
- Top-level imports are exactly `argparse`, `datetime`, `json`, `os`, `sys`, `anthropic`, `jsonschema`.
- `WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))`, read by `resolve_paths` at call time, not at import time.
- `MODEL = "claude-opus-5-5"`; `THINKING_BUDGET_TOKENS = 16000`; `MAX_TOKENS = 21333` (final, spec G1 resolved); `TOOL_NAME = "submit_judgment"`.
- Request: `thinking={"type": "enabled", "budget_tokens": 16000}`, `tool_choice={"type": "auto"}` (extended thinking cannot force a tool), exactly one tool, `system=SYSTEM_PROMPT`. No `temperature`/`top_k`/`top_p`, no streaming, no `timeout=`. The SDK's default `max_retries` is left unchanged (spec G2).
- API key: read only via `os.environ.get("ANTHROPIC_API_KEY")`. `None` and `""` both count as unset. Check before `anthropic.Anthropic()` is constructed. Construct `anthropic.Anthropic()` with no arguments. Never print, log, interpolate, or write the key.
- At most two API calls per run. The single retry happens only when no `submit_judgment` tool_use block comes back. Failed schema validation is never retried (spec G3).
- Exit codes: 0 success, 1 runtime/API failure, 2 argument/precondition failure. Every error goes to stderr and starts with `Error: `. Exceptions outside the spec Section 6 table (`OSError`, `UnicodeDecodeError`) are not caught.
- `judgment.json`: `json.dump(obj, f, indent=2, ensure_ascii=False)` plus a trailing `"\n"`. Key order: `story_md_path, story_prompt_path, model, thinking_budget_tokens, timestamp, usage, scores, critique, revised_prompt`. `usage` is summed over every response. `thinking_tokens` is JSON `null` when no response reports it.
- `story_prompt.revised.txt`: exactly the `revised_prompt` string, with no added trailing newline. It is written after `judgment.json`.
- `judgment.raw.json` (E6/E7 only): `{"responses": [r.model_dump(mode="json"), ...]}`, `indent=2`, `ensure_ascii=False`.
- Outputs go to `story_dir` (the directory containing the resolved `story.md`). They overwrite earlier files without prompting and never delete anything.
- Stdout is used on success only and holds exactly the spec Section 5.3 block. Score lines are `"  %-20s  %d"`.
- Out of scope: `--story-id` validation, file-content validation (an empty file is sent as-is), streaming, backoff, wiring into `_phase_sequence`, and backfilling `story_prompt.txt`.
- Tests: pytest with plain `assert`, never the `check()` helper. Exactly **18** test functions, one per spec test ID: T1a T1b T2a T2b T3a T3b T4 T5a T5b T5c T5d T7 T8 T9 T10 T10b T10c T11. Multi-case IDs loop inside one function. Extra coverage goes in as extra assertions inside those 18 functions, never as new test functions, so the spec's A1 count check stays exact. No network: an autouse fixture makes constructing the real client fail the test.
- R1 baseline, measured 2026-10-02 before any change: `python3 tests/test_ltx_movie_offline.py` prints `OK 340/340` as its last line and exits 0. Run it directly. Under `pytest` it gives false greens.
- Pytest prints one `DeprecationWarning` for `SourceFileLoader.load_module()`, the loader the spec mandates in Section 7.1, so every passing run ends `N passed, 1 warning`. On startup it also prints a `pytest_asyncio` `PytestDeprecationWarning` about `asyncio_default_fixture_loop_scope` to stderr. Both are expected and are not failures.
- Every mutation runner gives each pytest subprocess a fresh `PYTHONPYCACHEPREFIX`. Do not remove it. When validating this plan, a same-size mutation (`return 2` -> `return 0`) falsely SURVIVED once without it. It was written within the same second as the control run's compile, so Python loaded the stale `.pyc` of the unmutated file.
- Commit hygiene: the working tree has unrelated modified and untracked files. Stage only by explicit path. Before each commit, confirm `git diff --cached --name-only` lists only that task's files. Commit messages end with the executing session's attribution trailer. The commands below use `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`, the repo's convention for code-executor commits. Substitute the executing session's own trailer line if it differs.

## Review Focus

1. **A story generated before Task 1 has no `story_prompt.txt`.** Every story on disk today hits this on the first run. It must exit 2, with the full E3 message including the `--force-story` hint, and write nothing. Test: T4 (Task 4).
2. **Claude replies in prose and never calls `submit_judgment`.** `tool_choice` cannot force a tool under extended thinking. The tool must make exactly one retry, passing `r1.content` back unmodified (thinking block and signature included, or the API rejects the turn). After that it writes the raw dump and exits 1, never fabricating scores. Tests: T9, T10 (Task 6).
3. **Malformed tool input.** Examples: a score of 0 or 11, `"7"`, `7.5`, `true`, a missing key, or input cut short at `max_tokens`. Schema validation must reject it, write the raw dump, and exit 1, with no `judgment.json` and no retry. Tests: T5a-T5d (Task 2), T10b (Task 5).
4. **A success run that reports wrong numbers silently.** Ways this can happen: a score lands under the wrong dimension, `story_prompt.revised.txt` gains a trailing newline, `usage.thinking_tokens` is fabricated as `0` when the API omits it, or retry usage is not summed. Tests: T7 (Task 5; distinct per-dimension scores, byte-equal revised prompt, exact stdout), T9 (sum over only the responses that report it) and T11 (`null` when none report it) (Task 6).
5. **Environment or API failure.** Cases: the key is unset or empty, or the first call or the retry fails with a connection, auth, or rate-limit error. Each must exit 1 with one `Error:` line, no traceback, no files written, and the key never echoed. Tests: T8 (Task 4), T10c and T11 (Task 6).

---

### Task 1: bin/ltx-movie persists the Phase 1 story prompt (D3)

**Files:**
- Modify: `bin/ltx-movie`, inserting 3 lines after line 665 (`seconds=_clip_seconds(args))` inside `phase1_story()`). They become new lines 666-668. Nothing else in the file changes.
- Test: no committed test (spec G7 forbids touching a fourth file). Verification uses an ephemeral stdin check script (Step 1) plus the existing regression suite `tests/test_ltx_movie_offline.py`, run directly (spec R1).

**Interfaces:**
- Consumes: existing `bin/ltx-movie` symbols `phase1_story(args)`, `build_story_prompt(narrative, story_id, panels, no_stills=False, seed_image=False, *, seconds)`, `_story_dir(story_id)` (line 383), `_clip_seconds(args)`, and module global `WS`.
- Produces: the file `generated/stories/<story_id>/story_prompt.txt`, containing exactly the `prompt` string passed to qwen-agent's `--user-prompt`. This is `bin/judge-story`'s required input (Tasks 4-6 read it via `resolve_paths`). There are no new Python symbols.

- [ ] **Step 1: Write the failing test**

This is an ephemeral check fed to `python3` on stdin, so no file is written. It loads `bin/ltx-movie`, points `WS` at a temp dir, stubs `subprocess.Popen` to capture the qwen-agent argv and fail like a crashed qwen-agent (rc 1, no story.md), and runs the real `phase1_story()`. Save nothing. Steps 2 and 4 paste this same block.

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import importlib.machinery, os, tempfile, types
ltx_movie = importlib.machinery.SourceFileLoader("ltx_movie", "bin/ltx-movie").load_module()
captured = {}
class FakeProc:
    returncode = 1
    def communicate(self, timeout=None):
        return ("", None)
def fake_popen(cmd, **kwargs):
    captured["prompt"] = cmd[cmd.index("--user-prompt") + 1]
    return FakeProc()
with tempfile.TemporaryDirectory() as tmp:
    ltx_movie.WS = tmp
    ltx_movie.subprocess.Popen = fake_popen
    args = types.SimpleNamespace(
        story_id="d3check", force_story=False, panels=3, no_stills=False, seed_image=None,
        narrative="a fox crosses a frozen river — at dawn, 100% on foot", frames=145,
        fps=24, story_model=None, story_context_window=None, seed_downscaled_path=None,
        no_review=True)
    os.makedirs(os.path.join(tmp, "generated", "stories", "d3check"))
    rc = ltx_movie.phase1_story(args)
    expected = ltx_movie.build_story_prompt(args.narrative, args.story_id, args.panels,
                                            args.no_stills, False,
                                            seconds=ltx_movie._clip_seconds(args))
    path = os.path.join(tmp, "generated", "stories", "d3check", "story_prompt.txt")
    assert rc == 1, "phase1_story rc %r (expected 1: stubbed qwen-agent failed)" % rc
    assert os.path.isfile(path), "FAIL D3: story_prompt.txt not written"
    with open(path, "rb") as f:
        data = f.read()
    assert data == expected.encode("utf-8"), "FAIL D3: content != build_story_prompt()"
    assert data == captured["prompt"].encode("utf-8"), "FAIL D3: content != qwen-agent prompt"
    print("PASS D3: story_prompt.txt byte-equal to the qwen-agent prompt (%d bytes)" % len(data))
EOF
```

- [ ] **Step 2: Run test to verify it fails**

First record the R1 baseline, then run the Step 1 block.

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 tests/test_ltx_movie_offline.py > /tmp/judge_story_r1_before.txt 2>&1; echo "rc=$?"; tail -1 /tmp/judge_story_r1_before.txt
```
Expected: `rc=0` then `OK 340/340`. If the count differs from 340, stop and report. The baseline in Global Constraints is stale.

Then paste and run the Step 1 block. Expected: stderr shows the stubbed `Error: qwen-agent exited 1 while authoring story.md`, followed by a traceback ending in `AssertionError: FAIL D3: story_prompt.txt not written`. The stdout `Running (...)` status line shows `--user-prompt --user-prompt '<N chars>'`. That duplication is pre-existing at `bin/ltx-movie:680` (`cmd[:-1]` keeps the flag, then re-adds it), cosmetic, and out of scope: do not fix it.

- [ ] **Step 3: Write minimal implementation**

Use the Edit tool on `bin/ltx-movie`. `old_string` is unique: line 978's `seconds=_clip_seconds(args))` has different indentation and is followed by a blank line.

old_string:
```python
                                     seconds=_clip_seconds(args))
        max_tokens = _phase1_max_tokens(args.panels)
```
new_string:
```python
                                     seconds=_clip_seconds(args))
        with open(os.path.join(_story_dir(args.story_id), "story_prompt.txt"), "w",
                  encoding="utf-8") as f:
            f.write(prompt)
        max_tokens = _phase1_max_tokens(args.panels)
```
Do not add `os.makedirs`: `main()` creates `story_dir` at line 1115 before any phase runs. Do not touch the `cmd = [sys.executable, os.path.join(WS, "bin", "qwen-agent"),` lines (test L19 asserts their exact text) or `_print_dry_run_plan()`.

- [ ] **Step 4: Run test to verify it passes**

Paste and run the Step 1 block again. Expected last line: `PASS D3: story_prompt.txt byte-equal to the qwen-agent prompt (3609 bytes)`. 3609 is the value measured on 2026-10-02 against the current `STORY_PROMPT_TEMPLATE`. If the template has changed since, a different byte count is fine as long as the line says `PASS D3`. The stubbed qwen-agent `Error:` line on stderr is expected noise.

Then run the R1 regression gate and the diff-shape check:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 tests/test_ltx_movie_offline.py > /tmp/judge_story_r1_after.txt 2>&1; echo "rc=$?"; tail -1 /tmp/judge_story_r1_after.txt
git diff --numstat -- bin/ltx-movie
git diff -- bin/ltx-movie | /usr/bin/grep '^[-+][^-+]'
```
Expected: `rc=0`, `OK 340/340`. Numstat is exactly `3	0	qwen-agent-workspace/bin/ltx-movie`. The grep prints exactly the three `+` lines from Step 3 and no `-` lines.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
git diff --cached --name-only            # expect: no output (nothing pre-staged)
git add -- bin/ltx-movie
git diff --cached --name-only            # expect exactly: qwen-agent-workspace/bin/ltx-movie
git commit -F - <<'EOF'
ltx-movie: persist the Phase 1 story prompt to story_prompt.txt

phase1_story() now writes the exact prompt string it passes to
qwen-agent's --user-prompt to generated/stories/<id>/story_prompt.txt
(UTF-8, verbatim, no trailing newline added), before qwen-agent runs.
Nothing saved this prompt before; bin/judge-story needs it as input
to propose a revised prompt. --dry-run is unchanged and writes nothing.

Verified: ephemeral phase1_story() check (stubbed Popen) shows the file
is byte-equal to the qwen-agent prompt; tests/test_ltx_movie_offline.py
still OK 340/340.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
```

---

### Task 2: bin/judge-story skeleton, submit_judgment schema, and validation

**Files:**
- Create: `bin/judge-story` (lines 1-82 at the end of this task), then `chmod +x`.
- Test: create `tests/test_judge_story.py` (lines 1-90 at the end of this task).

**Interfaces:**
- Consumes: nothing from earlier tasks. Independent of Task 1.
- Produces, in `bin/judge-story`: module globals `WS`, `MODEL`, `THINKING_BUDGET_TOKENS`, `MAX_TOKENS`, `TOOL_NAME`, `TOOL_DESCRIPTION`, `SCORE_KEYS` (tuple of the four score names in output order), `SUBMIT_JUDGMENT_SCHEMA` (dict), and `validate_judgment_input(tool_input) -> None`, which raises `jsonschema.ValidationError`. In `tests/test_judge_story.py`: module globals `WS`, `_SCRIPT_PATH`, `judge_story`, `SENTINEL_KEY`, `SCORE_NAMES`, `VALID_INPUT`, and the autouse fixture `_no_real_client`. Every later test task appends to this file and relies on these names.

- [ ] **Step 1: Write the failing test**

Create `tests/test_judge_story.py` with exactly this content. The imports `json`, `re`, `types`, `uuid`, `anthropic`, and `httpx` are used by tests appended in Tasks 4-6. They are included now so later tasks only append.

```python
"""Tests for bin/judge-story.

Spec: docs/superpowers/specs/2026-10-02-judge-story-design.md (Section 7).
Run from the workspace root: python3 -m pytest tests/test_judge_story.py -v

Plain pytest asserts only -- no check() helper, which reports false greens under
pytest. No test makes a network call: the autouse fixture below makes constructing
the real anthropic.Anthropic client fail the test, and every test that reaches the
API installs a recording fake first. Exactly one test function per spec test ID
(18 total); multi-case IDs loop inside their function.
"""

import copy
import importlib.machinery
import json
import os
import re
import types
import uuid

import anthropic
import httpx
import jsonschema
import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
_SCRIPT_PATH = os.path.join(WS, "bin", "judge-story")
judge_story = importlib.machinery.SourceFileLoader("judge_story", _SCRIPT_PATH).load_module()

SENTINEL_KEY = "sk-test-SENTINEL-do-not-leak"
SCORE_NAMES = ("pacing_progression", "action_plausibility", "visual_specificity", "continuity")

# Distinct per-dimension scores so a score copied under the wrong name is caught.
VALID_INPUT = {
    "scores": {"pacing_progression": 7, "action_plausibility": 6,
               "visual_specificity": 8, "continuity": 5},
    "critique": "Panel 3 stalls the chase; Panel 7 lands the jump — keep it.",
    "revised_prompt": "Write a 5-panel action story.\nKeep every panel filmable.",
}


@pytest.fixture(autouse=True)
def _no_real_client(monkeypatch):
    """SC4 guard for every test: constructing the real client fails the test, and the
    key starts unset. Tests that reach the API install a recording fake over this."""
    def _forbidden(*args, **kwargs):
        raise AssertionError("test constructed a real anthropic.Anthropic client")
    monkeypatch.setattr(judge_story.anthropic, "Anthropic", _forbidden)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


# --- T5: submit_judgment schema validation (spec 4.3, 4.4) ---------------------------

def test_t5a_missing_top_level_key_rejected():
    for key in ("scores", "critique", "revised_prompt"):
        payload = copy.deepcopy(VALID_INPUT)
        del payload[key]
        with pytest.raises(jsonschema.ValidationError):
            judge_story.validate_judgment_input(payload)


def test_t5b_missing_score_key_rejected():
    for key in SCORE_NAMES:
        payload = copy.deepcopy(VALID_INPUT)
        del payload["scores"][key]
        with pytest.raises(jsonschema.ValidationError):
            judge_story.validate_judgment_input(payload)


def test_t5c_out_of_range_or_non_integer_score_rejected():
    # 0 and 11 are the spec's range cases; "7", 7.5 and True pin "non-integer score"
    # (jsonschema does not count booleans as integers). Every dimension is checked.
    for key in SCORE_NAMES:
        for bad in (0, 11, "7", 7.5, True):
            payload = copy.deepcopy(VALID_INPUT)
            payload["scores"][key] = bad
            with pytest.raises(jsonschema.ValidationError):
                judge_story.validate_judgment_input(payload)


def test_t5d_valid_payload_accepted():
    for value in (1, 10):
        payload = copy.deepcopy(VALID_INPUT)
        payload["scores"] = {key: value for key in SCORE_NAMES}
        assert judge_story.validate_judgment_input(payload) is None
    # No additionalProperties constraint: extra keys are tolerated (spec 4.3).
    payload = copy.deepcopy(VALID_INPUT)
    payload["extra"] = "ignored"
    payload["scores"]["extra_score"] = 99
    assert judge_story.validate_judgment_input(payload) is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_story.py -v
```
Expected: collection error `ERROR tests/test_judge_story.py` with `FileNotFoundError` naming `bin/judge-story`, then `Interrupted: 1 error during collection`. Exit code 2.

- [ ] **Step 3: Write minimal implementation**

Create `bin/judge-story` with exactly this content, then make it executable:

```python
#!/usr/bin/env python3
"""judge-story -- judge a generated story.md with Claude and propose a revised prompt.

Phase 1 of the story-pipeline self-improvement loop
(docs/superpowers/specs/2026-10-02-judge-story-design.md). Observational only:
it reads a story.md and the sibling story_prompt.txt that bin/ltx-movie's
Phase 1 wrote next to it, asks Claude (extended thinking) to call the
submit_judgment tool with four 1-10 scores, a panel-specific critique, and a
revised story-generation prompt, then writes judgment.json and
story_prompt.revised.txt next to story.md and prints the scores, critique,
and revised prompt. It never regenerates anything.

Usage:
  bin/judge-story --story-id <id>               # generated/stories/<id>/story.md
  bin/judge-story --story-md <path/to/story.md>

Requires ANTHROPIC_API_KEY in the environment. Exit codes: 0 success,
1 runtime or API failure, 2 argument or precondition failure. If Claude never
calls submit_judgment (after one retry) or its input fails schema validation,
the raw API responses are written to judgment.raw.json and no scores are
reported.
"""

import argparse
import datetime
import json
import os
import sys

import anthropic
import jsonschema

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

MODEL = "claude-opus-5-5"
THINKING_BUDGET_TOKENS = 16000
# 21333 is the SDK's largest non-streaming max_tokens without an explicit timeout=;
# it leaves ~5,300 visible-output tokens above the thinking budget (spec 4.1, G1).
MAX_TOKENS = 21333
TOOL_NAME = "submit_judgment"
TOOL_DESCRIPTION = ("Submit your judgment of the story: four 1-10 scores, a critique naming "
                    "specific panels by number, and a full revised story-generation prompt. "
                    "You must call this exactly once.")

# Output order of the scores in judgment.json and on stdout (spec 5.1, 5.3).
SCORE_KEYS = ("pacing_progression", "action_plausibility", "visual_specificity", "continuity")

SUBMIT_JUDGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "object",
            "properties": {
                "pacing_progression": {"type": "integer", "minimum": 1, "maximum": 10},
                "action_plausibility": {"type": "integer", "minimum": 1, "maximum": 10},
                "visual_specificity": {"type": "integer", "minimum": 1, "maximum": 10},
                "continuity": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["pacing_progression", "action_plausibility", "visual_specificity",
                         "continuity"],
        },
        "critique": {
            "type": "string",
            "description": "Free-text critique. Name specific panels by number (e.g. 'Panel 7').",
        },
        "revised_prompt": {
            "type": "string",
            "description": ("A complete replacement for the original story-generation prompt "
                            "that addresses the critique."),
        },
    },
    "required": ["scores", "critique", "revised_prompt"],
}


def validate_judgment_input(tool_input):
    """Raise jsonschema.ValidationError unless tool_input matches SUBMIT_JUDGMENT_SCHEMA.

    The schema has no $schema key, so jsonschema uses its latest draft, which does not
    count booleans as integers. Extra keys are tolerated (no additionalProperties).
    """
    jsonschema.validate(instance=tool_input, schema=SUBMIT_JUDGMENT_SCHEMA)
```

```bash
chmod +x /Users/reubenpatterson/local_model_harness/qwen-agent-workspace/bin/judge-story
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_story.py -v
```
Expected: `4 passed, 1 warning` (the warning is the `load_module` DeprecationWarning).

Mechanical spec check: the schema must equal spec Section 4.3's JSON block exactly, and the constants must match Sections 1.2 and 4.1.
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && test -x bin/judge-story && echo "executable OK" && python3 - <<'EOF'
import importlib.machinery, json
js = importlib.machinery.SourceFileLoader("judge_story", "bin/judge-story").load_module()
lines = open("docs/superpowers/specs/2026-10-02-judge-story-design.md", encoding="utf-8").read().split("\n")
i = next(n for n, l in enumerate(lines) if l.startswith("### 4.3"))
start = next(n for n in range(i + 1, len(lines)) if lines[n].startswith("```json")) + 1
end = next(n for n in range(start, len(lines)) if lines[n].startswith("```"))
assert js.SUBMIT_JUDGMENT_SCHEMA == json.loads("\n".join(lines[start:end])), "schema != spec 4.3"
assert (js.MODEL, js.THINKING_BUDGET_TOKENS, js.MAX_TOKENS, js.TOOL_NAME) == (
    "claude-opus-5-5", 16000, 21333, "submit_judgment")
assert js.SCORE_KEYS == tuple(js.SUBMIT_JUDGMENT_SCHEMA["properties"]["scores"]["required"])
print("PASS schema and constants match the spec")
EOF
```
Expected: `executable OK`, then `PASS schema and constants match the spec`.

Mutation check (spec 7.4, the T5c half of "maximum 10 -> 11"; Task 5 re-runs it with T10b). This script self-restores the file:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile
PATH = "bin/judge-story"
OLD, NEW, COUNT = '"maximum": 10', '"maximum": 11', 4
TESTS = ["test_t5c_out_of_range_or_non_integer_score_rejected"]
def run(name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="judge-story-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "tests/test_judge_story.py::" + name],
                          capture_output=True, text=True, env=env).returncode
src = open(PATH, encoding="utf-8").read()
assert src.count(OLD) == COUNT, "anchor count %d != %d" % (src.count(OLD), COUNT)
for name in TESTS:
    assert run(name) == 0, "control: %s must pass unmutated" % name
try:
    with open(PATH, "w", encoding="utf-8") as f:
        f.write(src.replace(OLD, NEW))
    for name in TESTS:
        rc = run(name)
        print("%s: %s" % (name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
        assert rc == 1, "mutation not caught by " + name
finally:
    with open(PATH, "w", encoding="utf-8") as f:
        f.write(src)
assert open(PATH, encoding="utf-8").read() == src
print("restored bin/judge-story")
EOF
```
Expected: `test_t5c_out_of_range_or_non_integer_score_rejected: CAUGHT`, then `restored bin/judge-story`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
git diff --cached --name-only            # expect: no output
git add -- bin/judge-story tests/test_judge_story.py
git diff --cached --name-only            # expect exactly the two paths below
# qwen-agent-workspace/bin/judge-story
# qwen-agent-workspace/tests/test_judge_story.py
git commit -F - <<'EOF'
judge-story: add script skeleton and submit_judgment schema validation

New standalone bin/judge-story (spec 2026-10-02-judge-story-design.md):
module constants (model, thinking budget, max_tokens, tool name and
description), the submit_judgment JSON Schema from spec 4.3 verbatim,
and validate_judgment_input(). Tests T5a-T5d cover missing keys, out-of-
range and non-integer scores (incl. booleans), and valid payloads; an
autouse fixture makes constructing a real Anthropic client fail any test.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
```

---

### Task 3: Prompt text, user message, and tool-use lookup

**Files:**
- Modify: `bin/judge-story`. Insert `SYSTEM_PROMPT` and `RETRY_USER_MESSAGE` immediately before `def validate_judgment_input` (they become lines 76-106), and append `build_user_message` and `find_tool_use` at the end of the file (they become lines 118-139).
- Test: no new pytest function. The spec defines no test ID for these, and A1 requires exactly 18 tests; T7 and T9 exercise them through `main()` in Tasks 5-6. Verification is an ephemeral stdin check that compares the module against the spec's own verbatim text.

**Interfaces:**
- Consumes: `TOOL_NAME`, `TOOL_DESCRIPTION` (Task 2).
- Produces: `SYSTEM_PROMPT: str`, `RETRY_USER_MESSAGE: str`, `build_user_message(story_md_text, story_prompt_text) -> str`, and `find_tool_use(response) -> ToolUseBlock | None` (first `content` block with `type == "tool_use"` and `name == TOOL_NAME`). Tasks 5 and 6 call all four.

- [ ] **Step 1: Write the failing test**

This is an ephemeral check that pulls the verbatim text out of the spec file itself, so a paraphrase cannot pass. Save nothing. Steps 2 and 4 paste this same block.

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import importlib.machinery, re
import anthropic
js = importlib.machinery.SourceFileLoader("judge_story", "bin/judge-story").load_module()
lines = open("docs/superpowers/specs/2026-10-02-judge-story-design.md", encoding="utf-8").read().split("\n")
def fenced_after(marker):
    i = next(n for n, l in enumerate(lines) if marker in l)
    start = next(n for n in range(i + 1, len(lines)) if lines[n].startswith("```")) + 1
    end = next(n for n in range(start, len(lines)) if lines[n].startswith("```"))
    return "\n".join(lines[start:end])
def quoted_after(marker):
    line = next(l for l in lines if marker in l)
    return re.search(r'`"(.*)"`', line.split(marker, 1)[1]).group(1)
assert js.SYSTEM_PROMPT == fenced_after("`SYSTEM_PROMPT` **[spec choice"), "SYSTEM_PROMPT != spec 4.5"
assert js.RETRY_USER_MESSAGE == quoted_after("`RETRY_USER_MESSAGE` **[spec choice, verbatim]**"), "RETRY_USER_MESSAGE != spec 4.6"
assert js.TOOL_DESCRIPTION == quoted_after("`TOOL_DESCRIPTION` **[spec choice, verbatim]**"), "TOOL_DESCRIPTION != spec 4.1"
template = fenced_after("returns exactly:")
sp, sm = "Write {panels} panels.\n100% concrete.  \n", "# Story\n\n## Panel 1\nA fox.\n"
assert js.build_user_message(sm, sp) == template.replace(
    "{story_prompt_text}", sp).replace("{story_md_text}", sm), "user message != spec 4.5"
assert js.build_user_message("", "") == template.replace(
    "{story_prompt_text}", "").replace("{story_md_text}", ""), "empty inputs must pass through"
def msg(content):
    return anthropic.types.Message.model_validate({
        "id": "msg_x", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "stop_reason": "end_turn", "stop_sequence": None, "content": content,
        "usage": {"input_tokens": 1, "output_tokens": 1}})
think = {"type": "thinking", "thinking": "t", "signature": "s"}
text = {"type": "text", "text": "prose"}
other = {"type": "tool_use", "id": "toolu_a", "name": "other_tool", "input": {}}
want1 = {"type": "tool_use", "id": "toolu_b", "name": "submit_judgment", "input": {"n": 1}}
want2 = {"type": "tool_use", "id": "toolu_c", "name": "submit_judgment", "input": {"n": 2}}
assert js.find_tool_use(msg([think, text])) is None
assert js.find_tool_use(msg([think, other])) is None
assert js.find_tool_use(msg([think, text, other, want1, want2])).id == "toolu_b"
print("PASS prompts, user message, and find_tool_use match the spec")
EOF
```

- [ ] **Step 2: Run test to verify it fails**

Paste and run the Step 1 block. Expected: a traceback ending in `AttributeError: module 'judge_story' has no attribute 'SYSTEM_PROMPT'`.

- [ ] **Step 3: Write minimal implementation**

Edit 1 uses the Edit tool on `bin/judge-story`.

old_string:
```python
def validate_judgment_input(tool_input):
```
new_string:
```python
SYSTEM_PROMPT = (
    "You are an expert story editor judging a story written for an AI image-and-video "
    "generation pipeline. The story is intended to become a multi-panel, action-focused "
    "storyboard. The target output goal is the most realistic action scenes possible, with "
    "relatively little dialogue.\n"
    "\n"
    "Score the story on four dimensions, each an integer from 1 (worst) to 10 (best):\n"
    "- pacing_progression: whether the action builds and progresses panel to panel, without "
    "stalls, repeats, or jumps.\n"
    "- action_plausibility: whether each panel depicts physically realistic action that a "
    "camera could plausibly capture.\n"
    "- visual_specificity: whether each panel gives concrete, filmable visual detail rather "
    "than abstract or emotional description.\n"
    "- continuity: whether characters, setting, props, and positions stay consistent across "
    "panels.\n"
    "\n"
    "Then write a critique that names specific panels by number (for example, \"Panel 7\") "
    "when identifying strengths and problems.\n"
    "\n"
    "Finally, write a complete revised version of the original story-generation prompt that "
    "would address your critique. The revised prompt must be a full replacement for the "
    "original prompt, usable as-is, not a list of suggested edits.\n"
    "\n"
    "You must deliver your judgment by calling the submit_judgment tool exactly once. Do not "
    "put the judgment in a plain text reply; a response without a submit_judgment call is a "
    "failure."
)

RETRY_USER_MESSAGE = ("You did not call the submit_judgment tool. Call submit_judgment now "
                      "with your scores, critique, and revised_prompt. Do not reply with "
                      "plain text.")


def validate_judgment_input(tool_input):
```

Edit 2 appends this at the end of `bin/judge-story`, after `validate_judgment_input`'s body, with exactly two blank lines before the first `def`:

```python


def build_user_message(story_md_text, story_prompt_text):
    """The single user turn (spec 4.5). Both texts are inserted in full: no truncation,
    escaping, or stripping."""
    return ("Below are the original story-generation prompt and the story it produced.\n"
            "\n"
            "<story_prompt>\n"
            + story_prompt_text
            + "\n</story_prompt>\n"
            "\n"
            "<story_md>\n"
            + story_md_text
            + "\n</story_md>\n"
            "\n"
            "Judge the story and call submit_judgment.")


def find_tool_use(response):
    """First content block that is a submit_judgment tool call, else None."""
    for block in response.content:
        if block.type == "tool_use" and block.name == TOOL_NAME:
            return block
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Paste and run the Step 1 block. Expected: `PASS prompts, user message, and find_tool_use match the spec`.

Then confirm Task 2's tests still pass:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_story.py -q
```
Expected: `4 passed, 1 warning`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
git diff --cached --name-only            # expect: no output
git add -- bin/judge-story
git diff --cached --name-only            # expect exactly: qwen-agent-workspace/bin/judge-story
git commit -F - <<'EOF'
judge-story: add judging prompts, user message, and tool-call lookup

SYSTEM_PROMPT, RETRY_USER_MESSAGE, and the build_user_message() template
are transcribed verbatim from spec 4.5/4.6 (checked mechanically against
the spec text); find_tool_use() returns the first submit_judgment
tool_use block or None.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
```

---

### Task 4: CLI, path resolution, file preconditions, and the API-key gate

**Files:**
- Modify: `bin/judge-story`. Append `build_parser`, `resolve_paths`, `main` (an interim version that ends at client construction), and the `__main__` guard at the end of the file (they become lines 140-200).
- Test: append to `tests/test_judge_story.py`. This adds test helpers and tests T1a, T1b, T2a, T2b, T3a, T3b, T4, T8 (they become lines 91-229).

**Interfaces:**
- Consumes: `WS` (Task 2). Uses no Task 3 symbol yet.
- Produces: `build_parser() -> argparse.ArgumentParser`, `resolve_paths(story_id, story_md) -> (story_dir, story_md_path, story_prompt_path)`, and `main(argv=None) -> int`. In this task `main` implements spec 1.1 steps 1-7 and then raises `NotImplementedError("judging call is added by plan Task 5")`. No test reaches that line, because every Task 4 test returns at step 3, 4, or 6. Test helpers produced: `STORY_MD_TEXT`, `STORY_PROMPT_TEXT`, `_make_story(directory, with_prompt=True) -> pathlib.Path`, `_FakeAnthropic` (attributes `.constructions: list[(args, kwargs)]`, `.calls: list[dict]`, `.messages.create(**kwargs)`), and `_install_fake(monkeypatch, scripted) -> _FakeAnthropic`. Tasks 5-6 use all of them.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_judge_story.py`:

```python


# --- shared fixtures for main() tests -------------------------------------------------

# Trailing whitespace, "%", "{...}" and a non-ASCII dash check that the texts reach the
# user message untouched (no stripping, formatting, or escaping).
STORY_MD_TEXT = "# Fox crossing\n\n## Panel 1\nPrompt: A fox steps onto river ice — dawn.\n"
STORY_PROMPT_TEXT = "Write a {panels}-panel story about a fox.\nUse 100% concrete detail.  \n"


def _make_story(directory, with_prompt=True):
    directory.mkdir(parents=True, exist_ok=True)
    story_md = directory / "story.md"
    story_md.write_text(STORY_MD_TEXT, encoding="utf-8")
    if with_prompt:
        (directory / "story_prompt.txt").write_text(STORY_PROMPT_TEXT, encoding="utf-8")
    return story_md


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
    monkeypatch.setattr(judge_story.anthropic, "Anthropic", fake)
    return fake


# --- T1-T4: arguments, path resolution, file preconditions (spec 1.1, 3, 6) ---------

def test_t1a_both_flags_exit_2():
    with pytest.raises(SystemExit) as exc:
        judge_story.main(["--story-id", "x", "--story-md", "y"])
    assert exc.value.code == 2


def test_t1b_no_flags_exit_2():
    with pytest.raises(SystemExit) as exc:
        judge_story.main([])
    assert exc.value.code == 2


def test_t2a_resolve_paths_story_id(monkeypatch, tmp_path):
    assert judge_story.WS == WS
    base = os.path.join(WS, "generated", "stories", "abc")
    assert judge_story.resolve_paths("abc", None) == (
        base, os.path.join(base, "story.md"), os.path.join(base, "story_prompt.txt"))
    # WS is read at call time, not import time (spec 1.2).
    monkeypatch.setattr(judge_story, "WS", str(tmp_path))
    assert judge_story.resolve_paths("abc", None)[0] == os.path.join(
        str(tmp_path), "generated", "stories", "abc")


def test_t2b_resolve_paths_story_md(monkeypatch, tmp_path):
    s = tmp_path / "s"
    expected = (str(s), str(s / "story.md"), str(s / "story_prompt.txt"))
    assert judge_story.resolve_paths(None, str(s / "story.md")) == expected
    # A relative --story-md is made absolute against the current directory.
    monkeypatch.chdir(tmp_path)
    assert judge_story.resolve_paths(None, os.path.join("s", "story.md")) == expected


def test_t3a_missing_story_md_exit_2(tmp_path, capsys):
    missing = tmp_path / "story.md"
    assert judge_story.main(["--story-md", str(missing)]) == 2
    out, err = capsys.readouterr()
    assert "Error: story.md not found: %s\n" % missing in err
    assert out == ""
    # Passing the story directory instead of the file is the same precondition failure.
    assert judge_story.main(["--story-md", str(tmp_path)]) == 2
    _, err = capsys.readouterr()
    assert "Error: story.md not found: %s\n" % tmp_path in err
    assert os.listdir(tmp_path) == []


def test_t3b_nonexistent_story_id_exit_2(capsys):
    story_id = "judge-story-test-nonexistent-%s" % uuid.uuid4().hex
    assert judge_story.main(["--story-id", story_id]) == 2
    _, err = capsys.readouterr()
    assert "Error: story.md not found: " in err
    assert not os.path.exists(os.path.join(WS, "generated", "stories", story_id))


def test_t4_missing_story_prompt_exit_2(tmp_path, capsys):
    story_md = _make_story(tmp_path, with_prompt=False)
    assert judge_story.main(["--story-md", str(story_md)]) == 2
    out, err = capsys.readouterr()
    assert err == (
        "Error: story_prompt.txt not found: %s. judge-story needs the original "
        "story-generation prompt to produce revised_prompt. This story may predate "
        "bin/ltx-movie's story_prompt.txt persistence (re-run its Phase 1 with "
        "--force-story), or --story-md points at a directory without the sibling file.\n"
        % (tmp_path / "story_prompt.txt"))
    assert out == ""
    assert os.listdir(tmp_path) == ["story.md"]


# --- T8: API-key gate (spec 4.2) -------------------------------------------------------

def test_t8_key_unset_never_constructs_client(tmp_path, monkeypatch, capsys):
    _make_story(tmp_path)
    fake = _install_fake(monkeypatch, [])
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert judge_story.main(["--story-md", str(tmp_path / "story.md")]) == 1
    assert fake.constructions == []
    assert fake.calls == []
    out, err = capsys.readouterr()
    assert "ANTHROPIC_API_KEY" in err
    assert err == ("Error: ANTHROPIC_API_KEY is not set; export it in your environment to "
                   "run judge-story.\n")
    assert out == ""
    # An empty value counts as unset (spec 4.2).
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert judge_story.main(["--story-md", str(tmp_path / "story.md")]) == 1
    assert fake.constructions == []
    assert fake.calls == []
    _, err = capsys.readouterr()
    assert err.startswith("Error: ANTHROPIC_API_KEY is not set")
    assert sorted(os.listdir(tmp_path)) == ["story.md", "story_prompt.txt"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_story.py -q
```
Expected: `8 failed, 4 passed, 1 warning`. Each of the 8 new tests fails with `AttributeError: module 'judge_story' has no attribute 'main'` (or `'resolve_paths'` for T2a/T2b).

- [ ] **Step 3: Write minimal implementation**

Append to the end of `bin/judge-story`, with exactly two blank lines before the first `def`:

```python


def build_parser():
    parser = argparse.ArgumentParser(
        prog="judge-story",
        description="Judge a generated story.md with Claude and propose a revised story prompt.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--story-id", dest="story_id", metavar="ID",
                       help="judge generated/stories/ID/story.md and its sibling "
                            "story_prompt.txt")
    group.add_argument("--story-md", dest="story_md", metavar="PATH",
                       help="judge the story.md at PATH; story_prompt.txt must sit next to it")
    return parser


def resolve_paths(story_id, story_md):
    """(story_dir, story_md_path, story_prompt_path) for --story-id or --story-md (spec 3.2).

    Reads WS at call time. --story-md is made absolute without resolving symlinks.
    """
    if story_id is not None:
        story_dir = os.path.join(WS, "generated", "stories", story_id)
        story_md_path = os.path.join(story_dir, "story.md")
    else:
        story_md_path = os.path.abspath(story_md)
        story_dir = os.path.dirname(story_md_path)
    story_prompt_path = os.path.join(story_dir, "story_prompt.txt")
    return story_dir, story_md_path, story_prompt_path


def main(argv=None):
    args = build_parser().parse_args(argv)
    story_dir, story_md_path, story_prompt_path = resolve_paths(args.story_id, args.story_md)

    if not os.path.isfile(story_md_path):
        print("Error: story.md not found: %s" % story_md_path, file=sys.stderr)
        return 2
    if not os.path.isfile(story_prompt_path):
        print("Error: story_prompt.txt not found: %s. judge-story needs the original "
              "story-generation prompt to produce revised_prompt. This story may predate "
              "bin/ltx-movie's story_prompt.txt persistence (re-run its Phase 1 with "
              "--force-story), or --story-md points at a directory without the sibling "
              "file." % story_prompt_path, file=sys.stderr)
        return 2
    with open(story_md_path, encoding="utf-8") as f:
        story_md_text = f.read()
    with open(story_prompt_path, encoding="utf-8") as f:
        story_prompt_text = f.read()

    # Checked before the client exists; the key is never read into a variable -- the
    # SDK picks it up from the environment itself (spec 4.2).
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set; export it in your environment to run "
              "judge-story.", file=sys.stderr)
        return 1
    client = anthropic.Anthropic()
    raise NotImplementedError("judging call is added by plan Task 5")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_story.py -q
```
Expected: `12 passed, 1 warning`.

Run a real-shebang smoke test. It proves the `#!/usr/bin/env python3` interpreter imports `anthropic` and `jsonschema` (spec G5a):
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && bin/judge-story --help >/dev/null; echo "help rc=$?"; bin/judge-story --story-id judge-story-smoke-nonexistent; echo "missing rc=$?"; bin/judge-story; echo "noargs rc=$?"
```
Expected: `help rc=0`. Then `Error: story.md not found: /Users/reubenpatterson/local_model_harness/qwen-agent-workspace/generated/stories/judge-story-smoke-nonexistent/story.md` and `missing rc=2`. Then argparse usage plus `judge-story: error: one of the arguments --story-id --story-md is required` and `noargs rc=2`.

Mutation checks (spec 7.4: key check after construction must fail T8, and missing `story_prompt.txt` returning 0 must fail T4). Run this self-restoring script:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile
PATH = "bin/judge-story"
KEY_BLOCK = '''    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set; export it in your environment to run "
              "judge-story.", file=sys.stderr)
        return 1
'''
CLIENT = "    client = anthropic.Anthropic()\n"
MUTATIONS = [
    ("key check after construction", KEY_BLOCK + CLIENT, CLIENT + KEY_BLOCK, 1,
     ["test_t8_key_unset_never_constructs_client"]),
    ("missing story_prompt.txt returns 0",
     '"file." % story_prompt_path, file=sys.stderr)\n        return 2\n',
     '"file." % story_prompt_path, file=sys.stderr)\n        return 0\n', 1,
     ["test_t4_missing_story_prompt_exit_2"]),
]
def run(name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="judge-story-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "tests/test_judge_story.py::" + name],
                          capture_output=True, text=True, env=env).returncode
src = open(PATH, encoding="utf-8").read()
for label, old, new, count, tests in MUTATIONS:
    assert src.count(old) == count, "%s: anchor count %d != %d" % (label, src.count(old), count)
    for name in tests:
        assert run(name) == 0, "control: %s must pass unmutated" % name
    try:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(src.replace(old, new))
        for name in tests:
            rc = run(name)
            print("[%s] %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation not caught"
    finally:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(src)
assert open(PATH, encoding="utf-8").read() == src
print("restored bin/judge-story")
EOF
```
Expected: two `CAUGHT` lines, then `restored bin/judge-story`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
git diff --cached --name-only            # expect: no output
git add -- bin/judge-story tests/test_judge_story.py
git diff --cached --name-only            # expect exactly the two paths below
# qwen-agent-workspace/bin/judge-story
# qwen-agent-workspace/tests/test_judge_story.py
git commit -F - <<'EOF'
judge-story: add CLI, path resolution, preconditions, and API-key gate

--story-id / --story-md (mutually exclusive, required), resolve_paths()
per spec 3.2, exit 2 for a missing story.md or story_prompt.txt (with
the --force-story hint for pre-persistence stories), and exit 1 for an
unset or empty ANTHROPIC_API_KEY before any client is constructed.
main() stops at client construction; the judging call lands next.
Tests T1a-T4 and T8; mutations (key check moved after construction,
return 0 on missing prompt) both caught.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
```

---

### Task 5: Judging call, schema-failure path, output files, and stdout

**Files:**
- Modify: `bin/judge-story`. Insert `_create_message` and `_write_raw` immediately before `def main(argv=None):` (they become lines 170-197). Replace main's two interim lines (`client = anthropic.Anthropic()` and `raise NotImplementedError(...)`) with the happy path. Main's body then ends at line 274, and the `__main__` guard sits at lines 276-277.
- Test: append to `tests/test_judge_story.py`. This adds response builders and tests T7, T10b (they become lines 230-350).

**Interfaces:**
- Consumes: `MODEL`, `MAX_TOKENS`, `THINKING_BUDGET_TOKENS`, `TOOL_NAME`, `TOOL_DESCRIPTION`, `SUBMIT_JUDGMENT_SCHEMA`, `SCORE_KEYS`, and `validate_judgment_input` (Task 2). `SYSTEM_PROMPT`, `build_user_message`, and `find_tool_use` (Task 3). `main`'s locals `story_dir`, `story_md_path`, `story_prompt_path`, `story_md_text`, and `story_prompt_text` (Task 4). Test helpers `_make_story`, `_install_fake`, `STORY_MD_TEXT`, `STORY_PROMPT_TEXT`, `VALID_INPUT`, `SENTINEL_KEY`, and `SCORE_NAMES` (Tasks 2 and 4).
- Produces: `_create_message(client, messages) -> anthropic.types.Message` (the fixed spec 4.1 request) and `_write_raw(story_dir, responses) -> str` (path of `judgment.raw.json`). `main` now does one call, validation, writes, and stdout. A response with no tool call is not handled yet: `block.input` raises `AttributeError` until Task 6 adds the retry. Test helpers produced: `THINKING_BLOCK`, `_usage(input_tokens, output_tokens, thinking_tokens)`, `_message(content, usage, stop_reason)`, `_tool_response(tool_input, usage)`, and `_text_response(text, usage)`. Task 6 uses all of them.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_judge_story.py`:

```python


# --- SDK response builders: real anthropic.types.Message objects (spec 7.1) ----------

THINKING_BLOCK = {"type": "thinking", "thinking": "Weighing panel-to-panel momentum.",
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


# --- T7: successful run (spec 4.1, 5.1-5.3) ------------------------------------------

def test_t7_successful_run(tmp_path, monkeypatch, capsys):
    story_md = _make_story(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    fake = _install_fake(monkeypatch, [
        _tool_response(copy.deepcopy(VALID_INPUT), _usage(1200, 3400, 2100))])

    assert judge_story.main(["--story-md", str(story_md)]) == 0

    with open(tmp_path / "judgment.json", encoding="utf-8") as f:
        raw_text = f.read()
    judgment = json.loads(raw_text)
    assert list(judgment) == ["story_md_path", "story_prompt_path", "model",
                              "thinking_budget_tokens", "timestamp", "usage", "scores",
                              "critique", "revised_prompt"]
    assert judgment["story_md_path"] == str(story_md)
    assert judgment["story_prompt_path"] == str(tmp_path / "story_prompt.txt")
    assert judgment["model"] == "claude-opus-5-5"
    assert judgment["thinking_budget_tokens"] == 16000
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", judgment["timestamp"])
    assert judgment["usage"] == {"input_tokens": 1200, "output_tokens": 3400,
                                 "thinking_tokens": 2100}
    assert list(judgment["scores"]) == list(SCORE_NAMES)
    assert judgment["scores"] == VALID_INPUT["scores"]
    assert judgment["critique"] == VALID_INPUT["critique"]
    assert judgment["revised_prompt"] == VALID_INPUT["revised_prompt"]
    assert "—" in raw_text            # ensure_ascii=False
    assert raw_text.endswith("}\n")        # trailing newline after json.dump

    assert ((tmp_path / "story_prompt.revised.txt").read_bytes()
            == VALID_INPUT["revised_prompt"].encode("utf-8"))
    assert not (tmp_path / "judgment.raw.json").exists()

    out, err = capsys.readouterr()
    score_lines = "".join("  %-20s  %d\n" % (name, VALID_INPUT["scores"][name])
                          for name in SCORE_NAMES)
    assert "  pacing_progression    7\n" in score_lines   # pins the %-20s layout itself
    assert out == ("Scores:\n" + score_lines
                   + "\n--- Critique ---\n" + VALID_INPUT["critique"] + "\n"
                   + "\n--- Revised prompt ---\n" + VALID_INPUT["revised_prompt"] + "\n")
    assert err == ""

    assert fake.constructions == [((), {})]               # Anthropic() with no arguments
    assert len(fake.calls) == 1
    kwargs = fake.calls[0]
    assert sorted(kwargs) == ["max_tokens", "messages", "model", "system", "thinking",
                              "tool_choice", "tools"]
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["max_tokens"] == 21333
    assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": 16000}
    assert kwargs["tool_choice"] == {"type": "auto"}
    assert kwargs["system"] == judge_story.SYSTEM_PROMPT
    assert [tool["name"] for tool in kwargs["tools"]] == ["submit_judgment"]
    assert kwargs["tools"][0]["input_schema"] == judge_story.SUBMIT_JUDGMENT_SCHEMA
    assert kwargs["tools"][0]["description"] == judge_story.TOOL_DESCRIPTION
    messages = kwargs["messages"]
    assert len(messages) == 1 and messages[0]["role"] == "user"
    assert STORY_MD_TEXT in messages[0]["content"]
    assert STORY_PROMPT_TEXT in messages[0]["content"]
    assert messages[0]["content"] == (
        "Below are the original story-generation prompt and the story it produced.\n"
        "\n<story_prompt>\n" + STORY_PROMPT_TEXT + "\n</story_prompt>\n"
        "\n<story_md>\n" + STORY_MD_TEXT + "\n</story_md>\n"
        "\nJudge the story and call submit_judgment.")


# --- T10b: schema-invalid tool input (spec 4.4, E7) ----------------------------------

def test_t10b_schema_invalid_tool_input(tmp_path, monkeypatch, capsys):
    story_md = _make_story(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    bad = copy.deepcopy(VALID_INPUT)
    bad["scores"]["continuity"] = 11
    fake = _install_fake(monkeypatch, [_tool_response(bad, _usage(10, 20, 5))])

    assert judge_story.main(["--story-md", str(story_md)]) == 1

    assert len(fake.calls) == 1            # no retry on a validation failure (spec G3)
    with open(tmp_path / "judgment.raw.json", encoding="utf-8") as f:
        raw = json.load(f)
    assert len(raw["responses"]) == 1
    assert raw["responses"][0]["content"][1]["input"]["scores"]["continuity"] == 11
    assert not (tmp_path / "judgment.json").exists()
    assert not (tmp_path / "story_prompt.revised.txt").exists()
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("Error: submit_judgment input failed schema validation: ")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_story.py -q
```
Expected: `2 failed, 12 passed, 1 warning`. T7 and T10b both fail with `NotImplementedError: judging call is added by plan Task 5`.

- [ ] **Step 3: Write minimal implementation**

Edit 1 uses the Edit tool on `bin/judge-story`.

old_string:
```python
def main(argv=None):
```
new_string:
```python
def _create_message(client, messages):
    """One non-streaming judging call with the fixed spec 4.1 parameters. No temperature,
    top_k, or top_p: extended thinking rejects non-default values."""
    return client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "enabled", "budget_tokens": THINKING_BUDGET_TOKENS},
        system=SYSTEM_PROMPT,
        tools=[{
            "name": TOOL_NAME,
            "description": TOOL_DESCRIPTION,
            "input_schema": SUBMIT_JUDGMENT_SCHEMA,
        }],
        # Extended thinking cannot force a specific tool; SYSTEM_PROMPT requires the call.
        tool_choice={"type": "auto"},
        messages=messages,
    )


def _write_raw(story_dir, responses):
    """Dump every API response received this run to judgment.raw.json; return its path."""
    path = os.path.join(story_dir, "judgment.raw.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"responses": [r.model_dump(mode="json") for r in responses]}, f,
                  indent=2, ensure_ascii=False)
    return path


def main(argv=None):
```

Edit 2 uses the Edit tool on `bin/judge-story`.

old_string:
```python
    client = anthropic.Anthropic()
    raise NotImplementedError("judging call is added by plan Task 5")
```
new_string:
```python
    client = anthropic.Anthropic()

    user_message = build_user_message(story_md_text, story_prompt_text)
    responses = [_create_message(client, [{"role": "user", "content": user_message}])]
    block = find_tool_use(responses[0])
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        validate_judgment_input(block.input)
    except jsonschema.ValidationError as e:
        _write_raw(story_dir, responses)
        print("Error: submit_judgment input failed schema validation: %s" % e.message,
              file=sys.stderr)
        return 1

    tool_input = block.input
    thinking_counts = [r.usage.output_tokens_details.thinking_tokens for r in responses
                       if r.usage.output_tokens_details is not None
                       and r.usage.output_tokens_details.thinking_tokens is not None]
    judgment = {
        "story_md_path": story_md_path,
        "story_prompt_path": story_prompt_path,
        "model": MODEL,
        "thinking_budget_tokens": THINKING_BUDGET_TOKENS,
        "timestamp": timestamp,
        "usage": {
            "input_tokens": sum(r.usage.input_tokens for r in responses),
            "output_tokens": sum(r.usage.output_tokens for r in responses),
            # null, never a fabricated 0, when no response reports it (spec 5.1, G4)
            "thinking_tokens": sum(thinking_counts) if thinking_counts else None,
        },
        "scores": {name: tool_input["scores"][name] for name in SCORE_KEYS},
        "critique": tool_input["critique"],
        "revised_prompt": tool_input["revised_prompt"],
    }
    with open(os.path.join(story_dir, "judgment.json"), "w", encoding="utf-8") as f:
        json.dump(judgment, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with open(os.path.join(story_dir, "story_prompt.revised.txt"), "w", encoding="utf-8") as f:
        f.write(judgment["revised_prompt"])

    print("Scores:")
    for name in SCORE_KEYS:
        print("  %-20s  %d" % (name, judgment["scores"][name]))
    print()
    print("--- Critique ---")
    print(judgment["critique"])
    print()
    print("--- Revised prompt ---")
    print(judgment["revised_prompt"])
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_story.py -q
```
Expected: `14 passed, 1 warning`.

Mutation checks (spec 7.4: a trailing newline on the revised prompt must fail T7, and "maximum 10 -> 11" must fail both T5c and T10b). Run this self-restoring script:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile
PATH = "bin/judge-story"
MUTATIONS = [
    ("revised prompt gains a trailing newline",
     'f.write(judgment["revised_prompt"])', 'f.write(judgment["revised_prompt"] + "\\n")', 1,
     ["test_t7_successful_run"]),
    ("score maximum 10 -> 11", '"maximum": 10', '"maximum": 11', 4,
     ["test_t5c_out_of_range_or_non_integer_score_rejected",
      "test_t10b_schema_invalid_tool_input"]),
]
def run(name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="judge-story-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "tests/test_judge_story.py::" + name],
                          capture_output=True, text=True, env=env).returncode
src = open(PATH, encoding="utf-8").read()
for label, old, new, count, tests in MUTATIONS:
    assert src.count(old) == count, "%s: anchor count %d != %d" % (label, src.count(old), count)
    for name in tests:
        assert run(name) == 0, "control: %s must pass unmutated" % name
    try:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(src.replace(old, new))
        for name in tests:
            rc = run(name)
            print("[%s] %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation not caught"
    finally:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(src)
assert open(PATH, encoding="utf-8").read() == src
print("restored bin/judge-story")
EOF
```
Expected: three `CAUGHT` lines, then `restored bin/judge-story`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
git diff --cached --name-only            # expect: no output
git add -- bin/judge-story tests/test_judge_story.py
git diff --cached --name-only            # expect exactly the two paths below
# qwen-agent-workspace/bin/judge-story
# qwen-agent-workspace/tests/test_judge_story.py
git commit -F - <<'EOF'
judge-story: add the judging call, outputs, and schema-failure path

One non-streaming messages.create (claude-opus-5-5, extended thinking
16000, max_tokens 21333, one submit_judgment tool, tool_choice auto),
jsonschema validation of the tool input, then judgment.json (spec 5.1
key order, usage summed, thinking_tokens null when unreported) and
story_prompt.revised.txt (verbatim), and the exact spec 5.3 stdout.
Invalid tool input writes judgment.raw.json and exits 1 with no retry.
Tests T7 and T10b; trailing-newline and maximum-11 mutations caught.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
```

---

### Task 6: One retry, double failure, API errors, and the key-leak guard

**Files:**
- Modify: `bin/judge-story`, in the `main()` body. Replace the two lines `responses = [_create_message(...)]` and `block = find_tool_use(responses[0])` (lines 226-227) with the try/retry/except block plus the double-failure branch. They become lines 226-249. The file ends at line 299.
- Test: append to `tests/test_judge_story.py`. This adds tests T9, T10, T10c, T11 (they become lines 351-470).

**Interfaces:**
- Consumes: `_create_message`, `_write_raw` (Task 5); `find_tool_use`, `RETRY_USER_MESSAGE` (Task 3); and main's locals `client`, `user_message`, `story_dir` (Tasks 4-5). Test helpers `_make_story`, `_install_fake`, `_tool_response`, `_text_response`, `_usage`, `VALID_INPUT`, and `SENTINEL_KEY` (Tasks 2, 4, 5).
- Produces: the final `main()`, which implements spec 1.1 steps 1-11, Section 4.6, and E5/E6. No new symbols for later tasks. This is the last code task.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_judge_story.py`:

```python


# --- T9-T11: retry, double failure, API errors, key leakage (spec 4.6, 6) ------------

def test_t9_retry_after_missing_tool_call(tmp_path, monkeypatch):
    story_md = _make_story(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    # r1 reports no thinking_tokens; r2 does: the sum covers only the responses that
    # report it (spec 5.1).
    r1 = _text_response("Here is my judgment in prose.", _usage(100, 200, None))
    r2 = _tool_response(copy.deepcopy(VALID_INPUT), _usage(1000, 3000, 2500))
    fake = _install_fake(monkeypatch, [r1, r2])

    assert judge_story.main(["--story-md", str(story_md)]) == 0

    assert len(fake.calls) == 2
    first, second = fake.calls
    assert len(first["messages"]) == 1     # the retry builds a new list, not an append
    retry_messages = second["messages"]
    assert len(retry_messages) == 3
    assert [m["role"] for m in retry_messages] == ["user", "assistant", "user"]
    assert retry_messages[0] == first["messages"][0]
    assert retry_messages[1]["content"] == r1.content
    assert retry_messages[1]["content"][0].type == "thinking"
    assert retry_messages[1]["content"][0].signature == "sig-abc123"
    assert retry_messages[2]["content"] == judge_story.RETRY_USER_MESSAGE
    assert second["tool_choice"] == {"type": "auto"}
    assert ({k: v for k, v in second.items() if k != "messages"}
            == {k: v for k, v in first.items() if k != "messages"})
    with open(tmp_path / "judgment.json", encoding="utf-8") as f:
        judgment = json.load(f)
    assert judgment["usage"] == {"input_tokens": 1100, "output_tokens": 3200,
                                 "thinking_tokens": 2500}
    assert judgment["scores"] == VALID_INPUT["scores"]
    assert not (tmp_path / "judgment.raw.json").exists()


def test_t10_double_failure_writes_raw_and_no_judgment(tmp_path, monkeypatch, capsys):
    story_md = _make_story(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    r1 = _text_response("Prose judgment, attempt one.", _usage(100, 200, 50))
    r2 = _text_response("Prose judgment, attempt two.", _usage(110, 210, 60))
    fake = _install_fake(monkeypatch, [r1, r2])

    assert judge_story.main(["--story-md", str(story_md)]) == 1

    assert len(fake.calls) == 2
    with open(tmp_path / "judgment.raw.json", encoding="utf-8") as f:
        raw = json.load(f)
    assert len(raw["responses"]) == 2
    assert raw["responses"] == [r1.model_dump(mode="json"), r2.model_dump(mode="json")]
    assert not (tmp_path / "judgment.json").exists()
    assert not (tmp_path / "story_prompt.revised.txt").exists()
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ("Error: Claude did not call submit_judgment after one retry; raw "
                   "responses written to %s\n" % (tmp_path / "judgment.raw.json"))


def test_t10c_api_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)

    def connection_error():
        return anthropic.APIConnectionError(
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))

    # The first call raises.
    first_dir = tmp_path / "first"
    story_md = _make_story(first_dir)
    fake = _install_fake(monkeypatch, [connection_error()])
    assert judge_story.main(["--story-md", str(story_md)]) == 1
    assert len(fake.calls) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert "Anthropic API call failed" in err
    assert err.startswith("Error: Anthropic API call failed: APIConnectionError: ")
    assert sorted(os.listdir(first_dir)) == ["story.md", "story_prompt.txt"]

    # The retry call raises: E5 applies and r1 is not dumped (spec 6, E5 details).
    retry_dir = tmp_path / "retry"
    story_md = _make_story(retry_dir)
    fake = _install_fake(monkeypatch, [
        _text_response("Prose only.", _usage(100, 200, 50)), connection_error()])
    assert judge_story.main(["--story-md", str(story_md)]) == 1
    assert len(fake.calls) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("Error: Anthropic API call failed: APIConnectionError: ")
    assert sorted(os.listdir(retry_dir)) == ["story.md", "story_prompt.txt"]


def test_t11_api_key_never_leaks(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)

    # T7 scenario (success). These responses omit output_tokens_details, so this run
    # also pins usage.thinking_tokens == null rather than a fabricated 0 (spec 5.1, G4).
    ok_dir = tmp_path / "ok"
    story_md = _make_story(ok_dir)
    _install_fake(monkeypatch, [
        _tool_response(copy.deepcopy(VALID_INPUT), _usage(1200, 3400, None))])
    assert judge_story.main(["--story-md", str(story_md)]) == 0
    ok_out, ok_err = capsys.readouterr()

    # T10 scenario (double failure).
    fail_dir = tmp_path / "fail"
    story_md = _make_story(fail_dir)
    _install_fake(monkeypatch, [_text_response("Prose one.", _usage(1, 2, None)),
                                _text_response("Prose two.", _usage(3, 4, None))])
    assert judge_story.main(["--story-md", str(story_md)]) == 1
    fail_out, fail_err = capsys.readouterr()

    written = [ok_dir / "judgment.json", ok_dir / "story_prompt.revised.txt",
               fail_dir / "judgment.raw.json"]
    for path in written:
        assert path.is_file(), path
    with open(ok_dir / "judgment.json", encoding="utf-8") as f:
        assert json.load(f)["usage"]["thinking_tokens"] is None
    for text in [ok_out, ok_err, fail_out, fail_err] + [p.read_text(encoding="utf-8")
                                                         for p in written]:
        assert SENTINEL_KEY not in text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_story.py -q
```
Expected: `4 failed, 14 passed, 1 warning`. T9, T10, and T11 fail with `AttributeError: 'NoneType' object has no attribute 'input'`. T10c fails with an uncaught `anthropic.APIConnectionError: Connection error.`

- [ ] **Step 3: Write minimal implementation**

Use the Edit tool on `bin/judge-story`.

old_string:
```python
    responses = [_create_message(client, [{"role": "user", "content": user_message}])]
    block = find_tool_use(responses[0])
```
new_string:
```python
    responses = []
    try:
        responses.append(_create_message(client, [{"role": "user", "content": user_message}]))
        block = find_tool_use(responses[0])
        if block is None:
            # One retry in the same conversation. r1.content goes back exactly as
            # received: the API requires thinking blocks and signatures unmodified.
            responses.append(_create_message(client, [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": responses[0].content},
                {"role": "user", "content": RETRY_USER_MESSAGE},
            ]))
            block = find_tool_use(responses[1])
    except anthropic.APIError as e:
        # Covers APIStatusError subclasses, APIConnectionError, and APITimeoutError. A
        # failed retry discards r1 rather than dumping it (spec 6, E5).
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
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_story.py -v
```
Expected: 18 `PASSED` lines (T1a T1b T2a T2b T3a T3b T4 T5a T5b T5c T5d T7 T8 T9 T10 T10b T10c T11), then `18 passed, 1 warning`.

Mutation checks (spec 7.4: removing the retry must fail T9, and skipping the `judgment.raw.json` write must fail T10). Run this self-restoring script:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile
PATH = "bin/judge-story"
RETRY_BLOCK = '''        if block is None:
            # One retry in the same conversation. r1.content goes back exactly as
            # received: the API requires thinking blocks and signatures unmodified.
            responses.append(_create_message(client, [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": responses[0].content},
                {"role": "user", "content": RETRY_USER_MESSAGE},
            ]))
            block = find_tool_use(responses[1])
'''
MUTATIONS = [
    ("retry removed", RETRY_BLOCK, "", 1, ["test_t9_retry_after_missing_tool_call"]),
    ("judgment.raw.json not written",
     "        raw_path = _write_raw(story_dir, responses)\n",
     '        raw_path = os.path.join(story_dir, "judgment.raw.json")\n', 1,
     ["test_t10_double_failure_writes_raw_and_no_judgment"]),
]
def run(name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="judge-story-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "tests/test_judge_story.py::" + name],
                          capture_output=True, text=True, env=env).returncode
src = open(PATH, encoding="utf-8").read()
for label, old, new, count, tests in MUTATIONS:
    assert src.count(old) == count, "%s: anchor count %d != %d" % (label, src.count(old), count)
    for name in tests:
        assert run(name) == 0, "control: %s must pass unmutated" % name
    try:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(src.replace(old, new))
        for name in tests:
            rc = run(name)
            print("[%s] %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation not caught"
    finally:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(src)
assert open(PATH, encoding="utf-8").read() == src
print("restored bin/judge-story")
EOF
```
Expected: two `CAUGHT` lines, then `restored bin/judge-story`.

Confirm no interim marker survives: `/usr/bin/grep -c NotImplementedError bin/judge-story` prints `0`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
git diff --cached --name-only            # expect: no output
git add -- bin/judge-story tests/test_judge_story.py
git diff --cached --name-only            # expect exactly the two paths below
# qwen-agent-workspace/bin/judge-story
# qwen-agent-workspace/tests/test_judge_story.py
git commit -F - <<'EOF'
judge-story: add one retry, double-failure dump, and API error handling

If the first response has no submit_judgment call, retry once in the
same conversation (r1.content passed back unmodified, thinking blocks
included). A second miss writes judgment.raw.json with both responses
and exits 1; any anthropic.APIError on either call exits 1 with no files
written. Never fabricates scores. Tests T9, T10, T10c, T11 (key never in
stdout/stderr/files); retry-removed and skip-raw-dump mutations caught.
Full suite: 18 passed.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
```

---

## Final acceptance (main thread, after Task 6; spec Section 8.3)

These are run by the orchestrating session, not by the task implementer, because implementer-reported counts are not accepted (spec A1). They change no files.

### A1: suite count

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_story.py -v; /usr/bin/grep -c '^def test_' tests/test_judge_story.py
```
Pass: `18 passed, 1 warning`, one per spec ID in Sections 7.2 and 7.3, and the grep prints `18`.

### A2: all six spec 7.4 mutations on the final file (self-restoring)

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile
PATH = "bin/judge-story"
KEY_BLOCK = '''    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set; export it in your environment to run "
              "judge-story.", file=sys.stderr)
        return 1
'''
CLIENT = "    client = anthropic.Anthropic()\n"
RETRY_BLOCK = '''        if block is None:
            # One retry in the same conversation. r1.content goes back exactly as
            # received: the API requires thinking blocks and signatures unmodified.
            responses.append(_create_message(client, [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": responses[0].content},
                {"role": "user", "content": RETRY_USER_MESSAGE},
            ]))
            block = find_tool_use(responses[1])
'''
MUTATIONS = [
    ("key check after construction", KEY_BLOCK + CLIENT, CLIENT + KEY_BLOCK, 1,
     ["test_t8_key_unset_never_constructs_client"]),
    ("score maximum 10 -> 11", '"maximum": 10', '"maximum": 11', 4,
     ["test_t5c_out_of_range_or_non_integer_score_rejected",
      "test_t10b_schema_invalid_tool_input"]),
    ("retry removed", RETRY_BLOCK, "", 1, ["test_t9_retry_after_missing_tool_call"]),
    ("judgment.raw.json not written",
     "        raw_path = _write_raw(story_dir, responses)\n",
     '        raw_path = os.path.join(story_dir, "judgment.raw.json")\n', 1,
     ["test_t10_double_failure_writes_raw_and_no_judgment"]),
    ("missing story_prompt.txt returns 0",
     '"file." % story_prompt_path, file=sys.stderr)\n        return 2\n',
     '"file." % story_prompt_path, file=sys.stderr)\n        return 0\n', 1,
     ["test_t4_missing_story_prompt_exit_2"]),
    ("revised prompt gains a trailing newline",
     'f.write(judgment["revised_prompt"])', 'f.write(judgment["revised_prompt"] + "\\n")', 1,
     ["test_t7_successful_run"]),
]
def run(name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="judge-story-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "tests/test_judge_story.py::" + name],
                          capture_output=True, text=True, env=env).returncode
src = open(PATH, encoding="utf-8").read()
for label, old, new, count, tests in MUTATIONS:
    assert src.count(old) == count, "%s: anchor count %d != %d" % (label, src.count(old), count)
    for name in tests:
        assert run(name) == 0, "control: %s must pass unmutated" % name
    try:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(src.replace(old, new))
        for name in tests:
            rc = run(name)
            print("[%s] %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation not caught"
    finally:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(src)
assert open(PATH, encoding="utf-8").read() == src
print("restored bin/judge-story")
EOF
```
Pass: six mutations, seven `CAUGHT` lines (the maximum-11 mutation is checked against both T5c and T10b), then `restored bin/judge-story`.

### R1: ltx-movie regression

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 tests/test_ltx_movie_offline.py > /tmp/judge_story_r1_final.txt 2>&1; echo "rc=$?"; tail -1 /tmp/judge_story_r1_final.txt
```
Pass: `rc=0` and `OK 340/340`, matching the pre-Task-1 baseline.

### Scope check

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && git diff --name-only HEAD~6..HEAD && git show --stat --format=%s HEAD~5
```
Pass: the first command lists exactly `qwen-agent-workspace/bin/judge-story`, `qwen-agent-workspace/bin/ltx-movie`, and `qwen-agent-workspace/tests/test_judge_story.py`. The second shows the Task 1 commit as `bin/ltx-movie | 3 +++`. This assumes the six task commits are the six most recent. If other commits were interleaved, replace `HEAD~6` with the commit before Task 1.

### M1 (manual): a real Phase 1 run writes story_prompt.txt

This needs the story server listening on 8177. Run `bin/ltx-movie "a lone climber races a storm down a ridge" --story-id judge-story-m1 --panels 3`. When Phase 1 prints `Review story.md above. Enter to continue, Ctrl-C to abort:`, press Ctrl-C, so no stills or render run. If `generated/stories/judge-story-m1/story.md` already exists from an earlier attempt, add `--force-story`, or Phase 1 is skipped and no prompt is written. Then:

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import importlib.machinery
m = importlib.machinery.SourceFileLoader("ltx_movie", "bin/ltx-movie").load_module()
argv = ["a lone climber races a storm down a ridge", "--story-id", "judge-story-m1", "--panels", "3"]
args = m.build_parser().parse_args(argv)
m._resolve_length(args, argv)
expected = m.build_story_prompt(args.narrative, args.story_id, args.panels, args.no_stills,
                                bool(getattr(args, "seed_image", None)),
                                seconds=m._clip_seconds(args))
data = open("generated/stories/judge-story-m1/story_prompt.txt", "rb").read()
assert data == expected.encode("utf-8"), "M1 FAIL: story_prompt.txt != build_story_prompt()"
print("M1 PASS (%d bytes)" % len(data))
EOF
```
Pass: `M1 PASS (...)`.

### M2 (manual): a real judging run

This needs a real `ANTHROPIC_API_KEY` exported. Run `bin/judge-story --story-id judge-story-m1; echo "rc=$?"`. Pass: `rc=0`, `generated/stories/judge-story-m1/judgment.json` and `story_prompt.revised.txt` both present, and stdout matches the spec 5.3 layout. This is also the first live check of spec G6 (whether `claude-opus-5-5` accepts `thinking.type: "enabled"` with `tool_choice: auto`). If the API rejects the request, report it to the user as a design question. Do not patch around it.
