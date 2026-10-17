# Fleet Tracing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record one trace per REPL turn or one-shot, made of spans (the turn, each model call, each tool call, each delegation hop, each peer `/run` and its child process) with timings, statuses and a few bounded attributes; link the spans across processes and hosts by parent span ID; store each agent's spans in its own `A(<id>)/logs/trace.jsonl` through its daemon; and show one connected tree on demand with `/trace` in the REPL or `qwen-agentd trace` on any agent host, by pulling the records from every peer.

**Architecture:** Every pure piece lives in `fleet_lib.py`: W3C-shaped IDs from `secrets`, the exact-key record schema and its validator, the sanitizers, the propagation helpers (`trace` body field, `QWEN_AGENT_TRACE_ID` / `QWEN_AGENT_PARENT_SPAN`), the `TraceStore` (one lock, exact-byte rotation, capped queries, the recent list), the peer-answer merge, the `http.client` loopback clients and the tree and table renderers. `bin/qwen-agentd` is the single writer: it accepts finished spans on loopback `POST /spans`, records its own `delegate`, `run` and `agent` spans, forwards `trace` on `/run` (retrying once without it for a peer one release behind), answers signed `GET /trace/<id>` with its own records, and fans a loopback `GET /trace?id=` out to every live peer plus every delegate target. `bin/qwen-agent` posts its `turn`, `model` and `tool` spans as they finish within one shared 2 s budget per turn, passes the current tool span to local and remote delegations, and adds `/trace`; no import statement changes and no trace ever changes a turn's output.

**Tech Stack:** Python 3.13.0 (`python3`, pytest 8.3.4) and Python 3.9.6 (`/usr/bin/python3`, compile check only); standard library only (`secrets`, `http.client`, `threading`, `json`, `os`); loopback-only test daemons, stub model servers, in-process fake daemons and hook scripts from `tests/fleet_testutil.py`.

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-10-17-fleet-tracing-design.md` (commit `2be4d10`, user-approved), which builds on [FLEET] (`2026-10-16-fleet-discovery-self-update-design.md`), [MULTI] (`2026-10-17-fleet-multi-agent-hosts-design.md`) and [VISION] (`2026-10-17-fleet-vision-agent-design.md` and its plan `docs/superpowers/plans/2026-10-17-fleet-vision-agent.md`). This plan applies on top of the final [VISION] code, `a704a92` on `qwen-agent-redteam` ([VISION]'s final-review fix wave on top of `caa9cbc`); every Edit below is written against that tree, not against the `2eb980f` line numbers the spec cites. The spec is final; this plan changes no design decision. Every place where the plan had to read the spec, and every value it chose, is listed in "Plan decisions" at the end.

## Global Constraints

From the spec, verbatim (requirement IDs in brackets):

- [0.3] "`bin/qwen-agentd-launch`, `agent/qwen-agent-unsafe`, `scripts/`, `README.md`, every spec file, and every other file are not changed."
- [0.4] Out of scope: "OpenTelemetry (no dependency, no OTLP export, no `traceparent` header), sampling, a collector, a UI."; "Tracing preflight, `setup`, `discover_context_window`, the memory checkpoint, beacons, polling, self-update."; "Retention by age; compression; a trace ID in the one-shot envelope or in any log line."; "Recording any text other than the two bounded tool attributes of TR4 (Section 4.3 lists what is never recorded)."
- [TRK1] "`python3 -m pytest tests/ -q -rA` from `WS` gives the baseline recorded immediately before implementation (after [VISION] is in), with the Section 6.6 migrated test passing, plus every TRT test passing, and no lost pass. `python3 tests/test_qwen_agent_context_budget.py`, `python3 tests/test_qwen_agent_image_oneshot.py` and `python3 tests/test_qwen_agent_session_memory.py` each print the same `OK n/n` as at the baseline"
- [TRK2] "`/usr/bin/python3 -m py_compile` (3.9.6) and `python3 -m py_compile` (3.13) succeed on `fleet_lib.py`, `bin/qwen-agent`, `bin/qwen-agentd`, `bin/qwen-agentd-launch` and every changed or new test file"
- [TRK3] "Standard library only. `bin/qwen-agent`'s import set is unchanged (C8, M14). `fleet_lib.py` adds exactly `import secrets`; `bin/qwen-agentd` adds no import. Every trace HTTP call uses `http.client`; no `urllib.request` or `urlopen` appears in `fleet_lib.py` or `bin/qwen-agentd`"
- [TRK4] "Tests never use the real `HOME`, and never reach a daemon running on the machine: every new test sets `HOME` to a temp directory and sets `QWEN_AGENT_DAEMON_URL` (subprocesses) or `qa.FLEET_DAEMON_URL` (in-process) to a test daemon or a closed port"
- [TRK5] "No task text, user prompt, system prompt, model answer, tool result body, image byte or base64, fleet token, key or join string appears in any trace record, any file under any agent's `A/logs/` (the token: including `last-run.stderr`), any `/trace`, `/trace/<id>` or `/traces/recent` response, or `qwen-agentd trace` output"
- [TRK6] "A tracing failure (no daemon, a daemon slower than 2 s, a daemon answering 500, a daemon that cannot write its store) never changes a turn's stdout, answer, envelope or exit code, and adds at most 2 s to one process's turn"
- [TR21] "This WARNING is the only new log line of the feature. No existing log line changes (F53, F67, V21 text, and [VISION] VT20's regex, stay exact)."
- [TR48] "With tracing on, off, or failing, `run_turn`'s results, every byte the REPL prints for a turn, the one-shot envelope and exit code, the child argv, and the `/delegate` responses are identical. Every trace helper catches its own exceptions. Only `/help` gains one line."
- [TR49] "No import statement is added to `bin/qwen-agent` (C8, M14 still pass); `fleet_lib` adds only `import secrets`; `bin/qwen-agentd` adds none."
- [6.1] "Exact-output tests pass `localtime=time.gmtime` to the renderers, so they do not depend on the machine's time zone." and "Unit tests stay fast (the largest writes 2001 small records), so the gate's selftest (F93) stays fast."

House rules for this plan:

- `WS` = `/Users/reubenpatterson/local_agent_harness/qwen-agent-workspace`. The git root is one level up, so `git status` and `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix. Branch `qwen-agent-redteam`. Run every command from `WS` unless a step says otherwise.
- Start from `a704a92` or a later commit that contains it (the [VISION] plan's final review and its fix wave are in). Task 1 records the starting commit as `BASE` in a file; every later "since the base" check reads it from there.
- Files this plan modifies, and no others: `fleet_lib.py`, `bin/qwen-agentd`, `bin/qwen-agent`, `tests/fleet_testutil.py`, `tests/test_fleet_lib.py`, `tests/test_fleet_vision.py` (exactly one line, spec 6.6). Files it creates: `tests/test_fleet_tracing.py`, `tests/test_qwen_agent_tracing.py`. `agent/qwen-agent-unsafe`, `tests/test_researcher_think_off.py`, `bin/qwen-agentd-launch`, `scripts/`, `../README.md` and `docs/` stay byte-identical.
- Tests and commands never touch the real `HOME` (`~/agents`, `~/.local`, `~/.config`, `~/Library/LaunchAgents`), never run `launchctl` or `systemctl` for real, never run `init-fleet`, `join` or `install` by hand, and never contact 192.168.1.168, 192.168.1.185 or any real model server. Rollout is human-run after Task 14.
- Never print or log task text, prompts, answers, image bytes or the fleet token while executing this plan; the tests check that the code does not either.
- Every pytest run first prints a `pytest_asyncio` `PytestDeprecationWarning` about `asyncio_default_fixture_loop_scope`; it is expected and is not a failure. Durations in expected outputs vary; only the counts matter. macOS has no `timeout` command; do not use it.
- Every code block in this plan is copied exactly, byte for byte. An "Edit" replaces one block of old text, which occurs exactly once in the file, with the new text; "base lines" are the line numbers of the old text in the file as it is at the start of that task on the tested tree (later edits of the same task do not shift them, because each edit is located by its old text). If an Edit's old text does not occur exactly once, stop and report: do not adapt it. An "Append" adds two empty lines after the file's current last line, then the block. A "Create" writes a new file whose whole content is the block. Never retype a block from the spec when this plan shows it.
- [VISION]'s fix wave (`a704a92`: two `[server error ...]` lines in `bin/qwen-agent`, VT26's positive control in `tests/test_fleet_vision.py`, one test in `tests/test_qwen_agent_vision.py`) is in the tested tree. This plan never edits `bin/qwen-agentd`'s pre-body 413/503 close path in `_handle` (its two `_handle` edits are the single lines that call `fleet.loopback_endpoint` and `fleet.signed_endpoint`) and edits exactly one line of `tests/test_fleet_vision.py` (VT27's key set). If a later commit shifts a base line number below, continue: the old text locates every edit. If an old text itself was changed, stop and report.
- Commit hygiene: the working tree has unrelated untracked paths (`../.DS_Store`, `../.claude/`, `../agent/__pycache__/`, `../bin/`); never stage them. Stage only the paths each task names, check `git diff --cached --name-only` before each commit, put `(tracing TR<n>)` in every commit subject, and end every commit message with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Pre-tested: every task was implemented from this plan's text in a scratch copy of `a704a92` (outside the repository); each RED and GREEN result below is the one observed there, on this Mac, and every changed file compiled under both interpreters. Replaying this plan's Edits, Appends and Creates in order on `a704a92` reproduces the tested final tree byte for byte (checked by parsing this file back into edits).

## Review Focus

These five input classes are implied by the spec, are the ones most likely to hit a real user first, and no TRT test exercises them. Each is pinned by a test in its owning task.

1. **A tool key or error line in a non-Latin script with emoji** (a search query `東京 ラーメン 🍜 near Shibuya`, an error line of 256 emoji). Expected: accepted under the 8192-byte `/spans` cap (escaped by `ensure_ascii`), stored exactly, and rendered unchanged in the tree. Test: `test_tracing_focus_1_non_ascii_tool_keys_round_trip` (Task 6).
2. **The first `trace --recent` on a newly installed agent**, before any turn was traced, so no `trace.jsonl` exists yet. Expected: exit 1 with `qwen-agentd: no traces recorded on <agent>` (never a 500 or a missing-file error), `trace <id>` says `no records`, and no query creates the file. Test: `test_tracing_focus_2_fresh_agent_with_no_trace_file` (Task 9).
3. **Ctrl-C while the model is answering a REPL turn.** Expected: the interrupted turn still has a trace (its model span and turn span say `interrupted`), the next turn gets a new trace, and `/trace 2` reaches the interrupted one. Test: `test_tracing_focus_3_an_interrupted_repl_turn_is_still_traced` (Task 12).
4. **A daemon restart between the turn and the query** (every self-update restarts it). Expected: the trace is still returned by `GET /trace?id=` and listed by `--recent` after the restart. Test: `test_tracing_focus_4_traces_survive_a_daemon_restart` (Task 8).
5. **A peer child that crashes before printing an envelope** (a broken release, a model server that went away). Expected: the peer still records the run span and the agent span with http 502 and status `error`; a busy refusal is a run span `busy` with no agent span; a malformed `trace` field is a plain 400 with no span. Test: `test_tracing_focus_5_a_crashed_child_still_leaves_run_and_agent_spans` (Task 10).

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `fleet_lib.py` | Modify (Tasks 2-6) | Adds `import secrets`; the TR1 constants after `RUN_TMP_PREFIX`; `build_child_env(..., trace=None)`; `_ROUTES` and `http_route` for the four trace routes; `body_cap` for `/spans`; `_post_delegate` and `delegate_once(..., trace=None)` with the one retry; and a new last section `# Tracing: IDs, records, the store, the clients and the tree (tracing spec)` holding the IDs, the record schema, builder and validator, the sanitizers, the propagation helpers, the loopback clients and their result checks, `TraceStore`, the peer-answer merge and the renderers. |
| `bin/qwen-agentd` | Modify (Tasks 6-10) | The usage block gains `trace`; `_OPTIONAL_KEYS`, `_TRACE_QUERY_RE`, `_RECENT_QUERY_RE`; `_handle` passes the path to both dispatchers; `Daemon.trace_store`; `record_span`, `_trace_write_failed`, `handle_spans`, `handle_peer_trace`, `handle_trace_query`, `trace_call`, `_fetch_peer_traces`, `_merge_round`, `trace_query`, `handle_recent`; `handle_run` plus `_run_request` (run and agent spans), `spawn_run(..., trace=None)`, `_run_child(argv, trace=None)`; `handle_delegate` (delegate span), `forward_run` plus `_forward_once` (the `trace` field, the peer status, the retry); `cmd_trace` and the `trace` subparser. No import changes. |
| `bin/qwen-agent` | Modify (Tasks 11, 12) | `TRACE_RING_SIZE`, `TRACE_TURN_BUDGET`, `TRACE_ENV_KEYS`, `TRACE_USAGE`, `TURN_TRACE`, `TRACE_RING`; a `# Tracing` section before `# Section 11.1` with the turn, post, model and tool helpers; the instrumented `chat_completion`; the tool spans in `run_turn`; the turn spans in `repl` and `oneshot`; the child env and `/delegate` `trace` propagation; `/trace` (`HELP_TEXT`, `handle_slash_command`, `slash_trace`). No import statement changes. |
| `tests/fleet_testutil.py` | Modify (Tasks 6, 8, 9, 10, 13) | `trace_files`, `read_records`, `trace`, `recent`, `trace_cli`, `delegate(..., trace=None)`, `StubModelServer(..., delegate_task="stub task")`. |
| `tests/test_fleet_lib.py` | Modify (Tasks 2-6) | TRT1-TRT14. Still the gate's selftest. |
| `tests/test_fleet_vision.py` | Modify (Task 10) | VT27's one migrated assertion (spec 6.6). |
| `tests/test_fleet_tracing.py` | Create (Task 6), append (Tasks 7-10, 13) | TRT40-TRT49, the fan-out and unreadable-store tests, and Review Focus 1, 2, 4, 5. |
| `tests/test_qwen_agent_tracing.py` | Create (Task 11), append (Task 12) | TRT20-TRT28 and Review Focus 3. |

The suite stays green after every task. Two orderings are deliberate: Task 6 adds the four trace routes to `http_route` while the dispatchers know only `spans` (until Tasks 7 and 8 add `trace`, `trace_query` and `recent`, a request to those routes reaches the old `handle_run` / `handle_delegate` and gets their 400 `bad request`; no test sends one before its task); and Task 10 migrates VT27 in the same commit that makes every forwarded `/run` carry `trace`.

---

### Task 1: Baseline record (orchestrator; no code, no commit)

Implements TRT60's "before any change" half and TRT62's import baseline. Nothing is written into the repository.

**Files:**
- Create (outside git, excluded by `.git/info/exclude`, never staged): `/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-tracing/` with `base-commit.txt`, `baseline-pytest.txt`, `baseline-scripts.txt`, `baseline-imports.txt`.

**Interfaces:** Consumes nothing. Produces the files Task 14 compares against.

- [ ] **Step 1: Confirm the starting point ([VISION] in, nothing of this plan yet).**

```bash
cd /Users/reubenpatterson/local_agent_harness/qwen-agent-workspace
git status --short            # expected: only ?? ../.DS_Store, ?? ../.claude/, ?? ../agent/__pycache__/, ?? ../bin/
grep -c "def remove_stale_image_dirs" bin/qwen-agentd   # expected: 1 ([VISION] is in)
grep -c '"" if _skill_has_no_tools(args_ns) else err_body' bin/qwen-agent   # expected: 2 ([VISION]'s fix wave a704a92 is in)
grep -c "TRACE_FILE_NAME" fleet_lib.py                   # expected: 0 (this plan not started)
ls tests/test_fleet_tracing.py tests/test_qwen_agent_tracing.py 2>&1 | grep -c "No such file"   # expected: 2
ls ~/agents 2>&1 | head -1    # expected: "No such file or directory" (T25 then skips)
shasum -a 256 fleet_lib.py bin/qwen-agentd bin/qwen-agent tests/fleet_testutil.py tests/test_fleet_lib.py tests/test_fleet_vision.py
```

Expected checksums (the tree this plan was tested on, `a704a92`):

```text
264e10fb26dab22b232a94659178f5e09d92ed75f4367d910776d477a2d91c64  fleet_lib.py
afde8463766f10c574a16f49f9a5eb387cf0d1dfa2afd4f47aa1f0c172f19b37  bin/qwen-agentd
fd5fffce606305daaba48d856efe54bde429a40b171477bdeb1ab375b3c2b185  bin/qwen-agent
2e05246bf4a0738d91b49bafe75f50d0e3ce689a8e68f6355be37eca9422276f  tests/fleet_testutil.py
4a120d20683b0c0996a63992d0a001148fdbef95b05f4d174793537997d81615  tests/test_fleet_lib.py
b6ffc1236b7b480460bc38adba97ae1566d2d46dff8d1252a5e998778cbcfc61  tests/test_fleet_vision.py
```

If a checksum differs (a commit landed after `a704a92`), continue: every Edit below locates its old text itself and stops the run if that text is not found exactly once, and the expected test counts below are then compared against Step 2's recorded baseline instead of the literal numbers. Write the differing file names into `baseline-notes.txt` in the directory of Step 2.

- [ ] **Step 2: Record the base commit and the pytest baseline (about 8 min).**

```bash
D=/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-tracing
mkdir -p $D
git rev-parse HEAD > $D/base-commit.txt
python3 -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR|SKIPPED)' $D/baseline-pytest.txt
```

Expected last line: `1 failed, 1214 passed, 1 skipped, 274 warnings in ...`; the `FAILED` line is exactly `FAILED tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike`, and the `SKIPPED` line is `SKIPPED [1] tests/test_fleet_lib.py:272: no fleet.env on this host`. If the counts differ, write the actual ones into `baseline-notes.txt`; Task 14 compares against what was recorded here.

- [ ] **Step 3: Record the plain-python scripts and the import lines.**

```bash
D=/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-tracing
for f in test_qwen_agent_context_budget test_qwen_agent_image_oneshot test_qwen_agent_session_memory; do
  printf '%s: ' "$f"; python3 tests/$f.py 2>&1 | tail -1
done | tee $D/baseline-scripts.txt
grep -h "^import \|^from " fleet_lib.py bin/qwen-agentd > $D/baseline-imports.txt
wc -l < $D/baseline-imports.txt
```

Expected: `test_qwen_agent_context_budget: OK 68/68`, `test_qwen_agent_image_oneshot: OK 25/25`, `test_qwen_agent_session_memory: OK 205/205`; then `35`.

- [ ] **Step 4: Record the suites this plan touches (about 4 min).**

```bash
for f in test_fleet_lib test_fleet_integration test_fleet_vision test_qwen_agent_fleet test_qwen_agent_vision; do
  printf '%s: ' "$f"; python3 -m pytest tests/$f.py -q -p no:cacheprovider 2>&1 | tail -1
done
```

Expected: `test_fleet_lib: 58 passed, 1 skipped`, `test_fleet_integration: 37 passed`, `test_fleet_vision: 13 passed`, `test_qwen_agent_fleet: 10 passed`, `test_qwen_agent_vision: 14 passed` (durations vary).

---

### Task 2: fleet_lib trace constants, IDs, the record schema and its validator

Implements TR1 (the constants), TR2 (`import secrets`), TR3 (IDs), TR4 and TR5 (`_TRACE_KEYS`, `_TRACE_ATTRS`, `make_record`, `trace_record_error`) and TR6 (the sanitizers and `run_status`). Tests TRT1, TRT2, TRT3, TRT4.

**Files:**
- Modify: `fleet_lib.py` — two edits (the import block; after `RUN_TMP_PREFIX`) and one appended block (the new last section).
- Test: `tests/test_fleet_lib.py` — one appended block.

**Interfaces:**
- Consumes: `fleet_lib._is_int`, `HOST_ID_RE`, `REQUEST_ID_RE`, `KNOWN_SKILLS`, `MAX_BODY`, `PEER_HTTP_TIMEOUT`, `canonical_json` (existing).
- Produces in `fleet_lib`: every TR1 constant (`TRACE_FILE_NAME`, `TRACE_SCHEMA`, `RECENT_SCHEMA`, `TRACE_RECORD_VERSION`, `TRACE_KINDS`, `TRACE_POSTED_KINDS`, `TRACE_ENV_ID`, `TRACE_ENV_PARENT`, `TRACE_SPAN_MAX_BYTES`, `TRACE_TEXT_CHARS`, `TRACE_COUNT_MAX`, `TRACE_DUR_MAX_MS`, `TRACE_MAX_RECORDS`, `TRACE_QUERY_MAX_BYTES`, `TRACE_POST_TIMEOUT`, `TRACE_FANOUT_DEADLINE`, `TRACE_QUERY_TIMEOUT`, `TRACE_RECENT_TIMEOUT`, `TRACE_RECENT_DEFAULT`, `TRACE_RECENT_MAX`, `TRACE_CLIENT_MAX_BYTES`, `TRACE_ID_RE`, `SPAN_ID_RE`, `TRACE_NAME_RE`, `TRACE_TOKEN_RE`, `_TRACE_TEXT_BAD_RE`); `valid_trace_id(value) -> bool`; `valid_span_id(value) -> bool`; `new_trace_id() -> str` (32 hex); `new_span_id() -> str` (16 hex); `_TRACE_KEYS`; `_TRACE_ATTRS` (kind -> {attr: type}); `make_record(trace_id, span_id, parent_span_id, agent, kind, name, start, t0, status, attrs, now=None) -> dict` (no `"agent"` key when `agent` is None); `trace_record_error(rec, posted=False) -> None or str` (the first bad field: `record`, `keys`, `v`, `trace_id`, `span_id`, `parent_span_id`, `agent`, `kind`, `name`, `start`, `dur_ms`, `status`, `attrs`, `attrs.<key>`); `trace_name(value) -> str`; `trace_skill(value) -> str`; `trace_token(value) -> str or None`; `trace_count(value) -> int or None`; `run_status(http, envelope_status) -> "ok" | "busy" | "error"`. In `tests/test_fleet_lib.py`: `TR_TRACE`, `TR_SPAN`, `TR_PARENT`, `TR_REQ`, `_tr_attrs(kind)`, `_tr_record(kind="tool", agent="mac-local", **changes)` (used again by Tasks 3-6).

- [ ] **Step 1: Write the failing tests.**

Append to the end of `tests/test_fleet_lib.py` (after its current last line, base line 1626; add two empty lines, then this block, which ends with a newline):

```python
# --- fleet tracing: constants, IDs, the record and its validator (tracing spec TR1-TR6) ---

TR_TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
TR_SPAN = "00f067aa0ba902b7"
TR_PARENT = "53995c3f42cd8ad8"
TR_REQ = "9c1e0b7d2a4f6e83"


def _tr_attrs(kind):
    """One valid attrs object per kind, with exactly the keys of tracing spec TR4."""
    return copy.deepcopy({
        "turn": {"rounds": 2, "tool_calls": 1},
        "model": {"call": 1, "tools": True, "prompt_tokens": 812, "completion_tokens": 64,
                  "finish_reason": "tool_calls", "http": None},
        "tool": {"round": 1, "decision": "approved", "key": "skill=researcher",
                 "outcome": "ok, 912 characters", "error": False},
        "delegate": {"skill": "researcher", "target": "ollama-168", "request_id": TR_REQ, "http": 200,
                     "images": 0},
        "run": {"skill": "researcher", "request_id": TR_REQ, "http": 200, "images": 0, "image_bytes": 0},
        "agent": {"skill": "researcher", "request_id": TR_REQ, "http": 200, "envelope_status": "ok"},
    }[kind])


def _tr_record(kind="tool", agent="mac-local", **changes):
    """A valid stored-form record (posted form when agent is None), then `changes` applied."""
    rec = fleet_lib.make_record(TR_TRACE, TR_SPAN, TR_PARENT, agent, kind, "delegate_to_skill",
                                1760000000.123, 1000.0, "ok", _tr_attrs(kind), now=1001.0)
    rec.update(changes)
    return rec


def test_trt1_trace_constants_and_ids(monkeypatch):
    assert fleet_lib.TRACE_FILE_NAME == "trace.jsonl"
    assert fleet_lib.TRACE_SCHEMA == "qwen-agentd.trace.v1"
    assert fleet_lib.RECENT_SCHEMA == "qwen-agentd.recent.v1"
    assert fleet_lib.TRACE_RECORD_VERSION == 1
    assert fleet_lib.TRACE_KINDS == ("turn", "model", "tool", "delegate", "run", "agent")
    assert fleet_lib.TRACE_POSTED_KINDS == ("turn", "model", "tool")
    assert fleet_lib.TRACE_ENV_ID == "QWEN_AGENT_TRACE_ID"
    assert fleet_lib.TRACE_ENV_PARENT == "QWEN_AGENT_PARENT_SPAN"
    assert fleet_lib.TRACE_SPAN_MAX_BYTES == 8192
    assert fleet_lib.TRACE_TEXT_CHARS == 256
    assert fleet_lib.TRACE_COUNT_MAX == 10 ** 15
    assert fleet_lib.TRACE_DUR_MAX_MS == 10 ** 10
    assert fleet_lib.TRACE_MAX_RECORDS == 2000
    assert fleet_lib.TRACE_QUERY_MAX_BYTES == 1048576 - 4096
    assert fleet_lib.TRACE_POST_TIMEOUT == 2
    assert fleet_lib.TRACE_FANOUT_DEADLINE == 6
    assert fleet_lib.TRACE_QUERY_TIMEOUT == 20
    assert fleet_lib.TRACE_RECENT_TIMEOUT == 5
    assert fleet_lib.TRACE_RECENT_DEFAULT == 10
    assert fleet_lib.TRACE_RECENT_MAX == 100
    assert fleet_lib.TRACE_CLIENT_MAX_BYTES == 33554432
    assert fleet_lib.TRACE_ID_RE.pattern == "[0-9a-f]{32}"
    assert fleet_lib.SPAN_ID_RE.pattern == "[0-9a-f]{16}"
    assert fleet_lib.TRACE_NAME_RE.pattern == "[A-Za-z0-9][A-Za-z0-9_./:@+-]{0,127}"
    assert fleet_lib.TRACE_TOKEN_RE.pattern == "[a-z][a-z_]{0,31}"
    assert fleet_lib._TRACE_TEXT_BAD_RE.pattern == "[\\x00-\\x1f\\x7f]"
    trace_ids = [fleet_lib.new_trace_id() for _ in range(1000)]
    span_ids = [fleet_lib.new_span_id() for _ in range(1000)]
    assert all(fleet_lib.TRACE_ID_RE.fullmatch(t) for t in trace_ids) and len(set(trace_ids)) == 1000
    assert all(fleet_lib.SPAN_ID_RE.fullmatch(s) for s in span_ids) and len(set(span_ids)) == 1000
    for func, nbytes in ((fleet_lib.new_trace_id, 16), (fleet_lib.new_span_id, 8)):
        drawn = ["0" * (2 * nbytes), "ab" * nbytes]
        asked = []
        monkeypatch.setattr(fleet_lib.secrets, "token_hex", lambda n: asked.append(n) or drawn.pop(0))
        assert func() == "ab" * nbytes
        assert asked == [nbytes, nbytes] and drawn == []
    monkeypatch.undo()
    assert fleet_lib.valid_trace_id(TR_TRACE) and fleet_lib.valid_span_id(TR_SPAN)
    for bad in (TR_TRACE.upper(), TR_TRACE[:31], TR_TRACE + "0", "0" * 32, None, 5, TR_TRACE.encode()):
        assert fleet_lib.valid_trace_id(bad) is False, bad
    for bad in (TR_SPAN.upper(), TR_SPAN[:15], TR_SPAN + "0", "0" * 16, None, TR_TRACE):
        assert fleet_lib.valid_span_id(bad) is False, bad


def test_trt2_make_record_per_kind():
    for kind in fleet_lib.TRACE_KINDS:
        rec = fleet_lib.make_record(TR_TRACE, TR_SPAN, None, "mac-local", kind, "researcher",
                                    1760000000.5, 1000.0, "ok", _tr_attrs(kind), now=1000.0 + 1.2345)
        assert rec["dur_ms"] == 1235, kind
        assert rec["agent"] == "mac-local" and rec["v"] == 1
        assert fleet_lib.trace_record_error(rec) is None, kind
        assert json.loads(fleet_lib.canonical_json(rec)) == rec
        posted = fleet_lib.make_record(TR_TRACE, TR_SPAN, TR_PARENT, None, kind, "researcher",
                                       1760000000.5, 1000.0, "ok", _tr_attrs(kind), now=1001.0)
        assert "agent" not in posted
        expected = None if kind in ("turn", "model", "tool") else "kind"
        assert fleet_lib.trace_record_error(posted, posted=True) == expected, kind
    rec = fleet_lib.make_record(TR_TRACE, TR_SPAN, None, "a", "turn", "repl", 1.0, 1000.0, "ok",
                                _tr_attrs("turn"), now=999.0)
    assert rec["dur_ms"] == 0


def _trt3_cases():
    """(mutated record, posted, exact reason) for every TRT3 mutation."""
    def without(key):
        rec = _tr_record()
        del rec[key]
        return rec

    def attrs(**changes):
        a = _tr_attrs("tool")
        a.update(changes)
        return a

    def model_attrs(**changes):
        a = _tr_attrs("model")
        a.update(changes)
        return a

    return [
        ([], False, "record"),
        ("rec", False, "record"),
        (without("status"), False, "keys"),
        (_tr_record(task="secret task"), False, "keys"),
        (_tr_record(), True, "keys"),
        (_tr_record(v=2), False, "v"),
        (_tr_record(v=True), False, "v"),
        (_tr_record(trace_id=TR_TRACE.upper()), False, "trace_id"),
        (_tr_record(trace_id="0" * 32), False, "trace_id"),
        (_tr_record(span_id=TR_SPAN.upper()), False, "span_id"),
        (_tr_record(span_id="0" * 16), False, "span_id"),
        (_tr_record(span_id=TR_SPAN[:15]), False, "span_id"),
        (_tr_record(parent_span_id=TR_SPAN), False, "parent_span_id"),
        (_tr_record(agent="Bad"), False, "agent"),
        (_tr_record("run", agent=None), True, "kind"),
        (_tr_record(name="has space"), False, "name"),
        (_tr_record(start=-1), False, "start"),
        (_tr_record(start=float("nan")), False, "start"),
        (_tr_record(start="1"), False, "start"),
        (_tr_record(start=True), False, "start"),
        (_tr_record(dur_ms=-1), False, "dur_ms"),
        (_tr_record(dur_ms=1.5), False, "dur_ms"),
        (_tr_record(status="OK"), False, "status"),
        (_tr_record(attrs=dict(_tr_attrs("tool"), prompt="p")), False, "attrs"),
        (_tr_record(attrs=attrs(key="k" * 257)), False, "attrs.key"),
        (_tr_record(attrs=attrs(key="line\nbreak")), False, "attrs.key"),
        (_tr_record("model", attrs=model_attrs(prompt_tokens=True)), False, "attrs.prompt_tokens"),
    ]


def test_trt3_trace_record_error_reasons():
    for rec, posted, reason in _trt3_cases():
        assert fleet_lib.trace_record_error(rec, posted=posted) == reason, (reason, rec)
        if isinstance(rec, dict):
            for value in rec.values():
                if isinstance(value, str) and len(value) >= 3:
                    assert value not in reason
    assert fleet_lib.trace_record_error(_tr_record()) is None
    long_key = _tr_record(attrs=dict(_tr_attrs("tool"), key="k" * 256, outcome="é" * 256))
    assert fleet_lib.trace_record_error(long_key) is None


def test_trt4_attribute_schema_has_no_free_text_beyond_tool_key_and_outcome():
    assert fleet_lib._TRACE_ATTRS == {
        "turn": {"rounds": "int", "tool_calls": "int"},
        "model": {"call": "int", "tools": "bool", "prompt_tokens": "int?", "completion_tokens": "int?",
                  "finish_reason": "token?", "http": "int?"},
        "tool": {"round": "int", "decision": "token", "key": "text", "outcome": "text", "error": "bool"},
        "delegate": {"skill": "name", "target": "agent", "request_id": "reqid?", "http": "int?",
                     "images": "int"},
        "run": {"skill": "name", "request_id": "reqid", "http": "int", "images": "int", "image_bytes": "int"},
        "agent": {"skill": "name", "request_id": "reqid", "http": "int", "envelope_status": "token?"},
    }
    text = set((kind, key) for kind, schema in fleet_lib._TRACE_ATTRS.items()
               for key, typ in schema.items() if typ.rstrip("?") == "text")
    assert text == {("tool", "key"), ("tool", "outcome")}
    forbidden = {"task", "prompt", "answer", "messages", "content", "data", "images_data", "token", "text",
                 "result", "arguments"}
    for schema in fleet_lib._TRACE_ATTRS.values():
        assert not (set(schema) & forbidden)
    assert set(fleet_lib._TRACE_ATTRS) == set(fleet_lib.TRACE_KINDS)
    assert fleet_lib.trace_name("qwen38-6bit") == "qwen38-6bit"
    assert fleet_lib.trace_name("has space") == "unknown" and fleet_lib.trace_name(None) == "unknown"
    assert fleet_lib.trace_skill("researcher") == "researcher"
    assert fleet_lib.trace_skill("find the secret plan") == "unknown" and fleet_lib.trace_skill(3) == "unknown"
    assert fleet_lib.trace_token("tool_calls") == "tool_calls"
    assert fleet_lib.trace_token("Stop") is None and fleet_lib.trace_token(None) is None
    assert fleet_lib.trace_count(812) == 812
    for bad in (True, -1, 10 ** 15 + 1, 1.0, "3", None):
        assert fleet_lib.trace_count(bad) is None
    assert fleet_lib.run_status(200, "ok") == "ok"
    assert fleet_lib.run_status(200, "max_rounds") == "error"
    assert fleet_lib.run_status(409, None) == "busy"
    assert fleet_lib.run_status(502, None) == "error"
```

- [ ] **Step 2: Run the new tests to verify they fail.**

```bash
python3 -m pytest tests/test_fleet_lib.py -q -p no:cacheprovider -k "trt1_ or trt2_ or trt3_ or trt4_"
```

Expected: `4 failed, 59 deselected`; every test fails with `AttributeError: module 'fleet_lib' has no attribute ...` (`TRACE_FILE_NAME`, `TRACE_KINDS`, `make_record`, `_TRACE_ATTRS`).

- [ ] **Step 3: Implement.** In `fleet_lib.py`:

Edit 1 of 2 in `fleet_lib.py` (base lines 22-23). Replace:

```python
import re
import threading
```

with:

```python
import re
import secrets
import threading
```

Edit 2 of 2 in `fleet_lib.py` (base line 91). Replace:

```python
RUN_TMP_PREFIX = "images-"    # prefix of each run's directory; stale ones are removed at startup (V19)
```

with:

```python
RUN_TMP_PREFIX = "images-"    # prefix of each run's directory; stale ones are removed at startup (V19)
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

Append to the end of `fleet_lib.py` (after its current last line, base line 1350; add two empty lines, then this block, which ends with a newline):

```python
# ---------------------------------------------------------------------------
# Tracing: IDs, records, the store, the clients and the tree (tracing spec)
# ---------------------------------------------------------------------------

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

- [ ] **Step 4: Run the tests, the whole file and both compilers.**

```bash
python3 -m pytest tests/test_fleet_lib.py -q -p no:cacheprovider -k "trt1_ or trt2_ or trt3_ or trt4_"
python3 -m pytest tests/test_fleet_lib.py -q -p no:cacheprovider
/usr/bin/python3 -m py_compile fleet_lib.py tests/test_fleet_lib.py && python3 -m py_compile fleet_lib.py tests/test_fleet_lib.py && echo compile-ok
```

Expected: `4 passed, 59 deselected`; `62 passed, 1 skipped`; `compile-ok`.

- [ ] **Step 5: Commit.**

```bash
git add fleet_lib.py tests/test_fleet_lib.py
git diff --cached --name-only   # expected: qwen-agent-workspace/fleet_lib.py, qwen-agent-workspace/tests/test_fleet_lib.py
git commit -q -F - <<'EOF'
fleet_lib: trace constants, IDs, record schema and validator, sanitizers (tracing TR1-TR6)

TRT1-TRT4.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 3: fleet_lib propagation helpers, loopback clients and the traced delegate_once

Implements TR7 (`valid_trace_field`, `trace_context`), TR8 (`trace_env_context`, `build_child_env(..., trace=None)`), TR14 (`post_span`, `fetch_trace`, `fetch_recent`, `valid_trace_result`, `valid_recent_result`) and TR15 (`_post_delegate`, `delegate_once(..., trace=None)` with the one retry). Tests TRT5, TRT13.

**Files:**
- Modify: `fleet_lib.py` — two edits (`build_child_env`; the head of `delegate_once`) and one appended block.
- Test: `tests/test_fleet_lib.py` — one appended block.

**Interfaces:**
- Consumes (Task 2): `valid_trace_id`, `valid_span_id`, `new_trace_id`, `trace_record_error`, `TRACE_ENV_ID`, `TRACE_ENV_PARENT`, `TRACE_SCHEMA`, `RECENT_SCHEMA`, `TRACE_KINDS`, `TRACE_NAME_RE`, `TRACE_TOKEN_RE`, `TRACE_POST_TIMEOUT`, `TRACE_QUERY_TIMEOUT`, `TRACE_RECENT_TIMEOUT`, `TRACE_CLIENT_MAX_BYTES`; `TR_TRACE`, `TR_SPAN`, `_tr_record` in the tests; existing `_closed_port`, `_ENVELOPE`, `TEST_FLEET_ID`, `TEST_TOKEN`.
- Produces in `fleet_lib`: `valid_trace_field(obj) -> bool`; `trace_context(field) -> (trace_id, parent_span_id or None)`; `trace_env_context(environ) -> (trace_id, parent_span_id) or None`; `build_child_env(environ, daemon_url, trace=None) -> dict` (strips inherited `QWEN_AGENT_TRACE_ID` / `QWEN_AGENT_PARENT_SPAN`, sets them from `trace`); `_json_loads_or_none(raw)`; `valid_trace_result(obj, trace_id) -> bool`; `_RECENT_KEYS`; `valid_recent_result(obj) -> bool`; `post_span(daemon_url, record, timeout=TRACE_POST_TIMEOUT) -> bool`; `fetch_trace(daemon_url, trace_id) -> (result, None) or (None, message)`; `fetch_recent(daemon_url, n) -> (result, None) or (None, message)`; `_post_delegate(daemon_url, request) -> (status, raw, None) or (None, None, exc type name)`; `delegate_once(daemon_url, skill, task, host_id, images=None, trace=None)`. In the tests: `_TrServer(routes)` with `.url`, `.routes`, `.requests` (method, path, Content-Type, body), `.close()`.

- [ ] **Step 1: Write the failing tests.**

Append to the end of `tests/test_fleet_lib.py` (after its current last line, base line 1814; add two empty lines, then this block, which ends with a newline):

```python
# --- fleet tracing: propagation helpers and loopback clients (tracing spec TR7, TR8, TR14, TR15) ---

def test_trt5_trace_field_context_and_child_env():
    field = {"trace_id": TR_TRACE, "parent_span_id": TR_SPAN}
    assert fleet_lib.valid_trace_field(field) is True
    for bad in (dict(field, extra=1), {"trace_id": TR_TRACE}, None, [], "x",
                {"trace_id": TR_TRACE.upper(), "parent_span_id": TR_SPAN},
                {"trace_id": TR_TRACE, "parent_span_id": "0" * 16},
                {"trace_id": TR_TRACE, "parent_span_id": TR_TRACE}):
        assert fleet_lib.valid_trace_field(bad) is False, bad
    trace_id, parent = fleet_lib.trace_context(None)
    assert fleet_lib.valid_trace_id(trace_id) and parent is None
    assert fleet_lib.trace_context(field) == (TR_TRACE, TR_SPAN)
    env_ok = {"QWEN_AGENT_TRACE_ID": TR_TRACE, "QWEN_AGENT_PARENT_SPAN": TR_SPAN}
    assert fleet_lib.trace_env_context(env_ok) == (TR_TRACE, TR_SPAN)
    for env in ({}, {"QWEN_AGENT_TRACE_ID": TR_TRACE}, {"QWEN_AGENT_PARENT_SPAN": TR_SPAN},
                dict(env_ok, QWEN_AGENT_PARENT_SPAN=TR_SPAN.upper()),
                dict(env_ok, QWEN_AGENT_PARENT_SPAN=TR_SPAN[:15]),
                dict(env_ok, QWEN_AGENT_TRACE_ID="0" * 32)):
        assert fleet_lib.trace_env_context(env) is None, env
    environ = {
        "QWEN_AGENT_FLEET_ID": TEST_FLEET_ID,
        "QWEN_AGENT_FLEET_TOKEN": TEST_TOKEN,
        "SKILL_ENDPOINT_RESEARCHER": "http://192.168.1.168:11434/v1",
        "SKILL_MODEL_RESEARCHER": "qwen3.5:9b",
        "PATH": "/usr/bin:/bin",
        "HOME": "/Users/test",
        "QWEN_AGENT_HOST_ID": "mac-local",
        "QWEN_AGENT_DAEMON_URL": "http://127.0.0.1:1",
        "QWEN_AGENT_TRACE_ID": "1" * 32,
        "QWEN_AGENT_PARENT_SPAN": "2" * 16,
    }
    before = dict(environ)
    for trace in (None, (TR_TRACE, TR_SPAN)):
        env = fleet_lib.build_child_env(environ, "http://127.0.0.1:8190", trace)
        assert environ == before
        for gone in ("QWEN_AGENT_FLEET_ID", "QWEN_AGENT_FLEET_TOKEN", "SKILL_ENDPOINT_RESEARCHER",
                     "SKILL_MODEL_RESEARCHER"):
            assert gone not in env
        for kept in ("PATH", "HOME", "QWEN_AGENT_HOST_ID"):
            assert env[kept] == environ[kept]
        assert env["QWEN_AGENT_DAEMON_URL"] == "http://127.0.0.1:8190"
        assert not any(TEST_TOKEN in v for v in env.values())
        if trace is None:
            assert "QWEN_AGENT_TRACE_ID" not in env and "QWEN_AGENT_PARENT_SPAN" not in env
        else:
            assert (env["QWEN_AGENT_TRACE_ID"], env["QWEN_AGENT_PARENT_SPAN"]) == trace


class _TrServer(object):
    """A loopback server for TRT13: routes[(method, path)] = (status, body bytes, delay s).

    Records (method, path, Content-Type, body) of every request; unknown routes answer 404.
    """

    def __init__(self, routes):
        self.routes = routes
        self.requests = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _serve(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                outer.requests.append((self.command, self.path, self.headers.get("Content-Type"), body))
                status, raw, delay = outer.routes.get((self.command, self.path), (404, b"", 0))
                time.sleep(delay)
                try:
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except OSError:
                    pass

            do_GET = _serve
            do_POST = _serve

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_trt13_post_span_fetch_clients_and_delegate_retry():
    record = _tr_record("tool", agent=None)
    srv = _TrServer({("POST", "/spans"): (200, b'{"ok":true}', 0)})
    try:
        assert fleet_lib.post_span(srv.url, record) is True
        assert srv.requests == [("POST", "/spans", "application/json", fleet_lib.canonical_json(record))]
        srv.routes[("POST", "/spans")] = (500, b"{}", 0)
        assert fleet_lib.post_span(srv.url, record) is False
        srv.routes[("POST", "/spans")] = (200, b'{"ok":true}', 3)
        started = time.monotonic()
        assert fleet_lib.post_span(srv.url, record) is False
        assert time.monotonic() - started < 2.5
    finally:
        srv.close()
    closed = "http://127.0.0.1:%d" % _closed_port()
    assert fleet_lib.post_span(closed, record) is False
    assert fleet_lib.post_span(None, record) is False

    result = {"schema": "qwen-agentd.trace.v1", "trace_id": TR_TRACE, "records": [_tr_record()],
              "missing": [{"agent": "bravo", "reason": "unreachable (timeout)"}],
              "truncated": [{"agent": "alpha", "count": 2000}]}
    recent = {"schema": "qwen-agentd.recent.v1", "agent": "alpha", "traces": [
        {"trace_id": TR_TRACE, "start": 1760000000.123, "dur_ms": 12400, "status": "ok", "kind": "turn",
         "name": "repl", "spans": 5, "delegated": ["researcher@bravo"]}]}
    trace_path, recent_path = "/trace?id=" + TR_TRACE, "/traces/recent?n=3"
    srv = _TrServer({})
    try:
        cases = (
            ((401, b"", 0), "the daemon at %s has no trace support (http 401)" % srv.url),
            ((404, b"", 0), "the daemon at %s has no trace support (http 404)" % srv.url),
            ((500, b"{}", 0), "the daemon at %s answered http 500" % srv.url),
            ((200, b"not json", 0), "the daemon at %s returned an unrecognized trace response" % srv.url),
            ((200, b'{"schema": "qwen-agentd.trace.v1"}', 0),
             "the daemon at %s returned an unrecognized trace response" % srv.url),
        )
        for answer, message in cases:
            srv.routes = {("GET", trace_path): answer, ("GET", recent_path): answer}
            assert fleet_lib.fetch_trace(srv.url, TR_TRACE) == (None, message)
            assert fleet_lib.fetch_recent(srv.url, 3) == (None, message)
        srv.routes = {("GET", trace_path): (200, json.dumps(result).encode(), 0),
                      ("GET", recent_path): (200, json.dumps(recent).encode(), 0)}
        assert fleet_lib.fetch_trace(srv.url, TR_TRACE) == (result, None)
        assert fleet_lib.fetch_recent(srv.url, 3) == (recent, None)
        assert fleet_lib.fetch_trace(srv.url, "1" * 32) == (None, "the daemon at %s has no trace support "
                                                            "(http 404)" % srv.url)
        bad_records = dict(result, records=[dict(_tr_record(), status="BAD")])
        srv.routes[("GET", trace_path)] = (200, json.dumps(bad_records).encode(), 0)
        assert fleet_lib.fetch_trace(srv.url, TR_TRACE)[0] is None
        bad_recent = dict(recent, traces=[dict(recent["traces"][0], spans=True)])
        srv.routes[("GET", recent_path)] = (200, json.dumps(bad_recent).encode(), 0)
        assert fleet_lib.fetch_recent(srv.url, 3)[0] is None
    finally:
        srv.close()
    assert fleet_lib.fetch_trace(closed, TR_TRACE) == (None, "daemon not reachable at %s" % closed)
    assert fleet_lib.fetch_recent(closed, 3) == (None, "daemon not reachable at %s" % closed)

    field = {"trace_id": TR_TRACE, "parent_span_id": TR_SPAN}
    ok = json.dumps({"outcome": "ok", "envelope": _ENVELOPE, "detail": ""}).encode()
    srv = _TrServer({("POST", "/delegate"): (200, ok, 0)})
    try:
        assert fleet_lib.delegate_once(srv.url, "researcher", "t", "h", None, field) == ("ok", _ENVELOPE, "")
        assert [json.loads(r[3]) for r in srv.requests] == [
            {"skill": "researcher", "task": "t", "host_id": "h", "trace": field}]
        del srv.requests[:]
        srv.routes[("POST", "/delegate")] = (400, b'{"error":"bad request"}', 0)
        assert fleet_lib.delegate_once(srv.url, "researcher", "t", "h", trace=field) == \
            ("daemon_error", None, "http 400")
        assert [json.loads(r[3]) for r in srv.requests] == [
            {"skill": "researcher", "task": "t", "host_id": "h", "trace": field},
            {"skill": "researcher", "task": "t", "host_id": "h"}]
        del srv.requests[:]
        srv.routes[("POST", "/delegate")] = (400, b'{"error":"other"}', 0)
        assert fleet_lib.delegate_once(srv.url, "researcher", "t", "h", trace=field) == \
            ("daemon_error", None, "http 400")
        assert len(srv.requests) == 1
        del srv.requests[:]
        srv.routes[("POST", "/delegate")] = (400, b'{"error":"bad request"}', 0)
        assert fleet_lib.delegate_once(srv.url, "researcher", "t", "h") == ("daemon_error", None, "http 400")
        assert [r[3] for r in srv.requests] == [
            fleet_lib.canonical_json({"skill": "researcher", "task": "t", "host_id": "h"})]
    finally:
        srv.close()
```

- [ ] **Step 2: Run the new tests to verify they fail.**

```bash
python3 -m pytest tests/test_fleet_lib.py -q -p no:cacheprovider -k "trt5_ or trt13_"
```

Expected: `2 failed, 63 deselected`; TRT5 fails with `AttributeError: module 'fleet_lib' has no attribute 'valid_trace_field'`, TRT13 with `AttributeError: module 'fleet_lib' has no attribute 'post_span'`.

- [ ] **Step 3: Implement.** In `fleet_lib.py`:

Edit 1 of 2 in `fleet_lib.py` (base lines 611-621). Replace:

```python
def build_child_env(environ, daemon_url):
    """A new env for a /run child: no fleet secrets, no SKILL_* overrides (F54a)."""
    env = {}
    for key, value in environ.items():
        if key.startswith(FLEET_ENV_PREFIX):
            continue
        if key.startswith("SKILL_ENDPOINT_") or key.startswith("SKILL_MODEL_"):
            continue
        env[key] = value
    env["QWEN_AGENT_DAEMON_URL"] = daemon_url
    return env
```

with:

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

Edit 2 of 2 in `fleet_lib.py` (base lines 947-972). Replace:

```python
def delegate_once(daemon_url, skill, task, host_id, images=None):
    """POST /delegate for one named peer -> (outcome, envelope, detail). Never raises (F68).

    images is the wire list (vision spec V10, V20); None sends the three-key body unchanged.
    """
    if daemon_url is None:
        return "daemon_error", None, "no daemon"
    try:
        request = {"skill": skill, "task": task, "host_id": host_id}
        if images is not None:
            request["images"] = images
        body = canonical_json(request)
        conn = http.client.HTTPConnection("127.0.0.1", _loopback_port(daemon_url),
                                          timeout=DELEGATE_CLIENT_TIMEOUT)
        try:
            conn.request("POST", "/delegate", body=body,
                         headers={"Content-Type": "application/json", "Content-Length": str(len(body))})
            resp = conn.getresponse()
            status = resp.status
            raw = resp.read(MAX_BODY + 1)
        finally:
            conn.close()
    except Exception as e:
        return "daemon_error", None, type(e).__name__
    if status != 200:
        return "daemon_error", None, "http %d" % status
```

with:

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

Append to the end of `fleet_lib.py` (after its current last line, base line 1520; add two empty lines, then this block, which ends with a newline):

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


def trace_env_context(environ):
    """(trace_id, parent_span_id) from QWEN_AGENT_TRACE_ID and QWEN_AGENT_PARENT_SPAN when both are valid, else None."""
    trace_id, parent = environ.get(TRACE_ENV_ID, ""), environ.get(TRACE_ENV_PARENT, "")
    if valid_trace_id(trace_id) and valid_span_id(parent):
        return trace_id, parent
    return None


def _json_loads_or_none(raw):
    try:
        return json.loads(raw)
    except (ValueError, RecursionError, TypeError):
        return None


def valid_trace_result(obj, trace_id):
    """True iff obj is a GET /trace?id=<trace_id> result (tracing spec TR14, TR27). Never raises."""
    try:
        if not (isinstance(obj, dict) and obj.get("schema") == TRACE_SCHEMA and obj.get("trace_id") == trace_id):
            return False
        records, missing, truncated = obj.get("records"), obj.get("missing"), obj.get("truncated")
        if not (isinstance(records, list) and all(trace_record_error(r) is None for r in records)):
            return False
        if not (isinstance(missing, list) and all(
                isinstance(m, dict) and set(m) == {"agent", "reason"}
                and isinstance(m["agent"], str) and isinstance(m["reason"], str) for m in missing)):
            return False
        return isinstance(truncated, list) and all(
            isinstance(t, dict) and set(t) == {"agent", "count"}
            and isinstance(t["agent"], str) and _is_int(t["count"]) for t in truncated)
    except Exception:
        return False


_RECENT_KEYS = frozenset(("trace_id", "start", "dur_ms", "status", "kind", "name", "spans", "delegated"))


def valid_recent_result(obj):
    """True iff obj is a GET /traces/recent result (tracing spec TR14, TR28). Never raises."""
    try:
        if not (isinstance(obj, dict) and obj.get("schema") == RECENT_SCHEMA
                and isinstance(obj.get("agent"), str) and HOST_ID_RE.fullmatch(obj["agent"])
                and isinstance(obj.get("traces"), list)):
            return False
        for t in obj["traces"]:
            if not (isinstance(t, dict) and set(t) == _RECENT_KEYS and valid_trace_id(t["trace_id"])
                    and (_is_int(t["start"]) or isinstance(t["start"], float))
                    and _is_int(t["dur_ms"]) and _is_int(t["spans"])
                    and isinstance(t["status"], str) and TRACE_TOKEN_RE.fullmatch(t["status"])
                    and isinstance(t["kind"], str) and t["kind"] in TRACE_KINDS
                    and isinstance(t["name"], str) and TRACE_NAME_RE.fullmatch(t["name"])
                    and isinstance(t["delegated"], list) and all(isinstance(d, str) for d in t["delegated"])):
                return False
        return True
    except Exception:
        return False


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

- [ ] **Step 4: Run the tests, the whole file and both compilers.**

```bash
python3 -m pytest tests/test_fleet_lib.py -q -p no:cacheprovider -k "trt5_ or trt13_"
python3 -m pytest tests/test_fleet_lib.py -q -p no:cacheprovider
/usr/bin/python3 -m py_compile fleet_lib.py tests/test_fleet_lib.py && python3 -m py_compile fleet_lib.py tests/test_fleet_lib.py && echo compile-ok
```

Expected: `2 passed, 63 deselected`; `64 passed, 1 skipped`; `compile-ok`. (TRT13's slow server holds about 3 s.)

- [ ] **Step 5: Commit.**

```bash
git add fleet_lib.py tests/test_fleet_lib.py
git diff --cached --name-only   # expected: qwen-agent-workspace/fleet_lib.py, qwen-agent-workspace/tests/test_fleet_lib.py
git commit -q -F - <<'EOF'
fleet_lib: trace field and env helpers, loopback trace clients, traced delegate_once with retry (tracing TR7, TR8, TR14, TR15)

TRT5, TRT13.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 4: TraceStore: exact-byte rotation, capped queries, the recent list

Implements TR10 (files, rotation, locking, modes, skipped bad lines), TR11 (`query` with its record and byte caps) and TR12 (`recent`). Tests TRT9, TRT10, TRT11.

**Files:**
- Modify: `fleet_lib.py` — one appended block.
- Test: `tests/test_fleet_lib.py` — one appended block.

**Interfaces:**
- Consumes (Tasks 2, 3): `trace_record_error`, `canonical_json`, `_json_loads_or_none`, `make_record`, `new_span_id`, `TRACE_FILE_NAME`, `TRACE_MAX_RECORDS`, `TRACE_QUERY_MAX_BYTES`, `LOG_MAX_BYTES`, `LOG_BACKUPS`, `KNOWN_SKILLS`; `_tr_attrs`, `TR_PARENT` in the tests.
- Produces in `fleet_lib`: `TraceStore(directory, max_bytes=LOG_MAX_BYTES, backups=LOG_BACKUPS)` with `.path` (`<directory>/trace.jsonl`), `.append(record)` (raises `ValueError("bad trace record: <field>")`, or `OSError` when the directory cannot be written), `.query(trace_id, max_records=TRACE_MAX_RECORDS, max_bytes=TRACE_QUERY_MAX_BYTES) -> (records, truncated)`, `.recent(n) -> [{"trace_id", "start", "dur_ms", "status", "kind", "name", "spans", "delegated"}]`. Construction does no I/O. In the tests: `TR_TRACES`, `_tr_span(trace_id, kind="tool", parent=TR_PARENT, start=..., agent="alpha", name="calculate", status="ok", attrs=None, span_id=None)`, `_tr_lines(path)`.

- [ ] **Step 1: Write the failing tests.**

Append to the end of `tests/test_fleet_lib.py` (after its current last line, base line 1988; add two empty lines, then this block, which ends with a newline):

```python
# --- fleet tracing: the trace store (tracing spec TR10-TR12) ---

TR_TRACES = ("1" * 32, "2" * 32, "3" * 32)


def _tr_span(trace_id, kind="tool", parent=TR_PARENT, start=1760000000.0, agent="alpha", name="calculate",
             status="ok", attrs=None, span_id=None):
    """A valid stored record with a fresh span ID unless one is given."""
    return fleet_lib.make_record(trace_id, span_id or fleet_lib.new_span_id(), parent, agent, kind, name, start,
                                 1000.0, status, attrs if attrs is not None else _tr_attrs(kind), now=1001.0)


def _tr_lines(path):
    with open(path, "rb") as f:
        return f.read().splitlines()


def test_trt9_store_rotation_modes_query_and_concurrency(tmp_path):
    store = fleet_lib.TraceStore(str(tmp_path), max_bytes=2000, backups=3)
    assert os.listdir(str(tmp_path)) == []
    appended = []
    for i in range(60):
        rec = _tr_span(TR_TRACES[i % 3], start=1760000000.0 + i)
        store.append(rec)
        appended.append(rec)
    base = os.path.join(str(tmp_path), "trace.jsonl")
    assert sorted(os.listdir(str(tmp_path))) == ["trace.jsonl", "trace.jsonl.1", "trace.jsonl.2", "trace.jsonl.3"]
    for name in os.listdir(str(tmp_path)):
        path = os.path.join(str(tmp_path), name)
        assert os.path.getsize(path) <= 2000, name
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600, name
    kept = [json.loads(line) for name in (base + ".3", base + ".2", base + ".1", base) for line in _tr_lines(name)]
    assert kept == appended[-len(kept):] and len(kept) < 60
    assert appended[0] not in kept
    for trace_id in TR_TRACES:
        records, truncated = store.query(trace_id)
        assert truncated is False
        assert records == [r for r in kept if r["trace_id"] == trace_id] and records
    with open(base + ".2", "ab") as f:
        f.write(b"garbage line\n" + fleet_lib.canonical_json(appended[-1])[:40] + b"\n")
    records, _truncated = store.query(TR_TRACES[0])
    assert records == [r for r in kept if r["trace_id"] == TR_TRACES[0]]
    before = [(n, os.path.getsize(os.path.join(str(tmp_path), n))) for n in sorted(os.listdir(str(tmp_path)))]
    with pytest.raises(ValueError) as e:
        store.append(dict(appended[0], status="OK"))
    assert str(e.value) == "bad trace record: status"
    assert [(n, os.path.getsize(os.path.join(str(tmp_path), n))) for n in sorted(os.listdir(str(tmp_path)))] == before

    other = tmp_path / "threads"
    other.mkdir()
    shared = fleet_lib.TraceStore(str(other))

    def writer(k):
        for i in range(200):
            shared.append(_tr_span(TR_TRACES[k % 3], start=1760000000.0 + i))

    threads = [threading.Thread(target=writer, args=(k,)) for k in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    lines = _tr_lines(str(other / "trace.jsonl"))
    assert len(lines) == 1600
    assert all(fleet_lib.trace_record_error(json.loads(line)) is None for line in lines)


def test_trt10_query_caps(tmp_path):
    store = fleet_lib.TraceStore(str(tmp_path))
    records = [_tr_span(TR_TRACES[0], start=1760000000.0 + i) for i in range(2001)]
    for rec in records[:2000]:
        store.append(rec)
    assert store.query(TR_TRACES[0]) == (records[:2000], False)
    store.append(records[2000])
    assert store.query(TR_TRACES[0]) == (records[:2000], True)
    ten = sum(len(fleet_lib.canonical_json(r)) + 1 for r in records[:10])
    assert store.query(TR_TRACES[0], max_bytes=ten) == (records[:10], True)
    assert store.query(TR_TRACES[1]) == ([], False)


def test_trt11_recent_lists_roots_with_their_delegations(tmp_path):
    store = fleet_lib.TraceStore(str(tmp_path))
    a, b, c, d = TR_TRACES + ("4" * 32,)
    turn_a = _tr_span(a, "turn", None, 1760000300.0, name="repl")
    tool_a = _tr_span(a, "tool", turn_a["span_id"], 1760000301.0, name="delegate_to_skill",
                      attrs=dict(_tr_attrs("tool"), key="skill=investigator"))
    deleg_bravo = _tr_span(a, "delegate", tool_a["span_id"], 1760000302.0, name="investigator",
                           attrs=dict(_tr_attrs("delegate"), skill="investigator", target="bravo"))
    tool_a2 = _tr_span(a, "tool", turn_a["span_id"], 1760000303.0, name="delegate_to_skill",
                       attrs=dict(_tr_attrs("tool"), key="skill=analyst"))
    deleg_charlie = _tr_span(a, "delegate", tool_a2["span_id"], 1760000304.0, name="analyst", status="busy",
                             attrs=dict(_tr_attrs("delegate"), skill="analyst", target="charlie"))
    turn_b = _tr_span(b, "turn", None, 1760000200.0, name="oneshot")
    tool_b = _tr_span(b, "tool", turn_b["span_id"], 1760000201.0, name="delegate_to_skill",
                      attrs=dict(_tr_attrs("tool"), key="skill=analyst"))
    model_b = _tr_span(b, "model", turn_b["span_id"], 1760000202.0, name="m")
    turn_c = _tr_span(c, "turn", None, 1760000100.0, name="repl", status="max_rounds")
    run_d = _tr_span(d, "run", TR_PARENT, 1760000400.0, name="researcher")
    for rec in (turn_c, run_d, turn_b, tool_b, model_b, deleg_charlie, turn_a, tool_a, deleg_bravo, tool_a2):
        store.append(rec)
    entries = store.recent(10)
    assert [e["trace_id"] for e in entries] == [a, b, c]
    assert entries[0] == {"trace_id": a, "start": 1760000300.0, "dur_ms": 1000, "status": "ok", "kind": "turn",
                          "name": "repl", "spans": 5, "delegated": ["investigator@bravo", "analyst@charlie"]}
    assert (entries[1]["spans"], entries[1]["delegated"], entries[1]["name"]) == (3, ["analyst@alpha"], "oneshot")
    assert (entries[2]["spans"], entries[2]["delegated"], entries[2]["status"]) == (1, [], "max_rounds")
    assert store.recent(1) == entries[:1]
    assert fleet_lib.TraceStore(str(tmp_path / "absent")).recent(10) == []
```

- [ ] **Step 2: Run the new tests to verify they fail.**

```bash
python3 -m pytest tests/test_fleet_lib.py -q -p no:cacheprovider -k "trt9_ or trt10_ or trt11_"
```

Expected: `3 failed, 65 deselected`; each fails with `AttributeError: module 'fleet_lib' has no attribute 'TraceStore'`.

- [ ] **Step 3: Implement.** In `fleet_lib.py`:

Append to the end of `fleet_lib.py` (after its current last line, base line 1649; add two empty lines, then this block, which ends with a newline):

```python
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

- [ ] **Step 4: Run the tests, the whole file and both compilers.**

```bash
python3 -m pytest tests/test_fleet_lib.py -q -p no:cacheprovider -k "trt9_ or trt10_ or trt11_"
python3 -m pytest tests/test_fleet_lib.py -q -p no:cacheprovider
/usr/bin/python3 -m py_compile fleet_lib.py tests/test_fleet_lib.py && python3 -m py_compile fleet_lib.py tests/test_fleet_lib.py && echo compile-ok
```

Expected: `3 passed, 65 deselected`; `67 passed, 1 skipped`; `compile-ok`.

- [ ] **Step 5: Commit.**

```bash
git add fleet_lib.py tests/test_fleet_lib.py
git diff --cached --name-only   # expected: qwen-agent-workspace/fleet_lib.py, qwen-agent-workspace/tests/test_fleet_lib.py
git commit -q -F - <<'EOF'
fleet_lib: TraceStore with exact-byte rotation, capped query and recent roots (tracing TR10-TR12)

TRT9-TRT11.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 5: Merging peer answers and rendering the tree and the recent table

Implements TR13 (`peer_trace_result`, `merge_records`), TR16 (`fmt_ms`, `_span_line`), TR17 (`render_trace`, `_placeholder_agent`) and TR18 (`render_recent`). Tests TRT7, TRT8, TRT12, TRT14.

**Files:**
- Modify: `fleet_lib.py` — one appended block.
- Test: `tests/test_fleet_lib.py` — one appended block.

**Interfaces:**
- Consumes (Tasks 2, 3): `trace_record_error`, `_json_loads_or_none`; `TR_TRACE`, `TR_REQ` in the tests.
- Produces in `fleet_lib`: `peer_trace_result(trace_id, host_id, status, raw, reason) -> (records, missing_reason or None, truncated_count or None)`; `merge_records(records) -> list` (first of a duplicate `span_id` wins, sorted by `(start, agent, span_id)`); `fmt_ms(ms) -> str`; `render_trace(result, localtime=time.localtime) -> [str]`; `render_recent(traces, localtime=time.localtime) -> [str]`. In the tests: `TR_T0`, `_tr_example()` (the eight TR16 records), `_TR16_LINES`, `_tr_result(records, missing=(), truncated=())`.

- [ ] **Step 1: Write the failing tests.**

Append to the end of `tests/test_fleet_lib.py` (after its current last line, base line 2097; add two empty lines, then this block, which ends with a newline):

```python
# --- fleet tracing: merging peer answers and rendering (tracing spec TR13, TR16-TR18) ---

TR_T0 = 1792245802.0   # 2026-10-17 14:03:22 UTC, the start of the TR16 example's turn


def _tr_example():
    """The eight records of the TR16 example; ollama-168's clock runs 30 s behind mac-local's."""
    def rec(span_id, parent, agent, kind, name, start, dur_ms, attrs, status="ok"):
        return {"v": 1, "trace_id": TR_TRACE, "span_id": span_id, "parent_span_id": parent, "agent": agent,
                "kind": kind, "name": name, "start": start, "dur_ms": dur_ms, "status": status, "attrs": attrs}

    req = TR_REQ
    return [
        rec("1000000000000001", None, "mac-local", "turn", "repl", TR_T0, 12400,
            {"rounds": 2, "tool_calls": 1}),
        rec("1000000000000002", "1000000000000001", "mac-local", "model", "qwen38-6bit", TR_T0 + 0.01, 1900,
            {"call": 1, "tools": True, "prompt_tokens": 812, "completion_tokens": 64,
             "finish_reason": "tool_calls", "http": None}),
        rec("1000000000000003", "1000000000000001", "mac-local", "tool", "delegate_to_skill", TR_T0 + 1.95, 8600,
            {"round": 1, "decision": "approved", "key": "skill=researcher", "outcome": "ok, 912 characters",
             "error": False}),
        rec("1000000000000004", "1000000000000003", "mac-local", "delegate", "researcher", TR_T0 + 2.0, 8500,
            {"skill": "researcher", "target": "ollama-168", "request_id": req, "http": 200, "images": 0}),
        rec("2000000000000001", "1000000000000004", "ollama-168", "run", "researcher", TR_T0 + 2.1 - 30, 8300,
            {"skill": "researcher", "request_id": req, "http": 200, "images": 0, "image_bytes": 0}),
        rec("2000000000000002", "2000000000000001", "ollama-168", "agent", "researcher", TR_T0 + 2.1 - 30, 8300,
            {"skill": "researcher", "request_id": req, "http": 200, "envelope_status": "ok"}),
        rec("2000000000000003", "2000000000000002", "ollama-168", "model", "qwen3.5:9b", TR_T0 + 2.5 - 30, 6800,
            {"call": 1, "tools": True, "prompt_tokens": 402, "completion_tokens": 188, "finish_reason": "stop",
             "http": None}),
        rec("1000000000000005", "1000000000000001", "mac-local", "model", "qwen38-6bit", TR_T0 + 10.6, 1800,
            {"call": 2, "tools": True, "prompt_tokens": 1290, "completion_tokens": 140, "finish_reason": "stop",
             "http": None}),
    ]


_TR16_LINES = [
    "trace 4bf92f3577b3  2026-10-17 14:03:22  12.4s  agents: mac-local, ollama-168  spans: 8",
    "turn repl  12.4s  ok  rounds=2  tools=1  @mac-local",
    "  model qwen38-6bit  1.9s  ok  812→64 tok  tool_calls  @mac-local",
    "  tool delegate_to_skill  skill=researcher  8.6s  ok  -> ok, 912 characters  @mac-local",
    "    delegate researcher -> ollama-168  req=9c1e0b7d2a4f6e83  http=200  8.5s  ok  @mac-local",
    "      run researcher  req=9c1e0b7d2a4f6e83  http=200  8.3s  ok  @ollama-168",
    "        agent researcher  req=9c1e0b7d2a4f6e83  http=200  8.3s  ok  @ollama-168",
    "          model qwen3.5:9b  6.8s  ok  402→188 tok  stop  @ollama-168",
    "  model qwen38-6bit  1.8s  ok  1290→140 tok  stop  @mac-local",
]


def _tr_result(records, missing=(), truncated=()):
    return {"schema": "qwen-agentd.trace.v1", "trace_id": TR_TRACE, "records": list(records),
            "missing": list(missing), "truncated": list(truncated)}


def test_trt7_render_trace_matches_the_example_despite_skew():
    records = _tr_example()
    assert all(fleet_lib.trace_record_error(r) is None for r in records)
    assert fleet_lib.render_trace(_tr_result(records), localtime=time.gmtime) == _TR16_LINES
    assert fleet_lib.render_trace(_tr_result(reversed(records)), localtime=time.gmtime) == _TR16_LINES
    for ms, shown in ((0, "0ms"), (999, "999ms"), (1000, "1.0s"), (12449, "12.4s"), (None, "-")):
        assert fleet_lib.fmt_ms(ms) == shown


def test_trt8_orphans_warnings_cycles_and_depth():
    records = _tr_example()
    no_run = [r for r in records if r["kind"] != "run"]
    lines = fleet_lib.render_trace(_tr_result(no_run), localtime=time.gmtime)
    i = lines.index("… span 2000000000000001 on ollama-168 (not retrieved)")
    assert lines[i + 1] == "  agent researcher  req=9c1e0b7d2a4f6e83  http=200  8.3s  ok  @ollama-168"
    assert lines[i + 2] == "    model qwen3.5:9b  6.8s  ok  402→188 tok  stop  @ollama-168"
    assert lines[4] == "    delegate researcher -> ollama-168  req=9c1e0b7d2a4f6e83  http=200  8.5s  ok  @mac-local"
    no_delegate = [r for r in records if r["kind"] != "delegate"]
    for missing, where in (([{"agent": "bravo", "reason": "unreachable (timeout)"}], "bravo"),
                           ([], "?"),
                           ([{"agent": "bravo", "reason": "bad response"},
                             {"agent": "charlie", "reason": "unreachable (timeout)"}], "?")):
        lines = fleet_lib.render_trace(_tr_result(no_delegate, missing), localtime=time.gmtime)
        assert "… span 1000000000000004 on %s (not retrieved)" % where in lines
    lines = fleet_lib.render_trace(_tr_result(
        no_run, [{"agent": "charlie", "reason": "not in the registry"},
                 {"agent": "bravo", "reason": "unreachable (connection refused)"}],
        [{"agent": "ollama-168", "count": 2000}, {"agent": "alpha", "count": 7}]), localtime=time.gmtime)
    assert lines[1:5] == ["! bravo: unreachable (connection refused)", "! charlie: not in the registry",
                          "(truncated: alpha returned the first 7 records)",
                          "(truncated: ollama-168 returned the first 2000 records)"]
    no_root = [r for r in records if r["kind"] != "turn"]
    lines = fleet_lib.render_trace(_tr_result(no_root), localtime=time.gmtime)
    assert lines[0] == "trace 4bf92f3577b3  2026-10-17 14:02:54  -  agents: mac-local, ollama-168  spans: 7"
    assert fleet_lib.render_trace(_tr_result([]), localtime=time.gmtime) == [
        "trace 4bf92f3577b3  -  -  agents: none  spans: 0"]
    a = dict(records[1], span_id="3000000000000001", parent_span_id="3000000000000002")
    b = dict(records[1], span_id="3000000000000002", parent_span_id="3000000000000001", start=TR_T0 + 1)
    lines = fleet_lib.render_trace(_tr_result([a, b]), localtime=time.gmtime)
    assert len(lines) == 3 and sum("model qwen38-6bit" in line for line in lines) == 2
    chain, parent = [], None
    for i in range(3000):
        span = "%016x" % (i + 1)
        chain.append(dict(records[1], span_id=span, parent_span_id=parent, start=TR_T0 + i))
        parent = span
    lines = fleet_lib.render_trace(_tr_result(chain), localtime=time.gmtime)
    assert len(lines) == 3001 and lines[-1].startswith("  " * 2999 + "model ")


def test_trt12_peer_trace_result_and_merge():
    records = _tr_example()
    peer = [r for r in records if r["agent"] == "ollama-168"]

    def body(obj):
        return json.dumps(obj).encode()

    good = {"agent": "ollama-168", "trace_id": TR_TRACE, "records": peer, "truncated": False}
    assert fleet_lib.peer_trace_result(TR_TRACE, "ollama-168", None, None, "unreachable (timeout)") == \
        ([], "unreachable (timeout)", None)
    assert fleet_lib.peer_trace_result(TR_TRACE, "ollama-168", 404, b"{}", None) == \
        ([], "no trace support (http 404)", None)
    assert fleet_lib.peer_trace_result(TR_TRACE, "ollama-168", 500, b"{}", None) == ([], "error (http 500)", None)
    for bad in (b"not json", body(dict(good, agent="bravo")), body(dict(good, trace_id="1" * 32)),
                body(dict(good, truncated=1)), body(dict(good, records={}))):
        assert fleet_lib.peer_trace_result(TR_TRACE, "ollama-168", 200, bad, None) == ([], "bad response", None)
    assert fleet_lib.peer_trace_result(TR_TRACE, "ollama-168", 200, body(good), None) == (peer, None, None)
    mixed = dict(good, records=peer + [records[0], dict(peer[0], trace_id="1" * 32, span_id="5" * 16),
                                       dict(peer[1], status="BAD", span_id="6" * 16)], truncated=True)
    assert fleet_lib.peer_trace_result(TR_TRACE, "ollama-168", 200, body(mixed), None) == (peer, None, 6)
    dup = dict(records[0], start=TR_T0 + 99)
    merged = fleet_lib.merge_records([records[7], records[0], dup] + peer)
    assert merged == sorted([records[7], records[0]] + peer, key=lambda r: (r["start"], r["agent"], r["span_id"]))
    assert dup not in merged


def test_trt14_render_recent_table():
    traces = [
        {"trace_id": TR_TRACE, "start": TR_T0, "dur_ms": 12400, "status": "ok", "kind": "turn", "name": "repl",
         "spans": 5, "delegated": ["researcher@ollama-168", "analyst@mac-local"]},
        {"trace_id": "1" * 32, "start": TR_T0 - 3600, "dur_ms": 850, "status": "max_rounds", "kind": "turn",
         "name": "oneshot", "spans": 12, "delegated": []},
    ]
    assert fleet_lib.render_recent(traces, localtime=time.gmtime) == [
        "time                 trace id                               dur  status        spans  delegated",
        "2026-10-17 14:03:22  4bf92f3577b34da6a3ce929d0e0e4736     12.4s  ok                5  "
        "researcher@ollama-168, analyst@mac-local",
        "2026-10-17 13:03:22  11111111111111111111111111111111     850ms  max_rounds       12  -",
    ]
    assert fleet_lib.render_recent([], localtime=time.gmtime) == [
        "time                 trace id                               dur  status        spans  delegated"]
```

- [ ] **Step 2: Run the new tests to verify they fail.**

```bash
python3 -m pytest tests/test_fleet_lib.py -q -p no:cacheprovider -k "trt7_ or trt8_ or trt12_ or trt14_"
```

Expected: `4 failed, 68 deselected`; `AttributeError: module 'fleet_lib' has no attribute 'render_trace'` (TRT7, TRT8), `... 'peer_trace_result'` (TRT12), `... 'render_recent'` (TRT14).

- [ ] **Step 3: Implement.** In `fleet_lib.py` (the two glyphs are U+2026 and U+2192, written as UTF-8 characters, exactly as shown):

Append to the end of `fleet_lib.py` (after its current last line, base line 1760; add two empty lines, then this block, which ends with a newline):

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

- [ ] **Step 4: Run the tests, the whole file and both compilers.**

```bash
python3 -m pytest tests/test_fleet_lib.py -q -p no:cacheprovider -k "trt7_ or trt8_ or trt12_ or trt14_"
python3 -m pytest tests/test_fleet_lib.py -q -p no:cacheprovider
/usr/bin/python3 -m py_compile fleet_lib.py tests/test_fleet_lib.py && python3 -m py_compile fleet_lib.py tests/test_fleet_lib.py && echo compile-ok
```

Expected: `4 passed, 68 deselected`; `71 passed, 1 skipped`; `compile-ok`.

- [ ] **Step 5: Commit.**

```bash
git add fleet_lib.py tests/test_fleet_lib.py
git diff --cached --name-only   # expected: qwen-agent-workspace/fleet_lib.py, qwen-agent-workspace/tests/test_fleet_lib.py
git commit -q -F - <<'EOF'
fleet_lib: peer trace merge, tree and recent-table renderers (tracing TR13, TR16-TR18)

TRT7, TRT8, TRT12, TRT14.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 6: Daemon POST /spans, the trace routes and the /spans body cap

Implements TR9 (`_ROUTES`, `http_route`, `body_cap`), TR20's path plumbing and the `spans` branch, TR21 (`trace_store`, `record_span`, `_trace_write_failed`) and TR22 (`handle_spans`). Tests TRT6, TRT46, Review Focus 1.

**Files:**
- Modify: `fleet_lib.py` — three edits (`_ROUTES`, `http_route`, `body_cap`).
- Modify: `bin/qwen-agentd` — four edits (the two dispatcher calls in `_handle`; `Daemon.__init__`; `signed_endpoint` / `loopback_endpoint` plus the new tracing methods).
- Test: `tests/test_fleet_lib.py` — one appended block; `tests/fleet_testutil.py` — one appended block; `tests/test_fleet_tracing.py` — create.

**Interfaces:**
- Consumes (Tasks 2-5): `TraceStore`, `make_record`, `trace_record_error`, `TRACE_SPAN_MAX_BYTES`, `TRACE_FILE_NAME`, `render_trace`, `new_span_id`; existing `fleet_lib.log_dir`, `_json_or_none`, `LOG`, `Daemon._warn_lock`, `ftu.Fleet`, `ftu._request`, `ftu.raw_request`, `ftu.daemon_log_dir`.
- Produces: `fleet_lib.http_route` returns `("loopback", "spans")`, `("signed", "trace")`, `("loopback", "trace_query")`, `("loopback", "recent")` for the trace routes; `fleet_lib.body_cap("loopback", "spans") == 8192`. In `bin/qwen-agentd`: `Daemon.signed_endpoint(name, body, path)`, `Daemon.loopback_endpoint(name, body, path)`, `Daemon.trace_store`, `Daemon._trace_warned`, `Daemon.record_span(trace_id, span_id, parent_span_id, kind, name, start, t0, status, attrs)` (never raises), `Daemon._trace_write_failed(e)` (one WARNING per process), `Daemon.handle_spans(body) -> (status, object)`. In `tests/fleet_testutil.py`: `trace_files(home, host_id) -> [path]`, `read_records(home, host_id) -> [record]`. In `tests/test_fleet_tracing.py`: `T`, `P`, `_span(kind="tool", trace_id=T, parent=P, name="calculate", status="ok", attrs=None, start=None)` (a `/spans`-form record), `_post_span(port, record, headers=None) -> (status, body)`, `_alpha(tmp_path, **kwargs) -> Fleet`.

- [ ] **Step 1: Write the failing tests.**

Append to the end of `tests/test_fleet_lib.py` (after its current last line, base line 2243; add two empty lines, then this block, which ends with a newline):

```python
# --- fleet tracing: routes and the /spans body cap (tracing spec TR9) ---

def test_trt6_trace_routes_and_spans_cap():
    assert fleet_lib.http_route("POST", "/spans") == ("loopback", "spans")
    for path in ("/trace/" + TR_TRACE, "/trace/x"):
        assert fleet_lib.http_route("GET", path) == ("signed", "trace")
    for path in ("/trace?id=x", "/trace"):
        assert fleet_lib.http_route("GET", path) == ("loopback", "trace_query")
    for path in ("/traces/recent", "/traces/recent?n=3"):
        assert fleet_lib.http_route("GET", path) == ("loopback", "recent")
    for method, path in (("POST", "/trace/x"), ("GET", "/traces"), ("GET", "/spans"),
                         ("GET", "/run"), ("POST", "/health"), ("GET", "/peers/"),
                         ("PUT", "/peers"), ("GET", "/health?x=1"), ("GET", "/nowhere")):
        assert fleet_lib.http_route(method, path) == ("unknown", None), (method, path)
    assert fleet_lib.body_cap("loopback", "spans") == 8192
    assert fleet_lib.body_cap("signed", "run") == fleet_lib.MAX_IMAGE_BODY
    assert fleet_lib.body_cap("loopback", "delegate") == fleet_lib.MAX_IMAGE_BODY
    for kind, name in (("signed", "health"), ("signed", "skills"), ("loopback", "peers"), ("unknown", None),
                       ("signed", "trace"), ("loopback", "trace_query"), ("loopback", "recent")):
        assert fleet_lib.body_cap(kind, name) == fleet_lib.MAX_BODY, (kind, name)
```

Append to the end of `tests/fleet_testutil.py` (after its current last line, base line 518; add two empty lines, then this block, which ends with a newline):

```python
# --- tracing (docs/superpowers/specs/2026-10-17-fleet-tracing-design.md, Section 6.2) ---------

def trace_files(home, host_id):
    """Sorted paths of trace.jsonl* in the agent's log directory under HOME=home."""
    d = daemon_log_dir(home, host_id)
    if not os.path.isdir(d):
        return []
    return sorted(os.path.join(d, n) for n in os.listdir(d) if n.startswith(fleet_lib.TRACE_FILE_NAME))


def read_records(home, host_id):
    """Every line of the agent's trace files, oldest file first, json.loads'd."""
    paths = trace_files(home, host_id)
    current = [p for p in paths if p.endswith(fleet_lib.TRACE_FILE_NAME)]
    backups = sorted((p for p in paths if p not in current), key=lambda p: -int(p.rsplit(".", 1)[1]))
    records = []
    for path in backups + current:
        with open(path, encoding="utf-8") as f:
            records.extend(json.loads(line) for line in f if line.strip())
    return records
```

Create `tests/test_fleet_tracing.py` with exactly this content (it ends with a newline):

```python
"""Fleet tracing tests for bin/qwen-agentd and the real harness (tracing spec Section 6.5).

Run from the workspace root: python3 -m pytest tests/test_fleet_tracing.py -v
Loopback only. Every daemon runs with --timing-scale 0.1, explicit beacon targets and
HOME=<tmp dir>; the autouse fixture SIGKILLs every process group a test started and
stops every stub server. Every harness run gets QWEN_AGENT_DAEMON_URL explicitly, so no
test contacts a qwen-agentd running on this machine or a real model server.
"""

import base64
import http.server
import json
import os
import re
import stat
import subprocess
import sys
import threading
import time

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
import fleet_lib  # noqa: E402
import fleet_testutil as ftu  # noqa: E402


@pytest.fixture(autouse=True)
def _reap_processes():
    yield
    ftu.kill_all()


T = "4bf92f3577b34da6a3ce929d0e0e4736"
P = "53995c3f42cd8ad8"


def _span(kind="tool", trace_id=T, parent=P, name="calculate", status="ok", attrs=None, start=None):
    """A valid /spans-form record (no "agent") with a fresh span ID."""
    attrs = attrs if attrs is not None else {
        "turn": {"rounds": 1, "tool_calls": 0},
        "model": {"call": 1, "tools": True, "prompt_tokens": 3, "completion_tokens": 4,
                  "finish_reason": "stop", "http": None},
        "tool": {"round": 1, "decision": "approved", "key": "2+2", "outcome": "OK: 4", "error": False},
    }[kind]
    start = round(time.time(), 3) if start is None else start
    return fleet_lib.make_record(trace_id, fleet_lib.new_span_id(), parent, None, kind, name, start,
                                 time.monotonic(), status, attrs)


def _post_span(port, record, headers=None):
    """(status, body bytes) of loopback POST /spans with a JSON body."""
    body = record if isinstance(record, bytes) else fleet_lib.canonical_json(record)
    status, _h, raw = ftu._request(port, "POST", "/spans", body,
                                   headers or {"Content-Type": "application/json"}, timeout=10)
    return status, raw


def _alpha(tmp_path, **kwargs):
    """One running daemon 'alpha' (no skills, no beacons) -> the Fleet."""
    return ftu.Fleet(tmp_path, names=("alpha",), **kwargs).start()


# --- POST /spans (TR9, TR21, TR22) -----------------------------------------------------

def test_trt46_post_spans_validation_cap_and_store(tmp_path):
    fleet = _alpha(tmp_path)
    port, home = fleet.ports["alpha"], fleet.homes["alpha"]
    assert ftu.raw_request(port, "POST", "/spans", {"Content-Type": "application/json",
                                                    "Content-Length": "8193"}) == (413, b"")
    assert _post_span(port, b"not json") == (400, b'{"error":"bad span: record"}')
    run = fleet_lib.make_record(T, fleet_lib.new_span_id(), P, None, "run", "researcher", 1760000000.0, 0.0,
                                "ok", {"skill": "researcher", "request_id": "r1", "http": 200, "images": 0,
                                       "image_bytes": 0}, now=1.0)
    assert _post_span(port, run) == (400, b'{"error":"bad span: kind"}')
    assert _post_span(port, dict(_span(), task="secret")) == (400, b'{"error":"bad span: keys"}')
    assert _post_span(port, dict(_span(), agent="alpha")) == (400, b'{"error":"bad span: keys"}')
    assert ftu.read_records(home, "alpha") == []
    good = _span()
    assert _post_span(port, good) == (200, b'{"ok":true}')
    assert ftu.read_records(home, "alpha") == [dict(good, agent="alpha")]
    path = os.path.join(ftu.daemon_log_dir(home, "alpha"), "trace.jsonl")
    assert ftu.trace_files(home, "alpha") == [path]
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert "trace" not in fleet.daemons["alpha"].log()


def test_tracing_focus_1_non_ascii_tool_keys_round_trip(tmp_path):
    """Review Focus 1: a search query in Japanese with an emoji, and an error line made of
    emoji up to the 256-character limit. Expected: accepted (the escaped body stays under
    8192 bytes), stored exactly, and rendered unchanged in the tree."""
    fleet = _alpha(tmp_path)
    key = "東京 ラーメン \U0001f35c near Shibuya"
    outcome = "\U0001f35c" * 256
    rec = _span(attrs={"round": 1, "decision": "approved", "key": key, "outcome": outcome, "error": False},
                name="search")
    assert len(fleet_lib.canonical_json(rec)) < fleet_lib.TRACE_SPAN_MAX_BYTES
    assert _post_span(fleet.ports["alpha"], rec) == (200, b'{"ok":true}')
    stored = ftu.read_records(fleet.homes["alpha"], "alpha")
    assert [r["attrs"]["key"] for r in stored] == [key] and stored[0]["attrs"]["outcome"] == outcome
    result = {"schema": fleet_lib.TRACE_SCHEMA, "trace_id": T, "records": stored, "missing": [], "truncated": []}
    lines = fleet_lib.render_trace(result, localtime=time.gmtime)
    assert lines[1] == "… span %s on alpha (not retrieved)" % P
    assert lines[2].startswith("  tool search  %s  " % key) and lines[2].endswith("-> %s  @alpha" % outcome)
```

- [ ] **Step 2: Run the new tests to verify they fail (about 15 s: TRT46's headers-only request waits for its 10 s client timeout).**

```bash
python3 -m pytest tests/test_fleet_lib.py tests/test_fleet_tracing.py -q -p no:cacheprovider -k "trt6_ or trt46_ or tracing_focus_1_"
```

Expected: `3 failed, 72 deselected`; TRT6 fails with `assert ('unknown', None) == ('loopback', 'spans')`, TRT46 with `TimeoutError: timed out` (the 8193-byte headers-only request is not refused yet, so the daemon waits for the body), Review Focus 1 with `assert (401, b'') == (200, b'{"ok":true}')`.

- [ ] **Step 3: Implement.** In `fleet_lib.py` and `bin/qwen-agentd`:

Edit 1 of 3 in `fleet_lib.py` (base lines 832-833). Replace:

```python
    ("POST", "/delegate"): ("loopback", "delegate"),
}
```

with:

```python
    ("POST", "/delegate"): ("loopback", "delegate"),
    ("POST", "/spans"): ("loopback", "spans"),
}
```

Edit 2 of 3 in `fleet_lib.py` (base lines 841-843). Replace:

```python
def http_route(method, path):
    """(kind, name) for a request; ("unknown", None) for every other pair (F42)."""
    return _ROUTES.get((method, path), ("unknown", None))
```

with:

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

Edit 3 of 3 in `fleet_lib.py` (base lines 687-688). Replace:

```python
    """Largest request body accepted on a route: MAX_IMAGE_BODY for /run and /delegate, else MAX_BODY."""
    return MAX_IMAGE_BODY if (kind, name) in _IMAGE_ROUTES else MAX_BODY
```

with:

```python
    """Largest request body accepted on a route: MAX_IMAGE_BODY for /run and /delegate, else MAX_BODY."""
    if (kind, name) == ("loopback", "spans"):
        return TRACE_SPAN_MAX_BYTES
    return MAX_IMAGE_BODY if (kind, name) in _IMAGE_ROUTES else MAX_BODY
```

Edit 1 of 4 in `bin/qwen-agentd` (base line 402). Replace:

```python
                status, obj = fleet.loopback_endpoint(name, body)
```

with:

```python
                status, obj = fleet.loopback_endpoint(name, body, path)
```

Edit 2 of 4 in `bin/qwen-agentd` (base line 414). Replace:

```python
                status, raw = fleet.signed_endpoint(name, body)
```

with:

```python
                status, raw = fleet.signed_endpoint(name, body, path)
```

Edit 3 of 4 in `bin/qwen-agentd` (base lines 440-441). Replace:

```python
        self._warn_lock = threading.Lock()
        self._skew_warned = set()
```

with:

```python
        self._warn_lock = threading.Lock()
        self._skew_warned = set()
        self.trace_store = fleet_lib.TraceStore(fleet_lib.log_dir(host_id))
        self._trace_warned = False
```

Edit 4 of 4 in `bin/qwen-agentd` (base lines 629-641). Replace:

```python
    def signed_endpoint(self, name, body):
        """(status, body bytes) for a verified request to a signed endpoint."""
        if name == "health":
            return 200, fleet_lib.canonical_json(self.health_body())
        if name == "skills":
            return 200, fleet_lib.canonical_json({"host_id": self.host_id, "skills": self.skills_view()})
        return self.handle_run(body)

    def loopback_endpoint(self, name, body):
        """(status, JSON-able object) for a loopback-only endpoint; sent unsigned."""
        if name == "peers":
            return 200, self.peers_view()
        return self.handle_delegate(body)
```

with:

```python
    def signed_endpoint(self, name, body, path):
        """(status, body bytes) for a verified request to a signed endpoint."""
        if name == "health":
            return 200, fleet_lib.canonical_json(self.health_body())
        if name == "skills":
            return 200, fleet_lib.canonical_json({"host_id": self.host_id, "skills": self.skills_view()})
        return self.handle_run(body)

    def loopback_endpoint(self, name, body, path):
        """(status, JSON-able object) for a loopback-only endpoint; sent unsigned."""
        if name == "peers":
            return 200, self.peers_view()
        if name == "spans":
            return self.handle_spans(body)
        return self.handle_delegate(body)

    # --- tracing: the store, POST /spans and the query endpoints (tracing spec TR21-TR28) ---

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

- [ ] **Step 4: Run the tests, both files and both compilers.**

```bash
python3 -m pytest tests/test_fleet_lib.py tests/test_fleet_tracing.py -q -p no:cacheprovider -k "trt6_ or trt46_ or tracing_focus_1_"
python3 -m pytest tests/test_fleet_lib.py tests/test_fleet_tracing.py -q -p no:cacheprovider
/usr/bin/python3 -m py_compile fleet_lib.py bin/qwen-agentd tests/test_fleet_lib.py tests/fleet_testutil.py tests/test_fleet_tracing.py && python3 -m py_compile fleet_lib.py bin/qwen-agentd tests/test_fleet_lib.py tests/fleet_testutil.py tests/test_fleet_tracing.py && echo compile-ok
```

Expected: `3 passed, 72 deselected`; `74 passed, 1 skipped`; `compile-ok`.

- [ ] **Step 5: Commit.**

```bash
git add fleet_lib.py bin/qwen-agentd tests/test_fleet_lib.py tests/fleet_testutil.py tests/test_fleet_tracing.py
git diff --cached --name-only   # expected: the five paths above, each with the qwen-agent-workspace/ prefix
git commit -q -F - <<'EOF'
qwen-agentd: loopback POST /spans into the trace store; trace routes and the /spans cap (tracing TR9, TR20-TR22)

TRT6, TRT46, Review Focus 1.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 7: Daemon signed GET /trace/<id>

Implements TR26 (`handle_peer_trace`) and TR20's `trace` branch of `signed_endpoint`. Test TRT44.

**Files:**
- Modify: `bin/qwen-agentd` — two edits (`signed_endpoint`; after `handle_spans`).
- Test: `tests/test_fleet_tracing.py` — one appended block.

**Interfaces:**
- Consumes (Tasks 2, 4, 6): `valid_trace_id`, `Daemon.trace_store.query`, `Daemon.handle_spans`; `_span`, `_post_span`, `T` in the tests; existing `ftu.response_ok`, `ftu.TEST_KEY`, `ftu.OTHER_TOKEN`.
- Produces: `Daemon.handle_peer_trace(path) -> (status, body bytes)` (signed 200 `{"agent", "trace_id", "records", "truncated"}`, 400 `{"error": "bad trace id"}`, 500 `{"error": "trace store unreadable: <ExcType>"}`). In the tests: `_signed_get(port, path, key=ftu.TEST_KEY, nonce=None) -> (status, headers, body, request headers)`.

- [ ] **Step 1: Write the failing test.**

Append to the end of `tests/test_fleet_tracing.py` (after its current last line, base line 105; add two empty lines, then this block, which ends with a newline):

```python
# --- signed GET /trace/<id> (TR26) ---------------------------------------------------------

def _signed_get(port, path, key=ftu.TEST_KEY, nonce=None):
    """(status, headers, body, request headers) of a GET signed with key."""
    nonce = nonce or os.urandom(16).hex()
    headers = fleet_lib.sign_request(key, "GET", path, b"", int(time.time()), nonce)
    status, resp_headers, raw = ftu._request(port, "GET", path, None, dict(headers), timeout=10)
    return status, resp_headers, raw, headers


def test_trt44_signed_peer_trace_endpoint(tmp_path):
    fleet = ftu.Fleet(tmp_path, names=("bravo",)).start()
    port = fleet.ports["bravo"]
    mine = [_span("model", name="bravo-model"), _span()]
    other = _span(trace_id="1" * 32)
    for rec in mine + [other]:
        assert _post_span(port, rec)[0] == 200
    before = fleet.daemons["bravo"].log()
    path = "/trace/" + T
    assert ftu._request(port, "GET", path)[0::2] == (401, b"")
    status, headers, raw, sent = _signed_get(port, path)
    assert status == 200 and ftu.response_ok(ftu.TEST_KEY, 200, "GET", path, sent["X-Fleet-Nonce"], headers, raw)
    assert json.loads(raw) == {"agent": "bravo", "trace_id": T, "records": [dict(r, agent="bravo") for r in mine],
                               "truncated": False}
    assert ftu._request(port, "GET", path, None, dict(sent))[0::2] == (401, b"")
    assert _signed_get(port, path, key=bytes.fromhex(ftu.OTHER_TOKEN))[0::2] == (401, b"")
    for bad in ("/trace/xyz", "/trace/" + T + "?x=1", "/trace/" + T.upper()):
        status, headers, raw, sent = _signed_get(port, bad)
        assert (status, raw) == (400, b'{"error":"bad trace id"}'), bad
        assert ftu.response_ok(ftu.TEST_KEY, 400, "GET", bad, sent["X-Fleet-Nonce"], headers, raw)
    status, _h, raw, _s = _signed_get(port, "/trace/" + "2" * 32)
    assert (status, json.loads(raw)) == (200, {"agent": "bravo", "trace_id": "2" * 32, "records": [],
                                               "truncated": False})
    assert fleet.daemons["bravo"].log() == before
```

- [ ] **Step 2: Run the new test to verify it fails.**

```bash
python3 -m pytest tests/test_fleet_tracing.py -q -p no:cacheprovider -k trt44_
```

Expected: `1 failed, 2 deselected`; `assert (400 == 200)` (the signed `GET /trace/<id>` still reaches `handle_run`, which answers 400 `bad request`).

- [ ] **Step 3: Implement.** In `bin/qwen-agentd`:

Edit 1 of 2 in `bin/qwen-agentd` (base lines 636-637). Replace:

```python
            return 200, fleet_lib.canonical_json({"host_id": self.host_id, "skills": self.skills_view()})
        return self.handle_run(body)
```

with:

```python
            return 200, fleet_lib.canonical_json({"host_id": self.host_id, "skills": self.skills_view()})
        if name == "trace":
            return self.handle_peer_trace(path)
        return self.handle_run(body)
```

Edit 2 of 2 in `bin/qwen-agentd` (base lines 671-675). Replace:

```python
        try:
            self.trace_store.append(dict(obj, agent=self.host_id))
        except Exception as e:
            self._trace_write_failed(e)
        return 200, {"ok": True}
```

with:

```python
        try:
            self.trace_store.append(dict(obj, agent=self.host_id))
        except Exception as e:
            self._trace_write_failed(e)
        return 200, {"ok": True}

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

- [ ] **Step 4: Run the test, the file and both compilers.**

```bash
python3 -m pytest tests/test_fleet_tracing.py -q -p no:cacheprovider -k trt44_
python3 -m pytest tests/test_fleet_tracing.py -q -p no:cacheprovider
/usr/bin/python3 -m py_compile bin/qwen-agentd tests/test_fleet_tracing.py && python3 -m py_compile bin/qwen-agentd tests/test_fleet_tracing.py && echo compile-ok
```

Expected: `1 passed, 2 deselected`; `3 passed`; `compile-ok`.

- [ ] **Step 5: Commit.**

```bash
git add bin/qwen-agentd tests/test_fleet_tracing.py
git diff --cached --name-only   # expected: qwen-agent-workspace/bin/qwen-agentd, qwen-agent-workspace/tests/test_fleet_tracing.py
git commit -q -F - <<'EOF'
qwen-agentd: signed GET /trace/<id> returns this agent's records (tracing TR26)

TRT44.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 8: Daemon loopback GET /trace?id= fan-out and GET /traces/recent

Implements TR27 (`handle_trace_query`, `trace_call`, `_fetch_peer_traces`, `_merge_round`, `trace_query`: two rounds, every `missing` reason), TR28 (`handle_recent`) and TR20's `trace_query` and `recent` branches and the two query regexes. Tests TRT45, `test_tr27_fanout_two_rounds_and_missing_reasons`, `test_tr26_to_tr28_unreadable_store_answers_500`, Review Focus 4.

**Files:**
- Modify: `bin/qwen-agentd` — three edits (beside `_DELEGATE_KEYS`; `loopback_endpoint`; after `handle_peer_trace`).
- Test: `tests/fleet_testutil.py` — one appended block; `tests/test_fleet_tracing.py` — one appended block.

**Interfaces:**
- Consumes (Tasks 2-7): `peer_trace_result`, `merge_records`, `valid_trace_result`, `valid_recent_result`, `TraceStore.query`, `TraceStore.recent`, `TRACE_FANOUT_DEADLINE`, `TRACE_SCHEMA`, `RECENT_SCHEMA`, `TRACE_RECENT_DEFAULT`, `TRACE_RECENT_MAX`, `Daemon._thread`, `Daemon.table.live_peers()`, `Daemon.registry`; `_span`, `_post_span`, `_signed_get`, `_alpha` in the tests.
- Produces in `bin/qwen-agentd`: `_TRACE_QUERY_RE`, `_RECENT_QUERY_RE`; `Daemon.handle_trace_query(path)`, `Daemon.trace_call(address, port, path) -> (status, raw, None) or (None, None, reason)`, `Daemon._fetch_peer_traces(targets, trace_id) -> {host_id: (status, raw, reason)}`, `Daemon._merge_round(trace_id, targets, merged, missing, truncated)`, `Daemon.trace_query(trace_id) -> {"schema", "trace_id", "records", "missing", "truncated"}`, `Daemon.handle_recent(path)`. In `tests/fleet_testutil.py`: `trace(port, trace_id) -> (status, parsed body)`, `recent(port, n=10) -> (status, parsed body)`. In the tests: `_append_lines(home, host_id, records)`, `_delegate_record(agent, target, parent, start)`.

- [ ] **Step 1: Write the failing tests.**

Append to the end of `tests/fleet_testutil.py` (after its current last line, base line 540; add two empty lines, then this block, which ends with a newline):

```python
def trace(port, trace_id):
    """(status, parsed body or None) of loopback GET /trace?id=<trace_id>."""
    status, _headers, raw = _request(port, "GET", "/trace?id=" + trace_id, timeout=30)
    return status, (json.loads(raw) if raw else None)


def recent(port, n=10):
    """(status, parsed body or None) of loopback GET /traces/recent?n=<n>."""
    status, _headers, raw = _request(port, "GET", "/traces/recent?n=%d" % n, timeout=30)
    return status, (json.loads(raw) if raw else None)
```

Append to the end of `tests/test_fleet_tracing.py` (after its current last line, base line 141; add two empty lines, then this block, which ends with a newline):

```python
# --- loopback GET /trace?id= (fan-out) and GET /traces/recent (TR27, TR28) --------------

def _append_lines(home, host_id, records):
    """Append stored-form records to an agent's trace.jsonl the way its daemon would."""
    path = os.path.join(ftu.daemon_log_dir(home, host_id), "trace.jsonl")
    with open(path, "ab") as f:
        for rec in records:
            f.write(fleet_lib.canonical_json(rec) + b"\n")


def _delegate_record(agent, target, parent, start):
    return fleet_lib.make_record(T, fleet_lib.new_span_id(), parent, agent, "delegate", "researcher", start,
                                 0.0, "unreachable", {"skill": "researcher", "target": target, "request_id": "r1",
                                                      "http": None, "images": 0}, now=0.5)


def test_tr27_fanout_two_rounds_and_missing_reasons(tmp_path):
    fleet = ftu.Fleet(tmp_path, names=("alpha", "bravo"), extra_hosts={"charlie": {
        "port": ftu.free_port(), "model_server": {"type": "vllm", "url": "http://127.0.0.1:9/v1"},
        "model": "charlie-model", "skills": ["analyst"]}}).start()
    ftu.wait_until(lambda: fleet.peer_ids("alpha") == ["bravo"], 4.5)
    alpha, bravo = fleet.ports["alpha"], fleet.ports["bravo"]
    turn = _span("turn", parent=None, name="repl")
    tool = _span(parent=turn["span_id"], name="delegate_to_skill")
    for rec in (turn, tool):
        assert _post_span(alpha, rec)[0] == 200
    now = round(time.time(), 3)
    to_charlie = _delegate_record("alpha", "charlie", tool["span_id"], now)
    to_delta = _delegate_record("alpha", "delta", tool["span_id"], now + 0.001)
    _append_lines(fleet.homes["alpha"], "alpha", [to_charlie, to_delta])
    peer = _span("model", parent=to_charlie["span_id"], name="bravo-model")
    assert _post_span(bravo, peer)[0] == 200
    started = time.monotonic()
    status, result = ftu.trace(alpha, T)
    assert time.monotonic() - started < 3
    assert status == 200 and fleet_lib.valid_trace_result(result, T)
    expected = [dict(turn, agent="alpha"), dict(tool, agent="alpha"), to_charlie, to_delta, dict(peer, agent="bravo")]
    assert result["records"] == fleet_lib.merge_records(expected)
    assert result["missing"] == [{"agent": "charlie", "reason": "unreachable (connection refused)"},
                                 {"agent": "delta", "reason": "not in the registry"}]
    assert result["truncated"] == []
    assert ftu.trace(alpha, "1" * 32) == (200, {"schema": "qwen-agentd.trace.v1", "trace_id": "1" * 32,
                                                "records": [], "missing": [], "truncated": []})
    status, listed = ftu.recent(alpha)
    assert status == 200 and fleet_lib.valid_recent_result(listed)
    assert listed["agent"] == "alpha" and [t["trace_id"] for t in listed["traces"]] == [T]
    assert listed["traces"][0]["spans"] == 4
    assert listed["traces"][0]["delegated"] == ["researcher@charlie", "researcher@delta"]
    assert ftu._request(alpha, "GET", "/traces/recent")[0] == 200
    assert ftu.recent(bravo) == (200, {"schema": "qwen-agentd.recent.v1", "agent": "bravo", "traces": []})


def test_trt45_query_endpoints_refuse_browsers_and_bad_queries(tmp_path):
    fleet = _alpha(tmp_path)
    port = fleet.ports["alpha"]
    before = fleet.daemons["alpha"].log()
    body = fleet_lib.canonical_json(_span())
    requests = (("POST", "/spans", body), ("GET", "/trace?id=" + T, None), ("GET", "/traces/recent", None))
    for method, path, payload in requests:
        json_type = {"Content-Type": "application/json"} if method == "POST" else {}
        for headers in (dict(json_type, Host="evil.example:%d" % port),
                        dict(json_type, Origin="http://evil.example")):
            assert ftu._request(port, method, path, payload, headers)[0::2] == (403, b""), (path, headers)
    assert ftu._request(port, "POST", "/spans", body, {"Content-Type": "text/plain"})[0::2] == (403, b"")
    if sys.platform.startswith("linux"):
        for method, path, payload in requests:
            headers = {"Content-Length": str(len(payload or b"")), "Content-Type": "application/json"}
            assert ftu.raw_request(port, method, path, headers, payload or b"",
                                   source=("127.0.0.2", 0)) == (403, b"")
    assert ftu._request(port, "GET", "/trace?id=xyz")[0::2] == (400, b'{"error":"bad trace id"}')
    assert ftu._request(port, "GET", "/trace")[0::2] == (400, b'{"error":"bad trace id"}')
    for n in ("101", "0", "abc", "", "1000"):
        assert ftu._request(port, "GET", "/traces/recent?n=" + n)[0::2] == (400, b'{"error":"bad n"}'), n
    assert ftu.read_records(fleet.homes["alpha"], "alpha") == []
    assert fleet.daemons["alpha"].log() == before


def test_tr26_to_tr28_unreadable_store_answers_500(tmp_path):
    fleet = ftu.Fleet(tmp_path, names=("alpha",))
    os.makedirs(os.path.join(ftu.daemon_log_dir(fleet.homes["alpha"], "alpha"), "trace.jsonl"))
    fleet.start()
    port = fleet.ports["alpha"]
    status, _h, raw, _s = _signed_get(port, "/trace/" + T)
    assert (status, raw) == (500, b'{"error":"trace store unreadable: IsADirectoryError"}')
    assert ftu.trace(port, T) == (500, {"error": "trace store unreadable: IsADirectoryError"})
    assert ftu.recent(port) == (500, {"error": "trace store unreadable: IsADirectoryError"})
    assert _post_span(port, _span()) == (200, b'{"ok":true}')
    assert _post_span(port, _span()) == (200, b'{"ok":true}')
    log = fleet.daemons["alpha"].log()
    assert log.count("trace: cannot write ") == 1
    assert " WARNING " in log and "trace: cannot write %s: IsADirectoryError\n" % os.path.join(
        ftu.daemon_log_dir(fleet.homes["alpha"], "alpha"), "trace.jsonl") in log


def test_tracing_focus_4_traces_survive_a_daemon_restart(tmp_path):
    """Review Focus 4: every self-update restarts the daemon. Expected: a trace recorded
    before the restart is still listed by --recent and returned by GET /trace?id= after it."""
    fleet = _alpha(tmp_path)
    turn = _span("turn", parent=None, name="repl")
    assert _post_span(fleet.ports["alpha"], turn)[0] == 200
    fleet.daemons["alpha"].kill()
    ftu.start_daemon(fleet.homes["alpha"], "alpha", fleet.registry, fleet.beacon_ports["alpha"], "none")
    status, result = ftu.trace(fleet.ports["alpha"], T)
    assert status == 200 and result["records"] == [dict(turn, agent="alpha")]
    status, listed = ftu.recent(fleet.ports["alpha"], 1)
    assert status == 200 and [t["trace_id"] for t in listed["traces"]] == [T]
```

- [ ] **Step 2: Run the new tests to verify they fail.**

```bash
python3 -m pytest tests/test_fleet_tracing.py -q -p no:cacheprovider -k "tr27_ or trt45_ or tr26_to_tr28 or tracing_focus_4_"
```

Expected: `4 failed, 3 deselected`; the fan-out test and Review Focus 4 fail with `assert (400 == 200)` (the query still reaches `handle_delegate`), TRT45 with `b'{"error":"bad request"}' != b'{"error":"bad trace id"}'`, the unreadable-store test with `400 != 500`.

- [ ] **Step 3: Implement.** In `bin/qwen-agentd`:

Edit 1 of 3 in `bin/qwen-agentd` (base line 200). Replace:

```python
_DELEGATE_KEYS = frozenset(("skill", "task", "host_id"))
```

with:

```python
_DELEGATE_KEYS = frozenset(("skill", "task", "host_id"))
_TRACE_QUERY_RE = re.compile(r"/trace\?id=([0-9a-f]{32})")
_RECENT_QUERY_RE = re.compile(r"/traces/recent\?n=([0-9]{1,3})")
```

Edit 2 of 3 in `bin/qwen-agentd` (base lines 645-647). Replace:

```python
        if name == "spans":
            return self.handle_spans(body)
        return self.handle_delegate(body)
```

with:

```python
        if name == "spans":
            return self.handle_spans(body)
        if name == "trace_query":
            return self.handle_trace_query(path)
        if name == "recent":
            return self.handle_recent(path)
        return self.handle_delegate(body)
```

Edit 3 of 3 in `bin/qwen-agentd` (base lines 688-689). Replace:

```python
        return 200, fleet_lib.canonical_json({"agent": self.host_id, "trace_id": trace_id,
                                              "records": records, "truncated": truncated})
```

with:

```python
        return 200, fleet_lib.canonical_json({"agent": self.host_id, "trace_id": trace_id,
                                              "records": records, "truncated": truncated})

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

- [ ] **Step 4: Run the tests, the file and both compilers.**

```bash
python3 -m pytest tests/test_fleet_tracing.py -q -p no:cacheprovider -k "tr27_ or trt45_ or tr26_to_tr28 or tracing_focus_4_"
python3 -m pytest tests/test_fleet_tracing.py -q -p no:cacheprovider
/usr/bin/python3 -m py_compile bin/qwen-agentd tests/fleet_testutil.py tests/test_fleet_tracing.py && python3 -m py_compile bin/qwen-agentd tests/fleet_testutil.py tests/test_fleet_tracing.py && echo compile-ok
```

Expected: `4 passed, 3 deselected`; `7 passed`; `compile-ok`.

- [ ] **Step 5: Commit.**

```bash
git add bin/qwen-agentd tests/fleet_testutil.py tests/test_fleet_tracing.py
git diff --cached --name-only   # expected: the three paths above, each with the qwen-agent-workspace/ prefix
git commit -q -F - <<'EOF'
qwen-agentd: loopback GET /trace?id= fans out to peers and delegate targets; GET /traces/recent (tracing TR27, TR28)

TRT45, fan-out rounds, unreadable store, Review Focus 4.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 9: The qwen-agentd trace subcommand

Implements TR29 (the usage lines, `_RECENT_N_RE`, `cmd_trace`, the `trace` subparser). Tests TRT41a, Review Focus 2.

**Files:**
- Modify: `bin/qwen-agentd` — three edits (the module docstring; after `cmd_status`; after the `status` subparser).
- Test: `tests/fleet_testutil.py` — one appended block; `tests/test_fleet_tracing.py` — one appended block.

**Interfaces:**
- Consumes (Tasks 2-8): `fetch_trace`, `fetch_recent`, `render_trace`, `render_recent`, `valid_trace_id`, `fmt_ms`, `TRACE_RECENT_DEFAULT`, `TRACE_RECENT_MAX`; existing `fleet_lib.resolve_agent`, `fleet_lib.shown_value`, `_status_port`, `_add_agent_id`, `_err`; `ftu.trace`, `_span`, `_post_span`, `_alpha` in the tests.
- Produces: `cmd_trace(args) -> 0 | 1 | 2`; the parser accepts `trace [--agent-id ID] [--port N] [--json] [--recent [N]] [TRACE_ID]`. In `tests/fleet_testutil.py`: `trace_cli(home, args) -> subprocess.CompletedProcess` (text). In the tests: `_OldDaemon()` (answers every GET 401) with `.port`, `.close()`.

- [ ] **Step 1: Write the failing tests.**

Append to the end of `tests/fleet_testutil.py` (after its current last line, base line 552; add two empty lines, then this block, which ends with a newline):

```python
def trace_cli(home, args):
    """`qwen-agentd trace <args>` with HOME=home -> the CompletedProcess (text mode)."""
    return subprocess.run([sys.executable, AGENTD, "trace"] + list(args), env=clean_env(home),
                          capture_output=True, text=True, timeout=60)
```

Append to the end of `tests/test_fleet_tracing.py` (after its current last line, base line 249; add two empty lines, then this block, which ends with a newline):

```python
# --- qwen-agentd trace (TR29) ---------------------------------------------------------------

class _OldDaemon(object):
    """A loopback server that answers every request 401 with an empty body, as a daemon
    without tracing answers an unsigned GET to an unknown route (F44)."""

    def __init__(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(401)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_trt41a_trace_cli_on_one_agent(tmp_path):
    fleet = _alpha(tmp_path)
    port, home = fleet.ports["alpha"], fleet.homes["alpha"]
    older = _span("turn", trace_id="2" * 32, parent=None, name="oneshot", start=round(time.time(), 3) - 60)
    turn = _span("turn", parent=None, name="repl")
    model = _span("model", parent=turn["span_id"], name="alpha-model")
    for rec in (older, turn, model):
        assert _post_span(port, rec)[0] == 200
    proc = ftu.trace_cli(home, ["--port", str(port), T])
    assert (proc.returncode, proc.stderr) == (0, "")
    expected = fleet_lib.render_trace(ftu.trace(port, T)[1])
    assert proc.stdout == "\n".join(expected) + "\n"
    assert proc.stdout.startswith("trace 4bf92f3577b3  ") and "  agents: alpha  spans: 2\n" in proc.stdout
    assert proc.stdout.splitlines()[2] == "  model alpha-model  %s  ok  3→4 tok  stop  @alpha" % (
        fleet_lib.fmt_ms(model["dur_ms"]))
    proc = ftu.trace_cli(home, ["--port", str(port), "--json", T])
    assert proc.returncode == 0 and json.loads(proc.stdout) == ftu.trace(port, T)[1]
    assert proc.stdout == json.dumps(json.loads(proc.stdout), indent=2, sort_keys=True) + "\n"
    proc = ftu.trace_cli(home, ["--port", str(port), "--recent"])
    lines = proc.stdout.splitlines()
    assert proc.returncode == 0 and len(lines) == 3
    assert lines[0] == "time                 trace id                               dur  status        spans  delegated"
    assert lines[1].split()[2] == T and lines[2].split()[2] == "2" * 32
    assert lines[1].endswith("  2  -") and lines[2].endswith("  1  -")
    proc = ftu.trace_cli(home, ["--port", str(port), "--recent", "1"])
    assert proc.returncode == 0 and proc.stdout.splitlines()[1:] == lines[1:2]
    for args, message in (
            (["--recent", "0"], "qwen-agentd: invalid --recent '0' (1 to 100)"),
            (["--recent", "x"], "qwen-agentd: invalid --recent 'x' (1 to 100)"),
            (["--recent", "101"], "qwen-agentd: invalid --recent '101' (1 to 100)"),
            (["--recent", "--json"], "qwen-agentd: --json applies to trace TRACE_ID only"),
            ([T, "--recent"], "qwen-agentd: trace takes a TRACE_ID or --recent, not both"),
            ([], "qwen-agentd: trace needs a TRACE_ID or --recent [N]"),
            (["--port", "70000", T], "qwen-agentd: invalid --port 70000"),
            (["badid"], "qwen-agentd: invalid trace id 'badid' (32 lowercase hex characters)"),
            ([T.upper()], "qwen-agentd: invalid trace id '%s' (32 lowercase hex characters)" % T.upper())):
        proc = ftu.trace_cli(home, args)
        assert (proc.returncode, proc.stdout, proc.stderr) == (2, "", message + "\n"), args
    closed = ftu.free_port()
    proc = ftu.trace_cli(home, ["--port", str(closed), T])
    assert (proc.returncode, proc.stderr) == (1, "qwen-agentd: daemon not reachable at http://127.0.0.1:%d\n" % closed)
    proc = ftu.trace_cli(home, ["--port", str(port), "1" * 32])
    assert proc.returncode == 1
    assert proc.stdout == "trace 111111111111  -  -  agents: none  spans: 0\n"
    assert proc.stderr == "qwen-agentd: no records for trace %s\n" % ("1" * 32)
    old = _OldDaemon()
    try:
        for args in ([T], ["--recent"]):
            proc = ftu.trace_cli(home, ["--port", str(old.port)] + args)
            assert (proc.returncode, proc.stderr) == (
                1, "qwen-agentd: the daemon at http://127.0.0.1:%d has no trace support (http 401)\n" % old.port)
    finally:
        old.close()


def test_tracing_focus_2_fresh_agent_with_no_trace_file(tmp_path):
    """Review Focus 2: the first `trace --recent` on a newly installed agent, before any
    turn was traced. Expected: exit 1 with "no traces recorded on <agent>" (not an error
    about a missing file), `trace <id>` says "no records", and no query creates the file."""
    fleet = _alpha(tmp_path)
    port, home = fleet.ports["alpha"], fleet.homes["alpha"]
    proc = ftu.trace_cli(home, ["--port", str(port), "--recent"])
    assert (proc.returncode, proc.stdout, proc.stderr) == (1, "", "qwen-agentd: no traces recorded on alpha\n")
    proc = ftu.trace_cli(home, ["--port", str(port), T])
    assert proc.returncode == 1 and proc.stderr == "qwen-agentd: no records for trace %s\n" % T
    assert ftu.trace_files(home, "alpha") == []
    assert "trace" not in fleet.daemons["alpha"].log()
```

- [ ] **Step 2: Run the new tests to verify they fail.**

```bash
python3 -m pytest tests/test_fleet_tracing.py -q -p no:cacheprovider -k "trt41a_ or tracing_focus_2_"
```

Expected: `2 failed, 7 deselected`; both fail with exit code 2 from argparse (`trace` is not a subcommand yet): `assert (2, "usage: q...'install')\n") == (0, '')` and `assert (2, '', "usag...'install')\n") == (1, '', 'qwen...d on alpha\n')`.

- [ ] **Step 3: Implement.** In `bin/qwen-agentd`:

Edit 1 of 3 in `bin/qwen-agentd` (base line 10). Replace:

```python
  qwen-agentd status [--agent-id ID] [--port N]
```

with:

```python
  qwen-agentd status [--agent-id ID] [--port N]
  qwen-agentd trace [--agent-id ID | --port N] [--json] TRACE_ID
  qwen-agentd trace [--agent-id ID | --port N] --recent [N]
```

Edit 2 of 3 in `bin/qwen-agentd` (base lines 1305-1306). Replace:

```python
    sys.stdout.write("\n".join(lines) + "\n")
    return rc
```

with:

```python
    sys.stdout.write("\n".join(lines) + "\n")
    return rc


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

Edit 3 of 3 in `bin/qwen-agentd` (base line 1717). Replace:

```python
    p.set_defaults(func=cmd_status)
```

with:

```python
    p.set_defaults(func=cmd_status)
    p = sub.add_parser("trace", help="print one trace as a tree, or list this agent's recent traces")
    _add_agent_id(p)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--json", dest="as_json", action="store_true", default=False)
    p.add_argument("--recent", nargs="?", const=str(fleet_lib.TRACE_RECENT_DEFAULT), default=None, metavar="N")
    p.add_argument("trace_id", nargs="?", default=None, metavar="TRACE_ID")
    p.set_defaults(func=cmd_trace)
```

- [ ] **Step 4: Run the tests, the file, the existing CLI tests and both compilers.**

```bash
python3 -m pytest tests/test_fleet_tracing.py -q -p no:cacheprovider -k "trt41a_ or tracing_focus_2_"
python3 -m pytest tests/test_fleet_tracing.py -q -p no:cacheprovider
python3 -m pytest tests/test_fleet_integration.py -q -p no:cacheprovider -k "cli or status"
/usr/bin/python3 -m py_compile bin/qwen-agentd tests/fleet_testutil.py tests/test_fleet_tracing.py && python3 -m py_compile bin/qwen-agentd tests/fleet_testutil.py tests/test_fleet_tracing.py && echo compile-ok
```

Expected: `2 passed, 7 deselected`; `9 passed`; `8 passed, 29 deselected`; `compile-ok`.

- [ ] **Step 5: Commit.**

```bash
git add bin/qwen-agentd tests/fleet_testutil.py tests/test_fleet_tracing.py
git diff --cached --name-only   # expected: the three paths above, each with the qwen-agent-workspace/ prefix
git commit -q -F - <<'EOF'
qwen-agentd: trace subcommand prints a trace tree, its JSON, or the recent traces (tracing TR29)

TRT41a, Review Focus 2.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 10: Daemon run, agent and delegate spans, trace forwarding and the old-peer retry

Implements TR23 (`handle_run` plus `_run_request`: the run and agent spans, `spawn_run(..., trace=None)`, `_run_child(argv, trace=None)` and the child's trace env), TR24 (`handle_delegate`: the delegate span, `trace` always forwarded), TR25 (`forward_run` plus `_forward_once`: the peer status and the one verified-400 retry) and TR20's `_OPTIONAL_KEYS`; migrates VT27 (spec 6.6). Tests TRT43, TRT48, VT27, Review Focus 5.

**Files:**
- Modify: `bin/qwen-agentd` — seven edits (beside `_DELEGATE_KEYS`; `handle_run` through the head of `spawn_run`; the two `_run_child` calls in `spawn_run`; the `_run_child` signature; its `build_child_env` call; `handle_delegate` and `forward_run`).
- Test: `tests/fleet_testutil.py` — one edit; `tests/test_fleet_vision.py` — one edit (one line); `tests/test_fleet_tracing.py` — one appended block.

**Interfaces:**
- Consumes (Tasks 2-9): `valid_trace_field`, `trace_context`, `new_span_id`, `trace_skill`, `trace_token`, `run_status`, `build_child_env(..., trace)`, `Daemon.record_span`, `ftu.read_records`, `ftu.trace`, `ftu.trace_cli`; existing `request_images`, `serves_skill`, `ftu.write_hook`, `ftu.release_hook`, `ftu.send_beacon`, `ftu.CANNED_LINE`.
- Produces in `bin/qwen-agentd`: `_OPTIONAL_KEYS`; `Daemon.handle_run(body)` (records one run span per shape-valid request), `Daemon._run_request(req, trace, facts) -> (code, body)`, `Daemon.spawn_run(skill, task, images=None, trace=None)`, `Daemon._run_child(argv, trace=None)`, `Daemon.handle_delegate(body)` (one delegate span per shape-valid request), `Daemon.forward_run(record, skill, task, request_id, images=None, trace=None) -> (outcome, envelope, detail, http or None)`, `Daemon._forward_once(record, skill, task, request_id, images, trace) -> (outcome, envelope, detail, http, parsed peer_error body)`. In `tests/fleet_testutil.py`: `delegate(port, skill, task, host_id, timeout=120, images=None, trace=None)`. In the tests: `_signed_run(port, body, timeout=60)`, `_of_kind(records, kind, trace_id=T)`, `_OldPeer(port)`.

- [ ] **Step 1: Write the failing tests and migrate VT27.**

Edit 1 of 1 in `tests/fleet_testutil.py` (base lines 305-309). Replace:

```python
def delegate(port, skill, task, host_id, timeout=120, images=None):
    """(status, parsed body or None) of loopback POST /delegate; images (wire list) adds the key."""
    request = {"skill": skill, "task": task, "host_id": host_id}
    if images is not None:
        request["images"] = images
```

with:

```python
def delegate(port, skill, task, host_id, timeout=120, images=None, trace=None):
    """(status, parsed body or None) of loopback POST /delegate; images (wire list) and trace
    ({"trace_id", "parent_span_id"}) each add their key when not None."""
    request = {"skill": skill, "task": task, "host_id": host_id}
    if images is not None:
        request["images"] = images
    if trace is not None:
        request["trace"] = trace
```

Edit 1 of 1 in `tests/test_fleet_vision.py` (base line 441). Replace:

```python
        assert all(set(b) == {"skill", "task", "request_id", "images"} for b in delta.run_bodies)
```

with:

```python
        assert all(set(b) == {"skill", "task", "request_id", "images", "trace"} for b in delta.run_bodies)
```

Append to the end of `tests/test_fleet_tracing.py` (after its current last line, base line 343; add two empty lines, then this block, which ends with a newline):

```python
# --- POST /run and POST /delegate spans, propagation, the old-peer retry (TR23-TR25) ------------

def _signed_run(port, body, timeout=60):
    status, headers, raw, nonce = ftu.signed(ftu.TEST_KEY, "POST", port, "/run", body, timeout=timeout)
    assert ftu.response_ok(ftu.TEST_KEY, status, "POST", "/run", nonce, headers, raw), status
    return status, raw


def _of_kind(records, kind, trace_id=T):
    return [r for r in records if r["kind"] == kind and r["trace_id"] == trace_id]


def test_trt48_run_child_gets_the_agent_span_as_its_parent(tmp_path):
    hook = ftu.write_hook(os.path.join(str(tmp_path), "hook-envdump"), "envdump")
    fleet = ftu.Fleet(tmp_path, names=("alpha", "bravo"), extra_args={"bravo": ["--qwen-agent-bin", hook]}).start()
    ftu.wait_until(lambda: "bravo" in fleet.peer_ids("alpha"), 4.5)
    status, body = ftu.delegate(fleet.ports["alpha"], "researcher", "again", "bravo",
                                trace={"trace_id": T, "parent_span_id": P})
    assert status == 200 and body["outcome"] == "ok", body
    with open(hook + ".json", encoding="utf-8") as f:
        dumped = json.load(f)
    bravo = ftu.read_records(fleet.homes["bravo"], "bravo")
    alpha = ftu.read_records(fleet.homes["alpha"], "alpha")
    [delegate] = _of_kind(alpha, "delegate")
    [run] = _of_kind(bravo, "run")
    [agent] = _of_kind(bravo, "agent")
    assert dumped["env"]["QWEN_AGENT_TRACE_ID"] == T
    assert dumped["env"]["QWEN_AGENT_PARENT_SPAN"] == agent["span_id"]
    assert agent["parent_span_id"] == run["span_id"]
    assert run["parent_span_id"] == delegate["span_id"] and delegate["parent_span_id"] == P
    assert _of_kind(bravo, "turn") == []
    assert (delegate["status"], delegate["attrs"]) == ("ok", {"skill": "researcher", "target": "bravo",
                                                             "request_id": run["attrs"]["request_id"],
                                                             "http": 200, "images": 0})
    assert (run["status"], run["name"], run["attrs"]["http"]) == ("ok", "researcher", 200)
    assert (agent["status"], agent["attrs"]["envelope_status"]) == ("ok", "ok")
    bravo_url = "http://127.0.0.1:%d/v1" % fleet.server_ports["bravo"]
    assert dumped["argv"][1:] == ["--skill=researcher", "--user-prompt=again", "--base-url=%s" % bravo_url,
                                  "--model=bravo-model", "--model-server-type=ollama"]
    assert "run start skill=researcher request_id=%s task_chars=5 images=0 image_bytes=0" % (
        run["attrs"]["request_id"]) in fleet.daemons["bravo"].log()


class _OldPeer(object):
    """An in-process registered peer 'delta' from before tracing: its /run answers a body with
    a "trace" key with a signed 400 {"error": "bad request"} and any other body with the canned
    envelope; GET /trace/<id> is an unknown route (signed 404 {"error": "not found"})."""

    def __init__(self, port):
        self.run_bodies = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):
                pass

            def _reply(self, status, raw):
                headers = fleet_lib.sign_response(ftu.TEST_KEY, status, self.command, self.path,
                                                  self.headers.get("X-Fleet-Nonce"), raw,
                                                  int(time.time()), os.urandom(16).hex())
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/health":
                    self._reply(200, fleet_lib.canonical_json({"host_id": "delta", "role": "agent",
                                                               "version": "dev", "proto": 1,
                                                               "discovery": "beacon"}))
                elif self.path == "/skills":
                    self._reply(200, fleet_lib.canonical_json({"host_id": "delta", "skills": [
                        {"skill": "researcher", "model": "delta-model", "verified": True, "busy": False}]}))
                else:
                    self._reply(404, fleet_lib.canonical_json({"error": "not found"}))

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                outer.run_bodies.append(body)
                if "trace" in body:
                    self._reply(400, fleet_lib.canonical_json({"error": "bad request"}))
                else:
                    self._reply(200, ftu.CANNED_LINE.encode("utf-8"))

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_trt43_old_peer_gets_one_untraced_retry_and_shows_as_no_trace_support(tmp_path):
    delta_port = ftu.free_port()
    fleet = ftu.Fleet(tmp_path, names=("alpha",), extra_hosts={"delta": {
        "port": delta_port, "model_server": {"type": "vllm", "url": "http://127.0.0.1:9/v1"},
        "model": "delta-model", "skills": ["researcher"]}})
    delta = _OldPeer(delta_port)
    try:
        fleet.start()
        alpha = fleet.ports["alpha"]
        ftu.send_beacon(ftu.TEST_KEY, delta_port, fleet.beacon_ports["alpha"])
        ftu.wait_until(lambda: "delta" in fleet.peer_ids("alpha"), 3.0)
        status, body = ftu.delegate(alpha, "researcher", "t", "delta", trace={"trace_id": T, "parent_span_id": P})
        assert status == 200 and body["outcome"] == "ok" and body["envelope"]["answer"] == "CANNED", body
        [delegate] = _of_kind(ftu.read_records(fleet.homes["alpha"], "alpha"), "delegate")
        assert [sorted(b) for b in delta.run_bodies] == [["request_id", "skill", "task", "trace"],
                                                         ["request_id", "skill", "task"]]
        assert delta.run_bodies[0]["trace"] == {"trace_id": T, "parent_span_id": delegate["span_id"]}
        assert delta.run_bodies[0]["request_id"] == delta.run_bodies[1]["request_id"]
        status, result = ftu.trace(alpha, T)
        assert status == 200 and result["records"] == [delegate]
        assert (delegate["status"], delegate["attrs"]["http"]) == ("ok", 200)
        assert result["missing"] == [{"agent": "delta", "reason": "no trace support (http 404)"}]
        proc = ftu.trace_cli(fleet.homes["alpha"], ["--port", str(alpha), T])
        assert proc.returncode == 0
        lines = proc.stdout.splitlines()
        assert lines[1] == "! delta: no trace support (http 404)"
        assert lines[2] == "… span %s on alpha (not retrieved)" % P
        assert lines[3].startswith("  delegate researcher -> delta  req=%s  http=200  " % (
            delegate["attrs"]["request_id"])) and lines[3].endswith("  ok  @alpha")
    finally:
        delta.close()


def test_tracing_focus_5_a_crashed_child_still_leaves_run_and_agent_spans(tmp_path):
    """Review Focus 5: the peer's child crashes before printing an envelope (a model server
    that went away, a broken release). Expected: the run and agent spans are still recorded
    with http 502 and status error; a busy refusal is a run span "busy" with no agent span;
    a malformed trace field is a plain 400 with no span at all."""
    hook = ftu.write_hook(os.path.join(str(tmp_path), "hook-slow"), "slow")
    fleet = ftu.Fleet(tmp_path, names=("bravo",), extra_args={"bravo": ["--qwen-agent-bin", hook]}).start()
    port, home = fleet.ports["bravo"], fleet.homes["bravo"]

    def run_body(task, request_id, trace=None):
        req = {"skill": "researcher", "task": task, "request_id": request_id}
        if trace is not None:
            req["trace"] = trace
        return json.dumps(req).encode("utf-8")

    field = {"trace_id": T, "parent_span_id": P}
    assert _signed_run(port, run_body("garbage", "req-1", field)) == \
        (502, b'{"error":"skill produced no parseable output (exit code 1)"}')
    [run] = _of_kind(ftu.read_records(home, "bravo"), "run")
    [agent] = _of_kind(ftu.read_records(home, "bravo"), "agent")
    assert (run["parent_span_id"], run["status"], run["attrs"]["http"]) == (P, "error", 502)
    assert (agent["parent_span_id"], agent["status"]) == (run["span_id"], "error")
    assert agent["attrs"] == {"skill": "researcher", "request_id": "req-1", "http": 502, "envelope_status": None}
    result = {}
    first = threading.Thread(target=lambda: result.update(first=_signed_run(port, run_body("one", "req-2"))))
    first.start()
    ftu.wait_until(lambda: json.loads(ftu.signed(ftu.TEST_KEY, "GET", port, "/skills")[2])
                   ["skills"][0]["busy"] is True, 10)
    assert _signed_run(port, run_body("two", "req-3", field)) == (409, b'{"error":"busy"}')
    ftu.release_hook(hook, "one")
    first.join(30)
    assert result["first"] == (200, ftu.CANNED_LINE.encode("utf-8"))
    records = ftu.read_records(home, "bravo")
    busy = [r for r in records if r["kind"] == "run" and r["attrs"]["request_id"] == "req-3"]
    assert [(r["status"], r["attrs"]["http"], r["parent_span_id"]) for r in busy] == [("busy", 409, P)]
    assert [r for r in records if r["kind"] == "agent" and r["attrs"]["request_id"] == "req-3"] == []
    untraced = [r for r in records if r["kind"] == "run" and r["attrs"]["request_id"] == "req-2"]
    assert len(untraced) == 1 and untraced[0]["parent_span_id"] is None and untraced[0]["trace_id"] != T
    count = len(records)
    assert _signed_run(port, run_body("x", "req-4", {"trace_id": T})) == (400, b'{"error":"bad request"}')
    assert len(ftu.read_records(home, "bravo")) == count
```

- [ ] **Step 2: Run the new and migrated tests to verify they fail.**

```bash
python3 -m pytest tests/test_fleet_tracing.py tests/test_fleet_vision.py -q -p no:cacheprovider -k "trt48_ or trt43_ or tracing_focus_5_ or vt27_"
```

Expected: `4 failed, 21 deselected`; TRT48 and TRT43 fail with `AssertionError: {'error': 'bad request'}` / `assert (400 == 200)` (the daemons still reject a `/delegate` body with `trace`), Review Focus 5 with `assert (400, b'{"err...ad request"}') == (502, ...)` (the same for a traced `/run`), and VT27 with `assert False` (its forwarded bodies have no `trace` yet).

- [ ] **Step 3: Implement.** In `bin/qwen-agentd`:

Edit 1 of 7 in `bin/qwen-agentd` (base line 202). Replace:

```python
_DELEGATE_KEYS = frozenset(("skill", "task", "host_id"))
```

with:

```python
_DELEGATE_KEYS = frozenset(("skill", "task", "host_id"))
_OPTIONAL_KEYS = frozenset(("images", "trace"))   # body keys /run and /delegate accept beyond their base set
```

Edit 2 of 7 in `bin/qwen-agentd` (base lines 950-988). Replace:

```python
    def handle_run(self, body):
        """(status, body bytes) for a verified POST /run. One run at a time per host (vision spec V16)."""
        req = _json_or_none(body)
        if not (isinstance(req, dict) and set(req) in (_RUN_KEYS, _RUN_KEYS | {"images"})
                and all(isinstance(req[k], str) for k in _RUN_KEYS)
                and req["task"].strip() != ""
                and fleet_lib.REQUEST_ID_RE.fullmatch(req["request_id"])):
            return 400, fleet_lib.canonical_json({"error": "bad request"})
        try:
            images = fleet_lib.request_images(req)
        except fleet_lib.ImageError as e:
            return e.status, fleet_lib.canonical_json({"error": e.reason})
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
                     % (skill, request_id, len(task), len(images or []),
                        sum(len(data) for _media_type, data in images or [])))
            code, status, raw = self.spawn_run(skill, task, images)
            return code, raw
        finally:
            self.run_lock.release()
            if started is not None:
                LOG.info("run end skill=%s request_id=%s http=%d status=%s seconds=%.1f"
                         % (skill, request_id, code, status, time.monotonic() - started))

    def spawn_run(self, skill, task, images=None):
        """Run this release's bin/qwen-agent --skill child -> (http code, envelope status, body).

        images, decoded [(media_type, bytes)], are written to a private directory under
        A(<id>)/tmp, passed as --image paths, and removed on every exit (vision spec V17, V18).
        """
```

with:

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

    def spawn_run(self, skill, task, images=None, trace=None):
        """Run this release's bin/qwen-agent --skill child -> (http code, envelope status, body).

        images, decoded [(media_type, bytes)], are written to a private directory under
        A(<id>)/tmp, passed as --image paths, and removed on every exit (vision spec V17, V18).
        trace, (trace_id, agent span_id), becomes the child's QWEN_AGENT_TRACE_ID and
        QWEN_AGENT_PARENT_SPAN (tracing spec TR23).
        """
```

Edit 3 of 7 in `bin/qwen-agentd` (base lines 992-993). Replace:

```python
        if not images:
            return self._run_child(argv)
```

with:

```python
        if not images:
            return self._run_child(argv, trace)
```

Edit 4 of 7 in `bin/qwen-agentd` (base lines 1010-1011). Replace:

```python
            return self._run_child(argv)
        finally:
```

with:

```python
            return self._run_child(argv, trace)
        finally:
```

Edit 5 of 7 in `bin/qwen-agentd` (base line 1015). Replace:

```python
    def _run_child(self, argv):
```

with:

```python
    def _run_child(self, argv, trace=None):
```

Edit 6 of 7 in `bin/qwen-agentd` (base line 1024). Replace:

```python
                                        env=fleet_lib.build_child_env(os.environ, self.loopback_url),
```

with:

```python
                                        env=fleet_lib.build_child_env(os.environ, self.loopback_url, trace),
```

Edit 7 of 7 in `bin/qwen-agentd` (base lines 1048-1115). Replace:

```python
    def handle_delegate(self, body):
        """(status, object) for loopback POST /delegate. Never touches run_lock (F65, vision spec V14)."""
        req = _json_or_none(body)
        if not (isinstance(req, dict) and set(req) in (_DELEGATE_KEYS, _DELEGATE_KEYS | {"images"})
                and all(isinstance(req[k], str) for k in _DELEGATE_KEYS)
                and req["task"].strip() != "" and req["skill"] in fleet_lib.KNOWN_SKILLS
                and fleet_lib.HOST_ID_RE.fullmatch(req["host_id"])):
            return 400, {"error": "bad request"}
        try:
            fleet_lib.request_images(req)
        except fleet_lib.ImageError as e:
            return e.status, {"error": e.reason}
        skill, task, host_id = req["skill"], req["task"], req["host_id"]
        started = time.monotonic()
        record = self.table.record(host_id)
        if (host_id == self.host_id or not self.table.is_live(host_id) or record is None
                or record["compatible"] is not True or not fleet_lib.serves_skill(record["skills"], skill)):
            LOG.info("delegate skill=%s host=%s request_id=- outcome=not_live seconds=%.1f"
                     % (skill, host_id, time.monotonic() - started))
            return 200, {"outcome": "not_live", "envelope": None, "detail": ""}
        request_id = secrets.token_hex(8)
        outcome, envelope, detail = self.forward_run(record, skill, task, request_id, req.get("images"))
        LOG.info("delegate skill=%s host=%s request_id=%s outcome=%s seconds=%.1f"
                 % (skill, host_id, request_id, outcome, time.monotonic() - started))
        return 200, {"outcome": outcome, "envelope": envelope, "detail": detail}

    def forward_run(self, record, skill, task, request_id, images=None):
        """Signed POST /run to the peer's current address -> (outcome, envelope, detail) (F66).

        images is the wire list exactly as /delegate received it (vision spec V15, V20).
        """
        request = {"skill": skill, "task": task, "request_id": request_id}
        if images is not None:
            request["images"] = images
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
            return "timeout", None, ""
        except (OSError, http.client.HTTPException) as e:
            return "unreachable", None, type(e).__name__
        finally:
            conn.close()
        if len(raw) > fleet_lib.MAX_BODY:
            return "bad_response", None, ""
        if resp_headers.get("X-Fleet-Sig") is None and status in (413, 503):
            return ("busy", None, "") if status == 503 else ("peer_error", None, "http 413")
        if fleet_lib.verify_response(self.key, status, "POST", "/run", nonce, resp_headers, raw,
                                     int(time.time()), self.response_nonces) != "ok":
            return "bad_signature", None, ""
        if status == 409:
            return "busy", None, ""
        if status == 504:
            return "timeout", None, ""
        if status == 200:
            envelope = _json_or_none(raw)
            if isinstance(envelope, dict) and envelope.get("schema") == fleet_lib.ONESHOT_SCHEMA:
                return "ok", envelope, ""
            return "bad_response", None, ""
        return "peer_error", None, "http %d" % status
```

with:

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

- [ ] **Step 4: Run the tests, the three daemon suites and both compilers (about 2 min).**

```bash
python3 -m pytest tests/test_fleet_tracing.py tests/test_fleet_vision.py -q -p no:cacheprovider -k "trt48_ or trt43_ or tracing_focus_5_ or vt27_"
python3 -m pytest tests/test_fleet_tracing.py tests/test_fleet_vision.py tests/test_fleet_integration.py -q -p no:cacheprovider
/usr/bin/python3 -m py_compile bin/qwen-agentd tests/fleet_testutil.py tests/test_fleet_vision.py tests/test_fleet_tracing.py && python3 -m py_compile bin/qwen-agentd tests/fleet_testutil.py tests/test_fleet_vision.py tests/test_fleet_tracing.py && echo compile-ok
```

Expected: `4 passed, 21 deselected`; `62 passed in ...` (12 in `test_fleet_tracing.py` at this point, 13 in `test_fleet_vision.py`, 37 in `test_fleet_integration.py`); `compile-ok`. The second line includes [FLEET]'s T43-T48 and [VISION]'s VT20-VT27, which must all still pass (their log lines, argv and forwarded bodies are unchanged apart from VT27's migrated key set).

- [ ] **Step 5: Commit.**

```bash
git add bin/qwen-agentd tests/fleet_testutil.py tests/test_fleet_vision.py tests/test_fleet_tracing.py
git diff --cached --name-only   # expected: the four paths above, each with the qwen-agent-workspace/ prefix
git commit -q -F - <<'EOF'
qwen-agentd: run, agent and delegate spans; trace forwarding with one retry for older peers (tracing TR23-TR25)

TRT43, TRT48, Review Focus 5; VT27 migrated (spec 6.6).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 11: bin/qwen-agent turn, model and tool spans, propagation and the 2 s budget

Implements TR40 (constants and state), TR41 (`_trace_begin`, `_trace_end`, `_trace_post`, `_trace_context`, `_trace_child_env`), TR42 (turn spans in `repl` and `oneshot`; a one-shot that inherits a valid pair posts no turn span), TR43 (model spans in `chat_completion`), TR44 (tool spans in `run_turn`), TR45 (the local child env and the remote `trace` field), TR46 (one shared budget, the first failure stops posting), TR48 and TR49. Tests TRT20 (constants and imports), TRT21, TRT22, TRT23, TRT24, TRT25, TRT27, TRT28.

**Files:**
- Modify: `bin/qwen-agent` — ten edits (after `DECISION_LOG_NAME`; after `FLEET_DAEMON_URL = None`; `exec_delegate_to_skill`'s child env; `_delegate_remote`; the new `# Tracing` section before `# Section 11.1`; the end of `chat_completion`; `run_turn`'s dispatch call; `repl` twice; `oneshot`). No import statement is added.
- Test: `tests/test_qwen_agent_tracing.py` — create.

**Interfaces:**
- Consumes (Tasks 2, 3): through the lazily loaded `FLEET` module only: `trace_env_context`, `new_trace_id`, `new_span_id`, `make_record`, `post_span`, `TRACE_POST_TIMEOUT`, `trace_token`, `trace_name`, `trace_count`, `delegate_once(..., images, trace)`, `trace_record_error` (tests). Existing `_call_key`, `_trace_clip`, `_auto_trace_outcome`, `TOOL_BY_NAME`, `dispatch`'s record. `ftu.StubModelServer`, `ftu.clean_env`, `ftu.free_port`, `ftu.kill_all` in the tests.
- Produces in `bin/qwen-agent`: `TRACE_RING_SIZE = 20`, `TRACE_TURN_BUDGET = 2.0`, `TRACE_ENV_KEYS`, `TRACE_USAGE`, `TURN_TRACE`, `TRACE_RING`; `_trace_begin(name, inherit) -> trace_id or None`; `_trace_end(outcome)`; `_trace_post(kind, span_id, parent, name, start, t0, status, attrs)`; `_trace_context() -> (trace_id, tool span) or None`; `_trace_child_env(env)`; `_trace_model_begin()`, `_trace_model_end(span, args_ns, tools, result, error)`; `_trace_tool_begin()`, `_trace_key(name, args) -> str`, `_trace_tool_end(span, record, round_num)`. In the tests: `T`, `P`, `PNG_BYTES`, `_load()`, the `qa` fixture, `_closed_url()`, `_view(self_skills, peers)`, `_skill(name)`, `_TraceDaemon(view=None, mode="ok", trace_result=None, outcomes=None)` with `.url`, `.spans`, `.requests`, `.posts(path)`, `.trace_result`, `.close()`; `_FakeResp`, `_FakeProc`, `_today_argv`, `_reply(content=None, tool_calls=None, usage=None, finish=None)`, `_state(qa, monkeypatch, tmp_path, daemon_url, view=None, fleet=True, calculate=False) -> workspace`, `_oneshot(qa, monkeypatch, replies, argv=("--user-prompt=go",)) -> (exit code, stdout, stderr, chat bodies)` (all used again by Task 12).

- [ ] **Step 1: Write the failing tests.**

Create `tests/test_qwen_agent_tracing.py` with exactly this content (it ends with a newline):

```python
"""bin/qwen-agent tests for fleet tracing (tracing spec Section 6.4).

Run from the workspace root: python3 -m pytest tests/test_qwen_agent_tracing.py -v
Loads bin/qwen-agent with importlib.machinery.SourceFileLoader, as
tests/test_qwen_agent_fleet.py does. No model server and no real daemon: in-process runs
fake urllib.request.urlopen and replace setup(); every span goes to an in-process loopback
fake daemon; HOME is a temp directory; QWEN_AGENT_DAEMON_URL (subprocesses) and
qa.FLEET_DAEMON_URL (in-process) always point at a test daemon or a closed port.
"""

import ast
import base64
import builtins
import contextlib
import http.server
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
QA_PATH = os.path.join(WS, "bin", "qwen-agent")
sys.path.insert(0, WS)
import fleet_lib  # noqa: E402
import fleet_testutil as ftu  # noqa: E402

T = "4bf92f3577b34da6a3ce929d0e0e4736"
P = "53995c3f42cd8ad8"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 8
_OK = {"schema": "qwen-agent.oneshot.v1", "status": "ok", "answer": "REMOTE", "error": None,
       "rounds": 1, "tool_calls": []}
_LOCAL_LINE = ('{"schema": "qwen-agent.oneshot.v1", "status": "ok", "answer": "LOCAL", "error": null, '
               '"rounds": 1, "tool_calls": []}\n')


def _load(path=QA_PATH, name="qwen_agent_tracing_under_test"):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _closed_url():
    return "http://127.0.0.1:%d" % ftu.free_port()


@pytest.fixture
def qa(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("QWEN_AGENT_SEARXNG_URL", raising=False)
    monkeypatch.delenv("QWEN_AGENT_TRACE_ID", raising=False)
    monkeypatch.delenv("QWEN_AGENT_PARENT_SPAN", raising=False)
    monkeypatch.setenv("QWEN_AGENT_DAEMON_URL", _closed_url())
    return _load()


@pytest.fixture(autouse=True)
def _reap_processes():
    yield
    ftu.kill_all()


def _skill(name):
    return {"skill": name, "model": "m", "verified": True, "busy": False}


def _view(self_skills, peers):
    return {"schema": "qwen-agentd.peers.v1",
            "self": {"host_id": "mac-local", "role": "agent", "version": "dev", "proto": 1,
                     "discovery": "beacon", "skills": self_skills},
            "peers": [{"host_id": h, "address": "127.0.0.1", "port": 1, "role": "agent", "version": "dev",
                       "proto": 1, "compatible": True, "skills": s, "heard_via": "beacon", "age": 0.1}
                      for h, s in peers]}


class _TraceDaemon(object):
    """In-process loopback fake qwen-agentd (tracing spec 6.4).

    GET /peers -> view (default: a valid empty view); GET /trace?id=<id> -> trace_result with
    its trace_id set to <id> (200), or 404 when trace_result is None; POST /spans -> appends the parsed body to .spans and answers 200
    (mode "ok"), 500 ("error"), or 200 after 5 s ("slow"); POST /delegate -> outcomes[host_id]
    = (outcome, envelope). Every request is recorded in .requests as (method, path, body).
    """

    def __init__(self, view=None, mode="ok", trace_result=None, outcomes=None):
        self.view = view if view is not None else _view([], [])
        self.mode, self.trace_result, self.outcomes = mode, trace_result, outcomes or {}
        self.requests, self.spans = [], []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, raw):
                try:
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except OSError:
                    pass

            def do_GET(self):
                outer.requests.append(("GET", self.path, None))
                if self.path == "/peers":
                    self._send(200, json.dumps(outer.view).encode())
                elif self.path.startswith("/trace?id=") and outer.trace_result is not None:
                    result = dict(outer.trace_result, trace_id=self.path[len("/trace?id="):])
                    self._send(200, json.dumps(result).encode())
                else:
                    self._send(404, b"")

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                outer.requests.append(("POST", self.path, body))
                if self.path == "/spans":
                    outer.spans.append(body)
                    if outer.mode == "slow":
                        time.sleep(5)
                    self._send(500 if outer.mode == "error" else 200, b'{"ok": true}')
                    return
                outcome, envelope = outer.outcomes.get(body.get("host_id"), ("not_live", None))
                self._send(200, json.dumps({"outcome": outcome, "envelope": envelope, "detail": ""}).encode())

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def posts(self, path):
        return [b for m, p, b in self.requests if (m, p) == ("POST", path)]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class _FakeResp(object):
    def __init__(self, data):
        self._buf = io.BytesIO(data)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._buf.read()


class _FakeProc(object):
    """subprocess.Popen stand-in for a local --skill child: records argv and env."""
    calls = []

    def __init__(self, argv, **kwargs):
        _FakeProc.calls.append((argv, kwargs.get("env")))
        self.pid = 999999
        self.returncode = 0

    def communicate(self, timeout=None):
        return _LOCAL_LINE, ""


def _today_argv(qa, args_ns, skill, task, workspace):
    return [sys.executable, os.path.realpath(sys.argv[0]), "--skill=%s" % skill, "--user-prompt=%s" % task,
            "--workspace=%s" % workspace, "--base-url=%s" % args_ns.base_url, "--model=%s" % args_ns.model,
            "--max-tokens", str(args_ns.max_tokens), "--request-timeout", str(args_ns.request_timeout),
            "--max-rounds", str(args_ns.max_rounds), "--tool-timeout", str(args_ns.tool_timeout),
            "--context-window", str(qa.CONTEXT_WINDOW)]


def _reply(content=None, tool_calls=None, usage=None, finish=None):
    """One chat-completions response body."""
    message = {"role": "assistant", "content": content or ""}
    if tool_calls:
        message["tool_calls"] = [{"id": "call_%d" % i, "type": "function",
                                  "function": {"name": name, "arguments": json.dumps(args)}}
                                 for i, (name, args) in enumerate(tool_calls, 1)]
    body = {"choices": [{"index": 0, "message": message,
                         "finish_reason": finish or ("tool_calls" if tool_calls else "stop")}]}
    if usage is not None:
        body["usage"] = {"prompt_tokens": usage[0], "completion_tokens": usage[1], "total_tokens": sum(usage)}
    return body


def _state(qa, monkeypatch, tmp_path, daemon_url, view=None, fleet=True, calculate=False):
    """Module state as main() leaves it, with setup() replaced; returns the workspace path.

    calculate=True adds the calculate tool, which the top level does not advertise (only the
    skill roles do), so that a one-shot named "oneshot" can make an auto-approved call."""
    ws = os.path.realpath(str(tmp_path / "ws"))
    os.makedirs(ws, exist_ok=True)
    loaded = qa._load_fleet_lib() if fleet else None
    monkeypatch.setattr(qa, "FLEET", loaded)
    monkeypatch.setattr(qa, "FLEET_DAEMON_URL", daemon_url)
    targets = loaded.delegate_enum(qa.DELEGATE_TARGETS[None], view) if (loaded and view) else None
    tools = qa.build_tools_for_context(None, targets) + ([qa._CALCULATE_TOOL] if calculate else [])
    monkeypatch.setattr(qa, "TOOLS", tools)
    monkeypatch.setattr(qa, "TOOL_BY_NAME", dict((t["function"]["name"], t) for t in tools))
    monkeypatch.setattr(qa, "setup", lambda args_ns: setattr(qa, "WORKSPACE", qa.Path(ws)))
    _FakeProc.calls = []
    monkeypatch.setattr(qa.subprocess, "Popen", _FakeProc)
    return ws


def _oneshot(qa, monkeypatch, replies, argv=("--user-prompt=go",)):
    """qa.oneshot() in-process; replies are what urlopen returns (dict, bytes) or raises, in order.
    Returns (exit code, stdout, stderr, the chat request bodies)."""
    queue, bodies = list(replies), []

    def fake_urlopen(req, timeout=None):
        bodies.append(json.loads(req.data.decode("utf-8")))
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            raise item()
        return _FakeResp(item if isinstance(item, bytes) else json.dumps(item).encode())

    monkeypatch.setattr(qa.urllib.request, "urlopen", fake_urlopen)
    args_ns = qa.parse_args(list(argv))
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        with pytest.raises(SystemExit) as e:
            qa.oneshot(args_ns)
    return e.value.code, out.getvalue(), err.getvalue(), bodies


# --- TRT20-TRT25, TRT27, TRT28: spans, propagation, the budget (TR40-TR46, TR48, TR49) ---

def test_trt20_constants_and_unchanged_imports(qa):
    assert qa.TRACE_RING_SIZE == 20
    assert qa.TRACE_TURN_BUDGET == 2.0
    assert qa.TRACE_ENV_KEYS == (fleet_lib.TRACE_ENV_ID, fleet_lib.TRACE_ENV_PARENT)
    assert qa.TRACE_USAGE == "usage: /trace [N | TRACE_ID]  (N from 1 to 20 counts back from the last turn)"
    assert qa.TURN_TRACE is None and qa.TRACE_RING == []
    with open(QA_PATH, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module)
    assert names == {"argparse", "ast", "base64", "datetime", "html.parser", "json", "operator", "os", "re",
                     "signal", "subprocess", "sys", "time", "urllib.error", "urllib.parse", "urllib.request",
                     "uuid", "pathlib"}


def test_trt21_oneshot_posts_model_tool_model_turn(qa, monkeypatch, tmp_path):
    replies = [_reply(tool_calls=[("calculate", {"expression": "2+2"})], usage=(11, 3)),
               _reply("four", usage=(13, 5))]
    sink = _TraceDaemon()
    try:
        _state(qa, monkeypatch, tmp_path, sink.url, calculate=True)
        traced = _oneshot(qa, monkeypatch, replies)
        spans = list(sink.spans)
        _state(qa, monkeypatch, tmp_path, sink.url, calculate=True)
        no_usage = _oneshot(qa, monkeypatch, [_reply(tool_calls=[("calculate", {"expression": "2+2"})]),
                                              _reply("four")])
    finally:
        sink.close()
    _state(qa, monkeypatch, tmp_path, None, fleet=False, calculate=True)
    untraced = _oneshot(qa, monkeypatch, replies)
    assert traced[:2] == untraced[:2] == no_usage[:2] and traced[0] == 0
    assert json.loads(traced[1])["answer"] == "four"
    assert [s["kind"] for s in spans] == ["model", "tool", "model", "turn"]
    model1, tool, model2, turn = spans
    assert all(fleet_lib.trace_record_error(s, posted=True) is None for s in spans)
    assert len(set(s["trace_id"] for s in spans)) == 1
    assert turn["parent_span_id"] is None and (turn["name"], turn["status"]) == ("oneshot", "ok")
    assert turn["attrs"] == {"rounds": 2, "tool_calls": 1}
    assert all(s["parent_span_id"] == turn["span_id"] for s in (model1, tool, model2))
    assert model1["attrs"] == {"call": 1, "tools": True, "prompt_tokens": 11, "completion_tokens": 3,
                               "finish_reason": "tool_calls", "http": None}
    assert model2["attrs"] == {"call": 2, "tools": True, "prompt_tokens": 13, "completion_tokens": 5,
                               "finish_reason": "stop", "http": None}
    assert (model1["name"], model1["status"]) == ("qwen38-6bit", "ok")
    assert (tool["name"], tool["status"]) == ("calculate", "ok")
    assert tool["attrs"] == {"round": 1, "decision": "approved", "key": "2+2", "outcome": "OK: 4", "error": False}
    later = sink.spans[len(spans):]
    assert [s["kind"] for s in later] == ["model", "tool", "model", "turn"]
    assert later[0]["attrs"]["prompt_tokens"] is None and later[0]["attrs"]["completion_tokens"] is None
    assert later[0]["trace_id"] != turn["trace_id"]


def test_trt22_delegations_carry_the_tool_span(qa, monkeypatch, tmp_path):
    view = _view([_skill("analyst")], [("p1", [_skill("researcher")])])
    sink = _TraceDaemon(view=view, outcomes={"p1": ("ok", _OK)})
    try:
        _state(qa, monkeypatch, tmp_path, sink.url, view)
        code, _out, _err, _bodies = _oneshot(qa, monkeypatch, [
            _reply(tool_calls=[("delegate_to_skill", {"skill": "researcher", "task": "find x"})]),
            _reply("done")])
        assert code == 0
        [remote_tool] = [s for s in sink.spans if s["kind"] == "tool"]
        trace_id = remote_tool["trace_id"]
        assert remote_tool["attrs"]["key"] == "skill=researcher"
        assert sink.posts("/delegate") == [{"skill": "researcher", "task": "find x", "host_id": "p1",
                                            "trace": {"trace_id": trace_id,
                                                      "parent_span_id": remote_tool["span_id"]}}]
        ws = _state(qa, monkeypatch, tmp_path, sink.url, view)
        code, _out, _err, _bodies = _oneshot(qa, monkeypatch, [
            _reply(tool_calls=[("delegate_to_skill", {"skill": "analyst", "task": "t"})]), _reply("done")])
        assert code == 0
        local_tool = [s for s in sink.spans if s["kind"] == "tool"][-1]
        [(argv, env)] = _FakeProc.calls
        assert env["QWEN_AGENT_TRACE_ID"] == local_tool["trace_id"] != trace_id
        assert env["QWEN_AGENT_PARENT_SPAN"] == local_tool["span_id"]
        assert argv == _today_argv(qa, qa.parse_args(["--user-prompt=go"]), "analyst", "t", ws)
        assert len(sink.posts("/delegate")) == 1
    finally:
        sink.close()
    _state(qa, monkeypatch, tmp_path, None, fleet=False)
    monkeypatch.setenv("QWEN_AGENT_TRACE_ID", T)
    monkeypatch.setenv("QWEN_AGENT_PARENT_SPAN", P)
    monkeypatch.setattr(qa, "WORKSPACE", qa.Path(os.path.realpath(str(tmp_path / "ws"))))
    monkeypatch.setattr(qa, "ONESHOT", True)
    assert qa.exec_delegate_to_skill({"skill": "analyst", "task": "t"}, qa.parse_args(["--user-prompt=go"])) == \
        "LOCAL"
    [(_argv, env)] = _FakeProc.calls
    assert "QWEN_AGENT_TRACE_ID" not in env and "QWEN_AGENT_PARENT_SPAN" not in env


def _run_skill(home, sink_url, stub, extra_env):
    env = ftu.clean_env(home, QWEN_AGENT_DAEMON_URL=sink_url, **extra_env)
    return subprocess.run([sys.executable, QA_PATH, "--skill=researcher", "--user-prompt=x",
                           "--workspace=%s" % os.path.join(str(home), "ws"), "--base-url=%s" % stub.url,
                           "--model=m"], env=env, capture_output=True, text=True, timeout=120)


def test_trt23_child_inherits_a_valid_trace_only(qa, monkeypatch, tmp_path):
    stub = ftu.StubModelServer("vllm", "m", "ANSWER")
    sink = _TraceDaemon()
    try:
        home = tmp_path / "child"
        home.mkdir()
        proc = _run_skill(home, sink.url, stub, {"QWEN_AGENT_TRACE_ID": T, "QWEN_AGENT_PARENT_SPAN": P})
        assert proc.returncode == 0, proc.stderr
        assert [s["kind"] for s in sink.spans] == ["model"]
        assert (sink.spans[0]["trace_id"], sink.spans[0]["parent_span_id"]) == (T, P)
        assert sink.spans[0]["name"] == "m" and sink.spans[0]["attrs"]["prompt_tokens"] == 1
        for bad in (P.upper(), P[:15]):
            del sink.spans[:]
            proc = _run_skill(home, sink.url, stub, {"QWEN_AGENT_TRACE_ID": T, "QWEN_AGENT_PARENT_SPAN": bad})
            assert proc.returncode == 0, proc.stderr
            assert [s["kind"] for s in sink.spans] == ["model", "turn"]
            turn = sink.spans[1]
            assert (turn["name"], turn["parent_span_id"]) == ("researcher", None) and turn["trace_id"] != T
            assert sink.spans[0]["parent_span_id"] == turn["span_id"]
        del sink.spans[:]
        _state(qa, monkeypatch, tmp_path, sink.url)
        monkeypatch.setenv("QWEN_AGENT_TRACE_ID", T)
        monkeypatch.setenv("QWEN_AGENT_PARENT_SPAN", P)
        lines = ["hello"]
        monkeypatch.setattr(builtins, "input", lambda prompt="": lines.pop(0) if lines else (_ for _ in ()).throw(EOFError()))
        monkeypatch.setattr(qa, "print_banner", lambda *a, **k: None)
        monkeypatch.setattr(qa, "run_turn", lambda messages, args_ns, snapshot: {
            "status": "ok", "answer": "hi", "rounds": 1, "tool_calls": [], "error": None})
        with contextlib.redirect_stdout(io.StringIO()), pytest.raises(SystemExit):
            qa.repl(qa.parse_args([]))
        [turn] = sink.spans
        assert (turn["kind"], turn["name"], turn["parent_span_id"]) == ("turn", "repl", None)
        assert turn["trace_id"] != T and qa.TRACE_RING == [turn["trace_id"]]
    finally:
        sink.close()
        stub.stop()


def test_trt24_trt25_a_failing_daemon_never_changes_the_run(tmp_path):
    stub = ftu.StubModelServer("vllm", "m", "ANSWER")
    results = {}
    sinks = {"slow": _TraceDaemon(mode="slow"), "error": _TraceDaemon(mode="error"), "ok": _TraceDaemon()}
    try:
        for name, url in (("closed", _closed_url()), ("slow", sinks["slow"].url),
                          ("error", sinks["error"].url), ("ok", sinks["ok"].url)):
            home = tmp_path / name
            home.mkdir()
            env = ftu.clean_env(home, QWEN_AGENT_DAEMON_URL=url)
            started = time.monotonic()
            proc = subprocess.run([sys.executable, QA_PATH, "--user-prompt=x",
                                   "--workspace=%s" % (home / "ws"), "--base-url=%s" % stub.url, "--model=m"],
                                  env=env, capture_output=True, text=True, timeout=120)
            results[name] = (proc.returncode, proc.stdout, time.monotonic() - started)
        assert len(set((code, out) for code, out, _t in results.values())) == 1
        assert results["ok"][0] == 0 and json.loads(results["ok"][1])["answer"] == "ANSWER"
        assert results["slow"][2] - results["closed"][2] <= 2.5
        assert len(sinks["slow"].posts("/spans")) == 1 and len(sinks["error"].posts("/spans")) == 1
        assert [s["kind"] for s in sinks["ok"].posts("/spans")] == ["model", "turn"]
    finally:
        for sink in sinks.values():
            sink.close()
        stub.stop()
    found = [os.path.join(d, n) for d, _dirs, names in os.walk(str(tmp_path / "closed"))
             for n in names if n.startswith("trace.jsonl")]
    assert found == []


def test_trt27_no_prompt_task_content_answer_or_image_in_any_span(qa, monkeypatch, tmp_path):
    view = _view([_skill("analyst")], [("p1", [_skill("researcher"), _skill("vision")])])
    sink = _TraceDaemon(view=view, outcomes={"p1": ("ok", _OK)})
    try:
        ws = _state(qa, monkeypatch, tmp_path, sink.url, view)
        for name in ("a.png", "b.png"):
            with open(os.path.join(ws, name), "wb") as f:
                f.write(PNG_BYTES)
        code, out, _err, _bodies = _oneshot(qa, monkeypatch, [
            _reply(tool_calls=[
                ("delegate_to_skill", {"skill": "researcher", "task": "TRSENTINEL-TASK"}),
                ("delegate_to_skill", {"skill": "analyst", "task": "TRSENTINEL-TASK"}),
                ("write_file", {"path": "out.txt", "content": "TRSENTINEL-CONTENT"}),
                ("delegate_to_skill", {"skill": "vision", "task": "TRSENTINEL-TASK",
                                       "images": ["a.png", "b.png"]})]),
            _reply("TRSENTINEL-ANSWER")],
            argv=("--user-prompt=TRSENTINEL-PROMPT", "--danger-auto-approve"))
        assert code == 0 and json.loads(out)["answer"] == "TRSENTINEL-ANSWER"
        with open(os.path.join(ws, "out.txt"), encoding="utf-8") as f:
            assert f.read() == "TRSENTINEL-CONTENT"
        assert [b["host_id"] for b in sink.posts("/delegate")] == ["p1", "p1"]
        assert len(_FakeProc.calls) == 1
        tools = [s for s in sink.spans if s["kind"] == "tool"]
        assert [(s["name"], s["status"]) for s in tools] == [("delegate_to_skill", "ok")] * 2 + [
            ("write_file", "ok"), ("delegate_to_skill", "ok")]
        assert [s["attrs"]["key"] for s in tools] == ["skill=researcher", "skill=analyst", "out.txt",
                                                      "skill=vision images=2"]
        blob = json.dumps(sink.posts("/spans"))
        b64 = base64.b64encode(PNG_BYTES).decode("ascii")
        for needle in ("TRSENTINEL", b64, b64[:40], "a.png", "b.png", "LOCAL", "REMOTE"):
            assert needle not in blob, needle
    finally:
        sink.close()


def test_trt28_model_span_status_for_every_transport_failure(qa, monkeypatch, tmp_path):
    def http_500():
        return urllib.error.HTTPError("http://x/v1/chat/completions", 500, "Internal Server Error", {},
                                      io.BytesIO(b"model exploded"))

    cases = ((http_500, "http_error", 500), (urllib.error.URLError("refused"), "network_error", None),
             (b"not json", "malformed_response", None), (KeyboardInterrupt(), "interrupted", None))
    for failure, status, http in cases:
        sink = _TraceDaemon()
        try:
            _state(qa, monkeypatch, tmp_path, sink.url)
            traced = _oneshot(qa, monkeypatch, [failure])
        finally:
            sink.close()
        _state(qa, monkeypatch, tmp_path, None, fleet=False)
        untraced = _oneshot(qa, monkeypatch, [failure])
        assert traced[:3] == untraced[:3], status
        assert [s["kind"] for s in sink.spans] == ["model", "turn"]
        model, turn = sink.spans
        assert (model["status"], model["attrs"]["http"]) == (status, http)
        assert turn["status"] == json.loads(traced[1])["status"]
        if http == 500:
            assert "[server error 500] model exploded\n" in traced[2]
```

- [ ] **Step 2: Run the new tests to verify they fail.**

```bash
python3 -m pytest tests/test_qwen_agent_tracing.py -q -p no:cacheprovider
```

Expected: `7 failed`; TRT20 fails with `AttributeError: module 'qwen_agent_tracing_under_test' has no attribute 'TRACE_RING_SIZE'`, and every other test because no span is posted (`assert [] == ['model', 'to...odel', 'turn']`, `ValueError: not enough values to unpack (expected 1, got 0)`, `assert [] == ['model']`, `assert (0 == 1)`, `assert [] == [('delegate_t...skill', 'ok')]`, `assert [] == ['model', 'turn']`).

- [ ] **Step 3: Implement.** In `bin/qwen-agent`:

Edit 1 of 10 in `bin/qwen-agent` (base line 224). Replace:

```python
DECISION_LOG_NAME = "tool_decisions.log"     # workspace-relative JSON Lines tool-decision log
```

with:

```python
DECISION_LOG_NAME = "tool_decisions.log"     # workspace-relative JSON Lines tool-decision log
TRACE_RING_SIZE = 20       # REPL turns that /trace N reaches back to (tracing spec TR40)
TRACE_TURN_BUDGET = 2.0    # s, all POST /spans of one turn together; never scaled (tracing spec TR46)
# Each equals its fleet_lib namesake (TRACE_ENV_ID, TRACE_ENV_PARENT); bin/qwen-agent keeps its own
# copy because it must work without fleet_lib (fleet spec F70). Test TRT20 checks that they agree.
TRACE_ENV_KEYS = ("QWEN_AGENT_TRACE_ID", "QWEN_AGENT_PARENT_SPAN")
TRACE_USAGE = "usage: /trace [N | TRACE_ID]  (N from 1 to 20 counts back from the last turn)"
```

Edit 2 of 10 in `bin/qwen-agent` (base lines 658-659). Replace:

```python
FLEET = None
FLEET_DAEMON_URL = None
```

with:

```python
FLEET = None
FLEET_DAEMON_URL = None
TURN_TRACE = None   # the turn being traced (a dict, TR41), or None
TRACE_RING = []     # trace IDs of this REPL session's turns, oldest first, at most TRACE_RING_SIZE
```

Edit 3 of 10 in `bin/qwen-agent` (base line 1427). Replace:

```python
    child_env["QWEN_AGENT_PREFLIGHT_DONE"] = "1"   # see setup(): skips the tools prefill
```

with:

```python
    child_env["QWEN_AGENT_PREFLIGHT_DONE"] = "1"   # see setup(): skips the tools prefill
    _trace_child_env(child_env)
```

Edit 4 of 10 in `bin/qwen-agent` (base lines 1481-1487). Replace:

```python
    current = [None]

    def attempt(host_id):
        current[0] = host_id
        print("[delegating to %s on %s, up to %ds...]" % (skill, host_id, SKILL_SUBPROCESS_TIMEOUT),
              file=_ui())
        outcome, envelope, _detail = FLEET.delegate_once(FLEET_DAEMON_URL, skill, task, host_id, images)
```

with:

```python
    current = [None]
    context = _trace_context()
    trace = None if context is None else {"trace_id": context[0], "parent_span_id": context[1]}

    def attempt(host_id):
        current[0] = host_id
        print("[delegating to %s on %s, up to %ds...]" % (skill, host_id, SKILL_SUBPROCESS_TIMEOUT),
              file=_ui())
        outcome, envelope, _detail = FLEET.delegate_once(FLEET_DAEMON_URL, skill, task, host_id, images, trace)
```

Edit 5 of 10 in `bin/qwen-agent` (base lines 1951-1952). Replace:

```python
# ---------------------------------------------------------------------------
# Section 11.1: wire contract
```

with:

```python
# ---------------------------------------------------------------------------
# Tracing (docs/superpowers/specs/2026-10-17-fleet-tracing-design.md)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Section 11.1: wire contract
```

Edit 6 of 10 in `bin/qwen-agent` (base lines 1993-1994). Replace:

```python
    with urllib.request.urlopen(req, timeout=args_ns.request_timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))
```

with:

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

Edit 7 of 10 in `bin/qwen-agent` (base line 3688). Replace:

```python
            record = dispatch(tc, i, n, args_ns, history)
```

with:

```python
            tool_span = _trace_tool_begin()
            record = dispatch(tc, i, n, args_ns, history)
            _trace_tool_end(tool_span, record, round_num)
```

Edit 8 of 10 in `bin/qwen-agent` (base line 3770). Replace:

```python
        messages.append({"role": "user", "content": line})
```

with:

```python
        messages.append({"role": "user", "content": line})
        trace_id = _trace_begin("repl", False)
        if trace_id is not None:
            TRACE_RING.append(trace_id)
            del TRACE_RING[:-TRACE_RING_SIZE]
```

Edit 9 of 10 in `bin/qwen-agent` (base lines 3793-3795). Replace:

```python
            )

        # The harness-enforced memory write. Deliberately the LAST thing in the
```

with:

```python
            )
        _trace_end(outcome)

        # The harness-enforced memory write. Deliberately the LAST thing in the
```

Edit 10 of 10 in `bin/qwen-agent` (base line 3886). Replace:

```python
    outcome = run_turn(messages, args_ns, 1)
```

with:

```python
    _trace_begin(args_ns.skill or "oneshot", True)
    outcome = run_turn(messages, args_ns, 1)
    _trace_end(outcome)
```

- [ ] **Step 4: Run the tests, the other harness suites, the three plain scripts and both compilers.**

```bash
python3 -m pytest tests/test_qwen_agent_tracing.py -q -p no:cacheprovider
python3 -m pytest tests/test_qwen_agent_fleet.py tests/test_qwen_agent_vision.py tests/test_qwen_agent_danger_auto_approve.py -q -p no:cacheprovider
for f in test_qwen_agent_context_budget test_qwen_agent_image_oneshot test_qwen_agent_session_memory; do printf "%s: " "$f"; python3 tests/$f.py 2>&1 | tail -1; done
/usr/bin/python3 -m py_compile bin/qwen-agent tests/test_qwen_agent_tracing.py && python3 -m py_compile bin/qwen-agent tests/test_qwen_agent_tracing.py && echo compile-ok
```

Expected: `7 passed`; `32 passed`; `test_qwen_agent_context_budget: OK 68/68`, `test_qwen_agent_image_oneshot: OK 25/25`, `test_qwen_agent_session_memory: OK 205/205`; `compile-ok`. If a plain script's count changes, stop and report (C8 and M14 live there).

- [ ] **Step 5: Commit.**

```bash
git add bin/qwen-agent tests/test_qwen_agent_tracing.py
git diff --cached --name-only   # expected: qwen-agent-workspace/bin/qwen-agent, qwen-agent-workspace/tests/test_qwen_agent_tracing.py
git commit -q -F - <<'EOF'
qwen-agent: turn, model and tool spans within a 2 s per-turn budget; trace propagation to delegations (tracing TR40-TR46, TR48, TR49)

TRT20-TRT25, TRT27, TRT28.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 12: bin/qwen-agent /trace in the REPL

Implements TR47 (the `/help` line, the `/trace` branch of `handle_slash_command`, `slash_trace`). Tests TRT20 (the `/help` line), TRT26, Review Focus 3.

**Files:**
- Modify: `bin/qwen-agent` — three edits (`HELP_TEXT`; after `slash_resume`; `handle_slash_command`).
- Test: `tests/test_qwen_agent_tracing.py` — one appended block.

**Interfaces:**
- Consumes (Tasks 3, 5, 11): `FLEET.fetch_trace`, `FLEET.render_trace`, `FLEET.valid_trace_id`, `TRACE_RING`, `TRACE_RING_SIZE`, `TRACE_USAGE`; `_TraceDaemon`, `_state`, `_reply`, `_FakeResp`, `_closed_url`, `T` in the tests.
- Produces: `slash_trace(raw) -> [str]`; `/trace`, `/trace N`, `/trace <id>` in the REPL. In the tests: `_HELP_LINE`, `_canned()`, `_repl(qa, monkeypatch, lines, run_turn=None) -> stdout`.

- [ ] **Step 1: Write the failing tests.**

Append to the end of `tests/test_qwen_agent_tracing.py` (after its current last line, base line 466; add two empty lines, then this block, which ends with a newline):

```python
# --- TRT26 and the /help line: /trace in the REPL (TR47) ----------------------------------

_HELP_LINE = "  /trace      Show a turn's trace: /trace (last turn), /trace N (N turns back), /trace <id>"


def _canned():
    """A valid GET /trace?id= result with one turn record; the fake daemon sets its trace_id."""
    turn = fleet_lib.make_record(T, "1000000000000001", None, "mac-local", "turn", "repl", 1760000000.0, 0.0,
                                 "ok", {"rounds": 1, "tool_calls": 0}, now=1.5)
    return {"schema": fleet_lib.TRACE_SCHEMA, "trace_id": T, "records": [turn], "missing": [], "truncated": []}


def _repl(qa, monkeypatch, lines, run_turn=None):
    """qa.repl() over scripted input lines; run_turn is faked unless given. Returns stdout."""
    feed = list(lines)

    def fake_input(prompt=""):
        if not feed:
            raise EOFError
        return feed.pop(0)

    monkeypatch.setattr(builtins, "input", fake_input)
    monkeypatch.setattr(qa, "print_banner", lambda *a, **k: None)
    monkeypatch.setattr(qa, "memory_checkpoint", lambda *a, **k: None)
    monkeypatch.setattr(qa, "TRACE_RING", [])
    if run_turn is None:
        monkeypatch.setattr(qa, "run_turn", lambda messages, args_ns, snapshot: {
            "status": "ok", "answer": "hi %d" % len(messages), "rounds": 1, "tool_calls": [], "error": None})
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        with pytest.raises(SystemExit):
            qa.repl(qa.parse_args([]))
    return out.getvalue()


def test_trt20_help_lists_trace(qa):
    lines = qa.HELP_TEXT.splitlines()
    i = [n for n, line in enumerate(lines) if line.startswith("  /remember")][0]
    assert lines[i + 1] == _HELP_LINE


def test_trt26_slash_trace(qa, monkeypatch, tmp_path):
    sink = _TraceDaemon(trace_result=_canned())
    other = "5" * 32
    try:
        _state(qa, monkeypatch, tmp_path, sink.url)
        out = _repl(qa, monkeypatch, ["/trace", "hello", "/trace", "/trace 1", "/trace 2", "/trace 21",
                                      "/trace 0", "/trace xyz", "/trace   %s  " % other])
        [turn] = sink.posts("/spans")
        ring_id = turn["trace_id"]
        tree = "\n".join(qa.FLEET.render_trace(dict(_canned(), trace_id=ring_id))) + "\n"
        tree_other = "\n".join(qa.FLEET.render_trace(dict(_canned(), trace_id=other))) + "\n"
        usage = qa.TRACE_USAGE + "\n"
        assert out == ("no turns in this session yet\n" + "hi 2\n" + tree + tree +
                       "only 1 turn in this session\n" + usage * 3 + tree_other + "\n")
        gets = [p for m, p, _b in sink.requests if m == "GET" and p.startswith("/trace")]
        assert gets == ["/trace?id=" + ring_id] * 2 + ["/trace?id=" + other]
        sink.trace_result = None
        out = _repl(qa, monkeypatch, ["hello", "/trace"])
        assert out == "hi 2\nthe daemon at %s has no trace support (http 404)\n\n" % sink.url
        sink.trace_result = _canned()
        out = _repl(qa, monkeypatch, ["hello"] * 25)
        turn_ids = [s["trace_id"] for s in sink.posts("/spans")[-25:]]
        assert len(set(turn_ids)) == 25 and qa.TRACE_RING == turn_ids[-20:]
        traced_turns = out
    finally:
        sink.close()
    closed = _closed_url()
    _state(qa, monkeypatch, tmp_path, closed)
    assert _repl(qa, monkeypatch, ["hello", "/trace"]) == "hi 2\ndaemon not reachable at %s\n\n" % closed
    monkeypatch.setattr(qa, "FLEET_DAEMON_URL", None)
    assert _repl(qa, monkeypatch, ["/trace"]) == "tracing is off: QWEN_AGENT_DAEMON_URL is not usable\n\n"
    _state(qa, monkeypatch, tmp_path, None, fleet=False)
    assert _repl(qa, monkeypatch, ["hello", "/trace"]) == "hi 2\ntracing is off: fleet_lib.py is not available\n\n"
    assert _repl(qa, monkeypatch, ["hello"] * 25) == traced_turns
    assert qa.TRACE_RING == []


def test_tracing_focus_3_an_interrupted_repl_turn_is_still_traced(qa, monkeypatch, tmp_path):
    """Review Focus 3: Ctrl-C while the model is answering a REPL turn. Expected: the turn
    still gets a trace (its model span and turn span say "interrupted"), the next turn gets a
    new trace, and /trace 2 reaches the interrupted one."""
    sink = _TraceDaemon(trace_result=_canned())
    try:
        _state(qa, monkeypatch, tmp_path, sink.url)
        replies = [KeyboardInterrupt(), _reply("second answer")]
        monkeypatch.setattr(qa.urllib.request, "urlopen",
                            lambda req, timeout=None: (_ for _ in ()).throw(replies.pop(0))
                            if isinstance(replies[0], BaseException) else _FakeResp(json.dumps(replies.pop(0)).encode()))
        out = _repl(qa, monkeypatch, ["first", "second", "/trace 2"], run_turn=qa.run_turn)
        spans = sink.posts("/spans")
        assert [(s["kind"], s["status"]) for s in spans] == [("model", "interrupted"), ("turn", "interrupted"),
                                                             ("model", "ok"), ("turn", "ok")]
        first, second = spans[1]["trace_id"], spans[3]["trace_id"]
        assert first != second and qa.TRACE_RING == [first, second]
        assert spans[0]["trace_id"] == first and spans[0]["parent_span_id"] == spans[1]["span_id"]
        assert out.startswith("second answer\n")
        assert [p for m, p, _b in sink.requests if m == "GET" and p.startswith("/trace")] == ["/trace?id=" + first]
    finally:
        sink.close()
```

- [ ] **Step 2: Run the new tests to verify they fail.**

```bash
python3 -m pytest tests/test_qwen_agent_tracing.py -q -p no:cacheprovider -k "trt20_help or trt26_ or tracing_focus_3_"
```

Expected: `3 failed, 7 deselected`; the `/help` test fails with `assert '' == '  /trace    ..., /trace <id>'`, TRT26 and Review Focus 3 because every `/trace` line prints `unknown command: /trace (try /help)`.

- [ ] **Step 3: Implement.** In `bin/qwen-agent`:

Edit 1 of 3 in `bin/qwen-agent` (base line 2429). Replace:

```python
  /remember   Add one line to long-term memory: /remember <text>
```

with:

```python
  /remember   Add one line to long-term memory: /remember <text>
  /trace      Show a turn's trace: /trace (last turn), /trace N (N turns back), /trace <id>
```

Edit 2 of 3 in `bin/qwen-agent` (base lines 2530-2531). Replace:

```python
    print("[resumed from %d checkpoint(s) in %s; ~%d tokens reloaded]"
          % (count, source, estimate_tokens(messages[1:], include_tools=False)))
```

with:

```python
    print("[resumed from %d checkpoint(s) in %s; ~%d tokens reloaded]"
          % (count, source, estimate_tokens(messages[1:], include_tools=False)))


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

Edit 3 of 3 in `bin/qwen-agent` (base lines 2644-2646). Replace:

```python
            print("memory is disabled for this session.")
    else:
        print("unknown command: %s (try /help)" % cmd)
```

with:

```python
            print("memory is disabled for this session.")
    elif cmd == "/trace" or cmd.startswith("/trace "):
        for out_line in slash_trace(cmd[len("/trace"):]):
            print(out_line)
    else:
        print("unknown command: %s (try /help)" % cmd)
```

- [ ] **Step 4: Run the tests, the file, the three plain scripts and both compilers.**

```bash
python3 -m pytest tests/test_qwen_agent_tracing.py -q -p no:cacheprovider -k "trt20_help or trt26_ or tracing_focus_3_"
python3 -m pytest tests/test_qwen_agent_tracing.py -q -p no:cacheprovider
for f in test_qwen_agent_context_budget test_qwen_agent_image_oneshot test_qwen_agent_session_memory; do printf "%s: " "$f"; python3 tests/$f.py 2>&1 | tail -1; done
/usr/bin/python3 -m py_compile bin/qwen-agent tests/test_qwen_agent_tracing.py && python3 -m py_compile bin/qwen-agent tests/test_qwen_agent_tracing.py && echo compile-ok
```

Expected: `3 passed, 7 deselected`; `10 passed`; `test_qwen_agent_context_budget: OK 68/68`, `test_qwen_agent_image_oneshot: OK 25/25`, `test_qwen_agent_session_memory: OK 205/205`; `compile-ok`.

- [ ] **Step 5: Commit.**

```bash
git add bin/qwen-agent tests/test_qwen_agent_tracing.py
git diff --cached --name-only   # expected: qwen-agent-workspace/bin/qwen-agent, qwen-agent-workspace/tests/test_qwen_agent_tracing.py
git commit -q -F - <<'EOF'
qwen-agent: /trace shows a turn's trace tree from the local daemon (tracing TR47)

TRT20 (/help), TRT26, Review Focus 3.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 13: Integration: the three-daemon chain, a stopped peer, sentinels, an unwritable store

Implements no new code; it adds `StubModelServer(..., delegate_task=...)` and the end-to-end tests that span Tasks 2-12: TRT40 (one connected 14-span tree across alpha, bravo, charlie), TRT41b (`--recent` after two chain runs), TRT42 (a stopped peer: warning, placeholder, partial tree, before and after it leaves the live table), TRT47 (no prompt, task, answer, image or secret in any trace file, log, response or CLI output) and TRT49 (an unwritable store never changes a run). Because the code exists, these tests pass on their first run; a failure here is a defect in the owning task: stop and report it with the failing assertion, and do not change the test.

**Files:**
- Test: `tests/fleet_testutil.py` — two edits (`StubModelServer`); `tests/test_fleet_tracing.py` — one appended block.

**Interfaces:**
- Consumes (Tasks 2-12): everything above through the real daemons and the real harness; `ftu.trace`, `ftu.recent`, `ftu.trace_cli`, `ftu.read_records`, `ftu.trace_files`, `_span`, `_post_span`, `_of_kind` in the tests.
- Produces: `StubModelServer(kind, model, answer, delegate_skill=None, port=0, delegate_images=None, delegate_task="stub task")`. In the tests: `CHAIN_ANSWER`, `_chain(tmp_path, prompt="go", tasks=("stub task", "stub task"), before_start=None) -> (fleet, proc, trace_id or None)`, `_harness(fleet, tmp_path, prompt="go")`, `_newest(fleet)`, `_depth(line)`, `_CHAIN_SHAPE`, `_stopped_peer_lines(cli, d_span)`.

- [ ] **Step 1: Write the integration tests.**

Edit 1 of 2 in `tests/fleet_testutil.py` (base lines 128-134). Replace:

```python
    delegate_images, when not None, is added to that tool call's arguments as "images".
    port=0 picks a free port; a fixed port lets a test start the stub late.
    """

    def __init__(self, kind, model, answer, delegate_skill=None, port=0, delegate_images=None):
        self.kind, self.model, self.answer, self.delegate_skill = kind, model, answer, delegate_skill
        self.delegate_images = delegate_images
```

with:

```python
    delegate_images, when not None, is added to that tool call's arguments as "images".
    delegate_task is that tool call's "task" argument.
    port=0 picks a free port; a fixed port lets a test start the stub late.
    """

    def __init__(self, kind, model, answer, delegate_skill=None, port=0, delegate_images=None,
                 delegate_task="stub task"):
        self.kind, self.model, self.answer, self.delegate_skill = kind, model, answer, delegate_skill
        self.delegate_images = delegate_images
        self.delegate_task = delegate_task
```

Edit 2 of 2 in `tests/fleet_testutil.py` (base line 168). Replace:

```python
                    arguments = {"skill": stub.delegate_skill, "task": "stub task"}
```

with:

```python
                    arguments = {"skill": stub.delegate_skill, "task": stub.delegate_task}
```

Append to the end of `tests/test_fleet_tracing.py` (after its current last line, base line 515; add two empty lines, then this block, which ends with a newline):

```python
# --- the chain: three daemons and the real harness end to end (TR17, TR22-TR27, TR42-TR45, TR50) ---

CHAIN_ANSWER = "ALPHA-ANSWER | BRAVO-ANSWER | CHARLIE-ANSWER"


def _chain(tmp_path, prompt="go", tasks=("stub task", "stub task"), before_start=None):
    """alpha's real harness delegates investigator to bravo, whose child delegates analyst to
    charlie (tracing spec 6.5) -> (fleet, harness CompletedProcess, the newest trace ID on
    alpha or None)."""
    fleet = ftu.Fleet(tmp_path, skills={"bravo": ["investigator"]},
                      stub_kwargs={"alpha": {"delegate_skill": "investigator", "delegate_task": tasks[0]},
                                   "bravo": {"delegate_skill": "analyst", "delegate_task": tasks[1]}})
    if before_start is not None:
        before_start(fleet)
    fleet.start()
    ftu.wait_until(fleet.all_see_each_other, 4.5)
    proc = _harness(fleet, tmp_path, prompt)
    return fleet, proc, _newest(fleet)


def _harness(fleet, tmp_path, prompt="go"):
    """The real bin/qwen-agent one-shot on alpha's stub, routed through alpha's daemon."""
    home = tmp_path / "caller"
    home.mkdir(exist_ok=True)
    env = ftu.clean_env(home, QWEN_AGENT_DAEMON_URL=fleet.daemons["alpha"].url)
    return subprocess.run([sys.executable, ftu.QWEN_AGENT, "--user-prompt=" + prompt,
                           "--base-url=%s" % fleet.stubs["alpha"].url, "--model=alpha-model"],
                          env=env, capture_output=True, text=True, timeout=180)


def _newest(fleet):
    status, listed = ftu.recent(fleet.ports["alpha"])
    if status != 200 or not listed["traces"]:
        return None
    return listed["traces"][0]["trace_id"]


def _depth(line):
    return (len(line) - len(line.lstrip(" "))) // 2


_CHAIN_SHAPE = [
    (0, r"turn oneshot  \S+  ok  rounds=2  tools=1  @alpha"),
    (1, r"model alpha-model  \S+  ok  1→1 tok  tool_calls  @alpha"),
    (1, r"tool delegate_to_skill  skill=investigator  \S+  ok  -> ok, \d+ characters  @alpha"),
    (2, r"delegate investigator -> bravo  req=(?P<r1>[0-9a-f]{16})  http=200  \S+  ok  @alpha"),
    (3, r"run investigator  req=(?P<r1b>[0-9a-f]{16})  http=200  \S+  ok  @bravo"),
    (4, r"agent investigator  req=[0-9a-f]{16}  http=200  \S+  ok  @bravo"),
    (5, r"model bravo-model  \S+  ok  1→1 tok  tool_calls  @bravo"),
    (5, r"tool delegate_to_skill  skill=analyst  \S+  ok  -> ok, \d+ characters  @bravo"),
    (6, r"delegate analyst -> charlie  req=(?P<r2>[0-9a-f]{16})  http=200  \S+  ok  @bravo"),
    (7, r"run analyst  req=(?P<r2b>[0-9a-f]{16})  http=200  \S+  ok  @charlie"),
    (8, r"agent analyst  req=[0-9a-f]{16}  http=200  \S+  ok  @charlie"),
    (9, r"model charlie-model  \S+  ok  1→1 tok  stop  @charlie"),
    (5, r"model bravo-model  \S+  ok  1→1 tok  stop  @bravo"),
    (1, r"model alpha-model  \S+  ok  1→1 tok  stop  @alpha"),
]


# The _CHAIN_SHAPE indices in printed order. A model call and the tool call it returned can
# start in the same millisecond (starts are rounded to 1 ms, TR4); TR17 then orders those two
# siblings by span_id, so the tool's subtree may print before the first model line, on alpha
# (index 1 after 12) or on bravo (index 6 after 11), or both.
_CHAIN_ORDERS = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
                 [0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 13],
                 [0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 6, 12, 13],
                 [0, 2, 3, 4, 5, 7, 8, 9, 10, 11, 6, 12, 1, 13]]


def test_trt40_one_connected_tree_across_three_agents(tmp_path):
    fleet, proc, trace_id = _chain(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1])["answer"] == CHAIN_ANSWER
    home, alpha = fleet.homes["alpha"], fleet.ports["alpha"]
    cli = ftu.trace_cli(home, ["--port", str(alpha), trace_id])
    assert cli.returncode == 0, cli.stderr
    lines = cli.stdout.splitlines()
    assert re.fullmatch(r"trace %s  \S+ \S+  \S+  agents: alpha, bravo, charlie  spans: 14" % trace_id[:12],
                        lines[0]), lines[0]
    assert len(lines) == 15 and not any(line.startswith(("!", "…", "(truncated")) for line in lines)
    ids, order = {}, []
    for line in lines[1:]:
        hits = [n for n, (depth, pattern) in enumerate(_CHAIN_SHAPE)
                if depth == _depth(line) and re.fullmatch(pattern, line.strip()) and n not in order]
        assert hits, line
        order.append(hits[0])
        ids.update(re.fullmatch(_CHAIN_SHAPE[hits[0]][1], line.strip()).groupdict())
    assert order in _CHAIN_ORDERS, order
    assert ids["r1"] == ids["r1b"] and ids["r2"] == ids["r2b"]
    assert [_depth(line) for line in lines[1:]].count(0) == 1
    assert "run start skill=investigator request_id=%s task_chars=9 " % ids["r1"] in fleet.daemons["bravo"].log()
    assert "delegate skill=investigator host=bravo request_id=%s outcome=ok" % ids["r1"] in \
        fleet.daemons["alpha"].log()
    cli = ftu.trace_cli(home, ["--port", str(alpha), "--json", trace_id])
    result = json.loads(cli.stdout)
    assert cli.returncode == 0 and len(result["records"]) == 14
    spans = set(r["span_id"] for r in result["records"])
    assert all(r["parent_span_id"] in spans for r in result["records"] if r["parent_span_id"] is not None)
    assert [r["kind"] for r in result["records"]].count("turn") == 1
    assert (result["missing"], result["truncated"]) == ([], [])


def test_trt41b_recent_lists_the_chain_runs(tmp_path):
    fleet, proc, first = _chain(tmp_path)
    assert proc.returncode == 0, proc.stderr
    proc = _harness(fleet, tmp_path)
    assert proc.returncode == 0, proc.stderr
    second = _newest(fleet)
    assert second != first
    home, alpha = fleet.homes["alpha"], str(fleet.ports["alpha"])
    cli = ftu.trace_cli(home, ["--port", alpha, "--recent"])
    lines = cli.stdout.splitlines()
    assert cli.returncode == 0 and len(lines) == 3
    assert lines[0] == "time                 trace id                               dur  status        spans  delegated"
    assert [line.split()[2] for line in lines[1:]] == [second, first]
    for line in lines[1:]:
        assert line.split()[4:] == ["ok", "5", "investigator@bravo"], line
    cli = ftu.trace_cli(home, ["--port", alpha, "--recent", "1"])
    assert cli.returncode == 0 and cli.stdout.splitlines()[1:] == lines[1:2]
    cli = ftu.trace_cli(fleet.homes["bravo"], ["--port", str(fleet.ports["bravo"]), "--recent"])
    assert (cli.returncode, cli.stderr) == (1, "qwen-agentd: no traces recorded on bravo\n")


def _stopped_peer_lines(cli, d_span):
    assert cli.returncode == 0, cli.stderr
    lines = cli.stdout.splitlines()
    assert "! bravo: unreachable (connection refused)" in lines
    i = lines.index("… span %s on bravo (not retrieved)" % d_span)
    assert re.fullmatch(r"  run analyst  req=[0-9a-f]{16}  http=200  \S+  ok  @charlie", lines[i + 1])
    assert re.fullmatch(r"    agent analyst  req=[0-9a-f]{16}  http=200  \S+  ok  @charlie", lines[i + 2])
    assert re.fullmatch(r"      model charlie-model  \S+  ok  1→1 tok  stop  @charlie", lines[i + 3])
    [k] = [n for n, line in enumerate(lines) if line.startswith("    delegate investigator -> bravo")]
    assert _depth(lines[k + 1]) <= 2


def test_trt42_a_stopped_peer_leaves_a_partial_tree(tmp_path):
    fleet, proc, trace_id = _chain(tmp_path)
    assert proc.returncode == 0, proc.stderr
    home, alpha = fleet.homes["alpha"], str(fleet.ports["alpha"])
    result = json.loads(ftu.trace_cli(home, ["--port", alpha, "--json", trace_id]).stdout)
    [d_span] = [r["span_id"] for r in result["records"] if r["kind"] == "delegate" and r["agent"] == "bravo"]
    fleet.daemons["bravo"].kill()
    assert "bravo" in fleet.peer_ids("alpha")
    _stopped_peer_lines(ftu.trace_cli(home, ["--port", alpha, trace_id]), d_span)
    ftu.wait_until(lambda: "bravo" not in fleet.peer_ids("alpha"), 15)
    _stopped_peer_lines(ftu.trace_cli(home, ["--port", alpha, trace_id]), d_span)


def test_trt47_no_prompt_task_answer_image_or_secret_reaches_traces_or_logs(tmp_path):
    fleet, proc, trace_id = _chain(tmp_path / "chain", prompt="go TRSENTINEL-PROMPT",
                                   tasks=("TRSENTINEL-TASK-A", "TRSENTINEL-TASK-B"))
    assert proc.returncode == 0, proc.stderr
    home, alpha = fleet.homes["alpha"], str(fleet.ports["alpha"])
    blobs = [json.dumps(ftu.trace(fleet.ports["alpha"], trace_id)[1]).encode(),
             json.dumps(ftu.recent(fleet.ports["alpha"])[1]).encode()]
    for args in ([trace_id], ["--json", trace_id], ["--recent"]):
        cli = ftu.trace_cli(home, ["--port", alpha] + args)
        assert cli.returncode == 0
        blobs.append(cli.stdout.encode("utf-8"))
    stderr_blobs = []
    for name in fleet.names:
        log_dir = ftu.daemon_log_dir(fleet.homes[name], name)
        for entry in os.listdir(log_dir):
            with open(os.path.join(log_dir, entry), "rb") as f:
                (stderr_blobs if entry == "last-run.stderr" else blobs).append(f.read())
    assert len(ftu.trace_files(home, "alpha")) == 1 and stderr_blobs
    for blob in blobs:
        for needle in (b"TRSENTINEL", b"ALPHA-ANSWER", b"BRAVO-ANSWER", b"CHARLIE-ANSWER"):
            assert needle not in blob, needle
    secrets = (ftu.TEST_TOKEN.encode("ascii"), ftu.TEST_KEY,
               fleet_lib.make_join_string(ftu.TEST_FLEET_ID, ftu.TEST_TOKEN).encode("ascii"))
    for blob in blobs + stderr_blobs:
        for needle in secrets:
            assert needle not in blob

    vision = ftu.Fleet(tmp_path / "vision", names=("alpha", "bravo"), skills={"bravo": ["vision"]},
                       stub_kwargs={"alpha": {"delegate_skill": "vision",
                                              "delegate_images": ["a.png", "b.jpg"]}}).start()
    ftu.wait_until(lambda: fleet_lib.route_candidates("vision", vision.view("alpha")) == ["bravo"], 4.5)
    caller = tmp_path / "vision" / "caller"
    ws = caller / "ws"
    ws.mkdir(parents=True)
    (ws / "a.png").write_bytes(ftu.PNG_BYTES)
    (ws / "b.jpg").write_bytes(ftu.JPEG_BYTES)
    env = ftu.clean_env(caller, QWEN_AGENT_DAEMON_URL=vision.daemons["alpha"].url)
    proc = subprocess.run([sys.executable, ftu.QWEN_AGENT, "--user-prompt=go", "--workspace=%s" % ws,
                           "--base-url=%s" % vision.stubs["alpha"].url, "--model=alpha-model"],
                          env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    needles = [ftu.PNG_BYTES, ftu.JPEG_BYTES]
    for data in (ftu.PNG_BYTES, ftu.JPEG_BYTES):
        needles.append(base64.b64encode(data)[:40])
    for name in vision.names:
        paths = ftu.trace_files(vision.homes[name], name)
        assert paths, name
        for path in paths:
            with open(path, "rb") as f:
                blob = f.read()
            for needle in needles:
                assert needle not in blob, (path, needle[:12])
    keys = [r["attrs"]["key"] for r in ftu.read_records(vision.homes["alpha"], "alpha") if r["kind"] == "tool"]
    assert keys == ["skill=vision images=2"]


def test_trt49_an_unwritable_store_never_changes_a_run(tmp_path):
    def store_is_a_directory(fleet):
        os.makedirs(os.path.join(ftu.daemon_log_dir(fleet.homes["alpha"], "alpha"), "trace.jsonl"))

    fleet, proc, trace_id = _chain(tmp_path, before_start=store_is_a_directory)
    assert proc.returncode == 0, proc.stderr
    envelope = json.loads(proc.stdout.strip().splitlines()[-1])
    assert (envelope["status"], envelope["answer"]) == ("ok", CHAIN_ANSWER)
    assert trace_id is None
    assert _post_span(fleet.ports["alpha"], _span()) == (200, b'{"ok":true}')
    assert fleet.daemons["alpha"].log().count("trace: cannot write ") == 1
    assert [r["kind"] for r in ftu.read_records(fleet.homes["bravo"], "bravo")].count("run") == 1
```

- [ ] **Step 2: Run them (about 35 s).**

```bash
python3 -m pytest tests/test_fleet_tracing.py -q -p no:cacheprovider -k "trt40_ or trt41b_ or trt42_ or trt47_ or trt49_"
```

Expected: `5 passed, 12 deselected in ...` (about 30 s).

- [ ] **Step 3: Run both tracing files three times (flakiness check, about 2.5 min) and both compilers.**

```bash
for i in 1 2 3; do python3 -m pytest tests/test_fleet_tracing.py tests/test_qwen_agent_tracing.py -q -p no:cacheprovider 2>&1 | tail -1; done
/usr/bin/python3 -m py_compile tests/fleet_testutil.py tests/test_fleet_tracing.py && python3 -m py_compile tests/fleet_testutil.py tests/test_fleet_tracing.py && echo compile-ok
```

Expected: `27 passed in ...` three times; `compile-ok`.

- [ ] **Step 4: Commit.**

```bash
git add tests/fleet_testutil.py tests/test_fleet_tracing.py
git diff --cached --name-only   # expected: qwen-agent-workspace/tests/fleet_testutil.py, qwen-agent-workspace/tests/test_fleet_tracing.py
git commit -q -F - <<'EOF'
tests: tracing end to end across three daemons, a stopped peer, sentinels, an unwritable store (tracing TR17, TR21-TR27, TR42-TR45, TR50)

TRT40, TRT41b, TRT42, TRT47, TRT49.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 14: Regression, dual-interpreter compile, imports, untouched files, leak checks, gate, final review (no code)

Implements TRT60, TRT61, TRT62, TRT63 and the deliverable check of spec 0.3. No file is changed; nothing is committed unless a defect is found (then fix it in the task that owns it, with that task's commit prefix, and re-run this task).

**Files:** none modified. Reads Task 1's records.

**Interfaces:** Consumes every earlier task. Produces `/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-tracing/final-pytest.txt`.

- [ ] **Step 1: TRT60, the full suite (about 9 min).**

```bash
D=/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-tracing
python3 -m pytest tests/ -q -rA -p no:cacheprovider > $D/final-pytest.txt 2>&1
tail -1 $D/final-pytest.txt
grep -E '^(FAILED|ERROR|SKIPPED)' $D/final-pytest.txt
comm -23 <(grep '^PASSED' $D/baseline-pytest.txt | sort) <(grep '^PASSED' $D/final-pytest.txt | sort)
comm -13 <(grep '^PASSED' $D/baseline-pytest.txt | sort) <(grep '^PASSED' $D/final-pytest.txt | sort) | wc -l
```

Expected: `1 failed, 1255 passed, 1 skipped, 274 warnings in ...` (the baseline's 1214 passed plus 41); the only `FAILED` line is `FAILED tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and the only `SKIPPED` line is `SKIPPED [1] tests/test_fleet_lib.py:272: no fleet.env on this host` (T25); the first `comm` prints nothing (every baseline pass still passes, including the migrated VT27); the second prints `41` (14 in `test_fleet_lib.py`, 17 in `test_fleet_tracing.py`, 10 in `test_qwen_agent_tracing.py`).

- [ ] **Step 2: TRK1's plain scripts.**

```bash
D=/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-tracing
for f in test_qwen_agent_context_budget test_qwen_agent_image_oneshot test_qwen_agent_session_memory; do
  printf '%s: ' "$f"; python3 tests/$f.py 2>&1 | tail -1
done | diff $D/baseline-scripts.txt - && echo scripts-same
```

Expected: `scripts-same` (`OK 68/68`, `OK 25/25`, `OK 205/205`).

- [ ] **Step 3: TRT61, both interpreters.**

```bash
/usr/bin/python3 -m py_compile fleet_lib.py bin/qwen-agent bin/qwen-agentd bin/qwen-agentd-launch && echo py39-ok
python3 -m py_compile fleet_lib.py bin/qwen-agent bin/qwen-agentd bin/qwen-agentd-launch && echo py313-ok
/usr/bin/python3 -m py_compile tests/fleet_testutil.py tests/test_fleet_lib.py tests/test_fleet_vision.py tests/test_fleet_tracing.py tests/test_qwen_agent_tracing.py && echo tests-py39-ok
python3 -m py_compile tests/fleet_testutil.py tests/test_fleet_lib.py tests/test_fleet_vision.py tests/test_fleet_tracing.py tests/test_qwen_agent_tracing.py && echo tests-py313-ok
```

Expected: `py39-ok`, `py313-ok`, `tests-py39-ok`, `tests-py313-ok`.

- [ ] **Step 4: TRT62, imports and HTTP clients.**

```bash
D=/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-tracing
grep -h "^import \|^from " fleet_lib.py bin/qwen-agentd | diff $D/baseline-imports.txt -; echo "imports rc=$?"
grep -n -E "urllib\.request|urlopen" fleet_lib.py bin/qwen-agentd; echo "urllib rc=$?"
git diff $(cat $D/base-commit.txt) -- bin/qwen-agent | grep -E '^[-+](import |from )'; echo "qa-imports rc=$?"
```

Expected, exactly:

```text
9a10
> import secrets
imports rc=1
urllib rc=1
qa-imports rc=1
```

- [ ] **Step 5: TRT63, untouched files and the exact change set (run from the repo root).**

```bash
cd /Users/reubenpatterson/local_agent_harness
BASE=$(cat .superpowers/sdd/2026-10-17-tracing/base-commit.txt)
git diff --quiet $BASE -- agent README.md qwen-agent-workspace/tests/test_researcher_think_off.py qwen-agent-workspace/scripts qwen-agent-workspace/bin/qwen-agentd-launch qwen-agent-workspace/docs/superpowers/specs && echo untouched-ok
git diff --name-only $BASE..HEAD
git log --format=%s $BASE..HEAD | grep -c "(tracing TR"
git diff $BASE..HEAD -- qwen-agent-workspace/tests/test_fleet_vision.py | grep -c '^[-+] '
cd qwen-agent-workspace
test -x bin/qwen-agentd && test -x bin/qwen-agent && echo modes-ok
```

Expected: `untouched-ok`; the name list is exactly `qwen-agent-workspace/bin/qwen-agent`, `qwen-agent-workspace/bin/qwen-agentd`, `qwen-agent-workspace/fleet_lib.py`, `qwen-agent-workspace/tests/fleet_testutil.py`, `qwen-agent-workspace/tests/test_fleet_lib.py`, `qwen-agent-workspace/tests/test_fleet_tracing.py`, `qwen-agent-workspace/tests/test_fleet_vision.py`, `qwen-agent-workspace/tests/test_qwen_agent_tracing.py` (plus this plan file, `qwen-agent-workspace/docs/superpowers/plans/2026-10-17-fleet-tracing.md`, only if it was committed after `BASE`); `12`; `2` (VT27's one line, removed and added); `modes-ok`.

- [ ] **Step 6: TR21 and TR50, the one new log line and no text in any record shape.**

```bash
grep -n "LOG\." bin/qwen-agentd | grep -i "trace"
grep -n "LOG\." bin/qwen-agentd | grep -c "trace_id"
grep -n -E "QWEN_AGENT_FLEET_TOKEN|fleet\.env" bin/qwen-agent; echo "qa-secret rc=$?"
python3 -c "import sys; sys.path.insert(0, '.'); import fleet_lib; print(sorted((k, a) for k, s in fleet_lib._TRACE_ATTRS.items() for a, t in s.items() if t.rstrip('?') == 'text'))"
```

Expected: exactly one line, `LOG.warning("trace: cannot write %s: %s" % (self.trace_store.path, type(e).__name__))` (TR21's WARNING, the only new log line); `0`; `qa-secret rc=1` with nothing printed before it (T35's guard, unchanged); `[('tool', 'key'), ('tool', 'outcome')]` (TR50: the only free-text attributes). TRT27 (Task 11) and TRT47 (Task 13), both in Step 1, are the checks on real records, logs, responses and CLI output.

- [ ] **Step 7: The gate by hand.**

```bash
python3 bin/qwen-agentd selftest | tail -1
```

Expected: `72 passed, 1 skipped in ...` (the gate's selftest is `tests/test_fleet_lib.py`, 58 + 14 tracing tests; T25 skips because there is no `~/agents`).

- [ ] **Step 8: Code review.** Dispatch a `design-reviewer` (Opus, high effort) over `git diff $(cat /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-tracing/base-commit.txt)..HEAD` with this plan and the spec. It must check at minimum: the five Review Focus items; TR4/TR50 (no record field can hold task text, a prompt, an answer, a tool result beyond `_auto_trace_outcome`, an image or base64; `/spans` accepts only `turn`, `model`, `tool` without `agent`); TR48 and TRK6 (every trace helper in `bin/qwen-agent` catches its own exceptions, `_trace_post` honours the shared 2 s budget and stops after the first failure, `chat_completion` re-raises the original exception unchanged and never reads an `HTTPError` body); TR23 (the run span is recorded on every exit after the shape check, the agent span only around a started child, `run start`/`run end` lines byte-identical); TR25 (only a verified 400 `{"error": "bad request"}` triggers the one retry, with a new nonce); TR27 (both fan-out rounds are bounded by `TRACE_FANOUT_DEADLINE`, every `missing` reason text matches the spec); that `bin/qwen-agent`'s import statements and `bin/qwen-agentd`'s are unchanged and `fleet_lib.py` adds only `import secrets`; and that the two `_handle` edits are the dispatcher calls only. A NEEDS-FIX verdict comes with an exact patch; apply it in the owning task's files, re-run Steps 1-7, and commit with that task's message prefix.

---

## Coverage

### Requirements (TR) to tasks

| ID | Task(s) | ID | Task(s) |
|---|---|---|---|
| TR1, TR2, TR3 | 2 | TR20 | 6 (path, `spans`), 7 (`trace`), 8 (`trace_query`, `recent`, the two regexes), 10 (`_OPTIONAL_KEYS`) |
| TR4, TR5, TR6 | 2 | TR21, TR22 | 6 |
| TR7, TR8 | 3 | TR23, TR24, TR25 | 10 |
| TR9 | 6 | TR26 | 7 |
| TR10, TR11, TR12 | 4 | TR27, TR28 | 8 |
| TR13 | 5 | TR29 | 9 |
| TR14, TR15 | 3 | TR40-TR46 | 11 |
| TR16, TR17, TR18 | 5 | TR47 | 12 |
| TR48, TR49 | 11, 12, 14 | TR50 | 2 (TRT4), 11 (TRT27), 13 (TRT47), 14 (Step 6) |

### Tests (TRT, migrated VT27, Review Focus) to tasks

| Tests | Task | Tests | Task |
|---|---|---|---|
| TRT1-TRT4 | 2 | TRT41a, Review Focus 2 | 9 |
| TRT5, TRT13 | 3 | TRT43, TRT48, VT27 (migrated), Review Focus 5 | 10 |
| TRT9-TRT11 | 4 | TRT20 (constants, imports), TRT21-TRT25, TRT27, TRT28 | 11 |
| TRT7, TRT8, TRT12, TRT14 | 5 | TRT20 (`/help`), TRT26, Review Focus 3 | 12 |
| TRT6, TRT46, Review Focus 1 | 6 | TRT40, TRT41b, TRT42, TRT47, TRT49 | 13 |
| TRT44 | 7 | TRT60-TRT63 | 1 (baseline), 14 |
| TRT45, fan-out, unreadable store, Review Focus 4 | 8 | | |

### Success criteria (TRK)

| KPI | Automated (task) | Live |
|---|---|---|
| TRK1 | TRT60 (14) | none |
| TRK2 | TRT61 (14, and every task's compile step) | none |
| TRK3 | TRT62 (14), TRT20 (11), C8 and M14 (unchanged tests), `test_review_focus_4_proxy_environment_is_ignored` (unchanged) | none |
| TRK4 | every new test (Tasks 2-13), Step 8 review | none |
| TRK5 | TRT4 (2), TRT27 (11), TRT47 (13), Task 14 Step 6 | TRR3, TRR5 |
| TRK6 | TRT24 (11), TRT28 (11), TRT49 (13) | none |
| TRK7 | none | TRR2 |

---

## Plan decisions (where the spec is silent, split across tasks, or needed a reading)

The spec's design is unchanged. Each item is pinned by code shown in its task.

**Readings of the spec (proposed rulings):**

1. **TRT2's `dur_ms == 1235`** holds only for some `t0`: `make_record` computes `round((now - t0) * 1000)` in floating point, and `now = t0 + 1.2345` gives 1234.4999... (so 1234) for `t0` of 0, 1, 50 or 100, but 1234.50000000003 (so 1235) for `t0 = 1000.0`. `test_trt2_*` uses `t0 = 1000.0`; the builder is the spec's, unchanged.
2. **TRT21's `calculate` call in a one-shot named `oneshot`**: the top level does not advertise `calculate` (only the skill roles do, `build_tools_for_context`), so the call would be `invalid`/`unknown`. The test adds `qa._CALCULATE_TOOL` to the top-level `TOOLS` (`_state(..., calculate=True)`), which keeps the turn name `oneshot` and makes the call auto-approved, as the spec's expected spans require.
3. **TRT26's canned `trace_result`**: `fetch_trace` accepts a result only when its `trace_id` equals the requested one (TR14), and the REPL's ring holds random IDs, so `_TraceDaemon` answers `GET /trace?id=<id>` with `trace_result` and `trace_id` set to `<id>`. The expected output is `render_trace` of that answer.
4. **TRT11's four traces** are read as: one root with delegate spans to `bravo` then `charlie` (`["investigator@bravo", "analyst@charlie"]`, the `charlie` one a failed `busy` attempt, which TR12 lists too), one root with an `ok` local `delegate_to_skill` tool span keyed `skill=analyst` (`["analyst@alpha"]`), one root with no delegation (`[]`), and one trace with no local root (not listed).
5. **TRT41 is split by owning code**: `test_trt41a_*` (Task 9) checks every argument error, the closed port, an unknown ID, a pre-tracing daemon (401) and the tree, `--json` and `--recent` output on one agent with posted spans; `test_trt41b_*` (Task 13) checks the two chain runs (`spans` 5, `delegated` `investigator@bravo`, newest first, `--recent 1`).
6. **TRT20 is split**: the constants and the C8 import set (Task 11, with the code) and the `/help` line (Task 12, `test_trt20_help_lists_trace`).
7. **TRT45 lives in Task 8** (it needs all three loopback trace endpoints) and **TRT6 in Task 6** (with `http_route`, which the daemon needs for `/spans`).
8. **TRT42's "after it leaves alpha's live table"** waits up to 15 s for `bravo` to drop out of alpha's `/peers` (`LIVE_WINDOW` 90 s scaled by 0.1 is 9 s), then queries again; both queries expect the same lines.
9. **TRT47's vision variant** runs its own two-daemon fleet (VT20's) inside the same test, after the chain's checks, and checks every agent's `trace.jsonl*` plus alpha's tool key.
10. **TRT49's "T43's answer"** is read as the chain's normal envelope: status `ok`, answer `ALPHA-ANSWER | BRAVO-ANSWER | CHARLIE-ANSWER`; with alpha's store unwritable the newest-trace lookup returns 500, so the test also checks `_newest` is `None`, and that bravo still recorded its run span.
11. **TRT48 runs in Task 10, before Task 11**, so the envelope child posts nothing yet; after Task 11 it also posts a model span under the agent span, and the test still holds (it asserts no `turn` record and the parent chain, not the record count).
12. **TRT40's "the lines in order match"** allows the one variation TR17 itself produces: span starts are rounded to 1 ms (TR4), so a model call and the tool call it returned can start in the same millisecond, and TR17 then orders those two siblings by `span_id`, printing the tool's subtree first. Observed once in about ten chain runs during pre-testing. `_CHAIN_ORDERS` lists the four printed orders this allows (alpha's pair, bravo's pair, both); every other order, every depth and every line pattern is still exact.

**Values chosen by this plan:**

13. Placement in `fleet_lib.py`'s new last section, in task order: IDs, record, sanitizers (Task 2); `valid_trace_field`, `trace_context`, `trace_env_context`, `_json_loads_or_none`, `valid_trace_result`, `_RECENT_KEYS`, `valid_recent_result`, `post_span`, `_loopback_get`, `_loopback_result`, `fetch_trace`, `fetch_recent` (Task 3); `TraceStore` (Task 4); `peer_trace_result`, `merge_records`, the renderers (Task 5). `_post_delegate` sits directly before `delegate_once`; `build_child_env`, `_ROUTES`, `http_route` and `body_cap` are edited in place.
14. `valid_trace_result` and `valid_recent_result` are written from TR14's prose, each inside one `try`/`except Exception: return False`; `_RECENT_KEYS` is the TR12 entry key set.
15. `TRACE_USAGE` arrives in Task 11 with the other TR40 constants (the block is copied whole), and is first used in Task 12.
16. The dispatcher branches arrive with their handlers (`spans` in Task 6, `trace` in Task 7, `trace_query` and `recent` in Task 8); `record_span` and `_trace_write_failed` arrive in Task 6 (TR21) and are first called by `handle_spans` there, by the run, agent and delegate spans in Task 10.
17. `spawn_run`'s docstring gains two lines naming `trace` (TR23); no other docstring or comment outside the spec's code changes.
18. Test-only helpers: `fleet_testutil.recent` uses a 30 s timeout like `trace` (the spec gives none); `read_records` reads backups oldest first (`.3`, `.2`, `.1`, then the current file); `trace_files` returns `[]` when the log directory does not exist.
19. Extra tests beyond the TRT list, each in its owning task: `test_tr27_fanout_two_rounds_and_missing_reasons` (round 2 to a registered stopped agent and `not in the registry`, by appending delegate records to alpha's store file), `test_tr26_to_tr28_unreadable_store_answers_500` (the three 500 rows and the one WARNING), and the five `test_tracing_focus_<n>_*` tests (named so they do not collide with the earlier plans' `test_review_focus_<n>_*`, `test_multi_agent_focus_<n>_*` and `test_vision_focus_<n>_*`).
20. `test_fleet_lib.py` defines its own record fixtures (`TR_TRACE`, `_tr_attrs`, `_tr_record`, `_tr_span`) instead of importing `tests/fleet_testutil.py`, because it is the gate's selftest and stays self-contained. TRT13's slow server sleeps 3 s, so `test_fleet_lib.py` takes about 3 s longer.
21. Every new test file imports what later tasks need in its Create step, so later tasks only append.

**Known residual risks (not covered by any automated test):** real vLLM/Ollama `usage` counts, the REPL against the real fleet, a real LAN timeout and the 5 MB rotation at scale (TRR2-TRR5 and TRT1's constant check only); TRX1-TRX8 of spec Section 11, accepted by the user (non-UTF-8 terminals, nested 2 s budgets, skewed sibling order, free-text tool keys, read latency, the `?` placeholder, replayable queries, dropped spans).

---

## Rollout (human-run, after Task 14; not an executor task)

Spec Section 9, steps TRR1-TRR5, run by a human after [FLEET] R10 and [VISION] VR6, with no new port, firewall rule, service, secret or registry change: TRR1 (release: TRT60-TRT63 green, commit, push, `git tag v<YYYY.MM.DD>.<n>`, push the tag; within 30 min `qwen-agentd status --agent-id <id>` shows the version with `update: status=ok` on `mac-local`, `ollama-168`, and at .185's console `vision-185`), TRR2 (the Mac REPL delegates to `researcher` on `ollama-168`; `/trace` shows one connected tree with `agents: mac-local, ollama-168`, one depth-0 `turn repl` line, the `delegate researcher -> ollama-168 ... http=200 ... ok` line with `run`, `agent` and a `model qwen3.5:9b ... stop  @ollama-168` line with non-zero token counts, no `!` line and no placeholder; `<r>` matches .168's `run end` log line; `qwen-agentd trace --agent-id mac-local --json <id>` shows `"missing": []`; this is TRK7), TRR3 (VR4's vision question; `--recent 3` shows `vision@vision-185`; the tree shows `tool delegate_to_skill  skill=vision images=1` and `run vision ... @vision-185`; `grep -c iVBORw0KGgo ~/agents/vision-185/logs/trace.jsonl*` prints `0` per file), TRR4 (stop .168's service; the Mac's `qwen-agentd trace` within 90 s and after 2 min exits 0 with `! ollama-168: unreachable (connection refused)` and the delegate line as a leaf; start it again and the full tree returns) and TRR5 (R9's token grep over `~/agents` prints nothing, and a distinctive word of TRR2's question is in no `trace.jsonl*` on the Mac or .168). These steps run real daemons on 192.168.1.168 and 192.168.1.185, so no executor runs them.
