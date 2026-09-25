#!/usr/bin/env python3
"""tests/test_deploy_pkg.py -- unit tests for scripts/deploy/{build_pkg,install_pkg}.py.

Spec: docs/superpowers/specs/2026-09-25-ltx-chain-deploy-package-design.md (section 15)

Run both ways (the counts differ by design):
    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -q tests/test_deploy_pkg.py
    /usr/bin/python3 tests/test_deploy_pkg.py

unittest.TestCase classes with real assertions; never imports pytest; Python
3.9 language level. setUp replaces every HOOKS entry with a fake that raises,
so no test can touch the real system. Secret and pattern canaries and the
forbidden README strings are built by concatenation, so this file never holds
a matching literal.
"""
import ast
import collections
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

DEPLOY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "scripts", "deploy")


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(DEPLOY_DIR, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bp = load_module("build_pkg", "build_pkg.py")
HOOKED_MODULES = [bp]

FIXED_NOW = time.gmtime(1790000000)
SECRET_CANARY = "Lx3." + "k9Qm2vR7" + "Tz5.Wp8N"   # 20 bytes; the "." keeps every L2 pattern from matching
GITHUB_CANARY = "gh" + "p_" + "A" * 36


def unfaked(name):
    def hook(*args, **kwargs):
        raise AssertionError("unfaked hook %s" % name)
    return hook


def run_main(func, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = func(argv)
        except SystemExit as exc:
            rc = exc.code
    return rc, out.getvalue(), err.getvalue()


def write_file(path, data=b"x", mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    os.chmod(path, mode)


def make_link(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.symlink(value, path)


def file_sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def snapshot(root):
    """path -> (kind, mode, size, mtime_ns, link value, sha256) for everything under root."""
    snap = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = os.path.join(dirpath, name)
            st = os.lstat(path)
            if stat.S_ISLNK(st.st_mode):
                snap[path] = ("l", None, None, None, os.readlink(path), None)
            elif stat.S_ISDIR(st.st_mode):
                snap[path] = ("d", stat.S_IMODE(st.st_mode), None, st.st_mtime_ns, None, None)
            else:
                snap[path] = ("f", stat.S_IMODE(st.st_mode), st.st_size, st.st_mtime_ns, None, file_sha256(path))
    return snap


def payload_snapshot(pkg_root):
    """Relative view of payload/ for byte-identity (spec 11.3): file bytes, mode and
    mtime_ns; symlink values; directory modes. Directory mtimes are excluded."""
    snap = {}
    base = pkg_root + "/payload"
    for dirpath, dirnames, filenames in os.walk(base):
        for name in dirnames + filenames:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, base)
            st = os.lstat(path)
            if stat.S_ISLNK(st.st_mode):
                snap[rel] = ("l", os.readlink(path))
            elif stat.S_ISDIR(st.st_mode):
                snap[rel] = ("d", stat.S_IMODE(st.st_mode))
            else:
                snap[rel] = ("f", stat.S_IMODE(st.st_mode), st.st_mtime_ns, file_sha256(path))
    return snap


class DeployTestCase(unittest.TestCase):
    def setUp(self):
        for module in HOOKED_MODULES:
            fakes = dict((name, unfaked(name)) for name in list(module.HOOKS))
            patcher = mock.patch.dict(module.HOOKS, fakes)
            patcher.start()
            self.addCleanup(patcher.stop)
        bp.CTX_STATE["payload_started"] = False


class TestLanguageLevel(DeployTestCase):
    def test_T95_scripts_parse_at_python_3_9(self):
        names = sorted(n for n in os.listdir(DEPLOY_DIR) if n.endswith(".py"))
        self.assertIn("build_pkg.py", names)
        for name in names:
            with open(os.path.join(DEPLOY_DIR, name), "rb") as fh:
                source = fh.read().decode("utf-8")
            ast.parse(source, filename=name, feature_version=(3, 9))


class TestPrimitives(DeployTestCase):
    def setUp(self):
        DeployTestCase.setUp(self)
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="deploypkg-prim-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        bp.HOOKS["after_chunk"] = lambda src, nbytes: None

    def make_src(self, data):
        src = self.tmp + "/src/file.bin"
        write_file(src, data, 0o640)
        os.utime(src, ns=(1700000000123456789, 1700000000123456789))
        st = os.lstat(src)
        entry = {"k": "f", "b": st.st_size, "m": "%04o" % stat.S_IMODE(st.st_mode), "mt": st.st_mtime_ns}
        return src, entry

    def test_constants_verbatim(self):
        self.assertEqual(bp.SCHEMA_VERSION, 4)
        self.assertEqual(bp.CHUNK_SIZE, 8 * 1024 * 1024)
        self.assertEqual(bp.L2_MAX_BYTES, 4 * 1024 * 1024)
        self.assertEqual(bp.MIN_MEMSIZE_BYTES, 51539607552)
        self.assertEqual(bp.BUILD_HEADROOM_BYTES, 5 * 1024 ** 3)
        self.assertEqual(bp.INSTALL_HEADROOM_BYTES, 10 * 1024 ** 3)
        self.assertEqual(bp.STORY_PORT, 8177)
        self.assertEqual((bp.REQUIRED_USER, bp.REQUIRED_HOME), ("reubenpatterson", "/Users/reubenpatterson"))
        self.assertEqual(bp.FRAMEWORK_ROOT, "/Library/Frameworks/Python.framework")
        self.assertEqual(bp.USR_LOCAL_BIN, "/usr/local/bin")
        self.assertEqual(bp.VOLUMES_ROOT, "/Volumes")
        self.assertEqual(bp.FALCONSAI_USB_HUB, "/Volumes/Ollama/hf_home/hub")
        self.assertEqual(bp.BREW_BIN, "/opt/homebrew/bin/brew")
        self.assertEqual(bp.BREW_PY312, "/opt/homebrew/opt/python@3.12/bin/python3.12")
        self.assertEqual(bp.USB_ROOT_DEFAULT, "/Volumes/Ollama")
        self.assertEqual(sorted(bp.HOOKS), sorted(["run", "ismount", "diskutil_personality", "statvfs_free", "port_free", "which", "geteuid", "getpwnam", "getuser", "now_utc", "after_chunk", "after_entry", "http_ok", "sleep"]))

    def test_T06a_entry_line_key_order_and_separators(self):
        link = {"s": True, "l": "x", "t": "/a", "c": "H5", "k": "l", "_src": "/ignored"}
        self.assertEqual(bp.entry_line(link), '{"k":"l","c":"H5","t":"/a","l":"x","s":true}\n')
        f = {"mt": 5, "h": "ab", "m": "0644", "b": 3, "t": "/t", "p": "payload/A1-workspace-code/x", "c": "A1", "k": "f", "_rel": "x"}
        self.assertEqual(bp.entry_line(f), '{"k":"f","c":"A1","p":"payload/A1-workspace-code/x","t":"/t","b":3,"m":"0644","h":"ab","mt":5}\n')
        path = self.tmp + "/e.jsonl"
        write_file(path, (bp.entry_line(link) + "\n" + bp.entry_line(f)).encode("utf-8"))
        self.assertEqual(bp.read_entries(path), [{"k": "l", "c": "H5", "t": "/a", "l": "x", "s": True}, {"k": "f", "c": "A1", "p": "payload/A1-workspace-code/x", "t": "/t", "b": 3, "m": "0644", "h": "ab", "mt": 5}])

    def test_format_result_and_last_line(self):
        self.assertEqual(bp.format_result(bp.CheckResult("B01", True, "ok", True)), "PASS B01 ok")
        self.assertEqual(bp.format_result(bp.CheckResult("B01", False, "bad", True)), "FAIL B01 bad")
        self.assertEqual(bp.format_result(bp.CheckResult("B13", False, "stale", False)), "WARN B13 stale")
        self.assertEqual(bp.format_result(bp.CheckResult("I20", True, bp.PENDING_PREFIX + "later", True)), "PENDING I20 later")
        self.assertEqual(bp.last_line("a\nOK 3/3\n\n"), "OK 3/3")
        self.assertEqual(bp.last_line(""), "")

    def test_scanner_finds_secret_across_chunk_boundary(self):
        secret = SECRET_CANARY.encode("ascii")
        data = b"a" * 50 + secret + b"b" * 50
        chunks = [data[i:i + 64] for i in range(0, len(data), 64)]
        scanner = bp.KnownSecretScanner([secret])
        self.assertEqual([scanner.feed(c) for c in chunks], [False, True])
        self.assertNotIn(SECRET_CANARY, repr(scanner))
        self.assertEqual(repr(scanner), "<KnownSecretScanner values=1>")
        self.assertFalse(bp.KnownSecretScanner([]).feed(data))

    def test_write_package_file_is_atomic_and_l3_scanned(self):
        ctx = types.SimpleNamespace(package_root=self.tmp + "/pkg", secrets=[SECRET_CANARY.encode("ascii")])
        os.makedirs(ctx.package_root)
        digest = bp.write_package_file(ctx, "manifests/a.json", b'{"a": 1}\n', 0o644)
        self.assertEqual(digest, hashlib.sha256(b'{"a": 1}\n').hexdigest())
        self.assertEqual(sorted(os.listdir(ctx.package_root + "/manifests")), ["a.json"])
        self.assertEqual(stat.S_IMODE(os.lstat(ctx.package_root + "/manifests/a.json").st_mode), 0o644)
        with self.assertRaises(bp.CredentialLeak) as cm:
            bp.write_package_file(ctx, "manifests/b.json", b"x" + SECRET_CANARY.encode("ascii"), 0o644)
        self.assertIn("manifests/b.json", str(cm.exception))
        self.assertNotIn(SECRET_CANARY, str(cm.exception))
        self.assertEqual(sorted(os.listdir(ctx.package_root + "/manifests")), ["a.json"])

    def test_T30a_copy_preserves_bytes_mode_mtime(self):
        data = os.urandom(1000)
        src, entry = self.make_src(data)
        dst = self.tmp + "/pkg/payload/X/file.bin"
        with mock.patch.object(bp, "CHUNK_SIZE", 64):
            digest = bp.copy_regular_file(src, dst, entry, [])
        self.assertEqual(digest, hashlib.sha256(data).hexdigest())
        with open(dst, "rb") as fh:
            self.assertEqual(fh.read(), data)
        st = os.lstat(dst)
        self.assertEqual(stat.S_IMODE(st.st_mode), 0o640)
        self.assertEqual(st.st_mtime_ns, entry["mt"])

    def test_T31a_append_mid_copy_raises_mid_copy(self):
        src, entry = self.make_src(b"x" * 200)
        dst = self.tmp + "/pkg/payload/X/file.bin"
        state = {"done": False}

        def after_chunk(path, nbytes):
            if not state["done"]:
                state["done"] = True
                with open(path, "ab") as fh:
                    fh.write(b"appended")
        bp.HOOKS["after_chunk"] = after_chunk
        with mock.patch.object(bp, "CHUNK_SIZE", 64):
            with self.assertRaises(bp.SourceChanged) as cm:
                bp.copy_regular_file(src, dst, entry, [])
        self.assertEqual(str(cm.exception), "source changed mid-copy: " + src)
        self.assertFalse(os.path.lexists(dst))

    def test_T31b_same_size_rewrite_mid_copy_raises_mid_copy(self):
        src, entry = self.make_src(b"x" * 200)
        dst = self.tmp + "/pkg/payload/X/file.bin"
        state = {"done": False}

        def after_chunk(path, nbytes):
            if not state["done"]:
                state["done"] = True
                fd = os.open(path, os.O_WRONLY)
                os.pwrite(fd, b"Y", 150)
                os.close(fd)
                os.utime(path, ns=(entry["mt"] + 1000, entry["mt"] + 1000))
        bp.HOOKS["after_chunk"] = after_chunk
        with mock.patch.object(bp, "CHUNK_SIZE", 64):
            with self.assertRaises(bp.SourceChanged) as cm:
                bp.copy_regular_file(src, dst, entry, [])
        self.assertEqual(str(cm.exception), "source changed mid-copy: " + src)
        self.assertFalse(os.path.lexists(dst))

    def test_T32a_changed_since_enumeration(self):
        src, entry = self.make_src(b"x" * 200)
        write_file(src, b"x" * 201, 0o640)
        with self.assertRaises(bp.SourceChanged) as cm:
            bp.copy_regular_file(src, self.tmp + "/pkg/payload/X/file.bin", entry, [])
        self.assertEqual(str(cm.exception), "source changed since enumeration: " + src)

    def test_T13a_known_secret_in_copy_deletes_partial_dst(self):
        secret = SECRET_CANARY.encode("ascii")
        src, entry = self.make_src(b"a" * 50 + secret + b"b" * 50)
        dst = self.tmp + "/pkg/payload/X/file.bin"
        with mock.patch.object(bp, "CHUNK_SIZE", 64):
            with self.assertRaises(bp.CredentialLeak) as cm:
                bp.copy_regular_file(src, dst, entry, [secret])
        self.assertIn(src, str(cm.exception))
        self.assertNotIn(SECRET_CANARY, str(cm.exception))
        self.assertFalse(os.path.lexists(dst))


if __name__ == "__main__":
    unittest.main()
