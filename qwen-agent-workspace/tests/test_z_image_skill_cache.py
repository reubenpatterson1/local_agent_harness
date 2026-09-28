import os
import torch

import pytest
import z_image_skill


def test_scoped_hit(tmp_path, monkeypatch):
    # Create the expected repo directory inside the scoped hub cache.
    repo_dir = tmp_path / "hub" / "models--Tongyi-MAI--Z-Image-Turbo"
    repo_dir.mkdir(parents=True)
    monkeypatch.setenv("Z_IMAGE_HF_HOME", str(tmp_path))

    assert (
        z_image_skill._cache_dir_for("Tongyi-MAI/Z-Image-Turbo")
        == str(tmp_path / "hub")
    )


def test_scoped_miss_falls_back(tmp_path, monkeypatch):
    # Only the hub directory exists; the specific repo does not.
    (tmp_path / "hub").mkdir()
    monkeypatch.setenv("Z_IMAGE_HF_HOME", str(tmp_path))

    assert z_image_skill._cache_dir_for("Tongyi-MAI/Z-Image-Turbo") is None


def test_default_root_is_home_hf_home(monkeypatch):
    monkeypatch.delenv("Z_IMAGE_HF_HOME", raising=False)
    assert z_image_skill._z_image_hf_home() == os.path.expanduser("~/hf_home")


def test_env_read_at_call_time(tmp_path, monkeypatch):
    monkeypatch.setenv("Z_IMAGE_HF_HOME", str(tmp_path / "a"))
    assert z_image_skill._z_image_hf_home().endswith("a")

    # Change the environment variable without reloading the module.
    monkeypatch.setenv("Z_IMAGE_HF_HOME", str(tmp_path / "b"))
    assert z_image_skill._z_image_hf_home().endswith("b")


def test_load_pipeline_passes_cache_dir(tmp_path, monkeypatch):
    # Create only the text-encoder repo dir, not the base model's.
    (tmp_path / "hub" / "models--BennyDaBall--Qwen3-4b-Z-Image-Turbo-AbliteratedV1").mkdir(
        parents=True
    )
    monkeypatch.setenv("Z_IMAGE_HF_HOME", str(tmp_path))

    # Force CPU device to avoid GPU checks.
    monkeypatch.setattr(z_image_skill, "_pick_device", lambda: torch.device("cpu"))

    # Containers to capture call information.
    record = {
        "qwen_calls": 0,
        "pipeline_calls": 0,
    }

    class FakeQwen3Model:
        @staticmethod
        def from_pretrained(model_id, **kwargs):
            record["qwen_calls"] += 1
            record["qwen_model_id"] = model_id
            record["qwen_kwargs"] = kwargs
            return "FAKE_TEXT_ENCODER"

    class _FakeVAE:
        def to(self, dtype):
            # No-op; just record the dtype if desired.
            self._dtype = dtype

    class _FakePipeline:
        def __init__(self):
            self.vae = _FakeVAE()
            self._to_device = None

        def to(self, device):
            self._to_device = device
            return self

    class FakeZImagePipeline:
        @staticmethod
        def from_pretrained(model_id, **kwargs):
            record["pipeline_calls"] += 1
            record["pipeline_model_id"] = model_id
            record["pipeline_kwargs"] = kwargs
            return _FakePipeline()

    # Patch the imported classes in the module.
    monkeypatch.setattr(z_image_skill, "Qwen3Model", FakeQwen3Model)
    monkeypatch.setattr(z_image_skill, "ZImagePipeline", FakeZImagePipeline)

    # Run the function under test.
    pipeline = z_image_skill.load_pipeline()

    # Assertions on the captured arguments.
    assert record["qwen_calls"] == 1
    assert record["pipeline_calls"] == 1

    # Text encoder cache dir should point to the scoped hub.
    assert record["qwen_kwargs"]["cache_dir"] == str(tmp_path / "hub")
    # Base model cache dir should be None (default HF cache).
    assert record["pipeline_kwargs"]["cache_dir"] is None

    # Ensure the returned object behaves like a pipeline (has .vae).
    assert hasattr(pipeline, "vae")


def _fake_pipeline_classes(record):
    """Shared fakes for the LoRA tests below: a pipeline that records
    load_lora_weights/fuse_lora calls instead of doing anything real."""

    class FakeQwen3Model:
        @staticmethod
        def from_pretrained(model_id, **kwargs):
            return "FAKE_TEXT_ENCODER"

    class _FakeVAE:
        def to(self, dtype):
            pass

    class _FakePipeline:
        def __init__(self):
            self.vae = _FakeVAE()

        def to(self, device):
            return self

        def load_lora_weights(self, path_or_repo, **kwargs):
            record["lora_calls"].append(path_or_repo)

        def fuse_lora(self, **kwargs):
            record["fuse_calls"].append(kwargs)

    class FakeZImagePipeline:
        @staticmethod
        def from_pretrained(model_id, **kwargs):
            return _FakePipeline()

    return FakeQwen3Model, FakeZImagePipeline


def test_load_pipeline_applies_lora(monkeypatch):
    monkeypatch.setattr(z_image_skill, "_pick_device", lambda: torch.device("cpu"))
    record = {"lora_calls": [], "fuse_calls": []}
    FakeQwen3Model, FakeZImagePipeline = _fake_pipeline_classes(record)
    monkeypatch.setattr(z_image_skill, "Qwen3Model", FakeQwen3Model)
    monkeypatch.setattr(z_image_skill, "ZImagePipeline", FakeZImagePipeline)

    z_image_skill.load_pipeline(lora_path="my_lora.safetensors")

    assert record["lora_calls"] == ["my_lora.safetensors"]
    assert record["fuse_calls"] == [{"lora_scale": 1.0}]


def test_load_pipeline_no_lora_by_default(monkeypatch):
    monkeypatch.setattr(z_image_skill, "_pick_device", lambda: torch.device("cpu"))
    record = {"lora_calls": [], "fuse_calls": []}
    FakeQwen3Model, FakeZImagePipeline = _fake_pipeline_classes(record)
    monkeypatch.setattr(z_image_skill, "Qwen3Model", FakeQwen3Model)
    monkeypatch.setattr(z_image_skill, "ZImagePipeline", FakeZImagePipeline)

    z_image_skill.load_pipeline()

    assert record["lora_calls"] == []
    assert record["fuse_calls"] == []


def test_quantize_weights_env_default_none(monkeypatch):
    monkeypatch.delenv("Z_IMAGE_QUANTIZE_WEIGHTS", raising=False)
    assert z_image_skill._quantize_weights_env() is None


def test_quantize_weights_env_int8(monkeypatch):
    monkeypatch.setenv("Z_IMAGE_QUANTIZE_WEIGHTS", "int8")
    assert z_image_skill._quantize_weights_env() == "int8"


def test_quantize_weights_env_invalid_raises(monkeypatch):
    monkeypatch.setenv("Z_IMAGE_QUANTIZE_WEIGHTS", "int4")
    with pytest.raises(ValueError, match="int4"):
        z_image_skill._quantize_weights_env()


def test_quantize_transformer_real_int8():
    """Real (unmocked) optimum-quanto quantization on a throwaway module --
    cheap and fast even though it's not a fake, confirmed on the real
    Z-Image-Turbo transformer too (11.46 GiB bf16 -> 5.74 GiB, 2026-09-27)."""

    class Wrapper(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.proj = torch.nn.Linear(64, 64, bias=False, dtype=torch.bfloat16)

    m = Wrapper()
    z_image_skill._quantize_transformer(m, "int8")

    assert type(m.proj).__name__ == "QLinear"
    assert m.proj.weight._data.dtype == torch.int8


def _fake_transformer_class(record):
    class _FakeTransformer:
        pass

    class FakeZImageTransformer2DModel:
        @staticmethod
        def from_pretrained(model_id, **kwargs):
            record["transformer_calls"] += 1
            record["transformer_kwargs"] = kwargs
            return _FakeTransformer()

    return FakeZImageTransformer2DModel, _FakeTransformer


def test_load_pipeline_skips_quantization_by_default(monkeypatch):
    monkeypatch.delenv("Z_IMAGE_QUANTIZE_WEIGHTS", raising=False)
    monkeypatch.setattr(z_image_skill, "_pick_device", lambda: torch.device("cpu"))
    record = {"lora_calls": [], "fuse_calls": [], "transformer_calls": 0,
              "quantize_calls": []}
    FakeQwen3Model, FakeZImagePipeline = _fake_pipeline_classes(record)
    FakeZImageTransformer2DModel, _ = _fake_transformer_class(record)
    monkeypatch.setattr(z_image_skill, "Qwen3Model", FakeQwen3Model)
    monkeypatch.setattr(z_image_skill, "ZImagePipeline", FakeZImagePipeline)
    monkeypatch.setattr(z_image_skill, "ZImageTransformer2DModel", FakeZImageTransformer2DModel)
    monkeypatch.setattr(z_image_skill, "_quantize_transformer",
                         lambda t, q: record["quantize_calls"].append((t, q)))

    z_image_skill.load_pipeline()

    assert record["transformer_calls"] == 0
    assert record["quantize_calls"] == []


def test_load_pipeline_quantizes_transformer_when_env_set(monkeypatch):
    monkeypatch.setenv("Z_IMAGE_QUANTIZE_WEIGHTS", "int8")
    monkeypatch.setattr(z_image_skill, "_pick_device", lambda: torch.device("cpu"))

    class FakeQwen3Model:
        @staticmethod
        def from_pretrained(model_id, **kwargs):
            return "FAKE_TEXT_ENCODER"

    class _FakeVAE:
        def to(self, dtype):
            pass

    class _FakePipeline:
        def __init__(self):
            self.vae = _FakeVAE()

        def to(self, device):
            return self

    pipeline_calls = []

    class FakeZImagePipeline:
        @staticmethod
        def from_pretrained(model_id, **kwargs):
            pipeline_calls.append(kwargs)
            return _FakePipeline()

    transformer_record = {"transformer_calls": 0}
    FakeZImageTransformer2DModel, FakeTransformer = _fake_transformer_class(transformer_record)
    quantize_calls = []

    monkeypatch.setattr(z_image_skill, "Qwen3Model", FakeQwen3Model)
    monkeypatch.setattr(z_image_skill, "ZImagePipeline", FakeZImagePipeline)
    monkeypatch.setattr(z_image_skill, "ZImageTransformer2DModel", FakeZImageTransformer2DModel)
    monkeypatch.setattr(z_image_skill, "_quantize_transformer",
                         lambda t, q: quantize_calls.append((t, q)))

    z_image_skill.load_pipeline()

    assert transformer_record["transformer_calls"] == 1
    assert len(quantize_calls) == 1
    transformer_obj, qtype = quantize_calls[0]
    assert isinstance(transformer_obj, FakeTransformer)
    assert qtype == "int8"
    assert len(pipeline_calls) == 1
    assert pipeline_calls[0]["transformer"] is transformer_obj
