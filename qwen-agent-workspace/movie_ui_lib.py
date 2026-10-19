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
           "fields": fields, "created": utc_now()}
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


def cancel_groups(child_pid):
    """The process groups a cancel signals: the child's own group (MU23 step 1; the sweep of
    its descendants' groups, D1, is added separately, Q1)."""
    return [child_pid]


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
        child = subprocess.Popen(job["argv"], cwd=job["workspace"], env=dict(os.environ, PYTHONUNBUFFERED="1"),
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                 start_new_session=True, close_fds=True)
    except OSError as e:
        error = "cannot start: %s" % (e.strerror or e)
        write_status(jdir, {"state": "failed", "dispatched": status.get("dispatched"),
                            "runner_pid": os.getpid(), "pgid": None, "started": None,
                            "exit_code": None, "ended": utc_now(), "error": error})
        _say(error)
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
    return 0
