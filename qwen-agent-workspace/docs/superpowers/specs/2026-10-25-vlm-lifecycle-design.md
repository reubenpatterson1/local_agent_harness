# VLM lifecycle at job boundaries

Date: 2026-10-25 (rev 2: design-review fixes, Section 16)

Status: design spec. One binding user decision (Section 0.1). Every value the decision left open is marked **[spec choice]**, and Section 14 collects them. The implementer makes no design decisions.

Repository: `/Users/reubenpatterson/local_agent_harness`, branch `qwen-agent-redteam`. `WS` is `qwen-agent-workspace/`. Every relative path is relative to `WS`. Line numbers cite the code at `eeb8b5f`, and each citation was checked there. HEAD `642e5b0` adds only this spec file, so the code is identical.

Specs this one builds on, cited by tag:
- **[MOVIEUI]** `docs/superpowers/specs/2026-10-19-movie-ui-design.md` (MU1-MU85, V1-V7, GC1-GC10). Section 12 lists the amendments this spec makes to it, MU60 among them.
- **[CLEANSTOP]** `docs/superpowers/specs/2026-10-21-clean-stop-design.md` (S1-S8).
- **[SSPLAN]** `docs/superpowers/plans/2026-09-17-story-server-lifecycle-plan.md` (story-server D2, D9, R1, R3, R8).

---

## 0. Purpose and scope

### 0.1 Purpose and binding decision

The story/vision LLM ("the VLM": `bin/story-server mlx-vision`, `python -m mlx_vlm.server` on 127.0.0.1:8177, 22-34 GB resident) is stopped by some pipeline phases and never reliably brought back. When a server is brought back, a job cancel can kill it. Nothing serializes starts, so two servers can load at once and run the host out of memory. The six failure modes are F1-F6 (Section 0.2).

**Binding user decision: there is NO standalone VLM daemon.** The fix lives at job boundaries, using the two owners that already exist:
- `bin/story-server` (plus `bin/story-server-restore`) stays the only tool that starts or stops the VLM;
- the movie-ui single FIFO job runner (`movie_ui_lib.run_job`) decides, before and after each job, which state the VLM must be in.

The briefed design items D1-D8, as resolved here:

- **D1.** `job.json` gains `"vlm": "required" | "forbidden" | "any"`, set per job kind (table VP1).
- **D2.** Runner preflight. `required` runs `story-server-restore mlx-vision --wait`, then the health check (D4); a failure fails the job with an exact reason. `forbidden` runs `story-server stop`. `any` does nothing.
- **D3.** Runner postflight, after every end. It restores the VLM detached, in a new session with launchd as parent, iff the queue is empty or the next queued job is `required`. The ordering is fixed against the runner's flock and the cancel/orphan sweeps (VR1).
- **D4.** A port-scoped health check, run at preflight only, never on a timer (VR4). On failure: `story-server stop` (SIGTERM, wait, SIGKILL, port-owner tree only), then exactly one restart.
- **D5.** `bin/story-server` takes an exclusive flock on `$STATE_DIR/story-server.lock` for every start and stop. The wait is **blocking with a timeout**, with fast paths and stop-preempts-start (VS2). The host-wide `VLLM::EngineCore` sweep is replaced by port-owner process-tree discovery (VS6). `story-server-restore` reads the lock instead of scanning `ps` (VRS).
- **D6.** `character_dataset.py:1001` uses `story-server-restore --wait` (VC1).
- **D7.** The submit-time 409 for "story server not running" becomes a `warn` check, and enforcement moves to dispatch (VU1, VU3).
- **D8. Cut [spec choice].** There is no launchd agent, rationale in Section 14 item 12. Startup recovery (VU2) covers reboot for the movie-ui path.

### 0.2 Grounding (verified at eeb8b5f)

**Failure modes (the brief's citations, re-checked):**

- **F1.** `bin/ltx-movie` stops the VLM after Phase 1 and never restores it. `--story-server-stop-after-story` defaults to True (`:435-445`); `phase_release_story_server` runs `bin/story-server stop` and then waits for `--min-avail-gib` (`:1936-1954`); `_phase_sequence` inserts it after Phase 1 (`:2411-2413`). It is inserted even when Phase 1 is skipped because story.md exists (`:1305-1307`), and then it is harmless. Nothing in the movie-ui restores the VLM afterwards, so the next story or character-create job fails at its own gate (`character_dataset.py:1214-1216`).
- **F2.** `character_dataset.py:1001` restarts the server inline with `story_server(VLM_SERVE_MODE)` (`subprocess.run`, `:476-482`, no new session). The `nohup ... &` inside `bin/story-server` (`:383-388`) therefore puts `mlx_vlm.server` in the **job's** process group. movie-ui `cancel_tree` (`movie_ui_lib.py:278-297`) and `kill_orphan`'s SIGKILL (`:512-520`) kill it.
- **F3.** A SIGTERM during that `:1001` load hits `bin/story-server`'s `on_interrupt`, which kills the half-loaded server (`:402-409`). `bin/character` maps SIGTERM to `KeyboardInterrupt` (`bin/character:141-145`), but the exception arises inside the `finally`'s `else` branch, so `interrupted` is False and no restore runs (`character_dataset.py:994-1006`).
- **F4.** `bin/story-server` has no lock (header `:11-24`: "there is no lock file"). The mode-file check (`:282-297`) and the mode-file write (`:397`) are separated by the preflight, including a seconds-long `import mlx_vlm` probe (`:331`), and by the spawn. Two concurrent starts can both pass the check and spawn two 22-34 GB servers. The `VLLM::EngineCore` sweep is host-wide by design (`:95-103`, `engine_pids` `:190-195`), and `stop` and every kill path add it to the kill set (`:405`, `:431`, `:444`, `:571`). In `mlx-vision` mode no EngineCore is ever ours, so that sweep can only kill **another** vLLM's engine, namely the vllm-metal embed server on 8178. This is the qwen-serve-guard mistake (a machine-wide pgrep killed the 8178 sibling). `bin/story-server-restore` detects a start in progress by scanning `ps` (`:39-52`) and checks before it acts (`:62-79`), so it races.
- **F5.** Server availability is checked only at submit time: V2 `story server` (`movie_ui_lib.py:1078-1094`, needed per `story_needed` `:1120-1124`, inside `host_checks` `:1127-1138`). A failed check makes `POST /api/jobs` answer 409 (`movie_ui_server.py:755-759`). Nothing is checked at dispatch, which can be hours later. The page also disables "Write story" unless the startup capability snapshot said SERVING (`static/movie-ui/app.js:464`).
- **F6.** After a reboot, or a runner that died (`lost`, MU29), nothing restores the VLM.

**Additional findings that shape the design:**

- **G1. `start_new_session` alone does not escape a cancel.** `cancel_tree` signals `descendant_groups(child.pid)`, which is the pgid of **every transitive descendant** by ppid, from a `ps -A -o pid=,ppid=,pgid=` snapshot (`process_table` `movie_ui_lib.py:236-250`, `descendant_groups` `:253-265`, `cancel_groups` `:268-275`), new sessions included (MU23, D1 of [MOVIEUI]). `story-server-restore --wait` keeps its `story-server` child as a descendant while it waits (`bin/story-server-restore:75-79`). A cancel during a waiting restore therefore SIGTERMs the loading server's group, and `on_interrupt` kills the load. A new session changes the pgid but not the ppid chain, so the restore must double-fork: the server's parent is then launchd and it is absent from every such snapshot (VRS3).
- **G2.** `--wait` already exists (`bin/story-server-restore:5-12`, `:56`, `:70-72`, `:79`). This spec redefines its semantics (VRS4).
- **G3.** `mlx_vlm.server`'s `/v1/models` lists every cached model and flags the active one with `"loaded": true` (`character_dataset.py:446-463`, `bin/ltx-movie:812-815`). `story-server status` reads only `data[0].id` (`extract_served_id` `:130-137`, `:498-499`); VS10 makes it prefer the loaded entry.
- **G4.** The existing contract and its tests require that a second start of the same mode **during a load** exits 0 at once (M05), and that a start of a different mode exits 3 at once (M06). These are `test_story_server.py::test_s4_s5…` (`:361-401`), `::test_s22` (`:1028`) and `::test_s23` (`:996`). The lock keeps both fast paths (VS2).
- **G5.** `tests/test_story_server.py::test_s14_source_guards` **fails at HEAD**. Commit `439eb1d` host-adapted the defaults to `/Users/ailab1/...` (`bin/story-server:35`, `:41-42`, `:63-64`, `:77`), but the test still expects `/Users/reubenpatterson/...` (`:705-724`). It is a pre-existing baseline failure. 11.4 realigns it, which pins the macstudio paths in the test.
- **G6.** `movie_ui_lib.py`'s import allowlist is pinned by `tests/test_movie_ui_builder.py:244-252`, and GC3 requires `http.client` for HTTP, never `urllib` (`:230`).
- **G7.** `bin/character-train-vlm` (`:17-40`) and `bin/action-train-vlm` (`:16-39`) already stop, train, then restore. They stay unchanged.
- **G8.** `bin/pipeline-stop` never signals the story server (`NEVER`, `:40`) and finishes with `story-server-restore --wait`.
- **G9.** Host defaults. `bin/story-server`'s defaults name the macstudio host (`/Users/ailab1/...`, `:35-77`). This spec changes no host value. Tests isolate the host through the `STORY_SERVER_*` environment variables (`tests/test_story_server.py:161-195`), `STORY_SERVER_RESTORE_BIN` plus a temporary `HOME` (`tests/test_clean_stop.py:63-81`), and the new `MOVIE_UI_VLM_*` variables (11.1).

### 0.3 Deliverables

| # | File | Change |
|---|---|---|
| G1 | `bin/story-server` | lock (VS1-VS3, VS5), `lockinfo` (VS4), port-owner tree instead of the EngineCore sweep (VS6), fd hygiene (VS7), header and usage (VS8, VS9), the loaded model in `extract_served_id` (VS10) |
| G2 | `bin/story-server-restore` | lock-based in-progress detection, double-fork detach, new `--wait` semantics (VRS1-VRS5) |
| G3 | `movie_ui_lib.py` | `vlm` policy (VP1-VP4), preflight, health and postflight (VR1-VR6), V2 `warn` (VU1), recovery restore (VU2) |
| G4 | `movie_ui_server.py` | none beyond calling the changed `lib` functions; no new route. `create_job` sets `vlm` itself |
| G5 | `static/movie-ui/app.js`, `static/movie-ui/app.css` | the write-story gate drops `story_server`; a `.check-warn` class (VU3) |
| G6 | `character_dataset.py` | D6 (VC1) |
| G7 | `tests/conftest.py` | autouse `MOVIE_UI_VLM_LIFECYCLE=0` isolation (11.1) |
| G8 | `tests/test_vlm_lifecycle.py` (new) | VL1-VL28 |
| G9 | `tests/test_story_server.py`, `tests/test_clean_stop.py`, `tests/test_character_tool.py` | new VLS, VLR and VLC tests, plus the 11.4 edits |
| G10 | `tests/test_movie_ui_builder.py::test_mut26` | `BASELINE` re-baseline in a **separate test-only follow-up commit** (rollout step 5) |

**Not changed:** `bin/ltx-movie` (Phase 1b's `story-server stop` now takes the lock with no code change), `bin/character-train-vlm`, `bin/action-train-vlm`, `bin/pipeline-stop`, `bin/movie-ui-job`, `bin/character`, `action_dataset.py`, `bin/ltx-mlx-render`, and every host default in `bin/story-server`.

### 0.4 Out of scope

- A standalone VLM daemon or watchdog, and any timer-driven probe (binding decision; health probes have crashed vllm-metal).
- Starting or stopping the VLM from a page button.
- CLI runs outside movie-ui (`bin/ltx-movie` run by hand still leaves the VLM stopped after Phase 1b, as today). They still benefit from the lock and from port scoping.
- Modes other than `mlx-vision` for the runner. `vision` and `text` stay CLI-only.
- The 8178 embed server. Nothing in this spec reads, probes or signals it.
- Removing the train wrappers' own `restore --wait` under movie-ui (risk R5). This is a recorded **follow-up**, not part of this spec.

### 0.5 Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| VK1 | **No job starts with the VLM in the wrong state.** A `required` job's child is started only after a health check that passed in the same preflight. A `forbidden` job's child is started only after `story-server stop` exited 0 in the same preflight. | VL9-VL14, VL17 (call timestamps are earlier than the child's start marker) |
| VK2 | **Cancel and kill never kill the server.** A VLM start launched by a job (via `story-server-restore`, with or without `--wait`) survives `cancel_tree` and `kill_orphan`. The server's pgid and sid are in none of the groups the runner signals. | VL22, VLR1 |
| VK3 | **Never two servers.** With N=3 concurrent starts (same mode, no mode file yet) or 2 concurrent restores, exactly one stub server process exists. | VLS3, VLR8 |
| VK4 | **Back-to-back renders don't reload.** Two queued `forbidden` jobs give exactly `[stop, stop]` with no restore between them, then one restore after the second (queue empty). | VL21 |
| VK5 | **Port scoping.** `story-server stop` never signals a process outside the port-owner tree, the mode-file pid's tree and the port's `serve` argv matches. A `VLLM::EngineCore` outside that tree survives. | VLS8, VLS9 |
| VK6 | `python3 -m pytest tests/ -q -rA` from `WS` shows the pass count recorded just before implementation, plus every new test, plus the 11.4 edits, with no lost pass. `test_s14_source_guards` moves from fail to pass. `python3 tests/test_ltx_movie_offline.py` prints `OK n/n` with the baseline `n`. Measured after the G10 commit. | full run |
| VK7 | `/usr/bin/python3` (3.9.6) and `python3` (3.13) both `py_compile` every changed Python file. `bash -n bin/story-server` passes, and `/bin/bash` 3.2 runs the VLS tests. | VL27, MUT25 |
| VK8 | Live (macstudio, Section 13 step 6): each of the six F-scenarios is shown fixed, and the PID listening on 8178 is unchanged across every step. | live protocol |

### 0.6 Must-have and nice-to-have

Sections 2-8 are must-haves. Nice-to-have, **not built**: a `vlm` column in the jobs page; a preflight phase in the progress parser; a launchd agent (cut, D8).

---

## 1. Architecture

### 1.1 Owners

- `bin/story-server` is the only process that spawns or kills a VLM server on its port. Its flock serializes every start and stop on the host.
- `bin/story-server-restore` is the only "bring it back" entry point. It never spawns a server itself; it detaches a `story-server <mode>`.
- The movie-ui runner decides the state at the boundaries (preflight before the child, postflight after). The movie-ui server decides only once, at startup (VU2).
- Job-internal transitions stay where they are: Phase 1b in `bin/ltx-movie`, the generate phase in `character_dataset.py`, and the train wrappers.

### 1.2 VLM states

| State | Lock (`lockinfo`) | Mode file | Port 8177 | `story-server status` |
|---|---|---|---|---|
| STOPPED | free | absent | free | `STOPPED` |
| LOADING | held, `cmd=mlx-vision` | `mlx-vision <pid> <ts>` | free | `LOADING mlx-vision` |
| WARMING | held, `cmd=mlx-vision` | present | bound | `SERVING mlx-vision` |
| SERVING | free | present | bound, healthy | `SERVING mlx-vision` |
| HUNG | free | present | bound; `/v1/models` or the 1-token completion fails | `FOREIGN pid N` or `SERVING mlx-vision` |
| STOPPING | held, `cmd=stop` | any | any | any |

### 1.3 State diagram (VLM states vs job kinds)

```
                      postflight / recovery restore (queue empty or next=required)
              +------------------------------------------------------------+
              |                                                            v
         +---------+   preflight(required): restore --wait          +-----------+
         | STOPPED |----------------------------------------------->|  LOADING  |
         +---------+                                                +-----------+
           ^  ^  ^                                                        | ready
           |  |  | preflight(forbidden): stop                             v
           |  |  | (preempts LOADING/WARMING)                       +-----------+
           |  |  +--------------------------------------------------|  WARMING  |
           |  |                                                     +-----------+
           |  |  stop (Phase 1b of a required movie; character             | warm-up done
           |  |  create's generate; train wrappers; forbidden              v
           |  |  preflight)                                         +-----------+
           |  +---------------------------------------------------- |  SERVING  |<--+
           |                                                        +-----------+   |
           |                                                           |  ^          |
           |                  health fails at preflight(required)      |  | restore  |
           |                  -> stop (TERM, 60 s, KILL)     +------+  |  | once     |
           +---------------------------------------------- | HUNG |<-+  |          |
                                                           +------+     |          |
                                    preflight(required), healthy: no-op --+          |
                                    preflight(any), postflight(next=forbidden|any): no-op
```

Per job kind (policy from VP1; "in-job" lists the transitions the job's own code makes):

| Kind | Policy | Preflight result | In-job transitions (code) |
|---|---|---|---|
| `story` | required | SERVING (healthy) | none |
| `movie` (action `movie`), story.md missing at dispatch | required | SERVING | Phase 1b: SERVING → STOPPED (`bin/ltx-movie:1936-1954`) |
| `movie` (action `movie`), story.md present at dispatch | forbidden | STOPPED | Phase 1b stop: "nothing to stop" |
| `movie` (action `redo`) | forbidden | STOPPED | as above |
| `smoke` | forbidden | STOPPED | none |
| `character-create`, `character-regenerate` | required | SERVING | generate: → STOPPED (`character_dataset.py:980`); then `restore --wait` → SERVING (VC1) |
| `character-train` | forbidden | STOPPED | wrapper stop (no-op), train, wrapper `restore --wait` → SERVING (`bin/character-train-vlm:17-40`) |
| `action-train` | forbidden | STOPPED | as above (`bin/action-train-vlm:16-39`) |
| `action-create` | any | unchanged | none |
| `download` | any | unchanged | none |

### 1.4 One job end to end (ordering, normative)

1. The dispatcher writes `starting` and launches the runner (MU30, unchanged).
2. The runner takes `jdir/lock` (blocking; MU22 step 1, unchanged). From here until the runner exits, `job_alive` reports the job alive and nothing else is dispatched.
3. Status check, and a cancel before start (unchanged).
4. **Preflight** (VR2). Tools run as children of the runner, in the runner's process group. The runner is not a descendant of any job child, so no cancel sweep or orphan kill can reach them. The status stays `starting` throughout.
5. Child start, running status, the wait loop, and the cancel sweep (`cancel_tree`) on the child's tree (unchanged).
6. The final status is written.
7. **Postflight** (VR5), still holding `jdir/lock`. The cancel sweep has finished and `child.wait()` has returned, so no snapshot taken in step 5 can contain the restore. The restore detaches the server under launchd (VRS3).
8. The runner exits, which releases the lock, and only then can the next job be dispatched. The postflight's restore returned only after the detached `story-server` took the story-server lock, or exited, or 10 s passed (VRS2 step 4). So in the normal case the next preflight sees the load through `lockinfo`: a required preflight waits for it, and a forbidden preflight's stop preempts it. The exception is a start that could not take the lock within 10 s because it queues behind a stop. A required preflight still waits correctly, because its own restore queues another start behind the same lock. A forbidden preflight's stop can finish before the queued start takes the lock (risk R1).

---

## 2. Data shapes (normative)

### 2.1 `job.json` (amends MU15)

A new key `"vlm"`, one of `"required"`, `"forbidden"`, `"any"`. It is written once by `create_job` from `job_vlm(kind, fields, workspace, story_id)` (VP1). `"schema"` stays `"movie-ui.job.v1"`: the key is additive, and a job queued before the upgrade has no `vlm` and is treated as `"any"` (VP2) **[spec choice]**.

### 2.2 `status.json` rows (amends MU16)

| Writer | When | Object |
|---|---|---|
| runner | preflight failed | `{"state": "failed", "dispatched": T, "runner_pid": P, "pgid": null, "started": null, "exit_code": null, "ended": T, "error": "<VR2 error>"}` |
| runner | cancelled during preflight | `{"state": "cancelled", "exit_code": null, "ended": T}` (the server-cancel shape, as MU22 step 3) |

### 2.3 Lock file `$STATE_DIR/story-server.lock`

- Mode 0644. It is created by `story-server` (`: >>"$LOCK_FILE"`) and never deleted.
- Content: one line `<story-server pid> <cmd> <UTC %Y-%m-%dT%H:%M:%SZ>\n`, written by the holder right after it acquires the lock. `<cmd>` is one of `vision`, `text`, `mlx-vision`, `stop`.
- The content is advisory. It is trusted only while the lock is actually held **and** the pid is alive.

### 2.4 `story-server lockinfo` output

Exactly one line on stdout, exit 0:
- `lock: free path=<LOCK_FILE>`
- `lock: held pid=<pid> cmd=<cmd> since=<ts> path=<LOCK_FILE>`. A missing field prints `?`.

### 2.5 Environment and constants

| Name | Where | Default | Purpose |
|---|---|---|---|
| `STORY_SERVER_LOCK_TIMEOUT` | story-server | `1260` | the longest wait for the lock (VS1) |
| `STORY_SERVER_RESTORE_WAIT_S` | story-server-restore | `2520` | `--wait` cap (VRS4) |
| `STORY_SERVER_RESTORE_BIN` | story-server-restore | `<bin>/story-server` | exists today; tests use it |
| `MOVIE_UI_VLM_LIFECYCLE` | movie_ui_lib | `"1"` | `"0"` disables VR2, VR5, VU1's warn and VU2; bin/story-server, bin/story-server-restore, character_dataset.py, the vlm key and the page gate stay changed (reverting those is git revert of commits A and C). Used by the tests and as the runtime rollback switch |
| `MOVIE_UI_VLM_TOOLS` | movie_ui_lib | `<UI WS>/bin` | the directory holding `story-server` and `story-server-restore` |
| `MOVIE_UI_VLM_PORT` | movie_ui_lib | `8177` | the health-check port (tests use an ephemeral one) |

`movie_ui_lib` constants: `VLM_MODE = "mlx-vision"`, `VLM_POLICIES = ("required", "forbidden", "any")`, `VLM_STATUS_TIMEOUT_S = 60`, `VLM_HTTP_TIMEOUT_S = 10`, `VLM_COMPLETION_TIMEOUT_S = 120`, `VLM_PREFLIGHT_TIMEOUT_S = 6900`, `VLM_POSTFLIGHT_TIMEOUT_S = 90`, `VLM_TOOL_KILL_WAIT_S = 5`, `VLM_MAX_BODY = 1048576`, `VLM_RESTORE_LOG_TEXT = "~/.local/share/qwen-agent/story-server-restore.log"`, `VLM_RECOVERY = []` (pending recovery reasons, server process only), `RESTORERS = []` (Popen objects, polled to reap them, like `RUNNERS`).

**Timeout justifications:**
- `LOCK_TIMEOUT` 1260 s covers the longest legitimate hold: a start's readiness poll (`READY_TIMEOUT` 840 s, `:87`), plus warm-up (`WARM_TIMEOUT` 300 s, `:90`), plus one `kill_set` (60 + 10 s, `:92-93`), plus 50 s of probe slack.
- `RESTORE_WAIT_S` 2520 s is one full lock wait (1260) plus one full start (840 + 300 + 70 = 1210), rounded up to 42 min. A normal 5-14 min load plus up to 5 min of warm-up fits with margin. A load queued behind another load also fits.
- `VLM_PREFLIGHT_TIMEOUT_S` 6900 s. It covers two `restore --wait` (2 × 2520 = 5040) and two health checks (2 × 190 = 380; each is status 60 + models 10 + completion 120). It also covers one stop (a lock wait of 1260 + one `kill_set` of 70 + 20 s of slack = 1350). That sums to 6770 s, rounded up. It is a hard cap for pathological cases only. The tool steps are polled for the cancel marker every 1 s. The health check is **not** polled for cancel, so a cancel that arrives during one is acted on when it returns (up to 190 s later).
- Completion timeout 120 s: by preflight the server has finished its own warm-up (story-server S-9), so a healthy 1-token reply takes seconds. 120 s tolerates a cold Metal cache without masking a hang.

---

## 3. Policy (VP)

### VP1. `job_vlm(kind, fields, workspace, story_id)`

Pure except for one `os.path.isfile`. Returns a member of `VLM_POLICIES`:

```python
def job_vlm(kind, fields, workspace, story_id):
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
```

The rationale for each kind:
- `story`: `--story-only` always runs Phase 1, the VLM authors (`bin/ltx-movie:1290`, `STORY_BASE_URL` `:800`).
- `movie` with no story.md: Phase 1 authors.
- `movie` with story.md: Phase 1 is a model-free re-check (`story_engine.recheck`) or a skip (`:1305-1307`), and Phases 2-4 need at least 25 GiB free (`--min-avail-gib` `:433`, gate `:1952`, `:2160`).
- `redo`: needs story.md (`:1116`).
- `smoke`: `bin/ltx-mlx-render` with the full LTX model and no avail gate of its own.
- character create and regenerate: the `vlm_ready` gate (`character_dataset.py:1214-1216`) and the face, describe and score calls.
- Both trains: the gates require STOPPED (`character_dataset.py:1485-1488`, `action_dataset.py:383-386`), and training reuses the VLM's ~34 GB.
- `action-create`: ffmpeg only (`action_dataset.py:155-200`).
- `download`: no VLM.
- An unknown kind gets `any`.

`create_job` (`movie_ui_lib.py:173-189`) adds `"vlm": job_vlm(kind, fields, workspace, story_id)` to the `job` dict, between `"fields"` and `"created"`. Its signature does not change.

### VP2. `effective_vlm(job)`

```python
def effective_vlm(job):
    if job.get("kind") == "movie":
        return job_vlm("movie", job.get("fields"), job.get("workspace"), job.get("story_id"))
    vlm = job.get("vlm")
    return vlm if vlm in VLM_POLICIES else "any"
```

A movie job is recomputed at dispatch because a story job queued ahead of it can create story.md after submit.

### VP3. `next_queued_job(state)`

This returns `(job_id, job)` for the first ID in `read_queue(state)` that has no `status.json` (`os.path.lexists`) and a readable `job.json`, else `(None, None)`. The skip rule is the dispatcher's (MU30), and the function never writes.

### VP4. `vlm_restore_wanted(state)`

This returns `(True, "queue empty")` when `next_queued_job` gives `None`. Otherwise it maps `effective_vlm(job)` of the next job:
- `required` → `(True, "next job <id> needs it")`;
- `forbidden` → `(False, "next job <id> runs without it")`;
- `any` → `(False, "next job <id> is vlm=any")`.

---

## 4. Runner (VR)

### VR1. `run_job(jdir, grace)` (amends MU22)

Changes only. Every other line stays as at `movie_ui_lib.py:300-360`.
- `state_root = os.path.dirname(os.path.dirname(jdir))`, computed after the status check.
- Step 3 (cancel before start): after `_say("cancelled before start")`, call `vlm_postflight(state_root)`, then `return 0`.
- New step 3b. After `job = read_job(jdir)` and before opening `log.txt` for the child:

  ```python
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
  ```
- The child-start `OSError` path: call `vlm_postflight(state_root)` after `_say(error)` and before `return 1`.
- After the final `write_status` and `_say("exit %d (%s)" ...)`: call `vlm_postflight(state_root)`, then `return 0`.
- The status-not-starting path (`return 3`) runs **no** postflight. No job ended there.
- The child's environment (`movie_ui_lib.py:322-323`) becomes `dict(os.environ, PYTHONUNBUFFERED="1", QWEN_AGENT_VLM_MODEL=os.environ.get("QWEN_AGENT_VLM_MODEL") or "auto", STORY_SERVER_ENGINE_SCAN="0")`. This is unconditional, also when the lifecycle is disabled. A job whose workspace is an older release runs that release's own `bin/story-server stop` (Phase 1b, the generate phase, the train wrappers). Every `bin/story-server` since its first commit `6ab72ac` honours `STORY_SERVER_ENGINE_SCAN=0` (`:103`, `:192`), so the old host-wide sweep can no longer kill the 8178 embed server's EngineCore from a movie-ui job (risk R4). The new `bin/story-server` ignores the variable (VS1).

`vlm_lifecycle_enabled()` returns `os.environ.get("MOVIE_UI_VLM_LIFECYCLE", "1") != "0"`. `vlm_tools_dir(ui_ws=None)` returns `os.environ.get("MOVIE_UI_VLM_TOOLS")` when it is non-empty, else `os.path.join(ui_ws or os.path.dirname(os.path.realpath(__file__)), "bin")`. `vlm_port()` returns `int(os.environ.get("MOVIE_UI_VLM_PORT") or 8177)`.

The tools come from the **UI** workspace, not the job's workspace **[spec choice]**. The runner and its lifecycle tools then come from the same release, so the `--wait` and lock contracts match.

### VR2. `vlm_preflight(job, cancel, tools=None, port=None, health=None, timeout=VLM_PREFLIGHT_TIMEOUT_S)`

Returns `("ok", None)`, `("failed", <error>)` or `("cancelled", None)`. The defaults are `tools=vlm_tools_dir()`, `port=vlm_port()` and `health=vlm_health`.

```python
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
```

A restore that exits non-zero is treated like a failed health check on the first attempt **[spec choice]**. A hung `mlx-vision` server makes the restore exit 1, because it reports FOREIGN, and that case needs the stop-and-restart. A **different-mode** story server (`vision`/`text`) is never stopped by a required job, which simply fails (user resolution of Q2, conservative). The check runs before any stop.

`_vlm_other_mode(tools)` runs `run_light([os.path.join(tools, "story-server"), "status"], tools, timeout=VLM_STATUS_TIMEOUT_S)`. It takes the first `STATE_LINE_RE` match and returns `m.group(2)` when `re.fullmatch(r"(SERVING|LOADING) (vision|text)", state)` matches. On a timeout, an exit other than 0, no state line or no match it returns `None`.

### VR3. `_vlm_step(argv, cancel, deadline, timeout)`

Returns `("exit", rc)`, `("cancelled", None)` or `("failed", <error>)`.
1. `_say("vlm: running: %s" % shlex.join(argv))`.
2. `subprocess.Popen(argv, stdin=subprocess.DEVNULL, close_fds=True)`. stdout and stderr are inherited (the runner's stdout is `log.txt`, MU21). There is no new session. An `OSError` returns `("failed", "VLM preflight failed: cannot run %s: %s" % (argv[0], e.strerror or e))`.
3. Loop on `proc.wait(timeout=1)`. On `TimeoutExpired`:
   - if `cancel` exists, call `_stop_tool(proc)` and return `("cancelled", None)`;
   - if `time.monotonic() >= deadline`, call `_stop_tool(proc)` and return `("failed", "VLM preflight timed out after %d s" % timeout)`.
4. Return `("exit", proc.returncode)`.

`_stop_tool(proc)`: `proc.terminate()`; `proc.wait(VLM_TOOL_KILL_WAIT_S)`; on `TimeoutExpired`, `proc.kill()` and then `proc.wait()`. Terminating a waiting `story-server-restore` leaves the detached load running (VRS3). Terminating a `story-server stop` mid-way is acceptable, because the next preflight re-establishes the state.

### VR4. `vlm_health(tools, port, status_timeout=VLM_STATUS_TIMEOUT_S, http_timeout=VLM_HTTP_TIMEOUT_S, completion_timeout=VLM_COMPLETION_TIMEOUT_S)`

Returns `(ok, detail)`. The steps run in this order, and the first failure returns `(False, <H text>)`. There are no retries, and exactly one HTTP request of each kind is sent.

1. **Status.** `run = run_light([os.path.join(tools, "story-server"), "status"], tools, timeout=status_timeout)`.
   - `run["timed_out"]` → H1.
   - `run["exit_code"] != 0` → H2.
   - `state` is the first `STATE_LINE_RE` match; a missing match counts as `UNKNOWN`. `state != "SERVING mlx-vision"` → H3.
   - `model` is the first match of `HEALTH_LINE_RE = re.compile(r"^\s*health:\s*HTTP\s+\d{3}\s+model=(.+?)\s*$")`. No match, or `none` → H9.
2. **Models.** `http.client.HTTPConnection("127.0.0.1", port, timeout=http_timeout)`, `GET /v1/models`, read at most `VLM_MAX_BODY` bytes.
   - A non-200 status, a JSON decode error, a body that is not an object holding a list `data`, or any `OSError`/`http.client.HTTPException` → H4. `<what>` is `HTTP <n>`, `invalid JSON`, or the exception class name.
   - `entries = [d for d in data if isinstance(d, dict) and d.get("id") == model]`. Empty → H5.
   - `"loaded" in entries[0] and entries[0]["loaded"] is not True` → H6.
3. **Completion.** A new connection with `timeout=completion_timeout`. `POST /v1/chat/completions` with header `Content-Type: application/json` and body `json.dumps({"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "Reply with the single word ok"}]})`. A non-200 status, a JSON error or an exception → H7. A body that is not an object with a non-empty list `choices` → H8.
4. Return `(True, "%s on 127.0.0.1:%d" % (model, port))`.

The worst case is 190 s (60 + 10 + 120). The health check is called **only** from VR2. No timer calls it.

There is **no RSS or listening-pid check** (design review). Metal-resident memory is not counted in `ps` RSS: a healthy `mlx_vlm.server` was measured at 227 MB RSS. RSS therefore cannot tell a healthy server from a collapsed one. A hung server is caught by H1/H3 (a `/v1/models` probe timing out in `status`), H4 or H7/H8. Its port-scoped kill is `story-server stop`, which runs SIGTERM, then 60 s, then SIGKILL on the port-owner tree (VS6).

### VR5. `vlm_postflight(state)`

```python
def vlm_postflight(state):
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
```

A restore without `--wait` returns after one `lockinfo`, one `status`, the launch, and at most 10 s of waiting for the detached start to take the lock. That wait is typically under 0.5 s (VRS2 step 4). The runner therefore holds `jdir/lock` only briefly.

**It never runs twice for one end.** The runner's postflight is the only automatic restore for a job that ended under its runner. VU2 fires only once, at server startup. Any duplicate is a no-op through the lock (VRS2 step 1).

### VR6. `cancel_tree` and `kill_orphan` are unchanged

They stay as at `movie_ui_lib.py:268-297` and `:512-520`. With VR1's ordering and VRS3's detach, the server is never inside a cancelled tree or a killed group.

---

## 5. Server and page (VU)

### VU1. V2 `story server` becomes `warn` (amends V2, MU42, MU44)

- Split `story_server_check` (`movie_ui_lib.py:1078-1094`) into the pieces below.
  - `story_server_probe(ws_real)` returns `("serving", state)`, `("down", state)`, `("timeout", None)` or `("error", "bin/story-server status exited <n|none>: <last stderr line or ->")`. It uses the same `run_light` call and parsing as today.
  - `_story_server_pair(kind, value)` maps those to today's `(ok, detail)` texts, byte-identical:
    - `story server: <state>`;
    - `story server is <state>; start it with bin/story-server mlx-vision`;
    - `bin/story-server status timed out after 60 s`;
    - the error text.
  - `story_server_check(ws_real) = _story_server_pair(*story_server_probe(ws_real))`. The capability probe (MU60) keeps using it unchanged.
- New `story_server_record(ws_real)`:
  - When `vlm_lifecycle_enabled()` and the kind is `down`: `check("V2", "story server", "warn", "story server is %s; the job starts it when it reaches the front of the queue (a 5-14 min load)" % state)`.
  - When `vlm_lifecycle_enabled()` and the kind is `timeout`: `check("V2", "story server", "warn", "bin/story-server status timed out after 60 s; the job checks the story server and restarts it if needed when it reaches the front of the queue")`.
  - Otherwise: `_from_pair("V2", "story server", _story_server_pair(kind, value))`.
- `host_checks` uses `story_server_record(ws_real)` in place of `_from_pair("V2", "story server", story_server_check(ws_real))`.
- `check` records may now have `status == "warn"`. `checks_pass` is unchanged (only `fail` fails). A submit with a `warn` gets 201 and the record in `"checks"`. An `error` kind (for example exit 4, lsof missing) still fails with 409.

### VU2. Startup restore (F6; amends MU30, MU31)

- `_vlm_recheck(reason)` appends `reason` to `VLM_RECOVERY` only when `vlm_lifecycle_enabled()`.
- It is called **only** at the end of `startup_recovery`, with `"startup"`. `job_alive` and `kill_orphan` are unchanged and queue nothing (design review).
- Why no lost or orphan hook: correctness never depends on a pre-warm. Every `required` job's preflight restores on demand (VR2). An orphan hook would start a 34 GB load right after a SIGKILL, before the killed render's memory is freed.
- Why the startup hook stays [spec choice]: after a reboot or a movie-ui restart with an empty queue it restores the idle state that postflight would have left ("VLM up when idle", VR5). It runs at the first idle tick, so only when no job is active and no orphan is alive, and it follows the same `vlm_restore_wanted` rule. A user who starts movie-ui to write a story does not then wait 5-14 min in the first preflight.
- `dispatch_tick`: after the active-job loop and the orphan loop (both unchanged, so it is reached only when nothing is active and no live orphan exists), and before the queue loop:

  ```python
  if VLM_RECOVERY:
      reason = "; ".join(VLM_RECOVERY)
      del VLM_RECOVERY[:]
      recovery_restore(state, ui_ws, reason)
  ```
- `recovery_restore(state, ui_ws, reason)` (named for its only reason so far, `startup`):
  - Returns `None` if the lifecycle is disabled.
  - `wanted, why = vlm_restore_wanted(state)`. If not wanted, write `movie-ui: VLM restore (<reason>): skipped (<why>)\n` to stderr and return `None`.
  - Else `argv = [os.path.join(vlm_tools_dir(ui_ws), "story-server-restore"), VLM_MODE]`, prune `RESTORERS` of finished processes, and `subprocess.Popen(argv, stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)`. stdout and stderr are inherited (the server log). It never waits under `STORE_LOCK`.
  - `OSError` → stderr `movie-ui: VLM restore (<reason>): cannot start <argv[0]>: <strerror>\n`. Return `None`.
  - Success → append to `RESTORERS`, stderr `movie-ui: VLM restore (<reason>; <why>): started <shlex.join(argv)> (pid <pid>)\n`, and return the Popen.

### VU3. Page (static)

- `app.js:464` becomes `gate($("#c-write-story"), $("#c-write-story-reason"), []);`. The badge (`:195-213`) is unchanged.
- `app.css` adds, after line 47: `.check-warn { color: var(--warn); }`.

### VU4. Imports (amends GC3)

- `movie_ui_lib.py` adds `import http.client`, for loopback-only requests to 127.0.0.1. `http.client` ignores proxy environment variables, which is GC3's reason.
- `tests/test_movie_ui_builder.py::test_mut25_source_scan_of_new_python_files` adds `"http.client"` to its `allowed` set.

---

## 6. `bin/story-server` (VS)

### VS1. Constants (after `STANDDOWN=` `:79`)

```bash
LOCK_FILE="$STATE_DIR/story-server.lock"
# Longest legitimate hold: a start's readiness poll (READY_TIMEOUT 840 s) + warm-up (WARM_TIMEOUT
# 300 s) + one kill_set (60 + 10 s) + probe slack = 1260 s (VLM lifecycle spec 2.5).
LOCK_TIMEOUT="${STORY_SERVER_LOCK_TIMEOUT:-1260}"
```

Delete the `ENGINE_SCAN` comment and assignment (`:95-103`) and `engine_pids` (`:190-195`). The new script ignores `STORY_SERVER_ENGINE_SCAN`, and the runner's child environment still sets it for older releases (VR1).

### VS2. `lock_take CMD` (new helper, after `add_pid`)

```bash
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

Semantics:
- The helper inherits fd 9. The flock belongs to the open file description, which bash keeps open, so the lock stays held after the helper exits, until `story-server` exits (or is killed).
- The helper's own messages are M30, M32, M33, M35 and M36.
- A start that finds a live start of the **same** mode exits 0 (G4, M05 contract). A start that finds a live start of **another** mode exits 3 (M06 contract). Both fast paths require the holder's command line to contain `story-server` (`is_story_server`), the same check as the preempt. A stale record whose pid was reused by another process therefore never short-cuts a start; it waits instead.
- A stop that finds a live start sends it SIGTERM once, provided its command line contains `story-server` (never a foreign pid). The start's `on_interrupt` (`:402-409`) kills the half-loaded server, or bash dies by default action before the spawn or after `:449`. The stop then waits.
- Every other contention (stop vs stop, start vs stop, an unknown, dead or reused-pid holder) waits up to `LOCK_TIMEOUT`.
- If the lock file cannot be opened (no writable `$STATE_DIR`, for example on a host without `/Users/ailab1`), a start fails closed (M34, exit 4). A stop warns (M37) and proceeds without the lock (risk R10).

### VS3. Where the lock is taken

- `cmd_serve`: right after the `M00` line (`:276`), insert `lock_take "$MODE"`. The rest of S-1 to S-9 is unchanged, except for VS6 and VS7.
- `stop`: in the dispatch (`:688-690`), after the M00 `say`, call `lock_take stop`, then `cmd_stop`.
- `status` and `lockinfo` never take the lock.

### VS4. `lockinfo` subcommand

```bash
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
```

### VS5. Header (replaces `:11-24`)

Replace "these are documented, NOT defended in code; there is no lock file and no health watchdog" with "the lock is defended in code (VLM lifecycle spec VS2); there is no health watchdog". Insert this bullet before the R1 bullet:

```
#   * vision/text/mlx-vision and stop hold an exclusive flock on $STATE_DIR/story-server.lock for
#     their whole run; status and lockinfo never take it. A start that finds a start of the same
#     mode in progress exits 0, of another mode exits 3; a stop in progress makes it wait. A stop
#     that finds a start in progress SIGTERMs that start (its trap kills the half-loaded server)
#     and waits. A wait gives up after STORY_SERVER_LOCK_TIMEOUT s (exit 7).
```

In the R1 bullet, replace "If you delete it by hand mid-load, the next `vision` sees a free port and spawns a SECOND ~22 GiB server, which will OOM this host." with "A second start during the load is now refused by the lock, whatever the mode file says."

### VS6. Port-owner tree (replaces the EngineCore sweep)

New helper (after `serve_cmd_pids`):

```bash
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

Uses:
- `on_interrupt` (`:405`), M18 (`:431`) and M19 (`:444`): replace `kill_set "$SPAWN_PID $(port_pids) $(engine_pids)"` with `kill_set "$SPAWN_PID $(port_pids) $(tree_pids "$SPAWN_PID $(port_pids)")"`.
- `cmd_stop`: delete `eng_list` (`:567`, `:571`). Step 1 becomes:

  ```bash
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

  This runs before `if [ -z "$CAND" ]`. Step 2's validation (`:574-592`) is unchanged and still runs first.

### VS7. fd hygiene

- Append ` 9>&-` after `</dev/null` on the three spawn lines (`:380`, `:387`, `:392`).
- In the warm-up (`:464-467`), insert ` 9>&-` after `--data-binary @-`, before `<<EOF`.

The server and the warm-up curl (up to 300 s) never inherit the lock. The other children of `story-server` do inherit fd 9: the readiness `curl -m 10` probes, `sleep`, `ps`, `lsof` and the `$PY` helpers. All of them are short-lived. So when `story-server` itself is killed, the lock stays held until they exit, at most about 10 s (`PROBE_TIMEOUT`, `:89`). Waiters simply wait that long.

### VS8. Messages (new)

| ID | Stream | Text |
|---|---|---|
| M30 | stdout | `story-server: preempting the <mode> start in progress (story-server pid <pid>)` |
| M31 | stdout | `story-server: WARNING: VLLM::EngineCore pid <pid> has parent pid 1 and is not in port <PORT>'s process tree; left running (it may belong to another vLLM, such as the embed server on 8178)` |
| M32 | stdout | `story-server: waiting for the lock held by pid <pid> (<cmd> since <ts>) (<n>s elapsed)` (every 30 s) |
| M33 | stderr | `story-server: TIMEOUT: <LOCK_FILE> is still held by pid <pid> (<cmd> since <ts>) after <n>s; not running <cmd>` (exit 7) |
| M34 | stderr | `story-server: cannot open the lock file <LOCK_FILE>; refusing to run <cmd> without it` (exit 4) |
| M35 | stdout | `story-server: a <mode> start (story-server pid <pid>) is already running; it may still be loading -- poll <HEALTH_URL>` (exit 0) |
| M36 | stderr | `story-server: REFUSING: a <mode2> start (story-server pid <pid>) is already running; run "story-server stop" first, then start <mode>` (exit 3) |
| M37 | stdout | `story-server: WARNING: cannot open the lock file <LOCK_FILE>; stopping without the lock` (the stop continues) |

### VS9. Usage and dispatch

- M01 becomes `usage: story-server [vision|text|mlx-vision|status|stop|lockinfo]`.
- The argument check (`:655-657`) accepts `lockinfo`.
- `case` gains `lockinfo) cmd_lockinfo ;;`.
- No literal `8177` is added (S14). The new code uses no bash-4 features.

### VS10. `extract_served_id` prefers the loaded model (R13)

Replace the Python body of `extract_served_id` (`:131-137`) and its comment (`:130`) with the following. The quoting is unchanged: the code is single-quoted for bash and uses no single quotes.

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

A listing without any `loaded` flag (vLLM, MTPLX, the test stubs) behaves exactly as today.

---

## 7. `bin/story-server-restore` (VRS)

### VRS1. Constants

Keep `BIN`, `STORY_SERVER` and `LOG`. Add:

```python
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

Delete `start_in_progress`'s `ps` scan (`:39-52`). `ps` is no longer run anywhere in this file.

### VRS2. Order in `main` (argument parsing unchanged, `:56-61`)

1. `holder = lock_holder()`. If `holder` is not `None` and `holder[1] == mode`: print `story-server-restore: a story-server <mode> start is already in progress (pid <pid>)` (flush). Return `wait_done(mode, None)` with `--wait`, else `0`.
2. `if serving(mode)`: print `story-server-restore: already serving <mode>` and return `0`.
3. `pid = launch(mode)`. `None` → return `1`.
4. Print `story-server-restore: starting story-server <mode> (pid <pid>, own session); log: <LOG>` (flush). Then poll `lock_holder()` every `LOCK_POLL_S` (0.2 s) for at most `LOCK_WAIT_S` (10 s), until it returns `(p, c)` with `c == mode`, or `alive(pid)` is False:

   ```python
   deadline = time.monotonic() + LOCK_WAIT_S
   while time.monotonic() < deadline and alive(pid):
       holder = lock_holder()
       if holder is not None and holder[1] == mode:
           break
       time.sleep(LOCK_POLL_S)
   ```

   Return `wait_done(mode, pid)` with `--wait`, else `0`.

   **Why.** Without this wait a restore without `--wait` returns before the detached start has taken the lock. The caller (the runner's postflight, a job's interrupt path) can then exit, and the next preflight can run first: a forbidden stop finds nothing to stop, and the start then loads during the render. With the wait, the start normally holds the lock before the caller continues, so a following stop preempts it (1.4 step 8). Typically this costs under 0.5 s. It costs the full 10 s only when the start queues behind a stop holder (risk R1). The train wrappers' signal path (`bin/character-train-vlm:22-27`) calls a restore without `--wait` inside the 15 s cancel grace; 10 s fits.

The lock is checked before `serving` so that a WARMING server, which already reports SERVING, is waited for and never overlapped by the runner's health completion.

`lock_holder()`:
- runs `subprocess.run([STORY_SERVER, "lockinfo"], capture_output=True, text=True, timeout=30)`; an exception returns `None`;
- for the first stdout line whose words start `lock:`, `held`, `pid=<digits>`, `cmd=<x>` and whose pid is `alive`, returns `(pid, x)`;
- else returns `None`. An old `story-server` without `lockinfo` (usage, exit 2) gives `None`.

`alive(pid)`: `os.kill(pid, 0)` → True; `ProcessLookupError` → False; `PermissionError` → True.

### VRS3. `launch(mode)` (the double fork, G1)

- `os.makedirs(os.path.dirname(LOG), exist_ok=True)`.
- `proc = subprocess.run([sys.executable, "-c", LAUNCH, LOG, STORY_SERVER, mode], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)`.
- Any exception, `returncode != 0`, or stdout that is not digits once stripped → print `story-server-restore: cannot start story-server <mode>: <str(e), or the last stderr line, or "launcher exited <n>">` to stderr and return `None`.
- Else return `int(stdout)`.

The launcher exits as soon as it has spawned `story-server`, whose parent becomes launchd (pid 1) in a new session. No process tree that contains the caller contains the server.

**Why a double fork, not just `start_new_session`.** movie-ui's cancel signals `cancel_groups(child.pid)`, which walks every **transitive descendant** by ppid in a `ps` snapshot and signals each descendant's pgid (`movie_ui_lib.py:253-275`). A single-fork child in a new session keeps the caller as its parent, so while `--wait` waits it is still a descendant and its new group is signalled (G1). After the double fork the server's ppid is 1 and it is in no snapshot of the job's tree. The same holds for `kill_orphan`, which signals only the job child's recorded pgid.

### VRS4. `wait_done(mode, pid)` (the new `--wait`)

```python
deadline = time.monotonic() + WAIT_S
while (pid is not None and alive(pid)) or (lock_holder() or (None, None))[1] == mode:
    if time.monotonic() >= deadline:
        print("story-server-restore: TIMEOUT: story-server %s did not finish within %d s"
              % (mode, WAIT_S), file=sys.stderr)
        return 1
    time.sleep(POLL_S)
return 0 if serving(mode) else 1
```

While it waits, it runs only `lockinfo` (a local flock probe) and `kill -0`. It sends no HTTP request. It makes exactly one `status` call at the end.

### VRS5. Docstring

Replace the "Does nothing (exit 0)..." paragraph with:

> Does nothing (exit 0) when MODE is already serving. When `story-server lockinfo` shows a live MODE start holding the lock it starts nothing, and with --wait it waits for that start. Otherwise it launches `story-server MODE` through a launcher that exits at once, waits up to 10 s for that start to take the lock, so the server's parent is launchd and no job's cancel or orphan kill can reach it (VLM lifecycle spec VRS3). --wait blocks, polling only the lock and the started pid, until no MODE start is running (at most STORY_SERVER_RESTORE_WAIT_S, default 2520 s), then exits 0 iff `story-server status` reports SERVING MODE.

---

## 8. `character_dataset.py` (VC)

### VC1. D6

`restore_story_server` (`:485-493`) becomes:

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

In `_build_dataset`'s `finally` (`:1000-1004`), replace the two statements `rc = story_server(VLM_SERVE_MODE)` and the `if rc != 0: print(...)` that follows with:

```python
            rc = restore_story_server(wait=True)
            if rc != 0:
                print("warning: story-server-restore %s --wait returned %d" % (VLM_SERVE_MODE, rc),
                      file=sys.stderr)
```

The interrupted branch (`:999`) and the `wait_for_vlm` check (`:1005-1006`) are unchanged. On a SIGTERM during this wait, `subprocess.run` kills only the restore waiter, and the detached load continues (closing F3).

---

## 9. Deliberately unchanged

- `bin/ltx-movie`: its Phase 1b stop is correct inside a `required` movie job. A `forbidden` job's Phase 1b stop prints "nothing to stop".
- The train wrappers: kept per the brief. Their final restore is redundant with postflight, but harmless through the lock (R5).
- `bin/pipeline-stop`: its final `restore --wait` gains the new semantics automatically.

---

## 10. Runner and server strings (exact)

Runner lines are written through `_say`, so each gets the `[movie-ui] ` prefix:

| Text |
|---|
| `vlm: job.json says vlm=<a>; story.md <exists\|is missing> now, so vlm=<b>` |
| `vlm: preflight: vlm=any; the VLM is left as it is` |
| `vlm: preflight: this job runs without the VLM (vlm=forbidden)` |
| `vlm: preflight: this job needs the VLM (vlm=required)` |
| `vlm: running: <shlex.join(argv)>` |
| `vlm: stopped for this job` |
| `vlm: healthy: <detail>` |
| `vlm: unhealthy: <problem>; restarting it once` |
| `cancelled during the VLM preflight` |
| `vlm: postflight: not restoring the VLM (<why>)` |
| `vlm: postflight: restoring the VLM in its own session (<why>)` |
| `vlm: postflight: bin/story-server-restore exited <n>` / `... timed out after 90 s` / `vlm: postflight: cannot run <path>: <strerror>` |

Errors, stored in `status.json` `error` and also printed:
- `VLM preflight failed: bin/story-server stop exited <n>; the log above shows why`
- `VLM preflight failed after one restart: <problem>`
- `VLM preflight failed: the story server runs in <vision|text> mode, not mlx-vision; stop it with bin/story-server stop and resubmit`
- `VLM preflight timed out after <timeout> s`
- `VLM preflight failed: cannot run <path>: <strerror>`

Health problems (H):

| ID | Text |
|---|---|
| H1 | `bin/story-server status timed out after <status_timeout> s` |
| H2 | `bin/story-server status exited <n\|none>` |
| H3 | `story server is <state>, not SERVING mlx-vision` |
| H4 | `GET /v1/models failed: <HTTP n\|invalid JSON\|ExcName>` |
| H5 | `GET /v1/models does not list <model>` |
| H6 | `<model> is listed by /v1/models but not loaded` |
| H7 | `completion failed: <HTTP n\|invalid JSON\|ExcName>` |
| H8 | `completion reply has no choices` |
| H9 | `bin/story-server status printed no served model` |

The "restore exited" problem text is `bin/story-server-restore mlx-vision --wait exited <n> (see ~/.local/share/qwen-agent/story-server-restore.log)`.

V2 warn texts (W1, W2) are in VU1. Server stderr lines are in VU2.

---

## 11. Tests

### 11.1 Isolation

- `tests/conftest.py` gains an autouse fixture, `vlm_lifecycle_isolation(monkeypatch, tmp_path)`. It sets `MOVIE_UI_VLM_LIFECYCLE=0`, `MOVIE_UI_VLM_TOOLS=<tmp_path>/no-vlm-tools` (nonexistent) and `MOVIE_UI_VLM_PORT=9`. With it, every existing test sees HEAD's runner and V2 behaviour, and no test can reach the real `bin/story-server`. Runner subprocesses inherit the variables.
- Tests that exercise the lifecycle set `MOVIE_UI_VLM_LIFECYCLE=1`, a fake tools dir and an ephemeral port, and call `monkeypatch.setattr(lib, "VLM_RECOVERY", [])`.
- No test runs the real `bin/story-server` without `STORY_SERVER_STATE_DIR`, `STORY_SERVER_PORT` (ephemeral) and every binary override from `_base_env` (`tests/test_story_server.py:161-195`). The `/Users/ailab1` defaults are therefore never used. The only exceptions are S1 (exits 2 before acting) and S14 (reads the source).
- Restore tests set `HOME=<tmp>` and `STORY_SERVER_RESTORE_BIN=<fake>`.
- No test renders, binds 8177 or 8178, or signals a process it did not start. The VLS9 orphan is started by the test.

### 11.2 Fakes (normative)

**F-TOOLS** (`tests/test_vlm_lifecycle.py::make_fake_tools(tmp, model, stop_rc=0, restore_rc=0, restore_sleep=0, serve_on_restore=True)`) writes `<tmp>/tools/story-server` and `<tmp>/tools/story-server-restore`. Both are `#!<sys.executable>` scripts.
- Each call appends one JSON line to `<tmp>/tools/calls.jsonl`: `{"tool", "argv", "pid", "ppid", "pgid": os.getpgid(0), "sid": os.getsid(0), "t": time.time()}`.
- `<tmp>/tools/vlm_state` holds the state text (initially `STOPPED`).
- `story-server status` prints `story-server status  X\n  state:          <vlm_state>\n  health:         HTTP 200 model=<model>\n` and exits 0. The behaviour can be overridden per call by `<tmp>/tools/config.json` `{"status": {"exit": n, "sleep": s, "stdout": "..."}}`.
- `stop` writes `STOPPED` and exits `stop_rc`.
- `lockinfo` prints `lock: free path=x`.
- `story-server-restore` with `--wait`: sleeps `restore_sleep`, writes `SERVING mlx-vision` when `serve_on_restore`, and exits `restore_rc`. Without `--wait` it exits 0.
- When the environment holds `FAKE_PROBE_JOB_DIR`, `story-server-restore` also records `"job_lock_held"` (whether `flock(jdir/lock, LOCK_EX|LOCK_NB)` raises `BlockingIOError`) and `"job_state"` (`status.json` state) for VL19.

**F-HTTP** (`FakeVLM` in the same file) is a `ThreadingHTTPServer` on `127.0.0.1:0`:
- configurable `models` (a list of dicts), `models_status`, `completion_status`, `completion_body` and `completion_delay`;
- it records `(method, path, json body)` for every request.

**F-SS** (`tests/test_clean_stop.py::_fake_story_server`, rewritten) is a bash script:
- `status` prints `  state:          SERVING mlx-vision` iff `<tmp>/started` exists, else the configured state;
- `lockinfo` prints the content of `<tmp>/lockinfo` if it exists, else `lock: free path=x`;
- any other argument appends `"$1 sid=$(ps -o sess= -p $$) pgid=$(ps -o pgid= -p $$) ppid=$(ps -o ppid= -p $$)"` to `calls.txt`. Unless `lock_delay` is `never`, it then sleeps `lock_delay` seconds (default 0) and writes `lock: held pid=$$ cmd=$1 since=x path=x` to `<tmp>/lockinfo`, which emulates taking the lock. It then sleeps `sleep` seconds, touches `<tmp>/started`, and writes `lock: free path=x` to `<tmp>/lockinfo` before exiting.

### 11.3 New tests

`tests/test_vlm_lifecycle.py`:

| ID | Covers |
|---|---|
| VL1 | `job_vlm`: every row of VP1, including redo, movie with and without story.md, an unknown kind → any |
| VL2 | `create_job` writes `vlm`; compose, character, action, download and smoke jobs created through the HTTP routes carry the VP1 value |
| VL3 | `effective_vlm`: a movie whose story.md appears after submit → forbidden, plus the exact `job.json says` line from `vlm_preflight`; no key → any; `"bogus"` → any |
| VL4 | `next_queued_job` skips heads with a status and heads with a missing job.json |
| VL5 | `vlm_restore_wanted`: all four exact reason strings |
| VL6 | `vlm_health` happy path with F-TOOLS and F-HTTP: `(True, "<model> on 127.0.0.1:<port>")` |
| VL7 | H1-H9: one case each with the exact text (H1 with `status_timeout=1` and a status sleep of 3) |
| VL8 | request shape: exactly one GET `/v1/models` and one POST whose body equals the VR4 object; an H5 failure sends no POST |
| VL9 | preflight required, healthy: calls `[restore mlx-vision --wait]`, health once, `("ok", None)`, the log lines in order |
| VL10 | unhealthy then healthy: calls `[restore --wait, stop, restore --wait]` and the `unhealthy ...; restarting it once` line |
| VL11 | unhealthy twice → `VLM preflight failed after one restart: <H text>` |
| VL12 | restore exits 1 twice → the "after one restart" error with the restore-exit problem; calls `[restore, stop, restore]`; no health call |
| VL13 | forbidden: calls `[stop]`, `vlm: stopped for this job`; `stop_rc=3` → the exact stop error |
| VL14 | any: no calls |
| VL15 | cancel during preflight: `restore_sleep=30`, the cancel marker created after 1 s → `("cancelled", None)` within 8 s, and the fake restore pid is gone |
| VL16 | `timeout=2` with `restore_sleep=30` → `VLM preflight timed out after 2 s` |
| VL17 | end to end through `bin/movie-ui-job` (lifecycle on, F-TOOLS, F-HTTP): a required job → `done`; `[movie-ui] vlm:` preflight lines precede `started pid`; every preflight call `t` is below the child's own recorded `time.time()`; the child records `os.environ.get("STORY_SERVER_ENGINE_SCAN") == "0"`, also with the lifecycle off (VR1) |
| VL18 | e2e preflight failure: the status key set is exactly `{"state", "dispatched", "runner_pid", "pgid", "started", "exit_code", "ended", "error"}`, `pgid` null, runner exit 1, and a postflight restore call without `--wait` |
| VL19 | postflight ordering: the restore call records `job_lock_held is True`, `job_state` final, and `pgid` ≠ the job's recorded `pgid`; the child's group is gone (`group_alive` false) |
| VL20 | postflight decisions: queue empty → restore; next required → restore; next forbidden → no call plus the line; next any → no call plus the line |
| VL21 | VK4: two forbidden jobs run back to back through `dispatch_tick` → calls `[stop, stop, restore]`, the restore after the second job's final status |
| VL22 | VK2: a job's argv is a Python child running the **real** `bin/story-server-restore mlx-vision --wait` with `STORY_SERVER_RESTORE_BIN` = an F-SS variant whose mode call spawns `sleep 60` (pid file) and exits after 3 s. Cancel 1 s in → after the final status the sleeper is alive and its pgid and sid are not in the `cancel: SIGTERM to process group(s)` line. Variant: SIGKILL the runner → `lost` → `kill_orphan` → the sleeper is still alive. Teardown kills it |
| VL23 | VU2: `startup_recovery` with an empty queue → one restore Popen on the next idle tick plus the stderr line; a lost job with a live orphan defers the startup restore until the orphan is gone; next forbidden → the `skipped` line; a `lost` transition after startup and `kill_orphan` queue **nothing** (`VLM_RECOVERY == []`, no Popen) |
| VL24 | lifecycle off: no tool calls from preflight, postflight or recovery; V2 STOPPED → `fail` with the HEAD text |
| VL25 | D7: lifecycle on, STOPPED → `warn` W1 and `POST /api/jobs` 201 carrying it; timeout → W2; exit 4 → `fail` and 409 |
| VL26 | static: `app.js` contains `gate($("#c-write-story"), $("#c-write-story-reason"), []);`; `app.css` contains `.check-warn { color: var(--warn); }` |
| VL27 | `py_compile` under `/usr/bin/python3` and `sys.executable` of `bin/story-server-restore`, `character_dataset.py`, `movie_ui_lib.py`, `tests/test_vlm_lifecycle.py`; `bash -n bin/story-server` |
| VL28 | Q2: required job, restore exits 1, status reports `SERVING vision` → `VLM preflight failed: the story server runs in vision mode, not mlx-vision; stop it with bin/story-server stop and resubmit`; calls `[restore --wait]` plus one status, **no** stop. Same for `LOADING text`. With `FOREIGN pid 5` → the stop-and-restart path runs (`[restore, stop, restore]`) |

`tests/test_story_server.py` (uses `_base_env`):

| ID | Covers |
|---|---|
| VLS1 | `lockinfo`: no file → `lock: free path=<p>`; held by the test process (flock plus record `<pid> stop <ts>`) → the exact held line; released → free |
| VLS2 | a start holds the lock for its whole load: during `STUB_LOAD_DELAY=5`, `lockinfo` shows `pid=<proc1.pid> cmd=vision`; after exit 0 → free |
| VLS3 | VK3: three concurrent `vision` starts → exactly one stub server process; the two others exit 0 with M35 |
| VLS4 | stop preempts a load: M30 with proc1's pid in stdout; stop exits 0; proc1 exits 5 with `interrupted during load` in stderr; no stub left; mode file gone |
| VLS5 | stop waits for a stop: the test holds the lock with record `<own pid> stop <ts>`, `STORY_SERVER_LOCK_TIMEOUT=2` → exit 7 with M33; released after 1 s → stop proceeds and exits 0 |
| VLS6 | PID reuse: the test holds the lock with a record naming `vision` and the test's own pid, whose command lacks `story-server`. `stop` → no M30, no signal, exit 7 (M33). `vision` → no M35 fast path, it waits, exit 7. `text` → no M36, exit 7 |
| VLS7 | the server does not hold the lock: after a successful start, `lockinfo` is free while the stub server still runs |
| VLS8 | VK5 tree: the stub's own child (the stub vllm launches `/usr/bin/python3` as a child) is killed by stop; a test process started as `Popen(["VLLM::EngineCore", "-c", "import time; time.sleep(60)"], executable=sys.executable)` survives |
| VLS9 | an orphan EngineCore (double-forked, ppid 1) survives stop and M31 names its pid |
| VLS10 | a start waits for a stop holder: record `<own pid> stop`, released after 2 s → the start proceeds and spawns |
| VLS11 | source guards: no `engine_pids`, no `ENGINE_SCAN`; exactly 3 spawn lines end in `9>&-`; the warm-up curl has `9>&-`; `lock_take "$MODE"` and `lock_take stop` each appear once |
| VLS12 | unopenable lock: `STORY_SERVER_STATE_DIR=<tmp>/ro/state`, where `<tmp>/ro` is mode 0500 (the test restores 0700 in teardown). `stop` → M37 on stdout, exit 0 (nothing to stop), no lock file. `vision` → M34 on stderr, exit 4, no stub spawned. Skipped when running as root |
| VLS13 | VS10: an in-test HTTP server on the ephemeral port lists `[{"id": "other", "loaded": false}, {"id": "<MLX_VISION_MODEL_ID>", "loaded": true}]`, plus a mode file `mlx-vision <pid of an in-test sleep> <ts>` → `status` reports `state: SERVING mlx-vision` and `model=<MLX_VISION_MODEL_ID>`; without `loaded` flags, `data[0]` is used (the S8 cases unchanged) |

`tests/test_clean_stop.py`:

| ID | Covers |
|---|---|
| VLR1 | double fork: a restore without `--wait` and a fake whose mode call sleeps 5 → recorded `ppid` is 1, sid and pgid ≠ the caller's |
| VLR2 | `--wait` returns 0 after the fake start touches `started`; 1 when the fake never serves |
| VLR3 | in progress: `lockinfo` held with `cmd=mlx-vision` and a live pid (a test `sleep` process) → no mode call; without `--wait` exit 0 plus the exact message; with `--wait` it returns after the sleeper dies and `started` exists |
| VLR4 | held by `stop` → a mode call is made |
| VLR5 | `STORY_SERVER_RESTORE_WAIT_S=2` with a live holder → exit 1 plus the TIMEOUT text |
| VLR6 | source: no `"ps"` or `-axo` in `bin/story-server-restore` |
| VLR7 | already serving → `already serving mlx-vision`, no call (CS5 kept) |
| VLR8 | two concurrent restores against the **real** `bin/story-server` with `_base_env`-style overrides (stub `mlx-vision` python, `STUB_LOAD_DELAY=3`) → exactly one stub server |
| VLR9 | VRS2 step 4, without `--wait`: F-SS `lock_delay=1`, `sleep=30` → the restore returns after ≥1 s and <5 s, and `<tmp>/lockinfo` shows `held` at return. `lock_delay=never`, `sleep=3` → returns when the fake exits (≥3 s, <6 s). `lock_delay=never`, `sleep=30` → returns at the 10 s cap (≥10 s, <13 s). Teardown kills the fakes |

`tests/test_character_tool.py`:

| ID | Covers |
|---|---|
| VLC1 | a successful create calls `restore_story_server(wait=True)` (`server_calls == ["stop", "restore-wait"]`); the source no longer contains `story_server(VLM_SERVE_MODE)`; a restore rc of 1 prints `warning: story-server-restore mlx-vision --wait returned 1` |

### 11.4 Existing tests that change (only for the stated reason)

| Test | Reason |
|---|---|
| `test_movie_ui_jobs.py::test_store_writes_atomically_with_private_modes` (`:65`) | key set adds `"vlm"`; add `assert job["vlm"] == "required"` |
| `test_movie_ui_builder.py::test_mut25_source_scan_of_new_python_files` (`:247-250`) | `allowed` adds `"http.client"` (VU4) |
| `test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` | **separate test-only follow-up commit**: `BASELINE` set to the last feature commit SHA, comment appended ", then to <sha> (VLM lifecycle: character_dataset.py restores via story-server-restore --wait)" |
| `test_story_server.py::test_s1_usage` (`:310`) | usage string adds `|lockinfo` |
| `test_story_server.py::test_s4_s5_idempotence_during_load_and_stop` (`:385-397`) | S5 only. The new assertions: `rc4 == 0`; `"preempting the vision start in progress (story-server pid %d)" % proc1.pid in out4`; `not _pid_alive(mode_pid)`; no mode file; standdown exists; `proc1.returncode == 5` and `"interrupted during load" in err1`. The S4 assertions stay (M35 contains `already running`; M36 contains `REFUSING` and `already running`) |
| `test_story_server.py::test_s14_source_guards` (`:705-724`) | remove `STORY_SERVER_ENGINE_SCAN`; add `"STORY_SERVER_LOCK_TIMEOUT": "1260"`; the six host values become HEAD's (`STORY_SERVER_WS` `/Users/ailab1/local_agent_harness/qwen-agent-workspace`, `STORY_SERVER_VISION_MODEL_DIR` and `STORY_SERVER_MLX_VISION_MODEL_ID` `/Users/ailab1/mlx_models/qwen3-vl`, `STORY_SERVER_VLLM_BIN` `/Users/ailab1/.venv-vllm-metal/bin/vllm`, `STORY_SERVER_STATE_DIR` `/Users/ailab1/.qwen-serve-guard`, `STORY_SERVER_MLX_VLM_PYTHON` `/Users/ailab1/mlx-serve/bin/python`); the count stays 19. Test-only: no host value changes (G5). This **pins the macstudio paths** in the test, so a future host-adapt of the defaults must update S14 in the same commit |
| `test_story_server.py::_base_env` (`:191-195`) | delete the now-dead `STORY_SERVER_ENGINE_SCAN` line and its comment |
| `test_clean_stop.py::_fake_story_server`, `::test_cs4`, `::test_cs6` | F-SS (lockinfo, stateful status, `lock_delay` default 0); CS4 still asserts `own session`, the first word `mlx-vision` and a pgid ≠ the caller's; CS6 keeps `< 4` s, which holds because the default `lock_delay=0` writes `held` at once (VRS2 step 4) |
| `test_character_tool.py::_Fakes` (`:131-132`), `::test_k9`, `::test_k13`, `::test_k20` | fake `lambda wait=False: fakes.server_calls.append("restore-wait" if wait else "restore") or 0`; the asserts become `["stop", "restore-wait"]`. `::test_k21` is unchanged (`["stop", "restore"]`) |

**Must pass unchanged:**
- `test_movie_ui_checks.py::test_mut9_v2_host_checks`, because the lifecycle is off in conftest;
- `test_movie_ui_http.py` capability tests (`:250-261`);
- every MUT10-MUT15 runner test;
- `test_ltx_movie_offline.py` L40-L46;
- `test_story_server.py` S2-S13 and S15-S23 (S22 and S23 pass through M36/M35 and preemption);
- `test_clean_stop.py` CS1-CS3, CS5, CS7;
- `test_movie_ui_builder.py:118-131`.

---

## 12. Amendments to other specs

**[MOVIEUI]:**
- MU15: `vlm` key (2.1).
- MU16: two runner rows (2.2).
- MU22: steps 3b and 7b, plus postflight on the cannot-start and cancel-before-start paths (VR1).
- MU24: exit 1 also covers a preflight failure.
- MU30: the first idle tick after startup runs the startup restore (VU2).
- MU31: startup queues `startup` (VU2).
- MU22 step 4: the child's environment gains `STORY_SERVER_ENGINE_SCAN="0"` (VR1).
- MU42: status `warn`.
- MU44: `warn` records are returned with 201.
- V2 `story server`: VU1.
- **MU60:** the spec choice "[the story server starts and stops outside the UI]" is replaced by "[the job runner starts and stops the story server at job boundaries (VLM lifecycle spec); the page never starts or stops it; the capability probe stays a startup snapshot]".
- Section 16 out-of-scope "starting or stopping the story server ... from the page" still holds for the page.
- GC3: VU4.
- MUT25: the allowlist.
- The page: the write-story gate (VU3).

**[CLEANSTOP]:** S1 is amended so that "a start in progress" is decided by the lock, not `ps`, and the start is detached under launchd (VRS3). `--wait` follows VRS4.

**[SSPLAN]:**
- D9 and R8 (the host-global EngineCore sweep, "accepted") are superseded by VS6.
- R1 is now defended by the lock (VS5).
- D2's "no lock file" is superseded by VS2.

---

## 13. Rollout

1. Record the baseline at HEAD: full-suite pass/fail/skip counts, including the known failures (`test_s14_source_guards` and MUK2's `test_d2_copied_literals_match_the_spike`), and `test_ltx_movie_offline.py`'s `OK n/n`.
2. Feature commit A: G1, G2, VLS*, VLR*, and the 11.4 story-server and clean-stop edits.
3. Feature commit B: G3-G5, G7, `tests/test_vlm_lifecycle.py`, and the 11.4 movie-ui edits.
4. Feature commit C: G6, VLC1, and the 11.4 character-tool edits. Then an Opus design review of A-C against this spec.
5. Test-only commit G10 (the `test_mut26` re-baseline to commit C). Then measure VK6 and VK7.
6. Live on macstudio, run by the user. These steps are manual and not part of the suite.
   - (a) Record the 8178 listener PID.
   - (b) Run, in order:
     - a movie job without story.md, then a story job (F1: the second preflight is healthy);
     - a character create cancelled during the generate→score restore (F2, F3: the VLM ends up SERVING);
     - two concurrent `bin/story-server-restore mlx-vision` (F4: one server);
     - movie-ui stopped, `story-server stop`, movie-ui started (F6: restored);
     - two queued renders (VK4: no reload between them).
   - (c) Confirm the 8178 PID is unchanged.
   - (d) Runtime rollback: set `MOVIE_UI_VLM_LIFECYCLE=0` in the movie-ui environment, then run `bin/movie-ui-stop` and `bin/movie-ui-start`. This disables only VR2, VR5, VU1's warn and VU2. `bin/story-server`, `bin/story-server-restore`, `character_dataset.py`, the `vlm` key, the page gate and the child's `STORY_SERVER_ENGINE_SCAN=0` stay changed. A full rollback reverts commits A and C (`git revert`), and commit B for the movie-ui parts.

---

## 14. Values chosen by the spec

1. The VP1 table, in particular: `smoke` is forbidden; both trains are forbidden (not any); `action-create` and `download` are any; story and regenerate are required unconditionally.
2. Movie jobs are recomputed at dispatch (VP2). A job without `vlm` counts as any. The schema stays v1.
3. The runner uses the UI workspace's tools, not the job's (VR1).
4. A failed restore on the first attempt counts as unhealthy and gets the single stop-and-restart, except when the story server runs in `vision` or `text` mode. A required job then fails and stops nothing (Q2, resolved: conservative).
5. The lock is held for the whole start (incl. warm-up) and the whole stop. Blocking with a 1260 s timeout. Same-mode start → exit 0; other mode → exit 3; stop preempts a start with one SIGTERM. The fast paths and the preempt all require the holder's command to contain `story-server`. An unopenable lock fails a start closed and lets a stop proceed (M37).
6. `lockinfo` is a new subcommand, so `story-server` stays the single owner of the `STATE_DIR` default. The restore never hard-codes `/Users/ailab1`.
7. The restore detaches by double fork. After a launch it waits up to 10 s, polling every 0.2 s, for the start to take the lock. `--wait` then polls only `lockinfo` and `kill -0` every 2 s, capped at 2520 s.
8. Health: status, then models (the loaded entry), then one 1-token completion (120 s). No RSS or listening-pid check, because Metal memory is not in RSS. Exactly one restart.
9. Preflight cap 6900 s; the health check is not polled for cancel. Postflight is non-blocking (restore without `--wait`, 90 s cap) and runs while the job lock is still held.
10. The server-side restore runs once, at the first idle tick after startup. There are no lost or orphan hooks. It is never timer-driven.
11. V2 `down` and `timeout` become `warn` only while the lifecycle is on. The page's write-story gate is removed.
12. **D8 cut.** A login agent would load 22-34 GB at every login, even when the first queued job is a render (it would be preempted at once). It duplicates VU2 for the only consumer in scope (movie-ui), and it moves toward the daemon the user ruled out. RunAtLoad without KeepAlive would also give no restore after a crash, so it adds no coverage that VU2 and preflight lack.
13. Orphaned `VLLM::EngineCore` (ppid 1) processes are reported (M31), never killed.
14. `test_s14` is aligned to HEAD's host defaults (test-only). It now pins the macstudio paths.
16. The runner's child environment always sets `STORY_SERVER_ENGINE_SCAN=0`, protecting 8178 from older releases' stop.
17. `extract_served_id` prefers the `"loaded": true` entry (VS10).
15. An escape hatch, `MOVIE_UI_VLM_LIFECYCLE=0`, doubles as the test isolation switch.

---

## 15. Open risks and questions

### 15.1 Risks

- **R1.** A detached start that cannot take the lock within the restore's 10 s wait (VRS2 step 4) can reach the lock **after** the next forbidden job's preflight stop, and then load during a render. This happens only when it queues behind a stop holder. In the normal case the start holds the lock before its caller continues, and the next forbidden stop preempts it (1.4 step 8). When the race does happen, `bin/ltx-movie`'s avail gate (25 GiB, 1800 s) waits instead of OOMing. Smoke has no gate.
- **R2.** The health completion can overlap a human's `bin/qwen-agent chat` on 8177 (SSPLAN R3).
- **R3.** An orphaned EngineCore of **our** crashed vLLM front end is no longer reaped (port-scoping tradeoff); M31 names it.
- **R4.** Mixed releases. A job whose workspace is an older release runs that release's own `bin/story-server` inside the job (Phase 1b, `character_dataset.py`, the train wrappers). Those stops take no lock. Their host-wide EngineCore sweep is switched off by the runner's child environment `STORY_SERVER_ENGINE_SCAN="0"` (VR1). Every `bin/story-server` since its first commit `6ab72ac` (2026-09-25) honours that variable (`:103`, `:192`), including the only release tag, `v2026.10.20`. Still exposed, because they predate the switch: workspaces built from commits before `6ab72ac`; no tagged release is among them. Independently of releases, `bin/ltx-host-prep`'s unconditional `pkill -f 'VLLM::EngineCore'` (`:27`) still exists, but no movie-ui job runs it (`bin/ltx-movie:30`, `bin/ltx-mlx-render:8`).
- **R5.** The train wrappers reload the VLM (5-14 min) at the end of a train job even when the next job is a render; the next preflight then stops it. It is kept per the brief. Removing it under movie-ui is a recorded follow-up (0.4).
- **R6.** The idle policy "VLM up when the queue drains" loads 22-34 GB after every render queue drains. Any forbidden job preempts it.
- **R7.** PID reuse in the lock record and in the restore's `kill -0` wait. Bounded by the timeouts. A signal or a fast path happens only after the `story-server` command-line check.
- **R8.** A pathological preflight can hold the queue up to 115 min (6900 s), and the job shows `starting` throughout. The tool steps are cancellable within 1 s; a cancel during a health check waits up to 190 s.
- **R9.** On hosts where 8177 runs another story-server mode or vLLM (the dev Mac's chat server), a forbidden preflight stops it if `is_server_pid` matches (as Phase 1b already does). A required preflight fails: through the Q2 rule for `vision` or `text`, else through M09.
- **R10.** The regression M37 prevents. On hosts without `/Users/ailab1` (the dev Mac), `$STATE_DIR` cannot be created, so the lock file cannot be opened. If `stop` failed closed there, every movie render on such a host would fail at Phase 1b: `phase_release_story_server` returns 1 on any non-zero stop (`bin/ltx-movie:1947-1951`), a regression from HEAD, where `stop` works there. So `stop` warns (M37) and proceeds without the lock. Starts still fail closed (M34, exit 4) unless `STORY_SERVER_STATE_DIR` is set. Tests are unaffected (11.1, VLS12).
- **R11.** Delete-with-confirm of a lost job with a live orphan unblocks the queue. The next required job's preflight can then load the VLM beside that orphan render (the user confirmed the delete).
- **R12.** The double-fork launcher exists for milliseconds as a descendant of the caller. A cancel snapshot taken in that instant would include the server's new group.
- **R13.** `story-server status` judges SERVING by the served id. VS10 makes that the `"loaded": true` entry. A listing with no `loaded` flag still falls back to `data[0]`. A wrong first entry then reports FOREIGN, and the preflight stops and restarts once before failing.

### 15.2 Open

- **Q1.** Is `smoke` correctly `forbidden`? It is small (512x320, 9 frames) but loads the full LTX model and gemma. The spec does not depend on the answer.

Resolved by the design review: **Q2.** A required job fails, and stops nothing, when the story server runs in another mode (VR2, VL28). **Q3.** The train wrappers' own `restore --wait` is a follow-up and out of scope (0.4, R5).

---

## 16. Revision 2 changes (design review, verified at 642e5b0)

1. The RSS and listening-pid health steps are removed (VR4). Metal-resident memory is not in `ps` RSS: a healthy server was seen at 227 MB.
2. An unopenable lock lets `stop` proceed with a warning (M37, VLS12, R10).
3. A restore without `--wait` waits up to 10 s for the start to take the lock (VRS2 step 4, VLR9, 1.4 step 8, R1).
4. The child environment sets `STORY_SERVER_ENGINE_SCAN=0` (VR1, VL17, R4).
5. `VLM_PREFLIGHT_TIMEOUT_S = 6900`, and the health check is not polled for cancel (2.5).
6. The escape-hatch scope is stated (2.5, 13(d)).
7. Other fixes:
   - the double fork's reason is stated (VRS3);
   - the fast paths check the holder's command line (VS2, VLS6);
   - `extract_served_id` prefers the loaded entry (VS10, VLS13);
   - only the startup hook of VU2 remains;
   - the fd 9 hold of at most about 10 s is stated (VS7);
   - Q2 and Q3 are resolved;
   - the S14 realignment pins the macstudio paths.
