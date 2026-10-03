"""Tests for bin/judge-story.

Spec: docs/superpowers/specs/2026-10-02-judge-story-design.md (Section 7).
Run from the workspace root: python3 -m pytest tests/test_judge_story.py -v

Plain pytest asserts only -- no check() helper, which reports false greens under
pytest. No test makes a network call: the autouse fixture below makes constructing
the real anthropic.Anthropic client fail the test, and every test that reaches the
API installs a recording fake first. Exactly one test function per spec test ID
(18 total); multi-case IDs loop inside their function.
"""

import copy
import importlib.machinery
import json
import os
import re
import types
import uuid

import anthropic
import httpx
import jsonschema
import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
_SCRIPT_PATH = os.path.join(WS, "bin", "judge-story")
judge_story = importlib.machinery.SourceFileLoader("judge_story", _SCRIPT_PATH).load_module()

SENTINEL_KEY = "sk-test-SENTINEL-do-not-leak"
SCORE_NAMES = ("pacing_progression", "action_plausibility", "visual_specificity", "continuity")

# Distinct per-dimension scores so a score copied under the wrong name is caught.
VALID_INPUT = {
    "scores": {"pacing_progression": 7, "action_plausibility": 6,
               "visual_specificity": 8, "continuity": 5},
    "critique": "Panel 3 stalls the chase; Panel 7 lands the jump — keep it.",
    "revised_prompt": "Write a 5-panel action story.\nKeep every panel filmable.",
}


@pytest.fixture(autouse=True)
def _no_real_client(monkeypatch):
    """SC4 guard for every test: constructing the real client fails the test, and the
    key starts unset. Tests that reach the API install a recording fake over this."""
    def _forbidden(*args, **kwargs):
        raise AssertionError("test constructed a real anthropic.Anthropic client")
    monkeypatch.setattr(judge_story.anthropic, "Anthropic", _forbidden)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


# --- T5: submit_judgment schema validation (spec 4.3, 4.4) ---------------------------

def test_t5a_missing_top_level_key_rejected():
    for key in ("scores", "critique", "revised_prompt"):
        payload = copy.deepcopy(VALID_INPUT)
        del payload[key]
        with pytest.raises(jsonschema.ValidationError):
            judge_story.validate_judgment_input(payload)


def test_t5b_missing_score_key_rejected():
    for key in SCORE_NAMES:
        payload = copy.deepcopy(VALID_INPUT)
        del payload["scores"][key]
        with pytest.raises(jsonschema.ValidationError):
            judge_story.validate_judgment_input(payload)


def test_t5c_out_of_range_or_non_integer_score_rejected():
    # 0 and 11 are the spec's range cases; "7", 7.5 and True pin "non-integer score"
    # (jsonschema does not count booleans as integers). Every dimension is checked.
    for key in SCORE_NAMES:
        for bad in (0, 11, "7", 7.5, True):
            payload = copy.deepcopy(VALID_INPUT)
            payload["scores"][key] = bad
            with pytest.raises(jsonschema.ValidationError):
                judge_story.validate_judgment_input(payload)


def test_t5d_valid_payload_accepted():
    for value in (1, 10):
        payload = copy.deepcopy(VALID_INPUT)
        payload["scores"] = {key: value for key in SCORE_NAMES}
        assert judge_story.validate_judgment_input(payload) is None
    # No additionalProperties constraint: extra keys are tolerated (spec 4.3).
    payload = copy.deepcopy(VALID_INPUT)
    payload["extra"] = "ignored"
    payload["scores"]["extra_score"] = 99
    assert judge_story.validate_judgment_input(payload) is None


# --- shared fixtures for main() tests -------------------------------------------------

# Trailing whitespace, "%", "{...}" and a non-ASCII dash check that the texts reach the
# user message untouched (no stripping, formatting, or escaping).
STORY_MD_TEXT = "# Fox crossing\n\n## Panel 1\nPrompt: A fox steps onto river ice — dawn.\n"
STORY_PROMPT_TEXT = "Write a {panels}-panel story about a fox.\nUse 100% concrete detail.  \n"


def _make_story(directory, with_prompt=True):
    directory.mkdir(parents=True, exist_ok=True)
    story_md = directory / "story.md"
    story_md.write_text(STORY_MD_TEXT, encoding="utf-8")
    if with_prompt:
        (directory / "story_prompt.txt").write_text(STORY_PROMPT_TEXT, encoding="utf-8")
    return story_md


class _FakeAnthropic:
    """Stands in for anthropic.Anthropic. Calling it records the construction and returns
    itself as the client; .messages.create(**kwargs) records kwargs and returns (or
    raises, for exception instances) the scripted items in order."""

    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.constructions = []
        self.calls = []
        self.messages = types.SimpleNamespace(create=self._create)

    def __call__(self, *args, **kwargs):
        self.constructions.append((args, kwargs))
        return self

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.scripted.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _install_fake(monkeypatch, scripted):
    fake = _FakeAnthropic(scripted)
    monkeypatch.setattr(judge_story.anthropic, "Anthropic", fake)
    return fake


# --- T1-T4: arguments, path resolution, file preconditions (spec 1.1, 3, 6) ---------

def test_t1a_both_flags_exit_2():
    with pytest.raises(SystemExit) as exc:
        judge_story.main(["--story-id", "x", "--story-md", "y"])
    assert exc.value.code == 2


def test_t1b_no_flags_exit_2():
    with pytest.raises(SystemExit) as exc:
        judge_story.main([])
    assert exc.value.code == 2


def test_t2a_resolve_paths_story_id(monkeypatch, tmp_path):
    assert judge_story.WS == WS
    base = os.path.join(WS, "generated", "stories", "abc")
    assert judge_story.resolve_paths("abc", None) == (
        base, os.path.join(base, "story.md"), os.path.join(base, "story_prompt.txt"))
    # WS is read at call time, not import time (spec 1.2).
    monkeypatch.setattr(judge_story, "WS", str(tmp_path))
    assert judge_story.resolve_paths("abc", None)[0] == os.path.join(
        str(tmp_path), "generated", "stories", "abc")


def test_t2b_resolve_paths_story_md(monkeypatch, tmp_path):
    s = tmp_path / "s"
    expected = (str(s), str(s / "story.md"), str(s / "story_prompt.txt"))
    assert judge_story.resolve_paths(None, str(s / "story.md")) == expected
    # A relative --story-md is made absolute against the current directory.
    monkeypatch.chdir(tmp_path)
    assert judge_story.resolve_paths(None, os.path.join("s", "story.md")) == expected


def test_t3a_missing_story_md_exit_2(tmp_path, capsys):
    missing = tmp_path / "story.md"
    assert judge_story.main(["--story-md", str(missing)]) == 2
    out, err = capsys.readouterr()
    assert "Error: story.md not found: %s\n" % missing in err
    assert out == ""
    # Passing the story directory instead of the file is the same precondition failure.
    assert judge_story.main(["--story-md", str(tmp_path)]) == 2
    _, err = capsys.readouterr()
    assert "Error: story.md not found: %s\n" % tmp_path in err
    assert os.listdir(tmp_path) == []


def test_t3b_nonexistent_story_id_exit_2(capsys):
    story_id = "judge-story-test-nonexistent-%s" % uuid.uuid4().hex
    assert judge_story.main(["--story-id", story_id]) == 2
    _, err = capsys.readouterr()
    assert "Error: story.md not found: " in err
    assert not os.path.exists(os.path.join(WS, "generated", "stories", story_id))


def test_t4_missing_story_prompt_exit_2(tmp_path, capsys):
    story_md = _make_story(tmp_path, with_prompt=False)
    assert judge_story.main(["--story-md", str(story_md)]) == 2
    out, err = capsys.readouterr()
    assert err == (
        "Error: story_prompt.txt not found: %s. judge-story needs the original "
        "story-generation prompt to produce revised_prompt. This story may predate "
        "bin/ltx-movie's story_prompt.txt persistence (re-run its Phase 1 with "
        "--force-story), or --story-md points at a directory without the sibling file.\n"
        % (tmp_path / "story_prompt.txt"))
    assert out == ""
    assert os.listdir(tmp_path) == ["story.md"]


# --- T8: API-key gate (spec 4.2) -------------------------------------------------------

def test_t8_key_unset_never_constructs_client(tmp_path, monkeypatch, capsys):
    _make_story(tmp_path)
    fake = _install_fake(monkeypatch, [])
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert judge_story.main(["--story-md", str(tmp_path / "story.md")]) == 1
    assert fake.constructions == []
    assert fake.calls == []
    out, err = capsys.readouterr()
    assert "ANTHROPIC_API_KEY" in err
    assert err == ("Error: ANTHROPIC_API_KEY is not set; export it in your environment to "
                   "run judge-story.\n")
    assert out == ""
    # An empty value counts as unset (spec 4.2).
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert judge_story.main(["--story-md", str(tmp_path / "story.md")]) == 1
    assert fake.constructions == []
    assert fake.calls == []
    _, err = capsys.readouterr()
    assert err.startswith("Error: ANTHROPIC_API_KEY is not set")
    assert sorted(os.listdir(tmp_path)) == ["story.md", "story_prompt.txt"]
