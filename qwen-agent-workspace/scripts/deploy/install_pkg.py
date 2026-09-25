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
    return gated_install(ctx, fatal_failures)


if __name__ == "__main__":
    sys.exit(main())
