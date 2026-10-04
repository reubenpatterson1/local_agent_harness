"""Tests for bin/judge-stills.

Spec: docs/superpowers/specs/2026-10-04-judge-stills-design.md (Section 7).
Run from the workspace root: python3 -m pytest tests/test_judge_stills.py -v

Plain pytest asserts only -- no check() helper, which reports false greens under
pytest. No test makes a network call: the autouse fixture below makes constructing
the real anthropic.Anthropic client fail the test, and every test that reaches the
API installs a recording fake first. Story fixtures live under tmp_path with
judge_stills.WS patched to it; nothing is written to the real generated/ tree.
Exactly one test function per spec test ID (32 total); multi-case IDs loop inside
their function.
"""

import base64
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
_SCRIPT_PATH = os.path.join(WS, "bin", "judge-stills")
judge_stills = importlib.machinery.SourceFileLoader("judge_stills", _SCRIPT_PATH).load_module()

SENTINEL_KEY = "sk-test-SENTINEL-do-not-leak"
SCORE_NAMES = ("prompt_fidelity", "visual_continuity", "rendering_quality", "composition")
VC_MISSING_MESSAGE = "visual_continuity is required when judging 2 or more stills"

# Distinct per-dimension scores so a score copied under the wrong name is caught. The
# non-ASCII dash checks ensure_ascii=False in the written JSON.
VALID_INPUT = {
    "scores": {"prompt_fidelity": 7, "visual_continuity": 6,
               "rendering_quality": 8, "composition": 5},
    "critique": "Panel 1 nails the dawn light; Panel 3 loses the frog's markings — fix it.",
}


def _without_vc(payload):
    """A deep copy of payload with scores.visual_continuity removed."""
    result = copy.deepcopy(payload)
    del result["scores"]["visual_continuity"]
    return result


@pytest.fixture(autouse=True)
def _no_real_client(monkeypatch):
    """SC7 guard for every test: constructing the real client fails the test, and the
    key starts unset. Tests that reach the API install a recording fake over this."""
    def _forbidden(*args, **kwargs):
        raise AssertionError("test constructed a real anthropic.Anthropic client")
    monkeypatch.setattr(judge_stills.anthropic, "Anthropic", _forbidden)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


# --- T8: submit_judgment validation (spec 4.3, 4.4) ----------------------------------

def test_t8a_missing_top_level_key_rejected():
    for key in ("scores", "critique"):
        payload = copy.deepcopy(VALID_INPUT)
        del payload[key]
        with pytest.raises(jsonschema.ValidationError):
            judge_stills.validate_judgment_input(payload, 2)


def test_t8b_missing_always_required_score_rejected():
    # These three are required by the schema itself, so the stills count is irrelevant.
    for key in ("prompt_fidelity", "rendering_quality", "composition"):
        for stills_count in (1, 2):
            payload = copy.deepcopy(VALID_INPUT)
            del payload["scores"][key]
            with pytest.raises(jsonschema.ValidationError):
                judge_stills.validate_judgment_input(payload, stills_count)


def test_t8c_out_of_range_or_non_integer_score_rejected():
    # 0 and 11 are the range cases; "7", 7.5 and True pin "non-integer score"
    # (jsonschema does not count booleans as integers). Every dimension is checked.
    for key in SCORE_NAMES:
        for bad in (0, 11, "7", 7.5, True):
            payload = copy.deepcopy(VALID_INPUT)
            payload["scores"][key] = bad
            with pytest.raises(jsonschema.ValidationError):
                judge_stills.validate_judgment_input(payload, 2)


def test_t8d_valid_payload_accepted():
    for value in (1, 10):
        payload = copy.deepcopy(VALID_INPUT)
        payload["scores"] = {key: value for key in SCORE_NAMES}
        assert judge_stills.validate_judgment_input(payload, 2) is None
    # No additionalProperties constraint: extra keys are tolerated (spec 4.3).
    payload = copy.deepcopy(VALID_INPUT)
    payload["extra"] = "ignored"
    payload["scores"]["extra_score"] = 99
    assert judge_stills.validate_judgment_input(payload, 2) is None
    # The 1-still shape: visual_continuity omitted, the other three valid.
    assert judge_stills.validate_judgment_input(_without_vc(VALID_INPUT), 1) is None


def test_t8e_visual_continuity_optional_for_one_still():
    assert judge_stills.validate_judgment_input(_without_vc(VALID_INPUT), 1) is None
    # The schema alone allows the omission too (it is not in scores.required).
    jsonschema.validate(instance=_without_vc(VALID_INPUT),
                        schema=judge_stills.SUBMIT_JUDGMENT_SCHEMA)
    # And a 1-still judgment that scores it anyway is rejected, never written through.
    with pytest.raises(jsonschema.ValidationError) as exc:
        judge_stills.validate_judgment_input(copy.deepcopy(VALID_INPUT), 1)
    assert exc.value.message == ("visual_continuity must be omitted when judging fewer "
                                 "than 2 stills")


def test_t8f_visual_continuity_required_for_two_stills():
    with pytest.raises(jsonschema.ValidationError) as exc:
        judge_stills.validate_judgment_input(_without_vc(VALID_INPUT), 2)
    assert exc.value.message == VC_MISSING_MESSAGE


# --- shared story.md fixtures (spec 7.1) ----------------------------------------------

# Synthesized chain-format story: Panel 1 has Image: (with a continuation line) and a
# Style: line that must close Image; a "## Notes" section must not attach anywhere;
# Panel 2 has an empty title; Panels 2-3 have no Image:.
CHAIN_STORY_MD = (
    "## Panel 1 — Dawn on the Pad\n"
    "Image: A green frog on a lily pad — dawn.\n"
    "Second image line.\n"
    "Style: photorealistic, natural light\n"
    "Motion: The frog crouches.\n"
    "Narration: He waits.\n"
    "\n"
    "## Notes\n"
    "Not a panel; must not attach anywhere.\n"
    "\n"
    "## Panel 2 —\n"
    "Motion: The frog leaps.\n"
    "Narration: He jumps.\n"
    "\n"
    "## Panel 3 — Landing\n"
    "Motion: The frog lands on the log.\n"
    "Narration: Safe.\n"
)
CHAIN_PANELS = [
    {"header": "## Panel 1 — Dawn on the Pad",
     "image": "A green frog on a lily pad — dawn. Second image line.",
     "motion": "The frog crouches.", "narration": "He waits."},
    {"header": "## Panel 2 —", "image": "",
     "motion": "The frog leaps.", "narration": "He jumps."},
    {"header": "## Panel 3 — Landing", "image": "",
     "motion": "The frog lands on the log.", "narration": "Safe."},
]

# Pre-chain (frogjump) shape: every panel has Image:, Motion:, Narration: on single lines.
ALL_IMAGE_STORY_MD = (
    "## Panel 1 — A\n"
    "Image: A frog sits on a lily pad.\n"
    "Motion: The frog crouches low.\n"
    "Narration: Morning on the pond.\n"
    "\n"
    "## Panel 2 — B\n"
    "Image: The frog hangs mid-air over the water.\n"
    "Motion: The frog leaps forward.\n"
    "Narration: He jumps.\n"
)


# --- T3-T5: still discovery and panel-text parsing (spec 3.1-3.4) --------------------

def test_t3_find_stills_numeric_sort_and_filter(tmp_path):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    for name in ("panel_03.png", "panel_01.png", "panel_100.png", "panel_99.png",
                 "panel_02.png", "panel_1.png", "panel_01.jpg", "panel_01.png.bak",
                 "Panel_04.png", "images.json"):
        (images_dir / name).write_bytes(b"x")
    d = str(images_dir)
    assert judge_stills.find_stills(d) == [
        (1, os.path.join(d, "panel_01.png")),
        (2, os.path.join(d, "panel_02.png")),
        (3, os.path.join(d, "panel_03.png")),
        (99, os.path.join(d, "panel_99.png")),
        (100, os.path.join(d, "panel_100.png")),
    ]


def test_t4a_parse_panels_chain_fixture():
    assert judge_stills.parse_panels(CHAIN_STORY_MD) == CHAIN_PANELS


def test_t4b_parse_panels_all_image_fixture():
    assert judge_stills.parse_panels(ALL_IMAGE_STORY_MD) == [
        {"header": "## Panel 1 — A", "image": "A frog sits on a lily pad.",
         "motion": "The frog crouches low.", "narration": "Morning on the pond."},
        {"header": "## Panel 2 — B", "image": "The frog hangs mid-air over the water.",
         "motion": "The frog leaps forward.", "narration": "He jumps."},
    ]


def test_t4c_parse_panels_no_panels():
    assert judge_stills.parse_panels("") == []
    assert judge_stills.parse_panels("# Title\nno panels\n") == []


def test_t5_format_panel_text():
    assert judge_stills.format_panel_text(CHAIN_PANELS[0]) == (
        "## Panel 1 — Dawn on the Pad\n"
        "Image: A green frog on a lily pad — dawn. Second image line.\n"
        "Motion: The frog crouches.\n"
        "Narration: He waits.")
    assert judge_stills.format_panel_text(CHAIN_PANELS[1]) == (
        "## Panel 2 —\nMotion: The frog leaps.\nNarration: He jumps.")
    assert judge_stills.format_panel_text(
        {"header": "## Panel 9 — X", "image": "", "motion": "", "narration": ""}) == "## Panel 9 — X"


# --- T6-T7: encoding and user-message content (spec 3.5, 3.6) ------------------------

def _still_bytes(k):
    """Distinct fake PNG bytes for still k (spec 7.1): nothing decodes them, and distinct
    bytes let a test check panel order by decoding the base64 back."""
    return b"\x89PNG\r\n\x1a\n" + b"still-%d" % k


def test_t6_encode_still(tmp_path):
    data = _still_bytes(1)
    path = tmp_path / "panel_01.png"
    path.write_bytes(data)
    result = judge_stills.encode_still(str(path))
    assert result == base64.standard_b64encode(data).decode("ascii")
    assert base64.b64decode(result) == data


def test_t7_build_user_content_two_stills():
    assert judge_stills.build_user_content([("T1", "QQ=="), ("T3", "Qg==")]) == [
        {"type": "text", "text": "T1"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": "QQ=="}},
        {"type": "text", "text": "T3"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": "Qg=="}},
        {"type": "text", "text": judge_stills.FINAL_USER_TEXT_MULTI_TEMPLATE % 2},
    ]
    assert judge_stills.FINAL_USER_TEXT_MULTI_TEMPLATE % 2 == (
        "You are judging all 2 stills above against their panel text. Score all four "
        "dimensions, including visual_continuity, and call submit_judgment.")


def test_t7b_build_user_content_one_still():
    assert judge_stills.build_user_content([("T1", "QQ==")]) == [
        {"type": "text", "text": "T1"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": "QQ=="}},
        {"type": "text", "text": judge_stills.FINAL_USER_TEXT_SINGLE},
    ]


def test_t7c_build_user_content_zero_entries():
    assert judge_stills.build_user_content([]) == [
        {"type": "text", "text": judge_stills.FINAL_USER_TEXT_SINGLE}]


# --- shared fixtures for main() tests -------------------------------------------------

STORY_ID = "stills-test"


def _make_story(tmp_path, monkeypatch, story_md=CHAIN_STORY_MD, stills=(1, 3),
                story_id=STORY_ID, with_images_dir=True):
    """Build tmp_path/generated/stories/<story_id>/ and point judge_stills.WS at tmp_path.
    story_md=None skips story.md; with_images_dir=False skips images/. Each index in
    stills becomes images/panel_%02d.png holding _still_bytes(index). Returns the story
    directory as a pathlib.Path."""
    monkeypatch.setattr(judge_stills, "WS", str(tmp_path))
    story_dir = tmp_path / "generated" / "stories" / story_id
    story_dir.mkdir(parents=True)
    if story_md is not None:
        (story_dir / "story.md").write_text(story_md, encoding="utf-8")
    if with_images_dir:
        images_dir = story_dir / "images"
        images_dir.mkdir()
        for k in stills:
            (images_dir / ("panel_%02d.png" % k)).write_bytes(_still_bytes(k))
    return story_dir


def _listing(directory):
    """Every path under directory, relative and sorted, to prove nothing was written."""
    return sorted(os.path.relpath(os.path.join(root, name), directory)
                  for root, dirs, files in os.walk(directory) for name in dirs + files)


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
    monkeypatch.setattr(judge_stills.anthropic, "Anthropic", fake)
    return fake


# --- T1-T2, T9, T11: arguments, paths, preconditions, key gate (spec 2, 4.2, 6) ------

def test_t1a_no_args_exit_2():
    with pytest.raises(SystemExit) as exc:
        judge_stills.main([])
    assert exc.value.code == 2


def test_t1b_story_md_flag_rejected():
    with pytest.raises(SystemExit) as exc:
        judge_stills.main(["--story-md", "x"])
    assert exc.value.code == 2


def test_t2_resolve_paths(monkeypatch, tmp_path):
    assert judge_stills.WS == WS
    base = os.path.join(WS, "generated", "stories", "abc")
    assert judge_stills.resolve_paths("abc") == (
        base, os.path.join(base, "images"), os.path.join(base, "story.md"))
    # WS is read at call time, not import time (spec 2.2).
    monkeypatch.setattr(judge_stills, "WS", str(tmp_path))
    assert judge_stills.resolve_paths("abc")[0] == os.path.join(
        str(tmp_path), "generated", "stories", "abc")


def test_t9a_missing_images_dir(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, with_images_dir=False)
    before = _listing(story_dir)
    assert judge_stills.main(["--story-id", STORY_ID]) == 2
    out, err = capsys.readouterr()
    assert err == "Error: stills directory not found: %s\n" % (story_dir / "images")
    assert out == ""
    assert _listing(story_dir) == before


def test_t9b_no_matching_stills(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, stills=())
    (story_dir / "images" / "panel_1.png").write_bytes(_still_bytes(1))
    (story_dir / "images" / "images.json").write_text("{}", encoding="utf-8")
    before = _listing(story_dir)
    assert judge_stills.main(["--story-id", STORY_ID]) == 2
    out, err = capsys.readouterr()
    assert err == "Error: no panel_NN.png stills found in %s\n" % (story_dir / "images")
    assert out == ""
    assert _listing(story_dir) == before


def test_t9c_missing_story_md(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, story_md=None, stills=(1,))
    before = _listing(story_dir)
    assert judge_stills.main(["--story-id", STORY_ID]) == 2
    out, err = capsys.readouterr()
    assert err == "Error: story.md not found: %s\n" % (story_dir / "story.md")
    assert out == ""
    assert _listing(story_dir) == before


def test_t9d_nonexistent_story_checks_images_first(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(judge_stills, "WS", str(tmp_path))
    story_id = "judge-stills-test-nonexistent-%s" % uuid.uuid4().hex
    assert judge_stills.main(["--story-id", story_id]) == 2
    out, err = capsys.readouterr()
    # The images/ check runs before the story.md check (spec 1.2 steps 3-5).
    assert err.startswith("Error: stills directory not found:")
    assert out == ""
    assert not (tmp_path / "generated").exists()


def test_t9e_still_without_panel_section(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, stills=(1, 4))
    before = _listing(story_dir)
    assert judge_stills.main(["--story-id", STORY_ID]) == 2
    out, err = capsys.readouterr()
    assert err == ("Error: %s has no matching panel section in story.md (story.md has 3 "
                   "panel sections); the stills may be stale relative to story.md.\n"
                   % (story_dir / "images" / "panel_04.png"))
    assert out == ""
    assert _listing(story_dir) == before


def test_t11_key_unset_never_constructs_client(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch)
    before = _listing(story_dir)
    fake = _install_fake(monkeypatch, [])
    expected_err = ("Error: ANTHROPIC_API_KEY is not set; export it in your environment to "
                    "run judge-stills.\n")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert judge_stills.main(["--story-id", STORY_ID]) == 1
    assert fake.constructions == []
    assert fake.calls == []
    out, err = capsys.readouterr()
    assert err == expected_err
    assert out == ""
    # An empty value counts as unset (spec 4.2).
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert judge_stills.main(["--story-id", STORY_ID]) == 1
    assert fake.constructions == []
    assert fake.calls == []
    out, err = capsys.readouterr()
    assert err == expected_err
    assert out == ""
    assert _listing(story_dir) == before


# --- SDK response builders: real anthropic.types.Message objects (spec 7.1) ----------

THINKING_BLOCK = {"type": "thinking", "thinking": "Comparing the stills to the panel text.",
                  "signature": "sig-abc123"}

ONE_PANEL_STORY_MD = (
    "## Panel 1 — Only\n"
    "Image: A green frog on a lily pad at dawn.\n"
    "Motion: The frog blinks once.\n"
    "Narration: Morning comes.\n"
)


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


def _expected_stdout(scores, critique):
    return ("Scores:\n"
            + "".join(judge_stills.format_score_line(k, scores[k]) + "\n"
                      for k in SCORE_NAMES)
            + "\n--- Critique ---\n" + critique + "\n")


# --- T10, T10b, T14, T14b: judging call, outputs, validation failures (spec 4-6) -----

def test_t10_successful_run_two_stills(tmp_path, monkeypatch, capsys):
    # CHAIN_STORY_MD has 3 panels; panel 2 has no still.
    story_dir = _make_story(tmp_path, monkeypatch, stills=(1, 3))
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    fake = _install_fake(monkeypatch, [
        _tool_response(copy.deepcopy(VALID_INPUT), _usage(1200, 3400, 2100))])

    assert judge_stills.main(["--story-id", STORY_ID]) == 0

    with open(story_dir / "stills_judgment.json", encoding="utf-8") as f:
        raw_text = f.read()
    judgment = json.loads(raw_text)
    assert list(judgment) == ["story_id", "model", "effort", "timestamp", "usage",
                              "scores", "critique"]
    assert judgment["story_id"] == STORY_ID
    assert judgment["model"] == "claude-opus-5-5"
    assert judgment["effort"] == "high"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", judgment["timestamp"])
    assert judgment["usage"] == {"input_tokens": 1200, "output_tokens": 3400,
                                 "thinking_tokens": 2100}
    assert list(judgment["scores"]) == list(judge_stills.SCORE_KEYS) == list(SCORE_NAMES)
    assert judgment["scores"] == VALID_INPUT["scores"]
    assert judgment["critique"] == VALID_INPUT["critique"]
    assert "—" in raw_text            # ensure_ascii=False
    assert raw_text.endswith("}\n")        # trailing newline after json.dump
    for name in ("stills_judgment.raw.json", "judgment.json", "judgment.raw.json"):
        assert not (story_dir / name).exists(), name

    out, err = capsys.readouterr()
    score_lines = "".join("  %-20s  %d\n" % (k, VALID_INPUT["scores"][k]) for k in SCORE_NAMES)
    assert "  prompt_fidelity       7\n" in score_lines   # pins the %-20s layout itself
    assert out == _expected_stdout(VALID_INPUT["scores"], VALID_INPUT["critique"])
    assert out == "Scores:\n" + score_lines + "\n--- Critique ---\n" + VALID_INPUT["critique"] + "\n"
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
    assert kwargs["system"] == judge_stills.SYSTEM_PROMPT
    assert [tool["name"] for tool in kwargs["tools"]] == ["submit_judgment"]
    assert kwargs["tools"][0]["input_schema"] == judge_stills.SUBMIT_JUDGMENT_SCHEMA
    assert kwargs["tools"][0]["description"] == judge_stills.TOOL_DESCRIPTION
    messages = kwargs["messages"]
    assert len(messages) == 1 and messages[0]["role"] == "user"
    content = messages[0]["content"]
    assert [block["type"] for block in content] == ["text", "image", "text", "image", "text"]
    assert content[0]["text"] == judge_stills.format_panel_text(CHAIN_PANELS[0])
    assert base64.b64decode(content[1]["source"]["data"]) == _still_bytes(1)
    assert content[2]["text"] == judge_stills.format_panel_text(CHAIN_PANELS[2])
    assert base64.b64decode(content[3]["source"]["data"]) == _still_bytes(3)
    assert content[4]["text"] == judge_stills.FINAL_USER_TEXT_MULTI_TEMPLATE % 2
    for block in (content[1], content[3]):
        assert block["source"]["type"] == "base64"
        assert block["source"]["media_type"] == "image/png"


def test_t10b_successful_run_one_still(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, story_md=ONE_PANEL_STORY_MD, stills=(1,))
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    # The judge followed the 1-still instruction: visual_continuity is absent entirely.
    tool_input = _without_vc(VALID_INPUT)
    fake = _install_fake(monkeypatch, [_tool_response(tool_input, _usage(900, 2500, 1500))])

    assert judge_stills.main(["--story-id", STORY_ID]) == 0

    with open(story_dir / "stills_judgment.json", encoding="utf-8") as f:
        raw_text = f.read()
    judgment = json.loads(raw_text)
    assert judgment["scores"] == {"prompt_fidelity": 7, "visual_continuity": None,
                                  "rendering_quality": 8, "composition": 5}
    assert list(judgment["scores"]) == list(SCORE_NAMES)
    assert '"visual_continuity": null' in raw_text
    assert not (story_dir / "stills_judgment.raw.json").exists()

    out, err = capsys.readouterr()
    assert judge_stills.format_score_line("visual_continuity", None) == (
        "  visual_continuity     n/a (only 1 still)")
    assert out == ("Scores:\n"
                   "  prompt_fidelity       7\n"
                   "  visual_continuity     n/a (only 1 still)\n"
                   "  rendering_quality     8\n"
                   "  composition           5\n"
                   "\n--- Critique ---\n" + VALID_INPUT["critique"] + "\n")
    assert out == _expected_stdout(judgment["scores"], VALID_INPUT["critique"])
    assert err == ""

    assert len(fake.calls) == 1                       # a valid tool_use: no retry
    content = fake.calls[0]["messages"][0]["content"]
    assert [block["type"] for block in content] == ["text", "image", "text"]
    assert content[0]["text"] == ("## Panel 1 — Only\n"
                                  "Image: A green frog on a lily pad at dawn.\n"
                                  "Motion: The frog blinks once.\n"
                                  "Narration: Morning comes.")
    assert base64.b64decode(content[1]["source"]["data"]) == _still_bytes(1)
    assert content[2]["text"] == judge_stills.FINAL_USER_TEXT_SINGLE


def test_t14_schema_invalid_tool_input(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, stills=(1, 3))
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    bad = copy.deepcopy(VALID_INPUT)
    bad["scores"]["composition"] = 11
    fake = _install_fake(monkeypatch, [_tool_response(bad, _usage(10, 20, 5))])

    assert judge_stills.main(["--story-id", STORY_ID]) == 1

    assert len(fake.calls) == 1            # no retry on a validation failure
    with open(story_dir / "stills_judgment.raw.json", encoding="utf-8") as f:
        raw = json.load(f)
    assert len(raw["responses"]) == 1
    assert raw["responses"][0]["content"][1]["input"]["scores"]["composition"] == 11
    assert not (story_dir / "stills_judgment.json").exists()
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("Error: submit_judgment input failed schema validation: ")


def test_t14b_two_stills_missing_visual_continuity(tmp_path, monkeypatch, capsys):
    # A submit_judgment block WAS found (unlike T13); its input omits visual_continuity
    # although 2 stills were judged. Caught by the post-schema check (spec 4.4, E9).
    story_dir = _make_story(tmp_path, monkeypatch, stills=(1, 3))
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    fake = _install_fake(monkeypatch, [
        _tool_response(_without_vc(VALID_INPUT), _usage(10, 20, 5))])

    assert judge_stills.main(["--story-id", STORY_ID]) == 1

    assert len(fake.calls) == 1            # validation failure: no retry
    with open(story_dir / "stills_judgment.raw.json", encoding="utf-8") as f:
        raw = json.load(f)
    assert len(raw["responses"]) == 1
    assert not (story_dir / "stills_judgment.json").exists()
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ("Error: submit_judgment input failed schema validation: "
                   "visual_continuity is required when judging 2 or more stills\n")


# --- T12, T13, T15, T16: retry, double failure, API errors, key leakage (spec 4.6, 6) -

def test_t12_retry_after_missing_tool_call(tmp_path, monkeypatch):
    story_dir = _make_story(tmp_path, monkeypatch, stills=(1, 3))
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    # r1 reports no thinking_tokens; r2 does: the sum covers only the responses that
    # report it (spec 5.1).
    r1 = _text_response("Here is my judgment in prose.", _usage(100, 200, None))
    r2 = _tool_response(copy.deepcopy(VALID_INPUT), _usage(1000, 3000, 2500))
    fake = _install_fake(monkeypatch, [r1, r2])

    assert judge_stills.main(["--story-id", STORY_ID]) == 0

    assert len(fake.calls) == 2
    first, second = fake.calls
    assert len(first["messages"]) == 1     # the retry builds a new list, not an append
    retry_messages = second["messages"]
    assert len(retry_messages) == 3
    assert [m["role"] for m in retry_messages] == ["user", "assistant", "user"]
    assert retry_messages[0] == first["messages"][0]      # same images re-sent
    assert len(retry_messages[0]["content"]) == 5
    assert retry_messages[1]["content"] == r1.content
    assert retry_messages[1]["content"][0].type == "thinking"
    assert retry_messages[1]["content"][0].signature == "sig-abc123"
    assert retry_messages[2]["content"] == judge_stills.RETRY_USER_MESSAGE
    assert ({k: v for k, v in second.items() if k != "messages"}
            == {k: v for k, v in first.items() if k != "messages"})
    with open(story_dir / "stills_judgment.json", encoding="utf-8") as f:
        judgment = json.load(f)
    assert judgment["usage"] == {"input_tokens": 1100, "output_tokens": 3200,
                                 "thinking_tokens": 2500}
    assert judgment["scores"] == VALID_INPUT["scores"]
    assert not (story_dir / "stills_judgment.raw.json").exists()


def test_t13_double_failure_writes_raw_and_no_judgment(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch, stills=(1, 3))
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    r1 = _text_response("Prose judgment, attempt one.", _usage(100, 200, 50))
    r2 = _text_response("Prose judgment, attempt two.", _usage(110, 210, 60))
    fake = _install_fake(monkeypatch, [r1, r2])

    assert judge_stills.main(["--story-id", STORY_ID]) == 1

    assert len(fake.calls) == 2
    raw_path = story_dir / "stills_judgment.raw.json"
    with open(raw_path, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["responses"] == [r1.model_dump(mode="json"), r2.model_dump(mode="json")]
    assert not (story_dir / "stills_judgment.json").exists()
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ("Error: Claude did not call submit_judgment after one retry; raw "
                   "responses written to %s\n" % raw_path)


def test_t15_api_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)

    def connection_error():
        return anthropic.APIConnectionError(
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))

    # (a) The first call raises.
    first_dir = _make_story(tmp_path, monkeypatch, story_id="api-first")
    before = _listing(first_dir)
    fake = _install_fake(monkeypatch, [connection_error()])
    assert judge_stills.main(["--story-id", "api-first"]) == 1
    assert len(fake.calls) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("Error: Anthropic API call failed: APIConnectionError: ")
    assert _listing(first_dir) == before

    # (b) r1 has no tool call and the retry raises: E7, and r1 is not dumped.
    retry_dir = _make_story(tmp_path, monkeypatch, story_id="api-retry")
    before = _listing(retry_dir)
    fake = _install_fake(monkeypatch, [
        _text_response("Prose only.", _usage(100, 200, 50)), connection_error()])
    assert judge_stills.main(["--story-id", "api-retry"]) == 1
    assert len(fake.calls) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("Error: Anthropic API call failed: APIConnectionError: ")
    assert _listing(retry_dir) == before


def test_t16_api_key_never_leaks(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)

    # T10 scenario (success). These responses omit output_tokens_details, so this run
    # also pins usage.thinking_tokens == null rather than a fabricated 0 (spec 5.1).
    ok_dir = _make_story(tmp_path, monkeypatch, story_id="leak-ok")
    _install_fake(monkeypatch, [
        _tool_response(copy.deepcopy(VALID_INPUT), _usage(1200, 3400, None))])
    assert judge_stills.main(["--story-id", "leak-ok"]) == 0
    ok_out, ok_err = capsys.readouterr()

    # T13 scenario (double failure).
    fail_dir = _make_story(tmp_path, monkeypatch, story_id="leak-fail")
    _install_fake(monkeypatch, [_text_response("Prose one.", _usage(1, 2, None)),
                                _text_response("Prose two.", _usage(3, 4, None))])
    assert judge_stills.main(["--story-id", "leak-fail"]) == 1
    fail_out, fail_err = capsys.readouterr()

    written = [ok_dir / "stills_judgment.json", fail_dir / "stills_judgment.raw.json"]
    for path in written:
        assert path.is_file(), path
    with open(ok_dir / "stills_judgment.json", encoding="utf-8") as f:
        assert json.load(f)["usage"]["thinking_tokens"] is None
    for text in [ok_out, ok_err, fail_out, fail_err] + [p.read_text(encoding="utf-8")
                                                         for p in written]:
        assert SENTINEL_KEY not in text
