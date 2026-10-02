# bin/judge-story -- Design Spec (Phase 1 of the self-improvement loop)

Date: 2026-10-02
Status: Design approved section-by-section with the user in brainstorming; this document transcribes it. Items the brainstorm did not settle are listed in Section 9 (Known gaps / open questions). Choices made while writing this document, to remove ambiguity, are marked **[spec choice]**.

Workspace root (`WS`): `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/`

---

## 0. Purpose and scope

### 0.1 Purpose

This is Phase 1 of a larger project: a feedback loop, judged by a frontier model, for the story -> image -> video pipeline. Phase 1 does one thing. A human runs `bin/judge-story` by hand against an already-generated `story.md` and gets back:

1. A structured, text-only critique: four 1-10 scores plus free-text critique that names specific panels.
2. A proposed revised version of the prompt that generated the story.

The tool only observes. It does not regenerate anything automatically, and it is not part of the pipeline.

### 0.2 In scope (the whole deliverable)

| # | Item | File |
|---|---|---|
| D1 | New standalone script | `bin/judge-story` (new) |
| D2 | Tests for D1 | `tests/test_judge_story.py` (new) |
| D3 | Additive persistence of the story prompt | `bin/ltx-movie` (edit `phase1_story()` only) |

No other file is created or modified.

### 0.3 Out of scope

- Phase 2 and later of the self-improvement loop: automatic regeneration, closed-loop prompt replacement, image or video judging, multi-story aggregation.
- Wiring `bin/judge-story` into `bin/ltx-movie`'s phase sequence (`_phase_sequence`).
- A new shared Python module or package. Path logic is duplicated inline, following existing repo convention.
- Retry with backoff for API errors (Section 6).
- Backfilling `story_prompt.txt` for stories generated before D3.
- Validating `--story-id` values (for example, rejecting `..`). No existing `bin/*` script does this.
- Validating file content. An empty `story.md` or `story_prompt.txt` is sent as-is. **[spec choice]**
- Streaming API responses.

### 0.4 Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| SC1 | `bin/judge-story --story-id <id>` and `bin/judge-story --story-md <path>` both resolve the correct `story.md` / `story_prompt.txt` pair and write outputs into the directory containing `story.md` | Tests T2, T7 |
| SC2 | A successful run writes `judgment.json` (schema in Section 5.1) and `story_prompt.revised.txt` (exact `revised_prompt` text), prints the scores table and both dividers to stdout, and exits 0 | Test T7 |
| SC3 | Every row of the error table in Section 6 produces the specified exit code and message, and never fabricates scores | Tests T1, T3, T4, T5, T8, T10 |
| SC4 | No test makes a real network call. If `ANTHROPIC_API_KEY` is unset, the Anthropic client is never constructed | Test T8; review of the test file |
| SC5 | `ANTHROPIC_API_KEY`'s value never appears in stdout, stderr, or any file written | Test T11 |
| SC6 | After D3, a real (non-dry-run) Phase 1 run of `bin/ltx-movie` writes `generated/stories/<id>/story_prompt.txt` containing exactly the prompt string passed to qwen-agent | Manual check M1 (Section 8.3) |
| SC7 | D3 does not break existing `bin/ltx-movie` tests | Regression gate R1 (Section 8.3) |

### 0.5 Must-have vs nice-to-have

Every requirement in Sections 1-8 is a must-have. This phase has no nice-to-haves, and nothing beyond these sections is to be built.

---

## 1. Architecture

`bin/judge-story` is a new standalone Python script that follows the existing `bin/*` convention:

- Plain executable script, shebang `#!/usr/bin/env python3`, module docstring at the top, no file extension, executable bit set (`chmod +x`).
- Loaded as `__main__`. It has `def main(argv=None):` returning an `int`, and ends with:
  ```python
  if __name__ == "__main__":
      sys.exit(main())
  ```
  This matches `bin/ltx-movie:1082/1156-1157` and `bin/ltx-story-manifest:309/573-574`.
- It imports nothing from another `bin/*` file and introduces no shared module. The repo already duplicates small shared logic, such as story-dir path resolution, across `bin/ltx-movie`, `bin/ltx-story-manifest`, and `bin/ltx-mlx-render`. This script follows that precedent.
- Top-level imports: `argparse`, `datetime`, `json`, `os`, `sys`, `anthropic`, `jsonschema`. `anthropic` and `jsonschema` are imported at module top level **[spec choice]** so tests can monkeypatch `judge_story.anthropic.Anthropic`.

### 1.1 Execution sequence

`main(argv)` performs these steps in this exact order **[spec choice on ordering: file preconditions before the env check]**:

1. Parse arguments (Section 3). argparse errors exit 2 through argparse's own `SystemExit(2)`.
2. Resolve paths (Section 3.2) into `story_dir`, `story_md_path`, `story_prompt_path`.
3. If `story_md_path` is not an existing regular file (`os.path.isfile`), print the error to stderr and return 2.
4. If `story_prompt_path` is not an existing regular file, print the error to stderr and return 2.
5. Read both files as UTF-8 text.
6. If `ANTHROPIC_API_KEY` is unset or empty, print the error to stderr and return 1. This happens before `anthropic.Anthropic` is constructed.
7. Construct `anthropic.Anthropic()` with no arguments. The SDK reads the key from the environment.
8. Run the judging call and its single possible retry (Section 4).
9. Validate the tool input against the schema (Section 4.4).
10. Write `judgment.json`, then `story_prompt.revised.txt` (Section 5).
11. Print the stdout summary (Section 5.3). Return 0.

Why this ordering: file-precondition failures (exit 2) are reported the same way whether or not the key is set, and the missing-file tests do not need to manipulate the environment.

### 1.2 Internal function names [spec choice]

The implementer must use these names so tests can target them:

| Name | Kind | Responsibility |
|---|---|---|
| `WS` | module global | `os.path.dirname(os.path.dirname(os.path.realpath(__file__)))` |
| `MODEL` | module constant | `"claude-opus-5-5"` |
| `THINKING_BUDGET_TOKENS` | module constant | `16000` |
| `MAX_TOKENS` | module constant | `21333`. Final (Section 9, G1 resolved) |
| `TOOL_NAME` | module constant | `"submit_judgment"` |
| `SUBMIT_JUDGMENT_SCHEMA` | module constant (dict) | The JSON Schema in Section 4.3 |
| `SYSTEM_PROMPT` | module constant (str) | Section 4.5 |
| `RETRY_USER_MESSAGE` | module constant (str) | Section 4.6 |
| `build_parser()` | function | Returns the `argparse.ArgumentParser` |
| `resolve_paths(story_id, story_md)` | function | Returns `(story_dir, story_md_path, story_prompt_path)`. Reads the module global `WS` at call time, not at import time, so tests can monkeypatch it |
| `build_user_message(story_md_text, story_prompt_text)` | function | Returns the user-turn string (Section 4.5) |
| `find_tool_use(response)` | function | Returns the first content block with `type == "tool_use"` and `name == TOOL_NAME`, else `None` |
| `validate_judgment_input(tool_input)` | function | Calls `jsonschema.validate(instance=tool_input, schema=SUBMIT_JUDGMENT_SCHEMA)`. Raises `jsonschema.ValidationError` on failure |
| `main(argv=None)` | function | Orchestrates Section 1.1 and returns the exit code |

---

## 2. Companion change to `bin/ltx-movie`

### 2.1 Current state (confirmed by investigation)

Nothing in the codebase writes the story-generation prompt to disk:

- `phase1_story()` (`bin/ltx-movie:654`) builds the prompt with `build_story_prompt(...)` (`bin/ltx-movie:663-665`) and passes it to a `bin/qwen-agent` subprocess through `--user-prompt`.
- The status line redacts it: `cmd[:-1] + ["--user-prompt", "<%d chars>" % len(prompt)]` (`bin/ltx-movie:680`).
- The only place the full prompt is printed is `--dry-run`'s `_print_dry_run_plan()` (its own `build_story_prompt` call is at `bin/ltx-movie:976`), and it prints to stdout only.

### 2.2 Required change

In `phase1_story()`, immediately after the `build_story_prompt(...)` statement (the one ending `seconds=_clip_seconds(args))` at line 665) and before `max_tokens = _phase1_max_tokens(args.panels)`, insert:

```python
        with open(os.path.join(_story_dir(args.story_id), "story_prompt.txt"), "w",
                  encoding="utf-8") as f:
            f.write(prompt)
```

Constraints:

- The file contains the exact `prompt` string, verbatim: UTF-8 plain text with no JSON wrapper, no metadata, and no trailing newline added.
- `_story_dir(story_id)` is already defined at `bin/ltx-movie:383-384`. Reuse it.
- No `os.makedirs` is needed. `main()` creates `paths["story_dir"]` (`bin/ltx-movie:1115`) before any phase runs, and `phase1_story` is called only from `main()`'s phase loop.
- Do not modify the `cmd = [sys.executable, os.path.join(WS, "bin", "qwen-agent"),` lines. `tests/test_ltx_movie_offline.py` test L19 asserts on their exact text.
- The `_print_dry_run_plan()` path is unchanged. `--dry-run` does not write `story_prompt.txt`.

### 2.3 Resulting behavior (consequences, not additional requirements)

- `story_prompt.txt` is written or overwritten each time Phase 1 actually generates a story, which means `story.md` is absent or `--force-story` is passed.
- If Phase 1 is skipped because `story.md` already exists and `--force-story` was not given, `story_prompt.txt` is not written. For stories generated before this change, `bin/judge-story` exits 2 (Section 6) until they are regenerated with `--force-story`.
- The file is written before qwen-agent runs. If qwen-agent then fails or times out, `story_prompt.txt` exists but `story.md` may not.

---

## 3. CLI interface

### 3.1 Synopsis

```
bin/judge-story --story-id <id>
bin/judge-story --story-md <path/to/story.md>
```

`build_parser()`:

- `argparse.ArgumentParser(prog="judge-story", description=<one-line description of the tool>)`.
- `group = parser.add_mutually_exclusive_group(required=True)`.
- `group.add_argument("--story-id", dest="story_id", metavar="ID", help=...)`.
- `group.add_argument("--story-md", dest="story_md", metavar="PATH", help=...)`.
- No other arguments.

Giving both flags, or neither, is an argparse error: usage goes to stderr and the process raises `SystemExit(2)`.

### 3.2 Path resolution (`resolve_paths`)

When `--story-id` is given, use this pattern inline. It is copied from the duplicated precedent in `bin/ltx-movie:383-391`, `bin/ltx-story-manifest:534`, and `bin/ltx-mlx-render:147-148`.

```python
WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
story_dir = os.path.join(WS, "generated", "stories", story_id)
story_md_path = os.path.join(story_dir, "story.md")
story_prompt_path = os.path.join(story_dir, "story_prompt.txt")
```

When `--story-md` is given:

```python
story_md_path = os.path.abspath(story_md)          # [spec choice] absolutize
story_dir = os.path.dirname(story_md_path)
story_prompt_path = os.path.join(os.path.dirname(story_md_path), "story_prompt.txt")
```

The given path is made absolute with `os.path.abspath`, without resolving symlinks, so that `judgment.json` records an unambiguous "actual resolved path used" **[spec choice]**. The `--story-id` branch produces absolute paths already because `WS` comes from `realpath`.

### 3.3 Output location

All output files (`judgment.json`, `story_prompt.revised.txt`, and on failure `judgment.raw.json`) are written to `story_dir`, the directory containing the resolved `story.md`. This holds for both flags. Existing files with those names are overwritten without a prompt **[spec choice]**. Files from an earlier run are never deleted: a failed run leaves any earlier `judgment.json` in place.

---

## 4. Judging-call mechanics

### 4.1 Request parameters

Every `client.messages.create(...)` call uses exactly these parameters:

```python
client.messages.create(
    model=MODEL,                                   # "claude-opus-5-5"
    max_tokens=MAX_TOKENS,                         # 21333, final (Section 9, G1 resolved)
    thinking={"type": "enabled", "budget_tokens": THINKING_BUDGET_TOKENS},  # 16000
    system=SYSTEM_PROMPT,
    tools=[{
        "name": TOOL_NAME,                         # "submit_judgment"
        "description": TOOL_DESCRIPTION,
        "input_schema": SUBMIT_JUDGMENT_SCHEMA,
    }],
    tool_choice={"type": "auto"},
    messages=messages,
)
```

- Extended thinking with `budget_tokens=16000` is how "high effort" is achieved. The Messages API has no literal effort parameter.
- **API constraint (confirmed):** when extended thinking is enabled, `tool_choice` cannot force a specific tool. Only `auto` or `none` is valid. The script therefore offers exactly one tool with `tool_choice={"type": "auto"}` and relies on `SYSTEM_PROMPT` to require the call.
- Do not pass `temperature`, `top_k`, or `top_p`. Extended thinking does not accept non-default values for these.
- Do not stream. Use the plain non-streaming `messages.create`.
- `MAX_TOKENS = 21333` is final (Section 9, G1 resolved). It satisfies the SDK's non-streaming cap (`max_tokens > 21333` requires an explicit `timeout=`, which this design does not use) while leaving roughly 5,300 tokens of visible output above `THINKING_BUDGET_TOKENS` (16000) — plenty for a critique plus a revised prompt comparable to or somewhat longer than the ~3,783-character (~1,000-token) original example prompt. If real-world runs (M2) show truncated output, raising `max_tokens` with an explicit `timeout=` is the follow-up; that is out of scope for this spec.
- `TOOL_DESCRIPTION` **[spec choice, verbatim]**: `"Submit your judgment of the story: four 1-10 scores, a critique naming specific panels by number, and a full revised story-generation prompt. You must call this exactly once."`

### 4.2 API key handling

- Read the key only from the environment. Check with `os.environ.get("ANTHROPIC_API_KEY")`. Both `None` and `""` count as unset **[spec choice: empty treated as unset]**.
- If unset, print `Error: ANTHROPIC_API_KEY is not set; export it in your environment to run judge-story.` to stderr and return 1, without constructing `anthropic.Anthropic`.
- If set, construct `anthropic.Anthropic()` with no `api_key` argument. The SDK reads the environment itself.
- The key value is never printed, logged, interpolated into any message, or written to any file. The raw response dumps (Section 4.6) are API response bodies and do not contain the key.

### 4.3 `submit_judgment` input schema (`SUBMIT_JUDGMENT_SCHEMA`)

```json
{
  "type": "object",
  "properties": {
    "scores": {
      "type": "object",
      "properties": {
        "pacing_progression":  {"type": "integer", "minimum": 1, "maximum": 10},
        "action_plausibility": {"type": "integer", "minimum": 1, "maximum": 10},
        "visual_specificity":  {"type": "integer", "minimum": 1, "maximum": 10},
        "continuity":          {"type": "integer", "minimum": 1, "maximum": 10}
      },
      "required": ["pacing_progression", "action_plausibility", "visual_specificity", "continuity"]
    },
    "critique": {
      "type": "string",
      "description": "Free-text critique. Name specific panels by number (e.g. 'Panel 7')."
    },
    "revised_prompt": {
      "type": "string",
      "description": "A complete replacement for the original story-generation prompt that addresses the critique."
    }
  },
  "required": ["scores", "critique", "revised_prompt"]
}
```

No `additionalProperties` constraint is added. Extra keys are tolerated and ignored, and only the specified keys are copied into `judgment.json` **[spec choice]**.

### 4.4 Tool-input validation

- `find_tool_use(response)` scans `response.content` in order and returns the first block with `block.type == "tool_use"` and `block.name == "submit_judgment"`, or `None`.
- When a block is found, `validate_judgment_input(block.input)` runs `jsonschema.validate(instance=block.input, schema=SUBMIT_JUDGMENT_SCHEMA)`. jsonschema selects the validator class from the schema; because the schema has no `$schema` key, that is the latest draft.
- Validation rejects: a missing `scores`, `critique`, or `revised_prompt`; a missing score key; a score below 1 or above 10; and a non-integer score. jsonschema does not treat booleans as integers.
- If validation fails, the run is treated as a failed judgment and is not retried **[spec choice, see Section 9, G3]**. The script writes `judgment.raw.json` with every raw response received so far (Section 4.6), prints `Error: submit_judgment input failed schema validation: <ValidationError.message>` to stderr, and returns 1. No scores are fabricated.

### 4.5 Prompt content

The model receives a system prompt and one user turn.

`SYSTEM_PROMPT` **[spec choice, verbatim text authored from the approved requirements]**:

```
You are an expert story editor judging a story written for an AI image-and-video generation pipeline. The story is intended to become a multi-panel, action-focused storyboard. The target output goal is the most realistic action scenes possible, with relatively little dialogue.

Score the story on four dimensions, each an integer from 1 (worst) to 10 (best):
- pacing_progression: whether the action builds and progresses panel to panel, without stalls, repeats, or jumps.
- action_plausibility: whether each panel depicts physically realistic action that a camera could plausibly capture.
- visual_specificity: whether each panel gives concrete, filmable visual detail rather than abstract or emotional description.
- continuity: whether characters, setting, props, and positions stay consistent across panels.

Then write a critique that names specific panels by number (for example, "Panel 7") when identifying strengths and problems.

Finally, write a complete revised version of the original story-generation prompt that would address your critique. The revised prompt must be a full replacement for the original prompt, usable as-is, not a list of suggested edits.

You must deliver your judgment by calling the submit_judgment tool exactly once. Do not put the judgment in a plain text reply; a response without a submit_judgment call is a failure.
```

`build_user_message(story_md_text, story_prompt_text)` returns exactly:

```
Below are the original story-generation prompt and the story it produced.

<story_prompt>
{story_prompt_text}
</story_prompt>

<story_md>
{story_md_text}
</story_md>

Judge the story and call submit_judgment.
```

Both texts are inserted in full: no truncation, escaping, or stripping. The first call's `messages` is `[{"role": "user", "content": build_user_message(...)}]`.

### 4.6 Retry and double-failure

1. Call 1 sends `messages` as above. Let `r1` be the response.
2. If `find_tool_use(r1)` returns a block, go to validation (Section 4.4). There is no retry.
3. Otherwise make exactly one retry in the same conversation:
   ```python
   messages = [
       {"role": "user", "content": build_user_message(...)},
       {"role": "assistant", "content": r1.content},   # full content list, thinking blocks included, unmodified
       {"role": "user", "content": RETRY_USER_MESSAGE},
   ]
   ```
   Same parameters as Section 4.1, including `tool_choice={"type": "auto"}`. Let `r2` be the response.
   - The assistant turn passes `r1.content`, the SDK's list of content block objects, exactly as received. The API requires thinking blocks, with their signatures, to be returned unmodified.
   - `RETRY_USER_MESSAGE` **[spec choice, verbatim]**: `"You did not call the submit_judgment tool. Call submit_judgment now with your scores, critique, and revised_prompt. Do not reply with plain text."`
4. If `find_tool_use(r2)` returns a block, go to validation.
5. Otherwise this is a double failure:
   - Write `story_dir/judgment.raw.json` as UTF-8 JSON, `indent=2`, `ensure_ascii=False`, with this shape **[spec choice]**:
     ```json
     {"responses": [<r1.model_dump(mode="json")>, <r2.model_dump(mode="json")>]}
     ```
   - Print `Error: Claude did not call submit_judgment after one retry; raw responses written to <path>` to stderr.
   - Return 1. Write no `judgment.json` and no `story_prompt.revised.txt`. Never fabricate scores.

At most two API calls are made per run.

---

## 5. Output files and stdout

### 5.1 `judgment.json`

Written to `story_dir/judgment.json` as UTF-8 JSON with `json.dump(obj, f, indent=2, ensure_ascii=False)` plus a trailing `"\n"` **[spec choice: formatting]**. Keys appear in this order:

```json
{
  "story_md_path": "<story_md_path as resolved in Section 3.2>",
  "story_prompt_path": "<story_prompt_path as resolved in Section 3.2>",
  "model": "claude-opus-5-5",
  "thinking_budget_tokens": 16000,
  "timestamp": "2026-10-02T14:03:11Z",
  "usage": {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0},
  "scores": {
    "pacing_progression": 0,
    "action_plausibility": 0,
    "visual_specificity": 0,
    "continuity": 0
  },
  "critique": "string",
  "revised_prompt": "string"
}
```

Field rules:

- `model`: the literal `MODEL` constant (`"claude-opus-5-5"`), not `response.model`.
- `thinking_budget_tokens`: the literal `THINKING_BUDGET_TOKENS` (`16000`).
- `timestamp`: UTC time captured right after the successful API response returns, formatted as `datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`.
- `usage` **[spec choice: summed across all calls in the run]**. Both calls are billed, so the values are summed over every response received (r1, plus r2 if a retry happened):
  - `input_tokens`: sum of `response.usage.input_tokens`.
  - `output_tokens`: sum of `response.usage.output_tokens`. The API counts thinking tokens inside output tokens.
  - `thinking_tokens`: sum of `response.usage.output_tokens_details.thinking_tokens`. The installed SDK (anthropic 0.116.0) exposes this field, but it is `Optional`. If `output_tokens_details` or its `thinking_tokens` is `None` on every response, write JSON `null`. If it is present on some responses, sum the ones present **[spec choice: `null` instead of a fabricated 0; see Section 9, G4]**.
- `scores`: the four keys, in the order shown, with values copied from the validated tool input.
- `critique`, `revised_prompt`: copied verbatim from the validated tool input.

### 5.2 `story_prompt.revised.txt`

Written to `story_dir/story_prompt.revised.txt` as UTF-8 plain text: exactly the `revised_prompt` string, with no JSON, no added trailing newline, and no header. It is written after `judgment.json`.

### 5.3 Stdout (success only)

Format **[spec choice: exact layout]**:

```
Scores:
  pacing_progression    7
  action_plausibility   6
  visual_specificity    8
  continuity            5

--- Critique ---
<full critique text>

--- Revised prompt ---
<full revised_prompt text>
```

- Each score line is `"  %-20s  %d" % (name, value)`, in the key order of Section 5.1. That gives two leading spaces, the name left-justified in 20 columns, two spaces, then the value.
- The dividers are exactly `--- Critique ---` and `--- Revised prompt ---`, each on its own line and preceded by one blank line.
- The critique and revised prompt are printed in full, never truncated.
- Nothing else goes to stdout: no progress lines, no usage, and no output-path lines. stdout is exactly the block above.

---

## 6. Error handling

Exit codes: 0 success; 1 runtime or API failure; 2 argument or precondition failure. This matches the codebase's existing convention of 2 for precondition failures, as used throughout `bin/ltx-movie`. All error messages go to stderr and begin with `Error: `.

| # | Condition | Detected at (Section 1.1 step) | Message to stderr [spec choice: wording] | Exit | Files written |
|---|---|---|---|---|---|
| E1 | Both or neither of `--story-id` / `--story-md` | 1 | argparse's own usage error | 2 (argparse `SystemExit`) | none |
| E2 | Resolved `story.md` missing | 3 | `Error: story.md not found: <story_md_path>` | 2 | none |
| E3 | Resolved `story_prompt.txt` missing | 4 | `Error: story_prompt.txt not found: <story_prompt_path>. judge-story needs the original story-generation prompt to produce revised_prompt. This story may predate bin/ltx-movie's story_prompt.txt persistence (re-run its Phase 1 with --force-story), or --story-md points at a directory without the sibling file.` | 2 | none |
| E4 | `ANTHROPIC_API_KEY` unset or empty | 6 | `Error: ANTHROPIC_API_KEY is not set; export it in your environment to run judge-story.` | 1 | none |
| E5 | Anthropic API error (auth, rate limit, overloaded, connection, timeout, or any other SDK error) | 8 | `Error: Anthropic API call failed: <type(e).__name__>: <str(e)>` | 1 | none |
| E6 | No `submit_judgment` tool_use after one retry | 8 | Section 4.6 step 5 | 1 | `judgment.raw.json` |
| E7 | Tool input fails schema validation | 9 | Section 4.4 | 1 | `judgment.raw.json` |

E5 details:

- Wrap each `client.messages.create` call in `except anthropic.APIError as e:`. `anthropic.APIError` is the SDK base class covering `APIStatusError` (and its subclasses `AuthenticationError`, `RateLimitError`, `OverloadedError`, `InternalServerError`, and others), `APIConnectionError`, and `APITimeoutError`.
- If the retry call (call 2) raises, E5 applies. `r1` is not written to `judgment.raw.json` in that case **[spec choice]**.
- The tool adds no retry or backoff of its own. The SDK's built-in default `max_retries` is left unchanged (see Section 9, G2).
- Python exceptions outside this table (for example `OSError` on writing output, or `UnicodeDecodeError` on reading input) are not caught and propagate as tracebacks **[spec choice, following Simplicity First: no handling for unspecified cases]**.

---

## 7. Testing

### 7.1 Framework and style

- File: `tests/test_judge_story.py`, using pytest with plain `assert` statements. Do not use the `check()` helper style from `tests/test_ltx_movie_offline.py`: a non-raising `check()` makes pytest report false greens. The precedent for real-logic tests next to SDK-boundary mocks is `tests/test_z_image_skill_cache.py`.
- Load the script as a module the way `tests/test_ltx_movie_offline.py:22-26` loads `bin/ltx-movie`:
  ```python
  WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
  _SCRIPT_PATH = os.path.join(WS, "bin", "judge-story")
  judge_story = importlib.machinery.SourceFileLoader("judge_story", _SCRIPT_PATH).load_module()
  ```
- No real API calls, ever. Every test that reaches step 7 of Section 1.1 must first `monkeypatch.setattr(judge_story.anthropic, "Anthropic", <fake factory>)`. The fake factory records each construction and returns an object whose `.messages.create(**kwargs)` records the kwargs and returns pre-built responses in sequence.
- Pre-built responses are real SDK objects built with `anthropic.types.Message.model_validate({...})`, so `.content`, `.usage`, and `.model_dump(mode="json")` behave as in production. Include a `thinking` block (with `thinking` and `signature` strings) in responses that represent thinking output.
- Story fixtures are created under `tmp_path`, and tests use `--story-md <tmp_path>/story.md` so nothing is written into the real `generated/` tree. Tests that use `--story-id` either must exit before any write (T3) or only call `resolve_paths` directly (T2).
- Tests that need a key set use `monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-SENTINEL-do-not-leak")`. Tests that need it unset use `monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)`.

### 7.2 Real (unmocked) tests

| ID | Test | Assertion |
|---|---|---|
| T1a | `main(["--story-id", "x", "--story-md", "y"])` | raises `SystemExit` with `code == 2` |
| T1b | `main([])` | raises `SystemExit` with `code == 2` |
| T2a | `resolve_paths("abc", None)` | returns `(os.path.join(judge_story.WS, "generated", "stories", "abc"), .../story.md, .../story_prompt.txt)` exactly, and `judge_story.WS` equals the test file's `WS` |
| T2b | `resolve_paths(None, str(tmp_path / "s" / "story.md"))` | `story_dir == str(tmp_path / "s")`, `story_prompt_path == str(tmp_path / "s" / "story_prompt.txt")` |
| T3a | `--story-md` pointing at a `tmp_path` with no `story.md` | `main(...) == 2`; stderr contains `story.md not found` |
| T3b | `--story-id` of a nonexistent id (`"judge-story-test-nonexistent-<uuid4 hex>"`) | `main(...) == 2` |
| T4 | `tmp_path` with `story.md` but no `story_prompt.txt` | `main(...) == 2`; stderr contains `story_prompt.txt not found` |
| T5a | `validate_judgment_input` with each top-level required key removed in turn (3 cases) | raises `jsonschema.ValidationError` |
| T5b | `validate_judgment_input` with each score key removed in turn (4 cases) | raises `jsonschema.ValidationError` |
| T5c | `validate_judgment_input` with a score of `0`, then `11` | raises `jsonschema.ValidationError` |
| T5d | `validate_judgment_input` with a fully valid payload (all scores at 1, then at 10) | does not raise |
| T7 | Successful mocked run: one response with a valid `submit_judgment` tool_use | see the assertion list directly below |

T7 uses the SDK mock but checks real logic, so it is listed here as the "successful mocked run" from the brief. Its mocked response's `usage` sets `input_tokens`, `output_tokens`, and `output_tokens_details.thinking_tokens` to distinct nonzero integers. Its assertions:

- `main(["--story-md", str(story_md)]) == 0`.
- `judgment.json` exists in `tmp_path`, parses as JSON, and has exactly the keys of Section 5.1 in that order. `model == "claude-opus-5-5"`, `thinking_budget_tokens == 16000`, `timestamp` matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$`, `scores`/`critique`/`revised_prompt` equal the mocked tool input, `story_md_path`/`story_prompt_path` equal the resolved paths, and `usage` equals the mocked usage values.
- `story_prompt.revised.txt` content is byte-equal to the mocked `revised_prompt`.
- Captured stdout contains each `"  %-20s  %d"` score line, `--- Critique ---`, `--- Revised prompt ---`, the full critique, and the full revised prompt.
- The recorded `create` kwargs have `model == "claude-opus-5-5"`, `thinking == {"type": "enabled", "budget_tokens": 16000}`, `tool_choice == {"type": "auto"}`, exactly one tool named `submit_judgment` whose `input_schema` is `SUBMIT_JUDGMENT_SCHEMA`, and a user message containing both the fixture `story.md` text and the fixture `story_prompt.txt` text.
- `create` was called exactly once.

### 7.3 Mocked tests

| ID | Test | Assertion |
|---|---|---|
| T8 | Key unset (`delenv`), valid fixtures present | `main(...) == 1`; the fake `Anthropic` factory was constructed **zero** times and `create` was called zero times; stderr contains `ANTHROPIC_API_KEY` |
| T9 | Retry path: r1 has only a text block (and a thinking block); r2 has a valid tool_use | `main(...) == 0`; `create` called exactly twice; the second call's `messages` has length 3 with roles `user, assistant, user`, the assistant content equals r1's content, and the last user content equals `RETRY_USER_MESSAGE`; the second call also uses `tool_choice == {"type": "auto"}`; `judgment.json` written; `usage` values are the sums of r1 and r2 |
| T10 | Double failure: r1 and r2 both have no tool_use | `main(...) == 1`; `create` called exactly twice; `judgment.raw.json` exists and `json.load(...)["responses"]` has length 2, equal to `[r1.model_dump(mode="json"), r2.model_dump(mode="json")]`; `judgment.json` and `story_prompt.revised.txt` do **not** exist |
| T10b | Schema-invalid tool input: r1's tool_use has `continuity: 11` | `main(...) == 1`; `create` called exactly once; `judgment.raw.json` written with 1 response; no `judgment.json` |
| T10c | API error: `create` raises `anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))` (the test imports `httpx`, which `anthropic` depends on) | `main(...) == 1`; stderr contains `Anthropic API call failed`; no output files written |
| T11 | No key leakage: rerun the T7 and T10 scenarios with the sentinel key | the sentinel string `sk-test-SENTINEL-do-not-leak` does not appear in captured stdout, captured stderr, `judgment.json`, `story_prompt.revised.txt`, or `judgment.raw.json` |

### 7.4 Mutation checks (negative controls)

Before declaring D2 complete, the implementer applies each mutation below to `bin/judge-story` one at a time, runs the suite, confirms at least one named test fails, and reverts the mutation:

| Mutation | Must fail |
|---|---|
| Move the API-key check after `anthropic.Anthropic()` construction | T8 |
| Change `"maximum": 10` to `"maximum": 11` | T5c and T10b |
| Remove the retry (go straight to double-failure on r1) | T9 |
| Skip writing `judgment.raw.json` | T10 |
| Return 0 instead of 2 for a missing `story_prompt.txt` | T4 |
| Write `revised_prompt + "\n"` to `story_prompt.revised.txt` | T7 |

---

## 8. Implementation checklist and acceptance

### 8.1 Files

| File | Action |
|---|---|
| `bin/judge-story` | Create, `chmod +x` |
| `tests/test_judge_story.py` | Create |
| `bin/ltx-movie` | Insert the 3 lines in Section 2.2, nothing else |

### 8.2 Dependencies

- `anthropic`: imported at module top level. On this machine, `python3` (3.13.0, the interpreter the `#!/usr/bin/env python3` shebang resolves to) has `anthropic` 0.116.0. Apple `/usr/bin/python3` 3.9.6 does not. See Section 9, G5.
- `jsonschema`: imported at module top level. It may be a new dependency for this codebase. The implementer must confirm it is importable under the interpreter that runs `bin/*` and the tests, and that it is lightweight to add if missing (Section 9, G5).

### 8.3 Acceptance

| ID | Check | Pass condition |
|---|---|---|
| A1 | `python3 -m pytest tests/test_judge_story.py -v`, run from `WS` by the main thread (implementer-reported counts are not accepted) | every test in Sections 7.2 and 7.3 passes, and the count matches the number of tests defined there |
| A2 | Mutation checks in Section 7.4 | each mutation makes at least one named test fail |
| R1 | Existing `bin/ltx-movie` suite: `python3 tests/test_ltx_movie_offline.py` (run directly, because its `check()` style can give false greens under pytest) | same pass/fail result as before D3 |
| M1 | Manual: one real `bin/ltx-movie` Phase 1 run (or a `--force-story` rerun) | `generated/stories/<id>/story_prompt.txt` exists and is byte-equal to the prompt `build_story_prompt` returned for those args |
| M2 | Manual: `bin/judge-story --story-id <id from M1>` with a real key | exit 0, both output files present, stdout layout matches Section 5.3 |

---

## 9. Known gaps / open questions

These points were not settled in the brainstorm. No item in this section is blocking. Two items that were previously open are now resolved and no longer listed as gaps: G1 (`max_tokens` value) was resolved by the user on 2026-10-02 and is reflected in Section 4.1; its bullet is removed from this section. G9 (20-panel framing) was fixed the same day and is reflected in Section 4.5; its bullet is kept below, marked FIXED, for traceability. Every remaining item (G2-G8) has a spec choice recorded above that the user may override.

- **G2: SDK built-in retries.** The approved design says "no retry-with-backoff." The Anthropic SDK itself retries 429/5xx/connection errors by default (`max_retries=2`, with backoff). This spec reads "no retry" as "the tool adds no retry logic" and leaves the SDK default unchanged. If the user wants strictly one attempt, construct `anthropic.Anthropic(max_retries=0)`.
- **G3: what happens when the tool input fails validation.** The brief requires validation to reject bad tool input but does not say what follows. Spec choice: treat it as a failure (write `judgment.raw.json`, exit 1) with no retry, because the one-retry rule was approved only for "no tool_use block." Alternative: spend the single retry here too.
- **G4: `thinking_tokens` source and absent-value handling.** The approved schema includes `usage.thinking_tokens`, but its source was not discussed. Spec choice: `response.usage.output_tokens_details.thinking_tokens`, a field in the installed SDK, summed across calls, with `null` (not 0) when the API does not report it, so the value is never fabricated. Separately, the spec sums `usage` across both calls when a retry occurs. Alternative: report only the final call.
- **G5: dependency availability.** `anthropic` 0.116.0 and `jsonschema` 4.23.0 import under `python3` 3.13.0 on the development machine as of this writing. The implementer must still confirm: (a) that the interpreter running `bin/*` and pytest has both; (b) whether `jsonschema` should be declared anywhere (the workspace has no `requirements*.txt` or `pyproject.toml`); and (c) whether `bin/judge-story` should be added to the deploy package (`tests/test_deploy_pkg.py` / the cctech/16GB-M1 packaging), which would bring in the dual-interpreter gate. Recommendation: it is a dev-machine tool and stays out of the deploy package for Phase 1.
- **G6: `claude-opus-5-5` and `thinking.type: "enabled"` compatibility not verified against the live API.** The installed SDK's model literal list stops at `claude-opus-4-8` (the `model` parameter also accepts arbitrary strings, so this does not block the call), and the SDK also offers an `adaptive` thinking config. Whether `claude-opus-5-5` accepts `{"type": "enabled", "budget_tokens": 16000}` with `tool_choice: auto` will only be confirmed by M2. If the API rejects it, that is a design change for the user, not an implementer decision.
- **G7: no automated test for the `bin/ltx-movie` change (D3).** The brief limits changes to `bin/judge-story`, its test file, and the `bin/ltx-movie` edit, so D3 has no new automated test. It is covered by R1 (no regression) and M1 (manual). If the user wants an automated check, the natural place is a new test in `tests/test_ltx_movie_offline.py` that stubs `subprocess.Popen` and calls `phase1_story` with a temporary story id. That would change a fourth file.
- **G8: prompt wording.** The verbatim `SYSTEM_PROMPT`, user-message template, `TOOL_DESCRIPTION`, `RETRY_USER_MESSAGE`, the four dimension glosses, and all error-message wording were written for this spec from the approved requirements. The brainstorm approved their content requirements, not their exact wording. The user should review Section 4.5 in particular, since it directly shapes judgment quality.
- **G9 (FIXED): 20-panel framing vs the actual panel count.** The original draft's prompt framing said the story is "intended to become a 20-panel ... storyboard," hardcoded from the one 20-panel Ronin story that motivated this project. `bin/judge-story` is a general-purpose Phase 1 tool (Section 0), `bin/ltx-movie` accepts a variable `--panels`, and existing stories have other counts (for example the 15-panel M1 run). Fixed: `SYSTEM_PROMPT` (Section 4.5) now reads "a multi-panel, action-focused storyboard," with no fixed panel number. The spec still does not read or count panels from `story.md` content — that would be an unneeded addition beyond what was asked.
