"""Suite-wide test isolation (robust story spec RSK4): every test sees an empty temporary LoRA
catalog unless it sets LORA_CATALOG_DIR itself, so no suite reads the real
generated/loras/catalog.json once a user has created it."""

import pytest


@pytest.fixture(autouse=True)
def lora_catalog_isolation(monkeypatch, tmp_path):
    path = str(tmp_path / "lora_catalog_isolation")
    monkeypatch.setenv("LORA_CATALOG_DIR", path)
    return path
