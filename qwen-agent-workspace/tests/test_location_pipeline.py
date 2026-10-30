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


# --- LP10-LP12: bin/ltx-story-images (L3.8) ---------------------------------------------------

images = _load("ltx_story_images_for_location", os.path.join("bin", "ltx-story-images"))
IMAGES_STORY = """# The Harbour

A courier crosses a harbour town.

## Panel 1 — Quay
Image: A wide shot of the woman in grey on a stone quay.
Motion: The woman in grey walks along the quay.

## Panel 2 — Gate
Image: A wide shot of the woman in grey at a temple gate.
Motion: The woman in grey climbs the temple steps.

## Panel 3 — Return
Image: A wide shot of the woman in grey on the quay again.
Motion: The woman in grey runs back along the quay.
"""


def _images_story(tmp_path, beats=("l1", "l2", "l1"), pinned=(("l1", "harbour-street"),)):
    story_dir = str(tmp_path / "story")
    os.makedirs(story_dir)
    story_md = os.path.join(story_dir, "story.md")
    with open(story_md, "w", encoding="utf-8") as f:
        f.write(IMAGES_STORY)
    lt.write_plan(story_dir, list(beats), pinned=pinned)
    return story_md, os.path.join(story_dir, "images")


def _images(story_md, out_dir, *extra):
    return images.main(["--story-md", story_md, "--out-dir", out_dir, "--dry-run"] + list(extra))


def test_lp10_chained_panel_1_gets_the_stills_lora(tmp_path, capsys, story_env):
    harbour = lt.harbour(story_env["locations"], stills=True)
    story_md, out = _images_story(tmp_path)
    capsys.readouterr()
    assert _images(story_md, out, "--only", "1", "--location", "harbour-street") == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == ["1 | %s | %r" % (os.path.join(out, "panel_01.png"),
                                      "harboplc. A wide shot of the woman in grey on a stone quay."),
                     "    loras: harbour-street=%s@0.8" % harbour["loras"]["stills"]["path"]]
    seed = str(tmp_path / "seed.png")
    Image.new("RGB", (64, 64)).save(seed)
    assert _images(story_md, out, "--only", "1", "--seed-image", seed, "--location",
                   "harbour-street", "--location-strength", "0.5") == 0
    assert capsys.readouterr().out.splitlines() == [
        "1 | %s | seed: %s" % (os.path.join(out, "panel_01.png"), seed)]


def test_lp11_shots_order_warning_one_set_and_duplicates(tmp_path, capsys, story_env):
    harbour = lt.harbour(story_env["locations"], stills=True)
    temple = lt.temple(story_env["locations"])
    seu.kyra(story_env["lib"])
    kyra_stills = os.path.join(story_env["lib"], "kyra", "lora", "stills.safetensors")
    glob_lora = seu.lora_file(str(tmp_path / "files"), "grain")
    story_md, out = _images_story(tmp_path, pinned=(("l1", "harbour-street"),
                                                    ("l2", "temple-gate")))
    capsys.readouterr()
    common = ["--shots", "--cast", "the woman in grey=kyra", "--lora", glob_lora + ":0.5",
              "--location", "harbour-street", "--location", "temple-gate"]
    assert _images(story_md, out, "--only", "1", *common) == 0
    out_lines = capsys.readouterr().out.splitlines()
    assert ("WARNING: location temple-gate has no stills LoRA (not trained); its trigger is not "
            "added to Image: prompts and its panels render without it") in out_lines
    assert out_lines[-1] == "    loras: global=%s@0.5, harbour-street=%s@0.8, kyra=%s@0.8" % (
        os.path.abspath(glob_lora), harbour["loras"]["stills"]["path"], kyra_stills)
    assert "'harboplc. A wide shot of the kyrawmn woman in grey on a stone quay." in out_lines[-2]
    assert _images(story_md, out, "--only", "2", *common) == 0
    out_lines = capsys.readouterr().out.splitlines()
    assert "templplc" not in out_lines[-2]
    assert out_lines[-1] == "    loras: global=%s@0.5, kyra=%s@0.8" % (
        os.path.abspath(glob_lora), kyra_stills)
    assert _images(story_md, out, "--only", "1,2", *common) == 2
    assert capsys.readouterr().err == (
        "Error: the selected panels need different stills LoRA sets (z_image_skill loads one set "
        "per process); run one --only panel per invocation\n")
    assert _images(story_md, out, "--only", "1,3", *common) == 0
    capsys.readouterr()
    for given in (harbour["loras"]["stills"]["path"] + ":0.5", harbour["loras"]["stills"]["path"]):
        assert _images(story_md, out, "--only", "1", "--lora", given, "--location",
                       "harbour-street") == 2
        assert capsys.readouterr().err == (
            "Error: --lora %s is also location harbour-street's stills LoRA; pass it once\n"
            % harbour["loras"]["stills"]["path"])
    assert _images(story_md, out, "--only", "1", "--location-strength", "0.5") == 2
    assert capsys.readouterr().err == "Error: --location-strength requires --location\n"
    assert _images(story_md, out, "--only", "1", "--location", "nowhere") == 2
    assert capsys.readouterr().err.startswith("Error: unknown location: nowhere (no ")
    assert temple["loras"]["stills"] is None


def test_lp12_the_i20_source_counts_hold():
    with open(os.path.join(WS, "bin", "ltx-story-images"), encoding="utf-8") as f:
        source = f.read()
    assert source.count("_compose_prompt(") == 3
    assert source.count("_panel_seed(args.seed, i, grounded)") == 2


# --- LP14-LP19: bin/ltx-mlx-render (L3.9) ------------------------------------------------------

render = _load("ltx_mlx_render_for_location", os.path.join("bin", "ltx-mlx-render"))


def _render_at_d210c26(tmp_path):
    """bin/ltx-mlx-render as it was at d210c26, loaded from git show (skips outside a git
    checkout that has d210c26)."""
    old = subprocess.run(["git", "-C", WS, "show", "d210c26:./bin/ltx-mlx-render"],
                         capture_output=True, text=True)
    if old.returncode != 0:
        pytest.skip("not a git checkout with d210c26")
    path = str(tmp_path / "ltx_mlx_render_d210c26.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(old.stdout)
    return importlib.machinery.SourceFileLoader("ltx_mlx_render_d210c26", path).load_module()


def _lora(tmp_path, name):
    return seu.lora_file(str(tmp_path / "loras"), name)


def _render_panels(tmp_path, with_location=True):
    """Three t2v panels: panel 2 has a character, a catalog style and a catalog motion LoRA and,
    with_location, a location."""
    character, style, motion, place = (_lora(tmp_path, n) for n in ("kyra", "grain", "fast",
                                                                     "harbour"))
    catalog = [{"id": "film-grain", "kind": "style", "path": style,
                "sha256": seu.sha256_file(style), "strength": 0.6, "triggers": []},
               {"id": "fast-motion", "kind": "motion", "path": motion,
                "sha256": seu.sha256_file(motion), "strength": 0.7, "triggers": []}]
    panels = [{"index": k, "image_path": None, "panel_text": "text %d" % k,
               "motion_prompt": "motion %d" % k, "conditioning": "t2v"} for k in (1, 2, 3)]
    panels[1]["characters"] = [{"name": "kyra", "phrase": "the woman in grey",
                                "trigger": "kyrawmn", "video_lora": character, "strength": 0.8}]
    panels[1]["catalog_loras"] = catalog
    if with_location:
        panels[1]["locations"] = [{"name": "harbour-street", "video_lora": place,
                                   "strength": 0.8}]
    return panels, place


def test_lp14_the_render_unit_order(tmp_path):
    panels, place = _render_panels(tmp_path)
    globals_ = [{"path": _lora(tmp_path, "global"), "strength": 1.0}]
    units = render.build_units(json.loads(json.dumps(panels)), 0, "/clips", global_loras=globals_)
    assert [(l["kind"], l["name"]) for l in units[1]["loras"]] == [
        ("catalog", "fast-motion"), ("global", None), ("catalog", "film-grain"),
        ("location", "harbour-street"), ("character", "kyra")]
    assert units[1]["loras"][3] == {"kind": "location", "name": "harbour-street", "path": place,
                                    "strength": 0.8}
    assert "loras" in units[0] and [l["kind"] for l in units[0]["loras"]] == ["global"]
    old = _render_at_d210c26(tmp_path)
    plain, _place = _render_panels(tmp_path, with_location=False)
    assert render.build_units(json.loads(json.dumps(plain)), 0, "/clips",
                              global_loras=globals_) == old.build_units(
        json.loads(json.dumps(plain)), 0, "/clips", global_loras=globals_)


def _manifest_file(tmp_path, panels, name="manifest.json"):
    path = str(tmp_path / name)
    with open(path, "w") as f:
        json.dump({"schema_version": 3, "story_id": "location-lp", "panels": panels}, f)
    return path


def test_lp15_load_manifest_location_errors(tmp_path):
    panels, place = _render_panels(tmp_path)
    assert render.load_manifest(_manifest_file(tmp_path, panels))["panels"][1]["locations"] == [
        {"name": "harbour-street", "video_lora": place, "strength": 0.8}]
    good = {"name": "harbour-street", "video_lora": place, "strength": 0.8}
    for value, message in (
            ("harbour-street", "panel 2: locations must be a list"),
            ([dict(good, name="")], "panel 2: every locations entry needs a non-empty name"),
            (["harbour-street"], "panel 2: every locations entry needs a non-empty name"),
            ([good, dict(good, name="temple-gate")], "panel 2: at most one location per panel"),
            ([dict(good, video_lora="relative.safetensors")],
             "panel 2: location harbour-street's video_lora is not a readable file: "
             "relative.safetensors"),
            ([dict(good, video_lora=str(tmp_path / "missing.safetensors"))],
             "panel 2: location harbour-street's video_lora is not a readable file: %s"
             % (tmp_path / "missing.safetensors")),
            ([dict(good, strength=1.5)],
             "panel 2: location harbour-street's strength must be a number in (0, 1], got 1.5"),
            ([dict(good, strength=True)],
             "panel 2: location harbour-street's strength must be a number in (0, 1], got True")):
        bad = json.loads(json.dumps(panels))
        bad[1]["locations"] = value
        with pytest.raises(ValueError) as info:
            render.load_manifest(_manifest_file(tmp_path, bad))
        assert str(info.value) == message, value
    empty = json.loads(json.dumps(panels))
    empty[1]["locations"] = []
    render.load_manifest(_manifest_file(tmp_path, empty))


def _render_dry_run(tmp_path, panels, *extra):
    model = tmp_path / "model"
    model.mkdir(exist_ok=True)
    return render.main([_manifest_file(tmp_path, panels), str(tmp_path / "out.mp4"), "--dry-run",
                        "--model", str(model), "--clips-dir", str(tmp_path / "clips")]
                       + list(extra))


def test_lp16_render_refuses_a_location_lora_given_twice(tmp_path, capsys):
    panels, place = _render_panels(tmp_path)
    assert _render_dry_run(tmp_path, panels, "--lora", place + ":0.5") == 2
    assert capsys.readouterr().err == (
        "Error: --lora %s is also location harbour-street's video LoRA (panel 2); pass it once\n"
        % place)
    twice = json.loads(json.dumps(panels))
    twice[1]["catalog_loras"][0]["path"] = place
    twice[1]["catalog_loras"][0]["sha256"] = seu.sha256_file(place)
    assert _render_dry_run(tmp_path, twice) == 2
    assert capsys.readouterr().err == (
        "Error: catalog LoRA film-grain (panel 2) is also location harbour-street's video LoRA\n")


def test_lp17_a_location_panel_takes_the_merged_route(tmp_path, capsys):
    panels = [{"index": 1, "image_path": None, "panel_text": "text", "motion_prompt": "motion",
               "conditioning": "t2v",
               "locations": [{"name": "harbour-street", "video_lora": _lora(tmp_path, "place"),
                              "strength": 0.8}]}]
    one = _lora(tmp_path, "global")
    assert _render_dry_run(tmp_path, panels, "--lora", one) == 0
    out = capsys.readouterr().out
    assert "            lora: %s @ 1.0 (global)\n" % one in out
    assert "            lora: %s @ 0.8 (harbour-street)\n" % panels[0]["locations"][0][
        "video_lora"] in out
    plain = [dict(panels[0])]
    del plain[0]["locations"]
    assert _render_dry_run(tmp_path, plain, "--lora", one) == 0
    assert "(global)" not in capsys.readouterr().out


def _audio_lora(path):
    """A safetensors LoRA with one video and one audio-stream module (tests/
    test_video_only_lora.py's layout)."""
    import struct
    header, data = {"__metadata__": {"lora_alpha": "8"}}, b""
    for i, module in enumerate(("attn1.to_q", "audio_attn1.to_q")):
        for j, part in enumerate(("lora_A", "lora_B")):
            name = "diffusion_model.transformer_blocks.0." + module + "." + part + ".weight"
            header[name] = {"dtype": "F32", "shape": [1], "data_offsets": [len(data), len(data) + 4]}
            data += struct.pack("<f", float(10 * i + j + 1))
    blob = json.dumps(header).encode("utf-8")
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(blob)) + blob + data)
    return path


def test_lp18_location_loras_render_without_audio_modules(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "VIDEO_ONLY_LORA_DIR", str(tmp_path / "cache"))
    src = _audio_lora(str(tmp_path / "place.safetensors"))
    units = [{"loras": [{"kind": "location", "path": src}, {"kind": "global", "path": src},
                        {"kind": "character", "path": src}]}]
    render.use_video_only_character_loras(units)
    location, global_lora, character = [l["path"] for l in units[0]["loras"]]
    assert location == character != src and global_lora == src
    assert os.path.dirname(location) == str(tmp_path / "cache")
    with open(location, "rb") as f:
        import struct
        header = json.loads(f.read(struct.unpack("<Q", f.read(8))[0]))
    assert sorted(k for k in header if k != "__metadata__") == [
        "diffusion_model.transformer_blocks.0.attn1.to_q.lora_A.weight",
        "diffusion_model.transformer_blocks.0.attn1.to_q.lora_B.weight"]


def test_lp19_provenance_changes_only_for_the_location_panel(tmp_path):
    old = _render_at_d210c26(tmp_path)
    model = tmp_path / "model"
    model.mkdir()
    args = render.build_parser().parse_args([str(tmp_path / "m.json"), str(tmp_path / "o.mp4"),
                                             "--model", str(model)])
    plain, _place = _render_panels(tmp_path, with_location=False)
    located, _place = _render_panels(tmp_path)
    before = [old.build_clip_provenance(u, args)
              for u in old.build_units(json.loads(json.dumps(plain)), 0, "/clips")]
    after = [render.build_clip_provenance(u, args)
             for u in render.build_units(json.loads(json.dumps(located)), 0, "/clips")]
    unchanged = [render.build_clip_provenance(u, args)
                 for u in render.build_units(json.loads(json.dumps(plain)), 0, "/clips")]
    assert unchanged == before
    assert (after[0], after[2]) == (before[0], before[2])
    assert after[1] != before[1]
    assert [l["kind"] for l in after[1]["loras"]] == ["catalog", "catalog", "location", "character"]
    assert after[1]["loras"][2]["sha256"] == seu.sha256_file(located[1]["locations"][0]["video_lora"])
