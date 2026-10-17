# qwen-agent fleet -- Design Spec (end-to-end tracing, piece D)

Date: 2026-10-17
Status: The user approved every design decision of piece D in three sections on 2026-10-17: Section 1 (W3C-shaped IDs, stdlib only, span kinds `turn`, `model`, `tool`, `delegate`, `run`, `agent`, the optional `trace` body field on `/delegate` and `/run`, the `QWEN_AGENT_TRACE_ID` / `QWEN_AGENT_PARENT_SPAN` child environment, the JSONL record, the daemon as the single writer, loopback `POST /spans` with a 2 s client timeout, signed `GET /trace/<id>`, loopback `GET /trace?id=` fan-out and `GET /traces/recent`, the tree built from parent links); Section 2 (the REPL `/trace` commands, the `qwen-agentd trace` CLI, the tree and recent-list output, the failure cases); Section 3 (the test plan and the rollout). This document writes those decisions down precisely enough to implement without reopening any. Every value they left open is marked **[spec choice]** with a one-line reason, and Section 10 collects them. No design decision is left open.

Repository: `/Users/reubenpatterson/local_agent_harness`, branch `qwen-agent-redteam`. `WS` is `qwen-agent-workspace/`; relative paths are relative to `WS`.

Specs this one builds on. Their requirements are treated as **already implemented** when this feature is implemented (piece D is implemented after piece C), and are cited by ID:

- `docs/superpowers/specs/2026-10-16-fleet-discovery-self-update-design.md`, **[FLEET]** (`F<n>`, `T<n>`, `K<n>`, rollout `R<n>` in its Section 12).
- `docs/superpowers/specs/2026-10-17-fleet-multi-agent-hosts-design.md`, **[MULTI]** (`M<n>`, `MT<n>`).
- `docs/superpowers/specs/2026-10-17-fleet-vision-agent-design.md` and its plan `docs/superpowers/plans/2026-10-17-fleet-vision-agent.md`, **[VISION]** (`V<n>`, `VT<n>`, `VR<n>`). Its final code is this spec's base: `body_cap`, `request_images`, `delegate_once(..., images=None)`, `_RUN_KEYS`, `_DELEGATE_KEYS`, the V11 `_handle`, `spawn_run(skill, task, images=None)` with `_run_child(argv)`, `forward_run(..., images=None)` with its two unsigned-status rows, `_delegate_remote(..., images=None)`.

This spec edits **no other spec file**. Where it changes a requirement of those specs, Section 8 lists the change.

ID conventions: `TR<n>` is a requirement, `TRT<n>` a test, `TRK<n>` a success criterion, `TRR<n>` a live rollout step, `TRX<n>` an accepted risk, `TRC<n>` a contradiction. None clashes with F, T, K, R, M, MT, MK, MR, P, H, S, V, VT, VK, VR, VX or VC.

Line numbers cite `2eb980f` (the [MULTI] head, before [VISION]): `fleet_lib.py` (1210 lines), `bin/qwen-agentd` (1507), `bin/qwen-agent` (3864), `tests/fleet_testutil.py` (479). [VISION] edits several of the same functions first (its Tasks 2-6; `d9248ff` already carries Tasks 2-4). Every change below is described by function name as well as by line, and composes with [VISION]'s edits.

---

## 0. Purpose and scope

### 0.1 Purpose

Debug one request end to end. Today a delegated request leaves four disconnected traces: the caller's `[auto]` line and decision log, the caller daemon's `delegate ... request_id=<r>` line, the peer daemon's `run start/run end ... request_id=<r>` lines, and the peer child's `last-run.stderr`. This feature records one **trace** per REPL turn or one-shot, made of **spans** (hops, tool calls, model calls) with timings, statuses and a few bounded attributes, links them across processes and hosts by parent span ID, and shows them as one tree on demand from any agent host. There is no collector: each agent's daemon stores its own spans, and a query pulls them from every peer.

### 0.2 Grounding (shipped code)

**`fleet_lib.py`.** `PROTOCOL = 1` (`:25`) stays 1. `PEER_HTTP_TIMEOUT = 5` (`:38`), `MAX_BODY = 1048576` (`:44`), `REQUEST_ID_RE` (`:55`), `LOG_MAX_BYTES = 5242880` and `LOG_BACKUPS = 3` (`:80-81`). `canonical_json` (`:338-340`) is sorted-key, compact, `ensure_ascii=True`. `verify_request` (`:476-480`) checks headers, signature, skew, replay (F29h) over `method` and the **full request path** (query string included), so a signed `GET /trace/<id>` binds the ID. `build_child_env` (`:539-549`) copies the environment minus `QWEN_AGENT_FLEET_*` and `SKILL_*`, then sets `QWEN_AGENT_DAEMON_URL`. `_ROUTES` (`:688-694`) is an exact `(method, path)` table and `http_route` (`:702-704`) a dict lookup, so `/trace/<id>` and `?`-queries need a rule beyond the table. `fetch_view` (`:782-810`) and `delegate_once` (`:813-843`) are the `http.client` loopback clients (F44: never `urllib`). `log_dir(host_id)` (`:860-862`) is `A(<id>)/logs`. `shown_value` (`:1020-1024`) masks 64-hex runs in error text. The module imports no `secrets` (`:14-23`; [VISION] adds `base64` first).

**`bin/qwen-agentd`.** `_PrivateRotatingFileHandler` and `setup_logging` (`:162-182`) create `A/logs` mode 0700 and rotate `qwen-agentd.log` at 5 MB x 3. `_FleetHandler` (`:301-404`): HTTP/1.0 (`:304`), 30 s socket timeout (`:305`), `_loopback_request_ok` (`:338-350`: `Host` must be `127.0.0.1:<port>`, `localhost:<port>` or `[::1]:<port>`, no `Origin`, POST needs `Content-Type: application/json`), `_handle` (`:368-404`, replaced by [VISION] V11) calls `fleet.loopback_endpoint(name, body)` and `fleet.signed_endpoint(name, body)` without the path. The server is a `ThreadingHTTPServer` (`:284-291`), so handlers run concurrently. `Daemon._thread` (`:484-487`). `signed_call` (`:612-635`) returns `None` for every failure, losing the reason. `handle_run` (`:756-781`), `spawn_run` (`:783-815`), `handle_delegate` (`:819-839`), `forward_run` (`:841-874`) as [VISION] V14-V18 rewrite them. `cmd_status` and `_status_port` (`:1002-1067`) resolve an agent's loopback port from its registry ([MULTI] M30). `_build_parser` (`:1454-1485`).

**`bin/qwen-agent`.** The import set (`:26-43`) is pinned by `tests/test_qwen_agent_context_budget.py:477-491` (C8) and `tests/test_qwen_agent_session_memory.py:684-695` (M14): no import statement may be added; `secrets` is not imported, but `FLEET` (the lazily loaded `fleet_lib`, `:638-659`) is. `TRACE_KEY_CHARS = 200`, `TRACE_OUTCOME_CHARS = 160` (`:145-146`). `_trace_clip` (`:911-916`), `_auto_key` (`:919-943`), `_call_key` (`:946-974`: for `delegate_to_skill` the key is `skill=<s> task=<task>`, which contains task text), `_auto_trace_outcome` (`:977-998`: never echoes page text, file contents or a sub-agent's answer). `_log_decision` writes `WORKSPACE/tool_decisions.log` (`:1609-1636`). `dispatch` (`:1667-1837`) returns one record `{"tool", "arguments", "arguments_raw", "outcome", "deny_reason", "result"}` at every exit. `chat_completion` (`:1851-1877`) is the only chat call used by `run_turn` and `_forced_summary`, and also by `memory_checkpoint` (`:3234`); `preflight` uses its own `urlopen` calls. `run_turn` (`:3437-3585`) reads `finish_reason` (`:3510`) but no `usage`; its dispatch loop is `:3547-3560`. `repl` (`:3588-3667`): the turn is `:3629-3633`, the memory checkpoint `:3664-3667`. `oneshot` (`:3716-3756`): `run_turn` at `:3733`, the envelope `:3746-3756`. `exec_delegate_to_skill` (`:1266-1361`) builds the local child env at `:1315-1316`; `_delegate_remote` (`:1364-1391`). `HELP_TEXT` (`:2085-2104`), `handle_slash_command` (`:2273-2314`).

**Tests.** `tests/fleet_testutil.py`: `clean_env` (`:72-80`) drops every `QWEN_AGENT_*` variable; `StubModelServer` (`:112-181`) returns `usage` with 1/1 tokens (`:171`); `delegate` (`:292-297`). `tests/test_fleet_lib.py` is the self-update gate's selftest (F93) and must stay fast. [VISION]'s `test_vt27_*` asserts the exact key set of the `/run` bodies a daemon forwards (Section 6.6).

### 0.3 Deliverables

| # | File | Change |
|---|---|---|
| G1 | `fleet_lib.py` | `import secrets`; trace constants; IDs; record schema, builder and validator; sanitizers; body field and env helpers; routes and body cap; `TraceStore`; peer-result and merge helpers; `post_span`, `fetch_trace`, `fetch_recent`; `delegate_once(trace=)`; `build_child_env(trace=)`; `render_trace`, `render_recent`, `fmt_ms` (Section 1) |
| G2 | `bin/qwen-agentd` | endpoints `/spans`, `/trace/<id>`, `/trace?id=`, `/traces/recent`; run, agent and delegate spans; `trace` forwarding and the old-peer retry; `trace` subcommand (Section 2) |
| G3 | `bin/qwen-agent` | turn, model and tool spans; propagation to local and remote delegations; the per-turn post budget; `/trace` (Section 3) |
| G4 | `tests/fleet_testutil.py` | helper additions (Section 6.2) |
| G5 | `tests/test_fleet_lib.py` | unit tests TRT1-TRT14 |
| G6 | `tests/test_qwen_agent_tracing.py` (new) | harness tests TRT20-TRT28 **[spec choice: a new file keeps existing suites' diffs at zero]** |
| G7 | `tests/test_fleet_tracing.py` (new) | integration tests TRT40-TRT49 |
| G8 | `tests/test_fleet_vision.py` | the one migrated assertion of Section 6.6 |

`bin/qwen-agentd-launch`, `agent/qwen-agent-unsafe`, `scripts/`, `README.md`, every spec file, and every other file are not changed.

### 0.4 Out of scope

- OpenTelemetry (no dependency, no OTLP export, no `traceparent` header), sampling, a collector, a UI.
- Tracing preflight, `setup`, `discover_context_window`, the memory checkpoint, beacons, polling, self-update.
- Correcting clock skew between hosts (the tree uses parent links; only sibling order uses timestamps).
- Retention by age; compression; a trace ID in the one-shot envelope or in any log line.
- Recording any text other than the two bounded tool attributes of TR4 (Section 4.3 lists what is never recorded).

### 0.5 Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| TRK1 | `python3 -m pytest tests/ -q -rA` from `WS` gives the baseline recorded immediately before implementation (after [VISION] is in), with the Section 6.6 migrated test passing, plus every TRT test passing, and no lost pass. `python3 tests/test_qwen_agent_context_budget.py`, `python3 tests/test_qwen_agent_image_oneshot.py` and `python3 tests/test_qwen_agent_session_memory.py` each print the same `OK n/n` as at the baseline | TRT60 |
| TRK2 | `/usr/bin/python3 -m py_compile` (3.9.6) and `python3 -m py_compile` (3.13) succeed on `fleet_lib.py`, `bin/qwen-agent`, `bin/qwen-agentd`, `bin/qwen-agentd-launch` and every changed or new test file | TRT61 |
| TRK3 | Standard library only. `bin/qwen-agent`'s import set is unchanged (C8, M14). `fleet_lib.py` adds exactly `import secrets`; `bin/qwen-agentd` adds no import. Every trace HTTP call uses `http.client`; no `urllib.request` or `urlopen` appears in `fleet_lib.py` or `bin/qwen-agentd` | TRT62, `test_daemon_never_uses_urllib_request` |
| TRK4 | Tests never use the real `HOME`, and never reach a daemon running on the machine: every new test sets `HOME` to a temp directory and sets `QWEN_AGENT_DAEMON_URL` (subprocesses) or `qa.FLEET_DAEMON_URL` (in-process) to a test daemon or a closed port | review of TRT20-TRT49 |
| TRK5 | No task text, user prompt, system prompt, model answer, tool result body, image byte or base64, fleet token, key or join string appears in any trace record, any file under any agent's `A/logs/` (the token: including `last-run.stderr`), any `/trace`, `/trace/<id>` or `/traces/recent` response, or `qwen-agentd trace` output | TRT4, TRT27, TRT47 |
| TRK6 | A tracing failure (no daemon, a daemon slower than 2 s, a daemon answering 500, a daemon that cannot write its store) never changes a turn's stdout, answer, envelope or exit code, and adds at most 2 s to one process's turn | TRT24, TRT49 |
| TRK7 | Live: a Mac REPL turn that delegates to `researcher` on `ollama-168` shows one connected tree under `/trace` | TRR2 |

### 0.6 Must-have vs nice-to-have

Every requirement TR1-TR50 is a must-have. Nothing else is built.

---

## 1. `fleet_lib.py`

### 1.1 Constants, import, IDs

- **TR1. Constants.** Directly after `LOG_BACKUPS = 3` (`:81`; after [VISION]'s `RUN_TMP_*`), add exactly:

  ```python
  # --- tracing (docs/superpowers/specs/2026-10-17-fleet-tracing-design.md) ---
  TRACE_FILE_NAME = "trace.jsonl"     # A(<id>)/logs/trace.jsonl, rotated LOG_MAX_BYTES x LOG_BACKUPS (TR10)
  TRACE_SCHEMA = "qwen-agentd.trace.v1"     # loopback GET /trace?id= response (TR27)
  RECENT_SCHEMA = "qwen-agentd.recent.v1"   # loopback GET /traces/recent response (TR28)
  TRACE_RECORD_VERSION = 1
  TRACE_KINDS = ("turn", "model", "tool", "delegate", "run", "agent")
  TRACE_POSTED_KINDS = ("turn", "model", "tool")    # the kinds a qwen-agent may POST /spans
  TRACE_ENV_ID = "QWEN_AGENT_TRACE_ID"
  TRACE_ENV_PARENT = "QWEN_AGENT_PARENT_SPAN"
  TRACE_SPAN_MAX_BYTES = 8192         # POST /spans body cap (TR9)
  TRACE_TEXT_CHARS = 256              # longest tool key or outcome attribute
  TRACE_COUNT_MAX = 10 ** 15          # largest integer attribute
  TRACE_DUR_MAX_MS = 10 ** 10
  TRACE_MAX_RECORDS = 2000            # records one agent returns for one trace
  TRACE_QUERY_MAX_BYTES = MAX_BODY - 4096   # their encoded size; 4 KiB is left for the envelope
  TRACE_POST_TIMEOUT = 2              # s, bin/qwen-agent POST /spans; never scaled
  TRACE_FANOUT_DEADLINE = PEER_HTTP_TIMEOUT + 1   # s, one fan-out round to peers; never scaled
  TRACE_QUERY_TIMEOUT = 20            # s, a client's GET /trace?id= (two fan-out rounds plus margin)
  TRACE_RECENT_TIMEOUT = 5            # s, a client's GET /traces/recent
  TRACE_RECENT_DEFAULT = 10
  TRACE_RECENT_MAX = 100
  TRACE_CLIENT_MAX_BYTES = 33554432   # largest /trace?id= or /traces/recent response a client reads
  TRACE_ID_RE = re.compile(r"[0-9a-f]{32}")
  SPAN_ID_RE = re.compile(r"[0-9a-f]{16}")
  TRACE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:@+-]{0,127}")
  TRACE_TOKEN_RE = re.compile(r"[a-z][a-z_]{0,31}")
  _TRACE_TEXT_BAD_RE = re.compile(r"[\x00-\x1f\x7f]")
  ```

  `TRACE_SPAN_MAX_BYTES = 8192` **[spec choice: a 256-character key and outcome escaped as `\uXXXX` surrogate pairs by `ensure_ascii` is under 6.2 KiB]**. `TRACE_QUERY_TIMEOUT = 20` **[spec choice: TR27 has at most two rounds of 6 s, plus the local read]**. `TRACE_CLIENT_MAX_BYTES = 32 MiB` **[spec choice: 1 MiB per agent for up to 31 peers; the registry is far smaller]**. `TRACE_TOKEN_RE` must start with a letter, so every status, decision and `finish_reason` value below matches.
- **TR2. Import.** `import secrets` is added to the import block, directly after `import re`. No other import.
- **TR3. IDs.** In a new section `# Tracing: IDs, records, the store, the clients and the tree (tracing spec)` placed at the end of the file:

  ```python
  def _valid_id(value, regex):
      return isinstance(value, str) and regex.fullmatch(value) is not None and value.strip("0") != ""


  def valid_trace_id(value):
      """True for 32 lowercase hex characters, not all zero (W3C trace-id shape)."""
      return _valid_id(value, TRACE_ID_RE)


  def valid_span_id(value):
      """True for 16 lowercase hex characters, not all zero (W3C parent-id shape)."""
      return _valid_id(value, SPAN_ID_RE)


  def new_trace_id():
      """A fresh trace ID from secrets.token_hex(16); the all-zero value is drawn again."""
      while True:
          value = secrets.token_hex(16)
          if valid_trace_id(value):
              return value


  def new_span_id():
      """A fresh span ID from secrets.token_hex(8); the all-zero value is drawn again."""
      while True:
          value = secrets.token_hex(8)
          if valid_span_id(value):
              return value
  ```

  `request_id` ([FLEET] F65, 16 hex) is not replaced: it stays the daemons' log key and becomes a hop attribute (TR4).

### 1.2 The record

- **TR4. Schema.** One finished span is one JSON object, stored as one `canonical_json` line. Exactly these keys:

  | Key | Type and limit |
  |---|---|
  | `v` | int, exactly `1` (`bool` rejected) |
  | `trace_id` | `valid_trace_id` |
  | `span_id` | `valid_span_id` |
  | `parent_span_id` | `null`, or `valid_span_id` and not equal to `span_id` |
  | `agent` | the recording agent's ID, `HOST_ID_RE`. **Absent** in the `/spans` form; the daemon adds it (TR22) |
  | `kind` | one of `TRACE_KINDS` (`/spans` form: one of `TRACE_POSTED_KINDS`) |
  | `name` | `TRACE_NAME_RE` |
  | `start` | int or float (not bool), `0 <= start < 10**11`: wall-clock seconds, `round(time.time(), 3)` |
  | `dur_ms` | int, `0 <= dur_ms <= TRACE_DUR_MAX_MS`, from `time.monotonic()` |
  | `status` | `TRACE_TOKEN_RE` |
  | `attrs` | object with **exactly** the keys of its kind below |

  Attribute types: `int` is a non-bool int in `0..TRACE_COUNT_MAX`; `bool`; `token` matches `TRACE_TOKEN_RE`; `name` matches `TRACE_NAME_RE`; `agent` matches `HOST_ID_RE`; `reqid` matches `REQUEST_ID_RE`; `text` is a `str` of at most `TRACE_TEXT_CHARS` characters with no character in `[\x00-\x1f\x7f]`; `?` adds `null`.

  ```python
  _TRACE_KEYS = frozenset(("v", "trace_id", "span_id", "parent_span_id", "agent", "kind", "name",
                           "start", "dur_ms", "status", "attrs"))
  _TRACE_ATTRS = {
      "turn": {"rounds": "int", "tool_calls": "int"},
      "model": {"call": "int", "tools": "bool", "prompt_tokens": "int?", "completion_tokens": "int?",
                "finish_reason": "token?", "http": "int?"},
      "tool": {"round": "int", "decision": "token", "key": "text", "outcome": "text", "error": "bool"},
      "delegate": {"skill": "name", "target": "agent", "request_id": "reqid?", "http": "int?",
                   "images": "int"},
      "run": {"skill": "name", "request_id": "reqid", "http": "int", "images": "int", "image_bytes": "int"},
      "agent": {"skill": "name", "request_id": "reqid", "http": "int", "envelope_status": "token?"},
  }
  ```

  The kinds, who records them, their `name`, their `status` values and their parent:

  | Kind | Recorded by | `name` | `status` | Parent |
  |---|---|---|---|---|
  | `turn` | `bin/qwen-agent`, one per `run_turn` of a process that inherited **no** trace (TR42) | `repl`, `oneshot`, or the `--skill` value | the turn status (`ok`, `max_rounds`, `circuit_open`, `context_budget`, `truncated`, `interrupted`, `http_error`, `context_length`, `network_error`, `malformed_response`) | `null` (always a root) |
  | `model` | `bin/qwen-agent`, one per traced `chat_completion` | the model ID (`trace_name`) | `ok`, `http_error`, `network_error`, `malformed_response`, `interrupted`, `error` | the turn; in a child that inherited a trace, `QWEN_AGENT_PARENT_SPAN` (the agent span, or the caller's tool span for a local child) |
  | `tool` | `bin/qwen-agent`, one per dispatched tool call | the tool name, or `unknown` | `ok` / `error` for an executed call (by its `ERROR:` prefix), else the dispatch outcome (`denied`, `invalid`, `duplicate`, `circuit_open`, `rejected`) | as for `model` |
  | `delegate` | the caller's daemon, one per `POST /delegate` that passes validation | the skill | the F68 outcome (`ok`, `not_live`, `busy`, `timeout`, `unreachable`, `bad_signature`, `bad_response`, `peer_error`) | the body's `trace.parent_span_id` (the tool span), or `null` |
  | `run` | the peer's daemon, one per verified `POST /run` that passes the shape check | the skill (`trace_skill`) | `ok` (http 200 and envelope `ok`), `busy` (409), else `error` | the body's `trace.parent_span_id` (the delegate span), or `null` |
  | `agent` | the peer's daemon, one per `/run` child process (`spawn_run`, from image staging to its result) | the skill | `ok` (http 200 and envelope `ok`), else `error` | the run span |

  Per the approved Section 1 diagram (run -> agent -> model/tool/delegate), the daemon passes the **agent** span's ID as the child's `QWEN_AGENT_PARENT_SPAN` (TR23), and a child started with an inherited trace posts **no** `turn` span: its model and tool spans hang directly off the agent span (TR42). The agent span is the daemon's view of the child process (http code, envelope status), so it stands in for the child's turn and remains even when the child crashes before posting anything. A local `--skill` child (no daemon) likewise posts no turn; its spans hang off the caller's tool span.
- **TR5. Builder and validator.**

  ```python
  def make_record(trace_id, span_id, parent_span_id, agent, kind, name, start, t0, status, attrs, now=None):
      """One finished span (tracing spec TR4). agent None gives the /spans form, without "agent".

      start is round(time.time(), 3) at the span's start; t0 is time.monotonic() then, so
      dur_ms is immune to wall-clock steps. now (a monotonic time) is for tests.
      """
      end = time.monotonic() if now is None else now
      record = {"v": TRACE_RECORD_VERSION, "trace_id": trace_id, "span_id": span_id,
                "parent_span_id": parent_span_id, "kind": kind, "name": name, "start": start,
                "dur_ms": max(0, int(round((end - t0) * 1000))), "status": status, "attrs": attrs}
      if agent is not None:
          record["agent"] = agent
      return record


  def _trace_attr_ok(kind, value):
      if kind.endswith("?"):
          if value is None:
              return True
          kind = kind[:-1]
      if kind == "int":
          return _is_int(value) and 0 <= value <= TRACE_COUNT_MAX
      if kind == "bool":
          return isinstance(value, bool)
      if not isinstance(value, str):
          return False
      if kind == "text":
          return len(value) <= TRACE_TEXT_CHARS and _TRACE_TEXT_BAD_RE.search(value) is None
      regex = {"token": TRACE_TOKEN_RE, "name": TRACE_NAME_RE, "agent": HOST_ID_RE, "reqid": REQUEST_ID_RE}[kind]
      return regex.fullmatch(value) is not None


  def trace_record_error(rec, posted=False):
      """None for a valid trace record, else the name of its first bad field (tracing spec TR4).

      posted=True checks the /spans form: no "agent", and only TRACE_POSTED_KINDS. Never raises;
      the result never contains any part of rec.
      """
      try:
          if not isinstance(rec, dict):
              return "record"
          if set(rec) != (_TRACE_KEYS - {"agent"} if posted else _TRACE_KEYS):
              return "keys"
          if not (_is_int(rec["v"]) and rec["v"] == TRACE_RECORD_VERSION):
              return "v"
          if not valid_trace_id(rec["trace_id"]):
              return "trace_id"
          if not valid_span_id(rec["span_id"]):
              return "span_id"
          parent = rec["parent_span_id"]
          if parent is not None and not (valid_span_id(parent) and parent != rec["span_id"]):
              return "parent_span_id"
          if not posted and not (isinstance(rec["agent"], str) and HOST_ID_RE.fullmatch(rec["agent"])):
              return "agent"
          if not (isinstance(rec["kind"], str) and rec["kind"] in (TRACE_POSTED_KINDS if posted else TRACE_KINDS)):
              return "kind"
          if not (isinstance(rec["name"], str) and TRACE_NAME_RE.fullmatch(rec["name"])):
              return "name"
          start = rec["start"]
          if not ((_is_int(start) or isinstance(start, float)) and 0 <= start < 10 ** 11):
              return "start"
          if not (_is_int(rec["dur_ms"]) and 0 <= rec["dur_ms"] <= TRACE_DUR_MAX_MS):
              return "dur_ms"
          if not (isinstance(rec["status"], str) and TRACE_TOKEN_RE.fullmatch(rec["status"])):
              return "status"
          schema = _TRACE_ATTRS[rec["kind"]]
          attrs = rec["attrs"]
          if not (isinstance(attrs, dict) and set(attrs) == set(schema)):
              return "attrs"
          for key in sorted(schema):
              if not _trace_attr_ok(schema[key], attrs[key]):
                  return "attrs." + key
          return None
      except Exception:
          return "record"
  ```

  NaN and infinity fail the `start` range test. There is no separate size check: the field limits bound a stored line below 7 KiB.
- **TR6. Sanitizers.** Values that come from a model, a peer or a child pass through these before they enter a record:

  ```python
  def trace_name(value):
      """value when it is a valid span name, else "unknown"."""
      return value if isinstance(value, str) and TRACE_NAME_RE.fullmatch(value) else "unknown"


  def trace_skill(value):
      """A skill for a span: a KNOWN_SKILLS member, else "unknown" (a /run body's skill is unchecked text)."""
      return value if isinstance(value, str) and value in KNOWN_SKILLS else "unknown"


  def trace_token(value):
      """value when it matches TRACE_TOKEN_RE, else None (envelope statuses, finish_reason)."""
      return value if isinstance(value, str) and TRACE_TOKEN_RE.fullmatch(value) else None


  def trace_count(value):
      """value when it is an int attribute (usage token counts), else None."""
      return value if _is_int(value) and 0 <= value <= TRACE_COUNT_MAX else None


  def run_status(http, envelope_status):
      """The status of a run span (tracing spec TR4)."""
      if http == 200 and envelope_status == "ok":
          return "ok"
      return "busy" if http == 409 else "error"
  ```

### 1.3 Propagation helpers

- **TR7. Body field.** The optional `trace` key of a `/delegate` or `/run` body is exactly `{"trace_id": <valid_trace_id>, "parent_span_id": <valid_span_id>}`:

  ```python
  def valid_trace_field(obj):
      """True for {"trace_id", "parent_span_id"} with valid IDs and no other key (tracing spec TR7)."""
      return (isinstance(obj, dict) and set(obj) == {"trace_id", "parent_span_id"}
              and valid_trace_id(obj["trace_id"]) and valid_span_id(obj["parent_span_id"]))


  def trace_context(field):
      """(trace_id, parent_span_id) from a validated trace field, or a new trace with no parent."""
      if field is None:
          return new_trace_id(), None
      return field["trace_id"], field["parent_span_id"]
  ```

  A request without the key starts a new trace whose first span is a root. **[spec choice: a request from a caller without tracing is still debuggable on this host, and is listed by `trace --recent`.]**
- **TR8. Environment.**

  ```python
  def trace_env_context(environ):
      """(trace_id, parent_span_id) from QWEN_AGENT_TRACE_ID and QWEN_AGENT_PARENT_SPAN when both are valid, else None."""
      trace_id, parent = environ.get(TRACE_ENV_ID, ""), environ.get(TRACE_ENV_PARENT, "")
      if valid_trace_id(trace_id) and valid_span_id(parent):
          return trace_id, parent
      return None
  ```

  `build_child_env` (`:539-549`) becomes:

  ```python
  def build_child_env(environ, daemon_url, trace=None):
      """A new env for a /run child: no fleet secrets, no SKILL_* overrides (F54a), and no
      inherited trace; trace=(trace_id, parent_span_id) sets the child's (tracing spec TR8)."""
      env = {}
      for key, value in environ.items():
          if key.startswith(FLEET_ENV_PREFIX):
              continue
          if key.startswith("SKILL_ENDPOINT_") or key.startswith("SKILL_MODEL_"):
              continue
          if key in (TRACE_ENV_ID, TRACE_ENV_PARENT):
              continue
          env[key] = value
      env["QWEN_AGENT_DAEMON_URL"] = daemon_url
      if trace is not None:
          env[TRACE_ENV_ID], env[TRACE_ENV_PARENT] = trace
      return env
  ```

  With `trace=None` the result equals today's minus any inherited trace variables (T12 unchanged).

### 1.4 Routes and caps

- **TR9.** `_ROUTES` (`:688-694`) gains `("POST", "/spans"): ("loopback", "spans")`. `http_route` becomes:

  ```python
  def http_route(method, path):
      """(kind, name) for a request; ("unknown", None) for every other pair (F42, tracing spec TR9)."""
      route = _ROUTES.get((method, path))
      if route is not None:
          return route
      if method == "GET":
          if path.startswith("/trace/"):
              return "signed", "trace"
          if path == "/trace" or path.startswith("/trace?"):
              return "loopback", "trace_query"
          if path == "/traces/recent" or path.startswith("/traces/recent?"):
              return "loopback", "recent"
      return "unknown", None
  ```

  The endpoints validate the rest of the path (TR26-TR28). Every pair T24 lists as unknown stays unknown. A daemon without this feature answers a signed `GET /trace/<id>` with its signed 404 `{"error": "not found"}` (F44), which TR27 reports as `no trace support (http 404)`.

  [VISION]'s `body_cap(kind, name)` gains, as its first statement, `if (kind, name) == ("loopback", "spans"): return TRACE_SPAN_MAX_BYTES`. Every other route keeps its cap (VT5 unchanged).

### 1.5 The store

- **TR10. `TraceStore`: files, rotation, locking.**

  ```python
  def _json_loads_or_none(raw):
      try:
          return json.loads(raw)
      except (ValueError, RecursionError, TypeError):
          return None


  class TraceStore(object):
      """A(<id>)/logs/trace.jsonl and its backups trace.jsonl.1 .. .3 (tracing spec TR10-TR12).

      The daemon is the only writer. Every method holds one lock, so concurrent handler
      threads never interleave or tear a line, and a read never sees a rotation half done.
      Construction does no I/O.
      """

      def __init__(self, directory, max_bytes=LOG_MAX_BYTES, backups=LOG_BACKUPS):
          self.path = os.path.join(directory, TRACE_FILE_NAME)
          self.max_bytes = max_bytes
          self.backups = backups
          self._lock = threading.Lock()

      def _names(self):
          """The store's files, oldest first: path.<backups>, ..., path.1, path."""
          return ["%s.%d" % (self.path, i) for i in range(self.backups, 0, -1)] + [self.path]

      def append(self, record):
          """Append one valid stored-form record; rotate first when the line would pass max_bytes."""
          reason = trace_record_error(record)
          if reason is not None:
              raise ValueError("bad trace record: %s" % reason)
          line = canonical_json(record) + b"\n"
          with self._lock:
              try:
                  size = os.path.getsize(self.path)
              except FileNotFoundError:
                  size = 0
              if size > 0 and size + len(line) > self.max_bytes:
                  for i in range(self.backups - 1, 0, -1):
                      older = "%s.%d" % (self.path, i)
                      if os.path.lexists(older):
                          os.replace(older, "%s.%d" % (self.path, i + 1))
                  os.replace(self.path, self.path + ".1")
              fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
              try:
                  os.fchmod(fd, 0o600)
                  view = memoryview(line)
                  while view:
                      view = view[os.write(fd, view):]
              finally:
                  os.close(fd)

      def _records(self, needle=None):
          """Every valid stored record, oldest file first, line order; the caller holds the lock."""
          for name in self._names():
              try:
                  f = open(name, "rb")
              except FileNotFoundError:
                  continue
              with f:
                  for line in f:
                      if needle is not None and needle not in line:
                          continue
                      rec = _json_loads_or_none(line)
                      if trace_record_error(rec) is None:
                          yield rec
  ```

  - Rotation is RotatingFileHandler's rule with exact bytes: a non-empty current file whose size plus the new line would exceed `LOG_MAX_BYTES` (5 MB) is renamed `.1` after `.2 -> .3`, `.1 -> .2` (the old `.3` is replaced, so at most 4 files, about 20 MB, exist). No file exceeds 5 MB. Renames keep mode 0600.
  - The store never creates the directory: `setup_logging` (`:171-182`) made `A/logs` mode 0700 before the daemon exists. A missing directory makes `append` raise, which TR21 handles.
  - No `fsync` **[spec choice: a lost tail on power loss costs debugging data only; an fsync per span would cost every turn]**.
  - An unparsable or invalid line (a torn tail after a crash, a hand edit) is skipped by every reader.
- **TR11. `query`.**

  ```python
      def query(self, trace_id, max_records=TRACE_MAX_RECORDS, max_bytes=TRACE_QUERY_MAX_BYTES):
          """(records, truncated) of one trace: oldest file first, at most max_records records whose
          canonical encodings (plus one separator byte each) total at most max_bytes."""
          needle = ('"trace_id":"%s"' % trace_id).encode("ascii")
          records, total = [], 0
          with self._lock:
              for rec in self._records(needle):
                  if rec["trace_id"] != trace_id:
                      continue
                  size = len(canonical_json(rec)) + 1
                  if len(records) >= max_records or total + size > max_bytes:
                      return records, True
                  records.append(rec)
                  total += size
          return records, False
  ```

  `trace_id` is always `valid_trace_id` (the endpoints check it first). The byte needle skips non-matching lines without parsing them **[spec choice: `canonical_json` writes exactly this substring for the record's own ID, and no attribute is named `trace_id`]**. Reading holds the lock, so appends from other handler threads wait for the read (about 0.2 s for a full 20 MB store).
- **TR12. `recent`.**

  ```python
      def recent(self, n):
          """Up to n root spans of this store, newest first, each with its trace's local span
          count and delegations (tracing spec TR12)."""
          roots, counts, hops, forwarded, tools = {}, {}, {}, set(), []
          with self._lock:
              for rec in self._records():
                  tid = rec["trace_id"]
                  counts[tid] = counts.get(tid, 0) + 1
                  if rec["parent_span_id"] is None:
                      best = roots.get(tid)
                      if best is None or (rec["start"], rec["span_id"]) < (best["start"], best["span_id"]):
                          roots[tid] = rec
                  if rec["kind"] == "delegate":
                      forwarded.add(rec["parent_span_id"])
                      hops.setdefault(tid, []).append(
                          (rec["start"], rec["span_id"], "%s@%s" % (rec["attrs"]["skill"], rec["attrs"]["target"])))
                  elif (rec["kind"] == "tool" and rec["name"] == "delegate_to_skill" and rec["status"] == "ok"
                        and rec["attrs"]["key"].startswith("skill=")):
                      tools.append(rec)
          for rec in tools:
              skill = rec["attrs"]["key"][len("skill="):].split(" ")[0]
              if rec["span_id"] not in forwarded and skill in KNOWN_SKILLS:
                  hops.setdefault(rec["trace_id"], []).append(
                      (rec["start"], rec["span_id"], "%s@%s" % (skill, rec["agent"])))
          out = []
          for root in sorted(roots.values(), key=lambda r: (-r["start"], r["trace_id"]))[:n]:
              delegated = []
              for _start, _span, hop in sorted(hops.get(root["trace_id"], [])):
                  if hop not in delegated:
                      delegated.append(hop)
              out.append({"trace_id": root["trace_id"], "start": root["start"], "dur_ms": root["dur_ms"],
                          "status": root["status"], "kind": root["kind"], "name": root["name"],
                          "spans": counts[root["trace_id"]], "delegated": delegated})
          return out
  ```

  A remote delegation shows as `<skill>@<peer>` (its delegate span); a local subprocess delegation as `<skill>@<this agent>` (an approved, `ok` `delegate_to_skill` tool span with no delegate child, its skill read from the `skill=<s>` key). Failed attempts are listed too, in start order, each pair once. No task text is involved.

### 1.6 Merging peer answers

- **TR13.**

  ```python
  def peer_trace_result(trace_id, host_id, status, raw, reason):
      """(records, missing_reason, truncated_count) for one peer's GET /trace/<id> (tracing spec TR27).

      reason is the transport failure from the daemon's call (or None). Records that fail
      validation, name another agent or another trace are dropped silently.
      """
      if reason is not None:
          return [], reason, None
      if status == 404:
          return [], "no trace support (http 404)", None
      if status != 200:
          return [], "error (http %d)" % status, None
      obj = _json_loads_or_none(raw)
      if not (isinstance(obj, dict) and obj.get("agent") == host_id and obj.get("trace_id") == trace_id
              and isinstance(obj.get("records"), list) and isinstance(obj.get("truncated"), bool)):
          return [], "bad response", None
      records = [r for r in obj["records"]
                 if trace_record_error(r) is None and r["agent"] == host_id and r["trace_id"] == trace_id]
      return records, None, (len(obj["records"]) if obj["truncated"] else None)


  def merge_records(records):
      """Records with each span_id kept once (first wins), ordered by (start, agent, span_id)."""
      seen, out = set(), []
      for r in records:
          if r["span_id"] not in seen:
              seen.add(r["span_id"])
              out.append(r)
      return sorted(out, key=lambda r: (r["start"], r["agent"], r["span_id"]))
  ```

### 1.7 Clients

- **TR14. `post_span`, `fetch_trace`, `fetch_recent`.** All `http.client` to `127.0.0.1` (F44), all never raise.

  ```python
  def post_span(daemon_url, record, timeout=TRACE_POST_TIMEOUT):
      """True iff the local daemon accepted one finished span (loopback POST /spans, tracing spec TR22)."""
      if daemon_url is None:
          return False
      try:
          body = canonical_json(record)
          conn = http.client.HTTPConnection("127.0.0.1", _loopback_port(daemon_url), timeout=timeout)
          try:
              conn.request("POST", "/spans", body=body,
                           headers={"Content-Type": "application/json", "Content-Length": str(len(body))})
              resp = conn.getresponse()
              status = resp.status
              resp.read(MAX_BODY + 1)
          finally:
              conn.close()
      except Exception:
          return False
      return status == 200


  def _loopback_get(daemon_url, path, timeout):
      try:
          conn = http.client.HTTPConnection("127.0.0.1", _loopback_port(daemon_url), timeout=timeout)
          try:
              conn.request("GET", path)
              resp = conn.getresponse()
              return resp.status, resp.read(TRACE_CLIENT_MAX_BYTES + 1)
          finally:
              conn.close()
      except Exception:
          return None, None


  def _loopback_result(daemon_url, status, raw, check):
      if status is None:
          return None, "daemon not reachable at %s" % daemon_url
      if status in (401, 404):
          return None, "the daemon at %s has no trace support (http %d)" % (daemon_url, status)
      if status != 200:
          return None, "the daemon at %s answered http %d" % (daemon_url, status)
      obj = _json_loads_or_none(raw) if len(raw) <= TRACE_CLIENT_MAX_BYTES else None
      if not check(obj):
          return None, "the daemon at %s returned an unrecognized trace response" % daemon_url
      return obj, None


  def fetch_trace(daemon_url, trace_id):
      """(result, None) or (None, message) for loopback GET /trace?id=<trace_id> (tracing spec TR27)."""
      status, raw = _loopback_get(daemon_url, "/trace?id=" + trace_id, TRACE_QUERY_TIMEOUT)
      return _loopback_result(daemon_url, status, raw, lambda obj: valid_trace_result(obj, trace_id))


  def fetch_recent(daemon_url, n):
      """(result, None) or (None, message) for loopback GET /traces/recent?n=<n> (tracing spec TR28)."""
      status, raw = _loopback_get(daemon_url, "/traces/recent?n=%d" % n, TRACE_RECENT_TIMEOUT)
      return _loopback_result(daemon_url, status, raw, valid_recent_result)
  ```

  A daemon without this feature answers these unsigned `GET`s 401 (unknown route, F44): hence `(401, 404)` -> `no trace support`. `valid_trace_result(obj, trace_id)` is `True` iff `obj` is a dict with `schema == TRACE_SCHEMA`, `trace_id == trace_id`, `records` a list whose every item has `trace_record_error(...) is None`, `missing` a list of dicts with exactly `{"agent", "reason"}` (both `str`), and `truncated` a list of dicts with exactly `{"agent", "count"}` (`str`, non-bool int); it never raises. `valid_recent_result(obj)` is `True` iff `obj` is a dict with `schema == RECENT_SCHEMA`, `agent` matching `HOST_ID_RE`, and `traces` a list of dicts with exactly the keys of TR12's entries, where `trace_id` is valid, `start` an int or float, `dur_ms` and `spans` non-bool ints, `status` matches `TRACE_TOKEN_RE`, `kind` is in `TRACE_KINDS`, `name` matches `TRACE_NAME_RE`, and `delegated` is a list of `str`; it never raises.
- **TR15. `delegate_once(daemon_url, skill, task, host_id, images=None, trace=None)`.** `trace` is the TR7 field dict. The function becomes:

  ```python
  def _post_delegate(daemon_url, request):
      """(status, raw, None) of one loopback POST /delegate, or (None, None, <ExcType>)."""
      try:
          body = canonical_json(request)
          conn = http.client.HTTPConnection("127.0.0.1", _loopback_port(daemon_url),
                                            timeout=DELEGATE_CLIENT_TIMEOUT)
          try:
              conn.request("POST", "/delegate", body=body,
                           headers={"Content-Type": "application/json", "Content-Length": str(len(body))})
              resp = conn.getresponse()
              return resp.status, resp.read(MAX_BODY + 1), None
          finally:
              conn.close()
      except Exception as e:
          return None, None, type(e).__name__


  def delegate_once(daemon_url, skill, task, host_id, images=None, trace=None):
      """POST /delegate for one named peer -> (outcome, envelope, detail). Never raises (F68).

      images is the wire list (vision spec V10, V20); trace is the {"trace_id", "parent_span_id"}
      field (tracing spec TR15). A daemon that answers a traced body 400 {"error": "bad request"}
      predates tracing; the same request is sent once more without the field.
      """
      if daemon_url is None:
          return "daemon_error", None, "no daemon"
      request = {"skill": skill, "task": task, "host_id": host_id}
      if images is not None:
          request["images"] = images
      if trace is not None:
          request["trace"] = trace
      status, raw, error = _post_delegate(daemon_url, request)
      if trace is not None and status == 400 and _json_loads_or_none(raw) == {"error": "bad request"}:
          del request["trace"]
          status, raw, error = _post_delegate(daemon_url, request)
      if error is not None:
          return "daemon_error", None, error
      if status != 200:
          return "daemon_error", None, "http %d" % status
  ```

  followed by the existing response mapping unchanged (`obj = json.loads(raw)` ... `return obj["outcome"], obj["envelope"], obj["detail"]`, `:833-843`). With `trace=None` the request bytes and every result are identical to [VISION]'s. **[spec choice: the retry keeps a dev-checkout `qwen-agent` working against an installed daemon one release behind; a valid body never gets that 400 from a current daemon.]**

### 1.8 Rendering (Section 2's output formats)

- **TR16. `fmt_ms` and line formats.**

  ```python
  _ELLIPSIS = "…"
  _ARROW = "→"


  def fmt_ms(ms):
      """A duration for display: "<n>ms" under one second, else "<s.s>s"; None gives "-"."""
      if ms is None:
          return "-"
      if ms < 1000:
          return "%dms" % ms
      return "%.1fs" % (ms / 1000.0)


  def _dash(value):
      return "-" if value is None else str(value)


  def _span_line(r):
      """One tree line for one record (tracing spec TR16)."""
      a, d, s, who = r["attrs"], fmt_ms(r["dur_ms"]), r["status"], "@" + r["agent"]
      if r["kind"] == "turn":
          return "turn %s  %s  %s  rounds=%d  tools=%d  %s" % (r["name"], d, s, a["rounds"], a["tool_calls"], who)
      if r["kind"] == "model":
          return "model %s  %s  %s  %s%s%s tok  %s  %s" % (
              r["name"], d, s, "?" if a["prompt_tokens"] is None else a["prompt_tokens"], _ARROW,
              "?" if a["completion_tokens"] is None else a["completion_tokens"], a["finish_reason"] or "-", who)
      if r["kind"] == "tool":
          return "tool %s  %s  %s  %s  -> %s  %s" % (r["name"], a["key"] or "-", d, s, a["outcome"] or "-", who)
      if r["kind"] == "delegate":
          return "delegate %s -> %s  req=%s  http=%s  %s  %s  %s" % (
              a["skill"], a["target"], _dash(a["request_id"]), _dash(a["http"]), d, s, who)
      return "%s %s  req=%s  http=%d  %s  %s  %s" % (r["kind"], a["skill"], a["request_id"], a["http"], d, s, who)
  ```

  Each line is prefixed by two spaces per depth. Every line ends with `@<agent>`, the agent that recorded it, so the target of a run or agent line is that suffix. Example (the trace of R7's turn):

  ```text
  trace 4bf92f3577b3  2026-10-17 14:03:22  12.4s  agents: mac-local, ollama-168  spans: 8
  turn repl  12.4s  ok  rounds=2  tools=1  @mac-local
    model qwen38-6bit  1.9s  ok  812→64 tok  tool_calls  @mac-local
    tool delegate_to_skill  skill=researcher  8.6s  ok  -> ok, 912 characters  @mac-local
      delegate researcher -> ollama-168  req=9c1e0b7d2a4f6e83  http=200  8.5s  ok  @mac-local
        run researcher  req=9c1e0b7d2a4f6e83  http=200  8.3s  ok  @ollama-168
          agent researcher  req=9c1e0b7d2a4f6e83  http=200  8.3s  ok  @ollama-168
            model qwen3.5:9b  6.8s  ok  402→188 tok  stop  @ollama-168
    model qwen38-6bit  1.8s  ok  1290→140 tok  stop  @mac-local
  ```
- **TR17. `render_trace(result, localtime=time.localtime)`** returns the lines (no trailing newline) for a TR27 result:

  ```python
  def _placeholder_agent(orphan, missing):
      """Where a missing parent span lives: the orphan's own agent, except for a run span, whose
      parent is a delegate span on the calling agent: the one unanswered agent, else "?"."""
      if orphan["kind"] != "run":
          return orphan["agent"]
      agents = sorted(set(m["agent"] for m in missing))
      return agents[0] if len(agents) == 1 else "?"


  def render_trace(result, localtime=time.localtime):
      """The trace tree of a GET /trace?id= result, built from parent links (tracing spec TR17)."""
      records = merge_records(result["records"])
      by_id = dict((r["span_id"], r) for r in records)

      def order(r):
          return (r["start"], r["span_id"])

      roots, children, orphans = [], {}, {}
      for r in records:
          parent = r["parent_span_id"]
          if parent is None:
              roots.append(r)
          elif parent in by_id:
              children.setdefault(parent, []).append(r)
          else:
              orphans.setdefault(parent, []).append(r)
      roots.sort(key=order)
      for group in list(children.values()) + list(orphans.values()):
          group.sort(key=order)
      if roots:
          start, dur = roots[0]["start"], fmt_ms(roots[0]["dur_ms"])
      elif records:
          start, dur = min(r["start"] for r in records), "-"
      else:
          start, dur = None, "-"
      when = "-" if start is None else time.strftime("%Y-%m-%d %H:%M:%S", localtime(start))
      agents = sorted(set(r["agent"] for r in records))
      lines = ["trace %s  %s  %s  agents: %s  spans: %d"
               % (result["trace_id"][:12], when, dur, ", ".join(agents) or "none", len(records))]
      for m in sorted(result["missing"], key=lambda m: (m["agent"], m["reason"])):
          lines.append("! %s: %s" % (m["agent"], m["reason"]))
      for t in sorted(result["truncated"], key=lambda t: t["agent"]):
          lines.append("(truncated: %s returned the first %d records)" % (t["agent"], t["count"]))
      visited = set()

      def walk(top, depth):
          stack = [(top, depth)]
          while stack:
              node, level = stack.pop()
              if node["span_id"] in visited:
                  continue
              visited.add(node["span_id"])
              lines.append("  " * level + _span_line(node))
              for child in reversed(children.get(node["span_id"], [])):
                  stack.append((child, level + 1))

      for r in roots:
          walk(r, 0)
      for parent in sorted(orphans, key=lambda p: order(orphans[p][0])):
          lines.append("%s span %s on %s (not retrieved)"
                       % (_ELLIPSIS, parent, _placeholder_agent(orphans[parent][0], result["missing"])))
          for r in orphans[parent]:
              walk(r, 1)
      for r in sorted(records, key=order):
          if r["span_id"] not in visited:
              walk(r, 0)
      return lines
  ```

  Rules this fixes: the tree comes **only** from `parent_span_id`; timestamps order siblings (`(start, span_id)`) and never move a span between parents, so a child whose clock runs behind its parent's still nests under it. The header uses the earliest root; without a root it shows the earliest start and `-` for the duration. Warnings (`! <agent>: <reason>`) then truncation notes follow the header. Orphans (parent not retrieved: the peer was unreachable, the parent span has not finished, or its post was dropped) go under one placeholder per missing parent, after the rooted tree. A cycle (impossible from this code; only a forged store) still prints each record once, via the last loop. The walk is iterative, so no depth hits the recursion limit. **[spec choice: a run orphan's placeholder names the only unanswered agent, because the `/run` body carries no caller ID (the field is fixed to two keys); with zero or several unanswered agents it says `?`.]**
- **TR18. `render_recent(traces, localtime=time.localtime)`.**

  ```python
  _RECENT_FMT = "%-19s  %-32s  %8s  %-12s  %5s  %s"


  def render_recent(traces, localtime=time.localtime):
      """The trace --recent table: a header line, then one line per root span, newest first."""
      lines = [_RECENT_FMT % ("time", "trace id", "dur", "status", "spans", "delegated")]
      for t in traces:
          lines.append(_RECENT_FMT % (time.strftime("%Y-%m-%d %H:%M:%S", localtime(t["start"])), t["trace_id"],
                                      fmt_ms(t["dur_ms"]), t["status"], t["spans"],
                                      ", ".join(t["delegated"]) or "-"))
      return lines
  ```

  The ID column is the full 32-character ID **[spec choice: so it can be pasted into `trace <id>` or `/trace <id>`; the tree header's 12 characters are for reading]**. `spans` counts this agent's records only.

---

## 2. `bin/qwen-agentd`

### 2.1 Handler and dispatch

- **TR20.** In [VISION]'s V11 `_handle`, the two endpoint calls gain the path: `status, obj = fleet.loopback_endpoint(name, body, path)` and `status, raw = fleet.signed_endpoint(name, body, path)`. Nothing else in `_handle` changes: `/spans`, `/trace?id=` and `/traces/recent` get V11 steps 2-6 (non-loopback client 403; `Content-Length`; cap via `body_cap`, so a `/spans` body over 8192 bytes is a 413 before any read; `Host`/`Origin`/`Content-Type` 403); `GET /trace/<id>` is verified by `verify_request` over its full path and answered signed (F29j). The dispatchers become:

  ```python
      def signed_endpoint(self, name, body, path):
          """(status, body bytes) for a verified request to a signed endpoint."""
          if name == "health":
              return 200, fleet_lib.canonical_json(self.health_body())
          if name == "skills":
              return 200, fleet_lib.canonical_json({"host_id": self.host_id, "skills": self.skills_view()})
          if name == "trace":
              return self.handle_peer_trace(path)
          return self.handle_run(body)

      def loopback_endpoint(self, name, body, path):
          """(status, JSON-able object) for a loopback-only endpoint; sent unsigned."""
          if name == "peers":
              return 200, self.peers_view()
          if name == "spans":
              return self.handle_spans(body)
          if name == "trace_query":
              return self.handle_trace_query(path)
          if name == "recent":
              return self.handle_recent(path)
          return self.handle_delegate(body)
  ```

  Beside `_RUN_KEYS` and `_DELEGATE_KEYS` add:

  ```python
  _OPTIONAL_KEYS = frozenset(("images", "trace"))   # body keys /run and /delegate accept beyond their base set
  _TRACE_QUERY_RE = re.compile(r"/trace\?id=([0-9a-f]{32})")
  _RECENT_QUERY_RE = re.compile(r"/traces/recent\?n=([0-9]{1,3})")
  ```
- **TR21. Daemon state.** `Daemon.__init__` adds `self.trace_store = fleet_lib.TraceStore(fleet_lib.log_dir(host_id))` and `self._trace_warned = False`. New methods:

  ```python
      def record_span(self, trace_id, span_id, parent_span_id, kind, name, start, t0, status, attrs):
          """Store one finished daemon span; a failure never fails the request (tracing spec TR21)."""
          try:
              self.trace_store.append(fleet_lib.make_record(trace_id, span_id, parent_span_id, self.host_id,
                                                            kind, name, start, t0, status, attrs))
          except Exception as e:
              self._trace_write_failed(e)

      def _trace_write_failed(self, e):
          """One WARNING per process when the store cannot be written."""
          with self._warn_lock:
              if self._trace_warned:
                  return
              self._trace_warned = True
          LOG.warning("trace: cannot write %s: %s" % (self.trace_store.path, type(e).__name__))
  ```

  This WARNING is the only new log line of the feature. No existing log line changes (F53, F67, V21 text, and [VISION] VT20's regex, stay exact). **[spec choice: no trace ID in log lines; `request_id` already joins logs to spans.]** `spawn_run` and `_run_child` never touch the store, so [VISION] VT25(a)'s bare `Daemon.__new__` object keeps working.

### 2.2 `POST /spans` (loopback-only, unauthenticated)

- **TR22.**

  ```python
      def handle_spans(self, body):
          """(status, object) for loopback POST /spans: one finished span from a local qwen-agent (tracing spec TR22)."""
          obj = _json_or_none(body)
          reason = fleet_lib.trace_record_error(obj, posted=True)
          if reason is not None:
              return 400, {"error": "bad span: %s" % reason}
          try:
              self.trace_store.append(dict(obj, agent=self.host_id))
          except Exception as e:
              self._trace_write_failed(e)
          return 200, {"ok": True}
  ```

  | Request | Response |
  |---|---|
  | `POST /spans` from a non-loopback client | 403, empty |
  | no `Content-Length` | 411 |
  | `Content-Length > 8192` | 413, empty, body not read |
  | browser-style (`Host` not loopback, `Origin` present, `Content-Type` not JSON) | 403, empty |
  | body not a valid `/spans`-form record | 400 `{"error": "bad span: <field>"}`, `<field>` from `trace_record_error` (`record`, `keys`, `v`, ..., `attrs.<key>`) |
  | valid | 200 `{"ok": true}`, also when the store write failed |

  Body: exactly one record in the TR4 form **without** `agent`, kind `turn`, `model` or `tool`. The daemon sets `agent` to its own ID **[spec choice: a process cannot mislabel which agent recorded it]**; `delegate`, `run` and `agent` spans come only from the daemon itself. One span per request **[spec choice: spans are posted as they finish (Section 2's "in-flight turn shows finished spans only"), so a batch shape would have one element]**.

### 2.3 `POST /run`

- **TR23.** `handle_run` keeps [VISION] V16's behaviour, extends its shape check with the optional `trace` key, and records one run span and one agent span:

  ```python
      def handle_run(self, body):
          """(status, body bytes) for a verified POST /run; one run at a time per host (vision spec V16).

          Every request that passes the shape check is recorded as one run span (tracing spec TR23).
          """
          req = _json_or_none(body)
          if not (isinstance(req, dict) and set(req) - _OPTIONAL_KEYS == _RUN_KEYS
                  and all(isinstance(req[k], str) for k in _RUN_KEYS)
                  and req["task"].strip() != ""
                  and fleet_lib.REQUEST_ID_RE.fullmatch(req["request_id"])
                  and ("trace" not in req or fleet_lib.valid_trace_field(req["trace"]))):
              return 400, fleet_lib.canonical_json({"error": "bad request"})
          trace_id, parent = fleet_lib.trace_context(req.get("trace"))
          span_id = fleet_lib.new_span_id()
          start, t0 = round(time.time(), 3), time.monotonic()
          facts = {"http": 500, "images": 0, "image_bytes": 0, "envelope_status": None}
          try:
              code, raw = self._run_request(req, (trace_id, span_id), facts)
              facts["http"] = code
              return code, raw
          finally:
              skill = fleet_lib.trace_skill(req["skill"])
              self.record_span(trace_id, span_id, parent, "run", skill, start, t0,
                               fleet_lib.run_status(facts["http"], facts["envelope_status"]),
                               {"skill": skill, "request_id": req["request_id"], "http": facts["http"],
                                "images": facts["images"], "image_bytes": facts["image_bytes"]})

      def _run_request(self, req, trace, facts):
          """Vision spec V16 steps 2-5 -> (http code, body bytes); fills facts for the run span.

          trace is (trace_id, run span_id); the child gets (trace_id, agent span_id) (tracing spec TR23).
          """
          try:
              images = fleet_lib.request_images(req)
          except fleet_lib.ImageError as e:
              return e.status, fleet_lib.canonical_json({"error": e.reason})
          facts["images"] = len(images or [])
          facts["image_bytes"] = sum(len(data) for _media_type, data in images or [])
          if not self.run_lock.acquire(False):
              return 409, fleet_lib.canonical_json({"error": "busy"})
          skill, task, request_id = req["skill"], req["task"], req["request_id"]
          started = None
          code, status, raw = 500, "-", b""
          try:
              if not fleet_lib.serves_skill(self.skills_state, skill):
                  code, raw = 400, fleet_lib.canonical_json({"error": "skill not served: %s" % skill})
                  return code, raw
              started = time.monotonic()
              LOG.info("run start skill=%s request_id=%s task_chars=%d images=%d image_bytes=%d"
                       % (skill, request_id, len(task), facts["images"], facts["image_bytes"]))
              agent_span, agent_start = fleet_lib.new_span_id(), round(time.time(), 3)
              code, status, raw = self.spawn_run(skill, task, images, (trace[0], agent_span))
              facts["envelope_status"] = fleet_lib.trace_token(status)
              self.record_span(trace[0], agent_span, trace[1], "agent", fleet_lib.trace_skill(skill),
                               agent_start, started, "ok" if code == 200 and status == "ok" else "error",
                               {"skill": fleet_lib.trace_skill(skill), "request_id": request_id, "http": code,
                                "envelope_status": fleet_lib.trace_token(status)})
              return code, raw
          finally:
              self.run_lock.release()
              if started is not None:
                  LOG.info("run end skill=%s request_id=%s http=%d status=%s seconds=%.1f"
                           % (skill, request_id, code, status, time.monotonic() - started))
  ```

  - `set(req) - _OPTIONAL_KEYS == _RUN_KEYS` accepts exactly the base keys plus any subset of `images` and `trace`; for `images` it equals V16's `set(req) in (_RUN_KEYS, _RUN_KEYS | {"images"})`. A bad `trace` value is 400 `bad request` like every other shape failure (no run span, no log line).
  - Status codes and bodies are V16's, unchanged, in the same order. The `run start` / `run end` lines are byte-identical to [VISION]'s.
  - `spawn_run(self, skill, task, images=None, trace=None)` passes `trace` to both of its `self._run_child(argv)` calls, which become `self._run_child(argv, trace)`; `_run_child(self, argv, trace=None)` builds the env with `fleet_lib.build_child_env(os.environ, self.loopback_url, trace)`. So the child gets `QWEN_AGENT_TRACE_ID=<trace_id>` and `QWEN_AGENT_PARENT_SPAN=<agent span_id>` on every run, traced or not; the agent span (parent: the run span) is recorded after the child returns, with its ID drawn before the spawn. argv is unchanged (F50, V18, T46).

### 2.4 `POST /delegate` and forwarding

- **TR24.** `handle_delegate`:

  ```python
      def handle_delegate(self, body):
          """(status, object) for loopback POST /delegate, recorded as one delegate span.

          Never touches run_lock (F65, vision spec V14, tracing spec TR24).
          """
          req = _json_or_none(body)
          if not (isinstance(req, dict) and set(req) - _OPTIONAL_KEYS == _DELEGATE_KEYS
                  and all(isinstance(req[k], str) for k in _DELEGATE_KEYS)
                  and req["task"].strip() != "" and req["skill"] in fleet_lib.KNOWN_SKILLS
                  and fleet_lib.HOST_ID_RE.fullmatch(req["host_id"])
                  and ("trace" not in req or fleet_lib.valid_trace_field(req["trace"]))):
              return 400, {"error": "bad request"}
          try:
              fleet_lib.request_images(req)
          except fleet_lib.ImageError as e:
              return e.status, {"error": e.reason}
          skill, task, host_id = req["skill"], req["task"], req["host_id"]
          trace_id, parent = fleet_lib.trace_context(req.get("trace"))
          span_id = fleet_lib.new_span_id()
          start = round(time.time(), 3)
          started = time.monotonic()
          images = len(req.get("images") or [])
          record = self.table.record(host_id)
          if (host_id == self.host_id or not self.table.is_live(host_id) or record is None
                  or record["compatible"] is not True or not fleet_lib.serves_skill(record["skills"], skill)):
              LOG.info("delegate skill=%s host=%s request_id=- outcome=not_live seconds=%.1f"
                       % (skill, host_id, time.monotonic() - started))
              self.record_span(trace_id, span_id, parent, "delegate", skill, start, started, "not_live",
                               {"skill": skill, "target": host_id, "request_id": None, "http": None,
                                "images": images})
              return 200, {"outcome": "not_live", "envelope": None, "detail": ""}
          request_id = secrets.token_hex(8)
          outcome, envelope, detail, http_status = self.forward_run(record, skill, task, request_id,
                                                                    req.get("images"), (trace_id, span_id))
          LOG.info("delegate skill=%s host=%s request_id=%s outcome=%s seconds=%.1f"
                   % (skill, host_id, request_id, outcome, time.monotonic() - started))
          self.record_span(trace_id, span_id, parent, "delegate", skill, start, started, outcome,
                           {"skill": skill, "target": host_id, "request_id": request_id, "http": http_status,
                            "images": images})
          return 200, {"outcome": outcome, "envelope": envelope, "detail": detail}
  ```

  Image errors (400/413) record no span **[spec choice: a shape refusal is the caller's bug and already shows as the tool span's `ERROR:` outcome]**. The forwarded `/run` always carries `trace` with the delegate span as parent, whether or not the `/delegate` body had one.
- **TR25. `forward_run(self, record, skill, task, request_id, images=None, trace=None)`** now returns `(outcome, envelope, detail, http)`, where `http` is the peer's response status when a response was received, else `None`. Its body moves unchanged into `_forward_once`, which adds the `trace` field and the status:

  ```python
      def forward_run(self, record, skill, task, request_id, images=None, trace=None):
          """Signed POST /run to the peer -> (outcome, envelope, detail, http status or None) (F66, V15).

          trace=(trace_id, parent_span_id) adds the body's "trace" field (tracing spec TR25). A peer
          that answers it with a signed 400 {"error": "bad request"} predates tracing: the request
          is sent once more, with a new nonce, without the field.
          """
          result = self._forward_once(record, skill, task, request_id, images, trace)
          if trace is not None and result[3] == 400 and result[4] == {"error": "bad request"}:
              result = self._forward_once(record, skill, task, request_id, images, None)
          return result[:4]

      def _forward_once(self, record, skill, task, request_id, images, trace):
          """One signed POST /run -> (outcome, envelope, detail, http, parsed body of a peer_error)."""
          request = {"skill": skill, "task": task, "request_id": request_id}
          if images is not None:
              request["images"] = images
          if trace is not None:
              request["trace"] = {"trace_id": trace[0], "parent_span_id": trace[1]}
          body = fleet_lib.canonical_json(request)
          nonce = secrets.token_hex(16)
          headers = fleet_lib.sign_request(self.key, "POST", "/run", body, int(time.time()), nonce)
          headers["Content-Type"] = "application/json"
          headers["Content-Length"] = str(len(body))
          conn = http.client.HTTPConnection(record["address"], record["port"], timeout=fleet_lib.FORWARD_TIMEOUT)
          try:
              conn.request("POST", "/run", body=body, headers=headers)
              resp = conn.getresponse()
              status, resp_headers = resp.status, resp.headers
              raw = resp.read(fleet_lib.MAX_BODY + 1)
          except (socket.timeout, TimeoutError):
              return "timeout", None, "", None, None
          except (OSError, http.client.HTTPException) as e:
              return "unreachable", None, type(e).__name__, None, None
          finally:
              conn.close()
          if len(raw) > fleet_lib.MAX_BODY:
              return "bad_response", None, "", status, None
          if resp_headers.get("X-Fleet-Sig") is None and status in (413, 503):
              return ("busy", None, "", 503, None) if status == 503 else ("peer_error", None, "http 413", 413, None)
          if fleet_lib.verify_response(self.key, status, "POST", "/run", nonce, resp_headers, raw,
                                       int(time.time()), self.response_nonces) != "ok":
              return "bad_signature", None, "", status, None
          if status == 409:
              return "busy", None, "", 409, None
          if status == 504:
              return "timeout", None, "", 504, None
          if status == 200:
              envelope = _json_or_none(raw)
              if isinstance(envelope, dict) and envelope.get("schema") == fleet_lib.ONESHOT_SCHEMA:
                  return "ok", envelope, "", 200, None
              return "bad_response", None, "", 200, None
          return "peer_error", None, "http %d" % status, status, _json_or_none(raw)
  ```

  The F66/V15 outcome table is unchanged. Only a **verified** 400 with exactly that body triggers the retry. **[spec choice: `PROTOCOL` stays 1 and [FLEET]/[VISION] daemons reject any unknown `/run` key, so during the self-update window (up to `UPDATE_INTERVAL + UPDATE_JITTER`, about 17 min) a traced forward to a peer one release behind would otherwise fail every delegation.]**

### 2.5 Query endpoints

- **TR26. `GET /trace/<id>` (signed, peer-to-peer).**

  ```python
      def handle_peer_trace(self, path):
          """(status, body bytes) for a verified GET /trace/<id>: this agent's records only (tracing spec TR26)."""
          trace_id = path[len("/trace/"):]
          if not fleet_lib.valid_trace_id(trace_id):
              return 400, fleet_lib.canonical_json({"error": "bad trace id"})
          try:
              records, truncated = self.trace_store.query(trace_id)
          except OSError as e:
              return 500, fleet_lib.canonical_json({"error": "trace store unreadable: %s" % type(e).__name__})
          return 200, fleet_lib.canonical_json({"agent": self.host_id, "trace_id": trace_id,
                                                "records": records, "truncated": truncated})
  ```

  | Request | Response |
  |---|---|
  | unsigned, bad signature, wrong key, skewed or replayed | 401, empty, unsigned (F44, F29j) |
  | signed, `<id>` not `valid_trace_id` (including any `?` suffix) | signed 400 `{"error": "bad trace id"}` |
  | signed, store unreadable | signed 500 `{"error": "trace store unreadable: <ExcType>"}` |
  | signed, valid | signed 200 `{"agent": <self>, "trace_id": <id>, "records": [...], "truncated": <bool>}`, at most 2000 records and at most `TRACE_QUERY_MAX_BYTES` of records, so the body stays under `MAX_BODY` |

  The response never includes another agent's records. No log line.
- **TR27. `GET /trace?id=<id>` (loopback-only, fan-out).**

  ```python
      def handle_trace_query(self, path):
          """(status, object) for loopback GET /trace?id=<id> (tracing spec TR27)."""
          match = _TRACE_QUERY_RE.fullmatch(path)
          if match is None or not fleet_lib.valid_trace_id(match.group(1)):
              return 400, {"error": "bad trace id"}
          try:
              return 200, self.trace_query(match.group(1))
          except OSError as e:
              return 500, {"error": "trace store unreadable: %s" % type(e).__name__}

      def trace_call(self, address, port, path):
          """(status, raw, None) of a verified signed GET, or (None, None, reason) (tracing spec TR27)."""
          nonce = secrets.token_hex(16)
          headers = fleet_lib.sign_request(self.key, "GET", path, b"", int(time.time()), nonce)
          try:
              conn = http.client.HTTPConnection(address, port, timeout=fleet_lib.PEER_HTTP_TIMEOUT)
              try:
                  conn.request("GET", path, headers=headers)
                  resp = conn.getresponse()
                  status, resp_headers = resp.status, resp.headers
                  raw = resp.read(fleet_lib.MAX_BODY + 1)
              finally:
                  conn.close()
          except (socket.timeout, TimeoutError):
              return None, None, "unreachable (timeout)"
          except ConnectionRefusedError:
              return None, None, "unreachable (connection refused)"
          except Exception as e:
              return None, None, "unreachable (%s)" % type(e).__name__
          if len(raw) > fleet_lib.MAX_BODY:
              return None, None, "bad response (too large)"
          if fleet_lib.verify_response(self.key, status, "GET", path, nonce, resp_headers, raw,
                                       int(time.time()), self.response_nonces) != "ok":
              return None, None, "bad signature (http %d)" % status
          return status, raw, None

      def _fetch_peer_traces(self, targets, trace_id):
          """{host_id: (status, raw, reason)} for [(host_id, address, port)], all at once, within TRACE_FANOUT_DEADLINE."""
          results, lock, path = {}, threading.Lock(), "/trace/" + trace_id

          def work(host_id, address, port):
              result = self.trace_call(address, port, path)
              with lock:
                  results[host_id] = result

          threads = [self._thread("trace-fetch", lambda h=h, a=a, p=p: work(h, a, p)) for h, a, p in targets]
          deadline = time.monotonic() + fleet_lib.TRACE_FANOUT_DEADLINE
          for thread in threads:
              thread.join(max(0.0, deadline - time.monotonic()))
          with lock:
              out = dict(results)
          for host_id, _address, _port in targets:
              out.setdefault(host_id, (None, None, "unreachable (timeout)"))
          return out

      def _merge_round(self, trace_id, targets, merged, missing, truncated):
          results = self._fetch_peer_traces(targets, trace_id)
          for host_id in sorted(results):
              status, raw, reason = results[host_id]
              records, why, count = fleet_lib.peer_trace_result(trace_id, host_id, status, raw, reason)
              if why is not None:
                  missing.append({"agent": host_id, "reason": why})
                  continue
              merged.extend(records)
              if count is not None:
                  truncated.append({"agent": host_id, "count": count})

      def trace_query(self, trace_id):
          """This agent's records of a trace merged with every reachable peer's (tracing spec TR27)."""
          records, cut = self.trace_store.query(trace_id)
          merged, missing, truncated = list(records), [], []
          if cut:
              truncated.append({"agent": self.host_id, "count": len(records)})
          round1 = [(p["host_id"], p["address"], p["port"]) for p in self.table.live_peers()
                    if p["host_id"] != self.host_id]
          self._merge_round(trace_id, round1, merged, missing, truncated)
          asked = set([self.host_id] + [h for h, _a, _p in round1])
          round2 = []
          for target in sorted(set(r["attrs"]["target"] for r in merged if r["kind"] == "delegate") - asked):
              host = self.registry["hosts"].get(target)
              if host is None:
                  missing.append({"agent": target, "reason": "not in the registry"})
              else:
                  round2.append((target, host["address"], host["port"]))
          self._merge_round(trace_id, round2, merged, missing, truncated)
          return {"schema": fleet_lib.TRACE_SCHEMA, "trace_id": trace_id,
                  "records": fleet_lib.merge_records(merged),
                  "missing": sorted(missing, key=lambda m: m["agent"]),
                  "truncated": sorted(truncated, key=lambda t: t["agent"])}
  ```

  - Round 1 asks every live peer (`live_peers()`, compatible or not) in parallel. Round 2 asks, at its **registry** address, every agent that a retrieved delegate span targeted and round 1 did not ask. **[spec choice: a stopped peer leaves the live table after `LIVE_WINDOW` (90 s); without round 2 it would vanish from the tree silently instead of showing `! <agent>: unreachable (...)`. Exactly one extra round bounds the query at about 12 s.]**
  - `missing` reasons, exactly: `unreachable (timeout)`, `unreachable (connection refused)`, `unreachable (<ExcType>)`, `bad response (too large)`, `bad signature (http <n>)`, `no trace support (http 404)`, `error (http <n>)`, `bad response`, `not in the registry`.
  - The response is 200 even when every peer failed, and even with no records: the client decides (TR29, TR47). Its size is at most about 1 MiB per agent asked. Unsigned (loopback, F44). No log line.
- **TR28. `GET /traces/recent[?n=<N>]` (loopback-only).**

  ```python
      def handle_recent(self, path):
          """(status, object) for loopback GET /traces/recent[?n=N] (tracing spec TR28)."""
          if path == "/traces/recent":
              n = fleet_lib.TRACE_RECENT_DEFAULT
          else:
              match = _RECENT_QUERY_RE.fullmatch(path)
              n = int(match.group(1)) if match is not None else 0
              if not 1 <= n <= fleet_lib.TRACE_RECENT_MAX:
                  return 400, {"error": "bad n"}
          try:
              traces = self.trace_store.recent(n)
          except OSError as e:
              return 500, {"error": "trace store unreadable: %s" % type(e).__name__}
          return 200, {"schema": fleet_lib.RECENT_SCHEMA, "agent": self.host_id, "traces": traces}
  ```

  Local records only, no fan-out.

### 2.6 CLI

- **TR29. `qwen-agentd trace`.** The module docstring's usage block (`:4-10`) gains two lines after the `status` line:

  ```text
    qwen-agentd trace [--agent-id ID | --port N] [--json] TRACE_ID
    qwen-agentd trace [--agent-id ID | --port N] --recent [N]
  ```

  `_build_parser` adds, directly after the `status` subparser:

  ```python
      p = sub.add_parser("trace", help="print one trace as a tree, or list this agent's recent traces")
      _add_agent_id(p)
      p.add_argument("--port", type=int, default=None)
      p.add_argument("--json", dest="as_json", action="store_true", default=False)
      p.add_argument("--recent", nargs="?", const=str(fleet_lib.TRACE_RECENT_DEFAULT), default=None, metavar="N")
      p.add_argument("trace_id", nargs="?", default=None, metavar="TRACE_ID")
      p.set_defaults(func=cmd_trace)
  ```

  and, after `cmd_status`:

  ```python
  _RECENT_N_RE = re.compile(r"[0-9]{1,3}")


  def cmd_trace(args):
      """Print one trace as a tree (or as JSON), or this agent's recent traces (tracing spec TR29)."""
      explicit = None
      if args.agent_id is not None:
          explicit, message = fleet_lib.resolve_agent(args.agent_id)
          if message is not None:
              _err(message)
              return 2
      if args.trace_id is not None and args.recent is not None:
          _err("qwen-agentd: trace takes a TRACE_ID or --recent, not both")
          return 2
      if args.trace_id is None and args.recent is None:
          _err("qwen-agentd: trace needs a TRACE_ID or --recent [N]")
          return 2
      if args.recent is not None:
          if args.as_json:
              _err("qwen-agentd: --json applies to trace TRACE_ID only")
              return 2
          if not (_RECENT_N_RE.fullmatch(args.recent) and 1 <= int(args.recent) <= fleet_lib.TRACE_RECENT_MAX):
              _err("qwen-agentd: invalid --recent %s (1 to %d)"
                   % (fleet_lib.shown_value(args.recent), fleet_lib.TRACE_RECENT_MAX))
              return 2
      elif not fleet_lib.valid_trace_id(args.trace_id):
          _err("qwen-agentd: invalid trace id %s (32 lowercase hex characters)" % fleet_lib.shown_value(args.trace_id))
          return 2
      port = args.port
      if port is not None and not 1 <= port <= 65535:
          _err("qwen-agentd: invalid --port %d" % port)
          return 2
      if port is None:
          port, message = _status_port(explicit)
          if message is not None:
              _err(message)
              return 2
      url = "http://127.0.0.1:%d" % port
      if args.recent is not None:
          result, error = fleet_lib.fetch_recent(url, int(args.recent))
          if error is not None:
              _err("qwen-agentd: " + error)
              return 1
          if not result["traces"]:
              _err("qwen-agentd: no traces recorded on %s" % result["agent"])
              return 1
          sys.stdout.write("\n".join(fleet_lib.render_recent(result["traces"])) + "\n")
          return 0
      result, error = fleet_lib.fetch_trace(url, args.trace_id)
      if error is not None:
          _err("qwen-agentd: " + error)
          return 1
      if args.as_json:
          sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
      else:
          sys.stdout.write("\n".join(fleet_lib.render_trace(result)) + "\n")
      if not result["records"]:
          _err("qwen-agentd: no records for trace %s" % args.trace_id)
          return 1
      return 0
  ```

  | Situation | Output | Exit |
  |---|---|---|
  | tree (complete or partial: unreachable peers, old peers, orphans, truncation) | TR17 lines on stdout | 0 |
  | `--json` | the TR27 result (`schema`, `trace_id`, `records`, `missing`, `truncated`), `indent=2`, sorted keys, ASCII | 0 |
  | no record anywhere | the tree header and warnings on stdout (or the JSON), then `qwen-agentd: no records for trace <id>` on stderr | 1 |
  | `--recent [N]` | TR18 table | 0 |
  | `--recent`, empty store | `qwen-agentd: no traces recorded on <agent>` | 1 |
  | no local daemon | `qwen-agentd: daemon not reachable at http://127.0.0.1:<port>` | 1 |
  | daemon without tracing | `qwen-agentd: the daemon at <url> has no trace support (http 401)` | 1 |
  | other daemon answer | `qwen-agentd: the daemon at <url> answered http <n>` / `... returned an unrecognized trace response` | 1 |
  | malformed ID, N, flag combination, port, `--agent-id`, or no port resolvable ([MULTI] M30 messages) | one stderr line above | 2 |
  | non-integer `--port`, unknown flag | argparse's message | 2 |

  An explicit `--port` wins over `--agent-id`, as in `status` (M30). `--recent` with no value is 10. **[spec choice: `--json` with `--recent` is refused rather than given a second JSON shape nobody asked for; an empty `--recent` exits 1, matching "no records -> exit 1".]**

---

## 3. `bin/qwen-agent`

No import statement is added or removed (C8, M14): IDs, records, HTTP and rendering all come from `FLEET`.

- **TR40. Constants and state.** Directly after `DECISION_LOG_NAME` (`:219`):

  ```python
  TRACE_RING_SIZE = 20       # REPL turns that /trace N reaches back to (tracing spec TR40)
  TRACE_TURN_BUDGET = 2.0    # s, all POST /spans of one turn together; never scaled (tracing spec TR46)
  # Each equals its fleet_lib namesake (TRACE_ENV_ID, TRACE_ENV_PARENT); bin/qwen-agent keeps its own
  # copy because it must work without fleet_lib (fleet spec F70). Test TRT20 checks that they agree.
  TRACE_ENV_KEYS = ("QWEN_AGENT_TRACE_ID", "QWEN_AGENT_PARENT_SPAN")
  TRACE_USAGE = "usage: /trace [N | TRACE_ID]  (N from 1 to 20 counts back from the last turn)"
  ```

  Directly after `FLEET_DAEMON_URL = None` (`:639`):

  ```python
  TURN_TRACE = None   # the turn being traced (a dict, TR41), or None
  TRACE_RING = []     # trace IDs of this REPL session's turns, oldest first, at most TRACE_RING_SIZE
  ```
- **TR41. When tracing is on, and the turn state.** A new section `# Tracing (docs/superpowers/specs/2026-10-17-fleet-tracing-design.md)` directly before `# Section 11.1: wire contract` (`:1840`):

  ```python
  def _trace_begin(name, inherit):
      """Start tracing one turn and return its trace ID, or None (tracing off). Never raises.

      Tracing is on only with fleet_lib loaded and a usable QWEN_AGENT_DAEMON_URL. inherit=True
      (one-shot only) takes the trace and parent from QWEN_AGENT_TRACE_ID / QWEN_AGENT_PARENT_SPAN.
      """
      global TURN_TRACE
      TURN_TRACE = None
      if FLEET is None or FLEET_DAEMON_URL is None:
          return None
      try:
          context = FLEET.trace_env_context(os.environ) if inherit else None
          trace_id, parent = context if context is not None else (FLEET.new_trace_id(), None)
          # Inherited: no turn span; the model and tool spans hang off the inherited parent (TR42).
          TURN_TRACE = {"trace_id": trace_id, "span_id": parent if context is not None else FLEET.new_span_id(),
                        "parent": None, "post_turn": context is None, "name": name,
                        "start": round(time.time(), 3), "t0": time.monotonic(), "budget": TRACE_TURN_BUDGET,
                        "dead": False, "tool_span": None, "model_calls": 0}
      except Exception:
          TURN_TRACE = None
          return None
      return trace_id


  def _trace_end(outcome):
      """Post the turn span last (only for a turn that inherited no trace), then stop tracing. Never raises."""
      global TURN_TRACE
      t = TURN_TRACE
      try:
          if t is not None and t["post_turn"]:
              _trace_post("turn", t["span_id"], t["parent"], t["name"], t["start"], t["t0"],
                          FLEET.trace_token(outcome["status"]) or "error",
                          {"rounds": int(outcome["rounds"]), "tool_calls": len(outcome["tool_calls"])})
      except Exception:
          pass
      TURN_TRACE = None


  def _trace_post(kind, span_id, parent, name, start, t0, status, attrs):
      """POST one finished span to the local daemon within the turn's budget; drop it on any failure."""
      t = TURN_TRACE
      if t is None or t["dead"]:
          return
      try:
          record = FLEET.make_record(t["trace_id"], span_id, parent, None, kind, name, start, t0, status, attrs)
          left = t["budget"]
          if left <= 0:
              t["dead"] = True
              return
          began = time.monotonic()
          ok = FLEET.post_span(FLEET_DAEMON_URL, record, min(FLEET.TRACE_POST_TIMEOUT, left))
          t["budget"] = left - (time.monotonic() - began)
          if not ok:
              t["dead"] = True
      except (Exception, KeyboardInterrupt):
          t["dead"] = True


  def _trace_context():
      """(trace_id, current tool span ID) while a traced tool call runs, else None."""
      t = TURN_TRACE
      if t is None or t["tool_span"] is None:
          return None
      return t["trace_id"], t["tool_span"]


  def _trace_child_env(env):
      """Point a local --skill child at the current tool span; never pass on an inherited trace."""
      for key in TRACE_ENV_KEYS:
          env.pop(key, None)
      context = _trace_context()
      if context is not None:
          env[TRACE_ENV_KEYS[0]], env[TRACE_ENV_KEYS[1]] = context
  ```

  A daemon that is not running costs one refused connection per turn (the first post marks the turn dead). **[spec choice: `KeyboardInterrupt` during a post is absorbed and ends tracing for the turn; it can only arrive within the 2 s budget, and the next model call stays interruptible.]**
- **TR42. Turn spans.** `repl` (`:3629-3667`): directly after `messages.append({"role": "user", "content": line})`:

  ```python
          trace_id = _trace_begin("repl", False)
          if trace_id is not None:
              TRACE_RING.append(trace_id)
              del TRACE_RING[:-TRACE_RING_SIZE]
  ```

  and directly after the `elif outcome["status"] == "context_budget": ...` notice block (after the answer and every `[stopped: ...]` notice are printed, before the memory checkpoint), `_trace_end(outcome)`. The checkpoint therefore runs untraced.

  `oneshot` (`:3732-3733`): `_trace_begin(args_ns.skill or "oneshot", True)` directly before `outcome = run_turn(messages, args_ns, 1)`, and `_trace_end(outcome)` directly after it (before the `[stopped: ...]` notices and the envelope). The REPL ignores the environment; a one-shot honours `QWEN_AGENT_TRACE_ID` + `QWEN_AGENT_PARENT_SPAN` only when both are valid, else it starts a new root trace silently **[spec choice: a stray or malformed variable must not break a run, and a REPL is never a child]**. A one-shot that inherits a valid pair posts **no** turn span: `TURN_TRACE["span_id"]` is the inherited parent, so its model and tool spans hang directly off it (a `/run` child's off the daemon's agent span, a local child's off the caller's tool span); budget, model and tool spans, and propagation to its own delegations are unchanged. The envelope is unchanged (no trace ID) **[spec choice: one-shot traces are found with `trace --recent`; the envelope schema has external consumers]**.
- **TR43. Model spans.** `chat_completion` (`:1851-1877`): the request body and headers are built exactly as today; the last two lines become:

  ```python
      span = _trace_model_begin()
      try:
          with urllib.request.urlopen(req, timeout=args_ns.request_timeout) as resp:
              result = json.loads(resp.read().decode("utf-8"))
      except BaseException as e:
          _trace_model_end(span, args_ns, "tools" in body, None, e)
          raise
      _trace_model_end(span, args_ns, "tools" in body, result, None)
      return result
  ```

  with, in the TR41 section:

  ```python
  def _trace_model_begin():
      """(span_id, start, t0, call number) for one traced chat call, or None. Never raises."""
      t = TURN_TRACE
      if t is None:
          return None
      try:
          t["model_calls"] += 1
          return FLEET.new_span_id(), round(time.time(), 3), time.monotonic(), t["model_calls"]
      except Exception:
          return None


  def _trace_model_end(span, args_ns, tools, result, error):
      """Post one model span: timing, token usage and finish_reason, never the messages or the answer."""
      if span is None or TURN_TRACE is None:
          return
      try:
          span_id, start, t0, call = span
          status, http = "ok", None
          if isinstance(error, urllib.error.HTTPError):
              status, http = "http_error", FLEET.trace_count(error.code)
          elif isinstance(error, KeyboardInterrupt):
              status = "interrupted"
          elif isinstance(error, (urllib.error.URLError, OSError)):
              status = "network_error"
          elif isinstance(error, ValueError):
              status = "malformed_response"
          elif error is not None:
              status = "error"
          usage = result.get("usage") if isinstance(result, dict) else None
          usage = usage if isinstance(usage, dict) else {}
          finish = None
          try:
              finish = result["choices"][0].get("finish_reason")
          except Exception:
              pass
          _trace_post("model", span_id, TURN_TRACE["span_id"], FLEET.trace_name(getattr(args_ns, "model", None)),
                      start, t0, status,
                      {"call": call, "tools": bool(tools), "prompt_tokens": FLEET.trace_count(usage.get("prompt_tokens")),
                       "completion_tokens": FLEET.trace_count(usage.get("completion_tokens")),
                       "finish_reason": FLEET.trace_token(finish), "http": http})
      except Exception:
          pass
  ```

  `HTTPError.read()` is never called here (run_turn reads the body afterwards). Traced calls: every `run_turn` round and the `_forced_summary` call (`tools` false). Calls with no turn in progress (the checkpoint, tests calling `chat_completion` directly, T33) post nothing and behave exactly as today. Tests that replace `chat_completion` with a fake simply record no model spans.
- **TR44. Tool spans.** In `run_turn`'s dispatch loop (`:3548-3549`), `record = dispatch(tc, i, n, args_ns, history)` becomes:

  ```python
              tool_span = _trace_tool_begin()
              record = dispatch(tc, i, n, args_ns, history)
              _trace_tool_end(tool_span, record, round_num)
  ```

  with:

  ```python
  def _trace_tool_begin():
      """(span_id, start, t0) for one traced tool call, made current for delegation, or None."""
      t = TURN_TRACE
      if t is None:
          return None
      try:
          span = (FLEET.new_span_id(), round(time.time(), 3), time.monotonic())
          t["tool_span"] = span[0]
          return span
      except Exception:
          return None


  def _trace_key(name, args):
      """A tool span's key: the decision-log key (_call_key), except that delegate_to_skill
      records only its skill and image count, never its task."""
      if not isinstance(args, dict):
          return ""
      try:
          if name == "delegate_to_skill":
              key = "skill=%s" % (args.get("skill", ""),)
              if isinstance(args.get("images"), list):
                  key += " images=%d" % len(args["images"])
              return _trace_clip(key)
          return _call_key(name, args)
      except Exception:
          return ""


  def _trace_tool_end(span, record, round_num):
      """Post one tool span from dispatch's record. Never raises."""
      t = TURN_TRACE
      if span is None or t is None:
          return
      try:
          t["tool_span"] = None
          name = record.get("tool")
          decision = record["outcome"]
          error = record["result"].startswith("ERROR:")
          try:
              outcome = _auto_trace_outcome(str(name), record["result"])
          except Exception:
              outcome = ""
          _trace_post("tool", span[0], t["span_id"],
                      name if isinstance(name, str) and name in TOOL_BY_NAME else "unknown",
                      span[1], span[2], ("error" if error else "ok") if decision == "approved" else decision,
                      {"round": round_num, "decision": decision, "key": _trace_key(name, record.get("arguments")),
                       "outcome": outcome, "error": error})
      except Exception:
          pass
  ```

  `key` is at most 203 characters (`_trace_clip`), `outcome` at most 163 (`_auto_trace_outcome`), both free of control characters. The `[auto]`, `[duplicate]` and `[circuit-open]` lines, the records, and `tool_decisions.log` are unchanged. **[spec choice: the key is the decision log's (`_call_key`, raw path) so blocked and denied calls get one too; for `delegate_to_skill` the `[auto]` key holds task text, which a trace never records.]**
- **TR45. Propagation.** `exec_delegate_to_skill` (`:1315-1316`): directly after `child_env["QWEN_AGENT_PREFLIGHT_DONE"] = "1"`, add `_trace_child_env(child_env)`. The local child's argv is unchanged (T35, T39, VT18). `_delegate_remote` ([VISION] V31): directly before `def attempt(host_id):` add

  ```python
      context = _trace_context()
      trace = None if context is None else {"trace_id": context[0], "parent_span_id": context[1]}
  ```

  and the call becomes `FLEET.delegate_once(FLEET_DAEMON_URL, skill, task, host_id, images, trace)`. With no turn traced (every existing test that calls `exec_delegate_to_skill` directly) `trace` is `None` and the `/delegate` bodies are byte-identical to today's (T36, VT17).
- **TR46. Budget.** Every post of one turn shares `TRACE_TURN_BUDGET = 2.0` s: each post's timeout is `min(TRACE_POST_TIMEOUT, budget left)`, the elapsed time is subtracted, and the first failed post (refused, timed out, non-200) or an exhausted budget stops all posting for the rest of that turn. The next REPL turn starts with a fresh budget. Spans are posted when they finish: model and tool spans during the turn, the turn span last, so a query during a turn shows the finished spans, with the turn's children under a TR17 placeholder until it ends. A dropped span is never retried.
- **TR47. `/trace`.** `HELP_TEXT` gains, directly after the `/remember` line:

  ```text
    /trace      Show a turn's trace: /trace (last turn), /trace N (N turns back), /trace <id>
  ```

  `handle_slash_command` gains, directly before the final `else`:

  ```python
      elif cmd == "/trace" or cmd.startswith("/trace "):
          for out_line in slash_trace(cmd[len("/trace"):]):
              print(out_line)
  ```

  and, directly after `slash_resume`:

  ```python
  def slash_trace(raw):
      """/trace, /trace N, /trace <id> -- one turn's trace tree from the local qwen-agentd. Returns lines."""
      if FLEET is None:
          return ["tracing is off: fleet_lib.py is not available"]
      if FLEET_DAEMON_URL is None:
          return ["tracing is off: QWEN_AGENT_DAEMON_URL is not usable"]
      arg = raw.strip()
      if arg == "" or re.fullmatch(r"[0-9]{1,2}", arg):
          n = int(arg) if arg else 1
          if not 1 <= n <= TRACE_RING_SIZE:
              return [TRACE_USAGE]
          if not TRACE_RING:
              return ["no turns in this session yet"]
          if n > len(TRACE_RING):
              return ["only %d turn%s in this session" % (len(TRACE_RING), "" if len(TRACE_RING) == 1 else "s")]
          trace_id = TRACE_RING[-n]
      elif FLEET.valid_trace_id(arg):
          trace_id = arg
      else:
          return [TRACE_USAGE]
      result, error = FLEET.fetch_trace(FLEET_DAEMON_URL, trace_id)
      if error is not None:
          return [error]
      lines = FLEET.render_trace(result)
      if not result["records"]:
          lines.append("no records for trace %s" % trace_id)
      return lines
  ```

  `/trace` is `/trace 1`, the last turn. **[spec choice: N above 20 is a usage error, so "only <k> turns" is never wrong about a session longer than the ring; `turn` is singular for k = 1.]** Every output line goes to stdout, like the other slash commands. The query can take up to `TRACE_QUERY_TIMEOUT` (20 s) when peers time out.
- **TR48. Output invariance.** With tracing on, off, or failing, `run_turn`'s results, every byte the REPL prints for a turn, the one-shot envelope and exit code, the child argv, and the `/delegate` responses are identical. Every trace helper catches its own exceptions. Only `/help` gains one line.
- **TR49. Imports.** No import statement is added to `bin/qwen-agent` (C8, M14 still pass); `fleet_lib` adds only `import secrets`; `bin/qwen-agentd` adds none.

---

## 4. Data shapes and what is never recorded

### 4.1 Summary

| Where | Shape |
|---|---|
| record (stored, `trace.jsonl` line) | TR4, `canonical_json` + `\n` |
| `POST /spans` body | TR4 without `agent`; kind `turn`/`model`/`tool`; at most 8192 bytes |
| `trace` body field (`/delegate`, `/run`) | `{"trace_id": <32 hex>, "parent_span_id": <16 hex>}` |
| child env | `QWEN_AGENT_TRACE_ID=<32 hex>`, `QWEN_AGENT_PARENT_SPAN=<16 hex>` |
| `GET /trace/<id>` response | `{"agent", "trace_id", "records", "truncated": bool}` |
| `GET /trace?id=` response | `{"schema": "qwen-agentd.trace.v1", "trace_id", "records", "missing": [{"agent", "reason"}], "truncated": [{"agent", "count"}]}` |
| `GET /traces/recent` response | `{"schema": "qwen-agentd.recent.v1", "agent", "traces": [{"trace_id", "start", "dur_ms", "status", "kind", "name", "spans", "delegated": ["<skill>@<agent>"]}]}` |
| files | `A/logs/trace.jsonl`, `.1`, `.2`, `.3`; mode 0600 in the 0700 `A/logs` |

### 4.2 Endpoints

| Method, path | Auth class | Cap | Statuses |
|---|---|---|---|
| `POST /spans` | loopback-only | 8192 | 200, 400, 403, 411, 413 |
| `GET /trace/<id>` | signed | -- | 200, 400, 401, 500 (signed except 401) |
| `GET /trace?id=<id>` | loopback-only | -- | 200, 400, 403, 500 |
| `GET /traces/recent[?n=N]` | loopback-only | -- | 200, 400, 403, 500 |

No new port, socket, thread type (beyond short-lived `trace-fetch` threads) or firewall rule.

### 4.3 Never recorded

- **TR50.** No trace record, `/spans` body, query response or CLI/REPL trace output contains: the user's prompt or REPL input; any system prompt; a delegation's task text; any message, model answer or reasoning; any tool result beyond `_auto_trace_outcome`'s one line; any tool argument other than the TR44 key (no `write_file` content, no `delegate_to_skill` task, no image path or byte); image bytes or base64; the fleet token, key or join string; environment variables; HTTP bodies. The structure enforces it: `trace_record_error` accepts exactly the `_TRACE_ATTRS` keys, and only `tool.key` and `tool.outcome` are free text (TRT4); the daemon rejects any other key (TRT46); a skill from a `/run` body becomes `unknown` unless it is a known skill (TR6). Sentinel greps prove it (TRT27, TRT47).

---

## 5. Code change map

| File | Location | Change |
|---|---|---|
| `fleet_lib.py` | imports | `import secrets` (TR2) |
| | after `LOG_BACKUPS` | TR1 constants |
| | `build_child_env` `:539-549` | `trace=None` (TR8) |
| | `_ROUTES`, `http_route` `:688-704` | TR9 |
| | [VISION] `body_cap` | `/spans` cap (TR9) |
| | `delegate_once` `:813-843` | `_post_delegate`, `trace=None`, retry (TR15) |
| | end of file | TR3-TR8, TR10-TR14, TR16-TR18 |
| `bin/qwen-agentd` | docstring `:4-10` | TR29 usage |
| | beside `_RUN_KEYS` | `_OPTIONAL_KEYS`, `_TRACE_QUERY_RE`, `_RECENT_QUERY_RE` (TR20) |
| | `_handle` (V11) | path to both dispatchers (TR20) |
| | `Daemon.__init__` | `trace_store`, `_trace_warned` (TR21) |
| | `signed_endpoint`, `loopback_endpoint` `:596-608` | TR20 |
| | new methods | `record_span`, `_trace_write_failed`, `handle_spans`, `handle_peer_trace`, `handle_trace_query`, `handle_recent`, `trace_call`, `_fetch_peer_traces`, `_merge_round`, `trace_query`, `_run_request`, `_forward_once` |
| | `handle_run`, `spawn_run`, `_run_child` | TR23 |
| | `handle_delegate`, `forward_run` | TR24, TR25 |
| | after `cmd_status`; `_build_parser` | `cmd_trace`, `_RECENT_N_RE`, the `trace` subparser (TR29) |
| `bin/qwen-agent` | after `:219`; after `:639` | TR40 |
| | `exec_delegate_to_skill` `:1315`; `_delegate_remote` | TR45 |
| | before `:1840` | TR41, TR43, TR44 helpers |
| | `chat_completion` `:1876-1877` | TR43 |
| | `HELP_TEXT`; after `slash_resume`; `handle_slash_command` | TR47 |
| | `run_turn` `:3548-3549` | TR44 |
| | `repl` `:3631`, after `:3654`; `oneshot` `:3733` | TR42 |

---

## 6. Tests

### 6.1 Rules

[FLEET] 11.1, [MULTI] 5.1 and [VISION] 7.1 hold. In addition:

- Every new test sets `HOME` to a temp directory (`monkeypatch.setenv` in-process, `fleet_testutil.clean_env` for subprocesses, which also drops any inherited `QWEN_AGENT_TRACE_*`). In-process harness tests set `qa.FLEET = qa._load_fleet_lib()` and `qa.FLEET_DAEMON_URL` to a test daemon or a closed port, replace `qa.setup` with a function that only sets `qa.WORKSPACE` (a realpath'd `Path` under `tmp_path`), and fake `qa.urllib.request.urlopen`; subprocesses get `QWEN_AGENT_DAEMON_URL` explicitly. No test reaches `127.0.0.1:8190` or a real model server.
- Exact-output tests pass `localtime=time.gmtime` to the renderers, so they do not depend on the machine's time zone.
- Unit tests stay fast (the largest writes 2001 small records), so the gate's selftest (F93) stays fast.

### 6.2 Helper additions (`tests/fleet_testutil.py`, on top of [VISION] 7.2)

| Helper | Addition |
|---|---|
| `StubModelServer(..., delegate_task="stub task")` | the delegate tool call's `task` argument; default unchanged |
| `delegate(port, skill, task, host_id, timeout=120, images=None, trace=None)` | when `trace` is not `None`, the body gains `"trace": trace` |
| `trace(port, trace_id)` | `(status, parsed body)` of loopback `GET /trace?id=<trace_id>`, timeout 30 |
| `recent(port, n=10)` | `(status, parsed body)` of loopback `GET /traces/recent?n=<n>` |
| `trace_cli(home, args)` | `subprocess.run([sys.executable, AGENTD, "trace"] + args, env=clean_env(home), capture_output=True, text=True, timeout=60)` |
| `trace_files(home, host_id)` | sorted paths of `trace.jsonl*` in `daemon_log_dir(home, host_id)` |
| `read_records(home, host_id)` | every line of those files, oldest file first, `json.loads`'d |

### 6.3 Unit tests (`tests/test_fleet_lib.py`)

| ID | Covers | Pass condition |
|---|---|---|
| TRT1 | TR1-TR3 | Every TR1 constant equals its literal. `new_trace_id()` fullmatches `TRACE_ID_RE`, `new_span_id()` `SPAN_ID_RE`; 1000 of each are distinct. With `fleet_lib.secrets.token_hex` monkeypatched to return `"0" * (2n)` once and then a valid value, each function returns the valid value. `valid_trace_id` rejects uppercase, 31 and 33 characters, all zeros, non-`str`. |
| TRT2 | TR4, TR5 | For one sample per kind (exactly TR4's attrs), `make_record(..., now=t0 + 1.2345)` has `dur_ms == 1235`, validates with `trace_record_error(rec) is None` when `agent` is given and with `posted=True` when `agent` is `None` (kinds `turn`, `model`, `tool` only); `json.loads(canonical_json(rec)) == rec`. `dur_ms` is 0 when `now < t0`. |
| TRT3 | TR5 | Each mutation of a valid stored record gives exactly this reason: non-dict `record`; a missing key, an extra `task` key, and `agent` present with `posted=True` `keys`; `v` 2 or `True` `v`; bad `trace_id`/`span_id` (uppercase, all zeros, 15 hex); `parent_span_id == span_id` `parent_span_id`; `agent` `"Bad"` `agent`; kind `run` with `posted=True` `kind`; name `"has space"` `name`; start `-1`, `float("nan")`, `"1"`, `True` `start`; dur `-1`, `1.5` `dur_ms`; status `"OK"` `status`; an extra attr `prompt` `attrs`; `key` of 257 characters, or with `"\n"` `attrs.key`; `prompt_tokens` `True` `attrs.prompt_tokens`. No reason contains any value of the record. |
| TRT4 | TR4, TR50 | `fleet_lib._TRACE_ATTRS` equals TR4's literal; the attributes typed `text` are exactly `{("tool", "key"), ("tool", "outcome")}`; no attribute name is in `{"task", "prompt", "answer", "messages", "content", "data", "images_data", "token", "text", "result", "arguments"}`. |
| TRT5 | TR7, TR8 | `valid_trace_field` accepts the two-key dict and rejects an extra key, a missing key, `None`, bad IDs. `trace_context(None)` gives a valid new ID and `None`. `trace_env_context` gives the pair only when both variables are valid. `build_child_env(environ_with_inherited_trace_vars, url)` has neither variable; with `trace=(t, s)` it has exactly those values; T12's assertions hold for both. |
| TRT6 | TR9 | `http_route("POST", "/spans") == ("loopback", "spans")`; `("GET", "/trace/" + id)` and `("GET", "/trace/x")` give `("signed", "trace")`; `("GET", "/trace?id=x")` and `("GET", "/trace")` `("loopback", "trace_query")`; `("GET", "/traces/recent")` and `("GET", "/traces/recent?n=3")` `("loopback", "recent")`; `("POST", "/trace/x")`, `("GET", "/traces")`, `("GET", "/spans")` and every T24 unknown pair stay `("unknown", None)`. `body_cap("loopback", "spans") == 8192`; VT5's assertions hold. |
| TRT7 | TR16, TR17 | A fixed 8-record result shaped like TR16's example, with the peer's clock 30 s **behind** (its run, agent and model starts precede the delegate's), renders with `localtime=time.gmtime` to exactly TR16's example lines (with the gmtime header). Swapping the order of `result["records"]` gives the same lines. `fmt_ms`: `0 -> "0ms"`, `999 -> "999ms"`, `1000 -> "1.0s"`, `12449 -> "12.4s"`, `None -> "-"`. |
| TRT8 | TR17 | Orphans: a result missing the run span gives `… span <id> on <agent> (not retrieved)` with the agent span indented under it and its model under the agent; a run orphan with `missing == [bravo]` names `bravo`, with zero or two missing names `?`; a non-run orphan names its own agent. Warnings and truncation notes appear after the header in agent order. No root: header shows the earliest start and `-`. Empty records: `trace <12>  -  -  agents: none  spans: 0`. Two records that are each other's parent print once each. A 3000-deep chain renders without `RecursionError`. |
| TRT9 | TR10, TR11 | `TraceStore(tmp, max_bytes=2000, backups=3)`: appending 60 records of three traces leaves `trace.jsonl`, `.1`, `.2`, `.3` and no `.4`; no file exceeds 2000 bytes; every file is mode 0600; `query` returns the retained records of one trace in append order across the backups, none of another trace; the oldest records are gone. A garbage line and a truncated JSON line in a backup are skipped. `append` of an invalid record raises `ValueError("bad trace record: <field>")` and writes nothing. On a second store with the default `max_bytes`, 8 threads appending 200 records each give exactly 1600 lines, every one parseable and valid. |
| TRT10 | TR11 | 2001 records of one trace: `query` returns the first 2000 and `True`; exactly 2000: `False`. With `max_bytes` set to the size of 10 records, it returns 10 and `True`. |
| TRT11 | TR12 | Records of four traces (two roots with delegate spans to `bravo` then `charlie`, one root with an `ok` `delegate_to_skill` tool span keyed `skill=analyst` and no delegate child, one trace with no local root): `recent(10)` lists the three roots newest first, with `spans` equal to the local counts and `delegated` `["investigator@bravo", "analyst@charlie"]` / `["analyst@alpha"]` / `[]`; `recent(1)` the newest only. |
| TRT12 | TR13 | `peer_trace_result`: a reason passes through; 404 `no trace support (http 404)`; 500 `error (http 500)`; bad JSON, wrong `agent`, wrong `trace_id`, non-bool `truncated` `bad response`; records naming another agent, another trace, or failing validation are dropped; `truncated` gives the count of the peer's records. `merge_records` keeps the first of a duplicate `span_id` and orders by `(start, agent, span_id)`. |
| TRT13 | TR14, TR15 | Against `_Scripted`: `post_span` sends one `POST /spans` with `Content-Type: application/json` and the canonical record, returns `True` for 200 and `False` for 500, a closed port, and `None` url; a server that sleeps 3 s gives `False` within 2.5 s (timeout 2). `fetch_trace` / `fetch_recent` return each TR14 message for a closed port, 401, 404, 500, non-JSON and an invalid shape, and the object for a valid one. `delegate_once(..., trace=F)` sends `F` as `"trace"`; when the server answers 400 `{"error":"bad request"}` it sends a second request without `"trace"` (2 requests); 400 `{"error":"other"}` and `trace=None` give one request; `trace=None` bodies equal [VISION]'s. |
| TRT14 | TR18 | `render_recent` of two entries with `localtime=time.gmtime` equals the literal header and rows of TR18 (`-` for no delegations). |

### 6.4 Harness tests (`tests/test_qwen_agent_tracing.py`)

They load `bin/qwen-agent` with `SourceFileLoader` as `tests/test_qwen_agent_fleet.py:28-33` does. `_TraceDaemon(view=None, mode="ok", trace_result=None, outcomes=None)` is an in-process loopback fake: `GET /peers` returns `view` (default: a valid empty view); `GET /trace?id=...` returns `trace_result` (200) or 404; `POST /spans` appends the parsed body and answers 200 (`mode="ok"`), 500 (`"error"`) or sleeps 5 s then 200 (`"slow"`); `POST /delegate` answers `outcomes[host_id]`. It records every request.

| ID | Covers | Pass condition |
|---|---|---|
| TRT20 | TR40, TR47 | `TRACE_RING_SIZE == 20`, `TRACE_TURN_BUDGET == 2.0`, `TRACE_ENV_KEYS == (fleet_lib.TRACE_ENV_ID, fleet_lib.TRACE_ENV_PARENT)`; the `/trace` line is in `HELP_TEXT`; C8's import set is unchanged. |
| TRT21 | TR41-TR44, TR46 | `oneshot` (setup replaced, `urlopen` faked): round 1 answers a `calculate` call `{"expression": "2+2"}` with `usage {"prompt_tokens": 11, "completion_tokens": 3}` and `finish_reason "tool_calls"`; round 2 answers text with `usage` 13/5 and `stop`. The sink receives, in order: model (`call 1`, `tools true`, 11, 3, `tool_calls`), tool (`calculate`, key `2+2`, decision `approved`, status `ok`, outcome `OK: 4`, `round 1`), model (`call 2`, 13, 5, `stop`), turn (`oneshot`, `rounds 2`, `tool_calls 1`, `ok`); one `trace_id`; model and tool parents are the turn's `span_id`; the turn's parent is `null`; every body passes `trace_record_error(posted=True)`. Without `usage`, `prompt_tokens` and `completion_tokens` are `null`. The printed envelope and exit code equal those of the same run with `qa.FLEET = None`. |
| TRT22 | TR45 | Remote: round 1 calls `delegate_to_skill {"skill": "researcher", "task": "find x"}`; the view routes `researcher` to peer `p1`; the `/delegate` body is `{"skill", "task", "host_id", "trace": {"trace_id": T, "parent_span_id": S}}`, where `T` is the turn's trace and `S` the `span_id` of the tool span posted afterwards (key `skill=researcher`). Local: the view's `self` serves `analyst`; `_FakeProc` records `env[QWEN_AGENT_TRACE_ID] == T` and `env[QWEN_AGENT_PARENT_SPAN]` equal to that tool span's ID, and argv equals `_today_argv`. With `qa.FLEET = None` and both variables set in `os.environ`, the child env has neither. |
| TRT23 | TR42 | Subprocess: the real `bin/qwen-agent --skill=researcher --user-prompt=x --base-url=<stub> --model=m` with `clean_env(home, QWEN_AGENT_DAEMON_URL=<sink>, QWEN_AGENT_TRACE_ID=T, QWEN_AGENT_PARENT_SPAN=P)`: no turn span is posted, and the posted model span has `trace_id T` and `parent_span_id P`. With `P` uppercase, or 15 hex: a new trace and a posted root turn (`researcher`, parent `null`), exit 0. In-process `repl()` with both variables set: the turn's parent is `null` and its trace is not `T`. |
| TRT24 | TR46, TR48, TRK6 | Subprocess one-shot against a `StubModelServer` (text answer), four times: daemon URL a closed port; the sink `slow`; the sink `error`; the sink `ok`. stdout (the envelope) is byte-identical and the exit code 0 in all four; elapsed(slow) - elapsed(closed port) <= 2.5 s; the slow and error sinks each received exactly one `POST /spans`; the ok sink two (model, turn). |
| TRT25 | TR41 | After the closed-port run of TRT24, no file named `trace.jsonl*` exists under the test `HOME` or the workspace. |
| TRT26 | TR47 | In-process `repl()` (`input` scripted, `run_turn` faked to return `ok` outcomes, sink with a canned `trace_result`): `/trace` before any turn prints `no turns in this session yet`; after one turn, `/trace` and `/trace 1` print exactly `render_trace(canned)`; `/trace 2` prints `only 1 turn in this session`; `/trace 21`, `/trace 0`, `/trace xyz` print `TRACE_USAGE`; `/trace <valid id>` queries that ID; a sink with `trace_result=None` prints `the daemon at <url> has no trace support (http 404)`; a closed port prints `daemon not reachable at <url>`; `qa.FLEET = None` prints `tracing is off: fleet_lib.py is not available`. After 25 turns `TRACE_RING` holds the last 20 IDs. The turn output (answer and notices) equals the same session with `qa.FLEET = None`. |
| TRT27 | TR44, TR50 | In-process one-shot with the prompt `TRSENTINEL-PROMPT`, a delegation whose task is `TRSENTINEL-TASK` (remote and local), a `write_file` call (with `--danger-auto-approve`) whose content is `TRSENTINEL-CONTENT`, a vision delegation of two workspace PNGs (view serving `vision`), and model answers `TRSENTINEL-ANSWER`: no `/spans` body contains any sentinel, the PNG bytes' base64, or an image path; the vision tool key is `skill=vision images=2`. |
| TRT28 | TR43 | Inside a traced one-shot turn, `qa.urllib.request.urlopen` (not `chat_completion`, which holds the instrumentation) faked to raise `HTTPError(500)` with a body, to raise `URLError`, to return a non-JSON body, and to raise `KeyboardInterrupt`, one per run: model spans have status `http_error` (`http 500`), `network_error`, `malformed_response`, `interrupted`; `run_turn`'s results and stderr equal the untraced run; the `HTTPError` body is still read by `run_turn` (its `[server error 500] <body>` line is unchanged). |

### 6.5 Integration tests (`tests/test_fleet_tracing.py`)

Loopback only, `--timing-scale 0.1`, the autouse reaper of `test_fleet_integration.py` copied. "The chain" is `ftu.Fleet(tmp_path, skills={"bravo": ["investigator"]}, stub_kwargs={"alpha": {"delegate_skill": "investigator"}, "bravo": {"delegate_skill": "analyst"}})`, started, with the real harness run on `alpha` as `test_fleet_integration._harness` does (copied) once every daemon sees the other two. Its trace ID is the newest entry of `ftu.recent(alpha)`.

| ID | Covers | Procedure and pass condition |
|---|---|---|
| TRT40 | TR22-TR27, TR42-TR45, TR17 | The chain. `ftu.trace_cli(home, ["--port", alpha, T])` exits 0; the header lists `agents: alpha, bravo, charlie`; there is exactly one depth-0 line (`turn oneshot ... @alpha`) and no placeholder; the lines in order match: alpha turn; alpha model; alpha tool `delegate_to_skill  skill=investigator`; alpha `delegate investigator -> bravo  req=<r1>  http=200 ... ok`; bravo `run investigator  req=<r1>`; bravo `agent investigator`; under it bravo model, bravo tool `skill=analyst`; bravo `delegate analyst -> charlie  req=<r2>`; charlie `run analyst`; charlie `agent analyst`; charlie model (under charlie's agent); bravo model (under bravo's agent); alpha model (14 spans; the only `turn` line is alpha's). `<r1>` appears in bravo's `run start` log line and alpha's `delegate` line. `--json` gives 14 records, every non-root parent present among them, `missing == []`, `truncated == []`. |
| TRT41 | TR12, TR18, TR29 | After two harness runs on the chain: `trace_cli(["--port", alpha, "--recent"])` exits 0; line 1 is TR18's header; two rows, newest first, `delegated` `investigator@bravo`, `spans` 5 (alpha's own: turn, two models, tool, delegate); `--recent 1` gives one row; `--recent 0`, `--recent x`, `--recent --json`, `T --recent`, no argument, `--port 70000`, and `badid` each exit 2 with TR29's line; against a closed port, exit 1 `qwen-agentd: daemon not reachable at ...`; an unknown ID exits 1 with `no records for trace <id>` on stderr. |
| TRT42 | TR27, TR17 | After TRT40's run, note bravo's delegate span ID `D` (from `--json`), then kill bravo. Within 1 s (still live) and again after it leaves alpha's live table: `trace_cli(T)` exits 0; stdout has `! bravo: unreachable (connection refused)`, `… span D on bravo (not retrieved)` followed by charlie's `run analyst` line at depth 1, its agent at depth 2 and its model at depth 3; alpha's delegate line has no child. |
| TRT43 | TR25, TR15, TR27 | `alpha` plus an in-process signed fake peer `delta` (T44's `_FakePeer` pattern) serving `researcher`: `/run` with a `trace` key answers signed 400 `{"error":"bad request"}`, without it the canned envelope; `GET /trace/<id>` answers signed 404 `{"error":"not found"}`. `ftu.delegate(alpha, "researcher", "t", "delta", trace={"trace_id": T, "parent_span_id": P})` gives outcome `ok`; delta saw two `/run` bodies, the first with `trace` (`parent_span_id` = alpha's delegate span) and the second without. `ftu.trace(alpha, T)` has alpha's delegate span (`status ok`, `http 200`) and `missing == [{"agent": "delta", "reason": "no trace support (http 404)"}]`; the CLI prints `! delta: no trace support (http 404)` and the delegate under `… span P on alpha (not retrieved)`. |
| TRT44 | TR26 | On bravo: unsigned `GET /trace/<T>` 401 empty; signed 200 whose signature verifies, `agent bravo`, only bravo's records; the same headers replayed 401; signed with `OTHER_TOKEN` 401; signed `GET /trace/xyz` signed 400 `{"error":"bad trace id"}`; bravo's log unchanged. |
| TRT45 | TR20, TR22, TR27, TR28 | `/spans`, `/trace?id=`, `/traces/recent` each with `Host: evil.example:<port>` 403, with `Origin: http://evil.example` 403; `POST /spans` with `Content-Type: text/plain` 403; on Linux, each from `127.0.0.2` 403. `GET /trace?id=xyz` 400 `bad trace id`; `GET /traces/recent?n=101` 400 `bad n`. The log is unchanged. |
| TRT46 | TR22, TR9 | `POST /spans` headers-only with `Content-Length: 8193` 413 empty; body `not json` 400 `{"error":"bad span: record"}`; a valid record with kind `run` `bad span: kind`; with an extra `task` key `bad span: keys`; with `agent` set `bad span: keys`. A valid record answers 200 `{"ok":true}` and appears in `ftu.read_records` with `agent alpha`; `trace.jsonl` is mode 0600. |
| TRT47 | TR50, TRK5 | The chain with `--user-prompt=go TRSENTINEL-PROMPT`, `delegate_task` `TRSENTINEL-TASK-A` (alpha) and `TRSENTINEL-TASK-B` (bravo); answers are the stubs' `ALPHA-ANSWER`, `BRAVO-ANSWER`, `CHARLIE-ANSWER`. Blobs: every file in every agent's `A/logs` except `last-run.stderr`, the `ftu.trace` and `ftu.recent` bodies, and the CLI's tree, `--json` and `--recent` stdout: none contains either task sentinel, the prompt sentinel or any answer. Those blobs plus every `last-run.stderr`: none contains `TEST_TOKEN`, `TEST_KEY` or the join string. Vision variant ([VISION] VT20's fleet, `alpha` delegating two images): no `trace.jsonl*` contains `PNG_BYTES`, `JPEG_BYTES` or the first 40 characters of either base64, and alpha's tool span key is `skill=vision images=2`. |
| TRT48 | TR23, TR8 | `bravo` with `--qwen-agent-bin <envdump hook>`; `ftu.delegate(alpha, "researcher", "again", "bravo", trace={...T...})`: the dumped env has `QWEN_AGENT_TRACE_ID == T` and `QWEN_AGENT_PARENT_SPAN` equal to bravo's agent span (from `read_records`), whose parent is bravo's run span, whose parent is alpha's delegate span; bravo has no `turn` record for `T`; `argv[1:]` equals T46's list. |
| TRT49 | TR21, TRK6 | Before starting `alpha`, create `<alpha home>/agents/alpha/logs/trace.jsonl` as a **directory**. The harness run on the chain still exits 0 with T43's answer; `POST /spans` still answers 200; alpha's log has exactly one `trace: cannot write ` line. |

### 6.6 Existing tests that change

| File | Test | Edit |
|---|---|---|
| `tests/test_fleet_vision.py` | `test_vt27_unsigned_peer_503_is_busy_and_413_is_peer_error` | `all(set(b) == {"skill", "task", "request_id", "images"} ...)` becomes `{"skill", "task", "request_id", "images", "trace"}`: TR24 always forwards `trace` |
| `tests/fleet_testutil.py` | helpers | Section 6.2 additions; no existing signature changes meaning |

Unchanged and still passing, checked against the code: T12 (no trace variables in its environ), T24 (no listed pair starts with `/trace`), T33 (no turn traced), T35-T39 and VT16-VT18 (they call `exec_delegate_to_skill` directly, so `trace` is `None` and the bodies are unchanged; T36's `interrupted(*args)` accepts six arguments), T43-T48 (T46 scans `trace.jsonl` too and finds no token; argv unchanged; T48's log lines unchanged), VT5, VT8, VT20-VT26 (VT20's `run start` regex and VT26's `b"stub task"` scan hold: no log line changes and no record holds task text), MT11 (`TraceStore` does no I/O at construction), C8, M10, M14, every `test_qwen_agent_*` suite (`FLEET` is `None` in-process unless a test sets it).

### 6.7 Regression

| ID | Covers | Pass condition |
|---|---|---|
| TRT60 | TRK1 | Before any change, record `python3 -m pytest tests/ -q -rA` from `WS` and the three plain-python scripts. After: the same outcomes, the Section 6.6 test passing, every TRT passing. |
| TRT61 | TRK2 | `/usr/bin/python3 -m py_compile` and `python3 -m py_compile` exit 0 on the four programs and every changed or new test file. |
| TRT62 | TRK3 | C8 and M14 pass. `grep -n "^import \|^from " fleet_lib.py bin/qwen-agentd` differs from the baseline only by `import secrets`. `grep -n -E "urllib\.request|urlopen" fleet_lib.py bin/qwen-agentd` prints nothing. |
| TRT63 | scope | `git diff --stat <base>` lists only G1-G8 (and this spec, committed separately). |

---

## 7. Requirement-to-test table

| Req | Tests | Live-only / reason |
|---|---|---|
| TR1 | TRT1 | |
| TR2 | TRT62 | |
| TR3 | TRT1 | |
| TR4 | TRT2, TRT3, TRT4 | |
| TR5 | TRT2, TRT3 | |
| TR6 | TRT3, TRT47 | |
| TR7 | TRT5, TRT43 | |
| TR8 | TRT5, TRT48 | |
| TR9 | TRT6, TRT46 | |
| TR10 | TRT9, TRT49 | 5 MB rotation at scale: TRT9 uses a small `max_bytes`; the constant is TRT1's |
| TR11 | TRT9, TRT10 | |
| TR12 | TRT11, TRT41 | |
| TR13 | TRT12, TRT42, TRT43 | |
| TR14 | TRT13, TRT41 | |
| TR15 | TRT13, TRT43 | |
| TR16 | TRT7, TRT40 | |
| TR17 | TRT7, TRT8, TRT42 | |
| TR18 | TRT14, TRT41 | |
| TR20 | TRT44, TRT45 | |
| TR21 | TRT49 | |
| TR22 | TRT46, TRT21 | |
| TR23 | TRT40, TRT48 | |
| TR24 | TRT40, TRT43 | |
| TR25 | TRT43 | |
| TR26 | TRT44 | |
| TR27 | TRT40, TRT42, TRT43 | real-LAN timeout reason: TRR4 |
| TR28 | TRT41, TRT45 | |
| TR29 | TRT41 | |
| TR40 | TRT20 | |
| TR41 | TRT21, TRT25 | |
| TR42 | TRT21, TRT23 | |
| TR43 | TRT21, TRT28 | real usage counts: TRR2 |
| TR44 | TRT21, TRT27 | |
| TR45 | TRT22, TRT40 | |
| TR46 | TRT24 | |
| TR47 | TRT26 | live REPL: TRR2 |
| TR48 | TRT21, TRT24, TRT26, TRT28 | |
| TR49 | TRT62, C8, M14 | |
| TR50 | TRT4, TRT27, TRT47 | TRR5 |

---

## 8. Changes to the parent specs (recorded here; their files are not edited)

| Spec / ID | Change |
|---|---|
| [FLEET] F4 | Span records (timings, statuses, bounded attributes, never text) also cross the network, on signed `GET /trace/<id>`. |
| [FLEET] F42 | Routes `POST /spans`, `GET /trace?id=`, `GET /traces/recent` (loopback) and `GET /trace/<id>` (signed); `http_route` matches the last three by prefix (TR9). |
| [FLEET] F47, [VISION] V16 | The `/run` body may carry `trace` (TR23). |
| [FLEET] F54a | The child env strips inherited `QWEN_AGENT_TRACE_ID` / `QWEN_AGENT_PARENT_SPAN` and sets them from the run span (TR8, TR23). |
| [FLEET] F65, F66, [VISION] V14, V15 | `/delegate` may carry `trace`; `forward_run` returns the peer status too and retries a traced 400 once without the field (TR24, TR25). |
| [FLEET] F68, [VISION] V10 | `delegate_once` gains `trace=None` and the same retry (TR15). |
| [FLEET] F69, [VISION] V31 | `_delegate_remote` passes the tool span as `trace` (TR45). |
| [FLEET] F94 | A new subcommand `trace` beside `status` (TR29). |
| [FLEET] F107, [MULTI] M5 | `A/logs` also holds `trace.jsonl` and `.1`-`.3`. |
| [FLEET] F109, [VISION] V22 | Extended by TR50; the one new log line is TR21's WARNING. |
| [VISION] V7 | `body_cap` gives `/spans` 8192 bytes (TR9). |
| [VISION] VT27 | Migrated (Section 6.6). |
| [FLEET] Section 12 | TRR1-TRR5 run after R10 and [VISION] VR6. |

---

## 9. Rollout (after [FLEET] R10 and [VISION] VR6)

Tracing ships as one ordinary release and reaches every agent by self-update (F84). No new port, firewall rule, service, secret or registry change. During the update window, an updated agent reports a peer one release behind as `! <agent>: no trace support (http 404)`, and every delegation keeps working through the TR15/TR25 retry.

- **TRR1. Release.** On the Mac dev checkout: TRT60-TRT63 pass; commit; push; `git tag v<YYYY.MM.DD>.<n>`; `git push origin v<YYYY.MM.DD>.<n>`. Pass: within 30 min, `qwen-agentd status --agent-id <id>` shows that version with `update: status=ok` for `mac-local` and `ollama-168` (R10's check) and, at .185's console, for `vision-185`.
- **TRR2 (as R7, TRK7). Mac.** Run `qwen-agent`; ask a question and tell the model to use `delegate_to_skill` with `skill="researcher"` (R7's step). Then type `/trace`. Pass: the header lists `agents: mac-local, ollama-168`; one depth-0 `turn repl` line; a `delegate researcher -> ollama-168  req=<r>  http=200 ... ok  @mac-local` line with `run`, `agent` and, under the agent, a `model qwen3.5:9b ... <p>→<c> tok  stop  @ollama-168` line beneath it, with non-zero token counts; no `!` line and no placeholder. `<r>` matches the `run end skill=researcher request_id=<r> http=200 status=ok` line in `~/agents/ollama-168/logs/qwen-agentd.log` on .168. `qwen-agentd trace --agent-id mac-local --json <id>` (the ID from `qwen-agentd trace --agent-id mac-local --recent 1`) shows `"missing": []`.
- **TRR3 (after VR4). Mac.** Repeat VR4's vision question in the REPL, then run `qwen-agentd trace --agent-id mac-local --recent 3`. Pass: the newest row's `delegated` column is `vision@vision-185`; `qwen-agentd trace --agent-id mac-local <that id>` shows a `tool delegate_to_skill  skill=vision images=1` line and `run vision ... @vision-185`. At .185's console: `grep -c iVBORw0KGgo ~/agents/vision-185/logs/trace.jsonl*` prints `0` for every file (no PNG base64).
- **TRR4 (as R6). .168 then Mac.** `systemctl --user stop qwen-agentd-ollama-168`. On the Mac, `qwen-agentd trace --agent-id mac-local <TRR2's id>` within 90 s, and again after 2 min. Pass both times: exit 0; a line `! ollama-168: unreachable (connection refused)` (or `(timeout)` if the host itself is down); the mac-local spans with the delegate line as a leaf. Then `systemctl --user start qwen-agentd-ollama-168`; the next query shows the full tree again.
- **TRR5 (as R9). Both hosts, and .185.** R9's token grep (which covers `~/agents`, so every `trace.jsonl*`) prints nothing. `grep -l '<a distinctive word of TRR2's question>' ~/agents/*/logs/trace.jsonl*` prints nothing on the Mac and on .168.

| KPI | Live step | Pass |
|---|---|---|
| TRK7 | TRR2 | one connected Mac -> ollama-168 tree |
| TRK5 (live part) | TRR3, TRR5 | no image base64, question text or token in any trace file |
| -- | TRR4 | stopped peer named, partial tree, exit 0 |

---

## 10. Values chosen by the spec

1. G6, G7: harness and integration tests in two new files.
2. TR1: `TRACE_SPAN_MAX_BYTES = 8192`, `TRACE_TEXT_CHARS = 256`, `TRACE_QUERY_TIMEOUT = 20`, `TRACE_FANOUT_DEADLINE = 6`, `TRACE_CLIENT_MAX_BYTES = 32 MiB`, `TRACE_RECENT_MAX = 100`, the name/token regexes.
3. TR3: IDs from `secrets` in `fleet_lib` (so `bin/qwen-agent` needs no import); all-zero IDs are redrawn.
4. TR4: the attribute set per kind, exact-key; only `tool.key` and `tool.outcome` are text.
5. TR4, TR23, TR42: `agent` is the daemon-side child-process span and the child's parent; a child with an inherited trace posts no turn span.
6. TR4, TR42: a turn span's name is `repl`, `oneshot` or the skill; there is no separate sub-agent kind.
7. TR7: a request without `trace` starts a new root trace.
8. TR10: no fsync; rotation by exact bytes before the write; invalid lines skipped on read.
9. TR11: the byte-needle prefilter; reads hold the store lock.
10. TR12: `delegated` lists delegate targets (failed attempts included) and local delegations (`ok` tool spans with no delegate child), each pair once.
11. TR15, TR25: one retry without `trace` on a verified 400 `bad request`, client and daemon side.
12. TR17: a run orphan's placeholder names the only unanswered agent, else `?`.
13. TR18: the recent list shows full 32-character IDs.
14. TR21: no trace ID in any log line; one WARNING per process on a store write failure.
15. TR22: one span per `/spans` request; the daemon sets `agent`; `/spans` accepts only `turn`, `model`, `tool`.
16. TR24: image-refused `/delegate` requests record no span; the forward always carries `trace`.
17. TR25: the peer status is recorded for every received response, verified or not.
18. TR27: a second fan-out round to delegate targets that were not live.
19. TR29: `--json` refused with `--recent`; an empty `--recent` exits 1; `--port` wins over `--agent-id`.
20. TR41: tracing is on whenever `fleet_lib` is loaded and the daemon URL is usable; a `KeyboardInterrupt` during a post is absorbed.
21. TR42: only one-shots honour the trace env; malformed values start a new trace silently; the envelope is unchanged.
22. TR44: the tool key is the decision-log key, with `delegate_to_skill` reduced to `skill=<s>[ images=<n>]`.
23. TR46: one 2 s budget per turn shared by every post; the first failure stops posting for the turn.
24. TR47: `/trace N` takes N from 1 to 20; `turn` is singular for one turn; one new `/help` line.

---

## 11. Risks and contradictions

**Contradictions and readings**

- **TRC1 (resolved).** The `agent` kind follows the approved Section 1 diagram, run -> agent -> the child's model/tool/delegate spans: the daemon passes the agent span as `QWEN_AGENT_PARENT_SPAN` and an inheriting child posts no turn span (TR4, TR23, TR42). Consequences: "child roots under run span" holds through the agent span; a child's rounds and turn status are not recorded (the agent span's `envelope_status` carries its outcome); local `--skill` children inherit the same variables and also post no turn, so TR12 finds local delegations from the caller's `ok` tool span instead of a child turn.
- **TRC2. [VISION] VT27** asserts the forwarded `/run` key set; TR24 adds `trace` to every forward, so VT27 is migrated (Section 6.6). No other [VISION] test asserts a forwarded body.
- **TRC3. [VISION] signatures.** `forward_run` returns four values instead of three (its only caller is `handle_delegate`); `spawn_run`/`_run_child` gain a trailing `trace=None`, so [VISION] VT25(a)'s positional calls are unaffected; `loopback_endpoint`/`signed_endpoint` gain `path` (no test calls them).
- **TRC4. "fans out to all live peers".** TR27 adds a second round to non-live delegate targets; without it the approved failure line `! <agent>: unreachable (...)` could never appear once a stopped peer left the live table (90 s).
- **TRC5. "PROTOCOL stays 1" vs strict key checks.** Without the TR15/TR25 retry, every traced delegation to a peer one release behind fails during the self-update window. The retry is the minimum that keeps the approved field shape and protocol.
- **TRC6. "only <k> turns in this session"** is rendered `only 1 turn in this session` for k = 1.

**Risks (accepted)**

- **TRX1. Non-UTF-8 terminals.** `→` and `…` (approved glyphs) raise `UnicodeEncodeError` on a stdout that cannot encode them (a non-UTF-8, non-C locale; Python 3.7+ coerces the C locale to UTF-8). The CLI then exits 1 with `internal error`; the REPL's `/trace` raises out of the slash command. Unseen on the fleet's macOS and Linux shells.
- **TRX2. Nested budgets.** The 2 s bound is per process turn. A turn that delegates locally waits for a child that has its own 2 s budget, so a slow daemon can add 2 s per nesting level (at most 3 levels: top, investigator, analyst).
- **TRX3. Skewed sibling order.** Siblings recorded on different hosts (rare: a tool span's delegate spans are all on the caller) are ordered by unsynchronised clocks; nesting is never affected.
- **TRX4. Free-text attributes.** `tool.key` holds the model's own tool arguments (a search query, a fetched URL, a command, a remembered line), and `tool.outcome` the first line of an `ERROR:` result, which can quote a server's error body. Both are clipped and control-character-free, stay inside the fleet (loopback or signed), and are the same text the `[auto]` lines and the decision log already show; a model that copies the user's prompt into a search query puts that text in a span.
- **TRX5. Read latency.** A query reads up to 20 MB under the store lock (about 0.2 s), during which `/spans` posts wait; a slow post costs at most the poster's budget.
- **TRX6. Placeholder `?`.** A run orphan with zero or several unanswered agents shows `on ?`, because the `/run` body carries no caller ID.
- **TRX7. Replayable queries.** A captured signed `GET /trace/<id>` can be replayed to another daemon within the 60 s skew window ([FLEET]'s and [VISION] VX1's parked replay risk); it returns only bounded, text-free records.
- **TRX8. Dropped spans.** A span whose post fails or exceeds the budget is lost; the tree then shows its children under a placeholder. This is the approved trade (no retry, no buffer) for never slowing a turn by more than 2 s.

**Coverage.** Every TR requirement maps to at least one TRT test (Section 7). Real token counts from vLLM/Ollama, the REPL against the real fleet, a real LAN timeout, and the 5 MB rotation size at scale are covered only by TRR2-TRR5 and by TRT1's constant check.

Open questions: none.
