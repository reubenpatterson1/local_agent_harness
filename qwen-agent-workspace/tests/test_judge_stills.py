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
