# Prompt anchoring fixes: design spec

Date: 2026-10-05. Branch: `qwen-agent-redteam`. Workspace (WS): `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace`. The git root is one level up, so repo paths are `qwen-agent-workspace/...`.

Status: approved by the user (three fixes). This spec has no open questions. Every design choice is made here. The implementer types exactly the text below and decides nothing.

## 0. Background, scope, success criteria

### 0.1 Problem (audit already done)

When a model-facing prompt contains a concrete example, the model copies it.

- `bin/ltx-movie:108` (STORY_PROMPT_TEMPLATE, Panel 1 `Image:` instructions) contains `such as "the woman in grey"`. Story first drafts copied it word for word, and the stills then rendered a grey costume. On disk today, 6 of the 47 `generated/stories/*/story.md` files contain "woman in grey".
- `bin/ltx-movie:141` (STORY_PROMPT_TEMPLATE_NO_STILLS, `Prompt:` style line) names three fixed production-value phrases. They leaked into 8 stories (8 of 47 on disk today).
- `bin/judge-story`, `bin/judge-stills` and `bin/judge-clips` each hard-code the target genre goal in their `SYSTEM_PROMPT`.

The observable-description example `"her eyebrows angle down and her lips press together"` at `bin/ltx-movie:141` has not leaked: it appears in 0 of 47 stories on disk. It stays unchanged.

### 0.2 In scope

| Fix | Files changed |
|---|---|
| FIX 1: referring-phrase instruction | `bin/ltx-movie` (line 108 only), `tests/test_ltx_movie_offline.py` |
| FIX 2: production-quality phrases | `bin/ltx-movie` (line 141 only), `tests/test_ltx_movie_offline.py` |
| FIX 3: `--goal` parameter | `bin/judge-story`, `bin/judge-stills`, `bin/judge-clips`, `bin/iterate-story`, `tests/test_judge_story.py`, `tests/test_judge_stills.py`, `tests/test_judge_clips.py`, `tests/test_iterate_story.py` |

No other file changes. In particular, the earlier design specs (`docs/superpowers/specs/2026-10-02-judge-story-design.md`, `2026-10-03-iterate-story-design.md`, `2026-10-04-judge-stills-design.md`, `2026-10-04-judge-clips-design.md`) are NOT edited. Where they describe the system-prompt text, the CLI, or the output-JSON key order, this spec supersedes them for the goal.

### 0.3 Success criteria (all must hold)

- SC1: `bin/ltx-movie` differs from commit `1d8580b` in exactly two lines, 108 and 141, and each line's new text is the exact text in sections 1 and 2.
- SC2: No rendered story prompt (any of the four `no_stills` x `seed_image` combinations) contains "woman in grey", "warm cinematic lighting", "film-grade color", "crisp fine detail" or "production-value".
- SC3: For each of the three judges, if `--goal` is omitted, the system prompt sent to the API is byte-for-byte equal to the current `SYSTEM_PROMPT` constant at commit `1d8580b`. This is checked two ways: the sha256 pin in the new tests, and the independent command A9 in section 6.
- SC4: With `--goal TEXT`, the normalized TEXT replaces the goal in the system prompt of both the first call and the retry call. Nothing else in the prompt changes.
- SC5: `judgment.json`, `stills_judgment.json` and `clips_judgment.json` always contain a `"goal"` key, placed immediately after `"effort"`. Its value is the exact goal text that went into the prompt (the default when `--goal` is omitted).
- SC6: `bin/iterate-story --goal TEXT` passes `--goal TEXT` verbatim to every `judge-story` call and to no `ltx-movie` call. Without `--goal`, every argv is unchanged.
- SC7: The exact test counts in section 6 pass, and every mutation in section 5 makes at least one named test fail.

### 0.4 Must-haves vs nice-to-haves

Everything in sections 1-7 is a must-have. There are no nice-to-haves in this change. Section 8 lists what is explicitly out of scope.

---

## 1. FIX 1: referring phrase built only from given details (`bin/ltx-movie:108`)

### 1.1 Edit E1 (STORY_PROMPT_TEMPLATE, line 108)

Inside line 108, replace this exact substring (it occurs once in the file):

```
Introduce each character with a short referring phrase of at most four words, such as "the woman in grey", and use that exact phrase for them everywhere else in the file.
```

with this exact text:

```
Introduce each character with a referring phrase of at most four words built only from details you already gave them in this Image: field or that the narrative states, and use that exact phrase for them everywhere else in the file. Never add a colour, garment or trait just to make the phrase.
```

The closing `>` that ends the `Image:` placeholder still follows straight after it. Line 108 therefore ends `...just to make the phrase.>`. The new text has no `{` or `}`, so `str.format` in `build_story_prompt` is unaffected. (Checked: the formatted template contains the new sentence exactly once.)

### 1.2 Audit of the other template constants

| Constant | Referring-phrase text it contains | Change? | Why |
|---|---|---|---|
| `STORY_PROMPT_TEMPLATE` line 115 (later-panel `Motion:`) | "Name each character only by their referring phrase from Panel 1, word for word." | No | It refers to the phrase. It gives no example and gives no construction rule. |
| `STORY_PROMPT_TEMPLATE_NO_STILLS` | None. It uses the full-description VERBATIM rule (line 139) and has no referring phrase at all. | No | Nothing to anchor on. Its only quoted examples are the production-value phrases (FIX 2), the eyebrows example (kept, 0/47 leaks) and the negative label examples `"Camera:"`/`"Audio:"` (kept: these are forbidden strings, not content to copy). |
| `SEED_IMAGE_PREFACE` | "Choose each person's short referring phrase from what is actually visible." | No (per brief) | It is already grounded in observed detail. It agrees with E1: in seed mode the `Image:` field literally describes the visible image, so "details you already gave them in this Image: field" are the visible details. |
| `SEED_IMAGE_POSTFACE` | "characters are named only by their Panel 1 referring phrase." | No | It refers to the phrase. It gives no example. |

---

## 2. FIX 2: production-quality phrases of the model's own choosing (`bin/ltx-movie:141`)

### 2.1 Edit E2 (STORY_PROMPT_TEMPLATE_NO_STILLS, line 141)

Inside line 141, replace this exact sentence (it occurs once in the file):

```
Keep the wording plain and factual apart from at most two production-value phrases per panel such as "warm cinematic lighting", "film-grade color" or "crisp fine detail".
```

with this exact sentence:

```
Keep each panel's wording plain and factual apart from at most two short production-quality phrases of your own choosing that suit the narrative.
```

The rest of line 141 stays byte-identical. That includes the eyebrows example before this sentence and `Use no markdown and no inline labels such as "Camera:" or "Audio:".` after it.

The approved phrase does not say "per panel". "Keep each panel's wording" is added so the per-panel scope of the old sentence survives. [spec choice]

### 2.2 Must not change

The `Rules:` block at `bin/ltx-movie:124-127` must not change (the user declined that change). A11 in section 6 checks this mechanically.

---

## 3. FIX 3: the genre goal as a parameter (`--goal TEXT`)

### 3.1 Design decisions (all three judges)

D1. Placeholder mechanism: `str.replace` on the unique sentinel token `@@GOAL@@`, applied to a module-level `SYSTEM_PROMPT_TEMPLATE`.
- `%`-formatting would need every future literal `%` in the prompt escaped as `%%`. `str.format` would break on any literal `{`/`}`.
- With `str.replace`, a `%`, `{` or `}` in the template or in the user's goal is copied through as is. A goal that contains `@@GOAL@@` itself is inserted literally, because `str.replace` does not re-scan the text it inserts.
- The three current prompts contain no `%`, `{`, `}` or `@@` (checked).

D2. The token replaces exactly the goal phrase. The prompt keeps its own "The target output goal is " prefix and its own trailing `.`.

D3. `DEFAULT_GOAL` is each tool's exact current goal text:
- judge-story: `the most realistic action scenes possible, with relatively little dialogue` (74 characters)
- judge-stills: `the most realistic action scenes possible` (41 characters)
- judge-clips: `the most realistic action scenes possible` (41 characters)

D4. `SYSTEM_PROMPT` stays as a module-level name, now equal to `build_system_prompt(DEFAULT_GOAL)`. Existing tests (`kwargs["system"] == judge_X.SYSTEM_PROMPT`, `test_t8c_system_prompt_content`) keep passing unchanged. `main()` never sends `SYSTEM_PROMPT` directly: it always sends `build_system_prompt(goal)`.

D5. Validation runs in `parse_goal`, used as argparse `type=` for `--goal`. It applies only to a value the user supplied, because the default is `None`.
1. Strip surrounding whitespace (`str.strip()`).
2. If the result ends with `.`, remove that one `.` and `rstrip()` again. The template supplies its own full stop, so this prevents `..`.
3. If the result is empty, reject with `must not be empty`.
4. If it contains `\n` or `\r`, reject with `must be a single line`. The goal sits mid-sentence in the prompt.
5. If it is longer than `GOAL_MAX_CHARS = 300` characters, reject with `must be at most 300 characters (got N)`. 300 is about 4x the longest default (74), which is room for a two-clause goal. It still keeps the goal a phrase rather than a second prompt pushed into the system prompt.

A rejection raises `argparse.ArgumentTypeError`. argparse then prints `<prog>: error: argument --goal: <message>` and exits 2, which matches each tool's documented exit 2 for argument failures. It does so before any file is read, any subprocess runs, or any client is built. A goal that starts with `-` must be written `--goal=-...` (standard argparse behaviour). Nothing extra handles this.

D6. Output JSON: every successful run writes a `"goal"` key in its judgment file, placed immediately after `"effort"`. Its value is the normalized goal that went into the prompt, so `DEFAULT_GOAL` when `--goal` is omitted. The key is always present. The `*.raw.json` dumps, stdout and stderr do not change.

D7. "Byte-identical when the flag is omitted" covers the API request: system prompt, messages, tools and all other kwargs. The judgment JSON is not byte-identical: it gains the `"goal"` key (D6), as the brief requires.

D8. `parse_goal` and the three constants are duplicated in each judge, not shared. This matches the existing per-script style (judge-stills duplicates ltx-story-manifest's regexes rather than loading them; see its lines 62-63).

D9. The `rendering_quality` clause in judge-stills, "a flattened or overly stylized look where photorealism was intended", is NOT goal-dependent and does not change. It only fires where photorealism was intended. That intent comes from the goal and the panel text the judge receives, so under a stylized goal the clause does not apply, and under the default realistic goal it does. Rewording it would add a second placeholder and change behaviour for the default goal. [spec choice]

D10. One placeholder per prompt (brief). judge-story's "multi-panel, action-focused storyboard" sentence, its `action_plausibility` dimension name, and judge-clips' `physical_realism` "real footage" wording do not change. They describe the pipeline's panel format and fixed score keys (the schema and iterate-story's `SCORE_KEYS` depend on them), not the target look. [spec choice] See section 8.

### 3.2 bin/judge-story: exact edits

JS-1 (module docstring, Usage). Old:

```
Usage:
  bin/judge-story --story-id <id>               # generated/stories/<id>/story.md
  bin/judge-story --story-md <path/to/story.md>
```

New:

```
Usage:
  bin/judge-story --story-id <id>               # generated/stories/<id>/story.md
  bin/judge-story --story-md <path/to/story.md>
  Either form also takes --goal TEXT, which replaces DEFAULT_GOAL in the judge's
  system prompt; judgment.json records the goal used.
```

JS-2 (constants and template head). Old:

```
SYSTEM_PROMPT = (
    "You are an expert story editor judging a story written for an AI image-and-video "
    "generation pipeline. The story is intended to become a multi-panel, action-focused "
    "storyboard. The target output goal is the most realistic action scenes possible, with "
    "relatively little dialogue.\n"
```

New:

```
# The target output goal stated in the system prompt; --goal replaces it. With --goal
# omitted, the prompt sent is byte-identical to the constant this template replaced
# (spec 2026-10-05-prompt-anchoring-fixes.md section 3).
DEFAULT_GOAL = "the most realistic action scenes possible, with relatively little dialogue"
# Substituted with str.replace, never %-formatting or str.format, so a literal %, { or }
# in the template or in a goal needs no escaping.
GOAL_TOKEN = "@@GOAL@@"
GOAL_MAX_CHARS = 300

SYSTEM_PROMPT_TEMPLATE = (
    "You are an expert story editor judging a story written for an AI image-and-video "
    "generation pipeline. The story is intended to become a multi-panel, action-focused "
    "storyboard. The target output goal is @@GOAL@@.\n"
```

JS-3 (after the template's closing paren). Old:

```
    "put the judgment in a plain text reply; a response without a submit_judgment call is a "
    "failure."
)

RETRY_USER_MESSAGE = ("You did not call the submit_judgment tool. Call submit_judgment now "
                      "with your scores, critique, and revised_prompt. Do not reply with "
```

New:

```
    "put the judgment in a plain text reply; a response without a submit_judgment call is a "
    "failure."
)


def build_system_prompt(goal):
    """SYSTEM_PROMPT_TEMPLATE with its single GOAL_TOKEN replaced by goal, verbatim. Pure."""
    return SYSTEM_PROMPT_TEMPLATE.replace(GOAL_TOKEN, goal)


# The system prompt when --goal is omitted: byte-identical to the constant it replaced.
SYSTEM_PROMPT = build_system_prompt(DEFAULT_GOAL)

RETRY_USER_MESSAGE = ("You did not call the submit_judgment tool. Call submit_judgment now "
                      "with your scores, critique, and revised_prompt. Do not reply with "
```

JS-4 (new function, inserted immediately before `def build_parser():`, followed by two blank lines):

```python
def parse_goal(text):
    """argparse type= for --goal (spec 2026-10-05 section 3.1 D5). Strips surrounding
    whitespace and then one trailing "." (the prompt supplies its own), and rejects an
    empty result, a line break, or more than GOAL_MAX_CHARS characters. Returns the goal
    exactly as it is inserted into the system prompt."""
    goal = text.strip()
    if goal.endswith("."):
        goal = goal[:-1].rstrip()
    if not goal:
        raise argparse.ArgumentTypeError("must not be empty")
    if "\n" in goal or "\r" in goal:
        raise argparse.ArgumentTypeError("must be a single line")
    if len(goal) > GOAL_MAX_CHARS:
        raise argparse.ArgumentTypeError("must be at most %d characters (got %d)"
                                         % (GOAL_MAX_CHARS, len(goal)))
    return goal
```

JS-5 (parser). Old:

```
                       help="instruct the judge that revised_prompt must target exactly N "
                            "panels (used by bin/iterate-story to keep the panel count "
                            "stable across rounds)")
    return parser
```

New:

```
                       help="instruct the judge that revised_prompt must target exactly N "
                            "panels (used by bin/iterate-story to keep the panel count "
                            "stable across rounds)")
    parser.add_argument("--goal", dest="goal", type=parse_goal, default=None, metavar="TEXT",
                        help="the target output goal stated in the judge's system prompt, "
                             "worded to complete 'The target output goal is TEXT.' "
                             "(default: '" + DEFAULT_GOAL + "')")
    return parser
```

JS-6 (`_create_message`). Old:

```
def _create_message(client, messages):
    """One non-streaming judging call with the fixed spec 4.1 parameters. No temperature,
    top_k, or top_p: extended thinking rejects non-default values."""
    return client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": EFFORT},
        system=SYSTEM_PROMPT,
```

New:

```
def _create_message(client, system_prompt, messages):
    """One non-streaming judging call with the fixed spec 4.1 parameters and the given
    system prompt. No temperature, top_k, or top_p: extended thinking rejects non-default
    values."""
    return client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": EFFORT},
        system=system_prompt,
```

JS-7 (main: compute the goal). Old:

```
    user_message = build_user_message(story_md_text, story_prompt_text, args.target_panels)
    responses = []
    try:
        responses.append(_create_message(client, [{"role": "user", "content": user_message}]))
```

New:

```
    user_message = build_user_message(story_md_text, story_prompt_text, args.target_panels)
    goal = DEFAULT_GOAL if args.goal is None else args.goal
    system_prompt = build_system_prompt(goal)
    responses = []
    try:
        responses.append(_create_message(client, system_prompt,
                                         [{"role": "user", "content": user_message}]))
```

JS-8 (main: the retry call). Old: `            responses.append(_create_message(client, [`. New: `            responses.append(_create_message(client, system_prompt, [`.

JS-9 (judgment dict). Old:

```
        "effort": EFFORT,
        "timestamp": timestamp,
```

New:

```
        "effort": EFFORT,
        "goal": goal,
        "timestamp": timestamp,
```

### 3.3 bin/judge-stills: exact edits

JT-1 (docstring Usage). Old:

```
Usage:
  bin/judge-stills --story-id <id>    # generated/stories/<id>/images/ + story.md
```

New:

```
Usage:
  bin/judge-stills --story-id <id>    # generated/stories/<id>/images/ + story.md
  bin/judge-stills --story-id <id> --goal TEXT    # replace DEFAULT_GOAL in the system prompt
```

JT-2 (constants and template head). Old:

```
SYSTEM_PROMPT = (
    "You are an expert visual director judging the still images generated for a story by "
    "an AI image-and-video generation pipeline. Each still was generated by an image model "
    "from the text of one story panel. The target output goal is the most realistic action "
    "scenes possible.\n"
```

New:

```
# The target output goal stated in the system prompt; --goal replaces it. With --goal
# omitted, the prompt sent is byte-identical to the constant this template replaced
# (spec 2026-10-05-prompt-anchoring-fixes.md section 3).
DEFAULT_GOAL = "the most realistic action scenes possible"
# Substituted with str.replace, never %-formatting or str.format, so a literal %, { or }
# in the template or in a goal needs no escaping.
GOAL_TOKEN = "@@GOAL@@"
GOAL_MAX_CHARS = 300

SYSTEM_PROMPT_TEMPLATE = (
    "You are an expert visual director judging the still images generated for a story by "
    "an AI image-and-video generation pipeline. Each still was generated by an image model "
    "from the text of one story panel. The target output goal is @@GOAL@@.\n"
```

The `rendering_quality` lines (`"- rendering_quality: rendering artifacts, anatomical errors, loss of detail, a "` / `"flattened or overly stylized look where photorealism was intended, and general image "` / `"quality.\n"`) do not change (D9).

JT-3 (after the template). Old:

```
    "put the judgment in a plain text reply; a response without a submit_judgment call is a "
    "failure."
)

# Final text block of the user message; it states the stills count so the judge knows
```

New:

```
    "put the judgment in a plain text reply; a response without a submit_judgment call is a "
    "failure."
)


def build_system_prompt(goal):
    """SYSTEM_PROMPT_TEMPLATE with its single GOAL_TOKEN replaced by goal, verbatim. Pure."""
    return SYSTEM_PROMPT_TEMPLATE.replace(GOAL_TOKEN, goal)


# The system prompt when --goal is omitted: byte-identical to the constant it replaced.
SYSTEM_PROMPT = build_system_prompt(DEFAULT_GOAL)

# Final text block of the user message; it states the stills count so the judge knows
```

JT-4: insert the `parse_goal` function from JS-4, character for character, immediately before `def build_parser():`, followed by two blank lines.

JT-5 (parser). Old:

```
                        help="judge generated/stories/ID/images/panel_NN.png against "
                             "generated/stories/ID/story.md")
    return parser
```

New:

```
                        help="judge generated/stories/ID/images/panel_NN.png against "
                             "generated/stories/ID/story.md")
    parser.add_argument("--goal", dest="goal", type=parse_goal, default=None, metavar="TEXT",
                        help="the target output goal stated in the judge's system prompt, "
                             "worded to complete 'The target output goal is TEXT.' "
                             "(default: '" + DEFAULT_GOAL + "')")
    return parser
```

JT-6 (`_create_message`). Old:

```
def _create_message(client, messages):
    """One non-streaming judging call with the fixed spec 4.1 parameters. No temperature,
    top_k, or top_p, and no budget_tokens thinking shape (the live API rejects it)."""
    return client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": EFFORT},
        system=SYSTEM_PROMPT,
```

New:

```
def _create_message(client, system_prompt, messages):
    """One non-streaming judging call with the fixed spec 4.1 parameters and the given
    system prompt. No temperature, top_k, or top_p, and no budget_tokens thinking shape
    (the live API rejects it)."""
    return client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": EFFORT},
        system=system_prompt,
```

JT-7 (main: compute the goal). Old:

```
    client = anthropic.Anthropic()

    responses = []
    try:
        responses.append(_create_message(client, [{"role": "user", "content": user_content}]))
```

New:

```
    client = anthropic.Anthropic()
    goal = DEFAULT_GOAL if args.goal is None else args.goal
    system_prompt = build_system_prompt(goal)

    responses = []
    try:
        responses.append(_create_message(client, system_prompt,
                                         [{"role": "user", "content": user_content}]))
```

JT-8 (retry call). Old: `            responses.append(_create_message(client, [`. New: `            responses.append(_create_message(client, system_prompt, [`.

JT-9 (judgment dict). Old:

```
        "effort": EFFORT,
        "timestamp": timestamp,
```

New:

```
        "effort": EFFORT,
        "goal": goal,
        "timestamp": timestamp,
```

### 3.4 bin/judge-clips: exact edits

JC-1 (docstring Usage). Old:

```
Usage:
  bin/judge-clips --story-id <id>    # generated/stories/<id>/clips/ + manifest.json
```

New:

```
Usage:
  bin/judge-clips --story-id <id>    # generated/stories/<id>/clips/ + manifest.json
  bin/judge-clips --story-id <id> --goal TEXT    # replace DEFAULT_GOAL in the system prompt
```

JC-2 (constants and template head). Old:

```
SYSTEM_PROMPT = (
    "You are an expert film director and visual-effects supervisor judging the video clips "
    "generated for a story by an AI image-and-video generation pipeline. The target output "
    "goal is the most realistic action scenes possible.\n"
```

New:

```
# The target output goal stated in the system prompt; --goal replaces it. With --goal
# omitted, the prompt sent is byte-identical to the constant this template replaced
# (spec 2026-10-05-prompt-anchoring-fixes.md section 3).
DEFAULT_GOAL = "the most realistic action scenes possible"
# Substituted with str.replace, never %-formatting or str.format, so a literal %, { or }
# in the template or in a goal needs no escaping.
GOAL_TOKEN = "@@GOAL@@"
GOAL_MAX_CHARS = 300

SYSTEM_PROMPT_TEMPLATE = (
    "You are an expert film director and visual-effects supervisor judging the video clips "
    "generated for a story by an AI image-and-video generation pipeline. The target output "
    "goal is @@GOAL@@.\n"
```

JC-3 (after the template). Old:

```
    "put the judgment in a plain text reply; a response without a submit_judgment call is a "
    "failure."
)

# Final text block of the user message; it states the clip count so the judge knows
```

New:

```
    "put the judgment in a plain text reply; a response without a submit_judgment call is a "
    "failure."
)


def build_system_prompt(goal):
    """SYSTEM_PROMPT_TEMPLATE with its single GOAL_TOKEN replaced by goal, verbatim. Pure."""
    return SYSTEM_PROMPT_TEMPLATE.replace(GOAL_TOKEN, goal)


# The system prompt when --goal is omitted: byte-identical to the constant it replaced.
SYSTEM_PROMPT = build_system_prompt(DEFAULT_GOAL)

# Final text block of the user message; it states the clip count so the judge knows
```

JC-4: insert the `parse_goal` function from JS-4, character for character, immediately before `def build_parser():`, followed by two blank lines.

JC-5 (parser). Old:

```
                        help="judge generated/stories/ID/clips/panel_NN.mp4 against "
                             "generated/stories/ID/manifest.json")
    return parser
```

New:

```
                        help="judge generated/stories/ID/clips/panel_NN.mp4 against "
                             "generated/stories/ID/manifest.json")
    parser.add_argument("--goal", dest="goal", type=parse_goal, default=None, metavar="TEXT",
                        help="the target output goal stated in the judge's system prompt, "
                             "worded to complete 'The target output goal is TEXT.' "
                             "(default: '" + DEFAULT_GOAL + "')")
    return parser
```

JC-6 (`_create_message`). Old:

```
def _create_message(client, messages):
    return client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": EFFORT},
        system=SYSTEM_PROMPT,
```

New:

```
def _create_message(client, system_prompt, messages):
    return client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": EFFORT},
        system=system_prompt,
```

JC-7 (main: compute the goal). Old:

```
    user_content = build_user_content(clip_inputs)
    client = anthropic.Anthropic()

    responses = []
    try:
        responses.append(_create_message(client, [{"role": "user", "content": user_content}]))
```

New:

```
    user_content = build_user_content(clip_inputs)
    client = anthropic.Anthropic()
    goal = DEFAULT_GOAL if args.goal is None else args.goal
    system_prompt = build_system_prompt(goal)

    responses = []
    try:
        responses.append(_create_message(client, system_prompt,
                                         [{"role": "user", "content": user_content}]))
```

JC-8 (retry call). Old: `            responses.append(_create_message(client, [`. New: `            responses.append(_create_message(client, system_prompt, [`.

JC-9 (judgment dict). Old:

```
        "effort": EFFORT,
        "timestamp": timestamp,
        "frames_per_clip": FRAMES_PER_CLIP,
```

New:

```
        "effort": EFFORT,
        "goal": goal,
        "timestamp": timestamp,
        "frames_per_clip": FRAMES_PER_CLIP,
```

### 3.5 bin/iterate-story: exact edits

Decisions:
- I1. iterate-story passes `--goal` through verbatim (no strip, no validation) and only when the user gave it (`is not None`, so an explicit `--goal ""` is passed too). judge-story is the only place that validates, so the rules live in one tool. An invalid goal makes round 1's judge-story exit 2 before any API call. iterate-story then reports `judge-story failed` (exit 1, live files unchanged, the judge's argparse error in the output tail) through its existing failure path. [spec choice]
- I2. `--goal` is not passed to `ltx-movie`, which has no goal concept.
- I3. `run-summary.json` does not change (keys stay `stop_reason`, `best_round`, `rounds`). The goal is already recorded in each round's archived `judgment.vN.json` (`"goal"` key, D6), and `iterate-story.log` already writes the full judge argv (`cmd: %r`), which includes `--goal`. Adding it to the summary would duplicate it. [spec choice]

IS-1 (docstring Usage). Old: `  bin/iterate-story --story-id <id> --threshold <N> [--max-rounds <N>]`. New: `  bin/iterate-story --story-id <id> --threshold <N> [--max-rounds <N>] [--goal TEXT]`.

IS-2 (parser). Old:

```
                        help="passed through to bin/ltx-movie's --story-context-window on "
                             "every regeneration call")
    return parser
```

New:

```
                        help="passed through to bin/ltx-movie's --story-context-window on "
                             "every regeneration call")
    parser.add_argument("--goal", dest="goal", default=None, metavar="TEXT",
                        help="passed through verbatim to bin/judge-story's --goal on every "
                             "judging call; bin/judge-story validates it")
    return parser
```

IS-3 (`build_judge_cmd`). Old:

```
def build_judge_cmd(story_id, target_panels):
    """bin/judge-story argv (spec 3.4.1, extended). Passes --target-panels so the judge
    builds its revised_prompt's beat plan for the pinned count from the start, instead of
    proposing a different count that then has to be patched after the fact."""
    return [sys.executable, os.path.join(WS, "bin", "judge-story"), "--story-id", story_id,
            "--target-panels", str(target_panels)]
```

New:

```
def build_judge_cmd(story_id, target_panels, goal=None):
    """bin/judge-story argv (spec 3.4.1, extended). Passes --target-panels so the judge
    builds its revised_prompt's beat plan for the pinned count from the start, instead of
    proposing a different count that then has to be patched after the fact. --goal is
    appended verbatim only when given, so the argv is unchanged for a caller that omits it."""
    cmd = [sys.executable, os.path.join(WS, "bin", "judge-story"), "--story-id", story_id,
           "--target-panels", str(target_panels)]
    if goal is not None:
        cmd += ["--goal", goal]
    return cmd
```

IS-4 (main). Old: `        judge_cmd = build_judge_cmd(args.story_id, pinned_panel_count)`. New: `        judge_cmd = build_judge_cmd(args.story_id, pinned_panel_count, args.goal)`.

---

## 4. Tests

General rules:
- Plain pytest asserts only (no `check()`), except in `tests/test_ltx_movie_offline.py`, which uses its own `check()` and is run directly, never through pytest.
- New pytest functions are named `test_goal_*` and carry no spec test ID. Like the existing `test_target_panels_optional` and `test_story_model_and_context_window_passthrough`, they extend the earlier specs' test-ID sets, so the "(N total)" counts in the test-file docstrings (which count spec test IDs) do not change.
- No test makes a network call. The existing autouse `_no_real_client` / `_no_real_subprocess` fixtures stay in force.

### 4.1 tests/test_ltx_movie_offline.py (+4 checks)

LT-1: in `test_story_prompt_template()`, append after the `L5j` check (the last statement of the function):

```python
    new_phrase_rule = ("Introduce each character with a referring phrase of at most four words "
                       "built only from details you already gave them in this Image: field or "
                       "that the narrative states, and use that exact phrase for them "
                       "everywhere else in the file. Never add a colour, garment or trait just "
                       "to make the phrase.")
    check("L5k the referring-phrase rule builds the phrase only from given details",
          new_phrase_rule in prompt, "got %r" % prompt[:1800])
    every_prompt = [ltx_movie.build_story_prompt("n", "sid", 3, no_stills, seed_image, seconds="6")
                    for no_stills in (False, True) for seed_image in (False, True)]
    check("L5l no story prompt carries the copied 'woman in grey' example",
          all("woman in grey" not in p for p in every_prompt))
```

LT-2: in `test_no_stills_story_prompt_template()`, append after the `L15k` check (the last statement of the function):

```python
    check("L15y the production-quality phrases are the model's own choice",
          "Keep each panel's wording plain and factual apart from at most two short "
          "production-quality phrases of your own choosing that suit the narrative." in p,
          "got %r" % p[-1400:])
    every_prompt = [ltx_movie.build_story_prompt("n", "sid", 3, no_stills, seed_image, seconds="6")
                    for no_stills in (False, True) for seed_image in (False, True)]
    check("L15z no story prompt names a fixed production-value phrase",
          all(s not in q for q in every_prompt
              for s in ("warm cinematic lighting", "film-grade color", "crisp fine detail",
                        "production-value")))
```

`L47` (every top-level `test_*` is called from `__main__`) is unaffected because no new top-level function is added.

### 4.2 tests/test_judge_story.py (1 modified, +3 new)

JST-0 (imports). Old: `import copy\nimport importlib.machinery`. New: `import copy\nimport hashlib\nimport importlib.machinery`.

JST-M (modify `test_t7_successful_run`). Old:

```
    assert list(judgment) == ["story_md_path", "story_prompt_path", "model",
                              "effort", "timestamp", "usage", "scores",
                              "critique", "revised_prompt"]
```

New:

```
    assert list(judgment) == ["story_md_path", "story_prompt_path", "model",
                              "effort", "goal", "timestamp", "usage", "scores",
                              "critique", "revised_prompt"]
    assert judgment["goal"] == judge_story.DEFAULT_GOAL
```

JST-N (append at end of file):

```python


# --- --goal: the target output goal as a parameter (spec 2026-10-05 section 3) --------

# sha256 of the SYSTEM_PROMPT constant at commit 1d8580b, before --goal existed (2223 chars).
LEGACY_SYSTEM_PROMPT_SHA256 = "39be908ef72c563313398c1a0f1ff4a69bd948a0e5f90c030aaea879694cb97b"
# "%" and "{...}" prove the goal is inserted verbatim, never formatted.
CUSTOM_GOAL = "a quiet 100% {literal} drama, mostly dialogue"


def test_goal_default_prompt_byte_identical():
    assert judge_story.DEFAULT_GOAL == ("the most realistic action scenes possible, with "
                                        "relatively little dialogue")
    assert judge_story.GOAL_TOKEN == "@@GOAL@@"
    assert judge_story.GOAL_MAX_CHARS == 300
    assert judge_story.SYSTEM_PROMPT_TEMPLATE.count(judge_story.GOAL_TOKEN) == 1
    rendered = judge_story.build_system_prompt(judge_story.DEFAULT_GOAL)
    assert rendered == judge_story.SYSTEM_PROMPT
    assert len(rendered) == 2223
    assert hashlib.sha256(rendered.encode("utf-8")).hexdigest() == LEGACY_SYSTEM_PROMPT_SHA256
    assert ("The target output goal is the most realistic action scenes possible, with "
            "relatively little dialogue.\n") in rendered


def test_goal_custom_rendering_and_validation(capsys):
    rendered = judge_story.build_system_prompt(CUSTOM_GOAL)
    assert "The target output goal is " + CUSTOM_GOAL + ".\n" in rendered
    assert judge_story.GOAL_TOKEN not in rendered
    assert judge_story.DEFAULT_GOAL not in rendered
    # Only the goal differs: every other byte of the default prompt is kept.
    assert rendered == judge_story.SYSTEM_PROMPT.replace(judge_story.DEFAULT_GOAL, CUSTOM_GOAL)
    parse = judge_story.build_parser().parse_args
    assert parse(["--story-id", "x"]).goal is None
    assert parse(["--story-id", "x", "--goal", CUSTOM_GOAL]).goal == CUSTOM_GOAL
    assert parse(["--story-id", "x", "--goal", "  calm drama.  "]).goal == "calm drama"
    assert parse(["--story-id", "x", "--goal", "x" * 300]).goal == "x" * 300
    for bad, message in (("", "must not be empty"), ("   ", "must not be empty"),
                         (" . ", "must not be empty"),
                         ("two\nlines", "must be a single line"),
                         ("two\rlines", "must be a single line"),
                         ("x" * 301, "must be at most 300 characters (got 301)")):
        with pytest.raises(SystemExit) as exc:
            parse(["--story-id", "x", "--goal", bad])
        assert exc.value.code == 2, repr(bad)
        assert "argument --goal: " + message in capsys.readouterr().err, repr(bad)
    helptext = " ".join(judge_story.build_parser().format_help().split())
    assert judge_story.DEFAULT_GOAL in helptext


def test_goal_reaches_api_and_judgment(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)

    # --goal omitted: the legacy prompt is sent and the default goal is recorded.
    default_dir = tmp_path / "default"
    story_md = _make_story(default_dir)
    fake = _install_fake(monkeypatch, [
        _tool_response(copy.deepcopy(VALID_INPUT), _usage(10, 20, 5))])
    assert judge_story.main(["--story-md", str(story_md)]) == 0
    assert fake.calls[0]["system"] == judge_story.SYSTEM_PROMPT
    with open(default_dir / "judgment.json", encoding="utf-8") as f:
        assert json.load(f)["goal"] == judge_story.DEFAULT_GOAL

    # --goal given: the normalized goal reaches the first call AND the retry, and
    # judgment.json records exactly the text that was inserted.
    custom_dir = tmp_path / "custom"
    story_md = _make_story(custom_dir)
    fake = _install_fake(monkeypatch, [
        _text_response("Prose only.", _usage(10, 20, None)),
        _tool_response(copy.deepcopy(VALID_INPUT), _usage(10, 20, 5))])
    assert judge_story.main(["--story-md", str(story_md),
                             "--goal", " " + CUSTOM_GOAL + ". "]) == 0
    assert len(fake.calls) == 2
    for call in fake.calls:
        assert call["system"] == judge_story.build_system_prompt(CUSTOM_GOAL)
    with open(custom_dir / "judgment.json", encoding="utf-8") as f:
        judgment = json.load(f)
    assert list(judgment)[3:5] == ["effort", "goal"]
    assert judgment["goal"] == CUSTOM_GOAL
    capsys.readouterr()

    # An invalid --goal exits 2 before any file is read or written or any client exists.
    bad_dir = tmp_path / "bad"
    story_md = _make_story(bad_dir)
    fake = _install_fake(monkeypatch, [])
    with pytest.raises(SystemExit) as exc:
        judge_story.main(["--story-md", str(story_md), "--goal", "   "])
    assert exc.value.code == 2
    assert fake.constructions == []
    assert sorted(os.listdir(bad_dir)) == ["story.md", "story_prompt.txt"]
    assert "argument --goal: must not be empty" in capsys.readouterr().err
```

### 4.3 tests/test_judge_stills.py (1 modified, +3 new)

JTT-0 (imports). Old: `import copy\nimport importlib.machinery`. New: `import copy\nimport hashlib\nimport importlib.machinery`.

JTT-M (modify `test_t10_successful_run_two_stills`). Old:

```
    assert list(judgment) == ["story_id", "model", "effort", "timestamp", "usage",
                              "scores", "critique"]
```

New:

```
    assert list(judgment) == ["story_id", "model", "effort", "goal", "timestamp", "usage",
                              "scores", "critique"]
    assert judgment["goal"] == judge_stills.DEFAULT_GOAL
```

JTT-N (append at end of file):

```python


# --- --goal: the target output goal as a parameter (spec 2026-10-05 section 3) --------

# sha256 of the SYSTEM_PROMPT constant at commit 1d8580b, before --goal existed (1957 chars).
LEGACY_SYSTEM_PROMPT_SHA256 = "6b102caf47750da8767f3fbcb6d875111221afea2f5594775ab14b88e1cd1cd1"
# "%" and "{...}" prove the goal is inserted verbatim, never formatted.
CUSTOM_GOAL = "a hand-painted 100% {literal} watercolour storybook look"


def test_goal_default_prompt_byte_identical():
    assert judge_stills.DEFAULT_GOAL == "the most realistic action scenes possible"
    assert judge_stills.GOAL_TOKEN == "@@GOAL@@"
    assert judge_stills.GOAL_MAX_CHARS == 300
    assert judge_stills.SYSTEM_PROMPT_TEMPLATE.count(judge_stills.GOAL_TOKEN) == 1
    rendered = judge_stills.build_system_prompt(judge_stills.DEFAULT_GOAL)
    assert rendered == judge_stills.SYSTEM_PROMPT
    assert len(rendered) == 1957
    assert hashlib.sha256(rendered.encode("utf-8")).hexdigest() == LEGACY_SYSTEM_PROMPT_SHA256
    assert "The target output goal is the most realistic action scenes possible.\n" in rendered


def test_goal_custom_rendering_and_validation(capsys):
    rendered = judge_stills.build_system_prompt(CUSTOM_GOAL)
    assert "The target output goal is " + CUSTOM_GOAL + ".\n" in rendered
    assert judge_stills.GOAL_TOKEN not in rendered
    assert judge_stills.DEFAULT_GOAL not in rendered
    assert rendered == judge_stills.SYSTEM_PROMPT.replace(judge_stills.DEFAULT_GOAL, CUSTOM_GOAL)
    # The rendering_quality clause is conditional on intent, so it is kept unchanged
    # under every goal (spec 2026-10-05 section 3.1 D9).
    assert "a flattened or overly stylized look where photorealism was intended" in rendered
    parse = judge_stills.build_parser().parse_args
    assert parse(["--story-id", "x"]).goal is None
    assert parse(["--story-id", "x", "--goal", CUSTOM_GOAL]).goal == CUSTOM_GOAL
    assert parse(["--story-id", "x", "--goal", "  calm drama.  "]).goal == "calm drama"
    assert parse(["--story-id", "x", "--goal", "x" * 300]).goal == "x" * 300
    for bad, message in (("", "must not be empty"), ("   ", "must not be empty"),
                         (" . ", "must not be empty"),
                         ("two\nlines", "must be a single line"),
                         ("two\rlines", "must be a single line"),
                         ("x" * 301, "must be at most 300 characters (got 301)")):
        with pytest.raises(SystemExit) as exc:
            parse(["--story-id", "x", "--goal", bad])
        assert exc.value.code == 2, repr(bad)
        assert "argument --goal: " + message in capsys.readouterr().err, repr(bad)
    helptext = " ".join(judge_stills.build_parser().format_help().split())
    assert judge_stills.DEFAULT_GOAL in helptext


def test_goal_reaches_api_and_judgment(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)

    # --goal omitted: the legacy prompt is sent and the default goal is recorded.
    default_dir = _make_story(tmp_path, monkeypatch, story_id="goal-default")
    fake = _install_fake(monkeypatch, [
        _tool_response(copy.deepcopy(VALID_INPUT), _usage(10, 20, 5))])
    assert judge_stills.main(["--story-id", "goal-default"]) == 0
    assert fake.calls[0]["system"] == judge_stills.SYSTEM_PROMPT
    with open(default_dir / "stills_judgment.json", encoding="utf-8") as f:
        assert json.load(f)["goal"] == judge_stills.DEFAULT_GOAL

    # --goal given: the normalized goal reaches the first call AND the retry, and
    # stills_judgment.json records exactly the text that was inserted.
    custom_dir = _make_story(tmp_path, monkeypatch, story_id="goal-custom")
    fake = _install_fake(monkeypatch, [
        _text_response("Prose only.", _usage(10, 20, None)),
        _tool_response(copy.deepcopy(VALID_INPUT), _usage(10, 20, 5))])
    assert judge_stills.main(["--story-id", "goal-custom",
                              "--goal", " " + CUSTOM_GOAL + ". "]) == 0
    assert len(fake.calls) == 2
    for call in fake.calls:
        assert call["system"] == judge_stills.build_system_prompt(CUSTOM_GOAL)
    with open(custom_dir / "stills_judgment.json", encoding="utf-8") as f:
        judgment = json.load(f)
    assert list(judgment)[2:4] == ["effort", "goal"]
    assert judgment["goal"] == CUSTOM_GOAL
    capsys.readouterr()

    # An invalid --goal exits 2 before any file is read or written or any client exists.
    bad_dir = _make_story(tmp_path, monkeypatch, story_id="goal-bad")
    before = _listing(bad_dir)
    fake = _install_fake(monkeypatch, [])
    with pytest.raises(SystemExit) as exc:
        judge_stills.main(["--story-id", "goal-bad", "--goal", "   "])
    assert exc.value.code == 2
    assert fake.constructions == []
    assert _listing(bad_dir) == before
    assert "argument --goal: must not be empty" in capsys.readouterr().err
```

### 4.4 tests/test_judge_clips.py (1 modified, +3 new; `test_t8c` unchanged)

`test_t8c_system_prompt_content` (line 490) stays unchanged and keeps passing: it asserts `"the most realistic action scenes possible"` is in `judge_clips.SYSTEM_PROMPT`, which is now the default-goal rendering (D4).

JCT-0 (imports). Old: `import fractions\nimport importlib.machinery`. New: `import fractions\nimport hashlib\nimport importlib.machinery`.

JCT-M (modify `test_t17_successful_run_two_clips`). Old:

```
    assert list(judgment) == ["story_id", "model", "effort", "timestamp", "frames_per_clip",
                              "usage", "clips", "movie", "critique"]
```

New:

```
    assert list(judgment) == ["story_id", "model", "effort", "goal", "timestamp",
                              "frames_per_clip", "usage", "clips", "movie", "critique"]
    assert judgment["goal"] == judge_clips.DEFAULT_GOAL
```

JCT-N (append at end of file):

```python


# --- --goal: the target output goal as a parameter (spec 2026-10-05 section 3) --------

# sha256 of the SYSTEM_PROMPT constant at commit 1d8580b, before --goal existed (3166 chars).
LEGACY_SYSTEM_PROMPT_SHA256 = "ac604f73c470bae702f8380aab81418258ea9cc3e9db75f26a319f2342594c3d"
# "%" and "{...}" prove the goal is inserted verbatim, never formatted.
CUSTOM_GOAL = "a slow 100% {literal} dialogue-driven drama"


def test_goal_default_prompt_byte_identical():
    assert judge_clips.DEFAULT_GOAL == "the most realistic action scenes possible"
    assert judge_clips.GOAL_TOKEN == "@@GOAL@@"
    assert judge_clips.GOAL_MAX_CHARS == 300
    assert judge_clips.SYSTEM_PROMPT_TEMPLATE.count(judge_clips.GOAL_TOKEN) == 1
    rendered = judge_clips.build_system_prompt(judge_clips.DEFAULT_GOAL)
    assert rendered == judge_clips.SYSTEM_PROMPT
    assert len(rendered) == 3166
    assert hashlib.sha256(rendered.encode("utf-8")).hexdigest() == LEGACY_SYSTEM_PROMPT_SHA256
    assert "The target output goal is the most realistic action scenes possible.\n" in rendered


def test_goal_custom_rendering_and_validation(capsys):
    rendered = judge_clips.build_system_prompt(CUSTOM_GOAL)
    assert "The target output goal is " + CUSTOM_GOAL + ".\n" in rendered
    assert judge_clips.GOAL_TOKEN not in rendered
    assert judge_clips.DEFAULT_GOAL not in rendered
    assert rendered == judge_clips.SYSTEM_PROMPT.replace(judge_clips.DEFAULT_GOAL, CUSTOM_GOAL)
    parse = judge_clips.build_parser().parse_args
    assert parse(["--story-id", "x"]).goal is None
    assert parse(["--story-id", "x", "--goal", CUSTOM_GOAL]).goal == CUSTOM_GOAL
    assert parse(["--story-id", "x", "--goal", "  calm drama.  "]).goal == "calm drama"
    assert parse(["--story-id", "x", "--goal", "x" * 300]).goal == "x" * 300
    for bad, message in (("", "must not be empty"), ("   ", "must not be empty"),
                         (" . ", "must not be empty"),
                         ("two\nlines", "must be a single line"),
                         ("two\rlines", "must be a single line"),
                         ("x" * 301, "must be at most 300 characters (got 301)")):
        with pytest.raises(SystemExit) as exc:
            parse(["--story-id", "x", "--goal", bad])
        assert exc.value.code == 2, repr(bad)
        assert "argument --goal: " + message in capsys.readouterr().err, repr(bad)
    helptext = " ".join(judge_clips.build_parser().format_help().split())
    assert judge_clips.DEFAULT_GOAL in helptext


def test_goal_reaches_api_and_judgment(tmp_path, monkeypatch, capsys, synthetic_clips):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)

    # --goal omitted: the legacy prompt is sent and the default goal is recorded.
    default_dir = _make_story(tmp_path, monkeypatch, manifest=_manifest([PANEL_1]),
                              clips={1: 1}, story_id="goal-default", synthetic=synthetic_clips)
    fake = _install_fake(monkeypatch, [
        _tool_response(copy.deepcopy(ONE_CLIP_INPUT), _usage(10, 20, 5))])
    assert judge_clips.main(["--story-id", "goal-default"]) == 0
    assert fake.calls[0]["system"] == judge_clips.SYSTEM_PROMPT
    with open(default_dir / "clips_judgment.json", encoding="utf-8") as f:
        assert json.load(f)["goal"] == judge_clips.DEFAULT_GOAL

    # --goal given: the normalized goal reaches the first call AND the retry, and
    # clips_judgment.json records exactly the text that was inserted.
    custom_dir = _make_story(tmp_path, monkeypatch, manifest=_manifest([PANEL_1]),
                             clips={1: 1}, story_id="goal-custom", synthetic=synthetic_clips)
    fake = _install_fake(monkeypatch, [
        _text_response("Prose only.", _usage(10, 20, None)),
        _tool_response(copy.deepcopy(ONE_CLIP_INPUT), _usage(10, 20, 5))])
    assert judge_clips.main(["--story-id", "goal-custom",
                             "--goal", " " + CUSTOM_GOAL + ". "]) == 0
    assert len(fake.calls) == 2
    for call in fake.calls:
        assert call["system"] == judge_clips.build_system_prompt(CUSTOM_GOAL)
    with open(custom_dir / "clips_judgment.json", encoding="utf-8") as f:
        judgment = json.load(f)
    assert list(judgment)[2:4] == ["effort", "goal"]
    assert judgment["goal"] == CUSTOM_GOAL
    capsys.readouterr()

    # An invalid --goal exits 2 before any check, subprocess, temp dir or client.
    bad_dir = _make_story(tmp_path, monkeypatch, manifest=_manifest([PANEL_1]),
                          clips={1: _dummy(1)}, story_id="goal-bad")
    before = _listing(bad_dir)
    _no_subprocess(monkeypatch)
    _no_tempdir(monkeypatch)
    fake = _install_fake(monkeypatch, [])
    with pytest.raises(SystemExit) as exc:
        judge_clips.main(["--story-id", "goal-bad", "--goal", "   "])
    assert exc.value.code == 2
    assert fake.constructions == []
    assert _listing(bad_dir) == before
    assert "argument --goal: must not be empty" in capsys.readouterr().err
```

### 4.5 tests/test_iterate_story.py (+1 new)

ITT-N (append at end of file):

```python


def test_goal_passthrough_to_every_judge_call(tmp_path, monkeypatch):
    # spec 2026-10-05 section 3.5: --goal reaches every judge-story call verbatim and no
    # ltx-movie call; omitted, every argv is unchanged (test_tm2 pins that exact argv).
    story_dir = _make_story(tmp_path, monkeypatch)
    fake = FakeRun(story_dir, [(4, 4, 4, 4), (7, 7, 7, 7)])
    monkeypatch.setattr(iterate_story.subprocess, "run", fake)
    assert iterate_story.main(["--story-id", STORY_ID, "--threshold", "7",
                               "--goal", "a quiet 100% drama"]) == 0
    judge_calls = [cmd for cmd, _ in fake.calls if os.path.basename(cmd[1]) == "judge-story"]
    ltx_calls = [cmd for cmd, _ in fake.calls if os.path.basename(cmd[1]) == "ltx-movie"]
    assert (len(judge_calls), len(ltx_calls)) == (2, 1)
    expected = [sys.executable, os.path.join(iterate_story.WS, "bin", "judge-story"),
                "--story-id", STORY_ID, "--target-panels", str(PINNED),
                "--goal", "a quiet 100% drama"]
    assert judge_calls == [expected, expected]
    assert "--goal" not in ltx_calls[0]
    with open(os.path.join(story_dir, iterate_story.LOG_FILE_NAME), encoding="utf-8") as f:
        assert f.read().count("'--goal', 'a quiet 100% drama'") == 2
    assert list(_summary(story_dir)) == ["stop_reason", "best_round", "rounds"]
    # Passed verbatim (judge-story normalizes and validates), and only when given.
    assert iterate_story.build_parser().parse_args(
        ["--story-id", "x", "--threshold", "7"]).goal is None
    assert iterate_story.build_judge_cmd("s", 3)[-2:] == ["--target-panels", "3"]
    assert iterate_story.build_judge_cmd("s", 3, " x. ")[-2:] == ["--goal", " x. "]
    assert iterate_story.build_judge_cmd("s", 3, "")[-2:] == ["--goal", ""]
```

---

## 5. Mutation table

Each row is a deliberate break, applied alone to the finished implementation and then reverted. A row passes when at least one listed test FAILS. Run the listed suite after each mutation. For the offline file, run `python3 tests/test_ltx_movie_offline.py` directly; a FAIL line plus exit 1 is the catch.

| # | File | Deliberate break | Must be caught by |
|---|---|---|---|
| M1 | bin/ltx-movie | Revert E1 (restore the "the woman in grey" sentence) | L5k, L5l |
| M2 | bin/ltx-movie | Keep E1 but delete ` Never add a colour, garment or trait just to make the phrase.` | L5k |
| M3 | bin/ltx-movie | Keep E1 and append ` such as "the woman in grey"` before the closing `>` | L5l |
| M4 | bin/ltx-movie | Revert E2 (restore the three fixed phrases) | L15y, L15z |
| M5 | bin/ltx-movie | Keep E2 and append ` such as "film-grade color"` before its full stop | L15z |
| M6 | bin/judge-story | Change `DEFAULT_GOAL` (drop `, with relatively little dialogue`) | test_goal_default_prompt_byte_identical |
| M7 | bin/judge-story | Template: drop the `.` after `@@GOAL@@` | test_goal_default_prompt_byte_identical, test_goal_custom_rendering_and_validation |
| M8 | bin/judge-story | Template keeps the old goal text AND adds the token after it | test_goal_default_prompt_byte_identical (hash), test_goal_custom_rendering_and_validation |
| M9 | bin/judge-story | `main` sends `SYSTEM_PROMPT` instead of `system_prompt` on the first call | test_goal_reaches_api_and_judgment |
| M10 | bin/judge-story | Retry call passes `build_system_prompt(DEFAULT_GOAL)` | test_goal_reaches_api_and_judgment |
| M11 | bin/judge-story | Remove `"goal": goal,` from the judgment dict | test_t7_successful_run, test_goal_reaches_api_and_judgment |
| M12 | bin/judge-story | Move `"goal"` after `"timestamp"` | test_t7_successful_run, test_goal_reaches_api_and_judgment |
| M13 | bin/judge-story | Record `args.goal` (None when omitted) instead of `goal` | test_t7_successful_run, test_goal_reaches_api_and_judgment |
| M14 | bin/judge-story | `parse_goal`: delete the trailing-"." removal | test_goal_custom_rendering_and_validation, test_goal_reaches_api_and_judgment |
| M15 | bin/judge-story | `parse_goal`: `>` changed to `>=` in the length check | test_goal_custom_rendering_and_validation |
| M16 | bin/judge-story | `parse_goal`: delete the line-break check | test_goal_custom_rendering_and_validation |
| M17 | bin/judge-story | Remove `type=parse_goal` from `--goal` | test_goal_custom_rendering_and_validation, test_goal_reaches_api_and_judgment |
| M18 | bin/judge-story | Help string drops the `(default: ...)` part | test_goal_custom_rendering_and_validation |
| M19 | bin/judge-stills | M6, M7, M9, M10, M11, M12, M14, M17 applied to judge-stills (one at a time) | the same-named judge-stills tests (test_t10_successful_run_two_stills in place of test_t7) |
| M20 | bin/judge-stills | Reword the `rendering_quality` clause | test_goal_default_prompt_byte_identical, test_goal_custom_rendering_and_validation |
| M21 | bin/judge-clips | M6, M7, M9, M10, M11, M12, M14, M17 applied to judge-clips (one at a time) | the same-named judge-clips tests (test_t17_successful_run_two_clips in place of test_t7) |
| M22 | bin/iterate-story | `build_judge_cmd` ignores `goal` | test_goal_passthrough_to_every_judge_call |
| M23 | bin/iterate-story | Always append `["--goal", str(goal)]` | test_tm2_subprocess_argv_and_override_file |
| M24 | bin/iterate-story | `if goal:` instead of `if goal is not None:` | test_goal_passthrough_to_every_judge_call |
| M25 | bin/iterate-story | `main` passes `args.goal` only when `round_number == 1` | test_goal_passthrough_to_every_judge_call |
| M26 | bin/iterate-story | `main` also passes `args.goal` to `build_ltx_movie_cmd`, which appends `["--goal", goal]` when it is not None | test_goal_passthrough_to_every_judge_call |
| M27 | bin/iterate-story | `build_judge_cmd` strips the goal (`goal.strip()`) | test_goal_passthrough_to_every_judge_call |

---

## 6. Acceptance commands

Run every command from WS (`cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace`). All of them are offline and light: no GPU, no server, no network. Do not start any render, server or story generation; a GPU render may be running.

| ID | Command | Before (HEAD 1d8580b) | After |
|---|---|---|---|
| A1 | `python3 -m pytest -q tests/test_judge_clips.py` | 55 passed | 58 passed |
| A2 | `python3 -m pytest -q tests/test_judge_stills.py` | 32 passed | 35 passed |
| A3 | `python3 -m pytest -q tests/test_judge_story.py` | 19 passed | 22 passed |
| A4 | `python3 -m pytest -q tests/test_iterate_story.py` | 17 passed | 18 passed |
| A5 | `python3 -m pytest -q tests/test_pipeline_log.py` | 17 passed | 17 passed |
| A6 | `python3 tests/test_ltx_movie_offline.py; echo rc=$?` (direct, NEVER via pytest) | `OK 340/340`, rc=0 | `OK 344/344`, rc=0 |
| A7 | `python3 tests/test_ltx_story_images.py; echo rc=$?` | `OK 101/101`, rc=0 | `OK 101/101`, rc=0 |
| A8 | `python3 -m pytest -q tests/test_deploy_pkg.py` and `/usr/bin/python3 tests/test_deploy_pkg.py` | 165 passed / Ran 165, OK | unchanged: 165 / 165 |

Read the count from the command's own output. For A6/A7, `echo rc=$?` must immediately follow the script, not a pipe.

A11 (mechanical diff check for SC1 and section 2.2): `git diff 1d8580b -- bin/ltx-movie | grep -c '^[-+][^-+]'` prints `4` (two removed lines, two added lines), and `git diff 1d8580b -- bin/ltx-movie | grep -n 'Explicit content\|explicit content\|descripibe'` prints nothing.

A9 (SC3, independent of the new tests). It loads the pre-change files from git and compares:

```bash
for t in judge-story judge-stills judge-clips; do git show 1d8580b:./bin/$t > /private/tmp/old_$t.py; done && python3 - <<'EOF'
import importlib.machinery, os, sys
sys.path.insert(0, os.getcwd())
for t in ("judge-story", "judge-stills", "judge-clips"):
    old = importlib.machinery.SourceFileLoader("old_" + t.replace("-", "_"), "/private/tmp/old_%s.py" % t).load_module()
    new = importlib.machinery.SourceFileLoader("new_" + t.replace("-", "_"), "bin/" + t).load_module()
    assert new.build_system_prompt(new.DEFAULT_GOAL) == old.SYSTEM_PROMPT, t
    assert new.SYSTEM_PROMPT == old.SYSTEM_PROMPT, t
    print(t, "byte-identical")
EOF
```

Expected output: three lines, `judge-story byte-identical`, `judge-stills byte-identical`, `judge-clips byte-identical`. (The loading part was checked against the current tree when this spec was written.)

A10 (D5 spot check with the CLI): `bin/judge-story --story-id goal-check-nonexistent --goal ''; echo rc=$?` prints `judge-story: error: argument --goal: must not be empty` and `rc=2`. The same holds for `bin/judge-stills` and `bin/judge-clips`, with the prog name changed. None of them makes a network call (argparse exits first).

### 6.1 Commits

Make three commits on `qwen-agent-redteam`. Stage ONLY the named files with `git add <path>`. The tree has unrelated dirty files (`bin/ltx-story-video`, `bin/qwen-agent`, `ltx_video_skill.py`, ...) that must stay unstaged. Before each commit, run `git diff --cached --stat` and confirm it lists exactly the files named for that commit.

1. `ltx-movie: build referring phrases only from given details; let the model choose production-quality phrases` with `bin/ltx-movie` and `tests/test_ltx_movie_offline.py`.
2. `judges: add --goal to judge-story, judge-stills, judge-clips; record it in the judgment JSON` with the three `bin/judge-*` files and the three `tests/test_judge_*.py` files.
3. `iterate-story: pass --goal through to every judge-story call` with `bin/iterate-story` and `tests/test_iterate_story.py`.

Every commit message ends with the attribution line the session requires.

---

## 7. Deploy package

`scripts/deploy/build_pkg.py` `PIPELINE_FILES` ships `bin/ltx-movie`, and `TEST_FILES` ships `tests/test_ltx_movie_offline.py`. The judge tools and iterate-story are not shipped.

No deploy test pins the real content or hash of either file:
- `tests/test_deploy_pkg.py` builds a fixture workspace whose pipeline files are stubs (`build_sources()` writes `# fixture <rel>\n`).
- The only `bin/ltx-movie` hash assertion (line 1263) compares against `file_sha256(self.fx.ws + "/bin/ltx-movie")`, which is computed on the fixture.
- Line 760 pins only the file LIST (`bp.PIPELINE_FILES == PIPELINE`), and that list does not change.

So no deploy test needs updating (A8 stays at 165). A package built before this change still ships the old `bin/ltx-movie` text. Rebuilding is a separate operator action and out of scope.

## 8. Out of scope (explicit)

- The explicit-content `Rules:` block at `bin/ltx-movie:124-127` (user declined).
- The `"her eyebrows angle down and her lips press together"` example (0/47 leaks) and the negative `"Camera:"`/`"Audio:"` label examples.
- judge-story's "action-focused storyboard" wording and `action_plausibility` key, judge-clips' `physical_realism` "real footage" wording, and judge-stills' `rendering_quality` clause (D9, D10).
- A `--goal` for `bin/ltx-movie` or any story-generation tool. Passing `--goal` to ltx-movie from iterate-story.
- Adding the goal to `run-summary.json`, stdout, or the `*.raw.json` dumps.
- Regenerating or re-judging any existing story. Editing the earlier design specs. Editing the test-file docstring counts.
- Rebuilding the deploy package.
