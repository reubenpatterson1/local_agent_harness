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
    have a status; then re-attach or mark lost every starting/running job (MU31)."""
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
    shutil.rmtree(job_dir(state, job_id))
    return True


def orphan_info(status):
    """{"pgid": G, "alive": True} for a lost job whose recorded group still exists, else None
    (MU26)."""
    if not isinstance(status, dict) or status.get("state") != "lost":
        return None
    pgid = status.get("pgid")
    if not isinstance(pgid, int) or isinstance(pgid, bool) or pgid <= 1:
        return None
    return {"pgid": pgid, "alive": True} if group_alive(pgid) else None


def kill_orphan(state, job_id):
    """SIGKILL a lost job's live orphan group; returns the pgid, or None when there is none (MU68)."""
    info = orphan_info(read_status(job_dir(state, job_id)))
    if info is None:
        return None
    _killpg_quiet(info["pgid"], signal.SIGKILL)
    return info["pgid"]


# ---------------------------------------------------------------------------
# Compose fields, the command builder and light subprocesses (MU36-MU41, MU59)
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8"     # bin/ltx-movie:318
DEFAULT_GEMMA = "mlx-community/gemma-3-12b-it-4bit"          # bin/ltx-movie:319-323
STILLS_BASE_MODEL = "Tongyi-MAI/Z-Image-Turbo"               # lora_catalog.py:29
ZIMAGE_TEXT_ENCODER = "BennyDaBall/Qwen3-4b-Z-Image-Turbo-AbliteratedV1"   # z_image_skill.py:53
ACTIONS = ("story", "regenerate", "movie", "redo")
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
    "auto_lora": True,
    "video_loras": [], "stills_loras": [],
    "characters": [],
    "story_legacy": False, "judge": False, "no_low_ram": False, "panel_timeout": None,
    "overwrite_movie": False, "redo": [],
}
LIGHT_TIMEOUT = 60
# MU37: the flags each compose field or action needs; "supported" (MU47) is all-present.
FIELD_FLAGS = (
    ("story_id", ("--story-id",)), ("panels", ("--panels",)), ("length", ("--length",)),
    ("fps", ("--fps",)), ("frames", ("--frames",)),
    ("resolution", ("--video-width", "--video-height")), ("seed_upload", ("--seed-image",)),
    ("model", ("--model",)), ("gemma", ("--gemma",)), ("story_model", ("--story-model",)),
    ("goal", ("--goal",)), ("shots", ("--shots",)), ("no_stills", ("--no-stills",)),
    ("video_loras", ("--lora",)), ("stills_loras", ("--stills-lora",)),
    ("characters", ("--character",)), ("auto_lora", ("--no-auto-lora",)),
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
    if fields["auto_lora"] is False:
        argv.append("--no-auto-lora")
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


def character_argv(kind, fields, ws_real, state, py=sys.executable):
    """The bin/character argv of a character-create, -regenerate or -train job (MU41)."""
    argv = [py, os.path.join(ws_real, "bin", "character")]
    if kind == "character-regenerate":
        return argv + ["create", fields["name"], "--regenerate"]
    if kind == "character-train":
        return (argv + ["train", fields["name"]] + (["--video"] if fields.get("video") else [])
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
    return argv


def run_light(argv, cwd, env=None, timeout=None):
    """One light subprocess (MU59): {"argv", "exit_code", "stdout", "stderr", "timed_out"}."""
    limit = LIGHT_TIMEOUT if timeout is None else timeout
    result = {"argv": list(argv), "exit_code": None, "stdout": "", "stderr": "", "timed_out": False}
    try:
        proc = subprocess.run(argv, cwd=cwd, env=env or dict(os.environ), stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=limit)
    except subprocess.TimeoutExpired as e:
        result["timed_out"] = True
        result["stdout"] = (e.stdout or b"").decode("utf-8", "replace")
        result["stderr"] = (e.stderr or b"").decode("utf-8", "replace")
        return result
    except OSError as e:
        result["stderr"] = "%s: %s" % (type(e).__name__, e.strerror or e)
        return result
    result["exit_code"] = proc.returncode
    result["stdout"] = proc.stdout.decode("utf-8", "replace")
    result["stderr"] = proc.stderr.decode("utf-8", "replace")
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
