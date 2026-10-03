"""Tests for bin/iterate-story.

Spec: docs/superpowers/specs/2026-10-03-iterate-story-design.md (Section 7).
Run from the workspace root: python3 -m pytest tests/test_iterate_story.py -v

Plain pytest asserts only -- no check() helper, which reports false greens under
pytest. No test makes a real subprocess, API, or generation call: the autouse
fixture below makes subprocess.run fail the test, and every test that reaches a
subprocess installs the recording FakeRun first. Story directories live under
tmp_path. Exactly one test function per spec test ID (16 total: T-P1, T-P2, T-P2b,
T-P3, T-P4, T-P5, T-M1..T-M9 and T-M6b); multi-case IDs loop inside one function.
"""

import importlib.machinery
import json
import os
import re
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
iterate_story = importlib.machinery.SourceFileLoader(
    "iterate_story", os.path.join(WS, "bin", "iterate-story")).load_module()


@pytest.fixture(autouse=True)
def _no_real_subprocess(monkeypatch):
    """SC9 guard for every test: a real subprocess.run from bin/iterate-story fails it."""
    def _forbidden(*args, **kwargs):
        raise AssertionError("test made a real subprocess call")
    monkeypatch.setattr(iterate_story.subprocess, "run", _forbidden)


# --- T-P1, T-P2, T-P2b: pinned panel count and re-injection (spec 3.1, 3.2) ------------

def test_tp1_count_panels():
    twenty = "".join("## Panel %d — Beat %d\nMotion: m\nNarration: n\n\n" % (i, i)
                     for i in range(1, 21))
    assert iterate_story.count_panels(twenty) == 20
    mixed = ("## Panel 1 — a\nThe guard points at Panel 4 on the wall.\n"
             "### Panel 9 — sub-heading\n ## Panel 8 — leading space\n"
             "## Panel 2 — b\n## Panel 3 — c\n")
    assert iterate_story.count_panels(mixed) == 3


def test_tp2_build_reinjection_and_fallback_append():
    assert iterate_story.build_reinjection(20) == (
        "\n\nThe file must contain EXACTLY 20 panel sections, numbered 1 through 20 in order.")
    assert (iterate_story.build_next_prompt("ABC\n", 20)
            == "ABC\n" + iterate_story.build_reinjection(20))


def test_tp2b_build_next_prompt_replaces_conflicting_declaration():
    assert iterate_story.PANEL_COUNT_DECLARATION_RE.pattern == (
        r"The file must contain EXACTLY \d+ panel sections?, numbered 1 through \d+ in order\.")
    revised = ("Here is the revised prompt.\n\nThe file must contain EXACTLY 30 panel sections, "
               "numbered 1 through 30 in order.\n\nFocus more on pacing in the middle act.")
    result = iterate_story.build_next_prompt(revised, 20)
    assert "EXACTLY 30" not in result
    assert result.count("EXACTLY 20") == 1
    assert result == ("Here is the revised prompt.\n\n\n\nFocus more on pacing in the middle act."
                      + iterate_story.build_reinjection(20))
    # Every occurrence is removed, and the singular "section" form matches too.
    twice = ("The file must contain EXACTLY 30 panel sections, numbered 1 through 30 in order."
             " X The file must contain EXACTLY 1 panel section, numbered 1 through 1 in order.")
    assert (iterate_story.build_next_prompt(twice, 20)
            == " X " + iterate_story.build_reinjection(20))


# --- T-P3: version-suffix scan (spec 1.4) ---------------------------------------------

def test_tp3_find_version_base(tmp_path):
    def _dir(name, files):
        d = tmp_path / name
        d.mkdir()
        for f in files:
            (d / f).write_text("x", encoding="utf-8")
        return str(d)

    ronin_shape = _dir("a", ["story.v1.md", "story.v2.md", "story_prompt.v1.txt",
                             "story_prompt.v2.txt", "judgment.v1.json", "judgment.v2.json"])
    assert iterate_story.find_version_base(ronin_shape) == 2
    assert iterate_story.find_version_base(_dir("b", [])) == 0
    assert iterate_story.find_version_base(_dir("c", ["judgment.v7.json"])) == 7
    assert iterate_story.find_version_base(
        _dir("d", ["story.v2.md.bak", "story.vX.md", "story.v.md"])) == 0
    # Numeric, not lexicographic, maximum across families.
    assert iterate_story.find_version_base(
        _dir("e", ["story.v9.md", "story_prompt.v10.txt"])) == 10


# --- T-P4, T-P5: stopping criteria and best-round selection (spec 3.3, 1.5) -----------

def test_tp4_evaluate_stop():
    assert (iterate_story.STOP_THRESHOLD, iterate_story.STOP_PLATEAU,
            iterate_story.STOP_MAX_ROUNDS) == ("threshold met", "plateaued",
                                               "max-rounds reached")
    cases = [
        ([(7, 7, 7, 7)], 7, 5, "threshold met"),
        ([(7, 7, 7, 6)], 7, 5, None),
        ([(5, 5, 5, 4), (5, 5, 5, 4)], 9, 5, "plateaued"),
        ([(5, 5, 5, 4), (6, 4, 4, 3)], 9, 5, None),
        ([(4, 4, 4, 4), (6, 6, 6, 6), (6, 6, 6, 6)], 9, 5, "plateaued"),
        ([(8, 8, 8, 8), (8, 8, 8, 8)], 7, 2, "threshold met"),
        ([(5, 5, 5, 4), (5, 5, 5, 4)], 9, 2, "plateaued"),
        ([(4, 4, 4, 4), (5, 4, 4, 4)], 9, 2, "max-rounds reached"),
        ([(4, 4, 4, 4)], 9, 1, "max-rounds reached"),
    ]
    for i, (history, threshold, max_rounds, expected) in enumerate(cases, 1):
        got = iterate_story.evaluate_stop(history, threshold, max_rounds)
        assert got == expected, "case %d: got %r, expected %r" % (i, got, expected)


def test_tp5_select_best_round():
    cases = [
        ([(1, (5, 4, 4, 3)), (2, (5, 5, 5, 4)), (3, (9, 9, 9, 3))], 2),
        ([(1, (4, 4, 4, 4)), (2, (9, 4, 4, 4))], 2),
        ([(1, (5, 5, 5, 4)), (2, (5, 5, 5, 4))], 1),
    ]
    for i, (rounds, expected) in enumerate(cases, 1):
        got = iterate_story.select_best_round(rounds)
        assert got == expected, "case %d: got %r, expected %r" % (i, got, expected)


# --- Loop tests: shared fixtures and the recording subprocess fake (spec 7.1) ---------

SCORE_KEYS = ("pacing_progression", "action_plausibility", "visual_specificity", "continuity")
STORY_ID = "iterate-test"
PINNED = 4
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
REGEN_1 = "## Panel 1 — regen 1\nMotion: m\nNarration: n\n"


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _story_md(panels):
    return "".join("## Panel %d — Beat %d\nMotion: m%d\nNarration: n%d\n\n" % (i, i, i, i)
                   for i in range(1, panels + 1))


def _make_story(tmp_path, monkeypatch):
    """Point iterate_story.WS at tmp_path and create generated/stories/STORY_ID with a
    PINNED-panel story.md and a story_prompt.txt. Returns the story dir."""
    monkeypatch.setattr(iterate_story, "WS", str(tmp_path))
    story_dir = os.path.join(str(tmp_path), "generated", "stories", STORY_ID)
    os.makedirs(story_dir)
    _write(os.path.join(story_dir, "story.md"), _story_md(PINNED))
    _write(os.path.join(story_dir, "story_prompt.txt"), "ORIGINAL PROMPT\n")
    return story_dir


def _summary(story_dir):
    with open(os.path.join(story_dir, "run-summary.json"), encoding="utf-8") as f:
        return json.load(f)


def _assert_live_equals_archive(story_dir, version):
    for live, archive in (("story.md", "story.v%d.md"), ("story_prompt.txt",
                                                         "story_prompt.v%d.txt"),
                          ("judgment.json", "judgment.v%d.json")):
        assert (_read_bytes(os.path.join(story_dir, live))
                == _read_bytes(os.path.join(story_dir, archive % version))), live


class FakeRun(object):
    """Recording fake for iterate_story.subprocess.run(cmd, **kwargs) (spec 7.1).
    Records (cmd, kwargs) and dispatches on os.path.basename(cmd[1]).

    judge_script, one entry per judge-story call: a 4-tuple of scores means success
    (writes judgment.json with revised_prompt "REVISED-<k>" and story_prompt.revised.txt,
    rc 0); an int means fail with that rc (writes nothing, output "judge boom").
    ltx_script, one entry per ltx-movie call: 0 means success (story.md = regen <k>,
    story_prompt.txt = the override content); a nonzero int means fail with that rc after
    writing story.md = "GARBAGE"; "noop" means write nothing and return rc 0. Calls past
    the end of ltx_script succeed. k counts calls per tool, from 1.
    """

    def __init__(self, story_dir, judge_script, ltx_script=()):
        self.story_dir = story_dir
        self.judge_script = list(judge_script)
        self.ltx_script = list(ltx_script)
        self.calls = []
        self.overrides = []
        self.judge_calls = 0
        self.ltx_calls = 0

    def __call__(self, cmd, **kwargs):
        self.calls.append((list(cmd), kwargs))
        tool = os.path.basename(cmd[1])
        if tool == "judge-story":
            self.judge_calls += 1
            k = self.judge_calls
            entry = self.judge_script.pop(0)
            if isinstance(entry, int):
                return subprocess.CompletedProcess(cmd, entry, stdout="judge boom\n")
            judgment = {"scores": dict(zip(SCORE_KEYS, entry)), "critique": "c%d" % k,
                        "revised_prompt": "REVISED-%d" % k}
            _write(os.path.join(self.story_dir, "judgment.json"),
                   json.dumps(judgment, indent=2) + "\n")
            _write(os.path.join(self.story_dir, "story_prompt.revised.txt"), "REVISED-%d" % k)
            return subprocess.CompletedProcess(cmd, 0, stdout="judged %d\n" % k)
        if tool == "ltx-movie":
            self.ltx_calls += 1
            k = self.ltx_calls
            override_path = cmd[cmd.index("--story-prompt-override") + 1]
            with open(override_path, encoding="utf-8") as f:
                content = f.read()
            self.overrides.append((override_path, content))
            entry = self.ltx_script.pop(0) if self.ltx_script else 0
            if entry == "noop":
                return subprocess.CompletedProcess(cmd, 0, stdout="nothing written\n")
            if entry != 0:
                _write(os.path.join(self.story_dir, "story.md"), "GARBAGE")
                return subprocess.CompletedProcess(cmd, entry, stdout="ltx boom\n")
            _write(os.path.join(self.story_dir, "story.md"),
                   "## Panel 1 — regen %d\nMotion: m\nNarration: n\n" % k)
            _write(os.path.join(self.story_dir, "story_prompt.txt"), content)
            return subprocess.CompletedProcess(cmd, 0, stdout="regenerated %d\n" % k)
        raise AssertionError("unexpected subprocess call: %r" % (cmd,))


# --- T-M1..T-M4, T-M7, T-M8: happy-path loop, arguments, preconditions (spec 1-5) -----

def test_tm1_threshold_stop_happy_path(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch)
    fake = FakeRun(story_dir, [(4, 4, 5, 2), (7, 7, 7, 7)])
    monkeypatch.setattr(iterate_story.subprocess, "run", fake)
    assert iterate_story.main(["--story-id", STORY_ID, "--threshold", "7"]) == 0
    assert (fake.judge_calls, fake.ltx_calls) == (2, 1)
    for v in (1, 2):
        for name in ("story.v%d.md", "story_prompt.v%d.txt", "judgment.v%d.json"):
            assert os.path.isfile(os.path.join(story_dir, name % v)), name % v
    assert not os.path.exists(os.path.join(story_dir, "story.v3.md"))
    assert capsys.readouterr().out == (
        "Round 1: pacing_progression=4 action_plausibility=4 visual_specificity=5 continuity=2\n"
        "Round 2: pacing_progression=7 action_plausibility=7 visual_specificity=7 continuity=7\n"
        "Stopped: threshold met. Best round: 2 (v2), promoted to story.md, story_prompt.txt, "
        "judgment.json.\n")
    _assert_live_equals_archive(story_dir, 2)
    with open(os.path.join(story_dir, "run-summary.json"), encoding="utf-8") as f:
        raw = f.read()
    assert raw.startswith('{\n  "stop_reason": ') and raw.endswith("}\n")
    summary = json.loads(raw)
    assert list(summary) == ["stop_reason", "best_round", "rounds"]
    assert summary["stop_reason"] == "threshold met"
    assert summary["best_round"] == 2
    assert [r["round"] for r in summary["rounds"]] == [1, 2]
    assert [r["version"] for r in summary["rounds"]] == ["v1", "v2"]
    for record, scores in zip(summary["rounds"], [(4, 4, 5, 2), (7, 7, 7, 7)]):
        assert list(record) == ["round", "version", "scores", "timestamp"]
        assert list(record["scores"]) == list(SCORE_KEYS)
        assert tuple(record["scores"].values()) == scores
        assert TIMESTAMP_RE.match(record["timestamp"]), record["timestamp"]


def test_tm2_subprocess_argv_and_override_file(tmp_path, monkeypatch):
    story_dir = _make_story(tmp_path, monkeypatch)
    fake = FakeRun(story_dir, [(4, 4, 5, 2), (7, 7, 7, 7)])
    monkeypatch.setattr(iterate_story.subprocess, "run", fake)
    assert iterate_story.main(["--story-id", STORY_ID, "--threshold", "7"]) == 0
    assert ([os.path.basename(cmd[1]) for cmd, _ in fake.calls]
            == ["judge-story", "ltx-movie", "judge-story"])
    judge_cmd = [sys.executable, os.path.join(iterate_story.WS, "bin", "judge-story"),
                 "--story-id", STORY_ID, "--target-panels", str(PINNED)]
    assert fake.calls[0][0] == judge_cmd
    assert fake.calls[2][0] == judge_cmd
    override_path, override_content = fake.overrides[0]
    assert fake.calls[1][0] == [sys.executable, os.path.join(iterate_story.WS, "bin", "ltx-movie"),
                                "--story-id", STORY_ID, "--panels", str(PINNED),
                                "--force-story", "--no-review", "--story-only",
                                "--story-prompt-override", override_path]
    assert "--danger-auto-approve" not in fake.calls[1][0]
    assert override_content == "REVISED-1" + iterate_story.build_reinjection(PINNED)
    assert not override_path.startswith(story_dir)
    assert not os.path.exists(override_path)
    for _, kwargs in fake.calls:
        assert kwargs == {"cwd": iterate_story.WS, "stdin": subprocess.DEVNULL,
                          "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
                          "text": True}

    with open(os.path.join(story_dir, iterate_story.LOG_FILE_NAME), encoding="utf-8") as f:
        log_text = f.read()
    assert log_text.count("=== round 1: judge-story ===") == 1
    assert log_text.count("=== round 1: ltx-movie ===") == 1
    assert log_text.count("=== round 2: judge-story ===") == 1
    assert "exit: 0" in log_text
    assert "judged 1" in log_text and "regenerated 1" in log_text and "judged 2" in log_text


def test_tm3_existing_versions_and_earliest_tie_promotion(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch)
    old = {}
    for v in (1, 2):
        for name, text in (("story.v%d.md" % v, "OLD STORY v%d\n" % v),
                           ("story_prompt.v%d.txt" % v, "OLD PROMPT v%d\n" % v),
                           ("judgment.v%d.json" % v, '{"revised_prompt": "OLD-%d"}\n' % v)):
            _write(os.path.join(story_dir, name), text)
            old[name] = text.encode("utf-8")
    pre_loop_story = _read_bytes(os.path.join(story_dir, "story.md"))
    fake = FakeRun(story_dir, [(5, 4, 4, 3), (5, 5, 5, 4), (5, 5, 5, 4)])
    monkeypatch.setattr(iterate_story.subprocess, "run", fake)
    assert iterate_story.main(["--story-id", STORY_ID, "--threshold", "9"]) == 0
    assert (fake.judge_calls, fake.ltx_calls) == (3, 2)
    summary = _summary(story_dir)
    assert summary["stop_reason"] == "plateaued"
    assert [r["version"] for r in summary["rounds"]] == ["v3", "v4", "v5"]
    assert not os.path.exists(os.path.join(story_dir, "story.v6.md"))
    assert _read_bytes(os.path.join(story_dir, "story.v3.md")) == pre_loop_story
    assert _read_bytes(os.path.join(story_dir, "story.v4.md")) == REGEN_1.encode("utf-8")
    for name, data in old.items():
        assert _read_bytes(os.path.join(story_dir, name)) == data, name
    assert summary["best_round"] == 2
    _assert_live_equals_archive(story_dir, 4)
    with open(os.path.join(story_dir, "judgment.v4.json"), encoding="utf-8") as f:
        revised = json.load(f)["revised_prompt"]
    assert revised == "REVISED-2"
    with open(os.path.join(story_dir, "story_prompt.revised.txt"), encoding="utf-8") as f:
        assert f.read() == revised
    assert capsys.readouterr().out.endswith(
        "Stopped: plateaued. Best round: 2 (v4), promoted to story.md, story_prompt.txt, "
        "judgment.json.\n")


def test_tm4_max_rounds_stop(tmp_path, monkeypatch):
    story_dir = _make_story(tmp_path, monkeypatch)
    fake = FakeRun(story_dir, [(3, 3, 3, 3), (4, 4, 4, 4)])
    monkeypatch.setattr(iterate_story.subprocess, "run", fake)
    assert iterate_story.main(["--story-id", STORY_ID, "--threshold", "9",
                               "--max-rounds", "2"]) == 0
    assert (fake.judge_calls, fake.ltx_calls) == (2, 1)
    summary = _summary(story_dir)
    assert summary["stop_reason"] == "max-rounds reached"
    assert summary["best_round"] == 2


def test_tm7_preconditions_exit_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(iterate_story, "WS", str(tmp_path))
    stories = os.path.join(str(tmp_path), "generated", "stories")
    os.makedirs(os.path.join(stories, "a"))
    _write(os.path.join(stories, "a", "story_prompt.txt"), "P\n")
    os.makedirs(os.path.join(stories, "b"))
    _write(os.path.join(stories, "b", "story.md"), _story_md(PINNED))
    os.makedirs(os.path.join(stories, "c"))
    _write(os.path.join(stories, "c", "story.md"),
           "# Title\n### Panel 1 — sub\n ## Panel 2 — indented\nPanel 4 in body text\n")
    _write(os.path.join(stories, "c", "story_prompt.txt"), "P\n")
    for story_id, expected in (("a", "story.md not found"),
                               ("b", "story_prompt.txt not found"),
                               ("c", 'no "## Panel" headers')):
        assert iterate_story.main(["--story-id", story_id, "--threshold", "7"]) == 2, story_id
        err = capsys.readouterr().err
        assert err.startswith("Error: "), err
        assert expected in err, err
        assert not os.path.exists(os.path.join(stories, story_id, "run-summary.json"))


def test_tm8_argument_errors_exit_2(capsys):
    for argv, message in ((["--story-id", "x", "--threshold", "0"],
                           "--threshold must be an integer from 1 to 10"),
                          (["--story-id", "x", "--threshold", "11"],
                           "--threshold must be an integer from 1 to 10"),
                          (["--story-id", "x", "--threshold", "7", "--max-rounds", "0"],
                           "--max-rounds must be at least 1"),
                          (["--story-id", "x"], "--threshold"),
                          (["--threshold", "7"], "--story-id")):
        with pytest.raises(SystemExit) as excinfo:
            iterate_story.main(argv)
        assert excinfo.value.code == 2, argv
        assert message in capsys.readouterr().err, argv


# --- T-M5, T-M6, T-M6b, T-M9: failure paths and no-op detection (spec 3.5, 6) ---------

def test_tm5_judge_failure_mid_loop_promotes_best_so_far(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch)
    fake = FakeRun(story_dir, [(6, 6, 6, 6), (7, 3, 3, 3), 1])
    monkeypatch.setattr(iterate_story.subprocess, "run", fake)
    assert iterate_story.main(["--story-id", STORY_ID, "--threshold", "9"]) == 1
    out, err = capsys.readouterr()
    assert "round 3" in err
    assert "judge-story exited 1" in err
    assert "judge boom" in err
    assert ("Promoted best round 1 (v1) to story.md, story_prompt.txt, judgment.json."
            in err)
    assert "Stopped:" not in out
    assert (fake.judge_calls, fake.ltx_calls) == (3, 2)
    _assert_live_equals_archive(story_dir, 1)
    summary = _summary(story_dir)
    assert summary["stop_reason"] == "judge-story failed"
    assert summary["best_round"] == 1
    assert len(summary["rounds"]) == 2


def test_tm6_ltx_movie_failure_restores_best_round(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch)
    fake = FakeRun(story_dir, [(5, 5, 5, 5)], ltx_script=[1])
    monkeypatch.setattr(iterate_story.subprocess, "run", fake)
    assert iterate_story.main(["--story-id", STORY_ID, "--threshold", "9"]) == 1
    err = capsys.readouterr().err
    assert "round 1" in err
    assert "ltx-movie exited 1" in err
    assert "ltx boom" in err
    assert _read_bytes(os.path.join(story_dir, "story.md")) != b"GARBAGE"
    _assert_live_equals_archive(story_dir, 1)
    assert not os.path.exists(fake.overrides[0][0])
    summary = _summary(story_dir)
    assert summary["stop_reason"] == "ltx-movie failed"
    assert summary["best_round"] == 1


def test_tm6b_round1_judge_failure_leaves_live_files(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch)
    before = _read_bytes(os.path.join(story_dir, "story.md"))
    fake = FakeRun(story_dir, [1])
    monkeypatch.setattr(iterate_story.subprocess, "run", fake)
    assert iterate_story.main(["--story-id", STORY_ID, "--threshold", "9"]) == 1
    err = capsys.readouterr().err
    assert "round 1" in err
    assert "judge-story exited 1" in err
    assert "No round completed; live files left unchanged." in err
    assert _read_bytes(os.path.join(story_dir, "story.md")) == before
    assert not os.path.exists(os.path.join(story_dir, "story.v1.md"))
    summary = _summary(story_dir)
    assert summary["best_round"] is None
    assert summary["rounds"] == []
    assert summary["stop_reason"] == "judge-story failed"


def test_tm9_noop_regeneration_is_failure(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch)
    fake = FakeRun(story_dir, [(5, 4, 4, 3)], ltx_script=["noop"])
    monkeypatch.setattr(iterate_story.subprocess, "run", fake)
    assert iterate_story.main(["--story-id", STORY_ID, "--threshold", "9"]) == 1
    err = capsys.readouterr().err
    assert "round 1" in err
    assert "ltx-movie exited 0 but story.md was not regenerated" in err
    assert (fake.judge_calls, fake.ltx_calls) == (1, 1)
    _assert_live_equals_archive(story_dir, 1)
    summary = _summary(story_dir)
    assert summary["stop_reason"] == "ltx-movie no-op"
    assert summary["best_round"] == 1
    assert len(summary["rounds"]) == 1
