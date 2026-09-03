# Spec: `qwen-agent` — session memory: short-term session notes, long-term principles, and a harness-enforced turn-end checkpoint

**Status:** Ready for implementation. No open design decisions. Open questions, if any, are listed in Section 14 and none of them block Step 1.
**Date:** 2026-09-02
**Type:** Additive feature on one working script, plus one new offline test file. Not a rewrite.

**Target artifacts:**

| Path | Action |
|---|---|
| `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/bin/qwen-agent` | edit in place (single file, mode `0755`, **2761 lines** as read on 2026-09-02) |
| `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/tests/test_qwen_agent_session_memory.py` | **create** (Section 11) |

**Do not edit any other file.** In particular do not touch
`/Users/reubenpatterson/qwen-agent-workspace/bin/qwen-agent` — that is a *different, older copy*
outside this git repository — and do not touch
`tests/test_qwen_agent_context_budget.py`, which must continue to pass unchanged.
Every line number and quoted anchor in this document refers to the 2761-line file under
`local_model_harness/`.

**Parent specs, all still authoritative except where this document explicitly revises them:**

- `docs/specs/2026-08-21-qwen-agent-tool-harness-design.md` — **[HARNESS]**
- `docs/specs/2026-08-21-qwen-agent-oneshot-api-design.md` — **[ONESHOT]**
- `docs/specs/2026-08-21-qwen-agent-tiered-approval-design.md` — **[TIERED]**
- `docs/specs/2026-08-21-qwen-agent-search-grounding-design.md` — **[SEARCH]**
- `docs/specs/2026-09-02-qwen-agent-context-budget-design.md` — **[BUDGET]**

**Interpreter constraint:** unchanged — the file must stay valid on Python **3.9.6** (`/usr/bin/python3`)
and **3.13.0** (`python3`). No 3.10+ syntax (no `X | Y` annotations, no `match`). Standard library only.
**No new imports in `bin/qwen-agent`.** Everything this spec needs is already imported at lines 19–35:
`argparse`, `datetime`, `json`, `os`, `sys`, `urllib.error`. In particular `shutil` is **not** imported
and must not be added (Section 4.4 gives the read-then-write copy that replaces it), and `copy` is
**not** imported and must not be added (Section 6.2 gives the `json.loads(json.dumps(...))` deep copy
that replaces it).

**Style constraints:** `%`-formatting only (no f-strings), `# ---` section-header comment banners,
double-quoted strings, diagnostics to `sys.stderr.write(...)`, confirmation/trace UI and
human-facing REPL notices to `print(..., file=_ui())`. Match the surrounding code exactly.

---

## 1. Purpose

### 1.1 The failure this fixes (already diagnosed — do not re-investigate)

The operator hand-pasted an instruction of the form *"ALWAYS review `session_memory.md` and update it
at the end of every turn"* into the prompt. The model obeyed the first half — it read files — and in
doing so filled the 16384-token window, hit [BUDGET]'s eviction and then its `context_budget` cliff,
and the turn ended before the model ever reached the write. The memory was never written **on any
turn**, so nothing was ever carried forward, so every new session started from zero and re-read the
same files, and the failure repeated.

The root cause is not the model's discipline. It is that **memory capture was expressed as a prompt
instruction, which is advisory, and which competes for exactly the resource (context) that running
out of makes it impossible to honour.** The harness, by contrast, always gets to run: `repl()` is
still executing after `run_turn` returns, whatever happened inside it.

Three consequences follow, and this spec implements all three:

1. **The turn-end write must be a harness step, not a rule.** `repl()` calls it after `run_turn`
   returns. It cannot be forgotten, crowded out, or truncated away.
2. **The checkpoint must not run inside the turn's own context.** It runs on a deep copy of the
   transcript with `max_tokens` cut to 320 and tools disabled, so it costs the live conversation
   nothing and cannot itself overflow the live transcript.
3. **Durable knowledge must survive the session, and must not be deletable by the model.** Long-term
   memory is append-only, backed up before every append, restored from the backup at start, loaded
   into the system message of every session, and reachable only through a tool that can never be
   auto-approved.

### 1.2 What "memory" means here, precisely

Two stores, different lifetimes, different gates:

| | short-term | long-term |
|---|---|---|
| file | `~/.qwen-agent/memory/session.md` | `~/.qwen-agent/memory/long_term.md` |
| lifetime | one REPL session; archived at the next start | forever |
| written by | the `remember` tool (auto-approved) and the turn-end checkpoint | the `promote` tool (**always** human-approved) and the `/remember` slash command (the human typed it) |
| read into the system message | only its final `## Turn N` section, only of the *previous* session, as a one-time handoff | in full (capped for display) at every session start |
| deletable by the harness | archived, never deleted | never deleted, never rewritten |

"Long short-term memory" is the combination: a fresh working store per session, seeded once with the
previous session's last checkpoint, sitting under a permanent store of principles.

### 1.3 Success criteria

Correct and complete when all of the following hold:

1. `python3 -m py_compile bin/qwen-agent` and `/usr/bin/python3 -m py_compile bin/qwen-agent` both exit 0.
2. `python3 tests/test_qwen_agent_session_memory.py` exits 0 and prints `OK n/n` with n ≥ 60.
3. `python3 tests/test_qwen_agent_context_budget.py` still exits 0 and prints `OK n/n` — no
   regression, in particular its `C8 no new imports` check still passes with the *unchanged*
   expected import set.
4. In a live REPL session, **every** turn that dispatched at least one tool call and did not die of a
   transport error appends a `## Turn N` section to `~/.qwen-agent/memory/session.md`, and prints
   `[memory] checkpoint saved (N chars)`. Zero turns silently skip it.
5. Starting a second REPL session shows the previous session's last checkpoint inside
   `## Handoff from previous session` in the system message, and the previous `session.md` has moved
   to `~/.qwen-agent/memory/sessions/`.
6. No `promote` call ever executes without the human answering `y` at a prompt that displayed the
   exact line to be appended.
7. One-shot mode (`--user-prompt`) and every `delegate_to_skill` child are byte-for-byte unchanged:
   same tool list, same system message, no memory directory touched.
8. The system message content is computed exactly once per session and is the identical object on
   `/reset`, so the server's prefix cache is never invalidated mid-session.

**Quantified KPI**, scenario: one REPL session of 6 user turns, each dispatching ≥ 1 tool call, then
a second REPL session started immediately after.

| Metric | Before | After (required) |
|---|---|---|
| Turns whose findings are written to disk | 0 | **6** |
| `## Turn N` sections in `session.md` at session end | 0 (file does not exist) | **6** |
| Handoff text present in session 2's system message | 0 chars | **> 0 chars** (the Turn 6 checkpoint) |
| Long-term entries lost to a crash mid-append | unbounded | **0** (`.bak` written first, restored at start) |
| Long-term entries written without human approval | n/a | **0** |
| Extra tokens added to the *live* transcript by the checkpoint | n/a | **0** (runs on a deep copy) |
| System-message bytes that change mid-session | n/a | **0** |

### 1.4 Non-goals — explicitly out of scope, do not implement

- **No summarisation, deduplication, ranking, or expiry of notes.** `session.md` is an append-only
  chronological log. `long_term.md` is an append-only list. Nothing rewrites either.
- **No search over archived sessions.** `sessions/*.md` is written and never read again, except that
  the file just archived is read once, immediately, for the handoff.
- **No memory in one-shot mode and none in `delegate_to_skill` children.** `oneshot()` never calls
  `memory_start`, never gets the memory tools, never gets the memory block.
- **No automatic deletion of anything.** Not of long-term entries, not of backups, not of archives.
  Pruning is the human's job with a text editor.
- **No second model call to compress memory.** The turn-end checkpoint is the only extra model call
  this spec adds, it is one per user turn, and it is capped at 320 output tokens.
- **No change to `RESULT_CHAR_LIMIT`, `_truncate`, `estimate_tokens`, `evict_to_budget`,
  `context_budget`, `discover_context_window`, `run_turn`, `_forced_summary`, or any [BUDGET]
  constant.** This spec *calls* those; it does not modify them.
- **No change to the approval flow for any existing tool**, to `AUTO_APPROVE_TOOLS`' meaning, to the
  duplicate guard, the circuit breaker, or the repeat reminders. The only edit to
  `AUTO_APPROVE_TOOLS` is adding the string `"remember"`.
- **No change to the schema of any existing tool.**
- **No new imports.**
- **No change to the module docstring** at lines 2–17 and no new spec reference added to it.
- **No memory content in the one-shot JSON envelope.**
- **No adjacent cleanup, reformatting, or renaming.** Every changed line must trace to this document.

---

## 2. The design, in one paragraph

At REPL start, after `setup()` and before anything is printed, `memory_start(WORKSPACE)` opens
`~/.qwen-agent/memory/`, restores `long_term.md` from its backup if the file vanished, moves any
leftover `session.md` into `sessions/<stamp>.md`, extracts that archive's **last** `## Turn N` section
as this session's handoff, writes a fresh `session.md` header, and returns a block of text that is
appended **once** to the REPL system message. Two extra tools appear in the REPL's tool list only:
`remember(text)`, auto-approved, which appends one dated bullet to `session.md`; and `promote(text)`,
which appends one dated bullet to `long_term.md` after copying it to `long_term.md.bak`, and which
`should_auto_approve` refuses *by name, before the tuple lookup*, so it can never run unseen. After
every user turn that dispatched at least one tool call and survived, `repl()` calls
`memory_checkpoint(messages, args_ns, turn_index)`, which deep-copies the transcript, appends a fixed
checkpoint prompt to the copy, runs one tools-disabled 320-token completion against it, and appends
the reply to `session.md` as `## Turn N`. The live transcript is never touched.

**Why the store lives outside the workspace:** `resolve_in_workspace` (line 511) rejects every path
that does not resolve under `WORKSPACE`. Putting the memory files under `~/.qwen-agent/memory/`
therefore means `read_file` and `write_file` **cannot reach them at all** — the existing guard does
the work, with no new check to write, review, or get wrong. The only writes to memory are through
`remember` (one line, ≤ 500 chars, no path argument), `promote` (human-gated), and the human's own
`/remember`. The model can neither read the raw files nor rewrite them, which is exactly the
protection long-term memory needs.

**Why the checkpoint runs on a deep copy:** two independent hard requirements. (1) *Transcript
purity* — if the checkpoint prompt and its answer stayed in `messages`, the next turn would see the
model summarising itself, and every later turn would carry N summaries of summaries. (2) *Prefix
cache and eviction safety* — `evict_to_budget` rewrites `content` **in place** on the dicts it is
given ([BUDGET] Section 2), so a shallow `list(messages)` copy would silently evict real tool results
out of the live conversation. The copy must be deep, and `json.loads(json.dumps(messages))` is the
deep copy available without a new import (every message is already JSON-serialisable — `chat_completion`
serialises the same list at line 1618).

**Why the memory block is frozen for the session:** the system message is the first thing in every
request. Changing one byte of it invalidates the server's prefix cache for the whole remaining
session, turning every subsequent turn's prefill into a full recompute. The block is therefore built
exactly once, in `memory_start`, and the resulting system-message dict is the same object `/reset`
restores. Notes written during the session are **not** folded back into the system message; they are
on disk for the next session and in the transcript for this one.

### 2.1 Alternatives considered and rejected

| Alternative | Why rejected |
|---|---|
| Keep it a prompt rule ("always update memory at turn end") | This is the bug. An instruction that requires context to execute cannot survive running out of context, and the failure is silent. |
| Store memory inside the workspace and let the model use `read_file`/`write_file` | Gives the model unrestricted read *and overwrite* of the long-term store. One bad `write_file` — or one prompt-injected page telling it to "clean up your memory file" — erases every principle. The workspace guard already gives us confinement for free by putting the store outside it. |
| Rebuild the system message each turn to include this turn's notes | Invalidates the prefix cache on every turn, costs a full prefill each time, and grows the fixed overhead the [BUDGET] work exists to bound. Notes are already in the live transcript for this session; they only need to reach *disk* for the next one. |
| Append the checkpoint prompt to the live `messages` | Pollutes the conversation permanently (the model then summarises its own summaries) and costs transcript budget on every subsequent turn. |
| Shallow-copy `messages` for the checkpoint | `evict_to_budget` mutates the message dicts in place, so eviction on the "copy" would delete real tool results from the live transcript. A silent, hard-to-diagnose data loss. |
| Summarise the whole session into long-term memory automatically | Long-term memory is the one store the model cannot undo. Anything automatic makes it a dumping ground within days, and the block is loaded into *every* future session, so junk is paid for forever. Human gate, always. |
| Let `promote` be auto-approved when the text "looks like a principle" | [TIERED] Section 3.2 already establishes that content tests are worthless against an adversarial or merely confused generator. Tier by name only. |
| Put `remember`/`promote` in `_BASE_TOOLS` | `build_tools_for_context(None)` returns all of `_BASE_TOOLS`, and one-shot mode also passes `skill=None` (line 2740 sets `TOOLS = build_tools_for_context(args_ns.skill)` for every mode). Memory tools in `_BASE_TOOLS` would therefore appear in one-shot and in delegate children, which have no memory session at all. A separate `_MEMORY_TOOLS` list added only by `repl()` is the only placement that gets this right. |
| Add the memory tools in `main()` when `args_ns.user_prompt is None` | `MEMORY_ENABLED` is not known until `memory_start` has tried to create the directory, which happens inside `repl()` after `setup()`. Adding in `main()` would advertise tools that a read-only home makes unusable. `repl()` is the only place with the answer. |
| Delete or rewrite old long-term entries when the file gets long | The whole value of the store is that it is not subject to the model's or the harness's judgement. Display is capped; disk is not touched. Pruning is a human editing a Markdown file. |
| Use `shutil.copyfile` for the backup | `shutil` is not imported and this spec adds no imports. A 6-line read-then-write is exact, and these files are kilobytes. |
| Use `copy.deepcopy` for the transcript copy | `copy` is not imported and this spec adds no imports. `json.loads(json.dumps(...))` is a valid deep copy for a structure that is about to be JSON-serialised anyway. |
| Reuse `write_file`'s confirmation preview for `promote` | `build_confirmation_body`'s `write_file` branch reads `resolved_paths["path"]` and `args["content"]`; `promote` has neither. It needs the one thing that matters — the exact line that will be appended — which is a dedicated branch. |
| Checkpoint on every turn, including turns with no tool calls | A pure-chat turn has produced no verified fact, no finding from evidence, and no tool-derived decision. Checkpointing it costs a model call per turn to record nothing. The `outcome["tool_calls"]` non-empty gate is the cheapest possible signal that the turn did work worth recording. |

---

## 3. New constants and globals

### 3.1 Constants — Section 5 block

**Anchor** (lines 67–70, verbatim):

```python
EVICTED_STUB = "[result evicted to free context: %d chars from %s]"
EVICTED_PREFIX = "[result evicted to free context:"   # marks an already-evicted result

# Self-contained layout: this script lives at <root>/bin/qwen-agent, and the docs
```

**Insert** immediately after the `EVICTED_PREFIX` line and before the blank line preceding the
`# Self-contained layout:` comment:

```python

# Session memory (see docs/specs/2026-09-02-qwen-agent-session-memory-design.md).
# The store lives OUTSIDE the workspace on purpose: resolve_in_workspace rejects
# every path that does not resolve under WORKSPACE, so read_file and write_file
# cannot reach these files at all. The only writes are the remember tool (one
# short line, no path argument), the promote tool (never auto-approved), and the
# human's own /remember. No new check was needed to get that; the existing
# workspace guard does it.
MEMORY_DIRNAME = os.path.join(".qwen-agent", "memory")   # relative to the user's home
MEMORY_DIR_MODE = 0o700
MEMORY_LONG_TERM_NAME = "long_term.md"
MEMORY_SESSION_NAME = "session.md"
MEMORY_ARCHIVE_DIRNAME = "sessions"
MEMORY_BACKUP_SUFFIX = ".bak"
MEMORY_TEXT_LIMIT = 500          # characters per entry, measured AFTER whitespace collapse
MEMORY_LT_DISPLAY_TOKENS = 1500  # estimated-token cap on the long-term block in the system message
MEMORY_HANDOFF_TOKENS = 800      # estimated-token cap on the handoff block in the system message
MEMORY_SHOW_CHAR_LIMIT = 100000  # per-file display cap for /memory; the file is never modified
MEMORY_CHECKPOINT_MAX_TOKENS = 320   # reply budget for the turn-end checkpoint call
MEMORY_TRUNCATED_MARKER = "\n[... truncated]"
MEMORY_OLDER_MARKER = "[%d older entries not shown; see ~/.qwen-agent/memory/long_term.md]"
# Turn statuses after which a checkpoint is pointless or impossible: the transport
# failed, the transcript was rolled back, or the window is already full. Every other
# status -- ok, max_rounds, circuit_open, truncated, context_budget -- did real tool
# work and is worth recording.
MEMORY_CHECKPOINT_SKIP_STATUSES = (
    "network_error", "http_error", "malformed_response", "interrupted",
    "context_length",
)
```

Note `MEMORY_DIRNAME` uses `os.path.join` so it is `".qwen-agent/memory"` on this host; the value is
never displayed to the user, only joined onto `os.path.expanduser("~")`. `MEMORY_OLDER_MARKER`'s text
is a literal path spelled `~/.qwen-agent/memory/long_term.md` because that is the form a human
reading the system message can paste into a shell.

### 3.2 `AUTO_APPROVE_TOOLS` — add `"remember"`

**Anchor** (line 88, verbatim):

```python
AUTO_APPROVE_TOOLS = ("generate_image", "search", "fetch_url", "read_file", "delegate_to_skill", "calculate")
```

**Replace with** (one line, same style, `"remember"` appended last):

```python
AUTO_APPROVE_TOOLS = ("generate_image", "search", "fetch_url", "read_file", "delegate_to_skill", "calculate", "remember")
```

`remember` writes one whitespace-collapsed line of ≤ 500 characters to a fixed path with no path
argument, no shell, and no network. It is strictly less powerful than `read_file`, which is already
in this tuple. It is auto-approved so that the model actually uses it — a confirmation prompt per
note would make it unusable and the memory would stay empty, which is the bug this spec fixes.

**Do not edit lines 100–106** (the `# INVARIANT: every name above is a member of AUTO_APPROVE_TOOLS`
comment attached to `SKILL_TOOL_NAMES`). That invariant is *"every skill tool name is in
AUTO_APPROVE_TOOLS"*, a one-way containment. Adding a name to `AUTO_APPROVE_TOOLS` that is not a skill
tool name cannot violate it. `remember` is not in any `SKILL_TOOL_NAMES` entry and must not be added
to one — skill children have no memory session (Section 1.4).

### 3.3 Mutable global — beside `WORKSPACE` and `CONTEXT_WINDOW`

**Anchor** (lines 148–156, verbatim):

```python
# Tokens the served model can actually hold. Set once by setup() from GET /v1/models
# or from --context-window; read by the budget helpers, by the two overflow messages,
# and forwarded to delegate_to_skill children so parent and child agree.
CONTEXT_WINDOW = DEFAULT_CONTEXT_WINDOW

ONESHOT_SCHEMA = "qwen-agent.oneshot.v1"   # value of the JSON envelope's "schema" field
EXIT_ABNORMAL = 3                          # one-shot: turn ended with no final answer
```

**Insert** between the `CONTEXT_WINDOW = DEFAULT_CONTEXT_WINDOW` line and the `ONESHOT_SCHEMA` line,
keeping one blank line either side:

```python
# False only when memory_start() could not create or write ~/.qwen-agent/memory.
# REPL-only: oneshot() never calls memory_start, so this stays True there and is
# never read, because nothing in the one-shot path consults it.
MEMORY_ENABLED = True
```

---

## 4. New tool schemas — Section 7 block

**Anchor** (lines 477–482, verbatim, the tail of `_CALCULATE_TOOL` and the head of
`build_tools_for_context`):

```python
        },
    },
}


def build_tools_for_context(skill):
```

**Insert** the block below between the closing `}` of `_CALCULATE_TOOL` and the
`def build_tools_for_context(skill):` line, separated by two blank lines on each side.

```python
# Advertised ONLY by repl(), and only when session memory is enabled. Deliberately
# NOT in _BASE_TOOLS: build_tools_for_context(None) returns all of _BASE_TOOLS, and
# one-shot mode and delegate_to_skill children go through that same call, so putting
# them there would hand memory tools to processes that have no memory session.
_MEMORY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": (
                "Save one short note to your memory for the rest of this session. "
                "Call it the moment you verify a fact, reach a finding, or make a "
                "decision you would be annoyed to have to re-derive later in this "
                "conversation. One plain sentence, under 500 characters, no code and "
                "no file contents. This is short-term memory: it goes into this "
                "session's notes file, and it is not carried into future sessions "
                "unless you promote it. Approved automatically, so use it freely."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": (
                            "The note, as one plain sentence. Newlines and runs of "
                            "spaces are collapsed to single spaces. The limit is 500 "
                            "characters after that collapse."
                        ),
                    }
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "promote",
            "description": (
                "Save one durable principle to long-term memory, which is loaded into "
                "the system message of every future session. Use it only for "
                "something that will still be true and still be useful after the "
                "current task is finished: a standing preference of the user's, a "
                "property of this machine, a rule you were corrected on. Never use it "
                "for a fact about the task in front of you -- that is what remember is "
                "for. Every call is shown to the human and requires their explicit "
                "approval, and long-term entries are never deleted, so ask rarely."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": (
                            "The principle, as one plain sentence. Newlines and runs "
                            "of spaces are collapsed to single spaces. The limit is "
                            "500 characters after that collapse."
                        ),
                    }
                },
                "required": ["text"],
            },
        },
    },
]
```

**Do not modify `build_tools_for_context`.** It stays byte-for-byte identical, and continues to
return eight tools for `skill=None`. The memory tools are attached in `repl()` (Section 7.1) and
nowhere else.

Both descriptions' first sentences end in a period, which is what `_first_sentence` (line 1793) needs
to render them in `/help` and `/tools`.

---

## 5. Approval, trace keys, and the confirmation prompt

Four edits, in file order.

### 5.1 `should_auto_approve` — `promote` is refused by name, first

**Anchor** (lines 723–735, verbatim):

```python
def should_auto_approve(name, resolved_paths):
    """True when this call runs without a confirmation prompt.

    Decided by tool identity alone, plus the target-exists boolean for write_file.
    This function must never inspect args['command'] or args['code'].
    """
    if name in AUTO_APPROVE_TOOLS:
        return True
    if name == "write_file":
        is_overwrite, _ = _write_target_status(resolved_paths["path"])
        return not is_overwrite
    return False
```

**Replace with:**

```python
def should_auto_approve(name, resolved_paths):
    """True when this call runs without a confirmation prompt.

    Decided by tool identity alone, plus the target-exists boolean for write_file.
    This function must never inspect args['command'] or args['code'].

    promote is refused here explicitly, BEFORE the AUTO_APPROVE_TOOLS lookup, and
    that ordering is the whole point: adding "promote" to that tuple -- by a future
    edit, by a merge, or by a patch someone was talked into -- still cannot make a
    long-term memory write happen without a human seeing the exact line first.
    There is no other gate on it, and long-term entries are never deleted.
    """
    if name == "promote":
        return False
    if name in AUTO_APPROVE_TOOLS:
        return True
    if name == "write_file":
        is_overwrite, _ = _write_target_status(resolved_paths["path"])
        return not is_overwrite
    return False
```

### 5.2 `_auto_key` — `remember` must not reach the fallback

**Anchor** (lines 755–757, verbatim, the tail of `_auto_key`):

```python
    if name == "generate_image":
        return _trace_clip(args["prompt"])
    return _trace_clip(str(resolved_paths["path"]))
```

**Replace with:**

```python
    if name == "generate_image":
        return _trace_clip(args["prompt"])
    if name == "remember":
        return _trace_clip(args["text"])
    return _trace_clip(str(resolved_paths["path"]))
```

**This edit is mandatory and load-bearing, not cosmetic.** `remember` is auto-approved, so `dispatch`
reaches `_auto_key(name, args, resolved_paths)` at line 1536 with `resolved_paths == {}`. Without the
new branch, control falls through to `resolved_paths["path"]` and raises `KeyError: 'path'` — outside
the `try:` that wraps execution, so it would propagate out of `dispatch`, out of `run_turn`, and kill
the REPL turn with a traceback. The very first `remember` call would crash the agent.

### 5.3 `_call_key` — the decision-log key for both tools

**Anchor** (lines 760–768, verbatim, the head of `_call_key`):

```python
def _call_key(name, args):
    """Key argument shown on the [duplicate] line. Handles all nine tool names.

    No single process advertises all nine -- the top level has eight and each
    skill role has at most five (see build_tools_for_context) -- but this function
    is keyed by name and covers their union.
    """
```

**Replace the docstring** with (the counts are now wrong and this function is also `_log_decision`'s
key source, which is the reason the new names have to be here at all):

```python
def _call_key(name, args):
    """Key argument shown on the [duplicate] line and logged as a decision's "key".

    Handles all eleven tool names. No single process advertises all eleven -- the
    REPL has ten with memory enabled, eight without, and each skill role has at
    most five (see build_tools_for_context and _MEMORY_TOOLS) -- but this function
    is keyed by name and covers their union.
    """
```

**Anchor** (lines 781–785, verbatim, the tail of `_call_key`):

```python
    elif name == "generate_image":
        raw = args.get("prompt", "")
    else:
        raw = ""
    return _trace_clip(raw)
```

**Replace with:**

```python
    elif name == "generate_image":
        raw = args.get("prompt", "")
    elif name in ("remember", "promote"):
        raw = args.get("text", "")
    else:
        raw = ""
    return _trace_clip(raw)
```

This is the only change needed for the decision log: `_log_decision` (line 1371) already calls
`_call_key(name, args)` and writes the result as the `"key"` field, so a `remember` or `promote`
decision is logged with its clipped text and needs no further wiring.

### 5.4 `build_confirmation_body` — the `promote` preview

**Anchor** (lines 692–706, verbatim, the `generate_image` branch and the `else`):

```python
    elif tool_name == "generate_image":
        prompt = args["prompt"]
        return (
            "  prompt:\n"
            "%s\n"
            "  model:    Z-Image-Turbo (abliterated text encoder, uncensored)\n"
            "  output:   %s\n"
            "  timeout:  %ss\n"
            "  NOTE: output is screened by content_safety before it is saved; a\n"
            "        positive NSFW classification blocks the save and is logged."
            % (_indent_lines(prompt), WORKSPACE / GENERATED_IMAGES_SUBDIR, IMAGE_GEN_TIMEOUT)
        )
    else:
        return ""
```

**Insert** a new `elif` between the `generate_image` branch and the `else:`:

```python
    elif tool_name == "promote":
        clean, err = _memory_clean_text(args["text"])
        appended = err if err is not None else memory_long_term_line(clean)
        return (
            "  file:     %s\n"
            "  entries:  %d before this one\n"
            "  appends:  %s\n"
            "  NOTE: long-term memory is loaded into the system message of EVERY\n"
            "        future session and is never deleted by this harness. Approve\n"
            "        only a durable principle, not a fact about the current task."
            % (memory_long_term_path(), _memory_entry_count(memory_long_term_path()),
               appended)
        )
```

The preview shows the **exact line** `memory_write_long_term` will append, because both call
`memory_long_term_line` (Section 6.1). When the text fails validation the preview shows the same
`ERROR:` string the tool will return, so approving a doomed call is at least honest about it.

`build_confirmation_body` is defined at line 628 and calls three Section-14 helpers defined later in
the file. That is fine and matches existing practice (`build_confirmation_body` already references
`WORKSPACE` and `_write_target_status` by name); Python resolves module globals at call time, and
`confirm` is only ever called from `dispatch` at run time.

---

## 6. New code — Section 14 block

**Anchor** (lines 2281–2287, verbatim, the tail of `evict_to_budget` and the `Section 11` banner):

```python
    if evicted:
        print("[context] evicted %d tool result(s) to stay within the %d-token window"
              % (evicted, CONTEXT_WINDOW), file=_ui())
    return evicted


# ---------------------------------------------------------------------------
# Section 11: REPL main loop
# ---------------------------------------------------------------------------
```

**Insert** the entire block below between `return evicted` and the `# Section 11: REPL main loop`
banner, separated by two blank lines on each side (the file's existing convention).

### 6.1 Paths, formatting, and file primitives

```python
# ---------------------------------------------------------------------------
# Section 14: session memory -- short-term notes, long-term principles
# ---------------------------------------------------------------------------

def memory_root():
    """Absolute path of the memory directory, resolved at CALL time.

    Deliberately a function and not a module constant. Two reasons, both hard:
    importing this file must create nothing and touch nothing on disk, and the
    offline tests point HOME at a temporary directory AFTER importing it. A
    constant computed at import would freeze the real home into both.
    """
    return os.path.join(os.path.expanduser("~"), MEMORY_DIRNAME)


def memory_long_term_path():
    return os.path.join(memory_root(), MEMORY_LONG_TERM_NAME)


def memory_session_path():
    return os.path.join(memory_root(), MEMORY_SESSION_NAME)


def memory_archive_dir():
    return os.path.join(memory_root(), MEMORY_ARCHIVE_DIRNAME)


def _memory_now():
    """This process's clock, in UTC. Every timestamp in the store is UTC.

    Matches _log_decision's convention exactly, so a decision-log line and a
    memory entry written in the same second carry the same instant.
    """
    return datetime.datetime.now(datetime.timezone.utc)


def _memory_clean_text(text):
    """Collapse an entry to one line. Returns (clean_text, None) or (None, error).

    Every entry in both stores is exactly one line of Markdown, so newlines, tabs
    and runs of spaces are collapsed to single spaces BEFORE the length check: a
    multi-line entry would silently break the one-entry-per-line format that every
    reader and counter in this section depends on. The length limit is applied to
    the collapsed text, and the error message reports that same length, so the
    number the model is told is the number that was measured.
    """
    clean = " ".join(text.split())
    if clean == "":
        return None, "ERROR: text must be non-empty."
    if len(clean) > MEMORY_TEXT_LIMIT:
        return None, ("ERROR: text is %d characters; the limit is %d."
                      % (len(clean), MEMORY_TEXT_LIMIT))
    return clean, None


def _memory_read(path):
    """Whole file as text, or "" if it is missing or unreadable. Never raises.

    errors="replace" because a hand-edited store with a bad byte must still be
    displayable; this function never writes, so a mojibake read cannot corrupt
    anything on disk.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _memory_entry_count(path):
    """Number of dated bullet lines ("- [...") in a memory file."""
    total = 0
    for line in _memory_read(path).split("\n"):
        if line.startswith("- ["):
            total += 1
    return total


def _memory_backup(path):
    """Copy `path` to `path + ".bak"`, byte for byte. True on success.

    Read-then-write rather than shutil.copyfile: shutil is not imported and this
    spec adds no imports. These files are kilobytes, so reading the whole thing
    into memory is free. A missing source is SUCCESS -- there is nothing to
    protect yet, and refusing the first-ever append would be absurd.
    """
    try:
        with open(path, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    try:
        with open(path + MEMORY_BACKUP_SUFFIX, "wb") as f:
            f.write(data)
        return True
    except OSError:
        return False


def _memory_append_entry(path, line):
    """Append one already-formatted entry line. Returns None, or an ERROR string."""
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return None
    except OSError as e:
        return "ERROR: could not write %s: %s" % (path, e)


def memory_long_term_line(clean):
    """The exact line memory_write_long_term will append for `clean`.

    Shared by the append and by promote's confirmation preview, so the human
    approves the literal text that lands on disk rather than a paraphrase of it.
    """
    return "- [%s] %s" % (_memory_now().strftime("%Y-%m-%d"), clean)


def memory_write_long_term(clean):
    """Back up long_term.md, then append one dated entry. Returns (ok, error).

    Backup FIRST, unconditionally, and abort the whole operation if the backup
    fails. The .bak is the only thing standing between a half-completed append --
    a full disk, a signal, a crash -- and the loss of every durable entry the
    human ever approved, and memory_start() restores from it automatically at the
    next start. A write that cannot be protected is not performed.
    """
    path = memory_long_term_path()
    if not _memory_backup(path):
        return False, ("ERROR: could not back up %s before appending; nothing was "
                       "written." % path)
    err = _memory_append_entry(path, memory_long_term_line(clean))
    if err is not None:
        return False, err
    return True, None
```

### 6.2 Session start, the system-message block, and the tools

```python
def _memory_archive_path():
    """A unique sessions/<stamp>.md path.

    Two REPLs started in the same second get "-1", "-2", ... rather than one
    silently overwriting the other's archive. Nothing in this harness ever
    deletes an archive, so a collision would be an unrecoverable loss.
    """
    stamp = _memory_now().strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(memory_archive_dir(), "%s.md" % stamp)
    n = 1
    while os.path.exists(path):
        path = os.path.join(memory_archive_dir(), "%s-%d.md" % (stamp, n))
        n += 1
    return path


def _memory_last_turn_section(text):
    """Body of the LAST "## Turn N" section of an archived session file.

    The handoff is the previous session's final checkpoint and nothing else. The
    notes above it are raw working material -- timestamped, unordered, often
    superseded -- while the last checkpoint is the one part of the file the model
    itself wrote as a summary of where things stood. Returns "" when the file has
    no checkpoint at all, which is what a session that ended before its first
    tool turn looks like.
    """
    lines = text.split("\n")
    start = None
    for i, line in enumerate(lines):
        if line.startswith("## Turn "):
            start = i
    if start is None:
        return ""
    return "\n".join(lines[start + 1:]).strip()


def _memory_long_term_display():
    """Long-term entries as one block, capped at MEMORY_LT_DISPLAY_TOKENS.

    Drops the OLDEST lines from the DISPLAY only. long_term.md itself is never
    rewritten, by this function or any other in this file; the marker line names
    how many were dropped and where to read them. Uses the same
    len // CHARS_PER_TOKEN heuristic as estimate_tokens, for the same reason: a
    pessimistic character count needs no tokenizer and no new import.
    """
    lines = [ln for ln in _memory_read(memory_long_term_path()).split("\n")
             if ln.strip() != ""]
    if not lines:
        return ""
    limit = MEMORY_LT_DISPLAY_TOKENS * CHARS_PER_TOKEN
    dropped = 0
    while lines and len("\n".join(lines)) > limit:
        lines.pop(0)
        dropped += 1
    if dropped:
        lines.insert(0, MEMORY_OLDER_MARKER % dropped)
    return "\n".join(lines)


def _memory_block(handoff):
    """The text appended to the REPL system message. Built ONCE, in memory_start.

    PREFIX-CACHE INVARIANT, and it is a hard requirement, not an optimisation:
    the system message is the first thing in every request, so changing one byte
    of it invalidates the server's prefix cache for every remaining turn of the
    session and turns each subsequent prefill into a full recompute. This block
    is therefore computed exactly once and the resulting system-message dict is
    the same object /reset restores. Notes written during the session are NOT
    folded back in: they are already in the live transcript for this session, and
    on disk for the next one.
    """
    block = ""
    long_term = _memory_long_term_display()
    if long_term:
        block += "\n\n## Long-term memory\n" + long_term
    if handoff:
        limit = MEMORY_HANDOFF_TOKENS * CHARS_PER_TOKEN
        if len(handoff) > limit:
            handoff = handoff[:limit] + MEMORY_TRUNCATED_MARKER
        block += "\n\n## Handoff from previous session\n" + handoff
    return block


def memory_start(workspace):
    """Open this session's memory. REPL only. Returns the system-message block.

    The order is load-bearing:
      1. create ~/.qwen-agent/memory/ and its sessions/ subdirectory, mode 0700;
      2. restore long_term.md from its .bak if the file is gone and the backup is
         not -- memory_write_long_term writes the backup first, so this recovers
         a crash between the two writes;
      3. move any leftover session.md to sessions/<stamp>.md and read the handoff
         out of the archive;
      4. write a fresh session.md header.
    Any OSError in any of that sets MEMORY_ENABLED False, prints one warning, and
    returns "": a read-only or full home must degrade the REPL to exactly today's
    behaviour, never break it.
    """
    global MEMORY_ENABLED
    root = memory_root()
    try:
        os.makedirs(root, mode=MEMORY_DIR_MODE, exist_ok=True)
        os.makedirs(memory_archive_dir(), mode=MEMORY_DIR_MODE, exist_ok=True)
        lt_path = memory_long_term_path()
        bak_path = lt_path + MEMORY_BACKUP_SUFFIX
        if not os.path.exists(lt_path) and os.path.exists(bak_path):
            with open(bak_path, "rb") as f:
                data = f.read()
            with open(lt_path, "wb") as f:
                f.write(data)
            sys.stderr.write(
                "[memory] %s was missing; restored %d bytes from %s\n"
                % (lt_path, len(data), bak_path))
        handoff = ""
        session_path = memory_session_path()
        if os.path.exists(session_path):
            archived = _memory_archive_path()
            os.replace(session_path, archived)
            handoff = _memory_last_turn_section(_memory_read(archived))
        with open(session_path, "w", encoding="utf-8") as f:
            f.write("# Session %s\n"
                    % _memory_now().replace(microsecond=0).isoformat())
            f.write("workspace: %s\n" % workspace)
            f.write("\n## Notes\n")
    except OSError as e:
        MEMORY_ENABLED = False
        sys.stderr.write(
            "qwen-agent: session memory is disabled -- cannot use %s (%s: %s). The "
            "remember and promote tools and the /memory and /remember commands are "
            "not available this session.\n" % (root, type(e).__name__, e))
        return ""
    return _memory_block(handoff)
```

**Notes the implementer must not deviate from:**

- `os.makedirs(..., mode=MEMORY_DIR_MODE, exist_ok=True)` applies the mode only to directories it
  creates, and the process umask is subtracted from it. Under every umask this host will realistically
  have (022, 002, 077) the result is exactly `0o700`. Do not add an `os.chmod` — silently changing the
  permissions of a directory the user already created is not this function's business.
- `os.replace` (not `os.rename`, not a copy-then-delete) for the archive move: it is atomic within a
  filesystem and both paths are under `memory_root()`.
- `session.md` is created with mode `"w"`, once, immediately after the previous one was moved away.
  Every other write to it is mode `"a"`.
- `_memory_last_turn_section` finds the last match by scanning to the end and keeping the last index;
  do not `break` on the first match.
- The `except OSError` on `memory_start` is deliberately broad within that class and covers
  `PermissionError`, `FileNotFoundError` and `OSError: [Errno 28] No space left`. Do not narrow it and
  do not widen it to bare `Exception`.

### 6.3 The tool implementations

```python
def exec_remember(args):
    """Append one dated note to this session's short-term store.

    The note is appended at the END of session.md, not inserted under the
    "## Notes" heading. That heading marks where the log begins, not a container:
    notes and "## Turn N" checkpoints interleave in the order they actually
    happened, which is what makes the file readable as a session timeline and
    what makes the append a single O(1) open("a") with no parsing.
    """
    clean, err = _memory_clean_text(args["text"])
    if err is not None:
        return err
    path = memory_session_path()
    err = _memory_append_entry(
        path, "- [%s] %s" % (_memory_now().strftime("%H:%M"), clean))
    if err is not None:
        return err
    return "OK: noted (%d notes this session)" % _memory_entry_count(path)


def exec_promote(args):
    """Append one dated principle to the long-term store, after backing it up.

    Reached only after should_auto_approve refused this call by name and the
    human answered y at a prompt showing the exact line (see Section 5 of the
    spec). This function performs no gate of its own.
    """
    clean, err = _memory_clean_text(args["text"])
    if err is not None:
        return err
    ok, err = memory_write_long_term(clean)
    if not ok:
        return err
    return ("OK: promoted to long-term memory (%d entries)."
            % _memory_entry_count(memory_long_term_path()))
```

### 6.4 The turn-end checkpoint

```python
MEMORY_CHECKPOINT_PROMPT = (
    "Checkpoint. Write down what is worth keeping from THIS turn only, for your "
    "own use later in this session. At most five bullets, one line each, each one "
    "a fact you verified, a finding you reached, or a decision you made in this "
    "turn -- not a restatement of the question, not a plan, and not anything that "
    "was already true before this turn started. Then one final line beginning "
    "'Next steps:' saying what should happen next. Plain text only: no code, no "
    "file contents, no tool calls, no preamble, no closing remark."
)


def memory_checkpoint(messages, args_ns, turn_index):
    """Ask the model to write this turn's memory, and append it to session.md.

    This is the whole point of the feature: the write is a harness step that runs
    after run_turn has returned, so it cannot be crowded out of the context, and
    cannot be forgotten by a model that was told to remember.

    Runs on a DEEP COPY of the transcript, never on `messages` itself. Two
    independent hard requirements: (1) the checkpoint prompt and its answer must
    not join the conversation, or the next turn would see the model summarising
    itself and every later turn would carry summaries of summaries; (2)
    evict_to_budget rewrites message dicts IN PLACE, so a shallow list copy would
    silently evict real tool results out of the LIVE transcript. The deep copy is
    json.loads(json.dumps(...)) because the copy module is not imported and every
    message is already JSON-serialisable -- chat_completion serialises this same
    list on every request.

    Never raises, never changes the turn's outcome, and never writes to stdout on
    a failure path. Any failure prints one stderr line and returns.
    """
    ck_args = argparse.Namespace(**vars(args_ns))
    ck_args.max_tokens = MEMORY_CHECKPOINT_MAX_TOKENS
    try:
        transcript = json.loads(json.dumps(messages))
        transcript.append({"role": "user", "content": MEMORY_CHECKPOINT_PROMPT})
        evict_to_budget(transcript, ck_args, len(transcript), include_tools=False)
        if estimate_tokens(transcript, include_tools=False) > context_budget(ck_args):
            sys.stderr.write("[memory] checkpoint skipped: the transcript does not "
                             "fit the %d-token window\n" % CONTEXT_WINDOW)
            return
        resp = chat_completion(args_ns.base_url, transcript, ck_args,
                               include_tools=False)
        text = resp["choices"][0]["message"].get("content") or ""
    except KeyboardInterrupt:
        sys.stderr.write("[memory] checkpoint skipped: cancelled\n")
        return
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError,
            KeyError, IndexError, TypeError) as e:
        sys.stderr.write("[memory] checkpoint skipped: %s: %s\n"
                         % (type(e).__name__, e))
        return
    text = text.strip()
    if text == "":
        sys.stderr.write("[memory] checkpoint skipped: the model returned no text\n")
        return
    try:
        with open(memory_session_path(), "a", encoding="utf-8") as f:
            f.write("\n## Turn %d\n%s\n" % (turn_index, text))
    except OSError as e:
        sys.stderr.write("[memory] checkpoint skipped: %s: %s\n"
                         % (type(e).__name__, e))
        return
    print("[memory] checkpoint saved (%d chars)" % len(text), file=_ui())
```

**Notes the implementer must not deviate from:**

- `argparse.Namespace(**vars(args_ns))` is the args copy. `argparse` is imported at line 19; `copy` is
  not and must not be. `vars()` on a `Namespace` returns its `__dict__`, and `Namespace(**d)` rebuilds
  it — a flat copy, which is all that is needed since every field is a scalar.
- `ck_args`, not `args_ns`, is passed to `evict_to_budget`, `context_budget` and `chat_completion`.
  `context_budget` subtracts `max_tokens`, so the checkpoint's 320-token reply buys back 1216 tokens of
  prompt room versus the default 1536. Using `args_ns` there would evict more than necessary.
- `protect_from` is `len(transcript)`, i.e. everything is eligible. This is a throwaway copy; there is
  no "current round" to protect, and only `role == "tool"` messages are ever touched anyway.
- `KeyboardInterrupt` is caught **separately and first**. It is not an `Exception` subclass, so the
  second handler would miss it, and letting it escape would tear down the REPL loop from a step whose
  entire contract is "never affects the turn result".
- `IndexError` and `TypeError` are in the catch list in addition to the four the design named, because
  `resp["choices"][0]["message"]` raises `IndexError` on an empty `choices` list and `TypeError` when a
  server returns a non-subscriptable body. `run_turn` catches the same set at line 2529 for the same
  expression.
- `urllib.error.HTTPError` is listed before `URLError` even though it is a subclass of both `URLError`
  and `OSError`; the tuple order is documentation, not dispatch.
- The success line goes to `_ui()` (stdout in the REPL); every failure line goes to `sys.stderr`. That
  asymmetry is intentional and matches the rest of the file: `_ui()` carries things that happened,
  stderr carries things that did not.

**Amendment (review S4):** `evict_to_budget` gained a `quiet` parameter (default `False`), and the call
in this function now passes `quiet=True`. Without it, an eviction on the checkpoint's throwaway copy
printed the same `[context] evicted N tool result(s) ...` notice the live turn uses, which told the user
their real conversation had lost tool results when in fact nothing in `messages` was touched. `quiet`
suppresses only the print; the eviction itself, and its effect on the copy sent to the model, are
unchanged.

---

## 7. `repl()`, the banner, and the system message

### 7.1 `repl()` — five edits

**Anchor** (lines 2608–2614, verbatim, the head of `repl`):

```python
def repl(args_ns):
    setup(args_ns)
    print_banner(args_ns.model, WORKSPACE, args_ns.think)

    system_message = build_system_message(WORKSPACE)
    messages = [system_message]

```

**Replace with:**

```python
def repl(args_ns):
    # TOOLS/TOOL_BY_NAME are rebound here, not in main(), because whether the
    # memory tools may be advertised is not known until memory_start() has tried
    # to create the store: a read-only home must not leave the model holding two
    # tools that will fail on every call.
    global TOOLS, TOOL_BY_NAME

    setup(args_ns)
    memory_block = memory_start(WORKSPACE)
    if MEMORY_ENABLED:
        TOOLS = TOOLS + _MEMORY_TOOLS
        TOOL_BY_NAME = {t["function"]["name"]: t for t in TOOLS}

    print_banner(args_ns.model, WORKSPACE, args_ns.think, MEMORY_ENABLED)

    system_message = build_system_message(WORKSPACE, memory=MEMORY_ENABLED)
    if memory_block:
        system_message = {"role": "system",
                          "content": system_message["content"] + memory_block}
    messages = [system_message]
    turn_index = 0

```

`memory_start` runs **after** `setup` — it needs `WORKSPACE` resolved for the session header — and
**before** `print_banner` and `build_system_message`, which both consume `MEMORY_ENABLED`.

`TOOLS = TOOLS + _MEMORY_TOOLS` builds a new list rather than calling `.extend`, so the list object
`main()` created is not mutated. Nothing else holds a reference to it, but rebinding keeps the two
globals in step with the single `TOOL_BY_NAME` rebuild on the next line.

`preflight` has already run inside `setup()` with the eight-tool list, which is intended: the Check B
tool-calling probe (line 1970) is a server capability test, not a schema test, and keeping it on the
smaller list keeps its cost and its behaviour exactly as they are today.

**Anchor** (lines 2632–2636, verbatim, the middle of the loop):

```python
        snapshot = len(messages)
        messages.append({"role": "user", "content": line})

        outcome = run_turn(messages, args_ns, snapshot)
```

**Replace with:**

```python
        turn_index += 1
        snapshot = len(messages)
        messages.append({"role": "user", "content": line})

        outcome = run_turn(messages, args_ns, snapshot)
```

`turn_index` counts **user turns**, not rounds: it is incremented once per accepted input line, after
the blank-line and slash-command `continue`s, so `## Turn 1` is the first real turn and slash commands
never consume a number.

**Anchor** (lines 2646–2654, verbatim, the tail of `repl`, the last `elif` of the status chain):

```python
        elif outcome["status"] == "context_budget":
            sys.stderr.write(
                "[stopped: this conversation no longer fits in the server's %d-token "
                "window, even after evicting old tool results. The answer above, if "
                "any, is a forced summary. Use /reset to clear the conversation.]\n"
                % CONTEXT_WINDOW
            )
```

**Append** after that branch, at the same indent as the `if outcome["status"] == "max_rounds":` line
(8 spaces), as the last statement in the `while` body:

```python

        # The harness-enforced memory write. Deliberately the LAST thing in the
        # turn: the answer and any [stopped: ...] notice are already on screen, so
        # a slow or failing checkpoint delays nothing the user is waiting for. It
        # runs only for turns that actually dispatched a tool call -- a pure-chat
        # turn verified nothing and has nothing to record -- and never after a
        # transport failure, where the transcript was rolled back anyway.
        if (MEMORY_ENABLED and outcome["tool_calls"]
                and outcome["status"] not in MEMORY_CHECKPOINT_SKIP_STATUSES):
            memory_checkpoint(messages, args_ns, turn_index)
```

`outcome["tool_calls"]` is the `records` list built by `run_turn` — confirmed at `_turn_result`
(line 2323): `def _turn_result(status, answer, rounds, tool_calls, error)` with every call site passing
`records`. A non-empty list means at least one tool call was dispatched, whatever its outcome
(approved, denied, duplicate, circuit_open, invalid, rejected). A denied or failed call is still work
worth a note about what was refused and why.

### 7.2 `print_banner` — advertise what is actually loaded

**Anchor** (lines 2133–2141, verbatim):

```python
def print_banner(model, workspace, think):
    print("qwen-agent  |  model=%s  |  thinking=%s" % (model, "on" if think else "off"))
    print("workspace: %s" % workspace)
    print("tools: bash, search, fetch_url, read_file, write_file, run_python, generate_image, delegate_to_skill")
    print("approval required: bash, run_python, generate_image, overwriting an existing file. Default is no.")
    print("auto-approved (no prompt, traced with [auto]): search, read_file, fetch_url, new-file write_file, delegate_to_skill.")
    print("bash and run_python are NOT sandboxed -- read each command before approving.")
    print("/help for commands, /exit to quit.")
```

**Replace with:**

```python
def print_banner(model, workspace, think, memory=False):
    print("qwen-agent  |  model=%s  |  thinking=%s" % (model, "on" if think else "off"))
    print("workspace: %s" % workspace)
    if memory:
        print("tools: bash, search, fetch_url, read_file, write_file, run_python, generate_image, delegate_to_skill, remember, promote")
        print("approval required: bash, run_python, generate_image, promote, overwriting an existing file. Default is no.")
        print("auto-approved (no prompt, traced with [auto]): search, read_file, fetch_url, new-file write_file, delegate_to_skill, remember.")
        print("memory: %s   (/memory to inspect, /remember <text> to add a long-term entry)" % memory_root())
    else:
        print("tools: bash, search, fetch_url, read_file, write_file, run_python, generate_image, delegate_to_skill")
        print("approval required: bash, run_python, generate_image, overwriting an existing file. Default is no.")
        print("auto-approved (no prompt, traced with [auto]): search, read_file, fetch_url, new-file write_file, delegate_to_skill.")
    print("bash and run_python are NOT sandboxed -- read each command before approving.")
    print("/help for commands, /exit to quit.")
```

`memory=False` keeps the existing three lines byte-for-byte, so the `MEMORY_ENABLED = False`
degradation and any future caller see today's banner exactly. `print_banner` is called from exactly one
place (`repl`, line 2610); `oneshot` does not call it.

### 7.3 `build_system_message` — a `memory` parameter, default `False`

**Anchor** (lines 1644–1648, verbatim, the head of `build_system_message`):

```python
def build_system_message(workspace):
    content = (
        "You are a local command-line assistant running on the user's macOS machine "
        "with eight tools: bash, search, fetch_url, read_file, write_file, run_python, "
        "generate_image, delegate_to_skill.\n\n"
        "Rules you must follow:\n"
```

**Replace with:**

```python
def build_system_message(workspace, memory=False):
    """The top-level system message.

    memory=True is passed ONLY by repl(), and only when session memory is enabled.
    It changes the tool-count sentence and adds rules 9 and 10. Every other caller
    -- oneshot(), delegate_to_skill children, the offline tests -- takes the
    default and gets today's text byte for byte.
    """
    if memory:
        opening = (
            "You are a local command-line assistant running on the user's macOS machine "
            "with ten tools: bash, search, fetch_url, read_file, write_file, run_python, "
            "generate_image, delegate_to_skill, remember, promote.\n\n"
        )
    else:
        opening = (
            "You are a local command-line assistant running on the user's macOS machine "
            "with eight tools: bash, search, fetch_url, read_file, write_file, run_python, "
            "generate_image, delegate_to_skill.\n\n"
        )
    content = opening + (
        "Rules you must follow:\n"
```

**Anchor** (lines 1674–1679, verbatim, the tail of `build_system_message` — rule 8 and the return):

```python
        "8. delegate_to_skill hands a self-contained task to a specialized read-only "
        "sub-agent -- investigator for research, analyst to validate a specific claim, "
        "planner for an implementation plan -- and returns its final answer. The sub-agent "
        "sees only the task text you write, never this conversation, so the brief must be "
        "complete on its own. Use it for a bounded sub-task you want handled independently, "
        "not for anything you can just do yourself with your other tools."
    ).format(workspace=workspace)
    return {"role": "system", "content": content}
```

**Replace** the closing `).format(...)` line and the `return` with:

```python
        "8. delegate_to_skill hands a self-contained task to a specialized read-only "
        "sub-agent -- investigator for research, analyst to validate a specific claim, "
        "planner for an implementation plan -- and returns its final answer. The sub-agent "
        "sees only the task text you write, never this conversation, so the brief must be "
        "complete on its own. Use it for a bounded sub-task you want handled independently, "
        "not for anything you can just do yourself with your other tools."
    )
    if memory:
        content += (
            "\n9. remember(text) writes one line to your notes for this session. Call it "
            "the moment you verify a fact, reach a finding, or make a decision worth "
            "keeping -- one plain sentence, no code, no file contents. Do not wait until "
            "the end of the turn and do not batch them up: the note you did not write is "
            "the one you will have to re-derive. It is approved automatically, so it costs "
            "you nothing but the sentence.\n"
            "10. promote(text) writes one line to long-term memory, which is loaded into "
            "every future session and is never deleted. Use it only for a durable "
            "principle that will still apply after this task is over -- never for a fact "
            "about the task itself. It always requires the human's explicit approval, so "
            "ask rarely, and say plainly why the principle is durable."
        )
    return {"role": "system", "content": content.format(workspace=workspace)}
```

Rules 1–7 (lines 1649–1673) are untouched. Rule 8 does not end in `\n`, which is why rule 9 begins
with one. Neither new rule contains `{` or `}`, so moving `.format(workspace=workspace)` to after the
concatenation is safe; `{workspace}` appears only in rule 2.

`build_skill_system_message` (line 1769) and `SKILL_SYSTEM_PROMPTS` are untouched.

---

## 8. Slash commands

### 8.1 `HELP_TEXT`

**Anchor** (lines 1778–1791, verbatim):

```python
HELP_TEXT = """\
Commands:
  /help       Show this help.
  /exit       Exit the REPL (also /quit, /bye).
  /quit       Exit the REPL.
  /bye        Exit the REPL.
  /reset      Clear the conversation and start over.
  /stop       Stop the locally-served model process to free RAM/VRAM (REPL stays open).
  /workspace  Show the absolute workspace path.
  /tools      List the available tools.

Tools:
"""
```

**Replace** with (two lines inserted after `/tools`, same column alignment — the command column is 12
characters wide starting at column 3):

```python
HELP_TEXT = """\
Commands:
  /help       Show this help.
  /exit       Exit the REPL (also /quit, /bye).
  /quit       Exit the REPL.
  /bye        Exit the REPL.
  /reset      Clear the conversation and start over.
  /stop       Stop the locally-served model process to free RAM/VRAM (REPL stays open).
  /workspace  Show the absolute workspace path.
  /tools      List the available tools.
  /memory     Show both memory stores: paths, sizes, entry counts, contents.
  /remember   Add one line to long-term memory: /remember <text>

Tools:
"""
```

### 8.2 New helpers — Section 11.2 block

**Anchor** (lines 1807–1812, verbatim, `print_tools` and the head of `stop_local_model`):

```python
def print_tools():
    for t in TOOLS:
        fn = t["function"]
        print("  %-12s %s" % (fn["name"], _first_sentence(fn["description"])))


def stop_local_model(base_url):
```

**Insert** between `print_tools` and `stop_local_model`, separated by two blank lines on each side:

```python
def print_memory():
    """/memory -- both stores verbatim, with sizes and counts. Reads only.

    Display is capped per file; the file itself is never modified, never
    reformatted, and never truncated on disk. A store that has grown past the cap,
    or that a human hand-edited into something this harness would not have
    written, still shows its first MEMORY_SHOW_CHAR_LIMIT characters and says so.
    """
    for label, path in (("long-term", memory_long_term_path()),
                        ("session", memory_session_path())):
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        body = _memory_read(path)
        if len(body) > MEMORY_SHOW_CHAR_LIMIT:
            body = body[:MEMORY_SHOW_CHAR_LIMIT] + (
                "\n[... display truncated at %d of %d characters; the file on disk "
                "is unchanged]" % (MEMORY_SHOW_CHAR_LIMIT, len(body)))
        print(RULE)
        print("%s: %s" % (label, path))
        print("  %d bytes, %d entries" % (size, _memory_entry_count(path)))
        print(RULE)
        print(body.rstrip("\n") if body.strip() != "" else "(empty)")
    print(RULE)
    print("archives: %s" % memory_archive_dir())


def slash_remember(raw):
    """/remember <text> -- the human's own long-term entry. Returns one line.

    No model call and no confirmation prompt. A human typing the text IS the
    approval that the promote tool has to stop and ask for; asking them to
    confirm what they just typed would be theatre. Same validation, same
    backup-then-append, same file as promote.
    """
    clean, err = _memory_clean_text(raw)
    if err is not None:
        return err
    ok, err = memory_write_long_term(clean)
    if not ok:
        return err
    return ("OK: added to long-term memory (%d entries)."
            % _memory_entry_count(memory_long_term_path()))
```

`slash_remember`'s success string ("added to") deliberately differs from `exec_promote`'s ("promoted
to"): one is human-facing REPL output, the other is a tool result the model reads and may quote.

### 8.3 `handle_slash_command`

**Anchor** (lines 1884–1901, verbatim, the whole function):

```python
def handle_slash_command(line, messages, system_message, args_ns):
    cmd = line.strip()
    if cmd == "/help":
        print_help()
    elif cmd in ("/exit", "/quit", "/bye"):
        sys.exit(0)
    elif cmd == "/reset":
        messages[:] = [system_message]
        print("[conversation cleared]")
    elif cmd == "/stop":
        stop_local_model(args_ns.base_url)
    elif cmd == "/workspace":
        print(str(WORKSPACE))
    elif cmd == "/tools":
        print_tools()
    else:
        print("unknown command: %s (try /help)" % cmd)
```

**Replace with:**

```python
def handle_slash_command(line, messages, system_message, args_ns):
    cmd = line.strip()
    if cmd == "/help":
        print_help()
    elif cmd in ("/exit", "/quit", "/bye"):
        sys.exit(0)
    elif cmd == "/reset":
        # `system_message` already carries this session's memory block, built once
        # by memory_start(). /reset therefore restores the identical object and the
        # server's prefix cache survives. /reset does NOT archive session.md and
        # does NOT start a new memory session: notes and checkpoints already on
        # disk stay, and the turn counter keeps counting. Only a new process
        # rotates the store.
        messages[:] = [system_message]
        print("[conversation cleared]")
    elif cmd == "/stop":
        stop_local_model(args_ns.base_url)
    elif cmd == "/workspace":
        print(str(WORKSPACE))
    elif cmd == "/tools":
        print_tools()
    elif cmd == "/memory":
        if MEMORY_ENABLED:
            print_memory()
        else:
            print("memory is disabled for this session.")
    elif cmd == "/remember" or cmd.startswith("/remember "):
        if MEMORY_ENABLED:
            print(slash_remember(cmd[len("/remember"):]))
        else:
            print("memory is disabled for this session.")
    else:
        print("unknown command: %s (try /help)" % cmd)
```

A bare `/remember` with no text reaches `slash_remember("")`, which returns
`"ERROR: text must be non-empty."` — the same message the tool gives, printed to stdout. The
`cmd == "/remember" or cmd.startswith("/remember ")` form is required so that a hypothetical future
`/rememberall` does not silently land here.

---

## 9. `dispatch` — the execution switch

**Anchor** (lines 1571–1576, verbatim, the tail of the exec switch):

```python
        elif name == "calculate":
            result = exec_calculate(args)
        else:
            result = "ERROR: unknown tool '%s'." % name
    except KeyboardInterrupt:
        result = ("ERROR: execution was interrupted by the user before it completed. "
```

**Replace** the two branches before `else:` with four:

```python
        elif name == "calculate":
            result = exec_calculate(args)
        elif name == "remember":
            result = exec_remember(args)
        elif name == "promote":
            result = exec_promote(args)
        else:
            result = "ERROR: unknown tool '%s'." % name
```

Nothing else in `dispatch` changes. In particular:

- The `if name not in TOOL_BY_NAME:` guard at line 1436 already produces the right answer in one-shot
  mode and in skill children, where `remember`/`promote` are absent from `TOOL_BY_NAME`: a hallucinated
  call gets `ERROR: unknown tool 'remember'. Available tools: ...`.
- `validate_args` (line 598) needs no change: it reads the schema out of `TOOL_BY_NAME`, so the new
  tools get `text` required-and-must-be-a-string checking for free.
- The **denied** path for `promote` is the existing one at lines 1552–1558: `confirm` returns
  `(False, deny_reason)`, `dispatch` builds the standard
  `"ERROR: the user denied permission for this tool call. It was NOT executed. ..."` result and calls
  `_record(name, args, raw_arguments, "denied", result, history, deny_reason=deny_reason)`. No new
  code, no new message.
- `_auto_trace_outcome` (line 788) needs no change: `exec_remember` returns either an `ERROR:` string
  (first branch) or an `OK: noted ...` string (the `else` branch, which takes the first line). Both
  render correctly on the `[auto]` line.

---

## 10. What each mode gets — the complete matrix

| | REPL, memory enabled | REPL, memory disabled | one-shot (`--user-prompt`) | skill child (`--skill`) |
|---|---|---|---|---|
| `memory_start` called | yes | yes (it is what disabled it) | **no** | **no** |
| tools | 10 | 8 | 8 | per `SKILL_TOOL_NAMES` |
| `build_system_message(..., memory=)` | `True` | `False` | `False` (default) | n/a (`build_skill_system_message`) |
| memory block in system message | if non-empty | never | never | never |
| turn-end checkpoint | yes, gated | no | never | never |
| `/memory`, `/remember` | yes | print "memory is disabled for this session." | n/a (no slash commands) | n/a |
| `~/.qwen-agent/memory` touched | yes | attempted once, failed | **never** | **never** |

`oneshot()` (line 2659) and `main()` (line 2726) are **not modified by this spec**. `main()` already
does `TOOLS = build_tools_for_context(args_ns.skill)` for every mode, and `build_tools_for_context`
still returns eight tools for `skill=None`; the memory tools are attached only inside `repl()`.

---

## 11. The test file

**Create** `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/tests/test_qwen_agent_session_memory.py`.
Plain python, **no pytest**, no network, no subprocess, no filesystem writes outside `tempfile`.

**Run:** `python3 tests/test_qwen_agent_session_memory.py` from the repo root
(`/Users/reubenpatterson/local_model_harness/qwen-agent-workspace`). Prints one `PASS <id> <name>` or
`FAIL <id> <name> <detail>` line per assertion, then `OK n/n`, and exits 0 when nothing failed, 1
otherwise. Identical harness shape to `tests/test_qwen_agent_context_budget.py`: module-level
`TOTAL`/`FAILED` counters, a `check(name, condition, detail="")` function, a
`if __name__ == "__main__":` block that calls every test function in order and then prints `OK %d/%d`
and `sys.exit(0 if FAILED == 0 else 1)`.

### 11.1 Module header and loader

```python
"""Plain-python (no pytest) offline tests for bin/qwen-agent's session memory.

Run: python3 tests/test_qwen_agent_session_memory.py
Covers the 2026-09-02 session-memory design: the short-term session store, the
append-only long-term store, the one-time handoff, the remember/promote tools,
the never-auto-approve gate on promote, and the harness-enforced turn-end
checkpoint. Fully offline -- HOME is a temp directory and every server call is
monkeypatched; nothing here touches the network, a subprocess, the model, or the
real ~/.qwen-agent.
"""

import ast
import builtins
import contextlib
import copy
import datetime
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import stat
import sys
import tempfile
import urllib.error
```

**HOME must be redirected before the script is loaded**, so that the "import creates nothing" check
is meaningful:

```python
# HOME is redirected BEFORE bin/qwen-agent is loaded, so M0 can prove that
# importing it creates nothing. memory_root() resolves ~ at call time, which is
# the only reason this works -- a module constant would have frozen the real home.
_HOME = tempfile.mkdtemp(prefix="qwen-agent-memtest-import-")
os.environ["HOME"] = _HOME

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
_SCRIPT_PATH = os.path.join(WS, "bin", "qwen-agent")

_loader = importlib.machinery.SourceFileLoader("qwen_agent", _SCRIPT_PATH)
_spec = importlib.util.spec_from_loader("qwen_agent", _loader)
qwen_agent = importlib.util.module_from_spec(_spec)
sys.modules["qwen_agent"] = qwen_agent
_loader.exec_module(qwen_agent)

_DOTDIR_AT_IMPORT = os.path.exists(os.path.join(_HOME, ".qwen-agent"))
_MEMORY_ENABLED_AT_IMPORT = qwen_agent.MEMORY_ENABLED
_TOOLS_AT_IMPORT = qwen_agent.TOOLS

# The ten-tool REPL schema; repl() normally does this after memory_start().
qwen_agent.TOOLS = qwen_agent.build_tools_for_context(None) + qwen_agent._MEMORY_TOOLS
qwen_agent.TOOL_BY_NAME = {t["function"]["name"]: t for t in qwen_agent.TOOLS}
# Route _ui() to stderr so [auto] and [memory] lines do not interleave with PASS.
qwen_agent.ONESHOT = True
```

### 11.2 Shared fixtures

```python
TOTAL = 0
FAILED = 0


def check(name, condition, detail=""):
    global TOTAL, FAILED
    TOTAL += 1
    if condition:
        print("PASS %s" % name)
    else:
        FAILED += 1
        print("FAIL %s %s" % (name, detail))


def fresh_home():
    """A new empty HOME for one test. Returns the path.

    Memory paths are resolved lazily by memory_root(), so setting HOME is all
    that is needed -- nothing caches the previous value.
    """
    home = tempfile.mkdtemp(prefix="qwen-agent-memtest-")
    os.environ["HOME"] = home
    qwen_agent.MEMORY_ENABLED = True
    return home


def root_of(home):
    return os.path.join(home, ".qwen-agent", "memory")


def lt_of(home):
    return os.path.join(root_of(home), "long_term.md")


def sess_of(home):
    return os.path.join(root_of(home), "session.md")


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def make_args(**overrides):
    ns = qwen_agent.parse_args([])
    for key, value in overrides.items():
        setattr(ns, key, value)
    return ns


def text_response(text):
    return {"choices": [{"finish_reason": "stop", "message": {"content": text}}]}


def make_fake_chat(reply):
    """(fake_chat_completion, calls). Records include_tools and max_tokens."""
    calls = []

    def fake(base_url, messages, args_ns, include_tools=True):
        calls.append({"include_tools": include_tools,
                      "max_tokens": args_ns.max_tokens,
                      "messages": copy.deepcopy(messages)})
        return text_response(reply)

    return fake, calls


def tool_message_transcript():
    """A system + user + assistant-echo + tool transcript with a 4000-char result."""
    blob = ("    x = compute_value(alpha, beta, gamma)  # note\n" * 100)[:4000]
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "do the thing"},
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "call_1_1", "type": "function",
                         "function": {"name": "bash", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1_1", "content": blob},
    ], blob
```

Every test that monkeypatches restores the original in a `finally:` block. The attributes patched
across this file are `qwen_agent.chat_completion`, `qwen_agent.memory_checkpoint`,
`qwen_agent.run_turn`, `qwen_agent.setup`, `qwen_agent.print_banner`, `qwen_agent._prompt_line`,
`qwen_agent.AUTO_APPROVE_TOOLS`, `qwen_agent.CONTEXT_WINDOW`, `qwen_agent.WORKSPACE`,
`qwen_agent.MEMORY_ENABLED`, `qwen_agent.TOOLS`, `qwen_agent.TOOL_BY_NAME`, and `builtins.input`.

### 11.3 Test cases

Each numbered case is one test function. Every `check(...)` below is required; the id is the first
token of the check name. Every test begins with `fresh_home()` unless stated otherwise.

**M0 — import is side-effect free.** (no `fresh_home()`; reads the captured values)
- `M0 no dotdir created by import`: `_DOTDIR_AT_IMPORT is False`
- `M0 MEMORY_ENABLED defaults True`: `_MEMORY_ENABLED_AT_IMPORT is True`
- `M0 TOOLS None at import`: `_TOOLS_AT_IMPORT is None`
- `M0 memory_root follows HOME`: after `home = fresh_home()`,
  `qwen_agent.memory_root() == root_of(home)`

**M1 — first start.**
- `home = fresh_home()`; `block = qwen_agent.memory_start("/tmp/ws-a")` inside
  `contextlib.redirect_stderr(io.StringIO())`.
- `M1 block is empty`: `block == ""`
- `M1 root created`: `os.path.isdir(root_of(home))`
- `M1 root mode 0700`: `stat.S_IMODE(os.stat(root_of(home)).st_mode) == 0o700`
- `M1 sessions dir created`: `os.path.isdir(os.path.join(root_of(home), "sessions"))`
- `M1 session header`: `read(sess_of(home)).startswith("# Session ")`
- `M1 header timestamp is UTC ISO`: the first line matches
  `r"^# Session \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$"`
- `M1 workspace line`: `"\nworkspace: /tmp/ws-a\n" in read(sess_of(home))`
- `M1 notes heading`: `read(sess_of(home)).endswith("\n## Notes\n")`
- `M1 no long-term file created`: `not os.path.exists(lt_of(home))`
- `M1 still enabled`: `qwen_agent.MEMORY_ENABLED is True`

**M2 — second start archives and hands off.**
- `home = fresh_home()`; `qwen_agent.memory_start("/tmp/ws-a")`.
- Overwrite the session file with a known shape:
  `write(sess_of(home), "# Session x\nworkspace: /tmp/ws-a\n\n## Notes\n- [09:00] note one\n\n## Turn 1\nturn one body\n\n## Turn 2\nturn two body\nsecond line\n")`
- `block = qwen_agent.memory_start("/tmp/ws-b")` under `redirect_stderr`.
- `M2 session.md replaced`: `read(sess_of(home)).startswith("# Session ")` and
  `"turn two body" not in read(sess_of(home))`
- `M2 exactly one archive`: `len(os.listdir(os.path.join(root_of(home), "sessions"))) == 1`
- `M2 archive keeps everything`: the archived file's text contains `"note one"`, `"turn one body"`
  and `"turn two body"`
- `M2 handoff heading present`: `"\n\n## Handoff from previous session\n" in block`
- `M2 handoff is the last turn only`:
  `block.split("## Handoff from previous session\n", 1)[1] == "turn two body\nsecond line"`
- `M2 handoff excludes earlier turns`: `"turn one body" not in block`
- `M2 handoff excludes notes`: `"note one" not in block`
- `M2 no long-term heading`: `"## Long-term memory" not in block`
- A third sub-case, same `home`: replace `session.md` with a file containing **no** `## Turn` section,
  call `memory_start` again → `M2 no checkpoint means no handoff`: the returned block is `""`, and
  `len(os.listdir(sessions)) == 2`.

**M3 — long-term display cap drops the oldest, disk untouched.**
- `home = fresh_home()`; `os.makedirs(root_of(home))`.
- Write 60 entries, each **exactly 415 characters**:
  `write(lt_of(home), "".join("- [2026-01-01] %s\n" % ("x" * 400) for _ in range(60)))`
  (`"- [2026-01-01] "` is 15 chars + 400 = 415; the joined block of N lines is `416*N - 1` characters,
  and the cap is `1500 * 3 == 4500`, so exactly **10** lines survive and **50** are dropped —
  arithmetic, not a guess).
- `block = qwen_agent.memory_start("/tmp/ws")` under `redirect_stderr`.
- `M3 long-term heading present`: `"\n\n## Long-term memory\n" in block`
- `M3 marker names the drop count`:
  `"[50 older entries not shown; see ~/.qwen-agent/memory/long_term.md]" in block`
- `M3 marker is the first displayed line`: the line immediately after `"## Long-term memory\n"` is
  that marker
- `M3 exactly ten entries displayed`: the block contains exactly 10 lines starting with `"- ["`
- `M3 disk unchanged`: `read(lt_of(home)).count("- [2026-01-01]") == 60` and
  `os.path.getsize(lt_of(home)) == 60 * 416`
- `M3 no backup written by a read`: `not os.path.exists(lt_of(home) + ".bak")`

**M4 — handoff cap truncates the tail.**
- `home = fresh_home()`; `qwen_agent.memory_start("/tmp/ws")`; then
  `write(sess_of(home), "# Session x\n\n## Turn 1\n" + ("a" * 3000) + "\n")`.
- `block = qwen_agent.memory_start("/tmp/ws")` under `redirect_stderr`.
- `M4 truncation marker present`: `block.endswith("[... truncated]")`
- `M4 truncated at the cap`:
  `block.split("## Handoff from previous session\n", 1)[1] == "a" * 2400 + "\n[... truncated]"`
- A second sub-case: a `## Turn 1` body of exactly 2400 `"a"` characters →
  `M4 at-limit body is not truncated`: `"[... truncated]" not in block`

**M5 — `remember`.**
- `home = fresh_home()`; `qwen_agent.memory_start("/tmp/ws")` under `redirect_stderr`.
- `M5 first note return`: `qwen_agent.exec_remember({"text": "alpha beta"}) == "OK: noted (1 notes this session)"`
- `M5 second note return`: `qwen_agent.exec_remember({"text": "gamma"}) == "OK: noted (2 notes this session)"`
- `M5 line format`: the session file contains a line matching `r"^- \[\d\d:\d\d\] alpha beta$"`
  (`re.search` with `re.M`)
- `M5 appended at end of file`: the last non-empty line of the session file is the `gamma` note
- `M5 newlines collapsed`: `exec_remember({"text": "a\n\nb\tc   d"})` then the file contains
  `"] a b c d"`
- `M5 empty rejected`: `exec_remember({"text": ""}) == "ERROR: text must be non-empty."`
- `M5 whitespace rejected`: `exec_remember({"text": "   \n\t "}) == "ERROR: text must be non-empty."`
- `M5 oversize rejected`:
  `exec_remember({"text": "x" * 501}) == "ERROR: text is 501 characters; the limit is 500."`
- `M5 at-limit accepted`: `exec_remember({"text": "y" * 500}).startswith("OK: noted")`
- `M5 rejections did not write`: the note count in the file is 4 (`alpha beta`, `gamma`,
  `a b c d`, the 500-`y` note) — i.e. `qwen_agent._memory_entry_count(sess_of(home)) == 4`
- **`M5 dispatch end to end`**: with `qwen_agent.WORKSPACE = None` and stderr captured, call
  `qwen_agent.dispatch({"id": "c1", "type": "function", "function": {"name": "remember", "arguments": json.dumps({"text": "via dispatch"})}}, 1, 1, make_args(), [])`
  → `record["outcome"] == "approved"`, `record["result"].startswith("OK: noted")`, no exception, and
  the captured stderr contains `"[auto] remember via dispatch -> OK: noted"`. *(This is the case that
  catches a missing `_auto_key` branch, which would raise `KeyError: 'path'`.)*

**M6 — `promote`, and the gate that cannot be edited away.**
- `home = fresh_home()`; `qwen_agent.memory_start("/tmp/ws")`; seed
  `write(lt_of(home), "- [2025-12-31] pre-existing principle\n")`; `before = read(lt_of(home))`.
- `result = qwen_agent.exec_promote({"text": "the user prefers UTC timestamps"})`
- `M6 return string`: `result == "OK: promoted to long-term memory (2 entries)."`
- `M6 backup written first`: `read(lt_of(home) + ".bak") == before`
- `M6 entry appended with today's date`: the file's last line is
  `"- [%s] the user prefers UTC timestamps" % datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")`
  (the test computes this itself; it does not call the script's helper)
- `M6 nothing removed`: `"pre-existing principle" in read(lt_of(home))`
- `M6 second promote rolls the backup`: promote again → `read(lt_of(home) + ".bak")` equals the file
  content as it was **before** the second append (two entries), and the file now has three
- `M6 empty rejected`: `exec_promote({"text": " "}) == "ERROR: text must be non-empty."` and the
  entry count is still 3
- `M6 never auto-approved`: `qwen_agent.should_auto_approve("promote", {}) is False`
- `M6 gate survives a tampered tuple`: inside `try/finally`, set
  `qwen_agent.AUTO_APPROVE_TOOLS = qwen_agent.AUTO_APPROVE_TOOLS + ("promote",)`, assert
  `should_auto_approve("promote", {}) is False`, and restore the original tuple in `finally`
- `M6 remember is auto-approved`: `qwen_agent.should_auto_approve("remember", {}) is True`
- `M6 confirmation shows the exact line`:
  `body = qwen_agent.build_confirmation_body("promote", {"text": "one  principle"}, 30, {})`
  → `body` contains `qwen_agent.memory_long_term_line("one principle")` and contains
  `"never deleted by this harness"`
- `M6 denied via dispatch`: patch `qwen_agent._prompt_line` with `lambda text: "n"`, capture stderr,
  dispatch a `promote` call → `record["outcome"] == "denied"`,
  `record["deny_reason"] == "human_declined"`, `record["result"].startswith("ERROR: the user denied")`,
  and the long-term entry count is unchanged. Restore `_prompt_line` in `finally`.
- `M6 approved via dispatch`: patch `_prompt_line` with `lambda text: "y"` → `outcome == "approved"`,
  result starts with `"OK: promoted"`, entry count incremented by one.

**M7 — restore from `.bak`.**
- `home = fresh_home()`; `os.makedirs(root_of(home))`;
  `write(lt_of(home) + ".bak", "- [2026-01-01] survived a crash\n")`; no `long_term.md`.
- `stderr = io.StringIO()`; `block = qwen_agent.memory_start("/tmp/ws")` under
  `contextlib.redirect_stderr(stderr)`.
- `M7 file restored`: `read(lt_of(home)) == "- [2026-01-01] survived a crash\n"`
- `M7 restore is announced`: `"was missing; restored" in stderr.getvalue()` and
  `"restored 32 bytes" in stderr.getvalue()` (the seed string is 32 bytes including its newline)
- `M7 restored content reaches the block`: `"survived a crash" in block`
- `M7 backup left in place`: `os.path.exists(lt_of(home) + ".bak")`

**M8 — checkpoint mechanics.**
- `home = fresh_home()`; `qwen_agent.memory_start("/tmp/ws")` under `redirect_stderr`.
- `messages, blob = tool_message_transcript()`; `before = copy.deepcopy(messages)`.
- `qwen_agent.CONTEXT_WINDOW = 2048` (small enough that `evict_to_budget` fires on the copy);
  `args = make_args(max_tokens=1536)`.
- `fake, calls = make_fake_chat("- fact one\n- fact two\nNext steps: keep going")`; patch
  `qwen_agent.chat_completion`; run
  `qwen_agent.memory_checkpoint(messages, args, 1)` with stdout and stderr both captured.
- `M8 one chat call`: `len(calls) == 1`
- `M8 tools disabled`: `calls[0]["include_tools"] is False`
- `M8 max_tokens is 320`: `calls[0]["max_tokens"] == 320`
- `M8 caller max_tokens untouched`: `args.max_tokens == 1536`
- `M8 checkpoint prompt appended to the copy`:
  `calls[0]["messages"][-1]["content"] == qwen_agent.MEMORY_CHECKPOINT_PROMPT` and
  `calls[0]["messages"][-1]["role"] == "user"`
- `M8 live transcript unchanged`: `messages == before` (deep equality; this is the assertion that a
  shallow copy would fail, because `evict_to_budget` would have stubbed `messages[3]["content"]`)
- `M8 eviction did happen on the copy`:
  `calls[0]["messages"][3]["content"].startswith("[result evicted")`
- `M8 session file gained the turn`:
  `"\n## Turn 1\n- fact one\n- fact two\nNext steps: keep going\n" in read(sess_of(home))`
- `M8 saved line printed`: the captured `_ui()` stream (stderr, since `ONESHOT` is True) contains
  `"[memory] checkpoint saved (%d chars)" % len("- fact one\n- fact two\nNext steps: keep going")`
  — the test computes the length rather than hardcoding it (it is 44)
- Second sub-case, same home, `turn_index=2`, reply `"  second turn  "` →
  `M8 reply is stripped`: `"\n## Turn 2\nsecond turn\n" in read(sess_of(home))`
- Restore `qwen_agent.chat_completion` and `qwen_agent.CONTEXT_WINDOW` in `finally`.

**M9 — checkpoint gating and failure.**

`drive_repl` helper (module level in the test file):

```python
def drive_repl(lines, outcomes):
    """Run qwen_agent.repl() over canned input lines with a canned run_turn.

    Returns (checkpoint_calls, stdout_text, stderr_text). repl() exits via
    SystemExit when input runs out (its EOFError branch calls sys.exit(0)), which
    this catches. setup, print_banner and run_turn are replaced; memory_start is
    NOT -- the store under the temp HOME is the thing under test.
    """
    calls = []
    feed = list(lines)

    def fake_input(prompt=""):
        if not feed:
            raise EOFError
        return feed.pop(0)

    seq = list(outcomes)

    def fake_run_turn(messages, args_ns, snapshot):
        return seq.pop(0)

    orig = (builtins.input, qwen_agent.setup, qwen_agent.print_banner,
            qwen_agent.run_turn, qwen_agent.memory_checkpoint,
            qwen_agent.TOOLS, qwen_agent.TOOL_BY_NAME)
    out, err = io.StringIO(), io.StringIO()
    try:
        builtins.input = fake_input
        qwen_agent.setup = lambda ns: None
        qwen_agent.print_banner = lambda *a, **k: None
        qwen_agent.run_turn = fake_run_turn
        qwen_agent.memory_checkpoint = (
            lambda messages, args_ns, turn_index: calls.append(turn_index))
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                qwen_agent.repl(make_args())
            except SystemExit:
                pass
    finally:
        (builtins.input, qwen_agent.setup, qwen_agent.print_banner,
         qwen_agent.run_turn, qwen_agent.memory_checkpoint,
         qwen_agent.TOOLS, qwen_agent.TOOL_BY_NAME) = orig
    return calls, out.getvalue(), err.getvalue()


def outcome(status, tool_calls):
    return {"status": status, "answer": "ok", "rounds": 1,
            "tool_calls": tool_calls, "error": None}
```

`drive_repl` requires `qwen_agent.WORKSPACE` to be set (the memory header prints it) and
`qwen_agent.TOOLS` to be a list before `repl` extends it; the test sets
`qwen_agent.WORKSPACE = "/tmp/ws"` and `qwen_agent.TOOLS = qwen_agent.build_tools_for_context(None)`
before each call.

- `home = fresh_home()`.
- `M9 no tool calls means no checkpoint`:
  `drive_repl(["hello"], [outcome("ok", [])])[0] == []`
- `M9 tool calls mean a checkpoint`:
  `drive_repl(["hello"], [outcome("ok", [{"tool": "bash"}])])[0] == [1]`
- `M9 transport failures are skipped`: for each status in
  `("network_error", "http_error", "malformed_response", "interrupted", "context_length")`,
  `drive_repl(["hello"], [outcome(s, [{"tool": "bash"}])])[0] == []`
- `M9 forced-summary statuses are still checkpointed`: for each status in
  `("max_rounds", "circuit_open", "truncated", "context_budget")`, the result is `[1]`
- `M9 turn index counts user turns only`:
  `drive_repl(["a", "/help", "", "b"], [outcome("ok", [{"t": 1}]), outcome("ok", [{"t": 1}])])[0] == [1, 2]`
- `M9 disabled memory means no checkpoint`: set `qwen_agent.MEMORY_ENABLED = False` (restore after),
  patch `qwen_agent.memory_start` to return `""` → the recorder is never called
- `M9 URLError is survivable`: patch `qwen_agent.chat_completion` with a function that raises
  `urllib.error.URLError("refused")`, call `qwen_agent.memory_checkpoint(messages, make_args(), 1)`
  directly with stderr captured → no exception propagates, stderr contains
  `"[memory] checkpoint skipped: URLError:"`, and `read(sess_of(home))` gained no `"## Turn"`
- `M9 empty reply is skipped`: fake chat returns `text_response("   ")` → stderr contains
  `"[memory] checkpoint skipped: the model returned no text"` and no `## Turn` section is written

**M10 — one-shot and children get nothing.**
- `names = [t["function"]["name"] for t in qwen_agent.build_tools_for_context(None)]`
- `M10 eight tools at top level`: `len(names) == 8`
- `M10 no remember in the default tool list`: `"remember" not in names`
- `M10 no promote in the default tool list`: `"promote" not in names`
- For each skill in `("investigator", "analyst", "planner")`:
  `M10 skill <name> has no memory tools`: neither name appears in
  `[t["function"]["name"] for t in qwen_agent.build_tools_for_context(skill)]`
- `msg = qwen_agent.build_system_message("/tmp/ws")["content"]`
- `M10 default says eight tools`: `"with eight tools:" in msg`
- `M10 default has no memory block`: `"## Long-term memory" not in msg` and
  `"## Handoff from previous session" not in msg`
- `M10 default has no rule 9`: `"\n9. " not in msg`
- `M10 default ends at rule 8`: `msg.rstrip().endswith("not for anything you can just do yourself with your other tools.")`

**M11 — the REPL system message with memory.**
- `msg = qwen_agent.build_system_message("/tmp/ws", memory=True)["content"]`
- `M11 says ten tools`: `"with ten tools:" in msg`
- `M11 lists the memory tools`: `"delegate_to_skill, remember, promote." in msg`
- `M11 rule 9 present`: `"\n9. remember(text) writes one line to your notes for this session." in msg`
- `M11 rule 10 present`: `"\n10. promote(text) writes one line to long-term memory" in msg`
- `M11 rule 10 names the human gate`: `"requires the human's explicit approval" in msg`
- `M11 workspace still substituted`: `"/tmp/ws" in msg` and `"{workspace}" not in msg`
- `M11 rules 1-8 unchanged`: for the default message `base` and this one, `msg.startswith(...)` is
  false but `base.split("Rules you must follow:\n", 1)[1] == msg.split("Rules you must follow:\n", 1)[1].split("\n9. ")[0]`

**M12 — an unwritable memory root disables memory cleanly.**
- Skip the whole test with a single `check("M12 skipped as root", True, "running as root")` when
  `hasattr(os, "geteuid") and os.geteuid() == 0`.
- `home = fresh_home()`; `os.chmod(home, 0o500)`; then inside `try/finally` (the `finally` restores
  `os.chmod(home, 0o700)`):
  - `stderr = io.StringIO()`; `block = qwen_agent.memory_start("/tmp/ws")` under
    `contextlib.redirect_stderr(stderr)`
  - `M12 no exception`: reaching this line at all
  - `M12 returns an empty block`: `block == ""`
  - `M12 MEMORY_ENABLED is False`: `qwen_agent.MEMORY_ENABLED is False`
  - `M12 warning on stderr`: `"session memory is disabled" in stderr.getvalue()` and
    `"PermissionError" in stderr.getvalue()`
  - `M12 nothing created`: `not os.path.exists(os.path.join(home, ".qwen-agent"))`
  - `M12 slash commands say so`: with stdout captured,
    `qwen_agent.handle_slash_command("/memory", [], {}, make_args())` prints
    `"memory is disabled for this session."`, and the same for `"/remember x"`
- Restore `qwen_agent.MEMORY_ENABLED = True` after.

**M13 — the `/remember` slash command.**
- `home = fresh_home()`; `qwen_agent.memory_start("/tmp/ws")` under `redirect_stderr`;
  `write(lt_of(home), "- [2025-01-01] seed\n")`; `before = read(lt_of(home))`.
- Capture stdout while calling
  `qwen_agent.handle_slash_command("/remember never deploy on a Friday", [], {}, make_args())`.
- `M13 confirmation printed`: stdout contains `"OK: added to long-term memory (2 entries)."`
- `M13 entry appended`: `"never deploy on a Friday" in read(lt_of(home))`
- `M13 backup taken`: `read(lt_of(home) + ".bak") == before`
- `M13 seed preserved`: `"seed" in read(lt_of(home))`
- `M13 bare command rejected`: `handle_slash_command("/remember", ...)` prints
  `"ERROR: text must be non-empty."` and the entry count stays 2
- `M13 unknown near-miss still unknown`: `handle_slash_command("/rememberall", ...)` prints
  `"unknown command: /rememberall (try /help)"`
- `M13 /memory prints both paths`: capture stdout for `handle_slash_command("/memory", ...)` →
  output contains `lt_of(home)`, `sess_of(home)`, `"never deploy on a Friday"`, `" entries"`, and
  `"archives: "`
- `M13 help lists both`: `"/memory" in qwen_agent.HELP_TEXT` and `"/remember" in qwen_agent.HELP_TEXT`

**M14 — source guards.**
Read `_SCRIPT_PATH` as text into `src`.
- `M14 no new imports`: the set of top-level `import` / `from ... import` module names parsed with
  `ast.walk` (collecting `ast.Import` alias names and `ast.ImportFrom` module names) equals exactly
  ```
  {"argparse", "ast", "datetime", "html.parser", "json", "operator", "os", "re",
   "signal", "subprocess", "sys", "time", "urllib.error", "urllib.parse",
   "urllib.request", "uuid", "pathlib"}
  ```
  — byte-identical to `test_qwen_agent_context_budget.py`'s C8 set.
- `M14 shutil not used`: `re.search(r"\bshutil\.\w+\(", src) is None` (a docstring may name shutil to explain why it is not used; a call may not)
- `M14 copy module not used`: `"import copy" not in src` and `"copy.deepcopy" not in src`
- `M14 remember is auto-approved`: `'"remember"' in` the single line of `src` that starts with
  `"AUTO_APPROVE_TOOLS = "`
- `M14 promote is not in the tuple`: `"promote"` does **not** appear in that same line
- `M14 promote refused before the tuple lookup`:
  `src.index('if name == "promote":\n        return False') < src.index("if name in AUTO_APPROVE_TOOLS:")`
- `M14 memory tools attached only in repl`: `src.count("+ _MEMORY_TOOLS") == 1` (one extension site in `repl()`; the definition and the `_call_key` docstring mention are allowed)
- `M14 build_tools_for_context untouched`:
  `"tools.append(_CALCULATE_TOOL)\n    return tools" in src` and `"_MEMORY_TOOLS" not in
  src.split("def build_tools_for_context", 1)[1].split("\n\n\nTOOLS = None", 1)[0]`
- `M14 checkpoint deep-copies`: `"json.loads(json.dumps(messages))" in src`
- `M14 checkpoint uses argparse.Namespace`: `"argparse.Namespace(**vars(args_ns))" in src`
- `M14 memory_root is a function`: `"def memory_root():" in src` and
  `"MEMORY_ROOT = os.path.expanduser" not in src`
- `M14 RESULT_CHAR_LIMIT unchanged`: `"RESULT_CHAR_LIMIT = 4000" in src`
- `M14 no 8192 regression`: `"8192-token" not in src`
- `M14 no f-strings`: `not re.search(r'f"[^"]*\{', src)` and `not re.search(r"f'[^']*\{", src)`

### 11.4 Test ordering in `__main__`

`test_import_side_effects`, `test_first_start`, `test_second_start_handoff`,
`test_long_term_display_cap`, `test_handoff_cap`, `test_remember`, `test_promote`,
`test_restore_from_backup`, `test_checkpoint`, `test_checkpoint_gating`, `test_oneshot_unchanged`,
`test_repl_system_message`, `test_unwritable_root`, `test_slash_commands`, `test_source_guards`.

Each test restores `qwen_agent.MEMORY_ENABLED = True`, `qwen_agent.CONTEXT_WINDOW =
qwen_agent.DEFAULT_CONTEXT_WINDOW`, and any patched attribute on exit, so ordering cannot leak state.
The temp HOMEs are deliberately **not** deleted — they are under the system temp directory, they are
kilobytes, and leaving them makes a failure inspectable.

---

## 12. Ordered implementation checklist

Steps are strictly ordered; each depends on all before it.

| # | Step | Files | Depends on | Done when |
|---|---|---|---|---|
| 1 | Add the constants block (3.1) | `bin/qwen-agent` | — | `python3 -m py_compile bin/qwen-agent` exits 0 and `grep -c "^MEMORY_" bin/qwen-agent` prints 14 |
| 2 | Add `"remember"` to `AUTO_APPROVE_TOOLS` (3.2); do **not** touch lines 100–106 | `bin/qwen-agent` | 1 | `grep -n 'AUTO_APPROVE_TOOLS = ' bin/qwen-agent` shows one line ending `"calculate", "remember")` |
| 3 | Add the `MEMORY_ENABLED` global (3.3) | `bin/qwen-agent` | 1 | `grep -n "^MEMORY_ENABLED = True" bin/qwen-agent` prints one line |
| 4 | Add `_MEMORY_TOOLS` (Section 4) | `bin/qwen-agent` | 1 | `py_compile` exits 0; `grep -c "^_MEMORY_TOOLS = \[" bin/qwen-agent` prints 1 |
| 5 | Add the whole Section 14 block (Section 6) | `bin/qwen-agent` | 1, 3 | `py_compile` exits 0; `grep -c "^def memory_root\|^def memory_start\|^def memory_checkpoint\|^def exec_remember\|^def exec_promote\|^def memory_write_long_term\|^def memory_long_term_line" bin/qwen-agent` prints 7 |
| 6 | Approval and trace edits 5.1–5.4 | `bin/qwen-agent` | 5 | `py_compile` exits 0; `grep -n 'if name == "promote":' bin/qwen-agent` prints one line; `grep -c 'if name == "remember":' bin/qwen-agent` prints 1 |
| 7 | Wire `remember`/`promote` into `dispatch`'s exec switch (Section 9) | `bin/qwen-agent` | 5, 6 | `grep -c "result = exec_remember(args)\|result = exec_promote(args)" bin/qwen-agent` prints 2 |
| 8 | `build_system_message` gains `memory=False` (7.3) | `bin/qwen-agent` | 1 | `python3 -c "import importlib.machinery as m,importlib.util as u,sys;l=m.SourceFileLoader('q','bin/qwen-agent');s=u.spec_from_loader('q',l);q=u.module_from_spec(s);l.exec_module(q);print('ten tools' in q.build_system_message('/x',memory=True)['content'], 'eight tools' in q.build_system_message('/x')['content'])"` prints `True True` |
| 9 | `print_banner` gains `memory=False` (7.2) | `bin/qwen-agent` | — | `py_compile` exits 0; `grep -c "def print_banner(model, workspace, think, memory=False):" bin/qwen-agent` prints 1 |
| 10 | Rework `repl()` (7.1) | `bin/qwen-agent` | 4, 5, 8, 9 | `py_compile` exits 0; `grep -c "memory_start(WORKSPACE)\|memory_checkpoint(messages, args_ns, turn_index)" bin/qwen-agent` prints 2 |
| 11 | Slash commands: `HELP_TEXT`, `print_memory`, `slash_remember`, `handle_slash_command` (Section 8) | `bin/qwen-agent` | 5 | `py_compile` exits 0; `grep -c "^def print_memory\|^def slash_remember" bin/qwen-agent` prints 2; `python3 bin/qwen-agent --help` still exits 0 |
| 12 | Create the test file (Section 11) | `tests/test_qwen_agent_session_memory.py` | 1–11 | `python3 tests/test_qwen_agent_session_memory.py` exits 0 and prints `OK n/n` with n ≥ 60 |
| 13 | Regression sweep | — | 12 | `python3 -m py_compile bin/qwen-agent` and `/usr/bin/python3 -m py_compile bin/qwen-agent` both exit 0; `python3 tests/test_qwen_agent_context_budget.py` exits 0 and prints `OK n/n` |

If any step's acceptance check fails, stop and report — do not improvise a fix that is not in this
document.

---

## 13. Risks, edge cases, and failure modes

1. **One extra model call per tool-using turn.** The checkpoint is capped at 320 output tokens with
   tools omitted from the request, so it is the cheapest possible completion against a prompt the
   server has almost entirely cached. Cost is real but bounded and visible (`[memory] checkpoint
   saved` prints on every one). If it ever becomes the dominant cost, the lever is
   `MEMORY_CHECKPOINT_MAX_TOKENS`, a one-constant change.
2. **A shallow copy in the checkpoint would corrupt the live transcript.** `evict_to_budget` rewrites
   `content` in place. This is why Section 6.4 mandates `json.loads(json.dumps(messages))` and why
   test M8 asserts `messages == before` against a `copy.deepcopy` snapshot. This is the single most
   likely way to implement the feature wrongly and have it look like it works.
3. **`_auto_key` without a `remember` branch crashes the first `remember` call** with
   `KeyError: 'path'`, outside `dispatch`'s `try:`. Section 5.2 is mandatory; test M5's dispatch
   end-to-end case exists to catch exactly this.
4. **The checkpoint's own request can still be over budget.** `memory_checkpoint` evicts and then
   re-checks against `context_budget(ck_args)`; if it still does not fit it writes
   `[memory] checkpoint skipped: the transcript does not fit the N-token window` and returns without
   sending. That is why status `"context_budget"` is *not* in `MEMORY_CHECKPOINT_SKIP_STATUSES`: the
   checkpoint has a much larger prompt budget (320-token reply vs. 1536) and often fits where the turn
   did not.
5. **A single long-term line longer than the display cap.** `_memory_long_term_display` pops until the
   join fits; a hand-edited 5000-character line would pop everything and leave only the marker. The
   file on disk is untouched and `/memory` still shows it in full. The tool path cannot create this —
   `MEMORY_TEXT_LIMIT` is 500 — so it requires a human to have edited the file.
6. **Clock crossing midnight between preview and append.** `promote`'s confirmation shows
   `memory_long_term_line(clean)` and the append recomputes it. A call approved at 23:59:59.9 UTC can
   be written with the next day's date. Cosmetic, one line, once; not worth freezing the timestamp
   across a blocking human prompt.
7. **Two REPLs sharing one home.** Both write `session.md`; the second to start archives the first's
   file out from under it, and the first's later appends recreate a new `session.md` that the *third*
   start will archive. Notes are never lost (appends are `O_APPEND`, and archives are never deleted),
   but a concurrent pair interleaves. Out of scope: this is a single-operator interactive REPL. The
   `-1`, `-2` suffixes in `_memory_archive_path` exist so the archives themselves cannot collide.
8. **`os.makedirs(mode=0o700)` is subject to umask.** Under any umask this host will realistically
   carry (022, 002, 077) the result is exactly `0o700`. An exotic umask with bits inside `0o700` would
   make test M1's mode assertion fail — correctly, since the store would then not be private.
9. **A read-only or full home disables memory for the whole session, silently after the first line.**
   `memory_start` prints one warning and the REPL runs exactly as it does today. `/memory` and
   `/remember` say so explicitly. No retry: a home that was unwritable at start is not worth probing
   once per turn.
10. **The model may ignore `remember`.** The harness-enforced checkpoint is the backstop and is the
    part that actually fixes the reported bug; `remember` is the fine-grained, in-the-moment
    supplement. If the model never calls it, memory still accrues one `## Turn N` section per turn.
11. **Long-term memory grows without bound.** By design — nothing deletes. The display is capped at
    1500 estimated tokens with an explicit marker naming how many entries were hidden, so the *cost*
    is bounded even though the file is not. Pruning is a human editing Markdown.
12. **The handoff carries stale intent into a new session.** It is the previous session's last
    checkpoint, which may describe a task the user has abandoned. It is labelled
    `## Handoff from previous session`, so the model is told what it is, and `/reset` does not remove
    it (it is part of the frozen system message). Removing it requires restarting the REPL after the
    current `session.md` has been archived — i.e. two restarts. Accepted: the alternative is
    recomputing the system message mid-session, which breaks the prefix cache.
13. **`estimate_tokens` counts the two new schemas on every request.** `_MEMORY_TOOLS` serialises to
    roughly 1.6 kB, about 550 estimated tokens, added to the fixed per-request overhead in the REPL
    only. That is ~3% of a 16384-token window and is absorbed by [BUDGET]'s existing eviction. It is
    also the reason the memory tools stay out of one-shot and skill children, which are the
    latency-sensitive paths.
14. **`MEMORY_CHECKPOINT_SKIP_STATUSES` is a tuple compared with `not in`.** A future status string
    that should be skipped and is not added there produces a wasted call and a `[memory] checkpoint
    skipped` line, never a crash. Fail-safe by construction.
15. **The `.bak` restores a missing file, not a corrupted one.** `memory_start` restores only when
    `long_term.md` is absent. An append interrupted mid-write leaves the file present with a partial
    trailing line, which is not detected, and the next `promote` will back up that state. Small appends
    on APFS are effectively atomic, so this is rare; the guarantee is against loss of the file, not
    against a torn last line.

---

16. **The checkpoint is a full prefill; it does not share the prefix cache (measured 2026-09-03).**
    A live checkpoint request against MTPLX 2.10.1 logged `cached_tokens=0, cache_source=none` for a
    2200-token prompt (5.1 s prefill, 196-token reply), while the surrounding live requests hit the
    cached system prefix. The tools-off request renders a different system turn, so the prefix diverges
    at the first message. `tool_choice: "none"` would not help: MTPLX treats it as "tools inactive" and
    drops the schema from the prompt as well. Accepted cost: one prefill of the (evicted) transcript plus
    a short generation per tool-using turn -- roughly 30-60 s on this host. The alternative,
    `include_tools=True`, shares the prefix but lets the model answer with a tool call, which yields an
    empty checkpoint.

## 14. Open questions

None that block implementation. Two deferred decisions are recorded here so they are not
re-litigated during execution:

1. **Should `remember` notes be folded into the system message on `/reset`?** Deferred. It would give
   a reset conversation the session's own findings back, but it means recomputing the system message
   mid-session and invalidating the prefix cache — the one thing Section 2 forbids. The notes are on
   disk and will be in the *next* session's handoff via the checkpoint.
2. **Should archived sessions be searchable (`/memory search <term>`)?** Deferred, explicit non-goal
   for this spec (Section 1.4). Nothing in this design forecloses it: archives are plain Markdown in a
   known directory.

---

## 15. Acceptance checks (run all, from the repo root)

```
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
python3 -m py_compile bin/qwen-agent                    # exits 0
/usr/bin/python3 -m py_compile bin/qwen-agent           # exits 0 (3.9.6 syntax gate)
python3 tests/test_qwen_agent_session_memory.py         # prints OK n/n (n >= 60), exits 0
python3 tests/test_qwen_agent_context_budget.py         # prints OK n/n, exits 0 -- no regression
grep -c '8192-token' bin/qwen-agent                     # prints 0
grep -n 'AUTO_APPROVE_TOOLS = ' bin/qwen-agent          # one line, ends "calculate", "remember")
grep -n 'if name == "promote":' bin/qwen-agent          # one line, inside should_auto_approve
python3 bin/qwen-agent --help                           # exits 0, flag list unchanged
```

A live smoke check, once the server is up, run via an explicit path to
`local_model_harness/qwen-agent-workspace/bin/qwen-agent` (`~/.local/bin/qwen-agent` may point at a
different copy):

1. Start the REPL. Confirm the banner shows ten tools and a `memory:` line naming
   `~/.qwen-agent/memory`.
2. Run one turn that uses a tool. Confirm `[memory] checkpoint saved (N chars)` prints and that
   `~/.qwen-agent/memory/session.md` gained a `## Turn 1` section.
3. Ask the model to remember something. Confirm an `[auto] remember ... -> OK: noted (1 notes this
   session)` line.
4. Ask the model to promote something. Confirm a confirmation prompt showing `appends:  - [YYYY-MM-DD]
   ...`, answer `n`, confirm nothing was appended; ask again, answer `y`, confirm the line landed and
   that `long_term.md.bak` exists.
5. `/memory` — both files, both sizes, both counts.
6. `/exit`, restart. Confirm the previous `session.md` is now under `sessions/`, a fresh one exists,
   and the promoted principle plus the previous session's last checkpoint are both in the system
   message (verify with `/reset` then a trivial question, or by reading the store).

---

## 16. Verification notes for the caller

Every anchor in this document was read from the live file on 2026-09-02. The following points in the
briefing did not match what is actually in the code, or were left open; each is resolved here so the
executor never has to decide.

**Line numbers in the briefing were approximate; these are the verified ones.**

| Briefing said | Actual (2761-line file) |
|---|---|
| `AUTO_APPROVE_TOOLS` at ~88 | **88** — exact |
| `_BASE_TOOLS` at ~177–480 | **200–410**; `_BASE_TOOL_BY_NAME` at 412 |
| `build_tools_for_context` at ~459 | **482**; `TOOLS = None` / `TOOL_BY_NAME = None` at **503–504** |
| `should_auto_approve` at ~723 | **723** — exact |
| `confirm` at ~841 | **841** — exact |
| `dispatch`'s exec switch "around 770–800" | **1548–1574**. Lines 770–800 are `_call_key` and `_auto_trace_outcome`. |
| `build_system_message` at ~1650 | **1644** |
| `/help` text at ~1760 | `HELP_TEXT` at **1778** |
| `handle_slash_command` at ~1860 | **1884** |
| `repl` at ~2600+ | **2608** |

**Substantive findings and how they were resolved.**

1. **`_auto_key` would crash on the first `remember` call.** The briefing did not mention `_auto_key`
   (line 745). Its fallback is `return _trace_clip(str(resolved_paths["path"]))`, and `dispatch`
   passes `resolved_paths == {}` for any tool that is not `read_file`/`write_file`. Because
   `remember` is auto-approved, `dispatch` reaches `_auto_key` at line 1536 — *outside* the `try:`
   that wraps execution — so the missing branch is an uncaught `KeyError` that kills the turn. Section
   5.2 adds the branch; test M5's dispatch case asserts it. **This is the highest-risk omission in the
   briefing and the executor must not skip Section 5.2.**
2. **`_call_key`'s docstring is factually wrong after this change** ("all nine tool names", "the top
   level has eight"). Since `_call_key` is also `_log_decision`'s key source and the briefing
   explicitly asked for the decision-log key, the docstring is corrected in the same edit (Section
   5.3). This is the only docstring in the file this spec rewrites.
3. **`build_confirmation_body` has no fallback preview.** Its final `else: return ""` means a
   `promote` prompt with no new branch would show an empty body — a human approving a blank box. The
   briefing asked for a preview but did not say where; Section 5.4 adds an `elif` branch modelled on
   the `write_file` and `generate_image` branches, and shares `memory_long_term_line` with the append
   so the preview and the write cannot diverge.
4. **`print_banner` was not mentioned in the briefing but becomes false.** It hardcodes
   `"tools: ... delegate_to_skill"` and an approval list that would omit `promote`. It is called from
   exactly one place (`repl`, line 2610) and never from `oneshot`, so Section 7.2 gives it a
   `memory=False` parameter and leaves the three existing lines byte-identical on the default path.
   Flagged because it is an addition to the approved design, made for truthfulness.
5. **The tool extension must happen in `repl()`, not `main()`.** The briefing offered either.
   `MEMORY_ENABLED` is not known until `memory_start` has tried to create the directory, which is
   inside `repl()` after `setup()`. `main()` would have to advertise the tools before knowing whether
   they can work. Resolved to `repl()` (Section 7.1), which also keeps `preflight`'s Check B probe on
   the unchanged eight-tool list.
6. **`evict_to_budget` mutates in place, so the checkpoint copy must be deep.** The briefing said
   "a COPY of messages". A `list(messages)` copy shares the message dicts, and `evict_to_budget`
   ([BUDGET] Section 2, line 2240) rewrites `content` on those dicts, so eviction on the "copy" would
   delete real tool results from the live transcript. Resolved to `json.loads(json.dumps(messages))`
   (Section 6.4), which needs no new import. Test M8 asserts the live list is unchanged *while* the
   copy shows an eviction, so a shallow copy fails the test.
7. **The checkpoint's budget uses `ck_args`, not `args_ns`.** The briefing wrote
   `evict_to_budget(copy, args_ns, ...)`. `context_budget` subtracts `max_tokens`, so passing the
   original `args_ns` (1536) would evict more aggressively than the checkpoint's own 320-token reply
   requires. Resolved to `ck_args` for `evict_to_budget`, `context_budget`, and `chat_completion`.
8. **The checkpoint's exception list needed two more types.** The briefing named `HTTPError`,
   `URLError`, `OSError`, `KeyError`, `ValueError`. `resp["choices"][0]["message"]` raises
   `IndexError` on an empty `choices` list and `TypeError` on a non-subscriptable body — `run_turn`
   catches exactly those two for the same expression at line 2529. Both added. `KeyboardInterrupt` is
   caught separately and first, because it is not an `Exception` subclass and letting it escape would
   tear down the REPL from a step whose contract is "never affects the turn result".
9. **`"context_budget"` is deliberately *not* in the skip list.** The briefing's exclusion list was
   the five transport/context statuses, which leaves `context_budget` checkpointed. That is correct
   and intentional (the checkpoint has a far larger prompt budget than the turn did), and Section 6.4
   adds an explicit pre-send budget re-check so an impossible case degrades to one stderr line rather
   than a wasted round trip. Documented as risk 4.
10. **`/memory` printing files "in full" versus "oversized files displayed truncated".** These two
    briefing statements conflict. Resolved in favour of the protection requirement: a per-file display
    cap of `MEMORY_SHOW_CHAR_LIMIT = 100000` characters with an explicit
    `"the file on disk is unchanged"` marker. At 500 characters per entry that is ~200 entries, so no
    realistic store is truncated.
11. **`/remember` writes to *long-term* memory, not to the session store.** This reads oddly next to
    the `remember` *tool*, which writes to the session store. It is what the approved design specifies
    ("the human typing it is the approval"), and it is the right split — the human has no need of a
    per-session scratchpad and every need of a way to add a principle without waiting for the model to
    propose one. Kept as designed; `HELP_TEXT` and the banner both spell out that `/remember` adds a
    **long-term** entry, and `slash_remember`'s success string says "added to long-term memory" so the
    two paths are distinguishable in a transcript.
12. **Notes are appended at the end of `session.md`, not inserted under `## Notes`.** The briefing left
    this open and recommended append-at-end. Resolved to append-at-end: `## Notes` is written once by
    `memory_start` as the marker where the log begins, and `- [HH:MM]` notes and `## Turn N`
    checkpoints interleave in real time order. This makes every write a single `open(path, "a")` with
    no parsing, and makes the file readable as a session timeline.
13. **`_BASE_TOOLS` holds seven tools, not eight.** `build_tools_for_context(None)` returns eight
    (seven base plus `delegate_to_skill`); `calculate` lives in the separate `_CALCULATE_TOOL` and is
    skill-only. The "eight tools" wording in the system message is therefore correct today and becomes
    "ten tools" only under `memory=True`.
14. **The invariant comment at lines 100–106 is untouched, correctly.** It states a one-way
    containment (every skill tool name ∈ `AUTO_APPROVE_TOOLS`). Adding `"remember"` to the tuple
    cannot violate it, and `"remember"` must **not** be added to `SKILL_TOOL_NAMES`.
15. **`main()` and `oneshot()` are not modified at all.** The briefing suggested `main()` might need
    the tool extension; it does not, given resolution 5. This keeps [ONESHOT]'s envelope and the
    delegate-child contract provably unchanged, which is success criterion 7.
