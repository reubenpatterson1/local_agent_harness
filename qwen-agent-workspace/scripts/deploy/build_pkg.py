#!/usr/bin/env python3
"""build_pkg.py -- build the ltx-chain USB deployment package (schema 4).

Spec: docs/superpowers/specs/2026-09-25-ltx-chain-deploy-package-design.md
Plan: docs/superpowers/plans/2026-09-25-ltx-chain-deploy-package.md

Runs on the source host under
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3. Written at the
Python 3.9 language level because install_pkg.py loads this file under Apple's
/usr/bin/python3 (3.9.6) for the shared helpers (R8). Stdlib only. Importing
this module has no side effects: all work happens in main().
"""
import argparse
import collections
import configparser
import fcntl
import getpass
import glob
import hashlib
import json
import os
import platform
import pwd
import re
import shutil
import socket
import stat
import subprocess
import sys
import time
import traceback
import urllib.request

# ---------------------------------------------------------------------------
# Constants (spec 5.3). Read at call time; never captured in default arguments.
# ---------------------------------------------------------------------------
REQUIRED_USER = "reubenpatterson"
REQUIRED_HOME = "/Users/reubenpatterson"
FRAMEWORK_ROOT = "/Library/Frameworks/Python.framework"
USR_LOCAL_BIN = "/usr/local/bin"
VOLUMES_ROOT = "/Volumes"
FALCONSAI_USB_HUB = "/Volumes/Ollama/hf_home/hub"
BREW_BIN = "/opt/homebrew/bin/brew"
BREW_PY312 = "/opt/homebrew/opt/python@3.12/bin/python3.12"
USB_ROOT_DEFAULT = "/Volumes/Ollama"
CHUNK_SIZE = 8 * 1024 * 1024
L2_MAX_BYTES = 4 * 1024 * 1024
SCHEMA_VERSION = 4
MIN_MEMSIZE_BYTES = 51539607552          # 48 GiB
BUILD_HEADROOM_BYTES = 5 * 1024 ** 3
INSTALL_HEADROOM_BYTES = 10 * 1024 ** 3
STORY_PORT = 8177

GIT = "/usr/bin/git"
WS_REPO_PREFIX = "qwen-agent-workspace"
PACKAGE_ID_RE = re.compile(r"^ltx-chain-deploy-[0-9]{8}$")
PENDING_PREFIX = "PENDING: "
ENTRY_KEYS = ("k", "c", "p", "t", "b", "m", "h", "mt", "l", "s")
DEPLOY_SCRIPT_FILES = ("build_pkg.py", "install_pkg.py", "credential_allowlist.json")
HOST_TIMEOUT = 120
FREEZE_TIMEOUT = 300
GATE_TIMEOUT = 900


# ---------------------------------------------------------------------------
# Hooks: every real external probe goes through HOOKS; tests replace entries.
# ---------------------------------------------------------------------------
def _real_run(argv, timeout=120, env=None, cwd=None):
    try:
        proc = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout, env=env, cwd=cwd)
    except subprocess.TimeoutExpired as exc:
        partial = exc.output or b""
        return 124, partial.decode("utf-8", "replace")
    except OSError as exc:
        return 127, "%s: %s" % (argv[0], exc)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def _real_diskutil_personality(path):
    rc, text = _real_run(["/usr/sbin/diskutil", "info", path], timeout=60)
    if rc != 0:
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("File System Personality:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def _real_statvfs_free(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def _real_port_free(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _real_http_ok(url):
    try:
        response = urllib.request.urlopen(url, timeout=10)
        try:
            return response.status == 200
        finally:
            response.close()
    except Exception:
        return False


def _noop_after_chunk(src, nbytes):
    return None


def _noop_after_entry(index):
    return None


HOOKS = {
    "run": _real_run,
    "ismount": os.path.ismount,
    "diskutil_personality": _real_diskutil_personality,
    "statvfs_free": _real_statvfs_free,
    "port_free": _real_port_free,
    "which": shutil.which,
    "geteuid": os.geteuid,
    "getpwnam": pwd.getpwnam,
    "getuser": getpass.getuser,
    "now_utc": time.gmtime,
    "after_chunk": _noop_after_chunk,
    "after_entry": _noop_after_entry,
    "http_ok": _real_http_ok,
    "sleep": time.sleep,
}

CTX_STATE = {"payload_started": False}


class SourceChanged(Exception):
    """A source file differs from its enumeration, or changed while being copied."""


class CredentialLeak(Exception):
    """L3 or L4 found secret material headed into the package."""


class RPreViolation(Exception):
    """A subprocess was requested after the first payload byte (rule R-PRE)."""


CheckResult = collections.namedtuple("CheckResult", "check_id ok message fatal")


def format_result(result):
    if result.ok:
        if result.message.startswith(PENDING_PREFIX):
            return "PENDING %s %s" % (result.check_id, result.message[len(PENDING_PREFIX):])
        return "PASS %s %s" % (result.check_id, result.message)
    if result.fatal:
        return "FAIL %s %s" % (result.check_id, result.message)
    return "WARN %s %s" % (result.check_id, result.message)


def _run(argv, timeout=120, env=None, cwd=None):
    if CTX_STATE["payload_started"]:
        raise RPreViolation(argv[0])
    return HOOKS["run"](argv, timeout=timeout, env=env, cwd=cwd)


# ---------------------------------------------------------------------------
# Paths computed at call time
# ---------------------------------------------------------------------------
def home():
    return os.path.expanduser("~")


def workspace():
    return home() + "/local_model_harness/qwen-agent-workspace"


def repo_root():
    return home() + "/local_model_harness"


def framework_py():
    return FRAMEWORK_ROOT + "/Versions/3.13/bin/python3"


def ltx25_model_path():
    return home() + "/ltx-2-mlx/models/ltx-2.5-mlx-q8"


def deploy_dir():
    return os.path.dirname(os.path.abspath(__file__))


def iso_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", HOOKS["now_utc"]())


# ---------------------------------------------------------------------------
# Hashing, entry I/O, atomic writes
# ---------------------------------------------------------------------------
def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path, nocache=False):
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY)
    try:
        if nocache and hasattr(fcntl, "F_NOCACHE"):
            try:
                fcntl.fcntl(fd, fcntl.F_NOCACHE, 1)
            except OSError:
                pass
        while True:
            chunk = os.read(fd, CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest()


def mode_str(st):
    return "%04o" % stat.S_IMODE(st.st_mode)


def write_all(fd, data):
    view = memoryview(data)
    offset = 0
    while offset < len(data):
        offset += os.write(fd, view[offset:])


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def entry_line(entry):
    ordered = dict((key, entry[key]) for key in ENTRY_KEYS if key in entry)
    return json.dumps(ordered, separators=(",", ":"), ensure_ascii=False) + "\n"


def read_entries(path):
    with open(path, "rb") as fh:
        text = fh.read().decode("utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def last_line(text):
    stripped = text.rstrip()
    return stripped.splitlines()[-1] if stripped else ""


# ---------------------------------------------------------------------------
# L3 known-secret scanner (spec 8.3, exact)
# ---------------------------------------------------------------------------
class KnownSecretScanner(object):
    def __init__(self, secrets):
        self.secrets = list(secrets)
        self.keep = max(len(s) for s in self.secrets) - 1 if self.secrets else 0
        self.tail = b""

    def feed(self, chunk):
        window = self.tail + chunk
        for s in self.secrets:
            if window.find(s) != -1:
                return True
        self.tail = window[-self.keep:] if self.keep else b""
        return False

    def __repr__(self):
        return "<KnownSecretScanner values=%d>" % len(self.secrets)


def l3_message(name):
    return ("L3: a known secret value was found in %s; the partial payload file was deleted "
            "and no MANIFEST.json was written" % name)


def l3_check_bytes(secrets, data, name):
    if KnownSecretScanner(secrets).feed(data):
        raise CredentialLeak(l3_message(name))


def write_package_file(ctx, rel, data, mode):
    """L3-scan data, write <dir>/.<name>.tmp, fsync, chmod, os.replace, fsync the dir."""
    l3_check_bytes(ctx.secrets, data, rel)
    final = ctx.package_root + "/" + rel
    parent = os.path.dirname(final)
    os.makedirs(parent, exist_ok=True)
    tmp = parent + "/." + os.path.basename(final) + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        write_all(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(tmp, mode)
    os.replace(tmp, final)
    fsync_dir(parent)
    return sha256_bytes(data)


# ---------------------------------------------------------------------------
# Copy engine (spec 11.1)
# ---------------------------------------------------------------------------
def copy_regular_file(src, dst, entry, secrets):
    before = os.lstat(src)
    if not stat.S_ISREG(before.st_mode) or (before.st_size, before.st_mtime_ns) != (entry["b"], entry["mt"]):
        raise SourceChanged("source changed since enumeration: %s" % src)
    before_key = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    scanner = KnownSecretScanner(secrets)
    digest = hashlib.sha256()
    total = 0
    src_fd = os.open(src, os.O_RDONLY)
    try:
        dst_fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    except OSError:
        os.close(src_fd)
        raise
    try:
        while True:
            chunk = os.read(src_fd, CHUNK_SIZE)
            if not chunk:
                break
            if scanner.feed(chunk):
                os.close(dst_fd)
                dst_fd = -1
                os.close(src_fd)
                src_fd = -1
                os.unlink(dst)
                raise CredentialLeak(l3_message(src))
            write_all(dst_fd, chunk)
            digest.update(chunk)
            total += len(chunk)
            HOOKS["after_chunk"](src, total)
        os.fsync(dst_fd)
    finally:
        if dst_fd != -1:
            os.close(dst_fd)
        if src_fd != -1:
            os.close(src_fd)
    after = os.lstat(src)
    after_key = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_key != after_key:
        os.unlink(dst)
        raise SourceChanged("source changed mid-copy: %s" % src)
    os.chmod(dst, int(entry["m"], 8))
    os.utime(dst, ns=(entry["mt"], entry["mt"]))
    if os.lstat(dst).st_size != entry["b"]:
        os.unlink(dst)
        raise SourceChanged("copied size differs from the enumerated size: %s" % src)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Components (spec 7)
# ---------------------------------------------------------------------------
COMPONENT_ORDER = ("A1", "A2", "B1", "B2", "B3", "B4", "B5", "D1", "F1", "F2", "F3", "H0", "H1", "H2", "H3", "H4", "H5")
SLUGS = {
    "A1": "workspace-code", "A2": "hw-gate-seeds", "B1": "ltx2mlx-repo", "B2": "ltx2mlx-venv",
    "B3": "uv-cpython311", "B4": "ltx25-mlx-q8", "B5": "ltx2mlx-hf-cache-dirs", "D1": "vllm-venv",
    "F1": "framework-python", "F2": "framework-symlinks", "F3": "user-site", "H0": "hf-home-dirs",
    "H1": "hf-zimage", "H2": "hf-zimage-te", "H3": "hf-nsfw", "H4": "hf-qwen3vl32b", "H5": "mlx-models-link",
}
PIPELINE_FILES = ("z_image_skill.py", "ltx2_mlx_video_skill.py", "ltx_image_fit.py", "content_safety.py",
                  "bin/ltx-movie", "bin/ltx-story-images", "bin/ltx-story-manifest", "bin/ltx-mlx-render",
                  "bin/story-server", "bin/qwen-agent")
TEST_FILES = ("tests/test_ltx_movie_offline.py", "tests/test_ltx_mlx_render.py", "tests/test_ltx_story_images.py",
              "tests/test_ltx2_mlx_video_skill.py", "tests/test_ltx_image_fit.py",
              "tests/test_ltx_story_manifest_chain.py", "tests/check_ltx2_mlx_no_forbidden_imports.py")
A1_FILES = PIPELINE_FILES + TEST_FILES
A1_DIRS = ("", "bin", "tests")
A2_DIR_REL = "generated/hw_gate_seeds"
A2_FILES = ("portrait.png", "wide3x1.png", "square.png")
L1_NAMES = frozenset(["token", "stored_tokens", ".netrc", ".git-credentials", ".pypirc", ".env", "credentials", "id_rsa", "id_ecdsa", "id_ed25519", "id_dsa"])
PRUNE_DIRS = frozenset(["__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache"])
B1_EXCLUDES = frozenset(["models", "hf_cache", "converted_models", "source_caches", ".venv", ".claude", ".git"])
B4_EXCLUDES = frozenset([".cache"])
F1_EXCLUDES = frozenset(["bin/student-agent-mcp"] + ["lib/python3.13/site-packages/" + name for name in (
    "__editable___fubotv_mcp_common_0_1_0_finder.py", "__editable___student_agent_mcp_1_0_0_finder.py",
    "__editable__.fubotv_mcp_common-0.1.0.pth", "__editable__.student_agent_mcp-1.0.0.pth",
    "fubotv_mcp_common-0.1.0.dist-info", "student_agent_mcp-1.0.0.dist-info")])
F3_EXCLUDES = frozenset("lib/python/site-packages/" + name for name in (
    "__editable___fubotv_mcp_common_0_1_0_finder.py", "__editable__.fubotv_mcp_common-0.1.0.pth",
    "fubotv_mcp_common-0.1.0.dist-info"))
UV_CPYTHON_DIR = "cpython-3.11.13-macos-aarch64-none"
F2_FRAMEWORK_LINKS = ("Headers", "Python", "Resources", "Versions/Current")
F2_BIN_LINKS = ("idle3", "idle3.13", "pip3", "pip3.13", "pydoc3", "pydoc3.13", "python3", "python3-config",
                "python3-intel64", "python3.13", "python3.13-config", "python3.13-intel64", "python")
LTX25_PACK_FILES = frozenset([
    ".gitattributes", "LICENSE", "README.md", "audio_vae.safetensors", "chat_template.jinja",
    "connector.safetensors", "duration_head.safetensors", "embedded_config.json", "generation_config.json",
    "ltx-2.5-22b-distilled-lora-450-bf16.safetensors", "processor_config.json", "quantize_config.json",
    "spatial_upscaler_x2_v1_0.safetensors", "spatial_upscaler_x2_v1_0_config.json", "split_model.json",
    "temporal_upscaler_x2_v1_0.safetensors", "temporal_upscaler_x2_v1_0_config.json",
    "text_encoder.safetensors", "text_encoder_config.json", "tokenizer.json", "tokenizer_config.json",
    "transformer-dev.safetensors", "transformer-distilled.safetensors", "vae_decoder_av.safetensors",
    "vae_decoder_conv.safetensors", "vae_encoder_av.safetensors", "vae_encoder_conv.safetensors",
    "vocoder.safetensors"])
HF_PINS = {
    "H1": ("models--Tongyi-MAI--Z-Image-Turbo", "f332072aa78be7aecdf3ee76d5c247082da564a6"),
    "H2": ("models--BennyDaBall--Qwen3-4b-Z-Image-Turbo-AbliteratedV1", "ce497d288a7ddfd5d0f337c7139349d5d0236bfa"),
    "H3": ("models--Falconsai--nsfw_image_detection", "96cb0d0342c7afb80cab76ecc58b265fa44da256"),
    "H4": ("models--divinetribe--Huihui-Qwen3-VL-32B-Instruct-abliterated-4bit-mlx", "5428d6aaca0103a1e32f47261a20fecaa47700ec"),
}


def default_package_id():
    return "ltx-chain-deploy-" + time.strftime("%Y%m%d", time.localtime())


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="build_pkg.py", description="Build the ltx-chain USB deployment package.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="the default: run every check, write nothing")
    mode.add_argument("--apply", action="store_true", help="build the package")
    mode.add_argument("--verify-only", action="store_true", help="re-verify a finished package; writes nothing")
    mode.add_argument("--credential-report", action="store_true", help="enumeration + L1 + L2 report; writes nothing")
    parser.add_argument("--resume", action="store_true", help="with --apply: continue an interrupted build")
    parser.add_argument("--usb-root", default=None, help="default: %s" % USB_ROOT_DEFAULT)
    parser.add_argument("--package-id", default=None, help="default: ltx-chain-deploy-<local YYYYMMDD>")
    args = parser.parse_args(argv)
    if args.resume and not args.apply:
        parser.error("--resume requires --apply")
    if args.package_id is not None and not PACKAGE_ID_RE.match(args.package_id):
        parser.error("--package-id must match ^ltx-chain-deploy-[0-9]{8}$")
    return args


class BuildCtx(object):
    """Everything one invocation knows. Never printed: it holds the L3 secret values."""

    def __init__(self, args):
        self.args = args
        self.usb_root = os.path.abspath(args.usb_root if args.usb_root else USB_ROOT_DEFAULT)
        self.package_id = args.package_id if args.package_id else default_package_id()
        self.package_root = os.path.join(self.usb_root, self.package_id)
        self.apply = bool(args.apply)
        self.resume = bool(args.resume)
        self.started_at = ""
        self.secrets = []
        self.l3_sources = []
        self.l3_errors = []
        self.entries = []
        self.comp_stats = {}
        self.enum_errors = []
        self.l1_hits = []
        self.falconsai_hub = None
        self.allow = set()
        self.allow_entries = []
        self.allow_error = None
        self.l2_hits = []
        self.l2_new = []
        self.l2_allowed = []
        self.l2_errors = []
        self.host = {}
        self.host_failures = []
        self.freezes = {}
        self.git_record = {}
        self.git_problems = []
        self.baseline = None
        self.script_bytes = {}
        self.root_files = collections.OrderedDict()
        self.resume_prefix_len = 0
        self.resume_keep_bytes = 0
        self.resume_rename = False
        self.resume_error = None
        self.remaining_bytes = 0
        self.required_bytes = 0
        self.free_bytes = 0
        self.partial_fh = None
        self.entries_sha256 = ""

    def __repr__(self):
        return "<BuildCtx %s>" % self.package_id


def payload_prefix(cid):
    return "payload/%s-%s" % (cid, SLUGS[cid])


def b3_source():
    return home() + "/.local/share/uv/python/" + UV_CPYTHON_DIR


def l1_check(ctx, name, path):
    if name in L1_NAMES:
        ctx.l1_hits.append(path)


def _lstat_or_error(ctx, cid, path):
    try:
        return os.lstat(path)
    except OSError as exc:
        ctx.enum_errors.append("%s: cannot stat %s: %s" % (cid, path, exc))
        return None


def walk_tree(ctx, cid, src_root, dst_root, excludes):
    entries = []
    try:
        st = os.lstat(src_root)
    except OSError:
        ctx.enum_errors.append("%s: source root %s is missing" % (cid, src_root))
        return entries
    if not stat.S_ISDIR(st.st_mode):
        ctx.enum_errors.append("%s: source root %s is not a directory" % (cid, src_root))
        return entries
    prefix = payload_prefix(cid)
    entries.append({"k": "d", "c": cid, "p": prefix, "t": dst_root, "m": mode_str(st), "_src": src_root, "_rel": ""})
    _walk_dir(ctx, cid, src_root, dst_root, prefix, "", excludes, entries)
    return entries


def _walk_dir(ctx, cid, src_root, dst_root, prefix, rel_dir, excludes, entries):
    abs_dir = src_root + "/" + rel_dir if rel_dir else src_root
    try:
        names = sorted(os.listdir(abs_dir))
    except OSError as exc:
        ctx.enum_errors.append("%s: cannot list %s: %s" % (cid, abs_dir, exc))
        return
    for name in names:
        if name == ".DS_Store":
            continue
        rel = rel_dir + "/" + name if rel_dir else name
        if rel in excludes:
            continue
        path = src_root + "/" + rel
        st = _lstat_or_error(ctx, cid, path)
        if st is None:
            continue
        base = {"c": cid, "p": prefix + "/" + rel, "t": dst_root + "/" + rel, "_src": path, "_rel": rel}
        if stat.S_ISDIR(st.st_mode):
            if name in PRUNE_DIRS:
                continue
            entries.append(dict(base, k="d", m=mode_str(st)))
            _walk_dir(ctx, cid, src_root, dst_root, prefix, rel, excludes, entries)
        elif stat.S_ISLNK(st.st_mode):
            entries.append(dict(base, k="l", l=os.readlink(path)))
            l1_check(ctx, name, path)
        elif stat.S_ISREG(st.st_mode):
            if not os.access(path, os.R_OK):
                ctx.enum_errors.append("%s: unreadable file %s" % (cid, path))
                continue
            entries.append(dict(base, k="f", b=st.st_size, m=mode_str(st), mt=st.st_mtime_ns))
            l1_check(ctx, name, path)
        else:
            ctx.enum_errors.append("%s: special file (not a regular file, directory or symlink) %s" % (cid, path))


def _file_entry(ctx, cid, path, p, rel):
    st = _lstat_or_error(ctx, cid, path)
    if st is None:
        return None
    if not stat.S_ISREG(st.st_mode):
        ctx.enum_errors.append("%s: %s is not a regular file" % (cid, path))
        return None
    if not os.access(path, os.R_OK):
        ctx.enum_errors.append("%s: unreadable file %s" % (cid, path))
        return None
    l1_check(ctx, os.path.basename(path), path)
    return {"k": "f", "c": cid, "p": p, "t": path, "b": st.st_size, "m": mode_str(st),
            "mt": st.st_mtime_ns, "_src": path, "_rel": rel}


def _dir_entry(ctx, cid, path, p, rel):
    st = _lstat_or_error(ctx, cid, path)
    if st is None:
        return None
    if not stat.S_ISDIR(st.st_mode):
        ctx.enum_errors.append("%s: %s is not a directory" % (cid, path))
        return None
    return {"k": "d", "c": cid, "p": p, "t": path, "m": mode_str(st), "_src": path, "_rel": rel}


def enum_a1(ctx):
    ws = workspace()
    prefix = payload_prefix("A1")
    entries = []
    for rel in A1_DIRS:
        entry = _dir_entry(ctx, "A1", ws + "/" + rel if rel else ws, prefix + "/" + rel if rel else prefix, rel)
        if entry is not None:
            entries.append(entry)
    for rel in A1_FILES:
        entry = _file_entry(ctx, "A1", ws + "/" + rel, prefix + "/" + rel, rel)
        if entry is not None:
            entries.append(entry)
    return entries


def enum_a2(ctx):
    base = workspace() + "/" + A2_DIR_REL
    prefix = payload_prefix("A2")
    entries = []
    entry = _dir_entry(ctx, "A2", base, prefix, "")
    if entry is not None:
        entries.append(entry)
    for name in A2_FILES:
        entry = _file_entry(ctx, "A2", base + "/" + name, prefix + "/" + name, name)
        if entry is not None:
            entries.append(entry)
    return entries


def enum_f2(ctx):
    entries = []
    for path in (FRAMEWORK_ROOT, FRAMEWORK_ROOT + "/Versions", USR_LOCAL_BIN):
        st = _lstat_or_error(ctx, "F2", path)
        if st is None:
            continue
        if not stat.S_ISDIR(st.st_mode):
            ctx.enum_errors.append("F2: %s is not a directory" % path)
            continue
        entries.append({"k": "d", "c": "F2", "t": path, "m": mode_str(st), "_src": path})
    links = [FRAMEWORK_ROOT + "/" + n for n in F2_FRAMEWORK_LINKS] + [USR_LOCAL_BIN + "/" + n for n in F2_BIN_LINKS]
    for path in links:
        st = _lstat_or_error(ctx, "F2", path)
        if st is None:
            continue
        if not stat.S_ISLNK(st.st_mode):
            ctx.enum_errors.append("F2: %s is not a symlink" % path)
            continue
        l1_check(ctx, os.path.basename(path), path)
        entries.append({"k": "l", "c": "F2", "t": path, "l": os.readlink(path), "_src": path})
    return entries


def synthetic_dir(cid, target):
    return {"k": "d", "c": cid, "t": target, "m": "0755", "s": True}


def h5_link_value():
    repo, pin = HF_PINS["H4"]
    return home() + "/hf_home/hub/" + repo + "/snapshots/" + pin


def select_falconsai_hub():
    repo = HF_PINS["H3"][0]
    for hub in (home() + "/hf_home/hub", FALCONSAI_USB_HUB):
        if os.path.isdir(hub + "/" + repo):
            return hub
    return None


def sort_component(entries):
    with_p = sorted([e for e in entries if "p" in e], key=lambda e: e["p"])
    without_p = sorted([e for e in entries if "p" not in e], key=lambda e: e["t"])
    return with_p + without_p


def component_stats(entries):
    stats = collections.OrderedDict()
    for cid in COMPONENT_ORDER:
        stats[cid] = {"slug": SLUGS[cid], "files": 0, "symlinks": 0, "dirs": 0, "bytes": 0}
    for entry in entries:
        row = stats[entry["c"]]
        if entry["k"] == "f":
            row["files"] += 1
            row["bytes"] += entry["b"]
        elif entry["k"] == "l":
            row["symlinks"] += 1
        else:
            row["dirs"] += 1
    return stats


def stats_totals(stats):
    totals = {"files": 0, "symlinks": 0, "dirs": 0, "bytes": 0}
    for row in stats.values():
        for key in totals:
            totals[key] += row[key]
    return totals


def enumerate_components(ctx):
    H = home()
    hub = H + "/hf_home/hub"
    ctx.falconsai_hub = select_falconsai_hub()
    parts = {}
    parts["A1"] = enum_a1(ctx)
    parts["A2"] = enum_a2(ctx)
    parts["B1"] = walk_tree(ctx, "B1", H + "/ltx-2-mlx", H + "/ltx-2-mlx", B1_EXCLUDES)
    parts["B2"] = walk_tree(ctx, "B2", H + "/ltx-2-mlx/.venv", H + "/ltx-2-mlx/.venv", frozenset())
    parts["B3"] = walk_tree(ctx, "B3", b3_source(), b3_source(), frozenset())
    parts["B4"] = walk_tree(ctx, "B4", ltx25_model_path(), ltx25_model_path(), B4_EXCLUDES)
    parts["B5"] = [synthetic_dir("B5", H + "/ltx-2-mlx/hf_cache"), synthetic_dir("B5", H + "/ltx-2-mlx/hf_cache/hub")]
    parts["D1"] = walk_tree(ctx, "D1", H + "/.venv-vllm-metal", H + "/.venv-vllm-metal", frozenset())
    parts["F1"] = walk_tree(ctx, "F1", FRAMEWORK_ROOT + "/Versions/3.13", FRAMEWORK_ROOT + "/Versions/3.13", F1_EXCLUDES)
    parts["F2"] = enum_f2(ctx)
    parts["F3"] = walk_tree(ctx, "F3", H + "/Library/Python/3.13", H + "/Library/Python/3.13", F3_EXCLUDES)
    parts["H0"] = [synthetic_dir("H0", H + "/hf_home"), synthetic_dir("H0", hub)]
    for cid in ("H1", "H2", "H3", "H4"):
        repo = HF_PINS[cid][0]
        if cid == "H3":
            if ctx.falconsai_hub is None:
                ctx.enum_errors.append("H3: %s not found under %s or %s" % (repo, hub, FALCONSAI_USB_HUB))
                parts[cid] = []
                continue
            source_hub = ctx.falconsai_hub
        else:
            source_hub = hub
        parts[cid] = walk_tree(ctx, cid, source_hub + "/" + repo, hub + "/" + repo, frozenset())
    parts["H5"] = [synthetic_dir("H5", H + "/mlx_models"),
                   {"k": "l", "c": "H5", "t": H + "/mlx_models/qwen3-vl", "l": h5_link_value(), "s": True}]
    ctx.entries = []
    for cid in COMPONENT_ORDER:
        ctx.entries.extend(sort_component(parts[cid]))
    ctx.comp_stats = component_stats(ctx.entries)


# ---------------------------------------------------------------------------
# Employer-package leak guard (defense in depth: the F1_EXCLUDES/F3_EXCLUDES
# above are exact, version-pinned path strings; this catches drift if either
# employer package gets reinstalled at a different version before a build)
# ---------------------------------------------------------------------------
EMPLOYER_PACKAGE_RE = re.compile(r"(?i)fubotv|student[_-]agent")


def check_no_employer_packages(ctx):
    hits = sorted(set(e["t"] for e in ctx.entries if EMPLOYER_PACKAGE_RE.search(e["t"])))
    if hits:
        return CheckResult("B18", False, "employer package path(s) shipped: %s" % ", ".join(hits), True)
    return CheckResult("B18", True, "no employer package paths in %d entries" % len(ctx.entries), True)


# ---------------------------------------------------------------------------
# Credential gate (spec 8)
# ---------------------------------------------------------------------------
L2_PATTERNS = (
    ("hf_token", re.compile(rb"hf_[A-Za-z0-9]{34,40}")),
    ("private_key", re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("aws_access_key_id", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("github_token", re.compile(rb"gh[pousr]_[A-Za-z0-9]{36}")),
    ("anthropic_api_key", re.compile(rb"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_-]{32,}")),
    ("openai_api_key", re.compile(rb"(?<![A-Za-z0-9])sk-(?:proj-)?[A-Za-z0-9_-]{32,}")),
)


def is_allowlisted(allow, component, relpath, sha256, pattern_id):
    return (component, relpath, sha256, pattern_id) in allow


def parse_allowlist(data, label):
    doc = json.loads(data.decode("utf-8"))
    if not isinstance(doc, dict) or doc.get("schema_version") != 1 or not isinstance(doc.get("entries"), list):
        raise ValueError('%s: expected {"schema_version": 1, "entries": [...]}' % label)
    allow = set()
    entries = []
    for index, item in enumerate(doc["entries"]):
        if not isinstance(item, dict):
            raise ValueError("%s: entry %d is not an object" % (label, index))
        for key in ("component", "relpath", "sha256", "pattern"):
            if not isinstance(item.get(key), str) or not item.get(key):
                raise ValueError("%s: entry %d: %s must be a non-empty string" % (label, index, key))
        note = item.get("note")
        if not isinstance(note, str) or not note.strip():
            raise ValueError("%s: entry %d: note must be a non-empty string" % (label, index))
        allow.add((item["component"], item["relpath"], item["sha256"], item["pattern"]))
        entries.append(item)
    return allow, entries


def load_allowlist(path):
    with open(path, "rb") as fh:
        return parse_allowlist(fh.read(), path)


def l2_scan_bytes(data):
    return [pid for pid, rx in L2_PATTERNS if rx.search(data)]


def l2_scan_sources(ctx):
    hits = []
    errors = []
    for entry in ctx.entries:
        if entry["k"] != "f" or "_src" not in entry or entry["b"] > L2_MAX_BYTES:
            continue
        try:
            with open(entry["_src"], "rb") as fh:
                data = fh.read()
        except OSError as exc:
            errors.append("cannot read %s for the L2 scan: %s" % (entry["_src"], exc))
            continue
        pids = l2_scan_bytes(data)
        if pids:
            digest = sha256_bytes(data)
            for pid in pids:
                hits.append({"component": entry["c"], "relpath": entry["_rel"], "sha256": digest, "pattern": pid})
    return hits, errors


def classify_l2_hits(hits, allow):
    new = []
    allowed = []
    for hit in hits:
        if is_allowlisted(allow, hit["component"], hit["relpath"], hit["sha256"], hit["pattern"]):
            allowed.append(hit)
        else:
            new.append(hit)
    return new, allowed


def stale_allowlist_entries(entries, hits):
    keys = set((h["component"], h["relpath"], h["sha256"], h["pattern"]) for h in hits)
    return [e for e in entries if (e["component"], e["relpath"], e["sha256"], e["pattern"]) not in keys]


def report_json(hit):
    return json.dumps({"component": hit["component"], "relpath": hit["relpath"], "sha256": hit["sha256"],
                       "pattern": hit["pattern"], "note": ""}, separators=(", ", ": "))


def load_deploy_files(ctx):
    """Read scripts/deploy/* into memory before any write (stage step 4); parse the allowlist."""
    directory = deploy_dir()
    for name in DEPLOY_SCRIPT_FILES:
        with open(os.path.join(directory, name), "rb") as fh:
            ctx.script_bytes[name] = fh.read()
    try:
        ctx.allow, ctx.allow_entries = parse_allowlist(ctx.script_bytes["credential_allowlist.json"],
                                                       os.path.join(directory, "credential_allowlist.json"))
        ctx.allow_error = None
    except ValueError as exc:
        ctx.allow, ctx.allow_entries, ctx.allow_error = set(), [], str(exc)


def prepare_l2(ctx):
    ctx.l2_hits, ctx.l2_errors = l2_scan_sources(ctx)
    ctx.l2_new, ctx.l2_allowed = classify_l2_hits(ctx.l2_hits, ctx.allow)


def _read_token_file(path, label, add, sources, errors):
    if not os.path.lexists(path):
        sources.append({"source": label, "present": False, "values": 0})
        return
    try:
        with open(path, "rb") as fh:
            value = fh.read().strip()
    except OSError as exc:
        errors.append("B14: cannot read %s: %s" % (label, exc))
        sources.append({"source": label, "present": True, "values": 0})
        return
    sources.append({"source": label, "present": True, "values": add(label, [value])})


def _read_stored_tokens_file(path, label, add, sources, errors):
    if not os.path.lexists(path):
        sources.append({"source": label, "present": False, "values": 0})
        return
    found = []
    try:
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8")
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(text)
        for section in parser.sections():
            if parser.has_option(section, "hf_token"):
                found.append(parser.get(section, "hf_token").strip().encode("utf-8"))
            if parser.has_option(section, "refresh_token"):
                found.append(parser.get(section, "refresh_token").strip().encode("utf-8"))
    except (OSError, UnicodeDecodeError, configparser.Error):
        errors.append("B14: %s exists but cannot be parsed" % label)
        sources.append({"source": label, "present": True, "values": 0})
        return
    if not [v for v in found if v]:
        errors.append("B14: %s yields no hf_token or refresh_token values" % label)
    sources.append({"source": label, "present": True, "values": add(label, found)})


def load_known_secrets():
    """L3 secret values (spec 8.3). Values are never written, logged, hashed into output or measured."""
    H = home()
    values = []
    sources = []
    errors = []
    seen_paths = set()

    def add(label, candidates):
        count = 0
        for value in candidates:
            if not value:
                continue
            count += 1
            if len(value) < 16:
                errors.append("B14: a known-secret value from %s is too short to scan safely (< 16 bytes)" % label)
            if value not in values:
                values.append(value)
        return count

    def read_file(path, reader):
        path = os.path.normpath(path)
        if path in seen_paths:
            return
        seen_paths.add(path)
        reader(path, path, add, sources, errors)

    def read_env_value(name):
        label = "$" + name
        env_value = os.environ.get(name)
        if env_value is None:
            sources.append({"source": label, "present": False, "values": 0})
        else:
            sources.append({"source": label, "present": True, "values": add(label, [env_value.strip().encode("utf-8")])})

    def env_path(name):
        raw = os.environ.get(name)
        if not raw:
            return None
        return os.path.expandvars(os.path.expanduser(raw))

    read_file(H + "/.cache/huggingface/token", _read_token_file)
    read_file(H + "/.cache/huggingface/stored_tokens", _read_stored_tokens_file)
    read_file(H + "/ltx-2-mlx/hf_cache/token", _read_token_file)
    read_env_value("HF_TOKEN")
    hf_home_env = env_path("HF_HOME")
    if hf_home_env is not None:
        read_file(hf_home_env + "/token", _read_token_file)
        read_file(hf_home_env + "/stored_tokens", _read_stored_tokens_file)
    hf_home_dirs = [H + "/hf_home"] + sorted(glob.glob(os.path.join(VOLUMES_ROOT, "*", "hf_home")))
    for hf_dir in hf_home_dirs:
        read_file(hf_dir + "/token", _read_token_file)
        read_file(hf_dir + "/stored_tokens", _read_stored_tokens_file)
    token_path = env_path("HF_TOKEN_PATH")
    if token_path is not None:
        read_file(token_path, _read_token_file)
    read_env_value("HUGGING_FACE_HUB_TOKEN")
    return values, sources, errors


def list_tree(root):
    """[(relpath, lstat)] for everything under root, sorted, never following symlinks."""
    out = []

    def walk(rel_dir):
        abs_dir = root + "/" + rel_dir if rel_dir else root
        for name in sorted(os.listdir(abs_dir)):
            rel = rel_dir + "/" + name if rel_dir else name
            st = os.lstat(root + "/" + rel)
            out.append((rel, st))
            if stat.S_ISDIR(st.st_mode):
                walk(rel)
    walk("")
    return out


def allowlist_key(rel):
    parts = rel.split("/")
    if len(parts) >= 3 and parts[0] == "payload":
        return parts[1].split("-", 1)[0], "/".join(parts[2:])
    return "ROOT", rel


def scan_package(package_root, allow):
    """L1 + L2 over every file and symlink under package_root; any .DS_Store fails."""
    failures = []
    allowed = []
    for rel, st in list_tree(package_root):
        name = rel.rsplit("/", 1)[-1]
        if name == ".DS_Store":
            failures.append("DS_Store: " + rel)
            continue
        if stat.S_ISDIR(st.st_mode):
            continue
        if name in L1_NAMES:
            failures.append("L1 " + rel)
        if stat.S_ISREG(st.st_mode) and st.st_size <= L2_MAX_BYTES:
            with open(package_root + "/" + rel, "rb") as fh:
                data = fh.read()
            pids = l2_scan_bytes(data)
            if pids:
                component, relpath = allowlist_key(rel)
                digest = sha256_bytes(data)
                for pid in pids:
                    if is_allowlisted(allow, component, relpath, digest, pid):
                        allowed.append({"component": component, "relpath": relpath, "sha256": digest, "pattern": pid})
                    else:
                        failures.append("L2 %s %s" % (pid, rel))
    return failures, allowed


def check_b12(ctx):
    ok = not ctx.l1_hits
    message = ("L1: no credential-named files" if ok else
               "L1: credential-named file(s) (a component root is wrong): %s" % ", ".join(ctx.l1_hits))
    return CheckResult("B12", ok, message, True)


def check_b13(ctx):
    problems = []
    if ctx.allow_error:
        problems.append("allowlist failed to load: %s" % ctx.allow_error)
    problems.extend(ctx.l2_errors)
    if ctx.l2_new:
        shown = "; ".join("%s %s %s" % (h["component"], h["relpath"], h["pattern"]) for h in ctx.l2_new[:20])
        problems.append("%d L2 hit(s) not allowlisted (review them with --credential-report): %s" % (len(ctx.l2_new), shown))
    ok = not problems
    message = ("L2: %d hit(s), all allowlisted" % len(ctx.l2_allowed)) if ok else " | ".join(problems)
    return CheckResult("B13", ok, message, True)


def stale_allowlist_warnings(ctx):
    return [CheckResult("B13", False, "stale allowlist entry " + json.dumps(entry, separators=(", ", ": ")), False)
            for entry in stale_allowlist_entries(ctx.allow_entries, ctx.l2_hits)]


def check_b14(ctx):
    ok = not ctx.l3_errors
    present = ", ".join("%s=%s" % (s["source"], "present" if s["present"] else "absent") for s in ctx.l3_sources)
    message = ("L3: %d distinct known-secret value(s) loaded (%s)" % (len(ctx.secrets), present)) if ok else "; ".join(ctx.l3_errors)
    return CheckResult("B14", ok, message, True)


def credential_scan_doc(ctx):
    return {
        "l1_names": sorted(L1_NAMES),
        "l2_patterns": dict((pid, rx.pattern.decode("latin-1")) for pid, rx in L2_PATTERNS),
        "l2_max_bytes": L2_MAX_BYTES,
        "l2_allowlisted_hits": list(ctx.l2_allowed),
        "l3_sources": list(ctx.l3_sources),
    }


def l4_rescan(ctx):
    failures, allowed = scan_package(ctx.package_root, ctx.allow)
    if failures:
        raise CredentialLeak("L4: %d finding(s) in the package: %s" % (len(failures), "; ".join(failures[:20])))


def cmd_credential_report(args):
    ctx = BuildCtx(args)
    enumerate_components(ctx)
    load_deploy_files(ctx)
    prepare_l2(ctx)
    for path in ctx.l1_hits:
        print("L1 " + path)
    for hit in ctx.l2_hits:
        print("L2 %s %s" % ("ALLOWLISTED" if hit in ctx.l2_allowed else "NEW", report_json(hit)))
    stale = stale_allowlist_entries(ctx.allow_entries, ctx.l2_hits)
    for entry in stale:
        print("STALE " + json.dumps(entry, separators=(", ", ": ")))
    for message in ctx.enum_errors + ctx.l2_errors:
        print("ENUM-ERROR " + message)
    if ctx.allow_error:
        print("ALLOWLIST-ERROR " + ctx.allow_error)
    clean = not (ctx.l1_hits or ctx.l2_new or ctx.enum_errors or ctx.l2_errors or ctx.allow_error)
    print("build_pkg: CREDENTIAL REPORT %s: l1=%d new=%d allowlisted=%d stale=%d" % (
        "CLEAN" if clean else "NOT CLEAN", len(ctx.l1_hits), len(ctx.l2_new), len(ctx.l2_allowed), len(stale)))
    return 0 if clean else 1
