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
