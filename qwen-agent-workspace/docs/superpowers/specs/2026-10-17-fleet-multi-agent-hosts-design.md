# qwen-agent fleet -- Design Spec (multi-agent hosts)

Date: 2026-10-17
Status: The user approved every design decision in the 2026-10-17 multi-agent brief: the terminology (an agent is one daemon plus one registry entry, and `host_id` stays the internal name), the per-agent layout under `~/agents/<id>/`, the per-agent service names, the registry `port`, the generated wrapper commands, the beacon port and target defaults, the agent-resolution rule, `join --from-agent`, the test plan, and the KPIs. This document writes those decisions down precisely enough to implement without reopening them. Every value the brief left open is marked **[spec choice]** with a one-line reason, and Section 8 collects them. No design decision is left open.

Repository: `/Users/reubenpatterson/local_agent_harness`, branch `qwen-agent-redteam`, HEAD `2182f41` when this was written. Workspace root `WS` = `qwen-agent-workspace/`. All relative paths are relative to `WS`.

Parent spec: `docs/superpowers/specs/2026-10-16-fleet-discovery-self-update-design.md`, called **[FLEET]** below. Its requirement IDs are `F<n>`, its tests `T<n>`, its rollout steps `R<n>`. This spec revises [FLEET] only where Section 7 says so; everything else in [FLEET] still holds.

Companion spec: `docs/superpowers/specs/2026-10-17-fleet-host-prep-design.md`, called **[PREP]** below (IDs `P<n>`, tests `H<n>`). Its `--port` flag exists for this feature (M20).

ID conventions: `M<n>` is a requirement of this spec, `MT<n>` a test, `MK<n>` a success criterion, `MR<n>` a live check. They do not clash with `F`, `T`, `K`, `R`, `P` or `H`.

Terms:

- **Agent**: one `qwen-agentd run` daemon plus the one registry entry it serves (model server, model, skills, port). A machine may run several agents.
- **Agent ID** / **host ID**: the registry key that names one agent (`mac-local`). Code, protocol, registry and environment keep the name `host_id` (`QWEN_AGENT_HOST_ID`, the `/health` field, `hosts.<id>`). The CLI spells it `--agent-id`, with `--host-id` as an exact alias (M23).
- **Machine**: a computer with one IPv4 address. [FLEET]'s "host" meant "machine running exactly one agent"; in this spec "host" is not used for a machine.
- **Agent root** `A(<id>)`: `~/agents/<id>/`, the per-agent replacement of [FLEET]'s deploy root `D` (M2). Wherever [FLEET] says `D`, read `A(<this agent's id>)`.

---

## 0. Purpose and scope

### 0.1 Purpose

[FLEET] assumes one daemon per machine: one fixed deploy root (`fleet_lib.DEPLOY_ROOT = "~/.local/share/qwen-agent"`, `fleet_lib.py:67`), one `fleet.env` (`fleet_env_path()`, `fleet_lib.py:237-239`), one log directory (`log_dir()`, `fleet_lib.py:841-845`), one service label (`LAUNCHD_LABEL`, `SYSTEMD_UNIT`, `fleet_lib.py:69-70`), one `~/.local/bin/qwen-agent` symlink (`bin/qwen-agentd:1201-1211`), and UDP 8190 for every daemon (`bin/qwen-agentd:1326-1327`). A second agent on the same machine would collide on every one of these.

This spec makes the agent ID determine every per-agent path, service name and port, so that one machine can run several agents (for example, later, `vision-185` on port 8190 and `gemma-185` on port 8191 on .185). The first rollout still has one agent per machine: `mac-local` on this Mac and `ollama-168` on .168, both on port 8190.

### 0.2 Grounding (shipped code, read on 2026-10-17)

Nothing from [FLEET] has been deployed anywhere, so no migration is needed. `~/agents`, `~/.local/share/qwen-agent` and `~/.config/qwen-agent` do not exist on this Mac (checked). `~/.local/bin/qwen-agent` is a dangling symlink to `/Users/reubenpatterson/qwen-agent-workspace/bin/qwen-agent` (checked), and `~/.local/bin/qwen-agent.pre-symlink-backup-20260823-185849` is an unrelated regular file.

`fleet_lib.py` (986 lines):

- Constants `DEFAULT_PORT = 8190` (`:27`), `DEFAULT_DAEMON_URL = "http://127.0.0.1:8190"` (`:62`), `DAEMON_URL_RE` (`:63`), `DEPLOY_ROOT` (`:67`), `WS_SUBDIR` (`:68`), `LAUNCHD_LABEL = "com.qwen-agent.qwen-agentd"` (`:69`), `SYSTEMD_UNIT = "qwen-agentd.service"` (`:70`).
- `_HOST_KEYS` (`:97`); `_validate_hosts` (`:131-177`) iterates `sorted(hosts)` (`:136`), checks `port` in 1..65535 (`:160-163`), and already rejects a duplicate `(address, port)` pair (`:170-176`) with `hosts.<later id>: address <a>:<p> is already used by hosts.<earlier id>`. That is [FLEET] F7 rule 12, tested by T2 (`tests/test_fleet_lib.py:117`).
- `load_registry` fills `port` (`:209-222`); `self_entry` (`:225-230`).
- `fleet_env_path()` (`:237-239`); `write_fleet_env` (`:242-251`) creates the parent `0o700` and the file with `O_EXCL`, `0o600`, but writes in place (not atomic).
- `LivenessTable.bind` drops another host's record at the same `(address, port)` (`:560-577`); `heard(address, port, via)` matches records by address and port (`:579-592`).
- `daemon_url_from_env` (`:748-757`); `deploy_root()` (`:836-838`); `log_dir()` (`:841-845`, the only use of `sys` in the module); `release_version(repo_root, deploy_root)` (`:918-926`).

`bin/qwen-agentd` (1361 lines):

- `cmd_init_fleet` (`:69-83`), `cmd_join` (`:86-106`), `cmd_selftest` (`:109-112`).
- `setup_logging()` uses `fleet_lib.log_dir()` (`:133-144`).
- `_parse_port` (`:162-167`), `_parse_beacon_targets` (`:170-185`), `_validate_run_flags` (`:188-204`).
- `_loopback_request_ok` (`:293-305`) requires `Host` to be `127.0.0.1:<own port>`, `localhost:<own port>` or `[::1]:<own port>`, where the port is `self.server.fleet.port`, the daemon's registry port.
- `Daemon.start` (`:393-428`) loads `fleet.env` first, then the registry, then reads `QWEN_AGENT_HOST_ID` (`:409`), then `release_version(REPO_ROOT, fleet_lib.deploy_root())` (`:419`). `_bind_sockets` (`:430-445`) binds TCP `self.port` then UDP `self.beacon_port`, without `SO_REUSEADDR` on UDP.
- `_start_threads` reads the update state from `deploy_root()` (`:482`).
- `send_beacons` (`:657-676`) puts `self.port` (the HTTP port) in every beacon. `beacon_recv_loop` (`:678-694`) calls `self.table.heard(source[0], beacon["port"], "beacon")` and, when that returns `None`, `schedule_bind(source[0], beacon["port"])` (`:691-692`). `poll_once` (`:709-715`) binds at the registry `address` and `port`.
- `spawn_run` writes `last-run.stderr` under `fleet_lib.log_dir()` (`:751`).
- `_confirm_switch` uses `deploy_root()` (`:876`). `cmd_run` (`:893-911`) validates flags, then calls `setup_logging()` before `daemon.start()`.
- `cmd_status` (`:924-953`) defaults to port 8190 and reads `deploy_root()/update-state.json` (`:944`).
- `gate_release` writes `gate-<tag>.log` under `fleet_lib.log_dir()` (`:1034`).
- `launchd_plist_dict(py, d, host_id, logs)` (`:1075-1080`), `systemd_unit_text(py, d, host_id)` (`:1083-1095`), `install_service(py, d, host_id)` (`:1117-1139`, uses the fixed label and unit, and `fleet_lib.log_dir()` at `:1121`).
- `cmd_install` (`:1142-1225`): `--host-id` validation (`:1145-1147`), D and log dir creation (`:1166-1168`), the `~/.local/bin/qwen-agent` symlink with the not-a-symlink warning (`:1201-1211`), the `next:` line (`:1222-1224`).
- `restart_daemon(d)` (`:1232-1250`); `UpdateCtx.__init__` sets `self.d = fleet_lib.deploy_root()` (`:1258`).
- `_build_parser` (`:1313-1339`): `run --beacon-targets` default `255.255.255.255:8190` (`:1326`), `--beacon-port` default `"8190"` (`:1327`), `status --port` `type=int` default 8190 (`:1332`), `install --host-id` required (`:1335`).

`bin/qwen-agentd-launch` (115 lines): `main` derives `d = os.path.dirname(os.path.realpath(__file__))` (`:92-93`), so it needs no change to work from `A(<id>)/qwen-agentd-launch`. Only its docstring (`:4`) names the old path.

`bin/qwen-agent`: it never names the deploy root, `fleet.env` or a log path. It reaches its daemon only through `fleet_lib.daemon_url_from_env(os.environ)` (`:3808`), which defaults to `DEFAULT_DAEMON_URL`. It needs no change.

Tests: `tests/fleet_testutil.py` gives each daemon its own `HOME` (`Fleet.__init__`), writes `fleet.env` at `<home>/.config/qwen-agent/fleet.env` (`make_fleet`), and computes the log directory per platform (`daemon_log_dir`). `start_daemon` always passes `--beacon-port` and `--beacon-targets` explicitly.

### 0.3 Deliverables

| # | File | Change |
|---|---|---|
| E1 | `fleet_lib.py` | per-agent path, label, wrapper, resolution and beacon-default functions; registry port range; atomic `write_fleet_env` (Section 4.1) |
| E2 | `bin/qwen-agentd` | CLI flags, startup order, per-agent internals, install, status, join (Section 4.2) |
| E3 | `bin/qwen-agentd-launch` | docstring only (M34) |
| E4 | `tests/fleet_testutil.py` | helper signatures (Section 5.2) |
| E5 | `tests/test_fleet_lib.py` | new unit tests MT1-MT7; migrated T25, T29a |
| E6 | `tests/test_fleet_integration.py` | new MT10-MT13; migrated tests (Section 5.6) |
| E7 | `tests/test_fleet_self_update.py` | new MT20-MT24; migrated tests (Section 5.6) |
| E8 | [FLEET] | Section 12 R1-R10 rewritten; one supersession note per changed section (already done with this spec) |

`bin/qwen-agent`, `agent/qwen-agent-unsafe`, `scripts/`, [PREP] and every other file are not changed.

### 0.4 Out of scope

- An `uninstall` subcommand (M35 documents manual removal instead).
- Migrating old paths (nothing was deployed).
- Sharing one bare clone or one release tree between agents on a machine.
- Choosing which model server an agent uses (that is registry content).
- The vision feature and the `.185` agents' registry entries; MR1 is written against them but runs only after that feature ships.
- Changing `bin/qwen-agent`'s default daemon URL (it stays `http://127.0.0.1:8190`).

### 0.5 Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| MK1 | `python3 -m pytest tests/ -q -rA` from `WS` gives the [FLEET] T70 baseline (1027 passed; 1 failed, exactly `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike`; 1 skipped, T25) plus every new MT test passing and no other change in outcome | MT40 |
| MK2 | `/usr/bin/python3 -m py_compile` (3.9.6) and `python3 -m py_compile` (3.13) succeed on `fleet_lib.py`, `bin/qwen-agent`, `bin/qwen-agentd`, `bin/qwen-agentd-launch` | MT41 |
| MK3 | Two agents installed into one `HOME` get two agent roots, two service definitions and two wrappers, and never touch each other's files | MT20, MT23 |
| MK4 | Two agents on one address, started with no beacon flags, each bind their own registry port and discover each other within the poll bound (75 s, scaled 7.5 s) | MT10 |
| MK5 | The fleet token never appears in any command output, log line, wrapper file, beacon or child environment | MT13, MT20, T46 (migrated), R9 (live) |
| MK6 | [FLEET] R1-R10 pass live with the layout of this spec | R1-R10 (live) |

### 0.6 Must-have vs nice-to-have

Every requirement M1-M37 is a must-have. MR1 (two agents on .185) is an optional live check, run only after the vision feature.

---

## 1. Layout and identity

One rule: **the agent ID determines the paths, the service names and the port.**

- **M1. Names.** Internally the name stays `host_id` everywhere: the registry key, `/health`'s `host_id`, `QWEN_AGENT_HOST_ID`, `LivenessTable`, `self_entry`. No protocol field, registry key, or environment variable is renamed. Docs and CLI help say "agent ID". `--agent-id` is an exact alias of `--host-id` (M23).
- **M2. Agent root.** `fleet_lib.AGENTS_DIR = "~/agents"` replaces `DEPLOY_ROOT` (removed). New and changed functions:

  ```python
  def _check_agent_id(host_id):
      if not isinstance(host_id, str) or not HOST_ID_RE.fullmatch(host_id):
          raise ValueError("invalid agent id %r" % (host_id,))

  def deploy_root(host_id):
      """A(<id>) = ~/agents/<id>, this agent's root (multi-agent spec M2)."""
      _check_agent_id(host_id)
      return os.path.join(os.path.expanduser(AGENTS_DIR), host_id)
  ```

  Every function of M2-M8 that takes `host_id` calls `_check_agent_id` first. **[spec choice: a path is never built from an unvalidated ID, so `../x` cannot escape `~/agents`.]** `os.path.expanduser` reads `HOME` at each call, as today.
- **M3. Agent root contents.** Everything that lived under [FLEET]'s `D` lives under `A(<id>)`, plus `fleet.env` and the log directory:

  | Path | What | Created by |
  |---|---|---|
  | `A/` | mode `0o700` | `install` (M25 step 5) or `write_fleet_env` (M4), whichever runs first |
  | `A/repo/` | the bare clone (F80) | `install` |
  | `A/releases/<tag>/` | release worktrees (F80, F86) | `install`, updater |
  | `A/current` | relative symlink `releases/<tag>` (F80) | `install`, updater, launcher |
  | `A/update-state.json` | update state (F83) | `install`, updater, launcher, confirm thread |
  | `A/qwen-agentd-launch` | launcher copy, `0o755` (F80) | `install` |
  | `A/fleet.env` | the fleet secret, `0o600` (M4) | `init-fleet`, `join` |
  | `A/logs/` | the log directory, `0o700` (M5) | `install`, `run` |

  `~/agents` itself is created by `os.makedirs(..., exist_ok=True)` with the process umask and is never `chmod`ed. **[spec choice: it may already exist as a user directory; only per-agent roots hold secrets.]** The run lock is the in-memory `threading.Lock` `Daemon.run_lock` (`bin/qwen-agentd:373`); it has no file, so nothing moves for it. `~/.local/share/qwen-agent/` (except M14's SearXNG directory) and `~/.config/qwen-agent/` are no longer read or written by any fleet code.
- **M4. `fleet.env`.** `fleet_lib.FLEET_ENV_NAME = "fleet.env"`. `fleet_env_path(host_id)` returns `os.path.join(deploy_root(host_id), FLEET_ENV_NAME)`. File content and `load_fleet_env` are unchanged (F19, F21). `write_fleet_env(path, fleet_id, token)` keeps F20's contract (parent `0o700`; `FileExistsError` if `path` exists; file `0o600`) and becomes atomic **[spec choice: one writer serves init-fleet, join and `join --from-agent`, and none can leave a half-written secret]**:
  1. `os.makedirs(dirname, exist_ok=True)`, then `os.chmod(dirname, 0o700)`.
  2. `tmp = path + ".tmp"`. If `os.path.lexists(tmp)`, `os.unlink(tmp)`.
  3. `fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)`; write the two lines; `flush`; `os.fsync`; close.
  4. In `try`: `os.link(tmp, path)`. It raises `FileExistsError` when `path` exists, so an existing file is never replaced. `finally`: `os.unlink(tmp)`.
- **M5. Logs.** `fleet_lib.LOGS_SUBDIR = "logs"`. `log_dir(host_id)` returns `os.path.join(deploy_root(host_id), LOGS_SUBDIR)` on every platform. **[spec choice: the brief puts logs under the agent root; one rule on both platforms.]** The files are those of F107 (`qwen-agentd.log`, `last-run.stderr`, `gate-<tag>.log`, and on macOS `launchd.out`, `launchd.err`), each in its agent's `logs/`. `import sys` is removed from `fleet_lib.py`, since `log_dir` was its only user.
- **M6. Services.** `LAUNCHD_LABEL = "com.qwen-agent.qwen-agentd"` stays, as the base. `SYSTEMD_UNIT` is removed and replaced by `SYSTEMD_UNIT_FMT = "qwen-agentd-%s.service"`.

  ```python
  def launchd_label(host_id):       # com.qwen-agent.qwen-agentd.<id>
      _check_agent_id(host_id)
      return LAUNCHD_LABEL + "." + host_id

  def systemd_unit(host_id):        # qwen-agentd-<id>.service
      _check_agent_id(host_id)
      return SYSTEMD_UNIT_FMT % host_id
  ```

  - macOS: plist `~/Library/LaunchAgents/<launchd_label(id)>.plist`. `launchd_plist_dict(py, d, host_id, logs)` keeps its signature and F90's dict, except `"Label": fleet_lib.launchd_label(host_id)`. `install_service` passes `d = deploy_root(id)` and `logs = log_dir(id)`, and runs `launchctl bootout gui/<uid>/<launchd_label(id)>` (exit ignored), then `launchctl bootstrap gui/<uid> <plist path>`.
  - Linux: unit `~/.config/systemd/user/<systemd_unit(id)>`. `systemd_unit_text(py, d, host_id)` is unchanged; `d = deploy_root(id)`. The three commands are `systemctl --user daemon-reload`, `systemctl --user enable <systemd_unit(id)>`, `systemctl --user restart <systemd_unit(id)>`.
  - Both set `QWEN_AGENT_HOST_ID=<id>` exactly as F90 does; the daemon derives `A(<id>)` from it (M31).
- **M7. Port.** Each agent's port is its registry entry's `port` (optional; default `DEFAULT_PORT` 8190). F7 rule 8 becomes: `port`, if present, is an `int` (not a `bool`) in `1024..65535`. `fleet_lib.MIN_PORT = 1024`. The error text becomes `hosts.<id>.port: must be an integer in 1024..65535` (`fleet_lib.py:162-163`). **[spec choice: matches [PREP] `--port`'s range, so every registry port can be opened by the prep script.]** The same port serves TCP (HTTP, F41) and, by default, UDP (beacons, M15).
- **M8. Command paths.** `fleet_lib.BIN_DIR = "~/.local/bin"` and `fleet_lib.COMMAND_NAME = "qwen-agent"`.
  - `command_path(host_id)` returns `os.path.join(os.path.expanduser(BIN_DIR), COMMAND_NAME + "-" + host_id)`, i.e. `~/.local/bin/qwen-agent-<id>`.
  - `default_command_path()` returns `os.path.join(os.path.expanduser(BIN_DIR), COMMAND_NAME)`, i.e. `~/.local/bin/qwen-agent`.
- **M9. Wrapper bytes.** Both commands are generated POSIX `sh` scripts (a symlink cannot set an environment variable). Constants: `WRAPPER_MARKER = "# qwen-agentd wrapper"`, `WRAPPER_ID_PREFIX = "# agent-id: "`.

  ```python
  def _sh_single_quote(s):
      return "'" + s.replace("'", "'\\''") + "'"

  def wrapper_bytes(host_id, port):
      """The exact wrapper file for one agent (multi-agent spec M9)."""
      _check_agent_id(host_id)
      if not (_is_int(port) and MIN_PORT <= port <= 65535):
          raise ValueError("invalid port %r" % (port,))
      target = os.path.join(deploy_root(host_id), "current", WS_SUBDIR, "bin", "qwen-agent")
      return ("#!/bin/sh\n"
              + WRAPPER_MARKER + "\n"
              + WRAPPER_ID_PREFIX + host_id + "\n"
              + "QWEN_AGENT_DAEMON_URL=http://127.0.0.1:%d\n" % port
              + "export QWEN_AGENT_DAEMON_URL\n"
              + "exec " + _sh_single_quote(target) + ' "$@"\n').encode("utf-8")
  ```

  With `HOME=/Users/reubenpatterson`, `wrapper_bytes("mac-local", 8190)` is exactly:

  ```sh
  #!/bin/sh
  # qwen-agentd wrapper
  # agent-id: mac-local
  QWEN_AGENT_DAEMON_URL=http://127.0.0.1:8190
  export QWEN_AGENT_DAEMON_URL
  exec '/Users/reubenpatterson/agents/mac-local/current/qwen-agent-workspace/bin/qwen-agent' "$@"
  ```

  - **[spec choice: a separate `export` line.]** POSIX leaves unspecified whether an assignment before the special built-in `exec` is exported.
  - **[spec choice: the absolute path, expanded at install time.]** The command runs the agent it was installed for whatever `HOME` the caller has (sudo, a test `HOME`).
  - **[spec choice: always single-quoted, `'` written as `'\''`.]** One quoting form for every path, including paths with spaces.
  - The target goes through `current`, so self-update moves the command with no rewrite (F80). `bin/qwen-agent`'s `REPO_ROOT` resolves through `current` to the release (`os.path.realpath(__file__)`), as F70 requires.
  - The wrapper overrides any `QWEN_AGENT_DAEMON_URL` the caller set. To reach another agent's daemon, run that agent's `qwen-agent-<id>`.
- **M10. Wrapper detection and writing.** `WRAPPER_MAX_BYTES = 65536`.
  - `is_wrapper(data)` returns `WRAPPER_MARKER.encode("ascii") in data.split(b"\n")`, i.e. one whole line equals the marker.
  - `wrapper_agent_id(data)` returns the value after `WRAPPER_ID_PREFIX` on the first line of `data.split(b"\n")` that starts with `WRAPPER_ID_PREFIX.encode("ascii")`, decoded as ASCII, when that value fullmatches `HOST_ID_RE`. Otherwise (no such line, a decode error, or an invalid value) it returns `None`.
  - `classify_command_path(path)` returns `(kind, found_id)`:

    | Condition, first match wins | Result |
    |---|---|
    | `not os.path.lexists(path)` | `("absent", None)` |
    | `os.path.islink(path)` (dangling or not) | `("symlink", None)` |
    | `os.path.isfile(path)`, and reading up to `WRAPPER_MAX_BYTES + 1` bytes succeeds, gives at most `WRAPPER_MAX_BYTES` bytes, and `is_wrapper(data)` | `("wrapper", wrapper_agent_id(data))` |
    | anything else (a non-wrapper file, a larger file, a read `OSError`, a directory) | `("other", None)` |

  - `write_wrapper(path, data)`: `os.makedirs(dirname, exist_ok=True)`; `tmp = path + ".tmp"`; if `os.path.lexists(tmp)`, `os.unlink(tmp)`; `fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o755)`; `os.fchmod(fd, 0o755)` (the umask must not narrow it); write; `flush`; `os.fsync`; close; `os.replace(tmp, path)`. `os.replace` replaces a symlink itself, never its target.
- **M11. Per-agent command rule.** `agent_command_action(kind)` returns `"write"` for `absent`, `symlink` and `wrapper` (any agent ID), and `"refuse"` for `other`. `install` acts on `command_path(id)` per M25 step 9.
- **M12. Default command rule.** The default agent is the one installed with `--default`; otherwise the first one installed, which sets `~/.local/bin/qwen-agent` only when nothing is there. `default_command_action(kind, found_id, host_id, make_default)`, first match wins:

  | `kind` | condition | action |
  |---|---|---|
  | `absent` | | `"write"` |
  | `wrapper` | `found_id == host_id` (refresh this agent's own default) | `"write"` |
  | `symlink` or `wrapper` | `make_default` | `"write"` |
  | `other` | `make_default` | `"refuse"` |
  | any | otherwise | `"keep"` |

  A dangling symlink counts as "something there". Today's `~/.local/bin/qwen-agent` on this Mac is such a symlink, so R3a passes `--default` (see Section 7.2). **[spec choice: `found_id == host_id` refreshes the default's port and path on re-install, with or without `--default`.]**
- **M13. Existing checkouts.** No command writes inside a git checkout: `install` writes only under `A(<id>)`, `~/.local/bin/qwen-agent`, `~/.local/bin/qwen-agent-<id>` (each with its `.tmp`), and the service file (with its `.tmp`). The dev checkout `~/local_agent_harness` on this Mac and the older checkout on .185 are never touched. The dev checkout's `bin/qwen-agent` keeps working, and talks to the daemon on 8190 through `DEFAULT_DAEMON_URL`. A daemon started by hand from a checkout gets `release_version(REPO_ROOT, deploy_root(host_id))` = `"dev"` and runs no updater (F82). So does a daemon started from one agent's release with another agent's `QWEN_AGENT_HOST_ID`, because its `REPO_ROOT` is not under its own `A/releases`. It does not touch the other agent's state.
- **M14. SearXNG stays host-level.** [PREP]'s SearXNG stable directory stays `~/.local/share/qwen-agent/searxng/`. It is one per machine, not per agent, and no fleet code reads it. Do not "fix" it to `~/agents/...`.

---

## 2. Networking

- **M15. Beacon receive port.** `run --beacon-port` defaults to the agent's own registry port, `self_entry["port"]`, instead of 8190. The argparse default becomes `None`. A given value is validated as today (`_parse_port`, 1..65535, `qwen-agentd: invalid --beacon-port`). The default is applied after the registry loads (M31 step 9). The UDP socket still sets `SO_BROADCAST` and never `SO_REUSEADDR` (F31). Two agents on one machine therefore always receive on different UDP ports, because M19 forces different TCP ports at one address.
- **M16. Beacon send targets.** `run --beacon-targets` defaults to `fleet_lib.default_beacon_targets(registry)`:

  ```python
  BROADCAST_ADDR = "255.255.255.255"

  def default_beacon_targets(registry):
      """One broadcast target per distinct registry port, ascending (multi-agent spec M16)."""
      ports = set(h.get("port", DEFAULT_PORT) for h in registry["hosts"].values())
      return [(BROADCAST_ADDR, p) for p in sorted(ports)]
  ```

  It includes every entry, whatever its role, and this agent's own port. **[spec choice: an orchestrator entry may run a daemon later; beacons are tiny, and the agent's own echo is already dropped silently as a replay (F30).]** The argparse default becomes `None`. A given value is parsed as today (`_parse_beacon_targets`; `none` means `[]`). Explicit flags always win, and every existing test keeps passing explicit values. For the first rollout's registry (F18, no ports) the default is `[("255.255.255.255", 8190)]`, the same as [FLEET]'s.
- **M17. Bind matching (unchanged; confirmed in code).** Every beacon carries the sender's HTTP port (`make_beacon(self.key, self.port, ...)`, `bin/qwen-agentd:660`). The receiver matches `(source ip, beacon["port"])`: `table.heard(source[0], beacon["port"], "beacon")`, else `schedule_bind(source[0], beacon["port"])` (`bin/qwen-agentd:691-692`). `LivenessTable.heard` matches records by address **and** port (`fleet_lib.py:579-592`), and `bind` replaces only a record at the same `(address, port)` (`fleet_lib.py:568-570`). So two agents at one address are two separate peers. Agents on one machine hear each other when the OS loops a limited broadcast back to local sockets. If it does not, the poll fallback finds them at the registry `address:port` (F36, `bin/qwen-agentd:709-715`) within the poll bound. No code change.
- **M18. HTTP (unchanged).** Each daemon serves `("0.0.0.0", self_entry["port"])` (F41). The loopback-only `/peers` and `/delegate` keep the `Host` check against the daemon's own port (`bin/qwen-agentd:293-305`). Delegation to an agent on the same machine goes to that peer's current address (its LAN IP from the beacon source or the registry), signed, like any other peer (F66). No code change.
- **M19. Duplicate `(address, port)` (already shipped; kept).** [FLEET] F7 rule 12 already rejects two entries with the same `(address, port)` (`fleet_lib.py:170-176`). The error string and its order stay exactly as shipped. **[spec choice: the shipped string is consistent with the other F7 errors and T2 already pins it.]** Hosts are visited in `sorted()` order, so the alphabetically first ID owns the pair and every later one is reported: `hosts.<later id>: address <address>:<port> is already used by hosts.<first id>`. Example: `vision-185` and `gemma-185` both at `192.168.1.185:8190` give exactly one error, `hosts.vision-185: address 192.168.1.185:8190 is already used by hosts.gemma-185`. The brief's illustrative wording (`hosts.gemma-185.port: 8190 already used by vision-185 at ...`) is not adopted.
- **M20. Firewall.** Each agent needs its own port open for TCP and UDP from the LAN. [PREP]'s `--port N` does this, once per agent on the machine (`--port 8190`, then `--port 8191`). On macOS the application firewall allows by binary, not by port, so agents run by the same `python3` binary share one rule. This settles [PREP] risk R6: an agent receives beacons only on its own port (M15). Sending needs no inbound rule, so a machine whose agents use 8190 and 8191 needs exactly those two ports open.

---

## 3. Commands

### 3.1 Choosing an agent

- **M21. Agent directories.** `agent_ids_on_disk()` returns the sorted names `n` in `os.listdir(os.path.expanduser(AGENTS_DIR))` for which all of these hold:
  - `HOST_ID_RE.fullmatch(n)`;
  - `os.path.isdir(<AGENTS_DIR>/n)`;
  - `os.path.lexists(<AGENTS_DIR>/n/fleet.env)` or `os.path.lexists(<AGENTS_DIR>/n/current)`.

  A missing or unreadable `~/agents` gives `[]`. **[spec choice: `~/agents` is a generic name, so only directories holding a fleet secret or an installed release count.]**
- **M22. `resolve_agent(explicit)`** returns `(host_id, None)` or `(None, message)`:

  | Case | Result |
  |---|---|
  | `explicit` given, fullmatches `HOST_ID_RE` | `(explicit, None)`; the directory need not exist |
  | `explicit` given, invalid | `(None, "qwen-agentd: invalid --agent-id '<explicit>'")` |
  | `explicit is None`, `agent_ids_on_disk()` has exactly one ID | `(that ID, None)` |
  | `explicit is None`, no IDs | `(None, "qwen-agentd: no agent found in <expanded AGENTS_DIR>; pass --agent-id ID")` |
  | `explicit is None`, two or more IDs | `(None, "qwen-agentd: more than one agent in <expanded AGENTS_DIR> (<ids joined by ', '>); pass --agent-id ID")` |

  `init-fleet`, `join` and `status` resolve with it; every `message` goes to stderr and exits 2. `install` never infers (M23).
- **M23. Flags.** In `_build_parser`, the `init-fleet`, `join`, `status` and `install` subparsers each get `p.add_argument("--agent-id", "--host-id", dest="agent_id", default=None, metavar="ID")`, with `required=True` on `install` only. **[spec choice: one flag definition on every subcommand that names an agent, so `--host-id` works everywhere `--agent-id` does.]** `run` and `selftest` get no agent flag. Further flags:
  - `install`: `--default` (`action="store_true"`, `dest="make_default"`, default `False`); `--origin` and `--no-service` as today.
  - `join`: `--from-agent ID` (`dest="from_agent"`, default `None`); positional `STRING` as today.
  - `status`: `--port N` (`type=int`, default `None`).
  - `run`: `--beacon-targets` and `--beacon-port` default `None` (M15, M16).

  argparse's own error for a missing install flag is `qwen-agentd install: error: the following arguments are required: --agent-id/--host-id` (exit 2).
- **M24. `agent_port(fleets_dir, host_id) -> (port or None, files)`.** It scans the sorted names in `os.listdir(fleets_dir)` ending in `.json` (a missing or unreadable directory gives `(None, [])`). A file "lists" `host_id` when all of these hold: it reads as UTF-8; it parses with `json.loads`; it is a dict whose `hosts` is a dict containing `host_id`; and `validate_registry(obj, obj.get("fleet_id")) == []`. Any read or parse error skips the file. `files` = the sorted basenames that list `host_id`; `ports` = the set of `obj["hosts"][host_id].get("port", DEFAULT_PORT)` over them. The result is `(the one port, files)` when `len(ports) == 1`, otherwise `(None, files)`. **[spec choice: it needs no `fleet.env`, because on .168 `install` runs before `join`. It reads exactly the registries a release ships.]**

### 3.2 `install`

- **M25. `qwen-agentd install --agent-id ID [--default] [--origin URL] [--no-service]`.** This is [FLEET] F91 with `D = deploy_root(ID)` and `log_dir(ID)`, and these changes. Every failure prints the message shown to stderr and exits 2.
  1. `ID` must fullmatch `HOST_ID_RE`: `qwen-agentd: invalid --agent-id '<ID>'`.
  2. to 4. As F91: git, pytest, the Linux linger check.
  5. `os.makedirs(D, exist_ok=True)`; `os.chmod(D, 0o700)`; the same for `log_dir(ID)`.
  6. to 8. As F91 (clone or fetch, tags, the first release's stage and gate, swap, state).
  9. In this order:
     a. **Port.** `port, files = agent_port(os.path.join(D, "current", WS_SUBDIR, "fleets"), ID)`. If `port is None` and `files` is non-empty: `qwen-agentd: agent '<ID>' has different ports in <files joined by ', '> of release <tag>` (exit 2). If `files` is empty: write `qwen-agentd: warning: agent '<ID>' is not in any registry of release <tag>; its commands use port 8190` to stderr, and use `DEFAULT_PORT`. **[spec choice: today's install does not check the registry; the daemon reports an unknown ID at start (F9). This keeps that precedent.]** `<tag>` is `os.path.basename(os.path.realpath(D/current))`.
     b. **Launcher.** Copy it as F91 step 9.
     c. **Per-agent command.** `kind, _ = classify_command_path(command_path(ID))`. If `agent_command_action(kind) == "write"`, call `write_wrapper(command_path(ID), wrapper_bytes(ID, port))`. Otherwise write `qwen-agentd: warning: not replacing <path>: not a symlink or a qwen-agentd wrapper` to stderr and continue.
     d. **Default command.** `kind, found = classify_command_path(default_command_path())`; `action = default_command_action(kind, found, ID, args.make_default)`. `"write"`: `write_wrapper(default_command_path(), wrapper_bytes(ID, port))`. `"refuse"`: write the step c warning, with this path, to stderr. `"keep"`: nothing is written.
  10. Unless `--no-service`: `install_service(sys.executable, D, ID)` (M6).
  11. Output (M26). Exit 0.

  `install` stays idempotent: a re-run refreshes the launcher, both commands (subject to M11 and M12), and the service, and never re-clones or changes `current`.
- **M26. `install` stdout**, in this order, each line ending in `\n`:
  1. `installed <tag> at <D>`
  2. only when step 9c wrote: `command: <command_path(ID)> (daemon port <port>)`
  3. only when step 9d wrote: `default: <default_command_path()> runs agent <ID>`. Only when step 9d kept: `default: <default_command_path()> unchanged; pass --default to make it run agent <ID>`. Nothing on stdout when it refused.
  4. unless `--no-service`: `service: <plist or unit path>`
  5. when `fleet_env_path(ID)` does not exist: `next: run <D>/current/qwen-agent-workspace/bin/qwen-agentd join --agent-id <ID> (or init-fleet --agent-id <ID>); the service retries every 10 s`

### 3.3 `init-fleet` and `join`

- **M27. `init-fleet [--agent-id ID]`.** `ID` comes from `resolve_agent(args.agent_id)` (M22). The rest is F23 with `path = fleet_env_path(ID)`: an existing path gives `qwen-agentd: <path> already exists; remove it first to create a new fleet` (exit 2); otherwise it writes the file and prints F23's four lines, unchanged. The join string is shown once and never saved.
- **M28. `join [--agent-id ID] [STRING]`.** First `ID = resolve_agent(args.agent_id)`, before any prompt, so an ambiguous call never asks for the secret. Then F26 with `path = fleet_env_path(ID)`: a `getpass` prompt when `STRING` is omitted; `qwen-agentd: invalid join string`; `qwen-agentd: already joined fleet <fleet_id>` (exit 0); `qwen-agentd: <path> exists for a different fleet; remove it first` (exit 2); `qwen-agentd: joined fleet <fleet_id>` (exit 0).
- **M29. `join [--agent-id Y] --from-agent X`.** It copies agent X's fleet secret to agent Y on the same machine, without printing or prompting for the token. Steps, in order; every failure goes to stderr and exits 2:
  1. `Y = resolve_agent(args.agent_id)` (M22).
  2. `STRING` given as well: `qwen-agentd: join takes STRING or --from-agent, not both`.
  3. `X` must fullmatch `HOST_ID_RE`: `qwen-agentd: invalid --from-agent '<X>'`.
  4. `X == Y`: `qwen-agentd: --from-agent names agent '<Y>' itself`.
  5. `fleet_id, token = load_fleet_env(fleet_env_path(X))`. `FileNotFoundError`: `qwen-agentd: <fleet_env_path(X)> not found; agent '<X>' has not joined a fleet`. `FleetEnvError e`: `qwen-agentd: <e>` (F21's messages, which carry no secret).
  6. If `fleet_env_path(Y)` exists, apply F26 step 3 exactly (the same overwrite policy as `join`): the same `(fleet_id, token)` gives `qwen-agentd: already joined fleet <fleet_id>` on stdout and exit 0; anything else gives `qwen-agentd: <path> exists for a different fleet; remove it first` and exit 2. **[spec choice: one overwrite policy for both join forms; never overwrite.]**
  7. `write_fleet_env(fleet_env_path(Y), fleet_id, token)` (atomic, `0o600`, M4). Print `qwen-agentd: joined fleet <fleet_id> (copied from agent <X>)` to stdout. Exit 0.

  The token appears in no output, argv, environment or log. The fleet_id is not a secret (F23 prints it).

### 3.4 `status`

- **M30. `status [--agent-id ID] [--port N]`.**
  1. **Port.** If `--port` is given, use it, with no agent resolution and no registry read. **[spec choice: an explicit port wins, as a debugging escape hatch, and keeps `status --port N` working as today.]** Otherwise `ID = resolve_agent(args.agent_id)` (exit 2 on error), then `fleets_dir = A(ID)/current/qwen-agent-workspace/fleets` if `os.path.lexists(A(ID)/current)`, else `os.path.join(REPO_ROOT, "fleets")`. **[spec choice: an installed agent's daemon runs from `current`; a dev daemon runs from a checkout.]** Then `port, files = agent_port(fleets_dir, ID)`. `files == []`: `qwen-agentd: agent '<ID>' is not in any registry in <fleets_dir>; pass --port N` (exit 2). `port is None` otherwise: `qwen-agentd: agent '<ID>' has different ports in <files joined by ', '> in <fleets_dir>; pass --port N` (exit 2).
  2. **View.** `GET http://127.0.0.1:<port>/peers`, with F94's daemon, skills and peer lines unchanged.
  3. **Update line.** It reads `<A(U)>/update-state.json` for the first available `U`: `args.agent_id` if given (an invalid value exits 2 with M22's message, before any network call); else `view["self"]["host_id"]` when the daemon answered and that value fullmatches `HOST_ID_RE`; else the single ID of `agent_ids_on_disk()` when there is exactly one. With no `U`, or no state file, the line is `update: not installed`. Otherwise it is F94's `update: status=...` line.
  4. Exit codes: 0 when the daemon answered, 1 when it did not, 2 for step 1's errors.

### 3.5 `run` and `selftest`

- **M31. `run` startup order** (replaces F95 steps 3-9; F96-F99 unchanged). `cmd_run` does steps 1-5; `Daemon.start` does steps 6-13.
  1. `t0 = time.monotonic()`.
  2. Validate the flags (F92, M15, M16). `beacon_targets` and `beacon_port` are `None` when not given.
  3. `host_id = os.environ.get("QWEN_AGENT_HOST_ID", "")`. Empty: `qwen-agentd: QWEN_AGENT_HOST_ID is not set; agents on this machine: <agent_ids_on_disk() joined by ', ', or none>`. It no longer fullmatches `HOST_ID_RE`: `qwen-agentd: invalid QWEN_AGENT_HOST_ID '<value>'`. **[spec choice: the registry cannot be read before the agent's `fleet.env` gives its fleet_id, so the message lists agents on disk instead of registry IDs.]**
  4. `fleet_id, token = load_fleet_env(fleet_env_path(host_id))`, with F100's two messages, the missing-file one becoming `qwen-agentd: <path> not found; run qwen-agentd init-fleet --agent-id <id> or qwen-agentd join --agent-id <id>`. Then `key = token_key(token)` and `del token`.
  5. `setup_logging(host_id)`: `log_dir(host_id)`, `0o700`, as F107-F108.

  Errors in steps 2-4 go to stderr only, since logging is not set up yet. They create no directory. **[spec choice: a mistyped `QWEN_AGENT_HOST_ID` leaves nothing on disk.]** Under launchd that stderr lands in `A/logs/launchd.err`; under systemd it lands in the journal.

  6. Load the registry (default `REPO_ROOT/fleets/<fleet_id>.json`, F5). Errors are logged and printed (F100).
  7. `self_entry(registry, host_id)`. F9's error is logged and printed.
  8. `version = release_version(REPO_ROOT, deploy_root(host_id))`.
  9. `beacon_port = args value or self_entry["port"]`; `beacon_targets = args value or default_beacon_targets(registry)`. Here "args value" means the flag's parsed value when it is not `None`; an explicit `none` gives `[]`, which is not `None`.
  10. Bind TCP, then UDP (F95 step 8, F96).
  11. The synchronous model probe (F16).
  12. Start the threads (F95 step 10), reading the update state from `deploy_root(host_id)`.
  13. The F95 step 11 log line, with the resolved `beacon_port` and `len(beacon_targets)`. Then step 12 (wait).
- **M32. Per-agent internals.** Every use of the old no-argument functions becomes the agent's own:
  - `spawn_run`'s `last-run.stderr` goes in `log_dir(self.host_id)`.
  - `gate_release(d, tag)` writes `gate-<tag>.log` in `os.path.join(d, fleet_lib.LOGS_SUBDIR)`. This equals `log_dir(id)` because `d = deploy_root(id)`.
  - `UpdateCtx.__init__` sets `self.d = fleet_lib.deploy_root(daemon.host_id)`. So `fetch`, `stage`, `gate`, `swap`, `restart` and the state file all act on the agent's own root. Each agent's updater gates its own release.
  - `_start_threads` and `_confirm_switch` use `deploy_root(self.host_id)`.
  - `install` uses `deploy_root(ID)` and `log_dir(ID)`; `install_service` uses M6.
  - `cmd_status` uses M30.
- **M33. `selftest`** is unchanged (F93). T25 changes (Section 5.6): it checks the token of every `fleet_env_path(i)` for `i` in `agent_ids_on_disk()` whose file exists, and is skipped when none exists.
- **M34. Launcher.** `bin/qwen-agentd-launch` code is unchanged; it finds its root from its own path (`:92-93`), so `A(<id>)/qwen-agentd-launch` acts on `A(<id>)`. Its docstring's first path sentence (`:4`) becomes `install copies this file to ~/agents/<id>/qwen-agentd-launch, outside`. Like [FLEET] L8, a launcher change takes effect only after `install --agent-id <id>` is re-run, once per agent.

### 3.6 Removal, secrets, help text

- **M35. Manual removal** (no `uninstall` command). To remove agent `X`:
  - macOS: `launchctl bootout gui/$(id -u)/com.qwen-agent.qwen-agentd.X`, then `rm ~/Library/LaunchAgents/com.qwen-agent.qwen-agentd.X.plist`.
  - Linux: `systemctl --user disable --now qwen-agentd-X.service`, then `rm ~/.config/systemd/user/qwen-agentd-X.service && systemctl --user daemon-reload`.
  - Both: `rm -rf ~/agents/X` (releases, bare clone, state, logs and `fleet.env`), then `rm ~/.local/bin/qwen-agent-X`.
  - Default command: if `grep -qx '# agent-id: X' ~/.local/bin/qwen-agent` succeeds, either `rm ~/.local/bin/qwen-agent`, or make another installed agent `Y` the default with `python3 ~/agents/Y/current/qwen-agent-workspace/bin/qwen-agentd install --agent-id Y --default`. That re-run of install is idempotent, but it reloads Y's service, which restarts Y's daemon.
  - Firewall: remove X's port rule ([PREP] P15's commands, with `delete`) only if no other agent on the machine uses that port.
- **M36. Secrets.** F28 and F109 hold unchanged. In addition: wrapper files contain no secret (they carry the agent ID, a loopback URL and a path); `join --from-agent` never prints, logs or passes the token; `status` never reads `fleet.env`; `install` never reads `fleet.env`, only tests whether it exists.
- **M37. Help text.** The usage block at `bin/qwen-agentd:4-10` becomes:

  ```
    qwen-agentd [run] [--registry PATH] [--beacon-targets LIST] [--beacon-port N]
                      [--qwen-agent-bin PATH] [--timing-scale X]
    qwen-agentd init-fleet [--agent-id ID]
    qwen-agentd join [--agent-id ID] [STRING | --from-agent ID]
    qwen-agentd install --agent-id ID [--default] [--origin URL] [--no-service]
    qwen-agentd selftest
    qwen-agentd status [--agent-id ID] [--port N]
  ```

  The `install` subparser help becomes `install an agent into ~/agents/<id> with its service and commands`. The `status` help becomes `print an agent's fleet view and update state`. Docstrings of every changed `fleet_lib` function cite "multi-agent spec M<n>".

---

## 4. Code change map

### 4.1 `fleet_lib.py`

| Item | Change |
|---|---|
| `import sys` | removed (M5) |
| `DEPLOY_ROOT` | removed; `AGENTS_DIR = "~/agents"` added (M2) |
| `SYSTEMD_UNIT` | removed; `SYSTEMD_UNIT_FMT = "qwen-agentd-%s.service"` added (M6) |
| new constants | `LOGS_SUBDIR`, `FLEET_ENV_NAME`, `MIN_PORT = 1024`, `BROADCAST_ADDR`, `BIN_DIR`, `COMMAND_NAME`, `WRAPPER_MARKER`, `WRAPPER_ID_PREFIX`, `WRAPPER_MAX_BYTES = 65536` |
| `_validate_hosts` | port range `MIN_PORT..65535` and its message (M7); the duplicate rule unchanged (M19) |
| `fleet_env_path(host_id)`, `write_fleet_env` | M4 |
| `deploy_root(host_id)`, `log_dir(host_id)`, `_check_agent_id` | M2, M5 |
| `launchd_label`, `systemd_unit` | M6 |
| `command_path`, `default_command_path` | M8 |
| `_sh_single_quote`, `wrapper_bytes`, `is_wrapper`, `wrapper_agent_id`, `classify_command_path`, `write_wrapper` | M9, M10 |
| `agent_command_action`, `default_command_action` | M11, M12 |
| `agent_ids_on_disk`, `resolve_agent`, `agent_port` | M21, M22, M24 |
| `default_beacon_targets` | M16 |

Everything else in `fleet_lib.py` is unchanged.

### 4.2 `bin/qwen-agentd`

| Location | Change |
|---|---|
| docstring `:4-10` | M37 |
| `cmd_init_fleet` `:69-83` | M27 |
| `cmd_join` `:86-106` | M28, M29 |
| `setup_logging()` `:133-144` | becomes `setup_logging(host_id)` using `log_dir(host_id)` |
| `_validate_run_flags` `:188-204` | `None` passes through for both beacon flags (M31 step 2) |
| `Daemon.__init__` / `start` `:365-428` | `Daemon(args, beacon_targets, beacon_port, scale, t0, host_id, fleet_id, key)`. `start` does M31 steps 6-13; the `fleet.env` load and the `QWEN_AGENT_HOST_ID` read move to `cmd_run` |
| `_start_threads` `:482`, `_confirm_switch` `:876` | `deploy_root(self.host_id)` |
| `spawn_run` `:751` | `log_dir(self.host_id)` |
| `cmd_run` `:893-911` | M31 steps 1-5, then `Daemon(...)` and `start` |
| `cmd_status` `:924-953` | M30 |
| `gate_release` `:1034` | `os.path.join(d, fleet_lib.LOGS_SUBDIR)` |
| `launchd_plist_dict` `:1076` | `"Label": fleet_lib.launchd_label(host_id)` |
| `install_service` `:1117-1139` | M6 paths, label, unit, `log_dir(host_id)` |
| `cmd_install` `:1142-1225` | M25, M26; the symlink block `:1201-1211` is replaced by step 9c-d |
| `UpdateCtx.__init__` `:1258` | `deploy_root(daemon.host_id)` |
| `_build_parser` `:1313-1339` | M23 |

---

## 5. Tests

### 5.1 Rules

[FLEET] 11.1 holds, with three amendments:

- **No real `HOME`.** Every new test sets `HOME` to a temp directory, either with `monkeypatch.setenv("HOME", ...)` in-process or through `fleet_testutil.clean_env(home)` for subprocesses. The only test that reads the real `HOME` stays T25, which is read-only and skipped when there is no fleet secret, as today.
- **Broadcast exception.** MT10 is the only test that runs daemons without `--beacon-targets`, so its daemons send limited broadcasts to `255.255.255.255:<its two registry ports>`. Both ports come from `free_port()` (ephemeral, never 8190; the test asserts this), and the datagrams are test-fleet beacons (opaque, F29f). Its assertions do not depend on broadcast delivery. If `sendto` fails (no network), the daemons log F30's warning and are found by polling.
- **Stdlib and `http.client` only.** No `urllib` in new code. Every new file and change compiles under 3.9.6 and 3.13 (MT41).

### 5.2 Helper changes (`tests/fleet_testutil.py`)

| Helper | New behavior |
|---|---|
| `make_fleet(home, host_id, fleet_id=TEST_FLEET_ID, token=TEST_TOKEN)` | `write_fleet_env(<home>/agents/<host_id>/fleet.env, ...)`; returns the path. `host_id` is now the second positional parameter, and every call site is updated (Section 5.6) |
| `daemon_log_dir(home, host_id)` | `<home>/agents/<host_id>/logs` on every platform |
| `read_log(home, host_id)` | reads `daemon_log_dir(home, host_id)/qwen-agentd.log` (`""` if absent) |
| `DaemonProc.log()` | `read_log(self.home, self.host_id)`. When `beacon_port` is `None`, `DaemonProc.beacon_port` is set to the registry port |
| `start_daemon(home, host_id, registry, beacon_port, beacon_targets, ...)` | `beacon_port=None` omits `--beacon-port`; `beacon_targets=None` omits `--beacon-targets`. Otherwise unchanged |
| `Fleet.__init__` | `make_fleet(home, name)` |
| module docstring | "every daemon gets explicit beacon targets" gains "except MT10 (spec 5.1)" |

### 5.3 Unit tests (`tests/test_fleet_lib.py`; they also run in the self-update gate)

Each uses `monkeypatch.setenv("HOME", <value>)` and only `fleet_lib`, `tmp_path` and the standard library.

| ID | Covers | Pass condition |
|---|---|---|
| MT1 | M2, M4-M6, M8 | With `HOME=/h`: `deploy_root("mac-local") == "/h/agents/mac-local"`; `fleet_env_path("mac-local") == "/h/agents/mac-local/fleet.env"`; `log_dir("mac-local") == "/h/agents/mac-local/logs"`; `launchd_label("mac-local") == "com.qwen-agent.qwen-agentd.mac-local"`; `systemd_unit("ollama-168") == "qwen-agentd-ollama-168.service"`; `command_path("mac-local") == "/h/.local/bin/qwen-agent-mac-local"`; `default_command_path() == "/h/.local/bin/qwen-agent"`. Each of `deploy_root`, `fleet_env_path`, `log_dir`, `launchd_label`, `systemd_unit`, `command_path` and `wrapper_bytes` (with port 8190) raises `ValueError` for `""`, `"Mac"`, `"../x"`, `"a/b"`, `"mac-local\n"` and `None`. `not hasattr(fleet_lib, "DEPLOY_ROOT")` and `not hasattr(fleet_lib, "SYSTEMD_UNIT")`. |
| MT2 | M9, M10 | (a) With `HOME=/h`, `wrapper_bytes("mac-local", 8190)` equals the six lines of M9 with `/h` in place of `/Users/reubenpatterson`, byte for byte. (b) With `HOME=/h/it's`, the exec line is `exec '/h/it'\''s/agents/x/current/qwen-agent-workspace/bin/qwen-agent' "$@"` (agent `x`). (c) `ValueError` for ports `1023`, `65536`, `True`, `"8190"`. (d) `is_wrapper` is `True` for (a)'s bytes and for `b"#!/bin/sh\n# qwen-agentd wrapper\n"`; `False` for `b"# qwen-agentd wrapper extra\n"`, `b"#  qwen-agentd wrapper\n"`, `b""`. `wrapper_agent_id` gives `"mac-local"` for (a), and `None` with no ID line or for `# agent-id: Bad`. (e) Functional: with `HOME=<tmp>`, write `wrapper_bytes("x", 8191)` to `<tmp>/w` (mode 0755). Create `<tmp>/agents/x/current/qwen-agent-workspace/bin/qwen-agent` as `#!/bin/sh\nprintf '%s;%s;%s' "$QWEN_AGENT_DAEMON_URL" "$1" "$2"\n` (mode 0755). Run `["/bin/sh", "<tmp>/w", "a b", "c"]` with an env that lacks `QWEN_AGENT_DAEMON_URL`; stdout is exactly `http://127.0.0.1:8191;a b;c`. |
| MT3 | M10 | `classify_command_path`: missing gives `absent`; a dangling symlink gives `symlink`; (a)'s bytes give `("wrapper", "mac-local")`; a plain script gives `other`; a directory gives `other`; a file of `WRAPPER_MAX_BYTES + 1` bytes containing a marker line gives `other`. `write_wrapper` under `os.umask(0o077)` (restored in `finally`) gives mode `0o755` and leaves no `.tmp`. A pre-existing `<path>.tmp` is removed first. A symlink at `path` pointing at `<tmp>/target` is replaced, and `<tmp>/target`'s content is unchanged. `agent_command_action` and `default_command_action` return every row of M11 and M12. |
| MT4 | M7, M19 | Port `1023` gives exactly one error starting `hosts.mac-local.port: must be an integer in 1024..65535`; `1024` and `65535` validate. A registry with `vision-185` and `gemma-185` (both role `agent`, address `192.168.1.185`, port `8190`) gives exactly `["hosts.vision-185: address 192.168.1.185:8190 is already used by hosts.gemma-185"]`; with `gemma-185` on `8191` it gives `[]`. |
| MT5 | M16 | `default_beacon_targets(<F18 registry, no ports>) == [("255.255.255.255", 8190)]`. For ports `9000`, `8191`, `8190` and an orchestrator at `8190`, the result is `[(..., 8190), (..., 8191), (..., 9000)]`. An orchestrator-only port is included. The result is the same for the raw registry and for `load_registry`'s output. |
| MT6 | M21, M22 | With `HOME=<tmp>`: no `~/agents` gives `[]`, and `resolve_agent(None)` gives M22's no-agent message with `<tmp>/agents`. `agents/alpha/fleet.env` gives `["alpha"]` and `("alpha", None)`. Adding a dangling `agents/bravo/current` gives `["alpha", "bravo"]` and the more-than-one message `(alpha, bravo)`. These are ignored: `agents/Bad_Name/fleet.env`, an empty `agents/empty/`, a regular file `agents/file`, and `agents/notes/` holding `readme`. `resolve_agent("zed") == ("zed", None)`; `resolve_agent("Bad") == (None, "qwen-agentd: invalid --agent-id 'Bad'")`. |
| MT7 | M24, M4 | `agent_port`: a missing directory and an empty directory give `(None, [])`. `a.json` listing `h1` at 9001 gives `(9001, ["a.json"])`. `h1` without a port gives `(8190, ...)`. `b.json` (a second valid registry, other fleet_id) also at 9001 gives `(9001, ["a.json", "b.json"])`; at 9002 it gives `(None, ["a.json", "b.json"])`. Bad JSON, a registry failing `validate_registry`, and `notes.txt` are skipped. `write_fleet_env`: a leftover `<path>.tmp` is replaced and gone afterwards; an existing `path` raises `FileExistsError`, keeps its content, and leaves no `.tmp`; the parent is `0o700` and the file `0o600`. |

### 5.4 Integration tests (`tests/test_fleet_integration.py`)

| ID | Covers | Procedure and pass condition |
|---|---|---|
| MT10 | M15-M17, M31, MK4 | One `HOME` `<tmp>/m`; `make_fleet(m, "alpha")` and `make_fleet(m, "bravo")`; `pa, pb = free_port(), free_port()`, asserting `8190 not in (pa, pb)`. Stubs: `alpha` vllm with skills `[]`; `bravo` ollama with `["researcher"]`. One registry (`write_registry`, both at `127.0.0.1`). `start_daemon(m, "alpha", registry, None, None)` and the same for `bravo`; the argv contains neither `--beacon-port` nor `--beacon-targets`. Pass: (a) `<m>/agents/alpha/logs/qwen-agentd.log` contains `qwen-agentd dev started host_id=alpha port=<pa> beacon_port=<pa> beacon_targets=2 skills=`, and bravo's log the same with `pb`; neither log contains the other's `started host_id=` line. (b) Binding a new UDP socket (no `SO_REUSEADDR`) to `("0.0.0.0", pa)` raises `OSError` with `errno.EADDRINUSE`; the same for `pb`. (c) Within 7.5 s, `alpha`'s `/peers` lists `bravo` with `port == pb`, and `bravo`'s lists `alpha` with `port == pa`, whatever `heard_via`. |
| MT11 | M31 | Subprocess `run --registry <r> --beacon-targets none --beacon-port <free>` with `HOME=<h>`, where `<r>` lists `alpha`. (a) `QWEN_AGENT_HOST_ID` unset after `make_fleet(h, "alpha")`: exit 2, stderr exactly `qwen-agentd: QWEN_AGENT_HOST_ID is not set; agents on this machine: alpha\n`. With an empty `HOME`, `...: none\n`. (b) `Bad_Id`: `qwen-agentd: invalid QWEN_AGENT_HOST_ID 'Bad_Id'\n`. (c) `charlie` without a fleet secret: exit 2, stderr exactly `qwen-agentd: <h>/agents/charlie/fleet.env not found; run qwen-agentd init-fleet --agent-id charlie or qwen-agentd join --agent-id charlie\n`, and `<h>/agents/charlie` does not exist afterwards. (d) After `make_fleet(h, "charlie")`: F9's message on stderr, and the same line at ERROR in `read_log(h, "charlie")`. |
| MT12 | M30 | (a) `status` with no agents in `HOME`: exit 2, stderr M22's no-agent message, stdout empty. (b) Two agent directories: exit 2, the more-than-one message. (c) `status --agent-id zulu` with `zulu` not installed: exit 2, stderr `qwen-agentd: agent 'zulu' is not in any registry in <WS>/fleets; pass --port N\n`. (d) A daemon `alpha` running (`_single`), a second agent directory `bravo` in the same `HOME`, and `status --port <alpha port>`: exit 0, last line `update: not installed` (U = alpha from the view). (e) The same after killing alpha: exit 1, `daemon: not reachable at ...` then `update: not installed` (two agents on disk, so no U). (f) `status --agent-id alpha --port <alpha port>` while alpha runs: exit 0. |
| MT13 | M27-M29, M36, MK5 | In-process (`agentd` fixture, `HOME` = temp). (a) `init-fleet` with no agents: 2, M22's message. (b) `init-fleet --agent-id alpha`: 0, F23's four lines; `<HOME>/agents/alpha` is `0o700` and `fleet.env` `0o600`. (c) `init-fleet` (inferred alpha): 2, `... already exists ...`. (d) `join --agent-id bravo --from-agent alpha`: 0; stdout exactly `qwen-agentd: joined fleet <fid> (copied from agent alpha)\n`; stderr `""`; bravo's file bytes equal alpha's; mode `0o600`; no `.tmp`; neither stdout nor stderr contains the token or any 16-character substring of it. Repeating it gives 0 and `qwen-agentd: already joined fleet <fid>\n`. (e) Errors, each exit 2 with M29's exact message: `--agent-id alpha --from-agent alpha`; `--agent-id carol --from-agent dave` (no secret); `--agent-id carol --from-agent Bad_Id`; `--agent-id carol --from-agent alpha <join string>`; and `--agent-id bravo --from-agent alpha` after bravo's file has been replaced by another fleet's (`exists for a different fleet`). (f) `join` with two agents and no flag: 2, the more-than-one message, and the monkeypatched `getpass.getpass` (raising `AssertionError`) is never called. (g) `join --host-id erin <join string>` works like `--agent-id erin`. |

### 5.5 Install tests (`tests/test_fleet_self_update.py`, its `Origin` fixture)

Each runs `install` as a subprocess with `HOME=<tmp>/home`, `--origin <bare>` and `--no-service`, unless the row says otherwise. Expected wrapper bytes are computed in-process with `monkeypatch.setenv("HOME", <tmp>/home)` and `fleet_lib.wrapper_bytes`.

| ID | Covers | Procedure and pass condition |
|---|---|---|
| MT20 | M3, M11, M12, M25, M26, MK3 | The origin registry lists `h1` (port P1) and `h2` (port P2, both `free_port()`). Tag `v2026.01.01`. (1) `install --agent-id h1`: exit 0; stdout exactly `installed v2026.01.01 at <H>/agents/h1`, `command: <H>/.local/bin/qwen-agent-h1 (daemon port P1)`, `default: <H>/.local/bin/qwen-agent runs agent h1`, and M26's `next:` line for h1. Both commands are regular files, mode 0755, with bytes `wrapper_bytes("h1", P1)`. (2) `install --host-id h2`: the default line is `default: ... unchanged; pass --default to make it run agent h2`; `<H>/agents/h1` and `<H>/agents/h2` each have their own `repo/`, `current`, `update-state.json` and `qwen-agentd-launch`; the default still holds h1's bytes. (3) `install --agent-id h2 --default`: the default holds h2's bytes. (4) `install --agent-id h1`: `qwen-agent-h1` is rewritten; the default keeps h2's bytes (`unchanged` line). (5) After `make_fleet(H, "h1", ...)`, `join --agent-id h2 --from-agent h1` (subprocess) exits 0; `<H>/agents/h2/fleet.env` is `0o600` with the same bytes; stdout has no token. (6) No path outside `<H>/agents`, `<H>/.local/bin` and `<tmp>/o` (the origin) was created under `<tmp>`. |
| MT21 | M11, M12 | After MT20-style installs of h1: (a) `qwen-agent-h1` replaced by the regular file `#!/bin/sh\necho mine\n`; `install --agent-id h1` exits 0, stderr contains `qwen-agentd: warning: not replacing <H>/.local/bin/qwen-agent-h1: not a symlink or a qwen-agentd wrapper`, the file is unchanged, and there is no `command:` line. (b) The default replaced by a non-marker regular file; `install --agent-id h1 --default` warns the same for that path and leaves it unchanged. (c) The default replaced by a symlink to `/nonexistent`; `install --agent-id h2` keeps it (the `unchanged` line, still a symlink); `install --agent-id h2 --default` replaces it with a regular file holding h2's bytes. |
| MT22 | M24, M25 | (a) `install --agent-id h3` (not in the registry): exit 0; stderr contains `qwen-agentd: warning: agent 'h3' is not in any registry of release v2026.01.01; its commands use port 8190`; `qwen-agent-h3` holds `wrapper_bytes("h3", 8190)`. (b) An origin with a second valid registry file (fleet_id `fedcba9876543210`) listing `h1` at another port: `install --agent-id h1` exits 2 with exactly `qwen-agentd: agent 'h1' has different ports in 0123456789abcdef.json, fedcba9876543210.json of release v2026.01.01\n`. |
| MT23 | M6, MK3 | In-process. `launchd_plist_dict("/usr/bin/python3", "/h/agents/mac-local", "mac-local", "/h/agents/mac-local/logs")` equals F90's dict with `Label` `com.qwen-agent.qwen-agentd.mac-local` and those paths. `systemd_unit_text("/usr/bin/python3", "/home/u/agents/ollama-168", "ollama-168")` equals F90's text with that root. Then, with `HOME` = temp, `agentd.subprocess.run` monkeypatched to record argv and return `CompletedProcess(argv, 0, "", "")`, and `agentd.sys.platform` monkeypatched: for `"darwin"`, `install_service(py, deploy_root("a"), "a")` and the same for `"b"` write `~/Library/LaunchAgents/com.qwen-agent.qwen-agentd.a.plist` and `...b.plist` (each `plistlib.loads` to its own Label and `QWEN_AGENT_HOST_ID`), and record `launchctl bootout gui/<uid>/com.qwen-agent.qwen-agentd.a`, then `launchctl bootstrap gui/<uid> <a plist>`, then the same for b. For `"linux"`: `~/.config/systemd/user/qwen-agentd-a.service` and `-b.service`, and for each: `systemctl --user daemon-reload`, `enable qwen-agentd-<x>.service`, `restart qwen-agentd-<x>.service`. |
| MT24 | M30 | After MT20 step (1), with no daemon running: `status --agent-id h1` exits 1, and stdout is exactly `daemon: not reachable at http://127.0.0.1:P1\nupdate: status=ok from=- to=v2026.01.01 attempts=0 bad_tags=-\n`. This proves the port came from `A(h1)/current`'s registry. |

### 5.6 Existing tests that change

`grep -n -E "local/share/qwen-agent|\.config/qwen-agent|\"\.config\", \"qwen-agent\"|\"\.local\", \"share\"|fleet_env_path\(\)|deploy_root\(\)|log_dir\(\)|make_fleet\(|daemon_log_dir\(|read_log\(|--host-id|LAUNCHD_LABEL|com\.qwen-agent" tests/` finds the sites below. **18 test functions** need body edits; every other fleet test changes only through the helpers of Section 5.2.

| File | Test | Edit |
|---|---|---|
| `test_fleet_lib.py` | `test_t25_token_not_in_git_tree` | M33: iterate `agent_ids_on_disk()`; skip if no secret exists |
| `test_fleet_lib.py` | `test_t29a_state_io_prune_and_version` | its last assertions (`:1067-1070`) become `deploy_root("x") == expanduser("~/agents/x")` and `log_dir("x") == expanduser("~/agents/x/logs")` |
| `test_fleet_integration.py` | `test_cli_init_fleet` | `init-fleet --agent-id alpha`; `fleet_env_path("alpha")` |
| | `test_cli_join` | `join --agent-id alpha ...`; `fleet_env_path("alpha")` |
| | `test_cli_internal_error_is_one_line` | `init-fleet --agent-id alpha` (otherwise resolution exits 2 first) |
| | `test_run_endpoints_and_peers_view` | `daemon_log_dir(daemon.home, "alpha")` |
| | `test_run_startup_errors` | `env_path` = `<home>/agents/alpha/fleet.env` and M31's new message; `make_fleet(home, "alpha")`; the unset case expects M31 step 3's message (`agents on this machine: alpha`); the `charlie` case first runs `make_fleet(home, "charlie")`; `make_fleet(home, "bravo")` before the UDP-in-use case; the final assertion (`"ERROR MainThread qwen-agentd: QWEN_AGENT_HOST_ID is not set" in ftu.read_log(home)`) is deleted, because M31 no longer logs that error (MT11 covers the case) |
| | `test_t45_foreign_fleet_is_invisible_and_silent` | `make_fleet(echo_home, "echo", ftu.OTHER_FLEET_ID, ftu.OTHER_TOKEN)` |
| | `test_review_focus_1_own_beacon_echo_is_silent` | `make_fleet(home, "solo")` |
| | `test_unregistered_same_fleet_host_warns_once` | `make_fleet(zulu_home, "zulu")` |
| | `test_t48_run_endpoint` | `daemon_log_dir(fleet.homes["bravo"], "bravo")` |
| | `test_t46_no_secret_leaves_the_daemon` | `daemon_log_dir(fleet.homes[name], name)` |
| `test_fleet_self_update.py` | `test_t61_install_layout_and_idempotence` | `d = <home>/agents/h1`; stdout per M26 (first run: installed, command, default, next; re-run after `make_fleet(home, "h1", ...)`: installed, command, default); the symlink assertions become: both commands are regular files equal to `wrapper_bytes("h1", <port>)`, and the exec target's `realpath` is under `d/releases/v2026.01.01` |
| | `test_install_rejects_bad_host_id_and_failing_first_release` | expects `qwen-agentd: invalid --agent-id 'Mac_Local'\n`; `daemon_log_dir(home, "h1")` |
| | `test_service_definitions` | M23's dict and text (MT23's first half replaces its assertions) |
| | `test_t60_switch_gate_failure_and_crash_rollback` | `read_log(home, "h1")` |
| | `test_t62_dirty_tree_blocks_the_update` | `read_log(home, "h1")` |
| | `test_t63_update_waits_for_an_in_flight_run` | `read_log(home, "h1")` |

Helpers changed with no test-body edit: `_single` (`make_fleet(home, "alpha")`), `_deploy` (`<home>/agents/h1`), `_setup` (`make_fleet(home, "h1", ...)`), `Supervisor` (through `_deploy`). Unchanged and still passing as-is: `test_status_command` (U = alpha from the view, or the single agent on disk), T40's `status --port` assertions, and T60's `status --port` assertions (U = `h1` from the view).

### 5.7 Regression

| ID | Covers | Pass condition |
|---|---|---|
| MT40 | MK1 | Before any change, record `python3 -m pytest tests/ -q -rA` from `WS`. After it: the same outcomes as that baseline (1027 passed, the one known failure, the one T25 skip), with the migrated tests counted as passing, plus every MT test passing. |
| MT41 | MK2 | `/usr/bin/python3 -m py_compile` and `python3 -m py_compile` on the four fleet files exit 0. |
| MT42 | M3, M14 | `grep -rn -E "local/share/qwen-agent|\.config/qwen-agent" fleet_lib.py bin/qwen-agentd bin/qwen-agentd-launch bin/qwen-agent tests/fleet_testutil.py tests/test_fleet_lib.py tests/test_fleet_integration.py tests/test_fleet_self_update.py` prints nothing. This is an acceptance command, not a pytest. [PREP]'s script and spec keep `~/.local/share/qwen-agent/searxng` (M14). |

### 5.8 Live

[FLEET] Section 12 R1-R10 is rewritten for this layout (`mac-local` on this Mac, `ollama-168` on .168, both on 8190). It runs at the joint rollout after the vision feature.

- **MR1 (optional; after the vision feature registers the .185 agents).** On .185: run [PREP] once per agent (`--port 8190 ...`, then `--port 8191 ...`). Then:
  1. `python3 <bootstrap clone>/qwen-agent-workspace/bin/qwen-agentd install --agent-id vision-185 --default`
  2. `python3 ~/agents/vision-185/current/qwen-agent-workspace/bin/qwen-agentd join --agent-id vision-185` (paste the string)
  3. `python3 ~/agents/vision-185/current/qwen-agent-workspace/bin/qwen-agentd install --agent-id gemma-185`
  4. `python3 ~/agents/vision-185/current/qwen-agent-workspace/bin/qwen-agentd join --agent-id gemma-185 --from-agent vision-185`

  Pass:
  - Within 75 s, `qwen-agentd status --agent-id vision-185` lists `gemma-185 192.168.1.185:8191`, and `status --agent-id gemma-185` lists `vision-185 192.168.1.185:8190`.
  - The Mac's `status --agent-id mac-local` lists both.
  - `systemctl --user status qwen-agentd-vision-185 qwen-agentd-gemma-185` shows both active.
  - `grep QWEN_AGENT_DAEMON_URL ~/.local/bin/qwen-agent-gemma-185` shows port 8191.
  - The older checkout on .185 is unchanged (`git -C <it> status` as before).

---

## 6. Requirement-to-test table

| Req | Tests | Live-only / reason |
|---|---|---|
| M1 | MT13(g), MT20(2) (alias) | naming is review-only beyond the alias |
| M2 | MT1, MT6 | |
| M3 | MT20, MT42 | |
| M4 | MT1, MT7, MT13 | |
| M5 | MT1, MT10, MT11(d) | |
| M6 | MT1, MT23 | real launchctl and systemctl: R3d, R5, R6 |
| M7 | MT4 | |
| M8 | MT1 | |
| M9 | MT2 | |
| M10 | MT2, MT3 | |
| M11 | MT3, MT20, MT21 | |
| M12 | MT3, MT20, MT21 | the Mac's real dev symlink: R3a, R3d |
| M13 | MT20(6) | "never touched" for the real checkouts: R3a, MR1 |
| M14 | MT42 | |
| M15 | MT10 | real UDP 8190 on two machines: R4 |
| M16 | MT5, MT10(a) | real broadcast delivery: R4, MR1 |
| M17 | T40 (unchanged), MT10(c) | same-machine broadcast loopback: MR1 |
| M18 | T47, T44 (unchanged) | same-machine delegation over the LAN IP: MR1 |
| M19 | MT4, T2 | |
| M20 | none | firewall state is live-only ([PREP] H16-H19 test the script) |
| M21 | MT6 | |
| M22 | MT6, MT12, MT13 | |
| M23 | MT13(g), MT20(2), MT11 | |
| M24 | MT7, MT22, MT24 | |
| M25 | MT20-MT22, T61 (migrated) | real services: R3 |
| M26 | MT20, T61 (migrated) | |
| M27 | MT13(a-c) | |
| M28 | MT13(f-g), `test_cli_join` (migrated) | |
| M29 | MT13(d-e), MT20(5) | |
| M30 | MT12, MT24, `test_status_command` | |
| M31 | MT10, MT11, `test_run_startup_errors` (migrated) | |
| M32 | T60-T63 (migrated), T46, T48 | |
| M33 | T25 (migrated; skipped without a secret) | R9 |
| M34 | T60 (the launcher from `A(h1)`) | |
| M35 | none | manual procedure; review only |
| M36 | MT13(d), MT20(5), T46 | R9 |
| M37 | none | help text; review only |

## 7. Supersession of [FLEET]

### 7.1 Requirement map

| [FLEET] | Superseded by | Summary |
|---|---|---|
| Terms (`D`), 1.3 `DEPLOY_ROOT`, `SYSTEMD_UNIT` | M2, M6 | `D` becomes `A(<id>) = ~/agents/<id>`; unit name format |
| F7 rule 8 | M7 | port range 1024..65535 |
| F7 rule 12 | M19 | unchanged; confirmed |
| F10, F100 (unset ID) | M31 | message lists agents on disk; checked before `fleet.env` |
| F19, F20 | M4 | `A/fleet.env`; atomic write |
| F23 | M27 | `--agent-id` |
| F26 | M28, M29 | `--agent-id`; `--from-agent` |
| F30 | M16 | default targets from the registry's ports |
| F31 | M15 | default receive port = own port |
| F80 | M2, M3 | per-agent root; commands are wrappers |
| F90 | M6 | per-agent label, plist and unit |
| F91 | M25, M26, M11, M12 | `--agent-id`, `--default`, wrappers, output |
| F92 | M23, M15, M16 | flags and defaults |
| F94 | M30 | agent resolution and port precedence |
| F95, F100 | M31 | startup order and messages |
| F107 | M5 | `A/logs` on every platform |
| 11.2 helpers; T5, T25, T29a, T61, and the CLI tests | Section 5.2, 5.6 | |
| Section 12 R1-R10, R0 fallback unit name | Section 7.2 | |

### 7.2 Rollout

[FLEET] Section 12 has been edited in place so that every path, service label and command matches M2-M6 and M23-M30. The main points:

- R1 runs `init-fleet --agent-id mac-local` from the dev checkout.
- R3a and R3b install with `--agent-id <id> --default`. On this Mac, `--default` is required: `~/.local/bin/qwen-agent` is already a (dangling) symlink, which M12 counts as "something there". With `--default`, install replaces it, which is what [FLEET]'s install already did.
- R9's grep excludes `fleet.env` by name and also covers `~/.local/bin`.

---

## 8. Values chosen by the spec

1. M2: every path function validates the agent ID and raises `ValueError` (no path traversal).
2. M3: `~/agents` is created with the umask and never `chmod`ed (it may be a user directory).
3. M4: `write_fleet_env` is atomic (tmp, `O_EXCL`, `fsync`, `os.link`) for all three writers.
4. M5: logs live in `A/logs` on both platforms; `import sys` is dropped.
5. M6: `SYSTEMD_UNIT` is replaced by `SYSTEMD_UNIT_FMT`; `LAUNCHD_LABEL` stays as the base.
6. M7: the registry port range is 1024..65535, matching [PREP] `--port`.
7. M9: the wrapper uses a separate `export` line (POSIX leaves export through `VAR=x exec` unspecified).
8. M9: the wrapper uses the absolute target path expanded at install time (independent of the caller's `HOME`).
9. M9: the target is always single-quoted, `'` written as `'\''` (one form for every path).
10. M9, M10: the wrapper has an `# agent-id: <id>` line, so a re-install can recognize its own default.
11. M10: a wrapper is at most 64 KiB, and detection needs a whole-line marker match.
12. M12: re-installing the agent the default already runs refreshes the default, even without `--default`.
13. M16: the default beacon targets include every registry entry's port, orchestrators and self included.
14. M19: the shipped duplicate-pair error string and its sorted-order ownership are kept.
15. M21: an agent directory must hold `fleet.env` or `current` to count.
16. M22: the exact messages for no agent, more than one agent, and an invalid ID.
17. M23: `--agent-id` and `--host-id` are both accepted on every subcommand that names an agent.
18. M24: install and status find the port by scanning the release's `fleets/*.json` (no `fleet.env` needed; install precedes join on .168).
19. M25: an agent missing from the registry warns and uses 8190 (the precedent: install does not check the registry); conflicting ports exit 2.
20. M26: the install stdout lines `command:` and `default:`, in that order.
21. M29: `--from-agent` uses `join`'s never-overwrite policy, and its exact error messages.
22. M30: an explicit `--port` beats `--agent-id`; the update-line agent order (flag, view, single agent on disk).
23. M30: status reads registries from `A/current` when installed, else from `REPO_ROOT`.
24. M31: `QWEN_AGENT_HOST_ID` and `fleet.env` are checked before logging, so a typo creates no directory; the new unset and invalid messages.
25. MT10: the one test allowed to broadcast, on ephemeral ports.

## 9. Risks

- **MR-A. Memory contention (accepted; no design change).** Two model servers on one machine compete for memory. On this Mac a second vllm-metal instance starves the first through KV-cache pre-allocation at the default `--gpu-memory-utilization 0.92`. Running a second agent on the Mac needs explicit utilization caps on both servers.
- **MR-B. Two agents on one model server.** `run_lock` is per agent. Two agents pointed at the same vllm-metal URL can send it concurrent requests, which crash it ([FLEET] 0.2, L2). Give each agent its own model server, unless the server tolerates concurrency (Ollama does).
- **MR-C. Port changes need a re-install.** The wrapper bakes in the port at install time (M9). A release that changes an agent's registry port restarts the daemon on the new port, but `qwen-agent-<id>` and the default still point at the old one. They fall back silently to the local path, or reach another agent's daemon if the ports were swapped. After any port change, re-run `install --agent-id <id>` for each affected agent on each machine (like [FLEET] L8).
- **MR-D. Same-machine discovery may be poll-only.** Limited-broadcast loopback is OS-dependent. If it fails, agents on one machine find each other only through polling: within 75 s instead of 45 s, and dependent on the registry address being the machine's current IP ([FLEET] L4).
- **MR-E. Startup errors before logging.** An unset or invalid `QWEN_AGENT_HOST_ID`, or a missing or bad `fleet.env`, is reported only on stderr: `A/logs/launchd.err` on macOS, the journal on Linux. The R-steps tell the operator where to look.
- **MR-F. Disk per agent.** Each agent has its own bare clone and up to `KEEP_RELEASES + 2` worktrees.
- **MR-G. Generic `~/agents`.** `install` creates `~/agents/<id>` next to any unrelated content the user keeps there. M21 ignores directories without `fleet.env` or `current`.
- **MR-H. Default command replaces the dev symlink.** After R3a, `qwen-agent` on the Mac runs mac-local's release, not the dev checkout. To go back: `ln -sfn ~/local_agent_harness/qwen-agent-workspace/bin/qwen-agent ~/.local/bin/qwen-agent`. A later `install --default` replaces that symlink again; a plain `install` keeps it (M12).
- **MR-I. MT10 broadcasts.** The test sends real limited broadcasts on two ephemeral ports. They are harmless and opaque, but visible to LAN sniffers while the suite runs.
- **MR-J. Two updaters on one machine.** Agents on one machine update independently, each within one update period, so for up to 30 min they may run different releases. A `PROTOCOL` bump makes them mutually incompatible until both update ([FLEET] 9.10).

## 10. Coverage and traceability

- Every M requirement maps to at least one MT or migrated T test (Section 6), except M20 (firewall state, live-only; [PREP] tests the script), M35 (manual procedure) and M37 (help text), which are review-only.
- Every MT test names the requirements it covers. MT40-MT42 tie the whole change to MK1, MK2 and the old-path grep.
- Every [FLEET] requirement this spec changes is listed in Section 7.1, and [FLEET] carries a matching supersession note at the top of each affected section.
- The KPIs MK1-MK5 are automated. MK6 is live (R1-R10). MR1 is optional.
- Contradictions resolved here, which the reader should know about:
  - The duplicate `(address, port)` rule the brief called new already ships (M19).
  - The brief listed "logs" and "run lock" under the old root. Logs were outside it ([FLEET] F107), and the run lock is in memory. M5 moves the logs; nothing moves for the lock (M3).
  - The rule "set the default only if nothing is there" conflicts with "install replaces the Mac's existing symlink". R3a resolves this with `--default` (M12, Section 7.2).
  - F100's unset-ID message cannot list registry IDs any more (M31).

Open questions: none.
