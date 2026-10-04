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
