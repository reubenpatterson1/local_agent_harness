"""Tests for the location library's dataset builder and trainer (docs/superpowers/specs/
2026-10-29-location-lora-design.md, Sections 2.5-2.12 and 3.2-3.4, test table 6.5: LD1-LD24, with
the plan's Review Focus pins): location_dataset.py, and the qwenedit child extension in
character_dataset.py (LD18).

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_location_dataset.py
Stdlib plus pytest and PIL. No test reads the real HOME, renders, trains, runs Z-Image or the
editor, contacts a model server or touches port 8178: vlm_call, vlm_ready, story_server,
restore_story_server, wait_for_avail, wait_for_vlm, story_server_state, busy_process, free_gib,
edit_models_missing, run_logged, run_zimage_child, run_edit_child, SKILL.generate_video and
psutil.virtual_memory are fakes (the patterns of tests/test_character_dataset.py:579-641 and
:968-998), and every library lives under tmp_path (HOME, CHARACTER_LIBRARY_DIR,
LOCATION_LIBRARY_DIR and LORA_CATALOG_DIR). Real ffmpeg/ffprobe wrap the kept stills, as the
character tests do.
"""

import argparse
import json
import os
import sys
import types

import pytest
from PIL import Image

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import character_dataset  # noqa: E402
import story_engine_testutil as seu  # noqa: E402


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


# --- LD18: the qwenedit child takes a per-job image and a spec skill (L1.8) -----------------

def _fake_edit_stack(monkeypatch, calls):
    """Fake torch, diffusers, huggingface_hub and content_safety for child_qwenedit (as
    tests/test_character_dataset.py's test_d44_child_qwenedit); records pipe calls, the screen's
    skill and every Image.open path."""

    class _Blocked(Exception):
        pass

    class _Generator(object):
        def __init__(self, device):
            pass

        def manual_seed(self, seed):
            self.seed = seed
            return self

    class _Pipe(object):
        def to(self, device):
            return self

        def load_lora_weights(self, path):
            calls["lora"] = path

        def set_progress_bar_config(self, **kwargs):
            pass

        def __call__(self, **kwargs):
            calls["pipe"].append(kwargs)
            return types.SimpleNamespace(images=[Image.new("RGB", (kwargs["width"],
                                                                  kwargs["height"]), (0, 255, 0))])

    def _assert_safe(image, skill, prompt):
        calls["skills"].append(skill)

    fake_torch = types.ModuleType("torch")
    fake_torch.Generator = _Generator
    fake_torch.bfloat16 = "bf16"
    fake_torch.backends = types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: True))
    fake_diffusers = types.ModuleType("diffusers")
    fake_diffusers.QwenImageEditPlusPipeline = types.SimpleNamespace(
        from_pretrained=lambda model, **kwargs: _Pipe())
    fake_hub = types.ModuleType("huggingface_hub")
    fake_hub.hf_hub_download = lambda repo, name, local_files_only: "/cache/%s/%s" % (repo, name)
    fake_safety = types.ModuleType("content_safety")
    fake_safety.ContentSafetyError = _Blocked
    fake_safety.assert_image_safe = _assert_safe
    for name, module in (("torch", fake_torch), ("diffusers", fake_diffusers),
                         ("huggingface_hub", fake_hub), ("content_safety", fake_safety)):
        monkeypatch.setitem(sys.modules, name, module)
    real_open = Image.open

    def _open(path, *args, **kwargs):
        calls["opened"].append(path)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(character_dataset.Image, "open", _open)


def test_ld18_the_qwenedit_child_takes_a_per_job_image_and_skill(tmp_path, monkeypatch):
    a, b = str(tmp_path / "a.png"), str(tmp_path / "b.png")
    Image.new("RGB", (300, 200), (10, 20, 30)).save(a)
    Image.new("RGB", (200, 300), (40, 50, 60)).save(b)

    def _spec(name, jobs, **extra):
        spec = dict({"image": a, "model": "M", "lora_repo": "R", "lora_file": "F.safetensors",
                     "steps": 8, "true_cfg": 1.0,
                     "report_path": str(tmp_path / ("%s.report.json" % name)), "jobs": jobs},
                    **extra)
        path = str(tmp_path / ("%s.spec.json" % name))
        with open(path, "w") as f:
            json.dump(spec, f)
        return path

    def _job(k, image=None):
        job = {"prompt": "edit %d" % k, "output_path": str(tmp_path / ("out_%d.png" % k)),
               "seed": 5, "width": 64, "height": 40}
        if image is not None:
            job["image"] = image
        return job

    calls = {"pipe": [], "skills": [], "opened": [], "lora": None}
    _fake_edit_stack(monkeypatch, calls)
    path = _spec("loc", [_job(1, a), _job(2, b), _job(3, a), _job(4, b)], skill="location_edit")
    assert character_dataset.main(["qwenedit", "--spec", path]) == 0
    assert calls["opened"] == [a, b]
    assert [c["image"][0].size for c in calls["pipe"]] == [(300, 200), (200, 300), (300, 200),
                                                         (200, 300)]
    assert calls["skills"] == ["location_edit"] * 4
    with open(str(tmp_path / "loc.report.json")) as f:
        assert [j["status"] for j in json.load(f)["jobs"]] == ["ok"] * 4
    # A character-shaped spec (no per-job image, no skill) behaves exactly as before.
    calls.update(pipe=[], skills=[], opened=[])
    path = _spec("char", [_job(5), _job(6)])
    assert character_dataset.main(["qwenedit", "--spec", path]) == 0
    assert calls["opened"] == [a]
    assert [c["image"][0].size for c in calls["pipe"]] == [(300, 200), (300, 200)]
    assert calls["skills"] == ["character_edit"] * 2
    assert [(c["prompt"], c["num_inference_steps"], c["true_cfg_scale"], c["generator"].seed)
            for c in calls["pipe"]] == [("edit 5", 8, 1.0, 5), ("edit 6", 8, 1.0, 5)]
