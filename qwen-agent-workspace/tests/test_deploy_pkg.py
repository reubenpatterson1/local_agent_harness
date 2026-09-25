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
        self.deploy = self.ws + "/scripts/deploy"
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
                     "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE", "HF_TOKEN_PATH", "HUGGING_FACE_HUB_TOKEN"):
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
        V = self.fx.volumes
        values, sources, errors = bp.load_known_secrets()
        self.assertEqual((values, errors), ([], []))
        self.assertEqual([s["source"] for s in sources], [
            H + "/.cache/huggingface/token", H + "/.cache/huggingface/stored_tokens", H + "/ltx-2-mlx/hf_cache/token",
            "$HF_TOKEN", H + "/hf_home/token", H + "/hf_home/stored_tokens",
            V + "/USB/hf_home/token", V + "/USB/hf_home/stored_tokens", "$HUGGING_FACE_HUB_TOKEN"])
        self.assertEqual([s["present"] for s in sources], [False, False, False, False, False, False, False, False, False])
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
        self.assertEqual([s["values"] for s in sources], [1, 3, 1, 1, 0, 0, 0, 0, 0])
        self.assertEqual([s["present"] for s in sources], [True, True, True, True, False, False, False, False, False])
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

    def test_T14b_hf_home_volume_and_env_token_sources(self):
        H = self.fx.home
        V = self.fx.volumes
        HF = self.fx.root + "/custom_hf_home"
        base = [H + "/.cache/huggingface/token", H + "/.cache/huggingface/stored_tokens", H + "/ltx-2-mlx/hf_cache/token",
                "$HF_TOKEN", H + "/hf_home/token", H + "/hf_home/stored_tokens",
                V + "/USB/hf_home/token", V + "/USB/hf_home/stored_tokens", "$HUGGING_FACE_HUB_TOKEN"]
        os.environ["HF_HOME"] = ""
        os.environ["HF_TOKEN_PATH"] = ""
        values, sources, errors = bp.load_known_secrets()
        self.assertEqual((values, errors), ([], []))
        self.assertEqual([s["source"] for s in sources], base)
        tok_a = "tokA." + "x" * 20
        tok_h = "tokH." + "h" * 20
        tok_s = "tokS." + "s" * 20
        tok_f = "refF." + "f" * 20
        tok_v = "tokV." + "v" * 20
        tok_u = "tokU." + "u" * 20
        tok_p = "tokP." + "p" * 20
        tok_e = "tokE." + "e" * 20
        write_file(H + "/.cache/huggingface/token", (tok_a + "\n").encode("ascii"))
        write_file(H + "/.cache/huggingface/stored_tokens", ("[default]\nhf_token = %s\n" % tok_a).encode("ascii"))
        write_file(H + "/ltx-2-mlx/hf_cache/token", (tok_a + "\n").encode("ascii"))
        os.environ["HF_TOKEN"] = tok_a
        write_file(HF + "/token", (tok_h + "\n").encode("ascii"))
        write_file(HF + "/stored_tokens", ("[default]\nhf_token = %s\n" % tok_h).encode("ascii"))
        os.environ["HF_HOME"] = HF + "/"
        write_file(H + "/hf_home/token", (tok_s + "\n").encode("ascii"))
        write_file(H + "/hf_home/stored_tokens", ("[default]\nhf_token = %s\nrefresh_token = %s\n" % (tok_s, tok_f)).encode("ascii"))
        write_file(V + "/SomeVol/hf_home/token", (tok_v + "\n").encode("ascii"))
        write_file(V + "/SomeVol/hf_home/stored_tokens", ("[default]\nhf_token = %s\n" % tok_v).encode("ascii"))
        write_file(V + "/USB/hf_home/token", (tok_u + "\n").encode("ascii"))
        write_file(V + "/USB/hf_home/stored_tokens", ("[default]\nhf_token = %s\n" % tok_u).encode("ascii"))
        write_file(V + "/Decoy/not_hf_home/token", ("tokD." + "d" * 20 + "\n").encode("ascii"))
        write_file(H + "/alt/hf_token_file", (tok_p + "\n").encode("ascii"))
        os.environ["HF_TOKEN_PATH"] = "~/alt/hf_token_file"
        os.environ["HUGGING_FACE_HUB_TOKEN"] = "  " + tok_e + "\n"
        values, sources, errors = bp.load_known_secrets()
        self.assertEqual(errors, [])
        self.assertEqual([s["source"] for s in sources], [
            H + "/.cache/huggingface/token", H + "/.cache/huggingface/stored_tokens", H + "/ltx-2-mlx/hf_cache/token",
            "$HF_TOKEN", HF + "/token", HF + "/stored_tokens", H + "/hf_home/token", H + "/hf_home/stored_tokens",
            V + "/SomeVol/hf_home/token", V + "/SomeVol/hf_home/stored_tokens",
            V + "/USB/hf_home/token", V + "/USB/hf_home/stored_tokens",
            H + "/alt/hf_token_file", "$HUGGING_FACE_HUB_TOKEN"])
        self.assertEqual([s["present"] for s in sources], [True] * 14)
        self.assertEqual([s["values"] for s in sources], [1, 1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1])
        self.assertEqual(values, [t.encode("ascii") for t in (tok_a, tok_h, tok_s, tok_f, tok_v, tok_u, tok_p, tok_e)])
        self.assertEqual([s["source"] for s in sources if "USB2" in s["source"] or "Decoy" in s["source"]], [])
        os.environ["HF_HOME"] = self.fx.usb + "/hf_home"
        os.environ["HF_TOKEN_PATH"] = H + "/hf_home/token"
        values, sources, errors = bp.load_known_secrets()
        self.assertEqual(errors, [])
        self.assertEqual([s["source"] for s in sources], [
            H + "/.cache/huggingface/token", H + "/.cache/huggingface/stored_tokens", H + "/ltx-2-mlx/hf_cache/token",
            "$HF_TOKEN", V + "/USB/hf_home/token", V + "/USB/hf_home/stored_tokens",
            H + "/hf_home/token", H + "/hf_home/stored_tokens",
            V + "/SomeVol/hf_home/token", V + "/SomeVol/hf_home/stored_tokens", "$HUGGING_FACE_HUB_TOKEN"])
        self.assertEqual(values, [t.encode("ascii") for t in (tok_a, tok_u, tok_s, tok_f, tok_v, tok_e)])
        write_file(V + "/SomeVol/hf_home/stored_tokens", b"no section header here\n")
        write_file(H + "/alt/hf_token_file", b"fifteen.bytes15\n")
        os.environ["HF_TOKEN_PATH"] = H + "/alt/hf_token_file"
        values, sources, errors = bp.load_known_secrets()
        self.assertEqual(errors, [
            "B14: " + V + "/SomeVol/hf_home/stored_tokens exists but cannot be parsed",
            "B14: a known-secret value from " + H + "/alt/hf_token_file is too short to scan safely (< 16 bytes)"])
        ctx = self.fx.ctx()
        ctx.secrets, ctx.l3_sources, ctx.l3_errors = values, sources, errors
        self.assertFalse(bp.check_b14(ctx).ok)
        text = "\n".join(errors) + json.dumps(sources) + bp.check_b14(ctx).message
        for tok in (tok_a, tok_h, tok_s, tok_f, tok_v, tok_u, tok_p, tok_e, "fifteen.bytes15"):
            self.assertNotIn(tok, text)

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


def prebuild(fx, *extra):
    args = bp.parse_args(["--usb-root", fx.usb, "--package-id", fx.package_id] + list(extra))
    ctx = bp.BuildCtx(args)
    ctx.secrets, ctx.l3_sources, ctx.l3_errors = bp.load_known_secrets()
    bp.enumerate_components(ctx)
    results = bp.run_prebuild_checks(ctx)
    by_id = {}
    for result in results:
        by_id.setdefault(result.check_id, result)
    return ctx, results, by_id


class TestBuildChecks(DeployTestCase):
    def setUp(self):
        DeployTestCase.setUp(self)
        self.fx = Fixture(self)
        self.fx.build_sources()
        self.fx.configure_build_hooks()

    def check(self, check_id, *extra):
        return prebuild(self.fx, *extra)[2][check_id]

    def test_clean_fixture_passes_every_check_in_table_order(self):
        ctx, results, by_id = prebuild(self.fx)
        self.assertEqual([r.check_id for r in results], ["B%02d" % i for i in range(1, 20)])
        self.assertEqual([bp.format_result(r) for r in results if not r.ok], [])
        self.assertEqual(ctx.baseline["schema_version"], 1)
        self.assertEqual(ctx.baseline["interpreter"], self.fx.fw_py)
        self.assertEqual(ctx.baseline["cwd"], self.fx.ws)
        self.assertEqual(ctx.baseline["gates"][0], {"id": "G1", "argv": ["tests/test_ltx_movie_offline.py"], "rc": 0, "last_line": "OK 118/118"})
        self.assertEqual([g["id"] for g in ctx.baseline["gates"]], ["G1", "G2", "G3", "G4", "G5", "G6", "G7"])
        self.assertEqual(ctx.baseline["extras"], [
            {"id": "X1", "argv": ["bin/ltx-mlx-render", "--help"], "rc": 0},
            {"id": "X2", "argv": list(X2_ARGV), "rc": 0, "brace_lines": 0}])
        self.assertEqual(ctx.host["vllm_version"], "0.27.1")          # C1: last line, not the INFO line
        self.assertEqual(ctx.host["memsize"], 68719476736)
        self.assertEqual(ctx.host["ffmpeg_version"], "ffmpeg version 9.0.1 Copyright (c) 2000-2026 the FFmpeg developers")
        self.assertEqual(ctx.host["falconsai_source_hub"], self.fx.usb_hub)
        self.assertEqual(sorted(ctx.freezes), ["manifests/pip-freeze-framework-py313.txt", "manifests/pip-freeze-ltx2mlx-venv.txt", "manifests/pip-freeze-vllm-venv.txt"])
        self.assertEqual(ctx.git_record["head"], HEAD_SHA)
        self.assertEqual(ctx.git_record["branch"], "ltx2-mlx-video-pipeline")
        self.assertEqual(list(ctx.git_record["pipeline_files"]), list(PIPELINE))
        self.assertEqual(list(ctx.git_record["test_files"]), list(TESTS7))
        info = ctx.git_record["pipeline_files"]["bin/ltx-movie"]
        self.assertEqual(info["sha256"], file_sha256(self.fx.ws + "/bin/ltx-movie"))
        self.assertTrue(info["clean"])
        gate_calls = [c for c in self.fx.run.kwcalls if c[0][1:2] == ("tests/test_ltx_movie_offline.py",)]
        self.assertEqual(gate_calls, [((self.fx.fw_py, "tests/test_ltx_movie_offline.py"), 900, self.fx.ws)])

    def test_B01_usb_volume(self):
        self.fx.mounts.clear()
        self.assertFalse(self.check("B01").ok)
        self.fx.mounts.add(self.fx.usb)
        for personality in ("APFS", "Case-sensitive Journaled HFS+"):
            bp.HOOKS["diskutil_personality"] = lambda path, value=personality: value
            self.assertFalse(self.check("B01").ok, personality)

    def test_B02_free_space(self):
        bp.HOOKS["statvfs_free"] = lambda path: 1000
        ctx, results, by_id = prebuild(self.fx)
        self.assertFalse(by_id["B02"].ok)
        total = sum(e["b"] for e in ctx.entries if e["k"] == "f")
        self.assertEqual(ctx.required_bytes, total + bp.BUILD_HEADROOM_BYTES)
        self.assertIn("required=%d" % ctx.required_bytes, by_id["B02"].message)

    def test_B03_sources_and_venv_pins(self):
        cfg = self.fx.home + "/.venv-vllm-metal/pyvenv.cfg"
        write_file(cfg, b"home = /usr/bin\n")
        result = self.check("B03")
        self.assertFalse(result.ok)
        self.assertIn(cfg, result.message)
        write_file(cfg, ("home = %s\n" % os.path.dirname(self.fx.brew_py312)).encode("utf-8"))
        self.assertTrue(self.check("B03").ok)
        ltx_cfg = self.fx.home + "/ltx-2-mlx/.venv/pyvenv.cfg"
        write_file(ltx_cfg, b"home = /opt/other/bin\n")
        self.assertFalse(self.check("B03").ok)
        fifo = self.fx.home + "/Library/Python/3.13/lib/python/site-packages/torch/pipe"
        write_file(ltx_cfg, ("home = %s/bin\n" % bp.b3_source()).encode("utf-8"))
        os.mkfifo(fifo)
        result = self.check("B03")
        self.assertFalse(result.ok)
        self.assertIn(fifo, result.message)

    def test_B04_RF3_pack_file_set(self):
        P = self.fx.home + "/ltx-2-mlx/models/ltx-2.5-mlx-q8"
        self.assertTrue(self.check("B04").ok)
        os.unlink(P + "/vocoder.safetensors")
        result = self.check("B04")
        self.assertFalse(result.ok)
        self.assertIn("missing=['vocoder.safetensors']", result.message)
        self.assertIn("extra=[]", result.message)
        write_file(P + "/vocoder.safetensors", b"v")
        write_file(P + "/transformer-dev.safetensors.part", b"partial")
        result = self.check("B04")
        self.assertFalse(result.ok)
        self.assertIn("extra=['transformer-dev.safetensors.part']", result.message)
        os.unlink(P + "/transformer-dev.safetensors.part")
        os.unlink(P + "/LICENSE")
        os.makedirs(P + "/LICENSE")
        result = self.check("B04")
        self.assertFalse(result.ok)
        self.assertIn("not_regular=['LICENSE']", result.message)

    def test_B05_hf_repo_completeness(self):
        hub = self.fx.home + "/hf_home/hub"
        repo, pin = PINS["H1"]
        R = hub + "/" + repo
        write_file(R + "/refs/main", b"0" * 40)
        self.assertFalse(self.check("B05").ok)
        write_file(R + "/refs/main", pin.encode("ascii"))
        self.assertTrue(self.check("B05").ok)
        os.makedirs(R + "/snapshots/" + "1" * 40)
        self.assertFalse(self.check("B05").ok)
        os.rmdir(R + "/snapshots/" + "1" * 40)
        write_file(R + "/blobs/abc.incomplete", b"")
        self.assertFalse(self.check("B05").ok)
        os.unlink(R + "/blobs/abc.incomplete")
        make_link(R + "/snapshots/" + pin + "/missing.json", "../../blobs/nothere")
        result = self.check("B05")
        self.assertFalse(result.ok)
        self.assertIn("missing.json", result.message)
        os.unlink(R + "/snapshots/" + pin + "/missing.json")
        write_file(self.fx.usb_hub + "/" + PINS["H3"][0] + "/refs/main", b"f" * 40)
        self.assertFalse(self.check("B05").ok)

    def test_B06_case_insensitive_collisions(self):
        ctx = self.fx.ctx()
        self.assertTrue(bp.check_b06(ctx).ok)
        entry = [e for e in ctx.entries if e["c"] == "A1" and e["k"] == "f"][0]
        ctx.entries.append(dict(entry, t=entry["t"].upper(), p=entry["p"] + "-other"))
        result = bp.check_b06(ctx)
        self.assertFalse(result.ok)
        self.assertIn("t collision", result.message)
        ctx = self.fx.ctx()
        ctx.entries.append(dict(entry, p=entry["p"].upper(), t=entry["t"] + "-other"))
        result = bp.check_b06(ctx)
        self.assertFalse(result.ok)
        self.assertIn("p collision", result.message)

    def test_B07_package_root_state(self):
        self.assertTrue(self.check("B07").ok)
        os.makedirs(self.fx.pkg)
        result = self.check("B07")
        self.assertFalse(result.ok)
        self.assertIn("already exists", result.message)
        result = self.check("B07", "--apply", "--resume")
        self.assertTrue(result.ok, result.message)
        self.assertIn("resume prefix: 0 of", result.message)
        write_file(self.fx.pkg + "/MANIFEST.json", b"{}")
        result = self.check("B07", "--apply", "--resume")
        self.assertFalse(result.ok)
        self.assertIn("MANIFEST.json", result.message)
        shutil.rmtree(self.fx.pkg)
        result = self.check("B07", "--apply", "--resume")
        self.assertFalse(result.ok)
        self.assertIn("does not exist", result.message)

    def test_B07_resume_prefix_analysis(self):
        root = self.fx.pkg
        os.makedirs(root)
        ctx = self.fx.ctx("--apply", "--resume")
        e0, e1, e2 = ctx.entries[0], ctx.entries[1], ctx.entries[2]
        self.assertEqual((e0["k"], e1["k"], e2["k"]), ("d", "d", "f"))
        os.makedirs(root + "/" + e1["p"])
        shutil.copyfile(e2["_src"], root + "/" + e2["p"])
        lines = [dict(e0), dict(e1), dict(e2, h=file_sha256(e2["_src"]))]
        data = "".join(bp.entry_line(x) for x in lines).encode("utf-8")
        partial = root + "/MANIFEST-ENTRIES.jsonl.partial"
        write_file(partial, data + b'{"k":"f","c":"A')
        bp.analyze_resume(ctx)
        self.assertEqual((ctx.resume_prefix_len, ctx.resume_keep_bytes, ctx.resume_rename, ctx.resume_error), (3, len(data), False, None))
        self.assertEqual(ctx.entries[2]["h"], file_sha256(e2["_src"]))
        with open(root + "/" + e2["p"], "r+b") as fh:
            fh.write(b"X")
        ctx = self.fx.ctx("--apply", "--resume")
        bp.analyze_resume(ctx)
        self.assertEqual(ctx.resume_prefix_len, 2)
        self.assertEqual(ctx.resume_keep_bytes, len("".join(bp.entry_line(x) for x in lines[:2]).encode("utf-8")))
        os.rename(partial, root + "/MANIFEST-ENTRIES.jsonl")
        ctx = self.fx.ctx("--apply", "--resume")
        bp.analyze_resume(ctx)
        self.assertTrue(ctx.resume_rename)
        os.unlink(root + "/MANIFEST-ENTRIES.jsonl")
        write_file(partial, bp.entry_line(dict(e0, t=e0["t"] + "x")).encode("utf-8"))
        ctx = self.fx.ctx("--apply", "--resume")
        bp.analyze_resume(ctx)
        self.assertTrue(ctx.resume_error.startswith("enumeration changed since the interrupted build; delete %s and rebuild" % root))
        write_file(partial, "".join(bp.entry_line(x) for x in [lines[0], lines[1], dict(lines[2], mt=e2["mt"] + 1)]).encode("utf-8"))
        ctx = self.fx.ctx("--apply", "--resume")
        bp.analyze_resume(ctx)
        self.assertEqual(ctx.resume_error, "source changed since the interrupted build: " + e2["_src"])
        write_file(partial, b"not json\n")
        ctx = self.fx.ctx("--apply", "--resume")
        bp.analyze_resume(ctx)
        self.assertIn("not valid JSON", ctx.resume_error)

    def test_B08_synthetic_symlink_target(self):
        link = self.fx.home + "/mlx_models/qwen3-vl"
        os.unlink(link)
        make_link(link, "/elsewhere")
        self.assertFalse(self.check("B08").ok)
        os.unlink(link)
        self.assertFalse(self.check("B08").ok)

    def test_B09_port(self):
        bp.HOOKS["port_free"] = lambda port: False
        result = self.check("B09")
        self.assertFalse(result.ok)
        self.assertIn("stop the story server", result.message)

    def test_B10_hf_scope(self):
        H = self.fx.home
        self.assertTrue(bp.check_b10(self.fx.ctx()).ok)
        base = {"k": "f", "c": "B1", "p": "payload/B1-ltx2mlx-repo/x", "b": 1, "m": "0644", "mt": 1}
        cases = [
            dict(base, t=H + "/ltx-2-mlx/x", _src=H + "/hf_home/hub/models--other/x"),
            dict(base, t=H + "/ltx-2-mlx/x", _src=H + "/.cache/huggingface/token"),
            dict(base, t=H + "/ltx-2-mlx/x", _src=os.path.dirname(self.fx.usb_hub) + "/hub/models--other/y"),
            dict(base, c="H1", t=H + "/hf_home/hub/models--other/y", _src=H + "/hf_home/hub/" + PINS["H1"][0] + "/y"),
            dict(base, t=H + "/ltx-2-mlx/hf_cache/token", _src=H + "/ltx-2-mlx/README.md"),
        ]
        for extra in cases:
            ctx = self.fx.ctx()
            ctx.entries.append(extra)
            self.assertFalse(bp.check_b10(ctx).ok, extra)

    def test_B11_RF5_target_path_allowlist(self):
        H, fw, ulb = self.fx.home, self.fx.fw, self.fx.ulb
        for t in (H + "/x", fw, fw + "/Versions/3.13/bin/python3", ulb, ulb + "/python3"):
            self.assertTrue(bp.target_allowed(t), t)
        for t in ("/tmp/evil", H, H + "X/evil", fw + "X", fw + "X/y", ulb + "X", "/Volumes/Ollama/x",
                  "/opt/homebrew/bin/x", H + "/../evil", H + "/a/../../evil", H + "//x", H + "/./x", H + "/x/",
                  "relative/x", ""):
            self.assertFalse(bp.target_allowed(t), t)
        ctx = self.fx.ctx()
        self.assertTrue(bp.check_b11(ctx).ok)
        ctx.entries.append({"k": "d", "c": "H0", "t": H + "/../../etc/evil", "m": "0755", "s": True})
        result = bp.check_b11(ctx)
        self.assertFalse(result.ok)
        self.assertIn(H + "/../../etc/evil", result.message)
        with mock.patch.object(bp, "REQUIRED_HOME", H + "-other"):
            result = bp.check_b11(self.fx.ctx())
        self.assertFalse(result.ok)
        self.assertIn("home()", result.message)

    def test_B15_offline_gates(self):
        fw = self.fx.fw_py
        cases = [((fw, "tests/test_ltx_story_images.py"), (1, "FAILED\nOK 97/98\n"), "G3"),
                 ((fw, "tests/check_ltx2_mlx_no_forbidden_imports.py"), (0, "RESULT: 1 forbidden import\n"), "G7"),
                 ((fw,) + X2_ARGV, (0, '{"x": 1}\n'), "X2"),
                 ((fw, "tests/test_ltx_movie_offline.py"), (0, "OK 117/118\n"), "G1"),
                 ((fw, "tests/test_ltx_mlx_render.py"), (0, ""), "G2"),
                 ((fw, "bin/ltx-mlx-render", "--help"), (2, "usage error\n"), "X1")]
        for key, value, gate_id in cases:
            self.fx.run.overrides = {key: value}
            result = self.check("B15")
            self.assertFalse(result.ok, gate_id)
            self.assertIn(gate_id, result.message)
        self.fx.run.overrides = {}
        self.assertTrue(self.check("B15").ok)

    def test_B16_host_facts_and_freezes(self):
        cases = [(("/usr/sbin/sysctl", "-n", "hw.model"), (1, "error"), "hw_model"),
                 (("/usr/sbin/sysctl", "-n", "hw.memsize"), (0, "abc\n"), "memsize"),
                 ((self.fx.vllm_py, "-m", "pip", "freeze", "--all"), (1, "boom"), "pip-freeze-vllm-venv.txt")]
        for key, value, word in cases:
            self.fx.run.overrides = {key: value}
            result = self.check("B16")
            self.assertFalse(result.ok, word)
            self.assertIn(word, result.message)
        self.fx.run.overrides = {}
        bp.HOOKS["which"] = lambda name: None
        result = self.check("B16")
        self.assertFalse(result.ok)
        self.assertIn("ffmpeg", result.message)

    def test_B18_runs_in_prebuild(self):
        write_file(self.fx.fw + "/Versions/3.13/bin/fubotv-mcp-common", b"#!fake\n", 0o755)
        result = self.check("B18")
        self.assertFalse(result.ok)
        self.assertTrue(result.fatal)
        self.assertIn("fubotv-mcp-common", result.message)

    def test_B17_provenance(self):
        self.fx.untracked.add("qwen-agent-workspace/bin/story-server")
        result = self.check("B17")
        self.assertFalse(result.ok)
        self.assertIn("bin/story-server: untracked", result.message)
        self.fx.untracked.clear()
        self.fx.modified.add("qwen-agent-workspace/bin/qwen-agent")
        result = self.check("B17")
        self.assertFalse(result.ok)
        self.assertIn("bin/qwen-agent: modified", result.message)
        self.fx.modified.clear()
        self.fx.committed["qwen-agent-workspace/z_image_skill.py"] = "0" * 40
        result = self.check("B17")
        self.assertFalse(result.ok)
        self.assertIn("z_image_skill.py: blob differs", result.message)
        self.fx.committed.clear()
        self.fx.modified.add("qwen-agent-workspace/tests/test_ltx_image_fit.py")
        ctx, results, by_id = prebuild(self.fx)
        self.assertTrue(by_id["B17"].ok, by_id["B17"].message)
        self.assertFalse(ctx.git_record["test_files"]["tests/test_ltx_image_fit.py"]["clean"])
        self.assertEqual(ctx.git_record["porcelain"], [" M qwen-agent-workspace/tests/test_ltx_image_fit.py"])

    def test_B19_all_clean_when_install_pkg_present(self):
        deploy = self.fx.ws + "/scripts/deploy"
        ctx = self.fx.ctx()
        result = bp.check_b19(ctx)
        self.assertEqual(result, bp.CheckResult("B19", True, "all 3 deploy script files in %s match HEAD" % deploy, True))
        self.assertEqual(ctx.deploy_script_problems, [])
        record = ctx.deploy_script_record
        self.assertEqual((record["deploy_dir"], record["expected_deploy_dir"]), (deploy, deploy))
        rels = ["scripts/deploy/build_pkg.py", "scripts/deploy/install_pkg.py", "scripts/deploy/credential_allowlist.json"]
        self.assertEqual(list(record["files"]), rels)
        for rel in rels:
            with open(self.fx.ws + "/" + rel, "rb") as fh:
                data = fh.read()
            self.assertEqual(record["files"][rel], {"sha256": hashlib.sha256(data).hexdigest(), "git_blob": git_blob(data), "clean": True}, rel)
            self.assertIn((bp.GIT, "-C", self.fx.repo, "ls-files", "--error-unmatch", "--", "qwen-agent-workspace/" + rel), self.fx.run.calls)
        with open(os.path.join(DEPLOY_DIR, "build_pkg.py"), "rb") as a, open(deploy + "/build_pkg.py", "rb") as b:
            self.assertEqual(a.read(), b.read())
        self.assertEqual(ctx.git_record, {})

    def test_B19_install_pkg_not_committed_fails_closed(self):
        rel = "scripts/deploy/install_pkg.py"
        self.fx.untracked.add("qwen-agent-workspace/" + rel)
        ctx = self.fx.ctx()
        self.assertEqual(bp.check_b19(ctx), bp.CheckResult("B19", False, "deploy provenance: scripts/deploy/install_pkg.py: untracked", True))
        files = ctx.deploy_script_record["files"]
        self.assertEqual([r for r in files if not files[r]["clean"]], [rel])
        self.fx.untracked.clear()
        os.unlink(self.fx.ws + "/" + rel)
        ctx = self.fx.ctx()
        self.assertEqual(bp.check_b19(ctx), bp.CheckResult("B19", False, "deploy provenance: scripts/deploy/install_pkg.py: missing", True))
        self.assertEqual(ctx.deploy_script_record["files"][rel], {"sha256": "", "git_blob": "", "clean": False})
        self.assertEqual(ctx.deploy_script_problems, ["scripts/deploy/install_pkg.py: missing"])

    def test_B19_deploy_dir_mismatch(self):
        stray = self.fx.root + "/opt/stray/scripts/deploy"
        expected = self.fx.ws + "/scripts/deploy"
        with mock.patch.object(bp, "deploy_dir", lambda: stray):
            ctx = self.fx.ctx()
            result = bp.check_b19(ctx)
        self.assertEqual(result, bp.CheckResult("B19", False, "deploy provenance: deploy_dir() is %s, expected %s" % (stray, expected), True))
        self.assertEqual(ctx.deploy_script_record["deploy_dir"], stray)
        self.assertTrue(all(info["clean"] for info in ctx.deploy_script_record["files"].values()))
        self.fx.modified.add("qwen-agent-workspace/scripts/deploy/credential_allowlist.json")
        with mock.patch.object(bp, "deploy_dir", lambda: stray):
            result = bp.check_b19(self.fx.ctx())
        self.assertFalse(result.ok)
        self.assertEqual(result.message, "deploy provenance: deploy_dir() is %s, expected %s; scripts/deploy/credential_allowlist.json: modified" % (stray, expected))
        clone = self.fx.usb2 + "/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/scripts/deploy"
        shutil.copytree(self.fx.ws + "/scripts/deploy", clone)
        self.fx.modified.clear()
        with mock.patch.object(bp, "deploy_dir", lambda: clone):
            result = bp.check_b19(self.fx.ctx())
        self.assertEqual(result, bp.CheckResult("B19", False, "deploy provenance: deploy_dir() is %s, expected %s" % (clone, expected), True))

    def test_B19_symlinked_deploy_dir_is_the_checkout(self):
        link = self.fx.root + "/linked-deploy"
        make_link(link, self.fx.ws + "/scripts/deploy")
        with mock.patch.object(bp, "deploy_dir", lambda: link):
            result = bp.check_b19(self.fx.ctx())
        self.assertTrue(result.ok, result.message)
        copy = self.fx.root + "/copied-deploy"
        shutil.copytree(self.fx.ws + "/scripts/deploy", copy)
        with mock.patch.object(bp, "deploy_dir", lambda: copy):
            result = bp.check_b19(self.fx.ctx())
        self.assertEqual(result, bp.CheckResult("B19", False, "deploy provenance: deploy_dir() is %s, expected %s/scripts/deploy" % (copy, self.fx.ws), True))

    def test_B19_detects_dirty_build_pkg(self):
        self.fx.modified.add("qwen-agent-workspace/scripts/deploy/build_pkg.py")
        ctx, results, by_id = prebuild(self.fx)
        self.assertEqual(results[-1].check_id, "B19")
        self.assertEqual(by_id["B19"], bp.CheckResult("B19", False, "deploy provenance: scripts/deploy/build_pkg.py: modified", True))
        self.assertTrue(by_id["B17"].ok, by_id["B17"].message)
        self.assertTrue(ctx.deploy_script_record["files"]["scripts/deploy/credential_allowlist.json"]["clean"])
        self.fx.modified.clear()
        self.fx.committed["qwen-agent-workspace/scripts/deploy/credential_allowlist.json"] = "0" * 40
        result = self.check("B19")
        self.assertEqual(result, bp.CheckResult("B19", False, "deploy provenance: scripts/deploy/credential_allowlist.json: blob differs", True))
        self.fx.committed.clear()
        self.assertTrue(self.check("B19").ok)


class TestReadme(DeployTestCase):
    def setUp(self):
        DeployTestCase.setUp(self)
        self.fx = Fixture(self)
        self.fx.build_sources()
        ctx = self.fx.ctx()
        ctx.git_record = {"head": HEAD_SHA, "branch": "ltx2-mlx-video-pipeline"}
        self.text = bp.render_readme(ctx)
        self.lines = self.text.splitlines()

    def test_T90_every_ltx_movie_line_passes_model_explicitly(self):
        model = "--model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8"
        hits = [line for line in self.lines if "bin/ltx-movie" in line]
        self.assertGreaterEqual(len(hits), 2)
        for line in hits:
            self.assertIn(model, line)
            self.assertFalse(line.rstrip().endswith("\\"), line)
            self.assertIn("--story-server-stop-after-story", line)
            self.assertTrue(line.strip().startswith("/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 bin/ltx-movie "), line)
        self.assertEqual(len([line for line in hits if "--seed-image " in line]), 1)

    def test_T90b_sections_and_install_commands(self):
        for heading in ("## 1. What this package is", "## 2. Target requirements", "## 3. Install",
                        "## 4. Running the pipeline", "## 5. Warnings", "## 6. Troubleshooting", "## 7. Not included"):
            self.assertIn(heading, self.text)
        inst = "/usr/bin/python3 %s/%s/scripts/deploy/install_pkg.py" % (self.fx.usb, self.fx.package_id)
        for tail in ("--phase preflight", "--phase user --apply", "--phase verify", "--phase accept --gpu", "--phase accept --gpu-all"):
            self.assertIn(inst + " " + tail, self.text)
        self.assertIn("sudo " + inst + " --phase system-python --apply", self.text)
        self.assertIn("/usr/bin/python3 /Users/reubenpatterson/local_model_harness/qwen-agent-workspace/generated/deploy-receipts/%s/scripts/deploy/install_pkg.py --phase accept --gpu" % self.fx.package_id, self.text)
        for needle in ('export HF_HOME="/Users/reubenpatterson/hf_home"', "brew install ffmpeg python@3.12", HEAD_SHA,
                       "2026-09-25", "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8", "--image-seed",
                       "~/.qwen-serve-guard/stand-down", "curl -sf http://127.0.0.1:8177/v1/models",
                       ">= 48 GiB RAM", "sudo", "32 MB/min"):
            self.assertIn(needle, self.text)

    def test_T91_forbidden_strings_absent(self):
        low = self.text.lower()
        for needle in ("--video" + "-backend", "comf" + "yui", "cct" + "ech", "chriscole" + "tech", "81" + "89"):
            self.assertNotIn(needle, low)

    def test_T92_readme_is_l2_clean(self):
        self.assertEqual(bp.l2_scan_bytes(self.text.encode("utf-8")), [])


def build_apply(fx, *extra):
    return run_main(bp.main, ["--apply", "--usb-root", fx.usb, "--package-id", fx.package_id] + list(extra))


def build_dry(fx, *extra):
    return run_main(bp.main, ["--dry-run", "--usb-root", fx.usb, "--package-id", fx.package_id] + list(extra))


ROOT_FILES = ["README.md", "manifests/source-host.json", "manifests/pip-freeze-framework-py313.txt",
              "manifests/pip-freeze-ltx2mlx-venv.txt", "manifests/pip-freeze-vllm-venv.txt",
              "manifests/source-git.json", "manifests/acceptance-baseline.json", "manifests/credential-scan.json",
              "scripts/deploy/build_pkg.py", "scripts/deploy/install_pkg.py", "scripts/deploy/credential_allowlist.json"]


class BuildE2ECase(DeployTestCase):
    def setUp(self):
        DeployTestCase.setUp(self)
        self.fx = Fixture(self)
        self.fx.build_sources()
        self.fx.configure_build_hooks()

    def fresh_fixture(self):
        fx = Fixture(self)
        fx.build_sources()
        fx.configure_build_hooks()
        return fx


class TestBuildCli(BuildE2ECase):
    def test_dry_run_report_format_and_writes_nothing(self):
        before = snapshot(self.fx.root)
        rc, out, err = build_dry(self.fx)
        self.assertEqual(rc, 0, out + err)
        lines = out.splitlines()
        self.assertEqual(lines[-1], "build_pkg: DRY RUN OK")
        comp = [line for line in lines if re.match(r"^[A-H][0-9] ", line)]
        self.assertEqual([line.split()[0] for line in comp], list(ORDER))
        self.assertTrue(re.match(r"^A1 workspace-code files=17 symlinks=0 dirs=3 bytes=\d+ \(\d+\.\d\d GiB\)$", comp[0]), comp[0])
        self.assertEqual(comp[9], "F2 framework-symlinks files=0 symlinks=17 dirs=3 bytes=0 (0.00 GiB)")
        totals = [line for line in lines if line.startswith("TOTAL ")]
        self.assertEqual(len(totals), 1)
        self.assertTrue(re.match(r"^TOTAL files=\d+ symlinks=\d+ dirs=\d+ bytes=\d+ \(\d+\.\d\d GiB\)$", totals[0]))
        self.assertEqual(len([line for line in lines if line.startswith("SPACE required=")]), 1)
        self.assertEqual([line.split()[1] for line in lines if line.startswith("PASS ")], ["B%02d" % i for i in range(1, 20)])
        self.assertEqual(snapshot(self.fx.root), before)

    def test_default_mode_is_dry_run_and_failures_exit_4(self):
        bp.HOOKS["port_free"] = lambda port: False
        rc, out, err = run_main(bp.main, ["--usb-root", self.fx.usb, "--package-id", self.fx.package_id])
        self.assertEqual(rc, 4)
        self.assertIn("FAIL B09 ", out)
        self.assertEqual(out.splitlines()[-1], "build_pkg: DRY RUN FAILED (1 checks)")
        self.assertFalse(os.path.lexists(self.fx.pkg))

    def test_apply_builds_a_complete_package(self):
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 0, out + err)
        pkg = self.fx.pkg
        with open(pkg + "/MANIFEST.json") as fh:
            manifest = json.load(fh)
        entries = bp.read_entries(pkg + "/MANIFEST-ENTRIES.jsonl")
        self.assertEqual(manifest["schema_version"], 4)
        self.assertEqual(manifest["package_id"], self.fx.package_id)
        self.assertEqual(manifest["entries_file"], "MANIFEST-ENTRIES.jsonl")
        self.assertEqual(manifest["entries_sha256"], file_sha256(pkg + "/MANIFEST-ENTRIES.jsonl"))
        self.assertEqual(manifest["entries_count"], len(entries))
        self.assertEqual(list(manifest["components"]), list(ORDER))
        self.assertEqual(list(manifest["root_files"]), ROOT_FILES)
        for rel, digest in manifest["root_files"].items():
            self.assertEqual(file_sha256(pkg + "/" + rel), digest, rel)
        self.assertEqual(manifest["source_git_head"], HEAD_SHA)
        self.assertEqual(manifest["models"], {"video_model_path": self.fx.home + "/ltx-2-mlx/models/ltx-2.5-mlx-q8",
                                              "vision_model_snapshot": PINS["H4"][1],
                                              "vision_model_symlink": self.fx.home + "/mlx_models/qwen3-vl"})
        self.assertEqual(manifest["credential_scan"], {"l1": "clean", "l2_allowlisted": 0, "l3_values_loaded": 0, "l4": "clean"})
        self.assertIs(manifest["build"]["resumed"], False)
        self.assertEqual(manifest["totals"]["files"], len([e for e in entries if e["k"] == "f"]))
        self.assertFalse(os.path.lexists(pkg + "/BUILD-FAILED.json"))
        self.assertFalse(os.path.lexists(pkg + "/MANIFEST-ENTRIES.jsonl.partial"))
        self.assertEqual([n for n in os.listdir(pkg) if n.endswith(".tmp")], [])
        ctx = self.fx.ctx()
        ctx.git_record = {"head": HEAD_SHA, "branch": "ltx2-mlx-video-pipeline"}
        with open(pkg + "/README.md") as fh:
            self.assertEqual(fh.read(), bp.render_readme(ctx))
        with open(pkg + "/scripts/deploy/build_pkg.py", "rb") as a, open(os.path.join(DEPLOY_DIR, "build_pkg.py"), "rb") as b:
            self.assertEqual(a.read(), b.read())
        self.assertEqual(stat.S_IMODE(os.lstat(pkg + "/scripts/deploy/build_pkg.py").st_mode), 0o755)
        with open(pkg + "/manifests/acceptance-baseline.json") as fh:
            self.assertEqual(json.load(fh)["gates"][6], {"id": "G7", "argv": ["tests/check_ltx2_mlx_no_forbidden_imports.py"], "rc": 0, "last_line": "RESULT: ok"})
        self.assertTrue(out.splitlines()[-1].startswith("build_pkg: BUILD OK: " + pkg))

    def test_T06_jsonl_on_disk(self):
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 0, out + err)
        with open(self.fx.pkg + "/MANIFEST-ENTRIES.jsonl", "rb") as fh:
            raw_lines = fh.read().decode("utf-8").splitlines()
        shapes = set()
        for raw in raw_lines:
            obj = json.loads(raw)
            self.assertEqual(raw, json.dumps(obj, separators=(",", ":"), ensure_ascii=False))
            shapes.add(tuple(obj))
        self.assertEqual(shapes, set([
            ("k", "c", "p", "t", "b", "m", "h", "mt"),
            ("k", "c", "p", "t", "m"),
            ("k", "c", "p", "t", "l"),
            ("k", "c", "t", "m"),
            ("k", "c", "t", "l"),
            ("k", "c", "t", "m", "s"),
            ("k", "c", "t", "l", "s")]))

    def test_T03_payload_symlinks_after_apply(self):
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 0, out + err)
        repo, pin = PINS["H1"]
        link = self.fx.pkg + "/payload/H1-hf-zimage/snapshots/" + pin + "/config.json"
        self.assertTrue(os.path.islink(link))
        self.assertEqual(os.readlink(link), "../../blobs/" + hashlib.sha1(repo.encode("utf-8")).hexdigest())
        self.assertEqual(os.readlink(self.fx.pkg + "/payload/B3-uv-cpython311/bin/python3"), "python3.11")

    def test_T07_fifo_fails_b03_and_refuses_apply(self):
        fifo = self.fx.home + "/Library/Python/3.13/lib/python/site-packages/torch/pipe"
        os.mkfifo(fifo)
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 4)
        self.assertTrue([line for line in out.splitlines() if line.startswith("FAIL B03 ") and fifo in line])
        self.assertFalse(os.path.lexists(self.fx.pkg))

    def test_RF3_missing_pack_file_refuses_apply_without_creating_root(self):
        os.unlink(self.fx.home + "/ltx-2-mlx/models/ltx-2.5-mlx-q8/transformer-distilled.safetensors")
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 4)
        self.assertIn("missing=['transformer-distilled.safetensors']", out)
        self.assertIn("build_pkg: APPLY REFUSED (1 checks)", out)
        self.assertFalse(os.path.lexists(self.fx.pkg))

    def test_credential_report_through_main(self):
        rc, out, err = run_main(bp.main, ["--credential-report", "--usb-root", self.fx.usb, "--package-id", self.fx.package_id])
        self.assertEqual(rc, 0, out + err)
        self.assertTrue(out.splitlines()[-1].startswith("build_pkg: CREDENTIAL REPORT CLEAN"))

    def test_unexpected_pre_write_error_exits_1(self):
        def boom(ctx):
            raise RuntimeError("injected")
        with mock.patch.object(bp, "run_prebuild_checks", boom):
            rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 1)
        self.assertIn("RuntimeError: injected", err)
        self.assertFalse(os.path.lexists(self.fx.pkg))


class TestRPre(BuildE2ECase):
    def test_T20_failing_gate_refuses_before_any_write(self):
        self.fx.run.overrides[(self.fx.fw_py, "tests/test_ltx_story_images.py")] = (1, "boom\n")
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 4, out + err)
        self.assertIn("FAIL B15 ", out)
        self.assertFalse(os.path.lexists(self.fx.pkg))

    def test_T21_no_outside_open_and_no_subprocess_after_first_payload_write(self):
        root = self.fx.pkg
        sources = set()
        violations = []
        real_enumerate = bp.enumerate_components
        real_open = open
        real_os_open = os.open
        real_run = bp.HOOKS["run"]

        def spy_enumerate(ctx):
            real_enumerate(ctx)
            sources.update(e["_src"] for e in ctx.entries if "_src" in e)

        def allowed(path):
            if isinstance(path, int):
                return True
            p = os.path.abspath(os.fsdecode(path))
            return p == root or p.startswith(root + "/") or p in sources

        def guarded_open(file, *args, **kwargs):
            if bp.CTX_STATE["payload_started"] and not allowed(file):
                violations.append(("open", file))
                raise AssertionError("R-PRE: open(%r) after the first payload write" % (file,))
            return real_open(file, *args, **kwargs)

        def guarded_os_open(path, *args, **kwargs):
            if bp.CTX_STATE["payload_started"] and not allowed(path):
                violations.append(("os.open", path))
                raise AssertionError("R-PRE: os.open(%r) after the first payload write" % (path,))
            return real_os_open(path, *args, **kwargs)

        def guarded_run(argv, timeout=120, env=None, cwd=None):
            if bp.CTX_STATE["payload_started"]:
                violations.append(("run", tuple(argv)))
                raise AssertionError("R-PRE: subprocess after the first payload write")
            return real_run(argv, timeout=timeout, env=env, cwd=cwd)

        bp.HOOKS["run"] = guarded_run
        with mock.patch.object(bp, "enumerate_components", spy_enumerate), \
                mock.patch("builtins.open", guarded_open), \
                mock.patch.object(os, "open", guarded_os_open):
            rc, out, err = build_apply(self.fx)
        self.assertEqual(violations, [])
        self.assertEqual(rc, 0, out + err)
        self.assertTrue(os.path.isfile(root + "/MANIFEST.json"))
        bp.CTX_STATE["payload_started"] = True
        with self.assertRaises(bp.RPreViolation):
            bp._run(["/usr/bin/true"])
        bp.CTX_STATE["payload_started"] = False

    def test_T22_post_copy_failure_writes_build_failed_and_no_manifest(self):
        def boom(ctx):
            raise RuntimeError("injected L4 failure")
        with mock.patch.object(bp, "l4_rescan", boom):
            rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 3, out + err)
        with open(self.fx.pkg + "/BUILD-FAILED.json") as fh:
            doc = json.load(fh)
        self.assertEqual((doc["schema_version"], doc["package_id"], doc["failed_step"], doc["error_type"], doc["error"]),
                         (4, self.fx.package_id, "PC4", "RuntimeError", "injected L4 failure"))
        self.assertFalse(os.path.lexists(self.fx.pkg + "/MANIFEST.json"))
        self.assertTrue(os.path.isfile(self.fx.pkg + "/MANIFEST-ENTRIES.jsonl"))
        self.assertFalse(os.path.lexists(self.fx.pkg + "/MANIFEST-ENTRIES.jsonl.partial"))

    def test_T23_root_files_exist_before_the_first_entry_is_listed(self):
        seen = {}

        def after_entry(index):
            if index == 0:
                seen["present"] = [rel for rel in ROOT_FILES if os.path.isfile(self.fx.pkg + "/" + rel)]
        bp.HOOKS["after_entry"] = after_entry
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(seen["present"], ROOT_FILES)

    def test_T24_manifest_absent_while_l4_runs(self):
        real_l4 = bp.l4_rescan
        seen = {}

        def spy_l4(ctx):
            seen["manifest"] = os.path.lexists(ctx.package_root + "/MANIFEST.json")
            seen["readme"] = os.path.isfile(ctx.package_root + "/README.md")
            real_l4(ctx)
        with mock.patch.object(bp, "l4_rescan", spy_l4):
            rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(seen, {"manifest": False, "readme": True})
        self.assertTrue(os.path.isfile(self.fx.pkg + "/MANIFEST.json"))

    def test_T25_payload_started_is_set_by_the_first_payload_entry(self):
        flags = {}
        real_write_root_files = bp.write_root_files

        def spy_write_root_files(ctx):
            flags["root_files"] = bp.CTX_STATE["payload_started"]
            real_write_root_files(ctx)

        def after_entry(index):
            if index == 0:
                flags["first_entry"] = bp.CTX_STATE["payload_started"]
        bp.HOOKS["after_entry"] = after_entry
        with mock.patch.object(bp, "write_root_files", spy_write_root_files):
            rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(flags, {"root_files": False, "first_entry": True})
        self.assertIs(bp.CTX_STATE["payload_started"], False)

    def test_T26_check_messages_never_print_secret_material(self):
        write_file(self.fx.home + "/.cache/huggingface/token", (SECRET_CANARY + "\n").encode("ascii"))
        for label, text in (("l3", "KeyError: " + SECRET_CANARY + "\n"), ("l2", "token=" + GITHUB_CANARY + "\n")):
            self.fx.run.overrides[(self.fx.fw_py, "tests/test_ltx_story_images.py")] = (1, text)
            rc, out, err = build_dry(self.fx)
            self.assertEqual(rc, 4, label + out + err)
            self.assertIn("FAIL B15 (message withheld: it contained secret material)", out.splitlines(), label)
            self.assertNotIn(SECRET_CANARY, out + err, label)
            self.assertNotIn(GITHUB_CANARY, out + err, label)


class TestCopyEngineE2E(BuildE2ECase):
    def test_T30_payload_matches_sources(self):
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 0, out + err)
        pkg = self.fx.pkg
        ctx = self.fx.ctx()
        src_by_p = dict((e["p"], e["_src"]) for e in ctx.entries if "p" in e)
        entries = bp.read_entries(pkg + "/MANIFEST-ENTRIES.jsonl")
        for entry in entries:
            if "p" not in entry:
                continue
            dst = pkg + "/" + entry["p"]
            if entry["k"] == "f":
                src = src_by_p[entry["p"]]
                with open(src, "rb") as a, open(dst, "rb") as b:
                    self.assertEqual(a.read(), b.read(), entry["p"])
                self.assertEqual(entry["h"], file_sha256(src))
                sst, dstat = os.lstat(src), os.lstat(dst)
                self.assertEqual(stat.S_IMODE(dstat.st_mode), stat.S_IMODE(sst.st_mode), entry["p"])
                self.assertEqual(dstat.st_mtime_ns, sst.st_mtime_ns)
                self.assertEqual(dstat.st_mtime_ns, entry["mt"])
            elif entry["k"] == "d":
                self.assertEqual(stat.S_IMODE(os.lstat(dst).st_mode), int(entry["m"], 8), entry["p"])
        self.assertEqual(stat.S_IMODE(os.lstat(pkg + "/payload/B4-ltx25-mlx-q8").st_mode), 0o750)

    def test_T31_source_appended_mid_copy_aborts_with_exit_5(self):
        target = self.fx.home + "/ltx-2-mlx/README.md"
        state = {"done": False}

        def after_chunk(src, nbytes):
            if src == target and not state["done"]:
                state["done"] = True
                with open(src, "ab") as fh:
                    fh.write(b"more\n")
        bp.HOOKS["after_chunk"] = after_chunk
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 5, out + err)
        self.assertIn("source changed mid-copy: " + target, err)
        self.assertFalse(os.path.lexists(self.fx.pkg + "/MANIFEST.json"))
        self.assertFalse(os.path.lexists(self.fx.pkg + "/payload/B1-ltx2mlx-repo/README.md"))

    def test_T32_source_changed_between_enumeration_and_copy(self):
        target = self.fx.home + "/ltx-2-mlx/README.md"

        def after_entry(index):
            if index == 0:
                write_file(target, b"a different, longer README\n")
        bp.HOOKS["after_entry"] = after_entry
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 5, out + err)
        self.assertIn("source changed since enumeration: " + target, err)
        self.assertFalse(os.path.lexists(self.fx.pkg + "/MANIFEST.json"))


class TestCredentialGatesE2E(BuildE2ECase):
    def test_T10_nested_token_file_refuses_apply(self):
        path = self.fx.home + "/Library/Python/3.13/lib/python/site-packages/torch/sub/token"
        write_file(path, b"not-a-secret-value-xyz\n")
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 4)
        self.assertTrue([line for line in out.splitlines() if line.startswith("FAIL B12 ") and path in line])
        self.assertFalse(os.path.lexists(self.fx.pkg))

    def test_T13_known_secret_across_boundary_and_inside_chunk(self):
        secret = SECRET_CANARY.encode("ascii")
        for label, content in (("boundary", b"a" * 50 + secret + b"b" * 50), ("inside", b"a" * 10 + secret + b"b" * 10)):
            fx = self.fresh_fixture()
            write_file(fx.home + "/.cache/huggingface/token", secret + b"\n")
            src = fx.home + "/ltx-2-mlx/packages/ltx_core/leak.txt"
            write_file(src, content)
            with mock.patch.object(bp, "CHUNK_SIZE", 64):
                rc, out, err = build_apply(fx)
            self.assertEqual(rc, 5, label + out + err)
            self.assertIn(src, err)
            self.assertNotIn(SECRET_CANARY, out + err)
            self.assertFalse(os.path.lexists(fx.pkg + "/payload/B1-ltx2mlx-repo/packages/ltx_core/leak.txt"))
            self.assertFalse(os.path.lexists(fx.pkg + "/MANIFEST.json"))
            with open(fx.pkg + "/MANIFEST-ENTRIES.jsonl.partial", "rb") as fh:
                partial = fh.read()
            self.assertNotIn(b"leak.txt", partial)
            self.assertNotIn(secret, partial)

    def test_RF1_long_jwt_like_token_in_unrecognized_file_is_caught_by_l3(self):
        token = "hf" + "_" + "eyJ0eXAi" + "." + "Q" * 800
        self.assertEqual(bp.l2_scan_bytes(token.encode("ascii")), [])
        write_file(self.fx.home + "/ltx-2-mlx/hf_cache/token", (token + "\n").encode("ascii"))
        src = self.fx.home + "/Library/Python/3.13/lib/python/site-packages/torch/hub_auth.cfg"
        write_file(src, b"[auth]\nvalue = " + token.encode("ascii") + b"\n")
        self.assertEqual(self.fx.ctx().l1_hits, [])
        with mock.patch.object(bp, "CHUNK_SIZE", 64):
            rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 5, out + err)
        self.assertIn(src, err)
        self.assertNotIn(token, out + err)
        self.assertNotIn("Q" * 64, out + err)
        self.assertFalse(os.path.lexists(self.fx.pkg + "/payload/F3-user-site/lib/python/site-packages/torch/hub_auth.cfg"))
        self.assertFalse(os.path.lexists(self.fx.pkg + "/MANIFEST.json"))

    def test_RF1b_secret_in_a_root_file_aborts_before_payload(self):
        write_file(self.fx.home + "/.cache/huggingface/token", (SECRET_CANARY + "\n").encode("ascii"))
        self.fx.run.freeze_text = "pkg==1.0\n# " + SECRET_CANARY + "\n"
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 5, out + err)
        self.assertIn("manifests/pip-freeze-framework-py313.txt", err)
        self.assertNotIn(SECRET_CANARY, out + err)
        self.assertFalse(os.path.lexists(self.fx.pkg + "/manifests/pip-freeze-framework-py313.txt"))
        self.assertFalse(os.path.lexists(self.fx.pkg + "/manifests/.pip-freeze-framework-py313.txt.tmp"))
        self.assertFalse(os.path.lexists(self.fx.pkg + "/payload"))
        self.assertFalse(os.path.lexists(self.fx.pkg + "/MANIFEST.json"))

    def test_T15_l4_catches_a_pattern_in_a_root_file(self):
        self.fx.run.freeze_text = "pkg==1.0\n# " + GITHUB_CANARY + "\n"
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 3, out + err)
        with open(self.fx.pkg + "/BUILD-FAILED.json") as fh:
            doc = json.load(fh)
        self.assertEqual((doc["failed_step"], doc["error_type"], doc["schema_version"]), ("PC4", "CredentialLeak", 4))
        self.assertIn("manifests/pip-freeze-framework-py313.txt", doc["error"])
        self.assertFalse(os.path.lexists(self.fx.pkg + "/MANIFEST.json"))
        self.assertNotIn(GITHUB_CANARY, out + err + json.dumps(doc))

    def test_l4_rejects_a_ds_store_dropped_into_the_package(self):
        def after_entry(index):
            if index == 0:
                write_file(self.fx.pkg + "/payload/.DS_Store", b"finder")
        bp.HOOKS["after_entry"] = after_entry
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 3, out + err)
        with open(self.fx.pkg + "/BUILD-FAILED.json") as fh:
            self.assertIn("DS_Store", json.load(fh)["error"])


def build_verify(fx, package_id=None):
    return run_main(bp.main, ["--verify-only", "--usb-root", fx.usb, "--package-id", package_id or fx.package_id])


class TestResume(BuildE2ECase):
    def interrupt_at(self, k):
        def after_entry(index):
            if index == k:
                raise RuntimeError("injected interrupt at entry %d" % k)
        bp.HOOKS["after_entry"] = after_entry
        result = build_apply(self.fx)
        bp.HOOKS["after_entry"] = lambda index: None
        return result

    def reference(self):
        rc, out, err = run_main(bp.main, ["--apply", "--usb-root", self.fx.usb2, "--package-id", self.fx.package_id])
        self.assertEqual(rc, 0, out + err)
        return self.fx.usb2 + "/" + self.fx.package_id

    def assert_identical(self, ref):
        with open(self.fx.pkg + "/MANIFEST-ENTRIES.jsonl", "rb") as a, open(ref + "/MANIFEST-ENTRIES.jsonl", "rb") as b:
            self.assertEqual(a.read(), b.read())
        self.assertEqual(payload_snapshot(self.fx.pkg), payload_snapshot(ref))

    def partial_lines(self):
        with open(self.fx.pkg + "/MANIFEST-ENTRIES.jsonl.partial", "rb") as fh:
            return fh.read().split(b"\n")[:-1]

    def test_T40_interrupt_then_resume_is_byte_identical(self):
        rc, out, err = self.interrupt_at(30)
        self.assertEqual(rc, 5, out + err)
        self.assertIn("injected interrupt at entry 30", err)
        self.assertFalse(os.path.lexists(self.fx.pkg + "/MANIFEST.json"))
        self.assertEqual(len(self.partial_lines()), 31)
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PASS B07 resume prefix: 31 of ", out)
        with open(self.fx.pkg + "/MANIFEST.json") as fh:
            self.assertIs(json.load(fh)["build"]["resumed"], True)
        self.assert_identical(self.reference())

    def test_T41_torn_final_line_is_truncated(self):
        rc, out, err = self.interrupt_at(30)
        self.assertEqual(rc, 5)
        with open(self.fx.pkg + "/MANIFEST-ENTRIES.jsonl.partial", "ab") as fh:
            fh.write(b'{"k":"f","c":"B')
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PASS B07 resume prefix: 31 of ", out)
        self.assert_identical(self.reference())

    def test_T42_listed_source_changed_fails_b07(self):
        rc, out, err = self.interrupt_at(30)
        self.assertEqual(rc, 5)
        readme = self.fx.home + "/ltx-2-mlx/README.md"
        write_file(readme, b"changed after the interrupted build\n")
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 4, out + err)
        self.assertIn("FAIL B07 source changed since the interrupted build: " + readme, out)

    def test_T43_corrupted_listed_payload_is_recopied(self):
        rc, out, err = self.interrupt_at(30)
        self.assertEqual(rc, 5)
        victim = self.fx.pkg + "/payload/B1-ltx2mlx-repo/README.md"
        with open(victim, "r+b") as fh:
            fh.write(b"L")
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PASS B07 resume prefix: 25 of ", out)
        self.assert_identical(self.reference())

    def test_T44_resume_with_manifest_present_fails_b07(self):
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 0)
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 4)
        self.assertTrue([line for line in out.splitlines() if line.startswith("FAIL B07 ") and "MANIFEST.json" in line])

    def test_RF2_resume_after_mid_copy_abort_completes_and_verifies(self):
        target = self.fx.home + "/ltx-2-mlx/README.md"
        state = {"done": False}

        def after_chunk(src, nbytes):
            if src == target and not state["done"]:
                state["done"] = True
                with open(src, "ab") as fh:
                    fh.write(b"appended while copying\n")
        bp.HOOKS["after_chunk"] = after_chunk
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 5)
        self.assertEqual([l for l in self.partial_lines() if b"B1-ltx2mlx-repo/README.md" in l], [])
        bp.HOOKS["after_chunk"] = lambda src, nbytes: None
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PASS B07 resume prefix: 25 of ", out)
        rc, out, err = build_verify(self.fx)
        self.assertEqual(rc, 0, out + err)
        with open(self.fx.pkg + "/payload/B1-ltx2mlx-repo/README.md", "rb") as fh:
            self.assertTrue(fh.read().endswith(b"appended while copying\n"))

    def test_RF4_resume_after_post_copy_failure(self):
        def boom(ctx):
            raise RuntimeError("injected L4 failure")
        with mock.patch.object(bp, "l4_rescan", boom):
            rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 3)
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 0, out + err)
        entries = bp.read_entries(self.fx.pkg + "/MANIFEST-ENTRIES.jsonl")
        self.assertIn("PASS B07 resume prefix: %d of %d entries verified" % (len(entries), len(entries)), out)
        self.assertFalse(os.path.lexists(self.fx.pkg + "/BUILD-FAILED.json"))
        self.assertTrue(os.path.isfile(self.fx.pkg + "/MANIFEST.json"))
        self.assertEqual(build_verify(self.fx)[0], 0)
        self.assert_identical(self.reference())

    def test_RF4b_resume_without_package_root_refuses(self):
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 4)
        self.assertIn("--resume given but %s does not exist" % self.fx.pkg, out)
        self.assertFalse(os.path.lexists(self.fx.pkg))


class TestVerifyOnly(BuildE2ECase):
    def setUp(self):
        BuildE2ECase.setUp(self)
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 0, out + err)

    def test_T50_clean_package_verifies_and_nothing_is_written(self):
        before = snapshot(self.fx.usb)
        rc, out, err = build_verify(self.fx)
        self.assertEqual(rc, 0, out + err)
        nfiles = len([e for e in bp.read_entries(self.fx.pkg + "/MANIFEST-ENTRIES.jsonl") if e["k"] == "f" and "p" in e])
        self.assertEqual(out.splitlines()[-1], "build_pkg: VERIFY ok: %d files re-hashed" % nfiles)
        self.assertEqual(snapshot(self.fx.usb), before)

    def test_T50_each_corruption_fails(self):
        repo, pin = PINS["H1"]

        def flip(path):
            with open(path, "r+b") as fh:
                first = fh.read(1)
                fh.seek(0)
                fh.write(b"L" if first != b"L" else b"M")

        def truncate(path):
            os.truncate(path, 0)

        def relink(path):
            os.unlink(path)
            os.symlink("../../blobs/other", path)

        def append(path, data):
            with open(path, "ab") as fh:
                fh.write(data)

        cases = [
            ("flipped byte", lambda r: flip(r + "/payload/B1-ltx2mlx-repo/README.md"), "hash mismatch"),
            ("truncated", lambda r: truncate(r + "/payload/B1-ltx2mlx-repo/README.md"), "size mismatch"),
            ("missing", lambda r: os.unlink(r + "/payload/A2-hw-gate-seeds/square.png"), "missing"),
            ("extra", lambda r: write_file(r + "/payload/B1-ltx2mlx-repo/extra.txt", b"extra"), "extra"),
            ("entries edited", lambda r: append(r + "/MANIFEST-ENTRIES.jsonl", b"\n"), "entries sha256 mismatch"),
            ("root file edited", lambda r: append(r + "/README.md", b"edited\n"), "root file hash mismatch"),
            ("build failed marker", lambda r: write_file(r + "/BUILD-FAILED.json", b"{}"), "build failed marker present"),
            ("symlink changed", lambda r: relink(r + "/payload/H1-hf-zimage/snapshots/" + pin + "/config.json"), "symlink mismatch"),
            ("ds_store", lambda r: write_file(r + "/payload/.DS_Store", b"ds"), "credential scan"),
            ("manifest missing", lambda r: os.unlink(r + "/MANIFEST.json"), "manifest missing or unreadable"),
        ]
        for index, (label, mutate, reason) in enumerate(cases):
            package_id = "ltx-chain-deploy-202610%02d" % index
            copy = self.fx.usb + "/" + package_id
            shutil.copytree(self.fx.pkg, copy, symlinks=True)
            mutate(copy)
            before = snapshot(copy)
            rc, out, err = build_verify(self.fx, package_id)
            self.assertEqual(rc, 1, label + out + err)
            self.assertTrue([line for line in out.splitlines() if line.startswith("FAIL VERIFY " + reason + ": ")], label + out)
            self.assertEqual(snapshot(copy), before, label)

    def test_T51_failure_lines_never_print_secret_material(self):
        write_file(self.fx.home + "/.cache/huggingface/token", (SECRET_CANARY + "\n").encode("ascii"))
        write_file(self.fx.pkg + "/payload/B1-ltx2mlx-repo/" + SECRET_CANARY + ".txt", b"extra")
        write_file(self.fx.pkg + "/payload/B1-ltx2mlx-repo/" + GITHUB_CANARY + ".txt", b"extra")
        rc, out, err = build_verify(self.fx)
        self.assertEqual(rc, 1, out + err)
        withheld = [line for line in out.splitlines()
                    if line.startswith("FAIL VERIFY extra: (path withheld: it contained secret material)")]
        self.assertEqual(len(withheld), 2, out)
        self.assertNotIn(SECRET_CANARY, out + err)
        self.assertNotIn(GITHUB_CANARY, out + err)


if __name__ == "__main__":
    unittest.main()
