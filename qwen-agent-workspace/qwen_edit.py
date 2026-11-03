"""qwen_edit -- the shared Qwen edit runner (docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md,
Section 2): the selection checks (is a registry model and its LoRAs installed, does the host reach the
model's memory floor) and one child run over a list of edit jobs, every output screened with content
safety. bin/seed-edit, location_dataset.py and character_dataset.py import it; bin/ltx-movie loads it by
path, and only when --seed-edit-model names a registry model.

The mflux registry models run seed_edit_mflux_child.py under the mflux venv's Python, offline and with no
Hugging Face token in its environment, and this process screens every output before it gets its final
name; qwen2511-bf16 runs the unchanged character_dataset.py qwenedit child, which screens each output
itself. The child timeout is max(CHILD_TIMEOUT_S, JOB_TIMEOUT_S x jobs) seconds.

Environment: SEED_EDIT_MFLUX_PYTHON (default ~/mflux-edit/.venv/bin/python), SEED_EDIT_QWENEDIT_SCRIPT
(default <ws>/character_dataset.py), HF_HUB_CACHE and HF_HOME (the default hub), Z_IMAGE_HF_HOME (the
Z-Image hub, through movie_ui_lib.zimage_hub) and HOME. The mflux weights and LoRAs are looked up only at
their pinned revisions, in the Z-Image hub and then the default hub.

Python 3.9 and 3.13. The top level imports only the standard library, movie_ui_lib and movie_ui_seedgen;
PIL, psutil and content_safety are imported inside the functions that use them.
"""

import glob
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

import movie_ui_lib as lib
import movie_ui_seedgen as seedgen

WS = os.path.dirname(os.path.realpath(__file__))
EDIT_MODEL = "Qwen/Qwen-Image-Edit-2511"                                  # character_dataset.EDIT_MODEL
EDIT_LORA_REPO = "lightx2v/Qwen-Image-Edit-2511-Lightning"                # character_dataset.EDIT_LORA_REPO
EDIT_LORA_FILE = "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors"
EDIT_STEPS = 8
EDIT_TRUE_CFG = 1.0
LEGACY_EDIT_MODEL = "qwen2511-bf16"
MODEL_IDS = seedgen.QWEN_MODEL_IDS
MFLUX_MIN_VERSION = (0, 24, 0)
MFLUX_GUIDANCE = 1.0
DEFAULT_MFLUX_PYTHON = "~/mflux-edit/.venv/bin/python"   # expanded at use
AVAIL_WAIT_S = 600               # character_dataset.AVAIL_WAIT_S
CHILD_TIMEOUT_S = 3600           # the timeout floor (bin/seed-edit's former fixed timeout)
JOB_TIMEOUT_S = 600              # the budget per job above the floor
MFLUX_LINE_RE = re.compile(r"^seed-edit-child done (\d+) ([0-9]+\.[0-9])$")
QWENEDIT_LINE_RE = re.compile(r"^(\S+) (ok|blocked) ([0-9]+\.[0-9])s$")
CHILD = None    # the running Qwen child's Popen, or None


class SelectionError(Exception):
    """A bad edit-model or LoRA option; the message is the refusal text."""


class Unavailable(Exception):
    """The selection cannot run here now; the message is the refusal text."""


# ---------------------------------------------------------------------------
# Host checks and the registry lookups (moved from bin/seed-edit; seed models SQ15-SQ18)
# ---------------------------------------------------------------------------

def avail_gib():
    import psutil
    return psutil.virtual_memory().available / 2 ** 30


def total_gib():
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 2 ** 30
    except (ValueError, OSError):
        return None


def missing_modules(names):
    """The names importlib cannot find (find_spec None, ImportError or ValueError); imports nothing."""
    missing = []
    for name in names:
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            missing.append(name)
    return missing


def modules_problem(names):
    missing = missing_modules(names)
    return "%s not importable by %s" % (", ".join(missing), sys.executable) if missing else None


def default_hub():
    """$HF_HUB_CACHE, else <$HF_HOME or ~/.cache/huggingface>/hub (huggingface_hub's own rule)."""
    if os.environ.get("HF_HUB_CACHE"):
        return os.environ["HF_HUB_CACHE"]
    return os.path.join(os.environ.get("HF_HOME") or os.path.expanduser("~/.cache/huggingface"), "hub")


def mflux_python():
    return os.environ.get("SEED_EDIT_MFLUX_PYTHON") or os.path.expanduser(DEFAULT_MFLUX_PYTHON)


def find_lightning(hubs):
    """The snapshot path of the Lightning LoRA file in the first hub holding it (a non-empty regular
    file through its realpath), or None."""
    for hub in hubs:
        snapshot = lib.choose_snapshot(os.path.join(hub, lib.repo_dir_name(EDIT_LORA_REPO)))[0]
        if snapshot is None:
            continue
        path = os.path.join(snapshot, EDIT_LORA_FILE)
        real = os.path.realpath(path)
        if os.path.isfile(real) and os.path.getsize(real) > 0:
            return path
    return None


def bf16_problem():
    """None when the diffusers bf16 child's weights and modules are present, else the first problem."""
    problem = modules_problem(["PIL", "psutil", "torch", "diffusers", "transformers", "huggingface_hub"])
    if problem:
        return problem
    hub = default_hub()
    ok, detail = lib.model_check(EDIT_MODEL, hub)
    if not ok:
        return detail
    if find_lightning([hub]) is None:
        return "Lightning LoRA %s is not in %s" % (EDIT_LORA_FILE, hub)
    return None


def mflux_version(venv):
    """(number of mflux-*.dist-info/METADATA files in venv, (parsed, text) of the highest version that
    parses or None). Reads the files only; nothing is imported."""
    paths = sorted(glob.glob(os.path.join(venv, "lib", "python*", "site-packages", "mflux-*.dist-info",
                                          "METADATA")))
    best = None
    for path in paths:
        text = None
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("Version: "):
                        text = line[len("Version: "):].strip()
                        break
        except OSError:
            continue
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)", text or "")
        if match:
            parsed = tuple(int(g) for g in match.groups())
            if best is None or parsed > best[0]:
                best = (parsed, text)
    return len(paths), best


def pinned_snapshot(repo, revision, hubs):
    """(snapshot, repo_dir) of the first hub holding <repo dir>/snapshots/<revision> as a directory,
    else (None, None)."""
    for hub in hubs:
        repo_dir = os.path.join(hub, lib.repo_dir_name(repo))
        snapshot = os.path.join(repo_dir, "snapshots", revision)
        if os.path.isdir(snapshot):
            return snapshot, repo_dir
    return None, None


def pinned_file(repo, revision, name, hubs):
    """<hub>/<repo dir>/snapshots/<revision>/<name> in the first hub where its realpath is a non-empty
    regular file (the snapshot path is returned, not the realpath), else None."""
    for hub in hubs:
        path = os.path.join(hub, lib.repo_dir_name(repo), "snapshots", revision, name)
        real = os.path.realpath(path)
        if os.path.isfile(real) and os.path.getsize(real) > 0:
            return path
    return None


def weights_problem(entry, hubs):
    """(problem, model dir, built-in LoRA path) of an mflux registry model in hubs. problem is None
    when the pinned snapshot is intact (for qwen21 also with its component configs and processor/)
    and the built-in LoRA, if any, is present."""
    where = " or ".join(hubs)
    setup = "(run bin/seed-edit-setup --model %s)" % entry["id"]
    snapshot, repo_dir = pinned_snapshot(entry["repo"], entry["revision"], hubs)
    if snapshot is None:
        return "%s@%s is not in %s %s" % (entry["repo"], entry["revision"][:12], where, setup), None, None
    problems = list(lib.intact_scan(snapshot, repo_dir)[0])
    if entry["family"] == "qwen21":
        problems += ["missing %s" % rel for rel in seedgen.QWEN21_REQUIRED
                     if not os.path.isfile(os.path.join(snapshot, rel))]
        if not os.path.isdir(os.path.join(snapshot, "processor")):
            problems.append("missing processor/")
    if problems:
        return "%s: %s %s" % (entry["repo"], "; ".join(problems), setup), None, None
    lora = entry["builtin_lora"]
    lora_path = None
    if lora is not None:
        lora_path = pinned_file(lora["repo"], lora["revision"], lora["file"], hubs)
        if lora_path is None:
            return "Lightning LoRA %s is not in %s %s" % (lora["file"], where, setup), None, None
    return None, snapshot, lora_path


def qwen_hubs():
    """Seed models SQ16: the hubs searched for the mflux weights and LoRAs, in order."""
    return [lib.zimage_hub(), default_hub()]


def mflux_env_problem(entry):
    """Seed models SQ16 (amended by §14a item H): None when the mflux venv holds mflux 0.24.0 or newer,
    else the first problem. The setup hint names entry's own --model, so one setup run installs the
    venv and that model."""
    setup = "(run bin/seed-edit-setup --model %s)" % entry["id"]
    py = mflux_python()
    if not os.access(py, os.X_OK):
        return "no mflux venv at %s %s" % (py, setup)
    venv = os.path.dirname(os.path.dirname(py))
    count, best = mflux_version(venv)
    if count == 0:
        return "mflux is not installed in %s %s" % (venv, setup)
    if best is None:
        return "cannot read the mflux version in %s" % venv
    if best[0] < MFLUX_MIN_VERSION:
        return "mflux %s in %s is older than 0.24.0 %s" % (best[1], venv, setup)
    return None


def lora_problem(lora, hubs):
    """Seed models SQ16: (None, snapshot path) of a registry LoRA's pinned file, else (problem, None)."""
    path = pinned_file(lora["repo"], lora["revision"], lora["file"], hubs)
    if path is None:
        return ("%s is not in %s (run bin/seed-edit-setup --lora %s)" % (lora["file"], " or ".join(hubs), lora["id"]),
                None)
    return None, path


def qwen_model_problem(entry):
    """Seed models SQ16: (problem, paths) of a registry model; paths is {"model_path", "builtin_lora"}
    for a ready mflux entry, else {}."""
    if entry["backend"] == "diffusers":
        return bf16_problem(), {}
    problem = mflux_env_problem(entry)
    if problem is not None:
        return problem, {}
    problem, model_path, builtin_lora = weights_problem(entry, qwen_hubs())
    if problem is not None:
        return problem, {}
    problem = modules_problem(["PIL", "psutil", "torch", "transformers"])
    if problem is not None:
        return problem, {}
    return None, {"model_path": model_path, "builtin_lora": builtin_lora}


def memory_problem(entry):
    """Seed models SQ16: None when this host's total memory reaches the entry's floor, else why not."""
    t = total_gib()
    if t is None:
        return "cannot read this host's memory size"
    if t < entry["memory_gib"]:
        return "needs a host with at least %g GiB of memory (this host has %.1f GiB)" % (entry["memory_gib"], t)
    return None


def wait_for_memory(floor, label, tag="seed-edit"):
    """SG13 step 4, qwen edit models QE7: wait up to AVAIL_WAIT_S for floor GiB available, else
    Unavailable. tag starts the waiting line (seed-edit, ltx-movie)."""
    now = avail_gib()
    if now >= floor:
        return
    print("%s: waiting up to %d s for %g GiB available (now %.1f GiB)" % (tag, AVAIL_WAIT_S, floor, now), flush=True)
    deadline = time.monotonic() + AVAIL_WAIT_S
    while True:
        now = avail_gib()
        if now >= floor:
            return
        if time.monotonic() >= deadline:
            raise Unavailable("only %.1f GiB available after waiting %d s; %s needs %g GiB; free memory and retry"
                              % (now, AVAIL_WAIT_S, label, floor))
        time.sleep(5)


# ---------------------------------------------------------------------------
# The child (SG21, qwen edit models QE8, QE9)
# ---------------------------------------------------------------------------

def _kill_group(pid):
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except OSError:
        pass


def run_child(argv, env, on_line, timeout_s, log_path=None):
    """SG21, qwen edit models QE8: run a Qwen child in its own session with a timeout_s timer that
    SIGKILLs its process group; echo each line to stdout (and append it to log_path when given) and
    pass it to on_line without its newline. Text mode reads with universal newlines, so a progress
    bar's carriage return also ends a line and never hides a result line. Returns (exit code, True
    when the timer killed the child); any other SIGKILL (a memory-pressure kill) is an ordinary -9
    exit. The child is killed if this function exits early (an exception in on_line, or an
    interrupt)."""
    global CHILD
    proc = subprocess.Popen(argv, cwd=WS, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                            bufsize=1, start_new_session=True)
    CHILD = proc
    timed_out = threading.Event()

    def on_timeout():
        if proc.poll() is None:
            timed_out.set()
            _kill_group(proc.pid)

    timer = threading.Timer(timeout_s, on_timeout)
    timer.daemon = True
    timer.start()
    log = None
    try:
        if log_path is not None:
            log = open(log_path, "a", encoding="utf-8")
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            if log is not None:
                log.write(line)
                log.flush()
            on_line(line.rstrip("\n"))
        return proc.wait(), timed_out.is_set()
    finally:
        timer.cancel()
        if proc.poll() is None:
            _kill_group(proc.pid)
            proc.wait()
        proc.stdout.close()
        if log is not None:
            log.close()
        CHILD = None


def kill_running_child():
    """Qwen edit models QE9: SIGKILL the running Qwen child's process group, if there is one."""
    if CHILD is not None:
        _kill_group(CHILD.pid)


# ---------------------------------------------------------------------------
# The selection (qwen edit models Section 2.3, 2.4)
# ---------------------------------------------------------------------------

def check_lora_args(values, entry, flag="--lora"):
    """bin/seed-edit's check_loras (seed models SQ12 rows 12-16) with the flag name as a parameter:
    the cleaned [{"id", "scale"}] in registry order, or SelectionError."""
    loras = []
    for value in values:
        match = re.match(r"^([a-z0-9-]+)=(.*)$", value)
        if not match:
            raise SelectionError("%s must be ID=SCALE (got %s)" % (flag, value))
        lora_id, text = match.group(1), match.group(2)
        if lora_id not in seedgen.QWEN_LORA_IDS:
            raise SelectionError("%s: unknown LoRA %s; known: %s" % (flag, lora_id, ", ".join(seedgen.QWEN_LORA_IDS)))
        if any(item["id"] == lora_id for item in loras):
            raise SelectionError("%s %s is given twice" % (flag, lora_id))
        lora = seedgen.qwen_lora(lora_id)
        if lora["family"] != entry["family"]:
            raise SelectionError("%s %s is for %s, not %s" % (flag, lora_id, seedgen.QWEN_FAMILIES[lora["family"]],
                                                              entry["label"]))
        try:
            scale = float(text)
        except ValueError:
            scale = None
        if scale is None or not 0 < scale <= seedgen.SCALE_MAX:
            raise SelectionError("%s %s scale must be a number above 0 and at most 2" % (flag, lora_id))
        loras.append({"id": lora_id, "scale": scale})
    return seedgen.registry_order(loras)


def cli_selection(model_arg, lora_args, model_flag="--qwen-model", lora_flag="--lora"):
    """(model_id, loras) of a tool's edit-model options, or SelectionError (qwen edit models QE10)."""
    if model_arg is None:
        if lora_args is not None:
            raise SelectionError("%s needs %s" % (lora_flag, model_flag))
        return seedgen.DEFAULT_QWEN_MODEL, seedgen.default_loras(seedgen.DEFAULT_QWEN_MODEL)
    if model_arg not in MODEL_IDS:
        raise SelectionError("%s must be one of %s" % (model_flag, ", ".join(MODEL_IDS)))
    return model_arg, check_lora_args(lora_args or [], seedgen.qwen_model(model_arg), lora_flag)


def settings(model_id, loras):
    return seedgen.qwen_settings(model_id, loras)


def selection_of(edit):
    """(model_id, [{"id", "scale"}]) of a recorded settings block."""
    return edit["qwen_model"]["id"], [{"id": l["id"], "scale": l["scale"]} for l in edit["loras"]]


def label(model_id):
    return seedgen.qwen_model(model_id)["label"]


def multiple(model_id):
    return seedgen.qwen_model(model_id)["multiple"]


def memory_floor(model_id):
    return seedgen.qwen_model(model_id)["memory_gib"]


def child_timeout(n_jobs):
    return max(CHILD_TIMEOUT_S, JOB_TIMEOUT_S * n_jobs)


def generator_text(model_id, loras):
    """The manifest "generator" string of a selection; the legacy model keeps today's exact text."""
    if model_id == LEGACY_EDIT_MODEL:
        return "%s + %s, %d steps" % (EDIT_MODEL, EDIT_LORA_FILE, EDIT_STEPS)
    entry, chosen = seedgen.qwen_model(model_id), seedgen.qwen_settings(model_id, loras)
    listed = ", ".join("%s@%g" % (l["id"], l["scale"]) for l in chosen["loras"]) or "none"
    return "%s (%s) + LoRAs %s, %d steps" % (entry["label"], entry["repo"], listed, chosen["steps"])


def install_problem(model_id, loras):
    """(None, paths) when the selection is installed, else (refusal text, {}); paths is
    {"model_path", "builtin_lora", "lora_paths"} ({} entries for the diffusers model). The texts are
    bin/seed-edit's SQ21 steps 1-2."""
    entry = seedgen.qwen_model(model_id)
    problem, paths = qwen_model_problem(entry)
    if problem is not None:
        return "%s is unavailable: %s" % (entry["label"], problem), {}
    lora_paths = []
    for item in seedgen.registry_order(loras):
        lora = seedgen.qwen_lora(item["id"])
        problem, path = lora_problem(lora, qwen_hubs())
        if problem is not None:
            return "LoRA %s is unavailable: %s" % (lora["label"], problem), {}
        lora_paths.append(path)
    return None, dict(paths, lora_paths=lora_paths)


def selection_problem(model_id, loras):
    """None when the selection can run on this host (its total memory reaches the entry's memory_gib
    and it is installed), else the refusal text. Memory first, as the probe (seed models SQ18)."""
    entry = seedgen.qwen_model(model_id)
    memory = memory_problem(entry)
    if memory is not None:
        return "%s is unavailable: %s" % (entry["label"], memory)
    return install_problem(model_id, loras)[0]


# ---------------------------------------------------------------------------
# run_jobs (qwen edit models QE13-QE16)
# ---------------------------------------------------------------------------

def run_jobs(model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None, noun="job"):
    """Run one Qwen edit child over jobs and screen every output (qwen edit models spec QE13-QE16)."""
    entry = seedgen.qwen_model(model_id)
    problem, paths = install_problem(model_id, loras)
    if problem is not None:
        raise Unavailable(problem)
    os.makedirs(work_dir, exist_ok=True)
    chosen = seedgen.qwen_settings(model_id, loras)
    by_n = dict((job["n"], job) for job in jobs)
    done = {}

    def finish(n, status, seconds):
        done[n] = (status, seconds)
        if on_result is not None:
            on_result({"n": n, "output_path": by_n[n]["output_path"], "status": status, "seconds": seconds})

    if entry["backend"] == "diffusers":
        first = jobs[0]["source"]
        spec_jobs = []
        for job in jobs:
            item = {"prompt": job["prompt"], "output_path": job["stage_path"], "seed": job["seed"],
                    "width": width, "height": height}
            if job["source"] != first:
                item["image"] = job["source"]
            spec_jobs.append(item)
        spec_path = os.path.join(work_dir, "qwenedit_spec.json")
        lib.write_json_atomic(spec_path, {
            "image": first, "model": EDIT_MODEL, "lora_repo": EDIT_LORA_REPO, "lora_file": EDIT_LORA_FILE,
            "steps": EDIT_STEPS, "true_cfg": EDIT_TRUE_CFG, "skill": skill, "jobs": spec_jobs,
            "report_path": os.path.join(work_dir, "qwenedit_report.json")})
        by_stage = dict((os.path.basename(job["stage_path"]), job["n"]) for job in jobs)
        script = os.environ.get("SEED_EDIT_QWENEDIT_SCRIPT") or os.path.join(WS, "character_dataset.py")
        argv = [sys.executable, script, "qwenedit", "--spec", spec_path]
        env = dict(os.environ, PYTHONUNBUFFERED="1")

        def handle(line):
            match = QWENEDIT_LINE_RE.match(line)
            n = by_stage.get(match.group(1)) if match else None
            if n is None or n in done:
                return
            if match.group(2) == "ok":
                os.replace(by_n[n]["stage_path"], by_n[n]["output_path"])
            finish(n, match.group(2), float(match.group(3)))
    else:
        import content_safety
        from PIL import Image
        builtin = entry["builtin_lora"]
        ordered = seedgen.registry_order(loras)
        spec_path = os.path.join(work_dir, "mflux_spec.json")
        lib.write_json_atomic(spec_path, {
            "family": entry["family"], "model_path": paths["model_path"],
            "lora_paths": ([paths["builtin_lora"]] if builtin is not None else []) + paths["lora_paths"],
            "lora_scales": ([builtin["scale"]] if builtin is not None else []) + [item["scale"] for item in ordered],
            "width": width, "height": height, "steps": chosen["steps"], "guidance": MFLUX_GUIDANCE,
            "scheduler": chosen["scheduler"],
            "jobs": [{"n": job["n"], "seed": job["seed"], "prompt": job["prompt"], "source": job["source"],
                      "output_path": job["stage_path"]} for job in jobs]})
        argv = [mflux_python(), os.path.join(WS, "seed_edit_mflux_child.py"), "--spec", spec_path]
        env = seedgen.hf_child_env(os.environ, PYTHONUNBUFFERED="1", HF_HUB_OFFLINE="1")

        def handle(line):
            match = MFLUX_LINE_RE.match(line)
            n = int(match.group(1)) if match else None
            if n not in by_n or n in done:
                return
            job = by_n[n]
            with Image.open(job["stage_path"]) as img:
                rgb = img.convert("RGB")
            try:
                content_safety.assert_image_safe(rgb, skill=skill, prompt=job["prompt"])
            except content_safety.ContentSafetyError:
                os.remove(job["stage_path"])
                finish(n, "blocked", float(match.group(2)))
                return
            os.replace(job["stage_path"], job["output_path"])
            finish(n, "ok", float(match.group(2)))

    last = [""]

    def on_line(line):
        if line.strip():
            last[0] = line.strip()
        handle(line)

    timeout = child_timeout(len(jobs))
    code, timed_out = run_child(argv, env, on_line, timeout, log_path)
    failure = None
    if timed_out:
        failure = "%s child timed out after %d s" % (entry["label"], timeout)
    elif code != 0:
        failure = "%s child exited %d: %s" % (entry["label"], code, last[0] or "-")
    else:
        missing = [job["n"] for job in jobs if job["n"] not in done]
        if missing:
            failure = "%s child exited 0 without finishing %s %d" % (entry["label"], noun, missing[0])
    for job in jobs:
        if job["n"] not in done and os.path.exists(job["stage_path"]):
            os.remove(job["stage_path"])      # plan ruling R4: a failed job leaves no staged file (QE13)
    results = [{"n": job["n"], "output_path": job["output_path"],
                "status": done[job["n"]][0] if job["n"] in done else "failed",
                "seconds": done[job["n"]][1] if job["n"] in done else None} for job in jobs]
    return results, failure
