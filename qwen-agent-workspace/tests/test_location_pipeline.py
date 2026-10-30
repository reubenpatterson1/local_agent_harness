"""Tests for the location library's pipeline path (docs/superpowers/specs/
2026-10-29-location-lora-design.md, Sections 4.1, 4.2 and 4.7-4.11, test table 6.8: LP1-LP20,
with the plan's Review Focus pins): bin/ltx-story-manifest's per-panel attach,
bin/ltx-story-images' stills attach, bin/ltx-mlx-render's units, bin/ltx-movie's flags and
resolution, and bin/iterate-story.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_location_pipeline.py
Stdlib plus pytest and PIL. No test reads the real HOME, renders, trains, runs Z-Image or the
editor, contacts a model server or touches port 8178: every tool runs in-process against a
temporary workspace (story_engine_testutil.make_ws; each module's WS is patched to it), every
model call goes to that workspace's fake bin/qwen-agent, subprocess launches of the pipeline
tools are recorded instead of run, and every library lives under tmp_path (the autouse story_env
fixture: HOME, CHARACTER_LIBRARY_DIR, LOCATION_LIBRARY_DIR and LORA_CATALOG_DIR).
"""

import importlib.machinery
import json
import os
import shutil
import subprocess
import sys

import pytest
from PIL import Image

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import location_testutil as lt  # noqa: E402
import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


manifest = _load("ltx_story_manifest_for_location", os.path.join("bin", "ltx-story-manifest"))


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


CHAIN_STORY = """# The Harbour

A courier crosses a harbour town to a temple gate and back.

## Panel 1 — Quay
Image: A wide shot of the courier on a stone quay. Photorealistic live-action film still.
Motion: The courier walks along the quay; the camera tracks.
Narration: She hurries.

## Panel 2 — Gate
Motion: The courier climbs the temple steps.
Narration: She climbs.

## Panel 3 — Return
Motion: The courier runs back along the quay.
Narration: She returns.
"""
SHOTS_STORY = """# The Harbour

A courier crosses a harbour town to a temple gate and back.

## Panel 1 — Quay
Image: A wide shot of the courier on a stone quay.
Motion: The courier walks along the quay.
Narration: She hurries.

## Panel 2 — Gate
Image: A wide shot of the courier at a temple gate.
Motion: The courier climbs the temple steps.
Narration: She climbs.

## Panel 3 — Return
Image: A wide shot of the courier on the quay again.
Motion: The courier runs back along the quay.
Narration: She returns.
"""


def _manifest_story(tmp_path, monkeypatch, story_id="lp", text=CHAIN_STORY,
                    beats=("l1", "l2", "l1")):
    """A temporary workspace (manifest.WS) with generated/stories/<story_id>/story.md, one 64x64
    still per panel and, when beats is not None, a plan.json whose beat k is at beats[k - 1]
    (l1 is harbour-street). Returns (ws, story_dir, story_md, images)."""
    ws = seu.make_ws(tmp_path)
    monkeypatch.setattr(manifest, "WS", ws)
    story_dir = os.path.join(ws, "generated", "stories", story_id)
    os.makedirs(story_dir)
    story_md = os.path.join(story_dir, "story.md")
    with open(story_md, "w", encoding="utf-8") as f:
        f.write(text)
    images = []
    for k in range(1, text.count("## Panel ") + 1):
        images.append(os.path.join(story_dir, "panel_%02d.png" % k))
        Image.new("RGB", (64, 64), (90, 90, 90)).save(images[-1])
    if beats is not None:
        lt.write_plan(story_dir, list(beats))
    return ws, story_dir, story_md, images


def _manifest_argv(story_id, story_md, images, shots=False, *extra):
    mode = ["--shots"] + sum([["--image", i] for i in images], []) if shots else [
        "--chain", "--image", images[0]]
    return (["--story-id", story_id, "--prompts-md", story_md] + mode
            + ["--fps", "24", "--target-seconds", "18.125", "--min-frames", "145",
               "--max-frames", "145", "--force"] + list(extra))


def _panels(story_dir):
    with open(os.path.join(story_dir, "manifest.json")) as f:
        return json.load(f)["panels"]


# --- LP5-LP9, Review Focus 3, 4: bin/ltx-story-manifest (L3.7) -------------------------------

@pytest.mark.parametrize("shots", [False, True])
def test_lp5_lp6_the_manifest_attaches_the_planned_beats(tmp_path, monkeypatch, capsys,
                                                         story_env, shots):
    harbour = lt.harbour(story_env["locations"])
    text = SHOTS_STORY if shots else CHAIN_STORY
    ws, story_dir, story_md, images = _manifest_story(tmp_path, monkeypatch, text=text)
    capsys.readouterr()
    assert manifest.main(_manifest_argv("lp", story_md, images, shots,
                                        "--location", "harbour-street")) == 0
    out = capsys.readouterr().out
    panels = _panels(story_dir)
    entry = {"name": "harbour-street", "video_lora": harbour["loras"]["video"]["path"],
             "strength": 0.8}
    assert [p["locations"] for p in panels] == [[entry], [], [entry]]
    assert [p["motion_prompt"] for p in panels] == [
        "harboplc. The courier walks along the quay" + ("." if shots else "; the camera tracks."),
        "The courier climbs the temple steps.", "harboplc. The courier runs back along the quay."]
    assert "location: panel 1: harbour-street@0.8\nlocation: panel 3: harbour-street@0.8\n" in out
    assert "location: panel 2" not in out


def test_lp7_trigger_order_and_the_record_strength(tmp_path, monkeypatch, capsys, story_env):
    lt.harbour(story_env["locations"], strength=0.6)
    seu.kyra(story_env["lib"])
    ws, story_dir, story_md, images = _manifest_story(tmp_path, monkeypatch)
    plan = lt.write_plan(story_dir, ["l1", "l2", "l1"])
    plan["cast"] = [{"id": "c1", "phrase": "the woman in grey", "descriptor": seu.DESC_K,
                     "cast_name": "kyra"}]
    plan["beats"][0]["cast"] = ["c1"]
    with open(os.path.join(story_dir, "plan.json"), "w") as f:
        json.dump(plan, f)
    lora = seu.lora_file(str(tmp_path / "files"), "cat")
    entry = {"id": "cat-style", "kind": "style", "path": lora, "sha256": seu.sha256_file(lora),
             "strength": 0.7, "triggers": ["cattrig"]}
    catalog = os.path.join(story_dir, "catalog_loras.json")
    with open(catalog, "w") as f:
        json.dump({"schema": "ltx-movie.catalog-loras.v1", "story_id": "lp",
                   "panels": [[entry], [], []]}, f)
    assert manifest.main(_manifest_argv(
        "lp", story_md, images, False, "--cast", "the woman in grey=kyra", "--location",
        "harbour-street", "--location-strength", "0.9", "--catalog-loras", catalog)) == 0
    panels = _panels(story_dir)
    assert panels[0]["motion_prompt"] == (
        "cattrig. harboplc. kyrawmn. The courier walks along the quay; the camera tracks.")
    assert [l["strength"] for p in panels for l in p["locations"]] == [0.6, 0.6]
    assert "location: panel 1: harbour-street@0.6" in capsys.readouterr().out


def test_lp8_without_a_usable_plan_no_panel_gets_a_location(tmp_path, monkeypatch, capsys,
                                                            story_env):
    lt.harbour(story_env["locations"])
    lt.temple(story_env["locations"])
    ws, story_dir, story_md, images = _manifest_story(tmp_path, monkeypatch, beats=None)
    capsys.readouterr()
    assert manifest.main(_manifest_argv("lp", story_md, images, False,
                                        "--location", "harbour-street")) == 0
    out = capsys.readouterr().out
    assert out.count("note: there is no plan.json for this story; no location LoRAs are "
                     "attached (location LoRAs attach only to planned beats)\n") == 1
    assert "WARNING" not in out
    assert [p["locations"] for p in _panels(story_dir)] == [[], [], []]
    assert [p["motion_prompt"][:9] for p in _panels(story_dir)] == ["The couri"] * 3
    lt.write_plan(story_dir, ["l1", "l1"])
    assert manifest.main(_manifest_argv("lp", story_md, images, False,
                                        "--location", "harbour-street")) == 0
    assert ("note: plan.json is not usable for locations (it has 2 beats for 3 panels); no "
            "location LoRAs are attached\n") in capsys.readouterr().out
    lt.write_plan(story_dir, ["l1", "l2", "l1"])
    assert manifest.main(_manifest_argv("lp", story_md, images, False, "--location",
                                        "harbour-street", "--location", "temple-gate")) == 0
    out = capsys.readouterr().out
    assert ("WARNING: location temple-gate is the location of no panel's beat in plan.json; it "
            "gets no LoRA\n") in out
    assert "harbour-street is the location of no" not in out


def test_lp9_manifest_argument_errors(tmp_path, monkeypatch, capsys, story_env):
    lt.harbour(story_env["locations"])
    ws, story_dir, story_md, images = _manifest_story(tmp_path, monkeypatch)
    base = ["--story-id", "lp", "--prompts-md", story_md, "--image", images[0], "--force"]
    with pytest.raises(SystemExit) as info:
        manifest.main(base + ["--location", "harbour-street"])
    assert info.value.code == 2
    assert "--location requires --chain or --shots" in capsys.readouterr().err
    with pytest.raises(SystemExit) as info:
        manifest.main(_manifest_argv("lp", story_md, images, False, "--location-strength", "0.5"))
    assert info.value.code == 2
    assert "--location-strength requires --location" in capsys.readouterr().err
    for bad in ("0", "1.5"):
        assert manifest.main(_manifest_argv("lp", story_md, images, False, "--location",
                                            "harbour-street", "--location-strength", bad)) == 2
        assert capsys.readouterr().err == (
            "Error: --location-strength must be in (0, 1], got %r\n" % float(bad))
    assert manifest.main(_manifest_argv("lp", story_md, images, False, "--location", "a",
                                        "--location", "b", "--location", "c", "--location",
                                        "d")) == 2
    assert capsys.readouterr().err == "Error: at most 3 locations, got 4\n"


def test_review_focus_3_a_location_deleted_after_phase_1(tmp_path, monkeypatch, capsys,
                                                         story_env):
    lt.harbour(story_env["locations"])
    ws, story_dir, story_md, images = _manifest_story(tmp_path, monkeypatch)
    shutil.rmtree(os.path.join(story_env["locations"], "harbour-street"))
    assert manifest.main(_manifest_argv("lp", story_md, images, False,
                                        "--location", "harbour-street")) == 2
    assert capsys.readouterr().err == "Error: unknown location: harbour-street (no %s)\n" % (
        os.path.join(story_env["locations"], "harbour-street", "location.json"))
    assert not os.path.exists(os.path.join(story_dir, "manifest.json"))


def test_review_focus_4_a_plan_with_more_beats_than_the_target(tmp_path, monkeypatch, story_env):
    lt.harbour(story_env["locations"])
    four = CHAIN_STORY + ("\n## Panel 4 — Home\nMotion: The courier rests by the harbour "
                          "wall.\nNarration: She rests.\n")
    ws, story_dir, story_md, images = _manifest_story(tmp_path, monkeypatch, text=four,
                                                      beats=("l2", "l1", "l2", "l1"))
    plan_path = os.path.join(story_dir, "plan.json")
    with open(plan_path) as f:
        plan = json.load(f)
    plan["panels_target"] = 3
    with open(plan_path, "w") as f:
        json.dump(plan, f)
    argv = _manifest_argv("lp", story_md, images, False, "--location", "harbour-street")
    argv[argv.index("--target-seconds") + 1] = "24.167"
    assert manifest.main(argv) == 0
    assert [bool(p["locations"]) for p in _panels(story_dir)] == [False, True, False, True]
