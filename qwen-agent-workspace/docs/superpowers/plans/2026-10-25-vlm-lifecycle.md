# VLM Lifecycle at Job Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the story/vision LLM (`bin/story-server mlx-vision` on 127.0.0.1:8177) in the state each movie-ui job needs, without a daemon: serialize every start and stop behind one host lock, scope every kill to the port's own process tree, detach restores under launchd so no cancel or orphan kill reaches them, and have the movie-ui job runner bring the VLM up or down before each job (preflight, with one health-checked restart) and restore it after each job when the queue is empty or the next job needs it (postflight).

**Architecture:** `bin/story-server` gains an exclusive flock on `$STATE_DIR/story-server.lock` (blocking with a timeout, same-mode fast path, stop-preempts-start), a `lockinfo` subcommand, port-owner process-tree discovery in place of the host-wide `VLLM::EngineCore` sweep, and a loaded-model-aware `extract_served_id`. `bin/story-server-restore` reads the lock instead of `ps`, launches through a double fork so the server's parent is launchd, waits up to 10 s for the start to take the lock, and redefines `--wait`. `movie_ui_lib` gains the per-job `vlm` policy, a port-scoped health check (`http.client`), the runner's preflight and postflight around the existing child lifecycle, a submit-time `warn` for a stopped story server, and a one-shot startup restore; `character_dataset.py` restores through `story-server-restore --wait`; the page drops its write-story gate. `MOVIE_UI_VLM_LIFECYCLE=0` turns the movie-ui parts off (runtime rollback and test isolation).

**Tech Stack:** bash 3.2 (`/bin/bash`, macOS) for `bin/story-server`; Python 3.13 (`python3`, pytest 8.3.4) and Python 3.9.6 (`/usr/bin/python3`, compile check, and the interpreter `bin/story-server` runs its helpers with); standard library only; the existing story-server stubs of `tests/test_story_server.py`, the stub workspace of `tests/movie_ui_testutil.py`, and three new fakes: F-TOOLS and F-HTTP (`tests/test_vlm_lifecycle.py`) and the rewritten F-SS (`tests/test_clean_stop.py`).

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-10-25-vlm-lifecycle-design.md`, rev 2, commit `168b2e8` (binding user decision 0.1: no standalone VLM daemon; Q2 and Q3 resolved). Every Edit below is written against branch `qwen-agent-redteam` at `168b2e8`, whose code tree is the code tree of `eeb8b5f` (the spec's line numbers cite `eeb8b5f`; `642e5b0` and `168b2e8` add only the spec). The spec is binding; this plan changes no design decision. Where the spec is silent or a test it specifies cannot be written as stated on this host, the reading is listed in "Plan decisions"; points a spec gap blocks are in "Questions for controller".

## Global Constraints

From the spec, verbatim (section in brackets):

- [0.1] "The implementer makes no design decisions." "Binding user decision: there is NO standalone VLM daemon."
- [0.3] "**Not changed:** `bin/ltx-movie` (Phase 1b's `story-server stop` now takes the lock with no code change), `bin/character-train-vlm`, `bin/action-train-vlm`, `bin/pipeline-stop`, `bin/movie-ui-job`, `bin/character`, `action_dataset.py`, `bin/ltx-mlx-render`, and every host default in `bin/story-server`."
- [0.4] Out of scope: "A standalone VLM daemon or watchdog, and any timer-driven probe"; "Starting or stopping the VLM from a page button"; "Modes other than `mlx-vision` for the runner"; "The 8178 embed server. Nothing in this spec reads, probes or signals it."; "Removing the train wrappers' own `restore --wait` under movie-ui (risk R5)".
- [2.5] Environment: `STORY_SERVER_LOCK_TIMEOUT` default `1260`; `STORY_SERVER_RESTORE_WAIT_S` default `2520`; `STORY_SERVER_RESTORE_BIN` default `<bin>/story-server`; `MOVIE_UI_VLM_LIFECYCLE` default `"1"` (`"0"` disables VR2, VR5, VU1's warn and VU2); `MOVIE_UI_VLM_TOOLS` default `<UI WS>/bin`; `MOVIE_UI_VLM_PORT` default `8177`.
- [2.5] "`movie_ui_lib` constants: `VLM_MODE = "mlx-vision"`, `VLM_POLICIES = ("required", "forbidden", "any")`, `VLM_STATUS_TIMEOUT_S = 60`, `VLM_HTTP_TIMEOUT_S = 10`, `VLM_COMPLETION_TIMEOUT_S = 120`, `VLM_PREFLIGHT_TIMEOUT_S = 6900`, `VLM_POSTFLIGHT_TIMEOUT_S = 90`, `VLM_TOOL_KILL_WAIT_S = 5`, `VLM_MAX_BODY = 1048576`, `VLM_RESTORE_LOG_TEXT = "~/.local/share/qwen-agent/story-server-restore.log"`, `VLM_RECOVERY = []` ..., `RESTORERS = []`."
- [VRS1] `WAIT_S = int(os.environ.get("STORY_SERVER_RESTORE_WAIT_S", "2520"))`, `POLL_S = 2`, `LOCK_WAIT_S = 10`, `LOCK_POLL_S = 0.2`.
- [VR4] "There is **no RSS or listening-pid check**." "The health check is called **only** from VR2. No timer calls it."
- [VU4] "`movie_ui_lib.py` adds `import http.client`, for loopback-only requests to 127.0.0.1." (GC3: `http.client`, never `urllib`.)
- [VS9] "No literal `8177` is added (S14). The new code uses no bash-4 features."
- [VK7] "`/usr/bin/python3` (3.9.6) and `python3` (3.13) both `py_compile` every changed Python file. `bash -n bin/story-server` passes, and `/bin/bash` 3.2 runs the VLS tests."
- [11.1] "No test runs the real `bin/story-server` without `STORY_SERVER_STATE_DIR`, `STORY_SERVER_PORT` (ephemeral) and every binary override from `_base_env`." "Restore tests set `HOME=<tmp>` and `STORY_SERVER_RESTORE_BIN=<fake>`." "No test renders, binds 8177 or 8178, or signals a process it did not start."
- [0.3 G10, 13 step 5] "`tests/test_movie_ui_builder.py::test_mut26` | `BASELINE` re-baseline in a **separate test-only follow-up commit**".

Repository rules (the controller's; every task's requirements include them):

- Standard library only in every Python file this plan touches; every new or changed file must run on Python 3.9.6 and 3.13: no `match`, no `X | Y` type expressions, no `zip(strict=)`, no parenthesised context managers, no walrus operator, no `str.removeprefix`. `bin/story-server` stays bash 3.2: no `mapfile`, `declare -A`, `local -A`, `${v,,}`, `|&`, `;&` or `&>>`.
- Tests never use the real `HOME`, never start a real model server (only the stubs of `tests/test_story_server.py`, F-TOOLS, F-HTTP and F-SS), never render, and never touch ports 8177 or 8178 for real (every port is ephemeral, or `9`, the conftest's unreachable value).
- Run tests as `cd /Users/reubenpatterson/local_agent_harness/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/<file>`; every pytest run prints a `pytest_asyncio` deprecation warning first, which is expected.
- Never stage `../.DS_Store`, `../.claude/`, `.claude/`, `../agent/__pycache__/` or the repo-root `../bin/`. Stage only the paths a task names and check `git diff --cached --name-only` before every commit. Never use `git stash`, `git reset` or `git checkout` of a path.
- Every commit message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (the commit commands below pass it as a second `-m`).
- Known pre-existing failures at `168b2e8`, to be ignored when they fail exactly as at the baseline: `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike`, `tests/test_story_engine.py::test_rst62_import_sets`, `tests/test_story_server.py::test_s14_source_guards`. Interaction: Task 2 realigns `test_s14_source_guards` (spec 11.4), so it passes from Task 2's commit on; the list is these three for Task 1 and two (without `test_s14`) from Task 2 on.
- `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` diffs `PIPELINE_FILES` against a pinned commit. `character_dataset.py` is in `PIPELINE_FILES` (no other file this plan changes is), so `test_mut26` fails from Task 4's commit until Task 13 re-baselines it in its own test-only commit. No task before 13 edits it; Task 6 runs `tests/test_movie_ui_builder.py` with `-k "not mut26"`.
- **Safety: no test step may run a `bin/story-server stop` from `168b2e8` without `STORY_SERVER_ENGINE_SCAN=0`.** HEAD's sweep is host-wide and would SIGKILL a real `VLLM::EngineCore` (the 8178 embed server's). `tests/test_story_server.py::_base_env` sets the variable until Task 2 Step 3 removes the sweep and the line in the same step.

House rules:

- `WS` = `/Users/reubenpatterson/local_agent_harness/qwen-agent-workspace`. The git root is one level up, so `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix. Run every command from `WS`.
- Every code block is copied exactly, byte for byte. A **Create** writes a new file whose whole content is the block. An **Append** adds two empty lines after the file's current last line (which ends with one newline), then the block. An **Edit** replaces one block of old text, which must occur exactly once in the file at that moment, with the new text; if the old text does not occur exactly once, stop and report: do not adapt it.
- The compile check in each task is this command, with the task's files as arguments; expected output is two lines, `compiled N` for 3.9 and then for 3.13:

```bash
for py in /usr/bin/python3 python3; do $py -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' FILES; done
```

- The shell syntax check, in every task that changes `bin/story-server`, is `/bin/bash -n bin/story-server && bash -n bin/story-server && echo "syntax ok"`; expected output `syntax ok`.

## Review Focus

These five inputs are implied by the spec, are the ones most likely to hit a real user first, and no VL/VLS/VLR/VLC test exercises them. Each is pinned by a test in its owning task.

1. **A story job followed by a movie of the same story that was queued while story.md did not exist yet** (the normal "write the story, then render it" flow; the movie's `job.json` says `vlm=required`). Expected: the story job's postflight recomputes the movie's policy as `forbidden` and does not restore; the movie's preflight prints `vlm: job.json says vlm=required; story.md exists now, so vlm=forbidden` and stops the VLM before rendering. Test: `test_review_focus_1_story_then_movie_of_the_same_story` (Task 8).
2. **movie-ui restarted while a job is still running** (the runner is detached and survives the restart). Expected: the startup restore is deferred while the job is alive (no restore process, `VLM_RECOVERY` kept) and runs at the first idle tick after the job ends. Test: `test_review_focus_2_startup_restore_waits_for_a_running_job` (Task 9).
3. **A `story-server` from an older release, which has no `lockinfo` subcommand** (it prints the usage line and exits 2), behind `story-server-restore`. Expected: the restore treats the lock as free and still launches the start (spec VRS2: "An old `story-server` without `lockinfo` (usage, exit 2) gives `None`"). Test: `test_review_focus_3_restore_with_a_story_server_without_lockinfo` (Task 3).
4. **A `/v1/models` reply that is not UTF-8, or longer than `VLM_MAX_BODY`.** Expected: the health check returns `GET /v1/models failed: invalid JSON` (H4), so the preflight restarts once and then fails the job with that text; the runner never dies on a traceback (which would leave the job `lost`). Test: `test_review_focus_4_models_reply_not_utf8_or_oversized` (Task 6).
5. **A UI workspace whose path contains a space** (`MOVIE_UI_VLM_TOOLS` defaults to `<UI WS>/bin`). Expected: the preflight runs the tools (argv lists, no shell) and logs `vlm: running: '<dir with space>/story-server-restore' mlx-vision --wait`. Test: `test_review_focus_5_tools_path_with_a_space` (Task 7).

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `bin/story-server` | Modify (Tasks 1, 2) | `LOCK_FILE`, `LOCK_TIMEOUT`, `lock_take`, `cmd_lockinfo`, the lock at every start and stop, fd 9 hygiene, header and usage (VS1-VS5, VS7-VS9); `tree_pids` instead of `engine_pids`, the M31 orphan warning, `extract_served_id` preferring `"loaded": true` (VS6, VS10). |
| `bin/story-server-restore` | Modify (Task 3) | `lock_holder`, `alive`, `launch` (double fork), `wait_done`, the VRS2 order, the docstring (VRS1-VRS5). |
| `character_dataset.py` | Modify (Task 4) | `restore_story_server(wait=False)` returning the exit code; `_build_dataset` restores with `wait=True` (VC1). |
| `movie_ui_lib.py` | Modify (Tasks 5-10) | The VLM section: constants, `vlm_lifecycle_enabled`, `vlm_tools_dir`, `vlm_port`, `job_vlm`, `effective_vlm`, `next_queued_job`, `vlm_restore_wanted`, `vlm_health`, `vlm_preflight`, `_vlm_step`, `_stop_tool`, `_vlm_other_mode`, `vlm_postflight`, `_vlm_recheck`, `recovery_restore`; `create_job` writes `vlm`; `run_job` steps 3b and 7; `startup_recovery` and `dispatch_tick` hooks; `story_server_probe`, `_story_server_pair`, `story_server_record`; `import http.client`. |
| `static/movie-ui/app.js`, `static/movie-ui/app.css` | Modify (Task 10) | The write-story gate without `story_server`; `.check-warn`. |
| `tests/conftest.py` | Modify (Task 5) | Autouse `vlm_lifecycle_isolation`. |
| `tests/test_vlm_lifecycle.py` | Create (Task 5), Append (Tasks 6-12) | VL1-VL28, F-TOOLS, F-HTTP, Review Focus 1, 2, 4, 5. |
| `tests/test_story_server.py` | Modify (Tasks 1, 2) | VLS1-VLS13; the 11.4 edits of S1, S4/S5, S14 and `_base_env`; S18 (Plan decision 1). |
| `tests/test_clean_stop.py` | Modify (Task 3) | F-SS; CS6's pgid parse; VLR1-VLR9; Review Focus 3. |
| `tests/test_character_tool.py` | Modify (Task 4) | `_Fakes`' restore fake; K9, K13, K20; VLC1. |
| `tests/test_movie_ui_jobs.py` | Modify (Task 5) | The `job.json` key set adds `vlm`. |
| `tests/test_movie_ui_builder.py` | Modify (Tasks 6, 13) | MUT25's import allowlist adds `http.client` (Task 6); `test_mut26` `BASELINE` (Task 13, test-only commit). |

The task order follows the interfaces: the story-server lock, then port scoping (both consumed by the restore), then the restore (consumed by `character_dataset.py` and by the runner's tools), then `character_dataset.py`, then `movie_ui_lib` from the inside out (policy, health, preflight, runner and postflight, startup restore), then the submit-time warning and the page, then the escape-hatch pins, then the end-to-end cancel-and-kill test, then the review and the test-only re-baseline.

---

## Before Task 1: baseline record (controller; no code, no commit)

VK6 compares against the pass count recorded here. Nothing is written into the repository.

- [ ] **Step 1: Confirm the starting point.**

```bash
cd /Users/reubenpatterson/local_agent_harness/qwen-agent-workspace
git rev-parse --short HEAD                        # expected: 168b2e8
git status --short                                # expected: only ?? ../.claude/, ?? ../agent/__pycache__/, ?? ../bin/, ?? .claude/ (and ?? ../.DS_Store if present)
ls tests/test_vlm_lifecycle.py 2>&1 | grep -c "No such file"   # expected: 1
wc -l < bin/story-server                          # expected: 692
wc -l < bin/story-server-restore                  # expected: 83
wc -l < movie_ui_lib.py                           # expected: 1795
grep -c "ENGINE_SCAN" bin/story-server            # expected: 3
```

If any expected value differs, stop and report: every Edit below was written against this tree.

- [ ] **Step 2: Record the pytest and script baselines (about 10 minutes).**

```bash
D=/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-25-vlm-lifecycle
mkdir -p $D
git rev-parse HEAD > $D/base-commit.txt
python3 -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
python3 tests/test_ltx_movie_offline.py 2>&1 | tail -1 | tee $D/baseline-offline.txt
```

Expected: the `FAILED` lines are exactly the three known pre-existing failures of Global Constraints; the offline script prints `OK n/n`. Write any other difference into `$D/baseline-notes.txt`; Task 13 compares against what is recorded here.

---
### Task 1: bin/story-server: the exclusive lock and `lockinfo`

Implements VS1 (the lock constants), VS2, VS3, VS4, VS5, VS7, VS8 (M30, M32-M37), VS9. Tests VLS1-VLS7, VLS10, VLS12; the 11.4 edits of `test_s1_usage` and `test_s4_s5_idempotence_during_load_and_stop`; the S18 rewrite of Plan decision 1.

**Files:**
- Modify: `bin/story-server` (header `:11-20`; constants after `:79`; `lock_take` after `add_pid` `:262-268`; `cmd_serve` `:276`; the three spawn lines `:380`, `:387`, `:392`; the warm-up `:465`; `cmd_lockinfo` before the entry point `:649`; usage and dispatch `:655-692`)
- Modify: `tests/test_story_server.py` (imports; `test_s1_usage` `:310`; `test_s4_s5_idempotence_during_load_and_stop` `:389-398`; `test_s18_stop_text_before_bind_via_serve_cmd_pids` `:882-917`; append VLS tests)

**Interfaces:**
- Consumes: `bin/story-server`'s `say`, `die2`, `$PY`, `$STATE_DIR`, `$HEALTH_URL`, `add_pid` (all existing).
- Produces: `bin/story-server lockinfo` printing exactly one line, `lock: free path=<LOCK_FILE>` or `lock: held pid=<pid> cmd=<cmd> since=<ts> path=<LOCK_FILE>` (spec 2.4), exit 0; the lock file `$STATE_DIR/story-server.lock` holding `<story-server pid> <cmd> <UTC ts>\n` while held (spec 2.3); exit codes 0 (same-mode start in progress, M35), 3 (other-mode start in progress, M36), 4 (lock file unopenable for a start, M34), 7 (lock wait timed out, M33). Task 3's `story-server-restore` parses the `lockinfo` line; Task 2 builds on the same script. In `tests/test_story_server.py`: `_lock_path(env)`, `_hold_lock(path, cmd, pid) -> fd`, `_release_later(fd, seconds) -> threading.Timer`, `_lockinfo(env)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_vls1_lockinfo`, `test_vls2_a_start_holds_the_lock_for_its_whole_load`, `test_vls3_three_concurrent_starts_spawn_one_server`, `test_vls4_stop_preempts_a_load`, `test_vls5_stop_waits_for_a_stop`, `test_vls6_a_reused_pid_never_takes_a_fast_path_or_a_signal`, `test_vls7_the_server_does_not_hold_the_lock`, `test_vls10_a_start_waits_for_a_stop`, `test_vls12_an_unopenable_lock`.

**1.1.** Edit `tests/test_story_server.py`: replace this text, which occurs exactly once:

```python
import json
import os
import re
```

with:

```python
import fcntl
import json
import os
import re
```

**1.2.** Edit `tests/test_story_server.py`: replace this text, which occurs exactly once:

```python
import sys
import time

import pytest
```

with:

```python
import sys
import threading
import time

import pytest
```

**1.3.** Edit `tests/test_story_server.py`: replace this text, which occurs exactly once:

```python
        assert proc.stderr == "usage: story-server [vision|text|mlx-vision|status|stop]\n", args
```

with:

```python
        assert proc.stderr == "usage: story-server [vision|text|mlx-vision|status|stop|lockinfo]\n", args
```

**1.4.** Edit `tests/test_story_server.py`: replace this text, which occurs exactly once:

```python
        rc4, out4, err4 = _run(["stop"], env, timeout=90)
        assert rc4 == 0
        assert "stopped pid(s)" in out4 and mode_pid_s in out4  # M24
        assert not _pid_alive(mode_pid)
        assert not os.path.exists(mode_file)
        assert os.path.exists(standdown)

        out1, err1 = proc1.communicate(timeout=90)
        assert proc1.returncode == 5
        assert "FAILED" in err1                                 # M18
```

with:

```python
        rc4, out4, err4 = _run(["stop"], env, timeout=90)
        assert rc4 == 0
        # The stop preempts the start that holds the lock (VLM lifecycle spec VS2, M30); the
        # start's interrupt trap kills its half-loaded server, so the stop finds nothing left.
        assert "preempting the vision start in progress (story-server pid %d)" % proc1.pid in out4
        assert not _pid_alive(mode_pid)
        assert not os.path.exists(mode_file)
        assert os.path.exists(standdown)

        out1, err1 = proc1.communicate(timeout=90)
        assert proc1.returncode == 5
        assert "interrupted during load" in err1
```

**1.5.** Edit `tests/test_story_server.py`: replace this text, which occurs exactly once:

```python
    """MF-C for text mode: the mode file is gone and the port was never bound, so
    `serve_cmd_pids` is the ONLY thing that can find the loading MTPLX. Its awk predicate
    must carry the R5 module literal or `stop` prints M23 and the loader survives holding
    the memory the render needs."""
    port = _free_port()
    env = _base_env(tmp_path, port)
    env["STUB_LOAD_DELAY"] = "0"
    env["STUB_MODE"] = "never"
    env["STORY_SERVER_READY_TIMEOUT"] = "60"
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")

    proc1 = subprocess.Popen([STORY_SERVER, "text"], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        _wait_for_file(mode_file, timeout=10)
        with open(mode_file) as f:
            _mode, mode_pid_s, _ts = f.read().split()
        mode_pid = int(mode_pid_s)
        cmd = _wait_for_cmd(mode_pid_s, " -m mtplx.server.openai ", timeout=10)
        assert "mtplx serve" not in cmd, cmd

        os.remove(mode_file)          # the Ctrl-C / hand-deleted case

        rc, out, err = _run(["stop"], env, timeout=90)
        assert rc == 0, err
        assert "stopped pid(s)" in out and mode_pid_s in out           # M24
        assert not _pid_alive(mode_pid)

        out1, err1 = proc1.communicate(timeout=90)
        assert proc1.returncode == 5
        assert "FAILED" in err1                                        # M18
    finally:
        if proc1.poll() is None:
            proc1.kill()
            proc1.wait(timeout=10)
```

with:

```python
    """MF-C for text mode: the mode file is gone and the port was never bound, so
    `serve_cmd_pids` is the ONLY thing that can find the loading MTPLX. Its awk predicate
    must carry the R5 module literal or `stop` prints M23 and the loader survives holding
    the memory the render needs. (VLM lifecycle spec VS2: a loader whose `story-server text`
    still runs is now preempted through the lock, so this case starts the loader by hand --
    the hand-started case serve_cmd_pids exists for -- and no story-server holds the lock.)"""
    port = _free_port()
    env = _base_env(tmp_path, port)
    env["STUB_LOAD_DELAY"] = "0"
    env["STUB_MODE"] = "never"
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")

    loader = subprocess.Popen([env["STORY_SERVER_MTPLX_BIN"], "serve"], env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Reap the loader the moment it dies: kill_set's `kill -0` would see an unreaped child of
    # this test as alive and wait the full 70 s.
    reaper = threading.Thread(target=loader.wait, daemon=True)
    reaper.start()
    try:
        cmd = _wait_for_cmd(loader.pid, " -m mtplx.server.openai ", timeout=10)
        assert "mtplx serve" not in cmd, cmd
        assert not os.path.exists(mode_file)

        rc, out, err = _run(["stop"], env, timeout=90)
        assert rc == 0, err
        assert "stopped pid(s)" in out and str(loader.pid) in out      # M24
        reaper.join(timeout=10)
        assert loader.returncode is not None
    finally:
        if loader.poll() is None:
            loader.kill()
            loader.wait(timeout=10)
```

**1.6.** Append to `tests/test_story_server.py`:

```python
# ---------------------------------------------------------------------------
# VLS1-VLS7, VLS10, VLS12: the story-server lock (VLM lifecycle spec VS1-VS5, VS7-VS9)
# ---------------------------------------------------------------------------

LOCK_TS = "2026-10-25T00:00:00Z"


def _lock_path(env):
    return os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server.lock")


def _hold_lock(path, cmd, pid):
    """Take the story-server lock in this test process with the record "<pid> <cmd> <ts>", the
    way a story-server holder writes it (spec 2.3); returns the fd, and os.close releases it.
    The fd is not inherited by any child (PEP 446)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    os.ftruncate(fd, 0)
    os.write(fd, ("%d %s %s\n" % (pid, cmd, LOCK_TS)).encode("ascii"))
    return fd


def _release_later(fd, seconds):
    timer = threading.Timer(seconds, os.close, args=(fd,))
    timer.start()
    return timer


def _lockinfo(env):
    return _run(["lockinfo"], env)


def test_vls1_lockinfo(tmp_path):
    env = _base_env(tmp_path, _free_port())
    path = _lock_path(env)
    assert not os.path.exists(path)
    assert _lockinfo(env) == (0, "lock: free path=%s\n" % path, "")
    fd = _hold_lock(path, "stop", os.getpid())
    try:
        assert _lockinfo(env) == (
            0, "lock: held pid=%d cmd=stop since=%s path=%s\n" % (os.getpid(), LOCK_TS, path), "")
    finally:
        os.close(fd)
    assert _lockinfo(env) == (0, "lock: free path=%s\n" % path, "")


def test_vls2_a_start_holds_the_lock_for_its_whole_load(tmp_path):
    env = _base_env(tmp_path, _free_port())
    env["STUB_LOAD_DELAY"] = "5"
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")
    proc1 = subprocess.Popen([STORY_SERVER, "vision"], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        _wait_for_file(mode_file, timeout=10)
        rc, out, err = _lockinfo(env)
        assert rc == 0
        assert out.startswith("lock: held pid=%d cmd=vision since=" % proc1.pid), out
        out1, err1 = proc1.communicate(timeout=60)
        assert proc1.returncode == 0, err1
        assert _lockinfo(env)[1] == "lock: free path=%s\n" % _lock_path(env)
    finally:
        if proc1.poll() is None:
            proc1.kill()
            proc1.wait(timeout=10)
        _run(["stop"], env, timeout=30)


def test_vls3_three_concurrent_starts_spawn_one_server(tmp_path):
    env = _base_env(tmp_path, _free_port())
    env["STUB_LOAD_DELAY"] = "3"
    procs = [subprocess.Popen([STORY_SERVER, "vision"], env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) for _ in range(3)]
    try:
        results = [p.communicate(timeout=90) for p in procs]
        assert [p.returncode for p in procs] == [0, 0, 0], results
        winners = [p.pid for p, (out, _err) in zip(procs, results)
                   if "launched vision server, pid" in out]
        assert len(winners) == 1, results
        fast = [out for out, _err in results
                if ("a vision start (story-server pid %d) is already running; it may still be "
                    "loading -- poll http://127.0.0.1:%s/v1/models"
                    % (winners[0], env["STORY_SERVER_PORT"])) in out]
        assert len(fast) == 2, results
        assert _count_server_procs(env) == 1
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=10)
        _run(["stop"], env, timeout=30)


def test_vls4_stop_preempts_a_load(tmp_path):
    env = _base_env(tmp_path, _free_port())
    env["STUB_LOAD_DELAY"] = "30"
    env["STORY_SERVER_READY_TIMEOUT"] = "60"
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")
    proc1 = subprocess.Popen([STORY_SERVER, "vision"], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        _wait_for_file(mode_file, timeout=10)
        rc, out, err = _run(["stop"], env, timeout=90)
        assert rc == 0, err
        assert ("story-server: preempting the vision start in progress (story-server pid %d)\n"
                % proc1.pid) in out
        out1, err1 = proc1.communicate(timeout=90)
        assert proc1.returncode == 5
        assert "interrupted during load" in err1
        assert _count_server_procs(env) == 0
        assert not os.path.exists(mode_file)
    finally:
        if proc1.poll() is None:
            proc1.kill()
            proc1.wait(timeout=10)


def test_vls5_stop_waits_for_a_stop(tmp_path):
    env = _base_env(tmp_path, _free_port())
    path = _lock_path(env)
    env["STORY_SERVER_LOCK_TIMEOUT"] = "2"
    fd = _hold_lock(path, "stop", os.getpid())
    try:
        rc, out, err = _run(["stop"], env, timeout=30)
    finally:
        os.close(fd)
    assert rc == 7
    assert err == ("story-server: TIMEOUT: %s is still held by pid %d (stop since %s) after 2s; "
                   "not running stop\n" % (path, os.getpid(), LOCK_TS))
    env["STORY_SERVER_LOCK_TIMEOUT"] = "30"
    fd = _hold_lock(path, "stop", os.getpid())
    timer = _release_later(fd, 1.0)
    started = time.monotonic()
    try:
        rc, out, err = _run(["stop"], env, timeout=60)
    finally:
        timer.join()
    assert rc == 0, err
    assert time.monotonic() - started >= 1.0
    assert "nothing to stop" in out


def test_vls6_a_reused_pid_never_takes_a_fast_path_or_a_signal(tmp_path):
    env = _base_env(tmp_path, _free_port())
    env["STORY_SERVER_LOCK_TIMEOUT"] = "2"
    path = _lock_path(env)
    # A live process whose command line lacks "story-server" stands in for a reused pid.
    sleeper = subprocess.Popen(["/bin/sleep", "60"])
    fd = _hold_lock(path, "vision", sleeper.pid)
    try:
        for args, absent in ((["stop"], "preempting"), (["vision"], "already running"),
                             (["text"], "REFUSING")):
            rc, out, err = _run(args, env, timeout=30)
            assert rc == 7, (args, out, err)
            assert absent not in out + err, args
            assert ("story-server: TIMEOUT: %s is still held by pid %d (vision since %s) after "
                    "2s; not running %s\n" % (path, sleeper.pid, LOCK_TS, args[0])) == err, args
            assert sleeper.poll() is None, args
    finally:
        os.close(fd)
        sleeper.kill()
        sleeper.wait(timeout=10)


def test_vls7_the_server_does_not_hold_the_lock(tmp_path):
    env = _base_env(tmp_path, _free_port())
    env["STUB_LOAD_DELAY"] = "0"
    rc, out, err = _run(["vision"], env, timeout=60)
    try:
        assert rc == 0, err
        assert _count_server_procs(env) == 1
        assert _lockinfo(env)[1] == "lock: free path=%s\n" % _lock_path(env)
    finally:
        _run(["stop"], env, timeout=30)


def test_vls10_a_start_waits_for_a_stop(tmp_path):
    env = _base_env(tmp_path, _free_port())
    env["STUB_LOAD_DELAY"] = "0"
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")
    fd = _hold_lock(_lock_path(env), "stop", os.getpid())
    proc1 = subprocess.Popen([STORY_SERVER, "vision"], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        time.sleep(2.0)
        assert proc1.poll() is None
        assert not os.path.exists(mode_file)      # still waiting for the lock: nothing spawned
        os.close(fd)
        fd = None
        out1, err1 = proc1.communicate(timeout=60)
        assert proc1.returncode == 0, err1
        assert "launched vision server, pid" in out1
        assert _count_server_procs(env) == 1
    finally:
        if fd is not None:
            os.close(fd)
        if proc1.poll() is None:
            proc1.kill()
            proc1.wait(timeout=10)
        _run(["stop"], env, timeout=30)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_vls12_an_unopenable_lock(tmp_path):
    env = _base_env(tmp_path, _free_port())
    ro = tmp_path / "ro"
    ro.mkdir()
    env["STORY_SERVER_STATE_DIR"] = str(ro / "state")
    lock = os.path.join(str(ro), "state", "story-server.lock")
    os.chmod(str(ro), 0o500)
    try:
        rc, out, err = _run(["stop"], env)
        assert rc == 0, err
        assert ("story-server: WARNING: cannot open the lock file %s; stopping without the lock\n"
                % lock) in out
        assert "nothing to stop" in out
        assert not os.path.exists(lock)
        rc, out, err = _run(["vision"], env)
        assert rc == 4
        assert err == ("story-server: cannot open the lock file %s; refusing to run vision "
                       "without it\n" % lock)
        assert _count_server_procs(env) == 0
    finally:
        os.chmod(str(ro), 0o700)
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_story_server.py -k "vls or s1_usage or s4_s5" 2>&1 | tail -3
```

Expected: `11 failed, 20 deselected`: `test_s1_usage` (the usage text), `test_s4_s5_idempotence_during_load_and_stop` (no `preempting` line) and all nine VLS tests (`lockinfo` is not a subcommand yet, nothing waits for or refuses on a lock, and HEAD's `stop` prints no M37). The rewritten `test_s18_stop_text_before_bind_via_serve_cmd_pids` passes before and after this task (it pins the hand-started case on the new setup).

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/story-server`: replace this text, which occurs exactly once:

```bash
# Contract and known hazards (plan D2/R1/R3 -- these are documented, NOT defended in
# code; there is no lock file and no health watchdog):
#   * `vision` and `text` are idempotent: they exit 0 when the requested mode is
#     already serving OR still loading. There is no `ensure` subcommand, because it
#     would be a second name for that same behaviour.
#   * Switching modes is `stop` then `vision`/`text`. Nothing else switches modes.
#   * (R1) The mode file is the ONLY discriminator during the load window, because
#     vLLM binds the port only after the model is resident (measured: still unbound
#     after 7m29s). If you delete it by hand mid-load, the next `vision` sees a free
#     port and spawns a SECOND ~22 GiB server, which will OOM this host.
```

with:

```bash
# Contract and known hazards (plan D2/R1/R3 -- the lock is defended in code (VLM
# lifecycle spec VS2); there is no health watchdog):
#   * `vision` and `text` are idempotent: they exit 0 when the requested mode is
#     already serving OR still loading. There is no `ensure` subcommand, because it
#     would be a second name for that same behaviour.
#   * Switching modes is `stop` then `vision`/`text`. Nothing else switches modes.
#   * vision/text/mlx-vision and stop hold an exclusive flock on $STATE_DIR/story-server.lock for
#     their whole run; status and lockinfo never take it. A start that finds a start of the same
#     mode in progress exits 0, of another mode exits 3; a stop in progress makes it wait. A stop
#     that finds a start in progress SIGTERMs that start (its trap kills the half-loaded server)
#     and waits. A wait gives up after STORY_SERVER_LOCK_TIMEOUT s (exit 7).
#   * (R1) The mode file is the ONLY discriminator during the load window, because
#     vLLM binds the port only after the model is resident (measured: still unbound
#     after 7m29s). A second start during the load is now refused by the lock, whatever
#     the mode file says.
```

**3.2.** Edit `bin/story-server`: replace this text, which occurs exactly once:

```bash
STANDDOWN="$STATE_DIR/stand-down"
```

with:

```bash
STANDDOWN="$STATE_DIR/stand-down"
LOCK_FILE="$STATE_DIR/story-server.lock"
# Longest legitimate hold: a start's readiness poll (READY_TIMEOUT 840 s) + warm-up (WARM_TIMEOUT
# 300 s) + one kill_set (60 + 10 s) + probe slack = 1260 s (VLM lifecycle spec 2.5).
LOCK_TIMEOUT="${STORY_SERVER_LOCK_TIMEOUT:-1260}"
```

**3.3.** Edit `bin/story-server`: replace this text, which occurs exactly once:

```bash
    printf '%s' "${list:+$list }$p"
}
```

with:

```bash
    printf '%s' "${list:+$list }$p"
}

# Takes the exclusive story-server lock for CMD and keeps it on fd 9 until this script exits
# (VLM lifecycle spec VS2). Exits the script itself on the fast paths (0: same-mode start already
# running; 3: other-mode start running), on timeout (7) and when the lock file cannot be opened (4;
# a stop then warns and continues without the lock, so a host without $STATE_DIR can still stop).
lock_take() {
    /bin/mkdir -p "$STATE_DIR" 2>/dev/null
    if ! { : >>"$LOCK_FILE"; } 2>/dev/null; then
        if [ "$1" = "stop" ]; then
            say "WARNING: cannot open the lock file $LOCK_FILE; stopping without the lock"   # M37
            return 0
        fi
        die2 "cannot open the lock file $LOCK_FILE; refusing to run $1 without it"   # M34
        exit 4
    fi
    exec 9>>"$LOCK_FILE"
    "$PY" - "$$" "$1" "$LOCK_TIMEOUT" "$LOCK_FILE" "$HEALTH_URL" <<'LOCKPY'
import fcntl, os, signal, subprocess, sys, time
owner, cmd, timeout, path, url = int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]
SERVE = ("vision", "text", "mlx-vision")
def say(text, err=False):
    stream = sys.stderr if err else sys.stdout
    stream.write("story-server: " + text + "\n")
    stream.flush()
def holder():
    try:
        with open(path) as f:
            parts = f.read().split()
    except OSError:
        parts = []
    parts = (parts + ["?", "?", "?"])[:3]
    pid = int(parts[0]) if parts[0].isdigit() else None
    alive = False
    if pid is not None:
        try:
            os.kill(pid, 0)
            alive = True
        except ProcessLookupError:
            alive = False
        except PermissionError:
            alive = True
    return pid, parts[0], parts[1], parts[2], alive
def is_story_server(pid):
    try:
        line = subprocess.run(["/bin/ps", "-ww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        line = ""
    return "story-server" in line
start = time.monotonic()
next_note = 30
preempted = None
while True:
    try:
        fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
        break
    except BlockingIOError:
        pass
    pid, pid_text, held, since, alive = holder()
    if alive and held in SERVE and cmd in SERVE and is_story_server(pid):
        if held == cmd:
            say("a %s start (story-server pid %s) is already running; it may still be loading -- poll %s" % (cmd, pid_text, url))
            sys.exit(20)
        say("REFUSING: a %s start (story-server pid %s) is already running; run \"story-server stop\" first, then start %s" % (held, pid_text, cmd), err=True)
        sys.exit(3)
    if alive and held in SERVE and cmd == "stop" and preempted != pid:
        if is_story_server(pid):
            say("preempting the %s start in progress (story-server pid %d)" % (held, pid))
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        preempted = pid
    waited = int(time.monotonic() - start)
    if waited >= timeout:
        say("TIMEOUT: %s is still held by pid %s (%s since %s) after %ds; not running %s" % (path, pid_text, held, since, waited, cmd), err=True)
        sys.exit(7)
    if waited >= next_note:
        say("waiting for the lock held by pid %s (%s since %s) (%ds elapsed)" % (pid_text, held, since, waited))
        next_note += 30
    time.sleep(1)
os.ftruncate(9, 0)
os.write(9, ("%d %s %s\n" % (owner, cmd, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))).encode("ascii"))
LOCKPY
    local rc=$?
    case "$rc" in
        0)  return 0 ;;
        20) exit 0 ;;
        *)  exit "$rc" ;;
    esac
}
```

**3.4.** Edit `bin/story-server`: replace this text, which occurs exactly once:

```bash
    say "v1 cmd=$CMD port=$PORT state-dir=$STATE_DIR"   # M00

    local mf_ok=1
```

with:

```bash
    say "v1 cmd=$CMD port=$PORT state-dir=$STATE_DIR"   # M00
    lock_take "$MODE"                # VS2: exits on the fast paths, on timeout and on M34

    local mf_ok=1
```

**3.5.** Edit `bin/story-server`: replace this text, which occurs exactly once:

```bash
            --gpu-memory-utilization "$VISION_GPU_MEM_UTIL" \
            >>"$log" 2>&1 </dev/null &
```

with:

```bash
            --gpu-memory-utilization "$VISION_GPU_MEM_UTIL" \
            >>"$log" 2>&1 </dev/null 9>&- &
```

**3.6.** Edit `bin/story-server`: replace this text, which occurs exactly once:

```bash
            --max-tokens "$MLX_VISION_MAX_TOKENS" \
            >>"$log" 2>&1 </dev/null &
```

with:

```bash
            --max-tokens "$MLX_VISION_MAX_TOKENS" \
            >>"$log" 2>&1 </dev/null 9>&- &
```

**3.7.** Edit `bin/story-server`: replace this text, which occurs exactly once:

```bash
            --model-id "$MODEL_ID" --port "$PORT" --profile "$TEXT_PROFILE" \
            >>"$log" 2>&1 </dev/null &
```

with:

```bash
            --model-id "$MODEL_ID" --port "$PORT" --profile "$TEXT_PROFILE" \
            >>"$log" 2>&1 </dev/null 9>&- &
```

**3.8.** Edit `bin/story-server`: replace this text, which occurs exactly once:

```bash
           -X POST "$CHAT_URL" --data-binary @- <<EOF
```

with:

```bash
           -X POST "$CHAT_URL" --data-binary @- 9>&- <<EOF
```

**3.9.** Edit `bin/story-server`: replace this text, which occurs exactly once:

```bash
# ---------------------------------------------------------------------------
# entry point and dependency gate
# ---------------------------------------------------------------------------
```

with:

```bash
# ---------------------------------------------------------------------------
# lockinfo (VLM lifecycle spec VS4): never takes the lock
# ---------------------------------------------------------------------------

cmd_lockinfo() {
    if [ ! -e "$LOCK_FILE" ]; then
        printf 'lock: free path=%s\n' "$LOCK_FILE"
        exit 0
    fi
    "$PY" - "$LOCK_FILE" <<'PROBEPY'
import fcntl, os, sys
path = sys.argv[1]
try:
    fd = os.open(path, os.O_RDONLY)
except OSError:
    print("lock: free path=%s" % path)
    sys.exit(0)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    with open(path) as f:
        parts = (f.read().split() + ["?", "?", "?"])[:3]
    print("lock: held pid=%s cmd=%s since=%s path=%s" % (parts[0], parts[1], parts[2], path))
else:
    fcntl.flock(fd, fcntl.LOCK_UN)
    print("lock: free path=%s" % path)
PROBEPY
    exit 0
}

# ---------------------------------------------------------------------------
# entry point and dependency gate
# ---------------------------------------------------------------------------
```

**3.10.** Edit `bin/story-server`: replace this text, which occurs exactly once:

```bash
                        && [ "$CMD" != "status" ] && [ "$CMD" != "stop" ]; }; then
    printf 'usage: story-server [vision|text|mlx-vision|status|stop]\n' >&2   # M01
```

with:

```bash
                        && [ "$CMD" != "status" ] && [ "$CMD" != "stop" ] \
                        && [ "$CMD" != "lockinfo" ]; }; then
    printf 'usage: story-server [vision|text|mlx-vision|status|stop|lockinfo]\n' >&2   # M01
```

**3.11.** Edit `bin/story-server`: replace this text, which occurs exactly once:

```bash
    stop)
        say "v1 cmd=$CMD port=$PORT state-dir=$STATE_DIR"   # M00
        cmd_stop
        ;;
esac
```

with:

```bash
    stop)
        say "v1 cmd=$CMD port=$PORT state-dir=$STATE_DIR"   # M00
        lock_take stop
        cmd_stop
        ;;
    lockinfo)
        cmd_lockinfo
        ;;
esac
```

- [ ] **Step 4: Run the tests and confirm they pass; check the shell syntax.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_story_server.py 2>&1 | tail -3
/bin/bash -n bin/story-server && bash -n bin/story-server && echo "syntax ok"
```

Expected: `1 failed, 30 passed` (about 70 seconds); the one failure is the pre-existing `test_s14_source_guards` (host paths; Task 2 realigns it). Then `syntax ok`. The compile check with `FILES` = `tests/test_story_server.py`; expected `compiled 1` twice.

- [ ] **Step 5: Commit.**

```bash
git add bin/story-server tests/test_story_server.py
git diff --cached --name-only    # expected: qwen-agent-workspace/bin/story-server, qwen-agent-workspace/tests/test_story_server.py
git commit -m "feat(story-server): exclusive start/stop lock and lockinfo (VLM lifecycle VS1-VS5, VS7-VS9; VLS1-VLS7, VLS10, VLS12)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: bin/story-server: the port-owner tree replaces the EngineCore sweep; the loaded model

Implements VS1 (the `ENGINE_SCAN` deletion), VS6 (`tree_pids`, M31), VS10. Tests VLS8, VLS9, VLS11, VLS13; the 11.4 edits of `test_s14_source_guards` and `_base_env`. From this task's commit on, `test_s14_source_guards` passes.

**Files:**
- Modify: `bin/story-server` (`ENGINE_SCAN` `:95-103`; `extract_served_id` `:130-137`; `engine_pids` `:190-195`; `tree_pids` after `serve_cmd_pids` `:247-258`; the kill sets of `on_interrupt` `:405`, M18 `:431`, M19 `:444`; `cmd_stop` `:567-601`)
- Modify: `tests/test_story_server.py` (imports; `_base_env` `:191-195`; `test_s14_source_guards` `:705-725`; append VLS tests)

**Interfaces:**
- Consumes: Task 1's `bin/story-server` (`lock_take`, `cmd_lockinfo`, the `9>&-` spawn lines) and its test helpers.
- Produces: `tree_pids "<space-separated root pids>"` (stdout: space-separated live descendants, the roots excluded; spec VS6); `story-server stop` never adds a pid outside the port-owner tree, the mode-file pid's tree and the port's `serve` argv matches, and prints M31 for every `VLLM::EngineCore` with parent pid 1 outside that set; `story-server status` reports the `"loaded": true` entry's id as `model=` (VS10). Task 6's health check reads that `model=`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_vls8_stop_kills_the_port_owner_tree_and_nothing_outside_it`, `test_vls9_an_orphan_engine_core_survives_and_is_named`, `test_vls11_source_guards_for_the_lock_and_the_port_tree`, `test_vls13_status_prefers_the_loaded_model`.

Do **not** touch `_base_env` in this step: until Step 3 removes HEAD's host-wide sweep, its `STORY_SERVER_ENGINE_SCAN = "0"` line is what keeps the Step 2 run from SIGKILLing a real `VLLM::EngineCore` (Global Constraints, Safety).

**1.1.** Edit `tests/test_story_server.py`: replace this text, which occurs exactly once:

```python
import fcntl
import json
```

with:

```python
import fcntl
import http.server
import json
```

**1.2.** Edit `tests/test_story_server.py`: replace this text, which occurs exactly once:

```python
import socket
import stat
```

with:

```python
import signal
import socket
import stat
```

**1.3.** Edit `tests/test_story_server.py`: replace this text, which occurs exactly once:

```python
    expected_constants = {
        "STORY_SERVER_WS": "/Users/reubenpatterson/local_model_harness/qwen-agent-workspace",
        "STORY_SERVER_MODEL_ID": "qwen38-6bit",
        "STORY_SERVER_PORT": "8177",
        "STORY_SERVER_VISION_MODEL_DIR": "/Users/reubenpatterson/mlx_models/qwen3-vl",
        "STORY_SERVER_VLLM_BIN": "/Users/reubenpatterson/.venv-vllm-metal/bin/vllm",
        "STORY_SERVER_MTPLX_BIN": "/opt/homebrew/bin/mtplx",
        "STORY_SERVER_MTPLX_VERSION": "2.10.1",
        "STORY_SERVER_TEXT_MODEL_REPO": DEFAULT_TEXT_MODEL_REPO,
        "STORY_SERVER_STATE_DIR": "/Users/reubenpatterson/.qwen-serve-guard",
        "STORY_SERVER_LSOF": "/usr/sbin/lsof",
        "STORY_SERVER_PY": "/usr/bin/python3",
        "STORY_SERVER_READY_TIMEOUT": "840",
        "STORY_SERVER_READY_POLL": "5",
        "STORY_SERVER_WARM_TIMEOUT": "300",
        "STORY_SERVER_ENGINE_SCAN": "1",
        "STORY_SERVER_VISION_GPU_MEM_UTIL": "0.70",
        "STORY_SERVER_MLX_VISION_MODEL_ID": "andrevp/Qwen3.5-9B-Distilled-OPUS-Heretic-MLX-VLM-8bit",
        "STORY_SERVER_MLX_VLM_PYTHON": "python3",
        "STORY_SERVER_MLX_VISION_MAX_TOKENS": "16384",
    }
```

with:

```python
    # The host values are bin/story-server's macstudio defaults (VLM lifecycle spec 11.4, G5):
    # a future host-adapt of those defaults must update this table in the same commit.
    expected_constants = {
        "STORY_SERVER_WS": "/Users/ailab1/local_agent_harness/qwen-agent-workspace",
        "STORY_SERVER_MODEL_ID": "qwen38-6bit",
        "STORY_SERVER_PORT": "8177",
        "STORY_SERVER_VISION_MODEL_DIR": "/Users/ailab1/mlx_models/qwen3-vl",
        "STORY_SERVER_VLLM_BIN": "/Users/ailab1/.venv-vllm-metal/bin/vllm",
        "STORY_SERVER_MTPLX_BIN": "/opt/homebrew/bin/mtplx",
        "STORY_SERVER_MTPLX_VERSION": "2.10.1",
        "STORY_SERVER_TEXT_MODEL_REPO": DEFAULT_TEXT_MODEL_REPO,
        "STORY_SERVER_STATE_DIR": "/Users/ailab1/.qwen-serve-guard",
        "STORY_SERVER_LSOF": "/usr/sbin/lsof",
        "STORY_SERVER_PY": "/usr/bin/python3",
        "STORY_SERVER_READY_TIMEOUT": "840",
        "STORY_SERVER_READY_POLL": "5",
        "STORY_SERVER_WARM_TIMEOUT": "300",
        "STORY_SERVER_LOCK_TIMEOUT": "1260",
        "STORY_SERVER_VISION_GPU_MEM_UTIL": "0.70",
        "STORY_SERVER_MLX_VISION_MODEL_ID": "/Users/ailab1/mlx_models/qwen3-vl",
        "STORY_SERVER_MLX_VLM_PYTHON": "/Users/ailab1/mlx-serve/bin/python",
        "STORY_SERVER_MLX_VISION_MAX_TOKENS": "16384",
    }
```

**1.4.** Append to `tests/test_story_server.py`:

```python
# ---------------------------------------------------------------------------
# VLS8, VLS9, VLS11, VLS13: port scoping and the loaded model (VLM lifecycle spec VS6, VS10)
# ---------------------------------------------------------------------------

# A loader whose own child is reachable only through its process tree: the child neither
# listens on the port nor carries a serve argv, so only tree_pids can find it.
TREE_STUB = """#!/bin/bash
if [ "${1:-}" = "-c" ]; then exit 0; fi
/usr/bin/python3 -c 'import os, sys, time; f = open(sys.argv[1] + ".tmp", "w"); f.write(str(os.getpid())); f.close(); os.rename(sys.argv[1] + ".tmp", sys.argv[1]); time.sleep(600)' "$TREE_CHILD_PID_FILE"
"""


def _read_pid_file(path, timeout=10):
    _wait_for_file(path, timeout=timeout)
    with open(path) as f:
        return int(f.read())


def test_vls8_stop_kills_the_port_owner_tree_and_nothing_outside_it(tmp_path):
    port = _free_port()
    env = _base_env(tmp_path, port)
    stub = str(tmp_path / "stub-bin" / "tree-stub")
    _write_executable(stub, TREE_STUB)
    child_file = str(tmp_path / "tree-child.pid")
    env["TREE_CHILD_PID_FILE"] = child_file
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")
    loader = subprocess.Popen([stub, "-m", "mlx_vlm.server", "--port", str(port)], env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    threading.Thread(target=loader.wait, daemon=True).start()
    # Outside the tree: a test child named like a vLLM engine (not an orphan, not on the port).
    # bash's exec -a sets argv[0]; the framework Python would replace an argv[0] given to it.
    engine = subprocess.Popen(["/bin/bash", "-c", "exec -a VLLM::EngineCore /bin/sleep 60"])
    child = None
    try:
        assert _wait_for_cmd(engine.pid, "VLLM::EngineCore").startswith("VLLM::EngineCore")
        child = _read_pid_file(child_file)
        with open(mode_file, "w") as f:
            f.write("mlx-vision %d 2026-10-25T00:00:00Z\n" % loader.pid)
        rc, out, err = _run(["stop"], env, timeout=90)
        assert rc == 0, err
        stopped = out.split("stopped pid(s) ", 1)[1].split("\n", 1)[0].split()
        assert str(loader.pid) in stopped and str(child) in stopped, out
        assert str(engine.pid) not in stopped
        deadline = time.monotonic() + 10
        while _pid_alive(child) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not _pid_alive(child)
        assert engine.poll() is None
    finally:
        engine.kill()
        engine.wait(timeout=10)
        if loader.poll() is None:
            loader.kill()
        if child is not None and _pid_alive(child):
            os.kill(child, signal.SIGKILL)


def test_vls9_an_orphan_engine_core_survives_and_is_named(tmp_path):
    env = _base_env(tmp_path, _free_port())
    # A double-forked engine-named process: its parent becomes launchd (pid 1).
    launcher = ("import subprocess\n"
                "p = subprocess.Popen(['/bin/bash', '-c', 'exec -a VLLM::EngineCore /bin/sleep 60'], "
                "start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
                "stderr=subprocess.DEVNULL)\n"
                "print(p.pid)\n")
    orphan = int(subprocess.run([sys.executable, "-c", launcher], capture_output=True, text=True,
                                timeout=30).stdout)
    try:
        assert _wait_for_cmd(orphan, "VLLM::EngineCore").startswith("VLLM::EngineCore")
        deadline = time.monotonic() + 10
        while (subprocess.run(["/bin/ps", "-o", "ppid=", "-p", str(orphan)], capture_output=True,
                              text=True).stdout.strip() != "1" and time.monotonic() < deadline):
            time.sleep(0.1)
        rc, out, err = _run(["stop"], env, timeout=30)
        assert rc == 0, err
        assert ("story-server: WARNING: VLLM::EngineCore pid %d has parent pid 1 and is not in "
                "port %s's process tree; left running (it may belong to another vLLM, such as "
                "the embed server on 8178)\n" % (orphan, env["STORY_SERVER_PORT"])) in out
        assert "nothing to stop" in out
        assert _pid_alive(orphan)
    finally:
        os.kill(orphan, signal.SIGKILL)


def test_vls11_source_guards_for_the_lock_and_the_port_tree():
    with open(STORY_SERVER) as f:
        text = f.read()
    assert "engine_pids" not in text and "ENGINE_SCAN" not in text
    spawn = [line for line in text.splitlines() if line.rstrip().endswith("</dev/null 9>&- &")]
    assert len(spawn) == 3, spawn
    assert '--data-binary @- 9>&- <<EOF' in text
    assert text.count('lock_take "$MODE"') == 1
    assert text.count("lock_take stop") == 1
    assert 'kill_set "$SPAWN_PID $(port_pids) $(tree_pids "$SPAWN_PID $(port_pids)")"' in text


def _json_server(port, body):
    raw = json.dumps(body).encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_vls13_status_prefers_the_loaded_model(tmp_path):
    port = _free_port()
    env = _base_env(tmp_path, port)
    model = "test-mlx-vlm-model"
    env["STORY_SERVER_MLX_VISION_MODEL_ID"] = model
    mode_file = os.path.join(env["STORY_SERVER_STATE_DIR"], "story-server-mode")
    sleeper = subprocess.Popen(["/bin/sleep", "60"])
    with open(mode_file, "w") as f:
        f.write("mlx-vision %d 2026-10-25T00:00:00Z\n" % sleeper.pid)
    try:
        for listing, state, served in (
                ([{"id": "other", "loaded": False}, {"id": model, "loaded": True}],
                 "SERVING mlx-vision", model),
                ([{"id": model}, {"id": "other"}], "SERVING mlx-vision", model),
                ([{"id": "other"}, {"id": model}], "FOREIGN pid", "other")):
            server = _json_server(port, {"object": "list", "data": listing})
            try:
                rc, out, err = _run(["status"], env)
            finally:
                server.shutdown()
                server.server_close()
            assert rc == 0, err
            assert "state:          %s" % state in out, (listing, out)
            assert re.search(r"health:\s+HTTP 200 model=%s\n" % re.escape(served), out), out
    finally:
        sleeper.kill()
        sleeper.wait(timeout=10)
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_story_server.py -k "vls8 or vls9 or vls11 or vls13 or s14" 2>&1 | tail -3
```

Expected: `4 failed, 1 passed, 30 deselected`: VLS8 (the loader's child is not in `stopped pid(s)`), VLS9 (no M31 line), VLS11 (`engine_pids` is still in the script) and VLS13 (the first listing reports `FOREIGN pid`). `test_s14_source_guards` already passes: Task 1 added the `STORY_SERVER_LOCK_TIMEOUT` default, the realigned table matches HEAD's host values, and the table no longer names `STORY_SERVER_ENGINE_SCAN`.

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/story-server`: replace this text, which occurs exactly once:

```bash
LOG_TAIL_LINES=40
# D9's VLLM::EngineCore sweep is host-global: it is deliberately NOT scoped by $PORT,
# so it reaps an EngineCore belonging to a vLLM on any port (R8, accepted in
# production -- this host runs at most one vLLM). That makes it unsafe for the
# offline test suite, which runs `stop` against an ephemeral port while a real vLLM
# may be loading on the production port: without this switch every `stop` in the
# suite silently adds the real EngineCore to its kill set. Set
# STORY_SERVER_ENGINE_SCAN=0 to disable the sweep. Production sets nothing; the
# default 1 is the contract.
ENGINE_SCAN="${STORY_SERVER_ENGINE_SCAN:-1}"
```

with:

```bash
LOG_TAIL_LINES=40
```

**3.2.** Edit `bin/story-server`: replace this text, which occurs exactly once:

```bash
# stdin: a /v1/models body. stdout: data[0].id, or empty on any failure.
extract_served_id() {
    "$PY" -c 'import json,sys
try:
    print(json.load(sys.stdin)["data"][0]["id"])
except Exception:
    print("")'
}
```

with:

```bash
# stdin: a /v1/models body. stdout: the id of the first entry with "loaded": true (mlx_vlm.server
# lists every cached model and flags the active one), else data[0].id, or empty on any failure.
extract_served_id() {
    "$PY" -c 'import json,sys
try:
    data = json.load(sys.stdin)["data"]
    loaded = [d["id"] for d in data if isinstance(d, dict) and d.get("loaded") is True]
    print(loaded[0] if loaded else data[0]["id"])
except Exception:
    print("")'
}
```

**3.3.** Edit `bin/story-server`: replace this text, which occurs exactly once:

```bash
# stdout: space-separated live VLLM::EngineCore pids (see D9).
engine_pids() {
    [ "$ENGINE_SCAN" = "1" ] || return 0
    /bin/ps -xww -o pid=,command= 2>/dev/null \
      | /usr/bin/awk '$2 ~ /^VLLM::EngineCore/ { printf "%s ", $1 }'
}

# Reads $MODE_FILE into MODE_REC / PID_REC / TS_REC (empty when absent/garbage).
```

with:

```bash
# Reads $MODE_FILE into MODE_REC / PID_REC / TS_REC (empty when absent/garbage).
```

**3.4.** Edit `bin/story-server`: replace this text, which occurs exactly once:

```bash
              index(cmd, " -m mlx_vlm.server") > 0) printf "%s ", pid }'
}
```

with:

```bash
              index(cmd, " -m mlx_vlm.server") > 0) printf "%s ", pid }'
}

# stdout: space-separated live descendants of the space-separated root pids in $1 (the roots
# themselves are not printed). Port-scoped by construction: callers pass only this port's
# server pids, so a vLLM on another port (the 8178 embed server) is never in the set.
tree_pids() {
    /bin/ps -A -o pid=,ppid= 2>/dev/null | /usr/bin/awk -v roots="$1" '
        BEGIN { n = split(roots, r, " ")
                for (i = 1; i <= n; i++) if (r[i] ~ /^[0-9]+$/ && r[i] + 0 > 1) want[r[i]] = 1 }
        { p[NR] = $1; pp[NR] = $2 }
        END { changed = 1
              while (changed) { changed = 0
                  for (i = 1; i <= NR; i++)
                      if ((pp[i] in want) && !(p[i] in want)) { want[p[i]] = 1; out = out p[i] " "; changed = 1 } }
              printf "%s", out }'
}
```

**3.5.** Edit `bin/story-server`: replace this text, which occurs exactly once:

```bash
        die2 "interrupted during load; killing the $MODE server (pid $SPAWN_PID) so it does not hold memory the render needs"
        kill_set "$SPAWN_PID $(port_pids) $(engine_pids)"
```

with:

```bash
        die2 "interrupted during load; killing the $MODE server (pid $SPAWN_PID) so it does not hold memory the render needs"
        kill_set "$SPAWN_PID $(port_pids) $(tree_pids "$SPAWN_PID $(port_pids)")"
```

**3.6.** Edit `bin/story-server`: replace this text, which occurs exactly once:

```bash
                kill_set "$SPAWN_PID $(port_pids) $(engine_pids)"
```

with:

```bash
                kill_set "$SPAWN_PID $(port_pids) $(tree_pids "$SPAWN_PID $(port_pids)")"
```

**3.7.** Edit `bin/story-server`: replace this text, which occurs exactly once:

```bash
        /usr/bin/tail -n "$LOG_TAIL_LINES" "$log" >&2
        kill_set "$SPAWN_PID $(port_pids) $(engine_pids)"
```

with:

```bash
        /usr/bin/tail -n "$LOG_TAIL_LINES" "$log" >&2
        kill_set "$SPAWN_PID $(port_pids) $(tree_pids "$SPAWN_PID $(port_pids)")"
```

**3.8.** Edit `bin/story-server`: replace this text, which occurs exactly once:

```bash
    local port_list serve_list eng_list pid cmd120 accepted

    port_list=$(port_pids)
    serve_list=$(serve_cmd_pids)
    eng_list=$(engine_pids)
```

with:

```bash
    local port_list serve_list pid cmd120 accepted

    port_list=$(port_pids)
    serve_list=$(serve_cmd_pids)
```

**3.9.** Edit `bin/story-server`: replace this text, which occurs exactly once:

```bash
    # Step 1: build the candidate set.
    CAND=""
    for pid in $port_list $serve_list $eng_list; do
        CAND=$(add_pid "$CAND" "$pid")
    done
    if is_server_pid "$PID_REC"; then
        CAND=$(add_pid "$CAND" "$PID_REC")
    fi
```

with:

```bash
    # Step 1: build the candidate set: the port owners, this port's serve argv matches, the
    # mode-file pid, and every descendant of those (VLM lifecycle spec VS6). An orphaned
    # VLLM::EngineCore outside that tree is reported (M31), never killed.
    CAND=""
    for pid in $port_list $serve_list; do CAND=$(add_pid "$CAND" "$pid"); done
    if is_server_pid "$PID_REC"; then CAND=$(add_pid "$CAND" "$PID_REC"); fi
    for pid in $(tree_pids "$CAND"); do CAND=$(add_pid "$CAND" "$pid"); done
    /bin/ps -A -o pid=,ppid=,command= 2>/dev/null \
      | /usr/bin/awk '$2 == 1 && $3 ~ /^VLLM::EngineCore/ { print $1 }' | while read -r p; do
        case " $CAND " in *" $p "*) continue ;; esac
        say "WARNING: VLLM::EngineCore pid $p has parent pid 1 and is not in port $PORT's process tree; left running (it may belong to another vLLM, such as the embed server on 8178)"   # M31
    done
```

**3.10.** Edit `tests/test_story_server.py` (in the same step as the script change, never before it): replace this text, which occurs exactly once:

```python
    env["STORY_SERVER_WARM_TIMEOUT"] = "10"
    # engine_pids() is host-global, not port-scoped (plan D9/R8). Without this the
    # kill set of every `stop`/timeout/trap path in this suite would include a REAL
    # `VLLM::EngineCore` if one is alive on this host, and the suite would SIGKILL a
    # production vLLM that it never started.
    env["STORY_SERVER_ENGINE_SCAN"] = "0"
```

with:

```python
    env["STORY_SERVER_WARM_TIMEOUT"] = "10"
```

- [ ] **Step 4: Run the tests and confirm they pass; check the shell syntax.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_story_server.py 2>&1 | tail -3
/bin/bash -n bin/story-server && bash -n bin/story-server && echo "syntax ok"
grep -c "ENGINE_SCAN\|engine_pids" bin/story-server
```

Expected: `35 passed` (about 75 seconds; `test_s14_source_guards` now passes), `syntax ok`, then `0`. The compile check with `FILES` = `tests/test_story_server.py`; expected `compiled 1` twice.

- [ ] **Step 5: Commit.**

```bash
git add bin/story-server tests/test_story_server.py
git diff --cached --name-only    # expected: qwen-agent-workspace/bin/story-server, qwen-agent-workspace/tests/test_story_server.py
git commit -m "feat(story-server): port-owner process tree instead of the host-wide EngineCore sweep; status prefers the loaded model (VLM lifecycle VS6, VS10; VLS8, VLS9, VLS11, VLS13; S14 realigned)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: bin/story-server-restore: lock-based detection, the double fork and the new `--wait`

Implements VRS1-VRS5. Tests VLR1-VLR9 and Review Focus 3; the 11.4 F-SS rewrite and CS6's pgid parse (CS4 keeps its assertions unchanged).

**Files:**
- Modify: `bin/story-server-restore` (docstring `:7-16`; imports and constants `:19-26`; `start_in_progress` `:39-52`; `main` `:62-79`)
- Modify: `tests/test_clean_stop.py` (imports; `_fake_story_server` `:68-77`; `test_cs6_restore_without_wait_returns_at_once` `:114`; append VLR tests)

**Interfaces:**
- Consumes: Task 1's `story-server lockinfo` line (`lock: held pid=<pid> cmd=<cmd> since=<ts> path=<p>` / `lock: free path=<p>`); Task 1's lock fast path (a second same-mode start exits 0 at once).
- Produces: `bin/story-server-restore [MODE] [--wait]`: exit 0 when MODE serves or a live MODE start holds the lock (no `--wait`); launches `story-server MODE` with launchd as its parent and returns after the start took the lock, exited, or 10 s; `--wait` returns 0 iff `story-server status` reports `SERVING MODE` once no MODE start is running, 1 on `STORY_SERVER_RESTORE_WAIT_S` timeout (stderr `story-server-restore: TIMEOUT: story-server <mode> did not finish within <n> s`). Functions `lock_holder() -> (pid, cmd) or None`, `alive(pid) -> bool`, `launch(mode) -> pid or None`, `wait_done(mode, pid) -> int`. Tasks 4, 7, 8, 9 and 12 run this tool. In `tests/test_clean_stop.py`: `_fake_story_server(tmp_path, state="STOPPED", sleep=0, lock_delay="0", serve=True) -> (script, calls)`, `_calls(calls) -> [dict]`, `_detached_sleeper(seconds) -> pid`, `_kill_fakes(calls)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_vlr1_double_fork`, `test_vlr2_wait_returns_on_serving`, `test_vlr3_a_start_in_progress_starts_nothing`, `test_vlr4_a_stop_holder_does_not_block_a_launch`, `test_vlr5_wait_times_out`, `test_vlr6_no_ps_scan`, `test_vlr7_already_serving`, `test_vlr8_two_concurrent_restores_start_one_server`, `test_vlr9_launch_waits_for_the_lock`, `test_review_focus_3_restore_with_a_story_server_without_lockinfo`.

**1.1.** Edit `tests/test_clean_stop.py`: replace this text, which occurs exactly once:

```python
import importlib.machinery
import os
import signal
import subprocess
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
```

with:

```python
import importlib.machinery
import os
import signal
import socket
import subprocess
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(WS, "tests"))

import test_story_server as tss  # noqa: E402  (VLR8 uses its _base_env stubs)
```

**1.2.** Edit `tests/test_clean_stop.py`: replace this text, which occurs exactly once:

```python
def _fake_story_server(tmp_path, state="STOPPED", sleep=0):
    calls = tmp_path / "calls.txt"
    script = tmp_path / "story-server"
    script.write_text(
        "#!/bin/bash\n"
        "if [ \"$1\" = status ]; then echo '  state:          %s'; exit 0; fi\n"
        "echo \"$1 sid=$(ps -o sess= -p $$) pgid=$(ps -o pgid= -p $$)\" >> %s\n"
        "sleep %s\n" % (state, calls, sleep))
    script.chmod(0o755)
    return str(script), calls
```

with:

```python
def _fake_story_server(tmp_path, state="STOPPED", sleep=0, lock_delay="0", serve=True):
    """F-SS (VLM lifecycle spec 11.2): `status` prints SERVING mlx-vision once <tmp>/started
    exists, else `state`; `lockinfo` prints <tmp>/lockinfo, else a free lock; any other argument
    appends "<arg> sid=<sid> pgid=<pgid> ppid=<ppid> pid=<pid>" to calls.txt, then (unless
    lock_delay is "never") sleeps lock_delay and writes a held lockinfo line naming itself,
    sleeps `sleep`, touches <tmp>/started (when serve) and writes a free lockinfo line."""
    calls = tmp_path / "calls.txt"
    script = tmp_path / "story-server"
    script.write_text(
        "#!/bin/bash\n"
        "T='%s'\n"
        "if [ \"$1\" = status ]; then\n"
        "    if [ -e \"$T/started\" ]; then echo '  state:          SERVING mlx-vision'\n"
        "    else echo '  state:          %s'; fi\n"
        "    exit 0\n"
        "fi\n"
        "if [ \"$1\" = lockinfo ]; then\n"
        "    if [ -e \"$T/lockinfo\" ]; then cat \"$T/lockinfo\"; else echo 'lock: free path=x'; fi\n"
        "    exit 0\n"
        "fi\n"
        "echo \"$1 sid=$(/usr/bin/python3 -c 'import os; print(os.getsid(0))')"
        " pgid=$(ps -o pgid= -p $$ | tr -d ' ') ppid=$(ps -o ppid= -p $$ | tr -d ' ') pid=$$\""
        " >> \"$T/calls.txt\"\n"
        "if [ '%s' != never ]; then\n"
        "    sleep %s\n"
        "    echo \"lock: held pid=$$ cmd=$1 since=x path=x\" > \"$T/lockinfo\"\n"
        "fi\n"
        "sleep %s\n"
        "if [ '%s' = 1 ]; then touch \"$T/started\"; fi\n"
        "echo 'lock: free path=x' > \"$T/lockinfo\"\n"
        % (tmp_path, state, lock_delay, lock_delay, sleep, "1" if serve else "0"))
    script.chmod(0o755)
    return str(script), calls


def _calls(calls):
    """calls.txt as [{"arg", "sid", "pgid", "ppid", "pid"}] (ints for the numbers)."""
    out = []
    for line in calls.read_text().splitlines():
        words = line.split()
        row = {"arg": words[0]}
        row.update((k, int(v)) for k, v in (w.split("=", 1) for w in words[1:]))
        out.append(row)
    return out


def _detached_sleeper(seconds):
    """The pid of a `sleep` whose parent is launchd, so its exit is reaped at once (an unreaped
    child of this test would look alive to kill -0)."""
    out = subprocess.run(["/bin/sh", "-c", "/bin/sleep %s >/dev/null 2>&1 & echo $!" % seconds],
                         capture_output=True, text=True, timeout=10).stdout
    return int(out)


def _kill_fakes(calls):
    """Teardown: SIGKILL the process group of every fake start recorded in calls.txt."""
    if not calls.exists():
        return
    for row in _calls(calls):
        try:
            os.killpg(row["pgid"], signal.SIGKILL)
        except OSError:
            pass
```

**1.3.** Edit `tests/test_clean_stop.py`: replace this text, which occurs exactly once:

```python
    os.killpg(int(calls.read_text().split("pgid=")[1]), signal.SIGTERM)
```

with:

```python
    os.killpg(int(calls.read_text().split("pgid=")[1].split()[0]), signal.SIGTERM)
```

**1.4.** Append to `tests/test_clean_stop.py`:

```python
# ---------------------------------------------------------------------------
# VLR1-VLR9, Review Focus 3: the lock-aware, double-forking restore (VLM lifecycle spec VRS1-VRS5)
# ---------------------------------------------------------------------------

def _wait_for(predicate, timeout):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met within %.1f s" % timeout)
        time.sleep(0.05)


def _ppid(pid):
    return subprocess.run(["/bin/ps", "-o", "ppid=", "-p", str(pid)], capture_output=True,
                          text=True).stdout.strip()


def test_vlr1_double_fork(tmp_path):
    script, calls = _fake_story_server(tmp_path, sleep=5)
    try:
        result = _run_restore(tmp_path, script)
        assert result.returncode == 0, result.stderr
        row = _calls(calls)[0]
        assert row["arg"] == "mlx-vision"
        # The launcher has exited by the time the restore returns (launch() waits for it), so
        # the start's parent is launchd; the fake's own early ppid snapshot can race that exit.
        assert _ppid(row["pid"]) == "1"
        assert row["sid"] != os.getsid(0) and row["pgid"] != os.getpgid(0)
        assert row["sid"] == row["pid"] == row["pgid"]
    finally:
        _kill_fakes(calls)


def test_vlr2_wait_returns_on_serving(tmp_path):
    script, calls = _fake_story_server(tmp_path, sleep=1)
    result = _run_restore(tmp_path, script, "--wait")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "started").exists()
    never = tmp_path / "never"
    never.mkdir()
    script, calls = _fake_story_server(never, sleep=1, serve=False)
    result = _run_restore(never, script, "--wait")
    assert result.returncode == 1
    assert _calls(calls)[0]["arg"] == "mlx-vision"


def test_vlr3_a_start_in_progress_starts_nothing(tmp_path):
    script, calls = _fake_story_server(tmp_path)
    sleeper = _detached_sleeper(3)
    (tmp_path / "lockinfo").write_text("lock: held pid=%d cmd=mlx-vision since=x path=x\n" % sleeper)
    result = _run_restore(tmp_path, script)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ("story-server-restore: a story-server mlx-vision start is already in "
                             "progress (pid %d)\n" % sleeper)
    assert not calls.exists()
    (tmp_path / "started").touch()
    started = time.monotonic()
    result = _run_restore(tmp_path, script, "--wait")
    assert result.returncode == 0, result.stderr
    assert time.monotonic() - started >= 1.0
    assert not tss._pid_alive(sleeper)
    assert not calls.exists()


def test_vlr4_a_stop_holder_does_not_block_a_launch(tmp_path):
    script, calls = _fake_story_server(tmp_path, sleep=1)
    (tmp_path / "lockinfo").write_text("lock: held pid=%d cmd=stop since=x path=x\n" % os.getpid())
    result = _run_restore(tmp_path, script)
    try:
        assert result.returncode == 0, result.stderr
        assert "starting story-server mlx-vision" in result.stdout
        _wait_for(calls.exists, 5)
        assert _calls(calls)[0]["arg"] == "mlx-vision"
    finally:
        _kill_fakes(calls)


def test_vlr5_wait_times_out(tmp_path):
    script, calls = _fake_story_server(tmp_path)
    sleeper = _detached_sleeper(30)
    (tmp_path / "lockinfo").write_text("lock: held pid=%d cmd=mlx-vision since=x path=x\n" % sleeper)
    env = dict(os.environ, STORY_SERVER_RESTORE_BIN=script, HOME=str(tmp_path),
               STORY_SERVER_RESTORE_WAIT_S="2")
    try:
        result = subprocess.run([sys.executable, RESTORE, "--wait"], env=env, capture_output=True,
                                text=True, timeout=30)
        assert result.returncode == 1
        assert result.stderr == ("story-server-restore: TIMEOUT: story-server mlx-vision did not "
                                 "finish within 2 s\n")
        assert not calls.exists()
    finally:
        os.kill(sleeper, signal.SIGKILL)


def test_vlr6_no_ps_scan():
    with open(RESTORE, encoding="utf-8") as f:
        source = f.read()
    assert '"ps"' not in source and "-axo" not in source and "start_in_progress" not in source


def test_vlr7_already_serving(tmp_path):
    script, calls = _fake_story_server(tmp_path, state="SERVING mlx-vision")
    result = _run_restore(tmp_path, script, "--wait")
    assert result.returncode == 0
    assert result.stdout == "story-server-restore: already serving mlx-vision\n"
    assert not calls.exists()


def test_vlr8_two_concurrent_restores_start_one_server(tmp_path):
    port = tss._free_port()
    env = tss._base_env(tmp_path, port)
    env["STUB_LOAD_DELAY"] = "3"
    env["STORY_SERVER_MLX_VISION_MODEL_ID"] = "test-mlx-vlm-model"
    env["STUB_MODEL_ID"] = "test-mlx-vlm-model"
    env["STORY_SERVER_RESTORE_BIN"] = tss.STORY_SERVER
    env["HOME"] = str(tmp_path)
    stub = env["STORY_SERVER_MLX_VLM_PYTHON"]
    try:
        procs = [subprocess.Popen([sys.executable, RESTORE], env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) for _ in range(2)]
        for p in procs:
            p.communicate(timeout=60)
            assert p.returncode == 0
        log = os.path.join(str(tmp_path), ".local", "share", "qwen-agent", "story-server-restore.log")
        _wait_for(lambda: "warm-up OK" in open(log).read(), 60)
        assert len(tss._pgrep(stub + " -m mlx_vlm.server")) == 1
        with open(log) as f:
            text = f.read()
        assert text.count("launched mlx-vision server, pid") == 1
        assert text.count("start (story-server pid") + text.count("already serving") <= 1
    finally:
        subprocess.run([tss.STORY_SERVER, "stop"], env=env, capture_output=True, timeout=90)


def test_vlr9_launch_waits_for_the_lock(tmp_path):
    cases = (("1", 30, 1.0, 5.0, "held"), ("never", 3, 3.0, 6.0, "free"),
             ("never", 30, 10.0, 13.0, None))
    for i, (lock_delay, sleep, low, high, lockinfo) in enumerate(cases):
        root = tmp_path / ("case%d" % i)
        root.mkdir()
        script, calls = _fake_story_server(root, sleep=sleep, lock_delay=lock_delay)
        try:
            started = time.monotonic()
            result = _run_restore(root, script)
            took = time.monotonic() - started
            assert result.returncode == 0, result.stderr
            assert low <= took < high, (lock_delay, sleep, took)
            if lockinfo == "held":
                assert (root / "lockinfo").read_text().startswith("lock: held pid=%d cmd=mlx-vision"
                                                                  % _calls(calls)[0]["pid"])
            elif lockinfo == "free":
                assert (root / "lockinfo").read_text() == "lock: free path=x\n"
            else:
                assert not (root / "lockinfo").exists()
        finally:
            _kill_fakes(calls)


def test_review_focus_3_restore_with_a_story_server_without_lockinfo(tmp_path):
    """A story-server from an older release prints its usage and exits 2 for `lockinfo`; the
    restore must read that as a free lock and still launch (spec VRS2)."""
    calls = tmp_path / "calls.txt"
    script = tmp_path / "story-server"
    script.write_text(
        "#!/bin/bash\n"
        "case \"$1\" in\n"
        "    status) echo '  state:          STOPPED'; exit 0 ;;\n"
        "    vision|text|mlx-vision|stop) echo \"$1 pid=$$\" >> '%s'; sleep 1; exit 0 ;;\n"
        "esac\n"
        "echo 'usage: story-server [vision|text|mlx-vision|status|stop]' >&2\n"
        "exit 2\n" % calls)
    script.chmod(0o755)
    result = _run_restore(tmp_path, str(script))
    assert result.returncode == 0, result.stderr
    assert "starting story-server mlx-vision" in result.stdout
    _wait_for(calls.exists, 5)
    assert calls.read_text().split()[0] == "mlx-vision"
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_clean_stop.py 2>&1 | tail -3
```

Expected: 6 or 7 failed, the rest passed. These six must fail: `test_vlr1_double_fork` (HEAD returns before the fake has even recorded its call), `test_vlr2_wait_returns_on_serving`, `test_vlr3_a_start_in_progress_starts_nothing`, `test_vlr5_wait_times_out` (HEAD never reads `lockinfo`), `test_vlr6_no_ps_scan` and `test_vlr9_launch_waits_for_the_lock`. `test_review_focus_3_restore_with_a_story_server_without_lockinfo` fails only when HEAD's host-wide `ps` scan sees a fake left running by an earlier test (failure mode F4), else it passes. `test_vlr4`, `test_vlr7` and `test_vlr8` pass at HEAD (HEAD launches past a stop holder; VLR7 is CS5; Task 1's lock already keeps two concurrent restores to one server). CS1-CS7 pass with the new F-SS.

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/story-server-restore`: replace this text, which occurs exactly once:

```python
Runs `bin/story-server MODE` (default mlx-vision) in a NEW SESSION, so a cancel or kill sweep of
the job that asked for it (movie-ui Cancel signals every process group of the job, then SIGKILLs
them) cannot take the restarted server down with the job. Without --wait it returns at once and
the start continues in the background, logging to
~/.local/share/qwen-agent/story-server-restore.log; with --wait it waits for the start to finish
and returns its exit code.

Does nothing (exit 0) when the server already serves MODE; when another `story-server MODE`
start is in progress it starts nothing, and with --wait waits for that start to finish. Stdlib
only. Spec: docs/superpowers/specs/2026-10-21-clean-stop-design.md.
"""

import os
import subprocess
import sys
import time

BIN = os.path.dirname(os.path.realpath(__file__))
STORY_SERVER = os.environ.get("STORY_SERVER_RESTORE_BIN", os.path.join(BIN, "story-server"))
LOG = os.path.expanduser("~/.local/share/qwen-agent/story-server-restore.log")
```

with:

```python
Runs `bin/story-server MODE` (default mlx-vision) in a NEW SESSION, so a cancel or kill sweep of
the job that asked for it (movie-ui Cancel signals every process group of the job, then SIGKILLs
them) cannot take the restarted server down with the job. Without --wait it returns soon and
the start continues in the background, logging to
~/.local/share/qwen-agent/story-server-restore.log; with --wait it waits as described below.

Does nothing (exit 0) when MODE is already serving. When `story-server lockinfo` shows a live MODE
start holding the lock it starts nothing, and with --wait it waits for that start. Otherwise it
launches `story-server MODE` through a launcher that exits at once, waits up to 10 s for that
start to take the lock, so the server's parent is launchd and no job's cancel or orphan kill can
reach it (VLM lifecycle spec VRS3). --wait blocks, polling only the lock and the started pid,
until no MODE start is running (at most STORY_SERVER_RESTORE_WAIT_S, default 2520 s), then exits
0 iff `story-server status` reports SERVING MODE. Stdlib only. Specs:
docs/superpowers/specs/2026-10-21-clean-stop-design.md,
docs/superpowers/specs/2026-10-25-vlm-lifecycle-design.md.
"""

import os
import re
import subprocess
import sys
import time

BIN = os.path.dirname(os.path.realpath(__file__))
STORY_SERVER = os.environ.get("STORY_SERVER_RESTORE_BIN", os.path.join(BIN, "story-server"))
LOG = os.path.expanduser("~/.local/share/qwen-agent/story-server-restore.log")
WAIT_S = int(os.environ.get("STORY_SERVER_RESTORE_WAIT_S", "2520"))
POLL_S = 2
LOCK_WAIT_S = 10      # how long a launch waits for the detached start to take the lock (VRS2 step 4)
LOCK_POLL_S = 0.2
LAUNCH = ("import subprocess, sys\n"
          "log = open(sys.argv[1], 'ab')\n"
          "p = subprocess.Popen(sys.argv[2:], stdin=subprocess.DEVNULL, stdout=log, "
          "stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)\n"
          "sys.stdout.write('%d\\n' % p.pid)\n")
```

**3.2.** Edit `bin/story-server-restore`: replace this text, which occurs exactly once:

```python
def start_in_progress(mode):
    """True when another `story-server <mode>` start is running."""
    try:
        out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True,
                             text=True).stdout
    except OSError:
        return False
    for line in out.splitlines():
        pid, _, command = line.strip().partition(" ")
        words = command.split()
        if (int(pid) != os.getpid() and len(words) >= 2 and words[-1] == mode
                and os.path.basename(words[-2]) == "story-server"):
            return True
    return False
```

with:

```python
def alive(pid):
    """kill -0: True while pid exists (also when it belongs to another user)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_holder():
    """(pid, cmd) of the live process `story-server lockinfo` names as the lock holder, else None
    (also when lockinfo fails or is unknown, as in a story-server older than the lock)."""
    try:
        out = subprocess.run([STORY_SERVER, "lockinfo"], capture_output=True, text=True,
                             timeout=30).stdout
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        words = line.split()
        if (len(words) >= 4 and words[0] == "lock:" and words[1] == "held"
                and re.fullmatch(r"pid=[0-9]+", words[2]) and words[3].startswith("cmd=")):
            pid = int(words[2][4:])
            if alive(pid):
                return pid, words[3][4:]
    return None


def launch(mode):
    """Start `story-server MODE` through a launcher that exits at once (a double fork: the
    start's parent is launchd, VRS3); its pid, or None after printing why it could not start."""
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        proc = subprocess.run([sys.executable, "-c", LAUNCH, LOG, STORY_SERVER, mode],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        problem = str(e)
    else:
        out = proc.stdout.strip()
        if proc.returncode == 0 and out.isdigit():
            return int(out)
        lines = [line for line in proc.stderr.splitlines() if line.strip()]
        problem = lines[-1].strip() if lines else "launcher exited %d" % proc.returncode
    print("story-server-restore: cannot start story-server %s: %s" % (mode, problem),
          file=sys.stderr)
    return None


def wait_done(mode, pid):
    """--wait (VRS4): poll the started pid and the lock until no MODE start runs; then 0 iff
    MODE is serving. Sends no HTTP request while it waits."""
    deadline = time.monotonic() + WAIT_S
    while (pid is not None and alive(pid)) or (lock_holder() or (None, None))[1] == mode:
        if time.monotonic() >= deadline:
            print("story-server-restore: TIMEOUT: story-server %s did not finish within %d s"
                  % (mode, WAIT_S), file=sys.stderr)
            return 1
        time.sleep(POLL_S)
    return 0 if serving(mode) else 1
```

**3.3.** Edit `bin/story-server-restore`: replace this text, which occurs exactly once:

```python
    mode = args[0] if args else "mlx-vision"
    if serving(mode):
        print("story-server-restore: already serving %s" % mode)
        return 0
    if start_in_progress(mode):
        print("story-server-restore: a story-server %s start is already in progress" % mode,
              flush=True)
        if not wait:
            return 0
        while start_in_progress(mode):
            time.sleep(2)
        return 0 if serving(mode) else 1
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "ab") as log:
        proc = subprocess.Popen([STORY_SERVER, mode], stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
    print("story-server-restore: starting story-server %s (pid %d, own session); log: %s"
          % (mode, proc.pid, LOG), flush=True)
    return proc.wait() if wait else 0
```

with:

```python
    mode = args[0] if args else "mlx-vision"
    holder = lock_holder()
    if holder is not None and holder[1] == mode:
        print("story-server-restore: a story-server %s start is already in progress (pid %d)"
              % (mode, holder[0]), flush=True)
        return wait_done(mode, None) if wait else 0
    if serving(mode):
        print("story-server-restore: already serving %s" % mode)
        return 0
    pid = launch(mode)
    if pid is None:
        return 1
    print("story-server-restore: starting story-server %s (pid %d, own session); log: %s"
          % (mode, pid, LOG), flush=True)
    deadline = time.monotonic() + LOCK_WAIT_S
    while time.monotonic() < deadline and alive(pid):
        holder = lock_holder()
        if holder is not None and holder[1] == mode:
            break
        time.sleep(LOCK_POLL_S)
    return wait_done(mode, pid) if wait else 0
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_clean_stop.py 2>&1 | tail -1
```

Expected: `17 passed, 1 warning` (about 40 seconds; the warning is `load_module`'s deprecation, as at HEAD). Then the compile check with `FILES` = `bin/story-server-restore tests/test_clean_stop.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add bin/story-server-restore tests/test_clean_stop.py
git diff --cached --name-only    # expected: qwen-agent-workspace/bin/story-server-restore, qwen-agent-workspace/tests/test_clean_stop.py
git commit -m "feat(story-server-restore): lock-based in-progress detection, double-fork detach, new --wait (VLM lifecycle VRS1-VRS5; VLR1-VLR9)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: character_dataset.py restores through `story-server-restore --wait`

Implements VC1 (D6). Tests VLC1; the 11.4 edits of `_Fakes`, `test_k9`, `test_k13`, `test_k20` (`test_k21` is unchanged). From this commit on, `test_mut26` fails until Task 13 (Global Constraints).

**Files:**
- Modify: `character_dataset.py` (`restore_story_server` `:485-493`; `_build_dataset`'s `finally` `:1000-1004`)
- Modify: `tests/test_character_tool.py` (`_Fakes` `:131-132`; `test_k9` `:367`; `test_k13` `:451`; `test_k20` `:552`; append VLC1)

**Interfaces:**
- Consumes: Task 3's `bin/story-server-restore MODE [--wait]`.
- Produces: `character_dataset.restore_story_server(wait=False) -> int` (the restore's exit code; 1 after printing `warning: story-server-restore failed: <e>; run bin/story-server mlx-vision` when it cannot run). `_build_dataset` calls `restore_story_server(wait=True)` after a non-interrupted generate and prints `warning: story-server-restore mlx-vision --wait returned <rc>` on a non-zero code.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_vlc1_create_restores_with_wait`, `test_vlc1_a_failed_restore_warns`, `test_vlc1_restore_story_server_argv`.

**1.1.** Edit `tests/test_character_tool.py`: replace this text, which occurs exactly once:

```python
        monkeypatch.setattr(character_dataset, "restore_story_server",
                            lambda: fakes.server_calls.append("restore"))
```

with:

```python
        monkeypatch.setattr(character_dataset, "restore_story_server",
                            lambda wait=False: fakes.server_calls.append(
                                "restore-wait" if wait else "restore") or 0)
```

**1.2.** Edit `tests/test_character_tool.py`: replace this text, which occurs exactly once:

```python
    with open(os.path.join(lib_dir, ".triggers")) as f:
        assert f.read() == "kyrawmn kyra\n"
    assert fakes.server_calls == ["stop", "mlx-vision"]
```

with:

```python
    with open(os.path.join(lib_dir, ".triggers")) as f:
        assert f.read() == "kyrawmn kyra\n"
    assert fakes.server_calls == ["stop", "restore-wait"]
```

**1.3.** Edit `tests/test_character_tool.py`: replace this text, which occurs exactly once:

```python
    assert capsys.readouterr().err == "Error: Z-Image child process exited 1; log: /x.log\n"
    assert fakes.server_calls == ["stop", "mlx-vision"]
```

with:

```python
    assert capsys.readouterr().err == "Error: Z-Image child process exited 1; log: /x.log\n"
    assert fakes.server_calls == ["stop", "restore-wait"]
```

**1.4.** Edit `tests/test_character_tool.py`: replace this text, which occurs exactly once:

```python
                       "to abort: " % sheet]
    assert fakes.server_calls == ["stop", "mlx-vision"]
```

with:

```python
                       "to abort: " % sheet]
    assert fakes.server_calls == ["stop", "restore-wait"]
```

**1.5.** Append to `tests/test_character_tool.py`:

```python
# --- VLC1: the generate phase restores through story-server-restore --wait (VLM lifecycle VC1) --
def test_vlc1_create_restores_with_wait(lib_dir, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, scores=[9] * 24)
    assert tool.main(_ronin_create()) == 0
    assert fakes.server_calls == ["stop", "restore-wait"]
    with open(character_dataset.__file__, encoding="utf-8") as f:
        assert "story_server(VLM_SERVE_MODE)" not in f.read()
    assert "warning: story-server-restore" not in capsys.readouterr().err


def test_vlc1_a_failed_restore_warns(lib_dir, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, scores=[9] * 24)
    monkeypatch.setattr(character_dataset, "restore_story_server",
                        lambda wait=False: fakes.server_calls.append(
                            "restore-wait" if wait else "restore") or 1)
    assert tool.main(_ronin_create()) == 0
    assert fakes.server_calls == ["stop", "restore-wait"]
    assert ("warning: story-server-restore mlx-vision --wait returned 1\n"
            in capsys.readouterr().err)


def test_vlc1_restore_story_server_argv(monkeypatch, capsys):
    seen = []

    class _Done(object):
        returncode = 3

    def _run(argv, timeout=None):
        seen.append((argv, timeout))
        return _Done()

    monkeypatch.setattr(character_dataset.subprocess, "run", _run)
    restore = os.path.join(WS, "bin", "story-server-restore")
    assert character_dataset.restore_story_server(wait=True) == 3
    assert character_dataset.restore_story_server() == 3
    assert seen == [([restore, "mlx-vision", "--wait"], None), ([restore, "mlx-vision"], 60)]

    def _fail(argv, timeout=None):
        raise OSError("no such file")

    monkeypatch.setattr(character_dataset.subprocess, "run", _fail)
    assert character_dataset.restore_story_server(wait=True) == 1
    assert capsys.readouterr().err == ("warning: story-server-restore failed: no such file; run "
                                       "bin/story-server mlx-vision\n")
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_character_tool.py 2>&1 | tail -8
```

Expected: `6 failed, 21 passed, 1 warning`: `test_k9_seed_mode_happy_path`, `test_k13_generation_failure_restarts_the_vision_server` and `test_k20_preview_stop` (HEAD still calls `story_server("mlx-vision")`, so the calls are `["stop", "mlx-vision"]`), the two VLC1 create tests (the same calls), and `test_vlc1_restore_story_server_argv` (`TypeError`: HEAD's `restore_story_server` takes no `wait`). `test_k21_ctrl_c_at_the_preview_stop` passes (its interrupt path calls `restore_story_server()` without `wait`).

- [ ] **Step 3: Implement.**

**3.1.** Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
def restore_story_server():
    """Start the vision server through bin/story-server-restore: in its own session, without
    waiting (clean-stop spec S1, S3)."""
    try:
        subprocess.run([os.path.join(WS, "bin", "story-server-restore"), VLM_SERVE_MODE],
                       timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        print("warning: story-server-restore failed: %s; run bin/story-server %s"
              % (e, VLM_SERVE_MODE), file=sys.stderr)
```

with:

```python
def restore_story_server(wait=False):
    """Start the vision server through bin/story-server-restore (clean-stop spec S1; VLM lifecycle
    spec VRS3: the server's parent is launchd, so no kill sweep reaches it). Without wait it returns
    at once; with wait it waits for the start. Returns the restore's exit code (1 on an error)."""
    argv = [os.path.join(WS, "bin", "story-server-restore"), VLM_SERVE_MODE] + (["--wait"] if wait else [])
    try:
        return subprocess.run(argv, timeout=None if wait else 60).returncode
    except (OSError, subprocess.SubprocessError) as e:
        print("warning: story-server-restore failed: %s; run bin/story-server %s"
              % (e, VLM_SERVE_MODE), file=sys.stderr)
        return 1
```

**3.2.** Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
            rc = story_server(VLM_SERVE_MODE)
            if rc != 0:
                print("warning: story-server %s returned %d" % (VLM_SERVE_MODE, rc),
                      file=sys.stderr)
```

with:

```python
            rc = restore_story_server(wait=True)
            if rc != 0:
                print("warning: story-server-restore %s --wait returned %d" % (VLM_SERVE_MODE, rc),
                      file=sys.stderr)
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_character_tool.py tests/test_character_dataset.py 2>&1 | tail -3
```

Expected: `1 failed, 78 passed, 1 warning`; the one failure is the pre-existing `test_character_dataset.py::test_d2_copied_literals_match_the_spike`. Then the compile check with `FILES` = `character_dataset.py tests/test_character_tool.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add character_dataset.py tests/test_character_tool.py
git diff --cached --name-only    # expected: qwen-agent-workspace/character_dataset.py, qwen-agent-workspace/tests/test_character_tool.py
git commit -m "feat(character): restore the vision server through story-server-restore --wait (VLM lifecycle VC1; VLC1)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: movie_ui_lib: the per-job `vlm` policy, the lifecycle switches and the test isolation

Implements 2.1 (the `vlm` key), 2.5 (the `movie_ui_lib` constants and the three environment helpers of VR1), VP1, VP2, VP3, VP4, 11.1 (the conftest fixture). Tests VL1, VL2, VL3 (the `effective_vlm` half; Task 7 owns the preflight line), VL4, VL5, plus `test_vlm_constants_and_isolation` and `test_vlm_environment_helpers`; the 11.4 edit of `test_store_writes_atomically_with_private_modes`.

**Files:**
- Modify: `movie_ui_lib.py` (`create_job` `:179-181`; a new section before the "Liveness, the dispatcher" header `:357`)
- Modify: `tests/conftest.py` (append the fixture)
- Modify: `tests/test_movie_ui_jobs.py` (`:65`)
- Create: `tests/test_vlm_lifecycle.py`

**Interfaces:**
- Consumes: `movie_ui_lib.story_dir`, `read_queue`, `read_job`, `job_dir` (existing).
- Produces (in `movie_ui_lib`): the constants `VLM_MODE`, `VLM_POLICIES`, `VLM_STATUS_TIMEOUT_S`, `VLM_HTTP_TIMEOUT_S`, `VLM_COMPLETION_TIMEOUT_S`, `VLM_PREFLIGHT_TIMEOUT_S`, `VLM_POSTFLIGHT_TIMEOUT_S`, `VLM_TOOL_KILL_WAIT_S`, `VLM_MAX_BODY`, `VLM_RESTORE_LOG_TEXT`, `HEALTH_LINE_RE`, `VLM_RECOVERY` (list), `RESTORERS` (list) with the spec 2.5 values; `vlm_lifecycle_enabled() -> bool`; `vlm_tools_dir(ui_ws=None) -> str`; `vlm_port() -> int`; `job_vlm(kind, fields, workspace, story_id) -> "required" | "forbidden" | "any"`; `effective_vlm(job) -> str`; `next_queued_job(state) -> (job_id, job) or (None, None)`; `vlm_restore_wanted(state) -> (bool, reason)`; `create_job` writes `"vlm"` between `"fields"` and `"created"`. In `tests/test_vlm_lifecycle.py`: the module header (imports, `state` and `http_env` fixtures) that Tasks 6-12 append to.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_vlm_constants_and_isolation`, `test_vlm_environment_helpers`, `test_vl1_job_vlm`, `test_vl2_jobs_carry_their_vlm_policy`, `test_vl3_effective_vlm`, `test_vl4_next_queued_job`, `test_vl5_vlm_restore_wanted`.

**1.1.** Append to `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def vlm_lifecycle_isolation(monkeypatch, tmp_path):
    """VLM lifecycle spec 11.1: the movie-ui runner's preflight and postflight, V2's warn and the
    startup restore are off in every test unless the test turns them on itself, and nothing can
    reach the real bin/story-server through them (the tools directory does not exist, port 9 is
    unreachable). Runner subprocesses inherit these variables."""
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "0")
    monkeypatch.setenv("MOVIE_UI_VLM_TOOLS", str(tmp_path / "no-vlm-tools"))
    monkeypatch.setenv("MOVIE_UI_VLM_PORT", "9")
```

**1.2.** Edit `tests/test_movie_ui_jobs.py`: replace this text, which occurs exactly once:

```python
    assert set(job) == {"schema", "id", "kind", "workspace", "story_id", "character", "argv", "fields", "created"}
```

with:

```python
    assert set(job) == {"schema", "id", "kind", "workspace", "story_id", "character", "argv", "fields", "vlm",
                        "created"}
    assert job["vlm"] == "required"
```

**1.3.** Create `tests/test_vlm_lifecycle.py`:

```python
"""Tests for the VLM lifecycle at job boundaries (docs/superpowers/specs/2026-10-25-vlm-lifecycle-
design.md, Section 11: VL1-VL28 and Review Focus 1, 2, 4, 5): the per-job vlm policy, the
port-scoped health check, the runner's preflight and postflight, the startup restore, V2's warn
and the page gate.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_vlm_lifecycle.py
Stdlib plus pytest. Every story-server and story-server-restore here is F-TOOLS (make_fake_tools),
every VLM is F-HTTP (FakeVLM) on an ephemeral 127.0.0.1 port, every HOME is temporary, and the
conftest's vlm_lifecycle_isolation keeps the lifecycle off unless a test turns it on with
lifecycle_on(); VL22 alone runs the real bin/story-server-restore, against a fake story-server.
"""

import fcntl
import http.server
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time

import pytest

import movie_ui_testutil as mt
import movie_ui_lib as lib


@pytest.fixture
def state(monkeypatch, tmp_path):
    path = mt.set_home(monkeypatch, tmp_path)
    monkeypatch.setattr(lib, "VLM_RECOVERY", [])
    monkeypatch.setattr(lib, "RESTORERS", [])
    yield path
    mt.kill_everything(path)


@pytest.fixture
def http_env(monkeypatch, tmp_path):
    state = mt.set_home(monkeypatch, tmp_path)
    monkeypatch.setattr(lib, "VLM_RECOVERY", [])
    ws = mt.make_stub_workspace(tmp_path)
    running = mt.Running(state)
    yield {"state": state, "ws": ws, "srv": running, "tmp": str(tmp_path)}
    running.close()
    mt.kill_everything(state)


def _write_story(ws, story_id):
    sdir = lib.story_dir(ws, story_id)
    os.makedirs(sdir, exist_ok=True)
    with open(os.path.join(sdir, "story.md"), "w", encoding="utf-8") as f:
        f.write("## Panel 1 -- Shot 1\nImage: a quiet road.\nMotion: the camera drifts.\n")


# --- the constants, the switches and the isolation (spec 2.5, VR1, 11.1) ---------------------

def test_vlm_constants_and_isolation(tmp_path):
    assert (lib.VLM_MODE, lib.VLM_POLICIES) == ("mlx-vision", ("required", "forbidden", "any"))
    assert (lib.VLM_STATUS_TIMEOUT_S, lib.VLM_HTTP_TIMEOUT_S, lib.VLM_COMPLETION_TIMEOUT_S,
            lib.VLM_PREFLIGHT_TIMEOUT_S, lib.VLM_POSTFLIGHT_TIMEOUT_S, lib.VLM_TOOL_KILL_WAIT_S,
            lib.VLM_MAX_BODY) == (60, 10, 120, 6900, 90, 5, 1048576)
    assert lib.VLM_RESTORE_LOG_TEXT == "~/.local/share/qwen-agent/story-server-restore.log"
    assert isinstance(lib.VLM_RECOVERY, list) and isinstance(lib.RESTORERS, list)
    assert os.environ["MOVIE_UI_VLM_LIFECYCLE"] == "0"
    assert os.environ["MOVIE_UI_VLM_TOOLS"] == str(tmp_path / "no-vlm-tools")
    assert not os.path.exists(os.environ["MOVIE_UI_VLM_TOOLS"])
    assert os.environ["MOVIE_UI_VLM_PORT"] == "9"
    assert lib.vlm_lifecycle_enabled() is False


def test_vlm_environment_helpers(monkeypatch):
    for name in ("MOVIE_UI_VLM_LIFECYCLE", "MOVIE_UI_VLM_TOOLS", "MOVIE_UI_VLM_PORT"):
        monkeypatch.delenv(name)
    assert lib.vlm_lifecycle_enabled() is True
    assert lib.vlm_tools_dir() == os.path.join(mt.WS, "bin")
    assert lib.vlm_tools_dir("/ui") == "/ui/bin"
    assert lib.vlm_port() == 8177
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "yes")
    assert lib.vlm_lifecycle_enabled() is True
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "0")
    assert lib.vlm_lifecycle_enabled() is False
    monkeypatch.setenv("MOVIE_UI_VLM_TOOLS", "")
    assert lib.vlm_tools_dir("/ui") == "/ui/bin"
    monkeypatch.setenv("MOVIE_UI_VLM_TOOLS", "/t")
    assert lib.vlm_tools_dir("/ui") == "/t" and lib.vlm_tools_dir() == "/t"
    monkeypatch.setenv("MOVIE_UI_VLM_PORT", "1234")
    assert lib.vlm_port() == 1234


# --- VL1-VL5: the policy (VP1-VP4) -------------------------------------------------------------

def test_vl1_job_vlm(tmp_path):
    ws = str(tmp_path)
    for kind in ("story", "character-create", "character-regenerate"):
        assert lib.job_vlm(kind, {}, ws, None) == "required", kind
    for kind in ("smoke", "character-train", "action-train"):
        assert lib.job_vlm(kind, {}, ws, None) == "forbidden", kind
    for kind in ("action-create", "download", "something-new"):
        assert lib.job_vlm(kind, {}, ws, None) == "any", kind
    assert lib.job_vlm("movie", {"action": "movie"}, ws, "s1") == "required"
    assert lib.job_vlm("movie", {"action": "movie"}, ws, None) == "required"
    assert lib.job_vlm("movie", None, ws, "") == "required"
    assert lib.job_vlm("movie", {"action": "redo"}, ws, "s1") == "forbidden"
    _write_story(ws, "s1")
    assert lib.job_vlm("movie", {"action": "movie"}, ws, "s1") == "forbidden"
    assert lib.job_vlm("movie", {"action": "redo"}, ws, "s1") == "forbidden"
    assert lib.job_vlm("movie", {"action": "movie"}, ws, "s2") == "required"


def test_vl2_jobs_carry_their_vlm_policy(http_env, monkeypatch, tmp_path):
    s, ws, state = http_env["srv"], http_env["ws"], http_env["state"]
    mt.smoke_host(monkeypatch, tmp_path)
    _write_story(ws, "written")

    def created(method_path, body):
        status, _h, payload = mt.api(s, "POST", method_path, body=body)
        assert status == 201, (method_path, payload)
        return lib.read_job(lib.job_dir(state, payload["job"]["id"]))

    compose = (("story", mt.fields(ws), "required"),
               ("regenerate", mt.fields(ws, action="regenerate"), "required"),
               ("movie without story.md", mt.fields(ws, action="movie", story_id="fresh",
                                                    mode="no_stills"), "required"),
               ("movie with story.md", mt.fields(ws, action="movie", story_id="written",
                                                 mode="no_stills"), "forbidden"),
               ("smoke", mt.fields(ws, action="smoke"), "forbidden"))
    for name, body, policy in compose:
        assert created("/api/jobs", body)["vlm"] == policy, name
    character = {"ws": ws, "name": "kyra", "phrase": "the young woman", "class_noun": "woman",
                 "descriptor": "a tall young woman", "trigger": None, "seed": None,
                 "seed_upload": None, "force": False}
    routes = (("/api/characters", character, "character-create", "required"),
              ("/api/characters/kyra/regenerate", {"ws": ws}, "character-regenerate", "required"),
              ("/api/characters/kyra/train", {"ws": ws, "video": True}, "character-train",
               "forbidden"),
              ("/api/actions/roundhouse-kick/train", {"ws": ws}, "action-train", "forbidden"),
              ("/api/models/download", {"ws": ws, "repo": "org/name"}, "download", "any"))
    for path, body, kind, policy in routes:
        job = created(path, body)
        assert (job["kind"], job["vlm"]) == (kind, policy), path
        assert list(job)[-2:] == ["vlm", "created"]
    # The two kinds no HTTP test can submit on this host (redo needs the stills stack, an action
    # create needs real clips) go through the same create_job.
    for kind, fields, story_id, policy in (("movie", {"action": "redo"}, "written", "forbidden"),
                                           ("action-create", {"name": "kick"}, None, "any")):
        job = lib.create_job(state, lib.new_job_id(state), kind, ws, story_id, None, ["x"], fields)
        assert job["vlm"] == policy, kind


def test_vl3_effective_vlm(tmp_path):
    ws = str(tmp_path)
    movie = {"kind": "movie", "workspace": ws, "story_id": "s1", "fields": {"action": "movie"},
             "vlm": "required"}
    assert lib.effective_vlm(movie) == "required"
    _write_story(ws, "s1")
    assert lib.effective_vlm(movie) == "forbidden"
    assert lib.effective_vlm(dict(movie, vlm="bogus")) == "forbidden"
    assert lib.effective_vlm({"kind": "story"}) == "any"
    assert lib.effective_vlm({"kind": "story", "vlm": "bogus"}) == "any"
    assert lib.effective_vlm({"kind": "story", "vlm": "required"}) == "required"
    assert lib.effective_vlm({"kind": "smoke", "vlm": "forbidden"}) == "forbidden"


def test_vl4_next_queued_job(state, tmp_path):
    ws = str(tmp_path)
    assert lib.next_queued_job(state) == (None, None)
    done = mt.make_job(state, ["x"], ws, kind="smoke")
    lib.write_status(lib.job_dir(state, done), {"state": "cancelled", "exit_code": None,
                                                "ended": lib.utc_now()})
    gone = mt.make_job(state, ["x"], ws, kind="smoke")
    os.unlink(os.path.join(lib.job_dir(state, gone), "job.json"))
    nxt = mt.make_job(state, ["x"], ws, kind="download")
    job_id, job = lib.next_queued_job(state)
    assert job_id == nxt and job["kind"] == "download"
    assert lib.read_queue(state) == [done, gone, nxt]
    lib.write_queue(state, [done, gone])
    assert lib.next_queued_job(state) == (None, None)


def test_vl5_vlm_restore_wanted(state, tmp_path):
    ws = str(tmp_path)
    assert lib.vlm_restore_wanted(state) == (True, "queue empty")
    for kind, wanted, text in (("story", True, "next job %s needs it"),
                               ("smoke", False, "next job %s runs without it"),
                               ("download", False, "next job %s is vlm=any")):
        lib.write_queue(state, [])
        job_id = mt.make_job(state, ["x"], ws, kind=kind)
        assert lib.vlm_restore_wanted(state) == (wanted, text % job_id), kind
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_vlm_lifecycle.py tests/test_movie_ui_jobs.py 2>&1 | tail -3
```

Expected: `5 failed, 16 passed, 3 errors`: the four VL tests without fixtures and `test_store_writes_atomically_with_private_modes` fail with `AttributeError` or the missing `vlm` key; `test_vl2`, `test_vl4` and `test_vl5` error in setup, because their fixtures set `lib.VLM_RECOVERY`, which does not exist yet.

- [ ] **Step 3: Implement.**

**3.1.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    job = {"schema": JOB_SCHEMA, "id": job_id, "kind": kind, "workspace": workspace,
           "story_id": story_id, "character": character, "argv": list(argv),
           "fields": fields, "created": utc_now()}
```

with:

```python
    job = {"schema": JOB_SCHEMA, "id": job_id, "kind": kind, "workspace": workspace,
           "story_id": story_id, "character": character, "argv": list(argv),
           "fields": fields, "vlm": job_vlm(kind, fields, workspace, story_id), "created": utc_now()}
```

**3.2.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
# ---------------------------------------------------------------------------
# Liveness, the dispatcher, startup recovery and job actions (MU26, MU29-MU31, MU68).
```

with:

```python
# ---------------------------------------------------------------------------
# The VLM at job boundaries (docs/superpowers/specs/2026-10-25-vlm-lifecycle-design.md): each
# job's vlm policy, the runner's preflight and postflight, and the startup restore. Only
# bin/story-server and bin/story-server-restore start or stop the VLM; this code decides when.
# ---------------------------------------------------------------------------

VLM_MODE = "mlx-vision"
VLM_POLICIES = ("required", "forbidden", "any")
VLM_STATUS_TIMEOUT_S = 60
VLM_HTTP_TIMEOUT_S = 10
VLM_COMPLETION_TIMEOUT_S = 120
VLM_PREFLIGHT_TIMEOUT_S = 6900    # two restore --wait, two health checks and one stop (spec 2.5)
VLM_POSTFLIGHT_TIMEOUT_S = 90
VLM_TOOL_KILL_WAIT_S = 5
VLM_MAX_BODY = 1048576
VLM_RESTORE_LOG_TEXT = "~/.local/share/qwen-agent/story-server-restore.log"
HEALTH_LINE_RE = re.compile(r"^\s*health:\s*HTTP\s+\d{3}\s+model=(.+?)\s*$")
VLM_RECOVERY = []    # pending startup-restore reasons (server process only, VU2)
RESTORERS = []       # Popen objects of startup restores, polled (never waited for) to reap them


def vlm_lifecycle_enabled():
    """False only when MOVIE_UI_VLM_LIFECYCLE is "0": the runtime rollback switch, which the
    tests also use for isolation (spec 2.5, 11.1)."""
    return os.environ.get("MOVIE_UI_VLM_LIFECYCLE", "1") != "0"


def vlm_tools_dir(ui_ws=None):
    """The directory holding story-server and story-server-restore: MOVIE_UI_VLM_TOOLS when set,
    else the UI workspace's bin/, so the runner and its tools come from one release (VR1)."""
    return os.environ.get("MOVIE_UI_VLM_TOOLS") or os.path.join(
        ui_ws or os.path.dirname(os.path.realpath(__file__)), "bin")


def vlm_port():
    """The health check's port: MOVIE_UI_VLM_PORT, else 8177."""
    return int(os.environ.get("MOVIE_UI_VLM_PORT") or 8177)


def job_vlm(kind, fields, workspace, story_id):
    """The VLM state a job of kind needs: "required", "forbidden" or "any" (VP1). Pure except
    for one os.path.isfile (a movie whose story.md exists renders without the VLM)."""
    if kind in ("story", "character-create", "character-regenerate"):
        return "required"
    if kind == "movie":
        if (fields or {}).get("action") == "redo":
            return "forbidden"
        if not story_id:
            return "required"
        return ("forbidden" if os.path.isfile(os.path.join(story_dir(workspace, story_id), "story.md"))
                else "required")
    if kind in ("smoke", "character-train", "action-train"):
        return "forbidden"
    return "any"


def effective_vlm(job):
    """The policy at dispatch (VP2): a movie job is recomputed (a story job queued ahead of it
    can create story.md); any other job uses its recorded vlm, and no or an unknown key is "any"."""
    if job.get("kind") == "movie":
        return job_vlm("movie", job.get("fields"), job.get("workspace"), job.get("story_id"))
    vlm = job.get("vlm")
    return vlm if vlm in VLM_POLICIES else "any"


def next_queued_job(state):
    """(job_id, job) of the first queued ID without a status.json and with a readable job.json
    (the dispatcher's skip rule, MU30), else (None, None). Never writes (VP3)."""
    for job_id in read_queue(state):
        jdir = job_dir(state, job_id)
        if os.path.lexists(os.path.join(jdir, "status.json")):
            continue
        job = read_job(jdir)
        if job is not None:
            return job_id, job
    return None, None


def vlm_restore_wanted(state):
    """(wanted, why): restore the VLM after a job iff the queue is empty or the next job needs
    it (VP4)."""
    job_id, job = next_queued_job(state)
    if job is None:
        return True, "queue empty"
    policy = effective_vlm(job)
    if policy == "required":
        return True, "next job %s needs it" % job_id
    if policy == "forbidden":
        return False, "next job %s runs without it" % job_id
    return False, "next job %s is vlm=any" % job_id


# ---------------------------------------------------------------------------
# Liveness, the dispatcher, startup recovery and job actions (MU26, MU29-MU31, MU68).
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_vlm_lifecycle.py tests/test_movie_ui_jobs.py tests/test_movie_ui_http.py tests/test_model_download.py 2>&1 | tail -3
```

Expected: `89 passed` (about 40 seconds). Then the compile check with `FILES` = `movie_ui_lib.py tests/conftest.py tests/test_vlm_lifecycle.py tests/test_movie_ui_jobs.py`; expected `compiled 4` twice.

- [ ] **Step 5: Commit.**

```bash
git add movie_ui_lib.py tests/conftest.py tests/test_vlm_lifecycle.py tests/test_movie_ui_jobs.py
git diff --cached --name-only    # expected: the four paths above, each prefixed qwen-agent-workspace/
git commit -m "feat(movie-ui): per-job vlm policy, lifecycle switches and test isolation (VLM lifecycle 2.1, 2.5, VP1-VP4, 11.1; VL1-VL5)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: movie_ui_lib: the port-scoped health check

Implements VR4 and VU4 (`import http.client`; the MUT25 allowlist). Tests VL6, VL7, VL8 and Review Focus 4; builds the F-TOOLS and F-HTTP fakes of spec 11.2 that Tasks 7-12 use.

**Files:**
- Modify: `movie_ui_lib.py` (imports `:12-13`; a new block before the "Liveness, the dispatcher" header)
- Modify: `tests/test_movie_ui_builder.py` (`test_mut25_source_scan_of_new_python_files`'s `allowed` `:247-249`)
- Modify: `tests/test_vlm_lifecycle.py` (append)

**Interfaces:**
- Consumes: Task 5's constants (`VLM_MODE`, `VLM_STATUS_TIMEOUT_S`, `VLM_HTTP_TIMEOUT_S`, `VLM_COMPLETION_TIMEOUT_S`, `VLM_MAX_BODY`, `HEALTH_LINE_RE`); `run_light`, `STATE_LINE_RE` (existing); Task 2's `story-server status` `health: HTTP <code> model=<id>` line.
- Produces (in `movie_ui_lib`): `_vlm_request(port, timeout, method, path, body=None) -> (reply or None, what or None)`; `vlm_health(tools, port, status_timeout=VLM_STATUS_TIMEOUT_S, http_timeout=VLM_HTTP_TIMEOUT_S, completion_timeout=VLM_COMPLETION_TIMEOUT_S) -> (ok, detail)` with the H1-H9 texts of spec 10. In `tests/test_vlm_lifecycle.py`: `MODEL`, `FAKE_TOOL_SOURCE`, `make_fake_tools(tmp, model, stop_rc=0, restore_rc=0, restore_sleep=0, serve_on_restore=True) -> tools dir`, `tool_calls(tools, include_status=False) -> [dict]`, `call_names(tools, include_status=False) -> [str]` (`"restore --wait"`, `"restore"`, `"stop"`, `"status"`, `"lockinfo"`), `set_vlm_state(tools, text)`, `set_tool_config(tools, config)`, `lifecycle_on(monkeypatch, tools, port)`, `class FakeVLM(models, models_status=200, completion_status=200, completion_body=None, completion_delay=0, models_raw=None)` with `.port`, `.requests`, `.close()`, the `vlm` fixture (a `FakeVLM` listing `MODEL` as loaded), `_free_closed_port()`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_vl6_health_happy_path`, `test_vl7_health_problems`, `test_vl8_health_request_shape`, `test_review_focus_4_models_reply_not_utf8_or_oversized`.

**1.1.** Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
        allowed = {"argparse", "calendar", "errno", "fcntl", "hashlib", "hmac", "http.server", "json", "os",
                   "platform", "re", "secrets", "shlex", "shutil", "signal", "socket", "struct", "subprocess",
                   "sys", "threading", "time", "fleet_lib", "movie_ui_lib"}
```

with:

```python
        allowed = {"argparse", "calendar", "errno", "fcntl", "hashlib", "hmac", "http.client", "http.server",
                   "json", "os", "platform", "re", "secrets", "shlex", "shutil", "signal", "socket", "struct",
                   "subprocess", "sys", "threading", "time", "fleet_lib", "movie_ui_lib"}
```

**1.2.** Append to `tests/test_vlm_lifecycle.py`:

```python
# --- F-TOOLS and F-HTTP (spec 11.2) ------------------------------------------------------------

MODEL = "test-vlm-model"
COMPLETION = {"model": MODEL, "max_tokens": 1,
              "messages": [{"role": "user", "content": "Reply with the single word ok"}]}

FAKE_TOOL_SOURCE = r'''
import fcntl
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
args = sys.argv[1:]
record = {"tool": TOOL, "argv": args, "pid": os.getpid(), "ppid": os.getppid(),
          "pgid": os.getpgid(0), "sid": os.getsid(0), "t": time.time()}
probe = os.environ.get("FAKE_PROBE_JOB_DIR")
if probe and TOOL == "story-server-restore":
    fd = os.open(os.path.join(probe, "lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record["job_lock_held"] = False
        fcntl.flock(fd, fcntl.LOCK_UN)
    except BlockingIOError:
        record["job_lock_held"] = True
    os.close(fd)
    try:
        with open(os.path.join(probe, "status.json"), encoding="utf-8") as f:
            record["job_state"] = json.load(f).get("state")
    except (OSError, ValueError):
        record["job_state"] = None
with open(os.path.join(HERE, "calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps(record) + "\n")
try:
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        config = json.load(f)
except (OSError, ValueError):
    config = {}


def set_state(text):
    with open(os.path.join(HERE, "vlm_state"), "w", encoding="utf-8") as f:
        f.write(text)


if TOOL == "story-server":
    if args == ["status"]:
        entry = config.get("status", {})
        time.sleep(entry.get("sleep", 0))
        with open(os.path.join(HERE, "vlm_state"), encoding="utf-8") as f:
            vlm_state = f.read().strip()
        sys.stdout.write(entry.get("stdout", "story-server status  X\n  state:          %s\n"
                                             "  health:         HTTP 200 model=%s\n"
                                             % (vlm_state, PARAMS["model"])))
        sys.exit(entry.get("exit", 0))
    if args == ["stop"]:
        set_state("STOPPED")
        sys.exit(PARAMS["stop_rc"])
    if args == ["lockinfo"]:
        sys.stdout.write("lock: free path=x\n")
        sys.exit(0)
    sys.exit(0)
if "--wait" in args:
    time.sleep(PARAMS["restore_sleep"])
    if PARAMS["serve_on_restore"]:
        set_state("SERVING mlx-vision")
    sys.exit(PARAMS["restore_rc"])
sys.exit(0)
'''


def make_fake_tools(tmp, model, stop_rc=0, restore_rc=0, restore_sleep=0, serve_on_restore=True):
    """F-TOOLS: <tmp>/tools/story-server and story-server-restore, #!sys.executable scripts that
    append one JSON line per call to <tmp>/tools/calls.jsonl and share <tmp>/tools/vlm_state
    (initially STOPPED); <tmp>/tools/config.json {"status": {"exit", "sleep", "stdout"}}
    overrides status. Returns the tools directory."""
    tools = os.path.join(str(tmp), "tools")
    os.makedirs(tools, exist_ok=True)
    params = {"model": model, "stop_rc": stop_rc, "restore_rc": restore_rc,
              "restore_sleep": restore_sleep, "serve_on_restore": serve_on_restore}
    for tool in ("story-server", "story-server-restore"):
        path = os.path.join(tools, tool)
        with open(path, "w", encoding="utf-8") as f:
            f.write("#!%s\nTOOL = %r\nPARAMS = %r\n%s" % (sys.executable, tool, params,
                                                         FAKE_TOOL_SOURCE))
        os.chmod(path, 0o755)
    set_vlm_state(tools, "STOPPED")
    return tools


def set_vlm_state(tools, text):
    with open(os.path.join(tools, "vlm_state"), "w", encoding="utf-8") as f:
        f.write(text)


def set_tool_config(tools, config):
    with open(os.path.join(tools, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)


def tool_calls(tools, include_status=False):
    try:
        with open(os.path.join(tools, "calls.jsonl"), encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
    except OSError:
        rows = []
    return [r for r in rows if include_status or r["argv"] != ["status"]]


def call_names(tools, include_status=False):
    out = []
    for row in tool_calls(tools, include_status):
        if row["tool"] == "story-server-restore":
            out.append("restore --wait" if "--wait" in row["argv"] else "restore")
        else:
            out.append(" ".join(row["argv"]))
    return out


def lifecycle_on(monkeypatch, tools, port):
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "1")
    monkeypatch.setenv("MOVIE_UI_VLM_TOOLS", tools)
    monkeypatch.setenv("MOVIE_UI_VLM_PORT", str(port))
    monkeypatch.setattr(lib, "VLM_RECOVERY", [])


class FakeVLM(object):
    """F-HTTP: a ThreadingHTTPServer on 127.0.0.1:0 serving GET /v1/models (models, or the raw
    bytes models_raw, with models_status) and POST /v1/chat/completions (completion_body after
    completion_delay s, with completion_status; a list status is consumed one per request, its
    last value repeating). Every request is recorded as (method, path, JSON body or None)."""

    def __init__(self, models, models_status=200, completion_status=200, completion_body=None,
                 completion_delay=0, models_raw=None):
        self.models, self.models_status, self.models_raw = models, models_status, models_raw
        self.completion_status, self.completion_body = completion_status, completion_body
        self.completion_delay = completion_delay
        self.requests = []
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, status, raw):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except OSError:
                    pass

            def do_GET(self):
                fake.requests.append(("GET", self.path, None))
                raw = fake.models_raw
                if raw is None:
                    raw = json.dumps({"object": "list", "data": fake.models}).encode("utf-8")
                self._reply(fake.models_status, raw)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                fake.requests.append(("POST", self.path, json.loads(raw.decode("utf-8")) if raw else None))
                time.sleep(fake.completion_delay)
                status = fake.completion_status
                if isinstance(status, list):
                    status = status.pop(0) if len(status) > 1 else status[0]
                body = fake.completion_body
                if body is None:
                    body = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
                self._reply(status, json.dumps(body).encode("utf-8"))

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def vlm():
    fake = FakeVLM([{"id": "other-cached-model", "loaded": False}, {"id": MODEL, "loaded": True}])
    yield fake
    fake.close()


def _free_closed_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# --- VL6-VL8, Review Focus 4: the health check (VR4) -------------------------------------------

def test_vl6_health_happy_path(tmp_path, vlm):
    tools = make_fake_tools(tmp_path, MODEL)
    set_vlm_state(tools, "SERVING mlx-vision")
    assert lib.vlm_health(tools, vlm.port) == (True, "%s on 127.0.0.1:%d" % (MODEL, vlm.port))
    assert call_names(tools, include_status=True) == ["status"]


def test_vl7_health_problems(tmp_path):
    tools = make_fake_tools(tmp_path, MODEL)
    set_vlm_state(tools, "SERVING mlx-vision")
    serving = [{"id": MODEL, "loaded": True}]

    def health(fake=None, **kw):
        port = fake.port if fake is not None else _free_closed_port()
        try:
            return lib.vlm_health(tools, port, **kw)
        finally:
            if fake is not None:
                fake.close()

    set_tool_config(tools, {"status": {"sleep": 3}})
    assert health(status_timeout=1) == (False, "bin/story-server status timed out after 1 s")    # H1
    set_tool_config(tools, {"status": {"exit": 4}})
    assert health() == (False, "bin/story-server status exited 4")                                # H2
    set_tool_config(tools, {})
    set_vlm_state(tools, "LOADING mlx-vision")
    assert health() == (False, "story server is LOADING mlx-vision, not SERVING mlx-vision")      # H3
    set_tool_config(tools, {"status": {"stdout": "story-server status  X\n"}})
    assert health() == (False, "story server is UNKNOWN, not SERVING mlx-vision")
    set_tool_config(tools, {"status": {"stdout": "  state:          SERVING mlx-vision\n"
                                                 "  health:         HTTP 000 model=none\n"}})
    assert health() == (False, "bin/story-server status printed no served model")                # H9
    set_tool_config(tools, {"status": {"stdout": "  state:          SERVING mlx-vision\n"}})
    assert health() == (False, "bin/story-server status printed no served model")
    set_tool_config(tools, {})
    set_vlm_state(tools, "SERVING mlx-vision")
    assert health(FakeVLM(serving, models_status=503)) == (False, "GET /v1/models failed: HTTP 503")
    assert health(FakeVLM(serving, models_raw=b"{")) == (False, "GET /v1/models failed: invalid JSON")
    assert health(FakeVLM(serving, models_raw=b'{"data": {}}')) == (
        False, "GET /v1/models failed: invalid JSON")
    assert health() == (False, "GET /v1/models failed: ConnectionRefusedError")                   # H4
    assert health(FakeVLM([{"id": "other", "loaded": True}])) == (
        False, "GET /v1/models does not list %s" % MODEL)                                       # H5
    assert health(FakeVLM([{"id": MODEL, "loaded": False}])) == (
        False, "%s is listed by /v1/models but not loaded" % MODEL)                             # H6
    assert health(FakeVLM([{"id": MODEL}]))[0] is True
    assert health(FakeVLM(serving, completion_status=500)) == (False, "completion failed: HTTP 500")
    assert health(FakeVLM(serving, completion_delay=3), completion_timeout=1) == (
        False, "completion failed: TimeoutError")                                               # H7
    assert health(FakeVLM(serving, completion_body={"choices": []})) == (
        False, "completion reply has no choices")                                               # H8
    assert health(FakeVLM(serving, completion_body={"text": "ok"})) == (
        False, "completion reply has no choices")


def test_vl8_health_request_shape(tmp_path, vlm):
    tools = make_fake_tools(tmp_path, MODEL)
    set_vlm_state(tools, "SERVING mlx-vision")
    assert lib.vlm_health(tools, vlm.port)[0] is True
    assert vlm.requests == [("GET", "/v1/models", None), ("POST", "/v1/chat/completions", COMPLETION)]
    other = FakeVLM([{"id": "other", "loaded": True}])
    try:
        assert lib.vlm_health(tools, other.port)[1] == "GET /v1/models does not list %s" % MODEL
        assert other.requests == [("GET", "/v1/models", None)]
    finally:
        other.close()


def test_review_focus_4_models_reply_not_utf8_or_oversized(tmp_path):
    tools = make_fake_tools(tmp_path, MODEL)
    set_vlm_state(tools, "SERVING mlx-vision")
    big = b'{"data": [' + b" " * lib.VLM_MAX_BODY + b'{"id": "%s", "loaded": true}]}' % MODEL.encode()
    for raw in (b'{"data": [{"id": "\xff\xfe"}]}', big):
        fake = FakeVLM([], models_raw=raw)
        try:
            assert lib.vlm_health(tools, fake.port) == (False, "GET /v1/models failed: invalid JSON")
            assert [r[0] for r in fake.requests] == ["GET"]
        finally:
            fake.close()
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_vlm_lifecycle.py -k "vl6 or vl7 or vl8 or review_focus_4" 2>&1 | tail -3
python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py -k mut25 2>&1 | tail -1
```

Expected: `4 failed, 7 deselected` (`AttributeError: module 'movie_ui_lib' has no attribute 'vlm_health'`); then `3 passed, 9 deselected` (the widened allowlist is a superset of today's imports).

- [ ] **Step 3: Implement.**

**3.1.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
import fcntl
import json
```

with:

```python
import fcntl
import http.client
import json
```

**3.2.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    return False, "next job %s is vlm=any" % job_id


# ---------------------------------------------------------------------------
# Liveness, the dispatcher, startup recovery and job actions (MU26, MU29-MU31, MU68).
```

with:

```python
    return False, "next job %s is vlm=any" % job_id


def _vlm_request(port, timeout, method, path, body=None):
    """One loopback request to the VLM (VR4; http.client ignores proxy variables, GC3): (reply,
    None) with the parsed JSON of a 200 reply (at most VLM_MAX_BODY bytes read), else (None,
    what) with what "HTTP <n>", "invalid JSON" or the exception class name."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        if body is None:
            conn.request(method, path)
        else:
            conn.request(method, path, body=json.dumps(body).encode("utf-8"),
                         headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        raw = resp.read(VLM_MAX_BODY)
        if resp.status != 200:
            return None, "HTTP %d" % resp.status
    except (OSError, http.client.HTTPException) as e:
        return None, type(e).__name__
    finally:
        conn.close()
    try:
        return json.loads(raw.decode("utf-8")), None
    except (ValueError, RecursionError):
        return None, "invalid JSON"


def vlm_health(tools, port, status_timeout=VLM_STATUS_TIMEOUT_S, http_timeout=VLM_HTTP_TIMEOUT_S,
               completion_timeout=VLM_COMPLETION_TIMEOUT_S):
    """(ok, detail) of the port-scoped health check (VR4), called only from vlm_preflight: one
    bin/story-server status, one GET /v1/models, one 1-token completion, in that order and
    without retries; the first failure returns its H1-H9 text (spec 10)."""
    run = run_light([os.path.join(tools, "story-server"), "status"], tools, timeout=status_timeout)
    if run["timed_out"]:
        return False, "bin/story-server status timed out after %d s" % status_timeout
    if run["exit_code"] != 0:
        return False, "bin/story-server status exited %s" % (
            "none" if run["exit_code"] is None else run["exit_code"])
    lines = run["stdout"].splitlines()
    state = next((m.group(1) for m in (STATE_LINE_RE.match(l) for l in lines) if m), "UNKNOWN")
    if state != "SERVING " + VLM_MODE:
        return False, "story server is %s, not SERVING %s" % (state, VLM_MODE)
    model = next((m.group(1) for m in (HEALTH_LINE_RE.match(l) for l in lines) if m), None)
    if model is None or model == "none":
        return False, "bin/story-server status printed no served model"
    reply, what = _vlm_request(port, http_timeout, "GET", "/v1/models")
    data = reply.get("data") if isinstance(reply, dict) else None
    if what is None and not isinstance(data, list):
        what = "invalid JSON"
    if what is not None:
        return False, "GET /v1/models failed: %s" % what
    entries = [d for d in data if isinstance(d, dict) and d.get("id") == model]
    if not entries:
        return False, "GET /v1/models does not list %s" % model
    if "loaded" in entries[0] and entries[0]["loaded"] is not True:
        return False, "%s is listed by /v1/models but not loaded" % model
    reply, what = _vlm_request(port, completion_timeout, "POST", "/v1/chat/completions",
                               {"model": model, "max_tokens": 1, "messages": [
                                   {"role": "user", "content": "Reply with the single word ok"}]})
    if what is not None:
        return False, "completion failed: %s" % what
    choices = reply.get("choices") if isinstance(reply, dict) else None
    if not (isinstance(choices, list) and choices):
        return False, "completion reply has no choices"
    return True, "%s on 127.0.0.1:%d" % (model, port)


# ---------------------------------------------------------------------------
# Liveness, the dispatcher, startup recovery and job actions (MU26, MU29-MU31, MU68).
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_vlm_lifecycle.py 2>&1 | tail -1
python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py -k "not mut26" 2>&1 | tail -1
```

Expected: `11 passed` (about 12 seconds; `test_vl7` waits out the H1 and H7 timeouts); then `11 passed, 1 deselected` (`test_mut26` is deselected: it fails from Task 4 until Task 13). Then the compile check with `FILES` = `movie_ui_lib.py tests/test_vlm_lifecycle.py tests/test_movie_ui_builder.py`; expected `compiled 3` twice.

- [ ] **Step 5: Commit.**

```bash
git add movie_ui_lib.py tests/test_vlm_lifecycle.py tests/test_movie_ui_builder.py
git diff --cached --name-only    # expected: the three paths above, each prefixed qwen-agent-workspace/
git commit -m "feat(movie-ui): port-scoped VLM health check over http.client (VLM lifecycle VR4, VU4; VL6-VL8)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: movie_ui_lib: the runner's preflight

Implements VR2, VR3 (with `_stop_tool`) and `_vlm_other_mode`. Tests VL3 (the preflight line), VL9-VL16, VL28 and Review Focus 5.

**Files:**
- Modify: `movie_ui_lib.py` (a new block before the "Liveness, the dispatcher" header, after `vlm_health`)
- Modify: `tests/test_vlm_lifecycle.py` (append)

**Interfaces:**
- Consumes: Task 5's `effective_vlm`, `vlm_tools_dir`, `vlm_port`, `VLM_MODE`, `VLM_POLICIES`, `VLM_PREFLIGHT_TIMEOUT_S`, `VLM_TOOL_KILL_WAIT_S`, `VLM_STATUS_TIMEOUT_S`, `VLM_RESTORE_LOG_TEXT`; Task 6's `vlm_health(tools, port)`; `_say`, `run_light`, `STATE_LINE_RE` (existing); Task 3's `story-server-restore mlx-vision --wait` exit codes; F-TOOLS and F-HTTP from Task 6.
- Produces (in `movie_ui_lib`): `vlm_preflight(job, cancel, tools=None, port=None, health=None, timeout=VLM_PREFLIGHT_TIMEOUT_S) -> ("ok", None) | ("failed", error) | ("cancelled", None)`; `_vlm_step(argv, cancel, deadline, timeout) -> ("exit", rc) | ("cancelled", None) | ("failed", error)`; `_stop_tool(proc)`; `_vlm_other_mode(tools) -> "vision" | "text" | None`. Task 8's `run_job` calls `vlm_preflight(job, cancel)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_vl3_preflight_reports_a_recomputed_movie_policy`, `test_vl9_preflight_required_and_healthy`, `test_vl10_preflight_unhealthy_then_healthy`, `test_vl11_preflight_unhealthy_twice`, `test_vl12_preflight_restore_fails_twice`, `test_vl13_preflight_forbidden`, `test_vl14_preflight_any`, `test_vl15_cancel_during_preflight`, `test_vl16_preflight_timeout`, `test_vl28_another_mode_fails_without_a_stop`, `test_review_focus_5_tools_path_with_a_space`.

**1.1.** Append to `tests/test_vlm_lifecycle.py`:

```python
# --- VL3, VL9-VL16, VL28, Review Focus 5: the preflight (VR2, VR3) -----------------------------

REQUIRED = {"kind": "story", "vlm": "required"}
RESTORE_EXIT_1 = ("bin/story-server-restore mlx-vision --wait exited 1 "
                  "(see ~/.local/share/qwen-agent/story-server-restore.log)")


def _say_lines(capsys):
    return [line for line in capsys.readouterr().out.splitlines() if line.startswith("[movie-ui] ")]


def _preflight(tmp_path, job, tools, port, **kw):
    return lib.vlm_preflight(job, str(tmp_path / "cancel"), tools=tools, port=port, **kw)


def test_vl3_preflight_reports_a_recomputed_movie_policy(tmp_path, vlm, capsys):
    ws = str(tmp_path / "ws")
    tools = make_fake_tools(tmp_path, MODEL)
    movie = {"kind": "movie", "workspace": ws, "story_id": "s1", "fields": {"action": "movie"},
             "vlm": "required"}
    _write_story(ws, "s1")
    assert _preflight(tmp_path, movie, tools, vlm.port) == ("ok", None)
    assert _say_lines(capsys)[0] == ("[movie-ui] vlm: job.json says vlm=required; story.md exists now, "
                                     "so vlm=forbidden")
    assert call_names(tools) == ["stop"]
    os.unlink(os.path.join(lib.story_dir(ws, "s1"), "story.md"))
    movie["vlm"] = "forbidden"
    assert _preflight(tmp_path, movie, tools, vlm.port) == ("ok", None)
    assert _say_lines(capsys)[0] == ("[movie-ui] vlm: job.json says vlm=forbidden; story.md is missing "
                                     "now, so vlm=required")
    movie["vlm"] = "required"
    assert _preflight(tmp_path, movie, tools, vlm.port) == ("ok", None)
    assert "job.json says" not in " ".join(_say_lines(capsys))


def test_vl9_preflight_required_and_healthy(tmp_path, vlm, capsys):
    tools = make_fake_tools(tmp_path, MODEL)
    assert _preflight(tmp_path, REQUIRED, tools, vlm.port) == ("ok", None)
    assert call_names(tools) == ["restore --wait"]
    assert call_names(tools, include_status=True) == ["restore --wait", "status"]
    assert _say_lines(capsys) == [
        "[movie-ui] vlm: preflight: this job needs the VLM (vlm=required)",
        "[movie-ui] vlm: running: %s mlx-vision --wait" % os.path.join(tools, "story-server-restore"),
        "[movie-ui] vlm: healthy: %s on 127.0.0.1:%d" % (MODEL, vlm.port)]


def test_vl10_preflight_unhealthy_then_healthy(tmp_path, capsys):
    tools = make_fake_tools(tmp_path, MODEL)
    fake = FakeVLM([{"id": MODEL, "loaded": True}], completion_status=[500, 200])
    try:
        assert _preflight(tmp_path, REQUIRED, tools, fake.port) == ("ok", None)
    finally:
        fake.close()
    assert call_names(tools) == ["restore --wait", "stop", "restore --wait"]
    lines = _say_lines(capsys)
    assert "[movie-ui] vlm: unhealthy: completion failed: HTTP 500; restarting it once" in lines
    assert lines[-1] == "[movie-ui] vlm: healthy: %s on 127.0.0.1:%d" % (MODEL, fake.port)


def test_vl11_preflight_unhealthy_twice(tmp_path):
    tools = make_fake_tools(tmp_path, MODEL)
    fake = FakeVLM([{"id": MODEL, "loaded": True}], completion_status=500)
    try:
        assert _preflight(tmp_path, REQUIRED, tools, fake.port) == (
            "failed", "VLM preflight failed after one restart: completion failed: HTTP 500")
    finally:
        fake.close()
    assert call_names(tools) == ["restore --wait", "stop", "restore --wait"]


def test_vl12_preflight_restore_fails_twice(tmp_path, vlm):
    tools = make_fake_tools(tmp_path, MODEL, restore_rc=1)
    assert _preflight(tmp_path, REQUIRED, tools, vlm.port) == (
        "failed", "VLM preflight failed after one restart: " + RESTORE_EXIT_1)
    assert call_names(tools) == ["restore --wait", "stop", "restore --wait"]
    # The one status call is _vlm_other_mode's; no health check ran.
    assert call_names(tools, include_status=True) == ["restore --wait", "status", "stop",
                                                      "restore --wait"]
    assert vlm.requests == []


def test_vl13_preflight_forbidden(tmp_path, vlm, capsys):
    tools = make_fake_tools(tmp_path, MODEL)
    job = {"kind": "smoke", "vlm": "forbidden"}
    assert _preflight(tmp_path, job, tools, vlm.port) == ("ok", None)
    assert call_names(tools, include_status=True) == ["stop"]
    assert _say_lines(capsys) == [
        "[movie-ui] vlm: preflight: this job runs without the VLM (vlm=forbidden)",
        "[movie-ui] vlm: running: %s stop" % os.path.join(tools, "story-server"),
        "[movie-ui] vlm: stopped for this job"]
    failing = make_fake_tools(tmp_path / "rc3", MODEL, stop_rc=3)
    assert _preflight(tmp_path, job, failing, vlm.port) == (
        "failed", "VLM preflight failed: bin/story-server stop exited 3; the log above shows why")


def test_vl14_preflight_any(tmp_path, vlm, capsys):
    tools = make_fake_tools(tmp_path, MODEL)
    assert _preflight(tmp_path, {"kind": "download", "vlm": "any"}, tools, vlm.port) == ("ok", None)
    assert _preflight(tmp_path, {"kind": "download"}, tools, vlm.port) == ("ok", None)
    assert tool_calls(tools, include_status=True) == []
    assert _say_lines(capsys) == ["[movie-ui] vlm: preflight: vlm=any; the VLM is left as it is"] * 2


def test_vl15_cancel_during_preflight(tmp_path, vlm):
    tools = make_fake_tools(tmp_path, MODEL, restore_sleep=30)
    cancel = tmp_path / "cancel"
    threading.Timer(1.0, cancel.touch).start()
    started = time.monotonic()
    assert _preflight(tmp_path, REQUIRED, tools, vlm.port) == ("cancelled", None)
    assert time.monotonic() - started < 8
    row = tool_calls(tools)[0]
    assert row["tool"] == "story-server-restore"
    assert not mt.pid_alive(row["pid"])


def test_vl16_preflight_timeout(tmp_path, vlm):
    tools = make_fake_tools(tmp_path, MODEL, restore_sleep=30)
    started = time.monotonic()
    assert _preflight(tmp_path, REQUIRED, tools, vlm.port, timeout=2) == (
        "failed", "VLM preflight timed out after 2 s")
    assert time.monotonic() - started < 10
    assert not mt.pid_alive(tool_calls(tools)[0]["pid"])


def test_vl28_another_mode_fails_without_a_stop(tmp_path, vlm):
    for i, state_text, mode in ((0, "SERVING vision", "vision"), (1, "LOADING text", "text")):
        tools = make_fake_tools(tmp_path / str(i), MODEL, restore_rc=1, serve_on_restore=False)
        set_vlm_state(tools, state_text)
        assert _preflight(tmp_path, REQUIRED, tools, vlm.port) == (
            "failed", "VLM preflight failed: the story server runs in %s mode, not mlx-vision; stop "
                      "it with bin/story-server stop and resubmit" % mode)
        assert call_names(tools, include_status=True) == ["restore --wait", "status"]
    tools = make_fake_tools(tmp_path / "foreign", MODEL, restore_rc=1, serve_on_restore=False)
    set_vlm_state(tools, "FOREIGN pid 5")
    assert _preflight(tmp_path, REQUIRED, tools, vlm.port) == (
        "failed", "VLM preflight failed after one restart: " + RESTORE_EXIT_1)
    assert call_names(tools) == ["restore --wait", "stop", "restore --wait"]


def test_review_focus_5_tools_path_with_a_space(tmp_path, vlm, capsys):
    tools = make_fake_tools(tmp_path / "my ui ws", MODEL)
    assert " " in tools
    assert _preflight(tmp_path, REQUIRED, tools, vlm.port) == ("ok", None)
    restore = os.path.join(tools, "story-server-restore")
    assert _say_lines(capsys)[1] == "[movie-ui] vlm: running: '%s' mlx-vision --wait" % restore
    assert call_names(tools) == ["restore --wait"]
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_vlm_lifecycle.py -k "preflight or vl15 or vl28 or review_focus_5" 2>&1 | tail -3
```

Expected: `11 failed, 11 deselected`, each with `AttributeError: module 'movie_ui_lib' has no attribute 'vlm_preflight'`.

- [ ] **Step 3: Implement.**

**3.1.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    return True, "%s on 127.0.0.1:%d" % (model, port)


# ---------------------------------------------------------------------------
# Liveness, the dispatcher, startup recovery and job actions (MU26, MU29-MU31, MU68).
```

with:

```python
    return True, "%s on 127.0.0.1:%d" % (model, port)


def _stop_tool(proc):
    """SIGTERM a preflight tool, SIGKILL it after VLM_TOOL_KILL_WAIT_S, reap it (VR3). A waiting
    story-server-restore leaves its detached load running (VRS3)."""
    proc.terminate()
    try:
        proc.wait(VLM_TOOL_KILL_WAIT_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _vlm_step(argv, cancel, deadline, timeout):
    """Run one preflight tool as a child of the runner (its output goes to the runner's stdout and
    stderr, log.txt): ("exit", rc), ("cancelled", None) when the cancel marker appears, or
    ("failed", error) when it cannot start or the preflight deadline passes (VR3)."""
    _say("vlm: running: %s" % shlex.join(argv))
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, close_fds=True)
    except OSError as e:
        return "failed", "VLM preflight failed: cannot run %s: %s" % (argv[0], e.strerror or e)
    while True:
        try:
            proc.wait(timeout=1)
            return "exit", proc.returncode
        except subprocess.TimeoutExpired:
            if os.path.exists(cancel):
                _stop_tool(proc)
                return "cancelled", None
            if time.monotonic() >= deadline:
                _stop_tool(proc)
                return "failed", "VLM preflight timed out after %d s" % timeout


def _vlm_other_mode(tools):
    """"vision" or "text" when bin/story-server status reports SERVING or LOADING in that mode,
    else None (also on a timeout, a non-zero exit or no state line)."""
    run = run_light([os.path.join(tools, "story-server"), "status"], tools, timeout=VLM_STATUS_TIMEOUT_S)
    if run["timed_out"] or run["exit_code"] != 0:
        return None
    for line in run["stdout"].splitlines():
        match = STATE_LINE_RE.match(line)
        if match:
            other = re.fullmatch(r"(SERVING|LOADING) (vision|text)", match.group(1))
            return other.group(2) if other else None
    return None


def vlm_preflight(job, cancel, tools=None, port=None, health=None, timeout=VLM_PREFLIGHT_TIMEOUT_S):
    """Bring the VLM into the state the job needs before its child starts (VR2): "required" runs
    story-server-restore --wait and the health check, restarting the VLM once on a failure;
    "forbidden" runs story-server stop; "any" does nothing. Returns ("ok", None), ("failed",
    error) or ("cancelled", None)."""
    tools = vlm_tools_dir() if tools is None else tools
    port = vlm_port() if port is None else port
    health = vlm_health if health is None else health
    policy = effective_vlm(job)
    recorded = job.get("vlm")
    if job.get("kind") == "movie" and recorded in VLM_POLICIES and recorded != policy:
        _say("vlm: job.json says vlm=%s; story.md %s now, so vlm=%s"
             % (recorded, "exists" if policy == "forbidden" else "is missing", policy))
    deadline = time.monotonic() + timeout
    restore = [os.path.join(tools, "story-server-restore"), VLM_MODE, "--wait"]
    stop = [os.path.join(tools, "story-server"), "stop"]
    if policy == "any":
        _say("vlm: preflight: vlm=any; the VLM is left as it is")
        return "ok", None
    if policy == "forbidden":
        _say("vlm: preflight: this job runs without the VLM (vlm=forbidden)")
        outcome, value = _vlm_step(stop, cancel, deadline, timeout)
        if outcome != "exit":
            return outcome, value
        if value != 0:
            return "failed", ("VLM preflight failed: bin/story-server stop exited %d; the log above "
                              "shows why" % value)
        _say("vlm: stopped for this job")
        return "ok", None
    _say("vlm: preflight: this job needs the VLM (vlm=required)")
    for attempt in (1, 2):
        outcome, value = _vlm_step(restore, cancel, deadline, timeout)
        if outcome != "exit":
            return outcome, value
        if value != 0:
            problem = ("bin/story-server-restore %s --wait exited %d (see %s)"
                       % (VLM_MODE, value, VLM_RESTORE_LOG_TEXT))
        else:
            ok, problem = health(tools, port)
            if os.path.exists(cancel):
                return "cancelled", None
            if ok:
                _say("vlm: healthy: %s" % problem)
                return "ok", None
        if attempt == 2:
            return "failed", "VLM preflight failed after one restart: %s" % problem
        other = _vlm_other_mode(tools)
        if other is not None:
            return "failed", ("VLM preflight failed: the story server runs in %s mode, not %s; "
                              "stop it with bin/story-server stop and resubmit" % (other, VLM_MODE))
        _say("vlm: unhealthy: %s; restarting it once" % problem)
        outcome, value = _vlm_step(stop, cancel, deadline, timeout)
        if outcome != "exit":
            return outcome, value
        if value != 0:
            return "failed", ("VLM preflight failed: bin/story-server stop exited %d; the log above "
                              "shows why" % value)


# ---------------------------------------------------------------------------
# Liveness, the dispatcher, startup recovery and job actions (MU26, MU29-MU31, MU68).
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_vlm_lifecycle.py 2>&1 | tail -1
```

Expected: `22 passed` (about 25 seconds). Then the compile check with `FILES` = `movie_ui_lib.py tests/test_vlm_lifecycle.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add movie_ui_lib.py tests/test_vlm_lifecycle.py
git diff --cached --name-only    # expected: qwen-agent-workspace/movie_ui_lib.py, qwen-agent-workspace/tests/test_vlm_lifecycle.py
git commit -m "feat(movie-ui): runner preflight with one health-checked restart (VLM lifecycle VR2, VR3; VL3, VL9-VL16, VL28)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: movie_ui_lib: the runner calls the preflight and the postflight

Implements VR1 (steps 3b and 7, the postflight on the cancel-before-start and cannot-start paths, the child's `STORY_SERVER_ENGINE_SCAN="0"`) and VR5. Tests VL17-VL21 and Review Focus 1. VR6 (`cancel_tree` and `kill_orphan` unchanged) is pinned by VL22 in Task 12.

**Files:**
- Modify: `movie_ui_lib.py` (`run_job` `:300-354`; a new block before the "Liveness, the dispatcher" header, after `vlm_preflight`)
- Modify: `tests/test_vlm_lifecycle.py` (append)

**Interfaces:**
- Consumes: Task 5's `vlm_lifecycle_enabled`, `vlm_restore_wanted`, `vlm_tools_dir`, `VLM_MODE`, `VLM_POSTFLIGHT_TIMEOUT_S`; Task 7's `vlm_preflight(job, cancel)`; `_say`, `write_status`, `read_job` (existing).
- Produces (in `movie_ui_lib`): `vlm_postflight(state) -> None` (restores the VLM without `--wait`, detached under launchd by the restore, iff `vlm_restore_wanted(state)`; never raises for a missing tool or a timeout); `run_job(jdir, grace)` with the VR1 order (preflight after `read_job`, before `log.txt` is opened for the child; postflight after every final status, still holding `jdir/lock`; none on the return-3 path); the status row `{"state": "failed", "dispatched", "runner_pid", "pgid": None, "started": None, "exit_code": None, "ended", "error"}` for a preflight failure and `{"state": "cancelled", "exit_code": None, "ended"}` for a cancel during it (spec 2.2). In `tests/test_vlm_lifecycle.py`: `_final(state, job_id, timeout=30)`, `_child_probe(path)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_vl17_required_job_end_to_end`, `test_vl18_preflight_failure_end_to_end`, `test_vl19_postflight_runs_under_the_job_lock_after_the_final_status`, `test_vl20_postflight_decisions`, `test_vl21_back_to_back_renders_do_not_reload`, `test_review_focus_1_story_then_movie_of_the_same_story`.

**1.1.** Append to `tests/test_vlm_lifecycle.py`:

```python
# --- VL17-VL21, Review Focus 1: the runner's preflight and postflight (VR1, VR5) ----------------

STATUS_KEYS_FAILED = {"state", "dispatched", "runner_pid", "pgid", "started", "exit_code", "ended",
                      "error"}


def _final(state, job_id, timeout=30):
    return mt.wait_until(lambda: mt.status_of(state, job_id).get("state") in lib.FINISHED_STATES
                         and mt.status_of(state, job_id), timeout)


def _child_probe(path):
    """A job argv whose child records its own start time and STORY_SERVER_ENGINE_SCAN."""
    return mt.py_argv("import json, os, time\n"
                      "json.dump({'t': time.time(), 'scan': os.environ.get('STORY_SERVER_ENGINE_SCAN')}, "
                      "open(%r, 'w'))\n" % path)


def test_vl17_required_job_end_to_end(state, tmp_path, vlm, monkeypatch):
    tools = make_fake_tools(tmp_path, MODEL)
    lifecycle_on(monkeypatch, tools, vlm.port)
    probe = str(tmp_path / "child.json")
    job_id = mt.make_job(state, _child_probe(probe), str(tmp_path), kind="story")
    assert mt.dispatch(state, job_id).wait(timeout=60) == 0
    assert mt.status_of(state, job_id)["state"] == "done"
    lines = mt.read_log(state, job_id).splitlines()
    started = [i for i, line in enumerate(lines) if line.startswith("[movie-ui] started pid ")][0]
    assert [line for line in lines[:started] if line.startswith("[movie-ui] vlm:")] == [
        "[movie-ui] vlm: preflight: this job needs the VLM (vlm=required)",
        "[movie-ui] vlm: running: %s mlx-vision --wait" % os.path.join(tools, "story-server-restore"),
        "[movie-ui] vlm: healthy: %s on 127.0.0.1:%d" % (MODEL, vlm.port)]
    with open(probe) as f:
        child = json.load(f)
    assert child["scan"] == "0"
    rows = tool_calls(tools, include_status=True)
    assert [r["argv"] for r in rows if r["t"] < child["t"]] == [["mlx-vision", "--wait"], ["status"]]
    assert call_names(tools, include_status=True) == ["restore --wait", "status", "restore"]
    # The lifecycle off: no tool runs, and the child still gets STORY_SERVER_ENGINE_SCAN=0 (VR1).
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "0")
    probe_off = str(tmp_path / "child-off.json")
    off = mt.make_job(state, _child_probe(probe_off), str(tmp_path), kind="story")
    assert mt.dispatch(state, off).wait(timeout=60) == 0
    with open(probe_off) as f:
        assert json.load(f)["scan"] == "0"
    assert len(tool_calls(tools, include_status=True)) == 3
    assert "[movie-ui] vlm:" not in mt.read_log(state, off)


def test_vl18_preflight_failure_end_to_end(state, tmp_path, vlm, monkeypatch):
    tools = make_fake_tools(tmp_path, MODEL, restore_rc=1)
    lifecycle_on(monkeypatch, tools, vlm.port)
    job_id = mt.make_job(state, mt.py_argv("print('the child ran')"), str(tmp_path), kind="story")
    assert mt.dispatch(state, job_id).wait(timeout=60) == 1
    status = mt.status_of(state, job_id)
    assert set(status) == STATUS_KEYS_FAILED
    assert (status["state"], status["pgid"], status["started"], status["exit_code"]) == (
        "failed", None, None, None)
    assert status["error"] == "VLM preflight failed after one restart: " + RESTORE_EXIT_1
    assert call_names(tools) == ["restore --wait", "stop", "restore --wait", "restore"]
    log = mt.read_log(state, job_id)
    assert "the child ran" not in log and "[movie-ui] started pid" not in log
    assert "[movie-ui] " + status["error"] + "\n" in log
    assert "[movie-ui] vlm: postflight: restoring the VLM in its own session (queue empty)\n" in log


def test_vl19_postflight_runs_under_the_job_lock_after_the_final_status(state, tmp_path, vlm,
                                                                         monkeypatch):
    tools = make_fake_tools(tmp_path, MODEL)
    lifecycle_on(monkeypatch, tools, vlm.port)
    job_id = mt.make_job(state, mt.py_argv("import time; time.sleep(0.5)"), str(tmp_path),
                         kind="smoke")
    monkeypatch.setenv("FAKE_PROBE_JOB_DIR", lib.job_dir(state, job_id))
    assert mt.dispatch(state, job_id).wait(timeout=60) == 0
    status = mt.status_of(state, job_id)
    assert status["state"] == "done"
    restores = [r for r in tool_calls(tools) if r["tool"] == "story-server-restore"]
    assert len(restores) == 1 and restores[0]["argv"] == ["mlx-vision"]
    assert restores[0]["job_lock_held"] is True
    assert restores[0]["job_state"] == "done"
    assert restores[0]["pgid"] != status["pgid"]
    assert not lib.group_alive(status["pgid"])


def test_vl20_postflight_decisions(state, tmp_path, vlm, monkeypatch, capsys):
    tools = make_fake_tools(tmp_path, MODEL)
    lifecycle_on(monkeypatch, tools, vlm.port)
    ws = str(tmp_path)
    restore = os.path.join(tools, "story-server-restore")
    lib.vlm_postflight(state)
    assert call_names(tools) == ["restore"]
    assert _say_lines(capsys) == [
        "[movie-ui] vlm: postflight: restoring the VLM in its own session (queue empty)",
        "[movie-ui] vlm: running: %s mlx-vision" % restore]
    nxt = mt.make_job(state, ["x"], ws, kind="story")
    lib.vlm_postflight(state)
    assert call_names(tools) == ["restore", "restore"]
    assert _say_lines(capsys)[0] == ("[movie-ui] vlm: postflight: restoring the VLM in its own "
                                     "session (next job %s needs it)" % nxt)
    for kind, why in (("smoke", "next job %s runs without it"), ("download", "next job %s is vlm=any")):
        lib.write_queue(state, [])
        nxt = mt.make_job(state, ["x"], ws, kind=kind)
        lib.vlm_postflight(state)
        assert call_names(tools) == ["restore", "restore"], kind
        assert _say_lines(capsys) == ["[movie-ui] vlm: postflight: not restoring the VLM (%s)"
                                      % (why % nxt)]
    lib.write_queue(state, [])
    failing = str(tmp_path / "failing-tools")
    os.makedirs(failing)
    with open(os.path.join(failing, "story-server-restore"), "w") as f:
        f.write("#!/bin/sh\nexit 3\n")
    os.chmod(os.path.join(failing, "story-server-restore"), 0o755)
    monkeypatch.setenv("MOVIE_UI_VLM_TOOLS", failing)
    lib.vlm_postflight(state)
    assert _say_lines(capsys)[-1] == "[movie-ui] vlm: postflight: bin/story-server-restore exited 3"
    missing = str(tmp_path / "missing-tools")
    monkeypatch.setenv("MOVIE_UI_VLM_TOOLS", missing)
    lib.vlm_postflight(state)
    assert _say_lines(capsys)[-1] == ("[movie-ui] vlm: postflight: cannot run %s: No such file or "
                                      "directory" % os.path.join(missing, "story-server-restore"))


def test_vl21_back_to_back_renders_do_not_reload(state, tmp_path, vlm, monkeypatch):
    tools = make_fake_tools(tmp_path, MODEL)
    lifecycle_on(monkeypatch, tools, vlm.port)
    ws = str(tmp_path)
    first = mt.make_job(state, mt.py_argv("print('render 1')"), ws, kind="smoke")
    second = mt.make_job(state, mt.py_argv("print('render 2')"), ws, kind="smoke")
    assert lib.dispatch_tick(state, mt.WS) == first
    mt.wait_until(lambda: lib.dispatch_tick(state, mt.WS) == second, 30)
    _final(state, second)
    mt.wait_until(lambda: call_names(tools)[-1:] == ["restore"], 30)
    assert call_names(tools) == ["stop", "stop", "restore"]
    assert tool_calls(tools)[-1]["t"] >= lib.parse_utc(mt.status_of(state, second)["ended"])
    assert ("[movie-ui] vlm: postflight: not restoring the VLM (next job %s runs without it)"
            % second) in mt.read_log(state, first)
    log = mt.read_log(state, second)
    assert log.index("[movie-ui] exit 0 (done)") < log.index(
        "[movie-ui] vlm: postflight: restoring the VLM in its own session (queue empty)")


def test_review_focus_1_story_then_movie_of_the_same_story(state, tmp_path, vlm, monkeypatch):
    tools = make_fake_tools(tmp_path, MODEL)
    lifecycle_on(monkeypatch, tools, vlm.port)
    ws = str(tmp_path / "ws")
    os.makedirs(ws)
    sdir = lib.story_dir(ws, "s1")
    write_story = mt.py_argv("import os\nos.makedirs(%r, exist_ok=True)\n"
                             "open(os.path.join(%r, 'story.md'), 'w').write('## Panel 1\\n')\n"
                             % (sdir, sdir))
    story = mt.make_job(state, write_story, ws, kind="story", fields={"action": "story"})
    movie = mt.make_job(state, mt.py_argv("print('render')"), ws, kind="movie",
                        fields={"action": "movie"})
    assert lib.read_job(lib.job_dir(state, movie))["vlm"] == "required"
    assert lib.dispatch_tick(state, mt.WS) == story
    mt.wait_until(lambda: lib.dispatch_tick(state, mt.WS) == movie, 60)
    _final(state, movie)
    mt.wait_until(lambda: call_names(tools)[-1:] == ["restore"], 30)
    assert call_names(tools) == ["restore --wait", "stop", "restore"]
    assert mt.status_of(state, story)["state"] == "done"
    assert mt.status_of(state, movie)["state"] == "done"
    assert ("[movie-ui] vlm: postflight: not restoring the VLM (next job %s runs without it)"
            % movie) in mt.read_log(state, story)
    log = mt.read_log(state, movie)
    assert ("[movie-ui] vlm: job.json says vlm=required; story.md exists now, so vlm=forbidden"
            in log)
    assert log.index("[movie-ui] vlm: stopped for this job") < log.index("[movie-ui] started pid")
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_vlm_lifecycle.py -k "vl17 or vl18 or vl19 or vl20 or vl21 or review_focus_1" 2>&1 | tail -3
```

Expected: `6 failed, 22 deselected` (about a minute: VL21 and Review Focus 1 wait out their 30 s polls). VL17-VL19 and VL21 fail because HEAD's runner calls no tool (VL17 also because the child sees no `STORY_SERVER_ENGINE_SCAN`); VL20 with `AttributeError: ... 'vlm_postflight'`.

- [ ] **Step 3: Implement.**

**3.1.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
def run_job(jdir, grace=CANCEL_GRACE_S):
    """Run one dispatched job to its end (MU22). Returns 0 after a final status, 1 when the job
    argv could not be started, 3 when the status was not "starting" (MU24)."""
    lock_fd = os.open(os.path.join(jdir, "lock"), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    status = read_status(jdir) or {}
    if status.get("state") != "starting":
        _say("job is %s; nothing to run" % (status.get("state") or "unknown"))
        return 3
    cancel = os.path.join(jdir, "cancel")
    if os.path.exists(cancel):
        write_status(jdir, {"state": "cancelled", "exit_code": None, "ended": utc_now()})
        _say("cancelled before start")
        return 0
    job = read_job(jdir)
    log = open(os.path.join(jdir, "log.txt"), "ab")
    try:
        # Default the VLM model id to "auto" so the character/story pipeline resolves the
        # single *loaded* model the story-server reports (mlx_vlm serves it by path on this
        # host, not under the author's "qwen38-6bit" alias). An explicit env still wins.
        child = subprocess.Popen(
            job["argv"], cwd=job["workspace"],
            env=dict(os.environ, PYTHONUNBUFFERED="1",
                     QWEN_AGENT_VLM_MODEL=os.environ.get("QWEN_AGENT_VLM_MODEL") or "auto"),
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True, close_fds=True)
    except OSError as e:
        error = "cannot start: %s" % (e.strerror or e)
        write_status(jdir, {"state": "failed", "dispatched": status.get("dispatched"),
                            "runner_pid": os.getpid(), "pgid": None, "started": None,
                            "exit_code": None, "ended": utc_now(), "error": error})
        _say(error)
        return 1
```

with:

```python
def run_job(jdir, grace=CANCEL_GRACE_S):
    """Run one dispatched job to its end (MU22), with the VLM preflight before the child and the
    postflight after every end, both under jdir/lock (VLM lifecycle spec VR1). Returns 0 after a
    final status, 1 when the job argv could not be started or the VLM preflight failed, 3 when
    the status was not "starting" (MU24)."""
    lock_fd = os.open(os.path.join(jdir, "lock"), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    status = read_status(jdir) or {}
    if status.get("state") != "starting":
        _say("job is %s; nothing to run" % (status.get("state") or "unknown"))
        return 3
    state_root = os.path.dirname(os.path.dirname(jdir))
    cancel = os.path.join(jdir, "cancel")
    if os.path.exists(cancel):
        write_status(jdir, {"state": "cancelled", "exit_code": None, "ended": utc_now()})
        _say("cancelled before start")
        vlm_postflight(state_root)
        return 0
    job = read_job(jdir)
    if vlm_lifecycle_enabled():
        outcome, error = vlm_preflight(job, cancel)
        if outcome == "cancelled":
            write_status(jdir, {"state": "cancelled", "exit_code": None, "ended": utc_now()})
            _say("cancelled during the VLM preflight")
            vlm_postflight(state_root)
            return 0
        if outcome == "failed":
            write_status(jdir, {"state": "failed", "dispatched": status.get("dispatched"),
                                "runner_pid": os.getpid(), "pgid": None, "started": None,
                                "exit_code": None, "ended": utc_now(), "error": error})
            _say(error)
            vlm_postflight(state_root)
            return 1
    log = open(os.path.join(jdir, "log.txt"), "ab")
    try:
        # Default the VLM model id to "auto" so the character/story pipeline resolves the
        # single *loaded* model the story-server reports (mlx_vlm serves it by path on this
        # host, not under the author's "qwen38-6bit" alias). An explicit env still wins.
        # STORY_SERVER_ENGINE_SCAN=0 switches off an older release's host-wide EngineCore sweep
        # in this job's own bin/story-server stop, which could kill the 8178 embed server
        # (VLM lifecycle spec VR1, R4); the current bin/story-server ignores it.
        child = subprocess.Popen(
            job["argv"], cwd=job["workspace"],
            env=dict(os.environ, PYTHONUNBUFFERED="1",
                     QWEN_AGENT_VLM_MODEL=os.environ.get("QWEN_AGENT_VLM_MODEL") or "auto",
                     STORY_SERVER_ENGINE_SCAN="0"),
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True, close_fds=True)
    except OSError as e:
        error = "cannot start: %s" % (e.strerror or e)
        write_status(jdir, {"state": "failed", "dispatched": status.get("dispatched"),
                            "runner_pid": os.getpid(), "pgid": None, "started": None,
                            "exit_code": None, "ended": utc_now(), "error": error})
        _say(error)
        vlm_postflight(state_root)
        return 1
```

**3.2.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    write_status(jdir, final)
    _say("exit %d (%s)" % (code, state))
    return 0
```

with:

```python
    write_status(jdir, final)
    _say("exit %d (%s)" % (code, state))
    vlm_postflight(state_root)
    return 0
```

**3.3.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
            return "failed", ("VLM preflight failed: bin/story-server stop exited %d; the log above "
                              "shows why" % value)


# ---------------------------------------------------------------------------
# Liveness, the dispatcher, startup recovery and job actions (MU26, MU29-MU31, MU68).
```

with:

```python
            return "failed", ("VLM preflight failed: bin/story-server stop exited %d; the log above "
                              "shows why" % value)


def vlm_postflight(state):
    """After every job end, still holding jdir/lock (VR5): restore the VLM, without --wait, iff
    the queue is empty or the next job needs it. story-server-restore detaches the start under
    launchd and returns once the start holds the story-server lock (or after at most 10 s)."""
    if not vlm_lifecycle_enabled():
        return
    wanted, why = vlm_restore_wanted(state)
    if not wanted:
        _say("vlm: postflight: not restoring the VLM (%s)" % why)
        return
    _say("vlm: postflight: restoring the VLM in its own session (%s)" % why)
    argv = [os.path.join(vlm_tools_dir(), "story-server-restore"), VLM_MODE]
    _say("vlm: running: %s" % shlex.join(argv))
    try:
        rc = subprocess.run(argv, stdin=subprocess.DEVNULL, close_fds=True,
                            timeout=VLM_POSTFLIGHT_TIMEOUT_S).returncode
    except subprocess.TimeoutExpired:
        _say("vlm: postflight: bin/story-server-restore timed out after %d s" % VLM_POSTFLIGHT_TIMEOUT_S)
        return
    except OSError as e:
        _say("vlm: postflight: cannot run %s: %s" % (argv[0], e.strerror or e))
        return
    if rc != 0:
        _say("vlm: postflight: bin/story-server-restore exited %d" % rc)


# ---------------------------------------------------------------------------
# Liveness, the dispatcher, startup recovery and job actions (MU26, MU29-MU31, MU68).
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_vlm_lifecycle.py tests/test_movie_ui_jobs.py 2>&1 | tail -1
```

Expected: `45 passed` (about 40 seconds; every MUT10-MUT15 runner test in `test_movie_ui_jobs.py` passes unchanged, since the conftest keeps the lifecycle off). Then the compile check with `FILES` = `movie_ui_lib.py tests/test_vlm_lifecycle.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add movie_ui_lib.py tests/test_vlm_lifecycle.py
git diff --cached --name-only    # expected: qwen-agent-workspace/movie_ui_lib.py, qwen-agent-workspace/tests/test_vlm_lifecycle.py
git commit -m "feat(movie-ui): runner runs the VLM preflight before and the postflight after every job (VLM lifecycle VR1, VR5; VL17-VL21)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: movie_ui_lib: the one-shot startup restore

Implements VU2 (`_vlm_recheck`, `recovery_restore`, the `startup_recovery` and `dispatch_tick` hooks). Tests VL23 and Review Focus 2.

**Files:**
- Modify: `movie_ui_lib.py` (a new block before the "Liveness, the dispatcher" header, after `vlm_postflight`; `dispatch_tick` `:404-407`; `startup_recovery` `:435-447`)
- Modify: `tests/test_vlm_lifecycle.py` (append)

**Interfaces:**
- Consumes: Task 5's `vlm_lifecycle_enabled`, `vlm_restore_wanted`, `vlm_tools_dir(ui_ws)`, `VLM_MODE`, `VLM_RECOVERY`, `RESTORERS`.
- Produces (in `movie_ui_lib`): `_vlm_recheck(reason)` (appends to `VLM_RECOVERY` only while the lifecycle is on; called only by `startup_recovery`, with `"startup"`); `recovery_restore(state, ui_ws, reason) -> Popen or None` (stderr `movie-ui: VLM restore (<reason>): skipped (<why>)`, `movie-ui: VLM restore (<reason>): cannot start <path>: <strerror>` or `movie-ui: VLM restore (<reason>; <why>): started <argv> (pid <pid>)`); `dispatch_tick` drains `VLM_RECOVERY` into one `recovery_restore` after its active-job and orphan loops and before its queue loop. `movie_ui_server.main` already calls `startup_recovery` then starts the dispatcher, so no server change is needed (spec G4).

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_vl23_startup_restore_runs_once_at_the_first_idle_tick`, `test_vl23_startup_restore_waits_for_a_live_orphan`, `test_vl23_startup_restore_skipped_when_the_next_job_runs_without_it`, `test_vl23_lost_jobs_and_kill_orphan_queue_nothing`, `test_review_focus_2_startup_restore_waits_for_a_running_job`.

**1.1.** Append to `tests/test_vlm_lifecycle.py`:

```python
# --- VL23, Review Focus 2: the startup restore (VU2) -------------------------------------------

def test_vl23_startup_restore_runs_once_at_the_first_idle_tick(state, tmp_path, vlm, monkeypatch,
                                                                capsys):
    tools = make_fake_tools(tmp_path, MODEL)
    lifecycle_on(monkeypatch, tools, vlm.port)
    lib.startup_recovery(state)
    assert lib.VLM_RECOVERY == ["startup"]
    assert tool_calls(tools) == []
    assert lib.dispatch_tick(state, mt.WS) is None
    assert lib.VLM_RECOVERY == []
    assert len(lib.RESTORERS) == 1
    proc = lib.RESTORERS[0]
    assert proc.wait(timeout=30) == 0
    assert capsys.readouterr().err == ("movie-ui: VLM restore (startup; queue empty): started %s "
                                       "mlx-vision (pid %d)\n"
                                       % (os.path.join(tools, "story-server-restore"), proc.pid))
    row = tool_calls(tools)[0]
    assert row["argv"] == ["mlx-vision"] and row["sid"] != os.getsid(0)
    assert lib.dispatch_tick(state, mt.WS) is None
    assert call_names(tools) == ["restore"]


def test_vl23_startup_restore_waits_for_a_live_orphan(state, tmp_path, vlm, monkeypatch):
    tools = make_fake_tools(tmp_path, MODEL)
    lifecycle_on(monkeypatch, tools, vlm.port)
    orphan = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)
    try:
        mt.make_job(state, ["x"], str(tmp_path), kind="smoke",
                    status={"state": "lost", "pgid": orphan.pid, "exit_code": None, "ended": None,
                            "detected": lib.utc_now()})
        lib.startup_recovery(state)
        assert lib.VLM_RECOVERY == ["startup"]
        assert lib.dispatch_tick(state, mt.WS) is None
        assert lib.VLM_RECOVERY == ["startup"] and lib.RESTORERS == [] and tool_calls(tools) == []
    finally:
        orphan.kill()
        orphan.wait(timeout=10)
    assert lib.dispatch_tick(state, mt.WS) is None
    assert lib.VLM_RECOVERY == [] and len(lib.RESTORERS) == 1
    assert lib.RESTORERS[0].wait(timeout=30) == 0
    assert call_names(tools) == ["restore"]


def test_vl23_startup_restore_skipped_when_the_next_job_runs_without_it(state, tmp_path, vlm,
                                                                         monkeypatch, capsys):
    tools = make_fake_tools(tmp_path, MODEL)
    lifecycle_on(monkeypatch, tools, vlm.port)
    job_id = mt.make_job(state, ["x"], str(tmp_path), kind="smoke")
    assert lib.recovery_restore(state, mt.WS, "startup") is None
    assert capsys.readouterr().err == ("movie-ui: VLM restore (startup): skipped (next job %s runs "
                                       "without it)\n" % job_id)
    assert lib.RESTORERS == [] and tool_calls(tools) == []
    monkeypatch.setenv("MOVIE_UI_VLM_TOOLS", str(tmp_path / "missing-tools"))
    lib.write_queue(state, [])
    assert lib.recovery_restore(state, mt.WS, "startup") is None
    assert capsys.readouterr().err == ("movie-ui: VLM restore (startup): cannot start %s: No such "
                                       "file or directory\n"
                                       % os.path.join(str(tmp_path / "missing-tools"),
                                                      "story-server-restore"))


def test_vl23_lost_jobs_and_kill_orphan_queue_nothing(state, tmp_path, vlm, monkeypatch):
    tools = make_fake_tools(tmp_path, MODEL)
    lifecycle_on(monkeypatch, tools, vlm.port)
    stale = mt.make_job(state, ["x"], str(tmp_path), kind="smoke",
                        status={"state": "running", "dispatched": "2026-01-01T00:00:00Z",
                                "runner_pid": 1, "pgid": None, "started": "2026-01-01T00:00:00Z"})
    assert lib.job_alive(lib.job_dir(state, stale)) is False
    assert mt.status_of(state, stale)["state"] == "lost"
    orphan = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)
    try:
        lost = mt.make_job(state, ["x"], str(tmp_path), kind="smoke",
                           status={"state": "lost", "pgid": orphan.pid, "exit_code": None,
                                   "ended": None, "detected": lib.utc_now()})
        assert lib.kill_orphan(state, lost) == orphan.pid
        orphan.wait(timeout=10)
    finally:
        if orphan.poll() is None:
            orphan.kill()
            orphan.wait(timeout=10)
    assert lib.VLM_RECOVERY == []
    assert lib.dispatch_tick(state, mt.WS) is None
    assert lib.RESTORERS == [] and tool_calls(tools) == []


def test_review_focus_2_startup_restore_waits_for_a_running_job(state, tmp_path, vlm, monkeypatch):
    tools = make_fake_tools(tmp_path, MODEL)
    lifecycle_on(monkeypatch, tools, vlm.port)
    job_id = mt.make_job(state, ["x"], str(tmp_path), kind="smoke",
                         status={"state": "running", "dispatched": lib.utc_now(),
                                 "runner_pid": os.getpid(), "pgid": None, "started": lib.utc_now()})
    jdir = lib.job_dir(state, job_id)
    fd = os.open(os.path.join(jdir, "lock"), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)        # the detached runner that survived the restart
    try:
        lib.startup_recovery(state)
        assert mt.status_of(state, job_id)["state"] == "running"
        assert lib.VLM_RECOVERY == ["startup"]
        for _ in range(3):
            assert lib.dispatch_tick(state, mt.WS) is None
        assert lib.VLM_RECOVERY == ["startup"] and lib.RESTORERS == [] and tool_calls(tools) == []
        lib.write_status(jdir, dict(mt.status_of(state, job_id), state="done", exit_code=0,
                                    ended=lib.utc_now()))
    finally:
        os.close(fd)
    assert lib.dispatch_tick(state, mt.WS) is None
    assert lib.VLM_RECOVERY == [] and len(lib.RESTORERS) == 1
    assert lib.RESTORERS[0].wait(timeout=30) == 0
    assert call_names(tools) == ["restore"]
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_vlm_lifecycle.py -k "vl23 or review_focus_2" 2>&1 | tail -3
```

Expected: `4 failed, 1 passed, 28 deselected`. `test_vl23_lost_jobs_and_kill_orphan_queue_nothing` passes before and after (HEAD queues nothing either; it pins that the new hooks stay off those paths). The other four fail: `startup_recovery` queues nothing and `recovery_restore` does not exist.

- [ ] **Step 3: Implement.**

**3.1.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    if rc != 0:
        _say("vlm: postflight: bin/story-server-restore exited %d" % rc)


# ---------------------------------------------------------------------------
# Liveness, the dispatcher, startup recovery and job actions (MU26, MU29-MU31, MU68).
```

with:

```python
    if rc != 0:
        _say("vlm: postflight: bin/story-server-restore exited %d" % rc)


def _vlm_recheck(reason):
    """Queue one server-side VLM restore for the next idle dispatcher tick (VU2); called only by
    startup_recovery."""
    if vlm_lifecycle_enabled():
        VLM_RECOVERY.append(reason)


def recovery_restore(state, ui_ws, reason):
    """The server's restore after startup (VU2): when vlm_restore_wanted says so, start
    story-server-restore (no --wait) in its own session and return its Popen, never waiting under
    STORE_LOCK; else None. Every outcome is one line on the server's stderr."""
    if not vlm_lifecycle_enabled():
        return None
    wanted, why = vlm_restore_wanted(state)
    if not wanted:
        sys.stderr.write("movie-ui: VLM restore (%s): skipped (%s)\n" % (reason, why))
        return None
    argv = [os.path.join(vlm_tools_dir(ui_ws), "story-server-restore"), VLM_MODE]
    RESTORERS[:] = [p for p in RESTORERS if p.poll() is None]
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, start_new_session=True,
                                close_fds=True)
    except OSError as e:
        sys.stderr.write("movie-ui: VLM restore (%s): cannot start %s: %s\n"
                         % (reason, argv[0], e.strerror or e))
        return None
    RESTORERS.append(proc)
    sys.stderr.write("movie-ui: VLM restore (%s; %s): started %s (pid %d)\n"
                     % (reason, why, shlex.join(argv), proc.pid))
    return proc


# ---------------------------------------------------------------------------
# Liveness, the dispatcher, startup recovery and job actions (MU26, MU29-MU31, MU68).
```

**3.2.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
        if orphan_info(read_status(job_dir(state, job_id))) is not None:
            return None
    queue = read_queue(state)
```

with:

```python
        if orphan_info(read_status(job_dir(state, job_id))) is not None:
            return None
    if VLM_RECOVERY:
        reason = "; ".join(VLM_RECOVERY)
        del VLM_RECOVERY[:]
        recovery_restore(state, ui_ws, reason)
    queue = read_queue(state)
```

**3.3.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    """Rewrite queue.json without IDs that are malformed, duplicated, lack job.json or already
    have a status; then re-attach or mark lost every starting/running job (MU31)."""
```

with:

```python
    """Rewrite queue.json without IDs that are malformed, duplicated, lack job.json or already
    have a status; then re-attach or mark lost every starting/running job (MU31), and queue the
    startup VLM restore for the first idle dispatcher tick (VLM lifecycle spec VU2)."""
```

**3.4.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    write_queue(state, kept)
    for job_id in active_job_ids(state):
        job_alive(job_dir(state, job_id))
```

with:

```python
    write_queue(state, kept)
    for job_id in active_job_ids(state):
        job_alive(job_dir(state, job_id))
    _vlm_recheck("startup")
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_vlm_lifecycle.py tests/test_movie_ui_jobs.py tests/test_movie_ui_http.py 2>&1 | tail -1
```

Expected: `100 passed` (about 70 seconds). Then the compile check with `FILES` = `movie_ui_lib.py tests/test_vlm_lifecycle.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add movie_ui_lib.py tests/test_vlm_lifecycle.py
git diff --cached --name-only    # expected: qwen-agent-workspace/movie_ui_lib.py, qwen-agent-workspace/tests/test_vlm_lifecycle.py
git commit -m "feat(movie-ui): one-shot VLM restore at the first idle tick after startup (VLM lifecycle VU2; VL23)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: V2 "story server" becomes a warning at submit; the page drops its write-story gate

Implements VU1 (D7) and VU3. Tests VL25, VL26. `test_movie_ui_checks.py::test_mut9_v2_host_checks` and the capability tests of `test_movie_ui_http.py` must pass unchanged (spec 11.4: the lifecycle is off in the conftest).

**Files:**
- Modify: `movie_ui_lib.py` (`story_server_check` `:1078-1094`; `host_checks` `:1132`)
- Modify: `static/movie-ui/app.js` (`:464`)
- Modify: `static/movie-ui/app.css` (after `:47`)
- Modify: `tests/test_vlm_lifecycle.py` (append)

**Interfaces:**
- Consumes: Task 5's `vlm_lifecycle_enabled`; `run_light`, `STATE_LINE_RE`, `LIGHT_TIMEOUT`, `last_line`, `check`, `_from_pair` (existing).
- Produces (in `movie_ui_lib`): `story_server_probe(ws_real) -> ("serving", state) | ("down", state) | ("timeout", None) | ("error", text)`; `_story_server_pair(kind, value) -> (ok, detail)` (HEAD's four texts, byte for byte); `story_server_check(ws_real)` (unchanged results; the MU60 capability probe keeps calling it); `story_server_record(ws_real) -> check record` (`warn` W1/W2 while the lifecycle is on, else HEAD's `pass`/`fail`); `host_checks` uses `story_server_record`. A `warn` record does not fail `checks_pass`, so `POST /api/jobs` answers 201 with it in `"checks"`; the page shows it with class `check-warn`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_vl25_a_stopped_story_server_is_a_warning_while_the_lifecycle_is_on`, `test_vl26_page_gate_and_warn_style`.

**1.1.** Append to `tests/test_vlm_lifecycle.py`:

```python
# --- VL25, VL26: V2 at submit and the page (VU1, VU3) ------------------------------------------

W1 = ("story server is STOPPED; the job starts it when it reaches the front of the queue "
      "(a 5-14 min load)")
W2 = ("bin/story-server status timed out after 60 s; the job checks the story server and restarts "
      "it if needed when it reaches the front of the queue")


def test_vl25_a_stopped_story_server_is_a_warning_while_the_lifecycle_is_on(http_env, monkeypatch,
                                                                             tmp_path):
    s, ws = http_env["srv"], http_env["ws"]
    lifecycle_on(monkeypatch, make_fake_tools(tmp_path / "vlm", MODEL), 9)
    mt.stub_config(ws, {"story-server status": {
        "stdout": "story-server status  X\n  state:          STOPPED\n"}})
    warn = lib.check("V2", "story server", "warn", W1)
    assert lib.story_server_record(ws) == warn
    status, _h, payload = mt.api(s, "POST", "/api/jobs", body=mt.fields(ws))
    assert status == 201, payload
    assert warn in payload["checks"] and lib.checks_pass(payload["checks"])
    # The capability probe (MU60) keeps HEAD's pair.
    assert lib.story_server_check(ws) == (
        False, "story server is STOPPED; start it with bin/story-server mlx-vision")
    monkeypatch.setattr(lib, "LIGHT_TIMEOUT", 1)
    mt.stub_config(ws, {"story-server status": {"sleep": 3}})
    assert lib.story_server_record(ws) == lib.check("V2", "story server", "warn", W2)
    monkeypatch.setattr(lib, "LIGHT_TIMEOUT", 60)
    mt.stub_config(ws, {"story-server status": {
        "exit": 4, "stderr": "story-server: /usr/sbin/lsof is missing or not executable\n"}})
    fail = lib.check("V2", "story server", "fail", "bin/story-server status exited 4: story-server: "
                                                   "/usr/sbin/lsof is missing or not executable")
    assert lib.story_server_record(ws) == fail
    status, _h, payload = mt.api(s, "POST", "/api/jobs", body=mt.fields(ws))
    assert status == 409 and fail in payload["checks"]
    mt.stub_config(ws, {})
    assert lib.story_server_record(ws) == lib.check("V2", "story server", "pass",
                                                    "story server: SERVING vision")
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "0")
    mt.stub_config(ws, {"story-server status": {
        "stdout": "story-server status  X\n  state:          STOPPED\n"}})
    assert lib.story_server_record(ws) == lib.check(
        "V2", "story server", "fail", "story server is STOPPED; start it with bin/story-server mlx-vision")


def test_vl26_page_gate_and_warn_style():
    with open(os.path.join(mt.WS, "static", "movie-ui", "app.js"), encoding="utf-8") as f:
        js = f.read()
    assert 'gate($("#c-write-story"), $("#c-write-story-reason"), []);' in js
    assert '["story_server"]' not in js
    with open(os.path.join(mt.WS, "static", "movie-ui", "app.css"), encoding="utf-8") as f:
        css = f.read()
    assert ".check-warn { color: var(--warn); }\n" in css
    assert css.index(".check-skip, .check-running") < css.index(".check-warn")
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_vlm_lifecycle.py -k "vl25 or vl26" 2>&1 | tail -3
```

Expected: `2 failed, 33 deselected` (`AttributeError: ... 'story_server_record'`; `app.js` still gates on `["story_server"]`).

- [ ] **Step 3: Implement.**

**3.1.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
def story_server_check(ws_real):
    """(ok, detail) for V2 "story server": bin/story-server status (bash, run directly)."""
    run = run_light([os.path.join(ws_real, "bin", "story-server"), "status"], ws_real)
    if run["timed_out"]:
        return False, "bin/story-server status timed out after %d s" % LIGHT_TIMEOUT
    state = None
    for line in run["stdout"].splitlines():
        match = STATE_LINE_RE.match(line)
        if match:
            state = match.group(1)
            break
    if run["exit_code"] != 0 or state is None:
        code = "none" if run["exit_code"] is None else str(run["exit_code"])
        return False, "bin/story-server status exited %s: %s" % (code, last_line(run["stderr"]) or "-")
    if state.startswith("SERVING "):
        return True, "story server: %s" % state
    return False, "story server is %s; start it with bin/story-server mlx-vision" % state
```

with:

```python
def story_server_probe(ws_real):
    """bin/story-server status (bash, run directly) as ("serving", state), ("down", state),
    ("timeout", None) or ("error", "bin/story-server status exited <n|none>: <last stderr line
    or ->") (VLM lifecycle spec VU1)."""
    run = run_light([os.path.join(ws_real, "bin", "story-server"), "status"], ws_real)
    if run["timed_out"]:
        return "timeout", None
    state = None
    for line in run["stdout"].splitlines():
        match = STATE_LINE_RE.match(line)
        if match:
            state = match.group(1)
            break
    if run["exit_code"] != 0 or state is None:
        code = "none" if run["exit_code"] is None else str(run["exit_code"])
        return "error", "bin/story-server status exited %s: %s" % (code, last_line(run["stderr"]) or "-")
    if state.startswith("SERVING "):
        return "serving", state
    return "down", state


def _story_server_pair(kind, value):
    """The (ok, detail) of one story_server_probe result, as V2 reported it before the VLM
    lifecycle."""
    if kind == "serving":
        return True, "story server: %s" % value
    if kind == "down":
        return False, "story server is %s; start it with bin/story-server mlx-vision" % value
    if kind == "timeout":
        return False, "bin/story-server status timed out after %d s" % LIGHT_TIMEOUT
    return False, value


def story_server_check(ws_real):
    """(ok, detail) for the MU60 capability probe: bin/story-server status (bash, run directly)."""
    return _story_server_pair(*story_server_probe(ws_real))


def story_server_record(ws_real):
    """V2's "story server" record. While the VLM lifecycle is on, a stopped server or a status
    timeout is a warn (the job's preflight starts or checks it at dispatch, VU1); otherwise, and
    for an error, the record is pass or fail as before."""
    kind, value = story_server_probe(ws_real)
    if vlm_lifecycle_enabled() and kind == "down":
        return check("V2", "story server", "warn", "story server is %s; the job starts it when it "
                     "reaches the front of the queue (a 5-14 min load)" % value)
    if vlm_lifecycle_enabled() and kind == "timeout":
        return check("V2", "story server", "warn", "bin/story-server status timed out after 60 s; "
                     "the job checks the story server and restarts it if needed when it reaches "
                     "the front of the queue")
    return _from_pair("V2", "story server", _story_server_pair(kind, value))
```

**3.2.** Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
           _from_pair("V2", "story server", story_server_check(ws_real)) if story_needed(fields, ws_real)
```

with:

```python
           story_server_record(ws_real) if story_needed(fields, ws_real)
```

**3.3.** Edit `static/movie-ui/app.js`: replace this text, which occurs exactly once:

```javascript
    gate($("#c-write-story"), $("#c-write-story-reason"), ["story_server"]);
```

with:

```javascript
    gate($("#c-write-story"), $("#c-write-story-reason"), []);
```

**3.4.** Edit `static/movie-ui/app.css`: replace this text, which occurs exactly once:

```css
.check-skip, .check-running { color: var(--muted); }
```

with:

```css
.check-skip, .check-running { color: var(--muted); }
.check-warn { color: var(--warn); }
```

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_vlm_lifecycle.py tests/test_movie_ui_checks.py tests/test_movie_ui_http.py 2>&1 | tail -1
```

Expected: `99 passed` (about 65 seconds; `test_mut9_v2_host_checks` and the MUT9 capability test pass unchanged). Then the compile check with `FILES` = `movie_ui_lib.py tests/test_vlm_lifecycle.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add movie_ui_lib.py static/movie-ui/app.js static/movie-ui/app.css tests/test_vlm_lifecycle.py
git diff --cached --name-only    # expected: the four paths above, each prefixed qwen-agent-workspace/
git commit -m "feat(movie-ui): a stopped story server is a submit-time warning; the page drops its write-story gate (VLM lifecycle VU1, VU3; VL25, VL26)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: The escape hatch, pinned across every gate; the compile and syntax guards

Implements the 2.5/13(d) rollback contract (`MOVIE_UI_VLM_LIFECYCLE=0` disables VR2, VR5, VU1's warn and VU2, and nothing else) and VK7's in-suite guard. Tests VL24, VL27. No production code: each gate landed with its own function (Tasks 8, 9, 10); this task pins all four together through the real runner, the dispatcher, the startup hook and V2, which no earlier test does, so the tests pass when written.

**Files:**
- Modify: `tests/test_vlm_lifecycle.py` (append)

**Interfaces:**
- Consumes: `run_job` via `bin/movie-ui-job` (Task 8), `vlm_postflight` (Task 8), `startup_recovery`, `dispatch_tick`, `recovery_restore` (Task 9), `host_checks` and `story_server_record` (Task 10); F-TOOLS (Task 6).
- Produces: nothing new.

- [ ] **Step 1: Write the tests.**

New tests in this task: `test_vl24_the_lifecycle_switched_off`, `test_vl27_changed_python_files_compile` (two parameters), `test_vl27_story_server_bash_syntax`.

**1.1.** Append to `tests/test_vlm_lifecycle.py`:

```python
# --- VL24, VL27: the escape hatch and the compile guards (2.5, 13(d), VK7) ---------------------

def test_vl24_the_lifecycle_switched_off(state, tmp_path, vlm, monkeypatch, capsys):
    tools = make_fake_tools(tmp_path, MODEL)
    lifecycle_on(monkeypatch, tools, vlm.port)
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "0")
    ws = mt.make_stub_workspace(tmp_path)
    job_id = mt.make_job(state, mt.py_argv("print('child')"), ws, kind="story")
    assert mt.dispatch(state, job_id).wait(timeout=60) == 0
    assert mt.status_of(state, job_id)["state"] == "done"
    assert "[movie-ui] vlm:" not in mt.read_log(state, job_id)
    lib.vlm_postflight(state)
    lib.startup_recovery(state)
    assert lib.VLM_RECOVERY == []
    assert lib.dispatch_tick(state, mt.WS) is None
    assert lib.recovery_restore(state, mt.WS, "startup") is None
    assert lib.RESTORERS == [] and tool_calls(tools, include_status=True) == []
    mt.stub_config(ws, {"story-server status": {"stdout": "  state:          STOPPED\n"}})
    assert lib.host_checks(mt.fields(ws), ws)[2] == lib.check(
        "V2", "story server", "fail", "story server is STOPPED; start it with bin/story-server mlx-vision")
    captured = capsys.readouterr()
    assert "vlm:" not in captured.out and "VLM restore" not in captured.err


@pytest.mark.parametrize("python", ["/usr/bin/python3", sys.executable])
def test_vl27_changed_python_files_compile(python, tmp_path):
    if not os.path.isfile(python):
        pytest.skip("%s is not installed" % python)
    paths = [os.path.join(mt.WS, rel) for rel in ("bin/story-server-restore", "character_dataset.py",
                                                  "movie_ui_lib.py", "tests/test_vlm_lifecycle.py")]
    proc = subprocess.run([python, "-m", "py_compile"] + paths, capture_output=True, text=True,
                          timeout=120, env=dict(os.environ, PYTHONPYCACHEPREFIX=str(tmp_path)))
    assert proc.returncode == 0, proc.stderr


def test_vl27_story_server_bash_syntax():
    for bash in ("/bin/bash", "bash"):
        proc = subprocess.run([bash, "-n", os.path.join(mt.WS, "bin", "story-server")],
                              capture_output=True, text=True, timeout=30)
        assert proc.returncode == 0, (bash, proc.stderr)
```

- [ ] **Step 2: Run the tests.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_vlm_lifecycle.py -k "vl24 or vl27" 2>&1 | tail -1
```

Expected: `4 passed, 35 deselected`. If `test_vl24_the_lifecycle_switched_off` fails, the failing assertion names the gate that leaks (a `[movie-ui] vlm:` line from the runner, a tool call, `VLM_RECOVERY` non-empty, or a V2 `warn`); fix that gate in its own function (Tasks 8, 9, 10), never in this test.

- [ ] **Step 3: No implementation.** This task changes no production file (see the task header).

- [ ] **Step 4: Run the whole file and compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_vlm_lifecycle.py 2>&1 | tail -1
```

Expected: `39 passed` (about 35 seconds). Then the compile check with `FILES` = `tests/test_vlm_lifecycle.py`; expected `compiled 1` twice.

- [ ] **Step 5: Commit.**

```bash
git add tests/test_vlm_lifecycle.py
git diff --cached --name-only    # expected: qwen-agent-workspace/tests/test_vlm_lifecycle.py
git commit -m "test(movie-ui): pin the MOVIE_UI_VLM_LIFECYCLE=0 escape hatch and the compile guards (VLM lifecycle VL24, VL27)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: End to end: a server a job starts survives the job's cancel and its orphan kill

Pins VK2 and VR6 (`cancel_tree` and `kill_orphan` stay as at HEAD) with the real `bin/story-server-restore` inside a real runner. Test VL22. No production code: the double fork that makes VK2 hold landed in Task 3 (VLR1 is its failing test); this task proves it through movie-ui's own cancel and orphan paths, so the test passes when written.

**Files:**
- Modify: `tests/test_vlm_lifecycle.py` (append)

**Interfaces:**
- Consumes: Task 3's `bin/story-server-restore` (`STORY_SERVER_RESTORE_BIN`, `HOME` from `mt.set_home`); `mt.dispatch`, `mt.cancel_marker`, `lib.job_alive`, `lib.kill_orphan`, `lib.group_alive` (existing).
- Produces: nothing new.

- [ ] **Step 1: Write the test.**

New test in this task: `test_vl22_cancel_and_kill_orphan_never_reach_a_started_server`.

**1.1.** Append to `tests/test_vlm_lifecycle.py`:

```python
# --- VL22: VK2 end to end through the real story-server-restore (VRS3, VR6) --------------------

# An F-SS variant (spec 11.2): its mode call takes the "lock", starts a `sleep 60` standing in for
# the loading server (pid in <dir>/sleeper.pid), and exits after 3 s.
FSS_SPAWN = """#!/bin/bash
T='%s'
case "$1" in
    status)
        if [ -e "$T/started" ]; then echo '  state:          SERVING mlx-vision'
        else echo '  state:          STOPPED'; fi
        exit 0 ;;
    lockinfo)
        if [ -e "$T/lockinfo" ]; then cat "$T/lockinfo"; else echo 'lock: free path=x'; fi
        exit 0 ;;
esac
echo "lock: held pid=$$ cmd=$1 since=x path=x" > "$T/lockinfo"
/bin/sleep 60 &
echo $! > "$T/sleeper.pid.tmp" && mv "$T/sleeper.pid.tmp" "$T/sleeper.pid"
sleep 3
touch "$T/started"
echo 'lock: free path=x' > "$T/lockinfo"
"""


def _restore_job(state, tmp_path, name, monkeypatch):
    fss = tmp_path / name
    fss.mkdir()
    script = fss / "story-server"
    script.write_text(FSS_SPAWN % fss)
    script.chmod(0o755)
    monkeypatch.setenv("STORY_SERVER_RESTORE_BIN", str(script))
    restore = os.path.join(mt.WS, "bin", "story-server-restore")
    argv = mt.py_argv("import subprocess, sys\n"
                      "sys.exit(subprocess.call([sys.executable, %r, 'mlx-vision', '--wait']))\n"
                      % restore)
    job_id = mt.make_job(state, argv, str(tmp_path), kind="download")
    runner = mt.dispatch(state, job_id)
    pid_file = fss / "sleeper.pid"
    mt.wait_until(pid_file.exists, 20)
    return job_id, runner, int(pid_file.read_text())


def test_vl22_cancel_and_kill_orphan_never_reach_a_started_server(state, tmp_path, monkeypatch):
    sleepers = []
    try:
        job_id, _runner, sleeper = _restore_job(state, tmp_path, "cancelled", monkeypatch)
        sleepers.append(sleeper)
        time.sleep(1.0)
        mt.cancel_marker(state, job_id)
        status = _final(state, job_id)
        assert status["state"] == "cancelled"
        line = [l for l in mt.read_log(state, job_id).splitlines()
                if l.startswith("[movie-ui] cancel: SIGTERM to process group(s) ")][0]
        groups = [int(g) for g in line.split("group(s) ", 1)[1].split()]
        assert status["pgid"] in groups
        assert mt.pid_alive(sleeper)
        assert os.getpgid(sleeper) not in groups and os.getsid(sleeper) not in groups

        job_id, runner, sleeper = _restore_job(state, tmp_path, "orphaned", monkeypatch)
        sleepers.append(sleeper)
        mt.wait_until(lambda: mt.status_of(state, job_id).get("state") == "running", 10)
        os.killpg(runner.pid, signal.SIGKILL)
        runner.wait(timeout=10)
        assert lib.job_alive(lib.job_dir(state, job_id)) is False
        status = mt.status_of(state, job_id)
        assert status["state"] == "lost"
        assert lib.kill_orphan(state, job_id) == status["pgid"]
        mt.wait_until(lambda: not lib.group_alive(status["pgid"]), 10)
        assert mt.pid_alive(sleeper)
    finally:
        for pid in sleepers:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except OSError:
                pass
```

- [ ] **Step 2: Run the test.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_vlm_lifecycle.py -k vl22 2>&1 | tail -1
```

Expected: `1 passed, 39 deselected` (about 8 seconds). A failure on `mt.pid_alive(sleeper)` or on the group assertion means the restore no longer double-forks (Task 3, VRS3) or `cancel_tree`/`kill_orphan` changed (they must stay as at HEAD, VR6); fix the code, never this test.

- [ ] **Step 3: No implementation.** This task changes no production file (see the task header).

- [ ] **Step 4: Run the movie-ui, restore and story-server files together; compile.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_vlm_lifecycle.py tests/test_clean_stop.py tests/test_movie_ui_jobs.py 2>&1 | tail -1
```

Expected: `74 passed, 1 warning` (about 85 seconds). Then the compile check with `FILES` = `tests/test_vlm_lifecycle.py`; expected `compiled 1` twice.

- [ ] **Step 5: Commit.**

```bash
git add tests/test_vlm_lifecycle.py
git diff --cached --name-only    # expected: qwen-agent-workspace/tests/test_vlm_lifecycle.py
git commit -m "test(movie-ui): a VLM start a job launched survives the job's cancel and orphan kill (VLM lifecycle VK2; VL22)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Design review, the test_mut26 re-baseline (test-only commit), VK6 and VK7

Implements spec 13 steps 4-5 (the review and G10), and measures VK6 and VK7. It hands VK8 (the live macstudio protocol, 13 step 6) to the user. No production code changes in this task.

**Files:**
- Modify: `tests/test_movie_ui_builder.py` (`test_mut26_pipeline_files_are_unchanged` `:273-275`: spec 11.4 "`BASELINE` set to the last feature commit SHA, comment appended ', then to <sha> (VLM lifecycle: character_dataset.py restores via story-server-restore --wait)'")

**Interfaces:**
- Consumes: every earlier task's commit.
- Produces: the final pass counts in `/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-25-vlm-lifecycle/final-pytest.txt`.

- [ ] **Step 1: Design review (controller; spec 13 step 4).** Ask an Opus `design-reviewer` to review `git diff 168b2e8..HEAD -- qwen-agent-workspace` against the spec and this plan. Fix every finding in a new commit on the owning task's files before Step 2, then re-run that task's Step 4.

- [ ] **Step 2: Re-baseline test_mut26 to the last pipeline commit.**

```bash
SHA=$(git log -1 --format=%H -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py)
echo "$SHA"
python3 - "$SHA" <<'EOF'
import sys
sha = sys.argv[1]
path = "tests/test_movie_ui_builder.py"
with open(path, encoding="utf-8") as f:
    text = f.read()
old_comment = ("    # 1f5aa2c36cefe38567d76230c9e3e342c8f14869 (on-camera dialogue). This invariant holds "
               "from the new baseline.\n")
new_comment = ("    # 1f5aa2c36cefe38567d76230c9e3e342c8f14869 (on-camera dialogue), then to\n"
               "    # %s (VLM lifecycle: character_dataset.py restores via\n"
               "    # story-server-restore --wait). This invariant holds from the new baseline.\n" % sha)
old_base = '    BASELINE = "1f5aa2c36cefe38567d76230c9e3e342c8f14869"\n'
assert text.count(old_comment) == 1 and text.count(old_base) == 1
text = text.replace(old_comment, new_comment).replace(old_base, '    BASELINE = "%s"\n' % sha)
with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("re-based to", sha)
EOF
python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py -k mut26 2>&1 | tail -1
```

Expected: the SHA is Task 4's commit (the last one that touched a `PIPELINE_FILES` entry; `character_dataset.py` is the only such file this plan changes), or the Step 1 fix commit if that touched `character_dataset.py`; then `re-based to <that SHA>`; then `1 passed, 11 deselected`.

- [ ] **Step 3: Commit (test-only; spec 13 step 5).**

```bash
git add tests/test_movie_ui_builder.py
git diff --cached --name-only    # expected: only qwen-agent-workspace/tests/test_movie_ui_builder.py
git commit -m "test: re-baseline test_mut26 to the VLM lifecycle pipeline commit" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4: VK6, the full suite against the baseline (about 12 minutes).**

```bash
D=/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-25-vlm-lifecycle
python3 -m pytest tests/ -q -rA -p no:cacheprovider > $D/final-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt; tail -1 $D/final-pytest.txt
grep -E '^(FAILED|ERROR)' $D/final-pytest.txt
python3 tests/test_ltx_movie_offline.py 2>&1 | tail -1
diff <(grep -E '^PASSED' $D/baseline-pytest.txt | sort) <(grep -E '^PASSED' $D/final-pytest.txt | sort) | grep '^<' || echo "no lost pass"
```

Expected: the `FAILED` lines are exactly `test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `test_story_engine.py::test_rst62_import_sets` (`test_s14_source_guards` passes since Task 2). The passed count is the baseline's plus 1 for `test_s14`, plus every new test: 13 VLS, 10 in `test_clean_stop.py` (VLR1-VLR9 and Review Focus 3), 3 VLC1, and 40 collected in `tests/test_vlm_lifecycle.py`. That adds 67 to the baseline's passed count. The offline script prints `OK n/n` with the baseline `n`. The last command prints `no lost pass` (no test is renamed). Any other difference: stop and report.

- [ ] **Step 5: VK7.**

```bash
for py in /usr/bin/python3 python3; do $py -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' bin/story-server-restore character_dataset.py movie_ui_lib.py tests/conftest.py tests/test_vlm_lifecycle.py tests/test_story_server.py tests/test_clean_stop.py tests/test_character_tool.py tests/test_movie_ui_jobs.py tests/test_movie_ui_builder.py; done
/bin/bash -n bin/story-server && bash -n bin/story-server && echo "syntax ok"
grep -nE 'mapfile|declare -A|local -A|\$\{[A-Za-z_]+,,\}|\|&|;&|&>>' bin/story-server || echo "no bash-4 features"
```

Expected: `compiled 10` twice, `syntax ok`, `no bash-4 features`. `/bin/bash` 3.2 already ran every VLS test in Step 4, because `bin/story-server`'s shebang is `#!/bin/bash`.

- [ ] **Step 6: Hand-off of VK8 (the user, on macstudio; not an executor step).** The live protocol of spec 13 step 6:
  - (a) record the PID listening on 8178 (`/usr/sbin/lsof -nP -iTCP:8178 -sTCP:LISTEN -t`);
  - (b) run the five scenarios: a movie job without story.md, then a story job; a character create cancelled during the generate-to-score restore; two concurrent `bin/story-server-restore mlx-vision`; movie-ui stopped, `bin/story-server stop`, movie-ui started; two queued renders;
  - (c) confirm the 8178 PID is unchanged;
  - (d) the runtime rollback: `MOVIE_UI_VLM_LIFECYCLE=0` in movie-ui's environment, then `bin/movie-ui-stop` and `bin/movie-ui-start`.

---

## Coverage

### Spec section to task

| Spec | Task(s) |
|---|---|
| 0.3 G1 (`bin/story-server`) | 1 (VS1 lock constants, VS2-VS5, VS7-VS9), 2 (VS1 `ENGINE_SCAN` deletion, VS6, VS10) |
| 0.3 G2 (`bin/story-server-restore`) | 3 |
| 0.3 G3 (`movie_ui_lib.py`) | 5 (VP1-VP4, 2.5), 6 (VR4, VU4), 7 (VR2, VR3), 8 (VR1, VR5), 9 (VU2), 10 (VU1) |
| 0.3 G4 (`movie_ui_server.py`: no change) | 5 (`create_job` sets `vlm`), 9 (`main` already calls `startup_recovery`) |
| 0.3 G5 (`app.js`, `app.css`) | 10 |
| 0.3 G6 (`character_dataset.py`) | 4 |
| 0.3 G7 (`tests/conftest.py`) | 5 |
| 0.3 G8 (`tests/test_vlm_lifecycle.py`) | 5-12 |
| 0.3 G9 (VLS, VLR, VLC and the 11.4 edits) | 1, 2, 3, 4 |
| 0.3 G10 (`test_mut26`) | 13 |
| 1.4 one job end to end | 8 (steps 3-8), 12 (step 5's cancel) |
| 2.1 `job.json` `vlm` | 5 |
| 2.2 status rows | 8 |
| 2.3, 2.4 lock file and `lockinfo` | 1 |
| 2.5 environment and constants | 1 (`STORY_SERVER_LOCK_TIMEOUT`), 3 (`STORY_SERVER_RESTORE_WAIT_S`), 5 (the `movie_ui_lib` constants and `MOVIE_UI_VLM_*`) |
| VP1-VP4 | 5 |
| VR1 | 8 (the helpers `vlm_lifecycle_enabled`, `vlm_tools_dir`, `vlm_port`: 5) |
| VR2, VR3 | 7 |
| VR4 | 6 |
| VR5 | 8 |
| VR6 | 12 (pinned) |
| VU1 | 10 |
| VU2 | 9 |
| VU3 | 10 |
| VU4 | 6 |
| VS1-VS5, VS7-VS9 | 1 |
| VS6, VS10 | 2 |
| VRS1-VRS5 | 3 |
| VC1 | 4 |
| 10 strings | 7 (preflight lines, errors), 8 (postflight lines), 6 (H1-H9), 10 (W1, W2), 9 (server stderr) |
| 11.1 isolation | 5 |
| 11.2 fakes | 6 (F-TOOLS, F-HTTP), 3 (F-SS) |
| 11.4 edits | 1 (S1, S4/S5), 2 (S14, `_base_env`), 3 (F-SS, CS6), 4 (`_Fakes`, K9, K13, K20), 5 (`test_store_writes...`), 6 (MUT25), 13 (MUT26) |
| 12 amendments | the tasks that implement each amended item, as above |
| 13 rollout | Before Task 1 (step 1), 13 (steps 4-6) |
| VK1 | 7 (VL9-VL14), 8 (VL17) |
| VK2 | 3 (VLR1), 12 (VL22) |
| VK3 | 1 (VLS3), 3 (VLR8) |
| VK4 | 8 (VL21) |
| VK5 | 2 (VLS8, VLS9) |
| VK6, VK7 | 13 (VK7 also in 11 as VL27) |
| VK8 | 13 step 6 (hand-off) |

### Test IDs and their owning task (each is owned by exactly one task)

| IDs | Task |
|---|---|
| VLS1, VLS2, VLS3, VLS4, VLS5, VLS6, VLS7, VLS10, VLS12; S1, S4/S5 edits; S18 rewrite | 1 |
| VLS8, VLS9, VLS11, VLS13; S14, `_base_env` edits | 2 |
| VLR1-VLR9; F-SS, CS6 edits; Review Focus 3 | 3 |
| VLC1; `_Fakes`, K9, K13, K20 edits | 4 |
| VL1, VL2, VL3 (`effective_vlm`), VL4, VL5; constants and isolation tests; `test_store_writes...` edit | 5 |
| VL6, VL7, VL8; MUT25 edit; Review Focus 4 | 6 |
| VL3 (the preflight line), VL9-VL16, VL28; Review Focus 5 | 7 |
| VL17-VL21; Review Focus 1 | 8 |
| VL23; Review Focus 2 | 9 |
| VL25, VL26 | 10 |
| VL24, VL27 | 11 |
| VL22 | 12 |
| MUT26 re-baseline, VK6, VK7, VK8 hand-off | 13 |

## Plan decisions (where the spec is silent, or a test it specifies cannot be written as stated on this host)

1. **`test_s18_stop_text_before_bind_via_serve_cmd_pids` is rewritten (Task 1).** The spec lists S18 among the tests that "must pass unchanged" (11.4). Replayed, HEAD's S18 fails against the lock: its loader is owned by a running `story-server text`, so the test's `stop` preempts it (VS2, M30). The start's trap kills the loader, and the stop then prints `nothing to stop`, not M24; the start prints `interrupted during load`, not M18. The rewrite starts the MTPLX stub by hand, the hand-started case `serve_cmd_pids` exists for, so no story-server holds the lock. It keeps S18's purpose: the mode file is absent, the port is unbound, and only `serve_cmd_pids` finds the loader. It reaps the loader on a thread, because `kill_set`'s `kill -0` would see an unreaped child of the test as alive for 70 s. See Question 1.
2. **F-SS (Task 3) records the session id with `os.getsid(0)`, not `ps -o sess=`.** On macOS `ps -o sess=` prints `0` for every process, so the spec's line would make VLR1's sid check vacuous. F-SS also strips `ps`'s padding (`tr -d ' '`; HEAD's CS4 compared `pgid=` against a padded value and could not fail) and appends `pid=$$`. It gains a `serve` knob, because VLR2's "1 when the fake never serves" needs a fake that never touches `started`. CS6 parses the pgid up to the next word. CS4 stays byte-identical.
3. **VLR1 checks the start's live ppid after the restore returns** (`ps -o ppid= -p <pid>` is `1`). The fake's own ppid snapshot, its first action, can race the launcher's exit. `launch()` waits for the launcher, so by the time the restore returns the parent is launchd for certain.
4. **The `VLLM::EngineCore` stand-ins (VLS8, VLS9) are `/bin/bash -c 'exec -a VLLM::EngineCore /bin/sleep 60'`.** The spec's `Popen(["VLLM::EngineCore", ...], executable=sys.executable)` shows up in `ps` as `.../Python.app/Contents/MacOS/Python -c ...` with the framework Python, which replaces argv[0]. So it would match neither M31's awk nor the old sweep. This was replayed and confirmed.
5. **VLS8's loader is a test stub whose child is reachable only through the process tree.** The child neither listens on the port nor carries a serve argv. The spec's "the stub vllm launches /usr/bin/python3 as a child" would not exercise `tree_pids`: that child is the port listener, which `port_pids` already finds. The loader is started by hand with a hand-written mode file, so the test exercises `cmd_stop`'s tree and not `on_interrupt`'s. `on_interrupt`'s tree is covered by VLS4 and S4/S5 through the preemption.
6. **VLS6's lock record names a live `/bin/sleep` pid**, not the test's own pid. Its command line certainly lacks `story-server`. A pytest command line can contain that text, and the lock path itself (`story-server.lock`) does, so no helper passes the path in argv.
7. **VLS10 asserts that the start has spawned nothing while the stop holder holds the lock** (no mode file after 2 s). Replayed, a duration-only check passed at HEAD, because a start with warm-up takes about 2 s anyway.
8. **H4 for a parseable `/v1/models` reply without a list `data` is `invalid JSON`.** The spec's H4 lists only `HTTP <n>`, `invalid JSON` and the exception class name. `_vlm_request` treats `ValueError` (which includes `UnicodeDecodeError`) and `RecursionError` as `invalid JSON`, so a non-UTF-8 reply cannot kill the runner (Review Focus 4).
9. **"An exception returns None" / "Any exception" (VRS2, VRS3)** are read as `(OSError, ValueError, subprocess.SubprocessError)`. That covers a missing tool, a timeout and undecodable output. `launch()`'s `os.makedirs` sits inside that `try`, so an unwritable `~/.local/share` prints the VRS3 error instead of a traceback.
10. **`bin/story-server-restore`'s first docstring paragraph also changes.** Its sentence "with --wait it waits for the start to finish and returns its exit code" is false under VRS4, so it now says "with --wait it waits as described below". Everything else in that paragraph is unchanged, and the second paragraph is the VRS5 text.
11. **One commit per task**, instead of spec 13's commits A, B and C, to match the controller's task sizing. `test_mut26` is re-based in its own test-only commit to the last commit that touches a `PIPELINE_FILES` entry (Task 4's), after the 13-step-4 design review (Task 13).
12. **The conftest isolation lands in Task 5**, with the first lifecycle switch, so every later task's tests run isolated from the start.
13. **VL2 submits through HTTP every kind this host can validate.** That is story, regenerate, movie with and without story.md (`no_stills` mode), smoke, character create/regenerate/train, action train and download. `redo` needs the stills stack (V2) and `action-create` needs real clips, so those two go through `create_job` directly. Every route reaches the same `create_job`.
14. **VL3 is split**: `effective_vlm` in Task 5, the preflight's `job.json says` line in Task 7.
15. **F-HTTP has two additions**: a list `completion_status` is consumed one value per request, with the last value repeating (VL10's unhealthy-then-healthy), and there is a `models_raw` byte override (VL7's invalid JSON, Review Focus 4). F-TOOLS' `story-server` exits 0 for any argument the spec does not name. `call_names` leaves out `status` calls unless asked, so the spec's call lists (`[restore --wait, stop, restore --wait]`) read as written, and the tests that must show the status calls (VL9, VL12, VL28) ask for them.
16. **VL28's call lists include `_vlm_other_mode`'s one `status`**, which the spec mentions ("plus one status") for the vision/text case. The FOREIGN case asserts `[restore --wait, stop, restore --wait]` without status calls.
17. **VL21 checks ordering with `t >= parse_utc(ended)`** (`ended` has 1 s resolution) plus the log order `exit 0 (done)` before `postflight: restoring`.
18. **VL23 is four tests** (once at the first idle tick; deferred by a live orphan; skipped when the next job runs without it, plus the `cannot start` line; `lost` and `kill_orphan` queue nothing). The "skipped" case calls `recovery_restore` directly, so no runner is dispatched.
19. **VL22 and VL24 pass when written.** Each pins behaviour whose failing test belongs to an earlier task (VLR1; the gates of VL17, VL20, VL23, VL25). Tasks 11 and 12 say so in their headers.
20. **W2 keeps the spec's literal `60 s`**, even though the probe's limit is `LIGHT_TIMEOUT` (60 at HEAD; VL25 lowers it to 1 to trigger the timeout).
21. **`tests/test_clean_stop.py` imports `test_story_server` as `tss`** for VLR8's real-story-server stubs (`_base_env`, `_pgrep`, `_free_port`). Importing the module does not register its autouse fixture for `test_clean_stop.py`.
22. **Left unchanged, spec silent:** `scripts/deploy/install_pkg.py`'s `STORY_SERVER_USAGE` (`usage: story-server [vision|text|status|stop]`) is already stale at HEAD, because it lacks `mlx-vision`. Its tests use fakes, and this plan does not touch it.

## Questions for controller

1. **S18 (spec gap; resolved provisionally by Plan decision 1).** Spec 11.4 says S15-S23 "must pass unchanged". Replayed at Task 1, HEAD's `test_s18_stop_text_before_bind_via_serve_cmd_pids` fails under the spec's own stop-preempts-start rule (VS2): `stopped pid(s)` is absent and the start prints `interrupted during load`, not `FAILED`. The plan rewrites S18 to a hand-started loader, which keeps its `serve_cmd_pids` purpose. The alternative is to keep the story-server-owned loader and assert the preemption, as the spec does for S5. Please confirm the rewrite, or rule the alternative and amend 11.4 to list S18.

No other point blocks the plan.

## Execution handoff

Plan complete and saved to `qwen-agent-workspace/docs/superpowers/plans/2026-10-25-vlm-lifecycle.md`. Every Create/Append/Edit block was replayed in order against a scratch copy of the `168b2e8` tree. Each old text occurred exactly once at its turn, each task's Step 2 run failed or passed as its "Expected" line says, and each task's Step 4 test run passed. `bin/story-server` passed `/bin/bash -n`, and every changed Python file compiled under Python 3.9.6 and 3.13. The full suite was not run; it is Task 13 Step 4. Please review the plan. Which execution approach would you prefer?

- **Subagent-driven**: a fresh subagent implements each task and a fresh reviewer checks it before the next one starts, then a whole-branch review at the end.
- **Native**: one session implements every task, then one fresh reviewer checks the whole branch.

For this plan I recommend **subagent-driven**. Its 13 tasks hand exact interfaces forward (the lock line Task 3 parses, the restore exit codes Tasks 4 and 7 rely on, the `movie_ui_lib` section that Tasks 5-10 grow in place). A mistake that ships would kill the 8178 embed server or OOM the host with two 22-34 GB loads.
