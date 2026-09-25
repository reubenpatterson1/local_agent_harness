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
