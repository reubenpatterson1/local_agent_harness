"""Tests for pipeline_log.py and the wiring of run_logged into bin scripts.

Run from the workspace root: python3 -m pytest tests/test_pipeline_log.py -v
"""

import importlib.machinery
import os
import re
import subprocess
import sys
import types

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
import pipeline_log  # noqa: E402

judge_stills = importlib.machinery.SourceFileLoader(
    "judge_stills", os.path.join(WS, "bin", "judge-stills")).load_module()

ltx_movie = importlib.machinery.SourceFileLoader(
    "ltx_movie", os.path.join(WS, "bin", "ltx-movie")).load_module()

ltx_story_images = importlib.machinery.SourceFileLoader(
    "ltx_story_images", os.path.join(WS, "bin", "ltx-story-images")).load_module()

iterate_story = importlib.machinery.SourceFileLoader(
    "iterate_story", os.path.join(WS, "bin", "iterate-story")).load_module()


@pytest.fixture(autouse=True)
def _clear_env_flag(monkeypatch):
    monkeypatch.delenv(pipeline_log.ENV_FLAG, raising=False)


def _read_log(story_dir):
    path = os.path.join(story_dir, "iterate-story.log")
    with open(path, encoding="utf-8") as f:
        return f.read()


# --- Unit tests for pipeline_log functions ---

def test_p1_argv_value():
    av = pipeline_log.argv_value
    assert av(["--story-id", "x"], "--story-id") == "x"
    assert av(["--story-id=y"], "--story-id") == "y"
    assert av(["--story-id", "a", "--story-id", "b"], "--story-id") == "b"
    assert av([], "--story-id") is None
    assert av(["--story-id"], "--story-id") is None
    assert av(["--story-idx", "z"], "--story-id") is None


def test_p2_collapse_cr():
    assert pipeline_log.collapse_cr("a\rb\rc\nd") == "c\nd"
    assert pipeline_log.collapse_cr("x\ry\r\n") == "y\n"
    assert pipeline_log.collapse_cr("plain\n") == "plain\n"


def test_p3_success_record(tmp_path, capsys):
    def main():
        print("hello")
        sys.stderr.write("warn\n")
        return 0

    rc = pipeline_log.run_logged("judge-stills", str(tmp_path), main, ["prog", "--story-id", "x"])
    assert rc == 0

    captured = capsys.readouterr()
    assert "hello" in captured.out
    assert "warn" in captured.err

    text = _read_log(str(tmp_path))
    pattern = (r"^=== stage: judge-stills === \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n"
               r"cmd: \['prog', '--story-id', 'x'\]\n"
               r"exit: 0\n"
               r"--- output ---\n"
               r"hello\n"
               r"warn\n"
               r"--- end ---\n\n$")
    assert re.fullmatch(pattern, text) is not None


def test_p4_nonzero_return(tmp_path):
    def main():
        return 2

    rc = pipeline_log.run_logged("judge-stills", str(tmp_path), main, ["prog"])
    assert rc == 2
    assert "exit: 2\n" in _read_log(str(tmp_path))


def test_p5_system_exit_reraised(tmp_path):
    def main():
        raise SystemExit(3)

    with pytest.raises(SystemExit) as exc_info:
        pipeline_log.run_logged("judge-stills", str(tmp_path), main, ["prog"])
    assert exc_info.value.code == 3
    assert "exit: 3\n" in _read_log(str(tmp_path))


def test_p6_exception_reraised_with_traceback(tmp_path):
    def main():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        pipeline_log.run_logged("judge-stills", str(tmp_path), main, ["prog"])
    text = _read_log(str(tmp_path))
    assert "exit: 1\n" in text
    assert "RuntimeError: boom" in text


def test_p7_env_flag_skips(tmp_path, monkeypatch):
    monkeypatch.setenv(pipeline_log.ENV_FLAG, "1")

    results = []

    def main():
        print("x")
        results.append(True)
        return 5

    rc = pipeline_log.run_logged("judge-stills", str(tmp_path), main, ["prog"])
    assert rc == 5
    assert not (tmp_path / "iterate-story.log").exists()


def test_p8_missing_story_dir(tmp_path, capsys):
    def main():
        return 7

    rc = pipeline_log.run_logged("judge-stills", None, main, ["prog"])
    assert rc == 7

    nope = str(tmp_path / "nope")
    rc2 = pipeline_log.run_logged("judge-stills", nope, main, ["prog"])
    assert rc2 == 7
    assert not (tmp_path / "nope").exists()
    assert "warning" not in capsys.readouterr().err


def test_p9_write_failure_warns(tmp_path, capsys):
    (tmp_path / "iterate-story.log").mkdir()

    def main():
        return 4

    rc = pipeline_log.run_logged("judge-stills", str(tmp_path), main, ["prog"])
    assert rc == 4
    captured = capsys.readouterr()
    assert "warning: could not append to" in captured.err


def test_p10_appends(tmp_path):
    log_path = tmp_path / "iterate-story.log"
    log_path.write_text("EXISTING\n", encoding="utf-8")

    def main():
        return 0

    pipeline_log.run_logged("a", str(tmp_path), main, ["p"])
    pipeline_log.run_logged("b", str(tmp_path), main, ["p"])

    text = _read_log(str(tmp_path))
    assert text.startswith("EXISTING\n")
    assert text.index("=== stage: a ===") < text.index("=== stage: b ===")


def test_p11_streams_restored(tmp_path):
    orig_out = sys.stdout
    orig_err = sys.stderr

    def main_ok():
        return 0

    pipeline_log.run_logged("x", str(tmp_path), main_ok, ["p"])
    assert sys.stdout is orig_out
    assert sys.stderr is orig_err

    def main_raise():
        raise RuntimeError("err")

    with pytest.raises(RuntimeError):
        pipeline_log.run_logged("y", str(tmp_path), main_raise, ["p"])
    assert sys.stdout is orig_out
    assert sys.stderr is orig_err


def test_p12_progress_collapsed(tmp_path):
    def main():
        sys.stderr.write("0%\r50%\r100%\n")
        return 0

    pipeline_log.run_logged("x", str(tmp_path), main, ["p"])
    text = _read_log(str(tmp_path))
    assert "--- output ---\n100%\n--- end ---" in text


# --- Wiring tests ---

def test_w1_story_dir_resolvers():
    # judge_stills
    assert (judge_stills._pipeline_log_story_dir(["--story-id", "abc"])
            == os.path.join(WS, "generated", "stories", "abc"))
    assert judge_stills._pipeline_log_story_dir([]) is None

    # ltx_movie
    assert (ltx_movie._pipeline_log_story_dir(["--story-id", "abc"])
            == os.path.join(WS, "generated", "stories", "abc"))
    assert ltx_movie._pipeline_log_story_dir([]) is None

    # ltx_story_images
    assert (ltx_story_images._pipeline_log_story_dir(["--story-md", "/x/y/story.md"])
            == "/x/y")
    assert (ltx_story_images._pipeline_log_story_dir(["--story-md", "rel/story.md"])
            == os.path.dirname(os.path.abspath("rel/story.md")))
    assert ltx_story_images._pipeline_log_story_dir([]) is None


def test_w2_main_blocks_wired():
    for script_name, label in (("judge-stills", "judge-stills"),
                                ("ltx-movie", "ltx-movie"),
                                ("ltx-story-images", "ltx-story-images")):
        path = os.path.join(WS, "bin", script_name)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        expected = ('pipeline_log.run_logged("%s", _pipeline_log_story_dir(sys.argv[1:]), main, sys.argv)'
                    % label)
        assert expected in text, "Missing run_logged wiring in %s" % script_name
        assert "    sys.exit(main())" not in text, "Old sys.exit(main()) still present in %s" % script_name


def test_w3_ltx_story_images_dry_run_subprocess(tmp_path):
    story_md = tmp_path / "story.md"
    story_md.write_text("## Panel 1 \u2014 Test\nImage: A green frog on a lily pad.\n",
                        encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != pipeline_log.ENV_FLAG}

    cmd = [sys.executable, os.path.join(WS, "bin", "ltx-story-images"),
           "--story-md", str(story_md),
           "--out-dir", str(tmp_path / "images"),
           "--only", "1",
           "--dry-run"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
    assert result.returncode == 0, (
        "dry-run failed (unrelated to logging):\nstdout: %s\nstderr: %s" % (result.stdout, result.stderr))

    log_path = tmp_path / "iterate-story.log"
    text = log_path.read_text(encoding="utf-8")
    assert "=== stage: ltx-story-images ===" in text
    assert "exit: 0\n" in text
    assert "1 | " in text

    log_path.unlink()
    env2 = dict(env)
    env2[pipeline_log.ENV_FLAG] = "1"
    result2 = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env2)
    assert result2.returncode == 0
    assert not log_path.exists()


def test_w4_iterate_story_child_env(monkeypatch):
    monkeypatch.setenv("PIPELINE_LOG_CANARY", "c")

    recorded = {}

    def fake_run(cmd, **kwargs):
        recorded.update(kwargs)
        obj = types.SimpleNamespace(returncode=0, stdout="")
        return obj

    monkeypatch.setattr(iterate_story.subprocess, "run", fake_run)
    iterate_story._run(["true"])
    assert recorded["env"][pipeline_log.ENV_FLAG] == "1"
    assert recorded["env"]["PIPELINE_LOG_CANARY"] == "c"
