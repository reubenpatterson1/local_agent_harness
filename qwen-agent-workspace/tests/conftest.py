"""Suite-wide test isolation (robust story spec RSK4): every test sees an empty temporary LoRA
catalog unless it sets LORA_CATALOG_DIR itself, so no suite reads the real
generated/loras/catalog.json once a user has created it."""

import pytest


@pytest.fixture(autouse=True)
def lora_catalog_isolation(monkeypatch, tmp_path):
    path = str(tmp_path / "lora_catalog_isolation")
    monkeypatch.setenv("LORA_CATALOG_DIR", path)
    return path


@pytest.fixture(autouse=True)
def ltx_autotune_isolation(monkeypatch):
    """The host-aware LTX autotune (ltx2_mlx_video_skill, QWEN_LTX_AUTOTUNE) is off in every test
    unless the test turns it on itself, whatever the developer's shell exports."""
    monkeypatch.delenv("QWEN_LTX_AUTOTUNE", raising=False)
    monkeypatch.delenv("QWEN_LTX_MEM_GIB", raising=False)
