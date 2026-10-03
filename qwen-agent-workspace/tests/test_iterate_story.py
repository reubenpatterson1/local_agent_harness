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
