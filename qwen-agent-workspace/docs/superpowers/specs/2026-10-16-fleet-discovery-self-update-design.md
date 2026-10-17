# qwen-agent fleet -- Design Spec (discovery, remote skills, self-update)

Date: 2026-10-16
Status: The user approved every design decision in the 2026-10-16 brief (architecture "B", the registry schema, shared-secret trust, beacon + poll discovery, signed HTTP, routing, the researcher port, tag-based self-update with rollback, error handling, testing, KPIs, scope). This document transcribes those decisions and makes them implementable without reopening them. Every concrete value the brief did not give is marked **[spec choice]** and collected in Section 13 ("Values chosen by the spec") so the user can see and veto each one. Section 14 lists the accepted risks and known limitations. No design decision is left open.

Repository: `/Users/reubenpatterson/local_agent_harness` (public GitHub `reubenpatterson1/local_agent_harness`, remote `origin` = `https://github.com/reubenpatterson1/local_agent_harness.git`), branch `qwen-agent-redteam`, HEAD `64ce2c9` when this was written.

Workspace root (`WS`): `/Users/reubenpatterson/local_agent_harness/qwen-agent-workspace/`. All relative paths below are relative to `WS` unless they start with `~`, `/`, `D/` (the deploy root, Section 9.1), or `agent/`. `agent/` is the repo-root directory `/Users/reubenpatterson/local_agent_harness/agent/`, a sibling of `WS`; it holds `agent/qwen-agent-unsafe`.

Parent spec: `docs/specs/2026-08-22-qwen-agent-skill-framework-design.md`, called **[SKILLS]** below. It is authoritative except where this document revises it. Section 8.9 lists every revision.

ID conventions: `F<n>` is a requirement, `T<n>` is a test, `K<n>` is a success criterion / KPI. A bare "F12" is always the requirement; "test T12" is always the test.

Terms:

- **Host**: one machine in the fleet, named by a **host ID** (a registry key such as `mac-local`).
- **Daemon**: `bin/qwen-agentd run` running on a host. (`run` is the daemon subcommand, F92; `POST /run` is the HTTP endpoint, F47. The text always writes the endpoint as `POST /run` or `/run`.)
- **Peer**: another host's daemon, as seen by this host's daemon.
- **Live**: a peer that is registered, bound by a successful signed `GET /health`, and heard from (valid beacon or successful signed poll) within the live window (90 s).
- **Verified skill**: a skill that the registry declares for this host AND whose declared model the local model server reports as present.
- **Fleet view**: the JSON object `GET /peers` returns (Section 6.6). `bin/qwen-agent` routes from it.
- **Deploy root** `D`: `~/.local/share/qwen-agent/`.
- **Release**: a git tag matching `vYYYY.MM.DD[.N]`, checked out as a worktree under `D/releases/<tag>/`.

> **Superseded in part by multi-agent hosts** (`docs/superpowers/specs/2026-10-17-fleet-multi-agent-hosts-design.md`, M1-M3): a machine may run several agents, and `D` is now each agent's root `~/agents/<host_id>/`.

---

## 0. Purpose and scope

### 0.1 Purpose

Today every `delegate_to_skill` call runs a `--skill` subprocess of `bin/qwen-agent` on the same machine, against the same model server as the parent (`bin/qwen-agent:1224-1315`). The red-team agent `agent/qwen-agent-unsafe` reached a second machine (192.168.1.168, Ollama) by pointing one skill's `--base-url` at it through the env vars `SKILL_ENDPOINT_RESEARCHER` / `SKILL_MODEL_RESEARCHER` (`agent/qwen-agent-unsafe:86-99`). That ships every prompt and every tool round-trip across a flaky link to a remote model server, and needs hand-set env vars on the caller.

This spec replaces that with architecture **B**:

- Every host runs a daemon `bin/qwen-agentd` (stdlib only).
- The daemon advertises the skills its host serves. It runs them **locally**, with its own tools, against its **own** local model server.
- Only the task text and the final answer cross the network.
- Hosts find each other by signed UDP beacons, with signed HTTP polling as a fallback.
- Daemons update themselves from release tags on GitHub, with gated staging and automatic rollback.

It also ports the `researcher` skill from `agent/qwen-agent-unsafe` into the real harness `bin/qwen-agent`.

### 0.2 Grounding evidence

**Verified facts (from the brief; not re-litigated).**

- Ollama's `/v1` endpoint ignores `chat_template_kwargs.enable_thinking`. Only `"reasoning_effort": "none"` disables thinking there.
- The link to .168 is flaky: 60-250 ms ping, and once it answered ICMP while TCP ports timed out.
- vllm-metal crashes on concurrent requests, so a host runs one skill at a time.
- A Netskope client runs on the Mac.

**Hosts.**

| Host ID | Address | Role | Model server | Model | Skills |
|---|---|---|---|---|---|
| `orchestrator` | 192.168.1.170 | orchestrator | placeholder (not stood up) | placeholder | `[]` |
| `ollama-168` | 192.168.1.168 (Linux) | agent | Ollama, `http://127.0.0.1:11434/v1` | `qwen3.5:9b` | `researcher` |
| `mac-local` | 192.168.1.199 (this Mac) | agent | vLLM-metal, `http://127.0.0.1:8177/v1` | `qwen38-6bit` | `investigator`, `analyst`, `planner` |

**`bin/qwen-agent` as read on 2026-10-16 (3741 lines).**

- Imports are stdlib only (`bin/qwen-agent:26-43`). No `importlib` import exists yet.
- `REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))` (`:132`). Through the `~/.local/bin/qwen-agent` symlink it resolves to the real `qwen-agent-workspace/`.
- `AUTO_APPROVE_TOOLS = ("search", "fetch_url", "read_file", "delegate_to_skill", "calculate", "remember")` (`:144`).
- `SKILL_SUBPROCESS_TIMEOUT = 900` (`:148`).
- `SKILL_TOOL_NAMES` (`:152-156`) has three entries: investigator `(search, fetch_url, read_file, calculate, delegate_to_skill)`, analyst `(search, fetch_url, read_file, calculate)`, planner `(search, fetch_url, read_file)`. The INVARIANT comment at `:157-161` requires every name to be in `AUTO_APPROVE_TOOLS`. (The `run_python` exemption described in [SKILLS] Section 5 no longer exists in the code: `SKILL_TOKEN_ENV` is absent, and skills use `calculate` instead.)
- `DELEGATE_TARGETS` (`:165-168`): `None -> (investigator, analyst, planner)`, `investigator -> (analyst,)`.
- `SKILL_THINK_TEMP_DEFAULTS` (`:170-174`): investigator and planner think on at temperature 0.7; analyst think off at 0.2.
- `SEARXNG_BASE_URL = "http://127.0.0.1:8888"` (`:179`), a literal with no env override. `searxng/docker-compose.yml:31` publishes SearXNG on `127.0.0.1:8888` only, so it cannot be reached from another host.
- `_build_delegate_tool(targets)` (`:479-514`). Its description names only investigator, analyst and planner.
- `build_tools_for_context(skill)` (`:610-628`) reads `DELEGATE_TARGETS[skill]`. `TOOLS` and `TOOL_BY_NAME` are `None` at import (`:631-632`) and are assigned in `main()` (`:3697-3699`).
- `exec_delegate_to_skill(args, args_ns)` (`:1224-1315`):
  - validates the task and the enum (`:1232-1239`);
  - prints `[delegating to %s, up to %ds...]` (`:1241`);
  - builds the argv (`:1243-1257`), forwarding `--skill=`, `--user-prompt=`, `--workspace=`, `--base-url=`, `--model=`, `--max-tokens`, `--request-timeout`, `--max-rounds`, `--tool-timeout`, `--context-window`, and `--api-key=` when one is set;
  - sets `QWEN_AGENT_PREFLIGHT_DONE=1` in the child env (`:1262-1263`);
  - starts the child with `Popen` (`start_new_session` only at top level), and kills it with `killpg` on timeout or Ctrl-C;
  - parses the last line of stdout as the envelope, then maps `status` / `answer` / `error` to a result string (`:1303-1315`).
- `dispatch()` routes `delegate_to_skill` to `exec_delegate_to_skill` (`:1739-1740`). `_call_key` has a `delegate_to_skill` branch (`:937-938`).
- `chat_completion(base_url, messages, args_ns, include_tools=True)` (`:1775-1799`) always sends `chat_template_kwargs.enable_thinking`. It never sends `reasoning_effort`.
- `SKILL_SYSTEM_PROMPTS` (`:1887-1970`) has three entries. `build_skill_system_message` is at `:1973-1975`.
- `preflight(base_url, model, api_key, skip_tool_probe=False)` (`:2281-2405`):
  - Check A is `GET <base_url>/models` with the model id required;
  - Check B is a tool-calling probe with `max_tokens` 1;
  - both exit 2 on failure.
- `setup(args_ns)` (`:3160-3190`) skips Check B and the SearXNG probe when `QWEN_AGENT_PREFLIGHT_DONE == "1"`.
- `oneshot(args_ns)` (`:3613-3654`) prints one `qwen-agent.oneshot.v1` envelope `{schema, status, answer, error, rounds, tool_calls}` and exits 0 when the status is `ok`, else 3.
- `parse_args(argv)` (`:3660-3691`): `--skill` has `choices=("investigator", "analyst", "planner")` (`:3682-3683`).
- `main()` (`:3694-3741`) applies `SKILL_THINK_TEMP_DEFAULTS` when `--skill` is set (`:3724-3729`).

**`agent/qwen-agent-unsafe` (the port source, 2260 lines).**

- `SKILL_TOOL_NAMES["researcher"] = ("search", "fetch_url", "read_file", "calculate")` (`:64`).
- `DELEGATE_TARGETS`: `None -> (investigator, analyst, planner, researcher)`, `investigator -> (analyst, researcher)` (`:74-77`).
- `SKILL_THINK_TEMP_DEFAULTS["researcher"] = {"think": False, "temperature": 0.7}` (`:83`).
- `SKILL_ENDPOINT_OVERRIDES` / `SKILL_MODEL_OVERRIDES` (`:90-99`), and `OLLAMA_SKILLS = ("researcher",)` (`:104`).
- In `chat_completion` (`:1446`): `if args_ns.skill in OLLAMA_SKILLS and not args_ns.think: body["reasoning_effort"] = "none"` (`:1458-1459`).
- `SKILL_SYSTEM_PROMPTS["researcher"]` (`:1613-1636`).
- `--skill` has `choices=(..., "researcher")` (`:2221`).

**Tests that constrain the change.**

- `tests/test_researcher_think_off.py` loads **`agent/qwen-agent-unsafe`**, not `bin/qwen-agent`. It asserts `OLLAMA_SKILLS == ("researcher",)` there. This spec does not touch that file, so the test keeps passing unchanged.
- `tests/test_qwen_agent_context_budget.py:30-41` loads `bin/qwen-agent` by path and asserts that the import is side-effect free: `TOOLS` is `None` at import, and no socket is opened. It calls `build_tools_for_context(None)` directly, without `main()`.
- `scripts/deploy/build_pkg.py:383-385` ships `bin/qwen-agent` **alone** (no `fleet_lib.py`) in the ltx-chain deploy package. So **`bin/qwen-agent` must keep working when `fleet_lib.py` is absent** (F70).

**Environment on this Mac.**

- `~/.local/bin/qwen-agent -> /Users/reubenpatterson/qwen-agent-workspace/bin/qwen-agent` is a dangling symlink (checked).
- `~/.zshenv:11-12` exports `SKILL_ENDPOINT_RESEARCHER='http://192.168.1.168:11434/v1'` and `SKILL_MODEL_RESEARCHER='qwen3.5:9b'`.
- `~/.config/qwen-agent/` and `~/.local/share/qwen-agent/` do not exist.
- No git tags exist in the repo.
- `python3` is 3.13.0 with pytest 8.3.4; `/usr/bin/python3` is 3.9.6.

### 0.3 Deliverables

| # | Item | File |
|---|---|---|
| D1 | Fleet library: all fleet logic, pure and testable | `fleet_lib.py` (new) |
| D2 | Daemon and its subcommands | `bin/qwen-agentd` (new, mode 0755) |
| D3 | Stable launcher | `bin/qwen-agentd-launch` (new, mode 0755; `install` copies it to `D/qwen-agentd-launch`) |
| D4 | Registry for the production fleet | `fleets/<fleet_id>.json` (new, created at rollout, Section 12) |
| D5 | Harness changes: researcher port, fleet routing, SearXNG override | `bin/qwen-agent` (modified) |
| D6 | Unit tests (also the self-update gate's selftest) | `tests/test_fleet_lib.py` (new) |
| D7 | `bin/qwen-agent` fleet and researcher tests | `tests/test_qwen_agent_fleet.py` (new) |
| D8 | Single-machine 3-daemon integration tests | `tests/test_fleet_integration.py` (new) |
| D9 | Self-update integration test | `tests/test_fleet_self_update.py` (new) |
| D10 | Shared test helpers (stub model servers, daemon launcher, free ports) | `tests/fleet_testutil.py` (new) |

No other file is created or modified. In particular, `agent/qwen-agent-unsafe` and `tests/test_researcher_think_off.py` are not touched.

### 0.4 Out of scope (explicit)

- **`agent/qwen-agent-unsafe`** is the deliberately unsafe red-team agent. It stays confined to its Docker range. It does not join the fleet, run a daemon, read `fleet.env`, or appear in any registry. Nothing in this spec modifies it.
- **Standing up the orchestrator host (192.168.1.170) and its 70B model.** It is a registry entry only.
- **Signed-tag verification.** The GitHub account, including its 2FA, is the trust root (Section 14, accepted risk A1).
- Token rotation tooling, an `uninstall` subcommand, a `show-join` subcommand, multiple fleets per host, IPv6, TLS, and cancelling a remote run.
- Forwarding a remote child's stderr to the caller.
- Changing `_build_delegate_tool`'s description text (Section 14, L5).
- Changing the deploy package (`scripts/deploy/*`).

### 0.5 Success criteria / KPIs

| ID | Criterion | Verified by |
|---|---|---|
| K1 | A new registered host is live in the other daemons' `GET /peers` within 45 s in beacon mode, and within 75 s in poll mode | T40, T41 (scaled); R4, R5 (live) |
| K2 | A killed host leaves `GET /peers` within 90 s | T42 (scaled); R6 (live) |
| K3 | `delegate_to_skill(skill="researcher", ...)` from this Mac's REPL runs on ollama-168 and returns a non-empty answer, with no `SKILL_ENDPOINT_*` / `SKILL_MODEL_*` set anywhere in the environment | T43 (stub); R7 (live) |
| K4 | A daemon with a foreign token produces 0 peers and 0 log lines on a legitimate daemon | T45 |
| K5 | The token is absent from child-process environments, logs, beacons, and the git tree | T12, T18, T25, T46; R9 (live) |
| K6 | After a tag push, every installed host runs the new version within 30 min | T60 (scaled); R10 (live) |
| K7 | After a bad tag (gate failure or crash on start), every host stays on, or returns to, the previous version | T26, T60 |
| K8 | With no daemon running, `bin/qwen-agent` behaves exactly as today, and every existing test plus `tests/test_researcher_think_off.py` passes | T35, T70 |

### 0.6 Must-have vs nice-to-have

Every requirement in Sections 1-12 is a must-have. Nothing beyond them is built.

---

## 1. Architecture

### 1.1 Components and data flow

```
 mac-local                                         ollama-168
 +-----------------------------+                   +-----------------------------+
 | bin/qwen-agent (REPL)       |                   | bin/qwen-agentd run         |
 |  delegate_to_skill          |                   |  TCP 0.0.0.0:8190           |
 |   |  GET  /peers  (loopback)|                   |   GET /health  (signed)     |
 |   |  POST /delegate         |                   |   GET /skills  (signed)     |
 |   v  to 127.0.0.1:8190      |   signed POST     |   POST /run    (signed)     |
 | bin/qwen-agentd run    -----+---- /run -------->|     |                       |
 |  TCP 0.0.0.0:8190 (one      |<-- signed answer -+     v                       |
 |   listener; /peers and      |                   |  bin/qwen-agent --skill=    |
 |   /delegate loopback-only)  |                   |    researcher ...           |
 |  UDP 8190 beacons  <--------+-- broadcast ----->|                             |
 +-----------------------------+                   |     |                       |
        | (local skills: subprocess, unchanged)    |     v                       |
        v                                          |  Ollama 127.0.0.1:11434     |
   vLLM-metal 127.0.0.1:8177                       +-----------------------------+
```

- **F1.** `fleet_lib.py` holds all fleet logic as importable, side-effect-free functions and classes (Section 1.3). It is stdlib only, opens no socket at import, and is valid on Python 3.9.6 and 3.13.0: no `X | Y` annotations, no `match`, no 3.10+ stdlib APIs.
- **F2.** `bin/qwen-agentd` holds the CLI, the threads, the sockets, and the subprocess and git invocations. It loads `fleet_lib` from `os.path.join(REPO_ROOT, "fleet_lib.py")`, where `REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))`. It does this by `sys.path.insert(0, REPO_ROOT)` followed by `import fleet_lib`. It has the same interpreter constraint as F1.
- **F3.** `bin/qwen-agent` never imports `fleet_lib` at module top level. It loads it lazily in `main()` (F70). It never holds the fleet token.
- **F4.** Only these items cross the network:
  - beacons (Section 5.1);
  - signed `GET /health`, `GET /skills`, and `POST /run` requests and their signed responses.

  Prompts, tool calls, and model traffic never leave the host that runs the skill.

### 1.2 Threads in `qwen-agentd run` [spec choice]

| Thread | Period | Work |
|---|---|---|
| `beacon-send` | `BEACON_INTERVAL` (first send at start) | send one beacon to every beacon target (F30) |
| `beacon-recv` | blocking `recvfrom` with a 1 s timeout | verify beacons; bind or refresh peers (F31-F34) |
| `poll` | `POLL_INTERVAL` (first run one interval after start) | poll registered hosts not heard within `LIVE_WINDOW`; refresh live peers (F36, F37) |
| `prober` | `REPROBE_INTERVAL` (first run at start, synchronously, before the listener serves) | probe the local model server; recompute verified skills (F15-F17) |
| `housekeeping` | `HOUSEKEEPING_INTERVAL` | prune nonce caches; log liveness transitions (F38) |
| `http` | `ThreadingHTTPServer.serve_forever` | the single HTTP listener: signed endpoints and loopback-only endpoints (Section 6) |
| `updater` | `UPDATE_INTERVAL` + jitter (first run one period after start); **not started** when the version is `dev` | self-update cycle (Section 9.4) |
| `confirm` | every 1 s until success or `STARTUP_HEALTH_DEADLINE`; **started only** when `update-state.json` says `pending` for this version | post-update self-check (F88) |

All threads are daemon threads. The main thread waits on a `threading.Event` that is set on SIGTERM or SIGINT, then shuts down the HTTP server and returns 0.

### 1.3 `fleet_lib` public names [spec choice]

> **Superseded in part by multi-agent hosts** (M2, M5, M6, Section 4.1): `DEPLOY_ROOT` and `SYSTEMD_UNIT` are replaced; `deploy_root`, `fleet_env_path` and `log_dir` take a `host_id`.

Constants (module level, exact values):

```python
PROTOCOL = 1
DEFAULT_PORT = 8190
BEACON_INTERVAL = 30          # s, scaled by --timing-scale
POLL_INTERVAL = 60            # s, scaled
LIVE_WINDOW = 90              # s, scaled
REPROBE_INTERVAL = 60         # s, scaled
PEER_REFRESH_INTERVAL = 60    # s, scaled
HOUSEKEEPING_INTERVAL = 5     # s, scaled
UPDATE_INTERVAL = 900         # s, scaled
UPDATE_JITTER = 120           # s, scaled; uniform in [0, UPDATE_JITTER]
SKEW_WINDOW = 60              # s, never scaled
NONCE_RETENTION = 120         # s, never scaled
STARTUP_HEALTH_DEADLINE = 120 # s, never scaled
PEER_HTTP_TIMEOUT = 5         # s, /health and /skills calls to peers
MODEL_PROBE_TIMEOUT = 5       # s
RUN_TIMEOUT = 900             # s, equals bin/qwen-agent SKILL_SUBPROCESS_TIMEOUT
FORWARD_TIMEOUT = 930         # s, RUN_TIMEOUT + 30: /delegate -> peer /run
GATE_TIMEOUT = 300            # s, the staged release's selftest
GIT_TIMEOUT = 120             # s, any single git subprocess
MAX_BODY = 1048576            # bytes, request body cap
MAX_START_ATTEMPTS = 3
KEEP_RELEASES = 3
FLEET_TAG_CHARS = 16
KNOWN_SKILLS = ("investigator", "analyst", "planner", "researcher")
FLEET_ENV_KEYS = ("QWEN_AGENT_FLEET_ID", "QWEN_AGENT_FLEET_TOKEN")
FLEET_ENV_PREFIX = "QWEN_AGENT_FLEET_"   # every env key with this prefix is stripped (F54a, F86)
TAG_RE = re.compile(r"^v(\d{4})\.(\d{2})\.(\d{2})(?:\.([1-9]\d*))?$")
HOST_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
FLEET_ID_RE = re.compile(r"^[0-9a-f]{16}$")
TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
JOIN_PREFIX = "qaf1"
LOOPBACK_CLIENTS = ("127.0.0.1", "::1")   # client addresses allowed on loopback-only endpoints (F42)
LOCAL = "@local"              # route_candidates' marker for "run on this host" (F59); cannot match HOST_ID_RE
PEERS_SCHEMA = "qwen-agentd.peers.v1"
ONESHOT_SCHEMA = "qwen-agent.oneshot.v1"   # equals bin/qwen-agent ONESHOT_SCHEMA
DEFAULT_DAEMON_URL = "http://127.0.0.1:8190"
DAEMON_URL_RE = re.compile(r"^http://127\.0\.0\.1:([0-9]{1,5})$")
VIEW_TIMEOUT = 2              # s, bin/qwen-agent GET /peers; never scaled
DELEGATE_CLIENT_TIMEOUT = 960 # s, bin/qwen-agent POST /delegate = FORWARD_TIMEOUT + 30; never scaled
ORIGIN_URL = "https://github.com/reubenpatterson1/local_agent_harness.git"
DEPLOY_ROOT = "~/.local/share/qwen-agent"   # passed through os.path.expanduser at every use
WS_SUBDIR = "qwen-agent-workspace"          # the workspace directory inside a release worktree
LAUNCHD_LABEL = "com.qwen-agent.qwen-agentd"
SYSTEMD_UNIT = "qwen-agentd.service"
SUPERVISOR_RESTART_DELAY = 10 # s, launchd ThrottleInterval and systemd RestartSec
LOG_MAX_BYTES = 5242880       # 5 MB
LOG_BACKUPS = 3
```

Exceptions: `class RegistryError(ValueError)` and `class FleetEnvError(ValueError)`.

Functions and classes. Each one is specified in the section named on its row.

| Name | Section |
|---|---|
| `validate_registry(obj, expected_fleet_id) -> list[str]`, `load_registry(path, expected_fleet_id) -> dict`, `self_entry(registry, host_id) -> dict` | 2 |
| `fleet_env_path() -> str`, `write_fleet_env(path, fleet_id, token)`, `load_fleet_env(path) -> (fleet_id, token)`, `make_join_string(fleet_id, token) -> str`, `parse_join_string(s) -> (fleet_id, token)` | 3 |
| `token_key(token) -> bytes`, `fleet_tag(key) -> str`, `canonical_json(obj) -> bytes`, `NonceCache`, `make_beacon(key, port, now, nonce) -> bytes`, `verify_beacon(key, data, now, cache) -> (status, beacon)`, `sign_request(...)`, `verify_request(...)`, `sign_response(...)`, `verify_response(...)` | 4 |
| `probe_url(model_server) -> str`, `parse_loaded_models(server_type, body_bytes) -> set`, `verify_skills(entry, loaded) -> list[dict]` | 2.3 |
| `LivenessTable` | 5.3 |
| `is_loopback_client(ip) -> bool`, `http_route(method, path) -> (kind, name)` | 6.1 |
| `build_child_env(environ, daemon_url) -> dict` | 6.5 |
| `route_candidates(skill, view) -> list`, `delegate_enum(targets, view) -> list`, `valid_view(obj) -> bool`, `failover(candidates, attempt) -> dict`, `daemon_url_from_env(environ) -> (url, warning)`, `fetch_view(daemon_url) -> (view, warning)`, `delegate_once(daemon_url, skill, task, host_id) -> (outcome, envelope, detail)` | 7 |
| `deploy_root() -> str`, `tag_key(tag) -> tuple or None`, `select_candidate(tags, current, bad_tags, is_ancestor) -> str or None`, `read_state(path) -> dict`, `write_state(path, state)`, `releases_to_prune(present, current, state) -> list`, `release_version(repo_root, deploy_root) -> str`, `run_update_cycle(ctx) -> str` | 9 |
| `log_dir() -> str` | 10.5 |

`launcher_step(state, from_available) -> (state, action)` and the launcher's own `read_state` / `write_state` are **not** in `fleet_lib`. They live in `bin/qwen-agentd-launch` (F89), which never imports `fleet_lib`, so that a broken release cannot break its own rollback. **[spec choice]**

Functions in `fleet_lib` may open sockets or run subprocesses when called (`fetch_view`, `delegate_once`), but nothing does so at import.

---

## 2. Registry

### 2.1 Location and schema

> **Superseded in part by multi-agent hosts** (M7, M19): F7 rule 8's port range becomes 1024..65535; rule 12 is unchanged.

- **F5.** The registry for a fleet is `fleets/<fleet_id>.json` in the repo, under `WS`. **[spec choice: under `qwen-agent-workspace/`, beside `bin/`, so that `REPO_ROOT/fleets/` finds it in every release worktree.]** It is delivered to hosts only by self-update (or by `install`). The daemon reads `os.path.join(REPO_ROOT, "fleets", fleet_id + ".json")` unless `run --registry PATH` is given (F92).
- **F6.** Schema (UTF-8 JSON object):

```json
{
  "protocol": 1,
  "fleet_id": "<16 lowercase hex>",
  "hosts": {
    "<host_id>": {
      "role": "orchestrator" | "agent",
      "address": "<IPv4 dotted quad>",
      "port": 8190,
      "model_server": {"type": "ollama" | "vllm", "url": "http://..."},
      "model": "<model name>",
      "skills": ["<skill>", ...]
    }
  }
}
```

  `port` is **optional** and defaults to `DEFAULT_PORT` (8190). **[spec choice: the brief's schema has no port. One is needed so that decision 12's loopback integration tests can run three daemons on 127.0.0.1. The production registry omits it.]**

- **F7.** `validate_registry(obj, expected_fleet_id)` returns a list of error strings. An empty list means the registry is valid. It checks every rule below and collects all failures; it does not stop at the first. Each error string is prefixed with a JSON-path-like location (for example `hosts.mac-local.model_server.type: ...`). Rules:
  1. `obj` is a dict whose keys are exactly `{"protocol", "fleet_id", "hosts"}`. A missing or extra key is an error.
  2. `protocol` is an `int` (not a `bool`) equal to `PROTOCOL`.
  3. `fleet_id` is a `str` matching `FLEET_ID_RE` and equal to `expected_fleet_id`.
  4. `hosts` is a non-empty dict. Every key matches `HOST_ID_RE`.
  5. Every host value is a dict. Its keys are a subset of `{"role", "address", "port", "model_server", "model", "skills"}` that contains all of those keys except `port`.
  6. `role` is in `("orchestrator", "agent")`.
  7. `address` parses with `ipaddress.IPv4Address(address)`.
  8. `port`, if present, is an `int` (not a `bool`) in 1..65535.
  9. `model_server` is a dict whose keys are exactly `{"type", "url"}`. `type` is in `("ollama", "vllm")`. `url` is a `str` that starts with `http://`. When `type` is `ollama`, `url` also ends with `/v1`.
  10. `model` is a non-empty `str`.
  11. `skills` is a list of `str`. Every item is in `KNOWN_SKILLS`, and there are no duplicates. An empty list is allowed.
  12. No two hosts have the same `(address, port)` pair, with the port defaulted.
- **F8.** `load_registry(path, expected_fleet_id)` behaves as follows:
  - It reads the file as UTF-8 and parses it with `json.loads`.
  - An I/O or JSON error raises `RegistryError("cannot read registry <path>: <ExcType>: <msg>")`.
  - It runs `validate_registry`. Any errors raise `RegistryError("invalid registry <path>:\n  " + "\n  ".join(errors))`.
  - It returns a deep copy of the registry with `port` filled in on every host.
- **F9.** `self_entry(registry, host_id)` returns `registry["hosts"][host_id]`. If `host_id` is absent, it raises `RegistryError("host_id '<id>' is not in the fleet registry; valid IDs: <sorted ids joined by ', '>")`.

### 2.2 Self-identity

> **Superseded in part by multi-agent hosts** (M31): the unset-`QWEN_AGENT_HOST_ID` message lists the agents on disk, and is checked before `fleet.env`.

- **F10.** A daemon identifies itself only by the environment variable `QWEN_AGENT_HOST_ID`. Its IP address is never used for this. If the variable is unset or empty, `run` exits 2 (F100) with the registry's valid IDs listed.
- **F11.** A daemon uses a peer only if the peer is **both** registered (its `/health` `host_id` is a key in this daemon's registry) **and** heard from (Section 5). A same-fleet daemon whose `host_id` is unregistered is ignored. The first time each such `host_id` is seen, one WARNING line is logged: `ignoring unregistered host_id '<id>' at <ip>`.

### 2.3 Skill verification

- **F12.** Role and skills are **declared** by the registry. Skills are **verified** by probing the local model server. The role is reported in `/health` and is not otherwise verified.
- **F13.** `probe_url(model_server)`:
  - `vllm`: `url.rstrip("/") + "/models"`, for example `http://127.0.0.1:8177/v1/models`.
  - `ollama`: `url.rstrip("/")` with its trailing `/v1` removed, plus `/api/tags`, for example `http://127.0.0.1:11434/api/tags`.
- **F14.** `parse_loaded_models(server_type, body_bytes)` returns a set of model names. Any parse error, or an unexpected shape, returns an empty set.
  - `vllm`: `{item["id"] for item in json["data"] if isinstance(item.get("id"), str)}`.
  - `ollama`: the union of `item["name"]` and `item["model"]` over `json["models"]`, keeping only `str` values.
- **F15.** `verify_skills(entry, loaded)` returns, in registry order, `[{"skill": s, "model": entry["model"], "verified": entry["model"] in loaded} for s in entry["skills"]]`.
- **F16.** The prober issues `GET probe_url(...)` with timeout `MODEL_PROBE_TIMEOUT`. It runs once at startup, synchronously, and then every `REPROBE_INTERVAL`. A connection error, timeout, or non-200 response counts as `loaded = set()`, so every skill on this host is unverified.
- **F17.** Warnings go only to the log and only on change. After each probe, for each skill whose `verified` value differs from the previous probe's (at startup the previous value counts as `True`):
  - if it became `False`, log at WARNING: `skill '<s>' not offered: model '<m>' not present at <probe_url>`;
  - if it became `True`, log at INFO: `skill '<s>' offered: model '<m>' present`.

  A host whose model is down keeps beaconing and serving `/health`, and offers no verified skills (F104).

### 2.4 Initial registry content

- **F18.** At rollout (Section 12, step R2), `fleets/<fleet_id>.json` is created with exactly this content, where `<fleet_id>` is the value that `init-fleet` printed:

```json
{
  "protocol": 1,
  "fleet_id": "<fleet_id>",
  "hosts": {
    "orchestrator": {
      "role": "orchestrator",
      "address": "192.168.1.170",
      "model_server": {"type": "vllm", "url": "http://127.0.0.1:8000/v1"},
      "model": "PLACEHOLDER-70B",
      "skills": []
    },
    "ollama-168": {
      "role": "agent",
      "address": "192.168.1.168",
      "model_server": {"type": "ollama", "url": "http://127.0.0.1:11434/v1"},
      "model": "qwen3.5:9b",
      "skills": ["researcher"]
    },
    "mac-local": {
      "role": "agent",
      "address": "192.168.1.199",
      "model_server": {"type": "vllm", "url": "http://127.0.0.1:8177/v1"},
      "model": "qwen38-6bit",
      "skills": ["investigator", "analyst", "planner"]
    }
  }
}
```

  The orchestrator's `model_server.url` and `model` are deliberate placeholders. No daemon runs on .170, so that entry never becomes live.

---

## 3. Trust: shared secret

### 3.1 `fleet.env`

> **Superseded in part by multi-agent hosts** (M4): F19's path is `~/agents/<host_id>/fleet.env`; F20's write is atomic.

- **F19.** `fleet_env_path()` returns `os.path.expanduser("~/.config/qwen-agent/fleet.env")`. The file contains exactly two lines, in this order, each ending with `\n`:

```
QWEN_AGENT_FLEET_ID=<16 lowercase hex>
QWEN_AGENT_FLEET_TOKEN=<64 lowercase hex>
```

- **F20.** `write_fleet_env(path, fleet_id, token)`:
  - creates the parent directory with mode `0o700` (`os.makedirs(..., exist_ok=True)`, then `os.chmod(dir, 0o700)`);
  - opens the file with `os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)`, so an existing file raises `FileExistsError`;
  - writes both lines and `fsync`s.
- **F21.** `load_fleet_env(path)`. Each failure below raises `FleetEnvError` with the message shown:

  | Condition | Message |
  |---|---|
  | `os.stat(path).st_mode & 0o077 != 0` | `<path> must be mode 0600 (chmod 600 <path>)` |
  | the content is not exactly the two `KEY=value` lines of F19 | `<path> is malformed` |
  | a value fails `FLEET_ID_RE` / `TOKEN_RE` | `<path> is malformed` |

  On success it returns `(fleet_id, token)`. A missing file raises `FileNotFoundError`, which the caller maps to F100.
- **F22.** Only `bin/qwen-agentd` reads `fleet.env`, through `load_fleet_env`. `bin/qwen-agent` never reads it, and no code anywhere exports its values into an environment.

### 3.2 `init-fleet` and `join`

> **Superseded in part by multi-agent hosts** (M27-M29): both take `--agent-id`; `join --from-agent` is added.

- **F23.** `qwen-agentd init-fleet`:
  1. If `fleet_env_path()` exists: print `qwen-agentd: <path> already exists; remove it first to create a new fleet` to stderr and exit 2.
  2. Set `fleet_id = secrets.token_hex(8)` and `token = secrets.token_hex(32)`.
  3. Call `write_fleet_env(fleet_env_path(), fleet_id, token)`.
  4. Print exactly these lines to **stdout**, once:

     ```
     fleet_id: <fleet_id>
     join string (shown once; copy it to each other host over ssh):
     <join string>
     next: create fleets/<fleet_id>.json (see the fleet spec, Section 2.4), commit, tag a release
     ```
  5. Exit 0.

  The join string is never written to any file or log. No subcommand can print it again.
- **F24.** `make_join_string(fleet_id, token)` returns `"qaf1." + fleet_id + "." + token + "." + check`, where `check = hashlib.sha256((fleet_id + ":" + token).encode("ascii")).hexdigest()[:8]`. **[spec choice: dot-separated, with an 8-hex checksum to catch copy errors.]**
- **F25.** `parse_join_string(s)`:
  - strips whitespace and splits on `.`;
  - requires exactly 4 parts, `parts[0] == "qaf1"`, `parts[1]` matching `FLEET_ID_RE`, `parts[2]` matching `TOKEN_RE`, and `parts[3]` equal to the recomputed check;
  - on any failure raises `FleetEnvError("invalid join string")`, a message that contains no part of the input;
  - otherwise returns `(fleet_id, token)`.
- **F26.** `qwen-agentd join [STRING]`:
  1. If STRING is omitted, read it with `getpass.getpass("join string: ")`, which does not echo. **[spec choice: keeps the token out of shell history and `ps`. The positional form from the brief still works.]**
  2. Parse it with `parse_join_string`. On failure, print `qwen-agentd: invalid join string` to stderr and exit 2.
  3. If `fleet_env_path()` exists:
     - if `load_fleet_env` returns the same `(fleet_id, token)`, print `qwen-agentd: already joined fleet <fleet_id>` and exit 0;
     - otherwise print `qwen-agentd: <path> exists for a different fleet; remove it first` and exit 2.
  4. Otherwise call `write_fleet_env`, print `qwen-agentd: joined fleet <fleet_id>`, and exit 0.

### 3.3 Token handling invariants

- **F27.** The token string exists only in `fleet.env`, in `load_fleet_env`'s return value, and as `key = token_key(token)` held by the daemon. `token_key(token)` returns `bytes.fromhex(token)` (32 bytes). **[spec choice]**
- **F28.** The token, the key, and the join string are never:
  - in the repo;
  - in any environment variable the daemon sets or passes on;
  - in any log line, beacon, HTTP header, or HTTP body;
  - in any child process's argv or environment.

  Every log call that formats an exception message in the daemon formats only `type(e).__name__` and `str(e)`. No exception message is built from the token or key.
- **F29.** Loopback endpoints (Section 6) need no authentication: any process that can connect to 127.0.0.1 as this user can already read `fleet.env`.
- **F29a.** A message from a foreign fleet (different token) is dropped silently: no log line, no counter, no response body. This covers a beacon whose `fleet_tag` does not match, and an HTTP request whose signature does not verify. Only a correctly signed message can cause a log line about its sender (clock skew, F33; an unregistered host_id, F11).

---

## 4. Signing primitives

- **F29b.** `fleet_tag(key)` returns `hmac.new(key, b"fleet-tag", hashlib.sha256).hexdigest()[:FLEET_TAG_CHARS]`.
- **F29c.** `canonical_json(obj)` returns `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")`.
- **F29d.** `class NonceCache(retention=NONCE_RETENTION, clock=time.time)`:
  - `check_and_add(nonce) -> bool` returns `False` if `nonce` was added within the last `retention` seconds of `clock()`. Otherwise it records `nonce` with the time `clock()` and returns `True`.
  - `prune()` drops entries older than `retention`.
  - It is guarded by a `threading.Lock`.
  - The daemon keeps three instances: `beacon_nonces`, `request_nonces` (server side), and `response_nonces` (client side).
- **F29e.** Nonces are `secrets.token_hex(16)`. Timestamps are `int(time.time())`.

### 4.1 Beacons

- **F29f.** `make_beacon(key, port, now, nonce)` returns `canonical_json(b)`, where `b = {"proto": PROTOCOL, "fleet_tag": fleet_tag(key), "port": port, "ts": now, "nonce": nonce}` plus `b["sig"] = hmac.new(key, canonical_json(b_without_sig), hashlib.sha256).hexdigest()`. The beacon carries no host_id, skills, or version.
- **F29g.** `verify_beacon(key, data, now, cache)` returns `(status, beacon_dict_or_None)`. It checks, in this order:
  1. `json.loads(data)` gives a dict with exactly the keys `{proto, fleet_tag, port, ts, nonce, sig}`; `proto`, `port` and `ts` are `int`s; the rest are `str`s. Otherwise -> `("malformed", None)`.
  2. `proto != PROTOCOL` -> `("malformed", None)`.
  3. `not hmac.compare_digest(fleet_tag, fleet_tag(key))` -> `("foreign", None)`.
  4. The signature is recomputed over the other five fields. `not hmac.compare_digest(sig, expected)` -> `("bad_sig", None)`.
  5. `abs(now - ts) > SKEW_WINDOW` -> `("skew", beacon)`.
  6. `not cache.check_and_add(nonce)` -> `("replay", None)`.
  7. Otherwise -> `("ok", beacon)`.

  Only `"skew"` may produce a log line (F33). Every other non-`ok` status is dropped silently.

### 4.2 HTTP requests and responses

- **F29h.** Request signature input (bytes):
  ```
  "qwen-agentd-req-v1\n" + METHOD + "\n" + PATH + "\n" + str(ts) + "\n" + nonce + "\n" + sha256hex(body)
  ```
  encoded as ASCII. `PATH` is the request target exactly as sent (no query strings are used). `body` is `b""` for GET.
  - Headers: `X-Fleet-Ts: <ts>`, `X-Fleet-Nonce: <nonce>`, `X-Fleet-Sig: <hmac-sha256 hex>`.
  - `sign_request(key, method, path, body, now, nonce) -> dict` returns these three headers.
  - `verify_request(key, method, path, headers, body, now, cache) -> status` returns `"ok"`, `"bad"` (any header missing or malformed, or a signature mismatch checked with `hmac.compare_digest`), `"skew"`, or `"replay"`, checking in that order: headers, then signature, then skew, then replay.
- **F29i.** Response signature input:
  ```
  "qwen-agentd-resp-v1\n" + str(status_code) + "\n" + METHOD + "\n" + PATH + "\n" + request_nonce + "\n" + str(ts) + "\n" + nonce + "\n" + sha256hex(body)
  ```
  Including `request_nonce` binds a response to its request, so a captured response cannot be replayed as the answer to a different request.
  - `sign_response(key, status_code, method, path, request_nonce, body, now, nonce) -> dict` returns the same three header names.
  - `verify_response(key, status_code, method, path, request_nonce, headers, body, now, cache) -> status` uses the same statuses and order as F29h.
- **F29j.** The server signs every response to a request that verified as `"ok"`, whatever its status code (200, 400, 404, 409, 413, 500, 502, 504). A request that fails verification gets `401` with an empty, unsigned body. Responses are signed because a forged `/run` answer would be a prompt injection into the calling agent (decision 6). The client treats any response that fails `verify_response` as `bad_signature` and never reads its body.

---

## 5. Discovery and liveness

### 5.1 Beacon send

> **Superseded in part by multi-agent hosts** (M16): F30's default targets are `255.255.255.255:<p>` for each distinct registry port.

- **F30.** The `beacon-send` thread:
  - opens one UDP socket with `SO_BROADCAST`;
  - every `BEACON_INTERVAL`, starting at thread start, builds `make_beacon(key, self_port, int(time.time()), nonce)` with a fresh nonce;
  - **first** adds that nonce to `beacon_nonces`, so the host's own beacon, if it comes back, is rejected as a replay without a log line;
  - then calls `sendto` to every `(addr, port)` in the beacon target list.

  The target list defaults to `[("255.255.255.255", 8190)]` **[spec choice]**. It is set by `run --beacon-targets` (F92); the value `none` means an empty list. A send counts as successful when every `sendto` returned without `OSError`. On the transition from success to failure, log at WARNING: `beacon send failed (<ExcType>: <msg>); relying on poll fallback`. On the transition back, log at INFO: `beacon send recovered`.

### 5.2 Beacon receive

> **Superseded in part by multi-agent hosts** (M15): F31's default `beacon_port` is the agent's own registry port.

- **F31.** The daemon binds the UDP socket `("0.0.0.0", beacon_port)` at startup (F95 step 8) and hands it to the `beacon-recv` thread. The socket sets `SO_BROADCAST` and does **not** set `SO_REUSEADDR`. `beacon_port` defaults to 8190 and is set by `run --beacon-port` (F92). It reads datagrams of up to 2048 bytes; a larger datagram is truncated and therefore fails as `malformed`. Each datagram goes through `verify_beacon`.
- **F32.** For an `ok` beacon from source IP `ip`, with `port = beacon["port"]`:
  - If `(ip, port)` is already bound to a host_id in the `LivenessTable`, call `table.heard(ip, port, "beacon")`.
  - Otherwise, schedule a **bind attempt** for `(ip, port)`. At most one bind attempt per `(ip, port)` is in flight at a time; a set of in-flight addresses enforces this, and each attempt runs on its own short-lived thread. A bind attempt is:
    1. signed `GET /health` to `http://<ip>:<port>/health` with timeout `PEER_HTTP_TIMEOUT`;
    2. the response verifies, the status is 200, and the body is a JSON object with `str` `host_id`, `role`, `version`, `discovery` and `int` `proto`;
    3. `host_id != self_host_id`;
    4. `host_id` is in the registry (else F11);
    5. signed `GET /skills` succeeds and verifies in the same way;
    6. `table.bind(host_id, ip, port, health, skills, via="beacon")`.

    Any failed step abandons the attempt silently. The next beacon schedules a new one.

  A beacon alone never makes a peer live (decision 5): only `bind`, which requires a successful signed `/health`, does.
- **F33.** For a `skew` beacon, log one WARNING per source IP per daemon process: `clock skew of <ts-now:+d>s from <ip> exceeds 60s; check NTP on both hosts`. The beacon is otherwise dropped. The same once-per-IP set also covers signed HTTP requests that fail with `"skew"` (F44).
- **F34.** The source IP of the latest accepted beacon is the peer's **current address**. When a bind attempt from a new `(ip, port)` returns a `host_id` that is already bound at another address, the binding moves to the new address.

### 5.3 `LivenessTable`

- **F35.** `class LivenessTable(registry, self_host_id, live_window, clock=time.time)`, guarded by a `threading.Lock`. Each record, keyed by host_id, has these fields:
  - `address`, `port`;
  - `role`, `version`, `proto`, `compatible` (`proto == PROTOCOL`);
  - `skills` (the `/skills` list);
  - `last_heard` (float), `heard_via` (`"beacon"` | `"poll"`), `last_refresh` (float).

  Methods:
  - `bind(host_id, address, port, health, skills, via)` creates or replaces the record, and sets `last_heard = last_refresh = clock()`.
  - `heard(address, port, via) -> host_id or None` updates `last_heard` and `heard_via` for the record at that address. It returns `None` when no record is there.
  - `refresh(host_id, health, skills, via)` replaces `role`, `version`, `proto`, `compatible` and `skills`, and sets `last_heard = last_refresh = clock()` with `heard_via = via`.
  - `is_live(host_id) -> bool`: the record exists and `clock() - last_heard <= live_window`.
  - `live_peers() -> list[dict]` returns the live records as dicts (field set of F55), sorted by `last_heard` descending and then `host_id` ascending.
  - `unheard_registered() -> list[str]`: registry host_ids other than self that are not live, sorted.
  - `due_for_refresh(interval) -> list[str]`: live host_ids with `clock() - last_refresh >= interval`, sorted.
  - `transitions() -> list[(host_id, "live" | "down")]`: changes since the previous call. Each change is reported exactly once.
  - `heard_beacon_within(window) -> bool`: some record has `heard_via == "beacon"` and `clock() - last_heard <= window`.

### 5.4 Poll fallback and refresh

- **F36.** The `poll` thread runs every `POLL_INTERVAL`. For each host_id in `table.unheard_registered()`, it runs a bind attempt (F32 steps 1-6) against the registry `address` and `port`, with `via="poll"`. It runs every cycle in both modes. Poll failures are **never logged** (F29a, K4).
- **F37.** In the same thread and cycle, for each host_id in `table.due_for_refresh(PEER_REFRESH_INTERVAL)`, it issues signed `GET /health` and `GET /skills` to the record's current address. On success it calls `table.refresh(host_id, health, skills, via=<the record's current heard_via>)`. A version change is therefore picked up only from a successful signed `/health`. A changed `proto` sets `compatible` to `False`, and the peer is listed but never called (F57, F62). Failures are not logged; the record simply ages out.
- **F38.** The `housekeeping` thread, every `HOUSEKEEPING_INTERVAL`:
  - calls `prune()` on all three nonce caches;
  - logs each `table.transitions()` entry at INFO: `peer <host_id> live at <address>:<port> (version <v>, via <heard_via>)` or `peer <host_id> down`.
- **F39.** Discovery mode, as reported in `/health`: `"beacon"` when the last beacon send succeeded **and** `table.heard_beacon_within(LIVE_WINDOW)`; otherwise `"poll"`.
- **F40.** NTP is required on every host (Section 12, step R0). The daemon does not correct clocks.

---

## 6. HTTP API

### 6.1 Listener

- **F41.** The daemon runs **exactly one** HTTP listener: a `http.server.ThreadingHTTPServer` bound to `("0.0.0.0", self_entry["port"])`, with `daemon_threads = True`. It serves five endpoints in two classes:
  - **signed endpoints** `GET /health`, `GET /skills`, `POST /run`. Any client address may call them; every request must carry a valid signature (F44).
  - **loopback-only endpoints** `GET /peers`, `POST /delegate`. They are unauthenticated (F29) and are served only to a client whose address is in `LOOPBACK_CLIENTS` (F42).

  The registry `address` is never bound and never used for self-identity (F10). It is only the poll-fallback hint (F36). A peer's current address is the source IP of its latest accepted beacon (F34), so a DHCP address change is harmless while beacons flow (Section 14, L4 covers poll-only mode). The listener's port is `self_entry["port"]` (the registry value, default 8190); the loopback URL of this daemon is therefore `"http://127.0.0.1:%d" % self_entry["port"]`, called `loopback_url` below.
- **F42.** `is_loopback_client(ip)` returns `ip in LOOPBACK_CLIENTS` (exact string comparison on `self.client_address[0]`). `http_route(method, path)` returns:
  - `("signed", "health")` for `GET /health`, `("signed", "skills")` for `GET /skills`, `("signed", "run")` for `POST /run`;
  - `("loopback", "peers")` for `GET /peers`, `("loopback", "delegate")` for `POST /delegate`;
  - `("unknown", None)` for every other method/path pair.

  A request routed `"loopback"` from a client for which `is_loopback_client` is `False` gets **403**, unsigned, with an empty body and no log line. The 403 is sent before any request body is read.
- **F43.** `log_message` is overridden to do nothing, and `handle_error` is overridden to log at ERROR exactly `http handler error: <ExcType>`. A request routed `"unknown"` is handled like a signed endpoint (F44): after it verifies, it gets a **signed** 404 with body `{"error": "not found"}`; if it does not verify, it gets the unsigned 401 of F44 step 4. **[spec choice: an unknown path reveals nothing to an unauthenticated client.]**
- **F44.** Request handling order (one handler class for all methods; `do_GET` and `do_POST` both call it):
  1. `(kind, name) = http_route(method, path)`.
  2. If `kind == "loopback"` and the client is not loopback: 403 (F42). Stop.
  3. If the method is POST and `Content-Length` is absent: 411, unsigned, empty body. Stop.
  4. If `Content-Length > MAX_BODY`: 413, unsigned, empty body. Stop.
  5. Read the body (`b""` for GET).
  6. If `kind == "loopback"`: run the endpoint (F55, F65-F67) and send its response **unsigned**. Stop.
  7. Otherwise (`"signed"` or `"unknown"`), run `verify_request` against `request_nonces`:
     - `"bad"` or `"replay"`: 401, unsigned, empty body, no log line;
     - `"skew"`: 401, unsigned, empty body, plus F33's once-per-IP WARNING.
  8. Run the endpoint (or produce the 404 of F43), and sign whatever response it produces (F29j).

  A signed endpoint called from 127.0.0.1 still requires a signature. All JSON bodies are `canonical_json` and are sent with `Content-Type: application/json` and `Content-Length`. Every fleet HTTP **client** (daemon to peer, `bin/qwen-agent` to daemon, `qwen-agentd status`, the post-update self-check) uses `http.client.HTTPConnection` directly, never `urllib`, so no proxy setting or proxy environment variable can intercept fleet traffic. **[spec choice: the Mac runs a Netskope client.]**

### 6.2 `GET /health` (signed)

- **F45.** Status 200, body `{"host_id": <self>, "role": <registry role>, "version": <release_version>, "proto": PROTOCOL, "discovery": "beacon" | "poll"}`.

### 6.3 `GET /skills` (signed)

- **F46.** Status 200, body `{"host_id": <self>, "skills": [{"skill", "model", "verified", "busy"} ...]}`. The list comes from the latest `verify_skills` result, with `busy = run_lock.locked()` on every item. Every registry-declared skill appears; consumers route only to items with `verified: true` (F57).

### 6.4 `POST /run` (signed)

- **F47.** The request body is a JSON object with exactly the keys `skill`, `task` and `request_id`, all of type `str`:
  - `task.strip() != ""`;
  - `request_id` matches `^[A-Za-z0-9-]{1,64}$`.

  Otherwise: 400 `{"error": "bad request"}`.
- **F48.** `run_lock.acquire(blocking=False)`. If the lock is not acquired (a run, or an update, is in flight): 409 `{"error": "busy"}`.
- **F49.** If `skill` is not a verified skill of this host at the latest probe: release the lock, then 400 `{"error": "skill not served: <skill>"}`.
- **F50.** The daemon spawns the child:
  - argv: `[sys.executable, qwen_agent_bin, "--skill=" + skill, "--user-prompt=" + task, "--base-url=" + self_entry["model_server"]["url"], "--model=" + self_entry["model"], "--model-server-type=" + self_entry["model_server"]["type"]]`. No other flags are passed: never `--danger-auto-approve`, `--system-prompt`, `--workspace`, or `--api-key`.
  - `qwen_agent_bin` defaults to `os.path.join(REPO_ROOT, "bin", "qwen-agent")`, the same release as the daemon. It is set by `run --qwen-agent-bin` (a test hook, F92).
  - `cwd=os.path.expanduser("~")`, `stdin=subprocess.DEVNULL`, `stdout=subprocess.PIPE`.
  - `stderr` goes to the file `<log_dir>/last-run.stderr`, opened `"w"` with mode 0o600 and overwritten on every run. **[spec choice]**
  - `env=build_child_env(os.environ, loopback_url)` (`loopback_url` as defined in F41), `start_new_session=True`, `text=True`, `errors="replace"`.
- **F51.** `proc.communicate(timeout=RUN_TIMEOUT)`. On `TimeoutExpired`, `os.killpg(proc.pid, signal.SIGKILL)` (ignoring `ProcessLookupError`), `communicate()`, then 504 `{"error": "timeout"}`.
- **F52.** If the last non-empty stdout line parses as a JSON object whose `"schema"` is `"qwen-agent.oneshot.v1"`: 200, body = that line's exact bytes (UTF-8, stripped), i.e. the envelope unchanged. Otherwise: 502 `{"error": "skill produced no parseable output (exit code <rc>)"}`.
- **F53.** The lock is released in a `finally`. Two log lines are written, and neither contains the task text: `run start skill=<s> request_id=<r> task_chars=<len(task)>` and `run end skill=<s> request_id=<r> http=<code> status=<envelope status or -> seconds=<elapsed, 1 decimal>`.
- **F54.** Decision 8 (the skill tool invariant) holds by construction:
  - The child always runs with `--skill`, so its tool set is `SKILL_TOOL_NAMES[skill]`.
  - Every name in that set is in `AUTO_APPROVE_TOOLS` (T31).
  - The child's stdin is `/dev/null`.

  No gated tool (`bash`, `write_file`, `run_python`, `generate_image`, `promote`) can be reached through `/run`.

### 6.5 Child environment

- **F54a.** `build_child_env(environ, daemon_url)` returns a **new** dict (it does not mutate `environ`) equal to `environ` except that it:
  - drops every key that starts with `FLEET_ENV_PREFIX` (`QWEN_AGENT_FLEET_`), which covers both `FLEET_ENV_KEYS` and any other `QWEN_AGENT_FLEET_*` key;
  - drops every key that starts with `SKILL_ENDPOINT_` or `SKILL_MODEL_`;
  - sets `QWEN_AGENT_DAEMON_URL = daemon_url`. The daemon passes its own `loopback_url` (F41), `http://127.0.0.1:<self_entry["port"]>`.

  Every other key passes through unchanged, including `HOME`, `PATH`, `QWEN_AGENT_HOST_ID`, and `QWEN_AGENT_SEARXNG_URL` (F77). The token never enters the daemon's environment in the first place: the daemon reads it from `fleet.env` into memory only (F22, F28). The stripping is defensive. Tests T12 and T46 verify it.
- **F54b.** Summary of the `/run` child contract. Each item is specified by the requirement named; this list adds nothing.
  - It is the current release's harness: `REPO_ROOT/bin/qwen-agent` of the release the daemon itself runs from (F50).
  - argv: `--skill=<skill> --user-prompt=<task> --base-url=<this host's model_server.url> --model=<this host's model> --model-server-type=<this host's model_server.type>` (F50).
  - Environment: `build_child_env(os.environ, loopback_url)` (F54a).
  - One run at a time per host; any other `/run` gets 409 `busy` (F48).
  - Timeout `RUN_TIMEOUT` (900 s), then `killpg(SIGKILL)` and 504 (F51).
  - The response body is the child's `qwen-agent.oneshot.v1` envelope, byte for byte (F52).
- **F54c.** If `subprocess.Popen` raises `OSError`, the handler releases the lock (through F53's `finally`) and returns 500 `{"error": "cannot start skill: <ExcType>"}`. The `run end` line reports `http=500 status=-`.

### 6.6 `GET /peers` (loopback-only, unauthenticated)

- **F55.** Status 200. The body is the **fleet view** **[spec choice]**:

```json
{
  "schema": "qwen-agentd.peers.v1",
  "self": {
    "host_id": "<self host_id>",
    "role": "<registry role>",
    "version": "<release_version>",
    "proto": 1,
    "discovery": "beacon" | "poll",
    "skills": [{"skill": "<s>", "model": "<m>", "verified": true, "busy": false}]
  },
  "peers": [
    {
      "host_id": "<id>",
      "address": "<current IPv4>",
      "port": 8190,
      "role": "<role from /health>",
      "version": "<version from /health>",
      "proto": 1,
      "compatible": true,
      "skills": [{"skill": "<s>", "model": "<m>", "verified": true, "busy": false}],
      "heard_via": "beacon" | "poll",
      "age": 12.3
    }
  ]
}
```

  - `self.skills` is built exactly like the `/skills` list (F46): the latest `verify_skills` result, with `busy = run_lock.locked()` on every item.
  - `peers` is `table.live_peers()` (F35). Each peer record has **exactly** the ten keys shown; this is "the field set of F55". `skills` is the `skills` list from that peer's latest signed `/skills` response, as received. `age` is `round(clock() - last_heard, 1)`.
  - Only live peers appear. A live but incompatible peer appears with `"compatible": false` (F62). This host never appears in `peers`.
- **F56.** `/peers` reads only in-memory state and never contacts a peer, so it answers well inside `VIEW_TIMEOUT`. A request body, if any, is ignored.

### 6.7 `POST /delegate` (loopback-only, unauthenticated)

Specified in Section 7.3 (F65-F67).

---

## 7. Routing

### 7.1 Candidates

- **F57.** Eligibility for a skill `s` in a fleet view `v`:
  - **This host** is eligible iff `v["self"]["skills"]` contains an item with `skill == s` and `verified is True`.
  - **A peer** is eligible iff it appears in `v["peers"]` (so it is live, F35), its `compatible is True`, and its `skills` contains an item with `skill == s` and `verified is True`.

  An item with `verified: false` is never routed to, wherever it appears. The `busy` flag neither filters nor reorders candidates. **[spec choice: it is stale by the time the call arrives; a busy peer answers 409 and failover moves on, F68.]**
- **F58.** Order. If this host is eligible, it is the **only** candidate. The call runs locally through today's subprocess path and never fails over to a peer. **[spec choice: "local first" means "local whenever local is verified".]** Otherwise the candidates are the eligible peers in `v["peers"]` order: most recently heard first (the latest accepted beacon, or for a poll-mode peer the latest successful signed poll or refresh), ties broken by `host_id` ascending (F35).
- **F59.** `route_candidates(skill, view)` returns `[LOCAL]` when this host is eligible. Otherwise it returns the list of eligible peer `host_id`s in F58 order, which may be `[]`. It does not mutate `view`. **[spec choice]**
- **F60.** `delegate_enum(targets, view)` returns `[t for t in targets if route_candidates(t, view)]`, a list in `targets` order.
- **F61.** `valid_view(obj)` returns `True` iff all of these hold, else `False`. It never raises. Fields not listed are not checked.
  1. `obj` is a dict and `obj.get("schema") == PEERS_SCHEMA`.
  2. `obj["self"]` is a dict with a `str` `host_id` and a list `skills`.
  3. `obj["peers"]` is a list. Each element is a dict with a `str` `host_id`, a `bool` `compatible`, and a list `skills`.
  4. Every element of every `skills` list (self and peers) is a dict with a `str` `skill` and a `bool` `verified`.
- **F62.** Incompatible peers. A live peer whose `/health` `proto` differs from `PROTOCOL` has `compatible: false` (F35, F37).
  - It is listed in `/peers` and by `qwen-agentd status` (F94), so the operator can see it.
  - F57 makes it ineligible, so it never appears in `route_candidates` or `delegate_enum`.
  - The daemon never forwards a `/delegate` to it (F65), and nothing ever sends it `POST /run`.

  It becomes callable again only when a refresh (F37) or a new bind (F32) reports a matching `proto`. That happens once both hosts run releases with the same `PROTOCOL` (Section 9.10).

### 7.2 `bin/qwen-agent` and its local daemon

- **F63.** `daemon_url_from_env(environ)` returns `(url, warning)`:
  - `QWEN_AGENT_DAEMON_URL` unset or `""`: `(DEFAULT_DAEMON_URL, None)`.
  - The value matches `DAEMON_URL_RE` and its port is in 1..65535: `(value, None)`.
  - Otherwise: `(None, "qwen-agent: warning: ignoring QWEN_AGENT_DAEMON_URL=<value>: it must be http://127.0.0.1:<port>; fleet routing disabled")`.

  **[spec choice: the variable lets the daemon tell a `/run` child which daemon spawned it (F54a), and lets tests aim `bin/qwen-agent` at one of several loopback daemons. Only loopback URLs are accepted, so `bin/qwen-agent` never sends a task to an unauthenticated non-loopback endpoint.]** `bin/qwen-agent` reads no other fleet variable and never reads `fleet.env` (F22).
- **F64.** `fetch_view(daemon_url)` sends `GET /peers` to the URL's host and port with `http.client.HTTPConnection(..., timeout=VIEW_TIMEOUT)`, and returns `(view, warning)`:
  - `daemon_url is None`: `(None, None)` with no network call.
  - Connection refused, timeout, or any other `OSError` / `http.client.HTTPException`: `(None, None)`. A missing daemon is the normal case and is silent.
  - Status 200, a body that parses as JSON, and `valid_view(body)`: `(view, None)`.
  - Anything else (a non-200 status including 403, an unparseable body, an invalid view): `(None, "qwen-agent: warning: qwen-agentd at <url> returned an unrecognized fleet view; fleet routing disabled")`.

  `bin/qwen-agent` writes any returned warning, plus `"\n"`, to `sys.stderr`. `(None, ...)` means "no daemon": `bin/qwen-agent` then behaves exactly as it does with no fleet (F69 step 1). `bin/qwen-agent` calls `fetch_view` once in `main()` to build the `delegate_to_skill` enum (F78), and again at the start of every `delegate_to_skill` call to route it (F69). Routing therefore uses a fresh view while the tool schema stays fixed for the life of the process. **[spec choice]**

### 7.3 `POST /delegate` (daemon side)

- **F65.** Request validation and eligibility **[spec choice]**:
  1. The body must be a JSON object with exactly the keys `skill`, `task` and `host_id`, all `str`, with `task.strip() != ""`, `skill in KNOWN_SKILLS`, and `host_id` matching `HOST_ID_RE`. Otherwise: 400 `{"error": "bad request"}`.
  2. The daemon re-checks eligibility against its **own current** `LivenessTable`: `host_id != self_host_id`, `table.is_live(host_id)`, the record's `compatible is True`, and the record's `skills` contains an item with `skill == <skill>` and `verified is True`. If any check fails: 200 `{"outcome": "not_live", "envelope": null, "detail": ""}`, with no network traffic.

  `/delegate` never touches `run_lock`. A `/run` child on this host can therefore delegate through this same daemon without deadlock, and several `/delegate` calls may run at once.
- **F66.** Forwarding **[spec choice]**:
  - `request_id = secrets.token_hex(8)`.
  - `body = canonical_json({"skill": skill, "task": task, "request_id": request_id})`.
  - Headers: `sign_request(key, "POST", "/run", body, int(time.time()), secrets.token_hex(16))`, plus `Content-Type: application/json` and `Content-Length`.
  - The request goes to the record's **current** `address` and `port` (F34) through `http.client.HTTPConnection(address, port, timeout=FORWARD_TIMEOUT)`. The response body is read with `resp.read(MAX_BODY + 1)`.

  The outcome is the first matching row:

  | Condition | `outcome` | `detail` |
  |---|---|---|
  | `socket.timeout` / `TimeoutError` at any stage | `timeout` | `""` |
  | any other `OSError` or `http.client.HTTPException` | `unreachable` | `<ExcType>` |
  | the response body is longer than `MAX_BODY` | `bad_response` | `""` |
  | `verify_response(key, status, "POST", "/run", <request nonce>, resp_headers, body, int(time.time()), response_nonces) != "ok"` | `bad_signature` | `""` |
  | verified status 409 | `busy` | `""` |
  | verified status 504 | `timeout` | `""` |
  | verified status 200, and the body is a JSON object whose `schema` is `ONESHOT_SCHEMA` | `ok` | `""` |
  | verified status 200, any other body | `bad_response` | `""` |
  | any other verified status | `peer_error` | `"http <code>"` |

  A peer's 401 is unsigned, so it lands on `bad_signature`. The body of a response that fails verification is never parsed (F29j).
- **F67.** Response: 200, unsigned, body `canonical_json({"outcome": <outcome>, "envelope": <the parsed envelope dict when outcome is "ok", else None>, "detail": <detail>})`. One INFO log line, never containing the task or the answer: `delegate skill=<s> host=<h> request_id=<r> outcome=<o> seconds=<elapsed, 1 decimal>`. The `request_id` matches this line to the peer's `run start` / `run end` lines (F53). On a `not_live` outcome no `request_id` exists, and the line shows `request_id=-`.

### 7.4 `bin/qwen-agent` side

- **F68.** Two client functions in `fleet_lib` **[spec choice]**:
  - `delegate_once(daemon_url, skill, task, host_id)` sends `POST /delegate` with body `canonical_json({"skill": skill, "task": task, "host_id": host_id})` through `http.client.HTTPConnection(..., timeout=DELEGATE_CLIENT_TIMEOUT)`. It returns `(outcome, envelope, detail)`, never raises an `Exception`, and maps as follows (first match wins):

    | Condition | Return |
    |---|---|
    | `daemon_url is None`, any `OSError` / `http.client.HTTPException` / timeout | `("daemon_error", None, "<ExcType>")` (`"no daemon"` when the URL is `None`) |
    | status != 200 | `("daemon_error", None, "http <code>")` |
    | the body is not a JSON object with a `str` `outcome`, a `str` `detail`, and an `envelope` key | `("daemon_error", None, "bad response")` |
    | `outcome == "ok"` and `envelope` is not a dict whose `schema` is `ONESHOT_SCHEMA` | `("daemon_error", None, "bad response")` |
    | otherwise | `(outcome, envelope, detail)` |

  - `failover(candidates, attempt)`, where `attempt(host_id)` returns `(outcome, envelope)`:

    ```python
    def failover(candidates, attempt):
        tried = []
        for host_id in candidates:
            try:
                outcome, envelope = attempt(host_id)
            except Exception:
                outcome, envelope = "error", None
            if outcome == "ok":
                return {"outcome": "ok", "host_id": host_id, "envelope": envelope, "tried": tried}
            tried.append((host_id, outcome))
        return {"outcome": "exhausted", "host_id": None, "envelope": None, "tried": tried}
    ```

    A `BaseException` that is not an `Exception` (`KeyboardInterrupt`) propagates.

  Every non-`ok` outcome moves to the next candidate: `busy`, `timeout`, `bad_signature`, `unreachable`, `not_live`, `bad_response`, `peer_error`, `daemon_error`, `error`. This covers the brief's 409, timeout (900 + 30 s) and bad-signature cases, plus every other way a peer can fail mid-run.
- **F69.** The `delegate_to_skill` flow in `exec_delegate_to_skill` (code placement in F78). It runs after the existing task and enum checks **[spec choice]**:
  1. If `FLEET is None` or `FLEET_DAEMON_URL is None`: take the **local path**, which is today's code from the `[delegating to ...]` print through the envelope mapping, with no change other than F78(e) and F78(f).
  2. `view, warning = FLEET.fetch_view(FLEET_DAEMON_URL)`. Print any warning (F64). If `view is None`: local path.
  3. `candidates = FLEET.route_candidates(skill, view)`. If `candidates == [FLEET.LOCAL]`: local path.
  4. Otherwise run the **remote path** `_delegate_remote(skill, task, candidates)`:
     - Each attempt first prints `[delegating to <skill> on <host_id>, up to <SKILL_SUBPROCESS_TIMEOUT>s...]` to `_ui()`. It then calls `FLEET.delegate_once(FLEET_DAEMON_URL, skill, task, host_id)` and returns `(outcome, envelope)` to `failover`. When the outcome is not `ok`, it prints `[<skill> on <host_id> failed: <outcome>]` to `_ui()`.
     - `result = FLEET.failover(candidates, attempt)`.
  5. Result strings of the remote path:
     - `result["outcome"] == "ok"`: `_envelope_to_result(skill, result["envelope"])`. This is the exact mapping the local path uses (F78(e)).
     - `candidates == []`: `ERROR: no live host serves '<skill>'`.
     - Exhausted with `tried` non-empty: `ERROR: no live host serves '<skill>' (tried: <h1>: <o1>; <h2>: <o2>)`, with the pairs joined by `"; "` in attempt order.
     - A `KeyboardInterrupt` during an attempt is caught in `_delegate_remote`, which returns `ERROR: execution was interrupted by the user before the <skill> skill finished on <host_id>. The remote run may still be in progress there.` Cancelling a remote run is out of scope (Section 0.4).

  The remote path never raises. Every string it returns that is not an answer starts with `ERROR:`, so the duplicate guard and circuit breaker see it like any other tool failure ([SKILLS] Section 1.2, criterion 9). If the local daemon is unreachable, at startup or at call time, `bin/qwen-agent` behaves exactly as it does today (plus the researcher port, Section 8).

---

## 8. `bin/qwen-agent` changes

Line numbers refer to `bin/qwen-agent` as read on 2026-10-16 (Section 0.2). No other part of the file changes.

### 8.1 Optional `fleet_lib`

- **F70.** `bin/qwen-agent` must work unchanged when `fleet_lib.py` is absent (the deploy package ships `bin/qwen-agent` alone, `scripts/deploy/build_pkg.py:383-385`). **[spec choice]**
  - Add two module globals directly after `TOOL_BY_NAME = None` (`:632`): `FLEET = None` and `FLEET_DAEMON_URL = None`.
  - Add this function directly after them:

    ```python
    def _load_fleet_lib():
        """fleet_lib.py beside bin/, or None. Absent (deploy package) means no fleet routing."""
        path = os.path.join(REPO_ROOT, "fleet_lib.py")
        if not os.path.isfile(path):
            return None
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("fleet_lib", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception as e:
            sys.stderr.write("qwen-agent: warning: cannot load %s (%s: %s); fleet routing disabled\n"
                             % (path, type(e).__name__, e))
            return None
    ```

  - The top-level import block (`:26-43`) is not changed. The module is not inserted into `sys.modules`. `_load_fleet_lib` is called only from `main()` (F78(b)), so importing `bin/qwen-agent` stays free of side effects (`tests/test_qwen_agent_context_budget.py:30-41`).

### 8.2 Researcher constants

- **F71.** `SKILL_TOOL_NAMES` (`:152-156`) gains a fourth entry after `planner`: `"researcher":   ("search", "fetch_url", "read_file", "calculate"),`. The INVARIANT comment (`:157-161`) is unchanged and still holds (T31).
- **F72.** `DELEGATE_TARGETS` (`:165-168`) becomes `None -> ("investigator", "analyst", "planner", "researcher")` and `"investigator" -> ("analyst", "researcher")`. No other key is added; researcher has no `delegate_to_skill`, so the chain stays at depth 2.
- **F73.** `SKILL_THINK_TEMP_DEFAULTS` (`:170-174`) gains `"researcher":   {"think": False, "temperature": 0.7},`.

### 8.3 Researcher system prompt

- **F74.** `SKILL_SYSTEM_PROMPTS` (`:1887-1970`) gains a fourth entry after `planner`. Its key is `"researcher"`. Its value is the parenthesized string literal copied **verbatim** from `agent/qwen-agent-unsafe:1613-1636`, from `"You are the researcher sub-agent for qwen-agent, delegated ONE focused "` through `"agent that delegated the task to you."`. It contains the `{workspace}` placeholder that `build_skill_system_message` (`:1973-1975`) fills. The investigator's prompt is not changed (Section 14, L5).

### 8.4 CLI flags

- **F75.** In `parse_args` (`:3660-3691`) **[spec choice]**:
  - `--skill` gets `choices=("investigator", "analyst", "planner", "researcher")`.
  - A new flag is added directly after `--api-key`:

    ```python
    parser.add_argument("--model-server-type", type=str, default="vllm", choices=("vllm", "ollama"),
                        help="Type of the model server at --base-url. 'ollama' makes think-off "
                             "requests send reasoning_effort=none, because Ollama's /v1 ignores "
                             "chat_template_kwargs.enable_thinking.")
    ```

  The daemon passes `--model-server-type=<registry model_server.type>` to every `/run` child (F50). A human may pass it to the REPL or to one-shot mode.

### 8.5 Ollama thinking-off

- **F76.** In `chat_completion` (`:1775-1799`), directly after the `body` dict and before `if not include_tools:`, insert:

  ```python
      if getattr(args_ns, "model_server_type", "vllm") == "ollama" and not args_ns.think:
          body["reasoning_effort"] = "none"
  ```

  `getattr` keeps working for callers (including existing tests) that build `args_ns` without the attribute. With the default `vllm`, the request body is byte-identical to today's. The preflight tool probe (`preflight`, `:2281-2405`) is not changed.

### 8.6 SearXNG override

- **F77.** Replace `SEARXNG_BASE_URL = "http://127.0.0.1:8888"` (`:179`) with **[spec choice]**:

  ```python
  # QWEN_AGENT_SEARXNG_URL overrides it on hosts without a local instance (fleet spec F77).
  SEARXNG_BASE_URL = os.environ.get("QWEN_AGENT_SEARXNG_URL", "").strip().rstrip("/") or "http://127.0.0.1:8888"
  ```

  When the variable is unset, empty, or whitespace, the value is unchanged from today. The value is not otherwise validated; a bad URL shows up as `searxng_probe`'s existing warning and as `search` tool errors.

### 8.7 Routing hooks

- **F78.** Changes that wire Section 7 into the harness:
  - **(a)** `build_tools_for_context(skill)` (`:610-628`) becomes `build_tools_for_context(skill, delegate_targets=None)`. In its body, the line `tools.append(_build_delegate_tool(DELEGATE_TARGETS[skill]))` is replaced with:

    ```python
        targets = DELEGATE_TARGETS[skill] if delegate_targets is None else tuple(delegate_targets)
        if targets:
            tools.append(_build_delegate_tool(targets))
    ```

    With `delegate_targets=None` the result is identical to today's. An empty list omits the `delegate_to_skill` tool entirely **[spec choice: an empty JSON-schema enum is invalid]**. `dispatch()` then rejects a forced call as an unknown tool, as it already does.
  - **(b)** In `main()` (`:3694-3741`), the two lines that set `TOOLS` and `TOOL_BY_NAME` (`:3698-3699`) are replaced with the following block, and `FLEET, FLEET_DAEMON_URL` are added to the `global` statement at `:3697`:

    ```python
        FLEET = _load_fleet_lib()
        view = None
        if FLEET is not None:
            FLEET_DAEMON_URL, warning = FLEET.daemon_url_from_env(os.environ)
            if warning:
                sys.stderr.write(warning + "\n")
            view, warning = FLEET.fetch_view(FLEET_DAEMON_URL)
            if warning:
                sys.stderr.write(warning + "\n")
        delegate_targets = None
        if view is not None and args_ns.skill in DELEGATE_TARGETS:
            delegate_targets = FLEET.delegate_enum(DELEGATE_TARGETS[args_ns.skill], view)
        TOOLS = build_tools_for_context(args_ns.skill, delegate_targets)
        TOOL_BY_NAME = {t["function"]["name"]: t for t in TOOLS}
        if view is not None and args_ns.user_prompt is None:
            sys.stderr.write("[fleet: qwen-agentd at %s; %d live peer(s); delegate targets: %s]\n"
                             % (FLEET_DAEMON_URL, len(view["peers"]),
                                ", ".join(delegate_targets) if delegate_targets else "none"))
    ```

    The fleet line is printed only in REPL mode. **[spec choice: it gives the operator one visible confirmation, used in R7; one-shot children stay quiet.]**
  - **(c)** In `exec_delegate_to_skill` (`:1224-1315`), directly after the enum check (`:1237-1239`) and before the `[delegating to ...]` print (`:1241`), insert:

    ```python
        if FLEET is not None and FLEET_DAEMON_URL is not None:
            view, warning = FLEET.fetch_view(FLEET_DAEMON_URL)
            if warning:
                sys.stderr.write(warning + "\n")
            if view is not None:
                candidates = FLEET.route_candidates(skill, view)
                if candidates != [FLEET.LOCAL]:
                    return _delegate_remote(skill, task, candidates)
    ```

  - **(d)** A new function `_delegate_remote(skill, task, candidates)` directly after `exec_delegate_to_skill` implements F69 steps 4-5.
  - **(e)** The envelope-to-string mapping at `:1308-1315` (from `status = envelope.get("status")` to the final `return`) moves, verbatim, into a new function `_envelope_to_result(skill, envelope)` placed directly before `exec_delegate_to_skill`. The local path's tail becomes `return _envelope_to_result(skill, envelope)`. The JSON-parse `try` block above it stays where it is.
  - **(f)** In the local path's argv (`:1243-1257`), directly before `if args_ns.api_key:`, insert:

    ```python
        if args_ns.model_server_type != "vllm":
            argv.append("--model-server-type=%s" % args_ns.model_server_type)
    ```

    With the default `vllm`, the argv is byte-identical to today's. **[spec choice]**

### 8.8 Not ported

- **F79.** These items are **not** added to `bin/qwen-agent`: `SKILL_ENDPOINT_OVERRIDES`, `SKILL_MODEL_OVERRIDES`, `OLLAMA_SKILLS`, and any read of `SKILL_ENDPOINT_*` / `SKILL_MODEL_*`. The registry supersedes them: a skill runs on the host that serves it, against that host's own model server. No code in `bin/qwen-agent`, `fleet_lib.py`, `bin/qwen-agentd` or `bin/qwen-agentd-launch` reads those variables, and `build_child_env` strips them (F54a). `agent/qwen-agent-unsafe` and `tests/test_researcher_think_off.py` are not touched. That test continues to test only the unsafe agent, so the real harness port is covered by the new tests T30-T34.

### 8.9 Revisions to [SKILLS]

| [SKILLS] section | Revision |
|---|---|
| 1.1, 6.2 (a delegated skill always runs as a local subprocess against the parent's model server) | When a daemon is reachable and this host does not serve the skill with a verified model, the skill runs on a live peer through `POST /delegate` (Section 7). The local subprocess path is otherwise unchanged. |
| 1.2 criterion 10 (py_compile on 3.9 and 3.13) | Also applies to `fleet_lib.py`, `bin/qwen-agentd` and `bin/qwen-agentd-launch` (T71). |
| 2 (`DELEGATE_TARGETS`) | Top level adds `researcher`; investigator adds `researcher` (F72). |
| 3 (`build_tools_for_context`, enum of three at top level and one under investigator) | Up to four at top level and two under investigator. With a reachable daemon, the enum is filtered to skills the fleet serves at startup, and the tool is omitted when the filter leaves nothing (F78(a), F78(b)). |
| 4.1 (`--skill` choices) | Adds `researcher`. Adds `--model-server-type` (F75). |
| 4.2 (`SKILL_THINK_TEMP_DEFAULTS`) | Adds researcher: think off, temperature 0.7 (F73). |
| 4.3 (`chat_completion` body) | Adds `reasoning_effort: "none"` for an Ollama server with thinking off (F76). |
| 4.4 (per-role system prompts) | Adds the researcher prompt (F74). |
| 7 (recursion depth: top level, then investigator, then analyst) | The longest chain is top level, then investigator, then analyst or researcher. Depth is still 2, now possibly across hosts. |
| 8 ("no test framework exists") | pytest suites now exist for this feature (Section 11). |

---

## 9. Self-update

### 9.1 Deploy root

> **Superseded in part by multi-agent hosts** (M2, M3, M9-M12): F80's `D` is `~/agents/<host_id>/`, and `~/.local/bin/qwen-agent` and `~/.local/bin/qwen-agent-<id>` are generated wrappers, not symlinks.

- **F80.** `deploy_root()` returns `os.path.expanduser(DEPLOY_ROOT)`, i.e. `D = ~/.local/share/qwen-agent/`. It is the same on every host. The daemon that self-updates always runs from `D`, never from the dev checkout `~/local_agent_harness`. Layout:

  | Path | What | Created by |
  |---|---|---|
  | `D/` | mode `0o700` | `install` (F91) |
  | `D/repo/` | `git clone --bare <origin> D/repo`. Fetch-only: nothing ever commits or pushes in it. `origin` is `ORIGIN_URL` (public, no credentials) unless `install --origin` was given (a test hook). | `install` |
  | `D/releases/<tag>/` | one `git worktree` per release, detached at `refs/tags/<tag>`. The daemon runs from `D/releases/<tag>/qwen-agent-workspace/`. | `install`, updater (F86) |
  | `D/current` | a symlink whose target is the **relative** path `releases/<tag>`. Always swapped atomically: `os.symlink("releases/<tag>", D/".current.tmp")` (after unlinking a leftover `.current.tmp`), then `os.replace(D/".current.tmp", D/"current")`. **[spec choice: relative, so the tree survives a `$HOME` move.]** | `install`, updater (F85 step 7), launcher (F89) |
  | `D/update-state.json` | the update state (F83) | `install`, updater, launcher, confirm thread |
  | `D/qwen-agentd-launch` | a copy of the current release's `bin/qwen-agentd-launch`, mode `0o755`; it lives outside `releases/`, so no update replaces it | `install` |

  `~/.local/bin/qwen-agent` is a symlink to `D/current/qwen-agent-workspace/bin/qwen-agent`, so the user's command follows every update (F91 step 9).

### 9.2 Release tags and versions

- **F81.** A release tag matches `TAG_RE`, i.e. `^v\d{4}\.\d{2}\.\d{2}(\.[1-9]\d*)?$` (for example `v2026.10.17`, `v2026.10.17.1`). Only tags are ever deployed; branches never are. No tags exist yet (Section 0.2). `tag_key(tag)` returns `None` when `TAG_RE` does not match. Otherwise it returns `(int(year), int(month), int(day), int(n or 0))`. Tags are compared only by `tag_key`, so `v2026.10.17 < v2026.10.17.1 < v2026.10.17.2 < v2026.10.17.10 < v2026.10.18`.
- **F82.** `release_version(repo_root, deploy_root)`. Let `rr = os.path.realpath(repo_root)` and `parent = os.path.dirname(rr)`. It returns `os.path.basename(parent)` when all of these hold:
  - `os.path.basename(rr) == WS_SUBDIR`;
  - `os.path.dirname(parent) == os.path.realpath(os.path.join(deploy_root, "releases"))`;
  - `tag_key(os.path.basename(parent)) is not None`.

  Otherwise it returns `"dev"`. A `dev` daemon (for example one run from the dev checkout) never starts the updater (Section 1.2).

### 9.3 Update state

- **F83.** `D/update-state.json` is a JSON object with exactly these keys:

  | Key | Type | Meaning |
  |---|---|---|
  | `from` | `str` or `null` | the release that was running before the latest switch |
  | `to` | `str` or `null` | the release the latest switch (or `install`) moved to |
  | `status` | `"ok"`, `"pending"` or `"rolled_back"` | `pending` from the switch until the new daemon passes its self-check (F88) |
  | `attempts` | `int` >= 0 (not `bool`) | launcher starts counted while `pending` (F89) |
  | `bad_tags` | list of `str` | tags that failed their gate or were rolled back; never selected again |

  - `read_state(path)` returns the parsed dict. If the file is missing, unreadable, unparseable, or breaks the table above, it returns the default `{"from": None, "to": None, "status": "ok", "attempts": 0, "bad_tags": []}`. It never raises. **[spec choice]**
  - `write_state(path, state)` writes `canonical_json(state) + b"\n"` to `path + ".tmp"` (opened with `os.O_WRONLY | os.O_CREAT | os.O_TRUNC`, mode `0o600`), `fsync`s, then `os.replace`s it onto `path`.
  - `bin/qwen-agentd-launch` carries its own copies of both functions with identical behavior (F89). Test T29 checks that each side reads what the other writes.

### 9.4 Update cycle

- **F84.** Schedule. The `updater` thread loops: sleep `UPDATE_INTERVAL * scale + random.uniform(0, UPDATE_JITTER * scale)` (900 s plus 0-120 s at scale 1; it waits on the stop event, so shutdown interrupts the sleep), then call `run_update_cycle(ctx)`. The first cycle therefore runs one period after start. `ctx` is the daemon's real implementation of the interface in F85. Tests pass a fake. The cycle's return value is one of `"fetch_failed"`, `"up_to_date"`, `"dirty"`, `"busy"`, `"stage_failed"`, `"gate_failed"`, `"error"`, `"switched"`.
- **F85.** The `ctx` interface, and the real implementation of each method. Every git call is `subprocess.run([...], capture_output=True, text=True, timeout=GIT_TIMEOUT)`. A `TimeoutExpired` counts as a failure with detail `"timeout"`. `<detail>` of a failed git call is `"exit <rc>: <last non-empty stderr line, or ->"`. **[spec choice]**

  | Method | Real implementation |
  |---|---|
  | `fetch() -> (ok, detail)` | `git -C D/repo fetch origin --tags`; `ok` iff exit 0 |
  | `list_tags() -> list[str]` | `git -C D/repo tag --list`, stripped non-empty lines; `[]` on failure |
  | `is_ancestor(a, b) -> bool` | `git -C D/repo merge-base --is-ancestor refs/tags/<a> refs/tags/<b>`; `True` iff exit 0 |
  | `current_tag() -> str` | the daemon's own `release_version` (F82) |
  | `is_dirty() -> bool` | `git -C REPO_ROOT status --porcelain --untracked-files=no`; `True` iff stdout is non-empty or the exit is non-zero |
  | `try_lock() -> bool`, `unlock()` | `run_lock.acquire(blocking=False)`, `run_lock.release()` |
  | `read_state()`, `write_state(s)` | F83 on `D/update-state.json` |
  | `stage(tag) -> (ok, detail)` | F86 |
  | `gate(tag) -> (ok, detail)` | F86 |
  | `unstage(tag)` | `git -C D/repo worktree remove --force D/releases/<tag>`, then `shutil.rmtree(D/releases/<tag>, ignore_errors=True)`, then `git -C D/repo worktree prune`; failures are logged at WARNING and ignored |
  | `swap(tag)` | the atomic symlink swap of F80, pointing `D/current` at `releases/<tag>` |
  | `restart()` | F87 |
  | `log(level, msg)` | the daemon logger |

  `run_update_cycle(ctx)`, exactly:
  1. `ok, detail = ctx.fetch()`. If not `ok`: log WARNING `update: git fetch failed (<detail>); retrying next cycle` and return `"fetch_failed"`.
  2. `state = ctx.read_state()`; `cur = ctx.current_tag()`; `cand = select_candidate(ctx.list_tags(), cur, state["bad_tags"], ctx.is_ancestor)`. If `cand is None`: return `"up_to_date"` (no log line).
  3. If `ctx.is_dirty()`: log WARNING `update: <cand> available but the current release has modified tracked files; not updating` and return `"dirty"`.
  4. If not `ctx.try_lock()`: log INFO `update: <cand> deferred: a run is in flight` and return `"busy"`. From here until step 7's restart, or until the cycle returns, the lock is held, so every `POST /run` gets 409 (F48).
  5. `ok, detail = ctx.stage(cand)`. If not `ok`: `ctx.unlock()`, log WARNING `update: staging <cand> failed (<detail>)`, and return `"stage_failed"`. The tag is **not** marked bad: staging failures are local and transient.
  6. `ok, detail = ctx.gate(cand)`. If not `ok`: re-read the state, append `cand` to `bad_tags` if it is absent, `ctx.write_state(state)`, `ctx.unstage(cand)`, `ctx.unlock()`, log WARNING `update: <cand> failed its gate (<detail>); marked bad`, and return `"gate_failed"`.
  7. `prev = ctx.read_state()`. Then `ctx.write_state({"from": cur, "to": cand, "status": "pending", "attempts": 0, "bad_tags": prev["bad_tags"]})`, and log INFO `update: switching <cur> -> <cand>`. Then call `ctx.swap(cand)`. If it raises: `ctx.write_state(prev)`, `ctx.unlock()`, log ERROR `update: swap to <cand> failed (<ExcType>: <msg>)`, and return `"error"`. Otherwise call `ctx.restart()`, which in production never returns, then return `"switched"`.

  Any exception raised in steps 5-7 before `ctx.restart()` is called (other than the `swap` failure handled in step 7) is caught: `ctx.unlock()`, log ERROR `update: <ExcType>: <msg>`, return `"error"`. An exception from `ctx.restart()` itself is not caught (F87). An exception in steps 1-4 propagates to the thread guard (F97) with no lock held.
- **F85a.** `select_candidate(tags, current, bad_tags, is_ancestor)` **[spec choice]**:

  ```python
  def select_candidate(tags, current, bad_tags, is_ancestor):
      ck = tag_key(current)
      if ck is None:
          return None
      newer = [t for t in set(tags)
               if tag_key(t) is not None and tag_key(t) > ck and t not in bad_tags]
      for t in sorted(newer, key=tag_key, reverse=True):
          if is_ancestor(current, t):
              return t
      return None
  ```

  The result is the highest tag that is newer than `current`, descends from `current`, and is not bad. A newer tag that does not descend from `current` (for example one on an unrelated branch) is never selected. `is_ancestor` is called lazily, from the highest tag down.

### 9.5 Staging and the gate

- **F86.** Staging and the gate:
  - `stage(tag)`: if `D/releases/<tag>` exists (a leftover), run `unstage(tag)` first. Then `git -C D/repo worktree add --detach D/releases/<tag> refs/tags/<tag>`. `ok` iff exit 0.
  - `gate(tag)`, with `ws = D/releases/<tag>/qwen-agent-workspace` and `env = {k: v for k, v in os.environ.items() if not k.startswith(FLEET_ENV_PREFIX)}`:
    1. `[sys.executable, "-m", "py_compile", ws + "/bin/qwen-agent", ws + "/bin/qwen-agentd"]`, `cwd=ws`, `timeout=GATE_TIMEOUT`. A non-zero exit fails the gate with detail `"py_compile exit <rc>"`.
    2. `[sys.executable, ws + "/bin/qwen-agentd", "selftest"]`, `cwd=ws`, `env=env`, `start_new_session=True`, stdout and stderr both written to `<log_dir>/gate-<tag>.log` (opened `"w"`, mode `0o600`). It is bounded by `GATE_TIMEOUT`; on timeout the process group gets `SIGKILL`. A non-zero exit fails the gate with detail `"selftest exit <rc>"`; a timeout fails it with `"selftest timeout"`. **[spec choice: the gate log keeps pytest's output for diagnosis.]**

  `selftest` is the staged release's own subcommand (F93), so the gate runs the **new** release's tests against the **new** release's code.

### 9.6 Switch and post-switch self-check

- **F87.** `restart()`:
  1. Flush and close every logging handler.
  2. `os.execv(sys.executable, [sys.executable, os.path.join(D, "current", WS_SUBDIR, "bin", "qwen-agentd")] + sys.argv[1:])`.

  The PID stays the same. Python sockets are created non-inheritable (PEP 446), so the TCP listener and the UDP socket close at `exec`, and the new process can bind the same ports (`ThreadingHTTPServer` sets `allow_reuse_address`). An `OSError` from `os.execv` is not caught: it ends the process, the supervisor restarts it through the launcher, and the launcher counts that start (F89). `sys.argv[1:]` is whatever the launcher passed (F89), so test flags survive the restart.
- **F88.** Self-check by the new daemon. At startup, after the listener is serving (F95 step 10), the daemon reads the state. If `status == "pending"` and `to == <own version>`, it starts the `confirm` thread **[spec choice]**:
  - Every 1 s, until `STARTUP_HEALTH_DEADLINE` (120 s, never scaled) has passed since process start (`time.monotonic()` taken at the top of `run`), it sends a signed `GET /health` to `http://127.0.0.1:<port>/health` (timeout `PEER_HTTP_TIMEOUT`). Success means the response verifies, the status is 200, and `host_id` equals its own.
  - On success it writes `{"from": <from>, "to": <to>, "status": "ok", "attempts": 0, "bad_tags": <unchanged>}`, logs INFO `update: now running <to> (from <from>)`, and prunes: for each `t` in `releases_to_prune(os.listdir(D/releases), <own version>, state)`, it calls `unstage(t)`.
  - On deadline it logs ERROR `update: <to> did not answer its own /health within 120s; exiting for rollback`, flushes the log handlers, and calls `os._exit(1)`.

  Startup steps 1-9 of F95 already cover "load registry, probe model server, bind port". A failure there exits 2 before the self-check, and the launcher counts the restart (F89).
- **F88a.** `releases_to_prune(present, current, state)` **[spec choice]**:
  - `cands` = the names in `present` for which `tag_key` is not `None`. Other names are never touched.
  - `keep` = `{current}`, plus `state["from"]` if it is not `None`, plus the `KEEP_RELEASES` (3) highest of `cands` by `tag_key`.
  - It returns `sorted([n for n in cands if n not in keep], key=tag_key)`.

  So the current release, the rollback target, and the three newest stay on disk.

### 9.7 Launcher and rollback

- **F89.** `bin/qwen-agentd-launch` (installed as `D/qwen-agentd-launch`) is stdlib-only, never imports `fleet_lib`, has the same interpreter constraint as F1, and runs only through `if __name__ == "__main__":`. It defines its own `MAX_START_ATTEMPTS = 3` (T26 asserts it equals `fleet_lib.MAX_START_ATTEMPTS`), its own `read_state` / `write_state` (F83), and **[spec choice]**:

  ```python
  def launcher_step(state, from_available):
      if state["status"] != "pending":
          return state, "exec"
      new = dict(state, attempts=state["attempts"] + 1)
      if new["attempts"] < MAX_START_ATTEMPTS or not from_available:
          return new, "exec"
      bad = list(state["bad_tags"])
      if state["to"] is not None and state["to"] not in bad:
          bad.append(state["to"])
      new.update(status="rolled_back", bad_tags=bad)
      return new, "rollback"
  ```

  Its main:
  1. `D = os.path.dirname(os.path.realpath(__file__))`; `state = read_state(D/update-state.json)`.
  2. `from_available = state["from"] is not None and os.path.isdir(D/releases/<from>)`.
  3. `new, action = launcher_step(state, from_available)`.
  4. If `action == "rollback"`: swap `D/current` to `releases/<from>` (F80), **then** `write_state(new)`, then write `qwen-agentd-launch: <to> failed to start <attempts> times; rolled back to <from>` to stderr. Swapping first means a crash between the two steps repeats an idempotent rollback on the next start.
  5. Else, if `new != state`: `write_state(new)`.
  6. `os.execv(sys.executable, [sys.executable, os.path.join(D, "current", "qwen-agent-workspace", "bin", "qwen-agentd"), "run"] + sys.argv[1:])`.

  Counting: the updater's `execv` is start 0 of the new release (`attempts` 0). Each supervisor restart while `pending` passes through the launcher and adds 1. The launcher start that brings `attempts` to 3 rolls back instead. A bad release is therefore started at most 3 times, then the host runs `from` again with `to` in `bad_tags` and `status: rolled_back`. `rolled_back` stays until the next switch overwrites it. When `from` is unavailable (`None` or missing on disk, which pruning never causes), the launcher keeps exec'ing `current`. This cannot recover, and is logged on every start by the daemon's own startup errors.

### 9.8 Supervisors

> **Superseded in part by multi-agent hosts** (M6): F90's label is `com.qwen-agent.qwen-agentd.<id>` and its unit is `qwen-agentd-<id>.service`.

- **F90.** `install` writes and loads one service per platform. The interpreter recorded in it is `sys.executable` of the `install` process (`PY` below). `HOST_ID` is `install --host-id`. **[spec choice]**
  - **macOS** (`sys.platform == "darwin"`): `~/Library/LaunchAgents/com.qwen-agent.qwen-agentd.plist`, written with `plistlib.dumps` of exactly:

    ```python
    {"Label": LAUNCHD_LABEL,
     "ProgramArguments": [PY, D + "/qwen-agentd-launch"],
     "EnvironmentVariables": {"QWEN_AGENT_HOST_ID": HOST_ID,
                              "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
     "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": SUPERVISOR_RESTART_DELAY,
     "StandardOutPath": log_dir() + "/launchd.out", "StandardErrorPath": log_dir() + "/launchd.err"}
    ```

    It is loaded with `launchctl bootout gui/<uid>/com.qwen-agent.qwen-agentd` (exit status ignored), then `launchctl bootstrap gui/<uid> <plist path>`, where `<uid>` is `os.getuid()`. A non-zero exit from `bootstrap` makes `install` exit 2 with `qwen-agentd: launchctl bootstrap failed (exit <rc>)`.
  - **Linux** (`sys.platform.startswith("linux")`): first, `loginctl show-user <user> -p Linger`, where `<user> = getpass.getuser()`, must print exactly `Linger=yes`. Otherwise `install` exits 2 with `qwen-agentd: user lingering is off, so the daemon would stop at logout; run: sudo loginctl enable-linger <user>`. This check runs before anything is written. The unit file is `~/.config/systemd/user/qwen-agentd.service`:

    ```ini
    [Unit]
    Description=qwen-agent fleet daemon
    StartLimitIntervalSec=0

    [Service]
    ExecStart=PY D/qwen-agentd-launch
    Environment=QWEN_AGENT_HOST_ID=HOST_ID
    Restart=always
    RestartSec=10

    [Install]
    WantedBy=default.target
    ```

    `PY`, `D` and `HOST_ID` are substituted as absolute values. Then run `systemctl --user daemon-reload`, `systemctl --user enable qwen-agentd.service`, and `systemctl --user restart qwen-agentd.service`; a non-zero exit from any of them makes `install` exit 2 with `qwen-agentd: <command> failed (exit <rc>)`. `StartLimitIntervalSec=0` stops systemd from giving up on a crash loop, for example while `fleet.env` is still missing (F91 step 11).
  - Any other platform: `install` exits 2 with `qwen-agentd: unsupported platform <sys.platform>`.

  Both supervisors restart a dead daemon after 10 s and always go through the launcher, which is what makes rollback work (F89).

### 9.9 `install`

> **Superseded in part by multi-agent hosts** (M25, M26): F91 takes `--agent-id` (alias `--host-id`) and `--default`, writes wrappers, and prints new lines.

- **F91.** `qwen-agentd install --host-id ID [--origin URL] [--no-service]`. `--origin` (default `ORIGIN_URL`) and `--no-service` (write and load no service file, and skip the linger check) are test hooks. `install` is idempotent: re-running it refreshes the launcher, the symlink and the service, but never re-clones and never changes `current`. Steps, in order; every failure prints the message shown to stderr and exits 2 **[spec choice]**:
  1. `ID` must match `HOST_ID_RE`: `qwen-agentd: invalid --host-id '<ID>'`.
  2. `git --version` must exit 0: `qwen-agentd: git is required`.
  3. `[sys.executable, "-c", "import pytest"]` must exit 0: `qwen-agentd: pytest is required for the self-update gate (install python3-pytest, or pip install pytest, for <sys.executable>)`.
  4. On Linux without `--no-service`: the linger check (F90).
  5. `os.makedirs(D, exist_ok=True)`, then `os.chmod(D, 0o700)`. Create `log_dir()` the same way (F107); step 8's gate writes its log there.
  6. If `D/repo` is absent: `git clone --bare <origin> D/repo`. Otherwise `git -C D/repo fetch origin --tags`. Failure: `qwen-agentd: git <clone|fetch> failed (<detail>)`.
  7. `tags = [t for t in <git -C D/repo tag --list> if tag_key(t) is not None]`. If empty: `qwen-agentd: no release tags (vYYYY.MM.DD[.N]) at <origin>; tag a release first`.
  8. If `D/current` does not exist: `tag = max(tags, key=tag_key)`; `stage(tag)`; `gate(tag)` (F86). A failure gives `qwen-agentd: first release <tag> failed its gate (<detail>); see <log_dir>/gate-<tag>.log`. Then swap `D/current` to it, and `write_state` `{"from": None, "to": tag, "status": "ok", "attempts": 0, "bad_tags": []}`. If `D/current` exists, it is left unchanged.
  9. Copy `D/current/qwen-agent-workspace/bin/qwen-agentd-launch` to `D/qwen-agentd-launch` (write to a temp file in `D`, `chmod 0o755`, `os.replace`). Then make `~/.local/bin/` and point `~/.local/bin/qwen-agent` at `D/current/qwen-agent-workspace/bin/qwen-agent`, using a temp symlink plus `os.replace`. This replaces today's dangling symlink. If the path exists and is not a symlink, it is not replaced; `install` prints `qwen-agentd: warning: not replacing <path>: not a symlink` and continues.
  10. Unless `--no-service`: write and load the service (F90).
  11. Print to stdout `installed <tag of D/current> at <D>` and, unless `--no-service`, `service: <plist or unit path>`. If `fleet_env_path()` does not exist, also print `next: run <D>/current/qwen-agent-workspace/bin/qwen-agentd join (or init-fleet); the service retries every 10 s`. Exit 0.

  `install` is the only command that creates `D`. It may be run from the dev checkout (as on the Mac) or from a temporary clone (as on .168, R3); either way, the installed daemon runs from `D`.

### 9.10 Protocol compatibility and trust

- Peers on releases with a different `PROTOCOL` are incompatible and are never called (F62). A release that bumps `PROTOCOL` makes the fleet route only among already-updated hosts until every host has updated (at most one update period, K6).
- The registry is read once at daemon startup. A registry change reaches a host only as part of a release, through the restart in F87.
- Release tags are not signature-verified. The GitHub account, with its 2FA, is the trust root (Section 14, A1).
- A release tag must never be moved or deleted after it is pushed: `git fetch --tags` refuses to clobber an existing local tag, so a moved tag makes every later fetch on that host fail (Section 14, L7).

---

## 10. Daemon CLI, startup, errors, logs

### 10.1 Subcommands

> **Superseded in part by multi-agent hosts** (M23, M30, M15, M16): F92's flags and defaults and F94's port and agent resolution.

- **F92.** `bin/qwen-agentd [SUBCOMMAND] [FLAGS]`, parsed with `argparse` subparsers. If `argv` is empty or `argv[0]` starts with `-`, `"run"` is inserted as the subcommand, so `run` is the default. **[spec choice]**

  | Subcommand | Usage | Spec |
  |---|---|---|
  | `run` | `qwen-agentd [run] [--registry PATH] [--beacon-targets LIST] [--beacon-port N] [--qwen-agent-bin PATH] [--timing-scale X]` | F95-F99 |
  | `init-fleet` | `qwen-agentd init-fleet` | F23 |
  | `join` | `qwen-agentd join [STRING]` | F26 |
  | `install` | `qwen-agentd install --host-id ID [--origin URL] [--no-service]` | F91 |
  | `selftest` | `qwen-agentd selftest` | F93 |
  | `status` | `qwen-agentd status [--port N]` | F94 |

  `run` flags. Any invalid value exits 2 with the message shown:

  | Flag | Default | Meaning / validation |
  |---|---|---|
  | `--registry PATH` | `REPO_ROOT/fleets/<fleet_id>.json` | registry file (F5) |
  | `--beacon-targets LIST` | `255.255.255.255:8190` | comma-separated `IPv4:port` items, each IPv4 parsed by `ipaddress.IPv4Address` and each port an `int` in 1..65535; the single word `none` means no targets. Invalid: `qwen-agentd: invalid --beacon-targets` |
  | `--beacon-port N` | `8190` | UDP receive port (F31); `int` 1..65535 |
  | `--qwen-agent-bin PATH` | `REPO_ROOT/bin/qwen-agent` | test hook (F50); must be an existing file: `qwen-agentd: --qwen-agent-bin not found: <PATH>` |
  | `--timing-scale X` | `1.0` | test hook; `float` with `0 < X <= 1`; multiplies every constant marked "scaled" in Section 1.3. Invalid: `qwen-agentd: invalid --timing-scale` |

  There is no port flag for HTTP: the listener port is the registry's `port` for this host (F41).
- **F93.** `selftest` runs `[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", os.path.join(REPO_ROOT, "tests", "test_fleet_lib.py")]` with `cwd=REPO_ROOT` and `env` = `os.environ` minus every `FLEET_ENV_PREFIX` key, and exits with pytest's exit code. It is the gate's test step (F86) and is runnable by hand. **[spec choice: only the unit suite D6, which is fast, uses no network beyond in-process loopback, and needs no model server.]**
- **F94.** `status [--port N]` (default 8190). It reads `GET http://127.0.0.1:<N>/peers` (timeout `VIEW_TIMEOUT`) and `D/update-state.json`, and prints to stdout, one item per line **[spec choice]**:

  ```
  daemon: http://127.0.0.1:<N> (version <v>, host_id <id>, discovery <beacon|poll>)
  skills: <skill>=<verified|unverified>[+busy], ...        (or: skills: none)
  peer <host_id> <address>:<port> version <v> via <heard_via> age <age>s[ INCOMPATIBLE] skills <skill>=<verified|unverified>[+busy], ...
  ...                                                     (or: peers: none)
  update: status=<status> from=<from or -> to=<to or -> attempts=<n> bad_tags=<comma list or ->
  ```

  If the daemon is unreachable or returns an invalid view, the first line is `daemon: not reachable at http://127.0.0.1:<N>`, the skills and peer lines are omitted, and the exit code is 1. If `D/update-state.json` does not exist, the update line is `update: not installed`. Otherwise the exit code is 0.

### 10.2 `run` startup and lifecycle

> **Superseded in part by multi-agent hosts** (M31): F95's step order.

- **F95.** `run` startup, in order. Any failure in steps 3-9 is a startup error (F100).
  1. `t0 = time.monotonic()`.
  2. Parse and validate the flags (F92).
  3. Set up logging (F107-F108).
  4. `fleet_id, token = load_fleet_env(fleet_env_path())`; `key = token_key(token)`; the local `token` is deleted (`del token`).
  5. `registry = load_registry(args.registry or <default>, fleet_id)`.
  6. `host_id = os.environ.get("QWEN_AGENT_HOST_ID", "")`; `self_entry(registry, host_id)` (F9, F10).
  7. `version = release_version(REPO_ROOT, deploy_root())`.
  8. Create and bind the TCP listener `("0.0.0.0", self_entry["port"])` (F41), then the UDP beacon socket `("0.0.0.0", beacon_port)` (F31). Both sockets are created here and handed to their threads.
  9. Run the synchronous model probe (F16).
  10. Start the threads of Section 1.2: `beacon-send`, `beacon-recv`, `poll`, `prober` (its next probe one `REPROBE_INTERVAL` later), `housekeeping`, `http`, then `updater` when `version != "dev"`, then `confirm` when F88's condition holds.
  11. Log INFO `qwen-agentd <version> started host_id=<id> port=<p> beacon_port=<bp> beacon_targets=<count> skills=<skill>:<verified|unverified>,...`.
  12. Wait on the stop event (Section 1.2), shut down the listener, and exit 0.
- **F96.** Bind errors. An `OSError` with `errno.EADDRINUSE` on the TCP bind gives `qwen-agentd: TCP port <p> is already in use (is another qwen-agentd running?)`. On the UDP bind it gives `qwen-agentd: UDP port <bp> is already in use`. Any other bind `OSError` gives `qwen-agentd: cannot bind <TCP|UDP> 0.0.0.0:<port>: <ExcType>: <msg>`. All of these exit 2 (F100).
- **F97.** Thread guard. Each iteration of every periodic thread (`beacon-send`, `beacon-recv`, `poll`, `prober`, `housekeeping`, `updater`, `confirm`) runs inside `try/except Exception`, which logs ERROR `<thread name> error: <ExcType>: <msg>` and continues with the next iteration. Bind-attempt threads (F32) abandon silently. No thread exception ever ends the daemon.
- **F98.** Exit codes of `run`: 0 after SIGTERM or SIGINT; 1 from F88's deadline (`os._exit(1)`), or from an unexpected exception that escapes `main` (F99); 2 for every startup error (F100).
- **F99.** Exit codes of the other subcommands: `init-fleet` and `join` 0 or 2 (F23, F26); `install` 0 or 2 (F91); `selftest` pytest's code (F93); `status` 0 or 1 (F94). In every subcommand, an unexpected exception is caught at the top of `main`, which prints `qwen-agentd: internal error: <ExcType>: <msg>` to stderr (and logs it at ERROR under `run`) and exits 1. No traceback is ever printed. **[spec choice]**

### 10.3 Startup errors

> **Superseded in part by multi-agent hosts** (M31): F100's unset-ID and missing-`fleet.env` messages; neither is logged.

- **F100.** Each of these makes `run` print the message to stderr, log it at ERROR when logging is already set up (step 3 onward), and exit 2:

  | Condition (F95 step) | Message |
  |---|---|
  | `fleet.env` missing (4) | `qwen-agentd: <path> not found; run qwen-agentd init-fleet or qwen-agentd join` |
  | `FleetEnvError` (4) | `qwen-agentd: <FleetEnvError message>` (F21) |
  | registry unreadable or invalid (5) | `qwen-agentd: <RegistryError message>` (F8: the path and every schema error) |
  | `QWEN_AGENT_HOST_ID` unset or empty (6) | `qwen-agentd: QWEN_AGENT_HOST_ID is not set; valid IDs: <sorted registry host IDs joined by ', '>` |
  | `QWEN_AGENT_HOST_ID` not in the registry (6) | `qwen-agentd: <F9 message>` |
  | TCP or UDP port in use, or another bind error (8) | F96 |
  | invalid `run` flag (2) | F92 |
- **F101.** No startup message contains the token, the key, or the join string. `FleetEnvError` and `RegistryError` messages are built only from paths and registry content (F21, F8, F28).
- **F102.** A supervisor restarts a daemon that exited 2 every 10 s (F90). While `status` is `ok` or `rolled_back`, those restarts are not counted (F89). While `pending`, they are, so a release whose registry is invalid for this host rolls back after 3 starts.
- **F103.** A second `run` for the same user on the same host fails with F96's "TCP port in use" and exits 2. Under a supervisor this repeats every 10 s and is harmless. A daemon started by hand next to a running service therefore exits immediately.

### 10.4 Runtime degradation

- **F104.** Local model server down or model absent:
  - the daemon keeps running, beaconing, polling, and answering `/health`;
  - `/skills` and `/peers` `self.skills` report every skill `verified: false`;
  - `/run` answers 400 `skill not served` (F49);
  - the prober re-probes every `REPROBE_INTERVAL` (60 s) and logs only on change (F17).

  When the model returns, its skills are offered again from the next probe.
- **F105.** Broadcast blocked (a `sendto` raises, or beacons never arrive). The daemon logs F30's transition WARNING, keeps polling every `POLL_INTERVAL` (F36), and reports `discovery: "poll"` in `/health` and `/peers` (F39). Peers stay usable through polling. Nothing else changes.
- **F106.** A peer failing mid-run (it times out, dies, answers 409, or sends a bad signature) yields the next candidate, or one of F69's `ERROR:` strings once candidates run out. Neither `bin/qwen-agent` nor the daemon raises to its caller on any peer failure (F66, F68, F69).

### 10.5 Logs

> **Superseded in part by multi-agent hosts** (M5): F107's directory is `~/agents/<host_id>/logs` on every platform.

- **F107.** `log_dir()` returns `~/Library/Logs/qwen-agentd` when `sys.platform == "darwin"`, else `~/.local/state/qwen-agentd` (both via `os.path.expanduser`). `run` creates it with `os.makedirs(..., exist_ok=True)` and then `os.chmod(dir, 0o700)`. Files in it **[spec choice]**:
  - `qwen-agentd.log`, the daemon log;
  - `last-run.stderr` (F50);
  - `gate-<tag>.log` (F86);
  - on macOS, `launchd.out` and `launchd.err` (F90).
- **F108.** The daemon log uses `logging.handlers.RotatingFileHandler(<log_dir>/qwen-agentd.log, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS)`, i.e. 5 MB times 3 backups. The file is `chmod 0o600` after the handler opens it. The level is INFO and the format is `%(asctime)s %(levelname)s %(threadName)s %(message)s`. Only `run` logs to it; the other subcommands write to stdout and stderr only. **[spec choice]**
- **F109.** Log hygiene. No log line, in any file, contains:
  - the token, the key, or the join string (F28);
  - a task text or an answer (F53, F67).

  Exceptions are formatted only as `type(e).__name__` and `str(e)` (F28). `last-run.stderr` holds the child's own stderr, which is the harness's normal stderr output and is local to the host. Test T46 verifies hygiene; T18 verifies beacons separately.

---

## 11. Tests

> **Superseded in part by multi-agent hosts** (Section 5): the 11.2 helpers `make_fleet`, `daemon_log_dir`, `read_log` and `start_daemon` change, and T25, T29a, T61 and the CLI tests are migrated.

### 11.1 Rules for every new test [spec choice]

- pytest (`python3 -m pytest`, 3.13 with pytest 8.3.4 on the Mac). Run from `WS`.
- **Loopback only.** Every address a test binds or contacts is `127.0.0.1`, except T47's Linux-only `127.0.0.2` source address. No broadcast is sent: every daemon a test starts gets an explicit `--beacon-targets` list of `127.0.0.1:<port>` items, or `none`.
- **No real user state.** Every spawned daemon, `install`, and `bin/qwen-agent` process gets `HOME=<tmp dir>`, so `fleet.env`, `D`, the log directory, `~/.local/bin` and the harness workspace all live under the test's temp directory. Every spawned process also gets `QWEN_AGENT_SEARXNG_URL=http://127.0.0.1:<closed port>`, so no test depends on a running SearXNG.
- **Configurable ports and timing.** Ports come from `fleet_testutil.free_port()`. Integration tests run daemons with `--timing-scale 0.1` and self-update tests with `--timing-scale 0.01`. Time-based assertions use those scaled bounds.
- **Isolation.** Each integration and self-update test starts its own daemons and stubs, and kills them (whole process groups, SIGKILL) at teardown. No state is shared between tests.
- **Test fleet secret.** Tests create `fleet.env` with `write_fleet_env` and fixed test values. Tests that look for leaks search for those values.
- **Code under test is found relative to the test file.** Each new test file sets `WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))`, runs `sys.path.insert(0, WS)` before `import fleet_lib`, and spawns `WS/bin/...`. A release's selftest (F93) therefore always tests that release's own code, never another checkout's.

### 11.2 Shared helpers (`tests/fleet_testutil.py`, D10)

| Helper | Behavior |
|---|---|
| `free_port()` | binds TCP `127.0.0.1:0`, reads the port, checks that UDP `127.0.0.1:<port>` also binds, closes both, and returns the port; it retries up to 20 times |
| `make_fleet(home, fleet_id, token)` | `write_fleet_env(<home>/.config/qwen-agent/fleet.env, ...)` |
| `write_registry(path, fleet_id, hosts)` | writes a registry (F6) with every host at `127.0.0.1` and an explicit `port` |
| `StubModelServer(kind, model, answer, delegate_skill=None)` | a `ThreadingHTTPServer` on `127.0.0.1:<free port>`, `kind` in `("vllm", "ollama")`. `GET /v1/models` returns `{"object": "list", "data": [{"id": model, "object": "model"}]}` for both kinds (the harness preflight reads it). For `ollama`, `GET /api/tags` returns `{"models": [{"name": model, "model": model}]}`. `POST /v1/chat/completions` appends the parsed body to `.requests`. If `delegate_skill` is set and no message has role `tool`, it answers with one `delegate_to_skill` tool call (`{"skill": delegate_skill, "task": "stub task"}`). Otherwise it answers `{"role": "assistant", "content": answer}`, plus `" | " + <last tool message content>` when one exists. Responses use the OpenAI chat-completions shape, with `finish_reason` `"tool_calls"` or `"stop"` and a `usage` object. `.stop()` shuts it down. |
| `start_daemon(home, host_id, registry, beacon_port, beacon_targets, extra_args=())` | spawns `[sys.executable, WS/bin/qwen-agentd, "run", "--registry", registry, "--beacon-port", str(beacon_port), "--beacon-targets", beacon_targets, "--timing-scale", <scale>] + extra_args` in a new session, with `HOME=home`, `QWEN_AGENT_HOST_ID=host_id`, and `QWEN_AGENT_SEARXNG_URL` (11.1). It returns once `GET /peers` on the host's port answers 200, or fails the test after 10 s |
| `peers(port)`, `delegate(port, skill, task, host_id)` | loopback `GET /peers`, `POST /delegate` |
| `signed(key, method, port, path, body=b"")` | sends a request signed with `fleet_lib.sign_request` and returns `(status, headers, body, request_nonce)` |
| `write_hook(path, kind)` | writes an executable Python script for `--qwen-agent-bin`. `"slow"` reads the task from its `--user-prompt=` argument: for the task `garbage` it prints `not json` and exits 1; for any other task it waits until the file `<hook dir>/release-<task>` exists, then prints the `"canned"` envelope line. `"envdump"` writes `{"argv": sys.argv, "env": dict(os.environ)}` as JSON to `<path>.json`, then `os.execv`s the real `WS/bin/qwen-agent` with the same arguments. `"canned"` prints exactly `{"schema": "qwen-agent.oneshot.v1", "status": "ok", "answer": "CANNED", "error": null, "rounds": 1, "tool_calls": []}` and exits 0 |
| `wait_until(predicate, timeout, interval=0.1)` | polls; returns the elapsed seconds or fails the test |

Hook scripts are written into the test's temp directory at run time. No hook file is added to the repo.

### 11.3 Unit tests (`tests/test_fleet_lib.py`, D6; also the gate's selftest, F93)

| ID | Covers | Pass condition |
|---|---|---|
| T1 | F6, F7, F18 | The F18 registry (with a test fleet_id) validates to `[]`; so does the same registry with explicit ports. |
| T2 | F7 | One fixture per rule 1-12 yields at least one error, each prefixed with its location. A registry with 3 independent violations yields exactly 3 errors. |
| T3 | F8 | `load_registry` fills `port=8190` where absent and returns a deep copy. An unreadable file, bad JSON, and an invalid registry each raise `RegistryError` with F8's message format. |
| T4 | F9 | `self_entry` returns the entry; an unknown ID raises a message listing the sorted IDs. |
| T5 | F19-F21 | `write_fleet_env` creates the dir `0o700` and the file `0o600`; a second write raises `FileExistsError`; `load_fleet_env` round-trips; mode `0o644` gives the chmod message; each malformed variant gives `<path> is malformed`. |
| T6 | F24, F25 | Join string round-trip. A changed checksum, prefix, part count, fleet_id or token raises `FleetEnvError("invalid join string")`, and `str(e)` contains no 6-character substring of the input. |
| T7 | F13 | `probe_url` for `vllm` and `ollama` gives the two example URLs. |
| T8 | F14 | Canned Ollama `/api/tags` JSON (`{"models": [{"name": "qwen3.5:9b", "model": "qwen3.5:9b", "size": 1, "details": {}}]}`) gives `{"qwen3.5:9b"}`. Canned vLLM `/v1/models` JSON (`{"object": "list", "data": [{"id": "qwen38-6bit", "object": "model", "max_model_len": 16384}]}`) gives `{"qwen38-6bit"}`. Non-JSON, wrong shapes, and non-`str` names give `set()`. |
| T9 | F15 | `verify_skills` order and `verified` flags for a present and an absent model. |
| T10 | F29h | `sign_request` / `verify_request` give `"ok"`. Changing the method, path, ts, nonce, body, or signature gives `"bad"`; a missing or non-hex header gives `"bad"`. |
| T11 | F29i | `sign_response` / `verify_response` give `"ok"`. A different `request_nonce`, status code, method, path, or body gives `"bad"`. |
| T12 | F54a, K5 | `build_child_env` drops `QWEN_AGENT_FLEET_ID`, `QWEN_AGENT_FLEET_TOKEN`, `QWEN_AGENT_FLEET_EXTRA`, `SKILL_ENDPOINT_RESEARCHER` and `SKILL_MODEL_RESEARCHER`; keeps `PATH`, `HOME`, `QWEN_AGENT_HOST_ID` and `QWEN_AGENT_SEARXNG_URL` unchanged; sets `QWEN_AGENT_DAEMON_URL`; does not mutate its input. No value in the result contains the test token. |
| T13 | F29f, F29g | `verify_beacon` statuses: `ok`; `malformed` for bad JSON, a missing or extra key, a wrong type, and a `proto` mismatch; `bad_sig` for a tampered field. |
| T14 | F29d, F29g, F29h, F29i | Replays: the second identical beacon, request, or response gives `"replay"`. |
| T15 | F29g, F29h, F29i | Skew: `ts = now - 60` and `now + 60` give `ok`; `now - 61` and `now + 61` give `skew`, for beacons, requests and responses. |
| T16 | F29a, F29g | A beacon made with another key gives `("foreign", None)`, which is checked before the signature. |
| T17 | F29d | `NonceCache` with an injected clock: a nonce is rejected inside `retention` and accepted again after it; `prune()` empties expired entries. |
| T18 | F29f, F28, K5 | `make_beacon` output contains neither the token hex, the key bytes, nor the key hex, and is under 2048 bytes. |
| T19 | F35 | `LivenessTable` with an injected clock: live at exactly `live_window` after `last_heard`, not live 0.001 s later. `transitions()` reports each change exactly once. `unheard_registered()` excludes self. |
| T20 | F34, F35 | `live_peers()` order is `last_heard` descending, then `host_id`; each dict has exactly the ten F55 keys. `heard()` matches by address. A rebind at a new address moves the record. `due_for_refresh` and `heard_beacon_within` behave as specified. |
| T21 | F57-F59, F62 | `route_candidates`: local verified gives `[LOCAL]` even when peers serve the skill; local unverified falls through to peers; unverified items and `compatible: false` peers are excluded; view order is kept; no server gives `[]`. |
| T22 | F68 | `failover` with a fake `attempt` whose outcomes are `busy`, `timeout`, `bad_signature`, then `ok` returns `ok` for the 4th host, with `tried` holding the three in order. All failing gives `exhausted`. An `attempt` that raises `ValueError` records `"error"` and continues. `[]` gives `exhausted` with `tried == []`. A `KeyboardInterrupt` propagates. |
| T23 | F60, F61 | `delegate_enum` filters and keeps order. `valid_view` accepts a full F55 body, and rejects a wrong schema, a missing `self`, a non-bool `verified`, and a non-dict. |
| T24 | F42, F63 | `http_route` for all five endpoints and an unknown pair. `is_loopback_client`: `"127.0.0.1"` and `"::1"` give `True`; `"127.0.0.2"`, `"192.168.1.5"` and `"::ffff:127.0.0.1"` give `False`. `daemon_url_from_env`: unset gives the default; valid loopback gives the value; `http://192.168.1.5:8190`, `http://localhost:8190`, `https://127.0.0.1:8190` and port `0` give `(None, <warning>)`. |
| T25 | F28, K5 | Skipped unless `fleet_env_path()` exists and `REPO_ROOT` is in a git worktree. It reads the token through `load_fleet_env` and lists tracked files with `git -C REPO_ROOT ls-files -z`. It reads each file's bytes in Python and asserts that neither the token's ASCII bytes nor the key bytes occur. The token is never put in a subprocess argv and never appears in an assertion message. |
| T26 | F89, K7 | Loads `bin/qwen-agentd-launch` with `importlib.machinery.SourceFileLoader`. `MAX_START_ATTEMPTS == fleet_lib.MAX_START_ATTEMPTS`. `launcher_step`: `ok` and `rolled_back` give `exec` unchanged; `pending` with attempts 0 and 1 gives `exec` with attempts 1 and 2; attempts 2 gives `rollback` with attempts 3, `status: rolled_back`, and `to` appended to `bad_tags` once; `from_available=False` at attempts 2 gives `exec`. |
| T27 | F81, F85a | `tag_key` ordering of `v2026.10.17`, `.1`, `.2`, `.10`, `v2026.10.18`; `None` for `v2026.10.17.0`, `2026.10.17`, `v2026.1.17`, `vX`. `select_candidate`: picks the highest newer descendant; skips a higher non-descendant; skips `bad_tags`; ignores older, equal and invalid tags; `None` for a `dev` current. |
| T28 | F84, F85 | `run_update_cycle` with a fake `ctx` returns each of the 8 outcomes. The lock is released on `stage_failed`, `gate_failed` and `error`. `gate_failed` appends to `bad_tags` and unstages. `switched` wrote `pending` / attempts 0 / `from` / `to` **before** `swap`, and called `restart` after it. A raising `swap` restores the previous state. |
| T29 | F82, F83, F88a | `read_state` defaults for missing, corrupt, and wrong-typed files; `write_state` mode `0o600`, atomic (no `.tmp` left behind); the launcher's `read_state` reads `fleet_lib.write_state` output identically, and the reverse. `releases_to_prune` keeps current, from, and the 3 newest, and ignores non-tag names. `release_version` gives the tag for `D/releases/<tag>/qwen-agent-workspace` (with symlinks in the path) and `dev` otherwise. |

### 11.4 Harness tests (`tests/test_qwen_agent_fleet.py`, D7)

They load `bin/qwen-agent` with `importlib.machinery.SourceFileLoader`, like `tests/test_qwen_agent_context_budget.py:23-30`. Fake daemons are in-process `ThreadingHTTPServer`s on loopback.

| ID | Covers | Pass condition |
|---|---|---|
| T30 | F71-F74 | `SKILL_TOOL_NAMES["researcher"] == ("search", "fetch_url", "read_file", "calculate")`; the two `DELEGATE_TARGETS` tuples equal F72's; `SKILL_THINK_TEMP_DEFAULTS["researcher"] == {"think": False, "temperature": 0.7}`; `SKILL_SYSTEM_PROMPTS["researcher"]` equals the value loaded from `agent/qwen-agent-unsafe`. |
| T31 | F54, F71 | For all four skills, every name in `SKILL_TOOL_NAMES` is in `AUTO_APPROVE_TOOLS`, and none of `bash`, `write_file`, `run_python`, `generate_image`, `promote` appears. `build_tools_for_context("researcher")` names are exactly the four tools, with no `delegate_to_skill`. |
| T32 | F73, F75 | `parse_args(["--skill=researcher", "--user-prompt=x"])` is accepted. `main()`, run with `oneshot` monkeypatched to capture `args_ns` and `_load_fleet_lib` returning `None`, sets `think False` and `temperature 0.7`. `--model-server-type=bogus` exits 2; the default is `"vllm"`. |
| T33 | F76 | `chat_completion` request bodies, with `urlopen` faked: `ollama` + think off has `reasoning_effort == "none"`; `ollama` + think on has no such key; `vllm` + either has no such key, and its key set equals today's (`model, messages, tools, tool_choice, chat_template_kwargs, max_tokens, temperature, top_p, stream`); an `args_ns` without the attribute has no such key. |
| T34 | F77 | Loading the module with `QWEN_AGENT_SEARXNG_URL=" http://10.0.0.5:8888/ "` gives `SEARXNG_BASE_URL == "http://10.0.0.5:8888"`; unset, `""` and whitespace give `"http://127.0.0.1:8888"`. |
| T35 | F69, F70, F78, K8 | (a) A copy of `bin/qwen-agent` alone in `<tmp>/bin/`: `_load_fleet_lib()` is `None`, and `main()`'s `TOOLS` equals `build_tools_for_context(skill)` for `None` and `investigator`. (b) With `fleet_lib` present and `QWEN_AGENT_DAEMON_URL` pointing at a closed loopback port: `fetch_view` gives `(None, None)`; `exec_delegate_to_skill` calls `subprocess.Popen` (monkeypatched to record and return a fake process) with an argv equal, element for element, to today's (`:1243-1257`). (c) `_envelope_to_result` gives today's exact strings for `ok` with an answer, `ok` without one, and a non-`ok` status with and without a partial answer. |
| T36 | F64, F69 | With a fake daemon: local-first (self verified) goes to the `Popen` path and makes no `/delegate` call. Remote: `/delegate` receives exactly `{"skill", "task", "host_id"}`. Failover follows the view order (`busy`, then `ok`). No candidates gives exactly `ERROR: no live host serves 'researcher'`. All failed gives `ERROR: no live host serves 'researcher' (tried: a: busy; b: timeout)`. An `ok` envelope with status `max_rounds` gives the same string as the local mapping. A `KeyboardInterrupt` raised in the fake `delegate_once` gives F69's interrupted string. |
| T37 | F60, F78(a), F78(b) | Startup enum with a fake daemon: the top level lists only the served targets, in `DELEGATE_TARGETS` order; investigator gets the analyst/researcher subset; an empty result leaves no `delegate_to_skill` in `TOOLS`. The REPL fleet line is printed only when `--user-prompt` is absent. |
| T38 | F63, F64 | A non-loopback `QWEN_AGENT_DAEMON_URL` prints the F63 warning, makes no network call (the fake server records zero requests), and keeps today's enum. A fake daemon answering an invalid view, or 403, prints the F64 warning, and routing falls back to the local path. |
| T39 | F78(f) | The local-path argv contains `--model-server-type=ollama` exactly when the parent's `args_ns.model_server_type == "ollama"`, placed before any `--api-key`; with `vllm` it does not. |

### 11.5 Integration tests (`tests/test_fleet_integration.py`, D8)

The standard fixture: three daemons `alpha`, `bravo`, `charlie` on `127.0.0.1` with distinct HTTP ports and beacon ports, one shared test fleet, and one registry listing all of them. Each daemon's `--beacon-targets` lists the other two daemons' `127.0.0.1:<beacon_port>`. `alpha` has skills `[]` and a `vllm` stub; `bravo` has `["researcher"]` and an `ollama` stub; `charlie` has `["analyst"]` and a `vllm` stub. Tests that vary this setup say so. "Ready" means `start_daemon` has returned for every daemon.

| ID | Covers | Procedure and pass condition |
|---|---|---|
| T40 | K1 (beacon), F30-F32, F39 | Standard fixture. Within 4.5 s of ready (45 s scaled), every daemon's `/peers` lists the other two, and every `self.discovery == "beacon"`. |
| T41 | K1 (poll), F36, F39 | Standard fixture with `--beacon-targets none` everywhere. Within 7.5 s of ready (75 s scaled), every `/peers` lists the other two with `heard_via == "poll"`, and `discovery == "poll"`. |
| T42 | K2, F35, F38 | After T40's condition holds, SIGKILL `charlie`. Within 9 s (90 s scaled), `charlie` is absent from `alpha`'s and `bravo`'s `/peers`. Within a further 1 s (housekeeping), `alpha`'s log has a `peer charlie down` line. |
| T43 | K3, F50, F52, F65-F69, F76 | Standard fixture; `alpha`'s stub has `delegate_skill="researcher"`; `bravo`'s stub answers `BRAVO-ANSWER`. Once `bravo` is live in `alpha`'s view, run the **real** `WS/bin/qwen-agent --user-prompt=go --base-url=<alpha stub>/v1 --model=<alpha model>` with `QWEN_AGENT_DAEMON_URL=<alpha loopback_url>`, `HOME=<tmp>`, and no `SKILL_*` variables. It exits 0 with envelope `status == "ok"`, and an answer containing `BRAVO-ANSWER`. `bravo`'s stub received at least one request with `reasoning_effort == "none"` and `alpha`'s none. `bravo`'s log has `run start` and `run end ... http=200 status=ok` lines, and `alpha`'s log has a `delegate skill=researcher host=bravo ... outcome=ok` line. |
| T44 | F65-F68, F29j | Standard fixture plus a registered in-process fake peer `delta` (skills `["researcher"]`). It signs `/health` and `/skills` with the fleet key, and is bound into `alpha` by the test sending `alpha` a valid beacon carrying `delta`'s port. `delta`'s `/run` mode `busy` answers a signed 409; mode `badsig` answers 200 signed with a different key. Pass: `delegate(alpha, "researcher", "t", "delta")` gives `busy` and then `bad_signature`, one per mode. `failover(["delta", "bravo"], <delegate_once against alpha>)` gives `ok` from `bravo`, with `tried == [("delta", "busy")]`, then `[("delta", "bad_signature")]`. `delegate(alpha, "researcher", "t", "charlie")` gives `not_live` (charlie does not serve researcher). |
| T45 | K4, F29a, F11 | Standard fixture plus a foreign daemon `echo`: its own `HOME`, a different fleet_id and token, and its own registry listing `echo` plus an `alpha` entry at `alpha`'s address and port, so it polls `alpha`. Its beacon targets include `alpha`'s beacon port. Note `alpha`'s log size, run `echo` for 10 s (3 beacon intervals plus one poll, scaled), then stop it. Pass: `alpha`'s log gained **zero** lines; `alpha`'s and `bravo`'s `/peers` never listed `echo`'s port; `echo`'s `/peers` has `peers == []`. |
| T46 | K5, F28, F54a, F109 | T43's round trip, but `bravo` runs with `--qwen-agent-bin=<envdump hook>`, and the test also binds a sniffer UDP socket whose port is in `alpha`'s and `bravo`'s `--beacon-targets`. Pass: the dumped `env` has no key starting with `QWEN_AGENT_FLEET_` and no value containing the test token, and `QWEN_AGENT_DAEMON_URL == <bravo loopback_url>`. The dumped `argv[1:]` equals F50's list. No sniffed datagram, no file under any daemon's log directory (including `last-run.stderr`), and no `/peers` or `/delegate` response body contains the token hex, the key bytes, or the join string. |
| T47 | F41, F42, F44 | `alpha` only. A loopback request to `GET /health` without a signature gets 401 (signed endpoints need a signature even from loopback); with one it gets 200. `GET /nowhere` signed gets a signed 404; unsigned gets 401. On Linux: a client socket bound to source `127.0.0.2` gets 403 with an empty body for `GET /peers` and `POST /delegate`, and `alpha`'s log gains no line. On macOS, where `127.0.0.2` cannot be bound by default, that part is skipped and T24 covers the rule. |
| T48 | F47-F53 | `bravo` with `--qwen-agent-bin=<slow hook>`. Signed `/run` checks: a malformed body gives 400; an unserved skill gives 400 `skill not served: analyst`; a missing `Content-Length` gives 411; a body of `MAX_BODY + 1` gives 413; an unsigned request gives 401; a replayed request gives 401. While one slow run is in flight, a second gives a signed 409 `busy`, and `/skills` shows `busy: true`. After the release file is written, the first returns 200 whose body is byte-identical to the hook's canned line. The task `garbage` gives a signed 502 `skill produced no parseable output (exit code 1)`. The 504 timeout path (900 s, unscaled) and F54c's spawn failure are covered by review and by T22's outcome mapping, not by this test. |
| T49 | F16, F17, F104 | `bravo` whose stub port is closed at start. `/health` is 200; `/skills` reports `researcher` `verified: false`; `alpha` still lists `bravo` as live. After the stub starts on that port, within `REPROBE_INTERVAL` scaled plus 2 s, `/skills` reports `verified: true` and `bravo`'s log has `skill 'researcher' offered`. |

### 11.6 Self-update tests (`tests/test_fleet_self_update.py`, D9)

Fixture: a local bare repo `<tmp>/origin.git`, built by the test. Each commit holds `qwen-agent-workspace/` with copies of the current `fleet_lib.py`, `bin/qwen-agent`, `bin/qwen-agentd`, `bin/qwen-agentd-launch`, `tests/test_fleet_lib.py`, `tests/fleet_testutil.py`, and `fleets/<test fleet_id>.json` (one host `h1` at `127.0.0.1:<free port>`, model server at a closed port, skills `[]`). Releases are made with `git tag` plus `git push`. `install` runs as `[sys.executable, WS/bin/qwen-agentd, "install", "--host-id", "h1", "--origin", <tmp>/origin.git, "--no-service"]` with `HOME=<tmp>/home`. A **test supervisor** emulates launchd/systemd: a loop that runs `[sys.executable, D/qwen-agentd-launch, "--beacon-targets", "none", "--timing-scale", "0.01"]` and, whenever it exits, starts it again after 0.2 s.

| ID | Covers | Procedure and pass condition |
|---|---|---|
| T60 | K6, K7, F84-F89 | Tag `v2026.01.01` (good); `install`; `make_fleet`; start the supervisor. Then: (1) tag `v2026.01.02` (good, a child of v1, with a changed doc file). Within 60 s, `/health` reports version `v2026.01.02` and the state is `ok`, `from v2026.01.01`, `to v2026.01.02`. (2) Tag `v2026.01.03`, a child of v2 whose `tests/test_fleet_lib.py` has an appended `def test_gate_must_fail(): assert False`. Within 60 s, `v2026.01.03` is in `bad_tags`, version is still `v2026.01.02`, and `D/releases/v2026.01.03` does not exist. (3) Tag `v2026.01.04`, a child of **v2** whose registry file is `{}` (it passes the gate and crashes on start). Within 90 s: `status == "rolled_back"`, `to == "v2026.01.04"`, `bad_tags` holds both `v2026.01.03` and `v2026.01.04`, `D/current` points at `releases/v2026.01.02`, and `/health` reports `v2026.01.02`. The daemon PID is unchanged across step (1)'s switch (exec, not respawn). |
| T61 | F80, F83, F91 | `install` with no tags exits 2 with the no-tags message. After tagging: the layout matches F80 (modes `D 0o700`, launcher `0o755`, state `0o600`); `~/.local/bin/qwen-agent` resolves into `D/releases/<tag>/qwen-agent-workspace/bin/qwen-agent`; the state is the initial one; no service file exists. A second `install` exits 0 and changes neither `current` nor the state. |
| T62 | F85 step 3 | After install and start, modify a tracked file in `D/current/qwen-agent-workspace/`, then tag a good newer release. Over 3 update periods: no switch, and at least one `not updating` WARNING. After `git -C D/current checkout -- .`, the switch happens within 2 periods plus 10 s. |
| T63 | F48, F85 step 4 | The origin's registry gives h1 skills `["planner"]` and a model server at a `StubModelServer("vllm", ...)` the test starts first. The supervisor's launcher args add `--qwen-agent-bin <slow hook>`, which the launcher and the restart pass through (F87, F89). Hold a signed `/run` in flight, then tag a good newer release. Over 3 periods: no switch, and a `deferred: a run is in flight` INFO line. After releasing the run, the switch happens within 2 periods plus 10 s. |

### 11.7 Regression

| ID | Covers | Pass condition |
|---|---|---|
| T70 | K8 | Before any change, record the pass/fail result of every test in `WS/tests/` (`python3 -m pytest tests/ -q -rA` from `WS`, plus `python3 tests/test_qwen_agent_context_budget.py`). After the change, every test that passed before still passes, and every new test passes. |
| T71 | F1, [SKILLS] 1.2 | `/usr/bin/python3 -m py_compile` (3.9.6) and `python3 -m py_compile` (3.13.0) both succeed on `fleet_lib.py`, `bin/qwen-agent`, `bin/qwen-agentd` and `bin/qwen-agentd-launch`. |
| T72 | Section 0.3, F79 | `git diff --quiet <base commit> -- agent/qwen-agent-unsafe qwen-agent-workspace/tests/test_researcher_think_off.py qwen-agent-workspace/scripts/deploy` exits 0 (run from the repo root), and `tests/test_researcher_think_off.py` passes. |

---

## 12. Rollout

> **Multi-agent hosts:** R1-R10 below use that spec's layout (M2-M6, M23-M30): agent `mac-local` on this Mac and `ollama-168` on .168, both on port 8190.

Steps R0-R3 set the fleet up; R4-R10 are the live acceptance checks. Run them in order.

- **R0. Prerequisites, on both hosts.** On each host, run `scripts/fleet-host-prep.sh` until it exits 0. Its behavior is specified in `docs/superpowers/specs/2026-10-17-fleet-host-prep-design.md`. It checks, in this order: platform; packages (`python3` >= 3.9, `git`, pytest); clock (NTP, F40); that the model server serves this host's model (through `fleet_lib.probe_url` and `fleet_lib.parse_loaded_models`, F13, F14); that SearXNG answers at `http://127.0.0.1:8888/`; that the host firewall admits TCP and UDP 8190 from 192.168.1.0/24; and, on Linux, user lingering (F90). Without `--apply` it changes nothing. With `--apply` it asks for the sudo password once, fixes what it can, and prints every command it runs as a `+ <command>` line. It never touches `fleet.env` or any fleet secret. It never installs Docker or Ollama, and never starts a model server. It stops before R1. The script must be committed and pushed on `qwen-agent-redteam` before the .168 steps below, because .168 clones that branch.
  - **mac-local:** `bash ~/local_agent_harness/qwen-agent-workspace/scripts/fleet-host-prep.sh --model-server-type vllm --model qwen38-6bit`. If any line is `FAIL` or `UNKNOWN`, run the same command again with `--apply` added. The firewall check allows the binary that `python3` on `PATH` actually runs, so R3a's `install` must be run with that same `python3`.
  - **A host that serves only no-tools skills** (for example `vision-185`, which serves only `vision`) needs no SearXNG, so it adds `--no-searxng` to its command. `--port N` (default 8190) changes the firewall port being checked.
  - **ollama-168, over an interactive ssh session** (sudo needs a terminal to ask for the password). The repo is not on .168 yet. If `git` is missing, first run `sudo apt-get install -y git` (or `sudo dnf install -y git`). Then:
    1. `git clone --depth 1 --branch qwen-agent-redteam https://github.com/reubenpatterson1/local_agent_harness.git /tmp/qa-prep`
    2. `bash /tmp/qa-prep/qwen-agent-workspace/scripts/fleet-host-prep.sh --model-server-type ollama --model qwen3.5:9b --apply`
    3. `rm -rf /tmp/qa-prep`. This is safe because the script copies SearXNG's `docker-compose.yml` and `settings.yml` to `~/.local/share/qwen-agent/searxng/` and runs compose from there.
  - **Fallback if .168 cannot run Docker:** after R3, give the .168 service `QWEN_AGENT_SEARXNG_URL=<a reachable instance>` with `systemctl --user edit qwen-agentd-ollama-168` (a drop-in containing `[Service]` and `Environment=QWEN_AGENT_SEARXNG_URL=...`), then `systemctl --user restart qwen-agentd-ollama-168`. The Mac's instance listens only on `127.0.0.1:8888` (`searxng/docker-compose.yml:31`), so .168 cannot use it. Re-run the script with `--searxng-url <that URL>` to check it.
- **R1. Create the fleet, on mac-local, from the dev checkout.** Run `python3 ~/local_agent_harness/qwen-agent-workspace/bin/qwen-agentd init-fleet --agent-id mac-local`. It writes `~/agents/mac-local/fleet.env` (mode 0600, in a new `~/agents/mac-local/` of mode 0700). Note the `fleet_id`. Leave the join string in that terminal only; it is never saved (F23).
- **R2. Registry and first release.** Create `qwen-agent-workspace/fleets/<fleet_id>.json` with exactly F18's content. Run the full test suite (T70-T72). Commit, push the branch, then `git tag v<YYYY.MM.DD>` and `git push origin v<YYYY.MM.DD>`, using the release date.
- **R3. Install and join.**
  - **R3a, mac-local:** `python3 ~/local_agent_harness/qwen-agent-workspace/bin/qwen-agentd install --agent-id mac-local --default`. `fleet.env` already exists from R1, so the daemon starts. This creates `~/agents/mac-local/`, the LaunchAgent `com.qwen-agent.qwen-agentd.mac-local` (`~/Library/LaunchAgents/com.qwen-agent.qwen-agentd.mac-local.plist`), and the wrapper `~/.local/bin/qwen-agent-mac-local`. `--default` is required on this Mac: `~/.local/bin/qwen-agent` is already a (dangling) symlink to `/Users/reubenpatterson/qwen-agent-workspace/bin/qwen-agent`, and install replaces it with mac-local's wrapper, as F91's install also replaced a symlink there. The dev checkout is not touched: `~/local_agent_harness/qwen-agent-workspace/bin/qwen-agent` still works, and talks to the daemon on 8190.
  - **R3b, ollama-168, over ssh:**
    1. `git clone --branch v<YYYY.MM.DD> --depth 1 https://github.com/reubenpatterson1/local_agent_harness.git /tmp/qa-bootstrap`
    2. `python3 /tmp/qa-bootstrap/qwen-agent-workspace/bin/qwen-agentd install --agent-id ollama-168 --default`
    3. `python3 ~/agents/ollama-168/current/qwen-agent-workspace/bin/qwen-agentd join --agent-id ollama-168`, then paste the join string at the hidden prompt. Copy it by hand from the R1 terminal into this ssh session.
    4. `rm -rf /tmp/qa-bootstrap`. The service `qwen-agentd-ollama-168.service` picks up `~/agents/ollama-168/fleet.env` on its next 10 s restart.
  - **R3c, mac-local:** delete `~/.zshenv` lines 11-12 (`export SKILL_ENDPOINT_RESEARCHER=...`, `export SKILL_MODEL_RESEARCHER=...`) and the comment on line 10 that introduces them. Open a new shell; `env | grep '^SKILL_'` prints nothing. **[spec choice: line 10 goes too, since it only introduces lines 11-12.]**
  - **R3d, both hosts:** `QWEN_AGENT_HOST_ID` is in each service's environment because `install --agent-id` wrote it (F90, multi-agent M6). Check with `launchctl print gui/$(id -u)/com.qwen-agent.qwen-agentd.mac-local | grep QWEN_AGENT_HOST_ID` on the Mac and `systemctl --user show qwen-agentd-ollama-168 -p Environment` on .168. On each host, `grep -x '# agent-id: <id>' ~/.local/bin/qwen-agent` matches, `grep QWEN_AGENT_DAEMON_URL= ~/.local/bin/qwen-agent-<id>` shows `http://127.0.0.1:8190`, and `realpath ~/agents/<id>/current/qwen-agent-workspace/bin/qwen-agent` resolves into `~/agents/<id>/releases/<tag>/qwen-agent-workspace/bin/qwen-agent`. If a service does not start, its startup error is in `~/agents/mac-local/logs/launchd.err` (Mac) or `journalctl --user -u qwen-agentd-ollama-168` (.168).
- **R4. K1, beacon mode.** Within 45 s after the later of the two daemons started, `qwen-agentd status --agent-id <id>` on each host lists the other, `via beacon`, and `discovery beacon`. (Here and below, `qwen-agentd` on a host means `~/agents/<id>/current/qwen-agent-workspace/bin/qwen-agentd`, where `<id>` is `mac-local` on the Mac and `ollama-168` on .168.) If the Mac reports `discovery poll`, broadcast is being blocked (for example by Netskope); record that, and the fleet runs in poll mode (F105).
- **R5. K1, poll mode.** On the Mac: stop the service (`launchctl bootout gui/$(id -u)/com.qwen-agent.qwen-agentd.mac-local`), then run `QWEN_AGENT_HOST_ID=mac-local python3 ~/agents/mac-local/current/qwen-agent-workspace/bin/qwen-agentd run --beacon-targets none` in a terminal. Within 75 s, `qwen-agentd status --agent-id ollama-168` on .168 lists `mac-local ... via poll`. Stop the foreground daemon with Ctrl-C, then restore the service with `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.qwen-agent.qwen-agentd.mac-local.plist`.
- **R6. K2.** On .168: `systemctl --user stop qwen-agentd-ollama-168`. Within 90 s, `qwen-agentd status --agent-id mac-local` on the Mac no longer lists `ollama-168`, and `~/agents/mac-local/logs/qwen-agentd.log` has `peer ollama-168 down`. Then `systemctl --user start qwen-agentd-ollama-168`.
- **R7. K3.** In the new shell from R3c (no `SKILL_*` set), run `qwen-agent` (the `~/.local/bin/qwen-agent` wrapper, which runs mac-local's release). The REPL prints `[fleet: qwen-agentd at http://127.0.0.1:8190; ...; delegate targets: investigator, analyst, planner, researcher]`. Ask a question and tell the model to use `delegate_to_skill` with `skill="researcher"`. The UI shows `[delegating to researcher on ollama-168, ...]`, and the tool result is a non-empty answer. `~/agents/ollama-168/logs/qwen-agentd.log` on .168 has a `run end skill=researcher ... http=200 status=ok` line.
- **R8. K8.** Stop the Mac service (`launchctl bootout gui/$(id -u)/com.qwen-agent.qwen-agentd.mac-local`). `qwen-agent --user-prompt "..."` works exactly as before the fleet: there is no fleet line, the enum is unfiltered, and delegation is local. Restore the service (`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.qwen-agent.qwen-agentd.mac-local.plist`).
- **R9. K5.** On each host, with the token supplied by file descriptor (so it never appears in an argv): `grep -rlF --exclude=fleet.env -f <(sed -n 's/^QWEN_AGENT_FLEET_TOKEN=//p' ~/agents/<id>/fleet.env) ~/agents ~/.local/bin ~/local_agent_harness` prints nothing (`~/local_agent_harness` exists only on the Mac; `--exclude=fleet.env` skips every agent's own secret file, and the logs are under `~/agents/<id>/logs`). `ps eww <daemon pid>`, and the same for a running `/run` child during R7, show no `QWEN_AGENT_FLEET_` variable. `sudo tcpdump -A -c 3 -i any udp port 8190` on .168 shows only the beacon fields `fleet_tag`, `nonce`, `port`, `proto`, `sig`, `ts`.
- **R10. K6.** Commit a no-op change (a doc edit), tag `v<YYYY.MM.DD>.1`, and push the tag. Within 30 min, `qwen-agentd status --agent-id <id>` on both hosts shows that version, with `update: status=ok`.

K4 and K7 have no live step; tests T45, T26 and T60 cover them.

| KPI | Live step | Pass |
|---|---|---|
| K1 | R4, R5 | both hosts listed within 45 s (beacon) and within 75 s (poll) |
| K2 | R6 | stopped host gone within 90 s |
| K3 | R7 | researcher answer from ollama-168 with no `SKILL_*` set |
| K5 | R9 | no token in files, process environments, or beacons |
| K6 | R10 | both hosts on the new tag within 30 min |
| K8 | R8 | the harness behaves as before with no daemon |

---

## 13. Values chosen by the spec

Every **[spec choice]** in this document, one line each. Values in the Section 1.3 constants block are spec choices as a group; the ones with behavioral weight are listed individually.

1. Section 1.2: the thread set, the periods, and first-run timing of each thread.
2. Section 1.3: every `fleet_lib` name and every constant value (intervals 30/60/90/60/60/5/900/120 s, timeouts 5/5/900/930/300/120/2/960 s, `MAX_BODY` 1 MiB, `KEEP_RELEASES` 3, `FLEET_TAG_CHARS` 16).
3. Section 1.3: `launcher_step` and the launcher's state I/O live in the self-contained `bin/qwen-agentd-launch`, not in `fleet_lib`.
4. F5: the registry lives at `WS/fleets/<fleet_id>.json`.
5. F6: the optional per-host `port`, defaulting to 8190.
6. F24: join string format `qaf1.<fleet_id>.<token>.<8-hex sha256 check>`.
7. F26: `join` without an argument reads the string with `getpass`.
8. F27: `token_key(token) = bytes.fromhex(token)`.
9. F30: default beacon target `255.255.255.255:8190`.
10. F43: unknown paths are treated like signed endpoints (unsigned 401, or signed 404 after verification).
11. F44: all fleet HTTP clients use `http.client`, never `urllib`, to bypass proxies.
12. F50: child stderr goes to `<log_dir>/last-run.stderr`, overwritten on every run.
13. F55: the fleet view schema `qwen-agentd.peers.v1`, its ten-key peer record, and `age` rounded to 0.1 s.
14. F57: the `busy` flag neither filters nor reorders candidates.
15. F58: when this host is verified for a skill, the skill runs locally only, with no peer fallback.
16. F59: `LOCAL = "@local"` as the local marker.
17. F63: `QWEN_AGENT_DAEMON_URL`, accepted only as `http://127.0.0.1:<port>`, default `http://127.0.0.1:8190`.
18. F64: the view is fetched at startup (for the enum) and again at every delegation (for routing), with a 2 s timeout; an absent daemon is silent.
19. F65-F68: client-driven failover. `bin/qwen-agent` names one `host_id` per `/delegate`; the outcome vocabulary and the `/delegate` response shape.
20. F66: `request_id = secrets.token_hex(8)`.
21. F69: the UI lines `[delegating to <skill> on <host>, ...]` and `[<skill> on <host> failed: <outcome>]`, the `(tried: ...)` suffix, and the interrupted-remote-run message.
22. F70: `fleet_lib` is loaded by file path and not inserted into `sys.modules`; a load failure prints one warning.
23. F75: the flag name `--model-server-type`, its choices `vllm`/`ollama`, and the default `vllm`.
24. F77: `QWEN_AGENT_SEARXNG_URL` is stripped and loses trailing slashes; empty means unset.
25. F78(a): an empty filtered enum omits the `delegate_to_skill` tool.
26. F78(b): the one-line REPL fleet banner on stderr.
27. F78(f): `--model-server-type` is forwarded to local children only when it is not `vllm`.
28. F80: `D/repo` is a bare clone; `D/current` has a relative target and is swapped through `D/.current.tmp`.
29. F83: an unreadable or invalid state file reads as the default state.
30. F85: the cycle order fetch, select, dirty check, lock, stage, gate, switch, and holding the run lock from the lock step through the restart.
31. F85: staging failures do not mark a tag bad.
32. F85a: the candidate is the highest tag satisfying all conditions, with ancestry checked lazily from the top.
33. F86: gate output goes to `<log_dir>/gate-<tag>.log`; the gate strips `QWEN_AGENT_FLEET_*` variables from its environment.
34. F88: the self-check polls every 1 s, and a deadline miss exits 1 for rollback.
35. F88a: pruning keeps current, `from`, and the 3 newest releases.
36. F89: the counting rule (the exec start is attempt 0, and the third launcher start rolls back) and swap-before-write ordering.
37. F90: the launchd label, plist keys and PATH; the systemd unit name and text; `StartLimitIntervalSec=0`; a 10 s restart delay on both.
38. F91: the `install` flags `--host-id` (required), `--origin` and `--no-service`; idempotent re-install; the pytest pre-check; gating the first release; the `~/.local/bin/qwen-agent` target through `D/current`.
39. F92: `run` as the default subcommand, and the `run` flag set with its defaults.
40. F93: `selftest` runs only `tests/test_fleet_lib.py`, with `-p no:cacheprovider`.
41. F94: the `status` output format, `--port`, and exit codes.
42. F99: unexpected exceptions print one line and exit 1; no tracebacks.
43. F107-F108: the log file name, format and INFO level, the directory and file modes, and the macOS launchd stdout and stderr files.
44. Section 11: the test ID blocks (T1-T29 unit, T30-T39 harness, T40-T49 integration, T60-T63 self-update, T70-T72 regression), the timing scales 0.1 and 0.01, and the stub and hook behaviors.
45. R3c: the orphaned `~/.zshenv` comment on line 10 is removed together with lines 11-12.

---

## 14. Accepted risks and known limitations

> **Multi-agent hosts:** in L7 and L8, read `~/agents/<id>/repo` and `install --agent-id <id>` (M2, M25).

No design question is open. The items below were accepted with the design, or follow from it.

**Accepted risks**

- **A1. No signed-tag verification.** Anyone who can push a matching tag to `reubenpatterson1/local_agent_harness` can run code on every host within one update period. The GitHub account, with its 2FA, is the trust root. The gate (F86) catches broken releases, not malicious ones.
- **A2. One shared token for the whole fleet.** A compromise of any host's `fleet.env` gives the attacker full fleet membership: they can be bound as a peer, receive tasks, and return forged but validly signed answers. Recovery is a new fleet (remove `fleet.env` everywhere, `init-fleet`, `join`, a new registry file, a new release). There is no rotation tooling (Section 0.4).
- **A3. Visible on the LAN.** Any LAN observer can see a daemon beaconing on UDP 8190 and listening on TCP 8190 (bound to 0.0.0.0, F41). Beacons are opaque: no host_id, skills or version (F29f). Requests without a valid signature get a bare 401 or 403.
- **A4. NTP is required.** A clock more than 60 s off makes a host's beacons and requests fail as `skew` (one WARNING per peer IP, F33). That host drops out of the fleet until its clock is fixed (F40, R0).
- **A5. Loopback endpoints trust every local process.** `/peers` and `/delegate` are unauthenticated (F29), so any process on the host, including another OS user's, can read the fleet view and send tasks through the daemon. Both hosts are single-user.

**Known limitations**

- **L1. The orchestrator is a stub.** `orchestrator` (192.168.1.170) is a registry entry with `PLACEHOLDER-70B` and no daemon; it never becomes live. Standing it up (hardware, model server, a real registry entry, `install`) is future work outside this spec.
- **L2. One run per host, with no queue and no remote cancel.** A busy host answers 409 and the caller fails over (F48, F68). Ctrl-C on the caller does not stop a remote run (F69). `run_lock` serializes only `/run`. A human REPL session on mac-local can still overlap an incoming `/run` against the same vllm-metal server, which crashes on concurrent requests (Section 0.2). Today no host sends `/run` to mac-local (ollama-168's researcher never delegates, and the orchestrator is not up), so this is latent.
- **L3. The tool enum is fixed per process.** It is computed at startup (F78(b)). A skill that comes online later is not offered until the next `qwen-agent` start. A skill that goes offline returns F69's `ERROR:` string.
- **L4. Poll-only mode depends on registry addresses.** With beacons blocked, a peer is found only at its registry `address` (F36). If its DHCP address changes, it stays unreachable until beacons resume or a release updates the registry. In beacon mode, address changes are harmless (F34, F41).
- **L5. Prompts and descriptions name only the original roles.** `_build_delegate_tool`'s description (Section 0.4) and the investigator's system prompt (F74, ported unchanged) mention only investigator, analyst and planner. The model learns of `researcher` only from the enum.
- **L6. Broadcast may be blocked on the Mac.** Netskope or the macOS firewall may drop UDP broadcast. The fleet then runs in poll mode (F105), with K1's 75 s bound instead of 45 s (R4).
- **L7. Release tags are immutable by convention.** Moving or deleting a pushed release tag breaks `git fetch --tags` on every installed host (F85 step 1 then logs `fetch_failed` every cycle). Recovery is deleting that host's local tag: `git -C ~/.local/share/qwen-agent/repo tag -d <tag>`.
- **L8. Updating the launcher needs a manual re-install.** `D/qwen-agentd-launch` is copied only by `install` (F91 step 9). A release that changes `bin/qwen-agentd-launch` takes effect on a host only after `qwen-agentd install --host-id <id>` is re-run there.
- **L9. Two `/run` failure paths have no automated test.** The 504 timeout (900 s, not scaled) and F54c's spawn failure are checked by review only (T48).
