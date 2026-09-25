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


PIPELINE = ("z_image_skill.py", "ltx2_mlx_video_skill.py", "ltx_image_fit.py", "content_safety.py",
            "bin/ltx-movie", "bin/ltx-story-images", "bin/ltx-story-manifest", "bin/ltx-mlx-render",
            "bin/story-server", "bin/qwen-agent")
TESTS7 = ("tests/test_ltx_movie_offline.py", "tests/test_ltx_mlx_render.py", "tests/test_ltx_story_images.py",
          "tests/test_ltx2_mlx_video_skill.py", "tests/test_ltx_image_fit.py",
          "tests/test_ltx_story_manifest_chain.py", "tests/check_ltx2_mlx_no_forbidden_imports.py")
LEGACY = ("ltx_video_skill.py", "mps_guard.py", "flux_skill.py", "bin/ltx-chain", "bin/ltx-generate",
          "bin/ltx-host-prep", "bin/ltx-host-restore", "bin/ltx-story-video", "bin/pad-images", "start_vllm.sh")
PACK28 = (".gitattributes", "LICENSE", "README.md", "audio_vae.safetensors", "chat_template.jinja",
          "connector.safetensors", "duration_head.safetensors", "embedded_config.json", "generation_config.json",
          "ltx-2.5-22b-distilled-lora-450-bf16.safetensors", "processor_config.json", "quantize_config.json",
          "spatial_upscaler_x2_v1_0.safetensors", "spatial_upscaler_x2_v1_0_config.json", "split_model.json",
          "temporal_upscaler_x2_v1_0.safetensors", "temporal_upscaler_x2_v1_0_config.json",
          "text_encoder.safetensors", "text_encoder_config.json", "tokenizer.json", "tokenizer_config.json",
          "transformer-dev.safetensors", "transformer-distilled.safetensors", "vae_decoder_av.safetensors",
          "vae_decoder_conv.safetensors", "vae_encoder_av.safetensors", "vae_encoder_conv.safetensors",
          "vocoder.safetensors")
BIN_LINKS13 = ("idle3", "idle3.13", "pip3", "pip3.13", "pydoc3", "pydoc3.13", "python3", "python3-config",
               "python3-intel64", "python3.13", "python3.13-config", "python3.13-intel64", "python")
PINS = {
    "H1": ("models--Tongyi-MAI--Z-Image-Turbo", "f332072aa78be7aecdf3ee76d5c247082da564a6"),
    "H2": ("models--BennyDaBall--Qwen3-4b-Z-Image-Turbo-AbliteratedV1", "ce497d288a7ddfd5d0f337c7139349d5d0236bfa"),
    "H3": ("models--Falconsai--nsfw_image_detection", "96cb0d0342c7afb80cab76ecc58b265fa44da256"),
    "H4": ("models--divinetribe--Huihui-Qwen3-VL-32B-Instruct-abliterated-4bit-mlx", "5428d6aaca0103a1e32f47261a20fecaa47700ec"),
}
ORDER = ("A1", "A2", "B1", "B2", "B3", "B4", "B5", "D1", "F1", "F2", "F3", "H0", "H1", "H2", "H3", "H4", "H5")
HEAD_SHA = "6ab72ac3f29e8d68e06095574bcbd97d8f621240"
VLLM_OUT = ("INFO 09-25 07:36:25 [__init__.py:52] Available plugins for group vllm.platform_plugins:\n"
            "INFO 09-25 07:36:27 [__init__.py:237] Platform plugin metal is activated\n0.27.1\n")
GATE_OUT = {"G1": "OK 118/118", "G2": "OK 431/431", "G3": "OK 98/98", "G4": "OK 138/138",
            "G5": "OK 73/73", "G6": "OK 32/32", "G7": "RESULT: ok"}
GATE_ARGV = {"G1": "tests/test_ltx_movie_offline.py", "G2": "tests/test_ltx_mlx_render.py",
             "G3": "tests/test_ltx_story_images.py", "G4": "tests/test_ltx2_mlx_video_skill.py",
             "G5": "tests/test_ltx_image_fit.py", "G6": "tests/test_ltx_story_manifest_chain.py",
             "G7": "tests/check_ltx2_mlx_no_forbidden_imports.py"}
X2_ARGV = ("bin/ltx-movie", "a test narrative", "--story-id", "deploy-gate-dry", "--dry-run", "--no-review",
           "--model", "/Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8")
GEOMS = {"portrait": (320, 576, 320, 576), "wide": (960, 320, 960, 320),
         "square": (512, 512, 512, 512), "noseed": (704, 448, 1408, 896)}


def git_blob(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _under_path(path, root):
    return path == root or path.startswith(root + "/")


class FixtureRun(object):
    """Fake HOOKS["run"]: argv-keyed responses for every command build_pkg and install_pkg issue."""

    def __init__(self, fx):
        self.fx = fx
        self.overrides = {}
        self.calls = []
        self.kwcalls = []
        self.memsize = "68719476736"
        self.fw_version = "3.13.0"
        self.zsh_hf_home = None
        self.freeze_text = "pkg==1.0\n"
        self.media_overrides = {}

    def __call__(self, argv, timeout=120, env=None, cwd=None):
        key = tuple(argv)
        self.calls.append(key)
        self.kwcalls.append((key, timeout, cwd))
        self.fx.events.append(("run", key))
        if key in self.overrides:
            value = self.overrides[key]
            return value(key) if callable(value) else value
        if key and key[0] == bp.GIT:
            return self.git(key)
        table = self.table()
        if key in table:
            return table[key]
        if key and key[0] in (self.fx.ffprobe, self.fx.ffmpeg) and len(key) > 2:
            return self.media(key)
        raise AssertionError("unfaked run argv %r" % (key,))

    def table(self):
        fx = self.fx
        t = {
            ("/usr/sbin/sysctl", "-n", "hw.model"): (0, "Mac16,9\n"),
            ("/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"): (0, "Apple M4 Max\n"),
            ("/usr/sbin/sysctl", "-n", "hw.memsize"): (0, self.memsize + "\n"),
            ("/usr/bin/sw_vers", "-productVersion"): (0, "26.0\n"),
            ("/usr/bin/sw_vers", "-buildVersion"): (0, "25A100\n"),
            (fx.fw_py, "-c", "import sys;print(sys.version.split()[0])"): (0, self.fw_version + "\n"),
            (fx.ffmpeg, "-version"): (0, "ffmpeg version 9.0.1 Copyright (c) 2000-2026 the FFmpeg developers\nbuilt with Apple clang\n"),
            (fx.ffprobe, "-version"): (0, "ffprobe version 9.0.1 Copyright (c) 2007-2026 the FFmpeg developers\n"),
            (fx.brew_bin, "--version"): (0, "Homebrew 5.0.0\n"),
            (fx.brew_py312, "--version"): (0, "Python 3.12.9\n"),
            (fx.vllm_py, "-c", "import vllm; print(vllm.__version__)"): (0, VLLM_OUT),
            (fx.fw_py, "-m", "pip", "freeze", "--all", "--exclude", "fubotv-mcp-common", "--exclude", "student-agent-mcp"): (0, self.freeze_text),
            (fx.fw + "/Versions/3.13/bin/uv", "pip", "freeze", "--python", fx.home + "/ltx-2-mlx/.venv/bin/python"): (0, "ltx-core==0.15.4\n"),
            (fx.vllm_py, "-m", "pip", "freeze", "--all"): (0, "vllm==0.27.1\n"),
            (fx.fw_py, "bin/ltx-mlx-render", "--help"): (0, "usage: ltx-mlx-render [-h]\n"),
            (fx.fw_py,) + X2_ARGV: (0, "dry run: 2 panels\n"),
            ("/bin/zsh", "-c", 'printf "%s" "$HF_HOME"'): (0, self.zsh_hf_home if self.zsh_hf_home is not None else fx.home + "/hf_home"),
            (fx.fw_py, "-s", "-c", "import sys, psutil, pytest, pexpect; print(sys.version.split()[0])"): (0, "3.13.0\n"),
            (fx.fw_py, "-c", "import torch, diffusers, transformers, PIL, numpy, safetensors, psutil, pytest, pexpect"): (0, ""),
            (fx.vllm_py, "-c", "import vllm, vllm_metal, mlx_vlm; print(vllm.__version__)"): (0, VLLM_OUT.replace("07:36:2", "08:00:0")),
            (fx.home + "/ltx-2-mlx/.venv/bin/ltx-2-mlx", "--help"): (0, "usage: ltx-2-mlx [-h]\n"),
            (fx.ws + "/bin/story-server",): (2, "usage: story-server [vision|text|status|stop]\n"),
            (fx.ws + "/bin/story-server", "vision"): (0, ""),
            (fx.ws + "/bin/story-server", "stop"): (0, ""),
            ("/usr/bin/pgrep", "-fl", "ltx-2-mlx|z_image|mlx_lm|vllm"): (1, ""),
            ("/usr/sbin/sysctl", "-n", "vm.swapusage"): (0, "total = 2048.00M  used = 100.00M  free = 1948.00M  (encrypted)\n"),
        }
        for gid, rel in GATE_ARGV.items():
            t[(fx.fw_py, rel)] = (0, "running\n" + GATE_OUT[gid] + "\n")
        return t

    def git(self, key):
        fx = self.fx
        if key[1] != "-C" or key[2] != fx.repo:
            raise AssertionError("git must run as git -C <repo>: %r" % (key,))
        cmd = key[3:]
        if cmd == ("rev-parse", "HEAD"):
            return (0, HEAD_SHA + "\n")
        if cmd == ("rev-parse", "--abbrev-ref", "HEAD"):
            return (0, "ltx2-mlx-video-pipeline\n")
        if cmd == ("status", "--porcelain", "--", "qwen-agent-workspace"):
            return (0, "".join(" M %s\n" % rp for rp in sorted(fx.modified)))
        if cmd[:3] == ("ls-files", "--error-unmatch", "--"):
            rp = cmd[3]
            if rp in fx.untracked:
                return (1, "error: pathspec '%s' did not match any file(s) known to git\n" % rp)
            return (0, rp + "\n")
        if cmd[:3] == ("status", "--porcelain", "--"):
            rp = cmd[3]
            if rp in fx.untracked:
                return (0, "?? %s\n" % rp)
            return (0, " M %s\n" % rp) if rp in fx.modified else (0, "")
        if cmd[0] == "hash-object":
            with open(cmd[1], "rb") as fh:
                return (0, git_blob(fh.read()) + "\n")
        if cmd[0] == "rev-parse" and cmd[1].startswith("HEAD:"):
            rp = cmd[1][len("HEAD:"):]
            if rp in fx.untracked:
                return (128, "fatal: path '%s' does not exist in 'HEAD'\n" % rp)
            if rp in fx.committed:
                return (0, fx.committed[rp] + "\n")
            with open(fx.repo + "/" + rp, "rb") as fh:
                return (0, git_blob(fh.read()) + "\n")
        raise AssertionError("unfaked git argv %r" % (key,))

    def media(self, key):
        fx = self.fx
        path = key[-1] if key[0] == fx.ffprobe else key[key.index("-i") + 1]
        found = re.search(r"deploy-accept-(portrait|wide|square|noseed)-", path)
        label = found.group(1) if found else "portrait"
        width, height, still_w, still_h = GEOMS[label]
        media = self.media_overrides.get(label, {})
        if key[0] == fx.ffprobe:
            select = key[key.index("-select_streams") + 1]
            if path.endswith(".png"):
                stream = {"width": media.get("still_w", still_w), "height": media.get("still_h", still_h)}
            elif select == "a:0":
                stream = {"codec_name": media.get("audio", "aac")}
            else:
                stream = {"width": media.get("w", width), "height": media.get("h", height),
                          "codec_name": media.get("vcodec", "h264"), "nb_read_frames": media.get("frames", "290")}
            return (0, json.dumps({"streams": [stream]}) + "\n")
        default = ["0,0,0,1,6220800,ac2833aa09711810c612e6b20955113e"]
        rows = media.get("rows_seed" if path.endswith(".chainseed.png") else "rows_clip", default)
        return (0, "#format: frame checksums\n#version: 2\n" + "".join(row + "\n" for row in rows))


class Fixture(object):
    """A fake source host under one temp dir (Task 8's InstallFixture turns it into a fake target)."""

    def __init__(self, tc):
        self.tc = tc
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="deploypkg-"))
        tc.addCleanup(self.cleanup)
        self.home = self.root + "/Users/reubenpatterson"
        self.ws = self.home + "/local_model_harness/qwen-agent-workspace"
        self.repo = self.home + "/local_model_harness"
        self.fw = self.root + "/Library/Frameworks/Python.framework"
        self.ulb = self.root + "/usr/local/bin"
        self.volumes = self.root + "/Volumes"
        self.usb = self.volumes + "/USB"
        self.usb2 = self.volumes + "/USB2"
        self.usb_hub = self.usb + "/hf_home/hub"
        self.brew_bin = self.root + "/opt/homebrew/bin/brew"
        self.brew_py312 = self.root + "/opt/homebrew/opt/python@3.12/bin/python3.12"
        self.ffmpeg = self.root + "/opt/homebrew/bin/ffmpeg"
        self.ffprobe = self.root + "/opt/homebrew/bin/ffprobe"
        self.deploy = self.root + "/deploy"
        self.package_id = "ltx-chain-deploy-20260925"
        self.pkg = self.usb + "/" + self.package_id
        self.fw_py = self.fw + "/Versions/3.13/bin/python3"
        self.vllm_py = self.home + "/.venv-vllm-metal/bin/python"
        self.mounts = set([self.usb, self.usb2])
        self.untracked = set()
        self.modified = set()
        self.committed = {}
        self.events = []
        self.allowlist_entries = []
        self.run = FixtureRun(self)
        for path in (self.home, self.usb, self.usb2, self.deploy, self.ulb):
            os.makedirs(path)
        self.patch_build_module()

    def cleanup(self):
        for dirpath, dirnames, filenames in os.walk(self.root):
            for name in dirnames:
                path = os.path.join(dirpath, name)
                if not os.path.islink(path):
                    os.chmod(path, 0o755)
        shutil.rmtree(self.root, True)

    def patch_build_module(self):
        values = {"REQUIRED_HOME": self.home, "FRAMEWORK_ROOT": self.fw, "USR_LOCAL_BIN": self.ulb,
                  "VOLUMES_ROOT": self.volumes, "FALCONSAI_USB_HUB": self.usb_hub, "BREW_BIN": self.brew_bin,
                  "BREW_PY312": self.brew_py312, "USB_ROOT_DEFAULT": self.usb}
        patchers = [mock.patch.object(bp, name, value) for name, value in sorted(values.items())]
        patchers.append(mock.patch.object(bp, "deploy_dir", lambda: self.deploy))
        patchers.append(mock.patch.dict(os.environ, {"HOME": self.home}))
        for patcher in patchers:
            patcher.start()
            self.tc.addCleanup(patcher.stop)
        for name in ("HF_TOKEN", "HF_HOME", "Z_IMAGE_HF_HOME", "LTX2_MLX_HF_HOME", "HF_HUB_CACHE",
                     "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE"):
            os.environ.pop(name, None)

    def write_deploy_dir(self):
        for name in ("build_pkg.py", "install_pkg.py"):
            real = os.path.join(DEPLOY_DIR, name)
            if os.path.exists(real):
                with open(real, "rb") as fh:
                    data = fh.read()
            else:
                data = b"# install_pkg.py stand-in written by the test fixture before Task 8 exists\n"
            write_file(self.deploy + "/" + name, data, 0o755)
        self.write_allowlist()

    def write_allowlist(self, entries=None):
        if entries is not None:
            self.allowlist_entries = entries
        doc = {"schema_version": 1, "entries": self.allowlist_entries}
        write_file(self.deploy + "/credential_allowlist.json", (json.dumps(doc, indent=2) + "\n").encode("utf-8"))

    def make_repo(self, hub, repo, pin):
        root = hub + "/" + repo
        blob = hashlib.sha1(repo.encode("utf-8")).hexdigest()
        write_file(root + "/blobs/" + blob, ("weights for %s\n" % repo).encode("utf-8"))
        write_file(root + "/refs/main", pin.encode("ascii"))
        make_link(root + "/snapshots/" + pin + "/config.json", "../../blobs/" + blob)
        write_file(root + "/.DS_Store", b"ds")

    def build_sources(self):
        H, WS = self.home, self.ws
        for rel in PIPELINE + TESTS7:
            write_file(WS + "/" + rel, ("# fixture %s\n" % rel).encode("utf-8"), 0o755 if rel.startswith("bin/") else 0o644)
        for rel in LEGACY:
            write_file(WS + "/" + rel, b"# legacy, never shipped\n")
        for name in ("portrait.png", "wide3x1.png", "square.png"):
            write_file(WS + "/generated/hw_gate_seeds/" + name, b"\x89PNG fixture " + name.encode("ascii"))
        write_file(WS + "/generated/hw_gate_seeds/last_portrait.sid", b"sid\n")
        write_file(WS + "/__pycache__/z_image_skill.cpython-313.pyc", b"pyc")
        L = H + "/ltx-2-mlx"
        write_file(L + "/README.md", b"ltx-2-mlx fixture\n")
        write_file(L + "/packages/ltx_core/__init__.py", b"# core\n")
        write_file(L + "/packages/ltx_core/__pycache__/__init__.cpython-311.pyc", b"pyc")
        write_file(L + "/packages/.DS_Store", b"ds")
        write_file(L + "/.git/HEAD", b"ref: refs/heads/main\n")
        for name in ("hf_cache/hub", "converted_models", "source_caches", ".claude", "models/other-model"):
            write_file(L + "/" + name + "/excluded.txt", b"excluded\n")
        B3 = H + "/.local/share/uv/python/cpython-3.11.13-macos-aarch64-none"
        write_file(B3 + "/bin/python3.11", b"#!fake\n", 0o755)
        make_link(B3 + "/bin/python3", "python3.11")
        write_file(B3 + "/lib/libpython3.11.dylib", b"dylib")
        V = L + "/.venv"
        write_file(V + "/pyvenv.cfg", ("home = %s/bin\nversion_info = 3.11.13\n" % B3).encode("utf-8"))
        make_link(V + "/bin/python", B3 + "/bin/python3.11")
        write_file(V + "/bin/ltx-2-mlx", b"#!fake\n", 0o755)
        write_file(V + "/lib/python3.11/site-packages/ltx_pipelines.pth", (L + "/packages/ltx_core\n").encode("utf-8"))
        write_file(V + "/lib/python3.11/site-packages/__pycache__/x.cpython-311.pyc", b"pyc")
        P = L + "/models/ltx-2.5-mlx-q8"
        for name in PACK28:
            write_file(P + "/" + name, ("pack:%s\n" % name).encode("utf-8"))
        write_file(P + "/.cache/huggingface/download/x.metadata", b"cache")
        write_file(P + "/.DS_Store", b"ds")
        os.chmod(P, 0o750)
        D = H + "/.venv-vllm-metal"
        write_file(D + "/pyvenv.cfg", ("home = %s\nversion_info = 3.12.9\n" % os.path.dirname(self.brew_py312)).encode("utf-8"))
        make_link(D + "/bin/python", self.brew_py312)
        write_file(D + "/lib/python3.12/site-packages/vllm/__init__.py", b"__version__ = '0.27.1'\n")
        write_file(D + "/lib/python3.12/site-packages/vllm/.mypy_cache/x", b"cache")
        F = self.fw + "/Versions/3.13"
        write_file(F + "/bin/python3.13", b"#!fake\n", 0o755)
        make_link(F + "/bin/python3", "python3.13")
        write_file(F + "/bin/student-agent-mcp", b"from student_agent_mcp.__main__ import cli\n", 0o755)
        SP = F + "/lib/python3.13/site-packages"
        write_file(SP + "/psutil/__init__.py", b"# psutil\n")
        write_file(SP + "/psutil/__pycache__/__init__.cpython-313.pyc", b"pyc")
        write_file(SP + "/.ruff_cache/x", b"cache")
        write_file(SP + "/.pytest_cache/x", b"cache")
        for name in ("__editable___fubotv_mcp_common_0_1_0_finder.py", "__editable___student_agent_mcp_1_0_0_finder.py",
                     "__editable__.fubotv_mcp_common-0.1.0.pth", "__editable__.student_agent_mcp-1.0.0.pth"):
            write_file(SP + "/" + name, b"# editable reference\n")
        write_file(SP + "/fubotv_mcp_common-0.1.0.dist-info/METADATA", b"Name: fubotv-mcp-common\n")
        write_file(SP + "/student_agent_mcp-1.0.0.dist-info/METADATA", b"Name: student-agent-mcp\n")
        for name in ("Headers", "Python", "Resources"):
            make_link(self.fw + "/" + name, "Versions/Current/" + name)
        make_link(self.fw + "/Versions/Current", "3.13")
        os.chmod(self.fw + "/Versions", 0o775)
        for name in BIN_LINKS13:
            value = self.ulb + "/python3" if name == "python" else "../../../Library/Frameworks/Python.framework/Versions/3.13/bin/" + name
            make_link(self.ulb + "/" + name, value)
        U = H + "/Library/Python/3.13"
        USP = U + "/lib/python/site-packages"
        write_file(USP + "/torch/__init__.py", b"# torch\n")
        for name in ("__editable___fubotv_mcp_common_0_1_0_finder.py", "__editable__.fubotv_mcp_common-0.1.0.pth"):
            write_file(USP + "/" + name, b"# editable reference\n")
        write_file(USP + "/fubotv_mcp_common-0.1.0.dist-info/METADATA", b"Name: fubotv-mcp-common\n")
        write_file(U + "/bin/torchrun", b"#!fake\n", 0o755)
        hub = H + "/hf_home/hub"
        for cid in ("H1", "H2", "H4"):
            self.make_repo(hub, PINS[cid][0], PINS[cid][1])
        self.make_repo(self.usb_hub, PINS["H3"][0], PINS["H3"][1])
        big27 = "models--ailexleon--Huihui-Qwen3.8-27B-abliterated-mlx-6Bit"
        self.make_repo(hub, big27, "a68be749cc7a1e762811b899b3af9ca13c97d29d")
        write_file(H + "/.mtplx/state.json", b"{}")
        make_link(H + "/mlx_models/qwen3-vl", hub + "/" + PINS["H4"][0] + "/snapshots/" + PINS["H4"][1])
        make_link(H + "/mlx_models/Huihui-Qwen3.8-27B-abliterated-mlx-6bit", hub + "/" + big27 + "/snapshots/a68be749cc7a1e762811b899b3af9ca13c97d29d")
        self.write_deploy_dir()

    def configure_build_hooks(self):
        bp.HOOKS.update({
            "run": self.run,
            "ismount": lambda path: path in self.mounts,
            "diskutil_personality": lambda path: "Case-sensitive APFS",
            "statvfs_free": lambda path: 10 ** 15,
            "port_free": lambda port: True,
            "which": lambda name: {"ffmpeg": self.ffmpeg, "ffprobe": self.ffprobe}.get(name),
            "now_utc": lambda: FIXED_NOW,
            "after_chunk": lambda src, nbytes: None,
            "after_entry": lambda index: None,
        })

    def ctx(self, *extra):
        args = bp.parse_args(["--usb-root", self.usb, "--package-id", self.package_id] + list(extra))
        ctx = bp.BuildCtx(args)
        bp.enumerate_components(ctx)
        return ctx


def order_by_spec(keys):
    out = []
    for cid in ORDER:
        mine = [k for k in keys if k[1] == cid]
        out.extend(sorted([k for k in mine if k[2] is not None], key=lambda k: k[2]))
        out.extend(sorted([k for k in mine if k[2] is None], key=lambda k: k[3]))
    return out


def expected_keys(fx):
    H, WS = fx.home, fx.ws
    exp = []

    def tree(cid, slug, target, items):
        prefix = "payload/%s-%s" % (cid, slug)
        exp.append(("d", cid, prefix, target))
        for kind, rel in items:
            exp.append((kind, cid, prefix + "/" + rel, target + "/" + rel))

    a1 = "payload/A1-workspace-code"
    exp.extend([("d", "A1", a1, WS), ("d", "A1", a1 + "/bin", WS + "/bin"), ("d", "A1", a1 + "/tests", WS + "/tests")])
    exp.extend(("f", "A1", a1 + "/" + rel, WS + "/" + rel) for rel in PIPELINE + TESTS7)
    a2 = "payload/A2-hw-gate-seeds"
    exp.append(("d", "A2", a2, WS + "/generated/hw_gate_seeds"))
    exp.extend(("f", "A2", a2 + "/" + n, WS + "/generated/hw_gate_seeds/" + n) for n in ("portrait.png", "wide3x1.png", "square.png"))
    L = H + "/ltx-2-mlx"
    tree("B1", "ltx2mlx-repo", L, [("f", "README.md"), ("d", "packages"), ("d", "packages/ltx_core"), ("f", "packages/ltx_core/__init__.py")])
    tree("B2", "ltx2mlx-venv", L + "/.venv", [("f", "pyvenv.cfg"), ("d", "bin"), ("l", "bin/python"), ("f", "bin/ltx-2-mlx"), ("d", "lib"), ("d", "lib/python3.11"), ("d", "lib/python3.11/site-packages"), ("f", "lib/python3.11/site-packages/ltx_pipelines.pth")])
    tree("B3", "uv-cpython311", H + "/.local/share/uv/python/cpython-3.11.13-macos-aarch64-none", [("d", "bin"), ("f", "bin/python3.11"), ("l", "bin/python3"), ("d", "lib"), ("f", "lib/libpython3.11.dylib")])
    tree("B4", "ltx25-mlx-q8", L + "/models/ltx-2.5-mlx-q8", [("f", n) for n in PACK28])
    exp.extend([("d", "B5", None, L + "/hf_cache"), ("d", "B5", None, L + "/hf_cache/hub")])
    tree("D1", "vllm-venv", H + "/.venv-vllm-metal", [("f", "pyvenv.cfg"), ("d", "bin"), ("l", "bin/python"), ("d", "lib"), ("d", "lib/python3.12"), ("d", "lib/python3.12/site-packages"), ("d", "lib/python3.12/site-packages/vllm"), ("f", "lib/python3.12/site-packages/vllm/__init__.py")])
    tree("F1", "framework-python", fx.fw + "/Versions/3.13", [("d", "bin"), ("f", "bin/python3.13"), ("l", "bin/python3"), ("d", "lib"), ("d", "lib/python3.13"), ("d", "lib/python3.13/site-packages"), ("d", "lib/python3.13/site-packages/psutil"), ("f", "lib/python3.13/site-packages/psutil/__init__.py")])
    exp.extend([("d", "F2", None, fx.fw), ("d", "F2", None, fx.fw + "/Versions"), ("d", "F2", None, fx.ulb)])
    exp.extend(("l", "F2", None, fx.fw + "/" + n) for n in ("Headers", "Python", "Resources", "Versions/Current"))
    exp.extend(("l", "F2", None, fx.ulb + "/" + n) for n in BIN_LINKS13)
    tree("F3", "user-site", H + "/Library/Python/3.13", [("d", "bin"), ("f", "bin/torchrun"), ("d", "lib"), ("d", "lib/python"), ("d", "lib/python/site-packages"), ("d", "lib/python/site-packages/torch"), ("f", "lib/python/site-packages/torch/__init__.py")])
    exp.extend([("d", "H0", None, H + "/hf_home"), ("d", "H0", None, H + "/hf_home/hub")])
    slugs = {"H1": "hf-zimage", "H2": "hf-zimage-te", "H3": "hf-nsfw", "H4": "hf-qwen3vl32b"}
    for cid in ("H1", "H2", "H3", "H4"):
        repo, pin = PINS[cid]
        blob = hashlib.sha1(repo.encode("utf-8")).hexdigest()
        tree(cid, slugs[cid], H + "/hf_home/hub/" + repo, [("d", "blobs"), ("f", "blobs/" + blob), ("d", "refs"), ("f", "refs/main"), ("d", "snapshots"), ("d", "snapshots/" + pin), ("l", "snapshots/" + pin + "/config.json")])
    exp.extend([("d", "H5", None, H + "/mlx_models"), ("l", "H5", None, H + "/mlx_models/qwen3-vl")])
    return order_by_spec(exp)


class TestComponentCollection(DeployTestCase):
    def setUp(self):
        DeployTestCase.setUp(self)
        self.fx = Fixture(self)
        self.fx.build_sources()

    def keys(self, ctx):
        return [(e["k"], e["c"], e.get("p"), e["t"]) for e in ctx.entries]

    def test_T01_golden_entry_list(self):
        ctx = self.fx.ctx()
        self.assertEqual(ctx.enum_errors, [])
        self.assertEqual(ctx.l1_hits, [])
        self.assertEqual(self.keys(ctx), expected_keys(self.fx))

    def test_T02_exclusions(self):
        ctx = self.fx.ctx()
        targets = [e["t"] for e in ctx.entries]
        sources = [e.get("_src", "") for e in ctx.entries]
        for pruned in ("__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache"):
            self.assertEqual([t for t in targets if ("/" + pruned + "/") in (t + "/")], [], pruned)
        self.assertEqual([t for t in targets if t.endswith("/.DS_Store")], [])
        self.assertEqual([t for t in targets if "/ltx-2.5-mlx-q8/.cache" in t], [])
        L = self.fx.home + "/ltx-2-mlx"
        for name in ("models", "hf_cache", "converted_models", "source_caches", ".venv", ".claude", ".git"):
            self.assertEqual([e["t"] for e in ctx.entries if e["c"] == "B1" and _under_path(e["t"], L + "/" + name)], [], name)
        for marker in ("fubotv_mcp_common", "student_agent_mcp", "student-agent-mcp"):
            self.assertEqual([t for t in targets if marker in t], [], marker)
        a1 = sorted(e["_rel"] for e in ctx.entries if e["c"] == "A1" and e["k"] == "f")
        self.assertEqual(a1, sorted(PIPELINE + TESTS7))
        for rel in LEGACY:
            self.assertTrue(os.path.exists(self.fx.ws + "/" + rel), rel)
            self.assertNotIn(self.fx.ws + "/" + rel, targets)
        self.assertEqual([p for p in sources + targets if "Huihui-Qwen3.8-27B" in p or "/.mtplx" in p], [])
        self.assertNotIn(self.fx.ws + "/generated/hw_gate_seeds/last_portrait.sid", targets)

    def test_T02b_constants_verbatim(self):
        self.assertEqual(bp.COMPONENT_ORDER, ORDER)
        self.assertEqual(bp.LTX25_PACK_FILES, frozenset(PACK28))
        self.assertEqual(len(bp.LTX25_PACK_FILES), 28)
        self.assertEqual(bp.PIPELINE_FILES, PIPELINE)
        self.assertEqual(bp.TEST_FILES, TESTS7)
        self.assertEqual(bp.F2_BIN_LINKS, BIN_LINKS13)
        self.assertEqual(bp.F2_FRAMEWORK_LINKS, ("Headers", "Python", "Resources", "Versions/Current"))
        self.assertEqual(bp.HF_PINS, PINS)
        self.assertEqual(bp.PRUNE_DIRS, frozenset(["__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache"]))
        self.assertEqual(bp.B1_EXCLUDES, frozenset(["models", "hf_cache", "converted_models", "source_caches", ".venv", ".claude", ".git"]))
        self.assertEqual(bp.F1_EXCLUDES, frozenset(["bin/student-agent-mcp"] + ["lib/python3.13/site-packages/" + n for n in (
            "__editable___fubotv_mcp_common_0_1_0_finder.py", "__editable___student_agent_mcp_1_0_0_finder.py",
            "__editable__.fubotv_mcp_common-0.1.0.pth", "__editable__.student_agent_mcp-1.0.0.pth",
            "fubotv_mcp_common-0.1.0.dist-info", "student_agent_mcp-1.0.0.dist-info")]))
        self.assertEqual(bp.F3_EXCLUDES, frozenset("lib/python/site-packages/" + n for n in (
            "__editable___fubotv_mcp_common_0_1_0_finder.py", "__editable__.fubotv_mcp_common-0.1.0.pth",
            "fubotv_mcp_common-0.1.0.dist-info")))
        self.assertEqual(bp.SLUGS["B4"], "ltx25-mlx-q8")
        self.assertEqual(len(bp.SLUGS), 17)

    def test_T03a_hf_snapshot_links_are_relative_l_entries(self):
        ctx = self.fx.ctx()
        for cid in ("H1", "H2", "H3", "H4"):
            repo, pin = PINS[cid]
            links = [e for e in ctx.entries if e["c"] == cid and e["k"] == "l"]
            self.assertEqual([e["l"] for e in links], ["../../blobs/" + hashlib.sha1(repo.encode("utf-8")).hexdigest()])

    def test_T04_synthetic_entries(self):
        ctx = self.fx.ctx()
        synth = [e for e in ctx.entries if e["c"] in ("B5", "H0", "H5")]
        self.assertEqual(len(synth), 6)
        for e in synth:
            self.assertIs(e.get("s"), True)
            self.assertNotIn("p", e)
            self.assertNotIn("_src", e)
        link = [e for e in synth if e["k"] == "l"][0]
        self.assertEqual(link["l"], self.fx.home + "/hf_home/hub/" + PINS["H4"][0] + "/snapshots/" + PINS["H4"][1])
        self.assertEqual([e["m"] for e in synth if e["k"] == "d"], ["0755"] * 5)

    def test_T05_f2_has_17_links_and_3_dirs(self):
        ctx = self.fx.ctx()
        f2 = [e for e in ctx.entries if e["c"] == "F2"]
        self.assertEqual(sorted(collections.Counter(e["k"] for e in f2).items()), [("d", 3), ("l", 17)])
        self.assertEqual([e for e in f2 if "p" in e], [])
        by_t = dict((e["t"], e) for e in f2)
        self.assertEqual(by_t[self.fx.fw + "/Versions"]["m"], "0775")
        self.assertEqual(by_t[self.fx.fw + "/Versions/Current"]["l"], "3.13")
        self.assertEqual(by_t[self.fx.ulb + "/python"]["l"], self.fx.ulb + "/python3")

    def test_T05b_f2_wrong_type_is_an_enumeration_error(self):
        os.unlink(self.fx.ulb + "/pip3")
        write_file(self.fx.ulb + "/pip3", b"not a symlink")
        ctx = self.fx.ctx()
        self.assertTrue([m for m in ctx.enum_errors if self.fx.ulb + "/pip3" in m and "not a symlink" in m], ctx.enum_errors)

    def test_T07a_fifo_is_an_enumeration_error(self):
        fifo = self.fx.home + "/Library/Python/3.13/lib/python/site-packages/torch/pipe"
        os.mkfifo(fifo)
        ctx = self.fx.ctx()
        self.assertTrue([m for m in ctx.enum_errors if fifo in m and "special file" in m], ctx.enum_errors)

    def test_missing_source_root_is_an_enumeration_error(self):
        B3 = self.fx.home + "/.local/share/uv/python/cpython-3.11.13-macos-aarch64-none"
        shutil.rmtree(B3)
        ctx = self.fx.ctx()
        self.assertTrue([m for m in ctx.enum_errors if m.startswith("B3:") and B3 in m], ctx.enum_errors)

    def test_R6_falconsai_hub_selection(self):
        ctx = self.fx.ctx()
        self.assertEqual(ctx.falconsai_hub, self.fx.usb_hub)
        h3 = [e for e in ctx.entries if e["c"] == "H3"]
        self.assertTrue(all(e["_src"].startswith(self.fx.usb_hub + "/") for e in h3))
        self.assertTrue(all(e["t"].startswith(self.fx.home + "/hf_home/hub/") for e in h3))
        self.fx.make_repo(self.fx.home + "/hf_home/hub", PINS["H3"][0], PINS["H3"][1])
        self.assertEqual(self.fx.ctx().falconsai_hub, self.fx.home + "/hf_home/hub")
        shutil.rmtree(self.fx.home + "/hf_home/hub/" + PINS["H3"][0])
        shutil.rmtree(self.fx.usb_hub + "/" + PINS["H3"][0])
        ctx = self.fx.ctx()
        self.assertIsNone(ctx.falconsai_hub)
        self.assertTrue([m for m in ctx.enum_errors if m.startswith("H3:")])

    def test_stats(self):
        ctx = self.fx.ctx()
        self.assertEqual(list(ctx.comp_stats), list(ORDER))
        self.assertEqual((ctx.comp_stats["A1"]["files"], ctx.comp_stats["A1"]["dirs"]), (17, 3))
        self.assertEqual(ctx.comp_stats["F2"], {"slug": "framework-symlinks", "files": 0, "symlinks": 17, "dirs": 3, "bytes": 0})
        totals = bp.stats_totals(ctx.comp_stats)
        self.assertEqual(totals["bytes"], sum(e["b"] for e in ctx.entries if e["k"] == "f"))

    def test_B18_employer_package_leak_guard(self):
        ctx = self.fx.ctx()
        result = bp.check_no_employer_packages(ctx)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.check_id, "B18")
        self.assertTrue(result.fatal)
        write_file(self.fx.fw + "/Versions/3.13/bin/fubotv-mcp-common", b"#!fake\n", 0o755)
        ctx2 = self.fx.ctx()
        result2 = bp.check_no_employer_packages(ctx2)
        self.assertFalse(result2.ok)
        self.assertTrue(result2.fatal)
        self.assertIn("fubotv-mcp-common", result2.message)

    def test_parse_args_usage_errors(self):
        for argv in (["--resume"], ["--package-id", "ltx-chain-deploy-2026"], ["--apply", "--verify-only"]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    bp.parse_args(argv)
            self.assertEqual(cm.exception.code, 2, argv)
        args = bp.parse_args(["--usb-root", self.fx.usb + "/"])
        self.assertEqual(bp.BuildCtx(args).usb_root, self.fx.usb)


def allow_entry(hit, note="reviewed: test fixture canary"):
    return {"component": hit["component"], "relpath": hit["relpath"], "sha256": hit["sha256"],
            "pattern": hit["pattern"], "note": note}


L2_CANARIES = (
    ("hf_token", "hf" + "_" + "Ab3" * 12),
    ("private_key", "-----BEGIN " + "RSA PRIVATE" + " KEY-----"),
    ("aws_access_key_id", "AK" + "IA" + "ABCDEFGHIJKLMNOP"),
    ("github_token", GITHUB_CANARY),
    ("anthropic_api_key", " sk-" + "ant-" + "a" * 40),
    ("openai_api_key", " sk-" + "proj-" + "b" * 40),
)


class TestCredentialGates(DeployTestCase):
    def setUp(self):
        DeployTestCase.setUp(self)
        self.fx = Fixture(self)
        self.fx.build_sources()
        self.torch = self.fx.home + "/Library/Python/3.13/lib/python/site-packages/torch"

    def l2_ctx(self):
        ctx = self.fx.ctx()
        bp.load_deploy_files(ctx)
        bp.prepare_l2(ctx)
        return ctx

    def test_T10a_nested_token_file_is_an_l1_hit_and_tokenizer_json_is_not(self):
        write_file(self.torch + "/tokenizer.json", b"{}")
        write_file(self.torch + "/credentials.py", b"# code\n")
        os.makedirs(self.torch + "/token")
        ctx = self.fx.ctx()
        self.assertEqual(ctx.l1_hits, [])
        self.assertTrue(bp.check_b12(ctx).ok)
        write_file(self.torch + "/sub/token", b"not-a-secret-value-xyz\n")
        ctx = self.fx.ctx()
        self.assertEqual(ctx.l1_hits, [self.torch + "/sub/token"])
        result = bp.check_b12(ctx)
        self.assertFalse(result.ok)
        self.assertTrue(result.fatal)
        self.assertIn(self.torch + "/sub/token", result.message)

    def test_T11_each_l1_name_fails_b12(self):
        names = ["token", "stored_tokens", ".netrc", ".git-credentials", ".pypirc", ".env", "credentials",
                 "id_rsa", "id_ecdsa", "id_ed25519", "id_dsa"]
        self.assertEqual(sorted(bp.L1_NAMES), sorted(names))
        for name in names:
            path = self.torch + "/" + name
            write_file(path, b"harmless\n")
            ctx = self.fx.ctx()
            self.assertEqual(ctx.l1_hits, [path], name)
            self.assertFalse(bp.check_b12(ctx).ok, name)
            os.unlink(path)
        link = self.torch + "/id_rsa"
        make_link(link, "elsewhere")
        self.assertEqual(self.fx.ctx().l1_hits, [link])

    def test_T12_each_l2_pattern_is_allowlisted_only_by_exact_hash(self):
        for pid, canary in L2_CANARIES:
            path = self.torch + "/leak_%s.txt" % pid
            rel = "lib/python/site-packages/torch/leak_%s.txt" % pid
            write_file(path, ("prefix " + canary + " suffix\n").encode("utf-8"))
            ctx = self.l2_ctx()
            mine = [h for h in ctx.l2_hits if h["relpath"] == rel]
            self.assertIn(pid, [h["pattern"] for h in mine], pid)
            self.assertTrue(all(h["component"] == "F3" and h["sha256"] == file_sha256(path) for h in mine))
            self.assertFalse(bp.check_b13(ctx).ok, pid)
            self.fx.write_allowlist([allow_entry(h) for h in mine])
            ctx = self.l2_ctx()
            self.assertEqual(ctx.l2_new, [], pid)
            self.assertTrue(bp.check_b13(ctx).ok, pid)
            write_file(path, ("Prefix " + canary + " suffix\n").encode("utf-8"))   # one byte changed
            ctx = self.l2_ctx()
            self.assertFalse(bp.check_b13(ctx).ok, pid)
            warnings = bp.stale_allowlist_warnings(ctx)
            self.assertEqual(len(warnings), len(mine))
            self.assertTrue(all(w.check_id == "B13" and not w.ok and not w.fatal and w.message.startswith("stale allowlist entry {") for w in warnings))
            os.unlink(path)
            self.fx.write_allowlist([])

    def test_T12b_l2_size_limit(self):
        big = self.torch + "/big.bin"
        write_file(big, GITHUB_CANARY.encode("ascii") + b"\0" * bp.L2_MAX_BYTES)
        at_limit = self.torch + "/limit.bin"
        payload = GITHUB_CANARY.encode("ascii")
        write_file(at_limit, payload + b"\0" * (bp.L2_MAX_BYTES - len(payload)))
        ctx = self.l2_ctx()
        rels = [h["relpath"] for h in ctx.l2_hits]
        self.assertNotIn("lib/python/site-packages/torch/big.bin", rels)
        self.assertIn("lib/python/site-packages/torch/limit.bin", rels)

    def test_allowlist_validation(self):
        good = {"component": "F3", "relpath": "x", "sha256": "0" * 64, "pattern": "hf_token", "note": "ok"}
        allow, entries = bp.parse_allowlist(json.dumps({"schema_version": 1, "entries": [good]}).encode("utf-8"), "t")
        self.assertEqual(allow, set([("F3", "x", "0" * 64, "hf_token")]))
        self.assertEqual(entries, [good])
        for bad in ({"schema_version": 2, "entries": []}, {"schema_version": 1},
                    {"schema_version": 1, "entries": [dict(good, note="")]},
                    {"schema_version": 1, "entries": [dict(good, note="   ")]},
                    {"schema_version": 1, "entries": [dict((k, v) for k, v in good.items() if k != "note")]},
                    {"schema_version": 1, "entries": [dict(good, sha256=5)]}):
            with self.assertRaises(ValueError):
                bp.parse_allowlist(json.dumps(bad).encode("utf-8"), "t")
        with self.assertRaises(ValueError):
            bp.parse_allowlist(b"not json", "t")
        write_file(self.fx.deploy + "/credential_allowlist.json", b'{"schema_version": 1, "entries": [{"component": "F3"}]}')
        ctx = self.l2_ctx()
        self.assertIsNotNone(ctx.allow_error)
        result = bp.check_b13(ctx)
        self.assertFalse(result.ok)
        self.assertIn("allowlist failed to load", result.message)

    def test_T14_known_secret_sources(self):
        H = self.fx.home
        values, sources, errors = bp.load_known_secrets()
        self.assertEqual((values, errors), ([], []))
        self.assertEqual([s["source"] for s in sources], [H + "/.cache/huggingface/token", H + "/.cache/huggingface/stored_tokens", H + "/ltx-2-mlx/hf_cache/token", "$HF_TOKEN"])
        self.assertEqual([s["present"] for s in sources], [False, False, False, False])
        tok_a = "tokA." + "x" * 20
        tok_b = "tokB." + "y" * 20
        tok_r = "reft." + "z" * 20
        write_file(H + "/.cache/huggingface/token", (tok_a + "\n").encode("ascii"))
        write_file(H + "/.cache/huggingface/stored_tokens", ("[default]\nhf_token = %s\nrefresh_token = %s\n[other]\nhf_token = %s\n" % (tok_b, tok_r, tok_a)).encode("ascii"))
        write_file(H + "/ltx-2-mlx/hf_cache/token", (tok_a + "\n").encode("ascii"))
        os.environ["HF_TOKEN"] = "  " + tok_b + "  "
        values, sources, errors = bp.load_known_secrets()
        self.assertEqual(errors, [])
        self.assertEqual(values, [tok_a.encode("ascii"), tok_b.encode("ascii"), tok_r.encode("ascii")])
        self.assertEqual([s["values"] for s in sources], [1, 3, 1, 1])
        self.assertEqual([s["present"] for s in sources], [True, True, True, True])
        write_file(H + "/.cache/huggingface/token", b"fifteen.bytes15\n")
        values, sources, errors = bp.load_known_secrets()
        self.assertTrue([e for e in errors if "too short" in e], errors)
        self.assertEqual([e for e in errors if "fifteen" in e], [])
        write_file(H + "/.cache/huggingface/token", (tok_a + "\n").encode("ascii"))
        write_file(H + "/.cache/huggingface/stored_tokens", b"no section header here\n")
        values, sources, errors = bp.load_known_secrets()
        self.assertTrue([e for e in errors if "cannot be parsed" in e], errors)
        write_file(H + "/.cache/huggingface/stored_tokens", b"[default]\nsomething_else = abc\n")
        values, sources, errors = bp.load_known_secrets()
        self.assertTrue([e for e in errors if "no hf_token or refresh_token" in e], errors)
        ctx = self.fx.ctx()
        ctx.secrets, ctx.l3_sources, ctx.l3_errors = values, sources, errors
        self.assertFalse(bp.check_b14(ctx).ok)
        write_file(H + "/.cache/huggingface/stored_tokens", ("[default]\nrefresh_token = %s\n" % tok_r).encode("ascii"))
        values, sources, errors = bp.load_known_secrets()
        self.assertEqual([e for e in errors if "stored_tokens" in e], [])
        self.assertIn(tok_r.encode("ascii"), values)
        stored_source = [s for s in sources if s["source"] == H + "/.cache/huggingface/stored_tokens"][0]
        self.assertEqual(stored_source["values"], 1)

    def test_T16_scripts_are_l2_clean(self):
        names = sorted(n for n in os.listdir(DEPLOY_DIR) if n.endswith(".py"))
        self.assertIn("build_pkg.py", names)
        for name in names:
            with open(os.path.join(DEPLOY_DIR, name), "rb") as fh:
                self.assertEqual(bp.l2_scan_bytes(fh.read()), [], name)

    def test_T17_credential_report(self):
        path = self.torch + "/leak.txt"
        write_file(path, ("x " + GITHUB_CANARY + "\n").encode("ascii"))
        write_file(self.torch + "/deep/.netrc", b"machine example\n")
        before = snapshot(self.fx.root)
        args = bp.parse_args(["--credential-report", "--usb-root", self.fx.usb, "--package-id", self.fx.package_id])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = bp.cmd_credential_report(args)
        text = out.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("L1 " + self.torch + "/deep/.netrc", text.splitlines())
        new = [line for line in text.splitlines() if line.startswith("L2 NEW ")]
        self.assertEqual(len(new), 1)
        doc = json.loads(new[0][len("L2 NEW "):])
        self.assertEqual(doc, {"component": "F3", "relpath": "lib/python/site-packages/torch/leak.txt",
                               "sha256": file_sha256(path), "pattern": "github_token", "note": ""})
        self.assertIn('", "', new[0])
        self.assertNotIn(GITHUB_CANARY, text)
        self.assertEqual(snapshot(self.fx.root), before)
        self.assertFalse(os.path.exists(self.fx.pkg))
        os.unlink(self.torch + "/deep/.netrc")
        stale = {"component": "F3", "relpath": "gone.txt", "sha256": "0" * 64, "pattern": "hf_token", "note": "old"}
        self.fx.write_allowlist([dict(doc, note="reviewed"), stale])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = bp.cmd_credential_report(args)
        text = out.getvalue()
        self.assertEqual(rc, 0, text)
        self.assertEqual(len([l for l in text.splitlines() if l.startswith("L2 ALLOWLISTED ")]), 1)
        self.assertEqual([l for l in text.splitlines() if l.startswith("STALE ")], ["STALE " + json.dumps(stale, separators=(", ", ": "))])
        self.assertTrue(text.splitlines()[-1].startswith("build_pkg: CREDENTIAL REPORT CLEAN"))

    def test_scan_package_l1_l2_keys_and_ds_store(self):
        pkg = self.fx.root + "/pkgscan"
        write_file(pkg + "/payload/F3-user-site/lib/x.txt", ("a " + GITHUB_CANARY).encode("ascii"))
        write_file(pkg + "/manifests/source-host.json", ('{"k": "' + GITHUB_CANARY + '"}').encode("ascii"))
        write_file(pkg + "/payload/B1-ltx2mlx-repo/.DS_Store", b"ds")
        write_file(pkg + "/payload/B1-ltx2mlx-repo/deep/.netrc", b"machine x\n")
        make_link(pkg + "/payload/B1-ltx2mlx-repo/token", "nowhere")
        failures, allowed = bp.scan_package(pkg, set())
        self.assertEqual(sorted(failures), sorted([
            "L2 github_token payload/F3-user-site/lib/x.txt",
            "L2 github_token manifests/source-host.json",
            "DS_Store: payload/B1-ltx2mlx-repo/.DS_Store",
            "L1 payload/B1-ltx2mlx-repo/deep/.netrc",
            "L1 payload/B1-ltx2mlx-repo/token"]))
        self.assertEqual([f for f in failures if GITHUB_CANARY in f], [])
        allow = set([("F3", "lib/x.txt", file_sha256(pkg + "/payload/F3-user-site/lib/x.txt"), "github_token"),
                     ("ROOT", "manifests/source-host.json", file_sha256(pkg + "/manifests/source-host.json"), "github_token")])
        failures, allowed = bp.scan_package(pkg, allow)
        self.assertEqual(len(allowed), 2)
        self.assertEqual(sorted(failures), sorted(["DS_Store: payload/B1-ltx2mlx-repo/.DS_Store",
                                                   "L1 payload/B1-ltx2mlx-repo/deep/.netrc",
                                                   "L1 payload/B1-ltx2mlx-repo/token"]))
        self.assertEqual(bp.allowlist_key("payload/A2-hw-gate-seeds/portrait.png"), ("A2", "portrait.png"))
        self.assertEqual(bp.allowlist_key("README.md"), ("ROOT", "README.md"))

    def test_credential_scan_doc_holds_no_secret_material(self):
        secret = SECRET_CANARY
        write_file(self.fx.home + "/.cache/huggingface/token", (secret + "\n").encode("ascii"))
        ctx = self.l2_ctx()
        ctx.secrets, ctx.l3_sources, ctx.l3_errors = bp.load_known_secrets()
        doc = bp.credential_scan_doc(ctx)
        text = json.dumps(doc)
        self.assertNotIn(secret, text)
        self.assertNotIn(hashlib.sha256(secret.encode("ascii")).hexdigest(), text)
        self.assertEqual(doc["l1_names"], sorted(bp.L1_NAMES))
        self.assertEqual(list(doc["l2_patterns"]), [pid for pid, rx in bp.L2_PATTERNS])
        self.assertEqual(doc["l2_max_bytes"], 4194304)
        self.assertEqual(doc["l3_sources"][0], {"source": self.fx.home + "/.cache/huggingface/token", "present": True, "values": 1})
        self.assertEqual(bp.l2_scan_bytes(text.encode("utf-8")), [])


if __name__ == "__main__":
    unittest.main()
