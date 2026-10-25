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


@pytest.fixture(autouse=True)
def vlm_lifecycle_isolation(monkeypatch, tmp_path):
    """VLM lifecycle spec 11.1: the movie-ui runner's preflight and postflight, V2's warn and the
    startup restore are off in every test unless the test turns them on itself, and nothing can
    reach the real bin/story-server through them (the tools directory does not exist, port 9 is
    unreachable). Runner subprocesses inherit these variables."""
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "0")
    monkeypatch.setenv("MOVIE_UI_VLM_TOOLS", str(tmp_path / "no-vlm-tools"))
    monkeypatch.setenv("MOVIE_UI_VLM_PORT", "9")
