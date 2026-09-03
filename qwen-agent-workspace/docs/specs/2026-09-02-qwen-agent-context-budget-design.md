# Spec: `qwen-agent` — context-window discovery, token budgeting, tool-result eviction, and truncated-output handling

**Status:** Ready for implementation. No open design decisions.
**Date:** 2026-09-02
**Type:** Surgical bugfix to one working script, plus one new offline test file. Not a rewrite.

**Target artifacts:**

| Path | Action |
|---|---|
| `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/bin/qwen-agent` | edit in place (single file, mode `0755`, **2539 lines** as read on 2026-09-02) |
| `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/tests/test_qwen_agent_context_budget.py` | **create** (Section 9) |

**Do not edit any other file.** In particular do not touch
`/Users/reubenpatterson/qwen-agent-workspace/bin/qwen-agent` — that is a *different, older copy*
(2570 lines) outside this git repository. Every line number and quoted anchor in this document refers
to the 2539-line file under `local_model_harness/`.

**Parent specs, all still authoritative except where this document explicitly revises them:**

- `docs/specs/2026-08-21-qwen-agent-tool-harness-design.md` — **[HARNESS]**
- `docs/specs/2026-08-21-qwen-agent-oneshot-api-design.md` — **[ONESHOT]**
- `docs/specs/2026-08-21-qwen-agent-tiered-approval-design.md` — **[TIERED]**
- `docs/specs/2026-08-21-qwen-agent-search-grounding-design.md` — **[SEARCH]**

**Interpreter constraint:** unchanged — the file must stay valid on Python **3.9.6** (`/usr/bin/python3`)
and **3.13.0** (`python3`). No 3.10+ syntax (no `X | Y` annotations, no `match`). Standard library only.
**No new imports in `bin/qwen-agent`** — `json`, `os`, `sys`, `urllib.request`, `urllib.error` are
already imported at lines 19–35 and are the only modules the new code needs.

**Style constraints:** `%`-formatting only (no f-strings), `# ---` section-header comment banners,
double-quoted strings, diagnostics to `sys.stderr.write(...)`, confirmation/trace UI to
`print(..., file=_ui())`. Match the surrounding code exactly.

---

## 1. Purpose

### 1.1 The failure this fixes (already diagnosed — do not re-investigate)

`qwen-agent` talks to an MTPLX 2.10.1 OpenAI-compatible server at `http://127.0.0.1:8177/v1` with a
**16384-token** context window. `run_turn()` appends one assistant echo plus one `role: "tool"` message
per tool call to a `messages` list that, in the REPL, **persists across turns** and is only ever
cleared by `/reset`. Nothing evicts, summarises, or even counts. Each tool result is capped at
`RESULT_CHAR_LIMIT` = 4000 characters, and indented Python tokenises at roughly 2 characters/token, so
one result costs 1000–2200 tokens against a fixed overhead of ~2000 (system message + 8-tool schema).

Observed prompt-token trace for a single REPL session:

```
2021 -> 10510 -> 13536 -> 15081 -> 16355     (remaining context: 29)
```

MTPLX logs `max_tokens clamped to remaining context` — a **WARNING, not an error** — and generates
into whatever is left. The model's tool call comes back cut in half with `finish_reason: "length"`,
which the agent never reads, so it dispatches a mangled call. The *next* request gets HTTP 400 with
`"This model's maximum context length is 16384 tokens, but the prompt alone has N tokens..."` and
`"code": "context_length_exceeded"`. Only at that point does `_is_context_overflow()` fire and the turn
dies — and the message it prints says **"8192-token window"**, which has been wrong since the server
was reconfigured.

Three defects, one root cause (no token accounting):

1. **No budget.** The transcript grows until the server refuses it.
2. **Silent truncation.** `finish_reason == "length"` is never read, so a clipped tool call is
   dispatched as if it were complete.
3. **Stale diagnostics.** Two hardcoded "8192-token window" strings.

### 1.2 Success criteria

Correct and complete when all of the following hold:

1. `python3 -m py_compile bin/qwen-agent` exits 0.
2. `grep -c '8192-token' bin/qwen-agent` prints `0`.
3. `python3 tests/test_qwen_agent_context_budget.py` exits 0 and prints `OK n/n`.
4. On this host with MTPLX serving `qwen38-6bit`, a REPL session that runs ≥ 12 tool rounds never
   produces an HTTP 400 `context_length_exceeded`, and prints at least one
   `[context] evicted N tool result(s) ...` line instead.
5. Every diagnostic that names the window names **16384** (the discovered value), not 8192.
6. No behaviour change for turns that fit: a 3-round turn produces a byte-identical transcript to the
   pre-change build apart from the absence of any `[context]` line.

**Quantified KPI**, scenario: REPL, 12 consecutive rounds each returning a 4000-char tool result.

| Metric | Before | After (required) |
|---|---|---|
| HTTP 400 `context_length_exceeded` | 1 (fatal, turn lost) | **0** |
| Requests sent with estimated prompt > `window - max_tokens - 1024` | ≥ 3 | **0** |
| Dispatched tool calls from a `finish_reason == "length"` response | ≥ 1 | **0** |
| Turns ending with `answer: null` due to context | 1 | **0** (forced summary always attempted) |
| Window named in the overflow message | `8192` | `16384` (discovered) |

### 1.3 Non-goals — explicitly out of scope, do not implement

- **No summarisation of evicted content.** An evicted result becomes a fixed one-line stub. No extra
  model call, ever.
- **No streaming.** `"stream": False` stays.
- **No tokenizer dependency.** No `tiktoken`, no `transformers`, no `sentencepiece`, no third-party
  package of any kind. No new imports at all.
- **No change to the tool definitions**, `_BASE_TOOLS`, `build_tools_for_context`, or any tool schema.
- **No change to `RESULT_CHAR_LIMIT`** (stays 4000) or to `_truncate`.
- **No change to the approval flow**, `should_auto_approve`, `confirm`, `dispatch`, the duplicate
  guard, the circuit breaker, or the repeat reminders.
- **No change to the module docstring** at lines 2–17 and no new spec reference added to it.
- **No one-shot stderr notice for the new statuses.** The JSON envelope already carries `status` and
  `error`; one-shot consumers parse JSON. Only the REPL gets a new human-facing notice (Section 8).
- **No removal of the existing HTTP-400 overflow handler.** Budgeting is an estimate; the 400 handler
  stays as the backstop and only has its message text corrected.
- **No adjacent cleanup, reformatting, or renaming.** Every changed line must trace to this document.

---

## 2. The design, in one paragraph

At `setup()` the agent asks the server how big the window is and stores it in a module global
`CONTEXT_WINDOW`. Before *every* chat completion it estimates the prompt size with a pure,
dependency-free heuristic and compares it to
`budget = CONTEXT_WINDOW - args_ns.max_tokens - CONTEXT_FLOOR`. If it is over, it replaces the
**content** of the oldest not-yet-evicted `role: "tool"` messages with a short stub — oldest first,
never the current round's, never a system/user/assistant message — until it fits. If it still does not
fit, it does not send the request at all: it goes straight to the existing forced-summary path with a
new status `"context_budget"`. Separately, if a response comes back with `finish_reason == "length"`
*and* tool calls, those tool calls are discarded unread and the turn ends via forced summary with
status `"truncated"`.

**Why stub the content instead of deleting the message:** the OpenAI wire format requires every
`role: "tool"` message to follow an assistant message carrying a matching `tool_call_id`. Deleting a
tool message (or an assistant echo) orphans the other half of the pair and several servers, MTPLX
included, reject the resulting transcript outright. Rewriting `content` in place preserves the pairing,
preserves the round structure the model reasons over, is O(1) per eviction, and — because it mutates
the dicts inside the caller's list — automatically survives `del messages[snapshot:]` rollback and
persists across REPL turns, which is exactly what is wanted.

### 2.1 Alternatives considered and rejected

| Alternative | Why rejected |
|---|---|
| Use a real tokenizer (`tiktoken` / `transformers`) for exact counts | Third-party dependency in a file whose stated invariant is stdlib-only; the correct vocabulary for a 6-bit MLX Qwen3 quant is not obviously available; adds seconds of startup cost for an accuracy we do not need, since `CONTEXT_FLOOR` absorbs the error. |
| Read `usage.prompt_tokens` from the previous response and extrapolate | Tells you the size of a request that already succeeded, not of the one about to be sent; the fatal request returns no `usage` at all; and MTPLX's clamp means a response can succeed while already being over-budget. Useful only as a future calibration signal — deferred. |
| Drop whole messages (assistant echo + its tool results) from the front | Breaks the assistant/tool `tool_call_id` pairing invariant; risks a 400 that is *harder* to diagnose than the one we are fixing. |
| Sliding window over turns (keep system + last K turns) | Same pairing problem, plus it silently discards the user's own earlier instructions, which are cheap and load-bearing. |
| Summarise evicted results with an extra model call | Costs a full generation per eviction, needs context to produce it, and can itself overflow. Explicit non-goal. |
| Lower `RESULT_CHAR_LIMIT` | Bounds each result, not their sum — 20 rounds still overflow — and degrades every short turn to fix a long-turn problem. |
| Hardcode 16384 instead of discovering it | This bug *is* a hardcoded window (8192) that went stale. Discovery + `--context-window` override is the fix for the class, not the instance. |
| Reject the request with an error instead of forced-summarising | [SEARCH] Section 6 already established that an abnormal turn must still yield natural-language text; returning `answer: null` is the bug that spec fixed. |
| Validate `--context-window` against a minimum in `main()` | A too-small window degrades gracefully (every turn ends `context_budget` with a message naming the window), while a hard `sys.exit(2)` would also fire in `delegate_to_skill` children that inherit a small discovered window, turning a degraded parent into a dead child. |

---

## 3. New constants and globals

### 3.1 Immutable constants — Section 5 block

**Anchor** (lines 48–52, verbatim):

```python
RESULT_CHAR_LIMIT = 4000       # characters, applied to every tool result string
FETCH_BYTE_LIMIT = 2_000_000  # bytes read from the socket before hard stop
FETCH_USER_AGENT = "qwen-agent/1.0"

# Self-contained layout: this script lives at <root>/bin/qwen-agent, and the docs
```

**Insert** immediately after the `FETCH_USER_AGENT` line and before the blank line preceding the
`# Self-contained layout:` comment:

```python

# Context budget. The window is discovered from GET /v1/models at setup(); this is
# only the fallback when the server does not report one. CONTEXT_FLOOR is headroom
# held back from the budget on every request: the estimator below models neither the
# chat template's per-message control tokens nor a tokenizer's disagreement with a
# character heuristic, and 1024 tokens is ~6% of a 16384-token window -- cheap enough
# to give away, large enough to cover both plus the forced-summary prompt.
DEFAULT_CONTEXT_WINDOW = 16384
CONTEXT_FLOOR = 1024
# 3 chars/token is deliberately pessimistic: English prose runs ~4, indented Python
# ~2.5, and json.dumps' default ensure_ascii=True expands every non-ASCII character
# to a 6-character \uXXXX escape, which over-counts CJK rather than under-counting it.
# Under-counting is the only error mode that can still produce an HTTP 400, so every
# constant here is chosen to err high.
CHARS_PER_TOKEN = 3
PER_MESSAGE_TOKENS = 8         # role/delimiter tokens the chat template adds per message
EVICTED_STUB = "[result evicted to free context: %d chars from %s]"
EVICTED_PREFIX = "[result evicted to free context:"   # marks an already-evicted result
```

### 3.2 Mutable global — beside `WORKSPACE`

**Anchor** (lines 126–129, verbatim):

```python
WORKSPACE = None

ONESHOT_SCHEMA = "qwen-agent.oneshot.v1"   # value of the JSON envelope's "schema" field
EXIT_ABNORMAL = 3                          # one-shot: turn ended with no final answer
```

**Insert** between `WORKSPACE = None` and `ONESHOT_SCHEMA`, keeping one blank line either side:

```python
# Tokens the served model can actually hold. Set once by setup() from GET /v1/models
# or from --context-window; read by the budget helpers, by the two overflow messages,
# and forwarded to delegate_to_skill children so parent and child agree.
CONTEXT_WINDOW = DEFAULT_CONTEXT_WINDOW
```

---

## 4. New code — Section 13 block

**Anchor** (lines 2123–2134, verbatim):

```python
def _is_context_overflow(body):
    return (
        "maximum context length" in body
        or "max_model_len" in body
        or "longer than the maximum" in body
    )


# ---------------------------------------------------------------------------
# Section 11: REPL main loop
# ---------------------------------------------------------------------------
```

**Insert** the entire block below between the end of `_is_context_overflow` and the
`# Section 11: REPL main loop` banner, separated by two blank lines on each side (the file's existing
convention).

```python
# ---------------------------------------------------------------------------
# Section 13: context budget -- window discovery, token estimate, eviction
# ---------------------------------------------------------------------------

def discover_context_window(base_url, model, api_key):
    """Tokens the served model can hold, read from GET <base_url>/models.

    Prefers the entry whose id matches `model`, falls back to the first entry, and
    reads the first present of context_length / max_context_length / max_model_len.
    Returns DEFAULT_CONTEXT_WINDOW and writes one stderr note on any failure: this
    runs after preflight has already proved the endpoint answers, so a missing field
    is a server-version difference, not an outage, and a conservative default is
    always better than refusing to start.
    """
    headers = {"Authorization": "Bearer %s" % api_key} if api_key else {}
    try:
        req = urllib.request.Request(base_url + "/models", headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        items = data.get("data") or []
        entry = None
        for item in items:
            if item.get("id") == model:
                entry = item
                break
        if entry is None and items:
            entry = items[0]
        if entry is None:
            raise ValueError("no model entries in the response")
        for key in ("context_length", "max_context_length", "max_model_len"):
            value = entry.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)) and value > 0:
                return int(value)
        raise ValueError("no context-length field on model entry")
    except Exception as e:
        sys.stderr.write(
            "qwen-agent: could not read the context window from %s/models (%s: %s); "
            "assuming %d tokens. Override with --context-window.\n"
            % (base_url, type(e).__name__, e, DEFAULT_CONTEXT_WINDOW)
        )
        return DEFAULT_CONTEXT_WINDOW


def estimate_tokens(messages, include_tools=True):
    """Pessimistic prompt-size estimate in tokens. Pure, deterministic, cheap.

    Counts the JSON serialisation of each message at CHARS_PER_TOKEN characters per
    token plus PER_MESSAGE_TOKENS of delimiter overhead, and adds the serialised tool
    schema when it will be sent. Deliberately over-estimates (see CHARS_PER_TOKEN):
    over-estimating costs a premature eviction, under-estimating costs an HTTP 400.
    """
    total = 0
    for msg in messages:
        total += len(json.dumps(msg)) // CHARS_PER_TOKEN + PER_MESSAGE_TOKENS
    if include_tools and TOOLS:
        total += len(json.dumps(TOOLS)) // CHARS_PER_TOKEN
    return total


def context_budget(args_ns):
    """Prompt tokens one request may occupy: the window, less the reply, less headroom."""
    return CONTEXT_WINDOW - args_ns.max_tokens - CONTEXT_FLOOR


def _tool_name_for_call_id(messages, index):
    """Name of the tool that produced messages[index], from the matching assistant echo.

    Walks backwards to the nearest preceding assistant message whose tool_calls carry
    the same id. Returns "tool" when no echo matches -- that only affects the wording
    of an eviction stub, never control flow.
    """
    call_id = messages[index].get("tool_call_id")
    j = index - 1
    while j >= 0:
        msg = messages[j]
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls") or []:
                if tc.get("id") == call_id:
                    return tc.get("function", {}).get("name") or "tool"
        j -= 1
    return "tool"


def evict_to_budget(messages, args_ns, protect_from, include_tools=True):
    """Stub out the oldest tool results until the estimate fits the budget.

    Only role == "tool" messages below index `protect_from` are eligible, oldest
    first; system, user and assistant messages are never touched, and neither is the
    most recent round, which the model needs in order to make progress. Rewrites
    `content` in place rather than deleting the message, so every tool message keeps
    the assistant echo it belongs to (see the spec's Section 2). Mutating in place
    also means an eviction survives run_turn's `del messages[snapshot:]` rollback and
    persists across REPL turns -- both intended: the text is gone either way, and
    restoring it would only re-overflow the very next request.

    Terminates: each pass either stubs one more message (which is then skipped by its
    EVICTED_PREFIX) or finds no candidate and breaks.
    Returns the number of results evicted.
    """
    budget = context_budget(args_ns)
    evicted = 0
    while estimate_tokens(messages, include_tools) > budget:
        target = None
        for i in range(0, min(protect_from, len(messages))):
            msg = messages[i]
            if msg.get("role") != "tool":
                continue
            if (msg.get("content") or "").startswith(EVICTED_PREFIX):
                continue
            target = i
            break
        if target is None:
            break
        content = messages[target].get("content") or ""
        messages[target]["content"] = EVICTED_STUB % (
            len(content), _tool_name_for_call_id(messages, target))
        evicted += 1
    if evicted:
        print("[context] evicted %d tool result(s) to stay within the %d-token window"
              % (evicted, CONTEXT_WINDOW), file=_ui())
    return evicted
```

**Notes the implementer must not deviate from:**

- `estimate_tokens` reads the module global `TOOLS`. When `TOOLS` is `None` (the value before
  `main()` calls `build_tools_for_context`) the tools term is **0**. `if include_tools and TOOLS:`
  expresses exactly that; do not change it to `is not None`.
- `json.dumps(msg)` uses **default arguments** — in particular `ensure_ascii=True`. Do not pass
  `ensure_ascii=False`; the escaping is load-bearing (Section 3.1 comment).
- Integer division `//` only. No `round`, no `math`.
- `discover_context_window` catches broad `Exception` deliberately, matching `searxng_probe`
  (line 2094). Do not narrow it.

---

## 5. `setup()` — discover the window

**Anchor** (lines 2140–2158, verbatim):

```python
    global WORKSPACE

    workspace = Path(args_ns.workspace).expanduser()
```

**Change** the `global` line to:

```python
    global WORKSPACE, CONTEXT_WINDOW
```

**Anchor** (lines 2150–2158, verbatim, the tail of `setup`):

```python
    args_ns.base_url = args_ns.base_url.rstrip("/")
    # Set by exec_delegate_to_skill in the child env. A child re-running the tools
    # probe and the searxng probe only re-pays their cost and re-prints the same
    # warning on the parent's stderr.
    is_delegate_child = os.environ.get("QWEN_AGENT_PREFLIGHT_DONE") == "1"
    preflight(args_ns.base_url, args_ns.model, args_ns.api_key,
              skip_tool_probe=is_delegate_child)
    if not is_delegate_child:
        searxng_probe()
```

**Append** to the end of `setup`, after the `searxng_probe()` block, at the same indent as
`is_delegate_child`:

```python

    # --context-window wins over discovery, and a delegate child is always given the
    # parent's already-resolved value, so parent and child budget identically.
    if args_ns.context_window is not None:
        CONTEXT_WINDOW = args_ns.context_window
    else:
        CONTEXT_WINDOW = discover_context_window(
            args_ns.base_url, args_ns.model, args_ns.api_key)
```

Discovery runs for delegate children too when no flag was passed — it is one ~2 ms GET, the same
request `preflight` Check A already makes, and skipping it would leave the child on the fallback.

---

## 6. CLI flag and delegate forwarding

### 6.1 `parse_args`

**Anchor** (lines 2494–2495, verbatim):

```python
    parser.add_argument("--tool-timeout", type=int, default=DEFAULT_TOOL_TIMEOUT)
    parser.add_argument("--api-key", type=str, default=None)
```

**Insert between** those two lines:

```python
    parser.add_argument("--context-window", type=int, default=None)
```

`default=None` means "discover it". No validation is added in `main()` — see the rejected
alternatives table in Section 2.1.

### 6.2 `exec_delegate_to_skill`

**Anchor** (lines 1065–1069, verbatim):

```python
        "--max-tokens", str(args_ns.max_tokens),
        "--request-timeout", str(args_ns.request_timeout),
        "--max-rounds", str(args_ns.max_rounds),
        "--tool-timeout", str(args_ns.tool_timeout),
    ]
```

**Insert** one line after `--tool-timeout`, before the closing `]`:

```python
        "--context-window", str(CONTEXT_WINDOW),
```

Forward the **resolved module global**, not `args_ns.context_window` (which is `None` in the common
case). The parent has already run `setup()`, so `CONTEXT_WINDOW` is authoritative; the child then
takes the flag branch in `setup()` and skips its own discovery. No `global` declaration is needed to
read it.

---

## 7. `run_turn` and `_forced_summary`

### 7.1 `_forced_summary` — new `protect_from` parameter, eviction guard, corrected message

**Anchor** (line 2176, verbatim):

```python
def _forced_summary(messages, args_ns, round_num, records, status, error, args_think):
```

**Replace with** (a required 8th positional parameter — there are exactly two existing call sites,
both inside `run_turn`, and both are updated in Section 7.2):

```python
def _forced_summary(messages, args_ns, round_num, records, status, error, args_think,
                    protect_from):
```

**Append to the existing docstring**, as a new final paragraph before the closing `"""` (the docstring
currently ends with the "[HARNESS] 11 already establishes ..." sentence at lines 2187–2189):

```python
    `protect_from` is the index of the most recent round's assistant echo; messages at
    or after it are never evicted. This call is budget-guarded like any other: if the
    tools-disabled prompt still does not fit after eviction, it returns status
    "context_budget" with answer None and the caller's status is overridden.
```

**Anchor** (lines 2191–2196, verbatim):

```python
    sys.stderr.write("[forcing a final answer with tools disabled]\n")
    messages.append({"role": "user", "content": FORCED_SUMMARY_PROMPT})
    round_num += 1
    try:
        resp = chat_completion(args_ns.base_url, messages, args_ns, include_tools=False)
        msg = resp["choices"][0]["message"]
```

**Replace** the first three lines (through `round_num += 1`) with:

```python
    sys.stderr.write("[forcing a final answer with tools disabled]\n")
    messages.append({"role": "user", "content": FORCED_SUMMARY_PROMPT})
    round_num += 1
    evict_to_budget(messages, args_ns, protect_from, include_tools=False)
    estimate = estimate_tokens(messages, include_tools=False)
    if estimate > context_budget(args_ns):
        sys.stderr.write(
            "[context budget exhausted: %d estimated prompt tokens against a %d-token "
            "window, with nothing left to evict. Use /reset to start over.]\n"
            % (estimate, CONTEXT_WINDOW)
        )
        return _turn_result("context_budget", None, round_num, records,
                            "context budget exhausted: %d estimated prompt tokens "
                            "against a %d-token window" % (estimate, CONTEXT_WINDOW))
    try:
```

The `try:` line and everything after it are unchanged. The synthetic `FORCED_SUMMARY_PROMPT` message
stays in `messages` on the over-budget return: `_forced_summary` documents that it never rolls back,
and the user has just been told to `/reset`.

**Anchor** (lines 2204–2211, verbatim, inside `_forced_summary`'s `HTTPError` handler):

```python
        if _is_context_overflow(err_body):
            sys.stderr.write(
                "[context full: the conversation exceeds the server's "
                "8192-token window. Use /reset to start over.]\n"
            )
```

**Replace the `sys.stderr.write` call** with:

```python
            sys.stderr.write(
                "[context full: the conversation exceeds the server's "
                "%d-token window. Use /reset to start over.]\n" % CONTEXT_WINDOW
            )
```

Nothing else in that handler changes.

### 7.2 `run_turn`

Six edits, in file order.

**(a) Initialise `protect_from`.** Anchor (lines 2293–2299, verbatim):

```python
    records = []
    history = []      # [TIERED] duplicate guard AND this spec's circuit breaker (shared)
    streak = {"tool": None, "count": 0, "fired": set()}
    round_num = 0
    breaker_tripped = False
    while round_num < args_ns.max_rounds:
        round_num += 1
```

**Insert** after `breaker_tripped = False`, before the `while`:

```python
    # Index at or above which eviction is forbidden: the current round's assistant
    # echo and its tool results. len(messages) at turn start, so every earlier
    # turn's tool results are fair game the moment the user asks something new
    # (only role == "tool" messages are ever eligible, so exposing the new user
    # message itself is moot).
    protect_from = len(messages)
```

**(b) Budget check before the model call.** **Insert** between `round_num += 1` and the existing
`try:` that wraps `chat_completion`:

```python
        evict_to_budget(messages, args_ns, protect_from)
        estimate = estimate_tokens(messages, True)
        if estimate > context_budget(args_ns):
            return _forced_summary(
                messages, args_ns, round_num, records, "context_budget",
                "context budget exhausted: %d estimated prompt tokens against a "
                "%d-token window" % (estimate, CONTEXT_WINDOW),
                args_ns.think, protect_from)
```

Note there is **no** `del messages[snapshot:]` on this path: the transcript is real work and
`_forced_summary` is about to answer from it, exactly as the `max_rounds` and `circuit_open` paths do.

**(c) Corrected overflow message.** Anchor (lines 2310–2316, verbatim):

```python
            if _is_context_overflow(err_body):
                sys.stderr.write(
                    "[context full: the conversation exceeds the server's "
                    "8192-token window. Use /reset to start over.]\n"
                )
                status = "context_length"
                error = "context full: the conversation exceeds the server's context window"
```

**Replace the `sys.stderr.write` call** with:

```python
                sys.stderr.write(
                    "[context full: the conversation exceeds the server's "
                    "%d-token window. Use /reset to start over.]\n" % CONTEXT_WINDOW
                )
```

`status` and `error` are unchanged.

**(d) Read `finish_reason`.** Anchor (lines 2334–2340, verbatim):

```python
        try:
            msg = resp["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as e:
            sys.stderr.write("[malformed server response: %s]\n" % e)
            del messages[snapshot:]
            return _turn_result("malformed_response", None, round_num, records,
                                "malformed server response: %s" % e)
```

**Replace the two lines inside `try:`** with:

```python
        try:
            choice = resp["choices"][0]
            msg = choice["message"]
            finish_reason = choice.get("finish_reason")
```

The `except` clause is unchanged and already catches the `TypeError` a non-dict `choice` would raise.

**(e) Truncated-output handling.** Anchor (lines 2342–2351, verbatim):

```python
        if args_ns.think and msg.get("reasoning_content"):
            sys.stderr.write("[thinking]\n")
            sys.stderr.write(msg["reasoning_content"])
            sys.stderr.write("\n[/thinking]\n")

        tool_calls = msg.get("tool_calls") or []
        messages.append(assistant_echo(msg, tool_calls, round_num))

        if not tool_calls:
            return _turn_result("ok", msg.get("content") or "", round_num, records, None)
```

**Replace** everything from `tool_calls = msg.get(...)` through the `return _turn_result("ok", ...)`
with:

```python
        tool_calls = msg.get("tool_calls") or []

        # A response cut off at max_tokens can carry a tool call that was clipped
        # mid-arguments. MTPLX clamps max_tokens to the remaining context and logs
        # only a warning, so this is the normal shape of a near-full window. The call
        # is unverifiable, so it is discarded unread: the echo keeps the text the model
        # did produce, without tool_calls, and the turn ends with a forced summary.
        if finish_reason == "length" and tool_calls:
            protect_from = len(messages)
            messages.append(assistant_echo(msg, [], round_num))
            return _forced_summary(
                messages, args_ns, round_num, records, "truncated",
                "model output was cut off at max_tokens (%d); tool calls discarded"
                % args_ns.max_tokens,
                args_ns.think, protect_from)

        protect_from = len(messages)
        messages.append(assistant_echo(msg, tool_calls, round_num))

        if not tool_calls:
            if finish_reason == "length":
                sys.stderr.write("[note: answer was cut off at max_tokens=%d]\n"
                                 % args_ns.max_tokens)
            return _turn_result("ok", msg.get("content") or "", round_num, records, None)
```

`assistant_echo(msg, [], round_num)` returns `{"role": "assistant", "content": ...}` with **no**
`tool_calls` key — that is the required content-only echo; do not hand-build the dict.

**(f) Pass `protect_from` to the two existing `_forced_summary` calls.** Anchors (lines 2371–2375 and
2389–2391, verbatim):

```python
        if breaker_tripped:
            return _forced_summary(
                messages, args_ns, round_num, records, "circuit_open",
                "stopped after %d failed calls to the same tool in this turn"
                % FAILED_CALL_CAP, args_ns.think)
```

becomes

```python
        if breaker_tripped:
            return _forced_summary(
                messages, args_ns, round_num, records, "circuit_open",
                "stopped after %d failed calls to the same tool in this turn"
                % FAILED_CALL_CAP, args_ns.think, protect_from)
```

and

```python
    return _forced_summary(messages, args_ns, round_num, records, "max_rounds",
                           "reached the %d-round tool limit without a final answer"
                           % args_ns.max_rounds, args_ns.think)
```

becomes

```python
    return _forced_summary(messages, args_ns, round_num, records, "max_rounds",
                           "reached the %d-round tool limit without a final answer"
                           % args_ns.max_rounds, args_ns.think, protect_from)
```

The `if round_num == 0:` early return at lines 2385–2388 is unchanged.

### 7.3 Resulting per-round order of operations

1. `round_num += 1`
2. `evict_to_budget(messages, args_ns, protect_from)` — with tools counted
3. over budget still? → `_forced_summary(..., "context_budget", ...)`, return
4. `chat_completion` (existing exception handling unchanged)
5. extract `choice`, `msg`, `finish_reason`
6. thinking trace (unchanged)
7. `finish_reason == "length"` and tool_calls → content-only echo, `_forced_summary(..., "truncated", ...)`, return
8. `protect_from = len(messages)`; append the assistant echo
9. no tool calls → optional cut-off note → `"ok"`, return
10. dispatch loop, tool messages appended (unchanged)
11. circuit breaker / reminder (unchanged apart from the extra argument)

---

## 8. REPL notice for the new status

**Anchor** (lines 2424–2435, verbatim):

```python
        if outcome["status"] == "max_rounds":
            sys.stderr.write(
                "[stopped: reached the %d-round tool limit for this turn. The answer "
                "above is a forced summary. Type another message to continue, or "
                "/reset to clear the conversation.]\n" % args_ns.max_rounds
            )
        elif outcome["status"] == "circuit_open":
            sys.stderr.write(
                "[stopped: one tool failed %d times in this turn. The answer above is "
                "a forced summary. Type another message to continue, or /reset to "
                "clear the conversation.]\n" % FAILED_CALL_CAP
            )
```

**Append** a third branch, same indent:

```python
        elif outcome["status"] == "context_budget":
            sys.stderr.write(
                "[stopped: this conversation no longer fits in the server's %d-token "
                "window, even after evicting old tool results. The answer above, if "
                "any, is a forced summary. Use /reset to clear the conversation.]\n"
                % CONTEXT_WINDOW
            )
```

No branch is added for `"truncated"` (the `[forcing a final answer with tools disabled]` line already
appears) and none is added in `oneshot()` (Section 1.3).

---

## 9. The test file

**Create** `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/tests/test_qwen_agent_context_budget.py`.
Plain python, **no pytest**, no network, no subprocess, no filesystem writes outside `tempfile`.

**Run:** `python3 tests/test_qwen_agent_context_budget.py` from the repo root
(`/Users/reubenpatterson/local_model_harness/qwen-agent-workspace`). Prints one `PASS <id> <name>` or
`FAIL <id> <name> <detail>` line per assertion, then `OK n/n`, and exits 0 when nothing failed, 1
otherwise. Identical harness shape to `tests/test_ltx_movie_offline.py`: module-level `TOTAL`/`FAILED`
counters, a `check(name, condition, detail="")` function, a `if __name__ == "__main__":` block that
calls every test function in order and then prints `OK %d/%d` and `sys.exit(0 if FAILED == 0 else 1)`.

### 9.1 Module header

```python
"""Plain-python (no pytest) offline tests for bin/qwen-agent's context budget.

Run: python3 tests/test_qwen_agent_context_budget.py
Covers the 2026-09-02 context-budget design: window discovery, the token
estimator, tool-result eviction, the pre-send budget cliff, and
finish_reason == "length" handling. Fully offline -- every server call is
monkeypatched; nothing here touches the network, a subprocess, or the model.
"""
```

Imports: `copy`, `importlib.machinery`, `importlib.util`, `io`, `json`, `os`, `sys`, `tempfile`,
`urllib.error`, `urllib.request`, `contextlib`.

**Loading the script** — use this exact form, not `SourceFileLoader(...).load_module()`:
`load_module()` is deprecated since 3.12 and removed in 3.14, and this test must keep running.
`WS` is derived from `__file__` rather than hardcoded because two copies of this workspace exist on
this host and the test must always exercise the one it ships beside.

```python
WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
_SCRIPT_PATH = os.path.join(WS, "bin", "qwen-agent")

_loader = importlib.machinery.SourceFileLoader("qwen_agent", _SCRIPT_PATH)
_spec = importlib.util.spec_from_loader("qwen_agent", _loader)
qwen_agent = importlib.util.module_from_spec(_spec)
sys.modules["qwen_agent"] = qwen_agent
_loader.exec_module(qwen_agent)

# Captured before the test module touches anything: proves importing the script
# runs no setup, builds no tools, and opens no socket (the __main__ guard holds).
_TOOLS_AT_IMPORT = qwen_agent.TOOLS
_WORKSPACE_AT_IMPORT = qwen_agent.WORKSPACE
_CONTEXT_WINDOW_AT_IMPORT = qwen_agent.CONTEXT_WINDOW

# The eight-tool schema the REPL uses; main() normally does this.
qwen_agent.TOOLS = qwen_agent.build_tools_for_context(None)
qwen_agent.TOOL_BY_NAME = {t["function"]["name"]: t for t in qwen_agent.TOOLS}
# Route _ui() to stderr so eviction notices do not interleave with PASS lines.
qwen_agent.ONESHOT = True
```

### 9.2 Shared fixtures

```python
SYSTEM_MSG = qwen_agent.build_system_message("/tmp/qwen-agent-test-ws")
BLOB_LINE = "    x = compute_value(alpha, beta, gamma)  # inline note\n"


def python_blob(n_chars):
    """Deterministic n-char block of indented Python -- the worst realistic case."""
    return (BLOB_LINE * (n_chars // len(BLOB_LINE) + 1))[:n_chars]


BLOB = python_blob(4000)


def make_args(**overrides):
    ns = qwen_agent.parse_args([])
    for key, value in overrides.items():
        setattr(ns, key, value)
    return ns


def set_window(n):
    qwen_agent.CONTEXT_WINDOW = n


def tool_call_response(index, finish_reason="tool_calls"):
    return {"choices": [{"finish_reason": finish_reason, "message": {
        "content": "",
        "tool_calls": [{"id": "call_%d" % index, "type": "function", "function": {
            "name": "bash",
            "arguments": json.dumps({"command": "echo %d" % index})}}]}}]}


def text_response(text, finish_reason="stop"):
    return {"choices": [{"finish_reason": finish_reason,
                         "message": {"content": text}}]}


def make_fake_chat(script):
    """Return (fake_chat_completion, calls). `script(n, messages, include_tools)`
    receives the 1-based call number and returns the canned response dict."""
    calls = []

    def fake(base_url, messages, args_ns, include_tools=True):
        calls.append({
            "estimate": qwen_agent.estimate_tokens(messages, include_tools),
            "include_tools": include_tools,
            "messages": copy.deepcopy(messages),
        })
        return script(len(calls), messages, include_tools)

    return fake, calls


def fake_dispatch_ok(tc, i, n, args_ns, history):
    """Minimal record: run_turn reads exactly outcome, result and tool, and sets
    round and id itself."""
    return {"tool": tc["function"]["name"], "outcome": "approved", "result": BLOB}
```

Every test that monkeypatches restores the original in a `finally:` block. The attributes patched are
`qwen_agent.chat_completion`, `qwen_agent.dispatch`, `qwen_agent.preflight`,
`qwen_agent.searxng_probe`, `qwen_agent.discover_context_window`, `qwen_agent.CONTEXT_WINDOW`, and
`urllib.request.urlopen` (the real shared module — restoring it is mandatory).

### 9.3 Test cases

Each numbered case is one test function. Every `check(...)` below is required; the ids are the
first token of the check name.

**C0 — import is side-effect free.**
- `C0 TOOLS None at import`: `_TOOLS_AT_IMPORT is None`
- `C0 WORKSPACE None at import`: `_WORKSPACE_AT_IMPORT is None`
- `C0 CONTEXT_WINDOW defaults`: `_CONTEXT_WINDOW_AT_IMPORT == qwen_agent.DEFAULT_CONTEXT_WINDOW == 16384`

**C1 — estimator is monotone and over-estimates.**
- Build `msgs = [SYSTEM_MSG]`, then append `{"role": "user", "content": "hi"}`, then
  `{"role": "tool", "tool_call_id": "call_1_1", "content": BLOB}`.
- `C1 monotone`: `estimate_tokens(msgs[:1], False) < estimate_tokens(msgs[:2], False) < estimate_tokens(msgs[:3], False)`
- `C1 4000-char python result >= 1300 tokens`:
  `estimate_tokens([msgs[2]], False) >= 1300` (the implementation yields 1384; the assertion is the
  floor, not the value)
- `C1 tools term is additive`:
  `estimate_tokens(msgs, True) - estimate_tokens(msgs, False) == len(json.dumps(qwen_agent.TOOLS)) // 3`
- `C1 tools term is zero when TOOLS is None`: temporarily set `qwen_agent.TOOLS = None`, assert
  `estimate_tokens(msgs, True) == estimate_tokens(msgs, False)`, restore in `finally`.
- `C1 deterministic`: two consecutive calls on the same list return equal values.

**C2 — replay: 12 rounds of 4000-char results never exceed the budget.**
- `set_window(16384)`; `args = make_args(max_tokens=1536, max_rounds=12, think=False)`.
- `messages = [copy.deepcopy(SYSTEM_MSG), {"role": "user", "content": "analyse the repo"}]`;
  `before = copy.deepcopy(messages[:2])`.
- Script: `text_response("done")` when `include_tools` is False, else `tool_call_response(n)`.
- Patch `chat_completion` and `dispatch`; call `qwen_agent.run_turn(messages, args, 1)` inside
  `contextlib.redirect_stderr(io.StringIO())`.
- `budget = 16384 - 1536 - 1024` (i.e. `qwen_agent.context_budget(args)` == 13824).
- `C2 status is max_rounds`: `result["status"] == "max_rounds"`
- `C2 13 chat calls`: `len(calls) == 13` (12 tool rounds + 1 forced summary)
- `C2 every call within budget`: `all(c["estimate"] <= budget for c in calls)`
- `C2 eviction happened`: at least one message in `messages` with `role == "tool"` whose `content`
  starts with `"[result evicted"`
- `C2 newest tool result never evicted`: for every recorded call whose snapshot contains at least one
  `role == "tool"` message, the **last** such message's content `== BLOB`
- `C2 final newest tool result intact`: the last `role == "tool"` message in `messages` has
  `content == BLOB`
- `C2 stub names the tool and the size`: some evicted content `== "[result evicted to free context: 4000 chars from bash]"`
- `C2 system message untouched`: `messages[0] == before[0]`
- `C2 user message untouched`: `messages[1] == before[1]`
- `C2 no assistant message evicted`: no message with `role == "assistant"` has a content starting with
  `"[result evicted"`
- `C2 eviction notice printed`: the captured stderr contains `"[context] evicted"` and
  `"16384-token window"`

**C3 — the cliff: a window too small for the tool schema.**
- `set_window(4096)`; `args = make_args(max_tokens=1536, max_rounds=10)`.
- `messages = [copy.deepcopy(SYSTEM_MSG), {"role": "user", "content": "hello"}]`.
- Script: `text_response("summary")` for any call; patch `dispatch` with a function that raises
  `AssertionError("dispatch must not be called")`.
- `C3 status is context_budget`: `result["status"] == "context_budget"`
- `C3 error names the budget`: `result["error"].startswith("context budget exhausted:")` and
  `"4096-token window" in result["error"]`
- `C3 answer came from the forced summary`: `result["answer"] == "summary"`
- `C3 exactly one chat call`: `len(calls) == 1`
- `C3 that call had tools disabled`: `calls[0]["include_tools"] is False`
- `C3 no over-budget call was sent`:
  `all(c["estimate"] <= qwen_agent.context_budget(args) for c in calls)`

**C4 — `finish_reason == "length"` with tool calls.**
- `set_window(16384)`; `args = make_args(max_tokens=1536, max_rounds=5)`.
- Script: call 1 → `tool_call_response(1, finish_reason="length")` with
  `["choices"][0]["message"]["content"] = "I will run "`; call 2 → `text_response("recovered")`.
- Patch `dispatch` with a raiser as in C3.
- `C4 status is truncated`: `result["status"] == "truncated"`
- `C4 error names max_tokens`:
  `result["error"] == "model output was cut off at max_tokens (1536); tool calls discarded"`
- `C4 forced summary ran once`: `len(calls) == 2 and calls[1]["include_tools"] is False`
- `C4 answer is the summary`: `result["answer"] == "recovered"`
- `C4 no tool message appended`: no message in `messages` has `role == "tool"`
- `C4 echo has no tool_calls`: the first `role == "assistant"` message has no `"tool_calls"` key and
  `content == "I will run "`

**C5 — `finish_reason == "length"` without tool calls.**
- Same setup; script call 1 → `text_response("partial answer", finish_reason="length")`.
- `C5 status is ok`: `result["status"] == "ok"`
- `C5 answer preserved`: `result["answer"] == "partial answer"`
- `C5 one chat call`: `len(calls) == 1`
- `C5 stderr note`: captured stderr contains `"[note: answer was cut off at max_tokens=1536]"`

**C6 — context-window discovery.**
Fake urlopen helper (module level in the test file):

```python
class _FakeResponse(object):
    def __init__(self, payload):
        self._payload = payload.encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
```

- `C6 exact id match`: urlopen returns
  `{"data": [{"id": "other", "context_length": 4096}, {"id": "qwen38-6bit", "context_length": 16384, "max_context_length": 16384, "max_model_len": 16384}]}`
  → `discover_context_window("http://x/v1", "qwen38-6bit", None) == 16384`
- `C6 falls back to the first entry`: `{"data": [{"id": "other", "context_length": 8192}]}` with
  `model="qwen38-6bit"` → `8192`
- `C6 falls back through the key list`: `{"data": [{"id": "qwen38-6bit", "max_model_len": 32768}]}`
  → `32768`
- `C6 no field -> default`: `{"data": [{"id": "qwen38-6bit"}]}` → `16384`
- `C6 urlopen failure -> default, no exception`: urlopen raises
  `urllib.error.URLError("refused")` → returns `16384` and the captured stderr contains
  `"could not read the context window"`
- `C6 empty data -> default`: `{"data": []}` → `16384`
- Restore `urllib.request.urlopen` in a `finally`.

**C7 — `--context-window` overrides discovery; discovery fills in otherwise.**
- Patch `qwen_agent.preflight` and `qwen_agent.searxng_probe` with no-op lambdas accepting any
  arguments; use `tempfile.mkdtemp()` as the workspace.
- `C7 flag parses`: `qwen_agent.parse_args(["--context-window", "8192"]).context_window == 8192`
- `C7 default is None`: `qwen_agent.parse_args([]).context_window is None`
- `C7 flag wins`: patch `discover_context_window` with a raiser; run
  `qwen_agent.setup(make_args(context_window=8192, workspace=tmpdir))` →
  `qwen_agent.CONTEXT_WINDOW == 8192`
- `C7 discovery used when unset`: patch `discover_context_window` with `lambda *a: 4321`; run
  `qwen_agent.setup(make_args(context_window=None, workspace=tmpdir))` →
  `qwen_agent.CONTEXT_WINDOW == 4321`
- Restore `preflight`, `searxng_probe`, `discover_context_window`, `CONTEXT_WINDOW`, and
  `qwen_agent.WORKSPACE` in a `finally`.

**C8 — source guards.**
Read `_SCRIPT_PATH` as text.
- `C8 no stale 8192-token string`: `"8192-token" not in src`
- `C8 both overflow messages parameterised`:
  `src.count('"%d-token window. Use /reset to start over.]\\n" % CONTEXT_WINDOW')` — assert the
  literal `'%d-token window. Use /reset to start over.]'` occurs exactly **2** times
- `C8 no new imports`: the set of top-level `import` / `from ... import` module names parsed with
  `ast` equals the exact set
  `{"argparse", "ast", "datetime", "html.parser", "json", "operator", "os", "re", "signal",
  "subprocess", "sys", "time", "urllib.error", "urllib.parse", "urllib.request", "uuid", "pathlib"}`
  (use `ast.walk` over the module body, collecting `ast.Import` names and `ast.ImportFrom` module
  names; `from pathlib import Path` contributes `"pathlib"`). Requires adding `ast` to the test's
  imports.
- `C8 context-window flag forwarded to children`:
  `'"--context-window", str(CONTEXT_WINDOW),' in src`
- `C8 RESULT_CHAR_LIMIT unchanged`: `"RESULT_CHAR_LIMIT = 4000" in src`

### 9.4 Test ordering in `__main__`

`test_import_is_side_effect_free`, `test_estimator`, `test_replay_eviction`, `test_cliff`,
`test_truncated_with_tool_calls`, `test_truncated_without_tool_calls`, `test_window_discovery`,
`test_setup_window_resolution`, `test_source_guards`. Each restores `qwen_agent.CONTEXT_WINDOW` to
`qwen_agent.DEFAULT_CONTEXT_WINDOW` on exit so ordering cannot leak state.

---

## 10. Ordered implementation checklist

Steps are strictly ordered; each depends on all before it.

| # | Step | Files | Depends on | Done when |
|---|---|---|---|---|
| 1 | Add the constants block of Section 3.1 | `bin/qwen-agent` | — | `python3 -m py_compile bin/qwen-agent` exits 0 and `grep -n "CONTEXT_FLOOR = 1024" bin/qwen-agent` prints one line |
| 2 | Add the `CONTEXT_WINDOW` global of Section 3.2 | `bin/qwen-agent` | 1 | `grep -n "^CONTEXT_WINDOW = DEFAULT_CONTEXT_WINDOW" bin/qwen-agent` prints one line |
| 3 | Add the whole Section 13 block of Section 4 | `bin/qwen-agent` | 1, 2 | `py_compile` exits 0; `grep -c "^def discover_context_window\|^def estimate_tokens\|^def context_budget\|^def _tool_name_for_call_id\|^def evict_to_budget" bin/qwen-agent` prints 5 |
| 4 | Add `--context-window` to `parse_args` (6.1) | `bin/qwen-agent` | 1 | `python3 bin/qwen-agent --help` lists `--context-window` |
| 5 | Resolve the window in `setup()` (Section 5) | `bin/qwen-agent` | 2, 3, 4 | `py_compile` exits 0; `setup`'s `global` line reads `global WORKSPACE, CONTEXT_WINDOW` |
| 6 | Forward `--context-window` in `exec_delegate_to_skill` (6.2) | `bin/qwen-agent` | 4 | `grep -n '"--context-window", str(CONTEXT_WINDOW)' bin/qwen-agent` prints one line |
| 7 | Rework `_forced_summary` (7.1): new parameter, eviction guard, corrected message | `bin/qwen-agent` | 3 | `py_compile` exits 0; `grep -c "8192-token" bin/qwen-agent` prints 1 (one site left) |
| 8 | Rework `run_turn` (7.2 a–f) | `bin/qwen-agent` | 3, 7 | `py_compile` exits 0; `grep -c "8192-token" bin/qwen-agent` prints **0**; `grep -c "protect_from" bin/qwen-agent` prints ≥ 8 |
| 9 | Add the REPL `context_budget` notice (Section 8) | `bin/qwen-agent` | 8 | `grep -n "no longer fits in the server" bin/qwen-agent` prints one line |
| 10 | Create the test file (Section 9) | `tests/test_qwen_agent_context_budget.py` | 1–9 | `python3 tests/test_qwen_agent_context_budget.py` exits 0 and prints `OK n/n` with n ≥ 40 |
| 11 | Regression sweep | — | 10 | `python3 -m py_compile bin/qwen-agent` and `/usr/bin/python3 -m py_compile bin/qwen-agent` both exit 0; `python3 tests/test_ltx_movie_offline.py` still exits 0 (known pre-existing failure: `ltx_movie.build_story_prompt` missing; unrelated to this change) |

If any step's acceptance check fails, stop and report — do not improvise a fix that is not in this
document.

---

## 11. Risks, edge cases, and failure modes

1. **The estimator can still under-count.** Long base64 or hex blobs tokenise near 2 chars/token;
   at 3 chars/token the estimate is ~33% low. Mitigations already in place: `RESULT_CHAR_LIMIT` caps
   any single result at 4000 characters (≈1384 estimated, ≈2000 real worst case), and `CONTEXT_FLOOR`
   holds back 1024 tokens. Residual risk: an HTTP 400 is still possible on a pathological transcript.
   That is why the existing `_is_context_overflow` handler **stays** — it is the backstop, now with a
   correct message. If it ever fires in practice, the fix is to lower `CHARS_PER_TOKEN` to 2, a
   one-constant change.
2. **`context_length` may over-report.** Some servers report the model's architectural maximum rather
   than the served `--max-model-len`. Symptom: budgeting passes, the server still 400s. Remedy is
   already shipped: `--context-window N`. Documented here so the operator is not left guessing.
3. **The model may re-request an evicted result.** Stubs tell it what was dropped and how big it was.
   Re-running the tool is the intended recovery and is *not* blocked: [TIERED]'s duplicate guard only
   refuses repeats of calls that **failed**. A successful call can be re-run, and its fresh result
   lands in the protected newest round. Accepted cost: an extra round.
4. **Eviction thrash.** Each round can evict only as many results as needed; with `max_rounds` 10 and
   4000-char results the pass evicts at most one or two per round after round ~8. Bounded, and the
   `[context]` line makes it visible.
5. **Rollback interaction.** `del messages[snapshot:]` on a transport failure keeps pre-snapshot
   evictions. Deliberate: the text is unrecoverable anyway (the original was never stored), and
   restoring it would only re-overflow the retry. Post-snapshot messages are deleted wholesale, stubs
   included, which is correct.
6. **A stray `FORCED_SUMMARY_PROMPT` message.** When `_forced_summary` bails on budget it has already
   appended its prompt. The REPL user is told to `/reset`; if they do not, the next turn's eviction
   pass simply treats it as one more (tiny, non-evictable) user message. No correctness impact.
7. **Very small `--context-window`.** No validation is performed (Section 2.1). A window below
   `max_tokens + CONTEXT_FLOOR` makes `context_budget()` negative, so every turn ends immediately with
   `context_budget` and a message naming the window — a legible degradation, not a crash, and one that
   cannot brick a delegate child.
8. **A tool result larger than the whole budget** cannot occur: 4000 characters ≈ 1384 estimated
   tokens versus a 13824-token budget at the shipped defaults. If `max_tokens` were raised past
   ~14000 the budget would go negative — see risk 7, same behaviour.
9. **`finish_reason` may be absent or non-standard.** `choice.get("finish_reason")` returns `None`,
   which matches neither branch, so behaviour is exactly today's. No server that omits it is
   penalised.
10. **A truncated response with tool calls loses real work.** If `max_tokens` is genuinely too small
    for the task (e.g. a large `write_file`), every turn now ends `"truncated"` instead of dispatching
    a mangled call. The error text names `max_tokens` explicitly so the operator knows the lever.
    This is a deliberate trade: a silently corrupted `bash` command is worse than a stopped turn.
11. **Two workspace copies on this host.** `/Users/reubenpatterson/qwen-agent-workspace/bin/qwen-agent`
    is a 2570-line divergent copy. Editing it is out of scope; the test derives its path from
    `__file__` precisely so it can never test the wrong one.
12. **Assistant tool-call arguments are unevictable.** Only `role == "tool"` content is eligible;
    `assistant_echo` stores each call's full `arguments` string and nothing caps it. Many large
    `write_file` calls in one conversation can therefore build an unevictable floor that no eviction
    can lower, at which point the turn ends `context_budget` with `answer: None` and `/reset` is the
    only recovery. Truncating echoed arguments is a design change deferred from this spec.

---

## 12. Acceptance checks (run all, from the repo root)

```
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
python3 -m py_compile bin/qwen-agent            # exits 0
/usr/bin/python3 -m py_compile bin/qwen-agent   # exits 0 (3.9.6 syntax gate)
grep -c '8192-token' bin/qwen-agent             # prints 0
python3 tests/test_qwen_agent_context_budget.py # prints OK n/n, exits 0
python3 tests/test_ltx_movie_offline.py         # unchanged, exits 0 (known pre-existing failure: `ltx_movie.build_story_prompt` missing; unrelated to this change)
python3 bin/qwen-agent --help | grep -- --context-window   # prints the flag
```

A live smoke check, once the server is up: start the REPL, run any task that produces ≥ 8 tool
results, and confirm (a) at least one `[context] evicted N tool result(s) to stay within the
16384-token window` line, and (b) no HTTP 400 for the whole session. Run it via an explicit path to
`local_model_harness/qwen-agent-workspace/bin/qwen-agent`; `~/.local/bin/qwen-agent` points at a
different, unpatched copy.
