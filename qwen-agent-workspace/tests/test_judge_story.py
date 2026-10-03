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


# --- SDK response builders: real anthropic.types.Message objects (spec 7.1) ----------

THINKING_BLOCK = {"type": "thinking", "thinking": "Weighing panel-to-panel momentum.",
                  "signature": "sig-abc123"}


def _usage(input_tokens, output_tokens, thinking_tokens):
    """thinking_tokens=None omits output_tokens_details, as when the API does not report it."""
    usage = {"input_tokens": input_tokens, "output_tokens": output_tokens}
    if thinking_tokens is not None:
        usage["output_tokens_details"] = {"thinking_tokens": thinking_tokens}
    return usage


def _message(content, usage, stop_reason):
    return anthropic.types.Message.model_validate({
        "id": "msg_test_%s" % uuid.uuid4().hex, "type": "message", "role": "assistant",
        "model": "claude-opus-5-5", "stop_reason": stop_reason, "stop_sequence": None,
        "content": content, "usage": usage})


def _tool_response(tool_input, usage):
    return _message([THINKING_BLOCK, {"type": "tool_use", "id": "toolu_test",
                                      "name": "submit_judgment", "input": tool_input}],
                    usage, "tool_use")


def _text_response(text, usage):
    return _message([THINKING_BLOCK, {"type": "text", "text": text}], usage, "end_turn")


# --- T7: successful run (spec 4.1, 5.1-5.3) ------------------------------------------

def test_t7_successful_run(tmp_path, monkeypatch, capsys):
    story_md = _make_story(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    fake = _install_fake(monkeypatch, [
        _tool_response(copy.deepcopy(VALID_INPUT), _usage(1200, 3400, 2100))])

    assert judge_story.main(["--story-md", str(story_md)]) == 0

    with open(tmp_path / "judgment.json", encoding="utf-8") as f:
        raw_text = f.read()
    judgment = json.loads(raw_text)
    assert list(judgment) == ["story_md_path", "story_prompt_path", "model",
                              "effort", "timestamp", "usage", "scores",
                              "critique", "revised_prompt"]
    assert judgment["story_md_path"] == str(story_md)
    assert judgment["story_prompt_path"] == str(tmp_path / "story_prompt.txt")
    assert judgment["model"] == "claude-opus-5-5"
    assert judgment["effort"] == "high"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", judgment["timestamp"])
    assert judgment["usage"] == {"input_tokens": 1200, "output_tokens": 3400,
                                 "thinking_tokens": 2100}
    assert list(judgment["scores"]) == list(SCORE_NAMES)
    assert judgment["scores"] == VALID_INPUT["scores"]
    assert judgment["critique"] == VALID_INPUT["critique"]
    assert judgment["revised_prompt"] == VALID_INPUT["revised_prompt"]
    assert "—" in raw_text            # ensure_ascii=False
    assert raw_text.endswith("}\n")        # trailing newline after json.dump

    assert ((tmp_path / "story_prompt.revised.txt").read_bytes()
            == VALID_INPUT["revised_prompt"].encode("utf-8"))
    assert not (tmp_path / "judgment.raw.json").exists()

    out, err = capsys.readouterr()
    score_lines = "".join("  %-20s  %d\n" % (name, VALID_INPUT["scores"][name])
                          for name in SCORE_NAMES)
    assert "  pacing_progression    7\n" in score_lines   # pins the %-20s layout itself
    assert out == ("Scores:\n" + score_lines
                   + "\n--- Critique ---\n" + VALID_INPUT["critique"] + "\n"
                   + "\n--- Revised prompt ---\n" + VALID_INPUT["revised_prompt"] + "\n")
    assert err == ""

    assert fake.constructions == [((), {})]               # Anthropic() with no arguments
    assert len(fake.calls) == 1
    kwargs = fake.calls[0]
    assert sorted(kwargs) == ["max_tokens", "messages", "model", "output_config", "system",
                              "thinking", "tool_choice", "tools"]
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["max_tokens"] == 21333
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"] == {"effort": "high"}
    assert kwargs["tool_choice"] == {"type": "auto"}
    assert kwargs["system"] == judge_story.SYSTEM_PROMPT
    assert [tool["name"] for tool in kwargs["tools"]] == ["submit_judgment"]
    assert kwargs["tools"][0]["input_schema"] == judge_story.SUBMIT_JUDGMENT_SCHEMA
    assert kwargs["tools"][0]["description"] == judge_story.TOOL_DESCRIPTION
    messages = kwargs["messages"]
    assert len(messages) == 1 and messages[0]["role"] == "user"
    assert STORY_MD_TEXT in messages[0]["content"]
    assert STORY_PROMPT_TEXT in messages[0]["content"]
    assert messages[0]["content"] == (
        "Below are the original story-generation prompt and the story it produced.\n"
        "\n<story_prompt>\n" + STORY_PROMPT_TEXT + "\n</story_prompt>\n"
        "\n<story_md>\n" + STORY_MD_TEXT + "\n</story_md>\n"
        "\nJudge the story and call submit_judgment.")


# --- T10b: schema-invalid tool input (spec 4.4, E7) ----------------------------------

def test_t10b_schema_invalid_tool_input(tmp_path, monkeypatch, capsys):
    story_md = _make_story(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    bad = copy.deepcopy(VALID_INPUT)
    bad["scores"]["continuity"] = 11
    fake = _install_fake(monkeypatch, [_tool_response(bad, _usage(10, 20, 5))])

    assert judge_story.main(["--story-md", str(story_md)]) == 1

    assert len(fake.calls) == 1            # no retry on a validation failure (spec G3)
    with open(tmp_path / "judgment.raw.json", encoding="utf-8") as f:
        raw = json.load(f)
    assert len(raw["responses"]) == 1
    assert raw["responses"][0]["content"][1]["input"]["scores"]["continuity"] == 11
    assert not (tmp_path / "judgment.json").exists()
    assert not (tmp_path / "story_prompt.revised.txt").exists()
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("Error: submit_judgment input failed schema validation: ")


# --- T9-T11: retry, double failure, API errors, key leakage (spec 4.6, 6) ------------

def test_t9_retry_after_missing_tool_call(tmp_path, monkeypatch):
    story_md = _make_story(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    # r1 reports no thinking_tokens; r2 does: the sum covers only the responses that
    # report it (spec 5.1).
    r1 = _text_response("Here is my judgment in prose.", _usage(100, 200, None))
    r2 = _tool_response(copy.deepcopy(VALID_INPUT), _usage(1000, 3000, 2500))
    fake = _install_fake(monkeypatch, [r1, r2])

    assert judge_story.main(["--story-md", str(story_md)]) == 0

    assert len(fake.calls) == 2
    first, second = fake.calls
    assert len(first["messages"]) == 1     # the retry builds a new list, not an append
    retry_messages = second["messages"]
    assert len(retry_messages) == 3
    assert [m["role"] for m in retry_messages] == ["user", "assistant", "user"]
    assert retry_messages[0] == first["messages"][0]
    assert retry_messages[1]["content"] == r1.content
    assert retry_messages[1]["content"][0].type == "thinking"
    assert retry_messages[1]["content"][0].signature == "sig-abc123"
    assert retry_messages[2]["content"] == judge_story.RETRY_USER_MESSAGE
    assert second["tool_choice"] == {"type": "auto"}
    assert ({k: v for k, v in second.items() if k != "messages"}
            == {k: v for k, v in first.items() if k != "messages"})
    with open(tmp_path / "judgment.json", encoding="utf-8") as f:
        judgment = json.load(f)
    assert judgment["usage"] == {"input_tokens": 1100, "output_tokens": 3200,
                                 "thinking_tokens": 2500}
    assert judgment["scores"] == VALID_INPUT["scores"]
    assert not (tmp_path / "judgment.raw.json").exists()


def test_t10_double_failure_writes_raw_and_no_judgment(tmp_path, monkeypatch, capsys):
    story_md = _make_story(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    r1 = _text_response("Prose judgment, attempt one.", _usage(100, 200, 50))
    r2 = _text_response("Prose judgment, attempt two.", _usage(110, 210, 60))
    fake = _install_fake(monkeypatch, [r1, r2])

    assert judge_story.main(["--story-md", str(story_md)]) == 1

    assert len(fake.calls) == 2
    with open(tmp_path / "judgment.raw.json", encoding="utf-8") as f:
        raw = json.load(f)
    assert len(raw["responses"]) == 2
    assert raw["responses"] == [r1.model_dump(mode="json"), r2.model_dump(mode="json")]
    assert not (tmp_path / "judgment.json").exists()
    assert not (tmp_path / "story_prompt.revised.txt").exists()
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ("Error: Claude did not call submit_judgment after one retry; raw "
                   "responses written to %s\n" % (tmp_path / "judgment.raw.json"))


def test_t10c_api_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)

    def connection_error():
        return anthropic.APIConnectionError(
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))

    # The first call raises.
    first_dir = tmp_path / "first"
    story_md = _make_story(first_dir)
    fake = _install_fake(monkeypatch, [connection_error()])
    assert judge_story.main(["--story-md", str(story_md)]) == 1
    assert len(fake.calls) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert "Anthropic API call failed" in err
    assert err.startswith("Error: Anthropic API call failed: APIConnectionError: ")
    assert sorted(os.listdir(first_dir)) == ["story.md", "story_prompt.txt"]

    # The retry call raises: E5 applies and r1 is not dumped (spec 6, E5 details).
    retry_dir = tmp_path / "retry"
    story_md = _make_story(retry_dir)
    fake = _install_fake(monkeypatch, [
        _text_response("Prose only.", _usage(100, 200, 50)), connection_error()])
    assert judge_story.main(["--story-md", str(story_md)]) == 1
    assert len(fake.calls) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("Error: Anthropic API call failed: APIConnectionError: ")
    assert sorted(os.listdir(retry_dir)) == ["story.md", "story_prompt.txt"]


def test_t11_api_key_never_leaks(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)

    # T7 scenario (success). These responses omit output_tokens_details, so this run
    # also pins usage.thinking_tokens == null rather than a fabricated 0 (spec 5.1, G4).
    ok_dir = tmp_path / "ok"
    story_md = _make_story(ok_dir)
    _install_fake(monkeypatch, [
        _tool_response(copy.deepcopy(VALID_INPUT), _usage(1200, 3400, None))])
    assert judge_story.main(["--story-md", str(story_md)]) == 0
    ok_out, ok_err = capsys.readouterr()

    # T10 scenario (double failure).
    fail_dir = tmp_path / "fail"
    story_md = _make_story(fail_dir)
    _install_fake(monkeypatch, [_text_response("Prose one.", _usage(1, 2, None)),
                                _text_response("Prose two.", _usage(3, 4, None))])
    assert judge_story.main(["--story-md", str(story_md)]) == 1
    fail_out, fail_err = capsys.readouterr()

    written = [ok_dir / "judgment.json", ok_dir / "story_prompt.revised.txt",
               fail_dir / "judgment.raw.json"]
    for path in written:
        assert path.is_file(), path
    with open(ok_dir / "judgment.json", encoding="utf-8") as f:
        assert json.load(f)["usage"]["thinking_tokens"] is None
    for text in [ok_out, ok_err, fail_out, fail_err] + [p.read_text(encoding="utf-8")
                                                         for p in written]:
        assert SENTINEL_KEY not in text


def test_target_panels_optional():
    assert judge_story.build_parser().parse_args(["--story-id", "x"]).target_panels is None
    assert judge_story.build_parser().parse_args(
        ["--story-id", "x", "--target-panels", "20"]).target_panels == 20
    with_target = judge_story.build_user_message("MD", "PROMPT", 20)
    assert "target exactly 20 panels" in with_target
    without_target = judge_story.build_user_message("MD", "PROMPT")
    assert "target exactly" not in without_target
    assert judge_story.build_user_message("MD", "PROMPT", None) == without_target
