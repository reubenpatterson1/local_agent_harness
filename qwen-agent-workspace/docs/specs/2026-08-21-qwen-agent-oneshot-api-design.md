# Spec: `qwen-agent --prompt` — one-shot programmatic invocation mode

**Status:** Ready for implementation. No open design decisions.
**Date:** 2026-08-21
**Type:** ADDITIVE change to an existing, working script. This is a diff, not a rewrite.
**Target file:** `/Users/reubenpatterson/.local/bin/qwen-agent` (single file, mode `0755`)
**Parent spec:** `/Volumes/Ollama/vllm-metal/docs/specs/2026-08-21-qwen-agent-tool-harness-design.md`
— hereafter **[HARNESS]**. It remains authoritative and **must not be edited**. Everything in
[HARNESS] Sections 2, 3, 5, 7, 8, 9, 10.1, 10.2, 10.3, 10.4, 11.1, 11.2, 11.3, and 12 is unchanged
by this spec.
**Interpreter constraint:** unchanged — valid on Python **3.9.6** and 3.13.0. No 3.10+ syntax
(no `X | Y` annotations, no `match`). Standard library only. No new imports.

---

## 1. Purpose and success criteria

### 1.1 What this adds

A single new flag, `--prompt TEXT`, that turns `qwen-agent` into a callable subroutine for other
programs (bash scripts, Python scripts) while keeping the human confirmation gate fully intact.

In `--prompt` mode `qwen-agent` runs **exactly one user turn** — the same multi-round tool-calling
loop the REPL runs for one `>>> ` line — and emits **exactly one JSON object on stdout**, then exits.
No banner, no `>>> ` loop, no slash commands, no session persistence.

The confirmation gate is **not** relaxed, weakened, batched, or automated. Every tool call still
stops and waits for a human to type `y` at a real prompt read from stdin. The only thing that moves
is *where the prompt is drawn*: in `--prompt` mode the confirmation UI is written to **stderr**
instead of stdout, so that `result=$(qwen-agent --prompt "…")` captures the JSON and nothing else,
while the human still sees the prompts on their terminal and still answers them by hand.

### 1.2 Success criteria

The change is correct and complete when all of the following hold on this machine, with the vLLM
server running per [HARNESS] Section 3:

1. `result=$(qwen-agent --prompt "What is 2+2? Answer directly without using any tools.")` sets
   `result` to a single line of valid JSON conforming to Section 4, with `"status": "ok"`,
   `"tool_calls": []`, and `$?` equal to `0`.
2. `qwen-agent --prompt "Use bash to list the workspace." > out.json 2> ui.log` prints the
   confirmation frame of [HARNESS] Section 10 into `ui.log` (byte-identical in body content to what
   the REPL prints to stdout), waits for a keystroke on stdin, and writes **exactly one line** to
   `out.json` which parses as JSON with `tool_calls[0].outcome == "approved"`.
3. Answering `n` at every prompt yields `"status": "ok"`, exit `0`, and
   `tool_calls[*].outcome == "denied"`. A denial is **not** an invocation failure.
4. A path-escape attempt yields `tool_calls[0].outcome == "rejected"` with **no confirmation frame
   printed anywhere**, matching [HARNESS] Section 8.2.
5. `qwen-agent --max-rounds 1 --prompt "<something that requires two tool calls>"` yields
   `"status": "max_rounds"`, `"answer": null`, and exit `3`.
6. With the server down, `qwen-agent --prompt "hi"` writes the [HARNESS] Section 6.2 preflight
   message to stderr, writes **nothing** to stdout, and exits `2`.
7. Running `qwen-agent` with no `--prompt` reproduces [HARNESS] Section 13 (T1–T8) with byte-identical
   stdout: same banner, same stdout-drawn confirmation prompts, same final-answer line, same
   `[stopped: …]` round-limit wording, same exit codes. **Zero observable REPL regression.**
8. Every flag in [HARNESS] Section 4 (`--workspace`, `--think`, `--base-url`, `--model`,
   `--max-tokens`, `--request-timeout`, `--max-rounds`, `--tool-timeout`) has identical effect in
   `--prompt` mode.

### 1.3 Explicitly out of scope

All non-goals of [HARNESS] Section 1.3 carry over unchanged, plus:

- **No auto-approval, `--yes`, `--dry-run`, allowlist, or non-interactive approval of any kind.**
  This is the single most important boundary in this spec. The threat model of [HARNESS] Section 2 is
  unchanged: the human reading each command *is* the security control. Do not add a flag that removes
  it. Do not add one later "just for tests".
- **No session persistence.** Every `--prompt` invocation is a fresh conversation:
  `[system_message, user_message]`. No `--session-id`, no transcript file, no resume.
- **No `--prompt-file`, no reading the prompt from stdin.** stdin is reserved for approval keystrokes.
- **No `reasoning_content` in the JSON.** With `--think`, reasoning is written to stderr exactly as
  today ([HARNESS] Section 4) and is not captured in the envelope.
- **No streaming, no partial/incremental JSON, no NDJSON event stream.** One object, at the end.
- **No machine-readable form of the preflight failure.** Preflight failures stay plain-text stderr +
  exit `2`, unchanged, and stdout stays empty.
- **No change to the REPL's stdout-based confirmation UI.** [HARNESS] assumption 15.9 ("prompts print
  to stdout so they survive `2>/dev/null`") continues to hold for REPL mode.

---

## 2. CLI contract (delta only)

New usage line:

```
usage: qwen-agent [-h] [--workspace WORKSPACE] [--think] [--base-url BASE_URL]
                  [--model MODEL] [--max-tokens MAX_TOKENS]
                  [--request-timeout REQUEST_TIMEOUT] [--max-rounds MAX_ROUNDS]
                  [--tool-timeout TOOL_TIMEOUT] [--prompt PROMPT]
```

| Flag | Type | Default | Behaviour |
|---|---|---|---|
| `--prompt` | str | `None` | When present: one-shot mode (Sections 3–5). `TEXT` is sent as the single user message. When absent: the existing REPL, unchanged. |

Declaration, appended as the **last** `add_argument` call in `parse_args` so `--prompt` sorts last in
`--help`:

```python
parser.add_argument("--prompt", type=str, default=None)
```

No `metavar`, matching the style of the eight existing flags. No `argparse` mutually-exclusive group
is used or needed: mode selection is `args_ns.prompt is not None`. There are no positional arguments
and no other flag interaction.

**Empty prompt:** if `args_ns.prompt is not None and args_ns.prompt.strip() == ""`, write
`qwen-agent: --prompt requires non-empty text.\n` to stderr and `sys.exit(2)` — **before** workspace
creation and before preflight, so the failure costs no server round trip. (Contrast: the REPL silently
skips an empty input line; in a programmatic caller an empty prompt is a caller bug and must be loud.)

`--prompt` accepts any other non-empty string verbatim, including leading `/`. Slash commands
([HARNESS] Section 11.2) are **not** interpreted in one-shot mode; `--prompt "/help"` is sent to the
model as the literal user text `/help`.

---

## 3. Exit codes

| Code | Mode | Condition |
|---|---|---|
| `0` | both | REPL: `/exit`/`/quit`/`/bye`/EOF. One-shot: `"status": "ok"` — a final answer was produced. Individual tool calls inside the turn may have been denied, rejected, or invalid; that does not change the exit code. |
| `2` | both | `argparse` usage error; workspace `mkdir` failure ([HARNESS] 6.1); preflight failure ([HARNESS] 6.2 checks A and B); **new:** `--prompt` given with blank text. |
| `3` | one-shot only | **New.** The turn ended abnormally with no final answer: any `"status"` other than `"ok"` (Section 4.1 table). |
| `1` | — | Never produced deliberately. A `1` means an unhandled Python exception escaped, which is a bug per [HARNESS] Section 12's invariant. |

`3` is chosen because `0` and `2` are already taken, `1` is the shell/Python convention for "uncaught
error" and is deliberately left free as a bug signal, and `3` is the lowest unused value. The REPL
never exits `3`.

---

## 4. stdout JSON contract (one-shot mode only)

### 4.0 Emission rules

- Written with exactly one call:
  `sys.stdout.write(json.dumps(envelope) + "\n")` followed by `sys.stdout.flush()`.
- `json.dumps` is called with **default arguments only** — default separators (`", "` / `": "`),
  `ensure_ascii=True`, no `indent`, no `sort_keys`. Result is a single line with no embedded raw
  newlines.
- `ensure_ascii=True` (i.e. do not pass the flag) is deliberate: it guarantees the payload is
  encodable regardless of `sys.stdout.encoding`, so a non-UTF-8 locale can never turn a successful run
  into a `UnicodeEncodeError`. Consumers decode `\uXXXX` escapes transparently (`jq`, `json.loads`).
- Exactly one trailing `"\n"`. Nothing else is ever written to stdout in one-shot mode — see the audit
  in Section 6.3.
- **Key order is unspecified.** Consumers must address fields by name.
- Emitted for **every** terminal status, including all abnormal ones. There is no path where one-shot
  mode exits after preflight without printing the envelope.

### 4.1 Envelope

Exactly six keys, always all present.

| Field | Type | Description |
|---|---|---|
| `schema` | string | Literal `"qwen-agent.oneshot.v1"`. Version marker; consumers should reject unknown values. |
| `status` | string | One of the seven values in the table below. |
| `answer` | string \| null | The model's final assistant text (`message.content`, coerced from `null` to `""`) when `status == "ok"`; `null` for every other status. May legitimately be `""` if the model returned empty content — an empty string is a successful turn, not an error. Never the REPL's `"(no content)"` placeholder, which is display-only. |
| `error` | string \| null | `null` when `status == "ok"`; otherwise a single-line human-readable description, exact text per the table below. |
| `rounds` | integer | Number of model round trips attempted in this turn, ≥ 0. On `ok` this is the round that produced the answer. On a mid-turn transport failure it is the round that failed. On `max_rounds` it equals `--max-rounds`. |
| `tool_calls` | array | Ordered list of tool-call records (Section 4.2), oldest first, across all rounds. `[]` when the model answered without tools. |

Status values, their `error` text, and exit codes:

| `status` | Meaning | `error` value | Exit |
|---|---|---|---|
| `"ok"` | The model returned a response with no `tool_calls`. | `null` | `0` |
| `"max_rounds"` | `--max-rounds` model round trips completed and the model was still calling tools. | `"reached the %d-round tool limit without a final answer" % max_rounds` | `3` |
| `"context_length"` | `HTTPError` mid-turn whose body matched `_is_context_overflow` ([HARNESS] 12 row `CTX`). | `"context full: the conversation exceeds the server's context window"` | `3` |
| `"http_error"` | Any other `HTTPError` mid-turn (4xx/5xx). | `"server error %s: %s" % (code, err_body[:1000])` | `3` |
| `"network_error"` | `URLError` / `OSError` / socket timeout mid-turn. | `"network error: %s" % e` | `3` |
| `"malformed_response"` | Response was not JSON, or lacked `choices[0].message`. | `"malformed server response: %s" % e` | `3` |
| `"interrupted"` | `Ctrl-C` while awaiting the model's HTTP response. | `"cancelled by SIGINT while awaiting the model"` | `3` |

Note that the `error` strings above are **new, caller-facing** strings, deliberately distinct from the
bracketed human diagnostics that [HARNESS] Section 12 already writes to stderr. Both are emitted: the
existing stderr diagnostic is unchanged byte-for-byte (it is what the REPL relies on), and `error`
carries the same fact without the REPL-specific advice (`Use /reset to start over.`, `Type another
message to continue`) that is meaningless to a programmatic caller.

### 4.2 Tool-call record

Seven keys, always all present.

| Field | Type | Description |
|---|---|---|
| `tool` | string \| null | `function.name` from the model's tool call. `null` only if the model omitted it. Not validated against the tool list here — an unknown name appears verbatim with `outcome == "invalid"`. |
| `arguments` | object \| null | The JSON-decoded arguments, **only if** decoding succeeded **and** the decoded value is a `dict`. `null` when the arguments string was unparseable, or decoded to a non-object (list/string/number). |
| `arguments_raw` | string | The `function.arguments` string exactly as the server returned it, or `"{}"` if it was absent/empty (same normalisation the existing dispatcher applies). Never truncated. |
| `outcome` | string | One of `"approved"`, `"denied"`, `"rejected"`, `"invalid"` — table below. |
| `result` | string | The tool-result string that was fed back to the model as the `role: tool` content, **after** the [HARNESS] Section 9.6 4000-character truncation. Byte-identical to what the model saw. |
| `round` | integer | 1-based index of the model round trip in which this call was issued. |
| `id` | string | The `tool_call_id` used in the transcript: `tc_id(tc, i, round)` ([HARNESS] Section 11). |

`round` and `id` are included because both are cheap and let a caller reconstruct the transcript
ordering without re-deriving it.

`outcome` vocabulary — exhaustive, one value per pre-existing dispatcher exit path:

| `outcome` | Set when | Prompt shown? | Side effect? |
|---|---|---|---|
| `"approved"` | The human answered `y`/`yes` and the tool was executed. `result` may still be an `ERROR: …` string from execution, timeout ([HARNESS] 9.7), or `Ctrl-C` during execution ([HARNESS] 9.8) — the *approval* succeeded, the *execution* may not have. | yes | yes |
| `"denied"` | The human answered anything else, or EOF, or `Ctrl-C` at the prompt ([HARNESS] 10.3). | yes | no |
| `"rejected"` | Blocked before the prompt by workspace confinement ([HARNESS] 8.2) or by the `fetch_url` scheme check ([HARNESS] 9.5). | **no** | no |
| `"invalid"` | Blocked before the prompt by unknown tool name, unparseable `arguments` JSON, or argument-shape validation ([HARNESS] 7.1, 12 rows `ARG-JSON` / `ARG-SHAPE` / `TOOL-UNKNOWN`). | **no** | no |

`arguments` and `arguments_raw` are **never truncated**, unlike `result`. Rationale: the 4000-char
limit exists to protect the model's 8192-token context, not the caller's stdout, and a caller auditing
a `write_file` call needs the full content the model proposed. Total size is bounded by `--max-tokens`
(default 1536) anyway.

### 4.3 Example — normal completion, one approved tool call

Actual output is a single line; pretty-printed here for readability.

```json
{
  "schema": "qwen-agent.oneshot.v1",
  "status": "ok",
  "answer": "The workspace contains a single file, notes.txt, which is 18 bytes.",
  "error": null,
  "rounds": 2,
  "tool_calls": [
    {
      "tool": "bash",
      "arguments": {"command": "ls -l"},
      "arguments_raw": "{\"command\": \"ls -l\"}",
      "outcome": "approved",
      "result": "exit_code: 0\n--- stdout ---\ntotal 8\n-rw-r--r--  1 reubenpatterson  staff  18 Aug 21 09:14 notes.txt\n\n--- stderr ---\n(empty)",
      "round": 1,
      "id": "chatcmpl-tool-7f3a1c9e"
    }
  ]
}
```

`rounds` is `2`: round 1 produced the `bash` call, round 2 produced the answer.

### 4.4 Example — normal completion with a denial and a pre-approval rejection

Still `"status": "ok"` and still exit `0`: the invocation did its job, which was to run one turn to a
final answer under human control.

```json
{
  "schema": "qwen-agent.oneshot.v1",
  "status": "ok",
  "answer": "I can't read /etc/passwd — it's outside my workspace — and you declined the shell command, so I have nothing to report.",
  "error": null,
  "rounds": 3,
  "tool_calls": [
    {
      "tool": "read_file",
      "arguments": {"path": "/etc/passwd"},
      "arguments_raw": "{\"path\": \"/etc/passwd\"}",
      "outcome": "rejected",
      "result": "ERROR: rejected path '/etc/passwd': it resolves to '/etc/passwd', which is outside the workspace '/Users/reubenpatterson/qwen-agent-workspace'. This call was blocked automatically and was never shown to the user for approval. All file paths must stay inside the workspace directory.",
      "round": 1,
      "id": "chatcmpl-tool-11aa22bb"
    },
    {
      "tool": "bash",
      "arguments": {"command": "wc -l /etc/passwd"},
      "arguments_raw": "{\"command\": \"wc -l /etc/passwd\"}",
      "outcome": "denied",
      "result": "ERROR: the user denied permission for this tool call. It was NOT executed. Do not retry the identical call. Either take a different approach, or stop and explain to the user what you need to do and why.",
      "round": 2,
      "id": "chatcmpl-tool-33cc44dd"
    }
  ]
}
```

### 4.5 Example — abnormal, round limit exhausted

```json
{
  "schema": "qwen-agent.oneshot.v1",
  "status": "max_rounds",
  "answer": null,
  "error": "reached the 2-round tool limit without a final answer",
  "rounds": 2,
  "tool_calls": [
    {
      "tool": "write_file",
      "arguments": {"path": "nums.txt", "content": "1\n2\n3\n"},
      "arguments_raw": "{\"path\": \"nums.txt\", \"content\": \"1\\n2\\n3\\n\"}",
      "outcome": "approved",
      "result": "OK: wrote 6 bytes to /Users/reubenpatterson/qwen-agent-workspace/nums.txt",
      "round": 1,
      "id": "chatcmpl-tool-55ee66ff"
    },
    {
      "tool": "read_file",
      "arguments": {"path": "nums.txt"},
      "arguments_raw": "{\"path\": \"nums.txt\"}",
      "outcome": "approved",
      "result": "1\n2\n3\n",
      "round": 2,
      "id": "chatcmpl-tool-77aa88bb"
    }
  ]
}
```

Exit `3`. stderr additionally carries
`[stopped: reached the 2-round tool limit without a final answer.]`.

### 4.6 Example — abnormal, transport failure mid-turn

```json
{
  "schema": "qwen-agent.oneshot.v1",
  "status": "network_error",
  "answer": null,
  "error": "network error: <urlopen error [Errno 61] Connection refused>",
  "rounds": 2,
  "tool_calls": [
    {
      "tool": "bash",
      "arguments": {"command": "uptime"},
      "arguments_raw": "{\"command\": \"uptime\"}",
      "outcome": "approved",
      "result": "exit_code: 0\n--- stdout ---\n 9:14  up 3 days, 21:02, 2 users, load averages: 2.11 1.98 1.87\n\n--- stderr ---\n(empty)",
      "round": 1,
      "id": "chatcmpl-tool-99cc00dd"
    }
  ]
}
```

Exit `3`. `tool_calls` retains the work that did happen before the failure — a caller must be able to
see that `uptime` actually ran. stderr additionally carries the unchanged
`[network error: … Is vLLM still running?]` line.

---

## 5. Behaviour of the one-shot turn

### 5.1 Order of operations

1. Parse args. If `--prompt` is present and blank → stderr message, exit `2` (Section 2).
2. Set the one-shot flag (Section 6.1) — done **before** anything that could draw UI.
3. Workspace creation and realpath resolution — [HARNESS] 6.1, unchanged, exit `2` on failure.
4. `base_url` trailing-slash strip — unchanged.
5. Preflight checks A and B — [HARNESS] 6.2, unchanged, both still run, messages still to stderr,
   still exit `2`. **stdout stays empty on preflight failure.**
6. **Banner: skipped entirely.** [HARNESS] 6.3 is not executed in one-shot mode.
7. `messages = [build_system_message(WORKSPACE), {"role": "user", "content": args_ns.prompt}]`.
8. Run the shared turn loop (Section 6.2), identical to what the REPL runs for one input line: same
   `--max-rounds` cap, same wire body ([HARNESS] 11.1.1), same assistant echo ([HARNESS] 11.1.3),
   same dispatcher ([HARNESS] 7.1/8/9/10), same one `role: tool` reply per tool call.
9. If the status is `max_rounds`, write the one-shot round-limit notice to stderr (Section 6.4).
10. Build the envelope, write it to stdout, flush, `sys.exit(0 if status == "ok" else 3)`.

### 5.2 Interactive approval in one-shot mode — exact mechanics

- The confirmation frame ([HARNESS] 10.1) and bodies ([HARNESS] 10.2) are rendered with **identical
  content**, only to stderr instead of stdout.
- The `Approve? [y/N] ` prompt string is written to stderr and flushed, then one line is read with
  `sys.stdin.readline()`.
- `sys.stdin.readline()` is used instead of `input()` in one-shot mode **specifically to keep stdout
  clean**: when stdin and stdout are both TTYs, `input()` routes through GNU readline, which echoes
  keystrokes and terminal control sequences to stdout. That would violate the "one JSON object on
  stdout" contract for a user running `qwen-agent --prompt …` directly on a terminal without capturing
  output. `readline()` never touches stdout. Line editing is lost at the approval prompt in one-shot
  mode; for a one-character answer this is an acceptable and deliberate trade.
- Trailing `"\n"` is stripped from the returned line. Answer parsing is then [HARNESS] 10.3
  verbatim: `y`/`yes` after `.strip().lower()` approves, everything else denies.
- `readline()` returning `""` (EOF) raises `EOFError`, so the existing `except EOFError` in `confirm`
  keeps its current meaning: deny.
- `  -> running...` / `  -> denied` also go to stderr in one-shot mode.

### 5.3 Edge cases — resolved, not left open

| Case | Defined behaviour |
|---|---|
| stdin is closed, `/dev/null`, or an exhausted pipe | Every confirmation reads EOF → every call is **denied** ([HARNESS] 10.3). The turn still completes; typically `"status": "ok"` with all `outcome == "denied"`, exit `0`. This is correct, not a failure: there is no unattended approval path, by design ([HARNESS] Section 2). A caller wanting tools to actually run must keep a human at a terminal. |
| `--prompt` text that needs no tools | `tool_calls: []`, `rounds: 1`, `status: "ok"`, exit `0`. |
| Model returns empty `content` and no `tool_calls` | `answer: ""`, `status: "ok"`, exit `0`. The REPL's `"(no content)"` substitution is display-only and must **not** leak into the JSON. |
| `--max-rounds 0` (or negative) | Loop body never executes: `status: "max_rounds"`, `rounds: 0`, `tool_calls: []`, exit `3`. No HTTP request is made after preflight. Matches the existing REPL's `while/else` behaviour for the same value. |
| `Ctrl-C` at a confirmation prompt | That one call is denied; the turn continues ([HARNESS] 10.3 / 12 row `INT-PROMPT` semantics for the dispatcher). Envelope still printed. |
| `Ctrl-C` during tool execution | [HARNESS] 9.8 result string, `outcome: "approved"`, turn continues, envelope still printed. |
| `Ctrl-C` while awaiting the model | `status: "interrupted"`, exit `3`, envelope printed. stderr still gets the existing `\n[cancelled]` line. |
| A single model response containing multiple `tool_calls` | Each gets its own record, in response order, all with the same `round`. Every one still gets its own prompt and its own `role: tool` reply ([HARNESS] Section 11 invariant). |
| Prompt text beginning with `/` | Sent to the model verbatim. Not a slash command (Section 2). |
| Prompt text beginning with `-` | Standard `argparse` behaviour; callers pass `--prompt "-x"` as a single argument or use `--prompt=-x`. No special handling added. |
| `--think` in one-shot mode | Sampling params and `enable_thinking` change exactly as today; `reasoning_content` goes to stderr; it is **not** in the JSON (Section 1.3). |
| Preflight fails | stderr message + exit `2`, **no envelope**, stdout empty. Callers must check the exit code before parsing stdout. |
| Both `--prompt` and a slash-command-looking argv extra | No positionals exist; `argparse` errors with exit `2`. |

---

## 6. Implementation: exact changes to `/Users/reubenpatterson/.local/bin/qwen-agent`

The guiding rule: **the one-shot path must reuse the existing tool dispatcher and confirmation logic,
not duplicate it.** Achieved by (a) extracting the per-turn loop out of `repl()` into a shared
`run_turn()`, (b) extracting startup into a shared `setup()`, (c) adding one module-level mode flag
that redirects the confirmation UI stream. Nothing about tool semantics, confinement, prompt content,
or the wire contract is touched.

Line numbers below refer to the current file as read on 2026-08-21 (1058 lines).

### 6.0 Change map

| Location | Action |
|---|---|
| Docstring, lines 2–6 | Add one sentence (6.1). |
| Constants block, after line 38 | Add `ONESHOT_SCHEMA`, `EXIT_ABNORMAL`, `ONESHOT` and the `_ui()` helper (6.1). |
| `confirm()`, lines 385–403 | Redirect its five `print` calls to `_ui()`; replace the `input()` call with `_prompt_line()` (6.1). |
| New function, before `dispatch()` | `_record()` (6.1). |
| `dispatch()`, lines 562–666 | Change the return type from `str` to a record dict; return via `_record()` at all eight exit points; move the `raw_arguments` read above the unknown-tool check; route the line-635 `print()` to `_ui()` (6.1). |
| New functions, replacing part of `repl()` | `setup()`, `_turn_result()`, `run_turn()` (6.2). |
| `repl()`, lines 924–1028 | Reduced to: `setup()`, banner, input loop, `run_turn()` call, answer print, round-limit notice (6.3). |
| New function, after `repl()` | `oneshot()` (6.4). |
| `parse_args()`, line 1047 area | One `add_argument` appended (6.5). |
| `main()`, lines 1051–1053 | Branch on `args_ns.prompt` (6.5). |

Everything not listed is untouched. Explicitly **unchanged**: `TOOLS`, `TOOL_BY_NAME`,
`resolve_in_workspace`, `_TextExtractor`, `html_to_text`, `validate_args`, `_indent_lines`,
`build_confirmation_body`, `_fmt_std_result`, `_run_subprocess`, `exec_bash`, `exec_run_python`,
`exec_read_file`, `exec_write_file`, `exec_fetch_url`, `_truncate`, `tc_id`, `chat_completion`,
`assistant_echo`, `build_system_message`, `HELP_TEXT`, `_first_sentence`, `print_help`, `print_tools`,
`handle_slash_command`, `RESTART_COMMAND`, `preflight`, `print_banner`, `_is_context_overflow`, and
every existing constant value.

### 6.1 Mode flag, UI stream, prompt reader, record builder

Docstring — append to the existing summary paragraph (lines 2–6):

```
Also supports a one-shot programmatic mode: --prompt TEXT runs a single turn and
prints one JSON object to stdout (see
docs/specs/2026-08-21-qwen-agent-oneshot-api-design.md).
```

Constants — add immediately after the `WORKSPACE = None` block (line 38):

```python
ONESHOT_SCHEMA = "qwen-agent.oneshot.v1"   # value of the JSON envelope's "schema" field
EXIT_ABNORMAL = 3                          # one-shot: turn ended with no final answer

# True only in --prompt mode. Redirects the confirmation UI to stderr so stdout
# carries nothing but the JSON envelope. Never true in the REPL.
ONESHOT = False


def _ui():
    """Stream the confirmation UI is drawn on: stdout in the REPL, stderr in --prompt mode."""
    return sys.stderr if ONESHOT else sys.stdout


def _prompt_line(text):
    """Write an inline prompt to the UI stream and read one line from stdin.

    REPL mode keeps input() verbatim so readline editing and the existing stdout
    prompt behaviour are unchanged. One-shot mode writes to stderr and reads with
    sys.stdin.readline(), which never writes to stdout.
    Raises EOFError on end of input, matching input().
    """
    if not ONESHOT:
        return input(text)
    sys.stderr.write(text)
    sys.stderr.flush()
    line = sys.stdin.readline()
    if line == "":
        raise EOFError
    return line.rstrip("\n")
```

`confirm()` — replace lines 386–402 with the same statements retargeted; the logic, the strings, and
the answer parsing are untouched:

```python
def confirm(tool_name, args, i, n, tool_timeout, resolved_paths):
    out = _ui()
    print(RULE, file=out)
    print("TOOL CALL %d/%d  ·  %s" % (i, n, tool_name), file=out)
    print(build_confirmation_body(tool_name, args, tool_timeout, resolved_paths), file=out)
    print(RULE, file=out)
    try:
        answer = _prompt_line("Approve? [y/N] ")
    except EOFError:
        answer = ""
    except KeyboardInterrupt:
        print(file=out)
        answer = ""

    approved = answer.strip().lower() in ("y", "yes")
    if approved:
        print("  -> running...", file=out)
    else:
        print("  -> denied", file=out)
    return approved
```

Record builder — add immediately after `_truncate` (line 559):

```python
def _record(name, arguments, arguments_raw, outcome, result):
    """Build one tool-call record. Truncation is applied here, once, to `result`."""
    return {
        "tool": name,
        "arguments": arguments if isinstance(arguments, dict) else None,
        "arguments_raw": arguments_raw,
        "outcome": outcome,
        "result": _truncate(result),
    }
```

`dispatch()` — same body, same order of checks, same message strings; only the return values change
from `_truncate(result)` to `_record(...)`, and `raw_arguments` moves above the unknown-tool check so
that record can carry it. New docstring: `"""Dispatch one tool_call dict. Returns a tool-call record
per the one-shot spec Section 4.2."""`. The eight exit points map as:

| Existing site | New return |
|---|---|
| line 570, unknown tool | `_record(name, None, raw_arguments, "invalid", <same string>)` |
| line 578, `JSONDecodeError` | `_record(name, None, raw_arguments, "invalid", <same string>)` |
| line 584, `validate_args` failure | `_record(name, args, raw_arguments, "invalid", err)` |
| line 600, `read_file` path escape | `_record(name, args, raw_arguments, "rejected", <same string>)` (the `[rejected]` stderr line stays) |
| line 615, `write_file` path escape | `_record(name, args, raw_arguments, "rejected", <same string>)` (stderr line stays) |
| line 629, `fetch_url` bad scheme | `_record(name, args, raw_arguments, "rejected", <same string>)` (stderr line stays) |
| line 643, denial | `_record(name, args, raw_arguments, "denied", <same string>)` |
| line 666, post-execution | `_record(name, args, raw_arguments, "approved", result)` |

Also line 635, the `print()` inside `except KeyboardInterrupt:` around the `confirm` call, becomes
`print(file=_ui())`.

### 6.2 Shared startup and shared turn loop

Extracted from `repl()` verbatim. Insert both before `repl()`.

```python
def setup(args_ns):
    """Workspace + base_url + preflight. Shared by the REPL and one-shot mode.

    Extracted unchanged from the head of repl(). Exits 2 on failure.
    """
    global WORKSPACE

    workspace = Path(args_ns.workspace).expanduser()
    try:
        workspace.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        sys.stderr.write("qwen-agent: cannot create workspace %s: %s\n" % (workspace, e))
        sys.exit(2)
    WORKSPACE = Path(os.path.realpath(str(workspace)))

    args_ns.base_url = args_ns.base_url.rstrip("/")
    preflight(args_ns.base_url, args_ns.model)


def _turn_result(status, answer, rounds, tool_calls, error):
    return {"status": status, "answer": answer, "rounds": rounds,
            "tool_calls": tool_calls, "error": error}


def run_turn(messages, args_ns, snapshot):
    """Run one user turn to completion. Shared by the REPL and one-shot mode.

    `messages` must already end with this turn's user message; `snapshot` is
    len(messages) before it was appended, used for rollback on transport failure.
    Returns a turn-result dict. Writes diagnostics to stderr and the confirmation
    UI to _ui(); writes NOTHING to stdout, and in particular does not print the
    final answer -- the caller decides how to surface it.
    """
    records = []
    round_num = 0
    while round_num < args_ns.max_rounds:
        round_num += 1
        try:
            resp = chat_completion(args_ns.base_url, messages, args_ns)
        except KeyboardInterrupt:
            sys.stderr.write("\n[cancelled]\n")
            del messages[snapshot:]
            return _turn_result("interrupted", None, round_num, records,
                                "cancelled by SIGINT while awaiting the model")
        except urllib.error.HTTPError as e:
            code = e.code
            err_body = e.read().decode("utf-8", errors="replace")
            if _is_context_overflow(err_body):
                sys.stderr.write(
                    "[context full: the conversation exceeds the server's "
                    "8192-token window. Use /reset to start over.]\n"
                )
                status = "context_length"
                error = "context full: the conversation exceeds the server's context window"
            else:
                sys.stderr.write("[server error %s] %s\n" % (code, err_body[:1000]))
                status = "http_error"
                error = "server error %s: %s" % (code, err_body[:1000])
            del messages[snapshot:]
            return _turn_result(status, None, round_num, records, error)
        except (urllib.error.URLError, OSError) as e:
            sys.stderr.write("[network error: %s. Is vLLM still running?]\n" % e)
            del messages[snapshot:]
            return _turn_result("network_error", None, round_num, records,
                                "network error: %s" % e)
        except (ValueError, KeyError, IndexError) as e:
            sys.stderr.write("[malformed server response: %s]\n" % e)
            del messages[snapshot:]
            return _turn_result("malformed_response", None, round_num, records,
                                "malformed server response: %s" % e)

        try:
            msg = resp["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as e:
            sys.stderr.write("[malformed server response: %s]\n" % e)
            del messages[snapshot:]
            return _turn_result("malformed_response", None, round_num, records,
                                "malformed server response: %s" % e)

        if args_ns.think and msg.get("reasoning_content"):
            sys.stderr.write("[thinking]\n")
            sys.stderr.write(msg["reasoning_content"])
            sys.stderr.write("\n[/thinking]\n")

        tool_calls = msg.get("tool_calls") or []
        messages.append(assistant_echo(msg, tool_calls, round_num))

        if not tool_calls:
            return _turn_result("ok", msg.get("content") or "", round_num, records, None)

        n = len(tool_calls)
        for i, tc in enumerate(tool_calls, start=1):
            record = dispatch(tc, i, n, args_ns)
            record["round"] = round_num
            record["id"] = tc_id(tc, i, round_num)
            records.append(record)
            messages.append({
                "role": "tool",
                "tool_call_id": record["id"],
                "content": record["result"],
            })
        # loop continues -- the model is re-invoked with no new user input

    return _turn_result("max_rounds", None, round_num, records,
                        "reached the %d-round tool limit without a final answer"
                        % args_ns.max_rounds)
```

Behavioural equivalence notes, part of the contract:

- The original `while … else:` is replaced by a fall-through `return` after the loop. Same trigger
  condition (loop exhausted without an early exit), same non-rollback of the transcript on
  `max_rounds` ([HARNESS] Section 11).
- Every `break` in the original becomes a `return`; the `del messages[snapshot:]` rollbacks are
  preserved exactly where they were, including their absence on the `max_rounds` path.
- Except-clause order (`KeyboardInterrupt` first) is preserved; reordering would change which handler
  catches what.
- `dispatch` keeps its `(tc, i, n, args_ns)` signature. `round` and `id` are attached by the caller,
  which already has `round_num` for `tc_id`. No signature churn.
- `chat_completion(args_ns.base_url, …)` replaces the original's local `base_url` variable; `setup()`
  has already normalised `args_ns.base_url`, so the value is identical.

### 6.3 `repl()` after extraction

```python
def repl(args_ns):
    setup(args_ns)
    print_banner(args_ns.model, WORKSPACE, args_ns.think)

    system_message = build_system_message(WORKSPACE)
    messages = [system_message]

    while True:
        try:
            line = input("\n>>> ")
        except EOFError:
            print()
            sys.exit(0)
        except KeyboardInterrupt:
            print()
            continue

        if line.strip() == "":
            continue

        if line.lstrip().startswith("/"):
            handle_slash_command(line, messages, system_message)
            continue

        snapshot = len(messages)
        messages.append({"role": "user", "content": line})

        outcome = run_turn(messages, args_ns, snapshot)
        if outcome["status"] == "ok":
            print(outcome["answer"] or "(no content)")
        elif outcome["status"] == "max_rounds":
            sys.stderr.write(
                "[stopped: reached the %d-round tool limit for this turn. "
                "Type another message to continue, or /reset to clear the "
                "conversation.]\n" % args_ns.max_rounds
            )
```

The `"(no content)"` fallback and the round-limit wording are preserved **byte-for-byte**; all other
failure statuses already emitted their existing stderr diagnostic inside `run_turn`, so the REPL adds
nothing for them, exactly as before.

**stdout audit for one-shot mode.** Every `print`/stdout write in the file, and why it cannot pollute
the envelope:

| Lines | Writer | One-shot |
|---|---|---|
| 386–402 | `confirm()` frame, body, rule, verdict | routed to stderr via `_ui()` |
| 391 | `Approve? [y/N] ` prompt | routed to stderr via `_prompt_line()`; `readline()` bypasses readline echo |
| 635 | `dispatch()` `Ctrl-C` newline | routed to stderr via `_ui()` |
| 765–791 | `print_help`, `print_tools`, `handle_slash_command` | unreachable — no slash commands in one-shot |
| 900–905 | `print_banner` | not called in one-shot (Section 5.1 step 6) |
| 947–952 | `repl()` `>>> ` prompt and newlines | unreachable — `repl()` is not called |
| (was) 1011 | final-answer print | moved into `repl()`; `run_turn` no longer prints it |
| new | envelope | the sole stdout write in one-shot mode |

### 6.4 `oneshot()`

Insert after `repl()`.

```python
def oneshot(args_ns):
    """Run exactly one turn and print one JSON envelope to stdout. Never returns."""
    global ONESHOT
    ONESHOT = True

    setup(args_ns)

    messages = [build_system_message(WORKSPACE),
                {"role": "user", "content": args_ns.prompt}]
    outcome = run_turn(messages, args_ns, 1)

    if outcome["status"] == "max_rounds":
        sys.stderr.write(
            "[stopped: reached the %d-round tool limit without a final answer.]\n"
            % args_ns.max_rounds
        )

    envelope = {
        "schema": ONESHOT_SCHEMA,
        "status": outcome["status"],
        "answer": outcome["answer"],
        "error": outcome["error"],
        "rounds": outcome["rounds"],
        "tool_calls": outcome["tool_calls"],
    }
    sys.stdout.write(json.dumps(envelope) + "\n")
    sys.stdout.flush()
    sys.exit(0 if outcome["status"] == "ok" else EXIT_ABNORMAL)
```

`snapshot=1` means a transport failure rolls the transcript back to `[system_message]`; the transcript
is discarded immediately afterwards, so the rollback is inert but keeps `run_turn` mode-agnostic.

### 6.5 `parse_args()` and `main()`

```python
    parser.add_argument("--tool-timeout", type=int, default=DEFAULT_TOOL_TIMEOUT)
    parser.add_argument("--prompt", type=str, default=None)
    return parser.parse_args(argv)


def main():
    args_ns = parse_args(sys.argv[1:])
    if args_ns.prompt is not None:
        if args_ns.prompt.strip() == "":
            sys.stderr.write("qwen-agent: --prompt requires non-empty text.\n")
            sys.exit(2)
        oneshot(args_ns)
    else:
        repl(args_ns)
```

---

## 7. Caller-side usage (reference only — not to be embedded in the script)

No `--help` epilog and no README is added by this change; `--prompt` appears in the auto-generated
flag list and that is sufficient. The examples below exist for the acceptance tests in Section 8 and
for the implementer's own verification.

**bash**

```bash
# stdout captured; confirmation prompts still visible on the terminal via stderr.
if result=$(qwen-agent --prompt "Use bash to count the files in the workspace."); then
  answer=$(printf '%s' "$result" | python3 -c 'import json,sys; print(json.load(sys.stdin)["answer"])')
  printf 'answer: %s\n' "$answer"
else
  code=$?
  printf 'qwen-agent failed with exit %d\n' "$code" >&2
  # exit 2 => no JSON on stdout; exit 3 => JSON present, status explains why
  [ "$code" -eq 3 ] && printf '%s' "$result" | python3 -m json.tool >&2
fi
```

**Python**

```python
import json
import subprocess

proc = subprocess.run(
    ["qwen-agent", "--prompt", "Read notes.txt and summarise it.", "--max-rounds", "6"],
    stdout=subprocess.PIPE, text=True,          # stderr and stdin inherited: the human
)                                               # sees the prompts and answers them
if proc.returncode == 2:
    raise RuntimeError("qwen-agent preflight failed; see stderr")
payload = json.loads(proc.stdout)
assert payload["schema"] == "qwen-agent.oneshot.v1"
if payload["status"] != "ok":
    raise RuntimeError("turn ended abnormally: %s" % payload["error"])
print(payload["answer"])
for call in payload["tool_calls"]:
    print(call["round"], call["tool"], call["outcome"])
```

Note the deliberate absence of `stderr=subprocess.PIPE`: capturing stderr hides the confirmation
prompts and the run will appear to hang. Callers must let stderr and stdin reach the terminal.

---

## 8. Acceptance tests

Prerequisite: vLLM running per [HARNESS] Section 3. `A1`–`A10` are the acceptance gate; all must pass.

**A1 — no-tool turn, captured stdout.**
```bash
result=$(qwen-agent --prompt "What is 2+2? Answer directly, do not use any tools."); echo "exit=$?"
printf '%s' "$result" | python3 -m json.tool
printf '%s\n' "$result" | wc -l
```
Pass: `exit=0`; `json.tool` succeeds; `wc -l` is `1`; `status == "ok"`; `tool_calls == []`;
`rounds == 1`; `answer` mentions 4; `error is None`; `schema == "qwen-agent.oneshot.v1"`.

**A2 — approved tool call, stdout purity under redirection.**
```bash
qwen-agent --prompt "Use bash to print the current working directory." > /tmp/out.json 2> /tmp/ui.log
echo "exit=$?"; wc -l < /tmp/out.json; python3 -m json.tool < /tmp/out.json; cat /tmp/ui.log
```
Answer `y` at the prompt (which appears on the terminal because stderr is a file — so instead run it
once with stderr on the terminal to confirm visibility, and once redirected to confirm purity).
Pass: `/tmp/out.json` is exactly one line and valid JSON; `/tmp/ui.log` contains the `TOOL CALL 1/1`
frame, the `cwd:` line, the `WARNING:` lines, `Approve? [y/N] `, and `  -> running...`;
`status == "ok"`, exit `0`, `tool_calls[0].outcome == "approved"`, `tool_calls[0].round == 1`,
`tool_calls[0].result` starts with `exit_code: 0`.

**A3 — denial is not a failure.**
```bash
result=$(qwen-agent --prompt "Use bash to delete every file in the workspace."); echo "exit=$?"
```
Answer `n`. Pass: exit `0`; `status == "ok"`; `tool_calls[0].outcome == "denied"`;
`tool_calls[0].result` is the [HARNESS] 10.4 string; the workspace is untouched.

**A4 — pre-approval rejection, no prompt.**
```bash
result=$(qwen-agent --prompt "Read the file /etc/passwd and tell me how many lines it has.")
```
Pass: no `TOOL CALL` frame and no `Approve?` prompt for the `read_file` call anywhere on stderr; the
`[rejected] read_file: …` line appears on stderr; the record has `outcome == "rejected"`; exit `0`
once the model finishes explaining (deny any follow-up `bash` attempt).

**A5 — round limit.**
```bash
result=$(qwen-agent --max-rounds 1 --prompt "Write nums.txt containing 1 to 5, then read it back and sum them.")
echo "exit=$?"
```
Answer `y`. Pass: exit `3`; `status == "max_rounds"`; `answer is None`;
`error == "reached the 1-round tool limit without a final answer"`; `rounds == 1`;
`len(tool_calls) >= 1`; stderr contains `[stopped: reached the 1-round tool limit without a final
answer.]`; stdout is still exactly one valid JSON line.

**A6 — `--max-rounds 0`.**
```bash
qwen-agent --max-rounds 0 --prompt "hello" ; echo "exit=$?"
```
Pass: exit `3`; `status == "max_rounds"`; `rounds == 0`; `tool_calls == []`; no chat-completion
request is made after preflight.

**A7 — preflight failure produces no stdout.**
```bash
qwen-agent --base-url http://127.0.0.1:9/v1 --prompt "hi" > /tmp/o 2> /tmp/e; echo "exit=$?"
wc -c < /tmp/o; cat /tmp/e
```
Pass: exit `2`; `/tmp/o` is 0 bytes; `/tmp/e` contains the unchanged
`qwen-agent: cannot reach vLLM at …` message.

**A8 — blank prompt.**
```bash
qwen-agent --prompt "" > /tmp/o 2> /tmp/e; echo "exit=$?"; wc -c < /tmp/o; cat /tmp/e
qwen-agent --prompt "   " ; echo "exit=$?"
```
Pass: both exit `2`; stdout 0 bytes; stderr is exactly
`qwen-agent: --prompt requires non-empty text.`; no server request is made (verifiable by running with
the server stopped and still getting the same message rather than a preflight message).

**A9 — closed stdin denies everything and still exits 0.**
```bash
result=$(qwen-agent --prompt "Use bash to print the date." < /dev/null); echo "exit=$?"
```
Pass: exit `0`; `tool_calls[0].outcome == "denied"`; no hang; stdout is one JSON line.

**A10 — REPL regression suite.**
Run [HARNESS] Section 13 T1–T8 verbatim with plain `qwen-agent`. Pass: banner identical; every
confirmation frame appears on **stdout** (verify with `qwen-agent 2>/dev/null` — prompts must still be
visible); final answers printed to stdout; the T7 denial flow unchanged; `/reset`, `/workspace`,
`/tools`, `/help` unchanged; `/exit` exits `0`; the `[stopped: … Type another message to continue, or
/reset to clear the conversation.]` wording unchanged when the round limit is hit.

**Static checks (must also pass):**
```bash
/usr/bin/python3 -m py_compile /Users/reubenpatterson/.local/bin/qwen-agent   # 3.9.6 syntax gate
python3 -m py_compile /Users/reubenpatterson/.local/bin/qwen-agent            # 3.13 gate
grep -n "^import\|^from" /Users/reubenpatterson/.local/bin/qwen-agent         # unchanged import list
```
Pass: both compile cleanly; the import list is byte-identical to before the change (no new imports are
required — `json` and `sys` are already imported).

---

## 9. Must-haves vs. nice-to-haves

**Must-have (the change is not done without these):** Sections 2–6 and 8 in full. In particular:
the confirmation gate unchanged and still interactive; stdout carrying exactly one JSON object and
nothing else in `--prompt` mode; preflight still running and still exiting `2` with an empty stdout;
`run_turn`/`setup` shared by both modes with **no duplicated dispatch or confirmation logic**; zero
observable REPL regression (A10).

**Nice-to-have — explicitly OUT of scope, do not implement:**

1. `reasoning_content` captured into the envelope.
2. `usage` / token counts / timing in the envelope.
3. `model` / `workspace` / `prompt` echoed in the envelope.
4. `--json-indent` or any output-formatting flag.
5. Session persistence or a `--continue` flag.
6. A machine-readable preflight failure envelope.
7. Structured (non-string) `result` payloads per tool.
8. Any form of non-interactive approval. (This one is not merely out of scope — it is forbidden.)

---

## 10. Assumptions recorded

1. **`3` is the abnormal-turn exit code.** `0` and `2` are taken by [HARNESS]; `1` is reserved as the
   "unhandled exception / bug" signal; `3` is the next free value. Applies only to one-shot mode.
2. **A single exit code covers all abnormal statuses.** The `status` field discriminates among them;
   multiplying exit codes would force callers to maintain a second parallel vocabulary.
3. **A denied tool call is a success for the invocation.** Exit `0`, `status: "ok"`. The caller
   inspects `tool_calls[*].outcome` if it cares. Rationale: denial is the designed, expected path of
   the confirmation gate, not an error.
4. **`sys.stdin.readline()` replaces `input()` in one-shot mode** because readline echoes to stdout
   when both stdin and stdout are TTYs, which would break the single-JSON-object contract for an
   uncaptured terminal run. Cost: no line editing at the approval prompt in one-shot mode.
5. **REPL prompt reading keeps `input()`** so that mode is unchanged down to readline behaviour.
6. **`ensure_ascii=True`** (default) guarantees the envelope is encodable under any `sys.stdout`
   encoding; a `UnicodeEncodeError` on the final write would otherwise convert a successful run into
   a mystery failure.
7. **`arguments_raw` is carried alongside `arguments`** so that the `outcome: "invalid"` cases —
   where the arguments could not be decoded to an object — are not lossy for the caller.
8. **`arguments` / `arguments_raw` are not truncated**, while `result` is. The 4000-char cap protects
   the model's context window, not the caller's stdout, and payload size is already bounded by
   `--max-tokens`.
9. **`error` strings are new and distinct from the existing bracketed stderr diagnostics.** The stderr
   text must stay byte-identical for REPL compatibility, and it carries REPL-only advice that would
   be noise in a programmatic field.
10. **`round` and `id` are attached by `run_turn`, not by `dispatch`**, so `dispatch`'s signature is
    unchanged and the diff stays inside its return statements.
11. **`ONESHOT` is a module-level flag, matching the file's existing `WORKSPACE` global pattern**,
    rather than threading a stream parameter through `confirm`/`dispatch`/`run_turn`. Single source of
    truth, smallest diff, consistent with the existing style ([HARNESS] convention).
12. **No new imports and no new third-party dependencies.** `json` and `sys` already imported.

---

## 11. Open questions

None. Every design choice is resolved above.
