"""movie_ui_lib -- the movie-ui core: STATE files, the job store and queue, the detached job
runner, the command builder, validation checks V1-V7 and the progress parser.

See docs/superpowers/specs/2026-10-19-movie-ui-design.md (the movie-ui spec, piece F).
Standard library only (GC2): this module never imports or loads by path any pipeline module
(GC7); catalog, character and dry-run data come from the selected workspace's own bin/ tools
run as subprocesses. Valid on Python 3.9 and 3.13 (GC1). Every file it writes is written
atomically, mode 0600; every directory it creates is mode 0700 (GC10).
"""

import calendar
import fcntl
import http.client
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time

# ---------------------------------------------------------------------------
# Constants, times, atomic writes, STATE and the job store (GC9, GC10, MU2, MU15-MU19, MU28)
# ---------------------------------------------------------------------------

STATE_PATH = "~/.local/share/qwen-agent/movie-ui"   # MU2; expanded at every use
STATE_SUBDIRS = ("jobs", "uploads", "traces", "smoke")
JOB_SCHEMA = "movie-ui.job.v1"
SAVED_TRACE_SCHEMA = "movie-ui.saved-trace.v1"
JOB_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{64}\.(png|jpg|webp)$")
STORY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
CHARACTER_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,23}$")
ACTION_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")   # action_lib.NAME_RE
SMOKE_STORY_ID = "movie-ui-smoke"
CANCEL_GRACE_S = 15.0       # MU21; tests set it lower
STARTING_GRACE_S = 10.0     # MU29: a dispatched runner has this long to take its lock
ACTIVE_STATES = ("starting", "running")
FINAL_STATES = ("done", "failed", "cancelled")
FINISHED_STATES = ("done", "failed", "cancelled", "lost")
# Every regex above is applied with .fullmatch().


def utc_now():
    """The current time as UTC YYYY-MM-DDTHH:MM:SSZ (GC9)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_utc(text):
    """Epoch seconds for a utc_now() string, or None."""
    try:
        return calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return None


def state_dir():
    """STATE = ~/.local/share/qwen-agent/movie-ui, host-wide (MU2)."""
    return os.path.expanduser(STATE_PATH)


def make_dir(path):
    """Create path (and missing parents) if absent; the leaf is mode 0700 (GC10)."""
    if not os.path.isdir(path):
        os.makedirs(path, 0o700, exist_ok=True)
        os.chmod(path, 0o700)


def ensure_state(state):
    """Create STATE and its jobs, uploads, traces and smoke directories (MU2)."""
    make_dir(state)
    for name in STATE_SUBDIRS:
        make_dir(os.path.join(state, name))


def _unlink_quiet(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def write_bytes_atomic(path, data):
    """Write data to <path>.tmp-<pid>-<thread id>, close it, os.replace it onto path; 0600 (GC10)."""
    tmp = "%s.tmp-%d-%d" % (path, os.getpid(), threading.get_ident())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        _unlink_quiet(tmp)
        raise


def write_json_atomic(path, obj):
    """obj as indented UTF-8 JSON plus a newline, written by write_bytes_atomic."""
    write_bytes_atomic(path, (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def read_json(path, default=None):
    """The parsed JSON file at path, or default when it is missing or does not parse."""
    try:
        with open(path, "rb") as f:
            return json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return default


def jobs_root(state):
    return os.path.join(state, "jobs")


def job_dir(state, job_id):
    return os.path.join(state, "jobs", job_id)


def queue_path(state):
    return os.path.join(state, "queue.json")


def read_job(jdir):
    """job.json of one job directory as a dict, or None (MU15)."""
    job = read_json(os.path.join(jdir, "job.json"))
    return job if isinstance(job, dict) else None


def read_status(jdir):
    """status.json of one job directory as a dict, or None while queued or unreadable (MU16)."""
    status = read_json(os.path.join(jdir, "status.json"))
    return status if isinstance(status, dict) else None


def write_status(jdir, status):
    write_json_atomic(os.path.join(jdir, "status.json"), status)


def read_queue(state):
    """queue.json as a list of job IDs; missing or invalid JSON gives [] (MU18, MU31)."""
    queue = read_json(queue_path(state), [])
    return [i for i in queue if isinstance(i, str)] if isinstance(queue, list) else []


def write_queue(state, ids):
    write_json_atomic(queue_path(state), list(ids))


def list_job_ids(state):
    """Sorted IDs of every jobs/<id> directory whose name matches JOB_ID_RE and that has a
    readable job.json (MU32)."""
    try:
        names = os.listdir(jobs_root(state))
    except OSError:
        return []
    return sorted(n for n in names
                  if JOB_ID_RE.fullmatch(n) and read_job(job_dir(state, n)) is not None)


def new_job_id(state):
    """A fresh job ID: UTC %Y%m%d-%H%M%S, "-", 4 hex digits; drawn again while jobs/<id>
    exists (MU28)."""
    while True:
        job_id = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(2)
        if not os.path.lexists(job_dir(state, job_id)):
            return job_id


def create_job(state, job_id, kind, workspace, story_id, character, argv, fields):
    """Create jobs/<id>/ with job.json and an empty log.txt and append the ID to queue.json
    (MU15, MU28). The caller holds STORE_LOCK. Returns the job.json object."""
    jdir = job_dir(state, job_id)
    os.mkdir(jdir, 0o700)
    os.chmod(jdir, 0o700)
    job = {"schema": JOB_SCHEMA, "id": job_id, "kind": kind, "workspace": workspace,
           "story_id": story_id, "character": character, "argv": list(argv),
           "fields": fields, "vlm": job_vlm(kind, fields, workspace, story_id), "created": utc_now()}
    write_json_atomic(os.path.join(jdir, "job.json"), job)
    write_bytes_atomic(os.path.join(jdir, "log.txt"), b"")
    write_queue(state, read_queue(state) + [job_id])
    return job


# ---------------------------------------------------------------------------
# The job runner (MU21-MU25): bin/movie-ui-job calls run_job
# ---------------------------------------------------------------------------

RUNNERS = []    # Popen objects of launched runners, polled (never waited for) to reap them


def _say(text):
    """One runner line on stdout (log.txt when dispatched), prefixed "[movie-ui] " (MU17)."""
    sys.stdout.write("[movie-ui] %s\n" % text)
    sys.stdout.flush()


def launch_runner(state, job_id, ui_ws):
    """Start bin/movie-ui-job for one job in its own session, its output appended to log.txt,
    without waiting for it (MU21). Raises OSError when it cannot be started."""
    jdir = job_dir(state, job_id)
    RUNNERS[:] = [p for p in RUNNERS if p.poll() is None]
    log = open(os.path.join(jdir, "log.txt"), "ab")
    try:
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ui_ws, "bin", "movie-ui-job"), "--grace", repr(CANCEL_GRACE_S), jdir],
            start_new_session=True, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            cwd=jdir, env=dict(os.environ, PYTHONUNBUFFERED="1"), close_fds=True)
    finally:
        log.close()
    RUNNERS.append(proc)
    return proc


def _killpg_quiet(group, sig):
    try:
        os.killpg(group, sig)
    except (ProcessLookupError, PermissionError):
        pass


def group_alive(group):
    """False only when os.killpg(group, 0) raises ProcessLookupError."""
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_table():
    """[(pid, ppid, pgid)] from ps -A -o pid=,ppid=,pgid= (timeout 5 s), or None when ps fails."""
    try:
        proc = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,pgid="], stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    rows = []
    for line in proc.stdout.decode("ascii", "replace").splitlines():
        parts = line.split()
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            rows.append((int(parts[0]), int(parts[1]), int(parts[2])))
    return rows


def descendant_groups(root_pid, table):
    """Sorted {root_pid} | {pgid of every transitive descendant of root_pid} (MU23 step 1)."""
    children = {}
    for pid, ppid, pgid in table:
        children.setdefault(ppid, []).append((pid, pgid))
    groups, seen, stack = {root_pid}, set(), [root_pid]
    while stack:
        for pid, pgid in children.get(stack.pop(), []):
            if pid not in seen:
                seen.add(pid)
                groups.add(pgid)
                stack.append(pid)
    return sorted(groups)


def cancel_groups(child_pid):
    """The process groups a cancel signals: the child's group and every process group of its
    descendants (MU23 step 1, D1, Q1)."""
    table = process_table()
    if table is None:
        _say("ps failed; signalling process group %d only" % child_pid)
        return [child_pid]
    return descendant_groups(child_pid, table)


def cancel_tree(child, grace):
    """SIGTERM every group of cancel_groups, poll every 0.2 s for grace seconds, SIGKILL the
    groups still present, then reap the child (MU23 steps 2-4)."""
    groups = cancel_groups(child.pid)
    for group in groups:
        _killpg_quiet(group, signal.SIGTERM)
    _say("cancel: SIGTERM to process group(s) %s" % " ".join(str(g) for g in groups))
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        child.poll()
        if child.returncode is not None and not any(group_alive(g) for g in groups):
            break
        time.sleep(0.2)
    child.poll()
    left = [g for g in groups if group_alive(g)]
    for group in left:
        _killpg_quiet(group, signal.SIGKILL)
    if left:
        _say("cancel: SIGKILL to process group(s) %s" % " ".join(str(g) for g in left))
    child.wait()


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
    finally:
        log.close()
    running = {"state": "running", "dispatched": status.get("dispatched"), "runner_pid": os.getpid(),
               "pgid": child.pid, "started": utc_now()}
    write_status(jdir, running)
    _say("started pid %d: %s" % (child.pid, shlex.join(job["argv"])))
    signalled = False
    while True:
        try:
            child.wait(timeout=1)
            break
        except subprocess.TimeoutExpired:
            if not signalled and os.path.exists(cancel):
                signalled = True
                cancel_tree(child, grace)
    code = child.returncode
    state = "cancelled" if os.path.exists(cancel) else ("done" if code == 0 else "failed")
    final = dict(running)
    final.update({"state": state, "exit_code": code, "ended": utc_now()})
    write_status(jdir, final)
    _say("exit %d (%s)" % (code, state))
    vlm_postflight(state_root)
    return 0


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
    if port == 8178:
        return "failed", "VLM preflight refused: MOVIE_UI_VLM_PORT=8178 is the embed server's port; unset it"
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
# Every function here that reads or writes queue.json or a status is called with STORE_LOCK
# held (movie_ui_server.STORE_LOCK).
# ---------------------------------------------------------------------------

def job_alive(jdir, now=None):
    """True while a runner holds jdir/lock, or the job is "starting" and was dispatched less than
    STARTING_GRACE_S ago; otherwise False, after writing the "lost" status when the job was
    starting or running (MU29). Never consults a PID (MU25)."""
    fd = os.open(os.path.join(jdir, "lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        try:
            status = read_status(jdir) or {}
            state = status.get("state")
            if state not in ACTIVE_STATES:
                return False
            if state == "starting":
                dispatched = parse_utc(status.get("dispatched"))
                current = time.time() if now is None else now
                if dispatched is not None and current - dispatched < STARTING_GRACE_S:
                    return True
            lost = dict(status)
            lost.update({"state": "lost", "exit_code": None, "ended": None, "detected": utc_now()})
            write_status(jdir, lost)
            return False
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def active_job_ids(state):
    """IDs of the jobs whose status state is "starting" or "running"."""
    return [i for i in list_job_ids(state)
            if (read_status(job_dir(state, i)) or {}).get("state") in ACTIVE_STATES]


def dispatch_tick(state, ui_ws):
    """One dispatcher tick (MU30). Returns the ID of the job it dispatched, else None."""
    for job_id in active_job_ids(state):
        if job_alive(job_dir(state, job_id)):
            return None
    for job_id in list_job_ids(state):
        if orphan_info(read_status(job_dir(state, job_id))) is not None:
            return None
    if VLM_RECOVERY:
        reason = "; ".join(VLM_RECOVERY)
        del VLM_RECOVERY[:]
        recovery_restore(state, ui_ws, reason)
    queue = read_queue(state)
    while queue:
        job_id = queue.pop(0)
        jdir = job_dir(state, job_id)
        if os.path.lexists(os.path.join(jdir, "status.json")):
            write_queue(state, queue)
            continue
        job = read_job(jdir)
        if job is None:
            write_queue(state, queue)
            continue
        if not os.path.isdir(job["workspace"]):
            write_status(jdir, {"state": "failed", "exit_code": None, "ended": utc_now(),
                                "error": "workspace no longer exists (removed by self-update)"})
            write_queue(state, queue)
            continue
        dispatched = utc_now()
        write_status(jdir, {"state": "starting", "dispatched": dispatched})
        write_queue(state, queue)
        try:
            launch_runner(state, job_id, ui_ws)
        except OSError as e:
            write_status(jdir, {"state": "failed", "dispatched": dispatched, "exit_code": None,
                                "ended": utc_now(), "error": "cannot start runner: %s" % (e.strerror or e)})
        return job_id
    return None


def startup_recovery(state):
    """Rewrite queue.json without IDs that are malformed, duplicated, lack job.json or already
    have a status; then re-attach or mark lost every starting/running job (MU31), and queue the
    startup VLM restore for the first idle dispatcher tick (VLM lifecycle spec VU2)."""
    kept = []
    for job_id in read_queue(state):
        jdir = job_dir(state, job_id)
        if (JOB_ID_RE.fullmatch(job_id) and job_id not in kept
                and os.path.isfile(os.path.join(jdir, "job.json"))
                and not os.path.lexists(os.path.join(jdir, "status.json"))):
            kept.append(job_id)
    write_queue(state, kept)
    for job_id in active_job_ids(state):
        job_alive(job_dir(state, job_id))
    _vlm_recheck("startup")


def job_state(state, job_id, queue):
    """The status state, else "queued" when job_id is in queue, else "unknown" (MU67)."""
    status = read_status(job_dir(state, job_id))
    if status is not None and isinstance(status.get("state"), str):
        return status["state"]
    return "queued" if job_id in queue else "unknown"


def cancel_job(state, job_id):
    """"cancelled" for a queued job (removed from the queue), "cancelling" for a starting or
    running one (the cancel marker is created), None otherwise (MU68)."""
    queue = read_queue(state)
    current = job_state(state, job_id, queue)
    jdir = job_dir(state, job_id)
    if current == "queued":
        write_queue(state, [i for i in queue if i != job_id])
        write_status(jdir, {"state": "cancelled", "exit_code": None, "ended": utc_now()})
        return "cancelled"
    if current in ACTIVE_STATES:
        write_bytes_atomic(os.path.join(jdir, "cancel"), b"")
        return "cancelling"
    return None


def move_job(state, job_id, direction):
    """Swap a queued job with its neighbour ("up" or "down"; a no-op at an end). Returns the new
    queue, or None when the job is not queued (MU68)."""
    queue = read_queue(state)
    if job_id not in queue or job_state(state, job_id, queue) != "queued":
        return None
    i = queue.index(job_id)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(queue):
        queue[i], queue[j] = queue[j], queue[i]
        write_queue(state, queue)
    return queue


def delete_job(state, job_id):
    """Remove a finished (done, failed, cancelled, lost) job's directory; True when removed,
    False when the job is not finished (MU68). Story outputs are never touched."""
    if job_state(state, job_id, read_queue(state)) not in FINISHED_STATES:
        return False
    job = read_job(job_dir(state, job_id)) or {}
    sdir = os.path.join(state, "smoke", job_id)
    if job.get("kind") == "smoke" and os.path.lexists(sdir):
        shutil.rmtree(sdir)
    shutil.rmtree(job_dir(state, job_id))
    return True


def orphan_info(status):
    """{"pgid": G, "alive": True} for a lost job whose recorded group still exists, else None
    (MU26)."""
    if not isinstance(status, dict) or status.get("state") != "lost":
        return None
    pgid = status.get("pgid")
    if not isinstance(pgid, int) or isinstance(pgid, bool) or pgid <= 1 or pgid >= 2 ** 31 or pgid == os.getpgrp():
        return None
    return {"pgid": pgid, "alive": True} if group_alive(pgid) else None


def kill_orphan(state, job_id):
    """SIGKILL a lost job's live orphan group; returns the pgid, or None when there is none (MU68)."""
    info = orphan_info(read_status(job_dir(state, job_id)))
    if info is None:
        return None
    try:
        os.killpg(info["pgid"], signal.SIGKILL)
    except ProcessLookupError:
        pass
    return info["pgid"]


# ---------------------------------------------------------------------------
# Compose fields, the command builder and light subprocesses (MU36-MU41, MU59)
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "dgrauet/ltx-2.3-mlx-q8"                     # bin/ltx-movie:318
DEFAULT_GEMMA = "mlx-community/gemma-3-12b-it-4bit"          # bin/ltx-movie:319-323
STILLS_BASE_MODEL = "Tongyi-MAI/Z-Image-Turbo"               # lora_catalog.py:29
ZIMAGE_TEXT_ENCODER = "BennyDaBall/Qwen3-4b-Z-Image-Turbo-AbliteratedV1"   # z_image_skill.py:53
ACTIONS = ("story", "regenerate", "movie", "redo", "smoke")
MODES = ("chained", "shots", "no_stills")
LORA_KINDS = ("style", "motion", "physics")
OPTION_DEFAULTS = {"panels": 15, "fps": 24, "frames": 145, "model": DEFAULT_MODEL,
                   "gemma": DEFAULT_GEMMA, "panel_timeout": 7200}   # MU47
DEFAULT_FIELDS = {
    "ws": None, "action": "story",
    "story_id": "", "narrative": "", "goal": None,
    "panels": 15, "length": None, "fps": 24, "frames": 145,
    "width": None, "height": None, "seed_upload": None,
    "mode": "chained",
    "model": DEFAULT_MODEL, "gemma": DEFAULT_GEMMA,
    "story_model": None,
    "auto_lora": True, "narration": "full",
    "video_loras": [], "stills_loras": [],
    "characters": [], "action_loras": [],
    "story_legacy": False, "judge": False, "no_low_ram": False, "panel_timeout": None,
    "overwrite_movie": False, "redo": [],
}
NARRATION_MODES = ("full", "speech", "none")   # voice-over and speech / speech only / none
LIGHT_TIMEOUT = 60
# MU37: the flags each compose field or action needs; "supported" (MU47) is all-present.
FIELD_FLAGS = (
    ("story_id", ("--story-id",)), ("panels", ("--panels",)), ("length", ("--length",)),
    ("fps", ("--fps",)), ("frames", ("--frames",)),
    ("resolution", ("--video-width", "--video-height")), ("seed_upload", ("--seed-image",)),
    ("model", ("--model",)), ("gemma", ("--gemma",)), ("story_model", ("--story-model",)),
    ("goal", ("--goal",)), ("shots", ("--shots",)), ("no_stills", ("--no-stills",)),
    ("video_loras", ("--lora",)), ("stills_loras", ("--stills-lora",)),
    ("characters", ("--character",)), ("action_loras", ("--action",)),
    ("auto_lora", ("--no-auto-lora",)), ("narration", ("--no-narration", "--speech-only")),
    ("story_legacy", ("--story-legacy",)), ("judge", ("--judge",)), ("no_low_ram", ("--no-low-ram",)),
    ("panel_timeout", ("--panel-timeout",)), ("overwrite_movie", ("--force",)),
    ("regenerate", ("--force-story",)), ("redo", ("--redo",)), ("story_only", ("--story-only",)),
    ("no_review", ("--no-review",)),
)


def compose_fields(body):
    """The MU36 field object: every DEFAULT_FIELDS key, taken from body when present (unknown
    keys are ignored). Values are not validated here (V1 does that)."""
    fields = {}
    for key, default in DEFAULT_FIELDS.items():
        value = body.get(key, default) if isinstance(body, dict) else default
        fields[key] = list(value) if isinstance(value, list) else value
    if isinstance(fields["narration"], bool):   # jobs saved before the three-way setting
        fields["narration"] = "full" if fields["narration"] else "none"
    return fields


def goal_text(goal):
    """--goal's text as bin/ltx-movie's _parse_goal leaves it: stripped, one trailing "." removed
    and right-stripped (V1 rule 3)."""
    text = goal.strip()
    if text.endswith("."):
        text = text[:-1].rstrip()
    return text


def ordered(loras):
    """motion and physics items first, then every other item, each in submitted order (MU39)."""
    return ([item for item in loras if item.get("kind") in ("motion", "physics")]
            + [item for item in loras if item.get("kind") not in ("motion", "physics")])


def lora_arg(item):
    """PATH:STRENGTH for one LoRA item, the strength as repr(float(s)) (MU40 step 8)."""
    return "%s:%s" % (item["path"], repr(float(item["strength"])))


def action_arg(item):
    """NAME or NAME:STRENGTH for one action item (bin/ltx-movie --action)."""
    if item.get("strength") is None:
        return item["name"]
    return "%s:%s" % (item["name"], repr(float(item["strength"])))


def build_argv(fields, ws_real, state, py=sys.executable):
    """The bin/ltx-movie argv for actions story, regenerate, movie and redo (MU40). Pure; the
    fields have passed V1."""
    action = fields["action"]
    argv = [py, os.path.join(ws_real, "bin", "ltx-movie"), fields["narrative"].strip(),
            "--story-id", fields["story_id"]]
    if fields["panels"] is not None:
        argv += ["--panels", str(fields["panels"])]
    else:
        argv += ["--length", repr(float(fields["length"]))]
    argv += ["--fps", str(fields["fps"]), "--frames", str(fields["frames"])]
    if fields["seed_upload"]:
        argv += ["--seed-image", os.path.join(state, "uploads", fields["seed_upload"])]
    elif fields["width"] is not None and fields["height"] is not None:
        argv += ["--video-width", str(fields["width"]), "--video-height", str(fields["height"])]
    for key, flag in (("model", "--model"), ("gemma", "--gemma"), ("story_model", "--story-model")):
        if fields[key] is not None:
            argv += [flag, fields[key]]
    if fields["goal"] is not None:
        argv += ["--goal", goal_text(fields["goal"])]
    if fields["mode"] == "shots":
        argv.append("--shots")
    elif fields["mode"] == "no_stills":
        argv.append("--no-stills")
    for item in ordered(fields["video_loras"]):
        argv += ["--lora", lora_arg(item)]
    for item in ordered(fields["stills_loras"]):
        argv += ["--stills-lora", lora_arg(item)]
    for name in fields["characters"]:
        argv += ["--character", name]
    for item in fields["action_loras"]:
        argv += ["--action", action_arg(item)]
    if fields["auto_lora"] is False:
        argv.append("--no-auto-lora")
    if fields["narration"] == "none":
        argv.append("--no-narration")
    elif fields["narration"] == "speech":
        argv.append("--speech-only")
    for key, flag in (("story_legacy", "--story-legacy"), ("judge", "--judge"), ("no_low_ram", "--no-low-ram")):
        if fields[key]:
            argv.append(flag)
    if fields["panel_timeout"] is not None:
        argv += ["--panel-timeout", str(fields["panel_timeout"])]
    if fields["overwrite_movie"]:
        argv.append("--force")
    if action == "regenerate":
        argv.append("--force-story")
    if action == "redo":
        argv += ["--redo", ",".join(str(n) for n in sorted(set(fields["redo"])))]
    if action in ("story", "regenerate"):
        argv.append("--story-only")
    argv.append("--no-review")
    return argv


def _rule_actions(fields):
    """action_loras: at most 8 distinct trained-action names, each with a strength of None
    (the action's default) or 0 < s <= 2."""
    items = fields.get("action_loras")
    if not (isinstance(items, list) and len(items) <= 8):
        return ["action_loras must be a list of at most 8 actions"]
    errors, names = [], []
    for k, item in enumerate(items, start=1):
        name = item.get("name") if isinstance(item, dict) else None
        strength = item.get("strength") if isinstance(item, dict) else None
        if not (isinstance(name, str) and ACTION_NAME_RE.fullmatch(name)):
            errors.append("action %d: name must match [a-z][a-z0-9-]{1,31}" % k)
            continue
        names.append(name)
        if strength is not None and not (isinstance(strength, (int, float)) and not isinstance(strength, bool)
                                         and 0 < strength <= 2):
            errors.append("action %s: strength must satisfy 0 < s <= 2" % name)
    if len(set(names)) != len(names):
        errors.append("actions must be distinct")
    return errors


def action_argv(kind, fields, ws_real, py=sys.executable):
    """The bin/action argv of an action-create or action-train job."""
    if kind == "action-train":
        # Like character-train-vlm: stop the VLM for training's memory, always restart it.
        return [os.path.join(ws_real, "bin", "action-train-vlm"), py, fields["name"]]
    argv = [py, os.path.join(ws_real, "bin", "action"), "create", fields["name"],
            "--trigger", fields["trigger"], "--descriptor", fields["descriptor"]]
    for path in fields["clips"]:
        argv += ["--clip", path]
    argv += ["--performers", str(fields["performers"])]
    if fields.get("force"):
        argv.append("--force")
    if fields.get("regenerate"):
        argv.append("--regenerate")
    return argv


def character_argv(kind, fields, ws_real, state, py=sys.executable):
    """The bin/character argv of a character-create, -regenerate or -train job (MU41)."""
    argv = [py, os.path.join(ws_real, "bin", "character")]
    if kind == "character-regenerate":
        # Jobs have no terminal: skip the seed-image preview stop (seed-edit spec E10).
        argv += ["create", fields["name"], "--regenerate", "--no-review"]
        if fields.get("seed") is not None:
            argv += ["--seed", str(fields["seed"])]
        return argv
    if kind == "character-train":
        # Route through character-train-vlm, which stops the VLM (freeing its memory for
        # training) and always restarts it afterward -- so the UI Train button needs no
        # manual story-server stop/start. Wrapper args: <python> <name> [flags].
        wrapper = os.path.join(ws_real, "bin", "character-train-vlm")
        return ([wrapper, py, fields["name"]] + (["--video"] if fields.get("video") else [])
                + (["--stills"] if fields.get("stills") else []) + (["--force"] if fields.get("force") else []))
    argv += ["create", fields["name"], "--phrase", fields["phrase"]]
    if fields.get("seed_upload"):
        argv += ["--seed-image", os.path.join(state, "uploads", fields["seed_upload"])]
    else:
        argv += ["--descriptor", fields["descriptor"]]
    if fields.get("class_noun"):
        argv += ["--class", fields["class_noun"]]
    if fields.get("trigger"):
        argv += ["--trigger", fields["trigger"]]
    if fields.get("seed") is not None:
        argv += ["--seed", str(fields["seed"])]
    if fields.get("force"):
        argv.append("--force")
    return argv + ["--no-review"]


def run_light(argv, cwd, env=None, timeout=None):
    """One light subprocess (MU59): {"argv", "exit_code", "stdout", "stderr", "timed_out"}."""
    limit = LIGHT_TIMEOUT if timeout is None else timeout
    result = {"argv": list(argv), "exit_code": None, "stdout": "", "stderr": "", "timed_out": False}
    try:
        proc = subprocess.Popen(argv, cwd=cwd, env=env or dict(os.environ), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    except (OSError, ValueError) as e:
        result["stderr"] = "%s: %s" % (type(e).__name__, getattr(e, "strerror", None) or e)
        return result
    try:
        out, err = proc.communicate(timeout=limit)
    except subprocess.TimeoutExpired:
        _killpg_quiet(proc.pid, signal.SIGKILL)
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            out, err = b"", b""
        result["timed_out"] = True
        result["stdout"] = (out or b"").decode("utf-8", "replace")
        result["stderr"] = (err or b"").decode("utf-8", "replace")
        return result
    result["exit_code"] = proc.returncode
    result["stdout"] = out.decode("utf-8", "replace")
    result["stderr"] = err.decode("utf-8", "replace")
    return result


def tool_argv(ws_real, tool, *args):
    """[sys.executable, <ws>/bin/<tool>, args...] (MU59)."""
    return [sys.executable, os.path.join(ws_real, "bin", tool)] + list(args)


def last_line(text):
    """The last non-empty line of text, stripped, or ""."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""


_HELP_CACHE = {}
_HELP_LOCK = threading.Lock()


def parse_help_flags(text):
    """Every --flag on the option lines (starting with two spaces and "-") of argparse --help
    output (MU37)."""
    flags = set()
    for line in text.splitlines():
        if line.startswith("  -"):
            head = re.split(r"\s{2,}", line[2:], maxsplit=1)[0]
            flags.update(re.findall(r"--[a-z][a-z0-9-]*", head))
    return flags


def help_flags(ws_real):
    """(flags, error) for <ws>/bin/ltx-movie --help, cached by (ws, mtime_ns of bin/ltx-movie)
    (MU37). flags is a frozenset, or None with error "cannot read bin/ltx-movie --help (exit N):
    <last stderr line>"."""
    path = os.path.join(ws_real, "bin", "ltx-movie")
    try:
        key = (ws_real, os.stat(path).st_mtime_ns)
    except OSError as e:
        return None, "cannot read bin/ltx-movie --help (exit none): %s" % (e.strerror or e)
    with _HELP_LOCK:
        if key in _HELP_CACHE:
            return _HELP_CACHE[key]
    run = run_light(tool_argv(ws_real, "ltx-movie", "--help"), ws_real)
    if run["timed_out"]:
        return None, "cannot read bin/ltx-movie --help (timed out after %d s)" % LIGHT_TIMEOUT
    if run["exit_code"] == 0:
        value = (frozenset(parse_help_flags(run["stdout"])), None)
    else:
        code = "none" if run["exit_code"] is None else str(run["exit_code"])
        value = (None, "cannot read bin/ltx-movie --help (exit %s): %s" % (code, last_line(run["stderr"])))
    with _HELP_LOCK:
        _HELP_CACHE[key] = value
    return value


def supported_map(flags):
    """{field or action: bool} for MU47's "supported" (all False when flags is None)."""
    return dict((key, flags is not None and all(f in flags for f in needed)) for key, needed in FIELD_FLAGS)


# ---------------------------------------------------------------------------
# Check records, V1 fields and V2 host (MU42, MU43, V1, V2)
# ---------------------------------------------------------------------------

DETAIL_MAX = 20000
NARRATIVE_MAX = 20000
LORA_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
STATE_LINE_RE = re.compile(r"^\s*state:\s*(.+?)\s*$")
STILLS_PROBE = ("import torch; from diffusers import ZImagePipeline, ZImageTransformer2DModel; "
                "from transformers import Qwen3Model")
STILLS_PROBE_TIMEOUT = 60


def check(check_id, name, status, detail=""):
    """One check record (MU42); detail keeps its last DETAIL_MAX characters."""
    return {"id": check_id, "name": name, "status": status, "detail": (detail or "")[-DETAIL_MAX:]}


def checks_pass(checks):
    return not any(c["status"] == "fail" for c in checks)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def story_dir(ws_real, story_id):
    return os.path.join(ws_real, "generated", "stories", story_id)


def valid_story_id(story_id):
    """MU38: STORY_ID_RE and no "..". (movie-ui-smoke passes this; callers reserve it.)"""
    return isinstance(story_id, str) and STORY_ID_RE.fullmatch(story_id) is not None and ".." not in story_id


def resolved_panels(fields):
    """P: panels, or round(length / (frames / fps)) when length is given; None when not computable."""
    if _is_int(fields.get("panels")):
        return fields["panels"]
    length, frames, fps = fields.get("length"), fields.get("frames"), fields.get("fps")
    if _is_number(length) and _is_int(frames) and _is_int(fps) and frames > 0 and fps > 0:
        return int(round(length / (frames / float(fps))))
    return None


# Soft panel count spec SPC14, D11: story_engine.PANELS_EXTRA and bin/ltx-story-manifest's
# _PANEL_HEADER_RE (this module never loads a pipeline module, so both are repeated here and
# pinned equal by a test).
PANELS_EXTRA = 2
STORY_PANEL_RE = re.compile(r"^##\s*Panel\s*(\d+)\s*[—–-]\s*(.*)$")


def plan_panels(sdir, mode):
    """<sdir>/plan.json's "panels" when the file is a JSON object with schema ltx-movie.plan.v1,
    "mode" equal to mode, an int "panels" of at least 1, and <sdir>/story.md has exactly that
    many lines that STORY_PANEL_RE matches, line by line as bin/ltx-story-manifest's
    _parse_prompts_md counts them (fix FW-f); else None (SPC14)."""
    plan = read_json(os.path.join(sdir, "plan.json"))
    if not (isinstance(plan, dict) and plan.get("schema") == "ltx-movie.plan.v1"
            and plan.get("mode") == mode and _is_int(plan.get("panels")) and plan["panels"] >= 1):
        return None
    try:
        with open(os.path.join(sdir, "story.md"), "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    count = sum(1 for line in text.splitlines() if STORY_PANEL_RE.match(line))
    return plan["panels"] if count == plan["panels"] else None


def effective_panels(fields, sdir):
    """The story's panel count for fields (SPC14): plan_panels(sdir, fields["mode"]) when it lies
    in [resolved_panels(fields), resolved_panels(fields) + PANELS_EXTRA], else
    resolved_panels(fields). sdir None means no story directory."""
    target = resolved_panels(fields)
    planned = plan_panels(sdir, fields.get("mode")) if sdir is not None else None
    if target is not None and planned is not None and target <= planned <= target + PANELS_EXTRA:
        return planned
    return target


def _argv_safe(value):
    """A str that can be an argv element: no NUL and encodable as UTF-8 (no lone surrogates)."""
    if not isinstance(value, str) or "\x00" in value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _rule_models(fields):
    """V1 rule 9."""
    errors = []
    for key in ("model", "gemma", "story_model"):
        value = fields.get(key)
        if value is None:
            continue
        if not (isinstance(value, str) and 1 <= len(value) <= 512 and not value.startswith("-")
                and _argv_safe(value) and all(ord(ch) >= 0x20 for ch in value)):
            errors.append("%s must be a model name or an absolute path" % key)
    return errors


def _rule_loras(fields, which):
    """V1 rule 11 for one list (which is "video" or "stills")."""
    value = fields.get(which + "_loras")
    if not isinstance(value, list) or len(value) > 8:
        return ["%s LoRAs must be a list of at most 8 items" % which]
    errors, seen = [], set()
    for k, item in enumerate(value, 1):
        if not isinstance(item, dict):
            errors.append("%s LoRA %d: must be an object" % (which, k))
            continue
        path, strength, lora_id, kind = item.get("path"), item.get("strength"), item.get("id"), item.get("kind")
        if not (isinstance(path, str) and os.path.isabs(path)):
            errors.append("%s LoRA %d: path must be absolute" % (which, k))
        elif not _argv_safe(path):
            errors.append("%s LoRA %d: path contains invalid characters" % (which, k))
        else:
            real = os.path.realpath(path)
            if real in seen:
                errors.append("%s LoRA %s is listed twice" % (which, path))
            seen.add(real)
        if not (_is_number(strength) and 0 < strength <= 2):
            errors.append("%s LoRA %d: strength must be in (0, 2]" % (which, k))
        if lora_id is not None and not (isinstance(lora_id, str) and LORA_ID_RE.fullmatch(lora_id)):
            errors.append("%s LoRA %d: bad catalog id" % (which, k))
        if not (kind is None or kind in LORA_KINDS) or ((kind is None) != (lora_id is None)):
            errors.append("%s LoRA %d: bad kind" % (which, k))
    return errors


def _rule_flags(fields):
    """V1 rule 13."""
    errors = []
    for key in ("auto_lora", "story_legacy", "judge", "no_low_ram", "overwrite_movie"):
        if not isinstance(fields.get(key), bool):
            errors.append("%s must be true or false" % key)
    if fields.get("narration") not in NARRATION_MODES:
        errors.append("narration must be one of %s" % ", ".join(NARRATION_MODES))
    timeout = fields.get("panel_timeout")
    if timeout is not None and not (_is_int(timeout) and 60 <= timeout <= 86400):
        errors.append("panel_timeout must be an integer from 60 to 86400")
    return errors


def _rule_action(fields):
    """V1 rule 14."""
    return [] if fields.get("action") in ACTIONS else ["unknown action"]


def validate_fields(fields, ws_real, state):
    """V1: every failure line, in rule order; [] when the fields pass."""
    if fields.get("action") == "smoke":
        return _rule_models(fields) + _rule_loras(fields, "video") + _rule_flags(fields) + _rule_action(fields)
    errors = []
    story_id = fields.get("story_id")
    sid_ok = valid_story_id(story_id)
    if not sid_ok:                                                           # 1
        errors.append("story id must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$ and must not contain '..'")
    elif story_id.lower() == SMOKE_STORY_ID:
        sid_ok = False
        errors.append("story id movie-ui-smoke is reserved for smoke renders")
    narrative = fields.get("narrative")                                      # 2
    if not isinstance(narrative, str) or not narrative.strip():
        errors.append("narrative is required")
    elif len(narrative) > NARRATIVE_MAX:
        errors.append("narrative must be at most 20000 characters")
    elif narrative.strip().startswith("-"):
        errors.append("narrative must not start with '-'")
    elif not _argv_safe(narrative):
        errors.append("narrative contains invalid characters")
    goal = fields.get("goal")                                                # 3
    if goal is not None:
        text = goal_text(goal) if isinstance(goal, str) else ""
        if not text or "\n" in text or "\r" in text or len(text) > 300:
            errors.append("goal must be a single line of 1 to 300 characters")
        elif text.startswith("-"):
            errors.append("goal must not start with '-'")
        elif not _argv_safe(text):
            errors.append("goal contains invalid characters")
    panels, length = fields.get("panels"), fields.get("length")              # 4
    fps, frames = fields.get("fps"), fields.get("frames")
    fps_ok = _is_int(fps) and 1 <= fps <= 120
    frames_ok = _is_int(frames) and (frames - 1) % 8 == 0 and frames >= 9
    if (panels is None) == (length is None):
        errors.append("give exactly one of panels or length")
    elif panels is not None:
        if not (_is_int(panels) and 1 <= panels <= 200):
            errors.append("panels must be an integer from 1 to 200")
    elif not (_is_number(length) and 0 < length <= 3600):
        errors.append("length must be a number of seconds in (0, 3600]")
    elif fps_ok and frames_ok:
        n = int(round(length / (frames / float(fps))))
        if n < 2:
            errors.append("length resolves to %d panel(s); the minimum is 2" % n)
    if not fps_ok:                                                           # 5
        errors.append("fps must be an integer from 1 to 120")
    if not frames_ok:                                                        # 6
        errors.append("frames must satisfy (n-1)%8==0 and n>=9")
    seed, width, height = fields.get("seed_upload"), fields.get("width"), fields.get("height")   # 7
    if seed is not None and (width is not None or height is not None):
        errors.append("give a seed image or a resolution, not both")
    if not ((width is None and height is None)
            or (_is_int(width) and _is_int(height) and width % 64 == 0 and height % 64 == 0
                and width >= 64 and height >= 64)):
        errors.append("width and height must both be multiples of 64 (at least 64)")
    if seed is not None and not (isinstance(seed, str) and UPLOAD_ID_RE.fullmatch(seed)
                                 and os.path.isfile(os.path.join(state, "uploads", seed))):
        errors.append("seed image upload %s not found" % seed)
    mode = fields.get("mode")                                                # 8
    if mode not in MODES:
        errors.append("mode must be chained, shots or no_stills")
    elif seed is not None and mode == "no_stills":
        errors.append("a seed image cannot be used with no-stills mode")
    elif seed is not None and mode == "shots":
        errors.append("a seed image cannot be used with shots mode")
    errors += _rule_models(fields)                                           # 9
    errors += _rule_loras(fields, "video") + _rule_loras(fields, "stills")  # 11
    chars = fields.get("characters")                                         # 12
    if not (isinstance(chars, list) and len(chars) <= 8 and len(set(map(repr, chars))) == len(chars)
            and all(isinstance(c, str) and CHARACTER_NAME_RE.fullmatch(c) for c in chars)):
        errors.append("characters must be distinct character names")
    errors += _rule_actions(fields)                                          # 12b
    errors += _rule_flags(fields)                                            # 13
    errors += _rule_action(fields)                                           # 14
    if fields.get("story_legacy") is True and (fields.get("judge") is True or fields.get("auto_lora") is False
                                               or fields.get("narration") in ("speech", "none")
                                               or goal is not None):     # 15
        errors.append("--story-legacy cannot be combined with --judge, --no-auto-lora, "
                      "--no-narration, --speech-only or --goal")
    action = fields.get("action")
    sdir = story_dir(ws_real, story_id) if sid_ok else None
    if action == "redo":                                                     # 16
        redo = fields.get("redo")
        if mode != "shots":
            errors.append("redo needs shots mode")
        if not (isinstance(redo, list) and redo and all(_is_int(n) for n in redo)):
            errors.append("redo needs at least one panel number")
        else:
            total = effective_panels(fields, sdir)
            if total is not None:
                for n in sorted(set(redo)):
                    if not 1 <= n <= total:
                        errors.append("redo panel %d is out of range (1..%d)" % (n, total))
        if sdir is None or not os.path.isfile(os.path.join(sdir, "story.md")):
            errors.append("redo needs an existing story.md")
    if (action == "movie" and sdir is not None and fields.get("overwrite_movie") is False
            and os.path.exists(os.path.join(sdir, "movie.mp4"))):           # 17
        errors.append('movie.mp4 already exists; tick "Overwrite movie.mp4" (--force)')
    if errors:
        return errors
    flags, error = help_flags(ws_real)                                       # 18
    if flags is None:
        return [error]
    return ["this workspace's bin/ltx-movie does not support %s" % a
            for a in build_argv(fields, ws_real, state) if a.startswith("--") and a not in flags]


def ltx_bin():
    """The ltx-2-mlx binary bin/ltx-mlx-render would run (ltx2_mlx_video_skill.py:44-46, :130-139)."""
    path = os.environ.get("LTX2_MLX_BIN") or os.path.join(
        os.environ.get("LTX2_MLX_DIR") or os.path.expanduser("~/ltx-2-mlx"), ".venv", "bin", "ltx-2-mlx")
    if os.sep not in path:
        path = shutil.which(path) or path
    return path


def render_check():
    """(ok, detail) for V2 "render"."""
    path = ltx_bin()
    problems = []
    if not (os.path.isfile(path) and os.access(path, os.X_OK)):
        problems.append("ltx-2-mlx binary not found or not executable: %s (set LTX2_MLX_BIN)" % path)
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            problems.append("%s not found on PATH" % tool)
    return (False, "; ".join(problems)) if problems else (True, path)


def stills_check(ws_real, py=sys.executable):
    """(ok, detail) for V2 "stills": the imports of z_image_skill.py:46-48 in a child."""
    run = run_light([py, "-c", STILLS_PROBE], ws_real, timeout=STILLS_PROBE_TIMEOUT)
    if run["timed_out"]:
        return False, "stills dependency probe timed out after %d s" % STILLS_PROBE_TIMEOUT
    if run["exit_code"] == 0:
        return True, "stills dependencies importable"
    return False, "stills dependencies not importable: %s" % last_line(run["stderr"])


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


def judge_key_check():
    """(ok, detail) for V2 "judge key"."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True, "ANTHROPIC_API_KEY is set"
    return False, "--judge needs ANTHROPIC_API_KEY in movie-ui's environment"


def _from_pair(check_id, name, pair):
    return check(check_id, name, "pass" if pair[0] else "fail", pair[1])


def not_needed(check_id, name):
    return check(check_id, name, "skip", "not needed for this action")


def render_needed(fields):
    return fields["action"] in ("movie", "redo", "smoke")


def stills_needed(fields):
    return fields["action"] in ("movie", "redo") and fields["mode"] != "no_stills"


def story_needed(fields, ws_real):
    if fields["action"] in ("story", "regenerate"):
        return True
    return fields["action"] == "movie" and not os.path.isfile(
        os.path.join(story_dir(ws_real, fields["story_id"]), "story.md"))


def host_checks(fields, ws_real, py=sys.executable):
    """V2's four records."""
    out = [_from_pair("V2", "render", render_check()) if render_needed(fields) else not_needed("V2", "render"),
           _from_pair("V2", "stills", stills_check(ws_real, py)) if stills_needed(fields)
           else not_needed("V2", "stills"),
           story_server_record(ws_real) if story_needed(fields, ws_real)
           else not_needed("V2", "story server"),
           _from_pair("V2", "judge key", judge_key_check()) if fields["judge"] is True
           else not_needed("V2", "judge key")]
    return out


# ---------------------------------------------------------------------------
# V3: models present and intact, and the model list of MU63
# ---------------------------------------------------------------------------

def ltx_hub():
    """<LTX2_MLX_HF_HOME or <LTX2_MLX_DIR or ~/ltx-2-mlx>/hf_cache>/hub (ltx2_mlx_video_skill.py:47-48)."""
    home = os.environ.get("LTX2_MLX_HF_HOME") or os.path.join(
        os.environ.get("LTX2_MLX_DIR") or os.path.expanduser("~/ltx-2-mlx"), "hf_cache")
    return os.path.join(home, "hub")


def zimage_hub():
    """<Z_IMAGE_HF_HOME or ~/hf_home>/hub (z_image_skill.py:56-59)."""
    return os.path.join(os.environ.get("Z_IMAGE_HF_HOME") or os.path.expanduser("~/hf_home"), "hub")


def hf_hub():
    """<HF_HOME or ~/.cache/huggingface>/hub, the default HF cache."""
    return os.path.join(os.environ.get("HF_HOME") or os.path.expanduser("~/.cache/huggingface"), "hub")


def repo_dir_name(repo_id):
    return "models--" + repo_id.replace("/", "--")


def zimage_hub_for(repo_id):
    """The scoped Z-Image hub when it holds the repo, else the default HF hub (z_image_skill.py:62-69)."""
    scoped = zimage_hub()
    return scoped if os.path.isdir(os.path.join(scoped, repo_dir_name(repo_id))) else hf_hub()


def choose_snapshot(repo_dir):
    """(snapshot path, None) by refs/main, else the only snapshot; (None, reason) otherwise."""
    try:
        with open(os.path.join(repo_dir, "refs", "main"), "r", encoding="utf-8") as f:
            rev = f.read().strip()
        return os.path.join(repo_dir, "snapshots", rev), None
    except (OSError, ValueError):
        pass
    try:
        snaps = sorted(n for n in os.listdir(os.path.join(repo_dir, "snapshots"))
                       if os.path.isdir(os.path.join(repo_dir, "snapshots", n)))
    except OSError:
        snaps = []
    if len(snaps) == 1:
        return os.path.join(repo_dir, "snapshots", snaps[0]), None
    return None, "no refs/main"


def _nonempty_file(path):
    real = os.path.realpath(path)
    return os.path.isfile(real) and os.path.getsize(real) > 0


MAX_MODEL_WALK_ENTRIES = 20000


def intact_scan(snapshot, repo_dir=None):
    """(problems, notes): V3's intact rules (b)-(e) on one snapshot (or an absolute model directory
    when repo_dir is None; that walk is capped at MAX_MODEL_WALK_ENTRIES). The config.json clause of
    the brief is not applied (D3, Q3). An index listing none of the present shards is stale: ignored
    with a note, as mlx_lm loads by glob."""
    problems, notes = [], []
    visited = 0
    if repo_dir is not None:
        try:
            names = os.listdir(os.path.join(repo_dir, "blobs"))
        except OSError:
            names = []
        present = set(names)
        # An `.incomplete` is named "<sha256>.<etag>.incomplete"; it counts as a real
        # partial download only when the finished blob "<sha256>" is absent. HF/Xet can
        # leave a stale `.incomplete` sidecar beside a blob that later completed (the
        # finished blob being a symlink into the Xet store) -- that is not a problem.
        partial = [n for n in names
                   if n.endswith(".incomplete") and n.split(".", 1)[0] not in present]
        if partial:
            problems.append("download incomplete: %d partial blob(s)" % len(partial))
    safetensors, indexes = 0, []
    for dirpath, dirnames, filenames in os.walk(snapshot, followlinks=False):
        dirnames.sort()
        visited += len(dirnames) + len(filenames)
        if repo_dir is None and visited > MAX_MODEL_WALK_ENTRIES:
            return ["too many files under %s (more than %d)" % (snapshot, MAX_MODEL_WALK_ENTRIES)], notes
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, snapshot)
            real = os.path.realpath(full)
            if not os.path.isfile(real):
                problems.append("broken file: %s" % rel)
                continue
            if name.endswith(".safetensors"):
                safetensors += 1
                if os.path.getsize(real) == 0:
                    problems.append("empty file: %s" % rel)
            if name.endswith(".safetensors.index.json"):
                indexes.append(full)
    if safetensors == 0:
        problems.append("no .safetensors file")
    for index in indexes:
        rel = os.path.relpath(index, snapshot)
        data = read_json(index)
        if not (isinstance(data, dict) and isinstance(data.get("weight_map"), dict)):
            problems.append("unreadable index: %s" % rel)
            continue
        shards = sorted(set(v for v in data["weight_map"].values() if isinstance(v, str)))
        if safetensors and not any(os.path.lexists(os.path.join(os.path.dirname(index), v)) for v in shards):
            notes.append("index lists none of the present shards; ignored")
            continue
        for shard in shards:
            path = os.path.join(os.path.dirname(index), shard)
            if not _nonempty_file(path):
                problems.append("missing shard: %s" % os.path.relpath(path, snapshot))
    return problems, notes


def intact_problems(snapshot, repo_dir=None):
    return intact_scan(snapshot, repo_dir)[0]


def model_check(model_id, hub):
    """(ok, detail) for one V3 record: an absolute path is checked in place, an HF ID in hub."""
    if os.path.isabs(model_id):
        if not os.path.isdir(model_id):
            return False, "%s is not a directory" % model_id
        problems, notes = intact_scan(model_id)
        return (False, "; ".join(problems)) if problems else (True, "; ".join([model_id] + notes))
    repo_dir = os.path.join(hub, repo_dir_name(model_id))
    if not os.path.isdir(repo_dir):
        return False, "%s is not in %s" % (model_id, hub)
    snapshot, reason = choose_snapshot(repo_dir)
    if snapshot is None:
        return False, "cannot choose a snapshot of %s (%s)" % (model_id, reason)
    problems, notes = intact_scan(snapshot, repo_dir)
    return (False, "; ".join(problems)) if problems else (True, "; ".join([snapshot] + notes))


def model_checks(fields, ws_real):
    """V3's four records."""
    m = fields["model"] or DEFAULT_MODEL
    g = fields["gemma"] or DEFAULT_GEMMA
    out = []
    if render_needed(fields):
        out.append(_from_pair("V3", "video model %s" % m, model_check(m, ltx_hub())))
        out.append(_from_pair("V3", "gemma %s" % g, model_check(g, ltx_hub())))
    else:
        out += [not_needed("V3", "video model %s" % m), not_needed("V3", "gemma %s" % g)]
    for name, repo in (("Z-Image %s" % STILLS_BASE_MODEL, STILLS_BASE_MODEL),
                       ("Z-Image text encoder %s" % ZIMAGE_TEXT_ENCODER, ZIMAGE_TEXT_ENCODER)):
        if stills_needed(fields):
            out.append(_from_pair("V3", name, model_check(repo, zimage_hub_for(repo))))
        else:
            out.append(not_needed("V3", name))
    return out


def _tree_bytes(path):
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path, followlinks=False):
        for name in filenames:
            try:
                info = os.lstat(os.path.join(dirpath, name))
            except OSError:
                continue
            if info.st_mode & 0o170000 == 0o100000:
                total += info.st_size
    return total


def list_models():
    """MU63: {"hubs": {"ltx", "zimage", "hf"}, "models": [...]} sorted by (hub, repo)."""
    hubs = {"ltx": ltx_hub(), "zimage": zimage_hub(), "hf": hf_hub()}
    models = []
    for hub_name, hub in hubs.items():
        try:
            names = os.listdir(hub)
        except OSError:
            continue
        for name in names:
            repo_dir = os.path.join(hub, name)
            if not (name.startswith("models--") and os.path.isdir(repo_dir)):
                continue
            org, _sep, rest = name[len("models--"):].partition("--")
            snapshot, reason = choose_snapshot(repo_dir)
            problems = (["cannot choose a snapshot (%s)" % reason] if snapshot is None
                        else intact_problems(snapshot, repo_dir))
            models.append({"repo": "%s/%s" % (org, rest), "hub": hub_name, "repo_dir": repo_dir,
                           "intact": not problems, "problems": problems,
                           "bytes": _tree_bytes(os.path.join(repo_dir, "blobs"))})
    models.sort(key=lambda m: (m["hub"], m["repo"]))
    # The valid LoRA base models per target, for the UI's base-model dropdown: video
    # LoRAs attach to an ltx-hub DiT pack (not the gemma text encoder), stills LoRAs to
    # the Z-Image base (not its Qwen text encoder). The canonical default leads the list.
    present = {m["repo"] for m in models}
    ltx_repos = [m["repo"] for m in models if m["hub"] == "ltx" and m["repo"] != DEFAULT_GEMMA]
    video_bases = ([DEFAULT_MODEL] if DEFAULT_MODEL in present else [])
    video_bases += [r for r in ltx_repos if r != DEFAULT_MODEL]
    stills_bases = [STILLS_BASE_MODEL] if STILLS_BASE_MODEL in present else []
    if not video_bases:
        video_bases = [DEFAULT_MODEL]
    if not stills_bases:
        stills_bases = [STILLS_BASE_MODEL]
    return {"hubs": hubs, "models": models,
            "lora_bases": {"video": video_bases, "stills": stills_bases}}


# ---------------------------------------------------------------------------
# V4 LoRAs intact, V5 compatible, V6 dry run, and run_checks (MU43, V4-V6)
# ---------------------------------------------------------------------------

SAFETENSORS_HEADER_MAX = 104857600
DRY_RUN_TIMEOUT = 60
VERIFY_TIMEOUT = 300


class _ToolError(Exception):
    """A light bin/ call that failed; str() is the check detail."""


def catalog_list(ws_real, model, cache):
    """The parsed `lora-catalog list --model M --json` object (cached in cache by model)."""
    if model not in cache:
        run = run_light(tool_argv(ws_real, "lora-catalog", "list", "--model", model, "--json"), ws_real)
        try:
            if run["exit_code"] != 0:
                raise ValueError
            value = json.loads(run["stdout"])
            if not (isinstance(value, dict) and isinstance(value.get("entries"), list)):
                raise ValueError
            cache[model] = value
        except ValueError:
            cache[model] = _ToolError("bin/lora-catalog list --model %s --json %s: %s" % (
                model, "timed out" if run["timed_out"] else "exited %s" % run["exit_code"],
                last_line(run["stderr"]) or "unparsable output"))
    if isinstance(cache[model], _ToolError):
        raise cache[model]
    return cache[model]


def safetensors_problem(path):
    """None when path is a readable safetensors file with a JSON-object header, else the V4 detail."""
    try:
        if not os.path.isfile(path):
            raise OSError
        with open(path, "rb") as f:
            head = f.read(8)
            if len(head) != 8:
                return "%s: not a safetensors file" % path
            (n,) = struct.unpack("<Q", head)
            if not 0 < n <= SAFETENSORS_HEADER_MAX:
                return "%s: not a safetensors file" % path
            raw = f.read(n)
    except OSError:
        return "%s is not a readable file" % path
    try:
        header = json.loads(raw.decode("utf-8")) if len(raw) == n else None
    except (ValueError, RecursionError):
        header = None
    return None if isinstance(header, dict) else "%s: not a safetensors file" % path


def lora_checks(fields, ws_real, cache, smoke=False):
    """V4's records: catalog verify, then one LoRA file record per free path."""
    lists = [fields["video_loras"]] + ([] if smoke else [fields["stills_loras"]])
    chosen = set(item["id"] for items in lists for item in items if item.get("id") is not None)
    ids = set(chosen)
    out = []
    try:
        if fields["auto_lora"] is True and fields["story_legacy"] is False and not smoke:
            m = fields["model"] or DEFAULT_MODEL
            ids.update(e["id"] for e in catalog_list(ws_real, m, cache)["entries"] if e.get("target") == "video")
            if fields["mode"] != "no_stills":
                ids.update(e["id"] for e in catalog_list(ws_real, STILLS_BASE_MODEL, cache)["entries"]
                           if e.get("target") == "stills")
    except _ToolError as e:
        out.append(check("V4", "catalog verify", "fail", str(e)))
    else:
        if not ids:
            out.append(check("V4", "catalog verify", "skip", "no catalog LoRA chosen or pickable"))
        else:
            run = run_light(tool_argv(ws_real, "lora-catalog", "verify", *sorted(ids)), ws_real,
                            timeout=VERIFY_TIMEOUT)
            if run["timed_out"]:
                out.append(check("V4", "catalog verify", "fail",
                                 "bin/lora-catalog verify timed out after %d s" % VERIFY_TIMEOUT))
            elif run["exit_code"] == 0:
                out.append(check("V4", "catalog verify", "pass", run["stdout"] + run["stderr"]))
            else:
                chosen_fails, auto_fails = [], []
                for line in run["stdout"].splitlines():
                    found = re.match(r"FAIL (\S+?)(:|$)", line)
                    if found:
                        (chosen_fails if found.group(1) in chosen else auto_fails).append(line)
                if not chosen_fails and not auto_fails:
                    out.append(check("V4", "catalog verify", "fail", run["stdout"] + run["stderr"]))
                elif chosen_fails:
                    out.append(check("V4", "catalog verify", "fail", "\n".join(chosen_fails)))
                else:
                    out.append(check("V4", "catalog verify", "pass", run["stdout"] + run["stderr"]))
                if auto_fails:
                    out.append(check("V4", "LoRAs auto set", "skip",
                                     "the planner will skip these entries:\n" + "\n".join(auto_fails)))
    for items in lists:
        for item in items:
            if item.get("id") is None:
                problem = safetensors_problem(item["path"])
                out.append(check("V4", "LoRA file %s" % item["path"], "fail" if problem else "pass",
                                 problem or "%s: safetensors header ok" % item["path"]))
    return out


def _compat_problems(items, which, entries, target, model):
    problems = []
    for item in items:
        if item.get("id") is None:
            continue
        entry = entries.get(item["id"])
        if entry is None or entry.get("target") != target:
            problems.append("%s is not a %s LoRA compatible with %s" % (item["id"], target, model))
            continue
        if item["path"] != entry.get("path") or item.get("kind") != entry.get("kind"):
            problems.append("%s: path or kind differs from the catalog; reload the LoRA list" % item["id"])
        rng = entry.get("strength_range")
        if isinstance(rng, list) and len(rng) == 2 and not rng[0] <= item["strength"] <= rng[1]:
            problems.append("%s: strength %s is outside %s-%s" % (item["id"], item["strength"], rng[0], rng[1]))
    if sum(1 for item in items if item.get("id") is not None and item.get("kind") == "style") > 1:
        problems.append("at most one style LoRA among the %s LoRAs" % which)
    return problems


def _same_model(a, b):
    return a == b or (isinstance(a, str) and isinstance(b, str) and os.path.isabs(a) and os.path.isabs(b)
                      and os.path.realpath(a) == os.path.realpath(b))


def compat_checks(fields, ws_real, cache, smoke=False):
    """V5's records: catalog compatibility, then per cast character its record and, when it has a
    video LoRA, its video base model record (a mismatch is skip, never fail: D2, Q2)."""
    m = fields["model"] or DEFAULT_MODEL
    video = [i for i in fields["video_loras"] if i.get("id") is not None]
    stills = [] if smoke else [i for i in fields["stills_loras"] if i.get("id") is not None]
    out = []
    if not video and not stills:
        out.append(check("V5", "catalog compatibility", "skip", "no catalog LoRA chosen"))
    else:
        try:
            problems = []
            if video:
                entries = dict((e["id"], e) for e in catalog_list(ws_real, m, cache)["entries"])
                problems += _compat_problems(video, "video", entries, "video", m)
            if stills:
                entries = dict((e["id"], e) for e in catalog_list(ws_real, STILLS_BASE_MODEL, cache)["entries"])
                problems += _compat_problems(stills, "stills", entries, "stills", STILLS_BASE_MODEL)
        except _ToolError as e:
            problems = [str(e)]
        out.append(check("V5", "catalog compatibility", "fail" if problems else "pass",
                         "; ".join(problems) or "every catalog LoRA is compatible"))
    if smoke:
        return out + [not_needed("V5", "characters")]
    if not fields["characters"]:
        out.append(check("V5", "characters", "skip", "no character cast"))
    for name in fields["characters"]:
        run = run_light(tool_argv(ws_real, "character", "show", name), ws_real)
        if run["timed_out"]:
            out.append(check("V5", "character %s" % name, "fail",
                             "bin/character show %s timed out after %d s" % (name, LIGHT_TIMEOUT)))
            continue
        if run["exit_code"] != 0:
            out.append(check("V5", "character %s" % name, "fail", run["stderr"].strip() or run["stdout"].strip()))
            continue
        try:
            data, _end = json.JSONDecoder().raw_decode(run["stdout"].lstrip())
        except ValueError:
            data = None
        if not isinstance(data, dict):
            out.append(check("V5", "character %s" % name, "fail", "cannot parse bin/character show %s" % name))
            continue
        loras = data.get("loras") if isinstance(data.get("loras"), dict) else {}
        stills_lora = loras.get("stills") if isinstance(loras.get("stills"), dict) else None
        if data.get("status") != "trained":
            out.append(check("V5", "character %s" % name, "fail",
                             "character %s is not trained (status %s)" % (name, data.get("status"))))
        elif stills_lora is not None and stills_lora.get("base_model") != STILLS_BASE_MODEL:
            out.append(check("V5", "character %s" % name, "fail",
                             "character %s's stills LoRA is for %s, not %s"
                             % (name, stills_lora.get("base_model"), STILLS_BASE_MODEL)))
        else:
            out.append(check("V5", "character %s" % name, "pass", "trained"))
        video_lora = loras.get("video") if isinstance(loras.get("video"), dict) else None
        if video_lora is not None:
            base = video_lora.get("base_model")
            if _same_model(base, m):
                out.append(check("V5", "character %s video base model" % name, "pass", "trained on %s" % base))
            else:
                out.append(check("V5", "character %s video base model" % name, "skip",
                                 "video LoRA trained on %s; bin/ltx-movie does not check this against --model %s"
                                 % (base, m)))
    return out + action_checks(fields, ws_real)


def action_checks(fields, ws_real):
    """V5's per-action records (none when no action is chosen): each action is trained."""
    out = []
    for item in fields["action_loras"]:
        name = item["name"]
        run = run_light(tool_argv(ws_real, "action", "show", name), ws_real)
        try:
            data = json.loads(run["stdout"]) if run["exit_code"] == 0 else None
        except ValueError:
            data = None
        if run["timed_out"]:
            out.append(check("V5", "action %s" % name, "fail",
                             "bin/action show %s timed out after %d s" % (name, LIGHT_TIMEOUT)))
        elif not isinstance(data, dict):
            out.append(check("V5", "action %s" % name, "fail",
                             run["stderr"].strip() or "cannot parse bin/action show %s" % name))
        elif data.get("status") != "trained":
            out.append(check("V5", "action %s" % name, "fail",
                             "action %s is not trained (status %s)" % (name, data.get("status"))))
        else:
            out.append(check("V5", "action %s" % name, "pass", "trained"))
    return out


def dry_run_check(fields, ws_real, state):
    """V6: build_argv(fields) + ["--dry-run"] with STORY_PIPELINE_LOGGED=1 (D17)."""
    argv = build_argv(fields, ws_real, state) + ["--dry-run"]
    run = run_light(argv, ws_real, env=dict(os.environ, STORY_PIPELINE_LOGGED="1"), timeout=DRY_RUN_TIMEOUT)
    if run["timed_out"]:
        return check("V6", "dry run", "fail", "bin/ltx-movie --dry-run timed out after %d s" % DRY_RUN_TIMEOUT)
    return check("V6", "dry run", "pass" if run["exit_code"] == 0 else "fail", run["stdout"] + run["stderr"])


V_GROUP_NAMES = (("V2", "host can run it"), ("V3", "models present and intact"), ("V4", "LoRAs intact"),
                 ("V5", "compatible"), ("V6", "dry run"))


def run_checks(fields, ws_real, state, py=sys.executable):
    """MU43: V1; on a V1 failure one skip per V2-V6; otherwise V2-V6 in order, no short circuit."""
    errors = validate_fields(fields, ws_real, state)
    v1 = check("V1", "fields", "fail" if errors else "pass", "\n".join(errors))
    if errors:
        return [v1] + [check(i, n, "skip", "skipped: V1 failed") for i, n in V_GROUP_NAMES]
    if fields["action"] == "smoke":
        return [v1] + smoke_checks(fields, ws_real)
    cache = {}
    return ([v1] + host_checks(fields, ws_real, py) + model_checks(fields, ws_real)
            + lora_checks(fields, ws_real, cache) + compat_checks(fields, ws_real, cache)
            + [dry_run_check(fields, ws_real, state)])


# ---------------------------------------------------------------------------
# The progress parser (MU55, MU56)
# ---------------------------------------------------------------------------

LINE_CLIP = 300
FEED_MAX = 1048576
PHASE_RE = re.compile(r"^=== Phase (\d+b?): (.+?)(?: \(rewrite (\d+) of (\d+)\))? ===$")
REDO_RE = re.compile(r"^=== Redo: panels (.+) ===$")
TOTAL_RE = re.compile(r"^panels: (\d+)$")
PANEL_HDR_RE = re.compile(r"^=== panel (\d+)/(\d+) \(")
OK_RE = re.compile(r"^panel (\d+) ok: ")
REUSE_RE = re.compile(r"^panel (\d+): reusing ")
FAILED_RE = re.compile(r"^panel (\d+) FAILED \(([^)]*)\):? ?(.*)$")
SUMMARY_RE = re.compile(r"^=== render summary \(")
RETRY_RE = re.compile(r"^=== inline retry: panel (\d+) \(")
MOVIE_RE = re.compile(r"^MOVIE \d+/\d+ panels")
FACE_RE = re.compile(
    r"^Error: (?:the vision model found no face in the seed image; pass --force to proceed anyway\."
    r"|the main character's face fills only \d+% of the seed image's height \(minimum 15%\); a small "
    r"face makes a weak identity reference\. Use a closer crop of the character, or pass --force to "
    r"proceed anyway\.)$")
STILL_NAME_RE = re.compile(r"^panel_\d{2}\.png$")


def collapse(line):
    """The text after the last carriage return of a line (pipeline_log.collapse_cr's rule)."""
    return line.rstrip("\r").rsplit("\r", 1)[-1]


DOWNLOAD_HUBS = ("ltx", "zimage", "hf")


def build_download_argv(repo, hub, ws_real, py=sys.executable):
    """The bin/model-download argv that fetches `repo` into the named cache `hub`
    ("ltx"|"zimage"|"hf"). Pure; the caller validates repo/hub."""
    return [py, os.path.join(ws_real, "bin", "model-download"), "--hub", hub, repo]


def job_phases(kind, fields):
    """MU56's "phases", mirroring bin/ltx-movie's _phase_sequence."""
    if kind == "download":
        return []
    seed = ["0"] if fields.get("seed_upload") else []
    if kind == "story":
        return seed + ["1"]
    return (seed + ["1", "1b"] + (["redo"] if fields.get("action") == "redo" else [])
            + ([] if fields.get("mode") == "no_stills" else ["2"]) + ["3", "4"])


class ProgressParser(object):
    """Incremental log.txt parser for one job (MU55). feed() takes raw bytes; a line split across
    feeds is parsed once, whole."""

    def __init__(self, kind, fields):
        self.kind, self.fields = kind, fields
        self.offset = 0
        self.tail = b""
        self.phase = self.phase_title = self.rewrite = self.redo = self.panels_total = None
        self.panels = {}
        self.wrap_up = False
        self.face_problem = False
        self.last_line = ""

    def feed(self, data):
        self.offset += len(data)
        lines = (self.tail + data).split(b"\n")
        self.tail = lines.pop()
        for raw in lines:
            self._line(collapse(raw.decode("utf-8", "replace")))
        if len(self.tail) > 65536:
            i = self.tail.rstrip(b"\r").rfind(b"\r")
            if i >= 0:
                self.tail = self.tail[i:]

    def current_last_line(self):
        raw = self.tail
        for back in range(1, min(3, len(raw)) + 1):
            byte = raw[-back]
            if byte >= 0xC0:
                need = 4 if byte >= 0xF0 else 3 if byte >= 0xE0 else 2
                if need > back:
                    raw = raw[:-back]
                break
            if byte < 0x80:
                break
        tail = collapse(raw.decode("utf-8", "replace"))
        return tail[:LINE_CLIP] if tail.strip() else self.last_line

    def _line(self, line):
        if line.strip():
            self.last_line = line[:LINE_CLIP]
        match = PHASE_RE.match(line)
        if match:
            self.phase, self.phase_title = match.group(1), match.group(2)
            self.rewrite = [int(match.group(3)), int(match.group(4))] if match.group(3) else None
            return
        match = REDO_RE.match(line)
        if match:
            self.phase, self.redo = "redo", match.group(1)
            return
        match = TOTAL_RE.match(line)
        if match:
            self.panels_total = int(match.group(1))
            return
        match = PANEL_HDR_RE.match(line)
        if match:
            self.panels_total = int(match.group(2))
            self.panels[match.group(1)] = {"state": "running"}
            return
        match = RETRY_RE.match(line)
        if match:
            self.panels[match.group(1)] = {"state": "running"}
            return
        match = OK_RE.match(line)
        if match:
            self.panels[match.group(1)] = {"state": "ok", "reused": False}
            return
        match = REUSE_RE.match(line)
        if match:
            self.panels[match.group(1)] = {"state": "ok", "reused": True}
            return
        match = FAILED_RE.match(line)
        if match:
            self.panels[match.group(1)] = {"state": "failed", "reason": match.group(2),
                                           "detail": match.group(3)[:LINE_CLIP]}
            return
        if SUMMARY_RE.match(line) or MOVIE_RE.match(line):
            self.wrap_up = True
            return
        if FACE_RE.match(line):
            self.face_problem = True

    def snapshot(self, job, status, state, now=None):
        """The MU56 progress object for job (its job.json) and status (its status.json or None)."""
        started = parse_utc((status or {}).get("started"))
        current = time.time() if now is None else now
        elapsed = None if started is None else int(current - started)
        if self.kind == "smoke":
            clip = os.path.join(state, "smoke", job["id"], "clips", "panel_01.mp4")
            return {"kind": "smoke", "elapsed_s": elapsed, "last_line": self.current_last_line(),
                    "smoke": {"clip": clip, "clip_ok": os.path.isfile(clip) and os.path.getsize(clip) > 0}}
        if self.kind not in ("story", "movie"):
            return {"kind": self.kind, "elapsed_s": elapsed, "last_line": self.current_last_line(),
                    "face_problem": self.face_problem}
        stills = None
        if self.phase == "2":
            images = os.path.join(story_dir(job["workspace"], job["story_id"]), "images")
            try:
                count = sum(1 for n in os.listdir(images) if STILL_NAME_RE.fullmatch(n))
            except OSError:
                count = 0
            expected = (effective_panels(self.fields, story_dir(job["workspace"], job["story_id"]))
                        if self.fields.get("mode") == "shots" else 1)
            stills = {"expected": expected, "count": count}
        return {"phase": self.phase, "phase_title": self.phase_title, "rewrite": self.rewrite,
                "phases": job_phases(self.kind, self.fields), "redo": self.redo,
                "panels_total": self.panels_total,
                "panels": dict((k, dict(v)) for k, v in sorted(self.panels.items(), key=lambda kv: int(kv[0]))),
                "panels_done": sum(1 for v in self.panels.values() if v["state"] == "ok"),
                "wrap_up": self.wrap_up, "stills": stills, "last_line": self.current_last_line()}


# ---------------------------------------------------------------------------
# V7 smoke render (MU52, Q4)
# ---------------------------------------------------------------------------

SMOKE_PANEL_TEXT = ("A slow camera pan across a quiet forest clearing at golden hour, leaves moving "
                    "gently in the wind.")


def smoke_dir(state, job_id):
    return os.path.join(state, "smoke", job_id)


def write_smoke_manifest(state, job_id):
    """Create STATE/smoke/<id>/ (0700) and its manifest.json (MU52); returns the manifest path."""
    sdir = smoke_dir(state, job_id)
    make_dir(sdir)
    path = os.path.join(sdir, "manifest.json")
    write_json_atomic(path, {"schema_version": 3, "story_id": SMOKE_STORY_ID,
                             "panels": [{"index": 1, "conditioning": "t2v", "image_path": None,
                                         "panel_text": SMOKE_PANEL_TEXT}]})
    return path


def build_smoke_argv(fields, ws_real, state, job_id, py=sys.executable):
    """The bin/ltx-mlx-render argv of a smoke job (MU52): 512x320, 9 frames."""
    sdir = smoke_dir(state, job_id)
    argv = [py, os.path.join(ws_real, "bin", "ltx-mlx-render"), os.path.join(sdir, "manifest.json"),
            os.path.join(sdir, "smoke.mp4"), "--frames", "9", "--width", "512", "--height", "320",
            "--frame-rate", "24", "--clips-dir", os.path.join(sdir, "clips"),
            "--model", fields["model"] or DEFAULT_MODEL, "--gemma", fields["gemma"] or DEFAULT_GEMMA]
    for item in ordered(fields["video_loras"]):
        argv += ["--lora", lora_arg(item)]
    if fields["no_low_ram"]:
        argv.append("--no-low-ram")
    return argv + ["--panel-timeout", "1800"]


def smoke_checks(fields, ws_real):
    """MU52: V2 render, V3 video model and gemma, V4 and V5 on video items only; every other record
    is skip."""
    cache = {}
    host = [_from_pair("V2", "render", render_check()), not_needed("V2", "stills"),
            not_needed("V2", "story server"), not_needed("V2", "judge key")]
    return (host + model_checks(fields, ws_real) + lora_checks(fields, ws_real, cache, smoke=True)
            + compat_checks(fields, ws_real, cache, smoke=True) + [not_needed("V6", "dry run")])
