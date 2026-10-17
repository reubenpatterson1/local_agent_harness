# Fleet Multi-Agent Hosts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let one machine run several fleet agents by deriving every per-agent path, service name, command and port from the agent ID: the agent root `~/agents/<id>/` (repo, releases, `current`, update state, launcher, `fleet.env`, `logs/`), the LaunchAgent `com.qwen-agent.qwen-agentd.<id>` or unit `qwen-agentd-<id>.service`, the generated commands `~/.local/bin/qwen-agent-<id>` and `~/.local/bin/qwen-agent`, and the registry `port` (TCP and, by default, UDP), with `--agent-id` resolution, `join --from-agent`, and registry-derived beacon defaults.

**Architecture:** Every new decision is a pure function in `fleet_lib.py` (agent ID validation, per-agent paths, service names, command paths, wrapper bytes and detection, the install write/keep/refuse rules, agent resolution, the registry port lookup, default beacon targets, the atomic `fleet.env` write). `bin/qwen-agentd` reads `QWEN_AGENT_HOST_ID` and that agent's `fleet.env` before logging starts, then passes the agent ID to every path call (startup, logging, `/run`, the gate, the updater, the self-check, install, status, init-fleet, join). Generated POSIX `sh` wrappers replace the `~/.local/bin/qwen-agent` symlink, so each command carries its agent's daemon port. No protocol field, registry key or environment variable is renamed: `host_id` stays the internal name.

**Tech Stack:** Python 3.13.0 (`python3`, pytest 8.3.4) and Python 3.9.6 (`/usr/bin/python3`, compile check only); standard library only (`os`, `json`, `argparse`, `plistlib`, `socket`, `subprocess`, `http.client`); POSIX `/bin/sh` for the wrappers; git for the self-update fixtures; launchd and systemd only through a recorded `subprocess.run` in tests.

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-10-17-fleet-multi-agent-hosts-design.md` (commit `3366d49`), which amends `qwen-agent-workspace/docs/superpowers/specs/2026-10-16-fleet-discovery-self-update-design.md` ([FLEET]) only where its Section 7 says so. The spec is final and user-approved; this plan changes no design decision. Every value the spec leaves to the implementation, and every place where the plan had to interpret it, is listed in "Plan decisions" at the end.

## Global Constraints

From the spec, verbatim (requirement IDs in brackets):

- [0.2] "Nothing from [FLEET] has been deployed anywhere, so no migration is needed."
- [0.3] "`bin/qwen-agent`, `agent/qwen-agent-unsafe`, `scripts/`, [PREP] and every other file are not changed."
- [MK1] "`python3 -m pytest tests/ -q -rA` from `WS` gives the [FLEET] T70 baseline (1027 passed; 1 failed, exactly `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike`; 1 skipped, T25) plus every new MT test passing and no other change in outcome"
- [MK2] "`/usr/bin/python3 -m py_compile` (3.9.6) and `python3 -m py_compile` (3.13) succeed on `fleet_lib.py`, `bin/qwen-agent`, `bin/qwen-agentd`, `bin/qwen-agentd-launch`"
- [MK5] "The fleet token never appears in any command output, log line, wrapper file, beacon or child environment"
- [M1] "Internally the name stays `host_id` everywhere: the registry key, `/health`'s `host_id`, `QWEN_AGENT_HOST_ID`, `LivenessTable`, `self_entry`. No protocol field, registry key, or environment variable is renamed."
- [M2] "Every function of M2-M8 that takes `host_id` calls `_check_agent_id` first."
- [M13] "No command writes inside a git checkout: `install` writes only under `A(<id>)`, `~/.local/bin/qwen-agent`, `~/.local/bin/qwen-agent-<id>` (each with its `.tmp`), and the service file (with its `.tmp`)."
- [M14] "[PREP]'s SearXNG stable directory stays `~/.local/share/qwen-agent/searxng/`. It is one per machine, not per agent, and no fleet code reads it. Do not "fix" it to `~/agents/...`."
- [M36] "F28 and F109 hold unchanged. In addition: wrapper files contain no secret (they carry the agent ID, a loopback URL and a path); `join --from-agent` never prints, logs or passes the token; `status` never reads `fleet.env`; `install` never reads `fleet.env`, only tests whether it exists."
- [M37] "Docstrings of every changed `fleet_lib` function cite "multi-agent spec M<n>"."
- [5.1] "**No real `HOME`.** Every new test sets `HOME` to a temp directory, either with `monkeypatch.setenv("HOME", ...)` in-process or through `fleet_testutil.clean_env(home)` for subprocesses. The only test that reads the real `HOME` stays T25, which is read-only and skipped when there is no fleet secret, as today."
- [5.1] "**Broadcast exception.** MT10 is the only test that runs daemons without `--beacon-targets`, so its daemons send limited broadcasts to `255.255.255.255:<its two registry ports>`. Both ports come from `free_port()` (ephemeral, never 8190; the test asserts this)"
- [5.1] "**Stdlib and `http.client` only.** No `urllib` in new code. Every new file and change compiles under 3.9.6 and 3.13 (MT41)."

House rules for this plan:

- `WS` = `/Users/reubenpatterson/local_agent_harness/qwen-agent-workspace`. The git root is one level up, so `git status` and `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix. Branch `qwen-agent-redteam`, base commit `3366d49`. Run every command from `WS` unless a step says otherwise.
- Files this plan modifies, and no others: `fleet_lib.py`, `bin/qwen-agentd`, `bin/qwen-agentd-launch`, `tests/fleet_testutil.py`, `tests/test_fleet_lib.py`, `tests/test_fleet_integration.py`, `tests/test_fleet_self_update.py`. `bin/qwen-agent` and `tests/test_qwen_agent_fleet.py` are not changed (spec 0.2: `bin/qwen-agent` "needs no change"). `agent/qwen-agent-unsafe`, `tests/test_researcher_think_off.py` and `scripts/deploy/` stay byte-identical.
- A separate plan (fleet-host-prep) is being executed concurrently and edits `scripts/fleet-host-prep.sh` and `tests/test_fleet_host_prep.py`. Never edit, stage, restore or commit those two files; they may show as modified in `git status` for the whole run.
- Tests and commands never touch the real `HOME` (`~/agents`, `~/.local`, `~/.config`, `~/Library/LaunchAgents`) and never run `launchctl` or `systemctl` for real. Never run `init-fleet`, `join` or `install` by hand against the real `HOME` while executing this plan. Rollout is human-run after Task 10.
- Every pytest run first prints a `pytest_asyncio` `PytestDeprecationWarning` about `asyncio_default_fixture_loop_scope`; it is expected and is not a failure. Durations in expected outputs vary; only the counts matter. macOS has no `timeout` command; do not use it.
- Every code block in this plan is copied exactly, byte for byte. An "Edit" replaces one block of old text, which occurs exactly once in the file, with the new text; "base lines" are the line numbers of the old text in the file as it is at the start of that task (later edits of the same task do not shift them, because each edit is located by its old text). An "Append" adds two empty lines after the file's current last line, then the block. Never retype a block from the spec when this plan shows it.
- Commit hygiene: the working tree has unrelated untracked paths (`../.DS_Store`, `../.claude/`, `../agent/__pycache__/`, `../bin/`) and the concurrent plan's two files; never stage them. Stage only the paths each task names, check `git diff --cached --name-only` before each commit, and end every commit message with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Pre-tested: every task was implemented from this plan's text in a scratch copy of `3366d49`; each RED and GREEN result below is the one observed there, on this Mac, with both interpreters.

## Review Focus

These five input classes are implied by the spec, are the ones most likely to hit a real user first, and no MT test exercises them. Each is pinned by a test in its owning task.

1. **A shell that already exports `QWEN_AGENT_DAEMON_URL`** (another agent's port, a leftover from debugging, or garbage) runs an agent's command. Expected: the wrapper's own `http://127.0.0.1:<port>` wins, so the command always reaches the agent it was installed for. Test: `test_multi_agent_focus_1_wrapper_overrides_an_inherited_daemon_url` (Task 5).
2. **A prompt with shell metacharacters through the wrapper** (`*`, `$HOME`, quotes, a backslash, a newline, an empty argument). Expected: every argument reaches `bin/qwen-agent` byte for byte, none expanded, split or dropped. Test: `test_multi_agent_focus_2_wrapper_passes_shell_metacharacters_verbatim` (Task 5).
3. **`QWEN_AGENT_HOST_ID` with a stray space or newline** (a plist, unit or shell typo). Expected: exit 2 with `qwen-agentd: invalid QWEN_AGENT_HOST_ID '<value>'`, and nothing is created under `~/agents`. Test: `test_multi_agent_focus_3_host_id_with_stray_whitespace_is_rejected` (Task 4).
4. **A mistyped `--agent-id`** (`Mac-Local`, `../mac-local`, `mac-local/x`) on `join` or `init-fleet`. Expected: exit 2 with `qwen-agentd: invalid --agent-id '<value>'` before the hidden prompt asks for the secret, and nothing is created anywhere. Test: `test_multi_agent_focus_4_mistyped_agent_id_never_prompts` (Task 4).
5. **`join --from-agent X` when X's `fleet.env` was copied around and is now mode 0644.** Expected: exit 2 with F21's `must be mode 0600 (chmod 600 ...)` hint, nothing written for the target agent, and no part of the token printed. Test: `test_multi_agent_focus_5_from_agent_with_a_loose_secret_file` (Task 6).

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `fleet_lib.py` | Modify (Tasks 2-5) | Adds the agent-ID section at the end of the file: `_check_agent_id`, `launchd_label`, `systemd_unit`, `command_path`, `default_command_path`, `agent_ids_on_disk`, `resolve_agent`, `default_beacon_targets`, `agent_port`, the wrapper functions and the two action rules. `deploy_root`, `fleet_env_path` and `log_dir` take `host_id`; `write_fleet_env` is atomic; `DEPLOY_ROOT`, `SYSTEMD_UNIT` and `import sys` are gone. |
| `bin/qwen-agentd` | Modify (Tasks 4, 6-9) | Reads the agent identity before logging; every path is the agent's own; `--agent-id`/`--host-id` on `init-fleet`, `join`, `status`, `install`; `join --from-agent`; `install --default` writes wrappers; `status` resolves the port; `run`'s beacon flags default from the registry. |
| `bin/qwen-agentd-launch` | Modify (Task 4) | Docstring only (M34). |
| `tests/fleet_testutil.py` | Modify (Tasks 4, 9) | `make_fleet(home, host_id, ...)`, `daemon_log_dir(home, host_id)`, `read_log(home, host_id)`; `start_daemon` omits a beacon flag passed as `None`. |
| `tests/test_fleet_lib.py` | Modify (Tasks 2-5) | MT1-MT7 and Review Focus 1-2; T25 and T29a migrated. Still the gate's selftest. |
| `tests/test_fleet_integration.py` | Modify (Tasks 4, 6, 8, 9) | MT10-MT13 and Review Focus 3-5; ten tests migrated. |
| `tests/test_fleet_self_update.py` | Modify (Tasks 4, 7, 8) | MT20-MT24; six tests migrated. |

Inside `fleet_lib.py`, every new function goes in one new last section, `# Multi-agent hosts: ...`, appended by Tasks 2, 3 and 5 in that order. Inside `bin/qwen-agentd`, new helpers sit next to the command that uses them: `_join_from_agent` and `_save_join` after `cmd_join`, `_run_identity` before `cmd_run`, `_status_agent` and `_status_port` before `cmd_status`, `_add_agent_id` before `_build_parser`.

The suite stays green after every task. Two behaviors are transitional on purpose: after Task 4, `install` still writes the old `~/.local/bin/qwen-agent` symlink (now into `~/agents/<id>/current`) until Task 7 replaces it with wrappers, so T61 is migrated twice; and `status --port` keeps its 8190 default, and `run`'s beacon flags keep theirs, until Tasks 8 and 9.

---

### Task 1: Baseline record (orchestrator; no code, no commit)

Implements MT40's "before any change" half. Nothing is written into the repository.

**Files:**
- Create (outside git, excluded by `.git/info/exclude`, never staged): `/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-multi-agent/baseline-pytest.txt`.

**Interfaces:** Consumes nothing. Produces the baseline file Task 10 compares against.

- [ ] **Step 1: Confirm the starting point.**

```bash
cd /Users/reubenpatterson/local_agent_harness/qwen-agent-workspace
git log -1 --format=%h        # expected: 3366d49 (or a later commit that only touched docs/ or the fleet-host-prep files)
git status --short            # expected: only ?? ../.DS_Store, ?? ../.claude/, ?? ../agent/__pycache__/, ?? ../bin/, and possibly M on scripts/fleet-host-prep.sh and tests/test_fleet_host_prep.py
grep -c "def deploy_root():" fleet_lib.py   # expected: 1
ls ~/agents 2>&1 | head -1    # expected: "No such file or directory" (T25 then skips)
```

- [ ] **Step 2: Record the pytest baseline (about 5 min).**

```bash
mkdir -p /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-multi-agent
python3 -m pytest tests/ -q -rA -p no:cacheprovider > /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-multi-agent/baseline-pytest.txt 2>&1
tail -1 /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-multi-agent/baseline-pytest.txt
grep -E '^(FAILED|ERROR|SKIPPED)' /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-multi-agent/baseline-pytest.txt
```

Expected last line: `1 failed, 1027 passed, 1 skipped, 274 warnings in ...`; the `FAILED` line is exactly `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike`, and the `SKIPPED` line is `tests/test_fleet_lib.py:270: no fleet.env on this host`. If the concurrent fleet-host-prep plan has changed `tests/test_fleet_host_prep.py`, the passed count can differ: write the actual counts into `baseline-notes.txt` in the same directory and continue. Task 10 compares against what was recorded here, not against these numbers.

- [ ] **Step 3: Record the fleet suites alone (about 4 min).**

```bash
for f in test_fleet_lib test_fleet_integration test_fleet_self_update test_qwen_agent_fleet; do
  printf '%s: ' "$f"; python3 -m pytest tests/$f.py -q -p no:cacheprovider 2>&1 | tail -1
done
```

Expected: `test_fleet_lib: 38 passed, 1 skipped`, `test_fleet_integration: 27 passed`, `test_fleet_self_update: 8 passed`, `test_qwen_agent_fleet: 10 passed`.

---

### Task 2: fleet_lib agent IDs, service and command names, agent resolution

Implements M2 (`_check_agent_id`, `AGENTS_DIR`), M6 (`launchd_label`, `systemd_unit`, `SYSTEMD_UNIT_FMT`), M8, M21, M22, and the constants `LOGS_SUBDIR` and `FLEET_ENV_NAME` used by Task 4. Purely additive: `DEPLOY_ROOT` and `SYSTEMD_UNIT` stay until Task 4. Tests MT1 (names half, `test_mt1a_*`) and MT6.

**Files:**
- Modify: `fleet_lib.py` — one edit (base lines 69-70) and one appended section.
- Test: `tests/test_fleet_lib.py` — one appended block.

**Interfaces:**
- Consumes: `fleet_lib.HOST_ID_RE`, `fleet_lib.LAUNCHD_LABEL` (existing).
- Produces in `fleet_lib`: constants `AGENTS_DIR = "~/agents"`, `LOGS_SUBDIR = "logs"`, `FLEET_ENV_NAME = "fleet.env"`, `SYSTEMD_UNIT_FMT = "qwen-agentd-%s.service"`, `BIN_DIR = "~/.local/bin"`, `COMMAND_NAME = "qwen-agent"`; `_check_agent_id(host_id) -> None` (raises `ValueError("invalid agent id %r")` unless `host_id` is a `str` that fullmatches `HOST_ID_RE`); `launchd_label(host_id) -> str`; `systemd_unit(host_id) -> str`; `command_path(host_id) -> str`; `default_command_path() -> str`; `agent_ids_on_disk() -> list of str`; `resolve_agent(explicit) -> (host_id or None, message or None)`. In `tests/test_fleet_lib.py`: the module constant `BAD_AGENT_IDS` (used again by Tasks 4 and 5).

- [ ] **Step 1: Write the failing tests.**

Append to the end of `tests/test_fleet_lib.py`, after exactly two empty lines (the file ends with a newline, so add two more newlines, then this block, which ends with a newline):

```python
# --- multi-agent hosts: agent IDs, names, resolution (multi-agent spec M2, M6, M8, M21, M22) ---

BAD_AGENT_IDS = ("", "Mac", "../x", "a/b", "mac-local\n", None)


def test_mt1a_service_and_command_names(monkeypatch):
    monkeypatch.setenv("HOME", "/h")
    assert fleet_lib.launchd_label("mac-local") == "com.qwen-agent.qwen-agentd.mac-local"
    assert fleet_lib.systemd_unit("ollama-168") == "qwen-agentd-ollama-168.service"
    assert fleet_lib.command_path("mac-local") == "/h/.local/bin/qwen-agent-mac-local"
    assert fleet_lib.default_command_path() == "/h/.local/bin/qwen-agent"
    for bad in BAD_AGENT_IDS:
        for func in (fleet_lib.launchd_label, fleet_lib.systemd_unit, fleet_lib.command_path):
            with pytest.raises(ValueError):
                func(bad)


def test_mt6_agent_ids_on_disk_and_resolve_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    agents = tmp_path / "agents"
    assert fleet_lib.agent_ids_on_disk() == []
    assert fleet_lib.resolve_agent(None) == (
        None, "qwen-agentd: no agent found in %s; pass --agent-id ID" % agents)
    (agents / "alpha").mkdir(parents=True)
    (agents / "alpha" / "fleet.env").write_text("x")
    assert fleet_lib.agent_ids_on_disk() == ["alpha"]
    assert fleet_lib.resolve_agent(None) == ("alpha", None)
    (agents / "bravo").mkdir()
    (agents / "bravo" / "current").symlink_to("releases/v2026.01.01")
    (agents / "Bad_Name").mkdir()
    (agents / "Bad_Name" / "fleet.env").write_text("x")
    (agents / "empty").mkdir()
    (agents / "file").write_text("x")
    (agents / "notes").mkdir()
    (agents / "notes" / "readme").write_text("x")
    assert fleet_lib.agent_ids_on_disk() == ["alpha", "bravo"]
    assert fleet_lib.resolve_agent(None) == (
        None, "qwen-agentd: more than one agent in %s (alpha, bravo); pass --agent-id ID" % agents)
    assert fleet_lib.resolve_agent("zed") == ("zed", None)
    assert fleet_lib.resolve_agent("Bad") == (None, "qwen-agentd: invalid --agent-id 'Bad'")
```

- [ ] **Step 2: Run them to verify they fail.**

Run: `python3 -m pytest tests/test_fleet_lib.py::test_mt1a_service_and_command_names tests/test_fleet_lib.py::test_mt6_agent_ids_on_disk_and_resolve_agent -q -p no:cacheprovider`
Expected: `2 failed`, with `AttributeError: module 'fleet_lib' has no attribute 'launchd_label'` and `... 'agent_ids_on_disk'`.

- [ ] **Step 3: Add the constants.** In `fleet_lib.py`:

Edit 1 of 1 in `fleet_lib.py` (base lines 69-70). Replace:

```python
LAUNCHD_LABEL = "com.qwen-agent.qwen-agentd"
SYSTEMD_UNIT = "qwen-agentd.service"
```

with:

```python
LAUNCHD_LABEL = "com.qwen-agent.qwen-agentd"
SYSTEMD_UNIT = "qwen-agentd.service"
AGENTS_DIR = "~/agents"                     # A(<id>) = ~/agents/<id>, expanded at every use (multi-agent spec M2)
LOGS_SUBDIR = "logs"                        # A(<id>)/logs (multi-agent spec M5)
FLEET_ENV_NAME = "fleet.env"                # A(<id>)/fleet.env (multi-agent spec M4)
SYSTEMD_UNIT_FMT = "qwen-agentd-%s.service" # systemd_unit(<id>) (multi-agent spec M6)
BIN_DIR = "~/.local/bin"                    # where the agent commands live (multi-agent spec M8)
COMMAND_NAME = "qwen-agent"                 # ~/.local/bin/qwen-agent and qwen-agent-<id> (multi-agent spec M8)
```

- [ ] **Step 4: Add the functions.**

Append to the end of `fleet_lib.py`, after exactly two empty lines (the file ends with a newline, so add two more newlines, then this block, which ends with a newline):

```python
# ---------------------------------------------------------------------------
# Multi-agent hosts: agent IDs, service names, commands and agent resolution
# (docs/superpowers/specs/2026-10-17-fleet-multi-agent-hosts-design.md)
# ---------------------------------------------------------------------------

def _check_agent_id(host_id):
    """ValueError unless host_id is a valid agent ID; no path is built from a bad one (multi-agent spec M2)."""
    if not isinstance(host_id, str) or not HOST_ID_RE.fullmatch(host_id):
        raise ValueError("invalid agent id %r" % (host_id,))


def launchd_label(host_id):
    """com.qwen-agent.qwen-agentd.<id>, this agent's LaunchAgent label (multi-agent spec M6)."""
    _check_agent_id(host_id)
    return LAUNCHD_LABEL + "." + host_id


def systemd_unit(host_id):
    """qwen-agentd-<id>.service, this agent's systemd user unit (multi-agent spec M6)."""
    _check_agent_id(host_id)
    return SYSTEMD_UNIT_FMT % host_id


def command_path(host_id):
    """~/.local/bin/qwen-agent-<id>, this agent's command (multi-agent spec M8)."""
    _check_agent_id(host_id)
    return os.path.join(os.path.expanduser(BIN_DIR), COMMAND_NAME + "-" + host_id)


def default_command_path():
    """~/.local/bin/qwen-agent, the default agent's command (multi-agent spec M8)."""
    return os.path.join(os.path.expanduser(BIN_DIR), COMMAND_NAME)


def agent_ids_on_disk():
    """Sorted IDs of the directories in ~/agents that hold fleet.env or current (multi-agent spec M21)."""
    root = os.path.expanduser(AGENTS_DIR)
    try:
        names = os.listdir(root)
    except OSError:
        return []
    found = []
    for name in names:
        path = os.path.join(root, name)
        if (HOST_ID_RE.fullmatch(name) and os.path.isdir(path)
                and (os.path.lexists(os.path.join(path, FLEET_ENV_NAME))
                     or os.path.lexists(os.path.join(path, "current")))):
            found.append(name)
    return sorted(found)


def resolve_agent(explicit):
    """(host_id, None) or (None, stderr message) for an optional --agent-id (multi-agent spec M22)."""
    if explicit is not None:
        if isinstance(explicit, str) and HOST_ID_RE.fullmatch(explicit):
            return explicit, None
        return None, "qwen-agentd: invalid --agent-id '%s'" % (explicit,)
    root = os.path.expanduser(AGENTS_DIR)
    ids = agent_ids_on_disk()
    if len(ids) == 1:
        return ids[0], None
    if not ids:
        return None, "qwen-agentd: no agent found in %s; pass --agent-id ID" % root
    return None, "qwen-agentd: more than one agent in %s (%s); pass --agent-id ID" % (root, ", ".join(ids))
```

- [ ] **Step 5: Run the tests to verify they pass, then the whole file and both compilers.**

```bash
python3 -m pytest tests/test_fleet_lib.py::test_mt1a_service_and_command_names tests/test_fleet_lib.py::test_mt6_agent_ids_on_disk_and_resolve_agent -q -p no:cacheprovider
python3 -m pytest tests/test_fleet_lib.py -q -p no:cacheprovider
/usr/bin/python3 -m py_compile fleet_lib.py && python3 -m py_compile fleet_lib.py && echo compile-ok
```

Expected: `2 passed`; `40 passed, 1 skipped`; `compile-ok`.

- [ ] **Step 6: Commit.**

```bash
git add fleet_lib.py tests/test_fleet_lib.py
git diff --cached --name-only   # expected: qwen-agent-workspace/fleet_lib.py, qwen-agent-workspace/tests/test_fleet_lib.py
git commit -q -F - <<'EOF'
fleet_lib: agent IDs, service and command names, agent resolution (multi-agent M2, M6, M8, M21, M22)

MT1 (names), MT6.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 3: fleet_lib registry port range, default beacon targets, agent_port, atomic fleet.env

Implements M7 (`MIN_PORT`, the 1024..65535 rule and its message), M16's `default_beacon_targets` and `BROADCAST_ADDR`, M24 (`agent_port`), and M4's atomic `write_fleet_env` (same signature and F20 contract). M19's duplicate rule is unchanged and only pinned. Tests MT4, MT5, MT7; T5 must keep passing.

**Files:**
- Modify: `fleet_lib.py` — three edits (base lines 76, 167-169, 248-257) and one appended block.
- Test: `tests/test_fleet_lib.py` — one appended block.

**Interfaces:**
- Consumes (Task 2): the `COMMAND_NAME` constant line as the anchor for the new constants.
- Produces in `fleet_lib`: `MIN_PORT = 1024`, `BROADCAST_ADDR = "255.255.255.255"`; `default_beacon_targets(registry) -> list of (str, int)`, ascending by port, one per distinct `port` (default 8190) over every host; `agent_port(fleets_dir, host_id) -> (int or None, sorted list of str)`; `write_fleet_env(path, fleet_id, token)` (unchanged signature; now writes `<path>.tmp` and hard-links it, raising `FileExistsError` when `path` exists).

- [ ] **Step 1: Write the failing tests.**

Append to the end of `tests/test_fleet_lib.py`, after exactly two empty lines (the file ends with a newline, so add two more newlines, then this block, which ends with a newline):

```python
# --- multi-agent hosts: registry ports, beacon targets, agent_port, fleet.env (M4, M7, M16, M19, M24) ---

def test_mt4_port_range_and_duplicate_address(monkeypatch):
    reg = _f18_registry()
    reg["hosts"]["mac-local"]["port"] = 1023
    errors = fleet_lib.validate_registry(reg, TEST_FLEET_ID)
    assert len(errors) == 1 and errors[0].startswith("hosts.mac-local.port: must be an integer in 1024..65535")
    for good in (1024, 65535):
        reg["hosts"]["mac-local"]["port"] = good
        assert fleet_lib.validate_registry(reg, TEST_FLEET_ID) == []

    def agent(port):
        return {"role": "agent", "address": "192.168.1.185", "port": port,
                "model_server": {"type": "vllm", "url": "http://127.0.0.1:8000/v1"},
                "model": "m", "skills": []}
    two = {"protocol": 1, "fleet_id": TEST_FLEET_ID,
           "hosts": {"vision-185": agent(8190), "gemma-185": agent(8190)}}
    assert fleet_lib.validate_registry(two, TEST_FLEET_ID) == [
        "hosts.vision-185: address 192.168.1.185:8190 is already used by hosts.gemma-185"]
    two["hosts"]["gemma-185"]["port"] = 8191
    assert fleet_lib.validate_registry(two, TEST_FLEET_ID) == []


def test_mt5_default_beacon_targets(tmp_path):
    assert fleet_lib.default_beacon_targets(_f18_registry()) == [("255.255.255.255", 8190)]
    reg = _f18_registry()
    reg["hosts"]["mac-local"]["port"] = 9000
    reg["hosts"]["ollama-168"]["port"] = 8191
    reg["hosts"]["gemma-185"] = dict(reg["hosts"]["ollama-168"], address="192.168.1.185", port=8190)
    reg["hosts"]["orchestrator"]["port"] = 8190
    expected = [("255.255.255.255", 8190), ("255.255.255.255", 8191), ("255.255.255.255", 9000)]
    assert fleet_lib.default_beacon_targets(reg) == expected
    reg["hosts"]["orchestrator"]["port"] = 9100
    with_orchestrator = expected + [("255.255.255.255", 9100)]
    assert fleet_lib.default_beacon_targets(reg) == with_orchestrator
    loaded = fleet_lib.load_registry(_write_json(tmp_path / "r.json", reg), TEST_FLEET_ID)
    assert fleet_lib.default_beacon_targets(loaded) == with_orchestrator
    raw = _f18_registry()
    loaded = fleet_lib.load_registry(_write_json(tmp_path / "f18.json", raw), TEST_FLEET_ID)
    assert fleet_lib.default_beacon_targets(loaded) == fleet_lib.default_beacon_targets(raw)


def test_mt7_agent_port_and_atomic_fleet_env(tmp_path):
    fleets = tmp_path / "fleets"
    assert fleet_lib.agent_port(str(fleets), "h1") == (None, [])
    fleets.mkdir()
    assert fleet_lib.agent_port(str(fleets), "h1") == (None, [])

    def registry(fleet_id, port):
        host = {"role": "agent", "address": "127.0.0.1", "model_server": {"type": "vllm",
                "url": "http://127.0.0.1:9/v1"}, "model": "m", "skills": []}
        if port is not None:
            host["port"] = port
        return {"protocol": 1, "fleet_id": fleet_id, "hosts": {"h1": host}}
    _write_json(fleets / "a.json", registry(TEST_FLEET_ID, 9001))
    assert fleet_lib.agent_port(str(fleets), "h1") == (9001, ["a.json"])
    assert fleet_lib.agent_port(str(fleets), "h2") == (None, [])
    _write_json(fleets / "a.json", registry(TEST_FLEET_ID, None))
    assert fleet_lib.agent_port(str(fleets), "h1") == (8190, ["a.json"])
    _write_json(fleets / "a.json", registry(TEST_FLEET_ID, 9001))
    _write_json(fleets / "b.json", registry("fedcba9876543210", 9001))
    assert fleet_lib.agent_port(str(fleets), "h1") == (9001, ["a.json", "b.json"])
    _write_json(fleets / "b.json", registry("fedcba9876543210", 9002))
    assert fleet_lib.agent_port(str(fleets), "h1") == (None, ["a.json", "b.json"])
    _write_json(fleets / "b.json", registry("fedcba9876543210", 9001))
    (fleets / "bad.json").write_text("{not json")
    invalid = registry(TEST_FLEET_ID, 9005)
    invalid["protocol"] = 2
    _write_json(fleets / "invalid.json", invalid)
    (fleets / "notes.txt").write_text(json.dumps(registry(TEST_FLEET_ID, 9006)))
    assert fleet_lib.agent_port(str(fleets), "h1") == (9001, ["a.json", "b.json"])

    path = str(tmp_path / "agents" / "h1" / "fleet.env")
    os.makedirs(os.path.dirname(path))
    with open(path + ".tmp", "w") as f:
        f.write("leftover")
    fleet_lib.write_fleet_env(path, TEST_FLEET_ID, TEST_TOKEN)
    assert not os.path.lexists(path + ".tmp")
    assert stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert fleet_lib.load_fleet_env(path) == (TEST_FLEET_ID, TEST_TOKEN)
    with open(path, "rb") as f:
        before = f.read()
    with pytest.raises(FileExistsError):
        fleet_lib.write_fleet_env(path, "fedcba9876543210", OTHER_TOKEN)
    with open(path, "rb") as f:
        assert f.read() == before
    assert not os.path.lexists(path + ".tmp")
```

- [ ] **Step 2: Run them to verify they fail.**

Run: `python3 -m pytest tests/test_fleet_lib.py::test_mt4_port_range_and_duplicate_address tests/test_fleet_lib.py::test_mt5_default_beacon_targets tests/test_fleet_lib.py::test_mt7_agent_port_and_atomic_fleet_env tests/test_fleet_lib.py::test_t5_fleet_env_write_load_and_modes -q -p no:cacheprovider`
Expected: `3 failed, 1 passed` (T5 passes before and after): MT4 fails on `assert (0 == 1)` (port 1023 is still valid), MT5 and MT7 on `AttributeError` (`default_beacon_targets`, `agent_port`).

- [ ] **Step 3: Implement the in-place changes.** In `fleet_lib.py`:

Edit 1 of 3 in `fleet_lib.py` (base line 76). Replace:

```python
COMMAND_NAME = "qwen-agent"                 # ~/.local/bin/qwen-agent and qwen-agent-<id> (multi-agent spec M8)
```

with:

```python
COMMAND_NAME = "qwen-agent"                 # ~/.local/bin/qwen-agent and qwen-agent-<id> (multi-agent spec M8)
MIN_PORT = 1024                             # lowest registry port (multi-agent spec M7)
BROADCAST_ADDR = "255.255.255.255"          # the default beacon target address (multi-agent spec M16)
```

Edit 2 of 3 in `fleet_lib.py` (base lines 167-169). Replace:

```python
        port_ok = _is_int(port) and 1 <= port <= 65535
        if not port_ok:
            errors.append("%s.port: must be an integer in 1..65535" % loc)
```

with:

```python
        port_ok = _is_int(port) and MIN_PORT <= port <= 65535
        if not port_ok:
            errors.append("%s.port: must be an integer in %d..65535" % (loc, MIN_PORT))
```

Edit 3 of 3 in `fleet_lib.py` (base lines 248-257). Replace:

```python
def write_fleet_env(path, fleet_id, token):
    """Create fleet.env (dir 0700, file 0600). An existing file raises FileExistsError (F20)."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    os.chmod(directory, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write("%s=%s\n%s=%s\n" % (FLEET_ENV_KEYS[0], fleet_id, FLEET_ENV_KEYS[1], token))
        f.flush()
        os.fsync(f.fileno())
```

with:

```python
def write_fleet_env(path, fleet_id, token):
    """Create fleet.env atomically (dir 0700, file 0600) through <path>.tmp and os.link.

    An existing path raises FileExistsError and is never replaced (F20, multi-agent spec M4).
    """
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    os.chmod(directory, 0o700)
    tmp = path + ".tmp"
    if os.path.lexists(tmp):
        os.unlink(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write("%s=%s\n%s=%s\n" % (FLEET_ENV_KEYS[0], fleet_id, FLEET_ENV_KEYS[1], token))
        f.flush()
        os.fsync(f.fileno())
    try:
        os.link(tmp, path)
    finally:
        os.unlink(tmp)
```

- [ ] **Step 4: Add the two functions.**

Append to the end of `fleet_lib.py`, after exactly two empty lines (the file ends with a newline, so add two more newlines, then this block, which ends with a newline):

```python
def default_beacon_targets(registry):
    """One broadcast target per distinct registry port, ascending (multi-agent spec M16)."""
    ports = set(h.get("port", DEFAULT_PORT) for h in registry["hosts"].values())
    return [(BROADCAST_ADDR, p) for p in sorted(ports)]


def agent_port(fleets_dir, host_id):
    """(port or None, files): host_id's port in the valid registries of fleets_dir (multi-agent spec M24).

    files lists, sorted, every *.json in fleets_dir that parses, passes validate_registry
    against its own fleet_id, and has host_id in hosts. port is None unless all of them
    agree. Unreadable files are skipped; a missing directory gives (None, []).
    """
    try:
        names = sorted(os.listdir(fleets_dir))
    except OSError:
        return None, []
    files = []
    ports = set()
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(fleets_dir, name), "r", encoding="utf-8") as f:
                obj = json.loads(f.read())
        except (OSError, ValueError, RecursionError):
            continue
        if not (isinstance(obj, dict) and isinstance(obj.get("hosts"), dict) and host_id in obj["hosts"]
                and validate_registry(obj, obj.get("fleet_id")) == []):
            continue
        files.append(name)
        ports.add(obj["hosts"][host_id].get("port", DEFAULT_PORT))
    if len(ports) == 1:
        return ports.pop(), files
    return None, files
```

- [ ] **Step 5: Run the tests to verify they pass, then the whole file and both compilers.**

```bash
python3 -m pytest tests/test_fleet_lib.py::test_mt4_port_range_and_duplicate_address tests/test_fleet_lib.py::test_mt5_default_beacon_targets tests/test_fleet_lib.py::test_mt7_agent_port_and_atomic_fleet_env tests/test_fleet_lib.py::test_t5_fleet_env_write_load_and_modes -q -p no:cacheprovider
python3 -m pytest tests/test_fleet_lib.py -q -p no:cacheprovider
/usr/bin/python3 -m py_compile fleet_lib.py && python3 -m py_compile fleet_lib.py && echo compile-ok
```

Expected: `4 passed`; `43 passed, 1 skipped` (T2's port cases `0`, `65536` and `True` still report `hosts.mac-local.port: ...`); `compile-ok`.

- [ ] **Step 6: Commit.**

```bash
git add fleet_lib.py tests/test_fleet_lib.py
git diff --cached --name-only   # expected: qwen-agent-workspace/fleet_lib.py, qwen-agent-workspace/tests/test_fleet_lib.py
git commit -q -F - <<'EOF'
fleet_lib: registry port range, default beacon targets, agent_port, atomic fleet.env (multi-agent M4, M7, M16, M19, M24)

MT4, MT5, MT7.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 4: The per-agent root ~/agents/<id> and every caller; run identity before logging; --agent-id

Implements M2-M5 (`deploy_root`, `fleet_env_path`, `log_dir` take `host_id`; `DEPLOY_ROOT`, `SYSTEMD_UNIT` and `import sys` removed), M6 (per-agent plist label, plist path, unit name and commands), M23's `--agent-id`/`--host-id` flag on `init-fleet`, `join`, `status` (optional) and `install` (required), M27, M28, M30 step 3 (which agent's update state `status` prints), M31 (startup order and messages), M32 (per-agent internals), M34 (launcher docstring), the `install` and `status` help strings of M37, and M26's `next:` line. Tests MT1 (paths half, `test_mt1b_*`), MT11, MT12 (d)-(f), MT13 (a)-(c), (f), (g), MT23, Review Focus 3 and 4, and the migration of all 18 test functions of spec 5.6 plus the helpers `_single`, `_deploy`, `_setup` and `Fleet`.

`install`'s command writing is unchanged in this task (it still writes the `~/.local/bin/qwen-agent` symlink, now into `~/agents/<id>/current`); Task 7 replaces it. `status --port` keeps its 8190 default until Task 8, and `run`'s beacon flags keep theirs until Task 9.

**Files:**
- Modify: `fleet_lib.py` — four edits (base lines 21-23, 67-70, 245-247, 854-863).
- Modify: `bin/qwen-agentd` — 25 edits (base lines 69-70, 86-87, 91-93, 133-135, 365-366, 383-385, 391-419, 482, 751, 875-876, 893-901, 924-925, 944-946, 1034-1035, 1076, 1117-1124, 1129-1134, 1142-1147, 1166, 1192, 1214, 1222-1224, 1258, 1313-1320, 1331-1335).
- Modify: `bin/qwen-agentd-launch` — one edit (base line 4).
- Modify: `tests/fleet_testutil.py` — four edits (base lines 82-84, 183-191, 203-204, 376-377).
- Test: `tests/test_fleet_lib.py` — three edits (base lines 267-270, 275-276, 1067-1070) and one appended block.
- Test: `tests/test_fleet_integration.py` — 14 edits (base lines 45-46, 55-58, 66-78, 85-86, 117-119, 174, 198-210, 234-235, 242-243, 380, 417-419, 438, 508, 715) and one appended block.
- Test: `tests/test_fleet_self_update.py` — 11 edits (base lines 115-116, 131-133, 145, 149-150, 162, 169, 173-190, 283-284, 329-330, 349, 373).

**Interfaces:**
- Consumes (Tasks 2, 3): `fleet_lib._check_agent_id`, `AGENTS_DIR`, `LOGS_SUBDIR`, `FLEET_ENV_NAME`, `launchd_label`, `systemd_unit`, `agent_ids_on_disk`, `resolve_agent`; `BAD_AGENT_IDS` in `tests/test_fleet_lib.py`.
- Produces in `fleet_lib`: `deploy_root(host_id) -> "~/agents/<id>" expanded`, `fleet_env_path(host_id) -> A/fleet.env`, `log_dir(host_id) -> A/logs` (all raise `ValueError` for a bad ID).
- Produces in `bin/qwen-agentd`: `setup_logging(host_id)`; `Daemon(args, beacon_targets, beacon_port, scale, t0, host_id, fleet_id, key)` with `self.host_id`, `self.fleet_id`, `self.key` set in `__init__`; `_run_identity() -> (host_id, fleet_id, key)` (raises `StartupError`); `_status_agent(explicit, view) -> host_id or None`; `_add_agent_id(p, required=False)`; `args.agent_id` on `init-fleet`, `join`, `status`, `install`; `install_service(py, d, host_id)` (same signature, per-agent names). `cmd_install` keeps the local name `host_id = args.agent_id` (Task 7 uses it).
- Produces in `tests/fleet_testutil.py`: `make_fleet(home, host_id, fleet_id=TEST_FLEET_ID, token=TEST_TOKEN)`, `daemon_log_dir(home, host_id)`, `read_log(home, host_id)`. In `tests/test_fleet_integration.py`: `_identity_registry(tmp_path)`.

- [ ] **Step 1: Change the test helpers.** In `tests/fleet_testutil.py`:

Edit 1 of 4 in `tests/fleet_testutil.py` (base lines 82-84). Replace:

```python
def make_fleet(home, fleet_id=TEST_FLEET_ID, token=TEST_TOKEN):
    """Write <home>/.config/qwen-agent/fleet.env; returns its path."""
    path = os.path.join(str(home), ".config", "qwen-agent", "fleet.env")
```

with:

```python
def make_fleet(home, host_id, fleet_id=TEST_FLEET_ID, token=TEST_TOKEN):
    """Write <home>/agents/<host_id>/fleet.env; returns its path."""
    path = os.path.join(str(home), "agents", host_id, "fleet.env")
```

Edit 2 of 4 in `tests/fleet_testutil.py` (base lines 183-191). Replace:

```python
def daemon_log_dir(home):
    """fleet_lib.log_dir() as it resolves under HOME=home."""
    if sys.platform == "darwin":
        return os.path.join(str(home), "Library", "Logs", "qwen-agentd")
    return os.path.join(str(home), ".local", "state", "qwen-agentd")


def read_log(home):
    path = os.path.join(daemon_log_dir(home), "qwen-agentd.log")
```

with:

```python
def daemon_log_dir(home, host_id):
    """fleet_lib.log_dir(host_id) as it resolves under HOME=home: <home>/agents/<host_id>/logs."""
    return os.path.join(str(home), "agents", host_id, "logs")


def read_log(home, host_id):
    path = os.path.join(daemon_log_dir(home, host_id), "qwen-agentd.log")
```

Edit 3 of 4 in `tests/fleet_testutil.py` (base lines 203-204). Replace:

```python
    def log(self):
        return read_log(self.home)
```

with:

```python
    def log(self):
        return read_log(self.home, self.host_id)
```

Edit 4 of 4 in `tests/fleet_testutil.py` (base lines 376-377). Replace:

```python
            make_fleet(home)
            self.homes[name] = home
```

with:

```python
            make_fleet(home, name)
            self.homes[name] = home
```

- [ ] **Step 2: Migrate T25 and T29a and add MT1's paths half.** In `tests/test_fleet_lib.py`:

Edit 1 of 3 in `tests/test_fleet_lib.py` (base lines 267-270). Replace:

```python
def test_t25_token_not_in_git_tree():
    path = fleet_lib.fleet_env_path()
    if not os.path.exists(path):
        pytest.skip("no fleet.env on this host")
```

with:

```python
def test_t25_token_not_in_git_tree():
    paths = [fleet_lib.fleet_env_path(i) for i in fleet_lib.agent_ids_on_disk()]
    paths = [p for p in paths if os.path.exists(p)]
    if not paths:
        pytest.skip("no fleet.env on this host")
```

Edit 2 of 3 in `tests/test_fleet_lib.py` (base lines 275-276). Replace:

```python
    _fleet_id, token = fleet_lib.load_fleet_env(path)
    needles = (token.encode("ascii"), fleet_lib.token_key(token))
```

with:

```python
    needles = []
    for path in paths:
        _fleet_id, token = fleet_lib.load_fleet_env(path)
        needles.extend((token.encode("ascii"), fleet_lib.token_key(token)))
```

Edit 3 of 3 in `tests/test_fleet_lib.py` (base lines 1067-1070). Replace:

```python
    assert fleet_lib.deploy_root() == os.path.expanduser("~/.local/share/qwen-agent")
    expected_logs = ("~/Library/Logs/qwen-agentd" if sys.platform == "darwin"
                     else "~/.local/state/qwen-agentd")
    assert fleet_lib.log_dir() == os.path.expanduser(expected_logs)
```

with:

```python
    assert fleet_lib.deploy_root("x") == os.path.expanduser("~/agents/x")
    assert fleet_lib.log_dir("x") == os.path.expanduser("~/agents/x/logs")
```

Append to the end of `tests/test_fleet_lib.py`, after exactly two empty lines (the file ends with a newline, so add two more newlines, then this block, which ends with a newline):

```python
def test_mt1b_agent_root_paths(monkeypatch):
    monkeypatch.setenv("HOME", "/h")
    assert fleet_lib.deploy_root("mac-local") == "/h/agents/mac-local"
    assert fleet_lib.fleet_env_path("mac-local") == "/h/agents/mac-local/fleet.env"
    assert fleet_lib.log_dir("mac-local") == "/h/agents/mac-local/logs"
    for bad in BAD_AGENT_IDS:
        for func in (fleet_lib.deploy_root, fleet_lib.fleet_env_path, fleet_lib.log_dir):
            with pytest.raises(ValueError):
                func(bad)
    assert not hasattr(fleet_lib, "DEPLOY_ROOT")
    assert not hasattr(fleet_lib, "SYSTEMD_UNIT")
```

- [ ] **Step 3: Migrate the integration tests.** In `tests/test_fleet_integration.py` (Edits 1-4: the CLI tests take `--agent-id alpha`; 5: `_single`; 6: `test_run_endpoints_and_peers_view`; 7-9: `test_run_startup_errors`, whose final log assertion is deleted because M31 no longer logs the unset-ID error; 10-14: T45, own-beacon echo, zulu, T48, T46):

Edit 1 of 14 in `tests/test_fleet_integration.py` (base lines 45-46). Replace:

```python
def test_cli_init_fleet(agentd, capsys):
    assert agentd.main(["init-fleet"]) == 0
```

with:

```python
def test_cli_init_fleet(agentd, capsys):
    assert agentd.main(["init-fleet", "--agent-id", "alpha"]) == 0
```

Edit 2 of 14 in `tests/test_fleet_integration.py` (base lines 55-58). Replace:

```python
    path = fleet_lib.fleet_env_path()
    assert fleet_lib.parse_join_string(out[2]) == fleet_lib.load_fleet_env(path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert agentd.main(["init-fleet"]) == 2
```

with:

```python
    path = fleet_lib.fleet_env_path("alpha")
    assert fleet_lib.parse_join_string(out[2]) == fleet_lib.load_fleet_env(path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert agentd.main(["init-fleet", "--agent-id", "alpha"]) == 2
```

Edit 3 of 14 in `tests/test_fleet_integration.py` (base lines 66-78). Replace:

```python
    assert agentd.main(["join", "not-a-join-string"]) == 2
    assert capsys.readouterr().err == "qwen-agentd: invalid join string\n"
    prompts = []
    monkeypatch.setattr(agentd.getpass, "getpass", lambda prompt: prompts.append(prompt) or s + "\n")
    assert agentd.main(["join"]) == 0
    assert prompts == ["join string: "]
    assert capsys.readouterr().out == "qwen-agentd: joined fleet %s\n" % ftu.TEST_FLEET_ID
    path = fleet_lib.fleet_env_path()
    assert fleet_lib.load_fleet_env(path) == (ftu.TEST_FLEET_ID, ftu.TEST_TOKEN)
    assert agentd.main(["join", s]) == 0
    assert capsys.readouterr().out == "qwen-agentd: already joined fleet %s\n" % ftu.TEST_FLEET_ID
    other = fleet_lib.make_join_string(ftu.OTHER_FLEET_ID, ftu.OTHER_TOKEN)
    assert agentd.main(["join", other]) == 2
```

with:

```python
    assert agentd.main(["join", "--agent-id", "alpha", "not-a-join-string"]) == 2
    assert capsys.readouterr().err == "qwen-agentd: invalid join string\n"
    prompts = []
    monkeypatch.setattr(agentd.getpass, "getpass", lambda prompt: prompts.append(prompt) or s + "\n")
    assert agentd.main(["join", "--agent-id", "alpha"]) == 0
    assert prompts == ["join string: "]
    assert capsys.readouterr().out == "qwen-agentd: joined fleet %s\n" % ftu.TEST_FLEET_ID
    path = fleet_lib.fleet_env_path("alpha")
    assert fleet_lib.load_fleet_env(path) == (ftu.TEST_FLEET_ID, ftu.TEST_TOKEN)
    assert agentd.main(["join", "--agent-id", "alpha", s]) == 0
    assert capsys.readouterr().out == "qwen-agentd: already joined fleet %s\n" % ftu.TEST_FLEET_ID
    other = fleet_lib.make_join_string(ftu.OTHER_FLEET_ID, ftu.OTHER_TOKEN)
    assert agentd.main(["join", "--agent-id", "alpha", other]) == 2
```

Edit 4 of 14 in `tests/test_fleet_integration.py` (base lines 85-86). Replace:

```python
    monkeypatch.setattr(agentd.fleet_lib, "write_fleet_env", boom)
    assert agentd.main(["init-fleet"]) == 1
```

with:

```python
    monkeypatch.setattr(agentd.fleet_lib, "write_fleet_env", boom)
    assert agentd.main(["init-fleet", "--agent-id", "alpha"]) == 1
```

Edit 5 of 14 in `tests/test_fleet_integration.py` (base lines 117-119). Replace:

```python
    home = tmp_path / "alpha"
    home.mkdir()
    ftu.make_fleet(home)
```

with:

```python
    home = tmp_path / "alpha"
    home.mkdir()
    ftu.make_fleet(home, "alpha")
```

Edit 6 of 14 in `tests/test_fleet_integration.py` (base line 174). Replace:

```python
    log_dir = ftu.daemon_log_dir(daemon.home)
```

with:

```python
    log_dir = ftu.daemon_log_dir(daemon.home, "alpha")
```

Edit 7 of 14 in `tests/test_fleet_integration.py` (base lines 198-210). Replace:

```python
    env_path = os.path.join(str(home), ".config", "qwen-agent", "fleet.env")

    proc = _run_agentd(home, base, {"QWEN_AGENT_HOST_ID": "alpha"})
    assert proc.returncode == 2
    assert proc.stderr == ("qwen-agentd: %s not found; run qwen-agentd init-fleet or qwen-agentd join\n"
                           % env_path)
    ftu.make_fleet(home)

    proc = _run_agentd(home, base)
    assert proc.returncode == 2
    assert proc.stderr == "qwen-agentd: QWEN_AGENT_HOST_ID is not set; valid IDs: alpha, bravo\n"

    proc = _run_agentd(home, base, {"QWEN_AGENT_HOST_ID": "charlie"})
```

with:

```python
    env_path = os.path.join(str(home), "agents", "alpha", "fleet.env")

    proc = _run_agentd(home, base, {"QWEN_AGENT_HOST_ID": "alpha"})
    assert proc.returncode == 2
    assert proc.stderr == ("qwen-agentd: %s not found; run qwen-agentd init-fleet --agent-id alpha or "
                           "qwen-agentd join --agent-id alpha\n" % env_path)
    ftu.make_fleet(home, "alpha")

    proc = _run_agentd(home, base)
    assert proc.returncode == 2
    assert proc.stderr == "qwen-agentd: QWEN_AGENT_HOST_ID is not set; agents on this machine: alpha\n"

    ftu.make_fleet(home, "charlie")
    proc = _run_agentd(home, base, {"QWEN_AGENT_HOST_ID": "charlie"})
```

Edit 8 of 14 in `tests/test_fleet_integration.py` (base lines 234-235). Replace:

```python
    first = ftu.start_daemon(home, "alpha", registry, ftu.free_port(), "none")
    proc = _run_agentd(home, base, {"QWEN_AGENT_HOST_ID": "alpha"})
```

with:

```python
    first = ftu.start_daemon(home, "alpha", registry, ftu.free_port(), "none")
    ftu.make_fleet(home, "bravo")
    proc = _run_agentd(home, base, {"QWEN_AGENT_HOST_ID": "alpha"})
```

Edit 9 of 14 in `tests/test_fleet_integration.py` (base lines 242-243). Replace:

```python
    assert "Traceback" not in first.log()
    assert "ERROR MainThread qwen-agentd: QWEN_AGENT_HOST_ID is not set" in ftu.read_log(home)
```

with:

```python
    assert "Traceback" not in first.log()
```

Edit 10 of 14 in `tests/test_fleet_integration.py` (base line 380). Replace:

```python
    ftu.make_fleet(echo_home, ftu.OTHER_FLEET_ID, ftu.OTHER_TOKEN)
```

with:

```python
    ftu.make_fleet(echo_home, "echo", ftu.OTHER_FLEET_ID, ftu.OTHER_TOKEN)
```

Edit 11 of 14 in `tests/test_fleet_integration.py` (base lines 417-419). Replace:

```python
    home = tmp_path / "solo"
    home.mkdir()
    ftu.make_fleet(home)
```

with:

```python
    home = tmp_path / "solo"
    home.mkdir()
    ftu.make_fleet(home, "solo")
```

Edit 12 of 14 in `tests/test_fleet_integration.py` (base line 438). Replace:

```python
    ftu.make_fleet(zulu_home)
```

with:

```python
    ftu.make_fleet(zulu_home, "zulu")
```

Edit 13 of 14 in `tests/test_fleet_integration.py` (base line 508). Replace:

```python
    stderr_path = os.path.join(ftu.daemon_log_dir(fleet.homes["bravo"]), "last-run.stderr")
```

with:

```python
    stderr_path = os.path.join(ftu.daemon_log_dir(fleet.homes["bravo"], "bravo"), "last-run.stderr")
```

Edit 14 of 14 in `tests/test_fleet_integration.py` (base line 715). Replace:

```python
        log_dir = ftu.daemon_log_dir(fleet.homes[name])
```

with:

```python
        log_dir = ftu.daemon_log_dir(fleet.homes[name], name)
```

- [ ] **Step 4: Add MT11, MT13 (a-c, f, g), MT12 (d-f) and Review Focus 3 and 4.**

Append to the end of `tests/test_fleet_integration.py`, after exactly two empty lines (the file ends with a newline, so add two more newlines, then this block, which ends with a newline):

```python
# --- multi-agent hosts: run identity, init-fleet/join resolution, status agent (M22, M27, M28, M30, M31) ---

def _identity_registry(tmp_path):
    return ftu.write_registry(tmp_path / "id-registry.json", ftu.TEST_FLEET_ID, {
        "alpha": {"port": ftu.free_port(), "model_server": {"type": "vllm", "url": "http://127.0.0.1:9/v1"},
                  "model": "m", "skills": []}})


def test_mt11_run_identity_errors_before_logging(tmp_path):
    registry = _identity_registry(tmp_path)
    base = ["run", "--registry", registry, "--beacon-targets", "none", "--beacon-port", str(ftu.free_port())]
    empty = tmp_path / "empty"
    empty.mkdir()
    proc = _run_agentd(empty, base)
    assert (proc.returncode, proc.stderr) == (
        2, "qwen-agentd: QWEN_AGENT_HOST_ID is not set; agents on this machine: none\n")
    assert not os.path.lexists(str(empty / "agents"))
    home = tmp_path / "home"
    home.mkdir()
    ftu.make_fleet(home, "alpha")
    proc = _run_agentd(home, base)
    assert (proc.returncode, proc.stderr) == (
        2, "qwen-agentd: QWEN_AGENT_HOST_ID is not set; agents on this machine: alpha\n")
    proc = _run_agentd(home, base, {"QWEN_AGENT_HOST_ID": "Bad_Id"})
    assert (proc.returncode, proc.stderr) == (2, "qwen-agentd: invalid QWEN_AGENT_HOST_ID 'Bad_Id'\n")
    charlie = home / "agents" / "charlie"
    proc = _run_agentd(home, base, {"QWEN_AGENT_HOST_ID": "charlie"})
    assert (proc.returncode, proc.stderr) == (
        2, "qwen-agentd: %s not found; run qwen-agentd init-fleet --agent-id charlie or "
           "qwen-agentd join --agent-id charlie\n" % (charlie / "fleet.env"))
    assert not os.path.lexists(str(charlie))
    ftu.make_fleet(home, "charlie")
    proc = _run_agentd(home, base, {"QWEN_AGENT_HOST_ID": "charlie"})
    message = "qwen-agentd: host_id 'charlie' is not in the fleet registry; valid IDs: alpha"
    assert (proc.returncode, proc.stderr) == (2, message + "\n")
    assert "ERROR MainThread " + message in ftu.read_log(home, "charlie")


def test_multi_agent_focus_3_host_id_with_stray_whitespace_is_rejected(tmp_path):
    """Multi-agent Review Focus 3: QWEN_AGENT_HOST_ID with a stray space or newline (a plist, unit or
    shell typo) is refused by name, and nothing is created under ~/agents."""
    registry = _identity_registry(tmp_path)
    base = ["run", "--registry", registry, "--beacon-targets", "none", "--beacon-port", str(ftu.free_port())]
    home = tmp_path / "home"
    home.mkdir()
    ftu.make_fleet(home, "alpha")
    for value in ("alpha ", "alpha\n", " alpha"):
        proc = _run_agentd(home, base, {"QWEN_AGENT_HOST_ID": value})
        assert (proc.returncode, proc.stderr) == (2, "qwen-agentd: invalid QWEN_AGENT_HOST_ID '%s'\n" % value)
    assert os.listdir(str(home / "agents")) == ["alpha"]
    assert os.listdir(str(home / "agents" / "alpha")) == ["fleet.env"]


def test_mt13_init_fleet_and_join_resolve_the_agent(agentd, capsys, monkeypatch, tmp_path):
    agents = tmp_path / "home" / "agents"
    assert agentd.main(["init-fleet"]) == 2
    assert capsys.readouterr() == ("", "qwen-agentd: no agent found in %s; pass --agent-id ID\n" % agents)
    assert agentd.main(["init-fleet", "--agent-id", "alpha"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 4 and out[0].startswith("fleet_id: ")
    assert stat.S_IMODE(os.stat(str(agents / "alpha")).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(fleet_lib.fleet_env_path("alpha")).st_mode) == 0o600
    assert agentd.main(["init-fleet"]) == 2
    assert capsys.readouterr().err == ("qwen-agentd: %s already exists; remove it first to create a new fleet\n"
                                       % fleet_lib.fleet_env_path("alpha"))
    ftu.make_fleet(tmp_path / "home", "bravo")

    def no_prompt(prompt):
        raise AssertionError("join prompted for the secret")
    monkeypatch.setattr(agentd.getpass, "getpass", no_prompt)
    assert agentd.main(["join"]) == 2
    assert capsys.readouterr() == (
        "", "qwen-agentd: more than one agent in %s (alpha, bravo); pass --agent-id ID\n" % agents)
    s = fleet_lib.make_join_string(ftu.TEST_FLEET_ID, ftu.TEST_TOKEN)
    assert agentd.main(["join", "--host-id", "erin", s]) == 0
    assert capsys.readouterr() == ("qwen-agentd: joined fleet %s\n" % ftu.TEST_FLEET_ID, "")
    assert fleet_lib.load_fleet_env(fleet_lib.fleet_env_path("erin")) == (ftu.TEST_FLEET_ID, ftu.TEST_TOKEN)


def test_multi_agent_focus_4_mistyped_agent_id_never_prompts(agentd, capsys, monkeypatch, tmp_path):
    """Multi-agent Review Focus 4: a mistyped --agent-id (an upper-case letter, a path) on join or
    init-fleet is refused before the hidden prompt asks for the secret, and nothing is
    created under ~/agents."""
    prompts = []
    monkeypatch.setattr(agentd.getpass, "getpass", lambda prompt: prompts.append(prompt) or "")
    for bad in ("Mac-Local", "../mac-local", "mac-local/x"):
        for argv in (["join", "--agent-id", bad], ["init-fleet", "--agent-id", bad]):
            assert agentd.main(argv) == 2
            assert capsys.readouterr() == ("", "qwen-agentd: invalid --agent-id '%s'\n" % bad)
    assert prompts == []
    assert not os.path.lexists(str(tmp_path / "home" / "agents"))
    assert not os.path.lexists(str(tmp_path / "mac-local"))


def test_mt12_status_update_line_agent(tmp_path):
    daemon, _stub, _registry = _single(tmp_path)
    ftu.make_fleet(daemon.home, "bravo")
    proc = _run_agentd(daemon.home, ["status", "--port", str(daemon.port)])
    assert proc.returncode == 0 and proc.stdout.splitlines()[-1] == "update: not installed"
    fleet_lib.write_state(os.path.join(str(daemon.home), "agents", "alpha", "update-state.json"),
                          {"from": None, "to": "v2026.01.01", "status": "ok", "attempts": 0, "bad_tags": []})
    installed = "update: status=ok from=- to=v2026.01.01 attempts=0 bad_tags=-"
    proc = _run_agentd(daemon.home, ["status", "--port", str(daemon.port)])
    assert proc.returncode == 0 and proc.stdout.splitlines()[-1] == installed
    proc = _run_agentd(daemon.home, ["status", "--agent-id", "alpha", "--port", str(daemon.port)])
    assert proc.returncode == 0 and proc.stdout.splitlines()[-1] == installed
    proc = _run_agentd(daemon.home, ["status", "--agent-id", "Bad", "--port", str(daemon.port)])
    assert (proc.returncode, proc.stdout, proc.stderr) == (2, "", "qwen-agentd: invalid --agent-id 'Bad'\n")
    daemon.kill()
    proc = _run_agentd(daemon.home, ["status", "--port", str(daemon.port)])
    assert proc.returncode == 1
    assert proc.stdout == "daemon: not reachable at %s\nupdate: not installed\n" % daemon.url
```

- [ ] **Step 5: Migrate the self-update tests and add MT23.** In `tests/test_fleet_self_update.py` (Edit 7 replaces `test_service_definitions`' body with MT23's first half and adds `test_mt23_install_service_is_per_agent` after it):

Edit 1 of 11 in `tests/test_fleet_self_update.py` (base lines 115-116). Replace:

```python
def _deploy(home):
    return os.path.join(str(home), ".local", "share", "qwen-agent")
```

with:

```python
def _deploy(home):
    return os.path.join(str(home), "agents", "h1")
```

Edit 2 of 11 in `tests/test_fleet_self_update.py` (base lines 131-133). Replace:

```python
    assert proc.stdout == ("installed v2026.01.01 at %s\n"
                           "next: run %s/current/qwen-agent-workspace/bin/qwen-agentd join (or init-fleet); "
                           "the service retries every 10 s\n" % (d, d))
```

with:

```python
    assert proc.stdout == ("installed v2026.01.01 at %s\n"
                           "next: run %s/current/qwen-agent-workspace/bin/qwen-agentd join --agent-id h1 "
                           "(or init-fleet --agent-id h1); the service retries every 10 s\n" % (d, d))
```

Edit 3 of 11 in `tests/test_fleet_self_update.py` (base line 145). Replace:

```python
    assert os.path.exists(os.path.join(ftu.daemon_log_dir(home), "gate-v2026.01.01.log"))
```

with:

```python
    assert os.path.exists(os.path.join(ftu.daemon_log_dir(home, "h1"), "gate-v2026.01.01.log"))
```

Edit 4 of 11 in `tests/test_fleet_self_update.py` (base lines 149-150). Replace:

```python
    ftu.make_fleet(home, ftu.TEST_FLEET_ID, secrets.token_hex(32))
    proc = _install(home, origin)
```

with:

```python
    ftu.make_fleet(home, "h1", ftu.TEST_FLEET_ID, secrets.token_hex(32))
    proc = _install(home, origin)
```

Edit 5 of 11 in `tests/test_fleet_self_update.py` (base line 162). Replace:

```python
    assert (proc.returncode, proc.stderr) == (2, "qwen-agentd: invalid --host-id 'Mac_Local'\n")
```

with:

```python
    assert (proc.returncode, proc.stderr) == (2, "qwen-agentd: invalid --agent-id 'Mac_Local'\n")
```

Edit 6 of 11 in `tests/test_fleet_self_update.py` (base line 169). Replace:

```python
                           % os.path.join(ftu.daemon_log_dir(home), "gate-v2026.01.01.log"))
```

with:

```python
                           % os.path.join(ftu.daemon_log_dir(home, "h1"), "gate-v2026.01.01.log"))
```

Edit 7 of 11 in `tests/test_fleet_self_update.py` (base lines 173-190). Replace:

```python
def test_service_definitions():
    agentd = ftu.load_script("qwen_agentd_services", ftu.AGENTD)
    plist = agentd.launchd_plist_dict("/usr/bin/python3", "/h/.local/share/qwen-agent", "mac-local",
                                      "/h/Library/Logs/qwen-agentd")
    assert plist == {
        "Label": "com.qwen-agent.qwen-agentd",
        "ProgramArguments": ["/usr/bin/python3", "/h/.local/share/qwen-agent/qwen-agentd-launch"],
        "EnvironmentVariables": {"QWEN_AGENT_HOST_ID": "mac-local",
                                 "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
        "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10,
        "StandardOutPath": "/h/Library/Logs/qwen-agentd/launchd.out",
        "StandardErrorPath": "/h/Library/Logs/qwen-agentd/launchd.err"}
    assert plistlib.loads(plistlib.dumps(plist)) == plist
    assert agentd.systemd_unit_text("/usr/bin/python3", "/home/u/.local/share/qwen-agent", "ollama-168") == (
        "[Unit]\nDescription=qwen-agent fleet daemon\nStartLimitIntervalSec=0\n\n"
        "[Service]\nExecStart=/usr/bin/python3 /home/u/.local/share/qwen-agent/qwen-agentd-launch\n"
        "Environment=QWEN_AGENT_HOST_ID=ollama-168\nRestart=always\nRestartSec=10\n\n"
        "[Install]\nWantedBy=default.target\n")
```

with:

```python
def test_service_definitions():
    agentd = ftu.load_script("qwen_agentd_services", ftu.AGENTD)
    plist = agentd.launchd_plist_dict("/usr/bin/python3", "/h/agents/mac-local", "mac-local",
                                      "/h/agents/mac-local/logs")
    assert plist == {
        "Label": "com.qwen-agent.qwen-agentd.mac-local",
        "ProgramArguments": ["/usr/bin/python3", "/h/agents/mac-local/qwen-agentd-launch"],
        "EnvironmentVariables": {"QWEN_AGENT_HOST_ID": "mac-local",
                                 "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
        "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10,
        "StandardOutPath": "/h/agents/mac-local/logs/launchd.out",
        "StandardErrorPath": "/h/agents/mac-local/logs/launchd.err"}
    assert plistlib.loads(plistlib.dumps(plist)) == plist
    assert agentd.systemd_unit_text("/usr/bin/python3", "/home/u/agents/ollama-168", "ollama-168") == (
        "[Unit]\nDescription=qwen-agent fleet daemon\nStartLimitIntervalSec=0\n\n"
        "[Service]\nExecStart=/usr/bin/python3 /home/u/agents/ollama-168/qwen-agentd-launch\n"
        "Environment=QWEN_AGENT_HOST_ID=ollama-168\nRestart=always\nRestartSec=10\n\n"
        "[Install]\nWantedBy=default.target\n")


def test_mt23_install_service_is_per_agent(tmp_path, monkeypatch):
    """MT23: two agents in one HOME get two plists or two units, each loaded under its own name.
    subprocess.run is recorded, so no real launchctl or systemctl ever runs."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    agentd = ftu.load_script("qwen_agentd_mt23", ftu.AGENTD)
    calls = []

    def record(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(agentd.subprocess, "run", record)
    py = "/usr/bin/python3"
    monkeypatch.setattr(agentd.sys, "platform", "darwin")
    domain = "gui/%d" % os.getuid()
    expected = []
    for x in ("a", "b"):
        ok, path = agentd.install_service(py, fleet_lib.deploy_root(x), x)
        assert ok and path == os.path.join(str(home), "Library", "LaunchAgents",
                                           "com.qwen-agent.qwen-agentd.%s.plist" % x)
        with open(path, "rb") as f:
            plist = plistlib.loads(f.read())
        assert plist["Label"] == "com.qwen-agent.qwen-agentd." + x
        assert plist["EnvironmentVariables"]["QWEN_AGENT_HOST_ID"] == x
        assert plist["StandardErrorPath"] == os.path.join(fleet_lib.log_dir(x), "launchd.err")
        expected += [["launchctl", "bootout", "%s/com.qwen-agent.qwen-agentd.%s" % (domain, x)],
                     ["launchctl", "bootstrap", domain, path]]
    assert calls == expected
    del calls[:]
    monkeypatch.setattr(agentd.sys, "platform", "linux")
    expected = []
    for x in ("a", "b"):
        ok, path = agentd.install_service(py, fleet_lib.deploy_root(x), x)
        unit = "qwen-agentd-%s.service" % x
        assert ok and path == os.path.join(str(home), ".config", "systemd", "user", unit)
        with open(path, encoding="utf-8") as f:
            assert f.read() == agentd.systemd_unit_text(py, fleet_lib.deploy_root(x), x)
        expected += [["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", unit],
                     ["systemctl", "--user", "restart", unit]]
    assert calls == expected
```

Edit 8 of 11 in `tests/test_fleet_self_update.py` (base lines 283-284). Replace:

```python
    token = secrets.token_hex(32)
    ftu.make_fleet(home, ftu.TEST_FLEET_ID, token)
```

with:

```python
    token = secrets.token_hex(32)
    ftu.make_fleet(home, "h1", ftu.TEST_FLEET_ID, token)
```

Edit 9 of 11 in `tests/test_fleet_self_update.py` (base lines 329-330). Replace:

```python
        log = ftu.read_log(home)
        assert "update: switching v2026.01.01 -> v2026.01.02" in log
```

with:

```python
        log = ftu.read_log(home, "h1")
        assert "update: switching v2026.01.01 -> v2026.01.02" in log
```

Edit 10 of 11 in `tests/test_fleet_self_update.py` (base line 349). Replace:

```python
                "tracked files; not updating") in ftu.read_log(home)
```

with:

```python
                "tracked files; not updating") in ftu.read_log(home, "h1")
```

Edit 11 of 11 in `tests/test_fleet_self_update.py` (base line 373). Replace:

```python
        assert "INFO updater update: v2026.01.02 deferred: a run is in flight" in ftu.read_log(home)
```

with:

```python
        assert "INFO updater update: v2026.01.02 deferred: a run is in flight" in ftu.read_log(home, "h1")
```

- [ ] **Step 6: Run the new and migrated tests to verify they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider \
  tests/test_fleet_lib.py::test_t25_token_not_in_git_tree \
  tests/test_fleet_lib.py::test_t29a_state_io_prune_and_version \
  tests/test_fleet_lib.py::test_mt1b_agent_root_paths \
  tests/test_fleet_integration.py::test_cli_init_fleet \
  tests/test_fleet_integration.py::test_cli_join \
  tests/test_fleet_integration.py::test_cli_internal_error_is_one_line \
  tests/test_fleet_integration.py::test_run_startup_errors \
  tests/test_fleet_integration.py::test_mt11_run_identity_errors_before_logging \
  tests/test_fleet_integration.py::test_multi_agent_focus_3_host_id_with_stray_whitespace_is_rejected \
  tests/test_fleet_integration.py::test_mt13_init_fleet_and_join_resolve_the_agent \
  tests/test_fleet_integration.py::test_multi_agent_focus_4_mistyped_agent_id_never_prompts \
  tests/test_fleet_integration.py::test_mt12_status_update_line_agent \
  tests/test_fleet_self_update.py::test_t61_install_layout_and_idempotence \
  tests/test_fleet_self_update.py::test_install_rejects_bad_host_id_and_failing_first_release \
  tests/test_fleet_self_update.py::test_service_definitions \
  tests/test_fleet_self_update.py::test_mt23_install_service_is_per_agent
```

Expected: `15 failed, 1 skipped` (T25 skips before and after: there is no `~/agents` on this Mac). The failures are `TypeError` (`deploy_root()` takes no argument yet), argparse `SystemExit: 2` (no `--agent-id` yet), and wrong messages or paths.

- [ ] **Step 7: Switch the path functions.** In `fleet_lib.py`:

Edit 1 of 4 in `fleet_lib.py` (base lines 21-23). Replace:

```python
import re
import sys
import threading
```

with:

```python
import re
import threading
```

Edit 2 of 4 in `fleet_lib.py` (base lines 67-70). Replace:

```python
DEPLOY_ROOT = "~/.local/share/qwen-agent"   # passed through os.path.expanduser at every use
WS_SUBDIR = "qwen-agent-workspace"          # the workspace directory inside a release worktree
LAUNCHD_LABEL = "com.qwen-agent.qwen-agentd"
SYSTEMD_UNIT = "qwen-agentd.service"
```

with:

```python
WS_SUBDIR = "qwen-agent-workspace"          # the workspace directory inside a release worktree
LAUNCHD_LABEL = "com.qwen-agent.qwen-agentd"   # the base of launchd_label(<id>) (multi-agent spec M6)
```

Edit 3 of 4 in `fleet_lib.py` (base lines 245-247). Replace:

```python
def fleet_env_path():
    """~/.config/qwen-agent/fleet.env, the only place the token is stored (F19)."""
    return os.path.expanduser("~/.config/qwen-agent/fleet.env")
```

with:

```python
def fleet_env_path(host_id):
    """A(<id>)/fleet.env, the only place this agent's token is stored (F19, multi-agent spec M4)."""
    return os.path.join(deploy_root(host_id), FLEET_ENV_NAME)
```

Edit 4 of 4 in `fleet_lib.py` (base lines 854-863). Replace:

```python
def deploy_root():
    """D = ~/.local/share/qwen-agent, the same on every host (F80)."""
    return os.path.expanduser(DEPLOY_ROOT)


def log_dir():
    """The daemon's log directory (F107)."""
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Logs/qwen-agentd")
    return os.path.expanduser("~/.local/state/qwen-agentd")
```

with:

```python
def deploy_root(host_id):
    """A(<id>) = ~/agents/<id>, this agent's root (multi-agent spec M2)."""
    _check_agent_id(host_id)
    return os.path.join(os.path.expanduser(AGENTS_DIR), host_id)


def log_dir(host_id):
    """A(<id>)/logs, this agent's log directory on every platform (F107, multi-agent spec M5)."""
    return os.path.join(deploy_root(host_id), LOGS_SUBDIR)
```

- [ ] **Step 8: Make every caller per-agent.** In `bin/qwen-agentd` (Edits 1-3: `init-fleet` and `join` resolve the agent; 4: `setup_logging`; 5-7: `Daemon` takes the identity and `start` does M31 steps 6-13; 8-10: `_start_threads`, `spawn_run`, `_confirm_switch`; 11: `_run_identity` and `cmd_run`; 12-13: `status`'s update-line agent; 14: `gate_release`; 15-17: the plist label and `install_service`; 18-22: `cmd_install`; 23: `UpdateCtx`; 24-25: the parser):

Edit 1 of 25 in `bin/qwen-agentd` (base lines 69-70). Replace:

```python
def cmd_init_fleet(args):
    path = fleet_lib.fleet_env_path()
```

with:

```python
def cmd_init_fleet(args):
    host_id, message = fleet_lib.resolve_agent(args.agent_id)
    if message is not None:
        _err(message)
        return 2
    path = fleet_lib.fleet_env_path(host_id)
```

Edit 2 of 25 in `bin/qwen-agentd` (base lines 86-87). Replace:

```python
def cmd_join(args):
    raw = args.string if args.string is not None else getpass.getpass("join string: ")
```

with:

```python
def cmd_join(args):
    host_id, message = fleet_lib.resolve_agent(args.agent_id)
    if message is not None:
        _err(message)
        return 2
    raw = args.string if args.string is not None else getpass.getpass("join string: ")
```

Edit 3 of 25 in `bin/qwen-agentd` (base lines 91-93). Replace:

```python
        _err("qwen-agentd: invalid join string")
        return 2
    path = fleet_lib.fleet_env_path()
```

with:

```python
        _err("qwen-agentd: invalid join string")
        return 2
    path = fleet_lib.fleet_env_path(host_id)
```

Edit 4 of 25 in `bin/qwen-agentd` (base lines 133-135). Replace:

```python
def setup_logging():
    """<log_dir>/qwen-agentd.log, 5 MB x 3, INFO (F107, F108). Only `run` logs."""
    directory = fleet_lib.log_dir()
```

with:

```python
def setup_logging(host_id):
    """A(<id>)/logs/qwen-agentd.log, 5 MB x 3, INFO (F107, F108, multi-agent spec M5). Only `run` logs."""
    directory = fleet_lib.log_dir(host_id)
```

Edit 5 of 25 in `bin/qwen-agentd` (base lines 365-366). Replace:

```python
    def __init__(self, args, beacon_targets, beacon_port, scale, t0):
        self.args = args
```

with:

```python
    def __init__(self, args, beacon_targets, beacon_port, scale, t0, host_id, fleet_id, key):
        self.args = args
        self.host_id = host_id
        self.fleet_id = fleet_id
        self.key = key
```

Edit 6 of 25 in `bin/qwen-agentd` (base lines 383-385). Replace:

```python
        self.beacon_ok = True
        self.key = None
        self.httpd = None
```

with:

```python
        self.beacon_ok = True
        self.httpd = None
```

Edit 7 of 25 in `bin/qwen-agentd` (base lines 391-419). Replace:

```python
    # --- startup (F95 steps 4-11) -------------------------------------------------

    def start(self):
        path = fleet_lib.fleet_env_path()
        try:
            fleet_id, token = fleet_lib.load_fleet_env(path)
        except FileNotFoundError:
            raise StartupError("qwen-agentd: %s not found; run qwen-agentd init-fleet or "
                               "qwen-agentd join" % path)
        except fleet_lib.FleetEnvError as e:
            raise StartupError("qwen-agentd: %s" % e)
        self.key = fleet_lib.token_key(token)
        del token
        registry_path = self.args.registry or os.path.join(REPO_ROOT, "fleets", fleet_id + ".json")
        try:
            self.registry = fleet_lib.load_registry(registry_path, fleet_id)
        except fleet_lib.RegistryError as e:
            raise StartupError("qwen-agentd: %s" % e)
        self.host_id = os.environ.get("QWEN_AGENT_HOST_ID", "")
        if self.host_id == "":
            raise StartupError("qwen-agentd: QWEN_AGENT_HOST_ID is not set; valid IDs: %s"
                               % ", ".join(sorted(self.registry["hosts"])))
        try:
            self.entry = fleet_lib.self_entry(self.registry, self.host_id)
        except fleet_lib.RegistryError as e:
            raise StartupError("qwen-agentd: %s" % e)
        self.port = self.entry["port"]
        self.loopback_url = "http://127.0.0.1:%d" % self.port
        self.version = fleet_lib.release_version(REPO_ROOT, fleet_lib.deploy_root())
```

with:

```python
    # --- startup (multi-agent spec M31 steps 6-13) -------------------------------

    def start(self):
        registry_path = self.args.registry or os.path.join(REPO_ROOT, "fleets", self.fleet_id + ".json")
        try:
            self.registry = fleet_lib.load_registry(registry_path, self.fleet_id)
        except fleet_lib.RegistryError as e:
            raise StartupError("qwen-agentd: %s" % e)
        try:
            self.entry = fleet_lib.self_entry(self.registry, self.host_id)
        except fleet_lib.RegistryError as e:
            raise StartupError("qwen-agentd: %s" % e)
        self.port = self.entry["port"]
        self.loopback_url = "http://127.0.0.1:%d" % self.port
        self.version = fleet_lib.release_version(REPO_ROOT, fleet_lib.deploy_root(self.host_id))
```

Edit 8 of 25 in `bin/qwen-agentd` (base line 482). Replace:

```python
        state = fleet_lib.read_state(state_path(fleet_lib.deploy_root()))
```

with:

```python
        state = fleet_lib.read_state(state_path(fleet_lib.deploy_root(self.host_id)))
```

Edit 9 of 25 in `bin/qwen-agentd` (base line 751). Replace:

```python
        err_path = os.path.join(fleet_lib.log_dir(), "last-run.stderr")
```

with:

```python
        err_path = os.path.join(fleet_lib.log_dir(self.host_id), "last-run.stderr")
```

Edit 10 of 25 in `bin/qwen-agentd` (base lines 875-876). Replace:

```python
    def _confirm_switch(self):
        d = fleet_lib.deploy_root()
```

with:

```python
    def _confirm_switch(self):
        d = fleet_lib.deploy_root(self.host_id)
```

Edit 11 of 25 in `bin/qwen-agentd` (base lines 893-901). Replace:

```python
def cmd_run(args):
    t0 = time.monotonic()
    try:
        targets, beacon_port, scale = _validate_run_flags(args)
    except StartupError as e:
        _err(str(e))
        return 2
    setup_logging()
    daemon = Daemon(args, targets, beacon_port, scale, t0)
```

with:

```python
def _run_identity():
    """(host_id, fleet_id, key) from QWEN_AGENT_HOST_ID and its fleet.env (multi-agent spec M31 steps 3-4).

    Runs before logging is set up, so its errors go to stderr only and create nothing on disk.
    """
    host_id = os.environ.get("QWEN_AGENT_HOST_ID", "")
    if host_id == "":
        raise StartupError("qwen-agentd: QWEN_AGENT_HOST_ID is not set; agents on this machine: %s"
                           % (", ".join(fleet_lib.agent_ids_on_disk()) or "none"))
    if not fleet_lib.HOST_ID_RE.fullmatch(host_id):
        raise StartupError("qwen-agentd: invalid QWEN_AGENT_HOST_ID '%s'" % host_id)
    path = fleet_lib.fleet_env_path(host_id)
    try:
        fleet_id, token = fleet_lib.load_fleet_env(path)
    except FileNotFoundError:
        raise StartupError("qwen-agentd: %s not found; run qwen-agentd init-fleet --agent-id %s or "
                           "qwen-agentd join --agent-id %s" % (path, host_id, host_id))
    except fleet_lib.FleetEnvError as e:
        raise StartupError("qwen-agentd: %s" % e)
    key = fleet_lib.token_key(token)
    del token
    return host_id, fleet_id, key


def cmd_run(args):
    """Multi-agent spec M31 steps 1-5; Daemon.start does steps 6-13."""
    t0 = time.monotonic()
    try:
        targets, beacon_port, scale = _validate_run_flags(args)
        host_id, fleet_id, key = _run_identity()
    except StartupError as e:
        _err(str(e))
        return 2
    setup_logging(host_id)
    daemon = Daemon(args, targets, beacon_port, scale, t0, host_id, fleet_id, key)
```

Edit 12 of 25 in `bin/qwen-agentd` (base lines 924-925). Replace:

```python
def cmd_status(args):
    url = "http://127.0.0.1:%d" % args.port
```

with:

```python
def _status_agent(explicit, view):
    """The agent whose update state `status` prints, or None (multi-agent spec M30 step 3).

    The --agent-id flag, else the answering daemon's own host_id, else the single agent on disk.
    """
    if explicit is not None:
        return explicit
    if view is not None:
        host_id = view["self"]["host_id"]
        if fleet_lib.HOST_ID_RE.fullmatch(host_id):
            return host_id
    ids = fleet_lib.agent_ids_on_disk()
    return ids[0] if len(ids) == 1 else None


def cmd_status(args):
    explicit = None
    if args.agent_id is not None:
        explicit, message = fleet_lib.resolve_agent(args.agent_id)
        if message is not None:
            _err(message)
            return 2
    url = "http://127.0.0.1:%d" % args.port
```

Edit 13 of 25 in `bin/qwen-agentd` (base lines 944-946). Replace:

```python
    state_file = os.path.join(fleet_lib.deploy_root(), "update-state.json")
    if not os.path.exists(state_file):
        lines.append("update: not installed")
```

with:

```python
    agent = _status_agent(explicit, view)
    state_file = None if agent is None else state_path(fleet_lib.deploy_root(agent))
    if state_file is None or not os.path.exists(state_file):
        lines.append("update: not installed")
```

Edit 14 of 25 in `bin/qwen-agentd` (base lines 1034-1035). Replace:

```python
    logs = fleet_lib.log_dir()
    os.makedirs(logs, exist_ok=True)
```

with:

```python
    logs = os.path.join(d, fleet_lib.LOGS_SUBDIR)
    os.makedirs(logs, exist_ok=True)
```

Edit 15 of 25 in `bin/qwen-agentd` (base line 1076). Replace:

```python
    return {"Label": fleet_lib.LAUNCHD_LABEL,
```

with:

```python
    return {"Label": fleet_lib.launchd_label(host_id),
```

Edit 16 of 25 in `bin/qwen-agentd` (base lines 1117-1124). Replace:

```python
def install_service(py, d, host_id):
    """Write and load the platform's service -> (ok, service path or error message) (F90)."""
    if sys.platform == "darwin":
        path = os.path.expanduser("~/Library/LaunchAgents/%s.plist" % fleet_lib.LAUNCHD_LABEL)
        _write_file_atomic(path, plistlib.dumps(launchd_plist_dict(py, d, host_id, fleet_lib.log_dir())))
        domain = "gui/%d" % os.getuid()
        subprocess.run(["launchctl", "bootout", "%s/%s" % (domain, fleet_lib.LAUNCHD_LABEL)],
                       capture_output=True)
```

with:

```python
def install_service(py, d, host_id):
    """Write and load this agent's service -> (ok, service path or error message) (F90, multi-agent spec M6)."""
    if sys.platform == "darwin":
        label = fleet_lib.launchd_label(host_id)
        path = os.path.expanduser("~/Library/LaunchAgents/%s.plist" % label)
        _write_file_atomic(path, plistlib.dumps(launchd_plist_dict(py, d, host_id, fleet_lib.log_dir(host_id))))
        domain = "gui/%d" % os.getuid()
        subprocess.run(["launchctl", "bootout", "%s/%s" % (domain, label)], capture_output=True)
```

Edit 17 of 25 in `bin/qwen-agentd` (base lines 1129-1134). Replace:

```python
    if sys.platform.startswith("linux"):
        path = os.path.expanduser("~/.config/systemd/user/%s" % fleet_lib.SYSTEMD_UNIT)
        _write_file_atomic(path, systemd_unit_text(py, d, host_id).encode("utf-8"))
        for cmd in (["systemctl", "--user", "daemon-reload"],
                    ["systemctl", "--user", "enable", fleet_lib.SYSTEMD_UNIT],
                    ["systemctl", "--user", "restart", fleet_lib.SYSTEMD_UNIT]):
```

with:

```python
    if sys.platform.startswith("linux"):
        unit = fleet_lib.systemd_unit(host_id)
        path = os.path.expanduser("~/.config/systemd/user/%s" % unit)
        _write_file_atomic(path, systemd_unit_text(py, d, host_id).encode("utf-8"))
        for cmd in (["systemctl", "--user", "daemon-reload"],
                    ["systemctl", "--user", "enable", unit],
                    ["systemctl", "--user", "restart", unit]):
```

Edit 18 of 25 in `bin/qwen-agentd` (base lines 1142-1147). Replace:

```python
def cmd_install(args):
    """F91, steps 1-11. Idempotent: never re-clones and never changes an existing D/current."""
    d = fleet_lib.deploy_root()
    if not fleet_lib.HOST_ID_RE.fullmatch(args.host_id):
        _err("qwen-agentd: invalid --host-id '%s'" % args.host_id)
        return 2
```

with:

```python
def cmd_install(args):
    """F91 with D = A(<id>) (multi-agent spec M25). Idempotent: never re-clones, never changes D/current."""
    host_id = args.agent_id
    if not fleet_lib.HOST_ID_RE.fullmatch(host_id):
        _err("qwen-agentd: invalid --agent-id '%s'" % host_id)
        return 2
    d = fleet_lib.deploy_root(host_id)
    logs = fleet_lib.log_dir(host_id)
```

Edit 19 of 25 in `bin/qwen-agentd` (base line 1166). Replace:

```python
    for directory in (d, fleet_lib.log_dir()):
```

with:

```python
    for directory in (d, logs):
```

Edit 20 of 25 in `bin/qwen-agentd` (base line 1192). Replace:

```python
                 % (tag, detail, os.path.join(fleet_lib.log_dir(), "gate-%s.log" % tag)))
```

with:

```python
                 % (tag, detail, os.path.join(logs, "gate-%s.log" % tag)))
```

Edit 21 of 25 in `bin/qwen-agentd` (base line 1214). Replace:

```python
        ok, result = install_service(sys.executable, d, args.host_id)
```

with:

```python
        ok, result = install_service(sys.executable, d, host_id)
```

Edit 22 of 25 in `bin/qwen-agentd` (base lines 1222-1224). Replace:

```python
    if not os.path.exists(fleet_lib.fleet_env_path()):
        print("next: run %s/current/qwen-agent-workspace/bin/qwen-agentd join (or init-fleet); "
              "the service retries every 10 s" % d)
```

with:

```python
    if not os.path.exists(fleet_lib.fleet_env_path(host_id)):
        print("next: run %s/current/qwen-agent-workspace/bin/qwen-agentd join --agent-id %s "
              "(or init-fleet --agent-id %s); the service retries every 10 s" % (d, host_id, host_id))
```

Edit 23 of 25 in `bin/qwen-agentd` (base line 1258). Replace:

```python
        self.d = fleet_lib.deploy_root()
```

with:

```python
        self.d = fleet_lib.deploy_root(daemon.host_id)
```

Edit 24 of 25 in `bin/qwen-agentd` (base lines 1313-1320). Replace:

```python
def _build_parser():
    parser = argparse.ArgumentParser(prog="qwen-agentd", description="qwen-agent fleet daemon")
    sub = parser.add_subparsers(dest="command")
    sub.required = True
    p = sub.add_parser("init-fleet", help="create a new fleet and print its join string once")
    p.set_defaults(func=cmd_init_fleet)
    p = sub.add_parser("join", help="join an existing fleet (prompts when STRING is omitted)")
    p.add_argument("string", nargs="?", default=None, metavar="STRING")
```

with:

```python
def _add_agent_id(p, required=False):
    """--agent-id ID with --host-id as an exact alias (multi-agent spec M23)."""
    p.add_argument("--agent-id", "--host-id", dest="agent_id", default=None, metavar="ID", required=required)


def _build_parser():
    parser = argparse.ArgumentParser(prog="qwen-agentd", description="qwen-agent fleet daemon")
    sub = parser.add_subparsers(dest="command")
    sub.required = True
    p = sub.add_parser("init-fleet", help="create a new fleet and print its join string once")
    _add_agent_id(p)
    p.set_defaults(func=cmd_init_fleet)
    p = sub.add_parser("join", help="join an existing fleet (prompts when STRING is omitted)")
    _add_agent_id(p)
    p.add_argument("string", nargs="?", default=None, metavar="STRING")
```

Edit 25 of 25 in `bin/qwen-agentd` (base lines 1331-1335). Replace:

```python
    p = sub.add_parser("status", help="print this host's fleet view and update state")
    p.add_argument("--port", type=int, default=fleet_lib.DEFAULT_PORT)
    p.set_defaults(func=cmd_status)
    p = sub.add_parser("install", help="install this host into ~/.local/share/qwen-agent and its service")
    p.add_argument("--host-id", required=True, metavar="ID")
```

with:

```python
    p = sub.add_parser("status", help="print an agent's fleet view and update state")
    _add_agent_id(p)
    p.add_argument("--port", type=int, default=fleet_lib.DEFAULT_PORT)
    p.set_defaults(func=cmd_status)
    p = sub.add_parser("install", help="install an agent into ~/agents/<id> with its service and commands")
    _add_agent_id(p, required=True)
```

- [ ] **Step 9: Update the launcher docstring (M34).** In `bin/qwen-agentd-launch`:

Edit 1 of 1 in `bin/qwen-agentd-launch` (base line 4). Replace:

```python
install copies this file to ~/.local/share/qwen-agent/qwen-agentd-launch, outside
```

with:

```python
install copies this file to ~/agents/<id>/qwen-agentd-launch, outside
```

- [ ] **Step 10: Run the tests to verify they pass, then every fleet file and both compilers (about 4 min).**

```bash
python3 -m pytest -q -p no:cacheprovider \
  tests/test_fleet_lib.py::test_t25_token_not_in_git_tree \
  tests/test_fleet_lib.py::test_t29a_state_io_prune_and_version \
  tests/test_fleet_lib.py::test_mt1b_agent_root_paths \
  tests/test_fleet_integration.py::test_cli_init_fleet \
  tests/test_fleet_integration.py::test_cli_join \
  tests/test_fleet_integration.py::test_cli_internal_error_is_one_line \
  tests/test_fleet_integration.py::test_run_startup_errors \
  tests/test_fleet_integration.py::test_mt11_run_identity_errors_before_logging \
  tests/test_fleet_integration.py::test_multi_agent_focus_3_host_id_with_stray_whitespace_is_rejected \
  tests/test_fleet_integration.py::test_mt13_init_fleet_and_join_resolve_the_agent \
  tests/test_fleet_integration.py::test_multi_agent_focus_4_mistyped_agent_id_never_prompts \
  tests/test_fleet_integration.py::test_mt12_status_update_line_agent \
  tests/test_fleet_self_update.py::test_t61_install_layout_and_idempotence \
  tests/test_fleet_self_update.py::test_install_rejects_bad_host_id_and_failing_first_release \
  tests/test_fleet_self_update.py::test_service_definitions \
  tests/test_fleet_self_update.py::test_mt23_install_service_is_per_agent
for f in test_fleet_lib test_fleet_integration test_fleet_self_update test_qwen_agent_fleet; do
  printf '%s: ' "$f"; python3 -m pytest tests/$f.py -q -p no:cacheprovider 2>&1 | tail -1
done
/usr/bin/python3 -m py_compile fleet_lib.py bin/qwen-agent bin/qwen-agentd bin/qwen-agentd-launch && python3 -m py_compile fleet_lib.py bin/qwen-agent bin/qwen-agentd bin/qwen-agentd-launch && echo compile-ok
grep -n -E "deploy_root\(\)|log_dir\(\)|fleet_env_path\(\)|SYSTEMD_UNIT\b|DEPLOY_ROOT|args\.host_id" fleet_lib.py bin/qwen-agentd tests/fleet_testutil.py tests/test_fleet_integration.py tests/test_fleet_self_update.py
grep -n -E "deploy_root\(\)|log_dir\(\)|fleet_env_path\(\)" tests/test_fleet_lib.py
```

Expected: `15 passed, 1 skipped`; then `test_fleet_lib: 44 passed, 1 skipped`, `test_fleet_integration: 32 passed`, `test_fleet_self_update: 9 passed`, `test_qwen_agent_fleet: 10 passed`; `compile-ok`; both `grep`s print nothing (`tests/test_fleet_lib.py` names `DEPLOY_ROOT` and `SYSTEMD_UNIT` only inside MT1's `hasattr` checks, so the second grep leaves those two names out).

- [ ] **Step 11: Commit.**

```bash
git add fleet_lib.py bin/qwen-agentd bin/qwen-agentd-launch tests/fleet_testutil.py tests/test_fleet_lib.py tests/test_fleet_integration.py tests/test_fleet_self_update.py
git diff --cached --name-only   # expected: exactly those seven paths, each with the qwen-agent-workspace/ prefix
git commit -q -F - <<'EOF'
qwen-agentd: per-agent root ~/agents/<id>, run identity before logging, --agent-id (multi-agent M2-M6, M23, M27, M28, M30, M31, M32, M34)

MT1 (paths), MT11, MT12 (d-f), MT13 (a-c, f, g), MT23, Review Focus 3-4;
the 18 test functions of spec 5.6 migrated.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 5: fleet_lib generated commands (wrapper bytes, detection, writing, the install rules)

Implements M9, M10, M11, M12 and MT1's `wrapper_bytes` row. Pure functions; nothing calls them until Task 7. Tests MT2, MT3, Review Focus 1 and 2.

**Files:**
- Modify: `fleet_lib.py` — one edit (base line 75) and one appended block.
- Test: `tests/test_fleet_lib.py` — one appended block.

**Interfaces:**
- Consumes (Tasks 2-4): `_check_agent_id`, `deploy_root(host_id)`, `MIN_PORT`, `WS_SUBDIR`, `HOST_ID_RE`, `_is_int`; `BAD_AGENT_IDS` in the test file.
- Produces in `fleet_lib`: `WRAPPER_MARKER = "# qwen-agentd wrapper"`, `WRAPPER_ID_PREFIX = "# agent-id: "`, `WRAPPER_MAX_BYTES = 65536`; `_sh_single_quote(s) -> str`; `wrapper_bytes(host_id, port) -> bytes`; `is_wrapper(data: bytes) -> bool`; `wrapper_agent_id(data: bytes) -> str or None`; `classify_command_path(path) -> (kind, found_id)` with `kind` in `"absent"`, `"symlink"`, `"wrapper"`, `"other"`; `write_wrapper(path, data: bytes)`; `agent_command_action(kind) -> "write" or "refuse"`; `default_command_action(kind, found_id, host_id, make_default) -> "write", "refuse" or "keep"`. In the test file: `_m9_wrapper(home)`, `_fake_release_harness(home, host_id, script)`, `_run_wrapper(tmp_path, data, argv, env_extra=None)`.

- [ ] **Step 1: Write the failing tests.**

Append to the end of `tests/test_fleet_lib.py`, after exactly two empty lines (the file ends with a newline, so add two more newlines, then this block, which ends with a newline):

```python
# --- multi-agent hosts: the generated commands (multi-agent spec M9-M12) ----------------

def _m9_wrapper(home):
    return ("#!/bin/sh\n"
            "# qwen-agentd wrapper\n"
            "# agent-id: mac-local\n"
            "QWEN_AGENT_DAEMON_URL=http://127.0.0.1:8190\n"
            "export QWEN_AGENT_DAEMON_URL\n"
            "exec '%s/agents/mac-local/current/qwen-agent-workspace/bin/qwen-agent' \"$@\"\n" % home).encode("utf-8")


def _fake_release_harness(home, host_id, script):
    """An executable stand-in for A(<id>)/current/qwen-agent-workspace/bin/qwen-agent."""
    target = os.path.join(str(home), "agents", host_id, "current", "qwen-agent-workspace", "bin", "qwen-agent")
    os.makedirs(os.path.dirname(target))
    with open(target, "w") as f:
        f.write(script)
    os.chmod(target, 0o755)


def _run_wrapper(tmp_path, data, argv, env_extra=None):
    w = str(tmp_path / "w")
    with open(w, "wb") as f:
        f.write(data)
    os.chmod(w, 0o755)
    env = dict((k, v) for k, v in os.environ.items() if k != "QWEN_AGENT_DAEMON_URL")
    env.update(env_extra or {})
    return subprocess.run(["/bin/sh", w] + list(argv), env=env, capture_output=True, timeout=30)


def test_mt2_wrapper_bytes_and_detection(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/h")
    data = fleet_lib.wrapper_bytes("mac-local", 8190)
    assert data == _m9_wrapper("/h")
    for bad in BAD_AGENT_IDS:
        with pytest.raises(ValueError):
            fleet_lib.wrapper_bytes(bad, 8190)
    for bad_port in (1023, 65536, True, "8190"):
        with pytest.raises(ValueError):
            fleet_lib.wrapper_bytes("mac-local", bad_port)
    monkeypatch.setenv("HOME", "/h/it's")
    assert fleet_lib.wrapper_bytes("x", 8190).decode("utf-8").splitlines()[-1] == (
        "exec '/h/it'\\''s/agents/x/current/qwen-agent-workspace/bin/qwen-agent' \"$@\"")
    assert fleet_lib.is_wrapper(data) is True
    assert fleet_lib.is_wrapper(b"#!/bin/sh\n# qwen-agentd wrapper\n") is True
    for not_wrapper in (b"# qwen-agentd wrapper extra\n", b"#  qwen-agentd wrapper\n", b""):
        assert fleet_lib.is_wrapper(not_wrapper) is False
    assert fleet_lib.wrapper_agent_id(data) == "mac-local"
    assert fleet_lib.wrapper_agent_id(b"#!/bin/sh\n# qwen-agentd wrapper\n") is None
    assert fleet_lib.wrapper_agent_id(b"# qwen-agentd wrapper\n# agent-id: Bad\n") is None

    monkeypatch.setenv("HOME", str(tmp_path))
    _fake_release_harness(tmp_path, "x", "#!/bin/sh\nprintf '%s;%s;%s' \"$QWEN_AGENT_DAEMON_URL\" \"$1\" \"$2\"\n")
    proc = _run_wrapper(tmp_path, fleet_lib.wrapper_bytes("x", 8191), ["a b", "c"])
    assert (proc.returncode, proc.stdout) == (0, b"http://127.0.0.1:8191;a b;c")


def test_multi_agent_focus_1_wrapper_overrides_an_inherited_daemon_url(tmp_path, monkeypatch):
    """Multi-agent Review Focus 1: a shell that already exports QWEN_AGENT_DAEMON_URL (another agent's port,
    or a leftover from debugging) still reaches the wrapper's own agent."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _fake_release_harness(tmp_path, "x", "#!/bin/sh\nprintf '%s' \"$QWEN_AGENT_DAEMON_URL\"\n")
    for inherited in ("http://127.0.0.1:9999", "", "not a url"):
        proc = _run_wrapper(tmp_path, fleet_lib.wrapper_bytes("x", 8191), [],
                            {"QWEN_AGENT_DAEMON_URL": inherited})
        assert (proc.returncode, proc.stdout) == (0, b"http://127.0.0.1:8191"), inherited


def test_multi_agent_focus_2_wrapper_passes_shell_metacharacters_verbatim(tmp_path, monkeypatch):
    """Multi-agent Review Focus 2: prompts typed through the wrapper keep their exact bytes: globs, $VARS,
    quotes, backslashes, newlines and empty arguments are neither expanded nor dropped."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _fake_release_harness(tmp_path, "x", "#!/bin/sh\nfor a in \"$@\"; do printf '[%s]' \"$a\"; done\n")
    argv = ["*", "$HOME", "what's \"this\"?", "a\\b", "line1\nline2", "", "--user-prompt=x y"]
    proc = _run_wrapper(tmp_path, fleet_lib.wrapper_bytes("x", 8191), argv)
    assert proc.returncode == 0
    assert proc.stdout == "".join("[%s]" % a for a in argv).encode("utf-8")


def test_mt3_classify_write_and_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/h")
    data = fleet_lib.wrapper_bytes("mac-local", 8190)
    path = str(tmp_path / "cmd")
    assert fleet_lib.classify_command_path(path) == ("absent", None)
    os.symlink(str(tmp_path / "nowhere"), path)
    assert fleet_lib.classify_command_path(path) == ("symlink", None)
    os.unlink(path)
    with open(path, "wb") as f:
        f.write(data)
    assert fleet_lib.classify_command_path(path) == ("wrapper", "mac-local")
    with open(path, "wb") as f:
        f.write(b"#!/bin/sh\necho mine\n")
    assert fleet_lib.classify_command_path(path) == ("other", None)
    assert fleet_lib.classify_command_path(str(tmp_path)) == ("other", None)
    big = b"# qwen-agentd wrapper\n"
    with open(path, "wb") as f:
        f.write(big + b"x" * (fleet_lib.WRAPPER_MAX_BYTES + 1 - len(big)))
    assert os.path.getsize(path) == fleet_lib.WRAPPER_MAX_BYTES + 1
    assert fleet_lib.classify_command_path(path) == ("other", None)

    out = str(tmp_path / "bin" / "qwen-agent-x")
    os.makedirs(os.path.dirname(out))
    with open(out + ".tmp", "w") as f:
        f.write("leftover")
    old_umask = os.umask(0o077)
    try:
        fleet_lib.write_wrapper(out, data)
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o755
    assert not os.path.lexists(out + ".tmp")
    with open(out, "rb") as f:
        assert f.read() == data
    target = str(tmp_path / "target")
    with open(target, "w") as f:
        f.write("untouched")
    link = str(tmp_path / "bin" / "qwen-agent")
    os.symlink(target, link)
    fleet_lib.write_wrapper(link, data)
    assert not os.path.islink(link)
    with open(link, "rb") as f:
        assert f.read() == data
    with open(target) as f:
        assert f.read() == "untouched"

    for kind, action in (("absent", "write"), ("symlink", "write"), ("wrapper", "write"), ("other", "refuse")):
        assert fleet_lib.agent_command_action(kind) == action
    rows = [
        (("absent", None, "h1", False), "write"),
        (("absent", None, "h1", True), "write"),
        (("wrapper", "h1", "h1", False), "write"),
        (("wrapper", "h1", "h1", True), "write"),
        (("wrapper", "h2", "h1", True), "write"),
        (("wrapper", None, "h1", True), "write"),
        (("symlink", None, "h1", True), "write"),
        (("other", None, "h1", True), "refuse"),
        (("wrapper", "h2", "h1", False), "keep"),
        (("wrapper", None, "h1", False), "keep"),
        (("symlink", None, "h1", False), "keep"),
        (("other", None, "h1", False), "keep"),
    ]
    for args, action in rows:
        assert fleet_lib.default_command_action(*args) == action, args
```

- [ ] **Step 2: Run them to verify they fail.**

Run: `python3 -m pytest tests/test_fleet_lib.py::test_mt2_wrapper_bytes_and_detection tests/test_fleet_lib.py::test_multi_agent_focus_1_wrapper_overrides_an_inherited_daemon_url tests/test_fleet_lib.py::test_multi_agent_focus_2_wrapper_passes_shell_metacharacters_verbatim tests/test_fleet_lib.py::test_mt3_classify_write_and_actions -q -p no:cacheprovider`
Expected: `4 failed`, each with `AttributeError: module 'fleet_lib' has no attribute 'wrapper_bytes'`.

- [ ] **Step 3: Add the constants.** In `fleet_lib.py`:

Edit 1 of 1 in `fleet_lib.py` (base line 75). Replace:

```python
BROADCAST_ADDR = "255.255.255.255"          # the default beacon target address (multi-agent spec M16)
```

with:

```python
BROADCAST_ADDR = "255.255.255.255"          # the default beacon target address (multi-agent spec M16)
WRAPPER_MARKER = "# qwen-agentd wrapper"    # the line that marks a generated command (multi-agent spec M9)
WRAPPER_ID_PREFIX = "# agent-id: "          # the wrapper line that names its agent (multi-agent spec M9)
WRAPPER_MAX_BYTES = 65536                   # a larger file is never a wrapper (multi-agent spec M10)
```

- [ ] **Step 4: Add the functions.**

Append to the end of `fleet_lib.py`, after exactly two empty lines (the file ends with a newline, so add two more newlines, then this block, which ends with a newline):

```python
def _sh_single_quote(s):
    """s as one POSIX sh single-quoted word, ' written as '\\'' (multi-agent spec M9)."""
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


def is_wrapper(data):
    """True when one whole line of data equals WRAPPER_MARKER (multi-agent spec M10)."""
    return WRAPPER_MARKER.encode("ascii") in data.split(b"\n")


def wrapper_agent_id(data):
    """The agent ID on the first "# agent-id: " line of data, or None (multi-agent spec M10)."""
    prefix = WRAPPER_ID_PREFIX.encode("ascii")
    for line in data.split(b"\n"):
        if line.startswith(prefix):
            try:
                value = line[len(prefix):].decode("ascii")
            except UnicodeDecodeError:
                return None
            return value if HOST_ID_RE.fullmatch(value) else None
    return None


def classify_command_path(path):
    """(kind, found_id): "absent", "symlink", "wrapper" (with its agent ID) or "other" (multi-agent spec M10)."""
    if not os.path.lexists(path):
        return "absent", None
    if os.path.islink(path):
        return "symlink", None
    if os.path.isfile(path):
        try:
            with open(path, "rb") as f:
                data = f.read(WRAPPER_MAX_BYTES + 1)
        except OSError:
            return "other", None
        if len(data) <= WRAPPER_MAX_BYTES and is_wrapper(data):
            return "wrapper", wrapper_agent_id(data)
    return "other", None


def write_wrapper(path, data):
    """Atomically replace path (a symlink itself, never its target) with data, mode 0755 (multi-agent spec M10)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    if os.path.lexists(tmp):
        os.unlink(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o755)
    os.fchmod(fd, 0o755)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def agent_command_action(kind):
    """The action for ~/.local/bin/qwen-agent-<id> of this kind: "write" or "refuse" (multi-agent spec M11)."""
    return "write" if kind in ("absent", "symlink", "wrapper") else "refuse"


def default_command_action(kind, found_id, host_id, make_default):
    """The action for ~/.local/bin/qwen-agent: "write", "refuse" or "keep" (multi-agent spec M12)."""
    if kind == "absent":
        return "write"
    if kind == "wrapper" and found_id == host_id:
        return "write"
    if make_default and kind in ("symlink", "wrapper"):
        return "write"
    if make_default and kind == "other":
        return "refuse"
    return "keep"
```

- [ ] **Step 5: Run the tests to verify they pass, then the whole file and both compilers.**

```bash
python3 -m pytest tests/test_fleet_lib.py::test_mt2_wrapper_bytes_and_detection tests/test_fleet_lib.py::test_multi_agent_focus_1_wrapper_overrides_an_inherited_daemon_url tests/test_fleet_lib.py::test_multi_agent_focus_2_wrapper_passes_shell_metacharacters_verbatim tests/test_fleet_lib.py::test_mt3_classify_write_and_actions -q -p no:cacheprovider
python3 -m pytest tests/test_fleet_lib.py -q -p no:cacheprovider
/usr/bin/python3 -m py_compile fleet_lib.py && python3 -m py_compile fleet_lib.py && echo compile-ok
HOME=/Users/reubenpatterson python3 -c "import fleet_lib, sys; sys.stdout.write(fleet_lib.wrapper_bytes('mac-local', 8190).decode())"
```

Expected: `4 passed`; `48 passed, 1 skipped`; `compile-ok`; the last command prints exactly the six lines of spec M9 (it only computes bytes; it writes nothing):

```sh
#!/bin/sh
# qwen-agentd wrapper
# agent-id: mac-local
QWEN_AGENT_DAEMON_URL=http://127.0.0.1:8190
export QWEN_AGENT_DAEMON_URL
exec '/Users/reubenpatterson/agents/mac-local/current/qwen-agent-workspace/bin/qwen-agent' "$@"
```

- [ ] **Step 6: Commit.**

```bash
git add fleet_lib.py tests/test_fleet_lib.py
git diff --cached --name-only   # expected: qwen-agent-workspace/fleet_lib.py, qwen-agent-workspace/tests/test_fleet_lib.py
git commit -q -F - <<'EOF'
fleet_lib: generated agent commands, detection and the install rules (multi-agent M9-M12)

MT1 (wrapper_bytes), MT2, MT3, Review Focus 1-2.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 6: join --from-agent

Implements M29 and the `join` part of M36: copy another agent's fleet secret on the same machine without printing or prompting for it, with `join`'s never-overwrite policy shared through one helper. Tests MT13 (d), (e) and Review Focus 5.

**Files:**
- Modify: `bin/qwen-agentd` — three edits (base lines 90-102, 112-114, 1372-1373).
- Test: `tests/test_fleet_integration.py` — one appended block.

**Interfaces:**
- Consumes (Tasks 2-4): `fleet_lib.resolve_agent`, `fleet_env_path(host_id)`, `load_fleet_env`, `write_fleet_env`, `HOST_ID_RE`; the `agentd` fixture.
- Produces in `bin/qwen-agentd`: `args.from_agent` (`join --from-agent ID`, default `None`); `_join_from_agent(host_id, source_id, string) -> exit code`; `_save_join(host_id, fleet_id, token, suffix) -> exit code` (used by both `join` forms). In the test file: `_no_token_in(token, *texts) -> bool`.

- [ ] **Step 1: Write the failing tests.**

Append to the end of `tests/test_fleet_integration.py`, after exactly two empty lines (the file ends with a newline, so add two more newlines, then this block, which ends with a newline):

```python
# --- multi-agent hosts: join --from-agent (M29, M36) -------------------------------------

def _no_token_in(token, *texts):
    """True when no text contains the token or any 16-character substring of it."""
    pieces = [token[i:i + 16] for i in range(len(token) - 15)]
    return not any(p in t for t in texts for p in pieces)


def test_mt13_join_from_agent(agentd, capsys, monkeypatch, tmp_path):
    def no_prompt(prompt):
        raise AssertionError("join prompted for the secret")
    monkeypatch.setattr(agentd.getpass, "getpass", no_prompt)
    assert agentd.main(["init-fleet", "--agent-id", "alpha"]) == 0
    capsys.readouterr()
    fid, token = fleet_lib.load_fleet_env(fleet_lib.fleet_env_path("alpha"))
    assert agentd.main(["join", "--agent-id", "bravo", "--from-agent", "alpha"]) == 0
    out, err = capsys.readouterr()
    assert (out, err) == ("qwen-agentd: joined fleet %s (copied from agent alpha)\n" % fid, "")
    assert _no_token_in(token, out, err)
    bravo = fleet_lib.fleet_env_path("bravo")
    with open(fleet_lib.fleet_env_path("alpha"), "rb") as fa, open(bravo, "rb") as fb:
        assert fa.read() == fb.read()
    assert stat.S_IMODE(os.stat(bravo).st_mode) == 0o600
    assert not os.path.lexists(bravo + ".tmp")
    assert agentd.main(["join", "--agent-id", "bravo", "--from-agent", "alpha"]) == 0
    assert capsys.readouterr() == ("qwen-agentd: already joined fleet %s\n" % fid, "")
    s = fleet_lib.make_join_string(fid, token)
    for argv, message in (
            (["--agent-id", "alpha", "--from-agent", "alpha"], "qwen-agentd: --from-agent names agent 'alpha' itself"),
            (["--agent-id", "carol", "--from-agent", "dave"],
             "qwen-agentd: %s not found; agent 'dave' has not joined a fleet" % fleet_lib.fleet_env_path("dave")),
            (["--agent-id", "carol", "--from-agent", "Bad_Id"], "qwen-agentd: invalid --from-agent 'Bad_Id'"),
            (["--agent-id", "carol", "--from-agent", "alpha", s],
             "qwen-agentd: join takes STRING or --from-agent, not both")):
        assert agentd.main(["join"] + argv) == 2, argv
        out, err = capsys.readouterr()
        assert (out, err) == ("", message + "\n"), argv
        assert _no_token_in(token, out, err)
    assert not os.path.lexists(fleet_lib.deploy_root("carol"))
    os.unlink(bravo)
    fleet_lib.write_fleet_env(bravo, ftu.OTHER_FLEET_ID, ftu.OTHER_TOKEN)
    assert agentd.main(["join", "--agent-id", "bravo", "--from-agent", "alpha"]) == 2
    assert capsys.readouterr() == ("", "qwen-agentd: %s exists for a different fleet; remove it first\n" % bravo)
    assert fleet_lib.load_fleet_env(bravo) == (ftu.OTHER_FLEET_ID, ftu.OTHER_TOKEN)


def test_multi_agent_focus_5_from_agent_with_a_loose_secret_file(agentd, capsys, tmp_path):
    """Multi-agent Review Focus 5: the source agent's fleet.env was copied around and is now mode 0644.
    join --from-agent refuses with F21's chmod hint, writes nothing for the target agent,
    and prints no part of the token."""
    assert agentd.main(["init-fleet", "--agent-id", "alpha"]) == 0
    capsys.readouterr()
    source = fleet_lib.fleet_env_path("alpha")
    _fid, token = fleet_lib.load_fleet_env(source)
    os.chmod(source, 0o644)
    assert agentd.main(["join", "--agent-id", "bravo", "--from-agent", "alpha"]) == 2
    out, err = capsys.readouterr()
    assert (out, err) == ("", "qwen-agentd: %s must be mode 0600 (chmod 600 %s)\n" % (source, source))
    assert _no_token_in(token, out, err)
    assert not os.path.lexists(fleet_lib.deploy_root("bravo"))
```

- [ ] **Step 2: Run them to verify they fail.**

Run: `python3 -m pytest tests/test_fleet_integration.py::test_mt13_join_from_agent tests/test_fleet_integration.py::test_multi_agent_focus_5_from_agent_with_a_loose_secret_file -q -p no:cacheprovider`
Expected: `2 failed` with `SystemExit: 2` (argparse does not know `--from-agent` yet).

- [ ] **Step 3: Implement.** In `bin/qwen-agentd`:

Edit 1 of 3 in `bin/qwen-agentd` (base lines 90-102). Replace:

```python
def cmd_join(args):
    host_id, message = fleet_lib.resolve_agent(args.agent_id)
    if message is not None:
        _err(message)
        return 2
    raw = args.string if args.string is not None else getpass.getpass("join string: ")
    try:
        fleet_id, token = fleet_lib.parse_join_string(raw)
    except fleet_lib.FleetEnvError:
        _err("qwen-agentd: invalid join string")
        return 2
    path = fleet_lib.fleet_env_path(host_id)
    if os.path.lexists(path):
```

with:

```python
def cmd_join(args):
    host_id, message = fleet_lib.resolve_agent(args.agent_id)
    if message is not None:
        _err(message)
        return 2
    if args.from_agent is not None:
        return _join_from_agent(host_id, args.from_agent, args.string)
    raw = args.string if args.string is not None else getpass.getpass("join string: ")
    try:
        fleet_id, token = fleet_lib.parse_join_string(raw)
    except fleet_lib.FleetEnvError:
        _err("qwen-agentd: invalid join string")
        return 2
    return _save_join(host_id, fleet_id, token, "")


def _join_from_agent(host_id, source_id, string):
    """join --from-agent: copy agent source_id's secret to host_id, never printing it (multi-agent spec M29)."""
    if string is not None:
        _err("qwen-agentd: join takes STRING or --from-agent, not both")
        return 2
    if not fleet_lib.HOST_ID_RE.fullmatch(source_id):
        _err("qwen-agentd: invalid --from-agent '%s'" % source_id)
        return 2
    if source_id == host_id:
        _err("qwen-agentd: --from-agent names agent '%s' itself" % host_id)
        return 2
    source = fleet_lib.fleet_env_path(source_id)
    try:
        fleet_id, token = fleet_lib.load_fleet_env(source)
    except FileNotFoundError:
        _err("qwen-agentd: %s not found; agent '%s' has not joined a fleet" % (source, source_id))
        return 2
    except fleet_lib.FleetEnvError as e:
        _err("qwen-agentd: %s" % e)
        return 2
    return _save_join(host_id, fleet_id, token, " (copied from agent %s)" % source_id)


def _save_join(host_id, fleet_id, token, suffix):
    """F26 steps 3-4 for both join forms: never overwrite; the same fleet is exit 0 (multi-agent spec M28, M29)."""
    path = fleet_lib.fleet_env_path(host_id)
    if os.path.lexists(path):
```

Edit 2 of 3 in `bin/qwen-agentd` (base lines 112-114). Replace:

```python
    fleet_lib.write_fleet_env(path, fleet_id, token)
    print("qwen-agentd: joined fleet %s" % fleet_id)
    return 0
```

with:

```python
    fleet_lib.write_fleet_env(path, fleet_id, token)
    print("qwen-agentd: joined fleet %s%s" % (fleet_id, suffix))
    return 0
```

Edit 3 of 3 in `bin/qwen-agentd` (base lines 1372-1373). Replace:

```python
    p = sub.add_parser("join", help="join an existing fleet (prompts when STRING is omitted)")
    _add_agent_id(p)
```

with:

```python
    p = sub.add_parser("join", help="join an existing fleet (prompts when STRING is omitted)")
    _add_agent_id(p)
    p.add_argument("--from-agent", dest="from_agent", default=None, metavar="ID")
```

- [ ] **Step 4: Run the tests to verify they pass, then the whole file and both compilers.**

```bash
python3 -m pytest tests/test_fleet_integration.py::test_mt13_join_from_agent tests/test_fleet_integration.py::test_multi_agent_focus_5_from_agent_with_a_loose_secret_file -q -p no:cacheprovider
python3 -m pytest tests/test_fleet_integration.py -q -p no:cacheprovider
/usr/bin/python3 -m py_compile bin/qwen-agentd && python3 -m py_compile bin/qwen-agentd && echo compile-ok
```

Expected: `2 passed`; `34 passed`; `compile-ok`.

- [ ] **Step 5: Commit.**

```bash
git add bin/qwen-agentd tests/test_fleet_integration.py
git diff --cached --name-only   # expected: qwen-agent-workspace/bin/qwen-agentd, qwen-agent-workspace/tests/test_fleet_integration.py
git commit -q -F - <<'EOF'
qwen-agentd: join --from-agent copies another agent's fleet secret (multi-agent M29, M36)

MT13 (d, e), Review Focus 5.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 7: install writes the per-agent and default command wrappers; --default; the usage block

Implements M25 step 9 (port from the release's registries, launcher, per-agent command, default command) and step 1's message, M26 (the `command:` and `default:` lines), M23's `install --default`, M11-M13 end to end, and M37's usage block. The old symlink block is deleted. Tests MT20, MT21, MT22, and T61's second migration (wrappers instead of the symlink).

**Files:**
- Modify: `bin/qwen-agentd` — three edits (base lines 4-10, 1274-1297, 1421).
- Test: `tests/test_fleet_self_update.py` — four edits (base lines 119-122, 130-133, 139-142, 150-152) and one appended block.

**Interfaces:**
- Consumes (Tasks 3-5): `fleet_lib.agent_port`, `wrapper_bytes`, `command_path`, `default_command_path`, `classify_command_path`, `agent_command_action`, `default_command_action`, `write_wrapper`, `DEFAULT_PORT`; `cmd_install`'s locals `host_id`, `d`, `current` (Task 4); `ftu.make_fleet(home, host_id, ...)`.
- Produces in `bin/qwen-agentd`: `args.make_default` (`install --default`). In `tests/test_fleet_self_update.py`: `_agentd(home, *args) -> CompletedProcess`, `_install_agent(home, origin, host_id, *extra) -> CompletedProcess`, `_two_agent_origin(tmp_path) -> (home, origin, p1, p2)` (registry with `h1` on `p1` and `h2` on `p2`, tag `v2026.01.01`), `_read(path) -> bytes`, `_paths(home) -> (qwen-agent-h1, qwen-agent-h2, qwen-agent)`. Task 8 uses `_agentd`, `_install_agent` and `_two_agent_origin`.

- [ ] **Step 1: Migrate T61 to the wrappers.** In `tests/test_fleet_self_update.py`:

Edit 1 of 4 in `tests/test_fleet_self_update.py` (base lines 119-122). Replace:

```python
def test_t61_install_layout_and_idempotence(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    origin = Origin(tmp_path / "o", _registry(ftu.free_port()))
```

with:

```python
def test_t61_install_layout_and_idempotence(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    port = ftu.free_port()
    origin = Origin(tmp_path / "o", _registry(port))
```

Edit 2 of 4 in `tests/test_fleet_self_update.py` (base lines 130-133). Replace:

```python
    d = _deploy(home)
    assert proc.stdout == ("installed v2026.01.01 at %s\n"
                           "next: run %s/current/qwen-agent-workspace/bin/qwen-agentd join --agent-id h1 "
                           "(or init-fleet --agent-id h1); the service retries every 10 s\n" % (d, d))
```

with:

```python
    d = _deploy(home)
    bindir = os.path.join(str(home), ".local", "bin")
    lines = ("installed v2026.01.01 at %s\n" % d
             + "command: %s/qwen-agent-h1 (daemon port %d)\n" % (bindir, port)
             + "default: %s/qwen-agent runs agent h1\n" % bindir)
    assert proc.stdout == lines + ("next: run %s/current/qwen-agent-workspace/bin/qwen-agentd join --agent-id h1 "
                                   "(or init-fleet --agent-id h1); the service retries every 10 s\n" % d)
```

Edit 3 of 4 in `tests/test_fleet_self_update.py` (base lines 139-142). Replace:

```python
    link = os.path.join(str(home), ".local", "bin", "qwen-agent")
    assert os.readlink(link) == os.path.join(d, "current", "qwen-agent-workspace", "bin", "qwen-agent")
    assert os.path.realpath(link) == os.path.realpath(
        os.path.join(d, "releases", "v2026.01.01", "qwen-agent-workspace", "bin", "qwen-agent"))
```

with:

```python
    monkeypatch.setenv("HOME", str(home))
    wrapper = fleet_lib.wrapper_bytes("h1", port)
    for name in ("qwen-agent", "qwen-agent-h1"):
        path = os.path.join(bindir, name)
        assert os.path.isfile(path) and not os.path.islink(path)
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o755
        with open(path, "rb") as f:
            assert f.read() == wrapper
    target = os.path.join(d, "current", "qwen-agent-workspace", "bin", "qwen-agent")
    assert wrapper.decode("utf-8").splitlines()[-1] == "exec '%s' \"$@\"" % target
    assert os.path.realpath(target) == os.path.realpath(
        os.path.join(d, "releases", "v2026.01.01", "qwen-agent-workspace", "bin", "qwen-agent"))
```

Edit 4 of 4 in `tests/test_fleet_self_update.py` (base lines 150-152). Replace:

```python
    proc = _install(home, origin)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "installed v2026.01.01 at %s\n" % d
```

with:

```python
    proc = _install(home, origin)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == lines
```

- [ ] **Step 2: Add MT20, MT21 and MT22.**

Append to the end of `tests/test_fleet_self_update.py`, after exactly two empty lines (the file ends with a newline, so add two more newlines, then this block, which ends with a newline):

```python
# --- multi-agent hosts: install per agent, the generated commands (M3, M11-M13, M24-M26) ---

def _agentd(home, *args):
    return subprocess.run([sys.executable, ftu.AGENTD] + list(args), env=ftu.clean_env(home),
                          capture_output=True, text=True, timeout=300)


def _install_agent(home, origin, host_id, *extra):
    return _agentd(home, "install", "--agent-id", host_id, "--origin", origin.bare, "--no-service", *extra)


def _two_agent_origin(tmp_path):
    """Origin whose registry lists h1 and h2 on their own free ports, tagged v2026.01.01."""
    home = tmp_path / "home"
    home.mkdir()
    p1, p2 = ftu.free_port(), ftu.free_port()
    registry = _registry(p1)
    registry["hosts"]["h2"] = dict(registry["hosts"]["h1"], port=p2, model="h2-model")
    origin = Origin(tmp_path / "o", registry)
    origin.release("v2026.01.01")
    return home, origin, p1, p2


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _paths(home):
    """(qwen-agent-h1, qwen-agent-h2, qwen-agent) under <home>/.local/bin."""
    bindir = os.path.join(str(home), ".local", "bin")
    return (os.path.join(bindir, "qwen-agent-h1"), os.path.join(bindir, "qwen-agent-h2"),
            os.path.join(bindir, "qwen-agent"))


def test_mt20_two_agents_one_home(tmp_path, monkeypatch):
    home, origin, p1, p2 = _two_agent_origin(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    w1, w2 = fleet_lib.wrapper_bytes("h1", p1), fleet_lib.wrapper_bytes("h2", p2)
    cmd1, cmd2, default = _paths(home)
    a1, a2 = os.path.join(str(home), "agents", "h1"), os.path.join(str(home), "agents", "h2")
    # (1) the first agent sets the default
    proc = _install_agent(home, origin, "h1")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == (
        "installed v2026.01.01 at %s\n" % a1
        + "command: %s (daemon port %d)\n" % (cmd1, p1)
        + "default: %s runs agent h1\n" % default
        + "next: run %s/current/qwen-agent-workspace/bin/qwen-agentd join --agent-id h1 "
          "(or init-fleet --agent-id h1); the service retries every 10 s\n" % a1)
    for path in (cmd1, default):
        assert os.path.isfile(path) and not os.path.islink(path)
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o755
        assert _read(path) == w1
    # (2) a second agent (through the --host-id alias) leaves the default alone
    proc = _agentd(home, "install", "--host-id", "h2", "--origin", origin.bare, "--no-service")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[:3] == [
        "installed v2026.01.01 at %s" % a2, "command: %s (daemon port %d)" % (cmd2, p2),
        "default: %s unchanged; pass --default to make it run agent h2" % default]
    assert _read(cmd2) == w2 and _read(default) == w1
    for root in (a1, a2):
        for name in ("repo", "current", "update-state.json", "qwen-agentd-launch"):
            assert os.path.lexists(os.path.join(root, name)), (root, name)
        assert os.path.realpath(os.path.join(root, "current")) == os.path.join(root, "releases", "v2026.01.01")
    # (3) --default moves the default to h2
    proc = _install_agent(home, origin, "h2", "--default")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[2] == "default: %s runs agent h2" % default
    assert _read(default) == w2
    # (4) re-installing h1 rewrites its own command and keeps h2 as the default
    fleet_lib.write_wrapper(cmd1, fleet_lib.wrapper_bytes("h1", 1024))
    proc = _install_agent(home, origin, "h1")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[1:3] == [
        "command: %s (daemon port %d)" % (cmd1, p1),
        "default: %s unchanged; pass --default to make it run agent h1" % default]
    assert _read(cmd1) == w1 and _read(default) == w2
    # (5) h2 takes h1's fleet secret without seeing it
    token = secrets.token_hex(32)
    ftu.make_fleet(home, "h1", ftu.TEST_FLEET_ID, token)
    proc = _agentd(home, "join", "--agent-id", "h2", "--from-agent", "h1")
    assert (proc.returncode, proc.stderr) == (0, "")
    assert proc.stdout == "qwen-agentd: joined fleet %s (copied from agent h1)\n" % ftu.TEST_FLEET_ID
    assert token not in proc.stdout
    env2 = os.path.join(a2, "fleet.env")
    assert stat.S_IMODE(os.stat(env2).st_mode) == 0o600
    assert _read(env2) == _read(os.path.join(a1, "fleet.env"))
    # (6) nothing was written outside the two agent roots, ~/.local/bin and the origin
    allowed = (os.path.join(str(home), "agents"), os.path.join(str(home), ".local", "bin"), str(tmp_path / "o"))
    for root, dirs, files in os.walk(str(tmp_path)):
        for name in dirs + files:
            path = os.path.join(root, name)
            assert any(path == a or path.startswith(a + os.sep) or a.startswith(path + os.sep)
                       for a in allowed), path


def test_mt21_commands_are_never_clobbered(tmp_path, monkeypatch):
    home, origin, _p1, p2 = _two_agent_origin(tmp_path)
    cmd1, _cmd2, default = _paths(home)
    assert _install_agent(home, origin, "h1").returncode == 0
    # (a) a hand-written qwen-agent-h1 is kept, with a warning and no command: line
    with open(cmd1, "w") as f:
        f.write("#!/bin/sh\necho mine\n")
    proc = _install_agent(home, origin, "h1")
    assert proc.returncode == 0, proc.stderr
    assert ("qwen-agentd: warning: not replacing %s: not a symlink or a qwen-agentd wrapper" % cmd1) in proc.stderr
    assert _read(cmd1) == b"#!/bin/sh\necho mine\n"
    assert not any(line.startswith("command: ") for line in proc.stdout.splitlines())
    # (b) a hand-written default is kept even with --default; stdout has no default: line
    with open(default, "w") as f:
        f.write("#!/bin/sh\necho default\n")
    proc = _install_agent(home, origin, "h1", "--default")
    assert proc.returncode == 0, proc.stderr
    assert ("qwen-agentd: warning: not replacing %s: not a symlink or a qwen-agentd wrapper" % default) in proc.stderr
    assert _read(default) == b"#!/bin/sh\necho default\n"
    assert not any(line.startswith("default: ") for line in proc.stdout.splitlines())
    # (c) a dangling symlink (the Mac's old dev link) is kept without --default, replaced with it
    os.unlink(default)
    os.symlink("/nonexistent", default)
    proc = _install_agent(home, origin, "h2")
    assert proc.returncode == 0, proc.stderr
    assert "default: %s unchanged; pass --default to make it run agent h2" % default in proc.stdout.splitlines()
    assert os.readlink(default) == "/nonexistent"
    proc = _install_agent(home, origin, "h2", "--default")
    assert proc.returncode == 0, proc.stderr
    assert not os.path.islink(default)
    monkeypatch.setenv("HOME", str(home))
    assert _read(default) == fleet_lib.wrapper_bytes("h2", p2)


def test_mt22_install_port_from_the_release_registry(tmp_path, monkeypatch):
    home, origin, _p1, _p2 = _two_agent_origin(tmp_path)
    # (a) an agent missing from every registry warns and uses 8190
    proc = _install_agent(home, origin, "h3")
    assert proc.returncode == 0, proc.stderr
    assert ("qwen-agentd: warning: agent 'h3' is not in any registry of release v2026.01.01; "
            "its commands use port 8190") in proc.stderr
    monkeypatch.setenv("HOME", str(home))
    assert _read(os.path.join(str(home), ".local", "bin", "qwen-agent-h3")) == fleet_lib.wrapper_bytes("h3", 8190)
    # (b) two registries of one release that disagree on h1's port: exit 2
    home2 = tmp_path / "home2"
    home2.mkdir()
    origin2 = Origin(tmp_path / "o2", _registry(ftu.free_port()))
    other = _registry(ftu.free_port())
    other["fleet_id"] = ftu.OTHER_FLEET_ID
    origin2.write(os.path.join("fleets", ftu.OTHER_FLEET_ID + ".json"), json.dumps(other, indent=2))
    origin2.release("v2026.01.01")
    proc = _install_agent(home2, origin2, "h1")
    assert proc.returncode == 2
    assert proc.stderr == ("qwen-agentd: agent 'h1' has different ports in 0123456789abcdef.json, "
                           "fedcba9876543210.json of release v2026.01.01\n")
```

- [ ] **Step 3: Run them to verify they fail (about 15 s).**

Run: `python3 -m pytest tests/test_fleet_self_update.py::test_t61_install_layout_and_idempotence tests/test_fleet_self_update.py::test_mt20_two_agents_one_home tests/test_fleet_self_update.py::test_mt21_commands_are_never_clobbered tests/test_fleet_self_update.py::test_mt22_install_port_from_the_release_registry -q -p no:cacheprovider`
Expected: `4 failed`: T61 and MT20 find no `command:` or `default:` lines in the install output, MT21 finds no `not replacing` warning, and MT22 finds no `not in any registry` warning.

- [ ] **Step 4: Implement.** In `bin/qwen-agentd` (Edit 1: M37's usage block; Edit 2: M25 step 9 and M26 in `cmd_install`; Edit 3: `--default`):

Edit 1 of 3 in `bin/qwen-agentd` (base lines 4-10). Replace:

```python
  qwen-agentd [run] [--registry PATH] [--beacon-targets LIST] [--beacon-port N]
                    [--qwen-agent-bin PATH] [--timing-scale X]
  qwen-agentd init-fleet
  qwen-agentd join [STRING]
  qwen-agentd install --host-id ID [--origin URL] [--no-service]
  qwen-agentd selftest
  qwen-agentd status [--port N]
```

with:

```python
  qwen-agentd [run] [--registry PATH] [--beacon-targets LIST] [--beacon-port N]
                    [--qwen-agent-bin PATH] [--timing-scale X]
  qwen-agentd init-fleet [--agent-id ID]
  qwen-agentd join [--agent-id ID] [STRING | --from-agent ID]
  qwen-agentd install --agent-id ID [--default] [--origin URL] [--no-service]
  qwen-agentd selftest
  qwen-agentd status [--agent-id ID] [--port N]
```

Edit 2 of 3 in `bin/qwen-agentd` (base lines 1274-1297). Replace:

```python
    launcher_tmp = os.path.join(d, ".qwen-agentd-launch.tmp")
    shutil.copyfile(os.path.join(current, fleet_lib.WS_SUBDIR, "bin", "qwen-agentd-launch"), launcher_tmp)
    os.chmod(launcher_tmp, 0o755)
    os.replace(launcher_tmp, os.path.join(d, "qwen-agentd-launch"))
    bindir = os.path.expanduser("~/.local/bin")
    os.makedirs(bindir, exist_ok=True)
    link = os.path.join(bindir, "qwen-agent")
    if os.path.lexists(link) and not os.path.islink(link):
        _err("qwen-agentd: warning: not replacing %s: not a symlink" % link)
    else:
        link_tmp = link + ".tmp"
        if os.path.lexists(link_tmp):
            os.unlink(link_tmp)
        os.symlink(os.path.join(current, fleet_lib.WS_SUBDIR, "bin", "qwen-agent"), link_tmp)
        os.replace(link_tmp, link)
    service_path = None
    if not args.no_service:
        ok, result = install_service(sys.executable, d, host_id)
        if not ok:
            _err(result)
            return 2
        service_path = result
    print("installed %s at %s" % (os.path.basename(os.path.realpath(current)), d))
    if service_path is not None:
```

with:

```python
    tag = os.path.basename(os.path.realpath(current))
    port, files = fleet_lib.agent_port(os.path.join(current, fleet_lib.WS_SUBDIR, "fleets"), host_id)
    if port is None and files:
        _err("qwen-agentd: agent '%s' has different ports in %s of release %s" % (host_id, ", ".join(files), tag))
        return 2
    if not files:
        _err("qwen-agentd: warning: agent '%s' is not in any registry of release %s; its commands use port %d"
             % (host_id, tag, fleet_lib.DEFAULT_PORT))
        port = fleet_lib.DEFAULT_PORT
    launcher_tmp = os.path.join(d, ".qwen-agentd-launch.tmp")
    shutil.copyfile(os.path.join(current, fleet_lib.WS_SUBDIR, "bin", "qwen-agentd-launch"), launcher_tmp)
    os.chmod(launcher_tmp, 0o755)
    os.replace(launcher_tmp, os.path.join(d, "qwen-agentd-launch"))
    wrapper = fleet_lib.wrapper_bytes(host_id, port)
    command = fleet_lib.command_path(host_id)
    kind, _found = fleet_lib.classify_command_path(command)
    command_action = fleet_lib.agent_command_action(kind)
    if command_action == "write":
        fleet_lib.write_wrapper(command, wrapper)
    else:
        _err("qwen-agentd: warning: not replacing %s: not a symlink or a qwen-agentd wrapper" % command)
    default = fleet_lib.default_command_path()
    kind, found = fleet_lib.classify_command_path(default)
    default_action = fleet_lib.default_command_action(kind, found, host_id, args.make_default)
    if default_action == "write":
        fleet_lib.write_wrapper(default, wrapper)
    elif default_action == "refuse":
        _err("qwen-agentd: warning: not replacing %s: not a symlink or a qwen-agentd wrapper" % default)
    service_path = None
    if not args.no_service:
        ok, result = install_service(sys.executable, d, host_id)
        if not ok:
            _err(result)
            return 2
        service_path = result
    print("installed %s at %s" % (tag, d))
    if command_action == "write":
        print("command: %s (daemon port %d)" % (command, port))
    if default_action == "write":
        print("default: %s runs agent %s" % (default, host_id))
    elif default_action == "keep":
        print("default: %s unchanged; pass --default to make it run agent %s" % (default, host_id))
    if service_path is not None:
```

Edit 3 of 3 in `bin/qwen-agentd` (base line 1421). Replace:

```python
    _add_agent_id(p, required=True)
```

with:

```python
    _add_agent_id(p, required=True)
    p.add_argument("--default", dest="make_default", action="store_true", default=False)
```

- [ ] **Step 5: Run the tests to verify they pass, then the whole file and both compilers (about 3 min).**

```bash
python3 -m pytest tests/test_fleet_self_update.py::test_t61_install_layout_and_idempotence tests/test_fleet_self_update.py::test_mt20_two_agents_one_home tests/test_fleet_self_update.py::test_mt21_commands_are_never_clobbered tests/test_fleet_self_update.py::test_mt22_install_port_from_the_release_registry -q -p no:cacheprovider
python3 -m pytest tests/test_fleet_self_update.py -q -p no:cacheprovider
/usr/bin/python3 -m py_compile bin/qwen-agentd && python3 -m py_compile bin/qwen-agentd && echo compile-ok
grep -n "os.symlink" bin/qwen-agentd
```

Expected: `4 passed`; `12 passed`; `compile-ok`; the `grep` prints exactly one line, inside `swap_current` (`    os.symlink(os.path.join("releases", tag), tmp)`).

- [ ] **Step 6: Commit.**

```bash
git add bin/qwen-agentd tests/test_fleet_self_update.py
git diff --cached --name-only   # expected: qwen-agent-workspace/bin/qwen-agentd, qwen-agent-workspace/tests/test_fleet_self_update.py
git commit -q -F - <<'EOF'
qwen-agentd: install writes per-agent and default command wrappers, --default (multi-agent M11-M13, M25, M26, M37)

MT20, MT21, MT22; T61 now checks the wrappers.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 8: status finds the agent's port in its registry

Implements M30 step 1 (an explicit `--port` wins; otherwise resolve the agent and read its port from `A(<id>)/current`'s registries, or this checkout's when not installed) and step 4's exit 2, with `status --port` defaulting to `None`. Tests MT12 (a)-(c) and MT24; `test_status_command`, T40 and T60 keep passing unchanged.

**Files:**
- Modify: `bin/qwen-agentd` — two edits (base lines 991-998, 1437).
- Test: `tests/test_fleet_integration.py` and `tests/test_fleet_self_update.py` — one appended block each.

**Interfaces:**
- Consumes (Tasks 3, 4, 7): `fleet_lib.agent_port`, `resolve_agent`, `deploy_root`, `WS_SUBDIR`; `cmd_status`'s `explicit` (Task 4); `_agentd`, `_install_agent`, `_two_agent_origin`, `_registry` in the self-update tests.
- Produces in `bin/qwen-agentd`: `_status_port(explicit) -> (port, None) or (None, message)`; `status --port` default `None`.

- [ ] **Step 1: Write the failing tests.** In `tests/test_fleet_integration.py`:

Append to the end of `tests/test_fleet_integration.py`, after exactly two empty lines (the file ends with a newline, so add two more newlines, then this block, which ends with a newline):

```python
def test_mt12_status_resolves_the_agent_port(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    agents = home / "agents"
    proc = _run_agentd(home, ["status"])
    assert (proc.returncode, proc.stdout, proc.stderr) == (
        2, "", "qwen-agentd: no agent found in %s; pass --agent-id ID\n" % agents)
    ftu.make_fleet(home, "alpha")
    ftu.make_fleet(home, "bravo")
    proc = _run_agentd(home, ["status"])
    assert (proc.returncode, proc.stdout, proc.stderr) == (
        2, "", "qwen-agentd: more than one agent in %s (alpha, bravo); pass --agent-id ID\n" % agents)
    proc = _run_agentd(home, ["status", "--agent-id", "zulu"])
    assert (proc.returncode, proc.stdout, proc.stderr) == (
        2, "", "qwen-agentd: agent 'zulu' is not in any registry in %s; pass --port N\n" % os.path.join(WS, "fleets"))
```

In `tests/test_fleet_self_update.py`:

Append to the end of `tests/test_fleet_self_update.py`, after exactly two empty lines (the file ends with a newline, so add two more newlines, then this block, which ends with a newline):

```python
def test_mt24_status_port_from_the_installed_release(tmp_path):
    home, origin, p1, _p2 = _two_agent_origin(tmp_path)
    assert _install_agent(home, origin, "h1").returncode == 0
    proc = _agentd(home, "status", "--agent-id", "h1")
    assert proc.returncode == 1
    assert proc.stdout == ("daemon: not reachable at http://127.0.0.1:%d\n"
                           "update: status=ok from=- to=v2026.01.01 attempts=0 bad_tags=-\n" % p1)
    fleets = os.path.join(str(home), "agents", "h1", "current", "qwen-agent-workspace", "fleets")
    other = _registry(ftu.free_port())
    other["fleet_id"] = ftu.OTHER_FLEET_ID
    with open(os.path.join(fleets, ftu.OTHER_FLEET_ID + ".json"), "w", encoding="utf-8") as f:
        json.dump(other, f)
    proc = _agentd(home, "status")
    assert (proc.returncode, proc.stdout, proc.stderr) == (
        2, "", "qwen-agentd: agent 'h1' has different ports in 0123456789abcdef.json, fedcba9876543210.json "
               "in %s; pass --port N\n" % fleets)
```

- [ ] **Step 2: Run them to verify they fail.**

Run: `python3 -m pytest tests/test_fleet_integration.py::test_mt12_status_resolves_the_agent_port tests/test_fleet_self_update.py::test_mt24_status_port_from_the_installed_release -q -p no:cacheprovider`
Expected: `2 failed`: `status` still defaults to port 8190, so MT12 (a) gets exit 1 instead of 2, and MT24's `daemon:` line names 8190 instead of the registry port.

- [ ] **Step 3: Implement.** In `bin/qwen-agentd`:

Edit 1 of 2 in `bin/qwen-agentd` (base lines 991-998). Replace:

```python
def cmd_status(args):
    explicit = None
    if args.agent_id is not None:
        explicit, message = fleet_lib.resolve_agent(args.agent_id)
        if message is not None:
            _err(message)
            return 2
    url = "http://127.0.0.1:%d" % args.port
```

with:

```python
def _status_port(explicit):
    """(port, None) or (None, stderr message) from the agent's registries (multi-agent spec M30 step 1).

    An installed agent's daemon runs from A(<id>)/current, a dev daemon from this checkout.
    """
    host_id, message = fleet_lib.resolve_agent(explicit)
    if message is not None:
        return None, message
    d = fleet_lib.deploy_root(host_id)
    if os.path.lexists(os.path.join(d, "current")):
        fleets_dir = os.path.join(d, "current", fleet_lib.WS_SUBDIR, "fleets")
    else:
        fleets_dir = os.path.join(REPO_ROOT, "fleets")
    port, files = fleet_lib.agent_port(fleets_dir, host_id)
    if not files:
        return None, "qwen-agentd: agent '%s' is not in any registry in %s; pass --port N" % (host_id, fleets_dir)
    if port is None:
        return None, ("qwen-agentd: agent '%s' has different ports in %s in %s; pass --port N"
                      % (host_id, ", ".join(files), fleets_dir))
    return port, None


def cmd_status(args):
    """F94 with multi-agent spec M30: an explicit --port wins; otherwise the agent's registry port."""
    explicit = None
    if args.agent_id is not None:
        explicit, message = fleet_lib.resolve_agent(args.agent_id)
        if message is not None:
            _err(message)
            return 2
    port = args.port
    if port is None:
        port, message = _status_port(explicit)
        if message is not None:
            _err(message)
            return 2
    url = "http://127.0.0.1:%d" % port
```

Edit 2 of 2 in `bin/qwen-agentd` (base line 1437). Replace:

```python
    p.add_argument("--port", type=int, default=fleet_lib.DEFAULT_PORT)
```

with:

```python
    p.add_argument("--port", type=int, default=None)
```

- [ ] **Step 4: Run the tests to verify they pass, then both files and both compilers (about 4 min).**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_fleet_integration.py::test_mt12_status_resolves_the_agent_port tests/test_fleet_self_update.py::test_mt24_status_port_from_the_installed_release tests/test_fleet_integration.py::test_status_command tests/test_fleet_integration.py::test_t40_beacon_discovery_within_45s_scaled tests/test_fleet_integration.py::test_mt12_status_update_line_agent tests/test_fleet_self_update.py::test_t60_switch_gate_failure_and_crash_rollback
python3 -m pytest tests/test_fleet_integration.py -q -p no:cacheprovider
python3 -m pytest tests/test_fleet_self_update.py -q -p no:cacheprovider
/usr/bin/python3 -m py_compile bin/qwen-agentd && python3 -m py_compile bin/qwen-agentd && echo compile-ok
```

Expected: `6 passed`; `35 passed`; `13 passed`; `compile-ok`.

- [ ] **Step 5: Commit.**

```bash
git add bin/qwen-agentd tests/test_fleet_integration.py tests/test_fleet_self_update.py
git diff --cached --name-only   # expected: qwen-agent-workspace/bin/qwen-agentd, qwen-agent-workspace/tests/test_fleet_integration.py, qwen-agent-workspace/tests/test_fleet_self_update.py
git commit -q -F - <<'EOF'
qwen-agentd: status finds the agent's port in its registry (multi-agent M30)

MT12 (a-c), MT24.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 9: run's beacon port and targets default from the registry

Implements M15 and M16 in the daemon (both flags default to `None`; `Daemon.start` applies `self_entry["port"]` and `default_beacon_targets(registry)` after the registry loads, M31 step 9) and the `start_daemon` helper change of spec 5.2. Test MT10, the one test allowed to broadcast.

**Files:**
- Modify: `bin/qwen-agentd` — three edits (base lines 226-233, 445, 1459-1460).
- Modify: `tests/fleet_testutil.py` — two edits (base lines 3-4, 243-250).
- Test: `tests/test_fleet_integration.py` — one appended block.

**Interfaces:**
- Consumes (Tasks 3, 4): `fleet_lib.default_beacon_targets`; `Daemon.start`'s `self.port`, `self.registry`; `ftu.make_fleet`, `ftu.read_log`.
- Produces: `run --beacon-targets` and `--beacon-port` default `None`; `_validate_run_flags(args)` returns `None` for an omitted beacon flag; `ftu.start_daemon(home, host_id, registry, beacon_port, beacon_targets, ...)` omits a flag passed as `None`, and `DaemonProc.beacon_port` is then the registry port.

- [ ] **Step 1: Let `start_daemon` omit the beacon flags.** In `tests/fleet_testutil.py`:

Edit 1 of 2 in `tests/fleet_testutil.py` (base lines 3-4). Replace:

```python
Not a test module (pytest does not collect it). Loopback only: every server a
helper starts binds 127.0.0.1, and every daemon gets explicit beacon targets.
```

with:

```python
Not a test module (pytest does not collect it). Loopback only: every server a
helper starts binds 127.0.0.1, and every daemon gets explicit beacon targets
except MT10's (multi-agent spec 5.1).
```

Edit 2 of 2 in `tests/fleet_testutil.py` (base lines 243-250). Replace:

```python
    """Spawn `qwen-agentd run` for host_id; return once GET /peers answers 200 (10 s max)."""
    with open(str(registry), encoding="utf-8") as f:
        port = json.load(f)["hosts"][host_id].get("port", fleet_lib.DEFAULT_PORT)
    argv = [sys.executable, AGENTD, "run", "--registry", str(registry), "--beacon-port", str(beacon_port),
            "--beacon-targets", beacon_targets, "--timing-scale", scale] + list(extra_args)
    env = clean_env(home, QWEN_AGENT_HOST_ID=host_id, **(env_extra or {}))
    proc = spawn(argv, env, home)
    daemon = DaemonProc(proc, home, host_id, port, beacon_port)
```

with:

```python
    """Spawn `qwen-agentd run` for host_id; return once GET /peers answers 200 (10 s max).

    beacon_port=None omits --beacon-port (the daemon then receives on its registry port) and
    beacon_targets=None omits --beacon-targets (multi-agent spec M15, M16; only MT10 does this).
    """
    with open(str(registry), encoding="utf-8") as f:
        port = json.load(f)["hosts"][host_id].get("port", fleet_lib.DEFAULT_PORT)
    argv = [sys.executable, AGENTD, "run", "--registry", str(registry)]
    if beacon_port is not None:
        argv += ["--beacon-port", str(beacon_port)]
    if beacon_targets is not None:
        argv += ["--beacon-targets", beacon_targets]
    argv += ["--timing-scale", scale] + list(extra_args)
    env = clean_env(home, QWEN_AGENT_HOST_ID=host_id, **(env_extra or {}))
    proc = spawn(argv, env, home)
    daemon = DaemonProc(proc, home, host_id, port, port if beacon_port is None else beacon_port)
```

- [ ] **Step 2: Write the failing test.**

Append to the end of `tests/test_fleet_integration.py`, after exactly two empty lines (the file ends with a newline, so add two more newlines, then this block, which ends with a newline):

```python
# --- multi-agent hosts: two agents in one HOME with the default beacon flags (M15-M17, M31, MK4) ---

def test_mt10_two_agents_one_home_default_beacons(tmp_path):
    """The one test whose daemons run without beacon flags (multi-agent spec 5.1): they send
    limited broadcasts to 255.255.255.255 on their two ephemeral registry ports."""
    home = tmp_path / "m"
    home.mkdir()
    ftu.make_fleet(home, "alpha")
    ftu.make_fleet(home, "bravo")
    pa, pb = ftu.free_port(), ftu.free_port()
    assert fleet_lib.DEFAULT_PORT not in (pa, pb)
    stub_a = ftu.StubModelServer("vllm", "alpha-model", "ALPHA-ANSWER")
    stub_b = ftu.StubModelServer("ollama", "bravo-model", "BRAVO-ANSWER")
    registry = ftu.write_registry(tmp_path / "registry.json", ftu.TEST_FLEET_ID, {
        "alpha": {"port": pa, "model_server": {"type": "vllm", "url": stub_a.url},
                  "model": "alpha-model", "skills": []},
        "bravo": {"port": pb, "model_server": {"type": "ollama", "url": stub_b.url},
                  "model": "bravo-model", "skills": ["researcher"]}})
    alpha = ftu.start_daemon(home, "alpha", registry, None, None)
    bravo = ftu.start_daemon(home, "bravo", registry, None, None)
    for daemon in (alpha, bravo):
        assert "--beacon-port" not in daemon.proc.args and "--beacon-targets" not in daemon.proc.args
        assert daemon.beacon_port == daemon.port
    # (a) each agent logs to its own A/logs, receives on its own port, and beacons to both ports
    for daemon, other in ((alpha, "bravo"), (bravo, "alpha")):
        log = ftu.read_log(home, daemon.host_id)
        assert ("qwen-agentd dev started host_id=%s port=%d beacon_port=%d beacon_targets=2 skills="
                % (daemon.host_id, daemon.port, daemon.port)) in log
        assert "started host_id=%s " % other not in log
    # (b) both UDP ports are really bound
    for port in (pa, pb):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            with pytest.raises(OSError) as e:
                sock.bind(("0.0.0.0", port))
            assert e.value.errno == errno.EADDRINUSE
        finally:
            sock.close()

    # (c) the two agents at one address find each other within the scaled poll bound
    def lists(daemon, other, port):
        return [(p["host_id"], p["port"]) for p in ftu.peers(daemon.port)[1]["peers"]] == [(other, port)]
    ftu.wait_until(lambda: lists(alpha, "bravo", pb) and lists(bravo, "alpha", pa), 7.5)
```

- [ ] **Step 3: Run it to verify it fails.**

Run: `python3 -m pytest tests/test_fleet_integration.py::test_mt10_two_agents_one_home_default_beacons -q -p no:cacheprovider`
Expected: `1 failed` with `AssertionError: qwen-agentd bravo exited 2 at startup`: under the old defaults both daemons receive on UDP 8190, so the second cannot bind it. (If something on this Mac already holds UDP 8190, the message names `alpha` instead; that is the same failure.) This red run briefly binds UDP 8190 and sends test-fleet beacons to `255.255.255.255:8190`, which is harmless (opaque, signed with the test key) and is what the old default always did.

- [ ] **Step 4: Implement.** In `bin/qwen-agentd`:

Edit 1 of 3 in `bin/qwen-agentd` (base lines 226-233). Replace:

```python
def _validate_run_flags(args):
    """(beacon_targets, beacon_port, scale) or StartupError with the F92 message."""
    targets = _parse_beacon_targets(args.beacon_targets)
    if targets is None:
        raise StartupError("qwen-agentd: invalid --beacon-targets")
    beacon_port = _parse_port(args.beacon_port)
    if beacon_port is None:
        raise StartupError("qwen-agentd: invalid --beacon-port")
```

with:

```python
def _validate_run_flags(args):
    """(beacon_targets, beacon_port, scale) or StartupError with the F92 message.

    An omitted beacon flag stays None; Daemon.start applies its default (multi-agent spec M15, M16).
    """
    targets = None
    if args.beacon_targets is not None:
        targets = _parse_beacon_targets(args.beacon_targets)
        if targets is None:
            raise StartupError("qwen-agentd: invalid --beacon-targets")
    beacon_port = None
    if args.beacon_port is not None:
        beacon_port = _parse_port(args.beacon_port)
        if beacon_port is None:
            raise StartupError("qwen-agentd: invalid --beacon-port")
```

Edit 2 of 3 in `bin/qwen-agentd` (base line 445). Replace:

```python
        self.version = fleet_lib.release_version(REPO_ROOT, fleet_lib.deploy_root(self.host_id))
```

with:

```python
        self.version = fleet_lib.release_version(REPO_ROOT, fleet_lib.deploy_root(self.host_id))
        if self.beacon_port is None:
            self.beacon_port = self.port
        if self.beacon_targets is None:
            self.beacon_targets = fleet_lib.default_beacon_targets(self.registry)
```

Edit 3 of 3 in `bin/qwen-agentd` (base lines 1459-1460). Replace:

```python
    p.add_argument("--beacon-targets", default="255.255.255.255:%d" % fleet_lib.DEFAULT_PORT, metavar="LIST")
    p.add_argument("--beacon-port", default=str(fleet_lib.DEFAULT_PORT), metavar="N")
```

with:

```python
    p.add_argument("--beacon-targets", default=None, metavar="LIST")
    p.add_argument("--beacon-port", default=None, metavar="N")
```

- [ ] **Step 5: Run the test to verify it passes, then every fleet file and both compilers (about 4 min).**

```bash
python3 -m pytest tests/test_fleet_integration.py::test_mt10_two_agents_one_home_default_beacons -q -p no:cacheprovider
python3 -m pytest tests/test_fleet_lib.py tests/test_fleet_integration.py tests/test_fleet_self_update.py tests/test_qwen_agent_fleet.py -q -p no:cacheprovider
/usr/bin/python3 -m py_compile bin/qwen-agentd && python3 -m py_compile bin/qwen-agentd && echo compile-ok
```

Expected: `1 passed`; `107 passed, 1 skipped`; `compile-ok`.

- [ ] **Step 6: Commit.**

```bash
git add bin/qwen-agentd tests/fleet_testutil.py tests/test_fleet_integration.py
git diff --cached --name-only   # expected: qwen-agent-workspace/bin/qwen-agentd, qwen-agent-workspace/tests/fleet_testutil.py, qwen-agent-workspace/tests/test_fleet_integration.py
git commit -q -F - <<'EOF'
qwen-agentd: beacon port and targets default from the registry (multi-agent M15, M16)

MT10.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 10: Regression, dual-interpreter compile, untouched files, old-path grep, final review (no code)

Implements MT40, MT41, MT42 and the deliverable check of spec 0.3. No file is changed; nothing is committed unless a defect is found (then fix it in the task that owns it, with that task's commit prefix, and re-run this task).

**Files:** none modified. Reads Task 1's baseline.

**Interfaces:** Consumes every earlier task. Produces `/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-multi-agent/final-pytest.txt`.

- [ ] **Step 1: MT40, the full suite (about 6 min).**

```bash
python3 -m pytest tests/ -q -rA -p no:cacheprovider > /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-multi-agent/final-pytest.txt 2>&1
tail -1 /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-multi-agent/final-pytest.txt
grep -E '^(FAILED|ERROR|SKIPPED)' /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-multi-agent/final-pytest.txt
cd /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-multi-agent
comm -23 <(grep '^PASSED' baseline-pytest.txt | sort) <(grep '^PASSED' final-pytest.txt | sort) | grep -v test_fleet_host_prep
comm -13 <(grep '^PASSED' baseline-pytest.txt | sort) <(grep '^PASSED' final-pytest.txt | sort) | grep -v test_fleet_host_prep | wc -l
cd /Users/reubenpatterson/local_agent_harness/qwen-agent-workspace
```

Expected: `1 failed, 1051 passed, 1 skipped` (the baseline's 1027 plus 24 new tests: 10 in `test_fleet_lib.py`, 9 in `test_fleet_integration.py`, 5 in `test_fleet_self_update.py`; if Task 1 recorded different counts, the baseline's passed count plus 24); the only `FAILED` line is `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike`, and the only `SKIPPED` line is T25's `no fleet.env on this host`; the first `comm` prints nothing (every baseline pass still passes); the second prints `24` (new passes outside `tests/test_fleet_host_prep.py`, which the concurrent plan may have grown).

- [ ] **Step 2: MT41, both interpreters.**

```bash
/usr/bin/python3 -m py_compile fleet_lib.py bin/qwen-agent bin/qwen-agentd bin/qwen-agentd-launch && echo py39-ok
python3 -m py_compile fleet_lib.py bin/qwen-agent bin/qwen-agentd bin/qwen-agentd-launch && echo py313-ok
```

Expected: `py39-ok` and `py313-ok`.

- [ ] **Step 3: MT42, the old paths are gone; no urllib requests.**

```bash
grep -rn -E "local/share/qwen-agent|\.config/qwen-agent" fleet_lib.py bin/qwen-agentd bin/qwen-agentd-launch bin/qwen-agent tests/fleet_testutil.py tests/test_fleet_lib.py tests/test_fleet_integration.py tests/test_fleet_self_update.py; echo "mt42 rc=$?"
grep -n -E "urllib\.request|urlopen" fleet_lib.py bin/qwen-agentd; echo "urllib rc=$?"
```

Expected: `mt42 rc=1` with nothing printed before it, and `urllib rc=1` with nothing printed before it.

- [ ] **Step 4: Untouched files and the exact change set (run from the repo root).**

```bash
cd /Users/reubenpatterson/local_agent_harness
git diff --quiet 3366d49 -- agent/qwen-agent-unsafe qwen-agent-workspace/tests/test_researcher_think_off.py qwen-agent-workspace/scripts/deploy qwen-agent-workspace/bin/qwen-agent qwen-agent-workspace/tests/test_qwen_agent_fleet.py && echo untouched-ok
git diff --name-only 3366d49..HEAD -- . ':!qwen-agent-workspace/scripts/fleet-host-prep.sh' ':!qwen-agent-workspace/tests/test_fleet_host_prep.py' ':!qwen-agent-workspace/docs'
git log --format=%s 3366d49..HEAD | grep -c "multi-agent M"
cd qwen-agent-workspace
test -x bin/qwen-agentd && test -x bin/qwen-agentd-launch && echo modes-ok
```

Expected: `untouched-ok`; the name list is exactly `qwen-agent-workspace/bin/qwen-agentd`, `qwen-agent-workspace/bin/qwen-agentd-launch`, `qwen-agent-workspace/fleet_lib.py`, `qwen-agent-workspace/tests/fleet_testutil.py`, `qwen-agent-workspace/tests/test_fleet_integration.py`, `qwen-agent-workspace/tests/test_fleet_lib.py`, `qwen-agent-workspace/tests/test_fleet_self_update.py`; `8`; `modes-ok`.

- [ ] **Step 5: The gate by hand.**

```bash
python3 bin/qwen-agentd selftest | tail -1
```

Expected: `48 passed, 1 skipped in ...` (the gate's selftest is `tests/test_fleet_lib.py`; T25 skips because there is no `~/agents` yet).

- [ ] **Step 6: Code review.** Dispatch a `design-reviewer` (Opus, high effort) over `git diff 3366d49..HEAD -- qwen-agent-workspace/fleet_lib.py qwen-agent-workspace/bin qwen-agent-workspace/tests` with this plan and the spec. It must check at minimum: the five Review Focus items; M2 (every path function validates the ID before building a path); M36 and F28 (no format string in `_join_from_agent`, `_save_join`, `_run_identity` or `cmd_install` can include the token; `status` and `install` never read `fleet.env`); M31's order (no directory is created before `setup_logging(host_id)`); M12's table in `default_command_action`; that `bin/qwen-agent` is unchanged. A NEEDS-FIX verdict comes with an exact patch; apply it in the owning task's files, re-run Steps 1-5, and commit with that task's message prefix.

---

## Rollout (human-run, after Task 10; not an executor task)

Rollout creates the real fleet secret in `~/agents/mac-local/`, installs real LaunchAgents and systemd units, replaces the Mac's dangling `~/.local/bin/qwen-agent` symlink, and touches 192.168.1.168, so no executor runs it. Run [FLEET] Section 12 (`qwen-agent-workspace/docs/superpowers/specs/2026-10-16-fleet-discovery-self-update-design.md`, R0-R10), which spec Section 7.2 has already rewritten for this layout: `init-fleet --agent-id mac-local` from the dev checkout (R1), `install --agent-id <id> --default` on both machines (R3a, R3b; `--default` is required on this Mac because of the dangling symlink, M12), `join --agent-id ollama-168` on .168, and `qwen-agentd status --agent-id <id>` for R4-R10. MR1 (two agents on .185, with `join --from-agent`) is optional and runs only after the vision feature registers those agents (spec 5.8). Manual removal of an agent is spec M35.

---

## Coverage

### Requirements (M) to tasks

| ID | Task(s) | ID | Task(s) |
|---|---|---|---|
| M1 | 4 (alias), 7 (MT20 `--host-id`) | M20 | none (firewall; live only, [PREP]) |
| M2 | 2, 4 | M21 | 2 |
| M3 | 4, 7 (MT20) | M22 | 2, 4, 8 |
| M4 | 3 (write), 4 (path) | M23 | 4, 6, 7, 8, 9 |
| M5 | 4 | M24 | 3, 7, 8 |
| M6 | 2 (names), 4 (services) | M25 | 4 (paths), 7 (step 9) |
| M7 | 3 | M26 | 4 (`next:`), 7 |
| M8 | 2 | M27, M28 | 4 |
| M9, M10 | 5 | M29 | 6 |
| M11, M12 | 5, 7 | M30 | 4 (step 3), 8 (steps 1, 2, 4) |
| M13 | 7 (MT20 (6)) | M31 | 4 (steps 1-8, 10-13), 9 (step 9) |
| M14 | 10 (MT42) | M32 | 4 |
| M15, M16 | 3 (`default_beacon_targets`), 9 | M33 | 4 (T25) |
| M17, M18 | 9 (MT10 (c)); otherwise unchanged code | M34 | 4 |
| M19 | 3 (MT4) | M35 | rollout (manual procedure) |
| | | M36 | 4, 6, 7 |
| | | M37 | 4 (help strings), 7 (usage block) |

### Tests (MT and migrated T) to tasks

| Tests | Task | Tests | Task |
|---|---|---|---|
| MT1 (names) `test_mt1a_*`, MT6 | 2 | MT13 (d, e), Review Focus 5 | 6 |
| MT4, MT5, MT7 | 3 | MT20, MT21, MT22, T61 (second migration) | 7 |
| MT1 (paths) `test_mt1b_*`, MT11, MT12 (d-f), MT13 (a-c, f, g), MT23, Review Focus 3-4, the 18 migrated tests | 4 | MT12 (a-c), MT24 | 8 |
| MT1 (`wrapper_bytes`), MT2, MT3, Review Focus 1-2 | 5 | MT10 | 9 |
| MT40, MT41, MT42 | 1 (baseline), 10 | | |

### Success criteria (MK)

| KPI | Automated (task) | Live |
|---|---|---|
| MK1 | MT40 (10) | none |
| MK2 | MT41 (10, and every task's compile step) | none |
| MK3 | MT20 (7), MT23 (4) | R3, MR1 |
| MK4 | MT10 (9) | R4, MR1 |
| MK5 | MT13 (6), MT20 (7), T46 (migrated, 4), Review Focus 5 (6) | R9 |
| MK6 | none | R1-R10 |

### Review Focus to tests

| Item | Test | Task |
|---|---|---|
| 1 inherited `QWEN_AGENT_DAEMON_URL` | `test_multi_agent_focus_1_wrapper_overrides_an_inherited_daemon_url` | 5 |
| 2 shell metacharacters through the wrapper | `test_multi_agent_focus_2_wrapper_passes_shell_metacharacters_verbatim` | 5 |
| 3 whitespace in `QWEN_AGENT_HOST_ID` | `test_multi_agent_focus_3_host_id_with_stray_whitespace_is_rejected` | 4 |
| 4 mistyped `--agent-id` | `test_multi_agent_focus_4_mistyped_agent_id_never_prompts` | 4 |
| 5 loose source `fleet.env` | `test_multi_agent_focus_5_from_agent_with_a_loose_secret_file` | 6 |

---

## Plan decisions (where the spec is silent, split across tasks, or needed a reading)

The spec's design is unchanged. Each item is pinned by code shown in its task.

**Readings of the spec (proposed rulings):**

1. **Spec 5.6's `test_service_definitions` row says "M23's dict and text"; M6 is meant** (M23 is the flags requirement; MT23 defines the dict and text). MT23's first half replaces that test's assertions, and its second half is the new `test_mt23_install_service_is_per_agent` (Task 4).
2. **MT12 (d) and (e) as written cannot tell "U = alpha from the view" from "no U"**, because both print `update: not installed` when no state file exists. `test_mt12_status_update_line_agent` keeps the spec's exact assertions and additionally writes `<HOME>/agents/alpha/update-state.json`, so (d) and (f) must print alpha's `update: status=ok ...` line and (e) must still print `update: not installed` (two agents on disk, the daemon down). It also checks M30 step 3's "an invalid value exits 2 ... before any network call" with `--agent-id Bad --port N`.
3. **MT24 also covers M30 step 1's "different ports" message and inference without `--agent-id`**: after the spec's check, it drops a second registry listing `h1` on another port into `A(h1)/current/.../fleets/` and expects exit 2 with that message from `status` with no flags.
4. **MT20 (6) "no path outside ... was created"** is checked by walking `<tmp>` and allowing only `<H>/agents`, `<H>/.local/bin`, `<tmp>/o` and their ancestors (`<H>`, `<H>/.local`).
5. **M29 step 5 lists only `FileNotFoundError` and `FleetEnvError`.** Any other `OSError` reading the source `fleet.env` (for example a directory in its place) falls through to F99's `qwen-agentd: internal error: <ExcType>: <msg>`, exit 1. The message carries a path, never the token.
6. **M30 when `--port` is absent:** `resolve_agent` runs once to validate an explicit ID (step 3's rule) and again inside `_status_port`; the second call cannot fail for a valid explicit ID. With `--port` given, no registry is read (step 1).
7. **M26 when the service fails to load:** the output lines are printed after `install_service`, as today, so a failing `launchctl bootstrap` or `systemctl` exits 2 with F90's message and prints none of M26's lines (the wrappers are already written by then, which a re-run refreshes).
8. **M25 step 9's warning and error are tested by their exact text**; the warning names `fleet_lib.DEFAULT_PORT` through `%d`, which prints `8190`.

**Values chosen by this plan:**

9. Helper names in `bin/qwen-agentd`: `_add_agent_id(p, required=False)` (M23's one flag definition), `_run_identity()` (M31 steps 3-4), `_status_agent(explicit, view)` (M30 step 3), `_status_port(explicit)` (M30 step 1), `_join_from_agent(host_id, source_id, string)` and `_save_join(host_id, fleet_id, token, suffix)` (M28/M29's shared never-overwrite policy).
10. `_status_agent` checks `HOST_ID_RE` on the view's `host_id` (already a `str` by `valid_view`), so a daemon reporting an odd ID never builds a path.
11. `agent_command_action` returns `"write"` only for the three named kinds and `"refuse"` for anything else, so an unexpected kind can never overwrite a file.
12. The new constants carry `# ... (multi-agent spec M<n>)` comments; every new or changed `fleet_lib` docstring cites its M number (M37).
13. MT1 is split by dependency: names in Task 2 (`test_mt1a_service_and_command_names`), root paths and the removed constants in Task 4 (`test_mt1b_agent_root_paths`), and `wrapper_bytes`'s bad IDs inside `test_mt2_wrapper_bytes_and_detection` (Task 5). MT12 and MT13 are each split into two test functions for the same reason.
14. The Review Focus tests are named `test_multi_agent_focus_<n>_*` so that they do not collide with the [FLEET] plan's `test_review_focus_<n>_*` tests, which keep their names.
15. Transitional states (each task leaves the suite green): Task 4 keeps the old `~/.local/bin/qwen-agent` symlink code, pointing into `~/agents/<id>/current`, until Task 7 replaces it, so T61 is migrated twice; `status --port` defaults to 8190 until Task 8; the beacon flags keep their 8190 defaults until Task 9.
16. MT10's red run (Task 9 Step 3) runs the pre-Task-9 defaults, which bind UDP 8190 and broadcast test-fleet beacons on it; that is the old production default and is harmless.
17. `MT2 (e)`, Review Focus 1 and Review Focus 2 run `/bin/sh` on the wrapper with a stand-in `bin/qwen-agent` under a temp `HOME`; they live in `tests/test_fleet_lib.py`, so they also run in the self-update gate (each takes milliseconds).

**Known residual risks (not covered by any automated test):** real `launchctl bootout` + `bootstrap` per label and real `systemctl --user` per unit (R3d, R5, R6); same-machine broadcast loopback on Linux and the LAN-IP delegation path between two agents on one machine (MR1); the macOS application firewall rule per binary (M20, [PREP]); and MR-C (a registry port change needs `install --agent-id <id>` again to refresh the wrappers).
