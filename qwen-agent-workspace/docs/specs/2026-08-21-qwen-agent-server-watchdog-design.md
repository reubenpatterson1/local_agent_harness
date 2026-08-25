# Spec: `qwen-serve-guard` — vLLM server watchdog and post-start warmup

**Status:** Ready for implementation. No open design decisions.
**Date:** 2026-08-21
**Type:** NEW standalone infrastructure. Two new files plus two directories and two symlinks.
**Deliverables:**
- `/Users/reubenpatterson/.local/bin/qwen-serve-guard` (new file, mode `0755`)
- `/Users/reubenpatterson/Library/LaunchAgents/com.reubenpatterson.qwen-serve-guard.plist`
  (new file, mode `0644`)

**Files this spec MUST NOT touch:**
`/Users/reubenpatterson/.local/bin/qwen-agent` is **read-only for this work**. Not one line of it
changes. This spec *invokes* `qwen-agent`; it does not modify, wrap, patch, or re-implement any part
of it. The four sibling specs in this directory
(`2026-08-21-qwen-agent-tool-harness-design.md` — hereafter **[HARNESS]**,
`2026-08-21-qwen-agent-oneshot-api-design.md` — **[ONESHOT]**,
`2026-08-21-qwen-agent-tiered-approval-design.md` — **[TIERED]**,
`2026-08-21-qwen-agent-search-grounding-design.md` — **[SEARCH]**) are likewise read-only and remain
authoritative for everything about `qwen-agent`'s own behaviour.

**Interpreter constraint:** `/bin/bash` on this machine is **GNU bash 3.2.57(1)-release
(arm64-apple-darwin25)**. No bash-4 syntax anywhere: no associative arrays, no `${v,,}`, no
`mapfile`/`readarray`, no `${!ref}`, no `&>>`, no `[[ ... =~ ]]` reliance. Every external command is
invoked by **absolute path** (the launchd environment has a minimal `PATH`). No Python, no `jq`, no
Homebrew binary, no GNU coreutils — only what ships in `/bin`, `/usr/bin`, `/usr/sbin`.

---

## 1. Purpose and success criteria

### 1.1 The two problems this fixes

**Problem A — first-request latency after every server start.** The vLLM/MLX engine's built-in
startup warmup uses a generic, tools-free prompt. `qwen-agent` always sends the full six-tool schema
([HARNESS] Section 7, ~2 000 prompt tokens) and engages both the `qwen3` reasoning parser and the
`qwen3_xml` tool-call parser. The first request that exercises *that* path therefore pays a one-time
Metal/MLX kernel-compilation cost: measured generation throughput on the first real request is
**~0.1 tok/s**, climbing to the steady-state **~4–10 tok/s** over the following few requests. A
human typing at a prompt eats that stall.

**Problem B — recurring silent hang after long idle.** Documented in
`feedback_vllm_metal_idle_memory_reclaim.md` and `feedback_vllm_metal_hung_process_rss_collapse.md`:
after roughly five hours idle the `vllm serve` process stays alive, the port stays `LISTEN`, and the
server stops answering. Every occurrence has been diagnosed by hand with
`curl -m 10 http://127.0.0.1:8177/v1/models` timing out, and fixed by hand with `kill <pid>`
(escalating to `kill -9`, which has been necessary) followed by a relaunch with the canonical
command. Nothing detects or repairs this automatically today.

### 1.2 What this adds

One shell script, `qwen-serve-guard`, with four subcommands, plus one launchd agent that runs
`qwen-serve-guard check` every 300 seconds for as long as the user is logged in, across reboots.

| Subcommand | Who runs it | What it does |
|---|---|---|
| `check` | the launchd agent, every 300 s | Probe `/v1/models`. If it fails twice in a row, kill → start → wait-for-ready → warm. |
| `restart` | a human, instead of typing the raw `vllm serve` line | Unconditionally kill → start → wait-for-ready → warm. |
| `warm` | a human who started the server some other way | Fire the warmup request only. |
| `status` | a human | Print a one-screen report. Takes no lock, changes nothing. |

### 1.3 Success criteria

The work is correct and complete when every one of the following holds on this machine.

1. **S1 — healthy tick is a no-op.** With the server healthy, `qwen-serve-guard check` exits `0`,
   appends exactly three lines to the guard log (`guard.start`, `check.healthy`, `guard.end`), sends
   exactly one HTTP request, and leaves the server's PID unchanged.
2. **S2 — hang is detected and repaired.** With the server wedged (reproduce per test T4,
   Section 18), one `check` tick logs two `check.unhealthy` lines, kills the process (escalating to
   `SIGKILL` if `SIGTERM` does not take within 5 s), starts a new server, logs `restart.ready`
   within 180 s, logs `warm.ok`, logs `restart.ok`, and exits `0`. `/v1/models` answers `200`
   afterwards.
3. **S3 — dead server is restarted.** With no `vllm serve` process at all, one `check` tick starts
   one, warms it, and exits `0`.
4. **S4 — warmup removes the stall.** After any successful `restart.ok`, the **first** human
   `qwen-agent` request logs `Avg generation throughput: ≥ 2.0 tokens/s` in
   `~/Library/Logs/qwen-serve-guard/vllm-serve.log` — i.e. it is not the ~0.1 tok/s cold case.
5. **S5 — no overlapping restarts.** Two `qwen-serve-guard check` processes started 1 s apart: the
   second logs `guard.lock.busy`, exits `0`, and performs no probe, no kill, and no spawn.
6. **S6 — no silent failure loop.** With the server permanently unstartable (test T7), three
   consecutive `check` ticks log `restart.failed` with `fail_count=1/3`, `2/3`, `3/3`; the third also
   logs `breaker.tripped`; every subsequent tick logs exactly one `guard.standdown` line and spawns
   nothing. Total processes spawned across an hour of ticks: 3.
7. **S7 — recovery is one command.** `rm ~/.qwen-serve-guard/stand-down` (or a successful
   `qwen-serve-guard restart`) fully re-arms the watchdog, and the next tick behaves as if the
   failures never happened.
8. **S8 — survives reboot and logout/login.** After a reboot and a GUI login,
   `launchctl print gui/$(id -u)/com.reubenpatterson.qwen-serve-guard` succeeds and a
   `guard.start cmd=check` line appears in the guard log within 30 s of login, with no manual step.
9. **S9 — no external-volume dependency.** With `/Volumes/Ollama` unmounted, `check`, `restart`,
   `warm` and `status` all behave identically to the mounted case, and every log line is still
   written and readable.
10. **S10 — the warmup never blocks on a prompt.** The warmup subprocess's stdin is `/dev/null`;
    `qwen-agent`'s confirmation prompt therefore reads EOF and denies ([HARNESS] Section 10.3), so a
    warmup can never hang waiting for a keystroke. No warmup attempt ever exceeds 300 s wall clock.
11. **S11 — `qwen-agent` is byte-identical.** `diff` against a pre-change copy of
    `/Users/reubenpatterson/.local/bin/qwen-agent` is empty.
12. **S12 — clean install/uninstall.** The install commands in Section 16 succeed from a clean state,
    and the uninstall commands in Section 17.6 leave no `launchd` job, no dotfiles under
    `~/.qwen-serve-guard`, and a still-working manual `vllm serve` workflow.

### 1.4 Explicitly out of scope

- **Not a general process supervisor.** No `KeepAlive`, no restart-on-exit, no second launchd job
  that owns the `vllm serve` process. The server remains an ordinary orphaned process; the guard
  only ever kills and re-spawns it on a 300 s cadence.
- **No changes to `qwen-agent`**, including no new flags, no `--warmup` mode, no auto-approval, and
  no relaxation of [HARNESS] Section 2's threat model. The warmup gets its non-interactivity from
  `stdin < /dev/null`, which *denies* every gated call — it never approves one.
- **No RSS/memory-threshold health check.** See Section 3.2 for the measurement that killed this idea.
- **No root/system-level `LaunchDaemon`.** A per-user `LaunchAgent` only, running as
  `reubenpatterson`. The server must run as the logged-in user to see `~/mlx_models` and the venv.
- **No keep-alive pinging to *prevent* the idle hang.** The idle hang's root cause is still unknown;
  this spec detects and repairs, it does not attempt prophylaxis. (A keep-alive was floated in
  `feedback_vllm_metal_idle_memory_reclaim.md`; it is a separate experiment, not this work.)
- **No metrics, no notifications, no menu-bar UI, no email/Slack alerting.** The guard log plus
  `qwen-serve-guard status` is the whole operator interface.
- **No log shipping, no `newsyslog.conf` entry, no `logrotate`.** Rotation is one size check and one
  `mv` per file, inside the script (Section 7.3).
- **No config file and no environment-variable overrides.** Every tunable is a literal constant at
  the top of the script (Section 5). Changing behaviour means editing that block.
- **No support for a second model, a second port, or a remote server.** Single hard-coded target.
- **No attempt to preserve an in-flight `qwen-agent` session across a restart.** A restart kills the
  server; any client mid-turn gets a network error. See Assumption A7.

---

## 2. Verified environment facts

All measured on this machine on 2026-08-21. An executor must not re-derive these; it must also not
"fix" the script if one of them looks surprising.

| Fact | Verified value |
|---|---|
| macOS | `26.5.2` build `25F84` |
| `/bin/bash` | GNU bash **3.2.57(1)-release** (arm64) — bash-3 syntax only |
| `flock(1)` | **absent** |
| `setsid(1)` | **absent** |
| `timeout(1)` / `gtimeout(1)` | **absent** — a bash timeout helper is required (Section 11.2) |
| `taskpolicy(1)` | **absent** |
| `shlock(1)` | present at `/usr/bin/shlock`, but **deprecated** by its own man page |
| `lockf(1)` | present at `/usr/bin/lockf`; `flock(2)`-based; supports the `lockf [-s] [-t sec] fd` form for locking inside a shell script; returns **75** (`EX_TEMPFAIL`) when the file is already locked. Verified working with the `exec 9>>FILE; lockf -s -t 0 9` idiom. |
| `ps` keywords | `etime` **is** supported; `etimes` is **not** (`ps: etimes: keyword not found`) — elapsed seconds must be parsed from `etime` |
| `curl` | `/usr/bin/curl` 8.7.1 |
| `lsof` | `/usr/sbin/lsof` |
| Existing LaunchAgents | only `com.adobe.ccxprocess.plist`; no name collision |
| vLLM venv binary | `/Users/reubenpatterson/.venv-vllm-metal/bin/vllm` (exists, `0755`) |
| Model directory | `/Users/reubenpatterson/mlx_models/Huihui-Qwen3.8-27B-abliterated-mlx-6bit` — **internal SSD**; the `/Volumes/Ollama/mlx_models/...` copy is a stale backup and must not be served |
| `qwen-agent` | `/Users/reubenpatterson/.local/bin/qwen-agent`, `0755`, 71 574 bytes |
| `qwen-agent` one-shot flag | **`--user-prompt TEXT`** (with optional `--system-prompt`). [ONESHOT] documents this as `--prompt`; **the shipped script uses `--user-prompt`** and that is what this spec calls. |
| Live process tree | `93738` = API server (`.../Python /Users/.../vllm serve ...`), child `93862` = `VLLM::EngineCore`. `pgrep -f "vllm serve"` matches **only** the parent; the engine core needs its own pattern. |
| Startup wall time | `19:03:05` first log line → `Application startup complete` at `19:03:31` ⇒ **~26 s** from internal SSD (`init engine ... took 8.68 s`) |
| `/v1/models` when healthy | HTTP `200` in `0.0013 s`; body contains the exact substring `"id":"qwen38-6bit"` |
| **RSS when healthy** | `38 MB` (API server) and `69 MB` (engine core) — see Section 3.2 |
| Warmup invocation, live | `qwen-agent --user-prompt "Reply with the single word OK. Do not use any tools." --max-tokens 32 --max-rounds 1 --request-timeout 240 </dev/null` → exit `0`, stdout `{"schema": "qwen-agent.oneshot.v1", "status": "ok", "answer": "OK", "error": null, "rounds": 1, "tool_calls": []}`, empty stderr, 12 s on an already-warm server |

### 2.1 The canonical launch command (single source of truth)

```
VLLM_HOST_IP=127.0.0.1 ~/.venv-vllm-metal/bin/vllm serve \
  ~/mlx_models/Huihui-Qwen3.8-27B-abliterated-mlx-6bit \
  --served-model-name qwen38-6bit \
  --host 127.0.0.1 --port 8177 \
  --max-model-len 8192 --max-num-seqs 4 \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_xml
```

Every flag is load-bearing and none may be dropped, reordered into a different meaning, or
"modernised":

- `VLLM_HOST_IP=127.0.0.1` — without it `vllm serve` hangs forever in a silent retry loop
  (`get_ip()` picks a non-bindable interface on this Mac). This is the single most common way to
  break the server.
- `--reasoning-parser qwen3` **and** `--tool-call-parser qwen3_xml` — the parser names differ on
  purpose. `qwen3` is not a registered *tool* parser in vLLM 0.27.1; see [HARNESS] Section 3.
- `--enable-auto-tool-choice` — without it `qwen-agent`'s preflight check B fails with HTTP 400.
- No `--pipeline-parallel-size` — `PP > 1` flips `lazy_weights=True` and reproduces the Metal
  `SubmissionsIgnored` crash.

`spawn_server` (Section 10.4) is the only place in the deliverables that encodes this command.

---

## 3. Architecture and resolved design decisions

Each subsection states the decision, then why the rejected alternative was rejected. An executor
implements the decision and does not revisit the reasoning.

### 3.1 One script with four subcommands, not two or three scripts

**Decision:** a single executable, `qwen-serve-guard`, dispatching on `$1` ∈
{`check`, `restart`, `warm`, `status`}, default `check`.

**Why not a separate `qwen-serve-start` invoked by a separate watchdog:** the brief leaned toward a
reusable "start-and-warm" script so that automatic and manual restarts behave identically. A single
file achieves that *more* strongly — the watchdog and the human literally execute the same
`do_restart` function — and it removes a nested-locking problem that the two-file design creates.
With two files, the watchdog would hold the lock and then exec the start script, which would try to
take the same lock and fail (a `flock` on a second open file description of the same path conflicts
even within one process tree), forcing an environment-variable "lock already held" back channel.
One file, one `acquire_lock` call at the top, no back channel. The reusability requirement is met by
the `restart` subcommand, which *is* the shared start-and-warm entry point.

### 3.2 Health check: an HTTP request, never RSS

**Decision:** health is `curl -s -m 10 http://127.0.0.1:8177/v1/models` returning curl exit `0`,
HTTP `200`, and a body containing `"qwen38-6bit"`. Two consecutive failures 5 s apart are required
before any restart.

**Why not the RSS heuristic** from `feedback_vllm_metal_hung_process_rss_collapse.md` ("a healthy
server holding the ~21 GB model showed only 19 MB RSS — RSS is the reliable tell"): that heuristic is
**empirically wrong on this machine as configured**. Measured 2026-08-21 while the server was fully
healthy and answering `/v1/models` in 1.3 ms:

```
PID    PPID   RSS(KB)  COMMAND
93738     1    38640   .../Python /Users/.../vllm serve ...
93862 93738    69456   VLLM::EngineCore
```

38 MB and 69 MB — squarely inside the "wedged" band that memory file describes, while serving
correctly. The weights are `mmap`ed, so low RSS is normal, not diagnostic. Any RSS threshold would
produce constant false positives here, and would need re-tuning whenever the model changes. The HTTP
probe is the test that actually diagnosed every historical hang; it is the test the guard uses.
**This spec supersedes the RSS advice in that memory file for automated use.**

**Why `"qwen38-6bit"` must be in the body:** an HTTP `200` from a server that is up but serving the
wrong model (for example started by hand against the stale `/Volumes/Ollama/mlx_models` copy, or with
a different `--served-model-name`) is useless to `qwen-agent`, whose preflight rejects it with exit 2
([HARNESS] 6.2). The canonical relaunch fixes exactly that, so it is worth restarting for.

**Why two attempts, not one:** the false-positive cost is high (a restart kills a live session) and
the mitigation is cheap (one extra request, 5 s later, ≤ 25 s per tick worst case). A wedged server
fails both; a momentarily busy server passes the second.

**Why not also check for an active `qwen-agent` client and defer:** when the server is wedged, any
client is already unrecoverably stuck, so deferring on client presence would defeat the watchdog
exactly when it is needed. Recorded as Assumption A7.

### 3.3 Scheduling: a launchd `LaunchAgent`, not cron, not a `while` loop

**Decision:** `~/Library/LaunchAgents/com.reubenpatterson.qwen-serve-guard.plist` with
`StartInterval = 300` and `RunAtLoad = true`.

**Why launchd:** it is the supported mechanism on macOS for a periodic user-scoped job that must
survive logout, login, and reboot; `cron` on macOS is legacy, needs Full Disk Access grants for
`/usr/sbin/cron`, and has no equivalent of `RunAtLoad`. A `while true; do …; sleep 300; done`
daemon would itself need supervision to survive a reboot — that is what launchd is.

**Two launchd properties this design depends on, and one it must defend against:**

- launchd runs **one instance of a job at a time**. If a tick is still running when the next
  interval elapses, launchd does not spawn a second copy. This is the first line of defence against
  overlapping restarts; the lock in Section 8 is the second (it also covers manual invocations,
  which launchd knows nothing about).
- After a sleep/wake, launchd fires a missed `StartInterval` once on wake, rather than replaying
  every missed interval.
- **`AbandonProcessGroup` must be `true`.** By default launchd kills the job's remaining process
  group when the job's main process exits. Since `check` *spawns the vLLM server and then exits*,
  the default would kill the server we just started, seconds after starting it. This single key is
  the difference between working and catastrophically broken. `nohup` alone does **not** protect
  against it (that is a `SIGHUP` guard, not a process-group guard).

### 3.4 Locking: `lockf(1)` on an inherited file descriptor

**Decision:**

```bash
exec 9>>"$LOCK_FILE"
if ! /usr/bin/lockf -s -t 0 9; then ...busy... ; fi
```

**Why:** `flock(1)` does not exist on macOS. `shlock(1)` exists but is deprecated by Apple in favour
of `lockf`, and it is a PID-file scheme, which means a staleness check that gets it wrong if a PID is
recycled. `lockf` uses `flock(2)` on the open file description held by fd 9 in the guard process, so:
the lock is **atomic**, it is **released automatically by the kernel** when the process exits for any
reason (including `SIGKILL` and a panic), and there is therefore **no stale-lock case to reason about
at all** — no PID file, no timestamp heuristic, no `-9`-left-a-lockfile-behind failure mode. `-t 0`
means "fail immediately, never wait": a tick that cannot get the lock must do nothing, not queue up.
`-s` keeps it silent so the guard owns all output. Verified: second holder exits `75`
(`EX_TEMPFAIL`).

A hand-rolled `mkdir`-based lock was rejected for exactly the staleness reason: a `kill -9`'d guard
would leave a lock directory that a human then has to remove.

### 3.5 The manual-restart race, explicitly

Three cases, and what happens in each:

**Case A — a human runs `qwen-serve-guard restart` and the tick fires mid-restart.** The human's
process holds fd 9's lock. The tick's `lockf -t 0` fails immediately; it logs `guard.lock.busy` and
exits `0` **before probing, killing, or spawning anything**. Zero interference. This is the primary
mechanism and the reason `restart` is the documented way for a human to restart.

**Case B — a human runs the raw `vllm serve` line by hand and the tick fires while it is still
loading.** The guard has no lock to respect here, and the probe legitimately fails (the server is
not up yet), so a naive watchdog would kill the human's 10-second-old process. Defence: before
killing anything, `do_check` computes the **age of the youngest** candidate process. If it is
younger than `YOUNG_SECS` (240 s, comfortably above the 180 s ready budget and ~7× the measured 26 s
startup), the guard concludes a start is already in progress, logs
`restart.deferred reason=young_process`, kills **nothing**, waits for readiness, and then just warms
it up. This is not merely defensive: it means a hand-started server also gets warmed. The deferral
cannot loop — one tick later the process is older than 240 s and is treated normally — and it does
**not** increment the failure counter, since nothing was attempted.

**Case C — a human has killed the server and the tick fires in the gap before their relaunch.** The
guard sees no process and a free port, and starts a server; the human's own relaunch then fails with
"address already in use". This is an accepted residual race, mitigated procedurally: the runbook
(Section 17) tells the operator to use `qwen-serve-guard restart`, which is race-free by Case A. The
worst outcome is a confusing error and one redundant server start, not data loss and not two servers
(the port binding prevents that).

### 3.6 Warmup: invoke the real `qwen-agent` CLI

**Decision:** the warmup is

```
qwen-agent --user-prompt "Reply with the single word OK. Do not use any tools." \
           --max-tokens 32 --max-rounds 1 --request-timeout 240  < /dev/null
```

run with a hard 300 s wall-clock bound, at most twice, treating exit `0` **and** exit `3` as success.

**Why re-use the CLI rather than `curl` a hand-built request:** the six-tool schema lives inside
`qwen-agent` (`TOOLS`, [HARNESS] Section 7, ~170 lines of JSON). Any copy of it in a second file
would drift the first time a tool description changes, and a drifted warmup warms the wrong kernel
shapes — a silent failure. Invoking the CLI also exercises the *exact* code path a real request
takes: preflight check B's tools probe, the `chat_completion` body with
`chat_template_kwargs`/`temperature`/`top_p`, the reasoning parser, and the tool-call parser.

**Why stdin is `/dev/null`:** the run is unattended. Per [HARNESS] Section 10.3 and [TIERED]
Section 3, a confirmation prompt that reads EOF is treated as a **denial**, and a denial is a normal,
handled outcome ([HARNESS] 10.4). So `< /dev/null` guarantees the warmup can never block on a
keystroke, and guarantees that if the model ignores "do not use any tools" and asks for `bash`, the
answer is **no**. It never auto-approves anything. `--max-rounds 1` bounds it further: at most one
tool round, then [SEARCH] Section 6's forced tools-disabled summary, then done.

**Why exit `3` counts as success:** exit `3` is [ONESHOT] Section 3's "turn ended abnormally"
(`max_rounds`, `network_error`, …). For `max_rounds` in particular, a full round trip through the
tool-schema path *did* happen, which is the entire point of the warmup. Only exit `2` (preflight
failure — the server is not usable) and `124` (our timeout) are warmup failures.

**Why two attempts:** `qwen-agent`'s preflight check B posts a real tools request with a **60 s
timeout that this spec cannot change** (it is a literal in the read-only file). On a stone-cold
engine that probe could conceivably exceed 60 s, and `qwen-agent` would exit `2`. The compilation
work it did still persists in the engine, so attempt 2 is materially faster and will pass. Two
attempts, no more.

**Why a warmup failure does not count as a restart failure:** by the time `warmup` runs, the server
has already answered `/v1/models` — it is up and usable. The warmup is a latency optimisation, not a
correctness gate. Failing it must not trip the circuit breaker and must not cause another kill.

### 3.7 Logging: real files on the internal disk, symlinked into the project convention

**Decision:** the guard writes **only** to `/Users/reubenpatterson/Library/Logs/qwen-serve-guard/`.
Install creates two symlinks so the established project convention still resolves:

```
/Volumes/Ollama/vllm-metal/logs/guard.log       -> ~/Library/Logs/qwen-serve-guard/guard.log
/Volumes/Ollama/vllm-metal/logs/vllm-serve.log  -> ~/Library/Logs/qwen-serve-guard/vllm-serve.log
```

**Why this inversion:** the brief correctly flagged that reusing
`/Volumes/Ollama/vllm-metal/logs/` creates a soft dependency on an external drive that the model
itself no longer needs. Writing to a possibly-unmounted volume from a watchdog is the wrong
direction of dependency: a `mkdir` into `/Volumes/Ollama` while the drive is absent creates a
**local directory that shadows the mount point**, so the drive silently fails to mount cleanly
later — a genuinely nasty failure mode. Inverting it means the guard has zero external dependency
(criterion S9), while `ls /Volumes/Ollama/vllm-metal/logs/` still shows the logs whenever the drive
is attached. `~/Library/Logs/` is also the macOS-native location for user-level logs and is what
Console.app shows.

If even the local log directory cannot be created, `LOG_FILE` is set to the empty string and every
log line goes to **stderr**, which launchd captures in
`~/Library/Logs/qwen-serve-guard/launchd.err` — and, if that is unavailable too, is simply lost. A
logging failure must never abort a health check. There is no third fallback and no retry.

### 3.8 No silent failure loop: a three-strike stand-down

**Decision:** `~/.qwen-serve-guard/fail-count` holds the count of **consecutive failed restart
attempts**. On the 3rd, the guard writes `~/.qwen-serve-guard/stand-down` and from then on every
tick logs one `guard.standdown` line and does nothing else. A successful restart (automatic or
manual) resets the count to `0` and removes the stand-down file.

**Why a hard stop instead of exponential backoff:** the failures this protects against are
qualitatively permanent — a broken venv, a deleted model directory, a genuine crash-on-boot bug, an
unkillable process. Backoff would keep spawning 22 GB processes forever at a slowly decreasing rate
and keep growing the logs; there is no plausible failure here that heals itself after 40 minutes but
not after 15. Three strikes at 5-minute spacing gives 15 minutes of genuine transient tolerance and
then stops, which is what "must not retry indefinitely in a tight loop burning resources" asks for.

**The stand-down file doubles as the operator's off switch.** `touch ~/.qwen-serve-guard/stand-down`
pauses automatic restarts without unloading the agent (useful when you want the server down, or want
to debug it by hand, and don't want the watchdog resurrecting it). This is why the file is **never
auto-cleared on a healthy tick**: auto-clearing would silently defeat a human's deliberate pause. It
is cleared only by `rm`, or by a successful `restart` — which is itself an unambiguous human "resume
watching this" (and is why `restart` deliberately ignores stand-down and proceeds).

### 3.9 Consequence to accept: the server auto-starts at login

Because `check` treats "no server at all" as a condition to repair (criterion S3) and
`RunAtLoad = true`, the vLLM server will start automatically shortly after each GUI login, and will
be kept running. That is the desired behaviour for a daily-use tool whose whole problem is
first-request latency, and it is the only interpretation consistent with "detects a dead/hung server
and restarts it" — a watchdog cannot distinguish "intentionally down" from "crashed". The opt-out is
`touch ~/.qwen-serve-guard/stand-down` (keeps the agent loaded, stops the restarts) or
`launchctl bootout` (Section 17.3). Recorded as Assumption A1.

---

## 4. Deliverables and filesystem layout

| Path | Kind | Mode | Created by |
|---|---|---|---|
| `/Users/reubenpatterson/.local/bin/qwen-serve-guard` | file (Section 6) | `0755` | executor |
| `/Users/reubenpatterson/Library/LaunchAgents/com.reubenpatterson.qwen-serve-guard.plist` | file (Section 15) | `0644` | executor |
| `/Users/reubenpatterson/.qwen-serve-guard/` | dir | `0700` | install cmd + script at runtime |
| `/Users/reubenpatterson/.qwen-serve-guard/guard.lock` | file, 0 bytes | `0644` | script |
| `/Users/reubenpatterson/.qwen-serve-guard/fail-count` | file, one integer + `\n` | `0644` | script |
| `/Users/reubenpatterson/.qwen-serve-guard/stand-down` | file, one line, present ⇒ paused | `0644` | script or operator |
| `/Users/reubenpatterson/.qwen-serve-guard/health-body` | file, last probe body | `0644` | script |
| `/Users/reubenpatterson/.qwen-serve-guard/health-body.status` | file, last `status` probe body | `0644` | script |
| `/Users/reubenpatterson/Library/Logs/qwen-serve-guard/` | dir | `0755` | install cmd + script at runtime |
| `…/qwen-serve-guard/guard.log` (+ `.1`) | append-only text | `0644` | script |
| `…/qwen-serve-guard/vllm-serve.log` (+ `.1`) | append-only text | `0644` | script |
| `…/qwen-serve-guard/warmup.json` | last warmup stdout ([ONESHOT] envelope) | `0644` | script |
| `…/qwen-serve-guard/warmup.err` | last warmup stderr | `0644` | script |
| `…/qwen-serve-guard/launchd.out`, `launchd.err` | launchd-level capture; expected to stay empty | `0644` | launchd |
| `/Volumes/Ollama/vllm-metal/logs/guard.log` | symlink → local `guard.log` | link | install cmd |
| `/Volumes/Ollama/vllm-metal/logs/vllm-serve.log` | symlink → local `vllm-serve.log` | link | install cmd |

`warmup.json` and `warmup.err` are **truncated on every attempt** (`>`), not appended: they are
"what the last warmup did", and the durable record is the one-line `warm.*` entry in `guard.log`.

Pre-existing files in `/Volumes/Ollama/vllm-metal/logs/` (`serve-tools3.log`, `serve-internal.log`,
…) are left exactly as they are. The guard never writes to them and never deletes them.

---

## 5. Constants (exact names and values)

The literal block at the top of the script. An executor copies these values verbatim.

| Constant | Value | Meaning / why this value |
|---|---|---|
| `GUARD_VERSION` | `"1"` | echoed in `guard.start`, so a log makes it obvious which revision ran |
| `LAUNCHD_LABEL` | `"com.reubenpatterson.qwen-serve-guard"` | must match the plist `Label` and its filename |
| `HEALTH_URL` | `"http://127.0.0.1:8177/v1/models"` | the endpoint that diagnosed every historical hang |
| `MODEL_NAME` | `"qwen38-6bit"` | `--served-model-name`, and the substring the probe requires in the body |
| `SERVE_PORT` | `"8177"` | matches `qwen-agent`'s `DEFAULT_BASE_URL` |
| `VLLM_BIN` | `"/Users/reubenpatterson/.venv-vllm-metal/bin/vllm"` | serving venv; **never** `~/.venv-mlx-convert` |
| `MODEL_PATH` | `"/Users/reubenpatterson/mlx_models/Huihui-Qwen3.8-27B-abliterated-mlx-6bit"` | internal SSD copy; ~26 s start |
| `QWEN_AGENT` | `"/Users/reubenpatterson/.local/bin/qwen-agent"` | the warmup driver |
| `STATE_DIR` | `"/Users/reubenpatterson/.qwen-serve-guard"` | no spaces in the path, always available |
| `LOG_DIR` | `"/Users/reubenpatterson/Library/Logs/qwen-serve-guard"` | native user log location, no external volume |
| `GUARD_LOG_MAX` | `5242880` | 5 MiB ≈ 1.5 years at ~29 KB/day of healthy ticks |
| `SERVE_LOG_MAX` | `52428800` | 50 MiB; a full server session is ~100 KB |
| `PROBE_TIMEOUT` | `10` | seconds; identical to `qwen-agent`'s preflight timeout, so the guard's verdict and the user's experience agree |
| `PROBE_ATTEMPTS` | `2` | consecutive failures required before restarting |
| `PROBE_RETRY_DELAY` | `5` | seconds between probe attempts ⇒ ≤ 25 s per failing tick |
| `TERM_WAIT` | `5` | seconds to give `SIGTERM`; a wedged server has been observed to ignore it |
| `KILL_WAIT` | `5` | seconds to give `SIGKILL` before declaring the PID unkillable |
| `PORT_FREE_WAIT` | `10` | seconds to wait for the listener to disappear after the kills |
| `READY_TIMEOUT` | `180` | seconds; ~7× the measured 26 s start, room for cold page cache |
| `READY_POLL` | `3` | seconds between readiness probes |
| `YOUNG_SECS` | `240` | a candidate process younger than this is never killed (Section 3.5 Case B) |
| `WARM_PROMPT` | `"Reply with the single word OK. Do not use any tools."` | trivial, tool-free, one-token answer |
| `WARM_TIMEOUT` | `300` | hard wall-clock bound per warmup attempt |
| `WARM_MAX_TOKENS` | `32` | enough decode steps to compile the decode path; small enough to stay fast |
| `WARM_REQ_TIMEOUT` | `240` | `qwen-agent --request-timeout`, kept below `WARM_TIMEOUT` |
| `WARM_ATTEMPTS` | `2` | a failed attempt is retried exactly once |
| `FAIL_LIMIT` | `3` | consecutive failed restarts before standing down |
| `RUN_ID` | `"g$$"` | per-invocation tag on every log line, so one tick's lines can be grouped |

Worst-case wall clock for one failing tick: 25 s probing + 2×(5+5) s killing + 10 s port + 180 s
ready + 2×300 s warmup ≈ **13.9 minutes**, i.e. it can span two ticks. That is expected and is
exactly what the lock is for.

---

## 6. `/Users/reubenpatterson/.local/bin/qwen-serve-guard` — complete file

Create this file with **exactly** this content, then `chmod 755`. It has been syntax-checked with
`bash -n` and its `check`, `status`, lock-contention, stand-down, usage-error, `run_with_timeout` and
warmup paths were executed against the live server on 2026-08-21.

```bash
#!/bin/bash
#
# qwen-serve-guard -- health watchdog and start-and-warm wrapper for the local
# vLLM server that serves `qwen38-6bit` on 127.0.0.1:8177.
#
#   check    Probe /v1/models. If it fails twice, kill the server, start it,
#            wait for ready, and fire a warmup request. Run every 300s by the
#            launchd agent com.reubenpatterson.qwen-serve-guard.
#   restart  Unconditionally kill + start + wait + warm. What a human runs
#            instead of typing the raw `vllm serve` command by hand.
#   warm     Fire the warmup request only, against an already-running server.
#   status   Print a one-screen report to stdout. Takes no lock, changes nothing.
#
# Spec: /Volumes/Ollama/vllm-metal/docs/specs/2026-08-21-qwen-agent-server-watchdog-design.md
#
# /bin/bash on macOS is bash 3.2.57 -- no bash 4 syntax anywhere (no `local -A`,
# no ${v,,}, no mapfile, no ${!v}).
# `set -e` is deliberately NOT used: every exit status is inspected explicitly,
# and an unexpected abort would skip the log line that says why.

set -u

# ---------------------------------------------------------------------------
# Section 5: constants
# ---------------------------------------------------------------------------

GUARD_VERSION="1"
LAUNCHD_LABEL="com.reubenpatterson.qwen-serve-guard"

HEALTH_URL="http://127.0.0.1:8177/v1/models"
MODEL_NAME="qwen38-6bit"
SERVE_PORT="8177"

VLLM_BIN="/Users/reubenpatterson/.venv-vllm-metal/bin/vllm"
MODEL_PATH="/Users/reubenpatterson/mlx_models/Huihui-Qwen3.8-27B-abliterated-mlx-6bit"
QWEN_AGENT="/Users/reubenpatterson/.local/bin/qwen-agent"

STATE_DIR="/Users/reubenpatterson/.qwen-serve-guard"
LOCK_FILE="$STATE_DIR/guard.lock"
FAIL_FILE="$STATE_DIR/fail-count"
STANDDOWN_FILE="$STATE_DIR/stand-down"
HEALTH_BODY="$STATE_DIR/health-body"
HEALTH_BODY_STATUS="$STATE_DIR/health-body.status"

LOG_DIR="/Users/reubenpatterson/Library/Logs/qwen-serve-guard"
LOG_FILE="$LOG_DIR/guard.log"
SERVE_LOG="$LOG_DIR/vllm-serve.log"
WARM_OUT="$LOG_DIR/warmup.json"
WARM_ERR="$LOG_DIR/warmup.err"

GUARD_LOG_MAX=5242880          # 5 MiB, then rotate to guard.log.1
SERVE_LOG_MAX=52428800         # 50 MiB, then rotate to vllm-serve.log.1

PROBE_TIMEOUT=10               # curl -m, seconds. Matches qwen-agent preflight.
PROBE_ATTEMPTS=2               # consecutive failures required to call it dead
PROBE_RETRY_DELAY=5            # seconds between probe attempts

TERM_WAIT=5                    # seconds to wait for SIGTERM to work
KILL_WAIT=5                    # seconds to wait for SIGKILL to work
PORT_FREE_WAIT=10              # seconds to wait for the listener to disappear
READY_TIMEOUT=180              # seconds to wait for a fresh server to answer
READY_POLL=3                   # seconds between readiness probes
YOUNG_SECS=240                 # a vllm process younger than this is not killed

WARM_PROMPT="Reply with the single word OK. Do not use any tools."
WARM_TIMEOUT=300               # hard wall-clock bound on one warmup attempt
WARM_MAX_TOKENS=32
WARM_REQ_TIMEOUT=240           # qwen-agent --request-timeout
WARM_ATTEMPTS=2                # a failed attempt is retried exactly once

FAIL_LIMIT=3                   # consecutive failed restarts before standing down

RUN_ID="g$$"

# Globals assigned by functions. Declared here because `set -u` is on.
PROBE_CODE=""
PROBE_RTT=""
PROBE_CURL_RC=0
PROBE_REASON=""
HEALTH_REASON=""
SPAWN_PID=""
READY_ELAPSED=""
STATE_OK=0

# ---------------------------------------------------------------------------
# Section 7: logging
# ---------------------------------------------------------------------------

rotate_if_needed() {
    local f="$1"
    local max="$2"
    local size
    if [ ! -f "$f" ]; then
        return 0
    fi
    size=$(/usr/bin/stat -f%z "$f" 2>/dev/null)
    case "$size" in
        ''|*[!0-9]*) return 0 ;;
    esac
    if [ "$size" -ge "$max" ]; then
        /bin/mv -f "$f" "$f.1" 2>/dev/null
    fi
    return 0
}

setup_dirs() {
    if /bin/mkdir -p "$LOG_DIR" 2>/dev/null; then
        rotate_if_needed "$LOG_FILE" "$GUARD_LOG_MAX"
    else
        LOG_FILE=""
    fi
    if /bin/mkdir -p "$STATE_DIR" 2>/dev/null; then
        /bin/chmod 700 "$STATE_DIR" 2>/dev/null
        STATE_OK=1
    else
        STATE_OK=0
    fi
    return 0
}

log() {
    local line
    line="$(/bin/date "+%Y-%m-%dT%H:%M:%S%z") $RUN_ID $*"
    if [ -n "$LOG_FILE" ]; then
        if printf '%s\n' "$line" >>"$LOG_FILE" 2>/dev/null; then
            return 0
        fi
    fi
    printf '%s\n' "$line" >&2
    return 0
}

clip() {
    /usr/bin/tr -d '\000-\037' | /usr/bin/cut -c1-200
}

# ---------------------------------------------------------------------------
# Section 8: locking
# ---------------------------------------------------------------------------

acquire_lock() {
    if [ "$STATE_OK" -ne 1 ]; then
        log "guard.state.unwritable dir=$STATE_DIR"
        return 1
    fi
    if ! /usr/bin/touch "$LOCK_FILE" 2>/dev/null; then
        log "guard.lock.unopenable file=$LOCK_FILE"
        return 1
    fi
    exec 9>>"$LOCK_FILE"
    if ! /usr/bin/lockf -s -t 0 9; then
        return 2
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Section 9: health probe
# ---------------------------------------------------------------------------

probe_once() {
    local body="$1"
    local out
    PROBE_CODE=""
    PROBE_RTT=""
    PROBE_REASON=""
    out=$(/usr/bin/curl -s -m "$PROBE_TIMEOUT" -o "$body" \
          -w '%{http_code} %{time_total}' "$HEALTH_URL" 2>/dev/null)
    PROBE_CURL_RC=$?
    PROBE_CODE=$(printf '%s' "$out" | /usr/bin/awk '{print $1}')
    PROBE_RTT=$(printf '%s' "$out" | /usr/bin/awk '{print $2}')
    if [ -z "$PROBE_CODE" ]; then PROBE_CODE="000"; fi
    if [ -z "$PROBE_RTT" ]; then PROBE_RTT="0.000000"; fi
    if [ "$PROBE_CURL_RC" -eq 28 ]; then
        PROBE_REASON="timeout_${PROBE_TIMEOUT}s"
        return 1
    fi
    if [ "$PROBE_CURL_RC" -eq 7 ]; then
        PROBE_REASON="connect_refused"
        return 1
    fi
    if [ "$PROBE_CURL_RC" -ne 0 ]; then
        PROBE_REASON="curl_rc_${PROBE_CURL_RC}"
        return 1
    fi
    if [ "$PROBE_CODE" != "200" ]; then
        PROBE_REASON="http_${PROBE_CODE}"
        return 1
    fi
    if ! /usr/bin/grep -q -F "\"$MODEL_NAME\"" "$body" 2>/dev/null; then
        PROBE_REASON="model_missing"
        return 1
    fi
    return 0
}

health_check() {
    local attempt=1
    HEALTH_REASON=""
    while [ "$attempt" -le "$PROBE_ATTEMPTS" ]; do
        if probe_once "$HEALTH_BODY"; then
            log "check.healthy attempt=$attempt/$PROBE_ATTEMPTS http=$PROBE_CODE rtt=$PROBE_RTT"
            return 0
        fi
        log "check.unhealthy attempt=$attempt/$PROBE_ATTEMPTS reason=$PROBE_REASON http=$PROBE_CODE curl_rc=$PROBE_CURL_RC"
        HEALTH_REASON="$PROBE_REASON"
        attempt=$(( attempt + 1 ))
        if [ "$attempt" -le "$PROBE_ATTEMPTS" ]; then
            /bin/sleep "$PROBE_RETRY_DELAY"
        fi
    done
    return 1
}

# ---------------------------------------------------------------------------
# Section 10: process discovery, kill, spawn
# ---------------------------------------------------------------------------

port_pids() {
    /usr/sbin/lsof -nP -iTCP:"$SERVE_PORT" -sTCP:LISTEN -t 2>/dev/null
}

server_pids() {
    { port_pids
      /usr/bin/pgrep -f "vllm serve" 2>/dev/null
      /usr/bin/pgrep -f "VLLM::EngineCore" 2>/dev/null
    } | /usr/bin/sort -u -n | /usr/bin/grep -v -x "$$"
}

proc_age() {
    /bin/ps -o etime= -p "$1" 2>/dev/null | /usr/bin/awk '
        NF { n = split($1, a, "-"); d = 0; t = $1;
             if (n == 2) { d = a[1]; t = a[2] }
             m = split(t, b, ":");
             if (m == 3) { s = b[1]*3600 + b[2]*60 + b[3] }
             else if (m == 2) { s = b[1]*60 + b[2] }
             else { s = b[1] }
             print d*86400 + s; exit }'
}

youngest_age() {
    local pid age min
    min=""
    for pid in $(server_pids); do
        age=$(proc_age "$pid")
        case "$age" in
            ''|*[!0-9]*) continue ;;
        esac
        if [ -z "$min" ] || [ "$age" -lt "$min" ]; then
            min="$age"
        fi
    done
    printf '%s' "$min"
}

kill_pid() {
    local pid="$1"
    local waited=0
    log "restart.kill pid=$pid signal=TERM"
    /bin/kill -TERM "$pid" 2>/dev/null
    while [ "$waited" -lt "$TERM_WAIT" ]; do
        /bin/sleep 1
        waited=$(( waited + 1 ))
        if ! /bin/kill -0 "$pid" 2>/dev/null; then
            log "restart.kill.ok pid=$pid signal=TERM after=${waited}s"
            return 0
        fi
    done
    log "restart.kill.escalate pid=$pid signal=KILL after=${waited}s"
    /bin/kill -KILL "$pid" 2>/dev/null
    waited=0
    while [ "$waited" -lt "$KILL_WAIT" ]; do
        /bin/sleep 1
        waited=$(( waited + 1 ))
        if ! /bin/kill -0 "$pid" 2>/dev/null; then
            log "restart.kill.ok pid=$pid signal=KILL after=${waited}s"
            return 0
        fi
    done
    log "restart.kill.failed pid=$pid detail=alive_${KILL_WAIT}s_after_sigkill"
    return 1
}

wait_port_free() {
    local waited=0
    while [ "$waited" -lt "$PORT_FREE_WAIT" ]; do
        if [ -z "$(port_pids)" ]; then
            log "restart.port.free after=${waited}s"
            return 0
        fi
        /bin/sleep 1
        waited=$(( waited + 1 ))
    done
    log "restart.port.busy detail=still_listening_after_${PORT_FREE_WAIT}s"
    return 1
}

spawn_server() {
    rotate_if_needed "$SERVE_LOG" "$SERVE_LOG_MAX"
    printf '\n===== qwen-serve-guard spawn %s %s =====\n' \
        "$(/bin/date "+%Y-%m-%dT%H:%M:%S%z")" "$RUN_ID" >>"$SERVE_LOG" 2>/dev/null
    /usr/bin/nohup /usr/bin/env VLLM_HOST_IP=127.0.0.1 \
        "$VLLM_BIN" serve "$MODEL_PATH" \
        --served-model-name "$MODEL_NAME" \
        --host 127.0.0.1 --port "$SERVE_PORT" \
        --max-model-len 8192 --max-num-seqs 4 \
        --reasoning-parser qwen3 \
        --enable-auto-tool-choice \
        --tool-call-parser qwen3_xml \
        >>"$SERVE_LOG" 2>&1 </dev/null &
    SPAWN_PID=$!
    log "restart.spawn pid=$SPAWN_PID log=$SERVE_LOG"
    return 0
}

wait_ready() {
    local waited=0
    READY_ELAPSED=""
    while [ "$waited" -lt "$READY_TIMEOUT" ]; do
        /bin/sleep "$READY_POLL"
        waited=$(( waited + READY_POLL ))
        if probe_once "$HEALTH_BODY"; then
            READY_ELAPSED="$waited"
            log "restart.ready after=${waited}s http=$PROBE_CODE rtt=$PROBE_RTT"
            return 0
        fi
    done
    log "restart.notready after=${READY_TIMEOUT}s reason=$PROBE_REASON"
    return 1
}

# ---------------------------------------------------------------------------
# Section 11: warmup
# ---------------------------------------------------------------------------

run_with_timeout() {
    local limit="$1"
    shift
    local pid waited
    "$@" &
    pid=$!
    waited=0
    while [ "$waited" -lt "$limit" ]; do
        if ! /bin/kill -0 "$pid" 2>/dev/null; then
            wait "$pid"
            return $?
        fi
        /bin/sleep 1
        waited=$(( waited + 1 ))
    done
    /bin/kill -TERM "$pid" 2>/dev/null
    /bin/sleep 3
    /bin/kill -KILL "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
    return 124
}

warm_status() {
    /usr/bin/sed -n 's/.*"status": "\([a-z_]*\)".*/\1/p' "$WARM_OUT" 2>/dev/null \
        | /usr/bin/head -1
}

warm_err_tail() {
    /usr/bin/tail -n 1 "$WARM_ERR" 2>/dev/null | clip
}

warmup() {
    local attempt=1
    local rc started elapsed status
    while [ "$attempt" -le "$WARM_ATTEMPTS" ]; do
        log "warm.begin attempt=$attempt/$WARM_ATTEMPTS timeout=${WARM_TIMEOUT}s"
        started=$(/bin/date +%s)
        run_with_timeout "$WARM_TIMEOUT" \
            "$QWEN_AGENT" \
                --user-prompt "$WARM_PROMPT" \
                --max-tokens "$WARM_MAX_TOKENS" \
                --max-rounds 1 \
                --request-timeout "$WARM_REQ_TIMEOUT" \
            </dev/null >"$WARM_OUT" 2>"$WARM_ERR"
        rc=$?
        elapsed=$(( $(/bin/date +%s) - started ))
        status=$(warm_status)
        if [ -z "$status" ]; then status="none"; fi
        if [ "$rc" -eq 0 ] || [ "$rc" -eq 3 ]; then
            log "warm.ok attempt=$attempt elapsed=${elapsed}s exit=$rc status=$status"
            return 0
        fi
        log "warm.fail attempt=$attempt elapsed=${elapsed}s exit=$rc status=$status detail=\"$(warm_err_tail)\""
        attempt=$(( attempt + 1 ))
    done
    log "warm.giveup attempts=$WARM_ATTEMPTS detail=\"server is reachable; first real request will pay the compile cost\""
    return 1
}

# ---------------------------------------------------------------------------
# Section 12: failure accounting and stand-down
# ---------------------------------------------------------------------------

read_fail_count() {
    local n
    n=$(/bin/cat "$FAIL_FILE" 2>/dev/null)
    case "$n" in
        ''|*[!0-9]*) n=0 ;;
    esac
    printf '%s' "$n"
}

standdown_reason() {
    /usr/bin/head -1 "$STANDDOWN_FILE" 2>/dev/null | clip
}

record_success() {
    printf '0\n' >"$FAIL_FILE" 2>/dev/null
    if [ -f "$STANDDOWN_FILE" ]; then
        /bin/rm -f "$STANDDOWN_FILE" 2>/dev/null
        log "standdown.cleared reason=restart_succeeded"
    fi
    return 0
}

record_failure() {
    local reason="$1"
    local n
    n=$(read_fail_count)
    n=$(( n + 1 ))
    printf '%s\n' "$n" >"$FAIL_FILE" 2>/dev/null
    log "restart.failed reason=$reason fail_count=$n/$FAIL_LIMIT"
    if [ "$n" -ge "$FAIL_LIMIT" ] && [ ! -f "$STANDDOWN_FILE" ]; then
        printf 'reason=breaker tripped=%s fail_count=%s last_reason=%s\n' \
            "$(/bin/date "+%Y-%m-%dT%H:%M:%S%z")" "$n" "$reason" \
            >"$STANDDOWN_FILE" 2>/dev/null
        log "breaker.tripped fail_count=$n reason=$reason detail=\"no further automatic restarts until $STANDDOWN_FILE is removed\""
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Section 13: subcommands
# ---------------------------------------------------------------------------

do_restart() {
    local trigger="$1"
    local started elapsed pids pass p
    started=$(/bin/date +%s)
    log "restart.begin trigger=$trigger"

    if [ ! -x "$VLLM_BIN" ]; then
        record_failure "vllm_binary_missing"
        return 1
    fi
    if [ ! -d "$MODEL_PATH" ]; then
        record_failure "model_path_missing"
        return 1
    fi

    pass=1
    while [ "$pass" -le 2 ]; do
        pids=$(server_pids)
        if [ -z "$pids" ]; then
            break
        fi
        log "restart.discover pass=$pass pids=\"$(printf '%s' "$pids" | /usr/bin/tr '\n' ' ' | /usr/bin/sed 's/ *$//')\""
        for p in $pids; do
            if ! kill_pid "$p"; then
                record_failure "unkillable_pid_$p"
                return 1
            fi
        done
        pass=$(( pass + 1 ))
    done
    pids=$(server_pids)
    if [ -n "$pids" ]; then
        log "restart.discover.remain pids=\"$(printf '%s' "$pids" | /usr/bin/tr '\n' ' ' | /usr/bin/sed 's/ *$//')\""
        record_failure "processes_remain"
        return 1
    fi

    if ! wait_port_free; then
        record_failure "port_busy"
        return 1
    fi

    spawn_server
    if ! wait_ready; then
        record_failure "not_ready"
        return 1
    fi

    warmup
    elapsed=$(( $(/bin/date +%s) - started ))
    log "restart.ok trigger=$trigger elapsed=${elapsed}s"
    record_success
    return 0
}

do_check() {
    local age
    if health_check; then
        return 0
    fi
    log "check.decision restart_needed reason=$HEALTH_REASON"
    age=$(youngest_age)
    case "$age" in
        ''|*[!0-9]*) age="" ;;
    esac
    if [ -n "$age" ] && [ "$age" -lt "$YOUNG_SECS" ]; then
        log "restart.deferred reason=young_process age=${age}s threshold=${YOUNG_SECS}s detail=\"a start begun outside this run is probably still in progress; not killing it\""
        if wait_ready; then
            warmup
            log "restart.deferred.ready"
            return 0
        fi
        log "restart.deferred.notready detail=\"left for the next tick; fail_count not incremented\""
        return 0
    fi
    do_restart "check"
    return $?
}

status_line() {
    printf '  %-14s%s\n' "$1" "$2"
}

do_status() {
    local pids portpid
    printf 'qwen-serve-guard status  %s\n' "$(/bin/date "+%Y-%m-%dT%H:%M:%S%z")"
    if probe_once "$HEALTH_BODY_STATUS"; then
        status_line "health:" "HEALTHY  http=$PROBE_CODE rtt=${PROBE_RTT}s model=$MODEL_NAME"
    else
        status_line "health:" "UNHEALTHY  reason=$PROBE_REASON http=$PROBE_CODE curl_rc=$PROBE_CURL_RC"
    fi
    pids=$(server_pids | /usr/bin/tr '\n' ' ' | /usr/bin/sed 's/ *$//')
    if [ -z "$pids" ]; then pids="none"; fi
    status_line "server pids:" "$pids"
    portpid=$(port_pids | /usr/bin/tr '\n' ' ' | /usr/bin/sed 's/ *$//')
    if [ -z "$portpid" ]; then
        status_line "port $SERVE_PORT:" "free"
    else
        status_line "port $SERVE_PORT:" "LISTEN pid $portpid"
    fi
    status_line "fail count:" "$(read_fail_count) / $FAIL_LIMIT"
    if [ -f "$STANDDOWN_FILE" ]; then
        status_line "stand-down:" "YES -- automatic restarts are OFF. $(standdown_reason)"
        status_line "" "resume with: rm $STANDDOWN_FILE"
    else
        status_line "stand-down:" "no"
    fi
    if /bin/launchctl print "gui/$(/usr/bin/id -u)/$LAUNCHD_LABEL" >/dev/null 2>&1; then
        status_line "launchd:" "loaded ($LAUNCHD_LABEL)"
    else
        status_line "launchd:" "NOT LOADED ($LAUNCHD_LABEL)"
    fi
    if [ -n "$LOG_FILE" ]; then
        status_line "guard log:" "$LOG_FILE"
    else
        status_line "guard log:" "<unwritable -- guard logs to stderr>"
    fi
    status_line "server log:" "$SERVE_LOG"
    printf '  last 5 guard log lines:\n'
    if [ -n "$LOG_FILE" ] && [ -f "$LOG_FILE" ]; then
        /usr/bin/tail -n 5 "$LOG_FILE" | /usr/bin/sed 's/^/    /'
    else
        printf '    (none)\n'
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Section 14: entry point
# ---------------------------------------------------------------------------

CMD="${1:-check}"
case "$CMD" in
    check|restart|warm|status) ;;
    *)
        printf 'usage: qwen-serve-guard [check|restart|warm|status]\n' >&2
        exit 2
        ;;
esac

setup_dirs

if [ "$CMD" = "status" ]; then
    do_status
    exit 0
fi

log "guard.start cmd=$CMD version=$GUARD_VERSION"

acquire_lock
LOCK_RC=$?
if [ "$LOCK_RC" -eq 2 ]; then
    log "guard.lock.busy detail=\"another qwen-serve-guard run holds $LOCK_FILE; doing nothing\""
    log "guard.end cmd=$CMD rc=0"
    exit 0
fi
if [ "$LOCK_RC" -ne 0 ]; then
    log "guard.end cmd=$CMD rc=2"
    exit 2
fi

RC=0
case "$CMD" in
    check)
        if [ -f "$STANDDOWN_FILE" ]; then
            if probe_once "$HEALTH_BODY"; then
                log "guard.standdown state=healthy http=$PROBE_CODE rtt=$PROBE_RTT detail=\"$(standdown_reason)\""
            else
                log "guard.standdown state=unhealthy reason=$PROBE_REASON detail=\"$(standdown_reason)\""
            fi
            RC=0
        else
            do_check
            RC=$?
        fi
        ;;
    restart)
        do_restart "manual"
        RC=$?
        ;;
    warm)
        if warmup; then RC=0; else RC=1; fi
        ;;
esac

log "guard.end cmd=$CMD rc=$RC"
exit "$RC"
```

### 6.1 Non-obvious implementation notes (do not "simplify" these)

1. **`set -u` without `set -e`.** Every failure is handled by an explicit `if`; `set -e` would abort
   before the log line that explains why. Every variable a function assigns is pre-declared in the
   globals block precisely so `set -u` is safe.
2. **`/usr/bin/touch` before `exec 9>>`.** A failing `exec` *with redirections only* makes a
   non-interactive bash exit immediately, which would skip the diagnostic log line. The `touch`
   turns that into a testable condition.
3. **`grep -v -x "$$"` in `server_pids`.** Defensive self-exclusion. The guard's own argv does not
   contain `vllm serve`, so this should never fire; it costs nothing and makes a self-kill
   structurally impossible.
4. **`pgrep -f "VLLM::EngineCore"` is a separate pattern.** Verified: `pgrep -f "vllm serve"` matches
   only the API server. Without the second pattern an orphaned engine core could survive a kill and
   hold gigabytes.
5. **Two kill passes.** Killing the API server can orphan a fresh engine core, so the discover/kill
   loop runs at most twice, then re-checks and fails with `processes_remain` if anything is left.
6. **`wait_ready` sleeps *before* its first probe.** A probe issued the instant after `spawn_server`
   can only fail; sleeping first keeps the log clean of a guaranteed-useless failure.
7. **`run_with_timeout` returns the child's real exit status** by polling `kill -0` and then calling
   `wait`, and returns `124` (GNU `timeout`'s convention) when it has to kill. Verified: `0→0`,
   `3→3`, `2→2`, `7→7`, `sleep 30 with limit 2 → 124`.
8. **The `Terminated: 15` job message.** When `run_with_timeout` kills the warmup, bash prints a job
   notification. Because the call site redirects the whole function invocation's stderr to
   `$WARM_ERR`, that text lands in `warmup.err` and is surfaced by `warm_err_tail` — it does **not**
   pollute launchd's stderr. Verified.
9. **The warmup redirections belong at the `run_with_timeout` call site**, not inside the function:
   `</dev/null >"$WARM_OUT" 2>"$WARM_ERR"` is inherited by the `qwen-agent` child. `</dev/null` is
   the mechanism that guarantees criterion S10.
10. **`printf '%s' "$out" | awk '{print $1}'`** parses curl's `-w` output. `PROBE_CURL_RC` is read
    **immediately** after the assignment, before any other command can clobber `$?`.
11. **`sed -n 's/.*"status": "\([a-z_]*\)".*/\1/p'`** is a safe JSON parse here because [ONESHOT]
    Section 4.0 mandates `json.dumps` with default separators, so the envelope always contains the
    literal `"status": "..."` with exactly one space. Verified against live output. No `jq`
    dependency.
12. **`stat -f%z`** is the BSD form. `stat -c%s` (GNU) does not exist here.

---

## 7. Logging contract

### 7.1 Line format

Every guard log line is exactly:

```
<TIMESTAMP> <RUN_ID> <EVENT> [key=value ...]
```

- `TIMESTAMP` — `date "+%Y-%m-%dT%H:%M:%S%z"`, e.g. `2026-08-21T19:20:45-0400`.
- `RUN_ID` — `g` + the guard's PID, e.g. `g98242`. All lines from one tick share it; `grep g98242`
  reconstructs that tick.
- `EVENT` — one dotted token from the closed vocabulary in 7.2.
- Then zero or more `key=value` pairs. Values containing spaces are wrapped in `"…"`. Free text only
  ever appears inside a `detail="…"` value, and only after being passed through `clip` (control
  characters deleted, truncated to 200 chars), so **one event is always exactly one line**.

Real captured examples:

```
2026-08-21T19:20:45-0400 g98242 guard.start cmd=check version=1
2026-08-21T19:20:45-0400 g98242 check.healthy attempt=1/2 http=200 rtt=0.000945
2026-08-21T19:20:45-0400 g98242 guard.end cmd=check rc=0
2026-08-21T19:21:02-0400 g98439 guard.lock.busy detail="another qwen-serve-guard run holds /Users/reubenpatterson/.qwen-serve-guard/guard.lock; doing nothing"
2026-08-21T19:20:46-0400 g98302 guard.standdown state=healthy http=200 rtt=0.000767 detail="reason=manual paused by operator"
```

### 7.2 Event vocabulary (closed set — no other event token may be emitted)

| Event | Fields | When |
|---|---|---|
| `guard.start` | `cmd`, `version` | first line of every `check`/`restart`/`warm` run |
| `guard.end` | `cmd`, `rc` | last line of every such run |
| `guard.lock.busy` | `detail` | `lockf` could not acquire; this run does nothing |
| `guard.lock.unopenable` | `file` | `touch` on the lock path failed |
| `guard.state.unwritable` | `dir` | `$STATE_DIR` could not be created |
| `guard.standdown` | `state`, `http`/`reason`, `detail` | a `check` tick while the stand-down file exists |
| `check.healthy` | `attempt`, `http`, `rtt` | probe passed |
| `check.unhealthy` | `attempt`, `reason`, `http`, `curl_rc` | probe failed (one line per attempt) |
| `check.decision` | `restart_needed reason=` | all probe attempts failed |
| `restart.begin` | `trigger` (`check`\|`manual`) | a restart is starting |
| `restart.deferred` | `reason=young_process`, `age`, `threshold`, `detail` | Section 3.5 Case B |
| `restart.deferred.ready` | — | deferred start became ready and was warmed |
| `restart.deferred.notready` | `detail` | deferred start never became ready; left for the next tick |
| `restart.discover` | `pass`, `pids` | candidate PIDs found before a kill pass |
| `restart.discover.remain` | `pids` | processes survived two kill passes |
| `restart.kill` | `pid`, `signal=TERM` | `SIGTERM` sent |
| `restart.kill.escalate` | `pid`, `signal=KILL`, `after` | `SIGTERM` did not work within `TERM_WAIT` |
| `restart.kill.ok` | `pid`, `signal`, `after` | the PID is gone |
| `restart.kill.failed` | `pid`, `detail` | still alive `KILL_WAIT`s after `SIGKILL` |
| `restart.port.free` | `after` | the listener is gone |
| `restart.port.busy` | `detail` | port still `LISTEN` after `PORT_FREE_WAIT` |
| `restart.spawn` | `pid`, `log` | the new server process was launched |
| `restart.ready` | `after`, `http`, `rtt` | the new server answered `/v1/models` |
| `restart.notready` | `after`, `reason` | never answered inside `READY_TIMEOUT` |
| `restart.ok` | `trigger`, `elapsed` | the restart succeeded end to end |
| `restart.failed` | `reason`, `fail_count` | the restart failed; the counter was incremented |
| `breaker.tripped` | `fail_count`, `reason`, `detail` | `FAIL_LIMIT` reached; automation is now off |
| `standdown.cleared` | `reason=restart_succeeded` | a successful restart removed the stand-down file |
| `warm.begin` | `attempt`, `timeout` | a warmup attempt is starting |
| `warm.ok` | `attempt`, `elapsed`, `exit`, `status` | warmup completed (`exit` ∈ {0, 3}) |
| `warm.fail` | `attempt`, `elapsed`, `exit`, `status`, `detail` | warmup attempt failed |
| `warm.giveup` | `attempts`, `detail` | both attempts failed; restart still counts as successful |

`restart.failed` reasons, exhaustively: `vllm_binary_missing`, `model_path_missing`,
`unkillable_pid_<pid>`, `processes_remain`, `port_busy`, `not_ready`.

`check.unhealthy` reasons, exhaustively: `timeout_10s` (curl 28), `connect_refused` (curl 7),
`curl_rc_<n>` (any other curl error), `http_<code>` (non-200), `model_missing` (200 without
`"qwen38-6bit"` in the body).

### 7.3 Rotation

`rotate_if_needed FILE MAX` — if `stat -f%z FILE` ≥ `MAX`, `mv -f FILE FILE.1`. Exactly one
generation is kept; `FILE.1` is overwritten. `guard.log` is checked once per run, in `setup_dirs`
(safe: the guard opens it per write). `vllm-serve.log` is checked **only inside `spawn_server`**,
immediately before a new server is launched — renaming a file that a running server holds open would
not free any space, because the old server's fd follows the inode.

### 7.4 The external volume

The guard never reads or writes anything under `/Volumes/`. The two symlinks created at install
(Section 16 step 6) are a convenience for the operator; if `/Volumes/Ollama` is not mounted they are
simply not visible, and nothing degrades. If the volume is absent at install time, skip step 6 and
run it later — it is idempotent.

---

## 8. Locking contract

| Property | Value |
|---|---|
| Lock file | `/Users/reubenpatterson/.qwen-serve-guard/guard.lock` (0 bytes, content irrelevant) |
| Mechanism | `exec 9>>LOCK` then `/usr/bin/lockf -s -t 0 9` (`flock(2)` on the inherited open file description) |
| Scope | `check`, `restart`, `warm`. **Not** `status`, which must remain usable during a restart. |
| On contention | log `guard.lock.busy`, log `guard.end … rc=0`, `exit 0`. No probe, no kill, no spawn. |
| Release | implicit, by the kernel, when the guard process exits — including on `SIGKILL`, a panic, or a launchd teardown. **There is no stale-lock state and no cleanup step.** |
| Acquisition failures | `$STATE_DIR` uncreatable → `guard.state.unwritable`, exit `2`. `touch` fails → `guard.lock.unopenable`, exit `2`. |

The lock is acquired **after** `guard.start` is logged and **before** any probe, so a busy tick is
always visible in the log as exactly two lines.

---

## 9. Health check contract

**Command (exact):**

```
/usr/bin/curl -s -m 10 -o /Users/reubenpatterson/.qwen-serve-guard/health-body \
  -w '%{http_code} %{time_total}' http://127.0.0.1:8177/v1/models
```

**Healthy** requires all three of:

1. curl exit status `0`;
2. `%{http_code}` equal to `200`;
3. the response body contains the fixed substring `"qwen38-6bit"` (`grep -q -F`).

**Unhealthy** is any other outcome, classified per the reason list in 7.2.

**Decision rule:** `PROBE_ATTEMPTS = 2` attempts, `PROBE_RETRY_DELAY = 5` s apart. One pass ⇒
healthy, stop immediately. Two failures ⇒ unhealthy; the *second* failure's reason is carried into
`check.decision`. A failing tick costs ≤ 25 s.

Both attempts write to the same `health-body` file, so after any run that file holds the last
response body — useful when diagnosing a `model_missing` verdict. `status` uses a separate
`health-body.status` file so it never races a concurrent `check` for the same path.

---

## 10. Restart sequence contract

`do_restart TRIGGER` performs these steps in this order. Any step's failure aborts the sequence,
calls `record_failure` with the listed reason, and returns `1`.

| # | Step | Failure reason |
|---|---|---|
| 1 | log `restart.begin trigger=TRIGGER` | — |
| 2 | `[ -x $VLLM_BIN ]` | `vllm_binary_missing` |
| 3 | `[ -d $MODEL_PATH ]` | `model_path_missing` |
| 4 | up to **2 passes** of: discover candidates, `kill_pid` each | `unkillable_pid_<pid>` |
| 5 | re-discover; must be empty | `processes_remain` |
| 6 | `wait_port_free` (≤ 10 s) | `port_busy` |
| 7 | `spawn_server` | — (spawn itself cannot fail synchronously) |
| 8 | `wait_ready` (≤ 180 s, probe every 3 s) | `not_ready` |
| 9 | `warmup` (best effort; failure is logged, not fatal) | — |
| 10 | log `restart.ok`, `record_success` | — |

**Candidate discovery** is the sorted union of three sources, minus the guard's own PID:

```
lsof -nP -iTCP:8177 -sTCP:LISTEN -t      # whoever actually holds the port
pgrep -f "vllm serve"                    # the API server, even if it lost the port
pgrep -f "VLLM::EngineCore"              # the engine child, even if orphaned
```

**Kill escalation per PID:** `SIGTERM`, then poll `kill -0` once a second for 5 s; if still alive,
`SIGKILL`, then poll once a second for 5 s; if still alive, fail. This encodes the observed fact that
a wedged server can ignore `SIGTERM`.

**Spawn:** `nohup env VLLM_HOST_IP=127.0.0.1 <canonical command from Section 2.1>` with
stdout+stderr appended to `vllm-serve.log`, stdin `/dev/null`, backgrounded. `nohup` prevents
`SIGHUP` from a closing terminal (the manual case); the plist's `AbandonProcessGroup` prevents
launchd from killing it (the automatic case). Both are required; neither substitutes for the other.
A `===== qwen-serve-guard spawn <ts> <run_id> =====` banner is written to `vllm-serve.log` first, so
sessions are separable.

---

## 11. Warmup contract

### 11.1 Invocation (exact)

```
/Users/reubenpatterson/.local/bin/qwen-agent \
    --user-prompt "Reply with the single word OK. Do not use any tools." \
    --max-tokens 32 \
    --max-rounds 1 \
    --request-timeout 240 \
  </dev/null >~/Library/Logs/qwen-serve-guard/warmup.json \
             2>~/Library/Logs/qwen-serve-guard/warmup.err
```

wrapped in `run_with_timeout 300`.

### 11.2 Timeout helper

`run_with_timeout LIMIT CMD…`: start `CMD` in the background; poll `kill -0` once a second up to
`LIMIT`; if the child exits, `wait` and return **its** status; otherwise `SIGTERM`, sleep 3,
`SIGKILL`, and return `124`. This exists because macOS has no `timeout(1)` (Section 2). Verified
behaviour is listed in 6.1 note 7.

### 11.3 Outcome mapping

| `run_with_timeout` result | Verdict | Log |
|---|---|---|
| `0` — [ONESHOT] `status: "ok"` | success | `warm.ok … exit=0 status=ok` |
| `3` — [ONESHOT] abnormal turn (`max_rounds`, `network_error`, …) | **success** — the tool-schema path still round-tripped | `warm.ok … exit=3 status=<s>` |
| `2` — `qwen-agent` preflight failure | failure, retry | `warm.fail … exit=2` |
| `124` — our timeout | failure, retry | `warm.fail … exit=124` |
| anything else | failure, retry | `warm.fail … exit=<n>` |

Attempts: 2. If both fail, log `warm.giveup` and return `1`. **A warmup failure never calls
`record_failure`, never trips the breaker, and never fails the enclosing restart** — the server has
already proven reachable.

`status=` is parsed out of `warmup.json`; `none` means the file had no parseable status (for example
the process was killed before writing). `detail=` on a failure is the last line of `warmup.err`,
clipped.

---

## 12. State and the stand-down state machine

| File | Content | Meaning |
|---|---|---|
| `~/.qwen-serve-guard/fail-count` | one integer + `\n` | consecutive **failed restart attempts**. Absent, empty, or non-numeric is read as `0`. |
| `~/.qwen-serve-guard/stand-down` | one line, e.g. `reason=breaker tripped=2026-08-21T19:44:02-0400 fail_count=3 last_reason=not_ready` | present ⇒ **automatic restarts are off** |

Transitions:

| From | Event | To |
|---|---|---|
| `fail-count = n`, no stand-down | restart failed | `fail-count = n+1`; if `n+1 ≥ 3`, create `stand-down` with `reason=breaker` and log `breaker.tripped` |
| `fail-count = n`, no stand-down | restart succeeded | `fail-count = 0` |
| stand-down present | `check` tick | probe once, log one `guard.standdown` line, **do nothing else**, exit `0` |
| stand-down present | `restart` (manual) | proceed with the full restart regardless; on success `fail-count = 0` and the file is removed (`standdown.cleared`) |
| stand-down present | operator `rm` | fully re-armed; `fail-count` is left as-is and will be reset by the next successful restart |
| no stand-down | operator `touch` | automatic restarts paused (the operator's off switch) |

A healthy tick **never** clears the stand-down file — see Section 3.8 for why. `fail-count` counts
*restart attempts*, not ticks: a deferral (Case B) and a lock-busy tick both leave it untouched.

---

## 13. Subcommand behaviour matrix

| Subcommand | Lock | Probes | May kill | May spawn | May warm | Honours stand-down |
|---|---|---|---|---|---|---|
| `check` (default) | yes | 1–2 | yes | yes | yes | **yes** |
| `restart` | yes | ready-poll only | yes | yes | yes | no (proceeds, and clears it on success) |
| `warm` | yes | no | no | no | yes | no |
| `status` | **no** | 1 | no | no | no | reports it |

`check` full decision tree:

```
stand-down exists?  -> probe once, log guard.standdown, exit 0
health_check passes? -> exit 0
youngest candidate younger than 240s?
        -> log restart.deferred; wait_ready; if ready: warmup + restart.deferred.ready, exit 0
                                 else:      restart.deferred.notready, exit 0
otherwise            -> do_restart "check"
```

---

## 14. CLI contract and exit codes

```
usage: qwen-serve-guard [check|restart|warm|status]
```

- Exactly zero or one argument. No flags, no options, no `--help` (the usage line on a bad argument
  is the help).
- No argument ⇒ `check`. This is what the plist relies on being safe, though the plist passes
  `check` explicitly anyway.
- An unrecognised argument prints `usage: qwen-serve-guard [check|restart|warm|status]` to **stderr**
  and exits `2`, before any directory is created and before anything is logged.

| Exit | Meaning |
|---|---|
| `0` | Nothing was wrong, or something was wrong and was fixed. Covers: healthy tick; successful restart (even if the warmup failed); lock busy; stand-down tick; deferral; `warm` success; `status`. |
| `1` | A restart was attempted and failed (`check` or `restart`), or `warm` gave up. The reason is in the immediately preceding `restart.failed` / `warm.giveup` line. |
| `2` | Usage error, or the guard could not create/lock its own state directory. |

`status` writes its report to **stdout** and never writes to the guard log. Every other subcommand
writes nothing to stdout; all narration goes to the guard log (or, if that is unwritable, to stderr).

---

## 15. `~/Library/LaunchAgents/com.reubenpatterson.qwen-serve-guard.plist` — complete file

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.reubenpatterson.qwen-serve-guard</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/reubenpatterson/.local/bin/qwen-serve-guard</string>
        <string>check</string>
    </array>

    <key>StartInterval</key>
    <integer>300</integer>

    <key>RunAtLoad</key>
    <true/>

    <!-- REQUIRED. Without this, launchd kills the job's process group when the
         job exits, which would kill the vLLM server this job just spawned. -->
    <key>AbandonProcessGroup</key>
    <true/>

    <!-- Interactive, NOT Background: the spawned vLLM server inherits this
         job's QoS tier, and the Background tier throttles CPU and I/O, which
         would slow token generation for the whole session. -->
    <key>ProcessType</key>
    <string>Interactive</string>

    <key>WorkingDirectory</key>
    <string>/Users/reubenpatterson</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>HOME</key>
        <string>/Users/reubenpatterson</string>
    </dict>

    <key>StandardOutPath</key>
    <string>/Users/reubenpatterson/Library/Logs/qwen-serve-guard/launchd.out</string>
    <key>StandardErrorPath</key>
    <string>/Users/reubenpatterson/Library/Logs/qwen-serve-guard/launchd.err</string>
</dict>
</plist>
```

### 15.1 Keys that are deliberately absent

| Key | Why it is not here |
|---|---|
| `KeepAlive` | This is a periodic job, not a daemon. With `StartInterval` it would fight the schedule. |
| `ExitTimeOut` | The default (20 s) is correct. Setting it to `0` means *infinite*, which would hang a `bootout`. |
| `Nice`, `LowPriorityIO` | Defaults (0, false) are already what we want; setting them invites confusion with `ProcessType`. |
| `LimitLoadToSessionType` | Defaults to `Aqua` for a LaunchAgent, which is right — this needs a GUI login session. |
| `StartCalendarInterval` | Wrong tool: we want "every 5 minutes", not "at wall-clock times". |
| `ThrottleInterval` | Only relevant to respawn storms of a `KeepAlive` job. |
| `WatchPaths`, `QueueDirectories` | No file-triggered behaviour. |
| Anything about the vLLM server as its own job | Out of scope per 1.4. The server stays an ordinary orphaned process. |

### 15.2 Behaviour to expect from launchd

- **Single instance.** A tick that overruns 300 s does not get a second copy; launchd waits. The
  in-script lock (Section 8) covers the manual-invocation case launchd cannot see.
- **Sleep/wake.** A missed interval fires once on wake, not once per missed interval.
- **Non-zero exits** are recorded by launchd (`launchctl print` shows the last exit status) but do
  not change the schedule and do not disable the job.
- **`launchd.out` / `launchd.err` should stay empty** in normal operation. Content there means either
  the script could not write its own log, or bash emitted a job-control notice, or the script itself
  failed to exec — all worth reading.

---

## 16. Installation — exact commands

Run these in order, in a Terminal, as `reubenpatterson`. Each line is copy-pasteable.

```bash
# 1. Create the state and log directories with the intended modes.
mkdir -p /Users/reubenpatterson/.qwen-serve-guard
chmod 700 /Users/reubenpatterson/.qwen-serve-guard
mkdir -p /Users/reubenpatterson/Library/Logs/qwen-serve-guard
chmod 755 /Users/reubenpatterson/Library/Logs/qwen-serve-guard

# 2. Install the script (created per Section 6) and make it executable.
chmod 755 /Users/reubenpatterson/.local/bin/qwen-serve-guard

# 3. Syntax-check it before letting launchd anywhere near it.
/bin/bash -n /Users/reubenpatterson/.local/bin/qwen-serve-guard && echo "syntax OK"

# 4. Smoke-test by hand, with the server already running. Expect a HEALTHY line
#    and, from `check`, exit 0 plus three new log lines.
/Users/reubenpatterson/.local/bin/qwen-serve-guard status
/Users/reubenpatterson/.local/bin/qwen-serve-guard check ; echo "exit=$?"
tail -5 /Users/reubenpatterson/Library/Logs/qwen-serve-guard/guard.log

# 5. Install the plist (created per Section 15) and check its syntax.
chmod 644 /Users/reubenpatterson/Library/LaunchAgents/com.reubenpatterson.qwen-serve-guard.plist
plutil -lint /Users/reubenpatterson/Library/LaunchAgents/com.reubenpatterson.qwen-serve-guard.plist

# 6. Preserve the project logging convention (skip silently if the drive is not
#    mounted; re-run later -- it is idempotent).
if [ -d /Volumes/Ollama/vllm-metal/logs ]; then
  ln -sfn /Users/reubenpatterson/Library/Logs/qwen-serve-guard/guard.log \
          /Volumes/Ollama/vllm-metal/logs/guard.log
  ln -sfn /Users/reubenpatterson/Library/Logs/qwen-serve-guard/vllm-serve.log \
          /Volumes/Ollama/vllm-metal/logs/vllm-serve.log
  ls -l /Volumes/Ollama/vllm-metal/logs/guard.log /Volumes/Ollama/vllm-metal/logs/vllm-serve.log
fi

# 7. Load and enable the agent. `bootstrap` also runs it once (RunAtLoad).
launchctl bootstrap gui/$(id -u) \
  /Users/reubenpatterson/Library/LaunchAgents/com.reubenpatterson.qwen-serve-guard.plist
launchctl enable gui/$(id -u)/com.reubenpatterson.qwen-serve-guard
```

If step 7 reports `Bootstrap failed: 37: Operation already in progress` or `Input/output error`, the
job is already loaded from a previous attempt: run the `bootout` from 17.3 first, then `bootstrap`
again.

---

## 17. Operator runbook

### 17.1 Verify it is running

```bash
launchctl print gui/$(id -u)/com.reubenpatterson.qwen-serve-guard
```

Expect `state = waiting` (idle between ticks) or `state = running`, plus `runs = N` incrementing over
time and `last exit code = 0`. Then:

```bash
qwen-serve-guard status
```

Expect `health: HEALTHY`, `stand-down: no`, `launchd: loaded`. Confirm ticks are actually landing:

```bash
grep guard.start /Users/reubenpatterson/Library/Logs/qwen-serve-guard/guard.log | tail -5
```

Consecutive timestamps should be ~5 minutes apart.

### 17.2 Force a tick right now (do not wait 5 minutes)

```bash
launchctl kickstart gui/$(id -u)/com.reubenpatterson.qwen-serve-guard
```

### 17.3 Disable temporarily

Two levels, pick deliberately:

```bash
# Level 1 -- keep the agent loaded, stop it from restarting the server.
# Use this when you want the server down, or want to poke at it by hand.
touch /Users/reubenpatterson/.qwen-serve-guard/stand-down
# ... resume with:
rm /Users/reubenpatterson/.qwen-serve-guard/stand-down

# Level 2 -- unload the agent entirely (no ticks at all until re-bootstrapped
# or until the next login, since the plist stays on disk).
launchctl bootout gui/$(id -u)/com.reubenpatterson.qwen-serve-guard
# ... resume with:
launchctl bootstrap gui/$(id -u) \
  /Users/reubenpatterson/Library/LaunchAgents/com.reubenpatterson.qwen-serve-guard.plist
```

Level 1 is preferred for anything temporary: it is one file, it is visible in
`qwen-serve-guard status`, and it survives reboots the same way the agent does.

### 17.4 Read the logs

```bash
# What the watchdog has been doing.
tail -50 /Users/reubenpatterson/Library/Logs/qwen-serve-guard/guard.log

# Every decision from one tick (RUN_ID from the guard.start line).
grep g12345 /Users/reubenpatterson/Library/Logs/qwen-serve-guard/guard.log

# Restarts only.
grep -E 'restart\.(begin|ok|failed)|breaker' \
  /Users/reubenpatterson/Library/Logs/qwen-serve-guard/guard.log

# The server's own output, latest session last.
tail -100 /Users/reubenpatterson/Library/Logs/qwen-serve-guard/vllm-serve.log

# The last warmup in detail.
cat /Users/reubenpatterson/Library/Logs/qwen-serve-guard/warmup.json
cat /Users/reubenpatterson/Library/Logs/qwen-serve-guard/warmup.err

# launchd-level failures (should be empty).
cat /Users/reubenpatterson/Library/Logs/qwen-serve-guard/launchd.err

# Same files via the project convention, when the drive is mounted.
tail -50 /Volumes/Ollama/vllm-metal/logs/guard.log
```

### 17.5 Recover from a tripped breaker

```bash
qwen-serve-guard status      # shows stand-down: YES and the reason
grep -E 'restart\.failed|breaker\.tripped' \
  ~/Library/Logs/qwen-serve-guard/guard.log | tail -10
tail -100 ~/Library/Logs/qwen-serve-guard/vllm-serve.log   # why it would not start

# After fixing the underlying cause, either of these re-arms it:
qwen-serve-guard restart                      # fixes and re-arms in one step
rm ~/.qwen-serve-guard/stand-down             # re-arm only
```

### 17.6 Uninstall

```bash
launchctl bootout gui/$(id -u)/com.reubenpatterson.qwen-serve-guard
rm /Users/reubenpatterson/Library/LaunchAgents/com.reubenpatterson.qwen-serve-guard.plist
rm /Users/reubenpatterson/.local/bin/qwen-serve-guard
rm -rf /Users/reubenpatterson/.qwen-serve-guard
rm -f /Volumes/Ollama/vllm-metal/logs/guard.log /Volumes/Ollama/vllm-metal/logs/vllm-serve.log
# Logs are kept on purpose; delete them by hand if you want them gone:
#   rm -rf /Users/reubenpatterson/Library/Logs/qwen-serve-guard
```

The running vLLM server is untouched by an uninstall, and the manual launch command in Section 2.1
keeps working.

### 17.7 Restarting the server by hand — the one rule

**Use `qwen-serve-guard restart`, not the raw `vllm serve` line.** It takes the lock (so the watchdog
cannot interfere, Section 3.5 Case A), it uses the byte-identical canonical command, it waits for
readiness, and it warms the server so your first request is not the slow one. Typing the raw command
still works, and Case B's young-process rule keeps the watchdog from killing it, but you lose the
lock, the warmup, and the log entry.

---

## 18. Acceptance tests

Run in order. T1–T3 and T8–T11 are safe at any time. T4–T7 deliberately break things and each ends
with a restore step.

| # | Test | Procedure | Pass criteria |
|---|---|---|---|
| **T1** | Static checks | `bash -n qwen-serve-guard`; `plutil -lint …plist`; `grep -n 'local -A\|mapfile\|,,\|readarray' qwen-serve-guard` | first two clean; third finds nothing |
| **T2** | Healthy tick (S1) | server up; note `lsof -t -i:8177`; `qwen-serve-guard check` | exit `0`; exactly 3 new log lines (`guard.start`, `check.healthy`, `guard.end`); PID unchanged |
| **T3** | `status` output | `qwen-serve-guard status` | 10 aligned lines; `health: HEALTHY`; correct PIDs; `port 8177: LISTEN pid …`; `fail count: 0 / 3`; `stand-down: no`; `launchd: loaded` |
| **T4** | Hang detection (S2) | wedge the server: `kill -STOP <api_pid>`; then `qwen-serve-guard check` | two `check.unhealthy … reason=timeout_10s`; `restart.kill` (+`restart.kill.escalate`, since a `SIGSTOP`ped process cannot handle `SIGTERM`); `restart.spawn`; `restart.ready after=…s` with `…` ≤ 60; `warm.ok`; `restart.ok`; exit `0`; `curl -m 10 …/v1/models` returns 200 |
| **T5** | Dead server (S3) | `qwen-serve-guard restart` then kill the new server and immediately `touch`-age nothing; wait 5 minutes so the absence is not "young"; `qwen-serve-guard check` | `check.unhealthy … connect_refused` ×2; no `restart.kill*` lines; `restart.spawn`; `restart.ready`; `warm.ok`; `restart.ok` |
| **T6** | Lock (S5) | `qwen-serve-guard restart &` then, 2 s later, `qwen-serve-guard check` | the second logs `guard.lock.busy`, exits `0`, and emits **no** `check.healthy`/`check.unhealthy`/`restart.*` line |
| **T7** | Breaker (S6) | `sudo mv ~/mlx_models/Huihui-Qwen3.8-27B-abliterated-mlx-6bit{,.bak}`; run `check` three times; then a fourth | runs 1–3 log `restart.failed reason=model_path_missing fail_count=n/3` and exit `1`; run 3 also logs `breaker.tripped`; run 4 logs exactly one `guard.standdown` line and exits `0`. **Restore:** `mv` back, `qwen-serve-guard restart` → `restart.ok` + `standdown.cleared`, `fail count: 0 / 3` |
| **T8** | Young-process deferral | start the server with the raw Section 2.1 command; within 20 s run `qwen-serve-guard check` | `restart.deferred reason=young_process age=<20 …`; **no** `restart.kill`; then `restart.ready` and `warm.ok`; the hand-started PID is unchanged |
| **T9** | Warmup effect (S4) | immediately after any `restart.ok`, run `qwen-agent --user-prompt "Say hello."` and read the server log | `Avg generation throughput` on that request ≥ 2.0 tok/s (not ~0.1) |
| **T10** | Volume independence (S9) | eject `/Volumes/Ollama`; run `status`, `check`, `warm` | all behave exactly as with the volume mounted; new lines land in `~/Library/Logs/qwen-serve-guard/guard.log`; **no directory named `Ollama` is created under `/Volumes`** |
| **T11** | launchd end-to-end (S8) | `launchctl kickstart gui/$(id -u)/…`; then reboot, log in, wait 60 s | `guard.start cmd=check` appears after the kickstart and again after login; `launchctl print` shows `runs` incrementing and `last exit code = 0`; `launchd.err` stays empty |
| **T12** | Rotation | `dd if=/dev/zero bs=1m count=6 >> guard.log`; run `check` | `guard.log.1` exists at ~6 MB; `guard.log` is small and holds only the new run's lines |
| **T13** | Usage | `qwen-serve-guard bogus` | usage line on stderr, exit `2`, **nothing** appended to the guard log, no directories created |
| **T14** | `qwen-agent` untouched (S11) | `diff <(git-free backup copy) /Users/reubenpatterson/.local/bin/qwen-agent` | empty |
| **T15** | Orphaned engine core | `kill -9 <api_pid>` only, leaving `VLLM::EngineCore`; then `qwen-serve-guard check` | `restart.discover` lists the engine core PID; it is killed; `restart.ok` follows; `pgrep -f VLLM::EngineCore` returns nothing afterwards |

---

## 19. Must-haves vs. nice-to-haves

### 19.1 Must-haves (not shippable without these)

1. `check` detects a wedged server via the HTTP probe and repairs it. (S2)
2. Every successful start is followed by the `qwen-agent` warmup with stdin `/dev/null` and a
   bounded timeout. (S4, S10)
3. `lockf`-based mutual exclusion so ticks and manual runs never overlap destructively. (S5)
4. `SIGTERM` → `SIGKILL` escalation, including the orphaned `VLLM::EngineCore`.
5. Three-strike stand-down with a logged reason and a one-command human reset. (S6, S7)
6. launchd agent with `StartInterval 300`, `RunAtLoad`, and **`AbandonProcessGroup true`**. (S8)
7. Every tick, decision, and warmup result on one grep-able line in a log that does not depend on
   `/Volumes`. (S9)
8. Not one byte of `qwen-agent` changes. (S11)
9. The spawn command is byte-equivalent to Section 2.1, `VLLM_HOST_IP` included.
10. `qwen-serve-guard restart` is the shared start-and-warm path a human uses.

### 19.2 Nice-to-haves (explicitly deferred; do not build now)

1. **A longer warmup.** If T9 shows the throughput ramp persisting past the first request, change
   `WARM_PROMPT` to `"Count from 1 to 40, separated by spaces. Do not use any tools."` and
   `WARM_MAX_TOKENS` to `128`, which forces ~80 decode steps in one request instead of paying prefill
   twice. Constants only, no structural change.
2. **A `--think` warmup pass** to compile the reasoning-parser path as well. Only worth it if the
   user actually starts using `--think` routinely.
3. **An hourly keep-alive ping** to test whether idle-triggered wedging can be *prevented* rather
   than repaired. This is an experiment with a hypothesis to record, not a feature.
4. **Notification Center alert on `breaker.tripped`** (`osascript -e 'display notification …'`).
   Deferred because the failure is rare and `status` already shows it.
5. **`fail-count` decay** (e.g. forgive one strike per healthy hour). Deferred: three strikes at
   5-minute spacing already tolerates real transients, and decay makes the state machine harder to
   reason about.
6. **Multiple rotated log generations.** One `.1` is enough for a personal tool.

---

## 20. Assumptions recorded

Minimal calls made where the brief was silent. Each is a decision, not a guess to revisit mid-build.

- **A1 — the guard is a supervisor, so the server auto-starts at login.** "Detects a dead/hung
  server and restarts it" is read as covering *absent* as well as *wedged*, because a watchdog cannot
  distinguish "intentionally down" from "crashed". With `RunAtLoad`, that means the ~22 GB server
  comes up after each login. Opt out with `touch ~/.qwen-serve-guard/stand-down`. (Section 3.9)
- **A2 — health means "correct model, promptly".** The probe requires the body to contain
  `"qwen38-6bit"`, not merely HTTP 200, because a 200 from the wrong model is useless to
  `qwen-agent`. A restart with the canonical command fixes that case, so it is restart-worthy.
- **A3 — two probe attempts, no client-activity check.** Chosen over a single probe (false positives
  kill live sessions) and over "defer while a `qwen-agent` process exists" (which would defer forever
  in exactly the wedged case the watchdog exists for).
- **A4 — the stand-down file is both the breaker latch and the operator's pause switch**, and is
  never auto-cleared by a healthy tick. A successful *explicit* `restart` clears it, because that is
  itself the human intervention the breaker was waiting for.
- **A5 — logs live on the internal disk and are symlinked into
  `/Volumes/Ollama/vllm-metal/logs/`.** The convention is honoured without the dependency; writing
  into an unmounted mount point would shadow the mount, which is worse than any benefit. (Section 3.7)
- **A6 — `YOUNG_SECS = 240`.** Above `READY_TIMEOUT` (180 s) and ~9× the measured 26 s startup, so a
  legitimate in-progress start is never killed; low enough that a genuinely wedged server (observed
  only after ~5 hours idle) is never spared. A deferral self-clears at the next tick.
- **A7 — a restart may kill an in-flight client turn.** Not mitigated: if the server is wedged, the
  client is already stuck and unrecoverable. The client sees `qwen-agent`'s existing
  `network_error` path ([HARNESS] Section 12), which is a handled outcome.
- **A8 — `check` is the default subcommand** so that a bare `qwen-serve-guard` is the safe read-mostly
  action, never a restart.
- **A9 — warmup exit `3` counts as success.** [ONESHOT] exit `3` still means a full round trip
  through the tool-schema path happened, which is the whole point of warming.
- **A10 — two kill passes, then give up.** Enough to catch an engine core orphaned by the first pass;
  bounded so a pathological process cannot loop the guard.
- **A11 — rotation keeps exactly one old generation**, sized 5 MiB (guard) / 50 MiB (server). At the
  measured ~29 KB/day of healthy ticks that is over a year of history.
- **A12 — no `sudo` anywhere.** Everything runs as `reubenpatterson`; the model, venv, logs, and
  state are all user-owned. If any step needs `sudo`, something is wrong — stop and ask.
- **A13 — `ProcessType Interactive`.** The spawned server inherits the job's QoS tier, so the
  `Background` tier would throttle inference for the whole session. `Interactive` is the correct
  tier for a job whose child serves interactive requests.

---

## 21. Open questions

None blocking. Three worth revisiting after a week of real operation:

1. **Is one warmup request enough?** The observed ramp ("~0.1 tok/s climbing to 4–10 tok/s over the
   next few requests") suggests the compile cost may be spread over more than one request. T9
   measures this. If it fails, apply nice-to-have 19.2.1 — constants only.
2. **Does the ~5-hour idle wedge survive a restart cadence, or is it triggered by sleep/wake?** The
   guard's log will, for the first time, give a timestamped history of every occurrence
   (`restart.begin trigger=check` lines). After several data points, correlate against
   `pmset -g log` to test the sleep hypothesis. That is the input to any future *prevention* work
   (19.2.3), and it should be written back into
   `feedback_vllm_metal_idle_memory_reclaim.md`.
3. **Should `/Volumes/Ollama/vllm-metal/logs/` remain the documented convention at all?** This spec
   satisfies it by symlink, but the project's real logging root is now effectively
   `~/Library/Logs/qwen-serve-guard/`. If more components move off the external drive, promote the
   local path to the convention and retire the symlinks. Not this change.
