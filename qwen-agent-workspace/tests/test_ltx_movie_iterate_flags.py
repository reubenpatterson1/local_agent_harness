"""Tests for bin/ltx-movie's bin/iterate-story companion flags (spec D3/D4).

Spec: docs/superpowers/specs/2026-10-03-iterate-story-design.md (Sections 4 and 7.4).
Run from the workspace root: python3 -m pytest tests/test_ltx_movie_iterate_flags.py -v

Plain pytest asserts only -- no check() helper, which reports false greens under
pytest. No test makes a real subprocess call: the autouse fixture below makes
subprocess.Popen and subprocess.run fail the test, and tests that reach Phase 1's
qwen-agent call install a recording fake over Popen first (the popen_calls fixture).
Exactly one test function per spec test ID, T-L1 through T-L11 (11 total), plus two
post-ship tests for the C1 audit-trail fix (13 total).
"""

import importlib.machinery
import os

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
ltx_movie = importlib.machinery.SourceFileLoader(
    "ltx_movie_iterate_flags", os.path.join(WS, "bin", "ltx-movie")).load_module()

STORY_ID = "iterate-flags"


@pytest.fixture(autouse=True)
def _no_real_subprocess(monkeypatch):
    """SC9 guard for every test: any real subprocess call from bin/ltx-movie fails it."""
    def _forbidden(*args, **kwargs):
        raise AssertionError("test made a real subprocess call")
    monkeypatch.setattr(ltx_movie.subprocess, "Popen", _forbidden)
    monkeypatch.setattr(ltx_movie.subprocess, "run", _forbidden)


class _FakeProc(object):
    """Stands in for the qwen-agent child: exits 1 and writes no story.md, so
    phase1_story returns 1 right after building and recording its command."""
    returncode = 1

    def communicate(self, timeout=None):
        return "", None


@pytest.fixture
def popen_calls(tmp_path, monkeypatch):
    """Point ltx_movie.WS at tmp_path, create the story dir, and record every Popen cmd.
    Requested explicitly, so it runs after the autouse guard and overrides its Popen."""
    monkeypatch.setattr(ltx_movie, "WS", str(tmp_path))
    (tmp_path / "generated" / "stories" / STORY_ID).mkdir(parents=True)
    calls = []

    def _recording_popen(cmd, **kwargs):
        calls.append(list(cmd))
        return _FakeProc()

    monkeypatch.setattr(ltx_movie.subprocess, "Popen", _recording_popen)
    return calls


def _run_phase1(argv):
    args = ltx_movie.build_parser().parse_args(argv)
    ltx_movie.phase1_story(args)
    return args


def _phase1_with_narrative(flags):
    return _run_phase1(["a narrative", "--story-id", STORY_ID, "--panels", "1"] + list(flags))


def _story_prompt_txt(tmp_path):
    path = tmp_path / "generated" / "stories" / STORY_ID / "story_prompt.txt"
    return path.read_text(encoding="utf-8")


# --- T-L5..T-L7: --story-prompt-override (spec 4.1) -----------------------------------

def test_tl5_story_prompt_override_used_verbatim(tmp_path, popen_calls):
    override = tmp_path / "override.txt"
    content = "Override — prompt\nline 2\n"
    override.write_text(content, encoding="utf-8")
    _phase1_with_narrative(["--story-prompt-override", str(override)])
    assert len(popen_calls) == 1
    assert popen_calls[0][-2] == "--user-prompt"
    assert popen_calls[0][-1] == content
    assert _story_prompt_txt(tmp_path) == content


def test_tl6_default_prompt_unchanged_without_override(tmp_path, popen_calls):
    args = _phase1_with_narrative([])
    expected = ltx_movie.build_story_prompt("a narrative", STORY_ID, 1, False, False,
                                            seconds=ltx_movie._clip_seconds(args))
    assert len(popen_calls) == 1
    assert popen_calls[0][-1] == expected
    assert _story_prompt_txt(tmp_path) == expected


def test_tl7_missing_override_file_exits_2(tmp_path, popen_calls, capsys):
    rc = ltx_movie.main(["a narrative", "--story-id", STORY_ID,
                         "--story-prompt-override", str(tmp_path / "missing.txt")])
    assert rc == 2
    assert "--story-prompt-override file not found" in capsys.readouterr().err
    assert popen_calls == []


# --- T-L1..T-L4: --danger-auto-approve only with --force-story + --no-review (spec 4.2) ---

def test_tl1_force_story_and_no_review_add_danger_auto_approve(popen_calls):
    _phase1_with_narrative(["--force-story", "--no-review"])
    assert len(popen_calls) == 1
    cmd = popen_calls[0]
    assert "--danger-auto-approve" in cmd
    assert cmd.count("--danger-auto-approve") == 1
    assert cmd[-2] == "--user-prompt"


def test_tl2_force_story_alone_omits_danger_auto_approve(popen_calls):
    _phase1_with_narrative(["--force-story"])
    assert len(popen_calls) == 1
    assert "--danger-auto-approve" not in popen_calls[0]


def test_tl3_no_review_alone_omits_danger_auto_approve(popen_calls):
    _phase1_with_narrative(["--no-review"])
    assert len(popen_calls) == 1
    assert "--danger-auto-approve" not in popen_calls[0]


def test_tl4_no_flags_omit_danger_auto_approve(popen_calls):
    _phase1_with_narrative([])
    assert len(popen_calls) == 1
    assert "--danger-auto-approve" not in popen_calls[0]


# --- T-L8..T-L11: --story-only and optional narrative (spec 4.3) ------------------------

def test_tl8_story_only_runs_phase1_only():
    args = ltx_movie.build_parser().parse_args(["a narrative", "--story-id", STORY_ID,
                                                "--story-only"])
    assert args.story_server_stop_after_story is True
    names = tuple(f.__name__ for f in ltx_movie._phase_sequence(args))
    assert names == ("phase1_story",)


def test_tl9_story_only_with_seed_image_keeps_phase0():
    args = ltx_movie.build_parser().parse_args(["a narrative", "--story-id", STORY_ID,
                                                "--story-only", "--seed-image", "x.png"])
    names = tuple(f.__name__ for f in ltx_movie._phase_sequence(args))
    assert names == ("phase0_seed", "phase1_story")


def test_tl10_no_narrative_and_no_override_exits_2(popen_calls, capsys):
    with pytest.raises(SystemExit) as excinfo:
        ltx_movie.main(["--story-id", STORY_ID])
    assert excinfo.value.code == 2
    assert ("either a narrative argument or --story-prompt-override is required"
            in capsys.readouterr().err)
    assert popen_calls == []


def test_tl11_override_without_narrative_does_not_crash_phase1(tmp_path, popen_calls):
    override = tmp_path / "override.txt"
    override.write_text("Override only\n", encoding="utf-8")
    args = _run_phase1(["--story-id", STORY_ID, "--panels", "1",
                        "--story-prompt-override", str(override)])
    assert args.narrative is None
    assert len(popen_calls) == 1
    assert popen_calls[0][-1] == "Override only\n"
    assert _story_prompt_txt(tmp_path) == "Override only\n"


def test_danger_auto_approve_trace_reaches_stdout_on_success(tmp_path, monkeypatch, capsys):
    """C1 fix: the [danger-auto] trail must not be silently discarded on a successful
    (exit 0) qwen-agent call -- that's exactly the case the prior code dropped it in."""
    monkeypatch.setattr(ltx_movie, "WS", str(tmp_path))
    story_dir = tmp_path / "generated" / "stories" / STORY_ID
    story_dir.mkdir(parents=True)
    (story_dir / "story.md").write_text(
        "## Panel 1\nImage: a test image.\nMotion: a test motion.\nNarration: a line.\n",
        encoding="utf-8")
    out = ("some qwen-agent chatter\n"
           "[danger-auto] write_file generated/stories/%s/story.md\n" % STORY_ID)

    class _FakeProcSuccess(object):
        returncode = 0

        def communicate(self, timeout=None):
            return out, None

    monkeypatch.setattr(ltx_movie.subprocess, "Popen", lambda cmd, **kw: _FakeProcSuccess())
    _run_phase1(["a narrative", "--story-id", STORY_ID, "--panels", "1",
                "--force-story", "--no-review"])
    assert "[danger-auto] write_file" in capsys.readouterr().out


def test_danger_auto_approve_trace_not_printed_without_the_flag(tmp_path, monkeypatch, capsys):
    """The same captured output must NOT be printed when --danger-auto-approve was never
    in the command (--force-story alone) -- this isn't a blanket verbosity change."""
    monkeypatch.setattr(ltx_movie, "WS", str(tmp_path))
    story_dir = tmp_path / "generated" / "stories" / STORY_ID
    story_dir.mkdir(parents=True)
    (story_dir / "story.md").write_text(
        "## Panel 1\nImage: a test image.\nMotion: a test motion.\nNarration: a line.\n",
        encoding="utf-8")
    out = ("some qwen-agent chatter\n"
           "[danger-auto] write_file generated/stories/%s/story.md\n" % STORY_ID)

    class _FakeProcSuccess(object):
        returncode = 0

        def communicate(self, timeout=None):
            return out, None

    monkeypatch.setattr(ltx_movie.subprocess, "Popen", lambda cmd, **kw: _FakeProcSuccess())
    _run_phase1(["a narrative", "--story-id", STORY_ID, "--panels", "1", "--force-story"])
    assert "[danger-auto]" not in capsys.readouterr().out
