#!/usr/bin/env python3
"""install_pkg.py -- install the ltx-chain deployment package on the target Mac.

Spec: docs/superpowers/specs/2026-09-25-ltx-chain-deploy-package-design.md (sections 12-13)
Plan: docs/superpowers/plans/2026-09-25-ltx-chain-deploy-package.md

    /usr/bin/python3 <pkg>/scripts/deploy/install_pkg.py --phase {preflight,system-python,user,verify,accept}
        [--apply] [--package-root PATH] [--gpu | --gpu-all]

Runs under Apple's /usr/bin/python3 (3.9.6); stdlib only; Python 3.9 language
level. The shared helpers (entry I/O, hashing, L1/L2/L3 scanning, known-secret
loading, CheckResult) are loaded from build_pkg.py in this file's own directory
(R8). This module keeps its own HOOKS and constants; it never calls a build_pkg
function that reads HOOKS. Every printed line that carries package-, manifest-,
target-, exception- or subprocess-derived text goes through safe_line() first.
"""
import argparse
import glob
import hashlib
import importlib.util
import json
import os
import platform
import re
import signal
import stat
import subprocess
import sys
import time


def _load_build_pkg():
    spec = importlib.util.spec_from_file_location("build_pkg", os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_pkg.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_bp = _load_build_pkg()
CheckResult = _bp.CheckResult

REQUIRED_USER = "reubenpatterson"
REQUIRED_HOME = "/Users/reubenpatterson"
FRAMEWORK_ROOT = "/Library/Frameworks/Python.framework"
VOLUMES_ROOT = "/Volumes"
BREW_BIN = "/opt/homebrew/bin/brew"
BREW_PY312 = "/opt/homebrew/opt/python@3.12/bin/python3.12"
LSOF_PATH = "/usr/sbin/lsof"
SYSTEM_PY = "/usr/bin/python3"
CHUNK_SIZE = 8 * 1024 * 1024
SCHEMA_VERSION = 4
MIN_PYTHON = (3, 9)
MIN_MEMSIZE_BYTES = 51539607552          # 48 GiB
INSTALL_HEADROOM_BYTES = 10 * 1024 ** 3
STORY_PORT = 8177

EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_USAGE = 2
EXIT_REFUSED = 4
EXIT_GPU_REFUSED = 5

PHASES = ("preflight", "system-python", "user", "verify", "accept")
SYSTEM_COMPONENTS = ("F1", "F2")
FFMPEG_RE = re.compile(r"^ffmpeg version n?(\d+)\.")
FFPROBE_RE = re.compile(r"^ffprobe version n?(\d+)\.")
PY312_RE = re.compile(r"^Python 3\.12\.\d+\s*$")
HF_HOME_LINE_RE = re.compile(r"^\s*(export\s+)?HF_HOME=")


def _real_spawn(argv, cwd=None, env=None, stdout_path=None, new_session=False):
    out = open(stdout_path, "wb") if stdout_path else subprocess.DEVNULL
    try:
        return subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out,
                                stderr=subprocess.STDOUT, start_new_session=new_session)
    finally:
        if stdout_path:
            out.close()


HOOKS = dict(_bp.HOOKS)
HOOKS["spawn"] = _real_spawn
HOOKS["killpg"] = os.killpg


class InstallError(Exception):
    """A runtime failure during --apply (exit 1)."""


def home():
    return os.path.expanduser("~")


def workspace():
    return home() + "/local_model_harness/qwen-agent-workspace"


def framework_py():
    return FRAMEWORK_ROOT + "/Versions/3.13/bin/python3"


def ltx25_model_path():
    return home() + "/ltx-2-mlx/models/ltx-2.5-mlx-q8"


def receipts_dir(package_id):
    return workspace() + "/generated/deploy-receipts/" + package_id


def default_package_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def iso_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", HOOKS["now_utc"]())


class InstallCtx(object):
    def __init__(self, args):
        self.args = args
        self.phase = args.phase
        self.package_root = os.path.abspath(args.package_root) if args.package_root else default_package_root()
        self.is_receipts = not os.path.isdir(self.package_root + "/payload")
        self.manifest = None
        self.entries = []
        self.receipt_entries = []
        self.target_status = {}
        self.dir_modes = {}
        self.secrets = _bp.load_known_secrets()[0]   # L3 values: compared only, never printed
        self.memsize = -1
        self.ffmpeg = None
        self.ffprobe = None

    def package_id(self):
        if self.manifest and self.manifest.get("package_id"):
            return self.manifest["package_id"]
        return os.path.basename(self.package_root)


def has_secret(ctx, text):
    """True if text holds a known secret value (L3) or a secret-shaped string (L2)."""
    data = text.encode("utf-8", "backslashreplace")
    return bool(_bp.KnownSecretScanner(ctx.secrets).feed(data) or _bp.l2_scan_bytes(data))


def safe_line(ctx, line, withheld):
    """line, or withheld (fixed words, check ids, reasons and counts only) if line holds secret material."""
    return withheld if has_secret(ctx, line) else line


# ---------------------------------------------------------------------------
# Checks I01-I20 (spec 12.3)
# ---------------------------------------------------------------------------
def _not_loaded(check_id):
    return CheckResult(check_id, False, "manifest entries not loaded (see I06)", True)


def check_i01(ctx):
    ok = sys.version_info >= MIN_PYTHON
    return CheckResult("I01", ok, "python %s (need >= %d.%d)" % (platform.python_version(), MIN_PYTHON[0], MIN_PYTHON[1]), True)


def check_i02(ctx):
    system, machine = platform.system(), platform.machine()
    return CheckResult("I02", system == "Darwin" and machine == "arm64", "%s %s (need Darwin arm64)" % (system, machine), True)


def check_i03(ctx):
    rc, out = HOOKS["run"](["/usr/sbin/sysctl", "-n", "hw.memsize"])
    memsize = int(out.strip()) if rc == 0 and out.strip().isdigit() else -1
    ctx.memsize = memsize
    message = ("hw.memsize=%d bytes, need >= %d (48 GiB): the measured peak was 36.61 GiB with the vision model "
               "at 0.70 memory utilization, so a 16 GiB Mac cannot run it" % (memsize, MIN_MEMSIZE_BYTES))
    return CheckResult("I03", memsize >= MIN_MEMSIZE_BYTES, message, True)


def check_i04(ctx):
    rc, out = HOOKS["run"](["/usr/bin/sw_vers", "-productVersion"])
    text = out.strip()
    found = re.match(r"^(\d+)", text)
    major = int(found.group(1)) if rc == 0 and found else -1
    return CheckResult("I04", major >= 26, "macOS %s (need major >= 26)" % text, True)


def check_i05(ctx):
    problems = []
    try:
        pw_dir = HOOKS["getpwnam"](REQUIRED_USER).pw_dir
    except KeyError:
        pw_dir = None
    if pw_dir != REQUIRED_HOME:
        problems.append("user %s has home %r, expected %s" % (REQUIRED_USER, pw_dir, REQUIRED_HOME))
    if ctx.phase != "system-python":
        user = HOOKS["getuser"]()
        if user != REQUIRED_USER:
            problems.append("running as %r, expected %s" % (user, REQUIRED_USER))
        if os.environ.get("HOME") != REQUIRED_HOME:
            problems.append("$HOME=%r, expected %s" % (os.environ.get("HOME"), REQUIRED_HOME))
    ok = not problems
    return CheckResult("I05", ok, "account %s with home %s" % (REQUIRED_USER, REQUIRED_HOME) if ok else "; ".join(problems), True)


def check_i06(ctx):
    root = ctx.package_root
    manifest_path = root + "/MANIFEST.json"
    try:
        with open(manifest_path, "rb") as fh:
            manifest = json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        return CheckResult("I06", False, "cannot read %s: %s" % (manifest_path, exc), True)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        return CheckResult("I06", False, "%s is not a schema_version %d manifest" % (manifest_path, SCHEMA_VERSION), True)
    ctx.manifest = manifest
    problems = []
    if os.path.lexists(root + "/BUILD-FAILED.json"):
        problems.append("BUILD-FAILED.json is present")
    entries_path = root + "/" + manifest.get("entries_file", "MANIFEST-ENTRIES.jsonl")
    try:
        entries_sha = _bp.sha256_file(entries_path)
    except OSError:
        entries_sha = None
    if entries_sha != manifest.get("entries_sha256"):
        problems.append("sha256(%s) does not match entries_sha256" % entries_path)
    else:
        ctx.entries = _bp.read_entries(entries_path)
    root_files = manifest.get("root_files", {})
    for rel in sorted(root_files):
        try:
            got = _bp.sha256_file(root + "/" + rel)
        except OSError:
            got = None
        if got != root_files[rel]:
            problems.append("root file %s does not match its recorded sha256" % rel)
    if ctx.phase in ("preflight", "system-python", "user") and ctx.is_receipts:
        problems.append("%s has no payload/: it is a receipts root, from which only --phase verify and --phase accept run" % root)
    ok = not problems
    return CheckResult("I06", ok, "package %s: %d entries" % (manifest.get("package_id"), len(ctx.entries)) if ok else "; ".join(problems), True)


def check_i07(ctx):
    root = ctx.package_root
    if not os.path.isdir(root):
        return CheckResult("I07", False, "package root %s is missing" % root, True)
    found = [root + "/" + rel for rel, st in _bp.list_tree(root) if rel.rsplit("/", 1)[-1] == ".DS_Store"]
    ok = not found
    message = "no .DS_Store under the package" if ok else (
        "%d .DS_Store file(s): %s; remove them with: find \"%s\" -name .DS_Store -delete" % (len(found), ", ".join(found[:10]), root))
    return CheckResult("I07", ok, message, True)


def check_i08(ctx):
    root = ctx.package_root
    if not os.path.isdir(root):
        return CheckResult("I08", False, "package root %s is missing" % root, True)
    allow_path = root + "/scripts/deploy/credential_allowlist.json"
    try:
        allow, _ = _bp.load_allowlist(allow_path)
    except (OSError, ValueError) as exc:
        return CheckResult("I08", False, "cannot load %s: %s" % (allow_path, exc), True)
    failures, allowed = _bp.scan_package(root, allow)
    ok = not failures
    message = ("L1+L2 rescan clean (%d allowlisted hit(s))" % len(allowed)) if ok else (
        "%d finding(s): %s" % (len(failures), "; ".join(failures[:20])))
    return CheckResult("I08", ok, message, True)


def check_i09(ctx):
    if ctx.manifest is None or not ctx.entries:
        return _not_loaded("I09")
    need = sum(e["b"] for e in ctx.entries if e["k"] == "f" and not os.path.lexists(e["t"])) + INSTALL_HEADROOM_BYTES
    free = HOOKS["statvfs_free"](REQUIRED_HOME)
    return CheckResult("I09", free >= need, "free=%d need=%d (absent files + %d headroom) on %s" % (free, need, INSTALL_HEADROOM_BYTES, REQUIRED_HOME), True)


def target_matches_entry(target, entry):
    try:
        st = os.lstat(target)
    except OSError:
        return False, "missing"
    kind = entry["k"]
    if kind == "f":
        if not stat.S_ISREG(st.st_mode):
            return False, "not a regular file"
        if st.st_size != entry["b"]:
            return False, "size differs"
        try:
            actual = _bp.sha256_file(target)
        except OSError:
            return False, "unreadable"
        if actual != entry["h"]:
            return False, "content differs"
        return True, ""
    if kind == "l":
        if not stat.S_ISLNK(st.st_mode):
            return False, "not a symlink"
        if os.readlink(target) != entry["l"]:
            return False, "symlink target differs"
        return True, ""
    if not stat.S_ISDIR(st.st_mode):
        return False, "not a directory"
    return True, ""


def build_receipt_entries(ctx):
    root = ctx.package_root
    manifest = ctx.manifest
    dest = receipts_dir(ctx.package_id())
    items = [("MANIFEST.json", None), (manifest.get("entries_file", "MANIFEST-ENTRIES.jsonl"), manifest.get("entries_sha256"))]
    items.extend(sorted(manifest.get("root_files", {}).items()))
    out = []
    for rel, digest in items:
        src = root + "/" + rel
        try:
            st = os.lstat(src)
        except OSError:
            continue
        if digest is None:
            digest = _bp.sha256_file(src)
        out.append({"k": "f", "c": "RECEIPTS", "t": dest + "/" + rel, "b": st.st_size,
                    "m": "%04o" % stat.S_IMODE(st.st_mode), "h": digest, "mt": st.st_mtime_ns, "_src": src})
    return out


def install_check_entries(ctx):
    entries = list(ctx.entries)
    if ctx.phase == "user":
        ctx.receipt_entries = build_receipt_entries(ctx)
        entries.extend(ctx.receipt_entries)
    return entries


def check_i10(ctx):
    if ctx.manifest is None or not ctx.entries:
        return _not_loaded("I10")
    collisions = []
    for entry in install_check_entries(ctx):
        target = entry["t"]
        if not os.path.lexists(target):
            ctx.target_status[target] = "absent"
            continue
        same, reason = target_matches_entry(target, entry)
        if not same:
            collisions.append((target, reason))
        ctx.target_status[target] = "same" if same else reason
    for target, reason in collisions:
        print(safe_line(ctx, "COLLISION %s: %s" % (reason, target),
                        "COLLISION %s: (path withheld: it contained secret material)" % reason))
    if collisions:
        print("COLLISIONS %d" % len(collisions))
    ok = not collisions
    message = "every target is absent or identical" if ok else (
        "%d collision(s) listed above; the target Mac must be fresh (D11)" % len(collisions))
    return CheckResult("I10", ok, message, True)


def check_i11(ctx):
    if ctx.manifest is None or not ctx.entries:
        return _not_loaded("I11")
    seen = {}
    for entry in ctx.entries:
        seen.setdefault(entry["t"].lower(), []).append(entry["t"])
    dups = [values for values in seen.values() if len(values) > 1]
    ok = not dups
    return CheckResult("I11", ok, "no case-insensitive target duplicates" if ok else "; ".join(" | ".join(v) for v in dups[:20]), True)


def check_i12(ctx):
    problems = []
    for name, rx in (("ffmpeg", FFMPEG_RE), ("ffprobe", FFPROBE_RE)):
        path = HOOKS["which"](name)
        if not path:
            problems.append("%s not found on PATH" % name)
            continue
        setattr(ctx, name, path)
        rc, out = HOOKS["run"]([path, "-version"])
        lines = out.splitlines()
        first = lines[0] if lines else ""
        found = rx.match(first)
        if rc != 0 or not found or found.group(1) != "9":
            problems.append("%s: %r (need major version 9)" % (path, first))
    ok = not problems
    return CheckResult("I12", ok, "ffmpeg/ffprobe major version 9" if ok else "; ".join(problems), True)


def check_i13(ctx):
    ok = os.path.isfile(BREW_BIN) and os.access(BREW_BIN, os.X_OK)
    return CheckResult("I13", ok, "%s %s" % (BREW_BIN, "is executable" if ok else "is missing or not executable (install Homebrew)"), True)


def check_i14(ctx):
    rc, out = HOOKS["run"]([BREW_PY312, "--version"])
    ok = rc == 0 and PY312_RE.match(out) is not None
    return CheckResult("I14", ok, "%s --version -> %r (need Python 3.12.x; brew install python@3.12)" % (BREW_PY312, out.strip()), True)


def check_i15(ctx):
    missing = [p for p in (LSOF_PATH, SYSTEM_PY) if not (os.path.isfile(p) and os.access(p, os.X_OK))]
    return CheckResult("I15", not missing, "%s and %s are executable" % (LSOF_PATH, SYSTEM_PY) if not missing else "missing or not executable: %s" % ", ".join(missing), True)


def check_i16(ctx):
    ok = bool(HOOKS["port_free"](STORY_PORT))
    return CheckResult("I16", ok, "port %d is %s" % (STORY_PORT, "free" if ok else "in use"), True)


def zshenv_volume_lines(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    return [number for number, line in enumerate(lines, 1) if HF_HOME_LINE_RE.match(line) and "/Volumes/" in line]


def check_i17(ctx):
    want = home() + "/hf_home"
    problems = []
    env_value = os.environ.get("HF_HOME")
    if env_value != want:
        problems.append("process HF_HOME=%r, expected %r" % (env_value, want))
    rc, out = HOOKS["run"](["/bin/zsh", "-c", 'printf "%s" "$HF_HOME"'])
    if rc != 0 or out != want:
        problems.append("zsh HF_HOME=%r, expected %r" % (out, want))
    bad = zshenv_volume_lines(home() + "/.zshenv")
    if bad:
        problems.append("~/.zshenv HF_HOME line(s) mentioning /Volumes/ at line(s) %s" % ", ".join(str(n) for n in bad))
    ok = not problems
    if ok:
        return CheckResult("I17", True, "HF_HOME=%s in the process and in zsh" % want, True)
    return CheckResult("I17", False, "; ".join(problems) + '. Add exactly this line to ~/.zshenv: export HF_HOME="/Users/reubenpatterson/hf_home" (this installer never edits dotfiles)', True)


def check_i18(ctx):
    ws = workspace()
    if os.path.lexists(ws):
        ok = os.path.isdir(ws) and os.access(ws, os.W_OK)
        return CheckResult("I18", ok, "%s %s" % (ws, "is a writable directory" if ok else "is not a writable directory"), True)
    ancestor = os.path.dirname(ws)
    while not os.path.lexists(ancestor):
        ancestor = os.path.dirname(ancestor)
    ok = os.path.isdir(ancestor) and os.access(ancestor, os.W_OK)
    return CheckResult("I18", ok, "%s absent; nearest ancestor %s %s" % (ws, ancestor, "is writable" if ok else "is not writable"), True)


def check_i19(ctx):
    euid = HOOKS["geteuid"]()
    if ctx.phase == "system-python":
        ok = euid == 0
        return CheckResult("I19", ok, "running as root" if ok else "euid=%d: --phase system-python must run as root; run it with sudo" % euid, True)
    ok = euid != 0
    return CheckResult("I19", ok, "euid=%d (--phase %s must not run as root)" % (euid, ctx.phase), True)


def check_i20(ctx):
    if ctx.phase == "preflight" and not os.path.isdir(FRAMEWORK_ROOT + "/Versions/3.13"):
        return CheckResult("I20", True, _bp.PENDING_PREFIX + "%s/Versions/3.13 is not installed yet; run --phase system-python next" % FRAMEWORK_ROOT, True)
    rc, out = HOOKS["run"]([framework_py(), "-c", "import sys;print(sys.version.split()[0])"])
    got = out.strip()
    return CheckResult("I20", rc == 0 and got == "3.13.0", "%s reports %r (need 3.13.0)" % (framework_py(), got), True)


CHECKS = {
    "I01": check_i01, "I02": check_i02, "I03": check_i03, "I04": check_i04, "I05": check_i05,
    "I06": check_i06, "I07": check_i07, "I08": check_i08, "I09": check_i09, "I10": check_i10,
    "I11": check_i11, "I12": check_i12, "I13": check_i13, "I14": check_i14, "I15": check_i15,
    "I16": check_i16, "I17": check_i17, "I18": check_i18, "I19": check_i19, "I20": check_i20,
}
PHASE_CHECKS = {
    "preflight": ("I01", "I02", "I03", "I04", "I05", "I06", "I07", "I08", "I09", "I10", "I11", "I12", "I13", "I14", "I15", "I16", "I17", "I18", "I19", "I20"),
    "system-python": ("I01", "I02", "I03", "I04", "I05", "I06", "I07", "I08", "I09", "I10", "I11", "I19"),
    "user": ("I01", "I02", "I03", "I04", "I05", "I06", "I07", "I08", "I09", "I10", "I11", "I12", "I13", "I14", "I15", "I16", "I17", "I18", "I19", "I20"),
    "verify": ("I01", "I05", "I06", "I19", "I20"),
    "accept": ("I01", "I03", "I05", "I06", "I12", "I14", "I17", "I19", "I20"),
}


def run_checks(ctx):
    results = [CHECKS[check_id](ctx) for check_id in PHASE_CHECKS[ctx.phase]]
    for result in results:
        line = _bp.format_result(result)
        print(safe_line(ctx, line, "%s %s (message withheld: it contained secret material)" % (line.split(" ", 1)[0], result.check_id)))
    return results


# ---------------------------------------------------------------------------
# Plan print, --apply gate, per-file install (spec 12.2, 12.4)
# ---------------------------------------------------------------------------
def phase_components(ctx):
    components = list((ctx.manifest or {}).get("components", {}))
    if ctx.phase == "system-python":
        return [c for c in components if c in SYSTEM_COMPONENTS]
    if ctx.phase == "user":
        return [c for c in components if c not in SYSTEM_COMPONENTS]
    return components


def print_plan(ctx):
    for cid in phase_components(ctx):
        copy = same = collisions = 0
        for entry in ctx.entries:
            if entry["c"] != cid:
                continue
            status = ctx.target_status.get(entry["t"], "absent")
            if status == "absent":
                copy += 1
            elif status == "same":
                same += 1
            else:
                collisions += 1
        print(safe_line(ctx, "PLAN %s copy=%d identical=%d collisions=%d" % (cid, copy, same, collisions),
                        "PLAN (component id withheld: it contained secret material) copy=%d identical=%d collisions=%d"
                        % (copy, same, collisions)))
    if ctx.phase == "user":
        print(safe_line(ctx, "PLAN receipts -> %s" % receipts_dir(ctx.package_id()),
                        "PLAN receipts -> (path withheld: it contained secret material)"))


def gated_install(ctx, fatal_failures):
    """preflight / system-python / user: dry-run by default; --apply refused on any fatal check."""
    args = ctx.args
    if not args.apply:
        print_plan(ctx)
        return EXIT_OK if not fatal_failures else EXIT_REFUSED
    if fatal_failures:  # refuse --apply
        print("install_pkg: --apply REFUSED: %d fatal check(s) failed; nothing was written" % len(fatal_failures))
        return EXIT_REFUSED
    try:
        if ctx.phase == "system-python":
            return apply_system_python(ctx)
        if ctx.phase == "user":
            return apply_user(ctx)
    except Exception as exc:
        name = type(exc).__name__
        print(safe_line(ctx, "install_pkg: ERROR during --apply (%s): %s" % (name, exc),
                        "install_pkg: ERROR during --apply (%s): (message withheld: it contained secret material)" % name),
              file=sys.stderr)
        print("install_pkg: files already installed stay in place; a rerun skips them as identical", file=sys.stderr)
        return EXIT_RUNTIME
    return EXIT_OK


def _write_all(fd, data):
    view = memoryview(data)
    offset = 0
    while offset < len(data):
        offset += os.write(fd, view[offset:])


def make_dir(ctx, path):
    """Create path and its missing ancestors, top down; an existing path is never touched.
    A manifest directory is made under a temp name, chmod-ed to its recorded mode plus owner
    rwx (so its children can be installed), then renamed into place: it never appears under
    its final name with any other mode, even if the run is killed (spec 12.4)."""
    missing = []
    while not os.path.lexists(path):
        missing.append(path)
        path = os.path.dirname(path)
    for directory in reversed(missing):
        mode = ctx.dir_modes.get(directory)
        if mode is None:
            os.mkdir(directory)
            continue
        tmp = os.path.dirname(directory) + "/." + os.path.basename(directory) + ".ltxdeploy.tmp"
        if os.path.lexists(tmp):
            os.rmdir(tmp)   # an empty leftover from a killed run
        os.mkdir(tmp, 0o700)
        os.chmod(tmp, mode | 0o700)
        os.rename(tmp, directory)


def install_file(ctx, src, entry):
    target = entry["t"]
    parent = os.path.dirname(target)
    make_dir(ctx, parent)
    tmp = parent + "/." + os.path.basename(target) + ".ltxdeploy.tmp"
    hasher = hashlib.sha256()
    src_fd = os.open(src, os.O_RDONLY)
    try:
        dst_fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            total = 0
            while True:
                chunk = os.read(src_fd, CHUNK_SIZE)
                if not chunk:
                    break
                _write_all(dst_fd, chunk)
                hasher.update(chunk)
                total += len(chunk)
                HOOKS["after_chunk"](src, total)
            os.fsync(dst_fd)
        finally:
            os.close(dst_fd)
    finally:
        os.close(src_fd)
    digest = hasher.hexdigest()
    if digest != entry["h"]:
        os.unlink(tmp)
        raise InstallError("sha256 mismatch for %s" % target)
    os.chmod(tmp, int(entry["m"], 8))
    os.utime(tmp, ns=(entry["mt"], entry["mt"]))
    os.replace(tmp, target)


def install_symlink(ctx, entry):
    target = entry["t"]
    parent = os.path.dirname(target)
    make_dir(ctx, parent)
    tmp = parent + "/." + os.path.basename(target) + ".ltxdeploy.tmp"
    if os.path.lexists(tmp):
        os.unlink(tmp)
    os.symlink(entry["l"], tmp)
    os.replace(tmp, target)


def install_entry(ctx, entry):
    target = entry["t"]
    if ctx.target_status.get(target) == "same":
        return False
    if os.path.lexists(target):
        same, reason = target_matches_entry(target, entry)
        if same:
            return False
        raise InstallError("%s changed after the checks ran (%s)" % (target, reason))
    if entry["k"] == "f":
        install_file(ctx, ctx.package_root + "/" + entry["p"], entry)
    elif entry["k"] == "l":
        install_symlink(ctx, entry)
    else:
        make_dir(ctx, target)
    return True


def chmod_created_dirs(ctx, component):
    for entry in ctx.entries:
        if entry["c"] == component and entry["k"] == "d" and ctx.target_status.get(entry["t"]) == "absent":
            if os.path.isdir(entry["t"]) and not os.path.islink(entry["t"]):
                os.chmod(entry["t"], int(entry["m"], 8))


def install_components(ctx, components):
    # every d entry, not only this phase's: F1's first entry creates F2's Python.framework and Versions
    ctx.dir_modes = dict((e["t"], int(e["m"], 8)) for e in ctx.entries if e["k"] == "d")
    selected = [e for e in ctx.entries if e["c"] in components]
    last = {}
    for index, entry in enumerate(selected):
        last[entry["c"]] = index
    counts = {"files": 0, "symlinks": 0, "bytes": 0}
    for index, entry in enumerate(selected):
        install_entry(ctx, entry)
        if entry["k"] == "f":
            counts["files"] += 1
            counts["bytes"] += entry["b"]
        elif entry["k"] == "l":
            counts["symlinks"] += 1
        if last[entry["c"]] == index:
            chmod_created_dirs(ctx, entry["c"])
    return counts


def write_receipts(ctx):
    for entry in ctx.receipt_entries:
        if ctx.target_status.get(entry["t"]) == "same":
            continue
        install_file(ctx, entry["_src"], entry)


def apply_system_python(ctx):
    install_components(ctx, SYSTEM_COMPONENTS)
    rc, out = HOOKS["run"]([framework_py(), "-s", "-c", "import sys, psutil, pytest, pexpect; print(sys.version.split()[0])"], timeout=300)
    lines = out.splitlines()
    first = lines[0].strip() if lines else ""
    if rc != 0 or first != "3.13.0":
        detail = out[-200:]
        if has_secret(ctx, out):   # the whole output: a secret cut by the 200-character tail is still caught
            detail = "(output withheld: it contained secret material)"
        print("install_pkg: system-python post-check FAILED (rc=%d): %s" % (rc, detail), file=sys.stderr)
        return EXIT_RUNTIME
    print("install_pkg: system-python phase complete")
    return EXIT_OK


def apply_user(ctx):
    counts = install_components(ctx, phase_components(ctx))
    write_receipts(ctx)
    print("install_pkg: user phase complete: %d files, %d symlinks, %d bytes" % (counts["files"], counts["symlinks"], counts["bytes"]))
    return EXIT_OK


def verify_entry(entry):
    target = entry["t"]
    try:
        st = os.lstat(target)
    except OSError:
        return "missing"
    if entry["k"] == "f":
        if not stat.S_ISREG(st.st_mode):
            return "not a regular file"
        try:
            actual = _bp.sha256_file(target)
        except OSError:
            return "unreadable"
        if actual != entry["h"]:
            return "content differs"
        if stat.S_IMODE(st.st_mode) != int(entry["m"], 8):
            return "mode differs"
        return None
    if entry["k"] == "l":
        if not stat.S_ISLNK(st.st_mode):
            return "not a symlink"
        if os.readlink(target) != entry["l"]:
            return "symlink target differs"
        return None
    if not stat.S_ISDIR(st.st_mode):
        return "not a directory"
    if stat.S_IMODE(st.st_mode) != int(entry["m"], 8):
        return "mode differs"
    return None


def phase_verify(ctx, fatal_failures):
    if fatal_failures:
        print("install_pkg: verify REFUSED: %d fatal check(s) failed" % len(fatal_failures))
        return EXIT_REFUSED
    counts = {"f": 0, "l": 0, "d": 0}
    mismatches = 0
    for entry in ctx.entries:
        counts[entry["k"]] += 1
        reason = verify_entry(entry)
        if reason:
            mismatches += 1
            print(safe_line(ctx, "MISMATCH %s: %s" % (reason, entry["t"]),
                            "MISMATCH %s: (path withheld: it contained secret material)" % reason))
    if mismatches:
        print("install_pkg: verify FAILED: %d mismatch(es)" % mismatches)
        return EXIT_RUNTIME
    print("VERIFY OK %d files, %d symlinks, %d dirs" % (counts["f"], counts["l"], counts["d"]))
    return EXIT_OK


# ---------------------------------------------------------------------------
# accept (spec 13)
# ---------------------------------------------------------------------------
ACCEPT_NARR = ("An old fisherman in a flat cap and a waxed coat stands at a lighthouse railing as a storm "
               "rolls in over the sea. He grips the rail and watches the waves, then turns and walks toward "
               "the lighthouse door.")
GEOMETRIES = (
    ("portrait", "generated/hw_gate_seeds/portrait.png", 320, 576, 320, 576),
    ("wide", "generated/hw_gate_seeds/wide3x1.png", 960, 320, 960, 320),
    ("square", "generated/hw_gate_seeds/square.png", 512, 512, 512, 512),
    ("noseed", None, 704, 448, 1408, 896),
)
SCOPED_HF_VARS = ("Z_IMAGE_HF_HOME", "LTX2_MLX_HF_HOME", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE")
REFUSAL_ENV_VARS = ("HF_HOME",) + SCOPED_HF_VARS
STORY_SERVER_USAGE = "usage: story-server [vision|text|status|stop]"
SWAP_REFUSE_MB = 3072.00
LTX_MOVIE_TIMEOUT = 7200
STORY_SERVER_UP_TIMEOUT = 1800
POLL_SECONDS = 15

# The plan's Task 13 Step 3 sampler (2026-09-24 redesign plan), with one change:
# phase4_peak_used_gib = memsize/2**30 - min(avail) instead of the hard-coded 48.0.
SAMPLER_SRC = r'''
import glob, json, os, subprocess, sys, time, psutil
out, pid, memsize = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
story_dir = os.path.dirname(out)
samples = []
while psutil.pid_exists(pid):
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    lvl = subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
                         capture_output=True, text=True).stdout.strip()
    samples.append({"t": time.time(), "avail_gib": vm.available / 2**30,
                    "swap_used_gib": sw.used / 2**30, "pressure": int(lvl or 0)})
    time.sleep(2)
runs = glob.glob(os.path.join(story_dir, "runs", "*"))
t4 = max(os.stat(r).st_birthtime for r in runs) if runs else samples[0]["t"]
p4 = [s for s in samples if s["t"] >= t4] or samples
json.dump({"phase4_start": t4,
           "phase4_min_avail_gib": min(s["avail_gib"] for s in p4),
           "phase4_peak_used_gib": memsize / 2**30 - min(s["avail_gib"] for s in p4),
           "phase4_max_pressure": max(s["pressure"] for s in p4),
           "phase4_swap_delta_gib": max(s["swap_used_gib"] for s in p4) - p4[0]["swap_used_gib"],
           "samples": samples}, open(out, "w"), indent=2)
'''


def load_json(path):
    try:
        with open(path, "rb") as fh:
            return json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError):
        return {}


def output_tail(ctx, out):
    """The last 200 characters of out, or a fixed notice if the WHOLE of out holds secret material:
    a secret cut by the 200-character tail is still caught (as in apply_system_python)."""
    return "(output withheld: it contained secret material)" if has_secret(ctx, out) else out[-200:]


def accept_a1_metadata(ctx):
    problems = []
    for entry in ctx.entries:
        target = entry["t"]
        try:
            st = os.lstat(target)
        except OSError:
            problems.append("missing: %s" % target)
            continue
        if entry["k"] == "f":
            if not stat.S_ISREG(st.st_mode):
                problems.append("not a regular file: %s" % target)
            elif st.st_size != entry["b"]:
                problems.append("size differs: %s" % target)
            elif st.st_mtime_ns != entry["mt"]:
                problems.append("mtime differs: %s" % target)
        elif entry["k"] == "l":
            if not stat.S_ISLNK(st.st_mode) or os.readlink(target) != entry["l"]:
                problems.append("symlink target differs: %s" % target)
        elif not stat.S_ISDIR(st.st_mode):
            problems.append("not a directory: %s" % target)
    return {"ok": not problems, "problems": problems[:200], "problem_count": len(problems), "entries": len(ctx.entries)}


def accept_a2_probes(ctx):
    problems = []
    rc, out = HOOKS["run"]([framework_py(), "-c", "import torch, diffusers, transformers, PIL, numpy, safetensors, psutil, pytest, pexpect"], timeout=300)
    if rc != 0:
        problems.append("framework + user-site import probe rc=%d: %s" % (rc, output_tail(ctx, out)))
    want = load_json(ctx.package_root + "/manifests/source-host.json").get("vllm_version")
    rc, out = HOOKS["run"]([home() + "/.venv-vllm-metal/bin/python", "-c", "import vllm, vllm_metal, mlx_vlm; print(vllm.__version__)"], timeout=300)
    got = _bp.last_line(out).strip()   # C1: the version is the last line
    if rc != 0 or got != want:
        problems.append("vLLM probe rc=%d version=%r, source-host vllm_version=%r" % (rc, got, want))
    rc, out = HOOKS["run"]([home() + "/ltx-2-mlx/.venv/bin/ltx-2-mlx", "--help"], timeout=300)
    if rc != 0:
        problems.append("ltx-2-mlx --help rc=%d: %s" % (rc, output_tail(ctx, out)))
    return {"ok": not problems, "problems": problems}


def accept_a3_gates(ctx):
    baseline = load_json(ctx.package_root + "/manifests/acceptance-baseline.json")
    gates, extras = _bp.run_offline_gates(HOOKS["run"], framework_py(), workspace())
    base_gates = dict((g["id"], g) for g in baseline.get("gates", []))
    base_extras = dict((x["id"], x) for x in baseline.get("extras", []))
    problems = []
    for gate in gates:
        base = base_gates.get(gate["id"], {})
        if gate["rc"] != base.get("rc") or gate["last_line"] != base.get("last_line"):
            problems.append("%s: rc=%r last_line=%r; baseline rc=%r last_line=%r"
                            % (gate["id"], gate["rc"], gate["last_line"], base.get("rc"), base.get("last_line")))
    for extra in extras:
        if extra["id"] == "X1" and extra["rc"] != base_extras.get("X1", {}).get("rc"):
            problems.append("X1: rc=%r; baseline rc=%r" % (extra["rc"], base_extras.get("X1", {}).get("rc")))
        if extra["id"] == "X2" and (extra["rc"] != 0 or extra["brace_lines"] != 0):
            problems.append("X2: rc=%r brace_lines=%r" % (extra["rc"], extra["brace_lines"]))
    return {"ok": not problems, "problems": problems, "gates": gates, "extras": extras}


def accept_a4_story_server(ctx):
    rc, out = HOOKS["run"]([workspace() + "/bin/story-server"], timeout=120)
    ok = rc == 2 and STORY_SERVER_USAGE in out
    return {"ok": ok, "problems": [] if ok else ["story-server with no arguments: rc=%r output=%r" % (rc, output_tail(ctx, out))]}


def gpu_refusals(ctx):
    refusals = []
    for path in sorted(glob.glob(os.path.join(VOLUMES_ROOT, "*", "hf_home"))):
        if os.path.exists(path):
            refusals.append("r1: %s exists; eject the drive, so that the run can only use the shipped weights" % path)
    for name in REFUSAL_ENV_VARS:
        value = os.environ.get(name, "")
        if value.startswith("/Volumes/"):
            refusals.append("r2: %s=%s points at an external volume" % (name, value))
    rc, out = HOOKS["run"](["/bin/zsh", "-c", 'printf "%s" "$HF_HOME"'])
    if out.startswith("/Volumes/"):
        refusals.append("r2: zsh HF_HOME=%s points at an external volume" % out)
    rc, out = HOOKS["run"](["/usr/bin/pgrep", "-fl", "ltx-2-mlx|z_image|mlx_lm|vllm"])
    if out.strip():
        refusals.append("r3: another GPU job or a live story server is running: %s" % " | ".join(out.strip().splitlines()[:5]))
    if not HOOKS["port_free"](STORY_PORT):
        refusals.append("r4: port %d is in use" % STORY_PORT)
    rc, out = HOOKS["run"](["/usr/sbin/sysctl", "-n", "vm.swapusage"])
    found = re.search(r"used = ([0-9]+(?:\.[0-9]+)?)M", out)
    if rc != 0 or not found:
        refusals.append("r5: cannot read swap usage (%r)" % out.strip())
    elif float(found.group(1)) >= SWAP_REFUSE_MB:
        refusals.append("r5: swap used = %sM >= 3072.00M; wait: swap drains at about 32 MB/min and purge does not help" % found.group(1))
    return refusals


def wait_for_story_server():
    url = "http://127.0.0.1:%d/v1/models" % STORY_PORT
    waited = 0
    while True:
        if HOOKS["http_ok"](url):
            return True
        if waited >= STORY_SERVER_UP_TIMEOUT:
            return False
        HOOKS["sleep"](POLL_SECONDS)
        waited += POLL_SECONDS


def accept_env():
    env = dict(os.environ)
    env["HF_HOME"] = home() + "/hf_home"
    env["HF_HUB_OFFLINE"] = "1"
    for name in SCOPED_HF_VARS + ("HF_TOKEN",):
        env.pop(name, None)
    return env


def ffprobe_stream(ctx, path, select, entries, count=False):
    argv = ([ctx.ffprobe or "ffprobe", "-v", "error", "-select_streams", select] + (["-count_frames"] if count else [])
            + ["-show_entries", "stream=" + entries, "-of", "json", path])
    rc, out = HOOKS["run"](argv, timeout=300)
    if rc != 0:
        return {}
    try:
        streams = json.loads(out or "{}").get("streams") or [{}]
    except ValueError:
        return {}
    return streams[0]


def framemd5(ctx, path, vf):
    # -map 0:v:0 is mandatory: without it the AAC track adds rows and c4 always fails (fixed 2026-09-24).
    argv = [ctx.ffmpeg or "ffmpeg", "-v", "error", "-nostdin", "-i", path, "-map", "0:v:0", "-vf", vf,
            "-fps_mode", "passthrough", "-f", "framemd5", "-"]
    rc, out = HOOKS["run"](argv, timeout=300)
    rows = [line for line in out.splitlines() if line.strip() and not line.startswith("#")]
    return rows[0].split(",")[-1].strip() if rc == 0 and len(rows) == 1 else None


def evaluate_run(ctx, story_dir, rc, W, H, SW, SH):
    result = {}
    summaries = glob.glob(os.path.join(story_dir, "runs", "*", "story_summary.json"))
    summary = load_json(max(summaries, key=os.path.getmtime)) if summaries else {}
    result["c1"] = rc == 0 and summary.get("completed_units") == summary.get("requested_units") == 2
    movie = story_dir + "/movie.mp4"
    video = ffprobe_stream(ctx, movie, "v:0", "width,height,codec_name,nb_read_frames", count=True)
    audio = ffprobe_stream(ctx, movie, "a:0", "codec_name")
    result["c2"] = ((video.get("width"), video.get("height")) == (W, H) and str(video.get("nb_read_frames")) == "290"
                    and video.get("codec_name") == "h264" and audio.get("codec_name") == "aac")
    still = ffprobe_stream(ctx, story_dir + "/images/panel_01.png", "v:0", "width,height")
    result["c3"] = (still.get("width"), still.get("height")) == (SW, SH)
    seed_md5 = framemd5(ctx, story_dir + "/clips/panel_02.chainseed.png", "format=rgb24")
    last_md5 = framemd5(ctx, story_dir + "/clips/panel_01.mp4", "select=eq(n\\,144),format=rgb24")
    result["c4"] = seed_md5 is not None and seed_md5 == last_md5
    gate = load_json(story_dir + "/hw_gate.json")
    result["c5"] = bool(gate) and gate.get("phase4_max_pressure", 99) < 4 and gate.get("phase4_swap_delta_gib", 99) <= 1.0
    try:
        with open(story_dir + "/console.txt", "r", encoding="utf-8", errors="replace") as fh:
            console = fh.read()
    except OSError:
        console = ""
    found = re.search(r"residual pad (\d+) px", console)
    result["record"] = {"pad_px": int(found.group(1)) if found else 0, "movie": video, "still": still,
                        "peak_used_gib": round(gate.get("phase4_peak_used_gib", -1.0), 2),
                        "max_pressure": gate.get("phase4_max_pressure"),
                        "swap_delta_gib": round(gate.get("phase4_swap_delta_gib", -1.0), 3),
                        "unit_seconds": [u.get("seconds") for u in summary.get("units", [])]}
    return result


def gpu_run(ctx, label, seed, W, H, SW, SH):
    ws = workspace()
    result = {"label": label, "pass": False}
    rc, out = HOOKS["run"]([ws + "/bin/story-server", "vision"], timeout=120)
    result["story_server_vision_rc"] = rc
    if rc != 0:
        result["error"] = "story-server vision rc=%d: %s" % (rc, output_tail(ctx, out))
        return result
    if not wait_for_story_server():
        result["error"] = "story server did not come up"
        return result
    stamp = time.strftime("%Y%m%d%H%M%S", HOOKS["now_utc"]())
    sid = "deploy-accept-%s-%s" % (label, stamp)
    story_dir = ws + "/generated/stories/" + sid
    result["story_id"] = sid
    if os.path.lexists(story_dir):
        result["error"] = "story dir %s already exists; a story id is never reused" % story_dir
        return result
    os.makedirs(story_dir)
    argv = ([framework_py(), ws + "/bin/ltx-movie", ACCEPT_NARR, "--story-id", sid, "--panels", "2"]
            + (["--seed-image", ws + "/" + seed] if seed else [])
            + ["--model", ltx25_model_path(), "--no-review", "--story-server-stop-after-story"])
    started = time.time()
    proc = HOOKS["spawn"](argv, cwd=ws, env=accept_env(), stdout_path=story_dir + "/console.txt", new_session=True)
    sampler = HOOKS["spawn"]([framework_py(), "-c", SAMPLER_SRC, story_dir + "/hw_gate.json", str(proc.pid), str(ctx.memsize)],
                             cwd=ws, env=None, stdout_path=story_dir + "/sampler_console.txt", new_session=False)
    try:
        movie_rc = proc.wait(timeout=LTX_MOVIE_TIMEOUT)
    except subprocess.TimeoutExpired:
        HOOKS["killpg"](proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            HOOKS["killpg"](proc.pid, signal.SIGKILL)
            proc.wait()
        movie_rc = "timeout"
    with open(story_dir + "/gate_rc.txt", "w") as fh:
        fh.write("%s\n" % movie_rc)
    try:
        sampler.wait(timeout=60)
    except subprocess.TimeoutExpired:
        sampler.kill()
        sampler.wait()
    stop_rc, _ = HOOKS["run"]([ws + "/bin/story-server", "stop"], timeout=120)
    result["story_server_stop_rc"] = stop_rc
    result["rc"] = movie_rc
    result["seconds"] = round(time.time() - started, 1)
    result.update(evaluate_run(ctx, story_dir, movie_rc, W, H, SW, SH))
    result["pass"] = all(result[c] for c in ("c1", "c2", "c3", "c4", "c5"))
    result["movie"] = story_dir + "/movie.mp4"
    return result


def scrub_record(ctx, value):
    """Recursively withhold any string that holds secret material before the record reaches disk
    (the accept record can embed real subprocess/GPU-run output; see has_secret)."""
    if isinstance(value, str):
        return safe_line(ctx, value, "(value withheld: it contained secret material)")
    if isinstance(value, (list, tuple)):
        return [scrub_record(ctx, item) for item in value]
    if isinstance(value, dict):
        return dict((key, scrub_record(ctx, item)) for key, item in value.items())
    return value


def write_accept_record(ctx, record, stamp, verdict):
    record["verdict"] = verdict
    record["finished_at"] = iso_now()
    directory = receipts_dir(ctx.package_id())
    os.makedirs(directory, exist_ok=True)
    path = directory + "/accept-%s.json" % stamp
    text = json.dumps(scrub_record(ctx, record), indent=2) + "\n"
    if has_secret(ctx, text):   # scrub_record keeps dict keys as they are: keep only the verdict
        text = json.dumps({"schema_version": 1, "verdict": verdict, "finished_at": record["finished_at"],
                           "withheld": "the record contained secret material"}, indent=2) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    print(safe_line(ctx, "install_pkg: accept record written to %s" % path,
                    "install_pkg: accept record written (path withheld: it contained secret material)"))
    return path


def report_step(ctx, step_id, result):
    print("%s %s" % (step_id, "PASS" if result["ok"] else "FAIL"))
    for problem in result["problems"]:
        print(safe_line(ctx, "%s   %s" % (step_id, problem),
                        "%s   (problem withheld: it contained secret material)" % step_id))


def phase_accept(ctx, fatal_failures):
    args = ctx.args
    stamp = time.strftime("%Y%m%d%H%M%S", HOOKS["now_utc"]())
    geometries = GEOMETRIES if args.gpu_all else (GEOMETRIES[:1] if args.gpu else ())
    record = {"schema_version": 1, "package_id": ctx.package_id(), "started_at": iso_now(),
              "gpu": "all" if args.gpu_all else ("portrait" if args.gpu else "none"), "steps": {}}
    steps = record["steps"]
    steps["A0"] = {"ok": not fatal_failures, "failed": [r.check_id for r in fatal_failures]}
    if fatal_failures:
        write_accept_record(ctx, record, stamp, "REFUSED")
        print("ACCEPT REFUSED (A0: %s)" % ", ".join(r.check_id for r in fatal_failures))
        return EXIT_REFUSED
    if geometries:
        refusals = gpu_refusals(ctx)
        steps["refusals"] = refusals
        if refusals:
            for line in refusals:
                print(safe_line(ctx, "REFUSE " + line,
                                "REFUSE %s: (message withheld: it contained secret material)" % line.split(":", 1)[0]))
            write_accept_record(ctx, record, stamp, "GPU-REFUSED")
            print("ACCEPT REFUSED (GPU precondition; nothing was started)")
            return EXIT_GPU_REFUSED
    a1 = accept_a1_metadata(ctx)
    steps["A1"] = a1
    report_step(ctx, "A1", a1)
    ok = a1["ok"]
    if ok:
        for step_id, func in (("A2", accept_a2_probes), ("A3", accept_a3_gates), ("A4", accept_a4_story_server)):
            result = func(ctx)
            steps[step_id] = result
            report_step(ctx, step_id, result)
            ok = ok and result["ok"]
    else:
        print("A2-A5 skipped: A1 found installed files that do not match the manifest")
    runs = []
    if ok and geometries:
        runs = [gpu_run(ctx, *geometry) for geometry in geometries]
        steps["A5"] = runs
        for run in runs:
            failed = [c for c in ("c1", "c2", "c3", "c4", "c5") if not run.get(c)]
            line = "A5 %s %s%s" % (run["label"], "PASS" if run["pass"] else "FAIL",
                                   "" if run["pass"] else " (%s)" % (run.get("error") or "failed: " + ", ".join(failed)))
            print(safe_line(ctx, line, "A5 %s %s (detail withheld: it contained secret material)"
                            % (run["label"], "PASS" if run["pass"] else "FAIL")))
        ok = all(run["pass"] for run in runs)
    write_accept_record(ctx, record, stamp, "PASS" if ok else "FAIL")
    if not ok:
        print("ACCEPT FAIL")
        return EXIT_RUNTIME
    for run in runs:
        print(safe_line(ctx, "movie: %s (pad_px=%d)" % (run["movie"], run["record"]["pad_px"]),
                        "movie: (path withheld: it contained secret material)"))
    if runs:
        print("Eyeball each movie.mp4 now (manual sign-off, not part of the exit code): the subject is not cropped; "
              "there is no black bar beyond pad_px; panel 2 continues panel 1.")
    print("ACCEPT PASS")
    return EXIT_OK


# ---- CLI entry point ----


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="install_pkg.py", description="Install the ltx-chain deployment package.")
    parser.add_argument("--phase", required=True, choices=PHASES)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--package-root", default=None)
    gpu = parser.add_mutually_exclusive_group()
    gpu.add_argument("--gpu", action="store_true")
    gpu.add_argument("--gpu-all", action="store_true")
    args = parser.parse_args(argv)
    if args.apply and args.phase not in ("system-python", "user"):
        parser.error("--apply is valid only with --phase system-python or --phase user")
    if (args.gpu or args.gpu_all) and args.phase != "accept":
        parser.error("--gpu/--gpu-all are valid only with --phase accept")
    return args


def main(argv=None):
    args = parse_args(argv)
    ctx = InstallCtx(args)
    results = run_checks(ctx)
    fatal_failures = [r for r in results if r.fatal and not r.ok]
    if args.phase == "verify":
        return phase_verify(ctx, fatal_failures)
    if args.phase == "accept":
        return phase_accept(ctx, fatal_failures)
    return gated_install(ctx, fatal_failures)


if __name__ == "__main__":
    sys.exit(main())
