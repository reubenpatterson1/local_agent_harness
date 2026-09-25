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
        self.deploy_script_record = {}
        self.deploy_script_problems = []
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


def has_secret(ctx, text):
    """True if text holds a known secret value (L3) or a secret-shaped string (L2)."""
    data = text.encode("utf-8", "backslashreplace")
    return bool(KnownSecretScanner(ctx.secrets).feed(data) or l2_scan_bytes(data))


def safe_line(ctx, line, withheld):
    """line, or withheld (fixed words, check ids, reasons and counts only) if line holds secret material."""
    return withheld if has_secret(ctx, line) else line


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
    """L1 over every file and symlink under package_root; any .DS_Store fails. L2 over every regular
    file up to L2_MAX_BYTES, and over MANIFEST-ENTRIES.jsonl at any size (it holds every path and
    symlink value in the package, and a real one is far larger than L2_MAX_BYTES)."""
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
        if stat.S_ISREG(st.st_mode) and (st.st_size <= L2_MAX_BYTES or rel == "MANIFEST-ENTRIES.jsonl"):
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
    ctx.secrets = load_known_secrets()[0]   # L3 values for safe_line(): compared only, never printed
    enumerate_components(ctx)
    load_deploy_files(ctx)
    prepare_l2(ctx)
    for path in ctx.l1_hits:
        print(safe_line(ctx, "L1 " + path, "L1 (path withheld: it contained secret material)"))
    for hit in ctx.l2_hits:
        print("L2 %s %s" % ("ALLOWLISTED" if hit in ctx.l2_allowed else "NEW", report_json(hit)))
    stale = stale_allowlist_entries(ctx.allow_entries, ctx.l2_hits)
    for entry in stale:
        print("STALE " + json.dumps(entry, separators=(", ", ": ")))
    for message in ctx.enum_errors + ctx.l2_errors:
        print(safe_line(ctx, "ENUM-ERROR " + message, "ENUM-ERROR (message withheld: it contained secret material)"))
    if ctx.allow_error:
        print(safe_line(ctx, "ALLOWLIST-ERROR " + ctx.allow_error, "ALLOWLIST-ERROR (message withheld: it contained secret material)"))
    clean = not (ctx.l1_hits or ctx.l2_new or ctx.enum_errors or ctx.l2_errors or ctx.allow_error)
    print("build_pkg: CREDENTIAL REPORT %s: l1=%d new=%d allowlisted=%d stale=%d" % (
        "CLEAN" if clean else "NOT CLEAN", len(ctx.l1_hits), len(ctx.l2_new), len(ctx.l2_allowed), len(stale)))
    return 0 if clean else 1


# ---------------------------------------------------------------------------
# Offline gates (spec 10.1) -- shared with install_pkg (accept A3)
# ---------------------------------------------------------------------------
LTX25_LITERAL = "/Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8"
GATE_SPECS = (
    ("G1", ("tests/test_ltx_movie_offline.py",)),
    ("G2", ("tests/test_ltx_mlx_render.py",)),
    ("G3", ("tests/test_ltx_story_images.py",)),
    ("G4", ("tests/test_ltx2_mlx_video_skill.py",)),
    ("G5", ("tests/test_ltx_image_fit.py",)),
    ("G6", ("tests/test_ltx_story_manifest_chain.py",)),
    ("G7", ("tests/check_ltx2_mlx_no_forbidden_imports.py",)),
)
EXTRA_SPECS = (
    ("X1", ("bin/ltx-mlx-render", "--help")),
    ("X2", ("bin/ltx-movie", "a test narrative", "--story-id", "deploy-gate-dry", "--dry-run", "--no-review",
            "--model", LTX25_LITERAL)),
)
OK_LINE_RE = re.compile(r"^OK (\d+)/\1$")


def run_offline_gates(run, py, cwd):
    """Run G1-G7 then X1, X2 by direct invocation (never through pytest)."""
    gates = []
    for gate_id, argv in GATE_SPECS:
        rc, text = run([py] + list(argv), timeout=GATE_TIMEOUT, cwd=cwd)
        gates.append({"id": gate_id, "argv": list(argv), "rc": rc, "last_line": last_line(text)})
    extras = []
    for extra_id, argv in EXTRA_SPECS:
        rc, text = run([py] + list(argv), timeout=GATE_TIMEOUT, cwd=cwd)
        record = {"id": extra_id, "argv": list(argv), "rc": rc}
        if extra_id == "X2":
            record["brace_lines"] = sum(1 for line in text.splitlines() if "{" in line or "}" in line)
        extras.append(record)
    return gates, extras


def gate_build_failures(gates, extras):
    bad = []
    for gate in gates:
        if gate["id"] == "G7":
            ok = gate["rc"] == 0 and gate["last_line"] == "RESULT: ok"
        else:
            ok = gate["rc"] == 0 and OK_LINE_RE.match(gate["last_line"]) is not None
        if not ok:
            bad.append("%s rc=%r last_line=%r" % (gate["id"], gate["rc"], gate["last_line"]))
    for extra in extras:
        if extra["id"] == "X1" and extra["rc"] != 0:
            bad.append("X1 rc=%r" % extra["rc"])
        if extra["id"] == "X2" and (extra["rc"] != 0 or extra["brace_lines"] != 0):
            bad.append("X2 rc=%r brace_lines=%r" % (extra["rc"], extra["brace_lines"]))
    return bad


def check_offline_gates(ctx):
    gates, extras = run_offline_gates(_run, framework_py(), workspace())
    ctx.baseline = {"schema_version": 1, "measured_at": iso_now(), "interpreter": framework_py(),
                    "cwd": workspace(), "gates": gates, "extras": extras}
    bad = gate_build_failures(gates, extras)
    message = "offline gates G1-G7, X1, X2 passed" if not bad else "offline gate failure(s): " + "; ".join(bad)
    return CheckResult("B15", not bad, message, True)


# ---------------------------------------------------------------------------
# Host facts, pip freezes, git provenance (spec 6.4, B16, B17)
# ---------------------------------------------------------------------------
def _first_line(text):
    lines = text.strip().splitlines()
    return lines[0].strip() if lines else ""


def _probe(ctx, key, argv, pick_last=False):
    rc, text = _run(argv, timeout=HOST_TIMEOUT)
    if rc != 0:
        ctx.host_failures.append("%s: %s exited %d" % (key, " ".join(argv), rc))
        return ""
    return last_line(text).strip() if pick_last else _first_line(text)


def gather_host_facts(ctx):
    H = home()
    host = {}
    host["hw_model"] = _probe(ctx, "hw_model", ["/usr/sbin/sysctl", "-n", "hw.model"])
    host["cpu"] = _probe(ctx, "cpu", ["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"])
    memsize = _probe(ctx, "memsize", ["/usr/sbin/sysctl", "-n", "hw.memsize"])
    if memsize.isdigit():
        host["memsize"] = int(memsize)
    else:
        host["memsize"] = -1
        ctx.host_failures.append("memsize: %r is not an integer" % memsize)
    host["product_version"] = _probe(ctx, "product_version", ["/usr/bin/sw_vers", "-productVersion"])
    host["build_version"] = _probe(ctx, "build_version", ["/usr/bin/sw_vers", "-buildVersion"])
    host["machine"] = platform.machine()
    host["framework_python_version"] = _probe(ctx, "framework_python_version",
                                              [framework_py(), "-c", "import sys;print(sys.version.split()[0])"])
    for key, tool in (("ffmpeg_version", "ffmpeg"), ("ffprobe_version", "ffprobe")):
        path = HOOKS["which"](tool)
        if path:
            host[key] = _probe(ctx, key, [path, "-version"])
        else:
            host[key] = ""
            ctx.host_failures.append("%s: %s not found on PATH" % (key, tool))
    host["brew_version"] = _probe(ctx, "brew_version", [BREW_BIN, "--version"])
    host["brew_python312_version"] = _probe(ctx, "brew_python312_version", [BREW_PY312, "--version"])
    # C1: vllm logs timestamped INFO lines before the version; the version is the LAST line.
    host["vllm_version"] = _probe(ctx, "vllm_version", [H + "/.venv-vllm-metal/bin/python", "-c",
                                                        "import vllm; print(vllm.__version__)"], pick_last=True)
    host["falconsai_source_hub"] = ctx.falconsai_hub or ""
    host["gathered_at"] = iso_now()
    ctx.host = host


def freeze_commands():
    H = home()
    return (
        ("manifests/pip-freeze-framework-py313.txt",
         [framework_py(), "-m", "pip", "freeze", "--all", "--exclude", "fubotv-mcp-common", "--exclude", "student-agent-mcp"]),
        ("manifests/pip-freeze-ltx2mlx-venv.txt",
         [FRAMEWORK_ROOT + "/Versions/3.13/bin/uv", "pip", "freeze", "--python", H + "/ltx-2-mlx/.venv/bin/python"]),
        ("manifests/pip-freeze-vllm-venv.txt",
         [H + "/.venv-vllm-metal/bin/python", "-m", "pip", "freeze", "--all"]),
    )


def gather_freezes(ctx):
    for rel, argv in freeze_commands():
        rc, text = _run(argv, timeout=FREEZE_TIMEOUT)
        if rc != 0:
            ctx.host_failures.append("%s: %s exited %d" % (rel, " ".join(argv), rc))
        ctx.freezes[rel] = text


def git_file_state(repo, rel):
    rp = WS_REPO_PREFIX + "/" + rel
    abs_path = workspace() + "/" + rel
    try:
        with open(abs_path, "rb") as fh:
            data = fh.read()
    except OSError:
        return {"sha256": "", "git_blob": "", "clean": False}, "missing"
    rc_ls, _ = _run([GIT, "-C", repo, "ls-files", "--error-unmatch", "--", rp])
    rc_st, st_out = _run([GIT, "-C", repo, "status", "--porcelain", "--", rp])
    rc_ho, ho_out = _run([GIT, "-C", repo, "hash-object", abs_path])
    rc_rp, rp_out = _run([GIT, "-C", repo, "rev-parse", "HEAD:" + rp])
    blob = rp_out.strip() if rc_rp == 0 else ""
    reason = ""
    if rc_ls != 0:
        reason = "untracked"
    elif rc_st != 0 or st_out.strip():
        reason = "modified"
    elif rc_ho != 0 or rc_rp != 0 or ho_out.strip() != blob:
        reason = "blob differs"
    return {"sha256": sha256_bytes(data), "git_blob": blob, "clean": not reason}, reason


def gather_git_record(ctx):
    repo = repo_root()
    problems = []
    rc, out = _run([GIT, "-C", repo, "rev-parse", "HEAD"])
    if rc != 0:
        problems.append("git rev-parse HEAD failed (rc=%d)" % rc)
    head = out.strip() if rc == 0 else ""
    rc, out = _run([GIT, "-C", repo, "rev-parse", "--abbrev-ref", "HEAD"])
    branch = out.strip() if rc == 0 else ""
    rc, out = _run([GIT, "-C", repo, "status", "--porcelain", "--", WS_REPO_PREFIX])
    porcelain = [line for line in out.splitlines() if line.strip()] if rc == 0 else []
    record = {"head": head, "branch": branch, "porcelain": porcelain, "pipeline_files": {}, "test_files": {}}
    for rel in PIPELINE_FILES:
        info, reason = git_file_state(repo, rel)
        record["pipeline_files"][rel] = info
        if reason:
            problems.append("%s: %s" % (rel, reason))
    for rel in TEST_FILES:
        info, reason = git_file_state(repo, rel)
        record["test_files"][rel] = info
    ctx.git_record = record
    ctx.git_problems = problems


def gather_deploy_script_record(ctx):
    """B19: the running deploy scripts are the checkout's own, and each matches HEAD (reuses git_file_state)."""
    repo = repo_root()
    problems = []
    actual = os.path.realpath(deploy_dir())
    expected = os.path.realpath(workspace() + "/scripts/deploy")
    if actual != expected:
        problems.append("deploy_dir() is %s, expected %s" % (actual, expected))
    record = {"deploy_dir": actual, "expected_deploy_dir": expected, "files": {}}
    for name in DEPLOY_SCRIPT_FILES:
        rel = "scripts/deploy/" + name
        state, reason = git_file_state(repo, rel)
        record["files"][rel] = state
        if reason:
            problems.append("%s: %s" % (rel, reason))
    ctx.deploy_script_record = record
    ctx.deploy_script_problems = problems


# ---------------------------------------------------------------------------
# Resume-prefix analysis (spec 11.3; read-only, used by B07)
# ---------------------------------------------------------------------------
def entry_identity(entry):
    return tuple(entry.get(key) for key in ("k", "c", "p", "t", "l", "s"))


def payload_matches(package_root, line):
    if "p" not in line:
        return True
    path = package_root + "/" + line["p"]
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if line["k"] == "f":
        return stat.S_ISREG(st.st_mode) and st.st_size == line.get("b") and sha256_file(path) == line.get("h")
    if line["k"] == "l":
        return stat.S_ISLNK(st.st_mode) and os.readlink(path) == line.get("l")
    return stat.S_ISDIR(st.st_mode)


def analyze_resume(ctx):
    root = ctx.package_root
    partial = root + "/MANIFEST-ENTRIES.jsonl.partial"
    final = root + "/MANIFEST-ENTRIES.jsonl"
    ctx.resume_prefix_len = 0
    ctx.resume_keep_bytes = 0
    ctx.resume_rename = False
    ctx.resume_error = None
    if os.path.exists(partial):
        source = partial
    elif os.path.exists(final):
        source = final
        ctx.resume_rename = True
    else:
        return
    with open(source, "rb") as fh:
        data = fh.read()
    complete = data[:data.rfind(b"\n") + 1]
    offset = 0
    for index, raw in enumerate(complete.split(b"\n")[:-1]):
        try:
            line = json.loads(raw.decode("utf-8"))
        except ValueError:
            ctx.resume_error = "line %d of %s is not valid JSON; delete %s and rebuild" % (index, source, root)
            return
        if index >= len(ctx.entries) or entry_identity(line) != entry_identity(ctx.entries[index]):
            ctx.resume_error = "enumeration changed since the interrupted build; delete %s and rebuild" % root
            return
        fresh = ctx.entries[index]
        if (line.get("b"), line.get("m"), line.get("mt")) != (fresh.get("b"), fresh.get("m"), fresh.get("mt")):
            ctx.resume_error = "source changed since the interrupted build: %s" % fresh.get("_src", fresh["t"])
            return
        if not payload_matches(root, line):
            break
        if line["k"] == "f":
            fresh["h"] = line["h"]
        offset += len(raw) + 1
        ctx.resume_prefix_len = index + 1
    ctx.resume_keep_bytes = offset


# ---------------------------------------------------------------------------
# B01-B17 (spec 10)
# ---------------------------------------------------------------------------
def _under(path, root):
    return path == root or path.startswith(root + "/")


def check_b01(ctx):
    mounted = bool(HOOKS["ismount"](ctx.usb_root))
    personality = HOOKS["diskutil_personality"](ctx.usb_root) if mounted else ""
    ok = mounted and "APFS" in personality and "Case-sensitive" in personality
    return CheckResult("B01", ok, "usb_root=%s mounted=%s personality=%r (need a mounted Case-sensitive APFS volume)"
                       % (ctx.usb_root, mounted, personality), True)


def check_b02(ctx):
    total = sum(e["b"] for e in ctx.entries if e["k"] == "f")
    done = sum(e["b"] for e in ctx.entries[:ctx.resume_prefix_len] if e["k"] == "f")
    ctx.remaining_bytes = total - done
    ctx.required_bytes = ctx.remaining_bytes + BUILD_HEADROOM_BYTES
    try:
        ctx.free_bytes = HOOKS["statvfs_free"](ctx.usb_root)
    except OSError:
        ctx.free_bytes = -1
    ok = ctx.free_bytes >= ctx.required_bytes
    return CheckResult("B02", ok, "free=%d required=%d (remaining %d + headroom %d)"
                       % (ctx.free_bytes, ctx.required_bytes, ctx.remaining_bytes, BUILD_HEADROOM_BYTES), True)


def read_pyvenv_home(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                key, sep, value = line.partition("=")
                if sep and key.strip() == "home":
                    return value.strip()
    except OSError:
        return None
    return None


def check_b03(ctx):
    problems = list(ctx.enum_errors)
    H = home()
    for cfg, want in ((H + "/ltx-2-mlx/.venv/pyvenv.cfg", b3_source() + "/bin"),
                      (H + "/.venv-vllm-metal/pyvenv.cfg", os.path.dirname(BREW_PY312))):
        got = read_pyvenv_home(cfg)
        if got != want:
            problems.append("%s: home = %r, expected %r" % (cfg, got, want))
    ok = not problems
    return CheckResult("B03", ok, "sources readable; venv base interpreters pinned" if ok else "; ".join(problems[:20]), True)


def check_b04(ctx):
    pack = ltx25_model_path()
    try:
        names = set(os.listdir(pack)) - set([".cache", ".DS_Store"])
    except OSError as exc:
        return CheckResult("B04", False, "cannot list %s: %s" % (pack, exc), True)
    extra = sorted(names - LTX25_PACK_FILES)
    missing = sorted(LTX25_PACK_FILES - names)
    not_regular = sorted(n for n in names & LTX25_PACK_FILES if not stat.S_ISREG(os.lstat(pack + "/" + n).st_mode))
    ok = not extra and not missing and not not_regular
    return CheckResult("B04", ok, "%s: %d pinned files; extra=%s missing=%s not_regular=%s"
                       % (pack, len(LTX25_PACK_FILES), extra, missing, not_regular), True)


def hf_repo_problems(repo_dir, pin):
    if not os.path.isdir(repo_dir):
        return ["%s: repo dir missing" % repo_dir]
    problems = []
    try:
        with open(repo_dir + "/refs/main", "r") as fh:
            ref = fh.read().strip()
    except OSError:
        ref = None
    if ref != pin:
        problems.append("%s: refs/main=%r, expected %s" % (repo_dir, ref, pin))
    try:
        snaps = sorted(n for n in os.listdir(repo_dir + "/snapshots") if n != ".DS_Store")
    except OSError:
        snaps = None
    if snaps != [pin]:
        problems.append("%s: snapshots=%r, expected [%r]" % (repo_dir, snaps, pin))
    blobs = repo_dir + "/blobs"
    if not os.path.isdir(blobs):
        problems.append("%s: blobs/ missing" % repo_dir)
    for dirpath, dirnames, filenames in os.walk(blobs):
        for name in dirnames + filenames:
            if name.endswith(".incomplete"):
                problems.append("%s: incomplete download %s" % (repo_dir, os.path.join(dirpath, name)))
    blobs_real = os.path.realpath(blobs)
    for dirpath, dirnames, filenames in os.walk(repo_dir):
        for name in dirnames + filenames:
            path = os.path.join(dirpath, name)
            if os.path.islink(path):
                real = os.path.realpath(path)
                if not (real.startswith(blobs_real + "/") and os.path.isfile(real)):
                    problems.append("%s: symlink does not resolve to a blob: %s" % (repo_dir, path))
    return problems


def check_b05(ctx):
    hub = home() + "/hf_home/hub"
    problems = []
    for cid in ("H1", "H2", "H3", "H4"):
        repo, pin = HF_PINS[cid]
        source_hub = ctx.falconsai_hub if cid == "H3" else hub
        if source_hub is None:
            problems.append("H3: %s not found in either hub" % repo)
            continue
        problems.extend(hf_repo_problems(source_hub + "/" + repo, pin))
    ok = not problems
    return CheckResult("B05", ok, "H1-H4 complete at their pinned snapshots" if ok else "; ".join(problems[:20]), True)


def check_b06(ctx):
    problems = []
    for key in ("p", "t"):
        seen = {}
        for entry in ctx.entries:
            if key in entry:
                seen.setdefault(entry[key].lower(), []).append(entry[key])
        for values in seen.values():
            if len(values) > 1:
                problems.append("%s collision: %s" % (key, " | ".join(values)))
    ok = not problems
    return CheckResult("B06", ok, "no case-insensitive p/t collisions" if ok else "; ".join(problems[:20]), True)


def check_b07(ctx):
    root = ctx.package_root
    if not ctx.resume:
        if os.path.lexists(root):
            return CheckResult("B07", False, "package root %s already exists; pass --resume to continue an interrupted build, or choose another --package-id" % root, True)
        return CheckResult("B07", True, "package root %s does not exist yet" % root, True)
    if not os.path.isdir(root):
        return CheckResult("B07", False, "--resume given but %s does not exist" % root, True)
    if os.path.lexists(root + "/MANIFEST.json"):
        return CheckResult("B07", False, "%s already holds MANIFEST.json (the build is complete; nothing to resume)" % root, True)
    if ctx.resume_error:
        return CheckResult("B07", False, ctx.resume_error, True)
    return CheckResult("B07", True, "resume prefix: %d of %d entries verified" % (ctx.resume_prefix_len, len(ctx.entries)), True)


def check_b08(ctx):
    want = h5_link_value()
    problems = []
    h5 = [e for e in ctx.entries if e["c"] == "H5" and e["k"] == "l"]
    h4_dirs = set(e["t"] for e in ctx.entries if e["c"] == "H4" and e["k"] == "d")
    if len(h5) != 1 or h5[0]["l"] != want or want not in h4_dirs:
        problems.append("H5 link value is not the t of the pinned H4 snapshot dir %s" % want)
    link = home() + "/mlx_models/qwen3-vl"
    try:
        live = os.readlink(link)
    except OSError:
        live = None
    if live != want:
        problems.append("live %s -> %r, expected %s" % (link, live, want))
    ok = not problems
    return CheckResult("B08", ok, "mlx_models/qwen3-vl -> pinned H4 snapshot" if ok else "; ".join(problems), True)


def check_b09(ctx):
    ok = bool(HOOKS["port_free"](STORY_PORT))
    message = ("port %d is free" % STORY_PORT) if ok else (
        "port %d is in use: stop the story server before building (bin/story-server stop)" % STORY_PORT)
    return CheckResult("B09", ok, message, True)


def check_b10(ctx):
    H = home()
    src_scopes = (H + "/hf_home", os.path.dirname(FALCONSAI_USB_HUB), H + "/.cache/huggingface", H + "/ltx-2-mlx/hf_cache")
    pinned_src = [H + "/hf_home/hub/" + HF_PINS[c][0] for c in ("H1", "H2", "H4")]
    if ctx.falconsai_hub:
        pinned_src.append(ctx.falconsai_hub + "/" + HF_PINS["H3"][0])
    pinned_tgt = [H + "/hf_home/hub/" + HF_PINS[c][0] for c in ("H1", "H2", "H3", "H4")]
    problems = []
    for entry in ctx.entries:
        src = entry.get("_src")
        if src and any(_under(src, s) for s in src_scopes) and not any(_under(src, r) for r in pinned_src):
            problems.append("source outside the pinned HF repos: %s" % src)
        target = entry["t"]
        if _under(target, H + "/hf_home") and entry["c"] != "H0" and not any(_under(target, r) for r in pinned_tgt):
            problems.append("target under ~/hf_home outside the pinned repos: %s" % target)
        if _under(target, H + "/ltx-2-mlx/hf_cache") and entry["c"] != "B5":
            problems.append("target under ~/ltx-2-mlx/hf_cache that is not a B5 dir: %s" % target)
    ok = not problems
    return CheckResult("B10", ok, "HF sources and targets stay inside the pinned repos" if ok else "; ".join(problems[:20]), True)


def target_allowed(t):
    # C3 (plan addition): absolute and already normalised, so "..", "//" and "." cannot escape.
    if not t.startswith("/") or os.path.normpath(t) != t:
        return False
    if t.startswith("/Volumes/") or t.startswith("/opt/homebrew/"):
        return False
    return (t.startswith(REQUIRED_HOME + "/")
            or t == FRAMEWORK_ROOT or t.startswith(FRAMEWORK_ROOT + "/")
            or t == USR_LOCAL_BIN or t.startswith(USR_LOCAL_BIN + "/"))


def check_b11(ctx):
    problems = []
    if home() != REQUIRED_HOME:
        problems.append("home() is %s, expected %s" % (home(), REQUIRED_HOME))
    bad = [e["t"] for e in ctx.entries if not target_allowed(e["t"])]
    if bad:
        problems.append("%d target(s) outside the allowlist: %s" % (len(bad), ", ".join(bad[:20])))
    ok = not problems
    return CheckResult("B11", ok, "every target is under %s, %s or %s" % (REQUIRED_HOME, FRAMEWORK_ROOT, USR_LOCAL_BIN) if ok else "; ".join(problems), True)


def check_b16(ctx):
    gather_host_facts(ctx)
    gather_freezes(ctx)
    ok = not ctx.host_failures
    return CheckResult("B16", ok, "host facts and 3 pip freezes gathered" if ok else "; ".join(ctx.host_failures), True)


def check_b17(ctx):
    gather_git_record(ctx)
    ok = not ctx.git_problems
    message = ("all 10 pipeline files match HEAD %s" % ctx.git_record.get("head", "")) if ok else (
        "provenance: " + "; ".join(ctx.git_problems))
    return CheckResult("B17", ok, message, True)


def check_b19(ctx):
    gather_deploy_script_record(ctx)
    ok = not ctx.deploy_script_problems
    message = ("all %d deploy script files in %s match HEAD" % (
        len(DEPLOY_SCRIPT_FILES), ctx.deploy_script_record["expected_deploy_dir"])) if ok else (
        "deploy provenance: " + "; ".join(ctx.deploy_script_problems))
    return CheckResult("B19", ok, message, True)


def check_b20(ctx):
    """B20: no present file-backed known-secret source (ctx.l3_sources) lies under the volume being
    built onto. Both sides are realpaths, so a symlink cannot hide a token file on that volume.
    "$HF_TOKEN"-style env-var sources are not paths and are skipped. Messages name paths only."""
    root = os.path.realpath(ctx.usb_root)
    prefix = root.rstrip("/") + "/"
    hits = []
    for source in ctx.l3_sources:
        label = source["source"]
        if not source["present"] or not label.startswith("/"):
            continue
        real = os.path.realpath(label)
        if real.startswith(prefix):
            hits.append(label if real == label else "%s -> %s" % (label, real))
    if hits:
        return CheckResult("B20", False, "known-secret source file(s) on the build volume %s: %s; build onto a volume "
                           "that holds no credential files (pass a different --usb-root)" % (root, ", ".join(hits)), True)
    return CheckResult("B20", True, "no present known-secret source file is under %s" % root, True)


def run_prebuild_checks(ctx):
    """Stage step 4: B01-B17 in table order, then B18, then B19, then B20. Reads only; writes nothing."""
    load_deploy_files(ctx)
    prepare_l2(ctx)
    if ctx.resume and os.path.isdir(ctx.package_root) and not os.path.lexists(ctx.package_root + "/MANIFEST.json"):
        analyze_resume(ctx)
    results = []
    results.append(check_b01(ctx))
    results.append(check_b02(ctx))
    results.append(check_b03(ctx))
    results.append(check_b04(ctx))
    results.append(check_b05(ctx))
    results.append(check_b06(ctx))
    results.append(check_b07(ctx))
    results.append(check_b08(ctx))
    results.append(check_b09(ctx))
    results.append(check_b10(ctx))
    results.append(check_b11(ctx))
    results.append(check_b12(ctx))
    results.append(check_b13(ctx))
    results.extend(stale_allowlist_warnings(ctx))
    results.append(check_b14(ctx))
    results.append(check_offline_gates(ctx))
    results.append(check_b16(ctx))
    results.append(check_b17(ctx))
    results.append(check_no_employer_packages(ctx))
    results.append(check_b19(ctx))
    results.append(check_b20(ctx))
    return results


# ---------------------------------------------------------------------------
# README (spec 14): rendered from a string constant before the copy
# ---------------------------------------------------------------------------
README_PY = "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
README_NARRATIVE = ("An old fisherman in a flat cap and a waxed coat stands at a lighthouse railing as a storm "
                    "rolls in over the sea. He grips the rail and watches the waves, then turns and walks toward "
                    "the lighthouse door.")
README_TEMPLATE = """\
# ltx-chain deployment package %(package_id)s

## 1. What this package is

- Package id: %(package_id)s
- Build date: %(build_date)s
- Source git HEAD: %(head)s (branch %(branch)s)
- It installs exactly the ltx-movie sequential I2V frame-chaining pipeline on a second, similar Mac that has the same account (user reubenpatterson, home /Users/reubenpatterson). No path is re-pinned.
- Video model: %(model)s (ltx-2.5 only). Story model: Qwen3-VL-32B served by vLLM-Metal (vision mode only).
- Code: the 10 pipeline files and their 7 offline test files, listed explicitly (no tree walk).

What ships (component, counts, size):

%(component_lines)s

## 2. Target requirements

The package does not provide these; installing them needs network.

1. A local account `reubenpatterson` with home `/Users/reubenpatterson`, on macOS >= 26, Apple Silicon, >= 48 GiB RAM.
2. Homebrew at `/opt/homebrew`. Installing it also installs the Command Line Tools, which `/usr/bin/python3` needs on a fresh Mac.
3. `brew install ffmpeg python@3.12`. ffmpeg/ffprobe must be major version 9, and `/opt/homebrew/opt/python@3.12/bin/python3.12` must report 3.12.x. It is the vLLM venv's base interpreter.
4. `~/.zshenv` contains `export HF_HOME="/Users/reubenpatterson/hf_home"` and no `HF_HOME` line that mentions `/Volumes/`. The exact line to add is:

    export HF_HOME="/Users/reubenpatterson/hf_home"

5. A real Terminal session that can `sudo`, for the `system-python` phase.

## 3. Install

Run these in order, each on one line. A phase changes nothing unless it says --apply.

    %(inst)s --phase preflight
    sudo %(inst)s --phase system-python --apply
    %(inst)s --phase user --apply
    %(inst)s --phase verify
    %(inst)s --phase accept --gpu

The system-python phase needs a real Terminal, because sudo asks for a password.

Optional, all four acceptance geometries (portrait, wide, square, no seed):

    %(inst)s --phase accept --gpu-all

After the drive is ejected, run acceptance from the receipts copy:

    /usr/bin/python3 /Users/reubenpatterson/local_model_harness/qwen-agent-workspace/generated/deploy-receipts/%(package_id)s/scripts/deploy/install_pkg.py --phase accept --gpu

## 4. Running the pipeline

Start the story server and wait until it answers:

    cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
    bin/story-server vision
    until curl -sf http://127.0.0.1:8177/v1/models > /dev/null; do sleep 15; done

A plain run:

    %(py)s bin/ltx-movie "%(narrative)s" --story-id my-first-story --panels 4 --model %(model)s --story-server-stop-after-story

A run seeded from an image:

    %(py)s bin/ltx-movie "%(narrative)s" --story-id my-seeded-story --panels 4 --seed-image generated/hw_gate_seeds/portrait.png --model %(model)s --story-server-stop-after-story

## 5. Warnings

- The code's `--model` default for ltx-movie is `MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8`, an ltx-2.3 model that is NOT shipped. Always pass `--model %(model)s`.
- `--seed-image` takes an image path. `--image-seed` is a different flag that takes an integer.
- Restart the story server (`bin/story-server vision`) before every run: `--story-server-stop-after-story` stops it after each run's story phase.
- Keep swap under 3 GiB before a run (check `sysctl -n vm.swapusage`). Swap drains at about 32 MB/min, and `purge` does not help.

## 6. Troubleshooting

- `~/.qwen-serve-guard/stand-down` makes Phase 1 exit 2 without probing port 8177 (a known open bug). Report it; do not delete it blindly.

## 7. Not included

- Text-mode story generation (MTPLX 27B) and the 27B fallback model.
- ltx-2.3 models and the Gemma-3-12B text encoder.
- Path re-pinning: the target must have the same account and home.
"""


def render_readme(ctx):
    pid = ctx.package_id
    lines = []
    for cid in COMPONENT_ORDER:
        row = ctx.comp_stats.get(cid) or {"slug": SLUGS[cid], "files": 0, "symlinks": 0, "dirs": 0, "bytes": 0}
        lines.append("- %s %s: %d files, %d symlinks, %d dirs, %.2f GiB"
                     % (cid, row["slug"], row["files"], row["symlinks"], row["dirs"], row["bytes"] / 1024.0 ** 3))
    values = {
        "package_id": pid,
        "build_date": "%s-%s-%s" % (pid[-8:-4], pid[-4:-2], pid[-2:]),
        "head": ctx.git_record.get("head", ""),
        "branch": ctx.git_record.get("branch", ""),
        "component_lines": "\n".join(lines),
        "inst": "/usr/bin/python3 %s/%s/scripts/deploy/install_pkg.py" % (ctx.usb_root, pid),
        "py": README_PY,
        "model": LTX25_LITERAL,
        "narrative": README_NARRATIVE,
    }
    return README_TEMPLATE % values


# ---------------------------------------------------------------------------
# Root files, copy stage, post-copy stage (spec 9, 11)
# ---------------------------------------------------------------------------
def root_file_contents(ctx):
    def as_json(obj):
        return (json.dumps(obj, indent=2) + "\n").encode("utf-8")
    files = collections.OrderedDict()
    files["README.md"] = (render_readme(ctx).encode("utf-8"), 0o644)
    files["manifests/source-host.json"] = (as_json(ctx.host), 0o644)
    for rel, argv in freeze_commands():
        files[rel] = (ctx.freezes.get(rel, "").encode("utf-8"), 0o644)
    files["manifests/source-git.json"] = (as_json(ctx.git_record), 0o644)
    files["manifests/acceptance-baseline.json"] = (as_json(ctx.baseline), 0o644)
    files["manifests/credential-scan.json"] = (as_json(credential_scan_doc(ctx)), 0o644)
    for name in DEPLOY_SCRIPT_FILES:
        files["scripts/deploy/" + name] = (ctx.script_bytes[name], 0o755 if name.endswith(".py") else 0o644)
    return files


def write_root_files(ctx):
    ctx.root_files = collections.OrderedDict()
    for rel, (data, mode) in root_file_contents(ctx).items():
        ctx.root_files[rel] = write_package_file(ctx, rel, data, mode)


def open_package_root(ctx):
    root = ctx.package_root
    if not ctx.resume:
        os.mkdir(root)
        return
    failed = root + "/BUILD-FAILED.json"
    if os.path.lexists(failed):
        os.unlink(failed)
    partial = root + "/MANIFEST-ENTRIES.jsonl.partial"
    if ctx.resume_rename:
        os.replace(root + "/MANIFEST-ENTRIES.jsonl", partial)
    if os.path.exists(partial):
        os.truncate(partial, ctx.resume_keep_bytes)
    if ctx.resume_prefix_len < len(ctx.entries):
        entry = ctx.entries[ctx.resume_prefix_len]
        if "p" in entry:
            dst = root + "/" + entry["p"]
            if os.path.lexists(dst) and not (os.path.isdir(dst) and not os.path.islink(dst)):
                os.unlink(dst)


def copy_entry(ctx, entry):
    dst = ctx.package_root + "/" + entry["p"]
    if entry["k"] == "f":
        entry["h"] = copy_regular_file(entry["_src"], dst, entry, ctx.secrets)
    elif entry["k"] == "l":
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.lexists(dst):
            os.unlink(dst)
        os.symlink(entry["l"], dst)
    else:
        os.makedirs(dst, exist_ok=True)


def chmod_component_dirs(ctx, cid):
    for entry in ctx.entries:
        if entry["c"] == cid and entry["k"] == "d" and "p" in entry:
            os.chmod(ctx.package_root + "/" + entry["p"], int(entry["m"], 8))


def flush_partial(ctx):
    ctx.partial_fh.flush()
    os.fsync(ctx.partial_fh.fileno())


def copy_payload(ctx):
    ctx.partial_fh = open(ctx.package_root + "/MANIFEST-ENTRIES.jsonl.partial", "ab")
    last_index = {}
    for index, entry in enumerate(ctx.entries):
        last_index[entry["c"]] = index
    start = ctx.resume_prefix_len
    for cid in COMPONENT_ORDER:
        if cid in last_index and last_index[cid] < start:
            chmod_component_dirs(ctx, cid)
    since_sync = 0
    for index in range(start, len(ctx.entries)):
        entry = ctx.entries[index]
        if "p" in entry:
            CTX_STATE["payload_started"] = True
            copy_entry(ctx, entry)
        line = entry_line(entry).encode("utf-8")
        l3_check_bytes(ctx.secrets, line, "MANIFEST-ENTRIES.jsonl")
        ctx.partial_fh.write(line)
        since_sync += 1
        component_end = last_index[entry["c"]] == index
        if since_sync >= 512 or component_end:
            flush_partial(ctx)
            since_sync = 0
        if component_end:
            chmod_component_dirs(ctx, entry["c"])
        HOOKS["after_entry"](index)


def build_stage(ctx):
    """Stage steps 6-8. Any exception here is a copy-stage abort (exit 5)."""
    open_package_root(ctx)
    write_root_files(ctx)
    copy_payload(ctx)


def abort_copy_stage(ctx, exc):
    fh = ctx.partial_fh
    if fh is not None and not fh.closed:
        try:
            fh.flush()
            os.fsync(fh.fileno())
            fh.close()
        except OSError:
            pass
    print(safe_line(ctx, "build_pkg: COPY ABORTED (%s): %s" % (type(exc).__name__, exc),
                    "build_pkg: COPY ABORTED (%s): (error text withheld: it contained secret material)" % type(exc).__name__),
          file=sys.stderr)
    print("build_pkg: no MANIFEST.json was written; fix the cause, then rerun with --apply --resume --package-id %s"
          % ctx.package_id, file=sys.stderr)
    return 5


def finalize_entries(ctx):
    flush_partial(ctx)
    ctx.partial_fh.close()
    os.replace(ctx.package_root + "/MANIFEST-ENTRIES.jsonl.partial", ctx.package_root + "/MANIFEST-ENTRIES.jsonl")
    fsync_dir(ctx.package_root)


def check_a1_consistency(ctx):
    records = {}
    records.update(ctx.git_record.get("pipeline_files", {}))
    records.update(ctx.git_record.get("test_files", {}))
    for entry in ctx.entries:
        if entry["c"] == "A1" and entry["k"] == "f":
            record = records.get(entry["_rel"])
            if record is None or record["sha256"] != entry.get("h"):
                raise ValueError("PC3: A1 file %s was copied with a sha256 that differs from the provenance record"
                                 % entry["_rel"])


def manifest_doc(ctx):
    stats = component_stats(ctx.entries)
    return {
        "schema_version": SCHEMA_VERSION,
        "package_id": ctx.package_id,
        "created_at": iso_now(),
        "entries_file": "MANIFEST-ENTRIES.jsonl",
        "entries_sha256": ctx.entries_sha256,
        "entries_count": len(ctx.entries),
        "totals": stats_totals(stats),
        "components": stats,
        "root_files": ctx.root_files,
        "source_git_head": ctx.git_record.get("head", ""),
        "models": {"video_model_path": ltx25_model_path(), "vision_model_snapshot": HF_PINS["H4"][1],
                   "vision_model_symlink": home() + "/mlx_models/qwen3-vl"},
        "credential_scan": {"l1": "clean", "l2_allowlisted": len(ctx.l2_allowed),
                            "l3_values_loaded": len(ctx.secrets), "l4": "clean"},
        "build": {"started_at": ctx.started_at, "finished_at": iso_now(), "resumed": ctx.resume},
    }


def write_manifest(ctx):
    data = (json.dumps(manifest_doc(ctx), indent=2) + "\n").encode("utf-8")
    write_package_file(ctx, "MANIFEST.json", data, 0o644)


def fail_post_copy(ctx, step, exc):
    error = str(exc)
    doc = {"schema_version": SCHEMA_VERSION, "package_id": ctx.package_id, "failed_step": step,
           "error_type": type(exc).__name__, "error": error, "created_at": iso_now()}
    if has_secret(ctx, error):
        doc["error"] = "error text withheld: it contained secret material"
    data = (json.dumps(doc, indent=2) + "\n").encode("utf-8")
    manifest = ctx.package_root + "/MANIFEST.json"
    if os.path.lexists(manifest):
        os.unlink(manifest)
    try:
        write_package_file(ctx, "BUILD-FAILED.json", data, 0o644)
    except Exception as write_exc:
        print(safe_line(ctx, "build_pkg: could not write BUILD-FAILED.json: %s" % write_exc,
                        "build_pkg: could not write BUILD-FAILED.json (%s): (error text withheld: it contained secret material)"
                        % type(write_exc).__name__), file=sys.stderr)
    print(safe_line(ctx, "build_pkg: POST-COPY FAILURE at %s (%s): %s" % (step, doc["error_type"], error),
                    "build_pkg: POST-COPY FAILURE at %s (%s): (error text withheld: it contained secret material)"
                    % (step, doc["error_type"])), file=sys.stderr)
    print("build_pkg: BUILD-FAILED.json written; no MANIFEST.json. Fix the cause, then rerun with --apply --resume --package-id %s"
          % ctx.package_id, file=sys.stderr)
    return 3


def finish_build(ctx):
    step = "PC1"
    try:
        finalize_entries(ctx)
        step = "PC2"
        ctx.entries_sha256 = sha256_file(ctx.package_root + "/MANIFEST-ENTRIES.jsonl")
        step = "PC3"
        check_a1_consistency(ctx)
        step = "PC4"
        l4_rescan(ctx)
        step = "PC5"
        write_manifest(ctx)
    except Exception as exc:
        return fail_post_copy(ctx, step, exc)
    total = sum(e["b"] for e in ctx.entries if e["k"] == "f")
    print("build_pkg: BUILD OK: %s (%d entries, %d bytes)" % (ctx.package_root, len(ctx.entries), total))
    return 0


def print_prebuild_report(ctx, results):
    gib = 1024.0 ** 3
    for cid in COMPONENT_ORDER:
        row = ctx.comp_stats[cid]
        print("%s %s files=%d symlinks=%d dirs=%d bytes=%d (%.2f GiB)"
              % (cid, row["slug"], row["files"], row["symlinks"], row["dirs"], row["bytes"], row["bytes"] / gib))
    totals = stats_totals(ctx.comp_stats)
    print("TOTAL files=%d symlinks=%d dirs=%d bytes=%d (%.2f GiB)"
          % (totals["files"], totals["symlinks"], totals["dirs"], totals["bytes"], totals["bytes"] / gib))
    print("SPACE required=%d (%.2f GiB) free=%d (%.2f GiB)"
          % (ctx.required_bytes, ctx.required_bytes / gib, ctx.free_bytes, ctx.free_bytes / gib))
    for result in results:
        line = format_result(result)
        data = line.encode("utf-8")
        if KnownSecretScanner(ctx.secrets).feed(data) or l2_scan_bytes(data):
            line = "%s %s (message withheld: it contained secret material)" % (line.split(" ", 1)[0], result.check_id)
        print(line)


def cmd_build(args):
    ctx = BuildCtx(args)
    try:
        ctx.started_at = iso_now()
        ctx.secrets, ctx.l3_sources, ctx.l3_errors = load_known_secrets()
        enumerate_components(ctx)
        results = run_prebuild_checks(ctx)
    except Exception:
        traceback.print_exc()
        print("build_pkg: UNEXPECTED ERROR before any write", file=sys.stderr)
        return 1
    print_prebuild_report(ctx, results)
    fatal = [r for r in results if r.fatal and not r.ok]
    if not ctx.apply:
        if fatal:
            print("build_pkg: DRY RUN FAILED (%d checks)" % len(fatal))
            return 4
        print("build_pkg: DRY RUN OK")
        return 0
    if fatal:
        print("build_pkg: APPLY REFUSED (%d checks); the package root was not created" % len(fatal))
        return 4
    try:
        build_stage(ctx)
    except Exception as exc:
        return abort_copy_stage(ctx, exc)
    return finish_build(ctx)


# ---------------------------------------------------------------------------
# --verify-only (spec 11.4): re-verify a finished package; writes nothing
# ---------------------------------------------------------------------------
def verify_package(root):
    failures = []
    manifest_path = root + "/MANIFEST.json"
    try:
        with open(manifest_path, "rb") as fh:
            manifest = json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError):
        return [("manifest missing or unreadable", manifest_path)], 0
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        return [("manifest is not schema_version %d" % SCHEMA_VERSION, manifest_path)], 0
    if os.path.lexists(root + "/BUILD-FAILED.json"):
        failures.append(("build failed marker present", root + "/BUILD-FAILED.json"))
    entries_path = root + "/" + manifest.get("entries_file", "MANIFEST-ENTRIES.jsonl")
    try:
        entries_sha = sha256_file(entries_path, nocache=True)
        entries = read_entries(entries_path)
    except (OSError, ValueError):
        failures.append(("entries file unreadable", entries_path))
        return failures, 0
    if entries_sha != manifest.get("entries_sha256"):
        failures.append(("entries sha256 mismatch", entries_path))
    root_files = manifest.get("root_files", {})
    for rel in sorted(root_files):
        path = root + "/" + rel
        try:
            got = sha256_file(path, nocache=True)
        except OSError:
            got = None
        if got != root_files[rel]:
            failures.append(("root file hash mismatch", path))
    listed = set()
    nfiles = 0
    for entry in entries:
        if "p" not in entry:
            continue
        path = root + "/" + entry["p"]
        listed.add(entry["p"])
        try:
            st = os.lstat(path)
        except OSError:
            failures.append(("missing", path))
            continue
        if entry["k"] == "f":
            if not stat.S_ISREG(st.st_mode):
                failures.append(("not a regular file", path))
            elif st.st_size != entry["b"]:
                failures.append(("size mismatch", path))
            else:
                nfiles += 1
                if sha256_file(path, nocache=True) != entry["h"]:
                    failures.append(("hash mismatch", path))
        elif entry["k"] == "l":
            if not stat.S_ISLNK(st.st_mode) or os.readlink(path) != entry["l"]:
                failures.append(("symlink mismatch", path))
        elif not stat.S_ISDIR(st.st_mode):
            failures.append(("dir missing", path))
    if os.path.isdir(root + "/payload"):
        for rel, st in list_tree(root + "/payload"):
            if not stat.S_ISDIR(st.st_mode) and ("payload/" + rel) not in listed:
                failures.append(("extra", root + "/payload/" + rel))
    allow_path = root + "/scripts/deploy/credential_allowlist.json"
    try:
        allow, _ = load_allowlist(allow_path)
    except (OSError, ValueError):
        failures.append(("allowlist unreadable", allow_path))
        allow = set()
    scan_failures, _ = scan_package(root, allow)
    for item in scan_failures:
        failures.append(("credential scan", item))
    return failures, nfiles


def cmd_verify_only(args):
    usb_root = os.path.abspath(args.usb_root if args.usb_root else USB_ROOT_DEFAULT)
    package_id = args.package_id if args.package_id else default_package_id()
    root = os.path.join(usb_root, package_id)
    failures, nfiles = verify_package(root)
    secrets = load_known_secrets()[0]
    for reason, path in failures:
        line = "FAIL VERIFY %s: %s" % (reason, path)
        data = line.encode("utf-8")
        if KnownSecretScanner(secrets).feed(data) or l2_scan_bytes(data):
            line = "FAIL VERIFY %s: (path withheld: it contained secret material)" % reason
        print(line)
    if failures:
        print("build_pkg: VERIFY FAILED: %d problem(s) in %s" % (len(failures), root))
        return 1
    print("build_pkg: VERIFY ok: %d files re-hashed" % nfiles)
    return 0


# ---- CLI entry point ----


def main(argv=None):
    args = parse_args(argv)
    CTX_STATE["payload_started"] = False
    try:
        if args.verify_only:
            return cmd_verify_only(args)
        if args.credential_report:
            return cmd_credential_report(args)
        return cmd_build(args)
    finally:
        CTX_STATE["payload_started"] = False


if __name__ == "__main__":
    sys.exit(main())
