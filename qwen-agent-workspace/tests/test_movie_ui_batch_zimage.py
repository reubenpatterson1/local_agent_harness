"""Tests for the batch fork rule that a fork never chooses Z-Image (shots-zimage review fix).

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_batch_zimage.py
"""

import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import movie_ui_batch as batch  # noqa: E402

WSR = "/abs/ws"
QWEN = "Qwen/Qwen-Image-Edit-2509"


def merged(base, settings):
    variant = {"label": "v", "settings": settings, "prompt": {"append": "", "replace": [], "per_story": {}}}
    return batch.merge(dict({"narrative": "N"}, **base), variant, "s1", None, WSR)[1]


def test_bz1_chained_asis_forked_to_shots_drops_asis():
    fork = merged({"mode": "chained", "seed_edit_model": "as-is"}, {"mode": "shots"})
    assert fork["mode"] == "shots"
    assert fork["seed_edit_model"] is None


def test_bz2_shots_asis_stays_when_mode_unchanged():
    fork = merged({"mode": "shots", "seed_edit_model": "as-is"}, {"fps": 24})
    assert fork["mode"] == "shots"
    assert fork["seed_edit_model"] == "as-is"


def test_bz3_chained_asis_stays_when_mode_unchanged():
    fork = merged({"mode": "chained", "seed_edit_model": "as-is"}, {"fps": 24})
    assert fork["mode"] == "chained"
    assert fork["seed_edit_model"] == "as-is"


def test_bz4_qwen_model_survives_mode_change():
    fork = merged({"mode": "chained", "seed_edit_model": QWEN}, {"mode": "shots"})
    assert fork["mode"] == "shots"
    assert fork["seed_edit_model"] == QWEN
