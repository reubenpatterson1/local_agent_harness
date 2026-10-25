# VLM lifecycle at job boundaries

Date: 2026-10-25 (rev 1)

Status: design spec. One binding user decision (Section 0.1). Every value the decision left open is marked **[spec choice]**, and Section 14 collects them. The implementer makes no design decisions.

Repository: `/Users/reubenpatterson/local_agent_harness`, branch `qwen-agent-redteam`. `WS` is `qwen-agent-workspace/`. Every relative path is relative to `WS`. Line numbers cite the code at HEAD `eeb8b5f`, and each citation was checked there.

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
- **D8. Cut [spec choice].** There is no launchd agent, rationale in 14.1 item 12. Startup recovery (VU2) covers reboot for the movie-ui path.

### 0.2 Grounding (verified at eeb8b5f)

**Failure modes (the brief's citations, re-checked):**

- **F1.** `bin/ltx-movie` stops the VLM after Phase 1 and never restores it. `--story-server-stop-after-story` defaults to True (`:435-445`); `phase_release_story_server` runs `bin/story-server stop` and then waits for `--min-avail-gib` (`:1936-1954`); `_phase_sequence` inserts it after Phase 1 (`:2411-2413`). It is inserted even when Phase 1 is skipped because story.md exists (`:1305-1307`), and then it is harmless. Nothing in the movie-ui restores the VLM afterwards, so the next story or character-create job fails at its own gate (`character_dataset.py:1214-1216`).
- **F2.** `character_dataset.py:1001` restarts the server inline with `story_server(VLM_SERVE_MODE)` (`subprocess.run`, `:476-482`, no new session). The `nohup ... &` inside `bin/story-server` (`:383-388`) therefore puts `mlx_vlm.server` in the **job's** process group. movie-ui `cancel_tree` (`movie_ui_lib.py:278-297`) and `kill_orphan`'s SIGKILL (`:512-520`) kill it.
- **F3.** A SIGTERM during that `:1001` load hits `bin/story-server`'s `on_interrupt`, which kills the half-loaded server (`:402-409`). `bin/character` maps SIGTERM to `KeyboardInterrupt` (`bin/character:141-145`), but the exception arises inside the `finally`'s `else` branch, so `interrupted` is False and no restore runs (`character_dataset.py:994-1006`).
- **F4.** `bin/story-server` has no lock (header `:11-24`: "there is no lock file"). The mode-file check (`:282-297`) and the mode-file write (`:397`) are separated by the preflight, including a seconds-long `import mlx_vlm` probe (`:331`), and by the spawn. Two concurrent starts can both pass the check and spawn two 22-34 GB servers. The `VLLM::EngineCore` sweep is host-wide by design (`:95-103`, `engine_pids` `:190-195`), and `stop` and every kill path add it to the kill set (`:405`, `:431`, `:444`, `:571`). In `mlx-vision` mode no EngineCore is ever ours, so that sweep can only kill **another** vLLM's engine, namely the vllm-metal embed server on 8178. This is the qwen-serve-guard mistake (a machine-wide pgrep killed the 8178 sibling). `bin/story-server-restore` detects a start in progress by scanning `ps` (`:39-52`) and checks before it acts (`:62-79`), so it races.
- **F5.** Server availability is checked only at submit time: V2 `story server` (`movie_ui_lib.py:1078-1094`, needed per `story_needed` `:1120-1124`, inside `host_checks` `:1127-1138`). A failed check makes `POST /api/jobs` answer 409 (`movie_ui_server.py:755-759`). Nothing is checked at dispatch, which can be hours later. The page also disables "Write story" unless the startup capability snapshot said SERVING (`static/movie-ui/app.js:464`).
- **F6.** After a reboot, or a runner that died (`lost`, MU29), nothing restores the VLM.

**Additional findings that shape the design:**

- **G1. `start_new_session` alone does not escape a cancel.** `cancel_tree` signals `descendant_groups(child.pid)`, which is the pgid of **every transitive descendant** by ppid (`movie_ui_lib.py:253-265`), new sessions included (MU23, D1 of [MOVIEUI]). `story-server-restore --wait` keeps its `story-server` child as a descendant while it waits (`bin/story-server-restore:75-79`). A cancel during a waiting restore therefore SIGTERMs the loading server's group, and `on_interrupt` kills the load. The restore must double-fork so that the server's parent is launchd (VRS3).
- **G2.** `--wait` already exists (`bin/story-server-restore:5-12`, `:56`, `:70-72`, `:79`). This spec redefines its semantics (VRS4).
- **G3.** `mlx_vlm.server`'s `/v1/models` lists every cached model and flags the active one with `"loaded": true` (`character_dataset.py:446-463`, `bin/ltx-movie:812-815`). `story-server status` reads only `data[0].id` (`:130-137`, `:498-499`).
- **G4.** The existing contract and its tests require that a second start of the same mode **during a load** exits 0 at once (M05), and that a start of a different mode exits 3 at once (M06). These are `test_story_server.py::test_s4_s5…` (`:361-401`), `::test_s22` (`:1028`) and `::test_s23` (`:996`). The lock keeps both fast paths (VS2).
- **G5.** `tests/test_story_server.py::test_s14_source_guards` **fails at HEAD**. Commit `439eb1d` host-adapted the defaults to `/Users/ailab1/...` (`bin/story-server:35`, `:41-42`, `:63-64`, `:77`), but the test still expects `/Users/reubenpatterson/...` (`:705-724`). It is a pre-existing baseline failure.
- **G6.** `movie_ui_lib.py`'s import allowlist is pinned by `tests/test_movie_ui_builder.py:244-252`, and GC3 requires `http.client` for HTTP, never `urllib` (`:230`).
- **G7.** `bin/character-train-vlm` (`:17-40`) and `bin/action-train-vlm` (`:16-39`) already stop, train, then restore. They stay unchanged.
- **G8.** `bin/pipeline-stop` never signals the story server (`NEVER`, `:40`) and finishes with `story-server-restore --wait`.
- **G9.** Host defaults. `bin/story-server`'s defaults name the macstudio host (`/Users/ailab1/...`, `:35-77`). This spec changes no host value. Tests isolate the host through the `STORY_SERVER_*` environment variables (`tests/test_story_server.py:161-195`), `STORY_SERVER_RESTORE_BIN` plus a temporary `HOME` (`tests/test_clean_stop.py:63-81`), and the new `MOVIE_UI_VLM_*` variables (11.1).

### 0.3 Deliverables

| # | File | Change |
|---|---|---|
| G1 | `bin/story-server` | lock (VS1-VS3, VS5), `lockinfo` (VS4), port-owner tree instead of the EngineCore sweep (VS6), fd hygiene (VS7), header and usage (VS8, VS9) |
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
- Removing the train wrappers' own restore (risk R6).

### 0.5 Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| VK1 | **No job starts with the VLM in the wrong state.** A `required` job's child is started only after a health check that passed in the same preflight. A `forbidden` job's child is started only after `story-server stop` exited 0 in the same preflight. | VL10-VL15, VL18 (call timestamps are earlier than the child's start marker) |
| VK2 | **Cancel and kill never kill the server.** A VLM start launched by a job (via `story-server-restore`, with or without `--wait`) survives `cancel_tree` and `kill_orphan`. The server's pgid and sid are in none of the groups the runner signals. | VL23, VLR1 |
| VK3 | **Never two servers.** With N=3 concurrent starts (same mode, no mode file yet) or 2 concurrent restores, exactly one stub server process exists. | VLS3, VLR8 |
| VK4 | **Back-to-back renders don't reload.** Two queued `forbidden` jobs give exactly `[stop, stop]` with no restore between them, then one restore after the second (queue empty). | VL22 |
| VK5 | **Port scoping.** `story-server stop` never signals a process outside the port-owner tree, the mode-file pid's tree and the port's `serve` argv matches. A `VLLM::EngineCore` outside that tree survives. | VLS8, VLS9 |
| VK6 | `python3 -m pytest tests/ -q -rA` from `WS` shows the pass count recorded just before implementation, plus every new test, plus the 11.4 edits, with no lost pass. `test_s14_source_guards` moves from fail to pass. `python3 tests/test_ltx_movie_offline.py` prints `OK n/n` with the baseline `n`. Measured after the G10 commit. | full run |
| VK7 | `/usr/bin/python3` (3.9.6) and `python3` (3.13) both `py_compile` every changed Python file. `bash -n bin/story-server` passes, and `/bin/bash` 3.2 runs the VLS tests. | VL28, MUT25 |
| VK8 | Live (macstudio, Section 13 step 6): each of the six F-scenarios is shown fixed, and the PID listening on 8178 is unchanged across every step. | live protocol |

### 0.6 Must-have and nice-to-have

Sections 2-8 are must-haves. Nice-to-have, **not built**: a `vlm` column in the jobs page; a preflight phase in the progress parser; a launchd agent (cut, D8).

---

## 1. Architecture

### 1.1 Owners

- `bin/story-server` is the only process that spawns or kills a VLM server on its port. Its flock serializes every start and stop on the host.
- `bin/story-server-restore` is the only "bring it back" entry point. It never spawns a server itself; it detaches a `story-server <mode>`.
- The movie-ui runner decides the state at the boundaries (preflight before the child, postflight after). The movie-ui server decides only after a runner was lost, at startup, and after a killed orphan (VU2).
- Job-internal transitions stay where they are: Phase 1b in `bin/ltx-movie`, the generate phase in `character_dataset.py`, and the train wrappers.

### 1.2 VLM states

| State | Lock (`lockinfo`) | Mode file | Port 8177 | `story-server status` |
|---|---|---|---|---|
| STOPPED | free | absent | free | `STOPPED` |
| LOADING | held, `cmd=mlx-vision` | `mlx-vision <pid> <ts>` | free | `LOADING mlx-vision` |
| WARMING | held, `cmd=mlx-vision` | present | bound | `SERVING mlx-vision` |
| SERVING | free | present | bound, healthy | `SERVING mlx-vision` |
| HUNG | free | present | bound; `/v1/models` or completion fails, or RSS below 50% of the weights | `FOREIGN pid N` or `SERVING mlx-vision` |
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
8. The runner exits, which releases the lock. The next dispatch can happen only after this point, so the next preflight always observes the effects of this postflight (a load in progress is visible through `lockinfo`).

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
| `MOVIE_UI_VLM_LIFECYCLE` | movie_ui_lib | `"1"` | `"0"` disables VR2, VR5, VU1's warn and VU2; the behaviour is then byte-for-byte HEAD (tests, and a rollback switch) |
| `MOVIE_UI_VLM_TOOLS` | movie_ui_lib | `<UI WS>/bin` | the directory holding `story-server` and `story-server-restore` |
| `MOVIE_UI_VLM_PORT` | movie_ui_lib | `8177` | the health-check port (tests use an ephemeral one) |

`movie_ui_lib` constants: `VLM_MODE = "mlx-vision"`, `VLM_POLICIES = ("required", "forbidden", "any")`, `VLM_STATUS_TIMEOUT_S = 60`, `VLM_HTTP_TIMEOUT_S = 10`, `VLM_COMPLETION_TIMEOUT_S = 120`, `VLM_RSS_MIN_FRACTION = 0.5`, `VLM_PREFLIGHT_TIMEOUT_S = 5400`, `VLM_POSTFLIGHT_TIMEOUT_S = 90`, `VLM_TOOL_KILL_WAIT_S = 5`, `VLM_MAX_BODY = 1048576`, `VLM_RESTORE_LOG_TEXT = "~/.local/share/qwen-agent/story-server-restore.log"`, `VLM_RECOVERY = []` (pending recovery reasons, server process only), `RESTORERS = []` (Popen objects, polled to reap them, like `RUNNERS`).

**Timeout justifications:**
- `LOCK_TIMEOUT` 1260 s covers the longest legitimate hold: a start's readiness poll (`READY_TIMEOUT` 840 s, `:87`), plus warm-up (`WARM_TIMEOUT` 300 s, `:90`), plus one `kill_set` (60 + 10 s, `:92-93`), plus 50 s of probe slack.
- `RESTORE_WAIT_S` 2520 s is one full lock wait (1260) plus one full start (840 + 300 + 70 = 1210), rounded up to 42 min. A normal 5-14 min load plus up to 5 min of warm-up fits with margin. A load queued behind another load also fits.
- `VLM_PREFLIGHT_TIMEOUT_S` 5400 s covers two `restore --wait` (2 × 2520), two health checks (about 200 s each, bounded by their timeouts) and one stop. It is a hard cap for pathological cases only, and preflight is cancellable throughout.
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
    _say("vlm: unhealthy: %s; restarting it once" % problem)
    outcome, value = _vlm_step(stop, cancel, deadline, timeout)
    if outcome != "exit":
        return outcome, value
    if value != 0:
        return "failed", ("VLM preflight failed: bin/story-server stop exited %d; the log above "
                          "shows why" % value)
```

A restore that exits non-zero is treated like a failed health check on the first attempt **[spec choice]**. This also covers a different-mode server (`vision`/`text`, M36/M06 refusal): the stop clears it and the restart starts `mlx-vision`.

### VR3. `_vlm_step(argv, cancel, deadline, timeout)`

Returns `("exit", rc)`, `("cancelled", None)` or `("failed", <error>)`.
1. `_say("vlm: running: %s" % shlex.join(argv))`.
2. `subprocess.Popen(argv, stdin=subprocess.DEVNULL, close_fds=True)`. stdout and stderr are inherited (the runner's stdout is `log.txt`, MU21). There is no new session. An `OSError` returns `("failed", "VLM preflight failed: cannot run %s: %s" % (argv[0], e.strerror or e))`.
3. Loop on `proc.wait(timeout=1)`. On `TimeoutExpired`:
   - if `cancel` exists, call `_stop_tool(proc)` and return `("cancelled", None)`;
   - if `time.monotonic() >= deadline`, call `_stop_tool(proc)` and return `("failed", "VLM preflight timed out after %d s" % timeout)`.
4. Return `("exit", proc.returncode)`.

`_stop_tool(proc)`: `proc.terminate()`; `proc.wait(VLM_TOOL_KILL_WAIT_S)`; on `TimeoutExpired`, `proc.kill()` and then `proc.wait()`. Terminating a waiting `story-server-restore` leaves the detached load running (VRS3). Terminating a `story-server stop` mid-way is acceptable, because the next preflight re-establishes the state.

### VR4. `vlm_health(tools, port, listen_pid_fn=None, rss_fn=None, weights_fn=None, status_timeout=VLM_STATUS_TIMEOUT_S, http_timeout=VLM_HTTP_TIMEOUT_S, completion_timeout=VLM_COMPLETION_TIMEOUT_S)`

Returns `(ok, detail)`. The defaults are `vlm_listen_pid`, `vlm_rss_bytes` and `vlm_weights_bytes`. The steps run in this order, and the first failure returns `(False, <H text>)`. There are no retries, and exactly one HTTP request of each kind is sent.

1. **Status.** `run = run_light([os.path.join(tools, "story-server"), "status"], tools, timeout=status_timeout)`.
   - `run["timed_out"]` → H1.
   - `run["exit_code"] != 0` → H2.
   - `state` is the first `STATE_LINE_RE` match; a missing match counts as `UNKNOWN`. `state != "SERVING mlx-vision"` → H3.
   - `model` is the first match of `HEALTH_LINE_RE = re.compile(r"^\s*health:\s*HTTP\s+\d{3}\s+model=(.+?)\s*$")`. No match, or `none` → H12.
2. **Models.** `http.client.HTTPConnection("127.0.0.1", port, timeout=http_timeout)`, `GET /v1/models`, read at most `VLM_MAX_BODY` bytes.
   - A non-200 status, a JSON decode error, a body that is not an object holding a list `data`, or any `OSError`/`http.client.HTTPException` → H4. `<what>` is `HTTP <n>`, `invalid JSON`, or the exception class name.
   - `entries = [d for d in data if isinstance(d, dict) and d.get("id") == model]`. Empty → H5.
   - `"loaded" in entries[0] and entries[0]["loaded"] is not True` → H6.
3. **Listener.** `pid = listen_pid_fn(port)`. `None` → H7.
4. **RSS.**
   - If `VLM_RSS_MIN_FRACTION == 0`, set `rss_note = "rss check disabled"`.
   - Else `weights = weights_fn(model)`. If it is `0`, set `rss_note = "rss check skipped: no *.safetensors in %s" % model`.
   - Else `rss = rss_fn(pid)`. `None` → H8. `rss < VLM_RSS_MIN_FRACTION * weights` → H9. Otherwise `rss_note = "rss %.1f GiB of %.1f GiB weights" % (rss / 2**30, weights / 2**30)`.
5. **Completion.** A new connection with `timeout=completion_timeout`. `POST /v1/chat/completions` with header `Content-Type: application/json` and body `json.dumps({"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "Reply with the single word ok"}]})`. A non-200 status, a JSON error or an exception → H10. A body that is not an object with a non-empty list `choices` → H11.
6. Return `(True, "%s on 127.0.0.1:%d (pid %d; %s)" % (model, port, pid, rss_note))`.

RSS runs before the completion **[spec choice]**, so a collapsed server is caught without sending it inference.

The health check is called **only** from VR2. No timer calls it.

**Listening-port lookup [spec choice]:** `vlm_listen_pid(port)` runs `run_light(["/usr/sbin/lsof", "-nP", "-iTCP:%d" % port, "-sTCP:LISTEN", "-t"], "/", timeout=10)` and returns the int of the first all-digit stdout line, else `None`. The stdlib has no port-to-pid API on macOS. psutil is barred from `movie_ui_lib` (GC2). A ctypes `libproc` walk would be fragile struct-layout code. `/usr/sbin/lsof` is already a hard dependency of `bin/story-server` (M02, `:668-671`), and this invocation is identical to its `port_pids` (`:161`), so both tools agree on the owner.

`vlm_rss_bytes(pid)` runs `run_light(["/bin/ps", "-o", "rss=", "-p", str(pid)], "/", timeout=10)` and returns `int(stripped stdout) * 1024`, or `None` on a non-zero exit or a non-integer.

`vlm_weights_bytes(model)`:
- `0` unless `os.path.isdir(model)`;
- else the sum of `os.path.getsize(p)` for each name in `sorted(os.listdir(model))` ending in `.safetensors` where `p = os.path.join(model, name)` and `os.path.isfile(p)` (symlinks followed);
- `OSError` → `0`.

**RSS fraction 0.5 [spec choice]:** a healthy MLX server holds every weight resident after its warm-up, so its ratio is near 1.0. A hung vllm-metal/mlx server shows a collapsed RSS (the recorded incident). 0.5 leaves margin both ways. It is gated by a live measurement before rollout (Section 13 step 6a, risk R1).

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

A restore without `--wait` returns within about 1 s, after at most one `lockinfo` and one `status` (VRS2). The runner therefore holds `jdir/lock` only briefly.

**It never runs twice for one end.** The runner's postflight is the only automatic restore for a job that ended under its runner. VU2 fires only for `lost` jobs, at startup, and after a killed orphan. Any duplicate is a no-op through the lock (VRS2 step 1).

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

### VU2. Recovery restore (F6; amends MU29-MU31, MU68)

- `_vlm_recheck(reason)` appends `reason` to `VLM_RECOVERY` only when `vlm_lifecycle_enabled()`.
- It is called:
  - at the end of `startup_recovery` with `"startup"`;
  - in `job_alive`, right after it writes the `lost` status, with `"job %s lost" % os.path.basename(jdir)`;
  - in `kill_orphan`, after the `killpg` (sent, or `ProcessLookupError`), with `"orphan of job %s killed" % job_id`.
- `dispatch_tick`: after the active-job loop and the orphan loop (both unchanged, so it is reached only when nothing is active and no live orphan exists), and before the queue loop:

  ```python
  if VLM_RECOVERY:
      reason = "; ".join(VLM_RECOVERY)
      del VLM_RECOVERY[:]
      recovery_restore(state, ui_ws, reason)
  ```
- `recovery_restore(state, ui_ws, reason)`:
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

Delete the `ENGINE_SCAN` comment and assignment (`:95-103`) and `engine_pids` (`:190-195`).

### VS2. `lock_take CMD` (new helper, after `add_pid`)

```bash
# Takes the exclusive story-server lock for CMD and keeps it on fd 9 until this script exits
# (VLM lifecycle spec VS2). Exits the script itself on the fast paths (0: same-mode start already
# running; 3: other-mode start running), on timeout (7) and when the lock file cannot be opened (4).
lock_take() {
    /bin/mkdir -p "$STATE_DIR" 2>/dev/null
    if ! { : >>"$LOCK_FILE"; } 2>/dev/null; then
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
    if alive and held in SERVE and cmd in SERVE:
        if held == cmd:
            say("a %s start (story-server pid %s) is already running; it may still be loading -- poll %s" % (cmd, pid_text, url))
            sys.exit(20)
        say("REFUSING: a %s start (story-server pid %s) is already running; run \"story-server stop\" first, then start %s" % (held, pid_text, cmd), err=True)
        sys.exit(3)
    if alive and held in SERVE and cmd == "stop" and preempted != pid:
        try:
            line = subprocess.run(["/bin/ps", "-ww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            line = ""
        if "story-server" in line:
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
- A start that finds a live start of the **same** mode exits 0 (G4, M05 contract). A start that finds a live start of **another** mode exits 3 (M06 contract).
- A stop that finds a live start sends it SIGTERM once, provided its command line contains `story-server` (never a foreign pid). The start's `on_interrupt` (`:402-409`) kills the half-loaded server, or bash dies by default action before the spawn or after `:449`. The stop then waits.
- Every other contention (stop vs stop, start vs stop, an unknown or dead holder) waits up to `LOCK_TIMEOUT`.

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

The server never inherits the lock. A story-server killed during warm-up releases the lock at once.

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

### VS9. Usage and dispatch

- M01 becomes `usage: story-server [vision|text|mlx-vision|status|stop|lockinfo]`.
- The argument check (`:655-657`) accepts `lockinfo`.
- `case` gains `lockinfo) cmd_lockinfo ;;`.
- No literal `8177` is added (S14). The new code uses no bash-4 features.

---

## 7. `bin/story-server-restore` (VRS)

### VRS1. Constants

Keep `BIN`, `STORY_SERVER` and `LOG`. Add:

```python
WAIT_S = int(os.environ.get("STORY_SERVER_RESTORE_WAIT_S", "2520"))
POLL_S = 2
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
4. Print `story-server-restore: starting story-server <mode> (pid <pid>, own session); log: <LOG>` (flush). Return `wait_done(mode, pid)` with `--wait`, else `0`.

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

> Does nothing (exit 0) when MODE is already serving. When `story-server lockinfo` shows a live MODE start holding the lock it starts nothing, and with --wait it waits for that start. Otherwise it launches `story-server MODE` through a launcher that exits at once, so the server's parent is launchd and no job's cancel or orphan kill can reach it (VLM lifecycle spec VRS3). --wait blocks, polling only the lock and the started pid, until no MODE start is running (at most STORY_SERVER_RESTORE_WAIT_S, default 2520 s), then exits 0 iff `story-server status` reports SERVING MODE.

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
- The train wrappers: kept per the brief. Their final restore is redundant with postflight, but harmless through the lock (R6).
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
| H7 | `no process listens on 127.0.0.1:<port>` |
| H8 | `cannot read the RSS of pid <pid>` |
| H9 | `pid <pid> RSS <r> GiB is below 50% of the <w> GiB weights (a hung server)`. The `%.1f` formatting is used; 50 is `int(VLM_RSS_MIN_FRACTION * 100)` |
| H10 | `completion failed: <HTTP n\|invalid JSON\|ExcName>` |
| H11 | `completion reply has no choices` |
| H12 | `bin/story-server status printed no served model` |

The "restore exited" problem text is `bin/story-server-restore mlx-vision --wait exited <n> (see ~/.local/share/qwen-agent/story-server-restore.log)`.

V2 warn texts (W1, W2) are in VU1. Server stderr lines are in VU2.

---

## 11. Tests

### 11.1 Isolation

- `tests/conftest.py` gains an autouse fixture, `vlm_lifecycle_isolation(monkeypatch, tmp_path)`. It sets `MOVIE_UI_VLM_LIFECYCLE=0`, `MOVIE_UI_VLM_TOOLS=<tmp_path>/no-vlm-tools` (nonexistent) and `MOVIE_UI_VLM_PORT=9`. With it, every existing test sees HEAD behaviour, and no test can reach the real `bin/story-server`. Runner subprocesses inherit the variables.
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
- When the environment holds `FAKE_PROBE_JOB_DIR`, `story-server-restore` also records `"job_lock_held"` (whether `flock(jdir/lock, LOCK_EX|LOCK_NB)` raises `BlockingIOError`) and `"job_state"` (`status.json` state) for VL20.

**F-HTTP** (`FakeVLM` in the same file) is a `ThreadingHTTPServer` on `127.0.0.1:0`:
- configurable `models` (a list of dicts), `models_status`, `completion_status`, `completion_body` and `completion_delay`;
- it records `(method, path, json body)` for every request.

**F-SS** (`tests/test_clean_stop.py::_fake_story_server`, rewritten) is a bash script:
- `status` prints `  state:          SERVING mlx-vision` iff `<tmp>/started` exists, else the configured state;
- `lockinfo` prints the content of `<tmp>/lockinfo` if it exists, else `lock: free path=x`;
- any other argument appends `"$1 sid=$(ps -o sess= -p $$) pgid=$(ps -o pgid= -p $$) ppid=$(ps -o ppid= -p $$)"` to `calls.txt`, sleeps `sleep` seconds, then touches `<tmp>/started`.

### 11.3 New tests

`tests/test_vlm_lifecycle.py`:

| ID | Covers |
|---|---|
| VL1 | `job_vlm`: every row of VP1, including redo, movie with and without story.md, an unknown kind → any |
| VL2 | `create_job` writes `vlm`; compose, character, action, download and smoke jobs created through the HTTP routes carry the VP1 value |
| VL3 | `effective_vlm`: a movie whose story.md appears after submit → forbidden, plus the exact `job.json says` line from `vlm_preflight`; no key → any; `"bogus"` → any |
| VL4 | `next_queued_job` skips heads with a status and heads with a missing job.json |
| VL5 | `vlm_restore_wanted`: all four exact reason strings |
| VL6 | `vlm_health` happy path with F-TOOLS, F-HTTP, `listen_pid_fn=lambda p: 4242`, `rss_fn=lambda pid: 30 * 2**30`, `weights_fn=lambda m: 34 * 2**30`: `(True, "<model> on 127.0.0.1:<port> (pid 4242; rss 30.0 GiB of 34.0 GiB weights)")` |
| VL7 | H1-H12: one case each with the exact text (H1 with `status_timeout=1` and a status sleep of 3) |
| VL8 | request shape: exactly one GET `/v1/models` and one POST whose body equals the VR4 object; RSS failure (H9) sends no POST |
| VL9 | RSS boundary: `rss == 0.5 * weights` → ok; one byte less → H9; weights 0 → "rss check skipped: no *.safetensors in <model>"; `monkeypatch VLM_RSS_MIN_FRACTION = 0` → "rss check disabled"; `vlm_weights_bytes` sums only top-level `*.safetensors` (with a symlink) |
| VL10 | preflight required, healthy: calls `[restore mlx-vision --wait]`, health once, `("ok", None)`, the log lines in order |
| VL11 | unhealthy then healthy: calls `[restore --wait, stop, restore --wait]` and the `unhealthy ...; restarting it once` line |
| VL12 | unhealthy twice → `VLM preflight failed after one restart: <H text>` |
| VL13 | restore exits 1 twice → the "after one restart" error with the restore-exit problem; calls `[restore, stop, restore]`; no health call |
| VL14 | forbidden: calls `[stop]`, `vlm: stopped for this job`; `stop_rc=3` → the exact stop error |
| VL15 | any: no calls |
| VL16 | cancel during preflight: `restore_sleep=30`, the cancel marker created after 1 s → `("cancelled", None)` within 8 s, and the fake restore pid is gone |
| VL17 | `timeout=2` with `restore_sleep=30` → `VLM preflight timed out after 2 s` |
| VL18 | end to end through `bin/movie-ui-job` (lifecycle on, F-TOOLS, F-HTTP, model = a tmp dir with no safetensors; skipped when `/usr/sbin/lsof` is absent): a required job → `done`; `[movie-ui] vlm:` preflight lines precede `started pid`; every preflight call `t` is below the child's own recorded `time.time()` |
| VL19 | e2e preflight failure: the status key set is exactly `{"state", "dispatched", "runner_pid", "pgid", "started", "exit_code", "ended", "error"}`, `pgid` null, runner exit 1, and a postflight restore call without `--wait` |
| VL20 | postflight ordering: the restore call records `job_lock_held is True`, `job_state` final, and `pgid` ≠ the job's recorded `pgid`; the child's group is gone (`group_alive` false) |
| VL21 | postflight decisions: queue empty → restore; next required → restore; next forbidden → no call plus the line; next any → no call plus the line |
| VL22 | VK4: two forbidden jobs run back to back through `dispatch_tick` → calls `[stop, stop, restore]`, the restore after the second job's final status |
| VL23 | VK2: a job's argv is a Python child running the **real** `bin/story-server-restore mlx-vision --wait` with `STORY_SERVER_RESTORE_BIN` = an F-SS variant whose mode call spawns `sleep 60` (pid file) and exits after 3 s. Cancel 1 s in → after the final status the sleeper is alive and its pgid and sid are not in the `cancel: SIGTERM to process group(s)` line. Variant: SIGKILL the runner → `lost` → `kill_orphan` → the sleeper is still alive. Teardown kills it |
| VL24 | VU2: `startup_recovery` with an empty queue → one restore Popen plus the stderr line; a lost job → restore on the next idle tick; a live orphan defers it until `kill_orphan`; next forbidden → the `skipped` line |
| VL25 | lifecycle off: no tool calls from preflight, postflight or recovery; V2 STOPPED → `fail` with the HEAD text |
| VL26 | D7: lifecycle on, STOPPED → `warn` W1 and `POST /api/jobs` 201 carrying it; timeout → W2; exit 4 → `fail` and 409 |
| VL27 | static: `app.js` contains `gate($("#c-write-story"), $("#c-write-story-reason"), []);`; `app.css` contains `.check-warn { color: var(--warn); }` |
| VL28 | `py_compile` under `/usr/bin/python3` and `sys.executable` of `bin/story-server-restore`, `character_dataset.py`, `movie_ui_lib.py`, `tests/test_vlm_lifecycle.py`; `bash -n bin/story-server` |

`tests/test_story_server.py` (uses `_base_env`):

| ID | Covers |
|---|---|
| VLS1 | `lockinfo`: no file → `lock: free path=<p>`; held by the test process (flock plus record `<pid> stop <ts>`) → the exact held line; released → free |
| VLS2 | a start holds the lock for its whole load: during `STUB_LOAD_DELAY=5`, `lockinfo` shows `pid=<proc1.pid> cmd=vision`; after exit 0 → free |
| VLS3 | VK3: three concurrent `vision` starts → exactly one stub server process; the two others exit 0 with M35 |
| VLS4 | stop preempts a load: M30 with proc1's pid in stdout; stop exits 0; proc1 exits 5 with `interrupted during load` in stderr; no stub left; mode file gone |
| VLS5 | stop waits for a stop: the test holds the lock with record `<own pid> stop <ts>`, `STORY_SERVER_LOCK_TIMEOUT=2` → exit 7 with M33; released after 1 s → stop proceeds and exits 0 |
| VLS6 | no foreign signal: the record names `vision` with the test's own pid (whose command lacks `story-server`) → no M30 and no signal; exit 7 |
| VLS7 | the server does not hold the lock: after a successful start, `lockinfo` is free while the stub server still runs |
| VLS8 | VK5 tree: the stub's own child (the stub vllm launches `/usr/bin/python3` as a child) is killed by stop; a test process started as `Popen(["VLLM::EngineCore", "-c", "import time; time.sleep(60)"], executable=sys.executable)` survives |
| VLS9 | an orphan EngineCore (double-forked, ppid 1) survives stop and M31 names its pid |
| VLS10 | a start waits for a stop holder: record `<own pid> stop`, released after 2 s → the start proceeds and spawns |
| VLS11 | source guards: no `engine_pids`, no `ENGINE_SCAN`; exactly 3 spawn lines end in `9>&-`; the warm-up curl has `9>&-`; `lock_take "$MODE"` and `lock_take stop` each appear once |

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
| `test_story_server.py::test_s14_source_guards` (`:705-724`) | remove `STORY_SERVER_ENGINE_SCAN`; add `"STORY_SERVER_LOCK_TIMEOUT": "1260"`; the six host values become HEAD's (`STORY_SERVER_WS` `/Users/ailab1/local_agent_harness/qwen-agent-workspace`, `STORY_SERVER_VISION_MODEL_DIR` and `STORY_SERVER_MLX_VISION_MODEL_ID` `/Users/ailab1/mlx_models/qwen3-vl`, `STORY_SERVER_VLLM_BIN` `/Users/ailab1/.venv-vllm-metal/bin/vllm`, `STORY_SERVER_STATE_DIR` `/Users/ailab1/.qwen-serve-guard`, `STORY_SERVER_MLX_VLM_PYTHON` `/Users/ailab1/mlx-serve/bin/python`); the count stays 19. Test-only: no host value changes (G5) |
| `test_story_server.py::_base_env` (`:191-195`) | delete the now-dead `STORY_SERVER_ENGINE_SCAN` line and its comment |
| `test_clean_stop.py::_fake_story_server`, `::test_cs4`, `::test_cs6` | F-SS (lockinfo, stateful status); CS4 still asserts `own session`, the first word `mlx-vision` and a pgid ≠ the caller's |
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
- MU30: idle ticks run the pending recovery restore (VU2).
- MU31: startup queues `startup` (VU2).
- MU42: status `warn`.
- MU44: `warn` records are returned with 201.
- V2 `story server`: VU1.
- **MU60:** the spec choice "[the story server starts and stops outside the UI]" is replaced by "[the job runner starts and stops the story server at job boundaries (VLM lifecycle spec); the page never starts or stops it; the capability probe stays a startup snapshot]".
- MU68: kill-orphan queues a recovery restore.
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
   - (a) With the VLM serving, compare `ps -o rss= -p $(/usr/sbin/lsof -nP -iTCP:8177 -sTCP:LISTEN -t)` ×1024 with the sum of `*.safetensors` sizes under `/Users/ailab1/mlx_models/qwen3-vl`. If the ratio is below 0.8, set `VLM_RSS_MIN_FRACTION = 0.0` in a follow-up commit, which disables the RSS sub-check. Otherwise keep 0.5.
   - (b) Record the 8178 listener PID.
   - (c) Run, in order:
     - a movie job without story.md, then a story job (F1: the second preflight is healthy);
     - a character create cancelled during the generate→score restore (F2, F3: the VLM ends up SERVING);
     - two concurrent `bin/story-server-restore mlx-vision` (F4: one server);
     - movie-ui stopped, `story-server stop`, movie-ui started (F6: restored);
     - two queued renders (VK4: no reload between them).
   - (d) Confirm the 8178 PID is unchanged.
   - (e) Rollback is `MOVIE_UI_VLM_LIFECYCLE=0` in the movie-ui environment, then `bin/movie-ui-stop` and `bin/movie-ui-start`.

---

## 14. Values chosen by the spec

1. The VP1 table, in particular: `smoke` is forbidden; both trains are forbidden (not any); `action-create` and `download` are any; story and regenerate are required unconditionally.
2. Movie jobs are recomputed at dispatch (VP2). A job without `vlm` counts as any. The schema stays v1.
3. The runner uses the UI workspace's tools, not the job's (VR1).
4. A failed restore on the first attempt counts as unhealthy and gets the single stop-and-restart. A different-mode story server is therefore stopped by a required job.
5. The lock is held for the whole start (incl. warm-up) and the whole stop. Blocking with a 1260 s timeout. Same-mode start → exit 0; other mode → exit 3; stop preempts a start with one SIGTERM (only a pid whose command contains `story-server`).
6. `lockinfo` is a new subcommand, so `story-server` stays the single owner of the `STATE_DIR` default. The restore never hard-codes `/Users/ailab1`.
7. The restore detaches by double fork; `--wait` polls only `lockinfo` and `kill -0` every 2 s, capped at 2520 s.
8. Health: status, then models, then listener (lsof), then RSS (0.5 × top-level safetensors bytes), then one 1-token completion (120 s). Exactly one restart.
9. Preflight cap 5400 s. Postflight is non-blocking (restore without `--wait`, 90 s cap) and runs while the job lock is still held.
10. Recovery restore runs from `dispatch_tick` when idle, triggered only by startup, a lost job or a killed orphan. It is never timer-driven, because a reason must be pending.
11. V2 `down` and `timeout` become `warn` only while the lifecycle is on. The page's write-story gate is removed.
12. **D8 cut.** A login agent would load 22-34 GB at every login, even when the first queued job is a render (it would be preempted at once). It duplicates VU2 for the only consumer in scope (movie-ui), and it moves toward the daemon the user ruled out. RunAtLoad without KeepAlive would also give no restore after a crash, so it adds no coverage that VU2 and preflight lack.
13. Orphaned `VLLM::EngineCore` (ppid 1) processes are reported (M31), never killed.
14. `test_s14` is aligned to HEAD's host defaults (test-only).
15. An escape hatch, `MOVIE_UI_VLM_LIFECYCLE=0`, doubles as the test isolation switch.

---

## 15. Open risks and questions

### 15.1 Risks

- **R1.** RSS accounting for MLX/Metal. If `ps rss` does not count the Metal-resident weights for `mlx_vlm.server`, every required preflight fails H9 twice. Mitigation: the step 6a measurement gate, `VLM_RSS_MIN_FRACTION = 0.0` disables the sub-check, and `MOVIE_UI_VLM_LIFECYCLE=0` is the rollback.
- **R2.** A restore detached inside a job just before it ended (the character interrupt path, the train wrappers' signal path) can reach the lock **after** the next forbidden job's preflight stop, and then load during a render. The window is milliseconds (job exit, postflight, dispatch tick ≥1 s, runner start). `bin/ltx-movie`'s avail gate (25 GiB, 1800 s) then waits instead of OOMing. Smoke has no gate.
- **R3.** The health completion can overlap a human's `bin/qwen-agent chat` on 8177 (SSPLAN R3).
- **R4.** An orphaned EngineCore of **our** crashed vLLM front end is no longer reaped (port-scoping tradeoff); M31 names it.
- **R5.** Mixed releases. A job's own workspace (an older release) runs its own `bin/story-server` inside the job (Phase 1b, `character_dataset.py`). Until old releases are pruned, those stops take no lock and still sweep EngineCore host-wide.
- **R6.** The train wrappers reload the VLM (5-14 min) at the end of a train job even when the next job is a render; the next preflight then stops it. It is kept per the brief. A follow-up could skip the wrapper restore under movie-ui.
- **R7.** The idle policy "VLM up when the queue drains" loads 22-34 GB after every render queue drains. Any forbidden job preempts it.
- **R8.** PID reuse in the lock record and in the restore's `kill -0` wait. Bounded by the timeouts, and signals are sent only after a `story-server` command check.
- **R9.** A pathological preflight can hold the queue up to 90 min. It is cancellable, and the job then shows `starting`.
- **R10.** On hosts where 8177 runs another story-server mode or vLLM (the dev Mac's chat server), a forbidden preflight stops it if `is_server_pid` matches (as Phase 1b already does), and a required preflight fails (M09).
- **R11.** On hosts without `/Users/ailab1` (the dev Mac), the real `story-server` now exits 4 (M34) unless `STORY_SERVER_STATE_DIR` is set. Today it half-works there. Tests are unaffected (11.1).
- **R12.** Delete-with-confirm of a lost job with a live orphan unblocks the queue, and a recovery restore can then load beside that orphan render (the user confirmed the delete).
- **R13.** The double-fork launcher exists for milliseconds as a descendant of the caller. A cancel snapshot taken in that instant would include the server's new group.
- **R14.** `story-server status` still judges SERVING by `data[0].id` (G3). An `mlx_vlm` listing whose first entry is another cached model reports FOREIGN, and the preflight then stops and restarts it once before failing.

### 15.2 Open

These are decisions the user may want to revisit. The spec does not depend on an answer.
- **Q1.** Is `smoke` correctly `forbidden`? It is small (512x320, 9 frames) but loads the full LTX model and gemma.
- **Q2.** Should a required job stop a **different-mode** story server (`vision`/`text`) to start `mlx-vision` (choice 4)? The alternative is to fail the job.
- **Q3.** Should the train wrappers skip their own final restore under movie-ui (R6)?
