"""Tests for action_lib.py (action LoRA library, Phase 1 of
docs/superpowers/specs/2026-10-20-action-lora-motion-library-design.md).
Stdlib + pytest only; no clips, models or GPU needed."""

import importlib.machinery
import json
import os

import pytest

HERE = os.path.dirname(os.path.realpath(__file__))
WS = os.path.dirname(HERE)
action_lib = importlib.machinery.SourceFileLoader(
    "action_lib", os.path.join(WS, "action_lib.py")).load_module()


def _valid(**over):
    """A minimal valid action.json dict; override fields via kwargs."""
    data = {
        "schema_version": 1,
        "name": "roundhouse-kick",
        "kind": "motion",
        "trigger": "performs a roundhouse kick",
        "descriptor": "a spinning kick delivered with the rear leg to head height",
        "default_strength": 0.7,
        "strength_range": [0.4, 1.0],
        "source": {"type": "clips", "paths": ["/abs/clip0.mp4", "/abs/clip1.mp4"]},
        "identity_agnostic": True,
        "dataset": None,
        "lora": None,
        "status": "dataset",
        "created_at": "2026-10-20T00:00:00Z",
    }
    data.update(over)
    return data


def test_valid_record_passes():
    action_lib.validate_action(_valid())


def test_new_action_is_valid_and_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setenv(action_lib.LIBRARY_ENV, str(tmp_path))
    data = action_lib.new_action(
        "sword-draw", "draws the sword in one motion",
        "a fast iaido draw bringing the blade from scabbard to guard",
        ["clip0.mp4", "clip1.mp4"])
    assert data["kind"] == "motion" and data["status"] == "dataset" and data["lora"] is None
    assert all(os.path.isabs(p) for p in data["source"]["paths"])
    os.makedirs(action_lib.action_dir("sword-draw"))
    action_lib.write_action(data)
    assert action_lib.load_action("sword-draw") == data
    assert action_lib.list_names() == ["sword-draw"]


def test_list_and_registered_triggers(tmp_path, monkeypatch):
    monkeypatch.setenv(action_lib.LIBRARY_ENV, str(tmp_path))
    assert action_lib.list_names() == []
    assert action_lib.registered_triggers() == {}
    for name, status in (("kick-a", "dataset"), ("kick-b", "trained")):
        os.makedirs(action_lib.action_dir(name))
        d = _valid(name=name, trigger="does %s" % name.replace("-", " "), status=status)
        if status == "trained":
            d["lora"] = {"path": "/abs/%s.safetensors" % name, "sha256": "a" * 64,
                         "rank": 16, "alpha": 16, "base_model": "dgrauet/ltx-2.3-mlx-q8"}
        action_lib.write_action(d)
    assert action_lib.list_names() == ["kick-a", "kick-b"]
    # only the trained action is offered to the planner
    assert action_lib.registered_triggers() == {"does kick b": "kick-b"}


@pytest.mark.parametrize("field,bad", [
    ("schema_version", 2),
    ("name", "Bad_Name"),
    ("kind", "style"),                                   # actions are motion only
    ("trigger", "  leading space"),                      # not normalized
    ("trigger", "tab\tinside"),                          # illegal char
    ("descriptor", "too short"),                         # < 8 words
    ("descriptor", "kick without an article leading the phrase here now ok"),  # no a/an
    ("default_strength", "0.7"),                         # not a number
    ("strength_range", [0.4]),                           # not two numbers
    ("strength_range", [0.0, 1.0]),                      # lo must be > 0
    ("strength_range", [0.4, 2.5]),                      # hi must be <= 2
    ("source", {"type": "clips", "paths": []}),          # empty list
    ("source", {"type": "clips", "paths": ["rel.mp4"]}),  # not absolute
    ("source", {"type": "seed_image", "path": "/x"}),    # wrong type
    ("identity_agnostic", "true"),                       # not a bool
    ("dataset", 5),                                      # not object/null
    ("status", "done"),                                  # not a valid status
    ("created_at", "2026-10-20"),                        # not a UTC timestamp
])
def test_validate_rejects_bad_field(field, bad):
    with pytest.raises(action_lib.ActionError):
        action_lib.validate_action(_valid(**{field: bad}))


def test_default_within_range():
    with pytest.raises(action_lib.ActionError):
        action_lib.validate_action(_valid(default_strength=1.5, strength_range=[0.4, 1.0]))


def test_lora_alpha_must_equal_rank():
    good = {"path": "/abs/a.safetensors", "sha256": "a" * 64, "rank": 16, "alpha": 16,
            "base_model": "dgrauet/ltx-2.3-mlx-q8"}
    action_lib.validate_action(_valid(status="trained", lora=good))
    bad = dict(good, alpha=32)
    with pytest.raises(action_lib.ActionError):
        action_lib.validate_action(_valid(status="trained", lora=bad))


def test_name_must_match_directory():
    with pytest.raises(action_lib.ActionError):
        action_lib.validate_action(_valid(name="kick-a"), name="kick-b")


def test_missing_and_extra_keys():
    d = _valid(); d.pop("trigger")
    with pytest.raises(action_lib.ActionError):
        action_lib.validate_action(d)
    d = _valid(); d["surprise"] = 1
    with pytest.raises(action_lib.ActionError):
        action_lib.validate_action(d)


def test_load_unknown_raises(tmp_path, monkeypatch):
    monkeypatch.setenv(action_lib.LIBRARY_ENV, str(tmp_path))
    with pytest.raises(action_lib.ActionError):
        action_lib.load_action("nope")
