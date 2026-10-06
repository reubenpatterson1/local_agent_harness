"""Tests for z_image_skill's multi-adapter LoRA path (spec docs/superpowers/specs/
2026-10-05-character-library-design.md Section 9.6, Z1-Z6).

Run from the workspace root: python3 -m pytest tests/test_z_image_skill_multi_lora.py
No model is loaded: Qwen3Model and ZImagePipeline are replaced by recording fakes
(the tests/test_z_image_skill_cache.py:108-139 pattern, extended with adapters).
"""

import torch

import pytest
import z_image_skill


@pytest.fixture(autouse=True)
def _fresh_singleton(monkeypatch):
    monkeypatch.setattr(z_image_skill, "_pipeline", None)
    monkeypatch.setattr(z_image_skill, "_pipeline_loras", None)
    monkeypatch.setattr(z_image_skill, "_pick_device", lambda: torch.device("cpu"))
    monkeypatch.delenv("Z_IMAGE_QUANTIZE_WEIGHTS", raising=False)


def _fake_pipeline_classes(record):
    """A pipeline that records LoRA/adapter calls. get_list_adapters reports every loaded
    adapter name, except one whose path contains "nomatch" (it matched no weights)."""

    class FakeQwen3Model:
        @staticmethod
        def from_pretrained(model_id, **kwargs):
            record["constructed"].append(model_id)
            return "FAKE_TEXT_ENCODER"

    class _FakeVAE:
        def to(self, dtype):
            pass

    class _FakePipeline:
        def __init__(self):
            self.vae = _FakeVAE()
            self.adapters = []

        def to(self, device):
            return self

        def load_lora_weights(self, path_or_repo, **kwargs):
            record["lora_calls"].append((path_or_repo, kwargs) if kwargs else path_or_repo)
            if "nomatch" not in path_or_repo:
                self.adapters.append(kwargs.get("adapter_name", "default_0"))

        def get_list_adapters(self):
            return {"transformer": list(self.adapters)}

        def set_adapters(self, names, adapter_weights=None):
            record["set_adapters"].append((list(names), adapter_weights))

        def fuse_lora(self, **kwargs):
            record["fuse_calls"].append(kwargs)

    class FakeZImagePipeline:
        @staticmethod
        def from_pretrained(model_id, **kwargs):
            return _FakePipeline()

    return FakeQwen3Model, FakeZImagePipeline


def _install(monkeypatch):
    record = {"constructed": [], "lora_calls": [], "set_adapters": [], "fuse_calls": []}
    FakeQwen3Model, FakeZImagePipeline = _fake_pipeline_classes(record)
    monkeypatch.setattr(z_image_skill, "Qwen3Model", FakeQwen3Model)
    monkeypatch.setattr(z_image_skill, "ZImagePipeline", FakeZImagePipeline)
    return record


class _Image:
    def save(self, path):
        pass


class _CallablePipeline:
    def __call__(self, prompt, **kwargs):
        return type("Result", (), {"images": [_Image()]})()


def test_z1_adapters_weighted_and_fused_once(monkeypatch):
    record = _install(monkeypatch)
    z_image_skill.load_pipeline(loras=[("a.st", 1.0), ("b.st", 0.8)])
    assert record["lora_calls"] == [("a.st", {"adapter_name": "lora0"}),
                                    ("b.st", {"adapter_name": "lora1"})]
    assert record["set_adapters"] == [(["lora0", "lora1"], [1.0, 0.8])]
    assert record["fuse_calls"] == [{"adapter_names": ["lora0", "lora1"], "lora_scale": 1.0}]


def test_z2_lora_path_and_loras_are_exclusive(monkeypatch):
    record = _install(monkeypatch)
    with pytest.raises(ValueError, match="lora_path and loras are mutually exclusive"):
        z_image_skill.load_pipeline(lora_path="x", loras=[("a", 1.0)])
    assert record["constructed"] == []


def test_z3_unregistered_adapter_is_rejected(monkeypatch):
    record = _install(monkeypatch)
    with pytest.raises(ValueError, match="matched no Z-Image transformer weights"):
        z_image_skill.load_pipeline(loras=[("nomatch.st", 1.0)])
    assert record["set_adapters"] == []
    assert record["fuse_calls"] == []


def test_z4_singleton_refuses_a_different_lora_set(monkeypatch):
    calls = []

    def _load(lora_path=None, loras=None):
        calls.append((lora_path, loras))
        return _CallablePipeline()

    monkeypatch.setattr(z_image_skill, "load_pipeline", _load)
    monkeypatch.setattr(z_image_skill.content_safety, "assert_image_safe",
                        lambda image, **kw: None)
    z_image_skill.generate_image("p", loras=[("a", 1.0)])
    z_image_skill.generate_image("p", loras=[("a", 1.0)])
    assert calls == [(None, [("a", 1.0)])]
    with pytest.raises(RuntimeError, match="needs a new process"):
        z_image_skill.generate_image("p", loras=[("b", 1.0)])
    assert len(calls) == 1


def test_z5_uncast_call_shape_unchanged(monkeypatch):
    fake = _CallablePipeline()
    monkeypatch.setattr(z_image_skill, "load_pipeline", lambda lora_path=None: fake)
    monkeypatch.setattr(z_image_skill.content_safety, "assert_image_safe",
                        lambda image, **kw: None)
    image = z_image_skill.generate_image("p", lora_path="x")
    assert isinstance(image, _Image)


def test_z6_single_lora_path_unchanged(monkeypatch):
    record = _install(monkeypatch)
    z_image_skill.load_pipeline(lora_path="my_lora.safetensors")
    assert record["lora_calls"] == ["my_lora.safetensors"]
    assert record["fuse_calls"] == [{"lora_scale": 1.0}]
    assert record["set_adapters"] == []
