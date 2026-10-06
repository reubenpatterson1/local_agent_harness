# bin/judge-stills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `bin/judge-stills`, a hand-run, observe-only tool that sends a story's generated `panel_NN.png` stills, each paired by position with its panel's `Image:`/`Motion:`/`Narration:` text from `story.md`, to Claude and writes the returned 1-10 scores (`visual_continuity` only when 2 or more stills are judged) and panel-specific critique to `stills_judgment.json`.
**Architecture:** One standalone executable Python script, `bin/judge-stills`, modeled on `bin/judge-story`: no extension, `main(argv=None) -> int`, no imports from other `bin/*` files (the `story.md` panel parser is duplicated inline from `bin/ltx-story-manifest`), and no shared module. It runs the local file preconditions (images dir, stills, `story.md`, still-to-panel pairing), then the env-key gate, then at most two non-streaming `messages.create` calls carrying interleaved text and base64 PNG blocks (one retry, only when no tool call comes back), then jsonschema validation plus a stills-count-conditional `visual_continuity` check, then output writes.
**Tech Stack:** Python 3.13.0 (`/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`), `anthropic` 0.116.0 (Messages API, adaptive thinking, tool use, base64 image blocks), `jsonschema` 4.23.0, `httpx` 0.28.1 (tests only, to build an `APIConnectionError`), `pytest` 8.3.4.
**Spec:** docs/superpowers/specs/2026-10-04-judge-stills-design.md

## Global Constraints

- Workspace root `WS` = `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/`. Run every command in this plan from `WS`. The git repo root is one level up, so `git diff --name-only` prints paths with the `qwen-agent-workspace/` prefix.
- Exactly two files are created: `bin/judge-stills` (`chmod +x`) and `tests/test_judge_stills.py`. No other file is created or modified. `bin/judge-story`, `bin/ltx-story-images`, `bin/ltx-story-manifest`, and `bin/ltx-movie` are not touched (spec 0.3).
- Not added to the deploy package (`tests/test_deploy_pkg.py`) and not wired into `bin/ltx-movie`'s `_phase_sequence`; the dual-interpreter gate does not apply (spec 0.4, 7.5).
- Script conventions: shebang `#!/usr/bin/env python3`, module docstring at the top, no file extension, executable bit set, `def main(argv=None):` returning an `int`, ending with `if __name__ == "__main__":` / `    sys.exit(main())`.
- Top-level imports, in this order: `argparse`, `base64`, `datetime`, `json`, `os`, `re`, `sys`, then `anthropic` and `jsonschema`. Nothing is imported or loaded from another `bin/*` file (no `SourceFileLoader` of `bin/ltx-story-manifest`; spec G7).
- `WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))`, read by `resolve_paths` at call time, not at import time.
- `MODEL = "claude-opus-5-5"`; `EFFORT = "high"`; `MAX_TOKENS = 21333`; `TOOL_NAME = "submit_judgment"`; `MEDIA_TYPE = "image/png"`; `SCORE_KEYS = ("prompt_fidelity", "visual_continuity", "rendering_quality", "composition")`.
- `STILL_NAME_RE = re.compile(r"panel_(\d{2,})\.png")`, used with `fullmatch` over `os.listdir` (never `glob`). `PANEL_HEADER_RE = re.compile(r"^##\s*Panel\s*(\d+)\s*[—–-]\s*(.*)$")` and `PANEL_LABEL_RE = re.compile(r"^(Image|Motion|Narration|Prompt|Style):\s*(.*)$")`, verbatim copies of `bin/ltx-story-manifest:81-82`.
- Request: `thinking={"type": "adaptive"}`, `output_config={"effort": "high"}`, `tool_choice={"type": "auto"}`, exactly one tool, `system=SYSTEM_PROMPT`. Never `thinking={"type": "enabled", "budget_tokens": ...}` (the live API rejects it; judge-story commit `3203d8c`). No `temperature`/`top_k`/`top_p`, no streaming, no `timeout=`. The SDK's default `max_retries` (2) is left unchanged (spec G10).
- API key: read only via `os.environ.get("ANTHROPIC_API_KEY")`. `None` and `""` both count as unset. Checked before `anthropic.Anthropic()` is constructed, which is called with no arguments. The key is never assigned, printed, logged, interpolated, or written.
- At most two API calls per run. The single retry happens only when no `submit_judgment` tool_use block comes back, and it re-sends the same `user_content` list (all images). A validation failure is never retried.
- `SUBMIT_JUDGMENT_SCHEMA`'s `scores.required` is exactly `["prompt_fidelity", "rendering_quality", "composition"]`. `visual_continuity` is defined in `properties` but is NOT required by the schema (spec 4.3, G1 resolution).
- `validate_judgment_input(tool_input, stills_count)` takes two arguments. It runs `jsonschema.validate(instance=tool_input, schema=SUBMIT_JUDGMENT_SCHEMA)`, then, when `stills_count >= 2` and `"visual_continuity"` is not in `tool_input["scores"]`, raises `jsonschema.ValidationError("visual_continuity is required when judging 2 or more stills")`. `main` calls it as `validate_judgment_input(block.input, len(stills))`.
- `build_user_content` ends with `FINAL_USER_TEXT_MULTI_TEMPLATE % count` when `count >= 2`, else `FINAL_USER_TEXT_SINGLE`.
- Exit codes: 0 success, 1 runtime/API failure (E6-E9), 2 argument/precondition failure (E1-E5). Every error goes to stderr and starts with `Error: `. Exceptions outside the spec Section 6 table (`OSError` reading a still, `UnicodeDecodeError` reading `story.md`, `OSError` writing output) are not caught.
- E2 `Error: stills directory not found: <images_dir>`; E3 `Error: no panel_NN.png stills found in <images_dir>`; E4 `Error: story.md not found: <story_md_path>`; E5 `Error: <still_path> has no matching panel section in story.md (story.md has <len(panels)> panel sections); the stills may be stale relative to story.md.`; E6 `Error: ANTHROPIC_API_KEY is not set; export it in your environment to run judge-stills.`; E7 `Error: Anthropic API call failed: <type(e).__name__>: <str(e)>`; E8 `Error: Claude did not call submit_judgment after one retry; raw responses written to <raw_path>`; E9 `Error: submit_judgment input failed schema validation: <ValidationError.message>`.
- Precondition order in `main`: images dir (E2), stills found (E3), `story.md` (E4), pairing (E5), then key (E6). Still `(index, path)` pairs with `panels[index - 1]` by position; panels with no still are not sent.
- `stills_judgment.json`: `json.dump(obj, f, indent=2, ensure_ascii=False)` plus a trailing `"\n"`. Key order: `story_id, model, effort, timestamp, usage, scores, critique`. `scores` is in `SCORE_KEYS` order; `scores.visual_continuity` is `tool_input["scores"].get("visual_continuity")`, so JSON `null` in the 1-still case, never a fabricated integer. `usage` is summed over every response; `usage.thinking_tokens` is JSON `null` when no response reports it.
- `stills_judgment.raw.json` (E8/E9 only): `{"responses": [r.model_dump(mode="json"), ...]}`, `indent=2`, `ensure_ascii=False`, no trailing newline added.
- Outputs go to the story directory root. They overwrite earlier files without prompting and never delete anything. The tool never writes `judgment.json` or `judgment.raw.json` (those belong to `bin/judge-story`).
- Stdout is used on success only: exactly `"Scores:\n" + score_lines + "\n--- Critique ---\n" + critique + "\n"`. Each score line is `format_score_line(name, value)`: `"  %-20s  %d"`, or `"  %-20s  n/a (only 1 still)"` when the value is `None`.
- Out of scope: judging clips, any regeneration loop, `revised_prompt`, `--story-md`, reading `images.json`, sending `Style:`/`Prompt:` text, resizing/recompressing/chunking/size-based rejection, staleness checks beyond E5, non-PNG formats, backoff, `--story-id` validation, streaming.
- Tests: pytest with plain `assert`, never the `check()` helper. Exactly **32** test functions, one per spec test ID: T1a T1b T2 T3 T4a T4b T4c T5 T6 T7 T7b T7c T8a T8b T8c T8d T8e T8f T9a T9b T9c T9d T9e T10 T10b T11 T12 T13 T14 T14b T15 T16. Multi-case IDs loop inside one function. Extra coverage goes in as extra assertions inside those 32 functions, never as new test functions. No network: an autouse fixture makes constructing the real client fail the test. Every `main()` fixture lives under `tmp_path` with `judge_stills.WS` monkeypatched to it.
- Pytest prints one `DeprecationWarning` for `SourceFileLoader.load_module()` (the loader spec 7.1 mandates), so every passing run ends `N passed, 1 warning`. On startup it also prints a `pytest_asyncio` `PytestDeprecationWarning` about `asyncio_default_fixture_loop_scope`. Both are expected and are not failures.
- R1 baseline, measured 2026-10-03 before any change: `python3 -m pytest tests/test_judge_story.py -q` ends `19 passed, 1 warning`.
- Every mutation runner gives each pytest subprocess a fresh `PYTHONPYCACHEPREFIX`. Do not remove it: without it, a same-size mutation written in the same second as an earlier compile can load the stale `.pyc` and falsely survive (observed during the judge-story plan's validation).
- Commit hygiene: the working tree has unrelated modified and untracked files. Stage only by explicit path. Before each commit, confirm `git diff --cached --name-only` lists only that task's files. Commit messages end with `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.

## Review Focus

1. **The story has exactly one still, which is true of every story the current pipeline produces (spec G1).** `visual_continuity` must come out as JSON `null` in the file and `n/a (only 1 still)` on stdout, never as a fabricated integer and never as a `"%d" % None` crash. The judge must be told the count (the final text block says "1 still"). With 2 or more stills, a judgment that omits `visual_continuity` must fail E9 with a raw dump, not be written as `null`. Tests: T8e, T8f (Task 1); T7, T7b, T7c (Task 3); T10, T10b, T14b (Task 5).
2. **Stills and `story.md` don't line up.** `bin/iterate-story` output such as `ronin-iterate-test` has no `images/` directory at all (E2). Stills can be renamed or partial (E3). `story.md` can be regenerated with fewer panels than there are stills (E5). Each case must exit 2 with its exact message before any API work and write nothing, and the images check must run first. Tests: T9a-T9e (Task 4); real-data smoke S1 (Final acceptance).
3. **A still is judged against the wrong text.** Causes: `Style:` leaking into `Image:` in seed-image stories, a `## Notes` section attaching to a panel, an empty-title header being missed, `panel_100.png` sorting before `panel_99.png`, or a chain panel with no still being sent anyway. Tests: T3, T4a-T4c, T5 (Task 2, plus the real-story parser parity check); T10 (Task 5, panel 2 absent and order checked by decoding the base64).
4. **Claude answers in prose or returns a malformed judgment.** `tool_choice` cannot force the tool under thinking. The tool must make exactly one retry that re-sends every image and passes `r1.content` back unmodified, with the thinking signature. A double failure must write a raw dump and exit 1. A schema-invalid score (0, 11, `"7"`, `7.5`, `true`, missing key) must exit 1 with no retry. Usage must be summed correctly. Tests: T8a-T8d (Task 1); T14 (Task 5); T12, T13 (Task 6).
5. **Environment or API failure, and key leakage.** Cases: the key is unset or empty, or either call fails. Many-still stories can exceed the 32 MB request cap and surface as an API error (spec G2). Each case must exit 1 with one `Error:` line, no traceback, no files written, the client never constructed when the key is missing, and the key never echoed anywhere. Tests: T11 (Task 4); T15, T16 (Task 6).

---

### Task 1: Script skeleton, submit_judgment schema, and validate_judgment_input

**Files:**
- Create: `bin/judge-stills` (lines 1-89 at the end of this task), then `chmod +x`.
- Test: create `tests/test_judge_stills.py` (lines 1-118 at the end of this task).

**Interfaces:**
- Consumes: nothing.
- Produces, in `bin/judge-stills`: module globals `WS`, `MODEL`, `EFFORT`, `MAX_TOKENS`, `TOOL_NAME`, `SCORE_KEYS`, `MEDIA_TYPE`, `SUBMIT_JUDGMENT_SCHEMA` (dict), and `validate_judgment_input(tool_input, stills_count) -> None`, which raises `jsonschema.ValidationError`. The anchor comment line `# visual_continuity is deliberately NOT in scores.required: it is required only when` (directly above `SUBMIT_JUDGMENT_SCHEMA`) is where Task 2 inserts its constants. In `tests/test_judge_stills.py`: module globals `WS`, `_SCRIPT_PATH`, `judge_stills`, `SENTINEL_KEY`, `SCORE_NAMES`, `VC_MISSING_MESSAGE`, `VALID_INPUT`, helper `_without_vc(payload) -> dict`, and the autouse fixture `_no_real_client`. Every later test task appends to this file and relies on these names.

- [ ] **Step 1: Write the failing test**

Create `tests/test_judge_stills.py` with exactly this content. The imports `base64`, `json`, `re`, `types`, `uuid`, `anthropic`, and `httpx` are used by tests appended in Tasks 3-6. They are included now so later tasks only append.

```python
"""Tests for bin/judge-stills.

Spec: docs/superpowers/specs/2026-10-04-judge-stills-design.md (Section 7).
Run from the workspace root: python3 -m pytest tests/test_judge_stills.py -v

Plain pytest asserts only -- no check() helper, which reports false greens under
pytest. No test makes a network call: the autouse fixture below makes constructing
the real anthropic.Anthropic client fail the test, and every test that reaches the
API installs a recording fake first. Story fixtures live under tmp_path with
judge_stills.WS patched to it; nothing is written to the real generated/ tree.
Exactly one test function per spec test ID (32 total); multi-case IDs loop inside
their function.
"""

import base64
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
_SCRIPT_PATH = os.path.join(WS, "bin", "judge-stills")
judge_stills = importlib.machinery.SourceFileLoader("judge_stills", _SCRIPT_PATH).load_module()

SENTINEL_KEY = "sk-test-SENTINEL-do-not-leak"
SCORE_NAMES = ("prompt_fidelity", "visual_continuity", "rendering_quality", "composition")
VC_MISSING_MESSAGE = "visual_continuity is required when judging 2 or more stills"

# Distinct per-dimension scores so a score copied under the wrong name is caught. The
# non-ASCII dash checks ensure_ascii=False in the written JSON.
VALID_INPUT = {
    "scores": {"prompt_fidelity": 7, "visual_continuity": 6,
               "rendering_quality": 8, "composition": 5},
    "critique": "Panel 1 nails the dawn light; Panel 3 loses the frog's markings — fix it.",
}


def _without_vc(payload):
    """A deep copy of payload with scores.visual_continuity removed."""
    result = copy.deepcopy(payload)
    del result["scores"]["visual_continuity"]
    return result


@pytest.fixture(autouse=True)
def _no_real_client(monkeypatch):
    """SC7 guard for every test: constructing the real client fails the test, and the
    key starts unset. Tests that reach the API install a recording fake over this."""
    def _forbidden(*args, **kwargs):
        raise AssertionError("test constructed a real anthropic.Anthropic client")
    monkeypatch.setattr(judge_stills.anthropic, "Anthropic", _forbidden)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


# --- T8: submit_judgment validation (spec 4.3, 4.4) ----------------------------------

def test_t8a_missing_top_level_key_rejected():
    for key in ("scores", "critique"):
        payload = copy.deepcopy(VALID_INPUT)
        del payload[key]
        with pytest.raises(jsonschema.ValidationError):
            judge_stills.validate_judgment_input(payload, 2)


def test_t8b_missing_always_required_score_rejected():
    # These three are required by the schema itself, so the stills count is irrelevant.
    for key in ("prompt_fidelity", "rendering_quality", "composition"):
        for stills_count in (1, 2):
            payload = copy.deepcopy(VALID_INPUT)
            del payload["scores"][key]
            with pytest.raises(jsonschema.ValidationError):
                judge_stills.validate_judgment_input(payload, stills_count)


def test_t8c_out_of_range_or_non_integer_score_rejected():
    # 0 and 11 are the range cases; "7", 7.5 and True pin "non-integer score"
    # (jsonschema does not count booleans as integers). Every dimension is checked.
    for key in SCORE_NAMES:
        for bad in (0, 11, "7", 7.5, True):
            payload = copy.deepcopy(VALID_INPUT)
            payload["scores"][key] = bad
            with pytest.raises(jsonschema.ValidationError):
                judge_stills.validate_judgment_input(payload, 2)


def test_t8d_valid_payload_accepted():
    for value in (1, 10):
        payload = copy.deepcopy(VALID_INPUT)
        payload["scores"] = {key: value for key in SCORE_NAMES}
        assert judge_stills.validate_judgment_input(payload, 2) is None
    # No additionalProperties constraint: extra keys are tolerated (spec 4.3).
    payload = copy.deepcopy(VALID_INPUT)
    payload["extra"] = "ignored"
    payload["scores"]["extra_score"] = 99
    assert judge_stills.validate_judgment_input(payload, 2) is None
    # The 1-still shape: visual_continuity omitted, the other three valid.
    assert judge_stills.validate_judgment_input(_without_vc(VALID_INPUT), 1) is None


def test_t8e_visual_continuity_optional_for_one_still():
    assert judge_stills.validate_judgment_input(_without_vc(VALID_INPUT), 1) is None
    # The schema alone allows the omission too (it is not in scores.required).
    jsonschema.validate(instance=_without_vc(VALID_INPUT),
                        schema=judge_stills.SUBMIT_JUDGMENT_SCHEMA)


def test_t8f_visual_continuity_required_for_two_stills():
    with pytest.raises(jsonschema.ValidationError) as exc:
        judge_stills.validate_judgment_input(_without_vc(VALID_INPUT), 2)
    assert exc.value.message == VC_MISSING_MESSAGE
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_stills.py -v
```
Expected: collection error `ERROR tests/test_judge_stills.py - FileNotFoundError: [Errno 2] No such file or directory: '.../bin/judge-stills'`, then `Interrupted: 1 error during collection`. Exit code 2.

- [ ] **Step 3: Write minimal implementation**

Create `bin/judge-stills` with exactly this content, then make it executable. The docstring wording is this plan's choice within spec 1.1's required content; the schema is spec 4.3 verbatim (with `visual_continuity` absent from `scores.required`), and `validate_judgment_input` is spec 4.4 verbatim.

```python
#!/usr/bin/env python3
"""judge-stills -- judge a story's generated panel stills with Claude against the story text.

Loop Phase 3 of the story-pipeline self-improvement loop
(docs/superpowers/specs/2026-10-04-judge-stills-design.md). Observational only:
it reads the panel_NN.png stills that bin/ltx-story-images wrote under
generated/stories/<id>/images/, pairs each still by position with its panel
section of the sibling story.md, and sends each panel's Image:/Motion:/Narration:
text followed by its still to Claude (adaptive thinking, high effort). Claude
calls the submit_judgment tool with 1-10 scores for prompt_fidelity,
rendering_quality, and composition -- plus visual_continuity when 2 or more
stills are judged -- and a critique naming specific panels. The tool writes
stills_judgment.json to the story directory and prints the scores and critique.
It never regenerates anything.

Usage:
  bin/judge-stills --story-id <id>    # generated/stories/<id>/images/ + story.md

Requires ANTHROPIC_API_KEY in the environment. Exit codes: 0 success,
1 runtime or API failure, 2 argument or precondition failure. If Claude never
calls submit_judgment (after one retry) or its input fails validation, the raw
API responses are written to stills_judgment.raw.json and no scores are
reported.
"""

import argparse
import base64
import datetime
import json
import os
import re
import sys

import anthropic
import jsonschema

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

MODEL = "claude-opus-5-5"
EFFORT = "high"
# Same value and rationale as bin/judge-story: the SDK's largest non-streaming
# max_tokens without an explicit timeout= (spec 1.3).
MAX_TOKENS = 21333
TOOL_NAME = "submit_judgment"

# Output order of the scores in stills_judgment.json and on stdout (spec 5.1, 5.3).
SCORE_KEYS = ("prompt_fidelity", "visual_continuity", "rendering_quality", "composition")

# The pipeline always writes PNG stills (spec 3.5).
MEDIA_TYPE = "image/png"

# visual_continuity is deliberately NOT in scores.required: it is required only when
# 2 or more stills are judged, which JSON Schema cannot express, so
# validate_judgment_input enforces that case (spec 4.3, 4.4, G1).
SUBMIT_JUDGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "object",
            "properties": {
                "prompt_fidelity": {"type": "integer", "minimum": 1, "maximum": 10},
                "visual_continuity": {"type": "integer", "minimum": 1, "maximum": 10},
                "rendering_quality": {"type": "integer", "minimum": 1, "maximum": 10},
                "composition": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["prompt_fidelity", "rendering_quality", "composition"],
        },
        "critique": {
            "type": "string",
            "description": "Free-text critique. Name specific panels by number (e.g. 'Panel 3').",
        },
    },
    "required": ["scores", "critique"],
}


def validate_judgment_input(tool_input, stills_count):
    """Raise jsonschema.ValidationError unless tool_input is a complete judgment.

    First the schema check (no $schema key, so jsonschema uses its latest draft, which
    does not count booleans as integers; extra keys are tolerated). Then, when 2 or more
    stills were judged, visual_continuity must be present: its absence there is an
    instruction-following failure, not the legitimate 1-still omission (spec 4.4, G1).
    """
    jsonschema.validate(instance=tool_input, schema=SUBMIT_JUDGMENT_SCHEMA)
    if stills_count >= 2 and "visual_continuity" not in tool_input["scores"]:
        raise jsonschema.ValidationError(
            "visual_continuity is required when judging 2 or more stills"
        )
```

```bash
chmod +x /Users/reubenpatterson/local_model_harness/qwen-agent-workspace/bin/judge-stills
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_stills.py -v
```
Expected: `6 passed, 1 warning`.

Mechanical spec check: the schema must equal spec Section 4.3's JSON block exactly, and the constants must match Section 1.3.
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && test -x bin/judge-stills && echo "executable OK" && python3 - <<'EOF'
import importlib.machinery, json
js = importlib.machinery.SourceFileLoader("judge_stills", "bin/judge-stills").load_module()
lines = open("docs/superpowers/specs/2026-10-04-judge-stills-design.md", encoding="utf-8").read().split("\n")
i = next(n for n, l in enumerate(lines) if l.startswith("### 4.3"))
start = next(n for n in range(i + 1, len(lines)) if lines[n].startswith("```json")) + 1
end = next(n for n in range(start, len(lines)) if lines[n].startswith("```"))
assert js.SUBMIT_JUDGMENT_SCHEMA == json.loads("\n".join(lines[start:end])), "schema != spec 4.3"
assert "visual_continuity" not in js.SUBMIT_JUDGMENT_SCHEMA["properties"]["scores"]["required"]
assert (js.MODEL, js.EFFORT, js.MAX_TOKENS, js.TOOL_NAME, js.MEDIA_TYPE) == (
    "claude-opus-5-5", "high", 21333, "submit_judgment", "image/png")
assert js.SCORE_KEYS == ("prompt_fidelity", "visual_continuity", "rendering_quality", "composition")
assert set(js.SCORE_KEYS) == set(js.SUBMIT_JUDGMENT_SCHEMA["properties"]["scores"]["properties"])
print("PASS schema and constants match the spec")
EOF
```
Expected: `executable OK`, then `PASS schema and constants match the spec`.

Mutation checks (spec 7.4 rows "maximum 10 -> 11", "`visual_continuity` restored to `scores.required`", and "post-validation check removed", at the unit level. Task 5 re-runs them against T14, T10b, and T14b). This script restores the file itself:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile
PATH = "bin/judge-stills"
MUTATIONS = [
    ("score maximum 10 -> 11", '"maximum": 10', '"maximum": 11', 4,
     ["test_t8c_out_of_range_or_non_integer_score_rejected"]),
    ("visual_continuity restored to scores.required", '"required": ["prompt_fidelity", "rendering_quality", "composition"]', '"required": ["prompt_fidelity", "visual_continuity", "rendering_quality", "composition"]', 1,
     ["test_t8e_visual_continuity_optional_for_one_still"]),
    ("2+-stills visual_continuity check removed", '    if stills_count >= 2 and "visual_continuity" not in tool_input["scores"]:\n', "    if False:\n", 1,
     ["test_t8f_visual_continuity_required_for_two_stills"]),
]
def run(name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="judge-stills-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "tests/test_judge_stills.py::" + name],
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
print("restored bin/judge-stills")
EOF
```
Expected: three `CAUGHT` lines, then `restored bin/judge-stills`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
git diff --cached --name-only            # expect: no output
git add -- bin/judge-stills tests/test_judge_stills.py
git diff --cached --name-only            # expect exactly the two paths below
# qwen-agent-workspace/bin/judge-stills
# qwen-agent-workspace/tests/test_judge_stills.py
git commit -F - <<'EOF'
judge-stills: add script skeleton and submit_judgment validation

New standalone bin/judge-stills (spec 2026-10-04-judge-stills-design.md,
loop Phase 3): module constants, the submit_judgment JSON Schema from
spec 4.3 (visual_continuity defined but not schema-required, per the G1
resolution), and validate_judgment_input(tool_input, stills_count), which
adds the 2+-stills visual_continuity check after the schema check.
Tests T8a-T8f; an autouse fixture makes constructing a real Anthropic
client fail any test.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
```

---

### Task 2: Still discovery and story.md panel parsing

**Files:**
- Modify: `bin/judge-stills`. Insert `STILL_NAME_RE`, `PANEL_HEADER_RE`, and `PANEL_LABEL_RE` directly above the `SUBMIT_JUDGMENT_SCHEMA` comment (they become lines 52-59). Append `find_stills`, `parse_panels`, and `format_panel_text` at the end of the file (they become lines 100-166).
- Test: append to `tests/test_judge_stills.py`. This adds the `CHAIN_STORY_MD`, `CHAIN_PANELS`, and `ALL_IMAGE_STORY_MD` fixtures and tests T3, T4a, T4b, T4c, T5 (they become lines 120-215).

**Interfaces:**
- Consumes: nothing from Task 1 except the file itself and the anchor comment above `SUBMIT_JUDGMENT_SCHEMA`.
- Produces: `STILL_NAME_RE`, `PANEL_HEADER_RE`, `PANEL_LABEL_RE` (compiled patterns), `find_stills(images_dir) -> list[tuple[int, str]]` (numeric sort, path tie-break), `parse_panels(story_md_text) -> list[dict]` (each dict has exactly the keys `header`, `image`, `motion`, `narration`), and `format_panel_text(panel) -> str`. Test fixtures produced: `CHAIN_STORY_MD` (3 panels), `CHAIN_PANELS` (its expected parse), and `ALL_IMAGE_STORY_MD`. Tasks 4-6 use `CHAIN_STORY_MD` and `CHAIN_PANELS`.

Grounding verified 2026-10-03 while writing this plan. The spec's parser was run against every `generated/stories/*/story.md` (41 files) and every `story.v*.md` archive (10 more), and its `image`/`motion`/`narration` output equals `bin/ltx-story-manifest._parse_prompts_md`'s on all 51, with the same panel counts: `frogjump` 5, `ronin-iterate-test` 20, `test_story7` 5. Stories with `Style:` lines (`band_red_test`, `drift_red_test`, `mystorytest8`, and others) also match. One discrepancy with spec 3.2: `ronin-iterate-test/story.md` was regenerated by `bin/iterate-story` at 2026-10-03 18:08, and its Panel 12 header now has a title (`## Panel 12 — The Same Hand That Once Collected Debts`). No `story.md` on disk currently has an empty-title header. The empty-title rule is still pinned, by the synthesized `CHAIN_STORY_MD` (`## Panel 2 —`) in T4a, which is what the spec's tests use anyway. Also, `ronin-iterate-test` has no `images/` directory (relevant to Review Focus 2, not to this task).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_judge_stills.py`:

```python


# --- shared story.md fixtures (spec 7.1) ----------------------------------------------

# Synthesized chain-format story: Panel 1 has Image: (with a continuation line) and a
# Style: line that must close Image; a "## Notes" section must not attach anywhere;
# Panel 2 has an empty title; Panels 2-3 have no Image:.
CHAIN_STORY_MD = (
    "## Panel 1 — Dawn on the Pad\n"
    "Image: A green frog on a lily pad — dawn.\n"
    "Second image line.\n"
    "Style: photorealistic, natural light\n"
    "Motion: The frog crouches.\n"
    "Narration: He waits.\n"
    "\n"
    "## Notes\n"
    "Not a panel; must not attach anywhere.\n"
    "\n"
    "## Panel 2 —\n"
    "Motion: The frog leaps.\n"
    "Narration: He jumps.\n"
    "\n"
    "## Panel 3 — Landing\n"
    "Motion: The frog lands on the log.\n"
    "Narration: Safe.\n"
)
CHAIN_PANELS = [
    {"header": "## Panel 1 — Dawn on the Pad",
     "image": "A green frog on a lily pad — dawn. Second image line.",
     "motion": "The frog crouches.", "narration": "He waits."},
    {"header": "## Panel 2 —", "image": "",
     "motion": "The frog leaps.", "narration": "He jumps."},
    {"header": "## Panel 3 — Landing", "image": "",
     "motion": "The frog lands on the log.", "narration": "Safe."},
]

# Pre-chain (frogjump) shape: every panel has Image:, Motion:, Narration: on single lines.
ALL_IMAGE_STORY_MD = (
    "## Panel 1 — A\n"
    "Image: A frog sits on a lily pad.\n"
    "Motion: The frog crouches low.\n"
    "Narration: Morning on the pond.\n"
    "\n"
    "## Panel 2 — B\n"
    "Image: The frog hangs mid-air over the water.\n"
    "Motion: The frog leaps forward.\n"
    "Narration: He jumps.\n"
)


# --- T3-T5: still discovery and panel-text parsing (spec 3.1-3.4) --------------------

def test_t3_find_stills_numeric_sort_and_filter(tmp_path):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    for name in ("panel_03.png", "panel_01.png", "panel_100.png", "panel_99.png",
                 "panel_02.png", "panel_1.png", "panel_01.jpg", "panel_01.png.bak",
                 "Panel_04.png", "images.json"):
        (images_dir / name).write_bytes(b"x")
    d = str(images_dir)
    assert judge_stills.find_stills(d) == [
        (1, os.path.join(d, "panel_01.png")),
        (2, os.path.join(d, "panel_02.png")),
        (3, os.path.join(d, "panel_03.png")),
        (99, os.path.join(d, "panel_99.png")),
        (100, os.path.join(d, "panel_100.png")),
    ]


def test_t4a_parse_panels_chain_fixture():
    assert judge_stills.parse_panels(CHAIN_STORY_MD) == CHAIN_PANELS


def test_t4b_parse_panels_all_image_fixture():
    assert judge_stills.parse_panels(ALL_IMAGE_STORY_MD) == [
        {"header": "## Panel 1 — A", "image": "A frog sits on a lily pad.",
         "motion": "The frog crouches low.", "narration": "Morning on the pond."},
        {"header": "## Panel 2 — B", "image": "The frog hangs mid-air over the water.",
         "motion": "The frog leaps forward.", "narration": "He jumps."},
    ]


def test_t4c_parse_panels_no_panels():
    assert judge_stills.parse_panels("") == []
    assert judge_stills.parse_panels("# Title\nno panels\n") == []


def test_t5_format_panel_text():
    assert judge_stills.format_panel_text(CHAIN_PANELS[0]) == (
        "## Panel 1 — Dawn on the Pad\n"
        "Image: A green frog on a lily pad — dawn. Second image line.\n"
        "Motion: The frog crouches.\n"
        "Narration: He waits.")
    assert judge_stills.format_panel_text(CHAIN_PANELS[1]) == (
        "## Panel 2 —\nMotion: The frog leaps.\nNarration: He jumps.")
    assert judge_stills.format_panel_text(
        {"header": "## Panel 9 — X", "image": "", "motion": "", "narration": ""}) == "## Panel 9 — X"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_stills.py -q
```
Expected: `5 failed, 6 passed, 1 warning`. Each of T3, T4a, T4b, T4c, T5 fails with `AttributeError: module 'judge_stills' has no attribute 'find_stills'` (or `'parse_panels'` / `'format_panel_text'`).

- [ ] **Step 3: Write minimal implementation**

Edit 1 uses the Edit tool on `bin/judge-stills`.

old_string:
```python
# visual_continuity is deliberately NOT in scores.required: it is required only when
```
new_string:
```python
# Still filenames: two or more digits, exactly what bin/ltx-story-images's
# "panel_%02d.png" % i can produce (spec 3.1).
STILL_NAME_RE = re.compile(r"panel_(\d{2,})\.png")

# Verbatim copies of bin/ltx-story-manifest:81-82 (_PANEL_HEADER_RE, _PANEL_LABEL_RE).
# Duplicated rather than loaded, per spec 1.1 / G7: if those change, change these too.
PANEL_HEADER_RE = re.compile(r"^##\s*Panel\s*(\d+)\s*[—–-]\s*(.*)$")
PANEL_LABEL_RE = re.compile(r"^(Image|Motion|Narration|Prompt|Style):\s*(.*)$")

# visual_continuity is deliberately NOT in scores.required: it is required only when
```

Edit 2 appends this at the end of `bin/judge-stills`, after `validate_judgment_input`'s body, with exactly two blank lines before the first `def`:

```python


def find_stills(images_dir):
    """[(index, path)] for every panel_NN.png in images_dir, sorted numerically by index
    (path breaks ties). os.listdir + fullmatch, not glob, so a story id containing
    [ ] * ? is never treated as a wildcard (spec 3.1)."""
    found = []
    for name in os.listdir(images_dir):
        m = STILL_NAME_RE.fullmatch(name)
        if m:
            found.append((int(m.group(1)), os.path.join(images_dir, name)))
    found.sort(key=lambda item: (item[0], item[1]))
    return found


def parse_panels(story_md_text):
    """Panel sections of story.md, in file order, as dicts with header/image/motion/
    narration. The section and field rules duplicate bin/ltx-story-manifest's
    _parse_prompts_md (:202-245) verbatim, so pairing matches what was rendered.
    Prompt: and Style: are recognized only to close the open field, then dropped
    (spec 3.2, G5). Pure."""
    sections = []
    current = None
    for line in story_md_text.splitlines():
        if PANEL_HEADER_RE.match(line):
            if current is not None:
                sections.append(current)
            current = {"header": line, "body": []}
            continue
        if line.startswith("##"):
            if current is not None:
                sections.append(current)
                current = None
            continue
        if current is not None:
            current["body"].append(line)
    if current is not None:
        sections.append(current)

    panels = []
    for section in sections:
        fields = {"Image": [], "Motion": [], "Narration": [], "Prompt": [], "Style": []}
        open_field = None
        for line in section["body"]:
            m = PANEL_LABEL_RE.match(line)
            if m:
                open_field = m.group(1)
                value = m.group(2).strip()
                if value:
                    fields[open_field].append(value)
                continue
            if open_field is not None and line.strip():
                fields[open_field].append(line.strip())
        panels.append({"header": section["header"],
                       "image": " ".join(fields["Image"]),
                       "motion": " ".join(fields["Motion"]),
                       "narration": " ".join(fields["Narration"])})
    return panels


def format_panel_text(panel):
    """The panel's header line, then one line per non-empty field in the fixed order
    Image, Motion, Narration; no trailing newline (spec 3.4). Pure."""
    lines = [panel["header"]]
    for label, key in (("Image", "image"), ("Motion", "motion"), ("Narration", "narration")):
        if panel[key]:
            lines.append("%s: %s" % (label, panel[key]))
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_stills.py -q
```
Expected: `11 passed, 1 warning`.

Real-story parity check. It confirms the duplicated regexes and rules still match `bin/ltx-story-manifest` on every real `story.md`, and that `find_stills` sees frogjump's 5 stills and test_story7's 1. It is read-only.
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import glob, importlib.machinery
js = importlib.machinery.SourceFileLoader("judge_stills", "bin/judge-stills").load_module()
manifest = importlib.machinery.SourceFileLoader(
    "ltx_story_manifest", "bin/ltx-story-manifest").load_module()
assert js.PANEL_HEADER_RE.pattern == manifest._PANEL_HEADER_RE.pattern, "header regex drifted"
assert js.PANEL_LABEL_RE.pattern == manifest._PANEL_LABEL_RE.pattern, "label regex drifted"
paths = sorted(glob.glob("generated/stories/*/story.md"))
for required in ("frogjump", "ronin-iterate-test", "test_story7"):
    assert "generated/stories/%s/story.md" % required in paths, required + " missing"
for path in paths:
    with open(path, encoding="utf-8") as f:
        ours = js.parse_panels(f.read())
    _, theirs = manifest._parse_prompts_md(path)
    assert len(ours) == len(theirs), "%s: %d != %d panels" % (path, len(ours), len(theirs))
    for a, b in zip(ours, theirs):
        for key in ("image", "motion", "narration"):
            assert a[key] == b[key], "%s: %s differs" % (path, key)
counts = {s: len(js.parse_panels(open("generated/stories/%s/story.md" % s, encoding="utf-8").read()))
          for s in ("frogjump", "ronin-iterate-test", "test_story7")}
assert counts == {"frogjump": 5, "ronin-iterate-test": 20, "test_story7": 5}, counts
stills = js.find_stills("generated/stories/frogjump/images")
assert [i for i, _ in stills] == [1, 2, 3, 4, 5], stills
assert [i for i, _ in js.find_stills("generated/stories/test_story7/images")] == [1]
print("PASS parse_panels matches _parse_prompts_md on %d real stories" % len(paths))
EOF
```
Expected: `PASS parse_panels matches _parse_prompts_md on N real stories`, with N = 41 as of 2026-10-03. N may be higher if stories were added since; any assertion error is a failure.

Mutation checks (spec 7.4: string sort, one-digit regex, `Style` removed, `##` branch removed). This script restores the file itself:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile
PATH = "bin/judge-stills"
SECTION_CLOSE = '''        if line.startswith("##"):
            if current is not None:
                sections.append(current)
                current = None
            continue
'''
MUTATIONS = [
    ("find_stills sorts by filename string", "    found.sort(key=lambda item: (item[0], item[1]))\n", "    found.sort(key=lambda item: item[1])\n", 1,
     ["test_t3_find_stills_numeric_sort_and_filter"]),
    ("STILL_NAME_RE accepts one digit", r're.compile(r"panel_(\d{2,})\.png")', r're.compile(r"panel_(\d+)\.png")', 1,
     ["test_t3_find_stills_numeric_sort_and_filter"]),
    ("Style removed from PANEL_LABEL_RE", "Narration|Prompt|Style):", "Narration|Prompt):", 1,
     ["test_t4a_parse_panels_chain_fixture"]),
    ("## section-closing branch removed", SECTION_CLOSE, "", 1,
     ["test_t4a_parse_panels_chain_fixture"]),
]
def run(name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="judge-stills-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "tests/test_judge_stills.py::" + name],
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
print("restored bin/judge-stills")
EOF
```
Expected: four `CAUGHT` lines, then `restored bin/judge-stills`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
git diff --cached --name-only            # expect: no output
git add -- bin/judge-stills tests/test_judge_stills.py
git diff --cached --name-only            # expect exactly the two paths below
# qwen-agent-workspace/bin/judge-stills
# qwen-agent-workspace/tests/test_judge_stills.py
git commit -F - <<'EOF'
judge-stills: add still discovery and story.md panel parsing

find_stills() lists images/ with os.listdir + STILL_NAME_RE.fullmatch
(not glob) and sorts numerically; parse_panels() duplicates
bin/ltx-story-manifest's section/field rules and regexes verbatim
(spec 3.2, G7), keeping header/image/motion/narration; format_panel_text()
renders a panel's text block. Tests T3, T4a-T4c, T5; parser parity with
_parse_prompts_md checked on every real story.md.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
```

---

### Task 3: Prompt texts, image encoding, and user-message content

**Files:**
- Modify: `bin/judge-stills`. Insert `TOOL_DESCRIPTION` directly after `TOOL_NAME` (it becomes lines 45-48). Insert `SYSTEM_PROMPT`, `FINAL_USER_TEXT_SINGLE`, `FINAL_USER_TEXT_MULTI_TEMPLATE`, and `RETRY_USER_MESSAGE` immediately before `def validate_judgment_input` (they become lines 90-139, and `def validate_judgment_input` moves to line 142). Append `encode_still` and `build_user_content` at the end of the file (they become lines 224-249).
- Test: append to `tests/test_judge_stills.py`. This adds the `_still_bytes` helper and tests T6, T7, T7b, T7c (they become lines 217-261).

**Interfaces:**
- Consumes: `MEDIA_TYPE` (Task 1).
- Produces: `TOOL_DESCRIPTION: str`, `SYSTEM_PROMPT: str`, `FINAL_USER_TEXT_SINGLE: str`, `FINAL_USER_TEXT_MULTI_TEMPLATE: str` (one `%d`), `RETRY_USER_MESSAGE: str`, `encode_still(path) -> str` (ASCII base64), and `build_user_content(entries) -> list[dict]`, where `entries` is `[(panel_text, image_b64)]`. Test helper produced: `_still_bytes(k) -> bytes`. Task 4 calls `encode_still` and `build_user_content`; Task 5 sends `SYSTEM_PROMPT` and `TOOL_DESCRIPTION`; Task 6 sends `RETRY_USER_MESSAGE`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_judge_stills.py`:

```python


# --- T6-T7: encoding and user-message content (spec 3.5, 3.6) ------------------------

def _still_bytes(k):
    """Distinct fake PNG bytes for still k (spec 7.1): nothing decodes them, and distinct
    bytes let a test check panel order by decoding the base64 back."""
    return b"\x89PNG\r\n\x1a\n" + b"still-%d" % k


def test_t6_encode_still(tmp_path):
    data = _still_bytes(1)
    path = tmp_path / "panel_01.png"
    path.write_bytes(data)
    result = judge_stills.encode_still(str(path))
    assert result == base64.standard_b64encode(data).decode("ascii")
    assert base64.b64decode(result) == data


def test_t7_build_user_content_two_stills():
    assert judge_stills.build_user_content([("T1", "QQ=="), ("T3", "Qg==")]) == [
        {"type": "text", "text": "T1"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": "QQ=="}},
        {"type": "text", "text": "T3"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": "Qg=="}},
        {"type": "text", "text": judge_stills.FINAL_USER_TEXT_MULTI_TEMPLATE % 2},
    ]
    assert judge_stills.FINAL_USER_TEXT_MULTI_TEMPLATE % 2 == (
        "You are judging all 2 stills above against their panel text. Score all four "
        "dimensions, including visual_continuity, and call submit_judgment.")


def test_t7b_build_user_content_one_still():
    assert judge_stills.build_user_content([("T1", "QQ==")]) == [
        {"type": "text", "text": "T1"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": "QQ=="}},
        {"type": "text", "text": judge_stills.FINAL_USER_TEXT_SINGLE},
    ]


def test_t7c_build_user_content_zero_entries():
    assert judge_stills.build_user_content([]) == [
        {"type": "text", "text": judge_stills.FINAL_USER_TEXT_SINGLE}]
```

This task also has an ephemeral verbatim check. It pulls the text of every prompt constant out of the spec file itself, so a paraphrase cannot pass. Save nothing; Steps 2 and 4 paste this same block.
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import importlib.machinery, re
js = importlib.machinery.SourceFileLoader("judge_stills", "bin/judge-stills").load_module()
lines = open("docs/superpowers/specs/2026-10-04-judge-stills-design.md", encoding="utf-8").read().split("\n")
def fenced_after(marker):
    i = next(n for n, l in enumerate(lines) if marker in l)
    start = next(n for n in range(i + 1, len(lines)) if lines[n].startswith("```")) + 1
    end = next(n for n in range(start, len(lines)) if lines[n].startswith("```"))
    return "\n".join(lines[start:end])
def quoted_after(marker):
    line = next(l for l in lines if marker in l)
    return re.search(r'`"(.*)"`', line.split(marker, 1)[1]).group(1)
assert js.SYSTEM_PROMPT == fenced_after(
    "**[spec choice, verbatim text written from the approved dimension definitions"), "SYSTEM_PROMPT != spec 4.5"
assert js.TOOL_DESCRIPTION == quoted_after("`TOOL_DESCRIPTION` **[spec choice, verbatim]**"), "TOOL_DESCRIPTION != spec 4.1"
assert js.RETRY_USER_MESSAGE == quoted_after("`RETRY_USER_MESSAGE` **[spec choice, verbatim]**"), "RETRY_USER_MESSAGE != spec 4.6"
assert js.FINAL_USER_TEXT_SINGLE == quoted_after("`FINAL_USER_TEXT_SINGLE` **[spec choice, verbatim]**"), "FINAL_USER_TEXT_SINGLE != spec 3.6"
assert js.FINAL_USER_TEXT_MULTI_TEMPLATE == quoted_after(
    "`FINAL_USER_TEXT_MULTI_TEMPLATE` **[spec choice, verbatim;"), "FINAL_USER_TEXT_MULTI_TEMPLATE != spec 3.6"
assert js.FINAL_USER_TEXT_MULTI_TEMPLATE.count("%d") == 1 and "%" not in js.FINAL_USER_TEXT_SINGLE
assert not js.SYSTEM_PROMPT.endswith("\n")
print("PASS prompt texts match the spec verbatim")
EOF
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_stills.py -q
```
Expected: `4 failed, 11 passed, 1 warning`. T6, T7, T7b, and T7c fail with `AttributeError: module 'judge_stills' has no attribute 'encode_still'` (or `'build_user_content'`).

Paste and run the Step 1 verbatim-check block. Expected: a traceback ending in `AttributeError: module 'judge_stills' has no attribute 'SYSTEM_PROMPT'`.

- [ ] **Step 3: Write minimal implementation**

Edit 1 uses the Edit tool on `bin/judge-stills` (spec 4.1's `TOOL_DESCRIPTION`).

old_string:
```python
TOOL_NAME = "submit_judgment"
```
new_string:
```python
TOOL_NAME = "submit_judgment"
TOOL_DESCRIPTION = ("Submit your judgment of the stills: 1-10 scores for prompt_fidelity, "
                    "rendering_quality, and composition always, plus visual_continuity when "
                    "you are judging 2 or more stills, and a critique naming specific panels "
                    "by number. You must call this exactly once.")
```

Edit 2 uses the Edit tool on `bin/judge-stills`: spec 4.5's `SYSTEM_PROMPT`, spec 3.6's two final texts, and spec 4.6's `RETRY_USER_MESSAGE`, all verbatim. In `SYSTEM_PROMPT`, each paragraph break is `"\n"` + `"\n"` and each line before a bullet ends in `"\n"`. There is no trailing newline after the last sentence.

old_string:
```python
def validate_judgment_input(tool_input, stills_count):
```
new_string:
```python
SYSTEM_PROMPT = (
    "You are an expert visual director judging the still images generated for a story by "
    "an AI image-and-video generation pipeline. Each still was generated by an image model "
    "from the text of one story panel. The target output goal is the most realistic action "
    "scenes possible.\n"
    "\n"
    "You will receive the panels in panel order. For each panel you get its \"## Panel N\" "
    "header and whichever of its Image:, Motion:, and Narration: text it has, immediately "
    "followed by the still generated for that panel. Panels that have no generated still "
    "are not included. The final message tells you exactly how many stills you are "
    "judging.\n"
    "\n"
    "Score the stills on these dimensions, each an integer from 1 (worst) to 10 (best):\n"
    "- prompt_fidelity: whether each still actually depicts what that panel's Image: and "
    "Motion: text describes.\n"
    "- visual_continuity: whether character appearance, setting, lighting, and style "
    "actually stay consistent across the stills as rendered. Judge the rendered images "
    "themselves, not whether the text descriptions are consistent with each other.\n"
    "- rendering_quality: rendering artifacts, anatomical errors, loss of detail, a "
    "flattened or overly stylized look where photorealism was intended, and general image "
    "quality.\n"
    "- composition: whether each still's shot type and framing match what the panel text "
    "specifies, and whether the still is well composed.\n"
    "\n"
    "If you are judging fewer than 2 stills, do not include visual_continuity in your "
    "submit_judgment call at all: with a single still there is nothing to compare it "
    "against. If you are judging 2 or more stills, you must include visual_continuity, "
    "scored normally like the other three dimensions.\n"
    "\n"
    "Then write a critique that names specific panels by number (for example, \"Panel 3\") "
    "when identifying strengths and problems.\n"
    "\n"
    "You must deliver your judgment by calling the submit_judgment tool exactly once. Do not "
    "put the judgment in a plain text reply; a response without a submit_judgment call is a "
    "failure."
)

# Final text block of the user message; it states the stills count so the judge knows
# whether visual_continuity applies (spec 3.6, G1).
FINAL_USER_TEXT_SINGLE = ("You are judging 1 still above against its panel text. There is "
                          "only one still, so there is nothing to compare for "
                          "visual_continuity: omit it from your scores object entirely and "
                          "call submit_judgment with prompt_fidelity, rendering_quality, and "
                          "composition only.")
FINAL_USER_TEXT_MULTI_TEMPLATE = ("You are judging all %d stills above against their panel "
                                  "text. Score all four dimensions, including "
                                  "visual_continuity, and call submit_judgment.")

RETRY_USER_MESSAGE = ("You did not call the submit_judgment tool. Call submit_judgment now "
                      "with your scores and critique. Do not reply with plain text.")


def validate_judgment_input(tool_input, stills_count):
```

Edit 3 appends this at the end of `bin/judge-stills`, after `format_panel_text`'s body, with exactly two blank lines before the first `def`:

```python


def encode_still(path):
    """The file's raw bytes, standard base64, as ASCII text. No decoding, resizing,
    recompression, or magic-byte check (spec 3.5, 3.7)."""
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("ascii")


def build_user_content(entries):
    """The single user turn's content blocks (spec 3.6). entries is [(panel_text,
    image_b64)] in still order: each panel's text block, then its image block, then one
    final text block that states the stills count. Always 2 * len(entries) + 1 blocks.
    Pure."""
    content = []
    for panel_text, image_b64 in entries:
        content.append({"type": "text", "text": panel_text})
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": MEDIA_TYPE,
                                   "data": image_b64}})
    count = len(entries)
    if count >= 2:
        final_text = FINAL_USER_TEXT_MULTI_TEMPLATE % count
    else:
        final_text = FINAL_USER_TEXT_SINGLE
    content.append({"type": "text", "text": final_text})
    return content
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_stills.py -q
```
Expected: `15 passed, 1 warning`.

Paste and run the Step 1 verbatim-check block. Expected: `PASS prompt texts match the spec verbatim`.

Mutation checks (spec 7.4: image block before text, `MEDIA_TYPE` jpeg, always-multi, always-single, at the unit level; Task 5 re-runs them against T10/T10b). This script restores the file itself:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile
PATH = "bin/judge-stills"
TEXT_THEN_IMAGE = '''        content.append({"type": "text", "text": panel_text})
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": MEDIA_TYPE,
                                   "data": image_b64}})
'''
IMAGE_THEN_TEXT = '''        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": MEDIA_TYPE,
                                   "data": image_b64}})
        content.append({"type": "text", "text": panel_text})
'''
MUTATIONS = [
    ("image block before its panel text block", TEXT_THEN_IMAGE, IMAGE_THEN_TEXT, 1,
     ["test_t7_build_user_content_two_stills"]),
    ("MEDIA_TYPE image/jpeg", 'MEDIA_TYPE = "image/png"', 'MEDIA_TYPE = "image/jpeg"', 1,
     ["test_t7_build_user_content_two_stills"]),
    ("always FINAL_USER_TEXT_MULTI_TEMPLATE", "    if count >= 2:\n", "    if True:\n", 1,
     ["test_t7b_build_user_content_one_still", "test_t7c_build_user_content_zero_entries"]),
    ("always FINAL_USER_TEXT_SINGLE", "    if count >= 2:\n", "    if False:\n", 1,
     ["test_t7_build_user_content_two_stills"]),
]
def run(name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="judge-stills-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "tests/test_judge_stills.py::" + name],
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
print("restored bin/judge-stills")
EOF
```
Expected: five `CAUGHT` lines (always-multi is checked against both T7b and T7c), then `restored bin/judge-stills`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
git diff --cached --name-only            # expect: no output
git add -- bin/judge-stills tests/test_judge_stills.py
git diff --cached --name-only            # expect exactly the two paths below
# qwen-agent-workspace/bin/judge-stills
# qwen-agent-workspace/tests/test_judge_stills.py
git commit -F - <<'EOF'
judge-stills: add prompt texts, still encoding, and user-message content

SYSTEM_PROMPT, TOOL_DESCRIPTION, FINAL_USER_TEXT_SINGLE,
FINAL_USER_TEXT_MULTI_TEMPLATE and RETRY_USER_MESSAGE transcribed
verbatim from spec 3.6/4.1/4.5/4.6 (checked mechanically against the
spec text). encode_still() base64-encodes raw PNG bytes;
build_user_content() interleaves each panel's text then its image and
ends with a count-stating text block that branches on 1 vs 2+ stills
(G1). Tests T6, T7, T7b, T7c.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
```

---

### Task 4: CLI, path resolution, file preconditions, pairing, and the API-key gate

**Files:**
- Modify: `bin/judge-stills`. Append `build_parser`, `resolve_paths`, `main` (an interim version that ends at client construction), and the `__main__` guard at the end of the file (they become lines 251-311).
- Test: append to `tests/test_judge_stills.py`. This adds the `STORY_ID`, `_make_story`, `_listing`, `_FakeAnthropic`, and `_install_fake` helpers and tests T1a, T1b, T2, T9a, T9b, T9c, T9d, T9e, T11 (they become lines 263-424).

**Interfaces:**
- Consumes: `WS` (Task 1). `find_stills`, `parse_panels`, `format_panel_text` (Task 2). `encode_still`, `build_user_content` (Task 3). Test fixtures `CHAIN_STORY_MD` (Task 2) and `_still_bytes` (Task 3).
- Produces: `build_parser() -> argparse.ArgumentParser`, `resolve_paths(story_id) -> (story_dir, images_dir, story_md_path)`, and `main(argv=None) -> int`. In this task, `main` implements spec 1.2 steps 1-10 and then raises `NotImplementedError("judging call is added by plan Task 5")`. No test reaches that line, because every Task 4 test returns at step 3, 4, 5, 7, or 9. `main`'s locals `story_dir`, `stills`, `panels`, and `user_content` are consumed by Task 5. Test helpers produced: `STORY_ID = "stills-test"`, `_make_story(tmp_path, monkeypatch, story_md=CHAIN_STORY_MD, stills=(1, 3), story_id=STORY_ID, with_images_dir=True) -> pathlib.Path` (it also patches `judge_stills.WS`), `_listing(directory) -> list[str]`, `_FakeAnthropic` (attributes `.constructions: list[(args, kwargs)]`, `.calls: list[dict]`, `.messages.create(**kwargs)`), and `_install_fake(monkeypatch, scripted) -> _FakeAnthropic`. Tasks 5-6 use all of them.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_judge_stills.py`:

```python


# --- shared fixtures for main() tests -------------------------------------------------

STORY_ID = "stills-test"


def _make_story(tmp_path, monkeypatch, story_md=CHAIN_STORY_MD, stills=(1, 3),
                story_id=STORY_ID, with_images_dir=True):
    """Build tmp_path/generated/stories/<story_id>/ and point judge_stills.WS at tmp_path.
    story_md=None skips story.md; with_images_dir=False skips images/. Each index in
    stills becomes images/panel_%02d.png holding _still_bytes(index). Returns the story
    directory as a pathlib.Path."""
    monkeypatch.setattr(judge_stills, "WS", str(tmp_path))
    story_dir = tmp_path / "generated" / "stories" / story_id
    story_dir.mkdir(parents=True)
    if story_md is not None:
        (story_dir / "story.md").write_text(story_md, encoding="utf-8")
    if with_images_dir:
        images_dir = story_dir / "images"
        images_dir.mkdir()
        for k in stills:
            (images_dir / ("panel_%02d.png" % k)).write_bytes(_still_bytes(k))
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
    monkeypatch.setattr(judge_stills.anthropic, "Anthropic", fake)
    return fake


# --- T1-T2, T9, T11: arguments, paths, preconditions, key gate (spec 2, 4.2, 6) ------

def test_t1a_no_args_exit_2():
    with pytest.raises(SystemExit) as exc:
        judge_stills.main([])
    assert exc.value.code == 2


def test_t1b_story_md_flag_rejected():
    with pytest.raises(SystemExit) as exc:
        judge_stills.main(["--story-md", "x"])
    assert exc.value.code == 2


def test_t2_resolve_paths(monkeypatch, tmp_path):
    assert judge_stills.WS == WS
    base = os.path.join(WS, "generated", "stories", "abc")
    assert judge_stills.resolve_paths("abc") == (
        base, os.path.join(base, "images"), os.path.join(base, "story.md"))
    # WS is read at call time, not import time (spec 2.2).
    monkeypatch.setattr(judge_stills, "WS", str(tmp_path))
    assert judge_stills.resolve_paths("abc")[0] == os.path.join(
        str(tmp_path), "generated", "stories", "abc")


def test_t9a_missing_images_dir(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, with_images_dir=False)
    before = _listing(story_dir)
    assert judge_stills.main(["--story-id", STORY_ID]) == 2
    out, err = capsys.readouterr()
    assert err == "Error: stills directory not found: %s\n" % (story_dir / "images")
    assert out == ""
    assert _listing(story_dir) == before


def test_t9b_no_matching_stills(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, stills=())
    (story_dir / "images" / "panel_1.png").write_bytes(_still_bytes(1))
    (story_dir / "images" / "images.json").write_text("{}", encoding="utf-8")
    before = _listing(story_dir)
    assert judge_stills.main(["--story-id", STORY_ID]) == 2
    out, err = capsys.readouterr()
    assert err == "Error: no panel_NN.png stills found in %s\n" % (story_dir / "images")
    assert out == ""
    assert _listing(story_dir) == before


def test_t9c_missing_story_md(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, story_md=None, stills=(1,))
    before = _listing(story_dir)
    assert judge_stills.main(["--story-id", STORY_ID]) == 2
    out, err = capsys.readouterr()
    assert err == "Error: story.md not found: %s\n" % (story_dir / "story.md")
    assert out == ""
    assert _listing(story_dir) == before


def test_t9d_nonexistent_story_checks_images_first(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(judge_stills, "WS", str(tmp_path))
    story_id = "judge-stills-test-nonexistent-%s" % uuid.uuid4().hex
    assert judge_stills.main(["--story-id", story_id]) == 2
    out, err = capsys.readouterr()
    # The images/ check runs before the story.md check (spec 1.2 steps 3-5).
    assert err.startswith("Error: stills directory not found:")
    assert out == ""
    assert not (tmp_path / "generated").exists()


def test_t9e_still_without_panel_section(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, stills=(1, 4))
    before = _listing(story_dir)
    assert judge_stills.main(["--story-id", STORY_ID]) == 2
    out, err = capsys.readouterr()
    assert err == ("Error: %s has no matching panel section in story.md (story.md has 3 "
                   "panel sections); the stills may be stale relative to story.md.\n"
                   % (story_dir / "images" / "panel_04.png"))
    assert out == ""
    assert _listing(story_dir) == before


def test_t11_key_unset_never_constructs_client(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch)
    before = _listing(story_dir)
    fake = _install_fake(monkeypatch, [])
    expected_err = ("Error: ANTHROPIC_API_KEY is not set; export it in your environment to "
                    "run judge-stills.\n")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert judge_stills.main(["--story-id", STORY_ID]) == 1
    assert fake.constructions == []
    assert fake.calls == []
    out, err = capsys.readouterr()
    assert err == expected_err
    assert out == ""
    # An empty value counts as unset (spec 4.2).
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert judge_stills.main(["--story-id", STORY_ID]) == 1
    assert fake.constructions == []
    assert fake.calls == []
    out, err = capsys.readouterr()
    assert err == expected_err
    assert out == ""
    assert _listing(story_dir) == before
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_stills.py -q
```
Expected: `9 failed, 15 passed, 1 warning`. Each of the 9 new tests fails with `AttributeError: module 'judge_stills' has no attribute 'main'` (or `'resolve_paths'` for T2).

- [ ] **Step 3: Write minimal implementation**

Append to the end of `bin/judge-stills`, after `build_user_content`'s body, with exactly two blank lines before the first `def`:

```python


def build_parser():
    parser = argparse.ArgumentParser(
        prog="judge-stills",
        description="Judge a story's generated panel stills with Claude against the story text.")
    parser.add_argument("--story-id", dest="story_id", metavar="ID", required=True,
                        help="judge generated/stories/ID/images/panel_NN.png against "
                             "generated/stories/ID/story.md")
    return parser


def resolve_paths(story_id):
    """(story_dir, images_dir, story_md_path) for --story-id (spec 2.2). Reads WS at call
    time, not import time."""
    story_dir = os.path.join(WS, "generated", "stories", story_id)
    images_dir = os.path.join(story_dir, "images")
    story_md_path = os.path.join(story_dir, "story.md")
    return story_dir, images_dir, story_md_path


def main(argv=None):
    args = build_parser().parse_args(argv)
    story_dir, images_dir, story_md_path = resolve_paths(args.story_id)

    # Every local file precondition runs before the env check (spec 1.2, 2.3).
    if not os.path.isdir(images_dir):
        print("Error: stills directory not found: %s" % images_dir, file=sys.stderr)
        return 2
    stills = find_stills(images_dir)
    if not stills:
        print("Error: no panel_NN.png stills found in %s" % images_dir, file=sys.stderr)
        return 2
    if not os.path.isfile(story_md_path):
        print("Error: story.md not found: %s" % story_md_path, file=sys.stderr)
        return 2
    with open(story_md_path, encoding="utf-8") as f:
        panels = parse_panels(f.read())
    # Still N pairs with the N-th panel section by position, exactly how
    # bin/ltx-story-images rendered it; a still with no section there is stale (spec 3.3).
    for index, path in stills:
        if not 1 <= index <= len(panels):
            print("Error: %s has no matching panel section in story.md (story.md has %d "
                  "panel sections); the stills may be stale relative to story.md."
                  % (path, len(panels)), file=sys.stderr)
            return 2
    entries = [(format_panel_text(panels[index - 1]), encode_still(path))
               for index, path in stills]
    user_content = build_user_content(entries)

    # Checked before the client exists; the key is never read into a variable -- the
    # SDK picks it up from the environment itself (spec 4.2).
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set; export it in your environment to run "
              "judge-stills.", file=sys.stderr)
        return 1
    client = anthropic.Anthropic()
    raise NotImplementedError("judging call is added by plan Task 5")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_stills.py -q
```
Expected: `24 passed, 1 warning`.

Real-shebang smoke test. It proves the `#!/usr/bin/env python3` interpreter imports `anthropic` and `jsonschema`, and it writes nothing:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && bin/judge-stills --help >/dev/null; echo "help rc=$?"; bin/judge-stills --story-id judge-stills-smoke-nonexistent; echo "missing rc=$?"; bin/judge-stills; echo "noargs rc=$?"
```
Expected: `help rc=0`. Then `Error: stills directory not found: /Users/reubenpatterson/local_model_harness/qwen-agent-workspace/generated/stories/judge-stills-smoke-nonexistent/images` and `missing rc=2`. Then `usage: judge-stills [-h] --story-id ID`, `judge-stills: error: the following arguments are required: --story-id`, and `noargs rc=2`.

Mutation checks (spec 7.4: key check after construction, pairing check removed, images-dir check moved after the `story.md` check). This script restores the file itself:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile
PATH = "bin/judge-stills"
KEY_BLOCK = '''    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set; export it in your environment to run "
              "judge-stills.", file=sys.stderr)
        return 1
'''
CLIENT = "    client = anthropic.Anthropic()\n"
IMAGES_CHECKS = '''    if not os.path.isdir(images_dir):
        print("Error: stills directory not found: %s" % images_dir, file=sys.stderr)
        return 2
    stills = find_stills(images_dir)
    if not stills:
        print("Error: no panel_NN.png stills found in %s" % images_dir, file=sys.stderr)
        return 2
'''
STORY_MD_CHECK = '''    if not os.path.isfile(story_md_path):
        print("Error: story.md not found: %s" % story_md_path, file=sys.stderr)
        return 2
'''
MUTATIONS = [
    ("API-key check moved after client construction", KEY_BLOCK + CLIENT, CLIENT + KEY_BLOCK, 1,
     ["test_t11_key_unset_never_constructs_client"]),
    ("pairing check (E5) removed", "        if not 1 <= index <= len(panels):\n", "        if False:\n", 1,
     ["test_t9e_still_without_panel_section"]),
    ("images-dir check moved after the story.md check", IMAGES_CHECKS + STORY_MD_CHECK, STORY_MD_CHECK + IMAGES_CHECKS, 1,
     ["test_t9d_nonexistent_story_checks_images_first"]),
]
def run(name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="judge-stills-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "tests/test_judge_stills.py::" + name],
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
print("restored bin/judge-stills")
EOF
```
Expected: three `CAUGHT` lines, then `restored bin/judge-stills`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
git diff --cached --name-only            # expect: no output
git add -- bin/judge-stills tests/test_judge_stills.py
git diff --cached --name-only            # expect exactly the two paths below
# qwen-agent-workspace/bin/judge-stills
# qwen-agent-workspace/tests/test_judge_stills.py
git commit -F - <<'EOF'
judge-stills: add CLI, preconditions, still-panel pairing, and key gate

--story-id (required, the only flag) and resolve_paths() per spec 2.2.
Exit 2 for a missing images/ dir, no panel_NN.png stills, a missing
story.md, or a still with no panel section at its position (E2-E5, in
that order); exit 1 for an unset or empty ANTHROPIC_API_KEY before any
client is constructed. main() builds the interleaved user content and
stops at client construction; the judging call lands next. Tests T1a,
T1b, T2, T9a-T9e, T11.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
```

---

### Task 5: Judging call, validation-failure path, output file, and stdout

**Files:**
- Modify: `bin/judge-stills`. Insert `find_tool_use`, `format_score_line`, `_create_message`, and `_write_raw` immediately before `def main(argv=None):` (they become lines 271-315). Replace main's two interim lines (`client = anthropic.Anthropic()` and `raise NotImplementedError(...)`) with the happy path (main then ends at line 401; the `__main__` guard sits at lines 404-405).
- Test: append to `tests/test_judge_stills.py`. This adds the response builders, `ONE_PANEL_STORY_MD`, `_expected_stdout`, and tests T10, T10b, T14, T14b (they become lines 426-616).

**Interfaces:**
- Consumes: `MODEL`, `EFFORT`, `MAX_TOKENS`, `TOOL_NAME`, `SCORE_KEYS`, `SUBMIT_JUDGMENT_SCHEMA`, and `validate_judgment_input(tool_input, stills_count)` (Task 1). `SYSTEM_PROMPT` and `TOOL_DESCRIPTION` (Task 3). `main`'s locals `args`, `story_dir`, `stills`, and `user_content` (Task 4). Test helpers `_make_story`, `_install_fake`, `STORY_ID`, `CHAIN_PANELS`, `_still_bytes`, `VALID_INPUT`, `_without_vc`, `SENTINEL_KEY`, and `SCORE_NAMES`.
- Produces: `find_tool_use(response) -> ToolUseBlock | None`, `format_score_line(name, value) -> str`, `_create_message(client, messages) -> anthropic.types.Message` (the fixed spec 4.1 request), and `_write_raw(story_dir, responses) -> str` (path of `stills_judgment.raw.json`). `main` now makes one call, validates with `validate_judgment_input(block.input, len(stills))`, writes `stills_judgment.json`, and prints stdout. A response with no tool call is not handled yet: `block.input` raises `AttributeError` until Task 6 adds the retry. Test helpers produced: `THINKING_BLOCK`, `ONE_PANEL_STORY_MD`, `_usage(input_tokens, output_tokens, thinking_tokens)`, `_message(content, usage, stop_reason)`, `_tool_response(tool_input, usage)`, `_text_response(text, usage)`, and `_expected_stdout(scores, critique)`. Task 6 uses them.

T14b sits in this task, not Task 6, because the code it exercises (the `validate_judgment_input(block.input, len(stills))` call and the E9 path) lands here. In Task 6 it would pass before any Task 6 code was written, so it could never go red.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_judge_stills.py`:

```python


# --- SDK response builders: real anthropic.types.Message objects (spec 7.1) ----------

THINKING_BLOCK = {"type": "thinking", "thinking": "Comparing the stills to the panel text.",
                  "signature": "sig-abc123"}

ONE_PANEL_STORY_MD = (
    "## Panel 1 — Only\n"
    "Image: A green frog on a lily pad at dawn.\n"
    "Motion: The frog blinks once.\n"
    "Narration: Morning comes.\n"
)


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


def _expected_stdout(scores, critique):
    return ("Scores:\n"
            + "".join(judge_stills.format_score_line(k, scores[k]) + "\n"
                      for k in SCORE_NAMES)
            + "\n--- Critique ---\n" + critique + "\n")


# --- T10, T10b, T14, T14b: judging call, outputs, validation failures (spec 4-6) -----

def test_t10_successful_run_two_stills(tmp_path, monkeypatch, capsys):
    # CHAIN_STORY_MD has 3 panels; panel 2 has no still.
    story_dir = _make_story(tmp_path, monkeypatch, stills=(1, 3))
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    fake = _install_fake(monkeypatch, [
        _tool_response(copy.deepcopy(VALID_INPUT), _usage(1200, 3400, 2100))])

    assert judge_stills.main(["--story-id", STORY_ID]) == 0

    with open(story_dir / "stills_judgment.json", encoding="utf-8") as f:
        raw_text = f.read()
    judgment = json.loads(raw_text)
    assert list(judgment) == ["story_id", "model", "effort", "timestamp", "usage",
                              "scores", "critique"]
    assert judgment["story_id"] == STORY_ID
    assert judgment["model"] == "claude-opus-5-5"
    assert judgment["effort"] == "high"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", judgment["timestamp"])
    assert judgment["usage"] == {"input_tokens": 1200, "output_tokens": 3400,
                                 "thinking_tokens": 2100}
    assert list(judgment["scores"]) == list(judge_stills.SCORE_KEYS) == list(SCORE_NAMES)
    assert judgment["scores"] == VALID_INPUT["scores"]
    assert judgment["critique"] == VALID_INPUT["critique"]
    assert "—" in raw_text            # ensure_ascii=False
    assert raw_text.endswith("}\n")        # trailing newline after json.dump
    for name in ("stills_judgment.raw.json", "judgment.json", "judgment.raw.json"):
        assert not (story_dir / name).exists(), name

    out, err = capsys.readouterr()
    score_lines = "".join("  %-20s  %d\n" % (k, VALID_INPUT["scores"][k]) for k in SCORE_NAMES)
    assert "  prompt_fidelity       7\n" in score_lines   # pins the %-20s layout itself
    assert out == _expected_stdout(VALID_INPUT["scores"], VALID_INPUT["critique"])
    assert out == "Scores:\n" + score_lines + "\n--- Critique ---\n" + VALID_INPUT["critique"] + "\n"
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
    assert kwargs["system"] == judge_stills.SYSTEM_PROMPT
    assert [tool["name"] for tool in kwargs["tools"]] == ["submit_judgment"]
    assert kwargs["tools"][0]["input_schema"] == judge_stills.SUBMIT_JUDGMENT_SCHEMA
    assert kwargs["tools"][0]["description"] == judge_stills.TOOL_DESCRIPTION
    messages = kwargs["messages"]
    assert len(messages) == 1 and messages[0]["role"] == "user"
    content = messages[0]["content"]
    assert [block["type"] for block in content] == ["text", "image", "text", "image", "text"]
    assert content[0]["text"] == judge_stills.format_panel_text(CHAIN_PANELS[0])
    assert base64.b64decode(content[1]["source"]["data"]) == _still_bytes(1)
    assert content[2]["text"] == judge_stills.format_panel_text(CHAIN_PANELS[2])
    assert base64.b64decode(content[3]["source"]["data"]) == _still_bytes(3)
    assert content[4]["text"] == judge_stills.FINAL_USER_TEXT_MULTI_TEMPLATE % 2
    for block in (content[1], content[3]):
        assert block["source"]["type"] == "base64"
        assert block["source"]["media_type"] == "image/png"


def test_t10b_successful_run_one_still(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, story_md=ONE_PANEL_STORY_MD, stills=(1,))
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    # The judge followed the 1-still instruction: visual_continuity is absent entirely.
    tool_input = _without_vc(VALID_INPUT)
    fake = _install_fake(monkeypatch, [_tool_response(tool_input, _usage(900, 2500, 1500))])

    assert judge_stills.main(["--story-id", STORY_ID]) == 0

    with open(story_dir / "stills_judgment.json", encoding="utf-8") as f:
        raw_text = f.read()
    judgment = json.loads(raw_text)
    assert judgment["scores"] == {"prompt_fidelity": 7, "visual_continuity": None,
                                  "rendering_quality": 8, "composition": 5}
    assert list(judgment["scores"]) == list(SCORE_NAMES)
    assert '"visual_continuity": null' in raw_text
    assert not (story_dir / "stills_judgment.raw.json").exists()

    out, err = capsys.readouterr()
    assert judge_stills.format_score_line("visual_continuity", None) == (
        "  visual_continuity     n/a (only 1 still)")
    assert out == ("Scores:\n"
                   "  prompt_fidelity       7\n"
                   "  visual_continuity     n/a (only 1 still)\n"
                   "  rendering_quality     8\n"
                   "  composition           5\n"
                   "\n--- Critique ---\n" + VALID_INPUT["critique"] + "\n")
    assert out == _expected_stdout(judgment["scores"], VALID_INPUT["critique"])
    assert err == ""

    assert len(fake.calls) == 1                       # a valid tool_use: no retry
    content = fake.calls[0]["messages"][0]["content"]
    assert [block["type"] for block in content] == ["text", "image", "text"]
    assert content[0]["text"] == ("## Panel 1 — Only\n"
                                  "Image: A green frog on a lily pad at dawn.\n"
                                  "Motion: The frog blinks once.\n"
                                  "Narration: Morning comes.")
    assert base64.b64decode(content[1]["source"]["data"]) == _still_bytes(1)
    assert content[2]["text"] == judge_stills.FINAL_USER_TEXT_SINGLE


def test_t14_schema_invalid_tool_input(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, stills=(1, 3))
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    bad = copy.deepcopy(VALID_INPUT)
    bad["scores"]["composition"] = 11
    fake = _install_fake(monkeypatch, [_tool_response(bad, _usage(10, 20, 5))])

    assert judge_stills.main(["--story-id", STORY_ID]) == 1

    assert len(fake.calls) == 1            # no retry on a validation failure
    with open(story_dir / "stills_judgment.raw.json", encoding="utf-8") as f:
        raw = json.load(f)
    assert len(raw["responses"]) == 1
    assert raw["responses"][0]["content"][1]["input"]["scores"]["composition"] == 11
    assert not (story_dir / "stills_judgment.json").exists()
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("Error: submit_judgment input failed schema validation: ")


def test_t14b_two_stills_missing_visual_continuity(tmp_path, monkeypatch, capsys):
    # A submit_judgment block WAS found (unlike T13); its input omits visual_continuity
    # although 2 stills were judged. Caught by the post-schema check (spec 4.4, E9).
    story_dir = _make_story(tmp_path, monkeypatch, stills=(1, 3))
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    fake = _install_fake(monkeypatch, [
        _tool_response(_without_vc(VALID_INPUT), _usage(10, 20, 5))])

    assert judge_stills.main(["--story-id", STORY_ID]) == 1

    assert len(fake.calls) == 1            # validation failure: no retry
    with open(story_dir / "stills_judgment.raw.json", encoding="utf-8") as f:
        raw = json.load(f)
    assert len(raw["responses"]) == 1
    assert not (story_dir / "stills_judgment.json").exists()
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ("Error: submit_judgment input failed schema validation: "
                   "visual_continuity is required when judging 2 or more stills\n")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_stills.py -q
```
Expected: `4 failed, 24 passed, 1 warning`. T10, T10b, T14, and T14b each fail with `NotImplementedError: judging call is added by plan Task 5`.

- [ ] **Step 3: Write minimal implementation**

Edit 1 uses the Edit tool on `bin/judge-stills`.

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


def format_score_line(name, value):
    """One stdout score line (spec 5.3). None is reached only for visual_continuity when
    exactly 1 still was judged, so the "1 still" wording is always accurate."""
    if value is None:
        return "  %-20s  n/a (only 1 still)" % name
    return "  %-20s  %d" % (name, value)


def _create_message(client, messages):
    """One non-streaming judging call with the fixed spec 4.1 parameters. No temperature,
    top_k, or top_p, and no budget_tokens thinking shape (the live API rejects it)."""
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
        # Extended thinking cannot force a specific tool; SYSTEM_PROMPT requires the call.
        tool_choice={"type": "auto"},
        messages=messages,
    )


def _write_raw(story_dir, responses):
    """Dump every API response received this run to stills_judgment.raw.json; return its
    path. Response bodies only: neither the key nor the request's images (spec 5.2)."""
    path = os.path.join(story_dir, "stills_judgment.raw.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"responses": [r.model_dump(mode="json") for r in responses]}, f,
                  indent=2, ensure_ascii=False)
    return path


def main(argv=None):
```

Edit 2 uses the Edit tool on `bin/judge-stills`.

old_string:
```python
    client = anthropic.Anthropic()
    raise NotImplementedError("judging call is added by plan Task 5")
```
new_string:
```python
    client = anthropic.Anthropic()

    responses = [_create_message(client, [{"role": "user", "content": user_content}])]
    block = find_tool_use(responses[0])
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        validate_judgment_input(block.input, len(stills))
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
        "story_id": args.story_id,
        "model": MODEL,
        "effort": EFFORT,
        "timestamp": timestamp,
        "usage": {
            "input_tokens": sum(r.usage.input_tokens for r in responses),
            "output_tokens": sum(r.usage.output_tokens for r in responses),
            # null, never a fabricated 0, when no response reports it (spec 5.1)
            "thinking_tokens": sum(thinking_counts) if thinking_counts else None,
        },
        "scores": {
            "prompt_fidelity": tool_input["scores"]["prompt_fidelity"],
            # Absent (-> JSON null) only in the 1-still case; validation already rejected
            # a 2+-stills judgment that omits it (spec 4.4, 5.1).
            "visual_continuity": tool_input["scores"].get("visual_continuity"),
            "rendering_quality": tool_input["scores"]["rendering_quality"],
            "composition": tool_input["scores"]["composition"],
        },
        "critique": tool_input["critique"],
    }
    with open(os.path.join(story_dir, "stills_judgment.json"), "w", encoding="utf-8") as f:
        json.dump(judgment, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print("Scores:")
    for name in SCORE_KEYS:
        print(format_score_line(name, judgment["scores"][name]))
    print()
    print("--- Critique ---")
    print(judgment["critique"])
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_stills.py -q
```
Expected: `28 passed, 1 warning`.

Mutation checks (spec 7.4). These cover the rows owned by this task: every panel sent, output to `judgment.json`, no `None` branch in `format_score_line`, `[]` instead of `.get()`. They also re-run Tasks 1 and 3's rows against the end-to-end tests T10, T10b, T14, and T14b. This script restores the file itself:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile
PATH = "bin/judge-stills"
TEXT_THEN_IMAGE = '''        content.append({"type": "text", "text": panel_text})
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": MEDIA_TYPE,
                                   "data": image_b64}})
'''
IMAGE_THEN_TEXT = '''        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": MEDIA_TYPE,
                                   "data": image_b64}})
        content.append({"type": "text", "text": panel_text})
'''
NONE_BRANCH = '''    if value is None:
        return "  %-20s  n/a (only 1 still)" % name
'''
MUTATIONS = [
    ("image block before its panel text block", TEXT_THEN_IMAGE, IMAGE_THEN_TEXT, 1,
     ["test_t10_successful_run_two_stills"]),
    ("MEDIA_TYPE image/jpeg", 'MEDIA_TYPE = "image/png"', 'MEDIA_TYPE = "image/jpeg"', 1,
     ["test_t10_successful_run_two_stills"]),
    ("every story panel sent", "    user_content = build_user_content(entries)\n", "    user_content = build_user_content(entries)\n    user_content[-1:-1] = [{\"type\": \"text\", \"text\": format_panel_text(p)} for i, p in enumerate(panels, 1) if i not in dict(stills)]\n", 1,
     ["test_t10_successful_run_two_stills"]),
    ("output written to judgment.json", 'os.path.join(story_dir, "stills_judgment.json")', 'os.path.join(story_dir, "judgment.json")', 1,
     ["test_t10_successful_run_two_stills"]),
    ("score maximum 10 -> 11", '"maximum": 10', '"maximum": 11', 4,
     ["test_t14_schema_invalid_tool_input"]),
    ("visual_continuity restored to scores.required", '"required": ["prompt_fidelity", "rendering_quality", "composition"]', '"required": ["prompt_fidelity", "visual_continuity", "rendering_quality", "composition"]', 1,
     ["test_t10b_successful_run_one_still"]),
    ("2+-stills visual_continuity check removed", '    if stills_count >= 2 and "visual_continuity" not in tool_input["scores"]:\n', "    if False:\n", 1,
     ["test_t14b_two_stills_missing_visual_continuity"]),
    ("always FINAL_USER_TEXT_MULTI_TEMPLATE", "    if count >= 2:\n", "    if True:\n", 1,
     ["test_t10b_successful_run_one_still"]),
    ("always FINAL_USER_TEXT_SINGLE", "    if count >= 2:\n", "    if False:\n", 1,
     ["test_t10_successful_run_two_stills"]),
    ("format_score_line has no None branch", NONE_BRANCH, "", 1,
     ["test_t10b_successful_run_one_still"]),
    ("visual_continuity copied with [] instead of .get()", 'tool_input["scores"].get("visual_continuity")', 'tool_input["scores"]["visual_continuity"]', 1,
     ["test_t10b_successful_run_one_still"]),
]
def run(name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="judge-stills-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "tests/test_judge_stills.py::" + name],
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
print("restored bin/judge-stills")
EOF
```
Expected: eleven `CAUGHT` lines, then `restored bin/judge-stills`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
git diff --cached --name-only            # expect: no output
git add -- bin/judge-stills tests/test_judge_stills.py
git diff --cached --name-only            # expect exactly the two paths below
# qwen-agent-workspace/bin/judge-stills
# qwen-agent-workspace/tests/test_judge_stills.py
git commit -F - <<'EOF'
judge-stills: add judging call, stills_judgment.json, and stdout

_create_message() sends spec 4.1's fixed request (adaptive thinking,
effort high, one tool, tool_choice auto). The tool input is validated
with validate_judgment_input(block.input, len(stills)); a failure (incl.
2+ stills without visual_continuity) dumps stills_judgment.raw.json and
exits 1 with no retry. Success writes stills_judgment.json (seven keys;
visual_continuity null for 1 still) and prints the scores, using
"n/a (only 1 still)" for a null score, then the critique. Tests T10,
T10b, T14, T14b.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
```

---

### Task 6: One retry, double failure, API errors, and the key-leak guard

**Files:**
- Modify: `bin/judge-stills`. Replace the two lines in `main` that make the single call (`responses = [...]` and `block = find_tool_use(responses[0])`) with the try/retry/except block and the double-failure branch (they become lines 354-378; the file ends at line 428).
- Test: append to `tests/test_judge_stills.py`. This adds tests T12, T13, T15, T16 (they become lines 618-731).

**Interfaces:**
- Consumes: `find_tool_use`, `_create_message`, `_write_raw` (Task 5). `RETRY_USER_MESSAGE` (Task 3). `main`'s locals `client`, `user_content`, and `story_dir`. Test helpers `_make_story`, `_listing`, `_install_fake`, `_tool_response`, `_text_response`, `_usage`, `VALID_INPUT`, `SENTINEL_KEY`, and `STORY_ID`.
- Produces: the final `main` (spec 1.2 steps 1-14 and 4.6). There are no new symbols.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_judge_stills.py`:

```python


# --- T12, T13, T15, T16: retry, double failure, API errors, key leakage (spec 4.6, 6) -

def test_t12_retry_after_missing_tool_call(tmp_path, monkeypatch):
    story_dir = _make_story(tmp_path, monkeypatch, stills=(1, 3))
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    # r1 reports no thinking_tokens; r2 does: the sum covers only the responses that
    # report it (spec 5.1).
    r1 = _text_response("Here is my judgment in prose.", _usage(100, 200, None))
    r2 = _tool_response(copy.deepcopy(VALID_INPUT), _usage(1000, 3000, 2500))
    fake = _install_fake(monkeypatch, [r1, r2])

    assert judge_stills.main(["--story-id", STORY_ID]) == 0

    assert len(fake.calls) == 2
    first, second = fake.calls
    assert len(first["messages"]) == 1     # the retry builds a new list, not an append
    retry_messages = second["messages"]
    assert len(retry_messages) == 3
    assert [m["role"] for m in retry_messages] == ["user", "assistant", "user"]
    assert retry_messages[0] == first["messages"][0]      # same images re-sent
    assert len(retry_messages[0]["content"]) == 5
    assert retry_messages[1]["content"] == r1.content
    assert retry_messages[1]["content"][0].type == "thinking"
    assert retry_messages[1]["content"][0].signature == "sig-abc123"
    assert retry_messages[2]["content"] == judge_stills.RETRY_USER_MESSAGE
    assert ({k: v for k, v in second.items() if k != "messages"}
            == {k: v for k, v in first.items() if k != "messages"})
    with open(story_dir / "stills_judgment.json", encoding="utf-8") as f:
        judgment = json.load(f)
    assert judgment["usage"] == {"input_tokens": 1100, "output_tokens": 3200,
                                 "thinking_tokens": 2500}
    assert judgment["scores"] == VALID_INPUT["scores"]
    assert not (story_dir / "stills_judgment.raw.json").exists()


def test_t13_double_failure_writes_raw_and_no_judgment(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, stills=(1, 3))
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    r1 = _text_response("Prose judgment, attempt one.", _usage(100, 200, 50))
    r2 = _text_response("Prose judgment, attempt two.", _usage(110, 210, 60))
    fake = _install_fake(monkeypatch, [r1, r2])

    assert judge_stills.main(["--story-id", STORY_ID]) == 1

    assert len(fake.calls) == 2
    raw_path = story_dir / "stills_judgment.raw.json"
    with open(raw_path, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["responses"] == [r1.model_dump(mode="json"), r2.model_dump(mode="json")]
    assert not (story_dir / "stills_judgment.json").exists()
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ("Error: Claude did not call submit_judgment after one retry; raw "
                   "responses written to %s\n" % raw_path)


def test_t15_api_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)

    def connection_error():
        return anthropic.APIConnectionError(
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))

    # (a) The first call raises.
    first_dir = _make_story(tmp_path, monkeypatch, story_id="api-first")
    before = _listing(first_dir)
    fake = _install_fake(monkeypatch, [connection_error()])
    assert judge_stills.main(["--story-id", "api-first"]) == 1
    assert len(fake.calls) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("Error: Anthropic API call failed: APIConnectionError: ")
    assert _listing(first_dir) == before

    # (b) r1 has no tool call and the retry raises: E7, and r1 is not dumped.
    retry_dir = _make_story(tmp_path, monkeypatch, story_id="api-retry")
    before = _listing(retry_dir)
    fake = _install_fake(monkeypatch, [
        _text_response("Prose only.", _usage(100, 200, 50)), connection_error()])
    assert judge_stills.main(["--story-id", "api-retry"]) == 1
    assert len(fake.calls) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("Error: Anthropic API call failed: APIConnectionError: ")
    assert _listing(retry_dir) == before


def test_t16_api_key_never_leaks(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)

    # T10 scenario (success). These responses omit output_tokens_details, so this run
    # also pins usage.thinking_tokens == null rather than a fabricated 0 (spec 5.1).
    ok_dir = _make_story(tmp_path, monkeypatch, story_id="leak-ok")
    _install_fake(monkeypatch, [
        _tool_response(copy.deepcopy(VALID_INPUT), _usage(1200, 3400, None))])
    assert judge_stills.main(["--story-id", "leak-ok"]) == 0
    ok_out, ok_err = capsys.readouterr()

    # T13 scenario (double failure).
    fail_dir = _make_story(tmp_path, monkeypatch, story_id="leak-fail")
    _install_fake(monkeypatch, [_text_response("Prose one.", _usage(1, 2, None)),
                                _text_response("Prose two.", _usage(3, 4, None))])
    assert judge_stills.main(["--story-id", "leak-fail"]) == 1
    fail_out, fail_err = capsys.readouterr()

    written = [ok_dir / "stills_judgment.json", fail_dir / "stills_judgment.raw.json"]
    for path in written:
        assert path.is_file(), path
    with open(ok_dir / "stills_judgment.json", encoding="utf-8") as f:
        assert json.load(f)["usage"]["thinking_tokens"] is None
    for text in [ok_out, ok_err, fail_out, fail_err] + [p.read_text(encoding="utf-8")
                                                         for p in written]:
        assert SENTINEL_KEY not in text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_stills.py -q
```
Expected: `4 failed, 28 passed, 1 warning`. T12, T13, and T16 fail with `AttributeError: 'NoneType' object has no attribute 'input'`. T15 fails with an uncaught `anthropic.APIConnectionError`.

- [ ] **Step 3: Write minimal implementation**

Use the Edit tool on `bin/judge-stills`.

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
            # One retry in the same conversation, re-sending every image. r1.content goes
            # back exactly as received: the API requires thinking blocks and signatures
            # unmodified (spec 4.6).
            responses.append(_create_message(client, [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": responses[0].content},
                {"role": "user", "content": RETRY_USER_MESSAGE},
            ]))
            block = find_tool_use(responses[1])
    except anthropic.APIError as e:
        # Covers APIStatusError subclasses, APIConnectionError, and APITimeoutError. A
        # failed retry discards r1 rather than dumping it (spec 4.6, E7).
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
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_stills.py -q
```
Expected: `32 passed, 1 warning`.

Mutation checks (spec 7.4: retry removed, retry without re-sending `user_content`, raw dump skipped). This script restores the file itself:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile
PATH = "bin/judge-stills"
RETRY_BLOCK = '''        if block is None:
            # One retry in the same conversation, re-sending every image. r1.content goes
            # back exactly as received: the API requires thinking blocks and signatures
            # unmodified (spec 4.6).
            responses.append(_create_message(client, [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": responses[0].content},
                {"role": "user", "content": RETRY_USER_MESSAGE},
            ]))
            block = find_tool_use(responses[1])
'''
MUTATIONS = [
    ("retry removed", RETRY_BLOCK, "", 1,
     ["test_t12_retry_after_missing_tool_call"]),
    ("retry does not re-send user_content", '                {"role": "user", "content": user_content},\n', "", 1,
     ["test_t12_retry_after_missing_tool_call"]),
    ("stills_judgment.raw.json write skipped", "        raw_path = _write_raw(story_dir, responses)\n", '        raw_path = os.path.join(story_dir, "stills_judgment.raw.json")\n', 1,
     ["test_t13_double_failure_writes_raw_and_no_judgment"]),
]
def run(name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="judge-stills-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "tests/test_judge_stills.py::" + name],
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
print("restored bin/judge-stills")
EOF
```
Expected: three `CAUGHT` lines, then `restored bin/judge-stills`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
git diff --cached --name-only            # expect: no output
git add -- bin/judge-stills tests/test_judge_stills.py
git diff --cached --name-only            # expect exactly the two paths below
# qwen-agent-workspace/bin/judge-stills
# qwen-agent-workspace/tests/test_judge_stills.py
git commit -F - <<'EOF'
judge-stills: add the single retry, double-failure dump, and API errors

When no submit_judgment block comes back, retry once in the same
conversation, re-sending every image and r1.content unmodified (thinking
signatures included). A second miss writes stills_judgment.raw.json and
exits 1. Any anthropic.APIError on either call exits 1 with one line and
writes nothing. Tests T12, T13, T15, T16 (key never leaks;
thinking_tokens null when unreported).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
```

---

## Final acceptance (main thread, after Task 6; spec Section 7.6)

The orchestrating session runs these, not the task implementer, because implementer-reported counts are not accepted (spec A1). Only the manual M1/M2 runs write files, and only under `generated/stories/`.

### A1: suite count

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_stills.py -v; /usr/bin/grep -c '^def test_' tests/test_judge_stills.py
```
Pass: `32 passed, 1 warning`, one per spec ID in Sections 7.2 and 7.3, and the grep prints `32`.

### A2: all 21 spec 7.4 mutations on the final file (self-restoring)

The "post-validation check removed" row is checked against both T8f and T14b (the spec names T14b; T8f pins it at the unit level).

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile
PATH = "bin/judge-stills"
KEY_BLOCK = '''    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set; export it in your environment to run "
              "judge-stills.", file=sys.stderr)
        return 1
'''
CLIENT = "    client = anthropic.Anthropic()\n"
SECTION_CLOSE = '''        if line.startswith("##"):
            if current is not None:
                sections.append(current)
                current = None
            continue
'''
TEXT_THEN_IMAGE = '''        content.append({"type": "text", "text": panel_text})
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": MEDIA_TYPE,
                                   "data": image_b64}})
'''
IMAGE_THEN_TEXT = '''        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": MEDIA_TYPE,
                                   "data": image_b64}})
        content.append({"type": "text", "text": panel_text})
'''
IMAGES_CHECKS = '''    if not os.path.isdir(images_dir):
        print("Error: stills directory not found: %s" % images_dir, file=sys.stderr)
        return 2
    stills = find_stills(images_dir)
    if not stills:
        print("Error: no panel_NN.png stills found in %s" % images_dir, file=sys.stderr)
        return 2
'''
STORY_MD_CHECK = '''    if not os.path.isfile(story_md_path):
        print("Error: story.md not found: %s" % story_md_path, file=sys.stderr)
        return 2
'''
RETRY_BLOCK = '''        if block is None:
            # One retry in the same conversation, re-sending every image. r1.content goes
            # back exactly as received: the API requires thinking blocks and signatures
            # unmodified (spec 4.6).
            responses.append(_create_message(client, [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": responses[0].content},
                {"role": "user", "content": RETRY_USER_MESSAGE},
            ]))
            block = find_tool_use(responses[1])
'''
NONE_BRANCH = '''    if value is None:
        return "  %-20s  n/a (only 1 still)" % name
'''
MUTATIONS = [
    ("API-key check moved after client construction", KEY_BLOCK + CLIENT, CLIENT + KEY_BLOCK, 1,
     ["test_t11_key_unset_never_constructs_client"]),
    ("find_stills sorts by filename string", "    found.sort(key=lambda item: (item[0], item[1]))\n", "    found.sort(key=lambda item: item[1])\n", 1,
     ["test_t3_find_stills_numeric_sort_and_filter"]),
    ("STILL_NAME_RE accepts one digit", r're.compile(r"panel_(\d{2,})\.png")', r're.compile(r"panel_(\d+)\.png")', 1,
     ["test_t3_find_stills_numeric_sort_and_filter"]),
    ("Style removed from PANEL_LABEL_RE", "Narration|Prompt|Style):", "Narration|Prompt):", 1,
     ["test_t4a_parse_panels_chain_fixture"]),
    ("## section-closing branch removed", SECTION_CLOSE, "", 1,
     ["test_t4a_parse_panels_chain_fixture"]),
    ("image block before its panel text block", TEXT_THEN_IMAGE, IMAGE_THEN_TEXT, 1,
     ["test_t7_build_user_content_two_stills", "test_t10_successful_run_two_stills"]),
    ("MEDIA_TYPE image/jpeg", 'MEDIA_TYPE = "image/png"', 'MEDIA_TYPE = "image/jpeg"', 1,
     ["test_t7_build_user_content_two_stills", "test_t10_successful_run_two_stills"]),
    ("pairing check (E5) removed", "        if not 1 <= index <= len(panels):\n", "        if False:\n", 1,
     ["test_t9e_still_without_panel_section"]),
    ("images-dir check moved after the story.md check", IMAGES_CHECKS + STORY_MD_CHECK, STORY_MD_CHECK + IMAGES_CHECKS, 1,
     ["test_t9d_nonexistent_story_checks_images_first"]),
    ("every story panel sent", "    user_content = build_user_content(entries)\n", "    user_content = build_user_content(entries)\n    user_content[-1:-1] = [{\"type\": \"text\", \"text\": format_panel_text(p)} for i, p in enumerate(panels, 1) if i not in dict(stills)]\n", 1,
     ["test_t10_successful_run_two_stills"]),
    ("output written to judgment.json", 'os.path.join(story_dir, "stills_judgment.json")', 'os.path.join(story_dir, "judgment.json")', 1,
     ["test_t10_successful_run_two_stills"]),
    ("score maximum 10 -> 11", '"maximum": 10', '"maximum": 11', 4,
     ["test_t8c_out_of_range_or_non_integer_score_rejected", "test_t14_schema_invalid_tool_input"]),
    ("retry removed", RETRY_BLOCK, "", 1,
     ["test_t12_retry_after_missing_tool_call"]),
    ("retry does not re-send user_content", '                {"role": "user", "content": user_content},\n', "", 1,
     ["test_t12_retry_after_missing_tool_call"]),
    ("stills_judgment.raw.json write skipped", "        raw_path = _write_raw(story_dir, responses)\n", '        raw_path = os.path.join(story_dir, "stills_judgment.raw.json")\n', 1,
     ["test_t13_double_failure_writes_raw_and_no_judgment"]),
    ("visual_continuity restored to scores.required", '"required": ["prompt_fidelity", "rendering_quality", "composition"]', '"required": ["prompt_fidelity", "visual_continuity", "rendering_quality", "composition"]', 1,
     ["test_t8e_visual_continuity_optional_for_one_still", "test_t10b_successful_run_one_still"]),
    ("2+-stills visual_continuity check removed", '    if stills_count >= 2 and "visual_continuity" not in tool_input["scores"]:\n', "    if False:\n", 1,
     ["test_t8f_visual_continuity_required_for_two_stills", "test_t14b_two_stills_missing_visual_continuity"]),
    ("always FINAL_USER_TEXT_MULTI_TEMPLATE", "    if count >= 2:\n", "    if True:\n", 1,
     ["test_t7b_build_user_content_one_still", "test_t7c_build_user_content_zero_entries", "test_t10b_successful_run_one_still"]),
    ("always FINAL_USER_TEXT_SINGLE", "    if count >= 2:\n", "    if False:\n", 1,
     ["test_t7_build_user_content_two_stills", "test_t10_successful_run_two_stills"]),
    ("format_score_line has no None branch", NONE_BRANCH, "", 1,
     ["test_t10b_successful_run_one_still"]),
    ("visual_continuity copied with [] instead of .get()", 'tool_input["scores"].get("visual_continuity")', 'tool_input["scores"]["visual_continuity"]', 1,
     ["test_t10b_successful_run_one_still"]),
]
def run(name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="judge-stills-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "tests/test_judge_stills.py::" + name],
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
print("restored bin/judge-stills")
EOF
```
Pass: 21 mutations and 29 `CAUGHT` lines, then `restored bin/judge-stills`. Any `NOT CAUGHT` or anchor-count assertion is a failure.

### R1: judge-story regression

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_story.py -q 2>&1 | tail -1
```
Pass: `19 passed, 1 warning`, matching the pre-Task-1 baseline.

### Scope check

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && git diff --name-only HEAD~6..HEAD
```
Pass: exactly `qwen-agent-workspace/bin/judge-stills` and `qwen-agent-workspace/tests/test_judge_stills.py`. This assumes the six task commits are the six most recent. If other commits were interleaved, replace `HEAD~6` with the commit before Task 1.

### S1: real-data precondition smoke (no key, no network, writes nothing)

This runs the real stills and real `story.md` files through every precondition, the pairing, and the base64 encoding, and stops at the key gate.
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && for s in frogjump test_story7 final_e2e_verify ronin-iterate-test; do env -u ANTHROPIC_API_KEY bin/judge-stills --story-id "$s"; echo "$s rc=$?"; done; git status --short generated/ | head -5
```
Pass:
- `frogjump`, `test_story7`, and `final_e2e_verify` each print the E6 line (`Error: ANTHROPIC_API_KEY is not set; export it in your environment to run judge-stills.`) and `rc=1`. This proves E2-E5 all passed on real data.
- `ronin-iterate-test` prints `Error: stills directory not found: .../generated/stories/ronin-iterate-test/images` and `rc=2`.
- No `stills_judgment*` file appears under any of the four story directories.

### M1 (manual, needs a real key): multi-still judging run

Spec M1. frogjump has 5 stills, every panel has `Image:`, about 8.1 MB base64.
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && find generated/stories/frogjump -type f -exec stat -f '%m %z %N' {} + | sort -k3 > /tmp/judge_stills_m1_before.txt && bin/judge-stills --story-id frogjump; echo "rc=$?"; find generated/stories/frogjump -type f -exec stat -f '%m %z %N' {} + | sort -k3 > /tmp/judge_stills_m1_after.txt; diff /tmp/judge_stills_m1_before.txt /tmp/judge_stills_m1_after.txt; python3 -c "import json; d = json.load(open('generated/stories/frogjump/stills_judgment.json', encoding='utf-8')); print(list(d)); print(d['scores'])"
```
Pass:
- `rc=0`, and stdout matches the spec 5.3 layout with four integer score lines.
- The `diff` shows exactly one added line, for `generated/stories/frogjump/stills_judgment.json`, and nothing else created or modified.
- The keys are `['story_id', 'model', 'effort', 'timestamp', 'usage', 'scores', 'critique']`, with `visual_continuity` an integer.
- The critique names panels by number.

If the API rejects the request (for example, a request-size or image error), it surfaces as E7. Report that to the user as a G2 design question; do not patch around it.

### M2 (manual, informational, not a gate): single-still run

Spec M2. Run `bin/judge-stills --story-id test_story1; echo "rc=$?"`. Expected: `rc=0`, `generated/stories/test_story1/stills_judgment.json` has `"visual_continuity": null`, and stdout prints `  visual_continuity     n/a (only 1 still)`. If `visual_continuity` is instead an integer, the model scored it anyway. Validation accepts that for 1 still, so it is not an error, but record it for the user. This is the only live check of whether the real model follows the 1-still instruction (G1).
